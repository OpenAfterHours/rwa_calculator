"""
Unit tests for CapitalImpactAnalyzer (M3.2).

Tests the capital impact attribution engine including:
- Per-exposure waterfall decomposition into 4 drivers
- Additivity invariant (scaling + supporting + floor + methodology = delta)
- IRB-specific attribution (scaling factor, output floor)
- SA-specific attribution (no scaling, no floor)
- Portfolio-level waterfall aggregation
- Summary aggregation by class and approach
- Edge cases (zero delta, missing exposures, no supporting factors)

Why these tests matter:
    Capital impact analysis is the key analytical product for firms
    transitioning from CRR to Basel 3.1. Attribution errors would lead
    to incorrect capital planning decisions. The additivity invariant
    is the critical correctness check — if drivers don't sum to the
    total delta, the decomposition is mathematically wrong.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    AggregatedResultBundle,
    CapitalImpactBundle,
    ComparisonBundle,
)
from rwa_calc.engine.comparison import (
    CapitalImpactAnalyzer,
    _compute_attribution_summary,
    _compute_exposure_attribution,
    _compute_portfolio_waterfall,
)


# =============================================================================
# Test Fixtures
# =============================================================================


def _make_crr_results(
    exposure_refs: list[str],
    exposure_classes: list[str],
    approaches: list[str],
    rwa_finals: list[float],
    rwa_pre_factors: list[float] | None = None,
    supporting_factors: list[float] | None = None,
) -> AggregatedResultBundle:
    """Build mock CRR AggregatedResultBundle with supporting factor columns."""
    data: dict = {
        "exposure_reference": exposure_refs,
        "exposure_class": exposure_classes,
        "approach_applied": approaches,
        "ead_final": [1_000_000.0] * len(exposure_refs),
        "risk_weight": [0.5] * len(exposure_refs),
        "rwa_final": rwa_finals,
    }
    if rwa_pre_factors is not None:
        data["rwa_pre_factor"] = rwa_pre_factors
    if supporting_factors is not None:
        data["supporting_factor"] = supporting_factors
    return AggregatedResultBundle(results=pl.LazyFrame(data), errors=[])


def _make_b31_results(
    exposure_refs: list[str],
    rwa_finals: list[float],
    rwa_pre_floors: list[float] | None = None,
    floor_impact_data: dict | None = None,
) -> AggregatedResultBundle:
    """Build mock B31 AggregatedResultBundle with optional floor impact."""
    data: dict = {
        "exposure_reference": exposure_refs,
        "exposure_class": ["corporate"] * len(exposure_refs),
        "approach_applied": ["foundation_irb"] * len(exposure_refs),
        "ead_final": [1_000_000.0] * len(exposure_refs),
        "risk_weight": [0.5] * len(exposure_refs),
        "rwa_final": rwa_finals,
    }
    if rwa_pre_floors is not None:
        data["rwa_pre_floor"] = rwa_pre_floors

    floor_impact = None
    if floor_impact_data is not None:
        floor_impact = pl.LazyFrame(floor_impact_data)

    return AggregatedResultBundle(
        results=pl.LazyFrame(data),
        floor_impact=floor_impact,
        errors=[],
    )


def _make_comparison(
    crr: AggregatedResultBundle,
    b31: AggregatedResultBundle,
) -> ComparisonBundle:
    """Build a minimal ComparisonBundle for testing attribution."""
    # We only need crr_results and b31_results for attribution
    return ComparisonBundle(
        crr_results=crr,
        b31_results=b31,
        exposure_deltas=pl.LazyFrame(),  # Not used by attribution
        summary_by_class=pl.LazyFrame(),
        summary_by_approach=pl.LazyFrame(),
        errors=[],
    )


# =============================================================================
# Test: Additivity Invariant
# =============================================================================


class TestAdditivityInvariant:
    """The four drivers must sum to delta_rwa for every exposure."""

    def test_irb_attribution_sums_to_delta(self) -> None:
        """IRB exposure: scaling + supporting + floor + methodology = delta."""
        # CRR: rwa_final = 530_000 (includes 1.06 scaling + 0.7619 SME factor)
        # rwa_pre_factor = 695_850 (before supporting factor, includes 1.06)
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["foundation_irb"],
            rwa_finals=[530_000.0],
            rwa_pre_factors=[695_850.0],
            supporting_factors=[0.7619],
        )
        # B31: rwa_final = 600_000 (no scaling, no supporting, no floor binding)
        b31 = _make_b31_results(
            ["EXP001"],
            rwa_finals=[600_000.0],
            rwa_pre_floors=[600_000.0],
        )
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]

        delta = row["delta_rwa"]
        driver_sum = (
            row["scaling_factor_impact"]
            + row["supporting_factor_impact"]
            + row["output_floor_impact"]
            + row["methodology_impact"]
        )
        assert driver_sum == pytest.approx(delta, abs=0.01)

    def test_sa_attribution_sums_to_delta(self) -> None:
        """SA exposure: scaling=0, floor=0, supporting + methodology = delta."""
        # CRR: rwa_final = 76_190 (with 0.7619 SME factor)
        # rwa_pre_factor = 100_000 (before supporting factor)
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["SA"],
            rwa_finals=[76_190.0],
            rwa_pre_factors=[100_000.0],
            supporting_factors=[0.7619],
        )
        # B31: rwa_final = 85_000 (85% RW for SME corporates, no factor)
        b31 = _make_b31_results(["EXP001"], rwa_finals=[85_000.0])
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]

        delta = row["delta_rwa"]
        driver_sum = (
            row["scaling_factor_impact"]
            + row["supporting_factor_impact"]
            + row["output_floor_impact"]
            + row["methodology_impact"]
        )
        assert driver_sum == pytest.approx(delta, abs=0.01)

    def test_multiple_exposures_all_sum_correctly(self) -> None:
        """Every exposure in a mixed SA + IRB portfolio satisfies additivity."""
        crr = _make_crr_results(
            ["SA1", "SA2", "IRB1"],
            ["corporate", "retail_mortgage", "corporate"],
            ["SA", "SA", "foundation_irb"],
            rwa_finals=[100_000.0, 50_000.0, 530_000.0],
            rwa_pre_factors=[100_000.0, 50_000.0, 695_850.0],
            supporting_factors=[1.0, 1.0, 0.7619],
        )
        b31 = _make_b31_results(
            ["SA1", "SA2", "IRB1"],
            rwa_finals=[85_000.0, 40_000.0, 600_000.0],
            rwa_pre_floors=[85_000.0, 40_000.0, 600_000.0],
        )
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        for row in attribution.to_dicts():
            delta = row["delta_rwa"]
            driver_sum = (
                row["scaling_factor_impact"]
                + row["supporting_factor_impact"]
                + row["output_floor_impact"]
                + row["methodology_impact"]
            )
            assert driver_sum == pytest.approx(delta, abs=0.01), (
                f"Additivity failed for {row['exposure_reference']}"
            )


# =============================================================================
# Test: Scaling Factor Impact
# =============================================================================


class TestScalingFactorImpact:
    """CRR applies 1.06x to IRB RWA; Basel 3.1 removes it."""

    def test_irb_scaling_impact_is_negative(self) -> None:
        """Removing 1.06x reduces RWA, so impact should be negative."""
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["foundation_irb"],
            rwa_finals=[1_060_000.0],
            rwa_pre_factors=[1_060_000.0],
            supporting_factors=[1.0],
        )
        b31 = _make_b31_results(
            ["EXP001"], rwa_finals=[1_000_000.0],
            rwa_pre_floors=[1_000_000.0],
        )
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]

        # scaling_impact = 1_060_000 * (1/1.06 - 1) = -60_000 / 1.06 ≈ -56_603.77
        expected = 1_060_000.0 * (1.0 / 1.06 - 1.0)
        assert row["scaling_factor_impact"] == pytest.approx(expected, abs=1.0)
        assert row["scaling_factor_impact"] < 0

    def test_sa_scaling_impact_is_zero(self) -> None:
        """SA exposures have no scaling factor — impact should be 0."""
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["SA"],
            rwa_finals=[100_000.0],
            rwa_pre_factors=[100_000.0],
            supporting_factors=[1.0],
        )
        b31 = _make_b31_results(["EXP001"], rwa_finals=[85_000.0])
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]
        assert row["scaling_factor_impact"] == pytest.approx(0.0)

    def test_advanced_irb_also_gets_scaling_impact(self) -> None:
        """A-IRB exposures should also have scaling factor decomposed."""
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["advanced_irb"],
            rwa_finals=[530_000.0],
            rwa_pre_factors=[530_000.0],
            supporting_factors=[1.0],
        )
        b31 = _make_b31_results(
            ["EXP001"], rwa_finals=[500_000.0],
            rwa_pre_floors=[500_000.0],
        )
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]
        assert row["scaling_factor_impact"] < 0


# =============================================================================
# Test: Supporting Factor Impact
# =============================================================================


class TestSupportingFactorImpact:
    """CRR applies SME/infrastructure supporting factors; B31 removes them."""

    def test_irb_sme_supporting_factor_impact(self) -> None:
        """Removing 0.7619 SME factor increases RWA (positive impact)."""
        # CRR: rwa_pre_factor = 1_060_000 (with 1.06 scaling, before factor)
        # CRR: rwa_final = 1_060_000 * 0.7619 = 807_614
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["foundation_irb"],
            rwa_finals=[807_614.0],
            rwa_pre_factors=[1_060_000.0],
            supporting_factors=[0.7619],
        )
        b31 = _make_b31_results(
            ["EXP001"], rwa_finals=[1_000_000.0],
            rwa_pre_floors=[1_000_000.0],
        )
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]

        # supporting_impact = (1_060_000 - 807_614) / 1.06 = 252_386 / 1.06 ≈ 238_100
        expected = (1_060_000.0 - 807_614.0) / 1.06
        assert row["supporting_factor_impact"] == pytest.approx(expected, abs=1.0)
        assert row["supporting_factor_impact"] > 0

    def test_sa_sme_supporting_factor_impact(self) -> None:
        """SA SME: supporting impact = rwa_pre_factor - rwa_final (no scaling)."""
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["SA"],
            rwa_finals=[76_190.0],
            rwa_pre_factors=[100_000.0],
            supporting_factors=[0.7619],
        )
        b31 = _make_b31_results(["EXP001"], rwa_finals=[85_000.0])
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]

        # SA supporting impact = 100_000 - 76_190 = 23_810
        expected = 100_000.0 - 76_190.0
        assert row["supporting_factor_impact"] == pytest.approx(expected, abs=1.0)
        assert row["supporting_factor_impact"] > 0

    def test_no_supporting_factor_means_zero_impact(self) -> None:
        """When supporting factor is 1.0 (not applied), impact should be 0."""
        crr = _make_crr_results(
            ["EXP001"], ["institution"], ["SA"],
            rwa_finals=[100_000.0],
            rwa_pre_factors=[100_000.0],
            supporting_factors=[1.0],
        )
        b31 = _make_b31_results(["EXP001"], rwa_finals=[80_000.0])
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]
        assert row["supporting_factor_impact"] == pytest.approx(0.0)


# =============================================================================
# Test: Output Floor Impact
# =============================================================================


class TestOutputFloorImpact:
    """B31 output floor: IRB RWA = max(IRB_RWA, SA_RWA × floor_pct)."""

    def test_floor_binding_produces_positive_impact(self) -> None:
        """When the floor binds, floor_impact should be positive."""
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["foundation_irb"],
            rwa_finals=[400_000.0],
            rwa_pre_factors=[400_000.0],
            supporting_factors=[1.0],
        )
        b31 = _make_b31_results(
            ["EXP001"],
            rwa_finals=[500_000.0],  # Post-floor (floor binds)
            rwa_pre_floors=[350_000.0],  # Pre-floor IRB RWA
            floor_impact_data={
                "exposure_reference": ["EXP001"],
                "floor_impact_rwa": [150_000.0],  # 500k - 350k
            },
        )
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]

        assert row["output_floor_impact"] == pytest.approx(150_000.0)
        assert row["output_floor_impact"] > 0

    def test_floor_not_binding_zero_impact(self) -> None:
        """When floor doesn't bind, floor impact should be 0."""
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["foundation_irb"],
            rwa_finals=[400_000.0],
            rwa_pre_factors=[400_000.0],
            supporting_factors=[1.0],
        )
        b31 = _make_b31_results(
            ["EXP001"],
            rwa_finals=[380_000.0],
            rwa_pre_floors=[380_000.0],
            floor_impact_data={
                "exposure_reference": ["EXP001"],
                "floor_impact_rwa": [0.0],
            },
        )
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]
        assert row["output_floor_impact"] == pytest.approx(0.0)

    def test_sa_exposure_has_no_floor_impact(self) -> None:
        """SA exposures are never subject to the output floor."""
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["SA"],
            rwa_finals=[100_000.0],
            rwa_pre_factors=[100_000.0],
            supporting_factors=[1.0],
        )
        b31 = _make_b31_results(["EXP001"], rwa_finals=[85_000.0])
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]
        assert row["output_floor_impact"] == pytest.approx(0.0)


