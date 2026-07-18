"""
P2.25(b) fixture builder: CR5 bucketing of a residential-RE not-materially-dependent
loan split across the 55%-LTV threshold (Art. 124F / Art. 124L).

Pipeline position (reporting path):
    post-split results LazyFrame (produced by RealEstateSplitter)
        -> Pillar3Generator._generate_cr5(framework="BASEL_3_1")
        -> Pillar3TemplateBundle.cr5

Scenario design (P2.25 — UKB CR5 sub-rows 9f / 9g):

    The RealEstateSplitter has ALREADY split one RRE loan (parent EAD 1,000,000;
    property value 1,000,000; LTV 100%) into two result rows, per Art. 124F:

        secured row  — EAD 550,000 @ 20% RW (secured portion, up to 55% of property value)
        residual row — EAD 450,000 @ 75% RW (above-55%-LTV residual; natural-person
                       counterparty RW per Art. 124L)

    The gap this item closes: the CR5 generator currently allocates BOTH rows into
    row 9 ("Secured by mortgages on immovable property") via the ``exposure_class``
    filter.  For Basel 3.1, when ``re_split_role`` is present and
    ``materially_dependent_on_property`` is False, the generator must produce two
    dedicated sub-rows instead:

        9f  "RE — secured up to 55% LTV"   secured row (EAD 550,000 → band f, 20%)
        9g  "RE — above 55% LTV (residual)" residual row (EAD 450,000 → band p, 75%)

    Row 9 Total still equals parent EAD (1,000,000); the sub-rows are "of which"
    memo rows and are NOT double-counted into grand Total row 17.

    B31 risk-weight band indices (B31_CR5_RISK_WEIGHTS, zero-based):
        index 5  → 0.20 (20%) → column ref "f"
        index 15 → 0.75 (75%) → column ref "p"

    RWEA check (informational, not asserted by CR5):
        secured:  550,000 × 0.20 =  110,000
        residual: 450,000 × 0.75 =  337,500
        total RWA:                   447,500

    CRR CR5 must remain byte-identical to today (new logic gates on
    framework == "BASEL_3_1").

Column set (matches OUTPUT_SCHEMA + RE_SPLITTER_OUTPUT_SCHEMA):
    - exposure_reference: str       — unique row ID
    - approach_applied:   str       — "standardised" for both rows
    - exposure_class:     str       — "residential_mortgage" (secured) / "retail_other" (residual)
    - ead_final:          Float64   — 550,000.0 / 450,000.0
    - rwa_final:          Float64   — 110,000.0 / 337,500.0
    - risk_weight:        Float64   — 0.20 / 0.75
    - re_split_role:      str       — "secured" / "residual"  [new discriminator]
    - materially_dependent_on_property: Boolean — False for both rows  [new discriminator]
    - property_ltv:       Float64   — 1.0 for both rows (100% LTV; split already done)
    - drawn_amount:       Float64   — mirrors ead_final (on-BS, no accrued interest)
    - interest:           Float64   — 0.0
    - nominal_amount:     Float64   — 0.0 (no off-BS component)
    - undrawn_amount:     Float64   — 0.0

References:
    - Art. 124F: RRE not-materially-dependent — secured portion up to 55% of property
                 value; 20% risk weight.
    - Art. 124L: residual portion — counterparty risk weight (natural person → 75%).
    - RE splitter output schema: src/rwa_calc/data/schemas.py RE_SPLITTER_OUTPUT_SCHEMA
    - OUTPUT_SCHEMA RE columns: src/rwa_calc/data/schemas.py lines 2066-2073
    - CR5 generator: src/rwa_calc/reporting/pillar3/generator.py _generate_cr5 (341-375)
    - B31 risk-weight bands: src/rwa_calc/reporting/pillar3/templates.py B31_CR5_RISK_WEIGHTS
    - B31 CR5 rows: src/rwa_calc/reporting/pillar3/templates.py B31_CR5_ROWS (mirrors B31_CR4_ROWS)
    - Scenario proposal: tmp/batch-20260530-1718/P2.25-scenario.md sections 2-4
"""

from __future__ import annotations

import polars as pl

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

SCENARIO_ID: str = "P2.25b"

# Framework — new sub-row bucketing is Basel 3.1 only
FRAMEWORK: str = "BASEL_3_1"

# Parent EAD (reconciliation check)
PARENT_EAD: float = 1_000_000.0

# --- Secured row (up to 55%-LTV portion, Art. 124F) ---
SECURED_EAD: float = 550_000.0  # 0.55 × property_value 1_000_000
SECURED_RW: float = 0.20  # Art. 124F preferential RW
SECURED_RWA: float = SECURED_EAD * SECURED_RW  # 110_000.0
SECURED_EXPOSURE_CLASS: str = "residential_mortgage"
SECURED_RE_SPLIT_ROLE: str = "secured"

# --- Residual row (above-55%-LTV portion, Art. 124L) ---
RESIDUAL_EAD: float = 450_000.0  # 1_000_000 − 550_000
RESIDUAL_RW: float = 0.75  # natural-person counterparty RW (Art. 124L)
RESIDUAL_RWA: float = RESIDUAL_EAD * RESIDUAL_RW  # 337_500.0
RESIDUAL_EXPOSURE_CLASS: str = "retail_other"  # original counterparty class
RESIDUAL_RE_SPLIT_ROLE: str = "residual"

