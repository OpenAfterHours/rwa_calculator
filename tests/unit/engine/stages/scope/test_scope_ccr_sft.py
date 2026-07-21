"""
Nested CCR / SFT bundle filtering for the scope resolver.

CCR is filtered at netting-set grain (surviving sets keep their trades and
collateral by semi-join); SFT is filtered at trade grain (surviving trades keep
their netting-set-keyed collateral). Both honour the booking filter and the
consolidated-only intragroup elimination.

References:
- CRR Art. 6 / 11-18 (levels of application); Art. 271-272 (CCR scope).
- docs/plans/multi-entity-reporting.md: scope resolver specification.
"""

from __future__ import annotations

from datetime import date

import polars as pl
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    RawSFTBundle,
    SftCollateralBundle,
    SftTradeBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import SFT_TABLE_EDGES, seal_lenient
from rwa_calc.domain.enums import ReportingBasis
from rwa_calc.engine.stages.scope import resolver

_TREE = pl.DataFrame(
    {
        "entity_reference": ["GRP", "BANK_A", "BANK_B"],
        "parent_entity_reference": [None, "GRP", "GRP"],
    }
)
_MAPPING = pl.DataFrame(
    {
        "book_code": ["BOOK_A", "BOOK_B"],
        "reporting_entity_reference": ["BANK_A", "BANK_B"],
    }
)

_STR3 = {
    "netting_set_id": pl.String,
    "book_code": pl.String,
    "intragroup_entity_reference": pl.String,
}


def _netting_sets() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "netting_set_id": ["NS_EXT", "NS_IG", "NS_OUT"],
            "book_code": ["BOOK_A", "BOOK_A", "BOOK_B"],
            "intragroup_entity_reference": [None, "BANK_B", None],
        },
        schema=_STR3,
    )


def _trades() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "trade_id": ["T_EXT", "T_IG", "T_OUT"],
            "netting_set_id": ["NS_EXT", "NS_IG", "NS_OUT"],
        },
        schema={"trade_id": pl.String, "netting_set_id": pl.String},
    )


def _ccr_collateral() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "ccr_collateral_reference": ["C_EXT", "C_OUT"],
            "netting_set_id": ["NS_EXT", "NS_OUT"],
        },
        schema={"ccr_collateral_reference": pl.String, "netting_set_id": pl.String},
    )


def _ccr_bundle() -> RawCCRBundle:
    return RawCCRBundle(
        trades=TradeBundle(trades=_trades()),
        netting_sets=NettingSetBundle(netting_sets=_netting_sets()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=pl.LazyFrame(schema={"margin_agreement_id": pl.String})
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=_ccr_collateral()),
    )


def _sft_bundle() -> RawSFTBundle:
    trades = pl.DataFrame(
        {
            "trade_id": ["ST_EXT", "ST_IG", "ST_OUT"],
            "netting_set_id": ["NS1", "NS2", "NS3"],
            "counterparty_reference": ["CP1", "CP2", "CP3"],
            "book_code": ["BOOK_A", "BOOK_A", "BOOK_B"],
            "intragroup_entity_reference": [None, "BANK_B", None],
        }
    )
    collateral = pl.DataFrame(
        {
            "sft_collateral_reference": ["SC1", "SC3"],
            "netting_set_id": ["NS1", "NS3"],
        }
    )
    sealed_trades, _ = seal_lenient(trades.lazy(), SFT_TABLE_EDGES["sft_trades"])
    sealed_collateral, _ = seal_lenient(collateral.lazy(), SFT_TABLE_EDGES["sft_collateral"])
    return RawSFTBundle(
        trades=SftTradeBundle(sft_trades=sealed_trades),
        collateral=SftCollateralBundle(sft_collateral=sealed_collateral),
    )


def _resolve(bundle, entity: str, basis: ReportingBasis):
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 1), reporting_entity=entity, reporting_basis=basis
    )
    return resolver.resolve_scope(bundle, config)


def _ids(frame: pl.LazyFrame, column: str) -> set[str]:
    return set(frame.collect()[column].to_list())


# ---------------------------------------------------------------------------
# CCR
# ---------------------------------------------------------------------------


