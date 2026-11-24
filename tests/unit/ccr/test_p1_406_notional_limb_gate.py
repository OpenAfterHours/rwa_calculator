"""
P1.406: the input gate reports every equity / commodity trade engine/ccr prices
on the Art. 279b(1)(c) notional limb (CCR035), and only those.

Pipeline position:
    contracts/validation.py::validate_bundle_values -> ccr_input_checks
    (ccr_notional_limb_findings / ccr_notional_limb_errors), upstream of the
    ccr_sa_ccr stage whose compute_adjusted_notional_equity / _commodity apply
    the limb.

Key responsibilities:
- Flag a derivative equity or commodity trade (asset class matched exactly as
  engine/ccr matches it: trimmed, case-insensitive) whose market_price or
  number_of_units is null — the trade engine/ccr prices on |notional|.
- Leave every other trade alone: a priced equity / commodity trade, any other
  risk category (other risks has its own documented notional treatment), an SFT
  row (CCR020's), so the warning is not an alarm that always fires (LESSONS B9).
- Parity: a trade is flagged iff the engine's adjusted notional for it is the
  notional rather than market price x units.
- A notional-limb trade whose notional is 0 or null has no adjusted notional at
  all: the engine prices it at zero, so it is reported CCR038 (ERROR) instead of
  the CCR035 warning — the item's own defect class (a zero add-on) must not
  survive behind a warning for the project's 0.0 placeholder convention
  (``make_equity_trade``'s ``notional`` 0.0 for a unit-priced equity trade).

Rule text: CCR (CRR) Part Art. 279b(1)(c) (unchanged by PS1/26): "... the
product of the market price of one unit of the underlying instrument ... and the
number of units ...; where a transaction mapped to the equity risk category or
commodity risk category is contractually expressed as a notional amount,
institutions shall use the notional amount of the transaction rather than the
number of units in the underlying instrument as the adjusted notional amount".
"""

from __future__ import annotations

import polars as pl

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    TradeBundle,
)
from rwa_calc.contracts.ccr_input_checks import (
    ccr_notional_limb_errors,
    ccr_notional_limb_findings,
)
from rwa_calc.contracts.validation import validate_bundle_values
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.ccr.adjusted_notional import (
    compute_adjusted_notional_commodity,
    compute_adjusted_notional_equity,
)
from rwa_calc.engine.ccr.risk_categories import map_trade_risk_categories
from tests.fixtures.raw_bundle import make_raw_bundle

_PRICED = {"market_price": 10.0, "number_of_units": 1_000.0}

_CORPUS = [
    {"trade_id": "T01", "asset_class": "equity", **_PRICED},
    {"trade_id": "T02", "asset_class": "equity", "number_of_units": 1_000.0},
    {"trade_id": "T03", "asset_class": "equity", "market_price": 10.0},
    {"trade_id": "T04", "asset_class": " Equity "},
    {"trade_id": "T05", "asset_class": "commodity", "commodity_type": "OIL_GAS", **_PRICED},
    {"trade_id": "T06", "asset_class": "COMMODITY", "commodity_type": "OIL_GAS"},
    {"trade_id": "T07", "asset_class": "interest_rate"},
    {"trade_id": "T08", "asset_class": "fx"},
    {"trade_id": "T09", "asset_class": "weather"},
    {"trade_id": "T10", "asset_class": "equity", "transaction_type": "sft"},
]


def test_gate_flags_exactly_the_notional_limb_trades() -> None:
    """Equity / commodity with no market price x units; casing folded; SFT rows skipped."""
    # Act
    errors = _gate_errors()

    # Assert
    assert _flagged(errors) == {"T02", "T03", "T04", "T06"}
    assert {e.code for e in errors} == {"CCR035"}
    assert all(e.severity == ErrorSeverity.WARNING for e in errors)


def test_gate_flags_exactly_the_trades_the_engine_prices_on_the_notional() -> None:
    """Parity: flagged iff the engine's adjusted notional is |notional|, not price x units."""
    # Arrange — a notional no price x units in the corpus can equal
    derivative = [row for row in _CORPUS if row.get("transaction_type") != "sft"]
    mapped = map_trade_risk_categories(_trades(derivative))
    priced = compute_adjusted_notional_commodity(
        compute_adjusted_notional_equity(mapped.with_columns(pl.lit(7.0).alias("notional")))
    ).collect()

    # Act
    on_notional = set(
        priced.filter(
            pl.col("asset_class").is_in(["equity", "commodity"])
            & (pl.col("adjusted_notional") == 7.0)
        )["trade_id"].to_list()
    )

    # Assert
    assert on_notional == _flagged(_gate_errors())


def test_finding_names_the_trade_and_the_missing_inputs() -> None:
    """The message names the trade, its netting set, the null inputs and the notional used."""
    # Act
    by_trade = {_trade_of(e): e for e in _gate_errors()}

    # Assert
    message = by_trade["T03"].message
    assert "trade 'T03'" in message
    assert "netting set 'NS1'" in message
    assert "number_of_units null" in message
    assert "notional" in message
    assert by_trade["T03"].field_name == "number_of_units"
    assert by_trade["T02"].field_name == "market_price"


