"""
Generate P1.123 fixtures: FCCM exposure volatility haircut (HE) for SFT exposures.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/collateral.py)

Key responsibilities:
- Produce one unrated corporate counterparty (CRR SA, 100% RW).
- Produce three loan rows: one control (standard lending, HE=0), one SFT with a
  debt-security exposure (HE>0), one SFT with cash exposure (HE=0).
- Produce three facilities (one per loan, on-balance-sheet committed).
- Produce three collateral rows (govt_bond CQS 1, direct loan allocation).

Scenario rationale (CRR Art. 223(5)):

    The FCCM formula for the adjusted exposure value is:
        E* = max(0, E(1+HE) - C_VA(1-HC-HFX))

    where HE is the exposure volatility haircut drawn from the same CRR Art. 224
    Table 1 as HC — but applied to the *exposure* side rather than the collateral
    side.  HE is non-zero when the exposure itself is a debt security (e.g., in a
    repo the "lender" hands over a bond — that bond carries its own price volatility
    risk).

    The three loans exercise three paths:

    CRR-P1123-L-CTRL  (is_sft=False, no exposure security):
        HE = 0 (standard secured lending — exposure is a loan, not a security)
        T_m = 20 days (Art. 224(2)(a))
        HC = H_C_10D_GOVT_CQS1_1_5Y × sqrt(20/10) = 2% × sqrt(2) = 2.8284%
        HFX = 0 (GBP/GBP, same currency)
        E* = 1,000,000 - 950,000 × (1 − 0.028284 − 0) = 1,000,000 − 923,130.35 = 76,869.65

    CRR-P1123-L-BIND  (is_sft=True, exposure is corp_bond CQS 2, 4yr):
        HE = H_CORP_CQS2_3_1_5Y_10D × sqrt(5/10) = 6% × sqrt(0.5) = 4.2426%
        T_m = 5 days (Art. 224(2)(c) SFT)
        HC = H_C_10D_GOVT_CQS1_1_5Y × sqrt(5/10) = 2% × sqrt(0.5) = 1.4142%
        HFX = 0 (GBP/GBP)
        E(1+HE) = 1,000,000 × (1 + 0.042426) = 1,042,426.41
        C*(1−HC) = 950,000 × (1 − 0.014142) = 936,565.03
        E* = max(0, 1,042,426.41 − 936,565.03) = 105,861.38

    CRR-P1123-L-RUNB  (is_sft=True, exposure is cash):
        HE = 0 (cash has 0% exposure volatility haircut under Art. 224 Table 1)
        T_m = 5 days (Art. 224(2)(c) SFT)
        HC = H_C_10D_GOVT_CQS1_1_5Y × sqrt(5/10) = 2% × sqrt(0.5) = 1.4142%
        HFX = 0 (GBP/GBP)
        E* = max(0, 1,000,000 − 950,000 × (1 − 0.014142)) = max(0, 1,000,000 − 936,565.03)
           = 63,434.97

    Bug (pre-fix):
        The engine's collateral.py omits the (1+HE) gross-up on the exposure side.
        For CRR-P1123-L-BIND, the engine currently computes:
            E* = max(0, E − C_VA) = max(0, 1,000,000 − 936,565.03) = 63,434.97
        whereas the correct Art. 223(5) result is 105,861.38 (a material understatement
        of 40.28% on this SFT bond-vs-bond position).

    SA risk weight (CRR Art. 122, unrated corporate) = 100%.

References:
    - CRR Art. 223(5): E* = max(0, E(1+HE) - CVA(1-HC-HFX))
    - CRR Art. 224 Table 1: supervisory haircuts for debt securities (10-day base)
    - CRR Art. 224(2)(a): 20-day liquidation period for secured lending
    - CRR Art. 224(2)(c): 5-day liquidation period for repo-style SFTs
    - CRR Art. 226(2): H_m = H_n × sqrt(T_m / 10) liquidation-period scaling
    - CRR Art. 122: corporate SA risk weights (unrated → 100%)
    - src/rwa_calc/data/tables/haircuts.py: COLLATERAL_HAIRCUTS, CRR_HAIRCUT_ROWS
    - src/rwa_calc/engine/crm/collateral.py: FCCM exposure value computation

Usage:
    uv run python tests/fixtures/p1_123/p1_123.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF: str = "CRR-P1123-CP1"

LOAN_REF_CTRL: str = "CRR-P1123-L-CTRL"  # control: is_sft=False, HE=0
LOAN_REF_BIND: str = "CRR-P1123-L-BIND"  # SFT, corp_bond exposure, HE>0
LOAN_REF_RUNB: str = "CRR-P1123-L-RUNB"  # SFT, cash exposure, HE=0

FACILITY_REF_CTRL: str = "CRR-P1123-F-CTRL"
FACILITY_REF_BIND: str = "CRR-P1123-F-BIND"
FACILITY_REF_RUNB: str = "CRR-P1123-F-RUNB"

COLLATERAL_REF_CTRL: str = "CRR-P1123-COLL-CTRL"
COLLATERAL_REF_BIND: str = "CRR-P1123-COLL-BIND"
COLLATERAL_REF_RUNB: str = "CRR-P1123-COLL-RUNB"

VALUE_DATE: date = date(2026, 1, 1)
MATURITY_DATE_CTRL: date = date(2030, 12, 31)
MATURITY_DATE_SFT: date = date(2026, 6, 30)

DRAWN_AMOUNT: float = 1_000_000.0
COLLATERAL_MARKET_VALUE: float = 950_000.0

# ---------------------------------------------------------------------------
# CRR Art. 224 Table 1 — 10-day base haircuts (source of truth for assertions)
# ---------------------------------------------------------------------------

# Collateral: govt_bond, CQS 1, 2-year residual maturity → 1-5yr band
_H_C_GOVT_CQS1_1_5Y_10D: float = 0.02  # 2%

# Exposure (BIND): corp_bond, CQS 2, 4-year residual maturity → CQS 2-3, 1-5yr band
_H_E_CORP_CQS2_3_1_5Y_10D: float = 0.06  # 6%

# Exposure (RUNB / CTRL): cash or standard loan — HE = 0
_H_E_ZERO: float = 0.0

# Liquidation periods: 20-day (secured lending), 5-day (SFT)
_T_M_SL: int = 20
_T_M_SFT: int = 5

# ---------------------------------------------------------------------------
# Scaled haircuts (per Art. 226(2): H_m = H_10d × sqrt(T_m / 10))
# ---------------------------------------------------------------------------

# CTRL (is_sft=False → 20-day)
H_C_CTRL: float = _H_C_GOVT_CQS1_1_5Y_10D * math.sqrt(_T_M_SL / 10)  # 2% × sqrt(2) = 2.8284%
H_E_CTRL: float = _H_E_ZERO  # 0

# BIND (is_sft=True → 5-day)
H_C_BIND: float = _H_C_GOVT_CQS1_1_5Y_10D * math.sqrt(_T_M_SFT / 10)  # 2% × sqrt(0.5) = 1.4142%
H_E_BIND: float = _H_E_CORP_CQS2_3_1_5Y_10D * math.sqrt(_T_M_SFT / 10)  # 6% × sqrt(0.5) = 4.2426%

# RUNB (is_sft=True → 5-day, cash exposure)
H_C_RUNB: float = _H_C_GOVT_CQS1_1_5Y_10D * math.sqrt(_T_M_SFT / 10)  # = H_C_BIND
H_E_RUNB: float = _H_E_ZERO  # 0

# ---------------------------------------------------------------------------
# Expected E* values (Art. 223(5): E* = max(0, E(1+HE) - C(1-HC-HFX)))
# HFX = 0 throughout (GBP collateral / GBP exposure — same currency)
# ---------------------------------------------------------------------------

# CTRL
_E_GROSSED_CTRL: float = DRAWN_AMOUNT * (1.0 + H_E_CTRL)
_C_ADJ_CTRL: float = COLLATERAL_MARKET_VALUE * (1.0 - H_C_CTRL)
EXPECTED_EAD_CTRL: float = max(0.0, _E_GROSSED_CTRL - _C_ADJ_CTRL)
# = max(0, 1_000_000 - 950_000 × 0.971716) = 1_000_000 - 923_130.35 = 76_869.65

# BIND (load-bearing: HE > 0 raises E* materially)
_E_GROSSED_BIND: float = DRAWN_AMOUNT * (1.0 + H_E_BIND)
_C_ADJ_BIND: float = COLLATERAL_MARKET_VALUE * (1.0 - H_C_BIND)
EXPECTED_EAD_BIND: float = max(0.0, _E_GROSSED_BIND - _C_ADJ_BIND)
# = max(0, 1_042_426.41 - 936_565.03) = 105_861.38

# RUNB (HE=0, same collateral haircut as BIND — SFT 5-day)
_E_GROSSED_RUNB: float = DRAWN_AMOUNT * (1.0 + H_E_RUNB)
_C_ADJ_RUNB: float = COLLATERAL_MARKET_VALUE * (1.0 - H_C_RUNB)
EXPECTED_EAD_RUNB: float = max(0.0, _E_GROSSED_RUNB - _C_ADJ_RUNB)
# = max(0, 1_000_000 - 936_565.03) = 63_434.97

# SA risk weight: CRR Art. 122, unrated corporate → 100%
_SA_RISK_WEIGHT: float = 1.0

EXPECTED_RWA_CTRL: float = EXPECTED_EAD_CTRL * _SA_RISK_WEIGHT
EXPECTED_RWA_BIND: float = EXPECTED_EAD_BIND * _SA_RISK_WEIGHT
EXPECTED_RWA_RUNB: float = EXPECTED_EAD_RUNB * _SA_RISK_WEIGHT

# Negative-pin: EAD that must NOT appear for BIND when the fix is absent.
# Pre-fix: engine omits (1+HE) on exposure side, so it computes E* as if HE=0:
#   E* = max(0, E - C(1-HC)) = max(0, 1_000_000 - 936_565.03) = 63_434.97
# This equals EXPECTED_EAD_RUNB, making BIND indistinguishable from RUNB pre-fix.
PRE_FIX_EAD_BIND: float = EXPECTED_EAD_RUNB  # 63_434.97


# ---------------------------------------------------------------------------
# Private dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.123 counterparty: unrated corporate, GB.

    entity_type=corporate → CRR Art. 122 SA risk weights.
    No CQS row in ratings → unrated → 100% RW.
    is_financial_sector_entity=False: no FI scalar applied.
    apply_fi_scalar=False: FIRB correlation multiplier not applied.
    is_core_market_participant=False: conservative non-CMP treatment.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    is_financial_sector_entity: bool
    apply_fi_scalar: bool
    is_core_market_participant: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "is_financial_sector_entity": self.is_financial_sector_entity,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_core_market_participant": self.is_core_market_participant,
        }


@dataclass(frozen=True)
class _Facility:
    """
    P1.123 facility: on-balance-sheet committed facility (parent for a drawn loan).

    committed=True, limit=1_000_000 GBP.  No risk_type set (null) because these
    facilities are on-balance-sheet containers — CCF logic applies to the loan
    drawn amount only.
    """

    facility_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    limit: float
    committed: bool
    seniority: str

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": self.currency,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "limit": self.limit,
            "committed": self.committed,
            "seniority": self.seniority,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.123 loan: GBP 1,000,000 drawn.

    Three variants share most fields; discriminating fields are loan_reference,
    maturity_date, is_sft, exposure_collateral_type, exposure_security_cqs,
    and exposure_security_residual_maturity_years.

    The three new exposure_* columns encode the security characteristics of the
    exposure itself (used to derive HE per Art. 224 Table 1):
        CTRL:  exposure_collateral_type=None (loan, not a security) → HE=0
        BIND:  exposure_collateral_type="corp_bond", cqs=2, maturity=4.0 → HE=6% (10d)
        RUNB:  exposure_collateral_type="cash" → HE=0 (cash has 0% haircut)
    """

    loan_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    drawn_amount: float
    interest: float
    seniority: str
    is_sft: bool
    has_one_day_maturity_floor: bool
    has_netting_agreement: bool
    has_sufficient_collateral_data: bool
    # New columns for HE derivation (Art. 223(5)) — nullable
    exposure_collateral_type: str | None
    exposure_security_cqs: int | None
    exposure_security_residual_maturity_years: float | None

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": self.currency,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "seniority": self.seniority,
            "is_sft": self.is_sft,
            "has_one_day_maturity_floor": self.has_one_day_maturity_floor,
            "has_netting_agreement": self.has_netting_agreement,
            "has_sufficient_collateral_data": self.has_sufficient_collateral_data,
            "exposure_collateral_type": self.exposure_collateral_type,
            "exposure_security_cqs": self.exposure_security_cqs,
            "exposure_security_residual_maturity_years": self.exposure_security_residual_maturity_years,
        }


