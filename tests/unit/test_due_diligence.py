"""Unit tests for Art. 110A due diligence risk weight override (Basel 3.1).

Tests cover:
- Override applied when due_diligence_override_rw > calculated risk_weight
- Override ignored when due_diligence_override_rw <= calculated risk_weight
- Override ignored when due_diligence_override_rw is null
- No-op when override column is absent from data
- No-op under CRR (Art. 110A is Basel 3.1 only)
- Warning emitted when due_diligence_performed column absent under Basel 3.1
- No warning emitted under CRR
- No warning when due_diligence_performed column is present
- Audit column due_diligence_override_applied set correctly
- Override only increases risk weight (max behavior)
- Integration with SA result bundle path

References:
- PRA PS1/26 Art. 110A: Due diligence obligation
- P1.49: Art. 110A due diligence obligation implementation
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import (
    ERROR_DUE_DILIGENCE_NOT_PERFORMED,
    CalculationError,
)
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.engine.sa.calculator import SACalculator

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _exposures_with_dd(
    *,
    risk_weights: list[float],
    override_rws: list[float | None] | None = None,
    dd_performed: list[bool | None] | None = None,
) -> pl.LazyFrame:
    """Create minimal SA exposures with due diligence columns."""
    n = len(risk_weights)
    data: dict[str, list[object]] = {
        "exposure_reference": [f"EXP_{i:03d}" for i in range(n)],
        "risk_weight": risk_weights,
    }
    if override_rws is not None:
        data["due_diligence_override_rw"] = override_rws
    if dd_performed is not None:
        data["due_diligence_performed"] = dd_performed
    return pl.DataFrame(data).lazy()


def _exposures_without_dd(
    *,
    risk_weights: list[float],
) -> pl.LazyFrame:
    """Create minimal SA exposures without any due diligence columns."""
    n = len(risk_weights)
    return pl.DataFrame(
        {
            "exposure_reference": [f"EXP_{i:03d}" for i in range(n)],
            "risk_weight": risk_weights,
        }
    ).lazy()


# =============================================================================
# Override Application Tests
# =============================================================================


class TestDueDiligenceOverrideApplication:
    """Tests for the risk weight override mechanism."""

    def test_override_applied_when_higher(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Override RW replaces calculated RW when it is higher."""
        exposures = _exposures_with_dd(
            risk_weights=[0.50],
            override_rws=[0.75],
        )
        result = calculator._apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.75)

    def test_override_ignored_when_lower(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Override RW is ignored when it is lower than calculated RW."""
        exposures = _exposures_with_dd(
            risk_weights=[1.50],
            override_rws=[0.75],
        )
        result = calculator._apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(1.50)

    def test_override_ignored_when_equal(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Override RW is ignored when it equals calculated RW."""
        exposures = _exposures_with_dd(
            risk_weights=[0.75],
            override_rws=[0.75],
        )
        result = calculator._apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.75)

    def test_null_override_ignored(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Null override values are silently ignored."""
        exposures = _exposures_with_dd(
            risk_weights=[0.50],
            override_rws=[None],
        )
        result = calculator._apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.50)

    def test_mixed_overrides(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Mixed override values: some applied, some ignored, some null."""
        exposures = _exposures_with_dd(
            risk_weights=[0.50, 1.50, 0.75, 1.00],
            override_rws=[0.75, 0.50, None, 2.50],
        )
        result = calculator._apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.75)  # override applied
        assert df["risk_weight"][1] == pytest.approx(1.50)  # override lower, ignored
        assert df["risk_weight"][2] == pytest.approx(0.75)  # null override, ignored
        assert df["risk_weight"][3] == pytest.approx(2.50)  # override applied

    def test_no_op_when_override_column_absent(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """No-op when due_diligence_override_rw column is not in the data."""
        exposures = _exposures_without_dd(risk_weights=[0.50, 1.00])
        result = calculator._apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.50)
        assert df["risk_weight"][1] == pytest.approx(1.00)

    def test_no_op_under_crr(
        self, calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """No-op under CRR — Art. 110A is Basel 3.1 only."""
        exposures = _exposures_with_dd(
            risk_weights=[0.50],
            override_rws=[0.75],
        )
        result = calculator._apply_due_diligence_override(exposures, crr_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.50)
        assert "due_diligence_override_applied" not in df.columns


# =============================================================================
# Audit Column Tests
# =============================================================================


class TestDueDiligenceAuditColumn:
    """Tests for the due_diligence_override_applied audit flag."""

    def test_audit_flag_true_when_override_applied(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Audit flag is True when override was applied."""
        exposures = _exposures_with_dd(
            risk_weights=[0.50],
            override_rws=[0.75],
        )
        result = calculator._apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["due_diligence_override_applied"][0] is True

    def test_audit_flag_false_when_override_not_applied(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Audit flag is False when override was not applied (lower RW)."""
        exposures = _exposures_with_dd(
            risk_weights=[1.50],
            override_rws=[0.75],
        )
        result = calculator._apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["due_diligence_override_applied"][0] is False

    def test_audit_flag_false_for_null_override(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Audit flag is False when override value is null."""
        exposures = _exposures_with_dd(
            risk_weights=[0.50],
            override_rws=[None],
        )
        result = calculator._apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["due_diligence_override_applied"][0] is False

    def test_audit_flag_absent_under_crr(
        self, calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """Audit column is not added under CRR."""
        exposures = _exposures_with_dd(
            risk_weights=[0.50],
            override_rws=[0.75],
        )
        result = calculator._apply_due_diligence_override(exposures, crr_config)
        df = result.collect()
        assert "due_diligence_override_applied" not in df.columns

    def test_audit_flag_absent_when_column_missing(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Audit column is not added when override column is absent."""
        exposures = _exposures_without_dd(risk_weights=[0.50])
        result = calculator._apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert "due_diligence_override_applied" not in df.columns


# =============================================================================
# Warning Tests
# =============================================================================


class TestDueDiligenceWarnings:
    """Tests for due diligence validation warnings."""

    def test_warning_when_dd_performed_absent_b31(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Warning emitted when due_diligence_performed column is absent under B31."""
        errors: list[CalculationError] = []
        exposures = _exposures_without_dd(risk_weights=[0.50])
        calculator._apply_due_diligence_override(
            exposures, b31_config, errors=errors
        )
        assert len(errors) == 1
        assert errors[0].code == ERROR_DUE_DILIGENCE_NOT_PERFORMED

    def test_warning_severity_is_warning(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Warning has WARNING severity (not ERROR)."""
        errors: list[CalculationError] = []
        exposures = _exposures_without_dd(risk_weights=[0.50])
        calculator._apply_due_diligence_override(
            exposures, b31_config, errors=errors
        )
        assert errors[0].severity == ErrorSeverity.WARNING

    def test_warning_category_is_data_quality(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Warning category is DATA_QUALITY."""
        errors: list[CalculationError] = []
        exposures = _exposures_without_dd(risk_weights=[0.50])
        calculator._apply_due_diligence_override(
            exposures, b31_config, errors=errors
        )
        assert errors[0].category == ErrorCategory.DATA_QUALITY

    def test_warning_has_regulatory_reference(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Warning includes Art. 110A regulatory reference."""
        errors: list[CalculationError] = []
        exposures = _exposures_without_dd(risk_weights=[0.50])
        calculator._apply_due_diligence_override(
            exposures, b31_config, errors=errors
        )
        assert "110A" in (errors[0].regulatory_reference or "")

    def test_warning_has_field_name(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Warning includes the expected field name."""
        errors: list[CalculationError] = []
        exposures = _exposures_without_dd(risk_weights=[0.50])
        calculator._apply_due_diligence_override(
            exposures, b31_config, errors=errors
        )
        assert errors[0].field_name == "due_diligence_performed"

    def test_no_warning_under_crr(
        self, calculator: SACalculator, crr_config: CalculationConfig
    ) -> None:
        """No warning under CRR even if DD column is absent."""
        errors: list[CalculationError] = []
        exposures = _exposures_without_dd(risk_weights=[0.50])
        calculator._apply_due_diligence_override(
            exposures, crr_config, errors=errors
        )
        assert len(errors) == 0

    def test_no_warning_when_dd_performed_present(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """No warning when due_diligence_performed column is present."""
        errors: list[CalculationError] = []
        exposures = _exposures_with_dd(
            risk_weights=[0.50],
            override_rws=[None],
            dd_performed=[True],
        )
        calculator._apply_due_diligence_override(
            exposures, b31_config, errors=errors
        )
        assert len(errors) == 0

    def test_no_warning_when_errors_none(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """No crash when errors parameter is None (unified/branch paths)."""
        exposures = _exposures_without_dd(risk_weights=[0.50])
        # Should not raise — warnings are silently skipped
        result = calculator._apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.50)

    def test_warning_only_once_not_per_row(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Warning is emitted once per calculation, not per row."""
        errors: list[CalculationError] = []
        exposures = _exposures_without_dd(risk_weights=[0.50, 0.75, 1.00])
        calculator._apply_due_diligence_override(
            exposures, b31_config, errors=errors
        )
        assert len(errors) == 1


# =============================================================================
# Edge Cases
# =============================================================================


class TestDueDiligenceEdgeCases:
    """Edge cases for due diligence override."""

    def test_zero_override_ignored(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Zero override RW is lower than any valid RW and is ignored."""
        exposures = _exposures_with_dd(
            risk_weights=[0.20],
            override_rws=[0.0],
        )
        result = calculator._apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.20)

    def test_very_high_override_applied(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Very high override RW (e.g. 12.5 = 1250%) is correctly applied."""
        exposures = _exposures_with_dd(
            risk_weights=[1.00],
            override_rws=[12.5],
        )
        result = calculator._apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(12.5)

    def test_override_with_dd_performed_false(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Override applied even when due_diligence_performed is False.

        The override_rw is independent of the performed flag. If a firm provides
        an override value, it is applied regardless of the DD assessment status.
        """
        exposures = _exposures_with_dd(
            risk_weights=[0.50],
            override_rws=[0.75],
            dd_performed=[False],
        )
        result = calculator._apply_due_diligence_override(exposures, b31_config)
        df = result.collect()
        assert df["risk_weight"][0] == pytest.approx(0.75)

    def test_override_preserves_other_columns(
        self, calculator: SACalculator, b31_config: CalculationConfig
    ) -> None:
        """Override does not drop or alter other columns."""
        lf = pl.DataFrame(
            {
                "exposure_reference": ["EXP_001"],
                "risk_weight": [0.50],
                "due_diligence_override_rw": [0.75],
                "exposure_class": ["corporate"],
                "ead_final": [100_000.0],
            }
        ).lazy()
        result = calculator._apply_due_diligence_override(lf, b31_config)
        df = result.collect()
        assert df["exposure_class"][0] == "corporate"
        assert df["ead_final"][0] == pytest.approx(100_000.0)
        assert df["risk_weight"][0] == pytest.approx(0.75)
