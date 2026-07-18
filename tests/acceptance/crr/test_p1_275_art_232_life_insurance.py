"""
P1.275 CRR — Art. 232(3)/233(3): life-insurance collateral FX reduction + multi-level pledge.

A £1m unrated SA corporate loan (100% RW) secured by a pledged life-insurance
policy (insurer RW 20% -> secured RW 20%):

    matched       — policy GBP £500k, no FX cut -> blended 0.60 -> RWA £600k.
    fx_mismatch   — policy USD £500k, Art. 233(3) 8% cut -> blended 0.632 -> RWA £632k.
    null_currency — policy currency null -> conservative 8% cut (CRM020) -> RWA £632k.
    counterparty  — two loans (£600k + £400k) under one counterparty, a £1m GBP
                    policy pledged at COUNTERPARTY level -> pro-rata -> RWA £200k.

References:
    - CRR Art. 232(3): pledged life-insurance policy as other funded protection.
    - CRR Art. 233(3): 8% FX volatility haircut on the protection value.
    - IMPLEMENTATION_PLAN.md: P1.275.
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.acceptance.p1_190_pipeline_helpers import find_loan_rows
from tests.fixtures.p1_275.p1_275 import SCENARIOS, build_p1_275_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_LIFE_INSURANCE_CURRENCY_UNKNOWN
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

REPORTING_DATE = date(2025, 12, 31)


def _run(scenario_label: str):
    bundle = build_p1_275_bundle(scenario_label, REPORTING_DATE)
    config = CalculationConfig.crr(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _scenario_rwa(result, scenario_label: str) -> float:
    total = 0.0
    for loan in SCENARIOS[scenario_label].loans:
        rows = find_loan_rows(result, loan.ref)
        assert rows, f"P1.275 CRR: no result rows for {loan.ref}"
        total += sum(r["rwa_final"] for r in rows if r.get("rwa_final") is not None)
    return total


def _crm020(result) -> list:
    return [e for e in result.errors if e.code == ERROR_LIFE_INSURANCE_CURRENCY_UNKNOWN]


class TestP1275CRRLifeInsurance:
    """CRR: the pledged life-insurance policy maps to a 20% secured RW, reduced 8% on FX."""

    def test_matched_currency_baseline(self) -> None:
        """Control: GBP policy, no FX cut -> secured 0.5 at 20% -> blended 0.60 -> £600k."""
        assert _scenario_rwa(_run("matched"), "matched") == pytest.approx(
            SCENARIOS["matched"].expected_rwa, rel=1e-6
        )

    def test_fx_mismatch_takes_8pct_reduction(self) -> None:
        """LOAD-BEARING: USD policy -> Art. 233(3) 8% cut -> effective £460k -> £632k > £600k."""
        rwa = _scenario_rwa(_run("fx_mismatch"), "fx_mismatch")
        assert rwa == pytest.approx(SCENARIOS["fx_mismatch"].expected_rwa, rel=1e-6)
        assert rwa > SCENARIOS["matched"].expected_rwa

    def test_null_currency_conservative_cut_and_warning(self) -> None:
        """A null policy currency cannot prove a match -> 8% cut + one CRM020 warning."""
        result = _run("null_currency")
        assert _scenario_rwa(result, "null_currency") == pytest.approx(
            SCENARIOS["null_currency"].expected_rwa, rel=1e-6
        )
        assert len(_crm020(result)) == 1

    def test_counterparty_level_pledge_flows_pro_rata(self) -> None:
        """LOAD-BEARING: a counterparty-level policy benefits BOTH loans pro-rata -> £200k."""
        result = _run("counterparty")
        rwa = _scenario_rwa(result, "counterparty")
        assert rwa == pytest.approx(SCENARIOS["counterparty"].expected_rwa, rel=1e-6)
        # Both loans individually receive the 20% secured RW (fully covered).
        for loan in SCENARIOS["counterparty"].loans:
            rows = find_loan_rows(result, loan.ref)
            rwa_loan = sum(r["rwa_final"] for r in rows if r.get("rwa_final") is not None)
            assert rwa_loan == pytest.approx(loan.drawn * 0.20, rel=1e-6)
