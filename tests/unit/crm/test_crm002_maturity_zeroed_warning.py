"""
CRM002: the Art. 237-239 maturity treatment reports what it took away.

Why this matters:
    Until the 2026-09-05 escape, ``ERROR_MATURITY_MISMATCH`` (CRM002) was declared
    and never produced. Protection zeroed by an Art. 237 gate or scaled by the
    Art. 238 factor left no record, so a fully netted interbank loan that lost its
    whole benefit to a fabricated mismatch showed LGD 45% and nothing else. The
    warning is rolled up to one count-carrying record per run (the CRM018 idiom)
    so a large book cannot flood the error channel.

References:
    CRR / PS1-26 Art. 237(1), 237(2)(a)-(b): eligibility gates that zero protection.
    CRR / PS1-26 Art. 238-239: (t - 0.25) / (T - 0.25) scaling.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import (
    ERROR_MATURITY_MISMATCH,
    CalculationError,
    ErrorSeverity,
)
from rwa_calc.engine.crm.haircuts import (
    HaircutCalculator,
    _record_maturity_mismatch_adjustments,
)


def _collateral_frame(
    factors: list[float],
    values: list[float],
) -> pl.LazyFrame:
    """Minimal post-mismatch collateral frame carrying the recorder's signal columns."""
    n = len(factors)
    return pl.LazyFrame(
        {
            "collateral_reference": [f"COLL{i}" for i in range(n)],
            "beneficiary_reference": [f"LOAN{i}" for i in range(n)],
            "value_after_haircut": values,
            "maturity_adjustment_factor": factors,
        },
        schema={
            "collateral_reference": pl.String,
            "beneficiary_reference": pl.String,
            "value_after_haircut": pl.Float64,
            "maturity_adjustment_factor": pl.Float64,
        },
    )


class TestCrm002RollsUpToOneWarning:
    """CRM002 is one count-carrying warning per run, never one per row."""

    def test_zeroed_and_scaled_rows_emit_single_warning_with_both_counts(self) -> None:
        # Arrange: two rows zeroed, one scaled, one untouched, one zeroed-but-worthless.
        lf = _collateral_frame(
            factors=[0.0, 0.0, 0.5, 1.0, 0.0],
            values=[1000.0, 250.0, 1000.0, 1000.0, 0.0],
        )
        errors: list[CalculationError] = []

        # Act
        _record_maturity_mismatch_adjustments(lf, errors)

        # Assert: exactly one CRM002 carrying "2 ... zeroed" and "1 ... scaled".
        assert len(errors) == 1
        warning = errors[0]
        assert warning.code == ERROR_MATURITY_MISMATCH
        assert warning.severity == ErrorSeverity.WARNING
        assert "2 collateral row(s)" in warning.message
        assert "1 row(s)" in warning.message
        assert warning.regulatory_reference == "CRR/PS1-26 Art. 237-239"

    def test_only_scaled_rows_still_emit_one_warning(self) -> None:
        # Arrange
        lf = _collateral_frame(factors=[0.6, 1.0], values=[1000.0, 1000.0])
        errors: list[CalculationError] = []

        # Act
        _record_maturity_mismatch_adjustments(lf, errors)

        # Assert
        assert len(errors) == 1
        assert "0 collateral row(s)" in errors[0].message
        assert "1 row(s)" in errors[0].message

    def test_untouched_rows_emit_nothing(self) -> None:
        # Arrange: every factor is 1.0.
        lf = _collateral_frame(factors=[1.0, 1.0, 1.0], values=[1000.0, 1000.0, 1000.0])
        errors: list[CalculationError] = []

        # Act
        _record_maturity_mismatch_adjustments(lf, errors)

        # Assert
        assert errors == []

    def test_null_factor_or_value_drops_out_of_the_count(self) -> None:
        # Arrange: a null factor and a null value must neither count nor raise.
        lf = pl.LazyFrame(
            {
                "collateral_reference": ["COLL0", "COLL1", "COLL2"],
                "beneficiary_reference": ["LOAN0", "LOAN1", "LOAN2"],
                "value_after_haircut": [None, 1000.0, 1000.0],
                "maturity_adjustment_factor": [0.0, None, 0.0],
            },
            schema={
                "collateral_reference": pl.String,
                "beneficiary_reference": pl.String,
                "value_after_haircut": pl.Float64,
                "maturity_adjustment_factor": pl.Float64,
            },
        )
        errors: list[CalculationError] = []

        # Act
        _record_maturity_mismatch_adjustments(lf, errors)

        # Assert: only COLL2 counts.
        assert len(errors) == 1
        assert "1 collateral row(s)" in errors[0].message


class TestCrm002ThroughApplyMaturityMismatch:
    """The warning is produced by the treatment itself when an error channel is given."""

    def _frame(self, coll_years: float, exposure_days: int, reporting: date) -> pl.LazyFrame:
        return pl.LazyFrame(
            {
                "residual_maturity_years": [coll_years],
                "exposure_maturity": [reporting + timedelta(days=exposure_days)],
                "value_after_haircut": [1000.0],
            },
            schema={
                "residual_maturity_years": pl.Float64,
                "exposure_maturity": pl.Date,
                "value_after_haircut": pl.Float64,
            },
        )

    def test_real_mismatch_records_crm002(self) -> None:
        # Arrange: 30-day collateral against a 2-year exposure → Art. 237(1) zero.
        config = CalculationConfig.crr(reporting_date=date(2025, 12, 31))
        lf = self._frame(30 / 365.25, 730, config.reporting_date)
        errors: list[CalculationError] = []

        # Act
        result = HaircutCalculator().apply_maturity_mismatch(lf, config, errors=errors).collect()

        # Assert
        assert result["maturity_adjustment_factor"][0] == 0.0
        assert [e.code for e in errors] == [ERROR_MATURITY_MISMATCH]

    def test_matched_pair_records_nothing(self) -> None:
        # Arrange: 30-day collateral against a 30-day exposure → no mismatch.
        config = CalculationConfig.crr(reporting_date=date(2025, 12, 31))
        lf = self._frame(30 / 365.25, 30, config.reporting_date)
        errors: list[CalculationError] = []

        # Act
        HaircutCalculator().apply_maturity_mismatch(lf, config, errors=errors).collect()

        # Assert
        assert errors == []

    def test_no_error_channel_is_silent_and_unchanged(self) -> None:
        # Arrange: direct callers that pass no channel get the same frame back.
        config = CalculationConfig.crr(reporting_date=date(2025, 12, 31))
        lf = self._frame(30 / 365.25, 730, config.reporting_date)

        # Act
        result = HaircutCalculator().apply_maturity_mismatch(lf, config).collect()

        # Assert
        assert result["maturity_adjustment_factor"][0] == 0.0
