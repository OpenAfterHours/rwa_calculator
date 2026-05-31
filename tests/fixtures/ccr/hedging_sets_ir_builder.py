"""
P8.15 fixture builder: IR hedging-set partition + asset-class add-on scenario.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_p8_15_hedging_sets_ir.py)
    -> engine-implementer (src/rwa_calc/engine/ccr/hedging_sets.py + pfe.py)

Scenario design:
    Two IR-GBP derivative trades in one netting set (NS-IR-01), counterparty CP_IR.
    The pair is chosen to exercise BOTH non-adjacent maturity buckets in a single
    netting set so that the engine's cross-bucket correlation formula (Art. 277a(1))
    is exercised with a known analytic result:

    T1 (trade_id="T1"): 10-year GBP IR swap, notional GBP 100m, delta=+1.0,
        is_long=True, MtM=0.  Bucket: GT_5Y (maturity > 5 years).
    T2 (trade_id="T2"): 3-year GBP IR swap, notional GBP 50m, delta=-1.0,
        is_long=False, MtM=0.  Bucket: 1Y_5Y (1 year <= maturity <= 5 years).

    Netting set NS-IR-01: counterparty CP_IR, legally enforceable (Art. 295),
    unmargined (is_margined=False).  No margin agreements, no CCR collateral.

Key fixture invariants (checked in save_p815_fixtures smoke-test):
    1. Two trade rows in the trades LazyFrame.
    2. One netting-set row in the netting_sets LazyFrame.
    3. T1 asset_class == "interest_rate", currency == "GBP", is_long == True.
    4. T2 asset_class == "interest_rate", currency == "GBP", is_long == False.
    5. T1 maturity tenor > 5 years from start (GT_5Y bucket expected by engine).
    6. T2 maturity tenor in [1, 5] years from start (1Y_5Y bucket expected by engine).
    7. Both trades belong to netting set NS-IR-01.
    8. Netting set NS-IR-01 is unmargined and legally enforceable.

This module is Python-only: no parquet files are written.  The test-writer
imports ``make_p815_trades()`` and ``make_p815_netting_sets()`` directly.
Zero-row margin-agreement and CCR-collateral frames are also available via
``make_p815_margin_agreements()`` and ``make_p815_collateral()`` for tests that
need to assemble a full four-frame CCR input bundle.

Exported public names
---------------------
    P815_NETTING_SET_ID     : str — "NS-IR-01"
    P815_COUNTERPARTY_REF   : str — "CP_IR"
    P815_TRADE_ID_T1        : str — "T1"
    P815_TRADE_ID_T2        : str — "T2"
    P815_NOTIONAL_T1        : float — 100_000_000.0
    P815_NOTIONAL_T2        : float — 50_000_000.0
    P815_ASSET_CLASS        : str — "interest_rate"
    P815_CURRENCY           : str — "GBP"
    P815_START_DATE         : date — 2026-05-23
    P815_MATURITY_T1        : date — 2036-05-23 (10-year, GT_5Y bucket)
    P815_MATURITY_T2        : date — 2029-05-23 (3-year, 1Y_5Y bucket)

    make_p815_trades()        -> pl.LazyFrame  (2 rows, TRADE_SCHEMA)
    make_p815_netting_sets()  -> pl.LazyFrame  (1 row, NETTING_SET_SCHEMA)

References:
    - CRR Art. 277(1)   — hedging-set definition by currency within IR asset class
    - CRR Art. 277(2)   — IR maturity bucket thresholds: LT_1Y / 1Y_5Y / GT_5Y
    - CRR Art. 277a(1)  — intra-asset-class add-on aggregation formula
    - CRR Art. 280a     — IR supervisory parameters (SF = 0.5%, correlation ρ = 0.7)
    - CRR Art. 279b     — adjusted notional for IR trades (SD function)
    - CRR Art. 295      — legal enforceability of netting agreement
    - src/rwa_calc/data/schemas.py — TRADE_SCHEMA, NETTING_SET_SCHEMA
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import CCR_COLLATERAL_SCHEMA

from .margin_builder import create_margin_agreements
from .netting_set_builder import NettingSet, create_netting_sets
from .trade_builder import Trade, create_trades

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

P815_NETTING_SET_ID: str = "NS-IR-01"
P815_COUNTERPARTY_REF: str = "CP_IR"

P815_TRADE_ID_T1: str = "T1"
P815_TRADE_ID_T2: str = "T2"

P815_ASSET_CLASS: str = "interest_rate"
P815_CURRENCY: str = "GBP"

# Calculation date used as start_date for both trades (trade date = today).
P815_START_DATE: date = date(2026, 5, 23)

# T1 matures 10 years from start → maturity > 5 years → GT_5Y bucket (Art. 277(2)(c)).
P815_MATURITY_T1: date = date(2036, 5, 23)

# T2 matures 3 years from start → 1 ≤ maturity ≤ 5 years → 1Y_5Y bucket (Art. 277(2)(b)).
P815_MATURITY_T2: date = date(2029, 5, 23)

P815_NOTIONAL_T1: float = 100_000_000.0  # GBP 100m
P815_NOTIONAL_T2: float = 50_000_000.0  # GBP 50m

# Supervisory delta: +1 (payer/long) for T1, -1 (receiver/short) for T2.
# CRR Art. 279a(1): non-option directional trades use ±1.
P815_DELTA_T1: float = 1.0
P815_DELTA_T2: float = -1.0

P815_IS_LONG_T1: bool = True  # long position → effective notional positive
P815_IS_LONG_T2: bool = False  # short position → effective notional negative

P815_MTM: float = 0.0  # both trades at-par

# Netting-set flags.
P815_IS_LEGALLY_ENFORCEABLE: bool = True  # Art. 295 condition met
P815_IS_MARGINED: bool = False  # unmargined → MF from Art. 279c(a) formula


# ---------------------------------------------------------------------------
# Trade builders
# ---------------------------------------------------------------------------


def _t1() -> Trade:
    """10-year GBP IR swap, long, delta=+1 — maps to GT_5Y maturity bucket."""
    return Trade(
        trade_id=P815_TRADE_ID_T1,
        netting_set_id=P815_NETTING_SET_ID,
        asset_class=P815_ASSET_CLASS,
        transaction_type="derivative",
        notional=P815_NOTIONAL_T1,
        currency=P815_CURRENCY,
        maturity_date=P815_MATURITY_T1,
        start_date=P815_START_DATE,
        delta=P815_DELTA_T1,
        is_long=P815_IS_LONG_T1,
        mtm_value=P815_MTM,
    )


def _t2() -> Trade:
    """3-year GBP IR swap, short, delta=-1 — maps to 1Y_5Y maturity bucket."""
    return Trade(
        trade_id=P815_TRADE_ID_T2,
        netting_set_id=P815_NETTING_SET_ID,
        asset_class=P815_ASSET_CLASS,
        transaction_type="derivative",
        notional=P815_NOTIONAL_T2,
        currency=P815_CURRENCY,
        maturity_date=P815_MATURITY_T2,
        start_date=P815_START_DATE,
        delta=P815_DELTA_T2,
        is_long=P815_IS_LONG_T2,
        mtm_value=P815_MTM,
    )


# ---------------------------------------------------------------------------
# Public LazyFrame factories
# ---------------------------------------------------------------------------


def make_p815_trades() -> pl.LazyFrame:
    """
    Return the 2-trade LazyFrame for the P8.15 IR hedging-set scenario.

    Both trades share netting set NS-IR-01 and asset class "interest_rate" (GBP).
    T1 (10y) falls in the GT_5Y maturity bucket; T2 (3y) falls in 1Y_5Y.
    Schema is enforced via TRADE_SCHEMA column specs.

    Returns:
        LazyFrame with 2 rows, columns matching TRADE_SCHEMA.
    """
    return create_trades([_t1(), _t2()]).lazy()


def make_p815_netting_sets() -> pl.LazyFrame:
    """
    Return the 1-netting-set LazyFrame for the P8.15 scenario.

    NS-IR-01 is legally enforceable (Art. 295) and unmargined.
    Schema is enforced via NETTING_SET_SCHEMA column specs.

    Returns:
        LazyFrame with 1 row, columns matching NETTING_SET_SCHEMA.
    """
    ns = NettingSet(
        netting_set_id=P815_NETTING_SET_ID,
        counterparty_reference=P815_COUNTERPARTY_REF,
        is_legally_enforceable=P815_IS_LEGALLY_ENFORCEABLE,
        is_margined=P815_IS_MARGINED,
    )
    return create_netting_sets([ns]).lazy()


def make_p815_margin_agreements() -> pl.LazyFrame:
    """Return a zero-row margin-agreements LazyFrame (P8.15: unmargined, no CSA)."""
    return create_margin_agreements([]).lazy()


def make_p815_collateral() -> pl.LazyFrame:
    """Return a zero-row CCR-collateral LazyFrame (P8.15: no posted/received collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA)).lazy()


