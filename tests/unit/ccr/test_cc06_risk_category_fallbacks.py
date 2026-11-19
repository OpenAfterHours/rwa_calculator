"""
Review CC-06 (unit): SA-CCR inputs never contribute a silent zero add-on.

Pipeline position:
    engine/ccr/risk_categories.py (map_trade_risk_categories,
    compute_adjusted_notional_other, compute_addon_other) and the matching input
    gate contracts/ccr_input_checks.py (CCR021 / CCR022 / CCR023)

Key responsibilities:
- Pin the case-insensitive mapping of asset_class / credit_quality /
  commodity_type and the conservative fallbacks for missing or unrecognised
  values (highest supervisory factor of the table; other-risks category).
- Pin the Art. 280f other-risks add-on and the Art. 279b(1)(d) adjusted notional.
- Pin that the input gate flags EXACTLY the trades the engine applies a fallback
  to (one corpus, both predicates) — B3: the two must not drift apart.
- Pin the recognised-value sets in data/schemas.py to the pack tables, and the
  pack table defaults to the factor the fallback actually applies.

Rule text (CRR / CCR (CRR) Part, unchanged by PS1/26):
- Art. 277(1): "Institutions shall map each transaction of a netting set to one
  of the following risk categories ...: (a) interest rate risk; (b) foreign
  exchange risk; (c) credit risk; (d) equity risk; (e) commodity risk; (f) other
  risks."
- Art. 278(1): the add-on of a risk category is included "where at least one
  transaction of the netting set has been mapped to that risk category".
- Art. 279b(1)(d): other risks — "the most appropriate method among the methods
  set out in points (a), (b) and (c)".
- Art. 280f(2): "SF Other = the supervisory factor for the other risk category
  with a value equal to 8%".

Defect pinned: a null / 'BBB' credit_quality, a null commodity_type, and an
asset_class of 'Interest_Rate' or 'inflation' each produced add-on 0 with no
error; DQ006 is case-insensitive, so 'Interest_Rate' passed the gate as well.
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
from rwa_calc.contracts.ccr_input_checks import ccr_trade_errors, ccr_trade_findings
from rwa_calc.data.schemas import (
    VALID_SA_CCR_COMMODITY_TYPES,
    VALID_SA_CCR_CREDIT_QUALITIES,
)
from rwa_calc.engine.ccr.risk_categories import (
    compute_addon_other,
    compute_adjusted_notional_other,
    map_trade_risk_categories,
)
from rwa_calc.rulebook.resolve import resolve
from tests.fixtures.raw_bundle import make_raw_bundle

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))


def _trades(rows: list[dict]) -> pl.LazyFrame:
    base = {
        "netting_set_id": "NS1",
        "transaction_type": "derivative",
        "asset_class": "interest_rate",
        "credit_quality": None,
        "commodity_type": None,
        "is_index": None,
    }
    return pl.LazyFrame(
        [{**base, **row} for row in rows],
        schema_overrides={
            "credit_quality": pl.String,
            "commodity_type": pl.String,
            "is_index": pl.Boolean,
            "asset_class": pl.String,
        },
    )


def _mapped(rows: list[dict]) -> dict[str, dict]:
    out = map_trade_risk_categories(_trades(rows)).collect()
    return {row["trade_id"]: row for row in out.to_dicts()}


# ---------------------------------------------------------------------------
# map_trade_risk_categories
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("interest_rate", "interest_rate"),
        ("Interest_Rate", "interest_rate"),
        ("  FX ", "fx"),
        ("OTHER", "other"),
        ("weather", "other"),
        ("inflation", "other"),
        (None, "other"),
    ],
)
def test_asset_class_is_case_folded_and_unknowns_map_to_other(
    raw: str | None, expected: str
) -> None:
    """Art. 277(1): every trade lands in one of the six categories; unknown -> (f) other."""
    # Arrange / Act
    row = _mapped([{"trade_id": "T", "asset_class": raw}])["T"]

    # Assert
    assert row["asset_class"] == expected


@pytest.mark.parametrize(
    ("quality", "is_index", "expected"),
    [
        ("IG", False, "IG"),
        ("ig", None, "IG"),
        ("NON_RATED", True, "NON_RATED"),
        (None, False, "NON_RATED"),
        ("BBB", None, "NON_RATED"),
        (None, True, "HY"),
        ("AAA", True, "HY"),
    ],
)
def test_credit_quality_fallback_is_the_highest_factor_of_its_table(
    quality: str | None, is_index: bool | None, expected: str
) -> None:
    """Missing / unknown quality: single name -> NON_RATED (6%), index -> HY (1.06%)."""
    # Arrange / Act
    row = _mapped(
        [
            {
                "trade_id": "C",
                "asset_class": "credit",
                "credit_quality": quality,
                "is_index": is_index,
            }
        ]
    )["C"]

    # Assert
    assert row["credit_quality"] == expected


@pytest.mark.parametrize(
    ("commodity_type", "expected"),
    [("OIL_GAS", "OIL_GAS"), ("metals", "METALS"), (None, "ELECTRICITY"), ("GOLD", "ELECTRICITY")],
)
def test_commodity_type_fallback_is_the_highest_factor_hedging_set(
    commodity_type: str | None, expected: str
) -> None:
    """Missing / unknown commodity_type -> the 40% ELECTRICITY hedging set."""
    # Arrange / Act
    row = _mapped(
        [{"trade_id": "K", "asset_class": "commodity", "commodity_type": commodity_type}]
    )["K"]

    # Assert
    assert row["commodity_type"] == expected


def test_fallbacks_touch_only_their_own_risk_category() -> None:
    """An IR trade keeps its null credit_quality / commodity_type (no spurious fill)."""
    # Arrange / Act
    row = _mapped([{"trade_id": "I", "asset_class": "interest_rate"}])["I"]

    # Assert
    assert row["credit_quality"] is None
    assert row["commodity_type"] is None


# ---------------------------------------------------------------------------
# Other-risks category (Art. 279b(1)(d), Art. 280f)
# ---------------------------------------------------------------------------


def test_other_adjusted_notional_prefers_unit_price_then_duration_scaled_notional() -> None:
    """(c) |price × units| when both given; else |notional| × max(1, SD(S, E)).

    Reporting 2026-03-31, 5y maturity: E = 1826/365.25, SD = 4.383491 (> 1), so the
    notional-based amount is 10m × 4.383491 = 43,834,912.43.
    """
    # Arrange
    reporting = date(2026, 3, 31)
    frame = pl.LazyFrame(
        [
            {
                "trade_id": "U",
                "asset_class": "other",
                "notional": 10_000_000.0,
                "market_price": 50.0,
                "number_of_units": -1_000.0,
                "start_date": reporting,
                "maturity_date": date(2031, 3, 31),
                "adjusted_notional": None,
            },
            {
                "trade_id": "N",
                "asset_class": "other",
                "notional": -10_000_000.0,
                "market_price": None,
                "number_of_units": None,
                "start_date": reporting,
                "maturity_date": date(2031, 3, 31),
                "adjusted_notional": None,
            },
            {
                "trade_id": "I",
                "asset_class": "interest_rate",
                "notional": 1.0,
                "market_price": None,
                "number_of_units": None,
                "start_date": reporting,
                "maturity_date": date(2031, 3, 31),
                "adjusted_notional": 123.0,
            },
        ],
        schema_overrides={
            "adjusted_notional": pl.Float64,
            "market_price": pl.Float64,
            "number_of_units": pl.Float64,
        },
    )

    # Act
    out = {
        r["trade_id"]: r
        for r in compute_adjusted_notional_other(frame, reporting).collect().to_dicts()
    }

    # Assert
    assert out["U"]["adjusted_notional"] == pytest.approx(50_000.0)
    assert out["N"]["adjusted_notional"] == pytest.approx(43_834_912.427, rel=1e-9)
    assert out["I"]["adjusted_notional"] == 123.0


def test_other_adjusted_notional_never_falls_below_the_notional() -> None:
    """A short trade's SD < 1, so method (c)'s |notional| (10m) wins over 10m × SD.

    Reporting 2026-03-31, maturity 2026-09-30: E = 183/365.25 = 0.501027,
    SD = (e^(-0.05 × 0.04) - e^(-0.05 × E)) / 0.05 = 0.454843 — the duration-scaled
    amount would be 4,548,430.52; the adjusted notional is 10,000,000.
    """
    # Arrange
    reporting = date(2026, 3, 31)
    frame = pl.LazyFrame(
        [
            {
                "trade_id": "S",
                "asset_class": "other",
                "notional": 10_000_000.0,
                "market_price": None,
                "number_of_units": None,
                "start_date": reporting,
                "maturity_date": date(2026, 9, 30),
                "adjusted_notional": None,
            }
        ],
        schema_overrides={
            "adjusted_notional": pl.Float64,
            "market_price": pl.Float64,
            "number_of_units": pl.Float64,
        },
    )

    # Act
    out = compute_adjusted_notional_other(frame, reporting).collect()

    # Assert
    assert out["adjusted_notional"][0] == pytest.approx(10_000_000.0, rel=1e-12), (
        "the max(1, SD) floor did not apply: a 6-month other-risks trade was "
        "scaled down by its supervisory duration"
    )


def test_other_add_on_nets_only_identical_risk_drivers() -> None:
    """Art. 277a(1)(f) / 280f: same underlying nets; unknown driver is its own set.

    R1 long 1m + R1 short 1m -> 0; trade X (no underlying) 1m -> 8% × 1m;
    trade Y (no underlying) -2m -> 8% × 2m. AddOn_Other = 80,000 + 160,000.
    """
    # Arrange
    frame = pl.LazyFrame(
        [
            {
                "trade_id": "A",
                "underlying_reference": "R1",
                "supervisory_delta": 1.0,
                "adjusted_notional": 1e6,
            },
            {
                "trade_id": "B",
                "underlying_reference": "R1",
                "supervisory_delta": -1.0,
                "adjusted_notional": 1e6,
            },
            {
                "trade_id": "X",
                "underlying_reference": None,
                "supervisory_delta": 1.0,
                "adjusted_notional": 1e6,
            },
            {
                "trade_id": "Y",
                "underlying_reference": None,
                "supervisory_delta": -1.0,
                "adjusted_notional": 2e6,
            },
        ],
        schema_overrides={"underlying_reference": pl.String},
    ).with_columns(
        pl.lit("NS1").alias("netting_set_id"),
        pl.lit("other").alias("asset_class"),
        pl.lit(1.0).alias("maturity_factor"),
    )

    # Act
    addon = compute_addon_other(frame).collect()["asset_class_addon"][0]

    # Assert
    assert addon == pytest.approx(0.08 * 1e6 + 0.08 * 2e6, rel=1e-12)


# ---------------------------------------------------------------------------
# Pack / schema parity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pack", [_CRR_PACK, _B31_PACK], ids=["crr", "b31"])
def test_recognised_value_sets_equal_the_pack_tables(pack) -> None:
    """The input gate's sets are the engine's (pack) keys — they cannot drift apart."""
    # Arrange
    credit = set(pack.lookup("sa_ccr_supervisory_factors_credit_sn").entries) | set(
        pack.lookup("sa_ccr_supervisory_factors_credit_idx").entries
    )
    commodity = set(pack.lookup("sa_ccr_supervisory_factors_commodity").entries)

    # Assert
    assert credit == VALID_SA_CCR_CREDIT_QUALITIES
    assert commodity == VALID_SA_CCR_COMMODITY_TYPES
    assert float(pack.scalar("sa_ccr_supervisory_factor_other")) == 0.08


@pytest.mark.parametrize(
    "table",
    [
        "sa_ccr_supervisory_factors_credit_sn",
        "sa_ccr_supervisory_factors_credit_idx",
        "sa_ccr_supervisory_factors_commodity",
    ],
)
def test_pack_default_states_the_fallback_factor_applied(table: str) -> None:
    """Each table's published default is its highest factor — the CCR022 fallback."""
    # Arrange
    lookup = _CRR_PACK.lookup(table)

    # Assert
    assert lookup.default == max(lookup.entries.values())


