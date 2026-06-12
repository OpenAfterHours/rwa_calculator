"""
P8.39 fixture: orchestrator-ready CCP wiring — CCR-CCP-1 / CCR-CCP-2.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_ccp_wiring.py)
    -> engine-implementer (engine/ccr/ccp.py wired into pipeline.py _run_ccr_stage)

Scenario design:
    Two acceptance scenarios sharing identical trade economics and differing only
    in ``is_client_cleared``.  The counterparty is CP-QCCP-LCH (entity_type="ccp",
    institution_cqs=2, is_qccp=True).

    | Scenario   | is_client_cleared | rw   | RWA                       |
    |------------|-------------------|------|---------------------------|
    | CCR-CCP-1  | False             | 2%   | QCCP_EAD * 0.02           |
    | CCR-CCP-2  | True              | 4%   | QCCP_EAD * 0.04           |

    Anti-degenerate baseline (without P8.39 wiring):
        institution_cqs=2 → CRR Art. 120(1) Table 3 → 50% SA RW.
        Degenerate RWA = QCCP_EAD * 0.50 = 2_375_044.163...
        Over-statement: 25× (CCR-CCP-1), 12.5× (CCR-CCP-2).

    Load-bearing assertions for test-writer:
        risk_weight == 0.02 (CCR-CCP-1), 0.04 (CCR-CCP-2)  — exact equality.
        risk_weight != 0.50  — keyed QCCP override displaced the SA fallback.
        EAD == QCCP_EAD (rel=1e-9)  — EAD not mutated by ccp.py.
        RWA == QCCP_EAD * rw (rel=1e-9).

Hand-calculated EAD (Art. 274(2), alpha=1.4, identical both scenarios):
    V  = 2_000_000;  C = 0
    RC = max(V - C, 0) = 2_000_000
    d  = 100_000_000 * (exp(-0.05*0) - exp(-0.05*3)) / 0.05 ≈ 278_584_046.59
    AddOn_IR = 0.005 * 278_584_046.59 ≈ 1_392_920.23...
    PFE = 1.0 * 1_392_920.23...   (multiplier = 1, V > 0, C = 0)
    EAD = 1.4 * (2_000_000 + 1_392_920.23...) ≈ 4_750_088.326134375

    See qccp_builder.QCCP_EAD for the authoritative constant (do NOT redefine here).

Keyed-join note:
    A single-trade / single-NS book (1 QCCP counterparty) passes under either a
    cross-join or a keyed join in apply_ccp_risk_weight, so does NOT regression-guard
    the fan-out bug.  The supplementary 2-counterparty book below
    (build_p839_two_counterparty_book) provides that regression guard.

    See proposal §5 and ``build_p839_two_counterparty_book`` below.

Exported public names
---------------------
    P839_CP_QCCP_REF         : str — "CP-QCCP-LCH" (QCCP counterparty)
    P839_CP_NON_QCCP_REF     : str — "CP-NON-QCCP-01" (non-QCCP, for 2-CP book)
    P839_ANTI_DEGENERATE_RW  : float — 0.50 (CQS-2 SA institution fallback)
    P839_RWA_ANTI_DEGENERATE : float — QCCP_EAD * 0.50

    build_p839_bundle(is_client_cleared) -> RawDataBundle
        Full orchestrator-ready bundle for PipelineOrchestrator.run_with_data.
        CCR-CCP-1: build_p839_bundle(is_client_cleared=False)
        CCR-CCP-2: build_p839_bundle(is_client_cleared=True)

    build_p839_two_counterparty_book() -> RawDataBundle
        2-counterparty, 2-NS, 2-trade bundle for keyed-join regression testing.
        One QCCP (CP-QCCP-LCH, is_qccp=True) + one non-QCCP (CP-NON-QCCP-01,
        is_qccp=False).  Both trades are NOT client-cleared.  Expected RWs:
        QCCP row → 0.02; non-QCCP row → NULL (SA fallback at CQS-2 = 50%).
        A cross-join fan-out would produce 4 rows instead of 2 — use this
        to pin the keyed-join invariant.

    save_p839_fixtures() -> list[tuple[str, int]]
        Smoke-check entry point called by generate_all.py.

References:
    - CRR Art. 306(1)(a) — 2% RW for proprietary QCCP trade exposures
    - CRR Art. 306(1)(c) — 4% RW for client-cleared QCCP trade exposures
    - CRR Art. 306(4) — RWA = Σ EAD × RW
    - CRR Art. 272 Def (88) — QCCP definition
    - CRR Art. 120(1) Table 3 — institution CQS 2 → 50% SA RW
    - BCBS CRE54.14 — 2% supervisory factor
    - BCBS CRE54.15 — 4% supervisory factor
    - tests/fixtures/ccr/qccp_builder.py — canonical EAD + RW constants (reused here)
"""

