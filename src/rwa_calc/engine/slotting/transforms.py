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
- The short-maturity band decision, sealed as
  ``slotting_short_maturity_rw_applied`` for the EL lookup and reporting
- RWA calculation (EAD x RW, pre-supporting-factor)
- Expected loss rates (Art. 158(6) Table B) and EL shortfall/excess (Art. 159)
- Audit trail construction

CRR weights vary by maturity (<2.5yr vs >=2.5yr) per Art. 153(5), and that
Table 1 split is mandatory ("shall"); the EU HVCRE Table 2 was not onshored, so
``is_hvcre`` is ignored under CRR. Basel 3.1 weights vary by HVCRE flag per PRA
PS1/26 Art. 153(5) Table A. Table A has two columns for 'Strong' (A / B) and two
for 'Good' (C / D) and ONE for each of 'Satisfactory', 'Weak' and 'Default'; the
'Strong' / 'Good' weight varies by maturity ONLY on the firm's Art. 153(5)(d)
election (``CalculationConfig.slotting_short_maturity_election``): column B /
column D is the Art. 153(5)(c) default, column A / column C the election. The
Art. 158(6) EL rate follows the column applied in both regimes.

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
- PRA PS1/26 Art. 153(5)(c)-(d) Table A; Art. 158(6) Table B
- BCBS CRE33: Basel 3.1 specialised lending slotting
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, cast

import polars as pl
from polars import col, lit
from watchfire import cites

from rwa_calc.contracts.errors import (
    ERROR_MISSING_EXPECTED_LOSS,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
)
from rwa_calc.domain.enums import SlottingCategory
from rwa_calc.engine.sa.rw_adjustments import (
    apply_guarantee_substitution as sa_apply_guarantee_substitution,
)
from rwa_calc.engine.utils import exact_fractional_years_expr
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.compile import lookup_float_map, scalar_value
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.model import LookupTable
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

# Slotting packs resolved once at module load. The slotting RW (Art. 153(5)) and
# EL (Art. 158(6)) tables + the 2.5y short-maturity threshold are pack-sourced; the
# b31 pack overrides the crr slotting_* entries via overlay.
_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

_SHORT_MATURITY_THRESHOLD_YEARS = scalar_value(
    _CRR_PACK.scalar_param("slotting_short_maturity_threshold_years")
)


def _to_float_map(table: LookupTable) -> dict[str, float]:
    """String-keyed slotting LookupTable -> {category: float} for Polars replace_strict."""
    return cast("dict[str, float]", lookup_float_map(table))


# =============================================================================
# RISK WEIGHT CONSTANTS — sourced from the rulepack (Art. 153(5) Table A)
# =============================================================================

_SLOTTING_WEIGHTS: dict[str, dict[str, dict[str, float]]] = {
    "crr": {
        "base": _to_float_map(_CRR_PACK.lookup("slotting_rw_base")),
        "short": _to_float_map(_CRR_PACK.lookup("slotting_rw_short")),
        "hvcre": _to_float_map(_CRR_PACK.lookup("slotting_rw_hvcre")),
        "hvcre_short": _to_float_map(_CRR_PACK.lookup("slotting_rw_hvcre_short")),
    },
    "basel_3_1": {
        "base": _to_float_map(_B31_PACK.lookup("slotting_rw_base")),
        "short": _to_float_map(_B31_PACK.lookup("slotting_rw_short")),
        "hvcre": _to_float_map(_B31_PACK.lookup("slotting_rw_hvcre")),
        "hvcre_short": _to_float_map(_B31_PACK.lookup("slotting_rw_hvcre_short")),
    },
}

