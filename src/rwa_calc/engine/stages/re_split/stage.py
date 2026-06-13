"""
Real-estate loan-splitter stage adapter.

Pipeline position:
    crm_processor -> re_splitter -> calculators

Key responsibilities:
- Run ``RealEstateSplitter.split`` (CRR Art. 125/126, B3.1 Art. 124F/H):
  materialises the secured RE row and the uncollateralised residual row
  for property-collateralised SA exposures. No-op when no rows carry
  ``re_split_mode``.
- Materialise + re-brand the stage exit under the splitter's own brand
  (``re_split_exit`` / ``re_split_exit_ccr``) — the calculators' branch
  split forks the plan three ways, so their input must be eager-backed.
- Forward NEW splitter errors (RE*) to the STAGE_ERRORS channel verbatim,
  skipping errors already accounted for by the CRM stage (frozen-dataclass
  equality dedup) — original code/severity/category preserved
  (error-channel slice, P2.21).
- Opt-in audit cache: sink the per-parent secured/residual reconciliation.

References:
- CRR Art. 125/126; PRA PS1/26 Art. 124F/124H (RE exposure splitting)
- docs/plans/target-architecture-migration.md (Phase 4)
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from rwa_calc.contracts.edges import (
    RE_SPLIT_EXIT_CCR_EDGE,
    RE_SPLIT_EXIT_EDGE,
    sealed_edge_of,
)
from rwa_calc.engine.materialise import materialise_sealed_edge
from rwa_calc.engine.orchestrator import (
    COMPONENTS,
    CRM_ADJUSTED,
    append_stage_errors,
)
from rwa_calc.observability.audit_cache import sink_audit

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.context import PipelineContext
    from rwa_calc.rulebook import RulepackV0

logger = logging.getLogger(__name__)


def run(
    ctx: PipelineContext,
    rulepack: RulepackV0,  # noqa: ARG001 — uniform stage signature (Phase 4)
    run_config: CalculationConfig,
) -> PipelineContext:
    """Run the real estate loan-splitter stage."""
    crm_adjusted = ctx.get(CRM_ADJUSTED)
    components = ctx.get(COMPONENTS)

    result = components.re_splitter.split(crm_adjusted, run_config)

    # Stage-exit edge: the calculators' branch split forks the plan three
    # ways, so their input must be eager-backed. The splitter's pure-plan
    # seal carries the contract; this materialises and re-brands the
    # eager-backed wrap under the same contract (selected by the
    # splitter's brand).
    exit_edge = (
        RE_SPLIT_EXIT_CCR_EDGE
        if sealed_edge_of(result.exposures) == "re_split_exit_ccr"
        else RE_SPLIT_EXIT_EDGE
    )
    result = replace(
        result,
        exposures=materialise_sealed_edge(
            result.exposures, run_config, exit_edge, label="re_split_exit"
        ),
    )

    # Splitter accumulates errors into the CRM bucket so existing error
    # reporting continues to capture them; skip duplicates already
    # accounted for upstream by the CRM stage (frozen-dataclass equality).
    # Unified error channel: NEW splitter errors (RE*) reach the result
    # verbatim — original code/severity/category preserved, never PIPELINE_*.
    new_errors = [error for error in result.crm_errors if error not in crm_adjusted.crm_errors]
    ctx = append_stage_errors(ctx, *new_errors)

    # Opt-in audit cache: per-parent secured/residual split reconciliation.
    # Only present when at least one exposure triggered RE splitting.
    if result.re_split_audit is not None:
        sink_audit(result.re_split_audit, run_config, "re_split_audit")

    return ctx.put(CRM_ADJUSTED, result)