# ---------------------------------------------------------------------------
# Smoke-check entry point — called by generate_all.py
# ---------------------------------------------------------------------------


def save_p815_fixtures() -> list[tuple[str, int]]:
    """
    Smoke-check all four P8.15 LazyFrames and return a generation report.

    No parquet files are written — this fixture is Python-only.  The function
    validates the invariants listed in the module docstring and raises
    ``AssertionError`` with a descriptive message if any is violated.

    Returns:
        A single-element list suitable for ``generate_all.py``'s report format:
        ``[("(python-only builder — no parquet)", 0)]``.

    Raises:
        AssertionError: If any schema or data invariant is violated.
    """
    trades_df = make_p815_trades().collect()
    ns_df = make_p815_netting_sets().collect()
    _ = make_p815_margin_agreements().collect()
    _ = make_p815_collateral().collect()

    _check_row_counts(trades_df, ns_df)  # Invariants 1 & 2
    _check_trade_asset_class_and_currency(trades_df)  # Invariants 3 & 4

    t1_row = trades_df.filter(pl.col("trade_id") == P815_TRADE_ID_T1)
    t2_row = trades_df.filter(pl.col("trade_id") == P815_TRADE_ID_T2)

    _check_trade_directions(t1_row, t2_row)  # Invariants 3 & 4 (is_long)
    _check_maturity_buckets()  # Invariants 5 & 6
    _check_trade_netting_set_membership(t1_row, t2_row)  # Invariant 7
    _check_netting_set_flags(ns_df)  # Invariant 8

    return [("(python-only builder — no parquet)", 0)]


