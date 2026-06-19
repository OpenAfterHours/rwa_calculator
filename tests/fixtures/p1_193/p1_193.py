"""
Generate P1.193 fixtures: B31 rated corporate-SME uses Art. 122(2) Table 6, not
the unconditional 85% override.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/namespace.py)

Key responsibilities:
- Produce seven counterparty rows: one per CQS band (1-6) plus one unrated.
  Each counterparty is entity_type="corporate", GB, annual_revenue=GBP 30m
  (below the ~GBP 43.66m SME threshold) so the classifier sets
  exposure_class=corporate_sme and is_sme=True.
- Produce seven loan rows (EAD GBP 2,000,000 each), long-dated (5y),
  seniority=senior, non-defaulted, domestic GBP. No collateral, no guarantee.
- Produce six external rating rows (one per CQS 1-6), long-term (is_short_term=False),
  counterparty-level, rating_is_issue_specific=True. The unrated exposure
  (LOAN_SME_UNRATED) has no corresponding rating row.
- Produce an empty model_permission parquet (SA-only pipeline).

Defect under test (pre-fix):
    sa/namespace.py applies the 85% SME corporate risk weight unconditionally
    via ``uc.contains('CORPORATE') & uc.contains('SME')`` with no CQS gate.
    A rated CORPORATE_SME (CQS 1-6) is forced to 85%, discarding the Table-6
    weight set by the rw_table join.

Post-fix assertion (primary — LOAN_SME_RATED_CQS2):
    exposure_class = corporate_sme
    is_sme         = True
    cqs            = 2
    expected RW    = 0.50  (PRA PS1/26 Art. 122(2) Table 6, CQS 2)
    expected RWA   = 2,000,000 × 0.50 = 1,000,000

Full CQS ladder (EAD 2,000,000 each, SF=1.0 under B31):

    | Reference             | CQS   | Expected RW | Expected RWA |
    |-----------------------|-------|-------------|--------------|
    | LOAN_SME_RATED_CQS1   | 1     | 0.20        | 400,000      |
    | LOAN_SME_RATED_CQS2   | 2     | 0.50        | 1,000,000    |
    | LOAN_SME_RATED_CQS3   | 3     | 0.75        | 1,500,000    |
    | LOAN_SME_RATED_CQS4   | 4     | 1.00        | 2,000,000    |
    | LOAN_SME_RATED_CQS5   | 5     | 1.50        | 3,000,000    |
    | LOAN_SME_RATED_CQS6   | 6     | 1.50        | 3,000,000    |
    | LOAN_SME_UNRATED      | null  | 0.85        | 1,700,000    |

Anti-confound: LOAN_SME_RATED_CQS2.sa_final_risk_weight == 0.50 and != 0.85.
PRA CQS 5 = 1.50 (150%), NOT the BCBS 100% reduction — PRA retained 150%.

Config: CalculationConfig.basel_3_1(permission_mode=PermissionMode.STANDARDISED).

References:
    - PRA PS1/26 Art. 122(2) Table 6: B31 corporate ECAI risk weights by CQS.
    - PRA PS1/26 Art. 122(11): 85% SME corporate RW for unrated SME-qualifying
      corporates (replaces CRR 100% + 0.7619 supporting factor).
    - src/rwa_calc/data/tables/b31_risk_weights.py: B31_CORPORATE_RISK_WEIGHTS
      (Table 6) and B31_CORPORATE_SME_RW (0.85, Art. 122(11)).
    - src/rwa_calc/engine/sa/namespace.py:1293-1295: defect site (unconditional
      85% SME override); fix pattern at :1285-1291.
    - docs/specifications/crr/sa-risk-weights.md:1176-1207.
    - tests/fixtures/p1_103/p1_103.py: structural template (B31 short-term corporate
      ECAI).

Usage:
    python tests/fixtures/p1_193/p1_193.py
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

# Common dates — 5-year term loan (long-dated, no short-term gate triggered).
VALUE_DATE = date(2027, 1, 1)
MATURITY_DATE = date(2032, 1, 1)  # 5-year maturity

EAD = 2_000_000.0  # GBP 2,000,000 per exposure

# Annual revenue below ~GBP 43.66m (EUR 50m) SME threshold.
# Classifier derives is_sme=True and exposure_class="corporate_sme" from this.
ANNUAL_REVENUE = 30_000_000.0  # GBP 30m

RATING_DATE = date(2027, 1, 2)
RATING_AGENCY = "S&P"

# ---------------------------------------------------------------------------
# Per-CQS scenario definitions
# ---------------------------------------------------------------------------

# (counterparty_ref, loan_ref, rating_ref, cqs_or_None, s_and_p_rating,
#  expected_rw, expected_rwa)
_SCENARIOS: list[tuple[str, str, str | None, int | None, str | None, float, float]] = [
    # counterparty_ref           loan_ref                rating_ref               cqs  rating    rw    rwa
    ("CP_SME_CQS1_P1193", "LOAN_SME_RATED_CQS1", "RTG_SME_CQS1_P1193", 1, "AA-", 0.20, 400_000.0),
    ("CP_SME_CQS2_P1193", "LOAN_SME_RATED_CQS2", "RTG_SME_CQS2_P1193", 2, "A+", 0.50, 1_000_000.0),
    (
        "CP_SME_CQS3_P1193",
        "LOAN_SME_RATED_CQS3",
        "RTG_SME_CQS3_P1193",
        3,
        "BBB+",
        0.75,
        1_500_000.0,
    ),
    ("CP_SME_CQS4_P1193", "LOAN_SME_RATED_CQS4", "RTG_SME_CQS4_P1193", 4, "BB+", 1.00, 2_000_000.0),
    ("CP_SME_CQS5_P1193", "LOAN_SME_RATED_CQS5", "RTG_SME_CQS5_P1193", 5, "B+", 1.50, 3_000_000.0),
    ("CP_SME_CQS6_P1193", "LOAN_SME_RATED_CQS6", "RTG_SME_CQS6_P1193", 6, "CCC", 1.50, 3_000_000.0),
    ("CP_SME_UR_P1193", "LOAN_SME_UNRATED", None, None, None, 0.85, 1_700_000.0),
]

# Primary assertion (CQS 2 — proposal §2 primary assert)
PRIMARY_LOAN_REF = "LOAN_SME_RATED_CQS2"
PRIMARY_EXPECTED_RW: float = 0.50
PRIMARY_EXPECTED_RWA: float = EAD * PRIMARY_EXPECTED_RW  # 1,000,000

# Regression guard (unrated — must still get 85%)
UNRATED_LOAN_REF = "LOAN_SME_UNRATED"
UNRATED_EXPECTED_RW: float = 0.85
UNRATED_EXPECTED_RWA: float = EAD * UNRATED_EXPECTED_RW  # 1,700,000

# Buggy pre-fix risk weight for anti-confound assertion
BUGGY_RW_BEFORE_FIX: float = 0.85

# ---------------------------------------------------------------------------
# Expected outputs table (for test-writer assertions)
# ---------------------------------------------------------------------------

#: Full expected-output mapping keyed by loan_reference.
EXPECTED_OUTPUTS: dict[str, dict[str, float]] = {
    loan_ref: {"risk_weight": rw, "rwa": rwa} for _, loan_ref, _, _, _, rw, rwa in _SCENARIOS
}


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.193 corporate SME counterparty.

    entity_type="corporate", annual_revenue=GBP 30m ensures the classifier
    derives exposure_class=corporate_sme and is_sme=True without needing to
    set those flags directly on the exposure.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float
    default_status: bool
    apply_fi_scalar: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "annual_revenue": self.annual_revenue,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.193 senior term loan: GBP 2,000,000 drawn, 5-year maturity.

    seniority=senior avoids the Art. 122 subordinated 150% override.
    Non-defaulted (is_defaulted=False by schema default).
    Currency=GBP, country_code=GB → no Art. 123B currency-mismatch.
    """

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
    """
    P1.193 external long-term ECAI rating.

    is_short_term=False — long-dated assessment; routes the SA engine to
    Table 6 (Art. 122(2)) rather than Table 6A (Art. 122(3)).
    rating_is_issue_specific=True — the CQS is not nulled by the Art. 139(2B)
    inferred-rating disapplied gate in the hierarchy resolver.
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


def create_p1193_counterparties() -> pl.DataFrame:
    """
    Return all seven P1.193 counterparty rows as a DataFrame.

    One counterparty per CQS band (1-6) plus one unrated counterparty.
    All are entity_type=corporate, GB, annual_revenue=GBP 30m so the
    classifier derives exposure_class=corporate_sme and is_sme=True.
    """
    rows = [
        _Counterparty(
            counterparty_reference=cp_ref,
            counterparty_name=f"SME Corp P1193 ({loan_ref})",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=ANNUAL_REVENUE,
            default_status=False,
            apply_fi_scalar=False,
        )
        for cp_ref, loan_ref, *_ in _SCENARIOS
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1193_loans() -> pl.DataFrame:
    """
    Return all seven P1.193 loan rows as a DataFrame.

    Seven term loans, EAD GBP 2,000,000 each, 5-year maturity, seniority=senior.
    """
    rows = [
        _Loan(
            loan_reference=loan_ref,
            counterparty_reference=cp_ref,
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=EAD,
            interest=0.0,
            seniority="senior",
        )
        for cp_ref, loan_ref, *_ in _SCENARIOS
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1193_ratings() -> pl.DataFrame:
    """
    Return six P1.193 external rating rows as a DataFrame.

    One rating per CQS 1-6 counterparty. The unrated counterparty
    (CP_SME_UR_P1193) is intentionally absent — no rating row produces
    the null CQS that routes to the 85% Art. 122(11) SME branch.

    All ratings are long-term (is_short_term=False) and issue-specific
    (rating_is_issue_specific=True), routing the SA engine to Table 6.
    """
    rows = []
    for cp_ref, _loan_ref, rating_ref, cqs, rating_value, *_ in _SCENARIOS:
        if rating_ref is None:
            # Unrated exposure — no rating row
            continue
        # A rated scenario row always carries a CQS and rating value (the only
        # null-CQS row is the unrated one, skipped above).
        assert cqs is not None
        assert rating_value is not None
        rows.append(
            _Rating(
                rating_reference=rating_ref,
                counterparty_reference=cp_ref,
                rating_type="external",
                rating_agency=RATING_AGENCY,
                rating_value=rating_value,
                cqs=cqs,
                pd=None,
                rating_date=RATING_DATE,
                is_solicited=True,
                model_id=None,
                is_short_term=False,
                rating_is_issue_specific=True,
                scope_type=None,
                scope_id=None,
            )
        )
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1193_model_permission() -> pl.DataFrame:
    """
    Return an empty model_permission DataFrame.

    P1.193 is a pure SA scenario (CalculationConfig.basel_3_1() with
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


def save_p1193_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.193 parquet files and return a mapping of name -> path.

    Files written:
        counterparty.parquet    — 7 rows (one per CQS band + unrated)
        loan.parquet            — 7 rows (one per exposure reference)
        rating.parquet          — 6 rows (CQS 1-6; unrated has no rating)
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
        ("counterparty", create_p1193_counterparties()),
        ("loan", create_p1193_loans()),
        ("rating", create_p1193_ratings()),
        ("model_permission", create_p1193_model_permission()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.193 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario B31-A11: rated corporate-SME → Art. 122(2) Table 6")
    print(f"  EAD={EAD:,.0f} GBP per exposure, SF=1.0 (PS1/26 removes SME SF)")
    print(f"  Annual revenue={ANNUAL_REVENUE:,.0f} GBP → classifier: corporate_sme")
    print(f"  Maturity: {VALUE_DATE} → {MATURITY_DATE} (5-year, long-dated)")
    print()
    print("  Reference              CQS  Expected RW  Expected RWA")
    print("  " + "-" * 55)
    for _, loan_ref, _, cqs, _, rw, rwa in _SCENARIOS:
        cqs_str = str(cqs) if cqs is not None else "null"
        print(f"  {loan_ref:<25} {cqs_str:<4}  {rw:.2%}       {rwa:>12,.0f}")
    print()
    print(f"  Primary assert: {PRIMARY_LOAN_REF}")
    print(f"    sa_final_risk_weight == {PRIMARY_EXPECTED_RW}  (Table 6 CQS 2)")
    print(
        f"    sa_final_risk_weight != {BUGGY_RW_BEFORE_FIX}  (anti-confound: pre-fix buggy value)"
    )
    print(f"    rwa_post_factor      == {PRIMARY_EXPECTED_RWA:,.0f}")
    print()
    print(f"  Regression guard: {UNRATED_LOAN_REF}")
    print(f"    sa_final_risk_weight == {UNRATED_EXPECTED_RW}  (Art. 122(11) 85% must still fire)")
    print(f"    rwa_post_factor      == {UNRATED_EXPECTED_RWA:,.0f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1193_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
