"""
Generate P1.196 fixtures: CRR rated corporate-SME (CQS 1) uses Art. 122 CQS-table
weight (20%), not the unconditional 100% override.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/namespace.py)

Key responsibilities:
- Produce one counterparty row: CP-SME-CQS1, entity_type=corporate, GB,
  annual_revenue=GBP 10,000,000 (well below the ~GBP 43.66m / EUR 50m SME
  threshold) so the classifier derives exposure_class=corporate_sme and is_sme=True.
  is_managed_as_retail=False keeps the row off the Art. 123 retail-75% branch.
- Produce one external rating row for CP-SME-CQS1: cqs=1 (AAA to AA- long-term),
  is_short_term=False, rating_is_issue_specific=True.
- Produce one drawn loan EXP-SME-CQS1: drawn_amount=GBP 1,000,000, currency=GBP,
  is_defaulted=False, is_buy_to_let=False. Below the GBP 2.2m Art. 501 tier-1
  threshold, so blended supporting factor is pure tier-1 = 0.7619.
- Produce an empty model_permission parquet (SA-only pipeline; no IRB permissions).

Defect under test (pre-fix):
    sa/namespace.py _apply_crr_risk_weight_overrides applies the 100% corporate-SME
    override unconditionally (no CQS gate) for any uc.contains("CORPORATE") &
    uc.contains("SME") exposure. A CQS 1 SME corporate that should carry 20%
    (Art. 122 Table 5) is overwritten to 100% — a 5x overstatement before the
    Art. 501 supporting factor is applied.

Post-fix assertion (primary):
    exposure_class         = corporate_sme
    cqs                    = 1
    risk_weight            = 0.20  (Art. 122 CQS 1 — NOT 1.00)
    ead_final              = 1,000,000.00
    rwa_pre_factor         = 200,000.00
    supporting_factor      = 0.7619  (Art. 501 tier-1, E* 1,000,000 < GBP 2.2m)
    supporting_factor_applied = True
    rwa_post_factor        = 152,380.00  (200,000 x 0.7619)

Contrast (buggy pre-fix path):
    risk_weight            = 1.00 (unconditional override)
    rwa_pre_factor         = 1,000,000
    rwa_post_factor        = 761,900  (1,000,000 x 0.7619) — 5x overstatement

Config: CalculationConfig.crr(permission_mode=PermissionMode.STANDARDISED).

References:
    - CRR Art. 122: corporate SA risk weights by CQS (Table 5); CQS1 = 20%.
    - CRR Art. 501: SME supporting factor; tier-1 threshold GBP 2.2m; SF = 0.7619.
    - src/rwa_calc/engine/sa/namespace.py:1383-1384: defect site (unconditional
      100% SME override); fix pattern: B31 sibling at :1295-1300 (P1.193).
    - src/rwa_calc/data/tables/crr_risk_weights.py:507-515: CORPORATE_RISK_WEIGHTS
      (CQS1=0.20); :590: CRR_CORPORATE_SME_RW=1.00.
    - src/rwa_calc/engine/supporting_factors.py:369-406: Art. 501 SF calculator.
    - docs/specifications/crr/sa-risk-weights.md:619-629.
    - tests/fixtures/p1_193/p1_193.py: structural template (B31 sibling fixture).

Usage:
    python tests/fixtures/p1_196/p1_196.py
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

# Common dates — 3-year term loan (not short-term, no short-term gate).
VALUE_DATE = date(2024, 1, 1)
MATURITY_DATE = date(2027, 1, 1)  # 3-year maturity

EAD = 1_000_000.0  # GBP 1,000,000 drawn amount

# Annual revenue GBP 10m — well below ~GBP 43.66m (EUR 50m) SME threshold.
# Classifier derives is_sme=True and exposure_class="corporate_sme" from this.
# Also satisfies Art. 501 SME supporting factor eligibility (< EUR 50m group turnover).
ANNUAL_REVENUE = 10_000_000.0  # GBP 10m

RATING_DATE = date(2024, 1, 2)
RATING_AGENCY = "S&P"

# CQS 1 corresponds to AAA to AA- in S&P long-term rating scale.
# Art. 122 Table 5: CQS1 -> 20% risk weight.
CQS = 1
RATING_VALUE = "AA-"

# Reference IDs
COUNTERPARTY_REF = "CP-SME-CQS1"
LOAN_REF = "EXP-SME-CQS1"
RATING_REF = "RTG-SME-CQS1-P1196"

# ---------------------------------------------------------------------------
# Expected outputs (for test-writer assertions)
# ---------------------------------------------------------------------------

#: Art. 122 Table 5 CQS1 risk weight.
EXPECTED_RISK_WEIGHT: float = 0.20

#: RWA before Art. 501 supporting factor.
EXPECTED_RWA_PRE_FACTOR: float = EAD * EXPECTED_RISK_WEIGHT  # 200,000.00

#: Art. 501 tier-1 supporting factor (E* = 1,000,000 < GBP 2,200,000 threshold).
EXPECTED_SUPPORTING_FACTOR: float = 0.7619

#: Final RWA post supporting factor.
EXPECTED_RWA_POST_FACTOR: float = round(EXPECTED_RWA_PRE_FACTOR * EXPECTED_SUPPORTING_FACTOR, 2)  # 152,380.00

#: Pre-fix buggy risk weight (unconditional 100% override, for anti-confound assertion).
BUGGY_RW_BEFORE_FIX: float = 1.00

EXPECTED_OUTPUTS: dict[str, float | bool | int] = {
    "risk_weight": EXPECTED_RISK_WEIGHT,
    "rwa_pre_factor": EXPECTED_RWA_PRE_FACTOR,
    "supporting_factor": EXPECTED_SUPPORTING_FACTOR,
    "supporting_factor_applied": True,
    "rwa_post_factor": EXPECTED_RWA_POST_FACTOR,
    "ead_final": EAD,
    "cqs": CQS,
}


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.196 corporate SME counterparty for CRR CQS-1 scenario.

    entity_type=corporate, annual_revenue=GBP 10m ensures the classifier derives
    exposure_class=corporate_sme and is_sme=True without needing to set those
    flags directly on the exposure.
    is_managed_as_retail=False keeps the row off the Art. 123 retail-75% branch.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "annual_revenue": self.annual_revenue,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.196 drawn term loan: GBP 1,000,000, 3-year maturity.

    seniority=senior avoids the Art. 122 subordinated 150% override.
    Non-defaulted (is_defaulted=False) — Art. 501 excludes defaulted exposures.
    is_buy_to_let=False — Art. 501 excludes BTL.
    Currency=GBP, country_code derives GB from counterparty → no Art. 123B
    currency-mismatch multiplier.
    EAD (GBP 1,000,000) < GBP 2,200,000 Art. 501 tier-1 threshold → pure
    tier-1 supporting factor of 0.7619.
    """

    loan_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    drawn_amount: float
    interest: float
    seniority: str
    is_defaulted: bool
    is_buy_to_let: bool

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
            "is_defaulted": self.is_defaulted,
            "is_buy_to_let": self.is_buy_to_let,
        }


