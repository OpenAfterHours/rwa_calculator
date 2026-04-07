"""
Unit tests for slotting expected loss rates (Art. 158(6) Table B).

Tests verify:
- CRR Table B EL rate constants match PRA Art. 158(6)
- B31 Table B EL rate constants match PRA PS1/26 Art. 158(6)
- Scalar lookup functions for both frameworks
- Polars namespace EL rate lookup (vectorised)
- EL computation in slotting calculator (expected_loss = el_rate × ead_final)
- EL shortfall/excess for slotting exposures
- Aggregator integration: slotting EL included in portfolio EL summary

References:
    CRR Art. 158(6), Table B: Expected loss rates for slotting exposures
    PRA PS1/26 Art. 158(6), Table B: Same structure, same values
    CRR Art. 62(d): T2 credit cap includes slotting RWA
    CRR Art. 159: EL shortfall/excess treatment
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

# Ensure slotting namespace is registered
import rwa_calc.engine.slotting.namespace  # noqa: F401
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.b31_slotting import (
    B31_SLOTTING_EL_RATES,
    B31_SLOTTING_EL_RATES_HVCRE,
    B31_SLOTTING_EL_RATES_SHORT,
    lookup_b31_slotting_el_rate,
)
from rwa_calc.data.tables.crr_slotting import (
    SLOTTING_EL_RATES,
    SLOTTING_EL_RATES_HVCRE,
    SLOTTING_EL_RATES_SHORT,
    lookup_slotting_el_rate,
)
from rwa_calc.domain.enums import SlottingCategory

# =============================================================================
# CRR Table B EL Rate Constants
# =============================================================================


class TestCRRSlottingELRates:
    """CRR Art. 158(6) Table B EL rates — non-HVCRE, >= 2.5yr."""

    def test_strong_zero_point_four_percent(self) -> None:
        assert SLOTTING_EL_RATES[SlottingCategory.STRONG] == Decimal("0.004")

    def test_good_zero_point_eight_percent(self) -> None:
        assert SLOTTING_EL_RATES[SlottingCategory.GOOD] == Decimal("0.008")

    def test_satisfactory_two_point_eight_percent(self) -> None:
        assert SLOTTING_EL_RATES[SlottingCategory.SATISFACTORY] == Decimal("0.028")

    def test_weak_eight_percent(self) -> None:
        assert SLOTTING_EL_RATES[SlottingCategory.WEAK] == Decimal("0.08")

    def test_default_fifty_percent(self) -> None:
        assert SLOTTING_EL_RATES[SlottingCategory.DEFAULT] == Decimal("0.50")

    def test_has_five_categories(self) -> None:
        assert len(SLOTTING_EL_RATES) == 5


class TestCRRSlottingELRatesShort:
    """CRR Art. 158(6) Table B EL rates — non-HVCRE, < 2.5yr."""

    def test_strong_zero_percent(self) -> None:
        """Strong short-maturity has 0% EL rate."""
        assert SLOTTING_EL_RATES_SHORT[SlottingCategory.STRONG] == Decimal("0.0")

    def test_good_zero_point_four_percent(self) -> None:
        assert SLOTTING_EL_RATES_SHORT[SlottingCategory.GOOD] == Decimal("0.004")

    def test_satisfactory_two_point_eight_percent(self) -> None:
        assert SLOTTING_EL_RATES_SHORT[SlottingCategory.SATISFACTORY] == Decimal("0.028")

    def test_weak_eight_percent(self) -> None:
        assert SLOTTING_EL_RATES_SHORT[SlottingCategory.WEAK] == Decimal("0.08")

    def test_default_fifty_percent(self) -> None:
        assert SLOTTING_EL_RATES_SHORT[SlottingCategory.DEFAULT] == Decimal("0.50")

    def test_strong_lower_than_long_maturity(self) -> None:
        """Short-maturity Strong (0%) < long-maturity Strong (0.4%)."""
        assert (
            SLOTTING_EL_RATES_SHORT[SlottingCategory.STRONG]
            < SLOTTING_EL_RATES[SlottingCategory.STRONG]
        )


class TestCRRSlottingELRatesHVCRE:
    """CRR Art. 158(6) Table B EL rates — HVCRE (flat, no maturity split)."""

    def test_hvcre_strong_zero_point_four(self) -> None:
        assert SLOTTING_EL_RATES_HVCRE[SlottingCategory.STRONG] == Decimal("0.004")

    def test_hvcre_good_zero_point_eight(self) -> None:
        assert SLOTTING_EL_RATES_HVCRE[SlottingCategory.GOOD] == Decimal("0.008")

    def test_hvcre_satisfactory_two_point_eight(self) -> None:
        assert SLOTTING_EL_RATES_HVCRE[SlottingCategory.SATISFACTORY] == Decimal("0.028")

    def test_hvcre_weak_eight_percent(self) -> None:
        assert SLOTTING_EL_RATES_HVCRE[SlottingCategory.WEAK] == Decimal("0.08")

    def test_hvcre_default_fifty_percent(self) -> None:
        assert SLOTTING_EL_RATES_HVCRE[SlottingCategory.DEFAULT] == Decimal("0.50")

    def test_hvcre_matches_long_maturity_non_hvcre(self) -> None:
        """HVCRE EL rates are same values as non-HVCRE long-maturity."""
        assert SLOTTING_EL_RATES_HVCRE == SLOTTING_EL_RATES


class TestCRRSlottingELRateLookup:
    """Scalar lookup function for CRR slotting EL rates."""

    def test_base_strong_by_string(self) -> None:
        assert lookup_slotting_el_rate("strong") == Decimal("0.004")

    def test_base_strong_by_enum(self) -> None:
        assert lookup_slotting_el_rate(SlottingCategory.STRONG) == Decimal("0.004")

    def test_short_maturity_strong(self) -> None:
        assert lookup_slotting_el_rate("strong", is_short_maturity=True) == Decimal("0.0")

    def test_hvcre_strong(self) -> None:
        assert lookup_slotting_el_rate("strong", is_hvcre=True) == Decimal("0.004")

    def test_hvcre_ignores_maturity(self) -> None:
        """HVCRE EL rates are flat — short and long maturity give same result."""
        assert lookup_slotting_el_rate(
            "good", is_hvcre=True, is_short_maturity=True
        ) == lookup_slotting_el_rate("good", is_hvcre=True, is_short_maturity=False)

    def test_unknown_category_defaults_to_satisfactory(self) -> None:
        assert lookup_slotting_el_rate("unknown") == Decimal("0.028")

    def test_case_insensitive(self) -> None:
        assert lookup_slotting_el_rate("STRONG") == Decimal("0.004")


# =============================================================================
# Basel 3.1 Table B EL Rate Constants
# =============================================================================


class TestB31SlottingELRates:
    """PRA PS1/26 Art. 158(6) Table B EL rates — non-HVCRE, >= 2.5yr."""

    def test_strong_zero_point_four_percent(self) -> None:
        assert B31_SLOTTING_EL_RATES[SlottingCategory.STRONG] == Decimal("0.004")

    def test_good_zero_point_eight_percent(self) -> None:
        assert B31_SLOTTING_EL_RATES[SlottingCategory.GOOD] == Decimal("0.008")

    def test_satisfactory_two_point_eight_percent(self) -> None:
        assert B31_SLOTTING_EL_RATES[SlottingCategory.SATISFACTORY] == Decimal("0.028")

    def test_weak_eight_percent(self) -> None:
        assert B31_SLOTTING_EL_RATES[SlottingCategory.WEAK] == Decimal("0.08")

    def test_default_fifty_percent(self) -> None:
        assert B31_SLOTTING_EL_RATES[SlottingCategory.DEFAULT] == Decimal("0.50")

    def test_matches_crr_rates(self) -> None:
        """B31 EL rates match CRR long-maturity rates (same PRA Table B)."""
        for cat in SlottingCategory:
            assert B31_SLOTTING_EL_RATES[cat] == SLOTTING_EL_RATES[cat]


class TestB31SlottingELRatesShort:
    """PRA PS1/26 Art. 158(6) Table B EL rates — non-HVCRE, < 2.5yr."""

    def test_strong_zero_percent(self) -> None:
        assert B31_SLOTTING_EL_RATES_SHORT[SlottingCategory.STRONG] == Decimal("0.0")

    def test_good_zero_point_four_percent(self) -> None:
        assert B31_SLOTTING_EL_RATES_SHORT[SlottingCategory.GOOD] == Decimal("0.004")


class TestB31SlottingELRatesHVCRE:
    """PRA PS1/26 Art. 158(6) Table B EL rates — HVCRE."""

    def test_hvcre_strong_zero_point_four(self) -> None:
        assert B31_SLOTTING_EL_RATES_HVCRE[SlottingCategory.STRONG] == Decimal("0.004")

    def test_hvcre_good_zero_point_eight(self) -> None:
        assert B31_SLOTTING_EL_RATES_HVCRE[SlottingCategory.GOOD] == Decimal("0.008")


class TestB31SlottingELRateLookup:
    """Scalar lookup function for B31 slotting EL rates."""

    def test_base_strong(self) -> None:
        assert lookup_b31_slotting_el_rate("strong") == Decimal("0.004")

    def test_short_maturity_strong(self) -> None:
        """B31 EL rates are maturity-dependent even though RW is not."""
        assert lookup_b31_slotting_el_rate("strong", is_short_maturity=True) == Decimal("0.0")

    def test_hvcre_strong(self) -> None:
        assert lookup_b31_slotting_el_rate("strong", is_hvcre=True) == Decimal("0.004")

    def test_unknown_defaults_to_satisfactory(self) -> None:
        assert lookup_b31_slotting_el_rate("unknown") == Decimal("0.028")


# =============================================================================
# Polars Namespace — EL Rate Lookup
# =============================================================================


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def basic_slotting_frame() -> pl.LazyFrame:
    """Frame with all five categories, non-HVCRE, long maturity."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3", "E4", "E5"],
            "slotting_category": ["strong", "good", "satisfactory", "weak", "default"],
            "is_hvcre": [False, False, False, False, False],
            "is_short_maturity": [False, False, False, False, False],
            "is_pre_operational": [False, False, False, False, False],
            "ead_final": [10_000_000.0, 10_000_000.0, 10_000_000.0, 10_000_000.0, 10_000_000.0],
        }
    )