# ---------------------------------------------------------------------------
# Input gate (CCR021 / CCR022 / CCR023) and its parity with the engine
# ---------------------------------------------------------------------------

_CORPUS = [
    {"trade_id": "T01", "asset_class": "interest_rate"},
    {"trade_id": "T02", "asset_class": "Interest_Rate"},
    {"trade_id": "T03", "asset_class": "weather"},
    {"trade_id": "T04", "asset_class": None},
    {"trade_id": "T05", "asset_class": "other"},
    {"trade_id": "T06", "asset_class": "credit", "credit_quality": "IG"},
    {"trade_id": "T07", "asset_class": "credit", "credit_quality": "ig"},
    {"trade_id": "T08", "asset_class": "credit", "credit_quality": None},
    {"trade_id": "T09", "asset_class": "CREDIT", "credit_quality": "BBB"},
    {"trade_id": "T10", "asset_class": "commodity", "commodity_type": "OIL_GAS"},
    {"trade_id": "T11", "asset_class": "commodity", "commodity_type": None},
    {"trade_id": "T12", "asset_class": "commodity", "commodity_type": "gold"},
    {"trade_id": "T13", "asset_class": "fx", "netting_set_id": "NS-MISSING"},
    {"trade_id": "T14", "asset_class": "weather", "transaction_type": "sft"},
]


