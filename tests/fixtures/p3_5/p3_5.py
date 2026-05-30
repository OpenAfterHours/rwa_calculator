"""
P3.5 fixture builder: CR9.1 ECAI-based PD back-testing seed frame (Basel 3.1 only).

Pipeline position (reporting path):
    seeded results LazyFrame
        -> Pillar3Generator._generate_all_cr9_1(lf, framework="BASEL_3_1")
        -> Pillar3TemplateBundle.cr9_1 (B31 only)

Scenario design (P3.5 — PRA PS1/26 UKB CR9.1 template, Art. 180(1)(f)):

    CR9.1 is the ECAI-mapping variant of CR9 PD back-testing.  Firms that
    use Art. 180(1)(f) ECAI-based PD estimation must group obligors by
    their firm-defined internal grade (mapped to an external ECAI rating)
    rather than by the fixed CR6 PD-range bands.  Each row in the output
    table corresponds to one ECAI grade; the final row is the aggregate
    total across all grades.

    The two seed-only discriminator columns are:
        ecai_pd_mapping  (bool, True)  — flags obligors in scope of CR9.1
        external_rating_equivalent (str) — the ECAI grade label used to
            group rows into CR9.1 PD bands ("A", "BBB", etc.).

    These columns do NOT exist in the production pipeline schema and are
    injected directly into the seed frame (exactly as P2.29 injects
    ``equity_transitional_approach``).

    Five corporate A-IRB obligors across two ECAI grades:

        Grade G1 → "A"   (OBL-1, OBL-2, OBL-3 — one defaulted)
        Grade G2 → "BBB" (OBL-4, OBL-5 — none defaulted)

    Obligor-level seed data:

        counterparty_reference | approach  | exposure_class | irb_pd_original | irb_pd_floored | ead_final | is_defaulted | external_rating_equivalent
        -----------------------+-----------+----------------+-----------------+----------------+-----------+--------------+---------------------------
        OBL-1                  | advanced_irb | corporate   | 0.0040          | 0.0040         | 100       | False        | A
        OBL-2                  | advanced_irb | corporate   | 0.0040          | 0.0040         | 100       | True         | A
        OBL-3                  | advanced_irb | corporate   | 0.0050          | 0.0050         | 200       | False        | A
        OBL-4                  | advanced_irb | corporate   | 0.0200          | 0.0200         | 50        | False        | BBB
        OBL-5                  | advanced_irb | corporate   | 0.0200          | 0.0200         | 150       | False        | BBB

    Hand-calculated CR9.1 output (key = "advanced_irb - corporate"):

        Row R1 (ECAI "A"):
            c = 3.0   (3 unique counterparties in grade)
            d = 1.0   (OBL-2 is_defaulted=True)
            e = 33.3333%  (1 / 3 × 100)
            f = 0.45%     (EAD-weighted PD: (100×0.004 + 100×0.004 + 200×0.005) / 400 × 100
                           = (0.4 + 0.4 + 1.0) / 400 × 100 = 1.8/4 = 0.45%)
            g = 0.43333%  (arithmetic avg PD: (0.004 + 0.004 + 0.005) / 3 × 100
                           = 0.013 / 3 × 100 = 0.43333%)
            h = 33.3333%  (fallback = observed rate — no historical_annual_default_rate column)

        Row R2 (ECAI "BBB"):
            c = 2.0
            d = 0.0
            e = 0.0%
            f = 2.00%  (EAD-weighted: (50×0.02 + 150×0.02) / 200 × 100 = 2.00%)
            g = 2.00%  (arithmetic avg: (0.02 + 0.02) / 2 × 100 = 2.00%)
            h = 0.0%   (fallback = observed rate = 0.0)

        Total row:
            c = 5.0
            d = 1.0
            e = 20.0%  (1 / 5 × 100)
            f = 0.96667%  (EAD-weighted: (100×0.004 + 100×0.004 + 200×0.005 + 50×0.02 + 150×0.02)
                           / 600 × 100 = (0.4 + 0.4 + 1.0 + 1.0 + 3.0) / 600 × 100
                           = 5.8 / 600 × 100 = 0.96667%)
            g = 1.06%  (arithmetic avg: (0.004+0.004+0.005+0.02+0.02) / 5 × 100
                        = 0.053 / 5 × 100 = 1.06%)
            h = 20.0%  (fallback = observed rate)

    Expected dict key: "advanced_irb - corporate"
    Expected output height: 3 (2 grade rows + 1 total row)

Usage (clean-import check):
    cd /path/to/worktrees/P3.5
    PYTHONPATH=src /path/to/.venv/bin/python tests/fixtures/p3_5/p3_5.py

References:
    - CR9.1 template definition: src/rwa_calc/reporting/pillar3/templates.py (CR9_1_COLUMNS)
    - CR9 generator (reference pattern): src/rwa_calc/reporting/pillar3/generator.py:604-703
    - PRA PS1/26 Art. 180(1)(f): ECAI-based PD estimation
    - PRA PS1/26 Annex XXII paras 12-15: CR9/CR9.1 back-testing disclosure instructions
    - UKB CR9.1 template guidance: PS1/26 App 17
"""

