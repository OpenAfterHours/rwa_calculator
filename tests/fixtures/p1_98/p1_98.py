"""
Generate P1.98 fixtures: subordinated corporate A-IRB LGD floor — fallback path 25%.

Pipeline position:
    fixture-builder output → test-writer → engine-implementer (formulas.py fix)

Key responsibilities:
- Produce one counterparty row: large corporate, GBP, annual_revenue=200,000,000.
- Produce one loan row: drawn_amount=1,000,000, lgd=0.10, seniority="subordinated",
  effective_maturity=2.5 (via maturity_date ~2.5y from reporting date).
- Produce one internal rating row: pd=0.0050, model_id=CORP_AIRB_P198.
- Produce one model-permissions row: approach="advanced_irb", exposure_class="corporate".

Defect under test (pre-fix):
    In formulas.py _lgd_floor_expression(), when:
        has_exposure_class=False   (exposure_class column absent from schema)
        has_seniority=True         (seniority column present)
        seniority="subordinated"
    The fallback branch fires:
        pl.when(is_subordinated).then(floors.subordinated_unsecured)  →  0.50
    But Art. 161(5) specifies a SINGLE 25% floor for ALL unsecured corporate A-IRB
    exposures regardless of seniority. The 50% value is the F-IRB supervisory LGD
    (Art. 161(1)(b)), not an A-IRB floor.

Post-fix assertion:
    lgd_floor = 0.25 (not 0.50)
    lgd_floored = max(lgd_own=0.10, 0.25) = 0.25

Hand-calculation (Basel 3.1, Art. 153):
    PD_own  = 0.0050   (above 0.0005 floor)
    LGD_own = 0.10     (below 0.25 floor — floor binds)
    EAD     = 1,000,000 (drawn_amount + interest=0)
    M       = 2.5

    Correlation R:
        f_PD = (1 - exp(-50 × 0.0050)) / (1 - exp(-50)) ≈ 0.22119921692859512
        R    = 0.12 × f_PD + 0.24 × (1 - f_PD)         ≈ 0.21345609396856858

    Capital K (LGD_floored=0.25):
        G(0.0050) ≈ -2.5758293035489004
        G(0.999)  ≈  3.0902323061678132
        cond_PD   ≈  0.09766
        K = 0.25 × cond_PD - 0.0050 × 0.25 ≈ 0.023166

    Maturity adjustment (b = (0.11852 - 0.05478 × ln(0.0050))²):
        b  ≈ 0.167118474
        MA = 1 / (1 - 1.5 × b) ≈ 1.3345392   (M=2.5, so M-2.5=0, MA term simplifies)

    Scaling factor (Basel 3.1) = 1.0

    RW  ≈ 0.023166 × 12.5 × 1.0 × 1.3345392 ≈ 0.38646
    RWA ≈ 1,000,000 × 0.38646               ≈ 386,459
    EL  = 0.0050 × 0.25 × 1,000,000         = 1,250

References:
    - PRA PS1/26 Art. 161(5): A-IRB unsecured corporate LGD floor 25%.
    - PRA PS1/26 Art. 160(1): Corporate PD floor 0.05%.
    - PRA PS1/26 Art. 153: IRB K, correlation, maturity adjustment.
    - Bug site: src/rwa_calc/engine/irb/formulas.py lines 157-166.
    - Config:   src/rwa_calc/contracts/config.py LGDFloors.subordinated_unsecured.
    - Spec:     docs/specifications/crr/airb-calculation.md lines 77-89.

Usage:
    uv run python tests/fixtures/p1_98/p1_98.py
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
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)


# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "CP_CORP_SUB_AIRB_P198"
LOAN_REF = "LN_CORP_SUB_AIRB_P198"
RATING_REF = "RTG_INT_CORP_SUB_AIRB_P198"
MODEL_ID = "CORP_AIRB_P198"

VALUE_DATE = date(2026, 1, 1)
# 2.5 years from 2026-01-01 → 2028-07-01; effective_maturity=2.5 is also set
# directly on the loan row for unambiguous M=2.5 in the IRB formula.
MATURITY_DATE = date(2028, 7, 1)
RATING_DATE = date(2026, 1, 2)

# Scenario inputs (match the hand-calculation in the module docstring)
PD_OWN = 0.0050        # 0.50% own PD estimate
LGD_OWN = 0.10         # 10% own LGD — below 25% A-IRB floor (floor binds)
DRAWN_AMOUNT = 1_000_000.0
EFFECTIVE_MATURITY = 2.5

# Expected outputs (for assertions in the acceptance test)
EXPECTED_LGD_FLOOR = 0.25       # Art. 161(5) — primary assertion (bug: 0.50)
EXPECTED_LGD_FLOORED = 0.25     # max(0.10, 0.25) = 0.25
EXPECTED_PD_FLOORED = 0.0050    # max(0.0050, 0.0005) = 0.0050
EXPECTED_CORRELATION = 0.21345609396856858
EXPECTED_K = 0.023166           # approximate
EXPECTED_MA = 1.3345392         # approximate (M=2.5 → M-2.5=0, MA=1/(...))
EXPECTED_RISK_WEIGHT = 0.38646  # approximate
EXPECTED_RWA = 386_459.0        # approximate (1_000_000 × RW)
EXPECTED_EL = 1_250.0           # exact: 0.0050 × 0.25 × 1_000_000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.98 counterparty: large corporate, GBP-denominated.

    annual_revenue=200,000,000 — below 440m large-corp threshold per Basel 3.1
    (no SME adjustment; standard corporate IRB correlation formula applies).
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float
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
class _Loan:
    """
    P1.98 loan: subordinated, lgd=0.10 (below 25% floor), drawn 1,000,000.

    seniority="subordinated" is the key field: when the IRB calculator is
    invoked without an exposure_class column (fallback path), the buggy code
    routes subordinated to floors.subordinated_unsecured=0.50 instead of
    the correct Art. 161(5) floor of 0.25.

    effective_maturity=2.5 is set directly to avoid any maturity_date rounding
    ambiguity and to ensure M=2.5 in the formula (M-2.5=0 simplifies MA term).
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
    effective_maturity: float

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
            "effective_maturity": self.effective_maturity,
        }


