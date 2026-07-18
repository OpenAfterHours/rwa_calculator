"""
Generate P1.238 fixtures: Art. 195 same-counterparty on-B/S netting constraint.

CRR/PS1-26 Art. 195 limits on-balance-sheet netting to reciprocal balances
between the institution and a SINGLE counterparty. Each scenario carries a £200k
deposit (a negative-drawn loan) and a £1m positive loan under the same netting
agreement AGR1; only the loan's counterparty differs:

    <regime>_same_cp   — loan owed by the deposit's counterparty  -> nets, EAD £800k
    <regime>_cross_cp  — loan owed by a DIFFERENT counterparty     -> no netting, EAD £1m
                         (and one CRM016 data-quality warning)

Both counterparties are unrated corporates (100% SA risk weight), so the RWA
equals the post-netting EAD.

The bundle is assembled IN MEMORY (no parquet dependency), so the acceptance
tests are reproducible on a fresh checkout.

References:
    - CRR/PS1-26 Art. 195: on-B/S netting — single counterparty.
    - CRR Art. 219: drawn-on-drawn cash netting.
    - CRR Art. 122: unrated corporate 100% risk weight.
    - IMPLEMENTATION_PLAN.md: P1.238.
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
RWA_SAME_CP_NETTED: float = 800_000.00  # (£1m − £200k) × 100%


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
    def expected_loan_rwa(self) -> float:
        return RWA_SAME_CP_NETTED if self.same_counterparty else RWA_NO_NETTING


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


def _loan(ref: str, cp_ref: str, drawn: float, reporting_date: date) -> dict:
    return {
        "loan_reference": ref,
        "counterparty_reference": cp_ref,
        "currency": "GBP",
        "value_date": reporting_date,
        "maturity_date": reporting_date + relativedelta(years=3),
        "drawn_amount": drawn,
        "interest": 0.0,
        "seniority": "senior",
        "netting_agreement_reference": AGREEMENT_REF,
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
        loan_rows.append(_loan(s.deposit_ref, s.deposit_cp, DEPOSIT_BALANCE, reporting_date))
        loan_rows.append(_loan(s.loan_ref, s.loan_cp, LOAN_DRAWN, reporting_date))
    loans = pl.DataFrame(loan_rows, schema=dtypes_of(LOAN_SCHEMA))

    return make_raw_bundle(
        counterparties=counterparties,
        loans=loans,
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
    )
