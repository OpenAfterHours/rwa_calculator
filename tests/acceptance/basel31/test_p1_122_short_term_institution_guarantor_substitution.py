"""
P1.122 — CRR Art. 120(2) / B31 Art. 120(2) Table 4 short-term institution guarantor.

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor → SACalculator → Aggregator

Key assertion:
    When a guaranteed exposure has residual maturity ≤ 3 months (≤ 0.25y), the
    engine must route the guarantor institution's risk weight lookup through the
    short-term Table 4 (Art. 120(2)) rather than the long-term Table 3 (Art. 120(1)).

    The discriminating guarantor is CQS 2 — the only CQS where Table 3 and Table 4
    diverge in a way that distinguishes both frameworks unambiguously:

        CRR Table 3 (long-term, pre-fix bug):  CQS 2 → 50%
        CRR Table 4 (short-term, post-fix):    CQS 2 → 20%
        B31 Table 3 (long-term, pre-fix bug):  CQS 2 → 30%  (UK deviation)
        B31 Table 4 (short-term, post-fix):    CQS 2 → 20%

    Post-fix expected values (both frameworks equal at Table 4 CQS 2 = 20%):
        guarantor_rw   = 0.20
        risk_weight    = 0.20  (post-substitution RW of guaranteed portion)
        rwa            = 200,000  (EAD 1,000,000 × 0.20)

    Pre-fix values (what the current engine emits — tests FAIL against these):
        CRR guarantor_rw = 0.50 → rwa = 500,000
        B31 guarantor_rw = 0.30 → rwa = 300,000

Scenario:
    - CP-BORROWER-P1122: corporate, GB, unrated
    - CP-GUARANTOR-P1122: institution, DE, CQS 2 (Moody's A2, ECRA-rated)
    - LN-P1122: GBP 1,000,000 drawn, value_date=2025-12-31, maturity=2026-03-22
      (81-day residual ≈ 0.2219y ≤ 0.25y → short-term gate fires)
    - GTE-P1122: unfunded guarantee, 100% coverage, original_maturity_years=2.0
      (≥ 1y → eligible under Art. 237(2)(a))

References:
    - CRR Art. 120(2) Table 4: short-term preferential RW for rated institutions
    - CRR Art. 120(1) Table 3: general (long-term) rated institution RW
    - CRR Art. 235: SA risk-weight substitution method (RWSM)
    - CRR Art. 237(2)(a): minimum original maturity of unfunded protection ≥ 1 year
    - PRA PS1/26 Art. 120(2) Table 4: B31 short-term ECRA CQS 2 → 20%
    - PRA PS1/26 Art. 120(1) Table 3: B31 long-term ECRA CQS 2 → 30% (UK deviation)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import FACILITY_MAPPING_SCHEMA, LENDING_MAPPING_SCHEMA
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_122.p1_122 import (
    EXPECTED_GUARANTOR_RW_B31_TABLE4,
    EXPECTED_GUARANTOR_RW_CRR_TABLE4,
    EXPECTED_RWA_B31_POSTFIX,
    EXPECTED_RWA_CRR_POSTFIX,
    LOAN_REF,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_122" / "data"

# ---------------------------------------------------------------------------
# Config factories
# ---------------------------------------------------------------------------


def _crr_config() -> CalculationConfig:
    """CRR SA-only config (reporting_date=2025-12-31, CRR era)."""
    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    )


def _b31_config() -> CalculationConfig:
    """Basel 3.1 SA-only config (reporting_date=2025-12-31 for dual-pin test)."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2025, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    )


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle from P1.122 parquets.

    Loads counterparties, loans, facility, guarantees, and ratings from the
    scenario-local parquets in tests/fixtures/p1_122/data/.

    Facility_mappings and lending_mappings are empty frames with the correct
    schema — the p1_122 scenario has a single loan/facility pair linked
    directly, so no hierarchy-mapping rows are needed.
    """
    return make_raw_bundle(
        facilities=pl.scan_parquet(_FIXTURES_DIR / "facility.parquet"),
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
    Run the P1.122 bundle through the credit risk pipeline and return SA results.

    The CRM processor splits the guaranteed loan into two sub-rows:
      - ``LN-P1122__G_CP-GUARANTOR-P1122``: guaranteed portion (ead_final = 1,000,000)
      - ``LN-P1122__REM``: remainder (ead_final = 0, fully covered)

    Returns the collected SA results DataFrame.
    """
    bundle = _build_bundle()
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None, (
        "SA results must not be None — check PermissionMode.STANDARDISED config"
    )
    return results.sa_results.collect()


