"""Tests for permission mode configuration and approach selection.

Tests cover:
- PermissionMode enum values
- CalculationRequest permission_mode field
- RWAService._create_config() with permission modes
- CCF behavior under different approach selections (FIRB 75% vs SA 50%)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.api.models import CalculationRequest
from rwa_calc.api.service import RWAService
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode

# =============================================================================
# PermissionMode Enum Tests
# =============================================================================


class TestPermissionModeEnum:
    """Tests for PermissionMode enum values."""

    def test_enum_has_expected_values(self) -> None:
        """PermissionMode should have standardised and irb values."""
        assert PermissionMode.STANDARDISED.value == "standardised"
        assert PermissionMode.IRB.value == "irb"

    def test_enum_is_complete(self) -> None:
        """PermissionMode should have exactly 2 values."""
        assert len(PermissionMode) == 2


# =============================================================================
# CalculationConfig Permission Mode Tests
# =============================================================================


class TestCalculationConfigPermissionMode:
    """Tests for CalculationConfig __post_init__ derivation."""

    def test_standardised_derives_sa_only(self) -> None:
        """STANDARDISED mode should derive sa_only irb_permissions."""
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            permission_mode=PermissionMode.STANDARDISED,
        )
        assert not config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.FIRB
        )
        assert not config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.AIRB
        )

    def test_irb_derives_full_irb(self) -> None:
        """IRB mode should derive full_irb irb_permissions."""
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            permission_mode=PermissionMode.IRB,
        )
        assert config.irb_permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)
        assert config.irb_permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)

    def test_default_is_standardised(self) -> None:
        """Default permission_mode should be STANDARDISED."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        assert config.permission_mode == PermissionMode.STANDARDISED


# =============================================================================
# CalculationRequest Tests
# =============================================================================


