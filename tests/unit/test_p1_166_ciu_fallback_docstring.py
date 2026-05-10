"""
Unit tests for P1.166: EquityType.CIU docstring accuracy.

The CIU enum member docstring must reflect the correct Basel 3.1 fallback
risk weight (1,250% per Art. 132(2)) and must not carry stale CRR-era
phrasing that no longer applies under the unified B31 SA treatment.

References:
- PRA PS1/26 Art. 132(2): CIU fallback risk weight = 1,250%
- P1.166: Docstring-only correction at src/rwa_calc/domain/enums.py:481
"""

from __future__ import annotations

from rwa_calc.domain.enums import EquityType


class TestCiuFallbackDocstring:
    """EquityType.CIU member docstring must contain accurate regulatory text."""

    def test_ciu_docstring_contains_1250_percent(self) -> None:
        """Arrange: retrieve EquityType.CIU member docstring.

        Act: inspect for the correct fallback risk weight string.

        Assert: '1,250%' is present — the Art. 132(2) fallback rate.
        """
        # Arrange
        doc = EquityType.CIU.__doc__
        assert doc is not None, "EquityType.CIU must have a docstring"

        # Act / Assert
        assert "1,250%" in doc, (
            f"EquityType.CIU.__doc__ must contain '1,250%' (Art. 132(2) fallback). Got: {doc!r}"
        )

    def test_ciu_docstring_contains_art_132_2_reference(self) -> None:
        """EquityType.CIU docstring must cite Art. 132(2) as the authority."""
        # Arrange
        doc = EquityType.CIU.__doc__
        assert doc is not None, "EquityType.CIU must have a docstring"

        # Act / Assert
        assert "Art. 132(2)" in doc, (
            f"EquityType.CIU.__doc__ must contain 'Art. 132(2)'. Got: {doc!r}"
        )

    def test_ciu_docstring_does_not_contain_stale_150_crr_sa(self) -> None:
        """EquityType.CIU docstring must not carry stale '150% CRR SA' phrasing."""
        # Arrange
        doc = EquityType.CIU.__doc__
        assert doc is not None, "EquityType.CIU must have a docstring"

        # Act / Assert
        assert "150% CRR SA" not in doc, (
            f"EquityType.CIU.__doc__ contains stale phrase '150% CRR SA'. Got: {doc!r}"
        )

    def test_ciu_docstring_does_not_contain_stale_250_listed_or_400_unlisted(self) -> None:
        """EquityType.CIU docstring must not carry stale '250% listed or 400% unlisted' text."""
        # Arrange
        doc = EquityType.CIU.__doc__
        assert doc is not None, "EquityType.CIU must have a docstring"

        # Act / Assert
        assert "250% listed or 400% unlisted" not in doc, (
            f"EquityType.CIU.__doc__ contains stale phrase '250% listed or 400% unlisted'. "
            f"Got: {doc!r}"
        )
