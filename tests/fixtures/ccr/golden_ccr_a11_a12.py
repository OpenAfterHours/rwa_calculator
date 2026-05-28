"""
Golden CCR-A11 / CCR-A12 scenarios: SA-CCR SFT EAD via FCCM (CRR Art. 271(2)).

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/)
    -> engine-implementer (CCR FCCM SFT branch)

Scenario design (plan item P8.38, scenarios CCR-A11 and CCR-A12):

    Both scenarios share the same single SFT trade booked as ``transaction_type="sft"``,
    ``asset_class="credit"``, against counterparty ``CP_INST_001`` (institution, CQS 2, GB).
    The exposure side is a corporate bond (CQS 1, residual maturity 7y) lending.

    Reporting date: 2026-06-30 (CRR window, pre-PS1/26 effective date).
    Framework: CRR, permission_mode=STANDARDISED, CCRConfig.sft_method="fccm".

    CCR-A11 — uncollateralised SFT
        No collateral posted/received; E* = E·(1 + HE).

    CCR-A12 — cash-collateralised SFT
        GBP 60m cash collateral received; HC_cash=0, HFX=0 (GBP/GBP).

Regulatory hand-calc (CRR Art. 223(5) + Art. 224 Table 1 + Art. 226(2)):

    E (notional)  = 60_700_000.00

    HE derivation:
        Exposure-side security: corp_bond, CQS 1, residual maturity 7y -> "5y_plus" band.
        H_10  = 0.08  (Art. 224 Table 1: debt sec, CQS 1, >5y residual)
        Liquidation period for SFTs: 5 business days (Art. 224(2)(c)).
        Scaling: H_m = H_10 x sqrt(T_m / 10)  (Art. 226(2))
                     = 0.08 x sqrt(5/10)
                     = 0.08 x 0.7071067811865476
                     = 0.05656854249492381   [IEEE-754 correctly rounded]

    E*(1 + HE) = 60_700_000 x 1.05656854249492381 = 64_133_710.52944188 (Python float)

    CCR-A11 (no collateral):
        CVA * (1 - HC - HFX) = 0
        E* = max(0, 64_133_710.529 - 0) = 64_133_710.52944188
        EAD  = 64_133_710.52944188
        RWA  = EAD x 0.50 = 32_066_855.26472094

    CCR-A12 (GBP 60m cash collateral):
        HC_cash = 0 ; HFX = 0 (GBP/GBP same currency)
        CVA * (1 - 0 - 0) = 60_000_000.00
        E* = max(0, 64_133_710.529 - 60_000_000) = 4_133_710.52944188
        EAD  = 4_133_710.52944188
        RWA  = EAD x 0.50 = 2_066_855.26472094

    Note: The scenario-architect proposal stated HE = 0.056568542494923804, but
    Python IEEE-754 arithmetic gives 0.05656854249492381 (last digit differs by 1 ULP).
    The fixture uses math.sqrt for ground-truth values; test-writer must reference the
    module constants (CCR_A11_EAD, CCR_A12_EAD, etc.) rather than the proposal literals.

Counterparty:
    CP_INST_001 — institution, CQS 2, GB.
    SA risk weight: CRR Art. 120 Table 3 → CQS 2 → 50%.

    NOTE: The counterparty reference ``CP_INST_001`` used here is distinct from the
    ``CP_001`` used by CCR-A1/A3/A10 golden scenarios. A fresh counterparty builder
    is provided so this module is self-contained and does not collide with existing
    golden scenario CP_001 data.

Trade HE input columns (not yet in TRADE_SCHEMA — engine-implementer will add them):
    exposure_collateral_type              String (nullable)  — "corp_bond" for A11/A12
    exposure_security_cqs                 Int8   (nullable)  — 1
    exposure_security_residual_maturity_years  Float64 (nullable) — 7.0

References:
    - CRR Art. 271(2) — SFT EAD computed via FCCM (not SA-CCR Art. 274).
    - CRR Art. 220(1)(a) — single-counterparty SFT / master-netting set scope.
    - CRR Art. 220(3)(a)(i) — standardised supervisory haircuts.
    - CRR Art. 223(5) — E* = max(0, E·(1+HE) − CVA·(1−HC−HFX)).
    - CRR Art. 224(2)(c) — 5-BD liquidation period for SFTs.
    - CRR Art. 224 Table 1 — H_10 = 0.08 for corp bond CQS 1 residual > 5y.
    - CRR Art. 226(2) — H_m = H_10 × √(T_m / 10) haircut scaling.
    - CRR Art. 120 Table 3 — institution CQS 2 → 50% SA risk weight.
    - PRA PS1/26 Art. 271/220-223 — verbatim carry-forward of CRR FCCM mechanics.
"""