# =============================================================================
# Test: Methodology Impact
# =============================================================================


class TestMethodologyImpact:
    """Residual delta after other drivers — captures RW/parameter changes."""

    def test_sa_methodology_captures_rw_changes(self) -> None:
        """For SA with no supporting factor, all delta goes to methodology."""
        crr = _make_crr_results(
            ["EXP001"], ["institution"], ["SA"],
            rwa_finals=[200_000.0],
            rwa_pre_factors=[200_000.0],
            supporting_factors=[1.0],
        )
        b31 = _make_b31_results(["EXP001"], rwa_finals=[150_000.0])
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]

        # All delta goes to methodology (no scaling, no supporting, no floor)
        assert row["methodology_impact"] == pytest.approx(-50_000.0)
        assert row["scaling_factor_impact"] == pytest.approx(0.0)
        assert row["supporting_factor_impact"] == pytest.approx(0.0)
        assert row["output_floor_impact"] == pytest.approx(0.0)

    def test_irb_methodology_is_residual(self) -> None:
        """IRB methodology captures PD/LGD floor effects as residual."""
        # CRR: rwa_final = 530_000, rwa_pre_factor = 530_000 (no supporting factor)
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["foundation_irb"],
            rwa_finals=[530_000.0],
            rwa_pre_factors=[530_000.0],
            supporting_factors=[1.0],
        )
        # B31: rwa_final = 550_000 (higher due to PD/LGD floors, no floor binding)
        b31 = _make_b31_results(
            ["EXP001"],
            rwa_finals=[550_000.0],
            rwa_pre_floors=[550_000.0],
            floor_impact_data={
                "exposure_reference": ["EXP001"],
                "floor_impact_rwa": [0.0],
            },
        )
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]

        # delta = 550k - 530k = 20k
        # scaling = 530k * (1/1.06 - 1) ≈ -30k
        # supporting = 0
        # floor = 0
        # methodology = 20k - (-30k) = 50k (residual captures PD/LGD changes)
        assert row["delta_rwa"] == pytest.approx(20_000.0)
        assert row["methodology_impact"] > 0  # Positive because formula changes increase RWA


