"""
Tests for the equity ``is_main_index`` null-default flip (P1.237).

Why this matters:
    CRR Art. 224 Table 4 / PS1/26 Art. 224 Table 3 define two equity haircut
    tiers: main-index (CRR 15%, B31 20%) and other-listed (CRR 25%, B31 30%).
    An *unreported* ``is_main_index`` flag is not evidence the equity sits on
    a main index — treating it as main-index (the old
    ``fill_null(True)`` sentinel at ``engine/crm/haircuts.py:521``) is
    anti-conservative. Per CRR Art. 197(1)(f) / 198(1)(a), only equity
    positively identified as main-index earns the cheaper haircut; an
    unreported flag must fall back to the conservative other-listed haircut
    (``fill_null(False)``).

References:
    CRR Art. 224 Table 4: main-index 15%, other listed 25%
    CRR Art. 197(1)(f) / 198(1)(a): main-index eligibility gates
    PRA PS1/26 Art. 224 Table 3: main-index 20%, other listed 30%
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_equity_collateral(*, is_main_index: bool | None) -> pl.LazyFrame:
    """Build a minimal equity collateral LazyFrame for haircut testing.

    Mirrors ``tests/unit/crm/test_equity_main_index.py::_build_equity_collateral``
    (market_value 500,000, GBP = exposure currency, 10-day liquidation period).
    """
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
        "valuation_date": pl.Date,
        "valuation_type": pl.String,
        "property_type": pl.String,
        "property_ltv": pl.Float64,
        "is_income_producing": pl.Boolean,
        "is_adc": pl.Boolean,
        "is_presold": pl.Boolean,
        "is_qualifying_re": pl.Boolean,
        "prior_charge_ltv": pl.Float64,
        "liquidation_period_days": pl.Int32,
        "qualifies_for_zero_haircut": pl.Boolean,
        "insurer_risk_weight": pl.Float64,
        "credit_event_reduction": pl.Float64,
    }
    data: dict = {
        "collateral_reference": ["EQ_NULL"],
        "collateral_type": ["equity"],
        "currency": ["GBP"],
        "exposure_currency": ["GBP"],
        "maturity_date": [None],
        "market_value": [500_000.0],
        "nominal_value": [500_000.0],
        "pledge_percentage": [None],
        "beneficiary_type": ["loan"],
        "beneficiary_reference": ["LOAN1"],
        "issuer_cqs": [None],
        "issuer_type": [None],
        "residual_maturity_years": [None],
        "original_maturity_years": [None],
        "is_eligible_financial_collateral": [True],
        "is_eligible_irb_collateral": [True],
        "is_main_index": [is_main_index],
        "valuation_date": [date(2025, 12, 31)],
        "valuation_type": ["market"],
        "property_type": [None],
        "property_ltv": [None],
        "is_income_producing": [None],
        "is_adc": [None],
        "is_presold": [None],
        "is_qualifying_re": [None],
        "prior_charge_ltv": [None],
        # P1.186: 10 pinned explicitly so the test asserts 10-day base values.
        "liquidation_period_days": [10],
        "qualifies_for_zero_haircut": [None],
        "insurer_risk_weight": [None],
        "credit_event_reduction": [None],
    }
    return pl.LazyFrame(data, schema=schema)


def _run_haircuts(collateral_lf: pl.LazyFrame, *, is_basel_3_1: bool) -> pl.DataFrame:
    """Run the HaircutCalculator and return the collected result row."""
    calc = HaircutCalculator()
    config = (
        CalculationConfig.basel_3_1(reporting_date=date(2025, 12, 31))
        if is_basel_3_1
        else CalculationConfig.crr(reporting_date=date(2025, 12, 31))
    )
    result = calc.apply_haircuts(collateral_lf, config)
    return result.collect()


def _haircut_for(is_main_index: bool | None, *, is_basel_3_1: bool) -> float:
    df = _run_haircuts(_build_equity_collateral(is_main_index=is_main_index), is_basel_3_1=is_basel_3_1)
    return df["collateral_haircut"][0]


# ===========================================================================
# P1.237: null is_main_index defaults to the conservative other-listed
# haircut (25% CRR / 30% B31), not the cheaper main-index haircut.
# ===========================================================================


class TestP1237EquityMainIndexNullDefault:
    """Unreported is_main_index must resolve to the other-listed haircut."""

    def test_crr_null_gets_other_listed_haircut(self) -> None:
        df = _run_haircuts(_build_equity_collateral(is_main_index=None), is_basel_3_1=False)
        assert df["collateral_haircut"][0] == pytest.approx(0.25)
        assert df["value_after_haircut"][0] == pytest.approx(375_000.0)

    def test_b31_null_gets_other_listed_haircut(self) -> None:
        df = _run_haircuts(_build_equity_collateral(is_main_index=None), is_basel_3_1=True)
        assert df["collateral_haircut"][0] == pytest.approx(0.30)
        assert df["value_after_haircut"][0] == pytest.approx(350_000.0)

    def test_null_matches_explicit_false_crr(self) -> None:
        """Framework-agnostic directional guard: null behaves like explicit False."""
        null_haircut = _haircut_for(None, is_basel_3_1=False)
        false_haircut = _haircut_for(False, is_basel_3_1=False)
        assert null_haircut == pytest.approx(false_haircut)

    def test_null_matches_explicit_false_b31(self) -> None:
        null_haircut = _haircut_for(None, is_basel_3_1=True)
        false_haircut = _haircut_for(False, is_basel_3_1=True)
        assert null_haircut == pytest.approx(false_haircut)

    def test_null_exceeds_explicit_true_crr(self) -> None:
        """Null must NOT get the cheaper main-index haircut."""
        null_haircut = _haircut_for(None, is_basel_3_1=False)
        true_haircut = _haircut_for(True, is_basel_3_1=False)
        assert null_haircut > true_haircut

    def test_null_exceeds_explicit_true_b31(self) -> None:
        null_haircut = _haircut_for(None, is_basel_3_1=True)
        true_haircut = _haircut_for(True, is_basel_3_1=True)
        assert null_haircut > true_haircut
