"""
P2.41 — COREP C 02.00 / OF 02.00 corporate sub-row split for Art. 147A(1)(e)/(f).

Scenario:
    Four IRB corporate counterparties designed to probe the three-way split:
        Row 0295 — Financial and large corporates (FSE limb OR large-corp-by-revenue)
        Row 0296 — Other general corporates SME
        Row 0297 — Other general corporates non-SME (default bucket)

    The load-bearing case is CP2 (LN-P241-LRGCORP): it is NOT a financial-sector
    entity (is_financial_sector_entity=False) but has annual_revenue=500m > GBP 440m.
    Under PRA PS1/26 Art. 147A(1)(d) this makes it a "large corporate" that must
    appear in COREP row 0295 alongside the FSE counterparty (CP1).

Pre-implementation failing mode:
    The COREP generator's ``_c02_00_irb_sub_agg`` only checks
    ``apply_fi_scalar`` / ``cp_is_financial_sector_entity`` for the ``_fse``
    signal.  CP2 has both of those False, so it falls into the ``nonsme`` bucket
    (row 0297) instead of row 0295.  The load-bearing assertion

        row_0295_rwa == rwa_fse + rwa_lrgcorp

    fails with an AssertionError (not a ColumnNotFoundError) because the
    COREP rows 0295/0296/0297 already exist — only the aggregation is wrong.

Fix scope (engine-implementer):
    Add ``cp_annual_revenue`` awareness to ``_c02_00_irb_sub_agg`` (or derive an
    ``exposure_subclass`` column in the classifier) so that corporate counterparties
    with annual_revenue > GBP 440m are marked ``_fse=True`` in the sub-aggregation,
    independent of their ``is_financial_sector_entity`` flag.

References:
    - PRA PS1/26 Art. 147A(1)(d): large-corporate F-IRB restriction (> GBP 440m)
    - PRA PS1/26 Art. 147A(1)(e): FSE F-IRB restriction
    - PRA PS1/26 Art. 147A(1)(f): other corporate (non-FSE, non-large, non-SME)
    - tests/fixtures/p2_41/p2_41.py: fixture constants and builders
    - src/rwa_calc/reporting/corep/generator.py: _c02_00_irb_sub_agg / _irb_sub_split
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from tests.fixtures.p2_41.p2_41 import (
    LOAN_CORPOTHER,
    LOAN_FSE,
    LOAN_LRGCORP,
    LOAN_SME,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p2_41"

# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------

_ABS_TOL = 1.0  # ±£1 absolute tolerance — IRB K formula is deterministic

# ---------------------------------------------------------------------------
# Pipeline runner (module-level helper, one run feeds all test methods)
# ---------------------------------------------------------------------------


def _run_pipeline_p241():
    """Run the Basel 3.1 pipeline with P2.41 scenario inputs.

    Loads counterparty, loan, rating, and model_permission parquet fixtures.
    Returns the AggregatedResultBundle from PipelineOrchestrator.run_with_data().

    Config:
        - CalculationConfig.basel_3_1(permission_mode=IRB)
        - reporting_date=2027-06-01 (fully in Basel 3.1 window per fixture docstring)
        - No OF-ADJ inputs (floor not expected to bind for these moderate-PD loans)
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
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.IRB,
        gcra_amount=0.0,
        sa_t2_credit=0.0,
        art_40_deductions=0.0,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


# ---------------------------------------------------------------------------
# P2.41 acceptance test class
# ---------------------------------------------------------------------------


