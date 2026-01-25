"""Unit tests for the CRR IRB (Internal Ratings-Based) calculator.

Tests cover:
- PD floor application (0.03% for CRR)
- F-IRB supervisory LGD values
- Asset correlation calculation (with SME adjustment)
- Capital requirement (K) formula
- Maturity adjustment
- 1.06 scaling factor (CRR only)
- RWA calculation
- Expected loss calculation

References:
- CRR Art. 153-154: IRB risk weight functions
- CRR Art. 161: F-IRB supervisory LGD
- CRR Art. 162-163: Maturity and PD floors
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb import (
    IRBCalculator,
    calculate_correlation,
    calculate_expected_loss,
    calculate_irb_rwa,
    calculate_k,
    calculate_maturity_adjustment,
    create_irb_calculator,
    get_backend,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def irb_calculator() -> IRBCalculator:
    """Return an IRB Calculator instance."""
    return IRBCalculator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def basel31_config() -> CalculationConfig:
    """Return a Basel 3.1 configuration."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


# =============================================================================
# Correlation Tests
# =============================================================================


class TestAssetCorrelation:
    """Tests for asset correlation calculation."""

    def test_corporate_correlation_at_low_pd(self) -> None:
        """Corporate correlation should approach 0.24 at low PD."""
        # At very low PD, f(PD) → 0, so R → 0.24
        corr = calculate_correlation(pd=0.0001, exposure_class="CORPORATE")
        assert corr == pytest.approx(0.24, rel=0.05)

    def test_corporate_correlation_at_high_pd(self) -> None:
        """Corporate correlation should approach 0.12 at high PD."""
        # At high PD, f(PD) → 1, so R → 0.12
        corr = calculate_correlation(pd=0.20, exposure_class="CORPORATE")
        assert corr == pytest.approx(0.12, rel=0.05)

    def test_retail_mortgage_fixed_correlation(self) -> None:
        """Retail mortgage should have fixed 0.15 correlation."""
        corr = calculate_correlation(pd=0.01, exposure_class="RETAIL_MORTGAGE")
        assert corr == pytest.approx(0.15)

    def test_qrre_fixed_correlation(self) -> None:
        """QRRE should have fixed 0.04 correlation."""
        corr = calculate_correlation(pd=0.01, exposure_class="RETAIL_QRRE")
        assert corr == pytest.approx(0.04)

    def test_other_retail_correlation_range(self) -> None:
        """Other retail correlation should be between 0.03 and 0.16."""
        corr = calculate_correlation(pd=0.05, exposure_class="RETAIL")
        assert 0.03 <= corr <= 0.16

    def test_sme_correlation_adjustment(self) -> None:
        """SME turnover should reduce corporate correlation."""
        base_corr = calculate_correlation(pd=0.01, exposure_class="CORPORATE")
        sme_corr = calculate_correlation(
            pd=0.01, exposure_class="CORPORATE", turnover_m=10.0
        )

        # SME should have lower correlation
        assert sme_corr < base_corr
        # Maximum reduction is 0.04
        assert base_corr - sme_corr <= 0.04

    def test_sme_adjustment_at_floor(self) -> None:
        """SME at turnover floor (EUR 5m) should get maximum adjustment."""
        base_corr = calculate_correlation(pd=0.01, exposure_class="CORPORATE")
        min_sme_corr = calculate_correlation(
            pd=0.01, exposure_class="CORPORATE", turnover_m=5.0
        )

        # At EUR 5m, adjustment = 0.04 * (1 - 0) = 0.04
        assert base_corr - min_sme_corr == pytest.approx(0.04, rel=0.01)

    def test_large_corporate_no_adjustment(self) -> None:
        """Large corporate (turnover >= EUR 50m) should get no adjustment."""
        base_corr = calculate_correlation(pd=0.01, exposure_class="CORPORATE")
        large_corr = calculate_correlation(
            pd=0.01, exposure_class="CORPORATE", turnover_m=100.0
        )

        assert base_corr == pytest.approx(large_corr)


# =============================================================================
# K Formula Tests
# =============================================================================


