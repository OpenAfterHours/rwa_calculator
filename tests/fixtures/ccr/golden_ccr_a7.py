"""
Golden CCR-A7 scenario: single 2-year GBP oil forward, unmargined.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/)
    -> engine-implementer (SA-CCR commodity branch of adjusted notional + PFE add-on)

Scenario design:
    One trade (T_CO_OIL_001): 2-year GBP oil forward, buy 20,000 bbl at
    GBP 50/bbl.  The engine computes adjusted notional as
    ``d = market_price × number_of_units = 50.0 × 20_000.0 = 1_000_000.0``
    per CRR Art. 279b(1)(c).  MtM = 0.0, delta = 1.0, unmargined.
    One netting set (NS_CO_001): counterparty CP_001 (institution, CQS 2, GB),
    legally enforceable (Art. 295), unmargined (CCR-A7 scope).
    Zero collateral: no posted or received collateral.

Regulatory hand-calc (CRR Art. 279b(1)(c) + Art. 277(3)(b) + Art. 278 + 274):

    adjusted_notional = market_price × number_of_units
                      = 50.0 × 20_000.0 = 1_000_000.0 GBP      (Art. 279b(1)(c))

    years_to_maturity = (2028-01-15 - 2026-01-15) / 365.25
                      = 730 / 365.25
                      = 1.998630136...                          (engine convention)

    MF                = sqrt(min(1.998630, 1.0) / 1.0)
                      = sqrt(1.0) = 1.0                         (Art. 279c(1))

    effective_notional = delta × d × MF
                       = 1.0 × 1_000_000.0 × 1.0 = 1_000_000.0

    D_OIL_GAS         = 1_000_000.0                            (single-trade, one bucket)

    AddOn_OIL_GAS     = SF_CM[OIL_GAS] × |D_OIL_GAS|
                      = 0.18 × 1_000_000.0 = 180_000.0         (Art. 280 Table 2)

    AddOn_commodity   = sqrt(180_000²) = 180_000.0             (Art. 280c: single bucket)

    RC                = max(V - C, 0) = max(0 - 0, 0) = 0      (Art. 275(1))

    PFE multiplier    = min(1, 0.05 + 0.95 × exp(0/(2×0.95×AddOn))) = 1.0  (Art. 278(3))

    PFE_addon         = 1.0 × 180_000.0 = 180_000.0 GBP        (Art. 278(1))

    EAD               = alpha × (RC + PFE) = 1.4 × 180_000.0
                      = 252_000.0 GBP                          (Art. 274(2))

    RWA               = EAD × RW = 252_000.0 × 0.50
                      = 126_000.0 GBP                          (Art. 120(1) Table 3)

Counterparty reuse:
    CCR-A7 reuses the CCR-A1 institution counterparty (CP_001, GB, CQS 2) so
    the SA Institution lookup ends in 50% RW. The counterparty/rating builders
    are imported from ``golden_ccr_a1`` directly.

References:
    - CRR Art. 271 (CCR scope)
    - CRR Art. 274(2) (EAD = alpha × (RC + PFE), alpha = 1.4)
    - CRR Art. 275(1) (unmargined RC = max(V - C, 0))
    - CRR Art. 277(3)(b) (5 commodity buckets)
    - CRR Art. 277a(1) (commodity add-on aggregation)
    - CRR Art. 278 (PFE multiplier + PFE add-on composition)
    - CRR Art. 279b(1)(c) (commodity adjusted notional d = mp × units)
    - CRR Art. 279c(1) (unmargined MF = sqrt(min(M, 1y) / 1y))
    - CRR Art. 280 Table 2 (SF_CM: OIL_GAS = 0.18)
    - CRR Art. 280c (commodity asset-class add-on)
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
# Scenario constants — single source of truth for CCR-A7 test assertions.
# ---------------------------------------------------------------------------

CCR_A7_TRADE_ID: str = "T_CO_OIL_001"
CCR_A7_NETTING_SET_ID: str = "NS_CO_001"
CCR_A7_COUNTERPARTY_REF: str = "CP_001"  # reuse CCR-A1 institution CP

CCR_A7_ASSET_CLASS: str = "commodity"
CCR_A7_TRANSACTION_TYPE: str = "derivative"
CCR_A7_COMMODITY_TYPE: str = "OIL_GAS"  # UPPER-CASE per COLUMN_VALUE_CONSTRAINTS

# Oil forward: buy 20,000 bbl at GBP 50/bbl.
# Engine computes d = market_price × number_of_units = 50.0 × 20_000.0 = 1_000_000.0
CCR_A7_NOTIONAL: float = 1_000_000.0  # sentinel — equals expected d value
CCR_A7_CURRENCY: str = "GBP"
CCR_A7_MARKET_PRICE: float = 50.0  # GBP per bbl
CCR_A7_NUMBER_OF_UNITS: float = 20_000.0  # bbl

CCR_A7_MTM: float = 0.0
CCR_A7_DELTA: float = 1.0
CCR_A7_IS_LONG: bool = True

# 2-year tenor: 2026-01-15 start, 2028-01-15 maturity.
CCR_A7_START_DATE: _date = _date(2026, 1, 15)
CCR_A7_MATURITY_DATE: _date = _date(2028, 1, 15)

CCR_A7_IS_LEGALLY_ENFORCEABLE: bool = True
CCR_A7_IS_MARGINED: bool = False

# ---------------------------------------------------------------------------
# Expected output constants — hand-calculated per CRR Art. 279b/277/278/274.
# ---------------------------------------------------------------------------

# d = 50.0 × 20_000.0 = 1_000_000.0                    [Art. 279b(1)(c)]
CCR_A7_ADJUSTED_NOTIONAL: float = 1_000_000.0

# MF = sqrt(min(1.998630, 1) / 1) = sqrt(1) = 1.0       [Art. 279c(1)]
CCR_A7_MF: float = 1.0

# RC = max(0 - 0, 0) = 0                                 [Art. 275(1)]
CCR_A7_RC: float = 0.0

# AddOn_OIL_GAS = 0.18 × 1_000_000 = 180_000            [SF_CM × |D_b|]
CCR_A7_ADDON_AGGREGATE: float = 180_000.0

# PFE multiplier = 1.0 (V = C = 0)                       [Art. 278(3)]
CCR_A7_PFE_MULTIPLIER: float = 1.0

# PFE_addon = 1.0 × 180_000 = 180_000                    [Art. 278(1)]
CCR_A7_PFE_ADDON: float = 180_000.0

# EAD = 1.4 × (0 + 180_000) = 252_000                   [Art. 274(2)]
CCR_A7_EAD: float = 252_000.0

# SA risk weight: institution CQS 2 → 50%               [Art. 120(1) Table 3]
CCR_A7_RISK_WEIGHT: float = 0.50

# RWA = 252_000 × 0.50 = 126_000
CCR_A7_RWA: float = 126_000.0

CCR_A7_EXPOSURE_CLASS: str = "institution"


# ---------------------------------------------------------------------------
# CCR-A7 trade + netting-set builders.
# ---------------------------------------------------------------------------


def _ccr_a7_trade() -> Trade:
    """Return the single CCR-A7 oil-forward trade instance."""
    return make_commodity_trade(
        trade_id=CCR_A7_TRADE_ID,
        netting_set_id=CCR_A7_NETTING_SET_ID,
        asset_class=CCR_A7_ASSET_CLASS,
        transaction_type=CCR_A7_TRANSACTION_TYPE,
        notional=CCR_A7_NOTIONAL,
        currency=CCR_A7_CURRENCY,
        maturity_date=CCR_A7_MATURITY_DATE,
        start_date=CCR_A7_START_DATE,
        delta=CCR_A7_DELTA,
        is_long=CCR_A7_IS_LONG,
        mtm_value=CCR_A7_MTM,
        market_price=CCR_A7_MARKET_PRICE,
        number_of_units=CCR_A7_NUMBER_OF_UNITS,
        commodity_type=CCR_A7_COMMODITY_TYPE,
    )


def _ccr_a7_netting_set() -> NettingSet:
    """Return the single CCR-A7 netting-set instance."""
    return NettingSet(
        netting_set_id=CCR_A7_NETTING_SET_ID,
        counterparty_reference=CCR_A7_COUNTERPARTY_REF,
        is_legally_enforceable=CCR_A7_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_A7_IS_MARGINED,
    )


def create_ccr_a7_trades() -> pl.DataFrame:
    """Return the single-row trades DataFrame for CCR-A7."""
    return create_trades([_ccr_a7_trade()])


def create_ccr_a7_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CCR-A7."""
    return create_netting_sets([_ccr_a7_netting_set()])


