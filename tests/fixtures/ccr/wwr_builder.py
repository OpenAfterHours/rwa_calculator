"""
P8.27 fixture: wrong-way risk (WWR) identification — specific WWR break-out.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_p8_27_wwr.py)
    -> engine-implementer (src/rwa_calc/engine/ccr/wwr.py)

Scenario design:
    Counterparty CP_WWR_01 issues equity that is the underlying of trade T_WWR_01
    (Art. 291(1)(b) specific WWR condition).  A second trade T_NORMAL_01 is an
    IR derivative in the same netting set with no WWR connection.

    NS_WWR_01: ``is_legally_enforceable=True``, ``is_margined=False``,
    ``has_general_wwr_flag=False`` (Art. 291(1)(a) general WWR not present).

    T_WWR_01 — equity derivative, notional GBP 10m, maturity 2028-01-01,
        mtm=0, delta=+1.0, is_long=True, **is_specific_wwr=True**,
        underlying_reference="CP_WWR_01_EQUITY".  Art. 291(1)(b): the issuer of
        the reference equity is the counterparty → specific WWR.
    T_NORMAL_01 — IR derivative, notional GBP 50m, maturity 2031-01-01,
        mtm=0, delta=+1.0, is_long=True, is_specific_wwr=False.

Expected post-gate netting-set frame (2 rows):
    - NS_WWR_01 (residual)      — contains T_NORMAL_01, wwr_lgd_override=null
    - NS_WWR_01__wwr__T_WWR_01 (synthetic) — contains T_WWR_01,
        wwr_lgd_override=1.0 (Art. 291(5)(c) LGD=100%)

Expected error frame: exactly one CCR010 (severity=WARNING) for NS_WWR_01.
Zero CCR011 (has_general_wwr_flag is False).

``is_specific_wwr`` is appended to the trades frame via ``with_columns`` rather
than declared in TRADE_SCHEMA — the schema extension is engine-implementer
territory.  Similarly ``has_general_wwr_flag`` and ``wwr_lgd_override`` are
appended to the netting-sets frame.

This module is Python-only: no parquet files are written.  The test-writer
imports ``make_p827_trades()``, ``make_p827_netting_sets()``, and the exported
constants directly.

Exported public names
---------------------
    NS_WWR_01_ID                : str — "NS_WWR_01"
    SYNTHETIC_NS_ID             : str — "NS_WWR_01__wwr__T_WWR_01"
    CP_WWR_01_REF               : str — "CP_WWR_01"
    T_WWR_01_ID                 : str — "T_WWR_01"
    T_NORMAL_01_ID              : str — "T_NORMAL_01"
    WWR_LGD_OVERRIDE_VALUE      : float — 1.0
    EXPECTED_CCR010_COUNT       : int — 1
    EXPECTED_CCR011_COUNT       : int — 0
    CCR010_ERROR_CODE           : str — "CCR010"
    CCR011_ERROR_CODE           : str — "CCR011"
    CCR_WWR_SEVERITY            : str — "warning"
    CCR010_REGULATORY_REF       : str — "CRR Art. 291(4)-(5)"
    CCR011_REGULATORY_REF       : str — "CRR Art. 291(1)(a), 291(6)"

    make_p827_trades()          -> pl.LazyFrame (2 rows, TRADE_SCHEMA + is_specific_wwr)
    make_p827_netting_sets()    -> pl.LazyFrame (1 row, NETTING_SET_SCHEMA + WWR cols)
    make_p827_margin_agreements() -> pl.LazyFrame (0 rows)
    make_p827_collateral()      -> pl.LazyFrame (0 rows)
    save_p827_fixtures()        -> list[tuple[str, int]]  (smoke-check entry point)

References:
    - CRR Art. 291(1)(a)/(1)(b)/(4)/(5)(a)/(5)(c)/(6) — WWR definitions and treatment
    - CRR Art. 272(4) — netting set definition
    - CRR Art. 274(2) — netting set membership
    - src/rwa_calc/data/schemas.py — TRADE_SCHEMA, NETTING_SET_SCHEMA
    - src/rwa_calc/domain/enums.py — ErrorSeverity.WARNING (WARNING | ERROR | CRITICAL only)
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

#: Original netting set identifier — pre-break-out.
NS_WWR_01_ID: str = "NS_WWR_01"

#: Counterparty reference (also issues the underlying equity of T_WWR_01).
CP_WWR_01_REF: str = "CP_WWR_01"

#: Synthetic netting set ID produced by the specific-WWR break-out (Art. 291(5)(a)).
#: Format: ``<original_ns_id>__wwr__<trade_id>``.
SYNTHETIC_NS_ID: str = f"{NS_WWR_01_ID}__wwr__T_WWR_01"

# --- Trade: specific WWR equity derivative ---
T_WWR_01_ID: str = "T_WWR_01"
T_WWR_01_ASSET_CLASS: str = "equity"
T_WWR_01_NOTIONAL: float = 10_000_000.0  # GBP 10m
T_WWR_01_MATURITY: date = date(2028, 1, 1)
T_WWR_01_START: date = date(2026, 5, 23)
T_WWR_01_MTM: float = 0.0
T_WWR_01_DELTA: float = 1.0
T_WWR_01_IS_LONG: bool = True
#: Art. 291(1)(b): the underlying equity is issued by the counterparty.
T_WWR_01_UNDERLYING_REF: str = "CP_WWR_01_EQUITY"
#: Specific WWR flag — new column appended via with_columns (not yet in TRADE_SCHEMA).
T_WWR_01_IS_SPECIFIC_WWR: bool = True

# --- Trade: normal IR derivative (no WWR connection) ---
T_NORMAL_01_ID: str = "T_NORMAL_01"
T_NORMAL_01_ASSET_CLASS: str = "interest_rate"
T_NORMAL_01_NOTIONAL: float = 50_000_000.0  # GBP 50m
T_NORMAL_01_MATURITY: date = date(2031, 1, 1)
T_NORMAL_01_START: date = date(2026, 5, 23)
T_NORMAL_01_MTM: float = 0.0
T_NORMAL_01_DELTA: float = 1.0
T_NORMAL_01_IS_LONG: bool = True
T_NORMAL_01_IS_SPECIFIC_WWR: bool = False

# --- Netting-set flags ---
NS_WWR_01_IS_LEGALLY_ENFORCEABLE: bool = True
NS_WWR_01_IS_MARGINED: bool = False
#: has_general_wwr_flag=False → no CCR011 emitted (Art. 291(1)(a) / 291(6)).
NS_WWR_01_HAS_GENERAL_WWR: bool = False

# --- Expected output scalars ---

#: LGD override applied to the synthetic netting set (Art. 291(5)(c): LGD = 100%).
#: Corresponds to ``CCR_WWR_SPECIFIC_LGD_OVERRIDE`` in data/tables/sa_ccr_factors.py.
WWR_LGD_OVERRIDE_VALUE: float = 1.0

#: One CCR010 per original NS containing ≥1 specific-WWR trade.
#: Aggregation key: original ``netting_set_id`` (here NS_WWR_01).
EXPECTED_CCR010_COUNT: int = 1

#: Zero CCR011 because has_general_wwr_flag=False.
EXPECTED_CCR011_COUNT: int = 0

# --- Error record constants ---

#: Error code emitted for each original NS with specific WWR trades (Art. 291(4)-(5)).
CCR010_ERROR_CODE: str = "CCR010"

#: Error code emitted per NS with has_general_wwr_flag=True (Art. 291(1)(a), 291(6)).
CCR011_ERROR_CODE: str = "CCR011"

#: Both CCR010 and CCR011 use WARNING severity (precedent: CCR001 at sa_ccr.py:187).
#: ``ErrorSeverity`` only defines WARNING | ERROR | CRITICAL — no INFO member.
CCR_WWR_SEVERITY: str = "warning"

CCR010_REGULATORY_REF: str = "CRR Art. 291(4)-(5)"
CCR011_REGULATORY_REF: str = "CRR Art. 291(1)(a), 291(6)"


# ---------------------------------------------------------------------------
# Internal trade/NS builders
# ---------------------------------------------------------------------------


def _trade_wwr() -> Trade:
    """Equity derivative on CP_WWR_01-issued equity — is_specific_wwr=True."""
    return Trade(
        trade_id=T_WWR_01_ID,
        netting_set_id=NS_WWR_01_ID,
        asset_class=T_WWR_01_ASSET_CLASS,
        transaction_type="derivative",
        notional=T_WWR_01_NOTIONAL,
        currency="GBP",
        maturity_date=T_WWR_01_MATURITY,
        start_date=T_WWR_01_START,
        delta=T_WWR_01_DELTA,
        is_long=T_WWR_01_IS_LONG,
        mtm_value=T_WWR_01_MTM,
        underlying_reference=T_WWR_01_UNDERLYING_REF,
    )


def _trade_normal() -> Trade:
    """IR derivative with no WWR connection — is_specific_wwr=False."""
    return Trade(
        trade_id=T_NORMAL_01_ID,
        netting_set_id=NS_WWR_01_ID,
        asset_class=T_NORMAL_01_ASSET_CLASS,
        transaction_type="derivative",
        notional=T_NORMAL_01_NOTIONAL,
        currency="GBP",
        maturity_date=T_NORMAL_01_MATURITY,
        start_date=T_NORMAL_01_START,
        delta=T_NORMAL_01_DELTA,
        is_long=T_NORMAL_01_IS_LONG,
        mtm_value=T_NORMAL_01_MTM,
    )


def _netting_set_wwr_01() -> NettingSet:
    """NS_WWR_01: legally enforceable, unmargined, no general WWR flag."""
    return NettingSet(
        netting_set_id=NS_WWR_01_ID,
        counterparty_reference=CP_WWR_01_REF,
        is_legally_enforceable=NS_WWR_01_IS_LEGALLY_ENFORCEABLE,
        is_margined=NS_WWR_01_IS_MARGINED,
    )


# ---------------------------------------------------------------------------
# Public LazyFrame factories
# ---------------------------------------------------------------------------


def make_p827_trades() -> pl.LazyFrame:
    """
    Return the 2-trade LazyFrame for the P8.27 WWR identification scenario.

    The returned frame contains all TRADE_SCHEMA columns plus the new
    ``is_specific_wwr`` column (Bool) appended via ``with_columns``.  This
    append pattern keeps the fixture loadable before the schema extension
    lands in schemas.py (engine-implementer territory).

    Row layout:
        - T_WWR_01:   equity derivative, is_specific_wwr=True
        - T_NORMAL_01: IR derivative,    is_specific_wwr=False

    Returns:
        LazyFrame with 2 rows, columns matching TRADE_SCHEMA + is_specific_wwr.
    """
    base = create_trades([_trade_wwr(), _trade_normal()])
    # Append is_specific_wwr values matching trade order (T_WWR_01 first).
    with_wwr = base.with_columns(
        pl.Series("is_specific_wwr", [T_WWR_01_IS_SPECIFIC_WWR, T_NORMAL_01_IS_SPECIFIC_WWR])
    )
    return with_wwr.lazy()


def make_p827_netting_sets() -> pl.LazyFrame:
    """
    Return the 1-row netting-set LazyFrame for the P8.27 scenario.

    The returned frame contains all NETTING_SET_SCHEMA columns plus two new
    columns appended via ``with_columns``:
        - ``has_general_wwr_flag`` (Bool, default False) — Art. 291(1)(a)/(6)
        - ``wwr_lgd_override``     (Float64, null)       — Art. 291(5)(c)

    The ``wwr_lgd_override`` on NS_WWR_01 is null in the *input* frame; the
    engine's ``apply_wwr_gate`` sets it to 1.0 on the **synthetic** NS row it
    creates.  This fixture represents the pre-gate input — NS_WWR_01 only.

    Returns:
        LazyFrame with 1 row, columns matching NETTING_SET_SCHEMA + WWR cols.
    """
    base = create_netting_sets([_netting_set_wwr_01()])
    with_wwr = base.with_columns(
        pl.lit(NS_WWR_01_HAS_GENERAL_WWR).alias("has_general_wwr_flag"),
        pl.lit(None, dtype=pl.Float64).alias("wwr_lgd_override"),
    )
    return with_wwr.lazy()


def make_p827_margin_agreements() -> pl.LazyFrame:
    """Return a zero-row margin-agreements LazyFrame (P8.27: no CSA — unmargined)."""
    return create_margin_agreements([]).lazy()


def make_p827_collateral() -> pl.LazyFrame:
    """Return a zero-row CCR-collateral LazyFrame (P8.27: no posted/received collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA)).lazy()


