"""
Generate P1.160 fixtures: PSM LGD routing by guarantor_seniority — subordinated case.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/guarantees.py)

Key responsibilities:
- Produce one borrower counterparty: corporate, GB, is_natural_person=False.
- Produce one guarantor counterparty: corporate, GB, is_natural_person=False.
- Produce one loan row: senior, M=2.5y, EAD=1,000,000 GBP, foundation_irb.
- Produce one guarantee row: GUAR_P1_160_001, subordinated guarantor, covering 100%
  of the loan, original_maturity_years=5.0.
- Produce two internal rating rows: borrower PD=0.0150, guarantor PD=0.0050.
- Produce two model-permission rows: F-IRB for corporate (borrower and guarantor).

Scenario design:
    This fixture exercises Art. 236(1)(a) PSM LGD routing when the guarantor's
    claim is subordinated (guarantor_seniority="subordinated").

    Under B31 Art. 161(1)(b), a subordinated claim carries supervisory LGD = 0.75.
    A senior claim under Art. 161(1)(aa) carries LGD = 0.40 (non-FSE, non-subordinated).

    The discriminating outcome:
    - Post-fix (correct): guarantor_seniority="subordinated" → LGD=0.75
        → guarantor_rw_irb ≈ 1.16037 (corporate, PD=0.005, M=2.5y, LGD=0.75)
        → guarantee NOT beneficial (guarantor_rw > borrower_rw ≈ 0.93869)
        → engine retains borrower RWA ≈ 938,690 (is_guarantee_beneficial=False)

    - Pre-fix bug: guarantor_seniority ignored → LGD=0.40 (senior default)
        → guarantor_rw_irb ≈ 0.61887 (corporate, PD=0.005, M=2.5y, LGD=0.40)
        → guarantee incorrectly applied → blended RWA ≈ 618,870

    The gap is in engine/crm/guarantees.py::apply_guarantees not threading the
    guarantor_seniority column through to the IRB guarantee calculation.

    Borrower (CORPORATE, F-IRB, non-FSE):
        PD_borrower = 0.0150 (1.5%)
        F-IRB supervisory LGD (senior, non-FSE, B31) = 0.40 (Art. 161(1)(aa))
        EAD = 1,000,000 GBP, M = 2.5y
        IRB RW ≈ 0.93869

    Guarantor (CORPORATE, F-IRB, non-FSE, SUBORDINATED):
        PD_guarantor = 0.0050 (0.50%)
        F-IRB supervisory LGD (subordinated, Art. 161(1)(b)) = 0.75
        IRB RW post-fix ≈ 1.16037 → guarantee NOT beneficial
        IRB RW pre-fix (LGD=0.40) ≈ 0.61887 → guarantee wrongly applied

    Guarantee:
        amount_covered = 1,000,000 GBP (100% — full coverage)
        guarantor_seniority = "subordinated"   (the load-bearing field)
        original_maturity_years = 5.0 (> M=2.5 → satisfies Art. 237(2)(a))

Hand-calc reference (do NOT assert here — test-writer's job):
    Borrower IRB RW (B31, corporate, PD=0.015, M=2.5y, LGD=0.40, no FI scalar):
        R = 0.12*(1-exp(-50*0.015))/(1-exp(-50)) + 0.24*(1-(1-exp(-50*0.015))/(1-exp(-50)))
        b = (0.11852 - 0.05478*ln(0.015))^2
        MA = (1 + (2.5 - 2.5)*b) / (1 - 1.5*b)  [simplified with M=2.5, maturity adj formula]
        RW ≈ 0.93869  →  RWA ≈ 938,690

    Guarantor PSM RW (post-fix): corporate, PD=0.005, M=2.5y, LGD=0.75
        guarantor_rw_irb ≈ 1.16037  →  guarantee NOT beneficial  →  RWA retained = 938,690

    Guarantor PSM RW (pre-fix): corporate, PD=0.005, M=2.5y, LGD=0.40 (wrong)
        guarantor_rw_irb ≈ 0.61887  →  guarantee wrongly applied  →  RWA = 618,870

References:
    - PRA PS1/26 Art. 236(1)(a): PSM substitutes guarantor PD/LGD/correlation.
    - PRA PS1/26 Art. 161(1)(aa): B31 F-IRB supervisory LGD 40% (senior, non-FSE corp).
    - PRA PS1/26 Art. 161(1)(b): B31 F-IRB supervisory LGD 75% (subordinated claim).
    - PRA PS1/26 Art. 163(1)(a): Corporate PD floor 0.05% (both PDs are above floor).
    - Code: src/rwa_calc/engine/irb/guarantee.py:357-365 — guarantor_seniority routing.
    - Gap: src/rwa_calc/engine/crm/guarantees.py::apply_guarantees — column not threaded.

Usage:
    uv run python tests/fixtures/p1_160/p1_160.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references
BORROWER_REF = "BORR_P1_160"
GUARANTOR_REF = "GUAR_P1_160_SUB"

# Exposure reference
LOAN_REF = "LOAN_P1_160"

# Guarantee reference
GUARANTEE_REF = "GUAR_P1_160_001"

# Rating references
RTG_BORROWER_REF = "RAT_BORR_P1_160"
RTG_GUARANTOR_REF = "RAT_GUAR_P1_160_SUB"

# Model IDs — separate per counterparty to allow clean resolution
MODEL_ID_CORP_FIRB_BORR = "CORP_FIRB_BORR_P1_160"    # F-IRB for borrower (corporate)
MODEL_ID_CORP_FIRB_GUAR = "CORP_FIRB_GUAR_P1_160"    # F-IRB for guarantor PSM path (corporate)

# Dates
VALUE_DATE = date(2026, 1, 1)
# maturity_date produces effective_maturity ≈ 2.5y from reporting_date 2027-06-30
MATURITY_DATE = date(2028, 7, 1)
GUARANTEE_MATURITY_DATE = date(2030, 12, 31)   # > facility maturity → no maturity mismatch
RATING_DATE = date(2026, 1, 1)

# IRB inputs
# Borrower: PD=0.015, well above B31 corporate floor 0.0005 — no floor effect
PD_BORROWER = 0.0150           # 1.5% corporate borrower PD
# Guarantor: PD=0.005, also above B31 corporate floor 0.0005 — no floor effect
PD_GUARANTOR = 0.0050          # 0.5% corporate guarantor PD

# Exposure amounts
EAD_AMOUNT = 1_000_000.0       # GBP 1,000,000 — loan fully drawn
AMOUNT_COVERED = 1_000_000.0   # 100% coverage — makes the is_guarantee_beneficial decision clear
PERCENTAGE_COVERED = 1.0
ORIGINAL_MATURITY_YEARS = 5.0  # > 1y → satisfies Art. 237(2)(a) eligibility
EFFECTIVE_MATURITY = 2.5       # M = 2.5y (set explicitly to avoid date-rounding ambiguity)


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """Counterparty row for P1.160."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float | None
    total_assets: float | None
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool
    is_financial_sector_entity: bool
    is_natural_person: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "annual_revenue": self.annual_revenue,
            "total_assets": self.total_assets,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
            "is_financial_sector_entity": self.is_financial_sector_entity,
            "is_natural_person": self.is_natural_person,
        }


