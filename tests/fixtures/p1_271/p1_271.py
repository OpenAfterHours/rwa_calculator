"""
P1.271 fixtures: Art. 197(1)(f)/198(1)(a) non-main-index equity eligibility gate.

CRR/PS1-26 Art. 197(1)(f) makes equities/convertible bonds included in a MAIN
index eligible financial collateral under all methods. Art. 198(1)(a) extends
eligibility to non-main-index equities only where they are LISTED on a recognised
exchange, and only under the (comprehensive) financial-collateral method this
calculator uses by default. A non-main-index equity that is not attested listed is
therefore ineligible.

Each scenario is a £1m unrated SA corporate loan (100% RW) secured by £500k of
NON-main-index equity (``is_main_index`` unset); only the equity's ``is_listed``
attestation differs:

    <regime>_listed    — listed on a recognised exchange -> recognised, RWA falls
    <regime>_unlisted  — listing unreported (null)        -> ineligible, RWA stays
                         gross and a CRM018 data-quality warning is raised.

The bundle is assembled IN MEMORY (mirroring P1.234/P1.270) — no parquet
dependency, so the acceptance tests are reproducible on a fresh checkout without a
fixture-generation step.

References:
    - CRR/PS1-26 Art. 197(1)(f): main-index equities eligible under all methods.
    - CRR/PS1-26 Art. 198(1)(a): non-main-index equities eligible only if listed on
      a recognised exchange (comprehensive method).
    - CRR Art. 224 Table 3/4: equity supervisory haircut (other-listed 25%/30%).
    - CRR Art. 122: unrated corporate 100% risk weight.
    - IMPLEMENTATION_PLAN.md: P1.271.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl
from dateutil.relativedelta import relativedelta

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    LOAN_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

DRAWN_AMOUNT: float = 1_000_000.00
COLLATERAL_MV: float = 500_000.00
GROSS_RWA: float = 1_000_000.00  # £1m EAD × 100% unrated-corporate RW, no benefit
# Listed other-listed equity: 25% haircut (CRR) / 30% (Basel 3.1) → EAD reductions.
CRR_LISTED_RWA: float = 625_000.00  # 1m − 500k × (1 − 0.25)
B31_LISTED_RWA: float = 650_000.00  # 1m − 500k × (1 − 0.30)


@dataclass(frozen=True)
class Scenario:
    """One P1.271 acceptance scenario."""

    label: str
    is_listed: bool | None

    @property
    def cp_ref(self) -> str:
        return f"P1271-CP-{self.label}"

    @property
    def loan_ref(self) -> str:
        return f"P1271-L-{self.label}"

    @property
    def coll_ref(self) -> str:
        return f"P1271-C-{self.label}"


SCENARIOS: dict[str, Scenario] = {
    "crr_listed": Scenario("crr_listed", True),
    "crr_unlisted": Scenario("crr_unlisted", None),
    "b31_listed": Scenario("b31_listed", True),
    "b31_unlisted": Scenario("b31_unlisted", None),
}

CRR_SCENARIOS = ["crr_listed", "crr_unlisted"]
B31_SCENARIOS = ["b31_listed", "b31_unlisted"]


def _counterparty(s: Scenario) -> dict:
    return {
        "counterparty_reference": s.cp_ref,
        "counterparty_name": f"P1.271 SA Corporate ({s.label})",
        "entity_type": "corporate",
        "country_code": "GB",
        "default_status": False,
        "is_financial_sector_entity": False,
        "apply_fi_scalar": False,
    }


def _loan(s: Scenario, reporting_date: date) -> dict:
    return {
        "loan_reference": s.loan_ref,
        "counterparty_reference": s.cp_ref,
        "currency": "GBP",
        "value_date": reporting_date,
        "maturity_date": reporting_date + relativedelta(years=3),
        "drawn_amount": DRAWN_AMOUNT,
        "interest": 0.0,
        "seniority": "senior",
    }


def _collateral(s: Scenario) -> dict:
    """£500k non-main-index equity pledged at loan level; listing per scenario."""
    return {
        "collateral_reference": s.coll_ref,
        "collateral_type": "equity",
        "currency": "GBP",
        "market_value": COLLATERAL_MV,
        "beneficiary_type": "loan",
        "beneficiary_reference": s.loan_ref,
        "issuer_type": "corporate",
        "is_eligible_financial_collateral": True,
        "is_eligible_irb_collateral": True,
        # NON-main-index: is_main_index deliberately left null. Only is_listed
        # varies across scenarios (the Art. 198(1)(a) eligibility condition).
        "is_listed": s.is_listed,
        "liquidation_period_days": 10,
    }


def build_p1_271_bundle(scenario_labels: list[str], reporting_date: date) -> RawDataBundle:
    """Assemble an in-memory RawDataBundle for the named P1.271 scenarios."""
    scenarios = [SCENARIOS[label] for label in scenario_labels]
    counterparties = pl.DataFrame(
        [_counterparty(s) for s in scenarios], schema=dtypes_of(COUNTERPARTY_SCHEMA)
    )
    loans = pl.DataFrame(
        [_loan(s, reporting_date) for s in scenarios], schema=dtypes_of(LOAN_SCHEMA)
    )
    collateral = pl.DataFrame(
        [_collateral(s) for s in scenarios], schema=dtypes_of(COLLATERAL_SCHEMA)
    )
    return make_raw_bundle(
        counterparties=counterparties,
        loans=loans,
        collateral=collateral,
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
    )
