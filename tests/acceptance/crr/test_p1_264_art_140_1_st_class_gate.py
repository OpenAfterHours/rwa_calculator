"""
P1.264: CRR Art. 140(1) short-term-override obligor-class gate.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Confirm a short-term (ST) issue-specific ECAI rating mis-scoped onto a
  SOVEREIGN loan (S1) is REJECTED — Art. 140(1) confines ST assessments to
  institution/corporate obligors — and the row's ``cqs`` / risk weight
  revert to the sovereign's own long-term rating, with a DQ warning raised.
- Confirm the same mis-scope pattern on an UNRATED sovereign (S2A) is
  rejected the same way, AND that rejecting it upstream also kills the
  P1.225 Art. 140(2) obligor-level contamination it was spuriously
  triggering onto its unrelated, unsecured, long-term sibling exposure
  (S2B) — the "observable-leak" scenario this fixture's second obligor
  isolates.
- Confirm correctly-scoped institution (I1) and corporate (C1) ST
  overrides are UNCHANGED — the class gate must not suppress the
  legitimate case.
- Confirm a NULL entity_type obligor (N1, the reviewer-found Kleene-null
  path — ``entity_type`` falls through every ``fill_null("")`` guard to
  exposure_class "other") also has its mis-scoped override rejected, and
  that the DQ009 warning is the ONLY observable effect (the "other" class
  never reads the ECRA/SCRA short-term tables at all, so risk_weight is
  invariant regardless of the fix).
- Confirm exactly THREE DQ009 warnings are raised (one per mis-scoped
  rating: S1, S2A, N1), never referencing the legitimate I1/C1 rows.

Hand-calculation (CRR, CalculationConfig.crr(), Table 7 CQS-to-RW — see
tests/fixtures/p1_264/p1_264.py for the full derivation):

    S1 (CP_P264_SOV, mis-scoped ST-CQS3 on a sovereign):
        pre-fix:  cqs=3 (corrupted), has_short_term_ecai=True, RW=0.00
            (sovereign RW reads cp_sovereign_cqs, not cqs — RWA-inert but
            still data-corrupt: the wrong CQS value sits on the row)
        post-fix: cqs reverts to 1 (the counterparty's own CQS-1 long-term
            rating), has_short_term_ecai=False, RW stays 0.00 (invariant)
    S2A (CP_P264_SOV2, mis-scoped ST-CQS4 on an UNRATED sovereign):
        pre-fix:  cqs=4 (corrupted), has_short_term_ecai=True, RW=1.00
        post-fix: cqs reverts to null (genuinely unrated), has_short_term_
            ecai=False, RW stays 1.00 (invariant — CQS4 happens to coincide
            with the UNRATED CQS-table entry)
    S2B (CP_P264_SOV2, unrated long-term unsecured sibling of S2A):
        pre-fix:  RW=1.50, RWA=1,500,000 — the P1.225 Art. 140(2)(a) 150%
            broadcast fires off S2A's corrupted has_short_term_ecai/cqs=4
            with no class gate upstream to stop it
        post-fix: RW=1.00, RWA=1,000,000 — S2A's override is rejected, so
            the obligor_st_150_contamination flag never sets for
            CP_P264_SOV2, and S2B reverts to the plain unrated-sovereign
            baseline (Art. 140(1) gate kills the trigger BEFORE it ever
            reaches Art. 140(2))
    I1 (CP_P264_INST, correctly-scoped ST-CQS2 institution): RW=0.50,
        RWA=500,000 — both pre- and post-fix
    C1 (CP_P264_CORP, correctly-scoped ST-CQS2 corporate): RW=0.50,
        RWA=500,000 — both pre- and post-fix
    N1 (CP_P264_NULLTYPE, entity_type=NULL, mis-scoped ST-CQS3): RW=1.00
        (exposure_class "other" — falls through every ENTITY_TYPE_TO_SA_CLASS
        entry to the class-default fallback), both pre- AND post-fix — the
        "other" class is not on the ECRA/SCRA short-term Table 7 / Table
        4A-6A class list at all, so the mis-scoped override was always
        RWA-inert here. Only ``has_short_term_ecai``/``cqs`` and the DQ009
        warning move.

    Portfolio total rwa_final (pipeline-observed, both regimes):
        pre-fix:  500,000 (C1) + 500,000 (I1) + 0 (S1) + 1,000,000 (S2A)
                 + 1,500,000 (S2B) + 1,000,000 (N1) = 4,500,000
        post-fix: 4,500,000 - 500,000 (S2B: 1,500,000 -> 1,000,000)
                 = 4,000,000 (everything else RWA-stable, including N1 —
                 its 1,000,000 "other"-class RWA never moves)

References:
    - CRR Art. 140(1) (CRE21.16): short-term credit assessments confined to
      institution/corporate obligors.
    - CRR Art. 114 Table 1: sovereign CQS-to-RW mapping (CQS 1 = 0%).
    - CRR Art. 131 Table 7: short-term credit assessment risk weights.
    - tests/fixtures/p1_264/p1_264.py: fixture builder, scenario constants,
      and the full hand-calculation this file's expected values are drawn
      from.
    - tests/fixtures/p1_225/p1_225.py: the Art. 140(2) obligor-level
      contamination fixture whose machinery this fixture's S2A/S2B pair
      exercises (already landed) — must stay green (see collateral guards).
    - docs/plans/compliance-audit-crr-111-241-rectification.md:129-133
      (P1.264 finding).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p1_264.p1_264 import (
    EXPECTED_RW_C1,
    EXPECTED_RW_I1,
    EXPECTED_RW_NULLTYPE_BASELINE,
    EXPECTED_RW_SOV2_UNRATED_BASELINE,
    EXPECTED_RW_SOV_BASELINE,
    EXPECTED_RWA_C1,
    EXPECTED_RWA_I1,
    EXPECTED_RWA_SOV2_UNRATED_BASELINE,
    EXPECTED_RWA_SOV_POST_FIX,
    LOAN_C1_REF,
    LOAN_I1_REF,
    LOAN_N1_REF,
    LOAN_S1_REF,
    LOAN_S2A_REF,
    LOAN_S2B_REF,
    RATING_N1_MISSCOPED_REF,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_264"

# Reporting date: mirrors p1_225's convention — ~30 days after value_date
# (2027-01-01), comfortably after the ratings' rating_date (2027-01-02).
# Residual to the ST maturity (2027-03-15) is 43 days ~= 0.118y, well
# within the 0.25y ST window; residual to the long-term maturity
# (2030-01-01) is ~3y, well outside it.
_REPORTING_DATE = date(2027, 1, 31)

# DQ009 does not exist as a named constant yet — the accepted design is
# "next after DQ008", but the engine-implementer confirms/assigns the
# final code. String literal, not an import, so this file fails on
# assertion values only, never on a not-yet-defined constant.
_DQ009 = "DQ009"

# Post-fix expected portfolio total: pipeline-observed pre-fix baseline
# (4,500,000, see module docstring) - S2B delta (-500,000).
_EXPECTED_TOTAL_RWA_POST_FIX = 4_000_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Build the P1.264 RawDataBundle: counterparty/loan/rating parquets, no
    facilities (loan-scoped ratings, mirrors p1_216/p1_223/p1_225).
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
    )


def _crr_config() -> CalculationConfig:
    """CRR SA-only config, reporting_date matching the fixture-report's verified run."""
    return CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


