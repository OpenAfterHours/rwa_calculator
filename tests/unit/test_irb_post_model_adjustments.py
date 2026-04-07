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
        result = (
            _make_irb_frame(expected_loss=10.0).irb.apply_post_model_adjustments(config).collect()
        )
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
        """All three RWEA adjustments stack per Art. 154(4A) sequencing.

        Why: Art. 154(4A)(b) mortgage floor is applied first to establish
        the post-floor RWEA base. Art. 154(4A)(a) PMA scalars then multiply
        the post-floor RWEA, capturing the floor increase in their base.
        """
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
        # Step 1: Mortgage floor: (0.20 - 0.10) * 2000 = 200
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(200.0)
        # Post-floor RWA = 200 + 200 = 400
        # Step 2: General PMA: 400 * 0.05 = 20 (applied to post-floor RWEA)
        assert result["post_model_adjustment_rwa"][0] == pytest.approx(20.0)
        # Step 2: Unrecognised: 400 * 0.02 = 8 (applied to post-floor RWEA)
        assert result["unrecognised_exposure_adjustment"][0] == pytest.approx(8.0)
        # Total: 200 + 200 + 20 + 8 = 428
        assert result["rwa"][0] == pytest.approx(428.0)

    def test_el_adjustment(self) -> None:
        """EL adjustment adds scalar × base_el to expected loss."""
        config = _b31_config(pma_el_scalar=Decimal("0.10"))
        result = (
            _make_irb_frame(expected_loss=10.0).irb.apply_post_model_adjustments(config).collect()
        )
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
        """Basel 3.1 default mortgage RW floor is 10% (PRA Art. 154(4A)(b))."""
        config = PostModelAdjustmentConfig.basel_3_1()
        assert config.mortgage_rw_floor == Decimal("0.10")

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


class TestPMASequencing:
    """Art. 153(5A)/154(4A): PMA scalars must use post-mortgage-floor RWEA.

    Why: PRA Art. 154(4A)(b) mortgage RW floor is applied first, then
    Art. 154(4A)(a) general PMAs are applied to the resulting RWEA.
    Applying PMA to pre-floor RWEA would understate capital for exposures
    that hit the mortgage floor.
    """

    def test_pma_uses_post_floor_rwa_not_pre_floor(self) -> None:
        """PMA scalar multiplies post-mortgage-floor RWEA, not pre-floor.

        Model RW=5% (RWA=100), mortgage floor=10%, PMA=10%.
        Pre-floor PMA would be 10, post-floor PMA should be 20.
        """
        config = _b31_config(
            pma_rwa_scalar=Decimal("0.10"),
            mortgage_rw_floor=Decimal("0.10"),
        )
        lf = _make_irb_frame(
            exposure_class="retail_mortgage",
            rwa=100.0,
            risk_weight=0.05,
            ead_final=2000.0,
        )
        result = lf.irb.apply_post_model_adjustments(config).collect()
        # Mortgage floor: (0.10 - 0.05) * 2000 = 100
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(100.0)
        # Post-floor RWA = 100 + 100 = 200
        # PMA: 200 * 0.10 = 20 (NOT 100 * 0.10 = 10)
        assert result["post_model_adjustment_rwa"][0] == pytest.approx(20.0)
        # Total: 100 + 100 + 20 = 220
        assert result["rwa"][0] == pytest.approx(220.0)

    def test_unrecognised_uses_post_floor_rwa(self) -> None:
        """Unrecognised exposure scalar also uses post-floor RWEA."""
        config = _b31_config(
            mortgage_rw_floor=Decimal("0.10"),
            unrecognised_exposure_scalar=Decimal("0.05"),
        )
        lf = _make_irb_frame(
            exposure_class="retail_mortgage",
            rwa=100.0,
            risk_weight=0.05,
            ead_final=2000.0,
        )
        result = lf.irb.apply_post_model_adjustments(config).collect()
        # Post-floor RWA = 100 + 100 = 200
        # Unrecognised: 200 * 0.05 = 10 (NOT 100 * 0.05 = 5)
        assert result["unrecognised_exposure_adjustment"][0] == pytest.approx(10.0)
        # Total: 100 + 100 + 10 = 210
        assert result["rwa"][0] == pytest.approx(210.0)

    def test_non_binding_floor_pma_uses_base_rwa(self) -> None:
        """When floor is non-binding, PMA uses original base RWA (no floor increase)."""
        config = _b31_config(
            pma_rwa_scalar=Decimal("0.10"),
            mortgage_rw_floor=Decimal("0.10"),
        )
        lf = _make_irb_frame(
            exposure_class="retail_mortgage",
            rwa=500.0,
            risk_weight=0.25,  # Above floor
            ead_final=2000.0,
        )
        result = lf.irb.apply_post_model_adjustments(config).collect()
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(0.0)
        # PMA: 500 * 0.10 = 50 (no floor increase, so base is still 500)
        assert result["post_model_adjustment_rwa"][0] == pytest.approx(50.0)
        assert result["rwa"][0] == pytest.approx(550.0)

    def test_corporate_with_pma_no_floor_effect(self) -> None:
        """Corporate exposures: mortgage floor inapplicable, PMA uses base RWA."""
        config = _b31_config(
            pma_rwa_scalar=Decimal("0.10"),
            mortgage_rw_floor=Decimal("0.10"),
        )
        lf = _make_irb_frame(
            exposure_class="corporate",
            rwa=1000.0,
            risk_weight=0.50,
            ead_final=2000.0,
        )
        result = lf.irb.apply_post_model_adjustments(config).collect()
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(0.0)
        assert result["post_model_adjustment_rwa"][0] == pytest.approx(100.0)
        assert result["rwa"][0] == pytest.approx(1100.0)

    def test_mixed_batch_sequencing(self) -> None:
        """Mixed mortgage+corporate batch: sequencing correct per-row.

        Why: Mortgage row has binding floor; corporate row doesn't.
        PMA must use different bases per row.
        """
        config = _b31_config(
            pma_rwa_scalar=Decimal("0.10"),
            mortgage_rw_floor=Decimal("0.10"),
        )
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["MTG_1", "CORP_1"],
                "exposure_class": ["retail_mortgage", "corporate"],
                "rwa": [100.0, 1000.0],
                "risk_weight": [0.05, 0.50],
                "ead_final": [2000.0, 2000.0],
                "expected_loss": [5.0, 50.0],
            }
        )
        result = lf.irb.apply_post_model_adjustments(config).collect()
        # Mortgage row: floor adjustment=100, post-floor RWA=200, PMA=20
        assert result["mortgage_rw_floor_adjustment"][0] == pytest.approx(100.0)
        assert result["post_model_adjustment_rwa"][0] == pytest.approx(20.0)
        assert result["rwa"][0] == pytest.approx(220.0)
        # Corporate row: no floor, PMA=1000*0.10=100
        assert result["mortgage_rw_floor_adjustment"][1] == pytest.approx(0.0)
        assert result["post_model_adjustment_rwa"][1] == pytest.approx(100.0)
        assert result["rwa"][1] == pytest.approx(1100.0)

    def test_rwa_pre_adjustments_records_original(self) -> None:
        """rwa_pre_adjustments captures original model RWA before any adjustment."""
        config = _b31_config(
            pma_rwa_scalar=Decimal("0.10"),
            mortgage_rw_floor=Decimal("0.15"),
        )
        lf = _make_irb_frame(
            exposure_class="retail_mortgage",
            rwa=200.0,
            risk_weight=0.10,
            ead_final=2000.0,
        )
        result = lf.irb.apply_post_model_adjustments(config).collect()
        assert result["rwa_pre_adjustments"][0] == pytest.approx(200.0)