from __future__ import annotations

from typing import Any

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
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from .margin_builder import create_margin_agreements
from .netting_set_builder import create_netting_sets, make_netting_set
from .qccp_builder import (
    QCCP_ASSET_CLASS,
    QCCP_CP_REF,
    QCCP_CURRENCY,
    QCCP_DELTA,
    QCCP_EAD,
    QCCP_ENTITY_TYPE,
    QCCP_INSTITUTION_CQS,
    QCCP_IS_LEGALLY_ENFORCEABLE,
    QCCP_IS_LONG,
    QCCP_IS_MARGINED,
    QCCP_MATURITY_DATE,
    QCCP_MTM_VALUE,
    QCCP_NOTIONAL,
    QCCP_NS_ID,
    QCCP_RW_CLIENT_CLEARED,
    QCCP_RW_PROPRIETARY,
    QCCP_RWA_CLIENT_CLEARED,
    QCCP_RWA_PROPRIETARY,
    QCCP_START_DATE,
    QCCP_TRADE_ID,
    QCCP_TRANSACTION_TYPE,
)
from .trade_builder import create_trades, make_trade

# ---------------------------------------------------------------------------
# P8.39-specific constants.
# All trade economics (QCCP_EAD, QCCP_NOTIONAL, etc.) are imported from
# qccp_builder — do NOT redefine here; that builder is the single source of
# truth for the common scenario inputs.
# ---------------------------------------------------------------------------

#: QCCP counterparty reference — same as in qccp_builder.
P839_CP_QCCP_REF: str = QCCP_CP_REF  # "CP-QCCP-LCH"

#: Non-QCCP counterparty reference (only needed for 2-counterparty regression book).
P839_CP_NON_QCCP_REF: str = "CP-NON-QCCP-01"

#: Non-QCCP netting set identifier (2-counterparty book only).
P839_NS_NON_QCCP_ID: str = "NS-NON-QCCP-01"

#: Non-QCCP trade identifier (2-counterparty book only).
P839_TRADE_NON_QCCP_ID: str = "T-NON-QCCP-01"

#: Anti-degenerate SA fallback RW — what the engine would apply if ccp.py is
#: never wired.  CQS-2 → 50% per CRR Art. 120(1) Table 3.
P839_ANTI_DEGENERATE_RW: float = 0.50

#: Anti-degenerate RWA baseline for CCR-CCP-1 (proprietary, no wiring).
P839_RWA_ANTI_DEGENERATE: float = QCCP_EAD * P839_ANTI_DEGENERATE_RW

# Re-export the primary scenario constants so test-writer can import from
# this single module without chasing qccp_builder separately.
P839_EAD: float = QCCP_EAD
P839_RW_PROPRIETARY: float = QCCP_RW_PROPRIETARY  # 0.02 — CCR-CCP-1
P839_RW_CLIENT_CLEARED: float = QCCP_RW_CLIENT_CLEARED  # 0.04 — CCR-CCP-2
P839_RWA_PROPRIETARY: float = QCCP_RWA_PROPRIETARY  # EAD * 0.02
P839_RWA_CLIENT_CLEARED: float = QCCP_RWA_CLIENT_CLEARED  # EAD * 0.04


# ---------------------------------------------------------------------------
# Private helpers — single-counterparty book (CCR-CCP-1 / CCR-CCP-2).
# ---------------------------------------------------------------------------