def _row(df: pl.DataFrame, exposure_reference: str) -> dict:
    """Return the single SA result row for ``exposure_reference``."""
    rows = df.filter(pl.col("exposure_reference") == exposure_reference).to_dicts()
    assert len(rows) == 1, (
        f"P1.264: expected exactly 1 row for {exposure_reference!r}, got {len(rows)}. "
        f"All exposure_references: {df['exposure_reference'].to_list()}"
    )
    return rows[0]


def _dq009_errors(errors: list) -> list:
    """Filter a CalculationError list down to DQ009 (ST-override class-gate) entries."""
    return [e for e in errors if e.code == _DQ009]


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixture
# ---------------------------------------------------------------------------


class TestP1264Art1401STClassGateCRR:
    """P1.264: CRR Art. 140(1) short-term-override obligor-class gate."""

    @pytest.fixture(scope="class")
    def pipeline_results(self):
        """CRR SA pipeline results over the full P1.264 fixture set (one run)."""
        bundle = _build_bundle()
        results = PipelineOrchestrator().run_with_data(bundle, _crr_config())
        assert results.sa_results is not None, (
            "SA results should not be None — check PermissionMode.STANDARDISED config"
        )
        return results

    @pytest.fixture(scope="class")
    def sa_results(self, pipeline_results) -> pl.DataFrame:
        """Collected SA results DataFrame (all five loans)."""
        return pipeline_results.sa_results.collect()

    # -------------------------------------------------------------------------
    # Item 1 — S1 value-corruption reversal. DISCRIMINATING: FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_264_s1_cqs_and_flag_revert(self, sa_results: pl.DataFrame) -> None:
        """
        P1.264 DISCRIMINATING: S1's mis-scoped CQS-3 ST override on a
        sovereign is rejected — cqs reverts to the counterparty's own
        CQS-1 long-term rating, has_short_term_ecai reverts to False.

        Arrange: LN_P264_S1, sovereign loan mis-scoped with a CQS-3 ST
                 rating (Art. 140(1) confines ST assessments to
                 institution/corporate obligors — sovereign is neither).
        Act:     full CRR SA pipeline.
        Assert:  cqs == 1, has_short_term_ecai is False.

        FAILS today: the override overwrites cqs unconditionally
        regardless of obligor class — cqs=3, has_short_term_ecai=True.
        """
        row = _row(sa_results, LOAN_S1_REF)

        assert row["cqs"] == 1, (
            f"P1.264: expected S1 cqs=1 (reverts to the counterparty's own "
            f"CQS-1 long-term sovereign rating — the mis-scoped ST override is "
            f"rejected per Art. 140(1)), got {row['cqs']!r}"
        )
        assert row["has_short_term_ecai"] is False, (
            f"P1.264: expected S1 has_short_term_ecai=False (the mis-scoped ST "
            f"override never applied), got {row['has_short_term_ecai']!r}"
        )

    def test_p1_264_s1_risk_weight_invariant(self, sa_results: pl.DataFrame) -> None:
        """
        P1.264: S1's risk_weight stays 0.00 both pre- and post-fix — the
        sovereign RW lookup reads ``cp_sovereign_cqs`` (the counterparty's
        own CQS-1 rating), not the corrupted ``cqs`` column, so this
        exposure's RWA was never actually affected by the mis-scope (only
        the ``cqs`` COLUMN was data-corrupt — see the reversal test above).

        Arrange: LN_P264_S1.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 0.00, rwa_final == 0.

        Should PASS both today and after the fix — a genuine invariant,
        not a discriminating test.
        """
        row = _row(sa_results, LOAN_S1_REF)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_SOV_BASELINE, abs=1e-6), (
            f"P1.264: expected S1 risk_weight={EXPECTED_RW_SOV_BASELINE:.2f} "
            f"(sovereign CQS 1, Art. 114 Table 1, unaffected by the cqs-column "
            f"corruption), got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_SOV_POST_FIX, abs=1.0), (
            f"P1.264: expected S1 rwa_final={EXPECTED_RWA_SOV_POST_FIX:,.0f}, "
            f"got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 2 — S2A reversal. DISCRIMINATING: FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_264_s2a_cqs_and_flag_revert(self, sa_results: pl.DataFrame) -> None:
        """
        P1.264 DISCRIMINATING: S2A's mis-scoped CQS-4 ST override on an
        UNRATED sovereign is rejected — cqs reverts to null (genuinely
        unrated), has_short_term_ecai reverts to False.

        Arrange: LN_P264_S2A, sovereign loan (CP_P264_SOV2, unrated at the
                 counterparty level) mis-scoped with a CQS-4 ST rating.
        Act:     full CRR SA pipeline.
        Assert:  cqs is null, has_short_term_ecai is False.

        FAILS today: cqs=4, has_short_term_ecai=True (the override applies
        regardless of obligor class).
        """
        row = _row(sa_results, LOAN_S2A_REF)

        assert row["cqs"] is None, (
            f"P1.264: expected S2A cqs=null (CP_P264_SOV2 is genuinely unrated — "
            f"the mis-scoped ST override is rejected per Art. 140(1)), "
            f"got {row['cqs']!r}"
        )
        assert row["has_short_term_ecai"] is False, (
            f"P1.264: expected S2A has_short_term_ecai=False (the mis-scoped ST "
            f"override never applied), got {row['has_short_term_ecai']!r}"
        )

    def test_p1_264_s2a_risk_weight_invariant(self, sa_results: pl.DataFrame) -> None:
        """
        P1.264: S2A's risk_weight stays 1.00 both pre- and post-fix — CQS 4
        happens to coincide with the CQS-table's UNRATED entry (both map to
        100%), so this exposure's own RWA is unaffected by the mis-scope
        even though the ``cqs`` COLUMN is corrupt pre-fix (see the reversal
        test above). The REAL RWA-visible damage is on S2B, not S2A itself
        (see test_p1_264_s2b_decontaminated_to_100_pct).

        Arrange: LN_P264_S2A.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 1.00, rwa_final == 1,000,000.

        Should PASS both today and after the fix.
        """
        row = _row(sa_results, LOAN_S2A_REF)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_SOV2_UNRATED_BASELINE, abs=1e-6), (
            f"P1.264: expected S2A risk_weight={EXPECTED_RW_SOV2_UNRATED_BASELINE:.2f} "
            f"(unrated-sovereign CQS-table fallback, unaffected by the cqs-column "
            f"corruption at this particular value), got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_SOV2_UNRATED_BASELINE, rel=1e-4), (
            f"P1.264: expected S2A rwa_final={EXPECTED_RWA_SOV2_UNRATED_BASELINE:,.0f}, "
            f"got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 3 — S2B decontamination (the RWA pin). DISCRIMINATING: FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_264_s2b_decontaminated_to_100_pct(self, sa_results: pl.DataFrame) -> None:
        """
        P1.264 DISCRIMINATING: S2B (CP_P264_SOV2's genuinely unrated,
        unsecured, long-term SIBLING of S2A) reverts to the plain
        unrated-sovereign 100% baseline once S2A's mis-scoped override is
        rejected.

        Derivation: the missing Art. 140(1) class gate lets S2A's
        mis-scoped ``has_short_term_ecai``/``cqs=4`` feed P1.225's Art.
        140(2)(a) 150%-broadcast machinery (``obligor_st_150_contamination``,
        already landed) — the gate kills the trigger UPSTREAM, before Art.
        140(2) ever sees it, so the contamination flag never sets for
        CP_P264_SOV2 and S2B is never touched.

        Arrange: LN_P264_S2B, unrated, unsecured, long-term (outside the ST
                 window — its own maturity cannot trigger has_short_term_ecai).
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 1.00, rwa_final == 1,000,000.

        FAILS today: risk_weight=1.50, rwa_final=1,500,000 — S2B is a
        genuinely unrated, long-term exposure with NO rating of its own,
        yet gets swept into 150% purely because S2A's corrupted CQS
        happens to sit on the same obligor.
        """
        row = _row(sa_results, LOAN_S2B_REF)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_SOV2_UNRATED_BASELINE, abs=1e-6), (
            f"P1.264: expected S2B risk_weight={EXPECTED_RW_SOV2_UNRATED_BASELINE:.2f} "
            f"(unrated-sovereign baseline — S2A's mis-scoped override no longer "
            f"triggers the Art. 140(2)(a) contamination flag), "
            f"got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_SOV2_UNRATED_BASELINE, rel=1e-4), (
            f"P1.264: expected S2B rwa_final={EXPECTED_RWA_SOV2_UNRATED_BASELINE:,.0f} "
            f"(EAD 1,000,000 x 100%), got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 4 — DQ warnings. DISCRIMINATING: FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_264_exactly_three_dq009_warnings_for_the_mis_scoped_ratings(
        self, pipeline_results
    ) -> None:
        """
        P1.264 DISCRIMINATING: exactly three DQ009 warnings are raised, one
        per mis-scoped rating (S1, S2A, N1) — none for the correctly-scoped
        I1/C1 controls.

        Arrange: all six P1.264 loans in one pipeline run (three mis-scoped
                 ST ratings on sovereign/null-entity-type obligors, two
                 correctly-scoped ST ratings on institution/corporate).
        Act:     full CRR SA pipeline.
        Assert:  len(DQ009 warnings) == 3, all WARNING severity, none
                 attributable to LOAN_I1_REF/LOAN_C1_REF (when the
                 optional exposure_reference field is populated).

        FAILS today: zero DQ009 warnings exist (no code, no validation).
        """
        dq009 = _dq009_errors(pipeline_results.errors)

        assert len(dq009) == 3, (
            f"P1.264: expected exactly 3 DQ009 warnings (S1 + S2A + N1 "
            f"mis-scoped ST ratings), got {len(dq009)}. "
            f"All errors: {[(e.code, e.message) for e in pipeline_results.errors]}"
        )
        assert all(e.severity == ErrorSeverity.WARNING for e in dq009), (
            f"P1.264: all DQ009 entries should be WARNING severity, "
            f"got {[e.severity for e in dq009]}"
        )
        referenced_exposures = {
            e.exposure_reference for e in dq009 if e.exposure_reference is not None
        }
        assert not referenced_exposures & {LOAN_I1_REF, LOAN_C1_REF}, (
            f"P1.264: DQ009 must never reference the correctly-scoped I1/C1 "
            f"controls, got exposure_reference values: {referenced_exposures}"
        )

    # -------------------------------------------------------------------------
    # Item 5 — controls. PASS today, must stay green.
    # -------------------------------------------------------------------------

    def test_p1_264_i1_correctly_scoped_control_unchanged(self, sa_results: pl.DataFrame) -> None:
        """
        P1.264: I1 (correctly-scoped institution ST-CQS2 override) is
        unaffected by the class gate — the gate must let legitimate
        institution overrides through unmodified.

        Arrange: LN_P264_I1, CP_P264_INST (institution), loan-scoped
                 ST-CQS2 rating.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 0.50, rwa_final == 500,000.

        Should PASS today and MUST still pass after.
        """
        row = _row(sa_results, LOAN_I1_REF)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_I1, abs=1e-4), (
            f"P1.264: expected I1 risk_weight={EXPECTED_RW_I1:.2f} (Table 7 CQS 2), "
            f"got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_I1, rel=1e-4), (
            f"P1.264: expected I1 rwa_final={EXPECTED_RWA_I1:,.0f}, got {row['rwa_final']:,.2f}"
        )

    def test_p1_264_c1_correctly_scoped_control_unchanged(self, sa_results: pl.DataFrame) -> None:
        """
        P1.264: C1 (correctly-scoped corporate ST-CQS2 override) is
        unaffected by the class gate — the gate must let legitimate
        corporate overrides through unmodified.

        Arrange: LN_P264_C1, CP_P264_CORP (corporate), loan-scoped
                 ST-CQS2 rating.
        Act:     full CRR SA pipeline.
        Assert:  risk_weight == 0.50, rwa_final == 500,000.

        Should PASS today and MUST still pass after.
        """
        row = _row(sa_results, LOAN_C1_REF)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_C1, abs=1e-4), (
            f"P1.264: expected C1 risk_weight={EXPECTED_RW_C1:.2f} (Table 7 CQS 2), "
            f"got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_C1, rel=1e-4), (
            f"P1.264: expected C1 rwa_final={EXPECTED_RWA_C1:,.0f}, got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 6 — portfolio total. DISCRIMINATING: FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_264_portfolio_total_rwa_reflects_decontamination(
        self, sa_results: pl.DataFrame
    ) -> None:
        """
        P1.264 DISCRIMINATING: portfolio total rwa_final reflects the S2B
        decontamination delta (N1 contributes an invariant 1,000,000 on
        both sides — the "other" class never reads the ST tables).

        Derivation: pipeline-observed pre-fix baseline (both regimes)
            500,000 (C1) + 500,000 (I1) + 0 (S1) + 1,000,000 (S2A)
            + 1,500,000 (S2B) + 1,000,000 (N1) = 4,500,000
        Post-fix: 4,500,000 - 500,000 (S2B: 1,500,000 -> 1,000,000)
                = 4,000,000 (everything else RWA-stable — S1/S2A/N1's own
                RWA was already invariant, only their ``cqs``/
                ``has_short_term_ecai`` COLUMNS change, see items 1-2 and
                the N1 test)

        Arrange: all six P1.264 loans in one pipeline run.
        Act:     full CRR SA pipeline; sum rwa_final across all rows.
        Assert:  total rwa_final == 4,000,000.

        FAILS today: total is 4,500,000 (S2B still contaminated). This is
        a redundant cross-check against test_p1_264_s2b_decontaminated_to_100_pct.
        """
        total_rwa = sa_results["rwa_final"].sum()

        assert total_rwa == pytest.approx(_EXPECTED_TOTAL_RWA_POST_FIX, rel=1e-4), (
            f"P1.264: expected portfolio total rwa_final="
            f"{_EXPECTED_TOTAL_RWA_POST_FIX:,.0f} (pre-fix baseline 4,500,000 "
            f"- S2B delta 500,000), got {total_rwa:,.2f}"
        )

    # -------------------------------------------------------------------------
    # New — N1 null entity_type. DISCRIMINATING: FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_264_n1_null_entity_type_rejected_with_dq009(
        self, sa_results: pl.DataFrame, pipeline_results
    ) -> None:
        """
        P1.264 DISCRIMINATING: N1's mis-scoped CQS-3 ST override on a
        NULL-entity_type obligor is rejected — the reviewer-found
        Kleene-null path (a null ``entity_type`` must not silently pass
        the class gate's ``fill_null("")`` guard).

        risk_weight is asserted as an INVARIANT, not a discriminating
        value: CP_P264_NULLTYPE's entity_type=NULL falls through every
        ENTITY_TYPE_TO_SA_CLASS entry to exposure_class="other", which is
        not on the ECRA/SCRA short-term Table 7 / Table 4A-6A class list
        at all — the mis-scoped override was always RWA-inert for this
        obligor. DQ009 is the ONLY observable effect of the fix here.

        Arrange: LN_P264_N1, CP_P264_NULLTYPE (entity_type=NULL) loan
                 mis-scoped with a CQS-3 ST rating (same shape as S1).
        Act:     full CRR SA pipeline.
        Assert:  has_short_term_ecai is False, cqs is null,
                 risk_weight == 1.00 (invariant), at least one DQ009
                 references LN_P264_N1 (or its rating).

        FAILS today (pre-guard): the class gate did not exist, so a null
        entity_type silently passed through — this pins the null-guard
        fix, not just the sovereign/institution-string-comparison case.
        """
        row = _row(sa_results, LOAN_N1_REF)

        assert row["has_short_term_ecai"] is False, (
            f"P1.264: expected N1 has_short_term_ecai=False (the mis-scoped ST "
            f"override on a null-entity_type obligor is rejected per Art. 140(1)), "
            f"got {row['has_short_term_ecai']!r}"
        )
        assert row["cqs"] is None, (
            f"P1.264: expected N1 cqs=null (CP_P264_NULLTYPE carries no long-term "
            f"rating of its own — the mis-scoped ST override is rejected), "
            f"got {row['cqs']!r}"
        )
        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_NULLTYPE_BASELINE, abs=1e-6), (
            f"P1.264: expected N1 risk_weight={EXPECTED_RW_NULLTYPE_BASELINE:.2f} "
            f"(exposure_class 'other' fallback — invariant, unaffected by the "
            f"class-gate fix), got {row['risk_weight']:.4f}"
        )

        dq009 = _dq009_errors(pipeline_results.errors)
        n1_referenced = any(
            e.exposure_reference == LOAN_N1_REF
            or LOAN_N1_REF in e.message
            or RATING_N1_MISSCOPED_REF in e.message
            for e in dq009
        )
        assert n1_referenced, (
            f"P1.264: expected at least one DQ009 warning referencing "
            f"{LOAN_N1_REF!r} (or its rating {RATING_N1_MISSCOPED_REF!r}), "
            f"got none across {len(dq009)} DQ009 warnings. "
            f"All DQ009: {[(e.exposure_reference, e.message) for e in dq009]}"
        )
