"""
Unit tests for CIU treatment (Art. 132-132C).

Tests cover:
- Fallback approach: 1250% risk weight (Art. 132B)
- Look-through default: 250% risk weight (Art. 132)
- Mandate-based: uses ciu_mandate_rw (Art. 132A)
- Null approach: defaults to 250% (backward compatible)

References:
- CRR Art. 132: Look-through approach
- CRR Art. 132A: Mandate-based approach
- CRR Art. 132B: Fall-back approach (1250%)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from tests.fixtures.single_exposure import calculate_single_equity_exposure

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.engine.equity import EquityCalculator


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def equity_calculator() -> EquityCalculator:
    return EquityCalculator()


@pytest.fixture
def sa_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        irb_permissions=IRBPermissions.sa_only(),
    )


# =============================================================================
# CIU APPROACH TESTS
# =============================================================================


class TestCIUApproachSelection:
    """Test CIU approach-aware risk weight selection."""

    def test_fallback_1250_percent(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU with fallback approach gets 1250% RW (Art. 132B)."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
            ciu_approach="fallback",
        )
        assert result["risk_weight"] == pytest.approx(12.50)

    def test_look_through_250_percent(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU with look-through approach gets 250% RW."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
            ciu_approach="look_through",
        )
        assert result["risk_weight"] == pytest.approx(2.50)

    def test_mandate_based_uses_ciu_mandate_rw(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU with mandate-based approach uses ciu_mandate_rw column."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
            ciu_approach="mandate_based",
            ciu_mandate_rw=3.50,
        )
        assert result["risk_weight"] == pytest.approx(3.50)

    def test_mandate_based_no_rw_falls_to_1250(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU mandate-based with no ciu_mandate_rw falls back to 1250%."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
            ciu_approach="mandate_based",
        )
        assert result["risk_weight"] == pytest.approx(12.50)

    def test_null_approach_defaults_250_percent(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU with null approach defaults to 250% (backward compatible)."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
        )
        assert result["risk_weight"] == pytest.approx(2.50)

    def test_fallback_rwa_calculation(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU fallback RWA = EAD * 12.50."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
            ciu_approach="fallback",
        )
        assert result["rwa"] == pytest.approx(12_500_000.0)
