"""
Generate P1.117 fixtures: B31 HVCRE slotting short-maturity subgrades.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (slotting fix)

Key responsibilities:
- Produce one counterparty row: HVCRE development SPV, GBP, entity_type=specialised_lending.
- Produce one specialised-lending metadata row: sl_type=ipre, slotting_category=strong,
  is_hvcre=True.
- Produce one loan row (primary): drawn_amount=10,000,000 GBP, maturity_date=2029-06-30
  (~2.0yr from reporting_date 2027-06-30 → is_short_maturity=True).
- Produce three optional regression loan rows:
    - HVCRE Good short (2.0yr)  → expected RW 0.95
    - HVCRE Strong long (3.0yr) → expected RW 0.95
    - HVCRE Good long (3.0yr)   → expected RW 1.20

Defect under test (pre-fix):
    In engine/slotting/namespace.py lookup_rw() (B31 branch), all HVCRE exposures
    are mapped to weights["hvcre"] regardless of remaining maturity:
        pl.when(is_hvcre_expr)
        .then(self._map_category(cat, weights["hvcre"]))
    This applies the long-maturity HVCRE weight (Strong=0.95, Good=1.20) even when
    remaining_maturity < 2.5yr. The correct Art. 153(5)(d) Table A weights for
    HVCRE short maturity are Strong=0.70, Good=0.95.
    The bug is noted inline at namespace.py line 415:
        "HVCRE column A/C is tracked separately (see P1.117) and not applied here."

Post-fix assertion (primary):
    exposure_reference=EXP_B31_HVCRE_SHORT_001
    counterparty_reference=CP_HVCRE_DEV_01
    is_hvcre=True, slotting_category=strong, remaining_maturity≈2.0yr → short=True
    expected_rw = 0.70 (Table A col A: HVCRE Strong short)
    ead_final   = 10_000_000
    expected_rwa = 7_000_000

Hand-calculation (Basel 3.1, Art. 153(5) Table A, CalculationConfig.basel_3_1(reporting_date=2027-06-30)):
    Step 1  Counterparty: entity_type="specialised_lending" → IRB exposure class:
            SPECIALISED_LENDING → slotting approach
    Step 2  HVCRE flag: is_hvcre=True
    Step 3  Remaining maturity: date(2029, 6, 30) − date(2027, 6, 30) = 2.0yr < 2.5yr
            → is_short_maturity=True
    Step 4  Risk weight lookup (Art. 153(5) Table A HVCRE, col A):
            Strong & short & HVCRE → 0.70
    Step 5  EAD: drawn_amount=10_000_000, interest=0 → EAD=10_000_000
    Step 6  RWA: 10_000_000 × 0.70 = 7_000_000

Regression rows (optional — for test-writer convenience):
    HVCRE Good short (2.0yr):  EAD=1_000_000 → RWA=950_000   (0.95 × col C)
    HVCRE Strong long (3.0yr): EAD=1_000_000 → RWA=950_000   (0.95 × col B)
    HVCRE Good long (3.0yr):   EAD=1_000_000 → RWA=1_200_000 (1.20 × col D)

Note on is_pre_operational: the proposal mentions is_pre_operational=False. This field
does not exist in SPECIALISED_LENDING_SCHEMA (PRA PS1/26 does not adopt the BCBS CRE33
pre-operational PF carve-out). Omitted from fixture; deviation reported.

References:
    - PRA PS1/26 Art. 153(5) Table A: HVCRE slotting risk weights
    - PRA PS1/26 Art. 153(5)(d): short-maturity subgrade concession (col A/C)
    - BCBS CRE33.5: supervisory slotting categories
    - docs/specifications/basel31/slotting-approach.md
    - src/rwa_calc/engine/slotting/namespace.py:415 (bug annotation)
    - src/rwa_calc/data/tables/b31_slotting.py (B31_SLOTTING_RISK_WEIGHTS_HVCRE)

Usage:
    uv run python tests/fixtures/p1_117/p1_117.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    LOAN_SCHEMA,
    SPECIALISED_LENDING_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Primary scenario identifiers
COUNTERPARTY_REF_PRIMARY = "CP_HVCRE_DEV_01"
LOAN_REF_PRIMARY = "EXP_B31_HVCRE_SHORT_001"

# Optional regression scenario identifiers
COUNTERPARTY_REF_GOOD = "CP_HVCRE_DEV_02"
COUNTERPARTY_REF_STRONG_LONG = "CP_HVCRE_DEV_03"
COUNTERPARTY_REF_GOOD_LONG = "CP_HVCRE_DEV_04"

LOAN_REF_GOOD_SHORT = "EXP_B31_HVCRE_GOOD_SHORT_001"
LOAN_REF_STRONG_LONG = "EXP_B31_HVCRE_STRONG_LONG_001"
LOAN_REF_GOOD_LONG = "EXP_B31_HVCRE_GOOD_LONG_001"

# Reporting date determines remaining maturity calculation
# CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))
REPORTING_DATE = date(2027, 6, 30)

VALUE_DATE = date(2027, 1, 1)

# Short-maturity date: 2029-06-30 gives ~2.0yr from 2027-06-30 → is_short_maturity=True
# Long-maturity date: 2030-06-30 gives ~3.0yr from 2027-06-30 → is_short_maturity=False
MATURITY_DATE_SHORT = date(2029, 6, 30)  # ~2.0yr residual
MATURITY_DATE_LONG = date(2030, 6, 30)  # ~3.0yr residual

# Primary scenario: HVCRE Strong, short maturity
PRIMARY_DRAWN_AMOUNT = 10_000_000.0
REGRESSION_DRAWN_AMOUNT = 1_000_000.0

# ---------------------------------------------------------------------------
# Expected outputs (assertions for test-writer)
# ---------------------------------------------------------------------------

# Art. 153(5) Table A HVCRE risk weights
# col A: HVCRE Strong short (<2.5yr)  = 0.70
# col B: HVCRE Strong long (>=2.5yr)  = 0.95
# col C: HVCRE Good short (<2.5yr)    = 0.95
# col D: HVCRE Good long (>=2.5yr)    = 1.20
EXPECTED_RW_HVCRE_STRONG_SHORT = 0.70  # Table A col A — primary assertion
EXPECTED_RW_HVCRE_GOOD_SHORT = 0.95  # Table A col C
EXPECTED_RW_HVCRE_STRONG_LONG = 0.95  # Table A col B
EXPECTED_RW_HVCRE_GOOD_LONG = 1.20  # Table A col D

EXPECTED_EAD_PRIMARY = PRIMARY_DRAWN_AMOUNT  # No interest; no AVA; no other reductions
EXPECTED_RWA_PRIMARY = PRIMARY_DRAWN_AMOUNT * EXPECTED_RW_HVCRE_STRONG_SHORT  # 7_000_000

EXPECTED_RWA_GOOD_SHORT = REGRESSION_DRAWN_AMOUNT * EXPECTED_RW_HVCRE_GOOD_SHORT  # 950_000
EXPECTED_RWA_STRONG_LONG = REGRESSION_DRAWN_AMOUNT * EXPECTED_RW_HVCRE_STRONG_LONG  # 950_000
EXPECTED_RWA_GOOD_LONG = REGRESSION_DRAWN_AMOUNT * EXPECTED_RW_HVCRE_GOOD_LONG  # 1_200_000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    HVCRE development SPV counterparty.

    entity_type="specialised_lending" directs the classifier to the slotting approach.
    Sector code 41.10 (Development of building projects) is appropriate for HVCRE.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float | None
    total_assets: float
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
            "total_assets": self.total_assets,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
        }


@dataclass(frozen=True)
class _SLMetadata:
    """
    Specialised lending metadata row.

    sl_type="ipre" with is_hvcre=True marks this as High-Volatility Commercial
    Real Estate per Art. 4(1)(120) and Art. 153(5) HVCRE table.
    slotting_category is set at the counterparty level and inherited by all exposures.
    """

    counterparty_reference: str
    sl_type: str
    slotting_category: str
    is_hvcre: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "sl_type": self.sl_type,
            "slotting_category": self.slotting_category,
            "is_hvcre": self.is_hvcre,
        }


@dataclass(frozen=True)
class _Loan:
    """
    Specialised lending drawn loan.

    lgd=0.45 stored for completeness (not used in slotting; slotting uses supervisory
    RW tables, not borrower IRB parameters).
    interest=0 and no provisions → EAD = drawn_amount exactly.
    seniority="senior" is the standard for project/real-estate finance.
    """

    loan_reference: str
    product_type: str
    book_code: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    drawn_amount: float
    interest: float
    lgd: float
    beel: float
    seniority: str

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "product_type": self.product_type,
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "lgd": self.lgd,
            "beel": self.beel,
            "seniority": self.seniority,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1117_counterparties() -> pl.DataFrame:
    """
    Return all P1.117 counterparties as a DataFrame.

    Four HVCRE development SPVs — one per subgrade scenario:
      CP_HVCRE_DEV_01: HVCRE IPRE, Strong (primary — short maturity)
      CP_HVCRE_DEV_02: HVCRE IPRE, Good (regression — short maturity)
      CP_HVCRE_DEV_03: HVCRE IPRE, Strong (regression — long maturity)
      CP_HVCRE_DEV_04: HVCRE IPRE, Good (regression — long maturity)
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_PRIMARY,
            counterparty_name="HVCRE Development SPV 01 (Strong, Short) - P1.117",
            entity_type="specialised_lending",
            country_code="GB",
            annual_revenue=None,
            total_assets=80_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_GOOD,
            counterparty_name="HVCRE Development SPV 02 (Good, Short) - P1.117",
            entity_type="specialised_lending",
            country_code="GB",
            annual_revenue=None,
            total_assets=80_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_STRONG_LONG,
            counterparty_name="HVCRE Development SPV 03 (Strong, Long) - P1.117",
            entity_type="specialised_lending",
            country_code="GB",
            annual_revenue=None,
            total_assets=80_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_GOOD_LONG,
            counterparty_name="HVCRE Development SPV 04 (Good, Long) - P1.117",
            entity_type="specialised_lending",
            country_code="GB",
            annual_revenue=None,
            total_assets=80_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1117_sl_metadata() -> pl.DataFrame:
    """
    Return specialised lending metadata for all P1.117 counterparties.

    sl_type="ipre" + is_hvcre=True → HVCRE Table A applies (Art. 153(5)).
    slotting_category differentiates Strong vs Good rows.
    """
    rows = [
        # Primary: HVCRE Strong (col A or B depending on maturity)
        _SLMetadata(
            counterparty_reference=COUNTERPARTY_REF_PRIMARY,
            sl_type="ipre",
            slotting_category="strong",
            is_hvcre=True,
        ),
        # Regression: HVCRE Good, short maturity (col C)
        _SLMetadata(
            counterparty_reference=COUNTERPARTY_REF_GOOD,
            sl_type="ipre",
            slotting_category="good",
            is_hvcre=True,
        ),
        # Regression: HVCRE Strong, long maturity (col B)
        _SLMetadata(
            counterparty_reference=COUNTERPARTY_REF_STRONG_LONG,
            sl_type="ipre",
            slotting_category="strong",
            is_hvcre=True,
        ),
        # Regression: HVCRE Good, long maturity (col D)
        _SLMetadata(
            counterparty_reference=COUNTERPARTY_REF_GOOD_LONG,
            sl_type="ipre",
            slotting_category="good",
            is_hvcre=True,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(SPECIALISED_LENDING_SCHEMA))


def create_p1117_loans() -> pl.DataFrame:
    """
    Return all P1.117 loans as a DataFrame.

    Primary (EXP_B31_HVCRE_SHORT_001):
        HVCRE IPRE Strong, short maturity (2.0yr), GBP 10m.
        Expected RW=0.70 (Table A col A), RWA=7,000,000.

    Regression rows (GBP 1m each):
        HVCRE Good short  → RW=0.95, RWA=950,000   (col C)
        HVCRE Strong long → RW=0.95, RWA=950,000   (col B)
        HVCRE Good long   → RW=1.20, RWA=1,200,000 (col D)
    """
    rows = [
        # =====================================================================
        # Primary: HVCRE Strong, short maturity — Table A col A = 70% RW
        # drawn=£10m → EAD=£10m → RWA=£7m
        # =====================================================================
        _Loan(
            loan_reference=LOAN_REF_PRIMARY,
            product_type="HVCRE_LOAN",
            book_code="SPECIALISED_LENDING",
            counterparty_reference=COUNTERPARTY_REF_PRIMARY,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_SHORT,  # 2029-06-30 ≈2.0yr → short
            currency="GBP",
            drawn_amount=PRIMARY_DRAWN_AMOUNT,
            interest=0.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =====================================================================
        # Regression: HVCRE Good, short maturity — Table A col C = 95% RW
        # drawn=£1m → EAD=£1m → RWA=£950k
        # =====================================================================
        _Loan(
            loan_reference=LOAN_REF_GOOD_SHORT,
            product_type="HVCRE_LOAN",
            book_code="SPECIALISED_LENDING",
            counterparty_reference=COUNTERPARTY_REF_GOOD,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_SHORT,  # 2029-06-30 ≈2.0yr → short
            currency="GBP",
            drawn_amount=REGRESSION_DRAWN_AMOUNT,
            interest=0.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =====================================================================
        # Regression: HVCRE Strong, long maturity — Table A col B = 95% RW
        # drawn=£1m → EAD=£1m → RWA=£950k
        # =====================================================================
        _Loan(
            loan_reference=LOAN_REF_STRONG_LONG,
            product_type="HVCRE_LOAN",
            book_code="SPECIALISED_LENDING",
            counterparty_reference=COUNTERPARTY_REF_STRONG_LONG,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_LONG,  # 2030-06-30 ≈3.0yr → long
            currency="GBP",
            drawn_amount=REGRESSION_DRAWN_AMOUNT,
            interest=0.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
        # =====================================================================
        # Regression: HVCRE Good, long maturity — Table A col D = 120% RW
        # drawn=£1m → EAD=£1m → RWA=£1.2m
        # =====================================================================
        _Loan(
            loan_reference=LOAN_REF_GOOD_LONG,
            product_type="HVCRE_LOAN",
            book_code="SPECIALISED_LENDING",
            counterparty_reference=COUNTERPARTY_REF_GOOD_LONG,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_LONG,  # 2030-06-30 ≈3.0yr → long
            currency="GBP",
            drawn_amount=REGRESSION_DRAWN_AMOUNT,
            interest=0.0,
            lgd=0.45,
            beel=0.0,
            seniority="senior",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1117_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.117 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1117_counterparties()),
        ("sl_metadata", create_p1117_sl_metadata()),
        ("loan", create_p1117_loans()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.117 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Primary scenario: HVCRE IPRE Strong, short maturity (2.0yr)")
    print("  CP_HVCRE_DEV_01 / EXP_B31_HVCRE_SHORT_001")
    print("  drawn=£10,000,000, maturity=2029-06-30, reporting=2027-06-30")
    print(f"  Expected RW={EXPECTED_RW_HVCRE_STRONG_SHORT:.2%}, EAD={EXPECTED_EAD_PRIMARY:,.0f}")
    print(f"  Expected RWA={EXPECTED_RWA_PRIMARY:,.0f}")
    print()
    print("Bug (pre-fix): all HVCRE → weights['hvcre'] regardless of maturity")
    print("  Strong short → 0.95 (wrong, should be 0.70)")
    print("Fix: add hvcre_short branch to lookup_rw() B31 path")
    print()
    print("Regression rows:")
    print(
        f"  HVCRE Good short  → RW={EXPECTED_RW_HVCRE_GOOD_SHORT:.2%}, RWA={EXPECTED_RWA_GOOD_SHORT:,.0f}"
    )
    print(
        f"  HVCRE Strong long → RW={EXPECTED_RW_HVCRE_STRONG_LONG:.2%}, RWA={EXPECTED_RWA_STRONG_LONG:,.0f}"
    )
    print(
        f"  HVCRE Good long   → RW={EXPECTED_RW_HVCRE_GOOD_LONG:.2%}, RWA={EXPECTED_RWA_GOOD_LONG:,.0f}"
    )


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1117_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
