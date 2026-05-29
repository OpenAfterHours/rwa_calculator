"""
Generate P2.19 fixtures: unlisted equity, young business, non-speculative — Art. 133(4) 400%.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (equity/calculator.py)

Scenario B31-L24 (P2.19):

    The Art. 133(4) higher-risk (400%) condition in equity/calculator.py is gated
    on equity_type in {private_equity, private_equity_diversified}.  An unlisted
    equity with business_age_years < 5.0 and is_speculative=False therefore
    incorrectly receives 250% instead of 400%.

    The fixture supplies the single row that exposes the defect:

        equity_type       = "unlisted"   → base-table RW 250% (Art. 133(3))
        business_age_years = 2.0         → < 5.0 threshold (Art. 133(4) condition b)
        is_exchange_traded = False        → not listed (Art. 133(4) condition a)
        is_speculative     = False        → crux: 400% must come from the dynamic
                                            condition, NOT the is_speculative path

    After the engine fix, the 400% condition is generalised to any non-listed equity
    (equity_type not in {listed, exchange_traded, government_supported}) that meets
    both Art. 133(4) sub-conditions.

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1(), reporting_date=2030-01-01):

    Step 1  equity_type="unlisted", is_exchange_traded=False → unlisted
    Step 2  is_speculative=False → skip speculative short-circuit
    Step 3  business_age_years=2.0 < 5.0 → Art. 133(4) higher-risk condition True
    Step 4  Art. 133(4): higher-risk unlisted equity → risk weight = 400%
    Step 5  EAD = fair_value = 1_000_000.0 (no carrying-value override)
    Step 6  RWA = 1_000_000.0 × 4.00 = 4_000_000.0
    Step 7  Transitional floor: reporting_date=2030-01-01 → steady-state → no floor
    Step 8  rwa_final = 4_000_000.0

Expected outputs:
    risk_weight  = 4.00
    ead_final    = 1_000_000.0
    rwa          = 4_000_000.0
    rwa_final    = 4_000_000.0

References:
    - PRA PS1/26 Art. 133(3): Standard unlisted equity = 250%
    - PRA PS1/26 Art. 133(4): Higher-risk unlisted (not exchange-traded, business <5yr) = 400%
    - PRA PS1/26 Glossary p.5: "long-established" = business >= 5 years old
    - src/rwa_calc/engine/equity/calculator.py: _apply_b31_equity_weights_sa() line ~548

Usage:
    python tests/fixtures/p2_19/p2_19.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, EQUITY_EXPOSURE_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions
# ---------------------------------------------------------------------------

COUNTERPARTY_REF: str = "B31-L24-CP1"
EXPOSURE_REF: str = "B31-L24-EQ1"

# Art. 133(4) business-age threshold (years)
BUSINESS_AGE_THRESHOLD_YEARS: float = 5.0

# Exposure economics
FAIR_VALUE: float = 1_000_000.0

# ---------------------------------------------------------------------------
# Expected outputs (for test-writer assertions)
# ---------------------------------------------------------------------------

#: Primary assertion: unlisted equity, young business → Art. 133(4) 400%
EXPECTED_RISK_WEIGHT: float = 4.00

#: EAD = fair_value (no carrying-value override)
EXPECTED_EAD: float = FAIR_VALUE  # 1_000_000.0

#: RWA = EAD × risk_weight
EXPECTED_RWA: float = FAIR_VALUE * EXPECTED_RISK_WEIGHT  # 4_000_000.0

#: rwa_final = RWA (steady-state, no transitional floor)
EXPECTED_RWA_FINAL: float = EXPECTED_RWA  # 4_000_000.0


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P2.19 equity counterparty row."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float | None
    total_assets: float | None
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool
    is_financial_sector_entity: bool

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
            "is_financial_sector_entity": self.is_financial_sector_entity,
        }


@dataclass(frozen=True)
class _EquityExposure:
    """
    P2.19 equity exposure row.

    equity_type="unlisted": base-table SA risk weight under Art. 133(3) is 250%.
    business_age_years=2.0: < 5.0 → Art. 133(4) higher-risk condition fires.
    is_speculative=False: crux of the scenario — the 400% must come from the
        dynamic Art. 133(4) condition, NOT from the is_speculative short-circuit.
    is_exchange_traded=False: satisfies Art. 133(4) condition (a) — not listed.
    """

    exposure_reference: str
    counterparty_reference: str
    equity_type: str
    currency: str
    fair_value: float
    is_speculative: bool
    is_exchange_traded: bool
    is_government_supported: bool
    is_significant_investment: bool
    business_age_years: float

    def to_dict(self) -> dict:
        return {
            "exposure_reference": self.exposure_reference,
            "counterparty_reference": self.counterparty_reference,
            "equity_type": self.equity_type,
            "currency": self.currency,
            "fair_value": self.fair_value,
            "is_speculative": self.is_speculative,
            "is_exchange_traded": self.is_exchange_traded,
            "is_government_supported": self.is_government_supported,
            "is_significant_investment": self.is_significant_investment,
            "business_age_years": self.business_age_years,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p219_counterparty() -> pl.DataFrame:
    """
    Return the P2.19 counterparty as a single-row DataFrame.

    entity_type="corporate": equity exposures are linked via counterparty_reference.
    is_financial_sector_entity=False: avoids FSE branch interference.
    """
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="P2.19 Unlisted Equity Issuer GB",
        entity_type="corporate",
        country_code="GB",
        annual_revenue=None,
        total_assets=None,
        default_status=False,
        apply_fi_scalar=False,
        is_managed_as_retail=False,
        is_financial_sector_entity=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p219_equity_exposure() -> pl.DataFrame:
    """
    Return the P2.19 equity exposure as a single-row DataFrame.

    The row exercises Art. 133(4) via the equity_type="unlisted" path.

    Pre-fix behaviour: the engine checks equity_type in {private_equity,
        private_equity_diversified} at line ~548 of calculator.py, so
        equity_type="unlisted" falls through to the default 250% branch,
        even though business_age_years=2.0 < 5.0 satisfies Art. 133(4).

    Post-fix assertion: risk_weight = 4.00 (400%), rwa = 4_000_000.
    """
    row = _EquityExposure(
        exposure_reference=EXPOSURE_REF,
        counterparty_reference=COUNTERPARTY_REF,
        equity_type="unlisted",  # EquityType.UNLISTED — base RW 250% before Art. 133(4) test
        currency="GBP",
        fair_value=FAIR_VALUE,  # 1_000_000.0 → ead_final
        is_speculative=False,  # crux: 400% must NOT come from speculative short-circuit
        is_exchange_traded=False,  # Art. 133(4)(a): not exchange-traded
        is_government_supported=False,
        is_significant_investment=False,
        business_age_years=2.0,  # Art. 133(4)(b): < 5.0 → higher-risk condition True
    )
    return pl.DataFrame(
        [row.to_dict()],
        schema=dtypes_of(EQUITY_EXPOSURE_SCHEMA),
    )


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p219_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P2.19 parquet files and return a mapping of name to path.

    Files written:
        counterparty.parquet      — 1 row  (B31-L24-CP1)
        equity_exposure.parquet   — 1 row  (B31-L24-EQ1)

    Args:
        output_dir: Target directory. Defaults to this package directory
            (``tests/fixtures/p2_19/``).

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts = [
        ("counterparty", create_p219_counterparty()),
        ("equity_exposure", create_p219_equity_exposure()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P2.19 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print(f"Scenario B31-L24: unlisted equity, business_age_years=2.0 < {BUSINESS_AGE_THRESHOLD_YEARS}y")
    print(f"  Counterparty:    {COUNTERPARTY_REF}")
    print(f"  Exposure:        {EXPOSURE_REF}")
    print(f"  equity_type:     unlisted (base RW 250%, Art. 133(3))")
    print(f"  is_speculative:  False — 400% must come from Art. 133(4), NOT speculative path")
    print(f"  business_age_years: 2.0 < {BUSINESS_AGE_THRESHOLD_YEARS}y → Art. 133(4) higher-risk")
    print(f"  fair_value:      GBP {FAIR_VALUE:,.0f}")
    print()
    print(f"  Expected risk_weight = {EXPECTED_RISK_WEIGHT:.2f}  (400%)")
    print(f"  Expected ead_final   = {EXPECTED_EAD:,.0f}")
    print(f"  Expected rwa         = {EXPECTED_RWA:,.0f}")
    print(f"  Expected rwa_final   = {EXPECTED_RWA_FINAL:,.0f}")
    print()
    print("Pre-fix defect:")
    print("  calculator.py ~line 548 gates Art. 133(4) on equity_type in")
    print("  {private_equity, private_equity_diversified} only → unlisted gets 250%")
    print("Post-fix: condition generalised to any non-listed, non-exchange-traded equity")


def main() -> None:
    """Entry point for standalone generation."""
    output_dir = None
    if "--data-dir" in sys.argv:
        idx = sys.argv.index("--data-dir")
        output_dir = Path(sys.argv[idx + 1])

    saved = save_p219_fixtures(output_dir)
    print_summary(saved)


if __name__ == "__main__":
    main()
