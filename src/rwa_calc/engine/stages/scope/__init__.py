"""
Scope resolver stage package (multi-entity reporting).

Pipeline position:
    (loader) -> resolve_scope -> securitisation_allocator

Layout:
- ``stage``    — the uniform ``run(ctx, rulepack, run_config)`` adapter
- ``resolver`` — ``resolve_scope`` plus the registry-tree / membership /
  booking-filter / intragroup-elimination transform functions and the SCP
  data-quality diagnostics

The stage no-ops when no reporting entity is configured, so an unscoped run is
byte-identical to today (hard invariant I1).

References:
- CRR Part One Title II (Art. 6, 11-18): individual / sub-consolidated /
  consolidated levels of application.
- docs/plans/multi-entity-reporting.md: scope resolver specification.
"""

from __future__ import annotations

from rwa_calc.engine.stages.scope.resolver import resolve_scope as resolve_scope
from rwa_calc.engine.stages.scope.stage import run as run
