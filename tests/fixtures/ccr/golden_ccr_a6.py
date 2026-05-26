"""
Golden CCR-A6 scenario: 1-year GBP long call on equity index, unmargined.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/)
    -> engine-implementer (SA-CCR equity branch: Black-Scholes Phi(d1) supervisory
       delta + index SF/rho parameters)

Scenario design:
    One trade (T_EQ_OPT_001): 1-year GBP long call on an equity index.
        asset_class           = "equity"
        option_type           = "call"          (non-linear payoff → Phi(d1) path)
        option_strike         = 110.0           (OTM)
        option_underlying_price = 100.0         (spot price P)
        is_long               = True            (long call → +Phi(d1))
        market_price          = 100.0  GBP      (per unit, same as underlying price)
        number_of_units       = 500_000         (contract size)
        reference_entity      = "UKX_INDEX"
        is_index              = True            (index → SF=0.20, rho=0.80)
        MtM = 0.0 (not yet valued), delta = 1.0 placeholder (engine replaces with Phi(d1))
        Tenor: 2026-01-15 start, 2027-01-15 maturity (1-year)
    One netting set (NS_EQ_OPT_001): counterparty CP_001 (institution, CQS 2, GB),
        legally enforceable (Art. 295), unmargined (CCR-A6 scope).
    Empty margin agreements and CCR collateral.

Regulatory hand-calc (CRR Art. 279a(2) + Art. 279b(1)(c) + Art. 279c(1) + Art. 280b + Art. 278 + 274):

    Supervisory volatility (equity, Art. 280b Table 2):
        σ = 0.80 (equity supervisory vol)

    T_to_maturity = (2027-01-15 - 2026-01-15) / 365.25
                  = 365 / 365.25 ≈ 0.99931553723477    (engine convention)

    Black-Scholes d1 (Art. 279a(2)):
        d1 = (ln(P/K) + 0.5 · σ² · T) / (σ · √T)
           = (ln(100/110) + 0.5 · 0.64 · 0.99931554) / (0.80 · √0.99931554)
           = (-0.09531018 + 0.31978097) / (0.79972762)
           = 0.22447079 / 0.79972762
           ≈ 0.28068...

    supervisory_delta = +Phi(d1)  (long call, Art. 279a(2)(a)):
        delta ≈ Phi(0.28068) ≈ 0.61055...
        (exact value determined by polars-normal-stats backend in test)

    adjusted_notional = market_price × number_of_units           (Art. 279b(1)(c))
                      = 100.0 × 500_000 = 50_000_000 GBP

    MF                = sqrt(min(T, 1.0) / 1.0)                  (Art. 279c(1))
                      = sqrt(0.99931554) ≈ 0.99965770

    effective_notional = delta × adjusted_notional × MF
                       = 0.61055... × 50_000_000 × 0.99965770
                       ≈ 30_506_419.53...  GBP  (depends on Phi backend)

    is_index=True → SF_EQ = 0.20, rho = 0.80                     (Art. 280b, Table 2)

    Single-trade collapse (sum_D ≈ 30_506_419.53):
    AddOn_HS = SF × sqrt((rho × sum_D)^2 + (1−rho^2) × sum_D^2)
             = 0.20 × sqrt((0.80 × D)^2 + (1 - 0.64) × D^2)
             = 0.20 × sqrt(D^2 × (0.64 + 0.36))
             = 0.20 × D
             ≈ 0.20 × 30_506_419.53
             ≈ 5_976_656.65... GBP                                (Art. 277a, 280b)

    RC                = max(V - C, 0) = max(0 - 0, 0) = 0        (Art. 275(1))

    PFE multiplier    = 1.0  (V=0, C=0, unmargined)              (Art. 278(3))

    PFE_addon         = 1.0 × AddOn_aggregate                     (Art. 278(1))
                      ≈ 5_976_656.65... GBP

    EAD               = α × (RC + PFE) = 1.4 × 5_976_656.65...  (Art. 274(2))
                      ≈ 8_367_319.31... GBP

    RWA               = EAD × RW = 8_367_319.31... × 0.50
                      ≈ 4_183_659.66... GBP                       (Art. 120(1) Table 3)

Note on expected values:
    The JSON pin values (addon_aggregate=5976656.65, ead=8367319.31, rwa=4183659.66)
    are computed from the exact Phi(d1) output of the polars-normal-stats backend.
    The exact delta used is ~0.61055. Acceptance tests recompute against the live
    backend and compare within monetary relative tolerance 1e-6.

Counterparty reuse:
    CCR-A6 reuses the CCR-A1 institution counterparty (CP_001, GB, CQS 2) so the
    SA Institution lookup ends in 50% RW. The counterparty/rating builders are
    imported from ``golden_ccr_a1`` directly.

References:
    - CRR Art. 274(2) (EAD = α × (RC + PFE), α = 1.4)
    - CRR Art. 275(1) (unmargined RC = max(V - C, 0))
    - CRR Art. 277(2)(d) (equity hedging set = one per asset class per NS)
    - CRR Art. 277a + Art. 280b (equity add-on formula)
    - CRR Art. 278(3) (PFE multiplier)
    - CRR Art. 279a(2)(a) (long call supervisory delta = +Phi(d1))
    - CRR Art. 279b(1)(c) (equity adjusted notional d = market_price × units)
    - CRR Art. 279c(1) (unmargined MF = sqrt(min(M, 1y) / 1y))
    - CRR Art. 280 Table 2 (SF_EQ = 32% SN / 20% IDX; σ_EQ = 80%)
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
# Scenario constants — single source of truth for CCR-A6 test assertions.
# ---------------------------------------------------------------------------

CCR_A6_TRADE_ID: str = "T_EQ_OPT_001"
CCR_A6_NETTING_SET_ID: str = "NS_EQ_OPT_001"
CCR_A6_COUNTERPARTY_REF: str = "CP_001"  # reuse CCR-A1 institution CP

CCR_A6_ASSET_CLASS: str = "equity"
CCR_A6_TRANSACTION_TYPE: str = "derivative"

# Equity option inputs (Art. 279a(2) + Art. 279b(1)(c)).
CCR_A6_MARKET_PRICE: float = 100.0          # GBP per unit (= underlying spot price)
CCR_A6_NUMBER_OF_UNITS: float = 500_000.0
CCR_A6_REFERENCE_ENTITY: str = "UKX_INDEX"
CCR_A6_IS_INDEX: bool = True               # equity index (not single-name)

# Black-Scholes supervisory delta inputs (CRR Art. 279a(2)).
CCR_A6_OPTION_TYPE: str = "call"
CCR_A6_OPTION_STRIKE: float = 110.0         # OTM call (K > P)
CCR_A6_OPTION_UNDERLYING_PRICE: float = 100.0  # spot price P

CCR_A6_MTM: float = 0.0
CCR_A6_DELTA: float = 1.0   # placeholder — engine overwrites with Phi(d1)
CCR_A6_IS_LONG: bool = True

# 1-year tenor: 2026-01-15 start, 2027-01-15 maturity.
CCR_A6_START_DATE: _date = _date(2026, 1, 15)
CCR_A6_MATURITY_DATE: _date = _date(2027, 1, 15)

CCR_A6_IS_LEGALLY_ENFORCEABLE: bool = True
CCR_A6_IS_MARGINED: bool = False

# ---------------------------------------------------------------------------
# Expected hand-calc outputs — single source of truth for acceptance asserts.
# ---------------------------------------------------------------------------

# Art. 279b(1)(c): d = market_price × number_of_units.
CCR_A6_ADJUSTED_NOTIONAL: float = 50_000_000.0

# Art. 275(1): RC = max(V - C, 0) = max(0 - 0, 0).
CCR_A6_RC_UNMARGINED: float = 0.0

# Art. 277a + 280b (index branch, single-trade collapse):
# AddOn_HS = 0.20 × effective_notional  (rho=0.80 collapses to 1.0 factor for single trade)
# Pin value from polars-normal-stats Phi(d1) backend:
CCR_A6_ADDON_AGGREGATE: float = 5_976_656.65

# Art. 278(3): PFE multiplier = 1.0 (at-par, unmargined).
CCR_A6_PFE_MULTIPLIER: float = 1.0

# Art. 278(1): PFE_addon = multiplier × AddOn_aggregate.
CCR_A6_PFE_ADDON: float = 5_976_656.65

# Art. 274(2): EAD = 1.4 × (RC + PFE).
CCR_A6_EAD_CCR: float = 8_367_319.31
CCR_A6_EAD_FINAL: float = 8_367_319.31

# Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight.
CCR_A6_EXPOSURE_CLASS: str = "institution"
CCR_A6_RISK_WEIGHT: float = 0.50

# RWA = EAD × RW.
CCR_A6_RWA_FINAL: float = 4_183_659.66

# Tolerance bounds for acceptance assertions.
CCR_A6_MONETARY_REL_TOLERANCE: float = 1e-6
CCR_A6_MULTIPLIER_ABS_TOLERANCE: float = 1e-12


# ---------------------------------------------------------------------------
# CCR-A6 trade + netting-set builders.
# ---------------------------------------------------------------------------


def _ccr_a6_trade() -> Trade:
    """Return the single CCR-A6 equity index call option trade instance."""
    return make_equity_trade(
        trade_id=CCR_A6_TRADE_ID,
        netting_set_id=CCR_A6_NETTING_SET_ID,
        asset_class=CCR_A6_ASSET_CLASS,
        transaction_type=CCR_A6_TRANSACTION_TYPE,
        notional=0.0,
        currency="GBP",
        maturity_date=CCR_A6_MATURITY_DATE,
        start_date=CCR_A6_START_DATE,
        delta=CCR_A6_DELTA,
        is_long=CCR_A6_IS_LONG,
        mtm_value=CCR_A6_MTM,
        option_type=CCR_A6_OPTION_TYPE,
        option_strike=CCR_A6_OPTION_STRIKE,
        option_underlying_price=CCR_A6_OPTION_UNDERLYING_PRICE,
        market_price=CCR_A6_MARKET_PRICE,
        number_of_units=CCR_A6_NUMBER_OF_UNITS,
        reference_entity=CCR_A6_REFERENCE_ENTITY,
        is_index=CCR_A6_IS_INDEX,
    )


def _ccr_a6_netting_set() -> NettingSet:
    """Return the single CCR-A6 netting-set instance."""
    return NettingSet(
        netting_set_id=CCR_A6_NETTING_SET_ID,
        counterparty_reference=CCR_A6_COUNTERPARTY_REF,
        is_legally_enforceable=CCR_A6_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_A6_IS_MARGINED,
    )


def create_ccr_a6_trades() -> pl.DataFrame:
    """Return the single-row trades DataFrame for CCR-A6."""
    return create_trades([_ccr_a6_trade()])


def create_ccr_a6_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CCR-A6."""
    return create_netting_sets([_ccr_a6_netting_set()])


