"""Unit tests for P2.29: OV1 equity sub-approach rows (11-14) + output-floor rows (26/27).

Tests cover:
    - Row 11: equity positions under IRB Transitional Approach (a=1600.0, c=128.0)
    - Row 12: equity investments in funds — look-through approach (a=1500.0, c=120.0)
    - Row 13: equity investments in funds — mandate-based approach (a=960.0, c=76.80)
    - Row 14: equity investments in funds — fall-back approach (a=6250.0, c=500.0)
    - Row 26: output floor multiplier (a=0.725, c=null)
    - Row 27: output floor adjustment (a=6250.0, c=null) — gated on parameter existence

The current generator returns null for all six rows (via _OV1_EXPLICIT_NULL_REFS).
These tests fail with AssertionError (not TypeError/ImportError) because:
    - Rows 11-14 and 26 are reachable from the seeded results LazyFrame alone;
      today _ov1_cell_values returns {"a": None} for refs in _OV1_EXPLICIT_NULL_REFS.
    - Row 27 requires a new output_floor_summary kwarg on generate_from_lazyframe;
      the test guards this path via inspect.signature so the file fails on
      rows 11-14/26 only (AssertionError) until the engine-implementer adds the param.

References:
    - P2.29 scenario proposal: tmp/batch-20260530-0032/P2.29-scenario.md
    - OV1 row labels: src/rwa_calc/reporting/pillar3/templates.py (B31_OV1_ROWS)
    - Current null stubs: src/rwa_calc/reporting/pillar3/generator.py:1009
    - PRA PS1/26 UKB OV1 template — Art. 438(d), App 17
"""

from __future__ import annotations

import inspect

import polars as pl
import pytest

from rwa_calc.reporting.pillar3.generator import (
    Pillar3Generator,
    Pillar3TemplateBundle,
)
from tests.fixtures.p2_29.p2_29 import (
    EXPECTED_ROW_11_A,
    EXPECTED_ROW_11_C,
    EXPECTED_ROW_12_A,
    EXPECTED_ROW_12_C,
    EXPECTED_ROW_13_A,
    EXPECTED_ROW_13_C,
    EXPECTED_ROW_14_A,
    EXPECTED_ROW_14_C,
    EXPECTED_ROW_26_A,
    EXPECTED_ROW_26_C,
    EXPECTED_ROW_27_A,
    EXPECTED_ROW_27_C,
    build_equity_results_lf,
    build_output_floor_summary,
)

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def b31_ov1_bundle() -> Pillar3TemplateBundle:
    """Generate the OV1 bundle from the equity-sub-approach seed frame.

    Uses generate_from_lazyframe with framework="BASEL_3_1".
    The output_floor_summary kwarg is passed only if generate_from_lazyframe
    already accepts it (guard via inspect.signature).
    """
    gen = Pillar3Generator()
    lf = build_equity_results_lf()

    sig = inspect.signature(gen.generate_from_lazyframe)
    if "output_floor_summary" in sig.parameters:
        return gen.generate_from_lazyframe(
            lf,
            framework="BASEL_3_1",
            output_floor_summary=build_output_floor_summary(),
        )
    # Parameter not yet added — call without it so rows 11-14/26 still run
    return gen.generate_from_lazyframe(lf, framework="BASEL_3_1")


@pytest.fixture(scope="module")
def ov1_df(b31_ov1_bundle: Pillar3TemplateBundle) -> pl.DataFrame:
    """Return the OV1 DataFrame, asserting it was generated."""
    assert b31_ov1_bundle.ov1 is not None, "OV1 must be generated for BASEL_3_1 framework"
    return b31_ov1_bundle.ov1


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _get_row(df: pl.DataFrame, row_ref: str) -> pl.DataFrame:
    """Return the single OV1 row with the given ref, asserting exactly one result."""
    row = df.filter(pl.col("row_ref") == row_ref)
    assert row.height == 1, f"Expected exactly 1 OV1 row with ref '{row_ref}', got {row.height}"
    return row


