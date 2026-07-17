"""
P1.234 (Basel 3.1) — Art. 197(1)(h) securitisation-position financial collateral.

Twin of tests/acceptance/crr/test_p1_234_art_197_securitisation_collateral.py.
The CQS-1 securitisation haircut is 8% at a 4y residual under BOTH regimes (CRR
1_5y band; B31 3_5y band), and the unrated-corporate RW is 100% in both, so every
expected value matches the CRR file — only the config differs.

References:
    - PS1/26 Art. 197(1)(h); Art. 224 Table 1 securitisation column.
    - tests/fixtures/p1_234/p1_234.py: fixture builder + hand-calculation.
    - docs/plans/compliance-audit-crr-111-241-rectification.md §5 WS3, P1.234.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_234.p1_234 import (
    EXPECTED_RWA_ELIGIBLE,
    EXPECTED_RWA_NO_BENEFIT,
    LN_BASELINE,
    LN_ELIGIBLE,
    LN_HIGH_RW,
    LN_NULL_RW,
    LN_RESEC,
    build_p234_bundle,
)

_REPORTING_DATE = date(2027, 6, 30)
_ABS_TOL = 0.5


def _results() -> pl.DataFrame:
    config = CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
    )
    results = PipelineOrchestrator().run_with_data(build_p234_bundle(_REPORTING_DATE), config)
    assert results.results is not None
    return results.results.collect()


def _loan_rwa(df: pl.DataFrame, loan_ref: str) -> float:
    """Total rwa_final for a loan. Collateralised loans are not row-split, so the
    exposure_reference is the loan_reference; fall back to parent for robustness."""
    rows = df.filter(pl.col("exposure_reference") == loan_ref)
    if rows.height == 0:
        rows = df.filter(pl.col("parent_exposure_reference") == loan_ref)
    assert rows.height > 0, f"no rows for {loan_ref}"
    return rows["rwa_final"].sum()


class TestP1234Art197SecuritisationCollateralB31:
    """P1.234 Basel 3.1: Art. 197(1)(h) securitisation-collateral eligibility + haircut."""

    @pytest.fixture(scope="class")
    def results(self) -> pl.DataFrame:
        return _results()

    def test_baseline_borrower_basis(self, results: pl.DataFrame) -> None:
        """Anchor: uncollateralised baseline is the 100% borrower basis."""
        assert _loan_rwa(results, LN_BASELINE) == pytest.approx(
            EXPECTED_RWA_NO_BENEFIT, abs=_ABS_TOL
        )

    def test_eligible_securitisation_gets_table1_haircut(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING: non-resec RW<=100% securitisation -> 8% haircut -> RWA 540,000."""
        assert _loan_rwa(results, LN_ELIGIBLE) == pytest.approx(EXPECTED_RWA_ELIGIBLE, abs=_ABS_TOL)

    def test_resecuritisation_ineligible(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING: resecuritisation -> ineligible -> RWA 1,000,000."""
        assert _loan_rwa(results, LN_RESEC) == pytest.approx(EXPECTED_RWA_NO_BENEFIT, abs=_ABS_TOL)

    def test_position_rw_over_100pct_ineligible(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING: RW > 100% securitisation -> ineligible -> RWA 1,000,000."""
        assert _loan_rwa(results, LN_HIGH_RW) == pytest.approx(
            EXPECTED_RWA_NO_BENEFIT, abs=_ABS_TOL
        )

    def test_null_position_rw_ineligible_conservative(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING: null position RW -> conservative ineligible -> RWA 1,000,000."""
        assert _loan_rwa(results, LN_NULL_RW) == pytest.approx(
            EXPECTED_RWA_NO_BENEFIT, abs=_ABS_TOL
        )
