"""
Golden CCR-A10 scenario: mixed-asset-class netting set — one trade per asset class.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/)
    -> engine-implementer (SA-CCR cross-asset-class linear AddOn aggregation)

Scenario design:
    Five trades share netting set NS_MIX_001, counterparty CP_001
    (institution, CQS 2, GB), legally enforceable (Art. 295), unmargined.
    Each trade is an exact clone of the corresponding single-asset CCR-A* scenario
    so that each per-class add-on reproduces the existing golden value.

    | trade_id       | asset_class   | source scenario | per-class add-on      |
    |----------------|---------------|-----------------|-----------------------|
    | T_MIX_IR_001   | interest_rate | CCR-A1          | 3_914_298.228         |
    | T_MIX_FX_001   | fx            | CCR-A2          | 3_198_904.672         |
    | T_MIX_CR_001   | credit        | CCR-A3          | 2_016_405.972         |
    | T_MIX_EQ_001   | equity        | CCR-A5          | 15_994_523.295317     |
    | T_MIX_CO_001   | commodity     | CCR-A7          | 180_000.0             |

Load-bearing target (CRR Art. 278(2) — linear sum, no cross-class correlation):
    AddOn_aggregate = Σ AddOn_asset_class
                    = 3_914_298.228
                    + 3_198_904.672
                    + 2_016_405.972
                    + 15_994_523.295317
                    + 180_000.0
                    = 25_304_132.167317

    RC = max(V - C, 0) = max(0 - 0, 0) = 0                (Art. 275(1))
    PFE multiplier = 1.0 (at-par, V=0, C=0)               (Art. 278(3))
    PFE_addon = 1.0 × 25_304_132.167317                    (Art. 278(1))
    EAD = 1.4 × (0 + 25_304_132.167317) = 35_425_785.034244 (Art. 274(2))
    RWA = 35_425_785.034244 × 0.50 = 17_712_892.517122     (Art. 120(1) Table 3)

FX rates:
    USD->GBP = 0.80 required for the FX trade leg-1 conversion
    (reuses create_ccr_a2_fx_rates() from golden_ccr_a2).

Counterparty reuse:
    CCR-A10 reuses the CCR-A1 institution counterparty (CP_001, GB, CQS 2) so
    the SA Institution lookup ends in 50% RW.  The counterparty/rating builders
    are imported from ``golden_ccr_a1`` directly.

References:
    - CRR Art. 271 (CCR scope)
    - CRR Art. 274(2) (EAD = alpha × (RC + PFE), alpha = 1.4)
    - CRR Art. 275(1) (unmargined RC = max(V - C, 0))
    - CRR Art. 277(1)–(3) (asset-class / hedging-set partition)
    - CRR Art. 278(1) (PFE = multiplier × AddOn_aggregate)
    - CRR Art. 278(2) (AddOn_aggregate = linear sum across asset classes)
    - CRR Art. 278(3) (PFE multiplier floor F = 0.05)
    - CRR Art. 279b (adjusted notional — per-asset-class branches)
    - CRR Art. 279c(1) (unmargined MF = sqrt(min(M, 1y) / 1y))
    - CRR Art. 280–280c (supervisory factors per asset class)
    - CRR Art. 120(1) Table 3 (institution CQS 2 SA risk weight = 50%)
    - BCBS CRE52.20–22 (cross-asset-class linear aggregation)
"""

from __future__ import annotations

from datetime import date as _date
from pathlib import Path

import polars as pl

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    RawDataBundle,
    TradeBundle,
)
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import CCR_COLLATERAL_SCHEMA
from tests.fixtures.raw_bundle import make_raw_bundle

from .golden_ccr_a1 import (
    _build_cp_001_counterparty,
    _build_cp_001_rating,
    _build_empty_facilities,
    _build_empty_facility_mappings,
    _build_empty_lending_mappings,
    _build_empty_loans,
    create_ccr_a1_margin_agreements,
)
from .golden_ccr_a2 import create_ccr_a2_fx_rates
from .netting_set_builder import NettingSet, create_netting_sets
from .trade_builder import (
    Trade,
    create_trades,
    make_commodity_trade,
    make_credit_trade,
    make_equity_trade,
    make_fx_trade,
    make_trade,
)

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for CCR-A10 test assertions.
# ---------------------------------------------------------------------------

CCR_A10_NETTING_SET_ID: str = "NS_MIX_001"
CCR_A10_COUNTERPARTY_REF: str = "CP_001"  # reuse CCR-A1 institution CP

