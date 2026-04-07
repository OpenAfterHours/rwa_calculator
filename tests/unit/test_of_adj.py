"""
Unit tests for Output Floor Adjustment (OF-ADJ) per PRA PS1/26 Art. 92 para 2A.

OF-ADJ = 12.5 * (IRB_T2 - IRB_CET1 - GCRA + SA_T2) reconciles the different
provision treatments between IRB (EL shortfall/excess) and SA (general credit
risk adjustments) so the output floor comparison is on a like-for-like basis.

Why OF-ADJ matters:
Without OF-ADJ, the floor comparison penalises IRB banks with EL shortfall
(which increases CET1 deductions) while giving no floor-level credit for
excess provisions (which decrease T2).  OF-ADJ converts these capital-tier
differences into RWA-equivalent terms (× 12.5 = 1/8%) so the floor threshold
is adjusted accordingly.

Components:
- IRB_T2: Art. 62(d) excess provisions added to T2 (capped at 0.6% of IRB RWA)
- IRB_CET1: Art. 36(1)(d) EL shortfall CET1 deduction + Art. 40 supervisory add-on
- GCRA: General credit risk adjustments (capped at 1.25% of S-TREA)
- SA_T2: Art. 62(c) SA T2 credit for general CRAs

References:
- PRA PS1/26 Art. 92 para 2A
- CRR Art. 62(d): IRB T2 credit
- CRR Art. 36(1)(d), Art. 40: IRB CET1 deductions
- CRR Art. 62(c): SA T2 credit
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, OutputFloorConfig
from rwa_calc.engine.aggregator import OutputAggregator
from rwa_calc.engine.aggregator._floor import GCRA_CAP_RATE, compute_of_adj

EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})


@pytest.fixture
def aggregator() -> OutputAggregator:
    return OutputAggregator()


def _b31_config(
    gcra_amount: float = 0.0,
    sa_t2_credit: float = 0.0,
    art_40_deductions: float = 0.0,
) -> CalculationConfig:
    """Basel 3.1 config with OF-ADJ capital-tier inputs."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2032, 1, 1),
        gcra_amount=gcra_amount,
        sa_t2_credit=sa_t2_credit,
        art_40_deductions=art_40_deductions,
    )


def _irb_frame(
    rwa: float = 50_000_000.0,
    sa_rwa: float = 100_000_000.0,
    excess: float = 0.0,
    shortfall: float = 0.0,
) -> pl.LazyFrame:
    """IRB frame with EL columns for OF-ADJ testing."""
    return pl.LazyFrame({
        "exposure_reference": ["EXP001"],
        "exposure_class": ["CORPORATE"],
        "approach_applied": ["FIRB"],
        "ead_final": [200_000_000.0],
        "risk_weight": [rwa / 200_000_000.0],
        "rwa_post_factor": [rwa],
        "rwa_final": [rwa],
        "sa_rwa": [sa_rwa],
        "expected_loss": [100_000.0],
        "provision_allocated": [100_000.0 + excess],
        "el_shortfall": [shortfall],
        "el_excess": [excess],
    })


# =============================================================================
# compute_of_adj unit tests
# =============================================================================