def create_ccr_a7_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-A7: no collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


def _build_ccr_a7_raw_ccr_bundle() -> RawCCRBundle:
    """Assemble the RawCCRBundle from the CCR-A7 domain frames."""
    return RawCCRBundle(
        trades=TradeBundle(trades=create_ccr_a7_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_ccr_a7_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_ccr_a1_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_ccr_a7_collateral().lazy()),
    )


def build_raw_data_bundle_with_ccr_a7() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle with CCR-A7 (oil forward) populated.

    Reuses CP_001 (institution, CQS 2, GB) from the CCR-A1 portfolio stub so
    the SA Institution lookup ends in CRR Art. 120(1) Table 3 → 50% RW.
    No fx_rates table required — commodity adjusted notional uses
    market_price × number_of_units (both already in GBP) per Art. 279b(1)(c).
    """
    return make_raw_bundle(
        counterparties=_build_cp_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_001_rating(),
        ccr=_build_ccr_a7_raw_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Save helper — entry point for generate_all.py.
# ---------------------------------------------------------------------------


def save_ccr_a7_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write CCR-A7 golden parquet files to *output_dir*.

    Files produced:
        ccr_a7_trades.parquet         — 1 row  (T_CO_OIL_001, 2y GBP oil forward)
        ccr_a7_netting_sets.parquet   — 1 row  (NS_CO_001, CP_001, enforceable, unmargined)

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
        ("ccr_a7_trades", create_ccr_a7_trades()),
        ("ccr_a7_netting_sets", create_ccr_a7_netting_sets()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved
