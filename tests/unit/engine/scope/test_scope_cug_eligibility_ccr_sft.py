"""
Art. 113(6) core-UK-group eligibility on the CCR netting-set and SFT trade grains.

Neither CRR Art. 113(6) nor PS1/26 Art. 113(6) excludes counterparty credit risk
from the intragroup 0% — the only carve-out is "exposures giving rise to Common
Equity Tier 1, Additional Tier 1 or Tier 2 items". So on an individual-basis run
the scope resolver sets ``intragroup_zero_rw_eligible`` on an SA-CCR netting set
and on an SFT trade tagged intragroup to a core-UK-group entity, exactly as it
does on the lending rows (P1.364, owner sign-off for the RWA-reducing limb). It
overwrites the carrier on every such row — a stray input True on an external row
is cleared — and leaves the equity frame untagged (an equity stake in a group
institution is a holding of its own-funds instruments).

References:
- CRR Art. 113(6); PS1/26 Art. 113(6)
- CRR / PS1/26 Annex II para 126 (0%-weighted intragroup CCR)
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
    SftTradeBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import SFT_TABLE_EDGES, seal_lenient
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    MARGIN_AGREEMENT_SCHEMA,
    NETTING_SET_SCHEMA,
    TRADE_SCHEMA,
)
from rwa_calc.domain.enums import ReportingBasis
from rwa_calc.engine.scope import resolver

_CARRIER = "intragroup_zero_rw_eligible"
_ENTITIES = ("GRP", "BANK_A", "BANK_B")
_PARENTS = (None, "GRP", "GRP")
_MAPPING = pl.DataFrame(
    {"book_code": ["BOOK_A", "BOOK_B"], "reporting_entity_reference": ["BANK_A", "BANK_B"]}
)

#: (reference, counterparty, intragroup tag, stray input carrier)
_ROWS = [
    ("IG", "BANK_B", "BANK_B", False),
    ("EXT", "CP_EXT", None, False),
    ("EXT_STRAY", "CP_EXT", None, True),
]


# ---------------------------------------------------------------------------
# Individual core-UK-group run: the positive case and the bypass closure
# ---------------------------------------------------------------------------


def test_intragroup_netting_set_to_cug_member_is_eligible():
    # Arrange
    bundle = _bundle(_tree(all_cug=True))

    # Act
    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    # Assert
    assert _eligible(result.ccr.netting_sets.netting_sets, "netting_set_id") == {
        "IG": True,
        "EXT": False,
        "EXT_STRAY": False,
    }


def test_intragroup_sft_trade_to_cug_member_is_eligible():
    # Arrange
    bundle = _bundle(_tree(all_cug=True))

    # Act
    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    # Assert
    assert _eligible(result.sft.trades.sft_trades, "trade_id") == {
        "IG": True,
        "EXT": False,
        "EXT_STRAY": False,
    }


def test_reporting_entity_outside_cug_clears_every_ccr_and_sft_row():
    """Not a member -> no row is eligible, and the stray True is overwritten."""
    # Arrange
    bundle = _bundle(_tree(all_cug=True, reporting_entity_cug=False))

    # Act
    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    # Assert
    assert set(_eligible(result.ccr.netting_sets.netting_sets, "netting_set_id").values()) == {
        False
    }
    assert set(_eligible(result.sft.trades.sft_trades, "trade_id").values()) == {False}


# ---------------------------------------------------------------------------
# Consolidated run: intragroup eliminated, the carrier left to its input value
# ---------------------------------------------------------------------------


def test_consolidated_run_eliminates_intragroup_ccr_and_sft_rows():
    # Arrange
    bundle = _bundle(_tree(all_cug=True))

    # Act
    result = _resolve(bundle, "GRP", ReportingBasis.CONSOLIDATED)

    # Assert — IG removed (its tag is a member); externals kept
    assert _keys(result.ccr.netting_sets.netting_sets, "netting_set_id") == ["EXT", "EXT_STRAY"]
    assert _keys(result.sft.trades.sft_trades, "trade_id") == ["EXT", "EXT_STRAY"]


# ---------------------------------------------------------------------------
# Equity is never tagged: an equity stake in a group institution is an own-funds
# holding (the CET1 / AT1 / T2 carve-out)
# ---------------------------------------------------------------------------


def test_equity_frame_is_never_tagged():
    # Arrange
    equity = pl.DataFrame(
        {
            "exposure_reference": ["EQ_IG"],
            "counterparty_reference": ["BANK_B"],
            "book_code": ["BOOK_A"],
            "intragroup_entity_reference": ["BANK_B"],
        }
    )
    bundle = make_raw_bundle(
        reporting_entities=_tree(all_cug=True),
        book_entity_mappings=_MAPPING,
        equity_exposures=equity,
    )

    # Act
    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    # Assert
    assert result.equity_exposures is not None
    assert _CARRIER not in result.equity_exposures.collect_schema().names()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _tree(*, all_cug: bool, reporting_entity_cug: bool = True) -> pl.DataFrame:
    flags = {"GRP": all_cug, "BANK_A": all_cug and reporting_entity_cug, "BANK_B": all_cug}
    return pl.DataFrame(
        {
            "entity_reference": list(_ENTITIES),
            "parent_entity_reference": list(_PARENTS),
            "core_uk_group": [flags[e] for e in _ENTITIES],
        }
    )


def _bundle(tree: pl.DataFrame):
    return make_raw_bundle(
        reporting_entities=tree,
        book_entity_mappings=_MAPPING,
        ccr=_ccr(),
        sft=_sft(),
    )


def _ccr() -> RawCCRBundle:
    # The carrier column is supplied explicitly so a stray input True can be shown
    # to be overwritten (CCR leaf frames are not re-sealed by the resolver).
    netting_sets = pl.DataFrame(
        [
            {
                "netting_set_id": ref,
                "counterparty_reference": cp,
                "book_code": "BOOK_A",
                "intragroup_entity_reference": tag,
                _CARRIER: stray,
            }
            for ref, cp, tag, stray in _ROWS
        ],
        schema={**dtypes_of(NETTING_SET_SCHEMA), _CARRIER: pl.Boolean},
    )
    trades = pl.DataFrame(
        [{"trade_id": f"T_{ref}", "netting_set_id": ref} for ref, *_ in _ROWS],
        schema=dtypes_of(TRADE_SCHEMA),
    )
    return RawCCRBundle(
        trades=TradeBundle(trades=trades.lazy()),
        netting_sets=NettingSetBundle(netting_sets=netting_sets.lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=pl.LazyFrame(schema=dtypes_of(MARGIN_AGREEMENT_SCHEMA))
        ),
        ccr_collateral=CCRCollateralBundle(
            ccr_collateral=pl.LazyFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))
        ),
    )


def _sft() -> RawSFTBundle:
    trades = pl.DataFrame(
        [
            {
                "trade_id": ref,
                "netting_set_id": f"SFT_NS_{ref}",
                "counterparty_reference": cp,
                "notional": 1_000_000.0,
                "currency": "GBP",
                "maturity_date": date(2026, 12, 31),
                "start_date": date(2026, 1, 1),
                "book_code": "BOOK_A",
                "intragroup_entity_reference": tag,
                _CARRIER: stray,
            }
            for ref, cp, tag, stray in _ROWS
        ]
    )
    sealed, _missing, _lossy = seal_lenient(trades.lazy(), SFT_TABLE_EDGES["sft_trades"])
    return RawSFTBundle(trades=SftTradeBundle(sft_trades=sealed))


def _resolve(bundle, entity: str, basis: ReportingBasis):
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 1), reporting_entity=entity, reporting_basis=basis
    )
    return resolver.resolve_scope(bundle, config, intragroup_zero_rw=True)


def _eligible(frame: pl.LazyFrame, key: str) -> dict[str, bool | None]:
    """Row key -> carrier value; asserts the resolver emitted the carrier at all."""
    df = frame.collect()
    assert _CARRIER in df.columns, f"the resolver did not set {_CARRIER} on this grain"
    return dict(zip(df[key].to_list(), df[_CARRIER].to_list(), strict=True))


def _keys(frame: pl.LazyFrame, key: str) -> list[str]:
    return sorted(frame.collect()[key].to_list())
