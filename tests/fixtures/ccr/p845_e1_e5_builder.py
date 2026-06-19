"""
P8.45 / CCR-E1..E5 fixture builder: default-risk RWA routing across counterparty
classes and frameworks with a constant SA-CCR EAD.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_ccr_e1_e5_default_risk_routing.py)
    -> engine-implementer (engine/ccr/pipeline_adapter.py + sa/risk_weights.py)

Scenario design:
    Five scenarios share identical trade economics — one 10-year GBP vanilla IR swap,
    notional GBP 100m, at-par (MtM=0), delta=1.0, unmargined, legally enforceable.
    Only the counterparty class (and, for E4/E5, the reporting framework) differ.
    EAD is therefore constant across all five scenarios:

        EAD = alpha x (RC + PFE_addon)
            = 1.4 x (0 + 3,914,298.228)
            = 5,480,017.519  (anchored to CCR-A1 JSON golden)

    The scenarios exercise the following routing paths:

        CCR-E1 (CRR):   institution,          CQS 2  -> RW 0.50  (CRR Art. 120 T3)
        CCR-E2 (CRR):   corporate,            CQS 3  -> RW 1.00  (CRR Art. 122)
        CCR-E3 (CRR):   sovereign (BR),       CQS 3  -> RW 0.50  (CRR Art. 114 CQS 3, non-domestic)
        CCR-E4 (B3.1):  institution,          CQS 2  -> RW 0.30  (B3.1 Art. 120 ECRA, >3m)
        CCR-E5 (B3.1):  corporate,            CQS 3  -> RW 0.75  (B3.1 Art. 122 Table 6)

    The routing risk for the sovereign (CCR-E3) is documented in the proposal:
    _enrich_ccr_rows_with_ratings must propagate the external CQS 3 onto the synthetic
    CCR row so that the SA risk-weight look-up resolves to 50% rather than falling back
    to 100% unrated.  The fixture supplies the rating faithfully; if the engine's join
    is broken the test surfaces the gap.

    Load-bearing assertions (for test-writer):
        1. EAD invariance within CRR: ead_final(E1) == ead_final(E2) == ead_final(E3) rel 1e-9
        2. EAD invariance within B3.1: ead_final(E4) == ead_final(E5)
        3. EAD invariance across frameworks: ead_final(E1) == ead_final(E4) rel 1e-6
        4. rwa_final == ead_final x risk_weight rel 1e-9 per row
        5. CRR vs B3.1 RW delta: rw(E1)=0.50 != rw(E4)=0.30; rw(E2)=1.00 != rw(E5)=0.75

Public bundle helpers (one per scenario):
    build_raw_data_bundle_ccr_e1() -> RawDataBundle   # CRR institution CQS 2
    build_raw_data_bundle_ccr_e2() -> RawDataBundle   # CRR corporate CQS 3
    build_raw_data_bundle_ccr_e3() -> RawDataBundle   # CRR sovereign (BR) CQS 3
    build_raw_data_bundle_ccr_e4() -> RawDataBundle   # B3.1 institution CQS 2
    build_raw_data_bundle_ccr_e5() -> RawDataBundle   # B3.1 corporate CQS 3

Config helpers:
    make_crr_config()    -> CalculationConfig   # reporting_date 2026-01-15, STANDARDISED
    make_b31_config()    -> CalculationConfig   # reporting_date 2027-01-15, STANDARDISED

References:
    - CRR Art. 114(1)-(4) (sovereign SA risk weights; Art. 114(4) domestic-currency 0%)
    - CRR Art. 120(1) Table 3 (institution CQS 2 -> 50%)
    - CRR Art. 122(1) (corporate CQS 3 -> 100%)
    - CRR Art. 274(2) (SA-CCR EAD = alpha x (RC + PFE))
    - CRR Art. 275(1) (unmargined RC = max(V - C, 0))
    - CRR Art. 279b(1)(a) (PFE add-on — interest rate)
    - CRR Art. 295 (contractual netting recognition)
    - PS1/26 Art. 120(2) Table 3 (institution CQS 2 -> 30% ECRA, tenor > 3m)
    - PS1/26 Art. 122(2) Table 6 (corporate CQS 3 -> 75%)
    - src/rwa_calc/data/schemas.py — TRADE_SCHEMA, NETTING_SET_SCHEMA,
      CCR_COLLATERAL_SCHEMA, COUNTERPARTY_SCHEMA, RATINGS_SCHEMA
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
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode
from tests.fixtures.raw_bundle import make_raw_bundle

from .margin_builder import create_margin_agreements
from .netting_set_builder import NettingSet, create_netting_sets
from .trade_builder import Trade, create_trades, make_trade

# ---------------------------------------------------------------------------
# Shared trade economics — identical across all five scenarios.
# ---------------------------------------------------------------------------

# CRR rows: reporting_date / start_date = 2026-01-15, maturity = 2036-01-15 (10y).
E_CRR_START_DATE: _date = _date(2026, 1, 15)
E_CRR_MATURITY_DATE: _date = _date(2036, 1, 15)
E_CRR_REPORTING_DATE: _date = _date(2026, 1, 15)

# B3.1 rows: reporting_date / start_date = 2027-01-15, maturity = 2037-01-15 (10y).
E_B31_START_DATE: _date = _date(2027, 1, 15)
E_B31_MATURITY_DATE: _date = _date(2037, 1, 15)
E_B31_REPORTING_DATE: _date = _date(2027, 1, 15)

# Trade economic parameters (shared).
E_NOTIONAL: float = 100_000_000.0          # GBP 100m
E_CURRENCY: str = "GBP"
E_ASSET_CLASS: str = "interest_rate"
E_TRANSACTION_TYPE: str = "derivative"
E_MTM: float = 0.0                         # at-par
E_DELTA: float = 1.0                       # non-option directional long
E_IS_LONG: bool = True

# Netting-set flags (shared).
E_IS_LEGALLY_ENFORCEABLE: bool = True      # Art. 295 condition met
E_IS_MARGINED: bool = False                # unmargined

# EAD anchor (from CCR-A1 golden JSON — live formula value).
# RC = max(V - C, 0) = max(0 - 0, 0) = 0.0
# pfe_addon (= add-on_aggregate) = 3,914,298.228
# EAD = 1.4 x (0 + 3,914,298.228) = 5,480,017.519
E_EAD_ANCHOR: float = 5_480_017.519
E_PFE_ADDON_ANCHOR: float = 3_914_298.228
E_RC_ANCHOR: float = 0.0

# ---------------------------------------------------------------------------
# CCR-E1 constants — CRR institution, CQS 2, GB.
# ---------------------------------------------------------------------------

CCR_E1_NETTING_SET_ID: str = "NS_E1"
CCR_E1_TRADE_ID: str = "T_E1"
CCR_E1_COUNTERPARTY_REF: str = "CP_E1"
CCR_E1_ENTITY_TYPE: str = "institution"
CCR_E1_COUNTRY_CODE: str = "GB"
CCR_E1_INSTITUTION_CQS: int = 2

CCR_E1_RATING_REF: str = "RTG_E1"
CCR_E1_RATING_TYPE: str = "external"
CCR_E1_RATING_AGENCY: str = "S&P"
CCR_E1_RATING_VALUE: str = "A"           # S&P "A" = CQS 2
CCR_E1_RATING_CQS: int = 2

# CRR Art. 120(1) Table 3: institution CQS 2 -> 50%.
CCR_E1_EXPECTED_RW: float = 0.50
CCR_E1_EXPECTED_RWA: float = E_EAD_ANCHOR * CCR_E1_EXPECTED_RW   # 2,740,008.760

# ---------------------------------------------------------------------------
# CCR-E2 constants — CRR corporate, CQS 3, GB.
# ---------------------------------------------------------------------------

CCR_E2_NETTING_SET_ID: str = "NS_E2"
CCR_E2_TRADE_ID: str = "T_E2"
CCR_E2_COUNTERPARTY_REF: str = "CP_E2"
CCR_E2_ENTITY_TYPE: str = "corporate"
CCR_E2_COUNTRY_CODE: str = "GB"

CCR_E2_RATING_REF: str = "RTG_E2"
CCR_E2_RATING_TYPE: str = "external"
CCR_E2_RATING_AGENCY: str = "S&P"
CCR_E2_RATING_VALUE: str = "BBB"         # S&P "BBB" = CQS 3
CCR_E2_RATING_CQS: int = 3

# CRR Art. 122(1): corporate CQS 3 -> 100%.
CCR_E2_EXPECTED_RW: float = 1.00
CCR_E2_EXPECTED_RWA: float = E_EAD_ANCHOR * CCR_E2_EXPECTED_RW   # 5,480,017.519

# ---------------------------------------------------------------------------
# CCR-E3 constants — CRR sovereign (BR, foreign/non-domestic), CQS 3.
# ---------------------------------------------------------------------------

CCR_E3_NETTING_SET_ID: str = "NS_E3"
CCR_E3_TRADE_ID: str = "T_E3"
CCR_E3_COUNTERPARTY_REF: str = "CP_E3"
CCR_E3_ENTITY_TYPE: str = "sovereign"
# BR is non-GB / non-EU -> Art. 114(4) domestic-currency 0% branch does NOT fire.
CCR_E3_COUNTRY_CODE: str = "BR"

CCR_E3_RATING_REF: str = "RTG_E3"
CCR_E3_RATING_TYPE: str = "external"
CCR_E3_RATING_AGENCY: str = "S&P"
CCR_E3_RATING_VALUE: str = "BBB"         # S&P "BBB" = CQS 3 (sovereign table)
CCR_E3_RATING_CQS: int = 3

# CRR Art. 114(1): sovereign CQS 3 -> 50% (non-domestic, Art. 114(4) does not apply).
CCR_E3_EXPECTED_RW: float = 0.50
CCR_E3_EXPECTED_RWA: float = E_EAD_ANCHOR * CCR_E3_EXPECTED_RW   # 2,740,008.760

# ---------------------------------------------------------------------------
# CCR-E4 constants — B3.1 institution, CQS 2, GB (ECRA).
# ---------------------------------------------------------------------------

CCR_E4_NETTING_SET_ID: str = "NS_E4"
CCR_E4_TRADE_ID: str = "T_E4"
CCR_E4_COUNTERPARTY_REF: str = "CP_E4"
CCR_E4_ENTITY_TYPE: str = "institution"
CCR_E4_COUNTRY_CODE: str = "GB"
CCR_E4_INSTITUTION_CQS: int = 2

CCR_E4_RATING_REF: str = "RTG_E4"
CCR_E4_RATING_TYPE: str = "external"
CCR_E4_RATING_AGENCY: str = "S&P"
CCR_E4_RATING_VALUE: str = "A"           # S&P "A" = CQS 2
CCR_E4_RATING_CQS: int = 2

# PS1/26 Art. 120(2) Table 3: institution CQS 2, tenor > 3m -> 30% (ECRA).
CCR_E4_EXPECTED_RW: float = 0.30
CCR_E4_EXPECTED_RWA: float = E_EAD_ANCHOR * CCR_E4_EXPECTED_RW   # 1,644,005.256

# ---------------------------------------------------------------------------
# CCR-E5 constants — B3.1 corporate, CQS 3, GB.
# ---------------------------------------------------------------------------

CCR_E5_NETTING_SET_ID: str = "NS_E5"
CCR_E5_TRADE_ID: str = "T_E5"
CCR_E5_COUNTERPARTY_REF: str = "CP_E5"
CCR_E5_ENTITY_TYPE: str = "corporate"
CCR_E5_COUNTRY_CODE: str = "GB"

CCR_E5_RATING_REF: str = "RTG_E5"
CCR_E5_RATING_TYPE: str = "external"
CCR_E5_RATING_AGENCY: str = "S&P"
CCR_E5_RATING_VALUE: str = "BBB"         # S&P "BBB" = CQS 3
CCR_E5_RATING_CQS: int = 3

# PS1/26 Art. 122(2) Table 6: corporate CQS 3 -> 75%.
CCR_E5_EXPECTED_RW: float = 0.75
CCR_E5_EXPECTED_RWA: float = E_EAD_ANCHOR * CCR_E5_EXPECTED_RW   # 4,110,013.139


# ---------------------------------------------------------------------------
# Config factories — self-documenting for test-writer.
# ---------------------------------------------------------------------------


def make_crr_config() -> CalculationConfig:
    """
    Return CRR CalculationConfig for CCR-E1/E2/E3 scenarios.

    reporting_date = 2026-01-15 (matches E_CRR_START_DATE / E_CRR_MATURITY_DATE).
    permission_mode = STANDARDISED (SA only — no IRB model permissions needed).

    References:
        - CRR Art. 114, 120, 122 (SA risk weights)
        - CRR Art. 274(2) (SA-CCR EAD = alpha x (RC + PFE))
    """
    return CalculationConfig.crr(
        reporting_date=E_CRR_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


def make_b31_config() -> CalculationConfig:
    """
    Return Basel 3.1 CalculationConfig for CCR-E4/E5 scenarios.

    reporting_date = 2027-01-15 (matches E_B31_START_DATE / E_B31_MATURITY_DATE).
    permission_mode = STANDARDISED (SA only — no IRB model permissions needed).

    References:
        - PS1/26 Art. 120 Table 3 (institution ECRA CQS 2 -> 30%)
        - PS1/26 Art. 122 Table 6 (corporate CQS 3 -> 75%)
        - PS1/26 Art. 274(2) (SA-CCR EAD = alpha x (RC + PFE))
    """
    return CalculationConfig.basel_3_1(
        reporting_date=E_B31_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


# ---------------------------------------------------------------------------
# Private shared helpers.
# ---------------------------------------------------------------------------


def _make_crr_trade(trade_id: str, netting_set_id: str) -> Trade:
    """Return a CRR-framework trade (10y, start 2026-01-15)."""
    return make_trade(
        trade_id=trade_id,
        netting_set_id=netting_set_id,
        asset_class=E_ASSET_CLASS,
        transaction_type=E_TRANSACTION_TYPE,
        notional=E_NOTIONAL,
        currency=E_CURRENCY,
        start_date=E_CRR_START_DATE,
        maturity_date=E_CRR_MATURITY_DATE,
        delta=E_DELTA,
        is_long=E_IS_LONG,
        mtm_value=E_MTM,
    )


def _make_b31_trade(trade_id: str, netting_set_id: str) -> Trade:
    """Return a B3.1-framework trade (10y, start 2027-01-15)."""
    return make_trade(
        trade_id=trade_id,
        netting_set_id=netting_set_id,
        asset_class=E_ASSET_CLASS,
        transaction_type=E_TRANSACTION_TYPE,
        notional=E_NOTIONAL,
        currency=E_CURRENCY,
        start_date=E_B31_START_DATE,
        maturity_date=E_B31_MATURITY_DATE,
        delta=E_DELTA,
        is_long=E_IS_LONG,
        mtm_value=E_MTM,
    )


def _make_netting_set(netting_set_id: str, counterparty_reference: str) -> NettingSet:
    """Return an unmargined, legally enforceable netting set."""
    return NettingSet(
        netting_set_id=netting_set_id,
        counterparty_reference=counterparty_reference,
        is_legally_enforceable=E_IS_LEGALLY_ENFORCEABLE,
        is_margined=E_IS_MARGINED,
    )


def _make_raw_ccr_bundle(trade: Trade, netting_set: NettingSet) -> RawCCRBundle:
    """Assemble a RawCCRBundle from a single trade and netting set (no margin, no collateral)."""
    return RawCCRBundle(
        trades=TradeBundle(trades=create_trades([trade]).lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_netting_sets([netting_set]).lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_margin_agreements([]).lazy()
        ),
        ccr_collateral=CCRCollateralBundle(
            ccr_collateral=pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA)).lazy()
        ),
    )


def _make_counterparty_row(
    counterparty_reference: str,
    counterparty_name: str,
    entity_type: str,
    country_code: str,
    institution_cqs: int | None = None,
) -> pl.LazyFrame:
    """
    Return a one-row counterparty LazyFrame.

    ``institution_cqs`` is populated for institution counterparties so that
    the SA calculator can resolve the risk weight even when the rating-inheritance
    pipeline is bypassed in narrow unit tests. It is null for corporate and
    sovereign rows (no institution_cqs concept for those classes).
    """
    row: dict = {
        "counterparty_reference": counterparty_reference,
        "counterparty_name": counterparty_name,
        "entity_type": entity_type,
        "country_code": country_code,
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": institution_cqs,
    }
    return pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA)).lazy()


def _make_external_rating_row(
    rating_reference: str,
    counterparty_reference: str,
    rating_agency: str,
    rating_value: str,
    cqs: int,
    rating_date: _date,
) -> pl.LazyFrame:
    """
    Return a one-row external ratings LazyFrame.

    ``is_solicited=True`` (standard for ECRA use).
    ``pd=None`` — external ratings carry no PD.
    ``is_short_term=False`` — all five scenarios use long-term tenor ratings.
    """
    row = {
        "rating_reference": rating_reference,
        "counterparty_reference": counterparty_reference,
        "rating_type": "external",
        "rating_agency": rating_agency,
        "rating_value": rating_value,
        "cqs": cqs,
        "pd": None,
        "rating_date": rating_date,
        "is_solicited": True,
        "model_id": None,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(RATINGS_SCHEMA)).lazy()


def _empty_facilities() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA))


def _empty_loans() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA))


def _empty_facility_mappings() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _empty_lending_mappings() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


# ---------------------------------------------------------------------------
# Public bundle-assembly helpers — one per scenario.
# ---------------------------------------------------------------------------


def build_raw_data_bundle_ccr_e1() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle for CCR-E1 (CRR institution, CQS 2).

    Counterparty CP_E1: entity_type="institution", GB, institution_cqs=2.
    Rating: external, S&P "A" = CQS 2.
    Trade T_E1: 10y GBP IR swap (start 2026-01-15, maturity 2036-01-15).
    Netting set NS_E1: CP_E1, legally enforceable, unmargined.

    Expected pipeline output:
        exposure_class     = institution
        approach_applied   = standardised
        risk_weight        = 0.50  (CRR Art. 120(1) Table 3, CQS 2)
        ead_final          ~ 5,480,017.519
        rwa_final          ~ 2,740,008.760

    References:
        - CRR Art. 120(1) Table 3 (institution CQS 2 -> 50% RW)
        - CRR Art. 274(2) (SA-CCR EAD formula)
    """
    trade = _make_crr_trade(CCR_E1_TRADE_ID, CCR_E1_NETTING_SET_ID)
    netting_set = _make_netting_set(CCR_E1_NETTING_SET_ID, CCR_E1_COUNTERPARTY_REF)
    counterparty = _make_counterparty_row(
        counterparty_reference=CCR_E1_COUNTERPARTY_REF,
        counterparty_name="CCR-E1 Institution (CQS 2, CRR)",
        entity_type=CCR_E1_ENTITY_TYPE,
        country_code=CCR_E1_COUNTRY_CODE,
        institution_cqs=CCR_E1_INSTITUTION_CQS,
    )
    rating = _make_external_rating_row(
        rating_reference=CCR_E1_RATING_REF,
        counterparty_reference=CCR_E1_COUNTERPARTY_REF,
        rating_agency=CCR_E1_RATING_AGENCY,
        rating_value=CCR_E1_RATING_VALUE,
        cqs=CCR_E1_RATING_CQS,
        rating_date=E_CRR_START_DATE,
    )
    return make_raw_bundle(
        counterparties=counterparty,
        facilities=_empty_facilities(),
        loans=_empty_loans(),
        facility_mappings=_empty_facility_mappings(),
        lending_mappings=_empty_lending_mappings(),
        ratings=rating,
        ccr=_make_raw_ccr_bundle(trade, netting_set),
    )


