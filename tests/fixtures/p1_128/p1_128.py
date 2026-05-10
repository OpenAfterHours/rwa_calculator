"""
Generate P1.128 fixtures: B31 Art. 121(4) SCRA short-term trade finance exception.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/namespace.py)

Key responsibilities:
- Produce one counterparty row: institution, GB, entity_type="bank", scra_grade="A",
  no external CQS (unrated path — no rating row with a non-null cqs).
- Produce one facility row: term_loan, GBP 1,000,000, 151-day original maturity
  (2027-01-01 to 2027-06-01), is_short_term_trade_lc=True (Art. 121(4) gate flag).
  No short-term ECAI rating row is attached — SCRA unrated path.
- Produce one loan row: GBP 1,000,000 drawn, same 151-day maturity window.
- Produce one empty ratings parquet (RATINGS_SCHEMA schema, zero rows) — absence of
  any external CQS forces the SCRA unrated path.
- No collateral, no guarantee, no provisions.
- Framework: CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30),
  permission_mode=PermissionMode.STANDARDISED).

Scenario rationale:
    Art. 121(4) (B31 / PRA PS1/26) extends the short-term SCRA treatment to
    self-liquidating trade finance exposures with original maturity > 3 months but
    ≤ 6 months.  Without this exception, a 151-day unrated SCRA Grade-A institution
    exposure would attract the long-term SCRA Grade A weight of 40% (B31_SCRA_RISK_WEIGHTS).
    With Art. 121(4) the engine must widen the SCRA short-term window from original_mty
    <= 0.25y to (original_mty <= 0.25y) | (is_short_term_trade_lc & original_mty <= 0.5y),
    reducing the weight to 20% (B31_SCRA_SHORT_TERM_RISK_WEIGHTS Grade A).

    The fixture exercises the widened window at a maturity just inside the 0.5y ceiling:
        151 days = 2027-06-01 − 2027-01-01
        original_maturity_years = 151 / 365 ≈ 0.4137
        0.25y < 0.4137y <= 0.5y            → long-term SCRA fires without Art. 121(4)
        is_short_term_trade_lc = True       → Art. 121(4) extends short-term window
        SCRA Grade A + short-term window    → RW = 0.20

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1()):
    EAD  = drawn_amount + interest = 1,000,000 + 0.00 = 1,000,000
    RW   = B31_SCRA_SHORT_TERM_RISK_WEIGHTS["A"] = 0.20  (Art. 121(4))
    RWA  = EAD × RW = 1,000,000 × 0.20 = 200,000
    K    = RWA × 0.08 = 16,000

    Contrastive (without Art. 121(4) fix — long-term SCRA Grade A):
        RW  = B31_SCRA_RISK_WEIGHTS["A"] = 0.40
        RWA = 1,000,000 × 0.40 = 400,000  ← must NOT match

References:
    - PRA PS1/26 Art. 121(4): SCRA short-term treatment extended to trade finance
      exposures with original maturity > 3m and <= 6m, self-liquidating.
    - PRA PS1/26 Art. 121(3) / CRE20.18: SCRA Grade A short-term (<=3m) RW = 20%.
    - src/rwa_calc/data/tables/b31_risk_weights.py: B31_SCRA_RISK_WEIGHTS (long-term),
      B31_SCRA_SHORT_TERM_RISK_WEIGHTS (short-term Grade A = 0.20).
    - src/rwa_calc/data/schemas.py: FACILITY_SCHEMA field is_short_term_trade_lc (line 81).
    - src/rwa_calc/engine/sa/namespace.py: _b31_append_institution_maturity_branches,
      in_st_window expression (lines 525-526).
    - docs/user-guide/exposure-classes/institution.md: SCRA narrative + Art. 121(4).

Usage:
    uv run python tests/fixtures/p1_128/p1_128.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "CP_INST_SCRA_TRADE_01"
FACILITY_REF = "FAC_INST_SCRA_TRADE_01"
LOAN_REF = "LN_INST_SCRA_TRADE_01"

# 151-day original maturity window.
# original_maturity_years = 151 / 365 ≈ 0.4137y
# 0.25y < 0.4137y <= 0.5y → inside Art. 121(4) extended short-term window only.
VALUE_DATE = date(2027, 1, 1)
MATURITY_DATE = date(2027, 6, 1)  # 151 days from VALUE_DATE

EAD = 1_000_000.0  # GBP 1,000,000; interest=0 → EAD exact

# Art. 121(4) + SCRA Grade A → short-term RW = 20%.
# B31_SCRA_SHORT_TERM_RISK_WEIGHTS["A"] = Decimal("0.20").
EXPECTED_RISK_WEIGHT: float = 0.20
EXPECTED_EAD: float = EAD
EXPECTED_RWA: float = EAD * EXPECTED_RISK_WEIGHT  # 200,000
EXPECTED_K: float = EXPECTED_RWA * 0.08  # 16,000

# Without Art. 121(4): long-term SCRA Grade A = 40%.
# B31_SCRA_RISK_WEIGHTS["A"] = Decimal("0.40").
SCRA_LONG_TERM_FALLBACK_RISK_WEIGHT: float = 0.40
SCRA_LONG_TERM_FALLBACK_RWA: float = EAD * SCRA_LONG_TERM_FALLBACK_RISK_WEIGHT  # 400,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.128 institution counterparty: entity_type=bank, country_code=GB, scra_grade=A.

    entity_type="bank" resolves to ExposureClass.INSTITUTION via ENTITY_TYPE_TO_SA_CLASS.
    scra_grade="A" sets the SCRA grade used by B31_SCRA_SHORT_TERM_RISK_WEIGHTS.
    institution_cqs=None (absent): no ECAI rating — forces SCRA (unrated) path.
    No external rating row in the ratings parquet confirms the unrated path.
    country_code="GB" kept inert — GBP exposure in a GBP-reporting firm, so
    Art. 121(6) FX floor does not apply.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    scra_grade: str

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "scra_grade": self.scra_grade,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.128 loan: GBP 1,000,000 drawn, 151-day original maturity.

    original_maturity_years = 151 / 365 ≈ 0.4137y.
    This is above the standard 3-month (0.25y) short-term gate but within the
    Art. 121(4) trade-finance extended window of 0.5y.
    interest=0 so EAD = drawn_amount exactly.
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


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1128_counterparty() -> pl.DataFrame:
    """
    Return one P1.128 counterparty row as a DataFrame.

    entity_type=bank, country_code=GB, scra_grade=A, not defaulted, no FI scalar.
    No institution_cqs — forces SCRA unrated path under Basel 3.1.
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="Banco Comercio Brasil — SCRA Grade A Unrated",
        entity_type="bank",
        country_code="GB",
        default_status=False,
        apply_fi_scalar=False,
        scra_grade="A",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1128_facility() -> pl.DataFrame:
    """
    Return one P1.128 facility row as a DataFrame.

    is_short_term_trade_lc=True: gates Art. 121(4) extended short-term window.
    No short-term ECAI rating is attached for this scenario (SCRA path — no
    dedicated short-term ECAI assessment exists on the ratings table). The
    151-day maturity (0.4137y) is between 0.25y and 0.5y — inside the trade
    finance window only when is_short_term_trade_lc=True.
    """
    base_row = {
        "facility_reference": FACILITY_REF,
        "product_type": "term_loan",
        "book_code": "FI_LENDING",
        "counterparty_reference": COUNTERPARTY_REF,
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
        "currency": "GBP",
        "limit": EAD,
        "committed": True,
        "lgd": 0.45,
        "beel": 0.0,
        "is_revolving": False,
        "seniority": "senior",
        "risk_type": "MR",
        "is_short_term_trade_lc": True,
    }
    return pl.DataFrame([base_row], schema=dtypes_of(FACILITY_SCHEMA))