class TestComputeOfAdj:
    """Unit tests for the compute_of_adj formula."""

    def test_all_zero_inputs(self) -> None:
        """All zero inputs produce zero OF-ADJ."""
        of_adj, gcra_capped = compute_of_adj(0.0, 0.0, 0.0, 0.0, 100_000.0)
        assert of_adj == pytest.approx(0.0)
        assert gcra_capped == pytest.approx(0.0)

    def test_irb_t2_only(self) -> None:
        """IRB T2 credit alone produces positive OF-ADJ.

        IRB T2 = 300k, everything else = 0.
        OF-ADJ = 12.5 * 300k = 3.75m.
        """
        of_adj, _ = compute_of_adj(300_000.0, 0.0, 0.0, 0.0, 100_000_000.0)
        assert of_adj == pytest.approx(3_750_000.0)

    def test_irb_cet1_only(self) -> None:
        """IRB CET1 deduction alone produces negative OF-ADJ.

        IRB CET1 = 200k, everything else = 0.
        OF-ADJ = 12.5 * (0 - 200k - 0 + 0) = -2.5m.
        """
        of_adj, _ = compute_of_adj(0.0, 200_000.0, 0.0, 0.0, 100_000_000.0)
        assert of_adj == pytest.approx(-2_500_000.0)

    def test_gcra_only(self) -> None:
        """GCRA alone produces negative OF-ADJ.

        GCRA = 500k, S-TREA = 100m → GCRA cap = 1.25m → GCRA uncapped at 500k.
        OF-ADJ = 12.5 * (0 - 0 - 500k + 0) = -6.25m.
        """
        of_adj, gcra_capped = compute_of_adj(0.0, 0.0, 500_000.0, 0.0, 100_000_000.0)
        assert of_adj == pytest.approx(-6_250_000.0)
        assert gcra_capped == pytest.approx(500_000.0)

    def test_sa_t2_only(self) -> None:
        """SA T2 credit alone produces positive OF-ADJ.

        SA T2 = 400k, everything else = 0.
        OF-ADJ = 12.5 * 400k = 5.0m.
        """
        of_adj, _ = compute_of_adj(0.0, 0.0, 0.0, 400_000.0, 100_000_000.0)
        assert of_adj == pytest.approx(5_000_000.0)

    def test_full_formula(self) -> None:
        """All four components present.

        IRB_T2=300k, IRB_CET1=100k, GCRA=200k, SA_T2=150k.
        OF-ADJ = 12.5 * (300k - 100k - 200k + 150k) = 12.5 * 150k = 1.875m.
        """
        of_adj, _ = compute_of_adj(300_000.0, 100_000.0, 200_000.0, 150_000.0, 100_000_000.0)
        assert of_adj == pytest.approx(1_875_000.0)

    def test_negative_of_adj(self) -> None:
        """OF-ADJ can be negative (IRB bank with EL shortfall, no SA provisions).

        IRB_T2=0, IRB_CET1=500k, GCRA=0, SA_T2=0.
        OF-ADJ = 12.5 * (0 - 500k - 0 + 0) = -6.25m.
        Negative OF-ADJ LOWERS the floor threshold.
        """
        of_adj, _ = compute_of_adj(0.0, 500_000.0, 0.0, 0.0, 100_000_000.0)
        assert of_adj == pytest.approx(-6_250_000.0)

    def test_gcra_cap_at_1_25_pct_of_s_trea(self) -> None:
        """GCRA is capped at 1.25% of S-TREA per Art. 92 para 2A.

        GCRA = 2m, S-TREA = 100m → cap = 1.25m → GCRA capped at 1.25m.
        OF-ADJ = 12.5 * (0 - 0 - 1.25m + 0) = -15.625m.
        """
        of_adj, gcra_capped = compute_of_adj(0.0, 0.0, 2_000_000.0, 0.0, 100_000_000.0)
        assert gcra_capped == pytest.approx(1_250_000.0)
        assert of_adj == pytest.approx(-15_625_000.0)

    def test_gcra_below_cap_unchanged(self) -> None:
        """GCRA below the cap is used as-is."""
        of_adj, gcra_capped = compute_of_adj(0.0, 0.0, 500_000.0, 0.0, 100_000_000.0)
        assert gcra_capped == pytest.approx(500_000.0)

    def test_gcra_at_cap_boundary(self) -> None:
        """GCRA exactly at 1.25% of S-TREA is not reduced."""
        # S-TREA = 80m → cap = 1m
        of_adj, gcra_capped = compute_of_adj(0.0, 0.0, 1_000_000.0, 0.0, 80_000_000.0)
        assert gcra_capped == pytest.approx(1_000_000.0)

    def test_gcra_cap_with_zero_s_trea(self) -> None:
        """Zero S-TREA: GCRA is used as-is (cap = 0, but GCRA >= 0 always)."""
        of_adj, gcra_capped = compute_of_adj(0.0, 0.0, 500_000.0, 0.0, 0.0)
        assert gcra_capped == pytest.approx(500_000.0)

    def test_gcra_cap_rate_constant(self) -> None:
        """GCRA_CAP_RATE must be 1.25% = 0.0125."""
        assert GCRA_CAP_RATE == pytest.approx(0.0125)

    def test_12_5_multiplier(self) -> None:
        """The 12.5 multiplier converts capital to RWA (1/8% capital requirement)."""
        of_adj, _ = compute_of_adj(80_000.0, 0.0, 0.0, 0.0, 100_000_000.0)
        # 12.5 * 80k = 1m
        assert of_adj == pytest.approx(1_000_000.0)


