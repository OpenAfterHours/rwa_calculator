"""
Generate P2.18 fixtures: B31 Art. 226(1) 20-day secured-lending / FX-mismatch / weekly reval.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (crm/haircuts.py)

Key responsibilities:
- Produce one counterparty (CP_B31_REVAL20): unrated corporate, GB.
- Produce one loan (LOAN_B31_REVAL20): is_sft=False drives T_m=20d default.
- Produce one collateral (COLL_B31_REVAL20): USD govt_bond CQS 1, 3-5y maturity,
  pledged to the GBP loan — exercises both the FX haircut path (8% base, scaled to
  20-day) and the Art. 226(1) non-daily revaluation adjustment (N_R=5 weekly).

This is the Basel 3.1 orthogonal corner of P1.101 (CRR corp_bond, 5-day SFT), now
testing:
  - B31 haircut table (govt_bond_cqs1_3_5y = 2.0%, same numeric value but different key)
  - 20-day liquidation period (secured lending, not SFT 5-day)
  - FX mismatch USD/GBP → H_fx fires
  - Weekly revaluation (N_R=5) → Art. 226(1) scaling with T_m=20

Scenario tag: B31-CRM-REVAL-20D-FX

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1()):

    Step 1 — Base 10-day haircuts (B31 Art. 224 Table 1):
        H_c_10d  = 2.0%  (govt_bond_cqs1_3_5y, PRA PS1/26 Art. 224 Table 1)
        H_fx_10d = 8.0%  (FX mismatch, Art. 224 Table 4 / Art. 233, unchanged from CRR)

    Step 2 — Scale to T_m=20 days (Art. 226(2), secured lending):
        H_c_m   = 0.02  × sqrt(20/10) = 0.02  × sqrt(2) = 0.028284271247461903
        H_fx_m  = 0.08  × sqrt(20/10) = 0.08  × sqrt(2) = 0.113137084989847603

    Step 3 — Non-daily revaluation adjustment (Art. 226(1)):
        N_R = 5 (revaluation_frequency_days = 5)
        T_m = 20 (liquidation_period_days — derived from is_sft=False)
        reval_factor = sqrt((N_R + T_m - 1) / T_m)
                     = sqrt((5 + 20 - 1) / 20)
                     = sqrt(24 / 20)
                     = sqrt(1.2)
                     = 1.0954451150103324

        H_c_final  = H_c_m  × reval_factor = 0.028284271247461903 × 1.0954451150103324
                   = 0.030983866769659336
        H_fx_final = H_fx_m × reval_factor = 0.113137084989847603 × 1.0954451150103324
                   = 0.123935467078637344

    Step 4 — Adjusted collateral (Art. 220, FCCM):
        C* = 900,000 × (1 − H_c_final − H_fx_final)
           = 900,000 × (1 − 0.030983866769659336 − 0.123935467078637344)
           = 900,000 × 0.845080666151703320
           = 760,572.599536532988

    Step 5 — EAD (E* = max(0, E − C*)):
        E* = max(0, 1,000,000 − 760,572.599536532988)
           = 239,427.400463467012

    Step 6 — SA risk weight (B31 Art. 122(2) Table 6 unrated, SCRA Grade B → 100%):
        RW = 1.00

    Step 7 — RWA:
        RWA = 239,427.400463467012

    Counterfactual (without Art. 226(1) reval scaling):
        H_c  = H_c_m  = 0.028284271247461903
        H_fx = H_fx_m = 0.113137084989847603
        C* = 900,000 × (1 − 0.141421356237309506) = 777,321.979786621446
        E* = 1,000,000 − 777,321.979786621446    = 222,678.020213378554
        RWA ≈ 222,678.02  (delta vs reval-adjusted: +£16,749.38)

References:
    - PRA PS1/26 Art. 224 Table 1: B31 govt bond CQS 1, 3-5y → H_c = 2.0% (10-day base)
    - PRA PS1/26 Art. 224 Table 4: FX mismatch H_fx = 8.0% (10-day base, unchanged)
    - PRA PS1/26 Art. 224(2)(a): T_m = 20 days for secured lending (is_sft=False)
    - PRA PS1/26 Art. 226(2): H_m = H_10 × sqrt(T_m / 10)
    - PRA PS1/26 Art. 226(1): non-daily revaluation scaling sqrt((N_R + T_m - 1) / T_m)
    - PRA PS1/26 Art. 220: adjusted exposure formula E* = max(0, E − C*(1-Hc-Hfx))
    - PRA PS1/26 Art. 122(2) Table 6: unrated corporate SCRA grade B → 100% SA RW
    - src/rwa_calc/data/tables/haircuts.py: BASEL31_COLLATERAL_HAIRCUTS, FX_HAIRCUT

Usage:
    uv run python tests/fixtures/p2_18/p2_18.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    CONTINGENTS_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    PROVISION_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF: str = "CP_B31_REVAL20"
LOAN_REF: str = "LOAN_B31_REVAL20"
COLLATERAL_REF: str = "COLL_B31_REVAL20"

VALUE_DATE: date = date(2027, 1, 4)
MATURITY_DATE: date = date(2031, 1, 4)

DRAWN_AMOUNT: float = 1_000_000.0
MARKET_VALUE: float = 900_000.0

# ---------------------------------------------------------------------------
# Regulatory constants (B31 Art. 224 Table 1 + Art. 233)
# ---------------------------------------------------------------------------

# 10-day base haircuts (PRA PS1/26 Art. 224 Table 1)
_H_C_10D: float = (
    0.02  # govt_bond CQS 1, 3-5y band — BASEL31_COLLATERAL_HAIRCUTS key: govt_bond_cqs1_3_5y
)
_H_FX_10D: float = 0.08  # FX mismatch haircut (Art. 224 Table 4 / Art. 233, unchanged)

# Liquidation period (Art. 224(2)(a)): is_sft=False → secured lending default
_T_M: int = 20

# Revaluation frequency (Art. 226(1)): weekly → N_R=5 days
_N_R: int = 5

# ---------------------------------------------------------------------------
# Hand-calculated intermediate and final values (single source of truth)
# ---------------------------------------------------------------------------

# Step 2 — Scale to T_m=20d (Art. 226(2))
H_C_SCALED: float = _H_C_10D * math.sqrt(_T_M / 10)  # = 0.028284271247461903
H_FX_SCALED: float = _H_FX_10D * math.sqrt(_T_M / 10)  # = 0.113137084989847603

# Step 3 — Non-daily revaluation factor (Art. 226(1))
REVAL_FACTOR: float = math.sqrt((_N_R + _T_M - 1) / _T_M)  # sqrt(24/20) = sqrt(1.2)

# Step 3 (cont.) — Final adjusted haircuts
H_C_FINAL: float = H_C_SCALED * REVAL_FACTOR  # = 0.030983866769659336
H_FX_FINAL: float = H_FX_SCALED * REVAL_FACTOR  # = 0.123935467078637344

# Step 4 — Adjusted collateral C* = C × (1 − H_c − H_fx)
ADJUSTED_COLLATERAL: float = MARKET_VALUE * (1.0 - H_C_FINAL - H_FX_FINAL)

# Step 5 — EAD E* = max(0, E − C*)
EAD_FINAL: float = max(0.0, DRAWN_AMOUNT - ADJUSTED_COLLATERAL)

# Step 6/7 — SA risk weight and RWA (B31 Art. 122(2) Table 6, unrated corporate → 100%)
SA_RISK_WEIGHT: float = 1.00
RWA_FINAL: float = EAD_FINAL * SA_RISK_WEIGHT

# Counterfactual — without Art. 226(1) reval scaling (daily revaluation assumed)
_COUNTERFACTUAL_C_ADJ: float = MARKET_VALUE * (1.0 - H_C_SCALED - H_FX_SCALED)
EAD_NO_REVAL_SCALING: float = max(0.0, DRAWN_AMOUNT - _COUNTERFACTUAL_C_ADJ)
RWA_NO_REVAL_SCALING: float = EAD_NO_REVAL_SCALING * SA_RISK_WEIGHT


# ---------------------------------------------------------------------------
# Private row builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P2.18 corporate counterparty: unrated, GB, entity_type=corporate.

    Unrated (no external_credit_rating) → SCRA Grade B under B31 Art. 122(2)
    Table 6 → 100% SA risk weight.  annual_revenue=120m → large corporate
    (no SME supporting factor applies under B31 anyway).
    apply_fi_scalar=False: no FIRB 1.25× correlation multiplier.
    is_managed_as_retail=False: routed through corporate class.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float
    total_assets: float
    default_status: bool
    sector_code: str
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
            "sector_code": self.sector_code,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P2.18 loan: GBP 1,000,000 drawn, is_sft=False.

    is_sft=False → engine infers T_m=20 days (Art. 224(2)(a) secured lending).
    product_type=term_loan: standard drawn term loan — on-BS, EAD = drawn + interest.
    seniority=senior: standard senior claim.
    liquidation_period_days=None: engine must derive T_m from is_sft.
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
    is_sft: bool

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
            "is_sft": self.is_sft,
        }


@dataclass(frozen=True)
class _Collateral:
    """
    P2.18 collateral: USD govt_bond CQS 1, 3-5y residual maturity.

    Key load-bearing fields:
        currency="USD" vs exposure "GBP" → H_fx fires (Art. 233)
        collateral_type="govt_bond", issuer_cqs=1, residual_maturity_years=4.5
            → B31 haircut key: govt_bond_cqs1_3_5y = 2.0% (10-day base)
        revaluation_frequency_days=5 → weekly reval, N_R=5 → Art. 226(1) scaling
        liquidation_period_days=None → engine derives T_m=20 from is_sft=False
        original_maturity_years=5.0 → >= 1y (no Art. 237(2) ineligibility cliff)
            The original_maturity_years=5.0 >= exposure maturity 4y → no Art. 238
            maturity mismatch between protection and exposure.
        qualifies_for_zero_haircut=False: Art. 227 zero-haircut exemption does not apply.
        is_eligible_financial_collateral=True: eligible under Art. 197(1)(b) for FCCM.
    """

    collateral_reference: str
    collateral_type: str
    currency: str
    maturity_date: date | None
    market_value: float
    nominal_value: float
    beneficiary_type: str
    beneficiary_reference: str
    issuer_cqs: int
    issuer_type: str
    residual_maturity_years: float
    original_maturity_years: float
    is_eligible_financial_collateral: bool
    is_eligible_irb_collateral: bool
    valuation_date: date
    valuation_type: str
    liquidation_period_days: int | None
    revaluation_frequency_days: int | None
    qualifies_for_zero_haircut: bool

    def to_dict(self) -> dict:
        return {
            "collateral_reference": self.collateral_reference,
            "collateral_type": self.collateral_type,
            "currency": self.currency,
            "maturity_date": self.maturity_date,
            "market_value": self.market_value,
            "nominal_value": self.nominal_value,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "issuer_cqs": self.issuer_cqs,
            "issuer_type": self.issuer_type,
            "residual_maturity_years": self.residual_maturity_years,
            "original_maturity_years": self.original_maturity_years,
            "is_eligible_financial_collateral": self.is_eligible_financial_collateral,
            "is_eligible_irb_collateral": self.is_eligible_irb_collateral,
            "valuation_date": self.valuation_date,
            "valuation_type": self.valuation_type,
            "liquidation_period_days": self.liquidation_period_days,
            "revaluation_frequency_days": self.revaluation_frequency_days,
            "qualifies_for_zero_haircut": self.qualifies_for_zero_haircut,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p218_counterparty() -> pl.DataFrame:
    """
    Return the P2.18 counterparty (unrated corporate, GB) as a DataFrame.

    entity_type=corporate → B31 Art. 122(2) Table 6 SA risk weights.
    Unrated (no CQS rating supplied) → SCRA Grade B default → 100% RW.
    annual_revenue=120m → large corporate (SME supporting factor absent in B31).
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="B31 Reval Test Corp Ltd",
        entity_type="corporate",
        country_code="GB",
        annual_revenue=120_000_000.0,
        total_assets=90_000_000.0,
        default_status=False,
        sector_code="64.19",
        apply_fi_scalar=False,
        is_managed_as_retail=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p218_loan() -> pl.DataFrame:
    """
    Return the P2.18 loan (GBP 1m, is_sft=False) as a DataFrame.

    is_sft=False → engine derives T_m=20d (LIQUIDATION_PERIOD_SECURED_LENDING).
    product_type=term_loan: on-balance-sheet drawn exposure, CCF not applicable.
    lgd=0.45: carry-through field; not load-bearing for this SA scenario.
    """
    row = _Loan(
        loan_reference=LOAN_REF,
        product_type="term_loan",
        book_code="CORP_LENDING",
        counterparty_reference=COUNTERPARTY_REF,
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        currency="GBP",
        drawn_amount=DRAWN_AMOUNT,
        interest=0.0,
        lgd=0.45,
        beel=0.0,
        seniority="senior",
        is_sft=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p218_collateral() -> pl.DataFrame:
    """
    Return the P2.18 collateral row (USD govt_bond CQS 1, 3-5y) as a DataFrame.

    Load-bearing design choices:
    - currency="USD" (vs GBP loan) → H_fx fires (Art. 233 FX mismatch haircut)
    - collateral_type="govt_bond", issuer_cqs=1, residual_maturity_years=4.5
        → B31 haircut key: govt_bond_cqs1_3_5y = 2.0% base (Art. 224 Table 1)
    - revaluation_frequency_days=5 → N_R=5 weekly revaluation → Art. 226(1) scaling
    - liquidation_period_days=None → engine derives T_m=20 from loan.is_sft=False
    - qualifies_for_zero_haircut=False → Art. 227 zero-haircut does not apply
    - original_maturity_years=5.0 → >= 1y (Art. 237(2) ineligibility threshold not hit)
    - valuation_type="market": live mark-to-market valuation
    """
    row = _Collateral(
        collateral_reference=COLLATERAL_REF,
        collateral_type="govt_bond",
        currency="USD",
        maturity_date=None,
        market_value=MARKET_VALUE,
        nominal_value=MARKET_VALUE,
        beneficiary_type="loan",
        beneficiary_reference=LOAN_REF,
        issuer_cqs=1,
        issuer_type="central_government",
        residual_maturity_years=4.5,
        original_maturity_years=5.0,
        is_eligible_financial_collateral=True,
        is_eligible_irb_collateral=True,
        valuation_date=VALUE_DATE,
        valuation_type="market",
        liquidation_period_days=None,
        revaluation_frequency_days=_N_R,
        qualifies_for_zero_haircut=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COLLATERAL_SCHEMA))


