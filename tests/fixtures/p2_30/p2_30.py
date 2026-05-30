"""
P2.30 fixture builder: Annex I Row 3 vs Row 4 CCF discrimination.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (data/schemas.py,
    engine/ccf.py or equivalent risk_type dispatch)

Scenario design (P2.30 — CRR Annex I / SA CCF 50%):

    CRR Annex I lists off-balance-sheet items in four risk bands.  Row 3 covers
    "other" issued OBS items (transaction-related contingents such as performance
    bonds, bid bonds, shipping guarantees — 50% CCF under SA).  Row 4 covers
    medium-risk commitments: Note Issuance Facilities (NIFs) and Revolving
    Underwriting Facilities (RUFs) — also 50% CCF under SA.

    Both rows carry the same CCF (50%) and therefore produce identical EAD, yet
    they are conceptually distinct: Row 3 items are issued OBS items (the bank
    has issued a guarantee or similar instrument on behalf of the counterparty);
    Row 4 items are commitment-style facilities (the bank has committed to extend
    credit or underwrite paper).

    Today both map to risk_type="MR".  P2.30 introduces RiskType.MR_ISSUED
    ("medium_risk_issued") for Annex I Row 3 so that:
    - Row 3 items carry risk_type="MR_ISSUED" (is_obs_commitment=False)
    - Row 4 items retain risk_type="MR"       (is_obs_commitment=True)

    Because both rows resolve to 50% CCF:
        ccf_applied = 0.50 for both
        ead_from_ccf = nominal × 0.50 = 1_000_000 × 0.50 = 500_000
        ead_pre_crm  = 500_000

    The only load-bearing assertion is that risk_type values are DISTINCT:
        Exposure A (OBS-ROW3-001): risk_type = "MR_ISSUED"  (Annex I Row 3)
        Exposure B (NIF-ROW4-001): risk_type = "MR"         (Annex I Row 4)

    MR_ISSUED is NOT yet in VALID_RISK_TYPES_INPUT / RISK_TYPE_SYNONYMS — the
    engine-implementer adds it in Wave 4.  Writing the literal string "MR_ISSUED"
    into the parquet is intentional so that pre-implementation the test fails RED
    (Row 3 and Row 4 are indistinguishable / MR_ISSUED is unrecognised), and
    post-implementation the test passes GREEN.

Counterparty:
    CP-CORP-01: entity_type="corporate", country_code="GB", unrated, non-SME.
    Classification routes to SA corporate exposure class (100% RW).
    RWA/RW assertions are out of scope — only CCF/EAD and risk_type are asserted.

Hand-calculation (SA, CalculationConfig.crr() or .basel_3_1()):

    Both rows: nominal_amount = 1_000_000, drawn_amount implicit = 0
    EAD formula (off-balance-sheet): ead_from_ccf = nominal × CCF
        Row 3 (MR_ISSUED): CCF = 0.50  →  ead = 500_000
        Row 4 (MR):        CCF = 0.50  →  ead = 500_000

References:
    - CRR Annex I: OBS items risk bands (Rows 1-4)
    - CRR Art. 111(2): CCF table for SA OBS exposures
    - CRR Art. 166(8)(d) / Art. 166(10): F-IRB CCF routing (MR/MR_ISSUED distinction)
    - PS1/26 App 1 Art. 111(1) Table A1: Basel 3.1 CCF table (Row 3 / Row 4 structure)

Usage:
    PYTHONPATH=src /path/to/.venv/bin/python tests/fixtures/p2_30/p2_30.py
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

SCENARIO_ID: str = "P2.30"

# Counterparty reference
COUNTERPARTY_REF: str = "CP-CORP-01"

# Exposure references
CONT_REF_ROW3: str = "OBS-ROW3-001"  # Annex I Row 3: other issued OBS item
CONT_REF_ROW4: str = "NIF-ROW4-001"  # Annex I Row 4: NIF/RUF commitment

# Risk types — MR_ISSUED is pre-schema (not yet in VALID_RISK_TYPES_INPUT)
RISK_TYPE_ROW3: str = "MR_ISSUED"  # NEW — Annex I Row 3; engine-implementer adds this
RISK_TYPE_ROW4: str = "MR"  # Existing — Annex I Row 4 (NIFs / RUFs)

# Shared economics
NOMINAL_AMOUNT: float = 1_000_000.00

# Dates
VALUE_DATE: date = date(2027, 1, 1)
MATURITY_DATE: date = date(2029, 6, 30)  # > 1y — typical NIF/RUF / issued contingent term

# is_obs_commitment discrimination
IS_OBS_COMMITMENT_ROW3: bool = False  # Row 3: issued OBS item (not a commitment)
IS_OBS_COMMITMENT_ROW4: bool = True  # Row 4: commitment (NIF/RUF)

# Expected CCF and EAD (both rows resolve to 50% under SA)
EXPECTED_CCF: float = 0.50
EXPECTED_EAD: float = NOMINAL_AMOUNT * EXPECTED_CCF  # 500_000.00

# bs_type for both rows
BS_TYPE: str = "OFB"  # off-balance-sheet


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P2.30 counterparty row — unrated GB corporate."""

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
    P2.30 contingent row.

    ``risk_type`` carries a literal string value.  For the Row 3 exposure
    this is "MR_ISSUED", which is NOT yet registered in VALID_RISK_TYPES_INPUT.
    Writing it as a plain pl.String column is valid parquet; the loader will
    treat it as an unknown type until the engine-implementer adds it.
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
    risk_type: str
    is_obs_commitment: bool
    bs_type: str

    def to_dict(self) -> dict:
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
            "is_obs_commitment": self.is_obs_commitment,
            "bs_type": self.bs_type,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p230_counterparties() -> pl.DataFrame:
    """
    Return the P2.30 counterparty (unrated GB corporate) as a DataFrame.

    CP-CORP-01: entity_type="corporate", GB, unrated, non-SME.  Classification
    routes to SA corporate exposure class (100% RW unrated); RW is not asserted
    by the P2.30 test suite — only CCF/EAD and risk_type distinctness are tested.
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF,
            counterparty_name="P2.30 Corp — Annex I Row 3 vs Row 4 CCF discrimination",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_natural_person=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p230_contingents() -> pl.DataFrame:
    """
    Return both P2.30 contingent rows as a DataFrame.

    Row A — Annex I Row 3 (OBS-ROW3-001):
        risk_type="MR_ISSUED", is_obs_commitment=False
        Expected CCF = 0.50 (same as MR — post-implementation)
        This row writes "MR_ISSUED" as a raw string; the engine-implementer
        will add it to VALID_RISK_TYPES_INPUT in Wave 4.

    Row B — Annex I Row 4 (NIF-ROW4-001):
        risk_type="MR", is_obs_commitment=True
        Expected CCF = 0.50 (existing MR path)

    The two rows are otherwise identical (same counterparty, nominal, dates) so
    that any EAD difference can only arise from the risk_type dispatch.

    Implementation note:
        ``risk_type`` is pl.String in CONTINGENTS_SCHEMA so "MR_ISSUED" writes
        without any schema coercion needed.  We build via dtypes_of(CONTINGENTS_SCHEMA)
        on the columns present in _Contingent.to_dict(); remaining schema columns
        receive their defaults via the loader's schema-tolerant fill path.
    """
    rows = [
        _Contingent(
            contingent_reference=CONT_REF_ROW3,
            product_type="PERF_BOND",  # typical Annex I Row 3 product
            book_code="CORP_LENDING",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            nominal_amount=NOMINAL_AMOUNT,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
            risk_type=RISK_TYPE_ROW3,  # "MR_ISSUED" — pre-schema, new value
            is_obs_commitment=IS_OBS_COMMITMENT_ROW3,
            bs_type=BS_TYPE,
        ),
        _Contingent(
            contingent_reference=CONT_REF_ROW4,
            product_type="NIF",  # typical Annex I Row 4 product
            book_code="CORP_LENDING",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            nominal_amount=NOMINAL_AMOUNT,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
            risk_type=RISK_TYPE_ROW4,  # "MR" — existing value
            is_obs_commitment=IS_OBS_COMMITMENT_ROW4,
            bs_type=BS_TYPE,
        ),
    ]

    # Build only columns that exist in CONTINGENTS_SCHEMA — risk_type is pl.String
    # so "MR_ISSUED" writes without coercion.
    schema_cols = {k: v for k, v in dtypes_of(CONTINGENTS_SCHEMA).items() if k in rows[0].to_dict()}
    return pl.DataFrame([r.to_dict() for r in rows], schema=schema_cols)


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p230_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P2.30 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory.  Defaults to this package directory
            (``tests/fixtures/p2_30/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_p230_counterparties()),
        ("contingent", create_p230_contingents()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P2.30 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
        if "risk_type" in df.columns and "contingent_reference" in df.columns:
            for row in df.iter_rows(named=True):
                print(
                    f"    {row['contingent_reference']}: risk_type={row['risk_type']!r}, "
                    f"is_obs_commitment={row.get('is_obs_commitment')}, "
                    f"nominal={row['nominal_amount']:,.0f}"
                )
    print("-" * 70)
    print(f"Scenario: {SCENARIO_ID} — Annex I Row 3 (MR_ISSUED) vs Row 4 (MR) discrimination")
    print(
        f"  Row 3 ({CONT_REF_ROW3}): risk_type={RISK_TYPE_ROW3!r}, "
        f"is_obs_commitment={IS_OBS_COMMITMENT_ROW3}"
    )
    print(f"    Expected ccf={EXPECTED_CCF}, ead={EXPECTED_EAD:,.0f}")
    print(
        f"  Row 4 ({CONT_REF_ROW4}): risk_type={RISK_TYPE_ROW4!r}, "
        f"is_obs_commitment={IS_OBS_COMMITMENT_ROW4}"
    )
    print(f"    Expected ccf={EXPECTED_CCF}, ead={EXPECTED_EAD:,.0f}")
    print()
    print("  Key assertion: risk_type values are DISTINCT")
    print(f"    Row 3 risk_type = {RISK_TYPE_ROW3!r}  (MR_ISSUED — NEW, pre-schema)")
    print(f"    Row 4 risk_type = {RISK_TYPE_ROW4!r}  (MR — existing)")
    print("  Both rows: ccf_applied=0.50, ead_from_ccf=500_000")


# ---------------------------------------------------------------------------
# Self-check (also serves as clean-import verification)
# ---------------------------------------------------------------------------


def _verify_contingents() -> None:
    """Verify the contingents DataFrame builds with correct shape and values."""
    df = create_p230_contingents()
    assert df.height == 2, f"Expected 2 rows, got {df.height}"

    row3 = df.filter(pl.col("contingent_reference") == CONT_REF_ROW3)
    row4 = df.filter(pl.col("contingent_reference") == CONT_REF_ROW4)

    assert row3.height == 1, f"Expected exactly 1 Row 3 row, got {row3.height}"
    assert row4.height == 1, f"Expected exactly 1 Row 4 row, got {row4.height}"

    assert row3["risk_type"][0] == RISK_TYPE_ROW3, (
        f"Row 3 risk_type should be {RISK_TYPE_ROW3!r}, got {row3['risk_type'][0]!r}"
    )
    assert row4["risk_type"][0] == RISK_TYPE_ROW4, (
        f"Row 4 risk_type should be {RISK_TYPE_ROW4!r}, got {row4['risk_type'][0]!r}"
    )

    # Core assertion: risk_types must be distinct
    assert RISK_TYPE_ROW3 != RISK_TYPE_ROW4, "risk_type values must be distinct"
    assert row3["risk_type"][0] != row4["risk_type"][0], (
        "Fixture row risk_type values must be distinct"
    )

    assert row3["is_obs_commitment"][0] == IS_OBS_COMMITMENT_ROW3
    assert row4["is_obs_commitment"][0] == IS_OBS_COMMITMENT_ROW4

    assert row3["nominal_amount"][0] == NOMINAL_AMOUNT
    assert row4["nominal_amount"][0] == NOMINAL_AMOUNT

    assert row3["bs_type"][0] == BS_TYPE
    assert row4["bs_type"][0] == BS_TYPE


def _verify_counterparty() -> None:
    """Verify the counterparty DataFrame builds with correct shape."""
    df = create_p230_counterparties()
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

    saved = save_p230_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    _verify_counterparty()
    _verify_contingents()
    saved = save_p230_fixtures()
    print_summary(saved)
    print()
    print("P2.30 fixture self-check passed.")
