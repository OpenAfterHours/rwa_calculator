"""
P8.25 / P8.39 fixture: QCCP trade exposure risk weight — three variants (CCR-B1a/b/c)
and orchestrator acceptance pair (CCR-CCP-1 / CCR-CCP-2).

Pipeline position:
    fixture-builder output -> test-writer (tests/unit/ccr/test_qccp_risk_weight.py,
        tests/acceptance/ccr/test_b1_qccp.py, tests/acceptance/ccr/test_ccp_wiring.py)
    -> engine-implementer (engine/ccr/ccp.py, pipeline.py CCR stage)

Scenario design:
    One GBP interest-rate derivative (T-QCCP-01, notional GBP 100m, MtM 2m,
    3-year tenor 2027-01-01 to 2030-01-01) in a single unmargined netting set
    (NS-QCCP-01) against counterparty CP-QCCP-LCH.

    Three variants share an identical EAD (SA-CCR formula, Art. 274(2)) and
    differ only in the QCCP risk-weight branch:

    | Variant      | is_qccp | is_client_cleared | rw   | Regulatory base                |
    |--------------|---------|-------------------|------|--------------------------------|
    | CCR-B1a      | True    | False             | 2%   | CRR Art. 306(1)(a)             |
    | CCR-B1b      | True    | True              | 4%   | CRR Art. 306(1)(c) / Art. 307  |
    | CCR-B1c      | False   | False             | 50%  | SA Institution CQS 2 (Table 3) |

    P8.39 orchestrator pair (CCR-CCP-1 / CCR-CCP-2) reuses the same trade economics.
    CCR-B1a == CCR-CCP-1; CCR-B1b == CCR-CCP-2.  The QCCP_INSTITUTION_CQS=2 value
    is load-bearing for the anti-degenerate assertion: without wiring, both rows
    fall to the SA-Institution ladder at 50% (CRR Art. 120(1) Table 3 CQS 2).
    Ratios: 50%/2% = 25x (proprietary), 50%/4% = 12.5x (client-cleared).

    Hand-calculated EAD (Art. 274(2), alpha=1.4, unmargined, no collateral):
        V   = 2_000_000
        C   = 0
        RC  = max(V - C, 0) = 2_000_000
        d   = 100_000_000 * (exp(-0.05*0) - exp(-0.05*3)) / 0.05
            = 100_000_000 * (1 - 0.860707976) / 0.05
            ≈ 278_584_046.59
        D   = delta * d * MF = 1.0 * 278_584_046.59 * 1.0
        AddOn_IR = SF_IR * |D| = 0.005 * 278_584_046.59 = 1_392_920.23...
        PFE  = 1.0 * AddOn_IR  (multiplier = 1 when V > 0, C = 0)
        EAD  = 1.4 * (RC + PFE) = 1.4 * 3_392_920.23... ≈ 4_750_088.326...

    Load-bearing invariant: EAD is identical across all three variants —
    only risk_weight changes.  Tolerance: pytest.approx(rel=1e-9).

Schema notes:
    ``is_qccp`` (Boolean) on the counterparty frame and ``is_client_cleared``
    (Boolean) on the trades frame are NOT yet in the canonical COUNTERPARTY_SCHEMA
    / TRADE_SCHEMA at the time this fixture is written (P8.25 schema additions are
    engine-implementer territory).  Until the engine-implementer lands those
    columns, this builder appends them via ``with_columns(pl.lit(...).alias(...))``,
    which makes them visible to tests without touching src/.

Module-level constants are the single source of truth for test-writer
assertions (EAD, risk weights, RWA, counterparty reference, etc.).  No
persistent parquet files are written — test-writer imports the builder
functions directly.

References:
    - CRR Art. 306(1)(a) — 2% RW for clearing-member's own trade exposures to QCCP
    - CRR Art. 306(1)(c) — 4% RW for client-cleared trades through clearing member
    - CRR Art. 306(4) — RWA = EAD × 2% / 4%
    - CRR Art. 272 Def (88) — qualified central counterparty (QCCP)
    - CRR Art. 107(2)(a) — other exposures to QCCP routed as institution (SA)
    - CRR Art. 120(1) Table 3 — institution CQS 2 → 50% SA RW (anti-degenerate baseline)
    - BCBS CRE54.14 — 2% supervisory factor (proprietary trade exposures)
    - BCBS CRE54.15 — 4% supervisory factor (client-cleared trade exposures)
    - src/rwa_calc/data/schemas.py — COUNTERPARTY_SCHEMA, TRADE_SCHEMA,
      NETTING_SET_SCHEMA, CCR_COLLATERAL_SCHEMA
    - src/rwa_calc/data/tables/crr_risk_weights.py — QCCP_PROPRIETARY_RW,
      QCCP_CLIENT_CLEARED_RW (reuse — do NOT redefine here)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import CCR_COLLATERAL_SCHEMA, COUNTERPARTY_SCHEMA

from .margin_builder import create_margin_agreements
from .netting_set_builder import NettingSet, create_netting_sets, make_netting_set
from .trade_builder import Trade, create_trades, make_trade

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

#: Trade identifier for all three CCR-B1 variants.
QCCP_TRADE_ID: str = "T-QCCP-01"

#: Netting set identifier shared by all three variants.
QCCP_NS_ID: str = "NS-QCCP-01"

#: Counterparty reference (LCH Ltd — QCCP entity).
QCCP_CP_REF: str = "CP-QCCP-LCH"

# --- Trade economic terms (identical across variants) ---
QCCP_NOTIONAL: float = 100_000_000.0  # GBP 100m
QCCP_CURRENCY: str = "GBP"
QCCP_ASSET_CLASS: str = "interest_rate"
QCCP_TRANSACTION_TYPE: str = "derivative"
QCCP_MTM_VALUE: float = 2_000_000.0  # in-the-money, V = 2m
QCCP_DELTA: float = 1.0  # non-option directional long (CRR Art. 279a(1))
QCCP_IS_LONG: bool = True
QCCP_START_DATE: date = date(2027, 1, 1)
QCCP_MATURITY_DATE: date = date(2030, 1, 1)  # 3-year tenor

# --- Netting set attributes ---
QCCP_IS_LEGALLY_ENFORCEABLE: bool = True  # Art. 295 condition met
QCCP_IS_MARGINED: bool = False  # unmargined, no CSA

# --- Counterparty attributes ---
QCCP_ENTITY_TYPE: str = "ccp"
QCCP_COUNTRY_CODE: str = "GB"
QCCP_INSTITUTION_CQS: int = 2  # CQS 2 → 50% SA institution RW for non-QCCP fallback (anti-degenerate baseline, CRR Art. 120 Table 3)

# --- Hand-calculated EAD (Art. 274(2), alpha=1.4) ---
# RC  = max(2_000_000 - 0, 0) = 2_000_000
# d   = 100_000_000 * (exp(-0.05*0) - exp(-0.05*3)) / 0.05 ≈ 278_584_046.59
# D   = 1.0 * 278_584_046.59 * 1.0
# AddOn_IR = 0.005 * 278_584_046.59 ≈ 1_392_920.23...
# PFE = 1.0 * AddOn_IR (multiplier = 1, V > 0, C = 0)
# EAD = 1.4 * (2_000_000 + 1_392_920.23...) = 1.4 * 3_392_920.23... ≈ 4_750_088.326...
QCCP_EAD: float = 4_750_088.326134375  # authoritative expected value (rel=1e-9)

# --- Risk weights per variant ---
QCCP_RW_PROPRIETARY: float = 0.02  # CCR-B1a: Art. 306(1), CRE54.14
QCCP_RW_CLIENT_CLEARED: float = 0.04  # CCR-B1b: Art. 307, CRE54.15
QCCP_RW_SA_FALLBACK: float = 0.50  # CCR-B1c: SA institution CQS 2 (CRR Art. 120 Table 3)

# --- Expected RWA per variant ---
QCCP_RWA_PROPRIETARY: float = QCCP_EAD * QCCP_RW_PROPRIETARY
QCCP_RWA_CLIENT_CLEARED: float = QCCP_EAD * QCCP_RW_CLIENT_CLEARED
QCCP_RWA_SA_FALLBACK: float = QCCP_EAD * QCCP_RW_SA_FALLBACK

# --- Suggested audit-column values for ccr_rw_source ---
CCR_RW_SOURCE_PROPRIETARY: str = "qccp_proprietary_art_306"
CCR_RW_SOURCE_CLIENT_CLEARED: str = "qccp_client_cleared_art_307"
CCR_RW_SOURCE_SA_FALLBACK: str = "sa_fallback_art_107_2_a"


# ---------------------------------------------------------------------------
# Scenario builders — shared across all three variants
# ---------------------------------------------------------------------------


def _qccp_trade() -> Trade:
    """Return the CCR-B1 single interest-rate derivative (shared by all three variants)."""
    return make_trade(
        trade_id=QCCP_TRADE_ID,
        netting_set_id=QCCP_NS_ID,
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


def _qccp_netting_set() -> NettingSet:
    """Return NS-QCCP-01: unmargined, legally enforceable (Art. 295 met)."""
    return make_netting_set(
        netting_set_id=QCCP_NS_ID,
        counterparty_reference=QCCP_CP_REF,
        is_legally_enforceable=QCCP_IS_LEGALLY_ENFORCEABLE,
        is_margined=QCCP_IS_MARGINED,
    )


# ---------------------------------------------------------------------------
# DataFrame factories — variant-specific via is_client_cleared on trades
# ---------------------------------------------------------------------------


def create_qccp_trades(is_client_cleared: bool) -> pl.DataFrame:
    """
    Return the single-row trades DataFrame for a CCR-B1 variant.

    The ``is_client_cleared`` column is appended as a Boolean literal via
    ``with_columns`` because it is not yet present in the canonical
    TRADE_SCHEMA (schema addition is engine-implementer territory for P8.25).
    Once TRADE_SCHEMA includes the column this call becomes redundant but
    remains correct — ``with_columns`` is idempotent when the column already
    exists with the same type.

    Args:
        is_client_cleared: True for CCR-B1b (client-cleared, Art. 307 4% RW),
            False for CCR-B1a (proprietary QCCP 2%) or CCR-B1c (non-QCCP).

    Returns:
        ``pl.DataFrame`` with columns from TRADE_SCHEMA plus ``is_client_cleared``.
    """
    base = create_trades([_qccp_trade()])
    return base.with_columns(pl.lit(is_client_cleared).alias("is_client_cleared"))


def create_qccp_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame (identical for all variants)."""
    return create_netting_sets([_qccp_netting_set()])