from __future__ import annotations

import math
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
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
    TRADE_SCHEMA,
)

from .margin_builder import create_margin_agreements
from .netting_set_builder import NettingSet, create_netting_sets

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

# Counterparty
CCR_A11_A12_COUNTERPARTY_REF: str = "CP_INST_001"
CCR_A11_A12_CP_ENTITY_TYPE: str = "institution"
CCR_A11_A12_CP_COUNTRY_CODE: str = "GB"
CCR_A11_A12_CP_INSTITUTION_CQS: int = 2

# Rating
CCR_A11_A12_RATING_REF: str = "RTG_INST_001"
CCR_A11_A12_RATING_TYPE: str = "external"
CCR_A11_A12_RATING_AGENCY: str = "S&P"
CCR_A11_A12_RATING_VALUE: str = "A"
CCR_A11_A12_RATING_DATE: _date = _date(2026, 1, 15)

# Shared trade / netting-set parameters
CCR_A11_TRADE_ID: str = "T_SFT_001"
CCR_A12_TRADE_ID: str = "T_SFT_002"
CCR_A11_NETTING_SET_ID: str = "NS_SFT_001"
CCR_A12_NETTING_SET_ID: str = "NS_SFT_002"
CCR_A11_A12_TRANSACTION_TYPE: str = "sft"
CCR_A11_A12_ASSET_CLASS: str = "credit"
CCR_A11_A12_NOTIONAL: float = 60_700_000.00
CCR_A11_A12_CURRENCY: str = "GBP"
CCR_A11_A12_MTM: float = 0.0
CCR_A11_A12_DELTA: float = 1.0
CCR_A11_A12_IS_LONG: bool = True
CCR_A11_A12_START_DATE: _date = _date(2026, 6, 30)
CCR_A11_A12_MATURITY_DATE: _date = _date(2026, 9, 30)
CCR_A11_A12_IS_LEGALLY_ENFORCEABLE: bool = True
CCR_A11_A12_IS_MARGINED: bool = False

# Exposure-side HE inputs (corp bond CQS 1, residual > 5y — "5y_plus" haircut band)
# These columns are NOT yet in TRADE_SCHEMA; they are appended as nullable extras
# by create_ccr_a11_trades() / create_ccr_a12_trades() for engine-implementer pickup.
CCR_A11_A12_EXPOSURE_COLLATERAL_TYPE: str = "corp_bond"
CCR_A11_A12_EXPOSURE_SECURITY_CQS: int = 1
CCR_A11_A12_EXPOSURE_SECURITY_RESIDUAL_MATURITY_YEARS: float = 7.0

# CCR-A12 collateral parameters
CCR_A12_COLLATERAL_REF: str = "COLL_SFT_001"
CCR_A12_COLLATERAL_TYPE: str = "cash"
CCR_A12_COLLATERAL_MARKET_VALUE: float = 60_000_000.00
CCR_A12_COLLATERAL_CURRENCY: str = "GBP"

# ---------------------------------------------------------------------------
# Hand-calculated expected outputs — single source of truth.
# ---------------------------------------------------------------------------

# HE calculation (Art. 224 Table 1 + Art. 226(2)):
#   H_10 = 0.08 (corp_bond CQS 1, residual > 5y)
#   liquidation_period = 5 BD (Art. 224(2)(c) SFT floor)
#   HE = H_10 × √(5/10)
CCR_A11_A12_H10: float = 0.08
CCR_A11_A12_LIQUIDATION_PERIOD_BD: int = 5
CCR_A11_A12_HE: float = CCR_A11_A12_H10 * math.sqrt(CCR_A11_A12_LIQUIDATION_PERIOD_BD / 10)
# = 0.056568542494923804

# E·(1+HE) — common to both scenarios
CCR_A11_A12_E_TIMES_1_PLUS_HE: float = CCR_A11_A12_NOTIONAL * (1.0 + CCR_A11_A12_HE)
# = 64_133_710.4314378749

