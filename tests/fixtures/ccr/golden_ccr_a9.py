"""
Golden CCR-A9 scenario: multi-bucket commodity netting set — three trades across
OIL_GAS, METALS, and ELECTRICITY buckets, unmargined.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/)
    -> engine-implementer (SA-CCR commodity cross-bucket sqrt aggregation)

Scenario design:
    Three trades share netting set NS_CO_003, counterparty CP_001
    (institution, CQS 2, GB), legally enforceable (Art. 295), unmargined.
    All trades have the same 2-year tenor (start_date=2026-01-15,
    maturity_date=2028-01-15) so that MF = sqrt(min(M, 1y)/1y) = 1.0 for
    every trade.  Zero MtM and zero collateral.

    | trade_id      | commodity_type | market_price | number_of_units | notional   |
    |---------------|----------------|--------------|-----------------|------------|
    | T_CO_OIL_002  | OIL_GAS        |        50.0  |        20_000.0 | 1_000_000  |
    | T_CO_MET_001  | METALS         |     8_000.0  |           250.0 | 2_000_000  |
    | T_CO_ELEC_002 | ELECTRICITY    |        25.0  |        40_000.0 | 1_000_000  |

Load-bearing target:
    Art. 280c / CRE52.69 cross-bucket aggregation:

        AddOn_OIL_GAS   = 0.18 × 1_000_000.0 = 180_000.0
        AddOn_METALS    = 0.18 × 2_000_000.0 = 360_000.0
        AddOn_ELECTRICITY = 0.40 × 1_000_000.0 = 400_000.0
        AddOn_commodity = sqrt(180_000² + 360_000² + 400_000²)
                        = sqrt(322_000_000_000)
                        ≈ 567_450.441

    This is the discriminating assertion: a single-bucket scenario (CCR-A7 or
    CCR-A8) cannot exercise cross-bucket aggregation; CCR-A9 is the first
    scenario to do so.

Regulatory hand-calc (CRR Art. 279b(1)(c) + Art. 277(3)(b) + Art. 280c + Art. 274):

    OIL_GAS trade:
    adjusted_notional  = 50.0 × 20_000.0 = 1_000_000.0 GBP    (Art. 279b(1)(c))
    years_to_maturity  = 730 / 365.25 = 1.998630136...
    MF                 = sqrt(min(1.998630, 1.0) / 1.0) = 1.0  (Art. 279c(1))
    effective_notional = 1.0 × 1_000_000.0 × 1.0 = 1_000_000.0
    AddOn_OIL_GAS      = 0.18 × 1_000_000.0 = 180_000.0        (SF_CM OIL_GAS=0.18)

    METALS trade:
    adjusted_notional  = 8_000.0 × 250.0 = 2_000_000.0 GBP    (Art. 279b(1)(c))
    MF = 1.0
    effective_notional = 1.0 × 2_000_000.0 × 1.0 = 2_000_000.0
    AddOn_METALS       = 0.18 × 2_000_000.0 = 360_000.0        (SF_CM METALS=0.18)

    ELECTRICITY trade:
    adjusted_notional  = 25.0 × 40_000.0 = 1_000_000.0 GBP    (Art. 279b(1)(c))
    MF = 1.0
    effective_notional = 1.0 × 1_000_000.0 × 1.0 = 1_000_000.0
    AddOn_ELECTRICITY  = 0.40 × 1_000_000.0 = 400_000.0        (SF_CM ELECTRICITY=0.40)

    Cross-bucket (Art. 280c: no cross-bucket correlation, CRE52.69):
    AddOn_commodity = sqrt(180_000² + 360_000² + 400_000²)
                    = sqrt(32_400_000_000 + 129_600_000_000 + 160_000_000_000)
                    = sqrt(322_000_000_000)
                    ≈ 567_450.4405846...

    RC  = max(V - C, 0) = max(0 - 0, 0) = 0                    (Art. 275(1))
    PFE multiplier = 1.0 (V = C = 0)                           (Art. 278(3))
    PFE_addon = 1.0 × 567_450.441 ≈ 567_450.441               (Art. 278(1))
    EAD = 1.4 × (0 + 567_450.441) ≈ 794_430.617               (Art. 274(2))
    RWA = 794_430.617 × 0.50 ≈ 397_215.308                    (Art. 120(1) Table 3)

Counterparty reuse:
    CCR-A9 reuses the CCR-A1 institution counterparty (CP_001, GB, CQS 2) so
    the SA Institution lookup ends in 50% RW.  The counterparty/rating builders
    are imported from ``golden_ccr_a1`` directly.

References:
    - CRR Art. 271 (CCR scope)
    - CRR Art. 274(2) (EAD = alpha × (RC + PFE), alpha = 1.4)
    - CRR Art. 275(1) (unmargined RC = max(V - C, 0))
    - CRR Art. 277(3)(b) (5 commodity buckets — UPPER-CASE)
    - CRR Art. 277a(1) (commodity add-on aggregation)
    - CRR Art. 278 (PFE multiplier + PFE add-on composition)
    - CRR Art. 279b(1)(c) (commodity adjusted notional d = mp × units)
    - CRR Art. 279c(1) (unmargined MF = sqrt(min(M, 1y) / 1y))
    - CRR Art. 280 Table 2 (SF_CM: OIL_GAS/METALS=0.18, ELECTRICITY=0.40)
    - CRR Art. 280c (commodity asset-class add-on, cross-bucket sqrt aggregation)
    - CRR Art. 120(1) Table 3 (institution CQS 2 SA risk weight = 50%)
    - BCBS CRE52.46-48, CRE52.67-69
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
from .netting_set_builder import NettingSet, create_netting_sets
from .trade_builder import Trade, create_trades, make_commodity_trade

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for CCR-A9 test assertions.
# ---------------------------------------------------------------------------

CCR_A9_NETTING_SET_ID: str = "NS_CO_003"
CCR_A9_COUNTERPARTY_REF: str = "CP_001"  # reuse CCR-A1 institution CP

CCR_A9_ASSET_CLASS: str = "commodity"
CCR_A9_TRANSACTION_TYPE: str = "derivative"
CCR_A9_CURRENCY: str = "GBP"

# Trade 1 — OIL_GAS bucket
CCR_A9_TRADE_OIL_ID: str = "T_CO_OIL_002"
CCR_A9_COMMODITY_TYPE_OIL: str = "OIL_GAS"  # UPPER-CASE per COLUMN_VALUE_CONSTRAINTS
CCR_A9_MARKET_PRICE_OIL: float = 50.0  # GBP per bbl
CCR_A9_UNITS_OIL: float = 20_000.0  # bbl
CCR_A9_NOTIONAL_OIL: float = 1_000_000.0  # sentinel = expected d = 50.0 × 20_000.0

# Trade 2 — METALS bucket
CCR_A9_TRADE_MET_ID: str = "T_CO_MET_001"
CCR_A9_COMMODITY_TYPE_MET: str = "METALS"  # UPPER-CASE per COLUMN_VALUE_CONSTRAINTS
CCR_A9_MARKET_PRICE_MET: float = 8_000.0  # GBP per troy oz (gold-style)
CCR_A9_UNITS_MET: float = 250.0  # troy oz
CCR_A9_NOTIONAL_MET: float = 2_000_000.0  # sentinel = expected d = 8_000.0 × 250.0

# Trade 3 — ELECTRICITY bucket
CCR_A9_TRADE_ELEC_ID: str = "T_CO_ELEC_002"
CCR_A9_COMMODITY_TYPE_ELEC: str = "ELECTRICITY"  # UPPER-CASE per COLUMN_VALUE_CONSTRAINTS
CCR_A9_MARKET_PRICE_ELEC: float = 25.0  # GBP per MWh
CCR_A9_UNITS_ELEC: float = 40_000.0  # MWh
CCR_A9_NOTIONAL_ELEC: float = 1_000_000.0  # sentinel = expected d = 25.0 × 40_000.0

# Shared trade fields
CCR_A9_MTM: float = 0.0
CCR_A9_DELTA: float = 1.0
CCR_A9_IS_LONG: bool = True

# 2-year tenor: 2026-01-15 start, 2028-01-15 maturity.
# MF = sqrt(min(~1.9986, 1.0) / 1.0) = sqrt(1.0) = 1.0 per Art. 279c(1).
CCR_A9_START_DATE: _date = _date(2026, 1, 15)
CCR_A9_MATURITY_DATE: _date = _date(2028, 1, 15)

CCR_A9_IS_LEGALLY_ENFORCEABLE: bool = True
CCR_A9_IS_MARGINED: bool = False

# ---------------------------------------------------------------------------
# Expected output constants — hand-calculated per CRR Art. 279b/277/280c/274.
# ---------------------------------------------------------------------------

# OIL_GAS:    d = 50.0 × 20_000.0 = 1_000_000.0,  MF=1.0, AddOn = 0.18 × 1_000_000.0
CCR_A9_ADJUSTED_NOTIONAL_OIL: float = 1_000_000.0
CCR_A9_ADDON_OIL: float = 180_000.0  # SF_CM[OIL_GAS]=0.18 × 1_000_000.0

# METALS:     d = 8_000.0 × 250.0 = 2_000_000.0,  MF=1.0, AddOn = 0.18 × 2_000_000.0
CCR_A9_ADJUSTED_NOTIONAL_MET: float = 2_000_000.0
CCR_A9_ADDON_MET: float = 360_000.0  # SF_CM[METALS]=0.18 × 2_000_000.0

# ELECTRICITY: d = 25.0 × 40_000.0 = 1_000_000.0, MF=1.0, AddOn = 0.40 × 1_000_000.0
CCR_A9_ADJUSTED_NOTIONAL_ELEC: float = 1_000_000.0
CCR_A9_ADDON_ELEC: float = 400_000.0  # SF_CM[ELECTRICITY]=0.40 × 1_000_000.0

# Cross-bucket Art. 280c / CRE52.69: sqrt(sum_b AddOn_b²)
# sqrt(180_000² + 360_000² + 400_000²)
# = sqrt(32_400_000_000 + 129_600_000_000 + 160_000_000_000)
# = sqrt(322_000_000_000)
# ≈ 567_450.4405846...
CCR_A9_ADDON_AGGREGATE: float = 567_450.441  # rounded to 3 dp for test tolerance

# RC = max(V - C, 0) = max(0 - 0, 0) = 0                       [Art. 275(1)]
CCR_A9_RC: float = 0.0

# PFE multiplier = 1.0 (V = C = 0)                             [Art. 278(3)]
CCR_A9_PFE_MULTIPLIER: float = 1.0

# PFE_addon = 1.0 × 567_450.441 = 567_450.441                  [Art. 278(1)]
CCR_A9_PFE_ADDON: float = 567_450.441

# EAD = 1.4 × (0 + 567_450.441) = 794_430.617                  [Art. 274(2)]
CCR_A9_EAD: float = 794_430.617

# SA risk weight: institution CQS 2 → 50%                      [Art. 120(1) Table 3]
CCR_A9_RISK_WEIGHT: float = 0.50

# RWA = 794_430.617 × 0.50 = 397_215.308
CCR_A9_RWA: float = 397_215.308

CCR_A9_EXPOSURE_CLASS: str = "institution"


# ---------------------------------------------------------------------------
# CCR-A9 trade + netting-set builders.
# ---------------------------------------------------------------------------


def _ccr_a9_oil_trade() -> Trade:
    """Return the OIL_GAS trade for netting set NS_CO_003."""
    return make_commodity_trade(
        trade_id=CCR_A9_TRADE_OIL_ID,
        netting_set_id=CCR_A9_NETTING_SET_ID,
        asset_class=CCR_A9_ASSET_CLASS,
        transaction_type=CCR_A9_TRANSACTION_TYPE,
        notional=CCR_A9_NOTIONAL_OIL,
        currency=CCR_A9_CURRENCY,
        maturity_date=CCR_A9_MATURITY_DATE,
        start_date=CCR_A9_START_DATE,
        delta=CCR_A9_DELTA,
        is_long=CCR_A9_IS_LONG,
        mtm_value=CCR_A9_MTM,
        market_price=CCR_A9_MARKET_PRICE_OIL,
        number_of_units=CCR_A9_UNITS_OIL,
        commodity_type=CCR_A9_COMMODITY_TYPE_OIL,
    )


def _ccr_a9_metals_trade() -> Trade:
    """Return the METALS trade for netting set NS_CO_003."""
    return make_commodity_trade(
        trade_id=CCR_A9_TRADE_MET_ID,
        netting_set_id=CCR_A9_NETTING_SET_ID,
        asset_class=CCR_A9_ASSET_CLASS,
        transaction_type=CCR_A9_TRANSACTION_TYPE,
        notional=CCR_A9_NOTIONAL_MET,
        currency=CCR_A9_CURRENCY,
        maturity_date=CCR_A9_MATURITY_DATE,
        start_date=CCR_A9_START_DATE,
        delta=CCR_A9_DELTA,
        is_long=CCR_A9_IS_LONG,
        mtm_value=CCR_A9_MTM,
        market_price=CCR_A9_MARKET_PRICE_MET,
        number_of_units=CCR_A9_UNITS_MET,
        commodity_type=CCR_A9_COMMODITY_TYPE_MET,
    )


def _ccr_a9_electricity_trade() -> Trade:
    """Return the ELECTRICITY trade for netting set NS_CO_003."""
    return make_commodity_trade(
        trade_id=CCR_A9_TRADE_ELEC_ID,
        netting_set_id=CCR_A9_NETTING_SET_ID,
        asset_class=CCR_A9_ASSET_CLASS,
        transaction_type=CCR_A9_TRANSACTION_TYPE,
        notional=CCR_A9_NOTIONAL_ELEC,
        currency=CCR_A9_CURRENCY,
        maturity_date=CCR_A9_MATURITY_DATE,
        start_date=CCR_A9_START_DATE,
        delta=CCR_A9_DELTA,
        is_long=CCR_A9_IS_LONG,
        mtm_value=CCR_A9_MTM,
        market_price=CCR_A9_MARKET_PRICE_ELEC,
        number_of_units=CCR_A9_UNITS_ELEC,
        commodity_type=CCR_A9_COMMODITY_TYPE_ELEC,
    )


def _ccr_a9_netting_set() -> NettingSet:
    """Return the single CCR-A9 netting-set instance."""
    return NettingSet(
        netting_set_id=CCR_A9_NETTING_SET_ID,
        counterparty_reference=CCR_A9_COUNTERPARTY_REF,
        is_legally_enforceable=CCR_A9_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_A9_IS_MARGINED,
    )


def create_ccr_a9_trades() -> pl.DataFrame:
    """Return the three-row trades DataFrame for CCR-A9 (OIL_GAS, METALS, ELECTRICITY)."""
    return create_trades(
        [
            _ccr_a9_oil_trade(),
            _ccr_a9_metals_trade(),
            _ccr_a9_electricity_trade(),
        ]
    )


def create_ccr_a9_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CCR-A9."""
    return create_netting_sets([_ccr_a9_netting_set()])


