"""
Output Aggregator for RWA Calculations.

Pipeline position:
    SA/IRB/Slotting/Equity Calculators -> OutputAggregator -> AggregatedResultBundle

Key responsibilities:
- Combining per-approach calculator results into a unified view
- Applying output floor (Basel 3.1) with impact analysis
- Generating supporting factor impact (CRR)
- Generating summaries by exposure class and approach
- Generating pre/post-CRM regulatory reporting views
- Computing portfolio-level EL summary with T2 credit cap

References:
- CRE99.1-8: Output floor (Basel 3.1)
- PS1/26 Ch.12: PRA output floor implementation
- CRR Art. 501/501a: SME and infrastructure supporting factors
- CRR Art. 62(d): T2 credit cap (0.6% of IRB RWA)
- CRR Art. 158-159: EL shortfall/excess treatment
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.engine.aggregator._crm_reporting import (
    generate_post_crm_detailed,
    generate_post_crm_summary,
    generate_pre_crm_summary,
)
from rwa_calc.engine.aggregator._el_summary import compute_el_portfolio_summary
from rwa_calc.engine.aggregator._equity_prep import prepare_equity_results
from rwa_calc.engine.aggregator._floor import apply_floor_with_impact
from rwa_calc.engine.aggregator._summaries import (
    generate_summary_by_approach,
    generate_summary_by_class,
)
from rwa_calc.engine.aggregator._supporting_factors import generate_supporting_factor_impact

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import EquityResultBundle
    from rwa_calc.contracts.config import CalculationConfig


class OutputAggregator:
    """
    Aggregate per-approach calculator results into final output.

    Implements OutputAggregatorProtocol. Combines SA, IRB, Slotting,
    and Equity results, applies regulatory adjustments (output floor,
    supporting factors), and produces all summary and reporting views.
    """

    def aggregate(
        self,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        slotting_results: pl.LazyFrame,
        equity_bundle: EquityResultBundle | None,
        config: CalculationConfig,
    ) -> AggregatedResultBundle:
        """
        Aggregate calculator outputs into final result bundle.

        Args:
            sa_results: SA branch results (already collected and re-lazied).
            irb_results: IRB branch results.
            slotting_results: Slotting branch results.
            equity_bundle: Equity result bundle (optional, separate path).
            config: Calculation configuration.

        Returns:
            AggregatedResultBundle with all summaries and adjustments.
        """
        # Combine for summaries (data already materialised — cheap concat)
        combined = pl.concat([sa_results, irb_results, slotting_results], how="diagonal_relaxed")

        # Concat equity if present
        equity_results = None
        if equity_bundle and equity_bundle.results is not None:
            equity_prepared = prepare_equity_results(equity_bundle.results)
            combined = pl.concat([combined, equity_prepared], how="diagonal_relaxed")
            equity_results = equity_bundle.results

        # Generate CRM reporting views
        pre_crm_summary = generate_pre_crm_summary(combined)
        post_crm_detailed = generate_post_crm_detailed(combined)
        post_crm_summary = generate_post_crm_summary(post_crm_detailed)
        summary_by_class = generate_summary_by_class(post_crm_detailed)
        summary_by_approach = generate_summary_by_approach(post_crm_detailed)

        # Apply output floor if enabled
        floor_impact = None
        if config.output_floor.enabled:
            floor_pct = float(config.output_floor.get_floor_percentage(config.reporting_date))
            combined, floor_impact = apply_floor_with_impact(
                combined,
                combined,  # SA-equivalent RW already joined by SA calculator
                floor_pct,
            )

        # Supporting factor impact
        supporting_factor_impact = None
        if config.supporting_factors.enabled:
            supporting_factor_impact = generate_supporting_factor_impact(combined)

        # EL portfolio summary (T2 credit cap, CET1/T2 deductions)
        # Include slotting EL: slotting is an IRB sub-approach (Art. 153(5) is in
        # the IRB chapter), so slotting RWA and EL feed into the T2 credit cap
        # (Art. 62(d)) and EL shortfall/excess (Art. 158-159).
        el_summary = compute_el_portfolio_summary(irb_results, slotting_results)

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
            errors=[],
        )
