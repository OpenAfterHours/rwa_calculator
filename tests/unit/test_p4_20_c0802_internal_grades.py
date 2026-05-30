"""
P4.20 — C 08.02 firm-supplied internal rating grades.

Failing tests (GROUP 1): Verify that the C 08.02 generator groups corporate
IRB exposures by the ``cp_internal_rating_grade`` column when present, producing
one row per grade label (AAA / BB / D) rather than collapsing into fixed PD
buckets.

Passing tests (GROUP 2): No-regression pin confirming that when the grade column
is absent the fixed-PD-bucket fallback output is byte-for-byte identical to the
existing behaviour tested in ``TestC0802``.

Pipeline position:
    grade-path results LazyFrame (cp_internal_rating_grade present)
        -> COREPGenerator.generate_from_lazyframe(lf, framework="CRR")
        -> COREPTemplateBundle.c08_02["corporate"]

References:
    - COREP Annex II, template C 08.02 ("CR IRB 2")
    - CRR Art. 142(1)(6) (internal rating system)
    - CRR Art. 153 (IRB risk-weight functions)
    - CRR Art. 169-170 (use of PD estimates)
    - P4.20 scenario proposal (tmp/batch-20260530-1718/P4.20-scenario.md)
"""

from __future__ import annotations

import pytest
import polars as pl

from rwa_calc.reporting.corep.generator import COREPGenerator

# Grade-path fixture builder and constants
from tests.fixtures.p4_20.p4_20 import (
    EXPECTED_AAA,
    EXPECTED_BB,
    EXPECTED_D,
    EXPECTED_GRADE_SET,
    EXPECTED_TOTAL_EAD,
    FALLBACK_SAME_BUCKET_EAD,
    FRAMEWORK,
    GRADE_AAA,
    GRADE_BB,
    GRADE_D,
    SAME_BUCKET_LABEL,
    build_grade_path_irb_results_lf,
)

# Fallback fixture reused from existing test module (do NOT modify)
from tests.unit.test_corep import _irb_results


# =============================================================================
# Helpers
# =============================================================================


def _extract_row(corp_df: pl.DataFrame, row_name: str, col: str) -> float:
    """Extract a single scalar from a C 08.02 corporate DataFrame.

    Returns 0.0 if the row is absent — this converts a KeyError / empty-frame
    situation into an assertion-level failure rather than an exception.
    """
    filtered = corp_df.filter(pl.col("row_name") == row_name)
    if filtered.height == 0:
        return 0.0
    return float(filtered[col][0])


def _row_name_set(corp_df: pl.DataFrame) -> set[str]:
    """Return the set of row_name values in a C 08.02 corporate DataFrame."""
    return set(corp_df["row_name"].to_list())


# =============================================================================
# GROUP 1 — Grade path (drives the engine change; FAILS today)
# =============================================================================
# Today the generator uses fixed PD buckets.  E1 (AAA, PD 0.01) and E2 (BB,
# PD 0.02) both map to "0.75% - 2.50%", so they collapse into ONE row.  The
# assertions below expect THREE rows {AAA, BB, D}; they will fail until the
# engine is updated to group by cp_internal_rating_grade.
# =============================================================================