def _gate_bundle():
    trades = _trades(_CORPUS)
    netting_sets = pl.LazyFrame([{"netting_set_id": "NS1", "counterparty_reference": "CP1"}])
    return make_raw_bundle(
        ccr=RawCCRBundle(
            trades=TradeBundle(trades=trades),
            netting_sets=NettingSetBundle(netting_sets=netting_sets),
            margin_agreements=MarginAgreementBundle(margin_agreements=pl.LazyFrame()),
            ccr_collateral=CCRCollateralBundle(ccr_collateral=pl.LazyFrame()),
        )
    )


def _gate_errors():
    bundle = _gate_bundle()
    assert bundle.ccr is not None
    columns = frozenset(bundle.ccr.trades.trades.collect_schema().names())
    findings = ccr_trade_findings(bundle, columns)
    assert findings is not None
    return ccr_trade_errors(findings.collect())


def _flagged(code: str, field: str) -> set[str]:
    return {
        e.message.split("trade '")[1].split("'")[0]
        for e in _gate_errors()
        if e.code == code and e.field_name == field
    }


def test_gate_flags_each_fallback_with_its_code() -> None:
    """CCR021 unknown category, CCR022 quality / type, CCR023 orphan; SFT rows skipped."""
    # Assert
    assert _flagged("CCR021", "asset_class") == {"T03", "T04"}
    assert _flagged("CCR022", "credit_quality") == {"T08", "T09"}
    assert _flagged("CCR022", "commodity_type") == {"T11", "T12"}
    assert _flagged("CCR023", "netting_set_id") == {"T13"}
    assert all(e.severity.value == "error" for e in _gate_errors())


