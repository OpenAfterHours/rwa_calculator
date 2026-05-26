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
    - CRR Art. 279a(2) (Black-Scholes option supervisory delta)
    - CRR Art. 279a(3) (CDO-tranche supervisory delta)
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
    # Optional nullable (4) — option/CDO supervisory delta inputs (CRR Art. 279a(2)/(3)).
    # option_type: "call" | "put" — null for non-option trades.
    # option_underlying_price: current price of the underlying (P in Black-Scholes Φ(d1)).
    # cdo_attachment: attachment point A of a CDO tranche (0 ≤ A < D ≤ 1); null if not CDO.
    # cdo_detachment: detachment point D of a CDO tranche (0 ≤ A < D ≤ 1); null if not CDO.
    option_type: str | None = None
    option_underlying_price: float | None = None
    cdo_attachment: float | None = None
    cdo_detachment: float | None = None
    payment_leg_index_id: str | None = None

    # CRR Art. 279b(1)(b): FX-derivative second-leg notional + currency.
    # Required when asset_class == "fx"; null otherwise.
    notional_leg2: float | None = None
    currency_leg2: str | None = None

    # P8.33 — equity / credit / commodity asset-class hedging-set columns.
    # All nullable: only populated for the relevant asset_class.
    # CRR Art. 279b(1)(c): equity & commodity adjusted notional d = market_price × number_of_units.
    market_price: float | None = None
    number_of_units: float | None = None
    # CRR Art. 277(2)(c)-(d): credit & equity hedging-set issuer reference / index ticker.
    reference_entity: str | None = None
    # CRR Art. 277(3)(b): commodity bucket — ELECTRICITY / OIL_GAS / METALS / AGRICULTURAL / OTHER.
    commodity_type: str | None = None
    # CRR Art. 280a / 280b: single-name vs index discriminator for credit / equity.
    is_index: bool | None = None

    # P8.35 — credit asset class: investment-grade discriminator for SF lookup.
    # Valid values: "IG" | "HY" | "NON_RATED". Null for non-credit rows.
    credit_quality: str | None = None

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
            "option_type": self.option_type,
            "option_underlying_price": self.option_underlying_price,
            "cdo_attachment": self.cdo_attachment,
            "cdo_detachment": self.cdo_detachment,
            "payment_leg_index_id": self.payment_leg_index_id,
            "notional_leg2": self.notional_leg2,
            "currency_leg2": self.currency_leg2,
            "market_price": self.market_price,
            "number_of_units": self.number_of_units,
            "reference_entity": self.reference_entity,
            "commodity_type": self.commodity_type,
            "is_index": self.is_index,
            "credit_quality": self.credit_quality,
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
        "option_type": None,
        "option_underlying_price": None,
        "cdo_attachment": None,
        "cdo_detachment": None,
        "payment_leg_index_id": None,
        "notional_leg2": None,
        "currency_leg2": None,
        "market_price": None,
        "number_of_units": None,
        "reference_entity": None,
        "commodity_type": None,
        "is_index": None,
        "credit_quality": None,
    }
    defaults.update(overrides)
    return Trade(**defaults)


