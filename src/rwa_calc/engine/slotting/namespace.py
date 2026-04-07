"""
Polars LazyFrame namespaces for Slotting calculations.

Provides fluent API for Specialised Lending slotting approach via registered namespaces:
- `lf.slotting.prepare_columns(config)` - Ensure required columns exist
- `lf.slotting.apply_slotting_weights(config)` - Apply slotting risk weights
- `lf.slotting.calculate_rwa()` - Calculate RWA

CRR weights vary by maturity (<2.5yr vs >=2.5yr) and HVCRE flag per Art. 153(5).
Basel 3.1 weights vary by HVCRE flag and PF pre-operational status per BCBS CRE33.

Usage:
    import polars as pl
    from rwa_calc.contracts.config import CalculationConfig
    import rwa_calc.engine.slotting.namespace  # Register namespace

    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    result = (exposures
        .slotting.prepare_columns(config)
        .slotting.apply_slotting_weights(config)
        .slotting.calculate_rwa()
    )

References:
- CRR Art. 153(5): Supervisory slotting approach (Tables 1 & 2)
- BCBS CRE33: Basel 3.1 specialised lending slotting
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from polars import col, lit

from rwa_calc.data.tables.b31_slotting import (
    B31_SLOTTING_EL_RATES,
    B31_SLOTTING_EL_RATES_HVCRE,
    B31_SLOTTING_EL_RATES_SHORT,
    B31_SLOTTING_RISK_WEIGHTS,
    B31_SLOTTING_RISK_WEIGHTS_HVCRE,
    B31_SLOTTING_RISK_WEIGHTS_PREOP,
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
        "preop": _to_float_map(B31_SLOTTING_RISK_WEIGHTS_PREOP),
        "hvcre": _to_float_map(B31_SLOTTING_RISK_WEIGHTS_HVCRE),
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
# LAZYFRAME NAMESPACE
# =============================================================================


@pl.api.register_lazyframe_namespace("slotting")
class SlottingLazyFrame:
    """
    Slotting calculation namespace for Polars LazyFrames.

    Provides fluent API for Specialised Lending slotting approach.

    Example:
        result = (exposures
            .slotting.prepare_columns(config)
            .slotting.apply_slotting_weights(config)
            .slotting.calculate_rwa()
        )
    """

    def __init__(self, lf: pl.LazyFrame) -> None:
        self._lf = lf

    def prepare_columns(self, config: CalculationConfig | None = None) -> pl.LazyFrame:
        """Ensure all required columns exist with defaults.

        When ``config`` is provided and ``maturity_date`` exists in the frame,
        ``is_short_maturity`` is derived automatically:
            remaining_maturity = (maturity_date - reporting_date) in years
            is_short_maturity  = remaining_maturity < 2.5

        A pre-existing ``is_short_maturity`` column is never overwritten so that
        callers can supply an explicit override.

        Args:
            config: Calculation configuration (provides reporting_date for maturity calc).
        """
        schema = self._lf.collect_schema()

        # Define default columns to add if they don't exist
        defaults = {
            "slotting_category": lit("satisfactory"),
            "is_hvcre": lit(False),
            "sl_type": lit("project_finance"),
            "is_pre_operational": lit(False),
        }

        # Add EAD logic specifically
        to_add = []
        if "ead_final" not in schema:
            ead_col = (
                col("ead")
                if "ead" in schema
                else col("ead_pre_crm")
                if "ead_pre_crm" in schema
                else lit(0.0)
            )
            to_add.append(ead_col.alias("ead_final"))

        # Derive is_short_maturity from maturity_date when not already present
        if "is_short_maturity" not in schema:
            if config is not None and "maturity_date" in schema:
                remaining = exact_fractional_years_expr(config.reporting_date, "maturity_date")
                to_add.append(
                    remaining.alias("remaining_maturity_years"),
                )
                to_add.append(
                    pl.when(col("maturity_date").is_not_null())
                    .then(remaining < _SHORT_MATURITY_THRESHOLD_YEARS)
                    .otherwise(lit(False))
                    .alias("is_short_maturity"),
                )
            else:
                # No config or no maturity_date — conservative default (long maturity)
                to_add.append(lit(False).alias("is_short_maturity"))

        # Add remaining_maturity_years for audit even when is_short_maturity exists
        if (
            "remaining_maturity_years" not in schema
            and "is_short_maturity" in schema
            and config is not None
            and "maturity_date" in schema
        ):
            remaining = exact_fractional_years_expr(config.reporting_date, "maturity_date")
            to_add.append(remaining.alias("remaining_maturity_years"))

        # Add missing default columns
        for name, expr in defaults.items():
            if name not in schema:
                to_add.append(expr.alias(name))

        return self._lf.with_columns(to_add) if to_add else self._lf

    def apply_slotting_weights(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply slotting risk weights based on framework, category, HVCRE flag, and maturity."""
        is_crr = config.is_crr

        if is_crr:
            rw_expr = col("slotting_category").slotting.lookup_rw(
                is_crr=True,
                is_hvcre=col("is_hvcre"),
                is_short=col("is_short_maturity"),
            )
        else:
            rw_expr = col("slotting_category").slotting.lookup_rw(
                is_crr=False,
                is_hvcre=col("is_hvcre"),
                is_preop=col("is_pre_operational"),
            )

        return self._lf.with_columns(risk_weight=rw_expr)

    def calculate_rwa(self) -> pl.LazyFrame:
        """Calculate RWA = EAD x Risk Weight (pre-supporting-factor)."""
        rwa = col("ead_final") * col("risk_weight")
        return self._lf.with_columns(rwa=rwa)

    def apply_el_rates(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply slotting expected loss rates per Art. 158(6) Table B.

        Produces:
            slotting_el_rate: The EL rate for this category/maturity/HVCRE combination
            expected_loss: EL rate x EAD (the expected loss amount)
        """
        is_crr = config.is_crr
        # EL rates are always maturity-dependent (even under B31 where RW is not)
        el_rate_expr = col("slotting_category").slotting.lookup_el_rate(
            is_crr=is_crr,
            is_hvcre=col("is_hvcre"),
            is_short=col("is_short_maturity"),
        )
        return self._lf.with_columns(
            slotting_el_rate=el_rate_expr,
            expected_loss=el_rate_expr * col("ead_final"),
        )

    def compute_el_shortfall_excess(self) -> pl.LazyFrame:
        """Compute EL shortfall and excess for slotting exposures.

        Compares expected loss against Art. 159(1) Pool B. Same logic as IRB
        (CRR Art. 158-159) but using slotting-specific EL rates.

        Pool B per Art. 159(1) includes provisions (a+b), AVAs (c), and
        other own funds reductions (d).

        Produces:
            el_shortfall: max(0, expected_loss - pool_b)
            el_excess:    max(0, pool_b - expected_loss)
        """
        schema = self._lf.collect_schema()
        cols = schema.names()

        if "expected_loss" not in cols:
            return self._lf.with_columns(
                el_shortfall=lit(0.0),
                el_excess=lit(0.0),
            )

        el = col("expected_loss").fill_null(0.0)
        prov = (
            col("provision_allocated").fill_null(0.0) if "provision_allocated" in cols else lit(0.0)
        )
        # Art. 159(1)(c): Additional value adjustments (AVAs per Art. 34)
        ava = col("ava_amount").fill_null(0.0) if "ava_amount" in cols else lit(0.0)
        # Art. 159(1)(d): Other own funds reductions
        other_ofr = (
            col("other_own_funds_reductions").fill_null(0.0)
            if "other_own_funds_reductions" in cols
            else lit(0.0)
        )
        pool_b = prov + ava + other_ofr

        return self._lf.with_columns(
            el_shortfall=pl.max_horizontal(lit(0.0), el - pool_b),
            el_excess=pl.max_horizontal(lit(0.0), pool_b - el),
        )

    def apply_all(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply full slotting calculation pipeline including EL."""
        return (
            self.prepare_columns(config)
            .slotting.apply_slotting_weights(config)
            .slotting.calculate_rwa()
            .slotting.apply_el_rates(config)
            .slotting.compute_el_shortfall_excess()
        )

    def build_audit(self) -> pl.LazyFrame:
        """Build slotting calculation audit trail."""
        schema = self._lf.collect_schema()

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
        audit = self._lf.select(select_cols)

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
# EXPRESSION NAMESPACE
# =============================================================================


@pl.api.register_expr_namespace("slotting")
class SlottingExpr:
    """
    Slotting calculation namespace for Polars Expressions.

    Provides column-level operations for slotting calculations.

    Example:
        df.with_columns(
            pl.col("slotting_category").slotting.lookup_rw(is_crr=True),
        )
    """

    def __init__(self, expr: pl.Expr) -> None:
        self._expr = expr

    def lookup_rw(
        self,
        is_crr: bool = True,
        is_hvcre: bool | pl.Expr = False,
        is_short: bool | pl.Expr = False,
        is_preop: bool | pl.Expr = False,
    ) -> pl.Expr:
        """Look up risk weight based on slotting category."""
        cat = self._expr.str.to_lowercase()

        is_hvcre_expr = lit(is_hvcre) if isinstance(is_hvcre, bool) else is_hvcre
        is_short_expr = lit(is_short) if isinstance(is_short, bool) else is_short
        is_preop_expr = lit(is_preop) if isinstance(is_preop, bool) else is_preop

        if is_crr:
            weights = _SLOTTING_WEIGHTS["crr"]
            return (
                pl.when(is_hvcre_expr.not_() & is_short_expr.not_())
                .then(self._map_category(cat, weights["base"]))
                .when(is_hvcre_expr.not_() & is_short_expr)
                .then(self._map_category(cat, weights["short"]))
                .when(is_hvcre_expr & is_short_expr.not_())
                .then(self._map_category(cat, weights["hvcre"]))
                .otherwise(self._map_category(cat, weights["hvcre_short"]))
            )
        else:
            weights = _SLOTTING_WEIGHTS["basel_3_1"]
            return (
                pl.when(is_hvcre_expr)
                .then(self._map_category(cat, weights["hvcre"]))
                .when(is_preop_expr)
                .then(self._map_category(cat, weights["preop"]))
                .otherwise(self._map_category(cat, weights["base"]))
            )

    def lookup_el_rate(
        self,
        is_crr: bool = True,
        is_hvcre: bool | pl.Expr = False,
        is_short: bool | pl.Expr = False,
    ) -> pl.Expr:
        """Look up expected loss rate per Art. 158(6) Table B.

        EL rates are always maturity-dependent for non-HVCRE (both CRR and B31).
        HVCRE EL rates are flat (same for both maturities).
        """
        cat = self._expr.str.to_lowercase()

        is_hvcre_expr = lit(is_hvcre) if isinstance(is_hvcre, bool) else is_hvcre
        is_short_expr = lit(is_short) if isinstance(is_short, bool) else is_short

        fw_key = "crr" if is_crr else "basel_3_1"
        rates = _SLOTTING_EL_RATES[fw_key]

        return (
            pl.when(is_hvcre_expr.not_() & is_short_expr.not_())
            .then(self._map_category(cat, rates["base"]))
            .when(is_hvcre_expr.not_() & is_short_expr)
            .then(self._map_category(cat, rates["short"]))
            .when(is_hvcre_expr & is_short_expr.not_())
            .then(self._map_category(cat, rates["hvcre"]))
            .otherwise(self._map_category(cat, rates["hvcre_short"]))
        )

    @staticmethod
    def _map_category(cat_expr: pl.Expr, weights: dict[str, float]) -> pl.Expr:
        """Map category name to weight/rate using replace_strict."""
        return cat_expr.replace_strict(
            old=list(weights.keys()),
            new=list(weights.values()),
            default=lit(weights["satisfactory"]),
            return_dtype=pl.Float64,
        )