# ---------------------------------------------------------------------------
# Smoke-check entry point — called by generate_all.py
# ---------------------------------------------------------------------------


def save_p827_fixtures() -> list[tuple[str, int]]:
    """
    Smoke-check all four P8.27 LazyFrames and return a generation report.

    No parquet files are written — this fixture is Python-only.  The function
    validates the invariants listed below and raises ``AssertionError`` with a
    descriptive message if any is violated.

    Invariants checked:
        1. Trades frame has exactly 2 rows.
        2. T_WWR_01 present with asset_class="equity", is_specific_wwr=True,
           underlying_reference="CP_WWR_01_EQUITY".
        3. T_NORMAL_01 present with asset_class="interest_rate", is_specific_wwr=False.
        4. Both trades belong to NS_WWR_01.
        5. Netting-set frame has exactly 1 row (NS_WWR_01 — pre-gate input).
        6. NS_WWR_01 is legally enforceable, unmargined.
        7. NS_WWR_01 has_general_wwr_flag=False.
        8. NS_WWR_01 wwr_lgd_override is null (pre-gate).
        9. SYNTHETIC_NS_ID is formed as ``NS_WWR_01__wwr__T_WWR_01``.
        10. WWR_LGD_OVERRIDE_VALUE == 1.0.
        11. EXPECTED_CCR010_COUNT == 1, EXPECTED_CCR011_COUNT == 0.

    Returns:
        ``[("(python-only builder — no parquet)", 0)]``

    Raises:
        AssertionError: If any invariant is violated.
    """
    trades_df = make_p827_trades().collect()
    ns_df = make_p827_netting_sets().collect()
    _ = make_p827_margin_agreements().collect()
    _ = make_p827_collateral().collect()

    _check_trade_invariants(trades_df)  # Invariants 1-4
    _check_netting_set_invariants(ns_df)  # Invariants 5-8
    _check_scalar_invariants()  # Invariants 9-11

    return [("(python-only builder — no parquet)", 0)]


