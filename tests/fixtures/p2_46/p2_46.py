"""
P2.46 fixture builder: Art. 150(1) PPU provenance enum on model_permissions.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
        (domain/enums.py PpuReason, classifier.py _resolve_model_permissions,
         reporting/corep/templates.py C 07.00 rows 0050/0060)

Scenario design (P2.46 — UK CRR Art. 150(1)/(148), COREP C 07.00/OF 07.00):

    One CRR run (PermissionMode.IRB, RegulatoryFramework.CRR) with three
    corporate SA-routed exposures that differ ONLY by SA provenance:

        EXP-P246-PPU:
            Counterparty CP-P246-PPU, rated via model_id MODEL-CORP-PPU.
            Model permission: approach=standardised, ppu_reason=art_150_1_c.
            Routing: PPU under CRR Art. 150(1)(c) → SA.
            COREP C 07.00 row 0050 ("of which: PPU of SA").

        EXP-P246-ROLLOUT:
            Counterparty CP-P246-ROLLOUT, rated via model_id MODEL-CORP-ROLLOUT.
            Model permission: approach=standardised, ppu_reason=art_148_rollout.
            Routing: sequential IRB roll-out Art. 148 → SA.
            COREP C 07.00 row 0060 ("of which: sequential IRB implementation").

        EXP-P246-NOPERM:
            Counterparty CP-P246-NOPERM, no model_id in rating row (null).
            No matching model_permissions row → ppu_reason null.
            Routing: SA fallback (no permission match) → neither row 0050 nor 0060.
            Only appears in row 0010 (Total SA EAD).

    All three are senior unrated corporate loans, GBP 1,000,000 drawn.
    SA risk weight (unrated corporate) = 1.00 (100%).
    EAD each = 1,000,000; RWA each = 1,000,000.

    Load-bearing COREP anti-degenerate invariant:
        Row 0010 (Total SA EAD) = 3,000,000
        Row 0050 (PPU, ppu_reason in art_150_1_*) = 1,000,000
        Row 0060 (roll-out, ppu_reason art_148_rollout) = 1,000,000
        Residual (0010 - 0050 - 0060) = 1,000,000 > 0
        Pre-fix: rows 0050/0060 both null (neither is populated).
        Post-fix: rows 0050/0060 discriminated correctly.

    model_id enters at counterparty grain via RATINGS_SCHEMA.internal_model_id
    (the classifier aliases RATINGS_SCHEMA.model_id -> model_id at ~L1408 in
    classifier.py). Three counterparties each with one rating row exercises the
    production rating-inheritance path.

ppu_reason is a NEW column on MODEL_PERMISSIONS_SCHEMA not yet present in
data/schemas.py at this stage (engine-implementer will add it in the next wave).
The parquet pre-populates ppu_reason via with_columns (same technique as the
rating_is_inferred column in p2_44.py) so the parquet is ready for the engine
to consume once the schema is extended.

approach="standardised" is also a NEW allowed value for VALID_MODEL_PERMISSION_APPROACHES
(currently {"foundation_irb", "advanced_irb", "slotting"}). The engine-implementer
must add "standardised" to that set so PPU/roll-out rows pass input validation.
The fixture bypasses dtypes_of validation (parquet write only) so this is safe.

References:
    - CRR Art. 150(1)(a)-(j): PPU conditions (model-permissions.md L56-108)
    - CRR Art. 148: sequential IRB roll-out (model-permissions.md L31)
    - COREP C 07.00/OF 07.00 Section 1 rows 0050/0060 (templates.py L298-299)
    - data/schemas.py L733 MODEL_PERMISSIONS_SCHEMA
    - data/schemas.py L1368 VALID_MODEL_PERMISSION_APPROACHES
    - engine/classifier.py L1374-1492 _resolve_model_permissions / sa_block
    - reporting/corep/generator.py L3703-3725 _c07_section1_subset

Usage:
    cd /home/philm/projects/rwa_calculator/tmp/worktrees/P2.46
    PYTHONPATH=src /home/philm/projects/rwa_calculator/.venv/bin/python \\
        tests/fixtures/p2_46/p2_46.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

SCENARIO_ID: str = "P2.46"
FRAMEWORK: str = "CRR"

# Counterparty references
CP_PPU: str = "CP-P246-PPU"
CP_ROLLOUT: str = "CP-P246-ROLLOUT"
CP_NOPERM: str = "CP-P246-NOPERM"

# Loan references
LOAN_PPU: str = "EXP-P246-PPU"
LOAN_ROLLOUT: str = "EXP-P246-ROLLOUT"
LOAN_NOPERM: str = "EXP-P246-NOPERM"

# Rating references
RATING_PPU: str = "RTG-P246-PPU"
RATING_ROLLOUT: str = "RTG-P246-ROLLOUT"
RATING_NOPERM: str = "RTG-P246-NOPERM"

# Model IDs (unique to this scenario — avoid cross-test interference)
# MODEL-CORP-PPU:     approach=standardised, ppu_reason=art_150_1_c
# MODEL-CORP-ROLLOUT: approach=standardised, ppu_reason=art_148_rollout
# CP-P246-NOPERM has no model_id in its rating row → no permission match
MODEL_CORP_PPU: str = "MODEL-CORP-PPU-P246"
MODEL_CORP_ROLLOUT: str = "MODEL-CORP-ROLLOUT-P246"

# ppu_reason values (load-bearing enum strings — must match PpuReason enum
# members that engine-implementer will add to domain/enums.py)
PPU_REASON_ART_150_1_C: str = "art_150_1_c"    # Art. 150(1)(c) PPU condition
PPU_REASON_ART_148: str = "art_148_rollout"      # Art. 148 sequential roll-out

# Loan economics (all three identical)
DRAWN_AMOUNT: float = 1_000_000.0
PROVISIONS: float = 0.0

# Dates
VALUE_DATE: date = date(2025, 1, 1)
MATURITY_DATE: date = date(2026, 6, 30)   # ~18 months — well above 1y floor
RATING_DATE: date = date(2025, 1, 2)
REPORTING_DATE: date = date(2025, 6, 30)  # CRR run (before 2027-01-01)

# Expected outputs (test-writer anchors)
EXPECTED_SA_RISK_WEIGHT: float = 1.00     # unrated corporate SA = 100%
EXPECTED_EAD: float = 1_000_000.0
EXPECTED_RWA: float = 1_000_000.0
EXPECTED_APPROACH_APPLIED: str = "standardised"

# COREP C 07.00 / OF 07.00 Section 1 row references
COREP_ROW_TOTAL_SA: str = "0010"        # Total SA EAD = 3,000,000
COREP_ROW_PPU: str = "0050"             # PPU of SA = 1,000,000 (art_150_1_c)
COREP_ROW_ROLLOUT: str = "0060"         # Sequential IRB = 1,000,000 (art_148_rollout)

# Anti-degenerate invariant values
EXPECTED_TOTAL_EAD: float = 3_000_000.0     # three exposures × 1m each
EXPECTED_PPU_EAD: float = 1_000_000.0       # EXP-P246-PPU only
EXPECTED_ROLLOUT_EAD: float = 1_000_000.0   # EXP-P246-ROLLOUT only
EXPECTED_RESIDUAL_EAD: float = 1_000_000.0  # EXP-P246-NOPERM (0010 - 0050 - 0060)


# ---------------------------------------------------------------------------
# Internal dataclasses (thin wrappers for type-safety)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
        }


@dataclass(frozen=True)
class _Loan:
    loan_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    drawn_amount: float
    interest: float
    seniority: str
    is_payroll_loan: bool
    is_buy_to_let: bool
    is_under_construction: bool

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "product_type": self.product_type,
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "seniority": self.seniority,
            "is_payroll_loan": self.is_payroll_loan,
            "is_buy_to_let": self.is_buy_to_let,
            "is_under_construction": self.is_under_construction,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p246_counterparties() -> pl.DataFrame:
    """Return the 3 P2.46 corporate counterparties as a DataFrame.

    All three are entity_type="corporate", GB, GBP.  They differ only in
    their names and references — the PPU / roll-out / no-permission
    discrimination is carried entirely by the rating model_id (and hence
    the model_permissions lookup), not by any counterparty field.

    apply_fi_scalar=False: non-FSE — no FI scalar complication.
    is_managed_as_retail=False: corporate classification.
    """
    rows = [
        _Counterparty(
            counterparty_reference=CP_PPU,
            counterparty_name="P2.46 Corp PPU Art 150(1)(c)",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
        _Counterparty(
            counterparty_reference=CP_ROLLOUT,
            counterparty_name="P2.46 Corp Art 148 Rollout",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
        _Counterparty(
            counterparty_reference=CP_NOPERM,
            counterparty_name="P2.46 Corp No Permission",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p246_loans() -> pl.DataFrame:
    """Return the 3 P2.46 loan rows as a DataFrame.

    All three are senior unsecured GBP 1,000,000 term loans.
    EAD = drawn_amount = 1,000,000 each (no interest, on-balance sheet).
    Maturity is ~18 months from VALUE_DATE — well above the 1-year floor.
    SA risk weight (unrated corporate) = 100%; RWA = EAD × 1.00 = 1,000,000.
    """
    rows = [
        _Loan(
            loan_reference=LOAN_PPU,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=CP_PPU,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
            is_payroll_loan=False,
            is_buy_to_let=False,
            is_under_construction=False,
        ),
        _Loan(
            loan_reference=LOAN_ROLLOUT,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=CP_ROLLOUT,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
            is_payroll_loan=False,
            is_buy_to_let=False,
            is_under_construction=False,
        ),
        _Loan(
            loan_reference=LOAN_NOPERM,
            product_type="TERM_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=CP_NOPERM,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
            is_payroll_loan=False,
            is_buy_to_let=False,
            is_under_construction=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p246_ratings() -> pl.DataFrame:
    """Return the 3 P2.46 rating rows as a DataFrame.

    Each counterparty has one rating row.  model_id is the discriminator:
        CP_PPU     → MODEL_CORP_PPU      (approach=standardised, ppu_reason=art_150_1_c)
        CP_ROLLOUT → MODEL_CORP_ROLLOUT  (approach=standardised, ppu_reason=art_148_rollout)
        CP_NOPERM  → model_id=None       (no matching permission → SA fallback)

    No external CQS is set (cqs=None, unrated) — the SA path (100% RW) is
    exercised directly without rating-substitution complications.
    rating_type="internal" for the two permissioned counterparties (standard
    for IRB runs); "internal" with null model_id for CP_NOPERM confirms the
    no-match path is independent of rating_type.
    """
    rows = [
        {
            "rating_reference": RATING_PPU,
            "counterparty_reference": CP_PPU,
            "rating_type": "internal",
            "rating_agency": "internal",
            "rating_value": None,
            "cqs": None,
            "pd": None,
            "rating_date": RATING_DATE,
            "is_solicited": False,
            "model_id": MODEL_CORP_PPU,
            "is_short_term": False,
            "scope_type": None,
            "scope_id": None,
        },
        {
            "rating_reference": RATING_ROLLOUT,
            "counterparty_reference": CP_ROLLOUT,
            "rating_type": "internal",
            "rating_agency": "internal",
            "rating_value": None,
            "cqs": None,
            "pd": None,
            "rating_date": RATING_DATE,
            "is_solicited": False,
            "model_id": MODEL_CORP_ROLLOUT,
            "is_short_term": False,
            "scope_type": None,
            "scope_id": None,
        },
        {
            "rating_reference": RATING_NOPERM,
            "counterparty_reference": CP_NOPERM,
            "rating_type": "internal",
            "rating_agency": "internal",
            "rating_value": None,
            "cqs": None,
            "pd": None,
            "rating_date": RATING_DATE,
            "is_solicited": False,
            "model_id": None,       # no model_id → no permissions match → ppu_reason null
            "is_short_term": False,
            "scope_type": None,
            "scope_id": None,
        },
    ]
    return pl.DataFrame(rows, schema=dtypes_of(RATINGS_SCHEMA))


def create_p246_model_permissions() -> pl.DataFrame:
    """Return the 2 P2.46 model permission rows as a DataFrame.

    Both permissions route to SA (approach=standardised) — they differ only in
    ppu_reason, which identifies the legal basis for the SA treatment:

        MODEL_CORP_PPU:     approach=standardised, ppu_reason=art_150_1_c
            Permanent partial use under CRR Art. 150(1)(c).
            COREP C 07.00 / OF 07.00 row 0050: "of which: PPU of SA".

        MODEL_CORP_ROLLOUT: approach=standardised, ppu_reason=art_148_rollout
            Sequential roll-out of the IRB approach under CRR Art. 148.
            COREP C 07.00 / OF 07.00 row 0060: "of which: sequential IRB".

    SCHEMA NOTE: ppu_reason is NOT yet present in MODEL_PERMISSIONS_SCHEMA at
    this stage.  The base DataFrame is built using dtypes_of(MODEL_PERMISSIONS_SCHEMA)
    (which omits ppu_reason) and then the column is appended via with_columns —
    the same technique used for rating_is_inferred in p2_44.py.  The engine-
    implementer will add ppu_reason as ColumnSpec(pl.String, required=False)
    to MODEL_PERMISSIONS_SCHEMA so subsequent schema-validated reads pick it up.

    APPROACH NOTE: approach="standardised" is also not yet in
    VALID_MODEL_PERMISSION_APPROACHES.  The engine-implementer must add it.
    The fixture bypasses the validation-set check (it is a parquet write
    only) so this is safe at the fixture stage.

    References:
        - CRR Art. 150(1)(a)-(j): PPU conditions → collapse to row 0050
        - CRR Art. 148: sequential roll-out → row 0060
        - data/schemas.py L1368 VALID_MODEL_PERMISSION_APPROACHES
        - reporting/corep/templates.py L298-299 (C 07.00 rows 0050/0060)
    """
    # Build base frame with current schema (no ppu_reason column yet)
    base_rows = [
        {
            "model_id": MODEL_CORP_PPU,
            "exposure_class": "corporate",
            "approach": "standardised",
            "country_codes": None,
            "excluded_book_codes": None,
        },
        {
            "model_id": MODEL_CORP_ROLLOUT,
            "exposure_class": "corporate",
            "approach": "standardised",
            "country_codes": None,
            "excluded_book_codes": None,
        },
    ]
    df = pl.DataFrame(base_rows, schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))
    # Append the new ppu_reason column (not yet in MODEL_PERMISSIONS_SCHEMA).
    # Uses pl.Series directly so each row gets its own string value.
    return df.with_columns(
        pl.Series("ppu_reason", [PPU_REASON_ART_150_1_C, PPU_REASON_ART_148])
    )


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p246_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """Write all P2.46 parquet files and return a name-to-path mapping.

    Files produced:
        counterparty.parquet      — 3 rows (CP-P246-PPU, CP-P246-ROLLOUT, CP-P246-NOPERM)
        loan.parquet              — 3 rows (EXP-P246-PPU, EXP-P246-ROLLOUT, EXP-P246-NOPERM)
        rating.parquet            — 3 rows (model_id set on PPU/ROLLOUT, null on NOPERM)
        model_permission.parquet  — 2 rows (standardised + ppu_reason column)

    The model_permission parquet carries the extra ppu_reason column beyond
    MODEL_PERMISSIONS_SCHEMA (engine-implementer will add it to the schema).

    Args:
        output_dir: Target directory.  Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_p246_counterparties()),
        ("loan", create_p246_loans()),
        ("rating", create_p246_ratings()),
        ("model_permission", create_p246_model_permissions()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P2.46 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<22} {len(df):>2} row(s)  ->  {path.name}")
    print("-" * 70)
    print("Scenario: Art. 150(1) PPU provenance enum on model_permissions (CRR IRB run)")
    print(f"  {LOAN_PPU:<22} SA via PPU Art.150(1)(c)  ppu_reason={PPU_REASON_ART_150_1_C!r}")
    print(f"  {LOAN_ROLLOUT:<22} SA via Art.148 rollout    ppu_reason={PPU_REASON_ART_148!r}")
    print(f"  {LOAN_NOPERM:<22} SA fallback (no perm)     ppu_reason=null")
    print()
    print("  COREP C 07.00 / OF 07.00 Section 1 expected values:")
    print(f"    Row {COREP_ROW_TOTAL_SA} (Total SA EAD)     = {EXPECTED_TOTAL_EAD:>12,.0f}")
    print(f"    Row {COREP_ROW_PPU} (PPU of SA)        = {EXPECTED_PPU_EAD:>12,.0f}")
    print(f"    Row {COREP_ROW_ROLLOUT} (Sequential IRB)   = {EXPECTED_ROLLOUT_EAD:>12,.0f}")
    print(f"    Residual (0010-0050-0060)  = {EXPECTED_RESIDUAL_EAD:>12,.0f} (>0, anti-degenerate)")


