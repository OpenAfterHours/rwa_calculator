"""
Collateral allocation and LGD calculation for CRM processing.

Pipeline position:
    EAD initialisation -> apply_collateral -> Guarantees

Key responsibilities:
- Netting collateral generation (CRR Art. 195)
- Haircut application and maturity mismatch
- Multi-level collateral allocation (direct / facility / counterparty)
- SA EAD reduction via eligible financial collateral
- F-IRB LGD calculation with supervisory values
- Overcollateralisation and minimum threshold checks

References:
    CRR Art. 223-224, 230: Collateral haircuts and allocation
    CRR Art. 161: F-IRB supervisory LGD
    CRE22.52-53, CRE32.9-12: Basel 3.1 equivalents
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.crm.constants import (
    NON_ELIGIBLE_RE_TYPES,
    beneficiary_level_expr,
    collateral_category_expr,
    collateral_lgd_expr,
    is_financial_collateral_type_expr,
    min_collateralisation_threshold_expr,
    overcollateralisation_ratio_expr,
    supervisory_lgd_values,
)
from rwa_calc.engine.crm.haircuts import HaircutCalculator

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


def generate_netting_collateral(
    exposures: pl.LazyFrame,
) -> pl.LazyFrame | None:
    """
    Generate synthetic cash collateral from negative-drawn netting-eligible loans.

    When a loan has a negative drawn amount (credit balance) and is covered by a
    netting agreement (CRR Art. 195), the absolute value of that negative balance
    can reduce sibling exposures in the same facility — treated as cash collateral.

    The netting agreement belongs to the negative-balance loan (the deposit). All
    positive-drawn exposures under the same netting facility benefit from the pool,
    regardless of their own has_netting_agreement flag.

    The netting facility is determined by:
    1. netting_facility_reference (explicit, if provided on the negative loan)
    2. root_facility_reference (top-level facility in hierarchy)
    3. parent_facility_reference (direct parent, fallback)

    The synthetic collateral rows are allocated pro-rata by ead_gross to positive-drawn
    siblings within the netting facility. Netting pools are grouped by
    (netting_facility, currency) so the haircut pipeline can apply FX haircuts when
    the pool currency differs from the sibling's currency.

    Args:
        exposures: Exposures with ead_gross initialised

    Returns:
        LazyFrame of synthetic collateral rows, or None if no netting applies
    """
    schema = exposures.collect_schema()
    if "has_netting_agreement" not in schema.names():
        return None
    if "parent_facility_reference" not in schema.names():
        return None

    has_root = "root_facility_reference" in schema.names()
    has_netting_ref = "netting_facility_reference" in schema.names()

    # Pool netting group: explicit reference > root > direct parent
    pool_group_parts = [pl.col("parent_facility_reference")]
    if has_root:
        pool_group_parts.insert(0, pl.col("root_facility_reference"))
    if has_netting_ref:
        pool_group_parts.insert(0, pl.col("netting_facility_reference"))

    pool_group_expr = pl.coalesce(pool_group_parts).alias("_netting_group")

    # Negative-drawn loans with a netting agreement provide the pool
    negative_loans = exposures.filter(
        (pl.col("has_netting_agreement") == True)  # noqa: E712
        & (pl.col("drawn_amount") < 0)
        & pl.col("parent_facility_reference").is_not_null()
    ).with_columns(pool_group_expr)

    # Sum abs(drawn_amount) per (netting_group, currency) → netting pool
    # Currency is kept so the synthetic collateral carries the source currency,
    # allowing the haircut pipeline to apply FX haircuts when currencies differ.
    netting_pool = (
        negative_loans.group_by(["_netting_group", "currency"])
        .agg(
            pl.col("drawn_amount").abs().sum().alias("netting_pool"),
        )
        .rename({"currency": "_pool_currency"})
    )

    # All positive-drawn exposures that could benefit from netting.
    # A sibling matches a pool if the pool's netting group equals its
    # parent_facility_reference OR root_facility_reference.
    positive_siblings = exposures.filter(
        (pl.col("ead_gross") > 0) & pl.col("parent_facility_reference").is_not_null()
    )

    sibling_cols = [
        "exposure_reference",
        "parent_facility_reference",
        "currency",
        "ead_gross",
        "maturity_date",
    ]
    if has_root:
        sibling_cols.append("root_facility_reference")

    positive_siblings = positive_siblings.select(sibling_cols)

    # Match siblings to pools: pool's netting group can match at parent or root level
    match_parent = positive_siblings.join(
        netting_pool,
        left_on="parent_facility_reference",
        right_on="_netting_group",
        how="inner",
    )

    if has_root:
        match_root = positive_siblings.join(
            netting_pool,
            left_on="root_facility_reference",
            right_on="_netting_group",
            how="inner",
        )
        matched = pl.concat([match_parent, match_root], how="diagonal").unique(
            subset=["exposure_reference", "_pool_currency"], keep="first"
        )
    else:
        matched = match_parent

    # Total EAD per pool for pro-rata allocation (recompute after matching)
    facility_totals = matched.group_by("_pool_currency", "netting_pool").agg(
        pl.col("ead_gross").sum().alias("_facility_total_ead"),
    )

    # Join totals back for pro-rata
    allocated = matched.join(
        facility_totals,
        on=["_pool_currency", "netting_pool"],
        how="left",
    ).filter(pl.col("_facility_total_ead") > 0)

    # Pro-rata market_value per sibling
    allocated = allocated.with_columns(
        (pl.col("netting_pool") * pl.col("ead_gross") / pl.col("_facility_total_ead")).alias(
            "market_value"
        ),
    )

    # Build synthetic collateral rows — currency from the pool (source of funds)
    synthetic = allocated.select(
        (pl.lit("NETTING_") + pl.col("exposure_reference")).alias("collateral_reference"),
        pl.lit("cash").alias("collateral_type"),
        pl.col("_pool_currency").alias("currency"),
        pl.col("maturity_date"),
        pl.col("market_value"),
        pl.lit(None).cast(pl.Float64).alias("nominal_value"),
        pl.lit(None).cast(pl.Float64).alias("pledge_percentage"),
        pl.lit("loan").alias("beneficiary_type"),
        pl.col("exposure_reference").alias("beneficiary_reference"),
        pl.lit(None).cast(pl.Int8).alias("issuer_cqs"),
        pl.lit(None).cast(pl.String).alias("issuer_type"),
        pl.lit(None).cast(pl.Float64).alias("residual_maturity_years"),
        pl.lit(True).alias("is_eligible_financial_collateral"),
        pl.lit(True).alias("is_eligible_irb_collateral"),
        pl.lit(None).cast(pl.Date).alias("valuation_date"),
        pl.lit(None).cast(pl.String).alias("valuation_type"),
        pl.lit(None).cast(pl.String).alias("property_type"),
        pl.lit(None).cast(pl.Float64).alias("property_ltv"),
        pl.lit(None).cast(pl.Boolean).alias("is_income_producing"),
        pl.lit(None).cast(pl.Boolean).alias("is_adc"),
        pl.lit(None).cast(pl.Boolean).alias("is_presold"),
    )

    return synthetic


def apply_collateral(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame,
    config: CalculationConfig,
    haircut_calculator: HaircutCalculator,
    is_basel_3_1: bool,
    build_exposure_lookups_fn: callable,
    join_collateral_to_lookups_fn: callable,
    resolve_pledge_from_joined_fn: callable,
) -> pl.LazyFrame:
    """
    Apply collateral to reduce EAD (SA) or LGD (IRB).

    Pre-computes shared exposure lookups once, then joins ALL lookup columns
    (EAD, currency, maturity) in a single pass of 3 joins. Pledge resolution
    and currency/maturity derivation operate on pre-joined columns — no
    additional joins needed.

    Args:
        exposures: Exposures with ead_gross
        collateral: Collateral data
        config: Calculation configuration
        haircut_calculator: HaircutCalculator instance
        is_basel_3_1: Whether Basel 3.1 framework applies
        build_exposure_lookups_fn: Function to build exposure lookups
        join_collateral_to_lookups_fn: Function to join collateral to lookups
        resolve_pledge_from_joined_fn: Function to resolve pledge percentages

    Returns:
        Exposures with collateral effects applied
    """
    # Pre-compute shared exposure lookups once
    direct_lookup, facility_lookup, cp_lookup = build_exposure_lookups_fn(exposures)

    # Materialise the small lookup frames to prevent plan-tree duplication.
    # Each lookup is referenced in multiple downstream joins; without this,
    # Polars re-evaluates the group_by/select expressions at each reference.
    direct_lookup = direct_lookup.collect().lazy()
    facility_lookup = facility_lookup.collect().lazy()
    cp_lookup = cp_lookup.collect().lazy()

    # Derive EAD totals from the lookups for allocation methods
    facility_ead_totals = facility_lookup.select(
        pl.col("_ben_ref_facility").alias("parent_facility_reference"),
        pl.col("_ead_facility").alias("_fac_ead_total"),
    )
    cp_ead_totals = cp_lookup.select(
        pl.col("_ben_ref_cp").alias("counterparty_reference"),
        pl.col("_ead_cp").alias("_cp_ead_total"),
    )

    # Single pass: join all lookup columns (EAD, currency, maturity)
    collateral = join_collateral_to_lookups_fn(
        collateral, direct_lookup, facility_lookup, cp_lookup
    )

    # Resolve pledge_percentage → market_value (uses pre-joined _beneficiary_ead)
    collateral = resolve_pledge_from_joined_fn(collateral)

    # Apply haircuts to collateral (no longer needs exposures)
    adjusted_collateral = haircut_calculator.apply_haircuts(collateral, config)

    # Apply maturity mismatch (no longer needs exposures)
    adjusted_collateral = haircut_calculator.apply_maturity_mismatch(adjusted_collateral)

    # Check for multi-level linking and collateral type info
    collateral_schema = adjusted_collateral.collect_schema()
    has_beneficiary_type = "beneficiary_type" in collateral_schema.names()
    has_collateral_type = "collateral_type" in collateral_schema.names()

    if has_beneficiary_type and has_collateral_type:
        # Unified EAD + LGD allocation: single group_by, single join chain
        return _apply_collateral_unified(
            exposures,
            adjusted_collateral,
            collateral_schema,
            config,
            facility_ead_totals,
            cp_ead_totals,
            is_basel_3_1,
        )

    # Legacy path: separate EAD and LGD allocation
    if "is_eligible_financial_collateral" in collateral_schema:
        eligible_collateral = adjusted_collateral.filter(
            pl.col("is_eligible_financial_collateral") == True  # noqa: E712
        )
    else:
        eligible_collateral = adjusted_collateral.filter(
            ~pl.col("collateral_type").str.to_lowercase().is_in(NON_ELIGIBLE_RE_TYPES)
        )

    eligible_schema = eligible_collateral.collect_schema()

    if "beneficiary_type" in eligible_schema.names():
        exposures = _allocate_collateral_multi_level_for_ead(
            exposures, eligible_collateral, facility_ead_totals, cp_ead_totals
        )
    else:
        # Guard: direct-only allocation
        collateral_by_exposure = eligible_collateral.group_by("beneficiary_reference").agg(
            [
                pl.coalesce(pl.col("value_after_maturity_adj"), pl.col("value_after_haircut"))
                .sum()
                .alias("total_collateral_adjusted"),
                pl.col("market_value").sum().alias("total_collateral_market"),
                pl.len().alias("collateral_count"),
            ]
        )

        exposures = exposures.join(
            collateral_by_exposure,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        )

        exposures = exposures.with_columns(
            [
                pl.col("total_collateral_adjusted")
                .fill_null(0.0)
                .alias("collateral_adjusted_value"),
                pl.col("total_collateral_market").fill_null(0.0).alias("collateral_market_value"),
            ]
        )

    # Legacy path: set per-type collateral values to 0.0 (not available)
    exposures = exposures.with_columns(
        [
            pl.lit(0.0).alias("collateral_financial_value"),
            pl.lit(0.0).alias("collateral_cash_value"),
            pl.lit(0.0).alias("collateral_re_value"),
            pl.lit(0.0).alias("collateral_receivables_value"),
            pl.lit(0.0).alias("collateral_other_physical_value"),
        ]
    )

    # Apply collateral effect based on approach
    exposures = exposures.with_columns(
        [
            pl.when(pl.col("approach") == ApproachType.SA.value)
            .then((pl.col("ead_gross") - pl.col("collateral_adjusted_value")).clip(lower_bound=0))
            .otherwise(pl.col("ead_gross"))
            .alias("ead_after_collateral"),
        ]
    )

    # For F-IRB: Calculate effective LGD with collateral
    exposures = _calculate_irb_lgd_with_collateral(
        exposures, adjusted_collateral, config, is_basel_3_1, facility_ead_totals, cp_ead_totals
    )

    return exposures


def apply_firb_supervisory_lgd_no_collateral(
    exposures: pl.LazyFrame,
    is_basel_3_1: bool,
) -> pl.LazyFrame:
    """
    Apply F-IRB supervisory LGD when no collateral is available.

    For F-IRB exposures without collateral, uses supervisory LGD values:
    - CRR Art. 161: Senior unsecured 45%, Subordinated 75%
    - Basel 3.1 CRE32.9-12: Senior unsecured 40%, Subordinated 75%

    A-IRB exposures keep their modelled LGD.

    Args:
        exposures: Exposures with lgd_pre_crm
        is_basel_3_1: Whether Basel 3.1 framework applies

    Returns:
        Exposures with lgd_post_crm set for F-IRB
    """
    lgd_values = supervisory_lgd_values(is_basel_3_1)
    lgd_senior = lgd_values["unsecured"]

    # Add collateral-related columns with zero values for consistency
    exposures = exposures.with_columns(
        [
            pl.lit(0.0).alias("total_collateral_for_lgd"),
            pl.lit(0.0).alias("collateral_coverage_pct"),
        ]
    )

    # Check if seniority column exists
    schema_names = set(exposures.collect_schema().names())
    if "seniority" in schema_names:
        # Determine LGD based on seniority for F-IRB
        exposures = exposures.with_columns(
            [
                pl.when(
                    (pl.col("approach") == ApproachType.FIRB.value)
                    & (
                        pl.col("seniority")
                        .fill_null("")
                        .str.to_lowercase()
                        .is_in(["subordinated", "junior"])
                    )
                )
                .then(pl.lit(0.75))  # Subordinated (same both frameworks)
                .when(pl.col("approach") == ApproachType.FIRB.value)
                .then(pl.lit(lgd_senior))  # Senior unsecured
                .otherwise(pl.col("lgd_pre_crm"))  # A-IRB or SA: keep existing
                .alias("lgd_post_crm"),
            ]
        )
    else:
        # No seniority column: use senior unsecured default for all F-IRB
        exposures = exposures.with_columns(
            [
                pl.when(pl.col("approach") == ApproachType.FIRB.value)
                .then(pl.lit(lgd_senior))  # Senior unsecured
                .otherwise(pl.col("lgd_pre_crm"))  # A-IRB or SA: keep existing
                .alias("lgd_post_crm"),
            ]
        )

    return exposures


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _apply_collateral_unified(
    exposures: pl.LazyFrame,
    adjusted_collateral: pl.LazyFrame,
    collateral_schema: pl.Schema,
    config: CalculationConfig,
    facility_ead_totals: pl.LazyFrame,
    cp_ead_totals: pl.LazyFrame,
    is_basel_3_1: bool,
) -> pl.LazyFrame:
    """
    Unified EAD + LGD collateral allocation in a single pass.

    Fuses _allocate_collateral_multi_level_for_ead and
    _allocate_collateral_multi_level_for_lgd into one group_by and one
    set of 3-level joins (5 joins instead of 10).
    """
    lgd_values = supervisory_lgd_values(is_basel_3_1)
    lgd_unsecured = lgd_values["unsecured"]

    # --- Determine eligible expression for EAD reduction ---
    if "is_eligible_financial_collateral" in collateral_schema:
        is_eligible = pl.col("is_eligible_financial_collateral")
    else:
        is_eligible = ~pl.col("collateral_type").str.to_lowercase().is_in(NON_ELIGIBLE_RE_TYPES)

    # --- Annotate collateral with LGD categories (using shared expressions) ---
    annotated = adjusted_collateral.with_columns(
        [
            collateral_lgd_expr(is_basel_3_1).alias("collateral_lgd"),
            overcollateralisation_ratio_expr().alias("overcollateralisation_ratio"),
            is_financial_collateral_type_expr().alias("is_financial_collateral_type"),
            collateral_category_expr().alias("_coll_category"),
            pl.coalesce(
                pl.col("value_after_maturity_adj")
                if "value_after_maturity_adj" in collateral_schema.names()
                else pl.lit(None),
                pl.col("value_after_haircut")
                if "value_after_haircut" in collateral_schema.names()
                else pl.lit(None),
                pl.col("market_value"),
            ).alias("adjusted_value"),
        ]
    )
    annotated = annotated.with_columns(
        (pl.col("adjusted_value") / pl.col("overcollateralisation_ratio")).alias(
            "effectively_secured"
        ),
    )

    # --- Single group_by: EAD + LGD aggregates in one pass ---
    val_expr = pl.coalesce(
        pl.col("value_after_maturity_adj"),
        pl.col("value_after_haircut"),
    )
    is_fin = pl.col("is_financial_collateral_type")

    all_coll = (
        annotated.with_columns(
            beneficiary_level_expr().alias("_level"),
        )
        .group_by(["_level", "beneficiary_reference"])
        .agg(
            [
                # EAD aggregates (eligible financial only)
                val_expr.filter(is_eligible).sum().alias("_cv"),
                pl.col("market_value").filter(is_eligible).sum().alias("_mv"),
                # LGD aggregates: financial
                pl.col("effectively_secured").filter(is_fin).sum().alias("_ef"),
                (pl.col("effectively_secured") * pl.col("collateral_lgd"))
                .filter(is_fin)
                .sum()
                .alias("_wf"),
                # LGD aggregates: non-financial
                pl.col("effectively_secured").filter(~is_fin).sum().alias("_en"),
                (pl.col("effectively_secured") * pl.col("collateral_lgd"))
                .filter(~is_fin)
                .sum()
                .alias("_wn"),
                pl.col("adjusted_value").filter(~is_fin).sum().alias("_rn"),
                # Per-type collateral values for COREP
                pl.col("adjusted_value")
                .filter(pl.col("_coll_category") == "financial")
                .sum()
                .alias("_adj_fin"),
                pl.col("adjusted_value")
                .filter(pl.col("_coll_category") == "cash")
                .sum()
                .alias("_adj_cash"),
                pl.col("adjusted_value")
                .filter(pl.col("_coll_category") == "real_estate")
                .sum()
                .alias("_adj_re"),
                pl.col("adjusted_value")
                .filter(pl.col("_coll_category") == "receivables")
                .sum()
                .alias("_adj_rec"),
                pl.col("adjusted_value")
                .filter(pl.col("_coll_category") == "other_physical")
                .sum()
                .alias("_adj_oth"),
            ]
        )
    )

    _agg = [
        "_cv",
        "_mv",
        "_ef",
        "_wf",
        "_en",
        "_wn",
        "_rn",
        "_adj_fin",
        "_adj_cash",
        "_adj_re",
        "_adj_rec",
        "_adj_oth",
    ]

    # Split the small aggregated result for per-level joins
    coll_direct = (
        all_coll.filter(pl.col("_level") == "direct")
        .drop("_level")
        .rename({c: f"{c}_d" for c in _agg})
    )
    coll_facility = (
        all_coll.filter(pl.col("_level") == "facility")
        .drop("_level")
        .rename({c: f"{c}_f" for c in _agg})
    )
    coll_counterparty = (
        all_coll.filter(pl.col("_level") == "counterparty")
        .drop("_level")
        .rename({c: f"{c}_c" for c in _agg})
    )

    # --- Join all 3 levels to exposures (5 joins total) ---
    exp_schema = exposures.collect_schema()

    exposures = exposures.join(
        coll_direct,
        left_on="exposure_reference",
        right_on="beneficiary_reference",
        how="left",
    )

    if "parent_facility_reference" in exp_schema.names():
        exposures = exposures.join(
            coll_facility,
            left_on="parent_facility_reference",
            right_on="beneficiary_reference",
            how="left",
        ).join(
            facility_ead_totals,
            on="parent_facility_reference",
            how="left",
        )
    else:
        exposures = exposures.with_columns(
            [pl.lit(0.0).alias(f"{c}_f") for c in _agg] + [pl.lit(0.0).alias("_fac_ead_total")]
        )

    exposures = exposures.join(
        coll_counterparty,
        left_on="counterparty_reference",
        right_on="beneficiary_reference",
        how="left",
    ).join(
        cp_ead_totals,
        on="counterparty_reference",
        how="left",
    )

    # --- Fill nulls + pro-rata weights ---
    fill_exprs = []
    for sfx in ["d", "f", "c"]:
        for c in _agg:
            fill_exprs.append(pl.col(f"{c}_{sfx}").fill_null(0.0))
    fill_exprs.extend(
        [
            pl.col("_fac_ead_total").fill_null(0.0),
            pl.col("_cp_ead_total").fill_null(0.0),
        ]
    )
    exposures = exposures.with_columns(fill_exprs)

    exposures = exposures.with_columns(
        [
            pl.when(pl.col("_fac_ead_total") > 0)
            .then(pl.col("ead_gross") / pl.col("_fac_ead_total"))
            .otherwise(pl.lit(0.0))
            .alias("_fw"),
            pl.when(pl.col("_cp_ead_total") > 0)
            .then(pl.col("ead_gross") / pl.col("_cp_ead_total"))
            .otherwise(pl.lit(0.0))
            .alias("_cw"),
        ]
    )

    # --- Combine all levels for EAD + LGD ---
    def _sum3(col: str) -> pl.Expr:
        return (
            pl.col(f"{col}_d")
            + pl.col(f"{col}_f") * pl.col("_fw")
            + pl.col(f"{col}_c") * pl.col("_cw")
        )

    exposures = exposures.with_columns(
        [
            _sum3("_cv").alias("collateral_adjusted_value"),
            _sum3("_mv").alias("collateral_market_value"),
            _sum3("_adj_fin").alias("collateral_financial_value"),
            _sum3("_adj_cash").alias("collateral_cash_value"),
            _sum3("_adj_re").alias("collateral_re_value"),
            _sum3("_adj_rec").alias("collateral_receivables_value"),
            _sum3("_adj_oth").alias("collateral_other_physical_value"),
            _sum3("_ef").alias("_eff_fin_a"),
            _sum3("_wf").alias("_wlgd_fin_a"),
            _sum3("_en").alias("_eff_nf_a"),
            _sum3("_wn").alias("_wlgd_nf_a"),
            _sum3("_rn").alias("_raw_nf_a"),
        ]
    )

    # Min threshold: zero non-financial if raw < 30% of EAD
    exposures = exposures.with_columns(
        [
            pl.when(pl.col("_raw_nf_a") >= 0.30 * pl.col("ead_gross"))
            .then(pl.col("_eff_nf_a"))
            .otherwise(pl.lit(0.0))
            .alias("_eff_nf_final"),
            pl.when(pl.col("_raw_nf_a") >= 0.30 * pl.col("ead_gross"))
            .then(pl.col("_wlgd_nf_a"))
            .otherwise(pl.lit(0.0))
            .alias("_wlgd_nf_final"),
        ]
    )

    # total_collateral_for_lgd + lgd_secured (combined)
    exposures = exposures.with_columns(
        [
            (pl.col("_eff_fin_a") + pl.col("_eff_nf_final")).alias("total_collateral_for_lgd"),
            pl.when(pl.col("_eff_fin_a") + pl.col("_eff_nf_final") > 0)
            .then(
                (pl.col("_wlgd_fin_a") + pl.col("_wlgd_nf_final"))
                / (pl.col("_eff_fin_a") + pl.col("_eff_nf_final"))
            )
            .otherwise(pl.lit(lgd_unsecured))
            .alias("lgd_secured"),
        ]
    )

    # --- Drop intermediate allocation columns ---
    drop_cols = [f"{c}_{sfx}" for sfx in ["d", "f", "c"] for c in _agg] + [
        "_fac_ead_total",
        "_cp_ead_total",
        "_fw",
        "_cw",
        "_eff_fin_a",
        "_wlgd_fin_a",
        "_eff_nf_a",
        "_wlgd_nf_a",
        "_raw_nf_a",
        "_eff_nf_final",
        "_wlgd_nf_final",
    ]
    exposures = exposures.drop(drop_cols)

    # --- Apply EAD reduction + determine seniority-based LGD ---
    exposures = exposures.with_columns(
        [
            pl.when(pl.col("approach") == ApproachType.SA.value)
            .then((pl.col("ead_gross") - pl.col("collateral_adjusted_value")).clip(lower_bound=0))
            .otherwise(pl.col("ead_gross"))
            .alias("ead_after_collateral"),
            pl.when(pl.col("seniority").str.to_lowercase().is_in(["subordinated", "junior"]))
            .then(pl.lit(0.75))
            .otherwise(pl.lit(lgd_unsecured))
            .alias("lgd_unsecured"),
        ]
    )

    # --- Calculate LGD post-CRM + audit ---
    exposures = exposures.with_columns(
        [
            pl.when(
                (pl.col("approach") == ApproachType.FIRB.value)
                & (pl.col("ead_gross") > 0)
                & (pl.col("total_collateral_for_lgd") > 0)
            )
            .then(
                (
                    (
                        pl.col("lgd_secured")
                        * pl.col("total_collateral_for_lgd").clip(upper_bound=pl.col("ead_gross"))
                    )
                    + (
                        pl.col("lgd_unsecured")
                        * (pl.col("ead_gross") - pl.col("total_collateral_for_lgd")).clip(
                            lower_bound=0
                        )
                    )
                )
                / pl.col("ead_gross")
            )
            .when((pl.col("approach") == ApproachType.FIRB.value) & (pl.col("ead_gross") > 0))
            .then(pl.col("lgd_unsecured"))
            .otherwise(pl.col("lgd_pre_crm"))
            .alias("lgd_post_crm"),
            pl.when(pl.col("ead_gross") > 0)
            .then(
                pl.col("total_collateral_for_lgd").clip(upper_bound=pl.col("ead_gross"))
                / pl.col("ead_gross")
                * 100
            )
            .otherwise(pl.lit(0.0))
            .alias("collateral_coverage_pct"),
        ]
    )

    return exposures


def _calculate_irb_lgd_with_collateral(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame,
    config: CalculationConfig,
    is_basel_3_1: bool,
    facility_ead_totals: pl.LazyFrame | None = None,
    cp_ead_totals: pl.LazyFrame | None = None,
) -> pl.LazyFrame:
    """
    Calculate effective LGD for F-IRB exposures with collateral.

    For F-IRB, collateral reduces LGD using supervisory values (CRR Art. 161).
    A-IRB uses internally modelled LGD - no adjustment is made here.
    """
    # Check if collateral has required columns
    collateral_schema = collateral.collect_schema()
    if "collateral_type" not in collateral_schema.names():
        return exposures

    lgd_values = supervisory_lgd_values(is_basel_3_1)
    lgd_unsecured = lgd_values["unsecured"]

    # Annotate collateral with LGD categories (using shared expressions)
    collateral_with_lgd = collateral.with_columns(
        [
            collateral_lgd_expr(is_basel_3_1).alias("collateral_lgd"),
            overcollateralisation_ratio_expr().alias("overcollateralisation_ratio"),
            min_collateralisation_threshold_expr().alias("min_collateralisation_threshold"),
            is_financial_collateral_type_expr().alias("is_financial_collateral_type"),
        ]
    )

    # Get adjusted collateral value (prefer maturity-adjusted, then haircut)
    # Then calculate effectively_secured = adjusted_value / overcollateralisation_ratio
    collateral_with_lgd = collateral_with_lgd.with_columns(
        [
            pl.coalesce(
                pl.col("value_after_maturity_adj")
                if "value_after_maturity_adj" in collateral_schema.names()
                else pl.lit(None),
                pl.col("value_after_haircut")
                if "value_after_haircut" in collateral_schema.names()
                else pl.lit(None),
                pl.col("market_value"),
            ).alias("adjusted_value"),
        ]
    )
    collateral_with_lgd = collateral_with_lgd.with_columns(
        [
            (pl.col("adjusted_value") / pl.col("overcollateralisation_ratio")).alias(
                "effectively_secured"
            ),
        ]
    )

    # Aggregate collateral by beneficiary with weighted LGD at each linking level
    has_beneficiary_type = "beneficiary_type" in collateral_schema.names()

    if has_beneficiary_type:
        # Multi-level collateral allocation
        exposures = _allocate_collateral_multi_level_for_lgd(
            exposures, collateral_with_lgd, facility_ead_totals, cp_ead_totals
        )
    else:
        # Legacy: direct linking only
        collateral_by_exposure = collateral_with_lgd.group_by("beneficiary_reference").agg(
            [
                pl.col("effectively_secured")
                .filter(pl.col("is_financial_collateral_type"))
                .sum()
                .alias("eff_fin"),
                (pl.col("effectively_secured") * pl.col("collateral_lgd"))
                .filter(pl.col("is_financial_collateral_type"))
                .sum()
                .alias("wlgd_fin"),
                pl.col("effectively_secured")
                .filter(~pl.col("is_financial_collateral_type"))
                .sum()
                .alias("eff_nf"),
                (pl.col("effectively_secured") * pl.col("collateral_lgd"))
                .filter(~pl.col("is_financial_collateral_type"))
                .sum()
                .alias("wlgd_nf"),
                pl.col("adjusted_value")
                .filter(~pl.col("is_financial_collateral_type"))
                .sum()
                .alias("raw_nf"),
            ]
        )

        exposures = exposures.join(
            collateral_by_exposure,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        )

        exposures = exposures.with_columns(
            [
                pl.col("eff_fin").fill_null(0.0),
                pl.col("wlgd_fin").fill_null(0.0),
                pl.col("eff_nf").fill_null(0.0),
                pl.col("wlgd_nf").fill_null(0.0),
                pl.col("raw_nf").fill_null(0.0),
            ]
        )

        # Apply min threshold: if raw non-financial < 30% of EAD, zero it out
        exposures = exposures.with_columns(
            [
                pl.when(pl.col("raw_nf") >= 0.30 * pl.col("ead_gross"))
                .then(pl.col("eff_nf"))
                .otherwise(pl.lit(0.0))
                .alias("eff_nf_final"),
                pl.when(pl.col("raw_nf") >= 0.30 * pl.col("ead_gross"))
                .then(pl.col("wlgd_nf"))
                .otherwise(pl.lit(0.0))
                .alias("wlgd_nf_final"),
            ]
        )

        # Combine financial + non-financial
        exposures = exposures.with_columns(
            [
                (pl.col("eff_fin") + pl.col("eff_nf_final")).alias("total_collateral_for_lgd"),
                (pl.col("wlgd_fin") + pl.col("wlgd_nf_final")).alias("total_weighted_lgd_sum"),
            ]
        )

        exposures = exposures.with_columns(
            [
                pl.when(pl.col("total_collateral_for_lgd") > 0)
                .then(pl.col("total_weighted_lgd_sum") / pl.col("total_collateral_for_lgd"))
                .otherwise(pl.lit(lgd_unsecured))
                .alias("lgd_secured"),
            ]
        )

        # Drop intermediate columns
        exposures = exposures.drop(
            [
                "eff_fin",
                "wlgd_fin",
                "eff_nf",
                "wlgd_nf",
                "raw_nf",
                "eff_nf_final",
                "wlgd_nf_final",
                "total_weighted_lgd_sum",
            ]
        )

    # Determine LGD for unsecured portion based on seniority
    exposures = exposures.with_columns(
        [
            pl.when(pl.col("seniority").str.to_lowercase().is_in(["subordinated", "junior"]))
            .then(pl.lit(0.75))
            .otherwise(pl.lit(lgd_unsecured))
            .alias("lgd_unsecured"),
        ]
    )

    # Calculate effective LGD for F-IRB exposures
    exposures = exposures.with_columns(
        [
            pl.when(
                (pl.col("approach") == ApproachType.FIRB.value)
                & (pl.col("ead_gross") > 0)
                & (pl.col("total_collateral_for_lgd") > 0)
            )
            .then(
                (
                    (
                        pl.col("lgd_secured")
                        * pl.col("total_collateral_for_lgd").clip(upper_bound=pl.col("ead_gross"))
                    )
                    + (
                        pl.col("lgd_unsecured")
                        * (pl.col("ead_gross") - pl.col("total_collateral_for_lgd")).clip(
                            lower_bound=0
                        )
                    )
                )
                / pl.col("ead_gross")
            )
            .when((pl.col("approach") == ApproachType.FIRB.value) & (pl.col("ead_gross") > 0))
            .then(pl.col("lgd_unsecured"))
            .otherwise(pl.col("lgd_pre_crm"))
            .alias("lgd_post_crm"),
        ]
    )

    # Add audit columns for LGD calculation
    exposures = exposures.with_columns(
        [
            pl.when(pl.col("ead_gross") > 0)
            .then(
                pl.col("total_collateral_for_lgd").clip(upper_bound=pl.col("ead_gross"))
                / pl.col("ead_gross")
                * 100
            )
            .otherwise(pl.lit(0.0))
            .alias("collateral_coverage_pct"),
        ]
    )

    return exposures


def _allocate_collateral_multi_level_for_lgd(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame,
    facility_ead_totals: pl.LazyFrame | None = None,
    cp_ead_totals: pl.LazyFrame | None = None,
) -> pl.LazyFrame:
    """
    Allocate collateral from multiple linking levels for LGD calculation.

    Uses a single group_by on (_level, beneficiary_reference) to traverse
    the heavy upstream collateral plan once, then splits the small aggregated
    result for per-level joins.

    Tracks financial and non-financial collateral separately to apply:
    - Overcollateralisation ratios (CRR Art. 230 / CRE32.9-12)
    - Minimum collateralisation thresholds (30% for RE/other physical)
    """
    is_fin = pl.col("is_financial_collateral_type")

    # Single group_by: classify level, then aggregate once
    all_coll = (
        collateral.with_columns(
            beneficiary_level_expr().alias("_level"),
        )
        .group_by(["_level", "beneficiary_reference"])
        .agg(
            [
                pl.col("effectively_secured").filter(is_fin).sum().alias("_eff_fin"),
                (pl.col("effectively_secured") * pl.col("collateral_lgd"))
                .filter(is_fin)
                .sum()
                .alias("_wlgd_fin"),
                pl.col("effectively_secured").filter(~is_fin).sum().alias("_eff_nf"),
                (pl.col("effectively_secured") * pl.col("collateral_lgd"))
                .filter(~is_fin)
                .sum()
                .alias("_wlgd_nf"),
                pl.col("adjusted_value").filter(~is_fin).sum().alias("_raw_nf"),
            ]
        )
    )

    # Split the small aggregated result and rename for per-level columns
    _lgd_agg_cols = ["_eff_fin", "_wlgd_fin", "_eff_nf", "_wlgd_nf", "_raw_nf"]

    coll_direct = (
        all_coll.filter(pl.col("_level") == "direct")
        .drop("_level")
        .rename({c: f"{c}_direct" for c in _lgd_agg_cols})
    )
    coll_facility = (
        all_coll.filter(pl.col("_level") == "facility")
        .drop("_level")
        .rename({c: f"{c}_facility" for c in _lgd_agg_cols})
    )
    coll_counterparty = (
        all_coll.filter(pl.col("_level") == "counterparty")
        .drop("_level")
        .rename({c: f"{c}_counterparty" for c in _lgd_agg_cols})
    )

    # Use pre-computed EAD totals, or compute if not provided
    if facility_ead_totals is not None:
        facility_ead_totals = facility_ead_totals.select(
            pl.col("parent_facility_reference"),
            pl.col("_fac_ead_total").alias("facility_ead_total"),
        )
    else:
        facility_ead_totals = (
            exposures.filter(pl.col("parent_facility_reference").is_not_null())
            .group_by("parent_facility_reference")
            .agg(
                [
                    pl.col("ead_gross").sum().alias("facility_ead_total"),
                ]
            )
        )

    if cp_ead_totals is not None:
        counterparty_ead_totals = cp_ead_totals.select(
            pl.col("counterparty_reference"),
            pl.col("_cp_ead_total").alias("cp_ead_total"),
        )
    else:
        counterparty_ead_totals = exposures.group_by("counterparty_reference").agg(
            [
                pl.col("ead_gross").sum().alias("cp_ead_total"),
            ]
        )

    # Join direct-level collateral
    exposures = exposures.join(
        coll_direct,
        left_on="exposure_reference",
        right_on="beneficiary_reference",
        how="left",
    )

    # Join facility-level collateral and totals
    exposures = exposures.join(
        coll_facility,
        left_on="parent_facility_reference",
        right_on="beneficiary_reference",
        how="left",
    ).join(
        facility_ead_totals,
        on="parent_facility_reference",
        how="left",
    )

    # Join counterparty-level collateral and totals
    exposures = exposures.join(
        coll_counterparty,
        left_on="counterparty_reference",
        right_on="beneficiary_reference",
        how="left",
    ).join(
        counterparty_ead_totals,
        on="counterparty_reference",
        how="left",
    )

    # Fill nulls for all aggregate columns
    fill_cols = []
    for level in ["direct", "facility", "counterparty"]:
        for c in _lgd_agg_cols:
            fill_cols.append(pl.col(f"{c}_{level}").fill_null(0.0))
    fill_cols.extend(
        [
            pl.col("facility_ead_total").fill_null(0.0),
            pl.col("cp_ead_total").fill_null(0.0),
        ]
    )
    exposures = exposures.with_columns(fill_cols)

    # Calculate allocation weights for pro-rata distribution
    exposures = exposures.with_columns(
        [
            pl.when(pl.col("facility_ead_total") > 0)
            .then(pl.col("ead_gross") / pl.col("facility_ead_total"))
            .otherwise(pl.lit(0.0))
            .alias("facility_weight"),
            pl.when(pl.col("cp_ead_total") > 0)
            .then(pl.col("ead_gross") / pl.col("cp_ead_total"))
            .otherwise(pl.lit(0.0))
            .alias("cp_weight"),
        ]
    )

    # Allocate financial collateral (no min threshold)
    exposures = exposures.with_columns(
        [
            (
                pl.col("_eff_fin_direct")
                + (pl.col("_eff_fin_facility") * pl.col("facility_weight"))
                + (pl.col("_eff_fin_counterparty") * pl.col("cp_weight"))
            ).alias("eff_fin_allocated"),
            (
                pl.col("_wlgd_fin_direct")
                + (pl.col("_wlgd_fin_facility") * pl.col("facility_weight"))
                + (pl.col("_wlgd_fin_counterparty") * pl.col("cp_weight"))
            ).alias("wlgd_fin_allocated"),
        ]
    )

    # Allocate non-financial collateral
    exposures = exposures.with_columns(
        [
            (
                pl.col("_eff_nf_direct")
                + (pl.col("_eff_nf_facility") * pl.col("facility_weight"))
                + (pl.col("_eff_nf_counterparty") * pl.col("cp_weight"))
            ).alias("eff_nf_allocated"),
            (
                pl.col("_wlgd_nf_direct")
                + (pl.col("_wlgd_nf_facility") * pl.col("facility_weight"))
                + (pl.col("_wlgd_nf_counterparty") * pl.col("cp_weight"))
            ).alias("wlgd_nf_allocated"),
            (
                pl.col("_raw_nf_direct")
                + (pl.col("_raw_nf_facility") * pl.col("facility_weight"))
                + (pl.col("_raw_nf_counterparty") * pl.col("cp_weight"))
            ).alias("raw_nf_allocated"),
        ]
    )

    # Apply min threshold: if raw non-financial < 30% of EAD, zero out non-financial
    exposures = exposures.with_columns(
        [
            pl.when(pl.col("raw_nf_allocated") >= 0.30 * pl.col("ead_gross"))
            .then(pl.col("eff_nf_allocated"))
            .otherwise(pl.lit(0.0))
            .alias("eff_nf_final"),
            pl.when(pl.col("raw_nf_allocated") >= 0.30 * pl.col("ead_gross"))
            .then(pl.col("wlgd_nf_allocated"))
            .otherwise(pl.lit(0.0))
            .alias("wlgd_nf_final"),
        ]
    )

    # Combine financial + non-financial
    exposures = exposures.with_columns(
        [
            (pl.col("eff_fin_allocated") + pl.col("eff_nf_final")).alias(
                "total_collateral_for_lgd"
            ),
            (pl.col("wlgd_fin_allocated") + pl.col("wlgd_nf_final")).alias(
                "total_weighted_lgd_sum"
            ),
        ]
    )

    # Calculate average LGD for secured portion
    exposures = exposures.with_columns(
        [
            pl.when(pl.col("total_collateral_for_lgd") > 0)
            .then(pl.col("total_weighted_lgd_sum") / pl.col("total_collateral_for_lgd"))
            .otherwise(pl.lit(0.45))
            .alias("lgd_secured"),
        ]
    )

    # Drop intermediate columns
    drop_cols = []
    for level in ["direct", "facility", "counterparty"]:
        for c in _lgd_agg_cols:
            drop_cols.append(f"{c}_{level}")
    drop_cols.extend(
        [
            "facility_ead_total",
            "cp_ead_total",
            "facility_weight",
            "cp_weight",
            "eff_fin_allocated",
            "wlgd_fin_allocated",
            "eff_nf_allocated",
            "wlgd_nf_allocated",
            "raw_nf_allocated",
            "eff_nf_final",
            "wlgd_nf_final",
            "total_weighted_lgd_sum",
        ]
    )
    exposures = exposures.drop(drop_cols)

    return exposures


def _allocate_collateral_multi_level_for_ead(
    exposures: pl.LazyFrame,
    eligible_collateral: pl.LazyFrame,
    facility_ead_totals: pl.LazyFrame | None = None,
    cp_ead_totals: pl.LazyFrame | None = None,
) -> pl.LazyFrame:
    """
    Allocate eligible financial collateral from multiple linking levels for SA EAD reduction.

    Uses a single group_by on (_level, beneficiary_reference) to traverse
    the heavy upstream collateral plan once, then splits the small aggregated
    result for per-level joins.
    """
    val_expr = pl.coalesce(
        pl.col("value_after_maturity_adj"),
        pl.col("value_after_haircut"),
    )

    # Single group_by: classify level, then aggregate once
    all_coll = (
        eligible_collateral.with_columns(
            beneficiary_level_expr().alias("_level"),
        )
        .group_by(["_level", "beneficiary_reference"])
        .agg(
            [
                val_expr.sum().alias("_coll_val"),
                pl.col("market_value").sum().alias("_mv_val"),
            ]
        )
    )

    # Split the small aggregated result
    coll_direct = all_coll.filter(pl.col("_level") == "direct").select(
        "beneficiary_reference",
        pl.col("_coll_val").alias("_coll_direct"),
        pl.col("_mv_val").alias("_mv_direct"),
    )
    coll_facility = all_coll.filter(pl.col("_level") == "facility").select(
        "beneficiary_reference",
        pl.col("_coll_val").alias("_coll_facility"),
        pl.col("_mv_val").alias("_mv_facility"),
    )
    coll_counterparty = all_coll.filter(pl.col("_level") == "counterparty").select(
        "beneficiary_reference",
        pl.col("_coll_val").alias("_coll_counterparty"),
        pl.col("_mv_val").alias("_mv_counterparty"),
    )

    # --- EAD totals for pro-rata allocation (use pre-computed or compute) ---
    exp_schema = exposures.collect_schema()
    if facility_ead_totals is None:
        if "parent_facility_reference" in exp_schema.names():
            facility_ead_totals = (
                exposures.filter(pl.col("parent_facility_reference").is_not_null())
                .group_by("parent_facility_reference")
                .agg(
                    pl.col("ead_gross").sum().alias("_fac_ead_total"),
                )
            )
        else:
            facility_ead_totals = pl.LazyFrame(
                schema={
                    "parent_facility_reference": pl.String,
                    "_fac_ead_total": pl.Float64,
                }
            )

    if cp_ead_totals is None:
        cp_ead_totals = exposures.group_by("counterparty_reference").agg(
            pl.col("ead_gross").sum().alias("_cp_ead_total"),
        )

    # --- Join direct-level ---
    exposures = exposures.join(
        coll_direct,
        left_on="exposure_reference",
        right_on="beneficiary_reference",
        how="left",
    )

    # --- Join facility-level and totals ---
    if "parent_facility_reference" in exp_schema.names():
        exposures = exposures.join(
            coll_facility,
            left_on="parent_facility_reference",
            right_on="beneficiary_reference",
            how="left",
        ).join(
            facility_ead_totals,
            on="parent_facility_reference",
            how="left",
        )
    else:
        exposures = exposures.with_columns(
            [
                pl.lit(0.0).alias("_coll_facility"),
                pl.lit(0.0).alias("_mv_facility"),
                pl.lit(0.0).alias("_fac_ead_total"),
            ]
        )

    # --- Join counterparty-level and totals ---
    exposures = exposures.join(
        coll_counterparty,
        left_on="counterparty_reference",
        right_on="beneficiary_reference",
        how="left",
    ).join(
        cp_ead_totals,
        on="counterparty_reference",
        how="left",
    )

    # --- Fill nulls ---
    exposures = exposures.with_columns(
        [
            pl.col("_coll_direct").fill_null(0.0),
            pl.col("_mv_direct").fill_null(0.0),
            pl.col("_coll_facility").fill_null(0.0),
            pl.col("_mv_facility").fill_null(0.0),
            pl.col("_coll_counterparty").fill_null(0.0),
            pl.col("_mv_counterparty").fill_null(0.0),
            pl.col("_fac_ead_total").fill_null(0.0),
            pl.col("_cp_ead_total").fill_null(0.0),
        ]
    )

    # --- Pro-rata weights ---
    exposures = exposures.with_columns(
        [
            pl.when(pl.col("_fac_ead_total") > 0)
            .then(pl.col("ead_gross") / pl.col("_fac_ead_total"))
            .otherwise(pl.lit(0.0))
            .alias("_fac_weight"),
            pl.when(pl.col("_cp_ead_total") > 0)
            .then(pl.col("ead_gross") / pl.col("_cp_ead_total"))
            .otherwise(pl.lit(0.0))
            .alias("_cp_weight"),
        ]
    )

    # --- Combine all levels ---
    exposures = exposures.with_columns(
        [
            (
                pl.col("_coll_direct")
                + (pl.col("_coll_facility") * pl.col("_fac_weight"))
                + (pl.col("_coll_counterparty") * pl.col("_cp_weight"))
            ).alias("collateral_adjusted_value"),
            (
                pl.col("_mv_direct")
                + (pl.col("_mv_facility") * pl.col("_fac_weight"))
                + (pl.col("_mv_counterparty") * pl.col("_cp_weight"))
            ).alias("collateral_market_value"),
        ]
    )

    # --- Drop intermediate columns ---
    exposures = exposures.drop(
        [
            "_coll_direct",
            "_mv_direct",
            "_coll_facility",
            "_mv_facility",
            "_coll_counterparty",
            "_mv_counterparty",
            "_fac_ead_total",
            "_cp_ead_total",
            "_fac_weight",
            "_cp_weight",
        ]
    )

    return exposures
