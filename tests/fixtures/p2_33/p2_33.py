"""
Generate P2.33 fixtures: B31-D.CCF9 — UK residential-mortgage commitment 50% CCF override.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (engine/ccf.py,
    data/schemas.py)

Scenario design (P2.33 / B31-D.CCF9 — PRA PS1/26 Art. 111(1) Table A1 Row 4(b)):

    Under Basel 3.1 (PRA PS1/26 Art. 111 Table A1), commitments to extend credit
    secured by residential property (Row 4(b)) receive a 50% CCF — the same as the
    general MR category — regardless of their ``risk_type`` category.  Without this
    override a UK residential-mortgage commitment with ``risk_type="OC"`` would fall
    to the 40% OC catch-all (Row 5), under-capitalising the CCF.

    The fix introduces a Boolean column ``is_uk_residential_mortgage_commitment``
    (default False) on FACILITY_SCHEMA and CONTINGENTS_SCHEMA.  When True and the
    config is Basel 3.1, the engine applies a 50% CCF override regardless of
    ``risk_type``.

    Two facility rows exercise the fork:

        FLAGGED (B31-CCF9-RESI):
            risk_type="OC", is_uk_residential_mortgage_commitment=True
            Expected under CalculationConfig.basel_3_1():
                ccf = 0.50  (Row 4(b) override fires)
                ead_from_ccf = 500_000.00  (1_000_000 × 0.50)
                ead_pre_crm  = 500_000.00
                on_bs_for_ead = 0.00  (fully undrawn: drawn_amount=0)

        CONTROL (B31-CCF9-OC-CONTROL):
            risk_type="OC", is_uk_residential_mortgage_commitment=False
            Expected under CalculationConfig.basel_3_1():
                ccf = 0.40  (OC fall-through, no override)
                ead_from_ccf = 400_000.00  (1_000_000 × 0.40)

    Under CalculationConfig.crr() both rows receive the CRR OC CCF (0.50) because
    Table A1 is Basel 3.1 only.  The is_uk_residential_mortgage_commitment flag is
    schema-present but has no effect under CRR.

    The column is NOT yet in FACILITY_SCHEMA / CONTINGENTS_SCHEMA when this fixture
    is generated — it is written directly into the parquet file with an explicit
    schema override.  The engine-implementer will add it to the schema in a later
    wave; at that point ``dtypes_of(FACILITY_SCHEMA)`` will include it and this
    builder can be simplified to use the schema helper.

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1()):

    FLAGGED row:
        Input: nominal (limit) = 1_000_000, drawn_amount = 0, committed = True,
               risk_type = "OC", is_uk_residential_mortgage_commitment = True
        Override: Table A1 Row 4(b) → CCF = 0.50
        EAD: on_bs = 0.00 (drawn_amount=0), ead_from_ccf = 1_000_000 × 0.50 = 500_000
        ead_pre_crm = 0 + 500_000 = 500_000

    CONTROL row:
        Input: nominal (limit) = 1_000_000, drawn_amount = 0, committed = True,
               risk_type = "OC", is_uk_residential_mortgage_commitment = False
        SA_CCF_B31["OC"] = 0.40
        EAD: on_bs = 0.00, ead_from_ccf = 1_000_000 × 0.40 = 400_000
        ead_pre_crm = 0 + 400_000 = 400_000

    Regulatory scalars (ccf.py):
        SA_CCF_B31["MR"] = 0.50  (Row 4 / general MR rate applied to Row 4(b))
        SA_CCF_B31["OC"] = 0.40  (Row 5 OC fall-through)

References:
    - PRA PS1/26 Art. 111(1) Table A1:
        Row 4(b): commitments to extend credit secured by residential property — 50%
        Row 5   : "other commitments" (OC) — 40%
    - src/rwa_calc/data/tables/ccf.py: SA_CCF_B31 dict (lines 74-75)
    - docs/specifications/b31/credit-conversion-factors.md §B31-D.CCF9 (planned slot)

Usage:
    uv run python tests/fixtures/p2_33/p2_33.py
    uv run python tests/fixtures/p2_33/p2_33.py --data-dir /path/to/output
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, FACILITY_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

#: Scenario ID used consistently across fixture, tests, and implementation.
SCENARIO_ID: str = "B31-D.CCF9"

# Counterparty
COUNTERPARTY_REF: str = "CP_P233_RTL"

# Facility references
FLAGGED_FAC_REF: str = "B31-CCF9-RESI"
CONTROL_FAC_REF: str = "B31-CCF9-OC-CONTROL"

# Shared economics
LIMIT: float = 1_000_000.00
DRAWN_AMOUNT: float = 0.00

# Dates
VALUE_DATE: date = date(2027, 1, 1)
MATURITY_DATE: date = date(2029, 6, 30)  # > 1y → committed facility, OC category eligible

# Expected outputs (Basel 3.1)
EXPECTED_CCF_FLAGGED: float = 0.50  # Table A1 Row 4(b) override
EXPECTED_EAD_FROM_CCF_FLAGGED: float = 500_000.00  # 1_000_000 × 0.50
EXPECTED_EAD_PRE_CRM_FLAGGED: float = 500_000.00
EXPECTED_ON_BS_FLAGGED: float = 0.00  # drawn_amount = 0

EXPECTED_CCF_CONTROL: float = 0.40  # SA_CCF_B31["OC"]
EXPECTED_EAD_FROM_CCF_CONTROL: float = 400_000.00  # 1_000_000 × 0.40

# Regulatory scalar cross-references (ccf.py lines)
SA_CCF_B31_MR: float = 0.50  # Row 4 / MR rate; ccf.py line 74
SA_CCF_B31_OC: float = 0.40  # Row 5 OC fall-through; ccf.py line 75


# ---------------------------------------------------------------------------
# Dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P2.33 counterparty row — retail individual obligor."""

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
class _Facility:
    """
    P2.33 facility row.

    The ``is_uk_residential_mortgage_commitment`` field is NOT yet declared in
    FACILITY_SCHEMA (engine-implementer's wave), so it is not included in
    ``to_dict()`` and is written separately via an explicit schema override in
    ``create_p233_facilities()``.
    """

    facility_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    limit: float
    committed: bool
    seniority: str
    risk_type: str
    is_revolving: bool
    is_uk_residential_mortgage_commitment: bool  # New column — schema-present in parquet only

    def to_dict(self) -> dict:
        """Return all columns including the new pre-schema column."""
        return {
            "facility_reference": self.facility_reference,
            "product_type": self.product_type,
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "limit": self.limit,
            "committed": self.committed,
            "seniority": self.seniority,
            "risk_type": self.risk_type,
            "is_revolving": self.is_revolving,
            "is_uk_residential_mortgage_commitment": self.is_uk_residential_mortgage_commitment,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p233_counterparties() -> pl.DataFrame:
    """
    Return the P2.33 counterparty (retail individual obligor) as a DataFrame.

    CP_P233_RTL: entity_type="individual", GB — a retail/natural-person borrower.
    Using an individual counterparty keeps the scenario in the retail exposure
    class, which is consistent with a UK residential-mortgage commitment.
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF,
            counterparty_name="P2.33 Individual UK Mortgage Borrower",
            entity_type="individual",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_natural_person=True,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p233_facilities() -> pl.DataFrame:
    """
    Return both P2.33 facility rows as a DataFrame.

    Both rows carry risk_type="OC" so the only discriminator between the two
    outputs is the new ``is_uk_residential_mortgage_commitment`` flag.

    FLAGGED (B31-CCF9-RESI):
        is_uk_residential_mortgage_commitment=True
        Expected Basel 3.1 CCF: 0.50 (Table A1 Row 4(b) override).

    CONTROL (B31-CCF9-OC-CONTROL):
        is_uk_residential_mortgage_commitment=False
        Expected Basel 3.1 CCF: 0.40 (SA_CCF_B31["OC"] fall-through).

    Implementation note:
        ``is_uk_residential_mortgage_commitment`` is not yet in FACILITY_SCHEMA.
        We build the base columns via ``dtypes_of(FACILITY_SCHEMA)`` and then
        ``with_columns`` the new Boolean column on top, matching the dtype the
        engine-implementer will register (pl.Boolean, default False).
    """
    rows = [
        _Facility(
            facility_reference=FLAGGED_FAC_REF,
            product_type="MORTGAGE_COMMITMENT",
            book_code="RETAIL_MORTGAGES",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            limit=LIMIT,
            committed=True,
            seniority="senior",
            risk_type="OC",
            is_revolving=False,
            is_uk_residential_mortgage_commitment=True,
        ),
        _Facility(
            facility_reference=CONTROL_FAC_REF,
            product_type="UNDRAWN_COMMIT",
            book_code="RETAIL_MORTGAGES",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            limit=LIMIT,
            committed=True,
            seniority="senior",
            risk_type="OC",
            is_revolving=False,
            is_uk_residential_mortgage_commitment=False,
        ),
    ]

    # Build using existing schema fields (excludes the new column).
    base_dict_list = [
        {k: v for k, v in r.to_dict().items() if k != "is_uk_residential_mortgage_commitment"}
        for r in rows
    ]
    df = pl.DataFrame(base_dict_list, schema=dtypes_of(FACILITY_SCHEMA))

    # Attach the new column explicitly so it rides in the parquet.
    # The engine-implementer will add this to FACILITY_SCHEMA; until then the
    # loader must use ``with_columns`` fill or a schema-tolerant load path.
    flag_values = [r.is_uk_residential_mortgage_commitment for r in rows]
    df = df.with_columns(
        pl.Series(
            "is_uk_residential_mortgage_commitment",
            flag_values,
            dtype=pl.Boolean,
        )
    )

    return df


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p233_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P2.33 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to this package directory
            (``tests/fixtures/p2_33/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_p233_counterparties()),
        ("facility", create_p233_facilities()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print(f"P2.33 / {SCENARIO_ID} fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        cols = df.columns
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
        if "is_uk_residential_mortgage_commitment" in cols:
            flags = df["is_uk_residential_mortgage_commitment"].to_list()
            refs = df["facility_reference"].to_list()
            for ref, flag in zip(refs, flags):
                print(f"    {ref}: is_uk_residential_mortgage_commitment={flag}")
    print("-" * 70)
    print(f"Scenario: {SCENARIO_ID} — UK residential-mortgage commitment 50% CCF override")
    print(f"  Flagged  ({FLAGGED_FAC_REF}): risk_type=OC, flag=True")
    print(f"    Basel 3.1 expected ccf={EXPECTED_CCF_FLAGGED}, ead_from_ccf={EXPECTED_EAD_FROM_CCF_FLAGGED:,.0f}")
    print(f"  Control  ({CONTROL_FAC_REF}): risk_type=OC, flag=False")
    print(f"    Basel 3.1 expected ccf={EXPECTED_CCF_CONTROL}, ead_from_ccf={EXPECTED_EAD_FROM_CCF_CONTROL:,.0f}")
    print()
    print("  Regulatory scalars (ccf.py):")
    print(f"    SA_CCF_B31['MR'] = {SA_CCF_B31_MR}  (Row 4(b) target rate)")
    print(f"    SA_CCF_B31['OC'] = {SA_CCF_B31_OC}  (Row 5 OC fall-through)")


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_p233_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    main()
