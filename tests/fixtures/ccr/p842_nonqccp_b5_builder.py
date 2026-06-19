"""
P8.42 / CCR-B5 fixture: non-QCCP CCP trade exposure at CQS-1 -> 20% institution RW.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_ccr_b1_b5_ccp.py)
    -> engine-implementer (engine/ccr/ccp.py + engine/sa/risk_weights.py)

Scenario design:
    One 10-year GBP interest-rate derivative (T-NONQCCP-B5, notional GBP 100m,
    MtM 0.0, delta 1.0) in a single unmargined netting set (NS-NONQCCP-B5) against
    counterparty CP-NONQCCP-B5.

    Trade economics are BYTE-IDENTICAL to CCR-A1 (same start/maturity dates,
    same notional, same MtM, same asset class).  The ONLY divergence is the
    counterparty: CP-NONQCCP-B5 is a CCP entity (entity_type="ccp") with
    is_qccp=False and institution_cqs=1.

    Because SA-CCR inputs are identical to CCR-A1, the EAD is also identical.
    The EAD is NOT transcribed as a constant here — it is loaded at test time
    from tests/expected_outputs/ccr/CCR-A1.json ("ead_final": 5_480_017.519).
    A future SA-CCR recalibration will update CCR-A1.json and automatically
    move both scenarios in lockstep.

    Risk-weight derivation (THE NEW PIN for CCR-B5):
        is_qccp = False  -> CRR Art. 306(1) NOT reached (2%/4% QCCP branch skipped)
        Art. 107(2)(a)   -> non-QCCP CCP demoted to institution SA ladder
        institution_cqs  = 1  -> CRR Art. 120(1) Table 3 CQS-1 -> RW = 0.20 (20%)
        RWA = EAD x 0.20

    Anti-degenerate guards (for test-writer):
        risk_weight == 0.20  (the new pin)
        risk_weight != 0.02  (QCCP proprietary — Art. 306(1)(a))
        risk_weight != 0.04  (QCCP client-cleared — Art. 306(1)(c))
        risk_weight != 0.50  (CQS-2 SA institution fallback — existing guard in p839 book)
        risk_weight != 0.40  (unrated institution fallback)
        risk_weight != 1.0   (corporate fallback)
        risk_weight != 12.5  (Art. 309 non-QCCP default-fund)

Counterparty attributes (CP-NONQCCP-B5):
    entity_type        = "ccp"    -> triggers ccp.py branch in CCR stage
    country_code       = "US"
    default_status     = False
    apply_fi_scalar    = False
    is_managed_as_retail = False
    institution_cqs    = 1        -> CRR Art. 120(1) Table 3: CQS-1 -> 20% RW
    is_qccp            = False    -> Art. 306 bypassed; Art. 107(2)(a) demotion fires

Trade / netting-set dates are aligned to CCR-A1 (CCR_A1_START_DATE / CCR_A1_MATURITY_DATE)
so the EAD invariant from CCR-A1.json holds exactly.

Module-level constants are the single source of truth for test-writer assertions.
No persistent parquet files are written — test-writer imports the builder function
``build_nonqccp_b5_bundle()`` directly.

References:
    - CRR Art. 107(2)(a) — non-QCCP CCP exposure treated as institution (SA)
    - CRR Art. 120(1) Table 3 — institution CQS-1 -> 20% SA risk weight
    - CRR Art. 272 Def (88) — QCCP definition (NOT met; is_qccp=False)
    - CRR Art. 274(2) — EAD = alpha*(RC + PFE), alpha=1.4
    - CRR Art. 275(1) — RC = max(V - C, 0) = 0.0 (MtM=0, no collateral)
    - CRR Art. 279b — PFE add-on (IR asset class, SF=0.5%)
    - tests/expected_outputs/ccr/CCR-A1.json — EAD invariant anchor (ead_final 5,480,017.519)
    - tests/fixtures/ccr/golden_ccr_a1.py — CCR-A1 trade economics (dates, notional, MtM)
    - tests/fixtures/ccr/qccp_builder.py::create_qccp_counterparty — is_qccp append pattern
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

from .golden_ccr_a1 import (
    CCR_A1_ASSET_CLASS,
    CCR_A1_CURRENCY,
    CCR_A1_DELTA,
    CCR_A1_IS_LEGALLY_ENFORCEABLE,
    CCR_A1_IS_LONG,
    CCR_A1_IS_MARGINED,
    CCR_A1_MATURITY_DATE,
    CCR_A1_MTM,
    CCR_A1_NOTIONAL,
    CCR_A1_START_DATE,
    CCR_A1_TRANSACTION_TYPE,
)
from .margin_builder import create_margin_agreements
from .netting_set_builder import create_netting_sets, make_netting_set
from .trade_builder import create_trades, make_trade

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

#: Trade identifier for CCR-B5.
NONQCCP_B5_TRADE_ID: str = "T-NONQCCP-B5"

#: Netting set identifier for CCR-B5.
NONQCCP_B5_NS_ID: str = "NS-NONQCCP-B5"

#: Counterparty reference for CCR-B5 (non-QCCP CCP at CQS-1).
NONQCCP_B5_CP_REF: str = "CP-NONQCCP-B5"

# --- Counterparty attributes ---

#: entity_type="ccp" routes the CCR-stage through the CCP branch (ccp.py).
NONQCCP_B5_ENTITY_TYPE: str = "ccp"

#: Country code for CP-NONQCCP-B5.
NONQCCP_B5_COUNTRY_CODE: str = "US"

#: institution_cqs=1 is the load-bearing value for CRR Art. 120(1) Table 3 CQS-1 -> 20% RW.
NONQCCP_B5_INSTITUTION_CQS: int = 1

#: is_qccp=False -> Art. 306(1) QCCP branch bypassed -> Art. 107(2)(a) demotion fires.
NONQCCP_B5_IS_QCCP: bool = False

# --- Trade economics: byte-identical to CCR-A1 so EAD == CCR-A1 golden. ---
# Trade dates, notional, MtM, delta, asset class, transaction type are imported
# directly from golden_ccr_a1. Do NOT redefine here — that module is the
# single source of truth for the economic terms.

# --- Expected risk weight (THE NEW PIN for CCR-B5) ---

#: CRR Art. 120(1) Table 3: institution CQS-1 -> 20% SA risk weight.
#: This is the only value that differs from CCR-A1 (which is CQS-2 -> 50%).
NONQCCP_B5_EXPECTED_RW: float = 0.20

# EAD is NOT a constant here — test-writer must load it from:
#   tests/expected_outputs/ccr/CCR-A1.json["ead_final"]  (= 5_480_017.519)
# and assert the CCR-B5 EAD against that loaded value (rel=1e-6).
# RWA is then asserted as EAD_loaded * NONQCCP_B5_EXPECTED_RW (rel=1e-9).


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_nonqccp_b5_counterparty() -> pl.DataFrame:
    """
    Return a single-row counterparty DataFrame for CP-NONQCCP-B5.

    Key attributes:
    - entity_type="ccp": routes through the CCP branch in the CCR stage.
    - is_qccp=False: Art. 306 QCCP branch skipped; Art. 107(2)(a) demotion fires.
    - institution_cqs=1: CRR Art. 120(1) Table 3 CQS-1 -> 20% SA risk weight.

    The ``is_qccp`` column is appended via ``with_columns`` because it is an
    engine-side schema addition not yet present in the canonical COUNTERPARTY_SCHEMA.
    This is the same pattern used by qccp_builder.create_qccp_counterparty and
    p839_ccp_builder._build_qccp_counterparty.

    References:
        - CRR Art. 107(2)(a) — non-QCCP CCP treated as institution (SA)
        - CRR Art. 120(1) Table 3 — institution CQS-1 -> 20% SA RW
    """
    row: dict[str, Any] = {
        "counterparty_reference": NONQCCP_B5_CP_REF,
        "counterparty_name": "Non-QCCP CCP (CQS-1, US)",
        "entity_type": NONQCCP_B5_ENTITY_TYPE,
        "country_code": NONQCCP_B5_COUNTRY_CODE,
        "annual_revenue": None,
        "total_assets": None,
        "default_status": False,
        "sector_code": None,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": NONQCCP_B5_INSTITUTION_CQS,
    }
    base = pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA))
    return base.with_columns(pl.lit(NONQCCP_B5_IS_QCCP).alias("is_qccp"))


def _build_nonqccp_b5_trade() -> pl.DataFrame:
    """
    Return a single-row trades DataFrame for T-NONQCCP-B5.

    All economic terms (dates, notional, currency, asset_class, transaction_type,
    delta, is_long, mtm_value) are imported from golden_ccr_a1 — byte-identical
    to the CCR-A1 trade so that the SA-CCR EAD is the same as CCR-A1.

    ``is_client_cleared=False`` because this is a proprietary (own-account) trade,
    not a client-cleared trade.  The counterparty is not a QCCP so the 4% route
    (Art. 306(1)(c)) is unreachable in any case.

    References:
        - CRR Art. 279b — PFE add-on (IR asset class, SF=0.5%)
        - CRR Art. 275(1) — RC = max(V - C, 0) = 0.0 (MtM=0, no collateral)
    """
    trade = make_trade(
        trade_id=NONQCCP_B5_TRADE_ID,
        netting_set_id=NONQCCP_B5_NS_ID,
        asset_class=CCR_A1_ASSET_CLASS,
        transaction_type=CCR_A1_TRANSACTION_TYPE,
        notional=CCR_A1_NOTIONAL,
        currency=CCR_A1_CURRENCY,
        maturity_date=CCR_A1_MATURITY_DATE,
        start_date=CCR_A1_START_DATE,
        delta=CCR_A1_DELTA,
        is_long=CCR_A1_IS_LONG,
        mtm_value=CCR_A1_MTM,
    )
    base = create_trades([trade])
    # is_client_cleared=False: proprietary trade, not client-cleared.
    return base.with_columns(pl.lit(False).alias("is_client_cleared"))


def _build_nonqccp_b5_netting_set() -> pl.DataFrame:
    """
    Return a single-row netting-sets DataFrame for NS-NONQCCP-B5.

    is_legally_enforceable=True (Art. 295 condition met) and is_margined=False
    (unmargined, no CSA) — mirrors the CCR-A1 netting set attributes exactly.
    """
    ns = make_netting_set(
        netting_set_id=NONQCCP_B5_NS_ID,
        counterparty_reference=NONQCCP_B5_CP_REF,
        is_legally_enforceable=CCR_A1_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_A1_IS_MARGINED,
    )
    return create_netting_sets([ns])


def _build_empty_ccr_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-B5: no posted/received collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


def _build_nonqccp_b5_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle for CCR-B5.

    Composition:
        trades            — 1 row  (T-NONQCCP-B5, 10y GBP IR swap, NS-NONQCCP-B5)
        netting_sets      — 1 row  (NS-NONQCCP-B5, CP-NONQCCP-B5, enforceable, unmargined)
        margin_agreements — 0 rows (unmargined, no CSA)
        ccr_collateral    — 0 rows (no posted/received collateral)
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=_build_nonqccp_b5_trade().lazy()),
        netting_sets=NettingSetBundle(netting_sets=_build_nonqccp_b5_netting_set().lazy()),
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
# Public bundle factory — primary public API for test-writer.
# ---------------------------------------------------------------------------


def build_nonqccp_b5_bundle() -> RawDataBundle:
    """
    Build a complete orchestrator-ready RawDataBundle for CCR-B5.

    CCR-B5 is the genuine delta for P8.42: a non-QCCP CCP trade exposure
    that is routed through the institution SA risk-weight ladder at CQS-1 -> 20%.

    Portfolio composition:
        Counterparty CP-NONQCCP-B5 (entity_type="ccp", is_qccp=False, CQS-1, US)
        Trade T-NONQCCP-B5 in NS-NONQCCP-B5 (10y GBP IR swap, MtM=0.0, unmargined)
        Empty margin agreements and CCR collateral
        Empty lending frames (no traditional lending)

    EAD assertion guidance (for test-writer):
        Load ead_ccr_a1 = json.load(...)["ead_final"]  from CCR-A1.json
        Assert result_ead == pytest.approx(ead_ccr_a1, rel=1e-6)
        Assert rwa_final == pytest.approx(ead_ccr_a1 * NONQCCP_B5_EXPECTED_RW, rel=1e-9)

        Do NOT transcribe 5_480_017.519 as a literal — bind to CCR-A1.json.

    Anti-degenerate risk-weight guards (for test-writer):
        assert risk_weight == NONQCCP_B5_EXPECTED_RW          # 0.20 — THE NEW PIN
        assert risk_weight != 0.02   # QCCP proprietary (Art. 306(1)(a))
        assert risk_weight != 0.04   # QCCP client-cleared (Art. 306(1)(c))
        assert risk_weight != 0.50   # CQS-2 SA institution fallback
        assert risk_weight != 0.40   # unrated institution fallback
        assert risk_weight != 1.0    # corporate fallback
        assert risk_weight != 12.5   # Art. 309 non-QCCP default-fund

    Usage::

        from tests.fixtures.ccr.p842_nonqccp_b5_builder import (
            build_nonqccp_b5_bundle,
            NONQCCP_B5_EXPECTED_RW,
            NONQCCP_B5_NS_ID,
        )
        data = build_nonqccp_b5_bundle()
        result = pipeline_orchestrator.run_with_data(data, config)

    References:
        - CRR Art. 107(2)(a) — non-QCCP CCP treated as institution
        - CRR Art. 120(1) Table 3 — institution CQS-1 -> 20% SA risk weight
        - CRR Art. 274(2) — EAD = 1.4 * (RC + PFE)
        - tests/expected_outputs/ccr/CCR-A1.json — EAD invariant anchor
    """
    cp_df = _build_nonqccp_b5_counterparty()
    facilities, loans, facility_mappings, lending_mappings = _build_empty_lending_frames()

    return make_raw_bundle(
        counterparties=cp_df.lazy(),
        facilities=facilities,
        loans=loans,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        ratings=pl.LazyFrame(schema=dtypes_of(RATINGS_SCHEMA)),
        ccr=_build_nonqccp_b5_raw_ccr_bundle(),
    )


# ---------------------------------------------------------------------------
# Smoke-check entry point — called by generate_all.py.
# ---------------------------------------------------------------------------


def save_p842_fixtures() -> list[tuple[str, int]]:
    """
    Smoke-check the CCR-B5 bundle and return a generation report.

    No parquet files are written — this is a Python-only builder (same pattern
    as p839_ccp_builder.py and p849_default_fund_builder.py).  Validates all
    load-bearing invariants; raises ``AssertionError`` with a descriptive
    message if any is violated.

    Invariants checked:
        1.  bundle.ccr is not None.
        2.  1 trade row; trade_id == NONQCCP_B5_TRADE_ID.
        3.  Trade is_client_cleared == False.
        4.  Trade notional == CCR_A1_NOTIONAL (byte-identical economics).
        5.  Trade start_date == CCR_A1_START_DATE; maturity_date == CCR_A1_MATURITY_DATE.
        6.  1 netting-set row; netting_set_id == NONQCCP_B5_NS_ID.
        7.  NS counterparty_reference == NONQCCP_B5_CP_REF.
        8.  NS is_legally_enforceable == True; is_margined == False.
        9.  1 counterparty row; counterparty_reference == NONQCCP_B5_CP_REF.
        10. Counterparty is_qccp == False (non-QCCP).
        11. Counterparty institution_cqs == NONQCCP_B5_INSTITUTION_CQS (1).
        12. Counterparty entity_type == NONQCCP_B5_ENTITY_TYPE ("ccp").
        13. 0 margin-agreement rows; 0 CCR-collateral rows.

    Returns:
        ``[("(python-only builder — no parquet)", 0)]``
    """
    bundle = build_nonqccp_b5_bundle()

    if bundle.ccr is None:
        raise AssertionError("P8.42 CCR-B5: bundle.ccr must not be None")

    trades_df = bundle.ccr.trades.trades.collect()
    ns_df = bundle.ccr.netting_sets.netting_sets.collect()
    margin_df = bundle.ccr.margin_agreements.margin_agreements.collect()
    coll_df = bundle.ccr.ccr_collateral.ccr_collateral.collect()
    cp_df = bundle.counterparties.collect()

    # Trade invariants.
    if trades_df.height != 1:
        raise AssertionError(f"P8.42 CCR-B5: expected 1 trade row, got {trades_df.height}")
    if trades_df["trade_id"][0] != NONQCCP_B5_TRADE_ID:
        raise AssertionError(
            f"P8.42 CCR-B5: trade_id must be {NONQCCP_B5_TRADE_ID!r} "
            f"(got {trades_df['trade_id'][0]!r})"
        )
    if "is_client_cleared" not in trades_df.columns:
        raise AssertionError("P8.42 CCR-B5: is_client_cleared column must be present on trades")
    if trades_df["is_client_cleared"][0] is not False:
        raise AssertionError(
            f"P8.42 CCR-B5: is_client_cleared must be False (got {trades_df['is_client_cleared'][0]!r})"
        )
    if trades_df["notional"][0] != CCR_A1_NOTIONAL:
        raise AssertionError(
            f"P8.42 CCR-B5: notional must be {CCR_A1_NOTIONAL} (got {trades_df['notional'][0]})"
        )
    if trades_df["start_date"][0] != CCR_A1_START_DATE:
        raise AssertionError(
            f"P8.42 CCR-B5: start_date must be {CCR_A1_START_DATE} "
            f"(got {trades_df['start_date'][0]})"
        )
    if trades_df["maturity_date"][0] != CCR_A1_MATURITY_DATE:
        raise AssertionError(
            f"P8.42 CCR-B5: maturity_date must be {CCR_A1_MATURITY_DATE} "
            f"(got {trades_df['maturity_date'][0]})"
        )

    # Netting-set invariants.
    if ns_df.height != 1:
        raise AssertionError(f"P8.42 CCR-B5: expected 1 NS row, got {ns_df.height}")
    if ns_df["netting_set_id"][0] != NONQCCP_B5_NS_ID:
        raise AssertionError(
            f"P8.42 CCR-B5: netting_set_id must be {NONQCCP_B5_NS_ID!r} "
            f"(got {ns_df['netting_set_id'][0]!r})"
        )
    if ns_df["counterparty_reference"][0] != NONQCCP_B5_CP_REF:
        raise AssertionError(
            f"P8.42 CCR-B5: NS counterparty_reference must be {NONQCCP_B5_CP_REF!r} "
            f"(got {ns_df['counterparty_reference'][0]!r})"
        )
    if ns_df["is_legally_enforceable"][0] is not True:
        raise AssertionError("P8.42 CCR-B5: NS is_legally_enforceable must be True")
    if ns_df["is_margined"][0] is not False:
        raise AssertionError("P8.42 CCR-B5: NS is_margined must be False")

    # Counterparty invariants.
    if cp_df.height != 1:
        raise AssertionError(f"P8.42 CCR-B5: expected 1 counterparty row, got {cp_df.height}")
    if cp_df["counterparty_reference"][0] != NONQCCP_B5_CP_REF:
        raise AssertionError(
            f"P8.42 CCR-B5: counterparty_reference must be {NONQCCP_B5_CP_REF!r} "
            f"(got {cp_df['counterparty_reference'][0]!r})"
        )
    if "is_qccp" not in cp_df.columns:
        raise AssertionError("P8.42 CCR-B5: is_qccp column must be present on counterparty")
    if cp_df["is_qccp"][0] is not False:
        raise AssertionError(
            f"P8.42 CCR-B5: counterparty is_qccp must be False (got {cp_df['is_qccp'][0]!r})"
        )
    if cp_df["institution_cqs"][0] != NONQCCP_B5_INSTITUTION_CQS:
        raise AssertionError(
            f"P8.42 CCR-B5: institution_cqs must be {NONQCCP_B5_INSTITUTION_CQS} "
            f"(got {cp_df['institution_cqs'][0]!r})"
        )
    if cp_df["entity_type"][0] != NONQCCP_B5_ENTITY_TYPE:
        raise AssertionError(
            f"P8.42 CCR-B5: entity_type must be {NONQCCP_B5_ENTITY_TYPE!r} "
            f"(got {cp_df['entity_type'][0]!r})"
        )

    # Empty-frame invariants.
    if margin_df.height != 0:
        raise AssertionError(
            f"P8.42 CCR-B5: margin_agreements must be empty (got {margin_df.height})"
        )
    if coll_df.height != 0:
        raise AssertionError(f"P8.42 CCR-B5: ccr_collateral must be empty (got {coll_df.height})")

    return [("(python-only builder — no parquet)", 0)]
