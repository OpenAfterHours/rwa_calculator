"""
Generate P1.156 fixtures: PSM guarantor LGD seniority/FSE-aware per Art. 236/161.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/psm.py)

Key responsibilities:
- Produce one borrower counterparty: corporate, GB, annual_revenue=200,000,000,
  is_financial_sector_entity=False.
- Produce three guarantor counterparties covering the three sub-cases:
    (a) GUAR-SR-NONFSE-001 : senior + non-FSE  (corporate, GB, is_fse=False)
    (b) GUAR-SR-FSE-001    : senior + FSE       (corporate, GB, is_fse=True)
    (c) GUAR-SUB-001       : subordinated + non-FSE (corporate, GB, is_fse=False)
- Produce three loan rows (one per sub-case) so there is no guarantee
  duplicate-aggregation ambiguity: LOAN-P1156-A, LOAN-P1156-B, LOAN-P1156-C.
- Produce three guarantee rows linking each loan to its guarantor, each with
  `guarantor_seniority` set to "senior" or "subordinated" as appropriate.
  NOTE: `guarantor_seniority` is a NEW column not yet in GUARANTEE_SCHEMA;
  it is written here as an extra column and polars write_parquet accepts it.
  The engine-implementer will add it to GUARANTEE_SCHEMA.
- Produce one internal rating row per counterparty (borrower + three guarantors).
- Produce one model-permission row granting both FIRB and AIRB for corporate
  under model_id M_CORP_FIRB.

Scenario design (three sub-cases):
    (a) senior + non-FSE guarantor:
        Art. 236(2) routes to Art. 161(1)(a): supervisory LGD 45% (F-IRB senior).
    (b) senior + FSE guarantor:
        Art. 236(2) routes to Art. 161(1)(a) but FSE scalar applies (Art. 153(4)):
        supervisory LGD 45% AND correlation multiplier 1.25 for guarantor-driven RW.
    (c) subordinated + non-FSE guarantor:
        Art. 236(2) routes to Art. 161(1)(b): supervisory LGD 75% (F-IRB subordinated).

Expected outputs (authoritative, for acceptance test assertions):
    Sub-case (a): guarantor LGD = 0.45  (Art. 161(1)(a) F-IRB senior unsecured)
    Sub-case (b): guarantor LGD = 0.45  (Art. 161(1)(a) F-IRB senior unsecured)
                  FSE correlation multiplier = 1.25 on substituted exposure
    Sub-case (c): guarantor LGD = 0.75  (Art. 161(1)(b) F-IRB subordinated)

Borrower inputs (all three loans):
    PD_borrower = 0.02  LGD_borrower = 0.40  EAD = 1,000,000 GBP  M = 2.5y

Guarantor inputs:
    PD_guarantor = 0.005  (all three guarantors)
    F-IRB LGD applied by engine per seniority (guarantor_seniority field)

References:
    - CRR Art. 236: substitution approach for guarantees under IRB.
    - CRR Art. 161(1)(a): F-IRB supervisory LGD 45% (senior unsecured).
    - CRR Art. 161(1)(b): F-IRB supervisory LGD 75% (subordinated unsecured).
    - CRR Art. 153(4): FSE correlation multiplier 1.25.
    - PRA PS1/26 App. 1: UK Basel 3.1 alignment — same Art. references retained.

Usage:
    uv run python tests/fixtures/p1_156/p1_156.py
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

# Borrower
BORROWER_REF = "BORR-001"

# Guarantors (one per sub-case)
GUAR_SR_NONFSE_REF = "GUAR-SR-NONFSE-001"  # sub-case (a): senior + non-FSE
GUAR_SR_FSE_REF = "GUAR-SR-FSE-001"  # sub-case (b): senior + FSE
GUAR_SUB_REF = "GUAR-SUB-001"  # sub-case (c): subordinated

# Loans (one per sub-case to avoid duplicate-aggregation issues)
LOAN_A_REF = "LOAN-P1156-A"  # sub-case (a): senior + non-FSE guarantor
LOAN_B_REF = "LOAN-P1156-B"  # sub-case (b): senior + FSE guarantor
LOAN_C_REF = "LOAN-P1156-C"  # sub-case (c): subordinated guarantor

# Guarantee references
GUAR_A_REF = "GUAR-P1156-A"
GUAR_B_REF = "GUAR-P1156-B"
GUAR_C_REF = "GUAR-P1156-C"

# Rating references
RTG_BORROWER_REF = "RTG-P1156-BORR"
RTG_SR_NONFSE_REF = "RTG-P1156-SR-NONFSE"
RTG_SR_FSE_REF = "RTG-P1156-SR-FSE"
RTG_SUB_REF = "RTG-P1156-SUB"

# Model permission
MODEL_ID = "M_CORP_FIRB"

# Dates
VALUE_DATE = date(2026, 1, 1)
MATURITY_DATE = date(2028, 7, 1)  # ~2.5 years from VALUE_DATE → effective_maturity=2.5
RATING_DATE = date(2026, 1, 2)

# Borrower IRB inputs
PD_BORROWER = 0.02  # 2% own PD
LGD_BORROWER = 0.40  # 40% own LGD (A-IRB estimate for borrower)
DRAWN_AMOUNT = 1_000_000.0
EFFECTIVE_MATURITY = 2.5

# Guarantor IRB inputs (same for all three; seniority drives F-IRB LGD via engine)
PD_GUARANTOR = 0.005  # 0.5% own PD (better credit than borrower)

# Expected guarantor LGD outputs (for acceptance test assertions)
EXPECTED_LGD_SENIOR = 0.45  # Art. 161(1)(a): F-IRB senior unsecured
EXPECTED_LGD_SUBORDINATED = 0.75  # Art. 161(1)(b): F-IRB subordinated unsecured
EXPECTED_FSE_MULTIPLIER = 1.25  # Art. 153(4): FSE correlation multiplier


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """A counterparty row for P1.156."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float
    total_assets: float
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool
    is_financial_sector_entity: bool

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
        }