def build_raw_data_bundle_ccr_e2() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle for CCR-E2 (CRR corporate, CQS 3).

    Counterparty CP_E2: entity_type="corporate", GB.
    Rating: external, S&P "BBB" = CQS 3.
    Trade T_E2: 10y GBP IR swap (start 2026-01-15, maturity 2036-01-15).
    Netting set NS_E2: CP_E2, legally enforceable, unmargined.

    Expected pipeline output:
        exposure_class     = corporate
        approach_applied   = standardised
        risk_weight        = 1.00  (CRR Art. 122(1), CQS 3)
        ead_final          ~ 5,480,017.519  (same EAD as E1 — class-invariant)
        rwa_final          ~ 5,480,017.519

    References:
        - CRR Art. 122(1) (corporate CQS 3 -> 100% RW)
        - CRR Art. 274(2) (SA-CCR EAD formula)
    """
    trade = _make_crr_trade(CCR_E2_TRADE_ID, CCR_E2_NETTING_SET_ID)
    netting_set = _make_netting_set(CCR_E2_NETTING_SET_ID, CCR_E2_COUNTERPARTY_REF)
    counterparty = _make_counterparty_row(
        counterparty_reference=CCR_E2_COUNTERPARTY_REF,
        counterparty_name="CCR-E2 Corporate (CQS 3, CRR)",
        entity_type=CCR_E2_ENTITY_TYPE,
        country_code=CCR_E2_COUNTRY_CODE,
    )
    rating = _make_external_rating_row(
        rating_reference=CCR_E2_RATING_REF,
        counterparty_reference=CCR_E2_COUNTERPARTY_REF,
        rating_agency=CCR_E2_RATING_AGENCY,
        rating_value=CCR_E2_RATING_VALUE,
        cqs=CCR_E2_RATING_CQS,
        rating_date=E_CRR_START_DATE,
    )
    return make_raw_bundle(
        counterparties=counterparty,
        facilities=_empty_facilities(),
        loans=_empty_loans(),
        facility_mappings=_empty_facility_mappings(),
        lending_mappings=_empty_lending_mappings(),
        ratings=rating,
        ccr=_make_raw_ccr_bundle(trade, netting_set),
    )


def build_raw_data_bundle_ccr_e3() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle for CCR-E3 (CRR sovereign, BR, CQS 3).

    Counterparty CP_E3: entity_type="sovereign", country_code="BR" (foreign).
    BR is not GB or EU — Art. 114(4) domestic-currency 0% branch does NOT fire.
    Rating: external, S&P "BBB" = CQS 3 (sovereign risk-weight table).
    Trade T_E3: 10y GBP IR swap (start 2026-01-15, maturity 2036-01-15).
    Netting set NS_E3: CP_E3, legally enforceable, unmargined.

    Expected pipeline output (if CQS inheritance is working correctly):
        exposure_class     = central_govt_central_bank
        approach_applied   = standardised
        risk_weight        = 0.50  (CRR Art. 114(1) Table 1, CQS 3, non-domestic)
        ead_final          ~ 5,480,017.519  (same EAD as E1/E2 — class-invariant)
        rwa_final          ~ 2,740,008.760

    ROUTING RISK: the sovereign CQS inheritance path in _enrich_ccr_rows_with_ratings
    is not pinned by any prior test. If the engine returns 100% (unrated fallback) instead
    of 50%, that is a genuine routing gap — NOT a fixture defect. The test must assert
    50% so the gap surfaces. See proposal routing-risk note.

    References:
        - CRR Art. 114(1) Table 1 (sovereign CQS 3 -> 50%)
        - CRR Art. 274(2) (SA-CCR EAD formula)
    """
    trade = _make_crr_trade(CCR_E3_TRADE_ID, CCR_E3_NETTING_SET_ID)
    netting_set = _make_netting_set(CCR_E3_NETTING_SET_ID, CCR_E3_COUNTERPARTY_REF)
    counterparty = _make_counterparty_row(
        counterparty_reference=CCR_E3_COUNTERPARTY_REF,
        counterparty_name="CCR-E3 Sovereign (BR, CQS 3, CRR)",
        entity_type=CCR_E3_ENTITY_TYPE,
        country_code=CCR_E3_COUNTRY_CODE,
        institution_cqs=None,  # sovereign — no institution_cqs
    )
    rating = _make_external_rating_row(
        rating_reference=CCR_E3_RATING_REF,
        counterparty_reference=CCR_E3_COUNTERPARTY_REF,
        rating_agency=CCR_E3_RATING_AGENCY,
        rating_value=CCR_E3_RATING_VALUE,
        cqs=CCR_E3_RATING_CQS,
        rating_date=E_CRR_START_DATE,
    )
    return make_raw_bundle(
        counterparties=counterparty,
        facilities=_empty_facilities(),
        loans=_empty_loans(),
        facility_mappings=_empty_facility_mappings(),
        lending_mappings=_empty_lending_mappings(),
        ratings=rating,
        ccr=_make_raw_ccr_bundle(trade, netting_set),
    )


