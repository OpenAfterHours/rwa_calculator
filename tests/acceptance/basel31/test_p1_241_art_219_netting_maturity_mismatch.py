"""
P1.241 Basel 3.1 — Art. 219 on-B/S netting is subject to the Art. 237-239
maturity mismatch (carried into PS1/26 unchanged in substance).

Regime twin of the CRR scenario: a £200k deposit nets a £1m loan under one
netting agreement and counterparty. PS1/26 retains Art. 237/238/239, so the
mismatch mechanics are regime-identical:

    b31_matched    — 6-year deposit nets a 5-year loan (no mismatch) → RWA £800k
    b31_partial    — 3yr-original / 6mo-residual deposit nets a 7-year loan →
                     benefit scaled by (t - 0.25)/(5 - 0.25) → RWA ~£989.7k
    b31_short_orig — 6-month-ORIGINAL deposit → mismatch with original < 1y →
                     Art. 237(2)(a) zeroes the protection → RWA £1m

References:
    - PS1/26 Art. 219: on-B/S netting treated as cash collateral (retained).
    - PS1/26 Art. 237-239: maturity-mismatch eligibility + adjustment (retained).
    - PS1/26 Art. 122: unrated corporate 100% risk weight.
    - IMPLEMENTATION_PLAN.md: P1.241.
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.p1_190_pipeline_helpers import find_loan_rows
from tests.fixtures.p1_241.p1_241 import SCENARIOS, build_p1_241_bundle

REPORTING_DATE = date(2027, 1, 1)


def _run(scenario_label: str):
    bundle = build_p1_241_bundle([scenario_label], REPORTING_DATE)
    config = CalculationConfig.basel_3_1(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _loan_rwa(result, loan_ref: str) -> float:
    rows = find_loan_rows(result, loan_ref)
    assert rows, f"P1.241: no result rows for {loan_ref}"
    return sum(r["rwa_final"] for r in rows if r.get("rwa_final") is not None)


class TestP1241B31NettingMaturityMismatch:
    """Basel 3.1: on-B/S netting cash collateral takes the Art. 237-239 mismatch."""

    def test_matched_deposit_nets_in_full(self) -> None:
        """Control: a 6-year deposit fully nets a 5-year loan → RWA £800k."""
        s = SCENARIOS["b31_matched"]
        result = _run("b31_matched")
        assert _loan_rwa(result, s.loan_ref) == pytest.approx(
            s.expected_loan_rwa(REPORTING_DATE), rel=1e-6
        )

    def test_partial_scaling_for_eligible_short_deposit(self) -> None:
        """The 3yr-original / 6mo-residual deposit is scaled identically to CRR."""
        s = SCENARIOS["b31_partial"]
        result = _run("b31_partial")
        assert _loan_rwa(result, s.loan_ref) == pytest.approx(
            s.expected_loan_rwa(REPORTING_DATE), rel=1e-6
        )

    def test_short_original_deposit_zeroed(self) -> None:
        """A 6-month-ORIGINAL deposit with a mismatch is ineligible (Art. 237(2)(a))
        → no netting benefit → full RWA £1m."""
        s = SCENARIOS["b31_short_orig"]
        result = _run("b31_short_orig")
        assert _loan_rwa(result, s.loan_ref) == pytest.approx(1_000_000.0, rel=1e-9)

    def test_short_original_exceeds_partial(self) -> None:
        """The <1y-original gate must bite harder than the partial-scaling case."""
        short = _loan_rwa(_run("b31_short_orig"), SCENARIOS["b31_short_orig"].loan_ref)
        partial = _loan_rwa(_run("b31_partial"), SCENARIOS["b31_partial"].loan_ref)
        assert short > partial
