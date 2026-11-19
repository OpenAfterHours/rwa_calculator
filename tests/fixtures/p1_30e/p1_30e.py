"""
Generate P1.30(e) fixtures: tranched (Art. 234) protection is not substituted.

Pipeline position:
    fixture-builder output -> tests/acceptance/crr/test_p1_30e_art_234_partial_protection_tranching.py

Scenario design:

    A corporate obligor (unrated, SA RW 100% in both regimes) has a GBP
    1,000,000 loan. An institution guarantor (CQS 2: 50% CRR / 30% Basel 3.1)
    provides a GBP 400,000 guarantee that attaches at a = GBP 200,000 and
    detaches at d = GBP 600,000 — a mezzanine band [a, d) of the loss, not a
    pro-rata share of the exposure.

Rule (PS1/26 Appendix 1; CRR Art. 234 / 235(2) read the same in substance):

    Art. 234(1): "Where an institution transfers a part of the risk of a loan in
    one or more tranches, the institution shall comply with the requirements set
    out in Chapter 5 of Title II of Part Three of CRR."
    Art. 235(2): "Where the protected amount (GA) is less than the exposure (E),
    the institution may apply the formula specified in paragraphs 1 and 1A only
    where the protected and unprotected parts of the exposure are of equal
    seniority."

    The band [a, d) is by construction not of equal seniority with [0, a) and
    [d, E], so the risk-weight substitution method may not be used. The engine
    does not run Chapter 5 for such protection, so the guarantee is NOT
    recognised (CRM027) and the loan keeps the obligor's 100%, the Art. 268(1)
    upper bound of the Chapter 5 result. (GT-03 of the guarantees review; this
    reverses the P1.30(e) design, which substituted on the mezzanine band and
    recognised RWA 800,000 under CRR / 720,000 under Basel 3.1.)

Hand calculation (both regimes):
    EAD = 1,000,000 at obligor 100%            -> RWA = 1,000,000
    No guarantor sub-row; one CRM027 naming G-234-1.

Control (same guarantee with attachment / detachment left null, a pro-rata
share): 400,000 at the guarantor's weight + 600,000 at 100% -> RWA 800,000
(CRR) / 720,000 (Basel 3.1). The acceptance test runs it to show that the
tranching columns alone decide the outcome.

Regulatory references:
    - CRR Art. 234 / PS1/26 Art. 234(1): tranched transfer of risk -> Chapter 5.
    - CRR / PS1/26 Art. 235(2): substitution only for equal seniority.
    - CRR Art. 268(1): the securitisation cap at the underlying requirement.
    - CRR Art. 120 Table 3 / PS1/26 ECRA: institution CQS 2 risk weight.
    - CRR / PS1/26 Art. 122: unrated corporate 100%.

Usage:
    uv run python tests/fixtures/p1_30e/p1_30e.py
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
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references
BORROWER_REF: str = "CP-CORP-1"  # corporate, unrated, 100% CRR SA RW
GUARANTOR_REF: str = "CP-INST-1"  # institution, CQS 2, 50% CRR SA RW (Art. 120 Table 3)

# Exposure / loan reference (scenario-architect designation: EXP-234-1 as a loan)
LOAN_REF: str = "EXP-234-1"

# Guarantee reference
GUARANTEE_REF: str = "G-234-1"

# Rating references
RTG_BORROWER_REF: str = "RTG-P130E-BORROWER"
RTG_GUARANTOR_REF: str = "RTG-P130E-GUARANTOR"

# Dates — CRR framework effective up to 31 Dec 2026
LOAN_VALUE_DATE: date = date(2026, 1, 2)
LOAN_MATURITY_DATE: date = date(2031, 1, 2)  # 5y residual; maturity mismatch absent
GUARANTEE_MATURITY_DATE: date = date(2031, 1, 2)  # matches loan — no Art. 239(3) adjustment
RATING_DATE: date = date(2026, 1, 2)

# Loan economics
LOAN_DRAWN_AMOUNT: float = 1_000_000.0
LOAN_INTEREST: float = 0.0
LOAN_EAD: float = LOAN_DRAWN_AMOUNT  # EAD = drawn + interest = 1,000,000

# Guarantee economics — Art. 234 mezzanine band [a, d)
GUARANTEE_AMOUNT_COVERED: float = 400_000.0  # band width = d - a
ATTACHMENT_AMOUNT: float = 200_000.0  # a: Art. 234 attachment point
DETACHMENT_AMOUNT: float = 600_000.0  # d: Art. 234 detachment point
ORIGINAL_MATURITY_YEARS: float = 5.0  # >= 1y → Art. 237(2)(a) eligibility satisfied

# CQS assignments
# Borrower: unrated — not added to ratings (no external CQS entry)
GUARANTOR_CQS: int = 2  # institution CQS 2

# SA risk weights by regime (measured engine output, read from the rulepack)
BORROWER_RW: float = 1.00  # corporate unrated, both regimes
GUARANTOR_RW: dict[str, float] = {"crr": 0.50, "b31": 0.30}

# Hand-calc expected values (assertions live in the acceptance test, not here)
EXPECTED_RWA_TOTAL: float = LOAN_EAD * BORROWER_RW  # 1,000,000 — not recognised
EXPECTED_EAD_TOTAL: float = LOAN_EAD  # 1,000,000
# Control: the same guarantee as a pro-rata share (no attachment / detachment).
EXPECTED_CONTROL_RWA: dict[str, float] = {
    regime: GUARANTEE_AMOUNT_COVERED * rw + (LOAN_EAD - GUARANTEE_AMOUNT_COVERED) * BORROWER_RW
    for regime, rw in GUARANTOR_RW.items()
}  # crr 800,000; b31 720,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.30(e) counterparty row."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
        }


@dataclass(frozen=True)
class _Loan:
    """P1.30(e) loan: GBP 1,000,000, 5-year residual."""

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
class _Rating:
    """P1.30(e) external ECAI rating."""

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


def create_p130e_counterparties() -> pl.DataFrame:
    """
    Return two P1.30(e) counterparties (borrower + guarantor) as a DataFrame.

    CP-CORP-1: corporate, GB, unrated (no external CQS entry) → CRR SA RW = 100%.
        No rating row is attached to this counterparty. The CRM beneficial test
        (Art. 213) confirms guarantor 50% < obligor 100%, enabling substitution.

    CP-INST-1: institution, GB, CQS 2 → CRR Art. 120 Table 3 SA RW = 50%.
        Rating row RTG-P130E-GUARANTOR links the external CQS 2 to this counterparty.
    """
    rows = [
        _Counterparty(
            counterparty_reference=BORROWER_REF,
            counterparty_name="P1.30e Corporate Borrower GB (unrated)",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=GUARANTOR_REF,
            counterparty_name="P1.30e Institution Guarantor GB CQS2",
            entity_type="institution",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p130e_loan() -> pl.DataFrame:
    """
    Return one P1.30(e) loan as a DataFrame.

    EXP-234-1: GBP 1,000,000 drawn, 5-year maturity, CP-CORP-1.
    EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000.
    The loan is corporate SA: unrated → 100% RW in both regimes. The tranched
    guarantee is not recognised, so the loan is not split.
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