def test_gate_flags_exactly_the_trades_the_engine_falls_back_on() -> None:
    """Parity: a trade is flagged iff the engine's mapped value differs from its folded input."""
    # Arrange — the engine's view of the same derivative trades
    derivative = [row for row in _CORPUS if row.get("transaction_type") != "sft"]
    engine = _mapped(derivative)

    def folded(value: str | None, upper: bool) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value.upper() if upper else value.lower()

    # Act — trades whose risk input the engine replaced with a fallback
    category_fallback = {
        t
        for t, row in engine.items()
        if folded(next(r for r in derivative if r["trade_id"] == t)["asset_class"], False)
        != row["asset_class"]
    }
    credit_fallback = {
        t
        for t, row in engine.items()
        if row["asset_class"] == "credit"
        and t not in category_fallback
        and folded(next(r for r in derivative if r["trade_id"] == t).get("credit_quality"), True)
        != row["credit_quality"]
    }
    commodity_fallback = {
        t
        for t, row in engine.items()
        if row["asset_class"] == "commodity"
        and t not in category_fallback
        and folded(next(r for r in derivative if r["trade_id"] == t).get("commodity_type"), True)
        != row["commodity_type"]
    }

    # Assert
    assert category_fallback == _flagged("CCR021", "asset_class")
    assert credit_fallback == _flagged("CCR022", "credit_quality")
    assert commodity_fallback == _flagged("CCR022", "commodity_type")


def test_gate_samples_and_summarises_beyond_the_cap() -> None:
    """Seven bad rows, cap 5: five row-named errors plus one summary naming 2 omitted."""
    # Arrange
    findings = pl.DataFrame(
        {
            "trade_id": [f"T{i}" for i in range(7)],
            "netting_set_id": ["NS1"] * 7,
            "counterparty_reference": ["CP1"] * 7,
            "asset_class": ["weather"] * 7,
            "credit_quality": [None] * 7,
            "commodity_type": [None] * 7,
            "_unrecognised_category": [True] * 7,
            "_unrecognised_credit_quality": [False] * 7,
            "_unrecognised_commodity_type": [False] * 7,
            "_orphan": [False] * 7,
        },
        schema_overrides={"credit_quality": pl.String, "commodity_type": pl.String},
    )

    # Act
    errors = ccr_trade_errors(findings, sample_cap=5)

    # Assert
    assert len(errors) == 6
    assert "2 additional trade(s)" in errors[-1].message
