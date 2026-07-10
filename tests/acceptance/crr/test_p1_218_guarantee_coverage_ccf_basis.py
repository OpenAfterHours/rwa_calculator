"""
P1.218 — CRR Art. 235(1)/236(3): guarantee coverage fraction must be measured on
the CCF=100% basis (``ead_for_crm``), not the post-CCF ``ead_after_collateral``.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Confirm that a partially-guaranteed, fully-undrawn Medium-Risk (50% CCF)
  commitment measures the covered part ``Eg = min(GA, E)`` against ``E`` at
  100% of the off-balance-sheet value, with the CCF re-applied to the
  covered/uncovered split afterwards (CRR Art. 235(1) / Art. 236(3)).
- Total RWA = 340,000 (covered 200,000 x 20% + uncovered 300,000 x 100%).

Defect under test (pre-fix):
    The CRM processor caps and pro-rates guarantee coverage against
    ``ead_after_collateral`` (already post-CCF), instead of ``ead_for_crm``
    (the CCF=100% basis). On this scenario that shrinks the coverage
    denominator from 1,000,000 to 500,000, over-recognising cover and
    understating total RWA at 180,000 instead of the correct 340,000 — a
    47.06% understatement (CRR Art. 235(1)/236(3)).

References:
    - CRR Art. 235(1): RWSM covered part Eg = min(GA, E), measured at CCF=100%.
    - CRR Art. 236(3): PSM CCF=100% override for the covered/uncovered split.
    - CRR Art. 111 / Annex I: SA CCF; Medium Risk commitment = 50%.
    - CRR Art. 122: corporate risk weights (CQS1 = 20%, unrated = 100%).
    - tests/fixtures/p1_218/p1_218.py: fixture builder and scenario constants.
    - docs/plans/compliance-audit-crr-111-241-rectification.md Section 5 WS2,
      P1.218.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p1_218.p1_218 import (
    BORROWER_REF,
    EXPECTED_BLENDED_RW,
    EXPECTED_BORROWER_RW,
    EXPECTED_COVERED_EAD,
    EXPECTED_COVERED_RWA,
    EXPECTED_GUARANTOR_RW,
    EXPECTED_TOTAL_EAD,
    EXPECTED_TOTAL_RWA,
    EXPECTED_UNCOVERED_EAD,
    EXPECTED_UNCOVERED_RWA,
    FACILITY_REF,
    GUARANTOR_REF,
    REPORTING_DATE,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import FACILITY_MAPPING_SCHEMA, LENDING_MAPPING_SCHEMA, LOAN_SCHEMA
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_218"

# The facility-undrawn hierarchy stage (engine/stages/hierarchy/facility_undrawn.py)
# synthesises one exposure per undrawn facility with exposure_reference =
# "<facility_reference>_UNDRAWN"; the CRM guarantee split then re-parents its
# sub-rows under that synthetic reference (not the raw facility_reference).
_UNDRAWN_EXPOSURE_REF = f"{FACILITY_REF}_UNDRAWN"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle from the P1.218 parquets.

    Facilities, counterparties, ratings and guarantees are loaded from the
    fixture parquets in tests/fixtures/p1_218/. Loans, facility_mappings and
    lending_mappings are empty frames — this scenario is a fully-undrawn
    commitment (no linked loan, no hierarchy mappings).
    """
    return make_raw_bundle(
        facilities=pl.scan_parquet(_FIXTURES_DIR / "facility.parquet"),
        loans=pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA)),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        guarantees=pl.scan_parquet(_FIXTURES_DIR / "guarantee.parquet"),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
    )


