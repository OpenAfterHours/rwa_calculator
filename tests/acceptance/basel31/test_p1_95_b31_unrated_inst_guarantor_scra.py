"""
P1.95 — B31 SCRA-grade dispatch for unrated institution guarantor.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key assertions:
    A GBP 1,000,000 corporate SME loan (5-year maturity, long-term > 3 months) is
    guaranteed 100% by an unrated GB institution.  Under Basel 3.1 Art. 121 the
    guarantor's SCRA grade determines the substituted risk weight.

    The CRM processor must dispatch SCRA-grade correctly:
        Grade A          → RW 40%  — substitution applies (40% < 85%)
        Grade A_ENHANCED → RW 30%  — substitution applies (30% < 85%)
        Grade B          → RW 75%  — substitution applies (75% < 85%)
        Grade C          → RW 150% — no substitution (150% > 85%, borrower RW used)
        null             → no SCRA path — no substitution (borrower RW 85% used)

    Borrower: unrated SME corporate (annual_revenue = GBP 20m < GBP 44m SME threshold)
    → B31 Art. 122(2) → pre_crm_risk_weight = 0.85.

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1(), reporting_date=2027-01-01):
    EAD = 1,000,000 (drawn_amount=1m, interest=0, no CCF)

    Grade A:          risk_weight = 0.40, rwa = 400,000, guarantee_status = SA_RW_SUBSTITUTION
    Grade A_ENHANCED: risk_weight = 0.30, rwa = 300,000, guarantee_status = SA_RW_SUBSTITUTION
    Grade B:          risk_weight = 0.75, rwa = 750,000, guarantee_status = SA_RW_SUBSTITUTION
    Grade C:          risk_weight = 0.85, rwa = 850,000, guarantee_status = GUARANTEE_NOT_APPLIED_NON_BENEFICIAL
    null:             risk_weight = 0.85, rwa = 850,000, guarantee_status = GUARANTEE_NOT_APPLIED_NON_BENEFICIAL

Pre-fix failure mode:
    The engine applies SCRA Grade A (40%) to ALL five guarantors, regardless of their
    actual scra_grade field.  The SCRA grade dispatch in the CRM guarantee processor
    uses Grade A's weight unconditionally.

References:
    - PRA PS1/26 Art. 121 Table 5: SCRA grades and risk weights for unrated institutions
    - PRA PS1/26 Art. 121(1): SCRA Grade A → 40% (>3m), 20% (<=3m)
    - PRA PS1/26 Art. 121(1A): SCRA Grade A_ENHANCED → 30% (>3m), 20% (<=3m)
    - PRA PS1/26 Art. 121(2): SCRA Grade B → 75% (>3m), 50% (<=3m)
    - PRA PS1/26 Art. 121(3): SCRA Grade C → 150% (all maturities)
    - PRA PS1/26 Art. 122(2): unrated SME corporate → 85%
    - PRA PS1/26 Art. 235: SA risk-weight substitution method (RWSM)
    - PRA PS1/26 Art. 237(2)(a): min original maturity of unfunded protection ≥ 1 year
    - tests/fixtures/p1_95/p1_95.py: scenario constants
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
from rwa_calc.data.schemas import (
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_95.p1_95 import (
    EAD,
    EXPECTED_RW_BORROWER,
    EXPECTED_RW_SCRA_A,
    EXPECTED_RW_SCRA_A_ENHANCED,
    EXPECTED_RW_SCRA_B,
    EXPECTED_RW_SCRA_C,
    EXPECTED_RWA_A,
    EXPECTED_RWA_A_ENHANCED,
    EXPECTED_RWA_B,
    EXPECTED_RWA_C,
    EXPECTED_RWA_NULL,
    LOAN_REF_A,
    LOAN_REF_A_ENHANCED,
    LOAN_REF_B,
    LOAN_REF_C,
    LOAN_REF_NULL,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_95"

# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------

_RW_TOL = 1e-6  # absolute on risk_weight
_AMT_TOL = 0.50  # £0.50 absolute on rwa_final / ead_final

# ---------------------------------------------------------------------------
# Guarantee status constants — values the engine emits
# ---------------------------------------------------------------------------

_STATUS_SUBSTITUTION = "SA_RW_SUBSTITUTION"
_STATUS_NOT_BENEFICIAL = "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"

# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Load P1.95 scenario parquets and assemble a RawDataBundle.

    No facilities (loan-only scenario), no ratings (all counterparties unrated
    — forces SCRA path for institution guarantors), no collateral, no provisions.

    facility_mappings and lending_mappings are empty frames with the correct
    schema — no hierarchy rows are needed for this scenario.
    """
    return RawDataBundle(
        facilities=pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loans.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparties.parquet"),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        guarantees=pl.scan_parquet(_FIXTURES_DIR / "guarantees.parquet"),
        ratings=pl.LazyFrame(schema=dtypes_of(RATINGS_SCHEMA)),
    )


