"""
Golden CCR-A3 scenario: single 5-year GBP single-name IG CDS, unmargined.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/)
    -> engine-implementer (SA-CCR credit branch: adjusted notional + PFE add-on)

Scenario design:
    One trade (T_CR_001): 5-year GBP single-name investment-grade CDS.
        notional: GBP 100m
        reference_entity: "ACME_LEI_5493001A" (single-name LEI)
        credit_quality: "IG" (investment-grade)
        is_index: False (single-name — not a credit index)
        MtM = 0.0 (at-par at the reporting date), delta = 1.0 (long protection).
    One netting set (NS_CR_001): counterparty CP_001 (institution, CQS 2, GB),
        legally enforceable (Art. 295), unmargined (CCR-A3 scope).

Regulatory hand-calc (CRR Art. 279b(1)(a) + Art. 277a + Art. 280a + Art. 274):

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

    SF_CR (single-name IG) = 0.0046                    (Art. 280 Table 2)
    rho   (single-name)    = 0.50                       (Art. 280a)

    AddOn_entity = SF_CR × EN = 0.0046 × 438,349,124.271 = 2,016,405.972

    For a single-entity netting set:
        systematic    = (rho × AddOn_entity)^2 = (0.50 × 2,016,405.972)^2
        idiosyncratic = (1 − rho^2) × AddOn_entity^2
                      = 0.75 × 2,016,405.972^2
        AddOn_credit_HS = sqrt(systematic + idiosyncratic) = 2,016,405.972
        (single-entity collapses to |SF × EN| — the multi-entity test is
         load-bearing for two entities in one hedging set)

    RC  = max(V - C, 0) = max(0 - 0, 0) = 0              (Art. 275(1))
    PFE multiplier = 1.0  (at-par, V=0, C=0)              (Art. 278(3))
    PFE_addon      = 1.0 × 2,016,405.972 = 2,016,405.972  (Art. 278(1))
    EAD            = 1.4 × (0 + 2,016,405.972)            (Art. 274(2))
                   ≈ 2,822,968.360 GBP
    RW (institution CQS-2) = 0.50                          (Art. 120(1) Table 3)
    RWA = 2,822,968.360 × 0.50 = 1,411,484.180 GBP

Counterparty reuse:
    CCR-A3 reuses the CCR-A1 institution counterparty (CP_001, GB, CQS 2) and
    its external rating row so the SA Institution lookup ends in 50% RW.

References:
    - CRR Art. 271 (CCR scope)
    - CRR Art. 274(2) (EAD = alpha × (RC + PFE), alpha = 1.4)
    - CRR Art. 275(1) (unmargined RC = max(V - C, 0))
    - CRR Art. 277(2)(c) (one credit hedging set per netting set)
    - CRR Art. 277a(1) (add-on aggregation within credit HS)
    - CRR Art. 278 (PFE multiplier + PFE add-on composition)
    - CRR Art. 279b(1)(a) (credit/IR adjusted notional via supervisory duration)
    - CRR Art. 279c(1) (unmargined MF = sqrt(min(M, 1y) / 1y))
    - CRR Art. 280 Table 2 (SF_CR_SN_IG = 0.0046)
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
# Scenario constants — single source of truth for CCR-A3 test assertions.
# ---------------------------------------------------------------------------

TRADE_ID: str = "T_CR_001"
NETTING_SET_ID: str = "NS_CR_001"
COUNTERPARTY_REF: str = "CP_001"  # reuse CCR-A1 institution CP

CCR_A3_ASSET_CLASS: str = "credit"
CCR_A3_TRANSACTION_TYPE: str = "derivative"

CCR_A3_NOTIONAL: float = 100_000_000.0
CCR_A3_CURRENCY: str = "GBP"

# 5-year tenor: 2026-01-15 start, 2031-01-15 maturity.
CCR_A3_START_DATE: _date = _date(2026, 1, 15)
CCR_A3_MATURITY_DATE: _date = _date(2031, 1, 15)

CCR_A3_MTM: float = 0.0
CCR_A3_DELTA: float = 1.0
CCR_A3_IS_LONG: bool = True

CCR_A3_REFERENCE_ENTITY: str = "ACME_LEI_5493001A"
CCR_A3_IS_INDEX: bool = False
CCR_A3_CREDIT_QUALITY: str = "IG"

CCR_A3_IS_LEGALLY_ENFORCEABLE: bool = True
CCR_A3_IS_MARGINED: bool = False

# ---------------------------------------------------------------------------
# Hand-calc expected outputs (tolerance rel=1e-6 in acceptance tests).
# ---------------------------------------------------------------------------

# CRR Art. 279b(1)(a): SD(0.04, 4.9993155373) = (exp(-0.002) - exp(-0.24996578)) / 0.05
CCR_A3_SUPERVISORY_DURATION: float = 4.3834912427  # full precision; E = 1826/365.25
CCR_A3_ADJUSTED_NOTIONAL: float = 438_349_124.271  # d = 100m × SD

CCR_A3_SF_SN_IG: float = 0.0046  # CRR Art. 280 Table 2: single-name IG
CCR_A3_RHO_SN: float = 0.50  # CRR Art. 280a: single-name correlation

# AddOn = SF × |EN|; for single entity collapses to SF × adj_notional × MF.
CCR_A3_ADDON_AGGREGATE: float = 2_016_405.972  # CRR Art. 277a (full precision)
CCR_A3_RC_UNMARGINED: float = 0.0  # CRR Art. 275(1): max(V - C, 0) = max(0, 0) = 0
CCR_A3_PFE_MULTIPLIER: float = 1.0  # CRR Art. 278(3): at-par (V=0, C=0) → 1.0
CCR_A3_PFE_ADDON: float = 2_016_405.972  # multiplier × addon_aggregate (full precision)
CCR_A3_EAD: float = 2_822_968.360  # 1.4 × (RC + PFE)  — CRR Art. 274(2) (full precision)

# CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight.
CCR_A3_RISK_WEIGHT: float = 0.50
CCR_A3_RWA: float = 1_411_484.180  # EAD × RW (full precision)


# ---------------------------------------------------------------------------
# CCR-A3 trade + netting-set builders.
# ---------------------------------------------------------------------------


def _ccr_a3_trade() -> Trade:
    """Return the single CCR-A3 credit-CDS trade instance."""
    return make_credit_trade(
        trade_id=TRADE_ID,
        netting_set_id=NETTING_SET_ID,
        asset_class=CCR_A3_ASSET_CLASS,
        transaction_type=CCR_A3_TRANSACTION_TYPE,
        notional=CCR_A3_NOTIONAL,
        currency=CCR_A3_CURRENCY,
        maturity_date=CCR_A3_MATURITY_DATE,
        start_date=CCR_A3_START_DATE,
        delta=CCR_A3_DELTA,
        is_long=CCR_A3_IS_LONG,
        mtm_value=CCR_A3_MTM,
        reference_entity=CCR_A3_REFERENCE_ENTITY,
        is_index=CCR_A3_IS_INDEX,
        credit_quality=CCR_A3_CREDIT_QUALITY,
    )


def _ccr_a3_netting_set() -> NettingSet:
    """Return the single CCR-A3 netting-set instance."""
    return NettingSet(
        netting_set_id=NETTING_SET_ID,
        counterparty_reference=COUNTERPARTY_REF,
        is_legally_enforceable=CCR_A3_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_A3_IS_MARGINED,
    )


def create_ccr_a3_trades() -> pl.DataFrame:
    """Return the single-row trades DataFrame for CCR-A3."""
    return create_trades([_ccr_a3_trade()])


def create_ccr_a3_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CCR-A3."""
    return create_netting_sets([_ccr_a3_netting_set()])


