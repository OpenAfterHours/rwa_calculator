"""
P2.48 fixture builder: CR8 RWEA-flow statement — two-period snapshot seed frames.

Pipeline position (reporting path):
    prior_period_lf (T-1) + current_period_lf (T)
        -> Pillar3Generator.generate_from_lazyframe(
               results=current_period_lf,
               previous_period_results=prior_period_lf,
           )
        -> Pillar3TemplateBundle.cr8 (9-row, column "a")

Scenario design (P2.48 — CRR Part 8 Art. 438(h) / PS1/26 UKB CR8):

    CR8 is the "RWEA flow statements for IRB credit-risk exposures" template.
    It requires TWO result snapshots to populate:

        Row 1  (opening)  — derived from prior period via _filter_irb_non_slotting + _col_sum
        Rows 2-7          — per-driver flow components (out of scope; stay None)
        Row 8  (Other)    — residual = closing - opening - sum(rows 2-7)
        Row 9  (closing)  — derived from current period via same filter + sum

    _filter_irb_non_slotting keeps only approach_applied in
    {"foundation_irb", "advanced_irb"} — slotting rows are excluded from CR8.

    Two-period snapshot (hand-calculated):

        Prior (T-1) — previous_period_results:
            EXP-FIRB-01   foundation_irb   rwa_final = 600_000.00
            EXP-AIRB-01   advanced_irb     rwa_final = 400_000.00
            EXP-SLOT-01   slotting         rwa_final = 250_000.00  <-- excluded by filter
          opening (row 1) = 600_000 + 400_000 = 1_000_000.00

        Current (T) — results:
            EXP-FIRB-02   foundation_irb   rwa_final = 720_000.00
            EXP-AIRB-02   advanced_irb     rwa_final = 430_000.00
            EXP-SLOT-02   slotting         rwa_final = 300_000.00  <-- excluded by filter
          closing (row 9) = 720_000 + 430_000 = 1_150_000.00

        Rows 2-7 = None (out of scope).
        Row 8 Other = closing - opening = 1_150_000 - 1_000_000 = +150_000.00 (increase).

        Reconciliation: row_1 + row_8 == row_9
                        1_000_000 + 150_000 == 1_150_000  ✓

    Decrease control (snapshots swapped):
        opening = 1_150_000, closing = 1_000_000
        row 8 = 1_000_000 - 1_150_000 = -150_000.00 (negative = decrease)

    Sign convention (PS1/26 Annex XXII §11):
        Positive = increase in RWEA (row 8 = +150_000).
        Negative = decrease in RWEA (decrease-control row 8 = -150_000).

    Backwards-compat (previous_period_results=None):
        Rows 1-8 must remain None; row 9 = 1_150_000.00 (existing behaviour).

Column names consumed by _generate_cr8 / _filter_irb_non_slotting / _col_sum:
    approach_applied  (str)  — filter values: "foundation_irb", "advanced_irb", "slotting"
    rwa_final         (f64)  — summed by _col_sum(data, rwa_col) after filter

Usage (clean-import check):
    cd /path/to/worktrees/P2.48
    PYTHONPATH=src /path/to/.venv/bin/python tests/fixtures/p2_48/p2_48.py

References:
    - CR8 generator:      src/rwa_calc/reporting/pillar3/generator.py:577-604 (_generate_cr8)
    - IRB filter:         src/rwa_calc/reporting/pillar3/generator.py:1101-1109 (_filter_irb_non_slotting)
    - Column-sum helper:  src/rwa_calc/reporting/pillar3/generator.py:1013-1018 (_col_sum)
    - CR8 template:       src/rwa_calc/reporting/pillar3/templates.py:508-522 (CR8_ROWS, CR8_COLUMNS)
    - CRR Art. 438(h):    CR8 RWEA flow statement disclosure obligation
    - PS1/26 Annex XXII §11: signed-delta convention (increase positive, decrease negative)
"""

from __future__ import annotations

import polars as pl

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

SCENARIO_ID: str = "P2.48"

# Framework — CR8 has the same 9-row structure under both CRR and BASEL_3_1
FRAMEWORK: str = "CRR"

# ---------------------------------------------------------------------------
# Prior period (T-1) — used to derive opening (row 1)
# ---------------------------------------------------------------------------

# IRB rows (included by _filter_irb_non_slotting)
PRIOR_FIRB_RWA: float = 600_000.00
PRIOR_AIRB_RWA: float = 400_000.00

# Slotting row (excluded by _filter_irb_non_slotting — must not affect row 1)
PRIOR_SLOTTING_RWA: float = 250_000.00

