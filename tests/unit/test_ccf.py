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

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.ccf import (
    CCFCalculator,
    create_ccf_calculator,
    drawn_for_ead,
    on_balance_ead,
    sa_ccf_expression,
)

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
    return pl.DataFrame(
        {
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
            "risk_type": ["MR", "FR", "MR", "MLR", "LR"],  # 50%, 100%, 50%, 20%, 0% CCF
            "approach": ["standardised"] * 5,
        }
    ).lazy()


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
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CONT001"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["MR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.50)
        assert result["ead_from_ccf"][0] == pytest.approx(50000.0)

    def test_full_risk_ccf_100_percent(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Full risk items (guarantees, acceptances) should get 100% CCF."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CONT001"],
                "drawn_amount": [0.0],
                "nominal_amount": [200000.0],
                "risk_type": ["FR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(1.00)
        assert result["ead_from_ccf"][0] == pytest.approx(200000.0)

    def test_low_risk_ccf_0_percent(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Low risk (unconditionally cancellable) should get 0% CCF."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CONT001"],
                "drawn_amount": [0.0],
                "nominal_amount": [300000.0],
                "risk_type": ["LR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.00)
        assert result["ead_from_ccf"][0] == pytest.approx(0.0)

    def test_medium_low_risk_ccf_20_percent(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Medium-low risk (documentary credits) should get 20% CCF."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CONT001"],
                "drawn_amount": [0.0],
                "nominal_amount": [150000.0],
                "risk_type": ["MLR"],
            }
        ).lazy()

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
            "CONT001": 0.50,  # MR (medium_risk)
            "CONT002": 1.00,  # FR (full_risk)
            "CONT003": 0.50,  # MR (medium_risk)
            "CONT004": 0.20,  # MLR (medium_low_risk)
            "CONT005": 0.00,  # LR (low_risk)
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
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_CONT001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1000000.0],
                "risk_type": ["MR"],  # Would be 50% for SA, 75% for F-IRB
                "approach": ["foundation_irb"],
            }
        ).lazy()

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
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_CANCEL001"],
                "drawn_amount": [0.0],
                "nominal_amount": [500000.0],
                "risk_type": ["LR"],  # Low risk = 0% CCF
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.00)
        assert result["ead_from_ccf"][0] == pytest.approx(0.0)

    def test_sa_vs_firb_ccf_difference(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SA and F-IRB should use different CCFs for same commitment type."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["SA_EXP", "FIRB_EXP"],
                "drawn_amount": [0.0, 0.0],
                "nominal_amount": [1000000.0, 1000000.0],
                "risk_type": ["MR", "MR"],  # Medium risk
                "approach": ["standardised", "foundation_irb"],
            }
        ).lazy()

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
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [500000.0],  # Drawn portion
                "nominal_amount": [200000.0],  # Undrawn portion
                "risk_type": ["MR"],  # 50% CCF
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # EAD = drawn + (nominal * CCF) = 500k + (200k * 0.5) = 600k
        assert result["ead_pre_crm"][0] == pytest.approx(600000.0)

    def test_fully_drawn_loan_no_ccf_impact(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Fully drawn loan with no undrawn should have EAD = drawn amount."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["LOAN001"],
                "drawn_amount": [1000000.0],
                "nominal_amount": [0.0],
                "risk_type": [None],  # No risk type for fully drawn
            }
        ).lazy()

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
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["RT_FR", "RT_MR", "RT_MLR", "RT_LR"],
                "drawn_amount": [0.0, 0.0, 0.0, 0.0],
                "nominal_amount": [100000.0, 100000.0, 100000.0, 100000.0],
                "risk_type": ["FR", "MR", "MLR", "LR"],
                "approach": ["standardised", "standardised", "standardised", "standardised"],
            }
        ).lazy()

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
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["RT_FULL", "RT_MED", "RT_MEDLOW", "RT_LOW"],
                "drawn_amount": [0.0, 0.0, 0.0, 0.0],
                "nominal_amount": [100000.0, 100000.0, 100000.0, 100000.0],
                "risk_type": ["full_risk", "medium_risk", "medium_low_risk", "low_risk"],
                "approach": ["standardised"] * 4,
            }
        ).lazy()

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
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_FR", "FIRB_MR", "FIRB_MLR", "FIRB_LR"],
                "drawn_amount": [0.0, 0.0, 0.0, 0.0],
                "nominal_amount": [100000.0, 100000.0, 100000.0, 100000.0],
                "risk_type": ["FR", "MR", "MLR", "LR"],
                "approach": ["foundation_irb"] * 4,
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # F-IRB: FR = 100%, MR = 75%, MLR = 75%, LR = 0%
        expected = {
            "FIRB_FR": (1.00, 100000.0),
            "FIRB_MR": (0.75, 75000.0),  # MR becomes 75% under F-IRB
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
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1000000.0],
                "risk_type": ["MR"],  # Would be 50% SA
                "ccf_modelled": [0.65],  # Bank's own estimate
                "approach": ["advanced_irb"],
            }
        ).lazy()

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
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_NULL"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["MR"],
                "ccf_modelled": [None],  # No modelled value
                "approach": ["advanced_irb"],
            }
        ).lazy()

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
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CASE1", "CASE2", "CASE3", "CASE4"],
                "drawn_amount": [0.0] * 4,
                "nominal_amount": [100000.0] * 4,
                "risk_type": ["fr", "Mr", "MLR", "LOW_RISK"],  # Mixed case
                "approach": ["standardised"] * 4,
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        expected = {
            "CASE1": 1.00,  # fr -> 100%
            "CASE2": 0.50,  # Mr -> 50%
            "CASE3": 0.20,  # MLR -> 20%
            "CASE4": 0.00,  # LOW_RISK -> 0%
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
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["SA_MR", "FIRB_MR", "SA_MLR", "FIRB_MLR"],
                "drawn_amount": [0.0] * 4,
                "nominal_amount": [100000.0] * 4,
                "risk_type": ["MR", "MR", "MLR", "MLR"],
                "approach": ["standardised", "foundation_irb", "standardised", "foundation_irb"],
            }
        ).lazy()

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
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_MLR_STANDARD", "FIRB_MLR_TRADE_LC"],
                "drawn_amount": [0.0, 0.0],
                "nominal_amount": [100000.0, 100000.0],
                "risk_type": ["MLR", "MLR"],  # Both MLR (20% SA, normally 75% F-IRB)
                "is_short_term_trade_lc": [False, True],  # Only second qualifies for exception
                "approach": ["foundation_irb", "foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # Standard MLR under F-IRB = 75%
        standard_row = result.filter(pl.col("exposure_reference") == "FIRB_MLR_STANDARD")
        assert standard_row["ccf"][0] == pytest.approx(0.75), (
            "Standard MLR should be 75% under F-IRB"
        )
        assert standard_row["ead_from_ccf"][0] == pytest.approx(75000.0)

        # Short-term trade LC under F-IRB = 20% (Art. 166(9) exception)
        trade_lc_row = result.filter(pl.col("exposure_reference") == "FIRB_MLR_TRADE_LC")
        assert trade_lc_row["ccf"][0] == pytest.approx(0.20), (
            "Short-term trade LC should retain 20% under F-IRB"
        )
        assert trade_lc_row["ead_from_ccf"][0] == pytest.approx(20000.0)

    def test_firb_short_term_trade_lc_only_applies_to_mlr(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """F-IRB: Art. 166(9) exception only applies to MLR risk type."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_MR_TRADE_LC", "FIRB_FR_TRADE_LC", "FIRB_LR_TRADE_LC"],
                "drawn_amount": [0.0, 0.0, 0.0],
                "nominal_amount": [100000.0, 100000.0, 100000.0],
                "risk_type": ["MR", "FR", "LR"],  # Non-MLR risk types
                "is_short_term_trade_lc": [True, True, True],  # Flag set but shouldn't affect these
                "approach": ["foundation_irb", "foundation_irb", "foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # MR with trade_lc flag should still be 75% (exception only for MLR)
        mr_row = result.filter(pl.col("exposure_reference") == "FIRB_MR_TRADE_LC")
        assert mr_row["ccf"][0] == pytest.approx(0.75), (
            "MR should still be 75% even with trade LC flag"
        )

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
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["SA_MLR_STANDARD", "SA_MLR_TRADE_LC"],
                "drawn_amount": [0.0, 0.0],
                "nominal_amount": [100000.0, 100000.0],
                "risk_type": ["MLR", "MLR"],
                "is_short_term_trade_lc": [False, True],  # Should not affect SA
                "approach": ["standardised", "standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # Both should be 20% under SA regardless of the flag
        for ref in ["SA_MLR_STANDARD", "SA_MLR_TRADE_LC"]:
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ccf"][0] == pytest.approx(0.20), f"SA MLR should be 20% for {ref}"


# =============================================================================
# Facility Undrawn CCF Tests
# =============================================================================


class TestFacilityUndrawnCCF:
    """Tests for CCF calculation on facility_undrawn exposures."""

    def test_facility_undrawn_sa_ccf_from_risk_type(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Facility undrawn exposures should use CCF from risk_type under SA."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": [
                    "FAC001_UNDRAWN",
                    "FAC002_UNDRAWN",
                    "FAC003_UNDRAWN",
                    "FAC004_UNDRAWN",
                ],
                "exposure_type": ["facility_undrawn"] * 4,
                "drawn_amount": [0.0] * 4,
                "undrawn_amount": [1000000.0] * 4,
                "nominal_amount": [1000000.0] * 4,
                "risk_type": ["MR", "MLR", "FR", "LR"],  # Different risk types
                "approach": ["standardised"] * 4,
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        expected = {
            "FAC001_UNDRAWN": (0.50, 500000.0),  # MR = 50%
            "FAC002_UNDRAWN": (0.20, 200000.0),  # MLR = 20%
            "FAC003_UNDRAWN": (1.00, 1000000.0),  # FR = 100%
            "FAC004_UNDRAWN": (0.00, 0.0),  # LR = 0%
        }

        for ref, (expected_ccf, expected_ead) in expected.items():
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ccf"][0] == pytest.approx(expected_ccf), f"CCF mismatch for {ref}"
            assert row["ead_from_ccf"][0] == pytest.approx(expected_ead), f"EAD mismatch for {ref}"

    def test_facility_undrawn_firb_ccf_75_percent(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Facility undrawn should get 75% CCF under F-IRB per Art. 166(8)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FAC_FIRB_UNDRAWN"],
                "exposure_type": ["facility_undrawn"],
                "drawn_amount": [0.0],
                "undrawn_amount": [500000.0],
                "nominal_amount": [500000.0],
                "risk_type": ["MR"],  # Would be 50% for SA
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # F-IRB: MR should use 75% CCF
        assert result["ccf"][0] == pytest.approx(0.75)
        assert result["ead_from_ccf"][0] == pytest.approx(375000.0)

    def test_facility_undrawn_airb_uses_modelled_ccf(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Facility undrawn should use ccf_modelled under A-IRB when provided."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FAC_AIRB_UNDRAWN"],
                "exposure_type": ["facility_undrawn"],
                "drawn_amount": [0.0],
                "undrawn_amount": [200000.0],
                "nominal_amount": [200000.0],
                "risk_type": ["MR"],
                "ccf_modelled": [0.80],  # Bank's modelled CCF
                "approach": ["advanced_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # A-IRB: should use the modelled CCF (80%)
        assert result["ccf"][0] == pytest.approx(0.80)
        assert result["ead_from_ccf"][0] == pytest.approx(160000.0)

    def test_facility_undrawn_uncommitted_lr_zero_ccf(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Uncommitted facilities with LR risk type should get 0% CCF."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FAC_UNCOMMITTED_UNDRAWN"],
                "exposure_type": ["facility_undrawn"],
                "drawn_amount": [0.0],
                "undrawn_amount": [1000000.0],
                "nominal_amount": [1000000.0],
                "risk_type": ["LR"],  # Low risk = unconditionally cancellable
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # LR = 0% CCF, so EAD from undrawn = 0
        assert result["ccf"][0] == pytest.approx(0.0)
        assert result["ead_from_ccf"][0] == pytest.approx(0.0)
        assert result["ead_pre_crm"][0] == pytest.approx(0.0)

    def test_facility_undrawn_trade_lc_firb_exception(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Facility undrawn trade LC should retain 20% under F-IRB per Art. 166(9)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FAC_TRADE_LC_UNDRAWN"],
                "exposure_type": ["facility_undrawn"],
                "drawn_amount": [0.0],
                "undrawn_amount": [500000.0],
                "nominal_amount": [500000.0],
                "risk_type": ["MLR"],
                "is_short_term_trade_lc": [True],  # Art. 166(9) exception
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # F-IRB with short-term trade LC should retain 20% CCF
        assert result["ccf"][0] == pytest.approx(0.20)
        assert result["ead_from_ccf"][0] == pytest.approx(100000.0)

    def test_facility_undrawn_ead_calculation(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Facility undrawn EAD should be calculated correctly from nominal_amount."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FAC_EAD_TEST"],
                "exposure_type": ["facility_undrawn"],
                "drawn_amount": [0.0],  # No drawn amount for undrawn exposure
                "undrawn_amount": [750000.0],
                "nominal_amount": [750000.0],
                "risk_type": ["MR"],  # 50% CCF for SA
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # EAD = drawn (0) + (nominal * CCF) = 0 + (750k * 0.5) = 375k
        assert result["ccf"][0] == pytest.approx(0.50)
        assert result["ead_from_ccf"][0] == pytest.approx(375000.0)
        assert result["ead_pre_crm"][0] == pytest.approx(375000.0)


# =============================================================================
# Accrued Interest in EAD Tests
# =============================================================================


class TestInterestInEAD:
    """Tests for accrued interest inclusion in EAD calculation."""

    def test_ead_includes_interest_for_drawn_loan(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """EAD should include accrued interest for drawn loans."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["LOAN_WITH_INTEREST"],
                "drawn_amount": [500.0],
                "interest": [10.0],  # Accrued interest
                "nominal_amount": [0.0],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # EAD = drawn (500) + interest (10) + CCF portion (0) = 510
        assert result["ead_pre_crm"][0] == pytest.approx(510.0)

    def test_ead_includes_interest_plus_ccf(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """EAD should be drawn + interest + CCF-adjusted undrawn."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["LOAN_WITH_UNDRAWN"],
                "drawn_amount": [500.0],
                "interest": [10.0],
                "nominal_amount": [500.0],  # Undrawn commitment
                "risk_type": ["MR"],  # 50% CCF
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # EAD = drawn (500) + interest (10) + (nominal * CCF) = 500 + 10 + 250 = 760
        assert result["ccf"][0] == pytest.approx(0.50)
        assert result["ead_from_ccf"][0] == pytest.approx(250.0)
        assert result["ead_pre_crm"][0] == pytest.approx(760.0)

    def test_null_interest_treated_as_zero(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Null interest should be treated as zero."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["LOAN_NULL_INTEREST"],
                "drawn_amount": [1000.0],
                "interest": [None],  # Null interest
                "nominal_amount": [0.0],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # EAD = drawn (1000) + interest (0) = 1000
        assert result["ead_pre_crm"][0] == pytest.approx(1000.0)

    def test_zero_interest_no_impact(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Zero interest should not change EAD."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["LOAN_ZERO_INTEREST"],
                "drawn_amount": [2000.0],
                "interest": [0.0],
                "nominal_amount": [0.0],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # EAD = drawn (2000) + interest (0) = 2000
        assert result["ead_pre_crm"][0] == pytest.approx(2000.0)

    def test_facility_undrawn_excludes_interest(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Facility undrawn (pure contingent) has no interest component."""
        # This tests that facility_undrawn exposures have interest = 0
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FAC_UNDRAWN_001"],
                "exposure_type": ["facility_undrawn"],
                "drawn_amount": [0.0],
                "interest": [0.0],  # Facility undrawn has no interest
                "undrawn_amount": [1000.0],
                "nominal_amount": [1000.0],
                "risk_type": ["MR"],  # 50% CCF
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # EAD = 0 + 0 + (1000 * 0.5) = 500
        assert result["ead_pre_crm"][0] == pytest.approx(500.0)


# =============================================================================
# SA CCF Expression Tests
# =============================================================================


class TestSACCFExpression:
    """Tests for the standalone sa_ccf_expression() function."""

    def test_fr_returns_100_percent(self) -> None:
        """Full risk should return 1.0 (100% CCF)."""
        df = pl.DataFrame({"risk_type": ["FR"]}).select(sa_ccf_expression().alias("ccf"))
        assert df["ccf"][0] == pytest.approx(1.0)

    def test_mr_returns_50_percent(self) -> None:
        """Medium risk should return 0.5 (50% CCF)."""
        df = pl.DataFrame({"risk_type": ["MR"]}).select(sa_ccf_expression().alias("ccf"))
        assert df["ccf"][0] == pytest.approx(0.5)

    def test_mlr_returns_20_percent(self) -> None:
        """Medium-low risk should return 0.2 (20% CCF)."""
        df = pl.DataFrame({"risk_type": ["MLR"]}).select(sa_ccf_expression().alias("ccf"))
        assert df["ccf"][0] == pytest.approx(0.2)

    def test_lr_returns_0_percent(self) -> None:
        """Low risk should return 0.0 (0% CCF)."""
        df = pl.DataFrame({"risk_type": ["LR"]}).select(sa_ccf_expression().alias("ccf"))
        assert df["ccf"][0] == pytest.approx(0.0)

    def test_full_value_names(self) -> None:
        """Full risk_type names should map correctly."""
        df = pl.DataFrame(
            {"risk_type": ["full_risk", "medium_risk", "medium_low_risk", "low_risk"]}
        ).select(sa_ccf_expression().alias("ccf"))
        assert df["ccf"].to_list() == pytest.approx([1.0, 0.5, 0.2, 0.0])

    def test_case_insensitive(self) -> None:
        """Risk type matching should be case insensitive."""
        df = pl.DataFrame({"risk_type": ["fr", "Fr", "FR", "FULL_RISK"]}).select(
            sa_ccf_expression().alias("ccf")
        )
        assert df["ccf"].to_list() == pytest.approx([1.0, 1.0, 1.0, 1.0])

    def test_null_defaults_to_mr(self) -> None:
        """Null risk_type should default to MR (50%)."""
        df = pl.DataFrame({"risk_type": [None]}).select(sa_ccf_expression().alias("ccf"))
        assert df["ccf"][0] == pytest.approx(0.5)

    def test_unknown_defaults_to_mr(self) -> None:
        """Unknown risk_type should default to MR (50%)."""
        df = pl.DataFrame({"risk_type": ["UNKNOWN"]}).select(sa_ccf_expression().alias("ccf"))
        assert df["ccf"][0] == pytest.approx(0.5)

    def test_custom_column_name(self) -> None:
        """Custom risk_type column name should work."""
        df = pl.DataFrame({"my_risk_type": ["FR", "LR"]}).select(
            sa_ccf_expression(risk_type_col="my_risk_type").alias("ccf")
        )
        assert df["ccf"].to_list() == pytest.approx([1.0, 0.0])

    def test_all_risk_types_batch(self) -> None:
        """Verify all SA CCFs in a single batch."""
        df = pl.DataFrame({"risk_type": ["FR", "MR", "MLR", "LR"]}).select(
            sa_ccf_expression().alias("ccf")
        )
        expected = [1.0, 0.5, 0.2, 0.0]
        assert df["ccf"].to_list() == pytest.approx(expected)


# =============================================================================
# On-Balance-Sheet EAD Helper Tests
# =============================================================================


class TestOnBalanceEAD:
    """Tests for on_balance_ead() helper expression."""

    def test_positive_drawn_plus_interest(self) -> None:
        """on_balance_ead() should return max(0, drawn) + interest."""
        df = pl.DataFrame(
            {
                "drawn_amount": [500.0],
                "interest": [10.0],
            }
        ).select(on_balance_ead().alias("ead"))
        assert df["ead"][0] == pytest.approx(510.0)

    def test_negative_drawn_plus_interest(self) -> None:
        """Negative drawn should be floored at 0; interest still included."""
        df = pl.DataFrame(
            {
                "drawn_amount": [-100000.0],
                "interest": [100.0],
            }
        ).select(on_balance_ead().alias("ead"))
        # max(0, -100k) + 100 = 100
        assert df["ead"][0] == pytest.approx(100.0)

    def test_null_interest_treated_as_zero(self) -> None:
        """Null interest should be treated as 0."""
        df = pl.DataFrame(
            {
                "drawn_amount": [1000.0],
                "interest": [None],
            }
        ).select(on_balance_ead().alias("ead"))
        assert df["ead"][0] == pytest.approx(1000.0)

    def test_zero_drawn_zero_interest(self) -> None:
        """Both zero should return 0."""
        df = pl.DataFrame(
            {
                "drawn_amount": [0.0],
                "interest": [0.0],
            }
        ).select(on_balance_ead().alias("ead"))
        assert df["ead"][0] == pytest.approx(0.0)

    def test_batch_values(self) -> None:
        """Multiple rows with mixed positive, negative, null values."""
        df = pl.DataFrame(
            {
                "drawn_amount": [-100.0, 0.0, 500.0, -50000.0],
                "interest": [100.0, 0.0, 20.0, None],
            }
        ).select(on_balance_ead().alias("ead"))
        assert df["ead"].to_list() == pytest.approx([100.0, 0.0, 520.0, 0.0])

    def test_negative_drawn_only_interest_contributes_to_ead(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Loan with negative drawn + interest: ead_pre_crm should equal interest amount."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["EXP_NEG_INT"],
                "drawn_amount": [-100000.0],
                "interest": [100.0],
                "nominal_amount": [0.0],
                "risk_type": ["MR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # EAD = max(0, -100k) + 100 + 0 = 100
        assert result["ead_pre_crm"][0] == pytest.approx(100.0)


# =============================================================================
# Negative Drawn Amount Tests
# =============================================================================


class TestNegativeDrawnAmount:
    """Tests for negative drawn amounts (credit balances) in EAD calculations.

    Loans such as current accounts with overdrafts can have negative drawn_amount
    when the counterparty has a credit balance. Without netting agreements, these
    should be treated as 0 for EAD purposes.
    """

    def test_drawn_for_ead_helper(self) -> None:
        """drawn_for_ead() should floor negative values at 0."""
        df = pl.DataFrame({"drawn_amount": [-100.0, 0.0, 50.0]}).select(
            drawn_for_ead().alias("floored")
        )
        assert df["floored"].to_list() == pytest.approx([0.0, 0.0, 50.0])

    def test_negative_drawn_ead_treated_as_zero(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Negative drawn amount should contribute 0 to ead_pre_crm, not reduce it."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [-100000.0],
                "interest": [5000.0],
                "nominal_amount": [200000.0],
                "risk_type": ["MR"],
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # CCF = 50% for MR → ead_from_ccf = 200k * 0.5 = 100k
        assert result["ead_from_ccf"][0] == pytest.approx(100000.0)
        # EAD = max(drawn, 0) + interest + ead_from_ccf = 0 + 5000 + 100000 = 105000
        assert result["ead_pre_crm"][0] == pytest.approx(105000.0)

    def test_negative_drawn_with_ccf_component(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Negative drawn with nominal should produce EAD = 0 + ccf*nominal."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [-50000.0],
                "interest": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["FR"],
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # CCF = 100% for FR → ead_from_ccf = 100k * 1.0 = 100k
        assert result["ead_from_ccf"][0] == pytest.approx(100000.0)
        # EAD = max(-50k, 0) + 0 + 100k = 100k (NOT -50k + 100k = 50k)
        assert result["ead_pre_crm"][0] == pytest.approx(100000.0)

    def test_negative_drawn_without_interest_column(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Legacy path (no interest column): negative drawn floored at 0."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [-75000.0],
                "nominal_amount": [100000.0],
                "risk_type": ["MR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # EAD = max(-75k, 0) + 50k = 50k (NOT -75k + 50k = -25k)
        assert result["ead_pre_crm"][0] == pytest.approx(50000.0)

    def test_positive_drawn_unchanged(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Positive drawn amounts should not be affected by the floor."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [500000.0],
                "interest": [20000.0],
                "nominal_amount": [300000.0],
                "risk_type": ["MR"],
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # EAD = 500k + 20k + 300k*0.5 = 670k
        assert result["ead_pre_crm"][0] == pytest.approx(670000.0)


# =============================================================================
# Provision-Adjusted CCF Tests (CRR Art. 111(2))
# =============================================================================


class TestProvisionAdjustedCCF:
    """Tests for CCF using provision-adjusted columns.

    When provision_on_drawn and nominal_after_provision are present,
    CCF should use nominal_after_provision for the off-balance-sheet
    component and subtract provision_on_drawn from the on-balance-sheet
    component.

    CRR Art. 111(2): SCRA deducted from nominal *before* CCF.
    """

    def test_obs_ead_uses_nominal_after_provision(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Off-balance EAD should use nominal_after_provision when available."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [0.0],
                "interest": [0.0],
                "nominal_amount": [500_000.0],
                "nominal_after_provision": [480_000.0],  # 20k provision
                "provision_on_drawn": [0.0],
                "risk_type": ["MR"],  # 50% CCF
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # ead_from_ccf = 480k * 0.5 = 240k (not 500k * 0.5 = 250k)
        assert result["ead_from_ccf"][0] == pytest.approx(240_000.0)
        assert result["ead_pre_crm"][0] == pytest.approx(240_000.0)

    def test_on_balance_ead_uses_provision_on_drawn(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """On-balance EAD should subtract provision_on_drawn from floored drawn."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [800_000.0],
                "interest": [10_000.0],
                "nominal_amount": [200_000.0],
                "nominal_after_provision": [200_000.0],  # No provision on nominal
                "provision_on_drawn": [50_000.0],
                "risk_type": ["MR"],
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # on_bal = max(0, 800k) - 50k + 10k = 760k
        # ead_from_ccf = 200k * 0.5 = 100k
        # ead_pre_crm = 760k + 100k = 860k
        assert result["ead_from_ccf"][0] == pytest.approx(100_000.0)
        assert result["ead_pre_crm"][0] == pytest.approx(860_000.0)

    def test_no_provision_columns_backward_compat(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Without provision columns, CCF behaves exactly as before."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [500_000.0],
                "interest": [10_000.0],
                "nominal_amount": [200_000.0],
                "risk_type": ["MR"],
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # ead_from_ccf = 200k * 0.5 = 100k
        # ead_pre_crm = 500k + 10k + 100k = 610k
        assert result["ead_from_ccf"][0] == pytest.approx(100_000.0)
        assert result["ead_pre_crm"][0] == pytest.approx(610_000.0)

    def test_mixed_provision_spill(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Provision split across drawn and nominal correctly adjusts both."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [30_000.0],
                "interest": [5_000.0],
                "nominal_amount": [200_000.0],
                "nominal_after_provision": [180_000.0],  # 20k provision on nominal
                "provision_on_drawn": [30_000.0],  # 30k absorbed by drawn
                "risk_type": ["MR"],
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # on_bal = max(0, 30k) - 30k + 5k = 5k (interest untouched)
        # ead_from_ccf = 180k * 0.5 = 90k
        # ead_pre_crm = 5k + 90k = 95k
        assert result["ead_from_ccf"][0] == pytest.approx(90_000.0)
        assert result["ead_pre_crm"][0] == pytest.approx(95_000.0)