@dataclass(frozen=True)
class _Collateral:
    """
    P1.123 collateral: GBP govt_bond CQS 1, 2-year residual maturity, pledged to a single loan.

    Load-bearing attributes:
        collateral_type="govt_bond": eligible financial collateral under Art. 197(1)(b)
        issuer_cqs=1, residual_maturity_years=2.0: 1-5yr band → HC=2% at 10 days
        currency="GBP": same as exposure currency → HFX=0
        is_eligible_financial_collateral=True: FCCM applies
        liquidation_period_days=None: engine derives T_m from linked exposure is_sft flag
            (20 days for is_sft=False per Art. 224(2)(a), 5 days for is_sft=True)
        revaluation_frequency_days=None: daily revaluation → Art. 226(1) factor = 1.0
        qualifies_for_zero_haircut=False: Art. 227 zero-haircut exemption not applied
    """

    collateral_reference: str
    collateral_type: str
    currency: str
    maturity_date: date
    market_value: float
    nominal_value: float
    beneficiary_type: str
    beneficiary_reference: str
    issuer_cqs: int
    issuer_type: str
    residual_maturity_years: float
    original_maturity_years: float
    is_eligible_financial_collateral: bool
    liquidation_period_days: int | None
    revaluation_frequency_days: int | None
    qualifies_for_zero_haircut: bool

    def to_dict(self) -> dict:
        return {
            "collateral_reference": self.collateral_reference,
            "collateral_type": self.collateral_type,
            "currency": self.currency,
            "maturity_date": self.maturity_date,
            "market_value": self.market_value,
            "nominal_value": self.nominal_value,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "issuer_cqs": self.issuer_cqs,
            "issuer_type": self.issuer_type,
            "residual_maturity_years": self.residual_maturity_years,
            "original_maturity_years": self.original_maturity_years,
            "is_eligible_financial_collateral": self.is_eligible_financial_collateral,
            "liquidation_period_days": self.liquidation_period_days,
            "revaluation_frequency_days": self.revaluation_frequency_days,
            "qualifies_for_zero_haircut": self.qualifies_for_zero_haircut,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1123_counterparties() -> pl.DataFrame:
    """
    Return the single P1.123 counterparty as a DataFrame.

    entity_type=corporate → CRR Art. 122. Unrated (no ratings row) → 100% SA RW.
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="P1123 Corp SFT Counterparty",
        entity_type="corporate",
        country_code="GB",
        default_status=False,
        is_financial_sector_entity=False,
        apply_fi_scalar=False,
        is_core_market_participant=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1123_facilities() -> pl.DataFrame:
    """
    Return three P1.123 facility rows as a DataFrame.

    All three facilities are identical in structure (committed, GBP 1,000,000).
    Maturity mirrors the associated loan.  No risk_type set (null) — these are
    on-balance-sheet containers; CCF is not applicable to drawn loan amounts.
    """
    common = {
        "counterparty_reference": COUNTERPARTY_REF,
        "currency": "GBP",
        "value_date": VALUE_DATE,
        "limit": 1_000_000.0,
        "committed": True,
        "seniority": "senior",
    }

    rows = [
        _Facility(
            facility_reference=FACILITY_REF_CTRL,
            maturity_date=MATURITY_DATE_CTRL,
            **common,
        ),
        _Facility(
            facility_reference=FACILITY_REF_BIND,
            maturity_date=MATURITY_DATE_SFT,
            **common,
        ),
        _Facility(
            facility_reference=FACILITY_REF_RUNB,
            maturity_date=MATURITY_DATE_SFT,
            **common,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_SCHEMA))


def create_p1123_loans() -> pl.DataFrame:
    """
    Return three P1.123 loan rows as a DataFrame.

    The three new columns (exposure_collateral_type, exposure_security_cqs,
    exposure_security_residual_maturity_years) are carried as extra columns in
    addition to LOAN_SCHEMA fields.  They are not yet declared in LOAN_SCHEMA
    (engine-implementer wave adds them), but the Polars parquet round-trip and
    the loader both tolerate extra nullable columns (strict=False by default in
    validate_bundle_values).

    CRR-P1123-L-CTRL (is_sft=False):
        HE = 0 (loan, not a security)
        T_m = 20 days → HC = 2% × sqrt(2) = 2.8284%
        E* = 1,000,000 − 950,000 × (1 − 0.028284) = 76,869.65

    CRR-P1123-L-BIND (is_sft=True, corp_bond CQS 2, 4yr):
        HE = 6% × sqrt(0.5) = 4.2426%  (corp_bond CQS 2-3, 1-5yr band)
        T_m = 5 days → HC = 2% × sqrt(0.5) = 1.4142%
        E* = max(0, 1,042,426.41 − 936,565.03) = 105,861.38

    CRR-P1123-L-RUNB (is_sft=True, cash):
        HE = 0 (cash has 0% haircut)
        T_m = 5 days → HC = 2% × sqrt(0.5) = 1.4142%
        E* = max(0, 1,000,000 − 936,565.03) = 63,434.97
    """
    common_bool = {
        "has_one_day_maturity_floor": False,
        "has_netting_agreement": False,
        "has_sufficient_collateral_data": False,
    }
    common = {
        "counterparty_reference": COUNTERPARTY_REF,
        "currency": "GBP",
        "value_date": VALUE_DATE,
        "drawn_amount": DRAWN_AMOUNT,
        "interest": 0.0,
        "seniority": "senior",
        **common_bool,
    }

    rows = [
        _Loan(
            loan_reference=LOAN_REF_CTRL,
            maturity_date=MATURITY_DATE_CTRL,
            is_sft=False,
            exposure_collateral_type=None,
            exposure_security_cqs=None,
            exposure_security_residual_maturity_years=None,
            **common,
        ),
        _Loan(
            loan_reference=LOAN_REF_BIND,
            maturity_date=MATURITY_DATE_SFT,
            is_sft=True,
            exposure_collateral_type="corp_bond",
            exposure_security_cqs=2,
            exposure_security_residual_maturity_years=4.0,
            **common,
        ),
        _Loan(
            loan_reference=LOAN_REF_RUNB,
            maturity_date=MATURITY_DATE_SFT,
            is_sft=True,
            exposure_collateral_type="cash",
            exposure_security_cqs=None,
            exposure_security_residual_maturity_years=None,
            **common,
        ),
    ]

    # Build the base schema from LOAN_SCHEMA, then add new columns
    base_schema = dtypes_of(LOAN_SCHEMA)
    extended_schema: dict[str, pl.DataType] = {
        **base_schema,
        "exposure_collateral_type": pl.String,
        "exposure_security_cqs": pl.Int8,
        "exposure_security_residual_maturity_years": pl.Float64,
    }
    return pl.DataFrame([r.to_dict() for r in rows], schema=extended_schema)


def create_p1123_collateral() -> pl.DataFrame:
    """
    Return three P1.123 collateral rows as a DataFrame.

    BIND and RUNB rows use GBP govt_bond CQS 1, 2-year residual maturity
    (950,000 market value).  The CTRL collateral uses residual_maturity_years=5.0
    so that it satisfies the Art. 238 no-mismatch condition: t_coll (5.0y) >= T_exposure
    (CTRL loan matures 2030-12-31, ~4.999y from reporting date 2025-12-31).

    Using 5.0 stays within the 1-5yr haircut band (HC=2%) because CRR
    get_maturity_band uses residual_maturity_years <= 5.0 for the 1_5y band.

    Load-bearing attributes per row:
    - govt_bond, CQS 1 → H_c_10d = 2%
    - CTRL: residual_maturity_years=5.0 (1-5yr band, no Art. 238 mismatch)
    - BIND/RUNB: residual_maturity_years=2.0 (1-5yr band; t=2.0y >= T≈0.5y SFT)
    - currency="GBP" → same as exposure → H_fx = 0
    - liquidation_period_days=None → engine infers T_m from loan is_sft flag
    - revaluation_frequency_days=None → daily revaluation → Art. 226(1) factor = 1.0
    - is_eligible_financial_collateral=True → FCCM (Art. 223-226) applies
    - qualifies_for_zero_haircut=False → Art. 227 zero-haircut exemption absent
    """
    _common_kwargs = {
        "collateral_type": "govt_bond",
        "currency": "GBP",
        "market_value": COLLATERAL_MARKET_VALUE,
        "nominal_value": COLLATERAL_MARKET_VALUE,
        "issuer_cqs": 1,
        "issuer_type": "sovereign",
        "original_maturity_years": 5.0,
        "is_eligible_financial_collateral": True,
        "liquidation_period_days": None,
        "revaluation_frequency_days": None,
        "qualifies_for_zero_haircut": False,
        "beneficiary_type": "loan",
    }

    rows = [
        # CTRL: residual_maturity_years=5.0 so t_coll >= T_exposure (~4.999y) — no Art. 238 mismatch
        # 5.0 maps to the 1-5y haircut band (HC=2%) under CRR get_maturity_band (residual <= 5.0)
        _Collateral(
            collateral_reference=COLLATERAL_REF_CTRL,
            beneficiary_reference=LOAN_REF_CTRL,
            maturity_date=date(2031, 1, 1),
            residual_maturity_years=5.0,
            **_common_kwargs,
        ),
        # BIND: residual_maturity_years=2.0 (SFT 1y, t=2.0y >> T≈0.5y — no mismatch)
        _Collateral(
            collateral_reference=COLLATERAL_REF_BIND,
            beneficiary_reference=LOAN_REF_BIND,
            maturity_date=date(2028, 12, 31),
            residual_maturity_years=2.0,
            **_common_kwargs,
        ),
        # RUNB: residual_maturity_years=2.0 (SFT 1y, t=2.0y >> T≈0.5y — no mismatch)
        _Collateral(
            collateral_reference=COLLATERAL_REF_RUNB,
            beneficiary_reference=LOAN_REF_RUNB,
            maturity_date=date(2028, 12, 31),
            residual_maturity_years=2.0,
            **_common_kwargs,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1123_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.123 parquet files and return a mapping of name to path.

    Four parquet files are written:
        counterparties.parquet  — 1 row
        facilities.parquet      — 3 rows
        loans.parquet           — 3 rows
        collateral.parquet      — 3 rows

    Args:
        output_dir: Target directory.  Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparties", create_p1123_counterparties()),
        ("facilities", create_p1123_facilities()),
        ("loans", create_p1123_loans()),
        ("collateral", create_p1123_collateral()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.123 fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 80)
    print("Scenario: CRR Art. 223(5) — FCCM exposure volatility haircut (HE) for SFTs")
    print()
    print("  Collateral:  GBP govt_bond CQS 1, 2yr residual maturity, MV=950,000")
    print(f"  H_c_10d      = {_H_C_GOVT_CQS1_1_5Y_10D:.4f}  (govt_bond CQS 1, 1-5yr)")
    print(f"  H_e_corp_10d = {_H_E_CORP_CQS2_3_1_5Y_10D:.4f}  (corp_bond CQS 2-3, 1-5yr)")
    print()
    print("  L-CTRL (is_sft=False, HE=0, T_m=20d):")
    print(f"    H_c   = {H_C_CTRL:.8f}")
    print(f"    H_e   = {H_E_CTRL:.8f}")
    print(f"    EAD*  = {EXPECTED_EAD_CTRL:>20.8f}  (EXPECTED_EAD_CTRL)")
    print()
    print("  L-BIND (is_sft=True, corp_bond CQS 2 exposure, T_m=5d):")
    print(f"    H_c   = {H_C_BIND:.8f}")
    print(f"    H_e   = {H_E_BIND:.8f}")
    print(f"    EAD*  = {EXPECTED_EAD_BIND:>20.8f}  (EXPECTED_EAD_BIND)  <-- load-bearing")
    print(f"    PRE_FIX_EAD_BIND = {PRE_FIX_EAD_BIND:.8f}  (must NOT match BIND post-fix)")
    print()
    print("  L-RUNB (is_sft=True, cash exposure, T_m=5d):")
    print(f"    H_c   = {H_C_RUNB:.8f}")
    print(f"    H_e   = {H_E_RUNB:.8f}")
    print(f"    EAD*  = {EXPECTED_EAD_RUNB:>20.8f}  (EXPECTED_EAD_RUNB)")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1123_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
