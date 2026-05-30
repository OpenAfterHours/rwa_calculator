"""
P4.20 fixture builder: C 08.02 grade-path IRB results LazyFrame.

Pipeline position (reporting path):
    seeded IRB results LazyFrame (carrying cp_internal_rating_grade)
        -> COREPGenerator.generate_from_lazyframe(lf)
        -> COREPTemplateBundle.c08_02["corporate"]  (CRR framework)

Scenario design (P4.20 — COREP Annex II, C 08.02, CRR Art. 142(1)(6)/153/169-170):

    C 08.02 is the IRB breakdown by firm internal rating grade.  The actual
    template requires rows keyed by the firm's own obligor grade scale (one row
    per grade).  When the IRB results frame carries a ``cp_internal_rating_grade``
    column the generator must group by grade label rather than the PD-band
    fallback labels defined in PD_BANDS.

    Grade-path fixture: 3 corporate exposures with distinct grade labels.
    The LOAD-BEARING PROPERTY is that E1 (PD 0.01) and E2 (PD 0.02) both map
    to the SAME fixed PD bucket "0.75% - 2.50%", so under the old fixed-bucket
    code they collapse to a single row (EAD 3000), but under grade-keying they
    produce TWO rows (AAA EAD 1000, BB EAD 2000).  E3 (PD 1.0) maps to
    "Default (100%)" and sits alone either way — it serves as a control.

    Fallback path: existing ``_irb_results()`` in test_corep.py (no grade column)
    exercises the fixed-bucket fallback; that fixture is NOT modified here.

Column set mirrors the existing _irb_results() helper in test_corep.py
(drawn_amount = ead_final, undrawn_amount = 0 so col 0020 = ead):
    exposure_reference   pl.String
    approach_applied     pl.String
    exposure_class       pl.String
    drawn_amount         pl.Float64  (= ead_final so col 0020 = ead)
    undrawn_amount       pl.Float64  (= 0.0)
    ead_final            pl.Float64
    rwa_final            pl.Float64
    irb_pd_floored       pl.Float64
    irb_lgd_floored      pl.Float64
    irb_maturity_m       pl.Float64
    irb_expected_loss    pl.Float64
    counterparty_reference  pl.String
    cp_internal_rating_grade  pl.String  <- NEW grade column

Expected C 08.02 output (CRR, group-by-grade, 3 rows):
    grade | 0005 | 0010 | 0020   | 0110   | 0230 | 0250  | 0260   | 0280   | 0300
    AAA   | AAA  | 0.01 | 1000.0 | 1000.0 | 0.45 | 730.0 | 700.0  |  2.25  | 1.0
    BB    | BB   | 0.02 | 2000.0 | 2000.0 | 0.45 | 730.0 | 1400.0 | 18.0   | 1.0
    D     | D    | 1.0  |  500.0 |  500.0 | 0.45 | 365.0 |  750.0 | 225.0  | 1.0

    Discriminating assertion: grade-path corporate DF has 3 rows {AAA, BB, D}.
    Under fixed-bucket fallback, E1+E2 would collapse to one "0.75% - 2.50%"
    row (EAD 3000, EW PD=0.01667).

Hand-calc (col 0250 maturity in days):
    AAA: M=2.0 yr -> 2.0*365 = 730.0 days
    BB:  M=2.0 yr -> 2.0*365 = 730.0 days
    D:   M=1.0 yr -> 1.0*365 = 365.0 days

Usage (clean-import + self-check):
    PYTHONPATH=/path/to/worktrees/P4.20/src \\
        /path/to/.venv/bin/python tests/fixtures/p4_20/p4_20.py

References:
    - COREP Annex II, template C 08.02 ("CR IRB 2")
    - CRR Art. 142(1)(6) (internal rating system), Art. 153 (IRB RW functions)
    - CRR Art. 169-170 (use of PD estimates)
    - reporting/corep/templates.py PD_BANDS (lines 712-721)
    - reporting/corep/generator.py _generate_all_c08_02 (lines 1485-1521)
    - reporting/corep/generator.py _generate_c08_02_for_class (lines 1523-1586)
    - reporting/corep/generator.py _c08_exposure_cols (line 3132) — col 0020
    - tests/unit/test_corep.py _irb_results() (line 129) — column-set template
"""

from __future__ import annotations

import polars as pl

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

SCENARIO_ID: str = "P4.20"
FRAMEWORK: str = "CRR"

# Grade labels used in the fixture
GRADE_AAA: str = "AAA"
GRADE_BB: str = "BB"
GRADE_D: str = "D"

EXPECTED_GRADE_SET: frozenset[str] = frozenset({GRADE_AAA, GRADE_BB, GRADE_D})

