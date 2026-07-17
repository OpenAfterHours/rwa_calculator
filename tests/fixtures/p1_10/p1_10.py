"""
Generate P1.10 fixtures: CRR/PS1-26 Art. 213(1)(c)(i) unfunded credit protection (UCP)
unilateral-cancellation / unilateral-change eligibility gate.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/guarantees.py,
    data/schemas.py GUARANTEE_SCHEMA, rulebook/packs/{crr,b31}.py Feature)

Key responsibilities:
- Produce two counterparty rows:
    CP_BORROWER_P110:  corporate, GB, unrated, large-corporate revenue profile
                        (mirrors the D3/D4 CORP_UR_001 "unrated corporate = 100% RW"
                        pattern) -> CRR Art. 122 / B31 equivalent unrated fallback = 100%.
    CP_GUARANTOR_P110: sovereign, CQS 2 (external rating) -> Art. 114 Table 1 = 20% RW,
                        identical under CRR and B31 (no regime divergence at this band).
- Produce one external rating row (guarantor only — the borrower is deliberately
  unrated so its baseline SA risk weight is the 100% fallback).
- Produce three loan rows, one per scenario, GBP 1,000,000 drawn each, identical
  economics (only the paired guarantee's new eligibility flags differ):
    LOAN_P110_BASE, LOAN_P110_A, LOAN_P110_B
- Produce three guarantee rows, one per loan, full (100%) coverage, guarantor =
  CP_GUARANTOR_P110, carrying the two NEW nullable Boolean columns
  ``is_unilaterally_cancellable`` / ``is_unilaterally_changeable`` (not yet declared
  on GUARANTEE_SCHEMA — the engine-implementer adds them; Polars accepts the extra
  parquet columns without error and the loader's lenient seal silently strips them
  until the schema catches up — see P1.124 for the identical extra-column pattern):
    GUAR_P110_BASE: both flags NULL   (permissive default — mirrors existing rows)
    GUAR_P110_A:    is_unilaterally_cancellable=True,  is_unilaterally_changeable=NULL
    GUAR_P110_B:    is_unilaterally_cancellable=False, is_unilaterally_changeable=True

Defect under test (pre-fix):
    CRR/PS1-26 Art. 213(1)(c)(i) requires unfunded credit protection to derive from
    an undertaking that cannot be unilaterally cancelled or that unilaterally
    increases the effective cost of protection by the protection provider. The CRM
    processor (``_prepare_guarantees``) does not currently gate on this condition at
    all — a guarantee that is unilaterally cancellable (or, under B31 only, one whose
    terms the guarantor can unilaterally change) is still substituted, overstating
    the credit risk mitigation benefit.

Post-fix assertion (primary, both CRR and B31 configs from this one fixture set):
    LOAN_P110_BASE + GUAR_P110_BASE (flags null, permissive)
        -> guarantee ELIGIBLE  -> RW = 20% (guarantor CQS 2) -> RWA = 200,000
    LOAN_P110_A + GUAR_P110_A (is_unilaterally_cancellable=True)
        -> guarantee INELIGIBLE (both regimes) -> RW = 100% (borrower, unrated)
           -> RWA = 1,000,000 + CRM012 warning
    LOAN_P110_B + GUAR_P110_B (is_unilaterally_cancellable=False,
                                is_unilaterally_changeable=True)
        -> CRR:  guarantee ELIGIBLE  -> RW = 20%  -> RWA = 200,000 (no warning;
                 CRR does not gate on the "change" arm)
        -> B31:  guarantee INELIGIBLE -> RW = 100% -> RWA = 1,000,000 + CRM012
                 warning (pack Feature ``ucp_unilateral_change_ineligible`` is on
                 for B31 / off for CRR)

Hand-calculation (CalculationConfig.crr() and CalculationConfig.basel_3_1(), both
identical for this fixture since neither the borrower's unrated-100% fallback nor
the guarantor's CQS-2-sovereign-20% band diverges between regimes):
    Loan EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000 GBP

    BASE (eligible, both regimes):
        RW = CP_GUARANTOR_P110 sovereign CQS 2 = 20%
        RWA = 1,000,000 x 0.20 = 200,000

    A (ineligible, both regimes — Art. 213(1)(c)(i) cancellable arm):
        RW = CP_BORROWER_P110 unrated corporate fallback = 100%
        RWA = 1,000,000 x 1.00 = 1,000,000

    B (regime-split — Art. 213(1)(c)(i) change arm, B31-only per P1.143 scoping):
        CRR: RW = 20%  -> RWA = 200,000   (unilateral-change arm not gated under CRR)
        B31: RW = 100% -> RWA = 1,000,000 (unilateral-change arm gated under B31)

    Maturity: guarantee maturity_date == loan maturity_date (both 2029-01-01), so
    there is no Art. 233 maturity-mismatch scaling to disentangle from the
    eligibility gate itself — RWA moves cleanly between the 20%/100% bands above.

Schema dependency:
    GUARANTEE_SCHEMA in src/rwa_calc/data/schemas.py does NOT yet include
    ``is_unilaterally_cancellable`` / ``is_unilaterally_changeable``
    (both ColumnSpec(pl.Boolean, required=False), null-permissive default).
    The parquet writer accepts the extra columns without error; the loader's
    lenient seal (contracts/edges.py: seal_lenient / EdgeContract.conform_lenient)
    silently drops any column not declared on the schema/edge, so existing
    fixture-dependent tests are unaffected until the engine-implementer adds the
    two fields to GUARANTEE_SCHEMA (and to RAW_TABLE_EDGES["guarantees"] via
    edge_columns_from_specs, which reads GUARANTEE_SCHEMA directly).
    See P1.10 in IMPLEMENTATION_PLAN.md for the schema-change item.

References:
    - CRR Art. 213(1)(c)(i): unfunded credit protection eligibility — the protection
      must derive from an undertaking that cannot be unilaterally cancelled by the
      protection provider, or that unilaterally increases the effective cost of
      protection after the credit protection agreement was entered into.
    - PS1/26, PRA Rulebook Art. 213(1)(c)(i): CRR-equivalent restatement; PS1/26
      additionally gates the unilateral-*change* arm (the "increases the effective
      cost" limb) more strictly — tracked separately as P1.143 (Rule 4.11
      transitional grandfathering, 1 Jan 2027-30 Jun 2028) which depends on this
      base eligibility gate.
    - CRR Art. 114 Table 1 / PS1/26 Art. 114: sovereign CQS-to-RW mapping,
      identical 0/20/50/100/100/150% bands under both regimes (CQS 2 = 20%).
    - CRR Art. 122 / PS1/26 equivalent: unrated corporate SA fallback = 100%.
    - docs/plans/compliance-audit-crr-111-241-rectification.md:596 (art213-eligibility-
      conditions-unvalidated finding).
    - tests/fixtures/p1_124/p1_124.py: identical extra-column-beyond-schema pattern
      (original_maturity_years) for a sibling Art. 237(2)(a) eligibility gate.
    - tests/fixtures/guarantee/guarantee.py: D4 scenario — the canonical SA
      guarantee-substitution shape this fixture mirrors (unrated corporate borrower,
      externally-rated guarantor, full/partial coverage substitution).

Usage:
    uv run python tests/fixtures/p1_10/p1_10.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

BORROWER_REF = "CP_BORROWER_P110"
GUARANTOR_REF = "CP_GUARANTOR_P110"

LOAN_BASE_REF = "LOAN_P110_BASE"
LOAN_A_REF = "LOAN_P110_A"
LOAN_B_REF = "LOAN_P110_B"

GUAR_BASE_REF = "GUAR_P110_BASE"
GUAR_A_REF = "GUAR_P110_A"
GUAR_B_REF = "GUAR_P110_B"

LOAN_VALUE_DATE = date(2026, 1, 1)
LOAN_MATURITY_DATE = date(2029, 1, 1)  # 3y — matches the D3/D4 CORP_UR_001 pattern

# Guarantee maturity == loan maturity: no Art. 233 maturity-mismatch scaling,
# so RWA moves cleanly on the eligibility gate alone.
GUARANTEE_MATURITY_DATE = LOAN_MATURITY_DATE

LOAN_DRAWN_AMOUNT = 1_000_000.0
LOAN_INTEREST = 0.0
LOAN_EAD = LOAN_DRAWN_AMOUNT + LOAN_INTEREST  # 1,000,000 GBP

GUARANTOR_CQS = 2  # sovereign CQS 2 -> Art. 114 Table 1 = 20% RW (both regimes)
RATING_AGENCY = "S&P"
RATING_VALUE = "A"  # representative CQS-2 mid-band external rating
RATING_DATE = date(2026, 1, 2)

# Expected outputs (see module docstring hand-calc)
EXPECTED_RW_SUBSTITUTED: float = 0.20  # guarantor sovereign CQS 2
EXPECTED_RW_UNRATED_BORROWER: float = 1.00  # borrower unrated corporate fallback

EXPECTED_RWA_ELIGIBLE: float = LOAN_EAD * EXPECTED_RW_SUBSTITUTED  # 200,000
EXPECTED_RWA_INELIGIBLE: float = LOAN_EAD * EXPECTED_RW_UNRATED_BORROWER  # 1,000,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.10 counterparty row (borrower or guarantor)."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float | None
    total_assets: float | None
    default_status: bool
    sector_code: str
    apply_fi_scalar: bool
    is_managed_as_retail: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "annual_revenue": self.annual_revenue,
            "total_assets": self.total_assets,
            "default_status": self.default_status,
            "sector_code": self.sector_code,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
        }


@dataclass(frozen=True)
class _Loan:
    """P1.10 loan: GBP 1,000,000 drawn, 3-year maturity, senior."""

    loan_reference: str
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
    """P1.10 external ECAI rating: S&P scale, pd=None, model_id=None."""

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


@dataclass(frozen=True)
class _Guarantee:
    """
    P1.10 guarantee row.

    Includes ``is_unilaterally_cancellable`` / ``is_unilaterally_changeable`` —
    two fields not yet in GUARANTEE_SCHEMA. The parquet writer accepts extra
    columns without error; the engine-implementer must add both fields to
    GUARANTEE_SCHEMA (ColumnSpec(pl.Boolean, required=False), null-permissive)
    before the CRM processor can read them.
    """

    guarantee_reference: str
    guarantee_type: str
    guarantor: str
    currency: str
    maturity_date: date
    amount_covered: float
    percentage_covered: float
    beneficiary_type: str
    beneficiary_reference: str
    protection_type: str
    includes_restructuring: bool
    is_unilaterally_cancellable: bool | None
    is_unilaterally_changeable: bool | None

    def to_dict(self) -> dict:
        return {
            "guarantee_reference": self.guarantee_reference,
            "guarantee_type": self.guarantee_type,
            "guarantor": self.guarantor,
            "currency": self.currency,
            "maturity_date": self.maturity_date,
            "amount_covered": self.amount_covered,
            "percentage_covered": self.percentage_covered,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "protection_type": self.protection_type,
            "includes_restructuring": self.includes_restructuring,
            "is_unilaterally_cancellable": self.is_unilaterally_cancellable,
            "is_unilaterally_changeable": self.is_unilaterally_changeable,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p110_counterparties() -> pl.DataFrame:
    """
    Return the two P1.10 counterparties (borrower + guarantor) as a DataFrame.

    CP_BORROWER_P110:  corporate, GB, unrated, large-corporate revenue profile
                        (mirrors CORP_UR_001) -> 100% SA fallback RW.
    CP_GUARANTOR_P110: sovereign, CQS 2 (external rating) -> 20% SA RW.
    """
    rows = [
        _Counterparty(
            counterparty_reference=BORROWER_REF,
            counterparty_name="P1.10 Unrated Large Corporate Borrower",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=600_000_000.0,  # large corporate, matches CORP_UR_001
            total_assets=500_000_000.0,
            default_status=False,
            sector_code="28.99",
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
        _Counterparty(
            counterparty_reference=GUARANTOR_REF,
            counterparty_name="P1.10 Sovereign Guarantor CQS2",
            entity_type="sovereign",
            country_code="SA",
            annual_revenue=None,
            total_assets=None,
            default_status=False,
            sector_code="84.11",
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p110_loans() -> pl.DataFrame:
    """
    Return the three P1.10 loans (one per scenario) as a DataFrame.

    All three are GBP 1,000,000 drawn, 3-year maturity, identical economics —
    only the paired guarantee's new eligibility flags differ per scenario.
    """
    rows = [
        _Loan(
            loan_reference=ref,
            counterparty_reference=BORROWER_REF,
            currency="GBP",
            value_date=LOAN_VALUE_DATE,
            maturity_date=LOAN_MATURITY_DATE,
            drawn_amount=LOAN_DRAWN_AMOUNT,
            interest=LOAN_INTEREST,
            seniority="senior",
        )
        for ref in (LOAN_BASE_REF, LOAN_A_REF, LOAN_B_REF)
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p110_ratings() -> pl.DataFrame:
    """
    Return the single P1.10 external rating (guarantor only) as a DataFrame.

    The borrower is deliberately left unrated so its baseline SA risk weight
    is the 100% unrated-corporate fallback.
    """
    rows = [
        _Rating(
            rating_reference="RTG-P110-GUARANTOR",
            counterparty_reference=GUARANTOR_REF,
            rating_type="external",
            rating_agency=RATING_AGENCY,
            rating_value=RATING_VALUE,
            cqs=GUARANTOR_CQS,
            pd=None,
            rating_date=RATING_DATE,
            is_solicited=True,
            model_id=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p110_guarantees() -> pl.DataFrame:
    """
    Return the three P1.10 guarantee rows as a DataFrame.

    GUAR_P110_BASE: both new flags NULL — permissive default (mirrors every
        pre-existing guarantee row elsewhere in the fixture estate, which
        carries no value for these two columns at all and so resolves to
        NULL through the schema's eventual default once the engine-implementer
        adds them; number-neutral by construction).
    GUAR_P110_A:    is_unilaterally_cancellable=True, is_unilaterally_changeable=NULL
        -> Art. 213(1)(c)(i) cancellable arm -> ineligible under both regimes.
    GUAR_P110_B:    is_unilaterally_cancellable=False, is_unilaterally_changeable=True
        -> Art. 213(1)(c)(i) change arm -> ineligible under B31 only (CRR unaffected).

    Columns ``is_unilaterally_cancellable`` / ``is_unilaterally_changeable`` are
    written as extra columns beyond GUARANTEE_SCHEMA. Polars does not validate
    this against the schema on write; the engine-implementer must add both
    fields to GUARANTEE_SCHEMA to read them.
    """
    guarantee_schema_plus = {
        "guarantee_reference": pl.String,
        "guarantee_type": pl.String,
        "guarantor": pl.String,
        "currency": pl.String,
        "maturity_date": pl.Date,
        "amount_covered": pl.Float64,
        "percentage_covered": pl.Float64,
        "beneficiary_type": pl.String,
        "beneficiary_reference": pl.String,
        "protection_type": pl.String,
        "includes_restructuring": pl.Boolean,
        # NEW fields — not yet in GUARANTEE_SCHEMA; engine-implementer must add them.
        "is_unilaterally_cancellable": pl.Boolean,
        "is_unilaterally_changeable": pl.Boolean,
    }

    rows = [
        _Guarantee(
            guarantee_reference=GUAR_BASE_REF,
            guarantee_type="sovereign_guarantee",
            guarantor=GUARANTOR_REF,
            currency="GBP",
            maturity_date=GUARANTEE_MATURITY_DATE,
            amount_covered=LOAN_DRAWN_AMOUNT,
            percentage_covered=1.0,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_BASE_REF,
            protection_type="guarantee",
            includes_restructuring=False,
            is_unilaterally_cancellable=None,
            is_unilaterally_changeable=None,
        ),
        _Guarantee(
            guarantee_reference=GUAR_A_REF,
            guarantee_type="sovereign_guarantee",
            guarantor=GUARANTOR_REF,
            currency="GBP",
            maturity_date=GUARANTEE_MATURITY_DATE,
            amount_covered=LOAN_DRAWN_AMOUNT,
            percentage_covered=1.0,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_A_REF,
            protection_type="guarantee",
            includes_restructuring=False,
            is_unilaterally_cancellable=True,
            is_unilaterally_changeable=None,
        ),
        _Guarantee(
            guarantee_reference=GUAR_B_REF,
            guarantee_type="sovereign_guarantee",
            guarantor=GUARANTOR_REF,
            currency="GBP",
            maturity_date=GUARANTEE_MATURITY_DATE,
            amount_covered=LOAN_DRAWN_AMOUNT,
            percentage_covered=1.0,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_B_REF,
            protection_type="guarantee",
            includes_restructuring=False,
            is_unilaterally_cancellable=False,
            is_unilaterally_changeable=True,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=guarantee_schema_plus)


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p110_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.10 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p110_counterparties()),
        ("loan", create_p110_loans()),
        ("rating", create_p110_ratings()),
        ("guarantee", create_p110_guarantees()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.10 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR/PS1-26 Art. 213(1)(c)(i) UCP unilateral-cancellation / -change gate")
    print(
        f"  Borrower:  {BORROWER_REF} (corporate, unrated, {EXPECTED_RW_UNRATED_BORROWER:.0%} RW)"
    )
    print(
        f"  Guarantor: {GUARANTOR_REF} (sovereign, CQS {GUARANTOR_CQS}, {EXPECTED_RW_SUBSTITUTED:.0%} RW)"
    )
    print()
    print(f"  {GUAR_BASE_REF}: both flags NULL -> ELIGIBLE both regimes -> RWA = 200,000")
    print(f"  {GUAR_A_REF}:    cancellable=True -> INELIGIBLE both regimes -> RWA = 1,000,000")
    print(
        f"  {GUAR_B_REF}:    changeable=True (cancellable=False) -> "
        "CRR RWA = 200,000 / B31 RWA = 1,000,000"
    )
    print()
    print("  Schema note: is_unilaterally_cancellable / is_unilaterally_changeable are")
    print("  extra columns beyond GUARANTEE_SCHEMA. Engine-implementer must add both as")
    print("  ColumnSpec(pl.Boolean, required=False) with a permissive null default.")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p110_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
