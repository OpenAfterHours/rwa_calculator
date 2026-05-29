"""
Generate P1.139 fixtures: Basel 3.1 CIU look-through with transitional floor (Rules 4.7-4.8).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (equity/calculator.py)

Key responsibilities:
- Produce one CIU wrapper equity-exposure row (equity_type="ciu", ciu_approach="look_through").
- Produce two CIU holdings rows against the same fund:
    H1-EQ : exposure_class="EQUITY",    cqs=null,  holding_value=600,000
    H2-CORP: exposure_class="CORPORATE", cqs=3,     holding_value=400,000
- Produce one counterparty row (fund vehicle, entity_type="corporate").
- No facilities, loans, collateral, guarantees — equity path only.

Scenario rationale (PRA PS1/26 Rules 4.7-4.8, CRR Art. 155(2)):

  The firm had IRB equity permission as of 31 Dec 2026 (Rule 4.7 scope gate).
  reporting_date = 2027-06-30: Rule 4.2 standard band = 160% for calendar year 2027.

  Buggy behaviour (pre-fix):
    _apply_transitional_floor zeroes the transitional floor for CIU look_through /
    mandate_based exposures — both the wrapper AND its EQUITY underlyings.
    The equity holding (exposure_class="EQUITY", cqs=null) falls through to
    _DEFAULT_HOLDING_RW = 1.00 (100%). Combined RW = 1.00, RWA = 1,000,000.

  Fixed behaviour (post-fix):
    Each EQUITY underlying inside the look-through gets max(Art.155(2) simple RW,
    Rule 4.2/4.3 transitional floor). The wrapper itself is NOT floored (Rule 4.7
    derogation to Art. 132A).

  Hand-calculation (B31, reporting_date=2027-06-30):

    H1-EQ (EQUITY, null CQS):
      Art. 155(2) IRB simple RW for "other" equity = 370% (IRB_SIMPLE_EQUITY_RISK_WEIGHTS)
      Rule 4.2 standard band 2027 = 160%
      higher-of = max(3.70, 1.60) = 3.70  → holding_rw = 3.70

    H2-CORP (CORPORATE, CQS 3):
      B31 corporate CQS 3 SA RW = 75% (B31_CORPORATE_RISK_WEIGHTS[3] = Decimal("0.75"))
      corporate holdings are NOT equity → no Art. 155(2) / Rule 4.2 floor applied
      holding_rw = 0.75

    Aggregate (fund_nav = 1,000,000):
      weighted_sum = 600,000 × 3.70 + 400,000 × 0.75
                   = 2,220,000 + 300,000
                   = 2,520,000
      ciu_look_through_rw = 2,520,000 / 1,000,000 = 2.52
      RWA = 1,000,000 × 2.52 = 2,520,000

  Note — deviation from proposal golden:
    The proposal assumed RW_corp = 1.00 (100%), yielding RWA = 2,620,000.
    Actual B31 corporate CQS 3 RW = 75% (B31_CORPORATE_RISK_WEIGHTS[3]).
    Correct golden: RWA = 2,520,000.  Test-writer must use EXPECTED_RWA not the
    proposal's 2,620,000.

  Buggy golden (pre-fix, for regression assertion):
    H1-EQ gets _DEFAULT_HOLDING_RW = 1.00 (no equity higher-of applied).
    weighted_sum_buggy = 600,000 × 1.00 + 400,000 × 0.75 = 900,000
    ciu_look_through_rw_buggy = 900,000 / 1,000,000 = 0.90
    RWA_buggy = 1,000,000 × 0.90 = 900,000
    (If the _DEFAULT_HOLDING_RW fallback is 1.00 and not the transitional floor,
     the understatement vs fixed is 2,520,000 - 900,000 = 1,620,000.)

Config:
    CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))
    had_irb_permission_2026=True (Rule 4.7 scope gate — firm had IRB equity permission)
    opted_out=False  (firm has not opted out of the transitional — floor applies)
    permission_mode=PermissionMode.STANDARDISED  (equity is SA-only under B31)

References:
    - PRA PS1/26 Rule 4.7: transitional floor applies to equity held under
      Art. 155(2) IRB simple method when firm had IRB equity permission on 31 Dec 2026.
    - PRA PS1/26 Rule 4.8: higher-of(Art.155(2) simple RW, Rule 4.2/4.3 transitional).
    - PRA PS1/26 Rule 4.2: 2027 standard band = 160%, 2028 = 200%, 2029 = 250%, 2030+ = none.
    - CRR Art. 155(2): IRB simple method equity risk weights (other = 370%).
    - PRA PS1/26 Art. 132A / B31 Art. 132a: CIU look-through — wrapper not floored.
    - src/rwa_calc/data/tables/crr_equity_rw.py: IRB_SIMPLE_EQUITY_RISK_WEIGHTS (OTHER=3.70)
    - src/rwa_calc/data/tables/b31_risk_weights.py: B31_CORPORATE_RISK_WEIGHTS (CQS3=0.75)
    - src/rwa_calc/engine/equity/calculator.py: _resolve_look_through_rw, _apply_transitional_floor

Usage:
    /home/philm/projects/rwa_calculator/.venv/bin/python tests/fixtures/p1_139/p1_139.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CIU_HOLDINGS_SCHEMA,
    COUNTERPARTY_SCHEMA,
    EQUITY_EXPOSURE_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty reference (the CIU fund vehicle)
COUNTERPARTY_REF: str = "CP_CIU_P1139"

# Wrapper exposure (the look-through CIU)
EXPOSURE_REF: str = "CIU-P1139-LT"

# Fund identifier — links wrapper exposure to its holdings
FUND_REFERENCE: str = "FUND-P1139"

# Holding references
HOLDING_REF_EQ: str = "H1-EQ"    # EQUITY holding, null CQS
HOLDING_REF_CORP: str = "H2-CORP"  # CORPORATE holding, CQS 3

# Monetary values
FUND_NAV: float = 1_000_000.0
EXPOSURE_VALUE: float = 1_000_000.0  # EAD / carrying_value = NAV
HOLDING_VALUE_EQ: float = 600_000.0
HOLDING_VALUE_CORP: float = 400_000.0

# CQS for CORPORATE holding (CQS 3 = 75% under B31 Art. 122(2) Table 6)
CQS_CORP: int = 3

# ---------------------------------------------------------------------------
# Expected outputs (authoritative — test-writer must assert these)
# ---------------------------------------------------------------------------

#: B31 corporate CQS 3 risk weight (Art. 122(2) Table 6)
#: = 75% (was 100% under CRR; B31 reduced CQS 3 to 75%)
CORPORATE_CQS3_RW: float = 0.75

#: CRR Art. 155(2) IRB simple RW for "other" equity = 370%
#: Source: IRB_SIMPLE_EQUITY_RISK_WEIGHTS[EquityType.OTHER] = Decimal("3.70")
IRB_SIMPLE_RW_EQUITY_OTHER: float = 3.70

#: Rule 4.2 transitional standard band for 2027 (reporting_date=2027-06-30)
TRANSITIONAL_STANDARD_BAND_2027: float = 1.60  # 160%

#: higher-of for H1-EQ: max(3.70, 1.60) = 3.70
EXPECTED_HOLDING_RW_EQ: float = 3.70

#: H2-CORP holding RW (no equity floor — corporate, not equity)
EXPECTED_HOLDING_RW_CORP: float = CORPORATE_CQS3_RW  # 0.75

#: Weighted sum: 600,000 × 3.70 + 400,000 × 0.75
EXPECTED_WEIGHTED_SUM: float = (
    HOLDING_VALUE_EQ * EXPECTED_HOLDING_RW_EQ
    + HOLDING_VALUE_CORP * EXPECTED_HOLDING_RW_CORP
)  # 2_220_000 + 300_000 = 2_520_000

#: ciu_look_through_rw = weighted_sum / fund_nav
EXPECTED_CIU_LT_RW: float = EXPECTED_WEIGHTED_SUM / FUND_NAV  # 2.52

#: RWA = NAV × ciu_look_through_rw
EXPECTED_RWA: float = EXPOSURE_VALUE * EXPECTED_CIU_LT_RW  # 2_520_000


# ---------------------------------------------------------------------------
# Minimal frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """Fund vehicle counterparty for P1.139."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
        }


