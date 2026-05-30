"""
P2.29 fixture builder: OV1 equity sub-approach rows (11-14) + output-floor rows (26/27).

Pipeline position (reporting path):
    seeded results LazyFrame + OutputFloorSummary
        -> Pillar3Generator.generate_from_lazyframe(...)
        -> Pillar3TemplateBundle.ov1 (B31 only)

Scenario design (P2.29 — PRA PS1/26 UKB OV1 template):

    OV1 rows 11-14 are Basel 3.1 memo rows that break equity exposures down by
    sub-approach.  Rows 26/27 report the output floor multiplier and adjustment.
    The current generator returns null for all six — this fixture seeds the
    minimal results LazyFrame that exercises those rows end-to-end.

    Because ``_determine_approach`` in the equity calculator always routes B31
    portfolios to SA (never IRB-transitional), row 11 cannot be populated by a
    real pipeline run.  The test therefore seeds ``equity_transitional_approach``
    directly on the results frame.  Row 27 (OF-ADJ) lives only on
    ``OutputFloorSummary``; the test must pass a real ``OutputFloorSummary``
    instance to ``generate_from_lazyframe`` (once the implementer adds that
    parameter).

    Equity rows in the seeded LazyFrame (all have approach_applied="equity"):

        Row 11 — IRB Transitional:
            exposure_id: "EQ-TRANS-01"
            equity_transitional_approach: "irb_transitional"
            ciu_approach: null
            rwa_final: 1_600.00
            output_floor_pct: 0.725

        Row 12 — Look-through:
            exposure_id: "EQ-LT-01"
            ciu_approach: "look_through"
            equity_transitional_approach: null
            rwa_final: 1_500.00
            output_floor_pct: 0.725

        Row 13 — Mandate-based:
            exposure_id: "EQ-MB-01"
            ciu_approach: "mandate_based"
            equity_transitional_approach: null
            rwa_final: 960.00
            output_floor_pct: 0.725

        Row 14 — Fall-back:
            exposure_id: "EQ-FB-01"
            ciu_approach: "fallback"
            equity_transitional_approach: null
            rwa_final: 6_250.00
            output_floor_pct: 0.725

    Column-c derivation (own funds):
        rows 11-14: c = 0.08 × a  (auto-shim in _ov1_row_values)
        rows 26/27: c = null      (ratio / adjustment — must be exempt from shim)

    OutputFloorSummary (hand-calculated):
        floor_pct       = 0.725           (fully-phased Basel 3.1 floor)
        of_adj          = 6_250.0         (see formula below)
        u_trea          = 10_310.0        (sum of rwa_final across all 4 equity rows)
        s_trea          = 100_000.0       (notional SA-equivalent — large enough floor binds)
        floor_threshold = 72_500.0        (0.725 × 100_000)
        shortfall       = 68_440.0        (72_500 + 6_250 - 10_310)
        portfolio_floor_binding = True
        floored_modelled_rwa = 78_750.0   (= 72_500 + 6_250)

    OF-ADJ formula (compute_of_adj):
        of_adj = 12.5 × (irb_t2_credit - irb_cet1_deduction - gcra_capped + sa_t2_credit)
        inputs: irb_t2_credit=500.0, irb_cet1_deduction=0.0, gcra_amount=0.0, sa_t2_credit=0.0,
                s_trea=100_000.0  → gcra_capped = min(0.0, 1_250.0) = 0.0
        of_adj = 12.5 × (500.0 - 0.0 - 0.0 + 0.0) = 6_250.0   ✓

    Expected OV1 output (framework="BASEL_3_1", column "a" / column "c"):

        row_ref  row_name                                             a           c
        11       Equity positions under IRB Transitional Approach     1_600.00    128.00
        12       Equity investments in funds — look-through approach  1_500.00    120.00
        13       Equity investments in funds — mandate-based approach   960.00     76.80
        14       Equity investments in funds — fall-back approach     6_250.00    500.00
        26       Output floor multiplier                              0.725       null
        27       Output floor adjustment                              6_250.0     null

Usage (clean-import check):
    cd /path/to/worktrees/P2.29
    PYTHONPATH=src /path/to/.venv/bin/python tests/fixtures/p2_29/p2_29.py

References:
    - OV1 row labels: src/rwa_calc/reporting/pillar3/templates.py:154-175 (B31_OV1_ROWS)
    - Current null stubs: src/rwa_calc/reporting/pillar3/generator.py:1009,1077-1080
    - OF-ADJ formula: src/rwa_calc/engine/aggregator/_floor.py:61-88 (compute_of_adj)
    - Bundle field: src/rwa_calc/contracts/bundles.py:623-637 (OutputFloorSummary)
    - PRA PS1/26 UKB OV1 template guidance: PS1/26 App 17
"""

