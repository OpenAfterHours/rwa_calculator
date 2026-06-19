"""
P1.110 — B31 SA RWSM: corporate CQS 3 guarantor risk weight = 75% (Art. 122(2) Table 6).

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor → SACalculator → Aggregator

Key assertion:
    B31 Art. 122(2) Table 6: corporate CQS 3 SA risk weight = 75% (0.75).
    Under SA guarantee substitution (RWSM), the guarantor's B31 risk weight is
    applied to the guaranteed portion. When the guarantor is corporate CQS 3,
    the substituted RW must be 0.75, not 1.00 (the CRR value).

    Pre-fix: the engine uses CRR corporate CQS 3 = 100% for both frameworks.
    Post-fix: the engine looks up B31 Art. 122(2) Table 6 → CQS 3 = 75%.

Discriminating values (borrowed from fixture module docstring):
    B31 (post-fix expected):
        guarantor RW  = 0.75 (corporate CQS 3, Art. 122(2) Table 6)
        guaranteed-portion risk_weight = 0.75
        total RWA     = 1,000,000 × 0.75 = 750,000

    CRR (regression — must pass before and after fix):
        guarantor RW  = 1.00 (corporate CQS 3, CRR Table 5)
        guaranteed-portion risk_weight = 1.00
        total RWA     = 1,000,000 × 1.00 = 1,000,000

    Borrower pre-CRM: corporate CQS 5 → 1.50 (CRR) / 1.00 (B31)
    Guarantee: full coverage (100%), original_maturity_years=5.0 (≥ 1y → eligible)

References:
    - PRA PS1/26 Art. 122(2) Table 6: B31 corporate SA risk weights by CQS
      (CQS 3 = 75%)
    - PRA PS1/26 Art. 235: SA risk-weight substitution method (RWSM)
    - CRR Table 5: CRR corporate SA risk weights (CQS 3 = 100%)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import FACILITY_MAPPING_SCHEMA, FACILITY_SCHEMA, LENDING_MAPPING_SCHEMA
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_110" / "data"

# Loan reference from fixture module (LOAN_REF = "LOAN_P1110")
_LOAN_REF = "LOAN_P1110"

# Expected values (from fixture module and task description)
_EXPECTED_RW_B31 = 0.75  # corporate CQS 3, B31 Art. 122(2) Table 6 — post-fix
_EXPECTED_RWA_B31 = 750_000.0  # 1,000,000 × 0.75 — post-fix

_EXPECTED_RW_CRR = 1.00  # corporate CQS 3, CRR Table 5 — regression pin
_EXPECTED_RWA_CRR = 1_000_000.0  # 1,000,000 × 1.00 — regression pin

# Pre-fix values (what the engine currently emits, causing the test to fail)
_PREFIX_RW_B31 = 1.00  # bug: returns CRR value instead of B31 value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle from P1.110 parquets.

    Loans, counterparties, guarantees, and ratings are loaded from the
    fixture parquets in tests/fixtures/p1_110/data/. Facilities,
    facility_mappings, and lending_mappings are empty frames because
    this scenario only uses drawn loan data — no undrawn facility rows
    or hierarchy mappings are required.
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


def _b31_config() -> CalculationConfig:
    """Basel 3.1 SA-only config (post-go-live, 2027-12-31)."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    )


def _crr_config() -> CalculationConfig:
    """CRR SA-only config (pre-Basel-3.1 effective date, 2025-12-31)."""
    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    )


def _run_pipeline(config: CalculationConfig) -> pl.DataFrame:
    """
    Run the P1.110 fixtures through the credit risk pipeline and return the
    SA results DataFrame.

    The guaranteed loan is split into two rows by the CRM processor:
      - ``LOAN_P1110__G_CP_GUARANTOR_P1110``: the guaranteed portion
        (parent_exposure_reference = LOAN_P1110, ead_final = 1,000,000)
      - ``LOAN_P1110__REM``: the remainder (ead_final = 0 — fully covered)

    Returns the collected SA results DataFrame for assertion.
    """
    bundle = _build_bundle()
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None, (
        "SA results should not be None — check PermissionMode.STANDARDISED config"
    )
    return results.sa_results.collect()


