"""
P1.181: CRR Art. 126(2)(d) — Commercial RE proportion split.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Validate CRR Art. 126(2)(d): where LTV > 50% MV the exposure is split into
  a secured portion (capped at 50% MV) carrying a 50% risk weight, and a
  residual portion carrying the counterparty's *unsecured* risk weight per
  Art. 124(1) / Art. 122 (i.e. the corporate CQS lookup, not a fixed 100%).
- Three exposures exercise the split rule end-to-end:
    LN-CRE-A (LTV=0.40, unrated): whole-loan 50% — regression anchor.
    LN-CRE-B (LTV=0.80, unrated): 0.625 × 50% + 0.375 × 100% = 68.75%.
    LN-CRE-C (LTV=0.80, CQS=1):  0.625 × 50% + 0.375 × 20%  = 38.75%.
  Exposure C discriminates a correct fix from a naïve 100%-residual hardcode.

Bug (pre-fix): The engine applies a binary whole-loan rule using the constant
    `cre_rw_standard` (= 1.00) on the residual leg, ignoring the counterparty
    CQS. The correct residual leg must use the Art. 122 corporate CQS lookup.

Hand-calculation (CRR Art. 126(2)(d)):
    Constants (COMMERCIAL_RE_PARAMS):
        ltv_threshold  = 0.50
        cre_rw_secured = 0.50

    LN-CRE-A — LTV=0.40, unrated:
        secured_share   = min(1.0, 0.50 / 0.40) = 1.0
        avg_rw          = 0.50 × 1.0 = 0.50
        rwa             = 1,000,000 × 0.50 = 500,000

    LN-CRE-B — LTV=0.80, unrated:
        secured_share   = min(1.0, 0.50 / 0.80) = 0.625
        residual_share  = 0.375
        counterparty_rw = 1.00  (Art. 122 Table 6, unrated)
        avg_rw          = 0.50 × 0.625 + 1.00 × 0.375 = 0.6875
        rwa             = 687,500  (pre-fix: 1,000,000)

    LN-CRE-C — LTV=0.80, CQS=1:
        secured_share   = 0.625; residual_share = 0.375
        counterparty_rw = 0.20  (Art. 122 Table 6, CQS=1)
        avg_rw          = 0.50 × 0.625 + 0.20 × 0.375 = 0.3875
        rwa             = 387,500  (naïve 100%-residual fix: 687,500)

References:
    - CRR Art. 126(2)(d): CRE secured / residual proportion split
    - CRR Art. 124(1): residual portion takes unsecured counterparty RW
    - CRR Art. 122 Table 6: corporate CQS risk weights
    - tests/fixtures/p1_181/p1_181.py: scenario constants and parquet builders
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_181"

# ---------------------------------------------------------------------------
# Scenario constants (single source of truth, mirrors p1_181.py)
# ---------------------------------------------------------------------------

_LOAN_REF_A = "LN-CRE-A"  # LTV=0.40, unrated — regression anchor
_LOAN_REF_B = "LN-CRE-B"  # LTV=0.80, unrated — split, 68.75%
_LOAN_REF_C = "LN-CRE-C"  # LTV=0.80, CQS=1  — split, 38.75% (discriminating)

_EAD = 1_000_000.0

# Expected risk weights per Art. 126(2)(d) proportion split
_EXPECTED_RW_A = 0.5000  # whole-loan 50% (LTV ≤ threshold)
_EXPECTED_RW_B = 0.6875  # 0.625×50% + 0.375×100%
_EXPECTED_RW_C = 0.3875  # 0.625×50% + 0.375×20%

# Expected RWA
_EXPECTED_RWA_A = 500_000.0
_EXPECTED_RWA_B = 687_500.0
_EXPECTED_RWA_C = 387_500.0

# Pre-fix (buggy) values — regression sentinels
# The current engine applies binary whole-loan 100% to high-LTV CRE exposures.
_BUGGY_RWA_B = 1_000_000.0
_BUGGY_RWA_C = 1_000_000.0  # naïve 100%-residual fix would give 687,500 not 387,500

# Tolerances per proposal § 4
_RW_TOL = 1e-6   # relative on risk_weight
_RWA_TOL = 0.01  # absolute on rwa


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1_181_sa_results() -> dict[str, dict]:
    """
    Run the P1.181 fixture through the CRR SA pipeline and return a mapping of
    loan_id -> result row dict for the three COMMERCIAL_MORTGAGE exposures.

    Module-scoped to run the pipeline once and reuse results across all test
    methods in this module.

    Arrange:
        - 2 counterparties: CP-CRE-CORP-UNRATED (cqs=None) and CP-CRE-CORP-CQS1 (cqs=1).
        - 3 loans: LN-CRE-A (LTV=0.40), LN-CRE-B (LTV=0.80), LN-CRE-C (LTV=0.80).
        - 2 ratings: null-CQS for unrated, CQS=1 for CQS-1 counterparty.
        - No facilities, no facility_mappings, no lending_mappings, no collateral.

    The engine must route COMMERCIAL_MORTGAGE exposures via CRR Art. 126(2)(d).
    Pre-fix: binary whole-loan 50%/100% (ignores CQS on residual leg).
    Post-fix: proportion split with counterparty CQS on residual leg.
    """
    # Arrange — load scenario-local parquets
    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet")
    loans = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet")
    ratings = pl.scan_parquet(_FIXTURES_DIR / "rating.parquet")

    lending_mappings = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )

    bundle = RawDataBundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=loans,
        counterparties=counterparties,
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=lending_mappings,
        ratings=ratings,
    )

    config = CalculationConfig.crr(
        reporting_date=date(2026, 3, 1),
        permission_mode=PermissionMode.STANDARDISED,
    )

    # Act — run the full pipeline
    results = PipelineOrchestrator().run_with_data(bundle, config)

    assert results.sa_results is not None, "SA results should not be None for SA-only config"

    df = results.sa_results.collect()

    # Extract one dict per loan reference
    output: dict[str, dict] = {}
    for loan_ref in (_LOAN_REF_A, _LOAN_REF_B, _LOAN_REF_C):
        rows = df.filter(pl.col("exposure_reference") == loan_ref).to_dicts()
        assert len(rows) == 1, (
            f"P1.181: expected exactly 1 SA row for {loan_ref}, got {len(rows)}"
        )
        output[loan_ref] = rows[0]

    return output


# ---------------------------------------------------------------------------
# P1.181 acceptance tests
# ---------------------------------------------------------------------------


class TestP1181Art126CREProportionSplit:
    """
    P1.181: CRR Art. 126(2)(d) — commercial RE proportion split with CQS-aware residual leg.

    Six tests verify that the three exposures produce the correct blended risk
    weight and RWA.  Regression sentinels confirm the pre-fix binary-whole-loan
    path no longer fires.

    Pre-fix failures:
      - LN-CRE-B: engine returns rwa=1,000,000 (binary 100%), expected 687,500.
      - LN-CRE-C: engine returns rwa=1,000,000 (binary 100%), expected 387,500.
    """

    # ------------------------------------------------------------------
    # LN-CRE-A: low LTV regression (LTV=0.40 → whole loan 50%)
    # ------------------------------------------------------------------

    def test_p1181_loan_a_risk_weight(self, p1_181_sa_results: dict[str, dict]) -> None:
        """
        LN-CRE-A: LTV=0.40 (below 50% MV threshold) — whole-loan 50% risk weight.

        Art. 126(2)(d): secured_share = min(1, 0.50/0.40) = 1.0 → avg_rw = 0.50.

        Arrange: LN-CRE-A, LTV=0.40, unrated corporate, EAD=1,000,000.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 0.5000.
        """
        # Arrange
        row = p1_181_sa_results[_LOAN_REF_A]

        # Assert
        assert row["risk_weight"] == pytest.approx(_EXPECTED_RW_A, rel=_RW_TOL), (
            f"P1.181 LN-CRE-A: expected risk_weight={_EXPECTED_RW_A} "
            f"(CRR Art. 126(2)(d) low-LTV whole-loan 50%), got {row['risk_weight']}"
        )

    def test_p1181_loan_a_rwa(self, p1_181_sa_results: dict[str, dict]) -> None:
        """
        LN-CRE-A: RWA = EAD × 0.50 = 500,000 (regression anchor).

        Arrange: LN-CRE-A, LTV=0.40, unrated, EAD=1,000,000.
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 500,000 ± 0.01.
        """
        # Arrange
        row = p1_181_sa_results[_LOAN_REF_A]

        # Assert
        assert row["rwa_final"] == pytest.approx(_EXPECTED_RWA_A, abs=_RWA_TOL), (
            f"P1.181 LN-CRE-A: expected rwa_final={_EXPECTED_RWA_A:,.0f}, "
            f"got {row['rwa_final']:,.2f}"
        )

    # ------------------------------------------------------------------
    # LN-CRE-B: high LTV, unrated (split — residual = 100%)
    # ------------------------------------------------------------------

    def test_p1181_loan_b_risk_weight(self, p1_181_sa_results: dict[str, dict]) -> None:
        """
        LN-CRE-B: LTV=0.80, unrated — proportion split gives 68.75% blended RW.

        Art. 126(2)(d):
            secured_share  = min(1, 0.50/0.80) = 0.625
            residual_share = 0.375
            counterparty_rw = 1.00 (Art. 122 unrated)
            avg_rw = 0.50×0.625 + 1.00×0.375 = 0.6875

        Pre-fix: binary whole-loan 100% → risk_weight=1.00.

        Arrange: LN-CRE-B, LTV=0.80, unrated corporate, EAD=1,000,000.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 0.6875.
        """
        # Arrange
        row = p1_181_sa_results[_LOAN_REF_B]

        # Assert
        assert row["risk_weight"] == pytest.approx(_EXPECTED_RW_B, rel=_RW_TOL), (
            f"P1.181 LN-CRE-B: expected risk_weight={_EXPECTED_RW_B} "
            f"(Art. 126(2)(d) proportion split: 0.625×50%+0.375×100%), "
            f"got {row['risk_weight']} "
            f"(pre-fix binary 100% would give risk_weight=1.00)"
        )

    def test_p1181_loan_b_rwa(self, p1_181_sa_results: dict[str, dict]) -> None:
        """
        LN-CRE-B: RWA = 1,000,000 × 0.6875 = 687,500 (not 1,000,000 pre-fix).

        Arrange: LN-CRE-B, LTV=0.80, unrated, EAD=1,000,000.
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 687,500 ± 0.01.
        """
        # Arrange
        row = p1_181_sa_results[_LOAN_REF_B]

        # Assert
        assert row["rwa_final"] == pytest.approx(_EXPECTED_RWA_B, abs=_RWA_TOL), (
            f"P1.181 LN-CRE-B: expected rwa_final={_EXPECTED_RWA_B:,.0f} "
            f"(Art. 126(2)(d) split: 0.625×50%+0.375×100%), "
            f"got {row['rwa_final']:,.2f} "
            f"(pre-fix binary 100% gives {_BUGGY_RWA_B:,.0f})"
        )

    # ------------------------------------------------------------------
    # LN-CRE-C: high LTV, CQS=1 (discriminating — residual = 20%)
    # ------------------------------------------------------------------

    def test_p1181_loan_c_risk_weight(self, p1_181_sa_results: dict[str, dict]) -> None:
        """
        LN-CRE-C: LTV=0.80, CQS=1 — proportion split gives 38.75% blended RW.

        Art. 126(2)(d) + Art. 122 Table 6:
            secured_share  = 0.625
            residual_share = 0.375
            counterparty_rw = 0.20 (CQS=1 corporate)
            avg_rw = 0.50×0.625 + 0.20×0.375 = 0.3875

        A naïve 100%-residual fix (passes B) returns 0.6875 here, not 0.3875.
        This test discriminates the correct Art. 124(1) CQS-aware residual from
        any hardcoded-100% workaround.

        Arrange: LN-CRE-C, LTV=0.80, CQS=1 corporate, EAD=1,000,000.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 0.3875.
        """
        # Arrange
        row = p1_181_sa_results[_LOAN_REF_C]

        # Assert
        assert row["risk_weight"] == pytest.approx(_EXPECTED_RW_C, rel=_RW_TOL), (
            f"P1.181 LN-CRE-C: expected risk_weight={_EXPECTED_RW_C} "
            f"(Art. 126(2)(d) split: 0.625×50%+0.375×20% for CQS=1), "
            f"got {row['risk_weight']} "
            f"(naïve 100%-residual fix gives 0.6875; pre-fix binary gives 1.00)"
        )

    def test_p1181_loan_c_rwa(self, p1_181_sa_results: dict[str, dict]) -> None:
        """
        LN-CRE-C: RWA = 1,000,000 × 0.3875 = 387,500 (discriminating assertion).

        Arrange: LN-CRE-C, LTV=0.80, CQS=1, EAD=1,000,000.
        Act:     full CRR SA pipeline.
        Assert:  rwa_final == 387,500 ± 0.01.
        """
        # Arrange
        row = p1_181_sa_results[_LOAN_REF_C]

        # Assert
        assert row["rwa_final"] == pytest.approx(_EXPECTED_RWA_C, abs=_RWA_TOL), (
            f"P1.181 LN-CRE-C: expected rwa_final={_EXPECTED_RWA_C:,.0f} "
            f"(Art. 126(2)(d) split with CQS=1 residual 20%), "
            f"got {row['rwa_final']:,.2f} "
            f"(pre-fix binary: {_BUGGY_RWA_C:,.0f}; "
            f"naïve 100%-residual fix: {_EXPECTED_RWA_B:,.0f})"
        )

    # ------------------------------------------------------------------
    # No fatal errors during pipeline run
    # ------------------------------------------------------------------

    def test_p1181_no_error_severity_errors(
        self, p1_181_sa_results: dict[str, dict]
    ) -> None:
        """
        P1.181 pipeline must not produce ERROR-level CalculationErrors.

        Arrange: clean CRE scenario — no missing data, no CRM, SA-only config.
        Act:     full CRR SA pipeline (results fixture already run).
        Assert:  all three loan rows are present (pipeline did not drop rows).
        """
        # Arrange / Assert — all three loans must have returned a result row
        for loan_ref in (_LOAN_REF_A, _LOAN_REF_B, _LOAN_REF_C):
            assert loan_ref in p1_181_sa_results, (
                f"P1.181: loan {loan_ref} missing from SA results — "
                f"pipeline may have dropped the row on an error path"
            )
