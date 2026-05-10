"""
Generate P1.100 fixtures: CRR Art. 137(1)-(2) ECA MEIP score direct risk-weight path.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/namespace.py)

Key responsibilities:
- Produce one sovereign counterparty row: SOV_KZ_001, entity_type=sovereign,
  country_code=KZ, no ECAI rating (sovereign_cqs=None), eca_score=2.
- Produce one loan row: USD 5,000,000 drawn, value_date=2026-01-15,
  maturity_date=2031-01-15, interest=0, seniority=senior.
- Produce one placeholder rating row: external_cqs=None, internal_pd=None,
  model_id=None — no ECAI assessment for Kazakhstan.
- No collateral, no guarantees, no provisions — clean single-factor SA test.
- Framework: CRR (CalculationConfig.crr()).

Scenario rationale:
    CRR Art. 137(1) allows a firm to use a nominated ECA's minimum export insurance
    premium (MEIP) score — an integer from 0 to 7 — instead of an ECAI CQS to
    determine the sovereign risk weight.  The risk weight is read directly from
    Art. 137(2) Table 9; there is no intermediate CQS step.

    Kazakhstan has no recognised ECAI rating but carries an OECD consensus score /
    ECA MEIP of 2, which Table 9 maps to 20% risk weight.

    Table 9 (CRR Art. 137(2)) — MEIP score → risk weight:
        0 →  0%      4 → 100%
        1 →  0%      5 → 100%
        2 → 20%  ← this scenario
        3 → 50%      6 → 100%
                     7 → 150%

Hand-calculation (CRR, CalculationConfig.crr()):
    EAD     = drawn_amount = 5,000,000 (USD; no FX, tested in isolation)
    RW      = Art. 137(2) Table 9, MEIP score 2 → 20% = 0.20
    RWA     = EAD × RW = 5,000,000 × 0.20 = 1,000,000

Expected outputs:
    exposure_class  = central_govt_central_bank
    approach_applied = standardised
    ead_final       = 5,000,000.0
    risk_weight     = 0.20
    rwa_final       = 1,000,000.0

References:
    - CRR Art. 137(1)-(2) Table 9: MEIP/ECA direct risk-weight mapping for sovereign.
    - CRR Art. 114: sovereign SA risk weights (Art. 137 overrides CQS lookup).
    - docs/specifications/crr/sa-risk-weights.md §Export Credit Agency Assessments.
    - src/rwa_calc/data/schemas.py COUNTERPARTY_SCHEMA: eca_score ColumnSpec(pl.Int8).

Usage:
    uv run python tests/fixtures/p1_100/p1_100.py
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

VALUE_DATE = date(2026, 1, 15)
MATURITY_DATE = date(2031, 1, 15)  # 5-year term loan

EAD = 5_000_000.0  # USD 5,000,000 drawn; interest=0 → EAD exact

# ECA MEIP score for Kazakhstan — Art. 137(1) nominated score.
ECA_SCORE: int = 2

# Art. 137(2) Table 9: MEIP score 2 → 20% risk weight.
EXPECTED_RISK_WEIGHT: float = 0.20

# Derived RWA: EAD × RW (no supporting factor — sovereign SA has no SF)
EXPECTED_RWA: float = EAD * EXPECTED_RISK_WEIGHT  # = 1,000,000.0

RATING_DATE = date(2026, 1, 15)


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.100 sovereign counterparty: entity_type=sovereign, country_code=KZ.

    No ECAI rating (sovereign_cqs=None): Kazakhstan is unrated under Art. 114.
    eca_score=2: nominated under Art. 137(1) as the MEIP classification input.
    The engine must prefer the Art. 137 MEIP path over Art. 114 CQS lookup when
    eca_score is present and sovereign_cqs is absent.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool
    eca_score: int | None

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
            # eca_score is excluded from the schema-dict — added as a typed
            # literal column below after dtypes_of(COUNTERPARTY_SCHEMA) build.
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.100 loan: USD 5,000,000 drawn, 5-year term.

    interest=0 so EAD = drawn_amount = 5,000,000 exactly.
    seniority=senior is the standard SA path (no LGD relevance for SA sovereign).
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
    P1.100 placeholder rating: no ECAI assessment for Kazakhstan.

    cqs=None and pd=None ensure the engine does not route via the Art. 114
    CQS lookup path.  The Art. 137 MEIP path is triggered solely by eca_score
    on the counterparty row.  model_id=None: pure SA scenario.
    """

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
    cqs: int | None
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


def create_p1100_counterparties() -> pl.DataFrame:
    """
    Return one P1.100 counterparty (SOV_KZ_001) as a DataFrame.

    eca_score=2 is added as a typed Int8 literal column after the schema-driven
    build because COUNTERPARTY_SCHEMA does not yet declare the column (the
    engine-implementer adds it).  This ensures the parquet output carries the
    column with the correct dtype and the test-writer can assert on it.
    """
    row = _Counterparty(
        counterparty_reference="SOV_KZ_001",
        counterparty_name="Republic of Kazakhstan (Unrated, ECA-scored)",
        entity_type="sovereign",
        country_code="KZ",
        default_status=False,
        apply_fi_scalar=False,
        is_managed_as_retail=False,
        eca_score=ECA_SCORE,
    )
    df = pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))
    # Attach eca_score as Int8 — matches the dtype the engine-implementer will
    # declare in COUNTERPARTY_SCHEMA: ColumnSpec(pl.Int8, required=False).
    return df.with_columns(pl.lit(ECA_SCORE).cast(pl.Int8).alias("eca_score"))


def create_p1100_loans() -> pl.DataFrame:
    """
    Return one P1.100 loan (LN_CRR_A14_ECA_001) as a DataFrame.

    EAD = drawn_amount = 5,000,000 USD; interest=0.
    """
    row = _Loan(
        loan_reference="LN_CRR_A14_ECA_001",
        counterparty_reference="SOV_KZ_001",
        currency="USD",
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        drawn_amount=EAD,
        interest=0.0,
        seniority="senior",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p1100_ratings() -> pl.DataFrame:
    """
    Return one P1.100 placeholder rating (no ECAI assessment) as a DataFrame.

    cqs=None and pd=None mean the Art. 114 CQS lookup returns 100% (unrated),
    but the Art. 137 path (eca_score=2 → 20%) must take precedence.
    The engine-implementer's test verifies the override wins.
    """
    row = _Rating(
        rating_reference="RTG_P1100_SOV_KZ_001",
        counterparty_reference="SOV_KZ_001",
        rating_type="external",
        rating_agency="none",
        rating_value="NR",
        cqs=None,
        pd=None,
        rating_date=RATING_DATE,
        is_solicited=False,
        model_id=None,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1100_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.100 parquet files and return a mapping of name -> path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1100_counterparties()),
        ("loan", create_p1100_loans()),
        ("rating", create_p1100_ratings()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.100 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR Art. 137(1)-(2) — ECA MEIP score 2 → 20% sovereign RW")
    print("          counterparty=SOV_KZ_001, entity_type=sovereign, country_code=KZ")
    print(f"          loan=LN_CRR_A14_ECA_001, USD {EAD:,.0f}")
    print(f"          value_date={VALUE_DATE}, maturity_date={MATURITY_DATE}")
    print(f"          eca_score={ECA_SCORE}, expected_rw={EXPECTED_RISK_WEIGHT:.0%}")
    print(f"          expected_rwa={EXPECTED_RWA:,.0f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1100_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
