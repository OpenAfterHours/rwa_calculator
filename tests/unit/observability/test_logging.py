"""Unit tests for `rwa_calc.observability` — logging setup, context, formatters."""

from __future__ import annotations

import asyncio
import io
import json
import logging
from collections.abc import Iterator
from datetime import date

import pytest

from rwa_calc.observability import (
    JsonFormatter,
    RunIdFilter,
    TextFormatter,
    bind_run_id,
    clear_run_id,
    configure_logging,
    current_run_id,
    new_run_id,
    stage_timer,
)
from rwa_calc.observability.logging_setup import _NAMESPACE


@pytest.fixture(autouse=True)
def _reset_namespace_logger() -> Iterator[None]:
    """Strip handlers + reset the idempotency guard between tests."""
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


def _make_record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="rwa_calc.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=None,
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestTextFormatter:
    def test_includes_run_id_placeholder(self) -> None:
        formatter = TextFormatter()
        record = _make_record("hello")
        record.run_id = "abc123"

        output = formatter.format(record)

        assert "[abc123]" in output
        assert "rwa_calc.test: hello" in output


class TestJsonFormatter:
    def test_serialises_core_fields(self) -> None:
        formatter = JsonFormatter()
        record = _make_record("msg")
        record.run_id = "run-1"

        payload = json.loads(formatter.format(record))

        assert payload["message"] == "msg"
        assert payload["level"] == "INFO"
        assert payload["logger"] == "rwa_calc.test"
        assert payload["run_id"] == "run-1"
        assert "timestamp" in payload

    def test_merges_whitelisted_extras(self) -> None:
        formatter = JsonFormatter()
        record = _make_record("msg", stage="classifier", elapsed_ms=12.3)
        record.run_id = "run-1"

        payload = json.loads(formatter.format(record))

        assert payload["stage"] == "classifier"
        assert payload["elapsed_ms"] == 12.3

    def test_ignores_non_whitelisted_extras(self) -> None:
        formatter = JsonFormatter()
        record = _make_record("msg", secret_field="should_not_appear")
        record.run_id = "run-1"

        payload = json.loads(formatter.format(record))

        assert "secret_field" not in payload

    def test_handles_exc_info(self) -> None:
        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="rwa_calc.test",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="failed",
                args=None,
                exc_info=sys.exc_info(),
            )
            record.run_id = "-"
            payload = json.loads(formatter.format(record))

        assert payload["exc_type"] == "ValueError"
        assert payload["exc_message"] == "boom"
        assert "traceback" in payload


class TestRunIdContextVar:
    def test_new_run_id_sets_and_clears(self) -> None:
        assert current_run_id() is None
        run_id, token = new_run_id()
        assert current_run_id() == run_id
        assert len(run_id) == 12
        clear_run_id(token)
        assert current_run_id() is None

    def test_bind_run_id_roundtrip(self) -> None:
        token = bind_run_id("custom-id")
        assert current_run_id() == "custom-id"
        clear_run_id(token)
        assert current_run_id() is None

    def test_isolation_across_asyncio_tasks(self) -> None:
        async def task(name: str, observed: dict[str, str]) -> None:
            run_id, token = new_run_id()
            observed[name] = run_id
            await asyncio.sleep(0.01)
            observed[f"{name}_after_sleep"] = current_run_id() or ""
            clear_run_id(token)

        async def main() -> dict[str, str]:
            observed: dict[str, str] = {}
            await asyncio.gather(task("a", observed), task("b", observed))
            return observed

        observed = asyncio.run(main())

        assert observed["a"] != observed["b"]
        assert observed["a_after_sleep"] == observed["a"]
        assert observed["b_after_sleep"] == observed["b"]


class TestRunIdFilter:
    def test_injects_dash_when_unset(self) -> None:
        filt = RunIdFilter()
        record = _make_record("msg")

        filt.filter(record)

        assert record.run_id == "-"

    def test_injects_current_run_id(self) -> None:
        filt = RunIdFilter()
        _, token = new_run_id()
        record = _make_record("msg")

        try:
            filt.filter(record)
            assert record.run_id == current_run_id()
        finally:
            clear_run_id(token)


