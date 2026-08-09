"""
Rulebook — the regime seam: the versioned, citation-carrying regime-as-data
layer (migration Phase 5, complete).

Regulatory values are authored as cited entries in the packs
(``packs/{common,crr,b31}.py``). ``registry.py`` names the pack layering per
regime, ``resolve.py`` merges them (base -> amendment) into a
``ResolvedRulepack``, ``compile.py`` crosses the Decimal -> float boundary,
and ``audit.py`` emits the pack manifest recorded in the run manifest and
served by the ``rulepack diff`` CLI.

The package root re-exports only :class:`RulepackV0` — the frozen facade
that fixes the stage signature ``Stage(ctx, rulepack, run_config)``. The pack
machinery is reached through the submodules above.

References:
- docs/plans/target-architecture-migration.md (Phase 4 signature freeze,
  Phase 5 rulebook; Phase 5 S13 deleted ``data/tables`` entirely — the packs
  are now the sole home for regulatory values)
"""

from __future__ import annotations

from rwa_calc.rulebook.v0 import RulepackV0

__all__ = ["RulepackV0"]