class TestP420GradePath:
    """GROUP 1 — grade-keyed C 08.02 rows (fails until engine supports grades)."""

    @pytest.fixture()
    def bundle(self) -> object:
        """Generate C 08.02 bundle from the grade-path fixture (CRR framework)."""
        gen = COREPGenerator()
        lf = build_grade_path_irb_results_lf()
        return gen.generate_from_lazyframe(lf, framework=FRAMEWORK)

    @pytest.fixture()
    def corp(self, bundle: object) -> pl.DataFrame:
        """Extract the corporate C 08.02 DataFrame from the bundle."""
        return bundle.c08_02["corporate"]  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Row count and row-name set
    # ------------------------------------------------------------------

    def test_p420_grade_path_row_count(self, corp: pl.DataFrame) -> None:
        """C 08.02 corporate produces exactly 3 rows when grade column is present.

        Arrange: grade-path fixture with grades AAA (E1) / BB (E2) / D (E3).
        Act: generate C 08.02 (CRR framework).
        Assert: 3 rows — one per grade.

        Today FAILS: E1+E2 collapse into the "0.75% - 2.50%" PD bucket (2 rows).
        """
        # Arrange / Act happen in fixtures
        actual_row_count = corp.height
        assert actual_row_count == 3, (
            f"Expected 3 grade rows {{AAA, BB, D}}, got {actual_row_count} rows. "
            f"Row names: {_row_name_set(corp)!r}. "
            "FAIL: engine is still using fixed PD buckets instead of grade labels."
        )

    def test_p420_grade_path_row_name_set(self, corp: pl.DataFrame) -> None:
        """C 08.02 row_name set is the firm grade labels {AAA, BB, D}.

        Arrange: grade-path fixture.
        Act: generate C 08.02 (CRR).
        Assert: row_name set == {AAA, BB, D}.

        Today FAILS: row names are PD-band labels (e.g. "0.75% - 2.50%").
        """
        actual_names = _row_name_set(corp)
        assert actual_names == EXPECTED_GRADE_SET, (
            f"Expected row_name set {EXPECTED_GRADE_SET!r}, got {actual_names!r}. "
            "FAIL: engine is grouping by PD bucket, not by internal rating grade."
        )

    def test_p420_grade_path_no_collapsed_same_bucket_row(self, corp: pl.DataFrame) -> None:
        """No single collapsed bucket row carrying EAD 3000 should exist.

        The discriminating assertion: under grade-keying AAA and BB are separate
        rows.  Under fixed-bucket keying they collapse to one "0.75% - 2.50%"
        row with EAD 3000 (= 1000 + 2000).

        Arrange: grade-path fixture.
        Act: generate C 08.02 (CRR).
        Assert: the "0.75% - 2.50%" bucket row is absent OR its EAD != 3000.

        Today FAILS: the collapsed row IS present with EAD 3000.
        """
        collapsed_ead = _extract_row(corp, SAME_BUCKET_LABEL, "0110")
        assert collapsed_ead != FALLBACK_SAME_BUCKET_EAD, (
            f"Found collapsed '{SAME_BUCKET_LABEL}' row with EAD {collapsed_ead!r} "
            f"(== FALLBACK_SAME_BUCKET_EAD={FALLBACK_SAME_BUCKET_EAD}). "
            "FAIL: AAA and BB are being merged into a single PD-bucket row."
        )

    # ------------------------------------------------------------------
    # AAA row assertions
    # ------------------------------------------------------------------

    def test_p420_aaa_row_ead(self, corp: pl.DataFrame) -> None:
        """AAA grade row has EAD 1000.0 (col 0110).

        Arrange: grade-path fixture, E1 = AAA, EAD 1000.
        Act: generate C 08.02 (CRR).
        Assert: AAA row col 0110 == 1000.0.

        Today FAILS: AAA row absent (guard returns 0.0), assert 0.0 == 1000.0.
        """
        actual = _extract_row(corp, GRADE_AAA, "0110")
        assert actual == pytest.approx(float(EXPECTED_AAA["0110"])), (  # type: ignore[arg-type]
            f"AAA row col 0110 expected {EXPECTED_AAA['0110']!r}, got {actual!r}. "
            "FAIL: grade-keyed AAA row is absent or has wrong EAD."
        )

    def test_p420_aaa_row_pd(self, corp: pl.DataFrame) -> None:
        """AAA grade row weighted PD == 0.01 (col 0010).

        Arrange: grade-path fixture, E1 PD = 0.01.
        Act: generate C 08.02 (CRR).
        Assert: AAA row col 0010 == 0.01.

        Today FAILS: AAA row absent (guard returns 0.0), assert 0.0 == 0.01.
        """
        actual = _extract_row(corp, GRADE_AAA, "0010")
        assert actual == pytest.approx(float(EXPECTED_AAA["0010"])), (  # type: ignore[arg-type]
            f"AAA row col 0010 expected {EXPECTED_AAA['0010']!r}, got {actual!r}."
        )

    def test_p420_aaa_row_maturity_days(self, corp: pl.DataFrame) -> None:
        """AAA grade row EW maturity == 730.0 days (col 0250 = 2.0 yr * 365).

        Arrange: grade-path fixture, E1 maturity = 2.0 yr.
        Act: generate C 08.02 (CRR).
        Assert: AAA row col 0250 == 730.0.

        Today FAILS: AAA row absent (guard returns 0.0), assert 0.0 == 730.0.
        """
        actual = _extract_row(corp, GRADE_AAA, "0250")
        assert actual == pytest.approx(float(EXPECTED_AAA["0250"])), (  # type: ignore[arg-type]
            f"AAA row col 0250 expected {EXPECTED_AAA['0250']!r}, got {actual!r}."
        )

    # ------------------------------------------------------------------
    # BB row assertions
    # ------------------------------------------------------------------

    def test_p420_bb_row_ead(self, corp: pl.DataFrame) -> None:
        """BB grade row has EAD 2000.0 (col 0110).

        Arrange: grade-path fixture, E2 = BB, EAD 2000.
        Act: generate C 08.02 (CRR).
        Assert: BB row col 0110 == 2000.0.

        Today FAILS: BB row absent (guard returns 0.0), assert 0.0 == 2000.0.
        """
        actual = _extract_row(corp, GRADE_BB, "0110")
        assert actual == pytest.approx(float(EXPECTED_BB["0110"])), (  # type: ignore[arg-type]
            f"BB row col 0110 expected {EXPECTED_BB['0110']!r}, got {actual!r}. "
            "FAIL: grade-keyed BB row is absent or has wrong EAD."
        )

    def test_p420_bb_row_pd(self, corp: pl.DataFrame) -> None:
        """BB grade row weighted PD == 0.02 (col 0010).

        Arrange: grade-path fixture, E2 PD = 0.02.
        Act: generate C 08.02 (CRR).
        Assert: BB row col 0010 == 0.02.

        Today FAILS: BB row absent (guard returns 0.0), assert 0.0 == 0.02.
        """
        actual = _extract_row(corp, GRADE_BB, "0010")
        assert actual == pytest.approx(float(EXPECTED_BB["0010"])), (  # type: ignore[arg-type]
            f"BB row col 0010 expected {EXPECTED_BB['0010']!r}, got {actual!r}."
        )

    def test_p420_bb_row_maturity_days(self, corp: pl.DataFrame) -> None:
        """BB grade row EW maturity == 730.0 days (col 0250 = 2.0 yr * 365).

        Arrange: grade-path fixture, E2 maturity = 2.0 yr.
        Act: generate C 08.02 (CRR).
        Assert: BB row col 0250 == 730.0.

        Today FAILS: BB row absent (guard returns 0.0), assert 0.0 == 730.0.
        """
        actual = _extract_row(corp, GRADE_BB, "0250")
        assert actual == pytest.approx(float(EXPECTED_BB["0250"])), (  # type: ignore[arg-type]
            f"BB row col 0250 expected {EXPECTED_BB['0250']!r}, got {actual!r}."
        )

    # ------------------------------------------------------------------
    # D row assertions (control row — also absent under fixed-bucket today
    # because grade column absent means no row_name=="D")
    # ------------------------------------------------------------------

    def test_p420_d_row_ead(self, corp: pl.DataFrame) -> None:
        """D grade row has EAD 500.0 (col 0110).

        Arrange: grade-path fixture, E3 = D, EAD 500.
        Act: generate C 08.02 (CRR).
        Assert: D row col 0110 == 500.0.

        Today FAILS: D row absent as grade label (guard returns 0.0).
        (E3 appears under "Default (100%)" label, not "D".)
        """
        actual = _extract_row(corp, GRADE_D, "0110")
        assert actual == pytest.approx(float(EXPECTED_D["0110"])), (  # type: ignore[arg-type]
            f"D row col 0110 expected {EXPECTED_D['0110']!r}, got {actual!r}. "
            "FAIL: grade-keyed D row absent (present as 'Default (100%)' bucket instead)."
        )

    def test_p420_d_row_pd(self, corp: pl.DataFrame) -> None:
        """D grade row weighted PD == 1.0 (col 0010).

        Arrange: grade-path fixture, E3 PD = 1.0.
        Act: generate C 08.02 (CRR).
        Assert: D row col 0010 == 1.0.

        Today FAILS: D row absent as grade label (guard returns 0.0).
        """
        actual = _extract_row(corp, GRADE_D, "0010")
        assert actual == pytest.approx(float(EXPECTED_D["0010"])), (  # type: ignore[arg-type]
            f"D row col 0010 expected {EXPECTED_D['0010']!r}, got {actual!r}."
        )

    def test_p420_d_row_maturity_days(self, corp: pl.DataFrame) -> None:
        """D grade row EW maturity == 365.0 days (col 0250 = 1.0 yr * 365).

        Arrange: grade-path fixture, E3 maturity = 1.0 yr.
        Act: generate C 08.02 (CRR).
        Assert: D row col 0250 == 365.0.

        Today FAILS: D row absent as grade label (guard returns 0.0).
        """
        actual = _extract_row(corp, GRADE_D, "0250")
        assert actual == pytest.approx(float(EXPECTED_D["0250"])), (  # type: ignore[arg-type]
            f"D row col 0250 expected {EXPECTED_D['0250']!r}, got {actual!r}."
        )

    # ------------------------------------------------------------------
    # Total EAD reconciliation
    # ------------------------------------------------------------------

    def test_p420_total_ead_reconciles(self, corp: pl.DataFrame) -> None:
        """Sum of EAD across all grade rows == 3500.0 (reconciles to C 08.01).

        Arrange: grade-path fixture, total EAD = 1000 + 2000 + 500 = 3500.
        Act: generate C 08.02 (CRR).
        Assert: Σ col 0110 == 3500.0.

        Today FAILS: only 2 rows present (0110 sums to 3500 numerically but
        row labels are wrong, so this passes numerically — caught by row-name tests).
        This serves as a belt-and-suspenders total check.
        """
        total_ead = corp["0110"].sum()
        assert total_ead == pytest.approx(EXPECTED_TOTAL_EAD), (
            f"Total EAD expected {EXPECTED_TOTAL_EAD!r}, got {total_ead!r}."
        )

    # ------------------------------------------------------------------
    # col 0005 == grade label (row_name == col 0005)
    # ------------------------------------------------------------------

    def test_p420_col_0005_equals_grade_label(self, corp: pl.DataFrame) -> None:
        """col 0005 (obligor grade identifier) equals the grade label.

        COREP Annex II requires col 0005 to carry the firm's obligor grade.

        Arrange: grade-path fixture.
        Act: generate C 08.02 (CRR).
        Assert: col 0005 set == {AAA, BB, D}.

        Today FAILS: col 0005 carries PD-band labels, not grade labels.
        """
        assert "0005" in corp.columns, "col 0005 (obligor grade identifier) missing"
        actual_0005_set = set(corp["0005"].to_list())
        assert actual_0005_set == EXPECTED_GRADE_SET, (
            f"col 0005 set expected {EXPECTED_GRADE_SET!r}, got {actual_0005_set!r}. "
            "FAIL: grade labels not propagated to col 0005."
        )


