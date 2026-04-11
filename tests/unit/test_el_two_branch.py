"""
Unit tests for Art. 159(3) two-branch EL shortfall/excess comparison.

Art. 159(3) requires that when non-defaulted EL exceeds non-defaulted provisions
(A > B) AND defaulted provisions exceed defaulted EL (D > C) simultaneously,
shortfall and excess must be computed separately for each pool. The defaulted
excess must NOT offset the non-defaulted shortfall.

Tests cover:
- Two-branch condition triggering (non-defaulted shortfall + defaulted excess)
- Non-triggering scenarios (only one pool has shortfall/excess)
- CET1/T2 deduction with two-branch rule
- T2 credit with two-branch rule
- Backward compatibility (no is_defaulted column)
- Pool-level breakdown fields on ELPortfolioSummary

References:
- CRR Art. 159(3): Two-branch no-cross-offset rule
- CRR Art. 62(d): T2 credit cap (0.6% of IRB RWA)
- CRR Art. 36(1)(d): CET1 deduction for EL shortfall
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.aggregator._el_summary import compute_el_portfolio_summary


class TestArt1593TwoBranch:
    """Art. 159(3) two-branch EL shortfall/excess comparison."""

    def test_two_branch_triggered_non_defaulted_shortfall_and_defaulted_excess(self) -> None:
        """When non-defaulted has shortfall AND defaulted has excess, pools don't cross-offset.

        Non-defaulted: EL=50k, prov=30k → shortfall=20k
        Defaulted: EL=10k, prov=40k → excess=30k

        Without Art. 159(3): net shortfall=20k, net excess=30k (excess offsets)
        With Art. 159(3): effective shortfall=20k (non-defaulted only),
                          effective excess=30k (defaulted only) — no cross-offset
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["ND_001", "ND_002", "DEF_001"],
                "approach_applied": ["FIRB", "FIRB", "FIRB"],
                "rwa_post_factor": [3_000_000.0, 2_000_000.0, 1_000_000.0],
                "expected_loss": [30_000.0, 20_000.0, 10_000.0],
                "provision_allocated": [20_000.0, 10_000.0, 40_000.0],
                "el_shortfall": [10_000.0, 10_000.0, 0.0],
                "el_excess": [0.0, 0.0, 30_000.0],
                "is_defaulted": [False, False, True],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert result.art_159_3_applies is True
        assert float(result.non_defaulted_el_shortfall) == pytest.approx(20_000.0)
        assert float(result.non_defaulted_el_excess) == pytest.approx(0.0)
        assert float(result.defaulted_el_shortfall) == pytest.approx(0.0)
        assert float(result.defaulted_el_excess) == pytest.approx(30_000.0)
        # Effective values: no cross-offset
        assert float(result.total_el_shortfall) == pytest.approx(20_000.0)
        assert float(result.total_el_excess) == pytest.approx(30_000.0)

    def test_two_branch_cet1_t2_deductions_use_non_defaulted_shortfall_only(self) -> None:
        """CET1/T2 deductions should be based on non-defaulted shortfall when 159(3) applies.

        Non-defaulted: shortfall=40k
        Defaulted: excess=100k
        Deductions: CET1=40k (100% to CET1 per Art. 36(1)(d)), T2=0
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["ND_001", "DEF_001"],
                "approach_applied": ["FIRB", "FIRB"],
                "rwa_post_factor": [5_000_000.0, 5_000_000.0],
                "expected_loss": [100_000.0, 20_000.0],
                "provision_allocated": [60_000.0, 120_000.0],
                "el_shortfall": [40_000.0, 0.0],
                "el_excess": [0.0, 100_000.0],
                "is_defaulted": [False, True],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert result.art_159_3_applies is True
        assert float(result.cet1_deduction) == pytest.approx(40_000.0)
        assert float(result.t2_deduction) == pytest.approx(0.0)

    def test_two_branch_t2_credit_uses_defaulted_excess_only(self) -> None:
        """T2 credit should use defaulted excess (not combined) when 159(3) applies.

        Non-defaulted: shortfall=15k, excess=0
        Defaulted: shortfall=0, excess=25k
        RWA=10M → T2 cap = 60k
        T2 credit = min(25k, 60k) = 25k (defaulted excess only)
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["ND_001", "DEF_001"],
                "approach_applied": ["FIRB", "FIRB"],
                "rwa_post_factor": [6_000_000.0, 4_000_000.0],
                "expected_loss": [50_000.0, 5_000.0],
                "provision_allocated": [35_000.0, 30_000.0],
                "el_shortfall": [15_000.0, 0.0],
                "el_excess": [0.0, 25_000.0],
                "is_defaulted": [False, True],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert result.art_159_3_applies is True
        assert float(result.t2_credit) == pytest.approx(25_000.0)
        assert float(result.t2_credit_cap) == pytest.approx(60_000.0)


