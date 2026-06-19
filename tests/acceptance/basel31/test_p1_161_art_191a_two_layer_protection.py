"""
P1.161 — PRA Art. 191A(2)(e)(i) "Funded-Only" Look-Through for Two-Layer Protection.

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor → SACalculator → Aggregator

Key assertions:
    When a guarantor has posted eligible cash collateral against its own guarantee
    obligation, PRA Art. 191A(2)(e)(i) allows a "funded-only" look-through election.
    Under look-through, the cash-covered tranche of the loan is treated as if the
    collateral were posted directly against the loan (FCSM, 0% RW for cash, Art. 222).
    The remaining tranche falls back to the obligor's unmitigated SA risk weight.

    Two runs exercise the same scenario:
    - Run A (look_through_election="none"): regression pin.
      Guarantor CQS 4 (BB+-BB-) corporate B31 SA RW = 100% = obligor unrated RW.
      Guarantee is NOT beneficial (no improvement). RWA = 1,000,000.
    - Run B (look_through_election="funded_only"): the new path.
      Guarantee is suppressed. Cash collateral (GBP 400k) re-anchored to obligor.
      EAD_final = 1,000,000 − 400,000 = 600,000. RW = 100% (unrated corporate).
      RWA = 600,000.

Hand-calc (Run B):
    Pre-CRM RW       = 1.00 (corporate unrated, B31 Art. 122(2) Table 6)
    Cash haircut Hc  = 0.00 (Art. 224 Table 1; all GBP — no FX mismatch Hfx = 0)
    C* = 400,000 × (1 − 0 − 0) = 400,000
    EAD_after_collateral = 1,000,000 − 400,000 = 600,000
    RWA = 600,000 × 1.00 = 600,000

References:
    - PRA PS1/26 Art. 191A(2)(e)(i): funded-only look-through election
    - PRA PS1/26 Art. 235: SA risk-weight substitution method (RWSM) — suppressed in Run B
    - PRA PS1/26 Art. 222: FCSM — cash collateral, Hc = Hfx = 0
    - PRA PS1/26 Art. 197(1)(a): cash as eligible financial collateral
    - B31 Art. 122(2) Table 6: corporate unrated SA RW = 100%
    - B31 Art. 122(2) Table 6: corporate CQS 4 (BB+-BB-) SA RW = 100%
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    ORG_MAPPING_SCHEMA,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_161"

# Exposure reference
_LOAN_REF = "LOAN_P1161"

# Expected RWA outcomes (from hand-calc in architect proposal)
_EXPECTED_RWA_RUN_A: float = 1_000_000.0  # regression pin: guarantee not beneficial
_EXPECTED_RWA_RUN_B: float = 600_000.0  # new path: cash collateral reduces EAD

# Expected EAD after collateral (Run B only)
_EXPECTED_EAD_RUN_B: float = 600_000.0

# Obligor unrated corporate B31 SA risk weight (Art. 122(2) Table 6)
_EXPECTED_RW: float = 1.00


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_run_a_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle from P1.161 Run A parquets.

    Run A uses look_through_election="none" (guarantee_run_a.parquet).
    Counterparty, loan, rating, and collateral are shared across both runs.

    Facilities, facility_mappings, lending_mappings, and org_mappings are empty
    LazyFrames because this scenario only uses drawn loan data — no undrawn
    facility rows or hierarchy mappings are required.
    """
    return make_raw_bundle(
        facilities=pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        org_mappings=pl.LazyFrame(schema=dtypes_of(ORG_MAPPING_SCHEMA)),
        guarantees=pl.scan_parquet(_FIXTURES_DIR / "guarantee_run_a.parquet"),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        collateral=pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet"),
    )


