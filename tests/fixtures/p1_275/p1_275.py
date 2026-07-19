"""
Generate P1.275 fixtures: Art. 232(3)/233(3) life-insurance collateral treatment.

A £1m unrated SA corporate loan (100% RW) secured by a pledged life-insurance
policy. The policy's ``insurer_risk_weight`` maps to a secured-portion RW
(Art. 232(3)); the surrender value is reduced by the Art. 233(3) 8% FX
volatility haircut on a currency mismatch:

    matched      — policy GBP £500k, insurer RW 20% -> secured RW 20%, no FX cut.
                   secured 0.5 -> blended 0.5*0.20 + 0.5*1.00 = 0.60 -> RWA £600k.
    fx_mismatch  — policy USD £500k (no FX rate -> value unconverted), 8% cut ->
                   effective £460k, secured 0.46 -> blended 0.632 -> RWA £632k.
    null_currency — policy currency null -> conservative 8% cut (CRM020) -> £632k.
    counterparty  — TWO loans (£600k + £400k) under one counterparty, a single
                   £1m GBP policy pledged at COUNTERPARTY level (insurer RW 20%).
                   Shared pro-rata by EAD -> each fully secured at 20% ->
                   RWA £600k*0.20 + £400k*0.20 = £200k (vs £1,000k unprotected).

Art. 232(3) and Art. 233(3) are retained unchanged under PS1/26 (the 8% Hfx is
regime-invariant), so the CRR and Basel 3.1 expectations are identical. The
bundle is assembled IN MEMORY (no parquet dependency).

References:
    - CRR Art. 232(3): pledged life-insurance policy as other funded protection.
    - CRR Art. 233(3): 8% FX volatility haircut on the protection value.
    - IMPLEMENTATION_PLAN.md: P1.275.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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

POLICY_VALUE: float = 500_000.00
INSURER_RW: float = 0.20  # -> secured-portion RW 20% (Art. 232(3))


@dataclass(frozen=True)
class Loan:
    """One loan leg within a P1.275 scenario."""

    ref: str
    drawn: float


@dataclass(frozen=True)
class Scenario:
    """One P1.275 acceptance scenario (one counterparty, one pledged policy)."""

    label: str
    loans: tuple[Loan, ...]
    pledge_ref: str
    policy_value: float
    policy_currency: str | None
    expected_rwa: float
    beneficiary_type: str = "loan"
    expects_crm020: bool = False
    loan_prefix: str = field(default="")

    @property
    def cp_ref(self) -> str:
        return f"P1275-CP-{self.label}"


SCENARIOS: dict[str, Scenario] = {
    "matched": Scenario(
        "matched",
        (Loan("P1275-LN-matched", 1_000_000.00),),
        pledge_ref="P1275-LN-matched",
        policy_value=POLICY_VALUE,
        policy_currency="GBP",
        expected_rwa=600_000.00,
    ),
    "fx_mismatch": Scenario(
        "fx_mismatch",
        (Loan("P1275-LN-fx", 1_000_000.00),),
        pledge_ref="P1275-LN-fx",
        policy_value=POLICY_VALUE,
        policy_currency="USD",
        expected_rwa=632_000.00,
    ),
    "null_currency": Scenario(
        "null_currency",
        (Loan("P1275-LN-null", 1_000_000.00),),
        pledge_ref="P1275-LN-null",
        policy_value=POLICY_VALUE,
        policy_currency=None,
        expected_rwa=632_000.00,
        expects_crm020=True,
    ),
    "counterparty": Scenario(
        "counterparty",
        (Loan("P1275-LN-cp-A", 600_000.00), Loan("P1275-LN-cp-B", 400_000.00)),
        pledge_ref="",  # filled to the counterparty reference in the builder
        policy_value=1_000_000.00,
        policy_currency="GBP",
        expected_rwa=200_000.00,
        beneficiary_type="counterparty",
    ),
}


def _counterparty(s: Scenario) -> dict:
    return {
        "counterparty_reference": s.cp_ref,
        "counterparty_name": f"P1.275 SA Corporate ({s.label})",
        "entity_type": "corporate",
        "country_code": "GB",
        "default_status": False,
        "is_financial_sector_entity": False,
        "apply_fi_scalar": False,
    }


def _loan(loan: Loan, s: Scenario, reporting_date: date) -> dict:
    return {
        "loan_reference": loan.ref,
        "counterparty_reference": s.cp_ref,
        "currency": "GBP",
        "value_date": reporting_date,
        "maturity_date": reporting_date + relativedelta(years=3),
        "drawn_amount": loan.drawn,
        "interest": 0.0,
        "seniority": "senior",
    }


def _collateral(s: Scenario) -> dict:
    beneficiary_ref = s.cp_ref if s.beneficiary_type == "counterparty" else s.pledge_ref
    return {
        "collateral_reference": f"P1275-POL-{s.label}",
        "collateral_type": "life_insurance",
        "currency": s.policy_currency,
        "market_value": s.policy_value,
        "beneficiary_type": s.beneficiary_type,
        "beneficiary_reference": beneficiary_ref,
        "insurer_risk_weight": INSURER_RW,
        # Life-insurance policies are NOT eligible financial collateral: they use the
        # Art. 232(3) RW-mapping side channel, not the comprehensive EAD reduction.
        "is_eligible_financial_collateral": False,
    }


def build_p1_275_bundle(scenario_label: str, reporting_date: date) -> RawDataBundle:
    """Assemble an in-memory RawDataBundle for the named P1.275 scenario."""
    s = SCENARIOS[scenario_label]
    counterparties = pl.DataFrame([_counterparty(s)], schema=dtypes_of(COUNTERPARTY_SCHEMA))
    loans = pl.DataFrame(
        [_loan(loan, s, reporting_date) for loan in s.loans], schema=dtypes_of(LOAN_SCHEMA)
    )
    collateral = pl.DataFrame([_collateral(s)], schema=dtypes_of(COLLATERAL_SCHEMA))
    return make_raw_bundle(
        counterparties=counterparties,
        loans=loans,
        collateral=collateral,
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
    )
