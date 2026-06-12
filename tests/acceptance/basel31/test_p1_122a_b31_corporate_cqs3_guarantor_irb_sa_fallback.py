"""
P1.122(a) — B31 IRB borrower + null-PD corporate guarantor → SA-fallback; CQS 3 = 75%.

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor → IRBCalculator → Aggregator

Key assertion:
    When a FIRB corporate borrower is covered by an unfunded corporate guarantee whose
    guarantor has pd=None in its rating row, the engine cannot route the guarantor
    through IRB parameter substitution (PSM). It must fall back to the SA risk-weight
    substitution method (RWSM), looking up the guarantor's SA risk weight by CQS.

    Under Basel 3.1 (PRA PS1/26 Art. 122(2) Table 6), corporate CQS 3 = 75%.
    Under CRR (Table 5), corporate CQS 3 = 100%.

    Pre-fix (current engine bug):
        engine/irb/guarantee.py:269-281 `_compute_guarantor_rw_sa` corporate branch
        hardcodes CRR Table 5 values with no `is_basel_3_1` branch, so B31 and CRR
        both yield CQS 3 = 100% → guarantor_rw = 1.00, rwa_final = 1,000,000.

    Post-fix expected (B31):
        guarantor_rw  = 0.75 (Art. 122(2) Table 6)
        risk_weight   = 0.75 (100% covered → blended RW = guarantor_rw)
        rwa_final     = 750,000 (EAD 1,000,000 × 0.75)

    Regression pin (CRR — must pass before AND after fix):
        guarantor_rw  = 1.00 (CRR Table 5)
        risk_weight   = 1.00
        rwa_final     = 1,000,000

    Cross-arm delta (B31_rwa − CRR_rwa):
        Post-fix: CRR_rwa − B31_rwa = 250,000
        Pre-fix (today): CRR_rwa − B31_rwa = 0  ← also FAILS in test_b31_vs_crr_rwa_delta_250k

Routing note:
    The guaranteed sub-row inherits approach=FIRB from the borrower exposure (the CRM
    processor does not change the approach field). The pipeline router places it in the
    IRB branch, so assertions must query irb_results, not sa_results.

References:
    - PRA PS1/26 Art. 122(2) Table 6: Basel 3.1 corporate SA risk weights by CQS
      (CQS 3 = 75%; CRR Table 5 CQS 3 = 100%)
    - PRA PS1/26 Art. 235: SA risk-weight substitution method (RWSM) for guarantees
    - CRR Art. 237(2)(a): unfunded credit protection original maturity ≥ 1 year
    - engine/irb/guarantee.py:269-281: _compute_guarantor_rw_sa corporate branch (bug site)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import FACILITY_MAPPING_SCHEMA, LENDING_MAPPING_SCHEMA
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.conftest import get_guaranteed_row, get_total_rwa
from tests.fixtures.p1_122a.p1_122a import (
    EXPECTED_GUARANTOR_RW_B31,
    EXPECTED_GUARANTOR_RW_CRR,
    EXPECTED_RWA_B31,
    EXPECTED_RWA_CRR,
    LOAN_REF,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Fixture path
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_122a" / "data"

# Pre-fix value (what the engine currently emits, causing the B31 test to fail)
_PREFIX_GUARANTOR_RW_B31 = 1.00  # bug: returns CRR Table 5 value for both frameworks


# ---------------------------------------------------------------------------
# Config factories
# ---------------------------------------------------------------------------


def _b31_irb_config() -> CalculationConfig:
    """Basel 3.1 IRB config (post-go-live, 2027-06-30).

    PermissionMode.IRB activates model-level IRB permissions. The
    MODEL_BORROWER_FIRB model permission row in the fixture grants
    foundation_irb for corporate exposures, routing CP_BORROWER_P1122A
    through F-IRB. The guarantor (CP_GUARANTOR_P1122A) has no model_id →
    it stays on SA, falling through to the SA risk-weight lookup.
    """
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.IRB,
    )


def _crr_irb_config() -> CalculationConfig:
    """CRR IRB config (pre-Basel-3.1 effective date, 2025-12-31).

    Same fixture data routed under CRR. The corporate guarantor CQS 3
    should yield 100% (CRR Table 5) regardless of the B31 fix.
    """
    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle from P1.122(a) parquets.

    All six parquets are loaded:
      - counterparty.parquet: borrower + guarantor (both entity_type="company")
      - facility.parquet:    FAC_P1122A (parent facility for the loan)
      - loan.parquet:        LOAN_P1122A (GBP 1,000,000 senior term loan)
      - guarantee.parquet:   GTE_P1122A (100% coverage by CP_GUARANTOR_P1122A)
      - rating.parquet:      borrower (internal, pd=0.02, model_id=MODEL_BORROWER_FIRB)
                             guarantor (external, cqs=3, pd=None — triggers SA fallback)
      - model_permission.parquet: MODEL_BORROWER_FIRB → corporate/foundation_irb

    facility_mappings and lending_mappings are empty frames (no hierarchy rows needed
    for a single loan/facility pair linked directly via counterparty_reference).
    """
    return make_raw_bundle(
        facilities=pl.scan_parquet(_FIXTURES_DIR / "facility.parquet"),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        guarantees=pl.scan_parquet(_FIXTURES_DIR / "guarantee.parquet"),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        model_permissions=pl.scan_parquet(_FIXTURES_DIR / "model_permission.parquet"),
    )


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline(config: CalculationConfig) -> pl.DataFrame:
    """
    Run the P1.122(a) fixtures through the credit risk pipeline and return
    the IRB results DataFrame.

    The CRM processor splits the guaranteed FIRB loan into two sub-rows:
      - LOAN_P1122A__G_CP_GUARANTOR_P1122A: guaranteed portion (ead_final = 1,000,000)
        approach=FIRB → routed to IRB branch → irb_results
      - LOAN_P1122A__REM: unguaranteed remainder (ead_final = 0 — fully covered)
        approach=FIRB → routed to IRB branch → irb_results

    Returns the collected IRB results DataFrame.
    """
    bundle = _build_bundle()
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.irb_results is not None, (
        "IRB results should not be None — check PermissionMode.IRB config and "
        "that model_permissions.parquet contains MODEL_BORROWER_FIRB."
    )
    return cast(pl.DataFrame, results.irb_results.collect())


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestP1122aB31CorporateCQS3GuarantorIRBSAFallback:
    """
    P1.122(a): B31 IRB borrower with null-PD corporate guarantor SA-fallback.

    The distinguishing scenario from P1.110 (both SA) is that HERE the BORROWER
    is FIRB-eligible (model_id=MODEL_BORROWER_FIRB) but the GUARANTOR lacks an
    internal PD (pd=None in rating row), forcing the engine onto the SA risk-weight
    fallback path in engine/irb/guarantee.py.

    Bug: `_compute_guarantor_rw_sa` (lines 269-281 of irb/guarantee.py) hardcodes
    CRR Table 5 risk weights for the corporate branch with no `is_basel_3_1` branch.
    Under B31, CQS 3 should be 75% (Art. 122(2) Table 6), not 100% (CRR Table 5).

    Three test functions:

    1. test_b31_irb_borrower_with_corporate_cqs3_guarantor_substitutes_at_75pct
       B31 FIRB exposure + CQS 3 SA guarantor → guarantor_rw = 0.75 (post-fix).
       FAILS pre-fix: engine emits 1.00 (CRR value applied to B31 path).

    2. test_crr_irb_borrower_with_corporate_cqs3_guarantor_regression
       CRR FIRB exposure + CQS 3 SA guarantor → guarantor_rw = 1.00.
       PASSES today and must continue to pass after the fix.

    3. test_b31_vs_crr_rwa_delta_250k
       crr_rwa − b31_rwa = 250,000 = 1,000,000 × (1.00 − 0.75).
       FAILS pre-fix: both engines return 1.00 → delta = 0.
    """

    # ------------------------------------------------------------------
    # Class-scoped IRB result fixtures
    # ------------------------------------------------------------------

    @pytest.fixture(scope="class")
    def b31_irb_results(self) -> pl.DataFrame:
        """
        Basel 3.1 IRB pipeline results for P1.122(a).

        Arrange: P1.122(a) parquets — FIRB corporate borrower (pd=0.02),
                 100% corporate guarantee (CQS 3, pd=None), reporting_date=2027-06-30.
        Act:     PipelineOrchestrator with CalculationConfig.basel_3_1(),
                 PermissionMode.IRB, MODEL_BORROWER_FIRB → corporate/foundation_irb.
        Return:  Collected IRB results DataFrame.
        """
        return _run_pipeline(_b31_irb_config())

    @pytest.fixture(scope="class")
    def crr_irb_results(self) -> pl.DataFrame:
        """
        CRR IRB pipeline results for P1.122(a) (regression pin).

        Arrange: Same P1.122(a) parquets, reporting_date=2025-12-31 (CRR era).
        Act:     PipelineOrchestrator with CalculationConfig.crr(), PermissionMode.IRB.
        Return:  Collected IRB results DataFrame.
        """
        return _run_pipeline(_crr_irb_config())

    # ------------------------------------------------------------------
    # B31 DISCRIMINATING ASSERTION — FAILS pre-fix
    # ------------------------------------------------------------------

    def test_b31_irb_borrower_with_corporate_cqs3_guarantor_substitutes_at_75pct(
        self, b31_irb_results: pl.DataFrame
    ) -> None:
        """
        P1.122(a) DISCRIMINATING: B31 FIRB borrower with CQS 3 SA fallback guarantor
        must substitute at 75% (Art. 122(2) Table 6).

        When the FIRB borrower's guarantor has pd=None, the engine falls through to the
        SA risk-weight path in _compute_guarantor_rw_sa. Under B31, corporate CQS 3
        = 75% (PRA PS1/26 Art. 122(2) Table 6). The bug returns 100% (CRR Table 5)
        for both frameworks. Post-fix, B31 must return 0.75.

        Arrange: B31 config, FIRB corporate borrower, corporate CQS 3 guarantor with
                 pd=None, 100% coverage, EAD = 1,000,000.
        Act:     IRB results for LOAN_P1122A guaranteed-portion sub-row.
        Assert:  risk_weight ≈ 0.75 (B31 Art. 122(2) Table 6 CQS 3).
                 rwa_final   ≈ 750,000 (EAD 1,000,000 × 0.75).

        PRE-FIX (today): risk_weight = 1.00, rwa_final = 1,000,000 → test FAILS.
        POST-FIX:        risk_weight = 0.75, rwa_final = 750,000  → test passes.
        """
        # Arrange
        row = get_guaranteed_row(b31_irb_results, LOAN_REF)

        # Assert risk weight — FAILS pre-fix (engine returns 1.00)
        actual_rw = row["risk_weight"]
        assert actual_rw == pytest.approx(EXPECTED_GUARANTOR_RW_B31, rel=1e-4), (
            f"P1.122(a) B31: guaranteed-portion risk_weight should be "
            f"{EXPECTED_GUARANTOR_RW_B31:.2f} "
            f"(PRA PS1/26 Art. 122(2) Table 6: corporate CQS 3 = 75%). "
            f"Got {actual_rw:.4f}. "
            f"Pre-fix value ~{_PREFIX_GUARANTOR_RW_B31:.2f} means "
            f"_compute_guarantor_rw_sa reads CRR Table 5 (100%) for the B31 path "
            f"(engine/irb/guarantee.py:269-281 missing is_basel_3_1 branch)."
        )

        # Assert RWA — also FAILS pre-fix
        actual_rwa = row["rwa_final"]
        assert actual_rwa == pytest.approx(EXPECTED_RWA_B31, rel=1e-4), (
            f"P1.122(a) B31: guaranteed-portion rwa_final should be "
            f"{EXPECTED_RWA_B31:,.0f} "
            f"(EAD 1,000,000 × guarantor_rw 0.75). "
            f"Got {actual_rwa:,.0f}. "
            f"Pre-fix: rwa = 1,000,000 (CRR 100% applied to B31 path, "
            f"overstating capital by 250,000)."
        )

    # ------------------------------------------------------------------
    # CRR REGRESSION PIN — must PASS before and after fix
    # ------------------------------------------------------------------

    def test_crr_irb_borrower_with_corporate_cqs3_guarantor_regression(
        self, crr_irb_results: pl.DataFrame
    ) -> None:
        """
        P1.122(a) CRR regression: FIRB borrower with CQS 3 SA fallback guarantor
        must substitute at 100% (CRR Table 5). Must pass before AND after the fix.

        CRR Art. 120/122 Table 5: corporate CQS 3 SA risk weight = 100%.
        The B31 fix must not change the CRR table routing. After the fix, B31 uses
        75% but CRR must still return 100%.

        Arrange: CRR config, same P1.122(a) parquets.
        Act:     IRB results for LOAN_P1122A guaranteed-portion sub-row.
        Assert:  risk_weight ≈ 1.00 (CRR Table 5 CQS 3).
                 rwa_final   ≈ 1,000,000 (EAD 1,000,000 × 1.00).
        """
        # Arrange
        row = get_guaranteed_row(crr_irb_results, LOAN_REF)

        # Assert risk weight — regression pin
        actual_rw = row["risk_weight"]
        assert actual_rw == pytest.approx(EXPECTED_GUARANTOR_RW_CRR, rel=1e-4), (
            f"P1.122(a) CRR regression: guaranteed-portion risk_weight should be "
            f"{EXPECTED_GUARANTOR_RW_CRR:.2f} (CRR Table 5: corporate CQS 3 = 100%). "
            f"Got {actual_rw:.4f}. "
            f"The B31 fix must not change CRR Table 5 routing."
        )

        # Assert RWA — regression pin
        actual_rwa = row["rwa_final"]
        assert actual_rwa == pytest.approx(EXPECTED_RWA_CRR, rel=1e-4), (
            f"P1.122(a) CRR regression: guaranteed-portion rwa_final should be "
            f"{EXPECTED_RWA_CRR:,.0f} (EAD 1,000,000 × guarantor_rw 1.00). "
            f"Got {actual_rwa:,.0f}."
        )

    # ------------------------------------------------------------------
    # CROSS-ARM DELTA — structural validation; FAILS pre-fix
    # ------------------------------------------------------------------

    def test_b31_vs_crr_rwa_delta_250k(
        self,
        b31_irb_results: pl.DataFrame,
        crr_irb_results: pl.DataFrame,
    ) -> None:
        """
        P1.122(a): CRR total RWA − B31 total RWA = 250,000 (post-fix).

        Delta = EAD × (CRR_guarantor_rw − B31_guarantor_rw) × coverage
              = 1,000,000 × (1.00 − 0.75) × 1.00 = 250,000.

        Pre-fix: both frameworks return 1.00 for CQS 3 → delta = 0 → FAILS.
        Post-fix: B31 returns 0.75, CRR returns 1.00 → delta = 250,000 → passes.

        Arrange: B31 and CRR IRB results for LOAN_P1122A with 100% guarantee.
        Act:     crr_total_rwa − b31_total_rwa.
        Assert:  delta ≈ 250,000 (abs=1.0).
        """
        # Arrange
        b31_rwa = get_total_rwa(b31_irb_results, LOAN_REF)
        crr_rwa = get_total_rwa(crr_irb_results, LOAN_REF)

        # Assert — FAILS pre-fix (both frameworks return 1,000,000, delta = 0)
        delta = crr_rwa - b31_rwa
        assert delta == pytest.approx(250_000.0, abs=1.0), (
            f"P1.122(a): CRR RWA ({crr_rwa:,.0f}) − B31 RWA ({b31_rwa:,.0f}) "
            f"should be 250,000 = 1,000,000 × (1.00 − 0.75). "
            f"Got delta = {delta:,.0f}. "
            f"If delta = 0: B31 guarantor SA RW lookup still reads CRR Table 5 (100%) "
            f"— fix engine/irb/guarantee.py:269-281 to branch on is_basel_3_1."
        )
