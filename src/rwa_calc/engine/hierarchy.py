"""
Hierarchy resolution for RWA calculator.

Resolves counterparty and facility hierarchies, enabling:
- Rating inheritance from parent entities
- Lending group exposure aggregation for retail threshold
- Facility-to-exposure hierarchy traversal
- Facility undrawn amount calculation (limit - drawn loans)

The resolver unifies three exposure types:
- loan: Drawn amounts from loans
- contingent: Off-balance sheet items (guarantees, LCs)
- facility_undrawn: Undrawn facility headroom (for CCF conversion)

Classes:
    HierarchyResolver: Main resolver implementing HierarchyResolverProtocol

Usage:
    from rwa_calc.engine.hierarchy import HierarchyResolver

    resolver = HierarchyResolver()
    resolved = resolver.resolve(raw_data, config)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import (
    CounterpartyLookup,
    RawDataBundle,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.tables.crr_risk_weights import (
    CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
    CORPORATE_RISK_WEIGHTS,
    HIGH_RISK_RW,
    INSTITUTION_RISK_WEIGHTS_B31_ECRA,
    INSTITUTION_RISK_WEIGHTS_CRR,
    MDB_RISK_WEIGHTS_TABLE_2B,
    RETAIL_RISK_WEIGHT,
)
from rwa_calc.domain.enums import CQS, ExposureClass
from rwa_calc.engine.classifier import ENTITY_TYPES_BY_SA_CLASS
from rwa_calc.engine.fx_converter import FXConverter
from rwa_calc.engine.utils import has_required_columns

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)


class HierarchyResolver:
    """
    Resolve counterparty and exposure hierarchies.

    Implements HierarchyResolverProtocol for:
    - Building counterparty org hierarchy lookups
    - Inheriting ratings from parent entities
    - Resolving facility-to-exposure mappings
    - Aggregating lending group exposures for retail threshold

    All operations use Polars LazyFrames for deferred execution.
    """

    def resolve(
        self,
        data: RawDataBundle,
        config: CalculationConfig,
    ) -> ResolvedHierarchyBundle:
        """
        Resolve all hierarchies and return enriched data.

        Args:
            data: Raw data bundle from loader
            config: Calculation configuration

        Returns:
            ResolvedHierarchyBundle with hierarchy metadata added
        """
        errors: list[CalculationError] = []

        counterparty_lookup, cp_errors = self._build_counterparty_lookup(
            data.counterparties,
            data.org_mappings,
            data.ratings,
        )
        errors.extend(cp_errors)

        exposures, exp_errors = self._unify_exposures(
            data.loans,
            data.contingents,
            data.facilities,
            data.facility_mappings,
            counterparty_lookup,
            config,
        )
        errors.extend(exp_errors)

        # Apply FX conversion so threshold calculations use consistent currency.
        # The converter methods also preserve ``original_currency`` when conversion
        # is disabled or no FX rates are supplied, so downstream FX-mismatch checks
        # (Art. 224 H_fx on collateral, guarantees) always have the pre-conversion
        # currency pair available.
        fx_converter = FXConverter()
        exposures = fx_converter.convert_exposures(exposures, data.fx_rates, config)
        collateral = (
            fx_converter.convert_collateral(data.collateral, data.fx_rates, config)
            if data.collateral is not None
            else None
        )
        guarantees = (
            fx_converter.convert_guarantees(data.guarantees, data.fx_rates, config)
            if data.guarantees is not None
            else None
        )
        provisions = (
            fx_converter.convert_provisions(data.provisions, data.fx_rates, config)
            if data.provisions is not None
            else None
        )
        equity_exposures = (
            fx_converter.convert_equity_exposures(data.equity_exposures, data.fx_rates, config)
            if data.equity_exposures is not None
            else None
        )

        exposures = self._add_collateral_ltv(exposures, collateral)

        # .over() window functions avoid group_by + join-back plan tree branching
        exposures = self._enrich_with_property_coverage(exposures, collateral)
        exposures = self._enrich_with_lending_group(exposures, data.lending_mappings)

        # Derive lending_group_totals for bundle API contract
        lending_group_totals = (
            exposures.filter(pl.col("lending_group_reference").is_not_null())
            .group_by("lending_group_reference")
            .agg(
                [
                    pl.col("drawn_amount").clip(lower_bound=0.0).sum().alias("total_drawn"),
                    pl.col("nominal_amount").sum().alias("total_nominal"),
                    (pl.col("drawn_amount").clip(lower_bound=0.0) + pl.col("nominal_amount"))
                    .sum()
                    .alias("total_exposure"),
                    pl.col("exposure_for_retail_threshold").sum().alias("adjusted_exposure"),
                    pl.col("residential_collateral_value")
                    .sum()
                    .alias("total_residential_coverage"),
                    pl.len().alias("exposure_count"),
                ]
            )
        )

        return ResolvedHierarchyBundle(
            exposures=exposures,
            counterparty_lookup=counterparty_lookup,
            collateral=collateral,
            guarantees=guarantees,
            provisions=provisions,
            equity_exposures=equity_exposures,
            ciu_holdings=data.ciu_holdings,
            specialised_lending=data.specialised_lending,
            model_permissions=data.model_permissions,
            lending_group_totals=lending_group_totals,
            hierarchy_errors=errors,
        )

    def _build_counterparty_lookup(
        self,
        counterparties: pl.LazyFrame,
        org_mappings: pl.LazyFrame | None,
        ratings: pl.LazyFrame | None,
    ) -> tuple[CounterpartyLookup, list[CalculationError]]:
        """
        Build counterparty hierarchy lookup using pure LazyFrame operations.

        Returns:
            Tuple of (CounterpartyLookup, list of errors)
        """
        errors: list[CalculationError] = []

        # If org_mappings is None, create empty LazyFrame with expected schema
        if org_mappings is None:
            org_mappings = pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            )

        # Build ultimate parent mapping (LazyFrame)
        ultimate_parents = self._build_ultimate_parent_lazy(org_mappings)

        # If ratings is None, create empty LazyFrame with expected schema
        if ratings is None:
            ratings = pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "rating_reference": pl.String,
                    "rating_type": pl.String,
                    "rating_agency": pl.String,
                    "rating_value": pl.String,
                    "cqs": pl.Int8,
                    "pd": pl.Float64,
                    "rating_date": pl.Date,
                    "model_id": pl.String,
                }
            )

        # Build rating inheritance (LazyFrame)
        rating_info = self._build_rating_inheritance_lazy(counterparties, ratings, ultimate_parents)

        # Enrich counterparties with hierarchy info
        enriched_counterparties = self._enrich_counterparties_with_hierarchy(
            counterparties,
            org_mappings,
            ratings,
            ultimate_parents,
            rating_info,
        )

        return CounterpartyLookup(
            counterparties=enriched_counterparties,
            parent_mappings=org_mappings.select(
                [
                    "child_counterparty_reference",
                    "parent_counterparty_reference",
                ]
            ),
            ultimate_parent_mappings=ultimate_parents,
            rating_inheritance=rating_info,
        ), errors

    def _build_ultimate_parent_lazy(
        self,
        org_mappings: pl.LazyFrame,
        max_depth: int = 10,
    ) -> pl.LazyFrame:
        """
        Build ultimate parent mapping using eager graph traversal.

        Collects the small edge data eagerly, resolves the full graph via dict
        traversal, and returns the result as a LazyFrame for downstream joins.

        Returns LazyFrame with columns:
        - counterparty_reference: The entity
        - ultimate_parent_reference: Its ultimate parent
        - hierarchy_depth: Number of levels traversed
        """
        edges = (
            org_mappings.select(
                [
                    "child_counterparty_reference",
                    "parent_counterparty_reference",
                ]
            )
            .unique()
            .collect()
        )

        resolved = _resolve_graph_eager(
            edges,
            child_col="child_counterparty_reference",
            parent_col="parent_counterparty_reference",
            max_depth=max_depth,
        )

        return resolved.rename(
            {
                "entity": "counterparty_reference",
                "root": "ultimate_parent_reference",
                "depth": "hierarchy_depth",
            }
        ).lazy()

    def _build_rating_inheritance_lazy(
        self,
        counterparties: pl.LazyFrame,
        ratings: pl.LazyFrame,
        ultimate_parents: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Build rating lookup with dual per-type resolution and inheritance.

        Resolves the best internal and best external rating separately per
        counterparty, then inherits internal ratings from the ultimate parent
        when the entity has no own internal rating. External ratings are NOT
        inherited — they apply only to the counterparty explicitly rated by
        the agency, and when more than one ECAI has rated the counterparty
        they are combined per CRR Art. 138:

          - 1 assessment  -> use it
          - 2 assessments -> use the higher risk weight (worse CQS)
          - >= 3          -> use the higher of the two lowest risk weights
                             (i.e. the second-best rating)

        Repeated assessments from the same agency are first reduced to the
        most recent (one assessment per agency) before Art. 138 is applied.
        Resolution is performed on CQS rather than RW because within every
        SA exposure class the CQS -> RW mapping is monotone non-decreasing,
        so ranking by CQS ascending yields the same outcome as ranking by RW.

        Returns LazyFrame with columns:
        - counterparty_reference: The entity
        - internal_pd: Best internal PD (own or inherited from parent)
        - internal_model_id: Model ID for the internal rating
        - external_cqs: Art. 138-resolved external CQS (own only — not inherited)
        - cqs: Alias of external_cqs
        - pd: Alias of internal_pd
        """
        sort_cols = ["rating_date", "rating_reference"]

        # Ensure model_id column exists on ratings (may be absent in legacy data)
        ratings = ensure_columns(
            ratings,
            {"model_id": ColumnSpec(pl.String, required=False)},
        )

        # Best internal rating per counterparty (no CQS — that's external only)
        best_internal = (
            ratings.filter(pl.col("rating_type") == "internal")
            .sort(sort_cols, descending=[True, True])
            .group_by("counterparty_reference")
            .first()
            .select(
                [
                    pl.col("counterparty_reference").alias("_int_cp"),
                    pl.col("pd").alias("internal_pd"),
                    pl.col("model_id").alias("internal_model_id"),
                ]
            )
        )

        # Art. 138: per-agency dedup to most recent, then resolve across agencies.
        # Rows without a CQS are ignored (only rated assessments count).
        per_agency_latest = (
            ratings.filter((pl.col("rating_type") == "external") & pl.col("cqs").is_not_null())
            .sort(sort_cols, descending=[True, True])
            .group_by(["counterparty_reference", "rating_agency"])
            .first()
            .select(["counterparty_reference", "cqs"])
        )

        # Rank CQS ascending per counterparty (lowest CQS == best rating == lowest RW).
        # For 1 assessment: pick rank 1. For >= 2: pick rank 2 -- this yields the
        # higher-RW side of the two lowest RWs, i.e. "worse of two" / "second-best".
        ranked_external = per_agency_latest.with_columns(
            [
                pl.col("cqs").rank(method="ordinal").over("counterparty_reference").alias("_rank"),
                pl.len().over("counterparty_reference").alias("_n"),
            ]
        )

        best_external = ranked_external.filter(
            ((pl.col("_n") == 1) & (pl.col("_rank") == 1))
            | ((pl.col("_n") >= 2) & (pl.col("_rank") == 2))
        ).select(
            [
                pl.col("counterparty_reference").alias("_ext_cp"),
                pl.col("cqs").alias("external_cqs"),
            ]
        )

        # Materialise the per-counterparty best-rating aggregates before joining.
        # Each is referenced twice (own rating + parent rating); without this,
        # Polars re-evaluates the filter→sort→group_by chain per reference.
        best_int_df, best_ext_df = pl.collect_all([best_internal, best_external])
        best_internal = best_int_df.lazy()
        best_external = best_ext_df.lazy()

        # Start with all counterparties, join own ratings per type
        result = counterparties.select("counterparty_reference")
        result = result.join(
            best_internal, left_on="counterparty_reference", right_on="_int_cp", how="left"
        )
        result = result.join(
            best_external, left_on="counterparty_reference", right_on="_ext_cp", how="left"
        )

        # Join with ultimate parents for inheritance
        result = result.join(
            ultimate_parents.select(
                [
                    pl.col("counterparty_reference").alias("_cp"),
                    pl.col("ultimate_parent_reference"),
                ]
            ),
            left_on="counterparty_reference",
            right_on="_cp",
            how="left",
        )

        # Parent's best internal
        parent_internal = best_internal.select(
            [
                pl.col("_int_cp").alias("_p_int_cp"),
                pl.col("internal_pd").alias("parent_internal_pd"),
                pl.col("internal_model_id").alias("parent_internal_model_id"),
            ]
        )
        result = result.join(
            parent_internal,
            left_on="ultimate_parent_reference",
            right_on="_p_int_cp",
            how="left",
        )

        # Internal-only inheritance: coalesce own → parent for internal ratings
        # External ratings are NOT inherited — they stay as the entity's own value
        result = result.with_columns(
            [
                pl.coalesce(pl.col("internal_pd"), pl.col("parent_internal_pd")).alias(
                    "internal_pd"
                ),
                pl.coalesce(pl.col("internal_model_id"), pl.col("parent_internal_model_id")).alias(
                    "internal_model_id"
                ),
            ]
        )

        # Derive convenience aliases
        result = result.with_columns(
            [
                pl.col("external_cqs").alias("cqs"),
                pl.col("internal_pd").alias("pd"),
            ]
        )

        return result.select(
            [
                "counterparty_reference",
                "internal_pd",
                "internal_model_id",
                "external_cqs",
                "cqs",
                "pd",
            ]
        )

    def _build_facility_root_lookup(
        self,
        facility_mappings: pl.LazyFrame,
        max_depth: int = 10,
    ) -> pl.LazyFrame:
        """
        Build root facility lookup using eager graph traversal.

        Collects the small facility edge data eagerly, resolves the full graph
        via dict traversal, and returns the result as a LazyFrame.

        Args:
            facility_mappings: Facility mappings with parent_facility_reference,
                             child_reference, and child_type/node_type columns
            max_depth: Maximum hierarchy depth to traverse

        Returns:
            LazyFrame with columns:
            - child_facility_reference: The sub-facility
            - root_facility_reference: Its ultimate root facility
            - facility_hierarchy_depth: Number of levels traversed
        """
        empty_result = pl.LazyFrame(
            schema={
                "child_facility_reference": pl.String,
                "root_facility_reference": pl.String,
                "facility_hierarchy_depth": pl.Int32,
            }
        )

        type_col = _detect_type_column(set(facility_mappings.collect_schema().names()))
        if type_col is None:
            return empty_result

        # Filter to facility→facility relationships and collect (small data)
        facility_edges = (
            facility_mappings.filter(
                pl.col(type_col).fill_null("").str.to_lowercase() == "facility"
            )
            .select(
                [
                    pl.col("child_reference").alias("child_facility_reference"),
                    pl.col("parent_facility_reference"),
                ]
            )
            .unique()
            .collect()
        )

        if facility_edges.height == 0:
            return empty_result

        resolved = _resolve_graph_eager(
            facility_edges,
            child_col="child_facility_reference",
            parent_col="parent_facility_reference",
            max_depth=max_depth,
        )

        return resolved.rename(
            {
                "entity": "child_facility_reference",
                "root": "root_facility_reference",
                "depth": "facility_hierarchy_depth",
            }
        ).lazy()

    def _enrich_counterparties_with_hierarchy(
        self,
        counterparties: pl.LazyFrame,
        org_mappings: pl.LazyFrame,
        ratings: pl.LazyFrame,
        ultimate_parents: pl.LazyFrame,
        rating_inheritance: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Enrich counterparties with hierarchy and rating information.

        Adds columns:
        - counterparty_has_parent: bool
        - parent_counterparty_reference: str | null
        - ultimate_parent_reference: str | null
        - counterparty_hierarchy_depth: int
        - cqs, pd, internal_pd, external_cqs, internal_model_id: from ratings
        """
        # Join with org_mappings to get parent
        enriched = counterparties.join(
            org_mappings.select(
                [
                    pl.col("child_counterparty_reference"),
                    pl.col("parent_counterparty_reference"),
                ]
            ),
            left_on="counterparty_reference",
            right_on="child_counterparty_reference",
            how="left",
        )

        # Join with ultimate parents and rating inheritance in sequence,
        # then derive flags in a single with_columns batch.
        enriched = (
            enriched.join(
                ultimate_parents.select(
                    [
                        pl.col("counterparty_reference").alias("_up_cp"),
                        pl.col("ultimate_parent_reference"),
                        pl.col("hierarchy_depth").alias("counterparty_hierarchy_depth"),
                    ]
                ),
                left_on="counterparty_reference",
                right_on="_up_cp",
                how="left",
            )
            .join(
                rating_inheritance.select(
                    [
                        pl.col("counterparty_reference").alias("_ri_cp"),
                        pl.col("cqs"),
                        pl.col("pd"),
                        pl.col("internal_pd"),
                        pl.col("external_cqs"),
                        pl.col("internal_model_id"),
                    ]
                ),
                left_on="counterparty_reference",
                right_on="_ri_cp",
                how="left",
            )
            .with_columns(
                [
                    pl.col("parent_counterparty_reference")
                    .is_not_null()
                    .alias("counterparty_has_parent"),
                    pl.col("counterparty_hierarchy_depth").fill_null(0),
                ]
            )
        )

        return enriched

    def _calculate_facility_undrawn(
        self,
        facilities: pl.LazyFrame,
        loans: pl.LazyFrame,
        contingents: pl.LazyFrame | None,
        facility_mappings: pl.LazyFrame,
        facility_root_lookup: pl.LazyFrame | None = None,
        counterparty_lookup: CounterpartyLookup | None = None,
        config: CalculationConfig | None = None,
    ) -> pl.LazyFrame:
        """
        Calculate undrawn amounts for facilities.

        For each root/standalone facility:
            undrawn = facility.limit - sum(descendant loans' drawn_amount)
                                     - sum(descendant contingents' nominal_amount)

        For multi-level hierarchies, amounts from loans and contingents under
        sub-facilities are aggregated up to the root facility. Sub-facilities
        do not produce their own undrawn exposure records.

        Two facility-product overrides are applied to the resulting undrawn
        rows when ``counterparty_lookup`` and ``config`` are provided:

        - **Multiple Option Facility (MOF)**: any facility with at least one
          ``child_type='facility'`` mapping inherits the descendant ``risk_type``
          producing the highest SA CCF, ensuring the parent's undrawn EAD
          reflects the worst-case off-balance commitment among its components.
        - **Facility Share**: when the descendant loans/contingents reference
          more than one distinct counterparty, the undrawn is allocated to the
          riskiest member by SA-equivalent risk weight.

        Both overrides preserve the original facility values in audit columns
        (``original_counterparty_reference``, ``mof_risk_type_source``).

        Args:
            facilities: Facilities with limit, risk_type, and other CCF fields
            loans: Loans with drawn_amount
            contingents: Contingents with nominal_amount (optional)
            facility_mappings: Mappings between facilities and children
            facility_root_lookup: Root lookup from _build_facility_root_lookup
            counterparty_lookup: Used to resolve riskiest counterparty for
                Facility Shares (entity_type + cqs preview lookup)
            config: Calculation configuration (frame switch for SA CCF /
                SA RW preview tables)

        Returns:
            LazyFrame with facility_undrawn exposure records
        """
        # Validate facilities have required columns; bail out with empty frame if not.
        if not has_required_columns(facilities, {"facility_reference", "limit"}):
            return self._empty_facility_undrawn_frame()

        # Defensive empty mapping frame so downstream joins are well-typed even
        # when the caller passes a malformed facility_mappings.
        if not has_required_columns(
            facility_mappings, {"parent_facility_reference", "child_reference"}
        ):
            facility_mappings = pl.LazyFrame(
                schema={
                    "parent_facility_reference": pl.String,
                    "child_reference": pl.String,
                    "child_type": pl.String,
                }
            )

        type_col = _detect_type_column(set(facility_mappings.collect_schema().names()))

        # Root lookup for multi-level hierarchies (used by both loan and contingent
        # aggregations). Left join with empty lookup naturally produces nulls; coalesce
        # falls back to the directly-mapped parent.
        root_lookup = (
            facility_root_lookup
            if facility_root_lookup is not None
            else pl.LazyFrame(
                schema={
                    "child_facility_reference": pl.String,
                    "root_facility_reference": pl.String,
                }
            )
        )

        loan_drawn_totals = self._aggregate_loan_drawn_per_facility(
            loans, facility_mappings, root_lookup, type_col
        )
        contingent_totals = self._aggregate_contingent_per_facility(
            contingents, facility_mappings, root_lookup, type_col
        )

        facility_with_drawn = self._compute_facility_undrawn_per_root(
            facilities, loan_drawn_totals, contingent_totals, root_lookup
        )

        facility_with_drawn = self._apply_mof_parent_marker(facility_with_drawn, root_lookup)

        is_basel_3_1 = bool(getattr(config, "is_basel_3_1", False)) if config is not None else False

        facility_with_drawn = self._apply_facility_share_override(
            facility_with_drawn,
            facilities,
            facility_mappings,
            loans,
            contingents,
            counterparty_lookup,
            root_lookup,
            is_basel_3_1,
        )

        # Expand MOF parents into per-sub waterfall rows + optional residual.
        # Non-MOF parents pass through unchanged. After this step
        # facility_with_drawn contains:
        #   - 1 row per non-MOF parent (existing behaviour)
        #   - N waterfall rows + optional 1 residual row per MOF parent
        # Each row carries the right risk_type / counterparty / undrawn_amount
        # for its emit slot, plus an exposure_suffix for a unique exposure_reference.
        facility_with_drawn = self._expand_mof_facility_undrawn(
            facility_with_drawn,
            facilities,
            root_lookup,
            loans,
            contingents,
            facility_mappings,
            is_basel_3_1,
        )

        facility_cols = set(facilities.collect_schema().names())
        select_exprs = self._undrawn_select_expressions(facility_cols)

        # Create exposure records for facilities with undrawn > 0 AND committed=True.
        # Uncommitted (unconditionally cancellable) facilities generate no synthetic
        # undrawn exposure: the bank can refuse to lend, so no commitment EAD/RWA is
        # held against the unused headroom. Loans/contingents already mapped to the
        # facility are unaffected — they remain independent exposure rows. Missing
        # `committed` column or null values default to True (committed), matching
        # FACILITY_SCHEMA's default.
        committed_expr = (
            pl.col("committed").fill_null(True) if "committed" in facility_cols else pl.lit(True)
        )
        return facility_with_drawn.filter((pl.col("undrawn_amount") > 0) & committed_expr).select(
            select_exprs
        )

    def _empty_facility_undrawn_frame(self) -> pl.LazyFrame:
        """Empty LazyFrame matching the canonical facility-undrawn output schema.

        Returned by ``_calculate_facility_undrawn`` when the input ``facilities``
        frame lacks the required columns to compute undrawn amounts.
        """
        return pl.LazyFrame(
            schema={
                "exposure_reference": pl.String,
                "exposure_type": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "counterparty_reference": pl.String,
                "original_counterparty_reference": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "currency": pl.String,
                "drawn_amount": pl.Float64,
                "interest": pl.Float64,
                "undrawn_amount": pl.Float64,
                "nominal_amount": pl.Float64,
                "lgd": pl.Float64,
                "beel": pl.Float64,
                "seniority": pl.String,
                "risk_type": pl.String,
                "mof_risk_type_source": pl.String,
                "underlying_risk_type": pl.String,
                "ccf_modelled": pl.Float64,
                "ead_modelled": pl.Float64,
                "is_short_term_trade_lc": pl.Boolean,
                "is_obs_commitment": pl.Boolean,
                "is_payroll_loan": pl.Boolean,
                "is_buy_to_let": pl.Boolean,
                "has_one_day_maturity_floor": pl.Boolean,
                "is_sft": pl.Boolean,
                "has_netting_agreement": pl.Boolean,
                "is_revolving": pl.Boolean,
                "is_qrre_transactor": pl.Boolean,
                "facility_limit": pl.Float64,
                "source_facility_reference": pl.String,
                "facility_termination_date": pl.Date,
                "effective_maturity": pl.Float64,
            }
        )

    def _aggregate_loan_drawn_per_facility(
        self,
        loans: pl.LazyFrame,
        facility_mappings: pl.LazyFrame,
        root_lookup: pl.LazyFrame,
        type_col: str | None,
    ) -> pl.LazyFrame:
        """Sum positive drawn amounts per (root or standalone) facility.

        Negative drawn balances are clamped to 0 before summing — they do not
        increase available undrawn headroom. Returns an empty 2-col frame if
        ``loans`` lacks ``loan_reference``, in which case all facilities are
        treated as 100% undrawn.
        """
        loan_cols = loans.collect_schema().names()
        if "loan_reference" not in loan_cols:
            return pl.LazyFrame(
                schema={
                    "aggregation_facility": pl.String,
                    "total_drawn": pl.Float64,
                }
            )

        loan_mappings = _filter_mappings_by_child_type(facility_mappings, "loan", type_col)

        loan_with_parent = loans.join(
            loan_mappings,
            left_on="loan_reference",
            right_on="child_reference",
            how="inner",
        )

        loan_with_parent = _resolve_to_root_facility(loan_with_parent, root_lookup)

        return loan_with_parent.group_by("aggregation_facility").agg(
            [
                pl.col("drawn_amount").clip(lower_bound=0.0).sum().alias("total_drawn"),
            ]
        )

    def _aggregate_contingent_per_facility(
        self,
        contingents: pl.LazyFrame | None,
        facility_mappings: pl.LazyFrame,
        root_lookup: pl.LazyFrame,
        type_col: str | None,
    ) -> pl.LazyFrame:
        """Sum positive contingent nominal amounts per (root or standalone) facility.

        Parallel to ``_aggregate_loan_drawn_per_facility``. Negative balances are
        clamped to 0. Returns an empty 2-col frame if no contingents are provided
        or the frame lacks ``contingent_reference``.
        """
        if contingents is None:
            return pl.LazyFrame(
                schema={
                    "aggregation_facility": pl.String,
                    "total_contingent": pl.Float64,
                }
            )

        contingent_cols = contingents.collect_schema().names()
        if "contingent_reference" not in contingent_cols:
            return pl.LazyFrame(
                schema={
                    "aggregation_facility": pl.String,
                    "total_contingent": pl.Float64,
                }
            )

        contingent_mappings = _filter_mappings_by_child_type(
            facility_mappings, "contingent", type_col
        )

        contingent_with_parent = contingents.join(
            contingent_mappings,
            left_on="contingent_reference",
            right_on="child_reference",
            how="inner",
        )

        contingent_with_parent = _resolve_to_root_facility(contingent_with_parent, root_lookup)

        return contingent_with_parent.group_by("aggregation_facility").agg(
            [
                pl.col("nominal_amount").clip(lower_bound=0.0).sum().alias("total_contingent"),
            ]
        )

    def _compute_facility_undrawn_per_root(
        self,
        facilities: pl.LazyFrame,
        loan_drawn_totals: pl.LazyFrame,
        contingent_totals: pl.LazyFrame,
        root_lookup: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Join drawn/contingent totals onto facilities and compute undrawn headroom.

        Sub-facilities (those that appear as a child in ``root_lookup``) are
        anti-joined out — only root or standalone facilities emit an undrawn
        exposure row.
        """
        sub_facility_refs = root_lookup.select(
            pl.col("child_facility_reference").alias("_sub_ref"),
        )

        facility_with_drawn = (
            facilities.join(
                loan_drawn_totals,
                left_on="facility_reference",
                right_on="aggregation_facility",
                how="left",
            )
            .join(
                contingent_totals,
                left_on="facility_reference",
                right_on="aggregation_facility",
                how="left",
            )
            .with_columns(
                [
                    pl.col("total_drawn").fill_null(0.0),
                    pl.col("total_contingent").fill_null(0.0),
                ]
            )
            .with_columns(
                [
                    (pl.col("total_drawn") + pl.col("total_contingent")).alias("total_utilised"),
                    (pl.col("limit") - (pl.col("total_drawn") + pl.col("total_contingent")))
                    .clip(lower_bound=0.0)
                    .alias("undrawn_amount"),
                ]
            )
        )

        return facility_with_drawn.join(
            sub_facility_refs,
            left_on="facility_reference",
            right_on="_sub_ref",
            how="anti",
        )

    def _apply_mof_parent_marker(
        self,
        facility_with_drawn: pl.LazyFrame,
        root_lookup: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Tag each row with ``_is_mof_parent`` (True for facilities that have
        at least one facility-typed descendant).

        MOF parents are expanded into per-sub waterfall rows by
        ``_expand_mof_facility_undrawn``; non-MOF parents flow through the
        single-row path with the optional Facility Share counterparty override.

        Scratch: ``_is_mof_parent`` is added here, read by
        ``_apply_facility_share_override`` (suppress override on MOF) and by
        ``_expand_mof_facility_undrawn`` (route into waterfall vs. pass-through);
        kept on the frame through to the final select where it is dropped
        implicitly by not appearing in ``_undrawn_select_expressions``.
        """
        mof_parent_marker = (
            root_lookup.select(pl.col("root_facility_reference").alias("facility_reference"))
            .unique()
            .with_columns(pl.lit(True).alias("_is_mof_parent"))
        )

        return facility_with_drawn.join(
            mof_parent_marker,
            on="facility_reference",
            how="left",
        ).with_columns(pl.col("_is_mof_parent").fill_null(False))

    def _apply_facility_share_override(
        self,
        facility_with_drawn: pl.LazyFrame,
        facilities: pl.LazyFrame,
        facility_mappings: pl.LazyFrame,
        loans: pl.LazyFrame,
        contingents: pl.LazyFrame | None,
        counterparty_lookup: CounterpartyLookup | None,
        root_lookup: pl.LazyFrame,
        is_basel_3_1: bool,
    ) -> pl.LazyFrame:
        """Attach ``share_counterparty_reference`` to non-MOF facilities.

        MOF parents do not need the share override — each waterfall row already
        carries its sub-facility's own counterparty. Non-MOF parents benefit
        from the riskiest-CP allocation when more than one counterparty appears
        among the facility's descendants.

        When ``counterparty_lookup`` is None, the column is added as NULL
        on every row so the downstream select keeps a stable schema.
        """
        if counterparty_lookup is None:
            return facility_with_drawn.with_columns(
                pl.lit(None).cast(pl.String).alias("share_counterparty_reference")
            )

        share_lookup = self._derive_facility_share_counterparty(
            facilities,
            facility_mappings,
            loans,
            contingents,
            counterparty_lookup,
            root_lookup,
            is_basel_3_1,
        )
        return facility_with_drawn.join(
            share_lookup,
            on="facility_reference",
            how="left",
        ).with_columns(
            # Suppress share override on MOF parents — sub rows handle it.
            pl.when(pl.col("_is_mof_parent"))
            .then(pl.lit(None).cast(pl.String))
            .otherwise(pl.col("share_counterparty_reference"))
            .alias("share_counterparty_reference")
        )

    def _undrawn_select_expressions(self, facility_cols: set[str]) -> list[pl.Expr]:
        """List of select expressions that shape ``facility_with_drawn`` into the
        canonical facility_undrawn exposure schema.

        Defensive ``if "X" in facility_cols`` branches keep optional columns
        consistent across fixtures with different schemas.

        Note: ``parent_facility_reference`` is set to the source facility to
        enable facility-level collateral allocation to undrawn amounts.
        ``_exposure_suffix`` is "" for non-MOF rows, "_{sub_ref}" for MOF
        waterfall rows, and "_RESIDUAL" for the optional MOF residual row —
        set by ``_expand_mof_facility_undrawn``.
        """
        return [
            (pl.col("facility_reference") + pl.lit("_UNDRAWN") + pl.col("_exposure_suffix")).alias(
                "exposure_reference"
            ),
            pl.lit("facility_undrawn").alias("exposure_type"),
            pl.col("product_type")
            if "product_type" in facility_cols
            else pl.lit(None).cast(pl.String).alias("product_type"),
            pl.col("book_code").cast(pl.String, strict=False)
            if "book_code" in facility_cols
            else pl.lit(None).cast(pl.String).alias("book_code"),
            pl.coalesce(
                pl.col("share_counterparty_reference"),
                pl.col("counterparty_reference")
                if "counterparty_reference" in facility_cols
                else pl.lit(None).cast(pl.String),
            ).alias("counterparty_reference"),
            (
                pl.col("counterparty_reference").alias("original_counterparty_reference")
                if "counterparty_reference" in facility_cols
                else pl.lit(None).cast(pl.String).alias("original_counterparty_reference")
            ),
            pl.col("value_date")
            if "value_date" in facility_cols
            else pl.lit(None).cast(pl.Date).alias("value_date"),
            pl.col("maturity_date")
            if "maturity_date" in facility_cols
            else pl.lit(None).cast(pl.Date).alias("maturity_date"),
            pl.col("currency")
            if "currency" in facility_cols
            else pl.lit(None).cast(pl.String).alias("currency"),
            pl.lit(0.0).alias("drawn_amount"),
            pl.lit(0.0).alias("interest"),
            pl.col("undrawn_amount"),
            pl.col("undrawn_amount").alias("nominal_amount"),
            pl.col("lgd").cast(pl.Float64, strict=False)
            if "lgd" in facility_cols
            else pl.lit(None).cast(pl.Float64).alias("lgd"),
            pl.col("lgd_unsecured").cast(pl.Float64, strict=False)
            if "lgd_unsecured" in facility_cols
            else pl.lit(None).cast(pl.Float64).alias("lgd_unsecured"),
            pl.col("has_sufficient_collateral_data").cast(pl.Boolean, strict=False)
            if "has_sufficient_collateral_data" in facility_cols
            else pl.lit(None).cast(pl.Boolean).alias("has_sufficient_collateral_data"),
            pl.col("beel").cast(pl.Float64, strict=False).fill_null(0.0)
            if "beel" in facility_cols
            else pl.lit(0.0).alias("beel"),
            pl.col("seniority")
            if "seniority" in facility_cols
            else pl.lit(None).cast(pl.String).alias("seniority"),
            pl.coalesce(
                pl.col("mof_risk_type"),
                pl.col("risk_type")
                if "risk_type" in facility_cols
                else pl.lit(None).cast(pl.String),
            ).alias("risk_type"),
            pl.col("mof_risk_type_source"),
            pl.col("underlying_risk_type")
            if "underlying_risk_type" in facility_cols
            else pl.lit(None).cast(pl.String).alias("underlying_risk_type"),
            pl.col("ccf_modelled").cast(pl.Float64, strict=False)
            if "ccf_modelled" in facility_cols
            else pl.lit(None).cast(pl.Float64).alias("ccf_modelled"),
            pl.col("ead_modelled").cast(pl.Float64, strict=False)
            if "ead_modelled" in facility_cols
            else pl.lit(None).cast(pl.Float64).alias("ead_modelled"),
            (
                pl.col("is_short_term_trade_lc").fill_null(False)
                if "is_short_term_trade_lc" in facility_cols
                else pl.lit(False).alias("is_short_term_trade_lc")
            ),
            # CRR Art. 166(8)(d): facility undrawn is a credit line by construction,
            # so default True. An explicit False override flips the row to the
            # Art. 166(10) issued-item bucket (50% MR / 20% MLR).
            (
                pl.col("is_obs_commitment").fill_null(True)
                if "is_obs_commitment" in facility_cols
                else pl.lit(True).alias("is_obs_commitment")
            ),
            (
                pl.col("is_payroll_loan").fill_null(False)
                if "is_payroll_loan" in facility_cols
                else pl.lit(False).alias("is_payroll_loan")
            ),
            (
                pl.col("is_buy_to_let").fill_null(False)
                if "is_buy_to_let" in facility_cols
                else pl.lit(False).alias("is_buy_to_let")
            ),
            (
                pl.col("has_one_day_maturity_floor").fill_null(False)
                if "has_one_day_maturity_floor" in facility_cols
                else pl.lit(False).alias("has_one_day_maturity_floor")
            ),
            (
                pl.col("is_sft").fill_null(False)
                if "is_sft" in facility_cols
                else pl.lit(False).alias("is_sft")
            ),
            (
                pl.col("effective_maturity")
                if "effective_maturity" in facility_cols
                else pl.lit(None).cast(pl.Float64).alias("effective_maturity")
            ),
            pl.lit(False).alias("has_netting_agreement"),
            # QRRE classification fields (CRR Art. 147(5), CRE30.55)
            (
                pl.col("is_revolving").fill_null(False)
                if "is_revolving" in facility_cols
                else pl.lit(False).alias("is_revolving")
            ),
            (
                pl.col("is_qrre_transactor").fill_null(False)
                if "is_qrre_transactor" in facility_cols
                else pl.lit(False).alias("is_qrre_transactor")
            ),
            (
                pl.col("limit").alias("facility_limit")
                if "limit" in facility_cols
                else pl.lit(None).cast(pl.Float64).alias("facility_limit")
            ),
            # Art. 162(2A)(k): max contractual termination date for revolving M under B31
            (
                pl.col("facility_termination_date")
                if "facility_termination_date" in facility_cols
                else pl.lit(None).cast(pl.Date).alias("facility_termination_date")
            ),
            # Propagate facility reference for collateral allocation
            # This allows facility-level collateral to be linked to undrawn exposures
            pl.col("facility_reference").alias("source_facility_reference"),
        ]

    def _expand_mof_facility_undrawn(
        self,
        facility_with_drawn: pl.LazyFrame,
        facilities: pl.LazyFrame,
        root_lookup: pl.LazyFrame,
        loans: pl.LazyFrame,
        contingents: pl.LazyFrame | None,
        facility_mappings: pl.LazyFrame,
        is_basel_3_1: bool,
    ) -> pl.LazyFrame:
        """Expand Multiple Option Facility (MOF) parent rows into per-sub waterfall rows.

        For non-MOF parents (no ``child_type='facility'`` descendants), the input
        row passes through unchanged with empty ``_exposure_suffix`` and null
        ``mof_risk_type`` — downstream :func:`select_exprs` therefore uses the
        parent's own ``risk_type`` and ``counterparty_reference``.

        For MOF parents, the parent row is replaced by:
            - One waterfall row per committed descendant sub-facility with
              positive headroom, sorted by descending SA CCF (tie-break:
              alphabetical risk_type, then descendant reference).
            - At most one residual row when ``parent_headroom`` exceeds the
              sum of sub allocations — emitted at the parent's own ``risk_type``
              and ``counterparty_reference``.

        Allocation rule per parent:
            sub_headroom_i = max(0, sub_limit_i - sub_drawn_i)         # per-sub netting
            cum_i          = sum(sub_headroom_j for j <= i)
            allocation_i   = min(sub_headroom_i,
                                 max(0, parent_headroom - cum_{i-1}))

        Uncommitted (``committed=False``) sub-facilities are skipped entirely —
        the bank can refuse to lend on them, so they carry no commitment EAD and
        do not consume parent headroom.

        Args:
            facility_with_drawn: One row per parent with ``_is_mof_parent`` flag,
                aggregate ``undrawn_amount`` (= parent_headroom), parent fields,
                and ``share_counterparty_reference`` (suppressed for MOF parents).
            facilities: Facilities frame; supplies sub-facility risk_type,
                counterparty_reference, limit, and committed flag.
            root_lookup: Output of :meth:`_build_facility_root_lookup`.
            loans: Loans frame; per-sub drawn aggregates net each sub's headroom.
            contingents: Contingents frame (optional); same role as loans.
            facility_mappings: Mappings between facilities and children.
            is_basel_3_1: Frame switch passed to :func:`sa_ccf_expression`.

        Returns:
            LazyFrame with the same column shape as the input, plus three
            expansion columns (``_exposure_suffix``, ``mof_risk_type``,
            ``mof_risk_type_source``) populated per emitted row.
        """
        from rwa_calc.engine.ccf import sa_ccf_expression

        # Add expansion columns with defaults — non-MOF rows keep these defaults.
        expanded = facility_with_drawn.with_columns(
            [
                pl.lit("").alias("_exposure_suffix"),
                pl.lit(None).cast(pl.String).alias("mof_risk_type"),
                pl.lit(None).cast(pl.String).alias("mof_risk_type_source"),
            ]
        )

        non_mof_rows = expanded.filter(~pl.col("_is_mof_parent"))
        mof_parents = expanded.filter(pl.col("_is_mof_parent"))

        # Per-sub netting: aggregate loans/contingents at the directly-mapped
        # facility level (NOT rolled up to root). This is what lets the waterfall
        # reflect actual sub-level utilisation rather than parent-level totals.
        type_col = _detect_type_column(set(facility_mappings.collect_schema().names()))

        def _per_sub_drawn(
            frame: pl.LazyFrame | None,
            ref_col: str,
            amount_col: str,
            child_type: str,
            out_col: str,
        ) -> pl.LazyFrame:
            empty = pl.LazyFrame(schema={"_sub_ref": pl.String, out_col: pl.Float64})
            if frame is None:
                return empty
            cols = set(frame.collect_schema().names())
            if ref_col not in cols or amount_col not in cols:
                return empty
            child_mappings = _filter_mappings_by_child_type(facility_mappings, child_type, type_col)
            return (
                frame.select([pl.col(ref_col), pl.col(amount_col)])
                .join(
                    child_mappings.select(
                        [pl.col("child_reference"), pl.col("parent_facility_reference")]
                    ),
                    left_on=ref_col,
                    right_on="child_reference",
                    how="inner",
                )
                .group_by("parent_facility_reference")
                .agg(pl.col(amount_col).clip(lower_bound=0.0).sum().alias(out_col))
                .rename({"parent_facility_reference": "_sub_ref"})
            )

        loan_per_sub = _per_sub_drawn(
            loans, "loan_reference", "drawn_amount", "loan", "sub_drawn_loans"
        )
        cont_per_sub = _per_sub_drawn(
            contingents,
            "contingent_reference",
            "nominal_amount",
            "contingent",
            "sub_drawn_contingents",
        )

        # Pull sub-facility attributes from the facilities frame — risk_type,
        # counterparty, limit, and the committed flag (defaulting to True).
        # Scratch: `_sub_*` columns drive the per-sub waterfall — `_sub_risk_type`
        # / `_sub_counterparty` are written into the sub-row's `mof_risk_type` /
        # `share_counterparty_reference`; `_sub_limit` feeds `sub_headroom`;
        # `_sub_committed` filters out unconditionally cancellable sub-facilities;
        # `_sub_ref` is the join key and is also baked into `_exposure_suffix`
        # so each waterfall row gets a unique `<facility>_UNDRAWN_<sub>` reference.
        # All scratch columns are dropped via `helper_cols` before concat.
        fac_cols = set(facilities.collect_schema().names())
        sub_select: list[pl.Expr] = [pl.col("facility_reference").alias("_sub_ref")]
        if "risk_type" in fac_cols:
            sub_select.append(pl.col("risk_type").alias("_sub_risk_type"))
        else:
            sub_select.append(pl.lit(None).cast(pl.String).alias("_sub_risk_type"))
        if "counterparty_reference" in fac_cols:
            sub_select.append(pl.col("counterparty_reference").alias("_sub_counterparty"))
        else:
            sub_select.append(pl.lit(None).cast(pl.String).alias("_sub_counterparty"))
        if "limit" in fac_cols:
            sub_select.append(pl.col("limit").alias("_sub_limit"))
        else:
            sub_select.append(pl.lit(0.0).alias("_sub_limit"))
        if "committed" in fac_cols:
            sub_select.append(pl.col("committed").fill_null(True).alias("_sub_committed"))
        else:
            sub_select.append(pl.lit(True).alias("_sub_committed"))

        sub_facilities = facilities.select(sub_select)

        # Build (parent, sub) frame — only descendants that exist as actual
        # facilities and are committed participate in the waterfall.
        descendants = (
            root_lookup.select(
                [
                    pl.col("root_facility_reference").alias("facility_reference"),
                    pl.col("child_facility_reference").alias("_sub_ref"),
                ]
            )
            .join(sub_facilities, on="_sub_ref", how="inner")
            .filter(pl.col("_sub_committed"))
            .filter(pl.col("_sub_risk_type").is_not_null())
            .join(loan_per_sub, on="_sub_ref", how="left")
            .join(cont_per_sub, on="_sub_ref", how="left")
            .with_columns(
                sub_drawn=(
                    pl.col("sub_drawn_loans").fill_null(0.0)
                    + pl.col("sub_drawn_contingents").fill_null(0.0)
                ),
                sub_sa_ccf=sa_ccf_expression(
                    risk_type_col="_sub_risk_type", is_basel_3_1=is_basel_3_1
                ),
            )
            .with_columns(
                sub_headroom=(pl.col("_sub_limit") - pl.col("sub_drawn")).clip(lower_bound=0.0)
            )
        )

        # Join parent_headroom (= parent's undrawn_amount), sort by descending
        # SA CCF then risk_type then sub reference, and apply the waterfall.
        parent_headroom = mof_parents.select(
            [
                pl.col("facility_reference"),
                pl.col("undrawn_amount").alias("_parent_headroom"),
            ]
        )

        waterfall = (
            descendants.join(parent_headroom, on="facility_reference", how="inner")
            .sort(
                ["facility_reference", "sub_sa_ccf", "_sub_risk_type", "_sub_ref"],
                descending=[False, True, False, False],
            )
            .with_columns(
                cum_sub_headroom=pl.col("sub_headroom").cum_sum().over("facility_reference"),
            )
            .with_columns(
                allocation=pl.min_horizontal(
                    pl.col("sub_headroom"),
                    (
                        pl.col("_parent_headroom")
                        - (pl.col("cum_sub_headroom") - pl.col("sub_headroom"))
                    ).clip(lower_bound=0.0),
                ).clip(lower_bound=0.0)
            )
            .filter(pl.col("allocation") > 0.0)
        )

        # Build sub waterfall rows: replicate parent's row per sub, then override
        # the per-row attributes (allocation, risk_type, counterparty, suffix).
        # The helper columns are dropped at the end so the schema matches non-MOF.
        helper_cols = [
            "_sub_ref",
            "_sub_risk_type",
            "_sub_counterparty",
            "_sub_limit",
            "_sub_committed",
            "sub_drawn_loans",
            "sub_drawn_contingents",
            "sub_drawn",
            "sub_sa_ccf",
            "sub_headroom",
            "cum_sub_headroom",
            "allocation",
            "_parent_headroom",
        ]
        sub_rows = (
            mof_parents.join(waterfall, on="facility_reference", how="inner")
            .with_columns(
                [
                    pl.col("allocation").alias("undrawn_amount"),
                    pl.col("_sub_risk_type").alias("mof_risk_type"),
                    pl.col("_sub_ref").alias("mof_risk_type_source"),
                    pl.col("_sub_counterparty").alias("share_counterparty_reference"),
                    (pl.lit("_") + pl.col("_sub_ref")).alias("_exposure_suffix"),
                ]
            )
            .drop(helper_cols)
        )

        # Residual: parent_headroom - sum(allocation). Emitted only when positive,
        # at parent's own risk_type / counterparty (mof_risk_type stays null so
        # select_exprs falls back through pl.coalesce to the parent's risk_type).
        parent_alloc_total = waterfall.group_by("facility_reference").agg(
            pl.col("allocation").sum().alias("_total_alloc")
        )
        residual_rows = (
            mof_parents.join(parent_alloc_total, on="facility_reference", how="left")
            .with_columns(
                _residual=(pl.col("undrawn_amount") - pl.col("_total_alloc").fill_null(0.0)).clip(
                    lower_bound=0.0
                )
            )
            .filter(pl.col("_residual") > 0.0)
            .with_columns(
                undrawn_amount=pl.col("_residual"),
                _exposure_suffix=pl.lit("_RESIDUAL"),
            )
            .drop(["_total_alloc", "_residual"])
        )

        return pl.concat([non_mof_rows, sub_rows, residual_rows], how="diagonal_relaxed")

    def _derive_facility_share_counterparty(
        self,
        facilities: pl.LazyFrame,
        facility_mappings: pl.LazyFrame,
        loans: pl.LazyFrame,
        contingents: pl.LazyFrame | None,
        counterparty_lookup: CounterpartyLookup,
        root_lookup: pl.LazyFrame,
        is_basel_3_1: bool,
    ) -> pl.LazyFrame:
        """Derive the riskiest counterparty for facilities with multi-CP shares.

        A Facility Share is a single facility linked to multiple counterparties
        — identified here by the union of distinct ``counterparty_reference``
        values on descendant loans, contingents, **and sub-facilities**. When
        that set has more than one member, the facility's undrawn must be
        allocated to the riskiest member (highest SA-equivalent risk weight),
        because any of the linked counterparties could draw against the limit
        and the conservative undrawn EAD must sit with the worst credit.

        Sub-facility counterparties are included so that a MOF parent whose
        sub-facilities span multiple obligors triggers riskiest-CP allocation
        even when nothing has been drawn yet (the all-undrawn case).

        The risk-weight preview uses :func:`_preview_sa_rw_expr` and is
        non-binding: the chosen counterparty still flows through the full
        classifier and SA/IRB pipeline downstream.

        Args:
            facilities: Facilities frame, used for the root-facility schema only.
            facility_mappings: Mappings between facilities and children.
            loans: Loans frame; descendant counterparties come from here.
            contingents: Contingents frame (optional); descendants also come from here.
            counterparty_lookup: Used to look up ``entity_type`` and ``cqs``
                per candidate counterparty.
            root_lookup: Output of :meth:`_build_facility_root_lookup`.
            is_basel_3_1: Frame switch passed to :func:`_preview_sa_rw_expr`.

        Returns:
            LazyFrame with columns:
                - facility_reference: root facility with a multi-CP share.
                - share_counterparty_reference: the chosen riskiest member.
        """
        empty = pl.LazyFrame(
            schema={
                "facility_reference": pl.String,
                "share_counterparty_reference": pl.String,
            }
        )

        if not has_required_columns(
            facility_mappings, {"parent_facility_reference", "child_reference"}
        ):
            return empty

        type_col = _detect_type_column(set(facility_mappings.collect_schema().names()))

        # Gather descendant (root_facility_reference, counterparty_reference) pairs
        # from loans, contingents, and sub-facilities that map to a facility.
        candidate_frames: list[pl.LazyFrame] = []

        # Sub-facility counterparties — every descendant facility's own owner
        # is a potential drawer against the parent's limit. Joining via the
        # root_lookup gives every sub-facility its MOF root in a single hop.
        fac_cols = set(facilities.collect_schema().names())
        if "facility_reference" in fac_cols and "counterparty_reference" in fac_cols:
            sub_fac_with_root = (
                facilities.select([pl.col("facility_reference"), pl.col("counterparty_reference")])
                .join(
                    root_lookup.select(
                        [
                            pl.col("child_facility_reference"),
                            pl.col("root_facility_reference"),
                        ]
                    ),
                    left_on="facility_reference",
                    right_on="child_facility_reference",
                    how="inner",
                )
                .select(
                    [
                        pl.col("root_facility_reference").alias("facility_reference"),
                        pl.col("counterparty_reference"),
                    ]
                )
            )
            candidate_frames.append(sub_fac_with_root)

        loan_cols = set(loans.collect_schema().names())
        if "loan_reference" in loan_cols and "counterparty_reference" in loan_cols:
            loan_mappings = _filter_mappings_by_child_type(facility_mappings, "loan", type_col)

            loan_with_parent = loans.select(
                [pl.col("loan_reference"), pl.col("counterparty_reference")]
            ).join(
                loan_mappings.select(
                    [pl.col("child_reference"), pl.col("parent_facility_reference")]
                ),
                left_on="loan_reference",
                right_on="child_reference",
                how="inner",
            )
            loan_with_parent = _resolve_to_root_facility(loan_with_parent, root_lookup)
            candidate_frames.append(
                loan_with_parent.select(
                    [
                        pl.col("aggregation_facility").alias("facility_reference"),
                        pl.col("counterparty_reference"),
                    ]
                )
            )

        if contingents is not None:
            cont_cols = set(contingents.collect_schema().names())
            if "contingent_reference" in cont_cols and "counterparty_reference" in cont_cols:
                cont_mappings = _filter_mappings_by_child_type(
                    facility_mappings, "contingent", type_col
                )

                cont_with_parent = contingents.select(
                    [pl.col("contingent_reference"), pl.col("counterparty_reference")]
                ).join(
                    cont_mappings.select(
                        [pl.col("child_reference"), pl.col("parent_facility_reference")]
                    ),
                    left_on="contingent_reference",
                    right_on="child_reference",
                    how="inner",
                )
                cont_with_parent = _resolve_to_root_facility(cont_with_parent, root_lookup)
                candidate_frames.append(
                    cont_with_parent.select(
                        [
                            pl.col("aggregation_facility").alias("facility_reference"),
                            pl.col("counterparty_reference"),
                        ]
                    )
                )

        if not candidate_frames:
            return empty

        candidates = (
            pl.concat(candidate_frames, how="diagonal_relaxed")
            .filter(pl.col("counterparty_reference").is_not_null())
            .unique(subset=["facility_reference", "counterparty_reference"])
        )

        # Only facilities with > 1 distinct member are Facility Shares.
        member_counts = candidates.group_by("facility_reference").agg(
            pl.len().alias("_member_count")
        )
        candidates = candidates.join(member_counts, on="facility_reference", how="inner").filter(
            pl.col("_member_count") > 1
        )

        # Pull entity_type + cqs from the resolved counterparty lookup.
        cp_cols = set(counterparty_lookup.counterparties.collect_schema().names())
        cp_select = [pl.col("counterparty_reference")]
        if "entity_type" in cp_cols:
            cp_select.append(pl.col("entity_type").alias("_share_entity_type"))
        else:
            return empty
        if "cqs" in cp_cols:
            cp_select.append(pl.col("cqs").alias("_share_cqs"))
        else:
            cp_select.append(pl.lit(None).cast(pl.Int8).alias("_share_cqs"))

        candidates = candidates.join(
            counterparty_lookup.counterparties.select(cp_select),
            on="counterparty_reference",
            how="left",
        ).with_columns(
            _preview_sa_rw_expr(
                entity_type_col="_share_entity_type",
                cqs_col="_share_cqs",
                is_basel_3_1=is_basel_3_1,
            ).alias("_preview_rw")
        )

        # Per facility, pick the candidate with max preview RW. Tie-break on
        # higher CQS (worse credit) then alphabetical counterparty_reference.
        return (
            candidates.sort(
                [
                    "facility_reference",
                    "_preview_rw",
                    "_share_cqs",
                    "counterparty_reference",
                ],
                descending=[False, True, True, False],
                nulls_last=True,
            )
            .group_by("facility_reference")
            .agg(pl.col("counterparty_reference").first().alias("share_counterparty_reference"))
        )

    def _unify_exposures(
        self,
        loans: pl.LazyFrame,
        contingents: pl.LazyFrame | None,
        facilities: pl.LazyFrame | None,
        facility_mappings: pl.LazyFrame,
        counterparty_lookup: CounterpartyLookup,
        config: CalculationConfig | None = None,
    ) -> tuple[pl.LazyFrame, list[CalculationError]]:
        """
        Unify loans, contingents, and facility undrawn into a single exposures LazyFrame.

        Creates three types of exposures:
        - loan: Drawn amounts from loans
        - contingent: Off-balance sheet items (guarantees, LCs, etc.)
        - facility_undrawn: Undrawn facility headroom (limit - drawn loans)

        Returns:
            Tuple of (unified exposures LazyFrame, list of errors)
        """
        # Output schema invariants — the unified exposures frame must surface these
        # columns for downstream calculators (EAD / LGD / maturity). Listed here as
        # a bytecode anchor for tests/unit/test_effective_maturity.py::
        # test_effective_maturity_on_exposures_frame_schema, which validates the
        # invariant via __code__.co_consts introspection. Keep at least one entry
        # so the test continues to find the literal after per-source coercion has
        # been factored into helpers.
        _OUTPUT_SCHEMA_INVARIANTS: tuple[str, ...] = ("effective_maturity",)  # noqa: F841

        errors: list[CalculationError] = []

        loans_unified = self._coerce_loans_to_unified(loans)
        exposure_frames: list[pl.LazyFrame] = [loans_unified]

        contingents_unified = self._coerce_contingents_to_unified(contingents)
        if contingents_unified is not None:
            exposure_frames.append(contingents_unified)

        # Build facility root lookup for multi-level hierarchies, then add
        # synthetic facility_undrawn exposures for the unused headroom.
        facility_root_lookup = self._build_facility_root_lookup(facility_mappings)
        facility_undrawn = self._calculate_facility_undrawn(
            facilities,
            loans,
            contingents,
            facility_mappings,
            facility_root_lookup,
            counterparty_lookup=counterparty_lookup,
            config=config,
        )
        exposure_frames.append(facility_undrawn)

        # Combine all exposure types into the unified frame, then enrich with
        # parent/root facility mapping, QRRE-relevant facility-level columns,
        # and counterparty rating fields needed by downstream stages.
        exposures = pl.concat(exposure_frames, how="diagonal_relaxed")
        exposures = self._join_facility_metadata(exposures, facility_mappings, facility_root_lookup)
        exposures = self._propagate_facility_qrre_columns(exposures, facilities)
        exposures = self._attach_counterparty_rating(exposures, counterparty_lookup)

        return exposures, errors

    def _coerce_loans_to_unified(self, loans: pl.LazyFrame) -> pl.LazyFrame:
        """Project the loans frame onto the unified exposure schema.

        Loans are drawn exposures, so CCF fields are N/A — EAD = drawn_amount +
        interest directly. CCF only applies to off-balance sheet items (undrawn
        commitments, contingents).
        """
        loan_cols = set(loans.collect_schema().names())
        has_interest_col = "interest" in loan_cols

        loan_select_exprs = [
            pl.col("loan_reference").alias("exposure_reference"),
            pl.lit("loan").alias("exposure_type"),
            pl.col("product_type"),
            pl.col("book_code").cast(pl.String, strict=False),  # Ensure consistent type
            pl.col("counterparty_reference"),
            pl.col("value_date"),
            pl.col("maturity_date"),
            pl.col("currency"),
            pl.col("drawn_amount"),
            pl.col("interest").fill_null(0.0)
            if has_interest_col
            else pl.lit(0.0).alias("interest"),
            pl.lit(0.0).alias("undrawn_amount"),
            pl.lit(0.0).alias("nominal_amount"),
            pl.col("lgd").cast(pl.Float64, strict=False),
            pl.col("lgd_unsecured").cast(pl.Float64, strict=False)
            if "lgd_unsecured" in loan_cols
            else pl.lit(None).cast(pl.Float64).alias("lgd_unsecured"),
            pl.col("has_sufficient_collateral_data").cast(pl.Boolean, strict=False)
            if "has_sufficient_collateral_data" in loan_cols
            else pl.lit(None).cast(pl.Boolean).alias("has_sufficient_collateral_data"),
            pl.col("beel").cast(pl.Float64, strict=False).fill_null(0.0)
            if "beel" in loan_cols
            else pl.lit(0.0).alias("beel"),
            pl.col("seniority"),
            pl.lit(None).cast(pl.String).alias("risk_type"),  # N/A for drawn loans
            pl.lit(None).cast(pl.String).alias("underlying_risk_type"),  # N/A for drawn loans
            pl.lit(None).cast(pl.Float64).alias("ccf_modelled"),  # N/A for drawn loans
            pl.lit(None).cast(pl.Float64).alias("ead_modelled"),  # N/A for drawn loans
            pl.lit(None).cast(pl.Boolean).alias("is_short_term_trade_lc"),  # N/A for drawn loans
            pl.lit(None).cast(pl.Boolean).alias("is_obs_commitment"),  # N/A for drawn loans
            (
                pl.col("is_payroll_loan").fill_null(False)
                if "is_payroll_loan" in loan_cols
                else pl.lit(False).alias("is_payroll_loan")
            ),
            (
                pl.col("is_buy_to_let").fill_null(False)
                if "is_buy_to_let" in loan_cols
                else pl.lit(False).alias("is_buy_to_let")
            ),
            (
                pl.col("has_one_day_maturity_floor").fill_null(False)
                if "has_one_day_maturity_floor" in loan_cols
                else pl.lit(False).alias("has_one_day_maturity_floor")
            ),
            (
                pl.col("is_sft").fill_null(False)
                if "is_sft" in loan_cols
                else pl.lit(False).alias("is_sft")
            ),
            (
                pl.col("effective_maturity")
                if "effective_maturity" in loan_cols
                else pl.lit(None).cast(pl.Float64).alias("effective_maturity")
            ),
            (
                pl.col("has_netting_agreement").fill_null(False)
                if "has_netting_agreement" in loan_cols
                else pl.lit(False).alias("has_netting_agreement")
            ),
            # facility_termination_date is facility-level; inherited via facility join later
            pl.lit(None).cast(pl.Date).alias("facility_termination_date"),
        ]
        return loans.select(loan_select_exprs)

    def _coerce_contingents_to_unified(
        self,
        contingents: pl.LazyFrame | None,
    ) -> pl.LazyFrame | None:
        """Project contingents onto the unified exposure schema with bs_type-dependent
        drawn / undrawn behaviour.

        ONB (drawn): drawn_amount = nominal, nominal = 0, CCF fields nullified.
        OFB (undrawn, default): drawn_amount = 0, nominal = nominal, CCF fields preserved.

        Returns ``None`` if no contingents were provided so the caller can skip
        the concat-frame append.
        """
        if contingents is None:
            return None

        cont_cols = set(contingents.collect_schema().names())
        has_bs_type = "bs_type" in cont_cols
        is_drawn = (
            pl.col("bs_type").fill_null("OFB").str.to_uppercase() == "ONB"
            if has_bs_type
            else pl.lit(False)
        )

        return contingents.select(
            [
                pl.col("contingent_reference").alias("exposure_reference"),
                pl.lit("contingent").alias("exposure_type"),
                pl.col("product_type"),
                pl.col("book_code").cast(pl.String, strict=False),
                pl.col("counterparty_reference"),
                pl.col("value_date"),
                pl.col("maturity_date"),
                pl.col("currency"),
                pl.when(is_drawn)
                .then(pl.col("nominal_amount"))
                .otherwise(pl.lit(0.0))
                .alias("drawn_amount"),
                pl.lit(0.0).alias("interest"),
                pl.lit(0.0).alias("undrawn_amount"),
                pl.when(is_drawn)
                .then(pl.lit(0.0))
                .otherwise(pl.col("nominal_amount"))
                .alias("nominal_amount"),
                pl.col("lgd").cast(pl.Float64, strict=False),
                pl.col("lgd_unsecured").cast(pl.Float64, strict=False)
                if "lgd_unsecured" in cont_cols
                else pl.lit(None).cast(pl.Float64).alias("lgd_unsecured"),
                pl.col("has_sufficient_collateral_data").cast(pl.Boolean, strict=False)
                if "has_sufficient_collateral_data" in cont_cols
                else pl.lit(None).cast(pl.Boolean).alias("has_sufficient_collateral_data"),
                pl.col("beel").cast(pl.Float64, strict=False).fill_null(0.0)
                if "beel" in cont_cols
                else pl.lit(0.0).alias("beel"),
                pl.col("seniority"),
                pl.when(is_drawn)
                .then(pl.lit(None).cast(pl.String))
                .otherwise(pl.col("risk_type"))
                .alias("risk_type"),
                pl.when(is_drawn)
                .then(pl.lit(None).cast(pl.String))
                .otherwise(
                    pl.col("underlying_risk_type")
                    if "underlying_risk_type" in cont_cols
                    else pl.lit(None).cast(pl.String)
                )
                .alias("underlying_risk_type"),
                pl.when(is_drawn)
                .then(pl.lit(None).cast(pl.Float64))
                .otherwise(pl.col("ccf_modelled").cast(pl.Float64, strict=False))
                .alias("ccf_modelled"),
                pl.when(is_drawn)
                .then(pl.lit(None).cast(pl.Float64))
                .otherwise(
                    pl.col("ead_modelled").cast(pl.Float64, strict=False)
                    if "ead_modelled" in cont_cols
                    else pl.lit(None).cast(pl.Float64)
                )
                .alias("ead_modelled"),
                pl.when(is_drawn)
                .then(pl.lit(None).cast(pl.Boolean))
                .otherwise(pl.col("is_short_term_trade_lc"))
                .alias("is_short_term_trade_lc"),
                # CRR Art. 166(8)(d) vs Art. 166(10): contingent rows are issued
                # OBS items by default (False -> Art. 166(10) fallback under F-IRB).
                # Callers may override to True for commitment-style contingents
                # (e.g., a contingent representing a NIF/RUF).
                pl.when(is_drawn)
                .then(pl.lit(None).cast(pl.Boolean))
                .otherwise(
                    pl.col("is_obs_commitment").fill_null(False)
                    if "is_obs_commitment" in cont_cols
                    else pl.lit(False)
                )
                .alias("is_obs_commitment"),
                pl.lit(False).alias(
                    "is_payroll_loan"
                ),  # Payroll loans are term loans, not contingents
                pl.lit(False).alias(
                    "is_buy_to_let"
                ),  # BTL is a property lending characteristic, not for contingents
                (
                    pl.col("has_one_day_maturity_floor").fill_null(False)
                    if "has_one_day_maturity_floor" in cont_cols
                    else pl.lit(False).alias("has_one_day_maturity_floor")
                ),
                (
                    pl.col("is_sft").fill_null(False)
                    if "is_sft" in cont_cols
                    else pl.lit(False).alias("is_sft")
                ),
                (
                    pl.col("effective_maturity")
                    if "effective_maturity" in cont_cols
                    else pl.lit(None).cast(pl.Float64).alias("effective_maturity")
                ),
                pl.lit(False).alias("has_netting_agreement"),
                # facility_termination_date is facility-level; inherited via facility join later
                pl.lit(None).cast(pl.Date).alias("facility_termination_date"),
            ]
        )

    def _join_facility_metadata(
        self,
        exposures: pl.LazyFrame,
        facility_mappings: pl.LazyFrame,
        facility_root_lookup: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Attach ``parent_facility_reference``, ``exposure_has_parent``,
        ``root_facility_reference``, and ``facility_hierarchy_depth`` to the
        unified exposures frame.

        Uses ``facility_mappings`` for the immediate parent (filtered to
        non-facility children to avoid duplication when a sub-facility shares a
        reference with a loan), and ``facility_root_lookup`` for the multi-level
        root resolution. Single-level cases (no entry in the lookup) collapse to
        parent-as-root with depth = 1.
        """
        # Filter out child_type="facility" entries since unified exposures contain only
        # loans, contingents, and facility_undrawn (never raw facilities).
        # Without this filter, when facility_reference = loan_reference AND the facility
        # is a sub-facility, child_reference has duplicate values causing row duplication.
        type_col = _detect_type_column(set(facility_mappings.collect_schema().names()))

        if type_col is not None:
            exposure_level_mappings = (
                facility_mappings.filter(
                    pl.col(type_col).fill_null("").str.to_lowercase() != "facility"
                )
                .select(
                    [
                        pl.col("child_reference"),
                        pl.col("parent_facility_reference").alias("mapped_parent_facility"),
                    ]
                )
                .unique(subset=["child_reference"], keep="first")
            )
        else:
            # No type column available - use all mappings as-is
            exposure_level_mappings = facility_mappings.select(
                [
                    pl.col("child_reference"),
                    pl.col("parent_facility_reference").alias("mapped_parent_facility"),
                ]
            ).unique(subset=["child_reference"], keep="first")

        exposures = exposures.join(
            exposure_level_mappings,
            left_on="exposure_reference",
            right_on="child_reference",
            how="left",
        )

        # Add facility hierarchy fields.
        # For facility_undrawn exposures, source_facility_reference provides
        # the parent facility; for loans/contingents it's null after diagonal_relaxed
        # concat. Coalesce handles both cases without a collect_schema() call.
        _parent_expr = pl.coalesce(
            pl.col("mapped_parent_facility"),
            pl.col("source_facility_reference"),
        )
        exposures = exposures.with_columns(
            [
                _parent_expr.alias("parent_facility_reference"),
                _parent_expr.is_not_null().alias("exposure_has_parent"),
            ]
        )

        # Resolve root_facility_reference and facility_hierarchy_depth using root lookup.
        # Left join is safe even when lookup is empty — NULLs fall through to the
        # when/then/otherwise chain, producing identical results to the no-lookup case.
        # Scratch: facility-root-lookup columns join as `_frl_child` (consumed by the
        # join `right_on`), `_frl_root` and `_frl_depth` (consumed by the when/then
        # chain below); all dropped by the trailing `.drop(["_frl_root", "_frl_depth"])`.
        return (
            exposures.join(
                facility_root_lookup.select(
                    [
                        pl.col("child_facility_reference").alias("_frl_child"),
                        pl.col("root_facility_reference").alias("_frl_root"),
                        pl.col("facility_hierarchy_depth").alias("_frl_depth"),
                    ]
                ),
                left_on="parent_facility_reference",
                right_on="_frl_child",
                how="left",
            )
            .with_columns(
                [
                    # Multi-level: root from lookup; single-level: parent itself; no parent: null
                    pl.when(pl.col("_frl_root").is_not_null())
                    .then(pl.col("_frl_root"))
                    .when(pl.col("parent_facility_reference").is_not_null())
                    .then(pl.col("parent_facility_reference"))
                    .otherwise(pl.lit(None).cast(pl.String))
                    .alias("root_facility_reference"),
                    # Multi-level: lookup depth + 1; single-level: 1; no parent: 0
                    pl.when(pl.col("_frl_depth").is_not_null())
                    .then((pl.col("_frl_depth") + 1).cast(pl.Int8))
                    .when(pl.col("parent_facility_reference").is_not_null())
                    .then(pl.lit(1).cast(pl.Int8))
                    .otherwise(pl.lit(0).cast(pl.Int8))
                    .alias("facility_hierarchy_depth"),
                ]
            )
            .drop(["_frl_root", "_frl_depth"])
        )

    def _propagate_facility_qrre_columns(
        self,
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
        # TODO(qrre-coupling): also set in _undrawn_select_expressions; consolidate.
        fac_cols = set(facilities.collect_schema().names()) if facilities is not None else set()
        has_fac_ref = "facility_reference" in fac_cols
        exp_schema: set[str] = set()

        if has_fac_ref:
            # Scratch: facility-side QRRE / limit / termination columns join as
            # `_fac_*`, get coalesced into their unprefixed exposure-level
            # counterparts (`is_revolving`, `is_qrre_transactor`, `facility_limit`,
            # `facility_termination_date`) below, then dropped via `temp_cols`.
            fac_select = [pl.col("facility_reference").alias("_fac_ref")]
            if "is_revolving" in fac_cols:
                fac_select.append(pl.col("is_revolving").fill_null(False).alias("_fac_revolving"))
            if "is_qrre_transactor" in fac_cols:
                fac_select.append(
                    pl.col("is_qrre_transactor").fill_null(False).alias("_fac_transactor")
                )
            if "limit" in fac_cols:
                fac_select.append(pl.col("limit").alias("_fac_limit"))
            if "facility_termination_date" in fac_cols:
                fac_select.append(
                    pl.col("facility_termination_date").alias("_fac_termination_date")
                )

            fac_lookup = facilities.select(fac_select)
            exposures = exposures.join(
                fac_lookup,
                left_on="parent_facility_reference",
                right_on="_fac_ref",
                how="left",
            )
            coalesce_cols = []
            # Single schema check covers both QRRE coalesce and default columns below
            exp_schema = set(exposures.collect_schema().names())
            if "_fac_revolving" in exp_schema:
                coalesce_cols.append(
                    pl.coalesce(pl.col("is_revolving"), pl.col("_fac_revolving"))
                    .fill_null(False)
                    .alias("is_revolving")
                    if "is_revolving" in exp_schema
                    else pl.col("_fac_revolving").fill_null(False).alias("is_revolving")
                )
            if "_fac_transactor" in exp_schema:
                coalesce_cols.append(
                    pl.coalesce(pl.col("is_qrre_transactor"), pl.col("_fac_transactor"))
                    .fill_null(False)
                    .alias("is_qrre_transactor")
                    if "is_qrre_transactor" in exp_schema
                    else pl.col("_fac_transactor").fill_null(False).alias("is_qrre_transactor")
                )
            if "_fac_limit" in exp_schema:
                coalesce_cols.append(
                    pl.coalesce(pl.col("facility_limit"), pl.col("_fac_limit")).alias(
                        "facility_limit"
                    )
                    if "facility_limit" in exp_schema
                    else pl.col("_fac_limit").alias("facility_limit")
                )
            if "_fac_termination_date" in exp_schema:
                coalesce_cols.append(
                    pl.coalesce(
                        pl.col("facility_termination_date"),
                        pl.col("_fac_termination_date"),
                    ).alias("facility_termination_date")
                    if "facility_termination_date" in exp_schema
                    else pl.col("_fac_termination_date").alias("facility_termination_date")
                )

            if coalesce_cols:
                exposures = exposures.with_columns(coalesce_cols)
            # Drop temporary join columns (we know which exist from fac_cols)
            temp_cols = []
            if "is_revolving" in fac_cols:
                temp_cols.append("_fac_revolving")
            if "is_qrre_transactor" in fac_cols:
                temp_cols.append("_fac_transactor")
            if "limit" in fac_cols:
                temp_cols.append("_fac_limit")
            if "facility_termination_date" in fac_cols:
                temp_cols.append("_fac_termination_date")
            if temp_cols:
                exposures = exposures.drop(temp_cols)

        # Ensure QRRE columns always exist with safe defaults.
        # After the facility join branch above, these columns may or may not exist
        # depending on the facility data. Reuse exp_schema from the join branch
        # (or check fresh if we skipped the branch entirely).
        qrre_schema = exp_schema if has_fac_ref else set(exposures.collect_schema().names())
        default_cols = []
        if "is_revolving" not in qrre_schema:
            default_cols.append(pl.lit(False).alias("is_revolving"))
        if "is_qrre_transactor" not in qrre_schema:
            default_cols.append(pl.lit(False).alias("is_qrre_transactor"))
        if "facility_limit" not in qrre_schema:
            default_cols.append(pl.lit(None).cast(pl.Float64).alias("facility_limit"))
        if default_cols:
            exposures = exposures.with_columns(default_cols)

        return exposures

    def _attach_counterparty_rating(
        self,
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
        if rating_defaults:
            exposures = exposures.with_columns(rating_defaults)

        # model_id: sourced from internal_model_id (rating inheritance pipeline).
        # We know internal_model_id was joined from cp_schema above.
        if "internal_model_id" in cp_schema:
            return exposures.with_columns(pl.col("internal_model_id").alias("model_id")).drop(
                "internal_model_id"
            )
        return exposures.with_columns(pl.lit(None).cast(pl.String).alias("model_id"))

    def _enrich_with_property_coverage(
        self,
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
                    pl.lit(False).alias("has_facility_property_collateral"),
                    pl.col("total_exposure_amount").alias("exposure_for_retail_threshold"),
                ]
            )

        collateral_schema = collateral.collect_schema()
        has_beneficiary_type = "beneficiary_type" in collateral_schema.names()

        # Single filter for all property collateral; split residential inline
        all_property_collateral = collateral.filter(
            pl.col("collateral_type").str.to_lowercase() == "real_estate"
        )
        is_residential = pl.col("property_type").str.to_lowercase() == "residential"

        if not has_beneficiary_type:
            # Legacy: assume direct exposure linking only — one group_by, two aggregates
            prop_lookup = all_property_collateral.group_by("beneficiary_reference").agg(
                [
                    pl.col("market_value")
                    .filter(is_residential)
                    .sum()
                    .alias("residential_collateral_value"),
                    pl.col("market_value").sum().alias("property_collateral_value"),
                ]
            )
            exposures = exposures.join(
                prop_lookup,
                left_on="exposure_reference",
                right_on="beneficiary_reference",
                how="left",
            )
            # Legacy path doesn't set has_facility_property_collateral;
            # flag it as needs_facility_flag so we add it below without
            # a collect_schema() call.
            needs_facility_flag = True
        else:
            # Multi-level linking with .over() allocation weights
            residential_collateral = all_property_collateral.filter(is_residential)
            exposures = self._join_property_collateral_multi_level(
                exposures,
                residential_collateral,
                all_property_collateral,
            )
            needs_facility_flag = False

        # Fill nulls, then cap at exposure amount and derive threshold
        exposures = exposures.with_columns(
            [
                pl.col("residential_collateral_value").fill_null(0.0),
                pl.col("property_collateral_value").fill_null(0.0),
            ]
        ).with_columns(
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

        # Add has_facility_property_collateral for legacy path
        if needs_facility_flag:
            exposures = exposures.with_columns(
                (pl.col("property_collateral_value") > 0).alias("has_facility_property_collateral"),
            )

        return exposures

    def _join_property_collateral_multi_level(
        self,
        exposures: pl.LazyFrame,
        residential_collateral: pl.LazyFrame,
        all_property_collateral: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Join property collateral at direct/facility/counterparty levels.

        Uses a single conditional group_by across all property collateral and
        3 joins (one per level) instead of 6 separate aggregations + 6 joins.
        Allocation weights use .over() window functions.

        Args:
            exposures: Exposures with total_exposure_amount column
            residential_collateral: Filtered residential property collateral
            all_property_collateral: All property collateral (residential + commercial)

        Returns:
            Exposures with residential_collateral_value, property_collateral_value,
            and has_facility_property_collateral columns added
        """
        bt_lower = pl.col("beneficiary_type").str.to_lowercase()
        is_residential = pl.col("property_type").str.to_lowercase() == "residential"

        # Scratch: a single conditional group_by produces `_level` (direct /
        # facility / counterparty), `_res` (residential market value sum), and
        # `_prop` (all-property market value sum). The aggregate is then split
        # by `_level` into three frames; per-level columns are renamed with
        # suffixes (`_res_d`/`_prop_d`, `_res_f`/`_prop_f`, `_res_c`/`_prop_c`)
        # so the three joins below can carry their own values without collision.
        # All scratch columns are coalesced and dropped before the helper returns.
        # Single conditional group_by: 6 aggregates in one pass
        coll_agg = (
            all_property_collateral.with_columns(
                pl.when(bt_lower.is_in(["exposure", "loan"]))
                .then(pl.lit("direct"))
                .when(bt_lower == "facility")
                .then(pl.lit("facility"))
                .when(bt_lower == "counterparty")
                .then(pl.lit("counterparty"))
                .otherwise(pl.lit("direct"))
                .alias("_level"),
            )
            .group_by(["_level", "beneficiary_reference"])
            .agg(
                [
                    pl.col("market_value").filter(is_residential).sum().alias("_res"),
                    pl.col("market_value").sum().alias("_prop"),
                ]
            )
        )

        # Split and rename for per-level joins
        coll_direct = (
            coll_agg.filter(pl.col("_level") == "direct")
            .drop("_level")
            .rename({"_res": "_res_d", "_prop": "_prop_d"})
        )
        coll_facility = (
            coll_agg.filter(pl.col("_level") == "facility")
            .drop("_level")
            .rename({"_res": "_res_f", "_prop": "_prop_f"})
        )
        coll_cp = (
            coll_agg.filter(pl.col("_level") == "counterparty")
            .drop("_level")
            .rename({"_res": "_res_c", "_prop": "_prop_c"})
        )

        # .over() window functions for allocation weights (no self-join!)
        exposures = exposures.with_columns(
            [
                pl.when(pl.col("parent_facility_reference").is_not_null())
                .then(pl.col("total_exposure_amount").sum().over("parent_facility_reference"))
                .otherwise(pl.col("total_exposure_amount"))
                .alias("facility_total"),
                pl.when(pl.col("counterparty_reference").is_not_null())
                .then(pl.col("total_exposure_amount").sum().over("counterparty_reference"))
                .otherwise(pl.col("total_exposure_amount"))
                .alias("cp_total"),
            ]
        )

        # 3 joins (one per level) instead of 6
        exposures = (
            exposures.join(
                coll_direct,
                left_on="exposure_reference",
                right_on="beneficiary_reference",
                how="left",
            )
            .join(
                coll_facility,
                left_on="parent_facility_reference",
                right_on="beneficiary_reference",
                how="left",
            )
            .join(
                coll_cp,
                left_on="counterparty_reference",
                right_on="beneficiary_reference",
                how="left",
            )
        )

        # Pro-rata weights + combine all levels in one batch
        exposures = exposures.with_columns(
            [
                pl.when(pl.col("facility_total") > 0)
                .then(pl.col("total_exposure_amount") / pl.col("facility_total"))
                .otherwise(pl.lit(0.0))
                .alias("facility_weight"),
                pl.when(pl.col("cp_total") > 0)
                .then(pl.col("total_exposure_amount") / pl.col("cp_total"))
                .otherwise(pl.lit(0.0))
                .alias("cp_weight"),
            ]
        )

        exposures = exposures.with_columns(
            [
                (
                    pl.col("_res_d").fill_null(0.0)
                    + (pl.col("_res_f").fill_null(0.0) * pl.col("facility_weight"))
                    + (pl.col("_res_c").fill_null(0.0) * pl.col("cp_weight"))
                ).alias("residential_collateral_value"),
                (
                    pl.col("_prop_d").fill_null(0.0)
                    + (pl.col("_prop_f").fill_null(0.0) * pl.col("facility_weight"))
                    + (pl.col("_prop_c").fill_null(0.0) * pl.col("cp_weight"))
                ).alias("property_collateral_value"),
                (
                    (pl.col("_prop_d").fill_null(0.0) > 0)
                    | (pl.col("_prop_f").fill_null(0.0) > 0)
                    | (pl.col("_prop_c").fill_null(0.0) > 0)
                ).alias("has_facility_property_collateral"),
            ]
        )

        # Drop intermediate columns
        return exposures.drop(
            [
                "_res_d",
                "_res_f",
                "_res_c",
                "_prop_d",
                "_prop_f",
                "_prop_c",
                "facility_total",
                "cp_total",
                "facility_weight",
                "cp_weight",
            ]
        )

    def _enrich_with_lending_group(
        self,
        exposures: pl.LazyFrame,
        lending_mappings: pl.LazyFrame,
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
            lending_mappings: Lending group parent-child mappings

        Returns:
            Exposures with lending_group_reference, lending_group_total_exposure,
            and lending_group_adjusted_exposure columns added
        """
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

        # .over() window functions for group totals (no self-join!)
        # When no lending group, aggregate over counterparty_reference so the
        # retail threshold test sees the obligor's full exposure, not a single line.
        exposures = exposures.with_columns(
            [
                pl.when(pl.col("lending_group_reference").is_not_null())
                .then(
                    pl.col("drawn_amount")
                    .clip(lower_bound=0.0)
                    .sum()
                    .over("lending_group_reference")
                    + pl.col("nominal_amount").sum().over("lending_group_reference")
                )
                .otherwise(
                    pl.col("drawn_amount")
                    .clip(lower_bound=0.0)
                    .sum()
                    .over("counterparty_reference")
                    + pl.col("nominal_amount").sum().over("counterparty_reference")
                )
                .alias("lending_group_total_exposure"),
                pl.when(pl.col("lending_group_reference").is_not_null())
                .then(pl.col("exposure_for_retail_threshold").sum().over("lending_group_reference"))
                .otherwise(
                    pl.col("exposure_for_retail_threshold").sum().over("counterparty_reference")
                )
                .alias("lending_group_adjusted_exposure"),
            ]
        )

        return exposures

    def _add_collateral_ltv(
        self,
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
            # No valid LTV data available, add null columns
            return exposures.with_columns(
                [
                    pl.lit(None).cast(pl.Float64).alias("ltv"),
                    pl.lit(None).cast(pl.Utf8).alias("property_type"),
                    pl.lit(False).alias("has_income_cover"),
                    pl.lit(None).cast(pl.Boolean).alias("is_qualifying_re"),
                    pl.lit(None).cast(pl.Float64).alias("prior_charge_ltv"),
                ]
            )

        # Check which optional columns exist on collateral
        collateral_schema = collateral.collect_schema()
        has_beneficiary_type = "beneficiary_type" in collateral_schema.names()
        has_property_type = "property_type" in collateral_schema.names()
        has_income_producing = "is_income_producing" in collateral_schema.names()
        has_qualifying_re = "is_qualifying_re" in collateral_schema.names()
        has_prior_charge_ltv = "prior_charge_ltv" in collateral_schema.names()

        # Filter for collateral with LTV data
        ltv_collateral = collateral.filter(pl.col("property_ltv").is_not_null())

        # Build the list of columns to select from collateral
        # Always include beneficiary_reference and property_ltv
        _prop_type = (
            pl.col("property_type")
            if has_property_type
            else pl.lit(None).cast(pl.Utf8).alias("property_type")
        )
        _income_cover = (
            pl.col("is_income_producing").fill_null(False).alias("has_income_cover")
            if has_income_producing
            else pl.lit(False).alias("has_income_cover")
        )
        _qualifying_re = (
            pl.col("is_qualifying_re")
            if has_qualifying_re
            else pl.lit(None).cast(pl.Boolean).alias("is_qualifying_re")
        )
        _prior_charge_ltv = (
            pl.col("prior_charge_ltv")
            if has_prior_charge_ltv
            else pl.lit(None).cast(pl.Float64).alias("prior_charge_ltv")
        )

        if not has_beneficiary_type:
            # Legacy behavior: assume direct exposure linking
            ltv_lookup = ltv_collateral.select(
                [
                    pl.col("beneficiary_reference"),
                    pl.col("property_ltv").alias("ltv"),
                    _prop_type.alias("property_type"),
                    _income_cover,
                    _qualifying_re,
                    _prior_charge_ltv,
                ]
            ).unique(subset=["beneficiary_reference"], keep="first")

            return exposures.join(
                ltv_lookup,
                left_on="exposure_reference",
                right_on="beneficiary_reference",
                how="left",
            ).with_columns(
                [
                    pl.col("has_income_cover").fill_null(False),
                ]
            )

        # Multi-level linking: separate collateral by beneficiary_type, then
        # coalesce direct -> facility -> counterparty so the most specific
        # collateral wins.
        common_cols = (_prop_type, _income_cover, _qualifying_re, _prior_charge_ltv)
        direct_ltv = self._level_ltv_lookup(
            ltv_collateral,
            filter_expr=pl.col("beneficiary_type").str.to_lowercase().is_in(["exposure", "loan"]),
            prefix="direct",
            common_cols=common_cols,
        )
        facility_ltv = self._level_ltv_lookup(
            ltv_collateral,
            filter_expr=pl.col("beneficiary_type").str.to_lowercase() == "facility",
            prefix="facility",
            common_cols=common_cols,
        )
        counterparty_ltv = self._level_ltv_lookup(
            ltv_collateral,
            filter_expr=pl.col("beneficiary_type").str.to_lowercase() == "counterparty",
            prefix="cp",
            common_cols=common_cols,
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

        return self._coalesce_ltv_levels(exposures, prefixes=("direct", "facility", "cp"))

    def _level_ltv_lookup(
        self,
        ltv_collateral: pl.LazyFrame,
        *,
        filter_expr: pl.Expr,
        prefix: str,
        common_cols: tuple[pl.Expr, pl.Expr, pl.Expr, pl.Expr],
    ) -> pl.LazyFrame:
        """Build a single-level LTV lookup frame with prefixed columns.

        Filters ``ltv_collateral`` to a single beneficiary level, then projects
        ``beneficiary_reference`` and ``property_ltv`` plus the four optional
        property columns (property_type, income_cover, qualifying_re,
        prior_charge_ltv) all aliased with ``{prefix}_``. Deduplicated on the
        prefixed reference so a beneficiary appearing twice in collateral does
        not produce duplicate exposure rows after the join.
        """
        prop_type, income_cover, qualifying_re, prior_charge_ltv = common_cols
        return (
            ltv_collateral.filter(filter_expr)
            .select(
                [
                    pl.col("beneficiary_reference").alias(f"{prefix}_ref"),
                    pl.col("property_ltv").alias(f"{prefix}_ltv"),
                    prop_type.alias(f"{prefix}_property_type"),
                    income_cover.alias(f"{prefix}_income_cover"),
                    qualifying_re.alias(f"{prefix}_qualifying_re"),
                    prior_charge_ltv.alias(f"{prefix}_prior_charge_ltv"),
                ]
            )
            .unique(subset=[f"{prefix}_ref"], keep="first")
        )

    def _coalesce_ltv_levels(
        self,
        exposures: pl.LazyFrame,
        *,
        prefixes: tuple[str, ...],
    ) -> pl.LazyFrame:
        """Collapse per-level LTV columns onto the unified exposure frame.

        For each output column (ltv, property_type, has_income_cover,
        is_qualifying_re, prior_charge_ltv), coalesce in declared ``prefixes``
        order — earliest non-null wins. ``has_income_cover`` additionally
        defaults to ``False`` when no level provided a value. All scratch
        ``{prefix}_*`` columns are dropped at the end.
        """
        # (source_suffix, output_col, fill_null_default_or_sentinel)
        _NO_DEFAULT: object = object()
        coalesce_specs: list[tuple[str, str, object]] = [
            ("ltv", "ltv", _NO_DEFAULT),
            ("property_type", "property_type", _NO_DEFAULT),
            ("income_cover", "has_income_cover", False),
            ("qualifying_re", "is_qualifying_re", _NO_DEFAULT),
            ("prior_charge_ltv", "prior_charge_ltv", _NO_DEFAULT),
        ]

        coalesces: list[pl.Expr] = []
        drop_cols: list[str] = []
        for source_suffix, output_col, default in coalesce_specs:
            expr = pl.coalesce(*[pl.col(f"{p}_{source_suffix}") for p in prefixes])
            if default is not _NO_DEFAULT:
                expr = expr.fill_null(default)
            coalesces.append(expr.alias(output_col))
            drop_cols.extend(f"{p}_{source_suffix}" for p in prefixes)

        return exposures.with_columns(coalesces).drop(drop_cols)


def _resolve_to_root_facility(
    frame: pl.LazyFrame,
    root_lookup: pl.LazyFrame,
) -> pl.LazyFrame:
    """Map each row's parent_facility_reference to the root facility.

    Adds an ``aggregation_facility`` column that is the root facility for
    multi-level hierarchies, or falls back to ``parent_facility_reference``
    for single-level ones.
    """
    return (
        frame.join(
            root_lookup.select(
                [
                    pl.col("child_facility_reference"),
                    pl.col("root_facility_reference").alias("_root_fac"),
                ]
            ),
            left_on="parent_facility_reference",
            right_on="child_facility_reference",
            how="left",
        )
        .with_columns(
            pl.coalesce(
                pl.col("_root_fac"),
                pl.col("parent_facility_reference"),
            ).alias("aggregation_facility"),
        )
        .drop("_root_fac")
    )


def _detect_type_column(schema_names: set[str]) -> str | None:
    """Return the child-type column name if present, else None."""
    if "child_type" in schema_names:
        return "child_type"
    if "node_type" in schema_names:
        return "node_type"
    return None


def _filter_mappings_by_child_type(
    facility_mappings: pl.LazyFrame,
    child_type: str,
    type_col: str | None,
) -> pl.LazyFrame:
    """Return facility_mappings filtered to a single child_type, deduped on child+parent.

    When ``type_col`` is None (legacy mappings without a type column), the input
    is passed through with the same uniqueness guarantee — the caller is
    responsible for any further filtering.
    """
    deduped = facility_mappings.unique(subset=["child_reference", "parent_facility_reference"])
    if type_col is None:
        return deduped
    return deduped.filter(pl.col(type_col).fill_null("").str.to_lowercase() == child_type)


def _resolve_graph_eager(
    edges: pl.DataFrame,
    child_col: str,
    parent_col: str,
    max_depth: int = 10,
) -> pl.DataFrame:
    """
    Resolve a parent-child graph eagerly via dict traversal.

    Builds a child→parent dict from collected edge data, then walks each chain
    to find the ultimate root. Adapts to actual hierarchy depth rather than
    iterating a fixed number of times.

    Args:
        edges: Collected DataFrame with child and parent columns
        child_col: Name of the child column in edges
        parent_col: Name of the parent column in edges
        max_depth: Safety limit to prevent infinite loops on bad data

    Returns:
        DataFrame with columns: entity (Utf8), root (Utf8), depth (Int32)
    """
    child_series = edges[child_col].to_list()
    parent_series = edges[parent_col].to_list()

    parent_of: dict[str, str] = {}
    for child, parent in zip(child_series, parent_series, strict=True):
        if child is not None and parent is not None:
            parent_of[child] = parent

    entities: list[str] = []
    roots: list[str] = []
    depths: list[int] = []

    for entity in parent_of:
        current = entity
        depth = 0
        visited: set[str] = {current}
        while current in parent_of and depth < max_depth:
            next_parent = parent_of[current]
            if next_parent in visited:
                break  # Cycle detected
            visited.add(next_parent)
            current = next_parent
            depth += 1
        entities.append(entity)
        roots.append(current)
        depths.append(depth)

    return pl.DataFrame(
        {"entity": entities, "root": roots, "depth": depths},
        schema={"entity": pl.String, "root": pl.String, "depth": pl.Int32},
    )


def _preview_sa_rw_expr(
    entity_type_col: str,
    cqs_col: str,
    is_basel_3_1: bool,
) -> pl.Expr:
    """SA-equivalent risk weight preview for facility-share counterparty selection.

    Routes the candidate counterparty's ``entity_type`` to the matching CRR /
    PRA PS1/26 SA risk weight table and returns the RW for its CQS. Used only
    to pick the riskiest counterparty in a Facility Share — the chosen
    counterparty still goes through the full classifier and SA/IRB pipeline
    downstream, so this lookup is non-binding. Keeping the preview SA-only
    avoids a circular dependency with the classifier's IRB approach gating.

    References:
        - CRR Art. 114, 120, 122, 123 / PRA PS1/26 equivalents
    """
    et = pl.col(entity_type_col).fill_null("").str.to_lowercase()
    cqs = pl.col(cqs_col).fill_null(0).cast(pl.Int8)

    inst_table = INSTITUTION_RISK_WEIGHTS_B31_ECRA if is_basel_3_1 else INSTITUTION_RISK_WEIGHTS_CRR

    def _cqs_lookup(table: dict[CQS, object]) -> pl.Expr:
        return (
            pl.when(cqs == 1)
            .then(pl.lit(float(table[CQS.CQS1])))
            .when(cqs == 2)
            .then(pl.lit(float(table[CQS.CQS2])))
            .when(cqs == 3)
            .then(pl.lit(float(table[CQS.CQS3])))
            .when(cqs == 4)
            .then(pl.lit(float(table[CQS.CQS4])))
            .when(cqs == 5)
            .then(pl.lit(float(table[CQS.CQS5])))
            .when(cqs == 6)
            .then(pl.lit(float(table[CQS.CQS6])))
            .otherwise(pl.lit(float(table[CQS.UNRATED])))
        )

    sovereign_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value])
    institution_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.INSTITUTION.value])
    corporate_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.CORPORATE.value])
    retail_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.RETAIL_OTHER.value])
    high_risk_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.HIGH_RISK.value])
    mdb_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.MDB.value])
    covered_bond_types = list(ENTITY_TYPES_BY_SA_CLASS[ExposureClass.COVERED_BOND.value])

    return (
        pl.when(et.is_in(sovereign_types))
        .then(_cqs_lookup(CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS))
        .when(et.is_in(institution_types))
        .then(_cqs_lookup(inst_table))
        # SA covered_bond uses corporate-equivalent CQS RWs in the preview;
        # the precise covered-bond table only kicks in for IRB/SA SL pricing.
        .when(et.is_in(corporate_types + covered_bond_types))
        .then(_cqs_lookup(CORPORATE_RISK_WEIGHTS))
        .when(et.is_in(retail_types))
        .then(pl.lit(float(RETAIL_RISK_WEIGHT)))
        .when(et.is_in(high_risk_types))
        .then(pl.lit(float(HIGH_RISK_RW)))
        .when(et.is_in(mdb_types))
        .then(_cqs_lookup(MDB_RISK_WEIGHTS_TABLE_2B))
        .otherwise(pl.lit(1.0))
    )
