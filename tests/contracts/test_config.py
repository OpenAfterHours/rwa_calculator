"""Tests for configuration contracts.

Tests the CalculationConfig and related configuration classes,
including factory methods for CRR and Basel 3.1 frameworks.
"""

from datetime import date
from decimal import Decimal

import pytest

from rwa_calc.contracts.config import (
    CalculationConfig,
    IRBPermissions,
    LGDFloors,
    OutputFloorConfig,
    PDFloors,
    RetailThresholds,
    SupportingFactors,
)
from rwa_calc.domain.enums import (
    ApproachType,
    CollateralType,
    ExposureClass,
    RegulatoryFramework,
)


class TestPDFloors:
    """Tests for PDFloors configuration."""

    def test_crr_pd_floors_single_value(self):
        """CRR should have a single 0.03% PD floor for all classes."""
        floors = PDFloors.crr()

        assert floors.corporate == Decimal("0.0003")
        assert floors.corporate_sme == Decimal("0.0003")
        assert floors.retail_mortgage == Decimal("0.0003")
        assert floors.retail_other == Decimal("0.0003")
        assert floors.retail_qrre_transactor == Decimal("0.0003")
        assert floors.retail_qrre_revolver == Decimal("0.0003")

    def test_basel_3_1_pd_floors_differentiated(self):
        """Basel 3.1 should have differentiated PD floors."""
        floors = PDFloors.basel_3_1()

        assert floors.corporate == Decimal("0.0005")  # 0.05%
        assert floors.corporate_sme == Decimal("0.0005")  # 0.05%
        assert floors.retail_mortgage == Decimal("0.0005")  # 0.05%
        assert floors.retail_other == Decimal("0.0005")  # 0.05%
        assert floors.retail_qrre_transactor == Decimal("0.0003")  # 0.03%
        assert floors.retail_qrre_revolver == Decimal("0.0010")  # 0.10%

    def test_get_floor_by_exposure_class(self):
        """get_floor should return correct floor for each class."""
        floors = PDFloors.basel_3_1()

        assert floors.get_floor(ExposureClass.CORPORATE) == Decimal("0.0005")
        assert floors.get_floor(ExposureClass.RETAIL_MORTGAGE) == Decimal("0.0005")
        assert floors.get_floor(ExposureClass.RETAIL_QRRE, is_qrre_transactor=True) == Decimal("0.0003")
        assert floors.get_floor(ExposureClass.RETAIL_QRRE, is_qrre_transactor=False) == Decimal("0.0010")

    def test_pd_floors_immutable(self):
        """PDFloors should be immutable (frozen dataclass)."""
        floors = PDFloors.crr()

        with pytest.raises(AttributeError):
            floors.corporate = Decimal("0.01")


class TestLGDFloors:
    """Tests for LGDFloors configuration."""

    def test_crr_lgd_floors_zero(self):
        """CRR should have no LGD floors (all zero)."""
        floors = LGDFloors.crr()

        assert floors.unsecured == Decimal("0.0")
        assert floors.financial_collateral == Decimal("0.0")
        assert floors.receivables == Decimal("0.0")
        assert floors.commercial_real_estate == Decimal("0.0")
        assert floors.residential_real_estate == Decimal("0.0")
        assert floors.other_physical == Decimal("0.0")

    def test_basel_3_1_lgd_floors(self):
        """Basel 3.1 should have LGD floors by collateral type."""
        floors = LGDFloors.basel_3_1()

        assert floors.unsecured == Decimal("0.25")  # 25%
        assert floors.financial_collateral == Decimal("0.0")  # 0%
        assert floors.receivables == Decimal("0.10")  # 10%
        assert floors.commercial_real_estate == Decimal("0.10")  # 10%
        assert floors.residential_real_estate == Decimal("0.05")  # 5%
        assert floors.other_physical == Decimal("0.15")  # 15%

    def test_get_floor_by_collateral_type(self):
        """get_floor should return correct floor for each collateral type."""
        floors = LGDFloors.basel_3_1()

        assert floors.get_floor(CollateralType.FINANCIAL) == Decimal("0.0")
        assert floors.get_floor(CollateralType.RECEIVABLES) == Decimal("0.10")
        assert floors.get_floor(CollateralType.OTHER) == Decimal("0.25")


class TestSupportingFactors:
    """Tests for SupportingFactors configuration."""

    def test_crr_supporting_factors_enabled(self):
        """CRR should have SME and infrastructure factors enabled."""
        factors = SupportingFactors.crr()

        assert factors.enabled is True
        assert factors.sme_factor_under_threshold == Decimal("0.7619")
        assert factors.sme_factor_above_threshold == Decimal("0.85")
        assert factors.infrastructure_factor == Decimal("0.75")

    def test_basel_3_1_supporting_factors_disabled(self):
        """Basel 3.1 should have supporting factors disabled (all 1.0)."""
        factors = SupportingFactors.basel_3_1()

        assert factors.enabled is False
        assert factors.sme_factor_under_threshold == Decimal("1.0")
        assert factors.sme_factor_above_threshold == Decimal("1.0")
        assert factors.infrastructure_factor == Decimal("1.0")


