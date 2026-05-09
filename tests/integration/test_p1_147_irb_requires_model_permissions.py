"""
Integration test: P1.147 — IRB mode requires model_permissions.parquet.

Pipeline position:
    CreditRiskCalc.validate() → DataPathValidator → ValidationResponse
    CreditRiskCalc.calculate() → validation gate → short-circuit on VAL003

Key responsibilities tested:
- When permission_mode="irb" and config/model_permissions.parquet is absent,
  validate() must return valid=False with exactly one VAL003 error whose
  message mentions both "model_permissions" and "irb".
- When permission_mode="standardised" with the same data set, validate()
  must return valid=True with no VAL003 error (control case).
- When permission_mode="irb" and model_permissions.parquet is absent,
  calculate() must short-circuit with success=False, a VAL003 error,
  summary.total_rwa == Decimal("0"), and summary.exposure_count == 0.

Test relies on the mandatory-minimum fixture that writes the five core
parquet files but deliberately omits config/model_permissions.parquet.

Pre-fix behaviour (target fail state):
- validate() returns valid=True  → AssertionError on `assert not response.valid`
- calculate() returns success=True → AssertionError on `assert not response.success`
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from rwa_calc.api import CreditRiskCalc
from tests.fixtures.api_validation.build_mandatory_only import write_mandatory_minimum

# =============================================================================
# Helpers
# =============================================================================


def _val003_errors(errors: list) -> list:
    """Return only errors with code VAL003."""
    return [e for e in errors if e.code == "VAL003"]


# =============================================================================
# Tests
# =============================================================================


class TestP1147IrbRequiresModelPermissions:
    """P1.147: DataPathValidator must emit VAL003 when IRB mode + no model_permissions."""

    def test_validate_irb_mode_missing_model_permissions_is_invalid(
        self, tmp_path: Path
    ) -> None:
        """
        When permission_mode='irb' and model_permissions.parquet is absent,
        validate() must return valid=False with exactly one VAL003 error.

        Pre-fix: valid=True → AssertionError.
        """
        # Arrange — mandatory-minimum set, no config/model_permissions.parquet
        write_mandatory_minimum(tmp_path)
        calc = CreditRiskCalc(
            data_path=tmp_path,
            framework="CRR",
            reporting_date=date(2025, 1, 1),
            permission_mode="irb",
        )

        # Act
        response = calc.validate()

        # Assert — validation must fail
        assert not response.valid, (
            "validate() returned valid=True; expected valid=False because "
            "model_permissions.parquet is absent in IRB mode"
        )

    def test_validate_irb_mode_val003_in_files_missing(self, tmp_path: Path) -> None:
        """
        config/model_permissions.parquet must appear in files_missing when IRB mode.

        Pre-fix: files_missing does not include this path → AssertionError.
        """
        # Arrange
        write_mandatory_minimum(tmp_path)
        calc = CreditRiskCalc(
            data_path=tmp_path,
            framework="CRR",
            reporting_date=date(2025, 1, 1),
            permission_mode="irb",
        )

        # Act
        response = calc.validate()

        # Assert
        expected_missing = Path("config/model_permissions.parquet")
        assert expected_missing in response.files_missing, (
            f"Expected {expected_missing} in files_missing; got {response.files_missing}"
        )

    def test_validate_irb_mode_val003_error_code_present(self, tmp_path: Path) -> None:
        """
        validate() must include exactly one error with code VAL003 in IRB mode.

        Pre-fix: no VAL003 error → AssertionError.
        """
        # Arrange
        write_mandatory_minimum(tmp_path)
        calc = CreditRiskCalc(
            data_path=tmp_path,
            framework="CRR",
            reporting_date=date(2025, 1, 1),
            permission_mode="irb",
        )

        # Act
        response = calc.validate()
        val003_errs = _val003_errors(response.errors)

        # Assert — exactly one VAL003
        assert len(val003_errs) == 1, (
            f"Expected exactly 1 VAL003 error; got {val003_errs}"
        )

    def test_validate_irb_mode_val003_error_attributes(self, tmp_path: Path) -> None:
        """
        The VAL003 error must have severity='error', category='Validation',
        and a message containing both 'model_permissions' and 'irb'.

        Pre-fix: no VAL003 → IndexError / AssertionError.
        """
        # Arrange
        write_mandatory_minimum(tmp_path)
        calc = CreditRiskCalc(
            data_path=tmp_path,
            framework="CRR",
            reporting_date=date(2025, 1, 1),
            permission_mode="irb",
        )

        # Act
        response = calc.validate()
        val003_errs = _val003_errors(response.errors)

        # Tolerate no VAL003 at all (pre-fix) so only one assertion fails cleanly
        if not val003_errs:
            pytest.fail("No VAL003 error found; cannot check attributes")

        err = val003_errs[0]

        # Assert — structural contract of the error
        assert err.severity == "error", f"Expected severity='error'; got {err.severity!r}"
        assert err.category == "Validation", f"Expected category='Validation'; got {err.category!r}"
        assert "model_permissions" in err.message.lower(), (
            f"Expected 'model_permissions' in message; got {err.message!r}"
        )
        assert "irb" in err.message.lower(), (
            f"Expected 'irb' in message; got {err.message!r}"
        )

    def test_validate_standardised_mode_no_val003(self, tmp_path: Path) -> None:
        """
        Control: when permission_mode='standardised', validate() must return
        valid=True and no VAL003 error, even without model_permissions.parquet.

        This test must PASS pre-fix (current behaviour is already correct here).
        """
        # Arrange
        write_mandatory_minimum(tmp_path)
        calc = CreditRiskCalc(
            data_path=tmp_path,
            framework="CRR",
            reporting_date=date(2025, 1, 1),
            permission_mode="standardised",
        )

        # Act
        response = calc.validate()

        # Assert — control must pass both before and after fix
        assert response.valid is True, (
            "validate() returned valid=False in standardised mode (unexpected)"
        )
        val003_errs = _val003_errors(response.errors)
        assert val003_errs == [], (
            f"Unexpected VAL003 errors in standardised mode: {val003_errs}"
        )

    def test_calculate_irb_mode_short_circuits_on_val003(self, tmp_path: Path) -> None:
        """
        When permission_mode='irb' and model_permissions.parquet is absent,
        calculate() must short-circuit: success=False, VAL003 present,
        total_rwa=Decimal('0'), exposure_count=0.

        Pre-fix: success=True → AssertionError.
        """
        # Arrange
        write_mandatory_minimum(tmp_path)
        calc = CreditRiskCalc(
            data_path=tmp_path,
            framework="CRR",
            reporting_date=date(2025, 1, 1),
            permission_mode="irb",
        )

        # Act
        response = calc.calculate()

        # Assert — pipeline must short-circuit
        assert not response.success, (
            "calculate() returned success=True; expected short-circuit with success=False "
            "because model_permissions.parquet is absent in IRB mode"
        )

    def test_calculate_irb_mode_val003_in_errors(self, tmp_path: Path) -> None:
        """
        calculate() must carry the VAL003 error when short-circuiting in IRB mode.

        Pre-fix: no VAL003 → AssertionError.
        """
        # Arrange
        write_mandatory_minimum(tmp_path)
        calc = CreditRiskCalc(
            data_path=tmp_path,
            framework="CRR",
            reporting_date=date(2025, 1, 1),
            permission_mode="irb",
        )

        # Act
        response = calc.calculate()
        val003_errs = _val003_errors(response.errors)

        # Assert
        assert len(val003_errs) >= 1, (
            f"Expected at least one VAL003 error in calculate() response; got {response.errors}"
        )

    def test_calculate_irb_mode_zero_rwa_on_short_circuit(self, tmp_path: Path) -> None:
        """
        calculate() must return total_rwa=Decimal('0') and exposure_count=0
        when short-circuiting in IRB mode.

        Pre-fix: total_rwa > 0 → AssertionError.
        """
        # Arrange
        write_mandatory_minimum(tmp_path)
        calc = CreditRiskCalc(
            data_path=tmp_path,
            framework="CRR",
            reporting_date=date(2025, 1, 1),
            permission_mode="irb",
        )

        # Act
        response = calc.calculate()

        # Assert — no RWA should be calculated if validation fails
        assert response.summary.total_rwa == Decimal("0"), (
            f"Expected total_rwa=Decimal('0') on short-circuit; got {response.summary.total_rwa}"
        )
        assert response.summary.exposure_count == 0, (
            f"Expected exposure_count=0 on short-circuit; got {response.summary.exposure_count}"
        )
