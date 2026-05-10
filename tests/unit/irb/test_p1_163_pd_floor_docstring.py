"""
Unit tests for P1.163: _pd_floor_expression docstring accuracy.

The _pd_floor_expression function docstring must reflect the correct Basel 3.1
PD floors (Art. 163(1)/CRE30.55) and must not carry stale values that were
present before the fix:
  - Retail mortgage floor must be 0.10%, not the stale 0.05%.
  - QRRE transactor floor must be 0.05%, not the stale 0.03%.

References:
- PRA PS1/26 Art. 163(1)(a-c): Differentiated PD floors by exposure class
- PRA PS1/26 Art. 160(1): QRRE transactor/revolver distinction
- BCBS CRE30.55: Basel 3.1 PD floors
- P1.163: Docstring-only correction at src/rwa_calc/engine/irb/formulas.py lines 64-65
"""

from __future__ import annotations

import inspect

from rwa_calc.engine.irb.formulas import _pd_floor_expression


class TestPdFloorDocstring:
    """_pd_floor_expression docstring must contain accurate Basel 3.1 PD floor values."""

    def test_docstring_exists(self) -> None:
        """_pd_floor_expression must have a docstring."""
        # Arrange / Act
        doc = inspect.getdoc(_pd_floor_expression)

        # Assert
        assert doc is not None, "_pd_floor_expression must have a docstring"

    def test_retail_mortgage_floor_is_0_10_percent(self) -> None:
        """Docstring must state the correct retail mortgage PD floor of 0.10%.

        Arrange: retrieve the function docstring via inspect.getdoc.
        Act: search for the correct Basel 3.1 value.
        Assert: 'Retail mortgage: 0.10%' is present (Art. 163(1)(a)).
        """
        # Arrange
        doc = inspect.getdoc(_pd_floor_expression)
        assert doc is not None

        # Act / Assert
        assert "Retail mortgage: 0.10%" in doc, (
            f"Docstring must contain 'Retail mortgage: 0.10%' (Art. 163(1)(a)). Got: {doc!r}"
        )

    def test_qrre_transactor_floor_is_0_05_percent(self) -> None:
        """Docstring must state the correct QRRE transactor PD floor of 0.05%.

        Arrange: retrieve the function docstring via inspect.getdoc.
        Act: search for the correct Basel 3.1 value.
        Assert: 'QRRE transactors: 0.05%' is present (Art. 163(1)(b) / CRE30.55).
        """
        # Arrange
        doc = inspect.getdoc(_pd_floor_expression)
        assert doc is not None

        # Act / Assert
        assert "QRRE transactors: 0.05%" in doc, (
            f"Docstring must contain 'QRRE transactors: 0.05%' (CRE30.55). Got: {doc!r}"
        )

    def test_qrre_revolver_floor_is_0_10_percent(self) -> None:
        """Docstring must state the correct QRRE revolver PD floor of 0.10%.

        Arrange: retrieve the function docstring via inspect.getdoc.
        Act: search for the correct Basel 3.1 value.
        Assert: 'revolvers: 0.10%' is present (CRE30.55).
        """
        # Arrange
        doc = inspect.getdoc(_pd_floor_expression)
        assert doc is not None

        # Act / Assert
        assert "revolvers: 0.10%" in doc, (
            f"Docstring must contain 'revolvers: 0.10%' (CRE30.55). Got: {doc!r}"
        )

    def test_corporate_sme_floor_is_0_05_percent(self) -> None:
        """Docstring must state the correct Corporate/SME PD floor of 0.05%.

        Arrange: retrieve the function docstring via inspect.getdoc.
        Act: search for the correct Basel 3.1 value.
        Assert: 'Corporate/SME: 0.05%' is present (Art. 163(1) / CRE30.55).
        """
        # Arrange
        doc = inspect.getdoc(_pd_floor_expression)
        assert doc is not None

        # Act / Assert
        assert "Corporate/SME: 0.05%" in doc, (
            f"Docstring must contain 'Corporate/SME: 0.05%' (CRE30.55). Got: {doc!r}"
        )

    def test_retail_other_floor_is_0_05_percent(self) -> None:
        """Docstring must state the correct Retail other PD floor of 0.05%.

        Arrange: retrieve the function docstring via inspect.getdoc.
        Act: search for the correct Basel 3.1 value.
        Assert: 'Retail other: 0.05%' is present (Art. 163(1) / CRE30.55).
        """
        # Arrange
        doc = inspect.getdoc(_pd_floor_expression)
        assert doc is not None

        # Act / Assert
        assert "Retail other: 0.05%" in doc, (
            f"Docstring must contain 'Retail other: 0.05%' (CRE30.55). Got: {doc!r}"
        )

    def test_docstring_contains_regulatory_citation(self) -> None:
        """Docstring must cite a recognised regulatory authority (Art. 163(1) or CRE30.55).

        Arrange: retrieve the function docstring via inspect.getdoc.
        Act: search for a regulatory reference.
        Assert: at least one of 'Art. 163(1)' or 'CRE30.55' is present.
        """
        # Arrange
        doc = inspect.getdoc(_pd_floor_expression)
        assert doc is not None

        # Act / Assert
        assert "Art. 163(1)" in doc or "CRE30.55" in doc, (
            f"Docstring must cite 'Art. 163(1)' or 'CRE30.55'. Got: {doc!r}"
        )

    def test_docstring_does_not_contain_stale_retail_mortgage_0_05(self) -> None:
        """Docstring must NOT carry the stale retail mortgage floor of 0.05%.

        Arrange: retrieve the function docstring via inspect.getdoc.
        Act: search for the stale value that existed before P1.163.
        Assert: 'Retail mortgage: 0.05%' is absent — it was incorrect pre-fix.
        """
        # Arrange
        doc = inspect.getdoc(_pd_floor_expression)
        assert doc is not None

        # Act / Assert
        assert "Retail mortgage: 0.05%" not in doc, (
            f"Docstring must NOT contain stale 'Retail mortgage: 0.05%'. Got: {doc!r}"
        )

    def test_docstring_does_not_contain_stale_qrre_transactor_0_03(self) -> None:
        """Docstring must NOT carry the stale QRRE transactor floor of 0.03%.

        Arrange: retrieve the function docstring via inspect.getdoc.
        Act: search for the stale value that existed before P1.163.
        Assert: 'QRRE transactors: 0.03%' is absent — it was incorrect pre-fix.
        """
        # Arrange
        doc = inspect.getdoc(_pd_floor_expression)
        assert doc is not None

        # Act / Assert
        assert "QRRE transactors: 0.03%" not in doc, (
            f"Docstring must NOT contain stale 'QRRE transactors: 0.03%'. Got: {doc!r}"
        )
