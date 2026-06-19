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
    OutputFloorConfig,
)
from rwa_calc.domain.enums import (
    ApproachType,
    ExposureClass,
    PermissionMode,
    RegulatoryFramework,
)


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

        # Check transitional percentages (PRA PS1/26 Art. 92(5))
        assert floor_config.get_floor_percentage(date(2027, 6, 1)) == Decimal("0.60")
        assert floor_config.get_floor_percentage(date(2028, 6, 1)) == Decimal("0.65")
        assert floor_config.get_floor_percentage(date(2029, 6, 1)) == Decimal("0.70")
        assert floor_config.get_floor_percentage(date(2030, 6, 1)) == Decimal("0.725")


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

        # Check sub-configurations
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
        assert config.output_floor.enabled is True

    def test_config_immutable(self):
        """CalculationConfig should be immutable (frozen dataclass)."""
        config = CalculationConfig.crr(reporting_date=date(2025, 1, 1))

        with pytest.raises(AttributeError):
            config.reporting_date = date(2026, 1, 1)  # ty: ignore[invalid-assignment]

    def test_config_with_irb_permission_mode(self):
        """Configuration should accept IRB permission mode."""
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31),
            permission_mode=PermissionMode.IRB,
        )

        assert config.permission_mode == PermissionMode.IRB

    def test_get_output_floor_percentage(self):
        """get_output_floor_percentage should use reporting date."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2028, 6, 1),  # Should be 65% (PRA Art. 92(5))
        )

        assert config.get_output_floor_percentage() == Decimal("0.65")

    def test_crr_eur_gbp_rate_customizable(self):
        """CRR config should allow custom EUR/GBP rate."""
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31),
            eur_gbp_rate=Decimal("0.85"),
        )

        assert config.eur_gbp_rate == Decimal("0.85")

    def test_sync_eur_gbp_rate_flag_defaults_true(self):
        """Auto-sync of eur_gbp_rate from fx_rates should be enabled by default."""
        crr_config = CalculationConfig.crr(reporting_date=date(2025, 12, 31))
        b31_config = CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))

        assert crr_config.sync_eur_gbp_rate_from_fx_table is True
        assert b31_config.sync_eur_gbp_rate_from_fx_table is True

    def test_with_fx_rate_updates_eur_gbp_rate(self):
        """with_fx_rate updates eur_gbp_rate (GBP thresholds now derive from the pack)."""
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31),
            eur_gbp_rate=Decimal("0.8732"),
        )

        new_config = config.with_fx_rate(Decimal("0.90"))

        assert new_config.eur_gbp_rate == Decimal("0.90")
        # Original config is untouched (frozen + replace returns a new instance)
        assert config.eur_gbp_rate == Decimal("0.8732")

    def test_with_fx_rate_noop_when_rate_unchanged(self):
        """with_fx_rate should return the same instance when rate matches."""
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31),
            eur_gbp_rate=Decimal("0.8732"),
        )

        assert config.with_fx_rate(Decimal("0.8732")) is config

    def test_with_fx_rate_noop_for_basel_3_1(self):
        """with_fx_rate should be a no-op for Basel 3.1 (GBP-native thresholds)."""
        config = CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))

        result = config.with_fx_rate(Decimal("0.90"))

        assert result is config
        assert result.eur_gbp_rate == config.eur_gbp_rate

    def test_with_fx_rate_preserves_post_init_derivations(self):
        """Replacing via with_fx_rate should re-run __post_init__ for irb_permissions."""
        config = CalculationConfig.crr(
            reporting_date=date(2025, 12, 31),
            permission_mode=PermissionMode.IRB,
            eur_gbp_rate=Decimal("0.8732"),
        )

        new_config = config.with_fx_rate(Decimal("0.90"))

        assert new_config.permission_mode == PermissionMode.IRB
        assert new_config.irb_permissions == config.irb_permissions