def build_raw_data_bundle_ccr_e4() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle for CCR-E4 (B3.1 institution, CQS 2, ECRA).

    Counterparty CP_E4: entity_type="institution", GB, institution_cqs=2.
    Rating: external, S&P "A" = CQS 2.
    Trade T_E4: 10y GBP IR swap (start 2027-01-15, maturity 2037-01-15).
    Netting set NS_E4: CP_E4, legally enforceable, unmargined.

    Expected pipeline output:
        exposure_class     = institution
        approach_applied   = standardised
        risk_weight        = 0.30  (PS1/26 Art. 120(2) Table 3, CQS 2, tenor > 3m, ECRA)
        ead_final          ~ 5,480,017.519  (same EAD as CRR scenarios, rel 1e-6)
        rwa_final          ~ 1,644,005.256

    CRR vs B3.1 RW delta: 0.50 (E1) vs 0.30 (E4) — confirms framework routing.

    References:
        - PS1/26 Art. 120(2) Table 3 (institution CQS 2 -> 30% ECRA, tenor > 3m)
        - PS1/26 Art. 274(2) (SA-CCR EAD formula, alpha=1.4)
    """
    trade = _make_b31_trade(CCR_E4_TRADE_ID, CCR_E4_NETTING_SET_ID)
    netting_set = _make_netting_set(CCR_E4_NETTING_SET_ID, CCR_E4_COUNTERPARTY_REF)
    counterparty = _make_counterparty_row(
        counterparty_reference=CCR_E4_COUNTERPARTY_REF,
        counterparty_name="CCR-E4 Institution (CQS 2, B3.1 ECRA)",
        entity_type=CCR_E4_ENTITY_TYPE,
        country_code=CCR_E4_COUNTRY_CODE,
        institution_cqs=CCR_E4_INSTITUTION_CQS,
    )
    rating = _make_external_rating_row(
        rating_reference=CCR_E4_RATING_REF,
        counterparty_reference=CCR_E4_COUNTERPARTY_REF,
        rating_agency=CCR_E4_RATING_AGENCY,
        rating_value=CCR_E4_RATING_VALUE,
        cqs=CCR_E4_RATING_CQS,
        rating_date=E_B31_START_DATE,
    )
    return make_raw_bundle(
        counterparties=counterparty,
        facilities=_empty_facilities(),
        loans=_empty_loans(),
        facility_mappings=_empty_facility_mappings(),
        lending_mappings=_empty_lending_mappings(),
        ratings=rating,
        ccr=_make_raw_ccr_bundle(trade, netting_set),
    )


def build_raw_data_bundle_ccr_e5() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle for CCR-E5 (B3.1 corporate, CQS 3).

    Counterparty CP_E5: entity_type="corporate", GB.
    Rating: external, S&P "BBB" = CQS 3.
    Trade T_E5: 10y GBP IR swap (start 2027-01-15, maturity 2037-01-15).
    Netting set NS_E5: CP_E5, legally enforceable, unmargined.

    Expected pipeline output:
        exposure_class     = corporate
        approach_applied   = standardised
        risk_weight        = 0.75  (PS1/26 Art. 122(2) Table 6, CQS 3)
        ead_final          ~ 5,480,017.519  (same EAD as E4 — class-invariant)
        rwa_final          ~ 4,110,013.139

    CRR vs B3.1 RW delta: 1.00 (E2) vs 0.75 (E5) — confirms framework routing.

    References:
        - PS1/26 Art. 122(2) Table 6 (corporate CQS 3 -> 75%)
        - PS1/26 Art. 274(2) (SA-CCR EAD formula, alpha=1.4)
    """
    trade = _make_b31_trade(CCR_E5_TRADE_ID, CCR_E5_NETTING_SET_ID)
    netting_set = _make_netting_set(CCR_E5_NETTING_SET_ID, CCR_E5_COUNTERPARTY_REF)
    counterparty = _make_counterparty_row(
        counterparty_reference=CCR_E5_COUNTERPARTY_REF,
        counterparty_name="CCR-E5 Corporate (CQS 3, B3.1)",
        entity_type=CCR_E5_ENTITY_TYPE,
        country_code=CCR_E5_COUNTRY_CODE,
    )
    rating = _make_external_rating_row(
        rating_reference=CCR_E5_RATING_REF,
        counterparty_reference=CCR_E5_COUNTERPARTY_REF,
        rating_agency=CCR_E5_RATING_AGENCY,
        rating_value=CCR_E5_RATING_VALUE,
        cqs=CCR_E5_RATING_CQS,
        rating_date=E_B31_START_DATE,
    )
    return make_raw_bundle(
        counterparties=counterparty,
        facilities=_empty_facilities(),
        loans=_empty_loans(),
        facility_mappings=_empty_facility_mappings(),
        lending_mappings=_empty_lending_mappings(),
        ratings=rating,
        ccr=_make_raw_ccr_bundle(trade, netting_set),
    )


