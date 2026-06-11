"""
Unit tests: aggregator summary views are eager-backed (migration Phase 1).

The aggregator receives already-eager calculator branches and must not hand
back deep lazy plans over them: every frame field on AggregatedResultBundle
is collected once inside ``aggregate()`` and wrapped back with ``.lazy()``,
so a downstream ``.collect()`` is a near-free shallow collect instead of a
plan re-execution (the api/models.py accessors and api/rest.py endpoints
previously re-executed the same summary plans once per call).

The check is structural, not timing-based: a ``DataFrame.lazy()`` wrapper
renders as a single DF node in the unoptimised plan, so ``plan_node_count``
(the same depth metric the stage-edge ceiling tests use) must be tiny for
every non-None frame field. A lazily rebuilt summary would carry the concat
/ group_by / floor expression nodes and blow straight past the bound.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.aggregator import OutputAggregator
from rwa_calc.engine.materialise import plan_node_count

# =============================================================================
# Fixtures / constants
# =============================================================================

EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})

# A DataFrame.lazy() wrapper renders as a single DF node in the unoptimised
# plan; allow one line of slack for renderer changes across Polars versions.
_SHALLOW_PLAN_MAX_NODES = 2

# Every LazyFrame-typed field on AggregatedResultBundle that aggregate()
# builds itself (the sa/irb/slotting/equity passthroughs are the callers').
_FRAME_FIELDS = (
    "results",
    "floor_impact",
    "supporting_factor_impact",
    "summary_by_class",
    "summary_by_approach",
    "pre_crm_summary",
    "post_crm_detailed",
    "post_crm_summary",
    "securitisation_summary",
    "securitisation_audit",
)


@pytest.fixture
def aggregator() -> OutputAggregator:
    return OutputAggregator()


@pytest.fixture
def sa_results() -> pl.LazyFrame:
    """SA results carrying supporting-factor columns (CRR impact view)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP001", "EXP002"],
            "counterparty_reference": ["CP001", "CP002"],
            "exposure_class": ["CORPORATE", "RETAIL"],
            "approach_applied": ["SA", "SA"],
            "ead_final": [1_000_000.0, 500_000.0],
            "risk_weight": [1.0, 0.75],
            "rwa_pre_factor": [1_000_000.0, 375_000.0],
            "supporting_factor": [0.7619, 1.0],
            "rwa_post_factor": [761_900.0, 375_000.0],
            "rwa_final": [761_900.0, 375_000.0],
            "supporting_factor_applied": [True, False],
            "is_sme": [True, False],
            "is_infrastructure": [False, False],
        }
    )


@pytest.fixture
def irb_results_with_sa_rwa() -> pl.LazyFrame:
    """IRB results with sa_rwa so the Basel 3.1 output floor can run."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP003"],
            "exposure_class": ["CORPORATE"],
            "approach_applied": ["FIRB"],
            "ead_final": [100_000_000.0],
            "risk_weight": [0.5],
            "rwa_final": [50_000_000.0],
            "sa_rwa": [100_000_000.0],
        }
    )


def _assert_all_frames_shallow(bundle: AggregatedResultBundle) -> None:
    """Every non-None aggregate-built frame field must be eager-backed."""
    for name in _FRAME_FIELDS:
        lf = getattr(bundle, name)
        if lf is None:
            continue
        nodes = plan_node_count(lf)
        assert nodes <= _SHALLOW_PLAN_MAX_NODES, (
            f"{name} is not eager-backed: unoptimised plan has {nodes} nodes "
            f"(expected <= {_SHALLOW_PLAN_MAX_NODES}). The aggregator must "
            "collect its summary views once and wrap them back with .lazy()."
        )


# =============================================================================
# Tests
# =============================================================================


class TestAggregatorEagerBackedViews:
    """aggregate() materialises its summary views once (Phase 1 contract)."""

    def test_crr_aggregate_frame_fields_are_eager_backed(
        self,
        aggregator: OutputAggregator,
        sa_results: pl.LazyFrame,
        irb_results_with_sa_rwa: pl.LazyFrame,
    ) -> None:
        """Under CRR every built frame (incl. supporting factors) is shallow."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))

        bundle = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=irb_results_with_sa_rwa,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=config,
        )

        assert bundle.supporting_factor_impact is not None
        _assert_all_frames_shallow(bundle)

    def test_basel31_floor_impact_is_eager_backed(
        self,
        aggregator: OutputAggregator,
        irb_results_with_sa_rwa: pl.LazyFrame,
    ) -> None:
        """When the output floor runs, the floored results and the per-row
        floor impact view are both eager-backed."""
        config = CalculationConfig.basel_3_1(reporting_date=date(2032, 1, 1))

        bundle = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=irb_results_with_sa_rwa,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=config,
        )

        assert bundle.floor_impact is not None
        _assert_all_frames_shallow(bundle)

    def test_crr_preserves_none_fields(
        self,
        aggregator: OutputAggregator,
        sa_results: pl.LazyFrame,
    ) -> None:
        """Materialisation must not invent frames: floor_impact stays None
        under CRR and the securitisation views stay None without allocations."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))

        bundle = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=EMPTY,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=config,
        )

        assert bundle.floor_impact is None
        assert bundle.securitisation_summary is None
        assert bundle.securitisation_audit is None

    def test_eager_backed_results_collect_to_same_values(
        self,
        aggregator: OutputAggregator,
        sa_results: pl.LazyFrame,
        irb_results_with_sa_rwa: pl.LazyFrame,
    ) -> None:
        """Recompute elimination is behaviour-neutral: repeated collects of
        the same field return identical data."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))

        bundle = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=irb_results_with_sa_rwa,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=config,
        )

        first = bundle.results.collect()
        second = bundle.results.collect()
        assert first.equals(second)
        assert first.height == 3