# CCR-A11 — uncollateralised
CCR_A11_EAD: float = CCR_A11_A12_E_TIMES_1_PLUS_HE
# = 64_133_710.4314378749
CCR_A11_RISK_WEIGHT: float = 0.50
CCR_A11_RWA: float = CCR_A11_EAD * CCR_A11_RISK_WEIGHT
# = 32_066_855.2157189374

# CCR-A12 — GBP cash collateral (HC=0, HFX=0)
CCR_A12_CVA_NET: float = CCR_A12_COLLATERAL_MARKET_VALUE  # × (1 − 0 − 0) = 60_000_000
CCR_A12_EAD: float = max(0.0, CCR_A11_A12_E_TIMES_1_PLUS_HE - CCR_A12_CVA_NET)
# = 4_133_710.4314378749
CCR_A12_RISK_WEIGHT: float = 0.50
CCR_A12_RWA: float = CCR_A12_EAD * CCR_A12_RISK_WEIGHT
# = 2_066_855.2157189374

# Monetary tolerance for acceptance assertions (1 ppm, consistent with other goldens).
CCR_A11_A12_MONETARY_REL_TOLERANCE: float = 1e-6

# Expected output identifiers (matching pipeline_adapter format for SFT FCCM rows)
CCR_A11_EXPOSURE_REFERENCE: str = "ccr__NS_SFT_001"
CCR_A12_EXPOSURE_REFERENCE: str = "ccr__NS_SFT_002"
CCR_A11_A12_CCR_METHOD: str = "fccm_sft"
CCR_A11_A12_RISK_TYPE: str = "CCR_SFT"
CCR_A11_A12_EXPOSURE_CLASS_SA: str = "institution"


# ---------------------------------------------------------------------------
# Trade builders.
# ---------------------------------------------------------------------------


def _base_sft_trade_dict(trade_id: str, netting_set_id: str) -> dict:
    """
    Return a plain dict for one SFT trade row, typed to TRADE_SCHEMA.

    The three exposure-side HE columns (``exposure_collateral_type``,
    ``exposure_security_cqs``, ``exposure_security_residual_maturity_years``)
    are NOT part of TRADE_SCHEMA today but are included as extra keys so that
    engine-implementer can consume them from the parquet file once the schema
    is extended (P8.38 engine step).

    References:
        CRR Art. 271(2) — SFT scope: transaction_type="sft".
        CRR Art. 223(5) — HE inputs on the exposure side.
    """
    return {
        "trade_id": trade_id,
        "netting_set_id": netting_set_id,
        "asset_class": CCR_A11_A12_ASSET_CLASS,
        "transaction_type": CCR_A11_A12_TRANSACTION_TYPE,
        "notional": CCR_A11_A12_NOTIONAL,
        "currency": CCR_A11_A12_CURRENCY,
        "maturity_date": CCR_A11_A12_MATURITY_DATE,
        "start_date": CCR_A11_A12_START_DATE,
        "delta": CCR_A11_A12_DELTA,
        "is_long": CCR_A11_A12_IS_LONG,
        "mtm_value": CCR_A11_A12_MTM,
        "is_long_settlement": False,
        "underlying_reference": None,
        "option_strike": None,
        "option_type": None,
        "option_underlying_price": None,
        "cdo_attachment": None,
        "cdo_detachment": None,
        "payment_leg_index_id": None,
        "is_client_cleared": False,
        "is_specific_wwr": False,
        "notional_leg2": None,
        "currency_leg2": None,
        "market_price": None,
        "number_of_units": None,
        "reference_entity": None,
        "commodity_type": None,
        "is_index": None,
        "credit_quality": None,
    }


