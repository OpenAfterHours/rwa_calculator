"""Unit tests for P2.48: CR8 RWEA flow statement — opening + closing + residual.

Tests cover:
    - WITH prior period supplied (new optional ``previous_period_results`` param):
        * row 1 (opening) == 1_000_000  (derived from prior period IRB-only sum)
        * row 8 (Other)   == +150_000   (signed residual = closing - opening)
        * row 9 (closing) == 1_150_000  (current period IRB-only sum, unchanged)
        * reconciliation  row_1 + row_8 == row_9
        * rows 2-7        all None      (out-of-scope flow drivers)
    - Decrease control (snapshots swapped):
        * row 8 == -150_000 (negative = decrease in RWEA)
    - Backwards-compat (no prior period):
        * rows 1-8 all None  (existing behaviour, regression guard)
        * row 9 == 1_150_000 (unchanged)

The dominant pre-implementation failure is:

    assert opening == pytest.approx(1_000_000, abs=0.01)
    →  AssertionError: assert None == approx(1000000 ± 10.0)

This is a clean AssertionError — NOT TypeError from a missing kwarg — because the
generate_from_lazyframe call is guarded via ``inspect.signature``: if
``previous_period_results`` is not yet a known parameter, the generator is called
without it (rows 1-8 come back None) and the opening assertion fires.

References:
    - P2.48 scenario proposal: .claude/state/next-items-20260530-0519-P2.48-scenario.md
    - CR8 generator: src/rwa_calc/reporting/pillar3/generator.py:577-604 (_generate_cr8)
    - IRB filter:    src/rwa_calc/reporting/pillar3/generator.py:1101-1109 (_filter_irb_non_slotting)
    - CR8 template:  src/rwa_calc/reporting/pillar3/templates.py:508-522 (CR8_ROWS)
    - CRR Art. 438(h): CR8 RWEA flow statement disclosure obligation
    - PS1/26 Annex XXII §11: signed-delta convention (increase positive, decrease negative)
"""

from __future__ import annotations

import inspect

import polars as pl
import pytest

