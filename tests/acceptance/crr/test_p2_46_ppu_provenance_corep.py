"""
P2.46 — Art. 150(1) PPU provenance enum: COREP C 07.00 rows 0050/0060.

Scenario:
    Three CRR corporate SA exposures (£1m each, unrated senior) that differ
    only in their SA routing provenance, surfaced via ppu_reason on the
    model_permissions table:

        EXP-P246-PPU:
            model_id MODEL-CORP-PPU-P246 → approach=standardised, ppu_reason=art_150_1_c
            Routing: Art. 150(1)(c) PPU → COREP C 07.00 row 0050 ("of which: PPU of SA").

        EXP-P246-ROLLOUT:
            model_id MODEL-CORP-ROLLOUT-P246 → approach=standardised, ppu_reason=art_148_rollout
            Routing: Art. 148 sequential roll-out → COREP C 07.00 row 0060
            ("of which: sequential IRB implementation").

        EXP-P246-NOPERM:
            No model_id in rating row → no model_permissions match → ppu_reason null.
            SA fallback — appears only in row 0010 (total).

    Load-bearing anti-degenerate invariant:
        Row 0010 EAD = 3,000,000  (all three exposures)
        Row 0050 EAD = 1,000,000  (PPU only)
        Row 0060 EAD = 1,000,000  (roll-out only)
        Residual     = 1,000,000  (no-permission only; 0010 − 0050 − 0060)

Pre-implementation failing mode:
    ``_c07_section1_subset`` (generator.py L3703) returns ``None`` for both
    row_ref "0050" and "0060" because no ppu_reason-aware filter exists yet.
    The generator therefore emits null rows for those row_refs.  The load-bearing
    assertion

        row_0050_ead == 1_000_000.0

    fails with AssertionError (not an ImportError or pipeline exception) because
    the "0200" column for that row is None, not 1_000_000.

Fix scope (engine-implementer):
    1. Add PpuReason StrEnum to domain/enums.py (art_150_1_a … art_150_1_j +
       art_148_rollout).
    2. Add ppu_reason ColumnSpec(pl.String, required=False) to
       MODEL_PERMISSIONS_SCHEMA (data/schemas.py L733).
    3. Add "standardised" to VALID_MODEL_PERMISSION_APPROACHES (data/schemas.py
       L1368) so PPU/roll-out rows pass input validation.
    4. Extend _resolve_model_permissions (classifier.py) to carry mp_ppu_reason
       onto the surviving SA-precedence row (ppu_reason in the output).
    5. Add ppu_reason ColumnSpec to CLASSIFIER_OUTPUT_SCHEMA.
    6. Extend _c07_section1_subset (generator.py L3703) to handle row_ref "0050"
       (filter ppu_reason.str.starts_with("art_150_1_")) and "0060"
       (filter ppu_reason == "art_148_rollout").

References:
    - CRR Art. 150(1)(a)-(j): PPU conditions (model-permissions.md L56-108)
    - CRR Art. 148: sequential IRB roll-out (model-permissions.md L31)
    - COREP C 07.00 / OF 07.00 Section 1 rows 0050/0060 (templates.py L298-299)
    - reporting/corep/generator.py L3703-3725 (_c07_section1_subset)
    - data/schemas.py L733 MODEL_PERMISSIONS_SCHEMA, L1368
      VALID_MODEL_PERMISSION_APPROACHES
    - tests/fixtures/p2_46/p2_46.py: fixture constants and factory functions
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from tests.fixtures.p2_46.p2_46 import (
    EXPECTED_PPU_EAD,
    EXPECTED_RESIDUAL_EAD,
    EXPECTED_ROLLOUT_EAD,
    EXPECTED_TOTAL_EAD,
    LOAN_NOPERM,
    LOAN_PPU,
    LOAN_ROLLOUT,
)

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p2_46"

# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------

_ABS_TOL = 1.0  # ±£1 absolute tolerance — SA is deterministic

# ---------------------------------------------------------------------------
# C 07.00 column reference for EAD ("Exposure value" per CRR_C07_COLUMNS)
# ---------------------------------------------------------------------------

_COL_EAD = "0200"

# ---------------------------------------------------------------------------
# Pipeline runner (module-level helper, one run feeds all test methods)
# ---------------------------------------------------------------------------


def _run_pipeline_p246():
    """Run the CRR pipeline with P2.46 scenario inputs.

    Loads counterparty, loan, rating, and model_permission parquet fixtures.
    Returns the AggregatedResultBundle from PipelineOrchestrator.run_with_data().

    Config:
        - CalculationConfig.crr(permission_mode=IRB)
        - reporting_date=2025-06-30 (CRR window — before 2027-01-01)
    """
    lending_mappings = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )
    facility_mappings = pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        }
    )
    facilities = pl.LazyFrame(
        schema={
            "facility_reference": pl.String,
            "counterparty_reference": pl.String,
        }
    )

    counterparties = pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet")
    loans = pl.scan_parquet(_FIXTURES_DIR / "loan.parquet")
    ratings = pl.scan_parquet(_FIXTURES_DIR / "rating.parquet")
    model_permissions = pl.scan_parquet(_FIXTURES_DIR / "model_permission.parquet")

    bundle = RawDataBundle(
        facilities=facilities,
        loans=loans,
        counterparties=counterparties,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        ratings=ratings,
        model_permissions=model_permissions,
    )
    config = CalculationConfig.crr(
        reporting_date=date(2025, 6, 30),
        permission_mode=PermissionMode.IRB,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


# ---------------------------------------------------------------------------
# P2.46 acceptance test class
# ---------------------------------------------------------------------------


class TestP246PpuProvenanceCorep:
    """
    P2.46: COREP C 07.00 corporate rows 0050/0060 must discriminate SA-routing
    provenance (PPU vs. sequential roll-out vs. no-permission).

    Scenario: three SA-routed CRR corporate loans (£1m each, unrated) with
    different ppu_reason values on their model_permissions rows.
    Reporting date 2025-06-30 (fully in CRR window).

    Load-bearing case: rows 0050 and 0060 must be populated with £1m EAD each.
    Pre-implementation both are null because _c07_section1_subset has no
    ppu_reason-aware filter.
    """

    @pytest.fixture(scope="class")
    def pipeline_result(self):
        """Run the full pipeline once; return AggregatedResultBundle."""
        return _run_pipeline_p246()

    @pytest.fixture(scope="class")
    def per_loan_rwa(self, pipeline_result):
        """Extract rwa_final keyed by loan_reference from pipeline results.

        These values are INVARIANT: the feature only affects COREP row 0050/0060
        aggregation, not the per-exposure SA capital calculation (all three are
        100% SA RW → RWA = EAD = £1m each).
        """
        results_df = pipeline_result.results.collect()
        ref_col = next(
            c for c in ("loan_reference", "exposure_reference") if c in results_df.columns
        )
        return {
            row[ref_col]: float(row["rwa_final"])
            for row in results_df.select([ref_col, "rwa_final"]).iter_rows(named=True)
            if row["rwa_final"] is not None
        }

    @pytest.fixture(scope="class")
    def corep_c07_corporate(self, pipeline_result):
        """Generate COREP C 07.00 for the 'corporate' class from pipeline results.

        The generator is called on result.results (the post-floor per-exposure
        LazyFrame), which carries all classifier columns including ppu_reason
        (once the engine-implementer adds it).

        Pre-fix: rows 0050 and 0060 have EAD column "0200" == None.
        Post-fix: rows 0050 and 0060 have EAD == 1,000,000 each.
        """
        generator = COREPGenerator()
        bundle = generator.generate_from_lazyframe(
            pipeline_result.results,
            framework="CRR",
        )
        assert "corporate" in bundle.c07_00, (
            "P2.46: 'corporate' key must be present in C 07.00 bundle. "
            "Check that all three loans loaded as corporate exposures "
            "and that approach_applied='standardised' is present in results."
        )
        return bundle.c07_00["corporate"]

    def _row_ead(self, c07_df: pl.DataFrame, row_ref: str) -> float | None:
        """Return the col-0200 EAD value for a given row_ref, or None if null.

        Raises AssertionError if the row_ref does not exist in the template —
        that indicates a template structure problem distinct from the P2.46 failure.
        """
        rows = c07_df.filter(pl.col("row_ref") == row_ref)
        assert rows.height == 1, (
            f"P2.46: Expected exactly 1 row with row_ref='{row_ref}' in C 07.00 corporate, "
            f"got {rows.height}. Available row_refs: "
            f"{c07_df['row_ref'].to_list()!r}"
        )
        raw = rows[_COL_EAD][0]
        return float(raw) if raw is not None else None

    # ------------------------------------------------------------------
    # GUARD — pipeline produces non-zero RWA for all three loans
    # ------------------------------------------------------------------

    def test_p2_46_guard_all_three_loans_have_rwa(self, per_loan_rwa) -> None:
        """
        Guard: all three P2.46 loans must have non-zero rwa_final.

        If any loan has zero or missing RWA the scenario is broken (classification
        or SA formula problem), not a COREP aggregation bug.

        Arrange: P2.46 fixtures, CRR IRB config.
        Act:     full pipeline run.
        Assert:  rwa_final > 0 for EXP-P246-PPU, EXP-P246-ROLLOUT, EXP-P246-NOPERM.
        """
        for loan_ref in (LOAN_PPU, LOAN_ROLLOUT, LOAN_NOPERM):
            rwa = per_loan_rwa.get(loan_ref, 0.0)
            assert rwa > 0.0, (
                f"P2.46 GUARD: rwa_final for {loan_ref!r} must be > 0. Got {rwa}. "
                "Check that the loan loaded correctly and the SA calculator ran."
            )

    # ------------------------------------------------------------------
    # GUARD — row 0050 and 0060 exist in the generated C 07.00
    # ------------------------------------------------------------------

    def test_p2_46_guard_corep_row_0050_exists(self, corep_c07_corporate) -> None:
        """
        Guard: row 0050 must be present in C 07.00 corporate for CRR.

        If this guard fails the COREP template structure is broken.

        Arrange: P2.46 fixtures, CRR IRB config.
        Act:     generate C 07.00 corporate.
        Assert:  c07_df contains row_ref == '0050'.
        """
        assert corep_c07_corporate.filter(pl.col("row_ref") == "0050").height == 1, (
            "P2.46 GUARD: row_ref='0050' (of which: Exposures under permanent partial use "
            "of SA) must exist in C 07.00 corporate under CRR framework. "
            "Ensure framework='CRR' is passed to generate_from_lazyframe and "
            "CRR_SA_ROW_SECTIONS includes this row."
        )

    def test_p2_46_guard_corep_row_0060_exists(self, corep_c07_corporate) -> None:
        """
        Guard: row 0060 must be present in C 07.00 corporate for CRR.

        Arrange: P2.46 fixtures, CRR IRB config.
        Act:     generate C 07.00 corporate.
        Assert:  c07_df contains row_ref == '0060'.
        """
        assert corep_c07_corporate.filter(pl.col("row_ref") == "0060").height == 1, (
            "P2.46 GUARD: row_ref='0060' (of which: Exposures under sequential IRB "
            "implementation) must exist in C 07.00 corporate under CRR framework. "
            "Ensure CRR_SA_ROW_SECTIONS includes row '0060'."
        )

    # ------------------------------------------------------------------
    # GUARD — row 0010 (total SA EAD) == 3,000,000
    # ------------------------------------------------------------------

    def test_p2_46_guard_row_0010_total_sa_ead(self, corep_c07_corporate) -> None:
        """
        Guard: row 0010 total SA EAD == 3,000,000 (three exposures × £1m).

        If this fails the pipeline is not producing 3 SA corporate exposures.
        This guard passes pre- and post-fix.

        Arrange: P2.46 fixtures, CRR IRB config.
        Act:     generate C 07.00 corporate.
        Assert:  row 0010 col 0200 ≈ 3,000,000.
        """
        actual = self._row_ead(corep_c07_corporate, "0010")
        assert actual is not None, (
            "P2.46 GUARD: row 0010 EAD (col 0200) must not be None. "
            "Check that ead_final/ead column is present in pipeline results."
        )
        assert actual == pytest.approx(EXPECTED_TOTAL_EAD, abs=_ABS_TOL), (
            f"P2.46 GUARD: row 0010 (Total SA EAD) = {actual:,.2f} "
            f"but expected {EXPECTED_TOTAL_EAD:,.2f} (3 × £1m corporate loans). "
            "All three P2.46 exposures must be present in SA corporate."
        )

    # ------------------------------------------------------------------
    # LOAD-BEARING — row 0050 PPU EAD == 1,000,000
    # ------------------------------------------------------------------

    def test_p2_46_row_0050_ppu_ead_is_1m(self, corep_c07_corporate) -> None:
        """
        PRIMARY (LOAD-BEARING): row 0050 EAD == 1,000,000 (PPU exposure only).

        COREP row 0050 ('of which: Exposures under permanent partial use of SA')
        must include ONLY EXP-P246-PPU (ppu_reason='art_150_1_c').

        Pre-implementation: _c07_section1_subset returns None for row_ref='0050'
        → the generator emits a null row → EAD col 0200 = None.

        This assertion FAILS pre-fix with:
            AssertionError: 1000000.0 != None  (or None != pytest.approx(1000000.0))

        Post-fix invariant: row 0050 EAD = £1m (EXP-P246-PPU only).

        Arrange: P2.46 fixtures, CRR IRB config.
        Act:     generate C 07.00 corporate.
        Assert:  row 0050 col 0200 ≈ 1,000,000.

        References:
            CRR Art. 150(1)(c): PPU condition — permanent partial use of SA.
            COREP C 07.00 / OF 07.00 Section 1 row 0050.
        """
        # Arrange / Act — via fixture
        actual = self._row_ead(corep_c07_corporate, "0050")

        # Assert — LOAD-BEARING: pre-fix gives None, expected 1,000,000
        assert actual == pytest.approx(EXPECTED_PPU_EAD, abs=_ABS_TOL), (
            f"P2.46 BUG: COREP row 0050 (PPU of SA) EAD col {_COL_EAD} = {actual!r} "
            f"but expected {EXPECTED_PPU_EAD:,.2f} (= EAD of EXP-P246-PPU, "
            "ppu_reason='art_150_1_c', CRR Art. 150(1)(c)). "
            "Pre-fix: _c07_section1_subset has no ppu_reason-aware filter for row '0050' "
            "→ returns None → generator emits null row → EAD = None. "
            "Engine-implementer must add ppu_reason column to the classifier output and "
            "filter ppu_reason.str.starts_with('art_150_1_') for row 0050 in "
            "_c07_section1_subset (generator.py)."
        )

    # ------------------------------------------------------------------
    # LOAD-BEARING — row 0060 sequential roll-out EAD == 1,000,000
    # ------------------------------------------------------------------

    def test_p2_46_row_0060_rollout_ead_is_1m(self, corep_c07_corporate) -> None:
        """
        PRIMARY (LOAD-BEARING): row 0060 EAD == 1,000,000 (roll-out exposure only).

        COREP row 0060 ('of which: Exposures under sequential IRB implementation')
        must include ONLY EXP-P246-ROLLOUT (ppu_reason='art_148_rollout').

        Pre-implementation: _c07_section1_subset returns None for row_ref='0060'
        → the generator emits a null row → EAD col 0200 = None.

        This assertion FAILS pre-fix with:
            AssertionError: 1000000.0 != None

        Post-fix invariant: row 0060 EAD = £1m (EXP-P246-ROLLOUT only).

        Arrange: P2.46 fixtures, CRR IRB config.
        Act:     generate C 07.00 corporate.
        Assert:  row 0060 col 0200 ≈ 1,000,000.

        References:
            CRR Art. 148: sequential IRB roll-out — Art. 148 phased implementation.
            COREP C 07.00 / OF 07.00 Section 1 row 0060.
        """
        # Arrange / Act — via fixture
        actual = self._row_ead(corep_c07_corporate, "0060")

        # Assert — LOAD-BEARING: pre-fix gives None, expected 1,000,000
        assert actual == pytest.approx(EXPECTED_ROLLOUT_EAD, abs=_ABS_TOL), (
            f"P2.46 BUG: COREP row 0060 (sequential IRB implementation) EAD col {_COL_EAD} "
            f"= {actual!r} but expected {EXPECTED_ROLLOUT_EAD:,.2f} "
            "(= EAD of EXP-P246-ROLLOUT, ppu_reason='art_148_rollout', CRR Art. 148). "
            "Pre-fix: _c07_section1_subset has no ppu_reason-aware filter for row '0060' "
            "→ returns None → generator emits null row → EAD = None. "
            "Engine-implementer must filter ppu_reason == 'art_148_rollout' for row 0060 "
            "in _c07_section1_subset (generator.py)."
        )

    # ------------------------------------------------------------------
    # ANTI-DEGENERATE — residual (0010 − 0050 − 0060) > 0
    # ------------------------------------------------------------------

    def test_p2_46_residual_no_permission_is_positive(self, corep_c07_corporate) -> None:
        """
        ANTI-DEGENERATE: residual (row 0010 − row 0050 − row 0060) == 1,000,000 > 0.

        EXP-P246-NOPERM (no model_id → no ppu_reason) must appear only in row 0010
        and not in rows 0050 or 0060.  If residual ≤ 0 the test data is degenerate
        (all exposures have ppu_reason, leaving nothing to test the null-case branch).

        This guard also validates that rows 0050 + 0060 do NOT over-count the total.

        Pre-implementation: rows 0050/0060 are None so residual = 0010 - 0 - 0 = 3m
        (non-zero but wrong).  This assertion may pass or fail depending on how
        None is coerced to 0 in the arithmetic.  The load-bearing assertions
        (test_p2_46_row_0050_ppu_ead_is_1m and test_p2_46_row_0060_rollout_ead_is_1m)
        are the primary red-mode drivers.

        Post-fix: residual = 3m − 1m − 1m = 1m == EXPECTED_RESIDUAL_EAD.

        Arrange: P2.46 fixtures, CRR IRB config.
        Act:     generate C 07.00 corporate.
        Assert:  (row_0010_ead − row_0050_ead − row_0060_ead) ≈ 1,000,000.
        """
        # Arrange
        ead_0010 = self._row_ead(corep_c07_corporate, "0010") or 0.0
        ead_0050 = self._row_ead(corep_c07_corporate, "0050") or 0.0
        ead_0060 = self._row_ead(corep_c07_corporate, "0060") or 0.0

        # Act
        residual = ead_0010 - ead_0050 - ead_0060

        # Assert — ANTI-DEGENERATE
        assert residual == pytest.approx(EXPECTED_RESIDUAL_EAD, abs=_ABS_TOL), (
            f"P2.46 ANTI-DEGENERATE: residual EAD (0010={ead_0010:,.2f} "
            f"- 0050={ead_0050:,.2f} - 0060={ead_0060:,.2f}) = {residual:,.2f}, "
            f"but expected {EXPECTED_RESIDUAL_EAD:,.2f}. "
            "EXP-P246-NOPERM (no ppu_reason) must contribute to row 0010 only, "
            "leaving residual = £1m."
        )

    # ------------------------------------------------------------------
    # CONSERVATION — per-exposure rwa_final all == 1,000,000
    # ------------------------------------------------------------------

    def test_p2_46_per_exposure_rwa_conservation(self, per_loan_rwa) -> None:
        """
        CONSERVATION: rwa_final == 1,000,000 for each exposure; portfolio sum == 3,000,000.

        PPU provenance is routing/provenance-only — it does NOT change the RWA
        for SA corporate (unrated, 100% risk weight).  All three loans must show
        rwa_final = EAD × 1.00 = 1,000,000.

        This assertion passes both pre- and post-fix (RWA conservation is
        invariant to the COREP aggregation change).

        Arrange: P2.46 fixtures, CRR IRB config.
        Act:     full pipeline run.
        Assert:  each loan rwa_final ≈ 1,000,000; sum ≈ 3,000,000.

        References:
            CRR Art. 122: unrated corporate SA risk weight = 100%.
            RWA = EAD × 1.00 = 1,000,000.
        """
        expected_per_exposure = 1_000_000.0
        expected_total = 3_000_000.0

        for loan_ref in (LOAN_PPU, LOAN_ROLLOUT, LOAN_NOPERM):
            rwa = per_loan_rwa.get(loan_ref)
            assert rwa is not None, (
                f"P2.46 CONSERVATION: rwa_final for {loan_ref!r} not found in pipeline results. "
                "All three loans must have rwa_final populated."
            )
            assert rwa == pytest.approx(expected_per_exposure, abs=_ABS_TOL), (
                f"P2.46 CONSERVATION: rwa_final for {loan_ref!r} = {rwa:,.2f} "
                f"but expected {expected_per_exposure:,.2f} "
                "(unrated corporate SA: RW=100%, EAD=£1m → RWA=£1m). "
                "CRR Art. 122."
            )

        total_rwa = sum(per_loan_rwa.get(lr, 0.0) for lr in (LOAN_PPU, LOAN_ROLLOUT, LOAN_NOPERM))
        assert total_rwa == pytest.approx(expected_total, abs=_ABS_TOL), (
            f"P2.46 CONSERVATION: portfolio rwa_final sum = {total_rwa:,.2f} "
            f"but expected {expected_total:,.2f} (3 × £1m). "
            "PPU provenance must not affect per-exposure RWA."
        )
