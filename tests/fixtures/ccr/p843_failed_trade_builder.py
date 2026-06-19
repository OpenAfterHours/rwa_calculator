"""
P8.43 fixture builder: failed-trades DvP scenarios CCR-C1 / CCR-C2 / CCR-C3.

Pipeline position:
    fixture-builder output -> test-writer (tests/unit/ccr/test_p8_43_failed_trade_bands.py)
    -> engine-implementer (src/rwa_calc/engine/ccr/failed_trades.py — pipeline wiring)

Scenario design:
    Three DvP rows, each placed in a distinct Art. 378 Table 1 multiplier band.
    All counterparty references are distinct (CCR-C1 / C2 / C3 are independent scenarios).

    CCR-C1: lower band (t+5 to t+15, multiplier 8%)
        FT_C1  working_days=6   debt      agreed=1,000,000  mv=900,000
        price_difference = 100,000
        own_funds = 100,000 × 0.08 = 8,000
        failed_trade_rwa = 8,000 × 12.5 = 100,000

    CCR-C2: mid band (t+31 to t+45, multiplier 75%)
        FT_C2  working_days=35  equity    agreed=4,000,000  mv=3,200,000
        price_difference = 800,000
        own_funds = 800,000 × 0.75 = 600,000
        failed_trade_rwa = 600,000 × 12.5 = 7,500,000

    CCR-C3: top band boundary (t+46+, multiplier 100%)
        FT_C3  working_days=46  fx        agreed=2,000,000  mv=1,500,000
        price_difference = 500,000
        own_funds = 500,000 × 1.00 = 500,000
        failed_trade_rwa = 500,000 × 12.5 = 6,250,000

    Portfolio total RWA = 100,000 + 7,500,000 + 6,250,000 = 13,850,000

Module-level constants are the single source of truth for test-writer assertions.
No persistent parquet files are written — the test-writer imports these constants
and the ``make_c_failed_trades_frame()`` factory directly.

DEPENDENCY NOTE:
    This module imports ``FAILED_TRADE_SCHEMA`` from ``rwa_calc.data.schemas``.
    That symbol was introduced in P8.24 and is assumed present in this worktree.

References:
    - CRR Art. 378 + Table 1 (DvP multiplier ladder: 5-15, 16-30, 31-45, 46+)
    - CRR Art. 92(3)(ca) (own-funds × 12.5 = RWA)
    - src/rwa_calc/data/schemas.py — FAILED_TRADE_SCHEMA
    - src/rwa_calc/engine/ccr/failed_trades.py — compute_failed_trade_rwa
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import FAILED_TRADE_SCHEMA

# ---------------------------------------------------------------------------
# Scenario-level constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

# --- Row FT_C1: DvP, t+6, band dvp_5_15, multiplier 8%, debt instrument ---
FT_C1_ID: str = "FT_C1"
FT_C1_COUNTERPARTY_REF: str = "CP_FT_C1"
FT_C1_TYPE: str = "dvp"
FT_C1_DAYS: int = 6
FT_C1_INSTRUMENT_CLASS: str = "debt"
FT_C1_AGREED_PRICE: float = 1_000_000.0
FT_C1_MV: float = 900_000.0
FT_C1_PRICE_DIFF: float = 100_000.0  # max(0, 1,000,000 - 900,000)
FT_C1_MULTIPLIER: float = 0.08  # Art. 378 Table 1: 5-15 days overdue
FT_C1_OWN_FUNDS: float = 8_000.0  # 100,000 × 0.08
FT_C1_RWA: float = 100_000.0  # 8,000 × 12.5
FT_C1_BAND: str = "dvp_5_15"

# --- Row FT_C2: DvP, t+35, band dvp_31_45, multiplier 75%, equity instrument ---
FT_C2_ID: str = "FT_C2"
FT_C2_COUNTERPARTY_REF: str = "CP_FT_C2"
FT_C2_TYPE: str = "dvp"
FT_C2_DAYS: int = 35
FT_C2_INSTRUMENT_CLASS: str = "equity"
FT_C2_AGREED_PRICE: float = 4_000_000.0
FT_C2_MV: float = 3_200_000.0
FT_C2_PRICE_DIFF: float = 800_000.0  # max(0, 4,000,000 - 3,200,000)
FT_C2_MULTIPLIER: float = 0.75  # Art. 378 Table 1: 31-45 days overdue
FT_C2_OWN_FUNDS: float = 600_000.0  # 800,000 × 0.75
FT_C2_RWA: float = 7_500_000.0  # 600,000 × 12.5
FT_C2_BAND: str = "dvp_31_45"

# --- Row FT_C3: DvP, t+46, band dvp_46_plus, multiplier 100%, fx instrument ---
FT_C3_ID: str = "FT_C3"
FT_C3_COUNTERPARTY_REF: str = "CP_FT_C3"
FT_C3_TYPE: str = "dvp"
FT_C3_DAYS: int = 46
FT_C3_INSTRUMENT_CLASS: str = "fx"
FT_C3_AGREED_PRICE: float = 2_000_000.0
FT_C3_MV: float = 1_500_000.0
FT_C3_PRICE_DIFF: float = 500_000.0  # max(0, 2,000,000 - 1,500,000)
FT_C3_MULTIPLIER: float = 1.00  # Art. 378 Table 1: 46+ days overdue
FT_C3_OWN_FUNDS: float = 500_000.0  # 500,000 × 1.00
FT_C3_RWA: float = 6_250_000.0  # 500,000 × 12.5
FT_C3_BAND: str = "dvp_46_plus"

# --- Portfolio aggregate ---
PORTFOLIO_TOTAL_RWA: float = 13_850_000.0  # 100,000 + 7,500,000 + 6,250,000

# ---------------------------------------------------------------------------
# Optional flag defaults — all False per Art. 378-380 scope rules.
# ---------------------------------------------------------------------------

IS_REPO_OR_SEC_LENDING: bool = False
IS_IMMATERIAL: bool = False
ELECT_CET1_DEDUCTION: bool = False
SYSTEM_WIDE_FAILURE_WAIVER: bool = False


# ---------------------------------------------------------------------------
# Dataclass — mirrors FAILED_TRADE_SCHEMA field for field.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FailedTradeC:
    """
    One CCR-C failed-settlement record (DvP-only, P8.43).

    Fields mirror ``FAILED_TRADE_SCHEMA`` in ``src/rwa_calc/data/schemas.py``.
    Non-DvP fields are always null for this scenario (all three rows are DvP).

    References:
        - CRR Art. 378 Table 1 (DvP price-difference × multiplier)
    """

    failed_trade_id: str
    counterparty_reference: str
    settlement_type: str
    working_days_past_due: int
    instrument_class: str
    agreed_settlement_price: float | None = None
    current_market_value: float | None = None
    value_transferred: float | None = None
    current_positive_exposure: float | None = None
    is_repo_or_sec_lending: bool = IS_REPO_OR_SEC_LENDING
    is_immaterial: bool = IS_IMMATERIAL
    elect_cet1_deduction: bool = ELECT_CET1_DEDUCTION
    system_wide_failure_waiver: bool = SYSTEM_WIDE_FAILURE_WAIVER

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for ``pl.DataFrame`` construction."""
        return {
            "failed_trade_id": self.failed_trade_id,
            "counterparty_reference": self.counterparty_reference,
            "settlement_type": self.settlement_type,
            "working_days_past_due": self.working_days_past_due,
            "instrument_class": self.instrument_class,
            "agreed_settlement_price": self.agreed_settlement_price,
            "current_market_value": self.current_market_value,
            "value_transferred": self.value_transferred,
            "current_positive_exposure": self.current_positive_exposure,
            "is_repo_or_sec_lending": self.is_repo_or_sec_lending,
            "is_immaterial": self.is_immaterial,
            "elect_cet1_deduction": self.elect_cet1_deduction,
            "system_wide_failure_waiver": self.system_wide_failure_waiver,
        }