def _build_qccp_counterparty(is_qccp: bool, cp_ref: str = P839_CP_QCCP_REF) -> pl.DataFrame:
    """
    Return a single-row counterparty DataFrame for a QCCP or non-QCCP entity.

    institution_cqs=QCCP_INSTITUTION_CQS (2) is the load-bearing value: the
    anti-degenerate SA-Institution weight is 50% (CRR Art. 120(1) Table 3 CQS 2).
    The ``is_qccp`` column is appended via ``with_columns`` since it is an
    engine-side schema addition; the base COUNTERPARTY_SCHEMA row is typed
    via ``dtypes_of``.
    """
    row: dict[str, Any] = {
        "counterparty_reference": cp_ref,
        "counterparty_name": f"{'LCH Ltd (QCCP)' if is_qccp else 'Non-QCCP Institution'}",
        "entity_type": QCCP_ENTITY_TYPE,  # "ccp"
        "country_code": "GB",
        "annual_revenue": None,
        "total_assets": None,
        "default_status": False,
        "sector_code": "66.11",
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": QCCP_INSTITUTION_CQS,  # 2 — load-bearing
    }
    base = pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA))
    return base.with_columns(pl.lit(is_qccp).alias("is_qccp"))


def _build_trade(
    trade_id: str,
    netting_set_id: str,
    is_client_cleared: bool,
) -> pl.DataFrame:
    """
    Return a single-row trades DataFrame.

    All economic terms are shared with the P8.25 qccp_builder constants.
    ``is_client_cleared`` is appended via ``with_columns`` (same pattern as
    qccp_builder.create_qccp_trades).
    """
    trade = make_trade(
        trade_id=trade_id,
        netting_set_id=netting_set_id,
        asset_class=QCCP_ASSET_CLASS,
        transaction_type=QCCP_TRANSACTION_TYPE,
        notional=QCCP_NOTIONAL,
        currency=QCCP_CURRENCY,
        maturity_date=QCCP_MATURITY_DATE,
        start_date=QCCP_START_DATE,
        delta=QCCP_DELTA,
        is_long=QCCP_IS_LONG,
        mtm_value=QCCP_MTM_VALUE,
    )
    base = create_trades([trade])
    return base.with_columns(pl.lit(is_client_cleared).alias("is_client_cleared"))


def _build_netting_set(netting_set_id: str, cp_ref: str) -> pl.DataFrame:
    """Return a single-row netting-sets DataFrame (unmargined, legally enforceable)."""
    ns = make_netting_set(
        netting_set_id=netting_set_id,
        counterparty_reference=cp_ref,
        is_legally_enforceable=QCCP_IS_LEGALLY_ENFORCEABLE,
        is_margined=QCCP_IS_MARGINED,
    )
    return create_netting_sets([ns])


def _build_empty_ccr_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


def _build_raw_ccr_bundle(trades_df: pl.DataFrame, netting_sets_df: pl.DataFrame) -> RawCCRBundle:
    """Wrap DataFrames into a RawCCRBundle with empty margin and collateral frames."""
    return RawCCRBundle(
        trades=TradeBundle(trades=trades_df.lazy()),
        netting_sets=NettingSetBundle(netting_sets=netting_sets_df.lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_margin_agreements([]).lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=_build_empty_ccr_collateral().lazy()),
    )


def _build_empty_lending_frames() -> tuple[pl.LazyFrame, pl.LazyFrame, pl.LazyFrame, pl.LazyFrame]:
    """Return zero-row facilities/loans/facility_mappings/lending_mappings LazyFrames."""
    return (
        pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA)),
        pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
    )


# ---------------------------------------------------------------------------
# Public bundle factories.
# ---------------------------------------------------------------------------


