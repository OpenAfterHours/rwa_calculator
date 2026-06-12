"""
Golden CCR-A2 scenario: single 1-year GBP/USD outright FX forward, unmargined.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/)
    -> engine-implementer (SA-CCR FX branch of adjusted notional + PFE add-on)

Scenario design:
    One trade (T_FX_001): 1-year GBP/USD outright FX forward.
        leg1: buy  USD 100m (currency="USD", notional=100_000_000)
        leg2: sell GBP  80m (currency_leg2="GBP", notional_leg2=80_000_000)
        Forward rate implied = 100m USD / 80m GBP = 1.25 USD/GBP.
        MtM = 0.0 (at-par at the reporting date), delta = 1.0 (linear long).
    One netting set (NS_FX_001): counterparty CP_001 (institution, CQS 2, GB),
        legally enforceable (Art. 295), unmargined (CCR-A2 scope).
    FX rates: spot USD->GBP = 0.80 (and EUR->GBP = 0.85 as unused decoration).

Regulatory hand-calc (CRR Art. 279b(1)(b)(i) + Art. 277a(2) + Art. 278 + 274):

    adjusted_notional = |notional_leg1| * rate_USD_to_GBP
                      = 100m * 0.80 = 80m GBP                  (Art. 279b(1)(b)(i))

    years_to_maturity = (2027-01-15 - 2026-01-15) / 365.25
                      = 365 / 365.25
                      = 0.99931553723477...                    (engine convention)

    MF                = sqrt(min(years_to_maturity, 1.0) / 1.0)
                      = sqrt(0.99931553723477) ≈ 0.99965770... (Art. 279c(1))

    effective_notional = delta * adjusted_notional * MF
                       = 1.0 * 80m * 0.99965770...
                       ≈ 79_972_616.13 GBP

    AddOn_HS_FX       = SF_FX * |D_HS|
                      = 0.04 * 79_972_616.13
                      ≈ 3_198_904.65 GBP                       (Art. 277a(2), CRE52.55)

    AddOn_FX (one HS) ≈ 3_198_904.65 GBP

    RC                = max(V - C, 0) = max(0 - 0, 0) = 0      (Art. 275(1))

    PFE multiplier    = min(1, 0.05 + 0.95 * exp(0 / (2*0.95*AddOn_aggregate)))
                      = min(1, 0.05 + 0.95 * 1.0) = 1.0         (Art. 278(3))

    PFE_addon         = 1.0 * 3_198_904.65 ≈ 3_198_904.65 GBP   (Art. 278(1))

    EAD               = alpha * (RC + PFE) = 1.4 * 3_198_904.65
                      ≈ 4_478_466.51 GBP                       (Art. 274(2))

    RWA               = EAD * RW = 4_478_466.51 * 0.50
                      ≈ 2_239_233.26 GBP                       (Art. 120(1) Table 3)

Counterparty reuse:
    CCR-A2 reuses the CCR-A1 institution counterparty (CP_001, GB, CQS 2) and
    its external rating row so the SA Institution lookup ends in 50% RW. The
    counterparty/rating builders are imported from ``golden_ccr_a1`` directly.

References:
    - CRR Art. 271 (CCR scope)
    - CRR Art. 274(2) (EAD = alpha * (RC + PFE), alpha = 1.4)
    - CRR Art. 275(1) (unmargined RC = max(V - C, 0))
    - CRR Art. 277(3)(a) (FX hedging set = currency pair)
    - CRR Art. 277a(2) (FX hedging-set add-on = SF * |D_HS|)
    - CRR Art. 278 (PFE multiplier + PFE add-on composition)
    - CRR Art. 279b(1)(b) (FX adjusted notional)
    - CRR Art. 279c(1) (unmargined MF = sqrt(min(M, 1y) / 1y))
    - CRR Art. 280 Table 1 (SF_FX = 0.04)
    - BCBS CRE52.55 (FX cross-hedging-set aggregation = simple sum)
    - CRR Art. 120(1) Table 3 (institution CQS 2 SA risk weight = 50%)
"""

from __future__ import annotations

from datetime import date as _date

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
from rwa_calc.data.schemas import CCR_COLLATERAL_SCHEMA, FX_RATES_SCHEMA
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
from .trade_builder import Trade, create_trades, make_fx_trade

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for CCR-A2 test assertions.
# ---------------------------------------------------------------------------

CCR_A2_TRADE_ID: str = "T_FX_001"
CCR_A2_NETTING_SET_ID: str = "NS_FX_001"
CCR_A2_COUNTERPARTY_REF: str = "CP_001"  # reuse CCR-A1 institution CP

CCR_A2_ASSET_CLASS: str = "fx"
CCR_A2_TRANSACTION_TYPE: str = "derivative"

