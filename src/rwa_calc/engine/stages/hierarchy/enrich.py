"""
Unified-exposure-frame enrichment for the hierarchy stage.

Pipeline position:
    Loader -> HierarchyResolver (stages/hierarchy) -> Classifier
    Sub-module of the hierarchy stage package; consumed by ``unify``
    (QRRE propagation + rating attach) and ``resolver`` (short-term
    override, property coverage, LTV, lending group).

Key responsibilities:
- Coalesce QRRE-relevant facility-level columns onto every exposure row
  (Site B of the ``_FACILITY_QRRE_COUPLED_COLUMNS`` coupling).
- Attach counterparty rating fields (cqs / pd / internal_pd / model_id).
- Apply the per-exposure short-term ECAI rating override.
- Add property-collateral coverage, LTV metadata, and lending-group totals
  to the unified frame via ``.over()`` window allocation.

References:
- CRR Art. 131: Short-term rating override for institutional exposures
- CRR Art. 135 / 136 / 138 / 139 / 140: ECAI rating use and mapping
- CRR Art. 123(c): retail threshold exclusion (residential property)
- CRR Art. 126: income-producing CRE risk-weight gate
- CRR Art. 4(1)(39): group of connected clients (lending group totals)
- PRA PS1/26 Art. 120(2B) Table 4A / Art. 122(3) Table 6A: short-term tables
- PRA PS1/26 Art. 121(4): SCRA short-term trade-finance LC window
- PRA PS1/26 Art. 124(4) / Art. 124A / Art. 124J: non-qualifying RE gate
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import misscoped_short_term_rating_warning
from rwa_calc.engine.entity_class_maps import ENTITY_TYPES_BY_SA_CLASS
from rwa_calc.engine.kernels.allocation import (
    NO_DEFAULT,
    LevelSpec,
    allocate_multi_level,
    beneficiary_level_expr,
    coalesce_attribute_levels,
    level_attribute_lookup,
)
from rwa_calc.engine.utils import has_required_columns, partition_by_nullable

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import CounterpartyLookup
    from rwa_calc.contracts.errors import CalculationError

logger = logging.getLogger(__name__)


def propagate_facility_qrre_columns(
    exposures: pl.LazyFrame,
    facilities: pl.LazyFrame | None,
) -> pl.LazyFrame:
    """Coalesce QRRE-relevant facility-level columns onto every exposure row.

    ``facility_undrawn`` exposures already carry ``is_revolving``,
    ``is_qrre_transactor``, ``facility_limit`` (set in the facility-undrawn
    select); loans / contingents have NULLs from the diagonal_relaxed concat.
    This join fills them in from the parent facility.

    Always returns a frame where ``is_revolving``, ``is_qrre_transactor``,
    and ``facility_limit`` exist with safe defaults.
    """
    # Site B of the two-site QRRE coupling pinned by
    # `_FACILITY_QRRE_COUPLED_COLUMNS` (stages/hierarchy/__init__.py). Site A
    # lives in `facility_undrawn._undrawn_select_expressions` and projects the
    # same column set when synthesising facility_undrawn rows; here we
    # join+coalesce the parent facility's values onto loan / contingent
    # exposure rows. The two sites use deliberately different shapes (project
    # vs. join+coalesce) and must not be merged — only their column set is
    # shared.
    if facilities is not None:
        exposures, qrre_schema = _join_facility_qrre_columns(exposures, facilities)
    else:
        qrre_schema = set(exposures.collect_schema().names())

    # Ensure QRRE columns always exist with safe defaults.
    # After the facility join branch above, these columns may or may not exist
    # depending on the facility data. Reuse exp_schema from the join branch
    # (or check fresh if we skipped the branch entirely).
    exposures = _apply_qrre_defaults(exposures, qrre_schema)

    # PRA PS1/26 Art. 121(4): the SCRA short-term window extends to self-
    # liquidating trade-finance LCs. The flag lives on the facility row;
    # drawn loans booked under a trade-LC facility have no facility_reference
    # column to inherit from, so OR-aggregate the flag across the facilities
    # of the same counterparty and broadcast it to every exposure of that
    # counterparty.
    # Coalesce preserves any explicit per-row value (e.g. on the synthetic
    # facility_undrawn rows that already carry the flag from their source
    # facility) and only fills nulls from the counterparty-level OR.
    if facilities is not None:
        exposures = _broadcast_trade_lc_flag(exposures, facilities)

    return exposures


@cites("CRR Art. 135")
@cites("CRR Art. 136")
@cites("CRR Art. 138")
@cites("CRR Art. 139")
def attach_counterparty_rating(
    exposures: pl.LazyFrame,
    counterparty_lookup: CounterpartyLookup,
) -> pl.LazyFrame:
    """Join counterparty rating fields onto every exposure row.

    ``cqs`` and ``pd`` are used by SA / IRB calculators; ``internal_pd`` is
    used by the classifier to gate IRB approach on internal-rating
    availability; ``external_cqs`` is carried for audit trail; ``model_id``
    (sourced from ``internal_model_id`` via the rating inheritance pipeline)
    links to model_permissions for per-model approach gating.
    """
    cp_schema = set(counterparty_lookup.counterparties.collect_schema().names())
    cp_select = [pl.col("counterparty_reference"), pl.col("cqs"), pl.col("pd")]
    if "internal_pd" in cp_schema:
        cp_select.append(pl.col("internal_pd"))
    if "external_cqs" in cp_schema:
        cp_select.append(pl.col("external_cqs"))
    if "external_rating_is_issue_specific" in cp_schema:
        cp_select.append(pl.col("external_rating_is_issue_specific"))
    if "internal_model_id" in cp_schema:
        cp_select.append(pl.col("internal_model_id"))

    exposures = exposures.join(
        counterparty_lookup.counterparties.select(cp_select),
        on="counterparty_reference",
        how="left",
    )

    # Ensure internal_pd, external_cqs, and model_id always exist for classifier
    rating_defaults = []
    if "internal_pd" not in cp_schema:
        rating_defaults.append(pl.lit(None).cast(pl.Float64).alias("internal_pd"))
    if "external_cqs" not in cp_schema:
        rating_defaults.append(pl.lit(None).cast(pl.Int8).alias("external_cqs"))
    # PRA PS1/26 Art. 139(2B): default provenance flag when no external rating
    # resolved — treat as issue-specific (legacy behaviour, no disapplication).
    if "external_rating_is_issue_specific" not in cp_schema:
        rating_defaults.append(
            pl.lit(True).cast(pl.Boolean).alias("external_rating_is_issue_specific")
        )
    if rating_defaults:
        exposures = exposures.with_columns(rating_defaults)

    # model_id: sourced from internal_model_id (rating inheritance pipeline).
    # We know internal_model_id was joined from cp_schema above.
    if "internal_model_id" in cp_schema:
        return exposures.with_columns(pl.col("internal_model_id").alias("model_id")).drop(
            "internal_model_id"
        )
    return exposures.with_columns(pl.lit(None).cast(pl.String).alias("model_id"))


@cites("CRR Art. 131")
@cites("CRR Art. 140")
def apply_short_term_rating_override(
    exposures: pl.LazyFrame,
    ratings: pl.LazyFrame | None,
    counterparty_lookup: CounterpartyLookup | None = None,
    errors: list[CalculationError] | None = None,
) -> pl.LazyFrame:
    """Apply per-exposure short-term rating override.

    Short-term ECAI assessments under PRA PS1/26 Art. 120(2B) Table 4A and
    Art. 122(3) Table 6A are issue-specific — each rating row attaches to a
    single exposure via ``(scope_type, scope_id)``. When a short-term rating
    row matches an exposure, its ``cqs`` overrides the counterparty-level
    rating attached by ``attach_counterparty_rating`` and the derived
    ``has_short_term_ecai`` flag is set to True, signalling the SA engine to
    route via Table 4A / Table 6A.

    Scope matching:

    - ``scope_type='facility'``  -> matches the source facility's drawn loans,
      its synthetic ``facility_undrawn`` row, and any descendant exposure via
      ``parent_facility_reference`` / ``root_facility_reference``.
    - ``scope_type='loan'``      -> matches the loan exposure with the same
      ``exposure_reference`` and ``exposure_type='loan'``.
    - ``scope_type='contingent'`` -> matches the contingent exposure with the
      same ``exposure_reference`` and ``exposure_type='contingent'``.

    Ties (multiple short-term ratings for the same exposure) are resolved by
    picking the row with the lowest CQS, breaking ties by latest
    ``rating_date``. This mirrors the external best-rating selection in
    ``ratings.build_rating_inheritance_lazy``.

    Always returns ``exposures`` augmented with a ``has_short_term_ecai``
    boolean column (False when no override matched).
    """
    st_ratings = _prepare_short_term_lookup(ratings)
    if st_ratings is None:
        return exposures.with_columns(pl.lit(False).alias("has_short_term_ecai"))

    exp_schema = set(exposures.collect_schema().names())
    match_branches = _build_short_term_match_branches(exp_schema)

    # Track which scope branches actually produce a match so we can
    # coalesce the resulting cqs in priority order: loan > contingent >
    # facility (most specific wins).
    joined_scopes: list[str] = []
    for scope, key_expr in match_branches:
        scope_lookup = st_ratings.filter(pl.col("_st_scope_type") == scope).select(
            [
                pl.col("_st_cp"),
                pl.col("_st_scope_id"),
                pl.col("_st_cqs").alias(f"_st_{scope}_cqs"),
            ]
        )
        exposures = exposures.with_columns(key_expr.alias(f"_match_key_{scope}"))
        exposures = exposures.join(
            scope_lookup,
            left_on=["counterparty_reference", f"_match_key_{scope}"],
            right_on=["_st_cp", "_st_scope_id"],
            how="left",
        ).drop(f"_match_key_{scope}")
        joined_scopes.append(scope)

    if not joined_scopes:
        return exposures.with_columns(pl.lit(False).alias("has_short_term_ecai"))

    # Coalesce in priority order: loan > contingent > facility (most
    # specific scope wins).
    priority = ["loan", "contingent", "facility"]
    ordered = [s for s in priority if s in joined_scopes]
    st_cqs_expr = pl.coalesce([pl.col(f"_st_{s}_cqs") for s in ordered])

    # Art. 140(1) / CRE21.16 obligor-class gate: short-term ECAI assessments may
    # be used ONLY for institution / corporate obligors. Join the raw entity_type
    # (from the counterparty lookup — no class column exists on the frame yet;
    # the classifier derives it later) and disqualify a match on any other class.
    # A mis-scoped match is ignored: has_short_term_ecai stays False, cqs keeps
    # its counterparty-level value and _st_assessment_cqs stays null, so the row
    # AND the Art. 120(3)(c) spillover / Art. 140(2) contamination helpers that
    # run AFTER the gate all inherit the rejection for free.
    #   Ordering: (1) scope-match [above] -> (2) THIS GATE -> (3) spillover ->
    #   (4) contamination flags.
    has_gate = counterparty_lookup is not None
    if has_gate:
        eligible = list(ENTITY_TYPES_BY_SA_CLASS["institution"]) + list(
            ENTITY_TYPES_BY_SA_CLASS["corporate"]
        )
        gate_lookup = counterparty_lookup.counterparties.select(
            pl.col("counterparty_reference"),
            pl.col("entity_type").str.to_lowercase().alias("_st_gate_entity_type"),
        )
        exposures = exposures.join(gate_lookup, on="counterparty_reference", how="left")
        # fill_null("") before is_in: Polars propagates null through is_in, so a
        # null/unknown entity_type (or a join-miss) would otherwise yield a NULL
        # eligibility -> a null has_short_term_ecai flag AND a null-dropped DQ009
        # filter (warning silently lost). "" resolves to ineligible -> clean
        # rejection + DQ009 emitted. Mirrors the entity_type null-guard idiom in
        # engine/sa/risk_weights.py.
        st_class_eligible = pl.col("_st_gate_entity_type").fill_null("").is_in(eligible)
    else:
        st_class_eligible = pl.lit(True)  # noqa: FBT003

    # Override: when a short-term cqs matched AND the obligor class is eligible,
    # replace the cqs column and set has_short_term_ecai=True. SA Tables 4A / 6A
    # are keyed off cqs only — rating_agency / rating_value are audit columns
    # added later by the classifier and intentionally not overridden here.
    #
    # Two scratch columns are carried into the obligor-level Art. 120(3)(c)
    # spillover step below: ``_st_assessment_cqs`` (the matched short-term ECAI
    # cqs, non-null only on the directly-rated ELIGIBLE exposure) and
    # ``_general_cqs`` (the obligor's pre-override counterparty cqs).
    has_st = st_cqs_expr.is_not_null() & st_class_eligible

    # Art. 140(1) DQ warning: a match rejected purely by the class gate (matched
    # but ineligible) is a mis-scoped rating — record one DQ009 per such
    # exposure before the scratch entity_type is dropped.
    if errors is not None and has_gate:
        _record_misscoped_st_ratings(
            exposures, st_cqs_expr.is_not_null() & st_class_eligible.not_(), errors
        )

    exposures = exposures.with_columns(
        [
            has_st.alias("has_short_term_ecai"),
            pl.when(has_st)
            .then(st_cqs_expr)
            .otherwise(pl.lit(None, dtype=pl.Int8))
            .cast(pl.Int8)
            .alias("_st_assessment_cqs"),
            pl.col("cqs").cast(pl.Int8).alias("_general_cqs"),
            pl.when(has_st).then(st_cqs_expr).otherwise(pl.col("cqs")).cast(pl.Int8).alias("cqs"),
        ]
    )
    exposures = _apply_obligor_short_term_spillover(exposures)
    # Art. 140(2) obligor-level contamination flags — reads the pristine
    # ``_st_assessment_cqs`` scratch here, BEFORE the drop below. The two flag
    # columns it emits are not ``_st_*`` scratch, so they survive the drop.
    exposures = _apply_obligor_st_contamination_flags(exposures)
    scratch = [f"_st_{s}_cqs" for s in joined_scopes] + ["_st_assessment_cqs", "_general_cqs"]
    if has_gate:
        scratch.append("_st_gate_entity_type")
    return exposures.drop(scratch)


def _record_misscoped_st_ratings(
    exposures: pl.LazyFrame,
    mis_scoped: pl.Expr,
    errors: list[CalculationError],
) -> None:
    """Append one DQ009 warning per Art. 140(1)-mis-scoped short-term rating.

    Targeted mid-pipeline collect of the mis-scoped rows' ``exposure_reference``
    and scratch ``_st_gate_entity_type`` only — the ratings/mis-scope set is a
    small dimension (empty on a well-scoped portfolio), so materialising just
    those two columns to build the per-exposure DQ messages is cheap.
    """
    dropped = (
        exposures.filter(mis_scoped).select("exposure_reference", "_st_gate_entity_type").collect()
    )
    for row in dropped.iter_rows(named=True):
        errors.append(
            misscoped_short_term_rating_warning(
                exposure_reference=row["exposure_reference"],
                obligor_entity_type=row["_st_gate_entity_type"],
            )
        )


def enrich_with_property_coverage(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame | None,
) -> pl.LazyFrame:
    """
    Add property collateral coverage columns to exposures inline.

    Calculates two separate values per exposure:
    1. residential_collateral_value: For CRR Art. 123(c) retail threshold exclusion
       (only residential property counts for threshold exclusion)
    2. property_collateral_value: For retail_mortgage classification
       (both residential AND commercial property qualify for mortgage treatment)

    Uses .over() window functions for facility/counterparty allocation weights
    instead of group_by + join-back, avoiding plan tree branching.

    Args:
        exposures: Unified exposures with hierarchy metadata
        collateral: Collateral data with property_type and market_value

    Returns:
        Exposures with columns added: residential_collateral_value,
        property_collateral_value, has_facility_property_collateral,
        exposure_for_retail_threshold
    """
    # Per CRR Article 147, "total amount owed" = drawn amount only (not undrawn)
    exposures = exposures.with_columns(
        pl.col("drawn_amount").clip(lower_bound=0.0).alias("total_exposure_amount"),
    )

    required_cols = {
        "beneficiary_reference",
        "collateral_type",
        "market_value",
        "property_type",
    }
    if not has_required_columns(collateral, required_cols):
        return exposures.with_columns(
            [
                pl.lit(0.0).alias("residential_collateral_value"),
                pl.lit(0.0).alias("property_collateral_value"),
                pl.lit(0.0).alias("residential_collateral_value_uncapped"),
                pl.lit(0.0).alias("commercial_collateral_value_uncapped"),
                pl.lit(False).alias("has_facility_property_collateral"),
                pl.lit(False).alias("re_collateral_non_qualifying"),
                pl.col("total_exposure_amount").alias("exposure_for_retail_threshold"),
            ]
        )

    # Single filter for all property collateral; split residential inline
    all_property_collateral = collateral.filter(
        pl.col("collateral_type").str.to_lowercase() == "real_estate"
    )
    # PRA PS1/26 Art. 124(4): a single non-qualifying RE component (Art. 124A
    # failure, e.g. valuation-independence breach) forces the WHOLE mixed-RE
    # exposure to Art. 124J. Track per-beneficiary whether any RE collateral
    # row fails the qualifying test so the classifier can fire the gate.
    # ``is_qualifying_re`` has no schema default — null means "unreported"
    # and is treated as qualifying here (fill_null(True) is a value fill).
    is_non_qualifying_re = pl.col("is_qualifying_re").fill_null(True) == False  # noqa: E712

    # Multi-level linking with .over() allocation weights
    exposures = _join_property_collateral_multi_level(
        exposures,
        all_property_collateral,
        is_non_qualifying_re=is_non_qualifying_re,
    )

    # Fill nulls, then cap at exposure amount and derive threshold.
    # Preserve the UNCAPPED residential / commercial RE collateral values
    # for the loan-splitter: the PRA PS1/26 Art. 124(4) pro-rata split is by
    # raw collateral value (and the 0.55xV cap is also on raw property value),
    # so the per-exposure cap applied below — which exists for the CRR retail
    # threshold — must not distort the split shares.
    exposures = (
        exposures.with_columns(
            [
                pl.col("residential_collateral_value").fill_null(0.0),
                pl.col("property_collateral_value").fill_null(0.0),
                pl.col("re_collateral_non_qualifying").fill_null(False),
            ]
        )
        .with_columns(
            [
                pl.col("residential_collateral_value").alias(
                    "residential_collateral_value_uncapped"
                ),
                (pl.col("property_collateral_value") - pl.col("residential_collateral_value"))
                .clip(lower_bound=0.0)
                .alias("commercial_collateral_value_uncapped"),
            ]
        )
        .with_columns(
            [
                pl.min_horizontal("residential_collateral_value", "total_exposure_amount").alias(
                    "residential_collateral_value"
                ),
                pl.min_horizontal("property_collateral_value", "total_exposure_amount").alias(
                    "property_collateral_value"
                ),
                (
                    pl.col("total_exposure_amount")
                    - pl.min_horizontal("residential_collateral_value", "total_exposure_amount")
                ).alias("exposure_for_retail_threshold"),
            ]
        )
    )

    return exposures


def enrich_with_lending_group(
    exposures: pl.LazyFrame,
    lending_mappings: pl.LazyFrame | None,
) -> pl.LazyFrame:
    """
    Add lending group reference and exposure totals to each exposure.

    Uses .over() window functions to compute group totals inline instead of
    group_by + join-back, avoiding plan tree branching.

    Per CRR Art. 123(c), the adjusted_exposure (excluding residential property)
    is used for retail threshold testing. When a counterparty is not part of
    an explicit lending group, it is treated as a group-of-one per CRR Art.
    4(1)(39) ("group of connected clients") — totals are aggregated across
    the counterparty's own exposures rather than leaving the per-row value.

    Args:
        exposures: Exposures with property coverage columns already added
        lending_mappings: Lending group parent-child mappings, or None when
            no lending-group table was supplied — every counterparty is
            then a group-of-one (identical to an empty mappings table)

    Returns:
        Exposures with lending_group_reference, lending_group_total_exposure,
        and lending_group_adjusted_exposure columns added
    """
    if lending_mappings is None:
        # No lending-group table: every row's group reference is null, so
        # the null-partition fallback below aggregates per counterparty —
        # exactly the empty-mappings behaviour.
        exposures = exposures.with_columns(
            pl.lit(None).cast(pl.String).alias("lending_group_reference")
        )
    else:
        # Build lending group membership
        lending_groups = lending_mappings.select(
            [
                pl.col("parent_counterparty_reference").alias("lending_group_reference"),
                pl.col("child_counterparty_reference").alias("member_counterparty_reference"),
            ]
        )

        parent_as_member = lending_mappings.select(
            [
                pl.col("parent_counterparty_reference").alias("lending_group_reference"),
                pl.col("parent_counterparty_reference").alias("member_counterparty_reference"),
            ]
        ).unique()

        all_members = pl.concat(
            [lending_groups, parent_as_member],
            how="vertical",
        ).unique(subset=["member_counterparty_reference"], keep="first")

        # Join to get lending group reference
        exposures = exposures.join(
            all_members,
            left_on="counterparty_reference",
            right_on="member_counterparty_reference",
            how="left",
        )

    # .over() window functions for group totals (no self-join!).
    # When no lending group, aggregate over counterparty_reference so the
    # retail threshold test sees the obligor's full exposure, not a single
    # line. lending_group_reference is left-join nullable, so the null-
    # partition guard prevents pooling unrelated unmapped rows.
    exposures = exposures.with_columns(
        [
            partition_by_nullable(
                pl.col("drawn_amount").clip(lower_bound=0.0).sum().over("lending_group_reference")
                + pl.col("nominal_amount").sum().over("lending_group_reference"),
                "lending_group_reference",
                pl.col("drawn_amount").clip(lower_bound=0.0).sum().over("counterparty_reference")
                + pl.col("nominal_amount").sum().over("counterparty_reference"),
            ).alias("lending_group_total_exposure"),
            partition_by_nullable(
                pl.col("exposure_for_retail_threshold").sum().over("lending_group_reference"),
                "lending_group_reference",
                pl.col("exposure_for_retail_threshold").sum().over("counterparty_reference"),
            ).alias("lending_group_adjusted_exposure"),
        ]
    )

    return exposures


def add_collateral_ltv(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame | None,
) -> pl.LazyFrame:
    """
    Add LTV and property metadata from collateral for real estate risk weights.

    Joins collateral property_ltv, property_type, is_income_producing, and
    is_qualifying_re to exposures where collateral is linked via
    beneficiary_reference. For mortgages and commercial RE, LTV determines risk
    weight. For CRE (CRR Art. 126), income cover status determines 50% vs 100%
    risk weight. Non-qualifying RE (Art. 124J) gets separate treatment under B31.

    Supports three levels of collateral linking based on beneficiary_type:
    1. Direct (exposure/loan): beneficiary_reference matches exposure_reference
    2. Facility: beneficiary_reference matches parent_facility_reference
    3. Counterparty: beneficiary_reference matches counterparty_reference

    Args:
        exposures: Unified exposures with exposure_reference
        collateral: Collateral data with beneficiary_reference and property_ltv (optional)

    Returns:
        Exposures with ltv, property_type, has_income_cover, and
        is_qualifying_re columns added
    """
    # Check if collateral is valid for LTV processing
    # Requires beneficiary_reference and property_ltv columns
    required_cols = {"beneficiary_reference", "property_ltv"}
    if not has_required_columns(collateral, required_cols):
        return _add_ltv_defaults_for_missing_collateral(exposures)

    # Filter for collateral with LTV data
    ltv_collateral = collateral.filter(pl.col("property_ltv").is_not_null())

    # Multi-level linking: separate collateral by beneficiary_type, then
    # coalesce direct -> facility -> counterparty so the most specific
    # collateral wins (the allocation kernel's attribute-precedence sibling).
    # The collateral frame is sealed at the loader edge, so the four property
    # columns always exist; ``is_income_producing`` is loader-defaulted
    # (schema default False), so no null fill needed. NOTE the preserved
    # LTV-copy drift: the direct filter is ``["exposure", "loan"]`` with no
    # otherwise — contingent-beneficiary collateral is silently excluded here
    # (unlike the property-coverage copy's unknown->direct fallback).
    attributes = (
        ("ltv", pl.col("property_ltv")),
        ("property_type", pl.col("property_type")),
        ("income_cover", pl.col("is_income_producing")),
        ("qualifying_re", pl.col("is_qualifying_re")),
        ("prior_charge_ltv", pl.col("prior_charge_ltv")),
    )
    direct_ltv = level_attribute_lookup(
        ltv_collateral,
        filter_expr=pl.col("beneficiary_type").str.to_lowercase().is_in(["exposure", "loan"]),
        prefix="direct",
        attributes=attributes,
    )
    facility_ltv = level_attribute_lookup(
        ltv_collateral,
        filter_expr=pl.col("beneficiary_type").str.to_lowercase() == "facility",
        prefix="facility",
        attributes=attributes,
    )
    counterparty_ltv = level_attribute_lookup(
        ltv_collateral,
        filter_expr=pl.col("beneficiary_type").str.to_lowercase() == "counterparty",
        prefix="cp",
        attributes=attributes,
    )

    # Join all three levels onto the exposures frame.
    exposures = (
        exposures.join(
            direct_ltv,
            left_on="exposure_reference",
            right_on="direct_ref",
            how="left",
        )
        .join(
            facility_ltv,
            left_on="parent_facility_reference",
            right_on="facility_ref",
            how="left",
        )
        .join(
            counterparty_ltv,
            left_on="counterparty_reference",
            right_on="cp_ref",
            how="left",
        )
    )

    # Earliest-prefix non-null wins; has_income_cover defaults to False when
    # no level provided a value.
    return coalesce_attribute_levels(
        exposures,
        prefixes=("direct", "facility", "cp"),
        specs=(
            ("ltv", "ltv", NO_DEFAULT),
            ("property_type", "property_type", NO_DEFAULT),
            ("income_cover", "has_income_cover", False),
            ("qualifying_re", "is_qualifying_re", NO_DEFAULT),
            ("prior_charge_ltv", "prior_charge_ltv", NO_DEFAULT),
        ),
    )


def _join_facility_qrre_columns(
    exposures: pl.LazyFrame,
    facilities: pl.LazyFrame,
) -> tuple[pl.LazyFrame, set[str]]:
    """Join facility-side QRRE / limit / termination columns onto exposures.

    Scratch: facility-side QRRE / limit / termination columns join as
    ``_fac_*``, get coalesced into their unprefixed exposure-level
    counterparts (``is_revolving``, ``is_qrre_transactor``, ``facility_limit``,
    ``facility_termination_date``), then dropped via the scratch aliases.
    The facilities frame is sealed at the loader edge, so every source
    column exists and the Boolean ones are non-null.
    """
    # (facility column, scratch alias, exposure-level column, fill-null bool default)
    fac_specs: tuple[tuple[str, str, str, bool], ...] = (
        ("is_revolving", "_fac_revolving", "is_revolving", True),
        ("is_qrre_transactor", "_fac_transactor", "is_qrre_transactor", True),
        ("limit", "_fac_limit", "facility_limit", False),
        (
            "facility_termination_date",
            "_fac_termination_date",
            "facility_termination_date",
            False,
        ),
    )

    fac_select: list[pl.Expr] = [pl.col("facility_reference").alias("_fac_ref")]
    fac_select.extend(pl.col(src_col).alias(alias) for src_col, alias, _, _ in fac_specs)

    exposures = exposures.join(
        facilities.select(fac_select),
        left_on="parent_facility_reference",
        right_on="_fac_ref",
        how="left",
    )

    # Single schema check covers both QRRE coalesce and default columns
    exp_schema = set(exposures.collect_schema().names())
    exposures = exposures.with_columns(
        [
            _build_qrre_coalesce_expr(alias, exp_col, exp_schema, fill_false)
            for _src_col, alias, exp_col, fill_false in fac_specs
        ]
    )

    # Drop temporary join columns
    exposures = exposures.drop([alias for _src_col, alias, _exp_col, _fill in fac_specs])
    return exposures, exp_schema


def _join_property_collateral_multi_level(
    exposures: pl.LazyFrame,
    all_property_collateral: pl.LazyFrame,
    *,
    is_non_qualifying_re: pl.Expr,
) -> pl.LazyFrame:
    """
    Join property collateral at direct/facility/counterparty levels.

    Thin parameterisation of the allocation kernel
    (:func:`rwa_calc.engine.kernels.allocation.allocate_multi_level`),
    preserving the property-coverage copy's drift axes:

    - Basis is drawn-only ``total_exposure_amount`` (CRR Art. 147 "total
      amount owed"), deliberately NOT an EAD basis.
    - Facility / counterparty levels use the IMMEDIATE parent key only — no
      ancestor cascade — with ``.over()`` window weights (guarded by
      ``partition_by_nullable`` inside the kernel against null-partition
      collapse; both keys are nullable in this frame).
    - Null / unknown ``beneficiary_type`` falls back to direct
      (``unknown="direct"``). The kernel classifier routes ``contingent``
      through its explicit direct branch where the legacy hand-rolled chain
      routed it through the ``otherwise`` — same label for every input.

    Args:
        exposures: Exposures with total_exposure_amount column
        all_property_collateral: All property collateral (residential + commercial);
            residential rows are filtered inline via ``filter(is_residential)``
            within the conditional ``group_by`` aggregate.
        is_non_qualifying_re: Per-collateral-row predicate flagging RE that
            fails Art. 124A (``is_qualifying_re == False``); aggregated to a
            per-beneficiary ``re_collateral_non_qualifying`` flag for the
            PRA PS1/26 Art. 124(4) all-or-nothing gate.

    Returns:
        Exposures with residential_collateral_value, property_collateral_value,
        has_facility_property_collateral, and re_collateral_non_qualifying
        columns added
    """
    is_residential = pl.col("property_type").str.to_lowercase() == "residential"

    return allocate_multi_level(
        exposures,
        all_property_collateral,
        values={
            "residential_collateral_value": pl.col("market_value").filter(is_residential).sum(),
            "property_collateral_value": pl.col("market_value").sum(),
        },
        basis=pl.col("total_exposure_amount"),
        level_of=beneficiary_level_expr(unknown="direct"),
        levels=(
            LevelSpec("direct", "exposure_reference", pro_rata=False),
            LevelSpec("facility", "parent_facility_reference", weights="window"),
            LevelSpec("counterparty", "counterparty_reference", weights="window"),
        ),
        any_positive={"has_facility_property_collateral": "property_collateral_value"},
        flag_values={"re_collateral_non_qualifying": is_non_qualifying_re.any()},
    )


def _add_ltv_defaults_for_missing_collateral(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Append null/default LTV columns the caller has not already populated.

    Loan / contingent fixtures may carry exposure-level ``ltv`` /
    ``property_type`` / ``has_income_cover`` / ``is_qualifying_re`` /
    ``prior_charge_ltv`` values (e.g. CRE Art. 126(2)(d) scenarios where the
    LTV and income-cover flags live on the loan rather than a collateral row);
    overwriting them here would silently break the SA real-estate branch
    downstream.
    """
    existing = set(exposures.collect_schema().names())
    # (output column, default expression)
    default_specs: tuple[tuple[str, pl.Expr], ...] = (
        ("ltv", pl.lit(None).cast(pl.Float64).alias("ltv")),
        ("property_type", pl.lit(None).cast(pl.Utf8).alias("property_type")),
        ("has_income_cover", pl.lit(False).alias("has_income_cover")),
        ("is_qualifying_re", pl.lit(None).cast(pl.Boolean).alias("is_qualifying_re")),
        ("prior_charge_ltv", pl.lit(None).cast(pl.Float64).alias("prior_charge_ltv")),
    )
    defaults = [expr for col, expr in default_specs if col not in existing]
    return exposures.with_columns(defaults) if defaults else exposures


def _prepare_short_term_lookup(ratings: pl.LazyFrame | None) -> pl.LazyFrame | None:
    """Filter, sort and materialise the short-term rating lookup.

    Returns ``None`` if no short-term rows are available (i.e. ``ratings`` is
    ``None`` or the filtered set is empty). The caller treats ``None`` as "no
    override applies — set ``has_short_term_ecai=False``".
    """
    if ratings is None:
        return None

    # Filter to candidate short-term rows. Drop rows missing the required
    # scope tuple — loader-side DQ flags those as DQ-RT-ST1 / DQ-RT-ST2
    # errors; here we silently ignore them so the pipeline keeps running.
    # ``is_short_term`` is loader-defaulted to False (Boolean schema default),
    # so no null fill is needed.
    st_ratings = ratings.filter(
        pl.col("is_short_term")
        & pl.col("scope_type").is_not_null()
        & pl.col("scope_id").is_not_null()
        & pl.col("counterparty_reference").is_not_null()
    ).select(
        [
            pl.col("counterparty_reference").alias("_st_cp"),
            pl.col("scope_type").alias("_st_scope_type"),
            pl.col("scope_id").alias("_st_scope_id"),
            pl.col("cqs").alias("_st_cqs"),
            pl.col("rating_date").alias("_st_rating_date"),
        ]
    )

    # Per-scope best-rating selection: lowest CQS, then latest date.
    st_ratings = (
        st_ratings.sort(
            ["_st_cqs", "_st_rating_date"],
            descending=[False, True],
            nulls_last=True,
        )
        .group_by(["_st_cp", "_st_scope_type", "_st_scope_id"])
        .first()
    )

    # Materialise the small short-term lookup eagerly so the three scope-
    # specific joins below can re-use it without re-evaluating the sort.
    st_ratings_df = st_ratings.collect()
    if st_ratings_df.height == 0:
        return None
    return st_ratings_df.lazy()


def _build_short_term_match_branches(exp_schema: set[str]) -> list[tuple[str, pl.Expr]]:
    """Build ``(scope_type, key_expression)`` pairs for each available scope.

    An exposure can satisfy multiple scope_types simultaneously (e.g. a loan
    exposure also inherits its parent facility's short-term rating); the
    caller left-joins each branch and coalesces in priority order so the most
    specific scope wins (loan > contingent > facility).
    """
    match_branches: list[tuple[str, pl.Expr]] = []
    # facility scope: any exposure whose parent or root facility id matches
    has_parent = "parent_facility_reference" in exp_schema
    has_root = "root_facility_reference" in exp_schema
    if has_parent or has_root:
        facility_key_expr = pl.coalesce(
            [
                pl.col("parent_facility_reference")
                if has_parent
                else pl.lit(None, dtype=pl.String),
                pl.col("root_facility_reference") if has_root else pl.lit(None, dtype=pl.String),
            ]
        )
        match_branches.append(("facility", facility_key_expr))
    # loan / contingent scope: match by exposure_reference + exposure_type
    if "exposure_type" in exp_schema and "exposure_reference" in exp_schema:
        match_branches.append(
            (
                "loan",
                pl.when(pl.col("exposure_type") == "loan")
                .then(pl.col("exposure_reference"))
                .otherwise(pl.lit(None, dtype=pl.String)),
            )
        )
        match_branches.append(
            (
                "contingent",
                pl.when(pl.col("exposure_type") == "contingent")
                .then(pl.col("exposure_reference"))
                .otherwise(pl.lit(None, dtype=pl.String)),
            )
        )
    return match_branches


@cites("CRR Art. 131")
def _apply_obligor_short_term_spillover(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Spill a less-favourable short-term ECAI assessment across the obligor.

    CRR Art. 131(2) / PRA PS1/26 Art. 120(3)(c): when an obligor carries a
    short-term issue-specific ECAI assessment (Table 4A / Table 7) that maps to
    a LESS favourable (higher) risk weight than that obligor's general
    preferential short-term treatment (Table 4), the general preferential
    treatment is disapplied and ALL of that obligor's unrated SHORT-TERM claims
    take the short-term assessment's cqs — not just the directly-rated
    exposure. The spillover is bounded to the short-term maturity window;
    long-term claims on the same obligor are unaffected.

    Reads two scratch columns produced by ``apply_short_term_rating_override``:
    ``_st_assessment_cqs`` (the matched short-term cqs, non-null only on the
    directly-rated exposure) and ``_general_cqs`` (the obligor's pre-override
    counterparty cqs).

    The "less favourable" test is a CQS-band comparison mirroring the Table 4
    vs Table 4A / Table 7 structure, so no risk-weight scalars are duplicated in
    the hierarchy stage. Table 4 (general preferential) assigns 20% to CQS 1-3,
    50% to CQS 4-5 and 150% to CQS 6; Table 4A / Table 7 (short-term assessment)
    assign 20%/50%/100%/150% to CQS 1/2/3/4+. Hence the assessment is worse iff:

    - general cqs 1-3 (Table 4 20%):  assessment cqs >= 2
    - general cqs 4-5 (Table 4 50%):  assessment cqs >= 3
    - general cqs 6   (Table 4 150%): never

    Both short-term tables are identical across CRR and Basel 3.1 over this cqs
    range, so the gate is regime-independent.
    """
    schema = set(exposures.collect_schema().names())
    required = {
        "counterparty_reference",
        "has_short_term_ecai",
        "_st_assessment_cqs",
        "_general_cqs",
        "value_date",
        "maturity_date",
        "cqs",
    }
    if not required <= schema:
        return exposures

    # Short-term maturity window: original maturity <= 3m (<= 6m for self-
    # liquidating trade-finance LCs). Derived from (maturity - value) dates,
    # mirroring the SA-stage derivation of ``original_maturity_years``. Missing
    # dates fall back to "not short-term" (conservative — no contamination of
    # long-term or unknown-maturity claims).
    original_mty = (
        pl.col("maturity_date").cast(pl.Int32) - pl.col("value_date").cast(pl.Int32)
    ).cast(pl.Float64) / 365.0
    is_trade_lc = (
        pl.col("is_short_term_trade_lc").fill_null(False)
        if "is_short_term_trade_lc" in schema
        else pl.lit(False)  # noqa: FBT003
    )
    in_st_window = ((original_mty <= 0.25) | (is_trade_lc & (original_mty <= 0.5))).fill_null(False)

    # Obligor-level aggregates (guarded against null-key partition collapse).
    # ``obligor_st_cqs``: worst (highest) short-term-assessment cqs among the
    # obligor's short-term-window exposures. ``obligor_general_cqs``: the
    # obligor's general preferential cqs.
    st_assessment_cqs = pl.when(pl.col("has_short_term_ecai") & in_st_window).then(
        pl.col("_st_assessment_cqs")
    )
    obligor_st_cqs = partition_by_nullable(
        st_assessment_cqs.max().over("counterparty_reference"),
        "counterparty_reference",
        pl.lit(None, dtype=pl.Int8),
    )
    obligor_general_cqs = partition_by_nullable(
        pl.col("_general_cqs").min().over("counterparty_reference"),
        "counterparty_reference",
        pl.col("_general_cqs"),
    )

    # Art. 120(3)(c) "less favourable" test — see docstring for the band map.
    less_favourable = ((obligor_general_cqs <= 3) & (obligor_st_cqs >= 2)) | (
        (obligor_general_cqs >= 4) & (obligor_general_cqs <= 5) & (obligor_st_cqs >= 3)
    )
    fires = obligor_st_cqs.is_not_null() & less_favourable.fill_null(False)

    # Spill onto the obligor's unrated short-term claims only. Directly-rated
    # exposures already carry has_short_term_ecai=True and their own cqs, so are
    # excluded via ``~has_short_term_ecai``.
    spill = fires & in_st_window & ~pl.col("has_short_term_ecai")
    return exposures.with_columns(
        [
            (pl.col("has_short_term_ecai") | spill).alias("has_short_term_ecai"),
            pl.when(spill).then(obligor_st_cqs).otherwise(pl.col("cqs")).cast(pl.Int8).alias("cqs"),
        ]
    )


@cites("CRR Art. 140")
@cites("PS1/26, paragraph 140")
def _apply_obligor_st_contamination_flags(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Flag obligor-level short-term rating contamination (Art. 140(2)).

    CRR Art. 140(2) / PRA PS1/26 Art. 140(2) (CRE21.17-18): a short-term ECAI
    assessment on ANY of an obligor's facilities contaminates that obligor's
    unrated UNSECURED exposures:

    - (a) an assessment attracting 150% (Table 7 CQS 4+) broadcasts 150% to ALL
      the obligor's unrated unsecured claims — short- OR long-term;
    - (b) an assessment attracting 50% (Table 7 CQS 2) floors the obligor's
      unrated SHORT-TERM unsecured claims at 100%.

    Emits two obligor-broadcast Boolean flags read by the SA risk-weight
    override (engine/sa/risk_weights.py). Reads the pristine ``_st_assessment_cqs``
    scratch (non-null only on the directly-rated exposure) BEFORE it is dropped —
    a spilled row carries a null assessment cqs and so never contributes. This is
    a DISTINCT mechanism from the Art. 120(3)(c) short-term spillover above, which
    modifies ``has_short_term_ecai`` / ``cqs``; this helper touches neither.
    Regime-independent (Table 7 is identical across CRR and Basel 3.1), mirroring
    ``_apply_obligor_short_term_spillover``. Called immediately after that
    spillover in ``apply_short_term_rating_override``, where the three inputs
    (``counterparty_reference`` / ``has_short_term_ecai`` / ``_st_assessment_cqs``)
    are already materialised, so no presence guard is needed.
    """
    # The directly-rated ST facility's assessment cqs drives the obligor flags;
    # ``_st_assessment_cqs`` is non-null only there (a spilled row's is null and
    # drops out of the ``.max()``). Table 7: CQS 4+ -> 150%, CQS 2 -> 50%.
    st_150 = pl.col("has_short_term_ecai") & (pl.col("_st_assessment_cqs") >= 4)
    st_50 = pl.col("has_short_term_ecai") & (pl.col("_st_assessment_cqs") == 2)
    return exposures.with_columns(
        [
            partition_by_nullable(
                st_150.max().over("counterparty_reference"),
                "counterparty_reference",
                pl.lit(False),  # noqa: FBT003
            ).alias("obligor_st_150_contamination"),
            partition_by_nullable(
                st_50.max().over("counterparty_reference"),
                "counterparty_reference",
                pl.lit(False),  # noqa: FBT003
            ).alias("obligor_st_50_floor"),
        ]
    )


def _build_qrre_coalesce_expr(
    alias: str,
    exp_col: str,
    exp_schema: set[str],
    fill_false: bool,
) -> pl.Expr:
    """Build the coalesce / fallback expression for one QRRE column.

    When ``exp_col`` already exists on the exposures frame, coalesce its value
    with the joined ``alias`` scratch column; otherwise project the scratch
    column directly. ``fill_false=True`` applies ``fill_null(False)`` so the
    output column is non-null boolean.
    """
    expr = pl.coalesce(pl.col(exp_col), pl.col(alias)) if exp_col in exp_schema else pl.col(alias)
    if fill_false:
        expr = expr.fill_null(False)
    return expr.alias(exp_col)


def _apply_qrre_defaults(exposures: pl.LazyFrame, qrre_schema: set[str]) -> pl.LazyFrame:
    """Ensure ``is_revolving``, ``is_qrre_transactor`` and ``facility_limit`` exist."""
    default_specs: tuple[tuple[str, pl.Expr], ...] = (
        ("is_revolving", pl.lit(False).alias("is_revolving")),
        ("is_qrre_transactor", pl.lit(False).alias("is_qrre_transactor")),
        ("facility_limit", pl.lit(None).cast(pl.Float64).alias("facility_limit")),
    )
    default_cols = [expr for col, expr in default_specs if col not in qrre_schema]
    if default_cols:
        exposures = exposures.with_columns(default_cols)
    return exposures


def _broadcast_trade_lc_flag(
    exposures: pl.LazyFrame,
    facilities: pl.LazyFrame,
) -> pl.LazyFrame:
    """OR-aggregate ``is_short_term_trade_lc`` per counterparty and broadcast.

    Coalesces with any explicit per-row value already on the exposures frame
    (e.g. synthetic facility_undrawn rows carrying the flag from their source
    facility) and only fills nulls from the counterparty-level OR.
    """
    cp_trade_lc = facilities.group_by("counterparty_reference").agg(
        pl.col("is_short_term_trade_lc").any().alias("_cp_trade_lc")
    )
    exposures = exposures.join(
        cp_trade_lc,
        on="counterparty_reference",
        how="left",
    )
    if "is_short_term_trade_lc" in exposures.collect_schema().names():
        exposures = exposures.with_columns(
            pl.coalesce(
                pl.col("is_short_term_trade_lc"),
                pl.col("_cp_trade_lc"),
            )
            .fill_null(False)
            .alias("is_short_term_trade_lc")
        )
    else:
        exposures = exposures.with_columns(
            pl.col("_cp_trade_lc").fill_null(False).alias("is_short_term_trade_lc")
        )
    return exposures.drop("_cp_trade_lc")
