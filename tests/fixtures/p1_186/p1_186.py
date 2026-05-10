"""
Generate P1.186 fixtures: FX Collateral Haircut H_fx Default for Secured Lending.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/haircuts.py)

Key responsibilities:
- Produce one corporate counterparty: unrated, GB, entity_type=corporate.
- Produce two loan rows: LOAN_P186_SL (is_sft=False) and LOAN_P186_SFT (is_sft=True).
- Produce two collateral rows: EUR-denominated govt_bond CQS 1, 1-5y residual maturity,
  pledged directly to each loan respectively. liquidation_period_days=None on both rows
  so the engine must derive the liquidation period from the loan's is_sft flag.

Scenario rationale (CRR Art. 224(2)(a)):
    When ``liquidation_period_days`` is None on the collateral row the engine must
    infer the liquidation period from the linked exposure:
        - is_sft=False → 20 days  (Art. 224(2)(a): secured lending)
        - is_sft=True  → 5 days   (Art. 224(2)(c): repo-style SFT)

    Both loans carry an EUR-denominated government bond as collateral while the
    exposure currency is GBP.  The FX haircut H_fx = 8% (Art. 233) must also be
    scaled by sqrt(T_m / 10):
        SL  (20-day):  H_fx = 8% × sqrt(20/10) = 11.3137%
        SFT  (5-day):  H_fx = 8% × sqrt( 5/10) =  5.6569%

    The collateral haircut H_c for govt_bond CQS 1, 1-5y residual maturity = 2%
    (10-day base, CRR Art. 224 Table 1).  Scaled:
        SL  (20-day):  H_c = 2% × sqrt(20/10) = 2.8284%
        SFT  (5-day):  H_c = 2% × sqrt( 5/10) = 1.4142%

    Total combined haircut = H_c + H_fx.
    Adjusted collateral: C* = C_market × (1 − H_c − H_fx)
    EAD (E*): max(0, E − C*)

Bug (pre-fix):
    The engine applies the 10-day default haircut to both H_c and H_fx without
    scaling for the actual liquidation period when ``liquidation_period_days`` is
    None.  This yields:
        H_c + H_fx = 2% + 8% = 10% (flat 10-day, no scaling)
        C* = 600,000 × 0.90 = 540,000
        EAD (SL, no scaling) = 1,000,000 − 540,000 = 460,000   ← PRE_FIX_EAD_SL

    The correct 20-day-scaled result for the SL exposure is 484,852.81 — higher
    because the 20-day liquidation period produces a larger combined haircut
    (14.14%) and therefore a smaller adjusted collateral value.

Hand-calculation (CRR, CalculationConfig.crr()):
    H_n_10d (govt_bond CQS 1, 1-5y)  = 0.02       (CRR Art. 224 Table 1)
    H_fx_10d                          = 0.08       (CRR Art. 233)
    E   = 1,000,000.00 GBP
    C   =   600,000.00 EUR (market value; FX ignored for sizing; treated as same unit)

    LOAN_P186_SL (is_sft=False → T_m = 20 days, Art. 224(2)(a)):
        H_c_sl   = 0.02 × sqrt(20/10) = 0.028284271247461903
        H_fx_sl  = 0.08 × sqrt(20/10) = 0.113137084989847603
        C*_sl    = 600,000 × (1 − 0.028284271247461903 − 0.113137084989847603)
                 = 600,000 × (1 − 0.141421356237309506)
                 = 600,000 × 0.858578643762690494
                 = 515,147.186257614296
        EAD_sl   = 1,000,000 − 515,147.186257614296 = 484,852.813742385704

    LOAN_P186_SFT (is_sft=True → T_m = 5 days, Art. 224(2)(a)):
        H_c_sft  = 0.02 × sqrt(5/10) = 0.014142135623730951
        H_fx_sft = 0.08 × sqrt(5/10) = 0.056568542494923804
        C*_sft   = 600,000 × (1 − 0.014142135623730951 − 0.056568542494923804)
                 = 600,000 × (1 − 0.070710678118654755)
                 = 600,000 × 0.929289321881345245
                 = 557,573.593128807147
        EAD_sft  = 1,000,000 − 557,573.593128807147 = 442,426.406871192853

    Risk weight (CRR Art. 122, corporate unrated) = 1.00 (100%)
    RWA_sl  = EAD_sl  × 1.00 = 484,852.81 (rounded to 2dp)
    RWA_sft = EAD_sft × 1.00 = 442,426.41 (rounded to 2dp)

References:
    - CRR Art. 224(2)(a): 20-day liquidation period for secured lending
    - CRR Art. 224(2)(c): 5-day liquidation period for repo-style SFTs
    - CRR Art. 226(2): H_m = H_10 × sqrt(T_m / 10) scaling formula
    - CRR Art. 233: FX mismatch haircut (H_fx = 8% at 10 days)
    - CRR Art. 197(1)(b): eligible financial collateral — govt bond CQS 1
    - CRR Art. 122: corporate SA risk weights (unrated → 100%)
    - src/rwa_calc/data/tables/haircuts.py: COLLATERAL_HAIRCUTS, FX_HAIRCUT
    - src/rwa_calc/engine/crm/haircuts.py: liquidation period derivation logic

Usage:
    uv run python tests/fixtures/p1_186/p1_186.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COLLATERAL_SCHEMA, COUNTERPARTY_SCHEMA, LOAN_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants — counterparty / exposure / collateral references
# ---------------------------------------------------------------------------

COUNTERPARTY_REF: str = "CP_P186"
LOAN_REF_SL: str = "LOAN_P186_SL"  # secured lending (is_sft=False)
LOAN_REF_SFT: str = "LOAN_P186_SFT"  # SFT control (is_sft=True)
COLLATERAL_REF_SL: str = "COLL_P186_SL"
COLLATERAL_REF_SFT: str = "COLL_P186_SFT"

VALUE_DATE: date = date(2025, 1, 1)
MATURITY_DATE: date = date(2027, 1, 1)
COLLATERAL_MATURITY: date = date(2027, 6, 30)  # > exposure maturity → no maturity mismatch

DRAWN_AMOUNT: float = 1_000_000.0
MARKET_VALUE: float = 600_000.0

# ---------------------------------------------------------------------------
# Regulatory constants (CRR Art. 224 Table 1 + Art. 233)
# ---------------------------------------------------------------------------

# 10-day base haircuts from CRR Art. 224 Table 1
_H_C_10D: float = 0.02  # govt_bond CQS 1, 1-5y residual maturity
_H_FX_10D: float = 0.08  # FX mismatch haircut (CRR Art. 233)

# Liquidation periods (Art. 224(2))
_T_M_SL: int = 20  # Art. 224(2)(a): secured lending default
_T_M_SFT: int = 5  # Art. 224(2)(c): repo-style SFT

# ---------------------------------------------------------------------------
# Hand-calculated expected outputs — single source of truth for assertions
# ---------------------------------------------------------------------------

# Scaled haircuts for secured lending (20-day)
H_C_SL: float = _H_C_10D * math.sqrt(_T_M_SL / 10)  # = 0.028284271247461903
H_FX_SL: float = _H_FX_10D * math.sqrt(_T_M_SL / 10)  # = 0.113137084989847603

# Scaled haircuts for SFT (5-day)
H_C_SFT: float = _H_C_10D * math.sqrt(_T_M_SFT / 10)  # = 0.014142135623730951
H_FX_SFT: float = _H_FX_10D * math.sqrt(_T_M_SFT / 10)  # = 0.056568542494923804

# Adjusted collateral: C* = C × (1 − H_c − H_fx)
_C_ADJ_SL: float = MARKET_VALUE * (1.0 - H_C_SL - H_FX_SL)
_C_ADJ_SFT: float = MARKET_VALUE * (1.0 - H_C_SFT - H_FX_SFT)

# EAD (E*) = max(0, E − C*)
EXPECTED_EAD_SL: float = max(0.0, DRAWN_AMOUNT - _C_ADJ_SL)  # ≈ 484_852.81374238568
EXPECTED_EAD_SFT: float = max(0.0, DRAWN_AMOUNT - _C_ADJ_SFT)  # ≈ 442_426.40687119284

# SA risk weight: CRR Art. 122, unrated corporate → 100%
_RISK_WEIGHT: float = 1.0

EXPECTED_RWA_SL: float = EXPECTED_EAD_SL * _RISK_WEIGHT  # ≈ 484_852.81
EXPECTED_RWA_SFT: float = EXPECTED_EAD_SFT * _RISK_WEIGHT  # ≈ 442_426.41

# Negative-pin: EAD that must NOT appear if the fix is absent.
# Pre-fix: engine uses flat 10-day haircut (H_c + H_fx = 10%) with no liquidation scaling.
#   C* = 600,000 × (1 − 0.02 − 0.08) = 600,000 × 0.90 = 540,000
#   EAD = 1,000,000 − 540,000 = 460,000
PRE_FIX_EAD_SL: float = DRAWN_AMOUNT - MARKET_VALUE * (1.0 - _H_C_10D - _H_FX_10D)  # = 460_000


# ---------------------------------------------------------------------------
# Minimal frozen dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.186 corporate counterparty: unrated, GB, entity_type=corporate.

    entity_type=corporate → CRR Art. 122 SA risk weights.
    Unrated (no CQS in ratings → 100% RW).
    is_financial_sector_entity=False: no FI scalar.
    apply_fi_scalar=False: FIRB correlation multiplier not applied.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    is_financial_sector_entity: bool
    apply_fi_scalar: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "is_financial_sector_entity": self.is_financial_sector_entity,
            "apply_fi_scalar": self.apply_fi_scalar,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.186 loan: GBP 1,000,000 drawn, senior, 2025-01-01 to 2027-01-01.

    Two variants share all fields except loan_reference and is_sft:
        LOAN_P186_SL:  is_sft=False → engine infers T_m=20d (Art. 224(2)(a))
        LOAN_P186_SFT: is_sft=True  → engine infers T_m=5d  (Art. 224(2)(c))

    has_one_day_maturity_floor=False: no artificial maturity floor.
    has_netting_agreement=False: no netting → full gross EAD before CRM.
    has_sufficient_collateral_data=False: no IRB path override.
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
        }


@dataclass(frozen=True)
class _Collateral:
    """
    P1.186 collateral row: EUR govt_bond CQS 1, pledged direct to a single loan.

    Key load-bearing fields:
        currency="EUR" vs exposure currency "GBP" → FX haircut fires (Art. 233)
        issuer_cqs=1, residual_maturity_years=2.0 → govt_bond_cqs1_1_5y band (H_c=2%)
        liquidation_period_days=None → engine must derive T_m from exposure is_sft
        qualifies_for_zero_haircut=False → Art. 227 zero-haircut exemption does NOT apply
        revaluation_frequency_days=None → daily revaluation assumed (factor=1.0, no Art. 226(1) scaling)
        is_eligible_financial_collateral=True → qualifies under Art. 197(1)(b) FCCM
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