from __future__ import annotations

import polars as pl

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

SCENARIO_ID: str = "P3.5"

# Framework — CR9.1 is Basel 3.1 only
FRAMEWORK: str = "BASEL_3_1"

# Expected dict key produced by _generate_all_cr9_1
EXPECTED_DICT_KEY: str = "advanced_irb - corporate"

# Expected output height: 2 grade rows + 1 total row
EXPECTED_HEIGHT: int = 3

# ---------------------------------------------------------------------------
# Row R1 — ECAI grade "A" (OBL-1, OBL-2, OBL-3 — one defaulted)
# ---------------------------------------------------------------------------

# c: number of obligors at end of previous year (unique counterparty_reference count)
EXPECTED_R1_C: float = 3.0

# d: of which defaulted during the year (OBL-2 is_defaulted=True)
EXPECTED_R1_D: float = 1.0

# e: observed average default rate (%) = d / c * 100 = 1/3 * 100
EXPECTED_R1_E: float = 100.0 / 3.0  # ≈ 33.3333%

# f: EAD-weighted average PD (%) = (100*0.004 + 100*0.004 + 200*0.005) / 400 * 100
#    = (0.4 + 0.4 + 1.0) / 400 * 100 = 1.8 / 400 * 100 = 0.45%
EXPECTED_R1_F: float = 0.45

# g: arithmetic average PD (%) = (0.004 + 0.004 + 0.005) / 3 * 100
#    = 0.013 / 3 * 100 ≈ 0.43333%
EXPECTED_R1_G: float = 100.0 * (0.004 + 0.004 + 0.005) / 3.0  # ≈ 0.43333%

# h: historical annual default rate (%) — no historical column present, falls back to e
EXPECTED_R1_H: float = EXPECTED_R1_E  # = 33.3333%

# ---------------------------------------------------------------------------
# Row R2 — ECAI grade "BBB" (OBL-4, OBL-5 — none defaulted)
# ---------------------------------------------------------------------------

# c: 2 unique obligors
EXPECTED_R2_C: float = 2.0

# d: 0 defaults
EXPECTED_R2_D: float = 0.0

# e: observed average default rate (%) = 0 / 2 * 100 = 0.0%
EXPECTED_R2_E: float = 0.0

# f: EAD-weighted PD (%) = (50*0.02 + 150*0.02) / 200 * 100 = 0.02 * 100 = 2.00%
EXPECTED_R2_F: float = 2.0

# g: arithmetic average PD (%) = (0.02 + 0.02) / 2 * 100 = 2.00%
EXPECTED_R2_G: float = 2.0

# h: historical annual default rate (%) — fallback to e = 0.0%
EXPECTED_R2_H: float = 0.0

# ---------------------------------------------------------------------------
# Total row — all 5 obligors across both grades
# ---------------------------------------------------------------------------

# c: 5 unique obligors total
EXPECTED_TOT_C: float = 5.0

# d: 1 default total
EXPECTED_TOT_D: float = 1.0

# e: observed average default rate (%) = 1 / 5 * 100 = 20.0%
EXPECTED_TOT_E: float = 20.0

# f: EAD-weighted PD (%) across all 5 obligors
#    = (100*0.004 + 100*0.004 + 200*0.005 + 50*0.02 + 150*0.02) / 600 * 100
#    = (0.4 + 0.4 + 1.0 + 1.0 + 3.0) / 600 * 100
#    = 5.8 / 600 * 100 = 0.96667%
EXPECTED_TOT_F: float = 5.8 / 6.0  # ≈ 0.96667%

# g: arithmetic average PD (%) across all 5 obligors
#    = (0.004 + 0.004 + 0.005 + 0.02 + 0.02) / 5 * 100
#    = 0.053 / 5 * 100 = 1.06%
EXPECTED_TOT_G: float = 100.0 * (0.004 + 0.004 + 0.005 + 0.02 + 0.02) / 5.0  # = 1.06%