@dataclass(frozen=True)
class _Loan:
    """
    Loan row for P1.160 — senior corporate term loan, fully drawn.

    effective_maturity=2.5 is set explicitly to avoid date-arithmetic ambiguity
    and is load-bearing for the maturity adjustment (MA) in both borrower and
    guarantor IRB RW calculations.
    """

    loan_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    drawn_amount: float
    interest: float
    seniority: str
    effective_maturity: float

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "product_type": self.product_type,
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "seniority": self.seniority,
            "effective_maturity": self.effective_maturity,
        }


@dataclass(frozen=True)
class _Guarantee:
    """
    Guarantee row for P1.160.

    Full senior-claim guarantee with guarantor_seniority="subordinated".
    The "subordinated" value is the load-bearing field that routes the engine to
    F-IRB supervisory LGD = 0.75 (Art. 161(1)(b)) rather than LGD = 0.40
    (Art. 161(1)(aa) senior non-FSE).  Post-fix: guarantor_rw_irb ≈ 1.16037,
    guarantee NOT beneficial, borrower RWA retained.
    """

    guarantee_reference: str
    guarantee_type: str
    guarantor: str
    currency: str
    maturity_date: date | None
    amount_covered: float
    percentage_covered: float
    beneficiary_type: str
    beneficiary_reference: str
    protection_type: str
    includes_restructuring: bool
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
            "includes_restructuring": self.includes_restructuring,
            "original_maturity_years": self.original_maturity_years,
            "guarantor_seniority": self.guarantor_seniority,
        }