class TestPMAELMonotonicity:
    """Art. 158(6A): PMA EL adjustments can only increase expected loss.

    Why: Art. 158(6A) explicitly requires that post-model EL adjustments
    result in EL >= pre-adjustment EL. A negative pma_el_scalar would
    decrease EL and understate capital shortfall.
    """

    def test_negative_pma_el_scalar_rejected(self) -> None:
        """Negative pma_el_scalar raises ValueError at config construction."""
        with pytest.raises(ValueError, match="pma_el_scalar must be >= 0"):
            PostModelAdjustmentConfig.basel_3_1(pma_el_scalar=Decimal("-0.05"))

    def test_negative_pma_rwa_scalar_rejected(self) -> None:
        """Negative pma_rwa_scalar raises ValueError."""
        with pytest.raises(ValueError, match="pma_rwa_scalar must be >= 0"):
            PostModelAdjustmentConfig.basel_3_1(pma_rwa_scalar=Decimal("-0.01"))

    def test_negative_unrecognised_scalar_rejected(self) -> None:
        """Negative unrecognised_exposure_scalar raises ValueError."""
        with pytest.raises(ValueError, match="unrecognised_exposure_scalar must be >= 0"):
            PostModelAdjustmentConfig.basel_3_1(unrecognised_exposure_scalar=Decimal("-0.10"))

    def test_negative_mortgage_floor_rejected(self) -> None:
        """Negative mortgage_rw_floor raises ValueError."""
        with pytest.raises(ValueError, match="mortgage_rw_floor must be >= 0"):
            PostModelAdjustmentConfig.basel_3_1(mortgage_rw_floor=Decimal("-0.05"))

    def test_zero_el_scalar_allowed(self) -> None:
        """Zero pma_el_scalar is valid (no EL adjustment)."""
        config = PostModelAdjustmentConfig.basel_3_1(pma_el_scalar=Decimal("0.0"))
        assert config.pma_el_scalar == Decimal("0.0")

    def test_el_adjustment_floored_at_zero_in_calculation(self) -> None:
        """Even if somehow a zero scalar is passed, EL adjustment never negative.

        Why: The calculation itself floors post_model_adjustment_el at 0,
        providing defense-in-depth beyond the config validation.
        """
        config = _b31_config(pma_el_scalar=Decimal("0.0"))
        result = (
            _make_irb_frame(expected_loss=10.0).irb.apply_post_model_adjustments(config).collect()
        )
        assert result["post_model_adjustment_el"][0] >= 0.0
        assert result["el_after_adjustment"][0] >= result["el_pre_adjustment"][0]

    def test_positive_el_scalar_increases_el(self) -> None:
        """Positive EL scalar correctly increases expected loss."""
        config = _b31_config(pma_el_scalar=Decimal("0.20"))
        result = (
            _make_irb_frame(expected_loss=100.0).irb.apply_post_model_adjustments(config).collect()
        )
        assert result["el_pre_adjustment"][0] == pytest.approx(100.0)
        assert result["post_model_adjustment_el"][0] == pytest.approx(20.0)
        assert result["el_after_adjustment"][0] == pytest.approx(120.0)

    def test_crr_disabled_config_allows_zero_defaults(self) -> None:
        """CRR config (disabled=True) passes validation with zero defaults."""
        config = PostModelAdjustmentConfig.crr()
        assert config.enabled is False
        assert config.pma_el_scalar == Decimal("0.0")
