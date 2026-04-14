"""
Guarantee substitution for CRM processing.

Pipeline position:
    Collateral -> apply_guarantees -> Finalise EAD

Key responsibilities:
- Multi-level guarantee resolution (direct / facility / counterparty)
- Multi-guarantor row splitting
- Cross-approach CCF substitution (IRB exposure + SA guarantor)
- Guarantor attribute lookup for risk weight substitution

References:
    CRR Art. 213-217: Unfunded credit protection
    CRE22.70-85: Basel 3.1 guarantee substitution
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.data.schemas import DIRECT_BENEFICIARY_TYPES
from rwa_calc.data.tables.eu_sovereign import (
    build_eu_domestic_currency_expr,
    denomination_currency_expr,
)
from rwa_calc.data.tables.haircuts import FX_HAIRCUT, RESTRUCTURING_EXCLUSION_HAIRCUT
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.ccf import (
    drawn_for_ead,
    interest_for_ead,
    on_balance_ead,
    sa_ccf_expression,
)
from rwa_calc.engine.classifier import ENTITY_TYPE_TO_SA_CLASS

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


def apply_guarantees(
    exposures: pl.LazyFrame,
    guarantees: pl.LazyFrame,
    counterparty_lookup: pl.LazyFrame,
    config: CalculationConfig,
    rating_inheritance: pl.LazyFrame | None = None,
) -> pl.LazyFrame:
    """
    Apply guarantee substitution.

    For guaranteed portion, substitute borrower RW with guarantor RW.

    Args:
        exposures: Exposures with EAD
        guarantees: Guarantee data
        counterparty_lookup: For guarantor risk weights
        config: Calculation configuration
        rating_inheritance: For guarantor CQS lookup

    Returns:
        Exposures with guarantee effects applied
    """
    # Default protection_type to "guarantee" if not provided (backward compatibility)
    guar_input_schema = guarantees.collect_schema()
    if "protection_type" not in guar_input_schema.names():
        guarantees = guarantees.with_columns(
            pl.lit("guarantee").alias("protection_type"),
        )
    else:
        # Fill nulls with "guarantee" (default for legacy data)
        guarantees = guarantees.with_columns(
            pl.col("protection_type").fill_null("guarantee").alias("protection_type"),
        )

    guarantees = _resolve_guarantees_multi_level(guarantees, exposures)

    # Apply haircuts to guarantee amounts BEFORE splitting (Art. 233).
    # Haircuts reduce the nominal credit protection value G, then capping
    # at EAD happens inside the split. This ensures large cross-currency
    # guarantees still fully cover smaller exposures after the haircut.
    guarantees = _apply_fx_haircut_to_guarantees(guarantees, exposures)
    guarantees = _apply_restructuring_haircut_to_guarantees(guarantees)

    exposures = exposures.with_columns(
        pl.col("exposure_reference").alias("parent_exposure_reference"),
    )

    exposures = _apply_guarantee_splits(guarantees, exposures)

    # Look up guarantor's entity type, country code, and CQS for risk weight substitution
    # Join with counterparty to get guarantor's entity type and country
    cp_schema = counterparty_lookup.collect_schema()
    cp_select_cols = [
        pl.col("counterparty_reference"),
        pl.col("entity_type").str.to_lowercase().alias("guarantor_entity_type"),
    ]
    if "country_code" in cp_schema.names():
        cp_select_cols.append(pl.col("country_code").alias("guarantor_country_code"))
    if "is_ccp_client_cleared" in cp_schema.names():
        cp_select_cols.append(
            pl.col("is_ccp_client_cleared").alias("guarantor_is_ccp_client_cleared")
        )

    exposures = exposures.join(
        counterparty_lookup.select(cp_select_cols),
        left_on="guarantor_reference",
        right_on="counterparty_reference",
        how="left",
    )

    # Ensure optional guarantor columns exist (fill null if not in counterparty data)
    post_join_names = exposures.collect_schema().names()
    missing_guarantor_cols = []
    if "guarantor_country_code" not in post_join_names:
        missing_guarantor_cols.append(pl.lit(None).cast(pl.String).alias("guarantor_country_code"))
    if "guarantor_is_ccp_client_cleared" not in post_join_names:
        missing_guarantor_cols.append(
            pl.lit(None).cast(pl.Boolean).alias("guarantor_is_ccp_client_cleared")
        )
    if missing_guarantor_cols:
        exposures = exposures.with_columns(missing_guarantor_cols)

    # Look up guarantor's CQS, PD, and internal_pd from ratings
    if rating_inheritance is not None:
        ri_schema = rating_inheritance.collect_schema()
        ri_cols = [
            pl.col("counterparty_reference"),
            pl.col("cqs").alias("guarantor_cqs"),
        ]
        # Guarantor PD needed for Basel 3.1 parameter substitution (CRE22.70-85)
        if "pd" in ri_schema.names():
            ri_cols.append(pl.col("pd").alias("guarantor_pd"))
        # Internal PD for approach determination (IRB requires internal rating)
        if "internal_pd" in ri_schema.names():
            ri_cols.append(pl.col("internal_pd").alias("guarantor_internal_pd"))

        exposures = exposures.join(
            rating_inheritance.select(ri_cols),
            left_on="guarantor_reference",
            right_on="counterparty_reference",
            how="left",
        )

        ri_names = ri_schema.names()
        missing_rating_cols = []
        if "pd" not in ri_names:
            missing_rating_cols.append(pl.lit(None).cast(pl.Float64).alias("guarantor_pd"))
        if "internal_pd" not in ri_names:
            missing_rating_cols.append(pl.lit(None).cast(pl.Float64).alias("guarantor_internal_pd"))
        if missing_rating_cols:
            exposures = exposures.with_columns(missing_rating_cols)
    else:
        exposures = exposures.with_columns(
            [
                pl.lit(None).cast(pl.Int8).alias("guarantor_cqs"),
                pl.lit(None).cast(pl.Float64).alias("guarantor_pd"),
                pl.lit(None).cast(pl.Float64).alias("guarantor_internal_pd"),
            ]
        )

    exposures = exposures.with_columns(
        [
            pl.col("guarantor_entity_type").fill_null("").alias("guarantor_entity_type"),
        ]
    )

    # Derive guarantor's exposure class from their entity type
    # This is needed for post-CRM reporting where the guaranteed portion
    # is reported under the guarantor's exposure class
    exposures = exposures.with_columns(
        [
            pl.col("guarantor_entity_type")
            .replace_strict(ENTITY_TYPE_TO_SA_CLASS, default="")
            .alias("guarantor_exposure_class"),
        ]
    )

    # Determine guarantor approach from IRB permissions AND rating type.
    # A guarantor is treated under IRB only if:
    # 1. The firm has IRB permission for the guarantor's exposure class, AND
    # 2. The guarantor has an internal rating (PD) — indicating the firm
    #    actively rates this counterparty under its IRB model.
    # Counterparties with only external ratings (CQS) are treated under SA.
    irb_exposure_class_values = set()
    for ec, approaches in config.irb_permissions.permissions.items():
        if ApproachType.FIRB in approaches or ApproachType.AIRB in approaches:
            irb_exposure_class_values.add(ec.value)

    # Art. 114(4)/(7): an EU/UK domestic-currency CGCB guarantor must receive 0% RW
    # via the SA short-circuit, even if the guarantor has an internal PD that would
    # otherwise route to IRB parameter substitution.
    schema_names = exposures.collect_schema().names()
    has_currency = "original_currency" in schema_names or "currency" in schema_names
    if has_currency:
        ccy_expr = denomination_currency_expr(schema_names)
        cgcb = ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value
        is_uk_domestic_cgcb_guarantor = (
            (pl.col("guarantor_exposure_class") == cgcb)
            & (pl.col("guarantor_country_code").fill_null("") == "GB")
            & (ccy_expr == "GBP")
        )
        is_eu_domestic_cgcb_guarantor = (
            pl.col("guarantor_exposure_class") == cgcb
        ) & build_eu_domestic_currency_expr("guarantor_country_code", ccy_expr)
        is_domestic_cgcb_guarantor = is_uk_domestic_cgcb_guarantor | is_eu_domestic_cgcb_guarantor
    else:
        is_domestic_cgcb_guarantor = pl.lit(False)

    exposures = exposures.with_columns(
        [
            pl.when(is_domestic_cgcb_guarantor)
            .then(pl.lit("sa"))
            .when(
                (pl.col("guarantor_exposure_class") != "")
                & pl.col("guarantor_exposure_class").is_in(list(irb_exposure_class_values))
                & pl.col("guarantor_internal_pd").is_not_null()
            )
            .then(pl.lit("irb"))
            .when(pl.col("guarantor_exposure_class") != "")
            .then(pl.lit("sa"))
            .otherwise(pl.lit(""))
            .alias("guarantor_approach"),
            # Audit: track whether guarantor approach was derived from internal or
            # external rating (spec output field per CRR Art. 153(3) / Art. 233A).
            pl.when(pl.col("guarantor_internal_pd").is_not_null())
            .then(pl.lit("internal"))
            .when(pl.col("guarantor_cqs").is_not_null())
            .then(pl.lit("external"))
            .otherwise(pl.lit(None).cast(pl.String))
            .alias("guarantor_rating_type"),
        ]
    )

    # Cross-approach CCF substitution (CRR Art. 111 / COREP C07)
    # When IRB exposure guaranteed by SA counterparty, use SA CCFs for guaranteed portion
    exposures = _apply_cross_approach_ccf(exposures)

    # Add post-CRM composite attributes for regulatory reporting
    # For the guaranteed portion, the post-CRM counterparty is the guarantor
    exposures = exposures.with_columns(
        [
            # Post-CRM counterparty for guaranteed portion (guarantor or original)
            pl.when(pl.col("guaranteed_portion") > 0)
            .then(pl.col("guarantor_reference"))
            .otherwise(pl.col("counterparty_reference"))
            .alias("post_crm_counterparty_guaranteed"),
            # Post-CRM exposure class for guaranteed portion (guarantor's class or original)
            pl.when((pl.col("guaranteed_portion") > 0) & (pl.col("guarantor_exposure_class") != ""))
            .then(pl.col("guarantor_exposure_class"))
            .otherwise(pl.col("exposure_class"))
            .alias("post_crm_exposure_class_guaranteed"),
            # Flag indicating whether exposure has an effective guarantee
            (pl.col("guaranteed_portion") > 0).alias("is_guaranteed"),
        ]
    )

    # Note: Transient columns (guarantor_entity_type, guarantor_cqs, etc.) are kept
    # because downstream SA/IRB calculators need them for risk weight substitution.
    # They can be dropped in the final output aggregation if needed.

    return exposures


def _resolve_guarantees_multi_level(
    guarantees: pl.LazyFrame,
    exposures: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Expand facility and counterparty-level guarantees to exposure-level.

    Direct (loan/contingent) guarantees pass through unchanged. Facility-level
    guarantees are allocated pro-rata by ``ead_after_collateral`` to all child
    exposures under that facility. Counterparty-level guarantees are allocated
    pro-rata across all exposures of that counterparty.

    For amount-based guarantees (``amount_covered``), the amount is split
    proportionally. For percentage-based guarantees (``percentage_covered``),
    the percentage passes through unchanged since it applies equally to each
    child exposure's EAD.

    References:
        CRR Art. 213-217: Unfunded credit protection
        CRE22.70-85: Basel 3.1 guarantee substitution

    Args:
        guarantees: Guarantee data with beneficiary_type and beneficiary_reference
        exposures: Exposures with ead_after_collateral, parent_facility_reference,
                   counterparty_reference

    Returns:
        Guarantees expanded to exposure-level beneficiary_reference
    """
    guar_schema = guarantees.collect_schema()

    if "beneficiary_type" not in guar_schema.names():
        return guarantees

    bt_lower = pl.col("beneficiary_type").str.to_lowercase()

    # --- 1. Direct guarantees — pass through unchanged ---
    direct_guarantees = guarantees.filter(bt_lower.is_in(DIRECT_BENEFICIARY_TYPES))

    expanded_parts: list[pl.LazyFrame] = [direct_guarantees]

    # --- 2. Facility-level guarantees — allocate pro-rata to child exposures ---
    exp_schema = exposures.collect_schema()
    has_parent_fac = "parent_facility_reference" in exp_schema.names()

    if has_parent_fac:
        facility_guarantees = guarantees.filter(bt_lower == "facility")
        fac_exposures = exposures.filter(pl.col("parent_facility_reference").is_not_null())
        expanded_parts.append(
            _allocate_guarantees_pro_rata(
                facility_guarantees, fac_exposures, "parent_facility_reference"
            )
        )

    # --- 3. Counterparty-level guarantees — allocate pro-rata ---
    cp_guarantees = guarantees.filter(bt_lower == "counterparty")
    expanded_parts.append(
        _allocate_guarantees_pro_rata(cp_guarantees, exposures, "counterparty_reference")
    )

    return pl.concat(expanded_parts, how="diagonal")


