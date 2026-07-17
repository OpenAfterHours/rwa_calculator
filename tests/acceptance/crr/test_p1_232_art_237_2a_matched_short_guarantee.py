"""
P1.232 (CRR) — Art. 237(2)(a): the original-maturity >=1yr test binds only WHERE
a maturity mismatch exists, end-to-end.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

A matched (or protection-outlives-exposure) short-dated guarantee — original
maturity < 1y but NO maturity mismatch — must be RECOGNISED (guarantor's 20% RW
on the covered part). Only a MISMATCHED short-original guarantee is zeroed. The
prior engine dropped every <1y-original guarantee unconditionally, over-stating
RWA for matched short-dated (e.g. trade-finance) guarantees.

Hand-calculation (EAD 1,000,000; borrower unrated corporate 100%; guarantor
corporate CQS 1 = 20%; every guarantee original_maturity_years = 0.75):
    LN_MATCHED  : 6m guarantee, 6m exposure (t == T, no mismatch) -> full coverage
        -> RWA = 1,000,000 x 20% = 200,000. Pre-fix: dropped -> 1,000,000.
    LN_OUTLIVES : 9m guarantee, 6m exposure (t > T, no mismatch) -> 200,000.
    LN_MISMATCH : 6m guarantee, 3y exposure (mismatch) -> Art. 237(2)(a) zeroes it
        -> 1,000,000 (both pre- and post-fix).

References:
    - CRR Art. 237(2)(a) + Art. 237(2) chapeau.
    - tests/fixtures/p1_232/p1_232.py: fixture builder + hand-calculation.
    - docs/plans/compliance-audit-crr-111-241-rectification.md §5 WS2, P1.232.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.p1_232.p1_232 import (
    EXPECTED_RWA_BORROWER_BASIS,
    EXPECTED_RWA_RECOGNISED,
    LN_BASELINE,
    LN_MATCHED,
    LN_MISMATCH,
    LN_OUTLIVES,
    build_p232_bundle,
)

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

_REPORTING_DATE = date(2026, 6, 30)


def _results() -> pl.DataFrame:
    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
    )
    results = PipelineOrchestrator().run_with_data(build_p232_bundle(_REPORTING_DATE), config)
    assert results.results is not None
    return results.results.collect()


def _loan_rwa(df: pl.DataFrame, loan_ref: str) -> float:
    rows = df.filter(pl.col("parent_exposure_reference") == loan_ref)
    assert rows.height > 0, f"no rows for {loan_ref}"
    return rows["rwa_final"].sum()


class TestP1232Art2372aMatchedShortGuaranteeCRR:
    """P1.232 CRR: original maturity <1y is only ineligible where a mismatch exists."""

    @pytest.fixture(scope="class")
    def results(self) -> pl.DataFrame:
        return _results()

    def test_baseline_borrower_basis(self, results: pl.DataFrame) -> None:
        """Anchor: unguaranteed baseline carries the 100% borrower basis."""
        assert _loan_rwa(results, LN_BASELINE) == pytest.approx(EXPECTED_RWA_BORROWER_BASIS)

    def test_matched_short_guarantee_recognised(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING (headline): a matched 6m/6m guarantee with original
        maturity 0.75y is RECOGNISED (no mismatch) — guarantor 20% RW on the
        covered part -> RWA = 200,000.

        PRE-FIX: the unconditional <1y pre-filter DROPS it -> RWA = 1,000,000.
        """
        assert _loan_rwa(results, LN_MATCHED) == pytest.approx(EXPECTED_RWA_RECOGNISED, rel=1e-4)

    def test_protection_outlives_exposure_recognised(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING: a 9m guarantee (original 0.75y) outliving a 6m exposure
        (no mismatch) is RECOGNISED -> RWA = 200,000. Pre-fix dropped -> 1,000,000."""
        assert _loan_rwa(results, LN_OUTLIVES) == pytest.approx(EXPECTED_RWA_RECOGNISED, rel=1e-4)

    def test_mismatched_short_guarantee_still_zeroed(self, results: pl.DataFrame) -> None:
        """Control: a 6m guarantee (original 0.75y) on a 3y exposure (mismatch) is
        STILL ineligible under Art. 237(2)(a) -> RWA = 1,000,000 (borrower basis).
        Confirms the relocated gate still binds where a mismatch exists."""
        assert _loan_rwa(results, LN_MISMATCH) == pytest.approx(EXPECTED_RWA_BORROWER_BASIS)
