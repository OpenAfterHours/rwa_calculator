"""
Polars LazyFrame namespaces for result aggregation.

Provides fluent API for combining and summarizing RWA results:
- ``lf.aggregator.combine_approach_results(sa, irb, slotting)`` - Combine results
- ``lf.aggregator.apply_output_floor(sa_results, config)`` - Apply Basel 3.1 output floor
- ``lf.aggregator.generate_summary_by_class()`` - Summarize by exposure class
- ``lf.aggregator.generate_summary_by_approach()`` - Summarize by approach

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
- PS1/26 Ch.12: PRA output floor implementation
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.engine._aggregator_helpers import (
    apply_floor_with_impact,
    combine_results,
    generate_summary_by_approach,
    generate_summary_by_class,
    generate_supporting_factor_impact,
)

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
    All methods delegate to shared helpers in ``_aggregator_helpers``.

    Example:
        result = (combined_results
            .aggregator.apply_output_floor(sa_results, config)
            .aggregator.generate_summary_by_class()
        )
    """

    def __init__(self, lf: pl.LazyFrame) -> None:
        self._lf = lf

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
        return combine_results(sa_results=sa, irb_results=irb, slotting_results=slotting)

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

        floor_pct = float(config.output_floor.get_floor_percentage(config.reporting_date))
        result, _ = apply_floor_with_impact(self._lf, sa_results, floor_pct)
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
                pl.when(pl.col("rwa_pre_floor") > 0)
                .then(pl.col("floor_impact_rwa") / pl.col("rwa_pre_floor") * 100)
                .otherwise(pl.lit(0.0))
                .alias("floor_impact_pct"),
                (pl.col("is_floor_binding")).cast(pl.Int8).alias("floor_binding_flag"),
            ]
        )

    def generate_summary_by_class(self) -> pl.LazyFrame:
        """
        Generate RWA summary by exposure class.

        Returns:
            LazyFrame with summary by exposure class
        """
        return generate_summary_by_class(self._lf)

    def generate_summary_by_approach(self) -> pl.LazyFrame:
        """
        Generate RWA summary by calculation approach.

        Returns:
            LazyFrame with summary by approach
        """
        return generate_summary_by_approach(self._lf)

    def generate_supporting_factor_impact(self) -> pl.LazyFrame:
        """
        Generate supporting factor impact analysis.

        Returns:
            LazyFrame with supporting factor impact per exposure
        """
        return generate_supporting_factor_impact(self._lf)
