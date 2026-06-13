"""
Tests for EL shortfall/excess error reporting when expected_loss column is absent.

P6.10: compute_el_shortfall_excess previously silently returned zero for both
el_shortfall and el_excess when expected_loss was missing. Now emits a
CalculationError warning so downstream consumers (T2 credit cap, CET1
deduction) can detect the data quality issue.

References:
    CRR Art. 158-159: EL shortfall treatment
    CRR Art. 62(d): T2 credit cap depends on accurate EL shortfall/excess
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.errors import (
    ERROR_MISSING_EXPECTED_LOSS,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
)
from rwa_calc.engine.irb.adjustments import compute_el_shortfall_excess
from rwa_calc.engine.irb.transforms import (
    compute_el_shortfall_excess as irb_compute_el_shortfall_excess,
)
from rwa_calc.engine.slotting.transforms import (
    compute_el_shortfall_excess as slotting_compute_el_shortfall_excess,
)

# =============================================================================
# HELPERS
# =============================================================================


def _frame_without_expected_loss() -> pl.LazyFrame:
    """Build a frame missing expected_loss — triggers the warning."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP_001", "EXP_002"],
            "provision_allocated": [5_000.0, 3_000.0],
        }
    )


def _frame_with_expected_loss() -> pl.LazyFrame:
    """Build a frame WITH expected_loss — no warning expected."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP_001"],
            "expected_loss": [10_000.0],
            "provision_allocated": [6_000.0],
            "ava_amount": [0.0],
            "other_own_funds_reductions": [0.0],
        }
    )


# =============================================================================
# IRB adjustments.compute_el_shortfall_excess
# =============================================================================


class TestIRBELShortfallErrorReporting:
    """IRB EL shortfall emits warning when expected_loss absent."""

    def test_emits_warning_when_expected_loss_absent(self) -> None:
        """Warning emitted when expected_loss column is missing."""
        errors: list[CalculationError] = []
        lf = _frame_without_expected_loss()
        compute_el_shortfall_excess(lf, errors=errors).collect()

        assert len(errors) == 1
        err = errors[0]
        assert err.code == ERROR_MISSING_EXPECTED_LOSS
        assert err.severity == ErrorSeverity.WARNING
        assert err.category == ErrorCategory.DATA_QUALITY
        assert err.field_name == "expected_loss"
        assert "T2 credit cap" in err.message

    def test_still_returns_zero_columns_when_absent(self) -> None:
        """Backward compat: still adds el_shortfall=0, el_excess=0 columns."""
        errors: list[CalculationError] = []
        lf = _frame_without_expected_loss()
        result = compute_el_shortfall_excess(lf, errors=errors).collect()

        assert "el_shortfall" in result.columns
        assert "el_excess" in result.columns
        assert result["el_shortfall"].to_list() == [0.0, 0.0]
        assert result["el_excess"].to_list() == [0.0, 0.0]

    def test_no_warning_when_expected_loss_present(self) -> None:
        """No warning when expected_loss column exists."""
        errors: list[CalculationError] = []
        lf = _frame_with_expected_loss()
        compute_el_shortfall_excess(lf, errors=errors).collect()

        assert len(errors) == 0

    def test_no_error_when_errors_param_is_none(self) -> None:
        """No crash when errors parameter is None (backward compat)."""
        lf = _frame_without_expected_loss()
        result = compute_el_shortfall_excess(lf, errors=None).collect()

        assert result["el_shortfall"].to_list() == [0.0, 0.0]

    def test_no_error_when_errors_param_omitted(self) -> None:
        """No crash when errors parameter is omitted (backward compat)."""
        lf = _frame_without_expected_loss()
        result = compute_el_shortfall_excess(lf).collect()

        assert result["el_shortfall"].to_list() == [0.0, 0.0]

    def test_error_has_regulatory_reference(self) -> None:
        """Error includes CRR Art. 158-159 regulatory reference."""
        errors: list[CalculationError] = []
        compute_el_shortfall_excess(_frame_without_expected_loss(), errors=errors).collect()

        assert errors[0].regulatory_reference == "CRR Art. 158-159"


# =============================================================================
# SLOTTING transforms compute_el_shortfall_excess
# =============================================================================


class TestSlottingELShortfallErrorReporting:
    """Slotting EL shortfall emits warning when expected_loss absent."""

    def test_emits_warning_when_expected_loss_absent(self) -> None:
        """Warning emitted via slotting transforms path."""
        errors: list[CalculationError] = []
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL_001"],
                "provision_allocated": [1_000.0],
            }
        )
        slotting_compute_el_shortfall_excess(lf, errors=errors).collect()

        assert len(errors) == 1
        err = errors[0]
        assert err.code == ERROR_MISSING_EXPECTED_LOSS
        assert err.severity == ErrorSeverity.WARNING
        assert err.category == ErrorCategory.DATA_QUALITY
        assert "slotting" in err.message

    def test_no_warning_when_expected_loss_present(self) -> None:
        """No warning when expected_loss column exists in slotting frame."""
        errors: list[CalculationError] = []
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SL_001"],
                "expected_loss": [5_000.0],
                "provision_allocated": [3_000.0],
                "ava_amount": [0.0],
                "other_own_funds_reductions": [0.0],
            }
        )
        slotting_compute_el_shortfall_excess(lf, errors=errors).collect()

        assert len(errors) == 0

    def test_still_returns_zero_columns_when_absent(self) -> None:
        """Backward compat: still adds zero columns in slotting path."""
        errors: list[CalculationError] = []
        lf = pl.LazyFrame({"exposure_reference": ["SL_001"]})
        result = slotting_compute_el_shortfall_excess(lf, errors=errors).collect()

        assert result["el_shortfall"][0] == pytest.approx(0.0)
        assert result["el_excess"][0] == pytest.approx(0.0)

    def test_no_crash_without_errors_param(self) -> None:
        """Backward compat: calling without errors= still works."""
        lf = pl.LazyFrame({"exposure_reference": ["SL_001"]})
        result = slotting_compute_el_shortfall_excess(lf).collect()

        assert result["el_shortfall"][0] == pytest.approx(0.0)


# =============================================================================
# IRB transforms wrapper
# =============================================================================


class TestIRBTransformsELShortfallErrorReporting:
    """IRB transforms wrapper passes errors through correctly."""

    def test_transforms_passes_errors_through(self) -> None:
        """Errors list is populated when calling the transforms wrapper."""

        errors: list[CalculationError] = []
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP_001"],
                "provision_allocated": [1_000.0],
            }
        )
        lf.pipe(irb_compute_el_shortfall_excess, errors=errors).collect()

        assert len(errors) == 1
        assert errors[0].code == ERROR_MISSING_EXPECTED_LOSS

    def test_transforms_no_errors_when_el_present(self) -> None:
        """No errors when expected_loss exists via the transforms wrapper."""

        errors: list[CalculationError] = []
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP_001"],
                "expected_loss": [10_000.0],
                "provision_allocated": [6_000.0],
                "ava_amount": [0.0],
                "other_own_funds_reductions": [0.0],
            }
        )
        lf.pipe(irb_compute_el_shortfall_excess, errors=errors).collect()

        assert len(errors) == 0
