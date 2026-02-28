"""Tests for input value validation in the pipeline.

Verifies that the pipeline detects invalid column values, reports them
as errors, and continues execution (non-blocking validation).
"""

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.engine.pipeline import PipelineOrchestrator


def _make_minimal_bundle(**overrides) -> RawDataBundle:
    """Create a minimal RawDataBundle suitable for pipeline validation testing."""
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
            "is_regulated": [False],
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

    defaults = {
        "facilities": facilities,
        "loans": loans,
        "counterparties": counterparties,
        "facility_mappings": facility_mappings,
        "lending_mappings": lending_mappings,
    }
    defaults.update(overrides)
    return RawDataBundle(**defaults)


def _make_config():
    """Create a minimal CalculationConfig."""
    from datetime import date

    from rwa_calc.contracts.config import CalculationConfig

    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


class TestPipelineInputValidation:
    """Tests that pipeline detects and reports invalid input values."""

    def test_valid_data_no_validation_errors(self):
        """Valid input data should produce no validation errors."""
        bundle = _make_minimal_bundle()
        pipeline = PipelineOrchestrator()
        config = _make_config()

        result = pipeline.run_with_data(bundle, config)

        validation_errors = [
            e
            for e in result.errors
            if hasattr(e, "message") and "input_validation" in str(e.message)
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
                "is_regulated": [False],
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
                "is_regulated": [False],
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