def _get_guaranteed_row(df: pl.DataFrame) -> dict:
    """
    Return the guaranteed-portion row for LOAN_P1110.

    The CRM processor splits fully-guaranteed loans into a ``__G_<guarantor>``
    row (the guaranteed portion) and a ``__REM`` row (the unguaranteed remainder).
    For a 100%-covered loan the ``__G_`` row carries EAD = 1,000,000 and the
    risk weight substituted from the guarantor's SA RW.
    """
    rows = df.filter(
        (pl.col("parent_exposure_reference") == _LOAN_REF)
        & pl.col("exposure_reference").str.contains("__G_")
    ).to_dicts()
    assert len(rows) == 1, (
        f"Expected exactly 1 guaranteed-portion row for {_LOAN_REF}, got {len(rows)}. "
        f"All rows: {df.select(['exposure_reference', 'parent_exposure_reference']).to_dicts()}"
    )
    return rows[0]


def _get_total_rwa(df: pl.DataFrame) -> float:
    """
    Return the total RWA for the LOAN_P1110 loan (sum across all split rows).

    The parent exposure is split into sub-rows by the CRM processor.
    Summing rwa_final across all rows with parent_exposure_reference == LOAN_P1110
    gives the consolidated RWA.
    """
    sub_rows = df.filter(pl.col("parent_exposure_reference") == _LOAN_REF)
    return sub_rows["rwa_final"].sum()


# ---------------------------------------------------------------------------
# P1.110 acceptance test class (parametrised over B31 and CRR)
# ---------------------------------------------------------------------------

_PARAMS = [
    pytest.param(
        "b31",
        _EXPECTED_RW_B31,
        _EXPECTED_RWA_B31,
        id="b31-corporate-cqs3-guaranteed-rw-75pct",
    ),
    pytest.param(
        "crr",
        _EXPECTED_RW_CRR,
        _EXPECTED_RWA_CRR,
        id="crr-corporate-cqs3-guaranteed-rw-100pct",
    ),
]