# ---------------------------------------------------------------------------
# Pipeline runner — module-scoped to run once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_95_sa_results() -> pl.DataFrame:
    """
    Run P1.95 fixtures through the Basel 3.1 SA pipeline once.

    Returns the collected SA results DataFrame. Module-scoped to avoid
    repeated pipeline invocations.

    Pre-fix: SCRA-grade dispatch is broken — the CRM processor applies
    Grade A's weight (40%) to ALL five guarantors regardless of scra_grade.

    Post-fix: Each guarantor's scra_grade is dispatched correctly per
    PRA PS1/26 Art. 121 Table 5.

    Arrange: five-loan bundle with five SCRA-graded guarantors (A, A_ENHANCED,
             B, C, null), Basel 3.1 SA-only config, reporting_date=2027-01-01.
    Act:     PipelineOrchestrator().run_with_data(bundle, config).
    Return:  collected SA results DataFrame.
    """
    # Arrange
    bundle = _build_bundle()
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 1, 1),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, (
        "P1.95: SA results must not be None for SA-only standardised config. "
        "Check PermissionMode.STANDARDISED and CalculationConfig.basel_3_1()."
    )
    return cast(pl.DataFrame, results.sa_results.collect())


# ---------------------------------------------------------------------------
# Row selector helpers
# ---------------------------------------------------------------------------


def _get_guaranteed_row(df: pl.DataFrame, loan_ref: str) -> dict:
    """
    Return the guaranteed-portion CRM split row for the given loan reference.

    The CRM processor splits a 100%-covered guaranteed loan into:
      - ``<loan_ref>__G_<guarantor>``: guaranteed portion (ead_final = 1,000,000)
      - ``<loan_ref>__REM``: remainder (ead_final = 0, fully covered)

    This helper returns the __G_ row which carries the substituted risk_weight.

    Asserts exactly one __G_ row exists per loan.
    """
    rows = df.filter(
        (pl.col("parent_exposure_reference") == loan_ref)
        & pl.col("exposure_reference").str.contains("__G_")
    ).to_dicts()
    assert len(rows) == 1, (
        f"P1.95: expected exactly 1 guaranteed-portion row for {loan_ref!r}, got {len(rows)}. "
        f"All exposure_references: {df['exposure_reference'].to_list()}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# Test classes — one per SCRA grade
# ---------------------------------------------------------------------------


class TestP195SCRAGradeA:
    """
    P1.95 — SCRA Grade A guarantor (B31 Art. 121(1)): RW 40% (>3m), 20% (<=3m).

    5-year loan (residual maturity >> 3m) → long-term branch → 40%.
    Substitution is beneficial: 40% < borrower RW 85%.

    Grade A is currently handled correctly by the engine (40% is the fallback
    used for all grades). These assertions serve as a regression guard and
    establish the baseline for the discriminating tests below.
    """

    def test_p1_95_scra_grade_a_risk_weight_is_40_pct(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        SCRA Grade A guarantor → risk_weight = 0.40 (Art. 121(1) long-term).

        Arrange: LN_P195_A, 5-year loan, SCRA Grade A guarantor (CP_GUARANTOR_INST_P195_A).
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  risk_weight == 0.40 ± 1e-6.
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_A)

        # Assert
        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_SCRA_A, abs=_RW_TOL), (
            f"P1.95 SCRA Grade A: expected risk_weight={EXPECTED_RW_SCRA_A:.2f} "
            f"(Art. 121(1) >3m long-term), got {row['risk_weight']:.4f}."
        )

    def test_p1_95_scra_grade_a_rwa_is_400k(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        SCRA Grade A: RWA = EAD × 0.40 = 400,000.

        Arrange: LN_P195_A, EAD = 1,000,000.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  rwa_final == 400,000 ± 0.50.
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_A)

        # Assert
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_A, abs=_AMT_TOL), (
            f"P1.95 SCRA Grade A: expected rwa_final={EXPECTED_RWA_A:,.0f} "
            f"(EAD 1,000,000 × 40%), got {row['rwa_final']:,.0f}."
        )

    def test_p1_95_scra_grade_a_guarantee_status_is_substitution(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        SCRA Grade A substitution is beneficial → guarantee_status = SA_RW_SUBSTITUTION.

        Arrange: LN_P195_A, guarantor_rw=0.40 < pre_crm_risk_weight=0.85.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  guarantee_status == "SA_RW_SUBSTITUTION".
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_A)

        # Assert
        assert row["guarantee_status"] == _STATUS_SUBSTITUTION, (
            f"P1.95 SCRA Grade A: expected guarantee_status={_STATUS_SUBSTITUTION!r}, "
            f"got {row['guarantee_status']!r}."
        )

    def test_p1_95_scra_grade_a_ead_is_1m(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        EAD = drawn_amount = 1,000,000 (no CCF, no FX, interest=0).

        Arrange: LN_P195_A, drawn_amount=1,000,000, interest=0.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  ead_final == 1,000,000 ± 0.50.
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_A)

        # Assert
        assert row["ead_final"] == pytest.approx(EAD, abs=_AMT_TOL), (
            f"P1.95 SCRA Grade A: expected ead_final={EAD:,.0f}, got {row['ead_final']:,.0f}."
        )


