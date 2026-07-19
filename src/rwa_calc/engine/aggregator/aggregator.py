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
from rwa_calc.contracts.edges import (
    AGGREGATOR_EXIT_EDGE,
    FLOOR_IMPACT_EDGE,
    SUMMARY_BY_APPROACH_EDGE,
    SUMMARY_BY_CLASS_EDGE,
    SUMMARY_BY_CLASS_METHOD_EDGE,
    SUPPORTING_FACTOR_IMPACT_EDGE,
    seal,
)
from rwa_calc.contracts.errors import non_finite_input_warning, non_finite_output_error
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.aggregator._el_summary import compute_el_portfolio_summary
from rwa_calc.engine.aggregator._equity_prep import prepare_equity_results
from rwa_calc.engine.aggregator._floor import apply_floor_with_impact, compute_of_adj
from rwa_calc.engine.aggregator._lgd_floor_check import check_retail_re_portfolio_lgd_floors
from rwa_calc.engine.aggregator._securitisation import (
    apply_residual_multiplier,
    generate_securitisation_audit,
    generate_securitisation_summary,
)
from rwa_calc.engine.aggregator._summaries import (
    generate_summary_by_approach,
    generate_summary_by_class,
    generate_summary_by_class_method,
    method_label_expr,
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

        # Applied reporting class (recon + COREP class dimension). Pure function
        # of columns already present on every branch exit, so it is added once
        # here and flows through the residual multiplier, output floor, post-CRM
        # views and the sealed results frame. ``exposure_class_post_crm`` is its
        # post-guarantee twin (guaranteed slice under the guarantor's class) that
        # the reconciliation ties out on; ``approach_post_crm`` is the matching
        # post-guarantee approach, so the two partition the same money the same way.
        combined_unmultiplied = _add_exposure_class_applied(combined_unmultiplied)
        combined_unmultiplied = _add_post_crm_reporting_class(combined_unmultiplied)
        combined_unmultiplied = _add_post_crm_reporting_approach(combined_unmultiplied)

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

        # Materialise the pre-floor views ONCE.  The calculator branches are
        # already eager (collected by materialise_branches at the calculator
        # edge), so these are plans over in-memory data; one pl.collect_all
        # shares the common subplan (concat + residual multiplier) across the
        # views.  Each frame is wrapped back with ``.lazy()`` so the bundle
        # fields stay LazyFrame-typed (migration Phase 1 — no bundle type
        # changes until the Phase 3 producer seal).  The by-class / by-approach
        # summaries are deferred until AFTER the output floor is applied below,
        # so they reflect the floored per-row RWA (P1.130).
        pre_floor_views: dict[str, pl.LazyFrame] = {
            "combined": combined,
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

        # CRR Art. 164(4)/(5) portfolio-level A-IRB retail-RE LGD-floor backstop.
        # CRR-only monitoring WARNING (never an RWA/LGD adjustment); Basel 3.1
        # disables the Feature — its per-exposure airb_lgd_floor supersedes it.
        # Reads the already-materialised ``combined_df`` (no extra collect).
        retail_re_lgd_floor_warnings: list[CalculationError] = []
        if resolved_pack.feature("crr_retail_re_portfolio_lgd_floor"):
            retail_re_lgd_floor_warnings = check_retail_re_portfolio_lgd_floors(
                combined_df, resolved_pack
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

        # Canonical reporting projection (Phase 7 S2): name the per-leg
        # substitution ledger on the frame that gets sealed. Applied AFTER the
        # residual multiplier and the output floor so the ``reporting_ead`` /
        # ``reporting_rw`` aliases mirror the sealed final values. No consumer
        # reads these columns yet (S4+ retarget the summaries/recon/reporting),
        # so this is provably cell-neutral.
        combined = _add_reporting_projection(combined)

        # Generate the persisted summaries as pure group-bys of the sealed
        # per-leg reporting ledger (Phase 7 S4) — the SINGLE by-class /
        # by-approach source. ``combined`` carries the reporting projection
        # and, when the floor bound, the per-row ``floor_impact_rwa`` add-on,
        # which ``total_rwa`` folds in so the reported totals reconcile with
        # ``output_floor_summary.total_rwa_post_floor`` (P1.130).
        summary_by_class = generate_summary_by_class(combined)
        summary_by_approach = generate_summary_by_approach(combined)
        summary_by_class_method = generate_summary_by_class_method(combined)

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
            # Producer seals for the consumer-read summary / floor / factor
            # frames (SEALED_FRAME_FIELDS-registered), same eager-backed wrap as
            # ``results``: the UI cards / results cache / analyses receive a
            # brand-validated frame, never a reshaped or partially-built one.
            floor_impact=(
                seal(post_floor_dfs["floor_impact"].lazy(), FLOOR_IMPACT_EDGE)
                if floor_impact is not None
                else None
            ),
            output_floor_summary=output_floor_summary,
            supporting_factor_impact=(
                seal(
                    post_floor_dfs["supporting_factor_impact"].lazy(), SUPPORTING_FACTOR_IMPACT_EDGE
                )
                if supporting_factor_impact is not None
                else None
            ),
            summary_by_class=seal(post_floor_dfs["summary_by_class"].lazy(), SUMMARY_BY_CLASS_EDGE),
            summary_by_approach=seal(
                post_floor_dfs["summary_by_approach"].lazy(), SUMMARY_BY_APPROACH_EDGE
            ),
            summary_by_class_method=seal(
                post_floor_dfs["summary_by_class_method"].lazy(), SUMMARY_BY_CLASS_METHOD_EDGE
            ),
            el_summary=el_summary,
            securitisation_summary=securitisation_summary,
            securitisation_audit=sec_audit_view,
            rwa_ccr_default_fund=rwa_ccr_default_fund,
            ead_ccr_total=ead_ccr_total,
            rwa_ccr_default=rwa_ccr_default,
            rwa_ccr_qccp_trade=rwa_ccr_qccp_trade,
            failed_trades_rwa=failed_trades_rwa,
            errors=(
                _detect_non_finite_errors(post_floor_dfs["results"]) + retail_re_lgd_floor_warnings
            ),
        )


# =============================================================================
# Private helpers
# =============================================================================


@cites("CRR Art. 112")
@cites("CRR Art. 123")
def _add_exposure_class_applied(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Add ``exposure_class_applied`` — the approach-agnostic applied class.

    The routing ``exposure_class`` records origination + guarantee substitution
    but omits two SA-only applied-treatment movements, so the reconciliation and
    COREP class dimensions previously mis-bucketed those rows (the RWA is correct
    in both cases — only the class label was wrong):

    - **SME managed as retail** (CRR Art. 123 / PS1/26 Art. 123A) — a
      corporate-SME row that took the 75% retail risk weight logically belongs
      to the retail class: Art. 122 corporate has no 75% band, so a 75%-weighted
      SME entails retail. The predicate mirrors the SA risk-weight branch exactly
      (``engine/sa/risk_weights.py``) so the reported class tracks the applied RW.
    - **Defaulted** (CRR Art. 112(1)(j) / Art. 127) — a defaulted SA exposure
      belongs to the "Exposures in default" class, which wins over origination
      (PS1/26 Table A2 priority 5). High-risk (Art. 128, Basel 3.1) still outranks
      default (priority 4), so a defaulted high-risk row keeps its class.

    Only SA rows (``approach_applied == "standardised"``) are re-mapped: IRB
    already reclassifies corporate→retail on ``exposure_class`` and reports
    default via a PD override (not a class), slotting keeps SPECIALISED_LENDING,
    and equity keeps EQUITY — so every non-SA approach keeps ``exposure_class``.

    This is a PRE-substitution (obligor-side) class and is applied to guaranteed
    exposures too. A guaranteed exposure is physically split into ``__G_`` /
    ``__REM`` legs (``engine/crm/guarantees.py``) that BOTH carry the obligor's
    origination ``exposure_class`` — the guarantor's class lives only in
    ``post_crm_exposure_class_guaranteed``, which drives the COREP C 07.00
    substitution inflow/outflow. So the guaranteed leg of a defaulted (or
    SME-managed-as-retail) obligor correctly takes the same applied class as its
    remainder: in C 07.00 the whole exposure originates in the obligor's sheet
    ("Exposures in default" / Retail) and the guaranteed portion leaves as an
    outflow. Gating the overlay on ``~is_guaranteed`` would wrongly drop the
    guaranteed portion out of that class and understate it.
    """
    is_sa = pl.col("approach_applied") == ApproachType.SA.value
    is_high_risk = pl.col("exposure_class") == ExposureClass.HIGH_RISK.value
    sme_managed_as_retail = (
        pl.col("exposure_class").str.to_uppercase().str.contains("SME", literal=True)
        & (pl.col("cp_is_managed_as_retail") == True)  # noqa: E712
        & (pl.col("qualifies_as_retail") == True)  # noqa: E712
    )
    return lf.with_columns(
        pl.when(~is_sa)
        .then(pl.col("exposure_class"))
        # A null is_defaulted falls through the when() (treated as not defaulted),
        # so no fill_null is needed — keep the applied class off origination.
        .when((pl.col("is_defaulted") == True) & ~is_high_risk)  # noqa: E712
        .then(pl.lit(ExposureClass.DEFAULTED.value))
        .when(sme_managed_as_retail)
        .then(pl.lit(ExposureClass.RETAIL_OTHER.value))
        .otherwise(pl.col("exposure_class"))
        .alias("exposure_class_applied")
    )


@cites("CRR Art. 235")
def _add_post_crm_reporting_class(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Add ``exposure_class_post_crm`` — the post-guarantee (post-substitution) class.

    The reconciliation ties out on a post-guarantee basis, so the guaranteed slice
    must be reported under the GUARANTOR's class (CRR Art. 235 substitution) while
    everything else keeps its obligor applied class. A guaranteed exposure is
    physically split into a ``__G_`` guaranteed leg and a ``__REM`` retained leg
    (``engine/crm/guarantees.py``); only the guaranteed leg carries
    ``is_guaranteed=True`` and the guarantor's class in
    ``post_crm_exposure_class_guaranteed``, so:

    - guaranteed leg -> ``post_crm_exposure_class_guaranteed`` (guarantor class)
    - retained leg / unguaranteed exposure -> ``exposure_class_applied``

    ``exposure_class_applied`` stays the PRE-substitution class that COREP C 07.00
    keys its sheet + substitution flows on; this is its post-substitution twin,
    consumed by the reconciliation's by-class allocation so our totals per class
    tie to a post-guarantee legacy extract. A guaranteed leg whose guarantor class
    is unresolved (null / empty) falls back to the applied class.
    """
    guarantor_class = pl.col("post_crm_exposure_class_guaranteed")
    return lf.with_columns(
        pl.when(
            (pl.col("is_guaranteed") == True)  # noqa: E712
            & guarantor_class.is_not_null()
            & (guarantor_class != "")
        )
        .then(guarantor_class)
        .otherwise(pl.col("exposure_class_applied"))
        .alias("exposure_class_post_crm")
    )


@cites("CRR Art. 235")
def _add_post_crm_reporting_approach(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Add ``approach_post_crm`` — the post-guarantee (post-substitution) approach.

    The approach twin of :func:`_add_post_crm_reporting_class`. Where the guaranteed
    slice is reported under the GUARANTOR's class, it must also be reported under the
    approach the guarantor exposure is treated with, so the class and the approach
    partition the same post-guarantee money consistently:

    - guaranteed leg, SA guarantor -> ``standardised`` (Art. 235 risk-weight
      substitution treats the protected portion as a direct SA exposure to the
      guarantor)
    - guaranteed leg, IRB guarantor -> the obligor's ``approach_applied`` (Art. 161 /
      CRE22.70-85 parameter substitution keeps the exposure under IRB)
    - retained leg / unguaranteed exposure -> ``approach_applied``

    ``approach_applied`` stays the approach the row's RWA was computed under (the
    branch it ran through); this is its post-substitution twin, consumed by the
    reconciliation's post-guarantee by-class x method allocation and by the post-CRM
    detailed reporting view.

    References:
        CRR Art. 235: SA risk-weight substitution on the protected portion.
        CRR Art. 161 / CRE22.70-85: IRB parameter substitution.
    """
    return lf.with_columns(_post_crm_approach_expr().alias("approach_post_crm"))


def _post_crm_approach_expr() -> pl.Expr:
    """The post-guarantee (post-substitution) approach for one exposure row.

    Single source of the rule (relocated from the retired ``_crm_reporting``
    module in Phase 7 S4):

    - a guaranteed leg with an SA guarantor is a direct SA exposure to the guarantor
      (CRR Art. 235 risk-weight substitution) -> ``standardised``
    - a guaranteed leg with an IRB guarantor stays under the obligor's IRB approach
      (CRR Art. 161 / CRE22.70-85 parameter substitution) -> ``approach_applied``
    - everything else keeps ``approach_applied``

    Requires ``is_guaranteed``, ``guarantor_approach`` and ``approach_applied`` —
    all sealed on every calculator branch exit. A null ``is_guaranteed`` makes the
    predicate null, which ``when`` routes to ``otherwise`` (the obligor's approach),
    so no fill is needed — mirroring ``_add_post_crm_reporting_class``.
    """
    return (
        pl.when(
            (pl.col("is_guaranteed") == True)  # noqa: E712
            & (pl.col("guarantor_approach") == "sa")
        )
        .then(pl.lit(ApproachType.SA.value))
        .otherwise(pl.col("approach_applied"))
    )


@cites("CRR Art. 235")
@cites("CRR Art. 112")
def _add_reporting_projection(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Add the canonical per-leg reporting projection (Phase 7 S2).

    The results frame IS the two-leg substitution ledger — CRM physically splits
    each guaranteed exposure into ``__G_<guarantor>`` guaranteed legs and
    ``__REM`` / ``__REM_FL`` / ``__REM_SEN`` retained legs
    (``engine/crm/guarantees.py``). This projection names that ledger once, on
    the sealed exit, so no downstream consumer re-derives class/approach/method
    or sniffs reference suffixes (COREP, Pillar 3, reconciliation, and the UI
    all read these columns instead of re-picking among the raw twins):

    - ``reporting_class`` — post-substitution class the RWA is bucketed under
      (Art. 235: guarantor class on guaranteed legs) = ``exposure_class_post_crm``.
    - ``reporting_class_origin`` — obligor applied class, uniform across a
      guaranteed exposure's legs (Art. 112/123) = ``exposure_class_applied``.
    - ``reporting_approach`` / ``reporting_approach_origin`` — the post- and
      pre-substitution approach twins (``approach_post_crm`` / ``approach_applied``).
    - ``reporting_method`` — the STD/FIRB/AIRB/SLOTTING/EQUITY methodology label
      of the post-substitution approach (``method_label_expr`` materialised).
    - ``reporting_leg_role`` — ``guaranteed`` (the ``__G_`` leg,
      ``is_guaranteed=True``), ``retained`` (the ``__REM*`` remainder /
      Art. 234 tranche legs), or ``whole``. COREP C 07.00 substitution
      outflow/inflow reconstruct as two sums over the ``guaranteed`` legs
      grouped by origin vs post-substitution class.
    - ``reporting_on_balance_sheet`` — declared at source from
      ``exposure_type`` (loan -> on; facility/contingent -> off; anything else
      null = excluded from both on- and off-BS template cells). Mirrors the
      production rule in ``reporting/kernel/filters.py`` (``bs_type`` never
      reaches the aggregator, so the exposure-type rule IS today's behaviour).
    - ``reporting_subclass`` / ``reporting_ead`` / ``reporting_rw`` — aliases of
      ``exposure_subclass`` / ``ead_final`` / ``risk_weight``.
    - ``guarantee_rwa_benefit`` (Phase 7 decision F8, recorded) — the additive
      per-leg Art. 235/236 substitution relief:
      ``ead_final x guarantee_benefit_rw`` = leg EAD x (borrower-basis RW -
      substituted RW). PRE-supporting-factor and PRE-floor by definition (the
      branch snapshots the delta before Art. 501/501a and the portfolio
      floor), isolating the substitution effect; the applied delta already
      folds the double-default override (Art. 153(3)) and the Art. 160(4)
      no-better-than-direct floor, so the benefit ties exactly to the relief
      the engine granted. 0.0 on retained/whole/non-beneficial legs; NULL
      where the substitution machinery never ran (unguaranteed runs, where
      the branch delta column is absent). Slotting legs substitute via
      RWSM (Art. 235(1), fixed 2026-07-12) and carry real benefits on the
      slotting borrower basis.

    Called after the residual multiplier and the output floor so the aliases
    mirror the sealed final values. Per-row post-floor RWA is deliberately NOT
    projected here — the floor is a portfolio-level max and its per-row
    allocation is a recorded-decision slice of its own (Phase 7 plan S5).
    """
    is_retained_leg = pl.col("exposure_reference").str.contains(r"__REM(?:_FL|_SEN)?$")
    leg_role = (
        pl.when(pl.col("is_guaranteed") == True)  # noqa: E712
        .then(pl.lit("guaranteed"))
        .when(is_retained_leg)
        .then(pl.lit("retained"))
        .otherwise(pl.lit("whole"))
    )
    on_balance_sheet = (
        pl.when(pl.col("exposure_type") == "loan")
        .then(pl.lit(True))
        .when(pl.col("exposure_type").is_in(["facility", "contingent"]))
        .then(pl.lit(False))
        .otherwise(pl.lit(None, dtype=pl.Boolean))
    )
    if "guarantee_benefit_rw" in lf.collect_schema().names():
        # Every branch (SA/IRB/slotting) produces the delta on guaranteed
        # runs; non-beneficial legs are clamped to 0.0 at the branch.
        rwa_benefit = pl.col("ead_final") * pl.col("guarantee_benefit_rw")
    else:
        rwa_benefit = pl.lit(None, dtype=pl.Float64)
    return lf.with_columns(
        pl.col("exposure_class_post_crm").alias("reporting_class"),
        pl.col("exposure_class_applied").alias("reporting_class_origin"),
        pl.col("approach_post_crm").alias("reporting_approach"),
        pl.col("approach_applied").alias("reporting_approach_origin"),
        method_label_expr("approach_post_crm").alias("reporting_method"),
        leg_role.alias("reporting_leg_role"),
        on_balance_sheet.alias("reporting_on_balance_sheet"),
        pl.col("exposure_subclass").alias("reporting_subclass"),
        pl.col("ead_final").alias("reporting_ead"),
        pl.col("risk_weight").alias("reporting_rw"),
        rwa_benefit.alias("guarantee_rwa_benefit"),
    )


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


def _detect_non_finite_errors(results_df: pl.DataFrame) -> list[CalculationError]:
    """Surface NaN/inf in the per-row outputs (AGG001) and IRB inputs (AGG002).

    Polars float ``.sum()`` propagates a NaN (it is not skipped like a null), so a
    single non-finite value would blank the portfolio totals and the summary
    charts. Rather than silently degrade, the aggregator records:

    - **AGG001 (error)** for the final output columns the cards/charts/summaries
      consume — ``rwa_final`` / ``ead_final`` / ``risk_weight``. The sealed
      ``reporting_ead`` / ``reporting_rw`` the by-class/by-approach summaries
      aggregate are per-leg aliases of ``ead_final`` / ``risk_weight`` (Phase 7
      S2), so this scan covers them by construction — the retired
      ``post_crm_detailed`` re-split, which could mint NEW values, no longer
      exists. ``ErrorSeverity.ERROR`` (not critical) keeps the run successful
      so the unaffected rows still report.
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
