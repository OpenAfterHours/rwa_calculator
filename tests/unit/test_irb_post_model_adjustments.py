"""
Tests for IRB post-model adjustments (Basel 3.1).

Why: PRA PS9/24 Art. 153(5A), 154(4A), 158(6A) require post-model
adjustments (PMAs) to IRB model outputs. These tests verify that the
IRB namespace correctly applies mortgage RW floors, general PMAs,
unrecognised exposure adjustments, and EL adjustments — and that CRR
exposures are unaffected.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

import rwa_calc.engine.irb.namespace  # noqa: F401 — register namespace
from rwa_calc.contracts.config import (
    CalculationConfig,
    PostModelAdjustmentConfig,
)


def _make_irb_frame(
    exposure_class: str = "corporate",
    rwa: float = 1000.0,
    risk_weight: float = 0.50,
    ead_final: float = 2000.0,
    expected_loss: float = 10.0,
) -> pl.LazyFrame:
    """Minimal IRB frame with columns expected by apply_post_model_adjustments."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP_1"],
            "exposure_class": [exposure_class],
            "rwa": [rwa],
            "risk_weight": [risk_weight],
            "ead_final": [ead_final],
            "expected_loss": [expected_loss],
        }
    )


def _b31_config(
    pma_rwa_scalar: Decimal = Decimal("0.0"),
    pma_el_scalar: Decimal = Decimal("0.0"),
    mortgage_rw_floor: Decimal = Decimal("0.15"),
    unrecognised_exposure_scalar: Decimal = Decimal("0.0"),
) -> CalculationConfig:
    """Basel 3.1 config with custom PMA settings."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2028, 3, 31),
        post_model_adjustments=PostModelAdjustmentConfig.basel_3_1(
            pma_rwa_scalar=pma_rwa_scalar,
            pma_el_scalar=pma_el_scalar,
            mortgage_rw_floor=mortgage_rw_floor,
            unrecognised_exposure_scalar=unrecognised_exposure_scalar,
        ),
    )


class TestPostModelAdjustmentsCRR:
    """CRR framework: PMAs disabled, columns added with zero values."""

    def test_crr_rwa_unchanged(self) -> None:
        """CRR: RWA is not modified by PMAs."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        lf = _make_irb_frame(rwa=1000.0)
        result = lf.irb.apply_post_model_adjustments(config).collect()
        assert result["rwa"][0] == pytest.approx(1000.0)

    def test_crr_pma_columns_zero(self) -> None:
        """CRR: PMA adjustment columns are zero."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        result = _make_irb_frame().irb.apply_post_model_adjustments(config).collect()
        assert result["post_model_adjustment_rwa"][0] == pytest.approx(0.0)
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(0.0)
        assert result["unrecognised_exposure_adjustment"][0] == pytest.approx(0.0)

    def test_crr_el_unchanged(self) -> None:
        """CRR: Expected loss not modified."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        result = _make_irb_frame(expected_loss=10.0).irb.apply_post_model_adjustments(config).collect()
        assert result["el_after_adjustment"][0] == pytest.approx(10.0)