# ---------------------------------------------------------------------------
# Smoke-check — called by generate_all.py.
# ---------------------------------------------------------------------------


def save_p845_fixtures() -> list[tuple[str, int]]:
    """
    Smoke-check all five P8.45 bundles and return a generation report.

    This is a Python-only builder: the five scenarios share the same underlying
    trade/NS parquet columns as the CCR-A1 golden, so writing separate parquet
    files would duplicate CCR-A1 data with different IDs. The scenarios differ
    only in counterparty/rating rows and trade IDs, which are built in-memory
    and passed to the pipeline at test time.

    Invariants checked:
        For each of the five bundles:
        1. bundle.ccr is not None.
        2. Trades frame has exactly 1 row with the correct trade_id.
        3. Trade notional = 100,000,000, currency = GBP, delta = 1.0, mtm_value = 0.0.
        4. Netting-set frame has 1 row: is_legally_enforceable=True, is_margined=False.
        5. Margin-agreements frame has 0 rows.
        6. CCR-collateral frame has 0 rows.
        7. Counterparty frame has 1 row with the correct entity_type and country_code.
        8. Rating frame has 1 row with the correct cqs value.
        9. EAD anchor constant is consistent with pfe_addon and RC hand-calc.
        10. Expected RWA constants are consistent with EAD_anchor x RW.
    """
    scenarios = [
        ("CCR-E1", build_raw_data_bundle_ccr_e1, CCR_E1_TRADE_ID, CCR_E1_NETTING_SET_ID,
         CCR_E1_COUNTERPARTY_REF, CCR_E1_ENTITY_TYPE, CCR_E1_COUNTRY_CODE, CCR_E1_RATING_CQS),
        ("CCR-E2", build_raw_data_bundle_ccr_e2, CCR_E2_TRADE_ID, CCR_E2_NETTING_SET_ID,
         CCR_E2_COUNTERPARTY_REF, CCR_E2_ENTITY_TYPE, CCR_E2_COUNTRY_CODE, CCR_E2_RATING_CQS),
        ("CCR-E3", build_raw_data_bundle_ccr_e3, CCR_E3_TRADE_ID, CCR_E3_NETTING_SET_ID,
         CCR_E3_COUNTERPARTY_REF, CCR_E3_ENTITY_TYPE, CCR_E3_COUNTRY_CODE, CCR_E3_RATING_CQS),
        ("CCR-E4", build_raw_data_bundle_ccr_e4, CCR_E4_TRADE_ID, CCR_E4_NETTING_SET_ID,
         CCR_E4_COUNTERPARTY_REF, CCR_E4_ENTITY_TYPE, CCR_E4_COUNTRY_CODE, CCR_E4_RATING_CQS),
        ("CCR-E5", build_raw_data_bundle_ccr_e5, CCR_E5_TRADE_ID, CCR_E5_NETTING_SET_ID,
         CCR_E5_COUNTERPARTY_REF, CCR_E5_ENTITY_TYPE, CCR_E5_COUNTRY_CODE, CCR_E5_RATING_CQS),
    ]

    for label, builder, trade_id, ns_id, cp_ref, entity_type, country_code, rating_cqs in scenarios:
        bundle = builder()

        # Invariant 1: CCR bundle present.
        if bundle.ccr is None:
            raise AssertionError(f"{label}: bundle.ccr must not be None")

        trades_df = bundle.ccr.trades.trades.collect()
        ns_df = bundle.ccr.netting_sets.netting_sets.collect()
        margin_df = bundle.ccr.margin_agreements.margin_agreements.collect()
        collateral_df = bundle.ccr.ccr_collateral.ccr_collateral.collect()
        cp_df = bundle.counterparties.collect()
        rating_df = (
            bundle.ratings.collect() if bundle.ratings is not None else pl.DataFrame()
        )

        # Invariant 2: exactly 1 trade row.
        if trades_df.height != 1:
            raise AssertionError(f"{label}: expected 1 trade row, got {trades_df.height}")
        if trades_df["trade_id"][0] != trade_id:
            raise AssertionError(
                f"{label}: trade_id must be {trade_id!r} (got {trades_df['trade_id'][0]!r})"
            )

        # Invariant 3: trade economics.
        if trades_df["notional"][0] != E_NOTIONAL:
            raise AssertionError(
                f"{label}: notional must be {E_NOTIONAL} (got {trades_df['notional'][0]})"
            )
        if trades_df["currency"][0] != E_CURRENCY:
            raise AssertionError(
                f"{label}: currency must be {E_CURRENCY!r} (got {trades_df['currency'][0]!r})"
            )
        if trades_df["delta"][0] != E_DELTA:
            raise AssertionError(
                f"{label}: delta must be {E_DELTA} (got {trades_df['delta'][0]})"
            )
        if trades_df["mtm_value"][0] != E_MTM:
            raise AssertionError(
                f"{label}: mtm_value must be {E_MTM} (got {trades_df['mtm_value'][0]})"
            )

        # Invariant 4: netting set.
        if ns_df.height != 1:
            raise AssertionError(f"{label}: expected 1 NS row, got {ns_df.height}")
        if ns_df["netting_set_id"][0] != ns_id:
            raise AssertionError(
                f"{label}: netting_set_id must be {ns_id!r} (got {ns_df['netting_set_id'][0]!r})"
            )
        if ns_df["is_legally_enforceable"][0] is not True:
            raise AssertionError(f"{label}: is_legally_enforceable must be True")
        if ns_df["is_margined"][0] is not False:
            raise AssertionError(f"{label}: is_margined must be False")

        # Invariant 5: empty margin.
        if margin_df.height != 0:
            raise AssertionError(
                f"{label}: margin_agreements must be empty (got {margin_df.height})"
            )

        # Invariant 6: empty collateral.
        if collateral_df.height != 0:
            raise AssertionError(
                f"{label}: ccr_collateral must be empty (got {collateral_df.height})"
            )

        # Invariant 7: counterparty.
        if cp_df.height != 1:
            raise AssertionError(f"{label}: expected 1 counterparty row, got {cp_df.height}")
        if cp_df["counterparty_reference"][0] != cp_ref:
            raise AssertionError(
                f"{label}: counterparty_reference must be {cp_ref!r}"
            )
        if cp_df["entity_type"][0] != entity_type:
            raise AssertionError(
                f"{label}: entity_type must be {entity_type!r} (got {cp_df['entity_type'][0]!r})"
            )
        if cp_df["country_code"][0] != country_code:
            raise AssertionError(
                f"{label}: country_code must be {country_code!r} (got {cp_df['country_code'][0]!r})"
            )

        # Invariant 8: rating.
        if rating_df.height != 1:
            raise AssertionError(f"{label}: expected 1 rating row, got {rating_df.height}")
        if rating_df["cqs"][0] != rating_cqs:
            raise AssertionError(
                f"{label}: rating cqs must be {rating_cqs} (got {rating_df['cqs'][0]})"
            )
        if rating_df["rating_type"][0] != "external":
            raise AssertionError(
                f"{label}: rating_type must be 'external' (got {rating_df['rating_type'][0]!r})"
            )

    # Invariant 9: EAD anchor hand-calc consistency.
    _alpha = 1.4
    computed_ead = _alpha * (E_RC_ANCHOR + E_PFE_ADDON_ANCHOR)
    if abs(computed_ead - E_EAD_ANCHOR) > 1e-3:
        raise AssertionError(
            f"EAD anchor mismatch: alpha x (RC + PFE) = {computed_ead} != {E_EAD_ANCHOR}"
        )

    # Invariant 10: expected RWA constants consistent with EAD x RW.
    for label, rw, expected_rwa in [
        ("CCR-E1", CCR_E1_EXPECTED_RW, CCR_E1_EXPECTED_RWA),
        ("CCR-E2", CCR_E2_EXPECTED_RW, CCR_E2_EXPECTED_RWA),
        ("CCR-E3", CCR_E3_EXPECTED_RW, CCR_E3_EXPECTED_RWA),
        ("CCR-E4", CCR_E4_EXPECTED_RW, CCR_E4_EXPECTED_RWA),
        ("CCR-E5", CCR_E5_EXPECTED_RW, CCR_E5_EXPECTED_RWA),
    ]:
        computed = E_EAD_ANCHOR * rw
        if abs(computed - expected_rwa) > 1e-3:
            raise AssertionError(
                f"{label}: expected_rwa {expected_rwa} != EAD_anchor x RW = {computed}"
            )

    # Python-only builder — no parquet files written.
    from tests.fixtures.generate_all import PYTHON_ONLY_NO_PARQUET  # noqa: PLC0415

    return [(PYTHON_ONLY_NO_PARQUET, 0)]


