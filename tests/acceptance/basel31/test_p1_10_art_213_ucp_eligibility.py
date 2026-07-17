"""
P1.10: PS1/26 Art. 213(1)(c)(i) unfunded credit protection (UCP) eligibility
gate — unilateral-cancellation / unilateral-change flags (Basel 3.1 twin).

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Confirm that a guarantee flagged ``is_unilaterally_cancellable=True`` is
  rejected as ineligible unfunded credit protection under PS1/26
  Art. 213(1)(c)(i) (same as the CRR sibling).
- Confirm the "unilateral change" arm of Art. 213(1)(c)(i) IS gated under
  Basel 3.1 (P1.143 scoping — the pack Feature
  ``ucp_unilateral_change_ineligible`` is on for B31): a guarantee flagged
  ``is_unilaterally_changeable=True`` alone is ineligible under B31, unlike
  under CRR (see the CRR sibling's B row).
- Confirm both flags null (the permissive default) leaves the guarantee
  eligible.

One combined pipeline run over all three P1.10 scenarios (BASE/A/B) so a
regression that leaks the new gate across rows shows up as an unexpected
RWA/CRM012 change on the BASE row.

Defect under test (pre-fix):
    Same as the CRR sibling
    (tests/acceptance/crr/test_p1_10_art_213_ucp_eligibility.py) —
    ``_prepare_guarantees`` does not gate on Art. 213(1)(c)(i) at all yet,
    and the two flag columns are silently dropped by the loader's lenient
    seal because they are not yet on GUARANTEE_SCHEMA.

Hand-calculation (CalculationConfig.basel_3_1() — see
tests/fixtures/p1_10/p1_10.py for the full derivation; the borrower/guarantor
risk weights are identical to CRR for this fixture, only the B scenario's
eligibility outcome diverges):
    Loan EAD = 1,000,000 GBP

    BASE (both flags null -> eligible):
        RW = CP_GUARANTOR_P110 sovereign CQS 2 = 20%
        RWA = 1,000,000 x 0.20 = 200,000

    A (is_unilaterally_cancellable=True -> ineligible):
        RW = CP_BORROWER_P110 unrated corporate fallback = 100%
        RWA = 1,000,000 x 1.00 = 1,000,000

    B (is_unilaterally_cancellable=False, is_unilaterally_changeable=True):
        B31: the "change" arm IS gated (pack Feature
             ``ucp_unilateral_change_ineligible`` on for B31) -> guarantee
             INELIGIBLE -> RW = 100% -> RWA = 1,000,000, plus a CRM012
             warning.
        (CRR sibling: tests/acceptance/crr/test_p1_10_art_213_ucp_eligibility.py
         — B stays ELIGIBLE under CRR, RWA = 200,000, no CRM012.)

References:
    - PS1/26, PRA Rulebook Art. 213(1)(c)(i): CRR-equivalent restatement;
      additionally gates the unilateral-change arm.
    - CRR Art. 114 Table 1 / PS1/26 equivalent: sovereign CQS-to-RW mapping
      (CQS 2 = 20%, identical under both regimes for this band).
    - CRR Art. 122 / PS1/26 equivalent: unrated corporate SA fallback = 100%.
    - tests/fixtures/p1_10/p1_10.py: fixture builder, scenario constants, and
      the full hand-calculation this file's expected values are drawn from.
    - docs/plans/compliance-audit-crr-111-241-rectification.md:596
      (art213-eligibility-conditions-unvalidated finding).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import FACILITY_MAPPING_SCHEMA, LENDING_MAPPING_SCHEMA
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.crr.conftest import aggregate_sa_rows_by_parent
from tests.fixtures.p1_10.p1_10 import (
    EXPECTED_RWA_ELIGIBLE,
    EXPECTED_RWA_INELIGIBLE,
    LOAN_A_REF,
    LOAN_B_REF,
    LOAN_BASE_REF,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_10"

# Same reporting date as the CRR sibling — the fixture's flag semantics don't
# depend on regime-effective-date arithmetic here, only which pack Feature is
# switched on (ucp_unilateral_change_ineligible: CRR off / B31 on).
_REPORTING_DATE = date(2026, 6, 1)

# CRM012 does not exist as a named constant yet — see the CRR sibling for the
# same reasoning (string literal, not an import).
_CRM012 = "CRM012"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """Same P1.10 bundle as the CRR sibling — all three scenarios (BASE/A/B)."""
    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        guarantees=pl.scan_parquet(_FIXTURES_DIR / "guarantee.parquet"),
    )


def _basel_31_config() -> CalculationConfig:
    """Basel 3.1 SA-only config, same reporting_date as the CRR sibling."""
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


def _crm012_errors(errors: list) -> list:
    """Filter a CalculationError list down to CRM012 (UCP ineligibility) entries."""
    return [e for e in errors if e.code == _CRM012]


# ---------------------------------------------------------------------------
# P1.10 acceptance tests — Basel 3.1
# ---------------------------------------------------------------------------


class TestP110Art213UCPEligibilityB31:
    """
    P1.10: PS1/26 Art. 213(1)(c)(i) UCP unilateral-cancellation / -change gate.

    One class-scoped pipeline run over all three scenarios (BASE/A/B) under
    ``CalculationConfig.basel_3_1()``.
    """

    @pytest.fixture(scope="class")
    def pipeline_results(self) -> AggregatedResultBundle:
        """B31 SA pipeline results over the full P1.10 fixture set (one run)."""
        bundle = _build_bundle()
        results = PipelineOrchestrator().run_with_data(bundle, _basel_31_config())
        assert results.sa_results is not None, (
            "SA results should not be None — check PermissionMode.STANDARDISED config"
        )
        return results

    @pytest.fixture(scope="class")
    def sa_results(self, pipeline_results: AggregatedResultBundle) -> pl.DataFrame:
        """Collected SA results DataFrame (all sub-rows across BASE/A/B)."""
        assert pipeline_results.sa_results is not None
        return pipeline_results.sa_results.collect()

    # -------------------------------------------------------------------------
    # Item 1 — BASE control (flags null): should PASS today.
    # -------------------------------------------------------------------------

    def test_p1_10_base_control_flags_null_eligible_rwa_is_200k(
        self, sa_results: pl.DataFrame
    ) -> None:
        """
        P1.10 BASE (control): both flags null -> guarantee stays eligible under B31.

        Arrange: LOAN_P110_BASE + GUAR_P110_BASE (both flags null).
        Act:     full B31 SA pipeline.
        Assert:  aggregated rwa_final == 200,000 (guarantor CQS 2, 20% RW).

        Should PASS today and must still pass after — null is "no known
        defect", not a defect, under either regime.
        """
        row = aggregate_sa_rows_by_parent(sa_results, LOAN_BASE_REF)

        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_ELIGIBLE, abs=1.0), (
            f"P1.10 BASE (B31): expected rwa_final={EXPECTED_RWA_ELIGIBLE:,.0f} "
            f"(both eligibility flags null -> guarantee eligible -> guarantor "
            f"CQS 2, 20% RW), got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 2 — P1.10-A (is_unilaterally_cancellable=True): FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_10_a_cancellable_true_ineligible_rwa_is_1m(self, sa_results: pl.DataFrame) -> None:
        """
        P1.10-A DISCRIMINATING: is_unilaterally_cancellable=True -> ineligible under B31.

        Arrange: LOAN_P110_A + GUAR_P110_A (is_unilaterally_cancellable=True).
        Act:     full B31 SA pipeline.
        Assert:  aggregated rwa_final == 1,000,000 (borrower unrated
                 corporate 100% RW, guarantee substitution REJECTED).

        FAILS today: the gate does not exist yet, so the engine still
        substitutes the guarantor's 20% RW, returning 200,000.
        """
        row = aggregate_sa_rows_by_parent(sa_results, LOAN_A_REF)

        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_INELIGIBLE, abs=1.0), (
            f"P1.10-A (B31): expected rwa_final={EXPECTED_RWA_INELIGIBLE:,.0f} "
            f"(is_unilaterally_cancellable=True -> Art. 213(1)(c)(i) ineligible "
            f"-> full borrower RW 100%), got {row['rwa_final']:,.2f}. Pre-fix "
            f"value ~200,000 means the guarantee is still substituted despite "
            f"being unilaterally cancellable."
        )

    def test_p1_10_a_cancellable_true_raises_crm012_warning(
        self, pipeline_results: AggregatedResultBundle
    ) -> None:
        """
        P1.10-A DISCRIMINATING: CRM012 (UCP ineligibility) warning is raised under B31.

        Arrange: LOAN_P110_A + GUAR_P110_A (is_unilaterally_cancellable=True).
        Act:     full B31 SA pipeline.
        Assert:  at least one CRM012 warning attributable to GUAR_P110_A is
                 present (the exact total count, including B's own CRM012
                 under B31, is pinned separately below).

        FAILS today: no CRM012 code exists yet.
        """
        crm012 = _crm012_errors(pipeline_results.errors)

        assert len(crm012) >= 1, (
            f"P1.10-A (B31): expected at least 1 CRM012 warning "
            f"(GUAR_P110_A is unilaterally cancellable), got {len(crm012)}. "
            f"All errors: {[(e.code, e.message) for e in pipeline_results.errors]}"
        )
        assert all(e.severity == ErrorSeverity.WARNING for e in crm012), (
            f"P1.10-A (B31): all CRM012 entries should be WARNING severity, "
            f"got {[e.severity for e in crm012]}"
        )

    # -------------------------------------------------------------------------
    # Item 3 — P1.10-B (changeable-only): B31 regime-split control. FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_10_b_changeable_only_ineligible_under_b31_rwa_is_1m(
        self, sa_results: pl.DataFrame
    ) -> None:
        """
        P1.10-B DISCRIMINATING: is_unilaterally_changeable=True IS gated under B31.

        Arrange: LOAN_P110_B + GUAR_P110_B (is_unilaterally_cancellable=False,
                 is_unilaterally_changeable=True).
        Act:     full B31 SA pipeline.
        Assert:  aggregated rwa_final == 1,000,000 (guarantee INELIGIBLE —
                 pack Feature ``ucp_unilateral_change_ineligible`` is on for
                 B31, unlike CRR).

        This is the regime-split control's B31 side (the CRR sibling asserts
        the opposite outcome for the same fixture row). FAILS today: the
        engine does not gate on anything yet, so this returns 200,000 instead
        of 1,000,000.
        """
        row = aggregate_sa_rows_by_parent(sa_results, LOAN_B_REF)

        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_INELIGIBLE, abs=1.0), (
            f"P1.10-B (B31): expected rwa_final={EXPECTED_RWA_INELIGIBLE:,.0f} "
            f"(is_unilaterally_changeable=True IS gated under B31 -> full "
            f"borrower RW 100%), got {row['rwa_final']:,.2f}. Pre-fix value "
            f"~200,000 means the change-only arm is not gated yet."
        )

    def test_p1_10_b_changeable_only_raises_crm012_under_b31(
        self, pipeline_results: AggregatedResultBundle
    ) -> None:
        """
        P1.10-B DISCRIMINATING: CRM012 warning is raised for the B31 change-only arm.

        Arrange: LOAN_P110_B + GUAR_P110_B (is_unilaterally_changeable=True).
        Act:     full B31 SA pipeline.
        Assert:  exactly two CRM012 warnings total in this run (A's
                 cancellable arm + B's change arm — BASE contributes none).

        FAILS today: no CRM012 code exists yet, so this count is 0.
        """
        crm012 = _crm012_errors(pipeline_results.errors)

        assert len(crm012) == 2, (
            f"P1.10 (B31): expected exactly 2 CRM012 warnings across BASE+A+B "
            f"(A: cancellable arm, B: change arm — BASE's null flags must not "
            f"trigger the gate), got {len(crm012)}. "
            f"All errors: {[(e.code, e.message) for e in pipeline_results.errors]}"
        )