def create_p130e_ratings() -> pl.DataFrame:
    """
    Return one P1.30(e) external rating (guarantor only) as a DataFrame.

    RTG-P130E-GUARANTOR: CP-INST-1, external, S&P A (representative CQS 2 mid-band).
        CQS 2 → CRR Art. 120 Table 3 institution SA RW = 50%.

    No rating for the borrower CP-CORP-1: unrated → engine defaults to 100% corporate
    SA RW (CRR Art. 122 Table 5 unrated column). Having no rating row is load-bearing
    for the beneficial-test outcome — the unrated 100% RW is the benchmark against which
    the guarantor's 50% is measured.
    """
    row = _Rating(
        rating_reference=RTG_GUARANTOR_REF,
        counterparty_reference=GUARANTOR_REF,
        rating_type="external",
        rating_agency="S&P",
        rating_value="A",  # representative S&P value for CQS 2 (A+ to A-)
        cqs=GUARANTOR_CQS,
        pd=None,
        rating_date=RATING_DATE,
        is_solicited=True,
        model_id=None,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(RATINGS_SCHEMA))


def create_p130e_guarantee() -> pl.DataFrame:
    """
    Return one P1.30(e) guarantee row as a DataFrame.

    G-234-1: GBP 400,000 guarantee from CP-INST-1 (CQS 2) on EXP-234-1.

    Art. 234 mezzanine band:
        attachment_amount = 200,000  (a: protection starts at GBP 200k loss)
        detachment_amount = 600,000  (d: protection ends at GBP 600k loss)
        Band width        = d - a = 400,000 = amount_covered  (reconciles)

    Were it a pro-rata share, no haircut would apply: GBP/GBP (no Art. 233(3)
    Hfx), original_maturity_years 5.0 (Art. 237(2)(a) met), maturity matches
    the loan (no Art. 239(3) scaling) — so the control run isolates tranching.
    """
    base_row = {
        "guarantee_reference": GUARANTEE_REF,
        "guarantee_type": "guarantee",
        "guarantor": GUARANTOR_REF,
        "currency": "GBP",
        "maturity_date": GUARANTEE_MATURITY_DATE,
        "amount_covered": GUARANTEE_AMOUNT_COVERED,
        "percentage_covered": GUARANTEE_AMOUNT_COVERED / LOAN_EAD,  # 0.40 (40%)
        "beneficiary_type": "loan",
        "beneficiary_reference": LOAN_REF,
        "protection_type": "guarantee",
        "includes_restructuring": False,
        "original_maturity_years": ORIGINAL_MATURITY_YEARS,
        "guarantor_seniority": "senior",
    }
    base_df = pl.DataFrame([base_row], schema=dtypes_of(GUARANTEE_SCHEMA))
    return base_df.with_columns(
        pl.lit(ATTACHMENT_AMOUNT).alias("attachment_amount"),
        pl.lit(DETACHMENT_AMOUNT).alias("detachment_amount"),
    )


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p130e_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.30(e) parquet files and return a mapping of name to path.

    Files written:
        counterparty.parquet  — 2 rows (CP-CORP-1 borrower, CP-INST-1 guarantor)
        loan.parquet          — 1 row  (EXP-234-1, GBP 1,000,000)
        rating.parquet        — 1 row  (RTG-P130E-GUARANTOR, CQS 2)
        guarantee.parquet     — 1 row  (G-234-1, attachment=200k, detachment=600k)

    Args:
        output_dir: Target directory. Defaults to the directory of this file
            (``tests/fixtures/p1_30e/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p130e_counterparties()),
        ("loan", create_p130e_loan()),
        ("rating", create_p130e_ratings()),
        ("guarantee", create_p130e_guarantee()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.30(e) fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>2} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: Art. 234 tranched protection is not substituted (CRM027)")
    print(f"  Borrower:  {BORROWER_REF} (corporate, unrated, RW={BORROWER_RW:.0%})")
    print(f"  Guarantor: {GUARANTOR_REF} (institution, CQS {GUARANTOR_CQS})")
    print(f"  Loan:      {LOAN_REF}  GBP {LOAN_DRAWN_AMOUNT:,.0f}")
    print(f"  Guarantee: {GUARANTEE_REF}  amount_covered={GUARANTEE_AMOUNT_COVERED:,.0f}")
    print(f"             attachment_amount={ATTACHMENT_AMOUNT:,.0f}")
    print(f"             detachment_amount={DETACHMENT_AMOUNT:,.0f}")
    print(f"  Expected RWA (both regimes) = {EXPECTED_RWA_TOTAL:,.0f}")


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_p130e_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    main()
