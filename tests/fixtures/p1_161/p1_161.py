"""
Generate P1.161 fixtures: PRA Art. 191A(2)(e)(i) "Funded-Only" Look-Through.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/guarantee.py)

Scenario design (P1.161 — two-layer protection look-through):

    A corporate obligor (unrated, B31 SA RW = 100%) has a loan of GBP 1,000,000.
    The loan is fully guaranteed by a corporate guarantor (rated CQS 4, B31 SA RW = 100%).
    The guarantor has in turn posted cash collateral of GBP 400,000 to the beneficiary
    bank against its own guarantee obligation.

    PRA Art. 191A(2)(e)(i) allows a "funded-only" look-through election: when the
    guarantor has pledged eligible financial collateral, the bank may, for the portion
    covered by that collateral, treat the exposure AS IF the collateral were posted
    directly against the original loan.

    Two runs exercise this fixture:

    Run A — regression (look_through_election="none"):
        Guarantee substitution applies. Guarantor CQS 4 (BB+-BB-) corporate B31 SA RW = 100%.
        Since guarantor RW (100%) == obligor unrated RW (100%), guarantee is NOT beneficial
        (Art. 235 RWSM only substitutes when guarantor RW < borrower RW).
        Full exposure retains obligor RW = 100%.
        RWA = 1,000,000 x 1.00 = 1,000,000

    Run B — new path (look_through_election="funded_only"):
        Engine applies look-through for the cash-collateral-covered tranche:
            - Cash collateral covers GBP 400,000 of the guarantee obligation.
            - Under Art. 222 FCSM (cash, zero haircut), that tranche carries 0% RW.
            - The remaining GBP 600,000 of the loan is uncovered / falls back to
              obligor RW = 100%.
        RWA = 400,000 x 0.00 + 600,000 x 1.00 = 600,000

Regulatory references:
    - PRA PS1/26 Art. 191A(2)(e)(i): funded-only look-through election.
    - PRA PS1/26 Art. 235: SA risk-weight substitution method (RWSM) for guarantees.
    - PRA PS1/26 Art. 222: FCSM — cash collateral zero haircut, Hc = Hfx = 0.
    - PRA PS1/26 Art. 197(1)(a): cash as eligible financial collateral.
    - PRA PS1/26 Art. 223(5): adjusted collateral value C* computation.
    - CRR Art. 122 / B31 Art. 122(2) Table 6: corporate SA risk weights by CQS.
      CQS 4 (BB+-BB-): 100% under both CRR Table 5 and B31 Table 6 (unchanged).

New schema fields introduced by this scenario:
    GUARANTEE_SCHEMA:
        is_collateralised_by_guarantor: Boolean — True when the guarantor has
            posted eligible collateral against its own guarantee obligation.
            Engine-implementer must add to GUARANTEE_SCHEMA in schemas.py.
        look_through_election: String enum — "none" | "funded_only" | "both".
            Controls whether Art. 191A(2)(e)(i) funded-only look-through applies.
            Engine-implementer must add to GUARANTEE_SCHEMA in schemas.py.

    COLLATERAL_SCHEMA:
        posted_by_counterparty_reference: String — counterparty reference of the
            party that posted the collateral (here the guarantor, not the obligor).
            Engine-implementer must add to COLLATERAL_SCHEMA in schemas.py.
        Note: beneficiary_type="guarantee" is used to link collateral to the
            guarantee row rather than directly to a loan/facility.
            Engine-implementer must add "guarantee" to VALID_BENEFICIARY_TYPES in
            schemas.py (currently: {"counterparty", "loan", "facility", "contingent"}).

Schema validator workaround:
    The new columns (is_collateralised_by_guarantor, look_through_election,
    posted_by_counterparty_reference) are NOT present in the current GUARANTEE_SCHEMA
    or COLLATERAL_SCHEMA. They are added via Polars with_columns() AFTER building the
    base DataFrame from dtypes_of(). The schema validator does not reject extra columns
    in parquet — it only enforces known columns on read. The engine-implementer must:
        1. Add the three new fields to GUARANTEE_SCHEMA and COLLATERAL_SCHEMA.
        2. Add "guarantee" to VALID_BENEFICIARY_TYPES.
        3. Add "look_through_election" to COLUMN_VALUE_CONSTRAINTS["guarantees"].
    All three are in src/rwa_calc/data/schemas.py.

    The validate_bundle_values() check on beneficiary_type would reject "guarantee"
    with the current VALID_BENEFICIARY_TYPES. The engine-implementer must extend it
    before the acceptance test can pass.

Usage:
    uv run python tests/fixtures/p1_161/p1_161.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references
OBLIGOR_REF = "CP_OBLIGOR_P1161"
GUARANTOR_REF = "CP_GUARANTOR_P1161"

# Exposure reference
LOAN_REF = "LOAN_P1161"

# Guarantee reference
GUARANTEE_REF = "GUAR_P1161"

# Collateral reference
COLLATERAL_REF = "COLL_P1161"

# Rating references
RTG_GUARANTOR_REF = "RATING_GTOR_P1161"

# Dates — Basel 3.1 effective 1 Jan 2027; value_date post-go-live
LOAN_VALUE_DATE = date(2027, 1, 2)
LOAN_MATURITY_DATE = date(2032, 1, 2)  # 5y residual
GUARANTEE_MATURITY_DATE = date(2032, 1, 2)  # matches loan — no maturity mismatch
RATING_DATE = date(2027, 1, 2)

# Loan economics
LOAN_DRAWN_AMOUNT: float = 1_000_000.0
LOAN_EAD: float = LOAN_DRAWN_AMOUNT  # EAD = drawn + interest (interest=0)

# Guarantee coverage
PERCENTAGE_COVERED: float = 1.0  # 100% full coverage
AMOUNT_COVERED: float = LOAN_DRAWN_AMOUNT
ORIGINAL_MATURITY_YEARS: float = 5.0  # >= 1y -> Art. 237(2)(a) satisfied

# Collateral (cash posted by guarantor against its own guarantee obligation)
COLLATERAL_MARKET_VALUE: float = 400_000.0
COLLATERAL_PLEDGE_PERCENTAGE: float = 1.0
COLLATERAL_RESIDUAL_MATURITY_YEARS: float = 5.0

# CQS assignments
# Obligor: unrated -> B31 SA corporate unrated RW = 100%
# Guarantor: CQS 4 -> B31 SA corporate RW = 100% (Art. 122(2) Table 6)
GUARANTOR_CQS: int = 4

# B31 SA risk weights (Art. 122(2) Table 6)
OBLIGOR_RW_B31: float = 1.00     # unrated corporate, B31
GUARANTOR_RW_B31: float = 1.00   # CQS 4 (BB+-BB-) corporate, B31 Table 6 = 100% (same as CRR)

# Expected RWA outcomes (for documentation; assertions live in acceptance test)
# Run A: look_through_election="none"
#   Guarantor RW (100%) == Obligor RW (100%) -> guarantee NOT beneficial (no improvement)
#   RWA = 1,000,000 x 1.00 = 1,000,000
EXPECTED_RWA_RUN_A: float = 1_000_000.0

# Run B: look_through_election="funded_only"
#   Cash collateral covers 400,000 -> 0% RW (Art. 222 FCSM cash, Hc=Hfx=0)
#   Remaining 600,000 uncovered -> obligor RW 100%
#   RWA = 400,000 x 0.00 + 600,000 x 1.00 = 600,000
EXPECTED_RWA_RUN_B: float = 600_000.0


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.161 counterparty row (obligor or guarantor)."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_financial_sector_entity: bool
    is_natural_person: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_financial_sector_entity": self.is_financial_sector_entity,
            "is_natural_person": self.is_natural_person,
        }


@dataclass(frozen=True)
class _Loan:
    """P1.161 loan: GBP 1,000,000 term loan, 5-year maturity."""

    loan_reference: str
    product_type: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    drawn_amount: float
    interest: float
    seniority: str

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "product_type": self.product_type,
            "counterparty_reference": self.counterparty_reference,
            "currency": self.currency,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "seniority": self.seniority,
        }


@dataclass(frozen=True)
class _Rating:
    """P1.161 external ECAI rating for the guarantor."""

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
    cqs: int
    pd: float | None
    rating_date: date
    is_solicited: bool
    model_id: str | None

    def to_dict(self) -> dict:
        return {
            "rating_reference": self.rating_reference,
            "counterparty_reference": self.counterparty_reference,
            "rating_type": self.rating_type,
            "rating_agency": self.rating_agency,
            "rating_value": self.rating_value,
            "cqs": self.cqs,
            "pd": self.pd,
            "rating_date": self.rating_date,
            "is_solicited": self.is_solicited,
            "model_id": self.model_id,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1161_counterparties() -> pl.DataFrame:
    """
    Return two P1.161 counterparties (obligor + guarantor) as a DataFrame.

    CP_OBLIGOR_P1161: corporate, GB, unrated -> B31 SA RW = 100%.
    CP_GUARANTOR_P1161: corporate, GB, CQS 4 -> B31 SA RW = 100% (Art. 122(2) Table 6,
        CQS 4 BB+-BB- = 100%, same as CRR).

    Both are non-FSE (is_financial_sector_entity=False), non-natural-person,
    non-defaulted, no FI scalar. The guarantor's CQS 4 RW (100%) equals the
    obligor's unrated RW (100%), so the guarantee is NOT beneficial under plain
    RWSM (no improvement) — the discriminating element is the funded-only look-through
    election which reduces RWA from 1,000,000 to 600,000 by applying 0% to the
    cash-collateralised tranche.
    """
    rows = [
        _Counterparty(
            counterparty_reference=OBLIGOR_REF,
            counterparty_name="P1.161 Corporate Obligor GB (unrated)",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
            is_natural_person=False,
        ),
        _Counterparty(
            counterparty_reference=GUARANTOR_REF,
            counterparty_name="P1.161 Corporate Guarantor GB CQS4",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
            is_natural_person=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1161_loan() -> pl.DataFrame:
    """
    Return one P1.161 loan as a DataFrame.

    LOAN_P1161: GBP 1,000,000 term loan on obligor CP_OBLIGOR_P1161.
    value_date=2027-01-02 (post Basel 3.1 go-live), maturity_date=2032-01-02 (5y).
    EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000 GBP.
    seniority=senior_unsecured so obligor SA RW is the unmitigated corporate RW.
    """
    row = _Loan(
        loan_reference=LOAN_REF,
        product_type="term_loan",
        counterparty_reference=OBLIGOR_REF,
        currency="GBP",
        value_date=LOAN_VALUE_DATE,
        maturity_date=LOAN_MATURITY_DATE,
        drawn_amount=LOAN_DRAWN_AMOUNT,
        interest=0.0,
        seniority="senior_unsecured",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p1161_rating() -> pl.DataFrame:
    """
    Return one P1.161 external rating (guarantor only) as a DataFrame.

    RATING_GTOR_P1161: CP_GUARANTOR_P1161, external_long_term, CQS 4, S&P BB+.
        -> B31 Art. 122(2) Table 6 CQS 4 corporate SA RW = 100%.

    No rating for the obligor (unrated) — engine defaults to unrated corporate RW.
    pd=None and model_id=None: no IRB path triggered.
    """
    row = _Rating(
        rating_reference=RTG_GUARANTOR_REF,
        counterparty_reference=GUARANTOR_REF,
        rating_type="external",
        rating_agency="S&P",
        rating_value="BB+",
        cqs=GUARANTOR_CQS,
        pd=None,
        rating_date=RATING_DATE,
        is_solicited=True,
        model_id=None,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1161_guarantee(look_through_election: str = "none") -> pl.DataFrame:
    """
    Return one P1.161 guarantee row as a DataFrame.

    GUAR_P1161: full-coverage (100%) guarantee from CP_GUARANTOR_P1161 covering LOAN_P1161.

    New fields (added via with_columns() after base schema construction):
        is_collateralised_by_guarantor=True: signals the guarantor has posted
            eligible collateral against its own obligation.
        look_through_election: controls Art. 191A(2)(e)(i) funded-only look-through.
            "none"       -> Run A regression (no look-through; RWA=1,000,000)
            "funded_only"-> Run B new path   (look-through applied; RWA=600,000)

    Schema note: is_collateralised_by_guarantor and look_through_election are NOT
    in the current GUARANTEE_SCHEMA. They are appended via with_columns() so the
    parquet carries them; the engine-implementer extends schemas.py to declare them.

    Args:
        look_through_election: "none" or "funded_only". Defaults to "none" (Run A).
    """
    base_row = {
        "guarantee_reference": GUARANTEE_REF,
        "guarantee_type": "guarantee",
        "guarantor": GUARANTOR_REF,
        "currency": "GBP",
        "maturity_date": GUARANTEE_MATURITY_DATE,
        "amount_covered": AMOUNT_COVERED,
        "percentage_covered": PERCENTAGE_COVERED,
        "beneficiary_type": "loan",
        "beneficiary_reference": LOAN_REF,
        "protection_type": "guarantee",
        "includes_restructuring": True,
        "original_maturity_years": ORIGINAL_MATURITY_YEARS,
        "guarantor_seniority": "senior",
    }
    base_df = pl.DataFrame([base_row], schema=dtypes_of(GUARANTEE_SCHEMA))
    # Append new P1.161 fields not yet in GUARANTEE_SCHEMA:
    return base_df.with_columns(
        pl.lit(True).alias("is_collateralised_by_guarantor"),
        pl.lit(look_through_election).alias("look_through_election"),
    )


def create_p1161_collateral() -> pl.DataFrame:
    """
    Return one P1.161 collateral row as a DataFrame.

    COLL_P1161: GBP 400,000 cash collateral posted by the guarantor against its
    own guarantee obligation (GUAR_P1161).

    New fields (added via with_columns() after base schema construction):
        beneficiary_type="guarantee": links the collateral to the guarantee row
            (not directly to the loan). NOT in current VALID_BENEFICIARY_TYPES.
            Engine-implementer must add "guarantee" to VALID_BENEFICIARY_TYPES
            in schemas.py and extend the CRM collateral-join logic.
        posted_by_counterparty_reference=CP_GUARANTOR_P1161: identifies the
            counterparty who posted the collateral. Engine uses this to match
            collateral to the guarantor leg in look-through processing.

    Schema note: posted_by_counterparty_reference is NOT in the current
    COLLATERAL_SCHEMA. It is appended via with_columns() so the parquet carries
    it; the engine-implementer extends schemas.py to declare it.

    The beneficiary_type="guarantee" value IS written to the parquet. The
    existing validate_bundle_values() will flag this as invalid (VALID_BENEFICIARY_TYPES
    does not include "guarantee"). The engine-implementer must add "guarantee" to
    VALID_BENEFICIARY_TYPES (schemas.py line ~752) before the acceptance test can pass.
    """
    # Build with existing COLLATERAL_SCHEMA fields only, then append new ones.
    # beneficiary_type="guarantee" intentionally uses the future enum value;
    # the schema cast does not constrain string values (only validates at runtime).
    base_row = {
        "collateral_reference": COLLATERAL_REF,
        "collateral_type": "cash",
        "currency": "GBP",
        "market_value": COLLATERAL_MARKET_VALUE,
        "pledge_percentage": COLLATERAL_PLEDGE_PERCENTAGE,
        "is_eligible_financial_collateral": True,
        "residual_maturity_years": COLLATERAL_RESIDUAL_MATURITY_YEARS,
        "beneficiary_type": "guarantee",
        "beneficiary_reference": GUARANTEE_REF,
    }
    base_df = pl.DataFrame([base_row], schema={
        "collateral_reference": pl.String,
        "collateral_type": pl.String,
        "currency": pl.String,
        "market_value": pl.Float64,
        "pledge_percentage": pl.Float64,
        "is_eligible_financial_collateral": pl.Boolean,
        "residual_maturity_years": pl.Float64,
        "beneficiary_type": pl.String,
        "beneficiary_reference": pl.String,
    })
    # Append new P1.161 field not yet in COLLATERAL_SCHEMA:
    return base_df.with_columns(
        pl.lit(GUARANTOR_REF).alias("posted_by_counterparty_reference"),
    )


# ---------------------------------------------------------------------------
# Scenario bundles: Run A (regression) and Run B (new path)
# ---------------------------------------------------------------------------


def create_p1161_run_a() -> dict[str, pl.DataFrame]:
    """
    Return all DataFrames for Run A (look_through_election="none").

    Run A is the regression guard: no funded-only look-through, guarantor CQS 4
    RW (100%) == obligor unrated RW (100%) -> guarantee not beneficial.
    Expected RWA = 1,000,000 (obligor's own unmitigated RW applies).
    """
    return {
        "counterparty": create_p1161_counterparties(),
        "loan": create_p1161_loan(),
        "rating": create_p1161_rating(),
        "guarantee": create_p1161_guarantee(look_through_election="none"),
        "collateral": create_p1161_collateral(),
    }


def create_p1161_run_b() -> dict[str, pl.DataFrame]:
    """
    Return all DataFrames for Run B (look_through_election="funded_only").

    Run B exercises Art. 191A(2)(e)(i): the cash collateral (GBP 400,000) posted
    by the guarantor triggers funded-only look-through.
        - Cash tranche (400k): 0% RW under Art. 222 FCSM (Hc=Hfx=0, cash GBP/GBP).
        - Residual tranche (600k): obligor unrated corporate RW 100%.
    Expected RWA = 400,000 x 0.00 + 600,000 x 1.00 = 600,000.
    """
    return {
        "counterparty": create_p1161_counterparties(),
        "loan": create_p1161_loan(),
        "rating": create_p1161_rating(),
        "guarantee": create_p1161_guarantee(look_through_election="funded_only"),
        "collateral": create_p1161_collateral(),
    }


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1161_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.161 parquet files and return a mapping of name to path.

    Two guarantee parquet files are written — one per run — because the
    guarantee's look_through_election differs between runs:
        guarantee_run_a.parquet: look_through_election="none"  (regression)
        guarantee_run_b.parquet: look_through_election="funded_only" (new path)

    The counterparty, loan, rating, and collateral files are shared across
    both runs (identical data).

    Args:
        output_dir: Target directory. Defaults to the directory of this file
            (``tests/fixtures/p1_161/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    run_a = create_p1161_run_a()
    run_b = create_p1161_run_b()

    # Shared artefacts (identical in both runs)
    shared_artefacts = [
        ("counterparty", run_a["counterparty"]),
        ("loan", run_a["loan"]),
        ("rating", run_a["rating"]),
        ("collateral", run_a["collateral"]),
    ]

    # Run-specific guarantee files
    guarantee_artefacts = [
        ("guarantee_run_a", run_a["guarantee"]),
        ("guarantee_run_b", run_b["guarantee"]),
    ]

    saved: dict[str, Path] = {}
    for name, df in shared_artefacts + guarantee_artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.161 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: PRA Art. 191A(2)(e)(i) Funded-Only Look-Through")
    print(f"  Obligor:   {OBLIGOR_REF} (corporate, unrated, B31 RW=100%)")
    print(f"  Guarantor: {GUARANTOR_REF} (corporate, CQS {GUARANTOR_CQS}, B31 RW=100%)")
    print(f"  Loan:      {LOAN_REF} GBP {LOAN_DRAWN_AMOUNT:,.0f}")
    print(f"  Guarantee: {GUARANTEE_REF} 100% coverage, original_maturity=5.0y, senior")
    print(f"  Collateral:{COLLATERAL_REF} GBP {COLLATERAL_MARKET_VALUE:,.0f} cash")
    print()
    print("  Run A (look_through_election='none'):")
    print("    Guarantor RW (100%) == Obligor RW (100%) -> guarantee NOT beneficial (no improvement)")
    print(f"    Expected RWA = {EXPECTED_RWA_RUN_A:,.0f}")
    print()
    print("  Run B (look_through_election='funded_only'):")
    print("    Cash tranche 400k: FCSM Art. 222 -> 0% RW")
    print("    Residual tranche 600k: obligor unrated -> 100% RW")
    print(f"    Expected RWA = {EXPECTED_RWA_RUN_B:,.0f}")
    print()
    print("  Schema extensions required (engine-implementer):")
    print("    schemas.py GUARANTEE_SCHEMA: add is_collateralised_by_guarantor (Boolean)")
    print("    schemas.py GUARANTEE_SCHEMA: add look_through_election (String)")
    print("    schemas.py COLLATERAL_SCHEMA: add posted_by_counterparty_reference (String)")
    print("    schemas.py VALID_BENEFICIARY_TYPES: add 'guarantee'")
    print("    schemas.py COLUMN_VALUE_CONSTRAINTS['guarantees']: add look_through_election")


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_p1161_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    main()
