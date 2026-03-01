"""
Polars LazyFrame namespaces for result aggregation.

Provides fluent API for combining and summarizing RWA results:
- `lf.aggregator.combine_approach_results(sa, irb, slotting)` - Combine results
- `lf.aggregator.apply_output_floor(sa_results, config)` - Apply Basel 3.1 output floor
- `lf.aggregator.generate_summary_by_class()` - Summarize by exposure class
- `lf.aggregator.generate_summary_by_approach()` - Summarize by approach

Usage:
    import polars as pl
    from rwa_calc.contracts.config import CalculationConfig
    import rwa_calc.engine.aggregator_namespace  # Register namespace

    config = CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))
    result = (combined_results
        .aggregator.apply_output_floor(sa_results, config)
        .aggregator.calculate_floor_impact()
    )

References:
- CRE99.1-8: Output floor (Basel 3.1)
- PS9/24 Ch.12: PRA output floor implementation
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# LAZYFRAME NAMESPACE
# =============================================================================


@pl.api.register_lazyframe_namespace("aggregator")
class AggregatorLazyFrame:
    """
    Result aggregation namespace for Polars LazyFrames.

    Provides fluent API for combining and summarizing RWA results.

    Example:
        result = (combined_results
            .aggregator.apply_output_floor(sa_results, config)
            .aggregator.generate_summary_by_class()
        )
    """

    def __init__(self, lf: pl.LazyFrame) -> None:
        self._lf = lf

    # =========================================================================
    # RESULT COMBINATION METHODS
    # =========================================================================

    def combine_approach_results(
        self,
        sa: pl.LazyFrame | None = None,
        irb: pl.LazyFrame | None = None,
        slotting: pl.LazyFrame | None = None,
    ) -> pl.LazyFrame:
        """
        Combine SA, IRB, and Slotting results into unified output.

        Args:
            sa: SA calculation results
            irb: IRB calculation results
            slotting: Slotting calculation results

        Returns:
            Combined LazyFrame with all results
        """
        frames = []

        if sa is not None:
            sa_prepared = sa.with_columns(
                [
                    pl.lit("SA").alias("approach_applied"),
                ]
            )
            # Normalize RWA column
            sa_schema = sa_prepared.collect_schema()
            if "rwa_post_factor" in sa_schema.names():
                sa_prepared = sa_prepared.with_columns(
                    [
                        pl.col("rwa_post_factor").alias("rwa_final"),
                    ]
                )
            elif "rwa" in sa_schema.names():
                sa_prepared = sa_prepared.with_columns(
                    [
                        pl.col("rwa").alias("rwa_final"),
                    ]
                )
            frames.append(sa_prepared)

        if irb is not None:
            irb_prepared = irb
            irb_schema = irb_prepared.collect_schema()
            irb_cols = irb_schema.names()
            # Set approach if not present
            if "approach_applied" not in irb_cols:
                # Determine base approach expression
                if "approach" in irb_cols:
                    base_approach_expr = pl.col("approach")
                else:
                    base_approach_expr = pl.lit("FIRB")

                # Post-CRM: fully SA-guaranteed IRB exposures report as "standardised"
                has_guarantee_cols = (
                    "guarantor_approach" in irb_cols and "guarantee_ratio" in irb_cols
                )
                if has_guarantee_cols:
                    approach_expr = (
                        pl.when(
                            (pl.col("guarantor_approach") == "sa")
                            & (pl.col("guarantee_ratio") >= 1.0)
                        )
                        .then(pl.lit("standardised"))
                        .otherwise(base_approach_expr)
                    )
                else:
                    approach_expr = base_approach_expr

                irb_prepared = irb_prepared.with_columns(
                    [
                        approach_expr.alias("approach_applied"),
                    ]
                )
            # Normalize RWA column
            if "rwa_final" not in irb_schema.names() and "rwa" in irb_schema.names():
                irb_prepared = irb_prepared.with_columns(
                    [
                        pl.col("rwa").alias("rwa_final"),
                    ]
                )
            frames.append(irb_prepared)

        if slotting is not None:
            slotting_prepared = slotting.with_columns(
                [
                    pl.lit("SLOTTING").alias("approach_applied"),
                ]
            )
            slotting_schema = slotting_prepared.collect_schema()
            if "rwa_final" not in slotting_schema.names() and "rwa" in slotting_schema.names():
                slotting_prepared = slotting_prepared.with_columns(
                    [
                        pl.col("rwa").alias("rwa_final"),
                    ]
                )
            frames.append(slotting_prepared)

        if not frames:
            return self._lf

        # Combine all frames
        if len(frames) == 1:
            return frames[0]

        return pl.concat(frames, how="diagonal_relaxed")

    # =========================================================================
    # OUTPUT FLOOR METHODS
    # =========================================================================

    def apply_output_floor(
        self,
        sa_results: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply output floor to IRB RWA (Basel 3.1 only).

        Final RWA = max(IRB RWA, SA RWA x floor_percentage)

        Args:
            sa_results: Equivalent SA RWA for floor comparison
            config: Calculation configuration

        Returns:
            LazyFrame with floor-adjusted RWA
        """
        if not config.output_floor.enabled:
            return self._lf

        # Get floor percentage
        floor_pct = float(config.output_floor.get_floor_percentage(config.reporting_date))

        schema = self._lf.collect_schema()
        sa_schema = sa_results.collect_schema()

        # Determine SA RWA column
        if "rwa_post_factor" in sa_schema.names():
            sa_rwa_col = "rwa_post_factor"
        elif "rwa" in sa_schema.names():
            sa_rwa_col = "rwa"
        else:
            return self._lf

        # Prepare SA results for join
        sa_rwa = sa_results.select(
            [
                pl.col("exposure_reference"),
                pl.col(sa_rwa_col).alias("sa_rwa"),
            ]
        )

        # Store pre-floor RWA
        rwa_col = "rwa_final" if "rwa_final" in schema.names() else "rwa"

        result = self._lf.with_columns(
            [
                pl.col(rwa_col).alias("rwa_pre_floor"),
            ]
        )

        # Join with SA for floor comparison
        result = result.join(
            sa_rwa,
            on="exposure_reference",
            how="left",
        )

        # IRB approaches for floor application
        irb_approaches = ["FIRB", "AIRB", "IRB", "foundation_irb", "advanced_irb"]

        # Calculate floor RWA and apply
        result = (
            result.with_columns(
                [
                    (pl.col("sa_rwa").fill_null(0.0) * floor_pct).alias("floor_rwa"),
                    pl.lit(floor_pct).alias("output_floor_pct"),
                ]
            )
            .with_columns(
                [
                    # Is floor binding? (only for IRB)
                    pl.when(
                        pl.col("approach_applied")
                        .str.to_lowercase()
                        .is_in([a.lower() for a in irb_approaches])
                    )
                    .then(pl.col("floor_rwa") > pl.col("rwa_pre_floor"))
                    .otherwise(pl.lit(False))
                    .alias("is_floor_binding"),
                ]
            )
            .with_columns(
                [
                    # Floor impact
                    pl.when(pl.col("is_floor_binding"))
                    .then(pl.col("floor_rwa") - pl.col("rwa_pre_floor"))
                    .otherwise(pl.lit(0.0))
                    .alias("floor_impact_rwa"),
                ]
            )
            .with_columns(
                [
                    # Apply floor to final RWA for IRB
                    pl.when(
                        pl.col("approach_applied")
                        .str.to_lowercase()
                        .is_in([a.lower() for a in irb_approaches])
                    )
                    .then(pl.max_horizontal(pl.col("rwa_pre_floor"), pl.col("floor_rwa")))
                    .otherwise(pl.col("rwa_pre_floor"))
                    .alias("rwa_final"),
                ]
            )
        )

        return result

    def calculate_floor_impact(self) -> pl.LazyFrame:
        """
        Calculate floor impact analysis.

        Requires apply_output_floor to have been called.

        Returns:
            LazyFrame with floor impact analysis
        """
        schema = self._lf.collect_schema()

        if "floor_rwa" not in schema.names():
            return self._lf

        return self._lf.with_columns(
            [
                # Floor impact as percentage of pre-floor RWA
                pl.when(pl.col("rwa_pre_floor") > 0)
                .then(pl.col("floor_impact_rwa") / pl.col("rwa_pre_floor") * 100)
                .otherwise(pl.lit(0.0))
                .alias("floor_impact_pct"),
                # Binding floor indicator
                (pl.col("is_floor_binding")).cast(pl.Int8).alias("floor_binding_flag"),
            ]
        )

    # =========================================================================
    # SUMMARY GENERATION METHODS
    # =========================================================================

    def generate_summary_by_class(self) -> pl.LazyFrame:
        """
        Generate RWA summary by exposure class.

        Aggregates:
        - Total EAD
        - Total RWA
        - Average risk weight
        - Exposure count
        - Floor binding count (if applicable)

        Returns:
            LazyFrame with summary by exposure class
        """
        schema = self._lf.collect_schema()

        # Build aggregation expressions
        agg_exprs = [
            pl.len().alias("exposure_count"),
        ]

        if "ead_final" in schema.names():
            agg_exprs.append(pl.col("ead_final").sum().alias("total_ead"))

        if "rwa_final" in schema.names():
            agg_exprs.append(pl.col("rwa_final").sum().alias("total_rwa"))
        elif "rwa" in schema.names():
            agg_exprs.append(pl.col("rwa").sum().alias("total_rwa"))

        if "risk_weight" in schema.names() and "ead_final" in schema.names():
            agg_exprs.append(
                (pl.col("risk_weight") * pl.col("ead_final")).sum().alias("_weighted_rw"),
            )

        if "is_floor_binding" in schema.names():
            agg_exprs.append(
                pl.col("is_floor_binding").sum().cast(pl.UInt32).alias("floor_binding_count"),
            )

        # Group by exposure class
        if "exposure_class" in schema.names():
            summary = self._lf.group_by("exposure_class").agg(agg_exprs)
        else:
            summary = self._lf.select(agg_exprs).with_columns(
                [
                    pl.lit("ALL").alias("exposure_class"),
                ]
            )

        # Calculate average risk weight
        summary_schema = summary.collect_schema()
        if "_weighted_rw" in summary_schema.names() and "total_ead" in summary_schema.names():
            summary = summary.with_columns(
                [
                    pl.when(pl.col("total_ead") > 0)
                    .then(pl.col("_weighted_rw") / pl.col("total_ead"))
                    .otherwise(pl.lit(0.0))
                    .alias("avg_risk_weight"),
                ]
            ).drop("_weighted_rw")

        return summary

    def generate_summary_by_approach(self) -> pl.LazyFrame:
        """
        Generate RWA summary by calculation approach.

        Aggregates:
        - Total EAD
        - Total RWA
        - Exposure count
        - Floor impact (if applicable)

        Returns:
            LazyFrame with summary by approach
        """
        schema = self._lf.collect_schema()

        # Build aggregation expressions
        agg_exprs = [
            pl.len().alias("exposure_count"),
        ]

        if "ead_final" in schema.names():
            agg_exprs.append(pl.col("ead_final").sum().alias("total_ead"))

        if "rwa_final" in schema.names():
            agg_exprs.append(pl.col("rwa_final").sum().alias("total_rwa"))
        elif "rwa" in schema.names():
            agg_exprs.append(pl.col("rwa").sum().alias("total_rwa"))

        if "floor_impact_rwa" in schema.names():
            agg_exprs.append(
                pl.col("floor_impact_rwa").sum().alias("total_floor_impact"),
            )

        if "expected_loss" in schema.names():
            agg_exprs.append(
                pl.col("expected_loss").sum().alias("total_expected_loss"),
            )

        # Group by approach
        if "approach_applied" in schema.names():
            return self._lf.group_by("approach_applied").agg(agg_exprs)
        else:
            return self._lf.select(agg_exprs).with_columns(
                [
                    pl.lit("ALL").alias("approach_applied"),
                ]
            )

    def generate_supporting_factor_impact(self) -> pl.LazyFrame:
        """
        Generate supporting factor impact analysis.

        Returns:
            LazyFrame with supporting factor impact per exposure
        """
        schema = self._lf.collect_schema()

        if "supporting_factor" not in schema.names() or "rwa_pre_factor" not in schema.names():
            return self._lf

        return self._lf.select(
            [
                pl.col("exposure_reference"),
                pl.col("exposure_class")
                if "exposure_class" in schema.names()
                else pl.lit(None).alias("exposure_class"),
                pl.col("is_sme") if "is_sme" in schema.names() else pl.lit(False).alias("is_sme"),
                pl.col("is_infrastructure")
                if "is_infrastructure" in schema.names()
                else pl.lit(False).alias("is_infrastructure"),
                pl.col("ead_final")
                if "ead_final" in schema.names()
                else pl.lit(0.0).alias("ead_final"),
                pl.col("supporting_factor"),
                pl.col("rwa_pre_factor"),
                pl.col("rwa_post_factor")
                if "rwa_post_factor" in schema.names()
                else pl.col("rwa_final").alias("rwa_post_factor"),
                (pl.col("rwa_pre_factor") - pl.col("rwa_post_factor")).alias(
                    "supporting_factor_impact"
                )
                if "rwa_post_factor" in schema.names()
                else (pl.col("rwa_pre_factor") - pl.col("rwa_final")).alias(
                    "supporting_factor_impact"
                ),
            ]
        ).filter(pl.col("supporting_factor") < 1.0)
