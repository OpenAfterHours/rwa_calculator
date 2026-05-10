"""
Generate P1.122 fixtures: short-term institution guarantor substitution under CRR Art. 120(2).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/guarantee.py)

Scenario design (P1.122 — dual-pin CRR / B31 acceptance scenario):

    A corporate borrower (GB, unrated under CRR, unrated under B31) has a short-term
    loan of GBP 1,000,000 with residual maturity ~81 days (0.2219y ≤ 0.25y).

    The loan is fully covered by a 2-year unfunded guarantee from a CQS 2 institution
    (DE, externally rated CQS 2 / Moody's A2).

    The engine bug under test: the CRM processor applies the guarantor's long-term Table 3
    risk weight (CRR Art. 120(1)) regardless of the borrower exposure's residual maturity.
    The fix must detect that the guaranteed exposure has residual maturity ≤ 3 months and
    route to Table 4 (CRR Art. 120(2)) when computing the guarantor substituted risk weight.

    CRR Art. 120(2) Table 4 short-term institution risk weights:
        CQS 1 → 20%
        CQS 2 → 20%   ← guarantor CQS; this is the discriminating value
        CQS 3 → 20%
        CQS 4 → 50%
        CQS 5 → 50%
        CQS 6 → 150%

    CRR Art. 120(1) Table 3 long-term institution risk weights:
        CQS 1 → 20%
        CQS 2 → 50%   ← pre-fix bug applies this instead of 20%
        CQS 3 → 50%
        CQS 4 → 100%
        CQS 5 → 100%
        CQS 6 → 150%

    The CQS 2 guarantor is the discriminating choice: Table 3 = 50% vs Table 4 = 20%.
    Any other CQS would be ambiguous (CQS 1: both 20%; CQS 6: both 150%).

Hand-calculation (CRR, CalculationConfig.crr(reporting_date=date(2025, 12, 31))):

    Loan:
        value_date = maturity_date = reporting_date = 2025-12-31
        maturity_date = 2026-03-22  → residual = 81 days / 365 ≈ 0.2219y ≤ 0.25y
        EAD = drawn_amount = 1,000,000 (GBP; interest=0)

    Guarantee:
        guarantor: CQS 2 institution (DE, externally rated Moody's A2)
        maturity_date = 2027-12-31 → original_maturity_years = 2.0 ≥ 1.0y (eligible)
        amount_covered = 1,000,000 = 100% coverage

    Borrower exposure class: corporate (unrated) → CRR corporate SA RW = 100%

    Guarantor substituted risk weight (correct, post-fix):
        Residual maturity of guaranteed exposure = 0.2219y ≤ 0.25y
        → Route to CRR Art. 120(2) Table 4 (short-term rated institution)
        → CQS 2 → Table 4 RW = 20%
        Substituted RW = 20% < borrower RW 100% → substitution applies
        RWA (post-fix) = 1,000,000 × 0.20 = 200,000

    Guarantor substituted risk weight (bug, pre-fix):
        Engine uses Art. 120(1) Table 3 (long-term) regardless of residual maturity
        → CQS 2 → Table 3 RW = 50%
        RWA (pre-fix) = 1,000,000 × 0.50 = 500,000

    Basel 3.1 path (CalculationConfig.basel_3_1(reporting_date=date(2025, 12, 31))):
        B31 Art. 120(2) Table 4 short-term ECRA:
            CQS 2 → 20%  (identical to CRR Table 4; both tables agree at CQS 2)
        B31 Art. 120(1) Table 3 long-term ECRA:
            CQS 2 → 30%  (UK CQS 2 = 30% deviation from BCBS; different from CRR 50%)
        RWA (B31 post-fix) = 1,000,000 × 0.20 = 200,000
        RWA (B31 pre-fix)  = 1,000,000 × 0.30 = 300,000

    Note: The same parquet files are used for both CRR and B31 assertions.
    The test parametrises the framework via CalculationConfig.crr() vs .basel_3_1().

References:
    - CRR Art. 120(2) Table 4: short-term preferential RW for rated institutions (residual ≤ 3m)
    - CRR Art. 120(1) Table 3: general (long-term) rated institution RW
    - CRR Art. 235: SA risk-weight substitution method (RWSM) for guarantees
    - CRR Art. 237(2)(a): minimum original maturity of unfunded protection ≥ 1 year
    - PRA PS1/26 Art. 120(2) Table 4: B31 short-term rated institution RW (CQS 2 → 20%)
    - src/rwa_calc/data/tables/crr_risk_weights.py: INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR
    - src/rwa_calc/data/tables/b31_risk_weights.py: INSTITUTION_SHORT_TERM_RISK_WEIGHTS_B31
    - src/rwa_calc/engine/crm/guarantee.py: guarantor RW lookup branch (pre-fix bug)

Usage:
    uv run python tests/fixtures/p1_122/p1_122.py
    uv run python tests/fixtures/p1_122/p1_122.py --data-dir tests/fixtures/p1_122/data
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references (match architect proposal)
BORROWER_REF = "CP-BORROWER-P1122"
GUARANTOR_REF = "CP-GUARANTOR-P1122"

# Exposure references
LOAN_REF = "LN-P1122"
FACILITY_REF = "FAC-P1122"

# Guarantee reference
GUARANTEE_REF = "GTE-P1122"

# Rating reference (guarantor external ECAI rating)
RATING_REF = "RT-GUARANTOR-P1122"

# Dates
# Reporting date / value_date: 2025-12-31
# Loan maturity: 2026-03-22 → 81 days residual → 81/365 ≈ 0.2219y ≤ 0.25y
REPORTING_DATE = date(2025, 12, 31)
LOAN_VALUE_DATE = date(2025, 12, 31)
LOAN_MATURITY_DATE = date(2026, 3, 22)  # 81 days from LOAN_VALUE_DATE

# Guarantee maturity: 2027-12-31 (2y original maturity ≥ 1y → eligible under Art. 237(2)(a))
GUARANTEE_MATURITY_DATE = date(2027, 12, 31)

# Loan economics
LOAN_DRAWN_AMOUNT = 1_000_000.0
LOAN_INTEREST = 0.0
LOAN_EAD = LOAN_DRAWN_AMOUNT + LOAN_INTEREST  # 1,000,000 GBP

# Guarantee coverage
AMOUNT_COVERED = 1_000_000.0  # full face coverage
PERCENTAGE_COVERED = 1.0
ORIGINAL_MATURITY_YEARS = 2.0  # ≥ 1y → satisfies Art. 237(2)(a) eligibility

# CQS of guarantor institution
# CQS 2 is the discriminating value:
#   CRR Table 4 (short-term, correct post-fix): 20%
#   CRR Table 3 (long-term, pre-fix bug):        50%
#   B31 Table 4 (short-term, correct post-fix): 20%
#   B31 Table 3 (long-term, pre-fix bug):        30% (UK CQS 2 deviation)
GUARANTOR_CQS: int = 2

# Moody's rating value for CQS 2 (A1/A2/A3 → CQS 2)
GUARANTOR_RATING_VALUE = "A2"
RATING_AGENCY = "Moody's"
RATING_DATE = date(2025, 12, 1)

# Expected risk weights (for documentation; assertions live in the test)
# CRR:
EXPECTED_GUARANTOR_RW_CRR_TABLE4: float = 0.20  # correct (post-fix, Art. 120(2) Table 4)
EXPECTED_GUARANTOR_RW_CRR_TABLE3: float = 0.50  # bug     (pre-fix, Art. 120(1) Table 3)
EXPECTED_RWA_CRR_POSTFIX: float = LOAN_EAD * EXPECTED_GUARANTOR_RW_CRR_TABLE4  # 200,000
EXPECTED_RWA_CRR_PREFIX: float = LOAN_EAD * EXPECTED_GUARANTOR_RW_CRR_TABLE3   # 500,000

# Basel 3.1 (UK CQS 2 deviation: Table 3 = 30% for long-term):
EXPECTED_GUARANTOR_RW_B31_TABLE4: float = 0.20  # correct (post-fix, Art. 120(2) Table 4)
EXPECTED_GUARANTOR_RW_B31_TABLE3: float = 0.30  # bug     (pre-fix, Art. 120(1) Table 3, UK deviation)
EXPECTED_RWA_B31_POSTFIX: float = LOAN_EAD * EXPECTED_GUARANTOR_RW_B31_TABLE4  # 200,000
EXPECTED_RWA_B31_PREFIX: float = LOAN_EAD * EXPECTED_GUARANTOR_RW_B31_TABLE3   # 300,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.122 counterparty row (borrower or guarantor institution)."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_financial_sector_entity: bool
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
            "institution_cqs": self.institution_cqs,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.122 loan: GBP 1,000,000 drawn, 81-day residual maturity (≤ 3 months).

    81 days / 365 ≈ 0.2219y ≤ 0.25y → fires the short-term gate in the CRM
    processor when deriving the guarantor's substituted risk weight.

    value_date = reporting_date = maturity derivation anchor so that residual
    maturity = original maturity for simplicity.
    """

    loan_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    drawn_amount: float
    interest: float
    seniority: str

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
        }


