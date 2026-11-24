"""
Build P1.143 fixtures: PS1/26 rule 4.11, the unfunded credit protection transitional.

Pipeline position:
    fixture builder (in-memory frames, no parquet) -> test-writer ->
    engine/crm/protection_screen.py (the Art. 213(1)(c)(i) screen)

Key responsibilities:
- Reuse the P1.10 counterparties and rating (an unrated corporate borrower at
  100% and a CQS 2 sovereign guarantor at 20%; tests/fixtures/p1_10/p1_10.py).
- Build one GBP 1,000,000 loan per scenario and one full-cover guarantee per
  loan. The guarantees differ only in ``protection_inception_date`` and the two
  Art. 213(1)(c)(i) flags, so RWA moves between 200,000 (recognised) and
  1,000,000 (not recognised) on the eligibility screen alone.

Rule under test (PS1/26 Credit Risk: General Provisions (CRR) Part, rule 4.11,
read from ps126app1.pdf):
    "During the period beginning with 1 January 2027 and ending with 30 June
    2028, point (b) of paragraph 1A of Credit Risk: Internal Ratings Based
    Approach (CRR) Part Article 183 and point (c)(i) of paragraph 1 of Credit
    Risk Mitigation (CRR) Part Article 213 shall apply to unfunded credit
    protection entered into prior to 1 January 2027 with the words 'or change'
    wherever they appear omitted."

PS1/26 Art. 213(1)(c)(i) reads "would allow the protection provider to
unilaterally cancel or change the protection in a way that would adversely
impact the institution". With "or change" omitted only the cancel limb is left.

Scenarios (every guarantee covers its loan in full; maturity equals the loan's,
so there is no maturity mismatch):

    ref    inception    cancellable  changeable  what it pins
    PRE    2026-06-01   False        True        the grandfathered row
    EVE    2026-12-31   False        True        "prior to": last eligible day
    CUT    2027-01-01   False        True        "prior to": first ineligible day
    POST   2027-02-01   False        True        entered into under Basel 3.1
    NULL   (null)       False        True        a missing date is not grandfathered
    CANCEL 2026-06-01   True         True        the cancel limb is never omitted

Hand calculation (Basel 3.1, SA):
    EAD = 1,000,000. Recognised: RW 20% (sovereign CQS 2) -> RWA 200,000.
    Not recognised: RW 100% (unrated corporate) -> RWA 1,000,000, one CRM012.

    reporting date          PRE   EVE   CUT   POST  NULL  CANCEL
    2026-12-31 (before)     1m    1m    1m    1m    1m    1m
    2027-01-01 (first day)  200k  200k  1m    1m    1m    1m
    2027-06-30 (inside)     200k  200k  1m    1m    1m    1m
    2028-06-30 (last day)   200k  200k  1m    1m    1m    1m
    2028-07-01 (after)      1m    1m    1m    1m    1m    1m

    CRR has no "or change" words (CRR Art. 213(1)(c)(i): "would allow the
    protection provider to cancel the protection unilaterally"), so on a CRR
    run every changeable-only row is recognised (200k) whatever its inception
    date, and CANCEL is not (1m).

References:
- PS1/26 Credit Risk: General Provisions (CRR) Part, rule 4.11.
- PS1/26 Art. 213(1)(c)(i); PS1/26 Art. 183(1A)(b).
- CRR Art. 213(1)(c)(i).
- tests/fixtures/p1_10/p1_10.py: the counterparties, rating and hand
  calculation this builder reuses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import GUARANTEE_SCHEMA, LOAN_SCHEMA
from tests.fixtures.p1_10.p1_10 import (
    BORROWER_REF,
    EXPECTED_RWA_ELIGIBLE,
    EXPECTED_RWA_INELIGIBLE,
    GUARANTEE_MATURITY_DATE,
    GUARANTOR_REF,
    LOAN_DRAWN_AMOUNT,
    LOAN_INTEREST,
    LOAN_MATURITY_DATE,
    LOAN_VALUE_DATE,
    create_p110_counterparties,
    create_p110_ratings,
)

# ---------------------------------------------------------------------------
# Rule 4.11 dates, as the rule states them
# ---------------------------------------------------------------------------

WINDOW_FIRST_DAY = date(2027, 1, 1)  # "beginning with 1 January 2027"
WINDOW_LAST_DAY = date(2028, 6, 30)  # "ending with 30 June 2028"
INCEPTION_CUTOFF = date(2027, 1, 1)  # "entered into prior to 1 January 2027"

# ---------------------------------------------------------------------------
# Expected outcomes (re-exported so the test reads them from one place)
# ---------------------------------------------------------------------------

RWA_RECOGNISED: float = EXPECTED_RWA_ELIGIBLE  # 200,000
RWA_NOT_RECOGNISED: float = EXPECTED_RWA_INELIGIBLE  # 1,000,000


@dataclass(frozen=True)
class Scenario:
    """One loan and the guarantee that fully covers it."""

    key: str
    inception: date | None
    cancellable: bool
    changeable: bool

    @property
    def loan_reference(self) -> str:
        """The covered loan's reference."""
        return f"LOAN_P1143_{self.key}"

    @property
    def guarantee_reference(self) -> str:
        """The guarantee's reference."""
        return f"GUAR_P1143_{self.key}"

    @property
    def changeable_only(self) -> bool:
        """True where only the 'or change' limb can make the row ineligible."""
        return self.changeable and not self.cancellable


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("PRE", date(2026, 6, 1), cancellable=False, changeable=True),
    Scenario("EVE", date(2026, 12, 31), cancellable=False, changeable=True),
    Scenario("CUT", date(2027, 1, 1), cancellable=False, changeable=True),
    Scenario("POST", date(2027, 2, 1), cancellable=False, changeable=True),
    Scenario("NULL", None, cancellable=False, changeable=True),
    Scenario("CANCEL", date(2026, 6, 1), cancellable=True, changeable=True),
)