class TestP195SCRAGradeAEnhanced:
    """
    P1.95 DISCRIMINATING — SCRA Grade A_ENHANCED guarantor: RW 30% (>3m).

    Pre-fix failure: engine returns risk_weight=0.40 (Grade A fallback) instead
    of 0.30 (Grade A_ENHANCED long-term).

    The A_ENHANCED grade is the key discriminator between Grade A (40%) and
    A_ENHANCED (30%). The engine must read scra_grade="A_ENHANCED" from the
    guarantor counterparty and dispatch to the correct weight.

    References: PRA PS1/26 Art. 121(1A).
    """

    def test_p1_95_scra_grade_a_enhanced_risk_weight_is_30_pct(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        DISCRIMINATING: SCRA Grade A_ENHANCED guarantor → risk_weight = 0.30.

        Art. 121(1A): A_ENHANCED requires CET1 >= 14% AND leverage ratio >= 5%.
        Long-term (5y >> 3m) → 30%.

        Pre-fix: engine returns risk_weight = 0.40 (Grade A fallback, SCRA grade
        dispatch broken — uses Grade A weight for all unrated institutions).

        Arrange: LN_P195_A_ENHANCED, 5-year loan, scra_grade="A_ENHANCED" guarantor.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  risk_weight == 0.30 ± 1e-6.
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_A_ENHANCED)

        # Assert — FAILS pre-fix (engine returns 0.40)
        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_SCRA_A_ENHANCED, abs=_RW_TOL), (
            f"P1.95 SCRA Grade A_ENHANCED: expected risk_weight={EXPECTED_RW_SCRA_A_ENHANCED:.2f} "
            f"(Art. 121(1A) >3m long-term A_ENHANCED = 30%). "
            f"Got {row['risk_weight']:.4f}. "
            f"Pre-fix: engine applies Grade A weight (0.40) to all unrated institutions "
            f"regardless of scra_grade. Fix: dispatch on scra_grade='A_ENHANCED' → 0.30."
        )

    def test_p1_95_scra_grade_a_enhanced_rwa_is_300k(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        DISCRIMINATING: SCRA Grade A_ENHANCED → rwa_final = 300,000.

        EAD × 0.30 = 1,000,000 × 0.30 = 300,000.

        Pre-fix: rwa_final = 400,000 (EAD × 0.40, Grade A fallback applied).

        Arrange: LN_P195_A_ENHANCED, EAD = 1,000,000.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  rwa_final == 300,000 ± 0.50.
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_A_ENHANCED)

        # Assert — FAILS pre-fix (engine returns 400,000)
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_A_ENHANCED, abs=_AMT_TOL), (
            f"P1.95 SCRA Grade A_ENHANCED: expected rwa_final={EXPECTED_RWA_A_ENHANCED:,.0f} "
            f"(EAD 1,000,000 × A_ENHANCED 30%). "
            f"Got {row['rwa_final']:,.0f}. "
            f"Pre-fix gives 400,000 (Grade A 40% misapplied). "
            f"Delta = {row['rwa_final'] - EXPECTED_RWA_A_ENHANCED:,.0f} (should be 0 post-fix)."
        )

    def test_p1_95_scra_grade_a_enhanced_guarantee_status_is_substitution(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        A_ENHANCED substitution is beneficial → guarantee_status = SA_RW_SUBSTITUTION.

        30% < borrower RW 85% → substitution applies.

        Arrange: LN_P195_A_ENHANCED, guarantor_rw=0.30 < pre_crm_risk_weight=0.85.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  guarantee_status == "SA_RW_SUBSTITUTION".
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_A_ENHANCED)

        # Assert
        assert row["guarantee_status"] == _STATUS_SUBSTITUTION, (
            f"P1.95 SCRA Grade A_ENHANCED: expected guarantee_status={_STATUS_SUBSTITUTION!r}, "
            f"got {row['guarantee_status']!r}. "
            f"A_ENHANCED RW (30%) < borrower RW (85%) → substitution must apply."
        )

    def test_p1_95_scra_grade_a_enhanced_pre_crm_rw_is_85_pct(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        Borrower pre-CRM risk weight = 0.85 (unrated SME corporate, Art. 122(2)).

        Confirms the borrower baseline is correctly set before guarantee substitution.

        Arrange: CP_BORROWER_P195, entity_type=corporate, annual_revenue=GBP 20m < 44m.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  pre_crm_risk_weight == 0.85 ± 1e-6.
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_A_ENHANCED)

        # Assert
        assert row["pre_crm_risk_weight"] == pytest.approx(EXPECTED_RW_BORROWER, abs=_RW_TOL), (
            f"P1.95: expected pre_crm_risk_weight={EXPECTED_RW_BORROWER:.2f} "
            f"(unrated SME corporate, Art. 122(2) = 85%). "
            f"Got {row['pre_crm_risk_weight']:.4f}."
        )


