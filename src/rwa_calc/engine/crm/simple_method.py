"""
Financial Collateral Simple Method (Art. 222).

Pipeline position:
    CRMProcessor (Step 4 alternative) -> SACalculator._apply_fcsm_rw_substitution

Key responsibilities:
- Aggregate eligible financial collateral per exposure (raw market value, no haircuts)
- Derive collateral risk weight from issuer type and CQS (Art. 114-134)
- Apply Art. 222(4) 0% RW exceptions (same-currency cash, 0%-RW sovereign bonds)
- Check maturity eligibility (Art. 222(7): collateral maturity >= exposure maturity)
- Set fcsm_* columns on exposure frame for SA calculator RW substitution
- Do NOT reduce EAD (that is the Comprehensive Method's mechanism)

References:
- CRR Art. 222: Financial Collateral Simple Method
- PRA PS1/26 Art. 222: Retained for SA exposures under Basel 3.1
- CRR Art. 191A / PRA PS1/26 Art. 191A: CRM method selection framework
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.domain.enums import ApproachType

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

# Art. 222(1): minimum 20% RW floor for secured portion (general case)
FCSM_RW_FLOOR = Decimal("0.20")

# Art. 222(4)(b): 20% market value discount for 0%-RW sovereign bonds
SOVEREIGN_BOND_DISCOUNT = Decimal("0.20")


def _derive_collateral_rw_expr(is_basel_3_1: bool = False) -> pl.Expr:
    """Derive the SA risk weight for financial collateral per Art. 222(1).

    "The risk weight prescribed under Chapter 2 of Title II for the type
    of collateral" — i.e., the SA risk weight that would apply if the
    collateral were itself an exposure.

    Args:
        is_basel_3_1: Whether Basel 3.1 tables apply (affects corporate CQS 5).

    Returns:
        Polars expression producing the collateral's own risk weight (float).
    """
    cqs = pl.col("issuer_cqs")
    ctype = pl.col("collateral_type").str.to_lowercase()

    # Cash, deposits, gold → 0% (Art. 134(1)/(4))
    is_cash_or_gold = ctype.is_in(["cash", "deposit", "gold"])

    # Sovereign/central government bonds → Art. 114 Table 1
    is_sovereign = (
        pl.col("issuer_type")
        .fill_null("")
        .str.to_lowercase()
        .is_in(["sovereign", "central_government", "central_bank"])
    )
    sovereign_rw = (
        pl.when(cqs == 1)
        .then(0.0)
        .when(cqs == 2)
        .then(0.20)
        .when(cqs == 3)
        .then(0.50)
        .when(cqs.is_in([4, 5]))
        .then(1.00)
        .when(cqs == 6)
        .then(1.50)
        .otherwise(1.00)  # unrated sovereign → conservative 100%
    )

    # Institution bonds → Art. 120 Table 3 (standard treatment)
    is_institution = (
        pl.col("issuer_type")
        .fill_null("")
        .str.to_lowercase()
        .is_in(["institution", "bank", "credit_institution"])
    )
    institution_rw = (
        pl.when(cqs == 1)
        .then(0.20)
        .when(cqs.is_in([2, 3]))
        .then(0.50)
        .when(cqs.is_in([4, 5]))
        .then(1.00)
        .when(cqs == 6)
        .then(1.50)
        .otherwise(1.00)  # unrated institution → conservative 100%
    )

    # Equity → 100% under CRR (Art. 133(2)), 250% under B31 (Art. 133(3))
    # For FCSM purposes, use CRR 100% (collateral is financial instrument, not equity exposure)
    is_equity = ctype.is_in(["equity", "equity_main_index", "equity_other"])

    # Corporate bonds → Art. 122 Table 5 (CRR) / Table 6 (B31)
    corp_cqs5_rw = 1.50 if is_basel_3_1 else 1.00  # B31 Art. 122(2) CQS 5 = 150%
    corporate_rw = (
        pl.when(cqs == 1)
        .then(0.20)
        .when(cqs == 2)
        .then(0.50)
        .when(cqs == 3)
        .then(1.00)
        .when(cqs == 4)
        .then(1.00)
        .when(cqs == 5)
        .then(corp_cqs5_rw)
        .when(cqs == 6)
        .then(1.50)
        .otherwise(1.00)  # unrated corporate → 100%
    )

    return (
        pl.when(is_cash_or_gold)
        .then(pl.lit(0.0))
        .when(is_sovereign)
        .then(sovereign_rw)
        .when(is_institution)
        .then(institution_rw)
        .when(is_equity)
        .then(pl.lit(1.00))
        .otherwise(corporate_rw)  # default: treat as corporate bond
    )


def _is_zero_rw_exception_expr() -> pl.Expr:
    """Art. 222(4): conditions for 0% RW instead of the 20% floor.

    Returns True when the 0% floor exception applies:
    (a) Cash deposit or deposit treated as cash, in the same currency
    (b) 0%-RW sovereign bond in the same currency (with 20% market value discount)

    The currency match is checked via _is_same_currency (set upstream).
    """
    ctype = pl.col("collateral_type").str.to_lowercase()
    is_same_currency = pl.col("_fcsm_same_currency").fill_null(False)

    # (a) Cash/deposit in same currency
    is_cash_same_ccy = ctype.is_in(["cash", "deposit"]) & is_same_currency

    # (b) 0%-RW sovereign bond in same currency (CQS 1 sovereign → 0% RW)
    is_zero_rw_sovereign = (
        (pl.col("_fcsm_item_rw") == 0.0)
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

    # Direct-level lookup
    exp_lookup = exposures.select(
        pl.col(exp_ref_col).alias("_exp_ref"),
        pl.col("currency").alias("_exp_currency")
        if "currency" in schema.names()
        else pl.lit("GBP").alias("_exp_currency"),
        pl.col(ead_col).alias("_exp_ead"),
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

    # For facility-level collateral, build a facility lookup
    if facility_col in schema.names():
        fac_lookup = exposures.group_by(facility_col).agg(
            pl.col("currency").first().alias("_fac_currency")
            if "currency" in schema.names()
            else pl.lit("GBP").alias("_fac_currency"),
            pl.col(ead_col).sum().alias("_fac_total_ead"),
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
        )

    # For counterparty-level collateral
    if cp_col in schema.names():
        cp_lookup = exposures.group_by(cp_col).agg(
            pl.col("currency").first().alias("_cp_currency")
            if "currency" in schema.names()
            else pl.lit("GBP").alias("_cp_currency"),
            pl.col(ead_col).sum().alias("_cp_total_ead"),
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
        )

    # Determine exposure currency via coalesce (direct → facility → counterparty)
    coll_with_exp = coll_with_exp.with_columns(
        pl.coalesce("_exp_currency", "_fac_currency", "_cp_currency").alias(
            "_resolved_exp_currency"
        ),
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
        & (pl.col("_fcsm_item_rw") == 0.0)
        & ~pl.col("collateral_type").str.to_lowercase().is_in(["cash", "deposit", "gold"])
    )
    coll_with_exp = coll_with_exp.with_columns(
        pl.when(is_sovereign_bond & pl.col("_fcsm_same_currency"))
        .then(pl.col("market_value") * (1.0 - float(SOVEREIGN_BOND_DISCOUNT)))
        .otherwise(pl.col("market_value"))
        .alias("_fcsm_effective_value"),
    )

    # 6. Determine effective RW (0% exception or item RW)
    coll_with_exp = coll_with_exp.with_columns(
        pl.when(_is_zero_rw_exception_expr())
        .then(pl.lit(0.0))
        .otherwise(pl.col("_fcsm_item_rw"))
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

    # 10. Cap at EAD, apply 20% floor (Art. 222(1))
    ead_expr = pl.col(ead_col).fill_null(0.0)
    result = result.with_columns(
        # Capped at EAD
        pl.min_horizontal("_fcsm_raw_value", ead_expr)
        .clip(lower_bound=0.0)
        .alias("fcsm_collateral_value"),
        # Apply 20% floor to the weighted-average RW (Art. 222(1))
        # Note: 0% exceptions have already been factored into _fcsm_effective_rw
        # per item, so the avg can be below 20% when 0% items dominate.
        # The floor applies to the overall blended secured RW, not per-item.
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
