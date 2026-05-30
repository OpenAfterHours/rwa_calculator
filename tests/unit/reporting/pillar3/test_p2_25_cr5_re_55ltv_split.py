"""Unit tests for P2.25(b): CR5 bucketing of RE not-materially-dependent loan
that straddles the 55%-LTV split (Art. 124F / Art. 124L).

Tests cover:
    - B31 CR5 emits sub-row 9f (secured up-to-55%-LTV portion, 550,000 at 20%)
    - B31 CR5 emits sub-row 9g (above-55%-LTV residual portion, 450,000 at 75%)
    - 9f EAD lands in band-column "f" (20%), 9f Total == 550,000
    - 9g EAD lands in band-column "p" (75%), 9g Total == 450,000
    - 9f Total + 9g Total == parent EAD 1,000,000
    - Existing RE whole-class row 9 Total still == 1,000,000 (sub-rows are
      "of which" memo rows; NOT double-counted into grand Total row 17)
    - CRR CR5 is byte-identical to today (new logic gates on framework==BASEL_3_1)

The dominant pre-implementation failure (before the engine-implementer wave) is:

    row_9f = bundle.cr5.filter(pl.col("row_ref") == "9f")
    assert row_9f.height == 1  # <-- AssertionError: got 0

This gives a clean RED failure at an AssertionError, not an ImportError or
collection error.

References:
    - P2.25 scenario proposal: tmp/batch-20260530-1718/P2.25-scenario.md §3-4
    - P2.25 fixture builder: tmp/batch-20260530-1718/P2.25-fixture.md
    - Fixture module: tests/fixtures/p2_25/p2_25.py
    - CR5 generator: src/rwa_calc/reporting/pillar3/generator.py _generate_cr5
    - CR5 templates: src/rwa_calc/reporting/pillar3/templates.py B31_CR5_RISK_WEIGHTS
    - Art. 124F: RRE not-materially-dependent secured portion ≤ 55% of value → 20% RW
    - Art. 124L: residual portion → counterparty risk weight (natural person → 75%)
    - PRA PS1/26 Annex XX: UKB CR5 template instructions, RW band allocation

B31 CR5 column refs (28 risk-weight bands, zero-indexed via _letter_ref):
    index  5 → 0.20 (20%) → "f"  (secured row)
    index 15 → 0.75 (75%) → "p"  (residual row)
    index 28 → "ac" Other/Deducted
    index 29 → "ad" Total
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.pillar3.generator import (
    Pillar3Generator,
    Pillar3TemplateBundle,
)
from tests.fixtures.p2_25.p2_25 import (
    B31_COL_RESIDUAL,
    B31_COL_SECURED,
    CR5_ROW_9,
    CR5_ROW_9F,
    CR5_ROW_9G,
    CR5_TOTAL_ROW,
    EXPECTED_9F_BAND_F,
    EXPECTED_9F_TOTAL,
    EXPECTED_9G_BAND_P,
    EXPECTED_9G_TOTAL,
    EXPECTED_ROW_9_TOTAL,
    FRAMEWORK,
    PARENT_EAD,
    build_re_split_results_lf,
)

# ---------------------------------------------------------------------------
# B31 CR5 structural constants (derived from _build_cr5_columns / _letter_ref)
# ---------------------------------------------------------------------------

# B31 has 28 risk-weight bands (indices 0-27).
# Total column = _letter_ref(28+1) = _letter_ref(29) = "ad"
_B31_CR5_TOTAL_COL: str = "ad"

# CRR has 14 risk-weight bands. Total = _letter_ref(15) = "p"
_CRR_CR5_TOTAL_COL: str = "p"


# ---------------------------------------------------------------------------
# Shared pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def b31_bundle() -> Pillar3TemplateBundle:
    """Generate the Pillar3TemplateBundle from the RE-split seed frame (BASEL_3_1)."""
    gen = Pillar3Generator()
    lf = build_re_split_results_lf()
    return gen.generate_from_lazyframe(lf, framework=FRAMEWORK)


@pytest.fixture(scope="module")
def crr_bundle() -> Pillar3TemplateBundle:
    """Generate the Pillar3TemplateBundle from the RE-split seed frame (CRR)."""
    gen = Pillar3Generator()
    lf = build_re_split_results_lf()
    return gen.generate_from_lazyframe(lf, framework="CRR")


# ---------------------------------------------------------------------------
# Helper: extract a single CR5 row as a Polars DataFrame, defaulting to an
# empty frame (not a KeyError / IndexError) when the row is absent.
# ---------------------------------------------------------------------------


def _cr5_row(bundle: Pillar3TemplateBundle, row_ref: str) -> pl.DataFrame:
    """Return the CR5 row matching *row_ref*, or an empty DataFrame if absent."""
    assert bundle.cr5 is not None, "bundle.cr5 is None — generator did not produce CR5"
    return bundle.cr5.filter(pl.col("row_ref") == row_ref)


def _scalar(df: pl.DataFrame, col: str) -> float:
    """Extract a scalar float from a single-row DataFrame; returns 0.0 if row is missing."""
    if df.height == 0:
        return 0.0
    val = df[col][0]
    return float(val) if val is not None else 0.0


# ---------------------------------------------------------------------------
# P2.25(b) primary test class: B31 sub-row 9f (secured up-to-55%-LTV)
# ---------------------------------------------------------------------------


class TestP225Cr5Row9fSecured:
    """Sub-row 9f must carry the secured portion (EAD 550,000 at 20% → band 'f').

    Pre-implementation: row_ref "9f" does not exist in bundle.cr5, so
    _cr5_row() returns an empty frame (height 0), _scalar() returns 0.0,
    and the assert 0.0 == 550_000.0 fires as an AssertionError.
    """

    def test_p2_25_cr5_9f_row_is_present(self, b31_bundle: Pillar3TemplateBundle) -> None:
        """CR5 must contain a row with row_ref '9f' for the secured RE portion.

        Failure mode: assert 0 == 1  (height is 0 when row absent)
        """
        # Arrange / Act
        row = _cr5_row(b31_bundle, CR5_ROW_9F)

        # Assert
        assert row.height == 1, (
            f"CR5 must emit exactly one row with row_ref={CR5_ROW_9F!r} for the "
            f"RE secured-up-to-55%-LTV portion (Art. 124F); got height={row.height}. "
            "The _generate_cr5 RE-split bucketing for BASEL_3_1 is not yet implemented."
        )

    def test_p2_25_cr5_9f_band_f_equals_secured_ead(
        self, b31_bundle: Pillar3TemplateBundle
    ) -> None:
        """Row 9f, band column 'f' (20%) must equal the secured EAD 550,000.

        Failure mode: assert 0.0 == 550000.0  (row absent → _scalar returns 0.0)
        """
        # Arrange
        row = _cr5_row(b31_bundle, CR5_ROW_9F)

        # Act
        actual_band_f = _scalar(row, B31_COL_SECURED)

        # Assert
        assert actual_band_f == pytest.approx(EXPECTED_9F_BAND_F), (
            f"CR5 row {CR5_ROW_9F!r} band {B31_COL_SECURED!r} (20%): "
            f"expected {EXPECTED_9F_BAND_F:,.0f}, got {actual_band_f:,.0f}"
        )

    def test_p2_25_cr5_9f_total_equals_secured_ead(self, b31_bundle: Pillar3TemplateBundle) -> None:
        """Row 9f Total column ('ad') must equal the secured EAD 550,000.

        Failure mode: assert 0.0 == 550000.0  (row absent → _scalar returns 0.0)
        """
        # Arrange
        row = _cr5_row(b31_bundle, CR5_ROW_9F)

        # Act
        actual_total = _scalar(row, _B31_CR5_TOTAL_COL)

        # Assert
        assert actual_total == pytest.approx(EXPECTED_9F_TOTAL), (
            f"CR5 row {CR5_ROW_9F!r} Total ({_B31_CR5_TOTAL_COL!r}): "
            f"expected {EXPECTED_9F_TOTAL:,.0f}, got {actual_total:,.0f}"
        )


# ---------------------------------------------------------------------------
# P2.25(b) primary test class: B31 sub-row 9g (above-55%-LTV residual)
# ---------------------------------------------------------------------------


class TestP225Cr5Row9gResidual:
    """Sub-row 9g must carry the residual portion (EAD 450,000 at 75% → band 'p').

    Pre-implementation: row_ref "9g" does not exist in bundle.cr5.
    """

    def test_p2_25_cr5_9g_row_is_present(self, b31_bundle: Pillar3TemplateBundle) -> None:
        """CR5 must contain a row with row_ref '9g' for the residual RE portion.

        Failure mode: assert 0 == 1  (height is 0 when row absent)
        """
        # Arrange / Act
        row = _cr5_row(b31_bundle, CR5_ROW_9G)

        # Assert
        assert row.height == 1, (
            f"CR5 must emit exactly one row with row_ref={CR5_ROW_9G!r} for the "
            f"RE above-55%-LTV residual portion (Art. 124L); got height={row.height}. "
            "The _generate_cr5 RE-split bucketing for BASEL_3_1 is not yet implemented."
        )

    def test_p2_25_cr5_9g_band_p_equals_residual_ead(
        self, b31_bundle: Pillar3TemplateBundle
    ) -> None:
        """Row 9g, band column 'p' (75%) must equal the residual EAD 450,000.

        Failure mode: assert 0.0 == 450000.0  (row absent → _scalar returns 0.0)
        """
        # Arrange
        row = _cr5_row(b31_bundle, CR5_ROW_9G)

        # Act
        actual_band_p = _scalar(row, B31_COL_RESIDUAL)

        # Assert
        assert actual_band_p == pytest.approx(EXPECTED_9G_BAND_P), (
            f"CR5 row {CR5_ROW_9G!r} band {B31_COL_RESIDUAL!r} (75%): "
            f"expected {EXPECTED_9G_BAND_P:,.0f}, got {actual_band_p:,.0f}"
        )

    def test_p2_25_cr5_9g_total_equals_residual_ead(
        self, b31_bundle: Pillar3TemplateBundle
    ) -> None:
        """Row 9g Total column ('ad') must equal the residual EAD 450,000.

        Failure mode: assert 0.0 == 450000.0  (row absent → _scalar returns 0.0)
        """
        # Arrange
        row = _cr5_row(b31_bundle, CR5_ROW_9G)

        # Act
        actual_total = _scalar(row, _B31_CR5_TOTAL_COL)

        # Assert
        assert actual_total == pytest.approx(EXPECTED_9G_TOTAL), (
            f"CR5 row {CR5_ROW_9G!r} Total ({_B31_CR5_TOTAL_COL!r}): "
            f"expected {EXPECTED_9G_TOTAL:,.0f}, got {actual_total:,.0f}"
        )


# ---------------------------------------------------------------------------
# P2.25(b) reconciliation: 9f + 9g Total == parent EAD 1,000,000
# ---------------------------------------------------------------------------


class TestP225Cr5SubRowReconciliation:
    """9f Total + 9g Total must reconcile to the parent EAD."""

    def test_p2_25_cr5_9f_plus_9g_totals_equal_parent_ead(
        self, b31_bundle: Pillar3TemplateBundle
    ) -> None:
        """Sub-row totals must sum to 1,000,000 (= SECURED_EAD + RESIDUAL_EAD).

        Failure mode: assert 0.0 == 1000000.0
        """
        # Arrange
        row_9f = _cr5_row(b31_bundle, CR5_ROW_9F)
        row_9g = _cr5_row(b31_bundle, CR5_ROW_9G)

        # Act
        total_9f = _scalar(row_9f, _B31_CR5_TOTAL_COL)
        total_9g = _scalar(row_9g, _B31_CR5_TOTAL_COL)
        combined = total_9f + total_9g

        # Assert
        assert combined == pytest.approx(PARENT_EAD), (
            f"9f Total ({total_9f:,.0f}) + 9g Total ({total_9g:,.0f}) "
            f"= {combined:,.0f} must equal parent EAD {PARENT_EAD:,.0f}"
        )


# ---------------------------------------------------------------------------
# P2.25(b) no-regression: row 9 and grand total row 17 (of-which semantics)
# ---------------------------------------------------------------------------


class TestP225Cr5NoRegression:
    """Pin the of-which semantics: sub-rows must NOT be double-counted in row 17.

    These assertions are designed to PASS both before and after the engine change.
    They encode the invariant that sub-rows 9f/9g are memo "of-which" rows.
    """

    def test_p2_25_cr5_row_9_total_unchanged(self, b31_bundle: Pillar3TemplateBundle) -> None:
        """Row 9 (whole RE class) Total must still equal 1,000,000.

        Row 9 aggregates all RE exposures. Sub-rows 9f/9g are "of which" breakdowns
        that must not change the row 9 Total itself.
        """
        # Arrange
        row_9 = _cr5_row(b31_bundle, CR5_ROW_9)

        # Act
        actual_total = _scalar(row_9, _B31_CR5_TOTAL_COL)

        # Assert
        assert actual_total == pytest.approx(EXPECTED_ROW_9_TOTAL), (
            f"CR5 row {CR5_ROW_9!r} (whole RE class) Total: "
            f"expected {EXPECTED_ROW_9_TOTAL:,.0f}, got {actual_total:,.0f}. "
            "Sub-rows 9f/9g must not change the row 9 aggregate total."
        )

    def test_p2_25_cr5_grand_total_not_double_counted(
        self, b31_bundle: Pillar3TemplateBundle
    ) -> None:
        """Grand Total row 17 must equal parent EAD (sub-rows excluded from count).

        Sub-rows 9f/9g are "of which" memo rows. They must not be added to
        the grand total row 17 on top of what row 9 already contributes.
        """
        # Arrange
        row_17 = _cr5_row(b31_bundle, CR5_TOTAL_ROW)

        # Act
        actual_grand_total = _scalar(row_17, _B31_CR5_TOTAL_COL)

        # Assert — grand total must equal PARENT_EAD (1,000,000), not 2,000,000
        assert actual_grand_total == pytest.approx(PARENT_EAD), (
            f"CR5 grand Total row {CR5_TOTAL_ROW!r}: "
            f"expected {PARENT_EAD:,.0f}, got {actual_grand_total:,.0f}. "
            "Sub-rows 9f/9g must be excluded from the grand total accumulation."
        )


# ---------------------------------------------------------------------------
# P2.25(b) CRR gate: new logic is BASEL_3_1 only, CRR must be byte-identical
# ---------------------------------------------------------------------------


class TestP225Cr5CrrUnchanged:
    """CRR CR5 must not emit rows 9f or 9g — new bucketing is B31-only."""

    def test_p2_25_cr5_crr_no_9f_row(self, crr_bundle: Pillar3TemplateBundle) -> None:
        """CRR CR5 must have no row_ref '9f' — RE-split bucketing is BASEL_3_1 only."""
        # Arrange / Act
        row = _cr5_row(crr_bundle, CR5_ROW_9F)

        # Assert
        assert row.height == 0, (
            f"CRR CR5 must not contain row_ref={CR5_ROW_9F!r} — "
            f"RE-split bucketing is BASEL_3_1-only; got height={row.height}"
        )

    def test_p2_25_cr5_crr_no_9g_row(self, crr_bundle: Pillar3TemplateBundle) -> None:
        """CRR CR5 must have no row_ref '9g' — RE-split bucketing is BASEL_3_1 only."""
        # Arrange / Act
        row = _cr5_row(crr_bundle, CR5_ROW_9G)

        # Assert
        assert row.height == 0, (
            f"CRR CR5 must not contain row_ref={CR5_ROW_9G!r} — "
            f"RE-split bucketing is BASEL_3_1-only; got height={row.height}"
        )