def build_p839_bundle(is_client_cleared: bool) -> RawDataBundle:
    """
    Build a complete orchestrator-ready RawDataBundle for CCR-CCP-1 or CCR-CCP-2.

    Both scenarios share:
    - Counterparty CP-QCCP-LCH: entity_type="ccp", is_qccp=True, institution_cqs=2.
    - Trade T-QCCP-01 in NS-QCCP-01: GBP 100m IR derivative, unmargined.
    - EAD = 4_750_088.326134375 (SA-CCR Art. 274(2)).

    Scenarios differ only in ``is_client_cleared`` on the trade row:
    - CCR-CCP-1 (is_client_cleared=False): risk_weight=0.02, RWA=EAD*0.02
    - CCR-CCP-2 (is_client_cleared=True):  risk_weight=0.04, RWA=EAD*0.04

    Without P8.39 wiring both rows degenerate to the SA-Institution ladder:
    CQS-2 → 50% → RWA = 2_375_044.163...  (25× / 12.5× over-statement).

    Usage::

        from tests.fixtures.ccr.p839_ccp_builder import build_p839_bundle
        # CCR-CCP-1: proprietary QCCP
        data_ccp1 = build_p839_bundle(is_client_cleared=False)
        # CCR-CCP-2: client-cleared QCCP
        data_ccp2 = build_p839_bundle(is_client_cleared=True)
        result = pipeline_orchestrator.run_with_data(data_ccp1, config)

    References:
        - CRR Art. 306(1)(a)/(c) — 2%/4% QCCP trade exposure RW
        - CRR Art. 120(1) Table 3 — institution CQS 2 → 50% SA fallback
    """
    counterparty_df = _build_qccp_counterparty(is_qccp=True)
    trades_df = _build_trade(QCCP_TRADE_ID, QCCP_NS_ID, is_client_cleared=is_client_cleared)
    netting_sets_df = _build_netting_set(QCCP_NS_ID, QCCP_CP_REF)

    facilities, loans, facility_mappings, lending_mappings = _build_empty_lending_frames()

    return make_raw_bundle(
        counterparties=counterparty_df.lazy(),
        facilities=facilities,
        loans=loans,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        ratings=pl.LazyFrame(schema=dtypes_of(RATINGS_SCHEMA)),
        ccr=_build_raw_ccr_bundle(trades_df, netting_sets_df),
    )


def build_p839_two_counterparty_book() -> RawDataBundle:
    """
    Build a 2-counterparty, 2-NS, 2-trade bundle for keyed-join regression testing.

    Purpose:
        A single-trade / single-NS fixture (1×1×1) passes under either a cross-join
        or a keyed join in ``apply_ccp_risk_weight``.  This 2-counterparty book has
        two counterparties, two netting sets, and two trades so that a cross-join
        fan-out would produce 4 rows instead of 2.  Test-writer can assert:
            result.height == 2
        to pin the keyed-join invariant.

    Composition:
        CP-QCCP-LCH   (is_qccp=True,  institution_cqs=2) — NS-QCCP-01 — T-QCCP-01
        CP-NON-QCCP-01(is_qccp=False, institution_cqs=2) — NS-NON-QCCP-01 — T-NON-QCCP-01

    Both trades are NOT client-cleared (is_client_cleared=False).

    Expected per-row risk_weight after apply_ccp_risk_weight:
        NS-QCCP-01:     risk_weight = 0.02  (QCCP proprietary)
        NS-NON-QCCP-01: risk_weight = NULL  (non-QCCP pass-through → SA fallback 50%)

    References:
        - CRR Art. 306(1)(a) — 2% for NS-QCCP-01
        - CRR Art. 107(2)(a) — SA-institution routing for NS-NON-QCCP-01
        - CRR Art. 120(1) Table 3 — 50% fallback for CQS-2 non-QCCP
    """
    # Two counterparties: one QCCP, one non-QCCP.
    qccp_cp = _build_qccp_counterparty(is_qccp=True, cp_ref=P839_CP_QCCP_REF)
    non_qccp_cp = _build_qccp_counterparty(is_qccp=False, cp_ref=P839_CP_NON_QCCP_REF)
    counterparties_df = pl.concat([qccp_cp, non_qccp_cp])

    # Two trades, one per netting set, both proprietary (not client-cleared).
    qccp_trade = _build_trade(QCCP_TRADE_ID, QCCP_NS_ID, is_client_cleared=False)
    non_qccp_trade = _build_trade(
        P839_TRADE_NON_QCCP_ID, P839_NS_NON_QCCP_ID, is_client_cleared=False
    )
    trades_df = pl.concat([qccp_trade, non_qccp_trade])

    # Two netting sets.
    qccp_ns = _build_netting_set(QCCP_NS_ID, P839_CP_QCCP_REF)
    non_qccp_ns = _build_netting_set(P839_NS_NON_QCCP_ID, P839_CP_NON_QCCP_REF)
    netting_sets_df = pl.concat([qccp_ns, non_qccp_ns])

    facilities, loans, facility_mappings, lending_mappings = _build_empty_lending_frames()

    return make_raw_bundle(
        counterparties=counterparties_df.lazy(),
        facilities=facilities,
        loans=loans,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        ratings=pl.LazyFrame(schema=dtypes_of(RATINGS_SCHEMA)),
        ccr=_build_raw_ccr_bundle(trades_df, netting_sets_df),
    )


