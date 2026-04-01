"""
Unit tests for OutputAggregator contract compliance and bundle structure.

Tests cover:
- OutputAggregator satisfies OutputAggregatorProtocol
- AggregatedResultBundle has all expected fields
- Empty inputs produce valid (empty) outputs
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.protocols import OutputAggregatorProtocol
from rwa_calc.engine.aggregator import OutputAggregator

EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})


class TestOutputAggregatorProtocolCompliance:
    """Tests that OutputAggregator satisfies OutputAggregatorProtocol."""

    def test_satisfies_protocol(self) -> None:
        aggregator = OutputAggregator()
        assert isinstance(aggregator, OutputAggregatorProtocol)

    def test_aggregate_method_exists(self) -> None:
        assert hasattr(OutputAggregator, "aggregate")


class TestEmptyInputs:
    """Tests that OutputAggregator handles empty inputs gracefully."""

    def test_empty_inputs_produce_valid_bundle(self) -> None:
        """Aggregate with all empty inputs returns valid bundle."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        aggregator = OutputAggregator()

        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=EMPTY,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=config,
        )

        assert result.results is not None
        assert result.results.collect().shape[0] == 0
        assert result.el_summary is None
        assert result.floor_impact is None
        assert result.errors == []

    def test_bundle_has_all_summary_fields(self) -> None:
        """AggregatedResultBundle has all summary LazyFrames."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        aggregator = OutputAggregator()

        result = aggregator.aggregate(
            sa_results=EMPTY,
            irb_results=EMPTY,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=config,
        )

        assert result.summary_by_class is not None
        assert result.summary_by_approach is not None
        assert result.pre_crm_summary is not None
        assert result.post_crm_detailed is not None
        assert result.post_crm_summary is not None

    @pytest.mark.parametrize(
        "field",
        [
            "sa_results",
            "irb_results",
            "slotting_results",
        ],
    )
    def test_per_approach_results_preserved(self, field: str) -> None:
        """Per-approach results are passed through on the bundle."""
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        aggregator = OutputAggregator()

        sa = pl.LazyFrame(
            {
                "exposure_reference": ["SA1"],
                "approach_applied": ["SA"],
                "rwa_final": [100.0],
            }
        )
        irb = pl.LazyFrame(
            {
                "exposure_reference": ["IRB1"],
                "approach_applied": ["FIRB"],
                "rwa_final": [200.0],
            }
        )
        slotting = pl.LazyFrame(
            {
                "exposure_reference": ["SLOT1"],
                "approach_applied": ["SLOTTING"],
                "rwa_final": [300.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=sa,
            irb_results=irb,
            slotting_results=slotting,
            equity_bundle=None,
            config=config,
        )

        branch_df = getattr(result, field).collect()
        assert len(branch_df) == 1
