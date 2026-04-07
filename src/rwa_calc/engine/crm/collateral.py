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
- A-IRB LGD Modelling Collateral Method (Art. 169A/169B)
- Overcollateralisation and minimum threshold checks

References:
    CRR Art. 223-224, 230: Collateral haircuts and allocation
    CRR Art. 161: F-IRB supervisory LGD
    PRA PS1/26 Art. 169A/169B: LGD Modelling Collateral Method
    CRE22.52-53, CRE32.9-12: Basel 3.1 equivalents
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.domain.enums import AIRBCollateralMethod, ApproachType
from rwa_calc.engine.crm.constants import (
    CRM_ALLOC_COLUMNS,
    MIN_COLLATERALISATION_THRESHOLDS,
    NON_ELIGIBLE_RE_TYPES,
    WATERFALL_ORDER,
    beneficiary_level_expr,
    collateral_category_expr,
    collateral_lgd_expr,
    is_financial_collateral_type_expr,
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
    build_exposure_lookups_fn: Callable,
    join_collateral_to_lookups_fn: Callable,
    resolve_pledge_from_joined_fn: Callable,
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

    # Materialise the small lookup frames in parallel to prevent plan-tree
    # duplication. Each lookup is referenced in multiple downstream joins;
    # without this, Polars re-evaluates the group_by/select at each reference.
    # collect_all runs all 3 concurrently and enables CSE on shared upstream.
    direct_df, facility_df, cp_df = pl.collect_all([direct_lookup, facility_lookup, cp_lookup])
    direct_lookup = direct_df.lazy()
    facility_lookup = facility_df.lazy()
    cp_lookup = cp_df.lazy()

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

    # Apply maturity mismatch using actual exposure maturity (Art. 238)
    adjusted_collateral = haircut_calculator.apply_maturity_mismatch(adjusted_collateral, config)

    return _apply_collateral_unified(
        exposures,
        adjusted_collateral,
        config,
        facility_ead_totals,
        cp_ead_totals,
        is_basel_3_1,
    )


def apply_firb_supervisory_lgd_no_collateral(
    exposures: pl.LazyFrame,
    is_basel_3_1: bool,
    config: CalculationConfig | None = None,
) -> pl.LazyFrame:
    """
    Apply F-IRB supervisory LGD when no collateral is available.

    For F-IRB exposures without collateral, uses supervisory LGD values:
    - CRR Art. 161(1)(a): Senior unsecured 45%, Subordinated 75%
    - Basel 3.1 Art. 161(1)(a)/(aa): FSE senior 45%, non-FSE senior 40%, Sub 75%

    For A-IRB exposures under Basel 3.1:
    - LGD Modelling + insufficient data (Art. 169B): own lgd_unsecured as LGDU
    - Foundation election: supervisory LGDU (same as F-IRB)
    - LGD Modelling + sufficient data: keep modelled LGD unchanged

    Under CRR, A-IRB exposures always keep their modelled LGD.

    Args:
        exposures: Exposures with lgd_pre_crm
        is_basel_3_1: Whether Basel 3.1 framework applies
        config: CalculationConfig (optional, for AIRB collateral method)

    Returns:
        Exposures with lgd_post_crm set for F-IRB (and qualifying A-IRB)
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

    # Determine LGD based on seniority for F-IRB
    schema_names = set(exposures.collect_schema().names())
    is_subordinated = (
        pl.col("seniority").fill_null("").str.to_lowercase().is_in(["subordinated", "junior"])
        if "seniority" in schema_names
        else pl.lit(False)
    )

    # Under Basel 3.1, FSE senior unsecured = 45% (Art. 161(1)(a));
    # non-FSE senior unsecured = 40% (Art. 161(1)(aa)).
    # Under CRR, all senior unsecured = 45% (no FSE distinction).
    if is_basel_3_1 and "cp_is_financial_sector_entity" in schema_names:
        lgd_senior_fse = lgd_values["unsecured_fse"]
        lgd_senior_expr = (
            pl.when(pl.col("cp_is_financial_sector_entity").fill_null(False))
            .then(pl.lit(lgd_senior_fse))
            .otherwise(pl.lit(lgd_senior))
        )
    else:
        lgd_senior_expr = pl.lit(lgd_senior)

    # --- Determine AIRB treatment (Art. 169A/169B) ---
    airb_method = config.airb_collateral_method if config else None
    is_airb = pl.col("approach") == ApproachType.AIRB.value

    if is_basel_3_1 and airb_method == AIRBCollateralMethod.FOUNDATION:
        # AIRB Foundation election: use supervisory LGDU (same as FIRB)
        airb_lgd_expr = (
            pl.when(is_subordinated)
            .then(pl.lit(0.75))
            .otherwise(lgd_senior_expr)
        )
        uses_formula = (pl.col("approach") == ApproachType.FIRB.value) | is_airb
    elif (
        is_basel_3_1
        and airb_method == AIRBCollateralMethod.LGD_MODELLING
        and "has_sufficient_collateral_data" in schema_names
    ):
        # Art. 169B: AIRB with insufficient data → use own lgd_unsecured
        _is_169b = is_airb & (
            pl.col("has_sufficient_collateral_data").fill_null(True) == False  # noqa: E712
        )
        own_lgdu = (
            pl.coalesce(pl.col("lgd_unsecured"), pl.col("lgd_pre_crm"))
            if "lgd_unsecured" in schema_names
            else pl.col("lgd_pre_crm")
        )
        # Build the expression: FIRB uses supervisory, AIRB 169B uses own, AIRB full keeps modelled
        exposures = exposures.with_columns(
            [
                pl.when((pl.col("approach") == ApproachType.FIRB.value) & is_subordinated)
                .then(pl.lit(0.75))
                .when(pl.col("approach") == ApproachType.FIRB.value)
                .then(lgd_senior_expr)
                .when(_is_169b & is_subordinated)
                .then(pl.lit(0.75))
                .when(_is_169b)
                .then(own_lgdu)
                .otherwise(pl.col("lgd_pre_crm"))
                .alias("lgd_post_crm"),
            ]
        )
        return exposures
    else:
        # CRR or no method: standard FIRB/AIRB split
        uses_formula = pl.col("approach") == ApproachType.FIRB.value

    exposures = exposures.with_columns(
        [
            pl.when(uses_formula & is_subordinated)
            .then(pl.lit(0.75))  # Subordinated (same both frameworks)
            .when(uses_formula)
            .then(lgd_senior_expr)  # Senior unsecured (FSE-aware under B31)
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
    config: CalculationConfig,
    facility_ead_totals: pl.LazyFrame,
    cp_ead_totals: pl.LazyFrame,
    is_basel_3_1: bool,
) -> pl.LazyFrame:
    """
    Unified EAD + LGD collateral allocation in a single pass.

    Performs a single group_by over all collateral levels (direct, facility,
    counterparty) and joins back to exposures for both SA EAD reduction and
    F-IRB LGD calculation.

    Art. 231 sequential fill: when multiple collateral types secure an
    exposure, each type absorbs exposure starting from the lowest LGDS.
    The institution receives the most favourable ordering (lowest LGDS first):
    financial (0%) -> covered_bond (11.25%) -> receivables -> real_estate
    -> other_physical.  This replaces the former pro-rata allocation.
    """
    lgd_values = supervisory_lgd_values(is_basel_3_1)
    lgd_unsecured = lgd_values["unsecured"]

    # LGDS values per waterfall category (Art. 230/231)
    lgds = {key: lgd_values[key] for _, key, _ in WATERFALL_ORDER}

    # Under Basel 3.1, FSE senior unsecured LGDU = 45% (Art. 161(1)(a));
    # non-FSE = 40% (Art. 161(1)(aa)). Under CRR, all = 45%.
    exposure_schema = exposures.collect_schema()
    _has_fse_col = is_basel_3_1 and "cp_is_financial_sector_entity" in exposure_schema.names()
    if _has_fse_col:
        lgd_unsecured_fse = lgd_values["unsecured_fse"]

    collateral_schema = adjusted_collateral.collect_schema()

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
    cat = pl.col("_coll_category")

    # Build per-category effectively_secured aggregates for Art. 231 waterfall
    waterfall_aggs = []
    for cat_values, _lgds_key, suffix in WATERFALL_ORDER:
        waterfall_aggs.append(
            pl.col("effectively_secured")
            .filter(cat.is_in(cat_values))
            .sum()
            .alias(f"_e{suffix}")
        )

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
                # Raw non-financial adjusted_value for 30% threshold
                pl.col("adjusted_value").filter(~is_fin).sum().alias("_rn"),
                # Per-type collateral values for COREP
                pl.col("adjusted_value")
                .filter(cat == "financial")
                .sum()
                .alias("_adj_fin"),
                pl.col("adjusted_value")
                .filter(cat == "cash")
                .sum()
                .alias("_adj_cash"),
                pl.col("adjusted_value")
                .filter(cat == "real_estate")
                .sum()
                .alias("_adj_re"),
                pl.col("adjusted_value")
                .filter(cat == "receivables")
                .sum()
                .alias("_adj_rec"),
                pl.col("adjusted_value")
                .filter(cat == "other_physical")
                .sum()
                .alias("_adj_oth"),
            ]
            + waterfall_aggs
        )
    )

    _wf_suffixes = [suffix for _, _, suffix in WATERFALL_ORDER]
    _agg = [
        "_cv",
        "_mv",
        "_rn",
        "_adj_fin",
        "_adj_cash",
        "_adj_re",
        "_adj_rec",
        "_adj_oth",
    ] + [f"_e{s}" for s in _wf_suffixes]

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

    combine_exprs = [
        _sum3("_cv").alias("collateral_adjusted_value"),
        _sum3("_mv").alias("collateral_market_value"),
        _sum3("_adj_fin").alias("collateral_financial_value"),
        _sum3("_adj_cash").alias("collateral_cash_value"),
        _sum3("_adj_re").alias("collateral_re_value"),
        _sum3("_adj_rec").alias("collateral_receivables_value"),
        _sum3("_adj_oth").alias("collateral_other_physical_value"),
        _sum3("_rn").alias("_raw_nf_a"),
    ]
    # Per-category effectively_secured after multi-level combination
    for suffix in _wf_suffixes:
        combine_exprs.append(_sum3(f"_e{suffix}").alias(f"_eff_{suffix}_a"))
    exposures = exposures.with_columns(combine_exprs)

    # Per-type minimum collateralisation thresholds (Art. 230)
    # Art. 230 requires the threshold to apply per collateral type, not across
    # the combined non-financial pool.  Each type (real_estate, other_physical)
    # must independently meet its 30% threshold to be eligible for LGDS
    # reduction.  Financial, covered_bond, and receivables have no threshold.
    _type_threshold: dict[str, tuple[float, str]] = {
        "re": (MIN_COLLATERALISATION_THRESHOLDS["real_estate"], "collateral_re_value"),
        "op": (
            MIN_COLLATERALISATION_THRESHOLDS["other_physical"],
            "collateral_other_physical_value",
        ),
    }
    nf_threshold_exprs = []
    for suffix in _wf_suffixes:
        if suffix not in _type_threshold:
            continue  # No threshold for fin/cb/rec
        threshold, raw_col = _type_threshold[suffix]
        if threshold <= 0:
            continue
        col_name = f"_eff_{suffix}_a"
        nf_threshold_exprs.append(
            pl.when(pl.col(raw_col) >= threshold * pl.col("ead_gross"))
            .then(pl.col(col_name))
            .otherwise(pl.lit(0.0))
            .alias(col_name)
        )
    if nf_threshold_exprs:
        exposures = exposures.with_columns(nf_threshold_exprs)

    # --- Art. 231 sequential fill (waterfall) ---
    # Allocate from lowest LGDS to highest. Each category absorbs up to
    # min(category_total, remaining_exposure). Uses the cumulative-cap
    # trick: es_i = min(cum_through_i, EAD) - min(cum_through_i-1, EAD).
    ead = pl.col("ead_gross")
    cum = pl.lit(0.0)
    es_exprs: list[pl.Expr] = []
    for suffix in _wf_suffixes:
        prev_cum = cum
        cum = cum + pl.col(f"_eff_{suffix}_a")
        es_i = pl.min_horizontal(cum, ead) - pl.min_horizontal(prev_cum, ead)
        es_exprs.append(es_i.alias(f"_es_{suffix}"))

    total_secured_expr = pl.min_horizontal(cum, ead)

    # Blended lgd_secured = sum(lgds_i * es_i) / total_secured
    lgd_num = pl.lit(0.0)
    for (_, lgds_key, suffix) in WATERFALL_ORDER:
        lgd_num = lgd_num + pl.lit(lgds[lgds_key]) * pl.col(f"_es_{suffix}")

    # Compute sequential allocations, then total + lgd_secured
    exposures = exposures.with_columns(es_exprs)
    exposures = exposures.with_columns(
        [
            total_secured_expr.alias("total_collateral_for_lgd"),
            pl.when(total_secured_expr > 0)
            .then(lgd_num / total_secured_expr)
            .otherwise(pl.lit(lgd_unsecured))
            .alias("lgd_secured"),
        ]
    )

    # --- Drop intermediate allocation columns ---
    # Preserve _es_* columns (renamed to crm_alloc_*) for the A-IRB blended
    # LGD floor (Art. 164(4)(c)).  These encode the dollar amount of EAD
    # absorbed by each collateral category in the Art. 231 waterfall.
    drop_cols = (
        [f"{c}_{sfx}" for sfx in ["d", "f", "c"] for c in _agg]
        + ["_fac_ead_total", "_cp_ead_total", "_fw", "_cw", "_raw_nf_a"]
        + [f"_eff_{s}_a" for s in _wf_suffixes]
    )
    exposures = exposures.drop(drop_cols)
    exposures = exposures.rename(
        {f"_es_{s}": CRM_ALLOC_COLUMNS[s] for s in _wf_suffixes}
    )

    # --- Apply EAD reduction + determine seniority-based LGDU ---
    # Supervisory LGDU for unsecured portion: FSE-aware under Basel 3.1
    # (Art. 161(1)(a) vs (aa))
    if _has_fse_col:
        supervisory_lgdu_expr = (
            pl.when(pl.col("cp_is_financial_sector_entity").fill_null(False))
            .then(pl.lit(lgd_unsecured_fse))
            .otherwise(pl.lit(lgd_unsecured))
        )
    else:
        supervisory_lgdu_expr = pl.lit(lgd_unsecured)

    # --- Determine which AIRB exposures use the Foundation formula ---
    # Art. 169A/169B (Basel 3.1 only): AIRB exposures may use the Foundation
    # Collateral Method formula under two scenarios:
    #   (1) Foundation election: firm opts for FCM instead of LGD Modelling
    #   (2) Art. 169B fallback: insufficient data → FCM formula with own LGDU
    # Under CRR, AIRB is free-form — own LGD always kept unchanged.
    exposure_schema = exposures.collect_schema()
    _has_lgd_unsecured_col = "lgd_unsecured" in exposure_schema.names()
    _has_suff_data_col = "has_sufficient_collateral_data" in exposure_schema.names()

    airb_method = config.airb_collateral_method
    is_airb = pl.col("approach") == ApproachType.AIRB.value

    # AIRB exposures that use the Foundation formula (like FIRB):
    if is_basel_3_1 and airb_method == AIRBCollateralMethod.FOUNDATION:
        # All AIRB exposures use Foundation Collateral Method with supervisory LGDU
        _airb_uses_formula = is_airb
        _airb_own_lgdu = False  # Use supervisory LGDU
    elif is_basel_3_1 and airb_method == AIRBCollateralMethod.LGD_MODELLING:
        # Art. 169B: AIRB with insufficient data → Foundation formula with own LGDU
        if _has_suff_data_col:
            _airb_uses_formula = is_airb & (
                pl.col("has_sufficient_collateral_data").fill_null(True) == False  # noqa: E712
            )
        else:
            _airb_uses_formula = pl.lit(False)  # No flag → assume sufficient data
        _airb_own_lgdu = True  # Art. 169B(2)(c): use firm's own unsecured LGD
    else:
        # CRR or None: AIRB keeps own modelled LGD, no formula applied
        _airb_uses_formula = pl.lit(False)
        _airb_own_lgdu = False

    # Combined condition: FIRB OR qualifying AIRB exposures use the formula
    _uses_formula = (pl.col("approach") == ApproachType.FIRB.value) | _airb_uses_formula

    # Build per-exposure LGDU expression
    # For AIRB Art. 169B: LGDU = own lgd_unsecured (Art. 169B(2)(c))
    # For FIRB and AIRB Foundation: LGDU = supervisory value
    is_subordinated = pl.col("seniority").str.to_lowercase().is_in(["subordinated", "junior"])

    if _airb_own_lgdu and _has_lgd_unsecured_col:
        # Art. 169B: AIRB exposures with insufficient data use own lgd_unsecured,
        # falling back to lgd_pre_crm if lgd_unsecured not provided.
        own_lgdu = pl.coalesce(pl.col("lgd_unsecured"), pl.col("lgd_pre_crm"))
        lgdu_expr = (
            pl.when(is_subordinated)
            .then(pl.lit(0.75))
            .when(_airb_uses_formula)
            .then(own_lgdu)
            .otherwise(supervisory_lgdu_expr)
        )
    else:
        lgdu_expr = (
            pl.when(is_subordinated)
            .then(pl.lit(0.75))
            .otherwise(supervisory_lgdu_expr)
        )

    exposures = exposures.with_columns(
        [
            pl.when(pl.col("approach") == ApproachType.SA.value)
            .then((pl.col("ead_gross") - pl.col("collateral_adjusted_value")).clip(lower_bound=0))
            .otherwise(pl.col("ead_gross"))
            .alias("ead_after_collateral"),
            lgdu_expr.alias("lgd_unsecured"),
        ]
    )

    # --- Calculate LGD post-CRM + audit ---
    # LGD* formula (Art. 230/231) applies to FIRB and qualifying AIRB exposures.
    # Non-qualifying AIRB and SA keep lgd_pre_crm.
    lgd_star_expr = (
        (
            pl.col("lgd_secured")
            * pl.col("total_collateral_for_lgd").clip(upper_bound=pl.col("ead_gross"))
        )
        + (
            pl.col("lgd_unsecured")
            * (pl.col("ead_gross") - pl.col("total_collateral_for_lgd")).clip(lower_bound=0)
        )
    ) / pl.col("ead_gross")

    exposures = exposures.with_columns(
        [
            pl.when(
                _uses_formula & (pl.col("ead_gross") > 0) & (pl.col("total_collateral_for_lgd") > 0)
            )
            .then(lgd_star_expr)
            .when(_uses_formula & (pl.col("ead_gross") > 0))
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
