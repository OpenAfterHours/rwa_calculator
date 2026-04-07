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

from rwa_calc.contracts.bundles import CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
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
    )


# =============================================================================
# CIU APPROACH TESTS
# =============================================================================


class TestCIUApproachSelection:
    """Test CIU approach-aware risk weight selection."""

    def test_fallback_150_percent(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU with fallback approach gets 150% RW under CRR (Art. 132(2))."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
            ciu_approach="fallback",
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_look_through_250_percent(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU with look-through approach defaults to 150% when RW not computed."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
            ciu_approach="look_through",
        )
        assert result["risk_weight"] == pytest.approx(1.50)

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

    def test_mandate_based_no_rw_falls_to_150(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU mandate-based with no ciu_mandate_rw falls back to 150% under CRR."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
            ciu_approach="mandate_based",
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_null_approach_defaults_250_percent(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU with null approach defaults to 150% (Art. 132(2) fallback)."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_fallback_rwa_calculation(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU fallback RWA = EAD * 1.50 under CRR (Art. 132(2))."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
            ciu_approach="fallback",
        )
        assert result["rwa"] == pytest.approx(1_500_000.0)


# =============================================================================
# MANDATE-BASED THIRD-PARTY FACTOR TESTS (Art. 132(4))
# =============================================================================


class TestCIUMandateBasedThirdParty:
    """Test 1.2x third-party factor for mandate-based approach."""

    def test_mandate_third_party_applies_1_2x_factor(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Third-party mandate calc applies 1.2x factor (Art. 132(4))."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
            ciu_approach="mandate_based",
            ciu_mandate_rw=3.50,
            ciu_third_party_calc=True,
        )
        assert result["risk_weight"] == pytest.approx(4.20)

    def test_mandate_own_calc_no_factor(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Own mandate calc has no 1.2x factor."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
            ciu_approach="mandate_based",
            ciu_mandate_rw=3.50,
            ciu_third_party_calc=False,
        )
        assert result["risk_weight"] == pytest.approx(3.50)

    def test_mandate_null_third_party_no_factor(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Null third_party_calc defaults to no 1.2x factor."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
            ciu_approach="mandate_based",
            ciu_mandate_rw=3.50,
        )
        assert result["risk_weight"] == pytest.approx(3.50)

    def test_third_party_flag_ignored_for_non_mandate(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Third-party flag has no effect on look-through approach."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
            ciu_approach="look_through",
            ciu_third_party_calc=True,
        )
        assert result["risk_weight"] == pytest.approx(1.50)

    def test_third_party_with_null_mandate_rw_uses_fallback(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Third-party with null mandate_rw uses 150% fallback * 1.2 = 180% under CRR."""
        result = calculate_single_equity_exposure(
            equity_calculator,
            ead=Decimal("1000000"),
            equity_type="ciu",
            config=sa_config,
            ciu_approach="mandate_based",
            ciu_third_party_calc=True,
        )
        assert result["risk_weight"] == pytest.approx(1.80)


# =============================================================================
# LOOK-THROUGH APPROACH TESTS (Art. 132)
# =============================================================================


def _make_look_through_bundle(
    equity_data: list[dict],
    holdings_data: list[dict] | None = None,
) -> CRMAdjustedBundle:
    """Helper to create a CRMAdjustedBundle with CIU look-through data."""
    equity_frame = pl.LazyFrame(equity_data)
    ciu_holdings = pl.LazyFrame(holdings_data) if holdings_data else None
    return CRMAdjustedBundle(
        exposures=pl.LazyFrame(),
        sa_exposures=pl.LazyFrame(),
        irb_exposures=pl.LazyFrame(),
        equity_exposures=equity_frame,
        ciu_holdings=ciu_holdings,
    )


class TestCIULookThrough:
    """Test CIU look-through approach risk weight resolution."""

    def test_single_holding_uses_holding_rw(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU with a single CORPORATE CQS3 holding uses that holding's RW."""
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_1",
                    "ead_final": 1_000_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_A",
                }
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_A",
                    "holding_reference": "H1",
                    "exposure_class": "CORPORATE",
                    "cqs": 3,
                    "holding_value": 1_000_000.0,
                }
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        row = result.results.collect().to_dicts()[0]
        # CRR CORPORATE CQS3 = 100%
        assert row["risk_weight"] == pytest.approx(1.00)

    def test_mixed_holdings_weighted_average(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU with mixed holdings gets value-weighted average RW."""
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_1",
                    "ead_final": 1_000_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_A",
                }
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_A",
                    "holding_reference": "H1",
                    "exposure_class": "CORPORATE",
                    "cqs": 1,
                    "holding_value": 600_000.0,
                },
                {
                    "fund_reference": "FUND_A",
                    "holding_reference": "H2",
                    "exposure_class": "CENTRAL_GOVT_CENTRAL_BANK",
                    "cqs": 1,
                    "holding_value": 400_000.0,
                },
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        row = result.results.collect().to_dicts()[0]
        # 60% * 0.20 (CORPORATE CQS1) + 40% * 0.00 (CGCB CQS1) = 0.12
        assert row["risk_weight"] == pytest.approx(0.12)

    def test_no_holdings_falls_back_to_250(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU with look_through but no matching holdings falls back to 150%."""
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_1",
                    "ead_final": 1_000_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_X",
                }
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_OTHER",
                    "holding_reference": "H1",
                    "exposure_class": "CORPORATE",
                    "cqs": 1,
                    "holding_value": 1_000_000.0,
                }
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        row = result.results.collect().to_dicts()[0]
        assert row["risk_weight"] == pytest.approx(1.50)

    def test_null_holdings_frame_falls_back(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """CIU with look_through and ciu_holdings=None falls back to 150%."""
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_1",
                    "ead_final": 1_000_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_A",
                }
            ],
            holdings_data=None,
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        row = result.results.collect().to_dicts()[0]
        assert row["risk_weight"] == pytest.approx(1.50)

    def test_unrated_holding_defaults_100(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Holding with unrated CQS (null) defaults to 100% RW."""
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_1",
                    "ead_final": 1_000_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_A",
                }
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_A",
                    "holding_reference": "H1",
                    "exposure_class": "CORPORATE",
                    "cqs": None,
                    "holding_value": 1_000_000.0,
                }
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        row = result.results.collect().to_dicts()[0]
        # CRR CORPORATE unrated = 100%
        assert row["risk_weight"] == pytest.approx(1.00)

    def test_multiple_funds_independent(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Two CIU exposures with different funds get independent effective RWs."""
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_1",
                    "ead_final": 1_000_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_A",
                },
                {
                    "exposure_reference": "CIU_2",
                    "ead_final": 500_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_B",
                },
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_A",
                    "holding_reference": "H1",
                    "exposure_class": "CENTRAL_GOVT_CENTRAL_BANK",
                    "cqs": 1,
                    "holding_value": 1_000_000.0,
                },
                {
                    "fund_reference": "FUND_B",
                    "holding_reference": "H2",
                    "exposure_class": "CORPORATE",
                    "cqs": 2,
                    "holding_value": 1_000_000.0,
                },
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        rows = result.results.collect().sort("exposure_reference").to_dicts()
        # FUND_A: 100% CGCB CQS1 = 0%
        assert rows[0]["risk_weight"] == pytest.approx(0.00)
        # FUND_B: 100% CORPORATE CQS2 = 50%
        assert rows[1]["risk_weight"] == pytest.approx(0.50)

    def test_non_look_through_ignores_holdings(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Mandate-based CIU ignores holdings data and uses mandate_rw."""
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_1",
                    "ead_final": 1_000_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "mandate_based",
                    "fund_reference": "FUND_A",
                    "ciu_mandate_rw": 3.50,
                }
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_A",
                    "holding_reference": "H1",
                    "exposure_class": "CENTRAL_GOVT_CENTRAL_BANK",
                    "cqs": 1,
                    "holding_value": 1_000_000.0,
                }
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        row = result.results.collect().to_dicts()[0]
        assert row["risk_weight"] == pytest.approx(3.50)

    def test_look_through_rwa_calculation(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Look-through RWA = EAD * effective_rw."""
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_1",
                    "ead_final": 2_000_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_A",
                }
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_A",
                    "holding_reference": "H1",
                    "exposure_class": "CORPORATE",
                    "cqs": 1,
                    "holding_value": 1_000_000.0,
                }
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        row = result.results.collect().to_dicts()[0]
        # CORPORATE CQS1 = 20%, RWA = 2M * 0.20 = 400K
        assert row["risk_weight"] == pytest.approx(0.20)
        assert row["rwa"] == pytest.approx(400_000.0)