def _check_trade_invariants(trades_df: pl.DataFrame) -> None:
    """Validate trade-frame invariants 1-4 (row count, T_WWR_01, T_NORMAL_01, NS membership)."""
    # Invariant 1: exactly 2 trade rows.
    if trades_df.height != 2:
        raise AssertionError(f"P8.27: expected 2 trade rows, got {trades_df.height}")

    # Invariant 2: T_WWR_01 checks.
    wwr_row = trades_df.filter(pl.col("trade_id") == T_WWR_01_ID)
    if wwr_row.height != 1:
        raise AssertionError(f"P8.27: trade {T_WWR_01_ID!r} not found")
    if wwr_row["asset_class"][0] != T_WWR_01_ASSET_CLASS:
        raise AssertionError(
            f"P8.27: {T_WWR_01_ID} asset_class must be {T_WWR_01_ASSET_CLASS!r} "
            f"(got {wwr_row['asset_class'][0]!r})"
        )
    if wwr_row["is_specific_wwr"][0] is not True:
        raise AssertionError(
            f"P8.27: {T_WWR_01_ID} is_specific_wwr must be True "
            f"(got {wwr_row['is_specific_wwr'][0]!r})"
        )
    if wwr_row["underlying_reference"][0] != T_WWR_01_UNDERLYING_REF:
        raise AssertionError(
            f"P8.27: {T_WWR_01_ID} underlying_reference must be "
            f"{T_WWR_01_UNDERLYING_REF!r} "
            f"(got {wwr_row['underlying_reference'][0]!r})"
        )

    # Invariant 3: T_NORMAL_01 checks.
    normal_row = trades_df.filter(pl.col("trade_id") == T_NORMAL_01_ID)
    if normal_row.height != 1:
        raise AssertionError(f"P8.27: trade {T_NORMAL_01_ID!r} not found")
    if normal_row["asset_class"][0] != T_NORMAL_01_ASSET_CLASS:
        raise AssertionError(
            f"P8.27: {T_NORMAL_01_ID} asset_class must be {T_NORMAL_01_ASSET_CLASS!r} "
            f"(got {normal_row['asset_class'][0]!r})"
        )
    if normal_row["is_specific_wwr"][0] is not False:
        raise AssertionError(
            f"P8.27: {T_NORMAL_01_ID} is_specific_wwr must be False "
            f"(got {normal_row['is_specific_wwr'][0]!r})"
        )

    # Invariant 4: both trades belong to NS_WWR_01.
    ns_ids = set(trades_df["netting_set_id"].to_list())
    if ns_ids != {NS_WWR_01_ID}:
        raise AssertionError(f"P8.27: all trades must belong to {NS_WWR_01_ID!r} (got {ns_ids})")


