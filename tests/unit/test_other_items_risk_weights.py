"""
Unit tests for "Other Items" (Art. 134) risk weights under CRR and Basel 3.1.

Why these tests matter:
    Art. 134 defines risk weights for miscellaneous items not covered by other
    exposure classes. Without explicit handling, all Other Items exposures
    silently default to 100% via the CQS join fallback. This is correct for
    tangible assets (Art. 134(2)) but wrong for:
    - Cash/gold: should be 0% (Art. 134(1)/(4)) — 100% default OVERSTATES
    - Items in collection: should be 20% (Art. 134(3)) — 100% default OVERSTATES
    - Residual lease value: should be 1/t × 100% (Art. 134(6)) — can differ

    The entity_type sub-values (other_cash, other_gold, other_items_in_collection,
    other_tangible, other_residual_lease) drive sub-type routing in the SA calculator.

Other Items treatment is identical under CRR and PRA PS1/26 Basel 3.1:
    - Cash and equivalent: 0% (Art. 134(1))
    - Gold bullion in own vaults: 0% (Art. 134(4))
    - Items in course of collection: 20% (Art. 134(3))
    - Tangible assets, prepaid expenses: 100% (Art. 134(2))
    - Residual value of leased assets: 1/t × 100% where t ≥ 1 (Art. 134(6))
    - All other: 100% (Art. 134(2))

References:
    - CRR Art. 134 / PRA PS1/26 Art. 134: Other items risk weights
    - CRR Art. 112(q): Other items exposure class
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from tests.fixtures.single_exposure import calculate_single_sa_exposure

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.crr_risk_weights import (
    OTHER_ITEMS_CASH_RW,
    OTHER_ITEMS_COLLECTION_RW,
    OTHER_ITEMS_DEFAULT_RW,
    OTHER_ITEMS_GOLD_RW,
    OTHER_ITEMS_TANGIBLE_RW,
    lookup_risk_weight,
)
from rwa_calc.engine.sa import SACalculator


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


# =============================================================================
# DATA TABLE TESTS
# =============================================================================


class TestOtherItemsRiskWeightConstants:
    """Tests for Art. 134 risk weight constants."""

    def test_cash_rw_zero(self):
        """Art. 134(1): Cash and equivalent → 0%."""
        assert OTHER_ITEMS_CASH_RW == Decimal("0.00")

    def test_gold_rw_zero(self):
        """Art. 134(4): Gold bullion in own vaults → 0%."""
        assert OTHER_ITEMS_GOLD_RW == Decimal("0.00")

    def test_collection_rw_twenty(self):
        """Art. 134(3): Items in course of collection → 20%."""
        assert OTHER_ITEMS_COLLECTION_RW == Decimal("0.20")

    def test_tangible_rw_hundred(self):
        """Art. 134(2): Tangible assets → 100%."""
        assert OTHER_ITEMS_TANGIBLE_RW == Decimal("1.00")

    def test_default_rw_hundred(self):
        """Art. 134(2): All other items → 100%."""
        assert OTHER_ITEMS_DEFAULT_RW == Decimal("1.00")

    def test_lookup_risk_weight_other(self):
        """lookup_risk_weight for OTHER returns 100% (generic default)."""
        assert lookup_risk_weight("OTHER", None) == Decimal("1.00")


# =============================================================================
# CRR SA CALCULATOR TESTS
# =============================================================================


class TestCRROtherItemsRiskWeights:
    """Tests for Other Items risk weights through the CRR SA calculator."""

    def test_cash_zero_percent(self, sa_calculator, crr_config):
        """CRR Art. 134(1): Cash and equivalent → 0% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_cash",
        )
        assert result["risk_weight"] == pytest.approx(0.0)
        assert result["rwa"] == pytest.approx(0.0)

    def test_gold_zero_percent(self, sa_calculator, crr_config):
        """CRR Art. 134(4): Gold bullion in own vaults → 0% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("3000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_gold",
        )
        assert result["risk_weight"] == pytest.approx(0.0)
        assert result["rwa"] == pytest.approx(0.0)

    def test_items_in_collection_twenty_percent(self, sa_calculator, crr_config):
        """CRR Art. 134(3): Items in course of collection → 20% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_items_in_collection",
        )
        assert result["risk_weight"] == pytest.approx(0.20)
        assert result["rwa"] == pytest.approx(400000.0)

    def test_tangible_hundred_percent(self, sa_calculator, crr_config):
        """CRR Art. 134(2): Tangible assets → 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_tangible",
        )
        assert result["risk_weight"] == pytest.approx(1.0)
        assert result["rwa"] == pytest.approx(1000000.0)

    def test_residual_lease_five_years(self, sa_calculator, crr_config):
        """CRR Art. 134(6): Residual lease value, t=5 years → 1/5 = 20% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_residual_lease",
            residual_maturity_years=5.0,
        )
        assert result["risk_weight"] == pytest.approx(0.20)
        assert result["rwa"] == pytest.approx(200000.0)

    def test_residual_lease_one_year(self, sa_calculator, crr_config):
        """CRR Art. 134(6): Residual lease value, t=1 year → 1/1 = 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_residual_lease",
            residual_maturity_years=1.0,
        )
        assert result["risk_weight"] == pytest.approx(1.0)

    def test_residual_lease_two_point_five_years(self, sa_calculator, crr_config):
        """CRR Art. 134(6): Residual lease value, t=2.5 years → 1/2.5 = 40% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_residual_lease",
            residual_maturity_years=2.5,
        )
        assert result["risk_weight"] == pytest.approx(0.40)

    def test_residual_lease_sub_one_year_floors_to_one(self, sa_calculator, crr_config):
        """CRR Art. 134(6): Residual lease t < 1 year floors to 1 → 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_residual_lease",
            residual_maturity_years=0.5,
        )
        assert result["risk_weight"] == pytest.approx(1.0)

    def test_residual_lease_null_maturity_defaults_to_hundred(self, sa_calculator, crr_config):
        """CRR Art. 134(6): Residual lease with null maturity → 100% (conservative)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_residual_lease",
        )
        assert result["risk_weight"] == pytest.approx(1.0)

    def test_generic_other_hundred_percent(self, sa_calculator, crr_config):
        """CRR Art. 134(2): Generic 'other' with no entity_type → 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.0)


# =============================================================================
# BASEL 3.1 SA CALCULATOR TESTS
# =============================================================================


class TestB31OtherItemsRiskWeights:
    """Tests for Other Items risk weights through the Basel 3.1 SA calculator.

    Other Items treatment is unchanged between CRR and Basel 3.1 (Art. 134
    is not modified by PRA PS1/26). These tests confirm identical behaviour.
    """

    def test_cash_zero_percent(self, sa_calculator, b31_config):
        """B31 Art. 134(1): Cash and equivalent → 0% RW (unchanged from CRR)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="other",
            config=b31_config,
            entity_type="other_cash",
        )
        assert result["risk_weight"] == pytest.approx(0.0)
        assert result["rwa"] == pytest.approx(0.0)

    def test_gold_zero_percent(self, sa_calculator, b31_config):
        """B31 Art. 134(4): Gold bullion → 0% RW (unchanged from CRR)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("3000000"),
            exposure_class="other",
            config=b31_config,
            entity_type="other_gold",
        )
        assert result["risk_weight"] == pytest.approx(0.0)

    def test_items_in_collection_twenty_percent(self, sa_calculator, b31_config):
        """B31 Art. 134(3): Items in course of collection → 20% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="other",
            config=b31_config,
            entity_type="other_items_in_collection",
        )
        assert result["risk_weight"] == pytest.approx(0.20)
        assert result["rwa"] == pytest.approx(400000.0)

    def test_tangible_hundred_percent(self, sa_calculator, b31_config):
        """B31 Art. 134(2): Tangible assets → 100% RW (unchanged from CRR)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=b31_config,
            entity_type="other_tangible",
        )
        assert result["risk_weight"] == pytest.approx(1.0)

    def test_residual_lease_five_years(self, sa_calculator, b31_config):
        """B31 Art. 134(6): Residual lease value, t=5 years → 20% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=b31_config,
            entity_type="other_residual_lease",
            residual_maturity_years=5.0,
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_residual_lease_ten_years(self, sa_calculator, b31_config):
        """B31 Art. 134(6): Residual lease value, t=10 years → 10% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=b31_config,
            entity_type="other_residual_lease",
            residual_maturity_years=10.0,
        )
        assert result["risk_weight"] == pytest.approx(0.10)

    def test_residual_lease_sub_one_year_floors(self, sa_calculator, b31_config):
        """B31 Art. 134(6): Residual lease t < 1yr floors to t=1 → 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=b31_config,
            entity_type="other_residual_lease",
            residual_maturity_years=0.25,
        )
        assert result["risk_weight"] == pytest.approx(1.0)

    def test_generic_other_hundred_percent(self, sa_calculator, b31_config):
        """B31 Art. 134(2): Generic OTHER → 100% RW (unchanged from CRR)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.0)
