"""
P1.300 fixtures: a third party's residual-value payment obligation on a lease,
recognised as unfunded credit protection (CRR / PS1/26 Art. 134(7), CRR Art.
166(4) / PS1/26 Art. 166A(4), via Art. 201 and Art. 213-215).

Verbatim, CRR Art. 134(7) (and PS1/26 Art. 134(7), ``ps126app1.pdf`` 0-indexed
page 68, which reads "is required" for "may be required" and points at the
Credit Risk Mitigation (CRR) Part):

    "A party other than the lessee may be required to make a payment related to
    the residual value of a leased property and that payment obligation fulfils
    the set of conditions in Article 201 regarding the eligibility of protection
    providers as well as the requirements for recognising other types of
    guarantees provided in Articles 213 to 215, that payment obligation may be
    taken into account as unfunded credit protection under Chapter 4."

CRR Art. 213(1)(c)(iii) (PS1/26 CRM Part Art. 213(1)(c)(iii), 0-indexed page 186)
sets the payout test for this case at lease expiry: no clause may prevent the
provider "from being obliged to pay out in a timely manner ... when the leasing
contract has expired for the purposes of recognising guaranteed residual value
under Articles 134(7) and 166(4)".

Input convention this fixture pins: the residual value is its OWN exposure — a
loan under a counterparty whose ``entity_type`` is ``other_residual_lease``
(class OTHER, Art. 134(7) ``1/t x 100%``) — and the third party's obligation is
an ordinary ``GUARANTEE_SCHEMA`` row whose ``beneficiary_reference`` is that
residual-value loan. The engine's generic SA risk-weight substitution (Art. 235)
then applies, subject to the Art. 193(1) benefit test.

Three exposures, one per scenario, each a residual value of 1,000,000 with the
lease expiring five years after the reporting date (the guarantee matures on the
same date, so there is no Art. 237-239 maturity mismatch):

    unguaranteed      control — no guarantee row.
    institution_cqs2  MOVER — full cover by an ECAI-rated CQS 2 GB institution.
    corporate_cqs5    DECLINE — full cover by an ECAI-rated CQS 5 GB corporate.
                      Eligible under Art. 201(1)(g) (it HAS an ECAI assessment),
                      but its 150% is not below the residual value's 100%, so
                      the Art. 193(1) benefit test declines it. Rated on purpose:
                      an UNRATED corporate is declined by Art. 201(1)(g) instead
                      (CRM013, guarantor_rw null) under the same status string.

``t`` is deliberately left unstated. Art. 134(7)'s ``t`` has no production input
today (P1.360), so the residual-value leg takes ``1/max(1, null->1) = 100%``.
P1.360's planned carrier (``lease_remaining_term_years``) keeps the null path at
100%, so these figures survive it; setting a ``t`` here would instead make the
residual value's own RW 20% (t = 5) and turn the mover into a decline.

Hand calculation (rwa_final on the residual-value exposure, EAD 1,000,000):

    unguaranteed      CRR 1,000,000 x 1.00 = 1,000,000 | B31 1,000,000 x 1.00 = 1,000,000
    institution_cqs2  CRR 1,000,000 x 0.50 =   500,000 (Art. 120 Table 3)
                      B31 1,000,000 x 0.30 =   300,000 (PS1/26 Art. 120 Table 3 ECRA)
    corporate_cqs5    guarantor RW 1.50 (Art. 122 Table 6, both regimes) >= 1.00
                      -> declined, 1,000,000 in both regimes

The bundle is assembled IN MEMORY (mirroring P1.271 / P1.273) — no parquet
dependency, so no ``generate_all.py`` registration is needed.

References:
    - CRR Art. 134(7) / PS1/26 Art. 134(7): lease exposure value; residual value
      1/t x 100%; third-party residual-value obligation as UFCP.
    - CRR Art. 166(4) / PS1/26 Art. 166A(4): the IRB counterpart.
    - CRR / PS1/26 Art. 201(1)(g), 213(1)(c)(iii), 235(1), 193(1).
    - CRR Art. 120 Table 3; PS1/26 Art. 120 Table 3 (ECRA); Art. 122 Table 6.
    - IMPLEMENTATION_PLAN.md: P1.300 (and P1.360 for ``t``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl
from dateutil.relativedelta import relativedelta

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

RESIDUAL_VALUE: float = 1_000_000.00
LEASE_REMAINING_YEARS: int = 5
RATING_AGENCY: str = "S&P"

INSTITUTION_GUARANTOR_REF: str = "P1300-GTOR-INST-CQS2"
CORPORATE_GUARANTOR_REF: str = "P1300-GTOR-CORP-CQS5"

# Art. 120 Table 3 CQS 2 institution RW: CRR 50%, PS1/26 ECRA 30%.
CRR_INSTITUTION_CQS2_RW: float = 0.50
B31_INSTITUTION_CQS2_RW: float = 0.30
# Art. 122 Table 6 CQS 5 corporate RW: 150% in both regimes.
CORPORATE_CQS5_RW: float = 1.50
# Art. 134(7) residual value with no ``t`` input: 1/1 x 100%.
RESIDUAL_VALUE_RW: float = 1.00

STATUS_SUBSTITUTED: str = "SA_RW_SUBSTITUTION"
STATUS_DECLINED: str = "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"


@dataclass(frozen=True)
class Scenario:
    """One P1.300 residual-value exposure and the guarantor (if any) covering it."""

    label: str
    guarantor_ref: str | None

    @property
    def cp_ref(self) -> str:
        return f"P1300-RV-CP-{self.label}"

    @property
    def loan_ref(self) -> str:
        return f"P1300-RV-L-{self.label}"

    @property
    def guarantee_ref(self) -> str:
        return f"P1300-RVG-{self.label}"


SCENARIOS: dict[str, Scenario] = {
    "unguaranteed": Scenario("unguaranteed", None),
    "institution_cqs2": Scenario("institution_cqs2", INSTITUTION_GUARANTOR_REF),
    "corporate_cqs5": Scenario("corporate_cqs5", CORPORATE_GUARANTOR_REF),
}

# Expected rwa_final summed over every result row of the residual-value loan.
EXPECTED_RWA: dict[tuple[str, str], float] = {
    ("crr", "unguaranteed"): RESIDUAL_VALUE * RESIDUAL_VALUE_RW,
    ("crr", "institution_cqs2"): RESIDUAL_VALUE * CRR_INSTITUTION_CQS2_RW,
    ("crr", "corporate_cqs5"): RESIDUAL_VALUE * RESIDUAL_VALUE_RW,
    ("b31", "unguaranteed"): RESIDUAL_VALUE * RESIDUAL_VALUE_RW,
    ("b31", "institution_cqs2"): RESIDUAL_VALUE * B31_INSTITUTION_CQS2_RW,
    ("b31", "corporate_cqs5"): RESIDUAL_VALUE * RESIDUAL_VALUE_RW,
}


def lease_expiry(reporting_date: date) -> date:
    """The lease (and the residual-value guarantee) ends five years out."""
    return reporting_date + relativedelta(years=LEASE_REMAINING_YEARS)


def build_p1_300_bundle(reporting_date: date) -> RawDataBundle:
    """Assemble the in-memory RawDataBundle holding all three P1.300 scenarios."""
    scenarios = list(SCENARIOS.values())
    guaranteed = [s for s in scenarios if s.guarantor_ref is not None]
    counterparties = pl.DataFrame(
        [_residual_counterparty(s) for s in scenarios] + _guarantor_counterparties(),
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    loans = pl.DataFrame(
        [_residual_loan(s, reporting_date) for s in scenarios], schema=dtypes_of(LOAN_SCHEMA)
    )
    guarantees = pl.DataFrame(
        [_guarantee(s, reporting_date) for s in guaranteed], schema=dtypes_of(GUARANTEE_SCHEMA)
    )
    ratings = pl.DataFrame(_guarantor_ratings(reporting_date), schema=dtypes_of(RATINGS_SCHEMA))
    return make_raw_bundle(
        counterparties=counterparties,
        loans=loans,
        guarantees=guarantees,
        ratings=ratings,
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
    )


def _residual_counterparty(s: Scenario) -> dict:
    """The residual-value 'obligor': Art. 134(7) other item, class OTHER."""
    return {
        "counterparty_reference": s.cp_ref,
        "counterparty_name": f"P1.300 leased-asset residual value ({s.label})",
        "entity_type": "other_residual_lease",
        "country_code": "GB",
        "default_status": False,
    }


def _guarantor_counterparties() -> list[dict]:
    return [
        {
            "counterparty_reference": INSTITUTION_GUARANTOR_REF,
            "counterparty_name": "P1.300 residual-value guarantor (institution, CQS 2)",
            "entity_type": "institution",
            "country_code": "GB",
            "default_status": False,
        },
        {
            "counterparty_reference": CORPORATE_GUARANTOR_REF,
            "counterparty_name": "P1.300 residual-value guarantor (corporate, CQS 5)",
            "entity_type": "corporate",
            "country_code": "GB",
            "default_status": False,
            "is_financial_sector_entity": False,
        },
    ]


def _residual_loan(s: Scenario, reporting_date: date) -> dict:
    """Residual value at its discounted accounting value (Art. 134(7))."""
    return {
        "loan_reference": s.loan_ref,
        "counterparty_reference": s.cp_ref,
        "currency": "GBP",
        "value_date": reporting_date - relativedelta(years=2),
        "maturity_date": lease_expiry(reporting_date),
        "drawn_amount": RESIDUAL_VALUE,
        "interest": 0.0,
        "seniority": "senior",
    }


def _guarantee(s: Scenario, reporting_date: date) -> dict:
    """Full-cover third-party residual-value guarantee, paying at lease expiry."""
    return {
        "guarantee_reference": s.guarantee_ref,
        "guarantee_type": "residual_value_guarantee",
        "guarantor": s.guarantor_ref,
        "currency": "GBP",
        "maturity_date": lease_expiry(reporting_date),
        "amount_covered": RESIDUAL_VALUE,
        "percentage_covered": 1.0,
        "beneficiary_type": "loan",
        "beneficiary_reference": s.loan_ref,
    }


def _guarantor_ratings(reporting_date: date) -> list[dict]:
    return [
        {
            "rating_reference": "P1300-RTG-INST-CQS2",
            "counterparty_reference": INSTITUTION_GUARANTOR_REF,
            "rating_type": "external",
            "rating_agency": RATING_AGENCY,
            "rating_value": "A",
            "cqs": 2,
            "rating_date": reporting_date - relativedelta(months=1),
        },
        {
            "rating_reference": "P1300-RTG-CORP-CQS5",
            "counterparty_reference": CORPORATE_GUARANTOR_REF,
            "rating_type": "external",
            "rating_agency": RATING_AGENCY,
            "rating_value": "B",
            "cqs": 5,
            "rating_date": reporting_date - relativedelta(months=1),
        },
    ]
