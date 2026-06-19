"""
Golden CCR-D1/D2/D3 scenarios: fall-through guard batch for Simplified SA-CCR and OEM.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/)
    -> NO engine change (regression guard — engine must stay on full SA-CCR path)

Scenario design (P8.44 / CCR-D1, D2, D3):
    Three orchestrator-ready RawDataBundles asserting the engine always applies
    the full SA-CCR formula (Art. 274/275/278/279c) and never a Simplified Art.281
    or Original Exposure Method branch.  The critical distinguishing pin is CCR-D3:
    a margined OTM position whose PFE multiplier drops below 1.0 (0.2082...).
    Simplified Art.281 would force the multiplier to 1.0, giving a wrong EAD.

    | Scenario | Trade         | NS          | Type  | MtM          | Margined |
    |----------|---------------|-------------|-------|--------------|----------|
    | CCR-D1   | T-D1-001      | NS-D1-001   | IR    | 0.0          | No       |
    | CCR-D2   | T-D2-001      | NS-D2-001   | FX    | 0.0          | No       |
    | CCR-D3   | T-D3-001      | NS-D3-001   | IR    | -4,000,000   | Yes      |

    Shared counterparty CP-D-001: institution, GB, CQS 2 (50% RW).

CCR-D1 economics (mirrors CCR-A1):
    10-year GBP vanilla IR swap, notional 100m, MtM 0.0, unmargined.
    SF_IR=0.005, F=0.05, alpha=1.4; AddOn=3,914,298.228; multiplier=1.0 (cap binds);
    RC=0; EAD=5,480,017.519; RW=0.50; RWA=2,740,008.759.
    MF = sqrt(min(M,1)/1) = 1.0 (full Art.279c(1), not OEM).

CCR-D2 economics (mirrors CCR-A2):
    1-year USD/GBP FX forward, notional 100m USD / 80m GBP, MtM 0.0, unmargined.
    SF_FX=0.04, MF=1.0; AddOn_FX=3,198,904.672; multiplier=1.0; RC=0;
    EAD=4,478,466.541; RW=0.50; RWA=2,239,233.271.

CCR-D3 economics (mirrors CCR-A13 — LOAD-BEARING):
    10-year GBP vanilla IR swap, notional 100m, MtM -4,000,000 (OTM), margined daily.
    NS: TH=2,000,000, MTA=500,000, NICA=250,000, MPOR=10d; margin_agreement_id MA-D3-001.
    Margined MF=0.30 (freq=1d -> MPOR_eff=10; Art. 279c(2)/285, P8.54), so
    AddOn=3,914,298.2277279915*0.30=1,174,289.4683183974; V=-4,000,000; C=0; V-C=-4,000,000;
    pfe_multiplier=0.20816907251400474 (SUB-1; Art.281 would force 1.0 — fails test);
    pfe_addon=244,450.7494828046; rc_margined=2,250,000.0 (TH+MTA-NICA floor);
    EAD=1.4*(2,250,000+244,450.7494828046)=3,492,231.049275926; RWA=1,746,115.524637963.

All scenarios: CRR regime, reporting_date 2026-01-15, STANDARDISED.

Exported public names
---------------------
    CCR_D1_TRADE_ID         : "T-D1-001"
    CCR_D1_NETTING_SET_ID   : "NS-D1-001"
    CCR_D2_TRADE_ID         : "T-D2-001"
    CCR_D2_NETTING_SET_ID   : "NS-D2-001"
    CCR_D3_TRADE_ID         : "T-D3-001"
    CCR_D3_NETTING_SET_ID   : "NS-D3-001"
    CCR_D3_MARGIN_AGREEMENT_ID : "MA-D3-001"
    CCR_D_COUNTERPARTY_REF  : "CP-D-001"
    (plus all expected-value constants for test-writer assertions)

    build_raw_data_bundle_ccr_d1() -> RawDataBundle
    build_raw_data_bundle_ccr_d2() -> RawDataBundle
    build_raw_data_bundle_ccr_d3() -> RawDataBundle
    save_ccr_d1_d3_fixtures()      -> list[tuple[str, int]]
        Smoke-check entry point called by generate_all.py.

References:
    - CRR Art. 273a(1)/(2) (Simplified SA-CCR eligibility threshold — absent from engine)
    - CRR Art. 274(2) (EAD = alpha * (RC + PFE), alpha = 1.4)
    - CRR Art. 275(1) (unmargined RC = max(V-C, 0))
    - CRR Art. 275(2) (margined RC = max(V-C, TH+MTA-NICA, 0))
    - CRR Art. 278(3) (PFE multiplier — sub-unity for OTM/under-collateralised)
    - CRR Art. 279b (PFE add-on — interest rate + FX)
    - CRR Art. 279c(1) (unmargined MF = sqrt(min(M,1y)/1y))
    - CRR Art. 281 (Simplified SA-CCR — pfe_multiplier forced to 1.0)
    - CRR Art. 282 (OEM — different formula entirely)
    - CRR Art. 120(1) Table 3 (institution CQS 2 → 50% risk weight)
    - tests/fixtures/ccr/golden_ccr_a1.py — CCR-D1 economics source
    - tests/fixtures/ccr/golden_ccr_a2.py — CCR-D2 economics source
    - tests/fixtures/ccr/golden_ccr_a13.py — CCR-D3 economics source
    - tests/expected_outputs/ccr/CCR-A1.json  — CCR-D1 assertion anchors
    - tests/expected_outputs/ccr/CCR-A2.json  — CCR-D2 assertion anchors
    - tests/expected_outputs/ccr/CCR-A13.json — CCR-D3 assertion anchors
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
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    FX_RATES_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from .margin_builder import Margin, create_margin_agreements
from .netting_set_builder import NettingSet, create_netting_sets
from .trade_builder import Trade, create_trades, make_fx_trade, make_trade

# ---------------------------------------------------------------------------
# Shared counterparty constants.
# ---------------------------------------------------------------------------

#: Counterparty reference shared by all three CCR-D scenarios.
CCR_D_COUNTERPARTY_REF: str = "CP-D-001"

#: Institution entity type — routes to ExposureClass.INSTITUTION.
CCR_D_ENTITY_TYPE: str = "institution"

#: Country code for the counterparty.
CCR_D_COUNTRY_CODE: str = "GB"

#: CQS 2 — CRR Art. 120(1) Table 3 → 50% SA risk weight.
CCR_D_INSTITUTION_CQS: int = 2

# Rating constants (S&P "A" = CQS 2, solicited external).
CCR_D_RATING_REF: str = "RTG-CCR-D-CP-001"
CCR_D_RATING_TYPE: str = "external"
CCR_D_RATING_AGENCY: str = "S&P"
CCR_D_RATING_VALUE: str = "A"
CCR_D_RATING_CQS: int = 2
CCR_D_RATING_DATE: _date = _date(2026, 1, 15)

# ---------------------------------------------------------------------------
# CCR-D1 constants — unmargined IR (mirrors CCR-A1 economics).
# ---------------------------------------------------------------------------

#: Trade ID for CCR-D1 (unmargined 10-year GBP IR swap).
CCR_D1_TRADE_ID: str = "T-D1-001"

#: Netting set ID for CCR-D1.
CCR_D1_NETTING_SET_ID: str = "NS-D1-001"

CCR_D1_ASSET_CLASS: str = "interest_rate"
CCR_D1_TRANSACTION_TYPE: str = "derivative"
CCR_D1_NOTIONAL: float = 100_000_000.0
CCR_D1_CURRENCY: str = "GBP"
CCR_D1_START_DATE: _date = _date(2026, 1, 15)
CCR_D1_MATURITY_DATE: _date = _date(2036, 1, 15)
CCR_D1_DELTA: float = 1.0
CCR_D1_IS_LONG: bool = True
CCR_D1_MTM: float = 0.0

CCR_D1_IS_LEGALLY_ENFORCEABLE: bool = True
CCR_D1_IS_MARGINED: bool = False

# Golden expected values (from CCR-A1.json, CRR Art. 274-278-279b-279c).
CCR_D1_EXPECTED_CCR_METHOD: str = "sa_ccr"
CCR_D1_EXPECTED_PFE_MULTIPLIER: float = 1.0  # cap binds (MtM=0, at-par)
CCR_D1_EXPECTED_RC_UNMARGINED: float = 0.0  # max(0-0,0) = 0
CCR_D1_EXPECTED_PFE_ADDON: float = 3_914_298.228
CCR_D1_EXPECTED_EAD: float = 5_480_017.519
CCR_D1_EXPECTED_RISK_WEIGHT: float = 0.50
CCR_D1_EXPECTED_RWA: float = 2_740_008.759

# Exposure reference that the CCR pipeline adapter appends.
CCR_D1_EXPOSURE_REFERENCE: str = f"ccr__{CCR_D1_NETTING_SET_ID}"

# ---------------------------------------------------------------------------
# CCR-D2 constants — unmargined FX (mirrors CCR-A2 economics).
# ---------------------------------------------------------------------------

#: Trade ID for CCR-D2 (unmargined 1-year USD/GBP FX forward).
CCR_D2_TRADE_ID: str = "T-D2-001"

#: Netting set ID for CCR-D2.
CCR_D2_NETTING_SET_ID: str = "NS-D2-001"

CCR_D2_ASSET_CLASS: str = "fx"
CCR_D2_TRANSACTION_TYPE: str = "derivative"

# Leg 1: bought USD 100m; leg 2: sold GBP 80m. Implied rate 1.25 USD/GBP.
CCR_D2_NOTIONAL_LEG1: float = 100_000_000.0
CCR_D2_CURRENCY_LEG1: str = "USD"
CCR_D2_NOTIONAL_LEG2: float = 80_000_000.0
CCR_D2_CURRENCY_LEG2: str = "GBP"

# Spot FX rate USD->GBP = 0.80.
CCR_D2_USD_GBP_SPOT: float = 0.80

CCR_D2_START_DATE: _date = _date(2026, 1, 15)
CCR_D2_MATURITY_DATE: _date = _date(2027, 1, 15)
CCR_D2_DELTA: float = 1.0
CCR_D2_IS_LONG: bool = True
CCR_D2_MTM: float = 0.0

CCR_D2_IS_LEGALLY_ENFORCEABLE: bool = True
CCR_D2_IS_MARGINED: bool = False

# Golden expected values (from CCR-A2.json, CRR Art. 274-278-279b(1)(b)(i)-279c).
CCR_D2_EXPECTED_CCR_METHOD: str = "sa_ccr"
CCR_D2_EXPECTED_PFE_MULTIPLIER: float = 1.0
CCR_D2_EXPECTED_RC_UNMARGINED: float = 0.0
CCR_D2_EXPECTED_PFE_ADDON: float = 3_198_904.672
CCR_D2_EXPECTED_EAD: float = 4_478_466.541
CCR_D2_EXPECTED_RISK_WEIGHT: float = 0.50
CCR_D2_EXPECTED_RWA: float = 2_239_233.271

CCR_D2_EXPOSURE_REFERENCE: str = f"ccr__{CCR_D2_NETTING_SET_ID}"

# ---------------------------------------------------------------------------
# CCR-D3 constants — margined OTM IR (mirrors CCR-A13 economics, LOAD-BEARING).
# ---------------------------------------------------------------------------

#: Trade ID for CCR-D3 (margined 10-year GBP IR swap, MtM = -4m).
CCR_D3_TRADE_ID: str = "T-D3-001"

#: Netting set ID for CCR-D3.
CCR_D3_NETTING_SET_ID: str = "NS-D3-001"

#: Margin agreement ID for CCR-D3.
CCR_D3_MARGIN_AGREEMENT_ID: str = "MA-D3-001"

CCR_D3_ASSET_CLASS: str = "interest_rate"
CCR_D3_TRANSACTION_TYPE: str = "derivative"
CCR_D3_NOTIONAL: float = 100_000_000.0
CCR_D3_CURRENCY: str = "GBP"
CCR_D3_START_DATE: _date = _date(2026, 1, 15)
CCR_D3_MATURITY_DATE: _date = _date(2036, 1, 15)
CCR_D3_DELTA: float = 1.0
CCR_D3_IS_LONG: bool = True
# OTM: drives sub-unity PFE multiplier via Art.278(3).
CCR_D3_MTM: float = -4_000_000.0

CCR_D3_IS_LEGALLY_ENFORCEABLE: bool = True
CCR_D3_IS_MARGINED: bool = True

# Margin / CSA parameters (CRR Art. 272(7) / Art. 285(2)(b)).
# TH + MTA - NICA = 2,000,000 + 500,000 - 250,000 = 2,250,000 [floor arm].
CCR_D3_MARGIN_THRESHOLD: float = 2_000_000.0
CCR_D3_MINIMUM_TRANSFER_AMOUNT: float = 500_000.0
CCR_D3_NICA: float = 250_000.0
CCR_D3_MPOR_DAYS: int = 10
CCR_D3_IS_SEGREGATED_IM: bool = False
CCR_D3_REMARGINING_FREQUENCY_DAYS: int = 1
CCR_D3_DISPUTE_COUNT_QTR: int = 0
CCR_D3_NUMBER_OF_TRADES: int = 1
CCR_D3_HAS_ILLIQUID_COLLATERAL: bool = False

# Golden expected values (from CCR-A13.json, full SA-CCR).
# CCR-D3 is a margined, daily-remargin NS (freq=1d -> MPOR_eff=10 -> margined
# MF=0.30 per CRR Art. 279c(2)/285), so the add-on scales by 0.30 (P8.54):
# AddOn_agg = 3_914_298.2277279915 * 0.30 = 1_174_289.4683183974.
# PRIMARY PIN: pfe_multiplier 0.20816907251400474 != 1.0 proves NOT Simplified.
CCR_D3_EXPECTED_CCR_METHOD: str = "sa_ccr"
CCR_D3_EXPECTED_PFE_MULTIPLIER: float = 0.20816907251400474  # sub-unity; Art.281 forces 1.0
CCR_D3_EXPECTED_RC_MARGINED: float = 2_250_000.0  # TH+MTA-NICA floor arm (MF-independent)
CCR_D3_EXPECTED_PFE_ADDON: float = 244_450.7494828046
CCR_D3_EXPECTED_EAD: float = 3_492_231.049275926
CCR_D3_EXPECTED_RISK_WEIGHT: float = 0.50
CCR_D3_EXPECTED_RWA: float = 1_746_115.524637963

# Contrast (would-go-RED if Simplified fired): forcing the PFE multiplier to 1.0
# over the same margined add-on gives
#   simplified_ead = 1.4 * (2_250_000 + 1_174_289.468) = 4_794_005.256
CCR_D3_WRONG_SIMPLIFIED_EAD: float = 4_794_005.255645756  # documented for test commentary

CCR_D3_EXPOSURE_REFERENCE: str = f"ccr__{CCR_D3_NETTING_SET_ID}"


# ---------------------------------------------------------------------------
# Private shared helpers.
# ---------------------------------------------------------------------------


def _build_shared_counterparty() -> pl.LazyFrame:
    """
    Return a one-row counterparty LazyFrame for CP-D-001.

    CP-D-001 is a GB institution with CQS 2 under CRR.  entity_type="institution"
    drives the Classifier to ExposureClass.INSTITUTION → SA risk weight lookup via
    CRR Art. 120(1) Table 3 (CQS 2 → 50%).  Shared across all three CCR-D scenarios.
    """
    row = {
        "counterparty_reference": CCR_D_COUNTERPARTY_REF,
        "counterparty_name": "CCR-D Test Institution (CQS 2)",
        "entity_type": CCR_D_ENTITY_TYPE,
        "country_code": CCR_D_COUNTRY_CODE,
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": CCR_D_INSTITUTION_CQS,
    }
    return pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA)).lazy()


def _build_shared_rating() -> pl.LazyFrame:
    """
    Return a one-row external ratings LazyFrame for CP-D-001.

    S&P "A" = CQS 2 under CRR ECRA mapping for institutions.
    CRR Art. 120(1) Table 3: institution CQS 2 → 50% risk weight.
    """
    row = {
        "rating_reference": CCR_D_RATING_REF,
        "counterparty_reference": CCR_D_COUNTERPARTY_REF,
        "rating_type": CCR_D_RATING_TYPE,
        "rating_agency": CCR_D_RATING_AGENCY,
        "rating_value": CCR_D_RATING_VALUE,
        "cqs": CCR_D_RATING_CQS,
        "pd": None,
        "rating_date": CCR_D_RATING_DATE,
        "is_solicited": True,
        "model_id": None,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(RATINGS_SCHEMA)).lazy()


def _build_empty_facilities() -> pl.LazyFrame:
    """Return a zero-row facilities LazyFrame (no traditional lending in any CCR-D bundle)."""
    return pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA))


def _build_empty_loans() -> pl.LazyFrame:
    """Return a zero-row loans LazyFrame (no drawn loans in any CCR-D bundle)."""
    return pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA))


def _build_empty_facility_mappings() -> pl.LazyFrame:
    """Return a zero-row facility-mappings LazyFrame (no facility hierarchy in CCR-D bundles)."""
    return pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _build_empty_lending_mappings() -> pl.LazyFrame:
    """Return a zero-row lending-mappings LazyFrame (no retail lending groups in CCR-D bundles)."""
    return pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


def _build_empty_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (no CCR collateral in any CCR-D scenario)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# CCR-D1 private builders.
# ---------------------------------------------------------------------------


def _ccr_d1_trade() -> Trade:
    """Return the single CCR-D1 trade (unmargined 10-year GBP IR swap, MtM=0.0)."""
    return make_trade(
        trade_id=CCR_D1_TRADE_ID,
        netting_set_id=CCR_D1_NETTING_SET_ID,
        asset_class=CCR_D1_ASSET_CLASS,
        transaction_type=CCR_D1_TRANSACTION_TYPE,
        notional=CCR_D1_NOTIONAL,
        currency=CCR_D1_CURRENCY,
        maturity_date=CCR_D1_MATURITY_DATE,
        start_date=CCR_D1_START_DATE,
        delta=CCR_D1_DELTA,
        is_long=CCR_D1_IS_LONG,
        mtm_value=CCR_D1_MTM,
    )


def _ccr_d1_netting_set() -> NettingSet:
    """Return the single CCR-D1 netting set (legally enforceable, unmargined)."""
    return NettingSet(
        netting_set_id=CCR_D1_NETTING_SET_ID,
        counterparty_reference=CCR_D_COUNTERPARTY_REF,
        is_legally_enforceable=CCR_D1_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_D1_IS_MARGINED,
    )


def _build_ccr_d1_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle for CCR-D1.

    Composition:
        trades              — 1 row  (T-D1-001, 10y GBP IR swap, NS-D1-001, MtM=0)
        netting_sets        — 1 row  (NS-D1-001, CP-D-001, enforceable, unmargined)
        margin_agreements   — 0 rows (unmargined, no CSA)
        ccr_collateral      — 0 rows (no collateral)
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=create_trades([_ccr_d1_trade()]).lazy()),
        netting_sets=NettingSetBundle(
            netting_sets=create_netting_sets([_ccr_d1_netting_set()]).lazy()
        ),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_margin_agreements([]).lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=_build_empty_collateral().lazy()),
    )


# ---------------------------------------------------------------------------
# CCR-D2 private builders.
# ---------------------------------------------------------------------------


def _ccr_d2_trade() -> Trade:
    """Return the single CCR-D2 FX-forward trade (unmargined 1-year USD/GBP, MtM=0.0)."""
    return make_fx_trade(
        trade_id=CCR_D2_TRADE_ID,
        netting_set_id=CCR_D2_NETTING_SET_ID,
        asset_class=CCR_D2_ASSET_CLASS,
        transaction_type=CCR_D2_TRANSACTION_TYPE,
        notional=CCR_D2_NOTIONAL_LEG1,
        currency=CCR_D2_CURRENCY_LEG1,
        notional_leg2=CCR_D2_NOTIONAL_LEG2,
        currency_leg2=CCR_D2_CURRENCY_LEG2,
        maturity_date=CCR_D2_MATURITY_DATE,
        start_date=CCR_D2_START_DATE,
        delta=CCR_D2_DELTA,
        is_long=CCR_D2_IS_LONG,
        mtm_value=CCR_D2_MTM,
    )


def _ccr_d2_netting_set() -> NettingSet:
    """Return the single CCR-D2 netting set (legally enforceable, unmargined)."""
    return NettingSet(
        netting_set_id=CCR_D2_NETTING_SET_ID,
        counterparty_reference=CCR_D_COUNTERPARTY_REF,
        is_legally_enforceable=CCR_D2_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_D2_IS_MARGINED,
    )


def _build_ccr_d2_fx_rates() -> pl.LazyFrame:
    """Return the CCR-D2 fx_rates LazyFrame (USD->GBP = 0.80)."""
    return pl.LazyFrame(
        {
            "currency_from": [CCR_D2_CURRENCY_LEG1],
            "currency_to": [CCR_D2_CURRENCY_LEG2],
            "rate": [CCR_D2_USD_GBP_SPOT],
        },
        schema=dtypes_of(FX_RATES_SCHEMA),
    )


def _build_ccr_d2_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle for CCR-D2.

    Composition:
        trades              — 1 row  (T-D2-001, 1y USD/GBP FX forward, NS-D2-001, MtM=0)
        netting_sets        — 1 row  (NS-D2-001, CP-D-001, enforceable, unmargined)
        margin_agreements   — 0 rows (unmargined, no CSA)
        ccr_collateral      — 0 rows (no collateral)
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=create_trades([_ccr_d2_trade()]).lazy()),
        netting_sets=NettingSetBundle(
            netting_sets=create_netting_sets([_ccr_d2_netting_set()]).lazy()
        ),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_margin_agreements([]).lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=_build_empty_collateral().lazy()),
    )


# ---------------------------------------------------------------------------
# CCR-D3 private builders.
# ---------------------------------------------------------------------------


def _ccr_d3_trade() -> Trade:
    """Return the single CCR-D3 trade (margined 10-year GBP IR swap, MtM=-4m)."""
    return make_trade(
        trade_id=CCR_D3_TRADE_ID,
        netting_set_id=CCR_D3_NETTING_SET_ID,
        asset_class=CCR_D3_ASSET_CLASS,
        transaction_type=CCR_D3_TRANSACTION_TYPE,
        notional=CCR_D3_NOTIONAL,
        currency=CCR_D3_CURRENCY,
        maturity_date=CCR_D3_MATURITY_DATE,
        start_date=CCR_D3_START_DATE,
        delta=CCR_D3_DELTA,
        is_long=CCR_D3_IS_LONG,
        mtm_value=CCR_D3_MTM,
    )


def _ccr_d3_netting_set() -> NettingSet:
    """Return the single CCR-D3 netting set (margined, TH=2m, MTA=0.5m, NICA=0.25m, MPOR=10d)."""
    return NettingSet(
        netting_set_id=CCR_D3_NETTING_SET_ID,
        counterparty_reference=CCR_D_COUNTERPARTY_REF,
        is_legally_enforceable=CCR_D3_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_D3_IS_MARGINED,
        margin_threshold=CCR_D3_MARGIN_THRESHOLD,
        minimum_transfer_amount=CCR_D3_MINIMUM_TRANSFER_AMOUNT,
        nica=CCR_D3_NICA,
        mpor_days=CCR_D3_MPOR_DAYS,
        margin_agreement_id=CCR_D3_MARGIN_AGREEMENT_ID,
        number_of_trades=CCR_D3_NUMBER_OF_TRADES,
        has_illiquid_collateral_or_hard_to_replace_otc=CCR_D3_HAS_ILLIQUID_COLLATERAL,
    )


def _ccr_d3_margin() -> Margin:
    """Return the CCR-D3 margin agreement (MA-D3-001)."""
    return Margin(
        margin_agreement_id=CCR_D3_MARGIN_AGREEMENT_ID,
        counterparty_reference=CCR_D_COUNTERPARTY_REF,
        margin_threshold=CCR_D3_MARGIN_THRESHOLD,
        minimum_transfer_amount=CCR_D3_MINIMUM_TRANSFER_AMOUNT,
        nica=CCR_D3_NICA,
        mpor_days=CCR_D3_MPOR_DAYS,
        is_segregated_im=CCR_D3_IS_SEGREGATED_IM,
        remargining_frequency_days=CCR_D3_REMARGINING_FREQUENCY_DAYS,
        dispute_count_qtr=CCR_D3_DISPUTE_COUNT_QTR,
    )


def _build_ccr_d3_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle for CCR-D3.

    Composition:
        trades              — 1 row  (T-D3-001, 10y GBP IR swap, NS-D3-001, MtM=-4m)
        netting_sets        — 1 row  (NS-D3-001, CP-D-001, enforceable, margined)
        margin_agreements   — 1 row  (MA-D3-001, TH=2m, MTA=0.5m, NICA=0.25m, MPOR=10d)
        ccr_collateral      — 0 rows (c_net = 0)
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=create_trades([_ccr_d3_trade()]).lazy()),
        netting_sets=NettingSetBundle(
            netting_sets=create_netting_sets([_ccr_d3_netting_set()]).lazy()
        ),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_margin_agreements([_ccr_d3_margin()]).lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=_build_empty_collateral().lazy()),
    )


# ---------------------------------------------------------------------------
# Public bundle-assembly helpers.
# ---------------------------------------------------------------------------


def build_raw_data_bundle_ccr_d1() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle for CCR-D1 (unmargined IR, CCR-A1 economics).

    Key responsibilities:
    - Provides CP-D-001 as an institution counterparty (entity_type="institution",
      CQS 2, GB) so the Classifier routes the CCR-derived synthetic exposure
      through SA-Institution (CRR Art. 120(1) Table 3 → 50% RW).
    - Provides a matching external rating (CQS 2, S&P "A") so the full
      rating-inheritance pipeline resolves external_cqs correctly.
    - Zero-row facility / loan / contingent / mapping frames; the only exposure
      is the CCR-derived synthetic row appended by the pipeline adapter.
    - ccr is populated with trade T-D1-001 (10y GBP IR swap, MtM=0.0) in
      netting set NS-D1-001 (CP-D-001, enforceable, unmargined), with empty
      margin and collateral frames.

    Fall-through guard assertion (CCR-D1 / CCR-A1 anchors):
        ccr_method      == "sa_ccr"
        pfe_multiplier  == approx(1.0, abs=1e-9)    (cap binds, MtM=0)
        rc_unmargined   == 0.0
        pfe_addon       == approx(3_914_298.228, rel=1e-6)
        ead_final       == approx(5_480_017.519, rel=1e-6)
        risk_weight     == 0.50
        rwa_final       == approx(2_740_008.759, rel=1e-6)

    Integration test usage:
        from tests.fixtures.ccr.golden_ccr_d1_d3 import build_raw_data_bundle_ccr_d1
        data = build_raw_data_bundle_ccr_d1()
        result = pipeline_orchestrator.run_with_data(data, config)

    References:
        - CRR Art. 275(1) (unmargined RC = max(V-C, 0))
        - CRR Art. 279c(1) (MF = sqrt(min(M,1y)/1y) — full Art, not OEM)
        - CRR Art. 120(1) Table 3 (institution CQS 2 → 50% RW)
    """
    return make_raw_bundle(
        counterparties=_build_shared_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_shared_rating(),
        ccr=_build_ccr_d1_raw_ccr_bundle(),
    )


