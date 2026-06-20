"""
SFT FCCM stage adapter (SFT/FCCM separation Phase 5).

Pipeline position:
    hierarchy_resolver -> ccr_sa_ccr -> sft_fccm -> classifier

Key responsibilities:
- Translate the optional ``data.sft`` bundle (a :class:`RawSFTBundle`) into one
  synthetic exposure row per SFT netting set with ``drawn_amount = E*``
  (CRR Art. 223(5): E* = max(0, E·(1+HE) − CVA·(1−HC−HFX))) and append those
  rows to the resolved exposures via ``diagonal_relaxed`` concat, so the unified
  pipeline consumes them without SFT-aware special-casing downstream.
- Inherit the resolved counterparty rating columns onto each synthetic row so
  the SA institution lookup (CRR Art. 120(1) Table 3) and IRB routing see the
  same ratings as traditional lending rows (shared with the SA-CCR stage via
  ``engine.stages._ccr_shared.enrich_ccr_rows_with_ratings``).
- Re-seal the stage exit against the EXISTING ``ccr_exit`` contract — NOT a new
  ``sft_exit`` brand. Downstream stages select their CCR-variant edge by exact
  brand-string equality (``classifier.py`` -> ``ccr_exit``), and SFT rows share
  the ``resolved.exposures`` frame with SA-CCR derivative rows. A fresh brand
  would de-select the SFT rows onto the non-CCR edge and strip their provenance
  columns (``source_netting_set_id`` / ``ccr_method`` / ``ead_ccr``). The SA-CCR
  stage and this stage both ``replace(resolved, exposures=...)`` sealing to
  ``ccr_exit``; the last writer's brand is what the classifier expects.
- No-op when ``data.sft is None`` (firm has no SFT book) and when the SFT trade
  frame is empty (zero rows -> nothing to append), exactly as the SA-CCR stage
  tolerates an empty / absent ``data.ccr``.

References:
- CRR Art. 271(2) (SFT EAD via FCCM, not SA-CCR Art. 274)
- CRR Art. 220(1)(a) (single-counterparty SFT scope)
- CRR Art. 223(5) (E* = max(0, E·(1+HE) − CVA·(1−HC−HFX)))
- docs/plans/sft-fccm-separation.md (Phase 5 — peer stage, ccr_exit brand)
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.edges import CCR_EXIT_EDGE
from rwa_calc.engine.materialise import materialise_sealed_edge
from rwa_calc.engine.orchestrator import RAW_DATA, RESOLVED_HIERARCHY
from rwa_calc.engine.sft.fccm import sft_bundle_to_exposures
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
    """Run the SFT FCCM adapter over the resolved hierarchy.

    No-ops only when the firm has no SFT book (``data.sft is None``). An empty
    (non-None) SFT bundle — the common registry-load shape when no sft parquet
    exists — still runs the chain: the FCCM core emits zero rows, the
    ``diagonal_relaxed`` concat is a no-op, and the frame re-seals to ccr_exit
    with the provenance columns null. This mirrors the SA-CCR stage, which
    likewise returns early only on ``data.ccr is None`` and re-seals an empty
    derivatives book to ccr_exit.
    """
    data = ctx.get(RAW_DATA)
    if data.sft is None:
        logger.debug("no SFT inputs - skipping SFT FCCM stage")
        return ctx

    resolved = ctx.get(RESOLVED_HIERARCHY)

    sft_exposure_rows = sft_bundle_to_exposures(data.sft, run_config.reporting_date)
    # Inherit the resolved counterparty rating columns onto each SFT synthetic
    # row so the SA institution lookup (CRR Art. 120(1) Table 3, keyed off
    # ``cqs``) and any IRB routing (keyed off ``internal_pd``) see the same
    # rating that ``hierarchy._attach_counterparty_rating`` joined onto
    # traditional lending rows.
    sft_exposure_rows = enrich_ccr_rows_with_ratings(
        sft_exposure_rows, resolved.counterparty_lookup
    )

    new_exposures = pl.concat(
        [resolved.exposures, sft_exposure_rows],
        how="diagonal_relaxed",
    )
    # When the SA-CCR stage ran ahead of us, ``resolved.exposures`` already
    # carries the ccr_exit provenance columns (filled null on non-CCR rows).
    # On a pure-SFT run (no derivatives book) they are ABSENT — the FCCM path
    # never projects them and there was no SA-CCR concat to add them — so the
    # ccr_exit contract's required SA-CCR columns must be injected as typed
    # nulls before the seal, exactly as ``diagonal_relaxed`` would fill them
    # against a derivative frame. Driven by the contract itself (no hand-kept
    # column list) so it stays correct as CCR_EXIT_EDGE evolves.
    new_exposures = _ensure_ccr_exit_columns(new_exposures)
    # Re-seal against the EXISTING ccr_exit contract (Section 3 of the
    # separation plan) — the SA-CCR provenance columns stay null on SFT rows
    # because the FCCM path never projects them.
    new_resolved = replace(
        resolved,
        exposures=materialise_sealed_edge(new_exposures, run_config, CCR_EXIT_EDGE),
    )
    return ctx.put(RESOLVED_HIERARCHY, new_resolved)


def _ensure_ccr_exit_columns(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Inject any absent ``CCR_EXIT_EDGE`` column as a typed null.

    A no-op when the SA-CCR stage already ran (the provenance columns exist);
    fills the gap on a pure-SFT run so the subsequent ``ccr_exit`` seal does
    not raise on its required SA-CCR-only columns. The set of columns is read
    from the edge contract so this never drifts from ``CCR_EXIT_EDGE``.
    """
    present = set(exposures.collect_schema().names())
    additions = [
        pl.lit(None).cast(col.dtype).alias(name)
        for name, col in CCR_EXIT_EDGE.columns.items()
        if name not in present
    ]
    return exposures.with_columns(additions) if additions else exposures
