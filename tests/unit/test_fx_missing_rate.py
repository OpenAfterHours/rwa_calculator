"""RC-11: an amount with no FX rate into the reporting currency draws DQ020.

``engine/fx`` converts an amount only where ``fx_rates`` holds a
``currency -> base_currency`` rate. Every other amount used to pass through in
its SOURCE currency's units, keep its source currency code, and be read as GBP
by every threshold, total and template downstream — with no error code anywhere
(review finding RC-11; the verifier re-measured a KWD 1,000,000 loan at EAD
1,000,000 with ``errors == []`` in both regimes). The direction depends on the
currency: KWD is worth more than GBP (understated), ZAR less (overstated ~20x),
so the defect is the silence. The fix keeps the pass-through — the engine has
no rate and must not invent one — and the pipeline-entry input gate reports one
DQ020 ERROR per currency (``contracts/validation.py::_validate_missing_fx_rates``,
batched into the gate's single ``collect_all``).

Hand calculation (unrated non-SME corporate, SA RW 100% both regimes): loan
KWD 1,000,000 drawn, no interest. No KWD rate: EAD = RWA = 1,000,000 (the
unconverted figure, now reported). KWD -> GBP 2.5 supplied: EAD = RWA =
2,500,000 and no DQ020.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from functools import cache
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_FX_RATE_MISSING
from rwa_calc.contracts.validation import validate_bundle_values
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import FX_RATES_SCHEMA
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import seal_raw_table
from tests.integration.conftest import make_facility, make_loan, make_raw_data_bundle

_REGIMES = ("CRR", "B31")


def _config(regime: str) -> CalculationConfig:
    if regime == "CRR":
        return CalculationConfig.crr(reporting_date=date(2026, 6, 30))
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _rates(*pairs: tuple[str, float | None]) -> pl.LazyFrame:
    return seal_raw_table(
        pl.LazyFrame(
            {
                "currency_from": [c for c, _ in pairs],
                "currency_to": ["GBP"] * len(pairs),
                "rate": [r for _, r in pairs],
            },
            schema=dtypes_of(FX_RATES_SCHEMA),
        ),
        "fx_rates",
    )


def _bundle(
    *loans: tuple[str, str | None, float],
    fx: pl.LazyFrame | None,
    collateral: pl.LazyFrame | None = None,
) -> RawDataBundle:
    bundle = make_raw_data_bundle(
        facilities=[make_facility(facility_reference="F1", limit=0.0)],
        loans=[
            make_loan(loan_reference=ref, currency=ccy, drawn_amount=amount, interest=0.0)
            for ref, ccy, amount in loans
        ],
        facility_mappings=[],
    )
    return dataclasses.replace(bundle, fx_rates=fx, collateral=collateral)


def _dq020(bundle: RawDataBundle, config: CalculationConfig) -> list[Any]:
    return [
        e for e in validate_bundle_values(bundle, config=config) if e.code == ERROR_FX_RATE_MISSING
    ]


class TestInputGate:
    """The detector mirrors the converter's own currency and rate tests."""

    def test_one_error_per_currency_with_rows_and_amount(self) -> None:
        bundle = _bundle(
            ("L1", "KWD", 1_000_000.0),
            ("L2", "KWD", 500_000.0),
            ("L3", "EUR", 1.0),
            fx=_rates(("EUR", 0.85)),
        )

        found = _dq020(bundle, _config("B31"))

        assert [e.actual_value for e in found] == ["KWD"]
        assert found[0].severity == ErrorSeverity.ERROR
        assert "2 row(s)" in found[0].message
        assert "loans: 2 row(s), 1,500,000.00" in found[0].message

    def test_tables_are_listed_under_one_currency(self) -> None:
        collateral = seal_raw_table(
            pl.LazyFrame(
                {
                    "collateral_reference": ["C1"],
                    "collateral_type": ["cash"],
                    "currency": ["KWD"],
                    "market_value": [250_000.0],
                    "beneficiary_type": ["loan"],
                    "beneficiary_reference": ["L1"],
                }
            ),
            "collateral",
        )
        bundle = _bundle(
            ("L1", "KWD", 1_000_000.0), fx=_rates(("EUR", 0.85)), collateral=collateral
        )

        found = _dq020(bundle, _config("CRR"))

        assert len(found) == 1
        assert "collateral: 1 row(s), 250,000.00" in found[0].message
        assert "loans: 1 row(s), 1,000,000.00" in found[0].message

    def test_no_fx_table_at_all_reports_every_foreign_currency(self) -> None:
        bundle = _bundle(("L1", "USD", 10.0), ("L2", "GBP", 10.0), fx=None)

        assert [e.actual_value for e in _dq020(bundle, _config("CRR"))] == ["USD"]

    def test_a_null_rate_is_no_rate(self) -> None:
        bundle = _bundle(("L1", "USD", 10.0), fx=_rates(("USD", None)))

        assert [e.actual_value for e in _dq020(bundle, _config("CRR"))] == ["USD"]

    def test_base_null_and_rated_currencies_are_silent(self) -> None:
        bundle = _bundle(
            ("L1", "GBP", 1.0), ("L2", "EUR", 1.0), ("L3", None, 1.0), fx=_rates(("EUR", 0.85))
        )

        assert _dq020(bundle, _config("B31")) == []

    def test_conversion_switched_off_reports_nothing(self) -> None:
        config = dataclasses.replace(_config("CRR"), apply_fx_conversion=False)
        bundle = _bundle(("L1", "KWD", 1.0), fx=None)

        assert _dq020(bundle, config) == []

    def test_the_configless_loader_call_reports_nothing(self) -> None:
        bundle = _bundle(("L1", "KWD", 1.0), fx=None)

        assert not [e for e in validate_bundle_values(bundle) if e.code == ERROR_FX_RATE_MISSING]


@cache
def _run(regime: str, with_kwd_rate: bool) -> AggregatedResultBundle:
    pairs = [("EUR", 0.85), ("KWD", 2.5)] if with_kwd_rate else [("EUR", 0.85)]
    bundle = _bundle(("L_KWD", "KWD", 1_000_000.0), fx=_rates(*pairs))
    return PipelineOrchestrator().run_with_data(bundle, _config(regime))


def _loan_row(result: AggregatedResultBundle) -> dict[str, Any]:
    ledger = result.results.collect().filter(pl.col("exposure_reference") == "L_KWD")
    assert ledger.height == 1
    return ledger.row(0, named=True)


@pytest.mark.parametrize("regime", _REGIMES)
class TestPipeline:
    """End to end, both regimes: the number is unchanged, the silence is not."""

    def test_missing_rate_is_reported(self, regime: str) -> None:
        found = [e for e in _run(regime, False).errors if e.code == ERROR_FX_RATE_MISSING]

        assert [e.actual_value for e in found] == ["KWD"]

    def test_missing_rate_still_passes_the_amount_through(self, regime: str) -> None:
        row = _loan_row(_run(regime, False))

        assert row["risk_weight"] == pytest.approx(1.0), "fixture adequacy: 100% RW"
        assert row["ead_final"] == pytest.approx(1_000_000.0)

    def test_supplied_rate_converts_and_is_silent(self, regime: str) -> None:
        result = _run(regime, True)
        row = _loan_row(result)

        assert row["ead_final"] == pytest.approx(2_500_000.0)
        assert row["rwa_final"] == pytest.approx(2_500_000.0)
        assert not [e for e in result.errors if e.code == ERROR_FX_RATE_MISSING]