class TestArt1593NotTriggered:
    """Scenarios where Art. 159(3) two-branch rule does NOT apply."""

    def test_all_non_defaulted_shortfall_no_two_branch(self) -> None:
        """Pure non-defaulted portfolio with shortfall — standard combined approach."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["ND_001", "ND_002"],
                "approach_applied": ["FIRB", "FIRB"],
                "rwa_post_factor": [5_000_000.0, 3_000_000.0],
                "expected_loss": [50_000.0, 30_000.0],
                "provision_allocated": [30_000.0, 10_000.0],
                "el_shortfall": [20_000.0, 20_000.0],
                "el_excess": [0.0, 0.0],
                "is_defaulted": [False, False],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert result.art_159_3_applies is False
        assert float(result.total_el_shortfall) == pytest.approx(40_000.0)
        assert float(result.total_el_excess) == pytest.approx(0.0)

    def test_all_defaulted_excess_no_two_branch(self) -> None:
        """Pure defaulted portfolio with excess — standard combined approach."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["DEF_001", "DEF_002"],
                "approach_applied": ["FIRB", "FIRB"],
                "rwa_post_factor": [3_000_000.0, 2_000_000.0],
                "expected_loss": [10_000.0, 5_000.0],
                "provision_allocated": [40_000.0, 25_000.0],
                "el_shortfall": [0.0, 0.0],
                "el_excess": [30_000.0, 20_000.0],
                "is_defaulted": [True, True],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert result.art_159_3_applies is False
        assert float(result.total_el_excess) == pytest.approx(50_000.0)
        assert float(result.total_el_shortfall) == pytest.approx(0.0)

    def test_both_pools_have_shortfall_no_two_branch(self) -> None:
        """Both defaulted and non-defaulted have shortfall — no cross-offset issue.

        Non-defaulted: shortfall=20k
        Defaulted: shortfall=10k
        Combined: shortfall=30k (standard approach, no excess to offset)
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["ND_001", "DEF_001"],
                "approach_applied": ["FIRB", "FIRB"],
                "rwa_post_factor": [5_000_000.0, 3_000_000.0],
                "expected_loss": [50_000.0, 30_000.0],
                "provision_allocated": [30_000.0, 20_000.0],
                "el_shortfall": [20_000.0, 10_000.0],
                "el_excess": [0.0, 0.0],
                "is_defaulted": [False, True],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert result.art_159_3_applies is False
        assert float(result.total_el_shortfall) == pytest.approx(30_000.0)

    def test_both_pools_have_excess_no_two_branch(self) -> None:
        """Both defaulted and non-defaulted have excess — no cross-offset issue."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["ND_001", "DEF_001"],
                "approach_applied": ["FIRB", "FIRB"],
                "rwa_post_factor": [5_000_000.0, 3_000_000.0],
                "expected_loss": [10_000.0, 5_000.0],
                "provision_allocated": [40_000.0, 30_000.0],
                "el_shortfall": [0.0, 0.0],
                "el_excess": [30_000.0, 25_000.0],
                "is_defaulted": [False, True],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert result.art_159_3_applies is False
        assert float(result.total_el_excess) == pytest.approx(55_000.0)

    def test_non_defaulted_excess_defaulted_shortfall_no_two_branch(self) -> None:
        """Non-defaulted has excess, defaulted has shortfall — opposite of 159(3) trigger.

        This is the reverse scenario: non-defaulted over-provisioned, defaulted
        under-provisioned. Art. 159(3) does NOT apply in this direction.
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["ND_001", "DEF_001"],
                "approach_applied": ["FIRB", "FIRB"],
                "rwa_post_factor": [5_000_000.0, 3_000_000.0],
                "expected_loss": [10_000.0, 30_000.0],
                "provision_allocated": [40_000.0, 20_000.0],
                "el_shortfall": [0.0, 10_000.0],
                "el_excess": [30_000.0, 0.0],
                "is_defaulted": [False, True],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert result.art_159_3_applies is False
        assert float(result.total_el_shortfall) == pytest.approx(10_000.0)
        assert float(result.total_el_excess) == pytest.approx(30_000.0)


class TestArt1593BackwardCompatibility:
    """Backward compatibility when is_defaulted column is absent."""

    def test_no_is_defaulted_column_treats_all_as_non_defaulted(self) -> None:
        """Without is_defaulted column, all exposures are non-defaulted.

        This is the conservative treatment: no defaulted excess can offset shortfall.
        Art. 159(3) cannot trigger because defaulted pool is always empty.
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "approach_applied": ["FIRB", "AIRB"],
                "rwa_post_factor": [5_000_000.0, 3_000_000.0],
                "expected_loss": [50_000.0, 30_000.0],
                "provision_allocated": [30_000.0, 10_000.0],
                "el_shortfall": [20_000.0, 20_000.0],
                "el_excess": [0.0, 0.0],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert result.art_159_3_applies is False
        assert float(result.total_el_shortfall) == pytest.approx(40_000.0)
        assert float(result.non_defaulted_el_shortfall) == pytest.approx(40_000.0)
        assert float(result.defaulted_el_shortfall) == pytest.approx(0.0)
        assert float(result.defaulted_el_excess) == pytest.approx(0.0)

    def test_mixed_shortfall_excess_without_is_defaulted(self) -> None:
        """Mixed portfolio without is_defaulted — standard combined approach."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002", "EXP003"],
                "approach_applied": ["FIRB", "AIRB", "FIRB"],
                "rwa_post_factor": [4_000_000.0, 3_000_000.0, 3_000_000.0],
                "expected_loss": [50_000.0, 10_000.0, 20_000.0],
                "provision_allocated": [30_000.0, 40_000.0, 50_000.0],
                "el_shortfall": [20_000.0, 0.0, 0.0],
                "el_excess": [0.0, 30_000.0, 30_000.0],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert result.art_159_3_applies is False
        # All treated as non-defaulted
        assert float(result.non_defaulted_el_shortfall) == pytest.approx(20_000.0)
        assert float(result.non_defaulted_el_excess) == pytest.approx(60_000.0)
        # Standard combined approach: shortfall=20k, excess=60k
        assert float(result.total_el_shortfall) == pytest.approx(20_000.0)
        assert float(result.total_el_excess) == pytest.approx(60_000.0)

    def test_null_is_defaulted_defaults_to_non_defaulted(self) -> None:
        """Null is_defaulted values should be treated as non-defaulted (conservative)."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "approach_applied": ["FIRB", "FIRB"],
                "rwa_post_factor": [5_000_000.0, 3_000_000.0],
                "expected_loss": [50_000.0, 10_000.0],
                "provision_allocated": [30_000.0, 40_000.0],
                "el_shortfall": [20_000.0, 0.0],
                "el_excess": [0.0, 30_000.0],
                "is_defaulted": [None, None],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert result.art_159_3_applies is False
        assert float(result.non_defaulted_el_shortfall) == pytest.approx(20_000.0)
        assert float(result.non_defaulted_el_excess) == pytest.approx(30_000.0)
        assert float(result.defaulted_el_shortfall) == pytest.approx(0.0)
        assert float(result.defaulted_el_excess) == pytest.approx(0.0)


