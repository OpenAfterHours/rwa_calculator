"""
Unit tests for cross-approach SME supporting factor E* aggregation.

CRR Art. 501 defines E* (the SME tier threshold input) as the total drawn
amount owed by the SME's group of connected clients, regardless of which
regulatory approach (SA, IRB, slotting) each member is treated under.

The unified-frame helper ``compute_e_star_group_drawn`` runs once in the
pipeline orchestrator before the SA / IRB / slotting split, so siblings under
any approach contribute to the threshold calculation. Each branch's
``apply_factors`` then reads the pre-computed column rather than doing its
own per-branch window sum on its (partial) view of the lending group.

These tests verify:
1. ``compute_e_star_group_drawn`` sums drawn across all approach rows.
2. ``apply_factors`` reads ``e_star_group_drawn`` when present and produces
   the cross-approach blended factor.
3. The legacy per-branch fallback still works when the column is absent
   (preserves test harnesses that bypass the pipeline).
4. Disabled supporting factors (Basel 3.1) is a no-op.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.supporting_factors import (
    SupportingFactorCalculator,
    compute_e_star_group_drawn,
)


@pytest.fixture()
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2025, 12, 31))


@pytest.fixture()
def basel31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 12, 31))


def _make_mixed_approach_frame(rows: list[dict]) -> pl.LazyFrame:
    """Build a unified-frame LazyFrame spanning SA / IRB / slotting rows.

    Each row dict supports:
        ref, cp, lg, approach (SA/IRB/SLOTTING), drawn, interest, res_coll,
        is_sme, is_btl, ead, rwa, cp_annual_revenue.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [r["ref"] for r in rows],
            "counterparty_reference": [r["cp"] for r in rows],
            "lending_group_reference": [r.get("lg") for r in rows],
            "approach": [r.get("approach", "SA") for r in rows],
            "drawn_amount": [float(r.get("drawn", 0.0)) for r in rows],
            "interest": [float(r.get("interest", 0.0)) for r in rows],
            "residential_collateral_value": [float(r.get("res_coll", 0.0)) for r in rows],
            "is_sme": [bool(r.get("is_sme", False)) for r in rows],
            "is_buy_to_let": [bool(r.get("is_btl", False)) for r in rows],
            "is_infrastructure": [False] * len(rows),
            "is_defaulted": [False] * len(rows),
            "ead_final": [float(r.get("ead", r.get("drawn", 0.0))) for r in rows],
            "rwa_pre_factor": [float(r.get("rwa", 0.0)) for r in rows],
            "cp_annual_revenue": [r.get("cp_annual_revenue") for r in rows],
        }
    )


