"""
Rulebook — the regime seam (Phase 4 v0 facade).

This package will become the versioned, citation-carrying regime-as-data
layer (migration Phase 5: model/packs/registry/resolve/compile/audit). In
Phase 4 it ships only :class:`RulepackV0`, a frozen facade over today's
``CalculationConfig`` + ``data/tables`` so the final stage signature —
``Stage(ctx, rulepack, run_config)`` — lands now and Phase 5 swaps the
implementation, never the signature.

References:
- docs/plans/target-architecture-migration.md (Phase 4 signature freeze,
  Phase 5 rulebook)
"""

from __future__ import annotations

from rwa_calc.rulebook.v0 import RulepackV0

__all__ = ["RulepackV0"]
