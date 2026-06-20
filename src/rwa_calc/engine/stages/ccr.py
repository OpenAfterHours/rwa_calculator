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

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import CounterpartyLookup
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

    from rwa_calc.engine.ccr import (
        apply_legal_enforceability_gate,
        apply_wwr_gate,
        ccr_rows_to_exposures,
    )

    resolved = ctx.get(RESOLVED_HIERARCHY)

    # Apply the Art. 272(4) legal-enforceability gate first so
    # non-enforceable netting sets are split into single-trade synthetic
    # NSes before the EAD chain runs, then the Art. 291(4)-(5) WWR gate so
    # specific-WWR trades break out into their own synthetic netting sets
    # (LGD = 100%).
    raw_ccr_gated = apply_wwr_gate(apply_legal_enforceability_gate(data.ccr))
    # Unified error channel: the gates' CCR001/CCR010/CCR011 diagnostics
    # reach the result verbatim — original code/severity/category preserved.
    ctx = append_stage_errors(ctx, *raw_ccr_gated.errors)
    ccr_exposure_rows = ccr_rows_to_exposures(
        raw_ccr_gated,
        run_config.ccr,
        run_config.reporting_date,
        base_currency=run_config.base_currency,
        fx_rates=data.fx_rates,
        # CRR Art. 274(2): the counterparty frame carries the
        # ``counterparty_type`` discriminator that selects the per-NS
        # supervisory alpha (1.0 carve-out vs 1.4 default).
        counterparties=data.counterparties,
        # PRA PS1/26 Art. 274(2A): the transitional alpha add-on is
        # Basel 3.1 only — gate it on the cited pack Feature so it never
        # fires under CRR. The add-on branch keeps its ``is_basel_3_1`` bool
        # plumbing param; only this regime read moves to the pack (S9a).
        is_basel_3_1=rulepack.pack.feature("ccr_transitional_alpha_addon_applicable"),
        # CRR Art. 271(2): SFT EAD method now lives on the peer SFTConfig
        # (SFT/FCCM separation, Phase 3). "fccm" routes SFT trades through
        # FCCM (Art. 220-223); reserved "var"/"imm" fail loud in the adapter.
        sft_method=run_config.sft.method,
    )
    # Inherit the resolved counterparty rating columns onto each CCR
    # synthetic row so the downstream SA Institution lookup (CRR
    # Art. 120(1) Table 3, keyed off ``cqs``) and any IRB routing (keyed
    # off ``internal_pd``) see the same rating that
    # ``hierarchy._attach_counterparty_rating`` joined onto traditional
    # lending rows. Without this enrichment, CCR rows arrive at the SA
    # calculator with ``cqs=None`` and fall through to the 100%
    # unrated-institution fallback.
    ccr_exposure_rows = _enrich_ccr_rows_with_ratings(
        ccr_exposure_rows, resolved.counterparty_lookup
    )
    concat_frames = [resolved.exposures, ccr_exposure_rows]

    # CCR Art. 378/379 settlement risk: when the firm reports failed (DvP /
    # non-DvP free-delivery) settlements, compute their own-funds / RWA via
    # ``compute_failed_trade_rwa`` and shape each row into a synthetic SA
    # exposure (drawn_amount = own_funds_requirement, RW pinned to 12.5 in the
    # SA override chain) so the failed-trade RWA reaches the aggregated totals.
    if data.ccr.failed_trades is not None:
        from rwa_calc.engine.ccr.failed_trades import compute_failed_trade_rwa

        failed_trade_rows = _failed_trade_rows_to_exposures(
            data.ccr.failed_trades.failed_trades,
            run_config,
            compute_failed_trade_rwa,
        )
        concat_frames.append(
            _enrich_ccr_rows_with_ratings(failed_trade_rows, resolved.counterparty_lookup)
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
        concat_frames.append(_enrich_ccr_rows_with_ratings(dfc_rows, resolved.counterparty_lookup))

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


def _failed_trade_rows_to_exposures(
    failed_trades: pl.LazyFrame,
    run_config: CalculationConfig,
    compute_failed_trade_rwa: Callable[[pl.LazyFrame, CalculationConfig], pl.LazyFrame],
) -> pl.LazyFrame:
    """Shape failed-trade own-funds requirements into synthetic SA exposure rows.

    CCR Art. 378/379 settlement risk: each failed trade carries an own-funds
    requirement (DvP price-difference x multiplier, or non-DvP exposure). The
    synthetic row sets ``drawn_amount = own_funds_requirement`` and tags itself
    with ``risk_type = "SETTLEMENT_FAILED_TRADE"`` so the SA override chain pins
    its risk weight to the own-funds->RWA factor (12.5, Art. 92(3)(ca)); the
    downstream EAD x RW then reproduces the upstream ``failed_trade_rwa``.

    References:
        CRR Art. 378 + Table 1; CRR Art. 379(1) + Table 2; CRR Art. 92(3)(ca).
    """
    computed = compute_failed_trade_rwa(failed_trades, run_config)
    return computed.select(
        pl.concat_str([pl.lit("ft__"), pl.col("failed_trade_id")]).alias("exposure_reference"),
        pl.lit("ccr_failed_trade").alias("exposure_type"),
        pl.col("counterparty_reference"),
        pl.lit(run_config.reporting_date).alias("value_date"),
        pl.lit(run_config.reporting_date).alias("maturity_date"),
        pl.col("own_funds_requirement").alias("drawn_amount"),
        pl.lit(0.0).alias("interest"),
        pl.lit(0.0).alias("undrawn_amount"),
        pl.lit(0.0).alias("nominal_amount"),
        pl.lit("senior").alias("seniority"),
        pl.lit("SETTLEMENT_FAILED_TRADE").alias("risk_type"),
        pl.lit("failed_trade").alias("ccr_method"),
        # Audit columns reconciling the synthetic row back to Art. 378/379.
        pl.col("regulatory_band"),
        pl.col("multiplier_or_rw"),
        pl.col("own_funds_requirement"),
        pl.col("failed_trade_rwa"),
        pl.col("price_difference"),
        pl.col("exposure_amount"),
    )


def _dfc_rows_to_exposures(
    default_fund_contributions: pl.LazyFrame,
    run_config: CalculationConfig,
    compute_dfc_capital: Callable[[pl.LazyFrame, CalculationConfig], pl.LazyFrame],
) -> pl.LazyFrame:
    """Shape default-fund-contribution K_CM into synthetic SA exposure rows.

    CCR Art. 308/309 CCP default-fund contributions: each contribution
    carries a clearing-member capital requirement (K_CM = K_CCP x DF_i /
    DF_CM, Art. 308(2)). The synthetic row sets ``drawn_amount = k_cm`` and
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


def _enrich_ccr_rows_with_ratings(
    ccr_exposure_rows: pl.LazyFrame,
    counterparty_lookup: CounterpartyLookup,
) -> pl.LazyFrame:
    """Join the resolved counterparty rating columns onto CCR rows.

    Mirrors the per-exposure rating attach performed by
    ``hierarchy._attach_counterparty_rating`` for traditional lending
    rows. The CCR pipeline adapter runs AFTER hierarchy resolution and
    appends synthetic rows via ``diagonal_relaxed`` concat, so without
    this enrichment those rows reach the SA calculator with ``cqs=None``
    / ``external_cqs=None`` / ``internal_pd=None`` and the institution
    risk-weight lookup falls through to its unrated 100% fallback
    (CRR Art. 121(1)) instead of the rated CQS table
    (CRR Art. 120(1) Table 3).
    """
    cp_schema = set(counterparty_lookup.counterparties.collect_schema().names())
    rating_cols = [c for c in ("cqs", "pd", "internal_pd", "external_cqs") if c in cp_schema]
    if not rating_cols:
        return ccr_exposure_rows
    cp_select = [pl.col("counterparty_reference"), *(pl.col(c) for c in rating_cols)]
    return ccr_exposure_rows.join(
        counterparty_lookup.counterparties.select(cp_select),
        on="counterparty_reference",
        how="left",
    )