class TestP195SCRAGradeB:
    """
    P1.95 DISCRIMINATING — SCRA Grade B guarantor: RW 75% (>3m).

    Pre-fix failure: engine returns risk_weight=0.40 (Grade A fallback).
    Post-fix: dispatch on scra_grade='B' → 0.75 (Art. 121(2) long-term).

    Substitution is still beneficial: 75% < borrower RW 85%.
    The guarantee reduces risk weight but not as much as Grade A.

    References: PRA PS1/26 Art. 121(2).
    """

    def test_p1_95_scra_grade_b_risk_weight_is_75_pct(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        DISCRIMINATING: SCRA Grade B guarantor → risk_weight = 0.75.

        Art. 121(2): Grade B (meets minimum regulatory requirements) → 75% (>3m).

        Pre-fix: engine returns risk_weight = 0.40 (Grade A fallback, SCRA grade
        dispatch broken).

        Arrange: LN_P195_B, 5-year loan, scra_grade="B" guarantor.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  risk_weight == 0.75 ± 1e-6.
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_B)

        # Assert — FAILS pre-fix (engine returns 0.40)
        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_SCRA_B, abs=_RW_TOL), (
            f"P1.95 SCRA Grade B: expected risk_weight={EXPECTED_RW_SCRA_B:.2f} "
            f"(Art. 121(2) >3m long-term B = 75%). "
            f"Got {row['risk_weight']:.4f}. "
            f"Pre-fix: engine applies Grade A weight (0.40) regardless of scra_grade. "
            f"Fix: dispatch on scra_grade='B' → 0.75."
        )

    def test_p1_95_scra_grade_b_rwa_is_750k(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        DISCRIMINATING: SCRA Grade B → rwa_final = 750,000.

        EAD × 0.75 = 1,000,000 × 0.75 = 750,000.

        Pre-fix: rwa_final = 400,000 (Grade A 40% misapplied).

        Arrange: LN_P195_B, EAD = 1,000,000.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  rwa_final == 750,000 ± 0.50.
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_B)

        # Assert — FAILS pre-fix (engine returns 400,000)
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_B, abs=_AMT_TOL), (
            f"P1.95 SCRA Grade B: expected rwa_final={EXPECTED_RWA_B:,.0f} "
            f"(EAD 1,000,000 × B 75%). "
            f"Got {row['rwa_final']:,.0f}. "
            f"Pre-fix gives 400,000 (Grade A 40% misapplied)."
        )

    def test_p1_95_scra_grade_b_guarantee_status_is_substitution(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        Grade B substitution is beneficial (75% < 85%) → SA_RW_SUBSTITUTION.

        Arrange: LN_P195_B, guarantor_rw=0.75 < pre_crm_risk_weight=0.85.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  guarantee_status == "SA_RW_SUBSTITUTION".
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_B)

        # Assert
        assert row["guarantee_status"] == _STATUS_SUBSTITUTION, (
            f"P1.95 SCRA Grade B: expected guarantee_status={_STATUS_SUBSTITUTION!r}, "
            f"got {row['guarantee_status']!r}. "
            f"Grade B RW (75%) < borrower RW (85%) → substitution must apply."
        )


