"""Unit tests for the CCF (Credit Conversion Factor) calculator.

Tests cover:
- SA CCF calculation (0%, 20%, 50%, 100%) per CRR Art. 111
- F-IRB CCF calculation (75%) per CRR Art. 166(8)
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
