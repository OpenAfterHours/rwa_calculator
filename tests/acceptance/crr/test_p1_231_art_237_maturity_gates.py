"""
P1.231 (CRR) — Art. 237(1)/(2)(b) guarantee maturity-eligibility gates, end-to-end.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

The guarantee maturity-mismatch step must ZERO (not merely scale) recognised
protection when:
  - Art. 162(3)/237(2)(b): the exposure is subject to the one-day IRB maturity
    floor and there is any maturity mismatch; or
  - Art. 237(1): the guarantee's raw residual maturity is < 3 months AND shorter
    than the exposure (tested pre-floor, so a short exposure does not mask it).

A zeroed guarantee reverts the exposure to the borrower's own 100% basis
(RWA = 1,000,000); a recognised one places EAD on the guarantor's CQS-1 20% RW
(RWA < 1,000,000).

References:
    - CRR Art. 237(1); Art. 162(3)/237(2)(b); Art. 239(3).
    - tests/fixtures/p1_231/p1_231.py: fixture builder + hand-calculation.
    - docs/plans/compliance-audit-crr-111-241-rectification.md §5 WS2, P1.231.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.p1_231.p1_231 import (
    EXPECTED_RWA_BORROWER_BASIS,
    LN_1DF_CONTROL,
    LN_1DF_MISMATCH,
    LN_237_1_MASKED,
    LN_237_1_OUTLIVES,
    LN_237_1_T02_T5,
    LN_BASELINE,
    LN_NULL_MATURITY,
    build_p231_bundle,
)

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

_REPORTING_DATE = date(2026, 6, 30)


def _results() -> pl.DataFrame:
    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
    )
    results = PipelineOrchestrator().run_with_data(build_p231_bundle(_REPORTING_DATE), config)
    assert results.results is not None
    return results.results.collect()


def _loan_rwa(df: pl.DataFrame, loan_ref: str) -> float:
    """Total rwa_final across all (split) rows of a loan."""
    rows = df.filter(pl.col("parent_exposure_reference") == loan_ref)
    assert rows.height > 0, f"no rows for {loan_ref}"
    return rows["rwa_final"].sum()


class TestP1231Art237MaturityGatesCRR:
    """P1.231 CRR: Art. 237(1)/(2)(b) guarantee maturity gates."""

    @pytest.fixture(scope="class")
    def results(self) -> pl.DataFrame:
        return _results()

    def test_baseline_borrower_basis(self, results: pl.DataFrame) -> None:
        """Anchor: the unguaranteed baseline loan carries the 100% borrower basis."""
        assert _loan_rwa(results, LN_BASELINE) == pytest.approx(EXPECTED_RWA_BORROWER_BASIS)

    # ---- Art. 162(3)/237(2)(b): one-day floor + mismatch -------------------

    def test_one_day_floor_mismatch_zeroed(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING: a one-day-floor exposure with a shorter guarantee gets
        NO benefit — reverts to the 100% borrower basis (Art. 237(2)(b)).

        PRE-FIX: the guarantee is scaled (RWA ~= 781,601, == the floor=False
        control below) -> test FAILS. POST-FIX: RWA = 1,000,000.
        """
        assert _loan_rwa(results, LN_1DF_MISMATCH) == pytest.approx(EXPECTED_RWA_BORROWER_BASIS)

    def test_one_day_floor_false_control_recognised(self, results: pl.DataFrame) -> None:
        """Control: the SAME mismatch WITHOUT the one-day floor is recognised
        (scaled) — RWA strictly below the borrower basis. Isolates the flag."""
        rwa = _loan_rwa(results, LN_1DF_CONTROL)
        assert rwa < EXPECTED_RWA_BORROWER_BASIS
        assert _loan_rwa(results, LN_1DF_MISMATCH) > rwa

    def test_null_exposure_maturity_one_day_floor_zeroed(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING (null-T): a one-day-floor loan with NULL maturity_date +
        a shorter guarantee gets NO benefit — the null exposure maturity defaults
        to a 5y exposure, so the mismatch stands and Art. 237(2)(b) zeroes it.

        PRE-FIX (null-T not defaulted): the gate never fires -> guarantee scaled
        -> RWA < 1,000,000. POST-FIX: RWA = 1,000,000.
        """
        assert _loan_rwa(results, LN_NULL_MATURITY) == pytest.approx(EXPECTED_RWA_BORROWER_BASIS)

    # ---- Art. 237(1): <3-month-and-shorter protection ----------------------

    def test_masked_short_protection_zeroed(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING: guarantee 40d / exposure 80d — both raw residuals
        < 0.25 (masking the mismatch once floored) — gets NO benefit (Art.
        237(1)).

        PRE-FIX: full coverage retained (RWA ~= 200,000) -> test FAILS.
        POST-FIX: RWA = 1,000,000.
        """
        assert _loan_rwa(results, LN_237_1_MASKED) == pytest.approx(EXPECTED_RWA_BORROWER_BASIS)

    def test_t02_long_exposure_zeroed(self, results: pl.DataFrame) -> None:
        """Control (team-lead spec): t ~= 0.2, T = 5y => ZERO benefit (RWA =
        borrower basis). Sub-3-month protection is not recognised."""
        assert _loan_rwa(results, LN_237_1_T02_T5) == pytest.approx(EXPECTED_RWA_BORROWER_BASIS)

    def test_protection_outlives_shorter_exposure_recognised(self, results: pl.DataFrame) -> None:
        """Control (team-lead spec): t ~= 0.2 protection OUTLIVES a shorter
        exposure (T ~= 0.15) — no mismatch, so it stays recognised at the
        guarantor's 20% RW (full coverage => RWA = 200,000)."""
        assert _loan_rwa(results, LN_237_1_OUTLIVES) == pytest.approx(200_000.0, rel=1e-4)


class TestP1231EadInvariant:
    """The maturity gates move only the RW split, never the total EAD."""

    def test_total_ead_unchanged(self) -> None:
        df = _results()
        for ln in (LN_1DF_MISMATCH, LN_237_1_MASKED, LN_237_1_OUTLIVES):
            ead = df.filter(pl.col("parent_exposure_reference") == ln)["ead_final"].sum()
            assert ead == pytest.approx(1_000_000.0, rel=1e-6), ln