def test_gate_samples_and_summarises_beyond_the_cap() -> None:
    """Seven notional-limb trades, cap 5: five row-named warnings plus one summary."""
    # Arrange
    rows = [{"trade_id": f"T{i}", "asset_class": "equity"} for i in range(7)]
    findings = ccr_notional_limb_findings(_bundle(rows), _COLUMNS)
    assert findings is not None

    # Act
    errors = ccr_notional_limb_errors(findings.collect(), sample_cap=5)

    # Assert
    assert len(errors) == 6
    assert "2 additional trade(s)" in errors[-1].message


#: Notional-limb trades with and without a usable notional, plus a unit-priced
#: control carrying the 0.0 placeholder notional.
_ZERO_CORPUS = [
    {"trade_id": "Z1", "asset_class": "equity", "market_price": 50.0, "notional": 0.0},
    {"trade_id": "Z2", "asset_class": "equity", "notional": None},
    {"trade_id": "Z3", "asset_class": "commodity", "commodity_type": "OIL_GAS", "notional": 0.0},
    {"trade_id": "Z4", "asset_class": "equity", "number_of_units": 1_000.0, "notional": -0.0},
    {"trade_id": "Z5", "asset_class": "equity", "notional": 5_000_000.0},
    {"trade_id": "Z6", "asset_class": "equity", **_PRICED, "notional": 0.0},
]


def test_notional_limb_with_no_notional_is_an_error() -> None:
    """No price x units and a 0 / null notional: CCR038 ERROR, not the CCR035 warning."""
    # Act
    errors = _gate_errors(_ZERO_CORPUS)

    # Assert
    assert _flagged(errors, "CCR038") == {"Z1", "Z2", "Z3", "Z4"}
    assert _flagged(errors) == {"Z5"}
    assert {e.severity for e in errors if e.code == "CCR038"} == {ErrorSeverity.ERROR}


def test_no_notional_finding_names_the_trade_and_the_zero_add_on() -> None:
    """The CCR038 message names the trade, its netting set, the inputs and the consequence."""
    # Act
    by_trade = {_trade_of(e): e for e in _gate_errors(_ZERO_CORPUS) if e.code == "CCR038"}

    # Assert
    finding = by_trade["Z1"]
    assert "trade 'Z1'" in finding.message
    assert "netting set 'NS1'" in finding.message
    assert "market_price 50.0, number_of_units null" in finding.message
    assert "adds nothing to the equity add-on" in finding.message
    assert finding.field_name == "notional"
    assert finding.actual_value == "notional=0.00"
    assert by_trade["Z2"].actual_value == "notional=null"
    assert finding.counterparty_reference == "CP1"


def test_no_notional_gate_samples_and_summarises_beyond_the_cap() -> None:
    """Seven zero-notional trades, cap 5: five row-named ERRORs plus one summary ERROR."""
    # Arrange
    rows = [{"trade_id": f"T{i}", "asset_class": "equity", "notional": 0.0} for i in range(7)]
    findings = ccr_notional_limb_findings(_bundle(rows), _COLUMNS)
    assert findings is not None

    # Act
    errors = ccr_notional_limb_errors(findings.collect(), sample_cap=5)

    # Assert
    assert [e.code for e in errors] == ["CCR038"] * 6
    assert "2 additional trade(s)" in errors[-1].message
    assert errors[-1].severity == ErrorSeverity.ERROR


def test_input_gate_reports_ccr035() -> None:
    """validate_bundle_values runs the check (it is wired, not dormant — LESSONS B1)."""
    # Act
    errors = validate_bundle_values(_bundle([{"trade_id": "T1", "asset_class": "equity"}]))

    # Assert
    assert [_trade_of(e) for e in errors if e.code == "CCR035"] == ["T1"]


def test_input_gate_reports_ccr038() -> None:
    """validate_bundle_values raises CCR038 for a notional-limb trade with a zero notional."""
    # Act
    errors = validate_bundle_values(
        _bundle([{"trade_id": "T1", "asset_class": "equity", "notional": 0.0}])
    )

    # Assert
    assert [(e.code, _trade_of(e)) for e in errors if e.code in {"CCR035", "CCR038"}] == [
        ("CCR038", "T1")
    ]


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
        "notional": 5_000_000.0,
        "currency": "GBP",
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
            "notional": pl.Float64,
            "commodity_type": pl.String,
            "credit_quality": pl.String,
            "is_index": pl.Boolean,
            "market_price": pl.Float64,
            "number_of_units": pl.Float64,
        },
    )


def _bundle(rows: list[dict]):
    return make_raw_bundle(
        ccr=RawCCRBundle(
            trades=TradeBundle(trades=_trades(rows)),
            netting_sets=NettingSetBundle(
                netting_sets=pl.LazyFrame(
                    [{"netting_set_id": "NS1", "counterparty_reference": "CP1"}]
                )
            ),
            margin_agreements=MarginAgreementBundle(margin_agreements=pl.LazyFrame()),
            ccr_collateral=CCRCollateralBundle(ccr_collateral=pl.LazyFrame()),
        )
    )


def _gate_errors(rows: list[dict] | None = None):
    findings = ccr_notional_limb_findings(_bundle(_CORPUS if rows is None else rows), _COLUMNS)
    assert findings is not None
    return ccr_notional_limb_errors(findings.collect())


def _trade_of(error) -> str:
    return error.message.split("trade '")[1].split("'")[0]


def _flagged(errors, code: str = "CCR035") -> set[str]:
    return {_trade_of(e) for e in errors if e.code == code}
