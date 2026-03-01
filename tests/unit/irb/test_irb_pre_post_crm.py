"""
Unit tests for IRB Pre/Post CRM attribute tracking.

Tests the implementation of Tasks 4.2-4.6 from the pre-post-crm-counterparty-plan:
- IRB calculator pre-CRM tracking
- IRB-specific reporting attributes
- F-IRB vs A-IRB distinction
- Non-beneficial guarantee handling
"""

from datetime import date

import polars as pl
import pytest

import rwa_calc.engine.irb.namespace  # noqa: F401 - Register namespace
from rwa_calc.contracts.config import CalculationConfig


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Create CRR configuration for tests."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


class TestIRBPreCRMTracking:
    """Tests for Task 4.2: IRB Calculator pre-CRM tracking."""

    def test_firb_guarantee_preserves_irb_original_rwa(self, crr_config: CalculationConfig) -> None:
        """F-IRB should preserve rwa_irb_original before guarantee substitution."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [500_000.0],  # Original IRB RWA
                "risk_weight": [0.50],  # Original IRB RW
                "guaranteed_portion": [1_000_000.0],
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["sovereign"],
                "guarantor_cqs": [1],  # 0% RW
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        # Original IRB values should be preserved
        assert result["rwa_irb_original"][0] == pytest.approx(500_000.0)
        assert result["risk_weight_irb_original"][0] == pytest.approx(0.50)
        # Pre-CRM columns should also be set
        assert result["pre_crm_risk_weight"][0] == pytest.approx(0.50)
        assert result["pre_crm_rwa"][0] == pytest.approx(500_000.0)

    def test_firb_guarantee_uses_sa_rw_for_guarantor(self, crr_config: CalculationConfig) -> None:
        """F-IRB guaranteed portion should use guarantor's SA risk weight."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [500_000.0],  # Original 50% RW
                "risk_weight": [0.50],
                "guaranteed_portion": [1_000_000.0],  # Fully guaranteed
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["sovereign"],
                "guarantor_cqs": [1],  # CQS 1 sovereign = 0%
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        # Guarantee is beneficial (0% < 50%)
        assert result["is_guarantee_beneficial"][0] is True
        assert result["guarantor_rw"][0] == pytest.approx(0.0)
        # Final RWA should be 0 (fully guaranteed by CQS 1 sovereign)
        assert result["rwa"][0] == pytest.approx(0.0)