from __future__ import annotations

import polars as pl

from rwa_calc.contracts.bundles import OutputFloorSummary

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

SCENARIO_ID: str = "P2.29"

# Framework — only BASEL_3_1 has rows 11-14 / 26 / 27
FRAMEWORK: str = "BASEL_3_1"

# Output floor percentage (fully-phased Basel 3.1 floor)
FLOOR_PCT: float = 0.725

# --- Equity row rwa_final values ---

RWA_IRB_TRANSITIONAL: float = 1_600.00  # row 11
RWA_LOOK_THROUGH: float = 1_500.00  # row 12
RWA_MANDATE_BASED: float = 960.00  # row 13
RWA_FALLBACK: float = 6_250.00  # row 14

# Sum across all 4 equity rows (= U-TREA for this minimal portfolio)
U_TREA: float = RWA_IRB_TRANSITIONAL + RWA_LOOK_THROUGH + RWA_MANDATE_BASED + RWA_FALLBACK
# = 1_600 + 1_500 + 960 + 6_250 = 10_310.00

# --- OutputFloorSummary fields ---

# OF-ADJ inputs — hand-verified via compute_of_adj:
#   of_adj = 12.5 * (irb_t2_credit - irb_cet1_deduction - gcra_capped + sa_t2_credit)
#          = 12.5 * (500.0 - 0.0 - 0.0 + 0.0) = 6_250.0
OF_ADJ_IRB_T2_CREDIT: float = 500.0
OF_ADJ_IRB_CET1_DEDUCTION: float = 0.0
OF_ADJ_GCRA_AMOUNT: float = 0.0
OF_ADJ_SA_T2_CREDIT: float = 0.0
OF_ADJ: float = 6_250.0  # 12.5 * 500.0

# S-TREA and floor threshold
S_TREA: float = 100_000.0
FLOOR_THRESHOLD: float = FLOOR_PCT * S_TREA  # 72_500.0
FLOORED_MODELLED_RWA: float = FLOOR_THRESHOLD + OF_ADJ  # 78_750.0
SHORTFALL: float = FLOORED_MODELLED_RWA - U_TREA  # 68_440.0

# --- Expected OV1 cell values ---

# Column a (RWEA T)
EXPECTED_ROW_11_A: float = RWA_IRB_TRANSITIONAL  # 1_600.00
EXPECTED_ROW_12_A: float = RWA_LOOK_THROUGH  # 1_500.00
EXPECTED_ROW_13_A: float = RWA_MANDATE_BASED  # 960.00
EXPECTED_ROW_14_A: float = RWA_FALLBACK  # 6_250.00
EXPECTED_ROW_26_A: float = FLOOR_PCT  # 0.725
EXPECTED_ROW_27_A: float = OF_ADJ  # 6_250.0

