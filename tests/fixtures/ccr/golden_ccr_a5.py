"""
Golden CCR-A5 scenario: single-name equity TRS, 1-year tenor, unmargined.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/)
    -> engine-implementer (SA-CCR equity branch of adjusted notional + PFE add-on)

Scenario design:
    One trade (T_EQ_001): 1-year GBP single-name equity TRS.
        asset_class = "equity"
        notional    = 0.0  (placeholder; equity branch uses market_price × units)
        market_price    = 50.0  GBP
        number_of_units = 1_000_000
        reference_entity = "GB00B16GWD56"
        is_index         = False  (single-name)
        MtM = 0.0 (at-par), delta = 1.0 (linear long), tenor 1y.
    One netting set (NS_EQ_001): counterparty CP_001 (institution, CQS 2, GB),
        legally enforceable (Art. 295), unmargined (CCR-A5 scope).
    Empty margin agreements and CCR collateral.

Regulatory hand-calc (CRR Art. 279b(1)(c) + Art. 279c(1) + Art. 280b + Art. 278 + 274):

    adjusted_notional = market_price × number_of_units
                      = 50.0 × 1_000_000 = 50_000_000 GBP       (Art. 279b(1)(c))

    years_to_maturity = (2027-01-15 - 2026-01-15) / 365.25
                      = 365 / 365.25
                      = 0.99931553723477...                      (engine convention)

    MF                = sqrt(min(years_to_maturity, 1.0) / 1.0)
                      = sqrt(0.99931553723477) = 0.99965770...   (Art. 279c(1))

    effective_notional = delta × adjusted_notional × MF
                       = 1.0 × 50_000_000 × 0.99965770...
                       = 49_982_885.29786...  GBP

    is_index=False → SF_EQ = 0.32, rho = 0.50                   (Art. 280b, Table 2)

    Single-trade collapse (sum_D = 49_982_885.30, sum_D^2 = same^2):
    AddOn_HS = SF × sqrt((rho × sum_D)^2 + (1−rho^2) × sum_D^2)
             = 0.32 × sqrt((0.5 × 49_982_885.30)^2 + 0.75 × (49_982_885.30)^2)
             = 0.32 × sqrt((49_982_885.30)^2 × (0.25 + 0.75))
             = 0.32 × 49_982_885.30
             = 15_994_523.295317...  GBP                         (Art. 277a)

    RC                = max(V - C, 0) = max(0 - 0, 0) = 0       (Art. 275(1))

    PFE multiplier    = min(1, 0.05 + 0.95 × exp(0 / (...))) = 1.0  (Art. 278(3))

    PFE_addon         = 1.0 × 15_994_523.295317 GBP              (Art. 278(1))

    EAD               = α × (RC + PFE) = 1.4 × 15_994_523.295317
                      = 22_392_332.613444 GBP                    (Art. 274(2))

    RWA               = EAD × RW = 22_392_332.613444 × 0.50
                      = 11_196_166.306722 GBP                    (Art. 120(1) Table 3)

Counterparty reuse:
    CCR-A5 reuses the CCR-A1 institution counterparty (CP_001, GB, CQS 2) so the
    SA Institution lookup ends in 50% RW. The counterparty/rating builders are
    imported from ``golden_ccr_a1`` directly.

References:
    - CRR Art. 274(2) (EAD = α × (RC + PFE), α = 1.4)
    - CRR Art. 275(1) (unmargined RC = max(V - C, 0))
    - CRR Art. 277(2)(d) (equity hedging set = one per asset class per NS)
    - CRR Art. 277a + Art. 280b (equity add-on formula)
    - CRR Art. 278(3) (PFE multiplier)
    - CRR Art. 279a(1) (supervisory delta = ±1 for linear trades)
    - CRR Art. 279b(1)(c) (equity adjusted notional d = market_price × units)
    - CRR Art. 279c(1) (unmargined MF = sqrt(min(M, 1y) / 1y))
    - CRR Art. 280 Table 2 (SF_EQ = 32% SN / 20% IDX)
    - CRR Art. 280b (rho = 0.50 SN / 0.80 IDX)
    - CRR Art. 120(1) Table 3 (institution CQS 2 SA risk weight = 50%)
"""

from __future__ import annotations

from datetime import date as _date
from pathlib import Path

import polars as pl

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    RawDataBundle,
    TradeBundle,
)
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import CCR_COLLATERAL_SCHEMA