@dataclass(frozen=True)
class _Facility:
    """
    P1.122 parent facility for the short-term loan.

    The codebase requires a parent facility for every loan (hierarchy resolver).
    Mirrors the loan's maturity so no facility-level maturity mismatch arises.
    risk_type=full_risk: on-balance-sheet drawn exposure — no CCF needed.
    """

    facility_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    limit: float
    committed: bool
    risk_type: str

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": self.currency,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "limit": self.limit,
            "committed": self.committed,
            "risk_type": self.risk_type,
        }


@dataclass(frozen=True)
class _Guarantee:
    """
    P1.122 guarantee row: 2-year unfunded guarantee from DE institution (CQS 2).

    original_maturity_years = 2.0 ≥ 1.0y → satisfies Art. 237(2)(a) eligibility.
    guarantee maturity (2027-12-31) > loan maturity (2026-03-22) → no maturity
    mismatch adjustment required on the guarantee side.

    The discriminating risk weight for CQS 2:
        CRR Table 4 (short-term, post-fix): 20%
        CRR Table 3 (long-term, pre-fix):   50%
    """

    guarantee_reference: str
    guarantee_type: str
    guarantor: str
    currency: str
    maturity_date: date
    amount_covered: float
    percentage_covered: float
    beneficiary_type: str
    beneficiary_reference: str
    protection_type: str
    original_maturity_years: float
    guarantor_seniority: str

    def to_dict(self) -> dict:
        return {
            "guarantee_reference": self.guarantee_reference,
            "guarantee_type": self.guarantee_type,
            "guarantor": self.guarantor,
            "currency": self.currency,
            "maturity_date": self.maturity_date,
            "amount_covered": self.amount_covered,
            "percentage_covered": self.percentage_covered,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "protection_type": self.protection_type,
            "original_maturity_years": self.original_maturity_years,
            "guarantor_seniority": self.guarantor_seniority,
        }


