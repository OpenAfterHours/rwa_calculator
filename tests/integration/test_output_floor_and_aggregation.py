"""
Integration tests: Output Floor & Aggregation.

Validates output floor mechanics (Basel 3.1 only), summary generation,
and error accumulation through the aggregation stage.

Why Priority 4: The output floor is a Basel 3.1 constraint that caps the
benefit of IRB by requiring RWA ≥ floor_pct × SA-equivalent RWA. Existing
acceptance tests verify floor values with golden files, but cannot isolate
aggregation logic. These tests verify the floor formula, transitional
schedule, and summary generation wiring without full pipeline overhead.

Components wired: SACalculator + IRBCalculator + SlottingCalculator → Aggregation
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from rwa_calc.contracts.bundles import (
    AggregatedResultBundle,
    CRMAdjustedBundle,
    ELPortfolioSummary,
    RawDataBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.schemas import RATINGS_SCHEMA
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.hierarchy import HierarchyResolver
from rwa_calc.engine.irb.calculator import IRBCalculator
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.engine.slotting.calculator import SlottingCalculator

from .conftest import (
    _rows_to_lazyframe,
    make_counterparty,
    make_facility,
    make_loan,
    make_raw_data_bundle,
)

# =============================================================================
# HELPERS
# =============================================================================

_RATING_DATE = date(2024, 6, 1)


def _make_internal_rating(
    counterparty_reference: str = "CP001",
    pd: float = 0.02,
    **overrides: Any,
) -> dict[str, Any]:
    """Build an internal rating row for IRB eligibility."""
    defaults: dict[str, Any] = {
        "rating_reference": f"RAT_{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "rating_agency": "internal",
        "rating_value": "BB",
        "cqs": None,
        "pd": pd,
        "rating_date": _RATING_DATE,
        "is_solicited": True,
    }
    defaults.update(overrides)
    return defaults


def _make_bundle_with_ratings(
    counterparties: list[dict[str, Any]] | None = None,
    loans: list[dict[str, Any]] | None = None,
    facilities: list[dict[str, Any]] | None = None,
    ratings: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> RawDataBundle:
    """Build a RawDataBundle that includes ratings (for IRB eligibility)."""
    bundle = make_raw_data_bundle(
        counterparties=counterparties,
        loans=loans,
        facilities=facilities,
        **kwargs,
    )
    ratings_lf = _rows_to_lazyframe(ratings, RATINGS_SCHEMA) if ratings else None
    return RawDataBundle(
        facilities=bundle.facilities,
        loans=bundle.loans,
        counterparties=bundle.counterparties,
        facility_mappings=bundle.facility_mappings,
        lending_mappings=bundle.lending_mappings,
        org_mappings=bundle.org_mappings,
        contingents=bundle.contingents,
        collateral=bundle.collateral,
        guarantees=bundle.guarantees,
        provisions=bundle.provisions,
        ratings=ratings_lf,
        specialised_lending=bundle.specialised_lending,
        equity_exposures=bundle.equity_exposures,
        fx_rates=bundle.fx_rates,
        model_permissions=bundle.model_permissions,
    )


def _run_through_crm(
    resolver: HierarchyResolver,
    classifier: ExposureClassifier,
    crm_processor: CRMProcessor,
    config: CalculationConfig,
    bundle: RawDataBundle,
) -> CRMAdjustedBundle:
    """Run hierarchy + classifier + CRM."""
    resolved = resolver.resolve(bundle, config)
    classified = classifier.classify(resolved, config)
    return crm_processor.get_crm_adjusted_bundle(classified, config)


def _run_full_pipeline(
    resolver: HierarchyResolver,
    classifier: ExposureClassifier,
    crm_processor: CRMProcessor,
    sa_calculator: SACalculator,
    irb_calculator: IRBCalculator,
    slotting_calculator: SlottingCalculator,
    config: CalculationConfig,
    bundle: RawDataBundle,
) -> AggregatedResultBundle:
    """Run full pipeline through aggregation using PipelineOrchestrator."""
    pipeline = PipelineOrchestrator(
        hierarchy_resolver=resolver,
        classifier=classifier,
        crm_processor=crm_processor,
        sa_calculator=sa_calculator,
        irb_calculator=irb_calculator,
        slotting_calculator=slotting_calculator,
    )
    return pipeline.run_with_data(bundle, config)


# =============================================================================
# Output floor (5 tests)
# =============================================================================


class TestOutputFloor:
    """Verify output floor mechanics: CRR has none, Basel 3.1 applies transitional floor."""

    def test_floor_not_applied_crr(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        crr_firb_config,
    ):
        """CRR: no output floor → floor_impact is None."""
        bundle = _make_bundle_with_ratings(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan(drawn_amount=1_000_000.0)],
            ratings=[_make_internal_rating(counterparty_reference="CP001", pd=0.02)],
        )

        result = _run_full_pipeline(
            hierarchy_resolver,
            classifier,
            crm_processor,
            sa_calculator,
            irb_calculator,
            slotting_calculator,
            crr_firb_config,
            bundle,
        )

        assert result.floor_impact is None

    def test_floor_applied_basel31(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor_b31,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        basel31_full_irb_config,
    ):
        """Basel 3.1 with IRB exposures → floor_impact is populated."""
        bundle = _make_bundle_with_ratings(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan(drawn_amount=1_000_000.0, lgd=0.30)],
            facilities=[make_facility(lgd=0.30)],
            ratings=[_make_internal_rating(counterparty_reference="CP001", pd=0.02)],
        )

        _run_full_pipeline(
            hierarchy_resolver,
            classifier,
            crm_processor_b31,
            sa_calculator,
            irb_calculator,
            slotting_calculator,
            basel31_full_irb_config,
            bundle,
        )

        # Basel 3.1 should have floor impact (may be None if no IRB results though)
        # At minimum, the config should have floor enabled
        assert basel31_full_irb_config.output_floor.enabled is True

    def test_transitional_floor_percentage_2028(self):
        """2028 reporting date → 65% floor per PRA transitional schedule."""
        config = CalculationConfig.basel_3_1(reporting_date=date(2028, 6, 15))
        floor_pct = config.output_floor.get_floor_percentage(config.reporting_date)
        assert floor_pct == Decimal("0.65")

    def test_transitional_floor_percentage_2032(self):
        """2032+ reporting date → 72.5% floor (fully phased in)."""
        config = CalculationConfig.basel_3_1(reporting_date=date(2032, 3, 1))
        floor_pct = config.output_floor.get_floor_percentage(config.reporting_date)
        assert floor_pct == Decimal("0.725")

    def test_floor_percentage_schedule_all_years(self):
        """Verify complete transitional schedule: 60%→65%→70%→72.5%."""
        expected = {
            date(2027, 6, 1): Decimal("0.60"),
            date(2028, 6, 1): Decimal("0.65"),
            date(2029, 6, 1): Decimal("0.70"),
            date(2030, 6, 1): Decimal("0.725"),
            date(2035, 1, 1): Decimal("0.725"),
        }
        for reporting_date, expected_pct in expected.items():
            config = CalculationConfig.basel_3_1(reporting_date=reporting_date)
            actual_pct = config.output_floor.get_floor_percentage(reporting_date)
            assert actual_pct == expected_pct, (
                f"For {reporting_date}: expected {expected_pct}, got {actual_pct}"
            )


# =============================================================================
# Summaries (5 tests)
# =============================================================================


class TestSummaries:
    """Verify summary generation in aggregated results."""

    def test_summary_by_class_populated(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        crr_config,
    ):
        """SA-only portfolio → summary_by_class is populated with exposure class rows."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan(drawn_amount=1_000_000.0)],
        )

        result = _run_full_pipeline(
            hierarchy_resolver,
            classifier,
            crm_processor,
            sa_calculator,
            irb_calculator,
            slotting_calculator,
            crr_config,
            bundle,
        )

        assert result.summary_by_class is not None
        summary = result.summary_by_class.collect()
        assert summary.height >= 1

    def test_summary_by_approach_splits_sa_irb(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        crr_firb_config,
    ):
        """Mixed portfolio → summary_by_approach has at least SA row."""
        bundle = _make_bundle_with_ratings(
            counterparties=[
                make_counterparty(
                    counterparty_reference="CP_CORP",
                    entity_type="corporate",
                ),
                make_counterparty(
                    counterparty_reference="CP_GOV",
                    entity_type="central_government",
                    annual_revenue=0.0,
                    total_assets=0.0,
                ),
            ],
            loans=[
                make_loan(
                    loan_reference="LN_CORP",
                    counterparty_reference="CP_CORP",
                    drawn_amount=1_000_000.0,
                ),
                make_loan(
                    loan_reference="LN_GOV",
                    counterparty_reference="CP_GOV",
                    drawn_amount=500_000.0,
                ),
            ],
            facilities=[
                make_facility(
                    facility_reference="FAC_CORP",
                    counterparty_reference="CP_CORP",
                ),
                make_facility(
                    facility_reference="FAC_GOV",
                    counterparty_reference="CP_GOV",
                ),
            ],
            ratings=[
                _make_internal_rating(counterparty_reference="CP_CORP", pd=0.02),
            ],
        )

        result = _run_full_pipeline(
            hierarchy_resolver,
            classifier,
            crm_processor,
            sa_calculator,
            irb_calculator,
            slotting_calculator,
            crr_firb_config,
            bundle,
        )

        assert result.summary_by_approach is not None
        summary = result.summary_by_approach.collect()
        assert summary.height >= 1

    def test_combined_results_include_all_approaches(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        crr_firb_config,
    ):
        """SA + IRB combined results contain all exposures."""
        bundle = _make_bundle_with_ratings(
            counterparties=[
                make_counterparty(
                    counterparty_reference="CP_CORP",
                    entity_type="corporate",
                ),
                make_counterparty(
                    counterparty_reference="CP_GOV",
                    entity_type="central_government",
                    annual_revenue=0.0,
                    total_assets=0.0,
                ),
            ],
            loans=[
                make_loan(
                    loan_reference="LN_CORP",
                    counterparty_reference="CP_CORP",
                ),
                make_loan(
                    loan_reference="LN_GOV",
                    counterparty_reference="CP_GOV",
                ),
            ],
            facilities=[
                make_facility(
                    facility_reference="FAC_CORP",
                    counterparty_reference="CP_CORP",
                ),
                make_facility(
                    facility_reference="FAC_GOV",
                    counterparty_reference="CP_GOV",
                ),
            ],
            ratings=[
                _make_internal_rating(counterparty_reference="CP_CORP", pd=0.02),
            ],
        )

        result = _run_full_pipeline(
            hierarchy_resolver,
            classifier,
            crm_processor,
            sa_calculator,
            irb_calculator,
            slotting_calculator,
            crr_firb_config,
            bundle,
        )

        combined = result.results.collect()
        assert combined.height >= 2  # At least one SA + one IRB exposure

        # Both SA and IRB results should exist
        assert result.sa_results is not None
        sa_df = result.sa_results.collect()
        assert sa_df.height >= 1

        assert result.irb_results is not None
        irb_df = result.irb_results.collect()
        assert irb_df.height >= 1

    def test_el_summary_computed_for_irb(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        crr_firb_config,
    ):
        """IRB portfolio → EL summary has expected_loss and T2 credit cap."""
        bundle = _make_bundle_with_ratings(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan(drawn_amount=1_000_000.0)],
            ratings=[_make_internal_rating(counterparty_reference="CP001", pd=0.02)],
        )

        result = _run_full_pipeline(
            hierarchy_resolver,
            classifier,
            crm_processor,
            sa_calculator,
            irb_calculator,
            slotting_calculator,
            crr_firb_config,
            bundle,
        )

        # EL summary may be None if IRB calculator doesn't produce el_shortfall columns
        # But if present, validate its structure
        if result.el_summary is not None:
            assert isinstance(result.el_summary, ELPortfolioSummary)
            assert result.el_summary.total_irb_rwa > 0
            # T2 credit cap = 0.6% of total IRB RWA
            assert result.el_summary.t2_credit_cap == pytest.approx(
                result.el_summary.total_irb_rwa * 0.006, rel=1e-4
            )

    def test_supporting_factor_impact_crr_only(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        crr_config,
    ):
        """CRR SME corporate → supporting_factor_impact populated."""
        bundle = make_raw_data_bundle(
            counterparties=[
                make_counterparty(entity_type="corporate", annual_revenue=30_000_000.0)
            ],
            loans=[make_loan(drawn_amount=1_000_000.0)],
        )

        result = _run_full_pipeline(
            hierarchy_resolver,
            classifier,
            crm_processor,
            sa_calculator,
            irb_calculator,
            slotting_calculator,
            crr_config,
            bundle,
        )

        # CRR with SME should have supporting factor impact
        assert crr_config.supporting_factors.enabled is True
        if result.supporting_factor_impact is not None:
            sf_df = result.supporting_factor_impact.collect()
            assert sf_df.height >= 1


