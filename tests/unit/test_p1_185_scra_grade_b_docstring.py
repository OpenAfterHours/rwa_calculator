"""
Unit tests for P1.185: SCRAGrade.B docstring accuracy.

The SCRAGrade.B enum member docstring must reflect the correct qualitative
Art. 121(1)(b) criterion — "meets published minimum requirements (excluding
buffers)" — and must not carry fabricated quantitative thresholds such as
"CET1 > 5.5%" or "Leverage > 3%" that do not appear in the regulation.

The engine-implementer will install corrected text via a post-class
``SCRAGrade.B.__doc__ = "..."`` assignment, mirroring the EquityType.CIU
pattern at enums.py lines 487-491.

References:
- PRA PS1/26 Art. 121(1)(b): SCRA Grade B qualitative criterion
- P1.185: Docstring-only correction at src/rwa_calc/domain/enums.py:334-335
"""

from __future__ import annotations

from decimal import Decimal

from rwa_calc.data.tables.b31_risk_weights import B31_SCRA_RISK_WEIGHTS
from rwa_calc.domain.enums import SCRAGrade


class TestSCRAGradeBDocstring:
    """SCRAGrade.B member docstring must contain accurate regulatory text."""

    # ------------------------------------------------------------------
    # Sanity checks — these pass today and must continue to pass
    # ------------------------------------------------------------------

    def test_scra_grade_b_value_is_b(self) -> None:
        """SCRAGrade.B.value must equal the string 'B'.

        Arrange: import SCRAGrade enum.

        Act: access .value on the B member.

        Assert: value is 'B'.
        """
        # Arrange / Act
        result = SCRAGrade.B.value

        # Assert
        assert result == "B", f"SCRAGrade.B.value expected 'B', got {result!r}"

    def test_b31_scra_risk_weight_b_is_75_percent(self) -> None:
        """B31_SCRA_RISK_WEIGHTS['B'] must equal Decimal('0.75').

        Arrange: import B31_SCRA_RISK_WEIGHTS table.

        Act: look up key 'B'.

        Assert: value is Decimal('0.75') (75% long-term risk weight).
        """
        # Arrange / Act
        result = B31_SCRA_RISK_WEIGHTS["B"]

        # Assert
        assert result == Decimal("0.75"), (
            f"B31_SCRA_RISK_WEIGHTS['B'] expected Decimal('0.75'), got {result!r}"
        )

    # ------------------------------------------------------------------
    # Positive-presence assertions — these FAIL until P1.185 is implemented
    # ------------------------------------------------------------------

    def test_scra_grade_b_docstring_contains_minimum_requirements(self) -> None:
        """SCRAGrade.B docstring must contain the phrase 'minimum requirements'.

        Arrange: retrieve SCRAGrade.B member docstring (set via post-class
        __doc__ assignment by the engine-implementer).

        Act: search for the qualitative criterion phrase.

        Assert: 'minimum requirements' is present — Art. 121(1)(b) language.
        """
        # Arrange
        doc = SCRAGrade.B.__doc__
        assert doc is not None, "SCRAGrade.B must have a docstring (set via post-class assignment)"

        # Act / Assert
        assert "minimum requirements" in doc, (
            f"SCRAGrade.B.__doc__ must contain 'minimum requirements' "
            f"(Art. 121(1)(b) qualitative criterion). Got: {doc!r}"
        )

    def test_scra_grade_b_docstring_contains_buffers(self) -> None:
        """SCRAGrade.B docstring must contain the word 'buffers'.

        Arrange: retrieve SCRAGrade.B member docstring.

        Act: search for 'buffers' — the regulation excludes buffers from the
        minimum requirement threshold, so the word must appear.

        Assert: 'buffers' is present.
        """
        # Arrange
        doc = SCRAGrade.B.__doc__
        assert doc is not None, "SCRAGrade.B must have a docstring (set via post-class assignment)"

        # Act / Assert
        assert "buffers" in doc, (
            f"SCRAGrade.B.__doc__ must contain 'buffers' "
            f"(Art. 121(1)(b): excluding buffers). Got: {doc!r}"
        )

    def test_scra_grade_b_docstring_contains_art_121_1_b_reference(self) -> None:
        """SCRAGrade.B docstring must cite Art. 121(1)(b) as the authority.

        Arrange: retrieve SCRAGrade.B member docstring.

        Act: search for the regulatory article citation.

        Assert: 'Art. 121(1)(b)' is present.
        """
        # Arrange
        doc = SCRAGrade.B.__doc__
        assert doc is not None, "SCRAGrade.B must have a docstring (set via post-class assignment)"

        # Act / Assert
        assert "Art. 121(1)(b)" in doc, (
            f"SCRAGrade.B.__doc__ must contain 'Art. 121(1)(b)'. Got: {doc!r}"
        )

    # ------------------------------------------------------------------
    # Negative-absence assertions — fabricated quantitative thresholds
    # must be removed from the member docstring
    # ------------------------------------------------------------------

    def test_scra_grade_b_docstring_does_not_contain_cet1(self) -> None:
        """SCRAGrade.B docstring must not carry fabricated 'CET1' threshold text.

        Arrange: retrieve SCRAGrade.B member docstring.

        Act: search for stale fabricated phrase 'CET1'.

        Assert: 'CET1' is absent — Art. 121(1)(b) is qualitative, not CET1-based.
        """
        # Arrange
        doc = SCRAGrade.B.__doc__
        assert doc is not None, "SCRAGrade.B must have a docstring (set via post-class assignment)"

        # Act / Assert
        assert "CET1" not in doc, (
            f"SCRAGrade.B.__doc__ contains fabricated phrase 'CET1'. Got: {doc!r}"
        )

    def test_scra_grade_b_docstring_does_not_contain_5_5_percent(self) -> None:
        """SCRAGrade.B docstring must not carry fabricated '5.5%' threshold text.

        Arrange: retrieve SCRAGrade.B member docstring.

        Act: search for stale fabricated threshold '5.5%'.

        Assert: '5.5%' is absent — this threshold does not appear in Art. 121(1)(b).
        """
        # Arrange
        doc = SCRAGrade.B.__doc__
        assert doc is not None, "SCRAGrade.B must have a docstring (set via post-class assignment)"

        # Act / Assert
        assert "5.5%" not in doc, (
            f"SCRAGrade.B.__doc__ contains fabricated threshold '5.5%'. Got: {doc!r}"
        )

    def test_scra_grade_b_docstring_does_not_contain_leverage_3_percent(self) -> None:
        """SCRAGrade.B docstring must not carry fabricated 'Leverage > 3%' text.

        Arrange: retrieve SCRAGrade.B member docstring.

        Act: search for stale fabricated phrase 'Leverage > 3%'.

        Assert: 'Leverage > 3%' is absent — this is not the Art. 121(1)(b) criterion.
        """
        # Arrange
        doc = SCRAGrade.B.__doc__
        assert doc is not None, "SCRAGrade.B must have a docstring (set via post-class assignment)"

        # Act / Assert
        assert "Leverage > 3%" not in doc, (
            f"SCRAGrade.B.__doc__ contains fabricated phrase 'Leverage > 3%'. Got: {doc!r}"
        )