@dataclass(frozen=True)
class _Rating:
    """
    P1.196 external long-term ECAI rating: CQS 1 (AA- from S&P).

    is_short_term=False — long-dated assessment routes the SA engine to
    Table 5 (Art. 122 long-term) rather than Table 5A short-term.
    rating_is_issue_specific=True — not an inferred/issuer-level rating;
    the Art. 139(2B) SL null-out gate in the hierarchy resolver is not triggered.
    scope_type/scope_id are null — counterparty-level rating (no facility scope).
    """

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
    is_short_term: bool
    rating_is_issue_specific: bool
    scope_type: str | None
    scope_id: str | None

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
            "is_short_term": self.is_short_term,
            "rating_is_issue_specific": self.rating_is_issue_specific,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1196_counterparties() -> pl.DataFrame:
    """
    Return the single P1.196 counterparty row as a DataFrame.

    One CQS-1 rated SME corporate: entity_type=corporate, GB,
    annual_revenue=GBP 10m so the classifier derives exposure_class=corporate_sme
    and is_sme=True. is_managed_as_retail=False keeps the row off the
    Art. 123 retail-75% branch.
    """
    cp = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="SME Corp P1196 CQS1",
        entity_type="corporate",
        country_code="GB",
        annual_revenue=ANNUAL_REVENUE,
        default_status=False,
        apply_fi_scalar=False,
        is_managed_as_retail=False,
    )
    return pl.DataFrame([cp.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1196_loans() -> pl.DataFrame:
    """
    Return the single P1.196 loan row as a DataFrame.

    GBP 1,000,000 drawn, 3-year maturity, seniority=senior, non-defaulted,
    not BTL. EAD below the GBP 2.2m Art. 501 tier-1 threshold — SF = 0.7619.
    """
    loan = _Loan(
        loan_reference=LOAN_REF,
        counterparty_reference=COUNTERPARTY_REF,
        currency="GBP",
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        drawn_amount=EAD,
        interest=0.0,
        seniority="senior",
        is_defaulted=False,
        is_buy_to_let=False,
    )
    return pl.DataFrame([loan.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p1196_ratings() -> pl.DataFrame:
    """
    Return the single P1.196 external rating row as a DataFrame.

    CQS 1 (AA- / AAA-AA-), long-term (is_short_term=False), issue-specific
    (rating_is_issue_specific=True). Counterparty-level scope (scope_type=None).
    This CQS 1 triggers the Art. 122 Table 5 -> 20% lookup in the SA engine
    and must NOT be overridden by the unconditional 100% SME override (the defect).
    """
    rating = _Rating(
        rating_reference=RATING_REF,
        counterparty_reference=COUNTERPARTY_REF,
        rating_type="external",
        rating_agency=RATING_AGENCY,
        rating_value=RATING_VALUE,
        cqs=CQS,
        pd=None,
        rating_date=RATING_DATE,
        is_solicited=True,
        model_id=None,
        is_short_term=False,
        rating_is_issue_specific=True,
        scope_type=None,
        scope_id=None,
    )
    return pl.DataFrame([rating.to_dict()], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1196_model_permission() -> pl.DataFrame:
    """
    Return an empty model_permission DataFrame.

    P1.196 is a pure SA scenario (CalculationConfig.crr() with
    PermissionMode.STANDARDISED). No IRB permissions are needed.
    """
    return pl.DataFrame(
        schema={
            "model_id": pl.String,
            "exposure_class": pl.String,
            "approach": pl.String,
            "country_codes": pl.List(pl.String),
        }
    )


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1196_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.196 parquet files and return a mapping of name -> path.

    Files written:
        counterparty.parquet     — 1 row  (CP-SME-CQS1)
        loan.parquet             — 1 row  (EXP-SME-CQS1)
        rating.parquet           — 1 row  (RTG-SME-CQS1-P1196, CQS=1)
        model_permission.parquet — 0 rows (SA-only pipeline)

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
        ("counterparty", create_p1196_counterparties()),
        ("loan", create_p1196_loans()),
        ("rating", create_p1196_ratings()),
        ("model_permission", create_p1196_model_permission()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.196 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario CRR-SA-SME-CQS1: rated corporate-SME CQS 1 -> Art. 122 20% RW")
    print(f"  EAD={EAD:,.0f} GBP, annual_revenue={ANNUAL_REVENUE:,.0f} GBP -> corporate_sme")
    print(f"  CQS={CQS} ({RATING_VALUE}) -> risk_weight={EXPECTED_RISK_WEIGHT}")
    print(f"  rwa_pre_factor   = {EXPECTED_RWA_PRE_FACTOR:,.2f}")
    print(f"  supporting_factor = {EXPECTED_SUPPORTING_FACTOR} (Art. 501 tier-1, E*<GBP 2.2m)")
    print(f"  rwa_post_factor  = {EXPECTED_RWA_POST_FACTOR:,.2f}")
    print()
    print(f"  Pre-fix buggy risk_weight = {BUGGY_RW_BEFORE_FIX} (anti-confound assertion)")
    print(f"  Primary assert: risk_weight == {EXPECTED_RISK_WEIGHT} (NOT {BUGGY_RW_BEFORE_FIX})")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1196_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
