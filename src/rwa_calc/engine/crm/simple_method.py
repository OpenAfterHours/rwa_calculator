"""
Financial Collateral Simple Method (Art. 222).

Pipeline position:
    CRMProcessor (Step 4 alternative) -> SACalculator._apply_fcsm_rw_substitution

Key responsibilities:
- Aggregate eligible financial collateral per exposure (raw market value, no haircuts)
- Derive collateral risk weight from issuer type and CQS (Art. 114-134)
- Apply the 20% floor per item (Art. 222(1)/(3))
- Apply the same-currency 0% RW carve-out per item — CRR Art. 222(4) / PRA PS1/26
  Art. 222(6) — for cash and 0%-RW sovereign bonds
- Set fcsm_* columns on exposure frame for SA calculator RW substitution
- Do NOT reduce EAD (that is the Comprehensive Method's mechanism)

References:
- CRR Art. 222: Financial Collateral Simple Method
- PRA PS1/26 Art. 222: Retained for SA exposures under Basel 3.1
- CRR Art. 191A / PRA PS1/26 Art. 191A: CRM method selection framework
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.tables.b31_risk_weights import B31_CORPORATE_RISK_WEIGHTS
from rwa_calc.data.tables.crr_risk_weights import (
    CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
    CORPORATE_RISK_WEIGHTS,
    INSTITUTION_RISK_WEIGHTS_B31_ECRA,
    INSTITUTION_RISK_WEIGHTS_CRR,
)
from rwa_calc.data.tables.crr_simple_method import (
    ART_222_4_CMP_RW,
    ART_222_4_NON_CMP_RW,
    FCSM_EQUITY_COLLATERAL_RW,
    FCSM_RW_FLOOR,
    SOVEREIGN_BOND_DISCOUNT,
)
from rwa_calc.domain.enums import CQS, ApproachType

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


def _derive_collateral_rw_expr(is_basel_3_1: bool = False) -> pl.Expr:
    """Derive the SA risk weight for financial collateral per Art. 222(1).

    "The risk weight prescribed under Chapter 2 of Title II for the type
    of collateral" — i.e., the SA risk weight that would apply if the
    collateral were itself an exposure.

    Args:
        is_basel_3_1: Whether Basel 3.1 tables apply (affects institution CQS 2
            ECRA divergence and corporate CQS 5).

    Returns:
        Polars expression producing the collateral's own risk weight (float).
    """
    cqs = pl.col("issuer_cqs")
    ctype = pl.col("collateral_type").str.to_lowercase()

    # Cash, deposits, gold → 0% (Art. 134(1)/(4))
    is_cash_or_gold = ctype.is_in(["cash", "deposit", "gold"])

    # Sovereign/central government bonds → Art. 114 Table 1.
    # Values sourced from CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS so that table
    # remains the single source of truth.
    is_sovereign = (
        pl.col("issuer_type")
        .fill_null("")
        .str.to_lowercase()
        .is_in(["sovereign", "central_government", "central_bank"])
    )
    sov_table = CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS
    sovereign_rw = (
        pl.when(cqs == 1)
        .then(float(sov_table[CQS.CQS1]))
        .when(cqs == 2)
        .then(float(sov_table[CQS.CQS2]))
        .when(cqs == 3)
        .then(float(sov_table[CQS.CQS3]))
        .when(cqs == 4)
        .then(float(sov_table[CQS.CQS4]))
        .when(cqs == 5)
        .then(float(sov_table[CQS.CQS5]))
        .when(cqs == 6)
        .then(float(sov_table[CQS.CQS6]))
        .otherwise(float(sov_table[CQS.UNRATED]))  # unrated sovereign → conservative 100%
    )

    # Institution bonds → Art. 120 Table 3 (CRR) / PRA PS1/26 Table 3 ECRA (B31).
    # CQS 2 diverges: 50% under CRR, 30% under B31 ECRA. Risk weights are sourced
    # from INSTITUTION_RISK_WEIGHTS_CRR / _B31_ECRA so the dicts remain the single
    # source of truth.
    is_institution = (
        pl.col("issuer_type")
        .fill_null("")
        .str.to_lowercase()
        .is_in(["institution", "bank", "credit_institution"])
    )
    inst_table = INSTITUTION_RISK_WEIGHTS_B31_ECRA if is_basel_3_1 else INSTITUTION_RISK_WEIGHTS_CRR
    institution_rw = (
        pl.when(cqs == 1)
        .then(float(inst_table[CQS.CQS1]))
        .when(cqs == 2)
        .then(float(inst_table[CQS.CQS2]))
        .when(cqs == 3)
        .then(float(inst_table[CQS.CQS3]))
        .when(cqs == 4)
        .then(float(inst_table[CQS.CQS4]))
        .when(cqs == 5)
        .then(float(inst_table[CQS.CQS5]))
        .when(cqs == 6)
        .then(float(inst_table[CQS.CQS6]))
        .otherwise(float(inst_table[CQS.UNRATED]))
    )

    # Equity → FCSM Art. 222(1) prescribes 100% under both frameworks (collateral
    # is treated by financial-instrument character, not equity-exposure character
    # — so B31 Art. 133(3)'s 250% does NOT apply when equity is FCSM collateral).
    # Single source of truth: FCSM_EQUITY_COLLATERAL_RW.
    is_equity = ctype.is_in(["equity", "equity_main_index", "equity_other"])

    # Corporate bonds → Art. 122 Table 5 (CRR) / Table 6 (B31). B31 diverges at
    # CQS 3 (0.75 vs 1.00 per PRA PS1/26 Art. 122(2)). Risk weights sourced from
    # CORPORATE_RISK_WEIGHTS (CRR) / B31_CORPORATE_RISK_WEIGHTS (B31) so each
    # table remains the single source of truth for its framework. Note: the two
    # dicts use different key types (CQS enum vs raw int), so build a uniform
    # int-keyed map of floats here for the per-CQS lookup.
    if is_basel_3_1:
        corp = {k: float(v) for k, v in B31_CORPORATE_RISK_WEIGHTS.items()}
    else:
        corp = {
            1: float(CORPORATE_RISK_WEIGHTS[CQS.CQS1]),
            2: float(CORPORATE_RISK_WEIGHTS[CQS.CQS2]),
            3: float(CORPORATE_RISK_WEIGHTS[CQS.CQS3]),
            4: float(CORPORATE_RISK_WEIGHTS[CQS.CQS4]),
            5: float(CORPORATE_RISK_WEIGHTS[CQS.CQS5]),
            6: float(CORPORATE_RISK_WEIGHTS[CQS.CQS6]),
            None: float(CORPORATE_RISK_WEIGHTS[CQS.UNRATED]),
        }
    corporate_rw = (
        pl.when(cqs == 1)
        .then(corp[1])
        .when(cqs == 2)
        .then(corp[2])
        .when(cqs == 3)
        .then(corp[3])
        .when(cqs == 4)
        .then(corp[4])
        .when(cqs == 5)
        .then(corp[5])
        .when(cqs == 6)
        .then(corp[6])
        .otherwise(corp[None])  # unrated corporate
    )

    return (
        pl.when(is_cash_or_gold)
        .then(pl.lit(0.0))
        .when(is_sovereign)
        .then(sovereign_rw)
        .when(is_institution)
        .then(institution_rw)
        .when(is_equity)
        .then(pl.lit(float(FCSM_EQUITY_COLLATERAL_RW)))
        .otherwise(corporate_rw)  # default: treat as corporate bond
    )


def _is_art_222_6_carveout_expr() -> pl.Expr:
    """Non-SFT same-currency cash / 0%-RW sovereign carve-out (Art. 222(6)).

    PRA PS1/26 Art. 222(6) (= CRR Art. 222(4) pre-renumbering): the 20% floor
    from Art. 222(1)/(3) does not apply to the following same-currency carve-outs
    when the exposure is NOT an SFT:
    (a) Cash deposit or cash assimilated instrument
    (b) 0%-RW sovereign debt securities (subject to 20% market-value discount)

    SFT-specific 0%/10% under Art. 222(4) is a separate branch handled by the
    secured-floor expression — see ``_secured_floor_expr``.

    The currency match is checked via `_fcsm_same_currency` (set upstream).
    """
    ctype = pl.col("collateral_type").str.to_lowercase()
    is_same_currency = pl.col("_fcsm_same_currency").fill_null(False)
    is_not_sft = ~pl.col("_fcsm_exposure_is_sft").fill_null(False)

    # (a) Cash/deposit in same currency
    is_cash_same_ccy = ctype.is_in(["cash", "deposit"]) & is_same_currency

    # (b) 0%-RW sovereign bond in same currency (CQS 1 sovereign → 0% RW)
    is_zero_rw_sovereign = (
        (pl.col("_fcsm_item_rw").abs() < 1e-10)
        & is_same_currency
        & ~ctype.is_in(["cash", "deposit", "gold", "equity", "equity_main_index", "equity_other"])
    )

    return (is_cash_same_ccy | is_zero_rw_sovereign) & is_not_sft


def _secured_floor_expr() -> pl.Expr:
    """Per-item secured-portion RW for FCSM, encoding Art. 222(3)/(4)/(6).

    Decision tree (per Art. 222 paragraph priority):
      1. SFT + Art. 227 zero-haircut criteria met → Art. 222(4) carve-out
         - Counterparty is core market participant → 0% (Art. 222(4)(a))
         - Otherwise                                → 10% (Art. 222(4)(b))
      2. Non-SFT + same-currency cash / 0%-RW sovereign → Art. 222(6) → 0%
      3. Otherwise → max(item_rw, 20% Art. 222(3) general floor)

    Reads ``_fcsm_exposure_is_sft``, ``_fcsm_cp_is_cmp``,
    ``_fcsm_qualifies_for_zero_haircut`` propagated by ``compute_fcsm_columns``.
    """
    is_sft = pl.col("_fcsm_exposure_is_sft").fill_null(False)
    is_cmp = pl.col("_fcsm_cp_is_cmp").fill_null(False)
    qualifies_zero_hc = pl.col("_fcsm_qualifies_for_zero_haircut").fill_null(False)
    item_rw = pl.col("_fcsm_item_rw")
    floor = pl.lit(float(FCSM_RW_FLOOR))

    sft_carveout_active = is_sft & qualifies_zero_hc
    cmp_floor = pl.lit(float(ART_222_4_CMP_RW))
    non_cmp_floor = pl.lit(float(ART_222_4_NON_CMP_RW))

    return (
        pl.when(sft_carveout_active & is_cmp)
        .then(cmp_floor)
        .when(sft_carveout_active & ~is_cmp)
        .then(non_cmp_floor)
        .when(_is_art_222_6_carveout_expr())
        .then(pl.lit(0.0))
        .otherwise(pl.max_horizontal(item_rw, floor))
    )


@cites("CRR Art. 222")
def compute_fcsm_columns(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame | None,
    config: CalculationConfig,
) -> pl.LazyFrame:
    """Compute FCSM columns on the exposure frame.

    Aggregates eligible financial collateral per exposure and sets:
    - fcsm_collateral_value: total raw market value of eligible financial collateral
      allocated to this exposure (capped at EAD)
    - fcsm_collateral_rw: weighted-average SA risk weight of the collateral

    Does NOT modify any EAD columns. The SA calculator uses these columns
    for risk weight substitution via _apply_fcsm_rw_substitution().

    IRB exposures are unaffected — Simple Method is SA-only per Art. 222.

    Args:
        exposures: Exposure frame with ead_gross, exposure_reference, etc.
        collateral: Collateral frame (may be None if no collateral).
        config: Calculation configuration.

    Returns:
        Exposure frame with fcsm_collateral_value and fcsm_collateral_rw columns.
    """
    if collateral is None:
        return _add_default_fcsm_columns(exposures)

    schema = exposures.collect_schema()
    schema_names = schema.names()
    ead_col = "ead_gross" if "ead_gross" in schema_names else "ead"
    exp_ref_col = "exposure_reference" if "exposure_reference" in schema_names else "loan_reference"
    facility_col = "parent_facility_reference"
    cp_col = "counterparty_reference"

    schema_flags = _SchemaFlags(
        has_exp_maturity="residual_maturity_years" in schema_names,
        sft_col=_resolve_sft_column(schema_names),
        has_cmp_col="cp_is_core_market_participant" in schema_names,
        has_currency="currency" in schema_names,
        has_facility=facility_col in schema_names,
        has_counterparty=cp_col in schema_names,
    )

    # 1. Filter to eligible financial collateral + ensure zero-haircut flag
    # 2. Derive per-item RW
    eligible = _prepare_eligible_collateral(collateral, config.is_basel_3_1)

    # 3. Multi-level join (direct + facility + counterparty) to bring exposure
    # currency, maturity, SFT and CMP flags onto each collateral row.
    coll_with_exp = _join_exposure_levels(
        eligible, exposures, exp_ref_col, facility_col, cp_col, ead_col, schema_flags
    )

    # 4. Resolve coalesced exposure-level columns and Art. 222(4) gating flags.
    coll_with_exp = _resolve_exposure_levels(coll_with_exp)

    # 5. Same-currency check + Art. 222(6)(b) sovereign-bond discount.
    coll_with_exp = _apply_currency_and_sovereign_discount(coll_with_exp)

    # 6. Per-item secured-portion RW (Art. 222(3)/(4)/(6) decision tree).
    coll_with_exp = coll_with_exp.with_columns(
        _secured_floor_expr().alias("_fcsm_effective_rw"),
    )

    # 6b. Art. 239(1) FCSM maturity-mismatch eligibility gate.
    coll_with_exp = _apply_maturity_eligibility_gate(coll_with_exp)

    # 7. Aggregate per beneficiary_reference.
    agg = _aggregate_per_beneficiary(coll_with_exp)

    # 8-9. Multi-level join back to exposures and combine with pro-rata shares.
    result = _join_aggregates_back(
        exposures, agg, exp_ref_col, facility_col, cp_col, ead_col, schema_flags
    )

    # 10. Cap collateral value at EAD; RW floor was applied per-item in step 6.
    result = _finalise_fcsm_columns(result, ead_col)

    # Drop temporary columns
    temp_cols = [
        c
        for c in result.collect_schema().names()
        if c.startswith("_fcsm_") or c in ("_fac_ead_total", "_cp_ead_total")
    ]
    return result.drop(temp_cols)


def undo_sa_ead_reduction(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Undo the Comprehensive Method's financial collateral EAD reduction for SA.

    Under the Simple Method, EAD is NOT reduced by financial collateral.
    The Comprehensive Method pipeline (which also runs for IRB LGD adjustment)
    sets ead_after_collateral = ead_gross - collateral_adjusted_value for SA.
    This function restores ead_after_collateral = ead_gross for SA exposures.

    IRB exposures are unaffected (they already keep ead_gross in the
    Comprehensive pipeline because LGD adjustment handles collateral).

    Args:
        exposures: Exposure frame after Comprehensive Method processing.

    Returns:
        Exposure frame with SA EAD restored to pre-collateral values.
    """
    schema = exposures.collect_schema()
    if "ead_after_collateral" not in schema.names():
        return exposures

    is_sa = pl.col("approach") == ApproachType.SA.value

    return exposures.with_columns(
        pl.when(is_sa)
        .then(pl.col("ead_gross"))
        .otherwise(pl.col("ead_after_collateral"))
        .alias("ead_after_collateral"),
        # Also zero out collateral_adjusted_value for SA (no EAD reduction)
        pl.when(is_sa)
        .then(pl.lit(0.0))
        .otherwise(
            pl.col("collateral_adjusted_value")
            if "collateral_adjusted_value" in schema.names()
            else pl.lit(0.0)
        )
        .alias("collateral_adjusted_value"),
    )