def create_p1128_loan() -> pl.DataFrame:
    """
    Return one P1.128 loan row as a DataFrame.

    GBP 1,000,000 drawn, value_date=2027-01-01, maturity_date=2027-06-01 (151 days).
    151/365 ≈ 0.4137y > 0.25y → standard short-term gate does NOT fire.
    is_short_term_trade_lc on the facility (Art. 121(4)) extends window to 0.5y.
    """
    row = _Loan(
        loan_reference=LOAN_REF,
        counterparty_reference=COUNTERPARTY_REF,
        currency="GBP",
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        drawn_amount=EAD,
        interest=0.0,
        seniority="senior",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p1128_ratings() -> pl.DataFrame:
    """
    Return an empty ratings DataFrame conforming to RATINGS_SCHEMA.

    Zero rows — no external ECAI rating for this counterparty.
    Absence of any rating row with a non-null cqs forces the SCRA (unrated)
    institution path; the engine finds no cp_institution_cqs and falls back
    to the scra_grade="A" field on the counterparty.
    """
    return pl.DataFrame(schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1128_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.128 parquet files and return a mapping of name -> path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1128_counterparty()),
        ("facility", create_p1128_facility()),
        ("loan", create_p1128_loan()),
        ("rating", create_p1128_ratings()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    original_maturity_years = (MATURITY_DATE - VALUE_DATE).days / 365.0
    print("P1.128 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: B31 Art. 121(4) SCRA short-term trade finance exception")
    print(f"          entity_type=bank, country_code=GB, scra_grade=A, GBP {EAD:,.0f}")
    print(f"          value_date={VALUE_DATE}, maturity_date={MATURITY_DATE} (151 days)")
    print(f"          original_maturity_years = {original_maturity_years:.4f}y")
    print(
        f"          0.25y < {original_maturity_years:.4f}y <= 0.5y AND is_short_term_trade_lc=True"
    )
    print("          -> Art. 121(4) extended window fires -> SCRA Grade A short-term")
    print("")
    print("  SCRA Grade  RW        Expected RWA    Capital (8%)")
    print(
        f"  A (short)   {EXPECTED_RISK_WEIGHT:.0%}       {EXPECTED_RWA:>12,.0f}    {EXPECTED_K:>10,.0f}"
    )
    print("")
    print("  Contrastive (long-term SCRA Grade A, without Art. 121(4) fix):")
    print(
        f"  A (long)    {SCRA_LONG_TERM_FALLBACK_RISK_WEIGHT:.0%}       "
        f"{SCRA_LONG_TERM_FALLBACK_RWA:>12,.0f}    {SCRA_LONG_TERM_FALLBACK_RWA * 0.08:>10,.0f}"
    )


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1128_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