# ---------------------------------------------------------------------------
# P2.29 core assertions — equity sub-approach rows (11-14) + floor row (26)
# ---------------------------------------------------------------------------


class TestP229OV1EquityIrbTransitional:
    """Row 11: equity positions under IRB Transitional Approach."""

    def test_p2_29_ov1_row_11_col_a_irb_transitional_rwa(self, ov1_df: pl.DataFrame) -> None:
        """Row 11 column 'a' must equal the sum of rwa_final for
        approach_applied='equity' AND equity_transitional_approach='irb_transitional'.

        Today _OV1_EXPLICIT_NULL_REFS returns a=None, so this assertion fails.
        """
        # Arrange
        row = _get_row(ov1_df, "11")

        # Act
        a_val = row["a"][0]

        # Assert
        assert a_val == pytest.approx(EXPECTED_ROW_11_A, abs=0.01), (
            f"OV1 row 11 column 'a' (IRB Transitional equity RWEA): "
            f"expected {EXPECTED_ROW_11_A}, got {a_val}"
        )

    def test_p2_29_ov1_row_11_col_c_own_funds(self, ov1_df: pl.DataFrame) -> None:
        """Row 11 column 'c' must equal 8% of column 'a' (= 128.0)."""
        # Arrange
        row = _get_row(ov1_df, "11")

        # Act
        c_val = row["c"][0]

        # Assert
        assert c_val == pytest.approx(EXPECTED_ROW_11_C, abs=0.01), (
            f"OV1 row 11 column 'c' (own funds = 8% of a): "
            f"expected {EXPECTED_ROW_11_C}, got {c_val}"
        )


class TestP229OV1EquityLookThrough:
    """Row 12: equity investments in funds — look-through approach."""

    def test_p2_29_ov1_row_12_col_a_look_through_rwa(self, ov1_df: pl.DataFrame) -> None:
        """Row 12 column 'a' must equal sum of rwa_final for ciu_approach='look_through'.

        Today returns None; expected 1500.0.
        """
        # Arrange
        row = _get_row(ov1_df, "12")

        # Act
        a_val = row["a"][0]

        # Assert
        assert a_val == pytest.approx(EXPECTED_ROW_12_A, abs=0.01), (
            f"OV1 row 12 column 'a' (look-through equity RWEA): "
            f"expected {EXPECTED_ROW_12_A}, got {a_val}"
        )

    def test_p2_29_ov1_row_12_col_c_own_funds(self, ov1_df: pl.DataFrame) -> None:
        """Row 12 column 'c' must equal 8% of 1500.0 = 120.0."""
        # Arrange
        row = _get_row(ov1_df, "12")

        # Act
        c_val = row["c"][0]

        # Assert
        assert c_val == pytest.approx(EXPECTED_ROW_12_C, abs=0.01), (
            f"OV1 row 12 column 'c' (own funds = 8% of a): "
            f"expected {EXPECTED_ROW_12_C}, got {c_val}"
        )


class TestP229OV1EquityMandateBased:
    """Row 13: equity investments in funds — mandate-based approach."""

    def test_p2_29_ov1_row_13_col_a_mandate_based_rwa(self, ov1_df: pl.DataFrame) -> None:
        """Row 13 column 'a' must equal sum of rwa_final for ciu_approach='mandate_based'.

        Today returns None; expected 960.0.
        """
        # Arrange
        row = _get_row(ov1_df, "13")

        # Act
        a_val = row["a"][0]

        # Assert
        assert a_val == pytest.approx(EXPECTED_ROW_13_A, abs=0.01), (
            f"OV1 row 13 column 'a' (mandate-based equity RWEA): "
            f"expected {EXPECTED_ROW_13_A}, got {a_val}"
        )

    def test_p2_29_ov1_row_13_col_c_own_funds(self, ov1_df: pl.DataFrame) -> None:
        """Row 13 column 'c' must equal 8% of 960.0 = 76.80."""
        # Arrange
        row = _get_row(ov1_df, "13")

        # Act
        c_val = row["c"][0]

        # Assert
        assert c_val == pytest.approx(EXPECTED_ROW_13_C, abs=0.01), (
            f"OV1 row 13 column 'c' (own funds = 8% of a): "
            f"expected {EXPECTED_ROW_13_C}, got {c_val}"
        )


