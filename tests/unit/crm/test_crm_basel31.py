"""Unit tests for Basel 3.1 CRM (Credit Risk Mitigation) changes.

Tests cover the key differences between CRR and Basel 3.1 for CRM:
1. Revised supervisory haircut tables (CRE22.52-53):
   - 5 maturity bands instead of CRR's 3
   - Higher haircuts for long-dated corporate bonds
   - Higher equity haircuts (25%/35% vs 15%/25%)
   - Sovereign CQS 2-3 10y+ increased to 12%
2. Revised F-IRB supervisory LGD (CRE32.9-12):
   - Senior unsecured: 40% (CRR: 45%)
   - Receivables/RE: 20% (CRR: 35%)
   - Other physical: 25% (CRR: 40%)
3. Framework-conditional logic in CRM processor

Why these tests matter:
    Basel 3.1 introduces material changes to CRM that reduce capital benefits
    from collateral (higher haircuts) while lowering regulatory LGD for F-IRB
    (better treatment of collateralised exposures). Getting these wrong
    produces materially incorrect RWA — in either direction.

References:
    CRR Art. 224: CRR supervisory haircuts
    CRE22.52-53: Basel 3.1 supervisory haircuts
    CRR Art. 161: CRR F-IRB supervisory LGD
    CRE32.9-12: Basel 3.1 F-IRB supervisory LGD
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.data.tables.crr_haircuts import (
    BASEL31_COLLATERAL_HAIRCUTS,
    COLLATERAL_HAIRCUTS,
    get_haircut_table,
    get_maturity_band,
    lookup_collateral_haircut,
)
from rwa_calc.data.tables.crr_firb_lgd import (
    BASEL31_FIRB_SUPERVISORY_LGD,
    FIRB_SUPERVISORY_LGD,
    lookup_firb_lgd,
)
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.crm.haircuts import HaircutCalculator
from rwa_calc.engine.crm.processor import CRMProcessor


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR configuration."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.firb_only(),
    )


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Basel 3.1 configuration."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2028, 1, 1),
        irb_permissions=IRBPermissions.firb_only(),
    )


@pytest.fixture
def crr_processor() -> CRMProcessor:
    """CRM processor for CRR framework."""
    return CRMProcessor(is_basel_3_1=False)


@pytest.fixture
def b31_processor() -> CRMProcessor:
    """CRM processor for Basel 3.1 framework."""
    return CRMProcessor(is_basel_3_1=True)


# =============================================================================
# Test: Basel 3.1 maturity bands (CRE22.52-53)
# =============================================================================


class TestBasel31MaturityBands:
    """Basel 3.1 uses 5 maturity bands instead of CRR's 3."""

    def test_crr_maturity_bands_are_3(self) -> None:
        """CRR uses 0-1y, 1-5y, 5y+ — 3 bands."""
        assert get_maturity_band(0.5, is_basel_3_1=False) == "0_1y"
        assert get_maturity_band(3.0, is_basel_3_1=False) == "1_5y"
        assert get_maturity_band(7.0, is_basel_3_1=False) == "5y_plus"

    def test_b31_maturity_bands_are_5(self) -> None:
        """Basel 3.1 uses 0-1y, 1-3y, 3-5y, 5-10y, 10y+ — 5 bands."""
        assert get_maturity_band(0.5, is_basel_3_1=True) == "0_1y"
        assert get_maturity_band(2.0, is_basel_3_1=True) == "1_3y"
        assert get_maturity_band(4.0, is_basel_3_1=True) == "3_5y"
        assert get_maturity_band(7.0, is_basel_3_1=True) == "5_10y"
        assert get_maturity_band(15.0, is_basel_3_1=True) == "10y_plus"

    def test_b31_maturity_band_boundaries(self) -> None:
        """Boundary values classified correctly for Basel 3.1."""
        assert get_maturity_band(1.0, is_basel_3_1=True) == "0_1y"
        assert get_maturity_band(3.0, is_basel_3_1=True) == "1_3y"
        assert get_maturity_band(5.0, is_basel_3_1=True) == "3_5y"
        assert get_maturity_band(10.0, is_basel_3_1=True) == "5_10y"
        assert get_maturity_band(10.01, is_basel_3_1=True) == "10y_plus"