def _check_netting_set_invariants(ns_df: pl.DataFrame) -> None:
    """Validate netting-set-frame invariants 5-8 (row count, flags, null lgd override)."""
    # Invariant 5: exactly 1 netting-set row.
    if ns_df.height != 1:
        raise AssertionError(f"P8.27: expected 1 netting-set row, got {ns_df.height}")
    if ns_df["netting_set_id"][0] != NS_WWR_01_ID:
        raise AssertionError(
            f"P8.27: netting_set_id must be {NS_WWR_01_ID!r} (got {ns_df['netting_set_id'][0]!r})"
        )

    # Invariant 6: legally enforceable, unmargined.
    if ns_df["is_legally_enforceable"][0] is not True:
        raise AssertionError(
            f"P8.27: NS_WWR_01 is_legally_enforceable must be True "
            f"(got {ns_df['is_legally_enforceable'][0]!r})"
        )
    if ns_df["is_margined"][0] is not False:
        raise AssertionError(
            f"P8.27: NS_WWR_01 is_margined must be False (got {ns_df['is_margined'][0]!r})"
        )

    # Invariant 7: has_general_wwr_flag=False.
    if ns_df["has_general_wwr_flag"][0] is not False:
        raise AssertionError(
            f"P8.27: NS_WWR_01 has_general_wwr_flag must be False "
            f"(got {ns_df['has_general_wwr_flag'][0]!r})"
        )

    # Invariant 8: wwr_lgd_override is null (pre-gate input; synthetic NS not present yet).
    if ns_df["wwr_lgd_override"][0] is not None:
        raise AssertionError(
            f"P8.27: NS_WWR_01 wwr_lgd_override must be null in pre-gate input frame "
            f"(got {ns_df['wwr_lgd_override'][0]!r})"
        )