from .golden_ccr_a1 import (
    _build_cp_001_counterparty,
    _build_cp_001_rating,
    _build_empty_facilities,
    _build_empty_facility_mappings,
    _build_empty_lending_mappings,
    _build_empty_loans,
    create_ccr_a1_margin_agreements,
)
from .netting_set_builder import NettingSet, create_netting_sets
from .trade_builder import Trade, create_trades, make_equity_trade

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for CCR-A5 test assertions.
# ---------------------------------------------------------------------------

CCR_A5_TRADE_ID: str = "T_EQ_001"
CCR_A5_NETTING_SET_ID: str = "NS_EQ_001"
CCR_A5_COUNTERPARTY_REF: str = "CP_001"  # reuse CCR-A1 institution CP

CCR_A5_ASSET_CLASS: str = "equity"
CCR_A5_TRANSACTION_TYPE: str = "derivative"

# Equity adjusted notional inputs (Art. 279b(1)(c)).
CCR_A5_MARKET_PRICE: float = 50.0          # GBP per unit
CCR_A5_NUMBER_OF_UNITS: float = 1_000_000.0
CCR_A5_REFERENCE_ENTITY: str = "GB00B16GWD56"
CCR_A5_IS_INDEX: bool = False              # single-name (not index)

CCR_A5_MTM: float = 0.0
CCR_A5_DELTA: float = 1.0
CCR_A5_IS_LONG: bool = True

# 1-year tenor: 2026-01-15 start, 2027-01-15 maturity.
CCR_A5_START_DATE: _date = _date(2026, 1, 15)
CCR_A5_MATURITY_DATE: _date = _date(2027, 1, 15)

CCR_A5_IS_LEGALLY_ENFORCEABLE: bool = True
CCR_A5_IS_MARGINED: bool = False

# ---------------------------------------------------------------------------
# Expected hand-calc outputs — single source of truth for acceptance asserts.
# ---------------------------------------------------------------------------

# Art. 279b(1)(c): d = market_price × number_of_units.
CCR_A5_ADJUSTED_NOTIONAL: float = 50_000_000.0

# Art. 275(1): RC = max(V - C, 0) = max(0 - 0, 0).
CCR_A5_RC_UNMARGINED: float = 0.0

# Art. 277a + 280b (single-name collapse, one trade):
# AddOn_HS = 0.32 × 49_982_885.297867 = 15_994_523.295317
CCR_A5_ADDON_AGGREGATE: float = 15_994_523.295317

# Art. 278(3): PFE multiplier = 1.0 (at-par, unmargined).
CCR_A5_PFE_MULTIPLIER: float = 1.0

# Art. 278(1): PFE_addon = multiplier × AddOn_aggregate.
CCR_A5_PFE_ADDON: float = 15_994_523.295317

# Art. 274(2): EAD = 1.4 × (RC + PFE).
CCR_A5_EAD_CCR: float = 22_392_332.613444
CCR_A5_EAD_FINAL: float = 22_392_332.613444

# Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight.
CCR_A5_EXPOSURE_CLASS: str = "institution"
CCR_A5_RISK_WEIGHT: float = 0.50

# RWA = EAD × RW.
CCR_A5_RWA_FINAL: float = 11_196_166.306722

# Tolerance bounds for acceptance assertions.
CCR_A5_MONETARY_REL_TOLERANCE: float = 1e-6
CCR_A5_MULTIPLIER_ABS_TOLERANCE: float = 1e-12


# ---------------------------------------------------------------------------
# CCR-A5 trade + netting-set builders.
# ---------------------------------------------------------------------------


def _ccr_a5_trade() -> Trade:
    """Return the single CCR-A5 equity TRS trade instance."""
    return make_equity_trade(
        trade_id=CCR_A5_TRADE_ID,
        netting_set_id=CCR_A5_NETTING_SET_ID,
        asset_class=CCR_A5_ASSET_CLASS,
        transaction_type=CCR_A5_TRANSACTION_TYPE,
        maturity_date=CCR_A5_MATURITY_DATE,
        start_date=CCR_A5_START_DATE,
        delta=CCR_A5_DELTA,
        is_long=CCR_A5_IS_LONG,
        mtm_value=CCR_A5_MTM,
        market_price=CCR_A5_MARKET_PRICE,
        number_of_units=CCR_A5_NUMBER_OF_UNITS,
        reference_entity=CCR_A5_REFERENCE_ENTITY,
        is_index=CCR_A5_IS_INDEX,
    )


