"""
Generate P1.159 fixtures: PSM correlation re-derivation uses guarantor's class, not borrower's.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/guarantee.py)

Key responsibilities:
- Produce one borrower counterparty: corporate, GB, large-corp (no annual_revenue),
  is_financial_sector_entity=True, apply_fi_scalar=True (Art. 153(2) FI scalar).
- Produce one guarantor counterparty: institution/bank, GB, is_financial_sector_entity=True,
  apply_fi_scalar=False (regulated bank — NOT subject to FI scalar on its own exposure).
- Produce one facility row for the corporate borrower: senior, M=2.5y, EAD=1,000,000 GBP.
- Produce one loan row: LN_P1159, draws the full facility.
- Produce one guarantee row: GTEE_P1159, bank guarantor covering 60% of facility,
  senior, original_maturity_years=5.0 (no maturity mismatch).
- Produce two internal rating rows: borrower PD=0.0150, guarantor PD=0.0010.
- Produce two model-permission rows: F-IRB for CORPORATE (borrower path), F-IRB for
  INSTITUTION (guarantor PSM path).

Scenario design:
    This fixture exercises Art. 236(1)(a)(i) — the PSM correlation formula must be
    derived from the **guarantor's** exposure class (INSTITUTION, R=0.12-0.24),
    NOT from the borrower's corporate context (R=0.12-0.24 + FI scalar 1.25x).

    The discriminating element is the FI scalar:
    - Borrower (corporate, FSE, apply_fi_scalar=True):
        correlation = standard_corporate_R * 1.25  (Art. 153(2))
    - Guarantor (institution, apply_fi_scalar=False):
        correlation = institution_R (Art. 153(1), no multiplier)

    If the engine incorrectly uses the borrower's class for the PSM correlation:
        - It would apply the FI scalar 1.25x to the guarantor's RW calculation.
    If the engine correctly uses the guarantor's class:
        - It applies the plain institution correlation (no FI scalar).
    This produces materially different RWA for the covered 60% portion.

    Borrower (CORPORATE, F-IRB, FSE, FI scalar applies):
        exposure_class: CORPORATE
        PD_borrower = 0.0150 (1.50%), above B31 corporate floor 0.0005 — no floor needed
        F-IRB supervisory LGD (senior, FSE) = 0.45 (Art. 161(1)(a))
        apply_fi_scalar = True → R * 1.25 on borrower's own calculation
        EAD = 1,000,000 GBP, M = 2.5y

    Guarantor (INSTITUTION, F-IRB, regulated bank, NO FI scalar):
        exposure_class: INSTITUTION (entity_type="institution")
        PD_guarantor = 0.0010 (0.10%), above B31 institution PD floor 0.0005
        F-IRB supervisory LGD (senior, non-FSE) = 0.40 (Art. 161(1)(aa) B31)
        apply_fi_scalar = False → plain institution correlation R=0.12-0.24
        NO FI scalar on guarantor's class

    Guarantee:
        amount_covered = 600,000 GBP (60% of EAD — partial, keeps both portions live)
        guarantor_seniority = "senior"
        original_maturity_years = 5.0 (>= M=2.5, no maturity mismatch)

Expected intermediate values (for test assertions):
    Corporate correlation at PD=0.015 (borrower's OWN calculation):
        R_corp_raw = 0.12*(1-exp(-50*0.015))/(1-exp(-50)) + 0.24*(1-(1-exp(-50*0.015))/(1-exp(-50)))
        R_corp_fi  = R_corp_raw * 1.25   (FI scalar for borrower)

    Institution correlation at PD=0.001 (guarantor's PSM calculation):
        R_inst_raw = 0.12*(1-exp(-50*0.001))/(1-exp(-50)) + 0.24*(1-(1-exp(-50*0.001))/(1-exp(-50)))
        R_inst     = R_inst_raw            (NO FI scalar — guarantor is regulated bank)

    The test should assert that the PSM guarantor RW uses R_inst (NOT R_corp_fi).
    If a bugged engine reads borrower context, it would produce R_inst_bugged = R_inst_raw * 1.25
    which is materially higher than the correct R_inst.

References:
    - PRA PS1/26 Art. 236(1)(a)(i): PSM substitutes guarantor PD/LGD/correlation.
    - PRA PS1/26 Art. 153(1): Institution correlation R=0.12 to 0.24 (same formula as corporate).
    - PRA PS1/26 Art. 153(2): FI scalar 1.25x applies to unregulated/large FSEs on the
      borrower's own exposure — does NOT transfer to guarantor row under PSM.
    - PRA PS1/26 Art. 161(1)(aa): B31 F-IRB supervisory LGD 40% (senior, non-FSE).
    - PRA PS1/26 Art. 163(1): Institution PD floor 0.05% (same as corporate).
    - Code: src/rwa_calc/engine/irb/guarantee.py — PSM correlation path.

Usage:
    uv run python tests/fixtures/p1_159/p1_159.py
"""

