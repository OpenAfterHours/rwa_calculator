"""
P1.10: CRR Art. 213(1)(c)(i) unfunded credit protection (UCP) eligibility gate —
unilateral-cancellation / unilateral-change flags.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Confirm that a guarantee flagged ``is_unilaterally_cancellable=True`` is
  rejected as ineligible unfunded credit protection under CRR Art. 213(1)(c)(i)
  and that a CRM012 warning is raised.
- Confirm the "unilateral change" arm of Art. 213(1)(c)(i) is B31-only (per
  P1.143 scoping): under CRR, ``is_unilaterally_changeable=True`` alone does
  NOT gate the guarantee.
- Confirm both flags null (the permissive default, mirroring every
  pre-existing guarantee row in the fixture estate) leaves the guarantee
  eligible.

One combined pipeline run over all three P1.10 scenarios (BASE/A/B) so a
regression that leaks the new gate across rows (e.g. a portfolio-wide check
instead of a per-guarantee-row one) shows up as an unexpected RWA/CRM012
change on the BASE or B rows, not just a missed change on A.

Defect under test (pre-fix):
    ``_prepare_guarantees`` (engine/crm/guarantees.py) does not gate on
    Art. 213(1)(c)(i) at all — a unilaterally-cancellable guarantee is still
    substituted, overstating the credit risk mitigation benefit. The two flag
    columns are also not yet on GUARANTEE_SCHEMA, so today they are silently
    dropped by the loader's lenient seal before the CRM stage ever sees them
    (see tests/fixtures/p1_10/p1_10.py "Schema dependency").

Hand-calculation (CalculationConfig.crr(), CalculationConfig.basel_3_1() — both
identical for this fixture, see tests/fixtures/p1_10/p1_10.py for the full
derivation):
    Loan EAD = 1,000,000 GBP (drawn_amount=1,000,000, interest=0)

    BASE (both flags null -> eligible, both regimes):
        RW = CP_GUARANTOR_P110 sovereign CQS 2 = 20% (CRR Art. 114 Table 1)
        RWA = 1,000,000 x 0.20 = 200,000

    A (is_unilaterally_cancellable=True -> ineligible, both regimes):
        RW = CP_BORROWER_P110 unrated corporate fallback = 100% (CRR Art. 122)
        RWA = 1,000,000 x 1.00 = 1,000,000

    B (is_unilaterally_cancellable=False, is_unilaterally_changeable=True):
        CRR:  the "change" arm is B31-only (P1.143 scoping) -> guarantee stays
              ELIGIBLE -> RW = 20% -> RWA = 200,000, no CRM012.
        (B31 sibling: tests/acceptance/basel31/test_p1_10_art_213_ucp_eligibility.py)

References:
    - CRR Art. 213(1)(c)(i): unfunded credit protection eligibility — the
      protection must derive from an undertaking that cannot be unilaterally
      cancelled by the protection provider, or that unilaterally increases the
      effective cost of protection after the credit protection agreement was
      entered into.
    - CRR Art. 114 Table 1: sovereign CQS-to-RW mapping (CQS 2 = 20%).
    - CRR Art. 122: unrated corporate SA fallback = 100%.
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
from tests.acceptance.crr.conftest import aggregate_sa_rows_by_parent
from tests.fixtures.p1_10.p1_10 import (
    EXPECTED_RWA_ELIGIBLE,
    EXPECTED_RWA_INELIGIBLE,
    LOAN_A_REF,
    LOAN_B_REF,
    LOAN_BASE_REF,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import FACILITY_MAPPING_SCHEMA, LENDING_MAPPING_SCHEMA
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_10"

# Reporting date: after the guarantor's rating_date (2026-01-02) and the loan
# value_date (2026-01-01), comfortably before the loan/guarantee maturity
# (2029-01-01) — no Art. 233/239(3) maturity-mismatch scaling to disentangle
# from the eligibility gate itself. Matches the P1.124 sibling's convention.
_REPORTING_DATE = date(2026, 6, 1)

# CRM012 does not exist as a named constant yet — the engine-implementer adds
# it to contracts/errors.py. Use the string literal per the wave instruction,
# not an import, so this test fails on ImportError only if the module itself
# is broken, never on a not-yet-defined constant.
_CRM012 = "CRM012"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle carrying all three P1.10 scenarios (BASE/A/B)
    in one bundle, so a single pipeline run exercises the eligibility gate
    across all three guarantee rows simultaneously.

    Facilities/facility_mappings/lending_mappings are empty — P1.10 has no
    facility hierarchy (loan-level guarantees only).
    """
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


