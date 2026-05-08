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

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.data.tables.b31_risk_weights import B31_CORPORATE_RISK_WEIGHTS
from rwa_calc.data.tables.crr_risk_weights import (
    CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
    CORPORATE_RISK_WEIGHTS,
    INSTITUTION_RISK_WEIGHTS_B31_ECRA,
    INSTITUTION_RISK_WEIGHTS_CRR,
)
from rwa_calc.data.tables.crr_simple_method import (
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


def _is_zero_rw_exception_expr() -> pl.Expr:
    """Same-currency cash / 0%-RW sovereign 0% RW exception (not floored to 20%).

    CRR Art. 222(4) / PRA PS1/26 Art. 222(6): the 20% floor from Art. 222(1)/(3)
    does not apply to the following same-currency carve-outs:
    (a) Cash deposit or cash assimilated instrument
    (b) 0%-RW sovereign debt securities (subject to 20% market-value discount)

    The PRA renumbered this to paragraph 6 when drafting PS1/26; the underlying
    substance is identical. SFT-specific 0%/10% (PRA Art. 222(4) / CRR Art. 222(5))
    is a separate branch — see P1.93.

    The currency match is checked via `_fcsm_same_currency` (set upstream).
    """
    ctype = pl.col("collateral_type").str.to_lowercase()
    is_same_currency = pl.col("_fcsm_same_currency").fill_null(False)

    # (a) Cash/deposit in same currency
    is_cash_same_ccy = ctype.is_in(["cash", "deposit"]) & is_same_currency

    # (b) 0%-RW sovereign bond in same currency (CQS 1 sovereign → 0% RW)
    is_zero_rw_sovereign = (
        (pl.col("_fcsm_item_rw").abs() < 1e-10)
        & is_same_currency
        & ~ctype.is_in(["cash", "deposit", "gold", "equity", "equity_main_index", "equity_other"])
    )

    return is_cash_same_ccy | is_zero_rw_sovereign


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

    is_b31 = config.is_basel_3_1

    # 1. Filter to eligible financial collateral
    eligible = collateral.filter(pl.col("is_eligible_financial_collateral").fill_null(False))

    # 2. Derive collateral risk weight per item
    eligible = eligible.with_columns(_derive_collateral_rw_expr(is_b31).alias("_fcsm_item_rw"))

    # 3. Join to exposures to get currency for same-currency check
    # Multi-level matching: direct (loan/exposure), facility, counterparty
    schema = exposures.collect_schema()
    ead_col = "ead_gross" if "ead_gross" in schema.names() else "ead"

    # Build reference-to-currency/EAD lookup from exposures
    exp_ref_col = (
        "exposure_reference" if "exposure_reference" in schema.names() else "loan_reference"
    )
    facility_col = "parent_facility_reference"
    cp_col = "counterparty_reference"

    # Direct-level lookup. Also carry residual_maturity_years for the
    # CRR Art. 239(1) FCSM eligibility gate (collateral residual maturity
    # must be >= exposure residual maturity — strictly binary, no Art. 239(2)
    # partial adjustment for FCSM).
    has_exp_maturity = "residual_maturity_years" in schema.names()
    exp_lookup = exposures.select(
        pl.col(exp_ref_col).alias("_exp_ref"),
        pl.col("currency").alias("_exp_currency")
        if "currency" in schema.names()
        else pl.lit("GBP").alias("_exp_currency"),
        pl.col(ead_col).alias("_exp_ead"),
        pl.col("residual_maturity_years").alias("_exp_residual_maturity_years")
        if has_exp_maturity
        else pl.lit(None).cast(pl.Float64).alias("_exp_residual_maturity_years"),
    ).unique(subset=["_exp_ref"])

    # Join collateral items to exposure-level data based on beneficiary_reference
    # Simple approach: join by beneficiary_reference = exposure_reference first,
    # then facility, then counterparty. Coalesce results.
    coll_with_exp = eligible.join(
        exp_lookup,
        left_on="beneficiary_reference",
        right_on="_exp_ref",
        how="left",
    )

    # For facility-level collateral, build a facility lookup. Use the
    # MAX residual_maturity_years across the facility's exposures so the
    # Art. 239(1) gate is conservative — the collateral must cover the
    # longest-dated exposure in the pool to be eligible at the pool level.
    if facility_col in schema.names():
        fac_lookup = exposures.group_by(facility_col).agg(
            pl.col("currency").first().alias("_fac_currency")
            if "currency" in schema.names()
            else pl.lit("GBP").alias("_fac_currency"),
            pl.col(ead_col).sum().alias("_fac_total_ead"),
            pl.col("residual_maturity_years").max().alias("_fac_residual_maturity_years")
            if has_exp_maturity
            else pl.lit(None).cast(pl.Float64).alias("_fac_residual_maturity_years"),
        )
        coll_with_exp = coll_with_exp.join(
            fac_lookup,
            left_on="beneficiary_reference",
            right_on=facility_col,
            how="left",
            suffix="_fac",
        )
    else:
        coll_with_exp = coll_with_exp.with_columns(
            pl.lit(None).cast(pl.Utf8).alias("_fac_currency"),
            pl.lit(None).cast(pl.Float64).alias("_fac_total_ead"),
            pl.lit(None).cast(pl.Float64).alias("_fac_residual_maturity_years"),
        )

    # For counterparty-level collateral
    if cp_col in schema.names():
        cp_lookup = exposures.group_by(cp_col).agg(
            pl.col("currency").first().alias("_cp_currency")
            if "currency" in schema.names()
            else pl.lit("GBP").alias("_cp_currency"),
            pl.col(ead_col).sum().alias("_cp_total_ead"),
            pl.col("residual_maturity_years").max().alias("_cp_residual_maturity_years")
            if has_exp_maturity
            else pl.lit(None).cast(pl.Float64).alias("_cp_residual_maturity_years"),
        )
        coll_with_exp = coll_with_exp.join(
            cp_lookup,
            left_on="beneficiary_reference",
            right_on=cp_col,
            how="left",
            suffix="_cp",
        )
    else:
        coll_with_exp = coll_with_exp.with_columns(
            pl.lit(None).cast(pl.Utf8).alias("_cp_currency"),
            pl.lit(None).cast(pl.Float64).alias("_cp_total_ead"),
            pl.lit(None).cast(pl.Float64).alias("_cp_residual_maturity_years"),
        )

    # Determine exposure currency via coalesce (direct → facility → counterparty)
    coll_with_exp = coll_with_exp.with_columns(
        pl.coalesce("_exp_currency", "_fac_currency", "_cp_currency").alias(
            "_resolved_exp_currency"
        ),
        pl.coalesce(
            "_exp_residual_maturity_years",
            "_fac_residual_maturity_years",
            "_cp_residual_maturity_years",
        ).alias("_resolved_exp_residual_maturity_years"),
    )

    # 4. Same-currency check for Art. 222(4)
    coll_currency = (
        pl.col("currency").fill_null("").str.to_uppercase()
        if "currency" in coll_with_exp.collect_schema().names()
        else pl.lit("")
    )
    coll_with_exp = coll_with_exp.with_columns(
        (coll_currency == pl.col("_resolved_exp_currency").fill_null("").str.to_uppercase()).alias(
            "_fcsm_same_currency"
        ),
    )

    # 5. Apply Art. 222(4)(b) 20% discount for 0%-RW sovereign bonds
    is_sovereign_bond = (
        pl.col("issuer_type")
        .fill_null("")
        .str.to_lowercase()
        .is_in(["sovereign", "central_government", "central_bank"])
        & (pl.col("_fcsm_item_rw").abs() < 1e-10)
        & ~pl.col("collateral_type").str.to_lowercase().is_in(["cash", "deposit", "gold"])
    )
    coll_with_exp = coll_with_exp.with_columns(
        pl.when(is_sovereign_bond & pl.col("_fcsm_same_currency"))
        .then(pl.col("market_value") * (1.0 - float(SOVEREIGN_BOND_DISCOUNT)))
        .otherwise(pl.col("market_value"))
        .alias("_fcsm_effective_value"),
    )

    # 6. Apply the 20% floor per item here (not on the aggregate) so that
    # Art. 222(4)/(6) carve-out items flow through at 0% — the floor must not
    # be re-imposed after the weighted average.
    coll_with_exp = coll_with_exp.with_columns(
        pl.when(_is_zero_rw_exception_expr())
        .then(pl.lit(0.0))
        .otherwise(pl.max_horizontal(pl.col("_fcsm_item_rw"), pl.lit(float(FCSM_RW_FLOOR))))
        .alias("_fcsm_effective_rw"),
    )

    # 6b. CRR Art. 239(1) FCSM maturity-mismatch eligibility gate. Collateral
    # whose residual maturity is strictly less than the secured exposure's
    # residual maturity is INELIGIBLE — Art. 239(1) is binary (the Art. 239(2)
    # (t-0.25)/(T-0.25) partial adjustment formula applies to FCCM/IRB only,
    # not FCSM). Zero-suppress the contribution at the per-item level so the
    # downstream weighted aggregation drops the row entirely. Only enforced
    # when both maturities are populated; missing data on either side
    # preserves the pre-existing (permissive) behaviour.
    coll_schema_names = coll_with_exp.collect_schema().names()
    if "residual_maturity_years" in coll_schema_names:
        coll_residual = pl.col("residual_maturity_years")
        exp_residual = pl.col("_resolved_exp_residual_maturity_years")
        is_maturity_ineligible = (
            coll_residual.is_not_null()
            & exp_residual.is_not_null()
            & (coll_residual < exp_residual)
        )
        coll_with_exp = coll_with_exp.with_columns(
            pl.when(is_maturity_ineligible)
            .then(pl.lit(0.0))
            .otherwise(pl.col("_fcsm_effective_value"))
            .alias("_fcsm_effective_value"),
            pl.when(is_maturity_ineligible)
            .then(pl.lit(0.0))
            .otherwise(pl.col("_fcsm_effective_rw"))
            .alias("_fcsm_effective_rw"),
        )

    # 7. Aggregate per beneficiary_reference: total value and weighted-avg RW
    agg = (
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

    # 8. Multi-level join back to exposures
    # Direct-level
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

    # Facility-level
    if facility_col in schema.names():
        # Compute pro-rata share for facility-level collateral
        fac_ead = exposures.group_by(facility_col).agg(
            pl.col(ead_col).sum().alias("_fac_ead_total"),
        )
        result = (
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
            .join(
                fac_ead,
                on=facility_col,
                how="left",
            )
            .with_columns(
                # Pro-rata share within facility
                pl.when(pl.col("_fac_ead_total") > 0)
                .then(pl.col(ead_col) / pl.col("_fac_ead_total"))
                .otherwise(0.0)
                .alias("_fcsm_fac_share"),
            )
        )
    else:
        result = result.with_columns(
            pl.lit(None).cast(pl.Float64).alias("_fcsm_val_f"),
            pl.lit(None).cast(pl.Float64).alias("_fcsm_rw_f"),
            pl.lit(0.0).alias("_fcsm_fac_share"),
            pl.lit(None).cast(pl.Float64).alias("_fac_ead_total"),
        )

    # Counterparty-level
    if cp_col in schema.names():
        cp_ead = exposures.group_by(cp_col).agg(
            pl.col(ead_col).sum().alias("_cp_ead_total"),
        )
        result = (
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
            .join(
                cp_ead,
                on=cp_col,
                how="left",
            )
            .with_columns(
                pl.when(pl.col("_cp_ead_total") > 0)
                .then(pl.col(ead_col) / pl.col("_cp_ead_total"))
                .otherwise(0.0)
                .alias("_fcsm_cp_share"),
            )
        )
    else:
        result = result.with_columns(
            pl.lit(None).cast(pl.Float64).alias("_fcsm_val_c"),
            pl.lit(None).cast(pl.Float64).alias("_fcsm_rw_c"),
            pl.lit(0.0).alias("_fcsm_cp_share"),
            pl.lit(None).cast(pl.Float64).alias("_cp_ead_total"),
        )

    # 9. Combine multi-level: direct + pro-rata facility + pro-rata counterparty
    result = result.with_columns(
        (
            pl.col("_fcsm_val_d").fill_null(0.0)
            + pl.col("_fcsm_val_f").fill_null(0.0) * pl.col("_fcsm_fac_share")
            + pl.col("_fcsm_val_c").fill_null(0.0) * pl.col("_fcsm_cp_share")
        ).alias("_fcsm_raw_value"),
        # Weighted-average RW: use the RW from the highest-value level
        pl.coalesce("_fcsm_rw_d", "_fcsm_rw_f", "_fcsm_rw_c").fill_null(0.0).alias("_fcsm_raw_rw"),
    )

    # 10. Cap collateral value at EAD; RW floor was applied per-item in step 6.
    ead_expr = pl.col(ead_col).fill_null(0.0)
    result = result.with_columns(
        pl.min_horizontal("_fcsm_raw_value", ead_expr)
        .clip(lower_bound=0.0)
        .alias("fcsm_collateral_value"),
        pl.col("_fcsm_raw_rw").alias("fcsm_collateral_rw"),
    )

    # Drop temporary columns
    temp_cols = [
        c
        for c in result.collect_schema().names()
        if c.startswith("_fcsm_")
        or c
        in (
            "_fac_ead_total",
            "_cp_ead_total",
        )
    ]
    result = result.drop(temp_cols)

    return result


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
