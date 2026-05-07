"""
Generate P1.157 fixtures: PSM "no better than direct" PD floor (Art. 160(4)).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/guarantee.py)

Key responsibilities:
- Produce one borrower counterparty: individual QRRE-transactor, GB.
- Produce one guarantor counterparty: large corporate, non-FSE, GB,
  annual_revenue=750,000,000 (above B31 large-corp 440m threshold intentionally
  but does not affect PSM routing — PSM uses F-IRB corporate formula regardless).
- Produce one facility row for the borrower: RETAIL_QRRE, is_qrre_transactor=True,
  lgd=0.50, effective_maturity=2.5, ead=1,000,000, currency=GBP.
  (Facility is used because FACILITY_SCHEMA carries is_qrre_transactor; the
  hierarchy resolver propagates the flag to any linked loan rows.)
- Produce one guarantee row: GTE_P1157, covers 600,000 GBP (60%), senior,
  protection_type="guarantee", guarantor_seniority="senior",
  original_maturity_years=5.0.
- Produce one rating row for the borrower: PD=0.0050, model_id=RTL_AIRB_P1157.
- Produce one rating row for the guarantor: PD=0.0004 — intentionally below the
  Basel 3.1 corporate PD floor of 0.0005 (0.05%) so the engine must floor it to
  0.0005 to satisfy the "no better than direct" constraint.
- Produce model permission rows: AIRB for retail_qrre (borrower), FIRB for
  corporate (guarantor PSM path).

Scenario design:
    The "no better than direct" floor (Art. 160(4)) requires that when PSM
    substitutes the guarantor's PD for the guaranteed portion, the guarantor's
    PD is floored at the PD floor applicable to the guarantor's exposure class
    as a direct borrower — not the borrower's class floor.

    Guarantor PD = 0.0004 (0.04%) is below the Basel 3.1 corporate PD floor
    of 0.0005 (0.05%) per Art. 163(1)(a). The engine must therefore use
    PD_guarantor_floored = 0.0005 when computing the PSM risk weight for the
    guaranteed portion.

    Borrower (QRRE transactor):
        exposure_class: RETAIL_QRRE, is_qrre_transactor=True
        PD_borrower = 0.0050, LGD_borrower = 0.50
        EAD = 1,000,000 GBP, M = 2.5y

    Guarantor (corporate, F-IRB via PSM):
        PD_guarantor_raw   = 0.0004  (below corporate B31 floor 0.0005)
        PD_guarantor_floored = 0.0005  (floor applied per Art. 160(4))
        F-IRB supervisory LGD (senior, non-FSE, B31) = 0.40 (Art. 161(1)(aa))

    Guarantee:
        amount_covered = 600,000 GBP (60% of EAD)
        guarantor_seniority = "senior"

Expected intermediate (floored guarantor PD):
    PD_guarantor_floored = max(0.0004, 0.0005) = 0.0005

References:
    - CRR Art. 160(4): PSM "no better than direct" PD floor.
    - PRA PS1/26 Art. 163(1)(a): Corporate PD floor 0.05%.
    - PRA PS1/26 Art. 163(1)(c): QRRE transactor PD floor 0.05%.
    - CRE22.70-85: Parameter substitution method.
    - CRR Art. 161(1)(aa): B31 F-IRB supervisory LGD 40% (senior, non-FSE corp).
    - Bug site: src/rwa_calc/engine/irb/guarantee.py line 333.

Usage:
    uv run python tests/fixtures/p1_157/p1_157.py
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
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references
BORROWER_REF = "CPTY_BORROWER_QRRE_TXN_P1157"
GUARANTOR_REF = "GTR_CORP_NONFSE_P1157"

# Exposure reference (facility — carries is_qrre_transactor)
FACILITY_REF = "FAC_QRRE_TXN_P1157"

# Guarantee reference
GUARANTEE_REF = "GTE_P1157"

# Rating references
RTG_BORROWER_REF = "RTG_P1157_BORR"
RTG_GUARANTOR_REF = "RTG_P1157_GTR"

# Model IDs
MODEL_ID_RETAIL_AIRB = "RTL_AIRB_P1157"   # AIRB for retail_qrre (borrower)
MODEL_ID_CORP_FIRB = "CORP_FIRB_P1157"    # FIRB for corporate (guarantor PSM path)

# Dates
VALUE_DATE = date(2026, 1, 1)
# Facility maturity ~2.5 years from VALUE_DATE → effective_maturity=2.5
MATURITY_DATE = date(2028, 7, 1)
GUARANTEE_MATURITY_DATE = date(2031, 1, 1)  # > facility maturity → no maturity mismatch
RATING_DATE = date(2026, 1, 2)

# Borrower IRB inputs (A-IRB retail QRRE-transactor)
PD_BORROWER = 0.0050           # 0.50% own PD
LGD_BORROWER = 0.50            # 50% own LGD (A-IRB unsecured retail QRRE)
EAD_FACILITY = 1_000_000.0     # GBP 1,000,000 facility limit (fully utilised)
EFFECTIVE_MATURITY = 2.5       # M = 2.5y (overrides date-derived M)

# Guarantor IRB inputs (corporate, F-IRB via PSM)
# Raw PD = 0.0004 is intentionally below the Basel 3.1 corporate PD floor of
# 0.0005 (0.05%, Art. 163(1)(a)).  The engine must floor it to 0.0005 per
# Art. 160(4) "no better than direct" constraint.
PD_GUARANTOR_RAW = 0.0004       # 0.04% — below corporate B31 floor
PD_GUARANTOR_FLOORED = 0.0005   # 0.05% — after Art. 160(4) floor (expected engine output)

# Guarantee coverage
AMOUNT_COVERED = 600_000.0      # GBP 600,000 (60% of EAD)
PERCENTAGE_COVERED = 0.60
ORIGINAL_MATURITY_YEARS = 5.0   # > 1y → satisfies Art. 237(2)(a) eligibility

# Guarantor revenue — above B31 large-corp 440m threshold
# (large-corp restriction applies to A-IRB; PSM is F-IRB and is unrestricted)
GUARANTOR_ANNUAL_REVENUE = 750_000_000.0


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """Counterparty row for P1.157."""

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
    Facility row for P1.157 borrower.

    Uses FACILITY_SCHEMA because is_qrre_transactor lives there.  The hierarchy
    resolver propagates the flag to any child loan rows during pipeline execution.
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
    lgd: float
    beel: float
    is_revolving: bool
    is_qrre_transactor: bool
    seniority: str
    risk_type: str
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
            "lgd": self.lgd,
            "beel": self.beel,
            "is_revolving": self.is_revolving,
            "is_qrre_transactor": self.is_qrre_transactor,
            "seniority": self.seniority,
            "risk_type": self.risk_type,
            "effective_maturity": self.effective_maturity,
        }


@dataclass(frozen=True)
class _Guarantee:
    """
    Guarantee row for P1.157.

    guarantor_seniority is in GUARANTEE_SCHEMA (added by P1.156 engine work).
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
    """Rating row for P1.157."""

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
    """Model permission row for P1.157."""

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