class TestP229OV1EquityFallBack:
    """Row 14: equity investments in funds — fall-back approach."""

    def test_p2_29_ov1_row_14_col_a_fallback_rwa(self, ov1_df: pl.DataFrame) -> None:
        """Row 14 column 'a' must equal sum of rwa_final for ciu_approach='fallback'.

        Today returns None; expected 6250.0.
        """
        # Arrange
        row = _get_row(ov1_df, "14")

        # Act
        a_val = row["a"][0]

        # Assert
        assert a_val == pytest.approx(EXPECTED_ROW_14_A, abs=0.01), (
            f"OV1 row 14 column 'a' (fall-back equity RWEA): "
            f"expected {EXPECTED_ROW_14_A}, got {a_val}"
        )

    def test_p2_29_ov1_row_14_col_c_own_funds(self, ov1_df: pl.DataFrame) -> None:
        """Row 14 column 'c' must equal 8% of 6250.0 = 500.0."""
        # Arrange
        row = _get_row(ov1_df, "14")

        # Act
        c_val = row["c"][0]

        # Assert
        assert c_val == pytest.approx(EXPECTED_ROW_14_C, abs=0.01), (
            f"OV1 row 14 column 'c' (own funds = 8% of a): "
            f"expected {EXPECTED_ROW_14_C}, got {c_val}"
        )


class TestP229OV1OutputFloorMultiplier:
    """Row 26: output floor multiplier (dimensionless ratio)."""

    def test_p2_29_ov1_row_26_col_a_floor_pct(self, ov1_df: pl.DataFrame) -> None:
        """Row 26 column 'a' must equal output_floor_pct from results frame (0.725).

        Today _OV1_EXPLICIT_NULL_REFS returns a=None; expected 0.725.
        """
        # Arrange
        row = _get_row(ov1_df, "26")

        # Act
        a_val = row["a"][0]

        # Assert
        assert a_val == pytest.approx(EXPECTED_ROW_26_A, abs=1e-6), (
            f"OV1 row 26 column 'a' (output floor multiplier): "
            f"expected {EXPECTED_ROW_26_A}, got {a_val}"
        )

    def test_p2_29_ov1_row_26_col_c_is_null(self, ov1_df: pl.DataFrame) -> None:
        """Row 26 column 'c' must remain null (ratio row — no own-funds shim)."""
        # Arrange
        row = _get_row(ov1_df, "26")

        # Act
        c_val = row["c"][0]

        # Assert
        assert c_val is EXPECTED_ROW_26_C, (
            f"OV1 row 26 column 'c': expected None (ratio — no shim), got {c_val}"
        )


# ---------------------------------------------------------------------------
# P2.29 row 27 — output floor adjustment (gated on new parameter)
# ---------------------------------------------------------------------------