class TestP195SCRAGradeC:
    """
    P1.95 DISCRIMINATING — SCRA Grade C guarantor: RW 150% (all maturities).

    Grade C is above the borrower RW (85%) — substitution must NOT be applied.
    The engine must detect that guarantor_rw (150%) > pre_crm_risk_weight (85%)
    and leave the risk weight at the borrower baseline.

    Pre-fix failure: engine applies Grade A fallback (40%) universally, so it
    incorrectly marks the guarantee as beneficial and returns risk_weight=0.40.

    Post-fix: dispatch on scra_grade='C' → guarantor_rw=1.50 > 0.85 → no
    substitution → risk_weight stays at 0.85, guarantee_status = NOT_BENEFICIAL.

    References: PRA PS1/26 Art. 121(3); Art. 235 (substitution only beneficial).
    """

    def test_p1_95_scra_grade_c_risk_weight_is_borrower_85_pct(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        DISCRIMINATING: SCRA Grade C guarantor is non-beneficial → risk_weight = 0.85.

        Guarantor Grade C RW = 150% > borrower RW 85% → CRM processor must not
        substitute. Final risk_weight = pre_crm_risk_weight = 0.85.

        Pre-fix: engine applies Grade A fallback (0.40) and marks as beneficial
                 → risk_weight = 0.40, which is wrong in two ways: wrong grade
                 weight AND wrong beneficial decision.

        Arrange: LN_P195_C, 5-year loan, scra_grade="C" guarantor, borrower RW=0.85.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  risk_weight == 0.85 ± 1e-6.
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_C)

        # Assert — FAILS pre-fix (engine returns 0.40)
        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_BORROWER, abs=_RW_TOL), (
            f"P1.95 SCRA Grade C: expected risk_weight={EXPECTED_RW_BORROWER:.2f} "
            f"(Grade C guarantor RW=150% > borrower RW=85% → no substitution). "
            f"Got {row['risk_weight']:.4f}. "
            f"Pre-fix: engine misapplies Grade A (0.40), treats substitution as beneficial."
        )

    def test_p1_95_scra_grade_c_rwa_is_850k(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        DISCRIMINATING: SCRA Grade C → rwa_final = 850,000 (borrower RW, no substitution).

        EAD × 0.85 = 1,000,000 × 0.85 = 850,000.

        Pre-fix: rwa_final = 400,000 (Grade A 40% misapplied, wrong beneficial decision).

        Arrange: LN_P195_C, EAD = 1,000,000.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  rwa_final == 850,000 ± 0.50.
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_C)

        # Assert — FAILS pre-fix (engine returns 400,000)
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_C, abs=_AMT_TOL), (
            f"P1.95 SCRA Grade C: expected rwa_final={EXPECTED_RWA_C:,.0f} "
            f"(EAD 1,000,000 × borrower RW 85% — Grade C not beneficial). "
            f"Got {row['rwa_final']:,.0f}. "
            f"Pre-fix gives 400,000 (Grade A 40% wrongly substituted)."
        )

    def test_p1_95_scra_grade_c_guarantee_status_is_not_beneficial(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        DISCRIMINATING: Grade C guarantee is non-beneficial → GUARANTEE_NOT_APPLIED_NON_BENEFICIAL.

        Grade C guarantor RW (150%) > borrower baseline RW (85%) → substitution
        would increase capital → CRM processor must flag as non-beneficial.

        Pre-fix: engine wrongly marks Grade A (40%) as beneficial.

        Arrange: LN_P195_C, guarantor_rw=1.50 > pre_crm_risk_weight=0.85.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  guarantee_status == "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL".
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_C)

        # Assert — FAILS pre-fix (engine returns "SA_RW_SUBSTITUTION")
        assert row["guarantee_status"] == _STATUS_NOT_BENEFICIAL, (
            f"P1.95 SCRA Grade C: expected guarantee_status={_STATUS_NOT_BENEFICIAL!r} "
            f"(Grade C RW=150% > borrower RW=85% → non-beneficial). "
            f"Got {row['guarantee_status']!r}. "
            f"Pre-fix: engine misclassifies Grade A (40%) as beneficial."
        )