def _ccr_a5_netting_set() -> NettingSet:
    """Return the single CCR-A5 netting-set instance."""
    return NettingSet(
        netting_set_id=CCR_A5_NETTING_SET_ID,
        counterparty_reference=CCR_A5_COUNTERPARTY_REF,
        is_legally_enforceable=CCR_A5_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_A5_IS_MARGINED,
    )


def create_ccr_a5_trades() -> pl.DataFrame:
    """Return the single-row trades DataFrame for CCR-A5."""
    return create_trades([_ccr_a5_trade()])


def create_ccr_a5_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CCR-A5."""
    return create_netting_sets([_ccr_a5_netting_set()])


def create_ccr_a5_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-A5: no collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Bundle assembly helpers.
# ---------------------------------------------------------------------------


def _build_ccr_a5_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle from the four CCR-A5 domain frames.

    Composition:
        trades            — 1 row  (T_EQ_001, 1y GBP equity TRS, NS_EQ_001)
        netting_sets      — 1 row  (NS_EQ_001, CP_001, enforceable, unmargined)
        margin_agreements — 0 rows (CCR-A5: unmargined, no CSA)
        ccr_collateral    — 0 rows (CCR-A5: no posted/received collateral)
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=create_ccr_a5_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_ccr_a5_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_ccr_a1_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_ccr_a5_collateral().lazy()),
    )


def build_raw_data_bundle_with_ccr_a5() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle with CCR-A5 (equity TRS) populated.

    Reuses CP_001 (institution, CQS 2, GB) from the CCR-A1 portfolio stub so
    the SA Institution lookup ends in CRR Art. 120(1) Table 3 → 50% RW.
    No FX rates frame needed (equity adjusted notional uses market_price × units
    directly in reporting currency GBP; no cross-currency conversion).
    """
    return RawDataBundle(
        counterparties=_build_cp_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_001_rating(),
        ccr=_build_ccr_a5_raw_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Save helper — canonical entry point for generate_all.py and standalone use.
# ---------------------------------------------------------------------------


def save_ccr_a5_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all CCR-A5 golden parquet files to *output_dir*.

    Files produced:
        ccr_a5_trades.parquet        — 1 row  (T_EQ_001, 1y GBP equity TRS)
        ccr_a5_netting_sets.parquet  — 1 row  (NS_EQ_001, CP_001, enforceable, unmargined)

    The margin_agreements and ccr_collateral frames are empty and shared with
    CCR-A1; they are not re-written here to avoid overwriting the A1 golden
    files. Acceptance tests that need empty margin / collateral frames should
    reuse ``create_ccr_a1_margin_agreements()`` / ``create_ccr_a5_collateral()``.

    Args:
        output_dir: Target directory. Defaults to the directory containing
            this script (``tests/fixtures/ccr/``).

    Returns:
        Dict mapping artefact name to saved absolute ``Path``.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("ccr_a5_trades", create_ccr_a5_trades()),
        ("ccr_a5_netting_sets", create_ccr_a5_netting_sets()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_ccr_a5_fixtures()
    print("CCR-A5 golden fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<30} {len(df):>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
    print("-" * 70)
    print("Scenario: CCR-A5 — single-name equity TRS, 1y, unmargined, no collateral")
    print(
        f"  Trade:       {CCR_A5_TRADE_ID} (asset_class={CCR_A5_ASSET_CLASS!r},"
        f" market_price={CCR_A5_MARKET_PRICE}, units={CCR_A5_NUMBER_OF_UNITS:,.0f})"
    )
    print(
        f"  Netting set: {CCR_A5_NETTING_SET_ID} -> {CCR_A5_COUNTERPARTY_REF}"
        f" (enforceable={CCR_A5_IS_LEGALLY_ENFORCEABLE},"
        f" margined={CCR_A5_IS_MARGINED})"
    )
    print(f"  Expected adj_notional: {CCR_A5_ADJUSTED_NOTIONAL:,.0f} GBP")
    print(f"  Expected addon_aggregate: {CCR_A5_ADDON_AGGREGATE:,.6f} GBP")
    print(f"  Expected EAD: {CCR_A5_EAD_CCR:,.6f} GBP")
    print(f"  Expected RWA: {CCR_A5_RWA_FINAL:,.6f} GBP")


if __name__ == "__main__":
    main()