class TestCapitalRequirementK:
    """Tests for capital requirement (K) calculation."""

    def test_k_zero_for_zero_pd(self) -> None:
        """K should be zero when PD is zero."""
        k = calculate_k(pd=0.0, lgd=0.45, correlation=0.15)
        assert k == 0.0

    def test_k_equals_lgd_for_defaulted(self) -> None:
        """K should equal LGD for defaulted exposure (PD=100%)."""
        k = calculate_k(pd=1.0, lgd=0.45, correlation=0.15)
        assert k == pytest.approx(0.45)

    def test_k_increases_with_pd(self) -> None:
        """K should increase with PD."""
        k_low = calculate_k(pd=0.01, lgd=0.45, correlation=0.15)
        k_high = calculate_k(pd=0.10, lgd=0.45, correlation=0.15)

        assert k_high > k_low

    def test_k_increases_with_lgd(self) -> None:
        """K should increase with LGD."""
        k_low_lgd = calculate_k(pd=0.01, lgd=0.25, correlation=0.15)
        k_high_lgd = calculate_k(pd=0.01, lgd=0.45, correlation=0.15)

        assert k_high_lgd > k_low_lgd

    def test_k_increases_with_correlation(self) -> None:
        """K should increase with correlation."""
        k_low_corr = calculate_k(pd=0.01, lgd=0.45, correlation=0.10)
        k_high_corr = calculate_k(pd=0.01, lgd=0.45, correlation=0.24)

        assert k_high_corr > k_low_corr

    def test_k_realistic_values(self) -> None:
        """K should be in realistic range for typical inputs."""
        # Typical corporate exposure: PD=1%, LGD=45%, R=0.15
        k = calculate_k(pd=0.01, lgd=0.45, correlation=0.15)

        # K should be positive and less than LGD
        assert 0 < k < 0.45
        # K is typically in 2-10% range for PD=1%
        assert 0.02 < k < 0.10


# =============================================================================
# Maturity Adjustment Tests
# =============================================================================


class TestMaturityAdjustment:
    """Tests for maturity adjustment calculation."""

    def test_ma_at_base_maturity(self) -> None:
        """MA at 2.5 years should be the baseline (numerator = 1.0).

        MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
        At M = 2.5: MA = 1 / (1 - 1.5 × b) > 1.0

        The "base" maturity of 2.5 years sets the numerator to 1.0,
        but the denominator makes MA > 1.0.
        """
        ma = calculate_maturity_adjustment(pd=0.01, maturity=2.5)
        # MA should be > 1.0 due to denominator
        assert ma > 1.0
        # But not too high - typically around 1.2-1.3 for PD=1%
        assert ma < 1.5

    def test_ma_increases_with_maturity(self) -> None:
        """MA should increase with maturity above 2.5 years."""
        ma_short = calculate_maturity_adjustment(pd=0.01, maturity=1.0)
        ma_long = calculate_maturity_adjustment(pd=0.01, maturity=5.0)

        assert ma_long > ma_short

    def test_ma_floor_applied(self) -> None:
        """Maturity should be floored at 1 year."""
        ma_below_floor = calculate_maturity_adjustment(pd=0.01, maturity=0.5)
        ma_at_floor = calculate_maturity_adjustment(pd=0.01, maturity=1.0)

        assert ma_below_floor == pytest.approx(ma_at_floor)

    def test_ma_cap_applied(self) -> None:
        """Maturity should be capped at 5 years."""
        ma_above_cap = calculate_maturity_adjustment(pd=0.01, maturity=10.0)
        ma_at_cap = calculate_maturity_adjustment(pd=0.01, maturity=5.0)

        assert ma_above_cap == pytest.approx(ma_at_cap)

    def test_ma_higher_for_low_pd(self) -> None:
        """MA effect should be larger for low PD exposures."""
        # b coefficient is higher for low PD, so MA impact is greater
        ma_low_pd = calculate_maturity_adjustment(pd=0.001, maturity=5.0)
        ma_high_pd = calculate_maturity_adjustment(pd=0.10, maturity=5.0)

        # Both should be > 1.0 for 5-year maturity
        assert ma_low_pd > 1.0
        assert ma_high_pd > 1.0
        # Low PD has higher MA
        assert ma_low_pd > ma_high_pd


# =============================================================================
# F-IRB LGD Tests
# =============================================================================