CCR_A10_IS_LEGALLY_ENFORCEABLE: bool = True
CCR_A10_IS_MARGINED: bool = False

# -- IR trade (clone of CCR-A1 T_001) --
CCR_A10_TRADE_IR_ID: str = "T_MIX_IR_001"
CCR_A10_IR_ASSET_CLASS: str = "interest_rate"
CCR_A10_IR_TRANSACTION_TYPE: str = "derivative"
CCR_A10_IR_NOTIONAL: float = 100_000_000.0  # GBP 100m
CCR_A10_IR_CURRENCY: str = "GBP"
CCR_A10_IR_START_DATE: _date = _date(2026, 1, 15)
CCR_A10_IR_MATURITY_DATE: _date = _date(2036, 1, 15)  # 10y tenor
CCR_A10_IR_DELTA: float = 1.0
CCR_A10_IR_IS_LONG: bool = True
CCR_A10_IR_MTM: float = 0.0

# -- FX trade (clone of CCR-A2 T_FX_001) --
CCR_A10_TRADE_FX_ID: str = "T_MIX_FX_001"
CCR_A10_FX_ASSET_CLASS: str = "fx"
CCR_A10_FX_TRANSACTION_TYPE: str = "derivative"
CCR_A10_FX_NOTIONAL_LEG1: float = 100_000_000.0  # USD 100m (buy)
CCR_A10_FX_CURRENCY_LEG1: str = "USD"
CCR_A10_FX_NOTIONAL_LEG2: float = 80_000_000.0  # GBP 80m (sell)
CCR_A10_FX_CURRENCY_LEG2: str = "GBP"
CCR_A10_FX_START_DATE: _date = _date(2026, 1, 15)
CCR_A10_FX_MATURITY_DATE: _date = _date(2027, 1, 15)  # 1y tenor
CCR_A10_FX_DELTA: float = 1.0
CCR_A10_FX_IS_LONG: bool = True
CCR_A10_FX_MTM: float = 0.0

# -- Credit trade (clone of CCR-A3 T_CR_001) --
CCR_A10_TRADE_CR_ID: str = "T_MIX_CR_001"
CCR_A10_CR_ASSET_CLASS: str = "credit"
CCR_A10_CR_TRANSACTION_TYPE: str = "derivative"
CCR_A10_CR_NOTIONAL: float = 100_000_000.0  # GBP 100m
CCR_A10_CR_CURRENCY: str = "GBP"
CCR_A10_CR_START_DATE: _date = _date(2026, 1, 15)
CCR_A10_CR_MATURITY_DATE: _date = _date(2031, 1, 15)  # 5y tenor
CCR_A10_CR_DELTA: float = 1.0
CCR_A10_CR_IS_LONG: bool = True
CCR_A10_CR_MTM: float = 0.0
CCR_A10_CR_REFERENCE_ENTITY: str = "ACME_LEI_5493001A"
CCR_A10_CR_IS_INDEX: bool = False
CCR_A10_CR_CREDIT_QUALITY: str = "IG"

# -- Equity trade (clone of CCR-A5 T_EQ_001) --
CCR_A10_TRADE_EQ_ID: str = "T_MIX_EQ_001"
CCR_A10_EQ_ASSET_CLASS: str = "equity"
CCR_A10_EQ_TRANSACTION_TYPE: str = "derivative"
CCR_A10_EQ_MARKET_PRICE: float = 50.0  # GBP per unit
CCR_A10_EQ_NUMBER_OF_UNITS: float = 1_000_000.0
CCR_A10_EQ_REFERENCE_ENTITY: str = "GB00B16GWD56"
CCR_A10_EQ_IS_INDEX: bool = False
CCR_A10_EQ_START_DATE: _date = _date(2026, 1, 15)
CCR_A10_EQ_MATURITY_DATE: _date = _date(2027, 1, 15)  # 1y tenor
CCR_A10_EQ_DELTA: float = 1.0
CCR_A10_EQ_IS_LONG: bool = True
CCR_A10_EQ_MTM: float = 0.0