# =============================================================================
# Test: Portfolio Waterfall
# =============================================================================


class TestPortfolioWaterfall:
    """Portfolio-level waterfall from CRR baseline to B31 total."""

    def test_waterfall_has_four_steps(self) -> None:
        """Waterfall should have exactly 4 driver steps."""
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["SA"],
            rwa_finals=[100_000.0],
            rwa_pre_factors=[100_000.0],
            supporting_factors=[1.0],
        )
        b31 = _make_b31_results(["EXP001"], rwa_finals=[85_000.0])
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison)
        waterfall = _compute_portfolio_waterfall(attribution).collect()

        assert waterfall.height == 4
        assert waterfall["step"].to_list() == [1, 2, 3, 4]

    def test_waterfall_cumulative_ends_at_b31_rwa(self) -> None:
        """The final cumulative value should equal total B31 RWA."""
        crr = _make_crr_results(
            ["SA1", "IRB1"], ["corporate", "corporate"],
            ["SA", "foundation_irb"],
            rwa_finals=[100_000.0, 530_000.0],
            rwa_pre_factors=[100_000.0, 530_000.0],
            supporting_factors=[1.0, 1.0],
        )
        b31 = _make_b31_results(
            ["SA1", "IRB1"],
            rwa_finals=[85_000.0, 500_000.0],
            rwa_pre_floors=[85_000.0, 500_000.0],
        )
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison)
        waterfall = _compute_portfolio_waterfall(attribution).collect()

        total_b31 = 85_000.0 + 500_000.0
        last_cumulative = waterfall["cumulative_rwa"][-1]
        assert last_cumulative == pytest.approx(total_b31, abs=1.0)

    def test_waterfall_driver_labels_present(self) -> None:
        """Each waterfall step should have a descriptive driver label."""
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["SA"],
            rwa_finals=[100_000.0],
            rwa_pre_factors=[100_000.0],
            supporting_factors=[1.0],
        )
        b31 = _make_b31_results(["EXP001"], rwa_finals=[85_000.0])
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison)
        waterfall = _compute_portfolio_waterfall(attribution).collect()

        drivers = waterfall["driver"].to_list()
        assert "Scaling factor removal" in drivers[0]
        assert "Supporting factor removal" in drivers[1]
        assert "Methodology" in drivers[2]
        assert "Output floor" in drivers[3]


