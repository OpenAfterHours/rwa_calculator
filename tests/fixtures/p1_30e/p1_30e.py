"""
Generate P1.30(e) fixtures: CRR Art. 234 mezzanine partial-protection tranching.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/guarantees.py)

Scenario design (P1.30(e) — Art. 234 attachment/detachment tranching):

    A corporate obligor (unrated, CRR SA RW = 100%) has a GBP 1,000,000 loan.
    An institution guarantor (CQS 2, CRR SA RW = 50%) provides a GBP 400,000
    guarantee that attaches at a = GBP 200,000 and detaches at d = GBP 600,000,
    forming a mezzanine band [a, d) rather than the default first-loss [0, G).

    Under CRR Art. 234, the borrower retains BOTH:
      - first-loss tranche  [0, a)      = GBP 200,000 at obligor RW (100%)
      - senior tranche      [d, EAD]    = GBP 400,000 at obligor RW (100%)

    The protected mezzanine tranche [a, d) = GBP 400,000 takes the guarantor's
    substituted RW (50%) by Art. 235 RWSM (substitution beneficial: 50% < 100%).

    The key distinction from today's engine (first-loss attach = attachment=0):
        Current engine: GA attached at 0 → guaranteed [0,400k), retained [400k,1,000k)
        Art. 234 correct: GA attached at 200k → retained [0,200k), [200k,600k) @ guarantor
                          RW, retained [600k,1,000k)
        The TOTAL RWA coincidentally equals (400k×0.50 + 600k×1.00 = 800k) in both
        interpretations when obligor RW is uniform 100% — but the ROW STRUCTURE differs.
        Tests MUST assert the three-row split, not just scalar RWA.

Hand calculation (CRR Art. 234 + Art. 235 RWSM):
    EAD           = 1,000,000
    a             =   200,000  (attachment_amount)
    d             =   600,000  (detachment_amount)
    amount_covered=   400,000  (= d - a, reconciles)

    No haircuts: same currency (GBP/GBP), original_maturity_years=5.0 (>= 1y, no mismatch).

    first-loss [0, a)   = 200,000 @ obligor 100%   → RWA = 200,000
    protected  [a, d)   = 400,000 @ guarantor 50%  → RWA = 200,000 (beneficial: 50% < 100%)
    senior     [d, EAD] = 400,000 @ obligor 100%   → RWA = 400,000
    Σ EAD  = 1,000,000  (conservation)
    Σ RWA  = 800,000
    Blended RW = 800,000 / 1,000,000 = 0.80 (80%)

Expected output (post-CRM stage, EXP-234-1 splits into THREE rows):
    EXP-234-1__REM_FL  (first-loss):  guaranteed_portion=0,       unguaranteed=200k, EAD=200k,  RW=1.00, RWA=200k
    EXP-234-1__G_CP-INST-1 (mez):    guaranteed_portion=400k,     unguaranteed=0,    EAD=400k,  RW=0.50, RWA=200k
    EXP-234-1__REM_SEN (senior):      guaranteed_portion=0,        unguaranteed=400k, EAD=400k,  RW=1.00, RWA=400k

New columns on GUARANTEE_SCHEMA introduced by this scenario (engine-implementer task):
    attachment_amount: ColumnSpec(pl.Float64, required=False) — Art. 234 attachment point a.
        null => a = 0 => first-loss (current behaviour preserved).
    detachment_amount: ColumnSpec(pl.Float64, required=False) — Art. 234 detachment point d.
        null => d = a + amount_covered (implied by amount_covered alone).

Schema note: attachment_amount and detachment_amount are NOT yet in GUARANTEE_SCHEMA.
    They are appended via with_columns() after building the base DataFrame from
    dtypes_of(GUARANTEE_SCHEMA), so the parquet carries them forward-compatibly.
    The engine-implementer must:
        1. Add both fields to GUARANTEE_SCHEMA in src/rwa_calc/data/schemas.py.
        2. Extend _build_remainder_sub_rows() in engine/crm/guarantees.py to emit
           two retained rows (__REM_FL, __REM_SEN) when attachment_amount is non-null.
        3. Update the redistribute_non_beneficial remainder-detection predicate
           from .str.ends_with("__REM") to .str.contains("__REM").

Regulatory references:
    - CRR Art. 234: tranching of credit protection (attachment/detachment).
    - CRR Art. 233A: proportional (for contrast — not exercised here).
    - CRR Art. 235: SA risk-weight substitution method (RWSM).
    - CRR Art. 213: beneficial substitution condition (guarantor RW < borrower RW).
    - CRR Art. 120 Table 3: institution SA risk weights by CQS; CQS 2 = 50%.
    - CRR Art. 122 Table 5: corporate SA risk weights; unrated = 100%.
    - CRR Art. 237(2)(a): original maturity >= 1y for eligibility (satisfied: 5.0y).
    - CRR Art. 238/239(3): maturity mismatch (not triggered: same maturity).

Usage:
    PYTHONPATH=/path/to/worktree/src /path/to/.venv/bin/python tests/fixtures/p1_30e/p1_30e.py
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
BORROWER_REF: str = "CP-CORP-1"       # corporate, unrated, 100% CRR SA RW
GUARANTOR_REF: str = "CP-INST-1"      # institution, CQS 2, 50% CRR SA RW (Art. 120 Table 3)

# Exposure / loan reference (scenario-architect designation: EXP-234-1 as a loan)
LOAN_REF: str = "EXP-234-1"

# Guarantee reference
GUARANTEE_REF: str = "G-234-1"

# Rating references
RTG_BORROWER_REF: str = "RTG-P130E-BORROWER"
RTG_GUARANTOR_REF: str = "RTG-P130E-GUARANTOR"

# Dates — CRR framework effective up to 31 Dec 2026
LOAN_VALUE_DATE: date = date(2026, 1, 2)
LOAN_MATURITY_DATE: date = date(2031, 1, 2)        # 5y residual; maturity mismatch absent
GUARANTEE_MATURITY_DATE: date = date(2031, 1, 2)   # matches loan — no Art. 239(3) adjustment
RATING_DATE: date = date(2026, 1, 2)

# Loan economics
LOAN_DRAWN_AMOUNT: float = 1_000_000.0
LOAN_INTEREST: float = 0.0
LOAN_EAD: float = LOAN_DRAWN_AMOUNT  # EAD = drawn + interest = 1,000,000

# Guarantee economics — Art. 234 mezzanine tranche [a, d)
GUARANTEE_AMOUNT_COVERED: float = 400_000.0   # protected tranche width = d - a
ATTACHMENT_AMOUNT: float = 200_000.0           # a: Art. 234 attachment point
DETACHMENT_AMOUNT: float = 600_000.0           # d: Art. 234 detachment point
ORIGINAL_MATURITY_YEARS: float = 5.0           # >= 1y → Art. 237(2)(a) eligibility satisfied

# Derived tranche widths
FIRST_LOSS_WIDTH: float = ATTACHMENT_AMOUNT                           # [0, a)   = 200,000
PROTECTED_WIDTH: float = DETACHMENT_AMOUNT - ATTACHMENT_AMOUNT        # [a, d)   = 400,000
SENIOR_WIDTH: float = LOAN_EAD - DETACHMENT_AMOUNT                    # [d, EAD] = 400,000

# CQS assignments
# Borrower: unrated — not added to ratings (no external CQS entry)
GUARANTOR_CQS: int = 2   # institution CQS 2 → 50% SA RW (CRR Art. 120 Table 3)

# SA risk weights (CRR framework)
BORROWER_RW: float = 1.00   # corporate unrated, CRR Art. 122 Table 5
GUARANTOR_RW: float = 0.50  # institution CQS 2, CRR Art. 120 Table 3

# Hand-calc expected values (assertions live in acceptance tests, not here)
EXPECTED_RWA_FIRST_LOSS: float = FIRST_LOSS_WIDTH * BORROWER_RW     # 200,000
EXPECTED_RWA_PROTECTED: float = PROTECTED_WIDTH * GUARANTOR_RW      # 200,000
EXPECTED_RWA_SENIOR: float = SENIOR_WIDTH * BORROWER_RW             # 400,000
EXPECTED_RWA_TOTAL: float = (
    EXPECTED_RWA_FIRST_LOSS + EXPECTED_RWA_PROTECTED + EXPECTED_RWA_SENIOR
)  # 800,000
EXPECTED_EAD_TOTAL: float = LOAN_EAD                                # 1,000,000 (conserved)
EXPECTED_BLENDED_RW: float = EXPECTED_RWA_TOTAL / EXPECTED_EAD_TOTAL  # 0.80 (80%)


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
    The loan is classified as corporate SA under CRR: unrated → 100% RW.

    Under Art. 234 the CRM stage splits this into three sub-rows:
        EXP-234-1__REM_FL  (first-loss retained, 200k),
        EXP-234-1__G_CP-INST-1 (mezzanine guaranteed, 400k),
        EXP-234-1__REM_SEN (senior retained, 400k).
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
        rating_value="A",          # representative S&P value for CQS 2 (A+ to A-)
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

    G-234-1: GBP 400,000 guarantee from CP-INST-1 (CQS 2, 50% RW) on EXP-234-1.

    Art. 234 mezzanine tranche:
        attachment_amount = 200,000  (a: protection starts at GBP 200k loss)
        detachment_amount = 600,000  (d: protection ends at GBP 600k loss)
        Protected width   = d - a = 400,000 = amount_covered  (reconciles)

    No haircuts apply:
        - Same currency (GBP/GBP): no FX mismatch haircut (Art. 233(3)).
        - original_maturity_years = 5.0 >= 1y: Art. 237(2)(a) eligibility satisfied.
        - Guarantee maturity matches loan: no Art. 239(3) scaling.

    Schema note: attachment_amount and detachment_amount are NEW fields not yet
    declared in GUARANTEE_SCHEMA. They are appended via with_columns() following
    the P1.161 pattern so the parquet carries them forward-compatibly. The
    engine-implementer must add both to GUARANTEE_SCHEMA in src/rwa_calc/data/schemas.py.
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
    # Append new Art. 234 fields not yet declared in GUARANTEE_SCHEMA.
    # Pattern mirrors P1.161: build from dtypes_of() then extend via with_columns().
    # The schema validator does not reject extra columns in parquet on read; once the
    # engine-implementer adds the two ColumnSpec declarations the validator will enforce
    # them without requiring any change to this fixture file.
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
    print("Scenario: CRR Art. 234 mezzanine partial-protection tranching")
    print(f"  Borrower:  {BORROWER_REF} (corporate, unrated, CRR RW={BORROWER_RW:.0%})")
    print(f"  Guarantor: {GUARANTOR_REF} (institution, CQS {GUARANTOR_CQS}, CRR RW={GUARANTOR_RW:.0%})")
    print(f"  Loan:      {LOAN_REF}  GBP {LOAN_DRAWN_AMOUNT:,.0f}")
    print(f"  Guarantee: {GUARANTEE_REF}  amount_covered={GUARANTEE_AMOUNT_COVERED:,.0f}")
    print(f"             attachment_amount={ATTACHMENT_AMOUNT:,.0f}")
    print(f"             detachment_amount={DETACHMENT_AMOUNT:,.0f}")
    print()
    print("  Art. 234 three-way split:")
    print(f"    first-loss [0, {ATTACHMENT_AMOUNT:,.0f})  = {FIRST_LOSS_WIDTH:,.0f} @ {BORROWER_RW:.0%}"
          f"  → RWA = {EXPECTED_RWA_FIRST_LOSS:,.0f}")
    print(f"    protected  [{ATTACHMENT_AMOUNT:,.0f}, {DETACHMENT_AMOUNT:,.0f}) = {PROTECTED_WIDTH:,.0f} @ {GUARANTOR_RW:.0%}"
          f"  → RWA = {EXPECTED_RWA_PROTECTED:,.0f}")
    print(f"    senior     [{DETACHMENT_AMOUNT:,.0f}, {LOAN_EAD:,.0f}] = {SENIOR_WIDTH:,.0f} @ {BORROWER_RW:.0%}"
          f"  → RWA = {EXPECTED_RWA_SENIOR:,.0f}")
    print(f"  Σ EAD = {EXPECTED_EAD_TOTAL:,.0f}  Σ RWA = {EXPECTED_RWA_TOTAL:,.0f}"
          f"  blended RW = {EXPECTED_BLENDED_RW:.0%}")
    print()
    print("  Schema extensions required (engine-implementer):")
    print("    schemas.py GUARANTEE_SCHEMA: add attachment_amount (Float64, required=False)")
    print("    schemas.py GUARANTEE_SCHEMA: add detachment_amount (Float64, required=False)")
    print("    engine/crm/guarantees.py: extend _build_remainder_sub_rows() for two-tranche split")
    print("    engine/crm/guarantees.py: update redistribute_non_beneficial predicate")
    print("      from .str.ends_with('__REM') to .str.contains('__REM')")


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
