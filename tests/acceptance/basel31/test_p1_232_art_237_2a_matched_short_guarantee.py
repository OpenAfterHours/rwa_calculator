"""
P1.232 (Basel 3.1) — Art. 237(2)(a): original-maturity >=1yr binds only WHERE a
maturity mismatch exists.

Twin of tests/acceptance/crr/test_p1_232_art_237_2a_matched_short_guarantee.py.
Art. 237 is identical under CRR and PS1/26 and the corporate CQS-1 (20%) / unrated
(100%) SA weights are regime-invariant, so every expected value matches the CRR
file — only the config (framework + go-live reporting date) differs.

References:
    - PS1/26 Art. 237(2)(a) + Art. 237(2) chapeau.
    - tests/fixtures/p1_232/p1_232.py: fixture builder + hand-calculation.
    - docs/plans/compliance-audit-crr-111-241-rectification.md §5 WS2, P1.232.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_232.p1_232 import (
    EXPECTED_RWA_BORROWER_BASIS,
    EXPECTED_RWA_RECOGNISED,
    LN_BASELINE,
    LN_MATCHED,
    LN_MISMATCH,
    LN_OUTLIVES,
    build_p232_bundle,
)

_REPORTING_DATE = date(2027, 6, 30)


def _results() -> pl.DataFrame:
    config = CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
    )
    results = PipelineOrchestrator().run_with_data(build_p232_bundle(_REPORTING_DATE), config)
    assert results.results is not None
    return results.results.collect()


def _loan_rwa(df: pl.DataFrame, loan_ref: str) -> float:
    rows = df.filter(pl.col("parent_exposure_reference") == loan_ref)
    assert rows.height > 0, f"no rows for {loan_ref}"
    return float(rows["rwa_final"].sum())


class TestP1232Art2372aMatchedShortGuaranteeB31:
    """P1.232 Basel 3.1: original maturity <1y is only ineligible where a mismatch exists."""

    @pytest.fixture(scope="class")
    def results(self) -> pl.DataFrame:
        return _results()

    def test_baseline_borrower_basis(self, results: pl.DataFrame) -> None:
        """Anchor: unguaranteed baseline carries the 100% borrower basis."""
        assert _loan_rwa(results, LN_BASELINE) == pytest.approx(EXPECTED_RWA_BORROWER_BASIS)

    def test_matched_short_guarantee_recognised(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING: matched 6m/6m guarantee, original 0.75y => recognised
        (200,000). Pre-fix dropped => 1,000,000."""
        assert _loan_rwa(results, LN_MATCHED) == pytest.approx(EXPECTED_RWA_RECOGNISED, rel=1e-4)

    def test_protection_outlives_exposure_recognised(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING: 9m guarantee outlives 6m exposure => recognised (200,000)."""
        assert _loan_rwa(results, LN_OUTLIVES) == pytest.approx(EXPECTED_RWA_RECOGNISED, rel=1e-4)

    def test_mismatched_short_guarantee_still_zeroed(self, results: pl.DataFrame) -> None:
        """Control: 6m guarantee on a 3y exposure (mismatch) stays ineligible
        (Art. 237(2)(a)) => 1,000,000."""
        assert _loan_rwa(results, LN_MISMATCH) == pytest.approx(EXPECTED_RWA_BORROWER_BASIS)