class TestSlottingNamespaceELRateLookup:
    """Polars namespace EL rate lookup tests."""

    def test_crr_non_hvcre_long_maturity_el_rates(
        self, basic_slotting_frame: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """CRR non-HVCRE >= 2.5yr: Strong=0.4%, Good=0.8%, Satisfactory=2.8%, Weak=8%, Default=50%."""
        result = (
            basic_slotting_frame.slotting.prepare_columns(crr_config)
            .slotting.apply_slotting_weights(crr_config)
            .slotting.calculate_rwa()
            .slotting.apply_el_rates(crr_config)
        ).collect()

        el_rates = result["slotting_el_rate"].to_list()
        assert el_rates == pytest.approx([0.004, 0.008, 0.028, 0.08, 0.50])

    def test_crr_non_hvcre_short_maturity_el_rates(self, crr_config: CalculationConfig) -> None:
        """CRR non-HVCRE < 2.5yr: Strong=0%, Good=0.4%."""
        lf = pl.LazyFrame(
            {
                "slotting_category": ["strong", "good"],
                "is_hvcre": [False, False],
                "is_short_maturity": [True, True],
                "is_pre_operational": [False, False],
                "ead_final": [10_000_000.0, 10_000_000.0],
            }
        )
        result = (
            lf.slotting.prepare_columns(crr_config)
            .slotting.apply_slotting_weights(crr_config)
            .slotting.calculate_rwa()
            .slotting.apply_el_rates(crr_config)
        ).collect()

        el_rates = result["slotting_el_rate"].to_list()
        assert el_rates == pytest.approx([0.0, 0.004])

    def test_crr_hvcre_el_rates_flat(self, crr_config: CalculationConfig) -> None:
        """HVCRE EL rates are flat (same for short and long maturity)."""
        lf = pl.LazyFrame(
            {
                "slotting_category": ["strong", "strong"],
                "is_hvcre": [True, True],
                "is_short_maturity": [False, True],
                "is_pre_operational": [False, False],
                "ead_final": [10_000_000.0, 10_000_000.0],
            }
        )
        result = (
            lf.slotting.prepare_columns(crr_config)
            .slotting.apply_slotting_weights(crr_config)
            .slotting.calculate_rwa()
            .slotting.apply_el_rates(crr_config)
        ).collect()

        el_rates = result["slotting_el_rate"].to_list()
        assert el_rates[0] == pytest.approx(el_rates[1])  # flat
        assert el_rates[0] == pytest.approx(0.004)

    def test_b31_el_rates_are_maturity_dependent(self, b31_config: CalculationConfig) -> None:
        """B31 EL rates vary by maturity even though B31 risk weights do not."""
        lf = pl.LazyFrame(
            {
                "slotting_category": ["strong", "strong"],
                "is_hvcre": [False, False],
                "is_short_maturity": [False, True],
                "is_pre_operational": [False, False],
                "ead_final": [10_000_000.0, 10_000_000.0],
            }
        )
        result = (
            lf.slotting.prepare_columns(b31_config)
            .slotting.apply_slotting_weights(b31_config)
            .slotting.calculate_rwa()
            .slotting.apply_el_rates(b31_config)
        ).collect()

        el_rates = result["slotting_el_rate"].to_list()
        assert el_rates[0] == pytest.approx(0.004)  # long maturity
        assert el_rates[1] == pytest.approx(0.0)  # short maturity


# =============================================================================
# EL Computation (expected_loss = el_rate × ead_final)
# =============================================================================


class TestSlottingELComputation:
    """Tests that expected_loss = el_rate × ead_final."""

    def test_expected_loss_computed(
        self, basic_slotting_frame: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """EL = el_rate × EAD for each exposure."""
        result = (
            basic_slotting_frame.slotting.prepare_columns(crr_config)
            .slotting.apply_slotting_weights(crr_config)
            .slotting.calculate_rwa()
            .slotting.apply_el_rates(crr_config)
        ).collect()

        el = result["expected_loss"].to_list()
        ead = 10_000_000.0
        assert el[0] == pytest.approx(0.004 * ead)  # Strong: 40k
        assert el[1] == pytest.approx(0.008 * ead)  # Good: 80k
        assert el[2] == pytest.approx(0.028 * ead)  # Satisfactory: 280k
        assert el[3] == pytest.approx(0.08 * ead)  # Weak: 800k
        assert el[4] == pytest.approx(0.50 * ead)  # Default: 5m

    def test_strong_short_maturity_zero_el(self, crr_config: CalculationConfig) -> None:
        """Strong short-maturity has 0% EL rate, so expected_loss = 0."""
        lf = pl.LazyFrame(
            {
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "is_short_maturity": [True],
                "is_pre_operational": [False],
                "ead_final": [10_000_000.0],
            }
        )
        result = (
            lf.slotting.prepare_columns(crr_config)
            .slotting.apply_slotting_weights(crr_config)
            .slotting.calculate_rwa()
            .slotting.apply_el_rates(crr_config)
        ).collect()

        assert result["expected_loss"][0] == pytest.approx(0.0)
        assert result["slotting_el_rate"][0] == pytest.approx(0.0)

    def test_default_category_zero_rw_but_positive_el(self, crr_config: CalculationConfig) -> None:
        """Default category: 0% RW (K=0) but 50% EL rate — EL still computed."""
        lf = pl.LazyFrame(
            {
                "slotting_category": ["default"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
                "ead_final": [5_000_000.0],
            }
        )
        result = (
            lf.slotting.prepare_columns(crr_config)
            .slotting.apply_slotting_weights(crr_config)
            .slotting.calculate_rwa()
            .slotting.apply_el_rates(crr_config)
        ).collect()

        assert result["risk_weight"][0] == pytest.approx(0.0)  # K=0
        assert result["rwa"][0] == pytest.approx(0.0)  # RWA=0
        assert result["expected_loss"][0] == pytest.approx(2_500_000.0)  # 50% × 5m


# =============================================================================
# EL Shortfall/Excess
# =============================================================================


class TestSlottingELShortfallExcess:
    """EL shortfall/excess computation for slotting exposures."""

    def test_full_shortfall_no_provisions(self, crr_config: CalculationConfig) -> None:
        """Without provisions, full EL is shortfall."""
        lf = pl.LazyFrame(
            {
                "slotting_category": ["good"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
                "ead_final": [10_000_000.0],
            }
        )
        result = (
            lf.slotting.prepare_columns(crr_config)
            .slotting.apply_slotting_weights(crr_config)
            .slotting.calculate_rwa()
            .slotting.apply_el_rates(crr_config)
            .slotting.compute_el_shortfall_excess()
        ).collect()

        el = 0.008 * 10_000_000.0  # 80k
        assert result["el_shortfall"][0] == pytest.approx(el)
        assert result["el_excess"][0] == pytest.approx(0.0)

    def test_partial_shortfall_with_provisions(self, crr_config: CalculationConfig) -> None:
        """Provisions cover part of EL — shortfall is the remainder."""
        lf = pl.LazyFrame(
            {
                "slotting_category": ["good"],
                "is_hvcre": [False],
                "is_short_maturity": [False],
                "is_pre_operational": [False],
                "ead_final": [10_000_000.0],
                "provision_allocated": [50_000.0],
            }
        )
        result = (
            lf.slotting.prepare_columns(crr_config)
            .slotting.apply_slotting_weights(crr_config)
            .slotting.calculate_rwa()
            .slotting.apply_el_rates(crr_config)
            .slotting.compute_el_shortfall_excess()
        ).collect()

        el = 80_000.0  # 0.8% × 10m
        assert result["el_shortfall"][0] == pytest.approx(el - 50_000.0)  # 30k
        assert result["el_excess"][0] == pytest.approx(0.0)

    def test_excess_when_provisions_exceed_el(self, crr_config: CalculationConfig) -> None:
        """Provisions > EL — excess can be added to T2 capital."""
        lf = pl.LazyFrame(
            {
                "slotting_category": ["strong"],
                "is_hvcre": [False],
                "is_short_maturity": [True],  # 0% EL
                "is_pre_operational": [False],
                "ead_final": [10_000_000.0],
                "provision_allocated": [100_000.0],
            }
        )
        result = (
            lf.slotting.prepare_columns(crr_config)
            .slotting.apply_slotting_weights(crr_config)
            .slotting.calculate_rwa()
            .slotting.apply_el_rates(crr_config)
            .slotting.compute_el_shortfall_excess()
        ).collect()

        assert result["el_shortfall"][0] == pytest.approx(0.0)
        assert result["el_excess"][0] == pytest.approx(100_000.0)


# =============================================================================
# Full Pipeline via calculate_branch
# =============================================================================


class TestSlottingCalculatorBranchEL:
    """Slotting calculator calculate_branch produces EL columns."""

    def test_calculate_branch_produces_el_columns(
        self, basic_slotting_frame: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        from rwa_calc.engine.slotting import SlottingCalculator

        calc = SlottingCalculator()
        result = calc.calculate_branch(basic_slotting_frame, crr_config).collect()

        assert "expected_loss" in result.columns
        assert "slotting_el_rate" in result.columns
        assert "el_shortfall" in result.columns
        assert "el_excess" in result.columns

    def test_calculate_branch_el_values(
        self, basic_slotting_frame: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        from rwa_calc.engine.slotting import SlottingCalculator

        calc = SlottingCalculator()
        result = calc.calculate_branch(basic_slotting_frame, crr_config).collect()

        ead = 10_000_000.0
        expected_els = [0.004 * ead, 0.008 * ead, 0.028 * ead, 0.08 * ead, 0.50 * ead]
        actual_els = result["expected_loss"].to_list()
        for actual, expected in zip(actual_els, expected_els, strict=True):
            assert actual == pytest.approx(expected)

    def test_calculate_branch_b31_config(
        self, basic_slotting_frame: pl.LazyFrame, b31_config: CalculationConfig
    ) -> None:
        from rwa_calc.engine.slotting import SlottingCalculator

        calc = SlottingCalculator()
        result = calc.calculate_branch(basic_slotting_frame, b31_config).collect()

        # B31 long-maturity EL rates same as CRR long-maturity
        ead = 10_000_000.0
        assert result["expected_loss"][0] == pytest.approx(0.004 * ead)  # Strong

    def test_apply_all_includes_el(
        self, basic_slotting_frame: pl.LazyFrame, crr_config: CalculationConfig
    ) -> None:
        """apply_all() chains EL computation after RWA."""
        result = basic_slotting_frame.slotting.apply_all(crr_config).collect()

        assert "expected_loss" in result.columns
        assert "el_shortfall" in result.columns
        assert "el_excess" in result.columns


# =============================================================================
# Aggregator Integration — Slotting EL in Portfolio Summary
# =============================================================================


class TestSlottingELAggregatorIntegration:
    """Verify slotting EL feeds into portfolio EL summary."""

    def test_slotting_el_included_in_portfolio_summary(self) -> None:
        from rwa_calc.engine.aggregator._el_summary import compute_el_portfolio_summary

        irb_results = pl.LazyFrame(
            {
                "expected_loss": [100_000.0],
                "provision_allocated": [80_000.0],
                "el_shortfall": [20_000.0],
                "el_excess": [0.0],
                "rwa_final": [1_000_000.0],
            }
        )
        slotting_results = pl.LazyFrame(
            {
                "expected_loss": [50_000.0],
                "provision_allocated": [30_000.0],
                "el_shortfall": [20_000.0],
                "el_excess": [0.0],
                "rwa_final": [500_000.0],
            }
        )

        summary = compute_el_portfolio_summary(irb_results, slotting_results)
        assert summary is not None
        assert float(summary.total_expected_loss) == pytest.approx(150_000.0)  # 100k + 50k
        assert float(summary.total_el_shortfall) == pytest.approx(40_000.0)  # 20k + 20k
        assert float(summary.total_irb_rwa) == pytest.approx(1_500_000.0)  # 1m + 500k
        assert float(summary.t2_credit_cap) == pytest.approx(1_500_000.0 * 0.006)  # 0.6% of combined

    def test_slotting_only_el_summary(self) -> None:
        """When only slotting has EL, portfolio summary still works."""
        from rwa_calc.engine.aggregator._el_summary import compute_el_portfolio_summary

        slotting_results = pl.LazyFrame(
            {
                "expected_loss": [80_000.0],
                "el_shortfall": [80_000.0],
                "el_excess": [0.0],
                "rwa_final": [7_000_000.0],
            }
        )

        summary = compute_el_portfolio_summary(None, slotting_results)
        assert summary is not None
        assert float(summary.total_expected_loss) == pytest.approx(80_000.0)
        assert float(summary.total_el_shortfall) == pytest.approx(80_000.0)
        assert float(summary.total_irb_rwa) == pytest.approx(7_000_000.0)
        assert float(summary.t2_credit_cap) == pytest.approx(7_000_000.0 * 0.006)

    def test_no_slotting_el_backward_compatible(self) -> None:
        """Old-style call without slotting still works."""
        from rwa_calc.engine.aggregator._el_summary import compute_el_portfolio_summary

        irb_results = pl.LazyFrame(
            {
                "expected_loss": [100_000.0],
                "el_shortfall": [100_000.0],
                "el_excess": [0.0],
                "rwa_final": [1_000_000.0],
            }
        )

        summary = compute_el_portfolio_summary(irb_results)
        assert summary is not None
        assert float(summary.total_expected_loss) == pytest.approx(100_000.0)

    def test_slotting_excess_increases_t2_credit(self) -> None:
        """Slotting provisions excess contributes to T2 credit."""
        from rwa_calc.engine.aggregator._el_summary import compute_el_portfolio_summary

        slotting_results = pl.LazyFrame(
            {
                "expected_loss": [40_000.0],
                "provision_allocated": [100_000.0],
                "el_shortfall": [0.0],
                "el_excess": [60_000.0],
                "rwa_final": [7_000_000.0],
            }
        )

        summary = compute_el_portfolio_summary(None, slotting_results)
        assert summary is not None
        assert float(summary.total_el_excess) == pytest.approx(60_000.0)
        t2_cap = 7_000_000.0 * 0.006  # 42k
        assert float(summary.t2_credit) == pytest.approx(min(60_000.0, t2_cap))


# =============================================================================
# Parametrized — All categories × maturity × HVCRE
# =============================================================================


@pytest.mark.parametrize(
    "category,is_hvcre,is_short,expected_rate",
    [
        ("strong", False, False, 0.004),
        ("strong", False, True, 0.0),
        ("strong", True, False, 0.004),
        ("strong", True, True, 0.004),  # HVCRE flat
        ("good", False, False, 0.008),
        ("good", False, True, 0.004),
        ("good", True, False, 0.008),
        ("satisfactory", False, False, 0.028),
        ("satisfactory", False, True, 0.028),
        ("weak", False, False, 0.08),
        ("weak", False, True, 0.08),
        ("default", False, False, 0.50),
        ("default", False, True, 0.50),
    ],
)
def test_crr_el_rate_parametrized(
    category: str,
    is_hvcre: bool,
    is_short: bool,
    expected_rate: float,
    crr_config: CalculationConfig,
) -> None:
    """Parametrized: verify all CRR EL rate lookups via namespace."""
    lf = pl.LazyFrame(
        {
            "slotting_category": [category],
            "is_hvcre": [is_hvcre],
            "is_short_maturity": [is_short],
            "is_pre_operational": [False],
            "ead_final": [1_000_000.0],
        }
    )
    result = (
        lf.slotting.prepare_columns(crr_config)
        .slotting.apply_slotting_weights(crr_config)
        .slotting.calculate_rwa()
        .slotting.apply_el_rates(crr_config)
    ).collect()

    assert result["slotting_el_rate"][0] == pytest.approx(expected_rate)
    assert result["expected_loss"][0] == pytest.approx(expected_rate * 1_000_000.0)