# -- Commodity trade (clone of CCR-A7 T_CO_OIL_001) --
CCR_A10_TRADE_CO_ID: str = "T_MIX_CO_001"
CCR_A10_CO_ASSET_CLASS: str = "commodity"
CCR_A10_CO_TRANSACTION_TYPE: str = "derivative"
CCR_A10_CO_COMMODITY_TYPE: str = "OIL_GAS"  # UPPER-CASE per COLUMN_VALUE_CONSTRAINTS
CCR_A10_CO_NOTIONAL: float = 1_000_000.0  # sentinel = expected d
CCR_A10_CO_CURRENCY: str = "GBP"
CCR_A10_CO_MARKET_PRICE: float = 50.0  # GBP per bbl
CCR_A10_CO_NUMBER_OF_UNITS: float = 20_000.0  # bbl
CCR_A10_CO_START_DATE: _date = _date(2026, 1, 15)
CCR_A10_CO_MATURITY_DATE: _date = _date(2028, 1, 15)  # 2y tenor
CCR_A10_CO_DELTA: float = 1.0
CCR_A10_CO_IS_LONG: bool = True
CCR_A10_CO_MTM: float = 0.0

# ---------------------------------------------------------------------------
# Expected output constants — hand-calculated per CRR Art. 278(2).
# Per-class add-ons reproduce the existing golden values from CCR-A1/A2/A3/A5/A7.
# ---------------------------------------------------------------------------

# CRR Art. 275(1): RC = max(V - C, 0) = max(0 - 0, 0) = 0.
CCR_A10_RC_UNMARGINED: float = 0.0

# Per-class add-ons (cloned from single-asset scenarios — see proposal section 3).
CCR_A10_ADDON_IR: float = 3_914_298.228  # CCR-A1 golden
CCR_A10_ADDON_FX: float = 3_198_904.672  # CCR-A2 golden
CCR_A10_ADDON_CREDIT: float = 2_016_405.972  # CCR-A3 golden
CCR_A10_ADDON_EQUITY: float = 15_994_523.295317  # CCR-A5 golden
CCR_A10_ADDON_COMMODITY: float = 180_000.0  # CCR-A7 golden

# CRR Art. 278(2): AddOn_aggregate = linear sum (no cross-class correlation).
CCR_A10_ADDON_AGGREGATE: float = 25_304_132.167317

# CRR Art. 278(3): PFE multiplier = 1.0 (at-par, V=0, C=0).
CCR_A10_PFE_MULTIPLIER: float = 1.0

# CRR Art. 278(1): PFE_addon = multiplier × AddOn_aggregate.
CCR_A10_PFE_ADDON: float = 25_304_132.167317

# CRR Art. 274(2): EAD = 1.4 × (RC + PFE).
CCR_A10_EAD_CCR: float = 35_425_785.034244
CCR_A10_EAD_FINAL: float = 35_425_785.034244

# CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight.
CCR_A10_EXPOSURE_CLASS: str = "institution"
CCR_A10_RISK_WEIGHT: float = 0.50

# RWA = EAD × RW.
CCR_A10_RWA_FINAL: float = 17_712_892.517122

# Tolerance bounds for acceptance assertions.
CCR_A10_MONETARY_REL_TOLERANCE: float = 1e-6
CCR_A10_MULTIPLIER_ABS_TOLERANCE: float = 1e-12


# ---------------------------------------------------------------------------
# CCR-A10 trade builders — one per asset class.
# ---------------------------------------------------------------------------


def _ccr_a10_ir_trade() -> Trade:
    """Return the IR swap trade for CCR-A10 (clone of CCR-A1 T_001)."""
    return make_trade(
        trade_id=CCR_A10_TRADE_IR_ID,
        netting_set_id=CCR_A10_NETTING_SET_ID,
        asset_class=CCR_A10_IR_ASSET_CLASS,
        transaction_type=CCR_A10_IR_TRANSACTION_TYPE,
        notional=CCR_A10_IR_NOTIONAL,
        currency=CCR_A10_IR_CURRENCY,
        maturity_date=CCR_A10_IR_MATURITY_DATE,
        start_date=CCR_A10_IR_START_DATE,
        delta=CCR_A10_IR_DELTA,
        is_long=CCR_A10_IR_IS_LONG,
        mtm_value=CCR_A10_IR_MTM,
    )