# Load-bearing property: E1 and E2 PDs map to the SAME fixed PD bucket.
# Confirmed against PD_BANDS = [..., (0.0075, 0.025, "0.75% - 2.50%"), ...]
E1_PD: float = 0.01   # AAA — falls in "0.75% - 2.50%"
E2_PD: float = 0.02   # BB  — falls in "0.75% - 2.50%"  (SAME BUCKET as E1)
E3_PD: float = 1.0    # D   — falls in "Default (100%)"  (different bucket)

SAME_BUCKET_LABEL: str = "0.75% - 2.50%"
E3_BUCKET_LABEL: str = "Default (100%)"

# Expected aggregated C 08.02 values per grade row (CRR, no partial data)
# Keys are C 08.02 column references.
EXPECTED_AAA: dict[str, object] = {
    "0005": GRADE_AAA,
    "0010": 0.01,
    "0020": 1000.0,
    "0110": 1000.0,
    "0230": 0.45,
    "0250": 730.0,
    "0260": 700.0,
    "0280": 2.25,
    "0300": 1.0,
}

EXPECTED_BB: dict[str, object] = {
    "0005": GRADE_BB,
    "0010": 0.02,
    "0020": 2000.0,
    "0110": 2000.0,
    "0230": 0.45,
    "0250": 730.0,
    "0260": 1400.0,
    "0280": 18.0,
    "0300": 1.0,
}

EXPECTED_D: dict[str, object] = {
    "0005": GRADE_D,
    "0010": 1.0,
    "0020": 500.0,
    "0110": 500.0,
    "0230": 0.45,
    "0250": 365.0,
    "0260": 750.0,
    "0280": 225.0,
    "0300": 1.0,
}

# Sum of EAD across all three grades — must reconcile to C 08.01 corporate total
EXPECTED_TOTAL_EAD: float = 3500.0

# Under fixed-bucket fallback E1+E2 collapse; expected collapsed EAD for that bucket
FALLBACK_SAME_BUCKET_EAD: float = 3000.0  # 1000 + 2000

# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def build_grade_path_irb_results_lf() -> pl.LazyFrame:
    """Return a synthetic IRB results LazyFrame for C 08.02 grade-path testing.

    Produces 3 corporate exposures each with a distinct internal rating grade.
    The column set mirrors ``_irb_results()`` in tests/unit/test_corep.py with
    the addition of the ``cp_internal_rating_grade`` column required by the new
    grade-keying path in ``_generate_c08_02_for_class``.

    Load-bearing property confirmed against PD_BANDS in templates.py:
        E1 (PD 0.01) and E2 (PD 0.02) map to the SAME bucket "0.75% - 2.50%".
        Under fixed-bucket code they collapse to one row (EAD 3000).
        Under grade-keying they are distinct rows AAA (EAD 1000) + BB (EAD 2000).
        E3 (PD 1.0) maps to "Default (100%)" and is a control — distinct either way.

    Column notes:
        drawn_amount  = ead_final   (so col 0020 original-exposure = ead)
        undrawn_amount = 0.0        (no off-balance-sheet component)

    Returns:
        A LazyFrame with 3 rows covering the AAA / BB / D grade labels.
    """
    schema: dict[str, pl.DataType] = {
        "exposure_reference": pl.String,
        "approach_applied": pl.String,
        "exposure_class": pl.String,
        "counterparty_reference": pl.String,
        "drawn_amount": pl.Float64,
        "undrawn_amount": pl.Float64,
        "ead_final": pl.Float64,
        "rwa_final": pl.Float64,
        "irb_pd_floored": pl.Float64,
        "irb_lgd_floored": pl.Float64,
        "irb_maturity_m": pl.Float64,
        "irb_expected_loss": pl.Float64,
        "cp_internal_rating_grade": pl.String,
    }

    rows = [
        # E1 — grade AAA, PD 0.01 (bucket "0.75% - 2.50%")
        {
            "exposure_reference": "GR_1",
            "approach_applied": "foundation_irb",
            "exposure_class": "corporate",
            "counterparty_reference": "CP_A",
            "drawn_amount": 1000.0,   # drawn = ead so col 0020 = 1000
            "undrawn_amount": 0.0,
            "ead_final": 1000.0,
            "rwa_final": 700.0,
            "irb_pd_floored": E1_PD,
            "irb_lgd_floored": 0.45,
            "irb_maturity_m": 2.0,
            "irb_expected_loss": 2.25,
            "cp_internal_rating_grade": GRADE_AAA,
        },
        # E2 — grade BB, PD 0.02 (same bucket "0.75% - 2.50%" as E1)
        {
            "exposure_reference": "GR_2",
            "approach_applied": "foundation_irb",
            "exposure_class": "corporate",
            "counterparty_reference": "CP_B",
            "drawn_amount": 2000.0,   # drawn = ead so col 0020 = 2000
            "undrawn_amount": 0.0,
            "ead_final": 2000.0,
            "rwa_final": 1400.0,
            "irb_pd_floored": E2_PD,
            "irb_lgd_floored": 0.45,
            "irb_maturity_m": 2.0,
            "irb_expected_loss": 18.0,
            "cp_internal_rating_grade": GRADE_BB,
        },
        # E3 — grade D, PD 1.0 ("Default (100%)" bucket — control row)
        {
            "exposure_reference": "GR_3",
            "approach_applied": "foundation_irb",
            "exposure_class": "corporate",
            "counterparty_reference": "CP_C",
            "drawn_amount": 500.0,    # drawn = ead so col 0020 = 500
            "undrawn_amount": 0.0,
            "ead_final": 500.0,
            "rwa_final": 750.0,
            "irb_pd_floored": E3_PD,
            "irb_lgd_floored": 0.45,
            "irb_maturity_m": 1.0,
            "irb_expected_loss": 225.0,
            "cp_internal_rating_grade": GRADE_D,
        },
    ]

    return pl.DataFrame(rows, schema=schema).lazy()


