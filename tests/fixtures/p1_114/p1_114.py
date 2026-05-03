"""
Generate P1.114 fixtures: null-propagation defect in model permissions book-code filter.

Pipeline position:
    fixture-builder output → test-writer → engine-implementer (classifier.py fix)

Key responsibilities:
- Produce one counterparty row with country_code=null (no geographic scoping needed).
- Produce one facility row and one loan row, both with book_code=null.
- Produce one facility-mapping row linking the facility to the loan.
- Produce one rating row with internal PD=0.01 and model_id="UK_CORP_PD_01".
- Produce one model-permissions row: country_codes=null, excluded_book_codes="TRADE_FINANCE".

Defect under test (pre-fix):
    In classifier.py the book_not_excluded predicate is evaluated as:
        pl.col("book_code").is_in(excluded_list)  →  null when book_code is null
    A null boolean AND-ed with other conditions yields null, so permission_valid=null
    and the exposure silently falls through to SA instead of FIRB.

Post-fix assertion:
    book_code=null is *not* in {"TRADE_FINANCE"}, therefore book_not_excluded=True,
    permission_valid=True, and approach="foundation_irb".

Optional FIRB RWA (CRR Art. 153(1), Art. 161(1)(a)):
    PD=0.01, LGD=0.45, M≈3.0 years
    R = 0.12 × (1 − exp(−50 × 0.01)) / (1 − exp(−50))
      + 0.24 × [1 − (1 − exp(−50 × 0.01)) / (1 − exp(−50))]
      ≈ 0.1928
    MA = (1 + (M − 2.5) × b) / (1 − 1.5 × b)  where b = (0.11852 − 0.05478 × ln(0.01))^2
    K  = (LGD × N((N⁻¹(PD) + √R × N⁻¹(0.999)) / √(1 − R)) − PD × LGD) × MA
    RWA = K × 12.5 × EAD × 1.06  (CRR Art. 153(1) scalar)
    Hand-calc: K≈0.0805, RWA≈1_066_427 on EAD=1_000_000.

References:
    - src/rwa_calc/engine/classifier.py (defect site)
    - CRR Art. 143 (model use scope)
    - CRR Art. 153(1), Art. 161(1)(a) (FIRB risk-weight formula + LGD)
    - tests/fixtures/model_permissions/model_permissions.py (existing pattern)

Usage:
    uv run python tests/fixtures/p1_114/p1_114.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "CP_NULL_GEO_001"
FACILITY_REF = "FAC_NULL_BOOK_001"
LOAN_REF = "LN_NULL_BOOK_001"
MODEL_ID = "UK_CORP_PD_01"
VALUE_DATE = date(2024, 1, 1)
MATURITY_DATE = date(2027, 1, 1)


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """Minimal counterparty for P1.114: null country_code, large corporate."""

    counterparty_reference: str
    entity_type: str
    country_code: str | None  # null — no geographic scoping
    annual_revenue: float
    total_assets: float
    default_status: bool
    apply_fi_scalar: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "annual_revenue": self.annual_revenue,
            "total_assets": self.total_assets,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
        }


@dataclass(frozen=True)
class _Facility:
    """
    Minimal facility for P1.114: null book_code.

    book_code=null is intentional — it must NOT match the "TRADE_FINANCE" exclusion.
    The schema declares book_code as optional (required=False), so null is valid.
    """

    facility_reference: str
    counterparty_reference: str
    book_code: str | None  # null — exercises the null-propagation defect path
    currency: str
    limit: float
    committed: bool
    seniority: str
    risk_type: str
    is_obs_commitment: bool
    value_date: date
    maturity_date: date

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "counterparty_reference": self.counterparty_reference,
            "book_code": self.book_code,
            "currency": self.currency,
            "limit": self.limit,
            "committed": self.committed,
            "seniority": self.seniority,
            "risk_type": self.risk_type,
            "is_obs_commitment": self.is_obs_commitment,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
        }


@dataclass(frozen=True)
class _Loan:
    """
    Minimal loan for P1.114: null book_code.

    book_code=null mirrors the facility — both are null, ensuring the defect is
    exercised regardless of which object the classifier resolves book_code from.
    """

    loan_reference: str
    counterparty_reference: str
    book_code: str | None  # null — exercises the null-propagation defect path
    currency: str
    drawn_amount: float
    interest: float
    seniority: str
    value_date: date
    maturity_date: date

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "counterparty_reference": self.counterparty_reference,
            "book_code": self.book_code,
            "currency": self.currency,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "seniority": self.seniority,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
        }


@dataclass(frozen=True)
class _FacilityMapping:
    """Maps the P1.114 facility to its loan child."""

    parent_facility_reference: str
    child_reference: str
    child_type: str

    def to_dict(self) -> dict:
        return {
            "parent_facility_reference": self.parent_facility_reference,
            "child_reference": self.child_reference,
            "child_type": self.child_type,
        }


@dataclass(frozen=True)
class _Rating:
    """Internal PD rating for the P1.114 counterparty."""

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    pd: float
    model_id: str
    rating_date: date

    def to_dict(self) -> dict:
        return {
            "rating_reference": self.rating_reference,
            "counterparty_reference": self.counterparty_reference,
            "rating_type": self.rating_type,
            "pd": self.pd,
            "model_id": self.model_id,
            "rating_date": self.rating_date,
        }


@dataclass(frozen=True)
class _ModelPermission:
    """
    P1.114 model permission row.

    country_codes=null  → no geographic restriction (all geographies permitted).
    excluded_book_codes="TRADE_FINANCE" → TRADE_FINANCE book excluded.

    The exposure has book_code=null, which is NOT in {"TRADE_FINANCE"}, so
    post-fix the permission is valid and FIRB is granted.
    """

    model_id: str
    exposure_class: str
    approach: str
    country_codes: str | None  # null — no geo restriction
    excluded_book_codes: str | None  # "TRADE_FINANCE" — non-null book exclusion

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


def create_p1114_counterparty() -> pl.DataFrame:
    """
    Return the P1.114 counterparty as a single-row DataFrame.

    country_code is null — tests the geographic-filter null path AND the
    book-code exclusion null path in a single exposure.
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF,
            entity_type="corporate",
            country_code=None,  # null — no geographic home
            annual_revenue=5_000_000_000.0,
            total_assets=10_000_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1114_facility() -> pl.DataFrame:
    """
    Return the P1.114 facility as a single-row DataFrame.

    book_code is null — the classifier must not mis-classify this as excluded
    from FIRB simply because book_code IS NULL and excluded_book_codes IS NOT NULL.
    """
    rows = [
        _Facility(
            facility_reference=FACILITY_REF,
            counterparty_reference=COUNTERPARTY_REF,
            book_code=None,  # null — exercises the null-propagation defect
            currency="GBP",
            limit=1_000_000.0,
            committed=True,
            seniority="senior",
            risk_type="credit",
            is_obs_commitment=True,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_SCHEMA))