# Column c (own funds = 0.08 × a for rows 11-14; null for 26/27)
EXPECTED_ROW_11_C: float = EXPECTED_ROW_11_A * 0.08  # 128.00
EXPECTED_ROW_12_C: float = EXPECTED_ROW_12_A * 0.08  # 120.00
EXPECTED_ROW_13_C: float = EXPECTED_ROW_13_A * 0.08  # 76.80
EXPECTED_ROW_14_C: float = EXPECTED_ROW_14_A * 0.08  # 500.00
EXPECTED_ROW_26_C: None = None  # ratio — no own-funds shim
EXPECTED_ROW_27_C: None = None  # adjustment — no own-funds shim


# ---------------------------------------------------------------------------
# Public factories
# ---------------------------------------------------------------------------


def build_equity_results_lf() -> pl.LazyFrame:
    """
    Return a seeded results LazyFrame carrying the four equity sub-approach rows.

    All four rows have approach_applied="equity".  The discriminator columns are:
    - ``equity_transitional_approach``: "irb_transitional" for row 11; null otherwise.
    - ``ciu_approach``: "look_through" / "mandate_based" / "fallback" for rows 12-14;
      null for row 11.
    - ``rwa_final``: the RWEA value for each sub-approach.
    - ``output_floor_pct``: 0.725 on every row (floor is binding).

    The LazyFrame intentionally omits columns not needed by _generate_ov1 (e.g.
    exposure_class, ead_final) to keep the fixture minimal.  _available_columns()
    in the generator accepts any superset of the required columns.
    """
    rows = [
        {
            "exposure_id": "EQ-TRANS-01",
            "approach_applied": "equity",
            "equity_transitional_approach": "irb_transitional",
            "ciu_approach": None,
            "rwa_final": RWA_IRB_TRANSITIONAL,
            "output_floor_pct": FLOOR_PCT,
        },
        {
            "exposure_id": "EQ-LT-01",
            "approach_applied": "equity",
            "equity_transitional_approach": None,
            "ciu_approach": "look_through",
            "rwa_final": RWA_LOOK_THROUGH,
            "output_floor_pct": FLOOR_PCT,
        },
        {
            "exposure_id": "EQ-MB-01",
            "approach_applied": "equity",
            "equity_transitional_approach": None,
            "ciu_approach": "mandate_based",
            "rwa_final": RWA_MANDATE_BASED,
            "output_floor_pct": FLOOR_PCT,
        },
        {
            "exposure_id": "EQ-FB-01",
            "approach_applied": "equity",
            "equity_transitional_approach": None,
            "ciu_approach": "fallback",
            "rwa_final": RWA_FALLBACK,
            "output_floor_pct": FLOOR_PCT,
        },
    ]
    schema = {
        "exposure_id": pl.Utf8,
        "approach_applied": pl.Utf8,
        "equity_transitional_approach": pl.Utf8,
        "ciu_approach": pl.Utf8,
        "rwa_final": pl.Float64,
        "output_floor_pct": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema).lazy()


def build_output_floor_summary() -> OutputFloorSummary:
    """
    Return a hand-verified OutputFloorSummary where the floor binds and OF-ADJ is non-zero.

    OF-ADJ is derived from compute_of_adj with:
        irb_t2_credit=500.0, irb_cet1_deduction=0.0, gcra_amount=0.0,
        sa_t2_credit=0.0, s_trea=100_000.0
        → of_adj = 12.5 * (500.0 − 0.0 − 0.0 + 0.0) = 6_250.0

    The floor binds: x * S-TREA + OF-ADJ = 72_500 + 6_250 = 78_750 > U-TREA = 10_310.
    """
    return OutputFloorSummary(
        u_trea=U_TREA,
        s_trea=S_TREA,
        floor_pct=FLOOR_PCT,
        floor_threshold=FLOOR_THRESHOLD,
        shortfall=SHORTFALL,
        portfolio_floor_binding=True,
        floored_modelled_rwa=FLOORED_MODELLED_RWA,
        of_adj=OF_ADJ,
        irb_t2_credit=OF_ADJ_IRB_T2_CREDIT,
        irb_cet1_deduction=OF_ADJ_IRB_CET1_DEDUCTION,
        gcra_amount=OF_ADJ_GCRA_AMOUNT,
        sa_t2_credit=OF_ADJ_SA_T2_CREDIT,
        sa_rwa_total=0.0,
        equity_rwa_total=U_TREA,
        total_rwa_post_floor=FLOORED_MODELLED_RWA,
    )