# ---------------------------------------------------------------------------
# Smoke-check entry point — called by generate_all.py.
# ---------------------------------------------------------------------------


def save_p839_fixtures() -> list[tuple[str, int]]:
    """
    Smoke-check both P8.39 bundles and return a generation report.

    No parquet files are written — this is a Python-only builder (same pattern
    as P8.53 / ccr_wwr1_builder.py).  Validates all load-bearing invariants
    listed below; raises ``AssertionError`` with a descriptive message if any
    is violated.

    Invariants checked (single-counterparty bundles):
        1.  CCR-CCP-1 bundle: ccr not None.
        2.  CCR-CCP-1: 1 trade row; trade_id == QCCP_TRADE_ID.
        3.  CCR-CCP-1: is_client_cleared == False on the trade.
        4.  CCR-CCP-1: 1 netting-set row; netting_set_id == QCCP_NS_ID.
        5.  CCR-CCP-1: counterparty is_qccp == True; institution_cqs == QCCP_INSTITUTION_CQS.
        6.  CCR-CCP-2: is_client_cleared == True on the trade.
        7.  CCR-CCP-2: all other invariants identical to CCR-CCP-1.

    Invariants checked (2-counterparty book):
        8.  2 counterparty rows (CP-QCCP-LCH + CP-NON-QCCP-01).
        9.  2 trade rows; 2 netting-set rows.
        10. is_qccp == True for CP-QCCP-LCH; False for CP-NON-QCCP-01.
        11. 0 margin-agreement rows; 0 CCR-collateral rows.

    Returns:
        ``[("(python-only builder — no parquet)", 0)]``
    """
    # --- CCR-CCP-1 ---
    b_ccp1 = build_p839_bundle(is_client_cleared=False)
    _check_p839_single(b_ccp1, scenario="CCR-CCP-1", expected_client_cleared=False)

    # --- CCR-CCP-2 ---
    b_ccp2 = build_p839_bundle(is_client_cleared=True)
    _check_p839_single(b_ccp2, scenario="CCR-CCP-2", expected_client_cleared=True)

    # --- 2-counterparty regression book ---
    b2 = build_p839_two_counterparty_book()
    _check_p839_two_cp(b2)

    return [("(python-only builder — no parquet)", 0)]


def _check_p839_single(bundle: RawDataBundle, scenario: str, expected_client_cleared: bool) -> None:
    """Verify invariants for a single-counterparty P8.39 bundle."""
    if bundle.ccr is None:
        raise AssertionError(f"P8.39 {scenario}: bundle.ccr must not be None")

    trades_df = bundle.ccr.trades.trades.collect()
    ns_df = bundle.ccr.netting_sets.netting_sets.collect()
    margin_df = bundle.ccr.margin_agreements.margin_agreements.collect()
    coll_df = bundle.ccr.ccr_collateral.ccr_collateral.collect()
    cp_df = bundle.counterparties.collect()

    if trades_df.height != 1:
        raise AssertionError(f"P8.39 {scenario}: expected 1 trade row, got {trades_df.height}")
    if trades_df["trade_id"][0] != QCCP_TRADE_ID:
        raise AssertionError(
            f"P8.39 {scenario}: trade_id must be {QCCP_TRADE_ID!r} "
            f"(got {trades_df['trade_id'][0]!r})"
        )
    if "is_client_cleared" not in trades_df.columns:
        raise AssertionError(f"P8.39 {scenario}: is_client_cleared column must be present")
    if trades_df["is_client_cleared"][0] is not expected_client_cleared:
        raise AssertionError(
            f"P8.39 {scenario}: is_client_cleared must be {expected_client_cleared} "
            f"(got {trades_df['is_client_cleared'][0]!r})"
        )

    if ns_df.height != 1:
        raise AssertionError(f"P8.39 {scenario}: expected 1 NS row, got {ns_df.height}")
    if ns_df["netting_set_id"][0] != QCCP_NS_ID:
        raise AssertionError(
            f"P8.39 {scenario}: netting_set_id must be {QCCP_NS_ID!r} "
            f"(got {ns_df['netting_set_id'][0]!r})"
        )
    if ns_df["is_legally_enforceable"][0] is not True:
        raise AssertionError(f"P8.39 {scenario}: NS is_legally_enforceable must be True")
    if ns_df["is_margined"][0] is not False:
        raise AssertionError(f"P8.39 {scenario}: NS is_margined must be False")

    if cp_df.height != 1:
        raise AssertionError(f"P8.39 {scenario}: expected 1 counterparty row, got {cp_df.height}")
    if "is_qccp" not in cp_df.columns:
        raise AssertionError(f"P8.39 {scenario}: is_qccp column must be present on counterparty")
    if cp_df["is_qccp"][0] is not True:
        raise AssertionError(f"P8.39 {scenario}: counterparty is_qccp must be True")
    if cp_df["institution_cqs"][0] != QCCP_INSTITUTION_CQS:
        raise AssertionError(
            f"P8.39 {scenario}: institution_cqs must be {QCCP_INSTITUTION_CQS} "
            f"(got {cp_df['institution_cqs'][0]!r})"
        )

    if margin_df.height != 0:
        raise AssertionError(
            f"P8.39 {scenario}: margin_agreements must be empty (got {margin_df.height})"
        )
    if coll_df.height != 0:
        raise AssertionError(
            f"P8.39 {scenario}: ccr_collateral must be empty (got {coll_df.height})"
        )


