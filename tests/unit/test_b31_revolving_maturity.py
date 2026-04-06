"""Unit tests for Basel 3.1 revolving maturity (Art. 162(2A)(k)).

Under Basel 3.1, IRB effective maturity (M) for revolving exposures must use
the maximum contractual termination date of the facility, not the repayment
date of the current drawing. This typically increases M, leading to higher
maturity adjustments and capital requirements.

CRR path is unchanged — revolving and non-revolving both use maturity_date.

References:
- PRA PS1/26 Art. 162(2A)(k)
- CRR Art. 162(2)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb import IRBExpr, IRBLazyFrame  # noqa: F401 - registers namespace


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Basel 3.1 config with reporting date 2030-06-30."""
    return CalculationConfig.basel_3_1(reporting_date=date(2030, 6, 30))


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR config with reporting date 2024-12-31."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


# =============================================================================
# Tests
# =============================================================================


class TestB31RevolvingMaturity:
    """Tests for Art. 162(2A)(k) revolving maturity under Basel 3.1."""

    def test_revolving_uses_termination_date_b31(self, b31_config: CalculationConfig) -> None:
        """Revolving exposure under B31 should use facility_termination_date for M.

        maturity_date = 2031-06-30 → M = 1.0 year
        facility_termination_date = 2035-06-30 → M = 5.0 years
        Under B31, revolving should use the termination date → M = 5.0.
        """
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2031, 6, 30)],  # 1yr from reporting
                "facility_termination_date": [date(2035, 6, 30)],  # 5yr from reporting
                "is_revolving": [True],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = lf.irb.prepare_columns(b31_config).collect()
        # M should be 5.0 (capped), derived from facility_termination_date
        assert result["maturity"][0] == pytest.approx(5.0, abs=0.05)

    def test_non_revolving_uses_maturity_date_b31(self, b31_config: CalculationConfig) -> None:
        """Non-revolving exposure under B31 should use maturity_date for M."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2031, 6, 30)],  # 1yr from reporting
                "facility_termination_date": [date(2035, 6, 30)],  # 5yr from reporting
                "is_revolving": [False],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = lf.irb.prepare_columns(b31_config).collect()
        # M should be ~1.0, derived from maturity_date (not termination date)
        assert result["maturity"][0] == pytest.approx(1.0, abs=0.05)

    def test_crr_revolving_ignores_termination_date(
        self, crr_config: CalculationConfig
    ) -> None:
        """Under CRR, revolving exposures use maturity_date regardless of termination date."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2025, 12, 31)],  # 1yr from CRR reporting
                "facility_termination_date": [date(2029, 12, 31)],  # 5yr from CRR reporting
                "is_revolving": [True],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = lf.irb.prepare_columns(crr_config).collect()
        # CRR ignores termination date — M from maturity_date ≈ 1.0
        assert result["maturity"][0] == pytest.approx(1.0, abs=0.05)

    def test_revolving_null_termination_date_falls_back_to_maturity(
        self, b31_config: CalculationConfig
    ) -> None:
        """When facility_termination_date is null, revolving B31 falls back to maturity_date."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2033, 6, 30)],  # 3yr
                "facility_termination_date": [None],
                "is_revolving": [True],
                "exposure_class": ["CORPORATE"],
            }
        ).cast({"facility_termination_date": pl.Date})

        result = lf.irb.prepare_columns(b31_config).collect()
        # Null termination date → fall back to maturity_date → M ≈ 3.0
        assert result["maturity"][0] == pytest.approx(3.0, abs=0.05)

    def test_revolving_missing_termination_col_falls_back_to_maturity(
        self, b31_config: CalculationConfig
    ) -> None:
        """When facility_termination_date column is absent, use maturity_date (backward compat)."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2033, 6, 30)],  # 3yr
                "is_revolving": [True],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = lf.irb.prepare_columns(b31_config).collect()
        # No termination date column → use maturity_date → M ≈ 3.0
        assert result["maturity"][0] == pytest.approx(3.0, abs=0.05)

    def test_revolving_termination_date_capped_at_5yr(
        self, b31_config: CalculationConfig
    ) -> None:
        """Revolving maturity from termination date is still capped at 5 years."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2031, 6, 30)],  # 1yr
                "facility_termination_date": [date(2040, 6, 30)],  # 10yr from reporting
                "is_revolving": [True],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = lf.irb.prepare_columns(b31_config).collect()
        # 10 years from reporting but capped at 5.0
        assert result["maturity"][0] == pytest.approx(5.0, abs=0.01)

    def test_revolving_termination_date_floored_at_1yr(
        self, b31_config: CalculationConfig
    ) -> None:
        """Revolving maturity from termination date is floored at 1 year."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2030, 9, 30)],  # 0.25yr
                "facility_termination_date": [date(2030, 9, 30)],  # 0.25yr from reporting
                "is_revolving": [True],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = lf.irb.prepare_columns(b31_config).collect()
        # 0.25yr from reporting but floored at 1.0
        assert result["maturity"][0] == pytest.approx(1.0, abs=0.01)

    def test_mixed_revolving_non_revolving_batch(
        self, b31_config: CalculationConfig
    ) -> None:
        """Mixed batch: revolving uses termination date, non-revolving uses maturity_date."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01, 0.01, 0.01],
                "lgd": [0.45, 0.45, 0.45],
                "ead_final": [1_000_000.0, 1_000_000.0, 1_000_000.0],
                "maturity_date": [
                    date(2031, 6, 30),  # 1yr
                    date(2031, 6, 30),  # 1yr
                    date(2031, 6, 30),  # 1yr
                ],
                "facility_termination_date": [
                    date(2034, 6, 30),  # 4yr — revolving will use this
                    date(2034, 6, 30),  # 4yr — non-revolving ignores this
                    None,  # null — revolving falls back to maturity_date
                ],
                "is_revolving": [True, False, True],
                "exposure_class": ["CORPORATE", "CORPORATE", "CORPORATE"],
            }
        ).cast({"facility_termination_date": pl.Date})

        result = lf.irb.prepare_columns(b31_config).collect()
        # Row 0: revolving + termination date → M ≈ 4.0
        assert result["maturity"][0] == pytest.approx(4.0, abs=0.05)
        # Row 1: non-revolving → M ≈ 1.0 (from maturity_date)
        assert result["maturity"][1] == pytest.approx(1.0, abs=0.05)
        # Row 2: revolving + null termination → fall back to maturity_date → M ≈ 1.0
        assert result["maturity"][2] == pytest.approx(1.0, abs=0.05)

    def test_revolving_null_is_revolving_defaults_non_revolving(
        self, b31_config: CalculationConfig
    ) -> None:
        """Null is_revolving defaults to False (non-revolving, conservative)."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2031, 6, 30)],  # 1yr
                "facility_termination_date": [date(2035, 6, 30)],  # 5yr
                "is_revolving": [None],
                "exposure_class": ["CORPORATE"],
            }
        ).cast({"is_revolving": pl.Boolean})

        result = lf.irb.prepare_columns(b31_config).collect()
        # Null is_revolving → treated as non-revolving → M from maturity_date ≈ 1.0
        assert result["maturity"][0] == pytest.approx(1.0, abs=0.05)

    def test_revolving_rwa_higher_with_termination_date(
        self, b31_config: CalculationConfig
    ) -> None:
        """Revolving exposure RWA should be higher when using termination date (longer M)."""
        base_data = {
            "pd": [0.01],
            "lgd": [0.45],
            "ead_final": [1_000_000.0],
            "exposure_class": ["CORPORATE"],
        }

        # Non-revolving: M from maturity_date ≈ 1yr → lower MA → lower RWA
        lf_non_revolving = pl.LazyFrame(
            {
                **base_data,
                "maturity_date": [date(2031, 6, 30)],  # 1yr
                "facility_termination_date": [date(2035, 6, 30)],  # 5yr
                "is_revolving": [False],
            }
        )
        rwa_non_revolving = (
            lf_non_revolving.irb.prepare_columns(b31_config)
            .irb.apply_all_formulas(b31_config)
            .collect()["rwa"][0]
        )

        # Revolving: M from termination date ≈ 5yr → higher MA → higher RWA
        lf_revolving = pl.LazyFrame(
            {
                **base_data,
                "maturity_date": [date(2031, 6, 30)],  # 1yr
                "facility_termination_date": [date(2035, 6, 30)],  # 5yr
                "is_revolving": [True],
            }
        )
        rwa_revolving = (
            lf_revolving.irb.prepare_columns(b31_config)
            .irb.apply_all_formulas(b31_config)
            .collect()["rwa"][0]
        )

        # Revolving should have higher RWA due to longer effective maturity
        assert rwa_revolving > rwa_non_revolving
        # With 5yr vs 1yr M, the difference should be substantial
        assert rwa_revolving > rwa_non_revolving * 1.1

    def test_retail_revolving_no_maturity_adjustment(
        self, b31_config: CalculationConfig
    ) -> None:
        """Retail revolving exposures still get MA=1.0 (retail exemption overrides maturity)."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2031, 6, 30)],  # 1yr
                "facility_termination_date": [date(2035, 6, 30)],  # 5yr
                "is_revolving": [True],
                "exposure_class": ["RETAIL_QRRE"],
            }
        )

        result = (
            lf.irb.prepare_columns(b31_config)
            .irb.apply_all_formulas(b31_config)
            .collect()
        )
        # Retail always gets MA = 1.0 regardless of maturity source
        assert result["maturity_adjustment"][0] == pytest.approx(1.0)

    def test_revolving_missing_is_revolving_col_uses_maturity_date(
        self, b31_config: CalculationConfig
    ) -> None:
        """When is_revolving column is absent, all exposures use maturity_date."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2031, 6, 30)],  # 1yr
                "facility_termination_date": [date(2035, 6, 30)],  # 5yr
                "exposure_class": ["CORPORATE"],
            }
        )

        result = lf.irb.prepare_columns(b31_config).collect()
        # No is_revolving column → treated as non-revolving → M from maturity_date ≈ 1.0
        assert result["maturity"][0] == pytest.approx(1.0, abs=0.05)