# ---------------------------------------------------------------------------
# Row selector helpers
# ---------------------------------------------------------------------------


def _get_guaranteed_row(df: pl.DataFrame) -> dict:
    """
    Return the guaranteed-portion sub-row for LN-P1122.

    The CRM processor splits a guaranteed loan into a ``__G_<guarantor>`` row
    (guaranteed portion) and a ``__REM`` row (unguaranteed remainder). For a
    100%-covered loan the ``__G_`` row carries ead_final = 1,000,000 and the
    risk_weight substituted from the guarantor's SA RW.
    """
    rows = df.filter(
        (pl.col("parent_exposure_reference") == LOAN_REF)
        & pl.col("exposure_reference").str.contains("__G_")
    ).to_dicts()
    assert len(rows) == 1, (
        f"Expected exactly 1 guaranteed-portion row for {LOAN_REF!r}, got {len(rows)}. "
        f"All rows: {df.select(['exposure_reference', 'parent_exposure_reference']).to_dicts()}"
    )
    return rows[0]


def _get_total_rwa(df: pl.DataFrame) -> float:
    """Return total rwa_final for LN-P1122 (sum across all split rows)."""
    sub_rows = df.filter(pl.col("parent_exposure_reference") == LOAN_REF)
    return sub_rows["rwa_final"].sum()


# ---------------------------------------------------------------------------
# Class-scoped SA result fixtures
# ---------------------------------------------------------------------------


