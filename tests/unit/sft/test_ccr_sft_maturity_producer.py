"""
Producer-level tests for the FCCM SFT effective-maturity carrier projection.

Drives :func:`sft_bundle_to_exposures` end-to-end on a single-trade SFT bundle
and asserts the synthetic row's ``ccr_effective_maturity`` column equals the
Art. 162 effective maturity M derived per netting set. The carrier is null off
the MNA carve-out, the one-day floor when the explicit qualifying flag is set,
and the 5BD intermediate floor for a non-daily MNA repo (CRR).

The run rulepack is threaded in explicitly (``rulepack=resolve('crr', d)``) so
the producer reads the regime-correct floors/feature — the default
module-``_PACK`` fall-back is exercised by the back-compat path elsewhere.

References:
    CRR Art. 162(2)(d) — 5BD repo/SFT M floor under an MNA.
    CRR Art. 162(3) — one-day (~1/365 y) floor.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawSFTBundle, SftTradeBundle
from rwa_calc.contracts.edges import SFT_TABLE_EDGES, seal_lenient
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import SFT_TRADE_SCHEMA
from rwa_calc.engine.sft.fccm import sft_bundle_to_exposures
from rwa_calc.rulebook.resolve import resolve

_REPORTING_DATE = date(2026, 1, 1)
_NS_ID = "NS_SFT_MAT"
_CRR_PACK = resolve("crr", _REPORTING_DATE)

_ONE_DAY = 1.0 / 365.0
_FIVE_DAY = 5.0 / 365.0
_REL_TOL = 1e-12


def _build_bundle(
    *,
    maturity_date: date | None,
    under_master_netting_agreement: bool = False,
    qualifies_one_day_maturity_floor: bool = False,
    qualifies_mna_intermediate_floor: bool = False,
    is_margined: bool = False,
    remargining_frequency_days: int = 1,
) -> RawSFTBundle:
    """One-trade, uncollateralised SFT bundle carrying the Art. 162 input flags."""
    trade_row = {
        "trade_id": "T_SFT_MAT",
        "netting_set_id": _NS_ID,
        "counterparty_reference": "CP_INST_001",
        "notional": 10_000_000.0,
        "currency": "GBP",
        "maturity_date": maturity_date,
        "start_date": _REPORTING_DATE,
        "exposure_collateral_type": None,
        "exposure_security_cqs": None,
        "exposure_security_residual_maturity_years": None,
        "is_margined": is_margined,
        "remargining_frequency_days": remargining_frequency_days,
        "mpor_floor_category": "repo_only",
        "has_margin_dispute_doubling": False,
        "mpor_days_override": None,
        "under_master_netting_agreement": under_master_netting_agreement,
        "qualifies_one_day_maturity_floor": qualifies_one_day_maturity_floor,
        "qualifies_mna_intermediate_floor": qualifies_mna_intermediate_floor,
    }
    trades_df = pl.DataFrame([trade_row], schema=dtypes_of(SFT_TRADE_SCHEMA))
    sealed_trades, _ = seal_lenient(trades_df.lazy(), SFT_TABLE_EDGES["sft_trades"])
    return RawSFTBundle(trades=SftTradeBundle(sft_trades=sealed_trades))


def _carrier(bundle: RawSFTBundle) -> float | None:
    """Run the FCCM producer with the CRR run pack and return ccr_effective_maturity."""
    rows = sft_bundle_to_exposures(bundle, _REPORTING_DATE, rulepack=_CRR_PACK).collect().to_dicts()
    assert len(rows) == 1
    return rows[0]["ccr_effective_maturity"]


def test_carrier_null_when_not_under_mna() -> None:
    """(i) Not under an MNA -> carrier null (date-derived 1y catch-all downstream)."""
    bundle = _build_bundle(
        maturity_date=date(2026, 5, 7),  # ~126 days
        under_master_netting_agreement=False,
    )
    assert _carrier(bundle) is None


def test_carrier_five_business_days_for_nondaily_mna_repo() -> None:
    """(ii) Under MNA, short non-daily repo -> 5BD intermediate floor 5/365 (CRR)."""
    bundle = _build_bundle(
        maturity_date=date(2026, 1, 3),  # 2 days remaining
        under_master_netting_agreement=True,
        qualifies_one_day_maturity_floor=False,
    )
    assert _carrier(bundle) == pytest.approx(_FIVE_DAY, rel=_REL_TOL)


def test_carrier_one_day_for_qualifying_overnight_repo() -> None:
    """(iii) Under MNA, qualifies-162(3) overnight repo -> one-day floor 1/365."""
    bundle = _build_bundle(
        maturity_date=_REPORTING_DATE,  # 0 days remaining
        under_master_netting_agreement=True,
        qualifies_one_day_maturity_floor=True,
    )
    assert _carrier(bundle) == pytest.approx(_ONE_DAY, rel=_REL_TOL)


def test_empty_sft_book_does_not_raise() -> None:
    """An empty SFT book (zero trades) must not abort the producer.

    Regression: with an empty ``sft_ns_ids`` the NS-grain carrier frame would
    infer a Null-typed ``netting_set_id`` and fail the str-key join, aborting
    the whole pipeline (the audit-cache empty-book regression). The carrier
    join key is forced to String, so the empty book yields a clean zero-row
    frame that still carries the carrier column.
    """
    empty_trades = pl.DataFrame([], schema=dtypes_of(SFT_TRADE_SCHEMA))
    sealed, _ = seal_lenient(empty_trades.lazy(), SFT_TABLE_EDGES["sft_trades"])
    bundle = RawSFTBundle(trades=SftTradeBundle(sft_trades=sealed))

    rows = sft_bundle_to_exposures(bundle, _REPORTING_DATE, rulepack=_CRR_PACK).collect()

    assert rows.height == 0
    assert "ccr_effective_maturity" in rows.columns
