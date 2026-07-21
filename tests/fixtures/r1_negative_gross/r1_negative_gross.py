"""
R1 fixtures: negative on-balance amounts must never make a gross-exposure
template cell report a negative figure, and a bare negative (no netting
agreement) must raise a DQ010 data-quality warning.

Pipeline position:
    fixture-builder output -> run_parquet_pipeline -> OutputAggregator
    -> {COREPGenerator, Pillar3Generator}

Scenario design:

    CP_R1_IRB (corporate, routed F-IRB via an internal rating + model permission):
        LN_R1_POS: a +1,000,000 drawn loan under netting_agreement_reference NET_R1
        LN_R1_DEP: a  -200,000 drawn DEPOSIT under the SAME NET_R1 reference — the
                   on-balance-sheet netting convention (CRR Art. 195/219). The
                   deposit legitimately offsets the loan, so it is NOT a data
                   error; its raw drawn stays negative through the pipeline and
                   would make the IRB gross-exposure cells go negative absent the
                   floored reporting carriers.

    CP_R1_BARE (corporate, SA — no rating):
        LN_R1_BARE: a -50,000 drawn loan with NO netting_agreement_reference — a
                    bare negative that cannot net against anything. This is the
                    DQ010 case (CRR Art. 111 / Art. 166 gross exposure value).

Gross-exposure expectations (floored, CRR Art. 111 SA / Art. 166 IRB):
    IRB on-balance gross drawn+interest (C 08.03 / CR6 col b) =
        clip(1,000,000) + clip(-200,000) = 1,000,000  (NOT the raw 800,000)
    SA on-balance gross drawn (CR4 col a / C 07.00 col 0010) =
        clip(-50,000) = 0                              (NOT the raw -50,000)

DQ010 expectations:
    validate_bundle_values(loans) emits exactly one DQ010 warning for the bare
    negative (LN_R1_BARE) and NONE for the netted deposit (LN_R1_DEP).

References:
    - CRR Art. 111 (SA gross exposure value); Art. 166 (IRB exposure value)
    - CRR Art. 195/219 (on-balance-sheet netting convention)
    - src/rwa_calc/engine/aggregator/aggregator.py::_add_reporting_projection
    - src/rwa_calc/contracts/validation.py::_validate_negative_amounts_without_netting

Usage:
    uv run python tests/fixtures/r1_negative_gross/r1_negative_gross.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants — referenced by tests for assertion values
# ---------------------------------------------------------------------------

CP_IRB: str = "CP-R1-IRB"
CP_BARE: str = "CP-R1-BARE"

LOAN_POS: str = "LN-R1-POS"
LOAN_DEP: str = "LN-R1-DEP"
LOAN_BARE: str = "LN-R1-BARE"

RATING_IRB: str = "RTG-R1-IRB"
MODEL_ID: str = "CORP-FIRB-R1"
NETTING_REF: str = "NET_R1"

VALUE_DATE: date = date(2029, 1, 1)
MATURITY_DATE: date = date(2031, 7, 1)  # approx 2.5y
RATING_DATE: date = date(2029, 1, 2)

# Raw drawn amounts
DRAWN_POS: float = 1_000_000.0
DRAWN_DEP: float = -200_000.0  # netted deposit (credit balance)
DRAWN_BARE: float = -50_000.0  # bare negative (no netting reference)

PD_IRB: float = 0.0050
LGD_FIRB: float = 0.40
EFFECTIVE_MATURITY: float = 2.5

# Floored gross-exposure expectations (the fix): negatives clip to 0.
IRB_GROSS_DRAWN_FLOORED: float = 1_000_000.0  # clip(1,000,000) + clip(-200,000)
IRB_GROSS_DRAWN_RAW: float = 800_000.0  # the buggy pre-fix sum (1,000,000 - 200,000)
SA_GROSS_DRAWN_FLOORED: float = 0.0  # clip(-50,000)


# ---------------------------------------------------------------------------
# Minimal dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float
    total_assets: float
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool

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
        }


@dataclass(frozen=True)
class _Loan:
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
    is_defaulted: bool
    netting_agreement_reference: str | None

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
            "is_defaulted": self.is_defaulted,
            "netting_agreement_reference": self.netting_agreement_reference,
        }


@dataclass(frozen=True)
class _Rating:
    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
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
            "pd": self.pd,
            "rating_date": self.rating_date,
            "is_solicited": self.is_solicited,
            "model_id": self.model_id,
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
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_r1_counterparties() -> pl.DataFrame:
    """Return the two R1 corporate counterparties.

    CP_R1_IRB carries an internal rating (F-IRB routing); CP_R1_BARE has no
    rating and routes SA. Both are unrated externally (no cqs).
    """
    rows = [
        _Counterparty(
            counterparty_reference=CP_IRB,
            counterparty_name="R1 IRB Corporate Ltd",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=200_000_000.0,
            total_assets=400_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
        _Counterparty(
            counterparty_reference=CP_BARE,
            counterparty_name="R1 Bare-Negative Corporate Ltd",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=200_000_000.0,
            total_assets=400_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_r1_loans() -> pl.DataFrame:
    """Return the three R1 loan rows.

    LN_R1_POS / LN_R1_DEP share NET_R1 (a positive loan and its netted deposit);
    LN_R1_BARE carries no netting reference (the DQ010 case).
    """
    rows = [
        _Loan(
            loan_reference=LOAN_POS,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=CP_IRB,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_POS,
            interest=0.0,
            lgd=LGD_FIRB,
            beel=0.0,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
            is_defaulted=False,
            netting_agreement_reference=NETTING_REF,
        ),
        _Loan(
            loan_reference=LOAN_DEP,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=CP_IRB,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_DEP,
            interest=0.0,
            lgd=LGD_FIRB,
            beel=0.0,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
            is_defaulted=False,
            netting_agreement_reference=NETTING_REF,
        ),
        _Loan(
            loan_reference=LOAN_BARE,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=CP_BARE,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_BARE,
            interest=0.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
            effective_maturity=EFFECTIVE_MATURITY,
            is_defaulted=False,
            netting_agreement_reference=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_r1_ratings() -> pl.DataFrame:
    """Return the single internal rating row for CP_R1_IRB (F-IRB routing)."""
    rows = [
        _Rating(
            rating_reference=RATING_IRB,
            counterparty_reference=CP_IRB,
            rating_type="internal",
            rating_agency="internal",
            rating_value="BBB",
            pd=PD_IRB,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_r1_model_permission() -> pl.DataFrame:
    """Return the single model permission granting F-IRB for corporates."""
    rows = [
        _ModelPermission(
            model_id=MODEL_ID,
            exposure_class="corporate",
            approach="foundation_irb",
            country_codes=None,
            excluded_book_codes=None,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_r1_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """Write all R1 parquet files and return a mapping of name to path."""
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, Path] = {}
    artefacts = [
        ("counterparty", create_r1_counterparties()),
        ("loan", create_r1_loans()),
        ("rating", create_r1_ratings()),
        ("model_permission", create_r1_model_permission()),
    ]
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path
    return saved


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_r1_fixtures()
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>2} row(s)  ->  {path.name}")


if __name__ == "__main__":
    main()