# Leg 1: bought USD 100m. Leg 2: sold GBP 80m. Implies forward rate 1.25 USD/GBP.
CCR_A2_NOTIONAL_LEG1: float = 100_000_000.0
CCR_A2_CURRENCY_LEG1: str = "USD"
CCR_A2_NOTIONAL_LEG2: float = 80_000_000.0
CCR_A2_CURRENCY_LEG2: str = "GBP"

# Spot FX rate written into the fx_rates table (USD -> GBP = 0.80).
CCR_A2_USD_GBP_SPOT: float = 0.80
CCR_A2_EUR_GBP_SPOT: float = 0.85  # unused decoration — confirms join filtering.

CCR_A2_MTM: float = 0.0
CCR_A2_DELTA: float = 1.0
CCR_A2_IS_LONG: bool = True

# 1-year tenor: 2026-01-15 start, 2027-01-15 maturity.
CCR_A2_START_DATE: _date = _date(2026, 1, 15)
CCR_A2_MATURITY_DATE: _date = _date(2027, 1, 15)

CCR_A2_IS_LEGALLY_ENFORCEABLE: bool = True
CCR_A2_IS_MARGINED: bool = False


# ---------------------------------------------------------------------------
# CCR-A2 trade + netting-set builders.
# ---------------------------------------------------------------------------


def _ccr_a2_trade() -> Trade:
    """Return the single CCR-A2 FX-forward trade instance."""
    return make_fx_trade(
        trade_id=CCR_A2_TRADE_ID,
        netting_set_id=CCR_A2_NETTING_SET_ID,
        asset_class=CCR_A2_ASSET_CLASS,
        transaction_type=CCR_A2_TRANSACTION_TYPE,
        notional=CCR_A2_NOTIONAL_LEG1,
        currency=CCR_A2_CURRENCY_LEG1,
        notional_leg2=CCR_A2_NOTIONAL_LEG2,
        currency_leg2=CCR_A2_CURRENCY_LEG2,
        maturity_date=CCR_A2_MATURITY_DATE,
        start_date=CCR_A2_START_DATE,
        delta=CCR_A2_DELTA,
        is_long=CCR_A2_IS_LONG,
        mtm_value=CCR_A2_MTM,
    )


def _ccr_a2_netting_set() -> NettingSet:
    """Return the single CCR-A2 netting-set instance."""
    return NettingSet(
        netting_set_id=CCR_A2_NETTING_SET_ID,
        counterparty_reference=CCR_A2_COUNTERPARTY_REF,
        is_legally_enforceable=CCR_A2_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_A2_IS_MARGINED,
    )


def create_ccr_a2_trades() -> pl.DataFrame:
    """Return the single-row trades DataFrame for CCR-A2."""
    return create_trades([_ccr_a2_trade()])


def create_ccr_a2_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CCR-A2."""
    return create_netting_sets([_ccr_a2_netting_set()])


def create_ccr_a2_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-A2: no collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


def create_ccr_a2_fx_rates() -> pl.LazyFrame:
    """Return the CCR-A2 fx_rates LazyFrame (USD->GBP = 0.80, EUR->GBP = 0.85)."""
    return pl.LazyFrame(
        {
            "currency_from": [CCR_A2_CURRENCY_LEG1, "EUR"],
            "currency_to": [CCR_A2_CURRENCY_LEG2, CCR_A2_CURRENCY_LEG2],
            "rate": [CCR_A2_USD_GBP_SPOT, CCR_A2_EUR_GBP_SPOT],
        },
        schema=dtypes_of(FX_RATES_SCHEMA),
    )


def _build_ccr_a2_raw_ccr_bundle() -> RawCCRBundle:
    """Assemble the RawCCRBundle from the four CCR-A2 domain frames."""
    return RawCCRBundle(
        trades=TradeBundle(trades=create_ccr_a2_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_ccr_a2_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_ccr_a1_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_ccr_a2_collateral().lazy()),
    )


def build_raw_data_bundle_with_ccr_a2() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle with CCR-A2 (FX forward) populated.

    Reuses CP_001 (institution, CQS 2, GB) from the CCR-A1 portfolio stub so
    the SA Institution lookup ends in CRR Art. 120(1) Table 3 → 50% RW.
    Adds the ``fx_rates`` LazyFrame so the FX adjusted-notional branch can
    convert leg1 (USD) into the reporting currency (GBP) per Art. 279b(1)(b)(i).
    """
    return make_raw_bundle(
        counterparties=_build_cp_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_001_rating(),
        fx_rates=create_ccr_a2_fx_rates(),
        ccr=_build_ccr_a2_raw_ccr_bundle(),
    )
