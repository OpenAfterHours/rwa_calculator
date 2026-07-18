"""
Generate P1.239/P1.240 fixtures: Art. 200(a)/232(2) third-party deposit treatment.

A £1m unrated SA corporate loan (100% RW) secured by a £400k cash deposit. The
deposit's `held_by_counterparty_reference` and `issuer_cqs` (the holder
institution's CQS) drive the treatment:

    own_bank        — null holder -> own-bank cash, 0% haircut, EAD reduced to £600k
                      -> RWA £600k (unchanged from today).
    third_party_cqs2 — held at a CQS2 institution -> Art. 232(2) substitution:
                      covered part (0.4) at the holder RW, no EAD reduction.
                      CRR holder RW 50% -> blended 0.8 -> RWA £800k.
                      B31 ECRA holder RW 30% -> blended 0.72 -> RWA £720k.
    third_party_unrated — held at an unrated institution.
                      CRR unrated institution RW 100% -> blended 1.0 (benefit-only
                      cap: no benefit) -> RWA £1,000k.
                      B31 unrated institution RW 40% -> blended 0.76 -> RWA £760k.

The bundle is assembled IN MEMORY (no parquet dependency).

References:
    - CRR Art. 200(a)/232(2) with Art. 212(1): third-party deposit as a guarantee.
    - CRR Art. 120/121 (PS1/26 Art. 120A ECRA): institution risk weights by CQS.
    - IMPLEMENTATION_PLAN.md: P1.239, P1.240.
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

LOAN_DRAWN: float = 1_000_000.00
DEPOSIT_VALUE: float = 400_000.00
HOLDER_REF = "P1239-BANK-H"


@dataclass(frozen=True)
class Scenario:
    """One P1.239 acceptance scenario."""

    label: str
    held_by: str | None
    issuer_cqs: int | None
    expected_rwa: float
    issuer_type: str = "institution"

    @property
    def cp_ref(self) -> str:
        return f"P1239-CP-{self.label}"

    @property
    def loan_ref(self) -> str:
        return f"P1239-LN-{self.label}"


SCENARIOS: dict[str, Scenario] = {
    "crr_own_bank": Scenario("crr_own_bank", None, None, 600_000.00),
    "crr_third_party_cqs2": Scenario("crr_third_party_cqs2", HOLDER_REF, 2, 800_000.00),
    # CRR unrated institution RW is 100% → benefit-only cap → no benefit (but not 0% cash).
    "crr_third_party_unrated": Scenario("crr_third_party_unrated", HOLDER_REF, None, 1_000_000.00),
    # Non-institution holder is out of Art. 232(2) scope → no benefit + CRM017.
    "crr_non_institution": Scenario(
        "crr_non_institution", HOLDER_REF, 2, 1_000_000.00, issuer_type="corporate"
    ),
    "b31_own_bank": Scenario("b31_own_bank", None, None, 600_000.00),
    "b31_third_party_cqs2": Scenario("b31_third_party_cqs2", HOLDER_REF, 2, 720_000.00),
    # B31 unrated institution → SCRA Grade-C 150% fallback → benefit-only cap → no benefit.
    "b31_third_party_unrated": Scenario("b31_third_party_unrated", HOLDER_REF, None, 1_000_000.00),
    "b31_non_institution": Scenario(
        "b31_non_institution", HOLDER_REF, 2, 1_000_000.00, issuer_type="corporate"
    ),
}


def _counterparty(s: Scenario) -> dict:
    return {
        "counterparty_reference": s.cp_ref,
        "counterparty_name": f"P1.239 SA Corporate ({s.label})",
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
        "drawn_amount": LOAN_DRAWN,
        "interest": 0.0,
        "seniority": "senior",
    }


def _collateral(s: Scenario) -> dict:
    return {
        "collateral_reference": f"P1239-DEP-{s.label}",
        "collateral_type": "cash",
        "currency": "GBP",
        "market_value": DEPOSIT_VALUE,
        "beneficiary_type": "loan",
        "beneficiary_reference": s.loan_ref,
        "issuer_type": s.issuer_type,
        "issuer_cqs": s.issuer_cqs,
        "is_eligible_financial_collateral": True,
        "held_by_counterparty_reference": s.held_by,
    }


def build_p1_239_bundle(scenario_labels: list[str], reporting_date: date) -> RawDataBundle:
    """Assemble an in-memory RawDataBundle for the named P1.239 scenarios."""
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