def _apply_guarantee_splits(
    guarantees: pl.LazyFrame,
    exposures: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Split exposures with multiple guarantors into per-guarantor sub-rows.

    For each exposure with N guarantors (N > 1), produces N+1 rows:
    - N guarantor sub-rows, each with that guarantor's covered amount
    - 1 remainder sub-row for the uncovered portion

    Single-guarantor exposures keep the existing aggregation behavior.
    Non-guaranteed exposures pass through unchanged.

    References:
        CRR Art. 215-217: Each guarantor's portion receives its own risk weight

    Args:
        guarantees: Exposure-level guarantees (after multi-level resolution)
        exposures: Exposures with ead_after_collateral and parent_exposure_reference

    Returns:
        Exposures with guarantee portions set, potentially with additional rows
    """
    guar_schema = guarantees.collect_schema()
    guar_cols = guar_schema.names()

    # Pre-aggregate by (beneficiary_reference, guarantor) so that multiple
    # protections from the same guarantor (e.g. direct + facility-level) are
    # summed before we decide whether to split.
    agg_exprs: list[pl.Expr] = [
        pl.col("amount_covered").sum().alias("amount_covered"),
    ]
    if "percentage_covered" in guar_cols:
        agg_exprs.append(pl.col("percentage_covered").first().alias("percentage_covered"))
    if "guarantee_reference" in guar_cols:
        agg_exprs.append(pl.col("guarantee_reference").first().alias("guarantee_reference"))
    if "protection_type" in guar_cols:
        agg_exprs.append(pl.col("protection_type").first().alias("protection_type"))
    # Preserve guarantee currency for FX mismatch haircut (Art. 233(3-4)).
    # Use original_currency (pre-FX-conversion) if available, else currency.
    if "original_currency" in guar_cols:
        agg_exprs.append(pl.col("original_currency").first().alias("guarantee_currency"))
    elif "currency" in guar_cols:
        agg_exprs.append(pl.col("currency").first().alias("guarantee_currency"))
    # Preserve includes_restructuring for CDS restructuring exclusion haircut (Art. 233(2)).
    if "includes_restructuring" in guar_cols:
        agg_exprs.append(pl.col("includes_restructuring").first().alias("includes_restructuring"))
    # Preserve haircut columns (applied before split in apply_guarantees pipeline)
    if "guarantee_fx_haircut" in guar_cols:
        agg_exprs.append(pl.col("guarantee_fx_haircut").first().alias("guarantee_fx_haircut"))
    if "guarantee_restructuring_haircut" in guar_cols:
        agg_exprs.append(
            pl.col("guarantee_restructuring_haircut")
            .first()
            .alias("guarantee_restructuring_haircut")
        )

    guarantees = guarantees.group_by("beneficiary_reference", "guarantor").agg(agg_exprs)

    # Refresh schema after aggregation
    guar_schema = guarantees.collect_schema()
    guar_cols = guar_schema.names()

    # Determine which guarantee columns are available for selection
    guar_select = ["beneficiary_reference", "amount_covered", "guarantor"]
    if "percentage_covered" in guar_cols:
        guar_select.append("percentage_covered")
    if "guarantee_reference" in guar_cols:
        guar_select.append("guarantee_reference")
    if "protection_type" in guar_cols:
        guar_select.append("protection_type")
    if "guarantee_currency" in guar_cols:
        guar_select.append("guarantee_currency")
    if "includes_restructuring" in guar_cols:
        guar_select.append("includes_restructuring")
    if "guarantee_fx_haircut" in guar_cols:
        guar_select.append("guarantee_fx_haircut")
    if "guarantee_restructuring_haircut" in guar_cols:
        guar_select.append("guarantee_restructuring_haircut")

    # Count distinct guarantors per exposure
    guarantee_counts = guarantees.group_by("beneficiary_reference").agg(
        pl.len().alias("guarantee_count"),
    )

    # Identify which exposures have guarantees and how many
    exposures_with_counts = exposures.join(
        guarantee_counts,
        left_on="exposure_reference",
        right_on="beneficiary_reference",
        how="left",
    ).with_columns(pl.col("guarantee_count").fill_null(0))

    # Drop initialized-to-null columns that will be re-added from guarantee data
    # (or explicitly set) in each split path.  Without this, the join produces
    # suffixed duplicates (e.g. protection_type_right) and the guarantee values
    # are lost.
    _cols_to_drop_before_join = [
        c
        for c in (
            "protection_type",
            "guarantee_currency",
            "includes_restructuring",
            "guarantee_fx_haircut",
            "guarantee_restructuring_haircut",
            "guarantee_amount",
            "guaranteed_portion",
            "unguaranteed_portion",
            "guarantor_reference",
        )
        if c in exposures_with_counts.collect_schema().names()
    ]
    if _cols_to_drop_before_join:
        exposures_with_counts = exposures_with_counts.drop(_cols_to_drop_before_join)

    # --- Path 1: No guarantees ---
    no_guarantee = exposures_with_counts.filter(pl.col("guarantee_count") == 0).with_columns(
        pl.lit(0.0).alias("guaranteed_portion"),
        pl.col("ead_after_collateral").alias("unguaranteed_portion"),
        pl.lit(None).cast(pl.String).alias("guarantor_reference"),
        pl.lit(0.0).alias("guarantee_amount"),
        pl.lit(0.0).alias("original_guarantee_amount"),
        pl.lit(None).cast(pl.String).alias("protection_type"),
        pl.lit(None).cast(pl.String).alias("guarantee_currency"),
        pl.lit(None).cast(pl.Boolean).alias("includes_restructuring"),
        pl.lit(0.0).alias("guarantee_fx_haircut"),
        pl.lit(0.0).alias("guarantee_restructuring_haircut"),
    )

    # --- Path 2: Single guarantor (backward compatible, no split) ---
    single_guar_exposures = exposures_with_counts.filter(pl.col("guarantee_count") == 1)
    single_guarantees = guarantees.select(guar_select)

    single = single_guar_exposures.join(
        single_guarantees,
        left_on="exposure_reference",
        right_on="beneficiary_reference",
        how="inner",
    )

    single = single.with_columns(
        _resolve_guarantee_amount_expr("percentage_covered" in guar_cols, "guarantee_amount"),
    )

    single = single.with_columns(
        pl.col("guarantee_amount").alias("original_guarantee_amount"),
        pl.min_horizontal("guarantee_amount", "ead_after_collateral").alias("guaranteed_portion"),
        pl.col("guarantor").alias("guarantor_reference"),
    ).with_columns(
        (pl.col("ead_after_collateral") - pl.col("guaranteed_portion")).alias(
            "unguaranteed_portion"
        ),
    )

    # --- Path 3: Multiple guarantors — row splitting ---
    multi_guar_exposures = exposures_with_counts.filter(pl.col("guarantee_count") > 1)
    multi_guarantees = guarantees.select(guar_select)

    # Join each guarantee to its exposure (1:N → produces N rows per exposure)
    multi_joined = multi_guar_exposures.join(
        multi_guarantees,
        left_on="exposure_reference",
        right_on="beneficiary_reference",
        how="inner",
    )

    multi_joined = multi_joined.with_columns(
        _resolve_guarantee_amount_expr("percentage_covered" in guar_cols, "_guar_amount"),
    )

    # Cap total coverage to EAD using pro-rata scaling
    multi_joined = (
        multi_joined.with_columns(
            pl.col("_guar_amount").sum().over("parent_exposure_reference").alias("_total_coverage"),
        )
        .with_columns(
            pl.min_horizontal(
                pl.lit(1.0),
                pl.col("ead_after_collateral") / pl.col("_total_coverage"),
            ).alias("_scale"),
        )
        .with_columns(
            (pl.col("_guar_amount") * pl.col("_scale")).alias("_effective_amount"),
        )
    )

    # Compute remainder per exposure
    multi_joined = multi_joined.with_columns(
        pl.col("_effective_amount")
        .sum()
        .over("parent_exposure_reference")
        .alias("_total_effective"),
    )

    # Build guarantor sub-rows: each gets its guarantor's covered amount
    guarantor_sub_rows = multi_joined.with_columns(
        pl.col("_effective_amount").alias("guaranteed_portion"),
        pl.lit(0.0).alias("unguaranteed_portion"),
        pl.col("_effective_amount").alias("ead_after_collateral"),
        pl.col("_effective_amount").alias("guarantee_amount"),
        pl.col("_guar_amount").alias("original_guarantee_amount"),
        pl.col("guarantor").alias("guarantor_reference"),
        pl.concat_str(
            [pl.col("parent_exposure_reference"), pl.lit("__G_"), pl.col("guarantor")],
        ).alias("exposure_reference"),
    )

    # Build remainder sub-rows: one per multi-guarantor exposure
    # Use first row per exposure to get the base columns
    remainder_sub_rows = (
        multi_joined.sort("parent_exposure_reference", "guarantor")
        .group_by("parent_exposure_reference", maintain_order=True)
        .first()
    ).with_columns(
        pl.lit(0.0).alias("guaranteed_portion"),
        (pl.col("ead_after_collateral") - pl.col("_total_effective")).alias("unguaranteed_portion"),
        (pl.col("ead_after_collateral") - pl.col("_total_effective")).alias("ead_after_collateral"),
        pl.lit(0.0).alias("guarantee_amount"),
        pl.lit(0.0).alias("original_guarantee_amount"),
        pl.lit(None).cast(pl.String).alias("guarantor_reference"),
        pl.lit(None).cast(pl.String).alias("protection_type"),
        pl.lit(None).cast(pl.String).alias("guarantee_currency"),
        pl.lit(None).cast(pl.Boolean).alias("includes_restructuring"),
        pl.lit(0.0).alias("guarantee_fx_haircut"),
        pl.lit(0.0).alias("guarantee_restructuring_haircut"),
        pl.concat_str(
            [pl.col("parent_exposure_reference"), pl.lit("__REM")],
        ).alias("exposure_reference"),
    )

    # Drop transient columns used during splitting
    transient = [
        "_guar_amount",
        "_total_coverage",
        "_scale",
        "_effective_amount",
        "_total_effective",
        "amount_covered",
    ]
    if "percentage_covered" in guar_cols:
        transient.append("percentage_covered")

    guarantor_sub_rows = _drop_columns_if_present(guarantor_sub_rows, transient)
    remainder_sub_rows = _drop_columns_if_present(remainder_sub_rows, transient)

    # Also drop transient/join columns from single and no-guarantee paths
    single_drop = ["amount_covered"]
    if "percentage_covered" in guar_cols:
        single_drop.append("percentage_covered")
    single = _drop_columns_if_present(single, single_drop)

    # Concat all paths
    parts = [no_guarantee, single, guarantor_sub_rows, remainder_sub_rows]
    return pl.concat(parts, how="diagonal_relaxed")


def _apply_cross_approach_ccf(
    exposures: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Apply cross-approach CCF substitution for guaranteed exposures.

    When an IRB exposure (F-IRB or A-IRB) is guaranteed by an SA counterparty,
    the guaranteed portion must use SA CCFs for COREP C07 reporting.
    If the guarantor is also IRB, the original IRB CCF is retained.

    Returns:
        Exposures with CCF-adjusted guaranteed/unguaranteed portions
    """
    schema = exposures.collect_schema()
    has_interest = "interest" in schema.names()
    has_risk_type = "risk_type" in schema.names()

    if not has_risk_type:
        return exposures

    # Only IRB exposures with SA guarantors and off-balance-sheet items
    needs_ccf_sub = (
        pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value])
        & (pl.col("guarantor_approach") == "sa")
        & (pl.col("guaranteed_portion") > 0)
        & (pl.col("nominal_amount") > 0)
    )

    sa_ccf = sa_ccf_expression()

    exposures = exposures.with_columns(
        [
            pl.when(pl.col("ead_after_collateral") > 0)
            .then(
                (pl.col("guaranteed_portion") / pl.col("ead_after_collateral")).clip(
                    upper_bound=1.0
                )
            )
            .otherwise(pl.lit(0.0))
            .alias("guarantee_ratio"),
            pl.col("ccf").alias("ccf_original"),
            pl.when(needs_ccf_sub).then(sa_ccf).otherwise(pl.col("ccf")).alias("ccf_guaranteed"),
            pl.col("ccf").alias("ccf_unguaranteed"),
        ]
    )

    # Recalculate EAD with split CCFs when cross-approach substitution applies
    # Use provision-adjusted on-balance and nominal when available
    has_provision_cols = "provision_on_drawn" in schema.names()

    if has_provision_cols and has_interest:
        on_bal = (drawn_for_ead() - pl.col("provision_on_drawn")).clip(
            lower_bound=0.0
        ) + interest_for_ead()
    elif has_provision_cols:
        on_bal = (drawn_for_ead() - pl.col("provision_on_drawn")).clip(lower_bound=0.0)
    elif has_interest:
        on_bal = on_balance_ead()
    else:
        on_bal = drawn_for_ead()

    # Use nominal_after_provision if available, else nominal_amount
    nominal_col = (
        pl.col("nominal_after_provision")
        if "nominal_after_provision" in schema.names()
        else pl.col("nominal_amount")
    )
    ratio = pl.col("guarantee_ratio")

    new_guaranteed = (on_bal * ratio) + (nominal_col * ratio * pl.col("ccf_guaranteed"))
    new_unguaranteed = (on_bal * (pl.lit(1.0) - ratio)) + (
        nominal_col * (pl.lit(1.0) - ratio) * pl.col("ccf_unguaranteed")
    )

    exposures = exposures.with_columns(
        [
            pl.when(needs_ccf_sub)
            .then(new_guaranteed)
            .otherwise(pl.col("guaranteed_portion"))
            .alias("guaranteed_portion"),
            pl.when(needs_ccf_sub)
            .then(new_unguaranteed)
            .otherwise(pl.col("unguaranteed_portion"))
            .alias("unguaranteed_portion"),
        ]
    )

    # Update ead_after_collateral and ead_from_ccf when substitution occurs
    exposures = exposures.with_columns(
        [
            pl.when(needs_ccf_sub)
            .then(pl.col("guaranteed_portion") + pl.col("unguaranteed_portion"))
            .otherwise(pl.col("ead_after_collateral"))
            .alias("ead_after_collateral"),
            pl.when(needs_ccf_sub)
            .then(
                nominal_col * ratio * pl.col("ccf_guaranteed")
                + nominal_col * (pl.lit(1.0) - ratio) * pl.col("ccf_unguaranteed")
            )
            .otherwise(pl.col("ead_from_ccf"))
            .alias("ead_from_ccf"),
        ]
    )

    return exposures


