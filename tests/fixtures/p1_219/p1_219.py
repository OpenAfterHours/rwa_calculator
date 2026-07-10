"""
Generate P1.219 fixtures: guarantee maturity-mismatch `t` must use residual protection
maturity (from `maturity_date`), not the seasoned `original_maturity_years` term.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/guarantees.py)

Key responsibilities:
- Produce two counterparty rows:
    CP-OBLIGOR-219:   corporate, GB, cqs=null (unrated -> 100% SA RW Art. 122)
    CP-GUARANTOR-219: institution, GB, cqs=1 (external rating -> 20% SA RW)
- Produce one loan row:
    EXP-219: GBP 1,000,000, value_date=2026-06-01, maturity_date=2030-06-01 (T=4.0y)
- Produce one guarantee row:
    G-219: maturity_date=2027-06-01 (residual t=1.0y -- authoritative post-fix)
           original_maturity_years=5.0 (seasoned; passes Art. 237(2)(a) >=1y gate;
           this is the WRONG t the pre-fix bug prefers over the residual)
           protection_type=guarantee (not credit_derivative -> H_restructuring=0)
- Produce one external rating row (guarantor CQS 1 only; obligor is unrated/null CQS).

Defect under test (pre-fix):
    crm/guarantees.py._apply_maturity_mismatch_to_guarantees() prefers
    ``original_maturity_years`` over the residual derived from ``maturity_date``
    when both are present:

        t_raw = when(original_maturity_years.is_not_null())
                .then(original_maturity_years)
                .otherwise(t_from_date)

    Art. 238(1) defines t as the years *remaining* to protection maturity — the
    residual, not the original seasoned term. With a seasoned 5-year guarantee
    whose *residual* maturity has run down to 1.0y, the bug uses t=5.0 (>= T=4.0y,
    "no mismatch") instead of the correct t=1.0 (< T=4.0y, mismatch scaling
    applies), understating RWA by ~76%.

Post-fix assertion (primary; identical CRR & B31 -- Art. 239(3) is
framework-invariant, mismatch guard already removed by P1.200):
    EXP-219 + G-219 -> residual t=1.0y wins -> Art. 239(3) scaling applies
    -> RWA = 840,000.0 (post-fix, correct)
    Pre-fix (bug, original wins): t=5.0 -> no mismatch -> RWA = 200,000.0 (understated)

Hand-calculations (Art. 239(3), day-count Actual/365, no leap adjustment):
    Loan EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000 GBP
    T_raw = (2030-06-01 - 2026-06-01) = 4.0y; T_eff = max(min(4.0,5.0),0.25) = 4.0
    Guarantee residual (maturity_date 2027-06-01 - reporting 2026-06-01) = 1.0y
    original_maturity_years = 5.0y; filter 5.0 >= 1.0 -> ELIGIBLE (Art. 237(2)(a))

    POST-FIX (residual wins): t_eff = max(1.0, 0.25) = 1.0
        mismatch: t_eff 1.0 < T_eff 4.0 -> scaling applies
        H_fx = 0 (GBP = GBP); H_r = 0 (protection_type=guarantee, not credit_derivative)
        G* = 1,000,000
        m = (t_eff - 0.25) / (T_eff - 0.25) = 0.75 / 3.75 = 0.2
        GA = 1,000,000 x 0.2 = 200,000.0
        guaranteed = min(GA, EAD) = 200,000.0; unguaranteed = 1,000,000 - 200,000 = 800,000.0
        RW_borrower = 1.00 (unrated corp, Art. 122); RW_guarantor = 0.20 (institution CQS 1)
        CORRECT RWA = 200,000.0 x 0.20 + 800,000.0 x 1.00 = 40,000.0 + 800,000.0 = 840,000.0

    PRE-FIX (bug, original wins): t_eff = 5.0
        mismatch: t_eff 5.0 < T_eff 4.0 -> False -> NO scaling -> GA = 1,000,000.0 (full face)
        BUGGED RWA = 1,000,000.0 x 0.20 = 200,000.0 (understated by 640,000, ~76%)

References:
    - CRR Art. 239(3): GA = G* x (t-0.25)/(T-0.25) maturity mismatch adjustment
    - CRR Art. 238(1): definition of protection maturity t (years remaining)
    - CRR Art. 237(2)(a): minimum original maturity >= 1y eligibility filter
    - CRR Art. 233/233(2): FX / restructuring haircuts (both zero in this scenario)
    - CRR Art. 122: unrated corporate 100% SA risk weight
    - CRR Art. 120 Table 3: institution CQS 1 -> 20% SA risk weight
    - PS1/26 mirrors of the above (mismatch scaling is framework-invariant post P1.200)
    - src/rwa_calc/data/schemas.py: GUARANTEE_SCHEMA (maturity_date, original_maturity_years)
    - src/rwa_calc/engine/crm/guarantees.py: _apply_maturity_mismatch_to_guarantees

Usage:
    python tests/fixtures/p1_219/p1_219.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants -- exported for test assertions
# ---------------------------------------------------------------------------

REPORTING_DATE = date(2026, 6, 1)

# Counterparty references
OBLIGOR_REF = "CP-OBLIGOR-219"
GUARANTOR_REF = "CP-GUARANTOR-219"

# Exposure reference
LOAN_REF = "EXP-219"

# Guarantee reference
GUARANTEE_REF = "G-219"

# Loan economics
LOAN_DRAWN_AMOUNT = 1_000_000.0
LOAN_EAD = LOAN_DRAWN_AMOUNT  # interest = 0

# Loan maturity: T = 4.0y from reporting date 2026-06-01
LOAN_VALUE_DATE = date(2026, 6, 1)
LOAN_MATURITY_DATE = date(2030, 6, 1)

# Guarantee maturity parameters -- the discriminating pair:
#   original_maturity_years is seasoned (5.0y, >= 1.0y -> eligible) -- the WRONG
#   t the pre-fix bug prefers.
#   maturity_date gives a residual of exactly 1.0y from the reporting date --
#   the CORRECT t per Art. 238(1) once the engine fix (residual wins) lands.
GUARANTEE_ORIGINAL_MATURITY_YEARS: float = 5.0  # seasoned term (bug's t pre-fix)
GUARANTEE_MATURITY_DATE = date(2027, 6, 1)  # residual t = 1.0y (correct t post-fix)

# Art. 239(3) scalars
_T_EFF: float = 4.0  # max(min(4.0, 5.0), 0.25)
_T_EFF_FLOOR: float = 0.25
_t_EFF_POST_FIX: float = 1.0  # max(1.0, 0.25) -- residual wins
_t_EFF_PRE_FIX: float = 5.0  # max(5.0, 0.25) -- original wins (bug)

# Derived: maturity multiplier m = (t-0.25)/(T-0.25) = 0.75/3.75 (post-fix only;
# pre-fix t=5.0 >= T=4.0 -> no mismatch -> m=1.0)
EXPECTED_MATURITY_MULTIPLIER: float = (_t_EFF_POST_FIX - _T_EFF_FLOOR) / (_T_EFF - _T_EFF_FLOOR)

# Guaranteed (GA) and unguaranteed portions (post-fix, correct)
EXPECTED_GUARANTEED_PORTION: float = LOAN_EAD * EXPECTED_MATURITY_MULTIPLIER
EXPECTED_UNGUARANTEED_PORTION: float = LOAN_EAD - EXPECTED_GUARANTEED_PORTION

# Risk weights
EXPECTED_GUARANTOR_RW: float = 0.20  # institution CQS 1, Art. 120 Table 3
_BORROWER_RW: float = 1.00  # unrated corporate, Art. 122

# Correct total RWA (post-fix, residual t wins -- identical CRR & B31)
EXPECTED_TOTAL_RWA: float = (
    EXPECTED_GUARANTEED_PORTION * EXPECTED_GUARANTOR_RW
    + EXPECTED_UNGUARANTEED_PORTION * _BORROWER_RW
)

# Bugged total RWA (pre-fix: original_maturity_years=5.0 >= T=4.0 -> no mismatch
# -> GA = full 1m)
BUGGED_TOTAL_RWA: float = LOAN_EAD * EXPECTED_GUARANTOR_RW  # = 200,000.0

# Guarantor rating
GUARANTOR_CQS = 1
_GUARANTOR_RATING_VALUE = "AA"  # CQS 1: AAA-AA-
RATING_AGENCY = "S&P"
RATING_DATE = date(2026, 6, 1)


# ---------------------------------------------------------------------------
# Minimal dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.219 counterparty row."""

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
    """P1.219 loan: GBP 1,000,000 drawn, 4-year maturity."""

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
    """P1.219 external ECAI rating."""

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
    P1.219 guarantee row: seasoned guarantee (long original, short residual).

    Carries BOTH ``maturity_date`` (residual t=1.0y -- correct post-fix) and
    ``original_maturity_years`` (5.0y seasoned term -- the WRONG t the pre-fix
    bug prefers). ``protection_type="guarantee"`` (not credit_derivative) so
    the restructuring haircut (Art. 233(2)) never applies regardless of
    ``includes_restructuring``.
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
    original_maturity_years: float

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
            "original_maturity_years": self.original_maturity_years,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1219_counterparties() -> pl.DataFrame:
    """
    Return two P1.219 counterparties (obligor + guarantor) as a DataFrame.

    CP-OBLIGOR-219:   corporate, GB, unrated (null CQS) -- 100% SA risk weight.
    CP-GUARANTOR-219: institution, GB, CQS 1 -- 20% SA risk weight.
    """
    rows = [
        _Counterparty(
            counterparty_reference=OBLIGOR_REF,
            counterparty_name="P1.219 Obligor Corporate GB Unrated",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=GUARANTOR_REF,
            counterparty_name="P1.219 Guarantor Institution GB CQS1",
            entity_type="institution",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1219_loan() -> pl.DataFrame:
    """
    Return one P1.219 loan as a DataFrame.

    EXP-219: GBP 1,000,000, value_date=2026-06-01, maturity_date=2030-06-01 (T=4.0y).
    EAD = drawn_amount (interest=0) = 1,000,000.
    """
    rows = [
        _Loan(
            loan_reference=LOAN_REF,
            counterparty_reference=OBLIGOR_REF,
            currency="GBP",
            value_date=LOAN_VALUE_DATE,
            maturity_date=LOAN_MATURITY_DATE,
            drawn_amount=LOAN_DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1219_ratings() -> pl.DataFrame:
    """
    Return one P1.219 external rating (guarantor only) as a DataFrame.

    CP-GUARANTOR-219: CQS 1 / S&P AA -> 20% SA institution RW.
    CP-OBLIGOR-219 is unrated -- no rating row (null CQS -> 100% unrated corporate RW).
    """
    rows = [
        _Rating(
            rating_reference="RTG-P1219-GUARANTOR",
            counterparty_reference=GUARANTOR_REF,
            rating_type="external",
            rating_agency=RATING_AGENCY,
            rating_value=_GUARANTOR_RATING_VALUE,
            cqs=GUARANTOR_CQS,
            pd=None,
            rating_date=RATING_DATE,
            is_solicited=True,
            model_id=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1219_guarantees() -> pl.DataFrame:
    """
    Return one P1.219 guarantee row as a DataFrame.

    G-219: guarantee from CP-GUARANTOR-219 on EXP-219.
        maturity_date = 2027-06-01 -> residual t = 1.0y (correct t post-fix)
        original_maturity_years = 5.0y (seasoned; >= 1.0y -> eligible; the WRONG
            t the pre-fix bug prefers over the residual)
        protection_type = "guarantee" (not credit_derivative -> H_r = 0)
        currency = GBP (no FX haircut vs GBP exposure)
        Post-fix Art. 239(3): GA = 1,000,000 x (1.0-0.25)/(4.0-0.25) = 200,000.0
    """
    # Use explicit schema dict to ensure optional GUARANTEE_SCHEMA fields are typed correctly
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
        "original_maturity_years": pl.Float64,
    }

    rows = [
        _Guarantee(
            guarantee_reference=GUARANTEE_REF,
            guarantee_type="guarantee",
            guarantor=GUARANTOR_REF,
            currency="GBP",
            maturity_date=GUARANTEE_MATURITY_DATE,
            amount_covered=LOAN_DRAWN_AMOUNT,
            percentage_covered=1.0,
            beneficiary_type="loan",
            beneficiary_reference=LOAN_REF,
            protection_type="guarantee",
            includes_restructuring=False,
            original_maturity_years=GUARANTEE_ORIGINAL_MATURITY_YEARS,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=guarantee_schema_plus)


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1219_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.219 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the data/ subdirectory
                    within the p1_219 fixture package.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent / "data"

    output_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1219_counterparties()),
        ("loan", create_p1219_loan()),
        ("rating", create_p1219_ratings()),
        ("guarantee", create_p1219_guarantees()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.219 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: guarantee maturity-mismatch t must use residual, not original term")
    print(f"  Obligor:   {OBLIGOR_REF} (corporate, unrated, 100% RW)")
    print(f"  Guarantor: {GUARANTOR_REF} (institution, CQS {GUARANTOR_CQS}, 20% RW)")
    print(f"  Loan:      {LOAN_REF}  GBP {LOAN_DRAWN_AMOUNT:,.0f}  maturity {LOAN_MATURITY_DATE}")
    print()
    print(
        f"  {GUARANTEE_REF}: maturity_date={GUARANTEE_MATURITY_DATE} (residual t=1.0y), "
        f"original_maturity_years={GUARANTEE_ORIGINAL_MATURITY_YEARS} (seasoned)"
    )
    print(f"    T_eff={_T_EFF:.2f}y")
    print(f"    POST-FIX t_eff={_t_EFF_POST_FIX:.2f}y (residual wins) -> mismatch -> Art.239(3)")
    print(f"    m = ({_t_EFF_POST_FIX}-0.25)/({_T_EFF}-0.25) = {EXPECTED_MATURITY_MULTIPLIER:.16f}")
    print(f"    GA = 1,000,000 x m = {EXPECTED_GUARANTEED_PORTION:.10f}")
    print(f"    CORRECT RWA = {EXPECTED_TOTAL_RWA:.10f}")
    print(f"    PRE-FIX t_eff={_t_EFF_PRE_FIX:.2f}y (original wins, bug) -> no mismatch")
    print(f"    BUGGED RWA = {BUGGED_TOTAL_RWA:.1f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1219_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
