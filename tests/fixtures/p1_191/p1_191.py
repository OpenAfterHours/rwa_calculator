"""
Generate P1.191 fixtures: QRRE per-individual aggregate nominal qualification test.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (engine/classifier.py _combine_classifications)

Key responsibilities:
- Produce two individual retail counterparties: QRRE_AGG (aggregate breach) and
  QRRE_OK (control, single facility under limit).
- Produce three revolving retail facilities: EXP_A and EXP_B for QRRE_AGG
  (aggregate 100k > 90k B31 / 87,320 CRR), EXP_C for QRRE_OK (50k ≤ limit).
- facility_limit == nominal_amount on every row so the drawn-vs-nominal basis
  question (drawn net-of-RE vs nominal) does not contaminate the assertion.
- Fixture is framework-agnostic: same rows are exercised under both CRR and B31
  configs by the test-writer.

Defect under test (classifier.py:876):
    is_qrre checks ``facility_limit.fill_null(inf) <= qrre_max_limit`` per row.
    CRR limit = EUR 100,000 × 0.8732 = GBP 87,320; B31 limit = GBP 90,000.
    Both EXP_A and EXP_B have facility_limit=50,000 ≤ limit per row → incorrectly
    classed as QRRE.  The correct test aggregates per counterparty_reference:
    QRRE_AGG aggregate = 50,000 + 50,000 = 100,000 > both limits → NOT QRRE.
    QRRE_OK  aggregate = 50,000 ≤ both limits → QRRE (expected pass).

Expected classification (post-fix):
    EXP_A  → RETAIL_OTHER   (both CRR and B31)
    EXP_B  → RETAIL_OTHER   (both CRR and B31)
    EXP_C  → RETAIL_QRRE    (both CRR and B31)

References:
    - CRR Art. 154(4)(c): QRRE aggregate nominal ≤ EUR 100,000 per individual
    - PRA PS1/26 Art. 147(5A)(c): QRRE aggregate nominal ≤ GBP 90,000 per individual
    - engine/classifier.py:870-877: _combine_classifications is_qrre per-row defect
    - engine/classifier.py:2182-2242: obligor-aggregate pattern to reuse
    - contracts/config.py:605 (EUR 100,000), :658 (CRR GBP 87,320), :687 (B31 GBP 90,000)
    - docs/specifications/common/hierarchy-classification.md:245: portfolio-level note
    - tests/unit/test_classifier_qrre_warnings.py: QRRE column/warning contract

Usage:
    PYTHONPATH=<worktree>/src python tests/fixtures/p1_191/p1_191.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, FACILITY_SCHEMA

# ---------------------------------------------------------------------------
# Scenario identity constants
# ---------------------------------------------------------------------------

#: Counterparty reference for the aggregate-breaching obligor (EXP_A + EXP_B = 100k)
CP_BREACH: str = "QRRE_AGG"

#: Counterparty reference for the control obligor (EXP_C = 50k, stays QRRE)
CP_OK: str = "QRRE_OK"

#: Facility reference — first facility belonging to the breach obligor
FAC_A: str = "EXP_A"

#: Facility reference — second facility belonging to the breach obligor
FAC_B: str = "EXP_B"

#: Facility reference — sole facility belonging to the control obligor
FAC_C: str = "EXP_C"

# ---------------------------------------------------------------------------
# Scenario monetary constants (GBP)
# ---------------------------------------------------------------------------

#: Facility limit for every exposure (facility_limit == nominal_amount by design)
FACILITY_LIMIT: float = 50_000.0

# ---------------------------------------------------------------------------
# Threshold constants (single source of truth for test-writer assertions)
# ---------------------------------------------------------------------------

#: B31 per-individual QRRE aggregate nominal limit (PRA PS1/26 Art. 147(5A)(c))
B31_QRRE_LIMIT_GBP: float = 90_000.0

#: CRR EUR 100,000 threshold expressed in GBP at the default rate 0.8732
#: (config.py:605 _CRR_QRRE_LIMIT_EUR × eur_gbp_rate 0.8732)
CRR_EUR_LIMIT: float = 100_000.0
CRR_EUR_GBP_RATE: float = 0.8732
CRR_QRRE_LIMIT_GBP: float = CRR_EUR_LIMIT * CRR_EUR_GBP_RATE  # 87,320.0

# ---------------------------------------------------------------------------
# Aggregate nominal arithmetic (single source of truth for test-writer)
# ---------------------------------------------------------------------------

#: QRRE_AGG aggregate nominal = EXP_A + EXP_B = 100,000 (exceeds both limits)
AGG_BREACH_NOMINAL: float = FACILITY_LIMIT + FACILITY_LIMIT  # 100,000.0

#: QRRE_OK aggregate nominal = EXP_C = 50,000 (below both limits)
AGG_OK_NOMINAL: float = FACILITY_LIMIT  # 50,000.0

# ---------------------------------------------------------------------------
# Common dates
# ---------------------------------------------------------------------------

VALUE_DATE: date = date(2027, 1, 4)  # Basel 3.1 era
MATURITY_DATE: date = date(2030, 1, 4)


# ---------------------------------------------------------------------------
# Private row dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.191 individual retail counterparty.

    entity_type="individual": routes to RETAIL_OTHER via Art. 112(h) / Art. 147(1)(d),
    then to QRRE if the revolving condition and aggregate-nominal limit pass.
    is_managed_as_retail=True: pool-management attestation (Art. 123A(1)(b)(iii) /
    Art. 154(4)(b)) satisfies that limb so only the aggregate-nominal gate discriminates.
    apply_fi_scalar=False: no FIRB 1.25x correlation multiplier (not an institution).
    annual_revenue=0.0, total_assets=0.0: natural persons have no corporate metrics;
    set to 0.0 (not null) to avoid triggering conservative-large-corp warnings (CLS008).
    default_status=False: performing exposure.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool
    is_natural_person: bool
    annual_revenue: float
    total_assets: float

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
            "annual_revenue": self.annual_revenue,
            "total_assets": self.total_assets,
        }


@dataclass(frozen=True)
class _Facility:
    """
    P1.191 revolving retail credit facility.

    is_revolving=True: required for the QRRE revolving gate (Art. 147(5) / Art. 154(4)).
    is_qrre_transactor=False: revolver, not transactor (conservative — revolver has higher
    IRB LGD under Art. 161(1)(d) than the QRRE-specific treatment; classification is same).
    limit=FACILITY_LIMIT: facility_limit in the exposure bundle = limit; since no loans
    are mapped (drawn=0), nominal_amount = undrawn_amount = limit, so
    facility_limit == nominal_amount == FACILITY_LIMIT (50,000).
    risk_type="MR": revolving credit facility (medium-risk CCF 75% under F-IRB, or SA
    Table A1 Row 4 under B31); irrelevant to classification but required by FACILITY_SCHEMA.
    committed=True: committed facility so undrawn_amount is non-zero (creates exposure row).
    seniority="senior": standard retail claim.
    """

    facility_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    limit: float
    committed: bool
    is_revolving: bool
    is_qrre_transactor: bool
    seniority: str
    risk_type: str
    product_type: str
    book_code: str

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": self.currency,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "limit": self.limit,
            "committed": self.committed,
            "is_revolving": self.is_revolving,
            "is_qrre_transactor": self.is_qrre_transactor,
            "seniority": self.seniority,
            "risk_type": self.risk_type,
            "product_type": self.product_type,
            "book_code": self.book_code,
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _make_cp(ref: str, name: str) -> _Counterparty:
    """Return a natural-person retail counterparty row for P1.191."""
    return _Counterparty(
        counterparty_reference=ref,
        counterparty_name=name,
        entity_type="individual",
        country_code="GB",
        default_status=False,
        apply_fi_scalar=False,
        is_managed_as_retail=True,
        is_natural_person=True,
        annual_revenue=0.0,
        total_assets=0.0,
    )


def _make_facility(ref: str, cp_ref: str) -> _Facility:
    """Return a revolving retail credit facility row for P1.191."""
    return _Facility(
        facility_reference=ref,
        counterparty_reference=cp_ref,
        currency="GBP",
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        limit=FACILITY_LIMIT,
        committed=True,
        is_revolving=True,
        is_qrre_transactor=False,
        seniority="senior",
        risk_type="MR",
        product_type="revolving_credit_facility",
        book_code="BANKING",
    )


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1191_counterparties() -> pl.DataFrame:
    """
    Return both P1.191 counterparties as a DataFrame (2 rows).

    QRRE_AGG: the aggregate-breach obligor. Has two revolving facilities
        (EXP_A + EXP_B) each with limit=50,000. Aggregate = 100,000 > both
        CRR (87,320) and B31 (90,000) limits. Under corrected engine: NOT QRRE.
        Under buggy per-row engine: each facility 50,000 ≤ limit → QRRE (wrong).

    QRRE_OK: the control obligor. Has one revolving facility (EXP_C) with
        limit=50,000. Aggregate = 50,000 ≤ both limits. Correctly QRRE under
        both buggy and fixed engine; used to confirm the rule still admits genuine
        QRRE members.
    """
    rows = [
        _make_cp(CP_BREACH, "QRRE Aggregate Breach — P1.191"),
        _make_cp(CP_OK, "QRRE Aggregate OK — P1.191"),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1191_facilities() -> pl.DataFrame:
    """
    Return all three P1.191 revolving retail facilities as a DataFrame (3 rows).

    EXP_A: limit=50,000, QRRE_AGG.  Per-row check passes (50k ≤ limit) — buggy.
        Correct aggregate-based check fails (QRRE_AGG total = 100k > limit) → RETAIL_OTHER.

    EXP_B: limit=50,000, QRRE_AGG.  Same as EXP_A — both facilities together
        constitute the breach.  → RETAIL_OTHER (post-fix).

    EXP_C: limit=50,000, QRRE_OK.  QRRE_OK aggregate = 50k ≤ both limits.
        → RETAIL_QRRE (correct under both buggy and fixed engine).

    No loans are mapped to these facilities, so:
        nominal_amount (undrawn_amount) = limit = 50,000 on every row.
        facility_limit                  = limit = 50,000 on every row.
        drawn_amount                    = 0.0   on every row.
    This ensures facility_limit == nominal_amount and the drawn-vs-nominal
    basis question (proposal §5) does not contaminate the assertion.
    """
    rows = [
        _make_facility(FAC_A, CP_BREACH),
        _make_facility(FAC_B, CP_BREACH),
        _make_facility(FAC_C, CP_OK),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1191_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.191 parquet files and return a mapping of name to path.

    Files written:
        counterparty.parquet — 2 rows (QRRE_AGG, QRRE_OK)
        facility.parquet     — 3 rows (EXP_A, EXP_B → QRRE_AGG; EXP_C → QRRE_OK)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1191_counterparties()),
        ("facility", create_p1191_facilities()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.191 fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 80)
    print("Scenario: QRRE per-individual aggregate nominal qualification test")
    print()
    print(
        f"  CRR  QRRE limit:  {CRR_QRRE_LIMIT_GBP:>10,.2f} GBP  (EUR {CRR_EUR_LIMIT:,.0f} × {CRR_EUR_GBP_RATE})"
    )
    print(f"  B31  QRRE limit:  {B31_QRRE_LIMIT_GBP:>10,.2f} GBP")
    print()
    print(
        f"  QRRE_AGG  aggregate nominal = {AGG_BREACH_NOMINAL:>10,.0f}  > both limits  → NOT QRRE (post-fix)"
    )
    print(
        f"  QRRE_OK   aggregate nominal = {AGG_OK_NOMINAL:>10,.0f}  ≤ both limits  → QRRE (both engines)"
    )
    print()
    print("  Expected exposure-class output (post-fix):")
    print("    EXP_A  RETAIL_OTHER   (QRRE_AGG aggregate breach)")
    print("    EXP_B  RETAIL_OTHER   (QRRE_AGG aggregate breach)")
    print("    EXP_C  RETAIL_QRRE    (QRRE_OK  within limit)")
    print()
    print("  Buggy per-row output (pre-fix):")
    print("    EXP_A  RETAIL_QRRE  (50,000 ≤ limit per row — WRONG)")
    print("    EXP_B  RETAIL_QRRE  (50,000 ≤ limit per row — WRONG)")
    print("    EXP_C  RETAIL_QRRE  (50,000 ≤ limit per row — correct by accident)")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1191_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
