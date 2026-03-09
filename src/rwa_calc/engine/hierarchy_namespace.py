"""
Polars LazyFrame namespaces for hierarchy resolution.

Provides fluent API for counterparty and exposure hierarchy operations:
- `lf.hierarchy.resolve_ultimate_parent(org_mappings)` - Resolve ultimate parents
- `lf.hierarchy.inherit_ratings(ratings, ultimate_parents)` - Inherit ratings from parents
- `lf.hierarchy.calculate_lending_group_totals(lending_mappings)` - Calculate group totals

Usage:
    import polars as pl
    import rwa_calc.engine.hierarchy_namespace  # Register namespace

    result = (counterparties
        .hierarchy.resolve_ultimate_parent(org_mappings, max_depth=10)
        .hierarchy.inherit_ratings(ratings, ultimate_parents)
    )

Note: These are convenience methods that delegate to the HierarchyResolver
for complex multi-step operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.engine.hierarchy import _resolve_graph_eager

if TYPE_CHECKING:
    pass


# =============================================================================
# LAZYFRAME NAMESPACE
# =============================================================================


@pl.api.register_lazyframe_namespace("hierarchy")
class HierarchyLazyFrame:
    """
    Hierarchy resolution namespace for Polars LazyFrames.

    Provides fluent API for counterparty and exposure hierarchy operations.

    Example:
        result = (counterparties
            .hierarchy.resolve_ultimate_parent(org_mappings, max_depth=10)
            .hierarchy.calculate_hierarchy_depth()
        )
    """

    def __init__(self, lf: pl.LazyFrame) -> None:
        self._lf = lf

    # =========================================================================
    # PARENT RESOLUTION METHODS
    # =========================================================================

    def resolve_ultimate_parent(
        self,
        org_mappings: pl.LazyFrame,
        max_depth: int = 10,
    ) -> pl.LazyFrame:
        """
        Resolve ultimate parent for each entity using eager graph traversal.

        Collects edge data, resolves the graph via dict traversal, and joins
        the resolved lookup back onto the calling LazyFrame.

        Args:
            org_mappings: LazyFrame with child_counterparty_reference and parent_counterparty_reference
            max_depth: Maximum hierarchy depth to traverse

        Returns:
            LazyFrame with ultimate_parent_reference and hierarchy_depth columns
        """
        schema_names = self._lf.collect_schema().names()

        # Get entity reference column
        if "counterparty_reference" in schema_names:
            entity_col = "counterparty_reference"
        elif "exposure_reference" in schema_names:
            entity_col = "exposure_reference"
        else:
            raise ValueError("No reference column found")

        # Collect edge data (small) and resolve graph eagerly
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

        # Build lookup LazyFrame
        lookup = resolved.rename(
            {
                "entity": "_lookup_entity",
                "root": "_lookup_root",
                "depth": "_lookup_depth",
            }
        ).lazy()

        # Left join resolved lookup back onto the calling LazyFrame
        # Entities not in edge data are roots (map to self, depth 0)
        return (
            self._lf.join(
                lookup,
                left_on=entity_col,
                right_on="_lookup_entity",
                how="left",
            )
            .with_columns(
                [
                    pl.coalesce(
                        pl.col("_lookup_root"),
                        pl.col(entity_col),
                    ).alias("ultimate_parent_reference"),
                    pl.col("_lookup_depth").fill_null(0).alias("hierarchy_depth"),
                ]
            )
            .drop(["_lookup_root", "_lookup_depth"])
        )

    def calculate_hierarchy_depth(self) -> pl.LazyFrame:
        """
        Calculate hierarchy depth from existing parent columns.

        Requires ultimate_parent_reference to be already resolved.

        Returns:
            LazyFrame with hierarchy_depth column
        """
        schema_names = self._lf.collect_schema().names()

        if "hierarchy_depth" in schema_names:
            return self._lf

        # Determine reference column
        if "counterparty_reference" in schema_names:
            ref_col = "counterparty_reference"
        elif "exposure_reference" in schema_names:
            ref_col = "exposure_reference"
        else:
            return self._lf.with_columns([pl.lit(0).alias("hierarchy_depth")])

        # Calculate depth based on whether entity is its own ultimate parent
        return self._lf.with_columns(
            [
                pl.when(pl.col("ultimate_parent_reference") == pl.col(ref_col))
                .then(pl.lit(0))
                .otherwise(pl.lit(1))  # Simplified - actual depth needs traversal
                .alias("hierarchy_depth"),
            ]
        )

    # =========================================================================
    # RATING INHERITANCE METHODS
    # =========================================================================

    def inherit_ratings(
        self,
        ratings: pl.LazyFrame,
        ultimate_parents: pl.LazyFrame | None = None,
    ) -> pl.LazyFrame:
        """
        Inherit ratings from parent entities with dual per-type resolution.

        Resolves best internal and best external rating separately, then
        inherits each type independently from the ultimate parent.

        Args:
            ratings: LazyFrame with counterparty_reference, cqs, pd, rating_value,
                     rating_type, rating_agency, rating_date
            ultimate_parents: LazyFrame with counterparty_reference and
                              ultimate_parent_reference

        Returns:
            LazyFrame with per-type and derived rating columns
        """
        schema_names = self._lf.collect_schema().names()

        if "counterparty_reference" not in schema_names:
            return self._lf

        ref_col = "counterparty_reference"
        rating_schema_names = ratings.collect_schema().names()
        has_rating_type = "rating_type" in rating_schema_names

        if not has_rating_type:
            # Fallback: no rating_type column — treat all as external
            rating_cols = ["counterparty_reference"]
            for col in ["cqs", "pd", "rating_value", "rating_agency", "rating_date"]:
                if col in rating_schema_names:
                    rating_cols.append(col)

            first_ratings = ratings.select(rating_cols).unique(
                subset=["counterparty_reference"], keep="first"
            )
            result = self._lf.join(
                first_ratings.select(
                    [
                        pl.col("counterparty_reference").alias("rated_cp"),
                        *[pl.col(c) for c in rating_cols if c != "counterparty_reference"],
                    ]
                ),
                left_on=ref_col,
                right_on="rated_cp",
                how="left",
            )
            return result

        # Dual per-type resolution
        sort_cols = []
        if "rating_date" in rating_schema_names:
            sort_cols.append("rating_date")
        if "rating_reference" in rating_schema_names:
            sort_cols.append("rating_reference")

        # Best internal rating per counterparty
        internal_base = ratings.filter(pl.col("rating_type") == "internal")
        if sort_cols:
            internal_base = internal_base.sort(sort_cols, descending=[True] * len(sort_cols))
        best_internal = internal_base.group_by("counterparty_reference").first().select(
            [
                pl.col("counterparty_reference").alias("_int_cp"),
                *([pl.col("cqs").alias("internal_cqs")] if "cqs" in rating_schema_names else []),
                *([pl.col("pd").alias("internal_pd")] if "pd" in rating_schema_names else []),
                *(
                    [pl.col("rating_value").alias("internal_rating_value")]
                    if "rating_value" in rating_schema_names
                    else []
                ),
                *(
                    [pl.col("rating_agency").alias("internal_rating_agency")]
                    if "rating_agency" in rating_schema_names
                    else []
                ),
            ]
        )

        # Best external rating per counterparty
        external_base = ratings.filter(pl.col("rating_type") == "external")
        if sort_cols:
            external_base = external_base.sort(sort_cols, descending=[True] * len(sort_cols))
        best_external = external_base.group_by("counterparty_reference").first().select(
            [
                pl.col("counterparty_reference").alias("_ext_cp"),
                *([pl.col("cqs").alias("external_cqs")] if "cqs" in rating_schema_names else []),
                *(
                    [pl.col("rating_value").alias("external_rating_value")]
                    if "rating_value" in rating_schema_names
                    else []
                ),
                *(
                    [pl.col("rating_agency").alias("external_rating_agency")]
                    if "rating_agency" in rating_schema_names
                    else []
                ),
            ]
        )

        result = self._lf.join(
            best_internal, left_on=ref_col, right_on="_int_cp", how="left"
        )
        result = result.join(
            best_external, left_on=ref_col, right_on="_ext_cp", how="left"
        )

        # Derive convenience columns
        int_cols = best_internal.collect_schema().names()
        ext_cols = best_external.collect_schema().names()

        derive = []
        if "external_cqs" in ext_cols and "internal_cqs" in int_cols:
            derive.append(
                pl.coalesce(pl.col("external_cqs"), pl.col("internal_cqs")).alias("cqs")
            )
        elif "external_cqs" in ext_cols:
            derive.append(pl.col("external_cqs").alias("cqs"))
        elif "internal_cqs" in int_cols:
            derive.append(pl.col("internal_cqs").alias("cqs"))

        if "internal_pd" in int_cols:
            derive.append(pl.col("internal_pd").alias("pd"))

        if derive:
            result = result.with_columns(derive)

        # Parent inheritance
        if ultimate_parents is not None:
            result = result.join(
                ultimate_parents.select(
                    [
                        pl.col("counterparty_reference").alias("_up_cp"),
                        pl.col("ultimate_parent_reference"),
                    ]
                ),
                left_on=ref_col,
                right_on="_up_cp",
                how="left",
            )

            # Parent internal
            parent_int_cols = [
                pl.col(c).alias(f"parent_{c}") for c in int_cols if c != "_int_cp"
            ]
            if parent_int_cols:
                parent_internal = best_internal.select(
                    [pl.col("_int_cp").alias("_p_int_cp"), *parent_int_cols]
                )
                result = result.join(
                    parent_internal,
                    left_on="ultimate_parent_reference",
                    right_on="_p_int_cp",
                    how="left",
                )

            # Parent external
            parent_ext_cols = [
                pl.col(c).alias(f"parent_{c}") for c in ext_cols if c != "_ext_cp"
            ]
            if parent_ext_cols:
                parent_external = best_external.select(
                    [pl.col("_ext_cp").alias("_p_ext_cp"), *parent_ext_cols]
                )
                result = result.join(
                    parent_external,
                    left_on="ultimate_parent_reference",
                    right_on="_p_ext_cp",
                    how="left",
                )

            # Coalesce own → parent per type
            coalesce_pairs = []
            for col_name in int_cols:
                if col_name != "_int_cp":
                    coalesce_pairs.append(
                        pl.coalesce(pl.col(col_name), pl.col(f"parent_{col_name}")).alias(
                            col_name
                        )
                    )
            for col_name in ext_cols:
                if col_name != "_ext_cp":
                    coalesce_pairs.append(
                        pl.coalesce(pl.col(col_name), pl.col(f"parent_{col_name}")).alias(
                            col_name
                        )
                    )
            if coalesce_pairs:
                result = result.with_columns(coalesce_pairs)

            # Re-derive convenience columns after inheritance
            re_derive = []
            if "external_cqs" in ext_cols and "internal_cqs" in int_cols:
                re_derive.append(
                    pl.coalesce(pl.col("external_cqs"), pl.col("internal_cqs")).alias("cqs")
                )
            elif "external_cqs" in ext_cols:
                re_derive.append(pl.col("external_cqs").alias("cqs"))
            elif "internal_cqs" in int_cols:
                re_derive.append(pl.col("internal_cqs").alias("cqs"))
            if "internal_pd" in int_cols:
                re_derive.append(pl.col("internal_pd").alias("pd"))
            if re_derive:
                result = result.with_columns(re_derive)

            # Inheritance flags
            has_own_internal = (
                pl.col("internal_cqs").is_not_null()
                if "internal_cqs" in int_cols
                else pl.lit(False)
            ) | (
                pl.col("internal_pd").is_not_null()
                if "internal_pd" in int_cols
                else pl.lit(False)
            )
            has_own_external = (
                pl.col("external_cqs").is_not_null()
                if "external_cqs" in ext_cols
                else pl.lit(False)
            )
            has_any_own = has_own_internal | has_own_external

            result = result.with_columns(
                [
                    pl.when(has_any_own)
                    .then(pl.lit(False))
                    .otherwise(pl.lit(True))
                    .alias("rating_inherited"),
                    pl.when(has_any_own)
                    .then(pl.lit("own_rating"))
                    .otherwise(pl.lit("parent_rating"))
                    .alias("inheritance_reason"),
                ]
            )

        return result

    def coalesce_ratings(self) -> pl.LazyFrame:
        """
        Coalesce own and parent ratings into effective rating columns.

        Requires inherit_ratings to be called first.

        Returns:
            LazyFrame with effective_* rating columns
        """
        schema_names = self._lf.collect_schema().names()

        columns_to_add = []

        if "cqs" in schema_names and "parent_cqs" in schema_names:
            columns_to_add.append(
                pl.coalesce(pl.col("cqs"), pl.col("parent_cqs")).alias("effective_cqs")
            )

        if "pd" in schema_names and "parent_pd" in schema_names:
            columns_to_add.append(
                pl.coalesce(pl.col("pd"), pl.col("parent_pd")).alias("effective_pd")
            )

        if columns_to_add:
            return self._lf.with_columns(columns_to_add)

        return self._lf

    # =========================================================================
    # LENDING GROUP METHODS
    # =========================================================================

    def calculate_lending_group_totals(
        self,
        lending_mappings: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Calculate total exposure by lending group.

        Args:
            lending_mappings: LazyFrame with parent_counterparty_reference (group) and child_counterparty_reference

        Returns:
            LazyFrame with lending group aggregations
        """
        schema_names = self._lf.collect_schema().names()

        # Build lending group membership
        lending_groups = lending_mappings.select(
            [
                pl.col("parent_counterparty_reference").alias("lending_group_reference"),
                pl.col("child_counterparty_reference").alias("member_counterparty_reference"),
            ]
        )

        # Include parent as member
        parent_as_member = lending_mappings.select(
            [
                pl.col("parent_counterparty_reference").alias("lending_group_reference"),
                pl.col("parent_counterparty_reference").alias("member_counterparty_reference"),
            ]
        ).unique()

        all_members = pl.concat([lending_groups, parent_as_member], how="vertical")

        # Join exposures to get lending group
        exposures_with_group = self._lf.join(
            all_members,
            left_on="counterparty_reference",
            right_on="member_counterparty_reference",
            how="left",
        )

        # Determine exposure amount expression (floor drawn_amount at 0)
        if "drawn_amount" in schema_names:
            amount_expr = pl.col("drawn_amount").clip(lower_bound=0.0)
        elif "ead_final" in schema_names:
            amount_expr = pl.col("ead_final")
        elif "ead" in schema_names:
            amount_expr = pl.col("ead")
        else:
            return self._lf.with_columns([pl.lit(0.0).alias("lending_group_total")])

        # Calculate totals per lending group
        lending_group_totals = (
            exposures_with_group.filter(pl.col("lending_group_reference").is_not_null())
            .group_by("lending_group_reference")
            .agg(
                [
                    amount_expr.sum().alias("total_exposure"),
                    pl.len().alias("exposure_count"),
                ]
            )
        )

        return lending_group_totals

    def add_lending_group_reference(
        self,
        lending_mappings: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Add lending group reference to exposures.

        Args:
            lending_mappings: LazyFrame with parent and child counterparty references

        Returns:
            LazyFrame with lending_group_reference column
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

        all_members = pl.concat([lending_groups, parent_as_member], how="vertical")

        return self._lf.join(
            all_members,
            left_on="counterparty_reference",
            right_on="member_counterparty_reference",
            how="left",
        )

    # =========================================================================
    # COLLATERAL LTV METHODS
    # =========================================================================

    def add_collateral_ltv(
        self,
        collateral: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Add LTV from collateral to exposures for real estate risk weights.

        Args:
            collateral: LazyFrame with beneficiary_reference and property_ltv

        Returns:
            LazyFrame with ltv column added
        """
        schema = self._lf.collect_schema()

        # Get reference column
        if "exposure_reference" in schema.names():
            ref_col = "exposure_reference"
        else:
            return self._lf

        # Check collateral has required columns
        coll_schema_names = collateral.collect_schema().names()
        if (
            "beneficiary_reference" not in coll_schema_names
            or "property_ltv" not in coll_schema_names
        ):
            return self._lf.with_columns([pl.lit(None).cast(pl.Float64).alias("ltv")])

        # Select LTV from collateral
        ltv_lookup = (
            collateral.select(
                [
                    pl.col("beneficiary_reference"),
                    pl.col("property_ltv").alias("ltv"),
                ]
            )
            .filter(pl.col("ltv").is_not_null())
            .unique(
                subset=["beneficiary_reference"],
                keep="first",
            )
        )

        return self._lf.join(
            ltv_lookup,
            left_on=ref_col,
            right_on="beneficiary_reference",
            how="left",
        )
