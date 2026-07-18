"""
P1.271 CRR — Art. 197(1)(f)/198(1)(a): non-main-index equity eligibility gate.

Scenario: £1m unrated SA corporate loan (100% RW) secured by £500k of NON-main-
index equity. Everything is held constant except the equity's is_listed flag:

    crr_listed    — listed on a recognised exchange -> recognised at the 25%
                    other-listed haircut, EAD/RWA fall to £625k.
    crr_unlisted  — listing unreported (null)        -> ineligible, RWA stays at
                    the £1m gross and a CRM018 data-quality warning is raised.

References:
    - CRR Art. 197(1)(f): main-index equities eligible under all methods.
    - CRR Art. 198(1)(a): non-main-index equities eligible only if listed.
    - CRR Art. 224 Table 4: other-listed equity 25% haircut.
    - CRR Art. 122: unrated corporate 100% risk weight.
    - IMPLEMENTATION_PLAN.md: P1.271.
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.acceptance.p1_190_pipeline_helpers import find_loan_rows
from tests.fixtures.p1_271.p1_271 import (
    CRR_LISTED_RWA,
    GROSS_RWA,
    SCENARIOS,
    build_p1_271_bundle,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_NON_MAIN_INDEX_EQUITY_INELIGIBLE
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

REPORTING_DATE = date(2026, 6, 30)


def _run(scenario_label: str):
    bundle = build_p1_271_bundle([scenario_label], REPORTING_DATE)
    config = CalculationConfig.crr(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _rwa(result, loan_ref: str) -> float:
    rows = find_loan_rows(result, loan_ref)
    assert rows, f"P1.271: no result rows for {loan_ref}"
    return sum(r["rwa_final"] for r in rows if r.get("rwa_final") is not None)


def _crm018(result) -> list:
    return [e for e in result.errors if e.code == ERROR_NON_MAIN_INDEX_EQUITY_INELIGIBLE]


class TestP1271CrrNonMainIndexEquity:
    """CRR: non-main-index equity is recognised only if attested listed."""

    def test_listed_equity_reduces_rwa(self) -> None:
        """Control: listed other-listed equity reduces RWA to £625k (25% haircut)."""
        result = _run("crr_listed")
        assert _rwa(result, SCENARIOS["crr_listed"].loan_ref) == pytest.approx(
            CRR_LISTED_RWA, rel=1e-6
        )
        assert _crm018(result) == []

    def test_unlisted_equity_no_benefit(self) -> None:
        """LOAD-BEARING: unlisted non-main-index equity is zeroed → RWA stays gross."""
        result = _run("crr_unlisted")
        assert _rwa(result, SCENARIOS["crr_unlisted"].loan_ref) == pytest.approx(
            GROSS_RWA, rel=1e-6
        )

    def test_unlisted_equity_emits_crm018(self) -> None:
        """The unlisted case raises exactly one CRM018 warning."""
        result = _run("crr_unlisted")
        warnings = _crm018(result)
        assert len(warnings) == 1
        assert warnings[0].regulatory_reference == "CRR/PS1-26 Art. 197(1)(f)/198(1)(a)"

    def test_unlisted_rwa_exceeds_listed(self) -> None:
        """The listing flag alone must change RWA (guards against a no-op gate)."""
        unlisted = _rwa(_run("crr_unlisted"), SCENARIOS["crr_unlisted"].loan_ref)
        listed = _rwa(_run("crr_listed"), SCENARIOS["crr_listed"].loan_ref)
        assert unlisted > listed