from __future__ import annotations

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
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references
BORROWER_REF = "CP_P1159_BORROWER"
GUARANTOR_REF = "CP_P1159_GUARANTOR"

# Exposure references
FACILITY_REF = "FAC_P1159"
LOAN_REF = "LN_P1159"

# Guarantee reference
GUARANTEE_REF = "GTEE_P1159"

# Rating references
RTG_BORROWER_REF = "RTG_P1159_BORR"
RTG_GUARANTOR_REF = "RTG_P1159_GTR"

# Model IDs — one per exposure class to make the PSM routing unambiguous
MODEL_ID_CORP_FIRB = "CORP_FIRB_P1159"  # F-IRB for CORPORATE (borrower)
MODEL_ID_INST_FIRB = "INST_FIRB_P1159"  # F-IRB for INSTITUTION (guarantor PSM path)

# Dates (reporting_date = 2027-06-30 as specified in proposal)
REPORTING_DATE = date(2027, 6, 30)
MATURITY_DATE = date(2029, 12, 30)  # ~2.5y from reporting date → effective_maturity ≈ 2.5
GUARANTEE_MATURITY_DATE = date(2032, 12, 30)  # 5y+ from reporting date → no maturity mismatch
RATING_DATE = date(2027, 1, 2)

# Borrower IRB inputs (corporate, F-IRB, FSE)
# PD=0.0150 (1.5%) — well above B31 corporate floor 0.0005 (0.05%). No floor needed.
# apply_fi_scalar=True: the FI scalar applies to the borrower's OWN corporate RW.
PD_BORROWER = 0.0150  # 1.5% corporate borrower PD

# Guarantor IRB inputs (institution, F-IRB, regulated bank, NO FI scalar)
# PD=0.0010 (0.10%) — above B31 institution floor 0.0005 (0.05%). No floor needed.
# apply_fi_scalar=False: regulated bank → Art. 153(2) FI scalar does NOT apply.
PD_GUARANTOR = 0.0010  # 0.10% institution guarantor PD

# Exposure amounts
EAD_AMOUNT = 1_000_000.0  # GBP 1,000,000 — loan drawn amount and facility limit
AMOUNT_COVERED = 600_000.0  # GBP 600,000 (60% partial — keeps both portions non-zero)
PERCENTAGE_COVERED = 0.60
ORIGINAL_MATURITY_YEARS = 5.0  # >= M=2.5 → no maturity mismatch (Art. 237(2)(a))
EFFECTIVE_MATURITY = 2.5  # M = 2.5y (set explicitly to avoid date-rounding ambiguity)


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """Counterparty row for P1.159."""

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
class _Facility:
    """
    Facility row for P1.159.

    Senior corporate credit line, M=2.5y, limit=1,000,000 GBP.
    effective_maturity=2.5 is set explicitly to avoid date arithmetic ambiguity.
    """

    facility_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    limit: float
    committed: bool
    seniority: str
    effective_maturity: float

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "product_type": self.product_type,
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "limit": self.limit,
            "committed": self.committed,
            "seniority": self.seniority,
            "effective_maturity": self.effective_maturity,
        }


@dataclass(frozen=True)
class _Loan:
    """Loan row for P1.159 — draws the full facility."""

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
    Guarantee row for P1.159.

    Partial senior bank guarantee covering 60% of the corporate facility.
    The guarantor_seniority="senior" drives F-IRB supervisory LGD to 40% (B31,
    Art. 161(1)(aa) — institution guarantor, non-FSE-scalar path).
    beneficiary_type="facility" links to FAC_P1159 so the engine resolves EAD
    from the facility-level.
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
    """Rating row for P1.159."""

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
    """Model permission row for P1.159."""

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


