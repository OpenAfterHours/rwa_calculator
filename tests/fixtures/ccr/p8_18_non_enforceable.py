"""
P8.18 fixture: two-trade netting set with ``is_legally_enforceable=False``.

Pipeline position:
    fixture-builder output -> test-writer (tests/unit/ccr/test_legal_enforceability.py)
    -> engine-implementer (apply_legal_enforceability_gate in sa_ccr.py)

Scenario design:
    Two interest-rate derivative trades (T_A, T_B) belonging to a single
    netting set (NS_Q1) that is **not** legally enforceable.

    NS_Q1 has ``is_legally_enforceable=False``, which triggers the
    legal-enforceability gate defined in CRR Art. 272(4) second subparagraph.
    The gate must expand each trade into its own single-trade synthetic
    netting set and append one ``CalculationError(code="CCR001")`` per
    affected original netting set to ``RawCCRBundle.errors``.

    | trade_id | netting_set_id | mtm_value | delta  | notional    |
    |----------|----------------|-----------|--------|-------------|
    | T_A      | NS_Q1          | +100.0    | +1.0   | 100_000_000 |
    | T_B      | NS_Q1          | -60.0     | -1.0   |  80_000_000 |

    Expected synthetic netting-set IDs after gate expansion:
        "NS_Q1__split__T_A"
        "NS_Q1__split__T_B"

    Zero margin agreements (unmargined).
    Zero CCR collateral.

Module-level constants are the single source of truth for test-writer
assertions; no persistent parquet files are written (the test-writer
constructs the bundle inline using these constants and the shared
``make_trade()`` / ``make_netting_set()`` helpers).

References:
    - CRR Art. 272(4) (netting set definition and legal enforceability gate)
    - CRR Art. 275(1) (replacement cost formula, unmargined)
    - CRR Art. 279a(1) (supervisory delta)
    - CRR Art. 295-297 (conditions for contractual netting recognition)
    - src/rwa_calc/data/schemas.py — TRADE_SCHEMA, NETTING_SET_SCHEMA,
      MARGIN_AGREEMENT_SCHEMA, CCR_COLLATERAL_SCHEMA
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import CCR_COLLATERAL_SCHEMA

from .margin_builder import create_margin_agreements
from .netting_set_builder import NettingSet, create_netting_sets, make_netting_set
from .trade_builder import Trade, create_trades, make_trade

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

#: Netting set identifier (not legally enforceable).
NS_Q1_ID: str = "NS_Q1"

#: Counterparty reference for NS_Q1.
CP_XX_REF: str = "CP_XX"

#: NS_Q1 is NOT legally enforceable — triggers Art. 272(4) gate.
NS_Q1_IS_LEGALLY_ENFORCEABLE: bool = False

#: NS_Q1 is unmargined.
NS_Q1_IS_MARGINED: bool = False

# --- Trade A (T_A) ---
T_A_ID: str = "T_A"
T_A_MTM: float = 100.0  # in-the-money; positive MtM
T_A_DELTA: float = 1.0  # non-option directional long (CRR Art. 279a(1))
T_A_IS_LONG: bool = True
T_A_NOTIONAL: float = 100_000_000.0  # GBP 100m
T_A_CURRENCY: str = "GBP"
T_A_ASSET_CLASS: str = "interest_rate"
T_A_TRANSACTION_TYPE: str = "derivative"
T_A_START_DATE: date = date(2026, 5, 23)
T_A_MATURITY_DATE: date = date(2036, 5, 23)  # 10-year

# --- Trade B (T_B) ---
T_B_ID: str = "T_B"
T_B_MTM: float = -60.0  # out-of-the-money for firm; negative MtM
T_B_DELTA: float = -1.0  # short directional (CRR Art. 279a(1))
T_B_IS_LONG: bool = True  # long in the underlying (short in delta sense)
T_B_NOTIONAL: float = 80_000_000.0  # GBP 80m
T_B_CURRENCY: str = "GBP"
T_B_ASSET_CLASS: str = "interest_rate"
T_B_TRANSACTION_TYPE: str = "derivative"
T_B_START_DATE: date = date(2026, 5, 23)
T_B_MATURITY_DATE: date = date(2031, 5, 23)  # 5-year

# --- Expected synthetic netting set IDs after legal-enforceability gate ---
SPLIT_NS_ID_T_A: str = f"{NS_Q1_ID}__split__{T_A_ID}"
SPLIT_NS_ID_T_B: str = f"{NS_Q1_ID}__split__{T_B_ID}"

# --- Expected CalculationError fields ---
CCR_ERROR_CODE: str = "CCR001"
CCR_ERROR_FIELD: str = "is_legally_enforceable"
CCR_ERROR_EXPECTED_VALUE: str = "True (Art. 295 conditions met)"
CCR_ERROR_ACTUAL_VALUE: str = "False"
CCR_ERROR_REGULATORY_REF: str = "CRR Art. 272(4); Art. 295-297"


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------


def _trade_a() -> Trade:
    """Return Trade A: GBP 100m IR derivative, MtM +100, delta +1."""
    return make_trade(
        trade_id=T_A_ID,
        netting_set_id=NS_Q1_ID,
        asset_class=T_A_ASSET_CLASS,
        transaction_type=T_A_TRANSACTION_TYPE,
        notional=T_A_NOTIONAL,
        currency=T_A_CURRENCY,
        maturity_date=T_A_MATURITY_DATE,
        start_date=T_A_START_DATE,
        mtm_value=T_A_MTM,
        delta=T_A_DELTA,
        is_long=T_A_IS_LONG,
    )


def _trade_b() -> Trade:
    """Return Trade B: GBP 80m IR derivative, MtM -60, delta -1."""
    return make_trade(
        trade_id=T_B_ID,
        netting_set_id=NS_Q1_ID,
        asset_class=T_B_ASSET_CLASS,
        transaction_type=T_B_TRANSACTION_TYPE,
        notional=T_B_NOTIONAL,
        currency=T_B_CURRENCY,
        maturity_date=T_B_MATURITY_DATE,
        start_date=T_B_START_DATE,
        mtm_value=T_B_MTM,
        delta=T_B_DELTA,
        is_long=T_B_IS_LONG,
    )


def _netting_set_q1() -> NettingSet:
    """Return NS_Q1: unmargined, NOT legally enforceable (Art. 272(4) gate triggers)."""
    return make_netting_set(
        netting_set_id=NS_Q1_ID,
        counterparty_reference=CP_XX_REF,
        is_legally_enforceable=NS_Q1_IS_LEGALLY_ENFORCEABLE,
        is_margined=NS_Q1_IS_MARGINED,
    )


# ---------------------------------------------------------------------------
# DataFrame factories
# ---------------------------------------------------------------------------


def create_p818_trades() -> pl.DataFrame:
    """Return the 2-row trades DataFrame for the P8.18 scenario (T_A and T_B in NS_Q1)."""
    return create_trades([_trade_a(), _trade_b()])


def create_p818_netting_sets() -> pl.DataFrame:
    """Return the 1-row netting-sets DataFrame for P8.18 (NS_Q1, not legally enforceable)."""
    return create_netting_sets([_netting_set_q1()])


def create_p818_margin_agreements() -> pl.DataFrame:
    """Return a zero-row margin-agreements DataFrame (P8.18: no CSA — unmargined)."""
    return create_margin_agreements([])


def create_p818_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (P8.18: no posted or received collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Convenience bundle accessor — returns all four frames as a named dict.
# ---------------------------------------------------------------------------


def make_p818_frames() -> dict[str, Any]:
    """
    Return a dict of the four SA-CCR input frames for the P8.18 scenario.

    Keys match the ``RawCCRBundle`` field names:
        - ``"trades"``            — 2-row ``pl.DataFrame``
        - ``"netting_sets"``      — 1-row ``pl.DataFrame``
        - ``"margin_agreements"`` — 0-row ``pl.DataFrame``
        - ``"ccr_collateral"``    — 0-row ``pl.DataFrame``

    The test-writer wraps these in the appropriate leaf bundles and then
    constructs a ``RawCCRBundle`` to pass to ``apply_legal_enforceability_gate``.

    Returns:
        Dict of ``pl.DataFrame`` objects keyed by bundle field name.
    """
    return {
        "trades": create_p818_trades(),
        "netting_sets": create_p818_netting_sets(),
        "margin_agreements": create_p818_margin_agreements(),
        "ccr_collateral": create_p818_collateral(),
    }
