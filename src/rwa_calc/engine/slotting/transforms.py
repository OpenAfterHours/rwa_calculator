"""
Slotting calculation transforms for Specialised Lending.

Plain typed functions over Polars LazyFrames and expressions implementing the
supervisory slotting approach. ``SlottingCalculator`` composes them via
``LazyFrame.pipe`` in regulatory order; tests call them directly.

Pipeline position:
    CRMProcessor -> SlottingCalculator -> OutputAggregator

Key responsibilities:
- Column preparation (maturity derivation, slotting metadata defaults)
- Risk weight lookup by category / HVCRE flag / maturity (CRR Art. 153(5))
- RWA calculation (EAD x RW, pre-supporting-factor)
- Expected loss rates (Art. 158(6) Table B) and EL shortfall/excess (Art. 159)
- Audit trail construction

CRR weights vary by maturity (<2.5yr vs >=2.5yr) per Art. 153(5); the EU HVCRE
Table 2 was not onshored, so ``is_hvcre`` is ignored under CRR. Basel 3.1
weights vary by HVCRE flag and PF pre-operational status per PRA PS1/26
Art. 153(5) Table A.

Usage:
    from rwa_calc.engine.slotting.transforms import (
        apply_slotting_weights,
        calculate_rwa,
        prepare_columns,
    )

    result = (
        exposures.pipe(prepare_columns, config)
        .pipe(apply_slotting_weights, config)
        .pipe(calculate_rwa)
    )

References:
- CRR Art. 153(5): Supervisory slotting approach (Tables 1 & 2)
- CRR Art. 158(6), Table B: Expected loss rates for slotting
- CRR Art. 159: EL shortfall/excess treatment
- BCBS CRE33: Basel 3.1 specialised lending slotting
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from polars import col, lit
from watchfire import cites

from rwa_calc.contracts.errors import (
    ERROR_MISSING_EXPECTED_LOSS,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
)
from rwa_calc.data.tables.b31_slotting import (
    B31_SLOTTING_EL_RATES,
    B31_SLOTTING_EL_RATES_HVCRE,
    B31_SLOTTING_EL_RATES_SHORT,
    B31_SLOTTING_RISK_WEIGHTS,
    B31_SLOTTING_RISK_WEIGHTS_HVCRE,
    B31_SLOTTING_RISK_WEIGHTS_HVCRE_SHORT,
    B31_SLOTTING_RISK_WEIGHTS_PREOP,
    B31_SLOTTING_RISK_WEIGHTS_SHORT,
)
from rwa_calc.data.tables.crr_slotting import (
    SLOTTING_EL_RATES,
    SLOTTING_EL_RATES_HVCRE,
    SLOTTING_EL_RATES_SHORT,
    SLOTTING_RISK_WEIGHTS,
    SLOTTING_RISK_WEIGHTS_HVCRE,
    SLOTTING_RISK_WEIGHTS_HVCRE_SHORT,
    SLOTTING_RISK_WEIGHTS_SHORT,
)
from rwa_calc.engine.utils import exact_fractional_years_expr

if TYPE_CHECKING:
    from decimal import Decimal

    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import SlottingCategory

logger = logging.getLogger(__name__)

# Threshold for short maturity classification under CRR Art. 153(5)
_SHORT_MATURITY_THRESHOLD_YEARS = 2.5


def _to_float_map(weights: dict[SlottingCategory, Decimal]) -> dict[str, float]:
    """Convert Decimal enum-keyed weights to str/float dict for Polars replace_strict."""
    return {cat.value: float(w) for cat, w in weights.items()}


# =============================================================================
# RISK WEIGHT CONSTANTS — sourced from data/tables/
# =============================================================================

_SLOTTING_WEIGHTS: dict[str, dict[str, dict[str, float]]] = {
    "crr": {
        "base": _to_float_map(SLOTTING_RISK_WEIGHTS),
        "short": _to_float_map(SLOTTING_RISK_WEIGHTS_SHORT),
        "hvcre": _to_float_map(SLOTTING_RISK_WEIGHTS_HVCRE),
        "hvcre_short": _to_float_map(SLOTTING_RISK_WEIGHTS_HVCRE_SHORT),
    },
    "basel_3_1": {
        "base": _to_float_map(B31_SLOTTING_RISK_WEIGHTS),
        "short": _to_float_map(B31_SLOTTING_RISK_WEIGHTS_SHORT),
        "preop": _to_float_map(B31_SLOTTING_RISK_WEIGHTS_PREOP),
        "hvcre": _to_float_map(B31_SLOTTING_RISK_WEIGHTS_HVCRE),
        "hvcre_short": _to_float_map(B31_SLOTTING_RISK_WEIGHTS_HVCRE_SHORT),
    },
}

# EL rate constants — sourced from data/tables/ (Art. 158(6) Table B)
# EL rates are maturity-dependent for non-HVCRE under both CRR and B31.
# HVCRE EL rates are flat (same for both maturities).
_SLOTTING_EL_RATES: dict[str, dict[str, dict[str, float]]] = {
    "crr": {
        "base": _to_float_map(SLOTTING_EL_RATES),
        "short": _to_float_map(SLOTTING_EL_RATES_SHORT),
        "hvcre": _to_float_map(SLOTTING_EL_RATES_HVCRE),
        "hvcre_short": _to_float_map(SLOTTING_EL_RATES_HVCRE),  # same as hvcre (flat)
    },
    "basel_3_1": {
        "base": _to_float_map(B31_SLOTTING_EL_RATES),
        "short": _to_float_map(B31_SLOTTING_EL_RATES_SHORT),
        "hvcre": _to_float_map(B31_SLOTTING_EL_RATES_HVCRE),
        "hvcre_short": _to_float_map(B31_SLOTTING_EL_RATES_HVCRE),  # same as hvcre (flat)
    },
}


# =============================================================================
# LAZYFRAME TRANSFORMS
# =============================================================================


def prepare_columns(lf: pl.LazyFrame, config: CalculationConfig | None = None) -> pl.LazyFrame:
    """Ensure all required columns exist with defaults.

    When ``config`` is provided and ``maturity_date`` exists in the frame,
    ``is_short_maturity`` is derived automatically:
        remaining_maturity = (maturity_date - reporting_date) in years
        is_short_maturity  = remaining_maturity < 2.5

    A pre-existing ``is_short_maturity`` column is never overwritten so that
    callers can supply an explicit override.

    Args:
        lf: Slotting exposures frame.
        config: Calculation configuration (provides reporting_date for maturity calc).
    """
    schema = lf.collect_schema()

    to_add: list[pl.Expr] = []

    to_add.extend(_maturity_columns(schema, config))
    to_add.extend(_default_columns(schema))

    return lf.with_columns(to_add) if to_add else lf


@cites("CRR Art. 153(5)")
def apply_slotting_weights(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Apply slotting risk weights based on framework, category, HVCRE flag, and maturity."""
    is_crr = config.is_crr

    if is_crr:
        rw_expr = lookup_rw(
            col("slotting_category"),
            is_crr=True,
            is_hvcre=col("is_hvcre"),
            is_short=col("is_short_maturity"),
        )
    else:
        rw_expr = lookup_rw(
            col("slotting_category"),
            is_crr=False,
            is_hvcre=col("is_hvcre"),
            is_short=col("is_short_maturity"),
            is_preop=col("is_pre_operational"),
        )

    return lf.with_columns(risk_weight=rw_expr)