# ---------------------------------------------------------------------------
# Row factories.
# ---------------------------------------------------------------------------


def _ft_c1() -> FailedTradeC:
    """FT_C1: DvP, t+6, dvp_5_15 band, multiplier 8%, debt instrument."""
    return FailedTradeC(
        failed_trade_id=FT_C1_ID,
        counterparty_reference=FT_C1_COUNTERPARTY_REF,
        settlement_type=FT_C1_TYPE,
        working_days_past_due=FT_C1_DAYS,
        instrument_class=FT_C1_INSTRUMENT_CLASS,
        agreed_settlement_price=FT_C1_AGREED_PRICE,
        current_market_value=FT_C1_MV,
    )


def _ft_c2() -> FailedTradeC:
    """FT_C2: DvP, t+35, dvp_31_45 band, multiplier 75%, equity instrument."""
    return FailedTradeC(
        failed_trade_id=FT_C2_ID,
        counterparty_reference=FT_C2_COUNTERPARTY_REF,
        settlement_type=FT_C2_TYPE,
        working_days_past_due=FT_C2_DAYS,
        instrument_class=FT_C2_INSTRUMENT_CLASS,
        agreed_settlement_price=FT_C2_AGREED_PRICE,
        current_market_value=FT_C2_MV,
    )


def _ft_c3() -> FailedTradeC:
    """FT_C3: DvP, t+46, dvp_46_plus band, multiplier 100%, fx instrument."""
    return FailedTradeC(
        failed_trade_id=FT_C3_ID,
        counterparty_reference=FT_C3_COUNTERPARTY_REF,
        settlement_type=FT_C3_TYPE,
        working_days_past_due=FT_C3_DAYS,
        instrument_class=FT_C3_INSTRUMENT_CLASS,
        agreed_settlement_price=FT_C3_AGREED_PRICE,
        current_market_value=FT_C3_MV,
    )