class TestArt1593PoolBreakdown:
    """Tests for the pool-level breakdown fields on ELPortfolioSummary."""

    def test_pool_breakdown_fields_populated(self) -> None:
        """All four pool breakdown fields should be populated correctly."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["ND_001", "ND_002", "DEF_001", "DEF_002"],
                "approach_applied": ["FIRB", "FIRB", "FIRB", "FIRB"],
                "rwa_post_factor": [3_000_000.0, 2_000_000.0, 1_500_000.0, 500_000.0],
                "expected_loss": [30_000.0, 25_000.0, 8_000.0, 12_000.0],
                "provision_allocated": [20_000.0, 15_000.0, 20_000.0, 5_000.0],
                "el_shortfall": [10_000.0, 10_000.0, 0.0, 7_000.0],
                "el_excess": [0.0, 0.0, 12_000.0, 0.0],
                "is_defaulted": [False, False, True, True],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert float(result.non_defaulted_el_shortfall) == pytest.approx(20_000.0)
        assert float(result.non_defaulted_el_excess) == pytest.approx(0.0)
        assert float(result.defaulted_el_shortfall) == pytest.approx(7_000.0)
        assert float(result.defaulted_el_excess) == pytest.approx(12_000.0)

    def test_pool_rwa_totals_correct(self) -> None:
        """Total IRB RWA should be sum of both pools."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["ND_001", "DEF_001"],
                "approach_applied": ["FIRB", "FIRB"],
                "rwa_post_factor": [6_000_000.0, 4_000_000.0],
                "el_shortfall": [10_000.0, 0.0],
                "el_excess": [0.0, 20_000.0],
                "is_defaulted": [False, True],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert float(result.total_irb_rwa) == pytest.approx(10_000_000.0)

    def test_two_branch_with_t2_credit_capped(self) -> None:
        """T2 credit from defaulted excess should still respect the 0.6% cap.

        Defaulted excess = 100k, RWA = 5M → cap = 30k
        T2 credit = min(100k, 30k) = 30k
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["ND_001", "DEF_001"],
                "approach_applied": ["FIRB", "FIRB"],
                "rwa_post_factor": [3_000_000.0, 2_000_000.0],
                "expected_loss": [50_000.0, 10_000.0],
                "provision_allocated": [30_000.0, 110_000.0],
                "el_shortfall": [20_000.0, 0.0],
                "el_excess": [0.0, 100_000.0],
                "is_defaulted": [False, True],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert result.art_159_3_applies is True
        assert float(result.total_el_excess) == pytest.approx(100_000.0)
        assert float(result.t2_credit_cap) == pytest.approx(30_000.0)
        assert float(result.t2_credit) == pytest.approx(30_000.0)

    def test_two_branch_with_slotting_results(self) -> None:
        """Art. 159(3) should work across combined IRB + slotting portfolios.

        IRB non-defaulted: shortfall=15k
        Slotting defaulted: excess=25k
        Art. 159(3) applies across combined frame.
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["IRB_ND_001"],
                "approach_applied": ["FIRB"],
                "rwa_post_factor": [5_000_000.0],
                "expected_loss": [50_000.0],
                "provision_allocated": [35_000.0],
                "el_shortfall": [15_000.0],
                "el_excess": [0.0],
                "is_defaulted": [False],
            }
        )
        slotting = pl.LazyFrame(
            {
                "exposure_reference": ["SL_DEF_001"],
                "approach_applied": ["slotting"],
                "rwa_post_factor": [3_000_000.0],
                "expected_loss": [10_000.0],
                "provision_allocated": [35_000.0],
                "el_shortfall": [0.0],
                "el_excess": [25_000.0],
                "is_defaulted": [True],
            }
        )

        result = compute_el_portfolio_summary(irb, slotting)
        assert result is not None
        assert result.art_159_3_applies is True
        assert float(result.non_defaulted_el_shortfall) == pytest.approx(15_000.0)
        assert float(result.defaulted_el_excess) == pytest.approx(25_000.0)
        assert float(result.total_el_shortfall) == pytest.approx(15_000.0)
        assert float(result.total_el_excess) == pytest.approx(25_000.0)
        assert float(result.total_irb_rwa) == pytest.approx(8_000_000.0)