def create_p1186_counterparty() -> pl.DataFrame:
    """
    Return the P1.186 counterparty (unrated corporate, GB) as a DataFrame.

    entity_type=corporate routes to CRR Art. 122 SA risk weights.
    No external CQS row is supplied → engine treats as unrated → RW = 100%.
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="P186 Corp Counterparty",
        entity_type="corporate",
        country_code="GB",
        default_status=False,
        is_financial_sector_entity=False,
        apply_fi_scalar=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1186_loans() -> pl.DataFrame:
    """
    Return two P1.186 loan rows as a DataFrame.

    LOAN_P186_SL (is_sft=False):
        Engine derives T_m=20 days (Art. 224(2)(a) secured lending default).
        H_c = 2% × sqrt(2) = 2.8284%; H_fx = 8% × sqrt(2) = 11.3137%
        EAD = 1,000,000 − 600,000 × (1 − 0.1414) ≈ 484,852.81

    LOAN_P186_SFT (is_sft=True):
        Engine derives T_m=5 days (Art. 224(2)(c) SFT default).
        H_c = 2% × sqrt(0.5) = 1.4142%; H_fx = 8% × sqrt(0.5) = 5.6569%
        EAD = 1,000,000 − 600,000 × (1 − 0.0707) ≈ 442,426.41
    """
    common = {
        "counterparty_reference": COUNTERPARTY_REF,
        "currency": "GBP",
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
        "drawn_amount": DRAWN_AMOUNT,
        "interest": 0.0,
        "seniority": "senior",
        "has_one_day_maturity_floor": False,
        "has_netting_agreement": False,
        "has_sufficient_collateral_data": False,
    }

    rows = [
        _Loan(
            loan_reference=LOAN_REF_SL,
            is_sft=False,  # secured lending → 20-day liquidation period
            **common,
        ),
        _Loan(
            loan_reference=LOAN_REF_SFT,
            is_sft=True,  # SFT → 5-day liquidation period
            **common,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1186_collateral() -> pl.DataFrame:
    """
    Return two P1.186 collateral rows as a DataFrame.

    Both rows represent identical EUR-denominated investment-grade government bonds
    pledged directly to their respective loans (LOAN_P186_SL and LOAN_P186_SFT).

    Load-bearing attributes:
    - currency="EUR" (vs GBP exposure) → H_fx fires (CRR Art. 233)
    - issuer_cqs=1, residual_maturity_years=2.0 → 1-5y band → H_c=2% base
    - liquidation_period_days=None → T_m inferred from linked exposure is_sft
    - qualifies_for_zero_haircut=False → Art. 227 exemption does not apply
    - revaluation_frequency_days=None → daily revaluation → no Art. 226(1) scaling
    - original_maturity_years=5.0 → no Art. 237(2) cliff (>= 1y)
    """
    _common_kwargs = {
        "collateral_type": "govt_bond",
        "currency": "EUR",
        "maturity_date": COLLATERAL_MATURITY,
        "market_value": MARKET_VALUE,
        "nominal_value": MARKET_VALUE,
        "issuer_cqs": 1,
        "issuer_type": "sovereign",
        "residual_maturity_years": 2.0,
        "original_maturity_years": 5.0,
        "is_eligible_financial_collateral": True,
        "liquidation_period_days": None,  # load-bearing: None → engine derives T_m
        "revaluation_frequency_days": None,  # daily revaluation → factor=1.0
        "qualifies_for_zero_haircut": False,  # Art. 227 zero-haircut does not apply
        "beneficiary_type": "loan",
    }

    rows = [
        _Collateral(
            collateral_reference=COLLATERAL_REF_SL,
            beneficiary_reference=LOAN_REF_SL,
            **_common_kwargs,
        ),
        _Collateral(
            collateral_reference=COLLATERAL_REF_SFT,
            beneficiary_reference=LOAN_REF_SFT,
            **_common_kwargs,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1186_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.186 parquet files and return a mapping of name to path.

    Three parquet files are written:
        counterparty.parquet  — 1 row  (CP_P186)
        loan.parquet          — 2 rows (LOAN_P186_SL, LOAN_P186_SFT)
        collateral.parquet    — 2 rows (COLL_P186_SL, COLL_P186_SFT)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1186_counterparty()),
        ("loan", create_p1186_loans()),
        ("collateral", create_p1186_collateral()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.186 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR Art. 224(2)(a) — FX haircut H_fx default liquidation scaling")
    print()
    print("  Collateral: EUR govt_bond, CQS 1, 1-5y residual maturity")
    print(f"  H_c (base 10-day)  = {_H_C_10D:.4f} (2.0%)")
    print(f"  H_fx (base 10-day) = {_H_FX_10D:.4f} (8.0%)")
    print()
    print("  LOAN_P186_SL  (is_sft=False → T_m=20d, Art. 224(2)(a)):")
    print(f"    H_c  = {H_C_SL:.15f}")
    print(f"    H_fx = {H_FX_SL:.15f}")
    print(f"    EAD  = {EXPECTED_EAD_SL:>20.11f}  (EXPECTED_EAD_SL)")
    print(f"    RWA  = {EXPECTED_RWA_SL:>20.2f}  (EXPECTED_RWA_SL)")
    print()
    print("  LOAN_P186_SFT (is_sft=True  → T_m=5d,  Art. 224(2)(c)):")
    print(f"    H_c  = {H_C_SFT:.15f}")
    print(f"    H_fx = {H_FX_SFT:.15f}")
    print(f"    EAD  = {EXPECTED_EAD_SFT:>20.11f}  (EXPECTED_EAD_SFT)")
    print(f"    RWA  = {EXPECTED_RWA_SFT:>20.2f}  (EXPECTED_RWA_SFT)")
    print()
    print(f"  PRE_FIX_EAD_SL (must NOT match SL result) = {PRE_FIX_EAD_SL:>20.2f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1186_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
