"""
P1.239/P1.240 Basel 3.1 — Art. 200(a)/232(2): third-party deposit as a guarantee.

A £1m unrated SA corporate loan (100% RW) secured by a £400k cash deposit:

    b31_own_bank            — own-bank deposit (null holder) -> 0% cash, RWA £600k
    b31_third_party_cqs2    — held at a CQS2 institution (ECRA 30% RW) -> covered part
                              at 30%, no EAD reduction -> blended 0.72 -> RWA £720k
    b31_third_party_unrated — held at an unrated institution (40% RW) -> blended 0.76
                              -> RWA £760k

References:
    - PS1/26 Art. 200(1)(a)/232: third-party deposit treated as a guarantee.
    - PS1/26 Art. 120A: institution ECRA risk weight (CQS2 = 30%).
    - IMPLEMENTATION_PLAN.md: P1.239/P1.240.
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_THIRD_PARTY_DEPOSIT_FIRB_DEFERRED
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.p1_190_pipeline_helpers import find_loan_rows
from tests.fixtures.p1_239.p1_239 import SCENARIOS, build_p1_239_bundle

REPORTING_DATE = date(2030, 6, 30)


def _run(scenario_label: str):
    bundle = build_p1_239_bundle([scenario_label], REPORTING_DATE)
    config = CalculationConfig.basel_3_1(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _loan_rwa(result, loan_ref: str) -> float:
    rows = find_loan_rows(result, loan_ref)
    assert rows, f"P1.239: no result rows for {loan_ref}"
    return sum(r["rwa_final"] for r in rows if r.get("rwa_final") is not None)


def _crm017(result) -> list:
    return [e for e in result.errors if e.code == ERROR_THIRD_PARTY_DEPOSIT_FIRB_DEFERRED]


class TestP1239B31ThirdPartyDeposit:
    """Basel 3.1: a third-party deposit substitutes the holder institution's ECRA RW."""

    def test_own_bank_deposit_zero_cash_unchanged(self) -> None:
        """Control: own-bank deposit (null holder) keeps the 0% cash treatment → RWA £600k."""
        s = SCENARIOS["b31_own_bank"]
        assert _loan_rwa(_run("b31_own_bank"), s.loan_ref) == pytest.approx(
            s.expected_rwa, rel=1e-3
        )

    def test_third_party_cqs2_holder_rw_substitution(self) -> None:
        """LOAD-BEARING: CQS2 holder → covered part at 30% ECRA → blended 0.72 → RWA £720k."""
        s = SCENARIOS["b31_third_party_cqs2"]
        assert _loan_rwa(_run("b31_third_party_cqs2"), s.loan_ref) == pytest.approx(
            s.expected_rwa, rel=1e-3
        )

    def test_unrated_holder_scra_grade_c_fallback_no_benefit(self) -> None:
        """LOAD-BEARING: an unrated B31 institution holder → SCRA Grade-C 150% fallback
        (CRE20.21) → benefit-only cap gives NO benefit → RWA £1,000k — NOT the 0% cash
        £600k and NOT the ECRA-unrated £760k."""
        result = _run("b31_third_party_unrated")
        rwa = _loan_rwa(result, SCENARIOS["b31_third_party_unrated"].loan_ref)
        assert rwa == pytest.approx(1_000_000.00, rel=1e-3)
        assert abs(rwa - 600_000.0) > 1.0
        assert abs(rwa - 760_000.0) > 1.0

    def test_non_institution_holder_no_benefit_and_warning(self) -> None:
        """A populated NON-institution holder is out of Art. 232(2) scope → no benefit
        (RWA £1,000k, not 0% cash) + one CRM017 warning."""
        result = _run("b31_non_institution")
        rwa = _loan_rwa(result, SCENARIOS["b31_non_institution"].loan_ref)
        assert rwa == pytest.approx(1_000_000.00, rel=1e-3)
        assert len(_crm017(result)) == 1

    def test_third_party_exceeds_own_bank(self) -> None:
        """The holder reference alone must raise RWA vs the own-bank 0% cash treatment."""
        third = _loan_rwa(_run("b31_third_party_cqs2"), SCENARIOS["b31_third_party_cqs2"].loan_ref)
        own = _loan_rwa(_run("b31_own_bank"), SCENARIOS["b31_own_bank"].loan_ref)
        assert third > own
