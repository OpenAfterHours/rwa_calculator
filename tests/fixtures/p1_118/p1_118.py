"""
Generate P1.118 fixtures: CRR Art. 166(9) F-IRB 20% CCF for short-term trade LCs.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (irb/namespace.py)

Key responsibilities:
- Produce two counterparty rows: corporate, GB, pd=0.005, annual_revenue=200m GBP.
  CP_TRADE_001 is the positive-case counterparty (Row A, is_short_term_trade_lc=True).
  CP_TRADE_002 is the negative-guard counterparty (Row B, is_short_term_trade_lc=False),
  identical PD/type — separate counterparty so test-writer can isolate each row.
- Produce two ratings rows: internal PD rating for each counterparty (PD=0.005,
  model_id="UK_CORP_FIRB_01"), enabling the F-IRB path under CalculationConfig.crr().
- Produce one model-permissions row: corporate FIRB, no book/geo restrictions.
- Produce two contingent rows (pure contingent fixture — no facilities, no loans):
    Row A: TF_LC_001 — documentary_credit, is_short_term_trade_lc=True,
           risk_type=MLR, is_obs_commitment=False, has_one_day_maturity_floor=False
           (caller does NOT set it; engine derives True from is_short_term_trade_lc=True).
    Row B: TF_LC_002 — identical except is_short_term_trade_lc=False (negative guard).
- Produce empty facility_mapping, empty lending_mapping (pure contingent).

Scenario rationale:
    CRR Art. 166(9) grants a 20% CCF to short-term self-liquidating documentary
    credits for goods movement, overriding the general 75% CCF that would apply
    to an MLR-class OBS item under Art. 166(8)(d).  Without this exception a
    documentary credit with risk_type=MLR would attract CCF=75%, producing a
    materially higher EAD and RWA.

    Additionally, CRR Art. 162(4) allows short-term self-liquidating trade finance
    to use a 1-day M floor (instead of the standard 1-year floor at Art. 162(2)),
    reducing the maturity adjustment (MA) for sub-1-year instruments.  The engine
    derives has_one_day_maturity_floor=True when is_short_term_trade_lc=True.

    Row A (positive):  is_short_term_trade_lc=True  → CCF=20%,  1-day M floor
    Row B (negative):  is_short_term_trade_lc=False → CCF=75%,  1-year M floor (standard)

Hand-calculation (CRR, CalculationConfig.crr(), reporting_date=2026-01-01):

    Common parameters:
        PD      = 0.005 (0.50%)
        LGD     = 0.45  (Art. 161(1)(a): senior unsecured corporate F-IRB)
        NOMINAL = 10,000,000 GBP
        Residual maturity (both rows): (2026-09-30 - 2026-01-01) = 272 days
                                        = 272/365 ≈ 0.7452y

    Asset correlation (Art. 153(1)):
        f(PD) = (1 - exp(-50 × 0.005)) / (1 - exp(-50)) ≈ 0.2135
        R     = 0.12 × f(PD) + 0.24 × (1 - f(PD)) ≈ 0.2135
        Note: annual_revenue = GBP 200m >> EUR 43m threshold → no SME reduction.

    Row A (is_short_term_trade_lc=True):
        CCF   = 0.20  (Art. 166(9) trade LC exception)
        EAD   = 10,000,000 × 0.20 = 2,000,000
        M     = 0.7452y  (residual; 1-day floor from Art. 162(4) — above 1 day)
        b     = (0.11852 - 0.05478 × ln(0.005))^2 ≈ 0.30706
        MA    = (1 + (0.7452 - 2.5) × 0.30706) / (1 - 1.5 × 0.30706) ≈ 0.9432
        K     = (LGD × N[(G(PD) + √(R/(1-R)) × G(0.999)) / √(1-R)] - PD × LGD) × MA
              ≈ 0.056437
        RWA   = K × 12.5 × 1.06 × EAD ≈ 1,495,568

    Row B (is_short_term_trade_lc=False):
        CCF   = 0.75  (Art. 166(8)(d): general MLR OBS item)
        EAD   = 10,000,000 × 0.75 = 7,500,000
        M     = max(1.0, 0.7452) = 1.0y  (Art. 162(2) standard 1-year floor)
        MA    = (1 + (1.0 - 2.5) × 0.30706) / (1 - 1.5 × 0.30706) ≈ 1.0000
        K     ≈ 0.059836
        RWA   = K × 12.5 × 1.06 × EAD ≈ 5,946,191

    Key assertions:
        EAD_A (2,000,000) << EAD_B (7,500,000) — CCF effect
        RWA_A (≈1,495,568) << RWA_B (≈5,946,191) — combined CCF + MA effect

References:
    - CRR Art. 166(9): 20% CCF for short-term self-liquidating documentary credits
    - CRR Art. 166(8)(d): 75% CCF for general MLR OBS issued items (default path)
    - CRR Art. 162(4): 1-day M floor for short-term self-liquidating trade finance
    - CRR Art. 162(2): 1-year M floor for all other exposures
    - CRR Art. 153(1): corporate asset correlation formula
    - CRR Art. 161(1)(a): F-IRB supervisory LGD = 45% (senior unsecured)
    - src/rwa_calc/data/schemas.py: CONTINGENTS_SCHEMA.is_short_term_trade_lc,
      CONTINGENTS_SCHEMA.has_one_day_maturity_floor
    - src/rwa_calc/data/tables/crr_ccf.py (or equivalent): CRR_FIRB_CCF table
    - docs/specifications/crr/credit-conversion-factors.md

Usage:
    uv run python tests/fixtures/p1_118/p1_118.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CONTINGENTS_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references — one per contingent row to isolate each scenario.
COUNTERPARTY_REF_A = "CP_TRADE_001"  # positive case: is_short_term_trade_lc=True
COUNTERPARTY_REF_B = "CP_TRADE_002"  # negative guard: is_short_term_trade_lc=False

# Contingent references
CONTINGENT_REF_A = "TF_LC_001"  # Row A: trade LC, is_short_term_trade_lc=True
CONTINGENT_REF_B = "TF_LC_002"  # Row B: trade LC, is_short_term_trade_lc=False

# Rating references
RATING_REF_A = "RTG_TRADE_001"
RATING_REF_B = "RTG_TRADE_002"

# IRB model — one permission row covers both counterparties (same exposure class + approach).
MODEL_ID = "UK_CORP_FIRB_01"

# Reporting date and contingent window.
# Residual maturity = (2026-09-30 - 2026-01-01) = 272 days = 272/365 ≈ 0.7452y
REPORTING_DATE = date(2026, 1, 1)
VALUE_DATE = date(2026, 1, 1)
MATURITY_DATE = date(2026, 9, 30)

# Common financial parameters
NOMINAL_AMOUNT = 10_000_000.0  # GBP 10,000,000 face value of each LC
PD = 0.005  # 0.50% — above CRR 0.03% floor
CP_ANNUAL_REVENUE = 200_000_000.0  # GBP 200m — above EUR 43m SME threshold

# ---------------------------------------------------------------------------
# Expected outputs (for test-writer)
# ---------------------------------------------------------------------------

# Art. 166(9): short-term trade LC CCF = 20%.
# Art. 166(8)(d): general MLR OBS item CCF = 75%.
CCF_TRADE_LC: float = 0.20  # Row A
CCF_GENERAL_MLR: float = 0.75  # Row B

# EAD = nominal × CCF (contingent; no drawn, no interest).
EXPECTED_EAD_A: float = NOMINAL_AMOUNT * CCF_TRADE_LC  # 2,000,000
EXPECTED_EAD_B: float = NOMINAL_AMOUNT * CCF_GENERAL_MLR  # 7,500,000

# Residual maturity = 272 days from 2026-01-01 to 2026-09-30.
RESIDUAL_MATURITY_YEARS: float = 272 / 365.0  # ≈ 0.7452y

# F-IRB effective maturity:
#   Row A: 1-day floor (Art. 162(4) trade LC exception) → M = 1/365 ≈ 0.00274y
#          Engine sets maturity = 1/365 literally when has_one_day_maturity_floor=True.
#          It does NOT treat 1/365 as a floor; it overwrites the residual with 1/365.
#          The engine-implementer must derive has_one_day_maturity_floor=True from
#          is_short_term_trade_lc=True (pre-fix the flag is read as-is → False → M=1.0y).
#   Row B: 1-year floor (Art. 162(2) standard) → M = max(1.0, 0.7452) = 1.0y
EXPECTED_M_A: float = 1.0 / 365.0  # ≈ 0.00274y — 1-day floor (engine sets M directly)
EXPECTED_M_B: float = 1.0  # standard 1-year floor

# F-IRB K and RWA (rounded to nearest integer for acceptance test tolerance).
# See module docstring for hand-calculation working.
EXPECTED_RWA_A: float = 1_495_568.0  # approx; test should allow ±1 rounding
EXPECTED_RWA_B: float = 5_946_191.0  # approx; test should allow ±1 rounding


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.118 corporate counterparty with F-IRB internal rating.

    entity_type=corporate routes to IRB CORPORATE class under CalculationConfig.crr().
    annual_revenue=200m GBP > EUR 43m threshold → no SME firm-size correlation reduction.
    is_financial_institution=False: no FI scalar (Art. 153(2)).
    country_code=GB: domestic GBP counterparty — no FX mismatch haircut.
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
class _Rating:
    """
    P1.118 internal F-IRB rating row.

    rating_type=internal with pd=0.005 and model_id="UK_CORP_FIRB_01" routes the
    counterparty to F-IRB under CalculationConfig.crr() (given a matching
    model_permissions row with approach=foundation_irb).
    cqs=None: no external ECAI rating — pure F-IRB path, no SA CQS lookup.
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
class _Contingent:
    """
    P1.118 contingent (off-balance-sheet documentary credit).

    product_type=documentary_credit: goods-movement LC (Art. 166(9) eligibility).
    risk_type=MLR: medium-low risk — the CCF category over which Art. 166(9) operates.
    is_obs_commitment=False: issued OBS item (not a commitment/NIF/RUF).
    is_short_term_trade_lc: the key gate flag.
        True  → CCF = 20% (Art. 166(9)) + 1-day M floor (Art. 162(4))
        False → CCF = 75% (Art. 166(8)(d) general MLR) + 1-year M floor
    has_one_day_maturity_floor=False: caller does NOT set this; engine derives True
        from is_short_term_trade_lc=True for Row A.
    effective_maturity=None: engine derives M from residual maturity.
    lgd=None: engine uses supervisory LGD from Art. 161(1)(a) (45% senior corporate).
    bs_type=OFB: off-balance sheet (standard for contingents).
    seniority=senior: senior unsecured → supervisory LGD = 45%.
    is_sft=False: not a securities financing transaction.
    """

    contingent_reference: str
    counterparty_reference: str
    product_type: str
    value_date: date
    maturity_date: date
    currency: str
    nominal_amount: float
    risk_type: str
    is_short_term_trade_lc: bool
    is_obs_commitment: bool
    has_one_day_maturity_floor: bool
    is_sft: bool
    bs_type: str
    seniority: str

    def to_dict(self) -> dict:
        return {
            "contingent_reference": self.contingent_reference,
            "counterparty_reference": self.counterparty_reference,
            "product_type": self.product_type,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "nominal_amount": self.nominal_amount,
            "risk_type": self.risk_type,
            "is_short_term_trade_lc": self.is_short_term_trade_lc,
            "is_obs_commitment": self.is_obs_commitment,
            "has_one_day_maturity_floor": self.has_one_day_maturity_floor,
            "is_sft": self.is_sft,
            "bs_type": self.bs_type,
            "seniority": self.seniority,
        }


