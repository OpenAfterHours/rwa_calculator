"""
Generate P2.32 fixtures: B31-D.CCF10 — purchased-receivables undrawn-commitment CCF override.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (engine/ccf.py,
    data/schemas.py)

Scenario design (P2.32 / B31-D.CCF10 — PRA PS1/26 Art. 166E(5)):

    Under Basel 3.1 (PRA PS1/26 Art. 166E(5)), undrawn purchase commitments for
    *revolving* purchased-receivables facilities receive a specific CCF treatment:

        - 40% by default (Art. 111(1) Table A1 Row 5 "Other Commitments" / OC).
        - 10% when the commitment also satisfies the Table A1 Row 7 UCC criteria
          (unconditionally-cancellable commitment / LR risk_type).

    This is a CCF override on the off-balance-sheet *undrawn purchase commitment*
    — it is NOT the dilution-vs-default split (Art. 157 / 161(1)(g), which is
    out of scope for P2.32).

    The fix introduces a Boolean column ``is_purchased_receivable_commitment``
    (default False) on FACILITY_SCHEMA and CONTINGENTS_SCHEMA.  When True AND
    ``is_revolving=True`` AND the config is Basel 3.1, the engine applies:

        CCF = 0.10  if risk_type == "LR"  (UCC / Row 7 exception)
        CCF = 0.40  otherwise             (Row 5 "Other Commitments" default)

    The MR row (PR_COMMIT_MR) is the strongest discriminator: without the
    override, ``risk_type="MR"`` would resolve to CCF = 0.50; with the
    Art. 166E(5) override it resolves to CCF = 0.40 (EAD = 400,000 vs 500,000).

    Four facility rows exercise the logic:

        PR_COMMIT_40 (B31-D.CCF10-OC):
            risk_type="OC", is_purchased_receivable_commitment=True,
            is_revolving=True.
            Expected under CalculationConfig.basel_3_1():
                ccf = 0.40  (Art. 166E(5) main limb)
                ead_from_ccf = 400_000.00
                ead_pre_crm  = 400_000.00

        PR_COMMIT_10 (B31-D.CCF10-LR):
            risk_type="LR", is_purchased_receivable_commitment=True,
            is_revolving=True.
            Expected under CalculationConfig.basel_3_1():
                ccf = 0.10  (Art. 166E(5) UCC / LR exception)
                ead_from_ccf = 100_000.00
                ead_pre_crm  = 100_000.00

        PR_COMMIT_MR (B31-D.CCF10-MR) — load-bearing discriminator:
            risk_type="MR", is_purchased_receivable_commitment=True,
            is_revolving=True.
            Expected under CalculationConfig.basel_3_1():
                ccf = 0.40  (Art. 166E(5) overrides the generic MR = 0.50)
                ead_from_ccf = 400_000.00  [pre-fix: 500_000.00]
                ead_pre_crm  = 400_000.00

        PR_COMMIT_40_CRR (CRR control):
            risk_type="OC", is_purchased_receivable_commitment=True,
            is_revolving=True.
            Under CalculationConfig.crr():
                flag is Basel-3.1-gated → no-op.
                CCF resolves via existing CRR OC path (0.50 SA / 0.75 F-IRB).
                EAD is unchanged from the pre-flag baseline.

    Counterparty CP_PR_CORP_001: corporate, GB, non-SME. Assertions are
    CCF/EAD-scoped only; RWA/K/RW/SF are not asserted.

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1()):

    All rows: drawn_amount = 0  →  nominal_after_provision = limit = 1_000_000
    EAD formula: on_bs + (nominal × CCF)  =  0 + (1_000_000 × CCF)

    PR_COMMIT_40:  CCF=0.40  →  EAD=400,000
    PR_COMMIT_10:  CCF=0.10  →  EAD=100,000
    PR_COMMIT_MR:  CCF=0.40  →  EAD=400,000  (generic MR=0.50 would give 500,000)

    Regulatory scalars (ccf.py, no new scalar added):
        SA_CCF_B31["OC"] = 0.40  (ccf.py line 75)
        SA_CCF_B31["LR"] = 0.10  (ccf.py line 77)
        SA_CCF_B31["MR"] = 0.50  (ccf.py line 74, overridden for flagged rows)

    CRR control (PR_COMMIT_40_CRR):
        Art. 166E(5) is Basel-3.1-only.  The flag is present in the parquet
        but the engine must not branch on it under CRR.  CRR OC CCF = 0.50
        (SA) or 0.75 (F-IRB OC path — Art. 166(8)(d)).

Implementation note:
    ``is_purchased_receivable_commitment`` is not yet in FACILITY_SCHEMA.
    We build the base columns via ``dtypes_of(FACILITY_SCHEMA)`` and then
    ``with_columns`` the new Boolean column on top, matching the dtype the
    engine-implementer will register (pl.Boolean, default False).

References:
    - PRA PS1/26 App 1 Art. 166E(5) (ps126app1.pdf p.118): CCF on undrawn
      purchase commitments for revolving purchased receivables.
    - Art. 111(1) Table A1 Row 5 (OC = 40%) and Row 7 (LR/UCC = 10%).
    - CRR Art. 166(8)(c): revolving purchased-receivables UCC → 0% (no-op
      negative control under CRR).
    - docs/specifications/crr/credit-conversion-factors.md L381-404 (P2.32
      "not yet implemented" note; verbatim ps126app1.pdf p.118 quote).
    - src/rwa_calc/data/tables/ccf.py lines 74-77 (SA_CCF_B31 dict).

Usage:
    /home/philm/projects/rwa_calculator/.venv/bin/python tests/fixtures/p2_32/p2_32.py
    /home/philm/projects/rwa_calculator/.venv/bin/python tests/fixtures/p2_32/p2_32.py --data-dir /path/to/output
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

#: Scenario IDs used consistently across fixture, tests, and implementation.
SCENARIO_ID_B31: str = "B31-D.CCF10"
SCENARIO_ID_CRR: str = "CRR-D.CCF9"

# Counterparty
COUNTERPARTY_REF: str = "CP_PR_CORP_001"

# Facility references
FAC_REF_OC: str = "PR_COMMIT_40"   # B3.1: CCF = 0.40 (OC / Art.166E(5) main limb)
FAC_REF_LR: str = "PR_COMMIT_10"   # B3.1: CCF = 0.10 (LR/UCC exception)
FAC_REF_MR: str = "PR_COMMIT_MR"   # B3.1: CCF = 0.40 (overrides generic MR = 0.50)
FAC_REF_CRR: str = "PR_COMMIT_40_CRR"  # CRR control: flag is no-op

# Shared economics
LIMIT: float = 1_000_000.00

# Dates
VALUE_DATE: date = date(2027, 1, 1)
MATURITY_DATE: date = date(2030, 6, 30)  # > 1y to qualify as committed OC

# Expected outputs (Basel 3.1)
EXPECTED_CCF_OC: float = 0.40      # Art. 166E(5) main limb → SA_CCF_B31["OC"]
EXPECTED_CCF_LR: float = 0.10      # Art. 166E(5) UCC/LR exception → SA_CCF_B31["LR"]
EXPECTED_CCF_MR: float = 0.40      # Art. 166E(5) override — generic MR=0.50 → 0.40

EXPECTED_EAD_OC: float = 400_000.00  # 1_000_000 × 0.40
EXPECTED_EAD_LR: float = 100_000.00  # 1_000_000 × 0.10
EXPECTED_EAD_MR: float = 400_000.00  # 1_000_000 × 0.40 (pre-fix: 500_000)

# Pre-fix (generic MR) expected output — used by tests to confirm the fix fires
PRE_FIX_CCF_MR: float = 0.50   # SA_CCF_B31["MR"] without Art. 166E(5) override
PRE_FIX_EAD_MR: float = 500_000.00

# Regulatory scalar cross-references (ccf.py lines)
SA_CCF_B31_OC: float = 0.40   # ccf.py line 75
SA_CCF_B31_LR: float = 0.10   # ccf.py line 77
SA_CCF_B31_MR: float = 0.50   # ccf.py line 74


# ---------------------------------------------------------------------------
# Dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P2.32 counterparty row — corporate obligor."""

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
    P2.32 facility row.

    The ``is_purchased_receivable_commitment`` field is NOT yet declared in
    FACILITY_SCHEMA (engine-implementer's wave), so it is not included in the
    base ``dtypes_of(FACILITY_SCHEMA)`` call and is written separately via an
    explicit ``with_columns`` override in ``create_p232_facilities()``.
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
    is_obs_commitment: bool
    is_purchased_receivable_commitment: bool  # New column — pre-schema in parquet only

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
            "is_obs_commitment": self.is_obs_commitment,
            "is_purchased_receivable_commitment": self.is_purchased_receivable_commitment,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p232_counterparties() -> pl.DataFrame:
    """
    Return the P2.32 counterparty (corporate obligor) as a DataFrame.

    CP_PR_CORP_001: entity_type="corporate", GB — a non-SME corporate borrower.
    Using a corporate counterparty is consistent with a purchased-receivables
    programme (seller / originator is typically a corporate entity).
    Assertions for this scenario are CCF/EAD-scoped only; classification to
    corporate exposure class is required but RW is not asserted.
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF,
            counterparty_name="P2.32 Corp — Revolving Purchased Receivables Seller",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
            is_natural_person=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p232_facilities() -> pl.DataFrame:
    """
    Return all four P2.32 facility rows as a DataFrame.

    Three Basel 3.1 rows (OC / LR / MR) exercise the Art. 166E(5) CCF routing.
    One CRR control row confirms the flag is a no-op under CRR.  All rows have
    ``is_revolving=True``, ``is_obs_commitment=True``, and
    ``is_purchased_receivable_commitment=True``.

    Implementation note:
        ``is_purchased_receivable_commitment`` is not yet in FACILITY_SCHEMA.
        We build the base columns via ``dtypes_of(FACILITY_SCHEMA)`` and then
        ``with_columns`` the new Boolean column on top, matching the dtype the
        engine-implementer will register (pl.Boolean, default False).

    Rows:
        PR_COMMIT_40 (OC):  Basel 3.1 → CCF=0.40, EAD=400,000
        PR_COMMIT_10 (LR):  Basel 3.1 → CCF=0.10, EAD=100,000
        PR_COMMIT_MR (MR):  Basel 3.1 → CCF=0.40 (LOAD-BEARING; pre-fix 0.50/500,000)
        PR_COMMIT_40_CRR:   CRR control → flag is no-op; CCF stays on CRR OC path
    """
    rows = [
        _Facility(
            facility_reference=FAC_REF_OC,
            product_type="PURCHASED_RECEIVABLES_COMMITMENT",
            book_code="PR_BOOK",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            limit=LIMIT,
            committed=True,
            seniority="senior",
            risk_type="OC",
            is_revolving=True,
            is_obs_commitment=True,
            is_purchased_receivable_commitment=True,
        ),
        _Facility(
            facility_reference=FAC_REF_LR,
            product_type="PURCHASED_RECEIVABLES_COMMITMENT",
            book_code="PR_BOOK",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            limit=LIMIT,
            committed=True,
            seniority="senior",
            risk_type="LR",
            is_revolving=True,
            is_obs_commitment=True,
            is_purchased_receivable_commitment=True,
        ),
        _Facility(
            facility_reference=FAC_REF_MR,
            product_type="PURCHASED_RECEIVABLES_COMMITMENT",
            book_code="PR_BOOK",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            limit=LIMIT,
            committed=True,
            seniority="senior",
            risk_type="MR",
            is_revolving=True,
            is_obs_commitment=True,
            is_purchased_receivable_commitment=True,
        ),
        _Facility(
            facility_reference=FAC_REF_CRR,
            product_type="PURCHASED_RECEIVABLES_COMMITMENT",
            book_code="PR_BOOK",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            limit=LIMIT,
            committed=True,
            seniority="senior",
            risk_type="OC",
            is_revolving=True,
            is_obs_commitment=True,
            is_purchased_receivable_commitment=True,  # flag present but CRR-gated no-op
        ),
    ]

    # Build using existing schema fields (excludes the new pre-schema column).
    base_dict_list = [
        {k: v for k, v in r.to_dict().items() if k != "is_purchased_receivable_commitment"}
        for r in rows
    ]
    df = pl.DataFrame(base_dict_list, schema=dtypes_of(FACILITY_SCHEMA))

    # Attach the new column explicitly so it rides in the parquet.
    # The engine-implementer will add this to FACILITY_SCHEMA; until then the
    # loader must use ``with_columns`` fill or a schema-tolerant load path.
    flag_values = [r.is_purchased_receivable_commitment for r in rows]
    df = df.with_columns(
        pl.Series(
            "is_purchased_receivable_commitment",
            flag_values,
            dtype=pl.Boolean,
        )
    )

    return df


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p232_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P2.32 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to this package directory
            (``tests/fixtures/p2_32/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_p232_counterparties()),
        ("facility", create_p232_facilities()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print(f"P2.32 / {SCENARIO_ID_B31} / {SCENARIO_ID_CRR} fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        cols = df.columns
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
        if "is_purchased_receivable_commitment" in cols and "facility_reference" in cols:
            flags = df["is_purchased_receivable_commitment"].to_list()
            refs = df["facility_reference"].to_list()
            risk_types = df["risk_type"].to_list() if "risk_type" in cols else [None] * len(refs)
            for ref, flag, rt in zip(refs, flags, risk_types):
                print(f"    {ref}: risk_type={rt!r}, is_purchased_receivable_commitment={flag}")
    print("-" * 70)
    print(f"Scenario: {SCENARIO_ID_B31} — purchased-receivables undrawn commitment CCF")
    print(f"  OC row  ({FAC_REF_OC}): risk_type=OC, flag=True")
    print(f"    Basel 3.1 expected ccf={EXPECTED_CCF_OC}, ead={EXPECTED_EAD_OC:,.0f}")
    print(f"  LR row  ({FAC_REF_LR}): risk_type=LR (UCC), flag=True")
    print(f"    Basel 3.1 expected ccf={EXPECTED_CCF_LR}, ead={EXPECTED_EAD_LR:,.0f}")
    print(f"  MR row  ({FAC_REF_MR}): risk_type=MR, flag=True [LOAD-BEARING]")
    print(
        f"    Basel 3.1 expected ccf={EXPECTED_CCF_MR}, ead={EXPECTED_EAD_MR:,.0f}"
        f"  (pre-fix: ccf={PRE_FIX_CCF_MR}, ead={PRE_FIX_EAD_MR:,.0f})"
    )
    print(f"  CRR row ({FAC_REF_CRR}): risk_type=OC, flag=True (CRR control — flag no-op)")
    print()
    print("  Regulatory scalars (ccf.py):")
    print(f"    SA_CCF_B31['OC'] = {SA_CCF_B31_OC}  (Art. 166E(5) main limb)")
    print(f"    SA_CCF_B31['LR'] = {SA_CCF_B31_LR}  (Art. 166E(5) UCC/LR exception)")
    print(f"    SA_CCF_B31['MR'] = {SA_CCF_B31_MR}  (generic MR — overridden for flagged rows)")


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_p232_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    main()
