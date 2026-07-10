"""
P1.223 — Art. 120(3)(c) Obligor-Level Short-Term Rating Spillover.

Acceptance scenario: a single institution obligor (INST-001, entity_type=bank)
carries three unsecured GBP loans. One short-term facility (FAC-A) has a
dedicated issue-specific short-term ECAI assessment (Table 4A, CQS 3 -> 100%)
that is LESS FAVOURABLE than the obligor's general preferential short-term
treatment under Table 4 (CQS 2 -> 20%). Art. 120(3)(c) (PS1/26; CRR twin
identical in substance) requires that when this happens, the general
preferential short-term treatment is DISAPPLIED for ALL of that obligor's
unrated short-term claims -- not just the specifically-rated exposure.

The engine currently applies the short-term rating override strictly
per-exposure (``apply_short_term_rating_override``,
``engine/stages/hierarchy/enrich.py:160-240``, scoped by
``(scope_type, scope_id)``). LN-A (rated) correctly gets 100%. LN-B (same
obligor, unrated, also short-term) incorrectly keeps the general
preferential 20% instead of spilling over to 100%. LN-C is a long-term claim
on the same obligor and must NOT be affected by the short-term spillover --
it is a negative control.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator
    -> OutputAggregator

Headline fail-first assertion:
    LN-B risk_weight == 1.00 and rwa_final == 2,000,000
    (pre-fix engine returns risk_weight == 0.20, rwa_final == 400,000).

Hand calculation (Basel 3.1, CalculationConfig.basel_3_1()):
    LN-A: EAD 1,000,000; RW Table 4A CQS3 = 1.00; RWA 1,000,000; K  80,000
    LN-B: EAD 2,000,000; RW spillover     = 1.00; RWA 2,000,000; K 160,000
          (pre-fix RW Table 4 CQS2 = 0.20; RWA 400,000; K 32,000)
    LN-C: EAD 4,000,000; RW long-term ECRA CQS2 = 0.30; RWA 1,200,000; K 96,000

CRR twin (CalculationConfig.crr(), same fixtures): LN-A / LN-B numerically
identical (Art. 131 Table 7 CQS3 = 100%; Table 4 CQS2 = 20% -> spillover
100%). LN-C differs -- long-term Table 3 institution CQS2 = 50% (vs 30%
under B31):
    LN-C: EAD 4,000,000; RW = 0.50; RWA 2,000,000; K 160,000

References:
    PRA PS1/26 Art. 120(3)(c): obligor-level short-term spillover.
    PRA PS1/26 Art. 120(2) Table 4: general preferential short-term.
    PRA PS1/26 Art. 120(2B) Table 4A: short-term ECAI assessment.
    CRR Art. 120(3)(c) + Art. 120(2) Table 4 + Art. 131 Table 7.
    src/rwa_calc/engine/stages/hierarchy/enrich.py:160-240
        (apply_short_term_rating_override -- per-exposure scoping; fix target).
    src/rwa_calc/engine/sa/risk_weights.py:634-702, :818-867
        (institution maturity branches, B31 / CRR).
    tests/fixtures/p1_223/p1_223.py: fixture constants + hand-calc.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest

from tests.fixtures.p1_223.p1_223 import (
    LOAN_REF_A,
    LOAN_REF_B,
    LOAN_REF_C,
    REPORTING_DATE_GUIDANCE,
)
from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_223"

# ---------------------------------------------------------------------------
# Expected outputs (local to this test module -- not a fixture edit)
# ---------------------------------------------------------------------------

# Basel 3.1 (PRA PS1/26 Art. 120(3)(c), Table 4/4A, Table 3 institution CQS2).
EXPECTED_B31 = {
    LOAN_REF_A: {"risk_weight": 1.00, "ead_final": 1_000_000.0, "rwa_final": 1_000_000.0},
    LOAN_REF_B: {"risk_weight": 1.00, "ead_final": 2_000_000.0, "rwa_final": 2_000_000.0},
    LOAN_REF_C: {"risk_weight": 0.30, "ead_final": 4_000_000.0, "rwa_final": 1_200_000.0},
}

# CRR twin (Art. 120(3)(c), Art. 120(2) Table 4, Art. 131 Table 7). Only
# LN-C's long-term institution risk weight differs from Basel 3.1 (50% vs 30%).
EXPECTED_CRR = {
    LOAN_REF_A: {"risk_weight": 1.00, "ead_final": 1_000_000.0, "rwa_final": 1_000_000.0},
    LOAN_REF_B: {"risk_weight": 1.00, "ead_final": 2_000_000.0, "rwa_final": 2_000_000.0},
    LOAN_REF_C: {"risk_weight": 0.50, "ead_final": 4_000_000.0, "rwa_final": 2_000_000.0},
}


# ---------------------------------------------------------------------------
# Shared multi-loan pipeline runner
# ---------------------------------------------------------------------------


def _run_p1223_sa_results(config: CalculationConfig) -> pl.DataFrame:
    """
    Run the P1.223 three-loan fixture through the SA pipeline and return
    the collected SA results DataFrame.

    Builds a RawDataBundle directly from the scenario-local parquets
    (counterparty, facility, loan, rating) plus the 3-row facility_mapping
    parquet linking each loan to its parent facility. This is a
    scenario-local multi-loan runner -- ``run_sa_single_loan_result``
    asserts exactly one result row, which does not fit this 3-loan
    obligor-spillover scenario.

    Args:
        config: Basel 3.1 or CRR CalculationConfig (SA-only permission mode).

    Returns:
        The full SA results DataFrame (one row per loan), to be filtered
        per ``exposure_reference`` by the caller.
    """
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    # Arrange -- load scenario-local parquets
    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet")
    facilities = pl.scan_parquet(_FIXTURES_DIR / "facility.parquet")
    loans = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet")
    ratings = pl.scan_parquet(_FIXTURES_DIR / "rating.parquet")
    facility_mappings = pl.scan_parquet(_FIXTURES_DIR / "facility_mapping.parquet")

    bundle = make_raw_bundle(
        facilities=facilities,
        loans=loans,
        counterparties=counterparties,
        facility_mappings=facility_mappings,
        ratings=ratings,
    )

    # Act -- run full SA pipeline
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, "SA results must not be None for SA-only config"

    return results.sa_results.collect()


@pytest.fixture(scope="module")
def p1_223_b31_sa_results() -> pl.DataFrame:
    """Run the P1.223 fixture through the Basel 3.1 SA pipeline (module-scoped)."""
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode

    config = CalculationConfig.basel_3_1(
        reporting_date=REPORTING_DATE_GUIDANCE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return _run_p1223_sa_results(config)


@pytest.fixture(scope="module")
def p1_223_crr_sa_results() -> pl.DataFrame:
    """Run the P1.223 fixture through the CRR SA pipeline (module-scoped)."""
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode

    config = CalculationConfig.crr(
        reporting_date=REPORTING_DATE_GUIDANCE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return _run_p1223_sa_results(config)


def _row_for(df: pl.DataFrame, exposure_reference: str) -> dict:
    """Return the single SA result row for ``exposure_reference`` as a dict."""
    rows = df.filter(pl.col("exposure_reference") == exposure_reference).to_dicts()
    assert len(rows) == 1, (
        f"Expected exactly 1 row for {exposure_reference!r}, got {len(rows)}. "
        f"All exposure_references: {df['exposure_reference'].to_list()}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# P1.223 acceptance tests -- Basel 3.1
# ---------------------------------------------------------------------------


class TestP1223Art1203cObligorShortTermSpilloverB31:
    """
    P1.223 (Basel 3.1): obligor-level short-term rating spillover, Art. 120(3)(c).

    INST-001's issue-specific short-term ECAI assessment on FAC-A
    (Table 4A CQS3 -> 100%) is LESS favourable than the obligor's general
    preferential short-term treatment (Table 4 CQS2 -> 20%). This disapplies
    the general preferential treatment for ALL of INST-001's unrated
    short-term claims (LN-B) -- not just the rated exposure (LN-A). LN-C is
    a long-term claim on the same obligor and is unaffected (negative
    control).
    """

    def test_p1_223_ln_b_obligor_spillover_risk_weight_and_rwa(
        self,
        p1_223_b31_sa_results: pl.DataFrame,
    ) -> None:
        """
        Headline fail-first assertion: LN-B spills over to the worse
        short-term ECAI risk weight (100%), not the general preferential
        20%.

        Arrange: INST-001, unrated short-term claim LN-B (GBP 2,000,000),
                 same obligor as LN-A's issue-specific ST rating (CQS3,
                 Table 4A -> 100%) which is less favourable than the
                 obligor's general preferential ST rating (Table 4 CQS2 ->
                 20%).
        Act:     Basel 3.1 SA pipeline (CalculationConfig.basel_3_1()).
        Assert:  risk_weight == 1.00, rwa_final == 2,000,000.

        Pre-fix (bug): engine returns risk_weight == 0.20,
        rwa_final == 400,000 -- the per-exposure-only override leaves
        LN-B on the general preferential Table 4 path.

        References:
            PRA PS1/26 Art. 120(3)(c): obligor-level ST spillover.
        """
        # Arrange
        row = _row_for(p1_223_b31_sa_results, LOAN_REF_B)
        expected = EXPECTED_B31[LOAN_REF_B]

        # Assert
        assert row["risk_weight"] == pytest.approx(expected["risk_weight"], abs=1e-4), (
            f"P1.223 Art. 120(3)(c): expected LN-B risk_weight="
            f"{expected['risk_weight']:.2f} (obligor spillover to Table 4A "
            f"worst-ST-assessment RW), got {row['risk_weight']:.4f} "
            f"(pre-fix engine incorrectly applies general preferential "
            f"Table 4 = 0.20 per-exposure only)"
        )
        assert row["rwa_final"] == pytest.approx(expected["rwa_final"], rel=1e-4), (
            f"P1.223: expected LN-B rwa_final={expected['rwa_final']:,.0f} "
            f"(EAD 2,000,000 x 100% spillover RW), got {row['rwa_final']:,.0f} "
            f"(pre-fix engine returns 400,000 = EAD x 20% Table 4 fallback)"
        )

    def test_p1_223_ln_a_issue_specific_rating_unaffected(
        self,
        p1_223_b31_sa_results: pl.DataFrame,
    ) -> None:
        """
        Regression guard: LN-A (the FAC-A-scoped issue-specific ST rating
        target) is unaffected by the obligor-spillover fix -- it already
        carries the worst ST-assessment RW directly via the per-exposure
        override.

        Arrange: LN-A, EAD 1,000,000, issue-specific ST rating CQS3
                 (Table 4A).
        Act:     Basel 3.1 SA pipeline.
        Assert:  risk_weight == 1.00, ead_final == 1,000,000,
                 rwa_final == 1,000,000.
        """
        # Arrange
        row = _row_for(p1_223_b31_sa_results, LOAN_REF_A)
        expected = EXPECTED_B31[LOAN_REF_A]

        # Assert
        assert row["risk_weight"] == pytest.approx(expected["risk_weight"], abs=1e-4), (
            f"P1.223: expected LN-A risk_weight={expected['risk_weight']:.2f} "
            f"(Table 4A CQS3), got {row['risk_weight']:.4f}"
        )
        assert row["ead_final"] == pytest.approx(expected["ead_final"], rel=1e-4), (
            f"P1.223: expected LN-A ead_final={expected['ead_final']:,.0f}, "
            f"got {row['ead_final']:,.0f}"
        )
        assert row["rwa_final"] == pytest.approx(expected["rwa_final"], rel=1e-4), (
            f"P1.223: expected LN-A rwa_final={expected['rwa_final']:,.0f}, "
            f"got {row['rwa_final']:,.0f}"
        )

    def test_p1_223_ln_c_long_term_claim_unaffected(
        self,
        p1_223_b31_sa_results: pl.DataFrame,
    ) -> None:
        """
        Regression guard (negative control): LN-C is a long-term claim
        (>3 months original maturity) on the same contaminated obligor.
        Art. 120(3)(c) spillover is scoped to short-term claims only
        (``in_st_window`` gate) -- LN-C must keep the long-term ECRA
        institution risk weight (Table 3, CQS2 -> 30% under Basel 3.1),
        NOT the spillover risk weight.

        Arrange: LN-C, EAD 4,000,000, long-term maturity (5y), CQS2
                 counterparty rating, no short-term rating.
        Act:     Basel 3.1 SA pipeline.
        Assert:  risk_weight == 0.30, ead_final == 4,000,000,
                 rwa_final == 1,200,000.
        """
        # Arrange
        row = _row_for(p1_223_b31_sa_results, LOAN_REF_C)
        expected = EXPECTED_B31[LOAN_REF_C]

        # Assert
        assert row["risk_weight"] == pytest.approx(expected["risk_weight"], abs=1e-4), (
            f"P1.223: expected LN-C risk_weight={expected['risk_weight']:.2f} "
            f"(long-term Table 3 CQS2, unaffected by ST spillover), "
            f"got {row['risk_weight']:.4f}"
        )
        assert row["ead_final"] == pytest.approx(expected["ead_final"], rel=1e-4), (
            f"P1.223: expected LN-C ead_final={expected['ead_final']:,.0f}, "
            f"got {row['ead_final']:,.0f}"
        )
        assert row["rwa_final"] == pytest.approx(expected["rwa_final"], rel=1e-4), (
            f"P1.223: expected LN-C rwa_final={expected['rwa_final']:,.0f}, "
            f"got {row['rwa_final']:,.0f}"
        )

    def test_p1_223_all_exposures_institution_standardised(
        self,
        p1_223_b31_sa_results: pl.DataFrame,
    ) -> None:
        """
        Regression guard: all three exposures classify as institution and
        route through the standardised approach.

        Arrange: INST-001 entity_type=bank, CalculationConfig.basel_3_1()
                 SA-only permission mode.
        Act:     Basel 3.1 SA pipeline.
        Assert:  exposure_class == 'institution', approach_applied ==
                 'standardised' for LN-A, LN-B, LN-C.
        """
        # Arrange / Assert
        for loan_ref in (LOAN_REF_A, LOAN_REF_B, LOAN_REF_C):
            row = _row_for(p1_223_b31_sa_results, loan_ref)
            assert row["exposure_class"] == "institution", (
                f"P1.223: expected {loan_ref} exposure_class='institution', "
                f"got {row['exposure_class']!r}"
            )
            assert row["approach_applied"] == "standardised", (
                f"P1.223: expected {loan_ref} approach_applied='standardised', "
                f"got {row['approach_applied']!r}"
            )


# ---------------------------------------------------------------------------
# P1.223 acceptance tests -- CRR twin
# ---------------------------------------------------------------------------


class TestP1223Art1203cObligorShortTermSpilloverCRR:
    """
    P1.223 CRR twin: Art. 120(3)(c) obligor-level short-term spillover under
    CRR (Art. 131 Table 7 short-term ECAI, Art. 120(2) Table 4 general
    preferential). LN-A / LN-B are numerically identical to the Basel 3.1
    case; LN-C's long-term institution risk weight differs (50% CRR vs 30%
    B31, Table 3 CQS2).
    """

    def test_p1_223_crr_ln_b_obligor_spillover_risk_weight_and_rwa(
        self,
        p1_223_crr_sa_results: pl.DataFrame,
    ) -> None:
        """
        Headline fail-first assertion (CRR twin): LN-B spills over to the
        worse short-term ECAI risk weight (100%), not the general
        preferential 20%.

        Arrange: INST-001, unrated short-term claim LN-B (GBP 2,000,000),
                 same obligor as LN-A's issue-specific ST rating (Art. 131
                 Table 7 CQS3 -> 100%) which is less favourable than the
                 obligor's general preferential ST rating (Art. 120(2)
                 Table 4 CQS2 -> 20%).
        Act:     CRR SA pipeline (CalculationConfig.crr()).
        Assert:  risk_weight == 1.00, rwa_final == 2,000,000.

        Pre-fix (bug): engine returns risk_weight == 0.20,
        rwa_final == 400,000.

        References:
            CRR Art. 120(3)(c): obligor-level ST spillover.
        """
        # Arrange
        row = _row_for(p1_223_crr_sa_results, LOAN_REF_B)
        expected = EXPECTED_CRR[LOAN_REF_B]

        # Assert
        assert row["risk_weight"] == pytest.approx(expected["risk_weight"], abs=1e-4), (
            f"P1.223 CRR twin Art. 120(3)(c): expected LN-B risk_weight="
            f"{expected['risk_weight']:.2f} (obligor spillover to Table 7 "
            f"worst-ST-assessment RW), got {row['risk_weight']:.4f} "
            f"(pre-fix engine incorrectly applies general preferential "
            f"Table 4 = 0.20 per-exposure only)"
        )
        assert row["rwa_final"] == pytest.approx(expected["rwa_final"], rel=1e-4), (
            f"P1.223 CRR twin: expected LN-B rwa_final={expected['rwa_final']:,.0f} "
            f"(EAD 2,000,000 x 100% spillover RW), got {row['rwa_final']:,.0f} "
            f"(pre-fix engine returns 400,000 = EAD x 20% Table 4 fallback)"
        )

    def test_p1_223_crr_ln_a_issue_specific_rating_unaffected(
        self,
        p1_223_crr_sa_results: pl.DataFrame,
    ) -> None:
        """
        Regression guard (CRR twin): LN-A is unaffected by the
        obligor-spillover fix -- numerically identical to Basel 3.1.

        Arrange: LN-A, EAD 1,000,000, issue-specific ST rating CQS3
                 (Art. 131 Table 7).
        Act:     CRR SA pipeline.
        Assert:  risk_weight == 1.00, ead_final == 1,000,000,
                 rwa_final == 1,000,000.
        """
        # Arrange
        row = _row_for(p1_223_crr_sa_results, LOAN_REF_A)
        expected = EXPECTED_CRR[LOAN_REF_A]

        # Assert
        assert row["risk_weight"] == pytest.approx(expected["risk_weight"], abs=1e-4), (
            f"P1.223 CRR twin: expected LN-A risk_weight={expected['risk_weight']:.2f} "
            f"(Table 7 CQS3), got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(expected["rwa_final"], rel=1e-4), (
            f"P1.223 CRR twin: expected LN-A rwa_final={expected['rwa_final']:,.0f}, "
            f"got {row['rwa_final']:,.0f}"
        )

    def test_p1_223_crr_ln_c_long_term_claim_50_pct(
        self,
        p1_223_crr_sa_results: pl.DataFrame,
    ) -> None:
        """
        Regression guard (CRR twin, negative control): LN-C's long-term
        institution risk weight under CRR Table 3 CQS2 is 50% (vs 30%
        under Basel 3.1) -- the only numerical divergence between the two
        regimes in this scenario. LN-C is unaffected by the short-term
        spillover under either regime.

        Arrange: LN-C, EAD 4,000,000, long-term maturity (5y), CQS2
                 counterparty rating, no short-term rating.
        Act:     CRR SA pipeline.
        Assert:  risk_weight == 0.50, ead_final == 4,000,000,
                 rwa_final == 2,000,000.
        """
        # Arrange
        row = _row_for(p1_223_crr_sa_results, LOAN_REF_C)
        expected = EXPECTED_CRR[LOAN_REF_C]

        # Assert
        assert row["risk_weight"] == pytest.approx(expected["risk_weight"], abs=1e-4), (
            f"P1.223 CRR twin: expected LN-C risk_weight={expected['risk_weight']:.2f} "
            f"(CRR Table 3 CQS2 institution long-term, unaffected by ST spillover), "
            f"got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(expected["rwa_final"], rel=1e-4), (
            f"P1.223 CRR twin: expected LN-C rwa_final={expected['rwa_final']:,.0f}, "
            f"got {row['rwa_final']:,.0f}"
        )