class TestConfigureLogging:
    def test_attaches_single_handler(self) -> None:
        configure_logging("INFO", "text", stream=io.StringIO())
        namespace_logger = logging.getLogger(_NAMESPACE)

        assert len(namespace_logger.handlers) == 1

    def test_idempotent_with_identical_args(self) -> None:
        stream = io.StringIO()
        configure_logging("INFO", "text", stream=stream)
        configure_logging("INFO", "text", stream=stream)

        namespace_logger = logging.getLogger(_NAMESPACE)
        assert len(namespace_logger.handlers) == 1

    def test_reconfigure_swaps_formatter_without_stacking(self) -> None:
        configure_logging("INFO", "text", stream=io.StringIO())
        configure_logging("DEBUG", "json", stream=io.StringIO())

        namespace_logger = logging.getLogger(_NAMESPACE)
        assert len(namespace_logger.handlers) == 1
        assert isinstance(namespace_logger.handlers[0].formatter, JsonFormatter)
        assert namespace_logger.level == logging.DEBUG

    def test_rejects_invalid_level(self) -> None:
        with pytest.raises(ValueError, match="invalid log level"):
            configure_logging("NOPE", "text")

    def test_silences_noisy_libs(self) -> None:
        configure_logging("DEBUG", "text", stream=io.StringIO())

        assert logging.getLogger("polars").level == logging.WARNING
        assert logging.getLogger("uvicorn.access").level == logging.WARNING

    def test_does_not_configure_root_logger(self) -> None:
        root_before = list(logging.getLogger().handlers)
        configure_logging("INFO", "text", stream=io.StringIO())
        root_after = list(logging.getLogger().handlers)

        assert root_before == root_after

    def test_namespace_logger_does_not_propagate(self) -> None:
        configure_logging("INFO", "text", stream=io.StringIO())
        assert logging.getLogger(_NAMESPACE).propagate is False

    def test_emits_text_record_through_handler(self) -> None:
        stream = io.StringIO()
        configure_logging("INFO", "text", stream=stream)
        _, token = new_run_id()
        try:
            logging.getLogger("rwa_calc.smoke").info("hello world")
        finally:
            clear_run_id(token)

        output = stream.getvalue()
        assert "hello world" in output
        assert "rwa_calc.smoke" in output


class TestStageTimer:
    def test_emits_entry_and_exit_records(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("rwa_calc.test.stage")
        caplog.set_level(logging.DEBUG, logger=logger.name)

        with stage_timer(logger, "loader", framework="CRR"):
            pass

        entry_records = [
            r
            for r in caplog.records
            if r.levelname == "DEBUG" and getattr(r, "stage", None) == "loader"
        ]
        exit_records = [
            r
            for r in caplog.records
            if r.levelname == "INFO" and getattr(r, "stage", None) == "loader"
        ]
        assert len(entry_records) == 1, "expected a single DEBUG entry record"
        assert entry_records[0].message == "loader started"
        assert len(exit_records) == 1, "expected a single INFO exit record"
        exit_record = exit_records[0]
        assert exit_record.message.startswith("loader completed in ")
        assert exit_record.message.endswith(" ms")
        assert getattr(exit_record, "elapsed_ms", None) is not None
        assert getattr(exit_record, "framework", None) == "CRR"

    def test_emits_warning_on_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("rwa_calc.test.stage")
        caplog.set_level(logging.DEBUG, logger=logger.name)

        with pytest.raises(RuntimeError), stage_timer(logger, "classifier"):
            raise RuntimeError("boom")

        failures = [
            r
            for r in caplog.records
            if r.levelname == "WARNING" and getattr(r, "stage", None) == "classifier"
        ]
        assert len(failures) == 1
        failure = failures[0]
        assert failure.message.startswith("classifier failed after ")
        assert failure.message.endswith(" ms")
        assert getattr(failure, "elapsed_ms", None) is not None


class TestCalculationConfigLogFields:
    def test_crr_defaults(self) -> None:
        from rwa_calc.contracts.config import CalculationConfig

        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))

        assert config.log_level == "INFO"
        assert config.log_format == "text"

    def test_basel_3_1_defaults(self) -> None:
        from rwa_calc.contracts.config import CalculationConfig

        config = CalculationConfig.basel_3_1(reporting_date=date(2024, 12, 31))

        assert config.log_level == "INFO"
        assert config.log_format == "text"

    def test_overrides_propagate(self) -> None:
        from rwa_calc.contracts.config import CalculationConfig

        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            log_level="DEBUG",
            log_format="json",
        )

        assert config.log_level == "DEBUG"
        assert config.log_format == "json"