def calculate_rwa(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Calculate RWA = EAD x Risk Weight (pre-supporting-factor)."""
    rwa = col("ead_final") * col("risk_weight")
    return lf.with_columns(rwa=rwa)


def apply_el_rates(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Apply slotting expected loss rates per Art. 158(6) Table B.

    Produces:
        slotting_el_rate: The EL rate for this category/maturity/HVCRE combination
        expected_loss: EL rate x EAD (the expected loss amount)
    """
    is_crr = config.is_crr
    # EL rates are always maturity-dependent (even under B31 where RW is not)
    el_rate_expr = lookup_el_rate(
        col("slotting_category"),
        is_crr=is_crr,
        is_hvcre=col("is_hvcre"),
        is_short=col("is_short_maturity"),
    )
    return lf.with_columns(
        slotting_el_rate=el_rate_expr,
        expected_loss=el_rate_expr * col("ead_final"),
    )


def compute_el_shortfall_excess(
    lf: pl.LazyFrame,
    *,
    errors: list[CalculationError] | None = None,
) -> pl.LazyFrame:
    """Compute EL shortfall and excess for slotting exposures.

    Compares expected loss against Art. 159(1) Pool B. Same logic as IRB
    (CRR Art. 158-159) but using slotting-specific EL rates.

    Pool B per Art. 159(1) includes provisions (a+b), AVAs (c), and
    other own funds reductions (d).

    Args:
        lf: Slotting exposures frame with expected_loss computed.
        errors: Optional error accumulator. Receives a warning if
            ``expected_loss`` column is absent (EL not yet computed).

    Produces:
        el_shortfall: max(0, expected_loss - pool_b)
        el_excess:    max(0, pool_b - expected_loss)
    """
    schema = lf.collect_schema()
    cols = schema.names()

    if "expected_loss" not in cols:
        if errors is not None:
            errors.append(
                CalculationError(
                    code=ERROR_MISSING_EXPECTED_LOSS,
                    message=(
                        "expected_loss column absent in slotting exposures — "
                        "EL shortfall/excess defaulted to zero. "
                        "T2 credit cap and CET1 deduction may be affected."
                    ),
                    severity=ErrorSeverity.WARNING,
                    category=ErrorCategory.DATA_QUALITY,
                    field_name="expected_loss",
                    regulatory_reference="CRR Art. 158-159",
                )
            )
        return lf.with_columns(
            el_shortfall=lit(0.0),
            el_excess=lit(0.0),
        )

    el = col("expected_loss").fill_null(0.0)
    prov = col("provision_allocated").fill_null(0.0)
    # Art. 159(1)(c): Additional value adjustments (AVAs per Art. 34)
    ava = col("ava_amount").fill_null(0.0)
    # Art. 159(1)(d): Other own funds reductions
    other_ofr = col("other_own_funds_reductions").fill_null(0.0)
    pool_b = prov + ava + other_ofr

    return lf.with_columns(
        el_shortfall=pl.max_horizontal(lit(0.0), el - pool_b),
        el_excess=pl.max_horizontal(lit(0.0), pool_b - el),
    )


def apply_all(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Apply full slotting calculation pipeline including EL."""
    return (
        lf.pipe(prepare_columns, config)
        .pipe(apply_slotting_weights, config)
        .pipe(calculate_rwa)
        .pipe(apply_el_rates, config)
        .pipe(compute_el_shortfall_excess)
    )


def build_audit(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Build slotting calculation audit trail."""
    schema = lf.collect_schema()

    base_cols = ["exposure_reference"]
    optional_cols = [
        "counterparty_reference",
        "exposure_class",
        "sl_type",
        "slotting_category",
        "is_hvcre",
        "is_short_maturity",
        "remaining_maturity_years",
        "ead_final",
        "risk_weight",
        "rwa",
        "supporting_factor",
    ]

    select_cols = [c for c in base_cols + optional_cols if c in schema]
    audit = lf.select(select_cols)

    if "rwa" in schema:
        audit = audit.with_columns(
            slotting_calculation=pl.concat_str(
                [
                    lit("Slotting: Category="),
                    col("slotting_category"),
                    pl.when(col("is_hvcre")).then(lit(" (HVCRE)")).otherwise(lit("")),
                    lit(", RW="),
                    (col("risk_weight") * 100).round(0).cast(pl.String),
                    lit("%, RWA="),
                    col("rwa").round(0).cast(pl.String),
                ]
            )
        )

    return audit


# =============================================================================
# EXPRESSION TRANSFORMS
# =============================================================================


def lookup_rw(
    category: pl.Expr,
    *,
    is_crr: bool = True,
    is_hvcre: bool | pl.Expr = False,
    is_short: bool | pl.Expr = False,
    is_preop: bool | pl.Expr = False,
) -> pl.Expr:
    """Look up risk weight based on slotting category."""
    cat = category.str.to_lowercase()

    is_hvcre_expr = lit(is_hvcre) if isinstance(is_hvcre, bool) else is_hvcre
    is_short_expr = lit(is_short) if isinstance(is_short, bool) else is_short
    is_preop_expr = lit(is_preop) if isinstance(is_preop, bool) else is_preop

    if is_crr:
        # UK CRR Art. 153(5) has a single slotting weight table — the EU
        # CRR HVCRE Table 2 was not onshored. is_hvcre is preserved on the
        # row for audit but ignored for risk-weight lookup; all SL picks
        # the Table 1 weight, with the only split being maturity (<2.5yr).
        weights = _SLOTTING_WEIGHTS["crr"]
        return (
            pl.when(is_short_expr)
            .then(_map_category(cat, weights["short"]))
            .otherwise(_map_category(cat, weights["base"]))
        )
    else:
        weights = _SLOTTING_WEIGHTS["basel_3_1"]
        # PRA PS1/26 Art. 153(5)(d) Table A: when remaining maturity < 2.5
        # years, both non-HVCRE and HVCRE pick the col-A/C subgrade table.
        # HVCRE short must fire before the generic HVCRE catch-all so the
        # is_short flag is honoured for HVCRE exposures.
        return (
            pl.when(is_hvcre_expr & is_short_expr)
            .then(_map_category(cat, weights["hvcre_short"]))
            .when(is_hvcre_expr)
            .then(_map_category(cat, weights["hvcre"]))
            .when(is_preop_expr)
            .then(_map_category(cat, weights["preop"]))
            .when(is_short_expr)
            .then(_map_category(cat, weights["short"]))
            .otherwise(_map_category(cat, weights["base"]))
        )


def lookup_el_rate(
    category: pl.Expr,
    *,
    is_crr: bool = True,
    is_hvcre: bool | pl.Expr = False,
    is_short: bool | pl.Expr = False,
) -> pl.Expr:
    """Look up expected loss rate per Art. 158(6) Table B.

    Under UK CRR Art. 158(6) Table B has a single specialised-lending
    column — the EU HVCRE row was not onshored, so ``is_hvcre`` is
    ignored on the CRR branch. Under Basel 3.1, HVCRE EL rates are flat
    (same value for both maturities) while non-HVCRE is maturity-split.
    """
    cat = category.str.to_lowercase()

    is_hvcre_expr = lit(is_hvcre) if isinstance(is_hvcre, bool) else is_hvcre
    is_short_expr = lit(is_short) if isinstance(is_short, bool) else is_short

    if is_crr:
        # UK CRR: ignore is_hvcre — single Table B column, maturity-split only.
        rates = _SLOTTING_EL_RATES["crr"]
        return (
            pl.when(is_short_expr)
            .then(_map_category(cat, rates["short"]))
            .otherwise(_map_category(cat, rates["base"]))
        )

    rates = _SLOTTING_EL_RATES["basel_3_1"]
    return (
        pl.when(is_hvcre_expr.not_() & is_short_expr.not_())
        .then(_map_category(cat, rates["base"]))
        .when(is_hvcre_expr.not_() & is_short_expr)
        .then(_map_category(cat, rates["short"]))
        .when(is_hvcre_expr & is_short_expr.not_())
        .then(_map_category(cat, rates["hvcre"]))
        .otherwise(_map_category(cat, rates["hvcre_short"]))
    )


# =============================================================================
# PRIVATE HELPERS
# =============================================================================


def _map_category(cat_expr: pl.Expr, weights: dict[str, float]) -> pl.Expr:
    """Map category name to weight/rate using replace_strict."""
    return cat_expr.replace_strict(
        old=list(weights.keys()),
        new=list(weights.values()),
        default=lit(weights["satisfactory"]),
        return_dtype=pl.Float64,
    )


def _maturity_columns(schema: pl.Schema, config: CalculationConfig | None) -> list[pl.Expr]:
    """Derive is_short_maturity and remaining_maturity_years column expressions."""
    needs_short = "is_short_maturity" not in schema

    if config is None:
        # No config — conservative default when missing.
        return [lit(False).alias("is_short_maturity")] if needs_short else []

    remaining = exact_fractional_years_expr(config.reporting_date, "maturity_date")

    if needs_short:
        return [
            remaining.alias("remaining_maturity_years"),
            pl.when(col("maturity_date").is_not_null())
            .then(remaining < _SHORT_MATURITY_THRESHOLD_YEARS)
            .otherwise(lit(False))
            .alias("is_short_maturity"),
        ]

    if "remaining_maturity_years" not in schema:
        return [remaining.alias("remaining_maturity_years")]

    return []


def _default_columns(schema: pl.Schema) -> list[pl.Expr]:
    """Provide default values for missing slotting metadata columns.

    ``is_pre_operational`` is the only non-contract input here; the
    crm_exit edge guarantees ``slotting_category`` / ``is_hvcre`` /
    ``sl_type`` are always present.
    """
    defaults = {
        "is_pre_operational": lit(False),
    }
    return [expr.alias(name) for name, expr in defaults.items() if name not in schema]