class TestP1110Art122CorporateCQS3GuaranteeSubstitution:
    """
    P1.110: B31 SA RWSM corporate CQS 3 guarantor risk weight = 75%.

    Art. 235 (PRA PS1/26): guarantee substitution applies the guarantor's SA
    risk weight to the guaranteed portion, provided that weight is lower than
    the borrower's pre-CRM weight. When the guarantor is corporate CQS 3:

        B31 Art. 122(2) Table 6: 75% (PRA PS1/26 Table 6)
        CRR Table 5:             100%

    The bug: before the fix the engine uses 100% for both frameworks because the
    SA risk-weight lookup for guarantors reads from the CRR table regardless of
    the framework config. After the fix the B31 table returns 75%.

    Discriminating assertions (B31 case FAILS pre-fix):
        guaranteed-portion risk_weight ≈ 0.75 (pre-fix: 1.00)
        total RWA ≈ 750,000 (pre-fix: 1,000,000)

    Regression pin (CRR case PASSES pre-fix and must continue to PASS post-fix):
        guaranteed-portion risk_weight ≈ 1.00
        total RWA ≈ 1,000,000
    """

    @pytest.fixture(scope="class")
    def b31_sa_results(self) -> pl.DataFrame:
        """
        Basel 3.1 SA pipeline results for P1.110 scenario.

        Arrange: P1.110 parquets — corporate borrower (CQS 5) with 100% corporate
                 guarantee (CQS 3) and reporting_date=2027-12-31 (post-go-live).
        Act:     CreditRiskCalc via PipelineOrchestrator with CalculationConfig.basel_3_1().
        Return:  Collected SA results DataFrame.
        """
        return _run_pipeline(_b31_config())

    @pytest.fixture(scope="class")
    def crr_sa_results(self) -> pl.DataFrame:
        """
        CRR SA pipeline results for P1.110 scenario (regression pin).

        Arrange: Same P1.110 parquets, reporting_date=2025-12-31 (CRR era).
        Act:     PipelineOrchestrator with CalculationConfig.crr().
        Return:  Collected SA results DataFrame.
        """
        return _run_pipeline(_crr_config())

    # -------------------------------------------------------------------------
    # B31 DISCRIMINATING ASSERTION — this FAILS before the engine fix
    # -------------------------------------------------------------------------

    def test_p1_110_b31_guaranteed_risk_weight_is_75pct(self, b31_sa_results: pl.DataFrame) -> None:
        """
        P1.110 DISCRIMINATING: B31 guaranteed-portion risk_weight = 0.75.

        Art. 122(2) Table 6 (PRA PS1/26): corporate CQS 3 SA risk weight = 75%.
        Under RWSM the guarantor's SA RW replaces the borrower's pre-CRM RW
        on the guaranteed portion. For a CQS 3 corporate guarantor under B31,
        the substituted RW must be 0.75.

        Pre-fix (current): engine returns 1.00 (CRR Table 5 value used for both
                           frameworks) → this test FAILS.
        Post-fix expected: 0.75 (B31 Art. 122(2) Table 6 CQS 3).

        Arrange: B31 config, corporate CQS 3 guarantor (CP_GUARANTOR_P1110),
                 100% coverage of GBP 1,000,000 term loan.
        Act:     Pipeline SA results for LOAN_P1110 guaranteed-portion row.
        Assert:  risk_weight ≈ 0.75 (abs=1e-6).
        """
        # Arrange
        row = _get_guaranteed_row(b31_sa_results)

        # Assert — FAILS pre-fix (engine returns 1.00)
        actual = row["risk_weight"]
        assert actual == pytest.approx(_EXPECTED_RW_B31, abs=1e-6), (
            f"P1.110 B31: guaranteed-portion risk_weight should be {_EXPECTED_RW_B31:.2f} "
            f"(Art. 122(2) Table 6: corporate CQS 3 = 75%). "
            f"Got {actual:.4f}. "
            f"Pre-fix value ~{_PREFIX_RW_B31:.2f} means guarantor SA RW lookup is reading "
            f"CRR Table 5 (100%) instead of B31 Table 6 (75%) for guarantee substitution."
        )

    def test_p1_110_b31_total_rwa_is_750k(self, b31_sa_results: pl.DataFrame) -> None:
        """
        P1.110 DISCRIMINATING: B31 total RWA = 750,000.

        EAD × guarantor RW = 1,000,000 × 0.75 = 750,000 (post-fix).
        Pre-fix: 1,000,000 × 1.00 = 1,000,000 (overstates capital by 250,000).

        Arrange: B31 config, full coverage, EAD = 1,000,000.
        Act:     Sum rwa_final across all LOAN_P1110 split rows.
        Assert:  total rwa_final ≈ 750,000 (abs=1.0).
        """
        # Arrange
        total_rwa = _get_total_rwa(b31_sa_results)

        # Assert — FAILS pre-fix (engine returns 1,000,000)
        assert total_rwa == pytest.approx(_EXPECTED_RWA_B31, abs=1.0), (
            f"P1.110 B31: total RWA should be {_EXPECTED_RWA_B31:,.0f} "
            f"(EAD 1,000,000 × guarantor RW 0.75). "
            f"Got {total_rwa:,.0f}. "
            f"Pre-fix: RWA = 1,000,000 (CRR RW 1.00 used instead of B31 RW 0.75). "
            f"Delta = {total_rwa - _EXPECTED_RWA_B31:,.0f} (should be 0 post-fix)."
        )

    # -------------------------------------------------------------------------
    # CRR REGRESSION PIN — must PASS both before and after the fix
    # -------------------------------------------------------------------------

    def test_p1_110_crr_guaranteed_risk_weight_is_100pct(
        self, crr_sa_results: pl.DataFrame
    ) -> None:
        """
        P1.110 CRR regression: guaranteed-portion risk_weight = 1.00 (CRR Table 5).

        CRR Art. 122 Table 5: corporate CQS 3 SA risk weight = 100%.
        This must remain 1.00 after the B31 fix to confirm CRR behaviour is
        not changed by the B31 table routing.

        Arrange: CRR config, same P1.110 parquets.
        Act:     Pipeline SA results for LOAN_P1110 guaranteed-portion row.
        Assert:  risk_weight ≈ 1.00 (abs=1e-6).
        """
        # Arrange
        row = _get_guaranteed_row(crr_sa_results)

        # Assert — regression pin (must PASS before and after fix)
        actual = row["risk_weight"]
        assert actual == pytest.approx(_EXPECTED_RW_CRR, abs=1e-6), (
            f"P1.110 CRR regression: guaranteed-portion risk_weight should be "
            f"{_EXPECTED_RW_CRR:.2f} (CRR Table 5: corporate CQS 3 = 100%). "
            f"Got {actual:.4f}. "
            f"The B31 fix must not change CRR Table 5 routing."
        )

    def test_p1_110_crr_total_rwa_is_1m(self, crr_sa_results: pl.DataFrame) -> None:
        """
        P1.110 CRR regression: total RWA = 1,000,000.

        EAD × guarantor RW = 1,000,000 × 1.00 = 1,000,000 under CRR.
        This value must remain unchanged after the B31 fix.

        Arrange: CRR config, full coverage, EAD = 1,000,000.
        Act:     Sum rwa_final across all LOAN_P1110 split rows.
        Assert:  total rwa_final ≈ 1,000,000 (abs=1.0).
        """
        # Arrange
        total_rwa = _get_total_rwa(crr_sa_results)

        # Assert — regression pin
        assert total_rwa == pytest.approx(_EXPECTED_RWA_CRR, abs=1.0), (
            f"P1.110 CRR regression: total RWA should be {_EXPECTED_RWA_CRR:,.0f} "
            f"(EAD 1,000,000 × guarantor RW 1.00 per CRR Table 5). "
            f"Got {total_rwa:,.0f}."
        )

    # -------------------------------------------------------------------------
    # EAD INTEGRITY — regression guard (both frameworks)
    # -------------------------------------------------------------------------

    def test_p1_110_b31_guaranteed_ead_is_1m(self, b31_sa_results: pl.DataFrame) -> None:
        """
        P1.110: guaranteed-portion EAD = 1,000,000 (full coverage under B31).

        The 100% coverage guarantee allocates the entire EAD to the guaranteed
        portion. The remainder row carries EAD = 0.

        Arrange: B31 config, 100% coverage, drawn_amount=1,000,000, interest=0.
        Act:     guaranteed-portion row ead_final.
        Assert:  ead_final ≈ 1,000,000 (abs=1.0).
        """
        # Arrange
        row = _get_guaranteed_row(b31_sa_results)

        # Assert
        assert row["ead_final"] == pytest.approx(1_000_000.0, abs=1.0), (
            f"P1.110 B31: guaranteed-portion ead_final should be 1,000,000, "
            f"got {row['ead_final']:,.0f}"
        )

    def test_p1_110_crr_guaranteed_ead_is_1m(self, crr_sa_results: pl.DataFrame) -> None:
        """
        P1.110: guaranteed-portion EAD = 1,000,000 (full coverage under CRR).

        Arrange: CRR config, 100% coverage, drawn_amount=1,000,000, interest=0.
        Act:     guaranteed-portion row ead_final.
        Assert:  ead_final ≈ 1,000,000 (abs=1.0).
        """
        # Arrange
        row = _get_guaranteed_row(crr_sa_results)

        # Assert
        assert row["ead_final"] == pytest.approx(1_000_000.0, abs=1.0), (
            f"P1.110 CRR: guaranteed-portion ead_final should be 1,000,000, "
            f"got {row['ead_final']:,.0f}"
        )

    # -------------------------------------------------------------------------
    # FRAMEWORK DELTA — structural validation
    # -------------------------------------------------------------------------

    def test_p1_110_b31_rwa_lower_than_crr_by_250k(
        self,
        b31_sa_results: pl.DataFrame,
        crr_sa_results: pl.DataFrame,
    ) -> None:
        """
        P1.110: B31 RWA should be 250,000 less than CRR RWA (post-fix).

        Delta = EAD × (CRR_guarantor_rw − B31_guarantor_rw) × coverage
              = 1,000,000 × (1.00 − 0.75) × 1.00 = 250,000.

        Pre-fix: both frameworks return the same RWA (1,000,000), so the delta
        is zero — this test FAILS pre-fix for the same reason as the B31 tests.

        Arrange: B31 and CRR results for LOAN_P1110 with full guarantee coverage.
        Act:     crr_rwa - b31_rwa.
        Assert:  delta ≈ 250,000 (abs=1.0).
        """
        # Arrange
        b31_rwa = _get_total_rwa(b31_sa_results)
        crr_rwa = _get_total_rwa(crr_sa_results)

        # Assert — FAILS pre-fix (both frameworks return 1,000,000, delta = 0)
        assert crr_rwa - b31_rwa == pytest.approx(250_000.0, abs=1.0), (
            f"P1.110: B31 RWA ({b31_rwa:,.0f}) should be 250,000 less than "
            f"CRR RWA ({crr_rwa:,.0f}). "
            f"Delta = {crr_rwa - b31_rwa:,.0f}. "
            f"Expected 250,000 = 1,000,000 × (1.00 − 0.75). "
            f"If delta = 0: B31 guarantor RW still using CRR table (100%) — fix not applied."
        )
