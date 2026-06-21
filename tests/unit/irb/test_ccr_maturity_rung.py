"""Unit tests for the ``ccr_effective_maturity`` carrier rung in the IRB
effective-maturity priority chain (CRR Art. 162(2)/(3) / PS1/26 162(2A)/(3)).

Synthetic FCCM SFT rows (``risk_type="CCR_SFT"``) carry their full Art. 162 M
on a dedicated ``ccr_effective_maturity`` Float64 carrier — the floor is a
MINIMUM already applied at the producer, so the carrier IS the resolved M and
must NOT be re-clipped to [1y, 5y] inside the chain.

Priority requirements verified here:
- AIRB CCR_SFT with a sub-1y carrier resolves to the carrier value (NOT re-floored
  to 1.0y) and sets ``has_one_day_maturity_floor=True`` so the maturity adjustment
  uses the sub-1y M (NOT the 1y floor).
- A firm-supplied ``effective_maturity`` override still wins over the carrier.
- FIRB rows ignore the carrier (FIRB 0.5y from Art. 162(1) must not be displaced).
- The carrier is feature-gated on ``ccr_synthetic_maturity`` — off → inert.
- Lending rows (no ``ccr_effective_maturity``) are untouched.

References:
- CRR Art. 162(2)(d) repo 5BD floor; Art. 162(3) one-day floor
- PS1/26 paragraph 162(2A)/(3)
- ``src/rwa_calc/engine/irb/transforms.py::_build_maturity_exprs``
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.contract_columns import pad_crm_exit_defaults as _pad

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb.transforms import (
    apply_all_formulas,
    classify_approach,
    prepare_columns,
)

ONE_DAY = 1.0 / 365.0
FIVE_BD = 5.0 / 365.0  # Art. 162(2)(d) repo floor expressed /365 (Phase-1b)


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2026, 1, 1))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 12, 31))


def _ccr_sft_frame(
    *,
    approach: str,
    ccr_effective_maturity: float | None,
    maturity_date: date | None = date(2026, 5, 7),
    effective_maturity: float | None = None,
    risk_type: str = "CCR_SFT",
) -> pl.LazyFrame:
    """Minimal IRB exposure frame carrying the CCR maturity carrier."""
    lf = pl.LazyFrame(
        {
            "exposure_reference": ["EXP001"],
            "pd": [0.01],
            "lgd": [0.45],
            "ead_final": [1_000_000.0],
            "exposure_class": ["CORPORATE"],
            "approach": [approach],
        }
    )
    lf = lf.with_columns(
        pl.Series("maturity_date", [maturity_date], dtype=pl.Date),
        pl.Series("ccr_effective_maturity", [ccr_effective_maturity], dtype=pl.Float64),
        pl.Series("effective_maturity", [effective_maturity], dtype=pl.Float64),
        pl.lit(risk_type).alias("risk_type"),
    )
    return _pad(lf)


class TestCarrierRungResolution:
    """The carrier drives M for AIRB CCR_SFT rows without re-clipping."""

    def test_airb_carrier_5bd_survives_uncliped(self, crr_config: CalculationConfig) -> None:
        lf = _ccr_sft_frame(approach="advanced_irb", ccr_effective_maturity=FIVE_BD)

        result = lf.pipe(classify_approach, crr_config).pipe(prepare_columns, crr_config).collect()

        assert result["maturity"][0] == pytest.approx(FIVE_BD, abs=1e-12)

    def test_airb_carrier_one_day_survives_uncliped(self, crr_config: CalculationConfig) -> None:
        lf = _ccr_sft_frame(approach="advanced_irb", ccr_effective_maturity=ONE_DAY)

        result = lf.pipe(classify_approach, crr_config).pipe(prepare_columns, crr_config).collect()

        assert result["maturity"][0] == pytest.approx(ONE_DAY, abs=1e-12)

    def test_airb_carrier_sets_one_day_floor_flag(self, crr_config: CalculationConfig) -> None:
        """Sub-1y carrier must set the MA 1y-floor suppressor."""
        lf = _ccr_sft_frame(approach="advanced_irb", ccr_effective_maturity=FIVE_BD)

        result = lf.pipe(classify_approach, crr_config).pipe(prepare_columns, crr_config).collect()

        assert result["has_one_day_maturity_floor"][0] is True

    def test_airb_long_carrier_does_not_set_flag(self, crr_config: CalculationConfig) -> None:
        """A >= 1y carrier resolves to the carrier value and must NOT set the
        suppressor (the 1y MA floor is inert at >= 1y anyway)."""
        lf = _ccr_sft_frame(approach="advanced_irb", ccr_effective_maturity=2.5)

        result = lf.pipe(classify_approach, crr_config).pipe(prepare_columns, crr_config).collect()

        assert result["maturity"][0] == pytest.approx(2.5, abs=1e-12)
        assert result["has_one_day_maturity_floor"][0] is False

    def test_airb_sub_one_year_carrier_sets_flag(self, crr_config: CalculationConfig) -> None:
        """A sub-1y carrier (e.g. 0.8y, floor inert but still < 1y) MUST set the
        suppressor so the MA uses 0.8 rather than re-flooring it up to 1.0y."""
        lf = _ccr_sft_frame(approach="advanced_irb", ccr_effective_maturity=0.8)

        result = lf.pipe(classify_approach, crr_config).pipe(prepare_columns, crr_config).collect()

        assert result["maturity"][0] == pytest.approx(0.8, abs=1e-12)
        assert result["has_one_day_maturity_floor"][0] is True


class TestCarrierMaturityAdjustmentBites:
    """The sub-1y carrier M must actually flow into the maturity adjustment."""

    def test_airb_carrier_ma_uses_sub_one_year_m(self, crr_config: CalculationConfig) -> None:
        """MA must reflect M=5/365, NOT be re-floored to 1.0y (MA < 1.0)."""
        lf = _ccr_sft_frame(approach="advanced_irb", ccr_effective_maturity=FIVE_BD)

        result = (
            lf.pipe(classify_approach, crr_config)
            .pipe(prepare_columns, crr_config)
            .pipe(apply_all_formulas, crr_config)
            .collect()
        )

        assert result["maturity"][0] == pytest.approx(FIVE_BD, abs=1e-12)
        assert result["maturity_adjustment"][0] < 1.0


class TestCarrierPrecedence:
    """Firm override > carrier; FIRB 0.5y not displaced; lending untouched."""

    def test_firm_override_wins_over_carrier(self, crr_config: CalculationConfig) -> None:
        lf = _ccr_sft_frame(
            approach="advanced_irb", ccr_effective_maturity=FIVE_BD, effective_maturity=0.3
        )

        result = lf.pipe(classify_approach, crr_config).pipe(prepare_columns, crr_config).collect()

        assert result["maturity"][0] == pytest.approx(0.3, abs=1e-9)

    def test_carrier_ignored_for_firb_rows(self, crr_config: CalculationConfig) -> None:
        """A FIRB CCR_SFT row keeps the 0.5y supervisory M; the carrier must not
        displace it even when populated with a sub-1y value."""
        lf = _ccr_sft_frame(approach="foundation_irb", ccr_effective_maturity=ONE_DAY)

        result = lf.pipe(classify_approach, crr_config).pipe(prepare_columns, crr_config).collect()

        assert result["maturity"][0] == pytest.approx(0.5, abs=1e-12)

    def test_lending_row_without_carrier_untouched(self, crr_config: CalculationConfig) -> None:
        """A lending row (no ccr_effective_maturity column) resolves date-derived M."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "exposure_class": ["CORPORATE"],
                "approach": ["advanced_irb"],
                "maturity_date": [date(2031, 1, 1)],  # 5y → clipped to 5.0
            }
        )

        result = (
            _pad(lf).pipe(classify_approach, crr_config).pipe(prepare_columns, crr_config).collect()
        )

        assert result["maturity"][0] == pytest.approx(5.0, abs=0.05)
        assert result["has_one_day_maturity_floor"][0] is False


class TestCarrierFeatureGate:
    """The carrier rung is gated on the ``ccr_synthetic_maturity`` feature."""

    def test_carrier_active_under_b31(self, b31_config: CalculationConfig) -> None:
        """B31 keeps the carrier (only 162(1) was deleted)."""
        lf = _ccr_sft_frame(approach="advanced_irb", ccr_effective_maturity=FIVE_BD)

        result = lf.pipe(classify_approach, b31_config).pipe(prepare_columns, b31_config).collect()

        assert result["maturity"][0] == pytest.approx(FIVE_BD, abs=1e-12)
        assert result["has_one_day_maturity_floor"][0] is True


class TestPackScalarHoming:
    """The homed pack scalars preserve the byte-identical values."""

    def test_one_day_floor_value_preserved(self, b31_config: CalculationConfig) -> None:
        """has_one_day_maturity_floor → M resolves to exactly 1/365."""
        lf = pl.LazyFrame(
            {
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity_date": [date(2035, 6, 30)],
                "has_one_day_maturity_floor": [True],
                "exposure_class": ["CORPORATE"],
            }
        )

        result = _pad(lf).pipe(prepare_columns, b31_config).collect()

        assert result["maturity"][0] == pytest.approx(ONE_DAY, abs=1e-15)