def _check_p839_two_cp(bundle: RawDataBundle) -> None:
    """Verify invariants for the 2-counterparty regression book."""
    if bundle.ccr is None:
        raise AssertionError("P8.39 2-CP book: bundle.ccr must not be None")

    cp_df = bundle.counterparties.collect()
    trades_df = bundle.ccr.trades.trades.collect()
    ns_df = bundle.ccr.netting_sets.netting_sets.collect()
    margin_df = bundle.ccr.margin_agreements.margin_agreements.collect()
    coll_df = bundle.ccr.ccr_collateral.ccr_collateral.collect()

    if cp_df.height != 2:
        raise AssertionError(f"P8.39 2-CP book: expected 2 counterparty rows, got {cp_df.height}")
    cp_refs = cp_df["counterparty_reference"].to_list()
    for ref in [P839_CP_QCCP_REF, P839_CP_NON_QCCP_REF]:
        if ref not in cp_refs:
            raise AssertionError(f"P8.39 2-CP book: counterparty {ref!r} not found in {cp_refs}")

    if "is_qccp" not in cp_df.columns:
        raise AssertionError("P8.39 2-CP book: is_qccp column must be present on counterparties")
    qccp_row = cp_df.filter(pl.col("counterparty_reference") == P839_CP_QCCP_REF)
    if qccp_row["is_qccp"][0] is not True:
        raise AssertionError("P8.39 2-CP book: CP-QCCP-LCH is_qccp must be True")
    non_qccp_row = cp_df.filter(pl.col("counterparty_reference") == P839_CP_NON_QCCP_REF)
    if non_qccp_row["is_qccp"][0] is not False:
        raise AssertionError("P8.39 2-CP book: CP-NON-QCCP-01 is_qccp must be False")

    if trades_df.height != 2:
        raise AssertionError(f"P8.39 2-CP book: expected 2 trade rows, got {trades_df.height}")
    if ns_df.height != 2:
        raise AssertionError(f"P8.39 2-CP book: expected 2 netting-set rows, got {ns_df.height}")
    if margin_df.height != 0:
        raise AssertionError(
            f"P8.39 2-CP book: margin_agreements must be empty (got {margin_df.height})"
        )
    if coll_df.height != 0:
        raise AssertionError(
            f"P8.39 2-CP book: ccr_collateral must be empty (got {coll_df.height})"
        )

    # Cross-join regression guard: verify no duplicate netting-set IDs leaked in.
    ns_ids = ns_df["netting_set_id"].to_list()
    if len(ns_ids) != len(set(ns_ids)):
        raise AssertionError(
            f"P8.39 2-CP book: duplicate netting_set_id detected (cross-join fan-out?): {ns_ids}"
        )