class TestP195SCRAGradeNull:
    """
    P1.95 DISCRIMINATING — null SCRA grade (no grade assigned).

    When the institution guarantor has no scra_grade (null), there is no SCRA
    substitution path available.  The guarantee cannot be applied, so the
    exposure retains the borrower risk weight (85%).

    Pre-fix failure: engine applies Grade A fallback (40%) even when scra_grade is null.

    Post-fix: null scra_grade → guarantee not applied → risk_weight = 0.85,
    guarantee_status = GUARANTEE_NOT_APPLIED_NON_BENEFICIAL.

    References: PRA PS1/26 Art. 121 (SCRA grades must be assigned for substitution);
                CRE20.21 conservative unrated fallback = 150%, hence > borrower 85%.
    """

    def test_p1_95_scra_null_risk_weight_is_borrower_85_pct(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        DISCRIMINATING: null scra_grade → no substitution → risk_weight = 0.85.

        Guarantor with no SCRA grade cannot be substituted. The engine must
        not apply any SCRA substitution when scra_grade is null.

        Pre-fix: engine applies Grade A fallback (0.40) even when scra_grade is null,
                 incorrectly reducing the risk weight.

        Arrange: LN_P195_NULL, scra_grade=null guarantor, borrower RW=0.85.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  risk_weight == 0.85 ± 1e-6.
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_NULL)

        # Assert — FAILS pre-fix (engine returns 0.40)
        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_BORROWER, abs=_RW_TOL), (
            f"P1.95 SCRA null: expected risk_weight={EXPECTED_RW_BORROWER:.2f} "
            f"(null scra_grade → no SCRA substitution path, borrower RW=85% retained). "
            f"Got {row['risk_weight']:.4f}. "
            f"Pre-fix: engine applies Grade A fallback (0.40) when scra_grade is null."
        )

    def test_p1_95_scra_null_rwa_is_850k(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        DISCRIMINATING: null scra_grade → rwa_final = 850,000 (borrower RW, no substitution).

        EAD × 0.85 = 1,000,000 × 0.85 = 850,000.

        Pre-fix: rwa_final = 400,000 (Grade A 40% misapplied).

        Arrange: LN_P195_NULL, EAD = 1,000,000.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  rwa_final == 850,000 ± 0.50.
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_NULL)

        # Assert — FAILS pre-fix (engine returns 400,000)
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_NULL, abs=_AMT_TOL), (
            f"P1.95 SCRA null: expected rwa_final={EXPECTED_RWA_NULL:,.0f} "
            f"(EAD 1,000,000 × borrower RW 85% — null grade, no substitution). "
            f"Got {row['rwa_final']:,.0f}. "
            f"Pre-fix gives 400,000 (Grade A 40% wrongly applied to null-grade guarantor)."
        )

    def test_p1_95_scra_null_guarantee_status_is_not_beneficial(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        DISCRIMINATING: null scra_grade → guarantee_status = GUARANTEE_NOT_APPLIED_NON_BENEFICIAL.

        No SCRA grade assigned → guarantor falls back to conservative unrated RW
        (CRE20.21, ≥150%) which exceeds borrower RW (85%) → non-beneficial.

        Pre-fix: engine wrongly marks as SA_RW_SUBSTITUTION (Grade A 40% applied).

        Arrange: LN_P195_NULL, scra_grade=null guarantor.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  guarantee_status == "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL".
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_NULL)

        # Assert — FAILS pre-fix (engine returns "SA_RW_SUBSTITUTION")
        assert row["guarantee_status"] == _STATUS_NOT_BENEFICIAL, (
            f"P1.95 SCRA null: expected guarantee_status={_STATUS_NOT_BENEFICIAL!r} "
            f"(null scra_grade → no SCRA path → non-beneficial). "
            f"Got {row['guarantee_status']!r}. "
            f"Pre-fix: engine incorrectly returns SA_RW_SUBSTITUTION."
        )