# =============================================================================
# Test: Basel 3.1 haircut tables (CRE22.52-53)
# =============================================================================


class TestBasel31HaircutTable:
    """Verify the Basel 3.1 haircut table has correct structure and values."""

    def test_b31_haircut_table_has_5_maturity_bands(self) -> None:
        """Basel 3.1 table should have 5 maturity band variants for bonds."""
        df = get_haircut_table(is_basel_3_1=True)
        bond_bands = df.filter(pl.col("collateral_type") == "govt_bond")["maturity_band"].to_list()
        unique_bands = set(bond_bands)
        assert unique_bands == {"0_1y", "1_3y", "3_5y", "5_10y", "10y_plus"}

    def test_crr_haircut_table_has_3_maturity_bands(self) -> None:
        """CRR table should have 3 maturity band variants for bonds."""
        df = get_haircut_table(is_basel_3_1=False)
        bond_bands = df.filter(pl.col("collateral_type") == "govt_bond")["maturity_band"].to_list()
        unique_bands = set(bond_bands)
        assert unique_bands == {"0_1y", "1_5y", "5y_plus"}


class TestBasel31EquityHaircuts:
    """Equity haircuts increase under Basel 3.1."""

    def test_crr_equity_main_index_15pct(self) -> None:
        assert COLLATERAL_HAIRCUTS["equity_main_index"] == Decimal("0.15")

    def test_crr_equity_other_25pct(self) -> None:
        assert COLLATERAL_HAIRCUTS["equity_other"] == Decimal("0.25")

    def test_b31_equity_main_index_25pct(self) -> None:
        assert BASEL31_COLLATERAL_HAIRCUTS["equity_main_index"] == Decimal("0.25")

    def test_b31_equity_other_35pct(self) -> None:
        assert BASEL31_COLLATERAL_HAIRCUTS["equity_other"] == Decimal("0.35")

    def test_lookup_equity_haircut_crr(self) -> None:
        assert lookup_collateral_haircut("equity", is_main_index=True, is_basel_3_1=False) == Decimal("0.15")
        assert lookup_collateral_haircut("equity", is_main_index=False, is_basel_3_1=False) == Decimal("0.25")

    def test_lookup_equity_haircut_b31(self) -> None:
        assert lookup_collateral_haircut("equity", is_main_index=True, is_basel_3_1=True) == Decimal("0.25")
        assert lookup_collateral_haircut("equity", is_main_index=False, is_basel_3_1=True) == Decimal("0.35")


