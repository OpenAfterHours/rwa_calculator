"""
Generate P2.15 fixtures: equity transitional irrevocable opt-out (PRA Rules 4.9-4.10).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (equity/calculator.py,
    contracts/config.py: EquityTransitionalConfig.opted_out)

Key responsibilities:
- Produce two equity-exposure rows + one CIU holdings row:
    EQ-OPTOUT-CIU-001 : CIU look-through wrapper, fund_nav=1,000,000,
                         single EQUITY underlying (null CQS, holding_value=1,000,000).
    EQ-CONTROL-001    : Direct LISTED equity, is_exchange_traded=True,
                         business_age_years=10, is_speculative=False.
- Produce two counterparty rows (one per exposure).
- The opt_out knob is a CONFIG field (EquityTransitionalConfig.opted_out), NOT a
  fixture column.  The test-writer runs both exposures through two configs:
    Config A — opted_out=False : higher-of path active for EQ-OPTOUT-CIU-001
    Config B — opted_out=True  : higher-of suppressed for EQ-OPTOUT-CIU-001

Scenario rationale (PRA PS1/26 Rules 4.9-4.10, CRR Art. 155(2)):

  reporting_date = 2027-06-30: Rule 4.2 standard band = 160% for calendar year 2027.
  Firm had IRB equity permission on 31 Dec 2026 (Rule 4.7 scope gate).

  EQ-OPTOUT-CIU-001 (load-bearing — CIU look-through):
    The single equity holding has exposure_class="EQUITY" and cqs=null.
    Under the shipped _equity_holding_higher_of_rw path (Rule 4.8):
      holding_rw = max(Art.155(2) "other" = 3.70, Rule 4.2 2027 = 1.60) = 3.70
    ciu_look_through_rw = (1,000,000 x 3.70) / 1,000,000 = 3.70
    risk_weight (wrapper) = 3.70  (routed via CIU look-through branch in calculator)
    RWA = 1,000,000 x 3.70 = 3,700,000  (opted_out=False)

    When opted_out=True, _equity_holding_higher_of_rw returns None:
      holding_rw falls back to _DEFAULT_HOLDING_RW = 1.00
    ciu_look_through_rw = (1,000,000 x 1.00) / 1,000,000 = 1.00
    risk_weight (wrapper) = 1.00
    RWA = 1,000,000 x 1.00 = 1,000,000  (opted_out=True)

  EQ-CONTROL-001 (control — direct LISTED equity):
    B31 Art. 133(3): standard equity → 250% (2.50)
    _apply_transitional_floor: max(2.50, 1.60 [Rule 4.2 2027]) = 2.50 (end-state wins)
    RWA = 1,000,000 x 2.50 = 2,500,000  under BOTH configs (opted_out flag irrelevant)

    Note: is_exchange_traded=True, business_age_years=10 — NOT higher-risk (Art. 133(4)).
    is_speculative=False.  These flags ensure the control stays on the standard 250% path.
    The transitional floor for direct LISTED equity (2.50) exceeds the 2027 band (1.60)
    so the floor does not bind and the RWA is 2,500,000 regardless of opted_out.

Hand-calculation (reporting_date=2027-06-30):

  opted_out=False:
    EQ-OPTOUT-CIU-001: ciu_look_through_rw=3.70 → RWA=3,700,000
    EQ-CONTROL-001:    risk_weight=2.50          → RWA=2,500,000

  opted_out=True:
    EQ-OPTOUT-CIU-001: ciu_look_through_rw=1.00 → RWA=1,000,000
    EQ-CONTROL-001:    risk_weight=2.50          → RWA=2,500,000  (unchanged)

Config:
    CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))
    equity_transitional = EquityTransitionalConfig.basel_3_1()  (enabled=True)
    opted_out field: False (Config A) / True (Config B) — new field on EquityTransitionalConfig

References:
    - PRA PS1/26 Rule 4.9: irrevocable opt-out from the equity transitional regime.
    - PRA PS1/26 Rule 4.10: when opted out, the higher-of(Art.155(2), transitional) path
      is suppressed — holdings revert to _DEFAULT_HOLDING_RW (100%).
    - PRA PS1/26 Rule 4.8: higher-of(Art.155(2) simple RW, Rule 4.2/4.3 transitional band).
    - PRA PS1/26 Rule 4.2: 2027 standard band = 160%.
    - CRR Art. 155(2): IRB simple method "other" equity RW = 370%.
    - PRA PS1/26 Art. 132a / Art. 133(3): CIU look-through; standard equity = 250%.
    - src/rwa_calc/engine/equity/calculator.py: _equity_holding_higher_of_rw,
      _resolve_look_through_rw, _apply_transitional_floor
    - src/rwa_calc/contracts/config.py: EquityTransitionalConfig

Usage:
    cd /home/philm/projects/rwa_calculator/tmp/worktrees/P2.15 && \\
    PYTHONPATH=/home/philm/projects/rwa_calculator/tmp/worktrees/P2.15/src \\
    /home/philm/projects/rwa_calculator/.venv/bin/python \\
    tests/fixtures/p2_15/p2_15.py
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

# Counterparty references
CP_CIU_OPTOUT: str = "CP-EQ-OPTOUT-P215"
CP_CONTROL: str = "CP-EQ-CTRL-P215"

# Exposure references
EXPOSURE_REF_CIU: str = "EQ-OPTOUT-CIU-001"
EXPOSURE_REF_CONTROL: str = "EQ-CONTROL-001"

# Fund identifier — links CIU wrapper to its single equity holding
FUND_REFERENCE: str = "FUND-P215-OPTOUT"

# Holding reference
HOLDING_REF_EQ: str = "H1-EQ-P215"

# Monetary values
EAD: float = 1_000_000.0
FUND_NAV: float = 1_000_000.0
HOLDING_VALUE_EQ: float = 1_000_000.0

# ---------------------------------------------------------------------------
# Expected outputs — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

#: CRR Art. 155(2) IRB simple RW for "other" equity = 370%
#: Source: IRB_SIMPLE_EQUITY_RISK_WEIGHTS[EquityType.OTHER] = Decimal("3.70")
IRB_SIMPLE_RW_EQUITY_OTHER: float = 3.70

#: Rule 4.2 transitional standard band for 2027 (reporting_date=2027-06-30)
TRANSITIONAL_STANDARD_BAND_2027: float = 1.60  # 160%

#: _DEFAULT_HOLDING_RW used when higher-of is suppressed (opted_out=True)
DEFAULT_HOLDING_RW: float = 1.00  # 100%

# --- opted_out=False (higher-of active) ---

#: higher-of: max(IRB_SIMPLE_RW_EQUITY_OTHER=3.70, transitional=1.60) = 3.70
EXPECTED_HOLDING_RW_OPT_OUT_FALSE: float = max(
    IRB_SIMPLE_RW_EQUITY_OTHER, TRANSITIONAL_STANDARD_BAND_2027
)
# = 3.70

#: CIU look-through RW (single equity holding): weighted_sum / fund_nav
#: = (1,000,000 x 3.70) / 1,000,000 = 3.70
EXPECTED_CIU_LT_RW_OPT_OUT_FALSE: float = (
    HOLDING_VALUE_EQ * EXPECTED_HOLDING_RW_OPT_OUT_FALSE
) / FUND_NAV
# = 3.70

#: RWA = EAD x ciu_look_through_rw
EXPECTED_RWA_CIU_OPT_OUT_FALSE: float = EAD * EXPECTED_CIU_LT_RW_OPT_OUT_FALSE
# = 3,700,000

# --- opted_out=True (higher-of suppressed) ---

#: Holding RW reverts to _DEFAULT_HOLDING_RW = 1.00
EXPECTED_HOLDING_RW_OPT_OUT_TRUE: float = DEFAULT_HOLDING_RW
# = 1.00

#: CIU look-through RW (single equity holding):
#: = (1,000,000 x 1.00) / 1,000,000 = 1.00
EXPECTED_CIU_LT_RW_OPT_OUT_TRUE: float = (
    HOLDING_VALUE_EQ * EXPECTED_HOLDING_RW_OPT_OUT_TRUE
) / FUND_NAV
# = 1.00

#: RWA = EAD x ciu_look_through_rw
EXPECTED_RWA_CIU_OPT_OUT_TRUE: float = EAD * EXPECTED_CIU_LT_RW_OPT_OUT_TRUE
# = 1,000,000

# --- control exposure (both configs) ---

#: B31 Art. 133(3): standard LISTED equity = 250%
#: Transitional floor 2027 = 160% < 250% end-state → floor does not bind.
#: Both opted_out configs produce the same 250% result.
EXPECTED_RW_CONTROL: float = 2.50

#: RWA = EAD x risk_weight
EXPECTED_RWA_CONTROL: float = EAD * EXPECTED_RW_CONTROL
# = 2,500,000


# ---------------------------------------------------------------------------
# Minimal frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P2.15 counterparty row."""

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
    """P2.15 equity exposure row (CIU wrapper or direct listed equity)."""

    exposure_reference: str
    counterparty_reference: str
    equity_type: str
    currency: str
    carrying_value: float
    fair_value: float
    is_speculative: bool
    is_exchange_traded: bool
    is_government_supported: bool
    is_significant_investment: bool
    ciu_approach: str | None
    fund_reference: str | None
    fund_nav: float | None
    business_age_years: float | None

    def to_dict(self) -> dict:
        return {
            "exposure_reference": self.exposure_reference,
            "counterparty_reference": self.counterparty_reference,
            "equity_type": self.equity_type,
            "currency": self.currency,
            "carrying_value": self.carrying_value,
            "fair_value": self.fair_value,
            "is_speculative": self.is_speculative,
            "is_exchange_traded": self.is_exchange_traded,
            "is_government_supported": self.is_government_supported,
            "is_significant_investment": self.is_significant_investment,
            "ciu_approach": self.ciu_approach,
            "fund_reference": self.fund_reference,
            "fund_nav": self.fund_nav,
            "business_age_years": self.business_age_years,
        }