# Expected opening balance (row 1) = FIRB + AIRB only
EXPECTED_OPENING: float = PRIOR_FIRB_RWA + PRIOR_AIRB_RWA  # 1_000_000.00

# ---------------------------------------------------------------------------
# Current period (T) — used to derive closing (row 9)
# ---------------------------------------------------------------------------

# IRB rows (included by _filter_irb_non_slotting)
CURRENT_FIRB_RWA: float = 720_000.00
CURRENT_AIRB_RWA: float = 430_000.00

# Slotting row (excluded by _filter_irb_non_slotting — must not affect row 9)
CURRENT_SLOTTING_RWA: float = 300_000.00

# Expected closing balance (row 9) = FIRB + AIRB only
EXPECTED_CLOSING: float = CURRENT_FIRB_RWA + CURRENT_AIRB_RWA  # 1_150_000.00

# ---------------------------------------------------------------------------
# Derived flow values
# ---------------------------------------------------------------------------

# Row 8 Other = closing - opening (rows 2-7 are all None / 0)
# Positive means increase in RWEA (PS1/26 Annex XXII §11 sign convention)
EXPECTED_ROW_8: float = EXPECTED_CLOSING - EXPECTED_OPENING  # +150_000.00

# Decrease-control variant (snapshots swapped): opening=1_150_000, closing=1_000_000
EXPECTED_ROW_8_DECREASE: float = EXPECTED_OPENING - EXPECTED_CLOSING  # -150_000.00

# Total CR8 rows
EXPECTED_CR8_HEIGHT: int = 9  # 9-row template (rows 1-9)


# ---------------------------------------------------------------------------
# Public factories
# ---------------------------------------------------------------------------


def build_prior_period_lf() -> pl.LazyFrame:
    """Return a seeded results LazyFrame representing the prior period (T-1).

    Three rows — two IRB approaches (foundation_irb, advanced_irb) plus one
    slotting row.  _filter_irb_non_slotting will retain only the IRB rows when
    computing the opening balance (row 1), so slotting is deliberately included
    to verify it is excluded from the CR8 opening sum.

    Columns consumed by _generate_cr8 / _filter_irb_non_slotting / _col_sum:
        approach_applied  — approach discriminator (String)
        rwa_final         — RWA value (Float64)
    """
    rows = [
        {
            "exposure_id": "EXP-FIRB-01",
            "approach_applied": "foundation_irb",
            "rwa_final": PRIOR_FIRB_RWA,
        },
        {
            "exposure_id": "EXP-AIRB-01",
            "approach_applied": "advanced_irb",
            "rwa_final": PRIOR_AIRB_RWA,
        },
        {
            "exposure_id": "EXP-SLOT-01",
            "approach_applied": "slotting",
            "rwa_final": PRIOR_SLOTTING_RWA,
        },
    ]
    schema = {
        "exposure_id": pl.Utf8,
        "approach_applied": pl.Utf8,
        "rwa_final": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema).lazy()


def build_current_period_lf() -> pl.LazyFrame:
    """Return a seeded results LazyFrame representing the current period (T).

    Three rows — two IRB approaches (foundation_irb, advanced_irb) plus one
    slotting row.  _filter_irb_non_slotting will retain only the IRB rows when
    computing the closing balance (row 9), so slotting is deliberately included
    to verify it is excluded from the CR8 closing sum.

    This is also the frame passed as the primary ``results`` argument to
    ``generate_from_lazyframe``; the generator filters it internally to derive
    the closing balance.

    Columns consumed by _generate_cr8 / _filter_irb_non_slotting / _col_sum:
        approach_applied  — approach discriminator (String)
        rwa_final         — RWA value (Float64)
    """
    rows = [
        {
            "exposure_id": "EXP-FIRB-02",
            "approach_applied": "foundation_irb",
            "rwa_final": CURRENT_FIRB_RWA,
        },
        {
            "exposure_id": "EXP-AIRB-02",
            "approach_applied": "advanced_irb",
            "rwa_final": CURRENT_AIRB_RWA,
        },
        {
            "exposure_id": "EXP-SLOT-02",
            "approach_applied": "slotting",
            "rwa_final": CURRENT_SLOTTING_RWA,
        },
    ]
    schema = {
        "exposure_id": pl.Utf8,
        "approach_applied": pl.Utf8,
        "rwa_final": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema).lazy()


# ---------------------------------------------------------------------------
# Self-check (also serves as clean-import verification)
# ---------------------------------------------------------------------------


