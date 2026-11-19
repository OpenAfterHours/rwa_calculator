"""
Failed-trade settlement risk: the side that can lose, Column 3, and the type (CC-09).

Pipeline position:
    RawCCRBundle.failed_trades -> compute_failed_trade_rwa -> ccr stage rows

Key responsibilities under test (review item CC-09, 2026-11):
- Art. 378 price difference is charged on the side that can LOSE: a sale loses
  when the market value has fallen below the agreed price, a purchase when it
  has risen above it. An unknown side is charged the absolute difference and
  named by a CCR031 warning.
- Art. 379(1) Table 2 Column 3 (first leg paid, fewer than five days after the
  second leg) is an ordinary credit exposure of value transferred plus current
  positive exposure — not a zero own-funds row labelled ``dvp_pre_t5``.
- ``settlement_type`` is read case-insensitively ("DVP" is DvP).

Rule text (CRR Art. 378 — PS1/26 Art. 92(3)(ca) keeps Title V in CRR): "The
price difference is calculated as the difference between the agreed settlement
price for the debt instrument, equity, foreign currency or commodity in question
and its current market value, where the difference could involve a loss for the
credit institution." CRR Art. 379(1) Table 2: Column 3 "From first contractual
payment or delivery leg up to four days after second contractual payment or
delivery leg — Treat as an exposure"; Column 4 "From 5 business days post second
contractual payment or delivery leg until extinction of the transaction — Treat
as an exposure risk weighted at 1 250 %".
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    FailedTradesBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.validation import validate_bundle_values
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    FAILED_TRADE_SCHEMA,
    MARGIN_AGREEMENT_SCHEMA,
    NETTING_SET_SCHEMA,
    TRADE_SCHEMA,
)
from rwa_calc.engine.ccr.failed_trades import compute_failed_trade_rwa
from tests.fixtures.raw_bundle import make_raw_bundle

_CONFIG = CalculationConfig.crr(reporting_date=date(2026, 3, 31))


def _dvp(ref: str, *, agreed: float, mv: float, is_purchase: bool | None) -> dict[str, Any]:
    return {
        "failed_trade_id": ref,
        "counterparty_reference": "CP",
        "settlement_type": "dvp",
        "working_days_past_due": 20,
        "instrument_class": "equity",
        "agreed_settlement_price": agreed,
        "current_market_value": mv,
        "is_purchase": is_purchase,
    }


def _frame(rows: list[dict[str, Any]]) -> pl.LazyFrame:
    # Full schema: a key a row omits is a typed null.
    return pl.LazyFrame(rows, schema=dtypes_of(FAILED_TRADE_SCHEMA))


def _by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out = compute_failed_trade_rwa(_frame(rows), _CONFIG).collect()
    return {row["failed_trade_id"]: row for row in out.to_dicts()}


class TestPriceDifferenceSide:
    """Art. 378: the price difference counts only where it can be a loss."""

    def test_purchase_loses_when_the_market_value_has_risen(self) -> None:
        # Arrange: agreed 0.9m, MV 1.0m, 20 days (50%).
        rows = [_dvp("BUY_UP", agreed=900_000.0, mv=1_000_000.0, is_purchase=True)]

        # Act
        row = _by_id(rows)["BUY_UP"]

        # Assert (pre-fix: max(0, agreed - MV) = 0)
        assert row["price_difference"] == pytest.approx(100_000.0)
        assert row["own_funds_requirement"] == pytest.approx(50_000.0)
        assert row["failed_trade_rwa"] == pytest.approx(625_000.0)

    def test_purchase_has_no_loss_when_the_market_value_has_fallen(self) -> None:
        # Arrange: the purchaser keeps cash worth more than the instrument.
        rows = [_dvp("BUY_DOWN", agreed=1_000_000.0, mv=900_000.0, is_purchase=True)]

        # Act
        row = _by_id(rows)["BUY_DOWN"]

        # Assert (pre-fix: charged 100,000 x 50% = 50,000 of own funds)
        assert row["price_difference"] == 0.0
        assert row["own_funds_requirement"] == 0.0

    def test_sale_loses_when_the_market_value_has_fallen(self) -> None:
        # Arrange (control: the seller convention the engine always applied)
        rows = [_dvp("SELL_DOWN", agreed=1_000_000.0, mv=900_000.0, is_purchase=False)]

        # Act
        row = _by_id(rows)["SELL_DOWN"]

        # Assert
        assert row["own_funds_requirement"] == pytest.approx(50_000.0)

    def test_sale_has_no_loss_when_the_market_value_has_risen(self) -> None:
        # Arrange
        rows = [_dvp("SELL_UP", agreed=900_000.0, mv=1_000_000.0, is_purchase=False)]

        # Act / Assert
        assert _by_id(rows)["SELL_UP"]["own_funds_requirement"] == 0.0

    @pytest.mark.parametrize(("agreed", "mv"), [(1_000_000.0, 900_000.0), (900_000.0, 1e6)])
    def test_unknown_side_is_charged_the_absolute_difference(
        self, agreed: float, mv: float
    ) -> None:
        # Arrange: either side could be the losing one.
        rows = [_dvp("UNKNOWN", agreed=agreed, mv=mv, is_purchase=None)]

        # Act / Assert
        assert _by_id(rows)["UNKNOWN"]["own_funds_requirement"] == pytest.approx(50_000.0)

    def test_settlement_type_is_case_insensitive(self) -> None:
        # Arrange: "DVP" used to match neither branch and gave 0.
        rows = [
            {
                **_dvp("UPPER", agreed=1_000_000.0, mv=900_000.0, is_purchase=False),
                "settlement_type": "DVP",
            }
        ]

        # Act / Assert
        row = _by_id(rows)["UPPER"]
        assert row["regulatory_band"] == "dvp_16_30"
        assert row["own_funds_requirement"] == pytest.approx(50_000.0)


def _empty(schema: dict[str, Any]) -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(schema))


def _bundle_of(failed_trades: pl.LazyFrame) -> Any:
    ccr = RawCCRBundle(
        trades=TradeBundle(trades=_empty(TRADE_SCHEMA)),
        netting_sets=NettingSetBundle(netting_sets=_empty(NETTING_SET_SCHEMA)),
        margin_agreements=MarginAgreementBundle(margin_agreements=_empty(MARGIN_AGREEMENT_SCHEMA)),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=_empty(CCR_COLLATERAL_SCHEMA)),
        failed_trades=FailedTradesBundle(failed_trades=failed_trades),
    )
    return make_raw_bundle(ccr=ccr)


class TestUnknownSideWarning:
    """CCR031 (input gate): one warning per DvP trade whose side decides the charge."""

    def test_names_only_dvp_rows_without_a_side_and_with_a_difference(self) -> None:
        # Arrange
        rows = [
            _dvp("NO_SIDE", agreed=1_000_000.0, mv=900_000.0, is_purchase=None),
            _dvp("NO_SIDE_NO_DIFF", agreed=1_000_000.0, mv=1_000_000.0, is_purchase=None),
            _dvp("SIDED", agreed=1_000_000.0, mv=900_000.0, is_purchase=False),
        ]

        # Act
        errors = validate_bundle_values(_bundle_of(_frame(rows)))

        # Assert
        assert [(e.code, e.exposure_reference) for e in errors if e.code == "CCR031"] == [
            ("CCR031", "ft__NO_SIDE")
        ]

    def test_a_table_without_the_column_leaves_every_side_unknown(self) -> None:
        # Arrange: the column genuinely absent (LESSONS B1), not a typed null.
        rows = _frame([_dvp("NO_COLUMN", agreed=1e6, mv=9e5, is_purchase=None)])
        rows = rows.drop("is_purchase")
        assert "is_purchase" not in rows.collect_schema().names()

        # Act: the engine reads it as unknown ...
        row = compute_failed_trade_rwa(rows, _CONFIG).collect().row(0, named=True)
        # ... and so does the input gate.
        errors = [e for e in validate_bundle_values(_bundle_of(rows)) if e.code == "CCR031"]

        # Assert
        assert row["own_funds_requirement"] == pytest.approx(50_000.0)
        assert [e.exposure_reference for e in errors] == ["ft__NO_COLUMN"]


class TestFreeDeliveryColumns:
    """Art. 379(1) Table 2 Columns 2-4 for a non-DvP (free) delivery."""

    @staticmethod
    def _free(ref: str, *, days: int, transferred: float | None) -> dict[str, Any]:
        return {
            "failed_trade_id": ref,
            "counterparty_reference": "CP",
            "settlement_type": "non_dvp_free_delivery",
            "working_days_past_due": days,
            "instrument_class": "debt",
            "value_transferred": transferred,
            "current_positive_exposure": 0.0,
        }

    def test_column_3_is_an_exposure_not_an_own_funds_amount(self) -> None:
        # Arrange: first leg paid (1m), two days after the second leg.
        rows = [self._free("COL3", days=2, transferred=1_000_000.0)]

        # Act
        row = _by_id(rows)["COL3"]

        # Assert (pre-fix: band "dvp_pre_t5", exposure dropped, own funds 0)
        assert row["regulatory_band"] == "non_dvp_col3"
        assert row["exposure_amount"] == pytest.approx(1_000_000.0)
        assert row["own_funds_requirement"] is None, "risk-weighted downstream"
        assert row["failed_trade_rwa"] is None

    def test_column_2_has_no_charge(self) -> None:
        # Arrange: nothing transferred yet.
        rows = [self._free("COL2", days=2, transferred=0.0)]

        # Act
        row = _by_id(rows)["COL2"]

        # Assert
        assert row["regulatory_band"] == "non_dvp_col2"
        assert row["own_funds_requirement"] == 0.0

    def test_column_4_is_unchanged(self) -> None:
        # Arrange (control)
        rows = [self._free("COL4", days=5, transferred=1_000_000.0)]

        # Act
        row = _by_id(rows)["COL4"]

        # Assert
        assert row["regulatory_band"] == "non_dvp_col4_t5_plus"
        assert row["own_funds_requirement"] == pytest.approx(1_000_000.0)
