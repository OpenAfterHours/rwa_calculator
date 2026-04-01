"""
Integration tests: Equity Flow.

Validates the equity exposure path through the pipeline: classification
determines equity routing, CRM passes equity through unchanged, the
EquityCalculator applies correct risk weights, and the aggregation
includes equity in the final results.

Why Priority 5: Equity is a separate path outside the main unified frame
(SA/IRB/slotting). It bypasses CRM entirely and uses its own calculator
with simpler risk weight logic (no correlation formula, no maturity
adjustment). Lower priority because it is less interconnected than the
main credit risk pipeline, but still needs integration coverage to verify
the pass-through wiring and approach determination logic.

Components wired: Classifier → EquityCalculator → aggregation
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.aggregator import (
    generate_post_crm_detailed,
    generate_summary_by_approach,
    prepare_equity_results,
)
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.equity.calculator import EquityCalculator
from rwa_calc.engine.hierarchy import HierarchyResolver

from .conftest import (
    make_counterparty,
    make_equity_exposure,
    make_facility,
    make_loan,
    make_raw_data_bundle,
)

# =============================================================================
# HELPERS
# =============================================================================


def _run_through_hierarchy_classifier_crm(
    bundle,
    config: CalculationConfig,
    hierarchy_resolver: HierarchyResolver,
    classifier: ExposureClassifier,
    crm_processor: CRMProcessor,
) -> CRMAdjustedBundle:
    """Run a RawDataBundle through hierarchy → classifier → CRM."""
    resolved = hierarchy_resolver.resolve(bundle, config)
    classified = classifier.classify(resolved, config)
    return crm_processor.get_crm_adjusted_bundle(classified, config)


def _build_crm_adjusted_with_equity(
    equity_rows: list[dict],
) -> CRMAdjustedBundle:
    """Build a minimal CRMAdjustedBundle with equity exposures for direct calculator tests."""
    from rwa_calc.data.schemas import EQUITY_EXPOSURE_SCHEMA

    from .conftest import _rows_to_lazyframe

    equity_lf = _rows_to_lazyframe(equity_rows, EQUITY_EXPOSURE_SCHEMA)
    # Minimal SA/IRB/exposures frames to satisfy the bundle
    empty = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})
    return CRMAdjustedBundle(
        exposures=empty,
        sa_exposures=empty,
        irb_exposures=empty,
        equity_exposures=equity_lf,
    )


# =============================================================================
# TEST CLASS: Approach Selection
# =============================================================================


class TestEquityApproachSelection:
    """Verify equity approach is determined correctly by config."""

    def test_equity_sa_approach_when_sa_only(
        self,
        equity_calculator: EquityCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """SA-only config → Article 133 SA weights applied."""
        # Arrange
        crm_bundle = _build_crm_adjusted_with_equity(
            [make_equity_exposure(equity_type="listed", fair_value=100_000.0)]
        )

        # Act
        result = equity_calculator.get_equity_result_bundle(crm_bundle, crr_config)

        # Assert
        assert result.approach == "sa"

    def test_equity_irb_simple_when_irb_permitted(
        self,
        equity_calculator: EquityCalculator,
        crr_full_irb_config: CalculationConfig,
    ) -> None:
        """CRR with IRB permissions → Article 155 IRB Simple weights."""
        # Arrange
        crm_bundle = _build_crm_adjusted_with_equity(
            [make_equity_exposure(equity_type="listed", fair_value=100_000.0)]
        )

        # Act
        result = equity_calculator.get_equity_result_bundle(crm_bundle, crr_full_irb_config)

        # Assert
        assert result.approach == "irb_simple"

    def test_equity_forced_sa_under_basel31(
        self,
        equity_calculator: EquityCalculator,
        basel31_full_irb_config: CalculationConfig,
    ) -> None:
        """Basel 3.1 removes IRB for equity — always SA regardless of IRB permissions."""
        # Arrange
        crm_bundle = _build_crm_adjusted_with_equity(
            [make_equity_exposure(equity_type="listed", fair_value=100_000.0)]
        )

        # Act
        result = equity_calculator.get_equity_result_bundle(crm_bundle, basel31_full_irb_config)

        # Assert — IRB permissions exist but equity forced to SA under Basel 3.1
        assert result.approach == "sa"


# =============================================================================
# TEST CLASS: Risk Weights
# =============================================================================


class TestEquityRiskWeights:
    """Verify correct risk weights for each equity type under SA and IRB Simple."""

    def test_listed_equity_100_percent_sa(
        self,
        equity_calculator: EquityCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Listed equity under SA → 100% risk weight (Art. 133)."""
        crm_bundle = _build_crm_adjusted_with_equity(
            [make_equity_exposure(equity_type="listed", fair_value=200_000.0)]
        )
        result = equity_calculator.get_equity_result_bundle(crm_bundle, crr_config)
        df = result.results.collect()

        assert df["risk_weight"][0] == pytest.approx(1.00)
        assert df["rwa"][0] == pytest.approx(200_000.0)

    def test_speculative_equity_400_percent_sa(
        self,
        equity_calculator: EquityCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Speculative equity under SA → 400% risk weight (Art. 133)."""
        crm_bundle = _build_crm_adjusted_with_equity(
            [
                make_equity_exposure(
                    equity_type="speculative",
                    is_speculative=True,
                    fair_value=50_000.0,
                )
            ]
        )
        result = equity_calculator.get_equity_result_bundle(crm_bundle, crr_config)
        df = result.results.collect()

        assert df["risk_weight"][0] == pytest.approx(4.00)
        assert df["rwa"][0] == pytest.approx(200_000.0)

    def test_unlisted_equity_250_percent_sa(
        self,
        equity_calculator: EquityCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Unlisted equity under SA → 250% risk weight (Art. 133)."""
        crm_bundle = _build_crm_adjusted_with_equity(
            [make_equity_exposure(equity_type="unlisted", fair_value=100_000.0)]
        )
        result = equity_calculator.get_equity_result_bundle(crm_bundle, crr_config)
        df = result.results.collect()

        assert df["risk_weight"][0] == pytest.approx(2.50)
        assert df["rwa"][0] == pytest.approx(250_000.0)

    def test_irb_simple_listed_290_percent(
        self,
        equity_calculator: EquityCalculator,
        crr_full_irb_config: CalculationConfig,
    ) -> None:
        """Listed equity under IRB Simple → 290% risk weight (Art. 155)."""
        crm_bundle = _build_crm_adjusted_with_equity(
            [make_equity_exposure(equity_type="listed", fair_value=100_000.0)]
        )
        result = equity_calculator.get_equity_result_bundle(crm_bundle, crr_full_irb_config)
        df = result.results.collect()

        assert result.approach == "irb_simple"
        assert df["risk_weight"][0] == pytest.approx(2.90)
        assert df["rwa"][0] == pytest.approx(290_000.0)

    def test_irb_simple_private_equity_diversified_190_percent(
        self,
        equity_calculator: EquityCalculator,
        crr_full_irb_config: CalculationConfig,
    ) -> None:
        """Private equity (diversified) under IRB Simple → 190% (Art. 155)."""
        crm_bundle = _build_crm_adjusted_with_equity(
            [
                make_equity_exposure(
                    equity_type="private_equity_diversified",
                    fair_value=100_000.0,
                )
            ]
        )
        result = equity_calculator.get_equity_result_bundle(crm_bundle, crr_full_irb_config)
        df = result.results.collect()

        assert result.approach == "irb_simple"
        assert df["risk_weight"][0] == pytest.approx(1.90)
        assert df["rwa"][0] == pytest.approx(190_000.0)


# =============================================================================
# TEST CLASS: Aggregation
# =============================================================================


class TestEquityAggregation:
    """Verify equity results integrate correctly into aggregated output."""

    def test_equity_results_in_aggregated_output(
        self,
        equity_calculator: EquityCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Equity bundle is included in the aggregated combined results."""
        # Arrange — create a minimal SA result + equity result
        sa_results = pl.LazyFrame(
            {
                "exposure_reference": ["LN001"],
                "exposure_class": ["corporate"],
                "approach_applied": ["SA"],
                "ead_final": [1_000_000.0],
                "risk_weight": [1.0],
                "rwa_final": [1_000_000.0],
            }
        )

        crm_bundle = _build_crm_adjusted_with_equity(
            [make_equity_exposure(equity_type="listed", fair_value=500_000.0)]
        )
        equity_bundle = equity_calculator.get_equity_result_bundle(crm_bundle, crr_config)
        equity_prepared = prepare_equity_results(equity_bundle.results)

        # Act — combine using free functions
        combined = pl.concat([sa_results, equity_prepared], how="diagonal_relaxed")
        combined_df = combined.collect()

        # Assert — equity row present in combined results
        equity_rows = combined_df.filter(pl.col("approach_applied") == "EQUITY")
        assert len(equity_rows) == 1
        assert equity_rows["rwa_final"][0] == pytest.approx(500_000.0)  # 100% RW x 500k

    def test_equity_separate_from_unified_frame(
        self,
        equity_calculator: EquityCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Equity results have approach_applied='EQUITY', distinct from SA/IRB/SLOTTING."""
        sa_results = pl.LazyFrame(
            {
                "exposure_reference": ["LN001"],
                "exposure_class": ["corporate"],
                "approach_applied": ["SA"],
                "ead_final": [1_000_000.0],
                "risk_weight": [1.0],
                "rwa_final": [1_000_000.0],
            }
        )
        crm_bundle = _build_crm_adjusted_with_equity(
            [
                make_equity_exposure(
                    exposure_reference="EQ001", equity_type="listed", fair_value=100_000.0
                ),
                make_equity_exposure(
                    exposure_reference="EQ002", equity_type="unlisted", fair_value=200_000.0
                ),
            ]
        )
        equity_bundle = equity_calculator.get_equity_result_bundle(crm_bundle, crr_config)
        equity_prepared = prepare_equity_results(equity_bundle.results)

        combined = pl.concat([sa_results, equity_prepared], how="diagonal_relaxed")
        combined_df = combined.collect()

        approaches = combined_df["approach_applied"].unique().to_list()
        assert "EQUITY" in approaches
        assert "SA" in approaches
        equity_rows = combined_df.filter(pl.col("approach_applied") == "EQUITY")
        assert len(equity_rows) == 2

    def test_equity_summary_by_approach(
        self,
        equity_calculator: EquityCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Equity has its own row in the approach summary."""
        sa_results = pl.LazyFrame(
            {
                "exposure_reference": ["LN001"],
                "exposure_class": ["corporate"],
                "approach_applied": ["SA"],
                "ead_final": [1_000_000.0],
                "risk_weight": [1.0],
                "rwa_final": [1_000_000.0],
            }
        )
        crm_bundle = _build_crm_adjusted_with_equity(
            [make_equity_exposure(equity_type="listed", fair_value=300_000.0)]
        )
        equity_bundle = equity_calculator.get_equity_result_bundle(crm_bundle, crr_config)
        equity_prepared = prepare_equity_results(equity_bundle.results)

        combined = pl.concat([sa_results, equity_prepared], how="diagonal_relaxed")
        post_crm_detailed = generate_post_crm_detailed(combined)
        summary = generate_summary_by_approach(post_crm_detailed)

        summary_df = summary.collect()
        approaches_in_summary = summary_df["approach_applied"].to_list()
        assert "EQUITY" in approaches_in_summary


# =============================================================================
# TEST CLASS: Pipeline Pass-Through
# =============================================================================


class TestEquityPipelinePassThrough:
    """Verify equity exposures pass through hierarchy → classifier → CRM untouched."""

    def test_equity_passes_through_hierarchy_and_classifier(
        self,
        hierarchy_resolver: HierarchyResolver,
        classifier: ExposureClassifier,
        crm_processor: CRMProcessor,
        crr_config: CalculationConfig,
    ) -> None:
        """Equity exposures survive hierarchy + classifier + CRM pass-through intact."""
        # Arrange — bundle with both normal loan and equity exposure
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty()],
            loans=[make_loan()],
            facilities=[make_facility()],
            equity_exposures=[
                make_equity_exposure(
                    exposure_reference="EQ_PASS",
                    equity_type="listed",
                    fair_value=750_000.0,
                ),
            ],
        )

        # Act — run through hierarchy → classifier → CRM
        crm_adjusted = _run_through_hierarchy_classifier_crm(
            bundle, crr_config, hierarchy_resolver, classifier, crm_processor
        )

        # Assert — equity exposures still present and unchanged
        assert crm_adjusted.equity_exposures is not None
        eq_df = crm_adjusted.equity_exposures.collect()
        assert len(eq_df) == 1
        assert eq_df["exposure_reference"][0] == "EQ_PASS"
        assert eq_df["fair_value"][0] == pytest.approx(750_000.0)

    def test_multiple_equity_types_flow_through_pipeline(
        self,
        hierarchy_resolver: HierarchyResolver,
        classifier: ExposureClassifier,
        crm_processor: CRMProcessor,
        equity_calculator: EquityCalculator,
        crr_config: CalculationConfig,
    ) -> None:
        """Multiple equity types flow through full pipeline and get correct risk weights."""
        # Arrange
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty()],
            loans=[make_loan()],
            facilities=[make_facility()],
            equity_exposures=[
                make_equity_exposure(
                    exposure_reference="EQ_LIST",
                    equity_type="listed",
                    fair_value=100_000.0,
                ),
                make_equity_exposure(
                    exposure_reference="EQ_SPEC",
                    equity_type="speculative",
                    is_speculative=True,
                    fair_value=50_000.0,
                ),
                make_equity_exposure(
                    exposure_reference="EQ_UNLIST",
                    equity_type="unlisted",
                    fair_value=200_000.0,
                ),
            ],
        )

        # Act — full pipeline through to equity calculator
        crm_adjusted = _run_through_hierarchy_classifier_crm(
            bundle, crr_config, hierarchy_resolver, classifier, crm_processor
        )
        result = equity_calculator.get_equity_result_bundle(crm_adjusted, crr_config)

        # Assert
        df = result.results.collect()
        assert len(df) == 3
        assert result.approach == "sa"

        # Check risk weights by reference
        rw_by_ref = dict(
            zip(df["exposure_reference"].to_list(), df["risk_weight"].to_list(), strict=True)
        )
        assert rw_by_ref["EQ_LIST"] == pytest.approx(1.00)
        assert rw_by_ref["EQ_SPEC"] == pytest.approx(4.00)
        assert rw_by_ref["EQ_UNLIST"] == pytest.approx(2.50)
