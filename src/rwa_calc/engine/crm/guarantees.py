"""
Guarantee substitution for CRM processing.

Pipeline position:
    Collateral -> apply_guarantees -> Finalise EAD

Key responsibilities:
- Eligibility screen and Art. 233 valuation of the protection (delegated to
  ``protection_screen`` and ``protection_value``)
- Multi-level guarantee resolution (direct / facility / counterparty)
- Multi-guarantor row splitting
- Cross-approach CCF substitution (IRB exposure + SA guarantor)
- Guarantor attribute lookup for risk weight substitution

References:
    CRR Art. 213-217: Unfunded credit protection
    CRR / PS1/26 Art. 233-235: valuation and the risk-weight substitution method
    CRE22.70-85: Basel 3.1 guarantee substitution
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, DIRECT_BENEFICIARY_TYPES
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.ccf import (
    drawn_for_ead,
    interest_for_ead,
    on_balance_ead,
    sa_ccf_expression,
)
from rwa_calc.engine.crm.expressions import COLLATERAL_VALUE_CARRIERS
from rwa_calc.engine.crm.guarantor_eligibility import assign_guarantor_approach
from rwa_calc.engine.crm.protection_screen import screen_unfunded_protection
from rwa_calc.engine.crm.protection_value import (
    attach_shared_cap,
    crm_basis_expr,
    value_unfunded_protection,
)
from rwa_calc.engine.entity_class_maps import ENTITY_TYPE_TO_SA_CLASS
from rwa_calc.engine.kernels.allocation import (
    expand_items_pro_rata,
    explode_facility_membership,
)
from rwa_calc.engine.utils import exact_fractional_years_expr
from rwa_calc.rulebook import RulepackV0

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.rulebook.resolve import ResolvedRulepack


def _stock_split_cols() -> tuple[str, ...]:
    """Stock columns that must be split proportionally when guarantee row-splits
    occur, so downstream per-counterparty aggregations (e.g. SME supporting
    factor) and cross-approach CCF recalculations remain correct.

    The collateral VALUATIONS are such a stock; leaving them whole published
    N x the collateral held. Deliberately EXCLUDED are the rates and the
    Art. 231 allocations (``crm_alloc_*``, ``total_collateral_for_lgd``) — the
    latter ARE stocks, but their only post-split consumer divides them by the
    unsplit ``ead_for_crm``, so splitting them alone would move capital. Full
    argument: ``tests/unit/crm/test_guarantee_collateral_split.py``.
    Both consumers skip any entry absent from the frame.
    """
    return (
        "drawn_amount",
        "undrawn_amount",
        "nominal_amount",
        "interest",
        "ead_pre_crm",
        "ead_from_ccf",
        "provision_deducted",
        "provision_on_drawn",
        "provision_on_nominal",
        "nominal_after_provision",
        # Art. 230/231 funded-protection VALUATIONS (disclosure carriers only),
        # named once in expressions.py so the adjusted and market-value bases
        # cannot drift apart again.
        *COLLATERAL_VALUE_CARRIERS,
    )


def _cols_to_drop_before_join() -> tuple[str, ...]:
    """Columns initialised to null on exposures that must be dropped before
    joining guarantee data, to avoid suffixed duplicates (e.g.
    protection_type_right) and lost guarantee values."""
    return (
        "protection_type",
        "guarantee_currency",
        "includes_restructuring",
        "guarantor_seniority",
        "guarantee_fx_haircut",
        "guarantee_restructuring_haircut",
        "guarantee_amount",
        "guaranteed_portion",
        "unguaranteed_portion",
        "guarantor_reference",
    )


@cites("CRR Art. 213")
@cites("CRR Art. 217")
def apply_guarantees(
    exposures: pl.LazyFrame,
    guarantees: pl.LazyFrame,
    counterparty_lookup: pl.LazyFrame,
    config: CalculationConfig,
    rating_inheritance: pl.LazyFrame | None = None,
    *,
    pack: ResolvedRulepack | None = None,
    errors: list[CalculationError] | None = None,
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
        errors: Optional CRM error channel. When provided, guarantees dropped by
            the Art. 213(1)(c)(i) eligibility gate append a CRM012 warning each.
            CRM013 (Art. 201) is NOT raised here: the processor raises it from the
            materialised ``crm_exit`` frame
            (:func:`~rwa_calc.engine.crm.guarantor_eligibility.record_ineligible_guarantors`).

    Returns:
        Exposures with guarantee effects applied
    """
    guarantees = _prepare_guarantees(guarantees, exposures, config, pack=pack, errors=errors)

    exposures = exposures.with_columns(
        pl.col("exposure_reference").alias("parent_exposure_reference"),
    )

    exposures = _apply_guarantee_splits(guarantees, exposures)
    # ``join_cols`` is STALE by 3 untested guarantor_* cols — safe by ASSERTION, not
    # by construction; see ``data.column_spec.ensure_columns``.
    exposures, join_cols = _join_guarantor_counterparty(exposures, counterparty_lookup)
    exposures = _join_guarantor_ratings(exposures, rating_inheritance)

    exposures = exposures.with_columns(
        pl.col("guarantor_entity_type").fill_null("").alias("guarantor_entity_type"),
    )

    # Derive guarantor's exposure class from their entity type. Needed for
    # post-CRM reporting where the guaranteed portion is reported under the
    # guarantor's exposure class.
    exposures = exposures.with_columns(
        pl.col("guarantor_entity_type")
        .replace_strict(ENTITY_TYPE_TO_SA_CLASS, default="")
        .alias("guarantor_exposure_class"),
    )

    exposures = assign_guarantor_approach(exposures, config, present=join_cols)

    # Cross-approach CCF substitution (CRR Art. 111 / COREP C07)
    # When IRB exposure guaranteed by SA counterparty, use SA CCFs for guaranteed
    # portion — the regime's own SA table (CRR Annex I, or PS1/26 Table A1).
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    exposures = _apply_cross_approach_ccf(
        exposures,
        present=join_cols,
        revised_table=resolved_pack.feature("sa_revised_ccf_table"),
    )

    # Add post-CRM composite attributes for regulatory reporting. For the
    # guaranteed portion, the post-CRM counterparty is the guarantor.
    exposures = exposures.with_columns(
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
        (pl.col("guaranteed_portion").fill_null(0.0) > 0).alias("is_guaranteed"),
    )

    # Note: Transient columns (guarantor_entity_type, guarantor_cqs, etc.) are kept
    # because downstream SA/IRB calculators need them for risk weight substitution.
    # They can be dropped in the final output aggregation if needed.

    return exposures


