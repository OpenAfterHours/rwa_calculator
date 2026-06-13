"""
Rulebook regime registry — the literal regime -> pack-order map.

Pipeline position:
    Read by ``rulebook/resolve.py`` to decide which pack modules to merge
    (and in what order) for a given regime id.

Key responsibilities:
- Map each supported regime id to its ordered pack tuple (base ->
  amendment; later packs override earlier ones on name collision).
- Stay a literal dict / tuple — no conditionals, loops, or comprehensions —
  so the regime composition is grep-able and diff-reviewable (mirrors the
  literal stage registry discipline of ``engine/registry.py``).

References:
- docs/plans/target-architecture-migration.md (Phase 5 — pack layering
  base -> amendment; the regime registry).
"""

from __future__ import annotations

REGIME_PACKS: dict[str, tuple[str, ...]] = {
    "crr": ("common", "crr"),
    "b31": ("common", "b31"),
}

SUPPORTED_REGIMES = ("crr", "b31")
