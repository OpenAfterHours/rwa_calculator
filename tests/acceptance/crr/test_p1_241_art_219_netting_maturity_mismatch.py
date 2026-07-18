"""
P1.241 CRR — Art. 219 on-B/S netting is subject to the Art. 237-239 maturity
mismatch.

A £200k deposit (negative-drawn loan) nets a £1m loan under agreement AGR1 and
the same counterparty. On-balance-sheet netting treats the deposit as cash
collateral (Art. 219), so the funded-protection maturity-mismatch rules apply:

    crr_matched    — 6-year deposit nets a 5-year loan (no mismatch) → full £200k
                     nets → RWA £800k (control)
    crr_partial    — 3-year-original / 6-month-residual deposit nets a 7-year loan
                     (T caps at 5y); original >= 1y so eligible → benefit scaled by
                     (t - 0.25)/(5 - 0.25) → RWA ~£989.7k
    crr_short_orig — 6-month-ORIGINAL deposit nets the 7-year loan → mismatch with
                     original < 1y → Art. 237(2)(a) zeroes the protection → RWA £1m

References:
    - CRR Art. 219: on-B/S netting treated as cash collateral.
    - CRR Art. 237(1)/(2)(a); Art. 238-239: mismatch eligibility + adjustment.
    - CRR Art. 122: unrated corporate 100% risk weight.
    - IMPLEMENTATION_PLAN.md: P1.241.
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.acceptance.p1_190_pipeline_helpers import find_loan_rows
from tests.fixtures.p1_241.p1_241 import SCENARIOS, build_p1_241_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

REPORTING_DATE = date(2026, 1, 1)


def _run(scenario_label: str):
    bundle = build_p1_241_bundle([scenario_label], REPORTING_DATE)
    config = CalculationConfig.crr(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _loan_rwa(result, loan_ref: str) -> float:
    rows = find_loan_rows(result, loan_ref)
    assert rows, f"P1.241: no result rows for {loan_ref}"
    return sum(r["rwa_final"] for r in rows if r.get("rwa_final") is not None)


class TestP1241CrrNettingMaturityMismatch:
    """CRR: on-B/S netting cash collateral takes the Art. 237-239 mismatch."""

    def test_matched_deposit_nets_in_full(self) -> None:
        """Control: a 6-year deposit fully nets a 5-year loan → RWA £800k."""
        s = SCENARIOS["crr_matched"]
        result = _run("crr_matched")
        assert _loan_rwa(result, s.loan_ref) == pytest.approx(
            s.expected_loan_rwa(REPORTING_DATE), rel=1e-6
        )

    def test_partial_scaling_for_eligible_short_deposit(self) -> None:
        """A 3yr-original / 6mo-residual deposit netting a 7yr loan is scaled by
        (t - 0.25)/(T - 0.25) → RWA ~£989.7k (original >= 1y so eligible)."""
        s = SCENARIOS["crr_partial"]
        result = _run("crr_partial")
        assert _loan_rwa(result, s.loan_ref) == pytest.approx(
            s.expected_loan_rwa(REPORTING_DATE), rel=1e-6
        )

    def test_partial_between_full_netting_and_no_netting(self) -> None:
        """The adjustment must strictly reduce — but not eliminate — the benefit."""
        rwa = _loan_rwa(_run("crr_partial"), SCENARIOS["crr_partial"].loan_ref)
        assert 800_000.0 < rwa < 1_000_000.0

    def test_short_original_deposit_zeroed(self) -> None:
        """LOAD-BEARING: a 6-month-ORIGINAL deposit with a mismatch is ineligible
        (Art. 237(2)(a)) → no netting benefit → full RWA £1m."""
        s = SCENARIOS["crr_short_orig"]
        result = _run("crr_short_orig")
        assert _loan_rwa(result, s.loan_ref) == pytest.approx(
            s.expected_loan_rwa(REPORTING_DATE), rel=1e-9
        )
        assert _loan_rwa(result, s.loan_ref) == pytest.approx(1_000_000.0, rel=1e-9)

    def test_short_original_exceeds_partial(self) -> None:
        """The <1y-original gate must bite harder than the partial-scaling case."""
        short = _loan_rwa(_run("crr_short_orig"), SCENARIOS["crr_short_orig"].loan_ref)
        partial = _loan_rwa(_run("crr_partial"), SCENARIOS["crr_partial"].loan_ref)
        assert short > partial
