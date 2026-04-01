"""
Integration tests for Pre/Post CRM regulatory reporting.

Tests the OutputAggregator's ability to generate pre-CRM and post-CRM
summary views for regulatory reporting (COREP).
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.aggregator import OutputAggregator

EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Create CRR configuration for tests."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def aggregator() -> OutputAggregator:
    return OutputAggregator()


class TestPostCRMDetailedView:
    """Tests for post-CRM detailed view with split rows."""

    def test_post_crm_detailed_creates_two_rows_for_guaranteed(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Guaranteed exposure should generate two reporting rows."""
        sa_results = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["SA"],
                "ead_final": [1_000_000.0],
                "risk_weight": [0.58],
                "rwa_final": [580_000.0],
                "pre_crm_counterparty_reference": ["CP001"],
                "pre_crm_exposure_class": ["CORPORATE"],
                "post_crm_counterparty_guaranteed": ["GUAR001"],
                "post_crm_exposure_class_guaranteed": ["CENTRAL_GOVT_CENTRAL_BANK"],
                "is_guaranteed": [True],
                "guaranteed_portion": [600_000.0],
                "unguaranteed_portion": [400_000.0],
                "guarantor_reference": ["GUAR001"],
                "pre_crm_risk_weight": [1.0],
                "guarantor_rw": [0.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=EMPTY,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        detailed_df = result.post_crm_detailed.collect()

        # Should have 2 rows for the guaranteed exposure
        assert len(detailed_df) == 2

        # Row 1: Unguaranteed portion under original borrower
        unguar_row = detailed_df.filter(pl.col("crm_portion_type") == "unguaranteed")
        assert len(unguar_row) == 1
        assert unguar_row["reporting_counterparty"][0] == "CP001"
        assert unguar_row["reporting_exposure_class"][0] == "CORPORATE"
        assert unguar_row["reporting_ead"][0] == pytest.approx(400_000.0)

        # Row 2: Guaranteed portion under guarantor
        guar_row = detailed_df.filter(pl.col("crm_portion_type") == "guaranteed")
        assert len(guar_row) == 1
        assert guar_row["reporting_counterparty"][0] == "GUAR001"
        assert guar_row["reporting_exposure_class"][0] == "CENTRAL_GOVT_CENTRAL_BANK"
        assert guar_row["reporting_ead"][0] == pytest.approx(600_000.0)

    def test_non_guaranteed_exposure_single_row(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Non-guaranteed exposure should have single reporting row."""
        sa_results = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["SA"],
                "ead_final": [1_000_000.0],
                "risk_weight": [1.0],
                "rwa_final": [1_000_000.0],
                "pre_crm_counterparty_reference": ["CP001"],
                "pre_crm_exposure_class": ["CORPORATE"],
                "post_crm_counterparty_guaranteed": ["CP001"],
                "post_crm_exposure_class_guaranteed": ["CORPORATE"],
                "is_guaranteed": [False],
                "guaranteed_portion": [0.0],
                "unguaranteed_portion": [1_000_000.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=EMPTY,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        detailed_df = result.post_crm_detailed.collect()
        assert len(detailed_df) == 1
        assert detailed_df["crm_portion_type"][0] == "original"


class TestPreCRMSummary:
    """Tests for pre-CRM summary view."""

    def test_pre_crm_summary_shows_original_class(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Pre-CRM summary groups all EAD under original borrower's class."""
        sa_results = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "counterparty_reference": ["CP001", "CP002"],
                "exposure_class": ["CORPORATE", "CORPORATE"],
                "approach_applied": ["SA", "SA"],
                "ead_final": [1_000_000.0, 500_000.0],
                "risk_weight": [0.58, 1.0],
                "rwa_final": [580_000.0, 500_000.0],
                "pre_crm_counterparty_reference": ["CP001", "CP002"],
                "pre_crm_exposure_class": ["CORPORATE", "CORPORATE"],
                "post_crm_counterparty_guaranteed": ["GUAR001", "CP002"],
                "post_crm_exposure_class_guaranteed": [
                    "CENTRAL_GOVT_CENTRAL_BANK",
                    "CORPORATE",
                ],
                "is_guaranteed": [True, False],
                "guaranteed_portion": [600_000.0, 0.0],
                "unguaranteed_portion": [400_000.0, 500_000.0],
                "pre_crm_risk_weight": [1.0, 1.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=EMPTY,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        summary_df = result.pre_crm_summary.collect()
        corp_row = summary_df.filter(pl.col("pre_crm_exposure_class") == "CORPORATE")
        assert len(corp_row) == 1

        assert corp_row["total_ead"][0] == pytest.approx(1_500_000.0)
        assert corp_row["total_rwa_blended"][0] == pytest.approx(1_080_000.0)


class TestPostCRMSummary:
    """Tests for post-CRM summary view."""

    def test_post_crm_summary_splits_by_guarantor_class(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Guaranteed portion should aggregate under guarantor's exposure class."""
        sa_results = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001"],
                "counterparty_reference": ["CP001"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["SA"],
                "ead_final": [1_000_000.0],
                "risk_weight": [0.58],
                "rwa_final": [580_000.0],
                "pre_crm_counterparty_reference": ["CP001"],
                "pre_crm_exposure_class": ["CORPORATE"],
                "post_crm_counterparty_guaranteed": ["GUAR001"],
                "post_crm_exposure_class_guaranteed": ["CENTRAL_GOVT_CENTRAL_BANK"],
                "is_guaranteed": [True],
                "guaranteed_portion": [600_000.0],
                "unguaranteed_portion": [400_000.0],
                "guarantor_reference": ["GUAR001"],
                "pre_crm_risk_weight": [1.0],
                "guarantor_rw": [0.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=EMPTY,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        summary_df = result.post_crm_summary.collect()
        assert len(summary_df) == 2

        corp_row = summary_df.filter(pl.col("reporting_exposure_class") == "CORPORATE")
        assert len(corp_row) == 1
        assert corp_row["total_ead"][0] == pytest.approx(400_000.0)
        assert corp_row["total_rwa"][0] == pytest.approx(400_000.0)

        sov_row = summary_df.filter(
            pl.col("reporting_exposure_class") == "CENTRAL_GOVT_CENTRAL_BANK"
        )
        assert len(sov_row) == 1
        assert sov_row["total_ead"][0] == pytest.approx(600_000.0)
        assert sov_row["total_rwa"][0] == pytest.approx(0.0)
        assert sov_row["guaranteed_portions"][0] == 1


class TestMixedSAIRBPortfolio:
    """Tests for mixed SA and IRB portfolios."""

    def test_mixed_sa_irb_portfolio_aggregation(
        self,
        aggregator: OutputAggregator,
        crr_config: CalculationConfig,
    ) -> None:
        """Aggregation handles mixed SA and IRB exposures with guarantees."""
        sa_results = pl.LazyFrame(
            {
                "exposure_reference": ["SA001"],
                "counterparty_reference": ["CP001"],
                "exposure_class": ["CORPORATE"],
                "approach_applied": ["SA"],
                "ead_final": [500_000.0],
                "risk_weight": [0.6],
                "rwa_final": [300_000.0],
                "pre_crm_exposure_class": ["CORPORATE"],
                "post_crm_exposure_class_guaranteed": ["INSTITUTION"],
                "is_guaranteed": [True],
                "guaranteed_portion": [250_000.0],
                "unguaranteed_portion": [250_000.0],
                "pre_crm_risk_weight": [1.0],
                "guarantor_rw": [0.2],
            }
        )

        irb_results = pl.LazyFrame(
            {
                "exposure_reference": ["IRB001"],
                "counterparty_reference": ["CP002"],
                "exposure_class": ["CORPORATE"],
                "approach": ["FIRB"],
                "approach_applied": ["FIRB"],
                "ead_final": [1_000_000.0],
                "risk_weight": [0.3],
                "rwa_final": [300_000.0],
                "pre_crm_exposure_class": ["CORPORATE"],
                "post_crm_exposure_class_guaranteed": ["CENTRAL_GOVT_CENTRAL_BANK"],
                "is_guaranteed": [True],
                "guaranteed_portion": [500_000.0],
                "unguaranteed_portion": [500_000.0],
                "pre_crm_risk_weight": [0.5],
                "guarantor_rw": [0.0],
            }
        )

        result = aggregator.aggregate(
            sa_results=sa_results,
            irb_results=irb_results,
            slotting_results=EMPTY,
            equity_bundle=None,
            config=crr_config,
        )

        # Pre-CRM summary should show all under CORPORATE
        pre_crm_df = result.pre_crm_summary.collect()
        corp_row = pre_crm_df.filter(pl.col("pre_crm_exposure_class") == "CORPORATE")
        assert corp_row["total_ead"][0] == pytest.approx(1_500_000.0)
        assert corp_row["exposure_count"][0] == 2

        # Post-CRM summary should show split across classes
        post_crm_df = result.post_crm_summary.collect()
        assert len(post_crm_df) >= 2