def main() -> None:
    """Entry point for standalone generation and smoke-check."""
    results = save_p845_fixtures()
    print("P8.45 / CCR-E1..E5 fixture smoke-check complete")
    print("-" * 70)
    print(f"  Result: {results[0][0]}")
    print("-" * 70)
    print("Scenarios:")
    for label, rw, rwa in [
        ("CCR-E1 (CRR institution,   CQS 2)", CCR_E1_EXPECTED_RW, CCR_E1_EXPECTED_RWA),
        ("CCR-E2 (CRR corporate,     CQS 3)", CCR_E2_EXPECTED_RW, CCR_E2_EXPECTED_RWA),
        ("CCR-E3 (CRR sovereign BR,  CQS 3)", CCR_E3_EXPECTED_RW, CCR_E3_EXPECTED_RWA),
        ("CCR-E4 (B3.1 institution,  CQS 2)", CCR_E4_EXPECTED_RW, CCR_E4_EXPECTED_RWA),
        ("CCR-E5 (B3.1 corporate,    CQS 3)", CCR_E5_EXPECTED_RW, CCR_E5_EXPECTED_RWA),
    ]:
        print(f"  {label:<40}  RW={rw:.2f}  RWA={rwa:>14,.3f}")
    print()
    print(f"  Shared EAD anchor: {E_EAD_ANCHOR:,.3f}  (RC={E_RC_ANCHOR}, PFE={E_PFE_ADDON_ANCHOR:,.3f})")
    print()
    print("Config factories:")
    crr_cfg = make_crr_config()
    b31_cfg = make_b31_config()
    print(f"  make_crr_config():  regime_id={crr_cfg.regime_id!r}, reporting_date={crr_cfg.reporting_date}")
    print(f"  make_b31_config():  regime_id={b31_cfg.regime_id!r}, reporting_date={b31_cfg.reporting_date}")


if __name__ == "__main__":
    main()
