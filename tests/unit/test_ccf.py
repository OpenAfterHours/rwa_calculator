"""Unit tests for the CCF (Credit Conversion Factor) calculator.

Tests cover:
- SA CCF calculation (0%, 20%, 50%, 100%) per CRR Art. 111
- F-IRB CCF calculation (75%) per CRR Art. 166(8)
- F-IRB exception for short-term trade LCs (20%) per CRR Art. 166(9)
- EAD calculation from undrawn commitments
- Approach-specific CCF selection
- A-IRB revolving restriction under Basel 3.1 (Art. 166D(1)(a))
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
    interest_for_ead,
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
# Basel 3.1 F-IRB CCF Tests (PRA PS1/26 Art. 166C)
# =============================================================================


class TestFIRBCCFBasel31:
    """Tests for F-IRB CCF under Basel 3.1: Art. 166C mandates SA CCFs.

    Under Basel 3.1, F-IRB off-balance-sheet items use SA CCFs (Table A1)
    instead of the CRR 75% flat rate:
    - FR: 100%, MR: 50%, OC: 40%, MLR: 20%, LR(UCC): 10%
    """

    @pytest.fixture
    def b31_config(self) -> CalculationConfig:
        """Return a Basel 3.1 configuration."""
        return CalculationConfig.basel_3_1(reporting_date=date(2028, 1, 1))

    def test_firb_mr_uses_sa_50_percent(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """B31 F-IRB MR should use SA 50% (not CRR 75%)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_MR_B31"],
                "drawn_amount": [0.0],
                "nominal_amount": [1000000.0],
                "risk_type": ["MR"],
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        assert result["ccf"][0] == pytest.approx(0.50)
        assert result["ead_from_ccf"][0] == pytest.approx(500000.0)

    def test_firb_mlr_uses_sa_20_percent(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """B31 F-IRB MLR should use SA 20% (not CRR 75%)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_MLR_B31"],
                "drawn_amount": [0.0],
                "nominal_amount": [500000.0],
                "risk_type": ["MLR"],
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        assert result["ccf"][0] == pytest.approx(0.20)
        assert result["ead_from_ccf"][0] == pytest.approx(100000.0)

    def test_firb_lr_uses_sa_10_percent(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """B31 F-IRB LR(UCC) should use SA 10% (not CRR 0%)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_LR_B31"],
                "drawn_amount": [0.0],
                "nominal_amount": [1000000.0],
                "risk_type": ["LR"],
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        assert result["ccf"][0] == pytest.approx(0.10)
        assert result["ead_from_ccf"][0] == pytest.approx(100000.0)

    def test_firb_fr_still_100_percent(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """B31 F-IRB FR should still be 100% (same as SA)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_FR_B31"],
                "drawn_amount": [0.0],
                "nominal_amount": [1000000.0],
                "risk_type": ["FR"],
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        assert result["ccf"][0] == pytest.approx(1.00)

    def test_firb_all_risk_types_b31(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """B31 F-IRB should use SA CCFs for all risk types (Art. 166C)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": [
                    "B31_FR",
                    "B31_FRC",
                    "B31_MR",
                    "B31_MLR",
                    "B31_LR",
                ],
                "drawn_amount": [0.0, 0.0, 0.0, 0.0, 0.0],
                "nominal_amount": [100000.0, 100000.0, 100000.0, 100000.0, 100000.0],
                "risk_type": ["FR", "FRC", "MR", "MLR", "LR"],
                "approach": ["foundation_irb"] * 5,
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        expected = {
            "B31_FR": 1.00,
            "B31_FRC": 1.00,
            "B31_MR": 0.50,
            "B31_MLR": 0.20,
            "B31_LR": 0.10,
        }

        for ref, expected_ccf in expected.items():
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ccf"][0] == pytest.approx(expected_ccf), f"CCF mismatch for {ref}"

    def test_crr_firb_still_75_percent_regression(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR F-IRB should still use 75% for MR/MLR (regression test)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRR_MR"],
                "drawn_amount": [0.0],
                "nominal_amount": [1000000.0],
                "risk_type": ["MR"],
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.75)


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
            {
                "risk_type": [
                    "full_risk",
                    "full_risk_commitment",
                    "medium_risk",
                    "other_commit",
                    "medium_low_risk",
                    "low_risk",
                ]
            }
        ).select(sa_ccf_expression().alias("ccf"))
        assert df["ccf"].to_list() == pytest.approx([1.0, 1.0, 0.5, 0.5, 0.2, 0.0])

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
        """Verify all SA CCFs in a single batch (CRR — OC maps to 50%)."""
        df = pl.DataFrame({"risk_type": ["FR", "FRC", "MR", "OC", "MLR", "LR"]}).select(
            sa_ccf_expression().alias("ccf")
        )
        expected = [1.0, 1.0, 0.5, 0.5, 0.2, 0.0]
        assert df["ccf"].to_list() == pytest.approx(expected)


# =============================================================================
# Basel 3.1 "Other Commitments" 40% CCF Tests (PRA Art. 111 Table A1 Row 5)
# =============================================================================