class TestIRBGuaranteeBeneficialCheck:
    """Tests for Task 4.6: Non-beneficial guarantee handling."""

    def test_non_beneficial_guarantee_not_applied(self, crr_config: CalculationConfig) -> None:
        """Guarantee should not be applied if guarantor RW >= borrower RW."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.001],  # Very low PD
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [100_000.0],  # IRB RWA = 10% RW
                "risk_weight": [0.10],  # Low IRB RW due to good credit
                "guaranteed_portion": [1_000_000.0],
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["institution"],
                "guarantor_cqs": [2],  # UK: 30% RW, higher than borrower's 10%
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        # Guarantee is NOT beneficial (30% > 10%)
        assert result["is_guarantee_beneficial"][0] is False
        # RWA should remain at original value (not substituted)
        assert result["rwa"][0] == pytest.approx(100_000.0)
        # Status should indicate non-beneficial
        assert result["guarantee_status"][0] == "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"

    def test_non_beneficial_guarantee_status_tracked(self, crr_config: CalculationConfig) -> None:
        """guarantee_status should be GUARANTEE_NOT_APPLIED_NON_BENEFICIAL when skipped."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.001],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [50_000.0],  # IRB RWA = 5% RW
                "risk_weight": [0.05],  # Very low IRB RW
                "guaranteed_portion": [1_000_000.0],
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["corporate"],
                "guarantor_cqs": [3],  # 100% RW, much higher than borrower's 5%
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        assert result["guarantee_status"][0] == "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"
        assert result["is_guarantee_beneficial"][0] is False
        # Original RW preserved
        assert result["rwa"][0] == pytest.approx(50_000.0)

    def test_beneficial_guarantee_applied(self, crr_config: CalculationConfig) -> None:
        """Guarantee should be applied when guarantor RW < borrower RW."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.05],  # High PD
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [800_000.0],  # IRB RWA = 80% RW
                "risk_weight": [0.80],  # High IRB RW
                "guaranteed_portion": [1_000_000.0],
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["institution"],
                "guarantor_cqs": [1],  # 20% RW, lower than borrower's 80%
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        # Guarantee IS beneficial (20% < 80%)
        assert result["is_guarantee_beneficial"][0] is True
        assert result["guarantee_status"][0] == "SA_RW_SUBSTITUTION"
        # RWA should be reduced to 20% RW
        assert result["rwa"][0] == pytest.approx(200_000.0)


class TestIRBGuaranteeMethodTracking:
    """Tests for guarantee method tracking."""

    def test_irb_guarantee_method_tracked(self, crr_config: CalculationConfig) -> None:
        """guarantee_method_used column should indicate which method was applied."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [500_000.0],
                "risk_weight": [0.50],
                "guaranteed_portion": [1_000_000.0],
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["sovereign"],
                "guarantor_cqs": [1],
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        assert "guarantee_method_used" in result.columns
        assert result["guarantee_method_used"][0] == "SA_RW_SUBSTITUTION"

    def test_no_guarantee_method_tracked_as_no_substitution(
        self, crr_config: CalculationConfig
    ) -> None:
        """No guarantee should result in NO_SUBSTITUTION method."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [500_000.0],
                "risk_weight": [0.50],
                "guaranteed_portion": [0.0],  # No guarantee
                "unguaranteed_portion": [1_000_000.0],
                "guarantor_entity_type": [None],
                "guarantor_cqs": [None],
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        assert result["guarantee_method_used"][0] == "NO_SUBSTITUTION"
        assert result["guarantee_status"][0] == "NO_GUARANTEE"


class TestIRBPartialGuarantee:
    """Tests for partial guarantee handling."""

    def test_partial_guarantee_blends_rwa(self, crr_config: CalculationConfig) -> None:
        """Partial guarantee should blend IRB RWA with SA RWA proportionally."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [500_000.0],  # 50% IRB RW
                "risk_weight": [0.50],
                "guaranteed_portion": [600_000.0],  # 60% guaranteed
                "unguaranteed_portion": [400_000.0],  # 40% unguaranteed
                "guarantor_entity_type": ["sovereign"],
                "guarantor_cqs": [1],  # 0% RW for guarantor
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        # Guarantee is beneficial
        assert result["is_guarantee_beneficial"][0] is True

        # Blended RWA calculation:
        # Unguaranteed portion: 500k * (400k/1m) = 200k IRB RWA
        # Guaranteed portion: 600k * 0% = 0
        # Total: 200k
        assert result["rwa"][0] == pytest.approx(200_000.0)

    def test_partial_guarantee_rw_benefit_calculated(self, crr_config: CalculationConfig) -> None:
        """Guarantee benefit should be calculated for partial guarantees."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "pd": [0.01],
                "lgd": [0.45],
                "ead_final": [1_000_000.0],
                "maturity": [2.5],
                "exposure_class": ["CORPORATE"],
                "rwa": [500_000.0],
                "risk_weight": [0.50],
                "guaranteed_portion": [1_000_000.0],
                "unguaranteed_portion": [0.0],
                "guarantor_entity_type": ["sovereign"],
                "guarantor_cqs": [1],  # 0% RW
            }
        )

        result = lf.irb.apply_guarantee_substitution(crr_config).collect()

        # RW benefit = original RW (50%) - new RW (0%) = 50%
        assert result["guarantee_benefit_rw"][0] == pytest.approx(0.50)
