"""
Generate P1.121 fixtures: CRR Art. 121(3) unrated institution short-term 20% risk weight.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/namespace.py pin)

Key responsibilities:
- Produce one counterparty row: institution, country_code=VN, sovereign_cqs=4,
  no external CQS (unrated), no SCRA grade.
- Produce one loan row: USD 1,000,000 drawn, value_date=2026-01-15,
  maturity_date=2026-04-10 (85 days ≈ 0.2329y ≤ 0.25y residual maturity threshold).
- Produce one ratings row: external rating absent — represented by an internal
  placeholder row with no cqs, driving the unrated SA path.
- No collateral, no guarantees, no provisions, no model_permissions (forces SA path).
- Framework: CRR (CalculationConfig.crr(reporting_date=date(2026,1,15))).

Scenario rationale:
    CRR Art. 121(3) states: where the residual maturity of exposures to unrated
    institutions is three months or less, the risk weight shall be 20%, regardless
    of the sovereign CQS band that would otherwise apply under Art. 121(1) Table 5.

    Vietnam (VN) sovereign CQS=4 → under Art. 121(1) Table 5 (long-term unrated
    institution): sovereign_cqs=4 → institution risk weight = 100%. The Art. 121(3)
    short-term override reduces this to 20%, making the fixture a strong regression
    test: any failure to apply the short-term gate will produce 100%, not 20%.

    The engine derives original_maturity_years from (maturity_date − value_date) / 365.0
    when the column is absent from the loan row (85 / 365 ≈ 0.2329 ≤ 0.25).

Hand-calculation (CRR, CalculationConfig.crr(reporting_date=date(2026, 1, 15))):
    EAD = drawn_amount = 1,000,000 (USD; FX USD->GBP assumed 1.0 for test simplicity)
    Maturity gate = residual_maturity = 85/365 ≈ 0.2329 ≤ 0.25y → Art. 121(3) fires

    Without short-term override:
        sovereign_cqs = 4 → Art. 121(1) Table 5 → RW = 1.00 → RWA = 1,000,000

    With Art. 121(3) short-term override (correct):
        residual_maturity ≤ 0.25y AND unrated → RW = 0.20 → RWA = 200,000

    Expected:
        risk_weight = 0.20
        rwa         = 200,000

    Boundary note: is_short_term_trade_lc=False and is_sft=False are explicit so the
    Art. 121(4) trade-finance preferential path (also 20% but a different code branch)
    is not exercised. The regression test isolates Art. 121(3) specifically.

References:
    - CRR Art. 121(3): short-term unrated institution 20% RW (residual maturity ≤ 3m)
    - CRR Art. 121(1) Table 5: sovereign-derived unrated institution RW (VN sovereign_cqs=4 → 100%)
    - CRR Art. 120(2) Table 4: short-term rated institution RW (not applicable — unrated path)
    - src/rwa_calc/data/tables/crr_risk_weights.py: INSTITUTION_UNRATED_SOVEREIGN_RW,
      INSTITUTION_UNRATED_SHORT_TERM_RW_CRR
    - src/rwa_calc/engine/sa/namespace.py: unrated institution short-term branch
    - docs/specifications/crr/sa-risk-weights.md: "Short-Term Institution Exposures"

Usage:
    uv run python tests/fixtures/p1_121/p1_121.py
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

COUNTERPARTY_REF = "CP_INST_UNRATED_VN_001"
LOAN_REF = "LN_CRR_A14_001"
RATING_REF = "RTG_CRR_A14_001"

# Loan date window: 85 days maturity → residual/original ≈ 0.2329y ≤ 0.25y threshold.
# value_date is also the reporting_date so residual = original.
VALUE_DATE = date(2026, 1, 15)
MATURITY_DATE = date(2026, 4, 10)  # 85 days from VALUE_DATE

# Vietnam sovereign CQS = 4.
# Art. 121(1) Table 5: sovereign_cqs=4 → long-term unrated institution RW = 100%.
# Art. 121(3): residual ≤ 0.25y AND unrated → override to 20%.
SOVEREIGN_CQS: int = 4

EAD = 1_000_000.0  # USD 1,000,000 drawn; interest=0 → EAD exact

# Art. 121(3) short-term override (the key assertion)
EXPECTED_RISK_WEIGHT: float = 0.20
EXPECTED_RWA: float = EXPECTED_RISK_WEIGHT * EAD  # 200,000

# Long-term unrated value (shows what breaks if short-term gate is missing)
LONG_TERM_RISK_WEIGHT: float = 1.00  # Art. 121(1) Table 5, sovereign_cqs=4


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    Unrated institution in Vietnam.

    entity_type=institution routes to CRR Art. 121 (unrated path because no cqs row).
    sovereign_cqs=4 sets the Art. 121(1) Table 5 long-term weight to 100% — the
    scenario proves that Art. 121(3) overrides this to 20% for short maturities.
    scra_grade=None: not applicable; SCRA is the Basel 3.1 unrated institution
    mechanism, not used in CRR framework.
    is_financial_sector_entity=False: no FI scalar (Art. 153(2) IRB only).
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    sovereign_cqs: int
    default_status: bool
    apply_fi_scalar: bool
    is_financial_sector_entity: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "sovereign_cqs": self.sovereign_cqs,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_financial_sector_entity": self.is_financial_sector_entity,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.121 loan: USD 1,000,000 drawn, 85-day maturity (≤ 3 months).

    The engine derives original_maturity_years = (maturity_date - value_date) / 365.
    With VALUE_DATE=2026-01-15 and MATURITY_DATE=2026-04-10 (85 days):
        original_maturity_years = 85 / 365 ≈ 0.2329 ≤ 0.25

    This fires the Art. 121(3) short-term gate for the unrated institution.
    is_short_term_trade_lc=False: isolates Art. 121(3); Art. 121(4) trade-finance
    path (also 20%, but different code branch) is intentionally not exercised.
    is_sft=False: not a securities financing transaction.
    book_code=BANKING: standard banking book treatment.
    """

    loan_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    drawn_amount: float
    interest: float
    seniority: str
    book_code: str
    is_sft: bool

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
            "book_code": self.book_code,
            "is_sft": self.is_sft,
        }