def create_p1114_loan() -> pl.DataFrame:
    """
    Return the P1.114 loan as a single-row DataFrame.

    book_code is null — mirrors the facility, ensuring the classifier sees null
    at every book-code resolution point.
    """
    rows = [
        _Loan(
            loan_reference=LOAN_REF,
            counterparty_reference=COUNTERPARTY_REF,
            book_code=None,  # null — exercises the null-propagation defect
            currency="GBP",
            drawn_amount=1_000_000.0,
            interest=0.0,
            seniority="senior",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1114_facility_mapping() -> pl.DataFrame:
    """Return the P1.114 facility-to-loan mapping as a single-row DataFrame."""
    rows = [
        _FacilityMapping(
            parent_facility_reference=FACILITY_REF,
            child_reference=LOAN_REF,
            child_type="loan",
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def create_p1114_rating() -> pl.DataFrame:
    """
    Return the P1.114 internal rating as a single-row DataFrame.

    PD=0.01 (1%) with model_id="UK_CORP_PD_01" links this counterparty to the
    P1.114 model permissions row, enabling the classifier to attempt FIRB routing.
    """
    rows = [
        _Rating(
            rating_reference="RAT_P1114_001",
            counterparty_reference=COUNTERPARTY_REF,
            rating_type="internal",
            pd=0.01,
            model_id=MODEL_ID,
            rating_date=VALUE_DATE,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1114_model_permission() -> pl.DataFrame:
    """
    Return the P1.114 model permission as a single-row DataFrame.

    Deliberately set:
    - country_codes=null  → no geographic restriction
    - excluded_book_codes="TRADE_FINANCE" → non-null exclusion list

    This combination is the minimal reproducer for the null-propagation defect:
    when book_code=null is tested against the exclusion list, a naive IS_IN
    returns null instead of False, poisoning the permission_valid boolean.
    """
    rows = [
        _ModelPermission(
            model_id=MODEL_ID,
            exposure_class="corporate",
            approach="foundation_irb",
            country_codes=None,  # null — no geo restriction
            excluded_book_codes="TRADE_FINANCE",  # non-null — triggers the defect path
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1114_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.114 parquet files and return a mapping of name → path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1114_counterparty()),
        ("facility", create_p1114_facility()),
        ("loan", create_p1114_loan()),
        ("facility_mapping", create_p1114_facility_mapping()),
        ("rating", create_p1114_rating()),
        ("model_permission", create_p1114_model_permission()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.114 fixture generation complete")
    print("-" * 60)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  →  {path}")
    print("-" * 60)
    print("Scenario: counterparty with null country_code,")
    print("          facility+loan with null book_code,")
    print("          model permission with country_codes=null,")
    print("          excluded_book_codes='TRADE_FINANCE'.")
    print("Post-fix: approach='foundation_irb', model_firb_permitted=True.")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1114_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