class TestPostModelAdjustmentsBasel31:
    """Basel 3.1: PMAs applied when enabled and configured."""

    def test_general_pma_rwa(self) -> None:
        """General PMA adds scalar × base_rwa to RWEA."""
        config = _b31_config(pma_rwa_scalar=Decimal("0.05"))
        result = _make_irb_frame(rwa=1000.0).irb.apply_post_model_adjustments(config).collect()
        assert result["rwa_pre_adjustments"][0] == pytest.approx(1000.0)
        assert result["post_model_adjustment_rwa"][0] == pytest.approx(50.0)
        # Final RWA = 1000 + 50 = 1050
        assert result["rwa"][0] == pytest.approx(1050.0)

    def test_mortgage_rw_floor_binding(self) -> None:
        """Mortgage RW floor increases RWEA when modelled RW < floor."""
        config = _b31_config(mortgage_rw_floor=Decimal("0.15"))
        # Mortgage with RW=0.10 < floor=0.15 → floor adds (0.15-0.10)*EAD
        lf = _make_irb_frame(
            exposure_class="retail_mortgage",
            rwa=200.0,
            risk_weight=0.10,
            ead_final=2000.0,
        )
        result = lf.irb.apply_post_model_adjustments(config).collect()
        # Floor adjustment = (0.15 - 0.10) * 2000 = 100.0
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(100.0)
        # Final RWA = 200 + 100 = 300
        assert result["rwa"][0] == pytest.approx(300.0)

    def test_mortgage_rw_floor_non_binding(self) -> None:
        """Mortgage RW floor has no effect when modelled RW >= floor."""
        config = _b31_config(mortgage_rw_floor=Decimal("0.15"))
        lf = _make_irb_frame(
            exposure_class="retail_mortgage",
            rwa=400.0,
            risk_weight=0.20,
            ead_final=2000.0,
        )
        result = lf.irb.apply_post_model_adjustments(config).collect()
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(0.0)
        assert result["rwa"][0] == pytest.approx(400.0)

    def test_mortgage_floor_corporate_unaffected(self) -> None:
        """Mortgage RW floor only applies to mortgage exposures, not corporate."""
        config = _b31_config(mortgage_rw_floor=Decimal("0.15"))
        lf = _make_irb_frame(
            exposure_class="corporate",
            rwa=200.0,
            risk_weight=0.10,
            ead_final=2000.0,
        )
        result = lf.irb.apply_post_model_adjustments(config).collect()
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(0.0)

    def test_unrecognised_exposure_adjustment(self) -> None:
        """Unrecognised exposure adjustment adds scalar × base_rwa."""
        config = _b31_config(unrecognised_exposure_scalar=Decimal("0.02"))
        result = _make_irb_frame(rwa=1000.0).irb.apply_post_model_adjustments(config).collect()
        assert result["unrecognised_exposure_adjustment"][0] == pytest.approx(20.0)
        assert result["rwa"][0] == pytest.approx(1020.0)

    def test_all_adjustments_combined(self) -> None:
        """All three RWEA adjustments stack additively."""
        config = _b31_config(
            pma_rwa_scalar=Decimal("0.05"),
            mortgage_rw_floor=Decimal("0.20"),
            unrecognised_exposure_scalar=Decimal("0.02"),
        )
        lf = _make_irb_frame(
            exposure_class="retail_mortgage",
            rwa=200.0,
            risk_weight=0.10,
            ead_final=2000.0,
        )
        result = lf.irb.apply_post_model_adjustments(config).collect()
        # General PMA: 200 * 0.05 = 10
        assert result["post_model_adjustment_rwa"][0] == pytest.approx(10.0)
        # Mortgage floor: (0.20 - 0.10) * 2000 = 200
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(200.0)
        # Unrecognised: 200 * 0.02 = 4
        assert result["unrecognised_exposure_adjustment"][0] == pytest.approx(4.0)
        # Total: 200 + 10 + 200 + 4 = 414
        assert result["rwa"][0] == pytest.approx(414.0)

    def test_el_adjustment(self) -> None:
        """EL adjustment adds scalar × base_el to expected loss."""
        config = _b31_config(pma_el_scalar=Decimal("0.10"))
        result = _make_irb_frame(expected_loss=10.0).irb.apply_post_model_adjustments(config).collect()
        assert result["el_pre_adjustment"][0] == pytest.approx(10.0)
        assert result["post_model_adjustment_el"][0] == pytest.approx(1.0)
        assert result["el_after_adjustment"][0] == pytest.approx(11.0)

    def test_zero_scalars_no_change(self) -> None:
        """With all scalars at zero (and no mortgage floor), RWA unchanged."""
        config = _b31_config(
            pma_rwa_scalar=Decimal("0.0"),
            mortgage_rw_floor=Decimal("0.0"),
            unrecognised_exposure_scalar=Decimal("0.0"),
        )
        result = _make_irb_frame(rwa=1000.0).irb.apply_post_model_adjustments(config).collect()
        assert result["rwa"][0] == pytest.approx(1000.0)

    def test_residential_exposure_class_triggers_mortgage_floor(self) -> None:
        """'residential_mortgage' exposure class triggers mortgage RW floor."""
        config = _b31_config(mortgage_rw_floor=Decimal("0.15"))
        lf = _make_irb_frame(
            exposure_class="residential_mortgage",
            rwa=200.0,
            risk_weight=0.10,
            ead_final=2000.0,
        )
        result = lf.irb.apply_post_model_adjustments(config).collect()
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(100.0)


class TestPostModelAdjustmentConfig:
    """Test PostModelAdjustmentConfig factory methods."""

    def test_crr_disabled(self) -> None:
        """CRR config has PMAs disabled."""
        config = PostModelAdjustmentConfig.crr()
        assert config.enabled is False

    def test_b31_enabled(self) -> None:
        """Basel 3.1 config has PMAs enabled."""
        config = PostModelAdjustmentConfig.basel_3_1()
        assert config.enabled is True

    def test_b31_default_mortgage_floor(self) -> None:
        """Basel 3.1 default mortgage RW floor is 15%."""
        config = PostModelAdjustmentConfig.basel_3_1()
        assert config.mortgage_rw_floor == Decimal("0.15")

    def test_b31_custom_scalars(self) -> None:
        """Basel 3.1 config accepts custom scalars."""
        config = PostModelAdjustmentConfig.basel_3_1(
            pma_rwa_scalar=Decimal("0.10"),
            unrecognised_exposure_scalar=Decimal("0.03"),
        )
        assert config.pma_rwa_scalar == Decimal("0.10")
        assert config.unrecognised_exposure_scalar == Decimal("0.03")

    def test_calculation_config_b31_includes_pma(self) -> None:
        """CalculationConfig.basel_3_1() includes PMAs by default."""
        config = CalculationConfig.basel_3_1(reporting_date=date(2028, 3, 31))
        assert config.post_model_adjustments.enabled is True

    def test_calculation_config_crr_excludes_pma(self) -> None:
        """CalculationConfig.crr() excludes PMAs."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        assert config.post_model_adjustments.enabled is False
