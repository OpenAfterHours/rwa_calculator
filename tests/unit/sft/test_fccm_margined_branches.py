"""
Unit tests for the margined/unmargined FCCM E* branches (CRR Art. 223(5)).

Drives :func:`sft_bundle_to_exposures` end-to-end on a single-trade SFT bundle
and pins the netting-set E* against the orchestrator-verified hand-calcs in
``.claude/state/margined-sft-design.md``:

    E = C = 10,000,000; collateral govt CQS1 0.5y ⇒ H_10 = 0.005; H_E = 0.

    (i)   unmargined daily repo (N_R=1, T_M=5) → E* = 35,355.3390593268  (anchor)
    (ii)  unmargined 3-day remargin (N_R=3, T_M=5) → E* = 41,833.0013267044
    (iii) margined repo-only N=2 ⇒ MPOR=6 (N_R suppressed) → E* = 38,729.8334620744

H_C(i) = 0.005·√(5/10); the Art. 226 non-daily factor √((N_R+T_M−1)/T_M) lifts
(ii); the margined branch (iii) raises T_M to the MPOR (6) and suppresses the
non-daily factor (MPOR already encodes N).

References:
    CRR Art. 223(5) — E* = max(0, E·(1+HE) − CVA·(1−HC−HFX)).
    CRR Art. 224(2)(b) — 5-BD repo liquidation period.
    CRR Art. 226 — non-daily revaluation scale-up.
    CRR Art. 285(2)-(5) — margined MPOR.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    RawSFTBundle,
    SftCollateralBundle,
    SftTradeBundle,
)
from rwa_calc.contracts.edges import SFT_TABLE_EDGES, seal_lenient
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import SFT_COLLATERAL_SCHEMA, SFT_TRADE_SCHEMA
from rwa_calc.engine.sft.fccm import sft_bundle_to_exposures

# Hand-calc anchors (E = C = 10,000,000; govt CQS1 0.5y collateral, H_E = 0).
_REPORTING_DATE = date(2026, 6, 30)
_NOTIONAL = 10_000_000.0
_COLLATERAL_MV = 10_000_000.0
_NS_ID = "NS_SFT_HC"

_ESTAR_UNMARGINED_DAILY = 35_355.3390593268  # (i)
_ESTAR_UNMARGINED_NR3 = 41_833.0013267044  # (ii)
_ESTAR_MARGINED_REPO_N2 = 38_729.8334620744  # (iii)

_REL_TOL = 1e-12


def _build_bundle(
    *,
    is_margined: bool = False,
    remargining_frequency_days: int = 1,
    mpor_floor_category: str = "repo_only",
    has_margin_dispute_doubling: bool = False,
    mpor_days_override: int | None = None,
) -> RawSFTBundle:
    """One-trade SFT bundle: E=C=10m, H_E=0, govt CQS1 0.5y collateral (H_10=0.005)."""
    trade_row = {
        "trade_id": "T_SFT_HC",
        "netting_set_id": _NS_ID,
        "counterparty_reference": "CP_INST_001",
        "notional": _NOTIONAL,
        "currency": "GBP",
        "maturity_date": date(2031, 6, 30),
        "start_date": _REPORTING_DATE,
        # No exposure-side security → H_E = 0.
        "exposure_collateral_type": None,
        "exposure_security_cqs": None,
        "exposure_security_residual_maturity_years": None,
        "is_margined": is_margined,
        "remargining_frequency_days": remargining_frequency_days,
        "mpor_floor_category": mpor_floor_category,
        "has_margin_dispute_doubling": has_margin_dispute_doubling,
        "mpor_days_override": mpor_days_override,
    }
    trades_df = pl.DataFrame([trade_row], schema=dtypes_of(SFT_TRADE_SCHEMA))
    sealed_trades, _ = seal_lenient(trades_df.lazy(), SFT_TABLE_EDGES["sft_trades"])

    coll_row = {
        "sft_collateral_reference": "COLL_SFT_HC",
        "netting_set_id": _NS_ID,
        "collateral_type": "govt_bond",
        "market_value": _COLLATERAL_MV,
        "currency": "GBP",
        "issuer_cqs": 1,
        "residual_maturity_years": 0.5,
    }
    coll_df = pl.DataFrame([coll_row], schema=dtypes_of(SFT_COLLATERAL_SCHEMA))
    sealed_coll, _ = seal_lenient(coll_df.lazy(), SFT_TABLE_EDGES["sft_collateral"])

    return RawSFTBundle(
        trades=SftTradeBundle(sft_trades=sealed_trades),
        collateral=SftCollateralBundle(sft_collateral=sealed_coll),
    )


def _ead_ccr(bundle: RawSFTBundle) -> float:
    """Run the FCCM stage and return the single netting set's ead_ccr."""
    rows = sft_bundle_to_exposures(bundle, _REPORTING_DATE).collect().to_dicts()
    assert len(rows) == 1
    return rows[0]["ead_ccr"]


def test_unmargined_daily_estar_matches_handcalc_i() -> None:
    """(i) Unmargined daily repo (N_R=1, T_M=5) → E* = 35,355.3390593268 (anchor)."""
    bundle = _build_bundle(is_margined=False, remargining_frequency_days=1)
    assert _ead_ccr(bundle) == pytest.approx(_ESTAR_UNMARGINED_DAILY, rel=_REL_TOL)


def test_unmargined_nr3_estar_matches_handcalc_ii() -> None:
    """(ii) Unmargined 3-day remargin (N_R=3, T_M=5) → E* = 41,833.0013267044."""
    bundle = _build_bundle(is_margined=False, remargining_frequency_days=3)
    assert _ead_ccr(bundle) == pytest.approx(_ESTAR_UNMARGINED_NR3, rel=_REL_TOL)


def test_margined_repo_only_n2_estar_matches_handcalc_iii() -> None:
    """(iii) Margined repo-only N=2 ⇒ MPOR=6 → E* = 38,729.8334620744."""
    bundle = _build_bundle(
        is_margined=True,
        remargining_frequency_days=2,
        mpor_floor_category="repo_only",
    )
    assert _ead_ccr(bundle) == pytest.approx(_ESTAR_MARGINED_REPO_N2, rel=_REL_TOL)


def test_margined_daily_repo_only_n1_equals_unmargined_daily() -> None:
    """Margined-but-daily repo-only N=1 ⇒ MPOR=5 → equals the unmargined-daily anchor."""
    bundle = _build_bundle(
        is_margined=True,
        remargining_frequency_days=1,
        mpor_floor_category="repo_only",
    )
    assert _ead_ccr(bundle) == pytest.approx(_ESTAR_UNMARGINED_DAILY, rel=_REL_TOL)