def _prepare_guarantees(
    guarantees: pl.LazyFrame,
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
    errors: list[CalculationError] | None = None,
) -> pl.LazyFrame:
    """Screen, expand and value guarantees before the split.

    Order follows the rule text: the eligibility screen runs on the raw rows
    (one message per input row); each contract's shared cap is read before
    multi-level expansion rescales ``amount_covered``; Art. 233(1)-(3)
    valuation needs the exposure-level E, so it runs after expansion; the
    Art. 237-239 maturity adjustment then applies to G* (Art. 235(1)(a): GA is
    G* "further adjusted for any maturity mismatch").
    """
    # Art. 233 H_fx and Art. 233(2) restructuring-exclusion scalars are
    # regime-invariant pack entries. Production threads the run's pack; direct
    # callers resolve an identical one from config.
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack

    # Art. 213(1)(c)(i) unilateral cancel / change, Art. 234 tranched protection,
    # letters of comfort / keepwells, and the guarantee_type -> credit-derivative
    # normalisation. Also defaults a null protection_type to "guarantee".
    guarantees = screen_unfunded_protection(guarantees, resolved_pack, errors)

    # CRR Art. 237(2)(a): the original-maturity >= 1yr eligibility test is NOT an
    # unconditional pre-filter — Art. 237(2) applies "where there is a maturity
    # mismatch". It is applied inside _apply_maturity_mismatch_to_guarantees
    # (mismatch-conditioned, mirroring the collateral twin in haircuts.py) rather
    # than dropping rows here (P1.232). The original_maturity_years column is
    # ensured so the residual-fallback and the relocated gate can read it
    # (null-PERMISSIVE, P1.10).
    guarantees = ensure_columns(
        guarantees,
        {"original_maturity_years": ColumnSpec(pl.Float64, required=False)},
    )

    guarantees = attach_shared_cap(guarantees)
    guarantees = _resolve_guarantees_multi_level(guarantees, exposures)
    guarantees = value_unfunded_protection(
        guarantees, exposures, exposures.collect_schema().names(), pack=resolved_pack
    )

    # CRR Art. 239(3) / PS1/26 Art. 239(3): maturity mismatch adjustment for
    # unfunded credit protection. When the protection's residual maturity t is
    # shorter than the exposure's effective maturity T, the covered amount G is
    # scaled by (t - 0.25) / (T - 0.25), with T capped at 5y. Applied before
    # splitting so the reduced amount_covered propagates through cap-at-EAD.
    # Framework-agnostic (reads only reporting_date + maturity columns; the
    # multiplier is identical under CRR and Basel 3.1), so it runs
    # unconditionally — mirroring the collateral sibling in collateral.py.
    return _apply_maturity_mismatch_to_guarantees(guarantees, exposures, config)