from rwa_calc.reporting.pillar3.generator import (
    Pillar3Generator,
    Pillar3TemplateBundle,
)
from tests.fixtures.p2_48.p2_48 import (
    EXPECTED_CLOSING,
    EXPECTED_CR8_HEIGHT,
    EXPECTED_OPENING,
    EXPECTED_ROW_8,
    EXPECTED_ROW_8_DECREASE,
    build_current_period_lf,
    build_prior_period_lf,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _build_bundle_with_prior() -> Pillar3TemplateBundle:
    """Generate a CR8 bundle with prior-period results supplied.

    Uses the inspect.signature guard: if ``previous_period_results`` does not
    yet exist as a parameter, call without it so rows 1-8 come back None and
    the opening assertion fires as a clean AssertionError (not TypeError).
    Once the engine-implementer adds the param, the full two-period path runs.
    """
    gen = Pillar3Generator()
    current_lf = build_current_period_lf()
    prior_lf = build_prior_period_lf()

    sig = inspect.signature(gen.generate_from_lazyframe)
    if "previous_period_results" in sig.parameters:
        return gen.generate_from_lazyframe(
            current_lf,
            framework="CRR",
            previous_period_results=prior_lf,
        )
    # Parameter not yet added — call without it; rows 1-8 come back None.
    # The opening assertion below will catch this as a clear AssertionError.
    return gen.generate_from_lazyframe(current_lf, framework="CRR")


def _build_bundle_decrease_control() -> Pillar3TemplateBundle:
    """Generate a CR8 bundle with snapshots swapped (decrease scenario).

    Prior = current period (opening = 1_150_000)
    Current = prior period (closing = 1_000_000)
    → row 8 = -150_000 (negative = decrease).
    """
    gen = Pillar3Generator()
    # Swap: prior gets current-period data, current gets prior-period data
    swapped_current_lf = build_prior_period_lf()
    swapped_prior_lf = build_current_period_lf()

    sig = inspect.signature(gen.generate_from_lazyframe)
    if "previous_period_results" in sig.parameters:
        return gen.generate_from_lazyframe(
            swapped_current_lf,
            framework="CRR",
            previous_period_results=swapped_prior_lf,
        )
    return gen.generate_from_lazyframe(swapped_current_lf, framework="CRR")


def _get_cr8_row(bundle: Pillar3TemplateBundle, row_ref: str) -> pl.DataFrame:
    """Return the single CR8 row matching row_ref, asserting exactly one result."""
    assert bundle.cr8 is not None, "CR8 must be generated"
    row = bundle.cr8.filter(pl.col("row_ref") == row_ref)
    assert row.height == 1, f"Expected exactly 1 CR8 row with ref '{row_ref}', got {row.height}"
    return row


# ---------------------------------------------------------------------------
# P2.48 — CR8 two-period flow (WITH prior period)
# ---------------------------------------------------------------------------


class TestP248CR8WithPriorPeriod:
    """CR8 template with prior-period snapshot: opening, residual, closing, reconciliation."""

    @pytest.fixture(scope="class")
    def bundle(self) -> Pillar3TemplateBundle:
        """Bundle generated with prior_period_results supplied."""
        return _build_bundle_with_prior()

    def test_p2_48_cr8_height_is_nine(self, bundle: Pillar3TemplateBundle) -> None:
        """CR8 must always contain exactly 9 rows regardless of period mode."""
        # Arrange
        assert bundle.cr8 is not None

        # Act
        height = bundle.cr8.height

        # Assert
        assert height == EXPECTED_CR8_HEIGHT, (
            f"CR8 must have {EXPECTED_CR8_HEIGHT} rows, got {height}"
        )

    def test_p2_48_cr8_opening_row1_equals_prior_irb_sum(
        self, bundle: Pillar3TemplateBundle
    ) -> None:
        """Row 1 (opening) must equal sum of IRB (non-slotting) rwa_final from prior period.

        Prior period: foundation_irb=600_000 + advanced_irb=400_000 = 1_000_000.
        Slotting row (250_000) must be excluded by _filter_irb_non_slotting.
        Today _generate_cr8 returns None for row 1 → AssertionError (None != 1_000_000).
        """
        # Arrange
        row = _get_cr8_row(bundle, "1")

        # Act
        opening = row["a"][0]

        # Assert
        assert opening == pytest.approx(EXPECTED_OPENING, abs=0.01), (
            f"CR8 row 1 (opening): expected {EXPECTED_OPENING:,.2f}, got {opening}"
        )

    def test_p2_48_cr8_row8_other_equals_signed_delta(self, bundle: Pillar3TemplateBundle) -> None:
        """Row 8 (Other) must equal closing − opening = +150_000 (positive = increase).

        Sign convention per PS1/26 Annex XXII §11: increases are positive.
        Today returns None → AssertionError (None != +150_000).
        """
        # Arrange
        row = _get_cr8_row(bundle, "8")

        # Act
        row_8 = row["a"][0]

        # Assert
        assert row_8 == pytest.approx(EXPECTED_ROW_8, abs=0.01), (
            f"CR8 row 8 (Other/residual): expected {EXPECTED_ROW_8:+,.2f}, got {row_8}"
        )

    def test_p2_48_cr8_closing_row9_equals_current_irb_sum(
        self, bundle: Pillar3TemplateBundle
    ) -> None:
        """Row 9 (closing) must equal sum of IRB rwa_final from current period.

        Current period: foundation_irb=720_000 + advanced_irb=430_000 = 1_150_000.
        This row is already populated by the existing implementation.
        """
        # Arrange
        row = _get_cr8_row(bundle, "9")

        # Act
        closing = row["a"][0]

        # Assert
        assert closing == pytest.approx(EXPECTED_CLOSING, abs=0.01), (
            f"CR8 row 9 (closing): expected {EXPECTED_CLOSING:,.2f}, got {closing}"
        )

    def test_p2_48_cr8_reconciliation_row1_plus_row8_equals_row9(
        self, bundle: Pillar3TemplateBundle
    ) -> None:
        """Reconciliation: opening + row_8 == closing (rows 2-7 are None = 0).

        This verifies the signed-delta arithmetic is self-consistent.
        Fails today because row_1 is None (None + something is not arithmetic).
        """
        # Arrange
        row_1 = _get_cr8_row(bundle, "1")["a"][0]
        row_8 = _get_cr8_row(bundle, "8")["a"][0]
        row_9 = _get_cr8_row(bundle, "9")["a"][0]

        # Act — all three must be non-null for arithmetic to work
        assert row_1 is not None, "Row 1 (opening) must not be None for reconciliation"
        assert row_8 is not None, "Row 8 (Other) must not be None for reconciliation"
        assert row_9 is not None, "Row 9 (closing) must not be None for reconciliation"
        reconciled = row_1 + row_8

        # Assert
        assert reconciled == pytest.approx(row_9, abs=0.01), (
            f"CR8 reconciliation: row_1 ({row_1:,.2f}) + row_8 ({row_8:+,.2f}) "
            f"= {reconciled:,.2f} but row_9 = {row_9:,.2f}"
        )

    def test_p2_48_cr8_rows_2_to_7_all_none(self, bundle: Pillar3TemplateBundle) -> None:
        """Rows 2-7 (per-driver flow components) must remain None (out of scope).

        These rows require exposure-level period-over-period lineage which is not
        available from two point-in-time snapshots.
        """
        # Arrange
        assert bundle.cr8 is not None
        driver_refs = ["2", "3", "4", "5", "6", "7"]

        for ref in driver_refs:
            # Act
            row = bundle.cr8.filter(pl.col("row_ref") == ref)
            assert row.height == 1, f"Expected exactly 1 row with ref '{ref}'"
            val = row["a"][0]

            # Assert
            assert val is None, (
                f"CR8 row {ref} (flow driver) must be None (out of scope), got {val}"
            )


# ---------------------------------------------------------------------------
# P2.48 — Decrease control (snapshots swapped)
# ---------------------------------------------------------------------------


class TestP248CR8DecreaseControl:
    """CR8 row 8 must be negative when RWEA has decreased period-over-period."""

    @pytest.fixture(scope="class")
    def bundle(self) -> Pillar3TemplateBundle:
        """Bundle with snapshots swapped: opening=1_150_000, closing=1_000_000."""
        return _build_bundle_decrease_control()

    def test_p2_48_cr8_row8_negative_for_decrease(self, bundle: Pillar3TemplateBundle) -> None:
        """Row 8 must be -150_000 when opening > closing (RWEA decreased).

        Sign convention: negative = decrease (PS1/26 Annex XXII §11).
        Today returns None → AssertionError.
        """
        # Arrange
        row = _get_cr8_row(bundle, "8")

        # Act
        row_8 = row["a"][0]

        # Assert
        assert row_8 == pytest.approx(EXPECTED_ROW_8_DECREASE, abs=0.01), (
            f"CR8 row 8 (decrease control): expected {EXPECTED_ROW_8_DECREASE:+,.2f}, got {row_8}"
        )


# ---------------------------------------------------------------------------
# P2.48 — Backwards-compatibility (no prior period supplied)
# ---------------------------------------------------------------------------


class TestP248CR8BackwardsCompat:
    """Regression guard: existing no-prior-period behaviour must be preserved."""

    @pytest.fixture(scope="class")
    def bundle(self) -> Pillar3TemplateBundle:
        """Bundle generated WITHOUT prior_period_results (current API, unchanged)."""
        gen = Pillar3Generator()
        return gen.generate_from_lazyframe(build_current_period_lf(), framework="CRR")

    def test_p2_48_cr8_closing_populated_without_prior(self, bundle: Pillar3TemplateBundle) -> None:
        """Row 9 (closing) must be populated even without prior period data.

        This is the existing behaviour and must not regress.
        """
        # Arrange
        row = _get_cr8_row(bundle, "9")

        # Act
        closing = row["a"][0]

        # Assert
        assert closing == pytest.approx(EXPECTED_CLOSING, abs=0.01), (
            f"CR8 row 9 (closing, no prior): expected {EXPECTED_CLOSING:,.2f}, got {closing}"
        )

    def test_p2_48_cr8_rows_1_to_8_null_without_prior(self, bundle: Pillar3TemplateBundle) -> None:
        """Rows 1-8 must all be None when no prior period is supplied.

        Backwards-compat: existing callers that don't pass previous_period_results
        must see no change in behaviour.
        """
        # Arrange
        assert bundle.cr8 is not None
        null_refs = ["1", "2", "3", "4", "5", "6", "7", "8"]

        for ref in null_refs:
            # Act
            row = bundle.cr8.filter(pl.col("row_ref") == ref)
            assert row.height == 1, f"Expected exactly 1 row with ref '{ref}'"
            val = row["a"][0]

            # Assert
            assert val is None, f"CR8 row {ref} must be None without prior period, got {val}"