class TestArt1593CapitalImpact:
    """Tests demonstrating the capital impact of the two-branch rule.

    These tests compare what the result would be with and without Art. 159(3)
    to verify the rule prevents capital understatement.
    """

    def test_two_branch_prevents_capital_understatement(self) -> None:
        """Demonstrates that without Art. 159(3), shortfall would be understated.

        Non-defaulted: EL=80k, prov=30k → shortfall=50k
        Defaulted: EL=10k, prov=60k → excess=50k

        Without Art. 159(3): combined shortfall=50k, combined excess=50k
            → net shortfall=50k, net excess=50k (excess offsets in combined pool)
            This is the SAME as the two-branch result in this case, BUT...

        The critical scenario is when the combined approach would net to
        LOWER shortfall. With two-branch:
            effective shortfall = 50k (non-defaulted only)
            effective excess = 50k (defaulted only)
            CET1 deduction = 50k (100% to CET1 per Art. 36(1)(d))
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["ND_001", "ND_002", "DEF_001"],
                "approach_applied": ["FIRB", "FIRB", "FIRB"],
                "rwa_post_factor": [4_000_000.0, 4_000_000.0, 2_000_000.0],
                "expected_loss": [50_000.0, 30_000.0, 10_000.0],
                "provision_allocated": [20_000.0, 10_000.0, 60_000.0],
                "el_shortfall": [30_000.0, 20_000.0, 0.0],
                "el_excess": [0.0, 0.0, 50_000.0],
                "is_defaulted": [False, False, True],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert result.art_159_3_applies is True
        # Non-defaulted shortfall is not reduced by defaulted excess
        assert float(result.total_el_shortfall) == pytest.approx(50_000.0)
        assert float(result.cet1_deduction) == pytest.approx(50_000.0)
        assert float(result.t2_deduction) == pytest.approx(0.0)

    def test_two_branch_flag_false_when_no_cross_offset_possible(self) -> None:
        """When there's no defaulted excess, Art. 159(3) doesn't apply.

        All exposures are non-defaulted, so no defaulted pool exists.
        The standard combined approach gives the correct result.
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "approach_applied": ["FIRB", "FIRB"],
                "rwa_post_factor": [5_000_000.0, 3_000_000.0],
                "expected_loss": [50_000.0, 30_000.0],
                "provision_allocated": [30_000.0, 10_000.0],
                "el_shortfall": [20_000.0, 20_000.0],
                "el_excess": [0.0, 0.0],
                "is_defaulted": [False, False],
            }
        )

        result = compute_el_portfolio_summary(irb)
        assert result is not None
        assert result.art_159_3_applies is False
        assert float(result.total_el_shortfall) == pytest.approx(40_000.0)
        assert float(result.cet1_deduction) == pytest.approx(40_000.0)
        assert float(result.t2_deduction) == pytest.approx(0.0)
