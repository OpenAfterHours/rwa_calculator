"""Unit tests for the CCF (Credit Conversion Factor) calculator.

Tests cover:
- SA CCF calculation (0%, 20%, 50%, 100%) per CRR Art. 111
- F-IRB CCF calculation (75%) per CRR Art. 166(8)
- F-IRB exception for short-term trade LCs (20%) per CRR Art. 166(9)
- EAD calculation from undrawn commitments
- Approach-specific CCF selection
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.ccf import CCFCalculator, create_ccf_calculator


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def ccf_calculator() -> CCFCalculator:
    """Return a CCFCalculator instance."""
    return CCFCalculator()


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def contingent_exposures() -> pl.LazyFrame:
    """Contingent exposures for CCF testing."""
    return pl.DataFrame({
        "exposure_reference": ["CONT001", "CONT002", "CONT003", "CONT004", "CONT005"],
        "exposure_type": ["contingent"] * 5,
        "product_type": ["LC", "GUARANTEE", "UNDRAWN_RCF", "TRADE_LC", "CANCELLABLE"],
        "book_code": ["CORP"] * 5,
        "counterparty_reference": ["CP001", "CP002", "CP003", "CP004", "CP005"],
        "value_date": [date(2023, 1, 1)] * 5,
        "maturity_date": [date(2028, 1, 1)] * 5,
        "currency": ["GBP"] * 5,
        "drawn_amount": [0.0] * 5,
        "undrawn_amount": [0.0] * 5,
        "nominal_amount": [100000.0, 200000.0, 500000.0, 150000.0, 300000.0],
        "lgd": [0.45] * 5,
        "seniority": ["senior"] * 5,
        "ccf_category": [
            "medium_risk",       # 50% CCF
            "full_risk",         # 100% CCF
            "undrawn_long_term", # 50% CCF
            "documentary_credit",# 20% CCF
            "low_risk",          # 0% CCF
        ],
        "approach": ["standardised"] * 5,
    }).lazy()


# =============================================================================
# SA CCF Tests (CRR Art. 111)
# =============================================================================


class TestSACCF:
    """Tests for Standardised Approach CCF calculation."""

    def test_medium_risk_ccf_50_percent(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Medium risk items should get 50% CCF."""
        exposures = pl.DataFrame({
            "exposure_reference": ["CONT001"],
            "drawn_amount": [0.0],
            "nominal_amount": [100000.0],
            "ccf_category": ["medium_risk"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.50)
        assert result["ead_from_ccf"][0] == pytest.approx(50000.0)

    def test_full_risk_ccf_100_percent(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Full risk items (guarantees, acceptances) should get 100% CCF."""
        exposures = pl.DataFrame({
            "exposure_reference": ["CONT001"],
            "drawn_amount": [0.0],
            "nominal_amount": [200000.0],
            "ccf_category": ["full_risk"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(1.00)
        assert result["ead_from_ccf"][0] == pytest.approx(200000.0)

    def test_low_risk_ccf_0_percent(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Low risk (unconditionally cancellable) should get 0% CCF."""
        exposures = pl.DataFrame({
            "exposure_reference": ["CONT001"],
            "drawn_amount": [0.0],
            "nominal_amount": [300000.0],
            "ccf_category": ["low_risk"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.00)
        assert result["ead_from_ccf"][0] == pytest.approx(0.0)

    def test_documentary_credit_ccf_20_percent(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Documentary credits should get 20% CCF."""
        exposures = pl.DataFrame({
            "exposure_reference": ["CONT001"],
            "drawn_amount": [0.0],
            "nominal_amount": [150000.0],
            "ccf_category": ["documentary_credit"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.20)
        assert result["ead_from_ccf"][0] == pytest.approx(30000.0)

    def test_multiple_exposures_correct_ccf(
        self,
        ccf_calculator: CCFCalculator,
        contingent_exposures: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Multiple exposures should get correct CCFs applied."""
        result = ccf_calculator.apply_ccf(contingent_exposures, crr_config).collect()

        expected_ccfs = {
            "CONT001": 0.50,   # medium_risk
            "CONT002": 1.00,   # full_risk
            "CONT003": 0.50,   # undrawn_long_term
            "CONT004": 0.20,   # documentary_credit
            "CONT005": 0.00,   # low_risk
        }

        for ref, expected_ccf in expected_ccfs.items():
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ccf"][0] == pytest.approx(expected_ccf), f"CCF mismatch for {ref}"


# =============================================================================
# F-IRB CCF Tests (CRR Art. 166(8))
# =============================================================================


class TestFIRBCCF:
    """Tests for F-IRB CCF calculation (75% for undrawn commitments)."""

    def test_firb_undrawn_ccf_75_percent(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """F-IRB undrawn commitments should get 75% CCF per CRR Art. 166(8)."""
        exposures = pl.DataFrame({
            "exposure_reference": ["FIRB_CONT001"],
            "drawn_amount": [0.0],
            "nominal_amount": [1000000.0],
            "ccf_category": ["undrawn_long_term"],  # Would be 50% for SA
            "approach": ["foundation_irb"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # F-IRB should use 75% CCF, not SA's 50%
        assert result["ccf"][0] == pytest.approx(0.75)
        assert result["ead_from_ccf"][0] == pytest.approx(750000.0)

    def test_firb_unconditionally_cancellable_still_zero(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """F-IRB unconditionally cancellable should still get 0% CCF."""
        exposures = pl.DataFrame({
            "exposure_reference": ["FIRB_CANCEL001"],
            "drawn_amount": [0.0],
            "nominal_amount": [500000.0],
            "ccf_category": ["unconditionally_cancellable"],
            "approach": ["foundation_irb"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.00)
        assert result["ead_from_ccf"][0] == pytest.approx(0.0)

    def test_sa_vs_firb_ccf_difference(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SA and F-IRB should use different CCFs for same commitment type."""
        exposures = pl.DataFrame({
            "exposure_reference": ["SA_EXP", "FIRB_EXP"],
            "drawn_amount": [0.0, 0.0],
            "nominal_amount": [1000000.0, 1000000.0],
            "ccf_category": ["undrawn_long_term", "undrawn_long_term"],
            "approach": ["standardised", "foundation_irb"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # SA exposure: 50% CCF
        sa_row = result.filter(pl.col("exposure_reference") == "SA_EXP")
        assert sa_row["ccf"][0] == pytest.approx(0.50)
        assert sa_row["ead_from_ccf"][0] == pytest.approx(500000.0)

        # F-IRB exposure: 75% CCF
        firb_row = result.filter(pl.col("exposure_reference") == "FIRB_EXP")
        assert firb_row["ccf"][0] == pytest.approx(0.75)
        assert firb_row["ead_from_ccf"][0] == pytest.approx(750000.0)


# =============================================================================
# EAD Calculation Tests
# =============================================================================


class TestEADCalculation:
    """Tests for EAD calculation from CCF."""

    def test_total_ead_includes_drawn_and_ccf(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Total EAD should include drawn amount plus CCF-adjusted undrawn."""
        exposures = pl.DataFrame({
            "exposure_reference": ["EXP001"],
            "drawn_amount": [500000.0],  # Drawn portion
            "nominal_amount": [200000.0],  # Undrawn portion
            "ccf_category": ["medium_risk"],  # 50% CCF
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # EAD = drawn + (nominal * CCF) = 500k + (200k * 0.5) = 600k
        assert result["ead_pre_crm"][0] == pytest.approx(600000.0)

    def test_fully_drawn_loan_no_ccf_impact(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Fully drawn loan with no undrawn should have EAD = drawn amount."""
        exposures = pl.DataFrame({
            "exposure_reference": ["LOAN001"],
            "drawn_amount": [1000000.0],
            "nominal_amount": [0.0],
            "ccf_category": [None],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.0)
        assert result["ead_from_ccf"][0] == pytest.approx(0.0)
        assert result["ead_pre_crm"][0] == pytest.approx(1000000.0)


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestCCFFactory:
    """Tests for CCF factory function."""

    def test_create_ccf_calculator(self) -> None:
        """Factory should create CCFCalculator."""
        calculator = create_ccf_calculator()
        assert isinstance(calculator, CCFCalculator)


# =============================================================================
# Risk Type Based CCF Tests (CRR Art. 111)
# =============================================================================


class TestCCFFromRiskType:
    """Tests for CCF calculation from risk_type column."""

    def test_sa_ccf_from_risk_type_codes(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SA CCFs should be determined by risk_type codes."""
        exposures = pl.DataFrame({
            "exposure_reference": ["RT_FR", "RT_MR", "RT_MLR", "RT_LR"],
            "drawn_amount": [0.0, 0.0, 0.0, 0.0],
            "nominal_amount": [100000.0, 100000.0, 100000.0, 100000.0],
            "risk_type": ["FR", "MR", "MLR", "LR"],
            "approach": ["standardised", "standardised", "standardised", "standardised"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # FR = 100%, MR = 50%, MLR = 20%, LR = 0%
        expected = {
            "RT_FR": (1.00, 100000.0),
            "RT_MR": (0.50, 50000.0),
            "RT_MLR": (0.20, 20000.0),
            "RT_LR": (0.00, 0.0),
        }

        for ref, (expected_ccf, expected_ead) in expected.items():
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ccf"][0] == pytest.approx(expected_ccf), f"CCF mismatch for {ref}"
            assert row["ead_from_ccf"][0] == pytest.approx(expected_ead), f"EAD mismatch for {ref}"

    def test_sa_ccf_from_risk_type_full_values(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SA CCFs should work with full risk_type values."""
        exposures = pl.DataFrame({
            "exposure_reference": ["RT_FULL", "RT_MED", "RT_MEDLOW", "RT_LOW"],
            "drawn_amount": [0.0, 0.0, 0.0, 0.0],
            "nominal_amount": [100000.0, 100000.0, 100000.0, 100000.0],
            "risk_type": ["full_risk", "medium_risk", "medium_low_risk", "low_risk"],
            "approach": ["standardised"] * 4,
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        expected = {
            "RT_FULL": 1.00,
            "RT_MED": 0.50,
            "RT_MEDLOW": 0.20,
            "RT_LOW": 0.00,
        }

        for ref, expected_ccf in expected.items():
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ccf"][0] == pytest.approx(expected_ccf), f"CCF mismatch for {ref}"

    def test_firb_ccf_mr_mlr_become_75pct(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """F-IRB: MR and MLR should become 75% CCF per CRR Art. 166(8)."""
        exposures = pl.DataFrame({
            "exposure_reference": ["FIRB_FR", "FIRB_MR", "FIRB_MLR", "FIRB_LR"],
            "drawn_amount": [0.0, 0.0, 0.0, 0.0],
            "nominal_amount": [100000.0, 100000.0, 100000.0, 100000.0],
            "risk_type": ["FR", "MR", "MLR", "LR"],
            "approach": ["foundation_irb"] * 4,
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # F-IRB: FR = 100%, MR = 75%, MLR = 75%, LR = 0%
        expected = {
            "FIRB_FR": (1.00, 100000.0),
            "FIRB_MR": (0.75, 75000.0),   # MR becomes 75% under F-IRB
            "FIRB_MLR": (0.75, 75000.0),  # MLR becomes 75% under F-IRB
            "FIRB_LR": (0.00, 0.0),
        }

        for ref, (expected_ccf, expected_ead) in expected.items():
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ccf"][0] == pytest.approx(expected_ccf), f"CCF mismatch for {ref}"
            assert row["ead_from_ccf"][0] == pytest.approx(expected_ead), f"EAD mismatch for {ref}"

    def test_airb_uses_ccf_modelled(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """A-IRB should use ccf_modelled when provided."""
        exposures = pl.DataFrame({
            "exposure_reference": ["AIRB_001"],
            "drawn_amount": [0.0],
            "nominal_amount": [1000000.0],
            "risk_type": ["MR"],  # Would be 50% SA
            "ccf_modelled": [0.65],  # Bank's own estimate
            "approach": ["advanced_irb"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # A-IRB with ccf_modelled should use the modelled value (65%)
        assert result["ccf"][0] == pytest.approx(0.65)
        assert result["ead_from_ccf"][0] == pytest.approx(650000.0)

    def test_airb_fallback_when_no_ccf_modelled(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """A-IRB should fall back to SA CCF when ccf_modelled is null."""
        exposures = pl.DataFrame({
            "exposure_reference": ["AIRB_NULL"],
            "drawn_amount": [0.0],
            "nominal_amount": [100000.0],
            "risk_type": ["MR"],
            "ccf_modelled": [None],  # No modelled value
            "approach": ["advanced_irb"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # A-IRB without ccf_modelled should fall back to SA (MR = 50%)
        assert result["ccf"][0] == pytest.approx(0.50)
        assert result["ead_from_ccf"][0] == pytest.approx(50000.0)

    def test_risk_type_case_insensitive(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Risk type should be case insensitive."""
        exposures = pl.DataFrame({
            "exposure_reference": ["CASE1", "CASE2", "CASE3", "CASE4"],
            "drawn_amount": [0.0] * 4,
            "nominal_amount": [100000.0] * 4,
            "risk_type": ["fr", "Mr", "MLR", "LOW_RISK"],  # Mixed case
            "approach": ["standardised"] * 4,
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        expected = {
            "CASE1": 1.00,   # fr -> 100%
            "CASE2": 0.50,   # Mr -> 50%
            "CASE3": 0.20,   # MLR -> 20%
            "CASE4": 0.00,   # LOW_RISK -> 0%
        }

        for ref, expected_ccf in expected.items():
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ccf"][0] == pytest.approx(expected_ccf), f"CCF mismatch for {ref}"

    def test_sa_vs_firb_with_risk_type(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SA and F-IRB should use different CCFs for same risk_type."""
        exposures = pl.DataFrame({
            "exposure_reference": ["SA_MR", "FIRB_MR", "SA_MLR", "FIRB_MLR"],
            "drawn_amount": [0.0] * 4,
            "nominal_amount": [100000.0] * 4,
            "risk_type": ["MR", "MR", "MLR", "MLR"],
            "approach": ["standardised", "foundation_irb", "standardised", "foundation_irb"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # SA: MR=50%, MLR=20%
        # F-IRB: MR=75%, MLR=75%
        expected = {
            "SA_MR": 0.50,
            "FIRB_MR": 0.75,
            "SA_MLR": 0.20,
            "FIRB_MLR": 0.75,
        }

        for ref, expected_ccf in expected.items():
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ccf"][0] == pytest.approx(expected_ccf), f"CCF mismatch for {ref}"

    def test_firb_short_term_trade_lc_exception(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """F-IRB: Short-term trade LCs for goods movement retain 20% CCF per Art. 166(9)."""
        exposures = pl.DataFrame({
            "exposure_reference": ["FIRB_MLR_STANDARD", "FIRB_MLR_TRADE_LC"],
            "drawn_amount": [0.0, 0.0],
            "nominal_amount": [100000.0, 100000.0],
            "risk_type": ["MLR", "MLR"],  # Both MLR (20% SA, normally 75% F-IRB)
            "is_short_term_trade_lc": [False, True],  # Only second qualifies for exception
            "approach": ["foundation_irb", "foundation_irb"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # Standard MLR under F-IRB = 75%
        standard_row = result.filter(pl.col("exposure_reference") == "FIRB_MLR_STANDARD")
        assert standard_row["ccf"][0] == pytest.approx(0.75), "Standard MLR should be 75% under F-IRB"
        assert standard_row["ead_from_ccf"][0] == pytest.approx(75000.0)

        # Short-term trade LC under F-IRB = 20% (Art. 166(9) exception)
        trade_lc_row = result.filter(pl.col("exposure_reference") == "FIRB_MLR_TRADE_LC")
        assert trade_lc_row["ccf"][0] == pytest.approx(0.20), "Short-term trade LC should retain 20% under F-IRB"
        assert trade_lc_row["ead_from_ccf"][0] == pytest.approx(20000.0)

    def test_firb_short_term_trade_lc_only_applies_to_mlr(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """F-IRB: Art. 166(9) exception only applies to MLR risk type."""
        exposures = pl.DataFrame({
            "exposure_reference": ["FIRB_MR_TRADE_LC", "FIRB_FR_TRADE_LC", "FIRB_LR_TRADE_LC"],
            "drawn_amount": [0.0, 0.0, 0.0],
            "nominal_amount": [100000.0, 100000.0, 100000.0],
            "risk_type": ["MR", "FR", "LR"],  # Non-MLR risk types
            "is_short_term_trade_lc": [True, True, True],  # Flag set but shouldn't affect these
            "approach": ["foundation_irb", "foundation_irb", "foundation_irb"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # MR with trade_lc flag should still be 75% (exception only for MLR)
        mr_row = result.filter(pl.col("exposure_reference") == "FIRB_MR_TRADE_LC")
        assert mr_row["ccf"][0] == pytest.approx(0.75), "MR should still be 75% even with trade LC flag"

        # FR should always be 100%
        fr_row = result.filter(pl.col("exposure_reference") == "FIRB_FR_TRADE_LC")
        assert fr_row["ccf"][0] == pytest.approx(1.00), "FR should be 100%"

        # LR should always be 0%
        lr_row = result.filter(pl.col("exposure_reference") == "FIRB_LR_TRADE_LC")
        assert lr_row["ccf"][0] == pytest.approx(0.00), "LR should be 0%"

    def test_sa_ignores_short_term_trade_lc_flag(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SA approach should ignore the is_short_term_trade_lc flag."""
        exposures = pl.DataFrame({
            "exposure_reference": ["SA_MLR_STANDARD", "SA_MLR_TRADE_LC"],
            "drawn_amount": [0.0, 0.0],
            "nominal_amount": [100000.0, 100000.0],
            "risk_type": ["MLR", "MLR"],
            "is_short_term_trade_lc": [False, True],  # Should not affect SA
            "approach": ["standardised", "standardised"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # Both should be 20% under SA regardless of the flag
        for ref in ["SA_MLR_STANDARD", "SA_MLR_TRADE_LC"]:
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ccf"][0] == pytest.approx(0.20), f"SA MLR should be 20% for {ref}"
