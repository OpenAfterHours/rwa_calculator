"""
P1.270 fixtures: Art. 194(4) own-issue / connected-issuer collateral gate.

CRR/PS1-26 Art. 194(4) makes funded protection ineligible where its value is
materially positively correlated with the obligor's credit quality — the
canonical case (BCBS CRE22) being a security ISSUED by the obligor. Each scenario
is an unrated SA corporate loan (100% RW) secured by a £10m CQS1 corporate bond;
only the bond's ``issuer_counterparty_reference`` differs:

    <regime>_own_issue    — bond issued by the obligor  -> excluded, RWA stays gross
    <regime>_third_party  — bond issued by an unrelated bank -> recognised, RWA falls

Own-issue also raises one CRM015 data-quality warning.

The bundle is assembled IN MEMORY (mirroring P1.234) — no parquet dependency, so
the acceptance tests are reproducible on a fresh checkout without a fixture-
generation step.

References:
    - CRR/PS1-26 Art. 194(4): correlation / connected-issuer ineligibility.
    - BCBS CRE22: own-issued securities expressly ineligible.
    - CRR Art. 224 Table 1: corporate bond supervisory haircut.
    - CRR Art. 122: unrated corporate 100% risk weight.
    - IMPLEMENTATION_PLAN.md: P1.270.
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

DRAWN_AMOUNT: float = 10_000_000.00
COLLATERAL_MV: float = 10_000_000.00
GROSS_RWA: float = 10_000_000.00  # £10m EAD × 100% unrated-corporate RW, no benefit
THIRD_PARTY_ISSUER = "P1270-BANK-X"


@dataclass(frozen=True)
class Scenario:
    """One P1.270 acceptance scenario."""

    label: str
    issuer_is_obligor: bool

    @property
    def cp_ref(self) -> str:
        return f"P1270-CP-{self.label}"

    @property
    def loan_ref(self) -> str:
        return f"P1270-L-{self.label}"

    @property
    def coll_ref(self) -> str:
        return f"P1270-C-{self.label}"

    @property
    def issuer_ref(self) -> str:
        return self.cp_ref if self.issuer_is_obligor else THIRD_PARTY_ISSUER


SCENARIOS: dict[str, Scenario] = {
    "crr_own_issue": Scenario("crr_own_issue", True),
    "crr_third_party": Scenario("crr_third_party", False),
    "b31_own_issue": Scenario("b31_own_issue", True),
    "b31_third_party": Scenario("b31_third_party", False),
}

CRR_SCENARIOS = ["crr_own_issue", "crr_third_party"]
B31_SCENARIOS = ["b31_own_issue", "b31_third_party"]


def _counterparty(s: Scenario) -> dict:
    return {
        "counterparty_reference": s.cp_ref,
        "counterparty_name": f"P1.270 SA Corporate ({s.label})",
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
    """A CQS1 corporate bond pledged at loan level; issuer set per scenario."""
    return {
        "collateral_reference": s.coll_ref,
        "collateral_type": "bond",
        "currency": "GBP",
        "market_value": COLLATERAL_MV,
        "beneficiary_type": "loan",
        "beneficiary_reference": s.loan_ref,
        "issuer_type": "corporate",
        "issuer_cqs": 1,
        "is_eligible_financial_collateral": True,
        "is_eligible_irb_collateral": True,
        "issuer_counterparty_reference": s.issuer_ref,
        "residual_maturity_years": 10.0,
        "original_maturity_years": 10.0,
        "liquidation_period_days": 10,
    }


def build_p1_270_bundle(scenario_labels: list[str], reporting_date: date) -> RawDataBundle:
    """Assemble an in-memory RawDataBundle for the named P1.270 scenarios."""
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