class TestOtherCommitCCF:
    """Tests for the 'other commitments' CCF category.

    PRA PS1/26 Art. 111 Table A1 Row 5 introduces a new 40% CCF for
    'all other commitments not in other categories'. Under CRR, this
    category did not exist — commitments were classified by maturity
    into MR (50% SA / 75% F-IRB) or MLR (20% SA / 75% F-IRB).

    References:
        PRA PS1/26 Art. 111 Table A1
    """

    @pytest.fixture
    def b31_config(self) -> CalculationConfig:
        """Return a Basel 3.1 configuration."""
        return CalculationConfig.basel_3_1(reporting_date=date(2028, 1, 1))

    # --- SA expression tests ---

    def test_oc_code_returns_40_percent_b31(self) -> None:
        """OC short code should return 40% under Basel 3.1."""
        df = pl.DataFrame({"risk_type": ["OC"]}).select(
            sa_ccf_expression(is_basel_3_1=True).alias("ccf")
        )
        assert df["ccf"][0] == pytest.approx(0.4)

    def test_other_commit_full_name_returns_40_percent_b31(self) -> None:
        """other_commit full name should return 40% under Basel 3.1."""
        df = pl.DataFrame({"risk_type": ["other_commit"]}).select(
            sa_ccf_expression(is_basel_3_1=True).alias("ccf")
        )
        assert df["ccf"][0] == pytest.approx(0.4)

    def test_oc_case_insensitive_b31(self) -> None:
        """OC matching should be case insensitive."""
        df = pl.DataFrame({"risk_type": ["oc", "Oc", "OC", "OTHER_COMMIT"]}).select(
            sa_ccf_expression(is_basel_3_1=True).alias("ccf")
        )
        assert df["ccf"].to_list() == pytest.approx([0.4, 0.4, 0.4, 0.4])

    def test_oc_returns_50_percent_crr(self) -> None:
        """OC should return 50% conservative default under CRR (>1yr MR equivalent)."""
        df = pl.DataFrame({"risk_type": ["OC"]}).select(
            sa_ccf_expression(is_basel_3_1=False).alias("ccf")
        )
        assert df["ccf"][0] == pytest.approx(0.5)

    def test_all_risk_types_b31_batch(self) -> None:
        """Verify all SA CCFs including OC and FRC in a single Basel 3.1 batch."""
        df = pl.DataFrame({"risk_type": ["FR", "FRC", "MR", "OC", "MLR", "LR"]}).select(
            sa_ccf_expression(is_basel_3_1=True).alias("ccf")
        )
        expected = [1.0, 1.0, 0.5, 0.4, 0.2, 0.1]
        assert df["ccf"].to_list() == pytest.approx(expected)

    def test_all_risk_types_crr_batch(self) -> None:
        """Verify all SA CCFs including OC and FRC in a CRR batch."""
        df = pl.DataFrame({"risk_type": ["FR", "FRC", "MR", "OC", "MLR", "LR"]}).select(
            sa_ccf_expression(is_basel_3_1=False).alias("ccf")
        )
        expected = [1.0, 1.0, 0.5, 0.5, 0.2, 0.0]
        assert df["ccf"].to_list() == pytest.approx(expected)

    # --- Pipeline-level SA tests ---

    def test_sa_pipeline_oc_40_percent_b31(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """SA pipeline should apply 40% CCF for OC risk_type under B31."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["OC_001"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["OC"],
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        assert result["ccf"][0] == pytest.approx(0.4)
        assert result["ead_from_ccf"][0] == pytest.approx(40000.0)

    def test_sa_pipeline_oc_50_percent_crr_no_maturity(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SA pipeline: OC without maturity_date gets conservative 50% under CRR."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["OC_CRR"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["OC"],
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.5)
        assert result["ead_from_ccf"][0] == pytest.approx(50000.0)

    # --- F-IRB pipeline tests ---

    def test_firb_oc_uses_sa_40_percent_b31(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """B31 F-IRB OC should use SA 40% (Art. 166C: F-IRB uses SA CCFs)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_OC_B31"],
                "drawn_amount": [0.0],
                "nominal_amount": [200000.0],
                "risk_type": ["OC"],
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        assert result["ccf"][0] == pytest.approx(0.4)
        assert result["ead_from_ccf"][0] == pytest.approx(80000.0)

    def test_firb_oc_75_percent_crr(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR F-IRB OC should get 75% (maps to MR/MLR, both 75% under F-IRB)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_OC_CRR"],
                "drawn_amount": [0.0],
                "nominal_amount": [200000.0],
                "risk_type": ["OC"],
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.75)

    # --- CRR maturity-dependent OC tests ---

    def test_sa_pipeline_oc_20_percent_crr_short_maturity(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR SA: OC with maturity <=1yr from reporting_date -> 20% CCF."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["OC_SHORT"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["OC"],
                "approach": ["standardised"],
                "maturity_date": [date(2025, 6, 30)],  # ~6 months from 2024-12-31
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.2)
        assert result["ead_from_ccf"][0] == pytest.approx(20000.0)

    def test_sa_pipeline_oc_50_percent_crr_long_maturity(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR SA: OC with maturity >1yr from reporting_date -> 50% CCF."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["OC_LONG"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["OC"],
                "approach": ["standardised"],
                "maturity_date": [date(2026, 6, 30)],  # ~18 months from 2024-12-31
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.5)
        assert result["ead_from_ccf"][0] == pytest.approx(50000.0)

    def test_sa_pipeline_oc_boundary_exactly_1yr(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR SA: OC with maturity exactly 365 days from reporting_date -> 20% (<=1yr)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["OC_BOUNDARY"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["OC"],
                "approach": ["standardised"],
                "maturity_date": [date(2025, 12, 31)],  # exactly 365 days from 2024-12-31
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.2)

    def test_sa_pipeline_oc_null_maturity_conservative_50(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR SA: OC with null maturity_date -> conservative 50%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["OC_NULL_MAT"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["OC"],
                "approach": ["standardised"],
                "maturity_date": [None],
            },
            schema_overrides={"maturity_date": pl.Date},
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.5)

    def test_firb_oc_75_percent_crr_independent_of_maturity(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR F-IRB: OC -> 75% regardless of maturity (MR=MLR=75% under F-IRB)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_OC_SHORT", "FIRB_OC_LONG"],
                "drawn_amount": [0.0, 0.0],
                "nominal_amount": [200000.0, 200000.0],
                "risk_type": ["OC", "OC"],
                "approach": ["foundation_irb", "foundation_irb"],
                "maturity_date": [date(2025, 6, 30), date(2026, 6, 30)],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.75)
        assert result["ccf"][1] == pytest.approx(0.75)

    def test_b31_oc_40_percent_ignores_maturity(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """B31 SA: OC -> 40% regardless of maturity (maturity distinction removed)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["OC_B31_SHORT", "OC_B31_LONG"],
                "drawn_amount": [0.0, 0.0],
                "nominal_amount": [100000.0, 100000.0],
                "risk_type": ["OC", "OC"],
                "approach": ["standardised", "standardised"],
                "maturity_date": [date(2028, 6, 30), date(2030, 1, 1)],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        assert result["ccf"][0] == pytest.approx(0.4)
        assert result["ccf"][1] == pytest.approx(0.4)

    # --- A-IRB pipeline tests ---

    def test_airb_oc_revolving_uses_modelled_with_floor_b31(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """B31 A-IRB revolving OC: modelled CCF with 50% SA floor (CRE32.27).

        SA CCF for OC = 40%, so floor = 50% × 40% = 20%.
        Modelled 30% > 20% floor, so use modelled 30%.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_OC_REV"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["OC"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.30],
                "is_revolving": [True],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        assert result["ccf"][0] == pytest.approx(0.30)

    def test_airb_oc_revolving_floor_binds_b31(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """B31 A-IRB revolving OC: floor binds when modelled < 50% of SA.

        SA CCF for OC = 40%, so floor = 50% × 40% = 20%.
        Modelled 15% < 20% floor, so floor applies → 20%.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_OC_FLOOR"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["OC"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.15],
                "is_revolving": [True],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        assert result["ccf"][0] == pytest.approx(0.20)

    def test_airb_oc_nonrevolving_uses_sa_b31(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """B31 A-IRB non-revolving OC: must use SA 40% (Art. 166D(1)(a))."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_OC_NONREV"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["OC"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.10],
                "is_revolving": [False],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        assert result["ccf"][0] == pytest.approx(0.40)


# =============================================================================
# Full Risk Commitment (FRC) — Table A1 Row 2 — 100% CCF (P1.65)
# =============================================================================


class TestFullRiskCommitmentCCF:
    """Tests for the 'full risk commitment' 100% CCF category (Table A1 Row 2).

    PRA PS1/26 Art. 111 Table A1 Row 2 defines 100% CCF for commitments with
    certain drawdown: factoring, repos, forward deposits, forward purchases,
    partly-paid shares. These are structurally distinct from Row 1 (guarantees,
    credit substitutes) but share the same 100% CCF.

    Why this matters: without a separate risk_type code, institutions may
    misclassify these as OC (40%) or MR (50%), understating capital by 50-60pp.

    References:
        PRA PS1/26 Art. 111 Table A1 Row 2
        CRR Annex I para 2
        PRA PS1/26 Art. 166D(1)(a) — A-IRB carve-out for 100% SA CCF items
    """

    @pytest.fixture
    def b31_config(self) -> CalculationConfig:
        """Return a Basel 3.1 configuration."""
        return CalculationConfig.basel_3_1(reporting_date=date(2028, 1, 1))

    @pytest.fixture
    def crr_config(self) -> CalculationConfig:
        """Return a CRR configuration."""
        return CalculationConfig.crr(reporting_date=date(2024, 12, 31))

    @pytest.fixture
    def ccf_calculator(self) -> CCFCalculator:
        return CCFCalculator()

    # --- SA expression tests ---

    def test_frc_short_code_returns_100_percent(self) -> None:
        """FRC short code should return 100% CCF under both CRR and B31."""
        for is_b31 in [True, False]:
            df = pl.DataFrame({"risk_type": ["FRC"]}).select(
                sa_ccf_expression(is_basel_3_1=is_b31).alias("ccf")
            )
            assert df["ccf"][0] == pytest.approx(1.0), f"FRC failed for is_b31={is_b31}"

    def test_frc_full_name_returns_100_percent(self) -> None:
        """full_risk_commitment full name should return 100% CCF."""
        df = pl.DataFrame({"risk_type": ["full_risk_commitment"]}).select(
            sa_ccf_expression().alias("ccf")
        )
        assert df["ccf"][0] == pytest.approx(1.0)

    def test_frc_case_insensitive(self) -> None:
        """FRC matching should be case insensitive."""
        df = pl.DataFrame({"risk_type": ["frc", "Frc", "FRC", "FULL_RISK_COMMITMENT"]}).select(
            sa_ccf_expression().alias("ccf")
        )
        assert df["ccf"].to_list() == pytest.approx([1.0, 1.0, 1.0, 1.0])

    def test_frc_same_as_fr(self) -> None:
        """FRC and FR should produce identical CCF values (both 100%)."""
        df = pl.DataFrame({"risk_type": ["FR", "FRC"]}).select(sa_ccf_expression().alias("ccf"))
        assert df["ccf"][0] == df["ccf"][1]

    def test_frc_b31_sa_same_as_crr(self) -> None:
        """FRC should be 100% under both CRR and Basel 3.1 SA."""
        crr = pl.DataFrame({"risk_type": ["FRC"]}).select(
            sa_ccf_expression(is_basel_3_1=False).alias("ccf")
        )
        b31 = pl.DataFrame({"risk_type": ["FRC"]}).select(
            sa_ccf_expression(is_basel_3_1=True).alias("ccf")
        )
        assert crr["ccf"][0] == pytest.approx(1.0)
        assert b31["ccf"][0] == pytest.approx(1.0)

    # --- SA pipeline tests ---

    def test_sa_pipeline_frc_100_percent_b31(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """SA pipeline should apply 100% CCF for FRC under B31."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FRC_001"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["FRC"],
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        assert result["ccf"][0] == pytest.approx(1.0)
        assert result["ead_from_ccf"][0] == pytest.approx(100000.0)

    def test_sa_pipeline_frc_100_percent_crr(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SA pipeline should apply 100% CCF for FRC under CRR."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FRC_CRR"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["FRC"],
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(1.0)
        assert result["ead_from_ccf"][0] == pytest.approx(100000.0)

    # --- F-IRB pipeline tests ---

    def test_firb_frc_100_percent_b31(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """B31 F-IRB should use SA 100% CCF for FRC (Art. 166C)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_FRC"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["FRC"],
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        assert result["ccf"][0] == pytest.approx(1.0)

    def test_firb_frc_100_percent_crr(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR F-IRB should apply 100% CCF for FRC (Annex I para 2)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_FRC_CRR"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["FRC"],
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(1.0)

    # --- A-IRB pipeline tests ---

    def test_airb_frc_revolving_uses_sa_100_b31(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """B31 A-IRB revolving FRC: must use SA 100% — own-estimate excluded.

        Art. 166D(1)(a) carve-out: revolving facilities with 100% SA CCF
        (Table A1 Row 2) cannot use own-estimate CCFs.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_FRC_REV"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["FRC"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.50],
                "is_revolving": [True],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        # SA CCF = 1.0, so is_eligible_for_own_ccf = False → uses SA 100%
        assert result["ccf"][0] == pytest.approx(1.0)

    def test_airb_frc_nonrevolving_uses_sa_100_b31(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """B31 A-IRB non-revolving FRC: must use SA 100% (Art. 166D(1)(a))."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_FRC_NONREV"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["FRC"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.60],
                "is_revolving": [False],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        assert result["ccf"][0] == pytest.approx(1.0)

    def test_airb_frc_crr_uses_modelled(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR A-IRB FRC: can use own-estimate CCF (no Art. 166D restriction)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_FRC_CRR"],
                "drawn_amount": [0.0],
                "nominal_amount": [100000.0],
                "risk_type": ["FRC"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.80],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        assert result["ccf"][0] == pytest.approx(0.80)

    # --- RWA impact test ---

    def test_frc_vs_oc_capital_impact(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """FRC (100%) produces 2.5x higher EAD than OC (40%) — capital impact.

        This test demonstrates why correct classification matters: a repo
        misclassified as OC would understate capital by 60pp of notional.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["REPO_CORRECT", "REPO_MISCLASSIFIED"],
                "drawn_amount": [0.0, 0.0],
                "nominal_amount": [1000000.0, 1000000.0],
                "risk_type": ["FRC", "OC"],
                "approach": ["standardised", "standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        frc_ead = result.filter(pl.col("exposure_reference") == "REPO_CORRECT")["ead_from_ccf"][0]
        oc_ead = result.filter(pl.col("exposure_reference") == "REPO_MISCLASSIFIED")[
            "ead_from_ccf"
        ][0]

        assert frc_ead == pytest.approx(1000000.0)  # 100% × 1M
        assert oc_ead == pytest.approx(400000.0)  # 40% × 1M
        assert frc_ead / oc_ead == pytest.approx(2.5)  # 2.5x capital difference

    # --- Validation tests ---

    def test_frc_in_valid_risk_type_codes(self) -> None:
        """FRC should be in the validation sets."""
        from rwa_calc.contracts.validation import (
            RISK_TYPE_CODE_TO_VALUE,
            VALID_RISK_TYPE_CODES,
            VALID_RISK_TYPES,
        )

        assert "frc" in VALID_RISK_TYPE_CODES
        assert "full_risk_commitment" in VALID_RISK_TYPES
        assert RISK_TYPE_CODE_TO_VALUE["frc"] == "full_risk_commitment"

    def test_frc_in_valid_risk_types_input(self) -> None:
        """FRC should be in the input validation set."""
        from rwa_calc.data.schemas import VALID_RISK_TYPES_INPUT

        assert "FRC" in VALID_RISK_TYPES_INPUT

    def test_risk_type_enum_has_frc(self) -> None:
        """RiskType enum should include FRC member."""
        from rwa_calc.domain.enums import RiskType

        assert hasattr(RiskType, "FRC")
        assert RiskType.FRC.value == "full_risk_commitment"

    # --- Mixed batch with all 6 risk types ---

    def test_mixed_batch_all_six_risk_types(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Pipeline with all 6 risk types produces correct CCFs and EADs."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": [
                    "EXP_FR",
                    "EXP_FRC",
                    "EXP_MR",
                    "EXP_OC",
                    "EXP_MLR",
                    "EXP_LR",
                ],
                "drawn_amount": [0.0] * 6,
                "nominal_amount": [100000.0] * 6,
                "risk_type": ["FR", "FRC", "MR", "OC", "MLR", "LR"],
                "approach": ["standardised"] * 6,
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        expected_ccf = {
            "EXP_FR": 1.0,
            "EXP_FRC": 1.0,
            "EXP_MR": 0.5,
            "EXP_OC": 0.4,
            "EXP_MLR": 0.2,
            "EXP_LR": 0.1,
        }
        for ref, exp_ccf in expected_ccf.items():
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ccf"][0] == pytest.approx(exp_ccf), f"CCF mismatch for {ref}"
            assert row["ead_from_ccf"][0] == pytest.approx(100000.0 * exp_ccf), (
                f"EAD mismatch for {ref}"
            )


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
# Negative Interest Amount Tests
# =============================================================================


class TestNegativeInterestAmount:
    """Tests for negative interest amounts in EAD calculations.

    Negative accrued interest should not reduce EAD without a netting agreement.
    Like negative drawn, interest is conservatively floored at 0.
    """

    def test_interest_for_ead_floors_negative_and_null(self) -> None:
        """interest_for_ead() should floor negative values at 0 and treat null as 0."""
        df = pl.DataFrame({"interest": [-200.0, 0.0, 50.0, None]}).select(
            interest_for_ead().alias("floored")
        )
        assert df["floored"].to_list() == pytest.approx([0.0, 0.0, 50.0, 0.0])

    def test_on_balance_ead_negative_interest_floored(self) -> None:
        """Negative interest should be floored at 0 in on_balance_ead()."""
        df = pl.DataFrame(
            {
                "drawn_amount": [500.0],
                "interest": [-200.0],
            }
        ).select(on_balance_ead().alias("ead"))
        # max(0, 500) + max(0, -200) = 500 + 0 = 500
        assert df["ead"][0] == pytest.approx(500.0)

    def test_on_balance_ead_both_negative(self) -> None:
        """Both negative drawn and interest should produce 0 EAD."""
        df = pl.DataFrame(
            {
                "drawn_amount": [-100.0],
                "interest": [-50.0],
            }
        ).select(on_balance_ead().alias("ead"))
        assert df["ead"][0] == pytest.approx(0.0)

    def test_on_balance_ead_null_interest_unchanged(self) -> None:
        """Null interest should still produce drawn-only EAD (regression)."""
        df = pl.DataFrame(
            {
                "drawn_amount": [100.0],
                "interest": [None],
            }
        ).select(on_balance_ead().alias("ead"))
        assert df["ead"][0] == pytest.approx(100.0)

    def test_negative_interest_ead_through_ccf_pipeline(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Full apply_ccf(): negative interest should not reduce ead_pre_crm."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["EXP001"],
                "drawn_amount": [1000.0],
                "interest": [-200.0],
                "nominal_amount": [0.0],
                "risk_type": ["MR"],
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # EAD = max(0, 1000) + max(0, -200) + 0 = 1000 (NOT 800)
        assert result["ead_pre_crm"][0] == pytest.approx(1000.0)


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


# =============================================================================
# Basel 3.1 A-IRB CCF Revolving Restriction Tests (PRA PS1/26 Art. 166D)
# =============================================================================


class TestAIRBCCFBasel31Revolving:
    """Tests for A-IRB CCF revolving restriction under Basel 3.1.

    PRA PS1/26 Art. 166D(1)(a) restricts own-estimate CCFs to revolving
    facilities only. Non-revolving A-IRB must use SA CCFs from Table A1.
    Additionally, revolving facilities with 100% SA CCF (Table A1 Row 2,
    e.g. factoring, repos) cannot use own-estimate CCFs.

    All own-estimate CCFs are floored at 50% of SA CCF (CRE32.27).
    """

    @pytest.fixture
    def b31_config(self) -> CalculationConfig:
        """Return a Basel 3.1 configuration."""
        return CalculationConfig.basel_3_1(reporting_date=date(2028, 1, 1))

    def test_nonrevolving_airb_uses_sa_ccf_not_modelled(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Non-revolving A-IRB under B31 must use SA CCF, ignoring modelled value.

        Art. 166D(1)(a): own-estimate CCFs only for revolving facilities.
        A non-revolving MR facility with modelled CCF 0.30 should get SA 50%.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_NR_001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1_000_000.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.30],
                "is_revolving": [False],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        # Non-revolving: SA MR = 50%, modelled 30% is ignored
        assert result["ccf"][0] == pytest.approx(0.50)
        assert result["ead_from_ccf"][0] == pytest.approx(500_000.0)

    def test_revolving_airb_uses_modelled_ccf_with_floor(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Revolving A-IRB under B31 uses modelled CCF with 50% SA floor.

        Art. 166D + CRE32.27: revolving MR facility with modelled 0.40 gets
        max(0.40, 0.50 * 0.50) = max(0.40, 0.25) = 0.40.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_REV_001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1_000_000.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.40],
                "is_revolving": [True],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        # Revolving, SA MR=50%: max(0.40, 0.50*0.50) = max(0.40, 0.25) = 0.40
        assert result["ccf"][0] == pytest.approx(0.40)

    def test_revolving_airb_floor_binds_when_modelled_too_low(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Revolving A-IRB modelled CCF below 50% SA floor is floored up.

        CRE32.27: revolving MR facility with modelled 0.10 gets
        max(0.10, 0.50 * 0.50) = max(0.10, 0.25) = 0.25.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_REV_FLOOR"],
                "drawn_amount": [0.0],
                "nominal_amount": [1_000_000.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.10],
                "is_revolving": [True],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        # Revolving, SA MR=50%: max(0.10, 0.25) = 0.25 (floor binds)
        assert result["ccf"][0] == pytest.approx(0.25)

    def test_revolving_fr_airb_cannot_use_own_estimate(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Revolving A-IRB with FR (100% SA CCF) cannot use own-estimate.

        Art. 166D(1)(a) carve-out: revolving facilities that attract 100%
        SA CCF (Table A1 Row 2, e.g. factoring, repos) must use SA 100%.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_REV_FR"],
                "drawn_amount": [0.0],
                "nominal_amount": [500_000.0],
                "risk_type": ["FR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.60],
                "is_revolving": [True],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        # Revolving BUT SA CCF = 100% (FR): must use SA, modelled 60% ignored
        assert result["ccf"][0] == pytest.approx(1.0)

    def test_null_is_revolving_defaults_to_false(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Null is_revolving defaults to False: SA CCF used (conservative).

        Missing revolving flag should be treated as non-revolving,
        preventing modelled CCF from being used.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_NULL_REV"],
                "drawn_amount": [0.0],
                "nominal_amount": [1_000_000.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.30],
                "is_revolving": [None],
            },
            schema_overrides={"is_revolving": pl.Boolean},
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        # Null is_revolving → False → SA MR = 50%
        assert result["ccf"][0] == pytest.approx(0.50)

    def test_crr_airb_ignores_revolving_flag(
        self,
        ccf_calculator: CCFCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Under CRR, A-IRB always uses modelled CCF regardless of is_revolving.

        The revolving restriction is Basel 3.1 only (Art. 166D).
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_CRR_NR"],
                "drawn_amount": [0.0],
                "nominal_amount": [1_000_000.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.30],
                "is_revolving": [False],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()

        # CRR: non-revolving still uses modelled CCF (no Art. 166D restriction)
        assert result["ccf"][0] == pytest.approx(0.30)

    def test_nonrevolving_airb_mlr_uses_sa_20_percent(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Non-revolving A-IRB MLR under B31 must use SA 20%.

        Even with a modelled CCF of 0.05, non-revolving gets SA MLR = 20%.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_NR_MLR"],
                "drawn_amount": [0.0],
                "nominal_amount": [500_000.0],
                "risk_type": ["MLR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.05],
                "is_revolving": [False],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        # Non-revolving: SA MLR = 20%, modelled 5% is ignored
        assert result["ccf"][0] == pytest.approx(0.20)

    def test_nonrevolving_airb_lr_uses_sa_10_percent(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Non-revolving A-IRB LR under B31 must use SA 10%.

        Under Basel 3.1, LR (unconditionally cancellable) = 10% for SA.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_NR_LR"],
                "drawn_amount": [0.0],
                "nominal_amount": [300_000.0],
                "risk_type": ["LR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.01],
                "is_revolving": [False],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        # Non-revolving: SA LR = 10% (B31), modelled 1% is ignored
        assert result["ccf"][0] == pytest.approx(0.10)

    def test_revolving_airb_lr_uses_modelled_with_floor(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Revolving A-IRB LR under B31 uses modelled with 50% SA floor.

        SA LR = 10% under B31. Floor = 50% * 10% = 5%.
        Modelled 0.08 > 0.05, so modelled is used.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_REV_LR"],
                "drawn_amount": [0.0],
                "nominal_amount": [300_000.0],
                "risk_type": ["LR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.08],
                "is_revolving": [True],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        # Revolving, SA LR=10%: max(0.08, 0.10*0.50) = max(0.08, 0.05) = 0.08
        assert result["ccf"][0] == pytest.approx(0.08)

    def test_missing_is_revolving_column_defaults_to_false(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """When is_revolving column is entirely absent, defaults to non-revolving.

        _ensure_columns adds is_revolving=False when missing, so A-IRB
        B31 exposures without the column use SA CCFs.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_NO_COL"],
                "drawn_amount": [0.0],
                "nominal_amount": [1_000_000.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.30],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        # No is_revolving column → default False → SA MR = 50%
        assert result["ccf"][0] == pytest.approx(0.50)

    def test_mixed_revolving_nonrevolving_batch(
        self,
        ccf_calculator: CCFCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Mixed batch: revolving uses modelled, non-revolving uses SA.

        Tests that the per-row branching works correctly in a multi-row frame.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["REV_001", "NR_001", "REV_FR", "NR_LR"],
                "drawn_amount": [0.0, 0.0, 0.0, 0.0],
                "nominal_amount": [1_000_000.0, 1_000_000.0, 500_000.0, 300_000.0],
                "risk_type": ["MR", "MR", "FR", "LR"],
                "approach": ["advanced_irb"] * 4,
                "ccf_modelled": [0.40, 0.30, 0.60, 0.01],
                "is_revolving": [True, False, True, False],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        expected = {
            "REV_001": 0.40,  # Revolving MR: max(0.40, 0.25) = 0.40
            "NR_001": 0.50,  # Non-revolving MR: SA = 0.50
            "REV_FR": 1.00,  # Revolving FR: SA = 1.00 (100% carve-out)
            "NR_LR": 0.10,  # Non-revolving LR: SA = 0.10
        }
        for ref, exp_ccf in expected.items():
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ccf"][0] == pytest.approx(exp_ccf), f"CCF mismatch for {ref}"


# =============================================================================
# Art. 166D(5) EAD Floor Tests (b) and (c) — Basel 3.1 A-IRB
# =============================================================================


class TestAIRBEADFloorBasel31:
    """Tests for Art. 166D(5) EAD floors (b) and (c) under Basel 3.1.

    Floor (b): When ead_modelled is provided (Art. 166D(3) single-EAD approach),
        EAD >= on-BS EAD + 50% x F-IRB off-BS EAD
        Under B31, F-IRB uses SA CCFs (Art. 166C).
    Floor (c): EAD >= on-balance-sheet EAD (ignoring Art. 166D).

    Floor (a) (CCF >= 50% x SA CCF) is tested in TestAIRBCCFBasel31Revolving.
    """

    @pytest.fixture
    def b31_config(self) -> CalculationConfig:
        return CalculationConfig.basel_3_1(reporting_date=date(2028, 1, 1))

    @pytest.fixture
    def ccf_calculator(self) -> CCFCalculator:
        return CCFCalculator()

    # ----- Floor (b): facility-level EAD floor -----

    def test_floor_b_binds_modelled_ead_below_floor(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Floor (b) raises EAD when ead_modelled is below the floor.

        Scenario: drawn=100k, nominal=200k, risk_type=MR (SA CCF=50%)
        Floor (b) = 100k + 0.5 * (200k * 0.50) = 100k + 50k = 150k
        ead_modelled = 120k < 150k → floor binds, ead_pre_crm = 150k
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_FLOOR_B_001"],
                "drawn_amount": [100_000.0],
                "nominal_amount": [200_000.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.30],
                "is_revolving": [True],
                "ead_modelled": [120_000.0],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        # Floor (b) = 100k + 0.5 * 200k * 0.50 = 150k
        assert result["ead_pre_crm"][0] == pytest.approx(150_000.0)

    def test_floor_b_does_not_bind_modelled_above_floor(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Floor (b) does not bind when ead_modelled exceeds the floor.

        Scenario: drawn=100k, nominal=200k, risk_type=MR (SA CCF=50%)
        Floor (b) = 100k + 0.5 * (200k * 0.50) = 150k
        ead_modelled = 250k > 150k → ead_modelled passes through
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_FLOOR_B_002"],
                "drawn_amount": [100_000.0],
                "nominal_amount": [200_000.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.30],
                "is_revolving": [True],
                "ead_modelled": [250_000.0],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ead_pre_crm"][0] == pytest.approx(250_000.0)

    def test_floor_b_with_lr_risk_type(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Floor (b) uses SA CCF for the risk type — LR = 10% under B31.

        Scenario: drawn=50k, nominal=500k, risk_type=LR (SA CCF=10%)
        Floor (b) = 50k + 0.5 * (500k * 0.10) = 50k + 25k = 75k
        ead_modelled = 60k < 75k → floor binds
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_FLOOR_B_LR"],
                "drawn_amount": [50_000.0],
                "nominal_amount": [500_000.0],
                "risk_type": ["LR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.05],
                "is_revolving": [True],
                "ead_modelled": [60_000.0],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ead_pre_crm"][0] == pytest.approx(75_000.0)

    def test_floor_b_with_interest(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Floor (b) includes accrued interest in on-balance-sheet component.

        Scenario: drawn=100k, interest=5k, nominal=200k, MR (SA CCF=50%)
        on_bal = 100k + 5k = 105k
        Floor (b) = 105k + 0.5 * (200k * 0.50) = 105k + 50k = 155k
        ead_modelled = 130k < 155k → floor binds
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_FLOOR_B_INT"],
                "drawn_amount": [100_000.0],
                "interest": [5_000.0],
                "nominal_amount": [200_000.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.30],
                "is_revolving": [True],
                "ead_modelled": [130_000.0],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ead_pre_crm"][0] == pytest.approx(155_000.0)

    # ----- Floor (c): fully-drawn EAD floor -----

    def test_floor_c_binds_modelled_below_on_balance(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Floor (c) raises EAD when modelled EAD is below on-balance amount.

        Scenario: drawn=200k, nominal=0 (fully drawn), risk_type=MR
        on_bal = 200k, Floor (b) = 200k + 0 = 200k, Floor (c) = 200k
        ead_modelled = 150k < 200k → floor (c) binds
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_FLOOR_C_001"],
                "drawn_amount": [200_000.0],
                "nominal_amount": [0.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.30],
                "is_revolving": [True],
                "ead_modelled": [150_000.0],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ead_pre_crm"][0] == pytest.approx(200_000.0)

    def test_floor_c_with_interest_included(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Floor (c) includes interest in the on-balance-sheet amount.

        Scenario: drawn=200k, interest=10k, nominal=0 (fully drawn)
        on_bal = 210k
        ead_modelled = 180k < 210k → floor (c) binds, ead_pre_crm = 210k
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_FLOOR_C_INT"],
                "drawn_amount": [200_000.0],
                "interest": [10_000.0],
                "nominal_amount": [0.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.30],
                "is_revolving": [True],
                "ead_modelled": [180_000.0],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ead_pre_crm"][0] == pytest.approx(210_000.0)

    # ----- No ead_modelled: standard CCF approach unchanged -----

    def test_null_ead_modelled_uses_standard_ccf_path(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """When ead_modelled is null, standard CCF approach is used.

        Scenario: drawn=100k, nominal=200k, MR, revolving, ccf_modelled=0.40
        Standard: ead_pre_crm = 100k + 200k * max(0.40, 0.25) = 100k + 80k = 180k
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_STD_001"],
                "drawn_amount": [100_000.0],
                "nominal_amount": [200_000.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.40],
                "is_revolving": [True],
                "ead_modelled": [None],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ead_pre_crm"][0] == pytest.approx(180_000.0)

    def test_missing_ead_modelled_column_backward_compatible(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """When ead_modelled column is entirely absent, standard CCF path works.

        This ensures backward compatibility with existing data.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_NO_COL"],
                "drawn_amount": [100_000.0],
                "nominal_amount": [200_000.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.40],
                "is_revolving": [True],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        # Standard: 100k + 200k * max(0.40, 0.25) = 180k
        assert result["ead_pre_crm"][0] == pytest.approx(180_000.0)

    # ----- CRR: no Art. 166D floors -----

    def test_crr_no_ead_floors_applied(self, ccf_calculator: CCFCalculator) -> None:
        """Under CRR, ead_modelled is ignored — standard CCF approach only.

        Art. 166D floors are Basel 3.1 only. CRR A-IRB uses modelled CCF directly.
        """
        crr_config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_CRR_001"],
                "drawn_amount": [100_000.0],
                "nominal_amount": [200_000.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.10],
                "is_revolving": [True],
                "ead_modelled": [50_000.0],  # Would be below floor under B31
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()
        # CRR: ead_pre_crm = 100k + 200k * 0.10 = 120k (modelled CCF, no floor)
        assert result["ead_pre_crm"][0] == pytest.approx(120_000.0)

    # ----- SA/FIRB exposures: floors don't apply -----

    def test_sa_exposure_no_ead_floor(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """SA exposures are unaffected by A-IRB EAD floors."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["SA_001"],
                "drawn_amount": [100_000.0],
                "nominal_amount": [200_000.0],
                "risk_type": ["MR"],
                "approach": ["standardised"],
                "ccf_modelled": [None],
                "is_revolving": [False],
                "ead_modelled": [50_000.0],  # Should be ignored for SA
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        # SA: ead_pre_crm = 100k + 200k * 0.50 = 200k
        assert result["ead_pre_crm"][0] == pytest.approx(200_000.0)

    # ----- Combined floor (b) and (c) interaction -----

    def test_floor_b_dominates_when_undrawn_exists(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Floor (b) > floor (c) when there is an off-balance component.

        Scenario: drawn=100k, nominal=400k, MR (SA CCF=50%)
        Floor (b) = 100k + 0.5 * (400k * 0.50) = 100k + 100k = 200k
        Floor (c) = 100k
        ead_modelled = 80k → floor (b) binds at 200k
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_COMBINED_001"],
                "drawn_amount": [100_000.0],
                "nominal_amount": [400_000.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.30],
                "is_revolving": [True],
                "ead_modelled": [80_000.0],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ead_pre_crm"][0] == pytest.approx(200_000.0)

    # ----- Mixed batch test -----

    def test_mixed_batch_modelled_and_standard(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Mixed batch: some with ead_modelled, some without, different approaches."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": [
                    "AIRB_MOD_LOW",  # ead_modelled below floor → floor binds
                    "AIRB_MOD_HIGH",  # ead_modelled above floor → passes through
                    "AIRB_STD",  # no ead_modelled → standard CCF path
                    "SA_IGNORE",  # SA → ead_modelled ignored
                ],
                "drawn_amount": [100_000.0, 100_000.0, 100_000.0, 100_000.0],
                "nominal_amount": [200_000.0, 200_000.0, 200_000.0, 200_000.0],
                "risk_type": ["MR", "MR", "MR", "MR"],
                "approach": ["advanced_irb", "advanced_irb", "advanced_irb", "standardised"],
                "ccf_modelled": [0.30, 0.30, 0.40, None],
                "is_revolving": [True, True, True, False],
                "ead_modelled": [120_000.0, 300_000.0, None, 50_000.0],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()

        # Floor (b) = 100k + 0.5 * 200k * 0.50 = 150k for all MR A-IRB
        expected = {
            "AIRB_MOD_LOW": 150_000.0,  # floor (b) binds: 120k → 150k
            "AIRB_MOD_HIGH": 300_000.0,  # ead_modelled passes: 300k > 150k
            "AIRB_STD": 180_000.0,  # standard: 100k + 200k*0.40 = 180k
            "SA_IGNORE": 200_000.0,  # SA: 100k + 200k*0.50 = 200k
        }
        for ref, exp_ead in expected.items():
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ead_pre_crm"][0] == pytest.approx(exp_ead), (
                f"EAD mismatch for {ref}: got {row['ead_pre_crm'][0]}, expected {exp_ead}"
            )

    # ----- EAD floor with provision-adjusted amounts -----

    def test_floor_b_uses_provision_adjusted_nominal(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Floor (b) uses nominal_after_provision, not raw nominal.

        Scenario: drawn=100k, nominal=200k, provision_on_nominal=20k
        nominal_after_provision = 180k
        Floor (b) = 100k + 0.5 * (180k * 0.50) = 100k + 45k = 145k
        ead_modelled = 110k < 145k → floor binds
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_PROV_001"],
                "drawn_amount": [100_000.0],
                "nominal_amount": [200_000.0],
                "nominal_after_provision": [180_000.0],
                "provision_on_drawn": [0.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.30],
                "is_revolving": [True],
                "ead_modelled": [110_000.0],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ead_pre_crm"][0] == pytest.approx(145_000.0)

    def test_standard_ccf_ead_not_below_on_balance(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Under standard CCF path, ead_pre_crm is floored at on-balance amount.

        Floor (c) belt-and-suspenders: even without ead_modelled, A-IRB B31
        ead_pre_crm >= on_bal. Normally redundant (CCF >= 0 ensures this),
        but tests the guard.

        Scenario: drawn=100k, nominal=200k, MR, revolving
        Standard CCF approach: ccf = max(0.30, 0.25) = 0.30
        ead_pre_crm = 100k + 200k * 0.30 = 160k > 100k (on_bal) — doesn't bind
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_STD_FLOOR_C"],
                "drawn_amount": [100_000.0],
                "nominal_amount": [200_000.0],
                "risk_type": ["MR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.30],
                "is_revolving": [True],
                "ead_modelled": [None],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        # Standard: 100k + 200k * 0.30 = 160k > 100k, so floor doesn't bind
        assert result["ead_pre_crm"][0] == pytest.approx(160_000.0)


# =============================================================================
# Art. 111(1)(c): Commitment-to-issue lower-of rule
# =============================================================================


class TestCommitmentToIssueLowerOf:
    """Test Art. 111(1)(c) lower-of CCF rule for commitments to issue OBS items.

    When a commitment is to issue another off-balance-sheet item listed in Table A1,
    the CCF is the LOWER of the CCF for the underlying OBS item and the commitment type.

    Example: A commitment (OC=40%) to issue a guarantee (FR=100%) → min(40%,100%) = 40%.
    """

    @pytest.fixture
    def ccf_calculator(self) -> CCFCalculator:
        return CCFCalculator()

    @pytest.fixture
    def crr_config(self) -> CalculationConfig:
        return CalculationConfig.crr(reporting_date=date(2024, 12, 31))

    @pytest.fixture
    def b31_config(self) -> CalculationConfig:
        return CalculationConfig.basel_3_1(reporting_date=date(2028, 1, 1))

    # --- SA tests ---

    def test_sa_commitment_oc_to_issue_guarantee_fr_uses_oc_ccf(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """OC commitment (40%) to issue FR guarantee (100%) → min(40%,100%) = 40%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["COMMIT_OC_FR"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["OC"],
                "underlying_risk_type": ["FR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ccf"][0] == pytest.approx(0.40)

    def test_sa_commitment_fr_to_issue_lr_uses_lr_ccf(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """FR commitment (100%) to issue LR item (10%) → min(100%,10%) = 10%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["COMMIT_FR_LR"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["FR"],
                "underlying_risk_type": ["LR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ccf"][0] == pytest.approx(0.10)

    def test_sa_commitment_mr_to_issue_mlr_uses_mlr_ccf(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """MR commitment (50%) to issue MLR item (20%) → min(50%,20%) = 20%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["COMMIT_MR_MLR"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["MR"],
                "underlying_risk_type": ["MLR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ccf"][0] == pytest.approx(0.20)

    def test_sa_commitment_mlr_to_issue_mr_uses_mlr_ccf(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """MLR commitment (20%) to issue MR item (50%) → min(20%,50%) = 20%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["COMMIT_MLR_MR"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["MLR"],
                "underlying_risk_type": ["MR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ccf"][0] == pytest.approx(0.20)

    def test_sa_same_risk_type_no_change(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """MR commitment (50%) to issue MR item (50%) → min(50%,50%) = 50%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["COMMIT_MR_MR"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["MR"],
                "underlying_risk_type": ["MR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ccf"][0] == pytest.approx(0.50)

    def test_sa_null_underlying_no_cap(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Null underlying_risk_type means no commitment-to-issue cap."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["NO_UNDERLYING"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["FR"],
                "underlying_risk_type": [None],
            },
            schema_overrides={"underlying_risk_type": pl.String},
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ccf"][0] == pytest.approx(1.0)

    def test_sa_missing_underlying_column_no_cap(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Missing underlying_risk_type column means no cap (backward compatible)."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["NO_COL"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["FR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ccf"][0] == pytest.approx(1.0)

    def test_sa_ead_correctness_with_lower_of(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """EAD reflects the capped CCF: 100k * 40% = 40k."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["EAD_CHECK"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["OC"],
                "underlying_risk_type": ["FR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ead_from_ccf"][0] == pytest.approx(40_000.0)
        assert result["ead_pre_crm"][0] == pytest.approx(40_000.0)

    # --- CRR SA tests ---

    def test_crr_sa_commitment_mr_to_issue_lr_uses_lr_ccf(
        self, ccf_calculator: CCFCalculator, crr_config: CalculationConfig
    ) -> None:
        """CRR: MR commitment (50%) to issue LR item (0%) → min(50%,0%) = 0%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRR_MR_LR"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["MR"],
                "underlying_risk_type": ["LR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()
        assert result["ccf"][0] == pytest.approx(0.0)

    def test_crr_sa_commitment_oc_to_issue_fr_uses_oc_ccf(
        self, ccf_calculator: CCFCalculator, crr_config: CalculationConfig
    ) -> None:
        """CRR: OC commitment (50%) to issue FR guarantee (100%) → min(50%,100%) = 50%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["CRR_OC_FR"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["OC"],
                "underlying_risk_type": ["FR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()
        assert result["ccf"][0] == pytest.approx(0.5)

    # --- F-IRB tests ---

    def test_firb_b31_commitment_mr_to_issue_lr_uses_lr(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """B31 F-IRB: MR (50%) to issue LR (10%) → min(50%,10%) = 10%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_B31_MR_LR"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["MR"],
                "underlying_risk_type": ["LR"],
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ccf"][0] == pytest.approx(0.10)

    def test_firb_crr_commitment_mr_to_issue_lr_uses_lr(
        self, ccf_calculator: CCFCalculator, crr_config: CalculationConfig
    ) -> None:
        """CRR F-IRB: MR (75%) to issue LR (0%) → min(75%,0%) = 0%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_CRR_MR_LR"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["MR"],
                "underlying_risk_type": ["LR"],
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config).collect()
        assert result["ccf"][0] == pytest.approx(0.0)

    # --- A-IRB tests ---

    def test_airb_b31_lower_of_caps_sa_floor(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """B31 A-IRB: revolving MR (SA=50%) to issue LR (SA=10%).

        Lower-of caps SA CCF to 10%. A-IRB with 50% SA floor → floor = 5%.
        Modelled CCF (30%) > floor (5%), so CCF = 30%.
        But capped SA CCF = 10%, and modelled 30% > 10%.
        The A-IRB path uses max(modelled, sa*0.5) = max(30%, 5%) = 30%.
        But the SA CCF is now 10%, and since modelled > 10%, it stays 30%.
        Wait — the A-IRB eligible path: max(ccf_modelled, _sa_ccf * 0.5) where
        _sa_ccf is already capped to 10%. So max(0.30, 0.05) = 0.30.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_B31_MR_LR"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["MR"],
                "underlying_risk_type": ["LR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.30],
                "is_revolving": [True],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        # SA CCF capped to 10% (underlying LR), but modelled 30% > floor (5%)
        assert result["ccf"][0] == pytest.approx(0.30)

    def test_airb_b31_non_revolving_uses_capped_sa(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """B31 A-IRB non-revolving: MR (SA=50%) to issue LR (SA=10%).

        Non-revolving → must use SA CCF. Capped SA = 10%.
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_B31_NONREV"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["MR"],
                "underlying_risk_type": ["LR"],
                "approach": ["advanced_irb"],
                "ccf_modelled": [0.30],
                "is_revolving": [False],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        # Non-revolving A-IRB uses SA CCF, which is capped to 10%
        assert result["ccf"][0] == pytest.approx(0.10)

    # --- Audit trail ---

    def test_audit_trail_includes_underlying_when_present(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Audit trail includes underlying_risk_type when column present in original."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AUDIT"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["OC"],
                "underlying_risk_type": ["FR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        audit = result["ccf_calculation"][0]
        assert "underlying=FR" in audit

    def test_audit_trail_omits_underlying_when_not_in_original(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Audit trail omits underlying_risk_type when column not in original input."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AUDIT_NO_UND"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["FR"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        audit = result["ccf_calculation"][0]
        assert "underlying=" not in audit

    # --- Mixed batch ---

    def test_mixed_batch_some_with_underlying_some_without(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Mixed batch: some exposures have underlying, some don't."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["WITH_UND", "NO_UND", "SAME_TYPE"],
                "drawn_amount": [0.0, 0.0, 0.0],
                "nominal_amount": [100_000.0, 100_000.0, 100_000.0],
                "risk_type": ["OC", "FR", "MR"],
                "underlying_risk_type": ["FR", None, "MR"],
            },
            schema_overrides={"underlying_risk_type": pl.String},
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        expected = {"WITH_UND": 0.40, "NO_UND": 1.0, "SAME_TYPE": 0.50}
        for ref, expected_ccf in expected.items():
            row = result.filter(pl.col("exposure_reference") == ref)
            assert row["ccf"][0] == pytest.approx(expected_ccf), f"CCF mismatch for {ref}"

    # --- Full name support ---

    def test_underlying_accepts_full_names(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """underlying_risk_type accepts full enum names like 'full_risk'."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FULL_NAME"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["other_commit"],
                "underlying_risk_type": ["full_risk"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ccf"][0] == pytest.approx(0.40)

    # --- FRC underlying ---

    def test_frc_underlying_100_percent(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """OC (40%) to issue FRC (100%) → min(40%,100%) = 40%."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["OC_FRC"],
                "drawn_amount": [0.0],
                "nominal_amount": [100_000.0],
                "risk_type": ["OC"],
                "underlying_risk_type": ["FRC"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        assert result["ccf"][0] == pytest.approx(0.40)

    # --- Capital impact demonstration ---

    def test_capital_impact_without_lower_of_would_overstate(
        self, ccf_calculator: CCFCalculator, b31_config: CalculationConfig
    ) -> None:
        """Demonstrates that without lower-of, a commitment to issue a low-risk item
        would get the commitment's own (higher) CCF, overstating exposure.

        FR commitment (100%) to issue LR item (10%):
        - Without lower-of: CCF=100%, EAD=100k → 100k exposure
        - With lower-of: CCF=10%, EAD=10k → 10k exposure
        - Capital saving: 90k exposure reduction
        """
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["WITH_RULE", "WITHOUT_RULE"],
                "drawn_amount": [0.0, 0.0],
                "nominal_amount": [100_000.0, 100_000.0],
                "risk_type": ["FR", "FR"],
                "underlying_risk_type": ["LR", None],
            },
            schema_overrides={"underlying_risk_type": pl.String},
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, b31_config).collect()
        with_rule = result.filter(pl.col("exposure_reference") == "WITH_RULE")
        without_rule = result.filter(pl.col("exposure_reference") == "WITHOUT_RULE")
        assert with_rule["ead_from_ccf"][0] == pytest.approx(10_000.0)
        assert without_rule["ead_from_ccf"][0] == pytest.approx(100_000.0)
