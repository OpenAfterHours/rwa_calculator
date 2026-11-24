"""
Multi-guarantor decline portfolio — one beneficial and one declined guarantor on one facility.

Pipeline position:
    build_multi_guarantor_decline_bundle(scenario) -> RawDataBundle -> PipelineOrchestrator

Why this portfolio: no registered ``RUNS`` portfolio
(``tests/acceptance/reporting/test_supervisory_validations.py``) holds an exposure
with more than one guarantor, so the path where the calculators DECLINE one of two
guarantees and reallocate its share (``engine/crm/guarantees.py::
redistribute_non_beneficial``) was reached by synthetic unit frames only — frames
whose shape the CRM split cannot produce. This builder produces the real shape:
one obligor, one committed facility with a drawn child loan, so the CRM stage
emits TWO parents (the loan and the facility's synthetic ``_UNDRAWN`` headroom),
each split into ``__G_<A>``, ``__G_<B>`` and ``__REM`` legs.

Shape (every amount a round number so a mis-sized leg is visible on sight):

- ``OBLIGOR`` — a large corporate (no SME adjustment, no supporting factor).
- ``FACILITY`` — committed, non-revolving, ``risk_type="MR"`` (medium risk), limit
  ``FACILITY_LIMIT``; ``LOAN`` draws ``DRAWN_AMOUNT`` under it, so the undrawn
  headroom is ``FACILITY_LIMIT - DRAWN_AMOUNT``. The off-balance-sheet leg is what
  separates the CCF=100% basis on which Art. 235 / 236(3) size the covered part
  from the post-CCF exposure value.
- Two FACILITY-level percentage guarantees, so each child exposure carries the
  same two percentages of its own exposure value. A percentage pair summing above
  100% over-covers the exposure, which is what leaves the beneficial guarantor with
  unused protection after the CRM split pro-rates the two covers down to E.
- Loan, facility and guarantees all mature on ``MATURITY`` with matched currency,
  so neither the Art. 233(3) FX haircut nor the Art. 237-239 maturity adjustment
  applies.

The obligor and the two guarantors are supplied per scenario
(:class:`DeclineScenario`), so one builder serves the IRB, SA and Basel 3.1
output-floor variants the tests need.

References:
- CRR Art. 193(1), (3) / PS1/26 Art. 193(2A): the basis for declining a guarantee.
- CRR Art. 235(1) / PS1/26 Art. 235(1)(a)-(b): Eg = min(GA, E) on the CCF=100%
  basis; the uncovered part takes the obligor's risk weight.
- CRR Art. 236(3): the IRB twin of the CCF=100% basis.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: Must match ``create_full_irb_model_permissions`` or no row routes IRB.
_MODEL_ID: str = "TEST_FULL_IRB"

OBLIGOR: str = "MGD-CP-OB"
FACILITY: str = "MGD-FAC"
LOAN: str = "MGD-LN"
#: The synthetic headroom exposure the hierarchy stage emits for ``FACILITY``.
UNDRAWN: str = f"{FACILITY}_UNDRAWN"

DRAWN_AMOUNT: float = 1_000_000.0
FACILITY_LIMIT: float = 2_000_000.0
#: Undrawn headroom = limit - drawn child loan.
UNDRAWN_AMOUNT: float = FACILITY_LIMIT - DRAWN_AMOUNT

VALUE_DATE: date = date(2026, 1, 2)
#: Chosen so the residual maturity is a whole number of years at both reporting
#: dates (the engine's day-of-year / 365 count): M = 4.0 at 2026-06-01 (CRR) and
#: M = 3.0 at 2027-06-01 (Basel 3.1), which keeps the IRB hand-calc exact.
MATURITY: date = date(2030, 6, 1)
CRR_REPORTING_DATE: date = date(2026, 6, 1)
B31_REPORTING_DATE: date = date(2027, 6, 1)

_LARGE_CORPORATE_REVENUE: float = 500_000_000.0
_GUARANTEE_ORIGINAL_MATURITY_YEARS: float = 4.4


@dataclass(frozen=True)
class Party:
    """One counterparty: its SA class, and its ratings (either, both or neither).

    ``cqs`` is an external ECAI rating (SA risk weight); ``pd`` is an internal
    rating with a ``model_id`` (IRB routing for an obligor, parameter
    substitution for a guarantor).
    """

    reference: str
    entity_type: str
    cqs: int | None = None
    pd: float | None = None


@dataclass(frozen=True)
class DeclineScenario:
    """One portfolio: the obligor, the two guarantors and their percentages.

    ``guarantor_a`` / ``guarantor_b`` cover ``pct_a`` / ``pct_b`` of every child
    exposure of ``FACILITY``. Which of them the engine declines follows from the
    ratings — the scenario only states the inputs.
    """

    obligor: Party
    guarantor_a: Party
    guarantor_b: Party
    pct_a: float
    pct_b: float


def build_multi_guarantor_decline_bundle(scenario: DeclineScenario) -> RawDataBundle:
    """Assemble the scenario as a sealed bundle (shape-identical to a loaded one).

    Run through ``PipelineOrchestrator().run_with_data`` with
    ``PermissionMode.IRB`` when the obligor carries an internal PD, and
    ``PermissionMode.STANDARDISED`` otherwise.
    """
    parties = (scenario.obligor, scenario.guarantor_a, scenario.guarantor_b)
    return make_raw_bundle(
        facilities=_facilities(),
        loans=_loans(),
        counterparties=_counterparties(parties),
        facility_mappings=_facility_mappings(),
        ratings=_ratings(parties),
        guarantees=_guarantees(scenario),
        model_permissions=create_full_irb_model_permissions(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties(parties: tuple[Party, ...]) -> pl.DataFrame:
    rows = [
        {
            "counterparty_reference": party.reference,
            "entity_type": party.entity_type,
            "country_code": "GB",
            "annual_revenue": _LARGE_CORPORATE_REVENUE,
        }
        for party in parties
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings(parties: tuple[Party, ...]) -> pl.DataFrame:
    rows: list[dict] = []
    for party in parties:
        if party.cqs is not None:
            rows.append(
                {
                    "rating_reference": f"MGD-RTG-EXT-{party.reference}",
                    "counterparty_reference": party.reference,
                    "rating_type": "external",
                    "rating_agency": "S&P",
                    "cqs": party.cqs,
                    "rating_date": VALUE_DATE,
                    "is_solicited": True,
                }
            )
        if party.pd is not None:
            rows.append(
                {
                    "rating_reference": f"MGD-RTG-INT-{party.reference}",
                    "counterparty_reference": party.reference,
                    "rating_type": "internal",
                    "pd": party.pd,
                    "model_id": _MODEL_ID,
                    "rating_date": VALUE_DATE,
                }
            )
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _facilities() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "facility_reference": FACILITY,
                "counterparty_reference": OBLIGOR,
                "product_type": "term_loan",
                "limit": FACILITY_LIMIT,
                "risk_type": "MR",
                "currency": "GBP",
                "value_date": VALUE_DATE,
                "maturity_date": MATURITY,
                "committed": True,
                "is_revolving": False,
            }
        ],
        schema_overrides=dtypes_of(FACILITY_SCHEMA),
    )


def _loans() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "loan_reference": LOAN,
                "counterparty_reference": OBLIGOR,
                "product_type": "term_loan",
                "drawn_amount": DRAWN_AMOUNT,
                "interest": 0.0,
                "currency": "GBP",
                "value_date": VALUE_DATE,
                "maturity_date": MATURITY,
                "seniority": "senior",
            }
        ],
        schema_overrides=dtypes_of(LOAN_SCHEMA),
    )


def _facility_mappings() -> pl.DataFrame:
    return pl.DataFrame(
        [{"parent_facility_reference": FACILITY, "child_reference": LOAN, "child_type": "loan"}],
        schema_overrides=dtypes_of(FACILITY_MAPPING_SCHEMA),
    )


def _guarantees(scenario: DeclineScenario) -> pl.DataFrame:
    rows = [
        _guarantee(scenario.guarantor_a.reference, scenario.pct_a),
        _guarantee(scenario.guarantor_b.reference, scenario.pct_b),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(GUARANTEE_SCHEMA))


def _guarantee(guarantor: str, percentage: float) -> dict:
    """A facility-level percentage guarantee: fully eligible, matched, unfunded."""
    return {
        "guarantee_reference": f"MGD-GUAR-{guarantor}",
        "guarantee_type": "guarantee",
        "guarantor": guarantor,
        "beneficiary_type": "facility",
        "beneficiary_reference": FACILITY,
        "currency": "GBP",
        "maturity_date": MATURITY,
        "original_maturity_years": _GUARANTEE_ORIGINAL_MATURITY_YEARS,
        "amount_covered": None,
        "percentage_covered": percentage,
        "protection_type": "guarantee",
        "includes_restructuring": True,
        "guarantor_seniority": "senior",
        "is_unilaterally_cancellable": False,
        "is_unilaterally_changeable": False,
    }
