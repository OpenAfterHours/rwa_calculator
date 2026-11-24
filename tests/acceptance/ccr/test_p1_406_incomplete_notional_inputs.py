"""
P1.406 through the real pipeline: an FX, equity or commodity trade whose
adjusted-notional inputs are incomplete is priced conservatively AND reported,
never silently zeroed — both regimes.

Pipeline position:
    RawDataBundle -> input gate (CCR035 / CCR036 / CCR037 / CCR038) -> ccr_sa_ccr stage
    (compute_adjusted_notional_fx / _equity / _commodity, CCR026 findings)
    -> SA calculator -> aggregated results (synthetic ``ccr__NS1`` row)

Key responsibilities:
- Pin a hand-calculated, non-zero EAD for each incomplete input shape the review
  CC-06 fix left open, under current UK CRR and under Basel 3.1, plus the
  row-named error that reports it.
- Pin the controls: a complete input prices exactly as before and raises no
  finding, so the new findings are not an alarm that always fires.
- Pin the netting: an FX trade priced with an unconverted leg, or with no
  second-leg notional (a stated second leg missing its notional — CCR037 — or
  no second leg at all — CCR036), is its own hedging set, so on a hedged pair
  the estimate cannot price the netting set below the value it has with the
  trade left out; a trade priced by the rule's own equity notional limb nets
  like any other, and there pricing it lowers EAD (the rule's netting).

Rule text (PRA Rulebook, Counterparty Credit Risk (CRR) Part, read 2026-11-23 in
both the current and the 01/01/2027 view — identical; PS1/26 Annex R does not
amend Arts. 277-280f):
- Art. 278(1): "institutions shall include the add-on of a given risk category in
  the calculation of the potential future exposure of a netting set where at
  least one transaction of the netting set has been mapped to that risk
  category."
- Art. 279b(1)(b): "(i) where the transaction consists of one payment leg, the
  adjusted notional amount shall be the notional amount of the derivative
  contract; (ii) where the transaction consists of two payment legs and the
  notional amount of one payment leg is denominated in the institution's
  reporting currency, the adjusted notional amount shall be the notional amount
  of the other payment leg; (iii) where the transaction consists of two payment
  legs and the notional amount of each payment leg is denominated in a currency
  other than the institution's reporting currency, the adjusted notional amount
  shall be the largest of the notional amounts of the two payment legs after
  those amounts have been converted into the institution's reporting currency at
  the prevailing spot exchange rate;"
- Art. 279b(1)(c): "... the product of the market price of one unit of the
  underlying instrument of the transaction and the number of units in the
  underlying instrument referenced by the transaction; where a transaction mapped
  to the equity risk category or commodity risk category is contractually
  expressed as a notional amount, institutions shall use the notional amount of
  the transaction rather than the number of units in the underlying instrument as
  the adjusted notional amount;"
- Art. 279b(3): the adjusted notional is converted "into their reporting currency
  at the prevailing spot exchange rate".

Defect pinned (measured pre-fix through PipelineOrchestrator, both regimes): every
FX case below with a missing rate gave ead 0.0 (the both-foreign case 4,284,000,
the EUR leg alone) and no CCR026 naming the second leg; the single-leg GBP trade
and the GBP trade with a stated USD second leg but no notional_leg2 gave 0.0 with
no finding; the notional-only equity and commodity trades gave 0.0 with no error.

Hand calculation (one trade, start = reporting date, 1-year maturity: >= 250
business days, so MF = 1; MtM 0, so RC = 0 and the PFE multiplier is 1; delta 1;
alpha 1.4 for the financial counterparty; regime-invariant — no SD in FX, equity
or commodity):
    FX (SF 4%, Art. 280 Table 1):
        GBP 80m / USD 100m, USD -> GBP 0.80: d = 80m (ii)
            EAD = 1.4 x 0.04 x 80m                  = 4,480,000
        any leg without a rate: d = the largest leg notional, each converted
            where it has a rate and unconverted where it has none
            GBP 80m / USD 100m, no USD rate: max(80m, 100m)       = 100m
            EUR 90m / USD 100m, EUR 0.85, no USD: max(76.5m, 100m) = 100m
            USD 100m / GBP 80m, no USD rate: max(100m, 80m)       = 100m
            EAD = 1.4 x 0.04 x 100m                 = 5,600,000
        no second-leg notional, GBP 80m: d = the first leg's notional = 80m
            (no second leg: rule (i), CCR036 WARNING; currency_leg2 USD
            stated: an estimate, CCR037 ERROR)  -> 4,480,000
        no second-leg notional, USD 100m against a stated GBP leg: rule (ii),
            the other (USD) leg at spot, 100m x 0.80 = 80m — the complete value,
            no finding, netted in USD/GBP     -> 4,480,000
        each such trade its own hedging set: against a long GBP 80m / USD
            100m (d = 80m by (ii)), a short with no second-leg notional
            EAD = 1.4 x 0.04 x (80m + 80m)      = 8,960,000
        but a short USD 100m against a stated GBP leg nets with a long
            USD 100m / GBP 80m: |80m - 80m|      -> EAD 0.0
    equity single name (SF 32%, one entity: AddOn = SF x |EN|):
        notional 50m, no price / units: d = |notional| = 50m
            EAD = 1.4 x 0.32 x 50m                  = 22,400,000
        control 50 x 1,000,000 units               = 22,400,000
        price 50, no units, notional 0.0 (the placeholder): no adjusted
            notional under either limb             -> EAD 0.0, CCR038 ERROR
    commodity OIL_GAS (SF 18%, one type: AddOn = SF x |EN|):
        notional 10m, no price / units: d = 10m
            EAD = 1.4 x 0.18 x 10m                  = 2,520,000
    the notional limb at 5 years (MF still 1; SD(S, E) about 4.38, which the
    limb does not carry — unlike Art. 279b(1)(a) and the other-risks shape
    |notional| x max(1, SD), indistinguishable from |notional| at 1 year):
        equity 50m -> 22,400,000; commodity OIL_GAS 10m -> 2,520,000
        long 219,174,562.14 by price x units, short notional-only 50m, one
            entity: EAD = 1.4 x 0.32 x 169,174,562.14 = 75,790,203.84

References:
    - CCR (CRR) Part Art. 274(2), 277(1), 277a(1)(b), 278(1), 279b(1)(b)/(c),
      279b(3), 280
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    RawDataBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import CCR_COLLATERAL_SCHEMA, COUNTERPARTY_SCHEMA, FX_RATES_SCHEMA
from rwa_calc.domain.enums import ErrorSeverity, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.margin_builder import create_margin_agreements
from tests.fixtures.ccr.netting_set_builder import create_netting_sets, make_netting_set
from tests.fixtures.ccr.trade_builder import create_trades, make_trade
from tests.fixtures.raw_bundle import make_raw_bundle

_REGIMES = ["crr", "b31"]

#: regime -> (reporting date, 1-year maturity date).
_DATES = {
    "crr": (date(2026, 3, 31), date(2027, 3, 31)),
    "b31": (date(2027, 3, 31), date(2028, 3, 31)),
}

_ALPHA = 1.4
_SF_FX = 0.04

#: Rates to GBP: ``None`` means the run carries no fx_rates table at all.
_ONLY_EUR = [("EUR", 0.85)]
_WITH_USD = [("USD", 0.80)]

_FX_LEGS: dict[str, dict[str, Any]] = {
    "gbp_usd": {
        "currency": "GBP",
        "notional": 80e6,
        "currency_leg2": "USD",
        "notional_leg2": 100e6,
    },
    "eur_usd": {
        "currency": "EUR",
        "notional": 90e6,
        "currency_leg2": "USD",
        "notional_leg2": 100e6,
    },
    "usd_gbp": {
        "currency": "USD",
        "notional": 100e6,
        "currency_leg2": "GBP",
        "notional_leg2": 80e6,
    },
    "gbp_single_leg": {"currency": "GBP", "notional": 80e6},
    "gbp_usd_no_leg2_notional": {"currency": "GBP", "notional": 80e6, "currency_leg2": "USD"},
    "usd_gbp_no_leg2_notional": {"currency": "USD", "notional": 100e6, "currency_leg2": "GBP"},
}

#: The codes an incomplete FX leg is reported under: CCR026 (a leg with no spot
#: rate), CCR036 (no second leg: read as one payment leg), CCR037 (a second leg
#: whose currency is stated but whose notional is not).
_FX_LEG_CODES = ("CCR026", "CCR036", "CCR037")

#: The severity each of those codes carries.
_FX_LEG_SEVERITY = {
    "CCR026": ErrorSeverity.ERROR,
    "CCR036": ErrorSeverity.WARNING,
    "CCR037": ErrorSeverity.ERROR,
}

#: scenario -> (legs, fx rates, expected ead, the (code, field, actual value) findings)
_FX_SCENARIOS: dict[str, tuple[str, list[tuple[str, float]] | None, float, list[Any]]] = {
    "leg2_no_rate": (
        "gbp_usd",
        _ONLY_EUR,
        _ALPHA * _SF_FX * 100e6,
        [("CCR026", "currency_leg2", "'USD'")],
    ),
    "both_foreign_leg2_no_rate": (
        "eur_usd",
        _ONLY_EUR,
        _ALPHA * _SF_FX * 100e6,
        [("CCR026", "currency_leg2", "'USD'")],
    ),
    "no_fx_rates_table": (
        "gbp_usd",
        None,
        _ALPHA * _SF_FX * 100e6,
        [("CCR026", "currency_leg2", "'USD'")],
    ),
    "leg1_no_rate": (
        "usd_gbp",
        _ONLY_EUR,
        _ALPHA * _SF_FX * 100e6,
        [("CCR026", "currency", "'USD'")],
    ),
    "single_payment_leg": (
        "gbp_single_leg",
        _ONLY_EUR,
        _ALPHA * _SF_FX * 80e6,
        [("CCR036", "notional_leg2", "notional_leg2=null, currency_leg2=null")],
    ),
    "stated_pair_no_leg2_notional": (
        "gbp_usd_no_leg2_notional",
        _WITH_USD,
        _ALPHA * _SF_FX * 80e6,
        [("CCR037", "notional_leg2", "notional_leg2=null, currency_leg2=USD")],
    ),
    # the stated second leg is the reporting currency: (ii) is the USD leg at
    # spot, 100m x 0.80 = 80m — complete, so nothing is reported
    "reporting_currency_leg2_no_notional": (
        "usd_gbp_no_leg2_notional",
        _WITH_USD,
        _ALPHA * _SF_FX * 80e6,
        [],
    ),
    "control_all_rates": ("gbp_usd", _WITH_USD, _ALPHA * _SF_FX * 80e6, []),
}

#: scenario -> (trade overrides, expected ead, CCR035 expected)
_UNIT_SCENARIOS: dict[str, tuple[dict[str, Any], float, bool]] = {
    "equity_notional_only": (
        {"asset_class": "equity", "notional": 50e6, "reference_entity": "R1", "is_index": False},
        _ALPHA * 0.32 * 50e6,
        True,
    ),
    "commodity_notional_only": (
        {"asset_class": "commodity", "notional": 10e6, "commodity_type": "OIL_GAS"},
        _ALPHA * 0.18 * 10e6,
        True,
    ),
    "equity_price_times_units_control": (
        {
            "asset_class": "equity",
            "notional": 0.0,
            "reference_entity": "R1",
            "is_index": False,
            "market_price": 50.0,
            "number_of_units": 1_000_000.0,
        },
        _ALPHA * 0.32 * 50e6,
        False,
    ),
}


@pytest.mark.parametrize("regime", _REGIMES)
@pytest.mark.parametrize("scenario", list(_FX_SCENARIOS))
def test_fx_trade_with_missing_leg_input_is_priced_and_reported(scenario: str, regime: str) -> None:
    """Art. 279b(1)(b): a missing spot rate or second leg never zeroes the FX add-on.

    Each incomplete shape is reported: CCR026 names a leg with no spot rate,
    CCR036 (WARNING) a trade with no second leg read as one payment leg
    (Art. 279b(1)(b)(i)), CCR037 a second leg whose currency is stated but whose
    notional is not. The complete control raises none of them.
    """
    # Arrange
    legs, rates, expected_ead, expected_findings = _FX_SCENARIOS[scenario]
    trade = {"asset_class": "fx", **_FX_LEGS[legs]}

    # Act
    row, errors = _run(regime, trade, rates)

    # Assert — the number
    assert row["ead_final"] == pytest.approx(expected_ead, rel=1e-9)
    # Assert — the report, each finding at its code's severity
    fx_leg = [e for e in errors if e.code in _FX_LEG_CODES]
    assert [(e.code, e.field_name, e.actual_value) for e in fx_leg] == expected_findings
    assert all(e.severity == _FX_LEG_SEVERITY[e.code] for e in fx_leg)


@pytest.mark.parametrize("regime", _REGIMES)
def test_leg2_finding_names_the_trade_and_the_treatment(regime: str) -> None:
    """The second-leg CCR026 is row-named and does not claim the trade was left unpriced."""
    # Act
    _row, errors = _run(regime, {"asset_class": "fx", **_FX_LEGS["gbp_usd"]}, _ONLY_EUR)

    # Assert
    (finding,) = [e for e in errors if e.code == "CCR026"]
    assert "trade 'T1'" in finding.message
    assert "netting set 'NS1'" in finding.message
    assert "largest" in finding.message


@pytest.mark.parametrize("regime", _REGIMES)
@pytest.mark.parametrize("scenario", list(_UNIT_SCENARIOS))
def test_equity_and_commodity_without_units_take_the_notional(scenario: str, regime: str) -> None:
    """Art. 279b(1)(c): no market price x units -> the contractual notional, reported CCR035."""
    # Arrange
    overrides, expected_ead, reported = _UNIT_SCENARIOS[scenario]

    # Act
    row, errors = _run(regime, overrides, _WITH_USD)

    # Assert — the number
    assert row["ead_final"] == pytest.approx(expected_ead, rel=1e-9)
    # Assert — the report, naming the trade
    ccr035 = [e for e in errors if e.code == "CCR035"]
    assert len(ccr035) == (1 if reported else 0)
    if reported:
        assert "trade 'T1'" in ccr035[0].message
        assert ccr035[0].severity == ErrorSeverity.WARNING


#: Two EUR/USD trades in one netting set (one currency pair, so at HEAD one
#: hedging set) that offset each other.
_HEDGED_EUR_USD: list[dict[str, Any]] = [
    {
        "trade_id": "A",
        "asset_class": "fx",
        "currency": "EUR",
        "notional": 90e6,
        "currency_leg2": "USD",
        "notional_leg2": 100e6,
        "is_long": True,
    },
    {
        "trade_id": "B",
        "asset_class": "fx",
        "currency": "EUR",
        "notional": 100e6,
        "currency_leg2": "USD",
        "notional_leg2": 100e6,
        "is_long": False,
    },
]

#: scenario -> (fx rates, expected ead). With a leg unconverted each trade is its
#: own hedging set: d_A = max(76.5m, 100m), d_B = max(85m, 100m), so
#: EAD = 1.4 x 0.04 x (100m + 100m). With every rate the pair nets:
#: d_A = max(76.5m, 80m) long, d_B = max(85m, 80m) short, EAD = 1.4 x 0.04 x 5m.
_HEDGED_SCENARIOS: dict[str, tuple[list[tuple[str, float]] | None, float]] = {
    "usd_rate_missing": (_ONLY_EUR, _ALPHA * _SF_FX * (100e6 + 100e6)),
    "no_fx_rates_table": (None, _ALPHA * _SF_FX * (100e6 + 100e6)),
    "control_all_rates": ([*_ONLY_EUR, *_WITH_USD], _ALPHA * _SF_FX * 5e6),
}

#: The risk weight this run's SA calculator gives the unrated institution
#: counterparty (not part of this item) — pinned so the capital effect is asserted
#: in RWA, absolutely, as well as in EAD.
_COUNTERPARTY_RW = {"crr": 1.0, "b31": 1.5}


@pytest.mark.parametrize("regime", _REGIMES)
@pytest.mark.parametrize("scenario", list(_HEDGED_SCENARIOS))
def test_fx_trade_with_an_unconverted_leg_offsets_nothing(scenario: str, regime: str) -> None:
    """A trade priced with an unconverted leg is its own hedging set (Art. 277a(1)(b)).

    Its adjusted notional is an estimate, not the Art. 279b(1)(b) value, so it is
    not netted against the pair's other trades: the netting set's add-on is then
    no lower than with the trade left out of the pair's hedging set. Pre-fix
    (measured through this pipeline, both regimes): usd_rate_missing 476,000 (the
    EUR legs alone netted, the USD legs dropped), no_fx_rates_table 0.0; with the
    unconverted leg netted in the pair's hedging set (the first P1.406 attempt)
    usd_rate_missing gave 0.0 — below the 280,000 the complete rates give.
    In RWA: usd_rate_missing 11,200,000 CRR / 16,800,000 Basel 3.1 (HEAD 476,000
    / 714,000; first attempt 0.0 / 0.0).
    """
    # Arrange
    rates, expected_ead = _HEDGED_SCENARIOS[scenario]

    # Act
    row, _errors = _run(regime, _HEDGED_EUR_USD, rates)

    # Assert
    assert row["ead_final"] == pytest.approx(expected_ead, rel=1e-9)
    assert row["rwa_final"] == pytest.approx(expected_ead * _COUNTERPARTY_RW[regime], rel=1e-9)


@pytest.mark.parametrize("regime", _REGIMES)
def test_hedged_fx_trades_with_an_unconverted_leg_are_each_reported(regime: str) -> None:
    """Both offsetting trades are named in a CCR026 on their second leg."""
    # Act
    _row, errors = _run(regime, _HEDGED_EUR_USD, _ONLY_EUR)

    # Assert
    findings = sorted(
        (e.field_name, e.actual_value, "trade 'A'" in e.message)
        for e in errors
        if e.code == "CCR026"
    )
    assert findings == [("currency_leg2", "'USD'", False), ("currency_leg2", "'USD'", True)]


#: A long GBP 80m / USD 100m forward (USD -> GBP 0.80, so d = 80m by (ii)).
_GBP_USD_LONG: dict[str, Any] = {
    "trade_id": "A",
    "asset_class": "fx",
    "currency": "GBP",
    "notional": 80e6,
    "currency_leg2": "USD",
    "notional_leg2": 100e6,
    "is_long": True,
}

#: scenario -> (trades, expected ead). Every trade is GBP 80m on its first leg, so
#: d = 80m each; a trade with no second-leg notional is its own hedging set, so
#: EAD = 1.4 x 0.04 x (80m + 80m). The complete control nets: |80m - 80m| = 0.
_NO_LEG2_NOTIONAL_HEDGES: dict[str, tuple[list[dict[str, Any]], float]] = {
    "stated_pair_no_leg2_notional": (
        [
            _GBP_USD_LONG,
            {
                "trade_id": "B",
                "asset_class": "fx",
                "currency": "GBP",
                "notional": 80e6,
                "currency_leg2": "USD",
                "is_long": False,
            },
        ],
        _ALPHA * _SF_FX * (80e6 + 80e6),
    ),
    "two_single_payment_legs": (
        [
            {"trade_id": "A", "asset_class": "fx", "currency": "GBP", "notional": 80e6},
            {
                "trade_id": "B",
                "asset_class": "fx",
                "currency": "GBP",
                "notional": 80e6,
                "is_long": False,
            },
        ],
        _ALPHA * _SF_FX * (80e6 + 80e6),
    ),
    # the short's stated second leg is GBP with no notional: (ii) takes its USD
    # leg at spot (100m x 0.80 = 80m), the rule value, so it nets in USD/GBP
    "reporting_currency_leg2_no_notional": (
        [
            {
                **_GBP_USD_LONG,
                "currency": "USD",
                "notional": 100e6,
                "currency_leg2": "GBP",
                "notional_leg2": 80e6,
            },
            {
                "trade_id": "B",
                "asset_class": "fx",
                "currency": "USD",
                "notional": 100e6,
                "currency_leg2": "GBP",
                "is_long": False,
            },
        ],
        0.0,
    ),
    "control_complete_pair": (
        [
            _GBP_USD_LONG,
            {**_GBP_USD_LONG, "trade_id": "B", "is_long": False},
        ],
        0.0,
    ),
}


@pytest.mark.parametrize("regime", _REGIMES)
@pytest.mark.parametrize("scenario", list(_NO_LEG2_NOTIONAL_HEDGES))
def test_fx_trade_with_no_second_leg_notional_offsets_nothing(scenario: str, regime: str) -> None:
    """A trade with no second-leg notional is its own hedging set (Art. 277a(1)(b)).

    With ``currency_leg2`` stated and ``notional_leg2`` null the input contradicts
    itself: it names a second leg whose notional is unknown, so the first leg's
    notional is an estimate of the Art. 279b(1)(b)(ii) value. With no second leg
    at all the trade states no currency pair, and Art. 277a(1)(b) shares a hedging
    set "only where their primary risk driver ... is based on the same currency
    pair". Either way the trade offsets nothing. Measured through this pipeline,
    both regimes: HEAD priced trade B at zero (EAD 4,480,000, the long alone, for
    the stated pair; 0.0 for the single legs); the second P1.406 attempt netted it
    against the long (EAD 0.0 for both). In RWA, stated pair: 8,960,000 CRR /
    13,440,000 Basel 3.1 (HEAD 4,480,000 / 6,720,000; second attempt 0.0 / 0.0).

    Not so where the stated second leg is the reporting currency: (ii) takes "the
    notional amount of the other payment leg", the USD leg at spot, so the GBP
    leg's notional is never needed, the value is the rule's and the trade nets in
    USD/GBP (Art. 277a(1)(b)). EAD 0.0 in both regimes, as at HEAD; the third
    P1.406 attempt isolated it (EAD 8,960,000; RWA 8,960,000 CRR / 13,440,000
    Basel 3.1) and raised a false CCR037.
    """
    # Arrange
    trades, expected_ead = _NO_LEG2_NOTIONAL_HEDGES[scenario]

    # Act
    row, _errors = _run(regime, trades, _WITH_USD)

    # Assert
    assert row["ead_final"] == pytest.approx(expected_ead, abs=1e-6)
    assert row["rwa_final"] == pytest.approx(expected_ead * _COUNTERPARTY_RW[regime], abs=1e-6)


@pytest.mark.parametrize("regime", _REGIMES)
def test_reporting_currency_leg2_with_no_notional_raises_no_finding(regime: str) -> None:
    """The hedged swapped-legs pair: the short's missing GBP notional is reported nowhere.

    It is not needed (Art. 279b(1)(b)(ii)), so no CCR036 / CCR037 / CCR026 fires —
    the finding is not an alarm on a complete input (LESSONS B9).
    """
    # Arrange
    trades, _ead = _NO_LEG2_NOTIONAL_HEDGES["reporting_currency_leg2_no_notional"]

    # Act
    _row, errors = _run(regime, trades, _WITH_USD)

    # Assert
    assert [e.code for e in errors if e.code in _FX_LEG_CODES] == []


@pytest.mark.parametrize("regime", _REGIMES)
@pytest.mark.parametrize(
    ("legs", "code", "treatment"),
    [
        ("gbp_single_leg", "CCR036", "one payment leg"),
        ("gbp_usd_no_leg2_notional", "CCR037", "notional_leg2 is null"),
    ],
)
def test_fx_trade_with_no_second_leg_notional_is_named(
    legs: str, code: str, treatment: str, regime: str
) -> None:
    """The CCR036 / CCR037 finding names the trade, its netting set and the treatment."""
    # Act
    _row, errors = _run(regime, {"asset_class": "fx", **_FX_LEGS[legs]}, _WITH_USD)

    # Assert
    (finding,) = [e for e in errors if e.code == code]
    assert "trade 'T1'" in finding.message
    assert "netting set 'NS1'" in finding.message
    assert treatment in finding.message
    assert "its own FX hedging set" in finding.message
    assert finding.counterparty_reference == "CP-FIN"


@pytest.mark.parametrize("regime", _REGIMES)
@pytest.mark.parametrize(
    "drop", [("notional_leg2",), ("notional_leg2", "currency_leg2")], ids=["notional", "both"]
)
def test_book_whose_trades_omit_the_fx_leg_columns_still_prices(
    drop: tuple[str, ...], regime: str
) -> None:
    """A trades frame that genuinely omits FX second-leg columns, no fx_rates table.

    The FX branch now runs on every call, so it must not read a column the frame
    does not have (LESSONS D2(b)). Measured on the second P1.406 attempt with
    ``notional_leg2`` omitted: CCR stage error 'unable to find column
    "notional_leg2"' and no ccr__ row at all (HEAD, which skipped the branch with
    no table, priced it). With ``currency_leg2`` omitted as well HEAD failed too:
    ``assign_hedging_set`` reads it. The trade is the unit-priced equity control:
    1.4 x 0.32 x 50 x 1,000,000.
    """
    # Arrange
    trade = _UNIT_SCENARIOS["equity_price_times_units_control"][0]

    # Act
    row, errors = _run(regime, trade, None, drop=drop)

    # Assert
    assert row["ead_final"] == pytest.approx(_ALPHA * 0.32 * 50e6, rel=1e-9)
    assert [e.code for e in errors if e.code.startswith("PIPELINE")] == []
    assert [e.code for e in errors if e.code in _FX_LEG_CODES] == []


#: scenario -> notional-limb equity / commodity trade whose notional is 0 or null.
_NO_NOTIONAL_SCENARIOS: dict[str, dict[str, Any]] = {
    # make_equity_trade's placeholder convention: notional 0.0, units missing
    "equity_placeholder_notional_no_units": {
        "asset_class": "equity",
        "notional": 0.0,
        "reference_entity": "R1",
        "is_index": False,
        "market_price": 50.0,
    },
    "commodity_zero_notional_no_price": {
        "asset_class": "commodity",
        "notional": 0.0,
        "commodity_type": "OIL_GAS",
        "number_of_units": 1_000.0,
    },
}


@pytest.mark.parametrize("regime", _REGIMES)
@pytest.mark.parametrize("scenario", list(_NO_NOTIONAL_SCENARIOS))
def test_notional_limb_with_a_zero_notional_is_reported_as_an_error(
    scenario: str, regime: str
) -> None:
    """No price x units and a zero notional: no adjusted notional at all -> CCR038 ERROR.

    Art. 279b(1)(c) has nothing to price the trade on — the product is null and the
    notional is 0 — so the trade adds nothing to its add-on (EAD 0.0 with MtM 0).
    That zero is reported as an ERROR naming the trade, never as the CCR035
    warning that claims the notional "is the adjusted notional". Measured on the
    third P1.406 attempt: EAD 0.0 with only a CCR035 WARNING; at HEAD EAD 0.0
    with no CCR finding at all.
    """
    # Arrange
    trade = _NO_NOTIONAL_SCENARIOS[scenario]

    # Act
    row, errors = _run(regime, trade, _WITH_USD)

    # Assert
    assert row["ead_final"] == pytest.approx(0.0, abs=1e-6)
    limb = [(e.code, e.severity) for e in errors if e.code in {"CCR035", "CCR038"}]
    assert limb == [("CCR038", ErrorSeverity.ERROR)]
    (finding,) = [e for e in errors if e.code == "CCR038"]
    assert "trade 'T1'" in finding.message
    assert finding.counterparty_reference == "CP-FIN"


@pytest.mark.parametrize("regime", _REGIMES)
def test_equity_notional_limb_offsets_a_priced_trade_on_the_same_entity(regime: str) -> None:
    """Art. 279b(1)(c)'s notional limb is the rule's value, so it nets like any other.

    A long 50 x 1,000,000 units priced on entity R1 and a short notional-only 50m
    on R1: d = 50m each, one entity, EN = 50m - 50m = 0, so AddOn = 0 and (MtM 0)
    EAD = 0. Pre-fix the short leg was priced at zero, leaving the long alone:
    1.4 x 0.32 x 50m = 22,400,000. The fall is the rule's, not a fallback's — the
    short trade is reported CCR035 so its notional reading can be checked.
    """
    # Arrange
    trades = [
        {
            "trade_id": "A",
            "asset_class": "equity",
            "notional": 0.0,
            "reference_entity": "R1",
            "is_index": False,
            "market_price": 50.0,
            "number_of_units": 1_000_000.0,
            "is_long": True,
        },
        {
            "trade_id": "B",
            "asset_class": "equity",
            "notional": 50e6,
            "reference_entity": "R1",
            "is_index": False,
            "is_long": False,
        },
    ]

    # Act
    row, errors = _run(regime, trades, _WITH_USD)

    # Assert
    assert row["ead_final"] == pytest.approx(0.0, abs=1e-6)
    assert [e.message.count("trade 'B'") for e in errors if e.code == "CCR035"] == [1]


#: asset -> (5-year notional-only trade, expected EAD = 1.4 x SF x |notional|).
_MULTI_YEAR_LIMB: dict[str, tuple[dict[str, Any], float]] = {
    "equity": (
        {"asset_class": "equity", "notional": 50e6, "reference_entity": "R1", "is_index": False},
        22_400_000.0,
    ),
    "commodity": (
        {"asset_class": "commodity", "notional": 10e6, "commodity_type": "OIL_GAS"},
        2_520_000.0,
    ),
}

#: The 5-year long's price x units: exactly what a limb of
#: |notional| x max(1, SD(S, E)) would give the 5-year short 50m on the CRR dates
#: (SD(0.04, 4.9993) = 4.38349), so that shape would offset the long completely.
_LONG_5Y_PRICE = 219.17456213563645
_LONG_5Y_UNITS = 1_000_000.0


@pytest.mark.parametrize("regime", _REGIMES)
@pytest.mark.parametrize("asset", list(_MULTI_YEAR_LIMB))
def test_multi_year_notional_limb_is_the_notional_not_a_duration_scaled_one(
    asset: str, regime: str
) -> None:
    """Art. 279b(1)(c)'s notional limb is |notional| at any residual maturity.

    Unlike Art. 279b(1)(a) (interest rate, credit) and the other-risks shape
    ``|notional| x max(1, SD(S, E))`` (``engine/ccr/risk_categories.py``), the
    equity / commodity limb carries no supervisory duration: "use the notional
    amount of the transaction ... as the adjusted notional amount". At one year
    SD is about 0.93, so max(1, SD) = 1 and a duration-scaled limb is invisible;
    at five years SD is about 4.38. MF stays 1 (residual maturity >= 1 year).
    Hand calculation: equity 1.4 x 0.32 x 50m = 22,400,000; commodity OIL_GAS
    1.4 x 0.18 x 10m = 2,520,000. A duration-scaled limb gives about 98.2m and
    11.0m. Pre-fix both gave 0.0.
    """
    # Arrange
    reporting_date = _DATES[regime][0]
    trade, expected_ead = _MULTI_YEAR_LIMB[asset]
    trade = {**trade, "maturity_date": reporting_date.replace(year=reporting_date.year + 5)}

    # Act
    row, errors = _run(regime, trade, _WITH_USD)

    # Assert
    assert row["ead_final"] == pytest.approx(expected_ead, rel=1e-9)
    assert [e.message.count("trade 'T1'") for e in errors if e.code == "CCR035"] == [1]


@pytest.mark.parametrize("regime", _REGIMES)
def test_multi_year_equity_notional_limb_offsets_only_its_notional(regime: str) -> None:
    """A 5-year short notional-only 50m on R1 offsets 50m of a long on R1, no more.

    Long A: 219.17456213563645 x 1,000,000 units = 219,174,562.14 on R1; short B:
    notional-only 50m on R1; both 5-year (MF 1), MtM 0. One entity:
    EN = 219,174,562.14 - 50m = 169,174,562.14, AddOn = 0.32 x EN, so
    EAD = 1.4 x 0.32 x 169,174,562.14 = 75,790,203.84 in both regimes. A limb of
    |notional| x max(1, SD) prices B at 219,174,562.14 on the CRR dates and the
    book at EAD 0.00 — capital understated in full. Pre-fix B was priced at zero:
    EAD 1.4 x 0.32 x 219,174,562.14 = 98,190,203.84.
    """
    # Arrange
    reporting_date = _DATES[regime][0]
    maturity = reporting_date.replace(year=reporting_date.year + 5)
    trades = [
        {
            "trade_id": "A",
            "asset_class": "equity",
            "notional": 0.0,
            "reference_entity": "R1",
            "is_index": False,
            "market_price": _LONG_5Y_PRICE,
            "number_of_units": _LONG_5Y_UNITS,
            "is_long": True,
            "maturity_date": maturity,
        },
        {
            "trade_id": "B",
            "asset_class": "equity",
            "notional": 50e6,
            "reference_entity": "R1",
            "is_index": False,
            "is_long": False,
            "maturity_date": maturity,
        },
    ]

    # Act
    row, errors = _run(regime, trades, _WITH_USD)

    # Assert
    assert row["ead_final"] == pytest.approx(75_790_203.84, abs=0.01)
    assert [e.message.count("trade 'B'") for e in errors if e.code == "CCR035"] == [1]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _config(regime: str) -> CalculationConfig:
    factory = CalculationConfig.crr if regime == "crr" else CalculationConfig.basel_3_1
    return factory(reporting_date=_DATES[regime][0], permission_mode=PermissionMode.STANDARDISED)


def _bundle(
    regime: str,
    trades: list[dict[str, Any]],
    rates: list[tuple[str, float]] | None,
    drop: tuple[str, ...] = (),
) -> RawDataBundle:
    start, maturity = _DATES[regime]
    counterparty = pl.DataFrame(
        [
            {
                "counterparty_reference": "CP-FIN",
                "counterparty_name": "Financial counterparty",
                "entity_type": "institution",
                "country_code": "GB",
                "default_status": False,
                "counterparty_type": "financial",
            }
        ],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    trade_frame = create_trades(
        [
            make_trade(
                **{
                    "trade_id": "T1",
                    "netting_set_id": "NS1",
                    "start_date": start,
                    "maturity_date": maturity,
                    **trade,
                }
            )
            for trade in trades
        ]
    ).drop(*drop)
    assert not set(drop) & set(trade_frame.columns)
    netting_sets = create_netting_sets(
        [
            make_netting_set(
                netting_set_id="NS1", counterparty_reference="CP-FIN", is_legally_enforceable=True
            )
        ]
    )
    fx_rates = (
        None
        if rates is None
        else pl.LazyFrame(
            [{"currency_from": ccy, "currency_to": "GBP", "rate": rate} for ccy, rate in rates],
            schema=dtypes_of(FX_RATES_SCHEMA),
        )
    )
    return make_raw_bundle(
        counterparties=counterparty.lazy(),
        fx_rates=fx_rates,
        ccr=RawCCRBundle(
            trades=TradeBundle(trades=trade_frame.lazy()),
            netting_sets=NettingSetBundle(netting_sets=netting_sets.lazy()),
            margin_agreements=MarginAgreementBundle(
                margin_agreements=create_margin_agreements([]).lazy()
            ),
            ccr_collateral=CCRCollateralBundle(
                ccr_collateral=pl.LazyFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))
            ),
        ),
    )


def _run(
    regime: str,
    trades: dict[str, Any] | list[dict[str, Any]],
    rates: list[tuple[str, float]] | None,
    drop: tuple[str, ...] = (),
) -> tuple[dict[str, Any], list[Any]]:
    """Run one netting set ``NS1`` of ``trades`` (one dict, or several) through the pipeline.

    ``drop`` names trade columns the frame genuinely omits (not typed nulls).
    """
    trade_list = [trades] if isinstance(trades, dict) else trades
    result = PipelineOrchestrator().run_with_data(
        _bundle(regime, trade_list, rates, drop), _config(regime)
    )
    rows = result.results.collect().filter(pl.col("exposure_reference") == "ccr__NS1").to_dicts()
    assert len(rows) == 1, f"expected one ccr__NS1 row, got {len(rows)}"
    return rows[0], result.errors
