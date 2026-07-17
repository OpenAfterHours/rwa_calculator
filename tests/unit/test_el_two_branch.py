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
        """Mixed portfolio without is_defaulted — pool-aggregate netting (P1.221).

        Single (non-defaulted) pool: A = sum(EL) = 50k+10k+20k = 80,000;
        B = sum(pool_b) = 30k+40k+50k = 120,000. Art. 159(3) compares the
        POOL AGGREGATE, not the per-row-then-summed el_shortfall/el_excess
        columns: nd_shortfall = max(0, 80k-120k) = 0; nd_excess =
        max(0, 120k-80k) = 40,000. The buggy per-row-then-sum path instead
        reports shortfall=20,000 (from EXP001 alone) and excess=60,000 (from
        EXP002+EXP003), which never nets EXP001's shortfall against its
        siblings' excess within the same pool.
        """
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
        assert float(result.non_defaulted_el_shortfall) == pytest.approx(0.0)
        assert float(result.non_defaulted_el_excess) == pytest.approx(40_000.0)
        # Pool-aggregate netting: shortfall=0, excess=40k (A=80k vs B=120k)
        assert float(result.total_el_shortfall) == pytest.approx(0.0)
        assert float(result.total_el_excess) == pytest.approx(40_000.0)

    def test_null_is_defaulted_defaults_to_non_defaulted(self) -> None:
        """Null is_defaulted values should be treated as non-defaulted (conservative).

        Pool-aggregate netting (P1.221): A = 50k+10k = 60,000; B = 30k+40k =
        70,000 -> nd_shortfall = max(0, 60k-70k) = 0; nd_excess =
        max(0, 70k-60k) = 10,000. The buggy per-row-then-sum path instead
        reports shortfall=20,000/excess=30,000 (EXP001's shortfall never nets
        against EXP002's excess within the same non-defaulted pool).
        """
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
        assert float(result.non_defaulted_el_shortfall) == pytest.approx(0.0)
        assert float(result.non_defaulted_el_excess) == pytest.approx(10_000.0)
        assert float(result.defaulted_el_shortfall) == pytest.approx(0.0)
        assert float(result.defaulted_el_excess) == pytest.approx(0.0)


class TestArt1593PoolBreakdown:
    """Tests for the pool-level breakdown fields on ELPortfolioSummary."""

    def test_pool_breakdown_fields_populated(self) -> None:
        """All four pool breakdown fields should be populated correctly.

        Pool-aggregate netting (P1.221) on the defaulted pool: C = 8k+12k =
        20,000; D = 20k+5k = 25,000 -> d_shortfall = max(0, 20k-25k) = 0;
        d_excess = max(0, 25k-20k) = 5,000. The buggy per-row-then-sum path
        instead reports shortfall=7,000/excess=12,000 (DEF_001's excess
        never nets against DEF_002's shortfall within the same defaulted
        pool). Non-defaulted pool is single-sign (both rows shortfall) so
        pool-aggregate == per-row-sum there and stays 20,000/0.
        """
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
        assert float(result.defaulted_el_shortfall) == pytest.approx(0.0)
        assert float(result.defaulted_el_excess) == pytest.approx(5_000.0)

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