class TestBasel31BondHaircuts:
    """Bond haircuts differ for long-dated maturities under Basel 3.1."""

    def test_govt_bond_cqs1_short_same_both_frameworks(self) -> None:
        """Government bond CQS 1, 0-1y: 0.5% under both."""
        crr = lookup_collateral_haircut("govt_bond", cqs=1, residual_maturity_years=0.5, is_basel_3_1=False)
        b31 = lookup_collateral_haircut("govt_bond", cqs=1, residual_maturity_years=0.5, is_basel_3_1=True)
        assert crr == Decimal("0.005")
        assert b31 == Decimal("0.005")

    def test_sovereign_cqs2_3_10y_plus_increases(self) -> None:
        """Sovereign CQS 2-3, 10y+: CRR 6% → Basel 3.1 12%."""
        crr = lookup_collateral_haircut("govt_bond", cqs=2, residual_maturity_years=15.0, is_basel_3_1=False)
        b31 = lookup_collateral_haircut("govt_bond", cqs=2, residual_maturity_years=15.0, is_basel_3_1=True)
        assert crr == Decimal("0.06")
        assert b31 == Decimal("0.12")

    def test_corp_bond_cqs1_2_long_dated_increases(self) -> None:
        """Corporate CQS 1-2 long-dated: 3-5y 6%, 5-10y 10%, 10y+ 12%."""
        # 3-5y: CRR uses 1-5y band (4%), B31 uses 3-5y band (6%)
        crr = lookup_collateral_haircut("corp_bond", cqs=1, residual_maturity_years=4.0, is_basel_3_1=False)
        b31 = lookup_collateral_haircut("corp_bond", cqs=1, residual_maturity_years=4.0, is_basel_3_1=True)
        assert crr == Decimal("0.04")
        assert b31 == Decimal("0.06")

        # 5-10y: CRR uses 5y+ band (6%), B31 uses 5-10y band (10%)
        crr = lookup_collateral_haircut("corp_bond", cqs=2, residual_maturity_years=7.0, is_basel_3_1=False)
        b31 = lookup_collateral_haircut("corp_bond", cqs=2, residual_maturity_years=7.0, is_basel_3_1=True)
        assert crr == Decimal("0.06")
        assert b31 == Decimal("0.10")

        # 10y+: CRR uses 5y+ band (6%), B31 uses 10y+ band (12%)
        crr = lookup_collateral_haircut("corp_bond", cqs=1, residual_maturity_years=12.0, is_basel_3_1=False)
        b31 = lookup_collateral_haircut("corp_bond", cqs=1, residual_maturity_years=12.0, is_basel_3_1=True)
        assert crr == Decimal("0.06")
        assert b31 == Decimal("0.12")

    def test_corp_bond_cqs3_long_dated_increases(self) -> None:
        """Corporate CQS 3 long-dated: 5-10y and 10y+ both 15%."""
        # 5-10y: CRR uses 5y+ band (8%), B31 uses 5-10y band (15%)
        crr = lookup_collateral_haircut("corp_bond", cqs=3, residual_maturity_years=7.0, is_basel_3_1=False)
        b31 = lookup_collateral_haircut("corp_bond", cqs=3, residual_maturity_years=7.0, is_basel_3_1=True)
        assert crr == Decimal("0.08")
        assert b31 == Decimal("0.15")

    def test_cash_and_gold_unchanged(self) -> None:
        """Cash 0% and gold 15% are unchanged under Basel 3.1."""
        assert lookup_collateral_haircut("cash", is_basel_3_1=True) == Decimal("0.00")
        assert lookup_collateral_haircut("gold", is_basel_3_1=True) == Decimal("0.15")


# =============================================================================
# Test: Basel 3.1 F-IRB supervisory LGD (CRE32.9-12)
# =============================================================================


class TestBasel31FIRBSupervisoryLGD:
    """F-IRB supervisory LGD values change under Basel 3.1."""

    def test_crr_senior_unsecured_45pct(self) -> None:
        assert FIRB_SUPERVISORY_LGD["unsecured_senior"] == Decimal("0.45")

    def test_b31_senior_unsecured_40pct(self) -> None:
        """Basel 3.1 reduces senior unsecured from 45% to 40%."""
        assert BASEL31_FIRB_SUPERVISORY_LGD["unsecured_senior"] == Decimal("0.40")

    def test_subordinated_unchanged(self) -> None:
        """Subordinated LGD stays at 75% under both frameworks."""
        assert FIRB_SUPERVISORY_LGD["subordinated"] == Decimal("0.75")
        assert BASEL31_FIRB_SUPERVISORY_LGD["subordinated"] == Decimal("0.75")

    def test_b31_receivables_20pct(self) -> None:
        """Basel 3.1 reduces receivables from 35% to 20%."""
        assert FIRB_SUPERVISORY_LGD["receivables"] == Decimal("0.35")
        assert BASEL31_FIRB_SUPERVISORY_LGD["receivables"] == Decimal("0.20")

    def test_b31_real_estate_20pct(self) -> None:
        """Basel 3.1 reduces RE from 35% to 20%."""
        assert FIRB_SUPERVISORY_LGD["residential_re"] == Decimal("0.35")
        assert BASEL31_FIRB_SUPERVISORY_LGD["residential_re"] == Decimal("0.20")
        assert FIRB_SUPERVISORY_LGD["commercial_re"] == Decimal("0.35")
        assert BASEL31_FIRB_SUPERVISORY_LGD["commercial_re"] == Decimal("0.20")

    def test_b31_other_physical_25pct(self) -> None:
        """Basel 3.1 reduces other physical from 40% to 25%."""
        assert FIRB_SUPERVISORY_LGD["other_physical"] == Decimal("0.40")
        assert BASEL31_FIRB_SUPERVISORY_LGD["other_physical"] == Decimal("0.25")

    def test_financial_collateral_unchanged(self) -> None:
        """Financial collateral LGD stays at 0% under both frameworks."""
        assert FIRB_SUPERVISORY_LGD["financial_collateral"] == Decimal("0.00")
        assert BASEL31_FIRB_SUPERVISORY_LGD["financial_collateral"] == Decimal("0.00")

    def test_lookup_firb_lgd_framework_dispatch(self) -> None:
        """lookup_firb_lgd dispatches correctly between frameworks."""
        # CRR
        assert lookup_firb_lgd(collateral_type=None, is_basel_3_1=False) == Decimal("0.45")
        assert lookup_firb_lgd(collateral_type="receivables", is_basel_3_1=False) == Decimal("0.35")
        # Basel 3.1
        assert lookup_firb_lgd(collateral_type=None, is_basel_3_1=True) == Decimal("0.40")
        assert lookup_firb_lgd(collateral_type="receivables", is_basel_3_1=True) == Decimal("0.20")


