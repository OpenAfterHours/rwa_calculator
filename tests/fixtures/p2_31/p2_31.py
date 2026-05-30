"""
P2.31 fixture builder: Annex I concrete-product to risk_type mapping table.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (data/schemas.py,
    data/tables/ccf.py, engine/ccf.py)

Scenario design (P2.31 — CRR Annex I / PRA PS1/26 Table A1 product-to-risk_type fill):

    No data-layer table currently maps concrete OBS product descriptions (e.g.
    "ACCEPTANCE", "PERFORMANCE_BOND") to the abstract Annex I ``risk_type`` used by
    the CCF engine.  P2.31 adds:

        (a) A new optional input column ``obs_product`` (pl.String) on
            CONTINGENTS_SCHEMA (and FACILITY_SCHEMA) — a normalised OBS product
            identifier distinct from the free-text ``product_type``.

        (b) A framework-invariant lookup table ``ANNEX1_PRODUCT_RISK_TYPE`` in
            ``data/tables/ccf.py`` that maps each canonical product key to the
            appropriate ``risk_type`` bucket.

        (c) Fill logic in ``engine/ccf.py`` that, when ``risk_type`` is null/empty,
            uses ``obs_product`` to resolve the bucket before the existing
            ``build_sa_ccf_expr`` step.  Explicit ``risk_type`` always wins.

    All products in scope resolve framework-invariantly under SA:
        ACCEPTANCE       -> FR   (CCF 1.00, CRR Annex I para 1 / PS1/26 Table A1 Row 1)
        PERFORMANCE_BOND -> MLR  (CCF 0.20, Annex I Row 6(b))
        DOCUMENTARY_CREDIT / TRADE_LC -> MLR (CCF 0.20, Annex I Row 6(a))

    Scenario rows (all contingents, nominal £2,000,000 each):

        CONT_P231_ACCEPT (product-fill ACCEPTANCE):
            obs_product="ACCEPTANCE", risk_type=None
            Expected: resolved risk_type="FR", ccf=1.00, ead_from_ccf=2_000_000

        CONT_P231_PERFBOND (product-fill PERFORMANCE_BOND):
            obs_product="PERFORMANCE_BOND", risk_type=None
            Expected: resolved risk_type="MLR", ccf=0.20, ead_from_ccf=400_000

        CONT_P231_DOCLC (product-fill DOCUMENTARY_CREDIT):
            obs_product="DOCUMENTARY_CREDIT", risk_type=None
            Expected: resolved risk_type="MLR", ccf=0.20, ead_from_ccf=400_000

        CONT_P231_OVERRIDE (explicit-wins control):
            obs_product="ACCEPTANCE", risk_type="LR"  (explicit wins)
            Expected: retained risk_type="LR", ccf=0.00 (LR=0%), ead_from_ccf=0

    Citation: CRR (EU 575/2013) Annex I paras 1-4 / Art. 111(1);
    PRA PS1/26 App 1 Art. 111(1) Table A1 Rows 1 and 6 (ps126app1.pdf pp.29-32).

Implementation note — why Python builder, not parquet:

    ``obs_product`` is not yet declared in CONTINGENTS_SCHEMA (that is
    engine-implementer's wave).  Parquet files written via ``dtypes_of(CONTINGENTS_SCHEMA)``
    would silently drop the column if the schema helper only emits declared columns.
    Following the precedent of P2.32 (``is_purchased_receivable_commitment``) and
    P2.33 (``is_uk_residential_mortgage_commitment``), we:

        1. Build a base DataFrame from known schema columns.
        2. Attach ``obs_product`` explicitly via ``with_columns(pl.Series(..., dtype=pl.String))``.
        3. Write parquet — the extra column is preserved because parquet serialises
           the actual column list, not a fixed schema envelope.

    The public ``create_p231_contingents()`` factory returns the full DataFrame
    (including ``obs_product``) so tests can consume it without a disk round-trip.
    The test-writer should import this factory directly rather than reading the parquet.

Hand-calculations (SA, CalculationConfig.crr() or CalculationConfig.basel_3_1()):

    All rows: nominal_amount = 2_000_000, drawn_amount = 0 (contingent)
    EAD formula: ead_from_ccf = nominal × CCF

    ACCEPTANCE  -> FR   -> CCF=1.00 -> EAD = 2_000_000 × 1.00 = 2_000_000
    PERF_BOND   -> MLR  -> CCF=0.20 -> EAD = 2_000_000 × 0.20 =   400_000
    DOC_CREDIT  -> MLR  -> CCF=0.20 -> EAD = 2_000_000 × 0.20 =   400_000
    OVERRIDE    -> LR   -> CCF=0.00 -> EAD = 2_000_000 × 0.00 =         0
        (explicit risk_type="LR" supplied; obs_product="ACCEPTANCE" is ignored)

References:
    - CRR Annex I paras 1, 2, 3, 4: OBS item risk bands
    - CRR Art. 111(1): SA EAD = drawn + CCF × undrawn
    - PRA PS1/26 App 1 Art. 111(1) Table A1 Row 1 (FR/100%) and Row 6 (MLR/20%)
    - docs/assets/ps126app1.pdf pp.29-32
    - docs/specifications/crr/credit-conversion-factors.md lines 86-98, 156

Usage:
    PYTHONPATH=/home/philm/projects/rwa_calculator/tmp/worktrees/P2.31/src \\
        /home/philm/projects/rwa_calculator/.venv/bin/python \\
        tests/fixtures/p2_31/p2_31.py
    PYTHONPATH=... python tests/fixtures/p2_31/p2_31.py --data-dir /path/to/output
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import CONTINGENTS_SCHEMA, COUNTERPARTY_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

SCENARIO_ID: str = "P2.31"

# Counterparty reference
COUNTERPARTY_REF: str = "CP_P231_CORP"

# Contingent references
CONT_REF_ACCEPT: str = "CONT_P231_ACCEPT"  # obs_product=ACCEPTANCE -> FR
CONT_REF_PERFBOND: str = "CONT_P231_PERFBOND"  # obs_product=PERFORMANCE_BOND -> MLR
CONT_REF_DOCLC: str = "CONT_P231_DOCLC"  # obs_product=DOCUMENTARY_CREDIT -> MLR
CONT_REF_OVERRIDE: str = (
    "CONT_P231_OVERRIDE"  # explicit risk_type=LR wins over obs_product=ACCEPTANCE
)

# obs_product values (normalised canonical keys)
OBS_PRODUCT_ACCEPTANCE: str = "ACCEPTANCE"
OBS_PRODUCT_PERFBOND: str = "PERFORMANCE_BOND"
OBS_PRODUCT_DOCLC: str = "DOCUMENTARY_CREDIT"

# Expected resolved risk_types (post-fill)
RESOLVED_RISK_TYPE_ACCEPT: str = "FR"  # Annex I para 1 / Table A1 Row 1
RESOLVED_RISK_TYPE_PERFBOND: str = "MLR"  # Annex I Row 6(b)
RESOLVED_RISK_TYPE_DOCLC: str = "MLR"  # Annex I Row 6(a)
RESOLVED_RISK_TYPE_OVERRIDE: str = "LR"  # explicit wins — obs_product ignored

# Expected CCF values (SA, framework-invariant for these products)
EXPECTED_CCF_ACCEPT: float = 1.00  # FR: direct credit substitute
EXPECTED_CCF_PERFBOND: float = 0.20  # MLR: performance bond
EXPECTED_CCF_DOCLC: float = 0.20  # MLR: documentary credit
EXPECTED_CCF_OVERRIDE: float = 0.00  # LR: unconditionally cancellable / 0%

# Shared economics
NOMINAL_AMOUNT: float = 2_000_000.00

# Expected EAD values
EXPECTED_EAD_ACCEPT: float = NOMINAL_AMOUNT * EXPECTED_CCF_ACCEPT  # 2_000_000
EXPECTED_EAD_PERFBOND: float = NOMINAL_AMOUNT * EXPECTED_CCF_PERFBOND  # 400_000
EXPECTED_EAD_DOCLC: float = NOMINAL_AMOUNT * EXPECTED_CCF_DOCLC  # 400_000
EXPECTED_EAD_OVERRIDE: float = NOMINAL_AMOUNT * EXPECTED_CCF_OVERRIDE  # 0

# Dates
VALUE_DATE: date = date(2027, 1, 1)
MATURITY_DATE: date = date(2028, 6, 30)

# Regulatory scalar cross-references (data/tables/ccf.py)
SA_CCF_FR: float = 1.00  # SA_CCF_CRR["FR"] = SA_CCF_B31["FR"] = 1.00
SA_CCF_MLR: float = 0.20  # SA_CCF_CRR["MLR"] = SA_CCF_B31["MLR"] = 0.20
SA_CCF_LR: float = 0.00  # SA_CCF_CRR["LR"] = SA_CCF_B31["LR"] = 0.00 (CRR) / 0.10 (B31)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P2.31 counterparty row — unrated GB corporate obligor."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool
    is_natural_person: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
            "is_natural_person": self.is_natural_person,
        }


@dataclass(frozen=True)
class _Contingent:
    """
    P2.31 contingent row.

    ``obs_product`` is the NEW column (not yet in CONTINGENTS_SCHEMA).
    It is serialised separately in ``create_p231_contingents()`` via an explicit
    ``with_columns`` call, matching the pattern used by P2.32 / P2.33.

    ``risk_type`` is None for the three product-fill rows to force the engine
    to resolve the bucket from ``obs_product``.  The override row supplies an
    explicit ``risk_type="LR"`` to confirm explicit-wins semantics.
    """

    contingent_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    nominal_amount: float
    lgd: float
    beel: float
    seniority: str
    obs_product: str  # NEW — not yet in CONTINGENTS_SCHEMA; serialised separately
    risk_type: str | None  # None for product-fill rows; explicit for override row

    def to_dict_base(self) -> dict:
        """Return only columns present in CONTINGENTS_SCHEMA (excludes obs_product)."""
        return {
            "contingent_reference": self.contingent_reference,
            "product_type": self.product_type,
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "nominal_amount": self.nominal_amount,
            "lgd": self.lgd,
            "beel": self.beel,
            "seniority": self.seniority,
            "risk_type": self.risk_type,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p231_counterparties() -> pl.DataFrame:
    """
    Return the P2.31 counterparty (unrated GB corporate) as a DataFrame.

    CP_P231_CORP: entity_type="corporate", GB, unrated, non-SME.  Classification
    routes to SA corporate exposure class (100% RW unrated).  Assertions for this
    scenario are CCF/EAD-scoped only; RW is not asserted.
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF,
            counterparty_name="P2.31 Corp — Annex I obs_product to risk_type mapping",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_natural_person=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p231_contingents() -> pl.DataFrame:
    """
    Return all four P2.31 contingent rows as a DataFrame.

    Three product-fill rows (ACCEPT / PERFBOND / DOCLC) carry ``obs_product``
    and null ``risk_type``, so the engine resolves the bucket via the new
    ``ANNEX1_PRODUCT_RISK_TYPE`` lookup.  The override row carries an explicit
    ``risk_type="LR"`` alongside ``obs_product="ACCEPTANCE"`` to confirm that
    explicit values always win.

    Implementation note:
        ``obs_product`` is not yet in CONTINGENTS_SCHEMA.  We build base columns
        from the schema, then attach ``obs_product`` via ``with_columns``, matching
        the pattern from P2.32 (``is_purchased_receivable_commitment``) and P2.33
        (``is_uk_residential_mortgage_commitment``).  Parquet preserves the extra
        column because it serialises the actual column list, not a schema envelope.

    Rows:
        CONT_P231_ACCEPT:    obs_product=ACCEPTANCE,         risk_type=None -> FR,  EAD=2_000_000
        CONT_P231_PERFBOND:  obs_product=PERFORMANCE_BOND,   risk_type=None -> MLR, EAD=400_000
        CONT_P231_DOCLC:     obs_product=DOCUMENTARY_CREDIT, risk_type=None -> MLR, EAD=400_000
        CONT_P231_OVERRIDE:  obs_product=ACCEPTANCE,         risk_type=LR   -> LR,  EAD=0
    """
    rows = [
        _Contingent(
            contingent_reference=CONT_REF_ACCEPT,
            product_type="BANKERS_ACCEPT",
            book_code="CORP_LENDING",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            nominal_amount=NOMINAL_AMOUNT,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
            obs_product=OBS_PRODUCT_ACCEPTANCE,
            risk_type=None,  # engine must fill from obs_product -> FR
        ),
        _Contingent(
            contingent_reference=CONT_REF_PERFBOND,
            product_type="PERF_BOND",
            book_code="CORP_LENDING",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            nominal_amount=NOMINAL_AMOUNT,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
            obs_product=OBS_PRODUCT_PERFBOND,
            risk_type=None,  # engine must fill from obs_product -> MLR
        ),
        _Contingent(
            contingent_reference=CONT_REF_DOCLC,
            product_type="TRADE_LC",
            book_code="TRADE_FINANCE",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            nominal_amount=NOMINAL_AMOUNT,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
            obs_product=OBS_PRODUCT_DOCLC,
            risk_type=None,  # engine must fill from obs_product -> MLR
        ),
        _Contingent(
            contingent_reference=CONT_REF_OVERRIDE,
            product_type="BANKERS_ACCEPT",
            book_code="CORP_LENDING",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            nominal_amount=NOMINAL_AMOUNT,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
            obs_product=OBS_PRODUCT_ACCEPTANCE,  # conflicting product — must be ignored
            risk_type="LR",  # explicit wins: result stays LR / CCF=0.00
        ),
    ]

    # Build base columns from schema — risk_type is pl.String so None serialises as null.
    schema_cols = {
        k: v for k, v in dtypes_of(CONTINGENTS_SCHEMA).items() if k in rows[0].to_dict_base()
    }
    base_dicts = [r.to_dict_base() for r in rows]
    df = pl.DataFrame(base_dicts, schema=schema_cols)

    # Attach the new pre-schema column explicitly.
    # The engine-implementer will add obs_product to CONTINGENTS_SCHEMA; until then
    # the loader must use a schema-tolerant fill path or with_columns override.
    obs_product_values = [r.obs_product for r in rows]
    df = df.with_columns(
        pl.Series(
            "obs_product",
            obs_product_values,
            dtype=pl.String,
        )
    )

    return df


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p231_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P2.31 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory.  Defaults to this package directory
            (``tests/fixtures/p2_31/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_p231_counterparties()),
        ("contingent", create_p231_contingents()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P2.31 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
        if "contingent_reference" in df.columns:
            for row in df.iter_rows(named=True):
                obs = row.get("obs_product", "<not in parquet>")
                rt = row.get("risk_type", None)
                nom = row.get("nominal_amount", 0)
                print(
                    f"    {row['contingent_reference']}: "
                    f"obs_product={obs!r}, risk_type={rt!r}, nominal={nom:,.0f}"
                )
    print("-" * 70)
    print(f"Scenario: {SCENARIO_ID} — Annex I obs_product -> risk_type fill (explicit wins)")
    print(f"  {CONT_REF_ACCEPT}: obs_product={OBS_PRODUCT_ACCEPTANCE!r}, risk_type=None")
    print(
        f"    Expected: resolved risk_type={RESOLVED_RISK_TYPE_ACCEPT!r}, "
        f"ccf={EXPECTED_CCF_ACCEPT}, ead={EXPECTED_EAD_ACCEPT:,.0f}"
    )
    print(f"  {CONT_REF_PERFBOND}: obs_product={OBS_PRODUCT_PERFBOND!r}, risk_type=None")
    print(
        f"    Expected: resolved risk_type={RESOLVED_RISK_TYPE_PERFBOND!r}, "
        f"ccf={EXPECTED_CCF_PERFBOND}, ead={EXPECTED_EAD_PERFBOND:,.0f}"
    )
    print(f"  {CONT_REF_DOCLC}: obs_product={OBS_PRODUCT_DOCLC!r}, risk_type=None")
    print(
        f"    Expected: resolved risk_type={RESOLVED_RISK_TYPE_DOCLC!r}, "
        f"ccf={EXPECTED_CCF_DOCLC}, ead={EXPECTED_EAD_DOCLC:,.0f}"
    )
    print(
        f"  {CONT_REF_OVERRIDE}: obs_product={OBS_PRODUCT_ACCEPTANCE!r}, risk_type='LR' [EXPLICIT WINS]"
    )
    print(
        f"    Expected: retained risk_type={RESOLVED_RISK_TYPE_OVERRIDE!r}, "
        f"ccf={EXPECTED_CCF_OVERRIDE}, ead={EXPECTED_EAD_OVERRIDE:,.0f}"
    )
    print()
    print("  Regulatory citations:")
    print("    FR  (1.00) <- CRR Annex I para 1 / PS1/26 Table A1 Row 1")
    print("    MLR (0.20) <- CRR Annex I Row 6(a)/(b) / PS1/26 Table A1 Row 6")


# ---------------------------------------------------------------------------
# Self-check (also serves as clean-import verification)
# ---------------------------------------------------------------------------


def _verify_contingents() -> None:
    """Verify the contingents DataFrame builds with correct shape and values."""
    df = create_p231_contingents()
    assert df.height == 4, f"Expected 4 rows, got {df.height}"

    # obs_product column must be present (injected via with_columns)
    assert "obs_product" in df.columns, (
        "obs_product column must be present in contingents DataFrame"
    )

    row_accept = df.filter(pl.col("contingent_reference") == CONT_REF_ACCEPT)
    row_perfbond = df.filter(pl.col("contingent_reference") == CONT_REF_PERFBOND)
    row_doclc = df.filter(pl.col("contingent_reference") == CONT_REF_DOCLC)
    row_override = df.filter(pl.col("contingent_reference") == CONT_REF_OVERRIDE)

    for ref, row in [
        (CONT_REF_ACCEPT, row_accept),
        (CONT_REF_PERFBOND, row_perfbond),
        (CONT_REF_DOCLC, row_doclc),
        (CONT_REF_OVERRIDE, row_override),
    ]:
        assert row.height == 1, f"Expected exactly 1 row for {ref!r}, got {row.height}"

    # Product-fill rows: risk_type must be null (None in parquet)
    assert row_accept["risk_type"][0] is None, (
        f"ACCEPT: risk_type must be null for product-fill, got {row_accept['risk_type'][0]!r}"
    )
    assert row_perfbond["risk_type"][0] is None, (
        f"PERFBOND: risk_type must be null for product-fill, got {row_perfbond['risk_type'][0]!r}"
    )
    assert row_doclc["risk_type"][0] is None, (
        f"DOCLC: risk_type must be null for product-fill, got {row_doclc['risk_type'][0]!r}"
    )

    # Override row: risk_type must be explicit "LR"
    assert row_override["risk_type"][0] == "LR", (
        f"OVERRIDE: risk_type must be 'LR', got {row_override['risk_type'][0]!r}"
    )

    # obs_product values
    assert row_accept["obs_product"][0] == OBS_PRODUCT_ACCEPTANCE
    assert row_perfbond["obs_product"][0] == OBS_PRODUCT_PERFBOND
    assert row_doclc["obs_product"][0] == OBS_PRODUCT_DOCLC
    assert row_override["obs_product"][0] == OBS_PRODUCT_ACCEPTANCE  # conflict with LR

    # Nominal amounts
    for ref, row in [
        (CONT_REF_ACCEPT, row_accept),
        (CONT_REF_PERFBOND, row_perfbond),
        (CONT_REF_DOCLC, row_doclc),
        (CONT_REF_OVERRIDE, row_override),
    ]:
        assert row["nominal_amount"][0] == NOMINAL_AMOUNT, (
            f"{ref}: nominal_amount={row['nominal_amount'][0]}, expected {NOMINAL_AMOUNT}"
        )


def _verify_counterparty() -> None:
    """Verify the counterparty DataFrame builds with correct shape."""
    df = create_p231_counterparties()
    assert df.height == 1, f"Expected 1 counterparty row, got {df.height}"
    assert df["counterparty_reference"][0] == COUNTERPARTY_REF
    assert df["entity_type"][0] == "corporate"
    assert df["country_code"][0] == "GB"


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_p231_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    _verify_counterparty()
    _verify_contingents()
    saved = save_p231_fixtures()
    print_summary(saved)
    print()
    print("P2.31 fixture self-check passed.")
