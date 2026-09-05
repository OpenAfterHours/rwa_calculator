"""
Generate on-B/S netting agreement-perimeter fixtures (reverses P1.238).

CRR/PS1-26 Art. 195 permits on-balance-sheet netting of reciprocal cash
balances; Art. 205(a) and Art. 219 describe the netting mechanics (drawn
against drawn) without confining the perimeter to a single counterparty pair.
By operator decision dated 2026-09-04, the netting perimeter for these
fixtures is the NETTING AGREEMENT ITSELF: every deposit and loan sharing one
`netting_agreement_reference` and currency nets against each other, regardless
of which counterparty within the agreement holds which leg. This reverses the
prior P1.238 reading, which pooled deposits by
(agreement, currency, counterparty) and refused to net a deposit against a
loan owed by a different counterparty under the same agreement.

The behaviour is gated by a new cited pack Feature,
`on_bs_netting_perimeter_is_agreement`, enabled=True under both CRR and
Basel 3.1. With the Feature disabled, the engine reverts to the prior
single-counterparty keying.

Each Scenario's rows carry their OWN `netting_agreement_reference`
(`f"{AGREEMENT_REF}-{label}"`, via `Scenario.agreement_ref`), rather than the
single module-level `AGREEMENT_REF` value. Under the agreement-perimeter
reading, ALL rows sharing one agreement reference pool together regardless of
counterparty — so if every scenario shared the literal `AGREEMENT_REF`
constant, a multi-scenario bundle (e.g. building `crr_same_cp` and
`crr_cross_cp` together) would pool their deposits and loans across
scenarios, corrupting each scenario's intended, isolated netting outcome.
Scoping the reference per scenario keeps scenarios independent no matter how
many are assembled into one bundle. `AGREEMENT_REF` remains exported as the
shared PREFIX for callers that need it.

Each scenario carries a £200k deposit (a negative-drawn loan) and a £1m
positive loan under its own netting agreement (`AGR1-<label>`); only the
loan's counterparty differs:

    <regime>_same_cp   — loan owed by the deposit's counterparty
                         -> nets under either keying, EAD £800k
    <regime>_cross_cp  — loan owed by a DIFFERENT counterparty under the
                         SAME agreement
                         -> Feature enabled (default): nets, EAD £800k, and
                            raises one CRM016 audit-trail WARNING recording
                            the cross-counterparty offset
                         -> Feature disabled: no netting, EAD £1m

Both counterparties are unrated corporates (Art. 122, 100% SA risk weight),
so the RWA equals the post-netting EAD in every case. `RWA_NO_NETTING`
(£1m) is kept exported as the Feature-disabled control value for `cross_cp`
scenarios; `RWA_NETTED` (£800k, aliased as `RWA_SAME_CP_NETTED` for
call-site compatibility) is now the expected value for BOTH `same_cp` and
`cross_cp` scenarios when the Feature is at its default (enabled).

The bundle is assembled IN MEMORY (no parquet dependency), so the acceptance
tests are reproducible on a fresh checkout.

References:
    - CRR/PS1-26 Art. 195: on-B/S netting of reciprocal balances.
    - CRR Art. 205(a): eligibility of on-balance-sheet netting as CRM.
    - CRR Art. 219: drawn-on-drawn cash netting.
    - CRR Art. 122: unrated corporate 100% risk weight.
    - Pack Feature: `on_bs_netting_perimeter_is_agreement`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl
from dateutil.relativedelta import relativedelta

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, FACILITY_MAPPING_SCHEMA, LOAN_SCHEMA
from tests.fixtures.raw_bundle import make_raw_bundle

DEPOSIT_BALANCE: float = -200_000.00
LOAN_DRAWN: float = 1_000_000.00
AGREEMENT_REF = "P1238-AGR1"
RWA_NO_NETTING: float = 1_000_000.00  # £1m EAD × 100% unrated corporate
RWA_NETTED: float = 800_000.00  # (£1m − £200k) × 100% — agreement-perimeter netting
RWA_SAME_CP_NETTED: float = RWA_NETTED  # alias kept for existing call sites


@dataclass(frozen=True)
class Scenario:
    """One P1.238 acceptance scenario."""

    label: str
    same_counterparty: bool

    @property
    def deposit_cp(self) -> str:
        return f"P1238-CP-DEP-{self.label}"

    @property
    def loan_cp(self) -> str:
        return self.deposit_cp if self.same_counterparty else f"P1238-CP-LOAN-{self.label}"

    @property
    def deposit_ref(self) -> str:
        return f"P1238-DEP-{self.label}"

    @property
    def loan_ref(self) -> str:
        return f"P1238-LN-{self.label}"

    @property
    def agreement_ref(self) -> str:
        """Scenario-scoped netting agreement reference.

        Scoped per scenario (rather than the shared `AGREEMENT_REF` constant)
        so that assembling more than one scenario into a single bundle cannot
        pool their deposits/loans together under the agreement-perimeter
        reading — see the module docstring.
        """
        return f"{AGREEMENT_REF}-{self.label}"

    @property
    def expected_loan_rwa(self) -> float:
        """RWA with the agreement-perimeter Feature at its default (enabled).

        The netting agreement reference alone defines the perimeter, so both
        same-counterparty and cross-counterparty legs under AGR1 net: £800k in
        every case. Callers exercising the Feature-disabled control path use
        `RWA_NO_NETTING` directly for the `cross_cp` scenarios instead of this
        property.
        """
        return RWA_NETTED


SCENARIOS: dict[str, Scenario] = {
    "crr_same_cp": Scenario("crr_same_cp", True),
    "crr_cross_cp": Scenario("crr_cross_cp", False),
    "b31_same_cp": Scenario("b31_same_cp", True),
    "b31_cross_cp": Scenario("b31_cross_cp", False),
}


def _counterparty(cp_ref: str) -> dict:
    return {
        "counterparty_reference": cp_ref,
        "counterparty_name": f"P1.238 SA Corporate ({cp_ref})",
        "entity_type": "corporate",
        "country_code": "GB",
        "default_status": False,
        "is_financial_sector_entity": False,
        "apply_fi_scalar": False,
    }


def _loan(ref: str, cp_ref: str, drawn: float, reporting_date: date, agreement_ref: str) -> dict:
    return {
        "loan_reference": ref,
        "counterparty_reference": cp_ref,
        "currency": "GBP",
        "value_date": reporting_date,
        "maturity_date": reporting_date + relativedelta(years=3),
        "drawn_amount": drawn,
        "interest": 0.0,
        "seniority": "senior",
        "netting_agreement_reference": agreement_ref,
    }


def build_p1_238_bundle(scenario_labels: list[str], reporting_date: date) -> RawDataBundle:
    """Assemble an in-memory RawDataBundle for the named P1.238 scenarios."""
    scenarios = [SCENARIOS[label] for label in scenario_labels]

    cp_refs: list[str] = []
    for s in scenarios:
        cp_refs.append(s.deposit_cp)
        if not s.same_counterparty:
            cp_refs.append(s.loan_cp)
    counterparties = pl.DataFrame(
        [_counterparty(ref) for ref in dict.fromkeys(cp_refs)],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )

    loan_rows: list[dict] = []
    for s in scenarios:
        loan_rows.append(
            _loan(s.deposit_ref, s.deposit_cp, DEPOSIT_BALANCE, reporting_date, s.agreement_ref)
        )
        loan_rows.append(_loan(s.loan_ref, s.loan_cp, LOAN_DRAWN, reporting_date, s.agreement_ref))
    loans = pl.DataFrame(loan_rows, schema=dtypes_of(LOAN_SCHEMA))

    return make_raw_bundle(
        counterparties=counterparties,
        loans=loans,
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
    )