SCENARIO_BY_KEY: dict[str, Scenario] = {s.key: s for s in SCENARIOS}


# ---------------------------------------------------------------------------
# Public frame factories
# ---------------------------------------------------------------------------


def create_p1143_counterparties() -> pl.DataFrame:
    """The P1.10 borrower (unrated corporate, 100%) and guarantor (sovereign CQS 2, 20%)."""
    return create_p110_counterparties()


def create_p1143_ratings() -> pl.DataFrame:
    """The P1.10 guarantor rating; the borrower stays unrated."""
    return create_p110_ratings()


def create_p1143_loans() -> pl.DataFrame:
    """One GBP 1,000,000 senior loan per scenario, P1.10 economics."""
    rows = [
        {
            "loan_reference": s.loan_reference,
            "counterparty_reference": BORROWER_REF,
            "currency": "GBP",
            "value_date": LOAN_VALUE_DATE,
            "maturity_date": LOAN_MATURITY_DATE,
            "drawn_amount": LOAN_DRAWN_AMOUNT,
            "interest": LOAN_INTEREST,
            "seniority": "senior",
        }
        for s in SCENARIOS
    ]
    schema = dtypes_of(LOAN_SCHEMA)
    return pl.DataFrame(rows, schema={k: schema[k] for k in rows[0]})


def create_p1143_guarantees() -> pl.DataFrame:
    """One full-cover sovereign guarantee per loan, carrying its inception date."""
    rows = [
        {
            "guarantee_reference": s.guarantee_reference,
            "guarantee_type": "sovereign_guarantee",
            "guarantor": GUARANTOR_REF,
            "currency": "GBP",
            "maturity_date": GUARANTEE_MATURITY_DATE,
            "amount_covered": LOAN_DRAWN_AMOUNT,
            "percentage_covered": 1.0,
            "beneficiary_type": "loan",
            "beneficiary_reference": s.loan_reference,
            "protection_type": "guarantee",
            "includes_restructuring": False,
            "is_unilaterally_cancellable": s.cancellable,
            "is_unilaterally_changeable": s.changeable,
            "protection_inception_date": s.inception,
        }
        for s in SCENARIOS
    ]
    declared = dtypes_of(GUARANTEE_SCHEMA)
    # protection_inception_date is written as a Date whether or not the schema
    # declares it, so the frame is the same before and after the schema change.
    schema = {k: declared.get(k, pl.Date) for k in rows[0]}
    return pl.DataFrame(rows, schema=schema)