class TestP195StructuralGuards:
    """
    P1.95 structural regression guards — hold before and after the fix.

    These verify that the guarantee eligibility, EAD computation, exposure
    classification, and pre-CRM risk weight are correct for all five rows.
    They should pass even pre-fix (the bug is in SCRA dispatch, not these paths).
    """

    def test_p1_95_borrower_exposure_class_is_corporate_sme(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        Borrower (annual_revenue=GBP 20m < threshold) is classified as corporate_sme.

        Arrange: CP_BORROWER_P195, entity_type=corporate, annual_revenue=20,000,000 GBP.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row for LN_P195_A.
        Assert:  exposure_class == "corporate_sme".
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_A)

        # Assert
        assert row["exposure_class"] == "corporate_sme", (
            f"P1.95: expected exposure_class='corporate_sme' "
            f"(annual_revenue=GBP 20m < SME threshold), "
            f"got {row['exposure_class']!r}."
        )

    def test_p1_95_guarantor_exposure_class_is_institution(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        Institution guarantor must be classified as 'institution'.

        Arrange: CP_GUARANTOR_INST_P195_A, entity_type=institution, GB.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row for LN_P195_A.
        Assert:  guarantor_exposure_class == "institution".
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_A)

        # Assert
        assert row["guarantor_exposure_class"] == "institution", (
            f"P1.95: expected guarantor_exposure_class='institution', "
            f"got {row['guarantor_exposure_class']!r}."
        )

    def test_p1_95_pre_crm_risk_weight_is_85_pct_for_grade_c(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        Pre-CRM risk weight = 0.85 on Grade C row (unrated SME corporate, Art. 122(2)).

        Confirms the borrower baseline is 85% for the non-substitution case.

        Arrange: LN_P195_C, borrower entity_type=corporate, annual_revenue=GBP 20m.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  pre_crm_risk_weight == 0.85 ± 1e-6.
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_C)

        # Assert
        assert row["pre_crm_risk_weight"] == pytest.approx(EXPECTED_RW_BORROWER, abs=_RW_TOL), (
            f"P1.95 Grade C: expected pre_crm_risk_weight={EXPECTED_RW_BORROWER:.2f} "
            f"(unrated SME corporate, Art. 122(2) = 85%), "
            f"got {row['pre_crm_risk_weight']:.4f}."
        )

    def test_p1_95_guarantor_scra_c_rw_is_150_pct(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        Grade C guarantor_rw = 1.50 (Art. 121(3): SCRA Grade C all maturities = 150%).

        This verifies the guarantor risk weight is correctly looked up as 150%
        even though it is not substituted (because it exceeds the borrower RW).

        Arrange: LN_P195_C, scra_grade="C" guarantor.
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row.
        Assert:  guarantor_rw == 1.50 ± 1e-6.
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_C)

        # Assert — FAILS pre-fix (engine returns guarantor_rw=0.40)
        assert row["guarantor_rw"] == pytest.approx(EXPECTED_RW_SCRA_C, abs=_RW_TOL), (
            f"P1.95 SCRA Grade C: expected guarantor_rw={EXPECTED_RW_SCRA_C:.2f} "
            f"(Art. 121(3) Grade C = 150%). "
            f"Got {row['guarantor_rw']:.4f}. "
            f"Pre-fix: engine uses Grade A weight (0.40) as guarantor_rw for all grades."
        )

    def test_p1_95_approach_applied_is_standardised(
        self,
        p1_95_sa_results: pl.DataFrame,
    ) -> None:
        """
        All exposures use standardised approach (SA-only config).

        Arrange: CalculationConfig.basel_3_1(PermissionMode.STANDARDISED).
        Act:     Basel 3.1 SA pipeline, guaranteed-portion row for LN_P195_A.
        Assert:  approach_applied == "standardised".
        """
        # Arrange
        row = _get_guaranteed_row(p1_95_sa_results, LOAN_REF_A)

        # Assert
        assert row["approach_applied"] == "standardised", (
            f"P1.95: expected approach_applied='standardised', got {row['approach_applied']!r}."
        )
