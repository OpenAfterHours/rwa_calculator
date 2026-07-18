"""
P1.274 Basel 3.1 — PS1/26 Art. 218 (retained): credit-linked-note own-issuance gate.

Scenario: £1m unrated SA corporate loan (100% RW) secured by £500k of credit-
linked note collateral. Everything is held constant except the note's
is_own_issued_cln attestation:

    b31_own_issued  — attested issued by the lending institution -> cash
                      treatment (0% haircut), EAD/RWA fall to £500k.
    b31_third_party — own-issuance unattested (null)             -> ineligible,
                      RWA stays at the £1m gross and a CRM019 data-quality
                      warning is raised.

Art. 218 is regime-identical (PS1/26 retains the CRR text), so the numbers match
the CRR twin.

References:
    - PS1/26 Art. 218: own-issued credit-linked note treated as cash collateral.
    - PS1/26 Art. 194(4): funded protection ineligible when materially positively
      correlated with the obligor (a third-party CLN's reference entity).
    - PS1/26 Art. 122: unrated corporate 100% risk weight.
    - IMPLEMENTATION_PLAN.md: P1.274.
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_CREDIT_LINKED_NOTE_NOT_OWN_ISSUED
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.p1_190_pipeline_helpers import find_loan_rows
from tests.fixtures.p1_274.p1_274 import (
    GROSS_RWA,
    OWN_ISSUED_RWA,
    SCENARIOS,
    build_p1_274_bundle,
)

REPORTING_DATE = date(2027, 6, 30)


def _run(scenario_label: str):
    bundle = build_p1_274_bundle([scenario_label], REPORTING_DATE)
    config = CalculationConfig.basel_3_1(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _rwa(result, loan_ref: str) -> float:
    rows = find_loan_rows(result, loan_ref)
    assert rows, f"P1.274: no result rows for {loan_ref}"
    return sum(r["rwa_final"] for r in rows if r.get("rwa_final") is not None)


def _crm019(result) -> list:
    return [e for e in result.errors if e.code == ERROR_CREDIT_LINKED_NOTE_NOT_OWN_ISSUED]


class TestP1274B31CreditLinkedNote:
    """Basel 3.1: a credit-linked note is cash collateral only if attested own-issued."""

    def test_own_issued_cln_reduces_rwa(self) -> None:
        """Control: own-issued CLN gets cash treatment, RWA falls to £500k."""
        result = _run("b31_own_issued")
        assert _rwa(result, SCENARIOS["b31_own_issued"].loan_ref) == pytest.approx(
            OWN_ISSUED_RWA, rel=1e-6
        )
        assert _crm019(result) == []

    def test_third_party_cln_no_benefit(self) -> None:
        """LOAD-BEARING: third-party CLN is zeroed → RWA stays gross."""
        result = _run("b31_third_party")
        assert _rwa(result, SCENARIOS["b31_third_party"].loan_ref) == pytest.approx(
            GROSS_RWA, rel=1e-6
        )

    def test_third_party_cln_emits_crm019(self) -> None:
        """The third-party case raises exactly one CRM019 warning."""
        result = _run("b31_third_party")
        warnings = _crm019(result)
        assert len(warnings) == 1
        assert warnings[0].regulatory_reference == "CRR/PS1-26 Art. 218"

    def test_third_party_rwa_exceeds_own_issued(self) -> None:
        """The own-issue flag alone must change RWA (guards against a no-op gate)."""
        third_party = _rwa(_run("b31_third_party"), SCENARIOS["b31_third_party"].loan_ref)
        own_issued = _rwa(_run("b31_own_issued"), SCENARIOS["b31_own_issued"].loan_ref)
        assert third_party > own_issued
