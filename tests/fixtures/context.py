"""
Sanctioned PipelineContext builder for tests (migration Phase 4).

Mirrors the bundle-builder family (raw_bundle.py / resolved_bundle.py):
tests never construct ``PipelineContext`` directly (enforced by
``tests/contracts/test_builder_conformance.py``) — this builder seeds the
orchestration artifact channels with their canonical defaults exactly as
``PipelineOrchestrator.run_with_data`` does, so stage adapters under test
see production-shaped contexts.

References:
- docs/plans/target-architecture-migration.md (Phase 4 — uniform stage model)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rwa_calc.contracts.context import ArtifactKey, PipelineContext
from rwa_calc.engine.orchestrator import (
    COMPONENTS,
    PIPELINE_ERRORS,
    SECURITISATION_RESOLVED,
    STAGE_ERRORS,
    build_components,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


def make_context(
    *pairs: tuple[ArtifactKey[Any], Any],
    config: CalculationConfig | None = None,
    **component_overrides: Any,
) -> PipelineContext:
    """Build a PipelineContext with canonical orchestration defaults.

    Args:
        *pairs: ``(key, value)`` artifact pairs written after the defaults.
        config: when supplied, per-run components are built from it (with
            ``component_overrides`` honoured, e.g. ``classifier=mock``) and
            written under the COMPONENTS key — exactly as the facade does.
        **component_overrides: keyword overrides forwarded to
            ``build_components``.

    Returns:
        A context carrying empty error channels (PIPELINE_ERRORS for stage
        crashes, STAGE_ERRORS for verbatim stage data-quality errors), a
        None securitisation lookup, optional components, and the supplied
        artifacts.
    """
    ctx = (
        PipelineContext.empty()
        .put(SECURITISATION_RESOLVED, None)
        .put(PIPELINE_ERRORS, ())
        .put(STAGE_ERRORS, ())
    )
    if config is not None:
        ctx = ctx.put(COMPONENTS, build_components(config, **component_overrides))
    for key, value in pairs:
        ctx = ctx.put(key, value)
    return ctx