# =============================================================================
# GROUP 2 — Fallback path (no-regression pin; PASSES both before and after)
# =============================================================================
# When the grade column is absent the generator must reproduce the fixed-PD-bucket
# output byte-for-byte.  These assertions mirror the existing TestC0802 checks.
# =============================================================================


class TestP420FallbackPath:
    """GROUP 2 — fixed-PD-bucket fallback (passes before and after engine change)."""

    @pytest.fixture()
    def bundle(self) -> object:
        """Generate C 08.02 bundle from the existing _irb_results() fixture (CRR)."""
        gen = COREPGenerator()
        return gen.generate_from_lazyframe(_irb_results(), framework="CRR")

    @pytest.fixture()
    def corp(self, bundle: object) -> pl.DataFrame:
        """Extract the corporate C 08.02 DataFrame from the bundle."""
        return bundle.c08_02["corporate"]  # type: ignore[attr-defined]

    def test_p420_fallback_corporate_band_050_ead(self, corp: pl.DataFrame) -> None:
        """Fallback: corporate '0.50% - 0.75%' band EAD == 5500.0 (col 0110).

        Arrange: existing _irb_results() — no grade column.
        Act: generate C 08.02 (CRR).
        Assert: '0.50% - 0.75%' row col 0110 == 5500.0 (mirrors TestC0802 line 1322).

        Passes today; must continue to pass after engine change.
        """
        actual = _extract_row(corp, "0.50% - 0.75%", "0110")
        assert actual == pytest.approx(5500.0), (
            f"Fallback '0.50% - 0.75%' band EAD expected 5500.0, got {actual!r}."
        )

    def test_p420_fallback_corporate_band_050_pd(self, corp: pl.DataFrame) -> None:
        """Fallback: corporate '0.50% - 0.75%' band weighted PD == 0.005 (col 0010).

        Arrange: existing _irb_results() — no grade column.
        Act: generate C 08.02 (CRR).
        Assert: col 0010 == 0.005 (mirrors TestC0802 line 1335).

        Passes today; must continue to pass after engine change.
        """
        actual = _extract_row(corp, "0.50% - 0.75%", "0010")
        assert actual == pytest.approx(0.005), (
            f"Fallback '0.50% - 0.75%' band PD expected 0.005, got {actual!r}."
        )

    def test_p420_fallback_corporate_band_050_maturity(self, corp: pl.DataFrame) -> None:
        """Fallback: corporate '0.50% - 0.75%' band EW maturity == 912.5 days (col 0250).

        Arrange: existing _irb_results() — no grade column.
        Act: generate C 08.02 (CRR).
        Assert: col 0250 == 912.5 days (2.5 yr * 365 = mirrors TestC0802 line 1353).

        Passes today; must continue to pass after engine change.
        """
        actual = _extract_row(corp, "0.50% - 0.75%", "0250")
        assert actual == pytest.approx(2.5 * 365.0, rel=1e-4), (
            f"Fallback '0.50% - 0.75%' band maturity expected 912.5, got {actual!r}."
        )

    def test_p420_fallback_col_0005_present(self, corp: pl.DataFrame) -> None:
        """Fallback: col 0005 is present in the output DataFrame.

        Arrange: existing _irb_results() — no grade column.
        Act: generate C 08.02 (CRR).
        Assert: '0005' in corp.columns.

        Passes today; must continue to pass after engine change.
        """
        assert "0005" in corp.columns, "col 0005 missing from fallback output"

    def test_p420_fallback_row_names_are_pd_bands(self, corp: pl.DataFrame) -> None:
        """Fallback: row_names are PD-band labels, not grade labels.

        Confirms the fallback path preserves fixed-bucket behaviour.

        Arrange: existing _irb_results() — no grade column.
        Act: generate C 08.02 (CRR).
        Assert: '0.50% - 0.75%' row_name present; 'AAA'/'BB'/'D' absent.

        Passes today; must continue to pass after engine change.
        """
        names = _row_name_set(corp)
        assert "0.50% - 0.75%" in names, (
            f"Expected PD-band label '0.50% - 0.75%' in fallback row names, got {names!r}"
        )
        # Grade labels must NOT appear in the fallback output
        for grade in (GRADE_AAA, GRADE_BB, GRADE_D):
            assert grade not in names, (
                f"Grade label '{grade}' must not appear in fallback (no-grade) output."
            )
