"""
P1.271 — CRR/PS1-26 Art. 197(1)(f)/198(1)(a): non-main-index equity is eligible
financial collateral only if listed on a recognised exchange.

Why this matters:
    Art. 197(1)(f) makes equities/convertible bonds included in a MAIN index
    eligible under all CRM methods. Art. 198(1)(a) extends eligibility to
    non-main-index equities ONLY where they are listed on a recognised exchange
    (and only under the comprehensive method). An equity that is neither attested
    main-index nor attested listed must not be recognised as collateral.

    The supervisory haircut (Art. 224 Table 3/4: other-listed 25% CRR / 30% B31)
    is a VALUATION parameter and is left intact; eligibility is a SEPARATE gate
    that zeroes the collateral value and clears is_eligible_financial_collateral.

References:
    CRR/PS1-26 Art. 197(1)(f): main-index equities eligible under all methods.
    CRR/PS1-26 Art. 198(1)(a): non-main-index equities eligible only if listed.
    CRR Art. 224 Table 3/4: equity supervisory haircut bands.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.crm.haircuts import HaircutCalculator

if TYPE_CHECKING:
    from polars._typing import PolarsDataType

_REPORTING_DATE = date(2025, 12, 31)


def _build_equity_collateral(
    *,
    is_main_index: bool | None,
    is_listed: bool | None,
    market_value: float = 100_000.0,
) -> pl.LazyFrame:
    """Build a minimal non-main-index-capable equity collateral LazyFrame."""
    schema: dict[str, PolarsDataType] = {
        "collateral_reference": pl.String,
        "collateral_type": pl.String,
        "currency": pl.String,
        "exposure_currency": pl.String,
        "maturity_date": pl.Date,
        "market_value": pl.Float64,
        "nominal_value": pl.Float64,
        "pledge_percentage": pl.Float64,
        "beneficiary_type": pl.String,
        "beneficiary_reference": pl.String,
        "issuer_cqs": pl.Int8,
        "issuer_type": pl.String,
        "residual_maturity_years": pl.Float64,
        "original_maturity_years": pl.Float64,
        "is_eligible_financial_collateral": pl.Boolean,
        "is_eligible_irb_collateral": pl.Boolean,
        "is_main_index": pl.Boolean,
        "is_listed": pl.Boolean,
        "valuation_date": pl.Date,
        "valuation_type": pl.String,
        "property_type": pl.String,
        "property_ltv": pl.Float64,
        "is_income_producing": pl.Boolean,
        "is_adc": pl.Boolean,
        "is_presold": pl.Boolean,
        "liquidation_period_days": pl.Int32,
        "qualifies_for_zero_haircut": pl.Boolean,
    }
    return pl.LazyFrame(
        {
            "collateral_reference": ["EQ1"],
            "collateral_type": ["equity"],
            "currency": ["GBP"],
            "exposure_currency": ["GBP"],
            "maturity_date": [None],
            "market_value": [market_value],
            "nominal_value": [market_value],
            "pledge_percentage": [None],
            "beneficiary_type": ["loan"],
            "beneficiary_reference": ["LOAN1"],
            "issuer_cqs": [None],
            "issuer_type": ["corporate"],
            "residual_maturity_years": [None],
            "original_maturity_years": [None],
            "is_eligible_financial_collateral": [True],
            "is_eligible_irb_collateral": [True],
            "is_main_index": [is_main_index],
            "is_listed": [is_listed],
            "valuation_date": [_REPORTING_DATE],
            "valuation_type": ["market"],
            "property_type": [None],
            "property_ltv": [None],
            "is_income_producing": [None],
            "is_adc": [None],
            "is_presold": [None],
            # 10-day base haircut → 25% CRR / 30% B31 for other-listed equity.
            "liquidation_period_days": [10],
            "qualifies_for_zero_haircut": [None],
        },
        schema=schema,
    )


def _apply(collateral: pl.LazyFrame, *, is_basel_3_1: bool = False) -> dict:
    calc = HaircutCalculator()
    config = (
        CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE)
        if is_basel_3_1
        else CalculationConfig.crr(reporting_date=_REPORTING_DATE)
    )
    return calc.apply_haircuts(collateral, config).collect().to_dicts()[0]


class TestNonMainIndexEquityListingGate:
    """Art. 198(1)(a): non-main-index equity needs a recognised-exchange listing."""

    def test_unlisted_non_main_index_equity_is_ineligible(self) -> None:
        """LOAD-BEARING: null is_listed on non-main-index equity → value zeroed."""
        row = _apply(_build_equity_collateral(is_main_index=None, is_listed=None))
        assert row["value_after_haircut"] == pytest.approx(0.0)
        assert row["is_eligible_financial_collateral"] is False

    def test_explicit_unlisted_non_main_index_equity_is_ineligible(self) -> None:
        """is_listed=False on non-main-index equity → value zeroed."""
        row = _apply(_build_equity_collateral(is_main_index=None, is_listed=False))
        assert row["value_after_haircut"] == pytest.approx(0.0)
        assert row["is_eligible_financial_collateral"] is False

    def test_listed_non_main_index_equity_is_eligible_crr(self) -> None:
        """is_listed=True → recognised at the 25% CRR other-listed haircut."""
        row = _apply(_build_equity_collateral(is_main_index=None, is_listed=True))
        # 100_000 × (1 − 0.25) = 75_000
        assert row["value_after_haircut"] == pytest.approx(75_000.0)
        assert row["is_eligible_financial_collateral"] is True

    def test_listed_non_main_index_equity_is_eligible_b31(self) -> None:
        """is_listed=True → recognised at the 30% Basel 3.1 other-listed haircut."""
        row = _apply(
            _build_equity_collateral(is_main_index=None, is_listed=True), is_basel_3_1=True
        )
        # 100_000 × (1 − 0.30) = 70_000
        assert row["value_after_haircut"] == pytest.approx(70_000.0)
        assert row["is_eligible_financial_collateral"] is True

    def test_main_index_equity_eligible_regardless_of_listing(self) -> None:
        """Art. 197(1)(f): main-index equity is eligible even with null is_listed."""
        row = _apply(_build_equity_collateral(is_main_index=True, is_listed=None))
        # main-index 15% CRR haircut: 100_000 × 0.85 = 85_000
        assert row["value_after_haircut"] == pytest.approx(85_000.0)
        assert row["is_eligible_financial_collateral"] is True

    def test_haircut_preserved_on_ineligible_row(self) -> None:
        """The 25% other-listed haircut is a valuation parameter, not the gate:
        it is preserved even when the row is ruled ineligible (value zeroed)."""
        row = _apply(_build_equity_collateral(is_main_index=None, is_listed=None))
        assert row["collateral_haircut"] == pytest.approx(0.25)
