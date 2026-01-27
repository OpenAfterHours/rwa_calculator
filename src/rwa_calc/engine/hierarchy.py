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

    def _is_valid_optional_data(
        self,
        data: pl.LazyFrame | None,
        required_columns: set[str] | None = None,
    ) -> bool:
        """
        Check if optional data is valid for processing.

        This provides defense-in-depth validation to ensure data:
        - Is not None
        - Has at least one row
        - Has all required columns (if specified)

        Args:
            data: Optional LazyFrame to validate
            required_columns: Set of column names that must be present (optional)

        Returns:
            True if data is valid for processing, False otherwise
        """
        if data is None:
            return False

        try:
            schema = data.collect_schema()

            # Check required columns if specified
            if required_columns is not None:
                if not required_columns.issubset(set(schema.names())):
                    return False

            # Check if there's at least one row
            return data.head(1).collect().height > 0
        except Exception:
            return False

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

        # Step 3: Calculate residential property coverage per exposure
        # This is needed to exclude residential RE from retail threshold calculation
        # per CRR Art. 123(c) and Basel 3.1 CRE20.65
        residential_coverage = self._calculate_residential_property_coverage(
            exposures,
            collateral,
        )

        # Step 4: Calculate lending group totals (excluding residential property)
        lending_group_totals, lg_errors = self._calculate_lending_group_totals(
            exposures,
            data.lending_mappings,
            residential_coverage,
        )
        errors.extend(lg_errors)

        # Step 5: Add lending group exposure totals to exposures
        exposures = self._add_lending_group_totals_to_exposures(
            exposures,
            data.lending_mappings,
            lending_group_totals,
            residential_coverage,
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
        # Note: Loans are drawn exposures - CCF fields are N/A since EAD = drawn_amount directly.
        # CCF only applies to off-balance sheet items (undrawn commitments, contingents).
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
            pl.lit(None).cast(pl.String).alias("risk_type"),  # N/A for drawn loans
            pl.lit(None).cast(pl.Float64).alias("ccf_modelled"),  # N/A for drawn loans
            pl.lit(None).cast(pl.Boolean).alias("is_short_term_trade_lc"),  # N/A for drawn loans
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
        residential_coverage: pl.LazyFrame,
    ) -> tuple[pl.LazyFrame, list[HierarchyError]]:
        """
        Calculate total exposure by lending group for retail threshold testing.

        Per CRR Art. 123(c) and Basel 3.1 CRE20.65, exposures secured by residential
        property (under SA treatment) are excluded from the EUR 1m threshold calculation.

        Calculates both:
        - total_exposure: Raw sum of drawn + nominal amounts
        - adjusted_exposure: Sum excluding residential property collateral value

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

        # Join with residential coverage to get adjusted exposure amounts
        exposures_with_group = exposures_with_group.join(
            residential_coverage.select([
                pl.col("exposure_reference").alias("_res_exp_ref"),
                pl.col("residential_collateral_value"),
                pl.col("exposure_for_retail_threshold"),
            ]),
            left_on="exposure_reference",
            right_on="_res_exp_ref",
            how="left",
        ).with_columns([
            # Fill nulls for exposures without residential coverage data
            pl.col("residential_collateral_value").fill_null(0.0),
            pl.col("exposure_for_retail_threshold").fill_null(
                pl.col("drawn_amount") + pl.col("nominal_amount")
            ),
        ])

        # Calculate totals per lending group
        # - total_exposure: Raw sum (for reference/audit)
        # - adjusted_exposure: Sum excluding residential property (for retail threshold)
        lending_group_totals = exposures_with_group.filter(
            pl.col("lending_group_reference").is_not_null()
        ).group_by("lending_group_reference").agg([
            pl.col("drawn_amount").sum().alias("total_drawn"),
            pl.col("nominal_amount").sum().alias("total_nominal"),
            (pl.col("drawn_amount") + pl.col("nominal_amount")).sum().alias("total_exposure"),
            pl.col("exposure_for_retail_threshold").sum().alias("adjusted_exposure"),
            pl.col("residential_collateral_value").sum().alias("total_residential_coverage"),
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
        # Check if collateral is valid for LTV processing
        # Requires beneficiary_reference and property_ltv columns
        required_cols = {"beneficiary_reference", "property_ltv"}
        if not self._is_valid_optional_data(collateral, required_cols):
            # No valid LTV data available, add null ltv column
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

    def _calculate_residential_property_coverage(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame | None,
    ) -> pl.LazyFrame:
        """
        Calculate residential property collateral coverage per exposure.

        Per CRR Art. 123(c) and Basel 3.1 CRE20.65, exposures fully and completely
        secured by residential property (assigned to SA residential property class)
        should be excluded from the EUR 1m retail threshold aggregation.

        The exclusion amount is the lesser of:
        - The residential property collateral value (after any haircuts)
        - The exposure amount (to prevent over-exclusion)

        Args:
            exposures: Unified exposures with exposure_reference
            collateral: Collateral data with property_type and market_value

        Returns:
            LazyFrame with columns:
            - exposure_reference: The exposure identifier
            - residential_collateral_value: Value of residential RE securing this exposure
            - exposure_for_retail_threshold: Exposure amount minus residential coverage
        """
        # Get exposure amounts for capping
        exposure_amounts = exposures.select([
            pl.col("exposure_reference"),
            (pl.col("drawn_amount") + pl.col("nominal_amount")).alias("total_exposure_amount"),
        ])

        # Check if collateral is valid for residential property coverage calculation
        # Requires beneficiary_reference, collateral_type, market_value, and property_type
        required_cols = {"beneficiary_reference", "collateral_type", "market_value", "property_type"}
        if not self._is_valid_optional_data(collateral, required_cols):
            # No valid collateral data, return exposures with zero residential coverage
            return exposure_amounts.with_columns([
                pl.lit(0.0).alias("residential_collateral_value"),
                pl.col("total_exposure_amount").alias("exposure_for_retail_threshold"),
            ])

        # Filter for residential property collateral only
        # Residential property = collateral_type is 'real_estate' AND property_type is 'residential'
        # Note: property_type existence is already validated above
        residential_collateral = collateral.filter(
            (pl.col("collateral_type").str.to_lowercase() == "real_estate") &
            (pl.col("property_type").str.to_lowercase() == "residential")
        )

        # Sum residential collateral value per beneficiary (exposure)
        residential_by_exposure = residential_collateral.group_by("beneficiary_reference").agg([
            pl.col("market_value").sum().alias("residential_collateral_value"),
        ])

        # Join with exposure amounts
        result = exposure_amounts.join(
            residential_by_exposure,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        )

        # Fill nulls with 0 and cap at exposure amount
        result = result.with_columns([
            pl.col("residential_collateral_value").fill_null(0.0),
        ]).with_columns([
            # Cap residential coverage at exposure amount (can't exclude more than exposure)
            pl.when(pl.col("residential_collateral_value") > pl.col("total_exposure_amount"))
            .then(pl.col("total_exposure_amount"))
            .otherwise(pl.col("residential_collateral_value"))
            .alias("residential_collateral_value"),
        ]).with_columns([
            # Calculate exposure for retail threshold = exposure - residential coverage
            (pl.col("total_exposure_amount") - pl.col("residential_collateral_value"))
            .alias("exposure_for_retail_threshold"),
        ])

        return result.select([
            "exposure_reference",
            "residential_collateral_value",
            "exposure_for_retail_threshold",
        ])

    def _add_lending_group_totals_to_exposures(
        self,
        exposures: pl.LazyFrame,
        lending_mappings: pl.LazyFrame,
        lending_group_totals: pl.LazyFrame,
        residential_coverage: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Add lending group reference and exposure totals to each exposure.

        Adds columns:
        - lending_group_reference: Reference to the lending group parent
        - lending_group_total_exposure: Raw sum of exposures in the lending group
        - lending_group_adjusted_exposure: Sum excluding residential property (for retail threshold)
        - residential_collateral_value: Residential RE collateral value for this exposure
        - exposure_for_retail_threshold: This exposure's contribution to retail threshold

        Per CRR Art. 123(c), the adjusted_exposure is used for retail threshold testing,
        excluding exposures secured by residential property under SA treatment.
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

        # Join to get lending group totals (both raw and adjusted)
        exposures = exposures.join(
            lending_group_totals.select([
                pl.col("lending_group_reference").alias("lg_ref_for_join"),
                pl.col("total_exposure").alias("lending_group_total_exposure"),
                pl.col("adjusted_exposure").alias("lending_group_adjusted_exposure"),
            ]),
            left_on="lending_group_reference",
            right_on="lg_ref_for_join",
            how="left",
        )

        # Join residential coverage per exposure (for audit trail)
        exposures = exposures.join(
            residential_coverage.select([
                pl.col("exposure_reference").alias("_res_exp_ref"),
                pl.col("residential_collateral_value"),
                pl.col("exposure_for_retail_threshold"),
            ]),
            left_on="exposure_reference",
            right_on="_res_exp_ref",
            how="left",
        )

        # Fill nulls with 0 for non-grouped exposures and exposures without residential coverage
        exposures = exposures.with_columns([
            pl.col("lending_group_total_exposure").fill_null(0.0),
            pl.col("lending_group_adjusted_exposure").fill_null(0.0),
            pl.col("residential_collateral_value").fill_null(0.0),
            pl.col("exposure_for_retail_threshold").fill_null(
                pl.col("drawn_amount") + pl.col("nominal_amount")
            ),
        ])

        return exposures


def create_hierarchy_resolver() -> HierarchyResolver:
    """
    Create a hierarchy resolver instance.

    Returns:
        HierarchyResolver ready for use
    """
    return HierarchyResolver()