def test_ccr_consolidated_eliminates_intragroup_netting_set():
    bundle = make_raw_bundle(
        reporting_entities=_TREE, book_entity_mappings=_MAPPING, ccr=_ccr_bundle()
    )

    result = _resolve(bundle, "GRP", ReportingBasis.CONSOLIDATED)

    assert _ids(result.ccr.netting_sets.netting_sets, "netting_set_id") == {"NS_EXT", "NS_OUT"}
    assert _ids(result.ccr.trades.trades, "trade_id") == {"T_EXT", "T_OUT"}


def test_ccr_individual_keeps_intragroup_but_filters_by_book():
    bundle = make_raw_bundle(
        reporting_entities=_TREE, book_entity_mappings=_MAPPING, ccr=_ccr_bundle()
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    # BOOK_A survives (NS_EXT + NS_IG kept on a solo run); NS_OUT (BOOK_B) gone.
    assert _ids(result.ccr.netting_sets.netting_sets, "netting_set_id") == {"NS_EXT", "NS_IG"}
    assert _ids(result.ccr.trades.trades, "trade_id") == {"T_EXT", "T_IG"}


def test_ccr_collateral_follows_surviving_netting_sets():
    bundle = make_raw_bundle(
        reporting_entities=_TREE, book_entity_mappings=_MAPPING, ccr=_ccr_bundle()
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    # NS_OUT dropped -> its collateral C_OUT drops; C_EXT (NS_EXT) survives.
    assert _ids(result.ccr.ccr_collateral.ccr_collateral, "ccr_collateral_reference") == {"C_EXT"}


# ---------------------------------------------------------------------------
# SFT
# ---------------------------------------------------------------------------


def test_sft_consolidated_eliminates_intragroup_trade():
    bundle = make_raw_bundle(
        reporting_entities=_TREE, book_entity_mappings=_MAPPING, sft=_sft_bundle()
    )

    result = _resolve(bundle, "GRP", ReportingBasis.CONSOLIDATED)

    assert _ids(result.sft.trades.sft_trades, "trade_id") == {"ST_EXT", "ST_OUT"}


def test_sft_individual_keeps_intragroup_but_filters_by_book():
    bundle = make_raw_bundle(
        reporting_entities=_TREE, book_entity_mappings=_MAPPING, sft=_sft_bundle()
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    assert _ids(result.sft.trades.sft_trades, "trade_id") == {"ST_EXT", "ST_IG"}


def test_sft_collateral_follows_surviving_trades():
    bundle = make_raw_bundle(
        reporting_entities=_TREE, book_entity_mappings=_MAPPING, sft=_sft_bundle()
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    # ST_OUT (NS3) dropped -> SC3 drops; SC1 (NS1) survives.
    assert _ids(result.sft.collateral.sft_collateral, "sft_collateral_reference") == {"SC1"}


def test_sft_trades_reseal_survives_bundle_validation():
    # SftTradeBundle.__post_init__ re-validates the raw_sft_trades brand; a
    # filtered-then-re-sealed frame must still satisfy it (no exception).
    bundle = make_raw_bundle(
        reporting_entities=_TREE, book_entity_mappings=_MAPPING, sft=_sft_bundle()
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    assert result.sft.trades.sft_trades is not None


def test_unmapped_book_on_ccr_netting_set_triggers_scp001():
    # SCP001 detection must cover the non-lending frames too: a netting set on
    # a book absent from the mapping is unattributable -> flagged + excluded.
    netting_sets = pl.LazyFrame(
        {
            "netting_set_id": ["NS1"],
            "book_code": ["BOOK_UNMAPPED"],
            "intragroup_entity_reference": [None],
        },
        schema=_STR3,
    )
    ccr = RawCCRBundle(
        trades=TradeBundle(
            trades=pl.LazyFrame(
                {"trade_id": ["T1"], "netting_set_id": ["NS1"]},
                schema={"trade_id": pl.String, "netting_set_id": pl.String},
            )
        ),
        netting_sets=NettingSetBundle(netting_sets=netting_sets),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=pl.LazyFrame(schema={"margin_agreement_id": pl.String})
        ),
        ccr_collateral=CCRCollateralBundle(
            ccr_collateral=pl.LazyFrame(
                schema={"ccr_collateral_reference": pl.String, "netting_set_id": pl.String}
            )
        ),
    )
    bundle = make_raw_bundle(reporting_entities=_TREE, book_entity_mappings=_MAPPING, ccr=ccr)

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    codes = [e.code for e in result.errors if e.code.startswith("SCP")]
    assert resolver.SCP_UNATTRIBUTABLE_BOOK in codes
    assert result.ccr.netting_sets.netting_sets.collect().height == 0