def create_ccr_a11_trades() -> pl.DataFrame:
    """
    Return the single-row trades DataFrame for CCR-A11 (uncollateralised SFT).

    Emits the base TRADE_SCHEMA columns plus three SFT HE input columns as
    nullable extras (not yet in TRADE_SCHEMA; engine-implementer will register
    them during P8.38 engine implementation):

        exposure_collateral_type              Utf8   — "corp_bond"
        exposure_security_cqs                 Int8   — 1
        exposure_security_residual_maturity_years  Float64 — 7.0

    References:
        CRR Art. 271(2) — SFT branch.
        CRR Art. 224 Table 1, Art. 226(2) — HE lookups keyed on these fields.
    """
    base = pl.DataFrame(
        [_base_sft_trade_dict(CCR_A11_TRADE_ID, CCR_A11_NETTING_SET_ID)],
        schema=dtypes_of(TRADE_SCHEMA),
    )
    return base.with_columns(
        pl.lit(CCR_A11_A12_EXPOSURE_COLLATERAL_TYPE)
        .cast(pl.String)
        .alias("exposure_collateral_type"),
        pl.lit(CCR_A11_A12_EXPOSURE_SECURITY_CQS).cast(pl.Int8).alias("exposure_security_cqs"),
        pl.lit(CCR_A11_A12_EXPOSURE_SECURITY_RESIDUAL_MATURITY_YEARS)
        .cast(pl.Float64)
        .alias("exposure_security_residual_maturity_years"),
    )


def create_ccr_a12_trades() -> pl.DataFrame:
    """
    Return the single-row trades DataFrame for CCR-A12 (cash-collateralised SFT).

    Identical to CCR-A11 trades except trade_id / netting_set_id.
    The collateral (GBP 60m cash) is captured in create_ccr_a12_ccr_collateral(),
    not on the trade row.

    References:
        CRR Art. 271(2), Art. 223(5) — collateral term reduces E*.
    """
    base = pl.DataFrame(
        [_base_sft_trade_dict(CCR_A12_TRADE_ID, CCR_A12_NETTING_SET_ID)],
        schema=dtypes_of(TRADE_SCHEMA),
    )
    return base.with_columns(
        pl.lit(CCR_A11_A12_EXPOSURE_COLLATERAL_TYPE)
        .cast(pl.String)
        .alias("exposure_collateral_type"),
        pl.lit(CCR_A11_A12_EXPOSURE_SECURITY_CQS).cast(pl.Int8).alias("exposure_security_cqs"),
        pl.lit(CCR_A11_A12_EXPOSURE_SECURITY_RESIDUAL_MATURITY_YEARS)
        .cast(pl.Float64)
        .alias("exposure_security_residual_maturity_years"),
    )


# ---------------------------------------------------------------------------
# Netting-set builders.
# ---------------------------------------------------------------------------


def create_ccr_a11_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CCR-A11 (NS_SFT_001)."""
    return create_netting_sets(
        [
            NettingSet(
                netting_set_id=CCR_A11_NETTING_SET_ID,
                counterparty_reference=CCR_A11_A12_COUNTERPARTY_REF,
                is_legally_enforceable=CCR_A11_A12_IS_LEGALLY_ENFORCEABLE,
                is_margined=CCR_A11_A12_IS_MARGINED,
            )
        ]
    )


def create_ccr_a12_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CCR-A12 (NS_SFT_002)."""
    return create_netting_sets(
        [
            NettingSet(
                netting_set_id=CCR_A12_NETTING_SET_ID,
                counterparty_reference=CCR_A11_A12_COUNTERPARTY_REF,
                is_legally_enforceable=CCR_A11_A12_IS_LEGALLY_ENFORCEABLE,
                is_margined=CCR_A11_A12_IS_MARGINED,
            )
        ]
    )


# ---------------------------------------------------------------------------
# CCR-collateral builders.
# ---------------------------------------------------------------------------


def create_ccr_a11_ccr_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-A11: no collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