def _build_run_b_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle from P1.161 Run B parquets.

    Run B uses look_through_election="funded_only" (guarantee_run_b.parquet).
    All other parquets are identical to Run A.

    The guarantee_run_b.parquet contains the new field look_through_election="funded_only"
    which triggers the Art. 191A(2)(e)(i) funded-only look-through path in the engine.
    """
    return make_raw_bundle(
        facilities=pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        org_mappings=pl.LazyFrame(schema=dtypes_of(ORG_MAPPING_SCHEMA)),
        guarantees=pl.scan_parquet(_FIXTURES_DIR / "guarantee_run_b.parquet"),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        collateral=pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet"),
    )


def _b31_config() -> CalculationConfig:
    """Basel 3.1 SA-only config (post-go-live, 2027-06-30)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _run_pipeline(bundle: RawDataBundle, config: CalculationConfig) -> pl.DataFrame:
    """
    Run P1.161 fixture bundle through the credit risk pipeline.

    Returns the collected SA results DataFrame. Raises AssertionError if SA
    results are absent (indicates PermissionMode or pipeline routing issue).
    """
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None, (
        "SA results should not be None — check CalculationConfig.basel_3_1() produces "
        "SA routing for a corporate unrated SA exposure."
    )
    return results.sa_results.collect()


def _get_total_rwa(df: pl.DataFrame) -> float:
    """
    Return the total RWA for LOAN_P1161 (sum across all CRM-split rows).

    The CRM processor may split the loan into sub-rows (e.g., collateral-covered
    tranche + uncovered tranche, or guaranteed + remainder). Summing rwa_final
    across all rows with parent_exposure_reference == LOAN_P1161 gives the
    consolidated RWA. Rows where exposure_reference == LOAN_P1161 directly
    are also included via the union.
    """
    # Try parent_exposure_reference first (CRM-split rows)
    if "parent_exposure_reference" in df.columns:
        sub_rows = df.filter(
            (pl.col("parent_exposure_reference") == _LOAN_REF)
            | (pl.col("exposure_reference") == _LOAN_REF)
        )
        if sub_rows.height > 0:
            return float(sub_rows["rwa_final"].sum())

    # Fallback: direct exposure_reference match
    rows = df.filter(pl.col("exposure_reference") == _LOAN_REF)
    return float(rows["rwa_final"].sum())


def _get_total_ead(df: pl.DataFrame) -> float:
    """
    Return the total EAD for LOAN_P1161 (sum across all CRM-split rows).

    For Run B the loan is split into a collateral-covered tranche (ead_final = 0,
    post-FCSM) and an uncovered tranche (ead_final = 600,000). The sum must
    equal the post-collateral EAD, not the original EAD.
    """
    if "parent_exposure_reference" in df.columns:
        sub_rows = df.filter(
            (pl.col("parent_exposure_reference") == _LOAN_REF)
            | (pl.col("exposure_reference") == _LOAN_REF)
        )
        if sub_rows.height > 0:
            return float(sub_rows["ead_final"].sum())

    rows = df.filter(pl.col("exposure_reference") == _LOAN_REF)
    return float(rows["ead_final"].sum())


# ---------------------------------------------------------------------------
# P1.161 acceptance test class
# ---------------------------------------------------------------------------