# =============================================================================
# Test: HaircutCalculator framework branching
# =============================================================================


class TestHaircutCalculatorFrameworkBranching:
    """HaircutCalculator produces different results by framework."""

    def test_crr_calculator_uses_crr_haircuts(self) -> None:
        """CRR calculator returns 15% for main index equity."""
        calc = HaircutCalculator(is_basel_3_1=False)
        result = calc.calculate_single_haircut(
            collateral_type="equity",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            is_main_index=True,
        )
        assert result.collateral_haircut == Decimal("0.15")
        assert result.adjusted_value == Decimal("850000")

    def test_b31_calculator_uses_b31_haircuts(self) -> None:
        """Basel 3.1 calculator returns 25% for main index equity."""
        calc = HaircutCalculator(is_basel_3_1=True)
        result = calc.calculate_single_haircut(
            collateral_type="equity",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            is_main_index=True,
        )
        assert result.collateral_haircut == Decimal("0.25")
        assert result.adjusted_value == Decimal("750000")

    def test_b31_corp_bond_long_dated_higher_haircut(self) -> None:
        """Basel 3.1 produces higher haircut for 7y corporate bond CQS 2."""
        calc = HaircutCalculator(is_basel_3_1=True)
        result = calc.calculate_single_haircut(
            collateral_type="corp_bond",
            market_value=Decimal("500000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=2,
            residual_maturity_years=7.0,
        )
        # 5-10y band: 10% under Basel 3.1 (vs 6% CRR 5y+ band)
        assert result.collateral_haircut == Decimal("0.10")

    def test_apply_haircuts_uses_config_framework(self, crr_config: CalculationConfig, b31_config: CalculationConfig) -> None:
        """apply_haircuts produces different maturity bands based on config."""
        collateral = pl.LazyFrame({
            "collateral_reference": ["C1"],
            "collateral_type": ["govt_bond"],
            "market_value": [100_000.0],
            "currency": ["GBP"],
            "exposure_currency": ["GBP"],
            "residual_maturity_years": [7.0],
            "issuer_cqs": [2],
            "issuer_type": ["sovereign"],
            "is_eligible_financial_collateral": [True],
        })

        crr_calc = HaircutCalculator(is_basel_3_1=False)
        crr_result = crr_calc.apply_haircuts(collateral, crr_config).collect()

        b31_calc = HaircutCalculator(is_basel_3_1=True)
        b31_result = b31_calc.apply_haircuts(collateral, b31_config).collect()

        # CRR: 5y+ band = 6%
        assert crr_result["maturity_band"][0] == "5y_plus"
        assert crr_result["collateral_haircut"][0] == pytest.approx(0.06)

        # Basel 3.1: 5-10y band = 6%
        assert b31_result["maturity_band"][0] == "5_10y"
        assert b31_result["collateral_haircut"][0] == pytest.approx(0.06)


# =============================================================================
# Test: CRM Processor framework branching for F-IRB LGD
# =============================================================================


class TestCRMProcessorFIRBLGDBranching:
    """CRM processor uses correct F-IRB supervisory LGD per framework."""

    def test_crr_processor_uses_45pct_senior_unsecured(self, crr_config: CalculationConfig) -> None:
        """CRR processor applies 45% LGD for senior unsecured F-IRB."""
        processor = CRMProcessor(is_basel_3_1=False)
        exposures = pl.LazyFrame({
            "exposure_reference": ["E1"],
            "counterparty_reference": ["CP1"],
            "approach": [ApproachType.FIRB.value],
            "ead_gross": [1_000_000.0],
            "lgd_pre_crm": [0.45],
            "seniority": ["senior"],
            "parent_facility_reference": [None],
            "currency": ["GBP"],
        })

        result = processor._apply_firb_supervisory_lgd_no_collateral(exposures).collect()
        assert result["lgd_post_crm"][0] == pytest.approx(0.45)

    def test_b31_processor_uses_40pct_senior_unsecured(self, b31_config: CalculationConfig) -> None:
        """Basel 3.1 processor applies 40% LGD for senior unsecured F-IRB."""
        processor = CRMProcessor(is_basel_3_1=True)
        exposures = pl.LazyFrame({
            "exposure_reference": ["E1"],
            "counterparty_reference": ["CP1"],
            "approach": [ApproachType.FIRB.value],
            "ead_gross": [1_000_000.0],
            "lgd_pre_crm": [0.40],
            "seniority": ["senior"],
            "parent_facility_reference": [None],
            "currency": ["GBP"],
        })

        result = processor._apply_firb_supervisory_lgd_no_collateral(exposures).collect()
        assert result["lgd_post_crm"][0] == pytest.approx(0.40)

    def test_subordinated_75pct_both_frameworks(self) -> None:
        """Subordinated LGD = 75% under both CRR and Basel 3.1."""
        for is_b31 in [False, True]:
            processor = CRMProcessor(is_basel_3_1=is_b31)
            exposures = pl.LazyFrame({
                "exposure_reference": ["E1"],
                "counterparty_reference": ["CP1"],
                "approach": [ApproachType.FIRB.value],
                "ead_gross": [1_000_000.0],
                "lgd_pre_crm": [0.75],
                "seniority": ["subordinated"],
                "parent_facility_reference": [None],
                "currency": ["GBP"],
            })

            result = processor._apply_firb_supervisory_lgd_no_collateral(exposures).collect()
            assert result["lgd_post_crm"][0] == pytest.approx(0.75), (
                f"Subordinated LGD should be 75% for {'B31' if is_b31 else 'CRR'}"
            )

    def test_airb_preserves_modelled_lgd(self) -> None:
        """A-IRB exposures keep their modelled LGD under both frameworks."""
        for is_b31 in [False, True]:
            processor = CRMProcessor(is_basel_3_1=is_b31)
            exposures = pl.LazyFrame({
                "exposure_reference": ["E1"],
                "counterparty_reference": ["CP1"],
                "approach": [ApproachType.AIRB.value],
                "ead_gross": [1_000_000.0],
                "lgd_pre_crm": [0.32],
                "seniority": ["senior"],
                "parent_facility_reference": [None],
                "currency": ["GBP"],
            })

            result = processor._apply_firb_supervisory_lgd_no_collateral(exposures).collect()
            assert result["lgd_post_crm"][0] == pytest.approx(0.32)

    def test_no_seniority_column_uses_senior_default(self) -> None:
        """Without seniority column, F-IRB defaults to senior unsecured LGD."""
        # CRR: 45%
        crr = CRMProcessor(is_basel_3_1=False)
        exp_crr = pl.LazyFrame({
            "exposure_reference": ["E1"],
            "counterparty_reference": ["CP1"],
            "approach": [ApproachType.FIRB.value],
            "ead_gross": [1_000_000.0],
            "lgd_pre_crm": [0.45],
            "parent_facility_reference": [None],
            "currency": ["GBP"],
        })
        result_crr = crr._apply_firb_supervisory_lgd_no_collateral(exp_crr).collect()
        assert result_crr["lgd_post_crm"][0] == pytest.approx(0.45)

        # Basel 3.1: 40%
        b31 = CRMProcessor(is_basel_3_1=True)
        exp_b31 = pl.LazyFrame({
            "exposure_reference": ["E1"],
            "counterparty_reference": ["CP1"],
            "approach": [ApproachType.FIRB.value],
            "ead_gross": [1_000_000.0],
            "lgd_pre_crm": [0.40],
            "parent_facility_reference": [None],
            "currency": ["GBP"],
        })
        result_b31 = b31._apply_firb_supervisory_lgd_no_collateral(exp_b31).collect()
        assert result_b31["lgd_post_crm"][0] == pytest.approx(0.40)