@dataclass(frozen=True)
class _CiuHolding:
    """
    CIU fund holding row (CIU_HOLDINGS_SCHEMA).

    fund_reference links to the CIU wrapper exposure.
    exposure_class: "EQUITY" — the load-bearing class for the opt-out path.
    cqs: null — equity holdings have no ECAI CQS grade.
    holding_value: GBP 1,000,000 (= fund_nav, so no leverage).
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


def create_p215_counterparties() -> pl.DataFrame:
    """
    Return all P2.15 counterparties as a two-row DataFrame.

    CP-EQ-OPTOUT-P215: CIU fund vehicle counterparty.
    CP-EQ-CTRL-P215:   Direct listed equity issuer counterparty.

    entity_type="corporate" for both — equity exposures link by counterparty_reference;
    entity_type does not itself affect the equity RW path.
    apply_fi_scalar=False, is_managed_as_retail=False, default_status=False.
    """
    rows = [
        # CIU fund vehicle (load-bearing exposure)
        _Counterparty(
            counterparty_reference=CP_CIU_OPTOUT,
            counterparty_name="P2.15 CIU Fund Vehicle — Opt-Out Test",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
        # Direct listed equity issuer (control exposure)
        _Counterparty(
            counterparty_reference=CP_CONTROL,
            counterparty_name="P2.15 Listed Equity Issuer — Control",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p215_equity_exposures() -> pl.DataFrame:
    """
    Return both P2.15 equity exposures as a two-row DataFrame.

    Row 1 — EQ-OPTOUT-CIU-001 (load-bearing):
      equity_type="ciu": routes through CIU branch in calculator.
      ciu_approach="look_through": triggers _resolve_look_through_rw aggregation.
      fund_reference=FUND-P215-OPTOUT: links to the single equity holding.
      fund_nav=1,000,000: denominator for weighted-avg RW (Art. 132a(3)).
      carrying_value=fair_value=1,000,000: EAD basis.
      is_speculative=False, is_exchange_traded=False, business_age_years=None:
        CIU wrapper — these flags apply to the underlying, not the wrapper itself.

    Row 2 — EQ-CONTROL-001 (control):
      equity_type="listed": B31 Art. 133(3) → 250% standard equity.
      is_exchange_traded=True: long-established listed stock.
      is_speculative=False: NOT higher-risk.
      business_age_years=10.0: > 5.0 → NOT young business (Art. 133(4) does not fire).
      carrying_value=fair_value=1,000,000: EAD basis.
      ciu_approach=None, fund_reference=None, fund_nav=None: not a CIU.

    Schema: EQUITY_EXPOSURE_SCHEMA (ensures all required columns present with correct dtypes).
    """
    rows = [
        # =====================================================================
        # EQ-OPTOUT-CIU-001: CIU look-through wrapper.
        # Under opted_out=False: holding_rw = max(3.70, 1.60) = 3.70 → RWA = 3,700,000.
        # Under opted_out=True:  holding_rw = 1.00 (default)         → RWA = 1,000,000.
        # =====================================================================
        _EquityExposure(
            exposure_reference=EXPOSURE_REF_CIU,
            counterparty_reference=CP_CIU_OPTOUT,
            equity_type="ciu",
            currency="GBP",
            carrying_value=EAD,
            fair_value=EAD,
            is_speculative=False,
            is_exchange_traded=False,
            is_government_supported=False,
            is_significant_investment=False,
            ciu_approach="look_through",
            fund_reference=FUND_REFERENCE,
            fund_nav=FUND_NAV,
            business_age_years=None,
        ),
        # =====================================================================
        # EQ-CONTROL-001: Direct LISTED equity, long-established.
        # B31 Art. 133(3): 250%. Transitional floor 2027 = 160% < 250% → no uplift.
        # RWA = 2,500,000 under BOTH opted_out configs.
        # =====================================================================
        _EquityExposure(
            exposure_reference=EXPOSURE_REF_CONTROL,
            counterparty_reference=CP_CONTROL,
            equity_type="listed",
            currency="GBP",
            carrying_value=EAD,
            fair_value=EAD,
            is_speculative=False,
            is_exchange_traded=True,  # listed stock
            is_government_supported=False,
            is_significant_investment=False,
            ciu_approach=None,
            fund_reference=None,
            fund_nav=None,
            business_age_years=10.0,  # >= 5.0 → NOT young business (Art. 133(4) inert)
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(EQUITY_EXPOSURE_SCHEMA))


def create_p215_ciu_holdings() -> pl.DataFrame:
    """
    Return the P2.15 CIU holdings as a single-row DataFrame.

    One equity holding under FUND-P215-OPTOUT:

    H1-EQ-P215 (EQUITY, null CQS, holding_value=1,000,000):
      exposure_class="EQUITY": routes to equity-class RW lookup.
      cqs=null: equity has no ECAI CQS → join misses → higher-of or default fallback.
      holding_value=1,000,000: equals fund_nav → no leverage.

    The single holding is the load-bearing row: its null CQS triggers the
    _equity_holding_higher_of_rw path when opted_out=False and reverts to
    _DEFAULT_HOLDING_RW=1.00 when opted_out=True.

    Schema: CIU_HOLDINGS_SCHEMA (fund_reference, holding_reference,
            exposure_class, cqs [Int8, nullable], holding_value [Float64]).
    """
    rows = [
        _CiuHolding(
            fund_reference=FUND_REFERENCE,
            holding_reference=HOLDING_REF_EQ,
            exposure_class="EQUITY",
            cqs=None,  # null — equity has no ECAI CQS grade
            holding_value=HOLDING_VALUE_EQ,  # GBP 1,000,000 = fund_nav (no leverage)
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(CIU_HOLDINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p215_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P2.15 parquet files and return a mapping of name to path.

    Files written:
        counterparties.parquet  — 2 rows (CP-EQ-OPTOUT-P215, CP-EQ-CTRL-P215)
        equity_exposures.parquet — 2 rows (EQ-OPTOUT-CIU-001, EQ-CONTROL-001)
        ciu_holding.parquet     — 1 row  (H1-EQ-P215, EQUITY null-CQS)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparties", create_p215_counterparties()),
        ("equity_exposures", create_p215_equity_exposures()),
        ("ciu_holding", create_p215_ciu_holdings()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P2.15 fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 80)
    print("Scenario: equity transitional irrevocable opt-out (PRA Rules 4.9-4.10)")
    print(
        f"  reporting_date: 2027-06-30 (Rule 4.2 standard band = {TRANSITIONAL_STANDARD_BAND_2027:.0%})"
    )
    print()
    print("  EQ-OPTOUT-CIU-001 (load-bearing — CIU look-through, single EQUITY holding, null CQS):")
    print(
        f"    opted_out=False: holding_rw={EXPECTED_HOLDING_RW_OPT_OUT_FALSE:.2f}"
        f" (max(IRB_simple={IRB_SIMPLE_RW_EQUITY_OTHER:.2f}, transitional={TRANSITIONAL_STANDARD_BAND_2027:.2f}))"
    )
    print(
        f"                     ciu_look_through_rw={EXPECTED_CIU_LT_RW_OPT_OUT_FALSE:.2f}"
        f"  RWA={EXPECTED_RWA_CIU_OPT_OUT_FALSE:,.0f}"
    )
    print(
        f"    opted_out=True:  holding_rw={EXPECTED_HOLDING_RW_OPT_OUT_TRUE:.2f}"
        f" (_DEFAULT_HOLDING_RW=100%, higher-of suppressed)"
    )
    print(
        f"                     ciu_look_through_rw={EXPECTED_CIU_LT_RW_OPT_OUT_TRUE:.2f}"
        f"  RWA={EXPECTED_RWA_CIU_OPT_OUT_TRUE:,.0f}"
    )
    print()
    print("  EQ-CONTROL-001 (control — direct LISTED equity, both configs):")
    print(f"    B31 Art. 133(3): RW={EXPECTED_RW_CONTROL:.2f} (250%)")
    print(
        f"    Transitional floor 2027: {TRANSITIONAL_STANDARD_BAND_2027:.2f} < {EXPECTED_RW_CONTROL:.2f} → floor does not bind"
    )
    print(f"    RWA={EXPECTED_RWA_CONTROL:,.0f} (unchanged under both opted_out configs)")
    print()
    print("  Key constants:")
    print(
        f"    IRB_SIMPLE_RW_EQUITY_OTHER       = {IRB_SIMPLE_RW_EQUITY_OTHER:.2f} (Art. 155(2) other)"
    )
    print(
        f"    TRANSITIONAL_STANDARD_BAND_2027  = {TRANSITIONAL_STANDARD_BAND_2027:.2f} (Rule 4.2 2027)"
    )
    print(f"    DEFAULT_HOLDING_RW               = {DEFAULT_HOLDING_RW:.2f} (Art. 132a fallback)")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p215_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