@dataclass(frozen=True)
class _Rating:
    """Rating row for P1.160."""

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
    cqs: int
    pd: float
    rating_date: date
    is_solicited: bool
    model_id: str

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


@dataclass(frozen=True)
class _ModelPermission:
    """Model permission row for P1.160."""

    model_id: str
    exposure_class: str
    approach: str
    country_codes: str | None
    excluded_book_codes: str | None

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "exposure_class": self.exposure_class,
            "approach": self.approach,
            "country_codes": self.country_codes,
            "excluded_book_codes": self.excluded_book_codes,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1160_counterparties() -> pl.DataFrame:
    """
    Return all P1.160 counterparties as a DataFrame.

    Two rows:
    - Borrower: corporate, GB, non-FSE, is_natural_person=False,
      apply_fi_scalar=False, default_status=False.
    - Guarantor: corporate, GB, non-FSE, is_natural_person=False,
      apply_fi_scalar=False, default_status=False.
      Both are standard non-FSE corporates so the discriminating element is
      entirely the guarantor_seniority on the guarantee row.
    """
    rows = [
        _Counterparty(
            counterparty_reference=BORROWER_REF,
            counterparty_name="P1.160 Corporate Borrower PLC",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=None,          # No revenue data — treated as large corp
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,        # Non-FSE — no Art. 153(2) FI scalar
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
            is_natural_person=False,
        ),
        _Counterparty(
            counterparty_reference=GUARANTOR_REF,
            counterparty_name="P1.160 Corporate Guarantor Sub PLC",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=None,
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,        # Non-FSE — no Art. 153(2) FI scalar
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
            is_natural_person=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1160_loans() -> pl.DataFrame:
    """
    Return the P1.160 loan as a DataFrame.

    One row — senior corporate term loan, fully drawn:
    - drawn_amount=1,000,000: EAD = drawn_amount.
    - seniority="senior": borrower's own LGD is 40% (B31 Art. 161(1)(aa) non-FSE).
    - effective_maturity=2.5: load-bearing for MA in both borrower and guarantor calcs.
    - model_id not on LOAN_SCHEMA: the IRB model is identified via ratings row.
    """
    loan = _Loan(
        loan_reference=LOAN_REF,
        product_type="term_loan",
        book_code="CORP_LENDING",
        counterparty_reference=BORROWER_REF,
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        currency="GBP",
        drawn_amount=EAD_AMOUNT,
        interest=0.0,
        seniority="senior",
        effective_maturity=EFFECTIVE_MATURITY,
    )
    return pl.DataFrame([loan.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p1160_guarantees() -> pl.DataFrame:
    """
    Return the P1.160 guarantee as a DataFrame.

    One row — full corporate guarantee, guarantor_seniority="subordinated":
    - guarantor_seniority="subordinated": the load-bearing field. Routes the
      PSM engine to F-IRB supervisory LGD 75% (Art. 161(1)(b)) rather than 40%.
    - amount_covered=1,000,000 GBP (100%): full coverage makes the
      is_guarantee_beneficial decision unambiguous — either the full EAD is
      re-weighted by the guarantor's RW or retained at borrower RW.
    - original_maturity_years=5.0: > M=2.5 → satisfies Art. 237(2)(a).
    - beneficiary_type="loan": links to LOAN_P1_160 directly.
    - includes_restructuring=True: covers restructuring credit events.
    """
    guarantee = _Guarantee(
        guarantee_reference=GUARANTEE_REF,
        guarantee_type="corporate_guarantee",
        guarantor=GUARANTOR_REF,
        currency="GBP",
        maturity_date=GUARANTEE_MATURITY_DATE,
        amount_covered=AMOUNT_COVERED,
        percentage_covered=PERCENTAGE_COVERED,
        beneficiary_type="loan",
        beneficiary_reference=LOAN_REF,
        protection_type="guarantee",
        includes_restructuring=True,
        original_maturity_years=ORIGINAL_MATURITY_YEARS,
        guarantor_seniority="subordinated",
    )
    return pl.DataFrame([guarantee.to_dict()], schema=dtypes_of(GUARANTEE_SCHEMA))


def create_p1160_ratings() -> pl.DataFrame:
    """
    Return all P1.160 internal ratings as a DataFrame.

    Two rows:
    - Borrower: PD=0.0150 (1.5%), CQS=3, model_id=CORP_FIRB_BORR_P1_160.
      Above B31 corporate floor 0.0005 — no floor effect.
      Produces borrower RW ≈ 0.93869 (corporate, M=2.5y, LGD=0.40).
    - Guarantor: PD=0.0050 (0.5%), CQS=2, model_id=CORP_FIRB_GUAR_P1_160.
      Above B31 corporate floor 0.0005 — no floor effect.
      Post-fix (LGD=0.75): guarantor_rw_irb ≈ 1.16037 > borrower_rw → NOT beneficial.
      Pre-fix (LGD=0.40): guarantor_rw_irb ≈ 0.61887 < borrower_rw → wrongly applied.
    """
    rows = [
        _Rating(
            rating_reference=RTG_BORROWER_REF,
            counterparty_reference=BORROWER_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="3A",          # ~1.5% PD band — investment grade corporate
            cqs=3,
            pd=PD_BORROWER,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID_CORP_FIRB_BORR,
        ),
        _Rating(
            rating_reference=RTG_GUARANTOR_REF,
            counterparty_reference=GUARANTOR_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="2A",          # ~0.5% PD band — investment grade corporate
            cqs=2,
            pd=PD_GUARANTOR,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID_CORP_FIRB_GUAR,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1160_model_permissions() -> pl.DataFrame:
    """
    Return all P1.160 model permissions as a DataFrame.

    Two rows (one per counterparty, both corporate class):
    - CORP_FIRB_BORR_P1_160: foundation_irb for corporate (borrower's own exposure class).
    - CORP_FIRB_GUAR_P1_160: foundation_irb for corporate (guarantor's PSM path).

    Separate model_ids isolate the borrower and guarantor IRB paths so the
    engine resolves each independently. Both use foundation_irb (F-IRB) with
    supervisory LGDs — the LGD selection is determined by guarantor_seniority,
    not by the model_id.
    """
    rows = [
        _ModelPermission(
            model_id=MODEL_ID_CORP_FIRB_BORR,
            exposure_class="corporate",
            approach="foundation_irb",
            country_codes="GB",
            excluded_book_codes=None,
        ),
        _ModelPermission(
            model_id=MODEL_ID_CORP_FIRB_GUAR,
            exposure_class="corporate",
            approach="foundation_irb",
            country_codes="GB",
            excluded_book_codes=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1160_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.160 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to this package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    artefacts = [
        ("counterparty", create_p1160_counterparties()),
        ("loan", create_p1160_loans()),
        ("guarantee", create_p1160_guarantees()),
        ("rating", create_p1160_ratings()),
        ("model_permission", create_p1160_model_permissions()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.160 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: PSM LGD routing by guarantor_seniority — subordinated case")
    print("  Borrower:  corporate non-FSE F-IRB, PD=0.0150, EAD=1,000,000 GBP")
    print("  Guarantor: corporate non-FSE F-IRB, PD=0.0050, guarantor_seniority='subordinated'")
    print("  Guarantee: 100% covered (GBP 1,000,000), subordinated, original_maturity=5.0y")
    print(f"  PD_borrower          = {PD_BORROWER}")
    print(f"  PD_guarantor         = {PD_GUARANTOR}")
    print("  Borrower LGD (senior non-FSE, Art. 161(1)(aa)) = 0.40")
    print("  Guarantor LGD post-fix (subordinated, Art. 161(1)(b)) = 0.75")
    print("  Guarantor LGD pre-fix (wrong: senior default) = 0.40")
    print("  Borrower IRB RW      ≈ 0.93869  →  RWA ≈ 938,690")
    print("  Guarantor RW post-fix≈ 1.16037  →  guarantee NOT beneficial (correct)")
    print("  Guarantor RW pre-fix ≈ 0.61887  →  guarantee wrongly applied (bug)")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1160_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
