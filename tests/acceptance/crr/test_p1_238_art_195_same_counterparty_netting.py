"""
P1.238 CRR — Art. 195: on-B/S netting is limited to a single counterparty.

Scenario: a £200k deposit (negative-drawn loan) and a £1m loan share netting
agreement AGR1. Only the loan's counterparty differs:

    crr_same_cp  — loan owed by the deposit's counterparty  -> nets, RWA £800k
    crr_cross_cp — loan owed by a DIFFERENT counterparty     -> no netting, RWA £1m
                   (plus one CRM016 data-quality warning)

References:
    - CRR Art. 195: on-B/S netting — single counterparty.
    - CRR Art. 122: unrated corporate 100% risk weight.
    - IMPLEMENTATION_PLAN.md: P1.238.
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.acceptance.p1_190_pipeline_helpers import find_loan_rows
from tests.fixtures.p1_238.p1_238 import SCENARIOS, build_p1_238_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_CROSS_COUNTERPARTY_NETTING
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

REPORTING_DATE = date(2026, 6, 30)


def _run(scenario_label: str):
    bundle = build_p1_238_bundle([scenario_label], REPORTING_DATE)
    config = CalculationConfig.crr(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _loan_rwa(result, loan_ref: str) -> float:
    rows = find_loan_rows(result, loan_ref)
    assert rows, f"P1.238: no result rows for {loan_ref}"
    return sum(r["rwa_final"] for r in rows if r.get("rwa_final") is not None)


def _crm016(result) -> list:
    return [e for e in result.errors if e.code == ERROR_CROSS_COUNTERPARTY_NETTING]


class TestP1238CrrSameCounterpartyNetting:
    """CRR: a deposit nets only a same-counterparty loan (Art. 195)."""

    def test_same_counterparty_loan_nets(self) -> None:
        """Control: same-counterparty loan nets the £200k deposit → RWA £800k."""
        s = SCENARIOS["crr_same_cp"]
        result = _run("crr_same_cp")
        assert _loan_rwa(result, s.loan_ref) == pytest.approx(s.expected_loan_rwa, rel=1e-3)
        assert _crm016(result) == []

    def test_cross_counterparty_loan_not_netted(self) -> None:
        """LOAD-BEARING: a different-counterparty loan is NOT netted → full RWA £1m."""
        s = SCENARIOS["crr_cross_cp"]
        result = _run("crr_cross_cp")
        assert _loan_rwa(result, s.loan_ref) == pytest.approx(s.expected_loan_rwa, rel=1e-3)

    def test_cross_counterparty_emits_crm016(self) -> None:
        """The cross-counterparty agreement raises exactly one CRM016 warning."""
        result = _run("crr_cross_cp")
        warnings = _crm016(result)
        assert len(warnings) == 1
        assert warnings[0].regulatory_reference == "CRR Art. 195"

    def test_cross_exceeds_same(self) -> None:
        """The constraint alone must raise the loan's RWA (guards against a no-op)."""
        cross = _loan_rwa(_run("crr_cross_cp"), SCENARIOS["crr_cross_cp"].loan_ref)
        same = _loan_rwa(_run("crr_same_cp"), SCENARIOS["crr_same_cp"].loan_ref)
        assert cross > same
