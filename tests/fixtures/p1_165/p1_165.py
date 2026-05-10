"""
Generate P1.165 fixtures: CRR receivables collateral, F-IRB pipeline, no Art. 224 haircut.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/haircuts.py)

Scenario design (CRR-D6r — "CRR receivables collateral, F-IRB, no Art. 224 volatility haircut"):

    A single counterparty / single facility / single drawn loan / single receivables
    collateral row that exercises the Art. 224 haircut removal path for CRR F-IRB.

    The load-bearing assertion this scenario pins:

        CRR Art. 224 Tables 1-4 enumerate eligible financial-collateral instrument
        categories (debt securities, equity, gold, cash, CIUs).  Receivables are NOT
        listed.  Therefore the per-row collateral_haircut emitted by apply_haircuts
        for a receivables collateral item must be 0.0 under CRR.

        The regulatorily correct treatment of receivables (F-IRB only, CRR Art. 199(5))
        flows entirely through the Art. 230 Foundation Collateral Method:
            - LGDS = 35% (senior) / 65% (subordinated) — Art. 230 Table 5
            - Overcollateralisation ratio = 1.25x (Art. 230(2), FIRB_OVERCOLLATERALISATION_RATIOS)
            - No separate Hc volatility haircut

        With EAD = 1,000,000, adjusted collateral value = 800,000, OC ratio = 1.25:
            effectively_secured = 800,000 / 1.25 = 640,000
            secured portion LGD  = 35%
            unsecured portion LGD = 45% (Art. 161(1)(a), senior corporate, non-FSE)
            LGD* = (0.35 x 640,000 + 0.45 x 360,000) / 1,000,000
                 = (224,000 + 162,000) / 1,000,000 = 0.386

Hand calculations:
    EAD (pre-CRM)           = 1,000,000.00  (on-BS, CCF = 100%)
    Hc                      = 0.0           (Art. 224 has no receivables row)
    Hfx                     = 0.0           (GBP/GBP, same currency)
    value_after_haircut     = 800,000 x (1 - 0 - 0) = 800,000.00
    value_after_maturity_adj = 800,000.00   (residual_maturity_years = None -> 10y >= 3y, factor=1.0)
    adjusted_value          = 800,000.00
    effectively_secured     = 800,000 / 1.25 = 640,000.00
    lgd_secured (LGD*)      = (0.35 x 640,000 + 0.45 x 360,000) / 1,000,000 = 0.386
    RWA                     ≈ 1,102,548 (Art. 153(1) K formula; see scenario for detail)

References:
    - CRR Art. 199(5):      receivables eligible as non-financial collateral (F-IRB only)
    - CRR Art. 224:         Tables 1-4 supervisory volatility haircuts (receivables NOT listed)
    - CRR Art. 230(1)-(2):  Foundation Collateral Method — LGDS = 35%/65%, OC = 1.25x
    - CRR Art. 230 Table 5: senior LGDS 35%, subordinated 65%, OC ratio 1.25x
    - CRR Art. 153(1):      F-IRB K formula and 1.06 scaling factor
    - CRR Art. 161(1)(a):   LGDU senior corporate non-FSE = 45%
    - CRR Art. 162:         maturity M = 3y (between 1y floor and 5y cap)
    - src/rwa_calc/data/tables/haircuts.py: COLLATERAL_HAIRCUTS (offending receivables = 0.20 pre-fix)
    - src/rwa_calc/data/tables/firb_lgd.py: FIRB_OVERCOLLATERALISATION_RATIOS (receivables 1.25x)
    - IMPLEMENTATION_PLAN.md: P1.165 entry

Usage:
    uv run python tests/fixtures/p1_165/p1_165.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl
from dateutil.relativedelta import relativedelta

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "CRR-P1165-CP1"
FACILITY_REF = "CRR-P1165-F1"
LOAN_REF = "CRR-P1165-L1"
COLLATERAL_REF = "CRR-P1165-C1"
RATING_REF = "RTG-P1165-001"

# F-IRB model: dedicated model ID for this scenario to avoid cross-contamination
# with shared fixtures.  UK corporate foundation_irb, no geo/book restriction.
MODEL_ID = "UK_CORP_FIRB_P1165"

# Reporting and maturity dates
# M = 3.0y exactly when maturity_date - reporting_date = 3 calendar years.
REPORTING_DATE = date(2026, 6, 30)
MATURITY_DATE = REPORTING_DATE + relativedelta(years=3)  # 2029-06-30 => M ≈ 3.0

RATING_DATE = date(2026, 6, 30)
VALUE_DATE = date(2026, 6, 30)

# Financial parameters
DRAWN_AMOUNT: float = 1_000_000.00
FACILITY_LIMIT: float = 1_000_000.00
COLLATERAL_MARKET_VALUE: float = 800_000.00
COLLATERAL_NOMINAL_VALUE: float = 800_000.00

# CRR F-IRB parameters
PD: float = 0.02  # 2% — well above CRR corporate PD floor (0.03%)

# Art. 230 Foundation Collateral Method parameters (for test-writer reference)
LGDS_SENIOR_RECEIVABLES: float = 0.35  # CRR Art. 230 Table 5 — senior receivables
LGDU_SENIOR_CORPORATE: float = 0.45  # CRR Art. 161(1)(a) — senior corporate non-FSE unsecured
OC_RATIO_RECEIVABLES: float = 1.25  # CRR Art. 230(2), FIRB_OVERCOLLATERALISATION_RATIOS

# CRM-stage expected values (for test-writer reference — post-fix behaviour)
# Pre-fix: Hc = 0.20, value_after_haircut = 800,000 * 0.80 = 640,000
EXPECTED_COLLATERAL_HAIRCUT: float = 0.0  # Art. 224 has no receivables row
EXPECTED_VALUE_AFTER_HAIRCUT: float = 800_000.00
EXPECTED_ADJUSTED_VALUE: float = 800_000.00

EFFECTIVELY_SECURED: float = COLLATERAL_MARKET_VALUE / OC_RATIO_RECEIVABLES  # 640,000.00
UNSECURED_PORTION: float = DRAWN_AMOUNT - EFFECTIVELY_SECURED  # 360,000.00

LGD_STAR: float = (
    LGDS_SENIOR_RECEIVABLES * EFFECTIVELY_SECURED + LGDU_SENIOR_CORPORATE * UNSECURED_PORTION
) / DRAWN_AMOUNT  # = (224,000 + 162,000) / 1,000,000 = 0.386

EXPECTED_LGD_STAR: float = LGD_STAR  # 0.386

# Approximate F-IRB RWA (Art. 153(1) with 1.06 scaling factor, M=3.0, PD=0.02)
# Computed in scenario §8; test-writer should pin to actual engine value once green.
EXPECTED_RWA_APPROX: float = 1_102_548.0  # ± rounding tolerance


# ---------------------------------------------------------------------------
# Private dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.165 counterparty: GB corporate, not defaulted, not a financial sector entity.

    entity_type=corporate routes to IRB CORPORATE class under CalculationConfig.crr().
    is_financial_sector_entity=False: LGDU = 45% (Art. 161(1)(a), non-FSE).
    apply_fi_scalar=False: no 1.25x FI scalar.
    country_code=GB: domestic GBP counterparty.
    default_status=False: performing exposure.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    is_financial_sector_entity: bool
    apply_fi_scalar: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "is_financial_sector_entity": self.is_financial_sector_entity,
            "apply_fi_scalar": self.apply_fi_scalar,
        }


@dataclass(frozen=True)
class _Facility:
    """
    P1.165 facility: GBP 1,000,000 committed term loan facility.

    seniority=senior: senior claim ranking (drives LGDU selection).
    risk_type=funded: on-balance-sheet, fully drawn (CCF not applicable).
    """

    facility_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    limit: float
    committed: bool
    seniority: str
    risk_type: str

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": self.currency,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "limit": self.limit,
            "committed": self.committed,
            "seniority": self.seniority,
            "risk_type": self.risk_type,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.165 loan: GBP 1,000,000 drawn, 3-year residual maturity (M ≈ 3.0).

    drawn_amount=1,000,000: fully drawn → EAD = drawn_amount + interest = 1,000,000.
    interest=0.0: no accrued interest.
    seniority=senior: senior claim → LGDU = 45% (Art. 161(1)(a)) for unsecured portion.
    maturity_date = REPORTING_DATE + 3y → M ≈ 3.0 (between 1y floor and 5y cap, Art. 162).
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
class _Collateral:
    """
    P1.165 collateral: receivables, GBP 800,000 market and nominal value.

    collateral_type=receivables: routes to Art. 230 Foundation Collateral Method.
    is_eligible_financial_collateral=False: receivables are non-financial collateral
        per CRR Art. 199(5) — not eligible for FCSM Art. 223-226.
    is_eligible_irb_collateral=True: eligible as F-IRB non-financial collateral
        per CRR Art. 199(5).
    issuer_cqs=None, issuer_type=None: not applicable for receivables.
    residual_maturity_years=None: no maturity-mismatch in this scenario;
        engine defaults null coll_maturity to 10y >= exposure 3y, factor = 1.0.
    liquidation_period_days=None: defaults to 20-day secured-lending period;
        once Hc = 0 this has no effect.
    currency=GBP: same as exposure → Hfx = 0.
    """

    collateral_reference: str
    collateral_type: str
    currency: str
    market_value: float
    nominal_value: float
    beneficiary_type: str
    beneficiary_reference: str
    is_eligible_financial_collateral: bool
    is_eligible_irb_collateral: bool

    def to_dict(self) -> dict:
        return {
            "collateral_reference": self.collateral_reference,
            "collateral_type": self.collateral_type,
            "currency": self.currency,
            "market_value": self.market_value,
            "nominal_value": self.nominal_value,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "is_eligible_financial_collateral": self.is_eligible_financial_collateral,
            "is_eligible_irb_collateral": self.is_eligible_irb_collateral,
        }


@dataclass(frozen=True)
class _Rating:
    """
    P1.165 internal F-IRB rating row.

    rating_type=internal with pd=0.02 and model_id=MODEL_ID routes the counterparty
    to F-IRB under CalculationConfig.crr() given a matching model_permissions row.
    cqs=None: no external ECAI rating — pure F-IRB internal-rating path.
    """

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    pd: float
    model_id: str
    rating_date: date

    def to_dict(self) -> dict:
        return {
            "rating_reference": self.rating_reference,
            "counterparty_reference": self.counterparty_reference,
            "rating_type": self.rating_type,
            "pd": self.pd,
            "model_id": self.model_id,
            "rating_date": self.rating_date,
        }


@dataclass(frozen=True)
class _ModelPermission:
    """
    P1.165 model permission: corporate foundation_irb, no geo/book restriction.

    A dedicated model_id (UK_CORP_FIRB_P1165) isolates this scenario's F-IRB
    permission from the shared global model_permissions fixture.
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