def make_fx_trade(**overrides: Any) -> Trade:
    """
    Return a ``Trade`` with CCR-A2 (FX-forward) golden defaults.

    Default values represent the canonical CCR-A2 single-trade scenario:
    a 1-year GBP/USD outright forward, buy USD 100m / sell GBP 80m
    (implies forward USD/GBP = 1.25), at-par (MtM=0), unmargined, delta=1.0.

    The leg1 fields (``notional`` / ``currency``) carry the bought-currency
    side; ``notional_leg2`` / ``currency_leg2`` carry the sold-currency side.
    CRR Art. 279b(1)(b) is symmetric in legs — sign convention lives in
    ``is_long`` / ``delta`` — so the choice of which side is "leg1" is
    purely conventional.

    Args:
        **overrides: Any ``Trade`` field keyword arguments. The caller only
            needs to supply fields that differ from the golden defaults.

    Returns:
        A frozen ``Trade`` instance with ``asset_class == "fx"``.
    """
    defaults: dict[str, Any] = {
        "trade_id": "T_FX_001",
        "netting_set_id": "NS_FX_001",
        "asset_class": "fx",
        "transaction_type": "derivative",
        "notional": 100_000_000.0,
        "currency": "USD",
        "maturity_date": date(2027, 1, 15),
        "start_date": date(2026, 1, 15),
        "delta": 1.0,
        "is_long": True,
        "mtm_value": 0.0,
        "is_long_settlement": False,
        "underlying_reference": None,
        "option_strike": None,
        "option_type": None,
        "option_underlying_price": None,
        "cdo_attachment": None,
        "cdo_detachment": None,
        "payment_leg_index_id": None,
        "notional_leg2": 80_000_000.0,
        "currency_leg2": "GBP",
        "market_price": None,
        "number_of_units": None,
        "reference_entity": None,
        "commodity_type": None,
        "is_index": None,
        "credit_quality": None,
    }
    defaults.update(overrides)
    return Trade(**defaults)


def make_credit_trade(**overrides: Any) -> Trade:
    """
    Return a ``Trade`` with CCR-A3 (single-name IG CDS) golden defaults.

    Default values represent the canonical CCR-A3 single-trade scenario:
    a 5-year GBP single-name investment-grade CDS, notional GBP 100m, at-par
    (MtM=0), delta=1.0 (non-option long), unmargined.

    Key economic parameters (CCR-A3):
        - asset_class="credit" — routes to the credit adjusted-notional branch
          (CRR Art. 279b(1)(a) supervisory-duration formula, shared with IR).
        - reference_entity="ACME_LEI_5493001A" — single-name CDS issuer LEI,
          used by the credit hedging-set per-entity correlation step
          (CRR Art. 277(2)(c) + Art. 280a).
        - is_index=False — single-name flag; discriminates SF and rho lookups
          (SF_SN_IG = 0.0046, rho_SN = 0.50 per CRR Art. 280 Table 2 + 280a).
        - credit_quality="IG" — investment-grade discriminator for the SF table.

    Args:
        **overrides: Any ``Trade`` field keyword arguments. The caller only
            needs to supply fields that differ from the golden defaults.

    Returns:
        A frozen ``Trade`` instance with ``asset_class == "credit"``.

    References:
        - CRR Art. 279b(1)(a): supervisory duration d = N × SD(S, E)
        - CRR Art. 277(2)(c): one hedging set per NS for credit
        - CRR Art. 280 Table 2: SF_CR_SN_IG = 0.0046
        - CRR Art. 280a: rho = 0.50 for single-name credit
    """
    defaults: dict[str, Any] = {
        "trade_id": "T_CR_001",
        "netting_set_id": "NS_CR_001",
        "asset_class": "credit",
        "transaction_type": "derivative",
        "notional": 100_000_000.0,
        "currency": "GBP",
        "maturity_date": date(2031, 1, 15),
        "start_date": date(2026, 1, 15),
        "delta": 1.0,
        "is_long": True,
        "mtm_value": 0.0,
        "is_long_settlement": False,
        "underlying_reference": None,
        "option_strike": None,
        "option_type": None,
        "option_underlying_price": None,
        "cdo_attachment": None,
        "cdo_detachment": None,
        "payment_leg_index_id": None,
        "notional_leg2": None,
        "currency_leg2": None,
        "market_price": None,
        "number_of_units": None,
        "reference_entity": "ACME_LEI_5493001A",
        "commodity_type": None,
        "is_index": False,
        "credit_quality": "IG",
    }
    defaults.update(overrides)
    return Trade(**defaults)


