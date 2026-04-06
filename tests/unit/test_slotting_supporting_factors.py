"""
Unit tests for supporting factor application in slotting calculator.

Verifies that CRR Art. 501a infrastructure supporting factor (0.75) and
CRR Art. 501 SME supporting factor are applied to slotting exposures,
fixing P1.44 where slotting exposures silently missed these factors.

References:
    CRR Art. 501a: Infrastructure supporting factor (0.75)
    CRR Art. 501: SME supporting factor (tiered 0.7619/0.85)
    CRR Art. 153(5): Supervisory slotting approach
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.slotting import SlottingCalculator
from tests.fixtures.single_exposure import calculate_single_slotting_exposure


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR configuration with supporting factors enabled."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Basel 3.1 configuration with supporting factors disabled."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))


@pytest.fixture
def slotting_calculator() -> SlottingCalculator:
    """Create a slotting calculator."""
    return SlottingCalculator()


# =============================================================================
# INFRASTRUCTURE SUPPORTING FACTOR (Art. 501a) — SLOTTING
# =============================================================================


class TestSlottingInfrastructureSupportingFactor:
    """Infrastructure PF in slotting should receive 0.75 factor under CRR."""

    def test_infrastructure_pf_gets_0_75_factor(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Infrastructure PF exposure gets 0.75 supporting factor under CRR."""
        result = calculate_single_slotting_exposure(
            slotting_calculator,
            ead=Decimal("10000000"),
            category="strong",
            is_hvcre=False,
            is_infrastructure=True,
            config=crr_config,
        )
        assert result["supporting_factor"] == pytest.approx(0.75)

    def test_infrastructure_pf_rwa_reduced(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """RWA for infrastructure PF is reduced by 0.75 factor.

        Strong non-HVCRE >= 2.5yr: RW = 70%
        EAD = 10m, RWA_pre = 7m, RWA_post = 7m × 0.75 = 5.25m
        """
        result = calculate_single_slotting_exposure(
            slotting_calculator,
            ead=Decimal("10000000"),
            category="strong",
            is_hvcre=False,
            is_infrastructure=True,
            config=crr_config,
        )
        expected_rwa = 10_000_000.0 * 0.70 * 0.75
        assert result["rwa"] == pytest.approx(expected_rwa)

    def test_non_infrastructure_pf_no_reduction(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Non-infrastructure PF gets factor of 1.0 — no reduction."""
        result = calculate_single_slotting_exposure(
            slotting_calculator,
            ead=Decimal("10000000"),
            category="strong",
            is_hvcre=False,
            is_infrastructure=False,
            config=crr_config,
        )
        assert result["supporting_factor"] == pytest.approx(1.0)
        assert result["rwa"] == pytest.approx(10_000_000.0 * 0.70)

    def test_missing_infrastructure_column_defaults_no_reduction(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """When is_infrastructure column is absent, defaults to False (no factor)."""
        result = calculate_single_slotting_exposure(
            slotting_calculator,
            ead=Decimal("10000000"),
            category="strong",
            is_hvcre=False,
            config=crr_config,
        )
        assert result["supporting_factor"] == pytest.approx(1.0)

    def test_b31_no_infrastructure_factor(
        self,
        slotting_calculator: SlottingCalculator,
        b31_config: CalculationConfig,
    ) -> None:
        """Under Basel 3.1, supporting factors are disabled — factor is 1.0."""
        result = calculate_single_slotting_exposure(
            slotting_calculator,
            ead=Decimal("10000000"),
            category="strong",
            is_hvcre=False,
            is_infrastructure=True,
            config=b31_config,
        )
        assert result["supporting_factor"] == pytest.approx(1.0)

    def test_infrastructure_hvcre_gets_factor(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Infrastructure HVCRE also gets 0.75 factor.

        Strong HVCRE >= 2.5yr: RW = 95%
        RWA_pre = 10m × 0.95 = 9.5m, RWA_post = 9.5m × 0.75 = 7.125m
        """
        result = calculate_single_slotting_exposure(
            slotting_calculator,
            ead=Decimal("10000000"),
            category="strong",
            is_hvcre=True,
            is_infrastructure=True,
            config=crr_config,
        )
        assert result["supporting_factor"] == pytest.approx(0.75)
        assert result["rwa"] == pytest.approx(10_000_000.0 * 0.95 * 0.75)

    def test_infrastructure_weak_category(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Infrastructure factor applies regardless of slotting category.

        Weak non-HVCRE >= 2.5yr: RW = 250%
        RWA_pre = 10m × 2.50 = 25m, RWA_post = 25m × 0.75 = 18.75m
        """
        result = calculate_single_slotting_exposure(
            slotting_calculator,
            ead=Decimal("10000000"),
            category="weak",
            is_hvcre=False,
            is_infrastructure=True,
            config=crr_config,
        )
        assert result["supporting_factor"] == pytest.approx(0.75)
        assert result["rwa"] == pytest.approx(10_000_000.0 * 2.50 * 0.75)


# =============================================================================
# SME SUPPORTING FACTOR (Art. 501) — SLOTTING
# =============================================================================


class TestSlottingSMESupportingFactor:
    """SME exposures in slotting should receive tiered SME factor under CRR."""

    def test_sme_slotting_gets_factor(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SME PF with small drawn amount gets 0.7619 (tier 1) factor."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["SME_PF"],
                "ead": [1_000_000.0],
                "slotting_category": ["good"],
                "is_hvcre": [False],
                "sl_type": ["project_finance"],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
                "is_sme": [True],
                "is_infrastructure": [False],
                "drawn_amount": [1_000_000.0],
                "interest": [0.0],
            }
        )
        result = slotting_calculator.calculate_branch(lf, crr_config).collect()
        sf = result["supporting_factor"][0]
        assert sf == pytest.approx(0.7619)


# =============================================================================
# COMBINED FACTORS — min(SME, infrastructure)
# =============================================================================


class TestSlottingCombinedFactors:
    """When both SME and infrastructure apply, min() is used."""

    def test_both_sme_and_infrastructure_uses_min(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """min(0.7619, 0.75) = 0.75 — infrastructure wins."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["BOTH"],
                "ead": [500_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "sl_type": ["project_finance"],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
                "is_sme": [True],
                "is_infrastructure": [True],
                "drawn_amount": [500_000.0],
                "interest": [0.0],
            }
        )
        result = slotting_calculator.calculate_branch(lf, crr_config).collect()
        sf = result["supporting_factor"][0]
        # min(0.7619, 0.75) = 0.75
        assert sf == pytest.approx(0.75)


# =============================================================================
# MIXED BATCH — infrastructure and non-infrastructure in same batch
# =============================================================================


class TestSlottingMixedBatch:
    """Mixed batch: some exposures get factor, others don't."""

    def test_mixed_batch_independent_factors(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Each exposure gets its own supporting factor independently."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["INFRA_PF", "NORMAL_PF", "INFRA_IPRE"],
                "ead": [10_000_000.0, 10_000_000.0, 5_000_000.0],
                "slotting_category": ["strong", "strong", "good"],
                "is_hvcre": [False, False, False],
                "sl_type": ["project_finance", "project_finance", "ipre"],
                "is_short_maturity": [False, False, False],
                "is_pre_operational": [False, False, False],
                "is_infrastructure": [True, False, True],
            }
        )
        result = slotting_calculator.calculate_branch(lf, crr_config).collect()
        sfs = result["supporting_factor"].to_list()
        rwas = result["rwa"].to_list()

        # Infra PF: Strong 70% × 0.75 = 52.5% → 5.25m
        assert sfs[0] == pytest.approx(0.75)
        assert rwas[0] == pytest.approx(10_000_000.0 * 0.70 * 0.75)

        # Normal PF: Strong 70% × 1.0 = 70% → 7m
        assert sfs[1] == pytest.approx(1.0)
        assert rwas[1] == pytest.approx(10_000_000.0 * 0.70)

        # Infra IPRE: Good 90% × 0.75 = 67.5% → 3.375m
        assert sfs[2] == pytest.approx(0.75)
        assert rwas[2] == pytest.approx(5_000_000.0 * 0.90 * 0.75)


# =============================================================================
# EL UNAFFECTED BY SUPPORTING FACTOR
# =============================================================================


class TestSlottingELUnaffectedByFactor:
    """Supporting factors reduce RWA but NOT expected loss."""

    def test_el_unchanged_with_infrastructure_factor(
        self,
        slotting_calculator: SlottingCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Expected loss is computed on pre-factor basis (EL = el_rate × EAD)."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["INFRA"],
                "ead": [10_000_000.0],
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "sl_type": ["project_finance"],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
                "is_infrastructure": [True],
            }
        )
        result = slotting_calculator.calculate_branch(lf, crr_config).collect()

        # EL = 0.4% × 10m = 40,000 — unaffected by 0.75 factor
        assert result["expected_loss"][0] == pytest.approx(10_000_000.0 * 0.004)
        # But RWA is reduced
        assert result["rwa"][0] == pytest.approx(10_000_000.0 * 0.70 * 0.75)