# ---------------------------------------------------------------------------
# Self-check (also serves as clean-import verification)
# ---------------------------------------------------------------------------


def _verify_of_adj() -> None:
    """Verify OF-ADJ constant against compute_of_adj formula."""
    from rwa_calc.engine.aggregator._floor import compute_of_adj

    computed, gcra_capped = compute_of_adj(
        irb_t2_credit=OF_ADJ_IRB_T2_CREDIT,
        irb_cet1_deduction=OF_ADJ_IRB_CET1_DEDUCTION,
        gcra_amount=OF_ADJ_GCRA_AMOUNT,
        sa_t2_credit=OF_ADJ_SA_T2_CREDIT,
        s_trea=S_TREA,
    )
    assert computed == OF_ADJ, f"OF-ADJ mismatch: computed={computed}, expected={OF_ADJ}"
    assert gcra_capped == 0.0, f"GCRA capped should be 0.0, got {gcra_capped}"


def _verify_lf() -> None:
    """Verify the LazyFrame builds and has the expected shape."""
    lf = build_equity_results_lf()
    df = lf.collect()
    assert df.height == 4, f"Expected 4 rows, got {df.height}"
    expected_cols = {
        "exposure_id",
        "approach_applied",
        "equity_transitional_approach",
        "ciu_approach",
        "rwa_final",
        "output_floor_pct",
    }
    assert expected_cols.issubset(set(df.columns)), (
        f"Missing columns: {expected_cols - set(df.columns)}"
    )

    # Row 11 discriminators
    row11 = df.filter(pl.col("exposure_id") == "EQ-TRANS-01")
    assert row11["equity_transitional_approach"][0] == "irb_transitional"
    assert row11["rwa_final"][0] == RWA_IRB_TRANSITIONAL

    # Row 14 — fall-back
    row14 = df.filter(pl.col("exposure_id") == "EQ-FB-01")
    assert row14["ciu_approach"][0] == "fallback"
    assert row14["rwa_final"][0] == RWA_FALLBACK

    # output_floor_pct uniform
    assert (df["output_floor_pct"] == FLOOR_PCT).all()


def _verify_summary() -> None:
    """Verify OutputFloorSummary fields are internally consistent."""
    s = build_output_floor_summary()
    assert s.portfolio_floor_binding is True
    assert s.floor_pct == FLOOR_PCT
    assert abs(s.of_adj - OF_ADJ) < 1e-9
    assert abs(s.floor_threshold - FLOOR_THRESHOLD) < 1e-6
    assert abs(s.shortfall - SHORTFALL) < 1e-6


if __name__ == "__main__":
    _verify_of_adj()
    _verify_lf()
    _verify_summary()
    print("P2.29 fixture self-check passed.")
    print(
        f"  4 equity rows: IRB-trans={RWA_IRB_TRANSITIONAL}, LT={RWA_LOOK_THROUGH}, "
        f"MB={RWA_MANDATE_BASED}, FB={RWA_FALLBACK}"
    )
    print(
        f"  OutputFloorSummary: floor_pct={FLOOR_PCT}, of_adj={OF_ADJ}, "
        f"binding={True}, shortfall={SHORTFALL}"
    )
    print(
        f"  Expected OV1 column-c: row11={EXPECTED_ROW_11_C}, row12={EXPECTED_ROW_12_C}, "
        f"row13={EXPECTED_ROW_13_C}, row14={EXPECTED_ROW_14_C}"
    )
    print(f"  Rows 26/27 column-c: {EXPECTED_ROW_26_C!r} (must stay null after fix)")