# h: historical annual default rate (%) — fallback to e = 20.0%
EXPECTED_TOT_H: float = EXPECTED_TOT_E


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def build_cr9_1_results_lf() -> pl.LazyFrame:
    """Return a seeded results LazyFrame carrying the five A-IRB corporate obligors.

    All five rows have:
        approach_applied = "advanced_irb"
        exposure_class   = "corporate"
        ecai_pd_mapping  = True   (seed-only column — not in production schema)
        external_rating_equivalent  (seed-only column — not in production schema)

    The two seed-only columns (``ecai_pd_mapping`` and
    ``external_rating_equivalent``) are injected here exactly as P2.29
    injects ``equity_transitional_approach`` onto its equity rows.
    The CR9.1 generator will filter on ``ecai_pd_mapping=True`` and group
    by ``external_rating_equivalent`` rather than by the fixed CR6 PD bands.

    Columns consumed by ``_compute_cr9_values`` (via ``_generate_all_cr9_1``):
        counterparty_reference  — for unique-obligor counting (_cr9_obligor_count)
        is_defaulted            — for default counting (_cr9_default_count)
        irb_pd_floored          — reported PD (col f / g)
        irb_pd_original         — allocation PD (bucket selection)
        ead_final               — EAD weight for col f (_cr9_ewa_pd_pct)
        approach_applied        — approach filter
        exposure_class          — class filter
        ecai_pd_mapping         — CR9.1 scope filter (seed-only)
        external_rating_equivalent — ECAI grade grouping key (seed-only)
    """
    rows = [
        {
            "counterparty_reference": "OBL-1",
            "approach_applied": "advanced_irb",
            "exposure_class": "corporate",
            "irb_pd_original": 0.0040,
            "irb_pd_floored": 0.0040,
            "ead_final": 100.0,
            "is_defaulted": False,
            "ecai_pd_mapping": True,
            "external_rating_equivalent": "A",
        },
        {
            "counterparty_reference": "OBL-2",
            "approach_applied": "advanced_irb",
            "exposure_class": "corporate",
            "irb_pd_original": 0.0040,
            "irb_pd_floored": 0.0040,
            "ead_final": 100.0,
            "is_defaulted": True,
            "ecai_pd_mapping": True,
            "external_rating_equivalent": "A",
        },
        {
            "counterparty_reference": "OBL-3",
            "approach_applied": "advanced_irb",
            "exposure_class": "corporate",
            "irb_pd_original": 0.0050,
            "irb_pd_floored": 0.0050,
            "ead_final": 200.0,
            "is_defaulted": False,
            "ecai_pd_mapping": True,
            "external_rating_equivalent": "A",
        },
        {
            "counterparty_reference": "OBL-4",
            "approach_applied": "advanced_irb",
            "exposure_class": "corporate",
            "irb_pd_original": 0.0200,
            "irb_pd_floored": 0.0200,
            "ead_final": 50.0,
            "is_defaulted": False,
            "ecai_pd_mapping": True,
            "external_rating_equivalent": "BBB",
        },
        {
            "counterparty_reference": "OBL-5",
            "approach_applied": "advanced_irb",
            "exposure_class": "corporate",
            "irb_pd_original": 0.0200,
            "irb_pd_floored": 0.0200,
            "ead_final": 150.0,
            "is_defaulted": False,
            "ecai_pd_mapping": True,
            "external_rating_equivalent": "BBB",
        },
    ]
    schema = {
        "counterparty_reference": pl.Utf8,
        "approach_applied": pl.Utf8,
        "exposure_class": pl.Utf8,
        "irb_pd_original": pl.Float64,
        "irb_pd_floored": pl.Float64,
        "ead_final": pl.Float64,
        "is_defaulted": pl.Boolean,
        "ecai_pd_mapping": pl.Boolean,
        "external_rating_equivalent": pl.Utf8,
    }
    return pl.DataFrame(rows, schema=schema).lazy()


# ---------------------------------------------------------------------------
# Self-check (also serves as clean-import verification)
# ---------------------------------------------------------------------------


