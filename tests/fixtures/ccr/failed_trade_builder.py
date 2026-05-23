"""
P8.24 fixture builder: failed-trades DvP / non-DvP settlement risk scenario.

Pipeline position:
    fixture-builder output -> test-writer (tests/unit/ccr/test_p8_24_failed_trades.py)
    -> engine-implementer (src/rwa_calc/engine/ccr/failed_trades.py)

Scenario design:
    Five rows covering both settlement-type branches:

    DvP rows (4) — CRR Art. 378 + Table 1:
        FT001  t+5  day band dvp_5_15     multiplier 0.08  price-diff   50,000
        FT002  t+20 day band dvp_16_30    multiplier 0.50  price-diff  200,000
        FT003  t+35 day band dvp_31_45    multiplier 0.75  price-diff  100,000
        FT004  t+50 day band dvp_46_plus  multiplier 1.00  price-diff  150,000

    non-DvP row (1) — CRR Art. 379(1) + Table 2 Column 4:
        FT005  t+6  band non_dvp_col4_t5_plus  RW=12.50
               exposure = value_transferred (1M) + current_positive_exposure (1.05M)
                        = 2,050,000
               own_funds_requirement = 2,050,000
               failed_trade_rwa = 25,625,000

    Portfolio total RWA = 29,737,500.

Module-level constants are the single source of truth for test-writer assertions.
No persistent parquet files are written — the test-writer imports these constants
and the ``make_failed_trades_frame()`` factory directly.

DEPENDENCY NOTE:
    This module imports ``FAILED_TRADE_SCHEMA`` from ``rwa_calc.data.schemas``.
    That symbol does not exist until engine-implementer lands the schema addition
    (P8.24 engine wave).  Import will raise ``ImportError`` until then, causing
    loud pytest-collection failure — which is the desired failing-test signal for
    the test-writer and engine-implementer waves.

References:
    - CRR Art. 378 + Table 1 (DvP multiplier ladder: t+5, t+20, t+35, t+45+)
    - CRR Art. 379(1) + Table 2 (non-DvP: Col 2 pre-first-leg, Col 3 t0-t4,
      Col 4 t5+)
    - CRR Art. 379(2) — IRB PD inference + immateriality carve-out (OOS in
      this scenario; all rows use Col 4 1250% RW)
    - CRR Art. 379(3) — CET1 deduction alternative (flag default False)
    - CRR Art. 380 — system-wide failure waiver (flag default False)
    - PRA PS1/26 Art. 92(3)(a), 92(3)(ca) — UK onshoring, unchanged numerics
    - src/rwa_calc/data/schemas.py — FAILED_TRADE_SCHEMA (added by engine-implementer)
    - src/rwa_calc/data/tables/failed_trades_multipliers.py — Art. 378 Table 1
      multiplier ladder (added by engine-implementer)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import FAILED_TRADE_SCHEMA  # requires engine-implementer wave

# ---------------------------------------------------------------------------
# Scenario-level constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

#: Counterparty that owns all five failed-trade rows.
COUNTERPARTY_REF: str = "CP_FT_001"

# --- Row FT001: DvP, t+5, band dvp_5_15 ---
FT001_ID: str = "FT001"
FT001_TYPE: str = "dvp"
FT001_DAYS: int = 5
FT001_AGREED_PRICE: float = 1_000_000.0
FT001_MV: float = 950_000.0
FT001_PRICE_DIFF: float = 50_000.0  # max(0, agreed - mv) = 50,000
FT001_MULTIPLIER: float = 0.08  # Art. 378 Table 1: 5-15 days overdue
FT001_OWN_FUNDS: float = 4_000.0  # 50,000 × 0.08
FT001_RWA: float = 50_000.0  # 4,000 × 12.5
FT001_BAND: str = "dvp_5_15"
FT001_INSTRUMENT_CLASS: str = "equity"

# --- Row FT002: DvP, t+20, band dvp_16_30 ---
FT002_ID: str = "FT002"
FT002_TYPE: str = "dvp"
FT002_DAYS: int = 20
FT002_AGREED_PRICE: float = 2_000_000.0
FT002_MV: float = 1_800_000.0
FT002_PRICE_DIFF: float = 200_000.0  # max(0, 2M - 1.8M)
FT002_MULTIPLIER: float = 0.50  # Art. 378 Table 1: 16-30 days overdue
FT002_OWN_FUNDS: float = 100_000.0  # 200,000 × 0.50
FT002_RWA: float = 1_250_000.0  # 100,000 × 12.5
FT002_BAND: str = "dvp_16_30"
FT002_INSTRUMENT_CLASS: str = "debt"

# --- Row FT003: DvP, t+35, band dvp_31_45 ---
FT003_ID: str = "FT003"
FT003_TYPE: str = "dvp"
FT003_DAYS: int = 35
FT003_AGREED_PRICE: float = 500_000.0
FT003_MV: float = 400_000.0
FT003_PRICE_DIFF: float = 100_000.0  # max(0, 500k - 400k)
FT003_MULTIPLIER: float = 0.75  # Art. 378 Table 1: 31-45 days overdue
FT003_OWN_FUNDS: float = 75_000.0  # 100,000 × 0.75
FT003_RWA: float = 937_500.0  # 75,000 × 12.5
FT003_BAND: str = "dvp_31_45"
FT003_INSTRUMENT_CLASS: str = "fx"

# --- Row FT004: DvP, t+50, band dvp_46_plus ---
FT004_ID: str = "FT004"
FT004_TYPE: str = "dvp"
FT004_DAYS: int = 50
FT004_AGREED_PRICE: float = 750_000.0
FT004_MV: float = 600_000.0
FT004_PRICE_DIFF: float = 150_000.0  # max(0, 750k - 600k)
FT004_MULTIPLIER: float = 1.00  # Art. 378 Table 1: 46+ days overdue
FT004_OWN_FUNDS: float = 150_000.0  # 150,000 × 1.00
FT004_RWA: float = 1_875_000.0  # 150,000 × 12.5
FT004_BAND: str = "dvp_46_plus"
FT004_INSTRUMENT_CLASS: str = "commodity"

# --- Row FT005: non-DvP free delivery, t+6, Col 4 (1250% RW) ---
FT005_ID: str = "FT005"
FT005_TYPE: str = "non_dvp_free_delivery"
FT005_DAYS: int = 6
FT005_VALUE_TRANSFERRED: float = 1_000_000.0
FT005_CURRENT_POSITIVE_EXPOSURE: float = 1_050_000.0
# Art. 379(1) Table 2 Col 4: exposure = value_transferred + current_positive_exposure
FT005_EXPOSURE: float = 2_050_000.0  # 1M + 1.05M
# Col 4 RW = 1250% expressed as multiplier (own-funds = exposure × 100%)
FT005_MULTIPLIER_OR_RW: float = 12.50  # RW=1250% => own-funds factor=1.0; RWA = exposure × 12.5
FT005_OWN_FUNDS: float = 2_050_000.0  # Art. 379(1): own-funds = full exposure amount
FT005_RWA: float = 25_625_000.0  # 2,050,000 × 12.5
FT005_BAND: str = "non_dvp_col4_t5_plus"
FT005_INSTRUMENT_CLASS: str = "equity"

# --- Portfolio aggregate ---
PORTFOLIO_TOTAL_RWA: float = 29_737_500.0  # sum of all 5 rows


# ---------------------------------------------------------------------------
# Optional flag defaults — all False per proposal Section 2 and Art. 378-380.
# ---------------------------------------------------------------------------

#: Art. 378 first paragraph: repo/SFT exclusion gate. False = in scope.
IS_REPO_OR_SEC_LENDING: bool = False

#: Art. 379(2) immateriality 100% RW alternative. False = full 1250% RW.
IS_IMMATERIAL: bool = False

#: Art. 379(3) CET1 deduction election. False = standard RWA treatment.
ELECT_CET1_DEDUCTION: bool = False

#: Art. 380 system-wide failure waiver. False = no waiver (OOS).
SYSTEM_WIDE_FAILURE_WAIVER: bool = False


# ---------------------------------------------------------------------------
# Dataclass — mirrors FAILED_TRADE_SCHEMA field for field.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FailedTrade:
    """
    One failed-settlement record for P8.24 (DvP or non-DvP).

    Fields mirror ``FAILED_TRADE_SCHEMA`` in ``src/rwa_calc/data/schemas.py``
    exactly (column names, dtypes, required/optional with defaults).

    DvP fields (``agreed_settlement_price``, ``current_market_value``) are
    required for ``settlement_type="dvp"`` rows; null for non-DvP.
    Non-DvP fields (``value_transferred``, ``current_positive_exposure``) are
    required for ``settlement_type="non_dvp_free_delivery"`` rows; null for DvP.

    References:
        - CRR Art. 378 Table 1 (DvP price-difference × multiplier)
        - CRR Art. 379(1) Table 2 (non-DvP exposure = sum of both legs)
    """

    # Required (5) — primary key + core settlement attributes.
    failed_trade_id: str
    counterparty_reference: str
    # "dvp" | "non_dvp_free_delivery"
    settlement_type: str
    working_days_past_due: int
    # "debt" | "equity" | "fx" | "commodity"
    instrument_class: str

    # DvP-only required (null for non-DvP).
    agreed_settlement_price: float | None = None
    current_market_value: float | None = None

    # non-DvP-only required (null for DvP).
    value_transferred: float | None = None
    current_positive_exposure: float | None = None

    # Optional boolean flags — default False per Art. 378-380 scope rules.
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
# Row factories — one per scenario row.
# ---------------------------------------------------------------------------


def _ft001() -> FailedTrade:
    """FT001: DvP, t+5, dvp_5_15 band, multiplier 8%, equity instrument."""
    return FailedTrade(
        failed_trade_id=FT001_ID,
        counterparty_reference=COUNTERPARTY_REF,
        settlement_type=FT001_TYPE,
        working_days_past_due=FT001_DAYS,
        instrument_class=FT001_INSTRUMENT_CLASS,
        agreed_settlement_price=FT001_AGREED_PRICE,
        current_market_value=FT001_MV,
        value_transferred=None,
        current_positive_exposure=None,
    )


def _ft002() -> FailedTrade:
    """FT002: DvP, t+20, dvp_16_30 band, multiplier 50%, debt instrument."""
    return FailedTrade(
        failed_trade_id=FT002_ID,
        counterparty_reference=COUNTERPARTY_REF,
        settlement_type=FT002_TYPE,
        working_days_past_due=FT002_DAYS,
        instrument_class=FT002_INSTRUMENT_CLASS,
        agreed_settlement_price=FT002_AGREED_PRICE,
        current_market_value=FT002_MV,
        value_transferred=None,
        current_positive_exposure=None,
    )


def _ft003() -> FailedTrade:
    """FT003: DvP, t+35, dvp_31_45 band, multiplier 75%, FX instrument."""
    return FailedTrade(
        failed_trade_id=FT003_ID,
        counterparty_reference=COUNTERPARTY_REF,
        settlement_type=FT003_TYPE,
        working_days_past_due=FT003_DAYS,
        instrument_class=FT003_INSTRUMENT_CLASS,
        agreed_settlement_price=FT003_AGREED_PRICE,
        current_market_value=FT003_MV,
        value_transferred=None,
        current_positive_exposure=None,
    )


def _ft004() -> FailedTrade:
    """FT004: DvP, t+50, dvp_46_plus band, multiplier 100%, commodity instrument."""
    return FailedTrade(
        failed_trade_id=FT004_ID,
        counterparty_reference=COUNTERPARTY_REF,
        settlement_type=FT004_TYPE,
        working_days_past_due=FT004_DAYS,
        instrument_class=FT004_INSTRUMENT_CLASS,
        agreed_settlement_price=FT004_AGREED_PRICE,
        current_market_value=FT004_MV,
        value_transferred=None,
        current_positive_exposure=None,
    )


def _ft005() -> FailedTrade:
    """FT005: non-DvP free delivery, t+6, Col 4 (1250% RW), equity instrument."""
    return FailedTrade(
        failed_trade_id=FT005_ID,
        counterparty_reference=COUNTERPARTY_REF,
        settlement_type=FT005_TYPE,
        working_days_past_due=FT005_DAYS,
        instrument_class=FT005_INSTRUMENT_CLASS,
        agreed_settlement_price=None,
        current_market_value=None,
        value_transferred=FT005_VALUE_TRANSFERRED,
        current_positive_exposure=FT005_CURRENT_POSITIVE_EXPOSURE,
    )


# ---------------------------------------------------------------------------
# Public DataFrame / LazyFrame factories.
# ---------------------------------------------------------------------------


def make_failed_trade(**overrides: Any) -> FailedTrade:
    """
    Return a ``FailedTrade`` with FT001 defaults, optionally overridden.

    Args:
        **overrides: Any ``FailedTrade`` field keyword arguments.

    Returns:
        A frozen ``FailedTrade`` instance.
    """
    defaults: dict[str, Any] = {
        "failed_trade_id": FT001_ID,
        "counterparty_reference": COUNTERPARTY_REF,
        "settlement_type": FT001_TYPE,
        "working_days_past_due": FT001_DAYS,
        "instrument_class": FT001_INSTRUMENT_CLASS,
        "agreed_settlement_price": FT001_AGREED_PRICE,
        "current_market_value": FT001_MV,
        "value_transferred": None,
        "current_positive_exposure": None,
        "is_repo_or_sec_lending": IS_REPO_OR_SEC_LENDING,
        "is_immaterial": IS_IMMATERIAL,
        "elect_cet1_deduction": ELECT_CET1_DEDUCTION,
        "system_wide_failure_waiver": SYSTEM_WIDE_FAILURE_WAIVER,
    }
    defaults.update(overrides)
    return FailedTrade(**defaults)


def create_failed_trades(trades: list[FailedTrade]) -> pl.DataFrame:
    """
    Convert a list of ``FailedTrade`` instances into a Polars DataFrame.

    Schema is enforced via ``dtypes_of(FAILED_TRADE_SCHEMA)`` — the canonical
    dtype dict derived from ``src/rwa_calc/data/schemas.py``.

    Args:
        trades: One or more ``FailedTrade`` instances.

    Returns:
        ``pl.DataFrame`` with columns matching ``FAILED_TRADE_SCHEMA``.
    """
    return pl.DataFrame([t.to_dict() for t in trades], schema=dtypes_of(FAILED_TRADE_SCHEMA))


def make_failed_trades_frame() -> pl.LazyFrame:
    """
    Return the canonical 5-row P8.24 failed-trade ``LazyFrame``.

    Row order:
        0 — FT001 (DvP, t+5)
        1 — FT002 (DvP, t+20)
        2 — FT003 (DvP, t+35)
        3 — FT004 (DvP, t+50)
        4 — FT005 (non-DvP, t+6)

    Schema matches ``FAILED_TRADE_SCHEMA`` exactly.

    Returns:
        ``pl.LazyFrame`` ready for ``compute_failed_trade_rwa()``.
    """
    rows = [_ft001(), _ft002(), _ft003(), _ft004(), _ft005()]
    return create_failed_trades(rows).lazy()
