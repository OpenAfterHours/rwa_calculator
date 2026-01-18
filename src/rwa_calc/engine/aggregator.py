"""
Output Aggregator for RWA Calculations.

Combines SA, IRB, and Slotting results with:
- Output floor application (Basel 3.1 only)
- Supporting factor tracking (CRR only)
- Summary generation by exposure class and approach

Pipeline position:
    SACalculator/IRBCalculator/SlottingCalculator -> OutputAggregator -> Pipeline output

Key responsibilities:
- Combine SA and IRB results into unified output
- Apply output floor (Basel 3.1: max(IRB RWA, 72.5% × SA RWA))
- Track supporting factor impact (CRR only)
- Generate summary statistics by class and approach

References:
- CRE99.1-8: Output floor (Basel 3.1)
- PS9/24 Ch.12: PRA output floor implementation
- CRR Art. 501: SME supporting factor
- CRR Art. 501a: Infrastructure supporting factor
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import (
    AggregatedResultBundle,
    SAResultBundle,
    IRBResultBundle,
    SlottingResultBundle,
)
from rwa_calc.contracts.errors import (
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# Error Types
# =============================================================================


@dataclass
class AggregationError:
    """Error during result aggregation."""

    error_type: str
    message: str
    exposure_reference: str | None = None


# =============================================================================
# Output Aggregator Implementation
# =============================================================================


class OutputAggregator:
    """
    Aggregate final RWA results from all calculators.

    Implements OutputAggregatorProtocol for:
    - Combining SA, IRB, and Slotting results
    - Applying output floor (Basel 3.1)
    - Tracking supporting factor impact (CRR)
    - Generating summaries by exposure class and approach

    Usage:
        aggregator = OutputAggregator()
        result = aggregator.aggregate_with_audit(
            sa_bundle=sa_results,
            irb_bundle=irb_results,
            slotting_bundle=slotting_results,
            config=config,
        )
    """

    def __init__(self) -> None:
        """Initialize output aggregator."""
        pass

    # =========================================================================
    # Public API
    # =========================================================================

    def aggregate(
        self,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Aggregate SA and IRB results into final output.

        Args:
            sa_results: Standardised Approach calculations
            irb_results: IRB approach calculations
            config: Calculation configuration

        Returns:
            Combined LazyFrame with all calculations
        """
        return self._combine_results(
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=None,
            config=config,
        )

    def aggregate_with_audit(
        self,
        sa_bundle: SAResultBundle | None,
        irb_bundle: IRBResultBundle | None,
        slotting_bundle: SlottingResultBundle | None,
        config: CalculationConfig,
    ) -> AggregatedResultBundle:
        """
        Aggregate with full audit trail.

        Args:
            sa_bundle: SA calculation results bundle
            irb_bundle: IRB calculation results bundle
            slotting_bundle: Slotting calculation results bundle
            config: Calculation configuration

        Returns:
            AggregatedResultBundle with full audit trail
        """
        errors: list[AggregationError] = []

        # Get result frames from bundles
        sa_results = sa_bundle.results if sa_bundle else None
        irb_results = irb_bundle.results if irb_bundle else None
        slotting_results = slotting_bundle.results if slotting_bundle else None

        # Combine all results
        combined = self._combine_results(
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=slotting_results,
            config=config,
        )

        # Apply output floor (Basel 3.1 only)
        floor_impact = None
        if config.output_floor.enabled and irb_results is not None and sa_results is not None:
            combined, floor_impact = self._apply_floor_with_impact(
                combined,
                sa_results,
                config,
            )

        # Generate supporting factor impact (CRR only)
        supporting_factor_impact = None
        if config.supporting_factors.enabled and sa_results is not None:
            supporting_factor_impact = self._generate_supporting_factor_impact(sa_results)

        # Generate summaries
        summary_by_class = self._generate_summary_by_class(combined)
        summary_by_approach = self._generate_summary_by_approach(combined)

        # Collect all errors
        all_errors = list(errors)
        if sa_bundle:
            all_errors.extend(sa_bundle.errors)
        if irb_bundle:
            all_errors.extend(irb_bundle.errors)
        if slotting_bundle:
            all_errors.extend(slotting_bundle.errors)

        return AggregatedResultBundle(
            results=combined,
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=slotting_results,
            floor_impact=floor_impact,
            supporting_factor_impact=supporting_factor_impact,
            summary_by_class=summary_by_class,
            summary_by_approach=summary_by_approach,
            errors=all_errors,
        )

    def apply_output_floor(
        self,
        irb_rwa: pl.LazyFrame,
        sa_equivalent_rwa: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply output floor to IRB RWA (Basel 3.1 only).

        Final RWA = max(IRB RWA, SA RWA × floor_percentage)

        Args:
            irb_rwa: IRB RWA before floor
            sa_equivalent_rwa: Equivalent SA RWA for comparison
            config: Calculation configuration

        Returns:
            LazyFrame with floor-adjusted RWA
        """
        if not config.output_floor.enabled:
            return irb_rwa

        # Get floor percentage (supports transitional schedule)
        floor_pct = float(
            config.output_floor.get_floor_percentage(config.reporting_date)
        )

        # Join IRB and SA results on exposure_reference
        floored = irb_rwa.join(
            sa_equivalent_rwa.select([
                pl.col("exposure_reference"),
                pl.col("rwa_post_factor" if "rwa_post_factor" in sa_equivalent_rwa.collect_schema().names() else "rwa").alias("sa_rwa"),
            ]),
            on="exposure_reference",
            how="left",
        )

        # Get IRB RWA column name
        irb_rwa_col = "rwa" if "rwa" in floored.collect_schema().names() else "rwa_post_factor"

        # Apply floor
        floored = floored.with_columns([
            # Floor RWA = SA RWA × floor percentage
            (pl.col("sa_rwa").fill_null(0.0) * floor_pct).alias("floor_rwa"),
            pl.lit(floor_pct).alias("output_floor_pct"),
        ]).with_columns([
            # Is floor binding?
            (pl.col("floor_rwa") > pl.col(irb_rwa_col)).alias("is_floor_binding"),
            # Floor impact (additional RWA)
            pl.max_horizontal(
                pl.lit(0.0),
                pl.col("floor_rwa") - pl.col(irb_rwa_col),
            ).alias("floor_impact_rwa"),
        ]).with_columns([
            # Final RWA = max(IRB RWA, floor RWA)
            pl.max_horizontal(
                pl.col(irb_rwa_col),
                pl.col("floor_rwa"),
            ).alias("rwa_final"),
        ])

        return floored

    # =========================================================================
    # Private Methods - Result Combination
    # =========================================================================

    def _combine_results(
        self,
        sa_results: pl.LazyFrame | None,
        irb_results: pl.LazyFrame | None,
        slotting_results: pl.LazyFrame | None,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Combine SA, IRB, and Slotting results into a unified LazyFrame.

        Adds approach identification and standardizes column names.
        """
        frames = []

        if sa_results is not None and self._has_rows(sa_results):
            sa_prepared = self._prepare_sa_results(sa_results)
            frames.append(sa_prepared)

        if irb_results is not None and self._has_rows(irb_results):
            irb_prepared = self._prepare_irb_results(irb_results)
            frames.append(irb_prepared)

        if slotting_results is not None and self._has_rows(slotting_results):
            slotting_prepared = self._prepare_slotting_results(slotting_results)
            frames.append(slotting_prepared)

        if not frames:
            # Return empty frame with expected schema
            return self._create_empty_result_frame()

        # Combine all frames
        if len(frames) == 1:
            combined = frames[0]
        else:
            combined = pl.concat(frames, how="diagonal_relaxed")

        return combined

    def _has_rows(self, frame: pl.LazyFrame) -> bool:
        """Check if a LazyFrame has any rows (without full collect)."""
        try:
            schema = frame.collect_schema()
            # If no columns, assume empty
            if len(schema) == 0:
                return False
            # Check first row exists
            return frame.head(1).collect().height > 0
        except Exception:
            return False

    def _prepare_sa_results(self, sa_results: pl.LazyFrame) -> pl.LazyFrame:
        """Prepare SA results with standard columns."""
        schema = sa_results.collect_schema()

        # Determine RWA column
        rwa_col = "rwa_post_factor" if "rwa_post_factor" in schema.names() else "rwa"

        return sa_results.with_columns([
            pl.lit("SA").alias("approach_applied"),
            pl.col(rwa_col).alias("rwa_final"),
        ])

    def _prepare_irb_results(self, irb_results: pl.LazyFrame) -> pl.LazyFrame:
        """Prepare IRB results with standard columns."""
        schema = irb_results.collect_schema()

        # Determine approach column
        if "approach" in schema.names():
            approach_expr = pl.col("approach")
        else:
            approach_expr = pl.lit("FIRB")

        # Determine RWA column
        rwa_col = "rwa" if "rwa" in schema.names() else "rwa_post_factor"

        return irb_results.with_columns([
            approach_expr.alias("approach_applied"),
            pl.col(rwa_col).alias("rwa_final"),
        ])

    def _prepare_slotting_results(self, slotting_results: pl.LazyFrame) -> pl.LazyFrame:
        """Prepare Slotting results with standard columns."""
        schema = slotting_results.collect_schema()

        # Determine RWA column
        rwa_col = "rwa" if "rwa" in schema.names() else "rwa_post_factor"

        return slotting_results.with_columns([
            pl.lit("SLOTTING").alias("approach_applied"),
            pl.col(rwa_col).alias("rwa_final"),
        ])

    def _create_empty_result_frame(self) -> pl.LazyFrame:
        """Create empty result frame with expected schema."""
        return pl.LazyFrame({
            "exposure_reference": pl.Series([], dtype=pl.String),
            "approach_applied": pl.Series([], dtype=pl.String),
            "exposure_class": pl.Series([], dtype=pl.String),
            "ead_final": pl.Series([], dtype=pl.Float64),
            "risk_weight": pl.Series([], dtype=pl.Float64),
            "rwa_final": pl.Series([], dtype=pl.Float64),
        })

    # =========================================================================
    # Private Methods - Output Floor
    # =========================================================================

    def _apply_floor_with_impact(
        self,
        combined: pl.LazyFrame,
        sa_results: pl.LazyFrame,
        config: CalculationConfig,
    ) -> tuple[pl.LazyFrame, pl.LazyFrame]:
        """
        Apply output floor and generate impact analysis.

        Returns:
            Tuple of (floored results, floor impact analysis)
        """
        # Get floor percentage
        floor_pct = float(
            config.output_floor.get_floor_percentage(config.reporting_date)
        )

        # Determine SA RWA column
        sa_schema = sa_results.collect_schema()
        if "rwa_post_factor" in sa_schema.names():
            sa_rwa_col = "rwa_post_factor"
        elif "rwa" in sa_schema.names():
            sa_rwa_col = "rwa"
        else:
            # No RWA column found - return unchanged
            return combined, self._create_empty_floor_impact_frame()

        # Prepare SA results for comparison
        sa_rwa = sa_results.select([
            pl.col("exposure_reference"),
            pl.col(sa_rwa_col).alias("sa_rwa"),
        ])

        # Ensure combined has rwa_final column
        combined_schema = combined.collect_schema()
        if "rwa_final" not in combined_schema.names():
            if "rwa" in combined_schema.names():
                combined = combined.with_columns([pl.col("rwa").alias("rwa_final")])
            elif "rwa_post_factor" in combined_schema.names():
                combined = combined.with_columns([pl.col("rwa_post_factor").alias("rwa_final")])
            else:
                combined = combined.with_columns([pl.lit(0.0).alias("rwa_final")])

        # Store pre-floor RWA for impact calculation
        combined = combined.with_columns([
            pl.col("rwa_final").alias("rwa_pre_floor"),
        ])

        # Join with SA for floor comparison (only for IRB exposures)
        result = combined.join(
            sa_rwa,
            on="exposure_reference",
            how="left",
            suffix="_sa",
        )

        # Get approach column for determining which are IRB
        irb_approaches = ["FIRB", "AIRB", "IRB"]

        # Apply floor only to IRB exposures
        result = result.with_columns([
            # Calculate floor RWA
            (pl.col("sa_rwa").fill_null(0.0) * floor_pct).alias("floor_rwa"),
            pl.lit(floor_pct).alias("output_floor_pct"),
        ]).with_columns([
            # Is floor binding? (only for IRB approaches)
            pl.when(pl.col("approach_applied").is_in(irb_approaches))
            .then(pl.col("floor_rwa") > pl.col("rwa_pre_floor"))
            .otherwise(pl.lit(False))
            .alias("is_floor_binding"),
        ]).with_columns([
            # Floor impact (additional RWA from floor)
            pl.when(pl.col("is_floor_binding"))
            .then(pl.col("floor_rwa") - pl.col("rwa_pre_floor"))
            .otherwise(pl.lit(0.0))
            .alias("floor_impact_rwa"),
        ]).with_columns([
            # Apply floor to final RWA for IRB exposures
            pl.when(pl.col("approach_applied").is_in(irb_approaches))
            .then(pl.max_horizontal(pl.col("rwa_pre_floor"), pl.col("floor_rwa")))
            .otherwise(pl.col("rwa_pre_floor"))
            .alias("rwa_final"),
        ])

        # Generate floor impact analysis
        result_schema = result.collect_schema()
        floor_impact = result.select([
            pl.col("exposure_reference"),
            pl.col("approach_applied"),
            pl.col("exposure_class") if "exposure_class" in result_schema.names() else pl.lit(None).cast(pl.String).alias("exposure_class"),
            pl.col("rwa_pre_floor"),
            pl.col("floor_rwa"),
            pl.col("is_floor_binding"),
            pl.col("floor_impact_rwa"),
            pl.col("rwa_final").alias("rwa_post_floor"),
            pl.col("output_floor_pct"),
        ]).filter(
            pl.col("approach_applied").is_in(irb_approaches)
        )

        return result, floor_impact

    def _create_empty_floor_impact_frame(self) -> pl.LazyFrame:
        """Create empty floor impact frame with expected schema."""
        return pl.LazyFrame({
            "exposure_reference": pl.Series([], dtype=pl.String),
            "approach_applied": pl.Series([], dtype=pl.String),
            "exposure_class": pl.Series([], dtype=pl.String),
            "rwa_pre_floor": pl.Series([], dtype=pl.Float64),
            "floor_rwa": pl.Series([], dtype=pl.Float64),
            "is_floor_binding": pl.Series([], dtype=pl.Boolean),
            "floor_impact_rwa": pl.Series([], dtype=pl.Float64),
            "rwa_post_floor": pl.Series([], dtype=pl.Float64),
            "output_floor_pct": pl.Series([], dtype=pl.Float64),
        })

    # =========================================================================
    # Private Methods - Supporting Factor Impact
    # =========================================================================

    def _generate_supporting_factor_impact(
        self,
        sa_results: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Generate supporting factor impact analysis.

        Shows the RWA reduction from SME and infrastructure factors.
        """
        schema = sa_results.collect_schema()

        # Check for supporting factor columns
        has_sf = "supporting_factor" in schema.names()
        has_applied = "supporting_factor_applied" in schema.names()
        has_pre = "rwa_pre_factor" in schema.names()
        has_post = "rwa_post_factor" in schema.names()

        if not (has_sf and has_pre and has_post):
            # Return empty impact frame
            return pl.LazyFrame({
                "exposure_reference": pl.Series([], dtype=pl.String),
                "supporting_factor": pl.Series([], dtype=pl.Float64),
                "rwa_pre_factor": pl.Series([], dtype=pl.Float64),
                "rwa_post_factor": pl.Series([], dtype=pl.Float64),
                "supporting_factor_impact": pl.Series([], dtype=pl.Float64),
                "supporting_factor_applied": pl.Series([], dtype=pl.Boolean),
            })

        # Calculate impact
        impact = sa_results.select([
            pl.col("exposure_reference"),
            pl.col("exposure_class") if "exposure_class" in schema.names() else pl.lit(None).alias("exposure_class"),
            pl.col("is_sme") if "is_sme" in schema.names() else pl.lit(False).alias("is_sme"),
            pl.col("is_infrastructure") if "is_infrastructure" in schema.names() else pl.lit(False).alias("is_infrastructure"),
            pl.col("ead_final") if "ead_final" in schema.names() else pl.lit(0.0).alias("ead_final"),
            pl.col("supporting_factor"),
            pl.col("rwa_pre_factor"),
            pl.col("rwa_post_factor"),
            (pl.col("rwa_pre_factor") - pl.col("rwa_post_factor")).alias("supporting_factor_impact"),
            pl.col("supporting_factor_applied") if has_applied else (pl.col("supporting_factor") < 1.0).alias("supporting_factor_applied"),
        ]).filter(
            pl.col("supporting_factor_applied")
        )

        return impact

    # =========================================================================
    # Private Methods - Summary Generation
    # =========================================================================

    def _generate_summary_by_class(
        self,
        results: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Generate RWA summary by exposure class.

        Aggregates:
        - Total EAD
        - Total RWA
        - Average risk weight
        - Exposure count
        - Floor binding count (if applicable)
        """
        schema = results.collect_schema()

        # Build aggregation expressions
        agg_exprs = [
            pl.col("ead_final").sum().alias("total_ead") if "ead_final" in schema.names() else pl.lit(0.0).alias("total_ead"),
            pl.col("rwa_final").sum().alias("total_rwa"),
            pl.len().alias("exposure_count"),
        ]

        # Add weighted average risk weight if possible
        if "risk_weight" in schema.names() and "ead_final" in schema.names():
            agg_exprs.append(
                (pl.col("risk_weight") * pl.col("ead_final")).sum().alias("_weighted_rw"),
            )

        # Add floor binding count if applicable
        if "is_floor_binding" in schema.names():
            agg_exprs.append(
                pl.col("is_floor_binding").sum().cast(pl.UInt32).alias("floor_binding_count"),
            )

        # Group by exposure class
        group_col = "exposure_class" if "exposure_class" in schema.names() else None

        if group_col:
            summary = results.group_by(group_col).agg(agg_exprs)
        else:
            # No class column - aggregate all
            summary = results.select(agg_exprs).with_columns([
                pl.lit("ALL").alias("exposure_class"),
            ])

        # Calculate average risk weight
        if "risk_weight" in schema.names() and "ead_final" in schema.names():
            summary = summary.with_columns([
                pl.when(pl.col("total_ead") > 0)
                .then(pl.col("_weighted_rw") / pl.col("total_ead"))
                .otherwise(pl.lit(0.0))
                .alias("avg_risk_weight"),
            ]).drop("_weighted_rw")

        return summary

    def _generate_summary_by_approach(
        self,
        results: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Generate RWA summary by calculation approach.

        Aggregates:
        - Total EAD
        - Total RWA
        - Exposure count
        - Floor impact (if applicable)
        """
        schema = results.collect_schema()

        # Build aggregation expressions
        agg_exprs = [
            pl.col("ead_final").sum().alias("total_ead") if "ead_final" in schema.names() else pl.lit(0.0).alias("total_ead"),
            pl.col("rwa_final").sum().alias("total_rwa"),
            pl.len().alias("exposure_count"),
        ]

        # Add floor impact if applicable
        if "floor_impact_rwa" in schema.names():
            agg_exprs.append(
                pl.col("floor_impact_rwa").sum().alias("total_floor_impact"),
            )

        # Add expected loss for IRB if available
        if "expected_loss" in schema.names():
            agg_exprs.append(
                pl.col("expected_loss").sum().alias("total_expected_loss"),
            )

        # Group by approach
        group_col = "approach_applied" if "approach_applied" in schema.names() else None

        if group_col:
            summary = results.group_by(group_col).agg(agg_exprs)
        else:
            # No approach column - aggregate all
            summary = results.select(agg_exprs).with_columns([
                pl.lit("ALL").alias("approach_applied"),
            ])

        return summary


# =============================================================================
# Factory Function
# =============================================================================


def create_output_aggregator() -> OutputAggregator:
    """
    Create an OutputAggregator instance.

    Returns:
        OutputAggregator ready for use
    """
    return OutputAggregator()