def create_qccp_margin_agreements() -> pl.DataFrame:
    """Return a zero-row margin-agreements DataFrame (CCR-B1: no CSA — unmargined)."""
    return create_margin_agreements([])


def create_qccp_ccr_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-B1: no posted/received collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


def create_qccp_counterparty(is_qccp: bool) -> pl.DataFrame:
    """
    Return a single-row counterparty DataFrame for CP-QCCP-LCH.

    The ``is_qccp`` column is appended as a Boolean literal via
    ``with_columns`` because it is not yet present in the canonical
    COUNTERPARTY_SCHEMA (schema addition is engine-implementer territory for
    P8.25).  Once COUNTERPARTY_SCHEMA includes the column this call becomes
    redundant but remains correct.

    Args:
        is_qccp: True for CCR-B1a/b (QCCP route), False for CCR-B1c (SA fallback).

    Returns:
        ``pl.DataFrame`` with columns from COUNTERPARTY_SCHEMA plus ``is_qccp``.
    """
    row: dict[str, Any] = {
        "counterparty_reference": QCCP_CP_REF,
        "counterparty_name": "LCH Ltd",
        "entity_type": QCCP_ENTITY_TYPE,
        "country_code": QCCP_COUNTRY_CODE,
        "annual_revenue": None,
        "total_assets": None,
        "default_status": False,
        "sector_code": "66.11",
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": QCCP_INSTITUTION_CQS,
    }
    base = pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA))
    return base.with_columns(pl.lit(is_qccp).alias("is_qccp"))