def create_ccr_a3_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-A3: no collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


def _build_ccr_a3_raw_ccr_bundle() -> RawCCRBundle:
    """Assemble the RawCCRBundle from the four CCR-A3 domain frames."""
    return RawCCRBundle(
        trades=TradeBundle(trades=create_ccr_a3_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_ccr_a3_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_ccr_a1_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_ccr_a3_collateral().lazy()),
    )


def build_raw_data_bundle_with_ccr_a3() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle with CCR-A3 (credit CDS) populated.

    Reuses CP_001 (institution, CQS 2, GB) from the CCR-A1 portfolio stub so
    the SA Institution lookup ends in CRR Art. 120(1) Table 3 → 50% RW.
    No FX rates table needed (GBP trade, no cross-currency leg).
    """
    return make_raw_bundle(
        counterparties=_build_cp_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_001_rating(),
        ccr=_build_ccr_a3_raw_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Save helper — canonical entry point for generate_all.py and standalone use.
# ---------------------------------------------------------------------------


def save_ccr_a3_fixtures(out_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all four CCR-A3 golden parquet files to *out_dir*.

    Files produced:
        ccr_a3_trades.parquet           — 1 row  (T_CR_001, 5y GBP CDS)
        ccr_a3_netting_sets.parquet     — 1 row  (NS_CR_001, CP_001, enforceable, unmargined)
        ccr_a3_margin_agreements.parquet — 0 rows (CCR-A3: no CSA)
        ccr_a3_ccr_collateral.parquet   — 0 rows (CCR-A3: no collateral)

    Uses ``ccr_a3_`` prefix on filenames to avoid overwriting CCR-A1 parquets in
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
        ("ccr_a3_trades", create_ccr_a3_trades()),
        ("ccr_a3_netting_sets", create_ccr_a3_netting_sets()),
        ("ccr_a3_margin_agreements", create_ccr_a1_margin_agreements()),
        ("ccr_a3_ccr_collateral", create_ccr_a3_collateral()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = out_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_ccr_a3_fixtures()
    print("CCR-A3 golden fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<35} {len(df):>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
    print("-" * 70)
    print("Scenario: CCR-A3 — single 5y GBP single-name IG CDS, unmargined, no collateral")
    print(
        f"  Trade:       {TRADE_ID} (asset_class={CCR_A3_ASSET_CLASS!r},"
        f" notional={CCR_A3_NOTIONAL:,.0f} {CCR_A3_CURRENCY})"
    )
    print(f"  Reference entity: {CCR_A3_REFERENCE_ENTITY}, is_index={CCR_A3_IS_INDEX}")
    print(
        f"  Netting set: {NETTING_SET_ID} -> {COUNTERPARTY_REF}"
        f" (enforceable={CCR_A3_IS_LEGALLY_ENFORCEABLE},"
        f" margined={CCR_A3_IS_MARGINED})"
    )
    print("  Margin agreements: 0 rows (unmargined CCR-A3)")
    print("  CCR collateral:    0 rows (no posted/received collateral)")
    print()
    print("Expected outputs (tolerance rel=1e-6):")
    print(f"  addon_aggregate : {CCR_A3_ADDON_AGGREGATE:,.3f}")
    print(f"  ead_ccr         : {CCR_A3_EAD:,.3f}")
    print(f"  risk_weight     : {CCR_A3_RISK_WEIGHT:.2f}")
    print(f"  rwa_final       : {CCR_A3_RWA:,.3f}")


if __name__ == "__main__":
    main()
