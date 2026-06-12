"""
Golden CCR-A4 scenario: single 5-year GBP credit-index (iTraxx Europe S40) IG CDS, unmargined.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/)
    -> engine-implementer (SA-CCR credit branch: index adjusted notional + PFE add-on)

Scenario design:
    One trade (T_CR_002): 5-year GBP credit-index IG CDS.
        notional: GBP 100m
        reference_entity: "ITRAXX_EUROPE_S40_LEI_5493001I" (iTraxx Europe Series 40 index)
        credit_quality: "IG" (investment-grade)
        is_index: True (credit index — load-bearing distinction vs CCR-A3 single-name)
        MtM = 0.0 (at-par at the reporting date), delta = 1.0 (long protection).
    One netting set (NS_CR_002): counterparty CP_001 (institution, CQS 2, GB),
        legally enforceable (Art. 295), unmargined (CCR-A4 scope).

Regulatory hand-calc (CRR Art. 279b(1)(a) + Art. 277a + Art. 280 + Art. 280a + Art. 274):

    S = max(0 / 365.25, 0.04) = 0.04             [10-BD floor, Art. 279b(1)(a)]
    E = 1826 / 365.25         = 4.9993155373...  [days from 2026-01-15 to 2031-01-15]

    SD(S, E) = (exp(-0.05 × S) − exp(-0.05 × E)) / 0.05
             = (exp(-0.002)    − exp(-0.24996578)) / 0.05
             ≈ (0.998002       − 0.778716)         / 0.05
             ≈ 4.3834912427

    d = 100m × 4.3834912427  = 438,349,124.271 GBP  (Art. 279b(1)(a))

    supervisory_delta = +1.0
    MF = sqrt(min(E, 1) / 1) = sqrt(1 / 1) = 1.0    (Art. 279c(1), E > 1y)
    EN = 1.0 × 438,349,124.271 × 1.0 = 438,349,124.271

    SF_CR (credit index IG) = 0.0038                  (Art. 280 Table 2)
    rho   (credit index)    = 0.80                     (Art. 280a)

    AddOn_entity = SF_CR × EN = 0.0038 × 438,349,124.271 = 1,665,726.672

    For a single-entity netting set:
        systematic    = (rho × AddOn_entity)^2 = (0.80 × 1,665,726.672)^2
        idiosyncratic = (1 − rho^2) × AddOn_entity^2
                      = (1 − 0.64) × 1,665,726.672^2
                      = 0.36 × 1,665,726.672^2
        AddOn_credit_HS = sqrt(systematic + idiosyncratic)
                        = sqrt((0.80 × A)^2 + 0.36 × A^2)  where A = 1,665,726.672
                        = sqrt((0.64 + 0.36) × A^2) = sqrt(A^2) = A = 1,665,726.672
        (single-entity still collapses to |SF × EN| — the multi-entity test
         is load-bearing for two entities in one hedging set)

    RC  = max(V - C, 0) = max(0 - 0, 0) = 0              (Art. 275(1))
    PFE multiplier = 1.0  (at-par, V=0, C=0)              (Art. 278(3))
    PFE_addon      = 1.0 × 1,665,726.672 = 1,665,726.672  (Art. 278(1))
    EAD            = 1.4 × (0 + 1,665,726.672)            (Art. 274(2))
                   ≈ 2,332,017.341 GBP
    RW (institution CQS-2) = 0.50                          (Art. 120(1) Table 3)
    RWA = 2,332,017.341 × 0.50 = 1,166,008.670 GBP

Key distinction from CCR-A3:
    CCR-A3 uses is_index=False (single-name) → SF=0.0046, rho=0.50.
    CCR-A4 uses is_index=True  (credit index) → SF=0.0038, rho=0.80.
    The is_index flag is the load-bearing difference; all other trade fields
    are identical (same tenor, same notional, same IG quality, same CP).

Counterparty reuse:
    CCR-A4 reuses the CCR-A1 institution counterparty (CP_001, GB, CQS 2) so
    the SA Institution lookup ends in CRR Art. 120(1) Table 3 → 50% RW.

References:
    - CRR Art. 271 (CCR scope)
    - CRR Art. 274(2) (EAD = alpha × (RC + PFE), alpha = 1.4)
    - CRR Art. 275(1) (unmargined RC = max(V - C, 0))
    - CRR Art. 277(2)(c) (one credit hedging set per netting set)
    - CRR Art. 277a(1) (add-on aggregation within credit HS)
    - CRR Art. 278 (PFE multiplier + PFE add-on composition)
    - CRR Art. 279b(1)(a) (credit/IR adjusted notional via supervisory duration)
    - CRR Art. 279c(1) (unmargined MF = sqrt(min(M, 1y) / 1y))
    - CRR Art. 280 Table 2 (SF_CR_IDX_IG = 0.0038)
    - CRR Art. 280a (credit rho: 0.50 single-name, 0.80 index)
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
from tests.fixtures.raw_bundle import make_raw_bundle

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
from .trade_builder import Trade, create_trades, make_credit_trade

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for CCR-A4 test assertions.
# ---------------------------------------------------------------------------

TRADE_ID: str = "T_CR_002"
NETTING_SET_ID: str = "NS_CR_002"
COUNTERPARTY_REF: str = "CP_001"  # reuse CCR-A1 institution CP

CCR_A4_ASSET_CLASS: str = "credit"
CCR_A4_TRANSACTION_TYPE: str = "derivative"

CCR_A4_NOTIONAL: float = 100_000_000.0
CCR_A4_CURRENCY: str = "GBP"

# 5-year tenor: 2026-01-15 start, 2031-01-15 maturity (same as CCR-A3).
CCR_A4_START_DATE: _date = _date(2026, 1, 15)
CCR_A4_MATURITY_DATE: _date = _date(2031, 1, 15)

CCR_A4_MTM: float = 0.0
CCR_A4_DELTA: float = 1.0
CCR_A4_IS_LONG: bool = True

CCR_A4_REFERENCE_ENTITY: str = "ITRAXX_EUROPE_S40_LEI_5493001I"
CCR_A4_IS_INDEX: bool = True  # credit index — load-bearing vs CCR-A3 single-name
CCR_A4_CREDIT_QUALITY: str = "IG"

CCR_A4_IS_LEGALLY_ENFORCEABLE: bool = True
CCR_A4_IS_MARGINED: bool = False

# ---------------------------------------------------------------------------
# Hand-calc expected outputs (tolerance rel=1e-6 in acceptance tests).
# ---------------------------------------------------------------------------

# CRR Art. 279b(1)(a): same SD formula as CCR-A3 (identical tenor, same dates).
# SD(0.04, 4.9993155373) = (exp(-0.002) - exp(-0.24996578)) / 0.05
CCR_A4_SUPERVISORY_DURATION: float = 4.3834912427  # full precision; E = 1826/365.25
CCR_A4_ADJUSTED_NOTIONAL: float = 438_349_124.271  # d = 100m × SD

CCR_A4_SF_IDX_IG: float = 0.0038  # CRR Art. 280 Table 2: credit index IG
CCR_A4_RHO_IDX: float = 0.80  # CRR Art. 280a: credit index correlation

# AddOn = SF × |EN|; single entity collapses to SF × adj_notional × MF.
CCR_A4_ADDON_AGGREGATE: float = 1_665_726.672  # CRR Art. 277a (full precision)
CCR_A4_RC_UNMARGINED: float = 0.0  # CRR Art. 275(1): max(V - C, 0) = max(0, 0) = 0
CCR_A4_PFE_MULTIPLIER: float = 1.0  # CRR Art. 278(3): at-par (V=0, C=0) → 1.0
CCR_A4_PFE_ADDON: float = 1_665_726.672  # multiplier × addon_aggregate (full precision)
CCR_A4_EAD: float = 2_332_017.341  # 1.4 × (RC + PFE)  — CRR Art. 274(2) (full precision)

# CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight.
CCR_A4_RISK_WEIGHT: float = 0.50
CCR_A4_RWA: float = 1_166_008.670  # EAD × RW (full precision)


# ---------------------------------------------------------------------------
# CCR-A4 trade + netting-set builders.
# ---------------------------------------------------------------------------


def _ccr_a4_trade() -> Trade:
    """Return the single CCR-A4 credit-index CDS trade instance."""
    return make_credit_trade(
        trade_id=TRADE_ID,
        netting_set_id=NETTING_SET_ID,
        asset_class=CCR_A4_ASSET_CLASS,
        transaction_type=CCR_A4_TRANSACTION_TYPE,
        notional=CCR_A4_NOTIONAL,
        currency=CCR_A4_CURRENCY,
        maturity_date=CCR_A4_MATURITY_DATE,
        start_date=CCR_A4_START_DATE,
        delta=CCR_A4_DELTA,
        is_long=CCR_A4_IS_LONG,
        mtm_value=CCR_A4_MTM,
        reference_entity=CCR_A4_REFERENCE_ENTITY,
        is_index=CCR_A4_IS_INDEX,
        credit_quality=CCR_A4_CREDIT_QUALITY,
    )


def _ccr_a4_netting_set() -> NettingSet:
    """Return the single CCR-A4 netting-set instance."""
    return NettingSet(
        netting_set_id=NETTING_SET_ID,
        counterparty_reference=COUNTERPARTY_REF,
        is_legally_enforceable=CCR_A4_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_A4_IS_MARGINED,
    )


def create_ccr_a4_trades() -> pl.DataFrame:
    """Return the single-row trades DataFrame for CCR-A4."""
    return create_trades([_ccr_a4_trade()])


def create_ccr_a4_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CCR-A4."""
    return create_netting_sets([_ccr_a4_netting_set()])


