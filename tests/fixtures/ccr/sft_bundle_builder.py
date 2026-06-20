"""
SFT (FCCM) ``RawSFTBundle`` builders for the dark-launch SFT stage tests.

Pipeline position:
    fixture-builder output -> test-writer (tests/integration, tests/acceptance)
    -> engine SFT FCCM stage (engine/stages/sft.py)

SFT/FCCM separation Phase 5: the new ``sft_fccm`` stage reads
``RawDataBundle.sft`` (a :class:`RawSFTBundle`), whose lean shape differs from
the co-mingled :class:`RawCCRBundle` consumed by the legacy in-CCR path:

- ``counterparty_reference`` is denormalised onto the trade row (no separate
  netting-set table) — FCCM scope is single-trade single-counterparty netting
  sets (CRR Art. 220(1)(a)).
- every row is an SFT (no ``transaction_type`` discriminator).
- collateral is OPTIONAL (``RawSFTBundle.collateral is None`` for an
  uncollateralised SFT).

These builders deliberately reuse the CCR-A11 / CCR-A12 golden constants
(notional, counterparty, HE inputs, collateral) so the SFT stage's E* is
byte-identical to the legacy in-CCR FCCM result for the same trade — proving the
peer subsystem reproduces the regulatory math end-to-end.

The leaf frames are sealed through the SAME standard loader seal path
(``SFT_TABLE_EDGES`` / ``seal_lenient``) as production-loaded SFT files, so the
test bundle is shape-identical to a production load and satisfies the
``raw_sft_trades`` / ``raw_sft_collateral`` brands validated by the leaf
bundles' ``__post_init__``.

References:
- CRR Art. 220(1)(a), 223(5), 271(2) — FCCM SFT EAD.
- docs/plans/sft-fccm-separation.md (Phase 5 — peer stage / dark-launch).
- tests/fixtures/ccr/golden_ccr_a11_a12.py — shared scenario constants.
"""

from __future__ import annotations

import polars as pl

from rwa_calc.contracts.bundles import (
    RawSFTBundle,
    SftCollateralBundle,
    SftTradeBundle,
)
from rwa_calc.contracts.edges import SFT_TABLE_EDGES, seal_lenient
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import SFT_COLLATERAL_SCHEMA, SFT_TRADE_SCHEMA

from .golden_ccr_a11_a12 import (
    CCR_A11_A12_COUNTERPARTY_REF,
    CCR_A11_A12_CURRENCY,
    CCR_A11_A12_EXPOSURE_COLLATERAL_TYPE,
    CCR_A11_A12_EXPOSURE_SECURITY_CQS,
    CCR_A11_A12_EXPOSURE_SECURITY_RESIDUAL_MATURITY_YEARS,
    CCR_A11_A12_MATURITY_DATE,
    CCR_A11_A12_NOTIONAL,
    CCR_A11_A12_START_DATE,
    CCR_A12_COLLATERAL_CURRENCY,
    CCR_A12_COLLATERAL_MARKET_VALUE,
    CCR_A12_COLLATERAL_REF,
    CCR_A12_COLLATERAL_TYPE,
)

# SFT trade / netting-set identifiers for the dark-launch scenarios. Distinct
# from the CCR-A11/A12 ids so a future co-existence test can populate both
# raw.ccr and raw.sft without exposure_reference collisions.
SFT_DL_A11_TRADE_ID: str = "SFT_T_A11"
SFT_DL_A11_NETTING_SET_ID: str = "NS_SFT_DL_A11"
SFT_DL_A12_TRADE_ID: str = "SFT_T_A12"
SFT_DL_A12_NETTING_SET_ID: str = "NS_SFT_DL_A12"

SFT_DL_A11_EXPOSURE_REFERENCE: str = f"ccr__{SFT_DL_A11_NETTING_SET_ID}"
SFT_DL_A12_EXPOSURE_REFERENCE: str = f"ccr__{SFT_DL_A12_NETTING_SET_ID}"


def _seal_sft_trades(df: pl.DataFrame) -> pl.LazyFrame:
    """Seal an SFT trade frame exactly as the loader does (leniently)."""
    sealed, _missing = seal_lenient(df.lazy(), SFT_TABLE_EDGES["sft_trades"])
    return sealed


def _seal_sft_collateral(df: pl.DataFrame) -> pl.LazyFrame:
    """Seal an SFT collateral frame exactly as the loader does (leniently)."""
    sealed, _missing = seal_lenient(df.lazy(), SFT_TABLE_EDGES["sft_collateral"])
    return sealed


def _sft_trade_df(trade_id: str, netting_set_id: str) -> pl.DataFrame:
    """One-row SFT trade frame mirroring the CCR-A11/A12 corp-bond exposure."""
    row = {
        "trade_id": trade_id,
        "netting_set_id": netting_set_id,
        "counterparty_reference": CCR_A11_A12_COUNTERPARTY_REF,
        "notional": CCR_A11_A12_NOTIONAL,
        "currency": CCR_A11_A12_CURRENCY,
        "maturity_date": CCR_A11_A12_MATURITY_DATE,
        "start_date": CCR_A11_A12_START_DATE,
        "exposure_collateral_type": CCR_A11_A12_EXPOSURE_COLLATERAL_TYPE,
        "exposure_security_cqs": CCR_A11_A12_EXPOSURE_SECURITY_CQS,
        "exposure_security_residual_maturity_years": (
            CCR_A11_A12_EXPOSURE_SECURITY_RESIDUAL_MATURITY_YEARS
        ),
    }
    return pl.DataFrame([row], schema=dtypes_of(SFT_TRADE_SCHEMA))


def _sft_collateral_df(netting_set_id: str) -> pl.DataFrame:
    """One-row SFT collateral frame: GBP 60m cash (HC=0, HFX=0)."""
    row = {
        "sft_collateral_reference": CCR_A12_COLLATERAL_REF,
        "netting_set_id": netting_set_id,
        "collateral_type": CCR_A12_COLLATERAL_TYPE,
        "market_value": CCR_A12_COLLATERAL_MARKET_VALUE,
        "currency": CCR_A12_COLLATERAL_CURRENCY,
        "issuer_cqs": None,
        "residual_maturity_years": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(SFT_COLLATERAL_SCHEMA))


def build_sft_bundle_a11() -> RawSFTBundle:
    """Uncollateralised SFT bundle (mirrors CCR-A11): E* = E·(1+HE), no collateral."""
    return RawSFTBundle(
        trades=SftTradeBundle(
            sft_trades=_seal_sft_trades(
                _sft_trade_df(SFT_DL_A11_TRADE_ID, SFT_DL_A11_NETTING_SET_ID)
            )
        ),
        collateral=None,
    )


def build_sft_bundle_a12() -> RawSFTBundle:
    """Cash-collateralised SFT bundle (mirrors CCR-A12): E* = E·(1+HE) − 60m."""
    return RawSFTBundle(
        trades=SftTradeBundle(
            sft_trades=_seal_sft_trades(
                _sft_trade_df(SFT_DL_A12_TRADE_ID, SFT_DL_A12_NETTING_SET_ID)
            )
        ),
        collateral=SftCollateralBundle(
            sft_collateral=_seal_sft_collateral(_sft_collateral_df(SFT_DL_A12_NETTING_SET_ID))
        ),
    )
