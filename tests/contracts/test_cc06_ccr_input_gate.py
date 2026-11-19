"""
Review CC-06 (contract): the CCR / SFT input gate is live, not dormant.

Pipeline position:
    contracts/validation.py::validate_bundle_values over a RawDataBundle carrying
    a CCR book (the gate the loader and run_with_data both call)

Key responsibilities:
- Every COLUMN_VALUE_CONSTRAINTS key names a frame ``bundle_frames`` actually
  registers. Before CC-06 the CCR / SFT entries were keyed ``trades`` /
  ``sft_trades`` against registered names ``ccr.trades`` / ``sft.trades``, so they
  validated nothing — and self-documented as "Dormant".
- An out-of-domain ``ccr.trades`` value now raises DQ006 through the gate.
- A CCR netting set whose counterparty is absent from the counterparty table
  raises DQ005 (the declared obligor link, TABLE_FOREIGN_KEYS).

References:
- CRR Art. 277(1) (risk categories); Art. 271 / 274 (netting-set obligor).
- .claude/LESSONS.md B1 (a guard keyed on a name nothing produces fails
  silently, forever).
"""

from __future__ import annotations

import polars as pl
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    FailedTradesBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    RawDataBundle,
    RawSFTBundle,
    SftCollateralBundle,
    SftTradeBundle,
    TradeBundle,
)
from rwa_calc.contracts.edges import SFT_TABLE_EDGES
from rwa_calc.contracts.validation import bundle_frames, validate_bundle_values
from rwa_calc.data.schemas import COLUMN_VALUE_CONSTRAINTS, TABLE_FOREIGN_KEYS


def _ccr_bundle(asset_class: str = "interest_rate", ns_counterparty: str = "CP1") -> RawDataBundle:
    counterparties = pl.LazyFrame({"counterparty_reference": ["CP1"], "entity_type": ["corporate"]})
    trades = pl.LazyFrame(
        {
            "trade_id": ["T1"],
            "netting_set_id": ["NS1"],
            "transaction_type": ["derivative"],
            "asset_class": [asset_class],
        }
    )
    netting_sets = pl.LazyFrame(
        {"netting_set_id": ["NS1"], "counterparty_reference": [ns_counterparty]}
    )
    return make_raw_bundle(
        counterparties=counterparties,
        ccr=RawCCRBundle(
            trades=TradeBundle(trades=trades),
            netting_sets=NettingSetBundle(netting_sets=netting_sets),
            margin_agreements=MarginAgreementBundle(margin_agreements=pl.LazyFrame()),
            ccr_collateral=CCRCollateralBundle(ccr_collateral=pl.LazyFrame()),
            failed_trades=FailedTradesBundle(failed_trades=pl.LazyFrame()),
            default_fund_contributions=pl.LazyFrame(),
        ),
        sft=RawSFTBundle(
            trades=SftTradeBundle(sft_trades=SFT_TABLE_EDGES["sft_trades"].empty_frame()),
            collateral=SftCollateralBundle(
                sft_collateral=SFT_TABLE_EDGES["sft_collateral"].empty_frame()
            ),
        ),
    )


def test_every_constraint_and_foreign_key_table_is_a_registered_frame() -> None:
    """No dormant registry key: each names a frame the gate visits."""
    # Arrange
    registered = set(bundle_frames(_ccr_bundle()))

    # Assert
    assert set(COLUMN_VALUE_CONSTRAINTS) - registered == set()
    assert set(TABLE_FOREIGN_KEYS) - registered == set()


def test_unrecognised_ccr_asset_class_raises_dq006() -> None:
    """ccr.trades asset_class 'weather' is out of domain (and CCR021 says what was done)."""
    # Arrange / Act
    errors = validate_bundle_values(_ccr_bundle(asset_class="weather"))

    # Assert
    codes = {(e.code, e.field_name) for e in errors}
    assert ("DQ006", "asset_class") in codes
    assert ("CCR021", "asset_class") in codes


def test_netting_set_with_unknown_counterparty_raises_dq005() -> None:
    """The netting-set obligor link is declared: an orphan counterparty is DQ005."""
    # Arrange / Act
    errors = validate_bundle_values(_ccr_bundle(ns_counterparty="CP-MISSING"))

    # Assert
    orphans = [e for e in errors if e.code == "DQ005"]
    assert [(e.field_name, e.actual_value) for e in orphans] == [
        ("counterparty_reference", "CP-MISSING")
    ]
    assert "[ccr.netting_sets]" in orphans[0].message


def test_clean_ccr_bundle_raises_no_ccr_input_error() -> None:
    """Control: a well-formed derivative trade raises none of the new findings."""
    # Arrange / Act
    errors = validate_bundle_values(_ccr_bundle())

    # Assert
    assert {e.code for e in errors} & {"DQ005", "DQ006", "CCR021", "CCR022", "CCR023"} == set()