class TestB31_P1_161_Art191A_FundedOnlyLookThrough:
    """
    P1.161: PRA Art. 191A(2)(e)(i) funded-only look-through for two-layer protection.

    Art. 191A(2)(e)(i) (PRA PS1/26): when a guarantor has posted eligible financial
    collateral, the bank may elect to apply a "funded-only" look-through — i.e.,
    treat the cash-collateralised tranche of the loan directly under FCSM
    (Art. 222), rather than routing it through Art. 235 RWSM guarantee substitution.

    In this scenario:
        Obligor:   CP_OBLIGOR_P1161  — corporate, unrated, B31 SA RW = 100%
        Guarantor: CP_GUARANTOR_P1161 — corporate, CQS 4 (BB+-BB-), B31 SA RW = 100%
        Loan:      LOAN_P1161 — GBP 1,000,000, 5y
        Guarantee: GUAR_P1161 — 100% coverage, senior, 5y maturity
        Collateral: COLL_P1161 — GBP 400,000 cash, posted by guarantor

    Run A (election="none") — regression pin:
        Guarantor RW (100%) == obligor RW (100%) → guarantee NOT beneficial.
        Collateral is linked to guarantee, not directly to loan → unallocated.
        RWA = 1,000,000 × 1.00 = 1,000,000.

    Run B (election="funded_only") — new path (FAILS pre-fix):
        Guarantee is suppressed. Cash collateral (400k) re-anchored to obligor.
        EAD_final = 1,000,000 − 400,000 = 600,000 (FCSM, Hc = Hfx = 0).
        RWA = 600,000 × 1.00 = 600,000.
    """

    @pytest.fixture(scope="class")
    def config(self) -> CalculationConfig:
        """Basel 3.1 SA config for P1.161 tests."""
        return _b31_config()

    @pytest.fixture(scope="class")
    def run_a_results(self, config: CalculationConfig) -> pl.DataFrame:
        """
        Basel 3.1 SA pipeline results for Run A (look_through_election="none").

        Arrange: P1.161 parquets with guarantee_run_a.parquet (no look-through).
                 Reporting date 2027-06-30 (post Basel 3.1 effective date).
        Act:     PipelineOrchestrator().run_with_data(bundle, config).
        Return:  Collected SA results DataFrame.
        """
        bundle = _build_run_a_bundle()
        return _run_pipeline(bundle, config)

    @pytest.fixture(scope="class")
    def run_b_results(self, config: CalculationConfig) -> pl.DataFrame:
        """
        Basel 3.1 SA pipeline results for Run B (look_through_election="funded_only").

        Arrange: P1.161 parquets with guarantee_run_b.parquet (funded-only election).
                 Cash collateral (GBP 400k) triggers Art. 191A(2)(e)(i) look-through.
        Act:     PipelineOrchestrator().run_with_data(bundle, config).
        Return:  Collected SA results DataFrame.
        """
        bundle = _build_run_b_bundle()
        return _run_pipeline(bundle, config)

    # -------------------------------------------------------------------------
    # Run A REGRESSION PIN — must PASS before and after fix
    # -------------------------------------------------------------------------

    def test_run_a_election_none_regression(self, run_a_results: pl.DataFrame) -> None:
        """
        P1.161 Run A: total RWA = 1,000,000 when look_through_election="none".

        Regression pin: guarantor CQS 4 (BB+-BB-) corporate B31 SA RW = 100%
        equals obligor unrated RW = 100%. Art. 235 RWSM guarantee substitution
        provides no improvement. Collateral is linked to guarantee (beneficiary_type=
        "guarantee"), not directly to the loan, so it is not allocated via FCSM.
        Full EAD retains obligor RW = 100%.

        This test must PASS today (before the engine fix) and must continue to
        PASS after the engine fix.

        Arrange: guarantee_run_a.parquet with look_through_election="none".
        Act:     Pipeline SA results summed across LOAN_P1161 split rows.
        Assert:  total rwa_final ≈ 1,000,000 (abs=1.0).
        """
        # Arrange
        total_rwa = _get_total_rwa(run_a_results)

        # Assert — regression pin
        assert total_rwa == pytest.approx(_EXPECTED_RWA_RUN_A, abs=1.0), (
            f"P1.161 Run A (regression): total RWA should be {_EXPECTED_RWA_RUN_A:,.0f} "
            f"(EAD 1,000,000 × obligor unrated RW 1.00). "
            f"Guarantor CQS 4 RW (100%) == obligor unrated RW (100%) → no benefit. "
            f"Got {total_rwa:,.0f}."
        )

    # -------------------------------------------------------------------------
    # Run B DISCRIMINATING ASSERTIONS — FAIL pre-fix
    # -------------------------------------------------------------------------

    def test_run_b_election_funded_only_collateral_re_anchored(
        self, run_b_results: pl.DataFrame
    ) -> None:
        """
        P1.161 Run B DISCRIMINATING: total RWA = 600,000 under funded-only look-through.

        Art. 191A(2)(e)(i) funded-only election:
            - Guarantee is suppressed (not substituted via Art. 235 RWSM).
            - Cash collateral (GBP 400k) is re-anchored directly to the obligor.
            - FCSM Art. 222: cash Hc = 0, no FX mismatch Hfx = 0.
            - C* = 400,000 × (1 − 0 − 0) = 400,000.
            - EAD_after_collateral = 1,000,000 − 400,000 = 600,000.
            - RW = 1.00 (corporate unrated, B31 Art. 122(2) Table 6).
            - RWA = 600,000 × 1.00 = 600,000.

        Pre-fix (current): engine ignores look_through_election; collateral
        remains linked to guarantee (beneficiary_type="guarantee") and is
        not allocated to the loan. Total RWA = 1,000,000.

        Post-fix expected: RWA = 600,000 (funded-only look-through applied).

        Arrange: guarantee_run_b.parquet with look_through_election="funded_only".
        Act:     Pipeline SA results summed across LOAN_P1161 split rows.
        Assert:  total rwa_final ≈ 600,000 (abs=1.0).
        """
        # Arrange
        total_rwa = _get_total_rwa(run_b_results)

        # Assert — FAILS pre-fix (engine returns 1,000,000; look-through not implemented)
        assert total_rwa == pytest.approx(_EXPECTED_RWA_RUN_B, abs=1.0), (
            f"P1.161 Run B: total RWA should be {_EXPECTED_RWA_RUN_B:,.0f} "
            f"(Art. 191A(2)(e)(i) funded-only look-through applied). "
            f"Cash collateral 400k re-anchored to obligor: "
            f"EAD_final 600k × unrated corporate RW 1.00 = 600,000. "
            f"Got {total_rwa:,.0f}. "
            f"If 1,000,000: look_through_election='funded_only' not yet processed — "
            f"engine-implementer must add Art. 191A(2)(e)(i) look-through path."
        )

    def test_run_b_ead_final_reduced_by_collateral(self, run_b_results: pl.DataFrame) -> None:
        """
        P1.161 Run B: ead_final = 600,000 after FCSM cash collateral offset.

        Under funded-only look-through, the cash collateral (GBP 400k, Hc = Hfx = 0)
        is applied directly against the obligor's EAD:
            C* = 400,000 × (1 − Hc − Hfx) = 400,000 × 1 = 400,000
            EAD_final = max(0, 1,000,000 − 400,000) = 600,000

        Art. 223(5) / Art. 222 (PRA PS1/26).

        Pre-fix: ead_final = 1,000,000 (collateral not allocated to loan).
        Post-fix: ead_final = 600,000.

        Arrange: guarantee_run_b.parquet with look_through_election="funded_only".
        Act:     Sum ead_final across LOAN_P1161 split rows.
        Assert:  total ead_final ≈ 600,000 (abs=1.0).
        """
        # Arrange
        total_ead = _get_total_ead(run_b_results)

        # Assert — FAILS pre-fix (engine returns 1,000,000)
        assert total_ead == pytest.approx(_EXPECTED_EAD_RUN_B, abs=1.0), (
            f"P1.161 Run B: total ead_final should be {_EXPECTED_EAD_RUN_B:,.0f} "
            f"(EAD 1,000,000 − cash C* 400,000 = 600,000; Art. 223(5) FCSM offset). "
            f"Got {total_ead:,.0f}. "
            f"If 1,000,000: cash collateral not being offset against the loan — "
            f"look-through re-anchoring not yet implemented."
        )

    # -------------------------------------------------------------------------
    # FRAMEWORK DELTA — structural discriminator
    # -------------------------------------------------------------------------

    def test_run_b_rwa_lower_than_run_a_by_400k(
        self,
        run_a_results: pl.DataFrame,
        run_b_results: pl.DataFrame,
    ) -> None:
        """
        P1.161: Run B RWA should be 400,000 less than Run A RWA (post-fix).

        Delta = C* × RW_cash = 400,000 × 0% = 0 RWA on cash tranche,
        saving = 400,000 × 1.00 = 400,000 compared to Run A.

        Pre-fix: both runs return RWA = 1,000,000; delta = 0 — FAILS.
        Post-fix: delta = 1,000,000 − 600,000 = 400,000 — PASSES.

        Arrange: Run A (no look-through) and Run B (funded-only) results.
        Act:     run_a_rwa − run_b_rwa.
        Assert:  delta ≈ 400,000 (abs=1.0).
        """
        # Arrange
        run_a_rwa = _get_total_rwa(run_a_results)
        run_b_rwa = _get_total_rwa(run_b_results)

        # Assert — FAILS pre-fix (both return 1,000,000, delta = 0)
        assert run_a_rwa - run_b_rwa == pytest.approx(400_000.0, abs=1.0), (
            f"P1.161: Run A RWA ({run_a_rwa:,.0f}) minus Run B RWA ({run_b_rwa:,.0f}) "
            f"should be 400,000 (cash collateral 400k × RW 1.00 saved under look-through). "
            f"Delta = {run_a_rwa - run_b_rwa:,.0f}. "
            f"If delta = 0: look_through_election='funded_only' not yet processed."
        )
