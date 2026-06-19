"""Unit tests for the capital-impact delta-attributor registry (Phase 6 S4)."""

from __future__ import annotations

# Importing comparison registers the ('crr', 'b31') pairing at module load.
import rwa_calc.analysis.comparison  # noqa: F401
from rwa_calc.analysis.attribution import get_attributor, neutral_attribution


class TestAttributorRegistry:
    """The CRR->B31 waterfall is one registered pairing; everything else is neutral."""

    def test_crr_b31_pairing_registered(self):
        """The ('crr', 'b31') pairing resolves to the 4-driver waterfall attributor."""
        attributor = get_attributor("crr", "b31")
        assert attributor.__name__ == "_crr_to_b31_attribution"  # ty: ignore[unresolved-attribute]

    def test_unregistered_pairing_falls_back_to_neutral(self):
        """Any unregistered pairing resolves to the neutral delta-only attributor."""
        assert get_attributor("base", "variant") is neutral_attribution

    def test_reversed_pairing_is_not_registered(self):
        """('b31', 'crr') is a distinct, unregistered pairing -> neutral fallback."""
        assert get_attributor("b31", "crr") is neutral_attribution
