"""
Generate P1.182 fixtures: long-established PE/VC equity — 250% vs 400% business-age split.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (equity/calculator.py)

Key responsibilities:
- Produce one counterparty row: corporate PE fund, GB.
- Produce three equity-exposure rows exercising the business_age_years threshold:
    B31-L24 (primary): private_equity, business_age_years=12.0 → 250% (long-established)
    EQ_PE_BUG_001   : private_equity, business_age_years=2.0  → 400% (young, <5y)
    EQ_PE_DIV_001   : private_equity_diversified, business_age_years=null → 400% (null=conservative)

Regulatory rule under test (PRA PS1/26 Art. 133(4), Glossary p.5):
    Higher-risk unlisted equity = unlisted AND business < 5 years old.
    PE/VC is higher-risk (400%) ONLY when both conditions are met:
        (a) not exchange-traded (is_exchange_traded=False), AND
        (b) business_age_years < 5.0 (or null — treated conservatively as <5y).
    When business_age_years >= 5.0, PE/VC reverts to standard equity 250%
    (Art. 133(3)) — the "long-established" carve-out.

    Source: docs/specifications/crr/sa-risk-weights.md line ~1250:
        "PE/VC is only higher-risk if it meets both criteria" (unlisted + <5yr).

Defect in current engine (pre-fix):
    engine/equity/calculator.py _apply_b31_equity_weights_sa() maps
    equity_type="private_equity" unconditionally to 400%:
        .when(pl.col("equity_type") == "private_equity")
        .then(pl.lit(_B31_SA_RW[EquityType.PRIVATE_EQUITY]))   # 400%
    This ignores business_age_years entirely. A long-established (>=5y) PE
    investment that is correctly labelled "private_equity" is over-weighted.

Post-fix assertion (primary — B31-L24):
    exposure_reference = EQ_PE_LEGACY_001
    equity_type = "private_equity"
    business_age_years = 12.0          (>= 5 → long-established)
    is_exchange_traded = False          (unlisted)
    is_speculative = False
    fair_value = 1_000_000 GBP → EAD = 1_000_000
    Expected risk_weight = 2.50 (250%, Art. 133(3) standard)
    Expected rwa         = 2_500_000

Regression row 1 (EQ_PE_BUG_001):
    equity_type = "private_equity"
    business_age_years = 2.0           (< 5 → higher-risk)
    Expected risk_weight = 4.00 (400%, Art. 133(4))
    Expected rwa         = 4_000_000   (fair_value=1_000_000)

Regression row 2 (EQ_PE_DIV_001):
    equity_type = "private_equity_diversified"
    business_age_years = null          (null treated conservatively as <5y)
    Expected risk_weight = 4.00 (400%, Art. 133(4))
    Expected rwa         = 4_000_000   (fair_value=1_000_000)

Hand-calculation (B31-L24 primary):
    Step 1  equity_type="private_equity", business_age_years=12.0 >= 5.0
            → NOT higher-risk under Art. 133(4)
    Step 2  Not speculative (is_speculative=False), not exchange-traded
    Step 3  Art. 133(3) standard equity → 250%
    Step 4  EAD = fair_value = 1_000_000 (no carrying-value override)
    Step 5  RWA = 1_000_000 × 2.50 = 2_500_000
    Step 6  Transitional floor: reporting_date=2030-01-01 → steady-state (no floor)

Config: CalculationConfig.basel_3_1(reporting_date=date(2030, 1, 1))
    2030-01-01 is the first day of steady-state — all transitional floors have
    completed their phase-in (PRA Rule 4.1/4.2: 2027/2028/2029/2030+).
    This avoids any ambiguity about whether the floor applies.

Note on EQUITY_EXPOSURE_SCHEMA:
    The engine-implementer wave must add:
        "business_age_years": ColumnSpec(pl.Float64, required=False)
    to EQUITY_EXPOSURE_SCHEMA in src/rwa_calc/data/schemas.py.
    Until that wave completes, the column is present in the fixture parquet
    file but will be ignored / pass-through by the loader (unknown columns
    are not rejected — the loader projects to the declared schema and extras
    are preserved via ensure_columns' pass-through behaviour).

References:
    - PRA PS1/26 Art. 133(3): Standard equity = 250%
    - PRA PS1/26 Art. 133(4): Higher-risk (unlisted + business <5yr) = 400%
    - PRA PS1/26 Glossary p.5: definition of "long-established" (<5 years old)
    - docs/specifications/crr/sa-risk-weights.md lines 1244-1250
    - src/rwa_calc/engine/equity/calculator.py: _apply_b31_equity_weights_sa()
    - src/rwa_calc/data/schemas.py: EQUITY_EXPOSURE_SCHEMA (add business_age_years)

Usage:
    uv run python tests/fixtures/p1_182/p1_182.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "CP_PE_LEGACY_001"

# Primary scenario — long-established PE → 250%
EXPOSURE_REF_LEGACY = "EQ_PE_LEGACY_001"

# Regression row 1 — young PE (2y) → still 400%
EXPOSURE_REF_BUG = "EQ_PE_BUG_001"

# Regression row 2 — diversified PE, null age → still 400% (conservative null treatment)
EXPOSURE_REF_DIVERSIFIED = "EQ_PE_DIVERSIFIED_001"

# Threshold from PRA PS1/26 Art. 133(4) / Glossary p.5
BUSINESS_AGE_THRESHOLD_YEARS = 5.0

# Primary: long-established PE (12 years > 5-year threshold)
BUSINESS_AGE_LEGACY_YEARS = 12.0

# Regression: young PE (2 years < 5-year threshold)
BUSINESS_AGE_YOUNG_YEARS = 2.0

FAIR_VALUE = 1_000_000.0

# ---------------------------------------------------------------------------
# Expected outputs (for test-writer assertions)
# ---------------------------------------------------------------------------

#: B31-L24 primary assertion: long-established PE → standard 250%
EXPECTED_RW_LEGACY = 2.50  # Art. 133(3)

#: B31-L24 primary: RWA = 1_000_000 × 2.50
EXPECTED_RWA_LEGACY = FAIR_VALUE * EXPECTED_RW_LEGACY  # 2_500_000

#: Regression row 1: young PE → higher-risk 400%
EXPECTED_RW_YOUNG = 4.00  # Art. 133(4)
EXPECTED_RWA_YOUNG = FAIR_VALUE * EXPECTED_RW_YOUNG  # 4_000_000

#: Regression row 2: diversified PE, null age → higher-risk 400%
EXPECTED_RW_DIVERSIFIED = 4.00  # Art. 133(4), null treated conservatively
EXPECTED_RWA_DIVERSIFIED = FAIR_VALUE * EXPECTED_RW_DIVERSIFIED  # 4_000_000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """PE fund counterparty — entity_type=corporate, GB-domiciled."""

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
class _EquityExposure:
    """
    Equity exposure row including the new business_age_years field.

    business_age_years: None means unknown → engine treats conservatively as <5y (400%).
    business_age_years >= 5.0 → long-established → standard 250% (Art. 133(3)).
    business_age_years < 5.0  → higher-risk     → 400% (Art. 133(4)).
    """

    exposure_reference: str
    counterparty_reference: str
    equity_type: str
    currency: str
    carrying_value: float
    fair_value: float
    is_speculative: bool
    is_exchange_traded: bool
    is_government_supported: bool
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
            "business_age_years": self.business_age_years,
        }


# ---------------------------------------------------------------------------
# Equity exposure schema for this fixture
# (extends EQUITY_EXPOSURE_SCHEMA with business_age_years — engine-implementer
#  wave adds this column to the canonical schema in data/schemas.py)
# ---------------------------------------------------------------------------

_EQUITY_FIXTURE_SCHEMA: dict[str, PolarsDataType] = {
    "exposure_reference": pl.String,
    "counterparty_reference": pl.String,
    "equity_type": pl.String,
    "currency": pl.String,
    "carrying_value": pl.Float64,
    "fair_value": pl.Float64,
    "is_speculative": pl.Boolean,
    "is_exchange_traded": pl.Boolean,
    "is_government_supported": pl.Boolean,
    "business_age_years": pl.Float64,  # NEW: added for P1.182
}


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1182_counterparty() -> pl.DataFrame:
    """
    Return the P1.182 counterparty as a single-row DataFrame.

    A single PE fund counterparty shared by all three equity exposure rows.
    entity_type=corporate — equity exposures are linked to the counterparty
    by counterparty_reference in the equity_exposures input table, not via
    the main loan/facility exposure table.
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF,
            counterparty_name="Legacy PE Fund Ltd - P1.182",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=None,
            total_assets=50_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1182_equity_exposures() -> pl.DataFrame:
    """
    Return all three P1.182 equity exposure rows as a DataFrame.

    Row 1 — EQ_PE_LEGACY_001 (primary, B31-L24):
        PE, 12y old → long-established → Art. 133(3) 250% → RWA = 2,500,000.

    Row 2 — EQ_PE_BUG_001 (regression):
        PE, 2y old → young, <5y → Art. 133(4) 400% → RWA = 4,000,000.

    Row 3 — EQ_PE_DIVERSIFIED_001 (regression):
        PE diversified, null age → null treated conservatively as <5y →
        Art. 133(4) 400% → RWA = 4,000,000.
    """
    rows = [
        # =====================================================================
        # Primary (B31-L24): long-established PE, 12 years old
        # business_age_years=12.0 >= 5.0 → NOT higher-risk → 250%
        # =====================================================================
        _EquityExposure(
            exposure_reference=EXPOSURE_REF_LEGACY,
            counterparty_reference=COUNTERPARTY_REF,
            equity_type="private_equity",
            currency="GBP",
            carrying_value=FAIR_VALUE,
            fair_value=FAIR_VALUE,
            is_speculative=False,
            is_exchange_traded=False,
            is_government_supported=False,
            business_age_years=BUSINESS_AGE_LEGACY_YEARS,  # 12.0 >= 5.0 → 250%
        ),
        # =====================================================================
        # Regression 1 (EQ_PE_BUG_001): young PE, 2 years old
        # business_age_years=2.0 < 5.0 → higher-risk → 400%
        # =====================================================================
        _EquityExposure(
            exposure_reference=EXPOSURE_REF_BUG,
            counterparty_reference=COUNTERPARTY_REF,
            equity_type="private_equity",
            currency="GBP",
            carrying_value=FAIR_VALUE,
            fair_value=FAIR_VALUE,
            is_speculative=False,
            is_exchange_traded=False,
            is_government_supported=False,
            business_age_years=BUSINESS_AGE_YOUNG_YEARS,  # 2.0 < 5.0 → 400%
        ),
        # =====================================================================
        # Regression 2 (EQ_PE_DIVERSIFIED_001): diversified PE, null age
        # null treated conservatively as <5y → higher-risk → 400%
        # =====================================================================
        _EquityExposure(
            exposure_reference=EXPOSURE_REF_DIVERSIFIED,
            counterparty_reference=COUNTERPARTY_REF,
            equity_type="private_equity_diversified",
            currency="GBP",
            carrying_value=FAIR_VALUE,
            fair_value=FAIR_VALUE,
            is_speculative=False,
            is_exchange_traded=False,
            is_government_supported=False,
            business_age_years=None,  # null → conservative → 400%
        ),
    ]
    return pl.DataFrame(
        [r.to_dict() for r in rows],
        schema=_EQUITY_FIXTURE_SCHEMA,
    )


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1182_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.182 parquet files and return a mapping of name to path.

    Files written:
        counterparty.parquet  — 1 row (CP_PE_LEGACY_001)
        equity_exposure.parquet — 3 rows (legacy PE, young PE, diversified PE)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1182_counterparty()),
        ("equity_exposure", create_p1182_equity_exposures()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.182 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Primary scenario (B31-L24): long-established PE (12y), GBP 1m")
    print("  EQ_PE_LEGACY_001 / CP_PE_LEGACY_001")
    print(f"  business_age_years=12.0 >= {BUSINESS_AGE_THRESHOLD_YEARS}y threshold")
    print(f"  Expected RW={EXPECTED_RW_LEGACY:.2%}, RWA={EXPECTED_RWA_LEGACY:,.0f}")
    print()
    print("Bug (pre-fix): private_equity always routes to 400%")
    print("  even when business_age_years >= 5.0 (long-established carve-out)")
    print("Fix: add business_age_years >= 5.0 check in _apply_b31_equity_weights_sa()")
    print()
    print("Regression rows:")
    print(
        f"  EQ_PE_BUG_001       PE 2y (<5y)   → RW={EXPECTED_RW_YOUNG:.2%}, RWA={EXPECTED_RWA_YOUNG:,.0f}"
    )
    print(
        f"  EQ_PE_DIVERSIFIED_001 PE-div null   → RW={EXPECTED_RW_DIVERSIFIED:.2%},"
        f" RWA={EXPECTED_RWA_DIVERSIFIED:,.0f}"
    )


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1182_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