# Both rows: not materially dependent on the property (this triggers the loan-split path)
MATERIALLY_DEPENDENT: bool = False

# LTV of the parent loan (100% — straddles the 55% split)
PROPERTY_LTV: float = 1.0

# --- B31 CR5 column refs ---
# B31_CR5_RISK_WEIGHTS (28 bands), zero-indexed:
#   index 5  → 0.20 (20%) → _letter_ref(5)  = "f"
#   index 15 → 0.75 (75%) → _letter_ref(15) = "p"
B31_COL_SECURED: str = "f"  # 20% band — secured row lands here
B31_COL_RESIDUAL: str = "p"  # 75% band — residual row lands here

# --- B31 CR5 row refs for the two new sub-rows ---
CR5_ROW_9F: str = "9f"  # "RE — secured up to 55% LTV"
CR5_ROW_9G: str = "9g"  # "RE — above 55% LTV (residual)"
CR5_ROW_9: str = "9"  # parent RE row (Total must still == PARENT_EAD)
CR5_TOTAL_ROW: str = "17"  # grand total (sub-rows excluded)

# --- Expected CR5 cell values ---

# Row 9f: only band "f" (20%) is populated; Total equals SECURED_EAD
EXPECTED_9F_BAND_F: float = SECURED_EAD  # 550_000.0
EXPECTED_9F_TOTAL: float = SECURED_EAD  # 550_000.0

# Row 9g: only band "p" (75%) is populated; Total equals RESIDUAL_EAD
EXPECTED_9G_BAND_P: float = RESIDUAL_EAD  # 450_000.0
EXPECTED_9G_TOTAL: float = RESIDUAL_EAD  # 450_000.0

# Row 9f + Row 9g Totals must reconcile to parent EAD
EXPECTED_SPLIT_TOTAL: float = PARENT_EAD  # 1_000_000.0

# Row 9 (whole RE class) Total still equals PARENT_EAD (no double-count into row 17)
EXPECTED_ROW_9_TOTAL: float = PARENT_EAD  # 1_000_000.0


# ---------------------------------------------------------------------------
# Public factories
# ---------------------------------------------------------------------------


def build_re_split_results_lf() -> pl.LazyFrame:
    """Return a post-split results LazyFrame representing the two CR5 rows.

    The LazyFrame carries ALL columns consumed by either the existing
    _generate_cr5 path OR the new RE-split bucketing logic.  Columns the
    test-writer does not need can be ignored.

    Shape: 2 rows (secured + residual).

    Column mapping to B31 CR5 generator inputs:
        ead_col  → ead_final (via _pick("ead_final", "final_ead", "ead"))
        rw_col   → risk_weight (via _pick("risk_weight", "sa_final_risk_weight"))
        ec_col   → exposure_class (via _pick("exposure_class"))
        new: re_split_role, materially_dependent_on_property, property_ltv
    """
    rows = [
        {
            # --- Secured portion (Art. 124F) ---
            "exposure_reference": "RE-SPLIT-SECURED-01",
            "approach_applied": "standardised",
            "exposure_class": SECURED_EXPOSURE_CLASS,
            "ead_final": SECURED_EAD,
            "rwa_final": SECURED_RWA,
            "risk_weight": SECURED_RW,
            "re_split_role": SECURED_RE_SPLIT_ROLE,
            "materially_dependent_on_property": MATERIALLY_DEPENDENT,
            "property_ltv": PROPERTY_LTV,
            # On-BS breakdown (all EAD is drawn; no off-BS component)
            "drawn_amount": SECURED_EAD,
            "interest": 0.0,
            "nominal_amount": 0.0,
            "undrawn_amount": 0.0,
        },
        {
            # --- Residual portion (Art. 124L, original counterparty class) ---
            "exposure_reference": "RE-SPLIT-RESIDUAL-01",
            "approach_applied": "standardised",
            "exposure_class": RESIDUAL_EXPOSURE_CLASS,
            "ead_final": RESIDUAL_EAD,
            "rwa_final": RESIDUAL_RWA,
            "risk_weight": RESIDUAL_RW,
            "re_split_role": RESIDUAL_RE_SPLIT_ROLE,
            "materially_dependent_on_property": MATERIALLY_DEPENDENT,
            "property_ltv": PROPERTY_LTV,
            # On-BS breakdown
            "drawn_amount": RESIDUAL_EAD,
            "interest": 0.0,
            "nominal_amount": 0.0,
            "undrawn_amount": 0.0,
        },
    ]
    schema = {
        "exposure_reference": pl.Utf8,
        "approach_applied": pl.Utf8,
        "exposure_class": pl.Utf8,
        "ead_final": pl.Float64,
        "rwa_final": pl.Float64,
        "risk_weight": pl.Float64,
        "re_split_role": pl.Utf8,
        "materially_dependent_on_property": pl.Boolean,
        "property_ltv": pl.Float64,
        "drawn_amount": pl.Float64,
        "interest": pl.Float64,
        "nominal_amount": pl.Float64,
        "undrawn_amount": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema).lazy()