# ---------------------------------------------------------------------------
# Self-check (smoke-test schema invariants without running the pipeline)
# ---------------------------------------------------------------------------


def _verify_fixtures() -> None:
    """Smoke-check all DataFrames: shapes, ppu_reason values, model_id integrity."""
    cp_df = create_p246_counterparties()
    ln_df = create_p246_loans()
    rt_df = create_p246_ratings()
    mp_df = create_p246_model_permissions()

    # Shape checks
    assert cp_df.height == 3, f"Expected 3 counterparties, got {cp_df.height}"
    assert ln_df.height == 3, f"Expected 3 loans, got {ln_df.height}"
    assert rt_df.height == 3, f"Expected 3 ratings, got {rt_df.height}"
    assert mp_df.height == 2, f"Expected 2 model_permissions, got {mp_df.height}"

    # ppu_reason column is present on model_permissions
    assert "ppu_reason" in mp_df.columns, "ppu_reason column must be present on model_permissions"

    # ppu_reason values are correctly assigned
    ppu_row = mp_df.filter(pl.col("model_id") == MODEL_CORP_PPU)
    assert ppu_row.height == 1
    assert ppu_row["ppu_reason"][0] == PPU_REASON_ART_150_1_C, (
        f"MODEL_CORP_PPU ppu_reason must be {PPU_REASON_ART_150_1_C!r}, "
        f"got {ppu_row['ppu_reason'][0]!r}"
    )

    rollout_row = mp_df.filter(pl.col("model_id") == MODEL_CORP_ROLLOUT)
    assert rollout_row.height == 1
    assert rollout_row["ppu_reason"][0] == PPU_REASON_ART_148, (
        f"MODEL_CORP_ROLLOUT ppu_reason must be {PPU_REASON_ART_148!r}, "
        f"got {rollout_row['ppu_reason'][0]!r}"
    )

    # Both permissions are approach=standardised
    for row in mp_df.iter_rows(named=True):
        assert row["approach"] == "standardised", (
            f"All P2.46 model_permissions must be approach=standardised, "
            f"got {row['approach']!r} for model_id={row['model_id']!r}"
        )

    # Ratings: PPU and ROLLOUT have model_ids; NOPERM has null
    rt_ppu = rt_df.filter(pl.col("counterparty_reference") == CP_PPU)
    assert rt_ppu["model_id"][0] == MODEL_CORP_PPU, (
        f"CP_PPU rating must reference {MODEL_CORP_PPU!r}"
    )

    rt_rollout = rt_df.filter(pl.col("counterparty_reference") == CP_ROLLOUT)
    assert rt_rollout["model_id"][0] == MODEL_CORP_ROLLOUT, (
        f"CP_ROLLOUT rating must reference {MODEL_CORP_ROLLOUT!r}"
    )

    rt_noperm = rt_df.filter(pl.col("counterparty_reference") == CP_NOPERM)
    assert rt_noperm["model_id"][0] is None, (
        f"CP_NOPERM rating must have null model_id (got {rt_noperm['model_id'][0]!r})"
    )

    # Loan amounts: all 1,000,000
    for row in ln_df.iter_rows(named=True):
        assert row["drawn_amount"] == DRAWN_AMOUNT, (
            f"All loans must have drawn_amount={DRAWN_AMOUNT}, "
            f"got {row['drawn_amount']} for {row['loan_reference']!r}"
        )

    # All counterparties are corporate, GB
    for row in cp_df.iter_rows(named=True):
        assert row["entity_type"] == "corporate", (
            f"All counterparties must be entity_type=corporate, "
            f"got {row['entity_type']!r} for {row['counterparty_reference']!r}"
        )
        assert row["country_code"] == "GB", (
            f"All counterparties must be GB, "
            f"got {row['country_code']!r} for {row['counterparty_reference']!r}"
        )

    # COREP sum invariant: EAD sum = 3 × 1,000,000
    total_ead = ln_df["drawn_amount"].sum()
    assert total_ead == EXPECTED_TOTAL_EAD, (
        f"Total EAD must be {EXPECTED_TOTAL_EAD}, got {total_ead}"
    )

    # Anti-degenerate: EXPECTED_RESIDUAL_EAD > 0 and
    # PPU + ROLLOUT + RESIDUAL = TOTAL
    assert EXPECTED_PPU_EAD + EXPECTED_ROLLOUT_EAD + EXPECTED_RESIDUAL_EAD == EXPECTED_TOTAL_EAD, (
        "Row 0050 + 0060 + residual must sum to row 0010 total"
    )
    assert EXPECTED_RESIDUAL_EAD > 0.0, "Residual EAD must be > 0 (anti-degenerate)"


def main() -> None:
    """Entry point for standalone generation."""
    _verify_fixtures()
    saved = save_p246_fixtures()
    print_summary(saved)
    print()
    print("P2.46 fixture self-check passed.")
    print(f"  3 counterparties: {CP_PPU}, {CP_ROLLOUT}, {CP_NOPERM}")
    print(f"  3 loans (GBP 1,000,000 each, senior unrated corporate)")
    print(f"  3 ratings (model_id on PPU/ROLLOUT, null on NOPERM)")
    print(f"  2 model_permissions (approach=standardised, ppu_reason column appended)")


if __name__ == "__main__":
    main()