# ---------------------------------------------------------------------------
# Public DataFrame / LazyFrame factories.
# ---------------------------------------------------------------------------


def create_c_failed_trades(trades: list[FailedTradeC]) -> pl.DataFrame:
    """
    Convert a list of ``FailedTradeC`` instances into a Polars DataFrame.

    Schema is enforced via ``dtypes_of(FAILED_TRADE_SCHEMA)``.

    Args:
        trades: One or more ``FailedTradeC`` instances.

    Returns:
        ``pl.DataFrame`` with columns matching ``FAILED_TRADE_SCHEMA``.
    """
    return pl.DataFrame([t.to_dict() for t in trades], schema=dtypes_of(FAILED_TRADE_SCHEMA))


def make_c_failed_trades_frame() -> pl.LazyFrame:
    """
    Return the canonical 3-row P8.43 failed-trade ``LazyFrame``.

    Row order:
        0 — FT_C1 (DvP, t+6,  dvp_5_15 band,    multiplier 8%)
        1 — FT_C2 (DvP, t+35, dvp_31_45 band,   multiplier 75%)
        2 — FT_C3 (DvP, t+46, dvp_46_plus band, multiplier 100%)

    Schema matches ``FAILED_TRADE_SCHEMA`` exactly.

    Returns:
        ``pl.LazyFrame`` ready for ``compute_failed_trade_rwa()``.
    """
    rows = [_ft_c1(), _ft_c2(), _ft_c3()]
    return create_c_failed_trades(rows).lazy()


def make_minimal_counterparties_frame() -> pl.LazyFrame:
    """
    Return a minimal 3-row counterparty ``LazyFrame`` for CCR-C1/C2/C3.

    Each scenario uses a distinct counterparty reference.  Entity type is
    ``"corporate"`` for all three — the risk weight on the CCR-C exposure
    path is driven by the failed-trade multiplier, not by the counterparty
    class, so the class choice is irrelevant for the settlement-risk
    calculation.  A real pipeline would need these rows for any downstream
    classifier join.

    Returns:
        ``pl.LazyFrame`` with three corporate counterparty rows.
    """
    from rwa_calc.data.column_spec import dtypes_of as _dtypes_of
    from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA as _CP_SCHEMA

    rows = [
        {
            "counterparty_reference": FT_C1_COUNTERPARTY_REF,
            "counterparty_name": "CCR-C1 Test Corporate (DvP t+6)",
            "entity_type": "corporate",
            "country_code": "GB",
            "default_status": False,
            "apply_fi_scalar": False,
            "is_managed_as_retail": False,
        },
        {
            "counterparty_reference": FT_C2_COUNTERPARTY_REF,
            "counterparty_name": "CCR-C2 Test Corporate (DvP t+35)",
            "entity_type": "corporate",
            "country_code": "GB",
            "default_status": False,
            "apply_fi_scalar": False,
            "is_managed_as_retail": False,
        },
        {
            "counterparty_reference": FT_C3_COUNTERPARTY_REF,
            "counterparty_name": "CCR-C3 Test Corporate (DvP t+46)",
            "entity_type": "corporate",
            "country_code": "GB",
            "default_status": False,
            "apply_fi_scalar": False,
            "is_managed_as_retail": False,
        },
    ]
    return pl.DataFrame(rows, schema=_dtypes_of(_CP_SCHEMA)).lazy()
