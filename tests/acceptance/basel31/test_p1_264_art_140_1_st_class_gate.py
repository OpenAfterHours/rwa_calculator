"""
P1.264: PS1/26 Art. 140(1) short-term-override obligor-class gate (Basel 3.1 twin).

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> SACalculator -> Aggregator

Key responsibilities:
- Same scenario as the CRR sibling
  (tests/acceptance/crr/test_p1_264_art_140_1_st_class_gate.py) under
  ``CalculationConfig.basel_3_1()`` — Art. 140(1) text is identical in
  both regimes, and every expected value in this file is identical to the
  CRR sibling (pipeline-confirmed).

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1(), Table 4A-6A
CQS-to-RW — see tests/fixtures/p1_264/p1_264.py for the full derivation):

    S1 (CP_P264_SOV, mis-scoped ST-CQS3 on a sovereign):
        pre-fix:  cqs=3 (corrupted), has_short_term_ecai=True, RW=0.00
        post-fix: cqs reverts to 1, has_short_term_ecai=False, RW stays 0.00
    S2A (CP_P264_SOV2, mis-scoped ST-CQS4 on an UNRATED sovereign):
        pre-fix:  cqs=4 (corrupted), has_short_term_ecai=True, RW=1.00
        post-fix: cqs reverts to null, has_short_term_ecai=False, RW stays 1.00
    S2B (CP_P264_SOV2, unrated long-term unsecured sibling of S2A):
        pre-fix:  RW=1.50, RWA=1,500,000 (P1.225 contamination leak)
        post-fix: RW=1.00, RWA=1,000,000
    I1 (CP_P264_INST, correctly-scoped ST-CQS2 institution): RW=0.50,
        RWA=500,000 — both pre- and post-fix
    C1 (CP_P264_CORP, correctly-scoped ST-CQS2 corporate): RW=0.50,
        RWA=500,000 — both pre- and post-fix
    N1 (CP_P264_NULLTYPE, entity_type=NULL, mis-scoped ST-CQS3): RW=1.00
        (exposure_class "other" fallback), both pre- AND post-fix — the
        "other" class is not on the ECRA/SCRA short-term Table 4A-6A
        class list at all, so the mis-scoped override was always
        RWA-inert here. Only ``has_short_term_ecai``/``cqs`` and the
        DQ009 warning move.

    Portfolio total rwa_final (pipeline-observed, both regimes):
        pre-fix:  500,000 (C1) + 500,000 (I1) + 0 (S1) + 1,000,000 (S2A)
                 + 1,500,000 (S2B) + 1,000,000 (N1) = 4,500,000
        post-fix: 4,500,000 - 500,000 (S2B: 1,500,000 -> 1,000,000)
                 = 4,000,000

References:
    - PRA PS1/26 Art. 140(1) (CRE21.16): short-term credit assessments
      confined to institution/corporate obligors.
    - PRA PS1/26 Art. 114 Table 1: sovereign CQS-to-RW mapping (CQS 1 = 0%).
    - PRA PS1/26 Art. 120(2B) Table 4A / Art. 122(3) Table 6A: short-term
      credit assessment risk weights.
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

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.pipeline import PipelineOrchestrator
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

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_264"

# Same reporting date as the CRR sibling.
_REPORTING_DATE = date(2027, 1, 31)

# DQ009 does not exist as a named constant yet — see the CRR sibling for
# the same reasoning (string literal, not an import).
_DQ009 = "DQ009"

# Post-fix expected portfolio total: pipeline-observed pre-fix baseline
# (4,500,000, see module docstring) - S2B delta (-500,000).
_EXPECTED_TOTAL_RWA_POST_FIX = 4_000_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """Same P1.264 bundle as the CRR sibling — counterparty/loan/rating."""
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


def _basel_31_config() -> CalculationConfig:
    """Basel 3.1 SA-only config, same reporting_date as the CRR sibling."""
    return CalculationConfig.basel_3_1(
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
# P1.264 acceptance tests — Basel 3.1
# ---------------------------------------------------------------------------


class TestP1264Art1401STClassGateB31:
    """P1.264: PS1/26 Art. 140(1) short-term-override obligor-class gate."""

    @pytest.fixture(scope="class")
    def pipeline_results(self):
        """B31 SA pipeline results over the full P1.264 fixture set (one run)."""
        bundle = _build_bundle()
        results = PipelineOrchestrator().run_with_data(bundle, _basel_31_config())
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
                 rating.
        Act:     full B31 SA pipeline.
        Assert:  cqs == 1, has_short_term_ecai is False.

        FAILS today: cqs=3, has_short_term_ecai=True.
        """
        row = _row(sa_results, LOAN_S1_REF)

        assert row["cqs"] == 1, (
            f"P1.264 (B31): expected S1 cqs=1 (reverts to the counterparty's own "
            f"CQS-1 long-term sovereign rating — the mis-scoped ST override is "
            f"rejected per Art. 140(1)), got {row['cqs']!r}"
        )
        assert row["has_short_term_ecai"] is False, (
            f"P1.264 (B31): expected S1 has_short_term_ecai=False (the mis-scoped "
            f"ST override never applied), got {row['has_short_term_ecai']!r}"
        )

    def test_p1_264_s1_risk_weight_invariant(self, sa_results: pl.DataFrame) -> None:
        """
        P1.264: S1's risk_weight stays 0.00 both pre- and post-fix — the
        sovereign RW lookup reads ``cp_sovereign_cqs``, not the corrupted
        ``cqs`` column.

        Arrange: LN_P264_S1.
        Act:     full B31 SA pipeline.
        Assert:  risk_weight == 0.00, rwa_final == 0.

        Should PASS both today and after the fix.
        """
        row = _row(sa_results, LOAN_S1_REF)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_SOV_BASELINE, abs=1e-6), (
            f"P1.264 (B31): expected S1 risk_weight={EXPECTED_RW_SOV_BASELINE:.2f} "
            f"(sovereign CQS 1, unaffected by the cqs-column corruption), "
            f"got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_SOV_POST_FIX, abs=1.0), (
            f"P1.264 (B31): expected S1 rwa_final={EXPECTED_RWA_SOV_POST_FIX:,.0f}, "
            f"got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 2 — S2A reversal. DISCRIMINATING: FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_264_s2a_cqs_and_flag_revert(self, sa_results: pl.DataFrame) -> None:
        """
        P1.264 DISCRIMINATING: S2A's mis-scoped CQS-4 ST override on an
        UNRATED sovereign is rejected — cqs reverts to null,
        has_short_term_ecai reverts to False.

        Arrange: LN_P264_S2A, sovereign loan (CP_P264_SOV2, unrated at the
                 counterparty level) mis-scoped with a CQS-4 ST rating.
        Act:     full B31 SA pipeline.
        Assert:  cqs is null, has_short_term_ecai is False.

        FAILS today: cqs=4, has_short_term_ecai=True.
        """
        row = _row(sa_results, LOAN_S2A_REF)

        assert row["cqs"] is None, (
            f"P1.264 (B31): expected S2A cqs=null (CP_P264_SOV2 is genuinely "
            f"unrated — the mis-scoped ST override is rejected per Art. 140(1)), "
            f"got {row['cqs']!r}"
        )
        assert row["has_short_term_ecai"] is False, (
            f"P1.264 (B31): expected S2A has_short_term_ecai=False (the "
            f"mis-scoped ST override never applied), got {row['has_short_term_ecai']!r}"
        )

    def test_p1_264_s2a_risk_weight_invariant(self, sa_results: pl.DataFrame) -> None:
        """
        P1.264: S2A's risk_weight stays 1.00 both pre- and post-fix — CQS 4
        happens to coincide with the CQS-table's UNRATED entry.

        Arrange: LN_P264_S2A.
        Act:     full B31 SA pipeline.
        Assert:  risk_weight == 1.00, rwa_final == 1,000,000.

        Should PASS both today and after the fix.
        """
        row = _row(sa_results, LOAN_S2A_REF)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_SOV2_UNRATED_BASELINE, abs=1e-6), (
            f"P1.264 (B31): expected S2A risk_weight="
            f"{EXPECTED_RW_SOV2_UNRATED_BASELINE:.2f} (unrated-sovereign "
            f"CQS-table fallback), got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_SOV2_UNRATED_BASELINE, rel=1e-4), (
            f"P1.264 (B31): expected S2A rwa_final="
            f"{EXPECTED_RWA_SOV2_UNRATED_BASELINE:,.0f}, got {row['rwa_final']:,.2f}"
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
        mis-scoped has_short_term_ecai/cqs=4 feed P1.225's Art. 140(2)(a)
        150%-broadcast machinery — the gate kills the trigger UPSTREAM,
        before Art. 140(2) ever sees it.

        Arrange: LN_P264_S2B, unrated, unsecured, long-term.
        Act:     full B31 SA pipeline.
        Assert:  risk_weight == 1.00, rwa_final == 1,000,000.

        FAILS today: risk_weight=1.50, rwa_final=1,500,000.
        """
        row = _row(sa_results, LOAN_S2B_REF)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_SOV2_UNRATED_BASELINE, abs=1e-6), (
            f"P1.264 (B31): expected S2B risk_weight="
            f"{EXPECTED_RW_SOV2_UNRATED_BASELINE:.2f} (unrated-sovereign "
            f"baseline — S2A's mis-scoped override no longer triggers the "
            f"Art. 140(2)(a) contamination flag), got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_SOV2_UNRATED_BASELINE, rel=1e-4), (
            f"P1.264 (B31): expected S2B rwa_final="
            f"{EXPECTED_RWA_SOV2_UNRATED_BASELINE:,.0f} (EAD 1,000,000 x 100%), "
            f"got {row['rwa_final']:,.2f}"
        )

    # -------------------------------------------------------------------------
    # Item 4 — DQ warnings. DISCRIMINATING: FAILS today.
    # -------------------------------------------------------------------------

    def test_p1_264_exactly_three_dq009_warnings_for_the_mis_scoped_ratings(
        self, pipeline_results
    ) -> None:
        """
        P1.264 DISCRIMINATING: exactly three DQ009 warnings are raised,
        one per mis-scoped rating (S1, S2A, N1) — none for the
        correctly-scoped I1/C1 controls.

        Arrange: all six P1.264 loans in one pipeline run.
        Act:     full B31 SA pipeline.
        Assert:  len(DQ009 warnings) == 3, all WARNING severity, none
                 attributable to LOAN_I1_REF/LOAN_C1_REF.

        FAILS today: zero DQ009 warnings exist.
        """
        dq009 = _dq009_errors(pipeline_results.errors)

        assert len(dq009) == 3, (
            f"P1.264 (B31): expected exactly 3 DQ009 warnings (S1 + S2A + N1 "
            f"mis-scoped ST ratings), got {len(dq009)}. "
            f"All errors: {[(e.code, e.message) for e in pipeline_results.errors]}"
        )
        assert all(e.severity == ErrorSeverity.WARNING for e in dq009), (
            f"P1.264 (B31): all DQ009 entries should be WARNING severity, "
            f"got {[e.severity for e in dq009]}"
        )
        referenced_exposures = {
            e.exposure_reference for e in dq009 if e.exposure_reference is not None
        }
        assert not referenced_exposures & {LOAN_I1_REF, LOAN_C1_REF}, (
            f"P1.264 (B31): DQ009 must never reference the correctly-scoped "
            f"I1/C1 controls, got exposure_reference values: {referenced_exposures}"
        )

    # -------------------------------------------------------------------------
    # Item 5 — controls. PASS today, must stay green.
    # -------------------------------------------------------------------------

    def test_p1_264_i1_correctly_scoped_control_unchanged(self, sa_results: pl.DataFrame) -> None:
        """
        P1.264: I1 (correctly-scoped institution ST-CQS2 override) is
        unaffected by the class gate.

        Arrange: LN_P264_I1, CP_P264_INST (institution), loan-scoped
                 ST-CQS2 rating.
        Act:     full B31 SA pipeline.
        Assert:  risk_weight == 0.50, rwa_final == 500,000.

        Should PASS today and MUST still pass after.
        """
        row = _row(sa_results, LOAN_I1_REF)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_I1, abs=1e-4), (
            f"P1.264 (B31): expected I1 risk_weight={EXPECTED_RW_I1:.2f} (CQS 2), "
            f"got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_I1, rel=1e-4), (
            f"P1.264 (B31): expected I1 rwa_final={EXPECTED_RWA_I1:,.0f}, "
            f"got {row['rwa_final']:,.2f}"
        )

    def test_p1_264_c1_correctly_scoped_control_unchanged(self, sa_results: pl.DataFrame) -> None:
        """
        P1.264: C1 (correctly-scoped corporate ST-CQS2 override) is
        unaffected by the class gate.

        Arrange: LN_P264_C1, CP_P264_CORP (corporate), loan-scoped
                 ST-CQS2 rating.
        Act:     full B31 SA pipeline.
        Assert:  risk_weight == 0.50, rwa_final == 500,000.

        Should PASS today and MUST still pass after.
        """
        row = _row(sa_results, LOAN_C1_REF)

        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_C1, abs=1e-4), (
            f"P1.264 (B31): expected C1 risk_weight={EXPECTED_RW_C1:.2f} (CQS 2), "
            f"got {row['risk_weight']:.4f}"
        )
        assert row["rwa_final"] == pytest.approx(EXPECTED_RWA_C1, rel=1e-4), (
            f"P1.264 (B31): expected C1 rwa_final={EXPECTED_RWA_C1:,.0f}, "
            f"got {row['rwa_final']:,.2f}"
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
        both sides).

        Derivation: pipeline-observed pre-fix baseline (both regimes)
            500,000 (C1) + 500,000 (I1) + 0 (S1) + 1,000,000 (S2A)
            + 1,500,000 (S2B) + 1,000,000 (N1) = 4,500,000
        Post-fix: 4,500,000 - 500,000 (S2B: 1,500,000 -> 1,000,000)
                = 4,000,000

        Arrange: all six P1.264 loans in one pipeline run.
        Act:     full B31 SA pipeline; sum rwa_final across all rows.
        Assert:  total rwa_final == 4,000,000.

        FAILS today: total is 4,500,000 (S2B still contaminated).
        """
        total_rwa = sa_results["rwa_final"].sum()

        assert total_rwa == pytest.approx(_EXPECTED_TOTAL_RWA_POST_FIX, rel=1e-4), (
            f"P1.264 (B31): expected portfolio total rwa_final="
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
        not on the ECRA/SCRA short-term Table 4A-6A class list at all —
        the mis-scoped override was always RWA-inert for this obligor.
        DQ009 is the ONLY observable effect of the fix here.

        Arrange: LN_P264_N1, CP_P264_NULLTYPE (entity_type=NULL) loan
                 mis-scoped with a CQS-3 ST rating (same shape as S1).
        Act:     full B31 SA pipeline.
        Assert:  has_short_term_ecai is False, cqs is null,
                 risk_weight == 1.00 (invariant), at least one DQ009
                 references LN_P264_N1 (or its rating).

        FAILS today (pre-guard): the class gate did not exist, so a null
        entity_type silently passed through — this pins the null-guard
        fix, not just the sovereign/institution-string-comparison case.
        """
        row = _row(sa_results, LOAN_N1_REF)

        assert row["has_short_term_ecai"] is False, (
            f"P1.264 (B31): expected N1 has_short_term_ecai=False (the "
            f"mis-scoped ST override on a null-entity_type obligor is rejected "
            f"per Art. 140(1)), got {row['has_short_term_ecai']!r}"
        )
        assert row["cqs"] is None, (
            f"P1.264 (B31): expected N1 cqs=null (CP_P264_NULLTYPE carries no "
            f"long-term rating of its own — the mis-scoped ST override is "
            f"rejected), got {row['cqs']!r}"
        )
        assert row["risk_weight"] == pytest.approx(EXPECTED_RW_NULLTYPE_BASELINE, abs=1e-6), (
            f"P1.264 (B31): expected N1 risk_weight="
            f"{EXPECTED_RW_NULLTYPE_BASELINE:.2f} (exposure_class 'other' "
            f"fallback — invariant, unaffected by the class-gate fix), "
            f"got {row['risk_weight']:.4f}"
        )

        dq009 = _dq009_errors(pipeline_results.errors)
        n1_referenced = any(
            e.exposure_reference == LOAN_N1_REF
            or LOAN_N1_REF in e.message
            or RATING_N1_MISSCOPED_REF in e.message
            for e in dq009
        )
        assert n1_referenced, (
            f"P1.264 (B31): expected at least one DQ009 warning referencing "
            f"{LOAN_N1_REF!r} (or its rating {RATING_N1_MISSCOPED_REF!r}), "
            f"got none across {len(dq009)} DQ009 warnings. "
            f"All DQ009: {[(e.exposure_reference, e.message) for e in dq009]}"
        )