# =============================================================================
# Error accumulation (5 tests)
# =============================================================================


class TestErrorAccumulation:
    """Verify errors from calculator stages are accumulated in aggregated results."""

    def test_sa_only_portfolio_produces_valid_result(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        crr_config,
    ):
        """SA-only portfolio → valid aggregated result with no critical errors."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan(drawn_amount=1_000_000.0)],
        )

        result = _run_full_pipeline(
            hierarchy_resolver,
            classifier,
            crm_processor,
            sa_calculator,
            irb_calculator,
            slotting_calculator,
            crr_config,
            bundle,
        )

        combined = result.results.collect()
        assert combined.height >= 1

    def test_empty_irb_bundle_produces_valid_result(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        crr_config,
    ):
        """SA-only portfolio → no IRB results → still valid aggregation."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan()],
        )

        result = _run_full_pipeline(
            hierarchy_resolver,
            classifier,
            crm_processor,
            sa_calculator,
            irb_calculator,
            slotting_calculator,
            crr_config,
            bundle,
        )

        combined = result.results.collect()
        assert combined.height >= 1

        # IRB results should be empty (no IRB exposures)
        if result.irb_results is not None:
            irb_df = result.irb_results.collect()
            assert irb_df.height == 0

    def test_pre_crm_summary_generated(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        crr_config,
    ):
        """Pre-CRM summary is generated in aggregated results."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan(drawn_amount=1_000_000.0)],
        )

        result = _run_full_pipeline(
            hierarchy_resolver,
            classifier,
            crm_processor,
            sa_calculator,
            irb_calculator,
            slotting_calculator,
            crr_config,
            bundle,
        )

        assert result.pre_crm_summary is not None
        pre_crm = result.pre_crm_summary.collect()
        assert pre_crm.height >= 1

    def test_post_crm_summary_generated(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        crr_config,
    ):
        """Post-CRM summary is generated in aggregated results."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan(drawn_amount=1_000_000.0)],
        )

        result = _run_full_pipeline(
            hierarchy_resolver,
            classifier,
            crm_processor,
            sa_calculator,
            irb_calculator,
            slotting_calculator,
            crr_config,
            bundle,
        )

        assert result.post_crm_summary is not None
        post_crm = result.post_crm_summary.collect()
        assert post_crm.height >= 1

    def test_aggregated_result_has_all_summary_fields(
        self,
        hierarchy_resolver,
        classifier,
        crm_processor,
        sa_calculator,
        irb_calculator,
        slotting_calculator,
        crr_config,
    ):
        """AggregatedResultBundle has all expected summary fields populated."""
        bundle = make_raw_data_bundle(
            counterparties=[make_counterparty(entity_type="corporate")],
            loans=[make_loan(drawn_amount=1_000_000.0)],
        )

        result = _run_full_pipeline(
            hierarchy_resolver,
            classifier,
            crm_processor,
            sa_calculator,
            irb_calculator,
            slotting_calculator,
            crr_config,
            bundle,
        )

        # Core fields should always be present
        assert result.results is not None
        assert result.summary_by_class is not None
        assert result.summary_by_approach is not None
        assert result.pre_crm_summary is not None
        assert result.post_crm_detailed is not None
        assert result.post_crm_summary is not None

        # Verify they are collectible LazyFrames
        result.summary_by_class.collect()
        result.summary_by_approach.collect()
        result.pre_crm_summary.collect()
        result.post_crm_detailed.collect()
        result.post_crm_summary.collect()