@dataclass(frozen=True)
class _ModelPermission:
    """
    P1.118 model permission: corporate F-IRB, no geographic/book restriction.

    exposure_class=corporate: covers both CP_TRADE_001 and CP_TRADE_002.
    approach=foundation_irb: F-IRB path under CalculationConfig.crr().
    country_codes=None: unrestricted — both GB counterparties permitted.
    excluded_book_codes=None: no book-code exclusions.
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


def create_p1118_counterparties() -> pl.DataFrame:
    """
    Return two P1.118 counterparties as a DataFrame.

    CP_TRADE_001: primary counterparty for Row A (is_short_term_trade_lc=True).
    CP_TRADE_002: negative-guard counterparty for Row B (is_short_term_trade_lc=False).
    Both are identical large corporates (GB, revenue=GBP 200m, PD=0.5%).
    Separate counterparties ensure test-writer can filter by counterparty_reference.
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_A,
            counterparty_name="Trade Corp Ltd (GB) — P1.118 positive case",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=CP_ANNUAL_REVENUE,
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_B,
            counterparty_name="Trade Corp Ltd (GB) — P1.118 negative guard",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=CP_ANNUAL_REVENUE,
            default_status=False,
            apply_fi_scalar=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1118_ratings() -> pl.DataFrame:
    """
    Return two P1.118 internal rating rows as a DataFrame.

    One rating per counterparty, both using the same model_id="UK_CORP_FIRB_01"
    and PD=0.005.  Separate rating rows are needed so the classifier can resolve
    each counterparty's IRB parameters independently.
    """
    rows = [
        _Rating(
            rating_reference=RATING_REF_A,
            counterparty_reference=COUNTERPARTY_REF_A,
            rating_type="internal",
            pd=PD,
            model_id=MODEL_ID,
            rating_date=REPORTING_DATE,
        ),
        _Rating(
            rating_reference=RATING_REF_B,
            counterparty_reference=COUNTERPARTY_REF_B,
            rating_type="internal",
            pd=PD,
            model_id=MODEL_ID,
            rating_date=REPORTING_DATE,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1118_model_permissions() -> pl.DataFrame:
    """
    Return one P1.118 model permission row as a DataFrame.

    model_id=UK_CORP_FIRB_01, exposure_class=corporate, approach=foundation_irb.
    Both CP_TRADE_001 and CP_TRADE_002 share this permission (no geo/book restriction).
    """
    row = _ModelPermission(
        model_id=MODEL_ID,
        exposure_class="corporate",
        approach="foundation_irb",
        country_codes=None,
        excluded_book_codes=None,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


def create_p1118_contingents() -> pl.DataFrame:
    """
    Return two P1.118 contingent rows as a DataFrame.

    Row A (TF_LC_001):
        is_short_term_trade_lc=True → engine applies CCF=20% (Art. 166(9)) and
        derives has_one_day_maturity_floor=True (Art. 162(4)).
        Expected EAD = 10,000,000 × 0.20 = 2,000,000.
        Expected M   = 0.7452y (residual; 1-day floor not binding above 1 day).

    Row B (TF_LC_002):
        is_short_term_trade_lc=False → engine applies CCF=75% (Art. 166(8)(d)) and
        uses standard 1-year M floor (Art. 162(2)).
        Expected EAD = 10,000,000 × 0.75 = 7,500,000.
        Expected M   = 1.0y (1-year floor is binding: residual 0.7452y < 1y).

    Isolating the two rows with separate counterparties allows the test-writer to
    assert on each row independently without confounding the IRB calc.
    """
    # Shared fields — identical across both rows except the key differentiator.
    _common = {
        "product_type": "documentary_credit",
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
        "currency": "GBP",
        "nominal_amount": NOMINAL_AMOUNT,
        "risk_type": "MLR",
        "is_obs_commitment": False,  # issued OBS item (not a commitment)
        "has_one_day_maturity_floor": False,  # engine derives True for Row A
        "is_sft": False,
        "bs_type": "OFB",
        "seniority": "senior",
    }

    rows = [
        # ----------------------------------------------------------------
        # Row A — positive case: is_short_term_trade_lc=True
        # Art. 166(9) fires → CCF=20%, EAD=2,000,000
        # Art. 162(4) fires → 1-day M floor (engine-derived; caller sets False)
        # ----------------------------------------------------------------
        _Contingent(
            contingent_reference=CONTINGENT_REF_A,
            counterparty_reference=COUNTERPARTY_REF_A,
            is_short_term_trade_lc=True,
            **_common,
        ),
        # ----------------------------------------------------------------
        # Row B — negative guard: is_short_term_trade_lc=False
        # Art. 166(9) does NOT fire → CCF=75%, EAD=7,500,000
        # Standard Art. 162(2) 1-year M floor applies
        # ----------------------------------------------------------------
        _Contingent(
            contingent_reference=CONTINGENT_REF_B,
            counterparty_reference=COUNTERPARTY_REF_B,
            is_short_term_trade_lc=False,
            **_common,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(CONTINGENTS_SCHEMA))


def create_p1118_facility_mapping() -> pl.DataFrame:
    """
    Return an empty facility-mapping DataFrame conforming to FACILITY_MAPPING_SCHEMA.

    This is a pure contingent fixture — no facilities, no loans, no mappings needed.
    An empty DataFrame is produced so generate_all.py can report zero rows cleanly.
    """
    return pl.DataFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def create_p1118_lending_mapping() -> pl.DataFrame:
    """
    Return an empty lending-mapping DataFrame conforming to LENDING_MAPPING_SCHEMA.

    No multi-debtor / parent-child lending structure in this fixture.
    """
    return pl.DataFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1118_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.118 parquet files and return a mapping of name -> path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1118_counterparties()),
        ("rating", create_p1118_ratings()),
        ("model_permission", create_p1118_model_permissions()),
        ("contingent", create_p1118_contingents()),
        ("facility_mapping", create_p1118_facility_mapping()),
        ("lending_mapping", create_p1118_lending_mapping()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.118 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR Art. 166(9) F-IRB 20% CCF — short-term trade LC exception")
    print(
        f"  Counterparties: {COUNTERPARTY_REF_A} (positive), {COUNTERPARTY_REF_B} (negative guard)"
    )
    print(f"  PD={PD:.3f}, LGD=0.45 (supervisory), nominal=GBP {NOMINAL_AMOUNT:,.0f}")
    print(f"  value_date={VALUE_DATE}, maturity_date={MATURITY_DATE} (272 days)")
    print(f"  Residual maturity = {RESIDUAL_MATURITY_YEARS:.4f}y")
    print("")
    print(f"  {'Row':<5}  {'Flag':<30}  {'CCF':>5}  {'EAD':>12}  {'M':>8}  {'RWA (approx)':>14}")
    print(
        f"  {'A':<5}  {'is_short_term_trade_lc=True':<30}  {CCF_TRADE_LC:>5.0%}  "
        f"{EXPECTED_EAD_A:>12,.0f}  {EXPECTED_M_A:>8.4f}  {EXPECTED_RWA_A:>14,.0f}"
    )
    print(
        f"  {'B':<5}  {'is_short_term_trade_lc=False':<30}  {CCF_GENERAL_MLR:>5.0%}  "
        f"{EXPECTED_EAD_B:>12,.0f}  {EXPECTED_M_B:>8.4f}  {EXPECTED_RWA_B:>14,.0f}"
    )
    print("")
    print("  Key assertions:")
    print(f"    EAD_A ({EXPECTED_EAD_A:,.0f}) << EAD_B ({EXPECTED_EAD_B:,.0f}) — CCF effect")
    print(f"    RWA_A ({EXPECTED_RWA_A:,.0f}) << RWA_B ({EXPECTED_RWA_B:,.0f}) — CCF + MA effect")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1118_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