# =============================================================================
# End-to-end aggregator tests with OF-ADJ
# =============================================================================


class TestOfAdjAggregator:
    """Test OF-ADJ integration through the full aggregator pipeline."""

    def test_of_adj_from_irb_excess_provisions(self, aggregator: OutputAggregator) -> None:
        """IRB excess provisions produce positive OF-ADJ via t2_credit.

        IRB RWA=50m, SA RWA=100m, excess=500k.
        T2 credit = min(500k, 50m × 0.006) = min(500k, 300k) = 300k.
        OF-ADJ = 12.5 × 300k = 3.75m.
        Floor threshold = 72.5% × 100m + 3.75m = 76.25m.
        """
        config = _b31_config()
        irb = _irb_frame(rwa=50_000_000.0, sa_rwa=100_000_000.0, excess=500_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)

        summary = result.output_floor_summary
        assert summary is not None
        assert summary.of_adj == pytest.approx(3_750_000.0, rel=0.001)
        assert summary.irb_t2_credit == pytest.approx(300_000.0, rel=0.001)
        assert summary.irb_cet1_deduction == pytest.approx(0.0, abs=1.0)
        assert summary.floor_threshold == pytest.approx(76_250_000.0, rel=0.001)
        assert summary.portfolio_floor_binding is True

    def test_of_adj_with_el_shortfall(self, aggregator: OutputAggregator) -> None:
        """IRB EL shortfall produces negative OF-ADJ via cet1_deduction.

        IRB RWA=50m, SA RWA=100m, shortfall=400k.
        CET1 deduction = 400k × 0.5 = 200k.
        OF-ADJ = 12.5 × (0 - 200k - 0 + 0) = -2.5m.
        Floor threshold = 72.5% × 100m - 2.5m = 70.0m.
        """
        config = _b31_config()
        irb = _irb_frame(rwa=50_000_000.0, sa_rwa=100_000_000.0, shortfall=400_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)

        summary = result.output_floor_summary
        assert summary is not None
        assert summary.irb_cet1_deduction == pytest.approx(200_000.0, rel=0.001)
        assert summary.of_adj == pytest.approx(-2_500_000.0, rel=0.001)
        assert summary.floor_threshold == pytest.approx(70_000_000.0, rel=0.001)

    def test_of_adj_with_gcra_input(self, aggregator: OutputAggregator) -> None:
        """GCRA config input reduces floor threshold.

        No EL shortfall/excess → IRB_T2 = 0, IRB_CET1 = 0.
        GCRA = 500k (below 1.25% of 100m = 1.25m → uncapped).
        OF-ADJ = 12.5 × (0 - 0 - 500k + 0) = -6.25m.
        Floor threshold = 72.5m - 6.25m = 66.25m.
        """
        config = _b31_config(gcra_amount=500_000.0)
        irb = _irb_frame(rwa=50_000_000.0, sa_rwa=100_000_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)

        summary = result.output_floor_summary
        assert summary is not None
        assert summary.gcra_amount == pytest.approx(500_000.0, rel=0.001)
        assert summary.of_adj == pytest.approx(-6_250_000.0, rel=0.001)
        assert summary.floor_threshold == pytest.approx(66_250_000.0, rel=0.001)

    def test_of_adj_with_sa_t2_input(self, aggregator: OutputAggregator) -> None:
        """SA T2 credit raises floor threshold.

        SA_T2 = 400k.
        OF-ADJ = 12.5 × (0 - 0 - 0 + 400k) = 5.0m.
        Floor threshold = 72.5m + 5.0m = 77.5m.
        """
        config = _b31_config(sa_t2_credit=400_000.0)
        irb = _irb_frame(rwa=50_000_000.0, sa_rwa=100_000_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)

        summary = result.output_floor_summary
        assert summary is not None
        assert summary.sa_t2_credit == pytest.approx(400_000.0, rel=0.001)
        assert summary.of_adj == pytest.approx(5_000_000.0, rel=0.001)
        assert summary.floor_threshold == pytest.approx(77_500_000.0, rel=0.001)

    def test_of_adj_with_art_40_deductions(self, aggregator: OutputAggregator) -> None:
        """Art. 40 supervisory add-on increases IRB CET1 deduction.

        art_40 = 100k, no shortfall → CET1 deduction = 0 + 100k = 100k.
        OF-ADJ = 12.5 × (0 - 100k - 0 + 0) = -1.25m.
        """
        config = _b31_config(art_40_deductions=100_000.0)
        irb = _irb_frame(rwa=50_000_000.0, sa_rwa=100_000_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)

        summary = result.output_floor_summary
        assert summary is not None
        assert summary.irb_cet1_deduction == pytest.approx(100_000.0, rel=0.001)
        assert summary.of_adj == pytest.approx(-1_250_000.0, rel=0.001)

    def test_of_adj_all_components(self, aggregator: OutputAggregator) -> None:
        """All four OF-ADJ components active simultaneously.

        IRB excess=500k → T2 credit = min(500k, 50m×0.006=300k) = 300k.
        art_40 = 50k → CET1 = 0 + 50k = 50k.
        GCRA = 200k (below cap). SA_T2 = 100k.
        OF-ADJ = 12.5 × (300k - 50k - 200k + 100k) = 12.5 × 150k = 1.875m.
        """
        config = _b31_config(gcra_amount=200_000.0, sa_t2_credit=100_000.0,
                             art_40_deductions=50_000.0)
        irb = _irb_frame(rwa=50_000_000.0, sa_rwa=100_000_000.0, excess=500_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)

        summary = result.output_floor_summary
        assert summary is not None
        assert summary.of_adj == pytest.approx(1_875_000.0, rel=0.001)
        assert summary.irb_t2_credit == pytest.approx(300_000.0, rel=0.001)
        assert summary.irb_cet1_deduction == pytest.approx(50_000.0, rel=0.001)
        assert summary.gcra_amount == pytest.approx(200_000.0, rel=0.001)
        assert summary.sa_t2_credit == pytest.approx(100_000.0, rel=0.001)

    def test_of_adj_gcra_capped_at_1_25_pct_of_s_trea(
        self, aggregator: OutputAggregator
    ) -> None:
        """GCRA input exceeding 1.25% of S-TREA is capped.

        S-TREA (for floor-eligible) = 100m → GCRA cap = 1.25m.
        GCRA input = 2m → capped to 1.25m.
        OF-ADJ = 12.5 × (0 - 0 - 1.25m + 0) = -15.625m.
        """
        config = _b31_config(gcra_amount=2_000_000.0)
        irb = _irb_frame(rwa=50_000_000.0, sa_rwa=100_000_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)

        summary = result.output_floor_summary
        assert summary is not None
        # GCRA capped from 2m to 1.25m
        assert summary.gcra_amount == pytest.approx(1_250_000.0, rel=0.001)
        assert summary.of_adj == pytest.approx(-15_625_000.0, rel=0.001)

    def test_of_adj_zero_when_no_el_summary_no_config(
        self, aggregator: OutputAggregator
    ) -> None:
        """No EL data and no config inputs → OF-ADJ = 0 (backward compat)."""
        config = _b31_config()
        irb = pl.LazyFrame({
            "exposure_reference": ["EXP001"],
            "exposure_class": ["CORPORATE"],
            "approach_applied": ["FIRB"],
            "ead_final": [200_000_000.0],
            "risk_weight": [0.25],
            "rwa_final": [50_000_000.0],
            "sa_rwa": [100_000_000.0],
        })
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)

        summary = result.output_floor_summary
        assert summary is not None
        assert summary.of_adj == pytest.approx(0.0, abs=1.0)
        # Original floor behavior: 72.5% × 100m = 72.5m
        assert summary.floor_threshold == pytest.approx(72_500_000.0, rel=0.001)

    def test_negative_of_adj_lowers_floor_threshold(
        self, aggregator: OutputAggregator
    ) -> None:
        """Negative OF-ADJ can make the floor NOT bind when it otherwise would.

        IRB RWA = 70m, SA RWA = 100m.
        Without OF-ADJ: 72.5% × 100m = 72.5m > 70m → floor binds.
        With GCRA = 500k: OF-ADJ = -6.25m → threshold = 66.25m < 70m → floor doesn't bind.
        """
        config = _b31_config(gcra_amount=500_000.0)
        irb = _irb_frame(rwa=70_000_000.0, sa_rwa=100_000_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)

        summary = result.output_floor_summary
        assert summary is not None
        assert summary.of_adj == pytest.approx(-6_250_000.0, rel=0.001)
        assert summary.floor_threshold == pytest.approx(66_250_000.0, rel=0.001)
        assert summary.portfolio_floor_binding is False
        assert summary.shortfall == pytest.approx(0.0, abs=1.0)

    def test_crr_no_of_adj(self, aggregator: OutputAggregator) -> None:
        """Under CRR, output floor is disabled — no OF-ADJ computed."""
        config = CalculationConfig.crr(reporting_date=date(2025, 12, 31))
        irb = _irb_frame(rwa=50_000_000.0, sa_rwa=100_000_000.0, excess=500_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)

        assert result.output_floor_summary is None

    def test_of_adj_summary_fields_populated(self, aggregator: OutputAggregator) -> None:
        """OutputFloorSummary has all OF-ADJ breakdown fields."""
        config = _b31_config(gcra_amount=300_000.0, sa_t2_credit=200_000.0,
                             art_40_deductions=75_000.0)
        irb = _irb_frame(rwa=50_000_000.0, sa_rwa=100_000_000.0, excess=500_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)

        summary = result.output_floor_summary
        assert summary is not None
        assert hasattr(summary, "of_adj")
        assert hasattr(summary, "irb_t2_credit")
        assert hasattr(summary, "irb_cet1_deduction")
        assert hasattr(summary, "gcra_amount")
        assert hasattr(summary, "sa_t2_credit")

    def test_of_adj_rwa_post_floor_correct(self, aggregator: OutputAggregator) -> None:
        """total_rwa_post_floor = u_trea + shortfall when floor binds.

        With OF-ADJ = 3.75m: threshold = 76.25m, shortfall = 76.25m - 50m = 26.25m.
        total_rwa_post_floor = 50m + 26.25m = 76.25m.
        """
        config = _b31_config()
        irb = _irb_frame(rwa=50_000_000.0, sa_rwa=100_000_000.0, excess=500_000.0)
        result = aggregator.aggregate(EMPTY, irb, EMPTY, None, config)

        summary = result.output_floor_summary
        assert summary is not None
        assert summary.total_rwa_post_floor == pytest.approx(
            summary.u_trea + summary.shortfall, rel=0.001
        )