def build_raw_data_bundle_ccr_d2() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle for CCR-D2 (unmargined FX, CCR-A2 economics).

    Key responsibilities:
    - Identical portfolio stub to CCR-D1 (CP-D-001, CQS 2, GB).
    - Adds the fx_rates LazyFrame so the FX adjusted-notional branch can convert
      leg1 (USD) into the reporting currency (GBP) per Art. 279b(1)(b)(i).
    - ccr is populated with trade T-D2-001 (1y USD/GBP FX forward) in
      netting set NS-D2-001 (CP-D-001, enforceable, unmargined).

    Fall-through guard assertion (CCR-D2 / CCR-A2 anchors):
        ccr_method      == "sa_ccr"
        pfe_multiplier  == approx(1.0, abs=1e-9)
        rc_unmargined   == 0.0
        pfe_addon       == approx(3_198_904.672, rel=1e-6)
        ead_final       == approx(4_478_466.541, rel=1e-6)
        risk_weight     == 0.50
        rwa_final       == approx(2_239_233.271, rel=1e-6)

    Integration test usage:
        from tests.fixtures.ccr.golden_ccr_d1_d3 import build_raw_data_bundle_ccr_d2
        data = build_raw_data_bundle_ccr_d2()
        result = pipeline_orchestrator.run_with_data(data, config)

    References:
        - CRR Art. 279b(1)(b)(i) (FX adjusted notional)
        - CRR Art. 277a(2) (FX hedging-set add-on)
        - CRR Art. 275(1) (unmargined RC)
    """
    return make_raw_bundle(
        counterparties=_build_shared_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_shared_rating(),
        fx_rates=_build_ccr_d2_fx_rates(),
        ccr=_build_ccr_d2_raw_ccr_bundle(),
    )


def build_raw_data_bundle_ccr_d3() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle for CCR-D3 (margined OTM IR, CCR-A13 economics).

    This is the load-bearing scenario.  The OTM position (MtM = -4m) causes
    the PFE multiplier (Art. 278(3)) to drop below 1.0:

        pfe_multiplier = 0.20816907251400474

    Simplified SA-CCR (Art. 281) would force this to 1.0, producing an EAD of
    4,794,005.256 instead of 3,492,231.049275926.  If the engine erroneously
    routes through the Simplified branch, the test fails on the multiplier pin.

    Key responsibilities:
    - Identical portfolio stub to CCR-D1 (CP-D-001, CQS 2, GB).
    - ccr is populated with trade T-D3-001 (10y GBP IR swap, MtM=-4m) in
      netting set NS-D3-001 (CP-D-001, enforceable, margined):
        - margin_threshold = 2,000,000
        - minimum_transfer_amount = 500,000
        - nica = 250,000
        - mpor_days = 10 (Art. 285(2)(b) minimum)
        - margin_agreement_id = MA-D3-001
    - One margin agreement row (MA-D3-001) matching the netting-set parameters.
    - Zero CCR collateral rows (c_net = 0).

    Fall-through guard assertion (CCR-D3 / CCR-A13 anchors):
        ccr_method      == "sa_ccr"
        pfe_multiplier  == approx(0.20816907251400474, rel=1e-9)  <- PRIMARY PIN
        rc_margined     == 2_250_000.0
        pfe_addon       == approx(244_450.7494828046, rel=1e-9)
        ead_final       == approx(3_492_231.049275926, rel=1e-9)
        risk_weight     == 0.50
        rwa_final       == approx(1_746_115.524637963, rel=1e-9)

    Contrast (must NOT match; indicates Simplified branch fired):
        simplified_ead  = 4_794_005.256  (Art.281 forced multiplier=1.0)

    Integration test usage:
        from tests.fixtures.ccr.golden_ccr_d1_d3 import build_raw_data_bundle_ccr_d3
        data = build_raw_data_bundle_ccr_d3()
        result = pipeline_orchestrator.run_with_data(data, config)

    References:
        - CRR Art. 275(2) (margined RC = max(V-C, TH+MTA-NICA, 0))
        - CRR Art. 278(3) (PFE multiplier formula — sub-unity when V-C < 0)
        - CRR Art. 281 (Simplified SA-CCR — multiplier forced to 1.0; NOT used)
        - CRR Art. 120(1) Table 3 (institution CQS 2 → 50% RW)
    """
    return make_raw_bundle(
        counterparties=_build_shared_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_shared_rating(),
        ccr=_build_ccr_d3_raw_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Smoke-check entry point — called by generate_all.py.
# ---------------------------------------------------------------------------


def save_ccr_d1_d3_fixtures() -> list[tuple[str, int]]:
    """
    Smoke-check all three CCR-D bundles and return a generation report.

    No parquet files are written — this is a Python-only builder (same pattern
    as golden_ccr_a1.py / p823_ls_builder.py etc.).

    Invariants verified:
        1.  All three bundles: bundle.ccr is not None.
        2.  CCR-D1: 1 trade (T-D1-001), 1 NS (NS-D1-001), 0 margin rows.
        3.  CCR-D2: 1 trade (T-D2-001), 1 NS (NS-D2-001), 0 margin rows.
        4.  CCR-D3: 1 trade (T-D3-001), 1 NS (NS-D3-001), 1 margin row (MA-D3-001).
        5.  CCR-D3: NS is_margined=True; margin params match golden constants.
        6.  CCR-D3: trade mtm_value == -4,000,000 (sub-unity multiplier input).
        7.  All three: CP-D-001 counterparty with institution_cqs=2.
        8.  All three: zero CCR collateral rows.
        9.  CCR-D2: trade has notional_leg2 populated (FX two-leg trade).

    Returns:
        ``[("(python-only builder — no parquet)", 0)]``
    """
    bundle_d1 = build_raw_data_bundle_ccr_d1()
    bundle_d2 = build_raw_data_bundle_ccr_d2()
    bundle_d3 = build_raw_data_bundle_ccr_d3()

    _check_ccr_d_bundle(
        bundle_d1,
        scenario="CCR-D1",
        expected_trade_id=CCR_D1_TRADE_ID,
        expected_ns_id=CCR_D1_NETTING_SET_ID,
        expected_is_margined=False,
        expected_margin_rows=0,
        expected_mtm=CCR_D1_MTM,
    )
    _check_ccr_d_bundle(
        bundle_d2,
        scenario="CCR-D2",
        expected_trade_id=CCR_D2_TRADE_ID,
        expected_ns_id=CCR_D2_NETTING_SET_ID,
        expected_is_margined=False,
        expected_margin_rows=0,
        expected_mtm=CCR_D2_MTM,
    )
    _check_ccr_d_bundle(
        bundle_d3,
        scenario="CCR-D3",
        expected_trade_id=CCR_D3_TRADE_ID,
        expected_ns_id=CCR_D3_NETTING_SET_ID,
        expected_is_margined=True,
        expected_margin_rows=1,
        expected_mtm=CCR_D3_MTM,
    )

    # CCR-D2 specific: trade must have notional_leg2 populated.
    d2_trades = bundle_d2.ccr.trades.trades.collect()  # ty: ignore[unresolved-attribute]
    if d2_trades["notional_leg2"][0] is None:
        raise AssertionError("CCR-D2: notional_leg2 must be non-null (FX two-leg trade)")
    if d2_trades["notional_leg2"][0] != CCR_D2_NOTIONAL_LEG2:
        raise AssertionError(
            f"CCR-D2: notional_leg2 must be {CCR_D2_NOTIONAL_LEG2} "
            f"(got {d2_trades['notional_leg2'][0]})"
        )

    # CCR-D3 specific: margin row must have correct agreement ID and MPOR.
    d3_margin = bundle_d3.ccr.margin_agreements.margin_agreements.collect()  # ty: ignore[unresolved-attribute]
    if d3_margin["margin_agreement_id"][0] != CCR_D3_MARGIN_AGREEMENT_ID:
        raise AssertionError(
            f"CCR-D3: margin_agreement_id must be {CCR_D3_MARGIN_AGREEMENT_ID!r} "
            f"(got {d3_margin['margin_agreement_id'][0]!r})"
        )
    if d3_margin["mpor_days"][0] != CCR_D3_MPOR_DAYS:
        raise AssertionError(
            f"CCR-D3: margin mpor_days must be {CCR_D3_MPOR_DAYS} (got {d3_margin['mpor_days'][0]})"
        )

    # Documented would-go-RED contrast: simplified EAD constant must differ from full EAD.
    if abs(CCR_D3_WRONG_SIMPLIFIED_EAD - CCR_D3_EXPECTED_EAD) < 1.0:
        raise AssertionError(
            "CCR-D3: simplified EAD must differ from full SA-CCR EAD by at least 1 GBP "
            "(constant cross-check failed)"
        )

    return [("(python-only builder — no parquet)", 0)]


def _check_ccr_d_bundle(
    bundle: RawDataBundle,
    scenario: str,
    expected_trade_id: str,
    expected_ns_id: str,
    expected_is_margined: bool,
    expected_margin_rows: int,
    expected_mtm: float,
) -> None:
    """Verify structural invariants for a single CCR-D bundle."""
    if bundle.ccr is None:
        raise AssertionError(f"{scenario}: bundle.ccr must not be None")

    trades_df = bundle.ccr.trades.trades.collect()
    ns_df = bundle.ccr.netting_sets.netting_sets.collect()
    margin_df = bundle.ccr.margin_agreements.margin_agreements.collect()
    coll_df = bundle.ccr.ccr_collateral.ccr_collateral.collect()
    cp_df = bundle.counterparties.collect()  # type: ignore[union-attr]

    # Trade row count and identity.
    if trades_df.height != 1:
        raise AssertionError(f"{scenario}: expected 1 trade row, got {trades_df.height}")
    if trades_df["trade_id"][0] != expected_trade_id:
        raise AssertionError(
            f"{scenario}: trade_id must be {expected_trade_id!r} (got {trades_df['trade_id'][0]!r})"
        )
    if trades_df["mtm_value"][0] != expected_mtm:
        raise AssertionError(
            f"{scenario}: mtm_value must be {expected_mtm} (got {trades_df['mtm_value'][0]})"
        )

    # Netting-set row count, identity, and margining status.
    if ns_df.height != 1:
        raise AssertionError(f"{scenario}: expected 1 netting-set row, got {ns_df.height}")
    if ns_df["netting_set_id"][0] != expected_ns_id:
        raise AssertionError(
            f"{scenario}: netting_set_id must be {expected_ns_id!r} "
            f"(got {ns_df['netting_set_id'][0]!r})"
        )
    if ns_df["is_margined"][0] is not expected_is_margined:
        raise AssertionError(
            f"{scenario}: is_margined must be {expected_is_margined} "
            f"(got {ns_df['is_margined'][0]})"
        )
    if ns_df["counterparty_reference"][0] != CCR_D_COUNTERPARTY_REF:
        raise AssertionError(
            f"{scenario}: NS counterparty_reference must be {CCR_D_COUNTERPARTY_REF!r} "
            f"(got {ns_df['counterparty_reference'][0]!r})"
        )

    # Margin agreement rows.
    if margin_df.height != expected_margin_rows:
        raise AssertionError(
            f"{scenario}: expected {expected_margin_rows} margin-agreement row(s), "
            f"got {margin_df.height}"
        )

    # CCR collateral — always zero.
    if coll_df.height != 0:
        raise AssertionError(f"{scenario}: ccr_collateral must be empty (got {coll_df.height})")

    # Counterparty: institution CQS 2.
    if cp_df.height != 1:
        raise AssertionError(f"{scenario}: expected 1 counterparty row, got {cp_df.height}")
    if cp_df["counterparty_reference"][0] != CCR_D_COUNTERPARTY_REF:
        raise AssertionError(
            f"{scenario}: counterparty_reference must be {CCR_D_COUNTERPARTY_REF!r} "
            f"(got {cp_df['counterparty_reference'][0]!r})"
        )
    if cp_df["entity_type"][0] != "institution":
        raise AssertionError(
            f"{scenario}: entity_type must be 'institution' (got {cp_df['entity_type'][0]!r})"
        )
    if cp_df["institution_cqs"][0] != CCR_D_INSTITUTION_CQS:
        raise AssertionError(
            f"{scenario}: institution_cqs must be {CCR_D_INSTITUTION_CQS} "
            f"(got {cp_df['institution_cqs'][0]!r})"
        )
