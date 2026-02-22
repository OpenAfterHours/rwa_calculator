"""Integration tests for IRB approach selection.

Tests cover:
- CalculationRequest irb_approach field
- RWAService._create_config() with different approach selections
- CCF behavior under different approach selections (FIRB 75% vs SA 50%)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.api.models import CalculationRequest
from rwa_calc.api.service import RWAService
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import ApproachType, ExposureClass, IRBApproachOption


# =============================================================================
# IRBApproachOption Enum Tests
# =============================================================================


class TestIRBApproachOptionEnum:
    """Tests for IRBApproachOption enum values."""

    def test_enum_has_all_expected_values(self) -> None:
        """IRBApproachOption should have all expected values."""
        assert IRBApproachOption.SA_ONLY.value == "sa_only"
        assert IRBApproachOption.FIRB.value == "firb"
        assert IRBApproachOption.AIRB.value == "airb"
        assert IRBApproachOption.FULL_IRB.value == "full_irb"
        assert IRBApproachOption.RETAIL_AIRB_CORPORATE_FIRB.value == "retail_airb_corporate_firb"

    def test_enum_is_complete(self) -> None:
        """IRBApproachOption should have exactly 5 values."""
        assert len(IRBApproachOption) == 5


# =============================================================================
# CalculationRequest Tests
# =============================================================================


class TestCalculationRequestIRBApproach:
    """Tests for CalculationRequest with irb_approach field."""

    def test_request_with_irb_approach_sa_only(self) -> None:
        """CalculationRequest should accept irb_approach='sa_only'."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            irb_approach="sa_only",
        )
        assert request.irb_approach == "sa_only"

    def test_request_with_irb_approach_firb(self) -> None:
        """CalculationRequest should accept irb_approach='firb'."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            irb_approach="firb",
        )
        assert request.irb_approach == "firb"

    def test_request_with_irb_approach_airb(self) -> None:
        """CalculationRequest should accept irb_approach='airb'."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            irb_approach="airb",
        )
        assert request.irb_approach == "airb"

    def test_request_with_irb_approach_full_irb(self) -> None:
        """CalculationRequest should accept irb_approach='full_irb'."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            irb_approach="full_irb",
        )
        assert request.irb_approach == "full_irb"

    def test_request_irb_approach_defaults_to_none(self) -> None:
        """CalculationRequest should have irb_approach default to None."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )
        assert request.irb_approach is None



# =============================================================================
# RWAService._create_config Tests
# =============================================================================


class TestServiceCreateConfig:
    """Tests for RWAService._create_config() with different approach selections."""

    @pytest.fixture
    def service(self) -> RWAService:
        """Return an RWAService instance."""
        return RWAService()

    def test_create_config_sa_only(self, service: RWAService) -> None:
        """_create_config with irb_approach='sa_only' should use sa_only permissions."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            irb_approach="sa_only",
        )

        config = service._create_config(request)

        # SA only should not permit FIRB or AIRB for corporate
        assert not config.irb_permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)
        assert not config.irb_permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)

    def test_create_config_firb(self, service: RWAService) -> None:
        """_create_config with irb_approach='firb' should use firb_only permissions."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            irb_approach="firb",
        )

        config = service._create_config(request)

        # FIRB should be permitted for corporate
        assert config.irb_permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)
        # AIRB should NOT be permitted
        assert not config.irb_permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)
        # Retail should only have SA (FIRB not permitted for retail)
        assert not config.irb_permissions.is_permitted(
            ExposureClass.RETAIL_MORTGAGE, ApproachType.FIRB
        )

    def test_create_config_airb(self, service: RWAService) -> None:
        """_create_config with irb_approach='airb' should use airb_only permissions."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            irb_approach="airb",
        )

        config = service._create_config(request)

        # AIRB should be permitted for corporate
        assert config.irb_permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)
        # FIRB should NOT be permitted
        assert not config.irb_permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)
        # Retail should have AIRB
        assert config.irb_permissions.is_permitted(
            ExposureClass.RETAIL_MORTGAGE, ApproachType.AIRB
        )

    def test_create_config_full_irb(self, service: RWAService) -> None:
        """_create_config with irb_approach='full_irb' should use full_irb permissions."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            irb_approach="full_irb",
        )

        config = service._create_config(request)

        # Both FIRB and AIRB should be permitted for corporate
        assert config.irb_permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)
        assert config.irb_permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)

    def test_create_config_no_irb_approach_defaults_sa_only(self, service: RWAService) -> None:
        """_create_config with no irb_approach should default to sa_only."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
        )

        config = service._create_config(request)

        assert not config.irb_permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.FIRB)
        assert not config.irb_permissions.is_permitted(ExposureClass.CORPORATE, ApproachType.AIRB)

    def test_create_config_crr_framework(self, service: RWAService) -> None:
        """_create_config should create CRR config when framework='CRR'."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="CRR",
            reporting_date=date(2024, 12, 31),
            irb_approach="firb",
        )

        config = service._create_config(request)

        assert config.is_crr
        assert not config.is_basel_3_1

    def test_create_config_basel_3_1_framework(self, service: RWAService) -> None:
        """_create_config should create Basel 3.1 config when framework='BASEL_3_1'."""
        request = CalculationRequest(
            data_path="/test/path",
            framework="BASEL_3_1",
            reporting_date=date(2027, 6, 30),
            irb_approach="firb",
        )

        config = service._create_config(request)

        assert config.is_basel_3_1
        assert not config.is_crr


