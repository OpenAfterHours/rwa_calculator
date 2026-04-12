"""
Unit tests for bond collateral eligibility per CRR Art. 197.

Tests verify:
- Government bonds CQS 1-4 are eligible as financial collateral (Art. 197(1)(b))
- Government bonds CQS 5-6 are ineligible
- Corporate/institution bonds CQS 1-3 are eligible (Art. 197(1)(d))
- Corporate/institution bonds CQS 4-6 are ineligible
- Unrated bonds (null CQS) are ineligible for both types
- The HaircutCalculator pipeline enforces eligibility (value_after_haircut = 0 for ineligible)
- The scalar lookup returns None for ineligible bonds

Why these tests matter:
    Ineligible bonds silently reducing EAD is a capital understatement bug.
    CQS 5-6 government bonds and CQS 4-6 corporate bonds must NOT reduce
    exposure-at-default, per Art. 197. Without enforcement, the CRM processor
    treats any bond with a haircut as eligible collateral.
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.data.tables.haircuts import (
    get_haircut_table,
    is_bond_eligible_as_financial_collateral,
    lookup_collateral_haircut,
)
from rwa_calc.engine.crm.haircuts import HaircutCalculator

# =============================================================================
# ELIGIBILITY FUNCTION TESTS
# =============================================================================


class TestBondEligibilityFunction:
    """Tests for is_bond_eligible_as_financial_collateral (Art. 197)."""

    def test_govt_bond_cqs1_eligible(self) -> None:
        """Government bond CQS 1 (AAA-AA) is eligible."""
        assert is_bond_eligible_as_financial_collateral("govt_bond", 1) is True

    def test_govt_bond_cqs2_eligible(self) -> None:
        """Government bond CQS 2 (A) is eligible."""
        assert is_bond_eligible_as_financial_collateral("govt_bond", 2) is True

    def test_govt_bond_cqs3_eligible(self) -> None:
        """Government bond CQS 3 (BBB) is eligible."""
        assert is_bond_eligible_as_financial_collateral("govt_bond", 3) is True

    def test_govt_bond_cqs4_eligible(self) -> None:
        """Government bond CQS 4 (BB) is eligible per Art. 197(1)(b)."""
        assert is_bond_eligible_as_financial_collateral("govt_bond", 4) is True

    def test_govt_bond_cqs5_ineligible(self) -> None:
        """Government bond CQS 5 (B) is ineligible."""
        assert is_bond_eligible_as_financial_collateral("govt_bond", 5) is False

    def test_govt_bond_cqs6_ineligible(self) -> None:
        """Government bond CQS 6 (CCC) is ineligible."""
        assert is_bond_eligible_as_financial_collateral("govt_bond", 6) is False

    def test_govt_bond_unrated_ineligible(self) -> None:
        """Unrated government bonds are ineligible."""
        assert is_bond_eligible_as_financial_collateral("govt_bond", None) is False

    def test_corp_bond_cqs1_eligible(self) -> None:
        """Corporate bond CQS 1 (AAA-AA) is eligible."""
        assert is_bond_eligible_as_financial_collateral("corp_bond", 1) is True

    def test_corp_bond_cqs2_eligible(self) -> None:
        """Corporate bond CQS 2 (A) is eligible."""
        assert is_bond_eligible_as_financial_collateral("corp_bond", 2) is True

    def test_corp_bond_cqs3_eligible(self) -> None:
        """Corporate bond CQS 3 (BBB) is eligible."""
        assert is_bond_eligible_as_financial_collateral("corp_bond", 3) is True

    def test_corp_bond_cqs4_ineligible(self) -> None:
        """Corporate bond CQS 4 (BB) is ineligible per Art. 197(1)(d)."""
        assert is_bond_eligible_as_financial_collateral("corp_bond", 4) is False

    def test_corp_bond_cqs5_ineligible(self) -> None:
        """Corporate bond CQS 5 (B) is ineligible."""
        assert is_bond_eligible_as_financial_collateral("corp_bond", 5) is False

    def test_corp_bond_cqs6_ineligible(self) -> None:
        """Corporate bond CQS 6 (CCC) is ineligible."""
        assert is_bond_eligible_as_financial_collateral("corp_bond", 6) is False

    def test_corp_bond_unrated_ineligible(self) -> None:
        """Unrated corporate bonds are ineligible."""
        assert is_bond_eligible_as_financial_collateral("corp_bond", None) is False

    def test_non_bond_always_eligible(self) -> None:
        """Non-bond collateral types are not subject to bond eligibility rules."""
        assert is_bond_eligible_as_financial_collateral("cash", None) is True
        assert is_bond_eligible_as_financial_collateral("equity", 5) is True
        assert is_bond_eligible_as_financial_collateral("real_estate", None) is True


# =============================================================================
# SCALAR LOOKUP TESTS
# =============================================================================


class TestScalarLookupEligibility:
    """Tests for lookup_collateral_haircut returning None for ineligible bonds."""

    def test_govt_bond_cqs4_returns_15_percent(self) -> None:
        """CQS 4 govt bond: eligible, 15% haircut per Art. 224 Table 1."""
        result = lookup_collateral_haircut("govt_bond", cqs=4, residual_maturity_years=3.0)
        assert result == Decimal("0.15")

    def test_govt_bond_cqs4_all_maturities(self) -> None:
        """CQS 4 govt bond: 15% flat across all maturity bands."""
        for mat in [0.5, 3.0, 7.0]:
            result = lookup_collateral_haircut("govt_bond", cqs=4, residual_maturity_years=mat)
            assert result == Decimal("0.15"), f"maturity={mat}"

    def test_govt_bond_cqs4_b31_returns_15_percent(self) -> None:
        """CQS 4 govt bond under Basel 3.1: eligible, 15% haircut."""
        result = lookup_collateral_haircut(
            "govt_bond", cqs=4, residual_maturity_years=3.0, is_basel_3_1=True
        )
        assert result == Decimal("0.15")

    def test_govt_bond_cqs5_returns_none(self) -> None:
        """CQS 5 govt bond: ineligible, returns None."""
        result = lookup_collateral_haircut("govt_bond", cqs=5, residual_maturity_years=3.0)
        assert result is None

    def test_govt_bond_cqs6_returns_none(self) -> None:
        """CQS 6 govt bond: ineligible, returns None."""
        result = lookup_collateral_haircut("govt_bond", cqs=6, residual_maturity_years=3.0)
        assert result is None

    def test_govt_bond_unrated_returns_none(self) -> None:
        """Unrated govt bond: ineligible, returns None."""
        result = lookup_collateral_haircut("govt_bond", cqs=None, residual_maturity_years=3.0)
        assert result is None

    def test_corp_bond_cqs4_returns_none(self) -> None:
        """CQS 4 corp bond: ineligible, returns None."""
        result = lookup_collateral_haircut("corp_bond", cqs=4, residual_maturity_years=3.0)
        assert result is None

    def test_corp_bond_cqs5_returns_none(self) -> None:
        """CQS 5 corp bond: ineligible, returns None."""
        result = lookup_collateral_haircut("corp_bond", cqs=5, residual_maturity_years=3.0)
        assert result is None

    def test_corp_bond_cqs6_returns_none(self) -> None:
        """CQS 6 corp bond: ineligible, returns None."""
        result = lookup_collateral_haircut("corp_bond", cqs=6, residual_maturity_years=3.0)
        assert result is None

    def test_corp_bond_unrated_returns_none(self) -> None:
        """Unrated corp bond: ineligible, returns None."""
        result = lookup_collateral_haircut("corp_bond", cqs=None, residual_maturity_years=3.0)
        assert result is None

    def test_corp_bond_cqs1_still_eligible(self) -> None:
        """CQS 1 corp bond: still eligible, returns valid haircut."""
        result = lookup_collateral_haircut("corp_bond", cqs=1, residual_maturity_years=3.0)
        assert result is not None
        assert result == Decimal("0.04")

    def test_govt_bond_cqs1_still_eligible(self) -> None:
        """CQS 1 govt bond: still eligible, returns valid haircut."""
        result = lookup_collateral_haircut("govt_bond", cqs=1, residual_maturity_years=3.0)
        assert result is not None
        assert result == Decimal("0.02")


# =============================================================================
# DATAFRAME TABLE TESTS
# =============================================================================


class TestHaircutTableEligibleRows:
    """Tests that haircut DataFrames include CQS 4 govt bond rows."""

    def test_crr_table_has_cqs4_govt_bond(self) -> None:
        """CRR haircut table includes CQS 4 government bond rows."""
        df = get_haircut_table(is_basel_3_1=False)
        cqs4_govt = df.filter((pl.col("collateral_type") == "govt_bond") & (pl.col("cqs") == 4))
        assert cqs4_govt.height == 3  # 3 CRR maturity bands
        assert all(h == pytest.approx(0.15) for h in cqs4_govt["haircut"].to_list())

    def test_b31_table_has_cqs4_govt_bond(self) -> None:
        """Basel 3.1 haircut table includes CQS 4 government bond rows."""
        df = get_haircut_table(is_basel_3_1=True)
        cqs4_govt = df.filter((pl.col("collateral_type") == "govt_bond") & (pl.col("cqs") == 4))
        assert cqs4_govt.height == 5  # 5 B31 maturity bands
        assert all(h == pytest.approx(0.15) for h in cqs4_govt["haircut"].to_list())

    def test_crr_table_no_cqs5_govt_bond(self) -> None:
        """CRR haircut table does NOT include CQS 5+ government bond rows."""
        df = get_haircut_table(is_basel_3_1=False)
        cqs5_govt = df.filter((pl.col("collateral_type") == "govt_bond") & (pl.col("cqs") >= 5))
        assert cqs5_govt.height == 0

    def test_crr_table_no_cqs4_corp_bond(self) -> None:
        """CRR haircut table does NOT include CQS 4+ corporate bond rows."""
        df = get_haircut_table(is_basel_3_1=False)
        cqs4_corp = df.filter((pl.col("collateral_type") == "corp_bond") & (pl.col("cqs") >= 4))
        assert cqs4_corp.height == 0


# =============================================================================
# SINGLE HAIRCUT CALCULATOR TESTS
# =============================================================================


class TestSingleHaircutIneligibility:
    """Tests for HaircutCalculator.calculate_single_haircut with ineligible bonds."""

    @pytest.fixture()
    def calculator(self) -> HaircutCalculator:
        return HaircutCalculator(is_basel_3_1=False)

    @pytest.fixture()
    def b31_calculator(self) -> HaircutCalculator:
        return HaircutCalculator(is_basel_3_1=True)

    def test_corp_bond_cqs4_zero_adjusted_value(self, calculator: HaircutCalculator) -> None:
        """CQS 4 corp bond: ineligible, adjusted value = 0."""
        result = calculator.calculate_single_haircut(
            collateral_type="corp_bond",
            market_value=Decimal("500000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=4,
            residual_maturity_years=3.0,
        )
        assert result.adjusted_value == Decimal("0")
        assert "INELIGIBLE" in result.description

    def test_govt_bond_cqs5_zero_adjusted_value(self, calculator: HaircutCalculator) -> None:
        """CQS 5 govt bond: ineligible, adjusted value = 0."""
        result = calculator.calculate_single_haircut(
            collateral_type="govt_bond",
            market_value=Decimal("1000000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=5,
            residual_maturity_years=2.0,
        )
        assert result.adjusted_value == Decimal("0")
        assert "INELIGIBLE" in result.description

    def test_govt_bond_cqs4_eligible_adjusted_value(self, calculator: HaircutCalculator) -> None:
        """CQS 4 govt bond: eligible, adjusted value = MV * (1 - 0.15)."""
        result = calculator.calculate_single_haircut(
            collateral_type="govt_bond",
            market_value=Decimal("100000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=4,
            residual_maturity_years=3.0,
        )
        assert result.adjusted_value == Decimal("85000")
        assert result.collateral_haircut == Decimal("0.15")

    def test_corp_bond_cqs5_b31_zero_adjusted_value(
        self, b31_calculator: HaircutCalculator
    ) -> None:
        """CQS 5 corp bond under Basel 3.1: ineligible, adjusted value = 0."""
        result = b31_calculator.calculate_single_haircut(
            collateral_type="corp_bond",
            market_value=Decimal("200000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=5,
            residual_maturity_years=3.0,
        )
        assert result.adjusted_value == Decimal("0")

    def test_unrated_corp_bond_zero_adjusted_value(self, calculator: HaircutCalculator) -> None:
        """Unrated corp bond: ineligible, adjusted value = 0."""
        result = calculator.calculate_single_haircut(
            collateral_type="corp_bond",
            market_value=Decimal("300000"),
            collateral_currency="GBP",
            exposure_currency="GBP",
            cqs=None,
            residual_maturity_years=3.0,
        )
        assert result.adjusted_value == Decimal("0")


# =============================================================================
# PIPELINE (LAZYFRAME) ELIGIBILITY TESTS
# =============================================================================


class TestPipelineEligibility:
    """Tests that the LazyFrame pipeline zeroes out ineligible bond values."""

    @pytest.fixture()
    def crr_config(self):
        """CRR calculation config."""
        from datetime import date

        from rwa_calc.contracts.config import CalculationConfig

        return CalculationConfig.crr(reporting_date=date(2025, 12, 31))

    @pytest.fixture()
    def b31_config(self):
        """Basel 3.1 calculation config."""
        from datetime import date

        from rwa_calc.contracts.config import CalculationConfig

        return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))

    def _make_collateral_lf(
        self,
        collateral_type: str,
        issuer_cqs: int | None,
        market_value: float = 500_000.0,
    ) -> pl.LazyFrame:
        """Build a minimal collateral LazyFrame for haircut testing."""
        return pl.LazyFrame(
            {
                "collateral_reference": ["COLL1"],
                "collateral_type": [collateral_type],
                "currency": ["GBP"],
                "market_value": [market_value],
                "issuer_cqs": [issuer_cqs],
                "issuer_type": ["sovereign" if "govt" in collateral_type else "corporate"],
                "residual_maturity_years": [3.0],
                "is_eligible_financial_collateral": [True],
                "exposure_currency": ["GBP"],
                "exposure_maturity": [5.0],
            },
            schema={
                "collateral_reference": pl.String,
                "collateral_type": pl.String,
                "currency": pl.String,
                "market_value": pl.Float64,
                "issuer_cqs": pl.Int8,
                "issuer_type": pl.String,
                "residual_maturity_years": pl.Float64,
                "is_eligible_financial_collateral": pl.Boolean,
                "exposure_currency": pl.String,
                "exposure_maturity": pl.Float64,
            },
        )

    def test_pipeline_corp_bond_cqs4_zeroed(self, crr_config) -> None:
        """Pipeline: CQS 4 corp bond gets value_after_haircut = 0."""
        calc = HaircutCalculator(is_basel_3_1=False)
        lf = self._make_collateral_lf("corp_bond", issuer_cqs=4)
        result = calc.apply_haircuts(lf, crr_config).collect()
        assert result["value_after_haircut"][0] == pytest.approx(0.0)

    def test_pipeline_corp_bond_cqs5_zeroed(self, crr_config) -> None:
        """Pipeline: CQS 5 corp bond gets value_after_haircut = 0."""
        calc = HaircutCalculator(is_basel_3_1=False)
        lf = self._make_collateral_lf("corp_bond", issuer_cqs=5)
        result = calc.apply_haircuts(lf, crr_config).collect()
        assert result["value_after_haircut"][0] == pytest.approx(0.0)

    def test_pipeline_govt_bond_cqs5_zeroed(self, crr_config) -> None:
        """Pipeline: CQS 5 govt bond gets value_after_haircut = 0."""
        calc = HaircutCalculator(is_basel_3_1=False)
        lf = self._make_collateral_lf("govt_bond", issuer_cqs=5)
        result = calc.apply_haircuts(lf, crr_config).collect()
        assert result["value_after_haircut"][0] == pytest.approx(0.0)

    def test_pipeline_govt_bond_cqs6_zeroed(self, crr_config) -> None:
        """Pipeline: CQS 6 govt bond gets value_after_haircut = 0."""
        calc = HaircutCalculator(is_basel_3_1=False)
        lf = self._make_collateral_lf("govt_bond", issuer_cqs=6)
        result = calc.apply_haircuts(lf, crr_config).collect()
        assert result["value_after_haircut"][0] == pytest.approx(0.0)

    def test_pipeline_govt_bond_cqs4_eligible(self, crr_config) -> None:
        """Pipeline: CQS 4 govt bond is eligible with 15% haircut."""
        calc = HaircutCalculator(is_basel_3_1=False)
        lf = self._make_collateral_lf("govt_bond", issuer_cqs=4)
        result = calc.apply_haircuts(lf, crr_config).collect()
        expected = 500_000.0 * (1.0 - 0.15)  # 425,000
        assert result["value_after_haircut"][0] == pytest.approx(expected)

    def test_pipeline_corp_bond_cqs3_eligible(self, crr_config) -> None:
        """Pipeline: CQS 3 corp bond is still eligible."""
        calc = HaircutCalculator(is_basel_3_1=False)
        lf = self._make_collateral_lf("corp_bond", issuer_cqs=3)
        result = calc.apply_haircuts(lf, crr_config).collect()
        assert result["value_after_haircut"][0] > 0.0

    def test_pipeline_corp_bond_cqs4_b31_zeroed(self, b31_config) -> None:
        """Pipeline under Basel 3.1: CQS 4 corp bond zeroed."""
        calc = HaircutCalculator(is_basel_3_1=True)
        lf = self._make_collateral_lf("corp_bond", issuer_cqs=4)
        result = calc.apply_haircuts(lf, b31_config).collect()
        assert result["value_after_haircut"][0] == pytest.approx(0.0)

    def test_pipeline_unrated_corp_bond_zeroed(self, crr_config) -> None:
        """Pipeline: Unrated corp bond gets value_after_haircut = 0."""
        calc = HaircutCalculator(is_basel_3_1=False)
        # Null CQS for unrated
        lf = pl.LazyFrame(
            {
                "collateral_reference": ["COLL1"],
                "collateral_type": ["corp_bond"],
                "currency": ["GBP"],
                "market_value": [500_000.0],
                "issuer_cqs": [None],
                "issuer_type": ["corporate"],
                "residual_maturity_years": [3.0],
                "is_eligible_financial_collateral": [True],
                "exposure_currency": ["GBP"],
                "exposure_maturity": [5.0],
            },
            schema={
                "collateral_reference": pl.String,
                "collateral_type": pl.String,
                "currency": pl.String,
                "market_value": pl.Float64,
                "issuer_cqs": pl.Int8,
                "issuer_type": pl.String,
                "residual_maturity_years": pl.Float64,
                "is_eligible_financial_collateral": pl.Boolean,
                "exposure_currency": pl.String,
                "exposure_maturity": pl.Float64,
            },
        )
        result = calc.apply_haircuts(lf, crr_config).collect()
        assert result["value_after_haircut"][0] == pytest.approx(0.0)

    def test_pipeline_eligible_flag_updated_for_ineligible(self, crr_config) -> None:
        """Pipeline: is_eligible_financial_collateral set to False for ineligible bonds."""
        calc = HaircutCalculator(is_basel_3_1=False)
        lf = self._make_collateral_lf("corp_bond", issuer_cqs=5)
        result = calc.apply_haircuts(lf, crr_config).collect()
        assert result["is_eligible_financial_collateral"][0] is False

    def test_pipeline_cash_unaffected(self, crr_config) -> None:
        """Pipeline: Cash collateral is unaffected by bond eligibility rules."""
        calc = HaircutCalculator(is_basel_3_1=False)
        lf = pl.LazyFrame(
            {
                "collateral_reference": ["COLL1"],
                "collateral_type": ["cash"],
                "currency": ["GBP"],
                "market_value": [100_000.0],
                "issuer_cqs": [None],
                "issuer_type": [None],
                "residual_maturity_years": [None],
                "is_eligible_financial_collateral": [True],
                "exposure_currency": ["GBP"],
                "exposure_maturity": [5.0],
            },
            schema={
                "collateral_reference": pl.String,
                "collateral_type": pl.String,
                "currency": pl.String,
                "market_value": pl.Float64,
                "issuer_cqs": pl.Int8,
                "issuer_type": pl.String,
                "residual_maturity_years": pl.Float64,
                "is_eligible_financial_collateral": pl.Boolean,
                "exposure_currency": pl.String,
                "exposure_maturity": pl.Float64,
            },
        )
        result = calc.apply_haircuts(lf, crr_config).collect()
        assert result["value_after_haircut"][0] == pytest.approx(100_000.0)
