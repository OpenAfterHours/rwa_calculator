"""
P1.109: CRR Art. 237/238/239(3) maturity mismatch on unfunded protection.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Confirm that a full-tenor guarantee (t == T) produces no mismatch adjustment and
  applies the guarantor's risk weight at face value: RWA = 200,000.
- Confirm that a maturity-mismatched guarantee (t=2.5y < T=5.0y) triggers the
  Art. 239(3) scaling formula, reducing the covered portion GA and blending
  borrower and guarantor risk weights: RWA = 621,052.6315789474.

Two scenarios (one pipeline run per parametrised case):

    GUAR_FULL_P1109: original_maturity_years=5.0, loan residual=5.0y
        t == T → no Art. 239(3) adjustment
        GA = 1,000,000  → RWA = 200,000

    GUAR_MM_P1109:   original_maturity_years=2.5, loan residual=5.0y
        t=2.5y < T=5.0y → Art. 239(3) applies
        GA = 1,000,000 × (2.5 − 0.25) / (5.0 − 0.25) = 473,684.2105263158
        guaranteed RWA   = 473,684.21 × 0.20 =  94,736.8421052632
        unguaranteed RWA = 526,315.79 × 1.00 = 526,315.7894736842
        total RWA        =                      621,052.6315789474

Defect under test (pre-fix):
    The CRM processor does not implement CRR Art. 239(3). With GUAR_MM_P1109, the
    engine applies the guarantee at face value (GA = 1,000,000) rather than scaling it,
    yielding rwa_final = 200,000 instead of 621,052.63 — understating RWA by ~421,053.

References:
    - CRR Art. 237(2)(a): minimum residual maturity of protection >= 1 year
    - CRR Art. 238: maturity of credit protection
    - CRR Art. 239(3): maturity mismatch adjustment formula
    - tests/fixtures/p1_109/p1_109.py: fixture builder and scenario constants
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_109" / "data"

# ---------------------------------------------------------------------------
# Constants from the fixture builder
# ---------------------------------------------------------------------------

from tests.fixtures.p1_109.p1_109 import (  # noqa: E402
    GA_MISMATCH,
    GA_UNGUARANTEED,
    GUAR_FULL_REF,
    GUAR_MM_REF,
    GUARANTOR_REF,
    LOAN_REF,
)

# ---------------------------------------------------------------------------
# Reporting date: 2026-01-01 == LOAN_VALUE_DATE, so loan residual = exactly 5y.
# ---------------------------------------------------------------------------
_REPORTING_DATE = date(2026, 1, 1)

# ---------------------------------------------------------------------------
# Expected outputs (hand-calculated per architect proposal)
# ---------------------------------------------------------------------------

# Scenario A — full-tenor guarantee (no mismatch)
_EXPECTED_A_EAD = 1_000_000.0
_EXPECTED_A_GUARANTEED_PORTION = 1_000_000.0
_EXPECTED_A_UNGUARANTEED_PORTION = 0.0
_EXPECTED_A_RWA = 200_000.0

# Scenario B — maturity-mismatched guarantee (Art. 239(3))
_EXPECTED_B_EAD = 1_000_000.0
_EXPECTED_B_GUARANTEED_PORTION = GA_MISMATCH  # 473,684.2105263158
_EXPECTED_B_UNGUARANTEED_PORTION = GA_UNGUARANTEED  # 526,315.7894736842
_EXPECTED_B_RWA = GA_MISMATCH * 0.20 + GA_UNGUARANTEED * 1.00  # 621,052.6315789474
_EXPECTED_B_EFFECTIVE_RW = _EXPECTED_B_RWA / _EXPECTED_B_EAD  # ≈ 0.6210526315789474


# ---------------------------------------------------------------------------
# Helper — build a RawDataBundle for a single guarantee reference
# ---------------------------------------------------------------------------


def _make_bundle(guarantee_ref: str) -> RawDataBundle:
    """
    Construct a RawDataBundle for LOAN_001_P1109 with exactly one guarantee row.

    Args:
        guarantee_ref: Either GUAR_FULL_REF or GUAR_MM_REF.

    Returns:
        RawDataBundle ready for pipeline execution.
    """
    single_guar = pl.scan_parquet(_FIXTURES_DIR / "guarantee.parquet").filter(
        pl.col("guarantee_reference") == guarantee_ref
    )
    return RawDataBundle(
        facilities=pl.LazyFrame(
            schema={
                "facility_reference": pl.String,
                "counterparty_reference": pl.String,
            }
        ),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        guarantees=single_guar,
    )


def _run_pipeline(guarantee_ref: str) -> pl.DataFrame:
    """
    Run the full CRR SA pipeline for the given guarantee scenario.

    Returns the SA results DataFrame (all rows, including guarantee sub-rows).
    """
    bundle = _make_bundle(guarantee_ref)
    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None, "SA results must not be None for SA-only config"
    return cast(pl.DataFrame, results.sa_results.collect())


def _aggregate_by_parent(df: pl.DataFrame, parent_ref: str) -> dict:
    """
    Aggregate all sub-rows (guarantee split rows + remainder) for a parent exposure.

    Additive fields (rwa_final, guaranteed_portion, unguaranteed_portion, ead_final)
    are summed. The first value is used for non-additive fields.
    """
    sub_rows = df.filter(pl.col("parent_exposure_reference") == parent_ref)
    assert sub_rows.height > 0, (
        f"No SA result rows found with parent_exposure_reference='{parent_ref}'"
    )
    _additive = {"rwa_final", "guaranteed_portion", "unguaranteed_portion", "ead_final"}
    result: dict = {}
    for col_name in sub_rows.columns:
        if col_name in _additive:
            result[col_name] = sub_rows[col_name].sum()
        else:
            result[col_name] = sub_rows[col_name][0]
    return result


# ---------------------------------------------------------------------------
# Acceptance tests — P1.109 CRR Art. 239(3) maturity mismatch adjustment
# ---------------------------------------------------------------------------


class TestP1109Art237MaturityMismatchGuarantees:
    """
    P1.109: CRR Art. 239(3) — maturity mismatch reduces the covered portion GA
    when protection residual maturity t < exposure residual maturity T.

    Two scenarios driven by a class-scoped pipeline fixture each:
      - GUAR_FULL  (t == T = 5.0y): no mismatch → GA = 1,000,000 → RWA = 200,000
      - GUAR_MM    (t = 2.5y < T = 5.0y): Art. 239(3) scaling → RWA = 621,052.63
    """

    # -----------------------------------------------------------------------
    # Class-scoped pipeline results — one run per guarantee scenario
    # -----------------------------------------------------------------------

    @pytest.fixture(scope="class")
    def guar_full_results(self) -> dict:
        """
        SA pipeline result for LOAN_001_P1109 under GUAR_FULL_P1109 (5.0y, no mismatch).

        Aggregates all guarantee sub-rows by parent ref.
        """
        df = _run_pipeline(GUAR_FULL_REF)
        return _aggregate_by_parent(df, LOAN_REF)

    @pytest.fixture(scope="class")
    def guar_mm_results(self) -> dict:
        """
        SA pipeline result for LOAN_001_P1109 under GUAR_MM_P1109 (2.5y, mismatched).

        Aggregates all guarantee sub-rows by parent ref.
        """
        df = _run_pipeline(GUAR_MM_REF)
        return _aggregate_by_parent(df, LOAN_REF)

    # -----------------------------------------------------------------------
    # Scenario A — GUAR_FULL (no mismatch) — should PASS today (regression pin)
    # -----------------------------------------------------------------------

    def test_p1_109_full_tenor_guarantee_ead_equals_loan_ead(self, guar_full_results: dict) -> None:
        """
        Full-tenor guarantee: aggregated ead_final == 1,000,000.

        Arrange: LOAN_001_P1109 (GBP 1M) + GUAR_FULL_P1109 (t=T=5.0y).
        Act:     full CRR SA pipeline.
        Assert:  total ead_final == 1,000,000 (no EAD change from guarantee).
        """
        # Arrange
        row = guar_full_results

        # Assert
        assert row["ead_final"] == pytest.approx(_EXPECTED_A_EAD, rel=1e-6), (
            f"P1.109 GUAR_FULL: expected ead_final={_EXPECTED_A_EAD:,.0f}, "
            f"got {row['ead_final']:,.2f}"
        )

    def test_p1_109_full_tenor_guarantee_covered_portion_equals_full_ead(
        self, guar_full_results: dict
    ) -> None:
        """
        Full-tenor guarantee: guaranteed_portion == 1,000,000 (full coverage, no scaling).

        Arrange: LOAN_001_P1109 + GUAR_FULL_P1109 (t == T, no mismatch).
        Act:     full CRR SA pipeline.
        Assert:  guaranteed_portion == 1,000,000.

        This test should PASS today — retained as regression pin.
        """
        # Arrange
        row = guar_full_results

        # Assert
        assert row["guaranteed_portion"] == pytest.approx(
            _EXPECTED_A_GUARANTEED_PORTION, rel=1e-6
        ), (
            f"P1.109 GUAR_FULL: expected guaranteed_portion={_EXPECTED_A_GUARANTEED_PORTION:,.0f}, "
            f"got {row['guaranteed_portion']:,.2f}"
        )

    def test_p1_109_full_tenor_guarantee_unguaranteed_portion_is_zero(
        self, guar_full_results: dict
    ) -> None:
        """
        Full-tenor guarantee: unguaranteed_portion == 0 (entire exposure is covered).

        Arrange: LOAN_001_P1109 + GUAR_FULL_P1109 (t == T, no mismatch).
        Act:     full CRR SA pipeline.
        Assert:  unguaranteed_portion == 0.0.

        This test should PASS today — retained as regression pin.
        """
        # Arrange
        row = guar_full_results

        # Assert
        assert row["unguaranteed_portion"] == pytest.approx(
            _EXPECTED_A_UNGUARANTEED_PORTION, abs=1e-2
        ), (
            f"P1.109 GUAR_FULL: expected unguaranteed_portion=0.0, "
            f"got {row['unguaranteed_portion']:,.2f}"
        )

    def test_p1_109_full_tenor_guarantee_rwa_equals_guarantor_rw_times_ead(
        self, guar_full_results: dict
    ) -> None:
        """
        Full-tenor guarantee: rwa_final == 200,000 (guarantor CQS 1 at 20% × EAD 1M).

        Arrange: LOAN_001_P1109 + GUAR_FULL_P1109 (t == T, no mismatch).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 200,000.

        This test should PASS today — retained as regression pin.
        """
        # Arrange
        row = guar_full_results

        # Assert
        assert row["rwa_final"] == pytest.approx(_EXPECTED_A_RWA, rel=1e-6), (
            f"P1.109 GUAR_FULL: expected rwa_final={_EXPECTED_A_RWA:,.0f} "
            f"(guarantor 20% × 1,000,000 — no mismatch scaling), "
            f"got {row['rwa_final']:,.2f}"
        )

    def test_p1_109_full_tenor_guarantee_guarantor_reference(self, guar_full_results: dict) -> None:
        """
        Full-tenor guarantee: guarantor_reference on the guaranteed sub-row == CP_GUARANTOR_P1109.

        Arrange: LOAN_001_P1109 + GUAR_FULL_P1109.
        Act:     full CRR SA pipeline.
        Assert:  guarantor_reference == 'CP_GUARANTOR_P1109'.

        This test should PASS today — retained as regression pin.
        """
        # Arrange / Act (fixture provides aggregated first-row values for non-additive fields)
        df = _run_pipeline(GUAR_FULL_REF)
        guaranteed_sub_rows = df.filter(
            (pl.col("parent_exposure_reference") == LOAN_REF) & (pl.col("is_guaranteed") == True)  # noqa: E712
        )

        # Assert
        assert guaranteed_sub_rows.height > 0, (
            "Expected at least one guaranteed sub-row for GUAR_FULL_P1109"
        )
        assert guaranteed_sub_rows["guarantor_reference"][0] == GUARANTOR_REF, (
            f"P1.109 GUAR_FULL: expected guarantor_reference='{GUARANTOR_REF}', "
            f"got '{guaranteed_sub_rows['guarantor_reference'][0]}'"
        )

    # -----------------------------------------------------------------------
    # Scenario B — GUAR_MM (maturity mismatch) — THESE FAIL TODAY (pre-fix)
    # -----------------------------------------------------------------------

    def test_p1_109_maturity_mismatch_ead_unchanged(self, guar_mm_results: dict) -> None:
        """
        Maturity-mismatched guarantee: total ead_final == 1,000,000 (EAD is not reduced).

        Arrange: LOAN_001_P1109 (GBP 1M, 5y) + GUAR_MM_P1109 (t=2.5y < T=5.0y).
        Act:     full CRR SA pipeline.
        Assert:  total ead_final == 1,000,000 (Art. 239(3) scales GA, not EAD).
        """
        # Arrange
        row = guar_mm_results

        # Assert
        assert row["ead_final"] == pytest.approx(_EXPECTED_B_EAD, rel=1e-6), (
            f"P1.109 GUAR_MM: expected ead_final={_EXPECTED_B_EAD:,.0f}, "
            f"got {row['ead_final']:,.2f}"
        )

    def test_p1_109_maturity_mismatch_guaranteed_portion_is_scaled(
        self, guar_mm_results: dict
    ) -> None:
        """
        CRR Art. 239(3): maturity mismatch reduces guaranteed_portion below face value.

        Arrange: LOAN_001_P1109 + GUAR_MM_P1109 (t=2.5y, T=5.0y).
        Act:     full CRR SA pipeline.
        Assert:  guaranteed_portion == 473,684.2105263158
                 (= 1,000,000 × (2.5 − 0.25) / (5.0 − 0.25)).

        THIS TEST FAILS TODAY because the engine applies GA at face value (1,000,000)
        instead of applying the Art. 239(3) scaling factor (2.25 / 4.75).
        """
        # Arrange
        row = guar_mm_results

        # Assert
        assert row["guaranteed_portion"] == pytest.approx(
            _EXPECTED_B_GUARANTEED_PORTION, rel=1e-6
        ), (
            f"P1.109 GUAR_MM: expected guaranteed_portion={_EXPECTED_B_GUARANTEED_PORTION:,.10f} "
            f"(Art. 239(3): 1,000,000 × (2.5−0.25)/(5.0−0.25)), "
            f"got {row['guaranteed_portion']:,.2f}"
        )

    def test_p1_109_maturity_mismatch_unguaranteed_portion(self, guar_mm_results: dict) -> None:
        """
        CRR Art. 239(3): unguaranteed_portion == EAD − scaled GA.

        Arrange: LOAN_001_P1109 + GUAR_MM_P1109 (t=2.5y, T=5.0y).
        Act:     full CRR SA pipeline.
        Assert:  unguaranteed_portion == 526,315.7894736842
                 (= 1,000,000 − 473,684.2105263158).

        THIS TEST FAILS TODAY because the engine returns unguaranteed_portion = 0.0
        (treats full face-value guarantee as 100% covering the exposure).
        """
        # Arrange
        row = guar_mm_results

        # Assert
        assert row["unguaranteed_portion"] == pytest.approx(
            _EXPECTED_B_UNGUARANTEED_PORTION, rel=1e-6
        ), (
            f"P1.109 GUAR_MM: expected unguaranteed_portion={_EXPECTED_B_UNGUARANTEED_PORTION:,.10f} "
            f"(= EAD − scaled GA), "
            f"got {row['unguaranteed_portion']:,.2f}"
        )

    def test_p1_109_maturity_mismatch_rwa_blends_borrower_and_guarantor_rw(
        self, guar_mm_results: dict
    ) -> None:
        """
        CRR Art. 239(3): total rwa_final blends guarantor RW on covered and borrower RW
        on uncovered portion.

        Arrange: LOAN_001_P1109 (corp CQS 4, 100% RW) + GUAR_MM_P1109 (inst CQS 1, 20% RW).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 621,052.6315789474
                 (= 473,684.21 × 0.20 + 526,315.79 × 1.00).

        THIS TEST FAILS TODAY because the engine returns rwa_final = 200,000.0
        (applies full guarantee at face value, ignoring the Art. 239(3) scaling).
        """
        # Arrange
        row = guar_mm_results

        # Assert
        assert row["rwa_final"] == pytest.approx(_EXPECTED_B_RWA, rel=1e-6), (
            f"P1.109 GUAR_MM: expected rwa_final={_EXPECTED_B_RWA:,.10f} "
            f"(Art. 239(3): {_EXPECTED_B_GUARANTEED_PORTION:,.4f} × 0.20 + "
            f"{_EXPECTED_B_UNGUARANTEED_PORTION:,.4f} × 1.00), "
            f"got {row['rwa_final']:,.2f}"
        )

    def test_p1_109_maturity_mismatch_effective_rw(self, guar_mm_results: dict) -> None:
        """
        CRR Art. 239(3): effective post-CRM risk weight == rwa_final / ead_final ≈ 0.621053.

        Arrange: LOAN_001_P1109 + GUAR_MM_P1109 (t=2.5y, T=5.0y).
        Act:     full CRR SA pipeline.
        Assert:  rwa_final / ead_final ≈ 0.6210526315789474.

        THIS TEST FAILS TODAY because rwa_final = 200,000 → effective RW = 0.20.
        """
        # Arrange
        row = guar_mm_results
        ead = row["ead_final"]
        rwa = row["rwa_final"]

        # Assert
        effective_rw = rwa / ead
        assert effective_rw == pytest.approx(_EXPECTED_B_EFFECTIVE_RW, rel=1e-6), (
            f"P1.109 GUAR_MM: expected effective RW = rwa_final/ead_final "
            f"≈ {_EXPECTED_B_EFFECTIVE_RW:.10f}, "
            f"got {effective_rw:.10f} (rwa={rwa:,.2f}, ead={ead:,.2f})"
        )

    def test_p1_109_maturity_mismatch_guarantor_reference(self, guar_mm_results: dict) -> None:
        """
        Maturity-mismatched guarantee: guaranteed sub-row has guarantor_reference == CP_GUARANTOR_P1109.

        Arrange: LOAN_001_P1109 + GUAR_MM_P1109.
        Act:     full CRR SA pipeline.
        Assert:  the guaranteed sub-row has guarantor_reference == 'CP_GUARANTOR_P1109'.

        This sub-assertion should pass even before the mismatch fix is applied.
        """
        # Arrange / Act
        df = _run_pipeline(GUAR_MM_REF)
        guaranteed_sub_rows = df.filter(
            (pl.col("parent_exposure_reference") == LOAN_REF) & (pl.col("is_guaranteed") == True)  # noqa: E712
        )

        # Assert
        assert guaranteed_sub_rows.height > 0, (
            "Expected at least one guaranteed sub-row for GUAR_MM_P1109"
        )
        assert guaranteed_sub_rows["guarantor_reference"][0] == GUARANTOR_REF, (
            f"P1.109 GUAR_MM: expected guarantor_reference='{GUARANTOR_REF}', "
            f"got '{guaranteed_sub_rows['guarantor_reference'][0]}'"
        )