def _crr_config() -> CalculationConfig:
    """CRR SA-only config, reporting_date matching the fixture's value_date."""
    return CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


def _crm012_errors(errors: list) -> list:
    """Filter a CalculationError list down to CRM012 (UCP ineligibility) entries."""
    return [e for e in errors if e.code == _CRM012]


# ---------------------------------------------------------------------------
# P1.10 acceptance tests — CRR
# ---------------------------------------------------------------------------


class TestP110Art213UCPEligibilityCRR:
    """
    P1.10: CRR Art. 213(1)(c)(i) UCP unilateral-cancellation / -change gate.

    One class-scoped pipeline run over all three scenarios (BASE/A/B) under
    ``CalculationConfig.crr()``.
    """

    @pytest.fixture(scope="class")
    def pipeline_results(self) -> AggregatedResultBundle:
        """CRR SA pipeline results over the full P1.10 fixture set (one run)."""
        bundle = _build_bundle()
        results = PipelineOrchestrator().run_with_data(bundle, _crr_config())
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
        P1.10 BASE (control): both flags null -> guarantee stays eligible.

        Arrange: LOAN_P110_BASE + GUAR_P110_BASE (is_unilaterally_cancellable
                 and is_unilaterally_changeable both null).
        Act:     full CRR SA pipeline.
        Assert:  aggregated rwa_final == 200,000 (guarantor CQS 2, 20% RW).

        This proves the fixture and the permissive null default — it should
        PASS today, before the engine-implementer adds the gate, and must
        still pass after (null is "no known defect", not a defect).
        """
        row = aggregate_sa_rows_by_parent(sa_results, LOAN_BASE_REF)

        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_ELIGIBLE, abs=1.0), (
            f"P1.10 BASE: expected rwa_final={EXPECTED_RWA_ELIGIBLE:,.0f} "
            f"(both eligibility flags null -> guarantee eligible -> guarantor "
            f"CQS 2, 20% RW), got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 2 — P1.10-A (is_unilaterally_cancellable=True): FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_10_a_cancellable_true_ineligible_rwa_is_1m(self, sa_results: pl.DataFrame) -> None:
        """
        P1.10-A DISCRIMINATING: is_unilaterally_cancellable=True -> ineligible.

        Arrange: LOAN_P110_A + GUAR_P110_A (is_unilaterally_cancellable=True).
        Act:     full CRR SA pipeline.
        Assert:  aggregated rwa_final == 1,000,000 (borrower unrated
                 corporate 100% RW, guarantee substitution REJECTED per
                 Art. 213(1)(c)(i)).

        FAILS today: the gate does not exist yet (and the flag column is
        silently dropped by the loader), so the engine still substitutes the
        guarantor's 20% RW, returning 200,000.
        """
        row = aggregate_sa_rows_by_parent(sa_results, LOAN_A_REF)

        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_INELIGIBLE, abs=1.0), (
            f"P1.10-A: expected rwa_final={EXPECTED_RWA_INELIGIBLE:,.0f} "
            f"(is_unilaterally_cancellable=True -> Art. 213(1)(c)(i) ineligible "
            f"-> full borrower RW 100%), got {row['rwa_final']:,.2f}. Pre-fix "
            f"value ~200,000 means the guarantee is still substituted despite "
            f"being unilaterally cancellable."
        )

    def test_p1_10_a_cancellable_true_raises_crm012_warning(
        self, pipeline_results: AggregatedResultBundle
    ) -> None:
        """
        P1.10-A DISCRIMINATING: CRM012 (UCP ineligibility) warning is raised.

        Arrange: LOAN_P110_A + GUAR_P110_A (is_unilaterally_cancellable=True);
                 BASE and B (CRR) both stay eligible in the same run.
        Act:     full CRR SA pipeline.
        Assert:  exactly one CRM012 warning in result.errors (attributable to
                 GUAR_P110_A alone — the exact count, not merely >=1, is the
                 control that BASE/B did not also trigger the gate).

        FAILS today: no CRM012 code exists yet, so result.errors carries zero
        matches.
        """
        crm012 = _crm012_errors(pipeline_results.errors)

        assert len(crm012) == 1, (
            f"P1.10-A: expected exactly 1 CRM012 warning (GUAR_P110_A only — "
            f"BASE and B stay eligible under CRR), got {len(crm012)}. "
            f"All errors: {[(e.code, e.message) for e in pipeline_results.errors]}"
        )
        assert crm012[0].severity == ErrorSeverity.WARNING, (
            f"P1.10-A: CRM012 should be WARNING severity, got {crm012[0].severity}"
        )

    # -------------------------------------------------------------------------
    # Item 3 — P1.10-B (changeable-only): CRR regime-split control.
    # -------------------------------------------------------------------------

    def test_p1_10_b_changeable_only_stays_eligible_under_crr(
        self, sa_results: pl.DataFrame
    ) -> None:
        """
        P1.10-B: is_unilaterally_changeable=True alone does NOT gate under CRR.

        Arrange: LOAN_P110_B + GUAR_P110_B (is_unilaterally_cancellable=False,
                 is_unilaterally_changeable=True).
        Act:     full CRR SA pipeline.
        Assert:  aggregated rwa_final == 200,000 (guarantee stays ELIGIBLE —
                 the "unilateral change" arm of Art. 213(1)(c)(i) is B31-only
                 per P1.143 scoping; CRR does not gate on it).

        This is the regime-split control: it should PASS today (the engine
        does not gate on anything yet) and MUST still pass after the fix
        (CRR must not gate on the change-only arm).
        """
        row = aggregate_sa_rows_by_parent(sa_results, LOAN_B_REF)

        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_ELIGIBLE, abs=1.0), (
            f"P1.10-B (CRR): expected rwa_final={EXPECTED_RWA_ELIGIBLE:,.0f} "
            f"(is_unilaterally_changeable=True alone does not gate under CRR), "
            f"got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 4 — cross-scenario control: exactly one CRM012, never on BASE/B.
    # -------------------------------------------------------------------------

    def test_p1_10_only_one_crm012_warning_across_all_crr_scenarios(
        self, pipeline_results: AggregatedResultBundle
    ) -> None:
        """
        P1.10 control: exactly one CRM012 across the whole combined run under CRR.

        Arrange: BASE (flags null) + A (cancellable=True) + B
                 (changeable=True only) all in the same pipeline run.
        Act:     full CRR SA pipeline.
        Assert:  total CRM012 count == 1 (A alone). If BASE's null flags or
                 B's changeable-only flag were misread as ineligible — e.g. a
                 gate that checks "any row in the guarantee table" instead of
                 the current row — this count would be 2 or 3 instead.

        FAILS today for the same reason as test_p1_10_a_cancellable_true_raises_crm012_warning
        (no CRM012 exists yet); kept as a separate node so a future
        over-broad gate implementation (right code, wrong scope) is caught
        even if the row-level RWA test above happens to still pass.
        """
        crm012 = _crm012_errors(pipeline_results.errors)

        assert len(crm012) == 1, (
            f"P1.10: expected exactly 1 CRM012 warning across BASE+A+B under "
            f"CRR (A only — BASE's null flags and B's changeable-only flag "
            f"must not trigger the gate), got {len(crm012)}."
        )
