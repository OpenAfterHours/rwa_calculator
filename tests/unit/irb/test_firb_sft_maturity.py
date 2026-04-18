"""
Unit tests for CRR Art. 162(1) F-IRB fixed supervisory maturity for repo-style SFTs.

CRR Art. 162(1) requires F-IRB firms to assign:
- M = 0.5 years to exposures arising from repurchase transactions or securities or
  commodities lending or borrowing transactions.
- M = 2.5 years to all other exposures.

Basel 3.1 deleted Art. 162(1); B31 F-IRB firms calculate M per Art. 162(2A) using the
actual maturity_date / facility_termination_date. The `is_sft` override therefore only
fires under CRR.

The `is_sft` flag is surfaced on Facility/Loan/Contingent inputs and propagates through
the hierarchy into the unified exposures frame consumed by `irb.prepare_columns()`.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

import rwa_calc.engine.irb.namespace  # noqa: F401 - Register namespace
from rwa_calc.contracts.config import CalculationConfig


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 12, 31))


def _firb_frame(
    *,
    is_sft: bool | None,
    maturity_date: date | None = None,
) -> pl.LazyFrame:
    """Minimal F-IRB exposure frame for maturity-only assertions."""
    data: dict[str, object] = {
        "exposure_reference": ["EXP001"],
        "pd": [0.01],
        "lgd": [0.45],
        "ead_final": [1_000_000.0],
        "exposure_class": ["CORPORATE"],
        "approach": ["foundation_irb"],
    }
    lf = pl.LazyFrame(data)
    maturity_col = pl.Series("maturity_date", [maturity_date], dtype=pl.Date)
    lf = lf.with_columns(maturity_col)
    if is_sft is not None:
        lf = lf.with_columns(pl.lit(is_sft).alias("is_sft"))
    return lf


class TestFIRBRepoSFTMaturity:
    """CRR Art. 162(1): F-IRB SFT maturity = 0.5y; non-SFT = 2.5y (via default)."""

    def test_firb_sft_overrides_to_half_year_under_crr(
        self, crr_config: CalculationConfig
    ) -> None:
        lf = _firb_frame(is_sft=True, maturity_date=date(2034, 12, 31))

        result = (
            lf.irb.classify_approach(crr_config)
            .irb.prepare_columns(crr_config)
            .collect()
        )

        assert result["maturity"][0] == pytest.approx(0.5)

    def test_firb_non_sft_uses_default_maturity_under_crr(
        self, crr_config: CalculationConfig
    ) -> None:
        lf = _firb_frame(is_sft=False, maturity_date=None)

        result = (
            lf.irb.classify_approach(crr_config)
            .irb.prepare_columns(crr_config)
            .collect()
        )

        assert result["maturity"][0] == pytest.approx(2.5)

    def test_firb_sft_absent_column_keeps_default(
        self, crr_config: CalculationConfig
    ) -> None:
        lf = _firb_frame(is_sft=None, maturity_date=None)

        result = (
            lf.irb.classify_approach(crr_config)
            .irb.prepare_columns(crr_config)
            .collect()
        )

        assert result["maturity"][0] == pytest.approx(2.5)

    def test_firb_sft_flag_ignored_under_basel_3_1(
        self, b31_config: CalculationConfig
    ) -> None:
        """B31 deleted Art. 162(1); is_sft must NOT force 0.5y."""
        lf = _firb_frame(is_sft=True, maturity_date=date(2037, 6, 30))

        result = (
            lf.irb.classify_approach(b31_config)
            .irb.prepare_columns(b31_config)
            .collect()
        )

        # Under B31, maturity is derived from maturity_date (clamped to [1, 5]).
        assert result["maturity"][0] != pytest.approx(0.5)
        assert result["maturity"][0] >= 1.0

    def test_airb_sft_flag_does_not_override(
        self, crr_config: CalculationConfig
    ) -> None:
        """Art. 162(1) applies only to F-IRB; A-IRB calculates M per Art. 162(2)."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "exposure_class": ["CORPORATE"],
                "approach": ["advanced_irb"],
                "maturity_date": [date(2028, 12, 31)],
                "is_sft": [True],
            }
        )

        result = (
            lf.irb.classify_approach(crr_config)
            .irb.prepare_columns(crr_config)
            .collect()
        )

        # A-IRB uses maturity_date (clamped to [1, 5]) — not forced to 0.5y.
        assert result["maturity"][0] != pytest.approx(0.5)
        assert result["maturity"][0] >= 1.0

    def test_firb_sft_overrides_explicit_maturity_date_under_crr(
        self, crr_config: CalculationConfig
    ) -> None:
        """Per Art. 162(1), the F-IRB supervisory M is a fixed regulatory value —
        an explicit maturity_date must not raise M above 0.5y for repo-style SFTs."""
        lf = _firb_frame(is_sft=True, maturity_date=date(2029, 12, 31))

        result = (
            lf.irb.classify_approach(crr_config)
            .irb.prepare_columns(crr_config)
            .collect()
        )

        assert result["maturity"][0] == pytest.approx(0.5)
