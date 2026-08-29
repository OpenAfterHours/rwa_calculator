"""
Scope resolver domain package (multi-entity reporting).

Pipeline position:
    (loader) -> resolve_scope -> securitisation_allocator

Layout:
- ``resolver`` — ``resolve_scope`` plus the registry-tree / membership /
  booking-filter / intragroup-elimination transform functions and the SCP
  data-quality diagnostics

The stage no-ops when no reporting entity is configured, so an unscoped run is
byte-identical to today (hard invariant I1). The ``run(ctx, rulepack,
run_config)`` adapter that wires this domain into the fold lives at
``engine/stages/scope.py``, not here: ``engine/stages/`` is the wiring layer
and holds nothing else.

References:
- CRR Part One Title II (Art. 6, 11-18): individual / sub-consolidated /
  consolidated levels of application.
- docs/plans/multi-entity-reporting.md: scope resolver specification.
- docs/plans/architecture-review-2026-08-29.md §2 (the stages/domain split)
"""

from __future__ import annotations

from rwa_calc.engine.scope.resolver import resolve_scope as resolve_scope
