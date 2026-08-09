"""
Rulebook packs — regime layers authored as cited Decimal rule entries.

Pipeline position:
    Each pack module exposes ``ENTRIES: dict[str, RuleEntry]``;
    ``rulebook/resolve.py`` merges the packs named in
    ``rulebook/registry.py::REGIME_PACKS`` (base -> amendment order) into a
    single ``ResolvedRulepack``.

Key responsibilities:
- Hold the regime-as-data content: ``common`` (regime-invariant),
  ``crr`` (pre-Basel-3.1), and ``b31`` (Basel 3.1 / PRA PS1/26) layers.

These packs are the value home for the whole engine. The table migration
completed in Phase 5 S12/S13: ``data/tables/`` was emptied and deleted, and
``engine/**`` now reads every regulatory value back from the resolved pack.
A new regulatory value belongs here, with a ``Citation`` — never in engine
module scope (enforced by ``scripts/arch_check.py`` checks 5, 6 and 12).

References:
- docs/plans/target-architecture-migration.md (Phase 5 — "Regimes are
  data"; pack layering base -> amendment).
"""

from __future__ import annotations