# ---------------------------------------------------------------------------
# Self-check (also serves as clean-import verification)
# ---------------------------------------------------------------------------


def _verify_lf() -> None:
    """Verify the LazyFrame builds and has the expected shape and content."""
    lf = build_grade_path_irb_results_lf()
    df = lf.collect()
    assert df.height == 3, "Expected 3 rows, got %d" % df.height

    required_cols = {
        "exposure_reference",
        "approach_applied",
        "exposure_class",
        "counterparty_reference",
        "drawn_amount",
        "undrawn_amount",
        "ead_final",
        "rwa_final",
        "irb_pd_floored",
        "irb_lgd_floored",
        "irb_maturity_m",
        "irb_expected_loss",
        "cp_internal_rating_grade",
    }
    missing = required_cols - set(df.columns)
    assert not missing, "Missing columns: %s" % missing

    # All three grades present
    grades = set(df["cp_internal_rating_grade"].to_list())
    assert grades == EXPECTED_GRADE_SET, "Grade mismatch: got %s" % grades

    # All three exposure_references unique
    refs = df["exposure_reference"].to_list()
    assert len(set(refs)) == 3, "Exposure references not unique: %s" % refs

    # Only corporate class
    classes = set(df["exposure_class"].to_list())
    assert classes == {"corporate"}, "Unexpected exposure classes: %s" % classes

    # All foundation_irb
    approaches = set(df["approach_applied"].to_list())
    assert approaches == {"foundation_irb"}, "Unexpected approaches: %s" % approaches

    # Load-bearing PD property: E1 and E2 are in the same fixed PD bucket
    from rwa_calc.reporting.corep.templates import PD_BANDS

    def _find_band(pd_val: float) -> str:
        for lower, upper, label in PD_BANDS:
            if lower <= pd_val < upper:
                return label
        return "Unassigned"

    aaa_row = df.filter(df["cp_internal_rating_grade"] == GRADE_AAA)
    bb_row = df.filter(df["cp_internal_rating_grade"] == GRADE_BB)
    d_row = df.filter(df["cp_internal_rating_grade"] == GRADE_D)

    band_aaa = _find_band(aaa_row["irb_pd_floored"][0])
    band_bb = _find_band(bb_row["irb_pd_floored"][0])
    band_d = _find_band(d_row["irb_pd_floored"][0])

    assert band_aaa == SAME_BUCKET_LABEL, (
        "AAA PD bucket expected %r, got %r" % (SAME_BUCKET_LABEL, band_aaa)
    )
    assert band_bb == SAME_BUCKET_LABEL, (
        "BB PD bucket expected %r, got %r" % (SAME_BUCKET_LABEL, band_bb)
    )
    assert band_aaa == band_bb, (
        "LOAD-BEARING: AAA and BB must be in same fixed bucket, got %r vs %r"
        % (band_aaa, band_bb)
    )
    assert band_d == E3_BUCKET_LABEL, (
        "D PD bucket expected %r, got %r" % (E3_BUCKET_LABEL, band_d)
    )
    assert band_aaa != band_d, "AAA and D must be in different fixed buckets"

    # drawn = ead, undrawn = 0 (so col 0020 original-exposure equals ead)
    assert df["undrawn_amount"].sum() == 0.0, "All undrawn_amount must be 0"
    drawn_eq_ead = (df["drawn_amount"] == df["ead_final"]).all()
    assert drawn_eq_ead, "drawn_amount must equal ead_final for all rows"

    # Total EAD reconciles to C 08.01 corporate total
    total_ead = df["ead_final"].sum()
    assert total_ead == EXPECTED_TOTAL_EAD, (
        "Total EAD expected %.1f, got %.1f" % (EXPECTED_TOTAL_EAD, total_ead)
    )


