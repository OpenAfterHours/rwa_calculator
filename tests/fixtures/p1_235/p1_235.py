"""
Generate P1.235 fixtures: FIRB Foundation Collateral Method eligibility gate.

CRR/PS1-26 Art. 199(2)/(5)/(6) restricts the non-financial collateral that may
reduce F-IRB LGD to collateral the institution ATTESTS is IRB-eligible via the
``is_eligible_irb_collateral`` flag. This fixture pins four senior-corporate
F-IRB scenarios that hold everything constant except the attestation flag, so an
acceptance test can show the flag alone flips the outcome end-to-end:

    crr_attested_re    — RE collateral, flag True  -> LGD* 0.378571 (recognised)
    crr_unattested_re  — RE collateral, flag False -> LGD  0.4500   (reverts to LGDU)
    b31_attested_re    — RE collateral, flag True  -> LGD* 0.2800   (recognised)
    b31_unattested_re  — RE collateral, flag False -> LGD  0.4000   (reverts to LGDU)

The attested cases mirror the P1.190 crr_full_re / b31_full_re hand-calcs; the
unattested cases revert to the senior unsecured supervisory LGD (45% CRR
Art. 161(1)(a); 40% PS1/26 Art. 161(1)(aa) non-FSE corporate).

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance p1_235)

References:
    - CRR Art. 199(2): eligible IRB collateral recognition conditions (attested).
    - CRR Art. 199(5): receivables 1-year maximum original maturity.
    - CRR Art. 199(6): other physical collateral eligibility.
    - CRR Art. 161(1)(a): LGDU senior unsecured corporate = 45%.
    - PS1/26 Art. 161(1)(aa): LGDU senior unsecured non-FSE corporate = 40%.
    - IMPLEMENTATION_PLAN.md: P1.235 entry.

Usage:
    uv run python tests/fixtures/p1_235/p1_235.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl
from dateutil.relativedelta import relativedelta

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Shared scenario constants
# ---------------------------------------------------------------------------

REPORTING_DATE = date(2026, 6, 30)
MATURITY_DATE = REPORTING_DATE + relativedelta(years=3)  # M ≈ 3.0y, no maturity mismatch
RATING_DATE = date(2026, 6, 30)

DRAWN_AMOUNT: float = 10_000_000.00
FACILITY_LIMIT: float = 10_000_000.00
COLLATERAL_MV: float = 10_000_000.00
PD: float = 0.02

# Expected LGD outcomes
CRR_ATTESTED_LGD: float = 0.378571  # P1.190 crr_full_re: OC=1.4×, LGDS=35%, LGDU=45%
B31_ATTESTED_LGD: float = 0.2800  # P1.190 b31_full_re: continuous formula, LGDU=40%
CRR_UNATTESTED_LGD: float = 0.4500  # gate zeroes ES -> LGDU (Art. 161(1)(a))
B31_UNATTESTED_LGD: float = 0.4000  # gate zeroes ES -> LGDU (Art. 161(1)(aa))


@dataclass(frozen=True)
class Scenario:
    """One P1.235 acceptance scenario."""

    label: str
    is_eligible_irb_collateral: bool
    expected_lgd: float

    @property
    def cp_ref(self) -> str:
        return f"P1235-CP-{self.label}"

    @property
    def fac_ref(self) -> str:
        return f"P1235-F-{self.label}"

    @property
    def loan_ref(self) -> str:
        return f"P1235-L-{self.label}"

    @property
    def coll_ref(self) -> str:
        return f"P1235-C-{self.label}"

    @property
    def model_id(self) -> str:
        return f"P1235-CORP-FIRB-{self.label}"


SCENARIOS: dict[str, Scenario] = {
    "crr_attested_re": Scenario("crr_attested_re", True, CRR_ATTESTED_LGD),
    "crr_unattested_re": Scenario("crr_unattested_re", False, CRR_UNATTESTED_LGD),
    "b31_attested_re": Scenario("b31_attested_re", True, B31_ATTESTED_LGD),
    "b31_unattested_re": Scenario("b31_unattested_re", False, B31_UNATTESTED_LGD),
}

# ---------------------------------------------------------------------------
# Private row dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
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
class _Facility:
    facility_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    limit: float
    committed: bool
    seniority: str
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
            "seniority": self.seniority,
            "risk_type": self.risk_type,
        }


@dataclass(frozen=True)
class _Loan:
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
class _Collateral:
    collateral_reference: str
    collateral_type: str
    currency: str
    market_value: float
    beneficiary_type: str
    beneficiary_reference: str
    is_eligible_financial_collateral: bool
    is_eligible_irb_collateral: bool
    property_type: str | None
    property_ltv: float | None

    def to_dict(self) -> dict:
        return {
            "collateral_reference": self.collateral_reference,
            "collateral_type": self.collateral_type,
            "currency": self.currency,
            "market_value": self.market_value,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "is_eligible_financial_collateral": self.is_eligible_financial_collateral,
            "is_eligible_irb_collateral": self.is_eligible_irb_collateral,
            "property_type": self.property_type,
            "property_ltv": self.property_ltv,
        }


@dataclass(frozen=True)
class _Rating:
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
# Private factory helpers
# ---------------------------------------------------------------------------


def _make_counterparty(s: Scenario) -> pl.DataFrame:
    row = _Counterparty(
        counterparty_reference=s.cp_ref,
        counterparty_name=f"P1.235 F-IRB Corporate ({s.label})",
        entity_type="corporate",
        country_code="GB",
        default_status=False,
        is_financial_sector_entity=False,
        apply_fi_scalar=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def _make_facility(s: Scenario) -> pl.DataFrame:
    row = _Facility(
        facility_reference=s.fac_ref,
        counterparty_reference=s.cp_ref,
        currency="GBP",
        value_date=REPORTING_DATE,
        maturity_date=MATURITY_DATE,
        limit=FACILITY_LIMIT,
        committed=True,
        seniority="senior",
        risk_type="funded",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(FACILITY_SCHEMA))


def _make_loan(s: Scenario) -> pl.DataFrame:
    row = _Loan(
        loan_reference=s.loan_ref,
        counterparty_reference=s.cp_ref,
        currency="GBP",
        value_date=REPORTING_DATE,
        maturity_date=MATURITY_DATE,
        drawn_amount=DRAWN_AMOUNT,
        interest=0.0,
        seniority="senior",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def _make_collateral(s: Scenario) -> pl.DataFrame:
    """One RE collateral row, attestation flag driven by the scenario.

    beneficiary_type=facility so facility-level collateral flows to the loan.
    original_maturity_years=10.0 -> no maturity mismatch.
    """
    row = _Collateral(
        collateral_reference=s.coll_ref,
        collateral_type="real_estate",
        currency="GBP",
        market_value=COLLATERAL_MV,
        beneficiary_type="facility",
        beneficiary_reference=s.fac_ref,
        is_eligible_financial_collateral=False,
        is_eligible_irb_collateral=s.is_eligible_irb_collateral,
        property_type="residential",
        property_ltv=1.00,
    )
    base = pl.DataFrame([row.to_dict()], schema=dtypes_of(COLLATERAL_SCHEMA))
    return base.with_columns(pl.lit(10.0).alias("original_maturity_years").cast(pl.Float64))


def _make_rating(s: Scenario) -> pl.DataFrame:
    row = _Rating(
        rating_reference=f"RTG-P1235-{s.label}",
        counterparty_reference=s.cp_ref,
        rating_type="internal",
        pd=PD,
        model_id=s.model_id,
        rating_date=RATING_DATE,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(RATINGS_SCHEMA))


def _make_model_permission(s: Scenario) -> pl.DataFrame:
    row = _ModelPermission(
        model_id=s.model_id,
        exposure_class="corporate",
        approach="foundation_irb",
        country_codes=None,
        excluded_book_codes=None,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


def _artefacts_for_scenario(s: Scenario) -> list[tuple[str, pl.DataFrame]]:
    return [
        (f"counterparty_{s.label}", _make_counterparty(s)),
        (f"facility_{s.label}", _make_facility(s)),
        (f"loan_{s.label}", _make_loan(s)),
        (f"collateral_{s.label}", _make_collateral(s)),
        (f"rating_{s.label}", _make_rating(s)),
        (f"model_permission_{s.label}", _make_model_permission(s)),
    ]


# ---------------------------------------------------------------------------
# Save helper
# ---------------------------------------------------------------------------


def save_p1235_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """Write all P1.235 parquet files and return a mapping of name -> path."""
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, Path] = {}
    for scenario in SCENARIOS.values():
        for name, df in _artefacts_for_scenario(scenario):
            path = output_dir / f"{name}.parquet"
            df.write_parquet(path)
            saved[name] = path
    return saved


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1235_fixtures()
    for name, path in saved.items():
        df = pl.read_parquet(path)
        # noqa: T201 — standalone fixture generator prints a summary.
        print(f"  {name:<45} {df.shape[0]:>2} row(s) -> {path.name}")  # noqa: T201


if __name__ == "__main__":
    main()