def _crr_config() -> CalculationConfig:
    """CRR SA-only config, reporting_date matching the fixture's value_date."""
    return CalculationConfig.crr(
        reporting_date=REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


def _run_pipeline() -> pl.DataFrame:
    """
    Run the P1.218 fixtures through the full CRR SA pipeline and return the
    collected SA results DataFrame (all sub-rows, including guarantee splits).
    """
    bundle = _build_bundle()
    results = PipelineOrchestrator().run_with_data(bundle, _crr_config())
    assert results.sa_results is not None, (
        "SA results should not be None — check PermissionMode.STANDARDISED config"
    )
    return results.sa_results.collect()


def _sub_rows(df: pl.DataFrame) -> pl.DataFrame:
    """All SA result sub-rows for the FAC_UNDRAWN synthetic exposure (covered + remainder)."""
    sub_rows = df.filter(pl.col("parent_exposure_reference") == _UNDRAWN_EXPOSURE_REF)
    assert sub_rows.height > 0, (
        f"No SA result rows found with parent_exposure_reference='{_UNDRAWN_EXPOSURE_REF}'"
    )
    return sub_rows


def _covered_row(df: pl.DataFrame) -> dict:
    """
    The guarantor-covered sub-row for FAC_UNDRAWN.

    Grouped by the ``is_guaranteed`` flag (guaranteed_portion > 0) rather than
    the ``__G_`` exposure_reference suffix, per the scenario's row-naming
    guidance (fixture-builder/test-writer own the exact suffix strings).
    """
    rows = _sub_rows(df).filter(pl.col("is_guaranteed") == True).to_dicts()  # noqa: E712
    assert len(rows) == 1, (
        f"Expected exactly 1 guaranteed-portion row for {_UNDRAWN_EXPOSURE_REF}, "
        f"got {len(rows)}. "
        f"All rows: {df.select(['exposure_reference', 'parent_exposure_reference']).to_dicts()}"
    )
    return rows[0]


def _remainder_row(df: pl.DataFrame) -> dict:
    """The borrower-retained remainder sub-row for FAC_UNDRAWN (guaranteed_portion == 0)."""
    rows = _sub_rows(df).filter(pl.col("is_guaranteed") == False).to_dicts()  # noqa: E712
    assert len(rows) == 1, (
        f"Expected exactly 1 remainder row for {_UNDRAWN_EXPOSURE_REF}, got {len(rows)}. "
        f"All rows: {df.select(['exposure_reference', 'parent_exposure_reference']).to_dicts()}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# P1.218 acceptance tests
# ---------------------------------------------------------------------------


class TestP1218GuaranteeCoverageCCFBasis:
    """
    P1.218: CRR Art. 235(1)/236(3) — guarantee coverage fraction measured on
    the CCF=100% basis (``ead_for_crm``), not the post-CCF ``ead_after_collateral``.

    FAC_UNDRAWN: GBP 1,000,000 fully-undrawn Medium-Risk (50% CCF) commitment.
    GTE_1: CP_GUARANTOR (CQS 1, 20% RW) covers GBP 400,000 (nominal, absolute
    amount) of the facility. Borrower (CP_BORROWER) is unrated corporate (100% RW).

    Hand calc (post-fix, the correct result):
        E (ead_for_crm, CCF=100%)      = 1,000,000
        ead_after_collateral (CCF=50%) = 500,000
        GA = min(400,000, 1,000,000)   = 400,000
        coverage_fraction f = GA / E   = 0.40
        Covered EAD   = f * 500,000    = 200,000  -> RWA = 200,000 x 0.20 = 40,000
        Uncovered EAD = (1-f) * 500,000 = 300,000 -> RWA = 300,000 x 1.00 = 300,000
        Total EAD = 500,000; Total RWA = 340,000; blended RW = 0.68

    Pre-fix (buggy) engine: coverage measured against ead_after_collateral
    (500,000) instead of ead_for_crm (1,000,000) -> total RWA = 180,000
    (47.06% understatement vs the correct 340,000).
    """

    @pytest.fixture(scope="class")
    def sa_results(self) -> pl.DataFrame:
        """SA pipeline results for the P1.218 scenario (class-scoped, one pipeline run)."""
        return _run_pipeline()

    # -------------------------------------------------------------------------
    # ANCHOR ASSERTION — exposure-total RWA. FAILS pre-fix (180,000 vs 340,000).
    # -------------------------------------------------------------------------

    def test_p1_218_exposure_total_rwa_is_340k(self, sa_results: pl.DataFrame) -> None:
        """
        P1.218 DISCRIMINATING (primary regression guard): exposure-total
        rwa_final == 340,000.

        Arrange: FAC_UNDRAWN (GBP 1,000,000 undrawn, MR 50% CCF) + GTE_1
                 (CP_GUARANTOR covers GBP 400,000 nominal, CQS 1 -> 20% RW).
        Act:     full CRR SA pipeline; sum rwa_final across FAC_UNDRAWN sub-rows.
        Assert:  total rwa_final == 340,000 (Art. 235(1)/236(3): coverage fraction
                 measured against the CCF=100% basis, then the CCF re-applied).

        Pre-fix the engine measures coverage against ead_after_collateral
        (already post-CCF), over-recognising cover and returning 180,000.
        """
        # Arrange
        sub_rows = _sub_rows(sa_results)

        # Act
        total_rwa = sub_rows["rwa_final"].sum()

        # Assert
        assert total_rwa == pytest.approx(EXPECTED_TOTAL_RWA, abs=1.0), (
            f"P1.218: exposure-total rwa_final should be {EXPECTED_TOTAL_RWA:,.0f} "
            f"(covered 200,000 x 0.20 + uncovered 300,000 x 1.00). "
            f"Got {total_rwa:,.2f}. "
            f"Pre-fix value ~180,000 means coverage is measured against "
            f"ead_after_collateral (post-CCF) instead of ead_for_crm (CCF=100% basis) — "
            f"fix _join_multi_guarantees in engine/crm/guarantees.py."
        )

    # -------------------------------------------------------------------------
    # EAD INVARIANT — EAD is unchanged between buggy and fixed engine.
    # -------------------------------------------------------------------------

    def test_p1_218_exposure_total_ead_is_500k(self, sa_results: pl.DataFrame) -> None:
        """
        P1.218: exposure-total ead_final == 500,000 (invariant — unaffected by the fix).

        The defect only shifts exposure between risk-weight bands; EAD is
        unchanged (E x CCF = 1,000,000 x 0.50 = 500,000) both pre- and post-fix.

        Arrange: FAC_UNDRAWN + GTE_1.
        Act:     full CRR SA pipeline; sum ead_final across FAC_UNDRAWN sub-rows.
        Assert:  total ead_final == 500,000.
        """
        # Arrange
        sub_rows = _sub_rows(sa_results)

        # Act
        total_ead = sub_rows["ead_final"].sum()

        # Assert
        assert total_ead == pytest.approx(EXPECTED_TOTAL_EAD, abs=1.0), (
            f"P1.218: exposure-total ead_final should be {EXPECTED_TOTAL_EAD:,.0f} "
            f"(E 1,000,000 x CCF 0.50), got {total_ead:,.2f}"
        )

    def test_p1_218_exposure_total_blended_risk_weight(self, sa_results: pl.DataFrame) -> None:
        """
        P1.218: blended risk weight = total RWA / total EAD == 0.68.

        Arrange: FAC_UNDRAWN + GTE_1.
        Act:     total rwa_final / total ead_final.
        Assert:  blended RW == 0.68 (pre-fix: 180,000 / 500,000 = 0.36).
        """
        # Arrange
        sub_rows = _sub_rows(sa_results)

        # Act
        total_rwa = sub_rows["rwa_final"].sum()
        total_ead = sub_rows["ead_final"].sum()
        blended_rw = total_rwa / total_ead

        # Assert
        assert blended_rw == pytest.approx(EXPECTED_BLENDED_RW, abs=1e-4), (
            f"P1.218: blended risk weight should be {EXPECTED_BLENDED_RW:.4f}, "
            f"got {blended_rw:.4f} (rwa={total_rwa:,.2f}, ead={total_ead:,.2f})"
        )

    # -------------------------------------------------------------------------
    # TWO-WAY SPLIT — covered sub-row (200,000 @ 20%) and remainder (300,000 @ 100%).
    # -------------------------------------------------------------------------

    def test_p1_218_covered_sub_row_ead_is_200k(self, sa_results: pl.DataFrame) -> None:
        """
        P1.218 DISCRIMINATING: covered sub-row ead_final == 200,000.

        Coverage fraction f = GA / E = 400,000 / 1,000,000 = 0.40 (measured
        against the CCF=100% basis). Covered EAD = f x ead_after_collateral
        = 0.40 x 500,000 = 200,000.

        Pre-fix the engine measures f against ead_after_collateral (500,000)
        giving f = 0.80, so the covered sub-row EAD is 400,000 instead.
        """
        # Arrange
        row = _covered_row(sa_results)

        # Assert
        assert row["ead_final"] == pytest.approx(EXPECTED_COVERED_EAD, abs=1.0), (
            f"P1.218: covered sub-row ead_final should be {EXPECTED_COVERED_EAD:,.0f} "
            f"(coverage_fraction 0.40 x ead_after_collateral 500,000), "
            f"got {row['ead_final']:,.2f}. Pre-fix value ~400,000 means coverage was "
            f"measured against the post-CCF ead_after_collateral instead of ead_for_crm."
        )

    def test_p1_218_covered_sub_row_risk_weight_is_guarantor_rw(
        self, sa_results: pl.DataFrame
    ) -> None:
        """
        P1.218: covered sub-row risk_weight == 0.20 (guarantor CQS 1, CRR Art. 122).

        Arrange: CP_GUARANTOR rated CQS 1 -> 20% corporate SA RW.
        Act:     covered sub-row risk_weight (guarantee substitution).
        Assert:  risk_weight == 0.20.
        """
        # Arrange
        row = _covered_row(sa_results)

        # Assert
        assert row["risk_weight"] == pytest.approx(EXPECTED_GUARANTOR_RW, abs=1e-6), (
            f"P1.218: covered sub-row risk_weight should be {EXPECTED_GUARANTOR_RW:.2f} "
            f"(CRR Art. 122, corporate CQS 1), got {row['risk_weight']:.4f}"
        )

    def test_p1_218_covered_sub_row_rwa_is_40k(self, sa_results: pl.DataFrame) -> None:
        """
        P1.218 DISCRIMINATING: covered sub-row rwa_final == 40,000 (200,000 x 0.20).

        Pre-fix: covered EAD is 400,000 (bug), giving rwa_final = 80,000.
        """
        # Arrange
        row = _covered_row(sa_results)

        # Assert
        assert row["rwa_final"] == pytest.approx(EXPECTED_COVERED_RWA, abs=1.0), (
            f"P1.218: covered sub-row rwa_final should be {EXPECTED_COVERED_RWA:,.0f} "
            f"(200,000 x 0.20), got {row['rwa_final']:,.2f}. "
            f"Pre-fix value ~80,000 means covered EAD is 400,000 instead of 200,000."
        )

    def test_p1_218_remainder_sub_row_ead_is_300k(self, sa_results: pl.DataFrame) -> None:
        """
        P1.218 DISCRIMINATING: remainder sub-row ead_final == 300,000.

        Uncovered EAD = (1 - 0.40) x ead_after_collateral = 0.60 x 500,000 = 300,000.
        Pre-fix the remainder is only 500,000 - 400,000 = 100,000.
        """
        # Arrange
        row = _remainder_row(sa_results)

        # Assert
        assert row["ead_final"] == pytest.approx(EXPECTED_UNCOVERED_EAD, abs=1.0), (
            f"P1.218: remainder sub-row ead_final should be {EXPECTED_UNCOVERED_EAD:,.0f} "
            f"(ead_after_collateral 500,000 - covered 200,000), got {row['ead_final']:,.2f}. "
            f"Pre-fix value ~100,000 means the covered portion over-recognised cover."
        )

    def test_p1_218_remainder_sub_row_risk_weight_is_borrower_rw(
        self, sa_results: pl.DataFrame
    ) -> None:
        """
        P1.218: remainder sub-row risk_weight == 1.00 (CP_BORROWER unrated corporate).

        Arrange: CP_BORROWER unrated -> 100% corporate SA RW (CRR Art. 122).
        Act:     remainder sub-row risk_weight (no guarantee substitution).
        Assert:  risk_weight == 1.00.
        """
        # Arrange
        row = _remainder_row(sa_results)

        # Assert
        assert row["risk_weight"] == pytest.approx(EXPECTED_BORROWER_RW, abs=1e-6), (
            f"P1.218: remainder sub-row risk_weight should be {EXPECTED_BORROWER_RW:.2f} "
            f"(CRR Art. 122, unrated corporate), got {row['risk_weight']:.4f}"
        )

    def test_p1_218_remainder_sub_row_rwa_is_300k(self, sa_results: pl.DataFrame) -> None:
        """
        P1.218 DISCRIMINATING: remainder sub-row rwa_final == 300,000 (300,000 x 1.00).

        Pre-fix: remainder EAD is 100,000 (bug), giving rwa_final = 100,000.
        """
        # Arrange
        row = _remainder_row(sa_results)

        # Assert
        assert row["rwa_final"] == pytest.approx(EXPECTED_UNCOVERED_RWA, abs=1.0), (
            f"P1.218: remainder sub-row rwa_final should be {EXPECTED_UNCOVERED_RWA:,.0f} "
            f"(300,000 x 1.00), got {row['rwa_final']:,.2f}. "
            f"Pre-fix value ~100,000 means remainder EAD is only 100,000 instead of 300,000."
        )

    # -------------------------------------------------------------------------
    # ATTRIBUTION — guarantor reference on the covered sub-row (non-discriminating).
    # -------------------------------------------------------------------------

    def test_p1_218_covered_sub_row_guarantor_reference(self, sa_results: pl.DataFrame) -> None:
        """
        P1.218: covered sub-row guarantor_reference == CP_GUARANTOR.

        This sub-assertion should pass even before the coverage-basis fix is applied.
        """
        # Arrange
        row = _covered_row(sa_results)

        # Assert
        assert row["guarantor_reference"] == GUARANTOR_REF, (
            f"P1.218: expected guarantor_reference='{GUARANTOR_REF}', "
            f"got '{row['guarantor_reference']}'"
        )

    def test_p1_218_remainder_sub_row_belongs_to_borrower(self, sa_results: pl.DataFrame) -> None:
        """
        P1.218: remainder sub-row has no guarantor (borrower-retained tranche).

        This sub-assertion should pass even before the coverage-basis fix is applied.
        """
        # Arrange
        row = _remainder_row(sa_results)

        # Assert
        assert row["guarantor_reference"] is None, (
            f"P1.218: remainder sub-row should carry a null guarantor_reference "
            f"(borrower-retained), got '{row['guarantor_reference']}'"
        )
        assert row["counterparty_reference"] == BORROWER_REF, (
            f"P1.218: remainder sub-row counterparty_reference should be '{BORROWER_REF}', "
            f"got '{row['counterparty_reference']}'"
        )
