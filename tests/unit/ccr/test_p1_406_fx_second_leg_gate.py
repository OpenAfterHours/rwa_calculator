"""
P1.406: the input gate reports every FX trade engine/ccr prices with no
second-leg notional — CCR036 (no second leg: read as one payment leg) and CCR037
(a second leg whose currency is stated but whose notional is not) — and only those.

Pipeline position:
    contracts/validation.py::validate_bundle_values -> ccr_input_checks
    (ccr_fx_second_leg_findings / ccr_fx_second_leg_errors), upstream of the
    ccr_sa_ccr stage whose compute_adjusted_notional_fx prices such a trade on its
    first leg's notional and flags it ``fx_own_hedging_set``.

Key responsibilities:
- Flag a derivative FX trade (asset class matched as engine/ccr matches it:
  trimmed, case-insensitive) whose ``notional_leg2`` is null: CCR036 WARNING
  when ``currency_leg2`` is null too, CCR037 ERROR when it is stated — except
  where the stated second leg is in the run's reporting currency and the first
  is not: Art. 279b(1)(b)(ii) then takes the first leg's notional at spot, so
  the missing notional is never needed and nothing is reported.
- CCR037 reads the run's reporting currency, so it is a configuration-dependent
  check: the configless file-loader call raises CCR036 only, and the pipeline
  entry (with its ``CalculationConfig``) raises CCR037 — as for DQ020.
- Leave every other trade alone: a complete two-leg FX trade, a second leg with
  a notional but no currency (CCR026's, reported where it is converted), any
  other risk category, an SFT row — so neither finding is an alarm that always
  fires (LESSONS B9).
- Parity: with every leg's rate known, a trade is flagged iff the engine prices
  it with no second-leg notional as its own hedging set (``fx_own_hedging_set``).
- Read a frame that genuinely omits the two second-leg columns (LESSONS B1).

Rule text: CCR (CRR) Part Art. 279b(1)(b) (unchanged by PS1/26): "(i) where the
transaction consists of one payment leg, the adjusted notional amount shall be
the notional amount of the derivative contract; (ii) where the transaction
consists of two payment legs and the notional amount of one payment leg is
denominated in the institution's reporting currency, the adjusted notional amount
shall be the notional amount of the other payment leg; ...". Art. 277a(1)(b):
FX trades share a hedging set "only where their primary risk driver ... is based
on the same currency pair".
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    TradeBundle,
)
from rwa_calc.contracts.ccr_input_checks import (
    ccr_fx_second_leg_errors,
    ccr_fx_second_leg_findings,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.validation import validate_bundle_values
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.ccr.adjusted_notional import compute_adjusted_notional_fx
from rwa_calc.engine.ccr.risk_categories import map_trade_risk_categories
from tests.fixtures.raw_bundle import make_raw_bundle

_COMPLETE = {"currency_leg2": "USD", "notional_leg2": 100e6}

_CORPUS = [
    {"trade_id": "F01", "asset_class": "fx", **_COMPLETE},
    {"trade_id": "F02", "asset_class": "fx"},
    {"trade_id": "F03", "asset_class": "fx", "currency_leg2": "USD"},
    {"trade_id": "F04", "asset_class": " FX "},
    {"trade_id": "F05", "asset_class": "Fx", "currency_leg2": "EUR"},
    {"trade_id": "F06", "asset_class": "fx", "notional_leg2": 100e6},
    {"trade_id": "F07", "asset_class": "interest_rate"},
    {"trade_id": "F08", "asset_class": "fx", "transaction_type": "sft"},
    {"trade_id": "F09", "asset_class": "equity", "market_price": 1.0, "number_of_units": 1.0},
    # the stated second leg is the reporting currency: (ii) needs only the USD leg
    {"trade_id": "F10", "asset_class": "fx", "currency": "USD", "currency_leg2": "GBP"},
    # both legs in the reporting currency: (ii)'s "other" leg is the unknown one
    {"trade_id": "F11", "asset_class": "fx", "currency": "GBP", "currency_leg2": "GBP"},
]


def test_gate_flags_exactly_the_fx_trades_with_no_second_leg_notional() -> None:
    """CCR036 for no second leg, CCR037 for a stated currency without its notional."""
    # Act
    errors = _gate_errors(_CORPUS)

    # Assert
    assert _flagged(errors, "CCR036") == {"F02", "F04"}
    assert _flagged(errors, "CCR037") == {"F03", "F05", "F11"}
    assert {e.code for e in errors} == {"CCR036", "CCR037"}


def test_gate_reads_the_configured_reporting_currency() -> None:
    """Base USD: F03's stated second leg (USD) is now the reporting currency, F10's is not.

    The exemption follows ``base_currency``, never a hard-coded GBP: with USD the
    reporting currency, F03 (GBP 5m against a stated USD leg) is (ii)'s complete
    value and F10 (USD 5m against a stated GBP leg) needs the GBP leg's notional;
    F11 (GBP against GBP) has both legs foreign and needs it too (iii).
    """
    # Act
    errors = _gate_errors(_CORPUS, base_currency="USD")

    # Assert
    assert _flagged(errors, "CCR037") == {"F05", "F10", "F11"}


def test_configless_gate_raises_no_ccr037() -> None:
    """No reporting currency (the file-loader call): CCR036 only; CCR037 needs the config."""
    # Act
    errors = _gate_errors(_CORPUS, base_currency=None)

    # Assert
    assert _flagged(errors, "CCR036") == {"F02", "F04"}
    assert {e.code for e in errors} == {"CCR036"}


def test_each_code_carries_its_severity() -> None:
    """CCR036 is a WARNING (the rule's own one-leg reading); CCR037 an ERROR (the input contradicts itself)."""
    # Act
    errors = _gate_errors(_CORPUS)

    # Assert
    assert {e.severity for e in errors if e.code == "CCR036"} == {ErrorSeverity.WARNING}
    assert {e.severity for e in errors if e.code == "CCR037"} == {ErrorSeverity.ERROR}


def test_gate_flags_exactly_the_trades_the_engine_prices_without_a_second_leg() -> None:
    """Parity: flagged iff the engine prices the trade on its first leg as its own hedging set.

    Every leg has a rate here (GBP / USD / EUR at 1.0), and the second leg's
    notional is one no first leg can equal, so the first leg's notional (7.0)
    marks the trades priced with no second-leg notional; of those, the engine
    isolates (``fx_own_hedging_set``) exactly the ones the gate reports — F10,
    whose missing notional (ii) never needs, is priced on its first leg, nets
    in its pair and is not reported.
    """
    # Arrange
    rates = pl.LazyFrame(
        {"currency_from": ["USD", "EUR"], "currency_to": ["GBP", "GBP"], "rate": [1.0, 1.0]},
        schema={"currency_from": pl.String, "currency_to": pl.String, "rate": pl.Float64},
    )
    derivative = [row for row in _CORPUS if row.get("transaction_type") != "sft"]
    mapped = map_trade_risk_categories(
        _trades(derivative).with_columns(pl.lit(7.0).alias("notional"))
    )
    priced = compute_adjusted_notional_fx(mapped, "GBP", rates).collect()

    # Act
    on_first_leg = priced.filter(
        (pl.col("asset_class") == "fx") & (pl.col("adjusted_notional") == 7.0)
    )
    isolated = set(on_first_leg.filter(pl.col("fx_own_hedging_set"))["trade_id"].to_list())

    # Assert
    errors = _gate_errors(_CORPUS)
    assert isolated == _flagged(errors, "CCR036") | _flagged(errors, "CCR037")
    assert set(on_first_leg["trade_id"].to_list()) - isolated == {"F10"}


def test_finding_names_the_trade_netting_set_counterparty_and_treatment() -> None:
    """Row-named: trade, netting set, counterparty, the null inputs and the notional used."""
    # Act
    by_trade = {_trade_of(e): e for e in _gate_errors(_CORPUS)}

    # Assert — CCR036, no second leg
    single = by_trade["F02"]
    assert "trade 'F02'" in single.message
    assert "netting set 'NS1'" in single.message
    assert "one payment leg" in single.message
    assert "5,000,000.00 (GBP)" in single.message
    assert single.counterparty_reference == "CP1"
    assert single.field_name == "notional_leg2"
    assert single.actual_value == "notional_leg2=null, currency_leg2=null"
    # Assert — CCR037, a stated second leg with no notional
    stated = by_trade["F03"]
    assert "currency_leg2 USD is stated but notional_leg2 is null" in stated.message
    assert "its own FX hedging set" in stated.message
    assert "estimate" in stated.message
    assert stated.actual_value == "notional_leg2=null, currency_leg2=USD"


def test_gate_samples_and_summarises_beyond_the_cap_per_code() -> None:
    """Seven of each, cap 5: five row-named entries plus one summary, per code."""
    # Arrange
    rows = [{"trade_id": f"S{i}", "asset_class": "fx"} for i in range(7)] + [
        {"trade_id": f"P{i}", "asset_class": "fx", "currency_leg2": "USD"} for i in range(7)
    ]
    findings = ccr_fx_second_leg_findings(_bundle(rows), _COLUMNS, base_currency="GBP")
    assert findings is not None

    # Act
    errors = ccr_fx_second_leg_errors(findings.collect(), sample_cap=5)

    # Assert
    for code, severity in (("CCR036", ErrorSeverity.WARNING), ("CCR037", ErrorSeverity.ERROR)):
        of_code = [e for e in errors if e.code == code]
        assert len(of_code) == 6
        assert "2 additional trade(s)" in of_code[-1].message
        assert of_code[-1].severity == severity


def test_gate_reads_a_frame_that_omits_the_second_leg_columns() -> None:
    """No ``notional_leg2`` / ``currency_leg2`` columns: every FX trade is CCR036, none fails.

    A column pinned as a typed null in ``schema_overrides`` cannot reproduce this
    path (LESSONS B1), so the frame genuinely omits both.
    """
    # Arrange
    trades = _trades([{"trade_id": "F1", "asset_class": "fx"}, {"trade_id": "I1"}]).drop(
        "notional_leg2", "currency_leg2"
    )
    assert "notional_leg2" not in trades.collect_schema().names()
    columns = _COLUMNS - {"notional_leg2", "currency_leg2"}

    # Act
    findings = ccr_fx_second_leg_findings(_bundle_of(trades), columns, base_currency="GBP")
    assert findings is not None
    errors = ccr_fx_second_leg_errors(findings.collect())

    # Assert
    assert [(e.code, _trade_of(e)) for e in errors] == [("CCR036", "F1")]


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (
            CalculationConfig.crr(reporting_date=date(2026, 3, 31)),
            [("CCR036", "T1"), ("CCR037", "T2")],
        ),
        # configless (the file-loader call): the reporting currency is unknown
        (None, [("CCR036", "T1")]),
    ],
    ids=["with_config", "configless"],
)
def test_input_gate_reports_ccr036_and_ccr037(
    config: CalculationConfig | None, expected: list[tuple[str, str]]
) -> None:
    """validate_bundle_values runs the check (it is wired, not dormant — LESSONS B1).

    T4's stated second leg is the run's reporting currency (GBP), so (ii) prices
    it on its USD leg at spot and nothing is reported.
    """
    # Act
    errors = validate_bundle_values(
        _bundle(
            [
                {"trade_id": "T1", "asset_class": "fx"},
                {"trade_id": "T2", "asset_class": "fx", "currency_leg2": "USD"},
                {"trade_id": "T3", "asset_class": "fx", **_COMPLETE},
                {"trade_id": "T4", "asset_class": "fx", "currency": "USD", "currency_leg2": "GBP"},
            ]
        ),
        config=config,
    )

    # Assert
    reported = sorted((e.code, _trade_of(e)) for e in errors if e.code in {"CCR036", "CCR037"})
    assert reported == expected


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