def create_p1165_counterparty() -> pl.DataFrame:
    """
    Return one P1.165 counterparty row as a DataFrame.

    CRR-P1165-CP1: GB corporate, PD=2%, not defaulted, not a financial sector entity.
    Conforms to COUNTERPARTY_SCHEMA.
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="P1.165 Receivables Collateral Corporate (GB)",
        entity_type="corporate",
        country_code="GB",
        default_status=False,
        is_financial_sector_entity=False,
        apply_fi_scalar=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1165_facility() -> pl.DataFrame:
    """
    Return one P1.165 facility row as a DataFrame.

    CRR-P1165-F1: GBP 1,000,000 committed term loan facility, senior, funded.
    Conforms to FACILITY_SCHEMA.
    """
    row = _Facility(
        facility_reference=FACILITY_REF,
        counterparty_reference=COUNTERPARTY_REF,
        currency="GBP",
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        limit=FACILITY_LIMIT,
        committed=True,
        seniority="senior",
        risk_type="funded",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(FACILITY_SCHEMA))


def create_p1165_loan() -> pl.DataFrame:
    """
    Return one P1.165 loan row as a DataFrame.

    CRR-P1165-L1: GBP 1,000,000 drawn, maturity_date = REPORTING_DATE + 3y → M ≈ 3.0.
    EAD = drawn_amount + interest = 1,000,000 + 0 = 1,000,000.
    Conforms to LOAN_SCHEMA.
    """
    row = _Loan(
        loan_reference=LOAN_REF,
        counterparty_reference=COUNTERPARTY_REF,
        currency="GBP",
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        drawn_amount=DRAWN_AMOUNT,
        interest=0.0,
        seniority="senior",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p1165_collateral() -> pl.DataFrame:
    """
    Return one P1.165 collateral row as a DataFrame.

    CRR-P1165-C1: receivables, GBP 800,000 market/nominal value, beneficiary = loan.
    Key design choices:
    - collateral_type=receivables (in RECEIVABLE_COLLATERAL_TYPES)
    - is_eligible_financial_collateral=False (Art. 199(5): non-financial collateral)
    - is_eligible_irb_collateral=True (Art. 199(5): F-IRB eligible)
    - issuer_cqs=None, issuer_type=None (not applicable for receivables)
    - residual_maturity_years=None (no maturity-mismatch in this scenario)
    - liquidation_period_days=None (Hc=0, so scaling period has no effect)
    Conforms to COLLATERAL_SCHEMA.
    """
    row = _Collateral(
        collateral_reference=COLLATERAL_REF,
        collateral_type="receivables",
        currency="GBP",
        market_value=COLLATERAL_MARKET_VALUE,
        nominal_value=COLLATERAL_NOMINAL_VALUE,
        beneficiary_type="loan",
        beneficiary_reference=LOAN_REF,
        is_eligible_financial_collateral=False,
        is_eligible_irb_collateral=True,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COLLATERAL_SCHEMA))


def create_p1165_rating() -> pl.DataFrame:
    """
    Return one P1.165 internal rating row as a DataFrame.

    RTG-P1165-001: internal, PD=2%, model_id=UK_CORP_FIRB_P1165.
    Routes CRR-P1165-CP1 to F-IRB under CalculationConfig.crr() when paired with
    the matching model_permissions row.
    Conforms to RATINGS_SCHEMA.
    """
    row = _Rating(
        rating_reference=RATING_REF,
        counterparty_reference=COUNTERPARTY_REF,
        rating_type="internal",
        pd=PD,
        model_id=MODEL_ID,
        rating_date=RATING_DATE,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1165_model_permission() -> pl.DataFrame:
    """
    Return one P1.165 model permission row as a DataFrame.

    UK_CORP_FIRB_P1165: corporate, foundation_irb, no geographic/book restriction.
    This standalone permission row is consumed directly by acceptance tests that
    build their own RawDataBundle — it is not injected into the shared
    model_permissions fixture.
    Conforms to MODEL_PERMISSIONS_SCHEMA.
    """
    row = _ModelPermission(
        model_id=MODEL_ID,
        exposure_class="corporate",
        approach="foundation_irb",
        country_codes=None,
        excluded_book_codes=None,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1165_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.165 parquet files and return a mapping of name -> path.

    Five parquet files are written:
    - counterparty.parquet     (1 row: CRR-P1165-CP1)
    - facility.parquet         (1 row: CRR-P1165-F1)
    - loan.parquet             (1 row: CRR-P1165-L1)
    - collateral.parquet       (1 row: CRR-P1165-C1)
    - rating.parquet           (1 row: RTG-P1165-001)
    - model_permission.parquet (1 row: UK_CORP_FIRB_P1165)

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
        ("counterparty", create_p1165_counterparty()),
        ("facility", create_p1165_facility()),
        ("loan", create_p1165_loan()),
        ("collateral", create_p1165_collateral()),
        ("rating", create_p1165_rating()),
        ("model_permission", create_p1165_model_permission()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary with shape/dtype verification."""
    print("P1.165 fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<22} {df.shape[0]:>2} row(s) x {df.shape[1]:>2} cols  ->  {path.name}")
        for col_name, dtype in df.schema.items():
            print(f"    {col_name:<40} {dtype}")
    print("-" * 80)
    print("Scenario: CRR receivables collateral, F-IRB, no Art. 224 volatility haircut")
    print(f"  Counterparty: {COUNTERPARTY_REF}  — corporate, GB, PD={PD:.2%}")
    print(f"  Facility:     {FACILITY_REF}   — GBP {FACILITY_LIMIT:,.0f}, senior, funded")
    print(f"  Loan:         {LOAN_REF}   — GBP {DRAWN_AMOUNT:,.0f} drawn, maturity {MATURITY_DATE}")
    print(f"  Collateral:   {COLLATERAL_REF}   — receivables, GBP {COLLATERAL_MARKET_VALUE:,.0f}")
    print(f"  Rating:       {RATING_REF}  — internal, PD={PD:.2%}, model={MODEL_ID}")
    print(f"  Reporting date: {REPORTING_DATE},  M ≈ 3.0y")
    print()
    print("  Expected CRM outputs (post-fix, Hc=0):")
    print(
        f"    collateral_haircut   = {EXPECTED_COLLATERAL_HAIRCUT}  (Art. 224 has no receivables row)"
    )
    print(f"    value_after_haircut  = {EXPECTED_VALUE_AFTER_HAIRCUT:,.2f}")
    print(f"    adjusted_value       = {EXPECTED_ADJUSTED_VALUE:,.2f}")
    print(f"    effectively_secured  = {EFFECTIVELY_SECURED:,.2f}  (800,000 / 1.25 OC ratio)")
    print(f"    LGD*                 = {LGD_STAR:.3f}  (= {EXPECTED_LGD_STAR:.3%})")
    print(f"    RWA (approx)         = {EXPECTED_RWA_APPROX:,.0f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1165_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
