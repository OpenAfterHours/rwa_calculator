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

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import (
    CounterpartyLookup,
    RawDataBundle,
    ResolvedHierarchyBundle,
)
from rwa_calc.engine.fx_converter import FXConverter
from rwa_calc.engine.utils import has_required_columns

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


@dataclass
class HierarchyError:
    """Error encountered during hierarchy resolution."""

    error_type: str
    message: str
    entity_reference: str | None = None
    context: dict = field(default_factory=dict)


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
        errors: list[HierarchyError] = []

        # Step 1: Build counterparty hierarchy lookup
        counterparty_lookup, cp_errors = self._build_counterparty_lookup(
            data.counterparties,
            data.org_mappings,
            data.ratings,
        )
        errors.extend(cp_errors)

        # Step 2: Unify exposures (loans + contingents + facility undrawn) with hierarchy metadata
        exposures, exp_errors = self._unify_exposures(
            data.loans,
            data.contingents,
            data.facilities,
            data.facility_mappings,
            counterparty_lookup,
        )
        errors.extend(exp_errors)

        # Step 2a: Apply FX conversion to exposures and CRM data
        # This enables threshold calculations in consistent currency
        fx_converter = FXConverter()
        collateral = data.collateral
        guarantees = data.guarantees
        provisions = data.provisions
        equity_exposures = data.equity_exposures

        if config.apply_fx_conversion and data.fx_rates is not None:
            exposures = fx_converter.convert_exposures(exposures, data.fx_rates, config)
            if collateral is not None:
                collateral = fx_converter.convert_collateral(collateral, data.fx_rates, config)
            if guarantees is not None:
                guarantees = fx_converter.convert_guarantees(guarantees, data.fx_rates, config)
            if provisions is not None:
                provisions = fx_converter.convert_provisions(provisions, data.fx_rates, config)
            if equity_exposures is not None:
                equity_exposures = fx_converter.convert_equity_exposures(equity_exposures, data.fx_rates, config)
        else:
            # Add audit trail columns with null values when no conversion
            exposures = exposures.with_columns([
                pl.col("currency").alias("original_currency"),
                (pl.col("drawn_amount") + pl.col("interest").fill_null(0.0) + pl.col("nominal_amount")).alias("original_amount"),
                pl.lit(None).cast(pl.Float64).alias("fx_rate_applied"),
            ])

        # Step 2b: Add collateral LTV to exposures (for real estate risk weights)
        exposures = self._add_collateral_ltv(exposures, collateral)

        # Step 3: Enrich exposures with property coverage and lending group totals
        # Uses .over() window functions instead of group_by + join-back to avoid
        # duplicating the upstream plan tree (self-join elimination)
        exposures = self._enrich_with_property_coverage(exposures, collateral)
        exposures = self._enrich_with_lending_group(exposures, data.lending_mappings)

        # Derive lending_group_totals for bundle API contract
        lending_group_totals = exposures.filter(
            pl.col("lending_group_reference").is_not_null()
        ).group_by("lending_group_reference").agg([
            pl.col("drawn_amount").clip(lower_bound=0.0).sum().alias("total_drawn"),
            pl.col("nominal_amount").sum().alias("total_nominal"),
            (
                pl.col("drawn_amount").clip(lower_bound=0.0) + pl.col("nominal_amount")
            ).sum().alias("total_exposure"),
            pl.col("exposure_for_retail_threshold").sum().alias("adjusted_exposure"),
            pl.col("residential_collateral_value").sum().alias(
                "total_residential_coverage"
            ),
            pl.len().alias("exposure_count"),
        ])

        return ResolvedHierarchyBundle(
            exposures=exposures,
            counterparty_lookup=counterparty_lookup,
            collateral=collateral,
            guarantees=guarantees,
            provisions=provisions,
            equity_exposures=equity_exposures,
            lending_group_totals=lending_group_totals,
            hierarchy_errors=errors,
        )

    def _build_counterparty_lookup(
        self,
        counterparties: pl.LazyFrame,
        org_mappings: pl.LazyFrame | None,
        ratings: pl.LazyFrame | None,
    ) -> tuple[CounterpartyLookup, list[HierarchyError]]:
        """
        Build counterparty hierarchy lookup using pure LazyFrame operations.

        Returns:
            Tuple of (CounterpartyLookup, list of errors)
        """
        errors: list[HierarchyError] = []

        # If org_mappings is None, create empty LazyFrame with expected schema
        if org_mappings is None:
            org_mappings = pl.LazyFrame(schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            })

        # Build ultimate parent mapping (LazyFrame)
        ultimate_parents = self._build_ultimate_parent_lazy(org_mappings)

        # If ratings is None, create empty LazyFrame with expected schema
        if ratings is None:
            ratings = pl.LazyFrame(schema={
                "counterparty_reference": pl.String,
                "rating_reference": pl.String,
                "rating_type": pl.String,
                "rating_agency": pl.String,
                "rating_value": pl.String,
                "cqs": pl.Int8,
                "pd": pl.Float64,
                "rating_date": pl.Date,
            })

        # Build rating inheritance (LazyFrame)
        rating_info = self._build_rating_inheritance_lazy(
            counterparties, ratings, ultimate_parents
        )

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
            parent_mappings=org_mappings.select([
                "child_counterparty_reference",
                "parent_counterparty_reference",
            ]),
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
        edges = org_mappings.select([
            "child_counterparty_reference",
            "parent_counterparty_reference",
        ]).unique().collect()

        resolved = _resolve_graph_eager(
            edges,
            child_col="child_counterparty_reference",
            parent_col="parent_counterparty_reference",
            max_depth=max_depth,
        )

        return resolved.rename({
            "entity": "counterparty_reference",
            "root": "ultimate_parent_reference",
            "depth": "hierarchy_depth",
        }).lazy()

    def _build_rating_inheritance_lazy(
        self,
        counterparties: pl.LazyFrame,
        ratings: pl.LazyFrame,
        ultimate_parents: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Build rating lookup with inheritance via LazyFrame joins.

        Returns LazyFrame with columns:
        - counterparty_reference: The entity
        - cqs, pd, rating_value, rating_agency, rating_type, rating_date: Rating info
        - inherited: Whether the rating was inherited
        - source_counterparty: Where the rating came from
        - inheritance_reason: own_rating, parent_rating, or unrated
        """
        # Get most recent rating per counterparty (sort by date then reference for consistency)
        first_ratings = (
            ratings
            .sort(["rating_date", "rating_reference"], descending=[True, True])
            .group_by("counterparty_reference")
            .first()
            .select([
                pl.col("counterparty_reference").alias("rated_cp"),
                pl.col("rating_type"),
                pl.col("rating_agency"),
                pl.col("rating_value"),
                pl.col("cqs"),
                pl.col("pd"),
                pl.col("rating_date"),
            ])
        )

        # Start with all counterparties
        result = counterparties.select("counterparty_reference")

        # Join with own ratings
        result = result.join(
            first_ratings,
            left_on="counterparty_reference",
            right_on="rated_cp",
            how="left",
        )

        # Join with ultimate parents
        result = result.join(
            ultimate_parents.select([
                pl.col("counterparty_reference").alias("_cp"),
                pl.col("ultimate_parent_reference"),
            ]),
            left_on="counterparty_reference",
            right_on="_cp",
            how="left",
        )

        # Join to get parent's ratings
        parent_ratings = first_ratings.select([
            pl.col("rated_cp").alias("parent_cp"),
            pl.col("cqs").alias("parent_cqs"),
            pl.col("pd").alias("parent_pd"),
            pl.col("rating_value").alias("parent_rating_value"),
            pl.col("rating_agency").alias("parent_rating_agency"),
            pl.col("rating_type").alias("parent_rating_type"),
            pl.col("rating_date").alias("parent_rating_date"),
        ])

        result = result.join(
            parent_ratings,
            left_on="ultimate_parent_reference",
            right_on="parent_cp",
            how="left",
        )

        # Resolve inheritance with coalesce
        has_own_rating = pl.col("cqs").is_not_null() | pl.col("rating_value").is_not_null()
        has_parent_rating = pl.col("parent_cqs").is_not_null() | pl.col("parent_rating_value").is_not_null()

        result = result.with_columns([
            pl.coalesce(pl.col("cqs"), pl.col("parent_cqs")).alias("cqs"),
            pl.coalesce(pl.col("pd"), pl.col("parent_pd")).alias("pd"),
            pl.coalesce(pl.col("rating_value"), pl.col("parent_rating_value")).alias("rating_value"),
            pl.coalesce(pl.col("rating_agency"), pl.col("parent_rating_agency")).alias("rating_agency"),
            pl.coalesce(pl.col("rating_type"), pl.col("parent_rating_type")).alias("rating_type"),
            pl.coalesce(pl.col("rating_date"), pl.col("parent_rating_date")).alias("rating_date"),

            pl.when(has_own_rating).then(pl.lit(False))
            .when(has_parent_rating).then(pl.lit(True))
            .otherwise(pl.lit(False)).alias("inherited"),

            pl.when(has_own_rating).then(pl.col("counterparty_reference"))
            .when(has_parent_rating).then(pl.col("ultimate_parent_reference"))
            .otherwise(pl.lit(None).cast(pl.String)).alias("source_counterparty"),

            pl.when(has_own_rating).then(pl.lit("own_rating"))
            .when(has_parent_rating).then(pl.lit("parent_rating"))
            .otherwise(pl.lit("unrated")).alias("inheritance_reason"),
        ])

        # Drop intermediate columns
        return result.select([
            "counterparty_reference", "cqs", "pd", "rating_value", "rating_agency",
            "rating_type", "rating_date", "inherited", "source_counterparty", "inheritance_reason",
        ])

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
        empty_result = pl.LazyFrame(schema={
            "child_facility_reference": pl.String,
            "root_facility_reference": pl.String,
            "facility_hierarchy_depth": pl.Int32,
        })

        # Detect type column (child_type / node_type / neither)
        mapping_schema = facility_mappings.collect_schema()
        mapping_cols = set(mapping_schema.names())

        if "child_type" in mapping_cols:
            type_col = "child_type"
        elif "node_type" in mapping_cols:
            type_col = "node_type"
        else:
            return empty_result

        # Filter to facility→facility relationships and collect (small data)
        facility_edges = facility_mappings.filter(
            pl.col(type_col).fill_null("").str.to_lowercase() == "facility"
        ).select([
            pl.col("child_reference").alias("child_facility_reference"),
            pl.col("parent_facility_reference"),
        ]).unique().collect()

        if facility_edges.height == 0:
            return empty_result

        resolved = _resolve_graph_eager(
            facility_edges,
            child_col="child_facility_reference",
            parent_col="parent_facility_reference",
            max_depth=max_depth,
        )

        return resolved.rename({
            "entity": "child_facility_reference",
            "root": "root_facility_reference",
            "depth": "facility_hierarchy_depth",
        }).lazy()

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
        - rating_inherited: bool
        - rating_source_counterparty: str | null
        - rating_inheritance_reason: str
        """
        # Join with org_mappings to get parent
        enriched = counterparties.join(
            org_mappings.select([
                pl.col("child_counterparty_reference"),
                pl.col("parent_counterparty_reference"),
            ]),
            left_on="counterparty_reference",
            right_on="child_counterparty_reference",
            how="left",
        )

        # Join with ultimate parents and rating inheritance in sequence,
        # then derive flags in a single with_columns batch.
        enriched = enriched.join(
            ultimate_parents.select([
                pl.col("counterparty_reference").alias("_up_cp"),
                pl.col("ultimate_parent_reference"),
                pl.col("hierarchy_depth").alias("counterparty_hierarchy_depth"),
            ]),
            left_on="counterparty_reference",
            right_on="_up_cp",
            how="left",
        ).join(
            rating_inheritance.select([
                pl.col("counterparty_reference").alias("_ri_cp"),
                pl.col("cqs"),
                pl.col("pd"),
                pl.col("rating_value"),
                pl.col("rating_agency"),
                pl.col("inherited").alias("rating_inherited"),
                pl.col("source_counterparty").alias("rating_source_counterparty"),
                pl.col("inheritance_reason").alias("rating_inheritance_reason"),
            ]),
            left_on="counterparty_reference",
            right_on="_ri_cp",
            how="left",
        ).with_columns([
            pl.col("parent_counterparty_reference").is_not_null().alias("counterparty_has_parent"),
            pl.col("counterparty_hierarchy_depth").fill_null(0),
        ])

        return enriched

    def _calculate_facility_undrawn(
        self,
        facilities: pl.LazyFrame,
        loans: pl.LazyFrame,
        contingents: pl.LazyFrame | None,
        facility_mappings: pl.LazyFrame,
        facility_root_lookup: pl.LazyFrame | None = None,
    ) -> pl.LazyFrame:
        """
        Calculate undrawn amounts for facilities.

        For each root/standalone facility:
            undrawn = facility.limit - sum(descendant loans' drawn_amount)
                                     - sum(descendant contingents' nominal_amount)

        For multi-level hierarchies, amounts from loans and contingents under
        sub-facilities are aggregated up to the root facility. Sub-facilities
        do not produce their own undrawn exposure records.

        Args:
            facilities: Facilities with limit, risk_type, and other CCF fields
            loans: Loans with drawn_amount
            contingents: Contingents with nominal_amount (optional)
            facility_mappings: Mappings between facilities and children
            facility_root_lookup: Root lookup from _build_facility_root_lookup

        Returns:
            LazyFrame with facility_undrawn exposure records
        """
        # Validate facilities have required columns
        required_cols = {"facility_reference", "limit"}
        if not has_required_columns(facilities, required_cols):
            # No valid facilities, return empty LazyFrame with expected schema
            return pl.LazyFrame(schema={
                "exposure_reference": pl.String,
                "exposure_type": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "counterparty_reference": pl.String,
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
                "ccf_modelled": pl.Float64,
                "is_short_term_trade_lc": pl.Boolean,
                "is_buy_to_let": pl.Boolean,
                "source_facility_reference": pl.String,
            })

        # Check if facility_mappings is valid
        mapping_required_cols = {"parent_facility_reference", "child_reference"}
        if not has_required_columns(facility_mappings, mapping_required_cols):
            facility_mappings = pl.LazyFrame(schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            })

        # Detect type column for filtering mappings (used by both loan and contingent sections)
        mapping_schema = facility_mappings.collect_schema()
        mapping_cols = set(mapping_schema.names())
        if "child_type" in mapping_cols:
            type_col = "child_type"
        elif "node_type" in mapping_cols:
            type_col = "node_type"
        else:
            type_col = None

        # Prepare root lookup for multi-level hierarchies (used by both loan and contingent sections).
        # Left join with empty lookup naturally produces nulls; coalesce falls back to parent.
        root_lookup = (
            facility_root_lookup
            if facility_root_lookup is not None
            else pl.LazyFrame(schema={
                "child_facility_reference": pl.String,
                "root_facility_reference": pl.String,
            })
        )

        # Get loan schema columns to ensure we can join
        loan_schema = loans.collect_schema()
        loan_ref_col = "loan_reference" if "loan_reference" in loan_schema.names() else None

        if loan_ref_col is None:
            # No valid loans, all facilities are 100% undrawn
            loan_drawn_totals = pl.LazyFrame(schema={
                "aggregation_facility": pl.String,
                "total_drawn": pl.Float64,
            })
        else:
            if type_col is not None:
                loan_mappings = facility_mappings.filter(
                    pl.col(type_col).fill_null("").str.to_lowercase() == "loan"
                ).unique(subset=["child_reference", "parent_facility_reference"])
            else:
                loan_mappings = facility_mappings.unique(
                    subset=["child_reference", "parent_facility_reference"]
                )

            # Sum drawn amounts by parent facility
            # Clamp negative drawn amounts to 0 before summing - negative balances
            # should not increase available undrawn headroom
            loan_with_parent = loans.join(
                loan_mappings,
                left_on="loan_reference",
                right_on="child_reference",
                how="inner",
            )

            # For multi-level hierarchies, map each loan's drawn amount to the ROOT facility.
            loan_with_parent = loan_with_parent.join(
                root_lookup.select([
                    pl.col("child_facility_reference"),
                    pl.col("root_facility_reference").alias("_root_fac"),
                ]),
                left_on="parent_facility_reference",
                right_on="child_facility_reference",
                how="left",
            ).with_columns([
                pl.coalesce(
                    pl.col("_root_fac"),
                    pl.col("parent_facility_reference"),
                ).alias("aggregation_facility"),
            ]).drop("_root_fac")

            loan_drawn_totals = loan_with_parent.group_by("aggregation_facility").agg([
                pl.col("drawn_amount").clip(lower_bound=0.0).sum().alias("total_drawn"),
            ])

        # Calculate contingent utilisation (parallel to loan drawn totals)
        contingent_ref_col = None
        if contingents is not None:
            cont_schema = contingents.collect_schema()
            if "contingent_reference" in cont_schema.names():
                contingent_ref_col = "contingent_reference"

        if contingent_ref_col is None:
            contingent_totals = pl.LazyFrame(schema={
                "aggregation_facility": pl.String,
                "total_contingent": pl.Float64,
            })
        else:
            # Filter mappings to only contingent children
            if type_col is not None:
                contingent_mappings = facility_mappings.filter(
                    pl.col(type_col).fill_null("").str.to_lowercase() == "contingent"
                ).unique(subset=["child_reference", "parent_facility_reference"])
            else:
                contingent_mappings = facility_mappings.unique(
                    subset=["child_reference", "parent_facility_reference"]
                )

            # Join contingents with their parent facility
            contingent_with_parent = contingents.join(
                contingent_mappings,
                left_on="contingent_reference",
                right_on="child_reference",
                how="inner",
            )

            # For multi-level hierarchies, map to root facility.
            # Reuse root_lookup from loan section (already handles None case).
            contingent_with_parent = contingent_with_parent.join(
                root_lookup.select([
                    pl.col("child_facility_reference"),
                    pl.col("root_facility_reference").alias("_root_fac"),
                ]),
                left_on="parent_facility_reference",
                right_on="child_facility_reference",
                how="left",
            ).with_columns([
                pl.coalesce(
                    pl.col("_root_fac"),
                    pl.col("parent_facility_reference"),
                ).alias("aggregation_facility"),
            ]).drop("_root_fac")

            contingent_totals = contingent_with_parent.group_by("aggregation_facility").agg([
                pl.col("nominal_amount").clip(lower_bound=0.0).sum().alias("total_contingent"),
            ])

        # Identify sub-facilities to exclude from output
        # Sub-facilities appear as child_reference with child_type="facility"
        # Anti-join with empty frame naturally returns all rows
        sub_facility_refs = root_lookup.select(
            pl.col("child_facility_reference").alias("_sub_ref"),
        )

        # Join with facilities to calculate undrawn
        # Combine loan drawn + contingent utilisation
        facility_with_drawn = facilities.join(
            loan_drawn_totals,
            left_on="facility_reference",
            right_on="aggregation_facility",
            how="left",
        ).join(
            contingent_totals,
            left_on="facility_reference",
            right_on="aggregation_facility",
            how="left",
        ).with_columns([
            pl.col("total_drawn").fill_null(0.0),
            pl.col("total_contingent").fill_null(0.0),
        ]).with_columns([
            # total_utilised = loans drawn + contingent nominal
            (pl.col("total_drawn") + pl.col("total_contingent")).alias("total_utilised"),
        ]).with_columns([
            # undrawn = limit - total_utilised, floor at 0
            (pl.col("limit") - pl.col("total_utilised"))
            .clip(lower_bound=0.0)
            .alias("undrawn_amount"),
        ])

        # Exclude sub-facilities: only root/standalone facilities produce undrawn exposures
        facility_with_drawn = facility_with_drawn.join(
            sub_facility_refs,
            left_on="facility_reference",
            right_on="_sub_ref",
            how="anti",
        )

        # Get facility schema to check for optional columns
        facility_schema = facilities.collect_schema()
        facility_cols = set(facility_schema.names())

        # Build select expressions with defaults for missing columns
        # Note: parent_facility_reference is set to the source facility to enable
        # facility-level collateral allocation to undrawn amounts
        select_exprs = [
            (pl.col("facility_reference") + "_UNDRAWN").alias("exposure_reference"),
            pl.lit("facility_undrawn").alias("exposure_type"),
            pl.col("product_type") if "product_type" in facility_cols else pl.lit(None).cast(pl.String).alias("product_type"),
            pl.col("book_code").cast(pl.String, strict=False) if "book_code" in facility_cols else pl.lit(None).cast(pl.String).alias("book_code"),
            pl.col("counterparty_reference") if "counterparty_reference" in facility_cols else pl.lit(None).cast(pl.String).alias("counterparty_reference"),
            pl.col("value_date") if "value_date" in facility_cols else pl.lit(None).cast(pl.Date).alias("value_date"),
            pl.col("maturity_date") if "maturity_date" in facility_cols else pl.lit(None).cast(pl.Date).alias("maturity_date"),
            pl.col("currency") if "currency" in facility_cols else pl.lit(None).cast(pl.String).alias("currency"),
            pl.lit(0.0).alias("drawn_amount"),
            pl.lit(0.0).alias("interest"),  # Facility undrawn has no accrued interest
            pl.col("undrawn_amount"),
            pl.col("undrawn_amount").alias("nominal_amount"),  # CCF uses nominal_amount
            pl.col("lgd").cast(pl.Float64, strict=False) if "lgd" in facility_cols else pl.lit(None).cast(pl.Float64).alias("lgd"),
            pl.col("beel").cast(pl.Float64, strict=False).fill_null(0.0) if "beel" in facility_cols else pl.lit(0.0).alias("beel"),
            pl.col("seniority") if "seniority" in facility_cols else pl.lit(None).cast(pl.String).alias("seniority"),
            pl.col("risk_type") if "risk_type" in facility_cols else pl.lit(None).cast(pl.String).alias("risk_type"),
            pl.col("ccf_modelled").cast(pl.Float64, strict=False) if "ccf_modelled" in facility_cols else pl.lit(None).cast(pl.Float64).alias("ccf_modelled"),
            (pl.col("is_short_term_trade_lc").fill_null(False) if "is_short_term_trade_lc" in facility_cols
             else pl.lit(False).alias("is_short_term_trade_lc")),
            (pl.col("is_buy_to_let").fill_null(False) if "is_buy_to_let" in facility_cols
             else pl.lit(False).alias("is_buy_to_let")),
            # Propagate facility reference for collateral allocation
            # This allows facility-level collateral to be linked to undrawn exposures
            pl.col("facility_reference").alias("source_facility_reference"),
        ]

        # Create exposure records for facilities with undrawn > 0
        facility_undrawn_exposures = facility_with_drawn.filter(
            pl.col("undrawn_amount") > 0
        ).select(select_exprs)

        return facility_undrawn_exposures

    def _unify_exposures(
        self,
        loans: pl.LazyFrame,
        contingents: pl.LazyFrame | None,
        facilities: pl.LazyFrame | None,
        facility_mappings: pl.LazyFrame,
        counterparty_lookup: CounterpartyLookup,
    ) -> tuple[pl.LazyFrame, list[HierarchyError]]:
        """
        Unify loans, contingents, and facility undrawn into a single exposures LazyFrame.

        Creates three types of exposures:
        - loan: Drawn amounts from loans
        - contingent: Off-balance sheet items (guarantees, LCs, etc.)
        - facility_undrawn: Undrawn facility headroom (limit - drawn loans)

        Returns:
            Tuple of (unified exposures LazyFrame, list of errors)
        """
        errors: list[HierarchyError] = []

        # Standardize loan columns
        # Note: Loans are drawn exposures - CCF fields are N/A since EAD = drawn_amount + interest directly.
        # CCF only applies to off-balance sheet items (undrawn commitments, contingents).
        loan_schema = loans.collect_schema()
        loan_cols = set(loan_schema.names())
        has_interest_col = "interest" in loan_cols

        # Build loan select expressions
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
            pl.col("interest").fill_null(0.0) if has_interest_col else pl.lit(0.0).alias("interest"),
            pl.lit(0.0).alias("undrawn_amount"),
            pl.lit(0.0).alias("nominal_amount"),
            pl.col("lgd").cast(pl.Float64, strict=False),
            pl.col("beel").cast(pl.Float64, strict=False).fill_null(0.0) if "beel" in loan_cols else pl.lit(0.0).alias("beel"),
            pl.col("seniority"),
            pl.lit(None).cast(pl.String).alias("risk_type"),  # N/A for drawn loans
            pl.lit(None).cast(pl.Float64).alias("ccf_modelled"),  # N/A for drawn loans
            pl.lit(None).cast(pl.Boolean).alias("is_short_term_trade_lc"),  # N/A for drawn loans
            (pl.col("is_buy_to_let").fill_null(False) if "is_buy_to_let" in loan_cols
             else pl.lit(False).alias("is_buy_to_let")),
        ]
        loans_unified = loans.select(loan_select_exprs)

        # Build list of exposure frames to concatenate
        exposure_frames = [loans_unified]

        # Add contingents if present
        if contingents is not None:
            # Detect bs_type column and default to OFB if missing
            cont_cols = set(contingents.collect_schema().names())
            has_bs_type = "bs_type" in cont_cols
            is_drawn = (
                pl.col("bs_type").fill_null("OFB").str.to_uppercase() == "ONB"
                if has_bs_type
                else pl.lit(False)
            )

            # Standardize contingent columns with bs_type-dependent behavior:
            # ONB (drawn): drawn_amount=nominal, nominal=0, CCF fields nullified
            # OFB (undrawn): drawn_amount=0, nominal=X, CCF fields preserved
            contingents_unified = contingents.select([
                pl.col("contingent_reference").alias("exposure_reference"),
                pl.lit("contingent").alias("exposure_type"),
                pl.col("product_type"),
                pl.col("book_code").cast(pl.String, strict=False),
                pl.col("counterparty_reference"),
                pl.col("value_date"),
                pl.col("maturity_date"),
                pl.col("currency"),
                pl.when(is_drawn).then(pl.col("nominal_amount"))
                .otherwise(pl.lit(0.0)).alias("drawn_amount"),
                pl.lit(0.0).alias("interest"),
                pl.lit(0.0).alias("undrawn_amount"),
                pl.when(is_drawn).then(pl.lit(0.0))
                .otherwise(pl.col("nominal_amount")).alias("nominal_amount"),
                pl.col("lgd").cast(pl.Float64, strict=False),
                pl.col("beel").cast(pl.Float64, strict=False).fill_null(0.0) if "beel" in cont_cols else pl.lit(0.0).alias("beel"),
                pl.col("seniority"),
                pl.when(is_drawn).then(pl.lit(None).cast(pl.String))
                .otherwise(pl.col("risk_type")).alias("risk_type"),
                pl.when(is_drawn).then(pl.lit(None).cast(pl.Float64))
                .otherwise(pl.col("ccf_modelled").cast(pl.Float64, strict=False)).alias("ccf_modelled"),
                pl.when(is_drawn).then(pl.lit(None).cast(pl.Boolean))
                .otherwise(pl.col("is_short_term_trade_lc")).alias("is_short_term_trade_lc"),
                pl.lit(False).alias("is_buy_to_let"),  # BTL is a property lending characteristic, not for contingents
            ])
            exposure_frames.append(contingents_unified)

        # Build facility root lookup for multi-level hierarchies
        facility_root_lookup = self._build_facility_root_lookup(facility_mappings)

        # Calculate and add facility undrawn exposures
        # This creates separate exposure records for undrawn facility headroom
        facility_undrawn = self._calculate_facility_undrawn(
            facilities, loans, contingents, facility_mappings, facility_root_lookup
        )
        exposure_frames.append(facility_undrawn)

        # Combine all exposure types
        exposures = pl.concat(exposure_frames, how="diagonal_relaxed")

        # Filter out child_type="facility" entries since unified exposures contain only
        # loans, contingents, and facility_undrawn (never raw facilities).
        # Without this filter, when facility_reference = loan_reference AND the facility
        # is a sub-facility, child_reference has duplicate values causing row duplication.
        mapping_schema = facility_mappings.collect_schema()
        mapping_cols = set(mapping_schema.names())

        if "child_type" in mapping_cols:
            type_col = "child_type"
        elif "node_type" in mapping_cols:
            type_col = "node_type"
        else:
            type_col = None

        if type_col is not None:
            exposure_level_mappings = facility_mappings.filter(
                pl.col(type_col).fill_null("").str.to_lowercase() != "facility"
            ).select([
                pl.col("child_reference"),
                pl.col("parent_facility_reference").alias("mapped_parent_facility"),
            ]).unique(subset=["child_reference"], keep="first")
        else:
            # No type column available - use all mappings as-is
            exposure_level_mappings = facility_mappings.select([
                pl.col("child_reference"),
                pl.col("parent_facility_reference").alias("mapped_parent_facility"),
            ]).unique(subset=["child_reference"], keep="first")

        # Join with facility mappings to get parent facility
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
        exposures = exposures.with_columns([
            _parent_expr.alias("parent_facility_reference"),
            _parent_expr.is_not_null().alias("exposure_has_parent"),
        ])

        # Resolve root_facility_reference and facility_hierarchy_depth using root lookup
        # Left join is safe even when lookup is empty — NULLs fall through to the
        # when/then/otherwise chain, producing identical results to the no-lookup case.
        exposures = exposures.join(
            facility_root_lookup.select([
                pl.col("child_facility_reference").alias("_frl_child"),
                pl.col("root_facility_reference").alias("_frl_root"),
                pl.col("facility_hierarchy_depth").alias("_frl_depth"),
            ]),
            left_on="parent_facility_reference",
            right_on="_frl_child",
            how="left",
        ).with_columns([
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
        ]).drop(["_frl_root", "_frl_depth"])

        # Add counterparty rating fields needed by downstream calculators.
        # Only cqs and pd are used by SA/IRB calculators; other hierarchy
        # metadata (parent_counterparty_reference, rating_inherited, etc.)
        # remains available on counterparty_lookup.counterparties but is not
        # carried on the exposure frame to reduce column count through pipeline.
        exposures = exposures.join(
            counterparty_lookup.counterparties.select([
                pl.col("counterparty_reference"),
                pl.col("cqs"),
                pl.col("pd"),
            ]),
            on="counterparty_reference",
            how="left",
        )

        return exposures, errors

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
            "beneficiary_reference", "collateral_type", "market_value", "property_type",
        }
        if not has_required_columns(collateral, required_cols):
            return exposures.with_columns([
                pl.lit(0.0).alias("residential_collateral_value"),
                pl.lit(0.0).alias("property_collateral_value"),
                pl.lit(False).alias("has_facility_property_collateral"),
                pl.col("total_exposure_amount").alias("exposure_for_retail_threshold"),
            ])

        collateral_schema = collateral.collect_schema()
        has_beneficiary_type = "beneficiary_type" in collateral_schema.names()

        # Filter for residential property collateral (for threshold exclusion)
        residential_collateral = collateral.filter(
            (pl.col("collateral_type").str.to_lowercase() == "real_estate")
            & (pl.col("property_type").str.to_lowercase() == "residential")
        )
        # Filter for ALL property collateral (residential + commercial)
        all_property_collateral = collateral.filter(
            pl.col("collateral_type").str.to_lowercase() == "real_estate"
        )

        if not has_beneficiary_type:
            # Legacy: assume direct exposure linking only
            res_lookup = residential_collateral.group_by(
                "beneficiary_reference"
            ).agg(
                pl.col("market_value").sum().alias("residential_collateral_value"),
            )
            prop_lookup = all_property_collateral.group_by(
                "beneficiary_reference"
            ).agg(
                pl.col("market_value").sum().alias("property_collateral_value"),
            )
            exposures = exposures.join(
                res_lookup,
                left_on="exposure_reference",
                right_on="beneficiary_reference",
                how="left",
            ).join(
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
            # This sets has_facility_property_collateral inline.
            exposures = self._join_property_collateral_multi_level(
                exposures, residential_collateral, all_property_collateral,
            )
            needs_facility_flag = False

        # Fill nulls, cap at exposure amount, derive threshold
        exposures = exposures.with_columns([
            pl.col("residential_collateral_value").fill_null(0.0),
            pl.col("property_collateral_value").fill_null(0.0),
        ]).with_columns([
            pl.when(
                pl.col("residential_collateral_value")
                > pl.col("total_exposure_amount")
            )
            .then(pl.col("total_exposure_amount"))
            .otherwise(pl.col("residential_collateral_value"))
            .alias("residential_collateral_value"),
            pl.when(
                pl.col("property_collateral_value")
                > pl.col("total_exposure_amount")
            )
            .then(pl.col("total_exposure_amount"))
            .otherwise(pl.col("property_collateral_value"))
            .alias("property_collateral_value"),
        ]).with_columns([
            (
                pl.col("total_exposure_amount")
                - pl.col("residential_collateral_value")
            ).alias("exposure_for_retail_threshold"),
        ])

        # Add has_facility_property_collateral for legacy path
        if needs_facility_flag:
            exposures = exposures.with_columns(
                (pl.col("property_collateral_value") > 0).alias(
                    "has_facility_property_collateral"
                ),
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
        is_residential = (
            pl.col("property_type").str.to_lowercase() == "residential"
        )

        # Single conditional group_by: 6 aggregates in one pass
        coll_agg = all_property_collateral.with_columns(
            pl.when(bt_lower.is_in(["exposure", "loan"]))
            .then(pl.lit("direct"))
            .when(bt_lower == "facility").then(pl.lit("facility"))
            .when(bt_lower == "counterparty").then(pl.lit("counterparty"))
            .otherwise(pl.lit("direct"))
            .alias("_level"),
        ).group_by(["_level", "beneficiary_reference"]).agg([
            pl.col("market_value").filter(is_residential).sum()
            .alias("_res"),
            pl.col("market_value").sum().alias("_prop"),
        ])

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
        exposures = exposures.with_columns([
            pl.when(pl.col("parent_facility_reference").is_not_null())
            .then(
                pl.col("total_exposure_amount").sum().over(
                    "parent_facility_reference"
                )
            )
            .otherwise(pl.col("total_exposure_amount"))
            .alias("facility_total"),
            pl.when(pl.col("counterparty_reference").is_not_null())
            .then(
                pl.col("total_exposure_amount").sum().over("counterparty_reference")
            )
            .otherwise(pl.col("total_exposure_amount"))
            .alias("cp_total"),
        ])

        # 3 joins (one per level) instead of 6
        exposures = exposures.join(
            coll_direct,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        ).join(
            coll_facility,
            left_on="parent_facility_reference",
            right_on="beneficiary_reference",
            how="left",
        ).join(
            coll_cp,
            left_on="counterparty_reference",
            right_on="beneficiary_reference",
            how="left",
        )

        # Pro-rata weights + combine all levels in one batch
        exposures = exposures.with_columns([
            pl.when(pl.col("facility_total") > 0)
            .then(pl.col("total_exposure_amount") / pl.col("facility_total"))
            .otherwise(pl.lit(0.0))
            .alias("facility_weight"),
            pl.when(pl.col("cp_total") > 0)
            .then(pl.col("total_exposure_amount") / pl.col("cp_total"))
            .otherwise(pl.lit(0.0))
            .alias("cp_weight"),
        ])

        exposures = exposures.with_columns([
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
        ])

        # Drop intermediate columns
        return exposures.drop([
            "_res_d", "_res_f", "_res_c",
            "_prop_d", "_prop_f", "_prop_c",
            "facility_total", "cp_total", "facility_weight", "cp_weight",
        ])

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
        is used for retail threshold testing.

        Args:
            exposures: Exposures with property coverage columns already added
            lending_mappings: Lending group parent-child mappings

        Returns:
            Exposures with lending_group_reference, lending_group_total_exposure,
            and lending_group_adjusted_exposure columns added
        """
        # Build lending group membership
        lending_groups = lending_mappings.select([
            pl.col("parent_counterparty_reference").alias(
                "lending_group_reference"
            ),
            pl.col("child_counterparty_reference").alias(
                "member_counterparty_reference"
            ),
        ])

        parent_as_member = lending_mappings.select([
            pl.col("parent_counterparty_reference").alias(
                "lending_group_reference"
            ),
            pl.col("parent_counterparty_reference").alias(
                "member_counterparty_reference"
            ),
        ]).unique()

        all_members = pl.concat(
            [lending_groups, parent_as_member], how="vertical",
        ).unique(subset=["member_counterparty_reference"], keep="first")

        # Join to get lending group reference
        exposures = exposures.join(
            all_members,
            left_on="counterparty_reference",
            right_on="member_counterparty_reference",
            how="left",
        )

        # .over() window functions for group totals (no self-join!)
        exposures = exposures.with_columns([
            pl.when(pl.col("lending_group_reference").is_not_null())
            .then(
                pl.col("drawn_amount")
                .clip(lower_bound=0.0)
                .sum()
                .over("lending_group_reference")
                + pl.col("nominal_amount").sum().over("lending_group_reference")
            )
            .otherwise(0.0)
            .alias("lending_group_total_exposure"),
            pl.when(pl.col("lending_group_reference").is_not_null())
            .then(
                pl.col("exposure_for_retail_threshold").sum().over(
                    "lending_group_reference"
                )
            )
            .otherwise(0.0)
            .alias("lending_group_adjusted_exposure"),
        ])

        return exposures

    def _add_collateral_ltv(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame | None,
    ) -> pl.LazyFrame:
        """
        Add LTV from collateral to exposures for real estate risk weight calculations.

        Joins collateral property_ltv to exposures where collateral is linked via
        beneficiary_reference. For mortgages and commercial RE, LTV determines risk weight.

        Supports three levels of collateral linking based on beneficiary_type:
        1. Direct (exposure/loan): beneficiary_reference matches exposure_reference
        2. Facility: beneficiary_reference matches parent_facility_reference
        3. Counterparty: beneficiary_reference matches counterparty_reference

        Args:
            exposures: Unified exposures with exposure_reference
            collateral: Collateral data with beneficiary_reference and property_ltv (optional)

        Returns:
            Exposures with ltv column added
        """
        # Check if collateral is valid for LTV processing
        # Requires beneficiary_reference and property_ltv columns
        required_cols = {"beneficiary_reference", "property_ltv"}
        if not has_required_columns(collateral, required_cols):
            # No valid LTV data available, add null ltv column
            return exposures.with_columns([
                pl.lit(None).cast(pl.Float64).alias("ltv"),
            ])

        # Check if beneficiary_type column exists for multi-level linking
        collateral_schema = collateral.collect_schema()
        has_beneficiary_type = "beneficiary_type" in collateral_schema.names()

        # Filter for collateral with LTV data
        ltv_collateral = collateral.filter(pl.col("property_ltv").is_not_null())

        if not has_beneficiary_type:
            # Legacy behavior: assume direct exposure linking
            ltv_lookup = ltv_collateral.select([
                pl.col("beneficiary_reference"),
                pl.col("property_ltv").alias("ltv"),
            ]).unique(subset=["beneficiary_reference"], keep="first")

            return exposures.join(
                ltv_lookup,
                left_on="exposure_reference",
                right_on="beneficiary_reference",
                how="left",
            )

        # Multi-level linking: separate collateral by beneficiary_type
        # 1. Direct/exposure-level collateral
        direct_ltv = ltv_collateral.filter(
            pl.col("beneficiary_type").str.to_lowercase().is_in(["exposure", "loan"])
        ).select([
            pl.col("beneficiary_reference").alias("direct_ref"),
            pl.col("property_ltv").alias("direct_ltv"),
        ]).unique(subset=["direct_ref"], keep="first")

        # 2. Facility-level collateral
        facility_ltv = ltv_collateral.filter(
            pl.col("beneficiary_type").str.to_lowercase() == "facility"
        ).select([
            pl.col("beneficiary_reference").alias("facility_ref"),
            pl.col("property_ltv").alias("facility_ltv"),
        ]).unique(subset=["facility_ref"], keep="first")

        # 3. Counterparty-level collateral
        counterparty_ltv = ltv_collateral.filter(
            pl.col("beneficiary_type").str.to_lowercase() == "counterparty"
        ).select([
            pl.col("beneficiary_reference").alias("cp_ref"),
            pl.col("property_ltv").alias("cp_ltv"),
        ]).unique(subset=["cp_ref"], keep="first")

        # Join all three levels
        exposures = exposures.join(
            direct_ltv,
            left_on="exposure_reference",
            right_on="direct_ref",
            how="left",
        ).join(
            facility_ltv,
            left_on="parent_facility_reference",
            right_on="facility_ref",
            how="left",
        ).join(
            counterparty_ltv,
            left_on="counterparty_reference",
            right_on="cp_ref",
            how="left",
        )

        # Coalesce LTV: prefer direct, then facility, then counterparty
        exposures = exposures.with_columns([
            pl.coalesce(
                pl.col("direct_ltv"),
                pl.col("facility_ltv"),
                pl.col("cp_ltv"),
            ).alias("ltv"),
        ]).drop(["direct_ltv", "facility_ltv", "cp_ltv"])

        return exposures



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


def create_hierarchy_resolver() -> HierarchyResolver:
    """
    Create a hierarchy resolver instance.

    Returns:
        HierarchyResolver ready for use
    """
    return HierarchyResolver()
