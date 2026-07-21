"""
Literal stage registry for the RWA pipeline (migration Phase 4).

Pipeline position:
    Consumed by the PipelineOrchestrator facade (engine/pipeline.py), which
    folds a PipelineContext through these stages via
    ``orchestrator.run_stages``.

Key responsibilities:
- The single ordered, literal list of pipeline stages — one screen, no
  conditionals. Conditional behaviour (CCR no-op without a derivatives
  book, floor-gated SA wiring, RE-split no-op) lives INSIDE the stage
  functions, never in the registry.
- Stage names are the ``stage_timer`` labels pinned by the observability
  tests; failure policies are verbatim ports of the pre-fold per-stage
  behaviour (see ``StageSpec.halt``).

References:
- CRR Art. 107: Approaches to credit risk (the stage wiring this orders)
- docs/plans/target-architecture-migration.md (Phase 4 — uniform stage model)
"""

from __future__ import annotations

import logging

from rwa_calc.engine.orchestrator import StageSpec
from rwa_calc.engine.stages import (
    aggregate,
    calc,
    ccr,
    classify,
    crm,
    equity,
    re_split,
    scope,
    securitisation,
    sft,
)
from rwa_calc.engine.stages import (
    hierarchy as hierarchy_stage,
)

logger = logging.getLogger(__name__)

PIPELINE_STAGES: tuple[StageSpec, ...] = (
    StageSpec("resolve_scope", scope.run, error_type="scope_error"),
    StageSpec("securitisation_allocator", securitisation.run, error_type="allocation_error"),
    StageSpec("hierarchy_resolver", hierarchy_stage.run, error_type="resolution_error"),
    StageSpec("ccr_sa_ccr", ccr.run, error_type="ccr_error"),
    StageSpec("sft_fccm", sft.run, error_type="sft_error"),
    StageSpec("classifier", classify.run, error_type="classification_error"),
    StageSpec("crm_processor", crm.run, error_type="crm_error"),
    StageSpec("re_splitter", re_split.run, error_type="re_split_error"),
    StageSpec("calculators", calc.run, error_type="calculation_error", halt="merged"),
    StageSpec("equity_calculator", equity.run, error_type="equity_calculation_error"),
    StageSpec("aggregator", aggregate.run, error_type="aggregation_error", halt="merged"),
)
