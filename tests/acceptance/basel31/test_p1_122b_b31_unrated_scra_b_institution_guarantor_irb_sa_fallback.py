"""
P1.122(b) — B31 IRB borrower + unrated SCRA-B institution guarantor → SA-fallback; RW=0.75.

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor → IRBCalculator → Aggregator

Key assertion:
    When a FIRB corporate borrower is covered by an unfunded institution guarantee whose
    guarantor has cqs=None (no ECAI rating) and scra_grade="B" on its counterparty row,
    the engine must route the guarantor through the SCRA path in the SA risk-weight
    substitution fallback (engine/irb/guarantee.py).

    Under Basel 3.1 (PRA PS1/26 Art. 121 Table 5), SCRA Grade B with residual maturity
    >3 months = 75%.

    Pre-fix (current engine bug):
        engine/irb/guarantee.py:272 calls
        ``build_institution_guarantor_rw_expr("guarantor_cqs", config.is_basel_3_1)``
        without passing ``scra_grade_col``. With ``scra_grade_col=None``, ``use_scra``
        is False and the function falls through to
        ``INSTITUTION_RISK_WEIGHTS_B31_ECRA[CQS.UNRATED] = 0.40``.
        Result: guarantor_rw = 0.40, rwa_final = 400,000.

    Post-fix expected (B31):
        ``scra_grade_col="guarantor_scra_grade"`` must be passed so unrated rows
        (null CQS) dispatch via the SCRA branch in ``build_institution_guarantor_rw_expr``.
        SCRA Grade B → Art. 121 Table 5 long-term = 75%.
        risk_weight   = 0.75
        rwa_final     = 750,000 (EAD 1,000,000 × 0.75)

    Regression pin (CRR — must pass before AND after fix):
        CRR has no SCRA. Unrated institution under CRR →
        ``INSTITUTION_RISK_WEIGHTS_CRR[CQS.UNRATED] = 1.00``.
        risk_weight   = 1.00
        rwa_final     = 1,000,000

    Cross-arm delta (CRR_rwa − B31_rwa):
        Post-fix: 1,000,000 − 750,000 = 250,000.
        Pre-fix:  1,000,000 − 400,000 = 600,000 (B31 test fails; delta wrong).

Routing note:
    The guaranteed sub-row inherits approach=FIRB from the borrower exposure (the CRM
    processor does not change the approach field). The pipeline router places it in the
    IRB branch, so assertions must query irb_results, not sa_results.

References:
    - PRA PS1/26 Art. 121 Table 5: SCRA Grade B long-term (>3m) = 75%
    - PRA PS1/26 Art. 235: SA risk-weight substitution method (RWSM) for guarantees
    - CRR Art. 237(2)(a): original maturity of unfunded credit protection ≥ 1 year
    - src/rwa_calc/data/tables/crr_risk_weights.py: build_institution_guarantor_rw_expr
      (bug site: missing scra_grade_col argument on line 272 of engine/irb/guarantee.py)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.conftest import get_guaranteed_row, get_total_rwa
from tests.fixtures.p1_122b.p1_122b import (
    EXPECTED_GUARANTOR_RW_B31,
    EXPECTED_GUARANTOR_RW_B31_PRE_FIX,
    EXPECTED_RWA_B31,
    EXPECTED_RWA_B31_PRE_FIX,
    LOAN_REF,
    load_p1_122b_bundle,
)

# ---------------------------------------------------------------------------
# Expected CRR values (CRR unrated institution = 1.00, Art. 121 fallback)
# ---------------------------------------------------------------------------

_EXPECTED_GUARANTOR_RW_CRR: float = 1.00  # INSTITUTION_RISK_WEIGHTS_CRR[CQS.UNRATED]
_EXPECTED_RWA_CRR: float = 1_000_000.0  # EAD 1,000,000 × 1.00

# Pre-fix value (what the B31 engine currently emits — SCRA grade not dispatched)
_PREFIX_GUARANTOR_RW_B31: float = EXPECTED_GUARANTOR_RW_B31_PRE_FIX  # 0.40

# Guarantee status string emitted by CRM processor on beneficial substitution
_STATUS_SUBSTITUTION: str = "SA_RW_SUBSTITUTION"


# ---------------------------------------------------------------------------
# Config factories
# ---------------------------------------------------------------------------


def _b31_irb_config() -> CalculationConfig:
    """Basel 3.1 IRB config (post-go-live, 2027-06-30).

    PermissionMode.IRB activates model-level IRB permissions. The
    MODEL_BORROWER_FIRB model permission row in the fixture grants
    foundation_irb for corporate exposures, routing CP_BORROWER_P1122B
    through F-IRB. The guarantor (CP_GUARANTOR_P1122B) has no model_id →
    it stays on SA, falling through to the institution SCRA lookup.
    """
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.IRB,
    )


def _crr_irb_config() -> CalculationConfig:
    """CRR IRB config (pre-Basel-3.1 effective date, 2025-12-31).

    Same fixture data routed under CRR. The unrated institution guarantor has
    no SCRA under CRR — fallback is INSTITUTION_RISK_WEIGHTS_CRR[CQS.UNRATED]
    = 100%.
    """
    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline(config: CalculationConfig) -> pl.DataFrame:
    """
    Run the P1.122(b) fixtures through the credit risk pipeline and return
    the IRB results DataFrame.

    The CRM processor splits the guaranteed FIRB loan into two sub-rows:
      - LOAN_P1122B__G_CP_GUARANTOR_P1122B: guaranteed portion (ead_final = 1,000,000)
        approach=FIRB → routed to IRB branch → irb_results
      - LOAN_P1122B__REM: unguaranteed remainder (ead_final = 0 — fully covered)
        approach=FIRB → routed to IRB branch → irb_results

    Returns the collected IRB results DataFrame.
    """
    bundle = load_p1_122b_bundle()
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.irb_results is not None, (
        "IRB results should not be None — check PermissionMode.IRB config and "
        "that model_permissions.parquet contains MODEL_BORROWER_FIRB."
    )
    return results.irb_results.collect()


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestP1122bB31UnratedScraBInstitutionGuarantorIRBSAFallback:
    """
    P1.122(b): B31 IRB borrower with unrated SCRA-B institution guarantor SA-fallback.

    The distinguishing scenario from P1.95 (both SA) and P1.122(a) (corporate CQS fallback)
    is that HERE the BORROWER is FIRB-eligible (model_id=MODEL_BORROWER_FIRB) and the
    GUARANTOR is an institution with scra_grade="B" and cqs=None (no ECAI rating).

    Bug: engine/irb/guarantee.py:272 calls
        ``build_institution_guarantor_rw_expr("guarantor_cqs", config.is_basel_3_1)``
    without ``scra_grade_col``. Without that argument, ``use_scra`` is False and null
    CQS rows fall through to ``INSTITUTION_RISK_WEIGHTS_B31_ECRA[CQS.UNRATED] = 0.40``.

    Post-fix: pass ``scra_grade_col="guarantor_scra_grade"`` so SCRA-B maps to 75%.

    Three test functions:

    1. test_b31_irb_borrower_with_unrated_scra_b_institution_guarantor_substitutes_at_75pct
       B31 FIRB exposure + SCRA-B institution SA guarantor → risk_weight = 0.75 (post-fix).
       FAILS pre-fix: engine emits 0.40 (B31 ECRA unrated fallback, SCRA grade not dispatched).

    2. test_crr_irb_borrower_with_unrated_institution_guarantor_regression
       CRR FIRB exposure + unrated institution guarantor → risk_weight = 1.00.
       CRR has no SCRA: INSTITUTION_RISK_WEIGHTS_CRR[CQS.UNRATED] = 1.00.
       PASSES today and must continue to pass after the fix.

    3. test_b31_vs_crr_rwa_delta_250k
       crr_rwa − b31_rwa = 250,000 post-fix.
       FAILS pre-fix: B31 returns 400,000 (not 750,000) → delta = 600,000 (not 250,000).
    """

    # ------------------------------------------------------------------
    # Class-scoped IRB result fixtures
    # ------------------------------------------------------------------

    @pytest.fixture(scope="class")
    def b31_irb_results(self) -> pl.DataFrame:
        """
        Basel 3.1 IRB pipeline results for P1.122(b).

        Arrange: P1.122(b) parquets — FIRB corporate borrower (pd=0.02),
                 100% institution guarantee (scra_grade="B", cqs=None),
                 reporting_date=2027-06-30.
        Act:     PipelineOrchestrator with CalculationConfig.basel_3_1(),
                 PermissionMode.IRB, MODEL_BORROWER_FIRB → corporate/foundation_irb.
        Return:  Collected IRB results DataFrame.
        """
        return _run_pipeline(_b31_irb_config())

    @pytest.fixture(scope="class")
    def crr_irb_results(self) -> pl.DataFrame:
        """
        CRR IRB pipeline results for P1.122(b) (regression pin).

        Arrange: Same P1.122(b) parquets, reporting_date=2025-12-31 (CRR era).
        Act:     PipelineOrchestrator with CalculationConfig.crr(), PermissionMode.IRB.
        Return:  Collected IRB results DataFrame.
        """
        return _run_pipeline(_crr_irb_config())

    # ------------------------------------------------------------------
    # B31 DISCRIMINATING ASSERTION — FAILS pre-fix
    # ------------------------------------------------------------------

    def test_b31_irb_borrower_with_unrated_scra_b_institution_guarantor_substitutes_at_75pct(
        self, b31_irb_results: pl.DataFrame
    ) -> None:
        """
        P1.122(b) DISCRIMINATING: B31 FIRB borrower with unrated SCRA-B institution
        guarantor must substitute at 75% (Art. 121 Table 5 long-term).

        When the FIRB borrower's institution guarantor has cqs=None and scra_grade="B",
        the engine must route through the SCRA fallback in
        ``build_institution_guarantor_rw_expr``. Under B31, SCRA Grade B (>3m) = 75%.
        The bug returns 40% (ECRA unrated fallback) because ``scra_grade_col`` is not
        passed to the IRB SA-fallback path. Post-fix, B31 must return 0.75.

        Arrange: B31 config, FIRB corporate borrower (pd=0.02), institution guarantor
                 (scra_grade="B", cqs=None, pd=None), 100% coverage, EAD = 1,000,000.
        Act:     IRB results for LOAN_P1122B guaranteed-portion sub-row.
        Assert:  risk_weight  ≈ 0.75 (B31 Art. 121 Table 5, SCRA-B >3m).
                 rwa_final    ≈ 750,000 (EAD 1,000,000 × 0.75).
                 ead_final    ≈ 1,000,000.
                 guarantee_status == "SA_RW_SUBSTITUTION".

        PRE-FIX (today): risk_weight = 0.40, rwa_final = 400,000 → test FAILS.
        POST-FIX:        risk_weight = 0.75, rwa_final = 750,000  → test passes.
        """
        # Arrange
        row = get_guaranteed_row(b31_irb_results, LOAN_REF)

        # Assert risk weight — FAILS pre-fix (engine returns 0.40)
        actual_rw = row["risk_weight"]
        assert actual_rw == pytest.approx(EXPECTED_GUARANTOR_RW_B31, rel=1e-4), (
            f"P1.122(b) B31: guaranteed-portion risk_weight should be "
            f"{EXPECTED_GUARANTOR_RW_B31:.2f} "
            f"(PRA PS1/26 Art. 121 Table 5: SCRA Grade B >3m = 75%). "
            f"Got {actual_rw:.4f}. "
            f"Pre-fix value ~{_PREFIX_GUARANTOR_RW_B31:.2f} means "
            f"engine/irb/guarantee.py:272 calls build_institution_guarantor_rw_expr "
            f"without scra_grade_col — null CQS falls through to B31 ECRA unrated "
            f"fallback (0.40) instead of dispatching via SCRA grade."
        )

        # Assert RWA — also FAILS pre-fix
        actual_rwa = row["rwa_final"]
        assert actual_rwa == pytest.approx(EXPECTED_RWA_B31, rel=1e-4), (
            f"P1.122(b) B31: guaranteed-portion rwa_final should be "
            f"{EXPECTED_RWA_B31:,.0f} "
            f"(EAD 1,000,000 × SCRA-B 0.75). "
            f"Got {actual_rwa:,.0f}. "
            f"Pre-fix: rwa = {EXPECTED_RWA_B31_PRE_FIX:,.0f} (ECRA unrated 40% applied "
            f"to B31 path, understating capital relief by "
            f"{EXPECTED_RWA_B31 - EXPECTED_RWA_B31_PRE_FIX:,.0f})."
        )

        # Assert EAD — structural: no CCF, no FX, full drawn amount
        actual_ead = row["ead_final"]
        assert actual_ead == pytest.approx(1_000_000.0, rel=1e-4), (
            f"P1.122(b) B31: guaranteed-portion ead_final should be 1,000,000 "
            f"(drawn=1m, interest=0, CCF=1.0). Got {actual_ead:,.0f}."
        )

        # Assert guarantee status — substitution is beneficial (0.75 < borrower FIRB RW)
        actual_status = row["guarantee_status"]
        assert actual_status == _STATUS_SUBSTITUTION, (
            f"P1.122(b) B31: guaranteed-portion guarantee_status should be "
            f"{_STATUS_SUBSTITUTION!r} (SCRA-B 75% < borrower FIRB RW → beneficial). "
            f"Got {actual_status!r}."
        )

    # ------------------------------------------------------------------
    # CRR REGRESSION PIN — must PASS before and after fix
    # ------------------------------------------------------------------

    def test_crr_irb_borrower_with_unrated_institution_guarantor_regression(
        self, crr_irb_results: pl.DataFrame
    ) -> None:
        """
        P1.122(b) CRR regression: FIRB borrower with unrated institution guarantor
        must substitute at 100% (CRR Art. 121 fallback for unrated institution).

        CRR has no SCRA mechanism. An unrated institution under CRR falls through to
        INSTITUTION_RISK_WEIGHTS_CRR[CQS.UNRATED] = 1.00. The B31 fix (adding
        scra_grade_col to the IRB SA-fallback) must not change the CRR path.

        Arrange: CRR config, same P1.122(b) parquets.
        Act:     IRB results for LOAN_P1122B guaranteed-portion sub-row.
        Assert:  risk_weight ≈ 1.00 (CRR unrated institution fallback).
                 rwa_final   ≈ 1,000,000 (EAD 1,000,000 × 1.00).
        """
        # Arrange
        row = get_guaranteed_row(crr_irb_results, LOAN_REF)

        # Assert risk weight — CRR regression pin
        actual_rw = row["risk_weight"]
        assert actual_rw == pytest.approx(_EXPECTED_GUARANTOR_RW_CRR, rel=1e-4), (
            f"P1.122(b) CRR regression: guaranteed-portion risk_weight should be "
            f"{_EXPECTED_GUARANTOR_RW_CRR:.2f} "
            f"(CRR Art. 121: unrated institution fallback = 100%). "
            f"Got {actual_rw:.4f}. "
            f"The B31 SCRA fix must not change CRR routing."
        )

        # Assert RWA — CRR regression pin
        actual_rwa = row["rwa_final"]
        assert actual_rwa == pytest.approx(_EXPECTED_RWA_CRR, rel=1e-4), (
            f"P1.122(b) CRR regression: guaranteed-portion rwa_final should be "
            f"{_EXPECTED_RWA_CRR:,.0f} (EAD 1,000,000 × CRR unrated 1.00). "
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
        P1.122(b): CRR total RWA − B31 total RWA = 250,000 (post-fix).

        Delta = EAD × (CRR_guarantor_rw − B31_guarantor_rw) × coverage
              = 1,000,000 × (1.00 − 0.75) × 1.00 = 250,000.

        Pre-fix: B31 engine returns 0.40 (ECRA unrated fallback, SCRA not dispatched)
        → B31 rwa = 400,000, delta = 1,000,000 − 400,000 = 600,000 → FAILS.
        Post-fix: B31 returns 0.75 → delta = 1,000,000 − 750,000 = 250,000 → passes.

        Arrange: B31 and CRR IRB results for LOAN_P1122B with 100% guarantee.
        Act:     crr_total_rwa − b31_total_rwa.
        Assert:  delta ≈ 250,000 (abs=1.0).
        """
        # Arrange
        b31_rwa = get_total_rwa(b31_irb_results, LOAN_REF)
        crr_rwa = get_total_rwa(crr_irb_results, LOAN_REF)

        # Assert — FAILS pre-fix (B31 returns 400,000 → delta = 600,000)
        delta = crr_rwa - b31_rwa
        assert delta == pytest.approx(250_000.0, abs=1.0), (
            f"P1.122(b): CRR RWA ({crr_rwa:,.0f}) − B31 RWA ({b31_rwa:,.0f}) "
            f"should be 250,000 = 1,000,000 × (1.00 − 0.75). "
            f"Got delta = {delta:,.0f}. "
            f"If delta = 600,000: B31 IRB SA-fallback still uses ECRA unrated (0.40) "
            f"instead of SCRA Grade B (0.75) — fix engine/irb/guarantee.py to pass "
            f"scra_grade_col='guarantor_scra_grade' to build_institution_guarantor_rw_expr."
        )