def create_p1159_counterparties() -> pl.DataFrame:
    """
    Return all P1.159 counterparties as a DataFrame.

    Two rows:
    - Borrower: corporate, GB, large-corp (annual_revenue=None — treated conservatively as
      large corporate above the 440m threshold), is_financial_sector_entity=True,
      apply_fi_scalar=True. The FI scalar (Art. 153(2)) applies to the borrower's OWN
      corporate correlation — it must NOT propagate into the PSM guarantor RW calculation.
    - Guarantor: institution (regulated bank), GB, is_financial_sector_entity=True,
      apply_fi_scalar=False. A regulated bank is subject to F-IRB-only restriction
      (Art. 147A) but is NOT subject to the Art. 153(2) FI scalar on its own
      institution exposure. The guarantor row has apply_fi_scalar=False so the engine
      can distinguish it from the borrower's cross-class PSM context.
    """
    rows = [
        _Counterparty(
            counterparty_reference=BORROWER_REF,
            counterparty_name="P1.159 Corporate Borrower FSE PLC",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=None,  # Null → engine treats as large-corp (conservative)
            total_assets=None,
            default_status=False,
            apply_fi_scalar=True,  # Art. 153(2): FI scalar applies to borrower's own RW
            is_managed_as_retail=False,
            is_financial_sector_entity=True,
        ),
        _Counterparty(
            counterparty_reference=GUARANTOR_REF,
            counterparty_name="P1.159 Bank Guarantor Institution GB",
            entity_type="institution",  # → IRB: INSTITUTION class (no FI scalar)
            country_code="GB",
            annual_revenue=None,  # Institutions don't have revenue-based turnover test
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,  # Regulated bank: FI scalar does NOT apply (Art. 153(2))
            is_managed_as_retail=False,
            is_financial_sector_entity=True,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1159_facilities() -> pl.DataFrame:
    """
    Return the P1.159 borrower facility as a DataFrame.

    One row — senior corporate term facility:
    - effective_maturity=2.5: M=2.5y avoids date-arithmetic edge cases and is
      load-bearing for maturity adjustment (MA) in both the borrower's corporate
      RW and the guarantor's institution PSM RW.
    - seniority="senior": F-IRB supervisory LGD of 45% (corporate FSE borrower,
      Art. 161(1)(a)) for the uncovered 40% borrower portion.
    """
    facility = _Facility(
        facility_reference=FACILITY_REF,
        product_type="TERM_LOAN",
        book_code="CORP_LENDING",
        counterparty_reference=BORROWER_REF,
        value_date=REPORTING_DATE,
        maturity_date=MATURITY_DATE,
        currency="GBP",
        limit=EAD_AMOUNT,
        committed=True,
        seniority="senior",
        effective_maturity=EFFECTIVE_MATURITY,
    )
    return pl.DataFrame([facility.to_dict()], schema=dtypes_of(FACILITY_SCHEMA))


def create_p1159_loans() -> pl.DataFrame:
    """
    Return the P1.159 loan as a DataFrame.

    One row — drawn term loan against FAC_P1159:
    - drawn_amount=1,000,000: fully drawn, EAD = drawn_amount.
    - seniority="senior": matches facility seniority.
    - effective_maturity=2.5: consistent with facility.
    - counterparty_reference=CP_P1159_BORROWER: borrower is the corporate FSE.
    """
    loan = _Loan(
        loan_reference=LOAN_REF,
        product_type="TERM_LOAN",
        book_code="CORP_LENDING",
        counterparty_reference=BORROWER_REF,
        value_date=REPORTING_DATE,
        maturity_date=MATURITY_DATE,
        currency="GBP",
        drawn_amount=EAD_AMOUNT,
        interest=0.0,
        seniority="senior",
        effective_maturity=EFFECTIVE_MATURITY,
    )
    return pl.DataFrame([loan.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p1159_guarantees() -> pl.DataFrame:
    """
    Return the P1.159 guarantee as a DataFrame.

    One row — partial senior bank guarantee covering 60% of the corporate facility:
    - guarantor=CP_P1159_GUARANTOR: institution (regulated bank), apply_fi_scalar=False.
    - amount_covered=600,000 GBP (60%): partial coverage keeps both the covered
      (institution-class PSM RW) and uncovered (corporate-class borrower RW) portions
      non-zero, making the PSM path exercised with a material EAD split.
    - guarantor_seniority="senior": routes to F-IRB supervisory LGD 40% under B31
      (Art. 161(1)(aa) — senior, non-FSE-scalar institution guarantor).
    - original_maturity_years=5.0: > M=2.5 → satisfies Art. 237(2)(a) eligibility.
    - maturity_date=2032-12-30: well beyond facility maturity → no maturity mismatch.
    - beneficiary_type="facility": links guarantee to FAC_P1159 facility level.
    """
    guarantee = _Guarantee(
        guarantee_reference=GUARANTEE_REF,
        guarantee_type="bank_guarantee",
        guarantor=GUARANTOR_REF,
        currency="GBP",
        maturity_date=GUARANTEE_MATURITY_DATE,
        amount_covered=AMOUNT_COVERED,
        percentage_covered=PERCENTAGE_COVERED,
        beneficiary_type="facility",
        beneficiary_reference=FACILITY_REF,
        protection_type="guarantee",
        includes_restructuring=True,
        original_maturity_years=ORIGINAL_MATURITY_YEARS,
        guarantor_seniority="senior",
    )
    schema_dtypes = dtypes_of(GUARANTEE_SCHEMA)
    return pl.DataFrame([guarantee.to_dict()], schema=schema_dtypes)


def create_p1159_ratings() -> pl.DataFrame:
    """
    Return all P1.159 internal ratings as a DataFrame.

    Two rows:
    - Borrower: PD=0.0150 (1.5%), CQS=3, model_id=CORP_FIRB_P1159.
      PD is well above B31 corporate floor 0.0005 — no floor effect, isolating
      the FI-scalar / class-routing as the discriminating test.
    - Guarantor: PD=0.0010 (0.10%), CQS=1, model_id=INST_FIRB_P1159.
      PD is above B31 institution floor 0.0005 — no floor effect.
      The institution guarantor's low PD produces a materially lower RW
      than the borrower's corporate curve, making the PSM benefit visible.
    """
    rows = [
        _Rating(
            rating_reference=RTG_BORROWER_REF,
            counterparty_reference=BORROWER_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="3A",  # ~1.5% PD band — investment grade corporate
            cqs=3,
            pd=PD_BORROWER,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID_CORP_FIRB,
        ),
        _Rating(
            rating_reference=RTG_GUARANTOR_REF,
            counterparty_reference=GUARANTOR_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="1A",  # ~0.10% PD band — high-quality institution
            cqs=1,
            pd=PD_GUARANTOR,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID_INST_FIRB,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1159_model_permissions() -> pl.DataFrame:
    """
    Return all P1.159 model permissions as a DataFrame.

    Two rows (one per exposure class, one model_id each):
    - CORP_FIRB_P1159: foundation_irb for 'corporate' (borrower's own exposure class).
    - INST_FIRB_P1159: foundation_irb for 'institution' (guarantor's class in PSM).

    Separate model_ids ensure the engine can cleanly resolve:
    - The borrower's corporate FIRB parameters (with FI scalar from counterparty flag).
    - The guarantor's institution FIRB parameters (no FI scalar).

    Under Basel 3.1, institutions are restricted to F-IRB (Art. 147A) so
    foundation_irb is the only valid approach for INST_FIRB_P1159.
    """
    rows = [
        _ModelPermission(
            model_id=MODEL_ID_CORP_FIRB,
            exposure_class="corporate",
            approach="foundation_irb",
            country_codes="GB",
            excluded_book_codes=None,
        ),
        _ModelPermission(
            model_id=MODEL_ID_INST_FIRB,
            exposure_class="institution",
            approach="foundation_irb",
            country_codes="GB",
            excluded_book_codes=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1159_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.159 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to this package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    artefacts = [
        ("counterparty", create_p1159_counterparties()),
        ("facility", create_p1159_facilities()),
        ("loan", create_p1159_loans()),
        ("guarantee", create_p1159_guarantees()),
        ("rating", create_p1159_ratings()),
        ("model_permission", create_p1159_model_permissions()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.159 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: PSM correlation re-derivation reads guarantor class (Art. 236(1)(a)(i))")
    print("  Borrower:  corporate FSE, apply_fi_scalar=True,  PD=0.0150, EAD=1,000,000 GBP")
    print("  Guarantor: institution,   apply_fi_scalar=False, PD=0.0010")
    print("  Guarantee: 60% covered (GBP 600,000), senior, original_maturity=5.0y")
    print(f"  PD_borrower         = {PD_BORROWER}")
    print(f"  PD_guarantor        = {PD_GUARANTOR}")
    print("  Borrower FI scalar  = 1.25x (applies to borrower's OWN corporate RW)")
    print("  Guarantor FI scalar = none  (regulated bank, apply_fi_scalar=False)")
    print("  PSM should use: institution correlation (no FI scalar) for covered 60%")
    print("  Bug: engine uses borrower class → applies FI scalar 1.25x (materially wrong)")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1159_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