@dataclass(frozen=True)
class _EquityExposure:
    """
    CIU wrapper equity-exposure row.

    equity_type="ciu": routes through the CIU branch in the equity calculator.
    ciu_approach="look_through": triggers _resolve_look_through_rw aggregation.
    fund_reference links to the CIU_HOLDINGS rows.
    fund_nav=1,000,000 is the denominator for the weighted-average RW.
    carrying_value=fair_value=1,000,000: EAD basis for RWA calculation.
    currency="GBP": the wrapper is denominated in GBP.
    """

    exposure_reference: str
    counterparty_reference: str
    equity_type: str
    currency: str
    carrying_value: float
    fair_value: float
    ciu_approach: str
    fund_reference: str
    fund_nav: float

    def to_dict(self) -> dict:
        return {
            "exposure_reference": self.exposure_reference,
            "counterparty_reference": self.counterparty_reference,
            "equity_type": self.equity_type,
            "currency": self.currency,
            "carrying_value": self.carrying_value,
            "fair_value": self.fair_value,
            "ciu_approach": self.ciu_approach,
            "fund_reference": self.fund_reference,
            "fund_nav": self.fund_nav,
        }


@dataclass(frozen=True)
class _CiuHolding:
    """
    CIU fund holding row (CIU_HOLDINGS_SCHEMA).

    fund_reference links this holding to the wrapper exposure.
    exposure_class: "EQUITY" or "CORPORATE" — used for CQS-based RW lookup.
    cqs: null for EQUITY (no CQS applies to equity holdings), 3 for CORPORATE.
    holding_value: the market value of this underlying position.
    """

    fund_reference: str
    holding_reference: str
    exposure_class: str
    cqs: int | None
    holding_value: float

    def to_dict(self) -> dict:
        return {
            "fund_reference": self.fund_reference,
            "holding_reference": self.holding_reference,
            "exposure_class": self.exposure_class,
            "cqs": self.cqs,
            "holding_value": self.holding_value,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1139_counterparty() -> pl.DataFrame:
    """
    Return the P1.139 counterparty as a single-row DataFrame.

    One CIU fund vehicle counterparty.  entity_type="corporate" — equity
    exposures link to the counterparty by counterparty_reference; the
    entity type does not itself affect the equity RW path.

    apply_fi_scalar=False: no FSE scalar.
    is_managed_as_retail=False: fund vehicle is not retail.
    default_status=False: performing.
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF,
            counterparty_name="P1.139 CIU Fund Vehicle Ltd",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1139_equity_exposure() -> pl.DataFrame:
    """
    Return the P1.139 CIU wrapper equity-exposure as a single-row DataFrame.

    One row: CIU-P1139-LT — a look-through CIU wrapping FUND-P1139.

    Columns set:
      equity_type="ciu"                  Routes to CIU branch in calculator.
      ciu_approach="look_through"        Triggers _resolve_look_through_rw.
      fund_reference="FUND-P1139"        Links to CIU holdings.
      fund_nav=1,000,000                 Denominator for weighted-avg RW (Art. 132a(3)).
      carrying_value=fair_value=1,000,000 EAD basis.
      currency="GBP"

    Columns intentionally left at schema defaults (null/False):
      is_speculative, is_exchange_traded, is_government_supported,
      is_significant_investment, ciu_mandate_rw, ciu_third_party_calc,
      business_age_years — none of these apply to a CIU look-through wrapper.
    """
    rows = [
        _EquityExposure(
            exposure_reference=EXPOSURE_REF,
            counterparty_reference=COUNTERPARTY_REF,
            equity_type="ciu",
            currency="GBP",
            carrying_value=EXPOSURE_VALUE,
            fair_value=EXPOSURE_VALUE,
            ciu_approach="look_through",
            fund_reference=FUND_REFERENCE,
            fund_nav=FUND_NAV,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(EQUITY_EXPOSURE_SCHEMA))


def create_p1139_ciu_holdings() -> pl.DataFrame:
    """
    Return the P1.139 CIU holdings as a two-row DataFrame.

    Both rows share fund_reference="FUND-P1139" to link back to the wrapper.

    Row 1 — H1-EQ (EQUITY holding):
      exposure_class="EQUITY": routes to equity-class RW lookup.
      cqs=null: equity has no ECAI CQS → lookup misses → _DEFAULT_HOLDING_RW=1.00
        (buggy) OR higher-of(Art.155(2)=370%, Rule 4.2 band=160%) (fixed).
      holding_value=600,000: GBP 600k of equity within the fund.

    Row 2 — H2-CORP (CORPORATE holding):
      exposure_class="CORPORATE": routes to corporate CQS-based RW lookup.
      cqs=3: B31 corporate CQS 3 = 75% (Art. 122(2) Table 6).
      holding_value=400,000: GBP 400k of corporate bonds within the fund.

    Schema: CIU_HOLDINGS_SCHEMA (fund_reference, holding_reference,
            exposure_class, cqs [Int8, nullable], holding_value [Float64]).
    """
    rows = [
        # ===================================================================
        # H1-EQ: equity holding — the load-bearing row for the higher-of fix.
        # Under the bug: holding_rw = 1.00 (100% default).
        # Post-fix: holding_rw = max(3.70, 1.60) = 3.70 (370%).
        # ===================================================================
        _CiuHolding(
            fund_reference=FUND_REFERENCE,
            holding_reference=HOLDING_REF_EQ,
            exposure_class="EQUITY",
            cqs=None,  # null — equity has no ECAI CQS grade
            holding_value=HOLDING_VALUE_EQ,  # GBP 600,000
        ),
        # ===================================================================
        # H2-CORP: corporate bond holding — B31 CQS-3 RW applies.
        # holding_rw = 0.75 (75%, B31 Art. 122(2) Table 6 CQS 3).
        # No Art. 155(2) floor — corporate is not equity.
        # ===================================================================
        _CiuHolding(
            fund_reference=FUND_REFERENCE,
            holding_reference=HOLDING_REF_CORP,
            exposure_class="CORPORATE",
            cqs=CQS_CORP,  # 3 → 75% B31 corporate RW
            holding_value=HOLDING_VALUE_CORP,  # GBP 400,000
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(CIU_HOLDINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1139_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.139 parquet files and return a mapping of name to path.

    Files written:
        counterparty.parquet      — 1 row  (CP_CIU_P1139)
        equity_exposure.parquet   — 1 row  (CIU-P1139-LT, look_through wrapper)
        ciu_holding.parquet       — 2 rows (H1-EQ, H2-CORP)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1139_counterparty()),
        ("equity_exposure", create_p1139_equity_exposure()),
        ("ciu_holding", create_p1139_ciu_holdings()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.139 fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 80)
    print("Scenario: CIU look-through equity transitional floor (Rules 4.7-4.8 higher-of)")
    print(f"  Fund: {FUND_REFERENCE}, NAV = {FUND_NAV:,.0f}")
    print(f"  H1-EQ  (EQUITY,    CQS=null, value={HOLDING_VALUE_EQ:,.0f}): holding_rw={EXPECTED_HOLDING_RW_EQ:.2f}")
    print(f"  H2-CORP(CORPORATE, CQS=3,    value={HOLDING_VALUE_CORP:,.0f}): holding_rw={EXPECTED_HOLDING_RW_CORP:.2f}")
    print(f"  weighted_sum = {EXPECTED_WEIGHTED_SUM:,.0f}")
    print(f"  ciu_look_through_rw = {EXPECTED_CIU_LT_RW:.4f}")
    print(f"  EXPECTED_RWA = {EXPECTED_RWA:,.0f}")
    print()
    print("  Note: corporate CQS-3 RW = 75% (B31 Art.122(2) Table 6), not 100%.")
    print("  The proposal's golden of 2,620,000 assumed RW_corp=1.00 — corrected to 2,520,000.")
    print()
    print("  Key constants:")
    print(f"    IRB_SIMPLE_RW_EQUITY_OTHER    = {IRB_SIMPLE_RW_EQUITY_OTHER:.2f} (Art. 155(2) other)")
    print(f"    TRANSITIONAL_STANDARD_BAND_2027 = {TRANSITIONAL_STANDARD_BAND_2027:.2f} (Rule 4.2 2027)")
    print(f"    CORPORATE_CQS3_RW             = {CORPORATE_CQS3_RW:.2f} (B31 Art. 122(2) Table 6)")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1139_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