def _resolve_guarantee_amount_expr(has_percentage: bool, alias: str) -> pl.Expr:
    """Build expression resolving guarantee amount from amount_covered or percentage_covered."""
    if has_percentage:
        return (
            pl.when(
                (
                    pl.col("amount_covered").is_null()
                    | (pl.col("amount_covered").cast(pl.Float64, strict=False).abs() < 1e-10)
                )
                & pl.col("percentage_covered").is_not_null()
                & (pl.col("percentage_covered") > 0)
            )
            .then(pl.col("percentage_covered") * pl.col("ead_after_collateral"))
            .otherwise(pl.col("amount_covered").fill_null(0.0))
            .alias(alias)
        )
    return pl.col("amount_covered").fill_null(0.0).alias(alias)


def _allocate_guarantees_pro_rata(
    guarantees: pl.LazyFrame,
    exposures: pl.LazyFrame,
    group_col: str,
) -> pl.LazyFrame:
    """Allocate amount-based guarantees pro-rata by ead_after_collateral within a group."""
    level_exposures = exposures.select(
        "exposure_reference",
        group_col,
        "ead_after_collateral",
    )

    totals = level_exposures.group_by(group_col).agg(
        pl.col("ead_after_collateral").sum().alias("_total_ead"),
    )

    weighted = (
        level_exposures.join(totals, on=group_col, how="left")
        .with_columns(
            pl.when(pl.col("_total_ead") > 0)
            .then(pl.col("ead_after_collateral") / pl.col("_total_ead"))
            .otherwise(pl.lit(0.0))
            .alias("_weight"),
        )
        .select("exposure_reference", group_col, "_weight")
    )

    return (
        guarantees.join(
            weighted,
            left_on="beneficiary_reference",
            right_on=group_col,
            how="inner",
        )
        .with_columns(
            (pl.col("amount_covered") * pl.col("_weight")).alias("amount_covered"),
            pl.col("exposure_reference").alias("beneficiary_reference"),
            pl.lit("loan").alias("beneficiary_type"),
        )
        .drop("exposure_reference", "_weight")
    )


