"""
FCCM SFT review-cluster builders: Basel 3.1 haircut table, Art. 197/198
eligibility of SFT securities, and master-netting eligibility (CC-12/13/14).

Pipeline position:
    fixture-builder output -> tests/unit/sft/*, tests/acceptance/ccr/
    test_sft_fccm_haircut_eligibility_netting.py -> engine SFT FCCM stage
    (engine/stages/sft.py -> engine/sft/fccm.py, engine/sft/netting.py)

The frames are small in-memory dicts sealed through the SAME loader seal
(``SFT_TABLE_EDGES`` / ``seal_lenient``) as a production SFT load, so the
bundles satisfy the ``raw_sft_trades`` / ``raw_sft_collateral`` brands and carry
every declared column (absent optional columns backfilled to their defaults).
No parquet is written: nothing here needs registering in ``generate_all.py``.

Counterparties (both GB institutions, external ratings):
- ``CP_INST_001`` — CQS 2: CRR Art. 120(1) Table 3 50%; PS1/26 Art. 120 ECRA 30%.
- ``SFT_REVIEW_CP_CQS4`` — CQS 4: 100% in both regimes. Distinct from CP 1's
  weight, so a netting set booked against the wrong counterparty moves RWA.

Every trade matures more than three months after both reporting dates, so the
Art. 120(2) short-term institution weights never apply.

References:
- CRR / PS1/26 Art. 220(1), 223(5), 224 Tables 1/3, 224(2)(b), 224(4), 206.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from rwa_calc.contracts.bundles import (
    RawDataBundle,
    RawSFTBundle,
    SftCollateralBundle,
    SftTradeBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import SFT_TABLE_EDGES, seal_lenient
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, RATINGS_SCHEMA
from rwa_calc.domain.enums import PermissionMode
from tests.fixtures.ccr.golden_ccr_a11_a12 import (
    CCR_A11_A12_COUNTERPARTY_REF,
    _build_cp_inst_001_counterparty,
    _build_cp_inst_001_rating,
    _build_empty_facilities,
    _build_empty_facility_mappings,
    _build_empty_lending_mappings,
    _build_empty_loans,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

SFT_REVIEW_CRR_REPORTING_DATE: date = date(2026, 6, 30)
SFT_REVIEW_B31_REPORTING_DATE: date = date(2027, 6, 30)

SFT_REVIEW_CP_CQS2: str = CCR_A11_A12_COUNTERPARTY_REF
SFT_REVIEW_CP_CQS4: str = "CP_INST_SFT_CQS4"

#: SA institution risk weight of each counterparty, per regime.
SFT_REVIEW_RISK_WEIGHT: dict[str, dict[str, float]] = {
    "crr": {SFT_REVIEW_CP_CQS2: 0.50, SFT_REVIEW_CP_CQS4: 1.00},
    "b31": {SFT_REVIEW_CP_CQS2: 0.30, SFT_REVIEW_CP_CQS4: 1.00},
}

SFT_REVIEW_NOTIONAL: float = 100_000_000.0


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def sft_review_config(regime: str) -> CalculationConfig:
    """Return the SA-only run config for ``regime`` ("crr" | "b31")."""
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=SFT_REVIEW_CRR_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        )
    return CalculationConfig.basel_3_1(
        reporting_date=SFT_REVIEW_B31_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


def sft_trade(trade_id: str, netting_set_id: str, **overrides: Any) -> dict[str, Any]:
    """One SFT trade row: cash lent GBP 100m to CP_INST_001 unless overridden."""
    row: dict[str, Any] = {
        "trade_id": trade_id,
        "netting_set_id": netting_set_id,
        "counterparty_reference": SFT_REVIEW_CP_CQS2,
        "notional": SFT_REVIEW_NOTIONAL,
        "currency": "GBP",
        "start_date": date(2026, 6, 1),
        "maturity_date": date(2028, 6, 30),
    }
    row.update(overrides)
    return row


def sft_collateral(
    reference: str, netting_set_id: str, collateral_type: str | None, market_value: float, **kw: Any
) -> dict[str, Any]:
    """One SFT collateral row in GBP (same currency as the trades: HFX = 0)."""
    row: dict[str, Any] = {
        "sft_collateral_reference": reference,
        "netting_set_id": netting_set_id,
        "collateral_type": collateral_type,
        "market_value": market_value,
        "currency": "GBP",
    }
    row.update(kw)
    return row


def build_sft_bundle(
    trades: list[dict[str, Any]],
    collateral: list[dict[str, Any]] | None = None,
) -> RawSFTBundle:
    """Seal trade / collateral rows exactly as the loader does and wrap them."""
    trades_df = pl.DataFrame(trades, schema_overrides=_present(trades, "sft_trades"))
    sealed_trades, *_ = seal_lenient(trades_df.lazy(), SFT_TABLE_EDGES["sft_trades"])
    if collateral is None:
        return RawSFTBundle(trades=SftTradeBundle(sft_trades=sealed_trades), collateral=None)
    coll_df = pl.DataFrame(collateral, schema_overrides=_present(collateral, "sft_collateral"))
    sealed_coll, *_ = seal_lenient(coll_df.lazy(), SFT_TABLE_EDGES["sft_collateral"])
    return RawSFTBundle(
        trades=SftTradeBundle(sft_trades=sealed_trades),
        collateral=SftCollateralBundle(sft_collateral=sealed_coll),
    )


def build_raw_data_bundle_sft_review(sft: RawSFTBundle) -> RawDataBundle:
    """Assemble a full RawDataBundle: the two institution counterparties + ``sft``."""
    counterparties = pl.concat(
        [_build_cp_inst_001_counterparty(), _cp_cqs4_counterparty()], how="vertical"
    )
    ratings = pl.concat([_build_cp_inst_001_rating(), _cp_cqs4_rating()], how="vertical")
    return make_raw_bundle(
        counterparties=counterparties,
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=ratings,
        sft=sft,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _present(rows: list[dict[str, Any]], table: str) -> dict[str, pl.DataType]:
    """Declared dtypes of the columns the rows actually carry (all-null safe)."""
    declared = SFT_TABLE_EDGES[table].columns
    names = {name for row in rows for name in row}
    return {name: declared[name].dtype for name in names if name in declared}


def _cp_cqs4_counterparty() -> pl.LazyFrame:
    row = {
        "counterparty_reference": SFT_REVIEW_CP_CQS4,
        "counterparty_name": "SFT review institution (CQS 4)",
        "entity_type": "institution",
        "country_code": "GB",
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": 4,
    }
    return pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA)).lazy()


def _cp_cqs4_rating() -> pl.LazyFrame:
    row = {
        "rating_reference": "RTG_INST_SFT_CQS4",
        "counterparty_reference": SFT_REVIEW_CP_CQS4,
        "rating_type": "external",
        "rating_agency": "S&P",
        "rating_value": "BB",
        "cqs": 4,
        "pd": None,
        "rating_date": date(2026, 1, 15),
        "is_solicited": True,
        "model_id": None,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(RATINGS_SCHEMA)).lazy()