@dataclass(frozen=True)
class _Rating:
    """
    P1.98 internal rating: pd=0.0050, model_id=CORP_AIRB_P198.

    model_id links to the P1.98 model_permission row which grants AIRB for
    the corporate exposure class.  PD=0.0050 > corporate floor 0.0005 so the
    floor does not bind here (simplifying the hand-calc).
    """

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
    cqs: int
    pd: float
    rating_date: date
    is_solicited: bool
    model_id: str

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
class _ModelPermission:
    """
    P1.98 model permission: AIRB for corporate, no geo or book restrictions.

    A dedicated model_id (CORP_AIRB_P198) avoids any cross-test interference
    with the existing UK_CORP_AIRB_01 permission that has a TRADE_FINANCE
    book exclusion.
    """

    model_id: str
    exposure_class: str
    approach: str
    country_codes: str | None
    excluded_book_codes: str | None

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "exposure_class": self.exposure_class,
            "approach": self.approach,
            "country_codes": self.country_codes,
            "excluded_book_codes": self.excluded_book_codes,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p198_counterparty() -> pl.DataFrame:
    """
    Return the P1.98 counterparty as a single-row DataFrame.

    Large corporate, GBP, annual_revenue=200m (below 440m large-corp threshold).
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF,
            counterparty_name="Subordinated AIRB Corporate Ltd",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=200_000_000.0,
            total_assets=400_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p198_loan() -> pl.DataFrame:
    """
    Return the P1.98 loan as a single-row DataFrame.

    drawn_amount=1,000,000  interest=0  → EAD=1,000,000
    lgd=0.10  seniority="subordinated"  effective_maturity=2.5
    No collateral, no guarantee — forces the _lgd_floor_expression fallback path.
    """
    rows = [
        _Loan(
            loan_reference=LOAN_REF,
            product_type="SUBORDINATED_LOAN",
            book_code="CORP_LENDING",
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="GBP",
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            lgd=LGD_OWN,
            beel=0.0,
            seniority="subordinated",
            effective_maturity=EFFECTIVE_MATURITY,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p198_rating() -> pl.DataFrame:
    """
    Return the P1.98 internal rating as a single-row DataFrame.

    pd=0.0050 (0.50%) — above corporate 0.05% floor so floor does not bind.
    model_id=CORP_AIRB_P198 links to the P1.98 model permission granting AIRB.
    """
    rows = [
        _Rating(
            rating_reference=RATING_REF,
            counterparty_reference=COUNTERPARTY_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="3A",
            cqs=3,
            pd=PD_OWN,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p198_model_permission() -> pl.DataFrame:
    """
    Return the P1.98 model permission as a single-row DataFrame.

    Grants AIRB for the corporate exposure class with no geo or book restrictions.
    A dedicated model_id avoids interference with existing permission rows.
    """
    rows = [
        _ModelPermission(
            model_id=MODEL_ID,
            exposure_class="corporate",
            approach="advanced_irb",
            country_codes=None,
            excluded_book_codes=None,
        )
    ]
    return pl.DataFrame(
        [r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA)
    )


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p198_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.98 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p198_counterparty()),
        ("loan", create_p198_loan()),
        ("rating", create_p198_rating()),
        ("model_permission", create_p198_model_permission()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.98 fixture generation complete")
    print("-" * 60)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 60)
    print("Scenario: subordinated corporate A-IRB, lgd_own=0.10")
    print("          seniority='subordinated', no collateral")
    print("          forces _lgd_floor_expression fallback path")
    print(f"Bug path: floors.subordinated_unsecured=0.50 (wrong)")
    print(f"Fix:      floors.unsecured=0.25 per Art. 161(5)")
    print(f"Expected: lgd_floored={EXPECTED_LGD_FLOORED}, rwa~{EXPECTED_RWA:,.0f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p198_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
