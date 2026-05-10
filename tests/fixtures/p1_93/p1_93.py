"""
Generate P1.93 fixtures: FCSM Art. 222(4) SFT 0%/10% carve-out + Art. 222(6) non-SFT gating.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/simple_method.py)

Key responsibilities:
- Produce two counterparty rows: institution CMP (CP_INST_001) and corporate non-CMP (CP_CORP_001).
- Produce three facility rows: two SFT repos (FAC_REPO_A, FAC_REPO_B) and one non-SFT OBS
  (FAC_OBS_C), all GBP 1,000,000.
- Produce three collateral rows: two GBP CQS-1 sovereign gilts (COLL_GILT_A, COLL_GILT_B)
  and one GBP cash deposit (COLL_CASH_C), all market_value=1,000,000.
- Config (test-side): CalculationConfig.basel_3_1(reporting_date=2028-01-01,
  crm_collateral_method=CRMCollateralMethod.SIMPLE).

Three runs share the same parquet files; tests sub-select by facility_reference:

Run A — SFT repo + CQS-1 sovereign gilt + CMP counterparty:
    is_sft=True, qualifies_for_zero_haircut=True, is_core_market_participant=True
    Art. 222(4) core-market-participant carve-out → secured-portion floor = 0%
    Sovereign gilt issuer_cqs=1 → RW_collateral = 0% (Art. 114(2))
    max(0%, 0%) = 0%  → secured-portion RW = 0%
    EAD = 1,000,000 (full collateral covers full exposure under FCSM)
    Secured portion = 1,000,000, unsecured = 0
    RWA_A = 1,000,000 × 0% = 0

Run B — SFT repo + CQS-1 sovereign gilt + non-CMP counterparty:
    is_sft=True, qualifies_for_zero_haircut=True, is_core_market_participant=False
    Art. 222(4) non-core-market-participant → secured-portion floor = 10%
    Sovereign gilt issuer_cqs=1 → RW_collateral = 0%
    max(10%, 0%) = 10%  → secured-portion RW = 10%
    Secured portion = 1,000,000, unsecured = 0
    RWA_B = 1,000,000 × 10% = 100,000

Run C — Non-SFT OBS facility + GBP cash deposit + CMP counterparty:
    is_sft=False, qualifies_for_zero_haircut=False, is_core_market_participant=True
    Art. 222(6)(a): same-currency (GBP) cash → floor = 0% (non-SFT path, regression guard)
    max(0%, 0%) = 0%  → secured-portion RW = 0%
    OBS facility: risk_type="MR" → CCF 50% (Basel 3.1 Art. 111 Table A1 MR)
    EAD = 1,000,000 × 50% = 500,000
    Secured portion = 500,000 (collateral 1,000,000 covers full EAD), unsecured = 0
    RWA_C = 500,000 × 0% = 0

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1(..., crm_collateral_method=SIMPLE)):
    Run A: institution CQS 1 → unsecured RW = 20% (Art. 120(1) Table 3, CQS 1)
        Art. 227 criteria met (same currency, qualifies_for_zero_haircut=True) → Art. 222(4)
        is_core_market_participant=True  → floor = 0%
        RW_gilt = 0% (sovereign CQS 1 under Art. 114(2))
        secured RW = max(0%, 0%) = 0%  → RWA = 1,000,000 × 0% = 0

    Run B: corporate unrated → unsecured RW = 100% (Art. 122)
        Art. 227 criteria met → Art. 222(4)
        is_core_market_participant=False → floor = 10%
        RW_gilt = 0%  → secured RW = max(10%, 0%) = 10%
        RWA = 1,000,000 × 10% = 100,000

    Run C: institution CQS 1 → unsecured RW = 20%
        is_sft=False → Art. 222(4) SFT carve-out does NOT apply
        Same-currency GBP cash → Art. 222(6)(a) applies → floor = 0%
        secured RW = max(0%, 0%) = 0%
        CCF(MR) = 50% → EAD = 1,000,000 × 50% = 500,000
        secured portion = min(1,000,000, 500,000) = 500,000 → fully secured
        RWA = 500,000 × 0% = 0

Regulatory references:
    - PRA PS1/26 Art. 222(3): 20% FCSM RW floor (default).
    - PRA PS1/26 Art. 222(4): 0%/10% SFT carve-out gated by Art. 227 criteria.
    - PRA PS1/26 Art. 222(6)(a): 0% for non-SFT same-currency cash.
    - PRA PS1/26 Art. 227(2): Eight preconditions for the zero-floor carve-out.
    - PRA PS1/26 Art. 227(3): Core market participant definition.
    - PRA PS1/26 Art. 114(2): 0%-RW sovereign for CQS 1 jurisdictions.
    - PRA PS1/26 Art. 120(1) Table 3: institution SA risk weights by CQS.
    - docs/specifications/crr/credit-risk-mitigation.md §§ "Art. 222(4)" and "Art. 222(6)".

Usage:
    uv run python tests/fixtures/p1_93/p1_93.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COLLATERAL_SCHEMA, COUNTERPARTY_SCHEMA, FACILITY_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references
CP_INST_REF = "CP_INST_001"  # institution, CQS 1, is_core_market_participant=True
CP_CORP_REF = "CP_CORP_001"  # corporate, is_core_market_participant=False

# Facility references (all three runs)
FAC_REPO_A = "FAC_REPO_A"  # Run A: SFT repo, CMP counterparty
FAC_REPO_B = "FAC_REPO_B"  # Run B: SFT repo, non-CMP counterparty
FAC_OBS_C = "FAC_OBS_C"  # Run C: Non-SFT OBS facility, CMP counterparty

# Collateral references
COLL_GILT_A = "COLL_GILT_A"  # CQS-1 sovereign gilt, beneficiary=FAC_REPO_A
COLL_GILT_B = "COLL_GILT_B"  # CQS-1 sovereign gilt, beneficiary=FAC_REPO_B
COLL_CASH_C = "COLL_CASH_C"  # GBP cash deposit, beneficiary=FAC_OBS_C

REPORTING_DATE = date(2028, 1, 1)
VALUE_DATE = date(2028, 1, 1)
MATURITY_DATE = date(2028, 12, 31)  # 1-year tenor

NOMINAL_AMOUNT: float = 1_000_000.0
COLLATERAL_VALUE: float = 1_000_000.0

# CCF for MR (medium risk) OBS — 50% under Basel 3.1 Art. 111 Table A1
CCF_MR: float = 0.50

# Expected outputs
INSTITUTION_CQS1_UNSECURED_RW: float = 0.20  # Art. 120(1) Table 3, CQS 1
CORPORATE_UNRATED_UNSECURED_RW: float = 1.00  # Art. 122, unrated
SOVEREIGN_CQS1_RW: float = 0.00  # Art. 114(2), CQS 1

# Run A: Art. 222(4) CMP — floor = 0%, sovereign collateral RW = 0% → secured RW = 0%
EXPECTED_FCSM_FLOOR_A: float = 0.00
EXPECTED_SECURED_RW_A: float = max(EXPECTED_FCSM_FLOOR_A, SOVEREIGN_CQS1_RW)  # 0%
EXPECTED_RWA_A: float = NOMINAL_AMOUNT * EXPECTED_SECURED_RW_A  # 0

# Run B: Art. 222(4) non-CMP — floor = 10%, sovereign collateral RW = 0% → secured RW = 10%
EXPECTED_FCSM_FLOOR_B: float = 0.10
EXPECTED_SECURED_RW_B: float = max(EXPECTED_FCSM_FLOOR_B, SOVEREIGN_CQS1_RW)  # 10%
EXPECTED_RWA_B: float = NOMINAL_AMOUNT * EXPECTED_SECURED_RW_B  # 100,000

# Run C: Art. 222(6)(a) non-SFT same-currency cash — floor = 0% → secured RW = 0%
EXPECTED_FCSM_FLOOR_C: float = 0.00
EXPECTED_SECURED_RW_C: float = max(EXPECTED_FCSM_FLOOR_C, 0.00)  # 0%
EAD_C: float = NOMINAL_AMOUNT * CCF_MR  # 500,000 (MR CCF 50%)
EXPECTED_RWA_C: float = EAD_C * EXPECTED_SECURED_RW_C  # 0


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.93 counterparty row.

    Two instances:
      CP_INST_001: institution, GB, CQS 1, is_core_market_participant=True.
          Conveys Art. 227(3) CMP status → Art. 222(4) floor = 0%.
      CP_CORP_001: corporate, GB, unrated, is_core_market_participant=False.
          Non-CMP → Art. 222(4) floor = 10%.

    institution_cqs carries the CQS on the counterparty row directly (no separate
    ratings row needed — the engine resolves institution SA RW from this field).
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_financial_sector_entity: bool
    is_core_market_participant: bool
    institution_cqs: int | None

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_financial_sector_entity": self.is_financial_sector_entity,
            "is_core_market_participant": self.is_core_market_participant,
            "institution_cqs": self.institution_cqs,
        }


@dataclass(frozen=True)
class _Facility:
    """
    P1.93 facility row.

    Three instances:
      FAC_REPO_A: SFT repo, GBP 1,000,000, risk_type=FR, is_sft=True.
          Links to CP_INST_001 (CMP) → Art. 222(4) 0% floor.
      FAC_REPO_B: SFT repo, GBP 1,000,000, risk_type=FR, is_sft=True.
          Links to CP_CORP_001 (non-CMP) → Art. 222(4) 10% floor.
      FAC_OBS_C: Non-SFT OBS, GBP 1,000,000, risk_type=MR, is_sft=False.
          Links to CP_INST_001 (CMP) → Art. 222(6)(a) 0% floor.

    risk_type=FR (full risk): 100% CCF for SFT repos (on-balance-sheet equivalent).
    risk_type=MR (medium risk): 50% CCF for OBS under Basel 3.1 Art. 111 Table A1.
    nominal_amount is used as the limit for CCF application.
    """

    facility_reference: str
    counterparty_reference: str
    currency: str
    nominal_amount: float
    risk_type: str
    is_sft: bool
    value_date: date
    maturity_date: date
    committed: bool
    seniority: str
    book_code: str
    has_one_day_maturity_floor: bool

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": self.currency,
            "limit": self.nominal_amount,
            "risk_type": self.risk_type,
            "is_sft": self.is_sft,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "committed": self.committed,
            "seniority": self.seniority,
            "book_code": self.book_code,
            "has_one_day_maturity_floor": self.has_one_day_maturity_floor,
        }


@dataclass(frozen=True)
class _Collateral:
    """
    P1.93 collateral row.

    Three instances:
      COLL_GILT_A / COLL_GILT_B: GBP sovereign gilt, CQS 1, market_value=1,000,000.
          collateral_type="govt_bond" (engine-recognised alias for sovereign debt).
          issuer_type="sovereign", issuer_cqs=1 → collateral RW = 0% (Art. 114(2)).
          qualifies_for_zero_haircut=True: institution certifies Art. 227(2) criteria met.
          is_eligible_financial_collateral=True: eligible for FCSM.
          residual_maturity_years=1.0 → 0-1y band, H_c=0.5% (FCCM path only — not
          used under FCSM, carried for completeness).

      COLL_CASH_C: GBP cash deposit, market_value=1,000,000.
          collateral_type="cash" → 0% haircut under any CRM method.
          qualifies_for_zero_haircut=False: Art. 227 SFT carve-out not applicable
          (exposure is non-SFT).
          is_eligible_financial_collateral=True: eligible for FCSM.
          issuer_cqs=None, issuer_type=None: cash has no issuer.
          residual_maturity_years=1.0: nominal maturity sentinel (no maturity mismatch risk).
    """

    collateral_reference: str
    collateral_type: str
    currency: str
    market_value: float
    beneficiary_type: str
    beneficiary_reference: str
    issuer_type: str | None
    issuer_cqs: int | None
    residual_maturity_years: float
    is_eligible_financial_collateral: bool
    qualifies_for_zero_haircut: bool
    valuation_date: date
    valuation_type: str

    def to_dict(self) -> dict:
        return {
            "collateral_reference": self.collateral_reference,
            "collateral_type": self.collateral_type,
            "currency": self.currency,
            "market_value": self.market_value,
            "nominal_value": self.market_value,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "issuer_type": self.issuer_type,
            "issuer_cqs": self.issuer_cqs,
            "residual_maturity_years": self.residual_maturity_years,
            "is_eligible_financial_collateral": self.is_eligible_financial_collateral,
            "qualifies_for_zero_haircut": self.qualifies_for_zero_haircut,
            "valuation_date": self.valuation_date,
            "valuation_type": self.valuation_type,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p193_counterparties() -> pl.DataFrame:
    """
    Return the two P1.93 counterparty rows as a DataFrame.

    CP_INST_001: institution, GB, institution_cqs=1, is_core_market_participant=True.
        Shared by FAC_REPO_A (Run A, CMP → 0%) and FAC_OBS_C (Run C, non-SFT → 0%).
    CP_CORP_001: corporate, GB, unrated, is_core_market_participant=False.
        Used by FAC_REPO_B (Run B, non-CMP → 10%).
    """
    rows = [
        _Counterparty(
            counterparty_reference=CP_INST_REF,
            counterparty_name="P1.93 GB Institution CQS-1 Core Market Participant",
            entity_type="institution",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=True,
            is_core_market_participant=True,
            institution_cqs=1,
        ),
        _Counterparty(
            counterparty_reference=CP_CORP_REF,
            counterparty_name="P1.93 GB Corporate Non-Core Market Participant",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
            is_core_market_participant=False,
            institution_cqs=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p193_facilities() -> pl.DataFrame:
    """
    Return the three P1.93 facility rows as a DataFrame.

    FAC_REPO_A: SFT repo, CP_INST_001, GBP, risk_type=FR, is_sft=True.
        Run A: CMP institution → Art. 222(4) → 0% RW floor.
    FAC_REPO_B: SFT repo, CP_CORP_001, GBP, risk_type=FR, is_sft=True.
        Run B: non-CMP corporate → Art. 222(4) → 10% RW floor.
    FAC_OBS_C: OBS facility, CP_INST_001, GBP, risk_type=MR, is_sft=False.
        Run C: non-SFT + same-currency cash → Art. 222(6)(a) → 0% RW floor.
    """
    rows = [
        _Facility(
            facility_reference=FAC_REPO_A,
            counterparty_reference=CP_INST_REF,
            currency="GBP",
            nominal_amount=NOMINAL_AMOUNT,
            risk_type="FR",
            is_sft=True,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            committed=True,
            seniority="senior",
            book_code="FI_LENDING",
            has_one_day_maturity_floor=False,
        ),
        _Facility(
            facility_reference=FAC_REPO_B,
            counterparty_reference=CP_CORP_REF,
            currency="GBP",
            nominal_amount=NOMINAL_AMOUNT,
            risk_type="FR",
            is_sft=True,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            committed=True,
            seniority="senior",
            book_code="CORP_LENDING",
            has_one_day_maturity_floor=False,
        ),
        _Facility(
            facility_reference=FAC_OBS_C,
            counterparty_reference=CP_INST_REF,
            currency="GBP",
            nominal_amount=NOMINAL_AMOUNT,
            risk_type="MR",
            is_sft=False,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            committed=True,
            seniority="senior",
            book_code="FI_LENDING",
            has_one_day_maturity_floor=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_SCHEMA))


def create_p193_collateral() -> pl.DataFrame:
    """
    Return the three P1.93 collateral rows as a DataFrame.

    COLL_GILT_A: GBP sovereign gilt CQS 1, beneficiary=FAC_REPO_A.
        qualifies_for_zero_haircut=True: Art. 227(2) criteria met → Art. 222(4) CMP.
    COLL_GILT_B: GBP sovereign gilt CQS 1, beneficiary=FAC_REPO_B.
        qualifies_for_zero_haircut=True: Art. 227(2) criteria met → Art. 222(4) non-CMP.
    COLL_CASH_C: GBP cash, beneficiary=FAC_OBS_C.
        qualifies_for_zero_haircut=False: non-SFT, Art. 227 not applicable.
        Art. 222(6)(a) path instead (same-currency cash, non-SFT).
    """
    rows = [
        _Collateral(
            collateral_reference=COLL_GILT_A,
            collateral_type="govt_bond",
            currency="GBP",
            market_value=COLLATERAL_VALUE,
            beneficiary_type="facility",
            beneficiary_reference=FAC_REPO_A,
            issuer_type="sovereign",
            issuer_cqs=1,
            residual_maturity_years=1.0,
            is_eligible_financial_collateral=True,
            qualifies_for_zero_haircut=True,
            valuation_date=REPORTING_DATE,
            valuation_type="market",
        ),
        _Collateral(
            collateral_reference=COLL_GILT_B,
            collateral_type="govt_bond",
            currency="GBP",
            market_value=COLLATERAL_VALUE,
            beneficiary_type="facility",
            beneficiary_reference=FAC_REPO_B,
            issuer_type="sovereign",
            issuer_cqs=1,
            residual_maturity_years=1.0,
            is_eligible_financial_collateral=True,
            qualifies_for_zero_haircut=True,
            valuation_date=REPORTING_DATE,
            valuation_type="market",
        ),
        _Collateral(
            collateral_reference=COLL_CASH_C,
            collateral_type="cash",
            currency="GBP",
            market_value=COLLATERAL_VALUE,
            beneficiary_type="facility",
            beneficiary_reference=FAC_OBS_C,
            issuer_type=None,
            issuer_cqs=None,
            residual_maturity_years=1.0,
            is_eligible_financial_collateral=True,
            qualifies_for_zero_haircut=False,
            valuation_date=REPORTING_DATE,
            valuation_type="market",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p193_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.93 parquet files and return a mapping of name -> path.

    Three parquet files are written:
    - counterparty.parquet   (2 rows: CP_INST_001, CP_CORP_001)
    - facility.parquet       (3 rows: FAC_REPO_A, FAC_REPO_B, FAC_OBS_C)
    - collateral.parquet     (3 rows: COLL_GILT_A, COLL_GILT_B, COLL_CASH_C)

    All three runs share these parquet files; tests sub-select by facility_reference.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p193_counterparties()),
        ("facility", create_p193_facilities()),
        ("collateral", create_p193_collateral()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.93 fixture generation complete")
    print("-" * 72)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 72)
    print("Scenario: PRA PS1/26 Art. 222(4) SFT 0%/10% carve-out + Art. 222(6) non-SFT gating")
    print(f"  Basel 3.1 FCSM (crm_collateral_method=SIMPLE), reporting_date={REPORTING_DATE}")
    print()
    print("  Run A — SFT repo, CQS-1 gilt, CMP counterparty (Art. 222(4) 0% floor):")
    print(f"    Facility: {FAC_REPO_A} (is_sft=True, risk_type=FR)")
    print(f"    Counterparty: {CP_INST_REF} (institution, CQS 1, CMP=True)")
    print(f"    Collateral: {COLL_GILT_A} (govt_bond, GBP, CQS 1, zero_haircut=True)")
    print(
        f"    FCSM floor = {EXPECTED_FCSM_FLOOR_A:.0%}  →  secured RW = {EXPECTED_SECURED_RW_A:.0%}"
    )
    print(f"    Expected RWA = {EXPECTED_RWA_A:,.0f}")
    print()
    print("  Run B — SFT repo, CQS-1 gilt, non-CMP counterparty (Art. 222(4) 10% floor):")
    print(f"    Facility: {FAC_REPO_B} (is_sft=True, risk_type=FR)")
    print(f"    Counterparty: {CP_CORP_REF} (corporate, unrated, CMP=False)")
    print(f"    Collateral: {COLL_GILT_B} (govt_bond, GBP, CQS 1, zero_haircut=True)")
    print(
        f"    FCSM floor = {EXPECTED_FCSM_FLOOR_B:.0%}  →  secured RW = {EXPECTED_SECURED_RW_B:.0%}"
    )
    print(f"    Expected RWA = {EXPECTED_RWA_B:,.0f}")
    print()
    print("  Run C — non-SFT OBS, GBP cash, CMP counterparty (Art. 222(6)(a) 0% floor):")
    print(f"    Facility: {FAC_OBS_C} (is_sft=False, risk_type=MR)")
    print(f"    Counterparty: {CP_INST_REF} (institution, CQS 1, CMP=True)")
    print(f"    Collateral: {COLL_CASH_C} (cash, GBP, zero_haircut=False)")
    print(
        f"    FCSM floor = {EXPECTED_FCSM_FLOOR_C:.0%}  →  secured RW = {EXPECTED_SECURED_RW_C:.0%}"
    )
    print(f"    CCF (MR) = {CCF_MR:.0%}  →  EAD = {EAD_C:,.0f}")
    print(f"    Expected RWA = {EXPECTED_RWA_C:,.0f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p193_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