def create_p1157_counterparties() -> pl.DataFrame:
    """
    Return all P1.157 counterparties as a DataFrame.

    Two rows:
    - Borrower: individual QRRE-transactor, GB, no revenue (retail individual).
    - Guarantor: large corporate, non-FSE, GB, annual_revenue=750m (above 440m
      large-corp threshold); is_financial_sector_entity=False so the standard
      non-FSE supervisory LGD applies (Art. 161(1)(aa): 40% B31).
    """
    rows = [
        _Counterparty(
            counterparty_reference=BORROWER_REF,
            counterparty_name="P1.157 QRRE Transactor Borrower",
            entity_type="individual",
            country_code="GB",
            annual_revenue=None,        # Individual — no revenue
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=False,
        ),
        _Counterparty(
            counterparty_reference=GUARANTOR_REF,
            counterparty_name="P1.157 Corporate Guarantor NonFSE PLC",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=GUARANTOR_ANNUAL_REVENUE,   # GBP 750m — above 440m large-corp
            total_assets=1_000_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_financial_sector_entity=False,           # Non-FSE → LGD 40% B31 (Art. 161(1)(aa))
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1157_facilities() -> pl.DataFrame:
    """
    Return the P1.157 borrower facility as a DataFrame.

    One row — a revolving QRRE-transactor credit facility:
    - is_qrre_transactor=True: flags the QRRE transactor sub-class so the
      PD floor expression selects the correct floor (0.05% B31) for the
      borrower's own PD calculation.
    - lgd=0.50: A-IRB unsecured retail QRRE LGD estimate (above the 50% A-IRB
      floor per Art. 164(4) for QRRE — floor is not binding here, floor = EAD).
    - effective_maturity=2.5: overrides date-derived M for unambiguous M=2.5.
    - risk_type="FR": fully revolving — 75% CCF under F-IRB (Art. 166(8)(d)).
    """
    facility = _Facility(
        facility_reference=FACILITY_REF,
        product_type="CREDIT_CARD",
        book_code="RETAIL_CARDS",
        counterparty_reference=BORROWER_REF,
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        currency="GBP",
        limit=EAD_FACILITY,
        committed=True,
        lgd=LGD_BORROWER,
        beel=0.0,
        is_revolving=True,
        is_qrre_transactor=True,        # Transactor sub-class (repays in full each period)
        seniority="senior",
        risk_type="FR",                 # Fully revolving
        effective_maturity=EFFECTIVE_MATURITY,
    )
    return pl.DataFrame([facility.to_dict()], schema=dtypes_of(FACILITY_SCHEMA))


def create_p1157_guarantees() -> pl.DataFrame:
    """
    Return the P1.157 guarantee as a DataFrame.

    One row — senior corporate guarantee covering 60% of the QRRE facility:
    - guarantor_seniority="senior": drives F-IRB supervisory LGD selection in
      PSM to 40% (non-FSE, B31, Art. 161(1)(aa)).
    - original_maturity_years=5.0: satisfies Art. 237(2)(a) (>= 1.0 year).
    - protection_type="guarantee": unfunded credit protection.
    """
    guarantee = _Guarantee(
        guarantee_reference=GUARANTEE_REF,
        guarantee_type="corporate_guarantee",
        guarantor=GUARANTOR_REF,
        currency="GBP",
        maturity_date=GUARANTEE_MATURITY_DATE,  # > facility maturity — no maturity mismatch
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
    records = [guarantee.to_dict()]
    return pl.DataFrame(records, schema=schema_dtypes)


def create_p1157_ratings() -> pl.DataFrame:
    """
    Return all P1.157 internal ratings as a DataFrame.

    Two rows:
    - Borrower: PD=0.0050 (above QRRE transactor B31 floor 0.0005), model_id=RTL_AIRB_P1157.
    - Guarantor: PD=0.0004 (BELOW corporate B31 floor 0.0005 — floor must bind in
      engine via Art. 160(4) "no better than direct" check), model_id=CORP_FIRB_P1157.
    """
    rows = [
        _Rating(
            rating_reference=RTG_BORROWER_REF,
            counterparty_reference=BORROWER_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="3B",       # Indicative QRRE band (PD ~0.50%)
            cqs=4,
            pd=PD_BORROWER,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID_RETAIL_AIRB,
        ),
        _Rating(
            rating_reference=RTG_GUARANTOR_REF,
            counterparty_reference=GUARANTOR_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="1A",       # High-quality corporate (PD ~0.04% raw)
            cqs=2,
            pd=PD_GUARANTOR_RAW,    # 0.0004 — below B31 corporate floor 0.0005
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID_CORP_FIRB,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1157_model_permissions() -> pl.DataFrame:
    """
    Return the P1.157 model permissions as a DataFrame.

    Two rows:
    - RTL_AIRB_P1157: advanced_irb for retail_qrre (borrower A-IRB).
    - CORP_FIRB_P1157: foundation_irb for corporate (guarantor PSM path — F-IRB
      supervisory LGDs apply to PSM regardless of borrower's A-IRB permission).
    """
    rows = [
        _ModelPermission(
            model_id=MODEL_ID_RETAIL_AIRB,
            exposure_class="retail_qrre",
            approach="advanced_irb",
            country_codes="GB",
            excluded_book_codes=None,
        ),
        _ModelPermission(
            model_id=MODEL_ID_CORP_FIRB,
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


def save_p1157_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.157 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to this package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    artefacts = [
        ("counterparty", create_p1157_counterparties()),
        ("facility", create_p1157_facilities()),
        ("guarantee", create_p1157_guarantees()),
        ("rating", create_p1157_ratings()),
        ("model_permission", create_p1157_model_permissions()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.157 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: PSM 'no better than direct' PD floor (Art. 160(4))")
    print("  Borrower:  QRRE transactor A-IRB, PD=0.0050, LGD=0.50, EAD=1,000,000 GBP")
    print("  Guarantor: corporate non-FSE F-IRB, PD_raw=0.0004 (below B31 floor 0.0005)")
    print("  Guarantee: 60% covered (GBP 600,000), senior, original_maturity=5.0y")
    print(f"  PD_guarantor_raw    = {PD_GUARANTOR_RAW}")
    print(f"  PD_guarantor_floored = {PD_GUARANTOR_FLOORED}  (Art. 160(4) floor binds)")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1157_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