class TestComputeEStarGroupDrawn:
    """Tests for compute_e_star_group_drawn (unified-frame helper)."""

    def test_sums_across_sa_and_slotting_siblings(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        # Arrange: lending group LG1 with one SA SME row + one slotting row
        rows = [
            {
                "ref": "L1",
                "cp": "CP_SME",
                "lg": "LG1",
                "approach": "SA",
                "drawn": 1_000_000.0,
                "is_sme": True,
                "cp_annual_revenue": 5_000_000.0,
            },
            {
                "ref": "L2",
                "cp": "CP_SLOT",
                "lg": "LG1",
                "approach": "SLOTTING",
                "drawn": 5_000_000.0,
                "is_sme": False,
            },
        ]
        frame = _make_mixed_approach_frame(rows)

        # Act
        result = compute_e_star_group_drawn(frame, crr_config).collect()

        # Assert: both rows see the full group total (£6m)
        e_star = result["e_star_group_drawn"].to_list()
        assert e_star[0] == pytest.approx(6_000_000.0)
        assert e_star[1] == pytest.approx(6_000_000.0)

    def test_sums_across_sa_and_irb_siblings(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        rows = [
            {
                "ref": "L1",
                "cp": "CP_SME",
                "lg": "LG2",
                "approach": "SA",
                "drawn": 1_500_000.0,
                "is_sme": True,
                "cp_annual_revenue": 5_000_000.0,
            },
            {
                "ref": "L2",
                "cp": "CP_IRB",
                "lg": "LG2",
                "approach": "AIRB",
                "drawn": 3_000_000.0,
                "is_sme": False,
            },
        ]
        frame = _make_mixed_approach_frame(rows)

        result = compute_e_star_group_drawn(frame, crr_config).collect()

        e_star = result["e_star_group_drawn"].to_list()
        assert e_star[0] == pytest.approx(4_500_000.0)
        assert e_star[1] == pytest.approx(4_500_000.0)

    def test_residential_carveout_netted_pre_aggregation(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        # Art. 501 excludes claims secured on residential collateral.
        rows = [
            {
                "ref": "L1",
                "cp": "CP_SME",
                "lg": "LG3",
                "approach": "SA",
                "drawn": 1_000_000.0,
                "res_coll": 400_000.0,  # nets to 600k contribution
                "is_sme": True,
                "cp_annual_revenue": 5_000_000.0,
            },
            {
                "ref": "L2",
                "cp": "CP_SLOT",
                "lg": "LG3",
                "approach": "SLOTTING",
                "drawn": 2_000_000.0,
                "res_coll": 0.0,  # 2m contribution
                "is_sme": False,
            },
        ]
        frame = _make_mixed_approach_frame(rows)

        result = compute_e_star_group_drawn(frame, crr_config).collect()

        # Expected total: (1.0m - 0.4m) + 2.0m = 2.6m
        e_star = result["e_star_group_drawn"].to_list()
        assert e_star[0] == pytest.approx(2_600_000.0)
        assert e_star[1] == pytest.approx(2_600_000.0)

    def test_interest_included_in_contribution(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        rows = [
            {
                "ref": "L1",
                "cp": "CP_SME",
                "lg": "LG4",
                "approach": "SA",
                "drawn": 1_000_000.0,
                "interest": 20_000.0,
                "is_sme": True,
                "cp_annual_revenue": 5_000_000.0,
            },
        ]
        frame = _make_mixed_approach_frame(rows)

        result = compute_e_star_group_drawn(frame, crr_config).collect()

        assert result["e_star_group_drawn"][0] == pytest.approx(1_020_000.0)

    def test_no_op_when_supporting_factors_disabled(
        self,
        basel31_config: CalculationConfig,
    ) -> None:
        # Basel 3.1: supporting factors disabled, helper returns frame unchanged.
        rows = [
            {
                "ref": "L1",
                "cp": "CP1",
                "lg": "LG5",
                "approach": "SA",
                "drawn": 1_000_000.0,
                "is_sme": True,
            },
        ]
        frame = _make_mixed_approach_frame(rows)

        result = compute_e_star_group_drawn(frame, basel31_config).collect()

        assert "e_star_group_drawn" not in result.columns

    def test_lending_group_fallback_to_counterparty(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        # No lending group → falls back to counterparty_reference for grouping.
        rows = [
            {
                "ref": "L1",
                "cp": "CP_SME",
                "lg": None,
                "approach": "SA",
                "drawn": 1_000_000.0,
                "is_sme": True,
                "cp_annual_revenue": 5_000_000.0,
            },
            {
                "ref": "L2",
                "cp": "CP_SME",
                "lg": None,
                "approach": "SA",
                "drawn": 500_000.0,
                "is_sme": True,
                "cp_annual_revenue": 5_000_000.0,
            },
        ]
        frame = _make_mixed_approach_frame(rows)

        result = compute_e_star_group_drawn(frame, crr_config).collect()

        e_star = result["e_star_group_drawn"].to_list()
        assert e_star[0] == pytest.approx(1_500_000.0)
        assert e_star[1] == pytest.approx(1_500_000.0)


class TestApplyFactorsReadsPreComputedColumn:
    """apply_factors reads e_star_group_drawn when present (pipeline mode)."""

    def test_blended_factor_uses_pre_computed_group_total(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        # SA SME row sees the full cross-approach E* via e_star_group_drawn.
        # Under the legacy per-branch path it would have seen only its own
        # £1m, getting factor=0.7619. With the cross-approach E* = £6m, the
        # blended factor is (2.2m * 0.7619 + 3.8m * 0.85) / 6m ≈ 0.8177.
        sa_row = pl.LazyFrame(
            {
                "exposure_reference": ["L1"],
                "counterparty_reference": ["CP_SME"],
                "lending_group_reference": ["LG1"],
                "drawn_amount": [1_000_000.0],
                "interest": [0.0],
                "residential_collateral_value": [0.0],
                "is_sme": [True],
                "is_buy_to_let": [False],
                "is_infrastructure": [False],
                "is_defaulted": [False],
                "ead_final": [1_000_000.0],
                "rwa_pre_factor": [750_000.0],
                "cp_annual_revenue": [5_000_000.0],
                "e_star_group_drawn": [6_000_000.0],
            }
        )

        result = SupportingFactorCalculator().apply_factors(sa_row, crr_config).collect()

        assert result["total_cp_drawn"][0] == pytest.approx(6_000_000.0)
        # Blended factor derived from the actual config (threshold is GBP, not EUR).
        threshold = float(crr_config.thresholds.sme_exposure_threshold)
        tier1_factor = float(crr_config.supporting_factors.sme_factor_under_threshold)
        tier2_factor = float(crr_config.supporting_factors.sme_factor_above_threshold)
        e_star = 6_000_000.0
        expected_factor = (threshold * tier1_factor + (e_star - threshold) * tier2_factor) / e_star
        assert result["supporting_factor"][0] == pytest.approx(expected_factor, rel=1e-6)

    def test_legacy_per_branch_fallback_when_column_absent(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        # No e_star_group_drawn column: apply_factors falls back to the
        # per-branch window sum. Sum across the two rows = £1.5m (below £2.2m
        # threshold) so the blended factor is pure tier 1 = 0.7619.
        sa_only = pl.LazyFrame(
            {
                "exposure_reference": ["L1", "L2"],
                "counterparty_reference": ["CP_A", "CP_B"],
                "lending_group_reference": ["LG_X", "LG_X"],
                "drawn_amount": [1_000_000.0, 500_000.0],
                "interest": [0.0, 0.0],
                "residential_collateral_value": [0.0, 0.0],
                "is_sme": [True, True],
                "is_buy_to_let": [False, False],
                "is_infrastructure": [False, False],
                "is_defaulted": [False, False],
                "ead_final": [1_000_000.0, 500_000.0],
                "rwa_pre_factor": [750_000.0, 375_000.0],
                "cp_annual_revenue": [5_000_000.0, 5_000_000.0],
            }
        )

        result = SupportingFactorCalculator().apply_factors(sa_only, crr_config).collect()

        # Group total £1.5m for both rows
        assert result["total_cp_drawn"].to_list() == [
            pytest.approx(1_500_000.0),
            pytest.approx(1_500_000.0),
        ]
        # Pure tier 1: blended factor = 0.7619
        for f in result["supporting_factor"].to_list():
            assert f == pytest.approx(0.7619, rel=1e-4)
