"""
Output Aggregator for RWA Calculations.

Pipeline position:
    SA/IRB/Slotting/Equity Calculators -> OutputAggregator -> AggregatedResultBundle

Key responsibilities:
- Combining per-approach calculator results into a unified view
- Computing portfolio-level EL summary with T2 credit cap
- Computing OF-ADJ from EL summary and capital-tier inputs
- Applying output floor (Basel 3.1) with OF-ADJ
- Generating supporting factor impact (CRR)
- Generating summaries by exposure class and approach
- Generating pre/post-CRM regulatory reporting views

References:
- PRA PS1/26 Art. 92 para 2A: TREA = max(U-TREA, x * S-TREA + OF-ADJ)
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
from rwa_calc.engine.aggregator._floor import apply_floor_with_impact, compute_of_adj
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

        # EL portfolio summary (T2 credit cap, CET1/T2 deductions)
        # Computed BEFORE the output floor because OF-ADJ depends on EL summary
        # results (IRB T2 credit and IRB CET1 deduction).
        #
        # IMPORTANT: The T2 credit cap (Art. 62(d)) uses un-floored IRB RWA,
        # not post-floor TREA.  Art. 62(d) references "risk-weighted exposure
        # amounts calculated under Chapter 3 of Title II of Part Three" — the
        # IRB chapter — not the portfolio-level floor from Art. 92(2A).
        # We intentionally pass the original irb_results / slotting_results
        # (which are unaffected by the floor applied to `combined` above),
        # NOT the floored `combined` LazyFrame.  Using post-floor TREA would
        # also create a circular dependency with the OF-ADJ formula.
        el_summary = compute_el_portfolio_summary(irb_results, slotting_results)

        # Apply portfolio-level output floor if applicable (Art. 92 para 2A)
        # Floor only applies to specific (institution_type, reporting_basis)
        # combinations — exempt entities use U-TREA with no floor add-on.
        floor_impact = None
        output_floor_summary = None
        if config.output_floor.is_floor_applicable():
            floor_pct = float(config.output_floor.get_floor_percentage(config.reporting_date))

            # Compute OF-ADJ from EL summary + capital-tier config inputs
            # OF-ADJ = 12.5 * (IRB_T2 - IRB_CET1 - GCRA + SA_T2)
            irb_t2 = el_summary.t2_credit if el_summary else 0.0
            irb_cet1 = (
                (el_summary.cet1_deduction if el_summary else 0.0)
                + config.output_floor.art_40_deductions
            )
            gcra = config.output_floor.gcra_amount
            sa_t2 = config.output_floor.sa_t2_credit

            # S-TREA is needed for GCRA cap — pre-compute it here.
            # We need a quick aggregate of SA-equivalent RWA for floor-eligible
            # exposures.  This duplicates some work in apply_floor_with_impact
            # but avoids restructuring the floor module's internal flow.
            from rwa_calc.engine.aggregator._schemas import FLOOR_ELIGIBLE_APPROACHES

            combined_cols = set(combined.collect_schema().names())
            if "approach_applied" in combined_cols:
                sa_rwa_col = "sa_rwa" if "sa_rwa" in combined_cols else "rwa_final"
                s_trea_pre = float(
                    combined.filter(
                        pl.col("approach_applied").is_in(list(FLOOR_ELIGIBLE_APPROACHES))
                    )
                    .select(pl.col(sa_rwa_col).fill_null(0.0).sum())
                    .collect()
                    .item()
                )
            else:
                s_trea_pre = 0.0

            of_adj_val, gcra_capped = compute_of_adj(irb_t2, irb_cet1, gcra, sa_t2, s_trea_pre)

            combined, floor_impact, output_floor_summary = apply_floor_with_impact(
                combined,
                combined,  # SA-equivalent RW already joined by SA calculator
                floor_pct,
                of_adj=of_adj_val,
                irb_t2_credit=irb_t2,
                irb_cet1_deduction=irb_cet1,
                gcra_amount=gcra_capped,
                sa_t2_credit=sa_t2,
            )

        # Supporting factor impact
        supporting_factor_impact = None
        if config.supporting_factors.enabled:
            supporting_factor_impact = generate_supporting_factor_impact(combined)

        return AggregatedResultBundle(
            results=combined,
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=slotting_results,
            equity_results=equity_results,
            floor_impact=floor_impact,
            output_floor_summary=output_floor_summary,
            supporting_factor_impact=supporting_factor_impact,
            summary_by_class=summary_by_class,
            summary_by_approach=summary_by_approach,
            pre_crm_summary=pre_crm_summary,
            post_crm_detailed=post_crm_detailed,
            post_crm_summary=post_crm_summary,
            el_summary=el_summary,
            errors=[],
        )