def _verify_constants() -> None:
    """Verify scenario constants are internally consistent."""
    assert EXPECTED_GRADE_SET == {GRADE_AAA, GRADE_BB, GRADE_D}, (
        "EXPECTED_GRADE_SET must contain exactly AAA, BB, D"
    )
    assert E1_PD < E2_PD, "E1_PD must be less than E2_PD"
    assert E2_PD < E3_PD, "E2_PD must be less than E3_PD"
    assert EXPECTED_TOTAL_EAD == 3500.0, "EXPECTED_TOTAL_EAD must be 3500.0"
    assert FALLBACK_SAME_BUCKET_EAD == 3000.0, "FALLBACK_SAME_BUCKET_EAD must be 3000.0"

    # Expected-output dicts have col 0005 set to the grade label
    assert EXPECTED_AAA["0005"] == GRADE_AAA, "EXPECTED_AAA 0005 must equal GRADE_AAA"
    assert EXPECTED_BB["0005"] == GRADE_BB, "EXPECTED_BB 0005 must equal GRADE_BB"
    assert EXPECTED_D["0005"] == GRADE_D, "EXPECTED_D 0005 must equal GRADE_D"

    # Maturity in days: 2.0 yr * 365 = 730, 1.0 yr * 365 = 365
    assert EXPECTED_AAA["0250"] == 730.0, "AAA col 0250 must be 730.0 days"
    assert EXPECTED_BB["0250"] == 730.0, "BB col 0250 must be 730.0 days"
    assert EXPECTED_D["0250"] == 365.0, "D col 0250 must be 365.0 days"

    # EAD totals
    assert EXPECTED_AAA["0110"] == 1000.0, "AAA col 0110 must be 1000.0"
    assert EXPECTED_BB["0110"] == 2000.0, "BB col 0110 must be 2000.0"
    assert EXPECTED_D["0110"] == 500.0, "D col 0110 must be 500.0"
    total = (
        float(EXPECTED_AAA["0110"])  # type: ignore[arg-type]
        + float(EXPECTED_BB["0110"])  # type: ignore[arg-type]
        + float(EXPECTED_D["0110"])   # type: ignore[arg-type]
    )
    assert total == EXPECTED_TOTAL_EAD, "Sum of 0110 must equal EXPECTED_TOTAL_EAD"


if __name__ == "__main__":
    _verify_constants()
    _verify_lf()
    lf = build_grade_path_irb_results_lf()
    df = lf.collect()
    print("P4.20 fixture self-check passed.")
    print("  %d rows: GR_1 (AAA), GR_2 (BB), GR_3 (D)" % df.height)
    print("  Load-bearing: AAA+BB in same fixed PD bucket '%s'" % SAME_BUCKET_LABEL)
    print("  Grade-path produces 3 rows; fixed-bucket fallback produces 2 rows")
    print("  Expected C 08.02 grade-path output (CRR):")
    print("    AAA: 0110=%.1f  0260=%.1f  0280=%.2f  0250=%.1f" % (
        float(EXPECTED_AAA["0110"]),  # type: ignore[arg-type]
        float(EXPECTED_AAA["0260"]),  # type: ignore[arg-type]
        float(EXPECTED_AAA["0280"]),  # type: ignore[arg-type]
        float(EXPECTED_AAA["0250"]),  # type: ignore[arg-type]
    ))
    print("    BB:  0110=%.1f  0260=%.1f  0280=%.1f  0250=%.1f" % (
        float(EXPECTED_BB["0110"]),   # type: ignore[arg-type]
        float(EXPECTED_BB["0260"]),   # type: ignore[arg-type]
        float(EXPECTED_BB["0280"]),   # type: ignore[arg-type]
        float(EXPECTED_BB["0250"]),   # type: ignore[arg-type]
    ))
    print("    D:   0110=%.1f   0260=%.1f  0280=%.1f  0250=%.1f" % (
        float(EXPECTED_D["0110"]),    # type: ignore[arg-type]
        float(EXPECTED_D["0260"]),    # type: ignore[arg-type]
        float(EXPECTED_D["0280"]),    # type: ignore[arg-type]
        float(EXPECTED_D["0250"]),    # type: ignore[arg-type]
    ))