# =============================================================================
# Test: Summary Aggregation
# =============================================================================


class TestSummaryAggregation:
    """Attribution summaries by class and approach."""

    def test_summary_by_class_groups_correctly(self) -> None:
        """Each exposure class should have aggregated driver totals."""
        crr = _make_crr_results(
            ["EXP001", "EXP002"], ["corporate", "institution"],
            ["SA", "SA"],
            rwa_finals=[100_000.0, 200_000.0],
            rwa_pre_factors=[100_000.0, 200_000.0],
            supporting_factors=[1.0, 1.0],
        )
        b31 = _make_b31_results(
            ["EXP001", "EXP002"],
            rwa_finals=[85_000.0, 150_000.0],
        )
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison)
        summary = _compute_attribution_summary(attribution, "exposure_class").collect()

        assert summary.height == 2
        assert "total_delta_rwa" in summary.columns
        assert "total_scaling_factor_impact" in summary.columns
        assert "total_supporting_factor_impact" in summary.columns
        assert "total_output_floor_impact" in summary.columns
        assert "total_methodology_impact" in summary.columns
        assert "exposure_count" in summary.columns

    def test_summary_by_approach_groups_correctly(self) -> None:
        """Each approach should have aggregated driver totals."""
        crr = _make_crr_results(
            ["SA1", "IRB1"], ["corporate", "corporate"],
            ["SA", "foundation_irb"],
            rwa_finals=[100_000.0, 530_000.0],
            rwa_pre_factors=[100_000.0, 530_000.0],
            supporting_factors=[1.0, 1.0],
        )
        b31 = _make_b31_results(
            ["SA1", "IRB1"],
            rwa_finals=[85_000.0, 500_000.0],
            rwa_pre_floors=[85_000.0, 500_000.0],
        )
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison)
        summary = _compute_attribution_summary(attribution, "approach_applied").collect()

        assert summary.height == 2
        approaches = summary["approach_applied"].to_list()
        assert "SA" in approaches
        assert "foundation_irb" in approaches

    def test_summary_drivers_sum_to_delta(self) -> None:
        """In each group, the sum of 4 driver totals equals total_delta_rwa."""
        crr = _make_crr_results(
            ["SA1", "IRB1", "IRB2"],
            ["corporate", "corporate", "institution"],
            ["SA", "foundation_irb", "foundation_irb"],
            rwa_finals=[76_190.0, 530_000.0, 400_000.0],
            rwa_pre_factors=[100_000.0, 695_850.0, 400_000.0],
            supporting_factors=[0.7619, 0.7619, 1.0],
        )
        b31 = _make_b31_results(
            ["SA1", "IRB1", "IRB2"],
            rwa_finals=[85_000.0, 600_000.0, 380_000.0],
            rwa_pre_floors=[85_000.0, 600_000.0, 380_000.0],
        )
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison)
        summary = _compute_attribution_summary(attribution, "exposure_class").collect()

        for row in summary.to_dicts():
            driver_sum = (
                row["total_scaling_factor_impact"]
                + row["total_supporting_factor_impact"]
                + row["total_output_floor_impact"]
                + row["total_methodology_impact"]
            )
            assert driver_sum == pytest.approx(row["total_delta_rwa"], abs=1.0), (
                f"Summary additivity failed for {row['exposure_class']}"
            )


