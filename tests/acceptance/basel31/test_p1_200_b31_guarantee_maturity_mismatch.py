"""
P1.200 — B31 guarantee/CDS maturity-mismatch (t−0.25)/(T−0.25) scaling wrongly gated on is_crr.

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor → SACalculator → Aggregator

Key assertion:
    PS1/26 Art. 239(3) GA = G* × (t−0.25)/(T−0.25) applies unconditionally to both
    CRR and Basel 3.1. The engine guards the only call to
    ``_apply_maturity_mismatch_to_guarantees`` with ``if config.is_crr``, so under
    ``CalculationConfig.basel_3_1()`` the scaling is skipped entirely: GA = 1,000,000
    (full face) instead of 466,666.67, and RWA = 200,000 instead of 626,666.67.

Scenario (EXP-200):
    - CP-OBLIGOR-200:   corporate, GB, unrated → 100% SA risk weight (Art. 122)
    - CP-GUARANTOR-200: institution, GB, CQS 1 → 20% SA risk weight (Art. 120)
    - EXP-200: GBP 1,000,000 drawn, maturity_date 2030-06-01 → T = 4.0y from 2026-06-01
    - G-200: CDS, original_maturity_years = 2.0y, includes_restructuring = True
      → H_r = 0 (Art. 233(2)); H_fx = 0 (GBP = GBP); G* = 1,000,000
      → t_eff = 2.0y ≥ 1.0y (eligible, Art. 237(2)(a)); t_eff < T_eff → mismatch
      → m = (2.0−0.25)/(4.0−0.25) = 1.75/3.75 = 0.46666...
      → GA = 466,666.6666666667
      → RWA = 466,666.67 × 0.20 + 533,333.33 × 1.00 = 626,666.6666666666

Defect under test (pre-fix):
    Under ``CalculationConfig.basel_3_1()``, ``crm/guarantees.py`` skips the scaling
    guard (``if config.is_crr``) → GA = 1,000,000 → RWA = 200,000.0.

    The primary discriminating assertion (total RWA ≈ 626,666.67) FAILS pre-fix because
    the engine returns 200,000.0.

CRR regression pin:
    Under ``CalculationConfig.crr()`` the guard already fires, so the fix must leave
    CRR byte-for-byte unchanged (RWA == 626,666.67 for both frameworks post-fix).

References:
    - PS1/26 Art. 235(1): RWSM substitution approach
    - PS1/26 Art. 237(2)(a): minimum original maturity >= 1y eligibility filter
    - PS1/26 Art. 239(3): GA = G* × (t−0.25)/(T−0.25) maturity mismatch adjustment
    - CRR Art. 239(3): identical formula
    - src/rwa_calc/engine/crm/guarantees.py: _apply_maturity_mismatch_to_guarantees
    - tests/fixtures/p1_200/p1_200.py: fixture builder and scenario constants
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import FACILITY_MAPPING_SCHEMA, FACILITY_SCHEMA, LENDING_MAPPING_SCHEMA
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.conftest import get_guaranteed_row, get_total_rwa
from tests.fixtures.p1_200.p1_200 import (
    BUGGED_TOTAL_RWA,
    EXPECTED_GUARANTEED_PORTION,
    EXPECTED_GUARANTOR_RW,
    EXPECTED_TOTAL_RWA_B31,
    LOAN_REF,
    REPORTING_DATE,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_200" / "data"

# ---------------------------------------------------------------------------
# Config factories
# ---------------------------------------------------------------------------


def _b31_config() -> CalculationConfig:
    """Basel 3.1 SA-only config with reporting_date matching the scenario (2026-06-01)."""
    return CalculationConfig.basel_3_1(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


def _crr_config() -> CalculationConfig:
    """CRR SA-only config with same reporting_date (regression pin)."""
    return CalculationConfig.crr(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle from P1.200 parquets.

    Loads counterparties, loans, ratings, and guarantees from the
    scenario-local parquets in tests/fixtures/p1_200/data/.

    Facilities, facility_mappings, and lending_mappings are empty frames
    with the correct schemas — the P1.200 scenario has a single drawn
    loan with no facility hierarchy rows required.
    """
    return make_raw_bundle(
        facilities=pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        guarantees=pl.scan_parquet(_FIXTURES_DIR / "guarantee.parquet"),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
    )


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline(config: CalculationConfig) -> pl.DataFrame:
    """
    Run the P1.200 bundle through the credit risk pipeline and return SA results.

    The CRM processor splits the guaranteed loan into two sub-rows:
      - ``EXP-200__G_CP-GUARANTOR-200``: guaranteed portion
        (ead_final = 466,666.67 post-fix; 1,000,000 pre-fix)
      - ``EXP-200__REM``: unguaranteed remainder
        (ead_final = 533,333.33 post-fix; 0 pre-fix)

    Returns the collected SA results DataFrame.
    """
    bundle = _build_bundle()
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None, (
        "SA results must not be None — check PermissionMode.STANDARDISED config"
    )
    return results.sa_results.collect()