def _ccr_a10_fx_trade() -> Trade:
    """Return the FX forward trade for CCR-A10 (clone of CCR-A2 T_FX_001)."""
    return make_fx_trade(
        trade_id=CCR_A10_TRADE_FX_ID,
        netting_set_id=CCR_A10_NETTING_SET_ID,
        asset_class=CCR_A10_FX_ASSET_CLASS,
        transaction_type=CCR_A10_FX_TRANSACTION_TYPE,
        notional=CCR_A10_FX_NOTIONAL_LEG1,
        currency=CCR_A10_FX_CURRENCY_LEG1,
        notional_leg2=CCR_A10_FX_NOTIONAL_LEG2,
        currency_leg2=CCR_A10_FX_CURRENCY_LEG2,
        maturity_date=CCR_A10_FX_MATURITY_DATE,
        start_date=CCR_A10_FX_START_DATE,
        delta=CCR_A10_FX_DELTA,
        is_long=CCR_A10_FX_IS_LONG,
        mtm_value=CCR_A10_FX_MTM,
    )


def _ccr_a10_credit_trade() -> Trade:
    """Return the credit CDS trade for CCR-A10 (clone of CCR-A3 T_CR_001)."""
    return make_credit_trade(
        trade_id=CCR_A10_TRADE_CR_ID,
        netting_set_id=CCR_A10_NETTING_SET_ID,
        asset_class=CCR_A10_CR_ASSET_CLASS,
        transaction_type=CCR_A10_CR_TRANSACTION_TYPE,
        notional=CCR_A10_CR_NOTIONAL,
        currency=CCR_A10_CR_CURRENCY,
        maturity_date=CCR_A10_CR_MATURITY_DATE,
        start_date=CCR_A10_CR_START_DATE,
        delta=CCR_A10_CR_DELTA,
        is_long=CCR_A10_CR_IS_LONG,
        mtm_value=CCR_A10_CR_MTM,
        reference_entity=CCR_A10_CR_REFERENCE_ENTITY,
        is_index=CCR_A10_CR_IS_INDEX,
        credit_quality=CCR_A10_CR_CREDIT_QUALITY,
    )


def _ccr_a10_equity_trade() -> Trade:
    """Return the equity TRS trade for CCR-A10 (clone of CCR-A5 T_EQ_001)."""
    return make_equity_trade(
        trade_id=CCR_A10_TRADE_EQ_ID,
        netting_set_id=CCR_A10_NETTING_SET_ID,
        asset_class=CCR_A10_EQ_ASSET_CLASS,
        transaction_type=CCR_A10_EQ_TRANSACTION_TYPE,
        maturity_date=CCR_A10_EQ_MATURITY_DATE,
        start_date=CCR_A10_EQ_START_DATE,
        delta=CCR_A10_EQ_DELTA,
        is_long=CCR_A10_EQ_IS_LONG,
        mtm_value=CCR_A10_EQ_MTM,
        market_price=CCR_A10_EQ_MARKET_PRICE,
        number_of_units=CCR_A10_EQ_NUMBER_OF_UNITS,
        reference_entity=CCR_A10_EQ_REFERENCE_ENTITY,
        is_index=CCR_A10_EQ_IS_INDEX,
    )


def _ccr_a10_commodity_trade() -> Trade:
    """Return the oil forward trade for CCR-A10 (clone of CCR-A7 T_CO_OIL_001)."""
    return make_commodity_trade(
        trade_id=CCR_A10_TRADE_CO_ID,
        netting_set_id=CCR_A10_NETTING_SET_ID,
        asset_class=CCR_A10_CO_ASSET_CLASS,
        transaction_type=CCR_A10_CO_TRANSACTION_TYPE,
        notional=CCR_A10_CO_NOTIONAL,
        currency=CCR_A10_CO_CURRENCY,
        maturity_date=CCR_A10_CO_MATURITY_DATE,
        start_date=CCR_A10_CO_START_DATE,
        delta=CCR_A10_CO_DELTA,
        is_long=CCR_A10_CO_IS_LONG,
        mtm_value=CCR_A10_CO_MTM,
        market_price=CCR_A10_CO_MARKET_PRICE,
        number_of_units=CCR_A10_CO_NUMBER_OF_UNITS,
        commodity_type=CCR_A10_CO_COMMODITY_TYPE,
    )


def _ccr_a10_netting_set() -> NettingSet:
    """Return the single CCR-A10 netting-set instance (NS_MIX_001)."""
    return NettingSet(
        netting_set_id=CCR_A10_NETTING_SET_ID,
        counterparty_reference=CCR_A10_COUNTERPARTY_REF,
        is_legally_enforceable=CCR_A10_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_A10_IS_MARGINED,
    )


# ---------------------------------------------------------------------------
# DataFrame factories.
# ---------------------------------------------------------------------------


