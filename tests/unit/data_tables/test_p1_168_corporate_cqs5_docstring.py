"""
Unit tests for P1.168: b31_risk_weights docstring accuracy for CQS5 corporate risk weight.

Both the module docstring and the ``get_b31_combined_cqs_risk_weights`` function
docstring currently state ``CQS5: 100%`` / ``CQS5=100%``, which contradicts the
PRA PS1/26 deviation that retains 150% for CQS 5 corporates (rather than the
BCBS-proposed 100%).  The constant ``B31_CORPORATE_RISK_WEIGHTS[5]`` already
holds ``Decimal("1.50")``, so only the prose needs correcting.

References:
- PRA PS1/26 Art. 122(1) Table 6: CQS 5 corporate SA risk weight = 150% (PRA
  deviation from BCBS CRE20.22 which would allow 100%)
- P1.168: Docstring-only correction at
  src/rwa_calc/data/tables/b31_risk_weights.py lines 16 and 390
"""

from __future__ import annotations

import inspect
from decimal import Decimal

from rwa_calc.engine.sa import b31_risk_weight_tables as b31_risk_weights
from rwa_calc.engine.sa.b31_risk_weight_tables import (
    B31_CORPORATE_RISK_WEIGHTS,
    get_b31_combined_cqs_risk_weights,
)


class TestCorporateCqs5ConstantSanity:
    """Guard the B31_CORPORATE_RISK_WEIGHTS constant value for CQS 5."""

    def test_b31_corporate_cqs5_is_150_percent(self) -> None:
        """Arrange: retrieve B31_CORPORATE_RISK_WEIGHTS[5].

        Act: compare to Decimal("1.50").

        Assert: value equals 1.50 — the PRA PS1/26 Art. 122(1) Table 6 rate.
        """
        # Arrange / Act
        actual = B31_CORPORATE_RISK_WEIGHTS[5]

        # Assert
        assert actual == Decimal("1.50"), (
            f"B31_CORPORATE_RISK_WEIGHTS[5] must be Decimal('1.50') per PRA PS1/26. Got: {actual!r}"
        )


class TestModuleDocstringCqs5:
    """b31_risk_weights module docstring must reflect 150%, not 100%, for CQS 5."""

    def test_module_docstring_does_not_contain_cqs5_100_percent(self) -> None:
        """Arrange: retrieve the module docstring via inspect.getdoc.

        Act: check for the stale '100%' phrasing next to 'CQS5'.

        Assert: 'CQS5: 100%' is NOT present — the bug this test pins.
        """
        # Arrange
        doc = inspect.getdoc(b31_risk_weights)
        assert doc is not None, "b31_risk_weights must have a module docstring"

        # Act / Assert
        assert "CQS5: 100%" not in doc, (
            "b31_risk_weights module docstring contains stale 'CQS5: 100%'. "
            "Must be corrected to 'CQS5: 150%' per PRA PS1/26 Art. 122(1) Table 6. "
            f"Got docstring: {doc!r}"
        )

    def test_module_docstring_contains_cqs5_150_percent(self) -> None:
        """Arrange: retrieve the module docstring via inspect.getdoc.

        Act: check for the correct '150%' phrasing next to 'CQS5'.

        Assert: 'CQS5: 150%' IS present — the authoritative PRA deviation value.
        """
        # Arrange
        doc = inspect.getdoc(b31_risk_weights)
        assert doc is not None, "b31_risk_weights must have a module docstring"

        # Act / Assert
        assert "CQS5: 150%" in doc, (
            "b31_risk_weights module docstring must contain 'CQS5: 150%' per "
            "PRA PS1/26 Art. 122(1) Table 6 (PRA deviation: 150%, not BCBS 100%). "
            f"Got docstring: {doc!r}"
        )


class TestFunctionDocstringCqs5:
    """get_b31_combined_cqs_risk_weights docstring must reflect 150%, not 100%, for CQS 5."""

    def test_function_docstring_does_not_contain_cqs5_eq_100_percent(self) -> None:
        """Arrange: retrieve get_b31_combined_cqs_risk_weights docstring via inspect.getdoc.

        Act: check for the stale 'CQS5=100%' phrasing.

        Assert: 'CQS5=100%' is NOT present — the bug this test pins.
        """
        # Arrange
        doc = inspect.getdoc(get_b31_combined_cqs_risk_weights)
        assert doc is not None, "get_b31_combined_cqs_risk_weights must have a docstring"

        # Act / Assert
        assert "CQS5=100%" not in doc, (
            "get_b31_combined_cqs_risk_weights docstring contains stale 'CQS5=100%'. "
            "Must be corrected to 'CQS5=150%' per PRA PS1/26 Art. 122(1) Table 6. "
            f"Got docstring: {doc!r}"
        )

    def test_function_docstring_contains_cqs5_eq_150_percent(self) -> None:
        """Arrange: retrieve get_b31_combined_cqs_risk_weights docstring via inspect.getdoc.

        Act: check for the correct 'CQS5=150%' phrasing.

        Assert: 'CQS5=150%' IS present — the authoritative PRA deviation value.
        """
        # Arrange
        doc = inspect.getdoc(get_b31_combined_cqs_risk_weights)
        assert doc is not None, "get_b31_combined_cqs_risk_weights must have a docstring"

        # Act / Assert
        assert "CQS5=150%" in doc, (
            "get_b31_combined_cqs_risk_weights docstring must contain 'CQS5=150%' per "
            "PRA PS1/26 Art. 122(1) Table 6 (PRA deviation: 150%, not BCBS 100%). "
            f"Got docstring: {doc!r}"
        )