# ---------------------------------------------------------------------------
# Acceptance tests — P1.200 B31 Art. 239(3) maturity mismatch guard defect
#
# Result-row readers (get_total_rwa / get_guaranteed_row) are imported from
# tests.acceptance.conftest — both take the parent loan reference (LOAN_REF).
# ---------------------------------------------------------------------------


class TestP1200B31GuaranteeMaturityMismatch:
    """
    P1.200: PS1/26 Art. 239(3) maturity mismatch scaling must apply under Basel 3.1.

    The defect: ``crm/guarantees.py`` guards the sole call to
    ``_apply_maturity_mismatch_to_guarantees`` with ``if config.is_crr``.
    Under ``CalculationConfig.basel_3_1()`` this evaluates to False and the
    scaling is skipped, giving GA = full face value (1,000,000) and
    RWA = 200,000 — an understatement of ~68% vs the correct 626,666.67.

    Fixture: EXP-200 (corporate, unrated, GBP 1M, T=4.0y from 2026-06-01)
             G-200 (CDS, original_maturity_years=2.0, includes_restructuring=True)
             CP-GUARANTOR-200 (institution GB, CQS 1 → 20% RW)

    Hand-calc (Art. 239(3)):
        m = (2.0−0.25)/(4.0−0.25) = 1.75/3.75 = 0.46666...
        GA = 1,000,000 × 0.46666... = 466,666.6666666667
        uncovered = 1,000,000 − 466,666.67 = 533,333.33
        RWA = 466,666.67 × 0.20 + 533,333.33 × 1.00 = 626,666.6666666666
    """

    @pytest.fixture(scope="class")
    def b31_sa_results(self) -> pl.DataFrame:
        """
        Basel 3.1 SA pipeline results for P1.200.

        Arrange: P1.200 parquets — corporate borrower (unrated) with CDS guarantee
                 from CQS-1 institution, reporting_date=2026-06-01 (T arithmetic).
        Act:     PipelineOrchestrator with CalculationConfig.basel_3_1().
        Return:  Collected SA results DataFrame.
        """
        return _run_pipeline(_b31_config())

    @pytest.fixture(scope="class")
    def crr_sa_results(self) -> pl.DataFrame:
        """
        CRR SA pipeline results for P1.200 (regression pin — CRR already correct).

        Arrange: Same P1.200 parquets, reporting_date=2026-06-01, CRR config.
        Act:     PipelineOrchestrator with CalculationConfig.crr().
        Return:  Collected SA results DataFrame.
        """
        return _run_pipeline(_crr_config())

    # -------------------------------------------------------------------------
    # B31 DISCRIMINATING ASSERTION — FAILS pre-fix
    # -------------------------------------------------------------------------

    def test_p1_200_b31_total_rwa_applies_art_239_3_maturity_mismatch_scaling(
        self, b31_sa_results: pl.DataFrame
    ) -> None:
        """
        P1.200 DISCRIMINATING: B31 total RWA = 626,666.67 (Art. 239(3) applied).

        PS1/26 Art. 239(3): GA = G* × (t−0.25)/(T−0.25).
        With t=2.0y < T=4.0y → m = 1.75/3.75 = 0.4666...
        Guaranteed portion = 1,000,000 × m = 466,666.67 → RW = 20% (CQS 1 institution)
        Uncovered portion  = 1,000,000 − 466,666.67 = 533,333.33 → RW = 100% (unrated corp)
        Total RWA = 93,333.33 + 533,333.33 = 626,666.6666666666

        Pre-fix (current): engine skips scaling under basel_3_1() due to ``if config.is_crr``
        guard in guarantees.py → GA = 1,000,000 → RWA = 200,000.0 — this test FAILS.
        Post-fix expected: RWA = 626,666.6666666666.

        Arrange: B31 config (reporting_date=2026-06-01), EXP-200 with G-200 (t=2.0y, T=4.0y).
        Act:     Sum rwa_final across all EXP-200 sub-rows.
        Assert:  total rwa_final ≈ 626,666.6666666666 (abs=0.01).
        """
        # Arrange
        total_rwa = get_total_rwa(b31_sa_results, LOAN_REF)

        # Assert — FAILS pre-fix (engine returns 200,000.0)
        assert total_rwa == pytest.approx(EXPECTED_TOTAL_RWA_B31, abs=0.01), (
            f"P1.200 B31: total RWA should be {EXPECTED_TOTAL_RWA_B31:,.10f} "
            f"(Art. 239(3): GA = 1,000,000 × (2.0−0.25)/(4.0−0.25) = 466,666.67; "
            f"RWA = 466,666.67×0.20 + 533,333.33×1.00). "
            f"Got {total_rwa:,.4f}. "
            f"Pre-fix value {BUGGED_TOTAL_RWA:,.0f} means the is_crr guard in "
            f"guarantees.py blocked the Art. 239(3) scaling under basel_3_1()."
        )

    def test_p1_200_b31_guaranteed_portion_is_maturity_mismatch_scaled(
        self, b31_sa_results: pl.DataFrame
    ) -> None:
        """
        P1.200 DISCRIMINATING: B31 guaranteed_portion == 466,666.6666666667.

        Art. 239(3): GA = 1,000,000 × (2.0−0.25)/(4.0−0.25) = 466,666.6666666667.
        Pre-fix: guaranteed_portion = 1,000,000 (no scaling applied).

        Arrange: B31 config, EXP-200 fully guaranteed by G-200 (t=2.0y < T=4.0y).
        Act:     Sum guaranteed_portion across all EXP-200 sub-rows.
        Assert:  guaranteed_portion ≈ 466,666.6666666667 (abs=0.01).
        """
        # Arrange
        sub_rows = b31_sa_results.filter(pl.col("parent_exposure_reference") == LOAN_REF)
        assert sub_rows.height > 0, f"No SA sub-rows for parent_exposure_reference='{LOAN_REF}'"
        guaranteed_portion = sub_rows["guaranteed_portion"].sum()

        # Assert — FAILS pre-fix (engine returns 1,000,000)
        assert guaranteed_portion == pytest.approx(EXPECTED_GUARANTEED_PORTION, abs=0.01), (
            f"P1.200 B31: guaranteed_portion should be {EXPECTED_GUARANTEED_PORTION:,.10f} "
            f"(Art. 239(3): G* × (t−0.25)/(T−0.25)). "
            f"Got {guaranteed_portion:,.4f}. "
            f"Pre-fix: guaranteed_portion = 1,000,000 (guard skips maturity scaling)."
        )

    def test_p1_200_b31_guaranteed_portion_risk_weight_is_20pct(
        self, b31_sa_results: pl.DataFrame
    ) -> None:
        """
        P1.200: B31 guaranteed-portion risk_weight = 0.20 (institution CQS 1, Art. 120).

        The substituted RW on the guaranteed sub-row must reflect the guarantor
        (CP-GUARANTOR-200, institution CQS 1 → 20%) under both CRR and B31.
        This assertion should pass even pre-fix (the RW lookup itself is unaffected
        by the mismatch guard); it confirms the substitution routing is correct.

        Arrange: B31 config, guaranteed-portion sub-row for EXP-200.
        Act:     risk_weight field on the __G_ sub-row.
        Assert:  risk_weight ≈ 0.20 (abs=1e-6).
        """
        # Arrange
        row = get_guaranteed_row(b31_sa_results, LOAN_REF)

        # Assert
        actual_rw = row["risk_weight"]
        assert actual_rw == pytest.approx(EXPECTED_GUARANTOR_RW, abs=1e-6), (
            f"P1.200 B31: guaranteed-portion risk_weight should be {EXPECTED_GUARANTOR_RW:.2f} "
            f"(institution CQS 1, Art. 120 Table 3). "
            f"Got {actual_rw:.4f}."
        )

    # -------------------------------------------------------------------------
    # CRR REGRESSION PIN — must PASS both before and after the fix
    # -------------------------------------------------------------------------

    def test_p1_200_crr_total_rwa_equals_b31_value(self, crr_sa_results: pl.DataFrame) -> None:
        """
        P1.200 CRR regression: CRR total RWA == 626,666.67 (same as B31 post-fix).

        CRR Art. 239(3) is identical to PS1/26 Art. 239(3). The CRR engine already
        applies the scaling (the ``if config.is_crr`` guard fires). Post-fix both
        frameworks must yield the same RWA for the same fixture.

        This test PASSES before the fix (CRR is already correct) and must continue
        to pass after the fix (the fix must not alter CRR behaviour).

        Arrange: CRR config, same EXP-200 + G-200 fixture.
        Act:     Sum rwa_final across all EXP-200 sub-rows.
        Assert:  total rwa_final ≈ 626,666.6666666666 (abs=0.01).
        """
        # Arrange
        total_rwa = get_total_rwa(crr_sa_results, LOAN_REF)

        # Assert — regression pin (CRR already correct)
        assert total_rwa == pytest.approx(EXPECTED_TOTAL_RWA_B31, abs=0.01), (
            f"P1.200 CRR: total RWA should be {EXPECTED_TOTAL_RWA_B31:,.10f} "
            f"(CRR Art. 239(3) scaling already applied). "
            f"Got {total_rwa:,.4f}. "
            f"If this fails, the B31 fix has inadvertently broken CRR behaviour."
        )

    # -------------------------------------------------------------------------
    # EAD INTEGRITY — structural regression guard (B31)
    # -------------------------------------------------------------------------

    def test_p1_200_b31_total_ead_is_unchanged(self, b31_sa_results: pl.DataFrame) -> None:
        """
        P1.200: Art. 239(3) scales GA (covered amount), not EAD — total EAD = 1,000,000.

        Arrange: B31 config, EXP-200 drawn_amount = 1,000,000.
        Act:     Sum ead_final across all EXP-200 sub-rows.
        Assert:  total ead_final ≈ 1,000,000 (abs=1.0).
        """
        # Arrange
        sub_rows = b31_sa_results.filter(pl.col("parent_exposure_reference") == LOAN_REF)
        total_ead = sub_rows["ead_final"].sum()

        # Assert
        assert total_ead == pytest.approx(1_000_000.0, abs=1.0), (
            f"P1.200 B31: total ead_final across sub-rows should be 1,000,000 "
            f"(Art. 239(3) does not change EAD). "
            f"Got {total_ead:,.2f}"
        )