# =============================================================================
# CCF Behavior Tests with Different Approaches
# =============================================================================


class TestCCFWithApproachSelection:
    """Tests verifying CCF behavior under different IRB approach selections."""

    @pytest.fixture
    def crr_config_sa(self) -> CalculationConfig:
        """Return CRR config with SA only."""
        return CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            irb_permissions=IRBPermissions.sa_only(),
        )

    @pytest.fixture
    def crr_config_firb(self) -> CalculationConfig:
        """Return CRR config with FIRB only."""
        return CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            irb_permissions=IRBPermissions.firb_only(),
        )

    @pytest.fixture
    def crr_config_airb(self) -> CalculationConfig:
        """Return CRR config with AIRB only."""
        return CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            irb_permissions=IRBPermissions.airb_only(),
        )

    def test_firb_permits_firb_for_corporate(self, crr_config_firb: CalculationConfig) -> None:
        """FIRB config should permit FIRB for corporate exposures."""
        assert crr_config_firb.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.FIRB
        )

    def test_firb_not_permits_airb_for_corporate(self, crr_config_firb: CalculationConfig) -> None:
        """FIRB config should not permit AIRB for corporate exposures."""
        assert not crr_config_firb.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.AIRB
        )

    def test_airb_permits_airb_for_corporate(self, crr_config_airb: CalculationConfig) -> None:
        """AIRB config should permit AIRB for corporate exposures."""
        assert crr_config_airb.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.AIRB
        )

    def test_airb_not_permits_firb_for_corporate(self, crr_config_airb: CalculationConfig) -> None:
        """AIRB config should not permit FIRB for corporate exposures."""
        assert not crr_config_airb.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.FIRB
        )

    def test_sa_only_not_permits_any_irb(self, crr_config_sa: CalculationConfig) -> None:
        """SA only config should not permit any IRB approaches."""
        assert not crr_config_sa.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.FIRB
        )
        assert not crr_config_sa.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.AIRB
        )


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
    def crr_config_firb(self) -> CalculationConfig:
        """Return CRR config with FIRB only."""
        return CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            irb_permissions=IRBPermissions.firb_only(),
        )

    def test_firb_mr_exposure_gets_75_percent_ccf(
        self,
        ccf_calculator,
        crr_config_firb: CalculationConfig,
    ) -> None:
        """FIRB exposure with MR risk_type should get 75% CCF."""
        exposures = pl.DataFrame({
            "exposure_reference": ["FIRB_MR_001"],
            "drawn_amount": [0.0],
            "nominal_amount": [1000000.0],
            "risk_type": ["MR"],  # Medium risk
            "approach": ["foundation_irb"],  # FIRB approach
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config_firb).collect()

        # FIRB: MR should get 75% CCF per CRR Art. 166(8)
        assert result["ccf"][0] == pytest.approx(0.75)
        assert result["ead_from_ccf"][0] == pytest.approx(750000.0)

    def test_sa_mr_exposure_gets_50_percent_ccf(
        self,
        ccf_calculator,
        crr_config_firb: CalculationConfig,
    ) -> None:
        """SA exposure with MR risk_type should get 50% CCF."""
        exposures = pl.DataFrame({
            "exposure_reference": ["SA_MR_001"],
            "drawn_amount": [0.0],
            "nominal_amount": [1000000.0],
            "risk_type": ["MR"],  # Medium risk
            "approach": ["standardised"],  # SA approach
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config_firb).collect()

        # SA: MR should get 50% CCF per CRR Art. 111
        assert result["ccf"][0] == pytest.approx(0.50)
        assert result["ead_from_ccf"][0] == pytest.approx(500000.0)

    def test_airb_with_ccf_modelled_uses_modelled_value(
        self,
        ccf_calculator,
        crr_config_firb: CalculationConfig,
    ) -> None:
        """AIRB exposure with ccf_modelled should use the modelled CCF."""
        exposures = pl.DataFrame({
            "exposure_reference": ["AIRB_MODELLED_001"],
            "drawn_amount": [0.0],
            "nominal_amount": [1000000.0],
            "risk_type": ["MR"],
            "ccf_modelled": [0.65],  # Bank's own estimate
            "approach": ["advanced_irb"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config_firb).collect()

        # AIRB with ccf_modelled should use the modelled value (65%)
        assert result["ccf"][0] == pytest.approx(0.65)
        assert result["ead_from_ccf"][0] == pytest.approx(650000.0)

    def test_airb_without_ccf_modelled_falls_back_to_sa(
        self,
        ccf_calculator,
        crr_config_firb: CalculationConfig,
    ) -> None:
        """AIRB exposure without ccf_modelled should fall back to SA CCF."""
        exposures = pl.DataFrame({
            "exposure_reference": ["AIRB_NO_MODEL_001"],
            "drawn_amount": [0.0],
            "nominal_amount": [1000000.0],
            "risk_type": ["MR"],
            "ccf_modelled": [None],  # No modelled CCF
            "approach": ["advanced_irb"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config_firb).collect()

        # AIRB without ccf_modelled should fall back to SA (MR = 50%)
        assert result["ccf"][0] == pytest.approx(0.50)
        assert result["ead_from_ccf"][0] == pytest.approx(500000.0)

    def test_firb_mlr_exposure_gets_75_percent_ccf(
        self,
        ccf_calculator,
        crr_config_firb: CalculationConfig,
    ) -> None:
        """FIRB exposure with MLR risk_type should get 75% CCF."""
        exposures = pl.DataFrame({
            "exposure_reference": ["FIRB_MLR_001"],
            "drawn_amount": [0.0],
            "nominal_amount": [1000000.0],
            "risk_type": ["MLR"],  # Medium-low risk
            "approach": ["foundation_irb"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config_firb).collect()

        # FIRB: MLR should also get 75% CCF per CRR Art. 166(8)
        assert result["ccf"][0] == pytest.approx(0.75)
        assert result["ead_from_ccf"][0] == pytest.approx(750000.0)

    def test_sa_mlr_exposure_gets_20_percent_ccf(
        self,
        ccf_calculator,
        crr_config_firb: CalculationConfig,
    ) -> None:
        """SA exposure with MLR risk_type should get 20% CCF."""
        exposures = pl.DataFrame({
            "exposure_reference": ["SA_MLR_001"],
            "drawn_amount": [0.0],
            "nominal_amount": [1000000.0],
            "risk_type": ["MLR"],  # Medium-low risk
            "approach": ["standardised"],
        }).lazy()

        result = ccf_calculator.apply_ccf(exposures, crr_config_firb).collect()

        # SA: MLR should get 20% CCF
        assert result["ccf"][0] == pytest.approx(0.20)
        assert result["ead_from_ccf"][0] == pytest.approx(200000.0)