def create_ccr_a4_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-A4: no collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


def _build_ccr_a4_raw_ccr_bundle() -> RawCCRBundle:
    """Assemble the RawCCRBundle from the four CCR-A4 domain frames."""
    return RawCCRBundle(
        trades=TradeBundle(trades=create_ccr_a4_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_ccr_a4_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_ccr_a1_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_ccr_a4_collateral().lazy()),
    )


def build_ccr_a4_bundle() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle with CCR-A4 (credit-index CDS) populated.

    Reuses CP_001 (institution, CQS 2, GB) from the CCR-A1 portfolio stub so
    the SA Institution lookup ends in CRR Art. 120(1) Table 3 → 50% RW.
    No FX rates table needed (GBP trade, no cross-currency leg).

    The critical distinction from build_raw_data_bundle_with_ccr_a3() is the
    single trade having is_index=True (credit index) instead of False
    (single-name), which routes the engine to SF_IDX_IG=0.0038 and rho=0.80
    rather than SF_SN_IG=0.0046 and rho=0.50.
    """
    return make_raw_bundle(
        counterparties=_build_cp_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_001_rating(),
        ccr=_build_ccr_a4_raw_ccr_bundle(),
    )


# Alias matching the naming pattern of build_raw_data_bundle_with_ccr_a3.
build_raw_data_bundle_with_ccr_a4 = build_ccr_a4_bundle


# ---------------------------------------------------------------------------
# Save helper — canonical entry point for generate_all.py and standalone use.
# ---------------------------------------------------------------------------


def save_ccr_a4_fixtures(out_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all four CCR-A4 golden parquet files to *out_dir*.

    Files produced:
        ccr_a4_trades.parquet            — 1 row  (T_CR_002, 5y GBP credit-index CDS)
        ccr_a4_netting_sets.parquet      — 1 row  (NS_CR_002, CP_001, enforceable, unmargined)
        ccr_a4_margin_agreements.parquet — 0 rows (CCR-A4: no CSA)
        ccr_a4_ccr_collateral.parquet    — 0 rows (CCR-A4: no collateral)

    Uses ``ccr_a4_`` prefix on filenames to avoid overwriting CCR-A3 parquets in
    the shared ``tests/fixtures/ccr/`` directory.

    Args:
        out_dir: Target directory. Defaults to the directory containing
            this script (``tests/fixtures/ccr/``).

    Returns:
        Dict mapping artefact name to saved absolute ``Path``.
    """
    if out_dir is None:
        out_dir = Path(__file__).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("ccr_a4_trades", create_ccr_a4_trades()),
        ("ccr_a4_netting_sets", create_ccr_a4_netting_sets()),
        ("ccr_a4_margin_agreements", create_ccr_a1_margin_agreements()),
        ("ccr_a4_ccr_collateral", create_ccr_a4_collateral()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = out_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_ccr_a4_fixtures()
    print("CCR-A4 golden fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<35} {len(df):>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
    print("-" * 70)
    print("Scenario: CCR-A4 — single 5y GBP credit-index IG CDS, unmargined, no collateral")
    print(
        f"  Trade:       {TRADE_ID} (asset_class={CCR_A4_ASSET_CLASS!r},"
        f" notional={CCR_A4_NOTIONAL:,.0f} {CCR_A4_CURRENCY})"
    )
    print(f"  Reference entity: {CCR_A4_REFERENCE_ENTITY}, is_index={CCR_A4_IS_INDEX}")
    print(
        f"  Netting set: {NETTING_SET_ID} -> {COUNTERPARTY_REF}"
        f" (enforceable={CCR_A4_IS_LEGALLY_ENFORCEABLE},"
        f" margined={CCR_A4_IS_MARGINED})"
    )
    print("  Margin agreements: 0 rows (unmargined CCR-A4)")
    print("  CCR collateral:    0 rows (no posted/received collateral)")
    print()
    print("Expected outputs (tolerance rel=1e-6):")
    print(f"  addon_aggregate : {CCR_A4_ADDON_AGGREGATE:,.3f}")
    print(f"  ead_ccr         : {CCR_A4_EAD:,.3f}")
    print(f"  risk_weight     : {CCR_A4_RISK_WEIGHT:.2f}")
    print(f"  rwa_final       : {CCR_A4_RWA:,.3f}")


if __name__ == "__main__":
    main()
