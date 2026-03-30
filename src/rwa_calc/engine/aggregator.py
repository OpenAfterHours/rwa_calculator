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
- Apply output floor (Basel 3.1: max(IRB RWA, 72.5% x SA RWA))
- Track supporting factor impact (CRR only)
- Generate summary statistics by class and approach

References:
- CRE99.1-8: Output floor (Basel 3.1)
- PS1/26 Ch.12: PRA output floor implementation
- CRR Art. 501: SME supporting factor
- CRR Art. 501a: Infrastructure supporting factor
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import (
    AggregatedResultBundle,
    EquityResultBundle,
    IRBResultBundle,
    SAResultBundle,
    SlottingResultBundle,
)
from rwa_calc.engine._aggregator_helpers import (
    apply_floor_with_impact,
    combine_results,
    compute_el_portfolio_summary,
    generate_post_crm_detailed,
    generate_post_crm_summary,
    generate_pre_crm_summary,
    generate_summary_by_approach,
    generate_summary_by_class,
    generate_supporting_factor_impact,
    resolve_rwa_col,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


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
        return combine_results(sa_results=sa_results, irb_results=irb_results)

    def aggregate_with_audit(
        self,
        sa_bundle: SAResultBundle | None,
        irb_bundle: IRBResultBundle | None,
        slotting_bundle: SlottingResultBundle | None,
        config: CalculationConfig,
        equity_bundle: EquityResultBundle | None = None,
    ) -> AggregatedResultBundle:
        """
        Aggregate with full audit trail.

        Args:
            sa_bundle: SA calculation results bundle
            irb_bundle: IRB calculation results bundle
            slotting_bundle: Slotting calculation results bundle
            config: Calculation configuration
            equity_bundle: Equity calculation results bundle

        Returns:
            AggregatedResultBundle with full audit trail
        """
        # Get result frames from bundles
        sa_results = sa_bundle.results if sa_bundle else None
        irb_results = irb_bundle.results if irb_bundle else None
        slotting_results = slotting_bundle.results if slotting_bundle else None
        equity_results = equity_bundle.results if equity_bundle else None

        # Combine all results
        combined = combine_results(
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=slotting_results,
            equity_results=equity_results,
        )

        # Apply output floor (Basel 3.1 only)
        floor_impact = None
        if config.output_floor.enabled and irb_results is not None and sa_results is not None:
            floor_pct = float(config.output_floor.get_floor_percentage(config.reporting_date))
            combined, floor_impact = apply_floor_with_impact(combined, sa_results, floor_pct)

        # Generate supporting factor impact (CRR only)
        supporting_factor_impact = None
        if config.supporting_factors.enabled and sa_results is not None:
            supporting_factor_impact = generate_supporting_factor_impact(sa_results)

        # Generate pre/post CRM summaries for regulatory reporting
        pre_crm_summary = generate_pre_crm_summary(combined)
        post_crm_detailed = generate_post_crm_detailed(combined)
        post_crm_summary = generate_post_crm_summary(post_crm_detailed)

        # Generate summaries from post-CRM detailed view (split rows for guarantees)
        summary_by_class = generate_summary_by_class(post_crm_detailed)
        summary_by_approach = generate_summary_by_approach(post_crm_detailed)

        # Compute portfolio-level EL summary with T2 credit cap (IRB only)
        el_summary = compute_el_portfolio_summary(irb_results)

        # Collect all errors from input bundles
        all_errors: list = []
        for bundle in (sa_bundle, irb_bundle, slotting_bundle, equity_bundle):
            if bundle:
                all_errors.extend(bundle.errors)

        return AggregatedResultBundle(
            results=combined,
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=slotting_results,
            equity_results=equity_results,
            floor_impact=floor_impact,
            supporting_factor_impact=supporting_factor_impact,
            summary_by_class=summary_by_class,
            summary_by_approach=summary_by_approach,
            pre_crm_summary=pre_crm_summary,
            post_crm_detailed=post_crm_detailed,
            post_crm_summary=post_crm_summary,
            el_summary=el_summary,
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

        Final RWA = max(IRB RWA, SA RWA x floor_percentage)

        Args:
            irb_rwa: IRB RWA before floor
            sa_equivalent_rwa: Equivalent SA RWA for comparison
            config: Calculation configuration

        Returns:
            LazyFrame with floor-adjusted RWA
        """
        if not config.output_floor.enabled:
            return irb_rwa

        floor_pct = float(config.output_floor.get_floor_percentage(config.reporting_date))

        # Join IRB and SA results on exposure_reference
        sa_cols = set(sa_equivalent_rwa.collect_schema().names())
        sa_rwa_col = resolve_rwa_col(sa_cols)
        if not sa_rwa_col:
            return irb_rwa

        floored = irb_rwa.join(
            sa_equivalent_rwa.select(
                [
                    pl.col("exposure_reference"),
                    pl.col(sa_rwa_col).alias("sa_rwa"),
                ]
            ),
            on="exposure_reference",
            how="left",
        )

        irb_cols = set(floored.collect_schema().names())
        irb_rwa_col = "rwa" if "rwa" in irb_cols else "rwa_post_factor"

        return floored.with_columns(
            [
                (pl.col("sa_rwa").fill_null(0.0) * floor_pct).alias("floor_rwa"),
                pl.lit(floor_pct).alias("output_floor_pct"),
            ]
        ).with_columns(
            [
                (pl.col("floor_rwa") > pl.col(irb_rwa_col)).alias("is_floor_binding"),
                pl.max_horizontal(
                    pl.lit(0.0),
                    pl.col("floor_rwa") - pl.col(irb_rwa_col),
                ).alias("floor_impact_rwa"),
                pl.max_horizontal(
                    pl.col(irb_rwa_col),
                    pl.col("floor_rwa"),
                ).alias("rwa_final"),
            ]
        )


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