def create_ccr_a6_margin_agreements() -> pl.DataFrame:
    """Return a zero-row margin-agreements DataFrame (CCR-A6: unmargined, no CSA)."""
    return create_ccr_a1_margin_agreements()


def create_ccr_a6_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-A6: no collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Bundle assembly helpers.
# ---------------------------------------------------------------------------


def _build_ccr_a6_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle from the four CCR-A6 domain frames.

    Composition:
        trades            — 1 row  (T_EQ_OPT_001, 1y GBP equity index call)
        netting_sets      — 1 row  (NS_EQ_OPT_001, CP_001, enforceable, unmargined)
        margin_agreements — 0 rows (CCR-A6: unmargined, no CSA)
        ccr_collateral    — 0 rows (CCR-A6: no posted/received collateral)
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=create_ccr_a6_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_ccr_a6_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_ccr_a6_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_ccr_a6_collateral().lazy()),
    )


def build_ccr_a6_bundle() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle with CCR-A6 (equity index call) populated.

    Reuses CP_001 (institution, CQS 2, GB) from the CCR-A1 portfolio stub so
    the SA Institution lookup ends in CRR Art. 120(1) Table 3 → 50% RW.
    No FX rates frame needed (equity adjusted notional uses market_price × units
    directly in reporting currency GBP; no cross-currency conversion).

    The trade carries ``option_type="call"`` + non-null ``option_strike`` and
    ``option_underlying_price`` — the engine supervisory-delta branch will
    replace the placeholder ``delta=1.0`` with ``+Phi(d1)`` per Art. 279a(2)(a).
    ``is_index=True`` routes SF and rho to the index row (SF=0.20, rho=0.80)
    per CRR Art. 280 Table 2 and Art. 280b.

    Returns:
        A fully assembled ``RawDataBundle`` ready for the CCR pipeline.
    """
    return RawDataBundle(
        counterparties=_build_cp_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_001_rating(),
        ccr=_build_ccr_a6_raw_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Save helper — canonical entry point for generate_all.py and standalone use.
# ---------------------------------------------------------------------------


def save_ccr_a6_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all CCR-A6 golden parquet files to *output_dir*.

    Files produced:
        ccr_a6_trades.parquet        — 1 row  (T_EQ_OPT_001, 1y GBP equity index call)
        ccr_a6_netting_sets.parquet  — 1 row  (NS_EQ_OPT_001, CP_001, enforceable, unmargined)

    The margin_agreements and ccr_collateral frames are empty and shared with
    CCR-A1; they are not re-written here to avoid overwriting the A1 golden
    files. Acceptance tests that need empty margin / collateral frames should
    reuse ``create_ccr_a1_margin_agreements()`` / ``create_ccr_a6_collateral()``.

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
        ("ccr_a6_trades", create_ccr_a6_trades()),
        ("ccr_a6_netting_sets", create_ccr_a6_netting_sets()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_ccr_a6_fixtures()
    print("CCR-A6 golden fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<30} {len(df):>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
    print("-" * 70)
    print("Scenario: CCR-A6 — 1y GBP long call on equity index, unmargined, no collateral")
    print(
        f"  Trade:       {CCR_A6_TRADE_ID} (asset_class={CCR_A6_ASSET_CLASS!r},"
        f" option_type={CCR_A6_OPTION_TYPE!r}, K={CCR_A6_OPTION_STRIKE},"
        f" P={CCR_A6_OPTION_UNDERLYING_PRICE}, is_index={CCR_A6_IS_INDEX})"
    )
    print(
        f"  Market:      market_price={CCR_A6_MARKET_PRICE},"
        f" units={CCR_A6_NUMBER_OF_UNITS:,.0f}"
    )
    print(
        f"  Netting set: {CCR_A6_NETTING_SET_ID} -> {CCR_A6_COUNTERPARTY_REF}"
        f" (enforceable={CCR_A6_IS_LEGALLY_ENFORCEABLE},"
        f" margined={CCR_A6_IS_MARGINED})"
    )
    print(f"  Expected adj_notional: {CCR_A6_ADJUSTED_NOTIONAL:,.0f} GBP")
    print(f"  Expected addon_aggregate (pin): {CCR_A6_ADDON_AGGREGATE:,.2f} GBP")
    print(f"  Expected EAD (pin): {CCR_A6_EAD_CCR:,.2f} GBP")
    print(f"  Expected RWA (pin): {CCR_A6_RWA_FINAL:,.2f} GBP")


if __name__ == "__main__":
    main()