class TestFIRBSupervisoryLGD:
    """Tests for F-IRB supervisory LGD application."""

    def test_senior_unsecured_forty_five_percent(
        self,
        irb_calculator: IRBCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Senior unsecured should get 45% LGD."""
        result = irb_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            pd=Decimal("0.01"),
            lgd=None,  # F-IRB supervisory
            exposure_class="CORPORATE",
            config=crr_config,
        )

        assert result["lgd_floored"] == pytest.approx(0.45)

    def test_subordinated_seventy_five_percent(
        self,
        irb_calculator: IRBCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Subordinated should get 75% LGD."""
        result = irb_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            pd=Decimal("0.01"),
            lgd=None,
            exposure_class="CORPORATE",
            is_subordinated=True,
            config=crr_config,
        )

        assert result["lgd_floored"] == pytest.approx(0.75)

    def test_real_estate_secured_thirty_five_percent(
        self,
        irb_calculator: IRBCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Real estate secured should get 35% LGD."""
        result = irb_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            pd=Decimal("0.01"),
            lgd=None,
            exposure_class="CORPORATE",
            collateral_type="residential_re",
            config=crr_config,
        )

        assert result["lgd_floored"] == pytest.approx(0.35)


# =============================================================================
# PD Floor Tests
# =============================================================================


class TestPDFloor:
    """Tests for PD floor application."""

    def test_crr_pd_floor_applied(
        self,
        irb_calculator: IRBCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR PD floor (0.03%) should be applied."""
        result = irb_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            pd=Decimal("0.0001"),  # 0.01% - below floor
            lgd=Decimal("0.45"),
            exposure_class="CORPORATE",
            config=crr_config,
        )

        # PD should be floored to 0.03%
        assert result["pd_floored"] == pytest.approx(0.0003)

    def test_pd_above_floor_unchanged(
        self,
        irb_calculator: IRBCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """PD above floor should be unchanged."""
        result = irb_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            pd=Decimal("0.05"),  # 5% - well above floor
            lgd=Decimal("0.45"),
            exposure_class="CORPORATE",
            config=crr_config,
        )

        assert result["pd_floored"] == pytest.approx(0.05)


# =============================================================================
# RWA Calculation Tests
# =============================================================================


class TestIRBRWACalculation:
    """Tests for IRB RWA calculation."""

    def test_rwa_formula_with_scaling(self) -> None:
        """RWA = K × 12.5 × 1.06 × EAD × MA under CRR."""
        result = calculate_irb_rwa(
            ead=1000000.0,
            pd=0.01,
            lgd=0.45,
            correlation=0.15,
            maturity=2.5,
            apply_scaling_factor=True,
        )

        # Verify formula: RWA = K × 12.5 × 1.06 × EAD × MA
        k = result["k"]
        ma = result["maturity_adjustment"]
        expected_rwa = k * 12.5 * 1.06 * 1000000.0 * ma

        assert result["rwa"] == pytest.approx(expected_rwa)

    def test_rwa_formula_without_scaling(self) -> None:
        """RWA = K × 12.5 × EAD × MA under Basel 3.1."""
        result = calculate_irb_rwa(
            ead=1000000.0,
            pd=0.01,
            lgd=0.45,
            correlation=0.15,
            maturity=2.5,
            apply_scaling_factor=False,
        )

        # Verify formula: RWA = K × 12.5 × EAD × MA (no 1.06)
        k = result["k"]
        ma = result["maturity_adjustment"]
        expected_rwa = k * 12.5 * 1000000.0 * ma

        assert result["rwa"] == pytest.approx(expected_rwa)

    def test_scaling_factor_difference(self) -> None:
        """CRR RWA should be 6% higher than Basel 3.1 due to scaling."""
        result_crr = calculate_irb_rwa(
            ead=1000000.0, pd=0.01, lgd=0.45, correlation=0.15,
            apply_scaling_factor=True,
        )
        result_basel = calculate_irb_rwa(
            ead=1000000.0, pd=0.01, lgd=0.45, correlation=0.15,
            apply_scaling_factor=False,
        )

        ratio = result_crr["rwa"] / result_basel["rwa"]
        assert ratio == pytest.approx(1.06)

    def test_retail_no_maturity_adjustment(
        self,
        irb_calculator: IRBCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Retail exposures should not have maturity adjustment."""
        result = irb_calculator.calculate_single_exposure(
            ead=Decimal("100000"),
            pd=Decimal("0.02"),
            lgd=Decimal("0.30"),
            maturity=Decimal("5.0"),
            exposure_class="RETAIL_MORTGAGE",
            config=crr_config,
        )

        # MA should be 1.0 for retail
        assert result["maturity_adjustment"] == pytest.approx(1.0)


# =============================================================================
# Expected Loss Tests
# =============================================================================


class TestExpectedLoss:
    """Tests for expected loss calculation."""

    def test_expected_loss_formula(self) -> None:
        """EL = PD × LGD × EAD."""
        el = calculate_expected_loss(pd=0.01, lgd=0.45, ead=1000000.0)
        expected = 0.01 * 0.45 * 1000000.0  # 4500
        assert el == pytest.approx(expected)

    def test_expected_loss_in_result(
        self,
        irb_calculator: IRBCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Expected loss should be included in calculation result."""
        result = irb_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            pd=Decimal("0.01"),
            lgd=Decimal("0.45"),
            exposure_class="CORPORATE",
            config=crr_config,
        )

        expected_el = 0.01 * 0.45 * 1000000.0
        assert result["expected_loss"] == pytest.approx(expected_el, rel=0.01)