# =============================================================================
# LEVERAGE ADJUSTMENT TESTS (Art. 132a(3))
# =============================================================================


class TestCIULeverageAdjustment:
    """Test CIU look-through leverage adjustment per Art. 132a(3).

    When a CIU is leveraged (total assets > NAV), the effective risk weight
    must be grossed up by dividing the weighted sum of underlying RWs by
    the fund's NAV rather than by total holding value. This prevents
    capital understatement for leveraged funds.
    """

    def test_leveraged_fund_doubles_effective_rw(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """2x leveraged fund: effective RW = 2 * underlying avg RW (Art. 132a(3))."""
        # Fund has 200K total assets (holdings) but only 100K NAV (2x leverage)
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_LEV",
                    "ead_final": 100_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_LEV",
                    "fund_nav": 100_000.0,
                }
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_LEV",
                    "holding_reference": "H1",
                    "exposure_class": "CORPORATE",
                    "cqs": 1,
                    "holding_value": 200_000.0,  # Total assets = 2x NAV
                }
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        row = result.results.collect().to_dicts()[0]
        # CORPORATE CQS1 = 20%, leverage = 200K/100K = 2x
        # effective_rw = (200K * 0.20) / 100K = 0.40 (40%)
        assert row["risk_weight"] == pytest.approx(0.40)
        assert row["rwa"] == pytest.approx(40_000.0)

    def test_unleveraged_fund_unchanged(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Unleveraged fund (NAV = total assets): same result as before."""
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_1",
                    "ead_final": 1_000_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_A",
                    "fund_nav": 1_000_000.0,  # NAV = total assets (no leverage)
                }
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_A",
                    "holding_reference": "H1",
                    "exposure_class": "CORPORATE",
                    "cqs": 1,
                    "holding_value": 1_000_000.0,
                }
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        row = result.results.collect().to_dicts()[0]
        # No leverage: effective_rw = (1M * 0.20) / 1M = 0.20
        assert row["risk_weight"] == pytest.approx(0.20)

    def test_null_fund_nav_backward_compatible(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """When fund_nav is null, falls back to sum(holding_value) — backward compat."""
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_1",
                    "ead_final": 1_000_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_A",
                    # No fund_nav — backward compatible
                }
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_A",
                    "holding_reference": "H1",
                    "exposure_class": "CORPORATE",
                    "cqs": 1,
                    "holding_value": 1_000_000.0,
                }
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        row = result.results.collect().to_dicts()[0]
        # Without fund_nav, uses total holding value as denominator = 20%
        assert row["risk_weight"] == pytest.approx(0.20)

    def test_missing_fund_nav_column_backward_compatible(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """When fund_nav column absent entirely, still backward compatible."""
        # Use the pre-existing test pattern (no fund_nav field at all)
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_1",
                    "ead_final": 1_000_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_A",
                }
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_A",
                    "holding_reference": "H1",
                    "exposure_class": "CORPORATE",
                    "cqs": 3,
                    "holding_value": 1_000_000.0,
                }
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        row = result.results.collect().to_dicts()[0]
        # CRR CORPORATE CQS3 = 100%, no leverage
        assert row["risk_weight"] == pytest.approx(1.00)

    def test_high_leverage_3x(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """3x leveraged fund: effective RW = 3 * underlying avg RW."""
        # Fund has 300K assets but 100K NAV (3x leverage)
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_3X",
                    "ead_final": 50_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_3X",
                    "fund_nav": 100_000.0,
                }
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_3X",
                    "holding_reference": "H1",
                    "exposure_class": "CORPORATE",
                    "cqs": 2,
                    "holding_value": 300_000.0,  # 3x NAV
                }
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        row = result.results.collect().to_dicts()[0]
        # CORPORATE CQS2 = 50%, leverage = 300K/100K = 3x
        # effective_rw = (300K * 0.50) / 100K = 1.50 (150%)
        assert row["risk_weight"] == pytest.approx(1.50)
        assert row["rwa"] == pytest.approx(75_000.0)  # 50K * 1.50

    def test_leveraged_mixed_holdings(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Leveraged fund with mixed holdings: leverage applied to weighted average."""
        # Fund NAV = 100K, total assets = 200K (2x leverage)
        # 60% CORPORATE CQS1 (20%) + 40% CGCB CQS1 (0%)
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_MIX",
                    "ead_final": 100_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_MIX",
                    "fund_nav": 100_000.0,
                }
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_MIX",
                    "holding_reference": "H1",
                    "exposure_class": "CORPORATE",
                    "cqs": 1,
                    "holding_value": 120_000.0,
                },
                {
                    "fund_reference": "FUND_MIX",
                    "holding_reference": "H2",
                    "exposure_class": "CENTRAL_GOVT_CENTRAL_BANK",
                    "cqs": 1,
                    "holding_value": 80_000.0,
                },
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        row = result.results.collect().to_dicts()[0]
        # weighted_sum = 120K * 0.20 + 80K * 0.00 = 24K
        # effective_rw = 24K / 100K (NAV) = 0.24 (24%)
        # Without leverage: 24K / 200K = 0.12 (12%) — understates by 2x
        assert row["risk_weight"] == pytest.approx(0.24)
        assert row["rwa"] == pytest.approx(24_000.0)

    def test_zero_fund_nav_uses_fallback(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """fund_nav=0 falls back to sum(holding_value) as denominator."""
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_0",
                    "ead_final": 100_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_0",
                    "fund_nav": 0.0,
                }
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_0",
                    "holding_reference": "H1",
                    "exposure_class": "CORPORATE",
                    "cqs": 1,
                    "holding_value": 100_000.0,
                }
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        row = result.results.collect().to_dicts()[0]
        # fund_nav=0 is invalid, falls back to total_value as denominator
        assert row["risk_weight"] == pytest.approx(0.20)

    def test_b31_leveraged_fund(
        self,
    ):
        """B31 leveraged fund uses same leverage mechanics with B31 RW tables."""
        b31_config = CalculationConfig.basel_3_1(
            reporting_date=date(2030, 6, 30),
        )
        calc = EquityCalculator()
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_B31",
                    "ead_final": 100_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_B31",
                    "fund_nav": 50_000.0,  # 2x leverage
                }
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_B31",
                    "holding_reference": "H1",
                    "exposure_class": "CORPORATE",
                    "cqs": 1,
                    "holding_value": 100_000.0,
                }
            ],
        )
        result = calc.get_equity_result_bundle(bundle, b31_config)
        row = result.results.collect().to_dicts()[0]
        # B31 CORPORATE CQS1 = 20%, leverage = 100K/50K = 2x
        # effective_rw = (100K * 0.20) / 50K = 0.40 (40%)
        assert row["risk_weight"] == pytest.approx(0.40)

    def test_multiple_funds_different_leverage(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Two CIU exposures to different funds with different leverage ratios."""
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_UNL",
                    "ead_final": 100_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_UNL",
                    "fund_nav": 100_000.0,  # 1x (no leverage)
                },
                {
                    "exposure_reference": "CIU_LEV",
                    "ead_final": 100_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_LEV",
                    "fund_nav": 50_000.0,  # 2x leverage
                },
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_UNL",
                    "holding_reference": "H1",
                    "exposure_class": "CORPORATE",
                    "cqs": 2,
                    "holding_value": 100_000.0,
                },
                {
                    "fund_reference": "FUND_LEV",
                    "holding_reference": "H2",
                    "exposure_class": "CORPORATE",
                    "cqs": 2,
                    "holding_value": 100_000.0,
                },
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        rows = result.results.collect().sort("exposure_reference").to_dicts()
        # FUND_LEV: CORPORATE CQS2 = 50%, leverage 2x → 100%
        assert rows[0]["risk_weight"] == pytest.approx(1.00)
        # FUND_UNL: CORPORATE CQS2 = 50%, no leverage → 50%
        assert rows[1]["risk_weight"] == pytest.approx(0.50)

    def test_negative_fund_nav_uses_total_value(
        self,
        equity_calculator: EquityCalculator,
        sa_config: CalculationConfig,
    ):
        """Negative fund_nav (distressed fund) falls back to total holding value."""
        bundle = _make_look_through_bundle(
            equity_data=[
                {
                    "exposure_reference": "CIU_NEG",
                    "ead_final": 100_000.0,
                    "equity_type": "ciu",
                    "ciu_approach": "look_through",
                    "fund_reference": "FUND_NEG",
                    "fund_nav": -50_000.0,  # Negative NAV
                }
            ],
            holdings_data=[
                {
                    "fund_reference": "FUND_NEG",
                    "holding_reference": "H1",
                    "exposure_class": "CORPORATE",
                    "cqs": 1,
                    "holding_value": 100_000.0,
                }
            ],
        )
        result = equity_calculator.get_equity_result_bundle(bundle, sa_config)
        row = result.results.collect().to_dicts()[0]
        # Negative NAV → falls back to total_value denominator
        assert row["risk_weight"] == pytest.approx(0.20)
