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

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.edges import AGGREGATOR_EXIT_EDGE, seal
from rwa_calc.contracts.errors import non_finite_input_warning, non_finite_output_error
from rwa_calc.engine.aggregator._crm_reporting import (
    generate_post_crm_detailed,
    generate_post_crm_summary,
    generate_pre_crm_summary,
)
from rwa_calc.engine.aggregator._el_summary import compute_el_portfolio_summary
from rwa_calc.engine.aggregator._equity_prep import prepare_equity_results
from rwa_calc.engine.aggregator._floor import apply_floor_with_impact, compute_of_adj
from rwa_calc.engine.aggregator._securitisation import (
    apply_residual_multiplier,
    generate_securitisation_audit,
    generate_securitisation_summary,
)
from rwa_calc.engine.aggregator._summaries import (
    generate_summary_by_approach,
    generate_summary_by_class,
    generate_summary_by_class_method,
)
from rwa_calc.engine.aggregator._supporting_factors import generate_supporting_factor_impact
from rwa_calc.rulebook import RulepackV0

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from rwa_calc.contracts.bundles import EquityResultBundle
    from rwa_calc.contracts.config import CalculationConfig, OutputFloorConfig
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)


class OutputAggregator:
    """
    Aggregate per-approach calculator results into final output.

    Implements OutputAggregatorProtocol. Combines SA, IRB, Slotting,
    and Equity results, applies regulatory adjustments (output floor,
    supporting factors), and produces all summary and reporting views.
    """

    @cites("PS1/26, paragraph 92")
    def aggregate(
        self,
        sa_results: pl.LazyFrame,
        irb_results: pl.LazyFrame,
        slotting_results: pl.LazyFrame,
        equity_bundle: EquityResultBundle | None,
        config: CalculationConfig,
        securitisation_audit: pl.LazyFrame | None = None,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> AggregatedResultBundle:
        """
        Aggregate calculator outputs into final result bundle.

        Args:
            sa_results: SA branch results (already collected and re-lazied).
            irb_results: IRB branch results.
            slotting_results: Slotting branch results.
            equity_bundle: Equity result bundle (optional, separate path).
            config: Calculation configuration.
            securitisation_audit: Resolved securitisation lookup from the
                allocator stage (one row per securitised exposure carrying
                residual_pct + pool_allocations + audit_status). None when
                no allocations were supplied.
            pack: Resolved rulepack for the run's regime/date (Phase 5 — sources
                the ``output_floor`` / ``supporting_factors`` regime gates).
                Production threads the orchestrator's pack; direct callers may
                omit it, in which case one is resolved from ``config``.

        Returns:
            AggregatedResultBundle with all summaries and adjustments. Every
            frame field is eager-backed: the summary views are collected once
            here (in two ``_collect_views`` batches, pre- and post-floor) and
            wrapped back with ``.lazy()``, so a downstream collect call is a
            near-free shallow collect rather than a plan re-execution.
        """
        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack

        # Combine for summaries (data already materialised — cheap concat).
        # ``combined_unmultiplied`` retains the full ead_final / rwa_final
        # values so the per-pool securitisation summary can multiply by each
        # pool's allocation_pct against the un-multiplied parent total. The
        # main ``combined`` then gets the residual multiplier applied so the
        # existing summaries (by class, by approach, floor, EL, supporting
        # factors) naturally reflect the on-balance-sheet residual only --
        # ``ead_final × (1 - securitisation_pct)`` in the user's words.
        combined_unmultiplied = pl.concat(
            [sa_results, irb_results, slotting_results], how="diagonal_relaxed"
        )

        # Concat equity if present
        equity_results = None
        if equity_bundle and equity_bundle.results is not None:
            equity_prepared = prepare_equity_results(equity_bundle.results)
            combined_unmultiplied = pl.concat(
                [combined_unmultiplied, equity_prepared], how="diagonal_relaxed"
            )
            equity_results = equity_bundle.results

        # Build the per-pool summary and the per-exposure reconciliation
        # BEFORE applying the residual multiplier -- the pool slice needs
        # the un-multiplied parent EAD.
        securitisation_summary = generate_securitisation_summary(combined_unmultiplied)
        sec_audit_view = generate_securitisation_audit(combined_unmultiplied, securitisation_audit)

        # Apply the residual multiplier in-place so every downstream
        # summary, floor calc, and EL roll-up reflects only the on-balance-
        # sheet portion. When no allocations are present, the multiplier
        # column is a uniform 1.0 and this is a no-op.
        combined = apply_residual_multiplier(combined_unmultiplied)

        # Pre-CRM summary uses the original (pre-substitution) class and is
        # unaffected by the output floor, so it is built from the current
        # ``combined``.  The post-CRM reporting views and the by-class /
        # by-approach summaries are deferred until AFTER the output floor is
        # applied below, so they reflect the floored per-row RWA (P1.130).
        pre_crm_summary = generate_pre_crm_summary(combined)

        # Materialise the pre-floor views ONCE.  The calculator branches are
        # already eager (collected by materialise_branches at the calculator
        # edge), so these are plans over in-memory data; one pl.collect_all
        # shares the common subplan (concat + residual multiplier) across the
        # views.  Each frame is wrapped back with ``.lazy()`` so the bundle
        # fields stay LazyFrame-typed (migration Phase 1 — no bundle type
        # changes until the Phase 3 producer seal).
        pre_floor_views: dict[str, pl.LazyFrame] = {
            "combined": combined,
            "pre_crm_summary": pre_crm_summary,
        }
        if securitisation_summary is not None:
            pre_floor_views["securitisation_summary"] = securitisation_summary
        if sec_audit_view is not None:
            pre_floor_views["securitisation_audit"] = sec_audit_view
        pre_floor_dfs = _collect_views(pre_floor_views)

        combined_df = pre_floor_dfs["combined"]
        combined = combined_df.lazy()

        # CCR Art. 308/309 default-fund-contribution roll-up: sum rwa_final over
        # the synthetic ``CCR_DEFAULT_FUND`` rows. Guarded for the column's
        # absence on CCR-free portfolios (risk_type is null/absent there).
        rwa_ccr_default_fund: float | None = None
        if {"risk_type", "rwa_final"} <= set(combined_df.columns):
            dfc_total = float(
                combined_df.filter(pl.col("risk_type") == "CCR_DEFAULT_FUND")
                .select(pl.col("rwa_final").fill_null(0.0).sum())
                .item()
            )
            if dfc_total > 0.0:
                rwa_ccr_default_fund = dfc_total

        # P8.52 CCR reporting roll-ups (COREP / Pillar-III scalars). Each is a
        # filtered sum over the already-materialised ``combined_df``; column-
        # presence-guarded so a CCR-free portfolio yields ``None`` not a raise.
        #
        # ead_ccr_total — CRR Art. 274(2): sum of ead_final over the synthetic
        # ``ccr__``-prefixed CCR derivative / SFT rows.
        ead_ccr_total: float | None = None
        if {"exposure_reference", "ead_final"} <= set(combined_df.columns):
            ead_total = float(
                combined_df.filter(pl.col("exposure_reference").str.starts_with("ccr__"))
                .select(pl.col("ead_final").sum())
                .item()
            )
            if ead_total > 0.0:
                ead_ccr_total = ead_total

        # rwa_ccr_default / rwa_ccr_qccp_trade — partition of the ``ccr__`` row
        # set by the QCCP trade-leg discriminator (cp_entity_type == "ccp" AND
        # cp_is_qccp.fill_null(True), mirroring the SA QCCP override). Default
        # is the non-QCCP complement (CRR Art. 107(2)(a)); qccp_trade is the
        # QCCP partition (CRR Art. 306(1)/(4)).
        rwa_ccr_default: float | None = None
        rwa_ccr_qccp_trade: float | None = None
        if {
            "exposure_reference",
            "rwa_final",
            "cp_entity_type",
            "cp_is_qccp",
        } <= set(combined_df.columns):
            ccr_rows = combined_df.filter(pl.col("exposure_reference").str.starts_with("ccr__"))
            is_qccp_trade = (pl.col("cp_entity_type") == "ccp") & pl.col("cp_is_qccp").fill_null(
                True
            )
            default_total = float(
                ccr_rows.filter(~is_qccp_trade).select(pl.col("rwa_final").sum()).item()
            )
            if default_total > 0.0:
                rwa_ccr_default = default_total
            qccp_total = float(
                ccr_rows.filter(is_qccp_trade).select(pl.col("rwa_final").sum()).item()
            )
            if qccp_total > 0.0:
                rwa_ccr_qccp_trade = qccp_total

        # failed_trades_rwa — CRR Art. 378-380 / Art. 92(3)(ca): sum of
        # rwa_final over the synthetic ``SETTLEMENT_FAILED_TRADE`` rows.
        failed_trades_rwa: float | None = None
        if {"risk_type", "rwa_final"} <= set(combined_df.columns):
            ft_total = float(
                combined_df.filter(pl.col("risk_type") == "SETTLEMENT_FAILED_TRADE")
                .select(pl.col("rwa_final").sum())
                .item()
            )
            if ft_total > 0.0:
                failed_trades_rwa = ft_total

        pre_crm_summary = pre_floor_dfs["pre_crm_summary"].lazy()
        if securitisation_summary is not None:
            securitisation_summary = pre_floor_dfs["securitisation_summary"].lazy()
        if sec_audit_view is not None:
            sec_audit_view = pre_floor_dfs["securitisation_audit"].lazy()

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
        #
        # Securitisation: feed the residual-multiplied views so EL / PoolB /
        # T2 cap arithmetic reflects only the on-balance-sheet portion. The
        # IRB EL formula scales linearly with EAD, so this is equivalent to
        # multiplying the final EL summary by the residual fraction.
        el_summary = compute_el_portfolio_summary(
            apply_residual_multiplier(irb_results),
            apply_residual_multiplier(slotting_results),
        )

        # Apply portfolio-level output floor if applicable (Art. 92 para 2A)
        # Floor only applies to specific (institution_type, reporting_basis)
        # combinations — exempt entities use U-TREA with no floor add-on.
        floor_impact = None
        output_floor_summary = None
        if resolved_pack.feature("output_floor") and config.output_floor.is_entity_in_scope():
            floor_pct = float(
                _output_floor_pct(resolved_pack, config.output_floor, config.reporting_date)
            )

            # Compute OF-ADJ from EL summary + capital-tier config inputs
            # OF-ADJ = 12.5 * (IRB_T2 - IRB_CET1 - GCRA + SA_T2)
            # ELPortfolioSummary stores Decimal; convert to float for floor arithmetic.
            irb_t2 = float(el_summary.t2_credit) if el_summary else 0.0
            irb_cet1 = (
                float(el_summary.cet1_deduction) if el_summary else 0.0
            ) + config.output_floor.art_40_deductions
            gcra = config.output_floor.gcra_amount
            sa_t2 = config.output_floor.sa_t2_credit

            # S-TREA is needed for GCRA cap — pre-compute it here.
            # We need a quick aggregate of SA-equivalent RWA for floor-eligible
            # exposures.  This duplicates some work in apply_floor_with_impact
            # but avoids restructuring the floor module's internal flow.
            # Computed eagerly from ``combined_df`` (materialised above) so no
            # extra plan execution is needed.
            from rwa_calc.engine.aggregator._schemas import FLOOR_ELIGIBLE_APPROACHES

            if "approach_applied" in combined_df.columns:
                sa_rwa_col = "sa_rwa" if "sa_rwa" in combined_df.columns else "rwa_final"
                s_trea_pre = float(
                    combined_df.filter(
                        pl.col("approach_applied").is_in(list(FLOOR_ELIGIBLE_APPROACHES))
                    )
                    .select(pl.col(sa_rwa_col).fill_null(0.0).sum())
                    .item()
                )
            else:
                s_trea_pre = 0.0

            of_adj_val, gcra_capped = compute_of_adj(
                irb_t2, irb_cet1, gcra, sa_t2, s_trea_pre, pack=resolved_pack
            )

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

        # Generate post-CRM reporting views from the (possibly floored)
        # ``combined`` frame.  When the floor binds, ``combined`` now carries
        # the per-row ``floor_impact_rwa`` add-on, which the by-class /
        # by-approach summaries fold into ``total_rwa`` so the reported totals
        # reconcile with ``output_floor_summary.total_rwa_post_floor`` (P1.130).
        # When the floor does not run (or does not bind), ``combined`` is the
        # pre-floor frame and these views are identical to the pre-fix output.
        post_crm_detailed = generate_post_crm_detailed(combined)
        post_crm_summary = generate_post_crm_summary(post_crm_detailed)
        summary_by_class = generate_summary_by_class(post_crm_detailed)
        summary_by_approach = generate_summary_by_approach(post_crm_detailed)
        summary_by_class_method = generate_summary_by_class_method(post_crm_detailed)

        # Supporting factor impact. The regime gate is pack Feature-sourced; the
        # pack is threaded into aggregate() (S11d), so this reads the run's
        # resolved pack directly rather than re-deriving one from config.
        supporting_factor_impact = None
        if resolved_pack.feature("supporting_factors"):
            supporting_factor_impact = generate_supporting_factor_impact(combined)

        # Materialise the post-floor views ONCE (same single-collect pattern
        # as the pre-floor batch).  ``None`` fields stay None — only frames
        # that were actually built are collected.
        post_floor_views: dict[str, pl.LazyFrame] = {
            "results": combined,
            "post_crm_detailed": post_crm_detailed,
            "post_crm_summary": post_crm_summary,
            "summary_by_class": summary_by_class,
            "summary_by_approach": summary_by_approach,
            "summary_by_class_method": summary_by_class_method,
        }
        if floor_impact is not None:
            post_floor_views["floor_impact"] = floor_impact
        if supporting_factor_impact is not None:
            post_floor_views["supporting_factor_impact"] = supporting_factor_impact
        post_floor_dfs = _collect_views(post_floor_views)

        return AggregatedResultBundle(
            # Producer seal (Phase 3): the aggregator's combined results
            # frame is the reporting input contract — pure plan ops over
            # the eager-backed wrap.
            results=seal(post_floor_dfs["results"].lazy(), AGGREGATOR_EXIT_EDGE),
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=slotting_results,
            equity_results=equity_results,
            floor_impact=(
                post_floor_dfs["floor_impact"].lazy() if floor_impact is not None else None
            ),
            output_floor_summary=output_floor_summary,
            supporting_factor_impact=(
                post_floor_dfs["supporting_factor_impact"].lazy()
                if supporting_factor_impact is not None
                else None
            ),
            summary_by_class=post_floor_dfs["summary_by_class"].lazy(),
            summary_by_approach=post_floor_dfs["summary_by_approach"].lazy(),
            summary_by_class_method=post_floor_dfs["summary_by_class_method"].lazy(),
            pre_crm_summary=pre_crm_summary,
            post_crm_detailed=post_floor_dfs["post_crm_detailed"].lazy(),
            post_crm_summary=post_floor_dfs["post_crm_summary"].lazy(),
            el_summary=el_summary,
            securitisation_summary=securitisation_summary,
            securitisation_audit=sec_audit_view,
            rwa_ccr_default_fund=rwa_ccr_default_fund,
            ead_ccr_total=ead_ccr_total,
            rwa_ccr_default=rwa_ccr_default,
            rwa_ccr_qccp_trade=rwa_ccr_qccp_trade,
            failed_trades_rwa=failed_trades_rwa,
            errors=_detect_non_finite_errors(
                post_floor_dfs["results"], post_floor_dfs.get("post_crm_detailed")
            ),
        )


# =============================================================================
# Private helpers
# =============================================================================


def _collect_views(views: dict[str, pl.LazyFrame]) -> dict[str, pl.DataFrame]:
    """Materialise a batch of aggregator views together, in one pass.

    The calculator branches arrive already eager (collected by
    ``materialise_branches`` at the calculator edge), so every view here is a
    plan over in-memory data.  Collecting the batch with a single
    ``pl.collect_all`` lets Polars share the common subplans (the combined
    concat + residual multiplier) across views via comm-subplan elimination.
    The caller wraps each eager result back with ``.lazy()`` so the bundle
    fields stay LazyFrame-typed; any downstream collect on them is then a
    near-free shallow collect instead of a plan re-execution.

    This is deliberately a plain ``pl.collect_all`` rather than
    ``materialise_branches``: the latter records per-frame EdgeEvents in the
    run capture, and the aggregator's internal summary views are not stage
    edges (the documented edge inventory in
    tests/integration/test_stage_edges.py pins the stage-exit sequence).
    """
    collected = pl.collect_all(list(views.values()))
    return dict(zip(views, collected, strict=True))


def _non_finite_refs(df: pl.DataFrame, col: str) -> list[str]:
    """Distinct ``exposure_reference`` values with a non-finite (NaN/inf) ``col``.

    Returns ``[]`` when the column is absent, non-float, or fully finite. A null
    is NOT non-finite (``is_finite()`` is null on a null, filled to False here), so
    only genuine NaN/inf rows are flagged. References are de-duplicated because the
    post-CRM reporting frame splits one exposure across several rows.
    """
    cols = set(df.columns)
    if col not in cols or df.schema[col] not in (pl.Float32, pl.Float64):
        return []
    mask = (~df.get_column(col).is_finite()).fill_null(value=False)  # noqa: FBT003
    if not bool(mask.any()):
        return []
    if "exposure_reference" not in cols:
        return ["<unknown>"] * int(mask.sum())
    refs = df.filter(mask).get_column("exposure_reference").cast(pl.String).to_list()
    return list(dict.fromkeys(refs))


def _detect_non_finite_errors(
    results_df: pl.DataFrame, reporting_df: pl.DataFrame | None
) -> list[CalculationError]:
    """Surface NaN/inf in the per-row outputs (AGG001) and IRB inputs (AGG002).

    Polars float ``.sum()`` propagates a NaN (it is not skipped like a null), so a
    single non-finite value would blank the portfolio totals and the summary
    charts. Rather than silently degrade, the aggregator records:

    - **AGG001 (error)** for the final output columns the cards/charts consume —
      ``rwa_final`` / ``ead_final`` / ``risk_weight`` (the totals/cards) plus the
      post-CRM ``reporting_rw`` / ``reporting_ead`` the by-class/by-approach charts
      aggregate. Reporting-column offenders already named by the output scan are
      not re-reported. ``ErrorSeverity.ERROR`` (not critical) keeps the run
      successful so the unaffected rows still report.
    - **AGG002 (warning)** for a non-finite raw IRB input (``pd`` / ``lgd``) that
      the floors raised to the regulatory minimum — a finite result that never
      trips AGG001, so without this it would be absorbed silently.
    """
    errors: list[CalculationError] = []

    flagged: set[str] = set()
    for col in ("rwa_final", "ead_final", "risk_weight"):
        refs = [r for r in _non_finite_refs(results_df, col) if r not in flagged]
        if refs:
            errors.append(non_finite_output_error(column=col, count=len(refs), references=refs[:5]))
            flagged.update(refs)
    if reporting_df is not None:
        for col in ("reporting_rw", "reporting_ead"):
            refs = [r for r in _non_finite_refs(reporting_df, col) if r not in flagged]
            if refs:
                errors.append(
                    non_finite_output_error(column=col, count=len(refs), references=refs[:5])
                )
                flagged.update(refs)

    for col in ("pd", "lgd"):
        refs = _non_finite_refs(results_df, col)
        if refs:
            errors.append(
                non_finite_input_warning(column=col, count=len(refs), references=refs[:5])
            )

    return errors


def _output_floor_pct(pack: ResolvedRulepack, output_floor: OutputFloorConfig, on: date) -> Decimal:
    """Output-floor percentage for ``on`` from the rulepack (Phase 5 S11e-v1).

    Pack twin of the value computation in
    ``OutputFloorConfig.get_floor_percentage``: the Art. 92(5) transitional
    phase-in (``output_floor_pct`` Schedule) and the fully-phased-in 72.5%
    (``output_floor_pct_full`` scalar) are pack data; the ``skip_transitional``
    ELECTION stays on the config. Called only when the ``output_floor`` Feature
    is on (the caller gates), so the disabled / before-start cases reduce to the
    Schedule's ``before_first`` (0.0) — byte-identical with the config method.
    """
    if output_floor.skip_transitional:
        return pack.scalar("output_floor_pct_full")
    return pack.schedule("output_floor_pct").resolve(on)