def create_ccr_a10_trades() -> pl.DataFrame:
    """Return the five-row trades DataFrame for CCR-A10 (one per asset class)."""
    return create_trades(
        [
            _ccr_a10_ir_trade(),
            _ccr_a10_fx_trade(),
            _ccr_a10_credit_trade(),
            _ccr_a10_equity_trade(),
            _ccr_a10_commodity_trade(),
        ]
    )


def create_ccr_a10_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CCR-A10."""
    return create_netting_sets([_ccr_a10_netting_set()])


def create_ccr_a10_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-A10: no collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Bundle assembly helpers.
# ---------------------------------------------------------------------------


def _build_ccr_a10_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle from the five CCR-A10 domain frames.

    Composition:
        trades            — 5 rows  (one per asset class, all in NS_MIX_001)
        netting_sets      — 1 row   (NS_MIX_001, CP_001, enforceable, unmargined)
        margin_agreements — 0 rows  (CCR-A10: unmargined, no CSA)
        ccr_collateral    — 0 rows  (CCR-A10: no posted/received collateral)
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=create_ccr_a10_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_ccr_a10_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_ccr_a1_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_ccr_a10_collateral().lazy()),
    )


def build_raw_data_bundle_with_ccr_a10() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle with CCR-A10 (mixed-asset-class) populated.

    Reuses CP_001 (institution, CQS 2, GB) from the CCR-A1 portfolio stub so
    the SA Institution lookup ends in CRR Art. 120(1) Table 3 → 50% RW.
    Includes the fx_rates LazyFrame (USD->GBP = 0.80) required by the FX
    adjusted-notional branch for T_MIX_FX_001 (Art. 279b(1)(b)(i)).

    Key assertion:
        AddOn_aggregate = Σ per-class add-ons = 25_304_132.167317
        This exercises CRR Art. 278(2): the linear cross-asset-class sum with
        no inter-class correlation.
    """
    return make_raw_bundle(
        counterparties=_build_cp_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_001_rating(),
        fx_rates=create_ccr_a2_fx_rates(),
        ccr=_build_ccr_a10_raw_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Save helper — canonical entry point for generate_all.py and standalone use.
# ---------------------------------------------------------------------------


def save_ccr_a10_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write CCR-A10 golden parquet files to *output_dir*.

    Files produced:
        ccr_a10_trades.parquet        — 5 rows  (one per asset class, all NS_MIX_001)
        ccr_a10_netting_sets.parquet  — 1 row   (NS_MIX_001, CP_001, enforceable, unmargined)

    The margin_agreements and ccr_collateral frames are empty and shared with
    CCR-A1; they are not re-written here.

    Args:
        output_dir: Target directory. Defaults to the directory containing
            this script (``tests/fixtures/ccr/``).

    Returns:
        Dict mapping artefact name to saved absolute ``Path``.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("ccr_a10_trades", create_ccr_a10_trades()),
        ("ccr_a10_netting_sets", create_ccr_a10_netting_sets()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_ccr_a10_fixtures()
    print("CCR-A10 golden fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<30} {len(df):>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
    print("-" * 70)
    print("Scenario: CCR-A10 — mixed-asset-class netting set (5 trades), unmargined")
    print(f"  Netting set:  {CCR_A10_NETTING_SET_ID} -> {CCR_A10_COUNTERPARTY_REF}")
    print(f"  Trades:       {CCR_A10_TRADE_IR_ID}  (IR,        add-on={CCR_A10_ADDON_IR:,.3f})")
    print(f"                {CCR_A10_TRADE_FX_ID}  (FX,        add-on={CCR_A10_ADDON_FX:,.3f})")
    print(f"                {CCR_A10_TRADE_CR_ID}  (credit,    add-on={CCR_A10_ADDON_CREDIT:,.3f})")
    print(f"                {CCR_A10_TRADE_EQ_ID}  (equity,    add-on={CCR_A10_ADDON_EQUITY:,.6f})")
    print(
        f"                {CCR_A10_TRADE_CO_ID}  (commodity, add-on={CCR_A10_ADDON_COMMODITY:,.0f})"
    )
    print(f"  addon_aggregate : {CCR_A10_ADDON_AGGREGATE:,.6f}")
    print(f"  EAD (final)     : {CCR_A10_EAD_FINAL:,.6f}")
    print(f"  RWA (final)     : {CCR_A10_RWA_FINAL:,.6f}")


if __name__ == "__main__":
    main()