def _check_row_counts(trades_df: pl.DataFrame, ns_df: pl.DataFrame) -> None:
    """Invariants 1 & 2: two trade rows and one netting-set row."""
    if trades_df.height != 2:
        raise AssertionError(f"Expected 2 trade rows, got {trades_df.height}")
    if ns_df.height != 1:
        raise AssertionError(f"Expected 1 netting-set row, got {ns_df.height}")


def _check_trade_asset_class_and_currency(trades_df: pl.DataFrame) -> None:
    """Invariants 3 & 4: asset class and currency for each trade."""
    for tid in (P815_TRADE_ID_T1, P815_TRADE_ID_T2):
        row = trades_df.filter(pl.col("trade_id") == tid)
        if row.height != 1:
            raise AssertionError(f"Trade {tid!r} not found in trades frame")
        ac = row["asset_class"][0]
        if ac != P815_ASSET_CLASS:
            raise AssertionError(
                f"Trade {tid!r}: asset_class must be {P815_ASSET_CLASS!r} (got {ac!r})"
            )
        ccy = row["currency"][0]
        if ccy != P815_CURRENCY:
            raise AssertionError(f"Trade {tid!r}: currency must be {P815_CURRENCY!r} (got {ccy!r})")


def _check_trade_directions(t1_row: pl.DataFrame, t2_row: pl.DataFrame) -> None:
    """Invariants 3 & 4 (is_long): T1 long, T2 short."""
    if t1_row["is_long"][0] is not True:
        raise AssertionError(f"T1 is_long must be True (got {t1_row['is_long'][0]!r})")
    if t2_row["is_long"][0] is not False:
        raise AssertionError(f"T2 is_long must be False (got {t2_row['is_long'][0]!r})")


def _check_maturity_buckets() -> None:
    """Invariants 5 & 6: T1 tenor > 5y (GT_5Y) and T2 tenor in [1, 5]y (1Y_5Y)."""
    t1_tenor_years = (P815_MATURITY_T1 - P815_START_DATE).days / 365.25
    if t1_tenor_years <= 5.0:
        raise AssertionError(
            f"T1 tenor must be > 5 years for GT_5Y bucket (got {t1_tenor_years:.2f}y)"
        )
    t2_tenor_years = (P815_MATURITY_T2 - P815_START_DATE).days / 365.25
    if not (1.0 <= t2_tenor_years <= 5.0):
        raise AssertionError(
            f"T2 tenor must be in [1, 5] years for 1Y_5Y bucket (got {t2_tenor_years:.2f}y)"
        )


def _check_trade_netting_set_membership(t1_row: pl.DataFrame, t2_row: pl.DataFrame) -> None:
    """Invariant 7: both trades belong to NS-IR-01."""
    for tid, row in ((P815_TRADE_ID_T1, t1_row), (P815_TRADE_ID_T2, t2_row)):
        ns_id = row["netting_set_id"][0]
        if ns_id != P815_NETTING_SET_ID:
            raise AssertionError(
                f"Trade {tid!r}: netting_set_id must be {P815_NETTING_SET_ID!r} (got {ns_id!r})"
            )


def _check_netting_set_flags(ns_df: pl.DataFrame) -> None:
    """Invariant 8: NS-IR-01 is unmargined and legally enforceable."""
    if ns_df["is_margined"][0] is not False:
        raise AssertionError(
            f"NS-IR-01 is_margined must be False (got {ns_df['is_margined'][0]!r})"
        )
    if ns_df["is_legally_enforceable"][0] is not True:
        raise AssertionError(
            f"NS-IR-01 is_legally_enforceable must be True "
            f"(got {ns_df['is_legally_enforceable'][0]!r})"
        )