class TestCalculationRequestPermissionMode:
    """Tests for CalculationRequest with permission_mode field."""

    def test_request_with_standardised(self) -> None:
        """CalculationRequest should accept permission_mode='standardised'."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            permission_mode="standardised",
        )
        assert request.permission_mode == "standardised"

    def test_request_with_irb(self) -> None:
        """CalculationRequest should accept permission_mode='irb'."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            permission_mode="irb",
        )
        assert request.permission_mode == "irb"

    def test_request_defaults_to_standardised(self) -> None:
        """CalculationRequest should default permission_mode to 'standardised'."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )
        assert request.permission_mode == "standardised"


# =============================================================================
# RWAService._create_config Tests
# =============================================================================


class TestServiceCreateConfig:
    """Tests for RWAService._create_config() with permission modes."""

    @pytest.fixture
    def service(self, tmp_path: Path) -> RWAService:
        """Return an RWAService instance."""
        return RWAService(cache_dir=tmp_path / "cache")

    def test_create_config_standardised(self, service: RWAService) -> None:
        """_create_config with 'standardised' should use sa_only permissions."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            permission_mode="standardised",
        )
        config = service._create_config(request)
        assert config.permission_mode == PermissionMode.STANDARDISED
        assert not config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.FIRB
        )

    def test_create_config_irb(self, service: RWAService) -> None:
        """_create_config with 'irb' should use full_irb permissions."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            permission_mode="irb",
        )
        config = service._create_config(request)
        assert config.permission_mode == PermissionMode.IRB
        assert config.irb_permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)
        assert config.irb_permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)

    def test_create_config_crr_framework(self, service: RWAService) -> None:
        """_create_config should create CRR config when framework='CRR'."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            permission_mode="irb",
        )
        config = service._create_config(request)
        assert config.is_crr

    def test_create_config_basel_3_1_framework(self, service: RWAService) -> None:
        """_create_config should create Basel 3.1 config when framework='BASEL_3_1'."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="BASEL_3_1",
            reporting_date=date(2027, 6, 30),
            permission_mode="irb",
        )
        config = service._create_config(request)
        assert config.is_basel_3_1


# =============================================================================
# CCF Calculator Integration Tests
# =============================================================================


class TestCCFCalculatorIntegration:
    """Integration tests for CCF calculation with different approach permissions.

    These tests verify the CCF values for MR risk_type under different approaches:
    - SA: 50% CCF
    - FIRB: 75% CCF
    - AIRB with ccf_modelled: Use modelled value
    - AIRB without ccf_modelled: Fall back to SA (50%)
    """

    @pytest.fixture
    def ccf_calculator(self):
        """Return a CCFCalculator instance."""
        from rwa_calc.engine.ccf import CCFCalculator

        return CCFCalculator()

    @pytest.fixture
    def crr_config_irb(self) -> CalculationConfig:
        """Return CRR config with IRB mode."""
        return CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            permission_mode=PermissionMode.IRB,
        )

    def test_firb_mr_exposure_gets_75_percent_ccf(
        self,
        ccf_calculator,
        crr_config_irb: CalculationConfig,
    ) -> None:
        """FIRB exposure with MR risk_type should get 75% CCF."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_MR_001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1000000.0],
                "risk_type": ["MR"],
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config_irb).collect()

        assert result["ccf"][0] == pytest.approx(0.75)
        assert result["ead_from_ccf"][0] == pytest.approx(750000.0)

    def test_sa_mr_exposure_gets_50_percent_ccf(
        self,
        ccf_calculator,
        crr_config_irb: CalculationConfig,
    ) -> None:
        """SA exposure with MR risk_type should get 50% CCF."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["SA_MR_001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1000000.0],
                "risk_type": ["MR"],
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config_irb).collect()

        assert result["ccf"][0] == pytest.approx(0.50)
        assert result["ead_from_ccf"][0] == pytest.approx(500000.0)

    def test_airb_with_ccf_modelled_uses_modelled_value(
        self,
        ccf_calculator,
        crr_config_irb: CalculationConfig,
    ) -> None:
        """AIRB exposure with ccf_modelled should use the modelled CCF."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_MODELLED_001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1000000.0],
                "risk_type": ["MR"],
                "ccf_modelled": [0.65],
                "approach": ["advanced_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config_irb).collect()

        assert result["ccf"][0] == pytest.approx(0.65)
        assert result["ead_from_ccf"][0] == pytest.approx(650000.0)

    def test_airb_without_ccf_modelled_falls_back_to_sa(
        self,
        ccf_calculator,
        crr_config_irb: CalculationConfig,
    ) -> None:
        """AIRB exposure without ccf_modelled should fall back to SA CCF."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["AIRB_NO_MODEL_001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1000000.0],
                "risk_type": ["MR"],
                "ccf_modelled": [None],
                "approach": ["advanced_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config_irb).collect()

        assert result["ccf"][0] == pytest.approx(0.50)
        assert result["ead_from_ccf"][0] == pytest.approx(500000.0)

    def test_firb_mlr_exposure_gets_75_percent_ccf(
        self,
        ccf_calculator,
        crr_config_irb: CalculationConfig,
    ) -> None:
        """FIRB exposure with MLR risk_type should get 75% CCF."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["FIRB_MLR_001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1000000.0],
                "risk_type": ["MLR"],
                "approach": ["foundation_irb"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config_irb).collect()

        assert result["ccf"][0] == pytest.approx(0.75)
        assert result["ead_from_ccf"][0] == pytest.approx(750000.0)

    def test_sa_mlr_exposure_gets_20_percent_ccf(
        self,
        ccf_calculator,
        crr_config_irb: CalculationConfig,
    ) -> None:
        """SA exposure with MLR risk_type should get 20% CCF."""
        exposures = pl.DataFrame(
            {
                "exposure_reference": ["SA_MLR_001"],
                "drawn_amount": [0.0],
                "nominal_amount": [1000000.0],
                "risk_type": ["MLR"],
                "approach": ["standardised"],
            }
        ).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config_irb).collect()

        assert result["ccf"][0] == pytest.approx(0.20)
        assert result["ead_from_ccf"][0] == pytest.approx(200000.0)
