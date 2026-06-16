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

This is the small proof pack for migration Phase 5 Slice 1 — it exercises
every rule shape with genuine cited values, not the full table migration
(Slices 4-10).

References:
- docs/plans/target-architecture-migration.md (Phase 5 — "Regimes are
  data"; pack layering base -> amendment).
"""

from __future__ import annotations