# ---------------------------------------------------------------------------
# Top-level convenience builder — primary public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QCCPTradeFixture:
    """
    All input frames for a single CCR-B1 variant.

    Attributes:
        trades:             1-row DataFrame (T-QCCP-01), with ``is_client_cleared``.
        netting_sets:       1-row DataFrame (NS-QCCP-01).
        margin_agreements:  0-row DataFrame (unmargined, no CSA).
        ccr_collateral:     0-row DataFrame (no posted/received collateral).
        counterparty:       1-row DataFrame (CP-QCCP-LCH), with ``is_qccp``.
        is_qccp:            Flag carried from caller, mirrors the counterparty column.
        is_client_cleared:  Flag carried from caller, mirrors the trades column.
    """

    trades: pl.DataFrame
    netting_sets: pl.DataFrame
    margin_agreements: pl.DataFrame
    ccr_collateral: pl.DataFrame
    counterparty: pl.DataFrame
    is_qccp: bool
    is_client_cleared: bool


def build_qccp_trade_fixture(
    is_qccp: bool,
    is_client_cleared: bool,
) -> QCCPTradeFixture:
    """
    Build a complete CCR-B1 variant fixture.

    Returns a ``QCCPTradeFixture`` containing all four SA-CCR input frames
    plus a counterparty frame.  The three variants differ only in the Boolean
    flags; all frames share the same economic terms (notional, MtM, tenor).

    Variants:
        CCR-B1a (proprietary QCCP):     is_qccp=True,  is_client_cleared=False
        CCR-B1b (client-cleared QCCP):  is_qccp=True,  is_client_cleared=True
        CCR-B1c (non-QCCP SA fallback): is_qccp=False, is_client_cleared=False

    Args:
        is_qccp:            True if the counterparty is a QCCP (CRR Def (88)).
        is_client_cleared:  True if the trade is client-cleared (Art. 307 route).

    Returns:
        ``QCCPTradeFixture`` with five populated DataFrames and the two flags.

    References:
        - CRR Art. 306(1) — 2% RW (proprietary trade exposure)
        - CRR Art. 307   — 4% RW (client-cleared exposure)
        - CRR Art. 107(2)(a) — SA institution fallback for non-QCCP
    """
    return QCCPTradeFixture(
        trades=create_qccp_trades(is_client_cleared=is_client_cleared),
        netting_sets=create_qccp_netting_sets(),
        margin_agreements=create_qccp_margin_agreements(),
        ccr_collateral=create_qccp_ccr_collateral(),
        counterparty=create_qccp_counterparty(is_qccp=is_qccp),
        is_qccp=is_qccp,
        is_client_cleared=is_client_cleared,
    )
