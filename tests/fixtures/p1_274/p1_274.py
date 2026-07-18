"""P1.274 fixtures: Art. 218 credit-linked-note own-issuance eligibility gate.

CRR/PS1-26 Art. 218 (retained under Basel 3.1) treats a credit-linked note as
cash collateral (0% haircut, full EAD offset) ONLY where the note is issued by
the LENDING institution itself — the note's cash proceeds fund the protection. A
CLN issued by a THIRD PARTY is not within Art. 218: its value is materially
correlated with the reference entity (typically the obligor — Art. 194(4)
wrong-way risk), so it is ineligible funded protection.

Each scenario is a £1m unrated SA corporate loan (100% RW) secured by £500k of
credit-linked note collateral; only the note's ``is_own_issued_cln`` attestation
differs:

    <regime>_own_issued  — attested own-issued -> cash treatment, EAD/RWA fall to
                           £500k.
    <regime>_third_party — own-issuance unattested (null) -> ineligible, RWA stays
                           at the £1m gross and a CRM019 data-quality warning is
                           raised.

The bundle is assembled IN MEMORY (mirroring P1.270/P1.271) — no parquet
dependency, so the acceptance tests are reproducible on a fresh checkout without a
fixture-generation step.

References:
    - CRR/PS1-26 Art. 218: own-issued credit-linked note treated as cash collateral.
    - CRR/PS1-26 Art. 194(4): funded protection ineligible when materially
      positively correlated with the obligor (a third-party CLN's reference).
    - CRR Art. 122: unrated corporate 100% risk weight.
    - IMPLEMENTATION_PLAN.md: P1.274.
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
# Own-issued CLN: cash 0% haircut → £500k EAD offset (same under both regimes).
OWN_ISSUED_RWA: float = 500_000.00  # 1m − 500k × (1 − 0.0)


@dataclass(frozen=True)
class Scenario:
    """One P1.274 acceptance scenario."""

    label: str
    is_own_issued_cln: bool | None

    @property
    def cp_ref(self) -> str:
        return f"P1274-CP-{self.label}"

    @property
    def loan_ref(self) -> str:
        return f"P1274-L-{self.label}"

    @property
    def coll_ref(self) -> str:
        return f"P1274-C-{self.label}"


SCENARIOS: dict[str, Scenario] = {
    "crr_own_issued": Scenario("crr_own_issued", True),
    "crr_third_party": Scenario("crr_third_party", None),
    "b31_own_issued": Scenario("b31_own_issued", True),
    "b31_third_party": Scenario("b31_third_party", None),
}

CRR_SCENARIOS = ["crr_own_issued", "crr_third_party"]
B31_SCENARIOS = ["b31_own_issued", "b31_third_party"]


def _counterparty(s: Scenario) -> dict:
    return {
        "counterparty_reference": s.cp_ref,
        "counterparty_name": f"P1.274 SA Corporate ({s.label})",
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
    """£500k credit-linked note pledged at loan level; own-issuance per scenario."""
    return {
        "collateral_reference": s.coll_ref,
        "collateral_type": "credit_linked_note",
        "currency": "GBP",
        "market_value": COLLATERAL_MV,
        "beneficiary_type": "loan",
        "beneficiary_reference": s.loan_ref,
        # The issuing institution; only is_own_issued_cln attests whether that
        # issuer IS the lending institution (Art. 218).
        "issuer_type": "institution",
        "is_eligible_financial_collateral": True,
        "is_eligible_irb_collateral": True,
        "is_own_issued_cln": s.is_own_issued_cln,
        "liquidation_period_days": 10,
    }


def build_p1_274_bundle(scenario_labels: list[str], reporting_date: date) -> RawDataBundle:
    """Assemble an in-memory RawDataBundle for the named P1.274 scenarios."""
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
