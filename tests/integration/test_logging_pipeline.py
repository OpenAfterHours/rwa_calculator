"""
Integration tests for pipeline logging instrumentation.

Exercises the full PipelineOrchestrator flow with a minimal fixture and
asserts that:
- each stage emits matching entry/exit records carrying a ``stage`` extra
- exit records include an ``elapsed_ms`` extra
- every record emitted during a run shares a single ``run_id``
- back-to-back runs produce distinct run_ids without stacking handlers
- no log record duplicates a ``CalculationError.message`` verbatim
"""

from __future__ import annotations

import logging
from datetime import date

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.observability import RunIdFilter, configure_logging
from rwa_calc.observability.logging_setup import _NAMESPACE

from .conftest import make_counterparty, make_loan, make_raw_data_bundle

_NAMESPACE_LOGGER_NAMES: tuple[str, ...] = (
    "rwa_calc.engine.pipeline",
    "rwa_calc.engine.loader",
    "rwa_calc.engine.hierarchy",
    "rwa_calc.engine.classifier",
    "rwa_calc.engine.crm.processor",
    "rwa_calc.engine.re_splitter",
    "rwa_calc.engine.sa.calculator",
    "rwa_calc.engine.irb.calculator",
    "rwa_calc.engine.slotting.calculator",
    "rwa_calc.engine.equity.calculator",
    "rwa_calc.engine.aggregator.aggregator",
)


@pytest.fixture(autouse=True)
def _reset_logging_state() -> None:
    """Strip handlers/state from the rwa_calc namespace logger between runs."""
    from rwa_calc.observability import logging_setup

    def _reset() -> None:
        namespace_logger = logging.getLogger(_NAMESPACE)
        for handler in list(namespace_logger.handlers):
            namespace_logger.removeHandler(handler)
        namespace_logger.filters.clear()
        namespace_logger.propagate = True
        namespace_logger.setLevel(logging.NOTSET)
        if hasattr(namespace_logger, "_rwa_calc_handler"):
            delattr(namespace_logger, "_rwa_calc_handler")
        logging_setup._configured = None

    _reset()
    yield
    _reset()


@pytest.fixture
def minimal_bundle():
    """Minimal valid RawDataBundle — one counterparty, one loan."""
    return make_raw_data_bundle(
        counterparties=[make_counterparty()],
        loans=[make_loan()],
    )


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


def _run_pipeline_capturing_records(
    data, config: CalculationConfig, caplog: pytest.LogCaptureFixture
):
    """Run the pipeline with caplog capturing rwa_calc namespace records."""
    caplog.set_level(logging.DEBUG, logger="rwa_calc")
    # caplog's handler needs RunIdFilter so records carry a run_id attribute
    caplog.handler.addFilter(RunIdFilter())
    pipeline = PipelineOrchestrator()
    result = pipeline.run_with_data(data, config)
    return result, caplog.records


class TestPipelineLoggingInstrumentation:
    def test_every_stage_emits_entry_and_exit_records(
        self,
        minimal_bundle,
        crr_config,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _, records = _run_pipeline_capturing_records(minimal_bundle, crr_config, caplog)

        stages_with_entries = {
            r.stage
            for r in records
            if r.levelname == "DEBUG" and hasattr(r, "stage") and r.message == f"{r.stage} started"
        }
        stages_with_exits = {
            r.stage
            for r in records
            if r.levelname == "INFO"
            and hasattr(r, "stage")
            and r.message.startswith(f"{r.stage} completed in ")
        }

        expected_stages = {
            "hierarchy_resolver",
            "classifier",
            "crm_processor",
            "re_splitter",
            "calculators",
            "aggregator",
        }
        missing_entries = expected_stages - stages_with_entries
        missing_exits = expected_stages - stages_with_exits
        assert not missing_entries, f"stages missing entry records: {missing_entries}"
        assert not missing_exits, f"stages missing exit records: {missing_exits}"

    def test_exit_records_carry_elapsed_ms(
        self,
        minimal_bundle,
        crr_config,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _, records = _run_pipeline_capturing_records(minimal_bundle, crr_config, caplog)

        exit_records = [
            r
            for r in records
            if r.levelname == "INFO"
            and hasattr(r, "stage")
            and r.message.startswith(f"{r.stage} completed in ")
        ]
        assert exit_records, "no stage exit records captured"
        for record in exit_records:
            elapsed = getattr(record, "elapsed_ms", None)
            assert elapsed is not None, f"missing elapsed_ms on {record.stage!r}"
            assert isinstance(elapsed, float)
            assert elapsed >= 0

    def test_single_run_id_shared_across_all_records(
        self,
        minimal_bundle,
        crr_config,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _, records = _run_pipeline_capturing_records(minimal_bundle, crr_config, caplog)

        run_ids = {getattr(r, "run_id", None) for r in records}
        run_ids.discard(None)
        run_ids.discard("-")
        assert len(run_ids) == 1, f"expected single run_id; got {run_ids}"

    def test_back_to_back_runs_have_distinct_run_ids(
        self,
        minimal_bundle,
        crr_config,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.DEBUG, logger="rwa_calc")
        caplog.handler.addFilter(RunIdFilter())
        pipeline = PipelineOrchestrator()

        pipeline.run_with_data(minimal_bundle, crr_config)
        first_run_ids = {getattr(r, "run_id", None) for r in caplog.records} - {None, "-"}
        caplog.clear()

        pipeline.run_with_data(minimal_bundle, crr_config)
        second_run_ids = {getattr(r, "run_id", None) for r in caplog.records} - {None, "-"}

        assert first_run_ids and second_run_ids
        assert first_run_ids != second_run_ids

    def test_configure_logging_does_not_stack_handlers_across_runs(
        self,
        minimal_bundle,
        crr_config,
    ) -> None:
        namespace_logger = logging.getLogger(_NAMESPACE)
        configure_logging("INFO", "text")
        configure_logging("INFO", "text")
        configure_logging("DEBUG", "json")

        pipeline = PipelineOrchestrator()
        pipeline.run_with_data(minimal_bundle, crr_config)
        pipeline.run_with_data(minimal_bundle, crr_config)

        assert len(namespace_logger.handlers) == 1

    def test_log_messages_do_not_duplicate_calculation_errors(
        self,
        minimal_bundle,
        crr_config,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        result, records = _run_pipeline_capturing_records(minimal_bundle, crr_config, caplog)

        log_messages = {r.message for r in records}
        for error in result.errors:
            assert error.message not in log_messages, (
                f"log record duplicates CalculationError.message: {error.message!r}"
            )
