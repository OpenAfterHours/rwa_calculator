"""
Tests for Art. 159(1) Pool B composition: AVA and other own funds reductions.

Art. 159(1) defines Pool B (the offset against expected loss) as:
    (a) General credit risk adjustments (GCRA)
    (b) Specific credit risk adjustments (SCRA) for non-defaulted
    (c) Additional value adjustments (AVAs per Art. 34)
    (d) Other own funds reductions

Previously, only (a+b) via ``provision_allocated`` were included.
These tests verify that (c) and (d) are now included in both the
per-exposure EL shortfall/excess computation and the portfolio-level
EL summary.

References:
    CRR Art. 159(1): Pool B composition
    CRR Art. 34, Art. 105: Additional value adjustments
    CRR Art. 62(d): T2 credit cap
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine.aggregator._el_summary import compute_el_portfolio_summary
from rwa_calc.engine.irb.adjustments import compute_el_shortfall_excess

# =============================================================================
# HELPERS
# =============================================================================


def _irb_frame(**overrides: object) -> pl.LazyFrame:
    """Build a minimal IRB exposure frame for EL testing."""
    defaults: dict[str, object] = {
        "exposure_reference": ["EXP_001"],
        "approach_applied": ["FIRB"],
        "rwa_post_factor": [1_000_000.0],
        "expected_loss": [10_000.0],
        "provision_allocated": [6_000.0],
        "ava_amount": [0.0],
        "other_own_funds_reductions": [0.0],
        "el_shortfall": [4_000.0],
        "el_excess": [0.0],
    }
    defaults.update(overrides)
    return pl.LazyFrame(defaults)


# =============================================================================
# PER-EXPOSURE: compute_el_shortfall_excess (IRB adjustments.py)
# =============================================================================


class TestPoolBIRBShortfallExcess:
    """Per-exposure EL shortfall/excess with AVA in Pool B."""

    def test_ava_reduces_shortfall(self) -> None:
        """AVA reduces EL shortfall: pool_b = prov + ava."""
        lf = pl.LazyFrame(
            {
                "expected_loss": [10_000.0],
                "provision_allocated": [6_000.0],
                "ava_amount": [2_000.0],
                "other_own_funds_reductions": [0.0],
            }
        )
        result = compute_el_shortfall_excess(lf).collect()
        # pool_b = 6000 + 2000 = 8000; shortfall = 10000 - 8000 = 2000
        assert result["el_shortfall"][0] == pytest.approx(2_000.0)
        assert result["el_excess"][0] == pytest.approx(0.0)

    def test_ava_eliminates_shortfall_creates_excess(self) -> None:
        """Large AVA can eliminate shortfall and create excess."""
        lf = pl.LazyFrame(
            {
                "expected_loss": [10_000.0],
                "provision_allocated": [6_000.0],
                "ava_amount": [5_000.0],
                "other_own_funds_reductions": [0.0],
            }
        )
        result = compute_el_shortfall_excess(lf).collect()
        # pool_b = 6000 + 5000 = 11000; excess = 11000 - 10000 = 1000
        assert result["el_shortfall"][0] == pytest.approx(0.0)
        assert result["el_excess"][0] == pytest.approx(1_000.0)

    def test_other_own_funds_reductions_reduces_shortfall(self) -> None:
        """Other own funds reductions reduce EL shortfall."""
        lf = pl.LazyFrame(
            {
                "expected_loss": [10_000.0],
                "provision_allocated": [6_000.0],
                "ava_amount": [0.0],
                "other_own_funds_reductions": [3_000.0],
            }
        )
        result = compute_el_shortfall_excess(lf).collect()
        # pool_b = 6000 + 3000 = 9000; shortfall = 10000 - 9000 = 1000
        assert result["el_shortfall"][0] == pytest.approx(1_000.0)
        assert result["el_excess"][0] == pytest.approx(0.0)

    def test_all_three_pool_b_components(self) -> None:
        """All three Pool B components sum correctly."""
        lf = pl.LazyFrame(
            {
                "expected_loss": [10_000.0],
                "provision_allocated": [4_000.0],
                "ava_amount": [3_000.0],
                "other_own_funds_reductions": [2_000.0],
            }
        )
        result = compute_el_shortfall_excess(lf).collect()
        # pool_b = 4000 + 3000 + 2000 = 9000; shortfall = 10000 - 9000 = 1000
        assert result["el_shortfall"][0] == pytest.approx(1_000.0)
        assert result["el_excess"][0] == pytest.approx(0.0)

    def test_missing_ava_column_backward_compat(self) -> None:
        """When ava_amount column absent, behaves as before (ava=0)."""
        lf = pl.LazyFrame(
            {
                "expected_loss": [10_000.0],
                "provision_allocated": [6_000.0],
            }
        )
        result = compute_el_shortfall_excess(lf).collect()
        # pool_b = 6000; shortfall = 10000 - 6000 = 4000
        assert result["el_shortfall"][0] == pytest.approx(4_000.0)
        assert result["el_excess"][0] == pytest.approx(0.0)

    def test_missing_other_ofr_column_backward_compat(self) -> None:
        """When other_own_funds_reductions column absent, behaves as before."""
        lf = pl.LazyFrame(
            {
                "expected_loss": [10_000.0],
                "provision_allocated": [6_000.0],
                "ava_amount": [2_000.0],
            }
        )
        result = compute_el_shortfall_excess(lf).collect()
        # pool_b = 6000 + 2000 = 8000; shortfall = 10000 - 8000 = 2000
        assert result["el_shortfall"][0] == pytest.approx(2_000.0)

    def test_null_ava_defaults_to_zero(self) -> None:
        """Null ava_amount is treated as zero (fill_null)."""
        lf = pl.LazyFrame(
            {
                "expected_loss": [10_000.0],
                "provision_allocated": [6_000.0],
                "ava_amount": [None],
                "other_own_funds_reductions": [0.0],
            },
            schema={
                "expected_loss": pl.Float64,
                "provision_allocated": pl.Float64,
                "ava_amount": pl.Float64,
                "other_own_funds_reductions": pl.Float64,
            },
        )
        result = compute_el_shortfall_excess(lf).collect()
        # Null AVA treated as 0; shortfall = 10000 - 6000 = 4000
        assert result["el_shortfall"][0] == pytest.approx(4_000.0)

    def test_mixed_batch_multiple_exposures(self) -> None:
        """Multiple exposures with varying Pool B composition."""
        lf = pl.LazyFrame(
            {
                "expected_loss": [10_000.0, 5_000.0, 3_000.0],
                "provision_allocated": [4_000.0, 6_000.0, 1_000.0],
                "ava_amount": [3_000.0, 0.0, 500.0],
                "other_own_funds_reductions": [1_000.0, 0.0, 0.0],
            }
        )
        result = compute_el_shortfall_excess(lf).collect()
        # Exp 1: pool_b=8000, shortfall=2000, excess=0
        assert result["el_shortfall"][0] == pytest.approx(2_000.0)
        assert result["el_excess"][0] == pytest.approx(0.0)
        # Exp 2: pool_b=6000, shortfall=0, excess=1000
        assert result["el_shortfall"][1] == pytest.approx(0.0)
        assert result["el_excess"][1] == pytest.approx(1_000.0)
        # Exp 3: pool_b=1500, shortfall=1500, excess=0
        assert result["el_shortfall"][2] == pytest.approx(1_500.0)
        assert result["el_excess"][2] == pytest.approx(0.0)

    def test_no_el_column_still_zero(self) -> None:
        """Without expected_loss column, shortfall/excess are zero regardless of AVA."""
        lf = pl.LazyFrame(
            {
                "provision_allocated": [6_000.0],
                "ava_amount": [2_000.0],
            }
        )
        result = compute_el_shortfall_excess(lf).collect()
        assert result["el_shortfall"][0] == pytest.approx(0.0)
        assert result["el_excess"][0] == pytest.approx(0.0)


# =============================================================================
# PORTFOLIO-LEVEL: compute_el_portfolio_summary
# =============================================================================


class TestPoolBPortfolioSummary:
    """Portfolio-level EL summary with AVA and other own funds reductions."""

    def test_ava_included_in_pool_b_total(self) -> None:
        """total_pool_b includes provisions + AVA + other_own_funds_reductions."""
        lf = _irb_frame(
            provision_allocated=[6_000.0],
            ava_amount=[2_000.0],
            other_own_funds_reductions=[1_000.0],
            expected_loss=[10_000.0],
            el_shortfall=[1_000.0],  # 10000 - (6000+2000+1000) = 1000
            el_excess=[0.0],
        )
        summary = compute_el_portfolio_summary(lf)
        assert summary is not None
        assert float(summary.total_provisions_allocated) == pytest.approx(6_000.0)
        assert float(summary.total_ava_amount) == pytest.approx(2_000.0)
        assert float(summary.total_other_own_funds_reductions) == pytest.approx(1_000.0)
        assert float(summary.total_pool_b) == pytest.approx(9_000.0)

    def test_ava_reduces_cet1_deduction(self) -> None:
        """AVA in Pool B reduces effective shortfall, thus reducing CET1 deduction."""
        # Without AVA: shortfall=4000, cet1_deduction=2000
        lf_no_ava = _irb_frame(
            expected_loss=[10_000.0],
            provision_allocated=[6_000.0],
            ava_amount=[0.0],
            el_shortfall=[4_000.0],
            el_excess=[0.0],
        )
        summary_no_ava = compute_el_portfolio_summary(lf_no_ava)

        # With AVA: shortfall=2000, cet1_deduction=1000
        lf_with_ava = _irb_frame(
            expected_loss=[10_000.0],
            provision_allocated=[6_000.0],
            ava_amount=[2_000.0],
            el_shortfall=[2_000.0],
            el_excess=[0.0],
        )
        summary_with_ava = compute_el_portfolio_summary(lf_with_ava)

        assert summary_no_ava is not None
        assert summary_with_ava is not None
        assert float(summary_no_ava.cet1_deduction) == pytest.approx(2_000.0)
        assert float(summary_with_ava.cet1_deduction) == pytest.approx(1_000.0)
        # AVA halved the CET1 deduction
        assert summary_with_ava.cet1_deduction < summary_no_ava.cet1_deduction

    def test_ava_can_generate_t2_credit(self) -> None:
        """AVA excess above EL feeds into T2 credit (subject to cap)."""
        lf = _irb_frame(
            expected_loss=[10_000.0],
            provision_allocated=[8_000.0],
            ava_amount=[5_000.0],
            el_shortfall=[0.0],
            el_excess=[3_000.0],  # pool_b=13000 > EL=10000; excess=3000
            rwa_post_factor=[10_000_000.0],  # cap = 10M * 0.006 = 60000
        )
        summary = compute_el_portfolio_summary(lf)
        assert summary is not None
        assert float(summary.total_el_excess) == pytest.approx(3_000.0)
        assert float(summary.t2_credit) == pytest.approx(3_000.0)  # within cap

    def test_backward_compat_no_ava_columns(self) -> None:
        """Without AVA columns, summary behaves identically to before."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["EXP_001"],
                "approach_applied": ["FIRB"],
                "rwa_post_factor": [1_000_000.0],
                "expected_loss": [10_000.0],
                "provision_allocated": [6_000.0],
                "el_shortfall": [4_000.0],
                "el_excess": [0.0],
            }
        )
        summary = compute_el_portfolio_summary(lf)
        assert summary is not None
        assert float(summary.total_provisions_allocated) == pytest.approx(6_000.0)
        assert float(summary.total_ava_amount) == pytest.approx(0.0)
        assert float(summary.total_other_own_funds_reductions) == pytest.approx(0.0)
        assert float(summary.total_pool_b) == pytest.approx(6_000.0)
        assert float(summary.total_el_shortfall) == pytest.approx(4_000.0)

    def test_two_branch_with_ava(self) -> None:
        """Art. 159(3) two-branch rule works correctly with AVA present."""
        lf = pl.LazyFrame(
            {
                "exposure_reference": ["ND_001", "D_001"],
                "approach_applied": ["FIRB", "FIRB"],
                "rwa_post_factor": [5_000_000.0, 5_000_000.0],
                "expected_loss": [50_000.0, 10_000.0],
                "provision_allocated": [20_000.0, 30_000.0],
                "ava_amount": [10_000.0, 5_000.0],
                "other_own_funds_reductions": [0.0, 0.0],
                "is_defaulted": [False, True],
                # ND: pool_b=30000, el=50000, shortfall=20000
                "el_shortfall": [20_000.0, 0.0],
                # D: pool_b=35000, el=10000, excess=25000
                "el_excess": [0.0, 25_000.0],
            }
        )
        summary = compute_el_portfolio_summary(lf)
        assert summary is not None
        assert summary.art_159_3_applies is True
        # Two-branch: shortfall from ND only, excess from D only
        assert float(summary.total_el_shortfall) == pytest.approx(20_000.0)
        assert float(summary.total_el_excess) == pytest.approx(25_000.0)
        # AVA totals
        assert float(summary.total_ava_amount) == pytest.approx(15_000.0)
        assert float(summary.total_pool_b) == pytest.approx(65_000.0)

    def test_slotting_with_ava(self) -> None:
        """AVA flows through combined IRB + slotting summary."""
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["IRB_001"],
                "approach_applied": ["FIRB"],
                "rwa_post_factor": [1_000_000.0],
                "expected_loss": [10_000.0],
                "provision_allocated": [6_000.0],
                "ava_amount": [2_000.0],
                "other_own_funds_reductions": [500.0],
                "el_shortfall": [1_500.0],
                "el_excess": [0.0],
            }
        )
        slotting = pl.LazyFrame(
            {
                "exposure_reference": ["SL_001"],
                "approach_applied": ["slotting"],
                "rwa_post_factor": [500_000.0],
                "expected_loss": [5_000.0],
                "provision_allocated": [3_000.0],
                "ava_amount": [1_000.0],
                "other_own_funds_reductions": [0.0],
                "el_shortfall": [1_000.0],
                "el_excess": [0.0],
            }
        )
        summary = compute_el_portfolio_summary(irb, slotting)
        assert summary is not None
        assert float(summary.total_ava_amount) == pytest.approx(3_000.0)
        assert float(summary.total_other_own_funds_reductions) == pytest.approx(500.0)
        assert float(summary.total_pool_b) == pytest.approx(12_500.0)  # 9000 + 3000 + 500

    def test_pool_b_breakdown_fields(self) -> None:
        """Verify all Pool B breakdown fields on ELPortfolioSummary."""
        lf = _irb_frame(
            provision_allocated=[5_000.0],
            ava_amount=[1_500.0],
            other_own_funds_reductions=[800.0],
            expected_loss=[10_000.0],
            el_shortfall=[2_700.0],  # 10000 - (5000+1500+800) = 2700
            el_excess=[0.0],
        )
        summary = compute_el_portfolio_summary(lf)
        assert summary is not None
        assert float(summary.total_provisions_allocated) == pytest.approx(5_000.0)
        assert float(summary.total_ava_amount) == pytest.approx(1_500.0)
        assert float(summary.total_other_own_funds_reductions) == pytest.approx(800.0)
        assert float(summary.total_pool_b) == pytest.approx(7_300.0)
        # CET1 deduction = 50% of shortfall
        assert float(summary.cet1_deduction) == pytest.approx(1_350.0)
        assert float(summary.t2_deduction) == pytest.approx(1_350.0)

    def test_zero_ava_identical_to_provisions_only(self) -> None:
        """Zero AVA/OFR gives same result as provisions-only."""
        lf_zero = _irb_frame(
            ava_amount=[0.0],
            other_own_funds_reductions=[0.0],
        )
        lf_absent = pl.LazyFrame(
            {
                "exposure_reference": ["EXP_001"],
                "approach_applied": ["FIRB"],
                "rwa_post_factor": [1_000_000.0],
                "expected_loss": [10_000.0],
                "provision_allocated": [6_000.0],
                "el_shortfall": [4_000.0],
                "el_excess": [0.0],
            }
        )
        s1 = compute_el_portfolio_summary(lf_zero)
        s2 = compute_el_portfolio_summary(lf_absent)
        assert s1 is not None and s2 is not None
        assert float(s1.total_el_shortfall) == pytest.approx(float(s2.total_el_shortfall))
        assert float(s1.total_el_excess) == pytest.approx(float(s2.total_el_excess))
        assert float(s1.cet1_deduction) == pytest.approx(float(s2.cet1_deduction))
        assert float(s1.t2_credit) == pytest.approx(float(s2.t2_credit))
