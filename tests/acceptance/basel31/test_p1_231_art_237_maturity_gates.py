"""
P1.231 (Basel 3.1) — Art. 237(1)/(2)(b) guarantee maturity-eligibility gates.

Twin of tests/acceptance/crr/test_p1_231_art_237_maturity_gates.py. Art. 237 is
identical under CRR and PS1/26, and the corporate CQS-1 (20%) / unrated (100%)
SA risk weights are regime-invariant, so every expected value matches the CRR
file — only the config (framework + go-live reporting date) differs.

References:
    - PS1/26 Art. 237(1); Art. 162(3)/237(2)(b); Art. 239(3).
    - tests/fixtures/p1_231/p1_231.py: fixture builder + hand-calculation.
    - docs/plans/compliance-audit-crr-111-241-rectification.md §5 WS2, P1.231.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_231.p1_231 import (
    EXPECTED_RWA_BORROWER_BASIS,
    LN_1DF_CONTROL,
    LN_1DF_MISMATCH,
    LN_237_1_MASKED,
    LN_237_1_OUTLIVES,
    LN_237_1_T02_T5,
    LN_BASELINE,
    build_p231_bundle,
)

_REPORTING_DATE = date(2027, 6, 30)


def _results() -> pl.DataFrame:
    config = CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
    )
    results = PipelineOrchestrator().run_with_data(build_p231_bundle(_REPORTING_DATE), config)
    assert results.results is not None
    return results.results.collect()


def _loan_rwa(df: pl.DataFrame, loan_ref: str) -> float:
    rows = df.filter(pl.col("parent_exposure_reference") == loan_ref)
    assert rows.height > 0, f"no rows for {loan_ref}"
    return rows["rwa_final"].sum()


class TestP1231Art237MaturityGatesB31:
    """P1.231 Basel 3.1: Art. 237(1)/(2)(b) guarantee maturity gates."""

    @pytest.fixture(scope="class")
    def results(self) -> pl.DataFrame:
        return _results()

    def test_baseline_borrower_basis(self, results: pl.DataFrame) -> None:
        """Anchor: the unguaranteed baseline loan carries the 100% borrower basis."""
        assert _loan_rwa(results, LN_BASELINE) == pytest.approx(EXPECTED_RWA_BORROWER_BASIS)

    def test_one_day_floor_mismatch_zeroed(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING: one-day-floor exposure + shorter guarantee => NO benefit
        (Art. 237(2)(b)); RWA = 1,000,000. Pre-fix scaled (~781,601) -> FAILS."""
        assert _loan_rwa(results, LN_1DF_MISMATCH) == pytest.approx(EXPECTED_RWA_BORROWER_BASIS)

    def test_one_day_floor_false_control_recognised(self, results: pl.DataFrame) -> None:
        """Control: same mismatch WITHOUT the floor is recognised (scaled)."""
        rwa = _loan_rwa(results, LN_1DF_CONTROL)
        assert rwa < EXPECTED_RWA_BORROWER_BASIS
        assert _loan_rwa(results, LN_1DF_MISMATCH) > rwa

    def test_masked_short_protection_zeroed(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING: guarantee 40d / exposure 80d (masked mismatch) => NO
        benefit (Art. 237(1)); RWA = 1,000,000. Pre-fix full coverage (~200,000)
        -> FAILS."""
        assert _loan_rwa(results, LN_237_1_MASKED) == pytest.approx(EXPECTED_RWA_BORROWER_BASIS)

    def test_t02_long_exposure_zeroed(self, results: pl.DataFrame) -> None:
        """Control (team-lead spec): t ~= 0.2, T = 5y => ZERO benefit."""
        assert _loan_rwa(results, LN_237_1_T02_T5) == pytest.approx(EXPECTED_RWA_BORROWER_BASIS)

    def test_protection_outlives_shorter_exposure_recognised(self, results: pl.DataFrame) -> None:
        """Control (team-lead spec): t ~= 0.2 protection outlives a shorter
        exposure (T ~= 0.15) — recognised at the guarantor's 20% RW (RWA = 200,000)."""
        assert _loan_rwa(results, LN_237_1_OUTLIVES) == pytest.approx(200_000.0, rel=1e-4)