# =============================================================================
# Config integration tests
# =============================================================================


class TestOfAdjConfig:
    """Test OutputFloorConfig OF-ADJ fields."""

    def test_default_values_zero(self) -> None:
        """OF-ADJ config fields default to zero."""
        config = OutputFloorConfig.basel_3_1()
        assert config.gcra_amount == 0.0
        assert config.sa_t2_credit == 0.0
        assert config.art_40_deductions == 0.0

    def test_crr_config_has_defaults(self) -> None:
        """CRR config has OF-ADJ fields at zero (floor disabled anyway)."""
        config = OutputFloorConfig.crr()
        assert config.gcra_amount == 0.0
        assert config.sa_t2_credit == 0.0
        assert config.art_40_deductions == 0.0

    def test_calculation_config_propagates_of_adj_inputs(self) -> None:
        """CalculationConfig.basel_3_1() propagates OF-ADJ inputs."""
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2032, 1, 1),
            gcra_amount=300_000.0,
            sa_t2_credit=200_000.0,
            art_40_deductions=50_000.0,
        )
        assert config.output_floor.gcra_amount == pytest.approx(300_000.0)
        assert config.output_floor.sa_t2_credit == pytest.approx(200_000.0)
        assert config.output_floor.art_40_deductions == pytest.approx(50_000.0)