def _apply_fx_haircut_to_guarantees(
    guarantees: pl.LazyFrame,
    exposures: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Apply FX mismatch haircut to guarantee amounts BEFORE splitting.

    Reduces ``amount_covered`` by H_fx (8%) when the guarantee currency
    differs from the exposure currency. Haircut is applied to the nominal
    credit protection value *before* capping at EAD, per CRR Art. 233(3-4):

        G* = G × (1 − H_fx)

    This ensures that a large guarantee in a foreign currency still fully
    covers a smaller exposure (e.g. £200m guarantee on €1m loan with 8%
    haircut → £184m effective → still fully covers €1m).

    References:
        CRR Art. 233(3-4), Art. 235(1): G = nominal credit protection value
        Art. 224 Table 4: H_fx = 8% (10-day liquidation period)
    """
    guar_schema = guarantees.collect_schema()
    guar_cols = guar_schema.names()

    # Determine guarantee currency column
    if "original_currency" in guar_cols:
        guar_ccy_col = "original_currency"
    elif "currency" in guar_cols:
        guar_ccy_col = "currency"
    else:
        return guarantees.with_columns(pl.lit(0.0).alias("guarantee_fx_haircut"))

    # Determine exposure currency column
    exp_schema = exposures.collect_schema()
    exp_cols = exp_schema.names()
    if "original_currency" in exp_cols:
        exp_ccy_col = "original_currency"
    elif "currency" in exp_cols:
        exp_ccy_col = "currency"
    else:
        return guarantees.with_columns(pl.lit(0.0).alias("guarantee_fx_haircut"))

    # Join guarantees with exposure currency (lightweight join)
    exp_ccy = exposures.select(
        pl.col("exposure_reference"),
        pl.col(exp_ccy_col).alias("_exp_ccy"),
    )

    guarantees = guarantees.join(
        exp_ccy,
        left_on="beneficiary_reference",
        right_on="exposure_reference",
        how="left",
    )

    h_fx = float(FX_HAIRCUT)
    has_pct = "percentage_covered" in guar_cols

    # Guarantee provides coverage via amount or percentage
    has_coverage = pl.col("amount_covered").fill_null(0.0) > 0
    if has_pct:
        has_coverage = has_coverage | (pl.col("percentage_covered").fill_null(0.0) > 0)

    fx_mismatch = (
        pl.col(guar_ccy_col).is_not_null()
        & pl.col("_exp_ccy").is_not_null()
        & (pl.col(guar_ccy_col) != pl.col("_exp_ccy"))
        & has_coverage
    )

    haircut_exprs: list[pl.Expr] = [
        # Amount-based: reduce amount_covered
        pl.when(fx_mismatch)
        .then(pl.col("amount_covered") * (1.0 - h_fx))
        .otherwise(pl.col("amount_covered"))
        .alias("amount_covered"),
        # Track the haircut applied
        pl.when(fx_mismatch)
        .then(pl.lit(h_fx))
        .otherwise(pl.lit(0.0))
        .alias("guarantee_fx_haircut"),
    ]

    # Percentage-based: reduce percentage_covered (G = pct × EAD, so G* = pct × (1-H) × EAD)
    if has_pct:
        haircut_exprs.append(
            pl.when(fx_mismatch)
            .then(pl.col("percentage_covered") * (1.0 - h_fx))
            .otherwise(pl.col("percentage_covered"))
            .alias("percentage_covered"),
        )

    guarantees = guarantees.with_columns(haircut_exprs)

    return guarantees.drop("_exp_ccy")


def _apply_restructuring_haircut_to_guarantees(
    guarantees: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Apply CDS restructuring exclusion haircut to guarantee amounts BEFORE splitting.

    When a credit derivative does not include restructuring as a credit event,
    ``amount_covered`` is reduced by 40%:

        G* = G × (1 − H_restructuring) = G × 0.60

    Applied to nominal credit protection value before capping/splitting,
    consistent with CRR Art. 233(2).

    References:
        CRR Art. 233(2), PRA PS1/26 Art. 233(2)
        Art. 216(1): Credit events for credit derivatives
    """
    schema = guarantees.collect_schema()
    cols = schema.names()

    has_protection_type = "protection_type" in cols
    has_includes_restructuring = "includes_restructuring" in cols

    if not has_protection_type or not has_includes_restructuring:
        return guarantees.with_columns(
            pl.lit(0.0).alias("guarantee_restructuring_haircut"),
        )

    h_restructuring = float(RESTRUCTURING_EXCLUSION_HAIRCUT)

    applies = (
        (pl.col("protection_type") == "credit_derivative")
        & (pl.col("includes_restructuring").fill_null(True).not_())
        & (pl.col("amount_covered").fill_null(0.0) > 0)
    )

    return guarantees.with_columns(
        pl.when(applies)
        .then(pl.col("amount_covered") * (1.0 - h_restructuring))
        .otherwise(pl.col("amount_covered"))
        .alias("amount_covered"),
        pl.when(applies)
        .then(pl.lit(h_restructuring))
        .otherwise(pl.lit(0.0))
        .alias("guarantee_restructuring_haircut"),
    )


def redistribute_non_beneficial(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """
    Redistribute non-beneficial guarantee portions to beneficial guarantors.

    When multi-guarantor exposures have mixed beneficial/non-beneficial sub-rows,
    the non-beneficial portions are reallocated to beneficial guarantors using a
    greedy strategy ordered by ascending ``guarantor_rw`` (lowest risk weight first).
    This minimises total RWA by filling the best guarantors first.

    Only operates on multi-guarantor sub-rows (created by ``_apply_guarantee_splits``).
    Single-guarantor and non-guaranteed exposures pass through unchanged.

    References:
        CRR Art. 213: Only beneficial guarantees should be applied
        CRR Art. 215-217: Guarantee substitution with multiple protections
    """
    schema = exposures.collect_schema()
    cols = schema.names()

    # Guard: need the columns created by _apply_guarantee_splits and the beneficial check
    required = [
        "parent_exposure_reference",
        "exposure_reference",
        "is_guarantee_beneficial",
        "guaranteed_portion",
        "ead_after_collateral",
        "original_guarantee_amount",
        "guarantor_rw",
    ]
    if not all(c in cols for c in required):
        return exposures

    # Classify row types
    is_sub_row = pl.col("parent_exposure_reference") != pl.col("exposure_reference")
    is_remainder = pl.col("exposure_reference").str.ends_with("__REM")
    is_guarantor_sub = is_sub_row & ~is_remainder

    # Check if any parent group has mixed beneficial/non-beneficial sub-rows.
    # If no non-beneficial sub-rows exist at all, skip redistribution entirely.
    has_non_ben = (
        pl.when(~pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(pl.lit(1))
        .otherwise(pl.lit(0))
        .sum()
        .over("parent_exposure_reference")
    )
    has_ben = (
        pl.when(pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(pl.lit(1))
        .otherwise(pl.lit(0))
        .sum()
        .over("parent_exposure_reference")
    )

    # Only redistribute for groups that have BOTH beneficial and non-beneficial
    needs_redistribution = (has_non_ben > 0) & (has_ben > 0) & is_sub_row

    # Pre-compute group-level amounts
    exposures = exposures.with_columns(
        # Total non-beneficial amount to free up (per parent group)
        pl.when(~pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(pl.col("guaranteed_portion"))
        .otherwise(pl.lit(0.0))
        .sum()
        .over("parent_exposure_reference")
        .alias("_non_ben_total"),
        # Total parent EAD (sum of all sub-row EADs in the group)
        pl.when(is_sub_row)
        .then(pl.col("ead_after_collateral"))
        .otherwise(pl.lit(0.0))
        .sum()
        .over("parent_exposure_reference")
        .alias("_parent_ead"),
    )

    # For beneficial sub-rows, compute remaining capacity and sort rank
    exposures = exposures.with_columns(
        pl.when(pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(
            (pl.col("original_guarantee_amount") - pl.col("guaranteed_portion")).clip(
                lower_bound=0.0
            )
        )
        .otherwise(pl.lit(0.0))
        .alias("_remaining_capacity"),
    )

    # Greedy fill: sort beneficial guarantors by guarantor_rw ascending,
    # compute cumulative capacity, and determine how much each absorbs.
    # Use ordered window function so lowest-RW guarantors fill first.
    exposures = exposures.with_columns(
        # Cumulative capacity of beneficial guarantors sorted by RW (ascending)
        # For non-beneficial or non-sub-rows, capacity is 0 so cumsum stays 0.
        pl.col("_remaining_capacity")
        .cum_sum()
        .over("parent_exposure_reference", order_by="guarantor_rw")
        .alias("_cum_capacity"),
    )

    exposures = exposures.with_columns(
        # Previous cumulative (capacity of better-ranked guarantors)
        (pl.col("_cum_capacity") - pl.col("_remaining_capacity")).alias("_prev_cum"),
    )

    # Each beneficial guarantor absorbs:
    #   min(remaining_capacity, max(0, freed_amount - prev_cumulative))
    absorbed = pl.min_horizontal(
        pl.col("_remaining_capacity"),
        (pl.col("_non_ben_total") - pl.col("_prev_cum")).clip(lower_bound=0.0),
    )

    # Compute new guaranteed portion for each row
    new_guaranteed = (
        pl.when(needs_redistribution & pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(pl.col("guaranteed_portion") + absorbed)
        .when(needs_redistribution & ~pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(pl.lit(0.0))
        .otherwise(pl.col("guaranteed_portion"))
    )

    # Compute total new beneficial EAD per group (for remainder calculation)
    exposures = exposures.with_columns(new_guaranteed.alias("_new_guaranteed"))

    new_ben_total = (
        pl.when(is_guarantor_sub)
        .then(pl.col("_new_guaranteed"))
        .otherwise(pl.lit(0.0))
        .sum()
        .over("parent_exposure_reference")
    )

    # Update all affected columns
    exposures = exposures.with_columns(
        # guaranteed_portion
        pl.col("_new_guaranteed").alias("guaranteed_portion"),
        # ead_after_collateral: for guarantor sub-rows = guaranteed_portion,
        # for remainder = parent_ead - sum(guarantor sub-row EADs)
        pl.when(needs_redistribution & is_guarantor_sub)
        .then(pl.col("_new_guaranteed"))
        .when(needs_redistribution & is_remainder)
        .then((pl.col("_parent_ead") - new_ben_total).clip(lower_bound=0.0))
        .otherwise(pl.col("ead_after_collateral"))
        .alias("ead_after_collateral"),
        # unguaranteed_portion
        pl.when(needs_redistribution & pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(pl.lit(0.0))
        .when(needs_redistribution & ~pl.col("is_guarantee_beneficial") & is_guarantor_sub)
        .then(pl.lit(0.0))
        .when(needs_redistribution & is_remainder)
        .then((pl.col("_parent_ead") - new_ben_total).clip(lower_bound=0.0))
        .otherwise(pl.col("unguaranteed_portion"))
        .alias("unguaranteed_portion"),
    )

    # Drop transient columns
    transient = [
        "_non_ben_total",
        "_parent_ead",
        "_remaining_capacity",
        "_cum_capacity",
        "_prev_cum",
        "_new_guaranteed",
    ]
    return _drop_columns_if_present(exposures, transient)


def _apply_guarantee_fx_haircut(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """
    Apply FX mismatch haircut to guarantee amounts.

    When a guarantee or credit derivative is denominated in a different currency
    from the exposure, the effective protection is reduced by H_fx (8%):

        G* = G × (1 − H_fx)

    This reduces ``guaranteed_portion`` and correspondingly increases
    ``unguaranteed_portion`` for cross-currency guarantees.

    References:
        CRR Art. 233(3-4), PRA PS1/26 Art. 233(3-4)
        H_fx = 8% (Art. 224 Table 4, 10-day liquidation period)
    """
    schema = exposures.collect_schema()
    cols = schema.names()

    # Need both guarantee_currency and exposure currency to detect mismatch
    has_guarantee_ccy = "guarantee_currency" in cols
    has_exposure_ccy = "original_currency" in cols or "currency" in cols

    if not has_guarantee_ccy or not has_exposure_ccy:
        return exposures.with_columns(pl.lit(0.0).alias("guarantee_fx_haircut"))

    # Use original_currency (pre-FX-conversion) if available, else currency
    exposure_ccy = (
        pl.col("original_currency") if "original_currency" in cols else pl.col("currency")
    )
    h_fx = float(FX_HAIRCUT)

    fx_mismatch = (
        pl.col("guarantee_currency").is_not_null()
        & (pl.col("guarantee_currency") != exposure_ccy)
        & (pl.col("guaranteed_portion") > 0)
    )

    exposures = exposures.with_columns(
        pl.when(fx_mismatch)
        .then(pl.col("guaranteed_portion") * (1.0 - h_fx))
        .otherwise(pl.col("guaranteed_portion"))
        .alias("guaranteed_portion"),
        pl.when(fx_mismatch)
        .then(pl.lit(h_fx))
        .otherwise(pl.lit(0.0))
        .alias("guarantee_fx_haircut"),
    ).with_columns(
        (pl.col("ead_after_collateral") - pl.col("guaranteed_portion"))
        .clip(lower_bound=0.0)
        .alias("unguaranteed_portion"),
    )

    return exposures


def _apply_restructuring_exclusion_haircut(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """
    Apply CDS restructuring exclusion haircut to credit derivative amounts.

    When a credit derivative does not include restructuring as a credit event,
    the effective protection is reduced by 40%:

        G* = G × (1 − H_restructuring) = G × 0.60

    This only applies to credit derivatives (``protection_type == "credit_derivative"``),
    not to regular guarantees. Null ``includes_restructuring`` defaults to ``True``
    (no haircut) for backward compatibility.

    References:
        CRR Art. 233(2), PRA PS1/26 Art. 233(2)
        Art. 216(1): Credit events for credit derivatives
    """
    schema = exposures.collect_schema()
    cols = schema.names()

    has_protection_type = "protection_type" in cols
    has_includes_restructuring = "includes_restructuring" in cols

    if not has_protection_type or not has_includes_restructuring:
        return exposures.with_columns(
            pl.lit(0.0).alias("guarantee_restructuring_haircut"),
        )

    h_restructuring = float(RESTRUCTURING_EXCLUSION_HAIRCUT)

    # Condition: credit derivative without restructuring as a credit event
    applies = (
        (pl.col("protection_type") == "credit_derivative")
        & (pl.col("includes_restructuring").fill_null(True).not_())
        & (pl.col("guaranteed_portion") > 0)
    )

    exposures = exposures.with_columns(
        pl.when(applies)
        .then(pl.col("guaranteed_portion") * (1.0 - h_restructuring))
        .otherwise(pl.col("guaranteed_portion"))
        .alias("guaranteed_portion"),
        pl.when(applies)
        .then(pl.lit(h_restructuring))
        .otherwise(pl.lit(0.0))
        .alias("guarantee_restructuring_haircut"),
    ).with_columns(
        (pl.col("ead_after_collateral") - pl.col("guaranteed_portion"))
        .clip(lower_bound=0.0)
        .alias("unguaranteed_portion"),
    )

    return exposures


def _drop_columns_if_present(lf: pl.LazyFrame, cols: list[str]) -> pl.LazyFrame:
    """Drop columns from LazyFrame, ignoring those not present."""
    schema = lf.collect_schema()
    to_drop = [c for c in cols if c in schema.names()]
    return lf.drop(to_drop) if to_drop else lf