def _verify_lfs() -> None:
    """Verify both LazyFrames build and have the expected shape and content."""
    prior_df = build_prior_period_lf().collect()
    current_df = build_current_period_lf().collect()

    assert prior_df.height == 3, f"Prior period: expected 3 rows, got {prior_df.height}"
    assert current_df.height == 3, f"Current period: expected 3 rows, got {current_df.height}"

    expected_cols = {"exposure_id", "approach_applied", "rwa_final"}
    assert expected_cols.issubset(set(prior_df.columns)), (
        f"Prior period missing columns: {expected_cols - set(prior_df.columns)}"
    )
    assert expected_cols.issubset(set(current_df.columns)), (
        f"Current period missing columns: {expected_cols - set(current_df.columns)}"
    )

    # Verify approach distribution in prior period
    prior_approaches = set(prior_df["approach_applied"].to_list())
    assert prior_approaches == {"foundation_irb", "advanced_irb", "slotting"}, (
        f"Prior period approaches unexpected: {prior_approaches}"
    )

    # Verify approach distribution in current period
    current_approaches = set(current_df["approach_applied"].to_list())
    assert current_approaches == {"foundation_irb", "advanced_irb", "slotting"}, (
        f"Current period approaches unexpected: {current_approaches}"
    )


def _verify_irb_filter() -> None:
    """Verify _filter_irb_non_slotting logic on both frames matches expected sums."""
    irb_approaches = ["foundation_irb", "advanced_irb"]

    prior_df = build_prior_period_lf().collect()
    prior_irb = prior_df.filter(pl.col("approach_applied").is_in(irb_approaches))
    computed_opening = float(prior_irb["rwa_final"].sum())
    assert abs(computed_opening - EXPECTED_OPENING) < 1e-6, (
        f"Opening mismatch: computed={computed_opening}, expected={EXPECTED_OPENING}"
    )

    current_df = build_current_period_lf().collect()
    current_irb = current_df.filter(pl.col("approach_applied").is_in(irb_approaches))
    computed_closing = float(current_irb["rwa_final"].sum())
    assert abs(computed_closing - EXPECTED_CLOSING) < 1e-6, (
        f"Closing mismatch: computed={computed_closing}, expected={EXPECTED_CLOSING}"
    )


def _verify_constants() -> None:
    """Verify expected-value constants are internally consistent."""
    assert abs(EXPECTED_OPENING - 1_000_000.0) < 1e-6, (
        f"Opening constant incorrect: {EXPECTED_OPENING}"
    )
    assert abs(EXPECTED_CLOSING - 1_150_000.0) < 1e-6, (
        f"Closing constant incorrect: {EXPECTED_CLOSING}"
    )
    assert abs(EXPECTED_ROW_8 - 150_000.0) < 1e-6, f"Row-8 constant incorrect: {EXPECTED_ROW_8}"
    assert abs(EXPECTED_ROW_8_DECREASE - (-150_000.0)) < 1e-6, (
        f"Row-8 decrease constant incorrect: {EXPECTED_ROW_8_DECREASE}"
    )

    # Reconciliation: opening + row_8 == closing
    assert abs(EXPECTED_OPENING + EXPECTED_ROW_8 - EXPECTED_CLOSING) < 1e-6, (
        f"Reconciliation failed: {EXPECTED_OPENING} + {EXPECTED_ROW_8} != {EXPECTED_CLOSING}"
    )

    assert EXPECTED_CR8_HEIGHT == 9, f"CR8 template height must be 9, got {EXPECTED_CR8_HEIGHT}"


if __name__ == "__main__":
    _verify_lfs()
    _verify_irb_filter()
    _verify_constants()
    print("P2.48 fixture self-check passed.")
    print(
        f"  Prior (T-1): FIRB={PRIOR_FIRB_RWA:,.2f}, AIRB={PRIOR_AIRB_RWA:,.2f}, "
        f"slotting={PRIOR_SLOTTING_RWA:,.2f} (excluded)"
    )
    print(
        f"  Current (T): FIRB={CURRENT_FIRB_RWA:,.2f}, AIRB={CURRENT_AIRB_RWA:,.2f}, "
        f"slotting={CURRENT_SLOTTING_RWA:,.2f} (excluded)"
    )
    print(f"  Opening (row 1) = {EXPECTED_OPENING:,.2f}")
    print(f"  Closing (row 9) = {EXPECTED_CLOSING:,.2f}")
    print(f"  Row 8 Other    = {EXPECTED_ROW_8:+,.2f}  (positive = increase)")
    print(f"  Decrease ctrl  = {EXPECTED_ROW_8_DECREASE:+,.2f}  (negative = decrease)")
    print(
        f"  Reconciliation: {EXPECTED_OPENING:,.2f} + {EXPECTED_ROW_8:+,.2f}"
        f" = {EXPECTED_OPENING + EXPECTED_ROW_8:,.2f} == {EXPECTED_CLOSING:,.2f} ✓"
    )
