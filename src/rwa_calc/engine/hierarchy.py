"""
Hierarchy resolution for RWA calculator.

Resolves counterparty and facility hierarchies, enabling:
- Rating inheritance from parent entities
- Lending group exposure aggregation for retail threshold
- Facility-to-exposure hierarchy traversal

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

        # Step 2: Unify exposures (loans + contingents) with hierarchy metadata
        exposures, exp_errors = self._unify_exposures(
            data.loans,
            data.contingents,
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

        if config.apply_fx_conversion and data.fx_rates is not None:
            exposures = fx_converter.convert_exposures(exposures, data.fx_rates, config)
            if collateral is not None:
                collateral = fx_converter.convert_collateral(collateral, data.fx_rates, config)
            if guarantees is not None:
                guarantees = fx_converter.convert_guarantees(guarantees, data.fx_rates, config)
            if provisions is not None:
                provisions = fx_converter.convert_provisions(provisions, data.fx_rates, config)
        else:
            # Add audit trail columns with null values when no conversion
            exposures = exposures.with_columns([
                pl.col("currency").alias("original_currency"),
                (pl.col("drawn_amount") + pl.col("nominal_amount")).alias("original_amount"),
                pl.lit(None).cast(pl.Float64).alias("fx_rate_applied"),
            ])

        # Step 2b: Add collateral LTV to exposures (for real estate risk weights)
        exposures = self._add_collateral_ltv(exposures, collateral)

        # Step 3: Calculate lending group totals
        lending_group_totals, lg_errors = self._calculate_lending_group_totals(
            exposures,
            data.lending_mappings,
        )
        errors.extend(lg_errors)

        # Step 4: Add lending group exposure totals to exposures
        exposures = self._add_lending_group_totals_to_exposures(
            exposures,
            data.lending_mappings,
            lending_group_totals,
        )

        return ResolvedHierarchyBundle(
            exposures=exposures,
            counterparty_lookup=counterparty_lookup,
            collateral=collateral,
            guarantees=guarantees,
            provisions=provisions,
            lending_group_totals=lending_group_totals,
            hierarchy_errors=errors,
        )

    def _build_counterparty_lookup(
        self,
        counterparties: pl.LazyFrame,
        org_mappings: pl.LazyFrame,
        ratings: pl.LazyFrame | None,
    ) -> tuple[CounterpartyLookup, list[HierarchyError]]:
        """
        Build counterparty hierarchy lookup using pure LazyFrame operations.

        Returns:
            Tuple of (CounterpartyLookup, list of errors)
        """
        errors: list[HierarchyError] = []

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
        Build ultimate parent mapping using iterative joins.

        Returns LazyFrame with columns:
        - counterparty_reference: The entity
        - ultimate_parent_reference: Its ultimate parent
        - hierarchy_depth: Number of levels traversed
        """
        # Get unique child references
        entities = org_mappings.select(
            pl.col("child_counterparty_reference").alias("counterparty_reference")
        ).unique()

        # Parent lookup for joins (alias child column to avoid name collision)
        parent_map = org_mappings.select([
            pl.col("child_counterparty_reference").alias("_lookup_child"),
            pl.col("parent_counterparty_reference").alias("_lookup_parent"),
        ])

        # Initialize: each entity's current parent is its direct parent (or self)
        # Depth starts at 1 for entities with a parent, 0 for root entities
        result = entities.join(
            parent_map,
            left_on="counterparty_reference",
            right_on="_lookup_child",
            how="left",
        ).with_columns([
            pl.coalesce(
                pl.col("_lookup_parent"),
                pl.col("counterparty_reference")
            ).alias("current_parent"),
            pl.when(pl.col("_lookup_parent").is_not_null())
            .then(pl.lit(1).cast(pl.Int32))
            .otherwise(pl.lit(0).cast(pl.Int32))
            .alias("depth"),
        ]).select([
            pl.col("counterparty_reference"),
            pl.col("current_parent"),
            pl.col("depth"),
        ])

        # Iteratively traverse upward - each iteration adds one level of depth
        for _ in range(max_depth):
            result = result.join(
                parent_map,
                left_on="current_parent",
                right_on="_lookup_child",
                how="left",
            ).with_columns([
                pl.coalesce(pl.col("_lookup_parent"), pl.col("current_parent")).alias("current_parent"),
                pl.when(pl.col("_lookup_parent").is_not_null())
                .then(pl.col("depth") + 1)
                .otherwise(pl.col("depth"))
                .alias("depth"),
            ]).select([
                pl.col("counterparty_reference"),
                pl.col("current_parent"),
                pl.col("depth"),
            ])

        return result.select([
            pl.col("counterparty_reference"),
            pl.col("current_parent").alias("ultimate_parent_reference"),
            pl.col("depth").alias("hierarchy_depth"),
        ])

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

        # Add has_parent flag
        enriched = enriched.with_columns([
            pl.col("parent_counterparty_reference").is_not_null().alias("counterparty_has_parent"),
        ])

        # Join with ultimate parents
        enriched = enriched.join(
            ultimate_parents.select([
                pl.col("counterparty_reference").alias("_up_cp"),
                pl.col("ultimate_parent_reference"),
                pl.col("hierarchy_depth").alias("counterparty_hierarchy_depth"),
            ]),
            left_on="counterparty_reference",
            right_on="_up_cp",
            how="left",
        )

        # Join with rating inheritance info
        enriched = enriched.join(
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
        )

        # Fill null hierarchy depth with 0 for entities without hierarchy
        enriched = enriched.with_columns([
            pl.col("counterparty_hierarchy_depth").fill_null(0),
        ])

        return enriched

    def _unify_exposures(
        self,
        loans: pl.LazyFrame,
        contingents: pl.LazyFrame | None,
        facility_mappings: pl.LazyFrame,
        counterparty_lookup: CounterpartyLookup,
    ) -> tuple[pl.LazyFrame, list[HierarchyError]]:
        """
        Unify loans and contingents into a single exposures LazyFrame.

        Returns:
            Tuple of (unified exposures LazyFrame, list of errors)
        """
        errors: list[HierarchyError] = []

        # Standardize loan columns
        loans_unified = loans.select([
            pl.col("loan_reference").alias("exposure_reference"),
            pl.lit("loan").alias("exposure_type"),
            pl.col("product_type"),
            pl.col("book_code"),
            pl.col("counterparty_reference"),
            pl.col("value_date"),
            pl.col("maturity_date"),
            pl.col("currency"),
            pl.col("drawn_amount"),
            pl.lit(0.0).alias("undrawn_amount"),
            pl.lit(0.0).alias("nominal_amount"),
            pl.col("lgd"),
            pl.col("seniority"),
            pl.lit(None).cast(pl.String).alias("ccf_category"),
            pl.col("risk_type"),
            pl.col("ccf_modelled"),
            pl.lit(None).cast(pl.Boolean).alias("is_short_term_trade_lc"),  # N/A for loans
        ])

        # If contingents is None, use only loans
        if contingents is None:
            exposures = loans_unified
        else:
            # Standardize contingent columns
            contingents_unified = contingents.select([
                pl.col("contingent_reference").alias("exposure_reference"),
                pl.lit("contingent").alias("exposure_type"),
                pl.col("product_type"),
                pl.col("book_code"),
                pl.col("counterparty_reference"),
                pl.col("value_date"),
                pl.col("maturity_date"),
                pl.col("currency"),
                pl.lit(0.0).alias("drawn_amount"),
                pl.lit(0.0).alias("undrawn_amount"),
                pl.col("nominal_amount"),
                pl.col("lgd"),
                pl.col("seniority"),
                pl.col("ccf_category"),
                pl.col("risk_type"),
                pl.col("ccf_modelled"),
                pl.col("is_short_term_trade_lc"),  # Art. 166(9) exception for F-IRB
            ])

            # Combine
            exposures = pl.concat([loans_unified, contingents_unified], how="diagonal_relaxed")

        # Join with facility mappings to get parent facility
        exposures = exposures.join(
            facility_mappings.select([
                pl.col("child_reference"),
                pl.col("parent_facility_reference"),
            ]),
            left_on="exposure_reference",
            right_on="child_reference",
            how="left",
        )

        # Add facility hierarchy fields
        exposures = exposures.with_columns([
            pl.col("parent_facility_reference").is_not_null().alias("exposure_has_parent"),
            pl.col("parent_facility_reference").alias("root_facility_reference"),  # Simplified
            pl.lit(1).cast(pl.Int8).alias("facility_hierarchy_depth"),
        ])

        # Add counterparty hierarchy fields from lookup (now includes ultimate parent)
        exposures = exposures.join(
            counterparty_lookup.counterparties.select([
                pl.col("counterparty_reference"),
                pl.col("counterparty_has_parent"),
                pl.col("parent_counterparty_reference"),
                pl.col("ultimate_parent_reference"),
                pl.col("counterparty_hierarchy_depth"),
                pl.col("cqs"),
                pl.col("pd"),
                pl.col("rating_value"),
                pl.col("rating_agency"),
                pl.col("rating_inherited"),
                pl.col("rating_source_counterparty"),
                pl.col("rating_inheritance_reason"),
            ]),
            on="counterparty_reference",
            how="left",
        )

        return exposures, errors

    def _calculate_lending_group_totals(
        self,
        exposures: pl.LazyFrame,
        lending_mappings: pl.LazyFrame,
    ) -> tuple[pl.LazyFrame, list[HierarchyError]]:
        """
        Calculate total exposure by lending group for retail threshold testing.

        Returns:
            Tuple of (lending group totals LazyFrame, list of errors)
        """
        errors: list[HierarchyError] = []

        # Build lending group membership
        # The parent_counterparty_reference is the lending group anchor
        lending_groups = lending_mappings.select([
            pl.col("parent_counterparty_reference").alias("lending_group_reference"),
            pl.col("child_counterparty_reference").alias("member_counterparty_reference"),
        ])

        # Include the parent itself as a member
        parent_as_member = lending_mappings.select([
            pl.col("parent_counterparty_reference").alias("lending_group_reference"),
            pl.col("parent_counterparty_reference").alias("member_counterparty_reference"),
        ]).unique()

        all_members = pl.concat([lending_groups, parent_as_member], how="vertical")

        # Join exposures to get lending group for each counterparty
        exposures_with_group = exposures.join(
            all_members,
            left_on="counterparty_reference",
            right_on="member_counterparty_reference",
            how="left",
        )

        # Calculate total drawn amount per lending group
        lending_group_totals = exposures_with_group.filter(
            pl.col("lending_group_reference").is_not_null()
        ).group_by("lending_group_reference").agg([
            pl.col("drawn_amount").sum().alias("total_drawn"),
            pl.col("nominal_amount").sum().alias("total_nominal"),
            (pl.col("drawn_amount") + pl.col("nominal_amount")).sum().alias("total_exposure"),
            pl.len().alias("exposure_count"),
        ])

        return lending_group_totals, errors

    def _add_collateral_ltv(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame | None,
    ) -> pl.LazyFrame:
        """
        Add LTV from collateral to exposures for real estate risk weight calculations.

        Joins collateral property_ltv to exposures where collateral is linked via
        beneficiary_reference. For mortgages and commercial RE, LTV determines risk weight.

        Args:
            exposures: Unified exposures with exposure_reference
            collateral: Collateral data with beneficiary_reference and property_ltv (optional)

        Returns:
            Exposures with ltv column added
        """
        # If collateral is None, add null ltv column
        if collateral is None:
            return exposures.with_columns([
                pl.lit(None).cast(pl.Float64).alias("ltv"),
            ])

        # Check if collateral has the required columns
        collateral_schema = collateral.collect_schema()
        if "beneficiary_reference" not in collateral_schema or "property_ltv" not in collateral_schema:
            # No LTV data available, add null ltv column
            return exposures.with_columns([
                pl.lit(None).cast(pl.Float64).alias("ltv"),
            ])

        # Select only the LTV column from collateral
        ltv_lookup = collateral.select([
            pl.col("beneficiary_reference"),
            pl.col("property_ltv").alias("ltv"),
        ]).filter(
            # Only include collateral with LTV data
            pl.col("ltv").is_not_null()
        ).unique(
            # Take first match if multiple collaterals
            subset=["beneficiary_reference"],
            keep="first",
        )

        # Join LTV to exposures
        exposures = exposures.join(
            ltv_lookup,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        )

        return exposures

    def _add_lending_group_totals_to_exposures(
        self,
        exposures: pl.LazyFrame,
        lending_mappings: pl.LazyFrame,
        lending_group_totals: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Add lending group reference and total exposure to each exposure.
        """
        # Build lending group membership (same as above)
        lending_groups = lending_mappings.select([
            pl.col("parent_counterparty_reference").alias("lending_group_reference"),
            pl.col("child_counterparty_reference").alias("member_counterparty_reference"),
        ])

        parent_as_member = lending_mappings.select([
            pl.col("parent_counterparty_reference").alias("lending_group_reference"),
            pl.col("parent_counterparty_reference").alias("member_counterparty_reference"),
        ]).unique()

        all_members = pl.concat([lending_groups, parent_as_member], how="vertical")

        # Join to get lending group reference
        exposures = exposures.join(
            all_members,
            left_on="counterparty_reference",
            right_on="member_counterparty_reference",
            how="left",
        )

        # Join to get lending group total exposure
        exposures = exposures.join(
            lending_group_totals.select([
                pl.col("lending_group_reference").alias("lg_ref_for_join"),
                pl.col("total_exposure").alias("lending_group_total_exposure"),
            ]),
            left_on="lending_group_reference",
            right_on="lg_ref_for_join",
            how="left",
        )

        # Fill nulls with 0 for non-grouped exposures
        exposures = exposures.with_columns([
            pl.col("lending_group_total_exposure").fill_null(0.0),
        ])

        return exposures


def create_hierarchy_resolver() -> HierarchyResolver:
    """
    Create a hierarchy resolver instance.

    Returns:
        HierarchyResolver ready for use
    """
    return HierarchyResolver()