# ---------------------------------------------------------------------------
# Self-check (also serves as clean-import verification)
# ---------------------------------------------------------------------------


def _verify_constants() -> None:
    """Verify hand-calculated scenario constants are internally consistent."""
    assert abs(SECURED_EAD + RESIDUAL_EAD - PARENT_EAD) < 1e-9, (
        f"EAD split does not reconcile: {SECURED_EAD} + {RESIDUAL_EAD} != {PARENT_EAD}"
    )
    assert abs(SECURED_RWA - SECURED_EAD * SECURED_RW) < 1e-9, (
        f"Secured RWA mismatch: {SECURED_RWA} != {SECURED_EAD} × {SECURED_RW}"
    )
    assert abs(RESIDUAL_RWA - RESIDUAL_EAD * RESIDUAL_RW) < 1e-9, (
        f"Residual RWA mismatch: {RESIDUAL_RWA} != {RESIDUAL_EAD} × {RESIDUAL_RW}"
    )
    assert EXPECTED_9F_TOTAL + EXPECTED_9G_TOTAL == EXPECTED_SPLIT_TOTAL, (
        f"Sub-row totals do not sum to parent EAD: "
        f"{EXPECTED_9F_TOTAL} + {EXPECTED_9G_TOTAL} != {EXPECTED_SPLIT_TOTAL}"
    )
    # B31 band cross-check: index 5 → "f", index 15 → "p"
    assert B31_COL_SECURED == "f", f"Expected column ref 'f' for 20%, got {B31_COL_SECURED!r}"
    assert B31_COL_RESIDUAL == "p", f"Expected column ref 'p' for 75%, got {B31_COL_RESIDUAL!r}"


def _verify_lf() -> None:
    """Verify the LazyFrame builds with the expected schema and values."""
    lf = build_re_split_results_lf()
    df = lf.collect()

    assert df.height == 2, f"Expected 2 rows, got {df.height}"

    required_cols = {
        "exposure_reference",
        "approach_applied",
        "exposure_class",
        "ead_final",
        "rwa_final",
        "risk_weight",
        "re_split_role",
        "materially_dependent_on_property",
        "property_ltv",
        "drawn_amount",
        "interest",
        "nominal_amount",
        "undrawn_amount",
    }
    assert required_cols.issubset(set(df.columns)), (
        f"Missing columns: {required_cols - set(df.columns)}"
    )

    # Secured row
    secured = df.filter(pl.col("re_split_role") == "secured")
    assert secured.height == 1, "Expected exactly one secured row"
    assert secured["ead_final"][0] == SECURED_EAD
    assert secured["risk_weight"][0] == SECURED_RW
    assert secured["exposure_class"][0] == SECURED_EXPOSURE_CLASS
    assert secured["materially_dependent_on_property"][0] is False

    # Residual row
    residual = df.filter(pl.col("re_split_role") == "residual")
    assert residual.height == 1, "Expected exactly one residual row"
    assert residual["ead_final"][0] == RESIDUAL_EAD
    assert residual["risk_weight"][0] == RESIDUAL_RW
    assert residual["exposure_class"][0] == RESIDUAL_EXPOSURE_CLASS
    assert residual["materially_dependent_on_property"][0] is False

    # EAD reconciliation
    total_ead = float(df["ead_final"].sum())
    assert abs(total_ead - PARENT_EAD) < 1e-9, (
        f"EAD reconciliation failed: {total_ead} != {PARENT_EAD}"
    )

    # All rows are standardised SA
    assert (df["approach_applied"] == "standardised").all()


if __name__ == "__main__":
    _verify_constants()
    _verify_lf()
    print("P2.25b fixture self-check passed.")
    print(
        f"  Secured row:  EAD={SECURED_EAD:,.0f}, RW={SECURED_RW:.0%}, "
        f"class={SECURED_EXPOSURE_CLASS!r}, role={SECURED_RE_SPLIT_ROLE!r}"
    )
    print(
        f"  Residual row: EAD={RESIDUAL_EAD:,.0f}, RW={RESIDUAL_RW:.0%}, "
        f"class={RESIDUAL_EXPOSURE_CLASS!r}, role={RESIDUAL_RE_SPLIT_ROLE!r}"
    )
    print(
        f"  Parent EAD reconciles: {SECURED_EAD:,.0f} + {RESIDUAL_EAD:,.0f} = "
        f"{SECURED_EAD + RESIDUAL_EAD:,.0f}"
    )
    print(
        f"  B31 CR5 bands: secured → col {B31_COL_SECURED!r} (20%), "
        f"residual → col {B31_COL_RESIDUAL!r} (75%)"
    )
    print(f"  Expected: cr5[{CR5_ROW_9F!r}][{B31_COL_SECURED!r}] == {EXPECTED_9F_BAND_F:,.0f}")
    print(f"  Expected: cr5[{CR5_ROW_9G!r}][{B31_COL_RESIDUAL!r}] == {EXPECTED_9G_BAND_P:,.0f}")
