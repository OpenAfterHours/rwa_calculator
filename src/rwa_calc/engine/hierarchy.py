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
                (pl.col("drawn_amount") + pl.col("interest").fill_null(0.0) + pl.col("nominal_amount")).alias("original_amount"),
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

    def _build_facility_root_lookup(
        self,
        facility_mappings: pl.LazyFrame,
        max_depth: int = 10,
    ) -> pl.LazyFrame:
        """
        Build root facility lookup for multi-level facility hierarchies.

        Mirrors _build_ultimate_parent_lazy but for facility-to-facility relationships.
        Iteratively traverses upward through facility hierarchy to find the root facility.

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

        # Filter to facility→facility relationships only
        facility_edges = facility_mappings.filter(
            pl.col(type_col).fill_null("").str.to_lowercase() == "facility"
        ).select([
            pl.col("child_reference").alias("child_facility_reference"),
            pl.col("parent_facility_reference"),
        ]).unique()

        # Check if there are any facility edges
        if facility_edges.head(1).collect().height == 0:
            return empty_result

        # Parent lookup for iterative joins
        parent_map = facility_edges.select([
            pl.col("child_facility_reference").alias("_lookup_child"),
            pl.col("parent_facility_reference").alias("_lookup_parent"),
        ])

        # Initialize: each sub-facility's current parent is its direct parent
        result = facility_edges.join(
            parent_map,
            left_on="parent_facility_reference",
            right_on="_lookup_child",
            how="left",
        ).with_columns([
            pl.coalesce(
                pl.col("_lookup_parent"),
                pl.col("parent_facility_reference"),
            ).alias("current_root"),
            pl.when(pl.col("_lookup_parent").is_not_null())
            .then(pl.lit(2).cast(pl.Int32))
            .otherwise(pl.lit(1).cast(pl.Int32))
            .alias("depth"),
        ]).select([
            pl.col("child_facility_reference"),
            pl.col("current_root"),
            pl.col("depth"),
        ])

        # Iteratively traverse upward
        for _ in range(max_depth - 1):
            result = result.join(
                parent_map,
                left_on="current_root",
                right_on="_lookup_child",
                how="left",
            ).with_columns([
                pl.coalesce(
                    pl.col("_lookup_parent"),
                    pl.col("current_root"),
                ).alias("current_root"),
                pl.when(pl.col("_lookup_parent").is_not_null())
                .then(pl.col("depth") + 1)
                .otherwise(pl.col("depth"))
                .alias("depth"),
            ]).select([
                pl.col("child_facility_reference"),
                pl.col("current_root"),
                pl.col("depth"),
            ])

        return result.select([
            pl.col("child_facility_reference"),
            pl.col("current_root").alias("root_facility_reference"),
            pl.col("depth").alias("facility_hierarchy_depth"),
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
        if not self._is_valid_optional_data(facilities, required_cols):
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
                "seniority": pl.String,
                "risk_type": pl.String,
                "ccf_modelled": pl.Float64,
                "is_short_term_trade_lc": pl.Boolean,
                "is_buy_to_let": pl.Boolean,
            })

        # Check if facility_mappings is valid
        mapping_required_cols = {"parent_facility_reference", "child_reference"}
        if not self._is_valid_optional_data(facility_mappings, mapping_required_cols):
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

            # For multi-level hierarchies, map each loan's drawn amount to the ROOT facility
            if facility_root_lookup is not None and facility_root_lookup.head(1).collect().height > 0:
                loan_with_parent = loan_with_parent.join(
                    facility_root_lookup.select([
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
            else:
                loan_with_parent = loan_with_parent.with_columns([
                    pl.col("parent_facility_reference").alias("aggregation_facility"),
                ])

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

            # For multi-level hierarchies, map to root facility
            if facility_root_lookup is not None and facility_root_lookup.head(1).collect().height > 0:
                contingent_with_parent = contingent_with_parent.join(
                    facility_root_lookup.select([
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
            else:
                contingent_with_parent = contingent_with_parent.with_columns([
                    pl.col("parent_facility_reference").alias("aggregation_facility"),
                ])

            contingent_totals = contingent_with_parent.group_by("aggregation_facility").agg([
                pl.col("nominal_amount").clip(lower_bound=0.0).sum().alias("total_contingent"),
            ])

        # Identify sub-facilities to exclude from output
        # Sub-facilities appear as child_reference with child_type="facility"
        if facility_root_lookup is not None and facility_root_lookup.head(1).collect().height > 0:
            sub_facility_refs = facility_root_lookup.select(
                pl.col("child_facility_reference").alias("_sub_ref"),
            )
        else:
            sub_facility_refs = pl.LazyFrame(schema={"_sub_ref": pl.String})

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

        # Add facility hierarchy fields
        # For facility_undrawn exposures, use source_facility_reference as parent_facility_reference
        # This enables facility-level collateral to be allocated to undrawn amounts
        schema_names = set(exposures.collect_schema().names())
        if "source_facility_reference" in schema_names:
            exposures = exposures.with_columns([
                # parent_facility_reference: prefer mapped value, then source_facility (for undrawn)
                pl.coalesce(
                    pl.col("mapped_parent_facility"),
                    pl.col("source_facility_reference"),
                ).alias("parent_facility_reference"),
            ])
        else:
            exposures = exposures.with_columns([
                pl.col("mapped_parent_facility").alias("parent_facility_reference"),
            ])

        exposures = exposures.with_columns([
            pl.col("parent_facility_reference").is_not_null().alias("exposure_has_parent"),
        ])

        # Resolve root_facility_reference and facility_hierarchy_depth using root lookup
        if facility_root_lookup.head(1).collect().height > 0:
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
        else:
            exposures = exposures.with_columns([
                pl.when(pl.col("parent_facility_reference").is_not_null())
                .then(pl.col("parent_facility_reference"))
                .otherwise(pl.lit(None).cast(pl.String))
                .alias("root_facility_reference"),
                pl.when(pl.col("parent_facility_reference").is_not_null())
                .then(pl.lit(1).cast(pl.Int8))
                .otherwise(pl.lit(0).cast(pl.Int8))
                .alias("facility_hierarchy_depth"),
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

        all_members = pl.concat(
            [lending_groups, parent_as_member], how="vertical"
        ).unique(subset=["member_counterparty_reference"], keep="first")

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
            # Per CRR Article 147, "total amount owed" = drawn amount only (not undrawn)
            pl.col("residential_collateral_value").fill_null(0.0),
            pl.col("exposure_for_retail_threshold").fill_null(
                pl.col("drawn_amount").clip(lower_bound=0.0)
            ),
        ])

        # Calculate totals per lending group
        # - total_exposure: Raw sum (for reference/audit)
        # - adjusted_exposure: Sum excluding residential property (for retail threshold)
        lending_group_totals = exposures_with_group.filter(
            pl.col("lending_group_reference").is_not_null()
        ).group_by("lending_group_reference").agg([
            pl.col("drawn_amount").clip(lower_bound=0.0).sum().alias("total_drawn"),
            pl.col("nominal_amount").sum().alias("total_nominal"),
            (pl.col("drawn_amount").clip(lower_bound=0.0) + pl.col("nominal_amount")).sum().alias("total_exposure"),
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
        if not self._is_valid_optional_data(collateral, required_cols):
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

    def _calculate_residential_property_coverage(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame | None,
    ) -> pl.LazyFrame:
        """
        Calculate property collateral coverage per exposure.

        Calculates two separate values:
        1. residential_collateral_value: For CRR Art. 123(c) retail threshold exclusion
           (only residential property counts for threshold exclusion)
        2. property_collateral_value: For retail_mortgage classification
           (both residential AND commercial property qualify for mortgage treatment)

        Per CRR Art. 123(c) and Basel 3.1 CRE20.65, exposures fully and completely
        secured by residential property (assigned to SA residential property class)
        should be excluded from the EUR 1m retail threshold aggregation.

        For retail classification (CRE30.17-18), exposures secured by ANY immovable
        property (residential or commercial) are treated as retail mortgages with
        fixed 0.15 correlation, not retail other with PD-dependent correlation.

        Supports three levels of collateral linking based on beneficiary_type:
        1. Direct (exposure/loan): beneficiary_reference matches exposure_reference
        2. Facility: beneficiary_reference matches parent_facility_reference
        3. Counterparty: beneficiary_reference matches counterparty_reference

        For facility/counterparty level collateral, values are allocated proportionally
        across exposures based on their share of total exposure amount.

        Args:
            exposures: Unified exposures with exposure_reference
            collateral: Collateral data with property_type and market_value

        Returns:
            LazyFrame with columns:
            - exposure_reference: The exposure identifier
            - residential_collateral_value: Value of residential RE (for threshold exclusion)
            - property_collateral_value: Value of all RE (residential + commercial)
            - exposure_for_retail_threshold: Exposure amount minus residential coverage
        """
        # Get exposure amounts with linkage keys for capping and allocation
        # Per CRR Article 147, "total amount owed" = drawn amount only (not undrawn commitments)
        exposure_amounts = exposures.select([
            pl.col("exposure_reference"),
            pl.col("counterparty_reference"),
            pl.col("parent_facility_reference"),
            pl.col("drawn_amount").clip(lower_bound=0.0).alias("total_exposure_amount"),
        ])

        # Check if collateral is valid for property coverage calculation
        # Requires beneficiary_reference, collateral_type, market_value, and property_type
        required_cols = {"beneficiary_reference", "collateral_type", "market_value", "property_type"}
        if not self._is_valid_optional_data(collateral, required_cols):
            # No valid collateral data, return exposures with zero coverage
            return exposure_amounts.select([
                pl.col("exposure_reference"),
                pl.lit(0.0).alias("residential_collateral_value"),
                pl.lit(0.0).alias("property_collateral_value"),
                pl.col("total_exposure_amount").alias("exposure_for_retail_threshold"),
            ])

        # Check if beneficiary_type column exists for multi-level linking
        collateral_schema = collateral.collect_schema()
        has_beneficiary_type = "beneficiary_type" in collateral_schema.names()

        # Filter for residential property collateral only (for threshold exclusion)
        # Residential property = collateral_type is 'real_estate' AND property_type is 'residential'
        residential_collateral = collateral.filter(
            (pl.col("collateral_type").str.to_lowercase() == "real_estate") &
            (pl.col("property_type").str.to_lowercase() == "residential")
        )

        # Filter for ALL property collateral (residential + commercial) for mortgage classification
        # Property collateral = collateral_type is 'real_estate' (any property_type)
        all_property_collateral = collateral.filter(
            pl.col("collateral_type").str.to_lowercase() == "real_estate"
        )

        if not has_beneficiary_type:
            # Legacy behavior: assume direct exposure linking only
            residential_by_exposure = residential_collateral.group_by("beneficiary_reference").agg([
                pl.col("market_value").sum().alias("residential_collateral_value"),
            ])
            property_by_exposure = all_property_collateral.group_by("beneficiary_reference").agg([
                pl.col("market_value").sum().alias("property_collateral_value"),
            ])

            result = exposure_amounts.join(
                residential_by_exposure,
                left_on="exposure_reference",
                right_on="beneficiary_reference",
                how="left",
            ).join(
                property_by_exposure,
                left_on="exposure_reference",
                right_on="beneficiary_reference",
                how="left",
            )
        else:
            # Multi-level linking: handle direct, facility, and counterparty levels
            result = self._aggregate_property_collateral_multi_level(
                exposure_amounts,
                residential_collateral,
                all_property_collateral,
            )

        # Fill nulls with 0 and cap at exposure amount
        result = result.with_columns([
            pl.col("residential_collateral_value").fill_null(0.0),
            pl.col("property_collateral_value").fill_null(0.0),
        ]).with_columns([
            # Cap residential coverage at exposure amount (can't exclude more than exposure)
            pl.when(pl.col("residential_collateral_value") > pl.col("total_exposure_amount"))
            .then(pl.col("total_exposure_amount"))
            .otherwise(pl.col("residential_collateral_value"))
            .alias("residential_collateral_value"),
            # Cap property coverage at exposure amount
            pl.when(pl.col("property_collateral_value") > pl.col("total_exposure_amount"))
            .then(pl.col("total_exposure_amount"))
            .otherwise(pl.col("property_collateral_value"))
            .alias("property_collateral_value"),
        ]).with_columns([
            # Calculate exposure for retail threshold = exposure - residential coverage
            # Note: Only RESIDENTIAL property is excluded from threshold, not commercial
            (pl.col("total_exposure_amount") - pl.col("residential_collateral_value"))
            .alias("exposure_for_retail_threshold"),
        ])

        # Add has_facility_property_collateral flag if available
        # (it will be added by _aggregate_property_collateral_multi_level)
        schema_names = set(result.collect_schema().names())
        output_cols = [
            "exposure_reference",
            "residential_collateral_value",
            "property_collateral_value",
            "exposure_for_retail_threshold",
        ]
        if "has_facility_property_collateral" in schema_names:
            output_cols.append("has_facility_property_collateral")
        else:
            # For legacy non-multi-level case, derive from property_collateral_value
            result = result.with_columns([
                (pl.col("property_collateral_value") > 0).alias("has_facility_property_collateral"),
            ])
            output_cols.append("has_facility_property_collateral")

        return result.select(output_cols)

    def _aggregate_property_collateral_multi_level(
        self,
        exposure_amounts: pl.LazyFrame,
        residential_collateral: pl.LazyFrame,
        all_property_collateral: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Aggregate property collateral values across direct, facility, and counterparty levels.

        For facility/counterparty level collateral, values are allocated proportionally
        across exposures based on their share of total exposure amount at that level.

        Args:
            exposure_amounts: Exposures with exposure_reference, counterparty_reference,
                            parent_facility_reference, and total_exposure_amount
            residential_collateral: Filtered residential property collateral
            all_property_collateral: All property collateral (residential + commercial)

        Returns:
            LazyFrame with exposure_reference, residential_collateral_value,
            property_collateral_value, and total_exposure_amount
        """
        # Helper to aggregate collateral by beneficiary type and level
        def aggregate_by_level(
            coll: pl.LazyFrame,
            level: str,
            value_alias: str,
        ) -> pl.LazyFrame:
            """Aggregate collateral values for a specific beneficiary level."""
            level_filter = ["exposure", "loan"] if level == "direct" else [level]
            return coll.filter(
                pl.col("beneficiary_type").str.to_lowercase().is_in(level_filter)
            ).group_by("beneficiary_reference").agg([
                pl.col("market_value").sum().alias(value_alias),
            ])

        # Aggregate residential collateral at each level
        res_direct = aggregate_by_level(residential_collateral, "direct", "res_direct")
        res_facility = aggregate_by_level(residential_collateral, "facility", "res_facility")
        res_counterparty = aggregate_by_level(residential_collateral, "counterparty", "res_cp")

        # Aggregate all property collateral at each level
        prop_direct = aggregate_by_level(all_property_collateral, "direct", "prop_direct")
        prop_facility = aggregate_by_level(all_property_collateral, "facility", "prop_facility")
        prop_counterparty = aggregate_by_level(all_property_collateral, "counterparty", "prop_cp")

        # Calculate allocation weights for facility-level collateral
        # (exposure's share of total exposure under that facility)
        facility_totals = exposure_amounts.group_by("parent_facility_reference").agg([
            pl.col("total_exposure_amount").sum().alias("facility_total"),
        ])

        # Calculate allocation weights for counterparty-level collateral
        # (exposure's share of total exposure for that counterparty)
        counterparty_totals = exposure_amounts.group_by("counterparty_reference").agg([
            pl.col("total_exposure_amount").sum().alias("cp_total"),
        ])

        # Join all levels of collateral to exposures
        result = exposure_amounts.join(
            res_direct,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        ).join(
            prop_direct,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        ).join(
            res_facility,
            left_on="parent_facility_reference",
            right_on="beneficiary_reference",
            how="left",
        ).join(
            prop_facility,
            left_on="parent_facility_reference",
            right_on="beneficiary_reference",
            how="left",
        ).join(
            facility_totals,
            on="parent_facility_reference",
            how="left",
        ).join(
            res_counterparty,
            left_on="counterparty_reference",
            right_on="beneficiary_reference",
            how="left",
        ).join(
            prop_counterparty,
            left_on="counterparty_reference",
            right_on="beneficiary_reference",
            how="left",
        ).join(
            counterparty_totals,
            on="counterparty_reference",
            how="left",
        )

        # Calculate pro-rata allocation weights
        result = result.with_columns([
            # Facility allocation weight (handle division by zero)
            pl.when(pl.col("facility_total") > 0)
            .then(pl.col("total_exposure_amount") / pl.col("facility_total"))
            .otherwise(pl.lit(0.0))
            .alias("facility_weight"),
            # Counterparty allocation weight (handle division by zero)
            pl.when(pl.col("cp_total") > 0)
            .then(pl.col("total_exposure_amount") / pl.col("cp_total"))
            .otherwise(pl.lit(0.0))
            .alias("cp_weight"),
        ])

        # Combine values from all levels with pro-rata allocation
        result = result.with_columns([
            # Residential: direct + (facility * weight) + (counterparty * weight)
            (
                pl.col("res_direct").fill_null(0.0) +
                (pl.col("res_facility").fill_null(0.0) * pl.col("facility_weight")) +
                (pl.col("res_cp").fill_null(0.0) * pl.col("cp_weight"))
            ).alias("residential_collateral_value"),
            # Property: direct + (facility * weight) + (counterparty * weight)
            (
                pl.col("prop_direct").fill_null(0.0) +
                (pl.col("prop_facility").fill_null(0.0) * pl.col("facility_weight")) +
                (pl.col("prop_cp").fill_null(0.0) * pl.col("cp_weight"))
            ).alias("property_collateral_value"),
            # Boolean flag: does the exposure or its parent facility have property collateral?
            # Used for mortgage classification of undrawn exposures (which have 0 drawn_amount)
            (
                (pl.col("prop_direct").fill_null(0.0) > 0) |
                (pl.col("prop_facility").fill_null(0.0) > 0) |
                (pl.col("prop_cp").fill_null(0.0) > 0)
            ).alias("has_facility_property_collateral"),
        ])

        # Drop intermediate columns
        return result.select([
            "exposure_reference",
            "total_exposure_amount",
            "residential_collateral_value",
            "property_collateral_value",
            "has_facility_property_collateral",
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

        all_members = pl.concat(
            [lending_groups, parent_as_member], how="vertical"
        ).unique(subset=["member_counterparty_reference"], keep="first")

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

        # Join property coverage per exposure (for audit trail and mortgage classification)
        # Dynamically select columns that exist in residential_coverage
        res_coverage_schema = set(residential_coverage.collect_schema().names())
        res_select_cols = [
            pl.col("exposure_reference").alias("_res_exp_ref"),
            pl.col("residential_collateral_value"),
            pl.col("property_collateral_value"),
            pl.col("exposure_for_retail_threshold"),
        ]
        if "has_facility_property_collateral" in res_coverage_schema:
            res_select_cols.append(pl.col("has_facility_property_collateral"))

        exposures = exposures.join(
            residential_coverage.select(res_select_cols),
            left_on="exposure_reference",
            right_on="_res_exp_ref",
            how="left",
        )

        # Fill nulls with 0 for non-grouped exposures and exposures without property coverage
        # Per CRR Article 147, "total amount owed" = drawn amount only (not undrawn)
        fill_null_exprs = [
            pl.col("lending_group_total_exposure").fill_null(0.0),
            pl.col("lending_group_adjusted_exposure").fill_null(0.0),
            pl.col("residential_collateral_value").fill_null(0.0),
            pl.col("property_collateral_value").fill_null(0.0),
            pl.col("exposure_for_retail_threshold").fill_null(
                pl.col("drawn_amount").clip(lower_bound=0.0)
            ),
        ]
        # Add has_facility_property_collateral if it exists
        exp_schema = set(exposures.collect_schema().names())
        if "has_facility_property_collateral" in exp_schema:
            fill_null_exprs.append(
                pl.col("has_facility_property_collateral").fill_null(False)
            )
        else:
            # Derive from property_collateral_value if not available
            fill_null_exprs.append(
                (pl.col("property_collateral_value").fill_null(0.0) > 0).alias("has_facility_property_collateral")
            )
        exposures = exposures.with_columns(fill_null_exprs)

        return exposures


def create_hierarchy_resolver() -> HierarchyResolver:
    """
    Create a hierarchy resolver instance.

    Returns:
        HierarchyResolver ready for use
    """
    return HierarchyResolver()