def make_equity_trade(**overrides: Any) -> Trade:
    """
    Return a ``Trade`` with CCR-A5 (equity TRS) golden defaults.

    Default values represent the canonical CCR-A5 single-trade scenario:
    a 1-year GBP single-name equity TRS (T_EQ_001) in netting set NS_EQ_001.
    The adjusted notional is derived from market_price × number_of_units
    (CRR Art. 279b(1)(c)); the ``notional`` field is 0.0 as a placeholder
    (the equity branch ignores it).

    Args:
        **overrides: Any ``Trade`` field keyword arguments. The caller only
            needs to supply fields that differ from the golden defaults.

    Returns:
        A frozen ``Trade`` instance with ``asset_class == "equity"``.

    References:
        - CRR Art. 277(2)(d) (equity hedging set = one per asset class per NS)
        - CRR Art. 279a(1) (supervisory delta = 1.0 for linear long)
        - CRR Art. 279b(1)(c) (equity adjusted notional d = market_price × units)
        - CRR Art. 280b (SF_EQ = 32% SN / 20% IDX; rho = 0.50 SN / 0.80 IDX)
    """
    defaults: dict[str, Any] = {
        "trade_id": "T_EQ_001",
        "netting_set_id": "NS_EQ_001",
        "asset_class": "equity",
        "transaction_type": "derivative",
        "notional": 0.0,  # placeholder — equity branch uses market_price × number_of_units
        "currency": "GBP",
        "maturity_date": date(2027, 1, 15),
        "start_date": date(2026, 1, 15),
        "delta": 1.0,
        "is_long": True,
        "mtm_value": 0.0,
        "is_long_settlement": False,
        "underlying_reference": None,
        "option_strike": None,
        "option_type": None,
        "option_underlying_price": None,
        "cdo_attachment": None,
        "cdo_detachment": None,
        "payment_leg_index_id": None,
        "notional_leg2": None,
        "currency_leg2": None,
        "market_price": 50.0,
        "number_of_units": 1_000_000.0,
        "reference_entity": "GB00B16GWD56",
        "commodity_type": None,
        "is_index": False,
        "credit_quality": None,
    }
    defaults.update(overrides)
    return Trade(**defaults)


def make_commodity_trade(**overrides: Any) -> Trade:
    """
    Return a ``Trade`` with CCR-A7 (oil forward) golden defaults.

    Default values represent the canonical CCR-A7 single-trade scenario:
    a 2-year GBP oil forward, delta=1.0 (non-option), is_long=True,
    MtM=0.0, market_price=50.0 GBP/bbl, number_of_units=20_000.0 bbl,
    commodity_type="OIL_GAS".

    The adjusted notional is computed by the engine as
    ``d = market_price × number_of_units = 50.0 × 20_000.0 = 1_000_000.0``
    per CRR Art. 279b(1)(c); the ``notional`` field here acts as a sentinel
    for schema-level validation only (set equal to the expected d value).

    Args:
        **overrides: Any ``Trade`` field keyword arguments. The caller only
            needs to supply fields that differ from the golden defaults.

    Returns:
        A frozen ``Trade`` instance with ``asset_class == "commodity"``.

    References:
        - CRR Art. 279b(1)(c) (commodity adjusted notional d = mp × units)
        - CRR Art. 277(3)(b) (5 commodity buckets — UPPER-CASE)
        - CRR Art. 280 Table 2 (SF_CM: OIL_GAS=0.18, ELECTRICITY=0.40)
    """
    defaults: dict[str, Any] = {
        "trade_id": "T_CO_OIL_001",
        "netting_set_id": "NS_CO_001",
        "asset_class": "commodity",
        "transaction_type": "derivative",
        "notional": 1_000_000.0,
        "currency": "GBP",
        "maturity_date": date(2028, 1, 15),
        "start_date": date(2026, 1, 15),
        "delta": 1.0,
        "is_long": True,
        "mtm_value": 0.0,
        "is_long_settlement": False,
        "underlying_reference": None,
        "option_strike": None,
        "option_type": None,
        "option_underlying_price": None,
        "cdo_attachment": None,
        "cdo_detachment": None,
        "payment_leg_index_id": None,
        "notional_leg2": None,
        "currency_leg2": None,
        "market_price": 50.0,
        "number_of_units": 20_000.0,
        "reference_entity": None,
        "commodity_type": "OIL_GAS",
        "is_index": None,
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