_COLUMNS = frozenset(
    {
        "trade_id",
        "netting_set_id",
        "transaction_type",
        "asset_class",
        "notional",
        "currency",
        "notional_leg2",
        "currency_leg2",
        "commodity_type",
        "credit_quality",
        "is_index",
        "market_price",
        "number_of_units",
    }
)


def _trades(rows: list[dict]) -> pl.LazyFrame:
    base = {
        "netting_set_id": "NS1",
        "transaction_type": "derivative",
        "asset_class": "interest_rate",
        "notional": 5_000_000.0,
        "currency": "GBP",
        "notional_leg2": None,
        "currency_leg2": None,
        "commodity_type": None,
        "credit_quality": None,
        "is_index": None,
        "market_price": None,
        "number_of_units": None,
    }
    return pl.LazyFrame(
        [{**base, **row} for row in rows],
        schema_overrides={
            "asset_class": pl.String,
            "notional_leg2": pl.Float64,
            "currency_leg2": pl.String,
            "commodity_type": pl.String,
            "credit_quality": pl.String,
            "is_index": pl.Boolean,
            "market_price": pl.Float64,
            "number_of_units": pl.Float64,
        },
    )


def _bundle(rows: list[dict]):
    return _bundle_of(_trades(rows))


def _bundle_of(trades: pl.LazyFrame):
    return make_raw_bundle(
        ccr=RawCCRBundle(
            trades=TradeBundle(trades=trades),
            netting_sets=NettingSetBundle(
                netting_sets=pl.LazyFrame(
                    [{"netting_set_id": "NS1", "counterparty_reference": "CP1"}]
                )
            ),
            margin_agreements=MarginAgreementBundle(margin_agreements=pl.LazyFrame()),
            ccr_collateral=CCRCollateralBundle(ccr_collateral=pl.LazyFrame()),
        )
    )


def _gate_errors(rows: list[dict], base_currency: str | None = "GBP"):
    findings = ccr_fx_second_leg_findings(_bundle(rows), _COLUMNS, base_currency=base_currency)
    assert findings is not None
    return ccr_fx_second_leg_errors(findings.collect())


def _trade_of(error) -> str:
    return error.message.split("trade '")[1].split("'")[0]


def _flagged(errors, code: str) -> set[str]:
    return {_trade_of(e) for e in errors if e.code == code}