class TestP241ExposureSubclassCorep:
    """
    P2.41: COREP C 02.00 corporate sub-rows must correctly reflect the
    Art. 147A(1)(d)/(e) three-way split (financial/large, SME, non-SME).

    Scenario: four IRB corporates (two F-IRB: FSE + large-by-revenue;
    two A-IRB: other + SME). Reporting date 2027-06-01 (post-B3.1 effective).

    Load-bearing case: CP2 (LN-P241-LRGCORP) is NOT an FSE but has revenue
    > GBP 440m.  Pre-implementation it lands in row 0297 (non-SME other)
    because the COREP generator only checks the FSE flag, not revenue.
    The fix must also gate on annual_revenue > 440m.
    """

    @pytest.fixture(scope="class")
    def pipeline_result(self):
        """Run the full pipeline once; return AggregatedResultBundle."""
        return _run_pipeline_p241()

    @pytest.fixture(scope="class")
    def per_loan_rwa(self, pipeline_result):
        """Extract rwa_final keyed by loan_reference from pipeline results.

        These values are INVARIANT across both the pre- and post-fix engine:
        the feature only affects how the COREP generator aggregates RWA into
        rows — not the per-exposure IRB capital calculation itself.
        """
        results_df = pipeline_result.results.collect()
        # The pipeline joins loan_reference / exposure_reference through as
        # "loan_reference" from the Loader stage.
        ref_col = next(
            c for c in ("loan_reference", "exposure_reference") if c in results_df.columns
        )
        rwa_by_loan: dict[str, float] = {
            row[ref_col]: float(row["rwa_final"])
            for row in results_df.select([ref_col, "rwa_final"]).iter_rows(named=True)
            if row["rwa_final"] is not None
        }
        return rwa_by_loan

    @pytest.fixture(scope="class")
    def corep_c02(self, pipeline_result):
        """Generate COREP C 02.00 from the pipeline results LazyFrame.

        The generator is called directly on result.results (the post-floor
        per-exposure LazyFrame), which carries all cp_* columns added by the
        Classifier stage — including cp_is_financial_sector_entity,
        cp_annual_revenue, is_sme, approach_applied, and rwa_final.
        """
        generator = COREPGenerator()
        bundle = generator.generate_from_lazyframe(
            pipeline_result.results,
            framework="BASEL_3_1",
        )
        assert bundle.c_02_00 is not None, (
            "P2.41: COREP C 02.00 must not be None for BASEL_3_1 framework "
            "with IRB exposures. Check that rwa_final / ead_final / "
            "approach_applied / exposure_class columns are present in results."
        )
        return bundle.c_02_00

    def _row_rwa(self, c02_df: pl.DataFrame, row_ref: str) -> float:
        """Return the col-0010 RWA value for a given row_ref.

        Raises AssertionError if the row does not exist — that indicates a
        template structure problem, not the P2.41 assertion-level failure.
        """
        rows = c02_df.filter(pl.col("row_ref") == row_ref)
        assert rows.height == 1, (
            f"P2.41: Expected exactly 1 row with row_ref='{row_ref}' in C 02.00, "
            f"got {rows.height}. The COREP template may not include this row under "
            "BASEL_3_1 framework — check generator.py row sections."
        )
        return float(rows["0010"][0] or 0.0)

    # ------------------------------------------------------------------
    # GUARD — pipeline produces non-zero RWA for all four loans
    # ------------------------------------------------------------------

    def test_p2_41_guard_all_four_loans_have_rwa(self, per_loan_rwa) -> None:
        """
        Guard: all four P2.41 loans must have non-zero rwa_final.

        If any loan has zero RWA the scenario is broken (classification or
        IRB formula problem), not a COREP aggregation bug.

        Arrange: P2.41 fixtures + Basel 3.1 IRB config.
        Act:     full pipeline run.
        Assert:  rwa_final > 0 for LN-P241-FSE, LN-P241-LRGCORP,
                 LN-P241-CORPOTHER, LN-P241-SME.
        """
        # Arrange / Act — via fixtures

        # Assert
        for loan_ref in (LOAN_FSE, LOAN_LRGCORP, LOAN_CORPOTHER, LOAN_SME):
            rwa = per_loan_rwa.get(loan_ref, 0.0)
            assert rwa > 0.0, (
                f"P2.41 GUARD: rwa_final for {loan_ref!r} must be > 0. Got {rwa}. "
                "Check that the loan loaded correctly and the IRB calculator ran."
            )

    # ------------------------------------------------------------------
    # GUARD — row 0295 exists in the generated C 02.00
    # ------------------------------------------------------------------

    def test_p2_41_guard_corep_row_0295_exists(self, corep_c02) -> None:
        """
        Guard: row 0295 must be present in C 02.00 for Basel 3.1.

        If this guard fails the COREP template structure is broken (wrong
        framework or missing F-IRB rows).  It is not the P2.41 assertion failure.

        Arrange: P2.41 fixtures + Basel 3.1 IRB config.
        Act:     generate C 02.00.
        Assert:  c02_df contains row_ref == '0295'.
        """
        # Arrange / Act — via fixtures

        # Assert
        assert corep_c02.filter(pl.col("row_ref") == "0295").height == 1, (
            "P2.41 GUARD: row_ref='0295' (F-IRB Financial/large corporates) "
            "must exist in C 02.00 under BASEL_3_1 framework. "
            "Ensure framework='BASEL_3_1' is passed to generate_from_lazyframe."
        )

    # ------------------------------------------------------------------
    # LOAD-BEARING — row 0295 must contain BOTH FSE and large-corp RWA
    # ------------------------------------------------------------------

    def test_p2_41_row_0295_includes_large_corp_by_revenue(self, per_loan_rwa, corep_c02) -> None:
        """
        PRIMARY (LOAD-BEARING): row 0295 RWA == rwa_fse + rwa_lrgcorp.

        COREP row 0295 ('F-IRB — Financial and large corporates') must include
        BOTH:
          - CP1 (FSE, is_financial_sector_entity=True)  → via FSE limb
          - CP2 (large-corp by revenue, FSE=False, rev=500m)  → via revenue limb

        Pre-implementation, the COREP generator only checks
        ``cp_is_financial_sector_entity`` (or ``apply_fi_scalar``) for the
        ``_fse`` signal.  CP2 has both of these False, so it falls into
        ``nonsme`` (row 0297).  This assertion therefore FAILS pre-fix with:

            assert row_0295_rwa == pytest.approx(rwa_fse + rwa_lrgcorp, abs=1.0)
            AssertionError: row_0295 (≈ rwa_fse_only) != rwa_fse + rwa_lrgcorp

        Post-fix invariant: both CP1 and CP2 appear in row 0295.

        Arrange: P2.41 fixtures + Basel 3.1 IRB config.
        Act:     generate C 02.00 from pipeline results.
        Assert:  row 0295 col 0010 ≈ rwa_fse + rwa_lrgcorp (within ±£1).
        """
        # Arrange
        rwa_fse = per_loan_rwa[LOAN_FSE]
        rwa_lrgcorp = per_loan_rwa[LOAN_LRGCORP]
        expected_0295 = rwa_fse + rwa_lrgcorp

        # Act
        actual_0295 = self._row_rwa(corep_c02, "0295")

        # Assert — LOAD-BEARING
        assert actual_0295 == pytest.approx(expected_0295, abs=_ABS_TOL), (
            f"P2.41 BUG: COREP row 0295 (Financial/large corporates) = {actual_0295:,.2f} "
            f"but expected {expected_0295:,.2f} (= rwa_fse {rwa_fse:,.2f} + "
            f"rwa_lrgcorp {rwa_lrgcorp:,.2f}). "
            "CP2 (LN-P241-LRGCORP, is_financial_sector_entity=False, revenue=500m) "
            "must route into row 0295 via the large-corp-by-revenue limb "
            "(PRA PS1/26 Art. 147A(1)(d)). "
            "Current engine only checks cp_is_financial_sector_entity/apply_fi_scalar; "
            "CP2 is misrouted to row 0297."
        )

    def test_p2_41_row_0295_strictly_exceeds_fse_alone(self, per_loan_rwa, corep_c02) -> None:
        """
        ANTI-DEGENERATE: row 0295 > rwa_fse alone (CP2 must have moved in).

        This is the companion assertion to the equality check above.  It
        explicitly verifies that the large-corp RWA contribution is non-trivial
        (i.e. the test is not vacuously passing because rwa_lrgcorp ≈ 0).

        Pre-implementation: row_0295 ≈ rwa_fse_only, so this assertion
        passes trivially only if the equality check also passed — which it
        won't.  After the fix both assertions pass.

        Arrange: P2.41 fixtures + Basel 3.1 IRB config.
        Act:     generate C 02.00.
        Assert:  row 0295 col 0010 > rwa_fse (i.e. CP2 adds positive RWA).
        """
        # Arrange
        rwa_fse = per_loan_rwa[LOAN_FSE]

        # Act
        actual_0295 = self._row_rwa(corep_c02, "0295")

        # Assert — ANTI-DEGENERATE
        assert actual_0295 > rwa_fse + _ABS_TOL, (
            f"P2.41 ANTI-DEGENERATE: row 0295 ({actual_0295:,.2f}) must strictly exceed "
            f"rwa_fse alone ({rwa_fse:,.2f}). "
            "CP2 (LN-P241-LRGCORP) EAD=80m, PD=0.80%, LGD=40% must contribute "
            "positive RWA to row 0295 via the large-corp-by-revenue limb."
        )

    # ------------------------------------------------------------------
    # A-IRB non-SME other row (0356) and F-IRB non-SME row (0297)
    # ------------------------------------------------------------------

    def test_p2_41_row_0356_contains_corpother_rwa(self, per_loan_rwa, corep_c02) -> None:
        """
        Row 0356 (A-IRB Other general corporates non-SME) == rwa_corpother.

        CP3 (LN-P241-CORPOTHER, MODEL-P241-AIRB, revenue=100m in [44m, 440m],
        not FSE) uses the A-IRB model and is neither FSE, large-corp, nor SME.
        It routes to A-IRB row 0356 (other non-SME).

        This row is not directly affected by the P2.41 fix.

        Arrange: P2.41 fixtures + Basel 3.1 IRB config.
        Act:     generate C 02.00.
        Assert:  row 0356 col 0010 ≈ rwa_corpother (within ±£1).
        """
        # Arrange
        rwa_corpother = per_loan_rwa[LOAN_CORPOTHER]

        # Act
        actual_0356 = self._row_rwa(corep_c02, "0356")

        # Assert
        assert actual_0356 == pytest.approx(rwa_corpother, abs=_ABS_TOL), (
            f"P2.41: COREP row 0356 (A-IRB Other corporates non-SME) = {actual_0356:,.2f} "
            f"but expected {rwa_corpother:,.2f} (= rwa_corpother from LN-P241-CORPOTHER). "
            "CP3 (MODEL-P241-AIRB, annual_revenue=100m, is_sme=False) should route "
            "to A-IRB row 0356."
        )

    def test_p2_41_row_0297_contains_zero_post_fix(self, per_loan_rwa, corep_c02) -> None:
        """
        Row 0297 (F-IRB Other general corporates non-SME) must be 0 post-fix.

        Neither CP1 (FSE → 0295) nor CP2 (large-corp → 0295 post-fix) lands
        in F-IRB row 0297.  CP3 and CP4 are A-IRB → rows 0356, 0355.

        Pre-implementation: row 0297 ≈ rwa_lrgcorp (CP2 misrouted here).
        Post-fix: row 0297 = 0.0 (no F-IRB exposures outside 0295).

        Pre-implementation failing mode: this assertion fails because
        row 0297 = rwa_lrgcorp ≈ 60.4m instead of 0.

        Arrange: P2.41 fixtures + Basel 3.1 IRB config.
        Act:     generate C 02.00.
        Assert:  row 0297 col 0010 ≈ 0 (within ±£1).
        """
        # Arrange / Act
        actual_0297 = self._row_rwa(corep_c02, "0297")

        # Assert
        assert actual_0297 == pytest.approx(0.0, abs=_ABS_TOL), (
            f"P2.41: COREP row 0297 (F-IRB Other corporates non-SME) = {actual_0297:,.2f} "
            f"but expected ≈ 0.0. "
            "Pre-fix: row 0297 ≈ rwa_lrgcorp ({:,.2f}) because CP2 (LN-P241-LRGCORP) "
            "is misrouted here (FSE=False, large-corp-by-revenue not yet detected). "
            "Post-fix: CP2 moves to row 0295 and row 0297 = 0.".format(per_loan_rwa[LOAN_LRGCORP])
        )

    # ------------------------------------------------------------------
    # CONSERVATION — F-IRB sub-rows must sum to F-IRB corporate total
    # ------------------------------------------------------------------

    def test_p2_41_firb_corporate_conservation(self, per_loan_rwa, corep_c02) -> None:
        """
        CONSERVATION: rows 0295+0296+0297 == total F-IRB corporate RWA.

        CP1 (FSE) and CP2 (large-corp) are both F-IRB. Post-fix both land
        in row 0295, and rows 0296/0297 are zero:
            0295 = rwa_fse + rwa_lrgcorp
            0296 = 0.0  (no F-IRB SME in this fixture)
            0297 = 0.0  (no F-IRB non-SME-other in this fixture; pre-fix = rwa_lrgcorp)

        Sum (0295 + 0296 + 0297) = rwa_fse + rwa_lrgcorp (F-IRB total).

        Pre-fix: 0295 = rwa_fse; 0297 = rwa_lrgcorp (misrouted).
        Sum = rwa_fse + rwa_lrgcorp regardless — conservation HOLDS pre-fix.
        This is a post-fix regression guard (not a failing pre-fix assertion).

        Arrange: P2.41 fixtures + Basel 3.1 IRB config.
        Act:     generate C 02.00.
        Assert:  rows 0295+0296+0297 ≈ rwa_fse + rwa_lrgcorp (within ±£1).
        """
        # Arrange — only CP1 and CP2 are F-IRB
        firb_total = per_loan_rwa[LOAN_FSE] + per_loan_rwa[LOAN_LRGCORP]

        # Act
        row_0295 = self._row_rwa(corep_c02, "0295")
        row_0296 = self._row_rwa(corep_c02, "0296")
        row_0297 = self._row_rwa(corep_c02, "0297")
        sub_total = row_0295 + row_0296 + row_0297

        # Assert — CONSERVATION
        assert sub_total == pytest.approx(firb_total, abs=_ABS_TOL), (
            f"P2.41 CONSERVATION: F-IRB sub-rows 0295 ({row_0295:,.2f}) "
            f"+ 0296 ({row_0296:,.2f}) + 0297 ({row_0297:,.2f}) = {sub_total:,.2f} "
            f"must equal F-IRB corporate total {firb_total:,.2f} "
            f"(rwa_fse {per_loan_rwa[LOAN_FSE]:,.2f} + rwa_lrgcorp {per_loan_rwa[LOAN_LRGCORP]:,.2f}). "
            "If this fails, an F-IRB corporate exposure is double-counted or dropped."
        )
