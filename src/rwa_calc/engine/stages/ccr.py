"""
SA-CCR stage adapter (P8.20).

Pipeline position:
    hierarchy_resolver -> ccr_sa_ccr -> classifier

Key responsibilities:
- Translate the optional ``data.ccr`` bundle into one synthetic exposure
  row per netting set with ``drawn_amount = EAD_CCR`` (CRR Art. 274(2):
  EAD = alpha * (RC + PFE)) and append those rows to the resolved
  exposures via ``diagonal_relaxed`` concat, so the unified pipeline
  consumes them without CCR-aware special-casing downstream.
- Apply the Art. 272(4) legal-enforceability gate and the Art. 291(4)-(5)
  WWR gate before the EAD chain runs; forward their CCR001/CCR010/CCR011
  diagnostics to the STAGE_ERRORS channel verbatim — original
  code/severity/category preserved (error-channel slice, P2.21).
- Inherit resolved counterparty rating columns onto each synthetic row so
  the SA institution lookup (CRR Art. 120(1) Table 3) and IRB routing see
  the same ratings as traditional lending rows.
- Re-seal the stage exit against the ``ccr_exit`` contract (hierarchy_exit
  shape plus the SA-CCR provenance columns).
- No-op when ``data.ccr is None`` (firm has no derivatives book).

References:
- CRR Art. 271 (CCR scope); CRR Art. 272(4) (netting set)
- CRR Art. 274(2) (alpha * (RC + PFE)); CRR Art. 291(4)-(5) (WWR)
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.edges import CCR_EXIT_EDGE
from rwa_calc.engine.materialise import materialise_sealed_edge
from rwa_calc.engine.orchestrator import (
    RAW_DATA,
    RESOLVED_HIERARCHY,
    append_stage_errors,
)
from rwa_calc.engine.stages._ccr_shared import enrich_ccr_rows_with_ratings

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.context import PipelineContext
    from rwa_calc.rulebook import RulepackV0

logger = logging.getLogger(__name__)


def run(
    ctx: PipelineContext,
    rulepack: RulepackV0,
    run_config: CalculationConfig,
) -> PipelineContext:
    """Run the SA-CCR pipeline adapter over the resolved hierarchy."""
    data = ctx.get(RAW_DATA)
    if data.ccr is None:
        logger.debug("no CCR inputs - skipping SA-CCR stage")
        return ctx

    from rwa_calc.contracts.ccr_collateral_checks import collect_findings
    from rwa_calc.engine.ccr import (
        apply_legal_enforceability_gate,
        apply_wwr_gate,
        attach_orphan_trade_netting_sets,
        ccr_rows_to_exposures,
        partition_out_sft_rows,
    )
    from rwa_calc.engine.ccr.findings import derivative_findings

    resolved = ctx.get(RESOLVED_HIERARCHY)

    # SFT/FCCM separation (Phase 6): the SA-CCR Art. 274 chain is
    # derivatives-only. SFT EAD (CRR Art. 271(2), Art. 220-223 FCCM) is
    # computed by the peer ``sft_fccm`` stage from ``RawDataBundle.sft``.
    # Strip — and flag via the unified error channel — any mis-placed
    # ``transaction_type == "sft"`` row that still arrives in
    # ``RawDataBundle.ccr`` so it cannot be silently mis-priced as a
    # derivative. This single invariant subsumes the double-count guard:
    # forbidding SFT in ``raw.ccr`` removes the only path to compute the same
    # SFT EAD twice (here AND in ``sft_fccm``).
    derivatives_only, sft_input_errors = partition_out_sft_rows(data.ccr)
    ctx = append_stage_errors(ctx, *sft_input_errors)

    # Apply the Art. 272(4) legal-enforceability gate first so
    # non-enforceable netting sets are split into single-trade synthetic
    # NSes before the EAD chain runs, then the Art. 291(4)-(5) WWR gate so
    # specific-WWR trades break out into their own synthetic netting sets
    # (LGD = 100%). A trade whose netting set is missing from the input gets a
    # non-enforceable stand-in first, so it is priced alone rather than dropped
    # (review CC-06; reported as CCR023 by the input gate).
    raw_ccr_gated = apply_wwr_gate(
        apply_legal_enforceability_gate(attach_orphan_trade_netting_sets(derivatives_only))
    )
    # Unified error channel: the gates' CCR001/CCR010/CCR011 diagnostics
    # reach the result verbatim — original code/severity/category preserved.
    ctx = append_stage_errors(ctx, *raw_ccr_gated.errors)
    # Review cluster saccr_b: CCR025 margin-term conflicts, CCR024 collateral left
    # out of VM / NICA and CCR026 amounts with no rate to the reporting currency —
    # built from the same engine/ccr expressions that price the netting sets.
    ctx = append_stage_errors(
        ctx,
        *collect_findings(
            derivative_findings(
                derivatives_only, raw_ccr_gated, data.fx_rates, run_config, rulepack.pack
            )
        ),
    )
    ccr_exposure_rows = ccr_rows_to_exposures(
        raw_ccr_gated,
        run_config.ccr,
        run_config.reporting_date,
        base_currency=run_config.base_currency,
        fx_rates=data.fx_rates,
        # Art. 276(1)(d): CCR collateral takes the run regime's Art. 224 haircuts;
        # Art. 279b(3): amounts are rebased to the reporting currency unless the
        # run has FX conversion switched off.
        calculation_config=run_config,
        rulepack=rulepack.pack,
        rebase_amounts=run_config.apply_fx_conversion,
        # Art. 274(2): the counterparty frame carries the ``counterparty_type``
        # discriminator that selects the per-NS supervisory alpha — the α = 1
        # NFC / pension carve-out is PS1/26 text, so it is gated on the cited
        # pack Feature (off under CRR, where α = 1.4 for every netting set).
        counterparties=data.counterparties,
        alpha_nfc_carve_out_applicable=rulepack.pack.feature(
            "sa_ccr_alpha_nfc_carve_out_applicable"
        ),
        # PRA PS1/26 Art. 274(2A): the transitional alpha add-on is
        # Basel 3.1 only — gate it on the cited pack Feature so it never
        # fires under CRR. The add-on branch keeps its ``is_basel_3_1`` bool
        # plumbing param; only this regime read moves to the pack (S9a).
        is_basel_3_1=rulepack.pack.feature("ccr_transitional_alpha_addon_applicable"),
    )
    # Inherit the resolved counterparty rating columns onto each CCR
    # synthetic row so the downstream SA Institution lookup (CRR
    # Art. 120(1) Table 3, keyed off ``cqs``) and any IRB routing (keyed
    # off ``internal_pd``) see the same rating that
    # ``enrich.attach_counterparty_rating`` joined onto traditional
    # lending rows. Without this enrichment, CCR rows arrive at the SA
    # calculator with ``cqs=None`` and fall through to the 100%
    # unrated-institution fallback.
    ccr_exposure_rows = enrich_ccr_rows_with_ratings(
        ccr_exposure_rows, resolved.counterparty_lookup
    )
    concat_frames = [resolved.exposures, ccr_exposure_rows]

    # CCR Art. 378/379 settlement risk: when the firm reports failed (DvP /
    # non-DvP free-delivery) settlements, shape each into a synthetic ``ft__``
    # row — an own-funds line (drawn_amount = own funds, RW pinned to 12.5) or,
    # for an Art. 379 Column 3 free delivery, an ordinary credit exposure — so
    # the settlement-risk RWA reaches the aggregated totals.
    if data.ccr.failed_trades is not None:
        from rwa_calc.engine.ccr.failed_trades import failed_trade_exposure_rows

        failed_trade_rows = failed_trade_exposure_rows(
            data.ccr.failed_trades.failed_trades, run_config
        )
        concat_frames.append(
            enrich_ccr_rows_with_ratings(failed_trade_rows, resolved.counterparty_lookup)
        )

    # CCR Art. 308/309 CCP default-fund contributions: when the firm reports
    # clearing-member default-fund contributions, compute their K_CM / RWEA
    # via ``compute_dfc_capital`` and shape each row into a synthetic SA
    # exposure (drawn_amount = K_CM, RW pinned to 12.5 in the SA override
    # chain) so the default-fund RWEA reaches the aggregated totals.
    if data.ccr.default_fund_contributions is not None:
        from rwa_calc.engine.ccr.default_fund import compute_dfc_capital

        dfc_rows = _dfc_rows_to_exposures(
            data.ccr.default_fund_contributions,
            run_config,
            compute_dfc_capital,
        )
        concat_frames.append(enrich_ccr_rows_with_ratings(dfc_rows, resolved.counterparty_lookup))

    new_exposures = pl.concat(
        concat_frames,
        how="diagonal_relaxed",
    )
    # Stage-exit edge (only when CCR rows were appended): the
    # hierarchy_exit shape plus the SA-CCR provenance columns — synthetic
    # rows may not otherwise reshape the frame.
    new_resolved = replace(
        resolved,
        exposures=materialise_sealed_edge(new_exposures, run_config, CCR_EXIT_EDGE),
    )
    return ctx.put(RESOLVED_HIERARCHY, new_resolved)


def _dfc_rows_to_exposures(
    default_fund_contributions: pl.LazyFrame,
    run_config: CalculationConfig,
    compute_dfc_capital: Callable[[pl.LazyFrame, CalculationConfig], pl.LazyFrame],
) -> pl.LazyFrame:
    """Shape default-fund-contribution K_CM into synthetic SA exposure rows.

    CCR Art. 307-310 CCP default-fund contributions: each contribution
    carries an own-funds requirement ``k_cm`` — Art. 308(2) max(K_CCP x DF_i /
    (DF_CCP + DF_CM), 8% x 2% x DF_i) for a QCCP pre-funded contribution,
    Art. 309(1) K = DF + UC for a non-QCCP, 0 for an Art. 310 QCCP unfunded
    contribution. The synthetic row sets ``drawn_amount = k_cm`` and
    tags itself with ``risk_type = "CCR_DEFAULT_FUND"`` so the SA override
    chain pins its risk weight to the own-funds->RWA factor (12.5, Art.
    92(3)(ca)); the downstream EAD x RW then reproduces the upstream
    ``dfc_rwea`` (K_CM x 12.5, Art. 308(3) / 309(2)). The ``ccp_reference``
    becomes the synthetic row's ``counterparty_reference`` so the rating
    enrichment join lines up.

    References:
        CRR Art. 308(2)/(3); CRR Art. 309(1)/(2); CRR Art. 92(3)(ca).
    """
    computed = compute_dfc_capital(default_fund_contributions, run_config)
    return computed.select(
        pl.concat_str([pl.lit("dfc__"), pl.col("contribution_id")]).alias("exposure_reference"),
        # Reconciliation base: keep the ``dfc__`` namespace (no legacy
        # per-exposure equivalent; avoids collision with a loan reference).
        pl.concat_str([pl.lit("dfc__"), pl.col("contribution_id")]).alias(
            "source_exposure_reference"
        ),
        pl.lit("ccr_default_fund").alias("exposure_type"),
        pl.col("ccp_reference").alias("counterparty_reference"),
        pl.lit(run_config.reporting_date).alias("value_date"),
        pl.lit(run_config.reporting_date).alias("maturity_date"),
        pl.col("k_cm").alias("drawn_amount"),
        pl.lit(0.0).alias("interest"),
        pl.lit(0.0).alias("undrawn_amount"),
        pl.lit(0.0).alias("nominal_amount"),
        pl.lit("senior").alias("seniority"),
        pl.lit("CCR_DEFAULT_FUND").alias("risk_type"),
        pl.lit("default_fund").alias("ccr_method"),
        # Audit columns reconciling the synthetic row back to Art. 308/309.
        pl.col("regulatory_band"),
        pl.col("k_ccp_published"),
        pl.col("k_cm"),
        pl.col("dfc_rwea"),
    )