def _add_default_fcsm_columns(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Add default (zero) FCSM columns when no collateral is available."""
    return exposures.with_columns(
        pl.lit(0.0).alias("fcsm_collateral_value"),
        pl.lit(0.0).alias("fcsm_collateral_rw"),
    )


@dataclass(frozen=True)
class _SchemaFlags:
    """Bundle of resolved exposure-schema feature flags used to pick join shape.

    Captures which optional columns are present on the exposure frame plus
    the resolved name of the SFT flag — ``exposure_is_sft`` if the CRM
    processor has already normalised, otherwise the raw ``is_sft`` if present,
    otherwise ``None`` so a literal False is substituted.
    """

    has_exp_maturity: bool
    sft_col: str | None
    has_cmp_col: bool
    has_currency: bool
    has_facility: bool
    has_counterparty: bool


def _resolve_sft_column(schema_names: list[str]) -> str | None:
    """Pick the SFT flag column name (or None if neither is present)."""
    if "exposure_is_sft" in schema_names:
        return "exposure_is_sft"
    if "is_sft" in schema_names:
        return "is_sft"
    return None


def _prepare_eligible_collateral(collateral: pl.LazyFrame, is_b31: bool) -> pl.LazyFrame:
    """Filter to eligible FC, normalise zero-haircut flag, derive per-item RW."""
    eligible = collateral.filter(pl.col("is_eligible_financial_collateral").fill_null(False))

    eligible_schema_names = eligible.collect_schema().names()
    if "qualifies_for_zero_haircut" not in eligible_schema_names:
        eligible = eligible.with_columns(
            pl.lit(False).alias("qualifies_for_zero_haircut"),
        )
    else:
        eligible = eligible.with_columns(
            pl.col("qualifies_for_zero_haircut").fill_null(False),
        )

    return eligible.with_columns(_derive_collateral_rw_expr(is_b31).alias("_fcsm_item_rw"))


def _currency_expr(present: bool, alias: str) -> pl.Expr:
    """Currency column for the given level, defaulting to GBP if absent."""
    return pl.col("currency").alias(alias) if present else pl.lit("GBP").alias(alias)


def _maturity_expr(present: bool, alias: str) -> pl.Expr:
    """Residual-maturity-years column, defaulting to null Float64 if absent."""
    if present:
        return pl.col("residual_maturity_years").alias(alias)
    return pl.lit(None).cast(pl.Float64).alias(alias)


def _sft_expr(sft_col: str | None, alias: str, *, aggregated: bool) -> pl.Expr:
    """SFT flag column, taking .max() across the group when aggregated."""
    if sft_col is None:
        return pl.lit(False).alias(alias)
    base = pl.col(sft_col).fill_null(False)
    if aggregated:
        base = base.max()
    return base.alias(alias)


def _cmp_expr(has_cmp_col: bool, alias: str, *, aggregated: bool) -> pl.Expr:
    """Core-market-participant flag column, taking .max() when aggregated."""
    if not has_cmp_col:
        return pl.lit(False).alias(alias)
    base = pl.col("cp_is_core_market_participant").fill_null(False)
    if aggregated:
        base = base.max()
    return base.alias(alias)


def _build_exposure_lookup(
    exposures: pl.LazyFrame, exp_ref_col: str, ead_col: str, sf: _SchemaFlags
) -> pl.LazyFrame:
    """Direct-level lookup carrying currency, EAD, maturity, SFT and CMP flags."""
    return exposures.select(
        pl.col(exp_ref_col).alias("_exp_ref"),
        _currency_expr(sf.has_currency, "_exp_currency"),
        pl.col(ead_col).alias("_exp_ead"),
        _maturity_expr(sf.has_exp_maturity, "_exp_residual_maturity_years"),
        _sft_expr(sf.sft_col, "_exp_is_sft", aggregated=False),
        _cmp_expr(sf.has_cmp_col, "_exp_cp_is_cmp", aggregated=False),
    ).unique(subset=["_exp_ref"])


def _build_facility_lookup(
    exposures: pl.LazyFrame, facility_col: str, ead_col: str, sf: _SchemaFlags
) -> pl.LazyFrame:
    """Facility-level aggregate lookup (MAX maturity, ANY SFT, ANY CMP)."""
    fac_aggs = [
        pl.col("currency").first().alias("_fac_currency")
        if sf.has_currency
        else pl.lit("GBP").alias("_fac_currency"),
        pl.col(ead_col).sum().alias("_fac_total_ead"),
        pl.col("residual_maturity_years").max().alias("_fac_residual_maturity_years")
        if sf.has_exp_maturity
        else pl.lit(None).cast(pl.Float64).alias("_fac_residual_maturity_years"),
        _sft_expr(sf.sft_col, "_fac_is_sft", aggregated=True),
        _cmp_expr(sf.has_cmp_col, "_fac_cp_is_cmp", aggregated=True),
    ]
    return exposures.group_by(facility_col).agg(fac_aggs)


def _build_counterparty_lookup(
    exposures: pl.LazyFrame, cp_col: str, ead_col: str, sf: _SchemaFlags
) -> pl.LazyFrame:
    """Counterparty-level aggregate lookup (MAX maturity, ANY SFT, ANY CMP)."""
    cp_aggs = [
        pl.col("currency").first().alias("_cp_currency")
        if sf.has_currency
        else pl.lit("GBP").alias("_cp_currency"),
        pl.col(ead_col).sum().alias("_cp_total_ead"),
        pl.col("residual_maturity_years").max().alias("_cp_residual_maturity_years")
        if sf.has_exp_maturity
        else pl.lit(None).cast(pl.Float64).alias("_cp_residual_maturity_years"),
        _sft_expr(sf.sft_col, "_cp_is_sft", aggregated=True),
        _cmp_expr(sf.has_cmp_col, "_cp_cp_is_cmp", aggregated=True),
    ]
    return exposures.group_by(cp_col).agg(cp_aggs)


def _default_facility_columns() -> list[pl.Expr]:
    """Null-filled facility-level columns when no facility column exists."""
    return [
        pl.lit(None).cast(pl.Utf8).alias("_fac_currency"),
        pl.lit(None).cast(pl.Float64).alias("_fac_total_ead"),
        pl.lit(None).cast(pl.Float64).alias("_fac_residual_maturity_years"),
        pl.lit(None).cast(pl.Boolean).alias("_fac_is_sft"),
        pl.lit(None).cast(pl.Boolean).alias("_fac_cp_is_cmp"),
    ]


def _default_counterparty_columns() -> list[pl.Expr]:
    """Null-filled counterparty-level columns when no CP column exists."""
    return [
        pl.lit(None).cast(pl.Utf8).alias("_cp_currency"),
        pl.lit(None).cast(pl.Float64).alias("_cp_total_ead"),
        pl.lit(None).cast(pl.Float64).alias("_cp_residual_maturity_years"),
        pl.lit(None).cast(pl.Boolean).alias("_cp_is_sft"),
        pl.lit(None).cast(pl.Boolean).alias("_cp_cp_is_cmp"),
    ]


def _join_exposure_levels(
    eligible: pl.LazyFrame,
    exposures: pl.LazyFrame,
    exp_ref_col: str,
    facility_col: str,
    cp_col: str,
    ead_col: str,
    sf: _SchemaFlags,
) -> pl.LazyFrame:
    """Join collateral to direct, facility and counterparty exposure data.

    Each level contributes its own currency / EAD / maturity / SFT / CMP
    columns; downstream code coalesces them in `_resolve_exposure_levels`.
    """
    exp_lookup = _build_exposure_lookup(exposures, exp_ref_col, ead_col, sf)
    coll_with_exp = eligible.join(
        exp_lookup, left_on="beneficiary_reference", right_on="_exp_ref", how="left"
    )

    if sf.has_facility:
        fac_lookup = _build_facility_lookup(exposures, facility_col, ead_col, sf)
        coll_with_exp = coll_with_exp.join(
            fac_lookup,
            left_on="beneficiary_reference",
            right_on=facility_col,
            how="left",
            suffix="_fac",
        )
    else:
        coll_with_exp = coll_with_exp.with_columns(_default_facility_columns())

    if sf.has_counterparty:
        cp_lookup = _build_counterparty_lookup(exposures, cp_col, ead_col, sf)
        coll_with_exp = coll_with_exp.join(
            cp_lookup,
            left_on="beneficiary_reference",
            right_on=cp_col,
            how="left",
            suffix="_cp",
        )
    else:
        coll_with_exp = coll_with_exp.with_columns(_default_counterparty_columns())

    return coll_with_exp


def _resolve_exposure_levels(coll_with_exp: pl.LazyFrame) -> pl.LazyFrame:
    """Coalesce direct/facility/counterparty columns into resolved aliases.

    Resolves Art. 222(4) gating flags through the same direct -> facility ->
    counterparty hierarchy and folds the collateral-frame
    ``qualifies_for_zero_haircut`` into a hidden alias so the secured-floor
    expression has a single set of column names to reason about.
    """
    return coll_with_exp.with_columns(
        pl.coalesce("_exp_currency", "_fac_currency", "_cp_currency").alias(
            "_resolved_exp_currency"
        ),
        pl.coalesce(
            "_exp_residual_maturity_years",
            "_fac_residual_maturity_years",
            "_cp_residual_maturity_years",
        ).alias("_resolved_exp_residual_maturity_years"),
        pl.coalesce("_exp_is_sft", "_fac_is_sft", "_cp_is_sft")
        .fill_null(False)
        .alias("_fcsm_exposure_is_sft"),
        pl.coalesce("_exp_cp_is_cmp", "_fac_cp_is_cmp", "_cp_cp_is_cmp")
        .fill_null(False)
        .alias("_fcsm_cp_is_cmp"),
        pl.col("qualifies_for_zero_haircut")
        .fill_null(False)
        .alias("_fcsm_qualifies_for_zero_haircut"),
    )


def _apply_currency_and_sovereign_discount(coll_with_exp: pl.LazyFrame) -> pl.LazyFrame:
    """Set _fcsm_same_currency and apply the Art. 222(6)(b) 20% discount.

    The discount is waived when the collateral satisfies the Art. 227(2)
    zero-haircut criteria (PRA PS1/26 Art. 222(4) SFT carve-out is a flat
    RW substitution, not a value haircut — so the 20% market-value discount
    must not be applied on top of it).
    """
    coll_schema_names = coll_with_exp.collect_schema().names()
    coll_currency = (
        pl.col("currency").fill_null("").str.to_uppercase()
        if "currency" in coll_schema_names
        else pl.lit("")
    )
    coll_with_exp = coll_with_exp.with_columns(
        (coll_currency == pl.col("_resolved_exp_currency").fill_null("").str.to_uppercase()).alias(
            "_fcsm_same_currency"
        ),
    )

    is_sovereign_bond = (
        pl.col("issuer_type")
        .fill_null("")
        .str.to_lowercase()
        .is_in(["sovereign", "central_government", "central_bank"])
        & (pl.col("_fcsm_item_rw").abs() < 1e-10)
        & ~pl.col("collateral_type").str.to_lowercase().is_in(["cash", "deposit", "gold"])
    )
    apply_sovereign_discount = (
        is_sovereign_bond
        & pl.col("_fcsm_same_currency")
        & ~pl.col("_fcsm_qualifies_for_zero_haircut")
    )
    return coll_with_exp.with_columns(
        pl.when(apply_sovereign_discount)
        .then(pl.col("market_value") * (1.0 - float(SOVEREIGN_BOND_DISCOUNT)))
        .otherwise(pl.col("market_value"))
        .alias("_fcsm_effective_value"),
    )


def _apply_maturity_eligibility_gate(coll_with_exp: pl.LazyFrame) -> pl.LazyFrame:
    """Zero-suppress collateral whose residual maturity is < exposure's.

    CRR Art. 239(1) FCSM maturity-mismatch eligibility gate is binary — the
    Art. 239(2) (t-0.25)/(T-0.25) partial adjustment applies to FCCM/IRB only.
    Only enforced when both maturities are populated; missing data on either
    side preserves the pre-existing (permissive) behaviour.
    """
    coll_schema_names = coll_with_exp.collect_schema().names()
    if "residual_maturity_years" not in coll_schema_names:
        return coll_with_exp

    coll_residual = pl.col("residual_maturity_years")
    exp_residual = pl.col("_resolved_exp_residual_maturity_years")
    is_maturity_ineligible = (
        coll_residual.is_not_null() & exp_residual.is_not_null() & (coll_residual < exp_residual)
    )
    return coll_with_exp.with_columns(
        pl.when(is_maturity_ineligible)
        .then(pl.lit(0.0))
        .otherwise(pl.col("_fcsm_effective_value"))
        .alias("_fcsm_effective_value"),
        pl.when(is_maturity_ineligible)
        .then(pl.lit(0.0))
        .otherwise(pl.col("_fcsm_effective_rw"))
        .alias("_fcsm_effective_rw"),
    )


def _aggregate_per_beneficiary(coll_with_exp: pl.LazyFrame) -> pl.LazyFrame:
    """Sum collateral value and value-weighted RW per beneficiary_reference."""
    return (
        coll_with_exp.group_by("beneficiary_reference")
        .agg(
            pl.col("_fcsm_effective_value").sum().alias("_fcsm_total_value"),
            (pl.col("_fcsm_effective_value") * pl.col("_fcsm_effective_rw"))
            .sum()
            .alias("_fcsm_weighted_rw_sum"),
        )
        .with_columns(
            pl.when(pl.col("_fcsm_total_value") > 0)
            .then(pl.col("_fcsm_weighted_rw_sum") / pl.col("_fcsm_total_value"))
            .otherwise(0.0)
            .alias("_fcsm_avg_rw"),
        )
    )


def _join_aggregates_back(
    exposures: pl.LazyFrame,
    agg: pl.LazyFrame,
    exp_ref_col: str,
    facility_col: str,
    cp_col: str,
    ead_col: str,
    sf: _SchemaFlags,
) -> pl.LazyFrame:
    """Join direct/facility/counterparty aggregates back to exposures.

    Computes the pro-rata share for facility- and counterparty-level
    collateral, then combines the three levels into a single raw value and
    coalesced RW for the downstream EAD cap.
    """
    result = exposures.join(
        agg.select(
            pl.col("beneficiary_reference").alias("_agg_ref"),
            pl.col("_fcsm_total_value").alias("_fcsm_val_d"),
            pl.col("_fcsm_avg_rw").alias("_fcsm_rw_d"),
        ),
        left_on=exp_ref_col,
        right_on="_agg_ref",
        how="left",
    )

    result = _join_facility_aggregate(result, exposures, agg, facility_col, ead_col, sf)
    result = _join_counterparty_aggregate(result, exposures, agg, cp_col, ead_col, sf)

    return result.with_columns(
        (
            pl.col("_fcsm_val_d").fill_null(0.0)
            + pl.col("_fcsm_val_f").fill_null(0.0) * pl.col("_fcsm_fac_share")
            + pl.col("_fcsm_val_c").fill_null(0.0) * pl.col("_fcsm_cp_share")
        ).alias("_fcsm_raw_value"),
        # Weighted-average RW: use the RW from the highest-value level
        pl.coalesce("_fcsm_rw_d", "_fcsm_rw_f", "_fcsm_rw_c").fill_null(0.0).alias("_fcsm_raw_rw"),
    )


def _join_facility_aggregate(
    result: pl.LazyFrame,
    exposures: pl.LazyFrame,
    agg: pl.LazyFrame,
    facility_col: str,
    ead_col: str,
    sf: _SchemaFlags,
) -> pl.LazyFrame:
    """Join the facility-level aggregate with pro-rata share, or default to 0."""
    if not sf.has_facility:
        return result.with_columns(
            pl.lit(None).cast(pl.Float64).alias("_fcsm_val_f"),
            pl.lit(None).cast(pl.Float64).alias("_fcsm_rw_f"),
            pl.lit(0.0).alias("_fcsm_fac_share"),
            pl.lit(None).cast(pl.Float64).alias("_fac_ead_total"),
        )

    fac_ead = exposures.group_by(facility_col).agg(
        pl.col(ead_col).sum().alias("_fac_ead_total"),
    )
    return (
        result.join(
            agg.select(
                pl.col("beneficiary_reference").alias("_agg_ref_f"),
                pl.col("_fcsm_total_value").alias("_fcsm_val_f"),
                pl.col("_fcsm_avg_rw").alias("_fcsm_rw_f"),
            ),
            left_on=facility_col,
            right_on="_agg_ref_f",
            how="left",
        )
        .join(fac_ead, on=facility_col, how="left")
        .with_columns(
            pl.when(pl.col("_fac_ead_total") > 0)
            .then(pl.col(ead_col) / pl.col("_fac_ead_total"))
            .otherwise(0.0)
            .alias("_fcsm_fac_share"),
        )
    )


def _join_counterparty_aggregate(
    result: pl.LazyFrame,
    exposures: pl.LazyFrame,
    agg: pl.LazyFrame,
    cp_col: str,
    ead_col: str,
    sf: _SchemaFlags,
) -> pl.LazyFrame:
    """Join the counterparty-level aggregate with pro-rata share, or default."""
    if not sf.has_counterparty:
        return result.with_columns(
            pl.lit(None).cast(pl.Float64).alias("_fcsm_val_c"),
            pl.lit(None).cast(pl.Float64).alias("_fcsm_rw_c"),
            pl.lit(0.0).alias("_fcsm_cp_share"),
            pl.lit(None).cast(pl.Float64).alias("_cp_ead_total"),
        )

    cp_ead = exposures.group_by(cp_col).agg(
        pl.col(ead_col).sum().alias("_cp_ead_total"),
    )
    return (
        result.join(
            agg.select(
                pl.col("beneficiary_reference").alias("_agg_ref_c"),
                pl.col("_fcsm_total_value").alias("_fcsm_val_c"),
                pl.col("_fcsm_avg_rw").alias("_fcsm_rw_c"),
            ),
            left_on=cp_col,
            right_on="_agg_ref_c",
            how="left",
        )
        .join(cp_ead, on=cp_col, how="left")
        .with_columns(
            pl.when(pl.col("_cp_ead_total") > 0)
            .then(pl.col(ead_col) / pl.col("_cp_ead_total"))
            .otherwise(0.0)
            .alias("_fcsm_cp_share"),
        )
    )


def _finalise_fcsm_columns(result: pl.LazyFrame, ead_col: str) -> pl.LazyFrame:
    """Cap collateral value at EAD and rename internal RW column to public."""
    ead_expr = pl.col(ead_col).fill_null(0.0)
    return result.with_columns(
        pl.min_horizontal("_fcsm_raw_value", ead_expr)
        .clip(lower_bound=0.0)
        .alias("fcsm_collateral_value"),
        pl.col("_fcsm_raw_rw").alias("fcsm_collateral_rw"),
    )