def create_ccr_a9_margin_agreements() -> pl.DataFrame:
    """Return an empty margin-agreements DataFrame (CCR-A9: unmargined)."""
    return create_ccr_a1_margin_agreements()


def create_ccr_a9_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-A9: no collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


def _build_ccr_a9_raw_ccr_bundle() -> RawCCRBundle:
    """Assemble the RawCCRBundle from the CCR-A9 domain frames."""
    return RawCCRBundle(
        trades=TradeBundle(trades=create_ccr_a9_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_ccr_a9_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_ccr_a9_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_ccr_a9_collateral().lazy()),
    )


def build_ccr_a9_bundle() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle with the CCR-A9 three-trade commodity netting set.

    Three commodity trades (OIL_GAS, METALS, ELECTRICITY) sit in a single
    netting set NS_CO_003 against CP_001 (institution, CQS 2, GB).  The
    load-bearing assertion is the Art. 280c / CRE52.69 cross-bucket sqrt
    aggregation:

        AddOn_commodity = sqrt(180_000² + 360_000² + 400_000²) ≈ 567_450.441

    Reuses CP_001 from the CCR-A1 portfolio stub so the SA Institution lookup
    ends in CRR Art. 120(1) Table 3 → 50% RW.
    """
    return make_raw_bundle(
        counterparties=_build_cp_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_001_rating(),
        ccr=_build_ccr_a9_raw_ccr_bundle(),
    )


# Canonical alias — matches the build_raw_data_bundle_with_ccr_a* naming used by siblings.
def build_raw_data_bundle_with_ccr_a9() -> RawDataBundle:
    """Alias for ``build_ccr_a9_bundle()`` — canonical naming for sibling CCR scenarios."""
    return build_ccr_a9_bundle()


# ---------------------------------------------------------------------------
# Save helper — entry point for generate_all.py.
# ---------------------------------------------------------------------------


def save_ccr_a9_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write CCR-A9 golden parquet files to *output_dir*.

    Files produced:
        ccr_a9_trades.parquet        — 3 rows  (T_CO_OIL_002, T_CO_MET_001, T_CO_ELEC_002)
        ccr_a9_netting_sets.parquet  — 1 row   (NS_CO_003, CP_001, enforceable, unmargined)

    Args:
        output_dir: Target directory.  Defaults to the directory containing
            this script (``tests/fixtures/ccr/``).

    Returns:
        Dict mapping artefact name to saved absolute ``Path``.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("ccr_a9_trades", create_ccr_a9_trades()),
        ("ccr_a9_netting_sets", create_ccr_a9_netting_sets()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved
