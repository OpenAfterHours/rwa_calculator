"""
P1.227: CRR Art. 201 guarantor-eligibility gate.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SA/IRB Calculators -> Aggregator

Key responsibilities:
- Confirm a genuinely UNRATED corporate guarantor (G1) is REJECTED as an
  eligible protection provider — Art. 201(1)(g) requires an established
  ECAI credit assessment (or, per Art. 201(2), an internal rating WHEN the
  beneficiary exposure is itself IRB-approach) — and the covered exposure
  reverts to the borrower's own basis, with a CRM013 warning raised.
- Confirm an INTERNAL-ONLY-rated corporate guarantor (G4) is REJECTED the
  same way for an SA beneficiary — an internal rating is invisible to the
  SA ECAI lookup, so Art. 201(2)'s IRB-only limb does not admit it.
- Confirm the SAME internal-only guarantor (CP_P227_G34) IS eligible when
  its beneficiary IS IRB-approach (G3) — Art. 201(2)'s limb is beneficiary-
  scoped, not guarantor-scoped, so G3 and G4 diverge purely on which
  approach their respective beneficiaries use.
- Confirm an eligible externally-rated corporate guarantor (G2) is
  UNCHANGED — the gate must not suppress the legitimate case.
- Confirm a retail (individual) guarantor (G5) is OUT OF SCOPE for this
  item's fix — it never substitutes today (a pre-existing null-guard
  neutralises it independently of Art. 201), so no CRM013 fires for it.

Hand-calculation (CRR, CalculationConfig.crr(), PermissionMode.IRB — see
tests/fixtures/p1_227/p1_227.py for the full derivation):

    CP_P227_B baseline (unguaranteed, CQS 5, Art. 122 Table 5):
        RW = 1.50 -> RWA = 1,000,000 x 1.50 = 1,500,000

    G1 (CP_P227_G1, genuinely unrated corporate guarantor):
        pre-fix:  substituted at the unrated-corporate class default,
            RW = 1.00 -> RWA = 1,000,000
        post-fix: guarantee dropped (Art. 201(1)(g)), reverts to borrower
            basis, RW = 1.50 -> RWA = 1,500,000, + CRM013
    G2 (CP_P227_G2, external CQS 2, eligible SA control):
        RW = 0.50 -> RWA = 500,000, both pre- and post-fix
    G3 (CP_P227_G34, internal-only, F-IRB beneficiary CP_P227_B_IRB):
        F-IRB parameter-substitution, pipeline-confirmed: RW = 1.034401
        (rel 1e-6) -> RWA ~= 1,034,401, UNCHANGED pre- and post-fix
        (Art. 201(2) IRB limb is satisfied)
    G4 (CP_P227_G34, SAME internal-only guarantor, SA beneficiary CP_P227_B):
        pre-fix:  substituted at the unrated-corporate class default (the
            SA lookup never reads guarantor_internal_pd),
            RW = 1.00 -> RWA = 1,000,000
        post-fix: guarantee dropped (internal-only insufficient for an SA
            beneficiary), reverts to borrower basis, RW = 1.50 ->
            RWA = 1,500,000, + CRM013
    G5 (CP_P227_G5, retail individual, review-addendum probe):
        RW = 1.50 -> RWA = 1,500,000, both pre- and post-fix — the retail
        substitution never applies (guarantor_rw resolves null for a
        RETAIL_OTHER guarantor class — there are no RETAIL entries in the
        CQS-driven SA risk-weight lookup table at all), so
        ``is_guarantee_beneficial`` (engine/sa/rw_adjustments.py:230-237)
        is already False independent of Art. 201 — NOT gated by this item.

    Portfolio total rwa_final (pipeline-observed, reporting_date=2027-02-01):
        pre-fix:  1,000,000 (G1) + 500,000 (G2) + 1,034,400.6488 (G3)
                 + 1,000,000 (G4) + 1,500,000 (G5) = 5,034,400.6488
        post-fix: 5,034,400.6488 + 500,000 (G1: 1.0M -> 1.5M)
                                 + 500,000 (G4: 1.0M -> 1.5M)
                 = 6,034,400.6488

References:
    - CRR Art. 201(1)(g): corporate guarantors must have an established
      credit assessment by a nominated ECAI.
    - CRR Art. 201(2): internal-rating recognition limited to IRB-approach
      beneficiary exposures.
    - CRR Art. 122 Table 5: CQS 5 -> 150%, CQS 2 -> 50%.
    - tests/fixtures/p1_227/p1_227.py: fixture builder, scenario constants,
      and the full hand-calculation this file's expected values are drawn
      from.
    - tests/acceptance/crr/test_p1_10_art_213_ucp_eligibility.py: the
      sibling Art. 213(1)(c)(i) eligibility gate (CRM012) whose
      ``_prepare_guarantees`` neighbourhood this item's fix (CRM013) shares
      — must stay green (see collateral guards).
    - docs/plans/compliance-audit-crr-111-241-rectification.md (P1.227
      finding).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p1_227.p1_227 import (
    EXPECTED_RW_G3_CRR,
    EXPECTED_RWA_B_BASELINE,
    EXPECTED_RWA_G2,
    EXPECTED_RWA_G3_CRR,
    EXPECTED_RWA_G5_TODAY,
    GUARANTEE_G1_REF,
    GUARANTEE_G4_REF,
    LOAN_G1_REF,
    LOAN_G2_REF,
    LOAN_G3_REF,
    LOAN_G4_REF,
    LOAN_G5_REF,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_227"

# Reporting date: pipeline-derivation-critical for the exact G3 F-IRB
# parameter-substitution pin (residual maturity from this date drives the
# maturity-adjustment factor). 2027-02-01 is comfortably after the ratings'
# rating_date (2027-01-02) and reproduces the accepted design's G3 target
# values (1.034401 CRR / 0.867422 B31) to 6dp — DO NOT change this date
# without re-deriving both G3 pins.
_REPORTING_DATE = date(2027, 2, 1)

# CRM013 does not exist as a named constant yet — the engine-implementer
# adds it to contracts/errors.py (next after P1.10's CRM012). String
# literal, not an import, so this file fails on assertion values only,
# never on a not-yet-defined constant.
_CRM013 = "CRM013"

# Post-fix expected portfolio total: pipeline-observed pre-fix baseline
# (5,034,400.6488, see module docstring) + G1 delta (+500,000)
# + G4 delta (+500,000).
_EXPECTED_TOTAL_RWA_POST_FIX = 6_034_400.648770877


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Build the P1.227 RawDataBundle: counterparty/loan/rating/guarantee/
    model_permission parquets, no facilities (loan-scoped, mirrors
    p1_10/p1_183/p1_225's pattern).
    """
    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        guarantees=pl.scan_parquet(_FIXTURES_DIR / "guarantee.parquet"),
        model_permissions=pl.scan_parquet(_FIXTURES_DIR / "model_permission.parquet"),
    )


def _crr_config() -> CalculationConfig:
    """CRR A-IRB config (PermissionMode.IRB — G3's beneficiary is F-IRB)."""
    return CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )


def _loan_total(df: pl.DataFrame, loan_ref: str) -> dict:
    """
    Sum rwa_final/ead_final across every result row for ``loan_ref``
    (``parent_exposure_reference``), regardless of whether the guarantee
    substitution split the row (eligible guarantee -> ``__G_``/``__REM``
    sub-rows) or collapsed to a single unguaranteed row (ineligible
    guarantee, rejected upstream — no split at all). Robust to both shapes,
    mirroring the P1.10 pattern.
    """
    rows = df.filter(pl.col("parent_exposure_reference") == loan_ref)
    assert rows.height > 0, (
        f"P1.227: expected at least 1 row with parent_exposure_reference="
        f"{loan_ref!r}, got 0. All parent_exposure_references: "
        f"{df['parent_exposure_reference'].unique().to_list()}"
    )
    return {
        "rwa_final": rows["rwa_final"].sum(),
        "ead_final": rows["ead_final"].sum(),
    }


def _crm013_errors(errors: list) -> list:
    """Filter a CalculationError list down to CRM013 (guarantor-eligibility) entries."""
    return [e for e in errors if e.code == _CRM013]


def _references(error, *needles: str) -> bool:
    """True if ``error`` names any of ``needles`` via exposure_reference or message text."""
    if error.exposure_reference in needles:
        return True
    return any(needle in error.message for needle in needles)


# ---------------------------------------------------------------------------
# P1.227 acceptance tests — CRR
# ---------------------------------------------------------------------------


class TestP1227Art201GuarantorEligibilityCRR:
    """P1.227: CRR Art. 201 guarantor-eligibility gate."""

    @pytest.fixture(scope="class")
    def pipeline_results(self) -> AggregatedResultBundle:
        """CRR SA/IRB pipeline results over the full P1.227 fixture set (one run)."""
        bundle = _build_bundle()
        results = PipelineOrchestrator().run_with_data(bundle, _crr_config())
        assert results.results is not None, "results should not be None"
        return results

    @pytest.fixture(scope="class")
    def results(self, pipeline_results: AggregatedResultBundle) -> pl.DataFrame:
        """Collected unified results DataFrame (SA + IRB combined — G3 is F-IRB)."""
        return pipeline_results.results.collect()

    # -------------------------------------------------------------------------
    # Item 1 — G1 ineligible (Art. 201(1)(g)). DISCRIMINATING: FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_227_g1_ineligible_reverts_to_borrower_basis(self, results: pl.DataFrame) -> None:
        """
        P1.227 DISCRIMINATING: G1's genuinely unrated corporate guarantor
        is rejected — the covered exposure reverts to CP_P227_B's own
        150% borrower basis.

        Arrange: LN_P227_G1, 100% guaranteed by CP_P227_G1 (unrated
                 corporate — no rating row of any kind).
        Act:     full CRR pipeline.
        Assert:  total rwa_final == 1,500,000 (borrower basis, CQS-5 150%).

        FAILS today: total rwa_final == 1,000,000 — the guarantee still
        substitutes in at the unrated-corporate class default (100%)
        despite the guarantor having no credit assessment at all.
        """
        totals = _loan_total(results, LOAN_G1_REF)

        assert totals["rwa_final"] == pytest.approx(EXPECTED_RWA_B_BASELINE, rel=1e-4), (
            f"P1.227: expected G1 total rwa_final={EXPECTED_RWA_B_BASELINE:,.0f} "
            f"(unrated guarantor rejected per Art. 201(1)(g) — borrower basis "
            f"150%), got {totals['rwa_final']:,.2f}. Pre-fix value ~1,000,000 "
            f"means the guarantee is still substituted despite the guarantor "
            f"having no credit assessment."
        )

    def test_p1_227_g1_raises_crm013_warning(
        self, pipeline_results: AggregatedResultBundle
    ) -> None:
        """
        P1.227 DISCRIMINATING: a CRM013 warning is raised for G1, naming
        the ineligible guarantee.

        Arrange: LN_P227_G1 / GUAR_P227_G1 (unrated corporate guarantor).
        Act:     full CRR pipeline.
        Assert:  at least one CRM013 warning references LN_P227_G1 or
                 GUAR_P227_G1, WARNING severity.

        FAILS today: no CRM013 code exists yet.
        """
        crm013 = _crm013_errors(pipeline_results.errors)
        g1_errors = [e for e in crm013 if _references(e, LOAN_G1_REF, GUARANTEE_G1_REF)]

        assert g1_errors, (
            f"P1.227: expected at least one CRM013 warning referencing "
            f"{LOAN_G1_REF!r}/{GUARANTEE_G1_REF!r}, got none across "
            f"{len(crm013)} CRM013 warnings. "
            f"All errors: {[(e.code, e.message) for e in pipeline_results.errors]}"
        )
        assert all(e.severity == ErrorSeverity.WARNING for e in g1_errors), (
            f"P1.227: CRM013 should be WARNING severity, got {[e.severity for e in g1_errors]}"
        )

    # -------------------------------------------------------------------------
    # Item 2 — G4 ineligible-for-SA (Art. 201(2) IRB-only). FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_227_g4_ineligible_for_sa_beneficiary_reverts_to_borrower_basis(
        self, results: pl.DataFrame
    ) -> None:
        """
        P1.227 DISCRIMINATING: G4's internal-only guarantor (CP_P227_G34
        — the SAME guarantor as G3) is rejected for an SA beneficiary —
        Art. 201(2)'s internal-rating limb only admits an IRB-approach
        BENEFICIARY, and CP_P227_B (G4's beneficiary) is SA-approach.

        The split between G3 (eligible) and G4 (ineligible) is driven
        entirely by the BENEFICIARY's approach, not the guarantor — both
        loans are guaranteed by the identical CP_P227_G34.

        Arrange: LN_P227_G4, 100% guaranteed by CP_P227_G34 (internal-only
                 rated), beneficiary CP_P227_B (SA-approach).
        Act:     full CRR pipeline.
        Assert:  total rwa_final == 1,500,000 (borrower basis, CQS-5 150%).

        FAILS today: total rwa_final == 1,000,000 — the SA lookup never
        reads guarantor_internal_pd, so the guarantee still substitutes at
        the unrated-corporate class default.
        """
        totals = _loan_total(results, LOAN_G4_REF)

        assert totals["rwa_final"] == pytest.approx(EXPECTED_RWA_B_BASELINE, rel=1e-4), (
            f"P1.227: expected G4 total rwa_final={EXPECTED_RWA_B_BASELINE:,.0f} "
            f"(internal-only guarantor rejected for an SA beneficiary per "
            f"Art. 201(2) — borrower basis 150%), got {totals['rwa_final']:,.2f}. "
            f"Pre-fix value ~1,000,000 means the guarantee is still substituted "
            f"despite the internal-only rating being invisible to the SA ECAI lookup."
        )

    def test_p1_227_g4_raises_crm013_warning(
        self, pipeline_results: AggregatedResultBundle
    ) -> None:
        """
        P1.227 DISCRIMINATING: a CRM013 warning is raised for G4, naming
        the ineligible guarantee.

        Arrange: LN_P227_G4 / GUAR_P227_G4 (internal-only corporate
                 guarantor, SA beneficiary).
        Act:     full CRR pipeline.
        Assert:  at least one CRM013 warning references LN_P227_G4 or
                 GUAR_P227_G4, WARNING severity.

        FAILS today: no CRM013 code exists yet.
        """
        crm013 = _crm013_errors(pipeline_results.errors)
        g4_errors = [e for e in crm013 if _references(e, LOAN_G4_REF, GUARANTEE_G4_REF)]

        assert g4_errors, (
            f"P1.227: expected at least one CRM013 warning referencing "
            f"{LOAN_G4_REF!r}/{GUARANTEE_G4_REF!r}, got none across "
            f"{len(crm013)} CRM013 warnings. "
            f"All errors: {[(e.code, e.message) for e in pipeline_results.errors]}"
        )
        assert all(e.severity == ErrorSeverity.WARNING for e in g4_errors), (
            f"P1.227: CRM013 should be WARNING severity, got {[e.severity for e in g4_errors]}"
        )

    # -------------------------------------------------------------------------
    # Item 3 — G2 eligible control. PASS today, must stay green.
    # -------------------------------------------------------------------------

    def test_p1_227_g2_eligible_control_unchanged(self, results: pl.DataFrame) -> None:
        """
        P1.227: G2 (externally-rated CQS-2 corporate guarantor) is
        unaffected by the eligibility gate — the gate must let a
        legitimate ECAI-rated guarantor through unmodified.

        Arrange: LN_P227_G2, 100% guaranteed by CP_P227_G2 (external CQS 2).
        Act:     full CRR pipeline.
        Assert:  total rwa_final == 500,000 (CQS-2 50% substitution).

        Should PASS today and MUST still pass after.
        """
        totals = _loan_total(results, LOAN_G2_REF)

        assert totals["rwa_final"] == pytest.approx(EXPECTED_RWA_G2, rel=1e-4), (
            f"P1.227: expected G2 total rwa_final={EXPECTED_RWA_G2:,.0f} "
            f"(eligible external-CQS-2 guarantor, 50% substitution), "
            f"got {totals['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 4 — G3 eligible-for-IRB control (Art. 201(2)). PASS today, must stay.
    # -------------------------------------------------------------------------

    def test_p1_227_g3_irb_beneficiary_control_unchanged(self, results: pl.DataFrame) -> None:
        """
        P1.227: G3 (the SAME internal-only CP_P227_G34 guarantor as G4,
        but with an F-IRB beneficiary) is unaffected — Art. 201(2)'s
        internal-rating limb admits it because its beneficiary
        (CP_P227_B_IRB) IS IRB-approach.

        Pinned TIGHT (rel=1e-6): the full F-IRB parameter-substitution
        formula (correlation / maturity-adjustment / K), not a flat
        CQS-table lookup — must not move at all, since this is the exact
        control that proves the gate is beneficiary-scoped, not a blanket
        "reject all internal-only guarantors" rule.

        Arrange: LN_P227_G3, 100% guaranteed by CP_P227_G34 (internal-only
                 rated), beneficiary CP_P227_B_IRB (F-IRB approach).
        Act:     full CRR pipeline.
        Assert:  blended risk weight (total rwa_final / total ead_final)
                 == 1.034401 (rel=1e-6).

        Should PASS today and MUST still pass after — the internal-rating
        limb must keep working for its genuinely-eligible IRB beneficiary.
        """
        totals = _loan_total(results, LOAN_G3_REF)
        blended_rw = totals["rwa_final"] / totals["ead_final"]

        assert blended_rw == pytest.approx(EXPECTED_RW_G3_CRR, rel=1e-6), (
            f"P1.227: expected G3 blended risk weight={EXPECTED_RW_G3_CRR:.6f} "
            f"(F-IRB parameter substitution, Art. 201(2) IRB limb — must not "
            f"move at all), got {blended_rw:.6f}"
        )
        assert totals["rwa_final"] == pytest.approx(EXPECTED_RWA_G3_CRR, rel=1e-6), (
            f"P1.227: expected G3 total rwa_final={EXPECTED_RWA_G3_CRR:,.4f}, "
            f"got {totals['rwa_final']:,.4f}"
        )

    # -------------------------------------------------------------------------
    # Item 5 — G5 retail-guarantor invariant + CRM013 scope control.
    # -------------------------------------------------------------------------

    def test_p1_227_g5_retail_guarantor_no_substitution_invariant(
        self, results: pl.DataFrame
    ) -> None:
        """
        P1.227: G5 (retail individual guarantor) never substitutes, both
        pre- and post-fix — the retail class has no entries in the
        CQS-driven SA risk-weight lookup table at all, so the pre-existing
        ``is_guarantee_beneficial`` null-guard (engine/sa/rw_adjustments.py:
        230-237) already reverts this exposure to the borrower's own basis,
        independent of Art. 201. G5 is OUT OF SCOPE for this item's fix
        (Art. 201(1) does not list retail persons as eligible protection
        providers at all — a possible separate plan item, not this one).

        Arrange: LN_P227_G5, 100% guaranteed by CP_P227_G5 (unrated
                 individual).
        Act:     full CRR pipeline.
        Assert:  total rwa_final == 1,500,000 (== the borrower's own
                 unguaranteed basis — identical to "no substitution").

        Should PASS today and MUST still pass after (this item does not
        touch the retail path at all).
        """
        totals = _loan_total(results, LOAN_G5_REF)

        assert totals["rwa_final"] == pytest.approx(EXPECTED_RWA_G5_TODAY, rel=1e-4), (
            f"P1.227: expected G5 total rwa_final={EXPECTED_RWA_G5_TODAY:,.0f} "
            f"(retail guarantor never substitutes — pre-existing null-guard, "
            f"not gated by this item), got {totals['rwa_final']:,.2f}"
        )

    def test_p1_227_crm013_count_over_whole_book_is_exactly_two(
        self, pipeline_results: AggregatedResultBundle
    ) -> None:
        """
        P1.227 DISCRIMINATING: exactly two CRM013 warnings are raised
        across the whole five-guarantee book — one for G1, one for G4.
        G5 (the retail guarantor) does NOT get a CRM013 — the accepted
        design gates only the CORPORATE limb (Art. 201(1)(g)/(2) are
        corporate-guarantor provisions); the retail leg is already
        neutralised by the null-guard above, so CRM013 firing for it too
        would be double-signalling the same accidental safety net, not a
        genuine Art. 201 violation this item is scoped to catch.

        Arrange: all five P1.227 guarantees in one pipeline run.
        Act:     full CRR pipeline.
        Assert:  len(CRM013 warnings) == 2 (G1 + G4 only).

        FAILS today: zero CRM013 warnings exist (no code, no validation).
        """
        crm013 = _crm013_errors(pipeline_results.errors)

        assert len(crm013) == 2, (
            f"P1.227: expected exactly 2 CRM013 warnings (G1 + G4 — the "
            f"corporate-guarantor eligibility failures; G5's retail "
            f"guarantor is out of scope for this item), got {len(crm013)}. "
            f"All errors: {[(e.code, e.message) for e in pipeline_results.errors]}"
        )

    # -------------------------------------------------------------------------
    # Item 6 — portfolio total. DISCRIMINATING: FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_227_portfolio_total_rwa_reflects_gated_guarantees(
        self, results: pl.DataFrame
    ) -> None:
        """
        P1.227 DISCRIMINATING: portfolio total rwa_final reflects BOTH the
        G1 and G4 reversion deltas simultaneously.

        Derivation: pipeline-observed pre-fix baseline
            1,000,000 (G1) + 500,000 (G2) + 1,034,400.6488 (G3)
            + 1,000,000 (G4) + 1,500,000 (G5) = 5,034,400.6488
        Post-fix: 5,034,400.6488 + 500,000 (G1: 1.0M -> 1.5M)
                                 + 500,000 (G4: 1.0M -> 1.5M)
                = 6,034,400.6488

        Arrange: all five P1.227 loans in one pipeline run.
        Act:     full CRR pipeline; sum rwa_final across all rows.
        Assert:  total rwa_final == 6,034,400.6488.

        FAILS today: total is 5,034,400.6488 (G1/G4 still substituted).
        This is a redundant cross-check against the individual G1/G4 tests
        above — it also catches a fix that gets G1/G4 individually right
        but accidentally perturbs G2/G3/G5.
        """
        total_rwa = results["rwa_final"].sum()

        assert total_rwa == pytest.approx(_EXPECTED_TOTAL_RWA_POST_FIX, rel=1e-6), (
            f"P1.227: expected portfolio total rwa_final="
            f"{_EXPECTED_TOTAL_RWA_POST_FIX:,.4f} (pre-fix baseline "
            f"5,034,400.6488 + G1 delta 500,000 + G4 delta 500,000), "
            f"got {total_rwa:,.4f}"
        )
