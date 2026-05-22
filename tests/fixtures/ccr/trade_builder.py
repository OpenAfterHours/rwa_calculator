"""
Trade-level fixture builder for SA-CCR tests.

Pipeline position:
    fixture-builder output -> test-writer (tests/integration/, tests/acceptance/)
    -> engine-implementer (CCR calculator)

Key responsibilities:
- Provide a frozen dataclass ``Trade`` whose fields mirror ``TRADE_SCHEMA``
  exactly (column names, dtypes, required/optional with defaults).
- ``make_trade(**overrides)`` produces a single ``Trade`` with sensible defaults
  for the CCR-A1 golden scenario (10-year GBP IR swap, unmargined, delta=1.0).
- ``create_trades(trades)`` converts a list of ``Trade`` instances to a
  ``pl.DataFrame`` typed by ``dtypes_of(TRADE_SCHEMA)``.

References:
    - CRR Art. 271 (CCR scope — OTC derivatives, SFTs)
    - CRR Art. 272(2) (transaction definition)
    - CRR Art. 279a(1) (supervisory delta for non-option trades)
    - CRR Art. 275 (replacement cost: V = mtm_value)
    - src/rwa_calc/data/schemas.py — TRADE_SCHEMA
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import TRADE_SCHEMA

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Trade:
    """
    One OTC derivative or SFT trade for SA-CCR input.

    Fields mirror ``TRADE_SCHEMA`` in ``src/rwa_calc/data/schemas.py`` exactly.
    Required fields (no default) match the 8 ``ColumnSpec(required=True)`` entries;
    optional fields carry the same defaults as the ``ColumnSpec`` declarations.

    References:
        - CRR Art. 271-272 (trade definition and netting set membership)
        - CRR Art. 275 (mtm_value = V in replacement cost formula)
        - CRR Art. 279a(1) (delta = 1.0 for non-option directional trades)
    """

    # Required (8) — must be supplied by the caller.
    trade_id: str
    netting_set_id: str
    # "interest_rate" | "fx" | "credit" | "equity" | "commodity"
    asset_class: str
    # "derivative" | "sft"
    transaction_type: str
    notional: float
    currency: str
    maturity_date: date
    start_date: date

    # Optional with defaults (4) — match ColumnSpec defaults in TRADE_SCHEMA.
    # CRR Art. 279a(1): supervisory delta defaults to 1.0 for non-option directional trades.
    delta: float = 1.0
    is_long: bool = True
    # CRR Art. 275: V (current market value). 0.0 = at-par trade.
    mtm_value: float = 0.0
    is_long_settlement: bool = False

    # Optional nullable (3) — null when not applicable.
    underlying_reference: str | None = None
    option_strike: float | None = None
    payment_leg_index_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for ``pl.DataFrame`` construction."""
        return {
            "trade_id": self.trade_id,
            "netting_set_id": self.netting_set_id,
            "asset_class": self.asset_class,
            "transaction_type": self.transaction_type,
            "notional": self.notional,
            "currency": self.currency,
            "maturity_date": self.maturity_date,
            "start_date": self.start_date,
            "delta": self.delta,
            "is_long": self.is_long,
            "mtm_value": self.mtm_value,
            "is_long_settlement": self.is_long_settlement,
            "underlying_reference": self.underlying_reference,
            "option_strike": self.option_strike,
            "payment_leg_index_id": self.payment_leg_index_id,
        }


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_trade(**overrides: Any) -> Trade:
    """
    Return a ``Trade`` with CCR-A1 golden defaults, optionally overridden.

    Default values represent the canonical CCR-A1 single-trade scenario:
    a 10-year GBP vanilla IR swap, notional GBP 100m, at-par (MtM=0),
    delta=1.0 (non-option), is_long=True, no underlying/option/index.

    Args:
        **overrides: Any ``Trade`` field keyword arguments.  The caller only
            needs to supply fields that differ from the golden defaults.

    Returns:
        A frozen ``Trade`` instance.
    """
    defaults: dict[str, Any] = {
        "trade_id": "T_001",
        "netting_set_id": "NS_001",
        "asset_class": "interest_rate",
        "transaction_type": "derivative",
        "notional": 100_000_000.0,
        "currency": "GBP",
        "maturity_date": date(2036, 1, 15),
        "start_date": date(2026, 1, 15),
        "delta": 1.0,
        "is_long": True,
        "mtm_value": 0.0,
        "is_long_settlement": False,
        "underlying_reference": None,
        "option_strike": None,
        "payment_leg_index_id": None,
    }
    defaults.update(overrides)
    return Trade(**defaults)


def create_trades(trades: list[Trade]) -> pl.DataFrame:
    """
    Convert a list of ``Trade`` instances into a Polars DataFrame.

    Schema is enforced via ``dtypes_of(TRADE_SCHEMA)`` — the canonical dtype
    dict derived from ``src/rwa_calc/data/schemas.py``.

    Args:
        trades: One or more ``Trade`` instances.

    Returns:
        ``pl.DataFrame`` with columns matching ``TRADE_SCHEMA``.
    """
    return pl.DataFrame([t.to_dict() for t in trades], schema=dtypes_of(TRADE_SCHEMA))