class TestP1221PoolAggregateNetting:
    """P1.221: Art. 159(3) EL-vs-provision netting compares POOL AGGREGATES.

    Bug: ``adjustments.py`` floors shortfall/excess per row (max(0, EL_i -
    pool_b_i)) before ``_el_summary.py`` sums those already-floored values
    per default-status pool, so one row's excess never offsets a sibling
    row's shortfall inside the same pool. Art. 159(3) requires the
    comparison on aggregate pool totals: nd_shortfall = max(0, sum(EL) -
    sum(pool_b)), not sum(max(0, EL_i - pool_b_i)).

    References:
    - CRR Art. 159(3): pool-level netting, not per-row-then-sum
    - CRR Art. 36(1)(d): CET1 deduction of shortfall (100%)
    - CRR Art. 62(d): T2 credit for excess (capped at 0.6% of IRB RWA)
    """

    def test_p1221_a_single_pool_mixed_sign_nets_at_pool_level(self) -> None:
        """P1.221-A: 3 non-defaulted exposures, mixed sign — must net at pool level.

        E1: EL=60,000, prov=20,000 -> per-row shortfall=40,000
        E2: EL=10,000, prov=50,000 -> per-row excess=40,000
        E3: EL=20,000, prov=25,000 -> per-row excess=5,000

        Pool aggregate: A=90,000, B=95,000 -> nd_shortfall=max(0,90k-95k)=0;
        nd_excess=max(0,95k-90k)=5,000. The buggy per-row-then-sum path
        instead reports shortfall=40,000 and excess=45,000 — this test pins
        the correct pool-aggregate answer, which the bug cannot produce.
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2", "E3"],
                "approach_applied": ["AIRB", "AIRB", "AIRB"],
                "rwa_post_factor": [20_000_000.0, 20_000_000.0, 20_000_000.0],
                "expected_loss": [60_000.0, 10_000.0, 20_000.0],
                "provision_allocated": [20_000.0, 50_000.0, 25_000.0],
                "el_shortfall": [40_000.0, 0.0, 0.0],
                "el_excess": [0.0, 40_000.0, 5_000.0],
                "is_defaulted": [False, False, False],
            }
        )

        result = compute_el_portfolio_summary(irb)

        assert result is not None
        assert float(result.total_expected_loss) == pytest.approx(90_000.0)
        assert float(result.total_provisions_allocated) == pytest.approx(95_000.0)
        assert float(result.total_pool_b) == pytest.approx(95_000.0)
        assert float(result.non_defaulted_el_shortfall) == pytest.approx(0.0)
        assert float(result.non_defaulted_el_excess) == pytest.approx(5_000.0)
        assert float(result.defaulted_el_shortfall) == pytest.approx(0.0)
        assert float(result.defaulted_el_excess) == pytest.approx(0.0)
        assert result.art_159_3_applies is False
        assert float(result.total_el_shortfall) == pytest.approx(0.0)
        assert float(result.total_el_excess) == pytest.approx(5_000.0)
        assert float(result.cet1_deduction) == pytest.approx(0.0)
        assert float(result.t2_credit) == pytest.approx(5_000.0)
        assert float(result.t2_deduction) == pytest.approx(0.0)

    def test_p1221_b_two_branch_selector_uses_pool_aggregate_inputs(self) -> None:
        """P1.221-B: the two-branch selector (Art. 159(3)) must trigger off
        pool aggregates, not the per-row-then-sum values it reads today.

        Non-defaulted: N1 EL=50k/prov=20k, N2 EL=30k/prov=40k
            -> A=80k, B=60k -> nd_shortfall=20,000, nd_excess=0
        Defaulted: D1 EL=8k/prov=25k, D2 EL=12k/prov=5k
            -> C=20k, D=30k -> d_shortfall=0, d_excess=10,000

        art_159_3_applies = (nd_shortfall>0) and (d_excess>0) = True -> split
        branch: effective_shortfall = nd_shortfall = 20,000; effective_excess
        = d_excess = 10,000. total_irb_rwa = 10,000,000 -> cap = 60,000 ->
        t2_credit = min(10k, 60k) = 10,000.

        The buggy per-row-then-sum path instead reports
        non_defaulted_el_shortfall=30,000 / non_defaulted_el_excess=10,000
        and defaulted_el_shortfall=7,000 / defaulted_el_excess=17,000,
        over-stating both the CET1 deduction and the T2 credit.
        """
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["N1", "N2", "D1", "D2"],
                "approach_applied": ["AIRB", "AIRB", "AIRB", "AIRB"],
                "rwa_post_factor": [4_000_000.0, 3_000_000.0, 2_000_000.0, 1_000_000.0],
                "expected_loss": [50_000.0, 30_000.0, 8_000.0, 12_000.0],
                "provision_allocated": [20_000.0, 40_000.0, 25_000.0, 5_000.0],
                "el_shortfall": [30_000.0, 0.0, 0.0, 7_000.0],
                "el_excess": [0.0, 10_000.0, 17_000.0, 0.0],
                "is_defaulted": [False, False, True, True],
            }
        )

        result = compute_el_portfolio_summary(irb)

        assert result is not None
        assert float(result.non_defaulted_el_shortfall) == pytest.approx(20_000.0)
        assert float(result.non_defaulted_el_excess) == pytest.approx(0.0)
        assert float(result.defaulted_el_shortfall) == pytest.approx(0.0)
        assert float(result.defaulted_el_excess) == pytest.approx(10_000.0)
        assert result.art_159_3_applies is True
        assert float(result.total_el_shortfall) == pytest.approx(20_000.0)
        assert float(result.total_el_excess) == pytest.approx(10_000.0)
        assert float(result.t2_credit_cap) == pytest.approx(60_000.0)
        assert float(result.t2_credit) == pytest.approx(10_000.0)
        assert float(result.cet1_deduction) == pytest.approx(20_000.0)