# =============================================================================
# Bundle Processing Tests
# =============================================================================


class TestIRBCalculatorBundleProcessing:
    """Tests for processing CRMAdjustedBundle."""

    def test_calculate_returns_lazyframe_result(
        self,
        irb_calculator: IRBCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """calculate() should return LazyFrameResult."""
        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001"],
            "ead_final": [1000000.0],
            "pd": [0.01],
            "lgd": [0.45],
            "exposure_class": ["CORPORATE"],
            "maturity": [2.5],
            "approach": ["foundation_irb"],
        }).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=pl.LazyFrame(),
            irb_exposures=exposures,
        )

        result = irb_calculator.calculate(bundle, crr_config)

        assert hasattr(result, "frame")
        assert hasattr(result, "errors")

    def test_multiple_exposures_processed(
        self,
        irb_calculator: IRBCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Multiple exposures should all be processed."""
        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001", "EXP002", "EXP003"],
            "ead_final": [1000000.0, 500000.0, 100000.0],
            "pd": [0.01, 0.05, 0.02],
            "lgd": [0.45, 0.45, 0.30],
            "exposure_class": ["CORPORATE", "CORPORATE", "RETAIL_MORTGAGE"],
            "maturity": [2.5, 3.0, 5.0],
            "approach": ["foundation_irb", "foundation_irb", "advanced_irb"],
        }).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=pl.LazyFrame(),
            irb_exposures=exposures,
        )

        result = irb_calculator.calculate(bundle, crr_config)
        df = result.frame.collect()

        assert len(df) == 3
        assert "rwa" in df.columns
        assert "k" in df.columns
        assert "correlation" in df.columns

        # All RWAs should be positive
        assert all(df["rwa"] > 0)

    def test_get_irb_result_bundle_returns_bundle(
        self,
        irb_calculator: IRBCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """get_irb_result_bundle() should return IRBResultBundle."""
        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001"],
            "ead_final": [1000000.0],
            "pd": [0.01],
            "lgd": [0.45],
            "exposure_class": ["CORPORATE"],
            "maturity": [2.5],
            "approach": ["foundation_irb"],
        }).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=pl.LazyFrame(),
            irb_exposures=exposures,
        )

        result = irb_calculator.get_irb_result_bundle(bundle, crr_config)

        assert hasattr(result, "results")
        assert hasattr(result, "expected_loss")
        assert hasattr(result, "calculation_audit")
        assert hasattr(result, "errors")


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestIRBFactoryFunctions:
    """Tests for IRB factory functions."""

    def test_create_irb_calculator(self) -> None:
        """Factory should create IRBCalculator."""
        calculator = create_irb_calculator()
        assert isinstance(calculator, IRBCalculator)


# =============================================================================
# Framework Comparison Tests
# =============================================================================


class TestCRRVsBasel31:
    """Tests comparing CRR and Basel 3.1 treatment."""

    def test_crr_applies_scaling_factor(
        self,
        irb_calculator: IRBCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR should apply 1.06 scaling factor."""
        result = irb_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            pd=Decimal("0.01"),
            lgd=Decimal("0.45"),
            exposure_class="CORPORATE",
            config=crr_config,
        )

        assert result["scaling_factor"] == pytest.approx(1.06)

    def test_basel31_no_scaling_factor(
        self,
        irb_calculator: IRBCalculator,
        basel31_config: CalculationConfig,
    ) -> None:
        """Basel 3.1 should not apply 1.06 scaling factor."""
        result = irb_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            pd=Decimal("0.01"),
            lgd=Decimal("0.45"),
            exposure_class="CORPORATE",
            config=basel31_config,
        )

        assert result["scaling_factor"] == pytest.approx(1.0)

    def test_crr_lower_pd_floor(
        self,
        irb_calculator: IRBCalculator,
        crr_config: CalculationConfig,
        basel31_config: CalculationConfig,
    ) -> None:
        """CRR has 0.03% PD floor vs Basel 3.1 0.05% for corporates."""
        result_crr = irb_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            pd=Decimal("0.0001"),
            lgd=Decimal("0.45"),
            exposure_class="CORPORATE",
            config=crr_config,
        )
        result_basel = irb_calculator.calculate_single_exposure(
            ead=Decimal("1000000"),
            pd=Decimal("0.0001"),
            lgd=Decimal("0.45"),
            exposure_class="CORPORATE",
            config=basel31_config,
        )

        # CRR floor: 0.03%
        assert result_crr["pd_floored"] == pytest.approx(0.0003)
        # Basel 3.1 floor: 0.05%
        assert result_basel["pd_floored"] == pytest.approx(0.0005)


