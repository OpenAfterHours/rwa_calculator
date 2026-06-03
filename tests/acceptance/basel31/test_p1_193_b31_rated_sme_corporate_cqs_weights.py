"""
P1.193 — B31 Art. 122(2) Table 6 CQS weights for rated corporate-SME.

Acceptance scenario (B31-A11): rated corporate-SME exposures (CQS 1-6) must
use PRA PS1/26 Art. 122(2) Table 6 risk weights, NOT the unconditional 85%
SME override. The 85% override (Art. 122(11)) must continue to fire for the
unrated SME exposure (LOAN_SME_UNRATED — regression guard).

Defect under test:
    ``sa/namespace.py:1293-1295`` applies the 85% SME risk weight via
    ``uc.contains('CORPORATE') & uc.contains('SME')`` with no CQS gate.  A
    rated CORPORATE_SME (CQS 1-6) is forced to 0.85, discarding the Table-6
    weight set by the ``rw_table`` join at ``namespace.py:1130``.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
    -> SACalculator -> OutputAggregator

Hand calculations (EAD = GBP 2,000,000, SF = 1.0 under PS1/26):

    | Reference             | CQS   | RW (Table 6) | RWA          |
    |-----------------------|-------|--------------|--------------|
    | LOAN_SME_RATED_CQS1   | 1     | 0.20         | 400,000      |
    | LOAN_SME_RATED_CQS2   | 2     | 0.50         | 1,000,000    |  <- primary
    | LOAN_SME_RATED_CQS3   | 3     | 0.75         | 1,500,000    |
    | LOAN_SME_RATED_CQS4   | 4     | 1.00         | 2,000,000    |
    | LOAN_SME_RATED_CQS5   | 5     | 1.50         | 3,000,000    |  PRA retains 150%
    | LOAN_SME_RATED_CQS6   | 6     | 1.50         | 3,000,000    |
    | LOAN_SME_UNRATED      | null  | 0.85         | 1,700,000    |  <- regression guard

Primary anti-confound: LOAN_SME_RATED_CQS2.risk_weight == 0.50 AND != 0.85.

Pre-fix failure mode: ALL rated rows return risk_weight = 0.85 (unconditional
SME override), so CQS1/2/3 rows over-weight and CQS4/5/6 rows under-weight
relative to Table 6. The unrated row correctly returns 0.85 pre-fix.

References:
    PRA PS1/26 Art. 122(2) Table 6: B31 corporate ECAI risk weights by CQS.
    PRA PS1/26 Art. 122(11): 85% SME corporate RW for unrated SME-qualifying
        corporates (replaces CRR 100% + 0.7619 supporting factor).
    src/rwa_calc/engine/sa/namespace.py:1293-1295 — defect site.
    tests/fixtures/p1_193/p1_193.py — fixture module.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from tests.acceptance.acceptance_helpers import get_sa_result_for_exposure
from tests.acceptance.sa_bundle import build_sa_loan_bundle

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_193"

# ---------------------------------------------------------------------------
# Expected Table-6 risk weights (PRA PS1/26 Art. 122(2))
# ---------------------------------------------------------------------------

_EXPECTED_RW: dict[str, float] = {
    "LOAN_SME_RATED_CQS1": 0.20,
    "LOAN_SME_RATED_CQS2": 0.50,
    "LOAN_SME_RATED_CQS3": 0.75,
    "LOAN_SME_RATED_CQS4": 1.00,
    "LOAN_SME_RATED_CQS5": 1.50,
    "LOAN_SME_RATED_CQS6": 1.50,
    "LOAN_SME_UNRATED": 0.85,
}

_EAD = 2_000_000.0

_BUGGY_RW = 0.85  # unconditional SME override — the pre-fix value for all rows

# ---------------------------------------------------------------------------
# Pipeline runner — module-scoped so the pipeline executes once per test file
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_193_sa_results() -> pl.DataFrame:
    """
    Run P1.193 fixtures through the Basel 3.1 SA pipeline and collect results.

    Module-scoped to avoid re-running the pipeline for each test method.
    Returns the collected SA results DataFrame.
    """
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    # Arrange
    bundle = build_sa_loan_bundle(_FIXTURES_DIR)
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, (
        "SA results must not be None for SA-only (PermissionMode.STANDARDISED) config"
    )
    return cast(pl.DataFrame, results.sa_results.collect())


def _get_row(sa_results: pl.DataFrame, loan_ref: str) -> dict:
    """Return the single SA result row for *loan_ref* via the shared result reader."""
    row = get_sa_result_for_exposure(sa_results, loan_ref)
    assert row is not None, (
        f"Expected an SA result row for {loan_ref!r}, found none. "
        f"All exposure_references in SA results: "
        f"{sa_results['exposure_reference'].to_list()}"
    )
    return row


# ---------------------------------------------------------------------------
# Classification pre-condition guard
# ---------------------------------------------------------------------------


class TestP1193ClassificationPreCondition:
    """
    Pre-condition: all P1.193 exposures must classify as corporate_sme.

    If this test fails the remaining assertions are meaningless — the failure
    is in classification/fixture data, not in the SA risk-weight logic under test.
    """

    def test_all_rows_classified_as_corporate_sme(self, p1_193_sa_results: pl.DataFrame) -> None:
        """
        All seven exposures must have exposure_class == 'corporate_sme'.

        Arrange: seven loans, counterparties with annual_revenue=GBP 30m.
        Act:     Basel 3.1 SA pipeline classifies by entity_type + revenue.
        Assert:  all rows have exposure_class == 'corporate_sme'.

        Failure mode: if any row shows 'corporate' instead of 'corporate_sme',
        the annual_revenue threshold or is_sme derivation is broken — do NOT
        proceed with RW assertions.
        """
        # Arrange
        expected_class = "corporate_sme"

        for loan_ref in _EXPECTED_RW:
            row = _get_row(p1_193_sa_results, loan_ref)

            # Assert
            assert row["exposure_class"] == expected_class, (
                f"P1.193: {loan_ref} must classify as {expected_class!r}, "
                f"got {row['exposure_class']!r}. "
                f"Check annual_revenue threshold in classifier — "
                f"fixture sets annual_revenue=GBP 30m (below ~GBP 43.66m threshold)."
            )


# ---------------------------------------------------------------------------
# Primary failing assertions (CQS ladder)
# ---------------------------------------------------------------------------


class TestP1193RatedSMECorporateCQSWeights:
    """
    B31-A11: Rated corporate-SME uses Table 6 CQS weights (Art. 122(2)).

    All rated rows (CQS 1-6) must fail under the current buggy engine because
    the 85% override is unconditional. The unrated row must pass already.
    """

    def test_b31_a11_rated_sme_cqs1_risk_weight_is_20pct(
        self, p1_193_sa_results: pl.DataFrame
    ) -> None:
        """
        Art. 122(2) Table 6 CQS 1: risk_weight = 0.20.

        Arrange: LOAN_SME_RATED_CQS1, CQS 1 (AA-), EAD 2,000,000.
        Act:     Basel 3.1 SA pipeline under CalculationConfig.basel_3_1().
        Assert:  risk_weight == 0.20  (Table 6 CQS 1 = 20%).

        Pre-fix failure mode: risk_weight == 0.85 (unconditional SME override).
        """
        # Arrange
        row = _get_row(p1_193_sa_results, "LOAN_SME_RATED_CQS1")
        expected_rw = _EXPECTED_RW["LOAN_SME_RATED_CQS1"]  # 0.20

        # Assert
        assert row["risk_weight"] == pytest.approx(expected_rw, abs=1e-6), (
            f"B31-A11: LOAN_SME_RATED_CQS1 Art. 122(2) Table 6 CQS 1 → "
            f"expected risk_weight={expected_rw:.2f} (20%), "
            f"got {row['risk_weight']:.4f}. "
            f"Pre-fix: engine returns {_BUGGY_RW:.2f} (unconditional 85% SME override)."
        )

    def test_b31_a11_rated_sme_cqs2_risk_weight_is_50pct(
        self, p1_193_sa_results: pl.DataFrame
    ) -> None:
        """
        Art. 122(2) Table 6 CQS 2: risk_weight = 0.50 — primary assert.

        Arrange: LOAN_SME_RATED_CQS2, CQS 2 (A+), EAD 2,000,000.
        Act:     Basel 3.1 SA pipeline under CalculationConfig.basel_3_1().
        Assert:  risk_weight == 0.50  (Table 6 CQS 2 = 50%).

        Pre-fix failure mode: risk_weight == 0.85 (unconditional SME override).
        Anti-confound: explicitly asserted != 0.85.
        """
        # Arrange
        row = _get_row(p1_193_sa_results, "LOAN_SME_RATED_CQS2")
        expected_rw = _EXPECTED_RW["LOAN_SME_RATED_CQS2"]  # 0.50

        # Assert — primary load-bearing assertion
        assert row["risk_weight"] == pytest.approx(expected_rw, abs=1e-6), (
            f"B31-A11 (PRIMARY): LOAN_SME_RATED_CQS2 Art. 122(2) Table 6 CQS 2 → "
            f"expected risk_weight={expected_rw:.2f} (50%), "
            f"got {row['risk_weight']:.4f}. "
            f"Pre-fix: engine forces all CORPORATE_SME to {_BUGGY_RW:.2f} "
            f"(namespace.py:1293-1295 unconditional SME override, no CQS gate)."
        )

        # Anti-confound: explicitly assert the buggy value is NOT returned
        assert row["risk_weight"] != pytest.approx(_BUGGY_RW, abs=1e-6), (
            f"B31-A11 (ANTI-CONFOUND): LOAN_SME_RATED_CQS2 risk_weight must NOT be "
            f"{_BUGGY_RW:.2f} (Art. 122(11) 85% applies only to unrated SME, "
            f"not CQS 2 rated SME). Got {row['risk_weight']:.4f}."
        )

    def test_b31_a11_rated_sme_cqs2_rwa_is_1m(self, p1_193_sa_results: pl.DataFrame) -> None:
        """
        RWA = EAD × RW = 2,000,000 × 0.50 = 1,000,000 for CQS 2.

        Arrange: LOAN_SME_RATED_CQS2, CQS 2, EAD = 2,000,000, expected RW = 0.50.
        Act:     Basel 3.1 SA pipeline.
        Assert:  rwa_final == 1,000,000.

        Pre-fix failure mode: rwa_final == 1,700,000 (2,000,000 × 0.85).
        """
        # Arrange
        row = _get_row(p1_193_sa_results, "LOAN_SME_RATED_CQS2")
        expected_rwa = _EAD * _EXPECTED_RW["LOAN_SME_RATED_CQS2"]  # 1,000,000

        # Assert
        assert row["rwa_final"] == pytest.approx(expected_rwa, rel=1e-4), (
            f"B31-A11: LOAN_SME_RATED_CQS2 RWA should be {expected_rwa:,.0f} "
            f"(2,000,000 × 0.50, Art. 122(2) CQS 2), "
            f"got {row['rwa_final']:,.0f}. "
            f"Pre-fix: {_EAD * _BUGGY_RW:,.0f} (2,000,000 × {_BUGGY_RW:.2f})."
        )

    def test_b31_a11_rated_sme_cqs3_risk_weight_is_75pct(
        self, p1_193_sa_results: pl.DataFrame
    ) -> None:
        """
        Art. 122(2) Table 6 CQS 3: risk_weight = 0.75.

        Arrange: LOAN_SME_RATED_CQS3, CQS 3 (BBB+), EAD 2,000,000.
        Act:     Basel 3.1 SA pipeline.
        Assert:  risk_weight == 0.75  (Table 6 CQS 3 = 75%).

        Pre-fix failure mode: risk_weight == 0.85.
        """
        # Arrange
        row = _get_row(p1_193_sa_results, "LOAN_SME_RATED_CQS3")
        expected_rw = _EXPECTED_RW["LOAN_SME_RATED_CQS3"]  # 0.75

        # Assert
        assert row["risk_weight"] == pytest.approx(expected_rw, abs=1e-6), (
            f"B31-A11: LOAN_SME_RATED_CQS3 Art. 122(2) Table 6 CQS 3 → "
            f"expected risk_weight={expected_rw:.2f} (75%), "
            f"got {row['risk_weight']:.4f}. "
            f"Pre-fix: engine returns {_BUGGY_RW:.2f}."
        )

    def test_b31_a11_rated_sme_cqs4_risk_weight_is_100pct(
        self, p1_193_sa_results: pl.DataFrame
    ) -> None:
        """
        Art. 122(2) Table 6 CQS 4: risk_weight = 1.00.

        Arrange: LOAN_SME_RATED_CQS4, CQS 4 (BB+), EAD 2,000,000.
        Act:     Basel 3.1 SA pipeline.
        Assert:  risk_weight == 1.00  (Table 6 CQS 4 = 100%).

        Pre-fix failure mode: risk_weight == 0.85 (under-weights this exposure).
        """
        # Arrange
        row = _get_row(p1_193_sa_results, "LOAN_SME_RATED_CQS4")
        expected_rw = _EXPECTED_RW["LOAN_SME_RATED_CQS4"]  # 1.00

        # Assert
        assert row["risk_weight"] == pytest.approx(expected_rw, abs=1e-6), (
            f"B31-A11: LOAN_SME_RATED_CQS4 Art. 122(2) Table 6 CQS 4 → "
            f"expected risk_weight={expected_rw:.2f} (100%), "
            f"got {row['risk_weight']:.4f}. "
            f"Pre-fix: engine returns {_BUGGY_RW:.2f} (under-weighs CQS 4+)."
        )

    def test_b31_a11_rated_sme_cqs5_risk_weight_is_150pct(
        self, p1_193_sa_results: pl.DataFrame
    ) -> None:
        """
        Art. 122(2) Table 6 CQS 5: risk_weight = 1.50 (PRA retains 150%).

        PRA PS1/26 did NOT adopt the BCBS CRE20.42 reduction from 150% to 100%
        for CQS 5 corporates — the UK retains 150%.

        Arrange: LOAN_SME_RATED_CQS5, CQS 5 (B+), EAD 2,000,000.
        Act:     Basel 3.1 SA pipeline.
        Assert:  risk_weight == 1.50  (PRA Table 6 CQS 5 = 150%).

        Pre-fix failure mode: risk_weight == 0.85 (under-weights this exposure).
        """
        # Arrange
        row = _get_row(p1_193_sa_results, "LOAN_SME_RATED_CQS5")
        expected_rw = _EXPECTED_RW["LOAN_SME_RATED_CQS5"]  # 1.50

        # Assert
        assert row["risk_weight"] == pytest.approx(expected_rw, abs=1e-6), (
            f"B31-A11: LOAN_SME_RATED_CQS5 PRA Art. 122(2) Table 6 CQS 5 → "
            f"expected risk_weight={expected_rw:.2f} (150%, PRA retains 150% not BCBS 100%), "
            f"got {row['risk_weight']:.4f}. "
            f"Pre-fix: engine returns {_BUGGY_RW:.2f}."
        )

    def test_b31_a11_rated_sme_cqs6_risk_weight_is_150pct(
        self, p1_193_sa_results: pl.DataFrame
    ) -> None:
        """
        Art. 122(2) Table 6 CQS 6: risk_weight = 1.50.

        Arrange: LOAN_SME_RATED_CQS6, CQS 6 (CCC), EAD 2,000,000.
        Act:     Basel 3.1 SA pipeline.
        Assert:  risk_weight == 1.50  (Table 6 CQS 6 = 150%).

        Pre-fix failure mode: risk_weight == 0.85 (under-weights this exposure).
        """
        # Arrange
        row = _get_row(p1_193_sa_results, "LOAN_SME_RATED_CQS6")
        expected_rw = _EXPECTED_RW["LOAN_SME_RATED_CQS6"]  # 1.50

        # Assert
        assert row["risk_weight"] == pytest.approx(expected_rw, abs=1e-6), (
            f"B31-A11: LOAN_SME_RATED_CQS6 Art. 122(2) Table 6 CQS 6 → "
            f"expected risk_weight={expected_rw:.2f} (150%), "
            f"got {row['risk_weight']:.4f}. "
            f"Pre-fix: engine returns {_BUGGY_RW:.2f}."
        )


# ---------------------------------------------------------------------------
# Regression guard — unrated must still get 85% (must PASS pre-fix)
# ---------------------------------------------------------------------------


class TestP1193UnratedSMECorporateRegressionGuard:
    """
    Regression guard: LOAN_SME_UNRATED must retain risk_weight = 0.85.

    Art. 122(11) applies the 85% SME weight when there is no usable CQS.
    This must not be disturbed by the CQS gate fix (the fix adds a guard
    ``pl.col('cqs').is_null() | (pl.col('cqs') <= 0)`` — the unrated path
    must still reach the 85% branch via that guard).
    """

    def test_b31_a11_unrated_sme_risk_weight_is_85pct(
        self, p1_193_sa_results: pl.DataFrame
    ) -> None:
        """
        Art. 122(11): unrated SME corporate → risk_weight = 0.85.

        Arrange: LOAN_SME_UNRATED, no rating row (cqs = null), EAD 2,000,000.
        Act:     Basel 3.1 SA pipeline.
        Assert:  risk_weight == 0.85  (Art. 122(11) 85% SME branch fires for null CQS).

        This must PASS before and after the fix — it is a regression pin.
        """
        # Arrange
        row = _get_row(p1_193_sa_results, "LOAN_SME_UNRATED")
        expected_rw = _EXPECTED_RW["LOAN_SME_UNRATED"]  # 0.85

        # Assert
        assert row["risk_weight"] == pytest.approx(expected_rw, abs=1e-6), (
            f"B31-A11 (REGRESSION GUARD): LOAN_SME_UNRATED Art. 122(11) → "
            f"expected risk_weight={expected_rw:.2f} (85% for null CQS), "
            f"got {row['risk_weight']:.4f}. "
            f"The 85% branch must still fire when cqs is null."
        )

    def test_b31_a11_unrated_sme_rwa_is_1_7m(self, p1_193_sa_results: pl.DataFrame) -> None:
        """
        RWA = 2,000,000 × 0.85 = 1,700,000 for unrated SME corporate.

        Arrange: LOAN_SME_UNRATED, no CQS, EAD = 2,000,000, RW = 0.85.
        Act:     Basel 3.1 SA pipeline.
        Assert:  rwa_final == 1,700,000.

        This must PASS before and after the fix.
        """
        # Arrange
        row = _get_row(p1_193_sa_results, "LOAN_SME_UNRATED")
        expected_rwa = _EAD * _EXPECTED_RW["LOAN_SME_UNRATED"]  # 1,700,000

        # Assert
        assert row["rwa_final"] == pytest.approx(expected_rwa, rel=1e-4), (
            f"B31-A11 (REGRESSION GUARD): LOAN_SME_UNRATED RWA should be "
            f"{expected_rwa:,.0f} (2,000,000 × 0.85), "
            f"got {row['rwa_final']:,.0f}."
        )
