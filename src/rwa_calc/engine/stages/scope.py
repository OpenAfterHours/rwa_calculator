"""
Scope resolver stage adapter.

Pipeline position:
    (loader) -> resolve_scope -> securitisation_allocator

Key responsibilities:
- Uniform ``run(ctx, rulepack, run_config)`` adapter for the scope resolver:
  consume the loaded ``RawDataBundle`` (RAW_DATA artifact) and republish the
  SAME artifact key with a scope-filtered bundle, so every downstream stage is
  untouched.
- Publish ``GROUP_POPULATION`` — the whole reporting group's population — so
  the hierarchy and calculators stages can count, on a solo / sub-consolidated
  run, the debt an obligor owes to the OTHER group entities in the retail
  threshold and the Art. 501 E* (None when the run already covers the whole
  group).
- Identity no-op (provably zero-cost — the context is returned unchanged) when
  ``run_config.reporting_entity`` is None. This is the hard I1 invariant: an
  unscoped run behaves byte-identically to today.

References:
- CRR Part One Title II (Art. 6, 11-18): levels of application.
- CRR Art. 123(c) / 501(1); PS1/26 Art. 123A(1)(b)(ii): group-wide "amount owed".
- docs/plans/multi-entity-reporting.md: scope resolver specification.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rwa_calc.engine.orchestrator import GROUP_POPULATION, RAW_DATA
from rwa_calc.engine.scope.resolver import resolve_group_population, resolve_scope

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
    """Run the scope resolver stage.

    No-op (returns the context unchanged) when no reporting entity is
    configured. Otherwise republishes RAW_DATA with the scope-filtered bundle,
    passing the pack ``intragroup_zero_rw`` Feature so the resolver can compute
    the CRR Art. 113(6) core-UK-group 0% RW eligibility on an individual run,
    and publishes GROUP_POPULATION from the UNFILTERED bundle (the whole
    reporting group, read for the group-wide obligor aggregates).
    """
    if run_config.reporting_entity is None:
        return ctx

    data = ctx.get(RAW_DATA)
    return ctx.put(
        RAW_DATA,
        resolve_scope(
            data,
            run_config,
            intragroup_zero_rw=rulepack.pack.feature("intragroup_zero_rw"),
        ),
    ).put(GROUP_POPULATION, resolve_group_population(data, run_config))