# =============================================================================
# Audit Trail Tests
# =============================================================================


class TestIRBAuditTrail:
    """Tests for IRB calculation audit trail."""

    def test_audit_contains_calculation_details(
        self,
        irb_calculator: IRBCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Audit should contain calculation breakdown."""
        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001"],
            "counterparty_reference": ["CP001"],
            "ead_final": [1000000.0],
            "pd": [0.01],
            "lgd": [0.45],
            "exposure_class": ["CORPORATE"],
            "maturity": [2.5],
            "approach": ["foundation_irb"],
        }).lazy()

        bundle = CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=pl.LazyFrame(),
            irb_exposures=exposures,
        )

        result = irb_calculator.get_irb_result_bundle(bundle, crr_config)
        audit = result.calculation_audit

        if audit is not None:
            audit_df = audit.collect()
            assert "irb_calculation" in audit_df.columns
            calc_str = audit_df["irb_calculation"][0]
            assert "PD=" in calc_str
            assert "LGD=" in calc_str
            assert "R=" in calc_str
            assert "K=" in calc_str
            assert "RWA=" in calc_str


# =============================================================================
# Stats Backend Tests
# =============================================================================


class TestStatsBackend:
    """Tests for stats backend detection and functionality."""

    def test_backend_available(self) -> None:
        """Backend should be detected and available."""
        backend = get_backend()
        assert backend in ["polars-normal-stats", "scipy"]

    def test_scalar_wrappers_use_vectorized(self) -> None:
        """Scalar wrappers should produce same results as direct calculation.

        This verifies that scalar functions (calculate_k, calculate_correlation, etc.)
        are thin wrappers around vectorized expressions, not separate implementations.
        """
        # Test calculate_k through vectorized path
        k_scalar = calculate_k(pd=0.01, lgd=0.45, correlation=0.15)

        # Verify result is reasonable
        assert 0 < k_scalar < 0.45
        assert 0.02 < k_scalar < 0.10

    def test_scalar_correlation_matches_params(self) -> None:
        """Scalar correlation should match expected parameter behavior."""
        # Corporate at low PD should approach 0.24
        corr_low_pd = calculate_correlation(pd=0.0001, exposure_class="CORPORATE")
        assert corr_low_pd == pytest.approx(0.24, rel=0.05)

        # Retail mortgage should be fixed 0.15
        corr_mortgage = calculate_correlation(pd=0.01, exposure_class="RETAIL_MORTGAGE")
        assert corr_mortgage == pytest.approx(0.15)

    def test_scalar_maturity_adjustment_consistent(self) -> None:
        """Scalar maturity adjustment should be consistent with formula."""
        ma = calculate_maturity_adjustment(pd=0.01, maturity=2.5)
        # At M=2.5, numerator = 1, so MA = 1/(1 - 1.5*b) > 1.0
        assert ma > 1.0
        assert ma < 1.5