class TestP229OV1OutputFloorAdjustment:
    """Row 27: output floor adjustment (OF-ADJ from OutputFloorSummary).

    This test is gated: if generate_from_lazyframe does not yet accept
    output_floor_summary, the row-27 assertions are skipped so the overall
    failure mode remains AssertionError (rows 11-14/26), not TypeError.
    After the engine-implementer adds the parameter, this class runs fully.
    """

    def test_p2_29_ov1_row_27_col_a_of_adj(self, ov1_df: pl.DataFrame) -> None:
        """Row 27 column 'a' must equal OutputFloorSummary.of_adj (= 6250.0).

        Skipped today because output_floor_summary kwarg does not exist yet.
        """
        # Arrange — check parameter gate
        gen = Pillar3Generator()
        sig = inspect.signature(gen.generate_from_lazyframe)
        if "output_floor_summary" not in sig.parameters:
            pytest.skip(
                "output_floor_summary parameter not yet added to generate_from_lazyframe; "
                "row-27 assertion deferred to post-implementation run"
            )

        # Re-generate with the floor summary now that we know the param exists
        lf = build_equity_results_lf()
        bundle_with_summary = gen.generate_from_lazyframe(
            lf,
            framework="BASEL_3_1",
            output_floor_summary=build_output_floor_summary(),
        )
        assert bundle_with_summary.ov1 is not None
        row = _get_row(bundle_with_summary.ov1, "27")

        # Act
        a_val = row["a"][0]

        # Assert
        assert a_val == pytest.approx(EXPECTED_ROW_27_A, abs=0.01), (
            f"OV1 row 27 column 'a' (OF-ADJ): expected {EXPECTED_ROW_27_A}, got {a_val}"
        )

    def test_p2_29_ov1_row_27_col_c_is_null(self, ov1_df: pl.DataFrame) -> None:
        """Row 27 column 'c' must remain null (adjustment — no own-funds shim).

        Skipped today because output_floor_summary kwarg does not exist yet.
        """
        # Arrange — check parameter gate
        gen = Pillar3Generator()
        sig = inspect.signature(gen.generate_from_lazyframe)
        if "output_floor_summary" not in sig.parameters:
            pytest.skip(
                "output_floor_summary parameter not yet added to generate_from_lazyframe; "
                "row-27 assertion deferred to post-implementation run"
            )

        lf = build_equity_results_lf()
        bundle_with_summary = gen.generate_from_lazyframe(
            lf,
            framework="BASEL_3_1",
            output_floor_summary=build_output_floor_summary(),
        )
        assert bundle_with_summary.ov1 is not None
        row = _get_row(bundle_with_summary.ov1, "27")

        # Act
        c_val = row["c"][0]

        # Assert
        assert c_val is EXPECTED_ROW_27_C, (
            f"OV1 row 27 column 'c': expected None (adjustment — no shim), got {c_val}"
        )


# ---------------------------------------------------------------------------
# Regression: row count and total-RWA invariants must not regress
# ---------------------------------------------------------------------------


class TestP229OV1Regression:
    """Regression guards: existing OV1 invariants must hold with equity-seeded data."""

    def test_p2_29_ov1_b31_row_count_unchanged(self, ov1_df: pl.DataFrame) -> None:
        """B31 OV1 must still contain exactly 20 rows (no new rows added)."""
        from rwa_calc.reporting.pillar3.templates import B31_OV1_ROWS

        # Arrange / Act
        actual_count = ov1_df.height

        # Assert
        assert actual_count == len(B31_OV1_ROWS), (
            f"B31 OV1 row count must remain {len(B31_OV1_ROWS)}, got {actual_count}"
        )

    def test_p2_29_ov1_row_29_total_rwa_matches_seed(self, ov1_df: pl.DataFrame) -> None:
        """Row 29 (total) must equal sum of all rwa_final in seed frame (10310.0).

        Equity sub-rows 11-14 are memo rows only — they must NOT add to the total.
        """
        # Arrange
        expected_total = 1600.0 + 1500.0 + 960.0 + 6250.0  # = 10310.0
        row_29 = _get_row(ov1_df, "29")

        # Act
        total_a = row_29["a"][0]

        # Assert
        assert total_a == pytest.approx(expected_total, abs=0.01), (
            f"OV1 row 29 (total RWA) must equal {expected_total} (sum of seed frame), "
            f"got {total_a}. Rows 11-14 are memo rows and must not double-count."
        )

    def test_p2_29_ov1_col_b_all_null(self, ov1_df: pl.DataFrame) -> None:
        """Column b (T-1) must remain fully null — no prior period data available."""
        # Arrange / Act
        null_count = ov1_df["b"].null_count()

        # Assert
        assert null_count == ov1_df.height, (
            f"Column 'b' must be all-null; got {ov1_df.height - null_count} non-null values"
        )