def _join_guarantor_counterparty(
    exposures: pl.LazyFrame, counterparty_lookup: pl.LazyFrame
) -> tuple[pl.LazyFrame, list[str]]:
    """Join guarantor entity/country/CCP/SCRA; also returns the joined column names.

    ``guarantor_is_natural_person`` is always joined: the Art. 201 gate
    (``guarantor_eligibility``) declines a guarantor whose own counterparty row is
    flagged a natural person, whatever its ``entity_type``. A lookup without the
    column (a direct caller's) reads as the schema default, False; an unmatched
    guarantor is null, which the gate reads as not flagged.
    """
    cp_names = counterparty_lookup.collect_schema().names()
    counterparty_lookup = ensure_columns(
        counterparty_lookup,
        {"is_natural_person": COUNTERPARTY_SCHEMA["is_natural_person"]},
        present=cp_names,
    )
    cp_select_cols = [
        pl.col("counterparty_reference"),
        pl.col("entity_type").str.to_lowercase().alias("guarantor_entity_type"),
        pl.col("is_natural_person").alias("guarantor_is_natural_person"),
    ]
    if "country_code" in cp_names:
        cp_select_cols.append(pl.col("country_code").alias("guarantor_country_code"))
    if "is_ccp_client_cleared" in cp_names:
        cp_select_cols.append(
            pl.col("is_ccp_client_cleared").alias("guarantor_is_ccp_client_cleared")
        )
    if "scra_grade" in cp_names:
        cp_select_cols.append(pl.col("scra_grade").alias("guarantor_scra_grade"))

    exposures = exposures.join(
        counterparty_lookup.select(cp_select_cols),
        left_on="guarantor_reference",
        right_on="counterparty_reference",
        how="left",
    )

    # Ensure optional guarantor columns exist (fill null if not in counterparty data)
    post_join_names = exposures.collect_schema().names()
    fillers: dict[str, PolarsDataType] = {
        "guarantor_country_code": pl.String,
        "guarantor_is_ccp_client_cleared": pl.Boolean,
        "guarantor_scra_grade": pl.String,
    }
    missing = [n for n in fillers if n not in post_join_names]
    exprs = [pl.lit(None).cast(fillers[n]).alias(n) for n in missing]
    return (exposures.with_columns(exprs) if exprs else exposures), [*post_join_names, *missing]