class TestP1122ShortTermInstitutionGuarantorSubstitution:
    """
    P1.122: short-term institution guarantor uses Art. 120(2) Table 4 (CQS 2 → 20%).

    The engine bug: the CRM processor applies the guarantor institution's long-term
    Table 3 risk weight regardless of the borrower exposure's residual maturity.
    After the fix, when the guaranteed exposure has residual maturity ≤ 0.25y
    (≤ 3 months), the guarantor RW must be looked up from Table 4 (short-term).

    Discriminating values for CQS 2 (Table 3 ≠ Table 4):
        CRR Table 3 (pre-fix): 50% → rwa = 500,000
        CRR Table 4 (post-fix):20% → rwa = 200,000   ← test asserts this
        B31 Table 3 (pre-fix): 30% → rwa = 300,000   (UK CQS 2 deviation)
        B31 Table 4 (post-fix):20% → rwa = 200,000   ← test asserts this

    B31 and CRR tests assert POST-FIX values — they FAIL pre-fix.
    """

    @pytest.fixture(scope="class")
    def crr_sa_results(self) -> pl.DataFrame:
        """
        CRR SA pipeline results for P1.122.

        Arrange: P1.122 parquets — CQS 2 institution guarantor, 81-day loan,
                 reporting_date=2025-12-31 (CRR era).
        Act:     PipelineOrchestrator with CalculationConfig.crr().
        Return:  Collected SA results DataFrame.
        """
        return _run_pipeline(_crr_config())

    @pytest.fixture(scope="class")
    def b31_sa_results(self) -> pl.DataFrame:
        """
        Basel 3.1 SA pipeline results for P1.122.

        Arrange: Same P1.122 parquets, reporting_date=2025-12-31,
                 CalculationConfig.basel_3_1().
        Act:     PipelineOrchestrator with CalculationConfig.basel_3_1().
        Return:  Collected SA results DataFrame.
        """
        return _run_pipeline(_b31_config())

    # -------------------------------------------------------------------------
    # B31 DISCRIMINATING ASSERTIONS — FAIL pre-fix
    # -------------------------------------------------------------------------

    def test_b31_short_term_institution_guarantor_uses_table_4_cqs2_20pct(
        self, b31_sa_results: pl.DataFrame
    ) -> None:
        """
        P1.122 DISCRIMINATING: B31 guaranteed-portion risk_weight = 0.20.

        Art. 120(2) Table 4 (PRA PS1/26): short-term ECRA rated institution,
        CQS 2 → 20%. When the guaranteed exposure residual maturity ≤ 0.25y,
        the guarantor RW must be sourced from Table 4, not Table 3.

        Pre-fix (current): engine applies Table 3 (long-term) CQS 2 → 30% (UK B31
                           deviation) → risk_weight = 0.30 → this test FAILS.
        Post-fix expected: Table 4 CQS 2 → risk_weight = 0.20.

        Arrange: B31 config, CQS 2 institution guarantor (CP-GUARANTOR-P1122),
                 81-day loan (residual ≤ 0.25y), 100% guarantee coverage.
        Act:     SA results for guaranteed-portion row.
        Assert:  risk_weight ≈ 0.20 (abs=1e-6).
        """
        # Arrange
        row = _get_guaranteed_row(b31_sa_results)

        # Assert — FAILS pre-fix (engine returns 0.30 via Table 3 UK CQS 2)
        actual = row["risk_weight"]
        assert actual == pytest.approx(EXPECTED_GUARANTOR_RW_B31_TABLE4, abs=1e-6), (
            f"P1.122 B31: guaranteed-portion risk_weight should be "
            f"{EXPECTED_GUARANTOR_RW_B31_TABLE4:.2f} "
            f"(Art. 120(2) Table 4: short-term ECRA CQS 2 = 20%). "
            f"Got {actual:.4f}. "
            f"Pre-fix: engine uses Table 3 (long-term) CQS 2 → 0.30 (UK B31 deviation). "
            f"Fix required: detect residual_maturity ≤ 0.25y and route guarantor RW "
            f"lookup to Table 4."
        )

    def test_b31_rwa_post_substitution_equals_200_000(self, b31_sa_results: pl.DataFrame) -> None:
        """
        P1.122 DISCRIMINATING: B31 total RWA = 200,000.

        EAD × guarantor Table 4 RW = 1,000,000 × 0.20 = 200,000 (post-fix).
        Pre-fix: 1,000,000 × 0.30 = 300,000 (Table 3 UK CQS 2 long-term).

        Arrange: B31 config, full coverage, EAD = 1,000,000.
        Act:     Sum rwa_final across all LN-P1122 split rows.
        Assert:  total rwa_final ≈ 200,000 (abs=0.5).
        """
        # Arrange
        total_rwa = _get_total_rwa(b31_sa_results)

        # Assert — FAILS pre-fix (engine returns 300,000)
        assert total_rwa == pytest.approx(EXPECTED_RWA_B31_POSTFIX, abs=0.5), (
            f"P1.122 B31: total RWA should be {EXPECTED_RWA_B31_POSTFIX:,.0f} "
            f"(EAD 1,000,000 × Table 4 CQS 2 = 20%). "
            f"Got {total_rwa:,.0f}. "
            f"Pre-fix: RWA = 300,000 (Table 3 UK CQS 2 = 30% applied instead of Table 4 = 20%). "
            f"Delta = {total_rwa - EXPECTED_RWA_B31_POSTFIX:,.0f} (should be 0 post-fix)."
        )

    # -------------------------------------------------------------------------
    # CRR DISCRIMINATING ASSERTIONS — FAIL pre-fix
    # -------------------------------------------------------------------------

    def test_crr_short_term_institution_guarantor_uses_table_4_cqs2_20pct(
        self, crr_sa_results: pl.DataFrame
    ) -> None:
        """
        P1.122 DISCRIMINATING: CRR guaranteed-portion risk_weight = 0.20.

        CRR Art. 120(2) Table 4: short-term rated institution, CQS 2 → 20%.
        When the guaranteed exposure residual maturity ≤ 0.25y the guarantor RW
        must be sourced from Table 4, not Table 3.

        Pre-fix (current): engine applies Table 3 (long-term) CQS 2 → 50% →
                           risk_weight = 0.50 → this test FAILS.
        Post-fix expected: Table 4 CQS 2 → risk_weight = 0.20.

        Arrange: CRR config, CQS 2 institution guarantor (CP-GUARANTOR-P1122),
                 81-day loan (residual ≤ 0.25y), 100% guarantee coverage.
        Act:     SA results for guaranteed-portion row.
        Assert:  risk_weight ≈ 0.20 (abs=1e-6).
        """
        # Arrange
        row = _get_guaranteed_row(crr_sa_results)

        # Assert — FAILS pre-fix (engine returns 0.50 via Table 3 CRR CQS 2)
        actual = row["risk_weight"]
        assert actual == pytest.approx(EXPECTED_GUARANTOR_RW_CRR_TABLE4, abs=1e-6), (
            f"P1.122 CRR: guaranteed-portion risk_weight should be "
            f"{EXPECTED_GUARANTOR_RW_CRR_TABLE4:.2f} "
            f"(Art. 120(2) Table 4: short-term rated institution CQS 2 = 20%). "
            f"Got {actual:.4f}. "
            f"Pre-fix: engine uses Table 3 (long-term) CQS 2 → 0.50. "
            f"Fix required: detect residual_maturity ≤ 0.25y and route guarantor RW "
            f"lookup to Table 4."
        )

    def test_crr_rwa_post_substitution_equals_200_000(self, crr_sa_results: pl.DataFrame) -> None:
        """
        P1.122 DISCRIMINATING: CRR total RWA = 200,000.

        EAD × guarantor Table 4 RW = 1,000,000 × 0.20 = 200,000 (post-fix).
        Pre-fix: 1,000,000 × 0.50 = 500,000 (Table 3 CRR CQS 2 long-term).

        Arrange: CRR config, full coverage, EAD = 1,000,000.
        Act:     Sum rwa_final across all LN-P1122 split rows.
        Assert:  total rwa_final ≈ 200,000 (abs=0.5).
        """
        # Arrange
        total_rwa = _get_total_rwa(crr_sa_results)

        # Assert — FAILS pre-fix (engine returns 500,000)
        assert total_rwa == pytest.approx(EXPECTED_RWA_CRR_POSTFIX, abs=0.5), (
            f"P1.122 CRR: total RWA should be {EXPECTED_RWA_CRR_POSTFIX:,.0f} "
            f"(EAD 1,000,000 × Table 4 CQS 2 = 20%). "
            f"Got {total_rwa:,.0f}. "
            f"Pre-fix: RWA = 500,000 (Table 3 CQS 2 = 50% applied instead of Table 4 = 20%). "
            f"Delta = {total_rwa - EXPECTED_RWA_CRR_POSTFIX:,.0f} (should be 0 post-fix)."
        )

    # -------------------------------------------------------------------------
    # GUARANTEE ELIGIBILITY — structural guard (both frameworks)
    # -------------------------------------------------------------------------

    def test_guaranteed_portion_is_full_under_art_237_eligibility(
        self, crr_sa_results: pl.DataFrame
    ) -> None:
        """
        P1.122: guarantee_ratio = 1.0 (100% coverage, original_maturity_years ≥ 1y).

        GTE-P1122 has original_maturity_years=2.0 ≥ 1.0y → satisfies Art. 237(2)(a).
        No maturity mismatch haircut applies (guarantee maturity 2027-12-31 >
        loan maturity 2026-03-22). The engine field ``guarantee_ratio`` records the
        fraction of EAD that is covered (0.0–1.0) on the guaranteed-portion row.

        Arrangement: CRR config; GTE-P1122 percentage_covered = 1.0, eligible maturity.
        Act:         CRM processor splits LN-P1122; guaranteed portion row.
        Assert:      guarantee_ratio == 1.0 (full coverage).
        """
        # Arrange
        row = _get_guaranteed_row(crr_sa_results)

        # Assert — regression guard (must hold before and after fix)
        assert row["guarantee_ratio"] == pytest.approx(1.0, abs=1e-6), (
            f"P1.122: guarantee_ratio should be 1.0 (full coverage, "
            f"original_maturity_years=2.0 ≥ 1y satisfies Art. 237(2)(a)). "
            f"Got {row['guarantee_ratio']!r}"
        )

    def test_ead_final_equals_drawn_amount(self, crr_sa_results: pl.DataFrame) -> None:
        """
        P1.122: guaranteed-portion ead_final = 1,000,000.

        No FX conversion (GBP loan, GBP guarantee), no CCF (full_risk on-balance-sheet
        drawn), no maturity-mismatch EAD scaling. EAD = drawn_amount = 1,000,000.

        Arrange: CRR config, drawn_amount=1,000,000, interest=0, no FX mismatch.
        Act:     SA results guaranteed-portion row.
        Assert:  ead_final ≈ 1,000,000 (abs=1.0).
        """
        # Arrange
        row = _get_guaranteed_row(crr_sa_results)

        # Assert — regression guard
        assert row["ead_final"] == pytest.approx(1_000_000.0, abs=1.0), (
            f"P1.122: guaranteed-portion ead_final should be 1,000,000 "
            f"(drawn_amount=1,000,000, no CCF, no FX mismatch). "
            f"Got {row['ead_final']:,.0f}"
        )
