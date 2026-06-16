"""
Rulebook regime registry — the literal regime -> pack-order map.

Pipeline position:
    Read by ``rulebook/resolve.py`` to decide which pack modules to merge
    (and in what order) for a given regime id.

Key responsibilities:
- Map each supported regime id to its ordered pack tuple (base ->
  amendment; later packs override earlier ones on name collision).
- Map the domain ``RegulatoryFramework`` enum to its regime id — the single
  framework -> pack-selector seam (used by ``RulepackV0.from_config``).
- Stay a literal dict / tuple — no conditionals, loops, or comprehensions —
  so the regime composition is grep-able and diff-reviewable (mirrors the
  literal stage registry discipline of ``engine/registry.py``).

References:
- docs/plans/target-architecture-migration.md (Phase 5 — pack layering
  base -> amendment; the regime registry).
"""

from __future__ import annotations

from rwa_calc.domain.enums import RegulatoryFramework

REGIME_PACKS: dict[str, tuple[str, ...]] = {
    "crr": ("common", "crr"),
    "b31": ("common", "b31"),
}

SUPPORTED_REGIMES = ("crr", "b31")

# The framework -> regime-id seam: the one place the domain enum is mapped to a
# pack-selector string. ``RulepackV0.from_config`` resolves the pack through this.
FRAMEWORK_TO_REGIME_ID: dict[RegulatoryFramework, str] = {
    RegulatoryFramework.CRR: "crr",
    RegulatoryFramework.BASEL_3_1: "b31",
}