@dataclass(frozen=True)
class _Rating:
    """
    P1.122 external ECAI rating for the guarantor institution.

    Moody's A2 → CQS 2 under the EBA/PRA ECAI mapping.
    is_solicited=True: solicited rating; used by the engine's ECAI-rated path.
    pd=None: external rating — PD is internal rating territory.
    model_id=None: pure SA scenario, no IRB model.
    """

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
    cqs: int
    pd: float | None
    rating_date: date
    is_solicited: bool
    model_id: str | None

    def to_dict(self) -> dict:
        return {
            "rating_reference": self.rating_reference,
            "counterparty_reference": self.counterparty_reference,
            "rating_type": self.rating_type,
            "rating_agency": self.rating_agency,
            "rating_value": self.rating_value,
            "cqs": self.cqs,
            "pd": self.pd,
            "rating_date": self.rating_date,
            "is_solicited": self.is_solicited,
            "model_id": self.model_id,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1122_counterparties() -> pl.DataFrame:
    """
    Return two P1.122 counterparties (borrower + guarantor institution) as a DataFrame.

    CP-BORROWER-P1122: corporate, GB, unrated → 100% CRR corporate SA RW (unrated).
        No external rating → no institution_cqs.
    CP-GUARANTOR-P1122: institution, DE, CQS 2 (Moody's A2), externally rated.
        institution_cqs=2 populated as a denormalised field; the ratings table
        carries the authoritative external CQS signal that drives ECRA lookup.
        scra_grade is absent (null) → ECRA path, not SCRA.
        is_financial_sector_entity=False: no FI scalar on the guarantee substitution.
    """
    rows = [
        _Counterparty(
            counterparty_reference=BORROWER_REF,
            counterparty_name="P1.122 Corporate Borrower GB",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
            institution_cqs=None,
        ),
        _Counterparty(
            counterparty_reference=GUARANTOR_REF,
            counterparty_name="P1.122 Guarantor Institution DE CQS2 Moody A2",
            entity_type="institution",
            country_code="DE",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
            institution_cqs=GUARANTOR_CQS,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1122_loan() -> pl.DataFrame:
    """
    Return one P1.122 short-term loan (81-day, GBP 1m) as a DataFrame.

    EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000 GBP.
    Residual maturity = 81 / 365 ≈ 0.2219y ≤ 0.25y.
    The engine CRM processor must detect this threshold and route the guarantor
    risk weight lookup to Table 4 (short-term) rather than Table 3 (long-term).
    """
    row = _Loan(
        loan_reference=LOAN_REF,
        counterparty_reference=BORROWER_REF,
        currency="GBP",
        value_date=LOAN_VALUE_DATE,
        maturity_date=LOAN_MATURITY_DATE,
        drawn_amount=LOAN_DRAWN_AMOUNT,
        interest=LOAN_INTEREST,
        seniority="senior",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p1122_facility() -> pl.DataFrame:
    """
    Return one P1.122 parent facility as a DataFrame.

    FAC-P1122 mirrors the loan's counterparty, currency, and maturity so the
    hierarchy resolver can link LN-P1122 to FAC-P1122 unambiguously.
    risk_type=full_risk: on-balance-sheet drawn loan → no CCF applied.
    committed=True: firm commitment.
    """
    row = _Facility(
        facility_reference=FACILITY_REF,
        counterparty_reference=BORROWER_REF,
        currency="GBP",
        value_date=LOAN_VALUE_DATE,
        maturity_date=LOAN_MATURITY_DATE,
        limit=LOAN_DRAWN_AMOUNT,
        committed=True,
        risk_type="full_risk",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(FACILITY_SCHEMA))


def create_p1122_guarantee() -> pl.DataFrame:
    """
    Return one P1.122 guarantee as a DataFrame.

    GTE-P1122: 2-year unfunded guarantee from DE institution (CQS 2, Moody's A2).

    original_maturity_years = 2.0 ≥ 1.0y → satisfies CRR Art. 237(2)(a) eligibility.
    beneficiary_type="loan", beneficiary_reference=LOAN_REF → links to LN-P1122.
    guarantee_type="unfunded": credit guarantee (not a letter of credit).
    protection_type="guarantee": canonical CRM type string.
    currency="GBP": matches loan currency → no FX mismatch haircut (Hfx = 0).
    guarantor_seniority="senior": F-IRB LGD selector (irrelevant for this SA scenario;
        included for schema completeness per P1.156 pattern).
    """
    guarantee = _Guarantee(
        guarantee_reference=GUARANTEE_REF,
        guarantee_type="unfunded",
        guarantor=GUARANTOR_REF,
        currency="GBP",
        maturity_date=GUARANTEE_MATURITY_DATE,
        amount_covered=AMOUNT_COVERED,
        percentage_covered=PERCENTAGE_COVERED,
        beneficiary_type="loan",
        beneficiary_reference=LOAN_REF,
        protection_type="guarantee",
        original_maturity_years=ORIGINAL_MATURITY_YEARS,
        guarantor_seniority="senior",
    )
    return pl.DataFrame([guarantee.to_dict()], schema=dtypes_of(GUARANTEE_SCHEMA))


def create_p1122_ratings() -> pl.DataFrame:
    """
    Return one P1.122 external rating (guarantor institution only) as a DataFrame.

    RT-GUARANTOR-P1122: Moody's A2 → CQS 2.
    This is the external ECAI rating that routes the guarantor to the ECRA path
    (not SCRA). The SA engine uses the CQS value from the ratings table for risk
    weight lookup in both Table 3 (long-term) and Table 4 (short-term).

    The borrower (CP-BORROWER-P1122) is a corporate and has no rating row; the
    engine falls back to the unrated corporate path (100% SA RW under both CRR
    and B31 for standard corporate).
    """
    row = _Rating(
        rating_reference=RATING_REF,
        counterparty_reference=GUARANTOR_REF,
        rating_type="external",
        rating_agency=RATING_AGENCY,
        rating_value=GUARANTOR_RATING_VALUE,
        cqs=GUARANTOR_CQS,
        pd=None,
        rating_date=RATING_DATE,
        is_solicited=True,
        model_id=None,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type, written to data/ subdirectory)
# ---------------------------------------------------------------------------


def save_p1122_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.122 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the ``data/`` subdirectory
            next to this file (``tests/fixtures/p1_122/data/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent / "data"
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_p1122_counterparties()),
        ("loan", create_p1122_loan()),
        ("facility", create_p1122_facility()),
        ("guarantee", create_p1122_guarantee()),
        ("rating", create_p1122_ratings()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.122 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR Art. 120(2) Table 4 guarantor short-term institution substitution")
    print(f"  Borrower:  {BORROWER_REF} (corporate, GB, unrated)")
    print(f"  Guarantor: {GUARANTOR_REF} (institution, DE, CQS {GUARANTOR_CQS}, Moody's A2)")
    print(f"  Loan:      {LOAN_REF}  GBP {LOAN_DRAWN_AMOUNT:,.0f}")
    print(f"             value_date={LOAN_VALUE_DATE}, maturity_date={LOAN_MATURITY_DATE} (81 days)")
    print(f"             residual ≈ 0.2219y ≤ 0.25y → short-term gate fires")
    print(f"  Guarantee: {GUARANTEE_REF}  100% coverage, original_maturity={ORIGINAL_MATURITY_YEARS}y")
    print()
    print("  CRR (CalculationConfig.crr()):")
    print(f"    Table 4 (short-term, post-fix): CQS {GUARANTOR_CQS} → {EXPECTED_GUARANTOR_RW_CRR_TABLE4:.0%}")
    print(f"    Table 3 (long-term, pre-fix):   CQS {GUARANTOR_CQS} → {EXPECTED_GUARANTOR_RW_CRR_TABLE3:.0%}")
    print(f"    Expected RWA (post-fix) = {EXPECTED_RWA_CRR_POSTFIX:,.0f}")
    print(f"    Bug RWA      (pre-fix)  = {EXPECTED_RWA_CRR_PREFIX:,.0f}")
    print()
    print("  B31 (CalculationConfig.basel_3_1()):")
    print(f"    Table 4 (short-term, post-fix): CQS {GUARANTOR_CQS} → {EXPECTED_GUARANTOR_RW_B31_TABLE4:.0%}")
    print(f"    Table 3 (long-term, pre-fix):   CQS {GUARANTOR_CQS} → {EXPECTED_GUARANTOR_RW_B31_TABLE3:.0%} (UK deviation)")
    print(f"    Expected RWA (post-fix) = {EXPECTED_RWA_B31_POSTFIX:,.0f}")
    print(f"    Bug RWA      (pre-fix)  = {EXPECTED_RWA_B31_PREFIX:,.0f}")


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_p1122_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    main()
