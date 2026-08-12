"""Tests for input value validation in the pipeline.

Verifies that:
- The loader validates bundle values and attaches errors to RawDataBundle
- The pipeline propagates RawDataBundle.errors to the final result
- The pipeline continues execution despite validation errors (non-blocking)
- Both pipeline entries gate the input domain, without double-reporting, and
  the output-bounds gate runs at the exit
"""

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.engine.loader import _run_bundle_validation
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle


def _bundle_defaults() -> dict[str, pl.LazyFrame]:
    """The minimal, fully in-domain set of raw tables these tests build on."""
    from datetime import date

    facilities = pl.LazyFrame(
        {
            "facility_reference": ["F1"],
            "product_type": ["term_loan"],
            "book_code": ["BOOK1"],
            "counterparty_reference": ["C1"],
            "value_date": [date(2024, 1, 1)],
            "maturity_date": [date(2029, 1, 1)],
            "currency": ["GBP"],
            "limit": [1_000_000.0],
            "committed": [True],
            "lgd": [None],
            "beel": [None],
            "is_revolving": [False],
            "seniority": ["senior"],
            "risk_type": ["FR"],
            "ccf_modelled": [None],
            "is_short_term_trade_lc": [False],
        }
    )

    loans = pl.LazyFrame(
        {
            "loan_reference": ["L1"],
            "product_type": ["term_loan"],
            "book_code": ["BOOK1"],
            "counterparty_reference": ["C1"],
            "value_date": [date(2024, 1, 1)],
            "maturity_date": [date(2029, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [500_000.0],
            "interest": [0.0],
            "lgd": [None],
            "beel": [None],
            "seniority": ["senior"],
        }
    )

    counterparties = pl.LazyFrame(
        {
            "counterparty_reference": ["C1"],
            "counterparty_name": ["Test Corp"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [10_000_000.0],
            "total_assets": [5_000_000.0],
            "default_status": [False],
            "sector_code": ["6200"],
            "apply_fi_scalar": [True],
            "is_managed_as_retail": [False],
        }
    )

    facility_mappings = pl.LazyFrame(
        {
            "parent_facility_reference": ["F1"],
            "child_reference": ["L1"],
            "child_type": ["loan"],
        }
    )

    lending_mappings = pl.LazyFrame(
        {
            "parent_counterparty_reference": pl.Series([], dtype=pl.String),
            "child_counterparty_reference": pl.Series([], dtype=pl.String),
        }
    )

    return {
        "facilities": facilities,
        "loans": loans,
        "counterparties": counterparties,
        "facility_mappings": facility_mappings,
        "lending_mappings": lending_mappings,
    }


def _make_minimal_bundle(**overrides) -> RawDataBundle:
    """Create a minimal RawDataBundle suitable for pipeline validation testing.

    Runs loader-level validation and attaches any errors to the bundle,
    matching the behaviour of a real loader.
    """
    defaults = _bundle_defaults()
    defaults.update(overrides)
    bundle = make_raw_bundle(**defaults)
    # Run loader-level validation to match real loader behaviour
    errors = _run_bundle_validation(bundle)
    if errors:
        return make_raw_bundle(**defaults, errors=errors)
    return bundle


def _make_config():
    """Create a minimal CalculationConfig."""
    from datetime import date

    from rwa_calc.contracts.config import CalculationConfig

    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


class TestPipelineInputValidation:
    """Tests that loader validation errors propagate through the pipeline."""

    def test_valid_data_no_validation_errors(self):
        """Valid input data should produce no validation errors."""
        bundle = _make_minimal_bundle()
        pipeline = PipelineOrchestrator()
        config = _make_config()

        result = pipeline.run_with_data(bundle, config)

        validation_errors = [
            e for e in result.errors if hasattr(e, "field_name") and e.field_name is not None
        ]
        assert validation_errors == []

    def test_invalid_entity_type_reported(self):
        """Invalid entity_type should appear in pipeline errors."""

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["C1"],
                "counterparty_name": ["Test Corp"],
                "entity_type": ["ALIEN_SPECIES"],
                "country_code": ["GB"],
                "annual_revenue": [10_000_000.0],
                "total_assets": [5_000_000.0],
                "default_status": [False],
                "sector_code": ["6200"],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [False],
            }
        )

        bundle = _make_minimal_bundle(counterparties=counterparties)
        pipeline = PipelineOrchestrator()
        config = _make_config()

        result = pipeline.run_with_data(bundle, config)

        validation_msgs = [
            str(e.message)
            for e in result.errors
            if hasattr(e, "message") and "ALIEN_SPECIES" in str(e.message)
        ]
        assert len(validation_msgs) >= 1

    def test_pipeline_continues_despite_validation_errors(self):
        """Pipeline should still produce results even with invalid values."""

        counterparties = pl.LazyFrame(
            {
                "counterparty_reference": ["C1"],
                "counterparty_name": ["Test Corp"],
                "entity_type": ["INVALID_TYPE"],
                "country_code": ["GB"],
                "annual_revenue": [10_000_000.0],
                "total_assets": [5_000_000.0],
                "default_status": [False],
                "sector_code": ["6200"],
                "apply_fi_scalar": [True],
                "is_managed_as_retail": [False],
            }
        )

        bundle = _make_minimal_bundle(counterparties=counterparties)
        pipeline = PipelineOrchestrator()
        config = _make_config()

        result = pipeline.run_with_data(bundle, config)

        # Pipeline should still return a result (not crash)
        assert result is not None
        assert result.results is not None

    def test_invalid_seniority_reported(self):
        """Invalid seniority value should appear in pipeline errors."""
        from datetime import date

        facilities = pl.LazyFrame(
            {
                "facility_reference": ["F1"],
                "product_type": ["term_loan"],
                "book_code": ["BOOK1"],
                "counterparty_reference": ["C1"],
                "value_date": [date(2024, 1, 1)],
                "maturity_date": [date(2029, 1, 1)],
                "currency": ["GBP"],
                "limit": [1_000_000.0],
                "committed": [True],
                "lgd": [None],
                "beel": [None],
                "is_revolving": [False],
                "seniority": ["MEGA_SENIOR"],
                "risk_type": ["FR"],
                "ccf_modelled": [None],
                "is_short_term_trade_lc": [False],
            }
        )

        bundle = _make_minimal_bundle(facilities=facilities)
        pipeline = PipelineOrchestrator()
        config = _make_config()

        result = pipeline.run_with_data(bundle, config)

        validation_msgs = [
            str(e.message)
            for e in result.errors
            if hasattr(e, "message") and "MEGA_SENIOR" in str(e.message)
        ]
        assert len(validation_msgs) >= 1


class TestPipelineEntryGates:
    """The Phase 0 gates wired at both pipeline entries and the pipeline exit.

    The file loader already ran ``validate_bundle_values``; the in-memory
    ``run_with_data`` entry did not. These pin that both paths report exactly
    once, and that the output-bounds check runs on every completed run.

    References:
    - docs/plans/test-space-correctness-proposal.md (Phase 0)
    """

    @staticmethod
    def _bad_pd_ratings() -> pl.LazyFrame:
        """A ratings table whose PD is percent-scaled (1.5 meaning 1.5%)."""
        return pl.LazyFrame(
            {
                "rating_reference": ["R-BAD"],
                "counterparty_reference": ["C1"],
                "rating_type": ["internal"],
                "pd": [1.5],
            }
        )

    def test_in_memory_entry_reports_out_of_domain_pd(self):
        """run_with_data must gate the input domain — the loader never ran for it."""
        bundle = make_raw_bundle(
            **{
                **_bundle_defaults(),
                "ratings": self._bad_pd_ratings(),
            }
        )
        assert bundle.errors == []  # no loader validation on this path

        result = PipelineOrchestrator().run_with_data(bundle, _make_config())

        pd_errors = [e for e in result.errors if e.code == "IRB001"]
        assert len(pd_errors) == 1
        assert pd_errors[0].exposure_reference == "R-BAD"

    def test_loader_path_does_not_double_report(self):
        """A bundle that already carries the loader's errors must not report twice."""
        defaults = {**_bundle_defaults(), "ratings": self._bad_pd_ratings()}
        unvalidated = make_raw_bundle(**defaults)
        loader_errors = _run_bundle_validation(unvalidated)
        assert [e for e in loader_errors if e.code == "IRB001"], (
            "the loader gate must produce the error this test de-duplicates"
        )
        bundle = make_raw_bundle(**defaults, errors=loader_errors)

        result = PipelineOrchestrator().run_with_data(bundle, _make_config())

        assert len([e for e in result.errors if e.code == "IRB001"]) == 1

    def test_output_bounds_gate_runs_at_the_exit(self, monkeypatch):
        """A risk weight above the 1250% cap is reported, not published silently."""
        from dataclasses import replace

        from rwa_calc.contracts.edges import AGGREGATOR_EXIT_EDGE, reseal_with
        from rwa_calc.engine.aggregator import OutputAggregator

        class _CapBreachingAggregator:
            """Real aggregator, then one column pushed past the Art. 92(3) cap."""

            def __init__(self) -> None:
                self._inner = OutputAggregator()

            def aggregate(self, **kwargs):
                bundle = self._inner.aggregate(**kwargs)
                breached = reseal_with(
                    bundle.results, {"risk_weight": pl.lit(20.0)}, AGGREGATOR_EXIT_EDGE
                )
                return replace(bundle, results=breached)

        pipeline = PipelineOrchestrator(output_aggregator=_CapBreachingAggregator())

        result = pipeline.run_with_data(make_raw_bundle(**_bundle_defaults()), _make_config())

        cap_errors = [e for e in result.errors if e.code == "OUT001"]
        assert cap_errors, "OUT001 must be raised for risk_weight above 12.5"
        assert cap_errors[0].exposure_reference is not None

    def test_clean_run_adds_no_gate_errors(self):
        """Neither gate fires on an in-domain, in-bounds portfolio."""
        result = PipelineOrchestrator().run_with_data(
            make_raw_bundle(**_bundle_defaults()), _make_config()
        )

        gate_codes = {"IRB001", "IRB002", "IRB008", "DQ012", "OUT001", "OUT002", "OUT003", "OUT004"}
        assert [e for e in result.errors if e.code in gate_codes] == []