# EL rate constants — sourced from the rulepack (Art. 158(6) Table B).
# The non-HVCRE EL rate follows the short-maturity band decision in both
# regimes (Art. 158(6): the Table B cell matching the Table A weight assigned).
# HVCRE EL rates are flat (same for both maturities).
_SLOTTING_EL_RATES: dict[str, dict[str, dict[str, float]]] = {
    "crr": {
        "base": _to_float_map(_CRR_PACK.lookup("slotting_el_base")),
        "short": _to_float_map(_CRR_PACK.lookup("slotting_el_short")),
        "hvcre": _to_float_map(_CRR_PACK.lookup("slotting_el_hvcre")),
        "hvcre_short": _to_float_map(_CRR_PACK.lookup("slotting_el_hvcre")),  # flat
    },
    "basel_3_1": {
        "base": _to_float_map(_B31_PACK.lookup("slotting_el_base")),
        "short": _to_float_map(_B31_PACK.lookup("slotting_el_short")),
        "hvcre": _to_float_map(_B31_PACK.lookup("slotting_el_hvcre")),
        "hvcre_short": _to_float_map(_B31_PACK.lookup("slotting_el_hvcre")),  # flat
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
@cites("PS1/26, paragraph 153")
def apply_slotting_weights(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Apply slotting risk weights by framework, category, HVCRE flag and maturity.

    Produces:
        slotting_short_maturity_rw_applied: True when the leg sits in the
            short-maturity band of Art. 153(5) — see ``_short_maturity_rw_applied``
            for the rule per regime and per grade. ``is_short_maturity`` stays the
            plain maturity fact; this is the band the EL lookup and the C 08.06 /
            CR10 rows read. It differs from the fact on one population only: a
            Basel 3.1 short-dated 'Strong' / 'Good' leg of a firm without the
            Art. 153(5)(d) election (False here, column B / D).
        risk_weight: the Art. 153(5) Table 1 / Table A weight.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    is_crr = not resolved_pack.feature("slotting_revised_tables")
    applied = _short_maturity_rw_applied(config, is_crr=is_crr)
    rw_expr = lookup_rw(
        col("slotting_category"),
        is_crr=is_crr,
        is_hvcre=col("is_hvcre"),
        is_short=applied,
    )
    return lf.with_columns(
        applied.alias("slotting_short_maturity_rw_applied"),
        risk_weight=rw_expr,
    )


def calculate_rwa(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Calculate RWA = EAD x Risk Weight (pre-supporting-factor)."""
    rwa = col("ead_final") * col("risk_weight")
    return lf.with_columns(rwa=rwa)


@cites("CRR Art. 235")
@cites("PS1/26, paragraph 235")
def apply_guarantee_substitution(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Risk-Weight Substitution Method on slotting legs (Art. 235(1)).

    The CRM stage already splits guaranteed slotting exposures into
    physical ``__G_``/``__REM`` legs and assigns ``guarantor_approach="sa"``
    (slotting has no PD, so parameter substitution never applies); this
    step is the previously-MISSING consumer: the covered leg takes the
    guarantor's SA risk weight when beneficial, via the SAME shared
    substitution step the SA branch runs (identical beneficial gate,
    multi-guarantor redistribution and audit columns — the F8
    ``guarantee_benefit_rw`` snapshot lands here, on the SLOTTING borrower
    basis, before supporting factors and the portfolio floor).

    Gated by the cited pack Feature ``slotting_guarantee_substitution``
    (recorded decision 2026-07-12: enabled under BOTH regimes — PS1/26
    mandates RWSM; the CRR-side basis is recorded as unsettled on the
    Feature's citation). Runs only when the CRM guarantee sub-step ran
    (the SA step's ``guarantor_entity_type`` sentinel gate).
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    if not resolved_pack.feature("slotting_guarantee_substitution"):
        return lf
    return sa_apply_guarantee_substitution(lf, config, pack=resolved_pack)


@cites("PS1/26, paragraph 235")
def zero_covered_expected_loss(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Zero the covered leg's slotting EL (Art. 235(1A)).

    The substituted covered part is an exposure to a guarantor treated
    under SA, which carries no slotting EL — leaving the borrower's
    Art. 158(6) EL on the ``__G_`` leg would double-count it into the
    Art. 159 shortfall pool (mirrors the IRB SA-guarantor precedent,
    ``engine/irb/guarantee.py::_adjust_expected_loss``). Applies ONLY to
    beneficially-substituted legs; non-beneficial and retained legs keep
    the borrower slotting EL.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    if not resolved_pack.feature("slotting_guarantee_substitution"):
        return lf
    cols = lf.collect_schema().names()
    if "is_guarantee_beneficial" not in cols or "guaranteed_portion" not in cols:
        return lf
    covered = pl.col("is_guarantee_beneficial") & (pl.col("guaranteed_portion") > 0)
    return lf.with_columns(
        pl.when(covered)
        .then(pl.lit(0.0))
        .otherwise(pl.col("slotting_el_rate"))
        .alias("slotting_el_rate"),
        pl.when(covered)
        .then(pl.lit(0.0))
        .otherwise(pl.col("expected_loss"))
        .alias("expected_loss"),
    )


@cites("PS1/26, paragraph 158")
def apply_el_rates(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Apply slotting expected loss rates per Art. 158(6) Table B.

    Art. 158(6) takes "the EL value in the cell of Table B that is in the
    corresponding row and column to the risk weight value in Table A that the
    institution has assigned", so the rate is keyed on the SAME short-maturity
    band decision ``apply_slotting_weights`` makes — not on raw maturity. A
    Basel 3.1 short-dated Strong leg without the Art. 153(5)(d) election takes
    column B's 0.4%, not column A's 0%.

    Produces:
        slotting_el_rate: The EL rate for this category/column/HVCRE combination
        expected_loss: EL rate x EAD (the expected loss amount)
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    is_crr = not resolved_pack.feature("slotting_revised_tables")
    el_rate_expr = lookup_el_rate(
        col("slotting_category"),
        is_crr=is_crr,
        is_hvcre=col("is_hvcre"),
        is_short=_short_maturity_rw_applied(config, is_crr=is_crr),
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
        "slotting_short_maturity_rw_applied",
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
) -> pl.Expr:
    """Look up risk weight based on slotting category.

    ``is_short`` selects the short-maturity weights: CRR Table 1's "less than
    2,5 years" row, or PS1/26 Table A column A / column C for 'Strong' / 'Good'
    (the 'Satisfactory' / 'Weak' / 'Default' short and base weights are the same
    single Table A column). It is the band decision, not the raw maturity fact:
    under Basel 3.1 a short-dated 'Strong' / 'Good' leg is short only on the
    Art. 153(5)(d) election (``apply_slotting_weights``).
    """
    cat = category.str.to_lowercase()

    is_hvcre_expr = lit(is_hvcre) if isinstance(is_hvcre, bool) else is_hvcre
    is_short_expr = lit(is_short) if isinstance(is_short, bool) else is_short

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
        # PRA PS1/26 Art. 153(5)(c)/(d) Table A: column B / D by default; the
        # column-A/C table where the caller's is_short holds (for 'Strong' /
        # 'Good', the (d) election on a < 2.5-year leg; the other grades' single
        # column is in both tables), for non-HVCRE and HVCRE alike. HVCRE short
        # must fire before the generic HVCRE catch-all. There is no
        # pre-operational arm: PRA did not adopt the CRE33 pre-op PF table, and
        # (d) covers "all categories", pre-operational PF included.
        return (
            pl.when(is_hvcre_expr & is_short_expr)
            .then(_map_category(cat, weights["hvcre_short"]))
            .when(is_hvcre_expr)
            .then(_map_category(cat, weights["hvcre"]))
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
    (same value in columns A-D) while non-HVCRE splits A/C from B/D; the
    'Satisfactory' / 'Weak' / 'Default' rates are one cell each, in both bands.
    ``is_short`` is the short-maturity band decision, exactly as for
    ``lookup_rw`` — the EL cell must sit in the column the weight came from.
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


def _short_maturity_rw_applied(config: CalculationConfig, *, is_crr: bool) -> pl.Expr:
    """Whether a leg sits in the short-maturity band of Art. 153(5).

    Per regime and grade:

    - CRR Art. 153(5) Table 1: the "less than 2,5 years" row is mandatory for
      every grade, so the band is the maturity fact.
    - PS1/26 'Strong' / 'Good': Art. 153(5)(c) makes column B / D the default and
      (d) lets the institution use column A / C "if less than 2.5 years remain",
      so the band is the maturity fact AND the firm's election. Without it a
      short-dated leg is weighted on column B / D, the long band's column.
    - PS1/26 'Satisfactory' / 'Weak' / 'Default' (and an unrecognised grade,
      which ``_map_category`` weights as 'Satisfactory'): Table A has ONE column
      for each, and (d) offers no other, so there is nothing to elect and the
      band is the maturity fact. Both bands carry the same Table A weight and
      Table B EL rate for these grades, HVCRE included, so the band moves no
      figure; it decides only which C 08.06 / CR10 row — each labelled by
      remaining maturity — the leg is reported on.

    An unknown (null) maturity flag is not short: the leg keeps the long band,
    the conservative weight.
    """
    is_short = col("is_short_maturity").eq_missing(lit(value=True))
    if is_crr or config.slotting_short_maturity_election:
        return is_short
    return is_short & ~_has_short_maturity_column(col("slotting_category"))


def _has_short_maturity_column(category: pl.Expr) -> pl.Expr:
    """The grades PS1/26 Art. 153(5)(d) offers a short-maturity column for.

    (d)(i) 'Strong' (column A instead of B) and (d)(ii) 'Good' (column C instead
    of D) — no other grade. Never null: an unrecognised or null grade has no
    column choice.
    """
    grade = category.str.to_lowercase()
    return grade.eq_missing(lit(SlottingCategory.STRONG.value)) | grade.eq_missing(
        lit(SlottingCategory.GOOD.value)
    )


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
    ``sl_type`` are always present. It is an audit carrier only: no weight
    or EL lookup reads it (PS1/26 Table A has no pre-operational row).
    """
    defaults = {
        "is_pre_operational": lit(False),
    }
    return [expr.alias(name) for name, expr in defaults.items() if name not in schema]
