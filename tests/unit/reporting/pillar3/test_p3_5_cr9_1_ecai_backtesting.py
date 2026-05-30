"""Unit tests for P3.5: CR9.1 ECAI-based PD back-testing generator.

Tests cover:
    - ``Pillar3TemplateBundle.cr9_1`` field populated for BASEL_3_1 framework
    - Key "advanced_irb - corporate_other_non_sme" produced by ``_generate_cr9_1``
      (P2.49 update: was "advanced_irb - corporate" before taxonomy extension)
    - Output height = 3 (2 grade rows + 1 total row)
    - Dynamic ECAI column "external_rating_equivalent" carries "A" / "BBB"
    - Per-row c/d/e/f/g/h values for R1 (grade "A"), R2 (grade "BBB"), Total
    - CRR gate: ``cr9_1`` is empty (CR9.1 is Basel 3.1 only)
    - Regression: existing ``cr9`` dict is not disturbed by the new generator

The dominant pre-implementation failure is an AssertionError produced by:

    cr9_1 = getattr(bundle, "cr9_1", None)
    assert cr9_1      # → AssertionError: None (field not yet on bundle)

This guarantees a clean RED fail — not AttributeError, ImportError, or
collection error.

References:
    - P3.5 scenario proposal: tmp/batch-20260530-0213/P3.5-scenario.md
    - P2.49 scenario proposal: CR9 taxonomy extension (5 F-IRB / 10 A-IRB leaves)
    - CR9.1 template definition: src/rwa_calc/reporting/pillar3/templates.py (CR9_1_COLUMNS)
    - CR9 generator (reference pattern): src/rwa_calc/reporting/pillar3/generator.py:604-703
    - PRA PS1/26 Art. 180(1)(f): ECAI-based PD estimation
    - PRA PS1/26 Annex XXII paras 12-15: CR9/CR9.1 back-testing instructions
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.pillar3.generator import (
    Pillar3Generator,
    Pillar3TemplateBundle,
)
from tests.fixtures.p3_5.p3_5 import (
    EXPECTED_DICT_KEY as _FIXTURE_EXPECTED_DICT_KEY,
)
from tests.fixtures.p3_5.p3_5 import (
    EXPECTED_HEIGHT,
    EXPECTED_R1_C,
    EXPECTED_R1_D,
    EXPECTED_R1_E,
    EXPECTED_R1_F,
    EXPECTED_R1_G,
    EXPECTED_R1_H,
    EXPECTED_R2_C,
    EXPECTED_R2_D,
    EXPECTED_R2_E,
    EXPECTED_R2_F,
    EXPECTED_R2_G,
    EXPECTED_R2_H,
    EXPECTED_TOT_C,
    EXPECTED_TOT_D,
    EXPECTED_TOT_E,
    EXPECTED_TOT_F,
    EXPECTED_TOT_G,
    EXPECTED_TOT_H,
    build_cr9_1_results_lf,
)

# ---------------------------------------------------------------------------
# P2.49 taxonomy update: shadow fixture constant with new leaf key.
#
# The P3.5 fixture was written before the P2.49 taxonomy extension.  After
# P2.49, the A-IRB "corporate" collapsed parent key is replaced by two leaf
# sub-class keys.  The P3.5 seed frame uses exposure_class="corporate" with
# is_sme=False / cp_is_financial_sector_entity absent, which routes to
# "advanced_irb - corporate_other_non_sme" under the new predicate logic.
#
# EXPECTED_DICT_KEY is redefined here (shadowing the imported fixture value
# "advanced_irb - corporate") so that all test lookups use the correct
# post-P2.49 key.  The fixture file itself is not modified — fixture-builder
# owns tests/fixtures/.
# ---------------------------------------------------------------------------
EXPECTED_DICT_KEY: str = "advanced_irb - corporate_other_non_sme"

# Keep reference to old fixture constant for diagnostic messages only
_LEGACY_EXPECTED_DICT_KEY: str = _FIXTURE_EXPECTED_DICT_KEY


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def b31_cr9_1_bundle() -> Pillar3TemplateBundle:
    """Generate the Pillar3TemplateBundle from the CR9.1 seed frame.

    Uses generate_from_lazyframe with framework="BASEL_3_1" — same calling
    convention as test_p2_29_ov1_equity_subapproach.py.
    """
    gen = Pillar3Generator()
    lf = build_cr9_1_results_lf()
    return gen.generate_from_lazyframe(lf, framework="BASEL_3_1")


@pytest.fixture(scope="module")
def crr_cr9_1_bundle() -> Pillar3TemplateBundle:
    """Generate the Pillar3TemplateBundle under CRR — cr9_1 must be empty."""
    gen = Pillar3Generator()
    lf = build_cr9_1_results_lf()
    return gen.generate_from_lazyframe(lf, framework="CRR")


# ---------------------------------------------------------------------------
# P3.5 primary test: cr9_1 field existence and key
# ---------------------------------------------------------------------------


class TestP35Cr91FieldExists:
    """``cr9_1`` must be a non-empty dict on the Pillar3TemplateBundle (B31 only).

    The getattr guard converts a missing field into None, which immediately
    fails the ``assert cr9_1`` as an AssertionError — not AttributeError.
    """

    def test_p3_5_cr9_1_field_is_non_empty_dict(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """``cr9_1`` must be a non-empty dict for BASEL_3_1 framework.

        Today the field does not exist on Pillar3TemplateBundle → getattr
        returns None → ``assert None`` → AssertionError (the load-bearing RED
        assertion).
        """
        # Arrange / Act
        cr9_1 = getattr(b31_cr9_1_bundle, "cr9_1", None)

        # Assert
        assert cr9_1, (
            "Pillar3TemplateBundle.cr9_1 must be a non-empty dict for BASEL_3_1; "
            f"got {cr9_1!r}. The cr9_1 field and _generate_cr9_1 are not yet implemented."
        )

    def test_p3_5_cr9_1_expected_dict_key_present(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """The key 'advanced_irb - corporate' must appear in cr9_1."""
        # Arrange
        cr9_1 = getattr(b31_cr9_1_bundle, "cr9_1", None)
        assert cr9_1, "cr9_1 not populated — see test_p3_5_cr9_1_field_is_non_empty_dict"

        # Act / Assert
        assert EXPECTED_DICT_KEY in cr9_1, (
            f"Expected key {EXPECTED_DICT_KEY!r} not found in cr9_1 keys: {list(cr9_1.keys())}"
        )

    def test_p3_5_cr9_1_output_height(self, b31_cr9_1_bundle: Pillar3TemplateBundle) -> None:
        """CR9.1 DataFrame for 'advanced_irb - corporate' must have height 3.

        2 grade rows (A, BBB) + 1 total row.
        """
        # Arrange
        cr9_1 = getattr(b31_cr9_1_bundle, "cr9_1", None)
        assert cr9_1, "cr9_1 not populated"
        assert EXPECTED_DICT_KEY in cr9_1, f"Key {EXPECTED_DICT_KEY!r} missing"

        # Act
        df = cr9_1[EXPECTED_DICT_KEY]
        actual_height = df.height

        # Assert
        assert actual_height == EXPECTED_HEIGHT, (
            f"CR9.1 '{EXPECTED_DICT_KEY}' must have {EXPECTED_HEIGHT} rows "
            f"(2 grade rows + 1 total), got {actual_height}"
        )


# ---------------------------------------------------------------------------
# P3.5 ECAI column content
# ---------------------------------------------------------------------------


class TestP35Cr91EcaiColumn:
    """The dynamic ECAI column must carry 'A' on R1 and 'BBB' on R2."""

    def test_p3_5_cr9_1_ecai_column_grade_a_present(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """Grade 'A' must appear in the external_rating_equivalent column."""
        # Arrange
        cr9_1 = getattr(b31_cr9_1_bundle, "cr9_1", None)
        assert cr9_1, "cr9_1 not populated"
        assert EXPECTED_DICT_KEY in cr9_1, f"Key {EXPECTED_DICT_KEY!r} missing"
        df = cr9_1[EXPECTED_DICT_KEY]

        # Act
        # The ECAI column is named "external_rating_equivalent" or "b" (PD range / grade)
        ecai_vals = _get_grade_column_values(df)

        # Assert
        assert "A" in ecai_vals, f"Grade 'A' must appear in CR9.1 grade column; found: {ecai_vals}"

    def test_p3_5_cr9_1_ecai_column_grade_bbb_present(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """Grade 'BBB' must appear in the external_rating_equivalent column."""
        # Arrange
        cr9_1 = getattr(b31_cr9_1_bundle, "cr9_1", None)
        assert cr9_1, "cr9_1 not populated"
        assert EXPECTED_DICT_KEY in cr9_1, f"Key {EXPECTED_DICT_KEY!r} missing"
        df = cr9_1[EXPECTED_DICT_KEY]

        # Act
        ecai_vals = _get_grade_column_values(df)

        # Assert
        assert "BBB" in ecai_vals, (
            f"Grade 'BBB' must appear in CR9.1 grade column; found: {ecai_vals}"
        )


# ---------------------------------------------------------------------------
# P3.5 per-row value assertions: R1 (grade "A")
# ---------------------------------------------------------------------------


class TestP35Cr91RowR1GradeA:
    """Per-column values for the grade-'A' row (R1)."""

    def test_p3_5_cr9_1_r1_col_c_obligor_count(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """R1 col c: 3 unique obligors in grade 'A'."""
        # Arrange
        row = _get_ecai_row(b31_cr9_1_bundle, "A")

        # Act
        actual = row["c"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_R1_C, abs=0.01), (
            f"R1 col c (obligor count): expected {EXPECTED_R1_C}, got {actual}"
        )

    def test_p3_5_cr9_1_r1_col_d_default_count(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """R1 col d: 1 defaulted obligor in grade 'A'."""
        # Arrange
        row = _get_ecai_row(b31_cr9_1_bundle, "A")

        # Act
        actual = row["d"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_R1_D, abs=0.01), (
            f"R1 col d (defaults): expected {EXPECTED_R1_D}, got {actual}"
        )

    def test_p3_5_cr9_1_r1_col_e_observed_dr(self, b31_cr9_1_bundle: Pillar3TemplateBundle) -> None:
        """R1 col e: observed average DR = 1/3 × 100 ≈ 33.3333%."""
        # Arrange
        row = _get_ecai_row(b31_cr9_1_bundle, "A")

        # Act
        actual = row["e"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_R1_E, abs=0.001), (
            f"R1 col e (observed DR %): expected {EXPECTED_R1_E:.4f}, got {actual}"
        )

    def test_p3_5_cr9_1_r1_col_f_ead_weighted_pd(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """R1 col f: EAD-weighted PD = 0.45%."""
        # Arrange
        row = _get_ecai_row(b31_cr9_1_bundle, "A")

        # Act
        actual = row["f"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_R1_F, abs=0.001), (
            f"R1 col f (EAD-wt PD %): expected {EXPECTED_R1_F}, got {actual}"
        )

    def test_p3_5_cr9_1_r1_col_g_arithmetic_avg_pd(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """R1 col g: arithmetic average PD ≈ 0.43333%."""
        # Arrange
        row = _get_ecai_row(b31_cr9_1_bundle, "A")

        # Act
        actual = row["g"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_R1_G, abs=0.001), (
            f"R1 col g (avg PD %): expected {EXPECTED_R1_G:.5f}, got {actual}"
        )

    def test_p3_5_cr9_1_r1_col_h_historical_dr(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """R1 col h: historical DR falls back to observed rate ≈ 33.3333%."""
        # Arrange
        row = _get_ecai_row(b31_cr9_1_bundle, "A")

        # Act
        actual = row["h"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_R1_H, abs=0.001), (
            f"R1 col h (historical DR %): expected {EXPECTED_R1_H:.4f}, got {actual}"
        )


# ---------------------------------------------------------------------------
# P3.5 per-row value assertions: R2 (grade "BBB")
# ---------------------------------------------------------------------------


class TestP35Cr91RowR2GradeBBB:
    """Per-column values for the grade-'BBB' row (R2)."""

    def test_p3_5_cr9_1_r2_col_c_obligor_count(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """R2 col c: 2 unique obligors in grade 'BBB'."""
        # Arrange
        row = _get_ecai_row(b31_cr9_1_bundle, "BBB")

        # Act
        actual = row["c"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_R2_C, abs=0.01), (
            f"R2 col c (obligor count): expected {EXPECTED_R2_C}, got {actual}"
        )

    def test_p3_5_cr9_1_r2_col_d_default_count(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """R2 col d: 0 defaults in grade 'BBB'."""
        # Arrange
        row = _get_ecai_row(b31_cr9_1_bundle, "BBB")

        # Act
        actual = row["d"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_R2_D, abs=0.01), (
            f"R2 col d (defaults): expected {EXPECTED_R2_D}, got {actual}"
        )

    def test_p3_5_cr9_1_r2_col_e_observed_dr(self, b31_cr9_1_bundle: Pillar3TemplateBundle) -> None:
        """R2 col e: observed average DR = 0.0%."""
        # Arrange
        row = _get_ecai_row(b31_cr9_1_bundle, "BBB")

        # Act
        actual = row["e"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_R2_E, abs=0.001), (
            f"R2 col e (observed DR %): expected {EXPECTED_R2_E}, got {actual}"
        )

    def test_p3_5_cr9_1_r2_col_f_ead_weighted_pd(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """R2 col f: EAD-weighted PD = 2.0%."""
        # Arrange
        row = _get_ecai_row(b31_cr9_1_bundle, "BBB")

        # Act
        actual = row["f"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_R2_F, abs=0.001), (
            f"R2 col f (EAD-wt PD %): expected {EXPECTED_R2_F}, got {actual}"
        )

    def test_p3_5_cr9_1_r2_col_g_arithmetic_avg_pd(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """R2 col g: arithmetic average PD = 2.0%."""
        # Arrange
        row = _get_ecai_row(b31_cr9_1_bundle, "BBB")

        # Act
        actual = row["g"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_R2_G, abs=0.001), (
            f"R2 col g (avg PD %): expected {EXPECTED_R2_G}, got {actual}"
        )

    def test_p3_5_cr9_1_r2_col_h_historical_dr(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """R2 col h: historical DR falls back to observed rate = 0.0%."""
        # Arrange
        row = _get_ecai_row(b31_cr9_1_bundle, "BBB")

        # Act
        actual = row["h"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_R2_H, abs=0.001), (
            f"R2 col h (historical DR %): expected {EXPECTED_R2_H}, got {actual}"
        )


# ---------------------------------------------------------------------------
# P3.5 per-row value assertions: Total row
# ---------------------------------------------------------------------------


class TestP35Cr91TotalRow:
    """Per-column values for the aggregate Total row (all 5 obligors)."""

    def test_p3_5_cr9_1_total_col_c_obligor_count(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """Total col c: 5 unique obligors across all grades."""
        # Arrange
        row = _get_total_row(b31_cr9_1_bundle)

        # Act
        actual = row["c"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_TOT_C, abs=0.01), (
            f"Total col c (obligor count): expected {EXPECTED_TOT_C}, got {actual}"
        )

    def test_p3_5_cr9_1_total_col_d_default_count(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """Total col d: 1 default across all grades."""
        # Arrange
        row = _get_total_row(b31_cr9_1_bundle)

        # Act
        actual = row["d"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_TOT_D, abs=0.01), (
            f"Total col d (defaults): expected {EXPECTED_TOT_D}, got {actual}"
        )

    def test_p3_5_cr9_1_total_col_e_observed_dr(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """Total col e: observed average DR = 1/5 × 100 = 20.0%."""
        # Arrange
        row = _get_total_row(b31_cr9_1_bundle)

        # Act
        actual = row["e"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_TOT_E, abs=0.001), (
            f"Total col e (observed DR %): expected {EXPECTED_TOT_E}, got {actual}"
        )

    def test_p3_5_cr9_1_total_col_f_ead_weighted_pd(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """Total col f: EAD-weighted PD ≈ 0.96667%."""
        # Arrange
        row = _get_total_row(b31_cr9_1_bundle)

        # Act
        actual = row["f"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_TOT_F, rel=1e-4), (
            f"Total col f (EAD-wt PD %): expected {EXPECTED_TOT_F:.5f}, got {actual}"
        )

    def test_p3_5_cr9_1_total_col_g_arithmetic_avg_pd(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """Total col g: arithmetic average PD = 1.06%."""
        # Arrange
        row = _get_total_row(b31_cr9_1_bundle)

        # Act
        actual = row["g"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_TOT_G, abs=0.001), (
            f"Total col g (avg PD %): expected {EXPECTED_TOT_G}, got {actual}"
        )

    def test_p3_5_cr9_1_total_col_h_historical_dr(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """Total col h: historical DR falls back to observed rate = 20.0%."""
        # Arrange
        row = _get_total_row(b31_cr9_1_bundle)

        # Act
        actual = row["h"][0]

        # Assert
        assert actual == pytest.approx(EXPECTED_TOT_H, abs=0.001), (
            f"Total col h (historical DR %): expected {EXPECTED_TOT_H}, got {actual}"
        )


# ---------------------------------------------------------------------------
# P3.5 framework gate: CRR → cr9_1 must be empty
# ---------------------------------------------------------------------------


class TestP35Cr91CrrFrameworkGate:
    """CR9.1 is Basel 3.1 only — CRR framework must produce an empty cr9_1."""

    def test_p3_5_cr9_1_crr_produces_empty_dict(
        self, crr_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """CRR framework must produce an empty (falsy) cr9_1.

        Pre-implementation: getattr returns None (falsy) → assert passes
        (the guard logic already treats absence as empty).
        Post-implementation: field is present but set to {} → also falsy.
        The assertion is that CRR never returns a non-empty cr9_1.
        """
        # Arrange / Act
        cr9_1 = getattr(crr_cr9_1_bundle, "cr9_1", {})

        # Assert
        assert not cr9_1, (
            f"CRR framework must produce empty cr9_1 (CR9.1 is B31-only); got {cr9_1!r}"
        )


# ---------------------------------------------------------------------------
# P3.5 regression: existing cr9 dict must not be disturbed
# ---------------------------------------------------------------------------


class TestP35Cr9Regression:
    """Existing CR9 generation must continue to work alongside the new CR9.1."""

    def test_p3_5_cr9_still_populated_for_b31(
        self, b31_cr9_1_bundle: Pillar3TemplateBundle
    ) -> None:
        """``bundle.cr9`` must be a non-empty dict for BASEL_3_1.

        The CR9 and CR9.1 generators are independent — adding cr9_1 must not
        break the existing cr9 dict.

        Pre-implementation: this test passes (cr9 is already implemented).
        """
        # Arrange / Act
        cr9 = b31_cr9_1_bundle.cr9

        # Assert
        assert cr9, (
            "bundle.cr9 must be non-empty for BASEL_3_1 with the P3.5 seed frame; "
            f"got {cr9!r}. The new _generate_cr9_1 must not break the existing cr9."
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_cr9_1_df(bundle: Pillar3TemplateBundle) -> pl.DataFrame:
    """Return the CR9.1 DataFrame for EXPECTED_DICT_KEY, with guard assertions."""
    cr9_1 = getattr(bundle, "cr9_1", None)
    assert cr9_1, "cr9_1 not populated — field or generator not yet implemented"
    assert EXPECTED_DICT_KEY in cr9_1, (
        f"Expected key {EXPECTED_DICT_KEY!r} not in cr9_1: {list(cr9_1.keys())}"
    )
    return cr9_1[EXPECTED_DICT_KEY]


def _get_grade_column_values(df: pl.DataFrame) -> list[str | None]:
    """Return values from the ECAI grade column.

    The column may be named "external_rating_equivalent" or "b" (PD range/grade).
    Tries "external_rating_equivalent" first, falls back to "b".
    """
    if "external_rating_equivalent" in df.columns:
        return df["external_rating_equivalent"].to_list()
    if "b" in df.columns:
        return df["b"].to_list()
    return []


def _get_ecai_row(bundle: Pillar3TemplateBundle, grade: str) -> pl.DataFrame:
    """Return the single CR9.1 row matching the given ECAI grade label."""
    df = _get_cr9_1_df(bundle)
    ecai_col = "external_rating_equivalent" if "external_rating_equivalent" in df.columns else "b"
    row = df.filter(pl.col(ecai_col) == grade)
    assert row.height == 1, (
        f"Expected exactly 1 CR9.1 row for grade {grade!r}, got {row.height}. "
        f"Available grades: {df[ecai_col].to_list()}"
    )
    return row


def _get_total_row(bundle: Pillar3TemplateBundle) -> pl.DataFrame:
    """Return the Total aggregate row from the CR9.1 DataFrame.

    The total row is identified by the 'row_ref' column == "Total" or by
    being the last row when no 'row_ref' column exists.
    """
    df = _get_cr9_1_df(bundle)
    if "row_ref" in df.columns:
        total = df.filter(pl.col("row_ref") == "Total")
        if total.height == 1:
            return total

    # Fall back: last row (total is always appended last in CR9 generation)
    return df.tail(1)
