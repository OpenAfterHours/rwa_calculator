"""
Integration tests for eur_gbp_rate auto-sync in PipelineOrchestrator.

Exercises the hook in ``PipelineOrchestrator.run_with_data`` that replaces
``config.eur_gbp_rate`` (and rebuilds ``config.thresholds``) from the
``(EUR, GBP)`` row in the loaded ``fx_rates`` table.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.observability import RunIdFilter
from rwa_calc.observability.logging_setup import _NAMESPACE

from .conftest import make_counterparty, make_loan, make_raw_data_bundle


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


def _bundle_with_fx_rate(rate: float):
    """Minimal bundle with a single (EUR, GBP, rate) row in fx_rates."""
    bundle = make_raw_data_bundle(
        counterparties=[make_counterparty()],
        loans=[make_loan()],
    )
    fx_rates = pl.LazyFrame(
        {
            "currency_from": ["EUR"],
            "currency_to": ["GBP"],
            "rate": [rate],
        }
    )
    return dataclasses.replace(bundle, fx_rates=fx_rates)


def _run(
    data, config: CalculationConfig, caplog: pytest.LogCaptureFixture
) -> list[logging.LogRecord]:
    caplog.set_level(logging.DEBUG, logger="rwa_calc")
    caplog.handler.addFilter(RunIdFilter())
    pipeline = PipelineOrchestrator()
    pipeline.run_with_data(data, config)
    return list(caplog.records)


def _autosync_warnings(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [
        r for r in records if r.levelname == "WARNING" and "eur_gbp_rate auto-sync" in r.message
    ]


class TestEurGbpRateAutoSync:
    def test_warns_and_replaces_rate_when_fx_table_diverges(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        bundle = _bundle_with_fx_rate(0.90)
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            eur_gbp_rate=Decimal("0.8732"),
        )

        records = _run(bundle, config, caplog)

        warnings = _autosync_warnings(records)
        assert len(warnings) == 1, f"expected one auto-sync warning; got {len(warnings)}"
        msg = warnings[0].message
        assert "0.8732" in msg
        assert "0.9" in msg  # Polars surfaces 0.90 as 0.9

    def test_no_warning_when_rates_match(self, caplog: pytest.LogCaptureFixture) -> None:
        bundle = _bundle_with_fx_rate(0.8732)
        config = CalculationConfig.crr(
            reporting_date=date(2024, 12, 31),
            eur_gbp_rate=Decimal("0.8732"),
        )

        records = _run(bundle, config, caplog)

        assert _autosync_warnings(records) == []

    def test_opt_out_suppresses_autosync(self, caplog: pytest.LogCaptureFixture) -> None:
        bundle = _bundle_with_fx_rate(0.90)
        config = dataclasses.replace(
            CalculationConfig.crr(
                reporting_date=date(2024, 12, 31),
                eur_gbp_rate=Decimal("0.8732"),
            ),
            sync_eur_gbp_rate_from_fx_table=False,
        )

        records = _run(bundle, config, caplog)

        assert _autosync_warnings(records) == []

    def test_basel_3_1_skips_autosync(self, caplog: pytest.LogCaptureFixture) -> None:
        """B3.1 uses GBP-native thresholds; eur_gbp_rate auto-sync is a no-op."""
        bundle = _bundle_with_fx_rate(0.90)
        config = CalculationConfig.basel_3_1(reporting_date=date(2028, 1, 15))

        records = _run(bundle, config, caplog)

        assert _autosync_warnings(records) == []
