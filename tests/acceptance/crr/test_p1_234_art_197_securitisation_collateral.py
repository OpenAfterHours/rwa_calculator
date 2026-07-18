"""
P1.234 (CRR) — Art. 197(1)(h) securitisation-position financial collateral.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

A non-resecuritisation securitisation position risk-weighted <= 100% is eligible
financial collateral with the Art. 224 Table 1 securitisation haircut (2x
corporate = 8% for CQS 1 at a 4y residual). A resecuritisation, a position RW
> 100%, or an unknown (null) RW is ineligible and gives no CRM benefit.

Hand-calculation (EAD 1,000,000; MV 500,000; unrated corporate 100% RW;
10-day liquidation period so the base haircut applies directly):
    LN_ELIGIBLE: E* = 1,000,000 - 500,000 x (1 - 0.08) = 540,000 -> RWA 540,000.
    LN_RESEC / LN_HIGH_RW / LN_NULL_RW: collateral zeroed -> RWA 1,000,000.
Pre-fix (no securitisation branch): every loan falls to the flat 40%
"other_physical" haircut with NO Art. 197 gate -> RWA ~= 700,000 (eligible
over-stated; the three ineligible ones under-stated).

References:
    - CRR Art. 197(1)(h); Art. 224 Table 1 securitisation column.
    - tests/fixtures/p1_234/p1_234.py: fixture builder + hand-calculation.
    - docs/plans/compliance-audit-crr-111-241-rectification.md §5 WS3, P1.234.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
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

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

_REPORTING_DATE = date(2026, 6, 30)
_ABS_TOL = 0.5


def _results() -> pl.DataFrame:
    config = CalculationConfig.crr(
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
    return float(rows["rwa_final"].sum())


class TestP1234Art197SecuritisationCollateralCRR:
    """P1.234 CRR: Art. 197(1)(h) securitisation-collateral eligibility + haircut."""

    @pytest.fixture(scope="class")
    def results(self) -> pl.DataFrame:
        return _results()

    def test_baseline_borrower_basis(self, results: pl.DataFrame) -> None:
        """Anchor: the uncollateralised baseline loan is the 100% borrower basis."""
        assert _loan_rwa(results, LN_BASELINE) == pytest.approx(
            EXPECTED_RWA_NO_BENEFIT, abs=_ABS_TOL
        )

    def test_eligible_securitisation_gets_table1_haircut(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING: a non-resec, RW<=100% securitisation position is eligible
        with the 8% Art. 224 Table 1 securitisation haircut -> RWA 540,000.

        PRE-FIX: routed to other_physical (flat 40%) -> RWA ~= 700,000.
        """
        assert _loan_rwa(results, LN_ELIGIBLE) == pytest.approx(EXPECTED_RWA_ELIGIBLE, abs=_ABS_TOL)

    def test_resecuritisation_ineligible(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING: a resecuritisation position gives NO CRM benefit
        (Art. 197(1)(h)) -> RWA 1,000,000. Pre-fix wrongly granted ~700,000."""
        assert _loan_rwa(results, LN_RESEC) == pytest.approx(EXPECTED_RWA_NO_BENEFIT, abs=_ABS_TOL)

    def test_position_rw_over_100pct_ineligible(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING: a securitisation position with RW > 100% is ineligible
        -> RWA 1,000,000. Pre-fix wrongly granted ~700,000."""
        assert _loan_rwa(results, LN_HIGH_RW) == pytest.approx(
            EXPECTED_RWA_NO_BENEFIT, abs=_ABS_TOL
        )

    def test_null_position_rw_ineligible_conservative(self, results: pl.DataFrame) -> None:
        """DISCRIMINATING: a null position RW is CONSERVATIVE — the RW<=100% gate
        cannot be confirmed, so the collateral is ineligible -> RWA 1,000,000."""
        assert _loan_rwa(results, LN_NULL_RW) == pytest.approx(
            EXPECTED_RWA_NO_BENEFIT, abs=_ABS_TOL
        )