@dataclass(frozen=True)
class _Rating:
    """
    P1.121 rating: internal placeholder confirming no external CQS assignment.

    rating_type=internal with pd=None and cqs=None (absent) means the SA engine
    finds no external CQS for this counterparty and routes to the unrated institution
    branch (Art. 121). model_id=None: no IRB model, forces SA path.

    An explicit rating row is required so the ratings join doesn't fail — the row
    is present but carries no CQS signal.
    """

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str | None
    rating_value: str | None
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


def create_p1121_counterparties() -> pl.DataFrame:
    """
    Return one P1.121 counterparty (unrated Vietnamese institution) as a DataFrame.

    entity_type=institution, country_code=VN, sovereign_cqs=4.
    No external rating → Art. 121 unrated path.
    Long-term (Art. 121(1) Table 5): sovereign_cqs=4 → RW=100%.
    Short-term override (Art. 121(3)): residual ≤ 0.25y → RW=20%.
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="Vietnam Unrated Institution — P1.121",
        entity_type="institution",
        country_code="VN",
        sovereign_cqs=SOVEREIGN_CQS,
        default_status=False,
        apply_fi_scalar=False,
        is_financial_sector_entity=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1121_loans() -> pl.DataFrame:
    """
    Return one P1.121 loan (85-day USD 1m) as a DataFrame.

    85 days / 365 ≈ 0.2329y ≤ 0.25y residual maturity → Art. 121(3) fires.
    interest=0 so EAD = drawn_amount = 1,000,000 exactly.
    is_short_term_trade_lc=False isolates Art. 121(3) from Art. 121(4) trade finance.
    """
    row = _Loan(
        loan_reference=LOAN_REF,
        counterparty_reference=COUNTERPARTY_REF,
        currency="USD",
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        drawn_amount=EAD,
        interest=0.0,
        seniority="senior",
        book_code="BANKING",
        is_sft=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p1121_ratings() -> pl.DataFrame:
    """
    Return one P1.121 rating placeholder (no CQS) as a DataFrame.

    rating_type=internal with cqs=None confirms no external ECAI assessment.
    The SA engine finds no external CQS → routes to unrated institution branch.
    model_id=None: no IRB model → SA path enforced.
    """
    row = _Rating(
        rating_reference=RATING_REF,
        counterparty_reference=COUNTERPARTY_REF,
        rating_type="internal",
        rating_agency=None,
        rating_value=None,
        cqs=None,
        pd=None,
        rating_date=VALUE_DATE,
        is_solicited=False,
        model_id=None,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1121_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.121 parquet files and return a mapping of name -> path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1121_counterparties()),
        ("loan", create_p1121_loans()),
        ("rating", create_p1121_ratings()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.121 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR Art. 121(3) — short-term unrated institution 20% RW")
    print(f"          entity_type=institution, country_code=VN, sovereign_cqs={SOVEREIGN_CQS}")
    print(f"          value_date={VALUE_DATE}, maturity_date={MATURITY_DATE} (85 days)")
    print("          residual_maturity ≈ 0.2329y ≤ 0.25y → Art. 121(3) gate fires")
    print("")
    print(
        f"  Long-term (Art. 121(1) Table 5, sovereign_cqs={SOVEREIGN_CQS}): RW={LONG_TERM_RISK_WEIGHT:.0%}"
    )
    print(
        f"  Short-term override (Art. 121(3)):                               RW={EXPECTED_RISK_WEIGHT:.0%}"
    )
    print(f"  EAD = {EAD:,.0f}  |  Expected RWA = {EXPECTED_RWA:,.0f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1121_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