# =============================================================================
# Test: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Edge cases and robustness scenarios."""

    def test_zero_delta_all_drivers_zero(self) -> None:
        """When CRR == B31, all drivers should be zero."""
        crr = _make_crr_results(
            ["EXP001"], ["central_govt_central_bank"], ["SA"],
            rwa_finals=[0.0],
            rwa_pre_factors=[0.0],
            supporting_factors=[1.0],
        )
        b31 = _make_b31_results(["EXP001"], rwa_finals=[0.0])
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]

        assert row["delta_rwa"] == pytest.approx(0.0)
        assert row["scaling_factor_impact"] == pytest.approx(0.0)
        assert row["supporting_factor_impact"] == pytest.approx(0.0)
        assert row["output_floor_impact"] == pytest.approx(0.0)
        assert row["methodology_impact"] == pytest.approx(0.0)

    def test_no_rwa_pre_factor_column_defaults_to_rwa_final(self) -> None:
        """When rwa_pre_factor is missing, supporting impact should be 0."""
        crr = AggregatedResultBundle(
            results=pl.LazyFrame({
                "exposure_reference": ["EXP001"],
                "exposure_class": ["corporate"],
                "approach_applied": ["SA"],
                "ead_final": [1_000_000.0],
                "risk_weight": [1.0],
                "rwa_final": [100_000.0],
                # No rwa_pre_factor, no supporting_factor columns
            }),
            errors=[],
        )
        b31 = _make_b31_results(["EXP001"], rwa_finals=[85_000.0])
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]

        # Without rwa_pre_factor, defaults to rwa_final → supporting impact = 0
        assert row["supporting_factor_impact"] == pytest.approx(0.0)
        # All delta goes to methodology
        assert row["methodology_impact"] == pytest.approx(-15_000.0)

    def test_no_floor_impact_data_means_zero_floor_impact(self) -> None:
        """When floor_impact LazyFrame is None, floor impact should be 0."""
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["foundation_irb"],
            rwa_finals=[530_000.0],
            rwa_pre_factors=[530_000.0],
            supporting_factors=[1.0],
        )
        b31 = _make_b31_results(
            ["EXP001"],
            rwa_finals=[500_000.0],
            rwa_pre_floors=[500_000.0],
            floor_impact_data=None,
        )
        comparison = _make_comparison(crr, b31)

        attribution = _compute_exposure_attribution(comparison).collect()
        row = attribution.to_dicts()[0]
        assert row["output_floor_impact"] == pytest.approx(0.0)