def _join_guarantor_ratings(
    exposures: pl.LazyFrame, rating_inheritance: pl.LazyFrame | None
) -> pl.LazyFrame:
    """Join guarantor CQS / PD / internal_pd from rating inheritance data."""
    if rating_inheritance is None:
        return exposures.with_columns(
            pl.lit(None).cast(pl.Int8).alias("guarantor_cqs"),
            pl.lit(None).cast(pl.Float64).alias("guarantor_pd"),
            pl.lit(None).cast(pl.Float64).alias("guarantor_internal_pd"),
        )

    ri_names = rating_inheritance.collect_schema().names()
    ri_cols = [
        pl.col("counterparty_reference"),
        pl.col("cqs").alias("guarantor_cqs"),
    ]
    # Guarantor PD needed for Basel 3.1 parameter substitution (CRE22.70-85)
    if "pd" in ri_names:
        ri_cols.append(pl.col("pd").alias("guarantor_pd"))
    # Internal PD for approach determination (IRB requires internal rating)
    if "internal_pd" in ri_names:
        ri_cols.append(pl.col("internal_pd").alias("guarantor_internal_pd"))

    exposures = exposures.join(
        rating_inheritance.select(ri_cols),
        left_on="guarantor_reference",
        right_on="counterparty_reference",
        how="left",
    )

    missing_rating_cols: list[pl.Expr] = []
    if "pd" not in ri_names:
        missing_rating_cols.append(pl.lit(None).cast(pl.Float64).alias("guarantor_pd"))
    if "internal_pd" not in ri_names:
        missing_rating_cols.append(pl.lit(None).cast(pl.Float64).alias("guarantor_internal_pd"))
    if missing_rating_cols:
        exposures = exposures.with_columns(missing_rating_cols)
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

    if "beneficiary_type" not in guar_schema.names():  # arch-exempt: early-exit guard
        return guarantees

    bt_lower = pl.col("beneficiary_type").str.to_lowercase()

    # --- 1. Direct guarantees — pass through unchanged ---
    direct_guarantees = guarantees.filter(bt_lower.is_in(DIRECT_BENEFICIARY_TYPES))

    expanded_parts: list[pl.LazyFrame] = [direct_guarantees]

    # --- 2. Facility-level guarantees — cascade pro-rata over the ancestor set ---
    # A guarantee pledged at any ancestor facility (parent, grandparent, ...
    # root) is allocated pro-rata across that facility's whole descendant subtree
    # — mirroring the collateral / provision cascade. The kernel's membership
    # helper explodes ``ancestor_facilities`` (parent + ancestors incl. self,
    # from the HierarchyResolver), falling back to the 1-element [parent] list
    # when absent — identical to the legacy single-level behaviour.
    exp_schema = exposures.collect_schema()
    has_parent_fac = "parent_facility_reference" in exp_schema.names()

    if has_parent_fac:
        facility_guarantees = guarantees.filter(bt_lower == "facility")
        fac_exposures = explode_facility_membership(exposures, exp_schema.names(), alias="_anc_fac")
        expanded_parts.append(
            _allocate_guarantees_pro_rata(facility_guarantees, fac_exposures, "_anc_fac")
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
    Split guaranteed exposures into per-guarantor sub-rows.

    For each exposure with N guarantors (N >= 1), produces N+1 rows:
    - N guarantor sub-rows, each with that guarantor's covered amount
    - 1 remainder sub-row for the uncovered portion

    Non-guaranteed exposures pass through unchanged.

    References:
        CRR Art. 215-217: Each guarantor's portion receives its own risk weight

    Args:
        guarantees: Exposure-level guarantees (after multi-level resolution)
        exposures: Exposures with ead_after_collateral and parent_exposure_reference

    Returns:
        Exposures with guarantee portions set, potentially with additional rows
    """
    guar_cols = guarantees.collect_schema().names()

    # Pre-aggregate by (beneficiary_reference, guarantor) so that multiple
    # protections from the same guarantor (e.g. direct + facility-level) are
    # summed before we decide whether to split.
    guarantees = guarantees.group_by("beneficiary_reference", "guarantor").agg(
        _build_guarantee_agg_exprs(guar_cols),
    )

    # Refresh schema after aggregation
    guar_cols = guarantees.collect_schema().names()
    guar_select = _build_guarantee_select_cols(guar_cols)

    exposures_with_counts = _attach_guarantee_counts(exposures, guarantees)

    # --- Path 1: No guarantees ---
    no_guarantee = _build_no_guarantee_rows(exposures_with_counts)

    # --- Path 2: Guaranteed exposures — row splitting (N >= 1 guarantors) ---
    multi_joined, join_names = _join_multi_guarantees(
        exposures_with_counts, guarantees, guar_select
    )

    guarantor_sub_rows = _build_guarantor_sub_rows(multi_joined, join_names)
    remainder_sub_rows = _build_remainder_sub_rows(multi_joined, join_names)

    # Drop transient columns used during splitting
    transient = [
        "_guar_amount",
        "_guar_ratio",
        "_total_coverage",
        "_scale",
        "_crm_basis",
        "_effective_amount",
        "_effective_ead",
        "_total_effective",
        "amount_covered",
    ]

    guarantor_sub_rows = _drop_columns_if_present(guarantor_sub_rows, transient)
    remainder_sub_rows = _drop_columns_if_present(remainder_sub_rows, transient)

    # Concat all paths
    parts = [no_guarantee, guarantor_sub_rows, remainder_sub_rows]
    return pl.concat(parts, how="diagonal_relaxed")


def _build_guarantee_agg_exprs(guar_cols: list[str]) -> list[pl.Expr]:
    """Build aggregation expressions for guarantees, preserving optional columns."""
    agg_exprs: list[pl.Expr] = [pl.col("amount_covered").sum().alias("amount_covered")]
    # (col_name, alias) — alias differs only for currency, where we always
    # rename to guarantee_currency for downstream FX mismatch logic.
    optional_first: list[tuple[str, str]] = [
        ("guarantee_reference", "guarantee_reference"),
        ("protection_type", "protection_type"),
    ]
    for src, alias in optional_first:
        if src in guar_cols:
            agg_exprs.append(pl.col(src).first().alias(alias))

    # Preserve guarantee currency for FX mismatch haircut (Art. 233(3-4)).
    # Use original_currency (pre-FX-conversion) if available, else currency.
    if "original_currency" in guar_cols:
        agg_exprs.append(pl.col("original_currency").first().alias("guarantee_currency"))
    elif "currency" in guar_cols:
        agg_exprs.append(pl.col("currency").first().alias("guarantee_currency"))

    # Remaining optional pass-through columns.
    for col in (
        "includes_restructuring",
        "guarantor_seniority",
        "guarantee_fx_haircut",
        "guarantee_restructuring_haircut",
    ):
        if col in guar_cols:
            agg_exprs.append(pl.col(col).first().alias(col))
    return agg_exprs


def _build_guarantee_select_cols(guar_cols: list[str]) -> list[str]:
    """Build the list of guarantee columns to select for the multi-join."""
    base = ["beneficiary_reference", "amount_covered", "guarantor"]
    optional = (
        "guarantee_reference",
        "protection_type",
        "guarantee_currency",
        "includes_restructuring",
        "guarantor_seniority",
        "guarantee_fx_haircut",
        "guarantee_restructuring_haircut",
    )
    return base + [c for c in optional if c in guar_cols]


def _attach_guarantee_counts(exposures: pl.LazyFrame, guarantees: pl.LazyFrame) -> pl.LazyFrame:
    """Attach a per-exposure guarantee_count and clear conflicting columns."""
    guarantee_counts = guarantees.group_by("beneficiary_reference").agg(
        pl.len().alias("guarantee_count"),
    )

    exposures_with_counts = exposures.join(
        guarantee_counts,
        left_on="exposure_reference",
        right_on="beneficiary_reference",
        how="left",
    ).with_columns(pl.col("guarantee_count").fill_null(0))

    existing = exposures_with_counts.collect_schema().names()
    to_drop = [c for c in _cols_to_drop_before_join() if c in existing]
    if to_drop:
        exposures_with_counts = exposures_with_counts.drop(to_drop)
    return exposures_with_counts


def _build_no_guarantee_rows(exposures_with_counts: pl.LazyFrame) -> pl.LazyFrame:
    """Return the pass-through rows for exposures with no guarantees."""
    return exposures_with_counts.filter(pl.col("guarantee_count") == 0).with_columns(
        pl.lit(0.0).alias("guaranteed_portion"),
        pl.col("ead_after_collateral").alias("unguaranteed_portion"),
        pl.lit(None).cast(pl.String).alias("guarantor_reference"),
        pl.lit(0.0).alias("guarantee_amount"),
        pl.lit(0.0).alias("original_guarantee_amount"),
        pl.lit(None).cast(pl.String).alias("protection_type"),
        pl.lit(None).cast(pl.String).alias("guarantee_currency"),
        pl.lit(None).cast(pl.Boolean).alias("includes_restructuring"),
        pl.lit(None).cast(pl.String).alias("guarantor_seniority"),
        pl.lit(0.0).alias("guarantee_fx_haircut"),
        pl.lit(0.0).alias("guarantee_restructuring_haircut"),
    )


def _join_multi_guarantees(
    exposures_with_counts: pl.LazyFrame,
    guarantees: pl.LazyFrame,
    guar_select: list[str],
) -> tuple[pl.LazyFrame, list[str]]:
    """Join guarantees onto guaranteed exposures and compute effective amounts.

    Returns the joined frame plus its post-join column names (reused by
    ``_build_guarantor_sub_rows`` so the schema is only materialised once).
    """
    multi_guar_exposures = exposures_with_counts.filter(pl.col("guarantee_count") >= 1)
    multi_guarantees = guarantees.select(guar_select)

    multi_joined = multi_guar_exposures.join(
        multi_guarantees,
        left_on="exposure_reference",
        right_on="beneficiary_reference",
        how="inner",
    )

    # CRR Art. 235(1) / 236(3): the covered part Eg = min(GA, E) measures the
    # exposure value E at the CCF=100% basis (ead_for_crm) -- before any credit
    # conversion factor -- with the CCF re-applied to the covered/uncovered split
    # afterwards. Capping and pro-rating coverage against the post-CCF
    # ead_after_collateral would over-recognise cover on undrawn commitments. For
    # pure on-balance-sheet rows ead_for_crm == ead_after_collateral, so the two
    # bases coincide. Fall back to ead_after_collateral only if ead_for_crm is
    # absent/null (defensive; collateral.py always populates it in the pipeline).
    # ``amount_covered`` already holds the valued protection GA (Art. 233 in
    # protection_value, Art. 237-239 maturity scaling in this module).
    join_names = multi_joined.collect_schema().names()
    multi_joined = multi_joined.with_columns(
        crm_basis_expr(join_names),
        pl.col("amount_covered").alias("_guar_amount"),
    )

    # Cap total coverage to the CCF=100% basis using pro-rata scaling, then derive
    # the coverage fraction (Eg / E) and re-apply the CCF to size the covered EAD.
    return (
        multi_joined.with_columns(
            pl.col("_guar_amount").sum().over("parent_exposure_reference").alias("_total_coverage"),
        )
        .with_columns(
            pl.min_horizontal(
                pl.lit(1.0),
                pl.col("_crm_basis") / pl.col("_total_coverage"),
            ).alias("_scale"),
        )
        .with_columns(
            (pl.col("_guar_amount") * pl.col("_scale")).alias("_effective_amount"),
        )
        .with_columns(
            # Coverage fraction on the CCF=100% basis. Guard against a null/zero
            # basis (rows with no exposure value) to avoid division-by-zero.
            pl.when(pl.col("_crm_basis") > 0)
            .then(pl.col("_effective_amount") / pl.col("_crm_basis"))
            .otherwise(pl.lit(0.0))
            .alias("_guar_ratio"),
        )
        .with_columns(
            # Re-apply the CCF (Art. 236(3)): covered EAD = coverage fraction x
            # post-CCF EAD. Total EAD stays invariant; only the RW split moves.
            (pl.col("_guar_ratio") * pl.col("ead_after_collateral")).alias("_effective_ead"),
        )
        .with_columns(
            pl.col("_effective_ead")
            .sum()
            .over("parent_exposure_reference")
            .alias("_total_effective"),
        )
    ), join_names


@cites("CRR Art. 235")
def _build_guarantor_sub_rows(multi_joined: pl.LazyFrame, schema_names: list[str]) -> pl.LazyFrame:
    """Build the per-guarantor sub-rows for guaranteed exposures.

    ``schema_names`` is the post-join column set from ``_join_multi_guarantees``
    (reused here so the joined schema is only materialised once).
    """
    guar_stock_splits: list[pl.Expr] = [
        # Covered EAD (post-CCF) = coverage fraction x ead_after_collateral. The
        # nominal credit-protection amount (G*) stays on guarantee_amount /
        # original_guarantee_amount. CRR Art. 235(1) / 236(3).
        pl.col("_effective_ead").alias("guaranteed_portion"),
        pl.lit(0.0).alias("unguaranteed_portion"),
        pl.col("_effective_ead").alias("ead_after_collateral"),
        pl.col("_effective_amount").alias("guarantee_amount"),
        pl.col("_guar_amount").alias("original_guarantee_amount"),
        pl.col("guarantor").alias("guarantor_reference"),
        pl.concat_str(
            [pl.col("parent_exposure_reference"), pl.lit("__G_"), pl.col("guarantor")],
        ).alias("exposure_reference"),
    ]
    guar_stock_splits.extend(
        (pl.col(c) * pl.col("_guar_ratio")).alias(c)
        for c in _stock_split_cols()
        if c in schema_names
    )
    return multi_joined.with_columns(guar_stock_splits)


@cites("CRR Art. 235")
def _build_remainder_sub_rows(multi_joined: pl.LazyFrame, schema_names: list[str]) -> pl.LazyFrame:
    """
    Build the borrower-retained remainder sub-row (the uncovered part), one per parent.

    CRR / PS1/26 Art. 235(1)(b): the uncovered part is E less the covered part,
    at the obligor's own risk weight. Emitted as one ``__REM`` row carrying a
    null ``guarantor_reference``. There is no tranched variant: protection that
    covers a band of the loss is screened out before the split
    (``protection_screen``, Art. 234 / 235(2)), so every recognised guarantee is
    an equal-seniority share of the exposure.

    Stock columns are split in proportion to the remainder's share of the parent
    EAD so downstream per-counterparty aggregations stay consistent.
    ``schema_names`` is the post-join column set from ``_join_multi_guarantees``.
    """
    remainder = (
        multi_joined.sort("parent_exposure_reference", "guarantor")
        .group_by("parent_exposure_reference", maintain_order=True)
        .first()
    )
    retained = pl.col("ead_after_collateral") - pl.col("_total_effective")
    retained_ratio = (
        pl.when(pl.col("ead_after_collateral") > 0)
        .then(retained / pl.col("ead_after_collateral"))
        .otherwise(pl.lit(0.0))
    )
    rem_exprs: list[pl.Expr] = [
        pl.lit(0.0).alias("guaranteed_portion"),
        retained.alias("unguaranteed_portion"),
        retained.alias("ead_after_collateral"),
        pl.lit(0.0).alias("guarantee_amount"),
        pl.lit(0.0).alias("original_guarantee_amount"),
        pl.lit(None).cast(pl.String).alias("guarantor_reference"),
        pl.lit(None).cast(pl.String).alias("protection_type"),
        pl.lit(None).cast(pl.String).alias("guarantee_currency"),
        pl.lit(None).cast(pl.Boolean).alias("includes_restructuring"),
        pl.lit(None).cast(pl.String).alias("guarantor_seniority"),
        pl.lit(0.0).alias("guarantee_fx_haircut"),
        pl.lit(0.0).alias("guarantee_restructuring_haircut"),
        pl.concat_str(
            [pl.col("parent_exposure_reference"), pl.lit("__REM")],
        ).alias("exposure_reference"),
    ]
    rem_exprs.extend(
        (pl.col(c) * retained_ratio).alias(c) for c in _stock_split_cols() if c in schema_names
    )
    return remainder.with_columns(rem_exprs)


def _apply_cross_approach_ccf(
    exposures: pl.LazyFrame,
    *,
    present: list[str] | None = None,
    revised_table: bool = False,
) -> pl.LazyFrame:
    """
    Apply cross-approach CCF substitution for guaranteed exposures.

    When an IRB exposure (F-IRB or A-IRB) is guaranteed by an SA counterparty,
    the guaranteed portion must use SA CCFs for COREP C07 reporting.
    If the guarantor is also IRB, the original IRB CCF is retained.

    ``revised_table`` is the run's ``sa_revised_ccf_table`` pack Feature: the
    SA factor is the PS1/26 Art. 111(1) Table A1 one under Basel 3.1 (Row 5
    other commitments 40%, Row 7 unconditionally cancellable 10%, the issued /
    commitment residual split on ``is_obs_commitment``) and the CRR Annex I one
    otherwise. Before, the CRR table was used in both regimes, so a Basel 3.1
    F-IRB unconditionally cancellable line took 0% on its guaranteed part.

    Returns:
        Exposures with CCF-adjusted guaranteed/unguaranteed portions
    """
    names = list(present) if present is not None else exposures.collect_schema().names()
    has_interest = "interest" in names
    has_risk_type = "risk_type" in names

    if not has_risk_type:
        return exposures

    # Only IRB exposures with SA guarantors and off-balance-sheet items
    needs_ccf_sub = (
        pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value])
        & (pl.col("guarantor_approach") == "sa")
        & (pl.col("guaranteed_portion") > 0)
        & (pl.col("nominal_amount") > 0)
    )

    sa_ccf = sa_ccf_expression(
        is_basel_3_1=revised_table,
        commitment_col="is_obs_commitment" if "is_obs_commitment" in names else None,
    )

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
    has_provision_cols = "provision_on_drawn" in names

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
        if "nominal_after_provision" in names
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


def _allocate_guarantees_pro_rata(
    guarantees: pl.LazyFrame,
    exposures: pl.LazyFrame,
    group_col: str,
) -> pl.LazyFrame:
    """Allocate amount-based guarantees pro-rata by ead_after_collateral within a group.

    Thin parameterisation of the allocation kernel's expand direction
    (:func:`rwa_calc.engine.kernels.allocation.expand_items_pro_rata`),
    preserving the guarantee-copy drift axes: the basis is
    ``ead_after_collateral`` (post-collateral EAD — deliberately different
    from the collateral copy's ``ead_for_crm``); the items -> weights join is
    INNER (facility / counterparty guarantees whose group has no exposures
    vanish silently); expanded rows are re-anchored as direct loan-level
    beneficiaries (``beneficiary_type = "loan"``).
    """
    return expand_items_pro_rata(
        guarantees,
        exposures,
        group_key=group_col,
        basis=pl.col("ead_after_collateral"),
        scale_columns=("amount_covered",),
        rewrite_type="loan",
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
        CRR Art. 193(1): a guarantee must never raise the RWEA (sa/rw_adjustments.py)
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
    # The split emits one "<parent>__REM" remainder row per parent, but this runs
    # in the calculators, AFTER re_splitter has renamed a split remainder to
    # "__REM_sec" / "__REM_res" — so match the stem, not the suffix.
    is_remainder = pl.col("exposure_reference").str.contains("__REM")
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


@cites("CRR Art. 217")
@cites("CRR Art. 237")
@cites("PS1/26, paragraph 237")
def _apply_maturity_mismatch_to_guarantees(
    guarantees: pl.LazyFrame,
    exposures: pl.LazyFrame,
    config: CalculationConfig,
) -> pl.LazyFrame:
    """
    Apply CRR Art. 237/239(3) maturity mismatch treatment to guarantee amounts.

    When the protection's residual maturity ``t`` is shorter than the
    exposure's effective maturity ``T``, the covered amount ``G`` is scaled:

        GA = G* × (t - 0.25) / (T - 0.25)

    with ``T`` capped at 5.0 years and both ``t`` and ``T`` floored at 0.25.
    Scaling is applied to ``amount_covered`` (G*, already valued under
    Art. 233) before the split, so the reduced protection value propagates
    through cap-at-EAD.

    Three Art. 237 eligibility gates ZERO coverage (rather than merely scaling
    it) before the 239(3) formula, mirroring the collateral sibling in
    ``engine/crm/haircuts.py``. All three bind ONLY WHERE a maturity mismatch
    exists (Art. 237(2) chapeau) — matched / protection-outlives-exposure
    guarantees stay recognised:

    - Art. 237(1): credit protection whose RAW residual maturity is < 3 months
      AND shorter than the exposure is not recognised. The test runs on the
      pre-floor residuals so a short exposure — whose ``T`` also floors to 0.25
      and would mask the mismatch under the scaling formula — no longer retains
      full coverage.
    - Art. 162(3)/237(2)(b): where the exposure is subject to the one-day IRB
      maturity floor (daily-margined repos/SFTs), ANY maturity mismatch makes
      the protection ineligible. The ``has_one_day_maturity_floor`` flag is
      joined from the exposure; null/absent is PERMISSIVE (treated as no floor).
    - Art. 237(2)(a): protection whose ORIGINAL maturity is < 1 year is ineligible
      where a mismatch exists. Relocated here from an unconditional pre-filter
      (P1.232) so matched short-dated (e.g. trade-finance) guarantees are no
      longer discarded. Reads ``original_maturity_years`` (the original term, NOT
      the residual ``t``); null is PERMISSIVE (>= 1y).

    The protection residual maturity ``t`` is derived from the guarantee
    row's ``maturity_date`` if present, otherwise from
    ``original_maturity_years``. The exposure residual ``T`` is derived
    from the exposure's ``maturity_date``.

    References:
        CRR / PS1-26 Art. 237(1): <3-month-and-shorter protection ineligibility.
        CRR / PS1-26 Art. 237(2)(a): <1y-original protection, mismatch-conditioned.
        CRR / PS1-26 Art. 237(2)(b) with Art. 162(3): one-day-floor exposures
            + any mismatch => ineligible.
        CRR Art. 238(1): maturity of credit protection — ``t`` is the RESIDUAL
            maturity (time remaining to protection maturity), not the original
            contract term; the residual from ``maturity_date`` therefore wins
            and ``original_maturity_years`` is only a fallback.
        CRR Art. 239(3): maturity mismatch adjustment formula.
    """
    guar_schema = guarantees.collect_schema()
    guar_cols = guar_schema.names()
    exp_schema = exposures.collect_schema()
    exp_cols = exp_schema.names()

    # Need exposure maturity_date and at least one of guarantee maturity_date
    # / original_maturity_years to compute t and T.
    if "maturity_date" not in exp_cols:
        return guarantees
    has_guar_maturity_date = "maturity_date" in guar_cols
    has_guar_original_maturity = "original_maturity_years" in guar_cols
    if not (has_guar_maturity_date or has_guar_original_maturity):
        return guarantees

    # Bring exposure residual maturity (years) and the Art. 162(3) one-day
    # maturity-floor flag onto each guarantee row.
    exp_t_expr = exact_fractional_years_expr(config.reporting_date, "maturity_date").alias("_exp_T")
    exp_select = [pl.col("exposure_reference"), exp_t_expr]
    has_1d_floor_col = "has_one_day_maturity_floor" in exp_cols
    if has_1d_floor_col:
        exp_select.append(
            pl.col("has_one_day_maturity_floor").fill_null(False).alias("_has_1d_floor")
        )
    exp_lookup = exposures.select(exp_select)

    guarantees = guarantees.join(
        exp_lookup,
        left_on="beneficiary_reference",
        right_on="exposure_reference",
        how="left",
    )
    # Null-PERMISSIVE: an exposure with no flag, an absent column, or a
    # join-miss beneficiary is treated as NOT subject to the one-day floor
    # (mirrors the collateral sibling's default).
    if has_1d_floor_col:
        guarantees = guarantees.with_columns(pl.col("_has_1d_floor").fill_null(False))
    else:
        guarantees = guarantees.with_columns(pl.lit(False).alias("_has_1d_floor"))

    # Compute t = RESIDUAL maturity (Art. 238(1)): the time REMAINING to
    # protection maturity, derived from the guarantee ``maturity_date`` minus
    # the reporting date. ``original_maturity_years`` is the ORIGINAL contract
    # term and must NOT override the residual — otherwise a seasoned guarantee
    # (long original term, short residual) is over-recognised. It is used for
    # ``t`` only as a fallback when ``maturity_date`` is null. The separate
    # Art. 237(2)(a) >=1y eligibility gate upstream still reads
    # ``original_maturity_years`` (the original term). A null PROTECTION maturity
    # t stays PERMISSIVE — no scaling, no gate, full coverage (t-side unknown =>
    # no basis to reduce). This is asymmetric with the EXPOSURE maturity T, which
    # a null defaults CONSERVATIVELY to 5y below (Art. 237 targets short
    # protection on longer exposures, so an unknown exposure horizon must not
    # defeat the gates).
    if has_guar_maturity_date and has_guar_original_maturity:
        t_from_date = exact_fractional_years_expr(config.reporting_date, "maturity_date")
        t_raw = (
            pl.when(pl.col("maturity_date").is_not_null())
            .then(t_from_date)
            .otherwise(pl.col("original_maturity_years"))
        )
    elif has_guar_maturity_date:
        t_raw = exact_fractional_years_expr(config.reporting_date, "maturity_date")
    else:
        t_raw = pl.col("original_maturity_years")

    # Art. 239(3) floors / caps: t and T floored at 0.25, T capped at 5.0.
    # A null / join-miss exposure maturity defaults to a 5y exposure (the most
    # conservative recognised maturity), aligning with the collateral twin
    # (haircuts.py) so a guarantee on a null-maturity exposure is still subject
    # to the mismatch gates and the 239(3) scaling rather than silently keeping
    # full coverage.
    floor = pl.lit(0.25)
    cap = pl.lit(5.0)
    exp_T = pl.col("_exp_T").fill_null(5.0)  # raw exposure residual; null -> 5y
    t_eff_safe = (
        pl.when(t_raw.is_null())
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.max_horizontal(t_raw, floor))
    )
    # The 0.25 floor lives ONLY on the scaling denominator (its purpose); the
    # eligibility gates below compare the RAW residuals.
    exp_t_eff = pl.max_horizontal(pl.min_horizontal(exp_T, cap), floor)

    # Mismatch (floored) drives the Art. 239(3) scaling.
    is_mismatch = t_eff_safe.is_not_null() & (t_eff_safe < exp_t_eff)
    scale = (t_eff_safe - floor) / (exp_t_eff - floor)

    # Art. 237(1): a RAW protection residual < 3 months that is also shorter than
    # the exposure is not recognised. Tested pre-floor (audit: "raw t < 0.25 AND
    # t < raw T") so a short exposure — whose T also floors to 0.25 and would
    # mask the mismatch under the scaling formula — no longer retains full
    # coverage, while a protection that OUTLIVES a sub-3-month exposure (t >= T)
    # stays recognised (Art. 238: no adjustment when protection >= exposure).
    # (The collateral twin labels this sub-point 237(2)(a) and floors the
    # exposure maturity at 0.25 for its mismatch test; per the audit we compare
    # the raw T so the outlives case is not spuriously zeroed.)
    raw_mismatch = t_raw.is_not_null() & (t_raw < exp_T)
    short_protection = raw_mismatch & (t_raw < floor)
    # Art. 162(3)/237(2)(b): a one-day-M-floor exposure (daily-margined repo/SFT)
    # with ANY maturity mismatch makes the protection ineligible.
    one_day_floor_gate = pl.col("_has_1d_floor") & raw_mismatch
    # Art. 237(2)(a): unfunded protection whose ORIGINAL maturity is < 1 year is
    # ineligible ONLY where a maturity mismatch exists (Art. 237(2) chapeau) — a
    # matched or protection-outlives-exposure short-dated guarantee stays
    # recognised. Relocated here (P1.232) from the former UNCONDITIONAL pre-filter
    # in _prepare_guarantees, mirroring the collateral twin's conditioning
    # (haircuts.py). Null original maturity is PERMISSIVE (treated as >= 1y => not
    # ineligible), preserving the P1.10 policy. Reads the ORIGINAL term
    # (original_maturity_years), NOT the residual t that feeds the scaling (P1.219).
    orig_maturity = (
        pl.col("original_maturity_years").fill_null(10.0)
        if has_guar_original_maturity
        else pl.lit(10.0)
    )
    short_original_gate = raw_mismatch & (orig_maturity < 1.0)

    # Zero-gates take priority over the scaling; otherwise scale on mismatch,
    # else full coverage. Mirrors the collateral sibling (engine/crm/haircuts.py).
    scale_safe = (
        pl.when(short_protection | one_day_floor_gate | short_original_gate)
        .then(pl.lit(0.0))
        .when(is_mismatch)
        .then(scale)
        .otherwise(pl.lit(1.0))
    )

    guarantees = guarantees.with_columns(
        (pl.col("amount_covered") * scale_safe).alias("amount_covered"),
    )
    return _drop_columns_if_present(guarantees, ["_exp_T", "_has_1d_floor"])


def _drop_columns_if_present(lf: pl.LazyFrame, cols: list[str]) -> pl.LazyFrame:
    """Drop columns, ignoring absent ones (Polars ``strict=False``, no schema walk).

    Always derives, so an edge brand no longer survives a no-op drop. No call site here
    needs one; a future one gets ``EdgeContractViolation`` at bundle build, not a number.
    """
    return lf.drop(cols, strict=False)