class TestOutputFloorConfig:
    """Tests for OutputFloorConfig configuration."""

    def test_crr_no_output_floor(self):
        """CRR should have no output floor."""
        floor_config = OutputFloorConfig.crr()

        assert floor_config.enabled is False
        assert floor_config.get_floor_percentage(date(2025, 1, 1)) == Decimal("0.0")

    def test_basel_3_1_output_floor_enabled(self):
        """Basel 3.1 should have 72.5% output floor."""
        floor_config = OutputFloorConfig.basel_3_1()

        assert floor_config.enabled is True
        assert floor_config.floor_percentage == Decimal("0.725")

    def test_basel_3_1_transitional_schedule(self):
        """Basel 3.1 should have transitional floor schedule."""
        floor_config = OutputFloorConfig.basel_3_1()

        # Check transitional percentages
        assert floor_config.get_floor_percentage(date(2027, 6, 1)) == Decimal("0.50")
        assert floor_config.get_floor_percentage(date(2028, 6, 1)) == Decimal("0.55")
        assert floor_config.get_floor_percentage(date(2029, 6, 1)) == Decimal("0.60")
        assert floor_config.get_floor_percentage(date(2030, 6, 1)) == Decimal("0.65")
        assert floor_config.get_floor_percentage(date(2031, 6, 1)) == Decimal("0.70")
        assert floor_config.get_floor_percentage(date(2032, 6, 1)) == Decimal("0.725")


class TestIRBPermissions:
    """Tests for IRBPermissions configuration."""

    def test_sa_only_permissions(self):
        """SA only should only permit Standardised Approach."""
        permissions = IRBPermissions.sa_only()

        assert permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.SA)
        assert not permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)
        assert not permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)

    def test_full_irb_permissions(self):
        """Full IRB should permit IRB for applicable classes."""
        permissions = IRBPermissions.full_irb()

        # Corporate can use SA, FIRB, or AIRB
        assert permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.SA)
        assert permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)
        assert permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)

        # Retail can only use SA or AIRB (no FIRB)
        assert permissions.is_permitted(ExposureClass.RETAIL_MORTGAGE, ApproachType.SA)
        assert not permissions.is_permitted(ExposureClass.RETAIL_MORTGAGE, ApproachType.FIRB)
        assert permissions.is_permitted(ExposureClass.RETAIL_MORTGAGE, ApproachType.AIRB)

        # Equity can only use SA under Basel 3.1
        assert permissions.is_permitted(ExposureClass.EQUITY, ApproachType.SA)
        assert not permissions.is_permitted(ExposureClass.EQUITY, ApproachType.AIRB)


class TestCalculationConfig:
    """Tests for CalculationConfig master configuration."""

    def test_crr_factory_method(self):
        """crr() factory should create correct CRR configuration."""
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31),
        )

        assert config.framework == RegulatoryFramework.CRR
        assert config.is_crr is True
        assert config.is_basel_3_1 is False
        assert config.reporting_date == date(2025, 12, 31)
        assert config.base_currency == "GBP"
        assert config.scaling_factor == Decimal("1.06")

        # Check sub-configurations
        assert config.pd_floors.corporate == Decimal("0.0003")
        assert config.lgd_floors.unsecured == Decimal("0.0")
        assert config.supporting_factors.enabled is True
        assert config.output_floor.enabled is False

    def test_basel_3_1_factory_method(self):
        """basel_3_1() factory should create correct Basel 3.1 configuration."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 3, 31),
        )

        assert config.framework == RegulatoryFramework.BASEL_3_1
        assert config.is_crr is False
        assert config.is_basel_3_1 is True
        assert config.reporting_date == date(2027, 3, 31)

        # Check sub-configurations
        assert config.pd_floors.corporate == Decimal("0.0005")
        assert config.lgd_floors.unsecured == Decimal("0.25")
        assert config.supporting_factors.enabled is False
        assert config.output_floor.enabled is True

    def test_config_immutable(self):
        """CalculationConfig should be immutable (frozen dataclass)."""
        config = CalculationConfig.crr(reporting_date=date(2025, 1, 1))

        with pytest.raises(AttributeError):
            config.reporting_date = date(2026, 1, 1)

    def test_config_with_custom_irb_permissions(self):
        """Configuration should accept custom IRB permissions."""
        permissions = IRBPermissions.full_irb()
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31),
            irb_permissions=permissions,
        )

        assert config.irb_permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)

    def test_get_output_floor_percentage(self):
        """get_output_floor_percentage should use reporting date."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 6, 1),  # Should be 55%
        )

        assert config.get_output_floor_percentage() == Decimal("0.55")

    def test_crr_eur_gbp_rate_customizable(self):
        """CRR config should allow custom EUR/GBP rate."""
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31),
            eur_gbp_rate=Decimal("0.85"),
        )

        assert config.eur_gbp_rate == Decimal("0.85")