def _verify_lf() -> None:
    """Verify the LazyFrame builds and has the expected shape and content."""
    lf = build_cr9_1_results_lf()
    df = lf.collect()
    assert df.height == 5, f"Expected 5 rows, got {df.height}"

    expected_cols = {
        "counterparty_reference",
        "approach_applied",
        "exposure_class",
        "irb_pd_original",
        "irb_pd_floored",
        "ead_final",
        "is_defaulted",
        "ecai_pd_mapping",
        "external_rating_equivalent",
    }
    assert expected_cols.issubset(set(df.columns)), (
        f"Missing columns: {expected_cols - set(df.columns)}"
    )

    # All rows are A-IRB corporate
    assert (df["approach_applied"] == "advanced_irb").all()
    assert (df["exposure_class"] == "corporate").all()
    assert (df["ecai_pd_mapping"] == True).all()  # noqa: E712

    # Grade distribution
    grade_a = df.filter(pl.col("external_rating_equivalent") == "A")
    grade_bbb = df.filter(pl.col("external_rating_equivalent") == "BBB")
    assert grade_a.height == 3, f"Expected 3 grade-A obligors, got {grade_a.height}"
    assert grade_bbb.height == 2, f"Expected 2 grade-BBB obligors, got {grade_bbb.height}"

    # Exactly one defaulted obligor (OBL-2) in grade A
    defaulted = df.filter(pl.col("is_defaulted") == True)  # noqa: E712
    assert defaulted.height == 1, f"Expected 1 defaulted obligor, got {defaulted.height}"
    assert defaulted["counterparty_reference"][0] == "OBL-2"
    assert defaulted["external_rating_equivalent"][0] == "A"


def _verify_constants() -> None:
    """Verify expected-value constants are internally consistent."""
    # Grade A hand-calc checks
    r1_ewa_pd = (100 * 0.004 + 100 * 0.004 + 200 * 0.005) / 400 * 100
    assert abs(EXPECTED_R1_F - r1_ewa_pd) < 1e-10, (
        f"R1 EWA-PD mismatch: computed={r1_ewa_pd}, constant={EXPECTED_R1_F}"
    )

    r1_avg_pd = (0.004 + 0.004 + 0.005) / 3 * 100
    assert abs(EXPECTED_R1_G - r1_avg_pd) < 1e-10, (
        f"R1 avg-PD mismatch: computed={r1_avg_pd}, constant={EXPECTED_R1_G}"
    )

    # Grade BBB hand-calc checks
    r2_ewa_pd = (50 * 0.02 + 150 * 0.02) / 200 * 100
    assert abs(EXPECTED_R2_F - r2_ewa_pd) < 1e-10, (
        f"R2 EWA-PD mismatch: computed={r2_ewa_pd}, constant={EXPECTED_R2_F}"
    )

    # Total hand-calc checks
    tot_ewa_pd = (100 * 0.004 + 100 * 0.004 + 200 * 0.005 + 50 * 0.02 + 150 * 0.02) / 600 * 100
    assert abs(EXPECTED_TOT_F - tot_ewa_pd) < 1e-10, (
        f"Total EWA-PD mismatch: computed={tot_ewa_pd}, constant={EXPECTED_TOT_F}"
    )

    tot_avg_pd = (0.004 + 0.004 + 0.005 + 0.02 + 0.02) / 5 * 100
    assert abs(EXPECTED_TOT_G - tot_avg_pd) < 1e-10, (
        f"Total avg-PD mismatch: computed={tot_avg_pd}, constant={EXPECTED_TOT_G}"
    )

    # Height / key constants
    assert EXPECTED_HEIGHT == 3, f"Expected height=3, got {EXPECTED_HEIGHT}"
    assert EXPECTED_DICT_KEY == "advanced_irb - corporate"


if __name__ == "__main__":
    _verify_lf()
    _verify_constants()
    print("P3.5 fixture self-check passed.")
    print("  5 obligors: 3 grade-A (1 defaulted), 2 grade-BBB (0 defaulted)")
    print(
        f"  Grade A  — c={EXPECTED_R1_C}, d={EXPECTED_R1_D}, "
        f"e={EXPECTED_R1_E:.4f}%, f={EXPECTED_R1_F}%, g={EXPECTED_R1_G:.5f}%"
    )
    print(
        f"  Grade BBB — c={EXPECTED_R2_C}, d={EXPECTED_R2_D}, "
        f"e={EXPECTED_R2_E}%, f={EXPECTED_R2_F}%, g={EXPECTED_R2_G}%"
    )
    print(
        f"  Total    — c={EXPECTED_TOT_C}, d={EXPECTED_TOT_D}, "
        f"e={EXPECTED_TOT_E}%, f={EXPECTED_TOT_F:.5f}%, g={EXPECTED_TOT_G}%"
    )
    print(f"  Dict key: {EXPECTED_DICT_KEY!r}, expected height: {EXPECTED_HEIGHT}")