# =============================================================================
# Test: CapitalImpactAnalyzer Integration
# =============================================================================


class TestCapitalImpactAnalyzer:
    """Integration tests for the CapitalImpactAnalyzer class."""

    def test_analyze_returns_capital_impact_bundle(self) -> None:
        """analyze() should return a CapitalImpactBundle with all fields."""
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["SA"],
            rwa_finals=[100_000.0],
            rwa_pre_factors=[100_000.0],
            supporting_factors=[1.0],
        )
        b31 = _make_b31_results(["EXP001"], rwa_finals=[85_000.0])
        comparison = _make_comparison(crr, b31)

        result = CapitalImpactAnalyzer().analyze(comparison)

        assert isinstance(result, CapitalImpactBundle)
        assert result.exposure_attribution is not None
        assert result.portfolio_waterfall is not None
        assert result.summary_by_class is not None
        assert result.summary_by_approach is not None

    def test_bundle_is_frozen(self) -> None:
        """CapitalImpactBundle should be immutable."""
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["SA"],
            rwa_finals=[100_000.0],
            rwa_pre_factors=[100_000.0],
            supporting_factors=[1.0],
        )
        b31 = _make_b31_results(["EXP001"], rwa_finals=[85_000.0])
        comparison = _make_comparison(crr, b31)

        result = CapitalImpactAnalyzer().analyze(comparison)

        with pytest.raises(AttributeError):
            result.exposure_attribution = pl.LazyFrame()  # type: ignore[misc]

    def test_errors_propagated_from_comparison(self) -> None:
        """Errors from the comparison bundle should propagate."""
        crr = _make_crr_results(
            ["EXP001"], ["corporate"], ["SA"],
            rwa_finals=[100_000.0],
            rwa_pre_factors=[100_000.0],
            supporting_factors=[1.0],
        )
        b31 = _make_b31_results(["EXP001"], rwa_finals=[85_000.0])
        comparison = ComparisonBundle(
            crr_results=crr,
            b31_results=b31,
            exposure_deltas=pl.LazyFrame(),
            summary_by_class=pl.LazyFrame(),
            summary_by_approach=pl.LazyFrame(),
            errors=["error1", "error2"],
        )

        result = CapitalImpactAnalyzer().analyze(comparison)
        assert len(result.errors) == 2