def create_ccr_a12_ccr_collateral() -> pl.DataFrame:
    """
    Return the single-row CCR-collateral DataFrame for CCR-A12.

    GBP 60m cash collateral received by the firm from CP_INST_001.
    HC_cash = 0 (Art. 224 Table 1 — cash). HFX = 0 (same-currency GBP/GBP).

    References:
        CRR Art. 223(5) — collateral term: CVA·(1 − HC − HFX).
        CRR Art. 224(2)(c) — 5-BD liquidation period for SFTs.
    """
    row = {
        "ccr_collateral_reference": CCR_A12_COLLATERAL_REF,
        "netting_set_id": CCR_A12_NETTING_SET_ID,
        "collateral_type": CCR_A12_COLLATERAL_TYPE,
        "market_value": CCR_A12_COLLATERAL_MARKET_VALUE,
        "is_posted_by_firm": False,  # received from counterparty
        "is_segregated": False,
        "currency": CCR_A12_COLLATERAL_CURRENCY,
        "issuer_cqs": None,
        "issuer_type": None,
        "residual_maturity_years": None,
        "haircut_override": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Portfolio-stub builders (counterparty + rating).
# ---------------------------------------------------------------------------


def _build_cp_inst_001_counterparty() -> pl.LazyFrame:
    """
    Return a one-row counterparty LazyFrame for CP_INST_001.

    CP_INST_001 is a GB institution with external CQS 2.
    entity_type="institution" → Classifier → ExposureClass.INSTITUTION.
    CRR Art. 120(1) Table 3: CQS 2 → 50% SA risk weight.

    institution_cqs=2 is set so narrow unit tests that bypass the rating
    inheritance pipeline can still resolve the risk weight.
    """
    row = {
        "counterparty_reference": CCR_A11_A12_COUNTERPARTY_REF,
        "counterparty_name": "P8.38 SFT Test Institution (CQS 2)",
        "entity_type": CCR_A11_A12_CP_ENTITY_TYPE,
        "country_code": CCR_A11_A12_CP_COUNTRY_CODE,
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": CCR_A11_A12_CP_INSTITUTION_CQS,
    }
    return pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA)).lazy()


def _build_cp_inst_001_rating() -> pl.LazyFrame:
    """
    Return a one-row external ratings LazyFrame for CP_INST_001.

    S&P "A" = CQS 2 under CRR ECRA.
    CRR Art. 120(1) Table 3: institution CQS 2 → 50% risk weight.
    pd=None — external ratings carry no PD.
    """
    row = {
        "rating_reference": CCR_A11_A12_RATING_REF,
        "counterparty_reference": CCR_A11_A12_COUNTERPARTY_REF,
        "rating_type": CCR_A11_A12_RATING_TYPE,
        "rating_agency": CCR_A11_A12_RATING_AGENCY,
        "rating_value": CCR_A11_A12_RATING_VALUE,
        "cqs": CCR_A11_A12_CP_INSTITUTION_CQS,
        "pd": None,
        "rating_date": CCR_A11_A12_RATING_DATE,
        "is_solicited": True,
        "model_id": None,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(RATINGS_SCHEMA)).lazy()


def _build_empty_facilities() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA))


def _build_empty_loans() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA))


def _build_empty_facility_mappings() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _build_empty_lending_mappings() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


def _build_empty_margin_agreements() -> pl.DataFrame:
    return create_margin_agreements([])


# ---------------------------------------------------------------------------
# RawCCRBundle / RawDataBundle assembly helpers.
# ---------------------------------------------------------------------------


def _build_ccr_a11_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle for CCR-A11 (uncollateralised SFT).

        trades            — 1 row  (T_SFT_001, sft, credit, NS_SFT_001)
        netting_sets      — 1 row  (NS_SFT_001, CP_INST_001, enforceable, unmargined)
        margin_agreements — 0 rows (unmargined, no CSA)
        ccr_collateral    — 0 rows (no collateral)
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=create_ccr_a11_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_ccr_a11_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=_build_empty_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_ccr_a11_ccr_collateral().lazy()),
    )


def _build_ccr_a12_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle for CCR-A12 (cash-collateralised SFT).

        trades            — 1 row  (T_SFT_002, sft, credit, NS_SFT_002)
        netting_sets      — 1 row  (NS_SFT_002, CP_INST_001, enforceable, unmargined)
        margin_agreements — 0 rows (unmargined, no CSA)
        ccr_collateral    — 1 row  (COLL_SFT_001, cash, GBP 60m)
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=create_ccr_a12_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_ccr_a12_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=_build_empty_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_ccr_a12_ccr_collateral().lazy()),
    )


