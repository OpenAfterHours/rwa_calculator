"""
Fixture builder for P8.13 option/CDO supervisory delta unit tests.

Pipeline position:
    fixture-builder output -> test-writer (tests/unit/ccr/test_supervisory_delta_options.py)
    -> engine-implementer (engine/ccr/supervisory_delta.py)

Key responsibilities:
- Provide 7 named trade rows covering all branches of the supervisory delta
  computation: ATM call/put (option delta), OTM short call (option delta),
  ITM long put (option delta), linear non-option (pass-through delta=1),
  long CDO tranche, and short CDO tranche.
- ``make_option_delta_trades()`` returns a ``pl.LazyFrame`` typed by
  ``dtypes_of(TRADE_SCHEMA)`` ready for the unit test to pass directly to
  the function under test.
- Module-level constants are the single source of truth for test-writer
  assertions (expected delta values are NOT baked in here — they belong in
  the test alongside the regulatory derivation).

Fixture design notes
--------------------
T is controlled via ``start_date`` and ``maturity_date``:
    maturity_date = start_date + round(T * 365) days
    reporting_date in tests = start_date  →  T_to_maturity = T exactly.

Supervisory volatility σ is not a trade-level input — the engine reads it
from SUPERVISORY_PARAMS_TABLE for the asset_class.  The fixture rows only
carry the inputs required by Art. 279a(2)/(3):

    Option delta:  option_type, option_strike (K), option_underlying_price (P), T
    CDO delta:     cdo_attachment (A), cdo_detachment (D), T  [notional used implicitly]
    Linear:        none of the above (delta=1 from Art. 279a(1))

References:
    - CRR Art. 279a(2) — Black-Scholes supervisory delta for options:
          δ = ±Φ(±(ln(P/K) + 0.5·σ²·T) / (σ·√T))
    - CRR Art. 279a(3) — CDO-tranche supervisory delta:
          δ = ±(Φ(D/(1-D)) - Φ(A/(1-A))) / (D - A)
    - BCBS CRE52.42 (option delta formula)
    - BCBS CRE52.43 (CDO-tranche delta formula)
    - src/rwa_calc/data/schemas.py — TRADE_SCHEMA
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from .trade_builder import Trade, create_trades, make_trade

# ---------------------------------------------------------------------------
# Scenario constants — referenced by the test for assertions.
# ---------------------------------------------------------------------------

#: Shared reference date; set as start_date for all trades so that
#: T_to_maturity == T when the test passes reporting_date = START_DATE.
START_DATE: date = date(2026, 1, 15)

#: Netting set for all option/CDO trades (not exercised in unit tests but
#: required by the TRADE_SCHEMA required-column contract).
NS_OPT: str = "NS_OPT"


def _maturity(t_years: float) -> date:
    """Return start_date + round(t_years * 365) days."""
    return START_DATE + timedelta(days=round(t_years * 365))


# ---------------------------------------------------------------------------
# Individual trade factories
# ---------------------------------------------------------------------------

# OPT_001: ATM call on interest-rate underlying, long, T=1.0 yr.
# P=K=0.03 → ln(P/K)=0.  Expected delta > 0 (long call).
TRADE_OPT_001: Trade = make_trade(
    trade_id="OPT_001",
    netting_set_id=NS_OPT,
    asset_class="interest_rate",
    transaction_type="derivative",
    notional=10_000_000.0,
    currency="GBP",
    start_date=START_DATE,
    maturity_date=_maturity(1.0),
    is_long=True,
    option_type="call",
    option_strike=0.03,
    option_underlying_price=0.03,
)

# OPT_002: ATM put on interest-rate underlying, long, T=1.0 yr.
# P=K=0.03.  Expected delta < 0 (long put gives negative delta).
TRADE_OPT_002: Trade = make_trade(
    trade_id="OPT_002",
    netting_set_id=NS_OPT,
    asset_class="interest_rate",
    transaction_type="derivative",
    notional=10_000_000.0,
    currency="GBP",
    start_date=START_DATE,
    maturity_date=_maturity(1.0),
    is_long=True,
    option_type="put",
    option_strike=0.03,
    option_underlying_price=0.03,
)

# OPT_003: OTM call on equity underlying, short, T=0.25 yr.
# P=100 < K=110 → ln(P/K) < 0 → Φ(d1) < 0.5.
# Short position: delta = -Φ(d1) (negative).
TRADE_OPT_003: Trade = make_trade(
    trade_id="OPT_003",
    netting_set_id=NS_OPT,
    asset_class="equity",
    transaction_type="derivative",
    notional=5_000_000.0,
    currency="GBP",
    start_date=START_DATE,
    maturity_date=_maturity(0.25),
    is_long=False,
    option_type="call",
    option_strike=110.0,
    option_underlying_price=100.0,
)

# OPT_004: ITM put on FX underlying, long, T=0.5 yr.
# P=1.20 < K=1.30 → put is in-the-money.
# Long put: delta = -Φ(-d1).
TRADE_OPT_004: Trade = make_trade(
    trade_id="OPT_004",
    netting_set_id=NS_OPT,
    asset_class="fx",
    transaction_type="derivative",
    notional=8_000_000.0,
    currency="GBP",
    start_date=START_DATE,
    maturity_date=_maturity(0.5),
    is_long=True,
    option_type="put",
    option_strike=1.30,
    option_underlying_price=1.20,
)

# LIN_001: Plain interest-rate swap, no option, long, T=5.0 yr.
# No option_type / option_strike / cdo fields → delta = +1.0 per Art. 279a(1).
TRADE_LIN_001: Trade = make_trade(
    trade_id="LIN_001",
    netting_set_id=NS_OPT,
    asset_class="interest_rate",
    transaction_type="derivative",
    notional=50_000_000.0,
    currency="GBP",
    start_date=START_DATE,
    maturity_date=_maturity(5.0),
    is_long=True,
)

# CDO_001: Long credit CDO tranche, A=3%, D=7%, T=5.0 yr.
# Long position: delta = +|Φ(D/(1-D)) - Φ(A/(1-A))| / (D - A).
TRADE_CDO_001: Trade = make_trade(
    trade_id="CDO_001",
    netting_set_id=NS_OPT,
    asset_class="credit",
    transaction_type="derivative",
    notional=20_000_000.0,
    currency="GBP",
    start_date=START_DATE,
    maturity_date=_maturity(5.0),
    is_long=True,
    cdo_attachment=0.03,
    cdo_detachment=0.07,
)

# CDO_002: Short credit CDO tranche, A=3%, D=7%, T=5.0 yr.
# Short position: delta is negated relative to CDO_001.
TRADE_CDO_002: Trade = make_trade(
    trade_id="CDO_002",
    netting_set_id=NS_OPT,
    asset_class="credit",
    transaction_type="derivative",
    notional=20_000_000.0,
    currency="GBP",
    start_date=START_DATE,
    maturity_date=_maturity(5.0),
    is_long=False,
    cdo_attachment=0.03,
    cdo_detachment=0.07,
)

# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

_ALL_TRADES: list[Trade] = [
    TRADE_OPT_001,
    TRADE_OPT_002,
    TRADE_OPT_003,
    TRADE_OPT_004,
    TRADE_LIN_001,
    TRADE_CDO_001,
    TRADE_CDO_002,
]


def make_option_delta_trades() -> pl.LazyFrame:
    """
    Return a 7-row ``LazyFrame`` covering option, linear, and CDO-tranche trades.

    Schema matches ``TRADE_SCHEMA`` exactly (via ``dtypes_of``), including the
    four new nullable columns added for P8.13:
        option_type, option_underlying_price, cdo_attachment, cdo_detachment.

    Use ``reporting_date = START_DATE`` in the test so that T_to_maturity
    equals the T values in the proposal table exactly.

    Returns:
        ``pl.LazyFrame`` with 7 rows and full TRADE_SCHEMA columns.
    """
    return create_trades(_ALL_TRADES).lazy()


def make_option_trades_only() -> pl.LazyFrame:
    """Return the 4 option rows only (OPT_001..OPT_004)."""
    return create_trades([TRADE_OPT_001, TRADE_OPT_002, TRADE_OPT_003, TRADE_OPT_004]).lazy()


def make_cdo_trades_only() -> pl.LazyFrame:
    """Return the 2 CDO tranche rows only (CDO_001, CDO_002)."""
    return create_trades([TRADE_CDO_001, TRADE_CDO_002]).lazy()


def make_linear_trade() -> pl.LazyFrame:
    """Return the single linear (non-option) row (LIN_001)."""
    return create_trades([TRADE_LIN_001]).lazy()