def _check_scalar_invariants() -> None:
    """Validate scalar invariants 9-11 (synthetic NS id, lgd override, expected error counts)."""
    # Invariant 9: SYNTHETIC_NS_ID forms correctly.
    expected_synthetic = f"{NS_WWR_01_ID}__wwr__{T_WWR_01_ID}"
    if expected_synthetic != SYNTHETIC_NS_ID:
        raise AssertionError(
            f"P8.27: SYNTHETIC_NS_ID must be {expected_synthetic!r} (got {SYNTHETIC_NS_ID!r})"
        )

    # Invariant 10: LGD override scalar == 1.0 (Art. 291(5)(c)).
    if WWR_LGD_OVERRIDE_VALUE != 1.0:
        raise AssertionError(
            f"P8.27: WWR_LGD_OVERRIDE_VALUE must be 1.0 (got {WWR_LGD_OVERRIDE_VALUE!r})"
        )

    # Invariant 11: expected error counts.
    if EXPECTED_CCR010_COUNT != 1:
        raise AssertionError(
            f"P8.27: EXPECTED_CCR010_COUNT must be 1 (got {EXPECTED_CCR010_COUNT!r})"
        )
    if EXPECTED_CCR011_COUNT != 0:
        raise AssertionError(
            f"P8.27: EXPECTED_CCR011_COUNT must be 0 (got {EXPECTED_CCR011_COUNT!r})"
        )