@dataclass(frozen=True)
class _Loan:
    """A loan row for P1.156."""

    loan_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    drawn_amount: float
    interest: float
    lgd: float
    beel: float
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
            "lgd": self.lgd,
            "beel": self.beel,
            "seniority": self.seniority,
            "effective_maturity": self.effective_maturity,
        }


@dataclass(frozen=True)
class _Guarantee:
    """
    A guarantee row for P1.156.

    `guarantor_seniority` is a NEW column (not yet in GUARANTEE_SCHEMA).
    It is written here as an extra column; polars write_parquet accepts
    extra columns without error.  The engine-implementer will add it to
    GUARANTEE_SCHEMA as part of the P1.156 engine implementation.
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
    # NEW field — engine-implementer adds to GUARANTEE_SCHEMA
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
            "guarantor_seniority": self.guarantor_seniority,
        }


@dataclass(frozen=True)
class _Rating:
    """An internal rating row for P1.156."""

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
    """A model-permission row for P1.156."""

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


def create_p1156_counterparties() -> pl.DataFrame:
    """
    Return all P1.156 counterparties as a DataFrame.

    Four rows: one borrower + three guarantors (one per sub-case).
    annual_revenue=200,000,000 for borrower — below Basel 3.1 440m large-corp
    threshold so standard corporate correlation formula applies.
    FSE flag distinguishes sub-case (b) guarantor from (a) and (c).
    """
    rows = [
        # Borrower — large non-FSE corporate
        _Counterparty(
            counterparty_reference=BORROWER_REF,
            counterparty_name="P1.156 Borrower Corp Ltd",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=200_000_000.0,
            total_assets=300_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
        ),
        # Guarantor (a): senior + non-FSE
        _Counterparty(
            counterparty_reference=GUAR_SR_NONFSE_REF,
            counterparty_name="P1.156 Guarantor Senior NonFSE Ltd",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=500_000_000.0,
            total_assets=800_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
        ),
        # Guarantor (b): senior + FSE — triggers Art. 153(4) correlation multiplier 1.25
        _Counterparty(
            counterparty_reference=GUAR_SR_FSE_REF,
            counterparty_name="P1.156 Guarantor Senior FSE Ltd",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=500_000_000.0,
            total_assets=800_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=True,
        ),
        # Guarantor (c): subordinated — triggers Art. 161(1)(b) LGD 75%
        _Counterparty(
            counterparty_reference=GUAR_SUB_REF,
            counterparty_name="P1.156 Guarantor Subordinated Ltd",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=500_000_000.0,
            total_assets=800_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1156_loans() -> pl.DataFrame:
    """
    Return all P1.156 loans as a DataFrame.

    Three rows — one per sub-case.  All share identical economic inputs so
    any difference in RWA comes purely from the guarantor's seniority/FSE flag.
    seniority="senior" on the loan (borrower-side); guarantor seniority is
    captured on the guarantee row via guarantor_seniority.
    effective_maturity=2.5 → M=2.5 in the IRB formula (M-2.5=0 simplifies MA).
    """
    loan_specs = [
        (LOAN_A_REF, BORROWER_REF),  # sub-case (a)
        (LOAN_B_REF, BORROWER_REF),  # sub-case (b)
        (LOAN_C_REF, BORROWER_REF),  # sub-case (c)
    ]
    rows = [
        _Loan(
            loan_reference=ref,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=cp_ref,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            lgd=LGD_BORROWER,
            beel=0.0,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
        )
        for ref, cp_ref in loan_specs
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1156_guarantees() -> pl.DataFrame:
    """
    Return all P1.156 guarantees as a DataFrame.

    Three rows — one per sub-case.
    `guarantor_seniority` is a NEW column not yet in GUARANTEE_SCHEMA.
    Writing it here as an extra column; polars write_parquet accepts it.

    Sub-case (a) — senior + non-FSE:
        guarantor_seniority = "senior"  → engine applies Art. 161(1)(a) LGD 45%
    Sub-case (b) — senior + FSE:
        guarantor_seniority = "senior"  → engine applies Art. 161(1)(a) LGD 45%
                                          AND Art. 153(4) FSE multiplier 1.25
    Sub-case (c) — subordinated + non-FSE:
        guarantor_seniority = "subordinated" → engine applies Art. 161(1)(b) LGD 75%
    """
    # Build GUARANTEE_SCHEMA columns as a base dict, then add the new field
    rows = [
        _Guarantee(
            guarantee_reference=GUAR_A_REF,
            guarantee_type="corporate_guarantee",
            guarantor=GUAR_SR_NONFSE_REF,
            currency="GBP",
            maturity_date=date(2029, 1, 1),  # > loan maturity 2028-07-01 → no maturity mismatch
            amount_covered=DRAWN_AMOUNT,
            percentage_covered=1.0,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_A_REF,
            protection_type="guarantee",
            includes_restructuring=True,
            guarantor_seniority="senior",
        ),
        _Guarantee(
            guarantee_reference=GUAR_B_REF,
            guarantee_type="corporate_guarantee",
            guarantor=GUAR_SR_FSE_REF,
            currency="GBP",
            maturity_date=date(2029, 1, 1),
            amount_covered=DRAWN_AMOUNT,
            percentage_covered=1.0,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_B_REF,
            protection_type="guarantee",
            includes_restructuring=True,
            guarantor_seniority="senior",
        ),
        _Guarantee(
            guarantee_reference=GUAR_C_REF,
            guarantee_type="corporate_guarantee",
            guarantor=GUAR_SUB_REF,
            currency="GBP",
            maturity_date=date(2029, 1, 1),
            amount_covered=DRAWN_AMOUNT,
            percentage_covered=1.0,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_C_REF,
            protection_type="guarantee",
            includes_restructuring=True,
            guarantor_seniority="subordinated",
        ),
    ]
    # Write with GUARANTEE_SCHEMA base columns first, then append the new column.
    # dtypes_of(GUARANTEE_SCHEMA) produces the canonical schema; `guarantor_seniority`
    # is not yet in it, so we build the DataFrame from plain dicts and cast known
    # columns explicitly.  Polars write_parquet accepts the extra column without error.
    schema_dtypes = dtypes_of(GUARANTEE_SCHEMA)
    records = [r.to_dict() for r in rows]
    # Build DataFrame: cast the known schema columns, leave guarantor_seniority as Utf8.
    df = pl.DataFrame(records, schema={**schema_dtypes, "guarantor_seniority": pl.String})
    return df


def create_p1156_ratings() -> pl.DataFrame:
    """
    Return all P1.156 internal ratings as a DataFrame.

    Four rows: borrower (pd=0.02) + three guarantors (pd=0.005 each).
    All linked to model_id=M_CORP_FIRB.
    """
    rows = [
        _Rating(
            rating_reference=RTG_BORROWER_REF,
            counterparty_reference=BORROWER_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="2B",
            cqs=4,
            pd=PD_BORROWER,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,
        ),
        _Rating(
            rating_reference=RTG_SR_NONFSE_REF,
            counterparty_reference=GUAR_SR_NONFSE_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="3A",
            cqs=3,
            pd=PD_GUARANTOR,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,
        ),
        _Rating(
            rating_reference=RTG_SR_FSE_REF,
            counterparty_reference=GUAR_SR_FSE_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="3A",
            cqs=3,
            pd=PD_GUARANTOR,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,
        ),
        _Rating(
            rating_reference=RTG_SUB_REF,
            counterparty_reference=GUAR_SUB_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="3A",
            cqs=3,
            pd=PD_GUARANTOR,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1156_model_permission() -> pl.DataFrame:
    """
    Return the P1.156 model permission as a DataFrame.

    M_CORP_FIRB grants both foundation_irb and advanced_irb for the corporate
    exposure class, no geo or book restrictions.  A single model_id covers all
    four counterparties (borrower + three guarantors) in this scenario.

    Two rows: one for foundation_irb (F-IRB) and one for advanced_irb (A-IRB),
    reflecting the proposal's requirement that the model grants both approaches.
    """
    rows = [
        _ModelPermission(
            model_id=MODEL_ID,
            exposure_class="corporate",
            approach="foundation_irb",
            country_codes=None,
            excluded_book_codes=None,
        ),
        _ModelPermission(
            model_id=MODEL_ID,
            exposure_class="corporate",
            approach="advanced_irb",
            country_codes=None,
            excluded_book_codes=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1156_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.156 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to this package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1156_counterparties()),
        ("loan", create_p1156_loans()),
        ("guarantee", create_p1156_guarantees()),
        ("rating", create_p1156_ratings()),
        ("model_permission", create_p1156_model_permission()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.156 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: PSM guarantor LGD seniority/FSE-aware (Art. 236/161)")
    print("  Sub-case (a): senior + non-FSE  → guarantor LGD 45% (Art. 161(1)(a))")
    print("  Sub-case (b): senior + FSE      → guarantor LGD 45% + FSE mult 1.25")
    print("  Sub-case (c): subordinated      → guarantor LGD 75% (Art. 161(1)(b))")
    print(f"  Expected senior LGD:     {EXPECTED_LGD_SENIOR}")
    print(f"  Expected sub. LGD:       {EXPECTED_LGD_SUBORDINATED}")
    print(f"  Expected FSE multiplier: {EXPECTED_FSE_MULTIPLIER}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1156_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
