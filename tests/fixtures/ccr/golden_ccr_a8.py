"""
Golden CCR-A8 scenario: single 1-year GBP electricity swap, unmargined.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/)
    -> engine-implementer (SA-CCR commodity branch of adjusted notional + PFE add-on)

Scenario design:
    One trade (T_CO_ELEC_001): 1-year GBP electricity swap, 40,000 MWh at
    GBP 25/MWh.  The engine computes adjusted notional as
    ``d = market_price × number_of_units = 25.0 × 40_000.0 = 1_000_000.0``
    per CRR Art. 279b(1)(c).  MtM = 0.0, delta = 1.0, unmargined.
    One netting set (NS_CO_002): counterparty CP_001 (institution, CQS 2, GB),
    legally enforceable (Art. 295), unmargined (CCR-A8 scope).
    Zero collateral: no posted or received collateral.

Regulatory hand-calc (CRR Art. 279b(1)(c) + Art. 277(3)(b) + Art. 278 + 274):

    adjusted_notional = market_price × number_of_units
                      = 25.0 × 40_000.0 = 1_000_000.0 GBP      (Art. 279b(1)(c))

    years_to_maturity = (2027-01-15 - 2026-01-15) / 365.25
                      = 365 / 365.25
                      = 0.999315537...                          (engine convention)

    MF                = sqrt(min(0.999315537, 1.0) / 1.0)
                      = sqrt(0.999315537)
                      ≈ 0.999657706...                          (Art. 279c(1))

    effective_notional = delta × d × MF
                       = 1.0 × 1_000_000.0 × 0.999657706
                       ≈ 999_657.706 GBP

    D_ELECTRICITY     = 999_657.706                             (single-trade, one bucket)

    AddOn_ELECTRICITY = SF_CM[ELECTRICITY] × |D_ELECTRICITY|
                      = 0.40 × 999_657.706                     (Art. 280 Table 2)
                      ≈ 399_863.080 GBP

    AddOn_commodity   ≈ 399_863.080 GBP                        (Art. 280c: single bucket)

    RC                = max(V - C, 0) = max(0 - 0, 0) = 0      (Art. 275(1))

    PFE multiplier    = min(1, 0.05 + 0.95 × exp(0/(2×0.95×AddOn))) = 1.0  (Art. 278(3))

    PFE_addon         ≈ 399_863.080 GBP                        (Art. 278(1))

    EAD               = alpha × (RC + PFE) = 1.4 × 399_863.080
                      ≈ 559_808.312 GBP                        (Art. 274(2))

    RWA               = EAD × RW = 559_808.312 × 0.50
                      ≈ 279_904.156 GBP                        (Art. 120(1) Table 3)

Load-bearing assertion:
    ELECTRICITY uses SF_CM = 0.40 (not the 0.18 catch-all for OIL_GAS/METALS/etc.).
    Comparing CCR-A8 AddOn (≈399_863) vs CCR-A7 AddOn (180_000) with equal
    adjusted notionals (1_000_000) confirms the electricity-specific SF is applied.

Counterparty reuse:
    CCR-A8 reuses the CCR-A1 institution counterparty (CP_001, GB, CQS 2) so
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
    - CRR Art. 280 Table 2 (SF_CM: ELECTRICITY = 0.40)
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
# Scenario constants — single source of truth for CCR-A8 test assertions.
# ---------------------------------------------------------------------------

CCR_A8_TRADE_ID: str = "T_CO_ELEC_001"
CCR_A8_NETTING_SET_ID: str = "NS_CO_002"
CCR_A8_COUNTERPARTY_REF: str = "CP_001"  # reuse CCR-A1 institution CP

CCR_A8_ASSET_CLASS: str = "commodity"
CCR_A8_TRANSACTION_TYPE: str = "derivative"
CCR_A8_COMMODITY_TYPE: str = "ELECTRICITY"  # UPPER-CASE per COLUMN_VALUE_CONSTRAINTS

# Electricity swap: 40,000 MWh at GBP 25/MWh.
# Engine computes d = market_price × number_of_units = 25.0 × 40_000.0 = 1_000_000.0
CCR_A8_NOTIONAL: float = 1_000_000.0  # sentinel — equals expected d value
CCR_A8_CURRENCY: str = "GBP"
CCR_A8_MARKET_PRICE: float = 25.0  # GBP per MWh
CCR_A8_NUMBER_OF_UNITS: float = 40_000.0  # MWh

CCR_A8_MTM: float = 0.0
CCR_A8_DELTA: float = 1.0
CCR_A8_IS_LONG: bool = True

# 1-year tenor: 2026-01-15 start, 2027-01-15 maturity.
CCR_A8_START_DATE: _date = _date(2026, 1, 15)
CCR_A8_MATURITY_DATE: _date = _date(2027, 1, 15)

CCR_A8_IS_LEGALLY_ENFORCEABLE: bool = True
CCR_A8_IS_MARGINED: bool = False

# ---------------------------------------------------------------------------
# Expected output constants — hand-calculated per CRR Art. 279b/277/278/274.
# ---------------------------------------------------------------------------

# d = 25.0 × 40_000.0 = 1_000_000.0                    [Art. 279b(1)(c)]
CCR_A8_ADJUSTED_NOTIONAL: float = 1_000_000.0

# years_to_maturity = 365 / 365.25 = 0.999315537...
# MF = sqrt(0.999315537) = 0.999657706...               [Art. 279c(1)]
# e_i = 1.0 × 1_000_000.0 × 0.999657706 = 999_657.706...
# D_ELECTRICITY = 999_657.706...
# AddOn = 0.40 × 999_657.706 = 399_863.080...           [SF_CM ELECTRICITY = 0.40]
CCR_A8_ADDON_AGGREGATE: float = 399_863.080  # rounded to 3 dp for test tolerance

# RC = max(0 - 0, 0) = 0                                [Art. 275(1)]
CCR_A8_RC: float = 0.0

# PFE multiplier = 1.0 (V = C = 0)                     [Art. 278(3)]
CCR_A8_PFE_MULTIPLIER: float = 1.0

# PFE_addon = 1.0 × 399_863.080 = 399_863.080          [Art. 278(1)]
CCR_A8_PFE_ADDON: float = 399_863.080

# EAD = 1.4 × 399_863.080 = 559_808.312                [Art. 274(2)]
CCR_A8_EAD: float = 559_808.312

# SA risk weight: institution CQS 2 → 50%               [Art. 120(1) Table 3]
CCR_A8_RISK_WEIGHT: float = 0.50

# RWA = 559_808.312 × 0.50 = 279_904.156
CCR_A8_RWA: float = 279_904.156

CCR_A8_EXPOSURE_CLASS: str = "institution"


# ---------------------------------------------------------------------------
# CCR-A8 trade + netting-set builders.
# ---------------------------------------------------------------------------


def _ccr_a8_trade() -> Trade:
    """Return the single CCR-A8 electricity-swap trade instance."""
    return make_commodity_trade(
        trade_id=CCR_A8_TRADE_ID,
        netting_set_id=CCR_A8_NETTING_SET_ID,
        asset_class=CCR_A8_ASSET_CLASS,
        transaction_type=CCR_A8_TRANSACTION_TYPE,
        notional=CCR_A8_NOTIONAL,
        currency=CCR_A8_CURRENCY,
        maturity_date=CCR_A8_MATURITY_DATE,
        start_date=CCR_A8_START_DATE,
        delta=CCR_A8_DELTA,
        is_long=CCR_A8_IS_LONG,
        mtm_value=CCR_A8_MTM,
        market_price=CCR_A8_MARKET_PRICE,
        number_of_units=CCR_A8_NUMBER_OF_UNITS,
        commodity_type=CCR_A8_COMMODITY_TYPE,
    )


def _ccr_a8_netting_set() -> NettingSet:
    """Return the single CCR-A8 netting-set instance."""
    return NettingSet(
        netting_set_id=CCR_A8_NETTING_SET_ID,
        counterparty_reference=CCR_A8_COUNTERPARTY_REF,
        is_legally_enforceable=CCR_A8_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_A8_IS_MARGINED,
    )


def create_ccr_a8_trades() -> pl.DataFrame:
    """Return the single-row trades DataFrame for CCR-A8."""
    return create_trades([_ccr_a8_trade()])


def create_ccr_a8_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CCR-A8."""
    return create_netting_sets([_ccr_a8_netting_set()])


