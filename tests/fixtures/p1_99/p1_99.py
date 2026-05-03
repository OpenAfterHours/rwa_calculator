"""
Generate P1.99 fixtures: CRR Art. 120(2) Table 4 short-term rated institution risk weights.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/namespace.py pin)

Key responsibilities:
- Produce six counterparty rows: INSTITUTION, DE, CQS 1-6, no SCRA grade.
- Produce six loan rows: EUR 1,000,000 drawn, value_date=2027-01-01,
  maturity_date=2027-04-01 (90 days ≈ 0.2466y ≤ 0.25y residual maturity threshold).
- Produce six external rating rows linking each counterparty to its CQS.
- No collateral, no guarantee, no provisions — clean single-factor SA test.
- Framework: CRR (CalculationConfig.crr()).

Scenario rationale:
    Art. 120(2) Table 4 applies when a rated institution's residual maturity is ≤ 3 months
    (≤ 0.25 years in the engine's year-fraction representation).  This fixture pins all six
    CQS bands in one parametric set so regression tests can verify the complete table.

    The engine derives original_maturity_years from (maturity_date − value_date) / 365.0
    when original_maturity_years is absent from the loan row (90/365 ≈ 0.2466 ≤ 0.25).
    The SA calculator then routes to the short-term institution branch for all six rows.

Hand-calculation (CRR, CalculationConfig.crr()):
    EAD per loan  = drawn_amount = 1,000,000 (EUR; with FX EUR->GBP=1.0 for simplicity)
    Maturity gate = residual_maturity = 90/365 ≈ 0.2466 ≤ 0.25y → Art. 120(2) Table 4

    Table 4 risk weights (CRR Art. 120(2)):
        CQS 1 → RW 0.20  → RWA  200,000
        CQS 2 → RW 0.20  → RWA  200,000
        CQS 3 → RW 0.20  → RWA  200,000
        CQS 4 → RW 0.50  → RWA  500,000
        CQS 5 → RW 0.50  → RWA  500,000
        CQS 6 → RW 1.50  → RWA 1,500,000

    Boundary note: residual = original = 90 days for these exposures because
    value_date == origination_date. Both Art. 120(2) (residual ≤ 3m) and the
    engine's original_maturity_years derivation path apply cleanly.

References:
    - CRR Art. 120(2) Table 4: short-term preferential RW for rated institutions.
    - CRR Art. 120(1) Table 3: general (long-term) rated institution RW table.
    - src/rwa_calc/data/tables/crr_risk_weights.py: INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR
    - src/rwa_calc/engine/sa/namespace.py: short-term institution branch (residual_mty ≤ 0.25)
    - docs/specifications/crr/sa-risk-weights.md: Table 4 (lines ~263-272)

Usage:
    uv run python tests/fixtures/p1_99/p1_99.py
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

# Loan date window: 90 days maturity → residual/original ≈ 0.2466y ≤ 0.25y threshold.
# This matches the P1.169 facility date window (2027-01-01 to 2027-04-01) so both
# scenarios can be run against the same FX fixture if needed.
VALUE_DATE = date(2027, 1, 1)
MATURITY_DATE = date(2027, 4, 1)  # 90 days from VALUE_DATE

EAD = 1_000_000.0  # EUR 1,000,000 drawn per loan; interest=0 → EAD exact

# Rating agency used for all six rows (S&P scale mirrors the CQS mapping)
RATING_AGENCY = "S&P"
RATING_DATE = date(2027, 1, 2)  # one day after value_date — current at origination

# CQS → S&P rating value mapping (representative mid-band values per CQS)
_CQS_RATING_VALUE: dict[int, str] = {
    1: "AA",    # CQS 1: AAA to AA-  → use AA (mid-band)
    2: "A",     # CQS 2: A+ to A-    → use A  (mid-band)
    3: "BBB",   # CQS 3: BBB+ to BBB-→ use BBB
    4: "BB",    # CQS 4: BB+ to BB-  → use BB
    5: "B",     # CQS 5: B+ to B-    → use B
    6: "CCC",   # CQS 6: CCC+ and below → use CCC
}

# Art. 120(2) Table 4 expected risk weights — authoritative source:
# src/rwa_calc/data/tables/crr_risk_weights.py INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR
EXPECTED_RISK_WEIGHTS: dict[int, float] = {
    1: 0.20,
    2: 0.20,
    3: 0.20,
    4: 0.50,
    5: 0.50,
    6: 1.50,
}

EXPECTED_RWA: dict[int, float] = {cqs: rw * EAD for cqs, rw in EXPECTED_RISK_WEIGHTS.items()}


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.99 institution counterparty: entity_type=institution, country_code=DE.

    No SCRA grade (scra_grade=None): the scenario exercises the ECAI-rated path
    exclusively, so SCRA is not relevant and must not interfere.
    DE country (non-UK) avoids any domestic currency / UK RGLA branch.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.99 loan: EUR 1,000,000 drawn, 90-day maturity (≤ 3 months).

    The engine derives original_maturity_years = (maturity_date - value_date) / 365.
    With VALUE_DATE=2027-01-01 and MATURITY_DATE=2027-04-01 (90 days):
        original_maturity_years = 90 / 365 ≈ 0.2466 ≤ 0.25

    This fires the Art. 120(2) short-term gate for all rated CQS 1-6 rows.
    No lgd, no seniority override needed: SA calculation does not use these for
    institution risk-weight lookup.
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
    P1.99 external ECAI rating: S&P scale, CQS 1-6, pd=None.

    External ratings have pd=None (PD is an internal-rating concept).
    is_solicited=True: solicited ratings are given preference in ECAI mapping.
    model_id=None: no IRB model — this is a pure SA scenario.
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


def create_p199_counterparties() -> pl.DataFrame:
    """
    Return six P1.99 counterparties (one per CQS band) as a DataFrame.

    All rows: entity_type=institution, country_code=DE, not defaulted, no FI scalar.
    Unique counterparty_reference per CQS so ratings and loans link unambiguously.
    """
    rows = [
        _Counterparty(
            counterparty_reference=f"CP-P199-INST-CQS{cqs}",
            counterparty_name=f"DE Institution CQS{cqs} Short-Term P1.99",
            entity_type="institution",
            country_code="DE",
            default_status=False,
            apply_fi_scalar=False,
        )
        for cqs in range(1, 7)
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p199_loans() -> pl.DataFrame:
    """
    Return six P1.99 loans (one per CQS band) as a DataFrame.

    Each loan: EUR 1,000,000 drawn, value_date=2027-01-01, maturity_date=2027-04-01.
    90 days / 365 ≈ 0.2466y ≤ 0.25y residual maturity → Art. 120(2) Table 4 fires.
    interest=0 so EAD = drawn_amount = 1,000,000 exactly.
    """
    rows = [
        _Loan(
            loan_reference=f"LN-P199-INST-CQS{cqs}",
            counterparty_reference=f"CP-P199-INST-CQS{cqs}",
            currency="EUR",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=EAD,
            interest=0.0,
            seniority="senior",
        )
        for cqs in range(1, 7)
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p199_ratings() -> pl.DataFrame:
    """
    Return six P1.99 external ratings (one per CQS band) as a DataFrame.

    External ratings (rating_type=external) with pd=None drive the SA ECAI-rated path.
    Each row links its counterparty to the corresponding CQS via S&P rating values.
    """
    rows = [
        _Rating(
            rating_reference=f"RTG-P199-INST-CQS{cqs}",
            counterparty_reference=f"CP-P199-INST-CQS{cqs}",
            rating_type="external",
            rating_agency=RATING_AGENCY,
            rating_value=_CQS_RATING_VALUE[cqs],
            cqs=cqs,
            pd=None,
            rating_date=RATING_DATE,
            is_solicited=True,
            model_id=None,
        )
        for cqs in range(1, 7)
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p199_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.99 parquet files and return a mapping of name -> path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p199_counterparties()),
        ("loan", create_p199_loans()),
        ("rating", create_p199_ratings()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.99 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR Art. 120(2) Table 4 — short-term rated institution RW")
    print(f"          entity_type=institution, country_code=DE, EUR {EAD:,.0f}")
    print(f"          value_date={VALUE_DATE}, maturity_date={MATURITY_DATE} (90 days)")
    print("          residual_maturity ≈ 0.2466y ≤ 0.25y → Art. 120(2) gate fires")
    print("")
    print("  CQS  Expected RW  Expected RWA")
    for cqs, rw in EXPECTED_RISK_WEIGHTS.items():
        print(f"   {cqs}     {rw:.0%}        {EXPECTED_RWA[cqs]:>12,.0f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p199_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