def create_p218_empty_facilities() -> pl.DataFrame:
    """Return an empty facilities DataFrame (no facilities in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(FACILITY_SCHEMA))


def create_p218_empty_contingents() -> pl.DataFrame:
    """Return an empty contingents DataFrame (no contingents in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(CONTINGENTS_SCHEMA))


def create_p218_empty_guarantees() -> pl.DataFrame:
    """Return an empty guarantees DataFrame (no guarantees in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(GUARANTEE_SCHEMA))


def create_p218_empty_provisions() -> pl.DataFrame:
    """Return an empty provisions DataFrame (no provisions in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(PROVISION_SCHEMA))


def create_p218_empty_ratings() -> pl.DataFrame:
    """Return an empty ratings DataFrame (unrated counterparty — no CQS row needed)."""
    return pl.DataFrame(schema=dtypes_of(RATINGS_SCHEMA))


def create_p218_empty_model_permissions() -> pl.DataFrame:
    """Return an empty model_permissions DataFrame (SA-only scenario)."""
    return pl.DataFrame(schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Bundle factory (matches test-writer expected API)
# ---------------------------------------------------------------------------


def build_p2_18_bundle(*, fixtures_dir: Path) -> RawDataBundle:
    """
    Build and return a RawDataBundle for the P2.18 scenario.

    The bundle is constructed entirely in-memory from the scenario constants
    defined in this module; the ``fixtures_dir`` argument is accepted for
    interface symmetry with other bundle builders (it is not used here).

    Returns:
        RawDataBundle with:
        - 1 counterparty (CP_B31_REVAL20)
        - 1 loan (LOAN_B31_REVAL20, is_sft=False)
        - 1 collateral (COLL_B31_REVAL20, USD, revaluation_frequency_days=5)
        - All other LazyFrames: empty, schema-conformant

    Args:
        fixtures_dir: Path to the fixtures directory (unused; accepted for
            interface compatibility with other bundle builders).
    """
    counterparty_lf = create_p218_counterparty().lazy()
    loan_lf = create_p218_loan().lazy()
    collateral_lf = create_p218_collateral().lazy()
    facilities_lf = create_p218_empty_facilities().lazy()
    contingents_lf = create_p218_empty_contingents().lazy()
    guarantees_lf = create_p218_empty_guarantees().lazy()
    provisions_lf = create_p218_empty_provisions().lazy()
    ratings_lf = create_p218_empty_ratings().lazy()

    return make_raw_bundle(
        facilities=facilities_lf,
        loans=loan_lf,
        counterparties=counterparty_lf,
        facility_mappings=pl.DataFrame(
            schema={"parent_facility_reference": pl.String, "child_reference": pl.String}
        ).lazy(),
        lending_mappings=pl.DataFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ).lazy(),
        org_mappings=None,
        contingents=contingents_lf,
        collateral=collateral_lf,
        guarantees=guarantees_lf,
        provisions=provisions_lf,
        ratings=ratings_lf,
        specialised_lending=None,
        equity_exposures=None,
        ciu_holdings=None,
        fx_rates=None,
        model_permissions=None,
    )


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p218_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P2.18 parquet files and return a mapping of name -> path.

    Three parquet files are written:
    - counterparty.parquet  (1 row: CP_B31_REVAL20)
    - loan.parquet          (1 row: LOAN_B31_REVAL20, is_sft=False)
    - collateral.parquet    (1 row: COLL_B31_REVAL20, USD, revaluation_frequency_days=5)

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
        ("counterparty", create_p218_counterparty()),
        ("loan", create_p218_loan()),
        ("collateral", create_p218_collateral()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P2.18 fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        cols = len(df.columns)
        print(f"  {name:<20} {len(df):>3} row(s)  {cols:>3} col(s)  ->  {path}")
    print("-" * 80)
    print("Scenario: B31-CRM-REVAL-20D-FX — Art. 226(1) weekly reval + FX mismatch + 20-day SL")
    print()
    print("  Collateral: USD govt_bond, CQS 1, residual 4.5y (3-5y band, B31 Art. 224 Table 1)")
    print(f"  H_c_10d    (base 10-day)  = {_H_C_10D:.4f}  (2.0%,  govt_bond_cqs1_3_5y)")
    print(f"  H_fx_10d   (base 10-day)  = {_H_FX_10D:.4f}  (8.0%,  Art. 224 Table 4)")
    print(f"  T_m        (secured lend) = {_T_M} days  (Art. 224(2)(a), is_sft=False)")
    print(f"  N_R        (reval freq)   = {_N_R} days  (weekly, Art. 226(1))")
    print()
    print(f"  H_c_scaled  (20-day)      = {H_C_SCALED:.15f}")
    print(f"  H_fx_scaled (20-day)      = {H_FX_SCALED:.15f}")
    print(f"  reval_factor sqrt(24/20)  = {REVAL_FACTOR:.15f}")
    print(f"  H_c_final   (reval adj)   = {H_C_FINAL:.15f}")
    print(f"  H_fx_final  (reval adj)   = {H_FX_FINAL:.15f}")
    print()
    print(f"  Adjusted collateral C*    = {ADJUSTED_COLLATERAL:>25.15f}")
    print(f"  EAD = E*                  = {EAD_FINAL:>25.15f}  (EAD_FINAL)")
    print(f"  SA RW (unrated corp B31)  = {SA_RISK_WEIGHT:.0%}")
    print(f"  RWA                       = {RWA_FINAL:>25.15f}  (RWA_FINAL)")
    print()
    print("  Counterfactual (no Art. 226(1) reval scaling — daily assumed):")
    print(f"    EAD_NO_REVAL_SCALING    = {EAD_NO_REVAL_SCALING:>25.15f}")
    print(f"    RWA_NO_REVAL_SCALING    = {RWA_NO_REVAL_SCALING:>25.15f}")
    print(f"    Delta RWA (reval effect)= {RWA_FINAL - RWA_NO_REVAL_SCALING:>+25.15f}")

    # Verify revaluation_frequency_days column is present in collateral parquet
    coll_df = pl.read_parquet(saved["collateral"])
    if "revaluation_frequency_days" in coll_df.columns:
        val = coll_df["revaluation_frequency_days"][0]
        print(f"\n  revaluation_frequency_days present in collateral parquet: {val}")
    else:
        print("\n  WARNING: revaluation_frequency_days column missing from collateral parquet")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p218_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
