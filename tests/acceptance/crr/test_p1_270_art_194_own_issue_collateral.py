"""
P1.270 CRR — Art. 194(4): own-issue / connected-issuer collateral is ineligible.

Scenario: £10m unrated SA corporate loan (100% RW) secured by a £10m CQS1
corporate bond. Everything is held constant except the bond's issuer:

    crr_third_party — bond issued by an unrelated bank -> recognised, EAD/RWA fall
    crr_own_issue   — bond issued by the obligor itself -> zeroed, RWA stays gross
                      and a CRM015 data-quality warning is raised.

References:
    - CRR Art. 194(4): correlation / connected-issuer ineligibility.
    - CRR Art. 122: unrated corporate 100% risk weight.
    - IMPLEMENTATION_PLAN.md: P1.270.
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.acceptance.p1_190_pipeline_helpers import find_loan_rows
from tests.fixtures.p1_270.p1_270 import GROSS_RWA, SCENARIOS, build_p1_270_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_OWN_ISSUE_COLLATERAL
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

REPORTING_DATE = date(2026, 6, 30)


def _run(scenario_label: str):
    bundle = build_p1_270_bundle([scenario_label], REPORTING_DATE)
    config = CalculationConfig.crr(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _rwa(result, loan_ref: str) -> float:
    rows = find_loan_rows(result, loan_ref)
    assert rows, f"P1.270: no result rows for {loan_ref}"
    return sum(r["rwa_final"] for r in rows if r.get("rwa_final") is not None)


def _crm015(result) -> list:
    return [e for e in result.errors if e.code == ERROR_OWN_ISSUE_COLLATERAL]


class TestP1270CrrOwnIssue:
    """CRR: collateral issued by the obligor is stripped of CRM benefit."""

    def test_third_party_bond_reduces_rwa(self) -> None:
        """Control: a third-party bond reduces RWA below the £10m gross value."""
        result = _run("crr_third_party")
        assert _rwa(result, SCENARIOS["crr_third_party"].loan_ref) < GROSS_RWA
        assert _crm015(result) == []

    def test_own_issue_bond_no_benefit(self) -> None:
        """LOAD-BEARING: an own-issued bond is zeroed → RWA stays at the £10m gross."""
        result = _run("crr_own_issue")
        assert _rwa(result, SCENARIOS["crr_own_issue"].loan_ref) == pytest.approx(
            GROSS_RWA, rel=1e-3
        )

    def test_own_issue_emits_crm015(self) -> None:
        """The own-issue case raises exactly one CRM015 warning."""
        result = _run("crr_own_issue")
        warnings = _crm015(result)
        assert len(warnings) == 1
        assert warnings[0].regulatory_reference == "CRR Art. 194(4)"

    def test_own_issue_rwa_exceeds_third_party(self) -> None:
        """The issuer flag alone must change RWA (guards against a no-op gate)."""
        own = _rwa(_run("crr_own_issue"), SCENARIOS["crr_own_issue"].loan_ref)
        third = _rwa(_run("crr_third_party"), SCENARIOS["crr_third_party"].loan_ref)
        assert own > third