def build_raw_data_bundle_ccr_a11() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle for CCR-A11 (uncollateralised SFT).

    The single SFT trade (T_SFT_001, GBP 60.7m, corp bond exposure CQS 1 7y)
    in netting set NS_SFT_001 against CP_INST_001 (institution, CQS 2, GB)
    exercises the Art. 271(2) FCCM SFT branch without any collateral offset.

    Key assertion:
        EAD  = E × (1 + HE) = 64_133_710.4314378749 (Art. 223(5) with CVA=0)
        RWA  = EAD × 0.50   = 32_066_855.2157189374 (Art. 120 Table 3 CQS 2)

    References:
        CRR Art. 271(2), 223(5), 224 Table 1, 226(2), 120 Table 3.
    """
    return RawDataBundle(
        counterparties=_build_cp_inst_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_inst_001_rating(),
        ccr=_build_ccr_a11_raw_ccr_bundle(),
    )


def build_raw_data_bundle_ccr_a12() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle for CCR-A12 (cash-collateralised SFT).

    The single SFT trade (T_SFT_002, GBP 60.7m, corp bond exposure CQS 1 7y)
    in netting set NS_SFT_002 against CP_INST_001 (institution, CQS 2, GB)
    exercises the Art. 271(2) FCCM SFT branch with GBP 60m cash collateral
    received (HC_cash=0, HFX=0 for same-currency pair).

    Key assertion:
        E* = max(0, E·(1+HE) − CVA) = 4_133_710.4314378749 (Art. 223(5))
        EAD  = 4_133_710.4314378749
        RWA  = EAD × 0.50 = 2_066_855.2157189374

    References:
        CRR Art. 271(2), 223(5), 224 Table 1, 226(2), 120 Table 3.
    """
    return RawDataBundle(
        counterparties=_build_cp_inst_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_inst_001_rating(),
        ccr=_build_ccr_a12_raw_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Save helper — canonical entry point for generate_all.py and standalone use.
# ---------------------------------------------------------------------------


def save_ccr_a11_a12_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all CCR-A11 / CCR-A12 golden parquet files to *output_dir*.

    Files produced:
        ccr_a11_trades.parquet          — 1 row  (T_SFT_001, sft/credit, no collateral)
        ccr_a11_netting_sets.parquet    — 1 row  (NS_SFT_001, CP_INST_001)
        ccr_a12_trades.parquet          — 1 row  (T_SFT_002, sft/credit, w/ collateral)
        ccr_a12_netting_sets.parquet    — 1 row  (NS_SFT_002, CP_INST_001)
        ccr_a12_ccr_collateral.parquet  — 1 row  (COLL_SFT_001, cash, GBP 60m)

    The A11 CCR collateral is empty and not written (no collateral case).
    The shared margin_agreements (0-row) is not re-written (no CSA in either case).

    Args:
        output_dir: Target directory. Defaults to the directory containing
            this script (``tests/fixtures/ccr/``).

    Returns:
        Dict mapping artefact name (without .parquet) to saved absolute Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("ccr_a11_trades", create_ccr_a11_trades()),
        ("ccr_a11_netting_sets", create_ccr_a11_netting_sets()),
        ("ccr_a12_trades", create_ccr_a12_trades()),
        ("ccr_a12_netting_sets", create_ccr_a12_netting_sets()),
        ("ccr_a12_ccr_collateral", create_ccr_a12_ccr_collateral()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_ccr_a11_a12_fixtures()
    print("CCR-A11 / CCR-A12 golden fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<35} {df.height:>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
    print("-" * 70)
    he = CCR_A11_A12_HE
    e_times_1_he = CCR_A11_A12_E_TIMES_1_PLUS_HE
    print(f"HE  = {CCR_A11_A12_H10} × sqrt({CCR_A11_A12_LIQUIDATION_PERIOD_BD}/10)")
    print(f"    = {he:.18f}")
    print(f"E·(1+HE) = {CCR_A11_A12_NOTIONAL:,.2f} × (1 + {he:.18f})")
    print(f"         = {e_times_1_he:.10f}")
    print()
    print("CCR-A11 (uncollateralised):")
    print(f"  EAD  = {CCR_A11_EAD:.10f}")
    print(f"  RWA  = {CCR_A11_RWA:.10f}")
    print()
    print("CCR-A12 (GBP 60m cash collateral):")
    print(f"  CVA  = {CCR_A12_CVA_NET:,.2f}")
    print(f"  E*   = max(0, {e_times_1_he:.4f} - {CCR_A12_CVA_NET:,.2f})")
    print(f"  EAD  = {CCR_A12_EAD:.10f}")
    print(f"  RWA  = {CCR_A12_RWA:.10f}")


if __name__ == "__main__":
    main()