def create_ccr_a8_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-A8: no collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


def _build_ccr_a8_raw_ccr_bundle() -> RawCCRBundle:
    """Assemble the RawCCRBundle from the CCR-A8 domain frames."""
    return RawCCRBundle(
        trades=TradeBundle(trades=create_ccr_a8_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_ccr_a8_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_ccr_a1_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_ccr_a8_collateral().lazy()),
    )


def build_raw_data_bundle_with_ccr_a8() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle with CCR-A8 (electricity swap) populated.

    Reuses CP_001 (institution, CQS 2, GB) from the CCR-A1 portfolio stub so
    the SA Institution lookup ends in CRR Art. 120(1) Table 3 → 50% RW.
    No fx_rates table required — commodity adjusted notional uses
    market_price × number_of_units (both already in GBP) per Art. 279b(1)(c).

    Load-bearing: the ELECTRICITY SF_CM = 0.40 (not the 0.18 catch-all) is
    the discriminating assertion for this scenario vs CCR-A7.
    """
    return RawDataBundle(
        counterparties=_build_cp_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_001_rating(),
        ccr=_build_ccr_a8_raw_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Save helper — entry point for generate_all.py.
# ---------------------------------------------------------------------------


def save_ccr_a8_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write CCR-A8 golden parquet files to *output_dir*.

    Files produced:
        ccr_a8_trades.parquet         — 1 row  (T_CO_ELEC_001, 1y GBP electricity swap)
        ccr_a8_netting_sets.parquet   — 1 row  (NS_CO_002, CP_001, enforceable, unmargined)

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
        ("ccr_a8_trades", create_ccr_a8_trades()),
        ("ccr_a8_netting_sets", create_ccr_a8_netting_sets()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved
