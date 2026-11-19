"""
RE-05 — PS1/26 Art. 123B(3): borrower income currency unknown; lending currency read pre-FX.

End-to-end through ``PipelineOrchestrator.run_with_data``, both regimes (C7).

Rule text (PS1/26 Appendix 1, quoted verbatim):

- Art. 123B(1): "an institution shall apply a 1.5 times multiplier to the applicable
  risk weight ... subject to a maximum risk weight of 150%, to any unhedged retail
  exposures or unhedged residential real estate exposures that are assigned to the
  exposure classes referred to in points (h) and (i) of Article 112(1) where: (a) the
  obligor is a natural person and the lending currency differs from the currency of
  the obligor's source of income".
- Art. 123B(3): "Where: (a) an institution is unable to identify those exposures with a
  currency mismatch which are subject to paragraph 1; and (b) the exposure was incurred
  prior to 1 January 2027, the institution shall apply the risk weight multiplier of
  1.5 to all unhedged retail exposures, and unhedged residential real estate exposures
  ..., except where the lending currency is the same as the domestic currency of the
  country of residence of the obligor or the country of employment of the obligor,
  subject to a maximum risk weight of 150%."

Scenario: GB-resident natural person, residential mortgage 80,000 at LTV 40% secured
on qualifying residential property, no FX rates unless stated.

Hand calculation (Basel 3.1): Art. 124F(1) loan split at LTV 40% -> whole loan inside
55% of value -> 20% (Art. 124F(2)). EUR loan with unknown income currency, GB obligor
(domestic GBP) -> 20% x 1.5 = 30% -> RWA 24,000 (was 20% / 16,000, no error).
GBP loan control -> lending currency is domestic -> 20% / 16,000.
CRR: Art. 125 35% -> 28,000 in every leg; no Art. 123B under CRR.

FX leg: with an EUR->GBP rate of 0.85 the EAD is 68,000 and ``currency`` is the
reporting currency GBP. A GBP earner's EUR mortgage is a mismatch -> 30% / 20,400
(was 20% / 13,600: the old test compared the reporting currency); an EUR earner's
EUR mortgage is not -> 20% / 13,600 (was 30% / 20,400).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_INCOME_CURRENCY_UNKNOWN
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

_LOAN = "RE05_MORTGAGE"
_DRAWN = 80_000.0
_EMPTY_FACILITY_MAPPINGS = pl.DataFrame(
    schema={
        "parent_facility_reference": pl.String,
        "child_reference": pl.String,
        "child_type": pl.String,
    }
)
_FX_RATES = pl.DataFrame(
    {"currency_from": ["EUR", "GBP"], "currency_to": ["GBP", "GBP"], "rate": [0.85, 1.0]}
)


def _run(
    regime: str,
    *,
    income: str | None,
    currency: str,
    value_date: date = date(2024, 1, 1),
    fx: bool = False,
) -> tuple[dict[str, Any], list[Any]]:
    counterparties = pl.DataFrame(
        {
            "counterparty_reference": ["RE05_NP"],
            "counterparty_name": ["RE05 natural person"],
            "entity_type": ["individual"],
            "country_code": ["GB"],
            "default_status": [False],
            "is_natural_person": [True],
            "is_managed_as_retail": [True],
            "borrower_income_currency": [income],
        },
        schema_overrides={"borrower_income_currency": pl.String},
    )
    loans = pl.DataFrame(
        {
            "loan_reference": [_LOAN],
            "product_type": ["mortgage"],
            "book_code": ["RETAIL"],
            "counterparty_reference": ["RE05_NP"],
            "value_date": [value_date],
            "maturity_date": [date(2045, 1, 1)],
            "currency": [currency],
            "drawn_amount": [_DRAWN],
            "interest": [0.0],
            "seniority": ["senior"],
        }
    )
    collateral = pl.DataFrame(
        {
            "collateral_reference": ["RE05_HOUSE"],
            "collateral_type": ["real_estate"],
            "currency": [currency],
            "market_value": [200_000.0],
            "nominal_value": [200_000.0],
            "beneficiary_type": ["loan"],
            "beneficiary_reference": [_LOAN],
            "property_type": ["residential"],
            "property_ltv": [0.4],
            "is_qualifying_re": [True],
            "valuation_date": [date(2026, 6, 30)],
            "valuation_type": ["market"],
        }
    )
    bundle = make_raw_bundle(
        counterparties=counterparties,
        loans=loans,
        collateral=collateral,
        facility_mappings=_EMPTY_FACILITY_MAPPINGS,
        fx_rates=_FX_RATES if fx else None,
    )
    if regime == "b31":
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 3, 31), permission_mode=PermissionMode.STANDARDISED
        )
    else:
        config = CalculationConfig.crr(
            reporting_date=date(2026, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    result = PipelineOrchestrator().run_with_data(bundle, config)
    rows = result.results.collect().filter(pl.col("exposure_reference") == _LOAN).to_dicts()
    assert len(rows) == 1, f"expected one result row for {_LOAN}, got {len(rows)}"
    return rows[0], list(result.errors)


def _sa010(errors: list[Any]) -> list[Any]:
    return [e for e in errors if e.code == ERROR_INCOME_CURRENCY_UNKNOWN]


class TestUnknownIncomeCurrency:
    @pytest.mark.parametrize(
        ("regime", "currency", "expected_rw"),
        [
            ("b31", "EUR", 0.30),  # 20% x 1.5 — lending currency is not GBP
            ("b31", "GBP", 0.20),  # lending currency is the GB domestic currency
            ("crr", "EUR", 0.35),
            ("crr", "GBP", 0.35),
        ],
    )
    def test_risk_weight_and_rwa(self, regime: str, currency: str, expected_rw: float) -> None:
        row, _ = _run(regime, income=None, currency=currency)

        assert row["exposure_class"] == "retail_mortgage"
        assert row["risk_weight"] == pytest.approx(expected_rw)
        assert row["rwa_final"] == pytest.approx(_DRAWN * expected_rw)

    def test_b31_pre_2027_exposure_raises_one_sa010(self) -> None:
        _, errors = _run("b31", income=None, currency="EUR", value_date=date(2024, 1, 1))

        sa010 = _sa010(errors)
        assert len(sa010) == 1
        assert "1 retail / residential real estate exposure(s)" in sa010[0].message
        assert "1 were incurred before 1 January 2027" in sa010[0].message

    def test_b31_post_2027_exposure_same_weight_and_counted_as_post(self) -> None:
        row, errors = _run("b31", income=None, currency="EUR", value_date=date(2027, 2, 1))

        assert row["risk_weight"] == pytest.approx(0.30)
        sa010 = _sa010(errors)
        assert len(sa010) == 1
        assert "0 were incurred before 1 January 2027" in sa010[0].message

    def test_b31_known_income_currency_raises_no_sa010(self) -> None:
        _, errors = _run("b31", income="GBP", currency="GBP")

        assert _sa010(errors) == []

    def test_crr_raises_no_sa010(self) -> None:
        _, errors = _run("crr", income=None, currency="EUR")

        assert _sa010(errors) == []


class TestLendingCurrencyAfterFxConversion:
    """With FX rates supplied, ``currency`` is the reporting currency; 123B reads the loan's."""

    @pytest.mark.parametrize(
        ("income", "expected_rw", "expected_applied"),
        [("GBP", 0.30, True), ("EUR", 0.20, False)],
    )
    def test_b31(self, income: str, expected_rw: float, expected_applied: bool) -> None:
        row, _ = _run("b31", income=income, currency="EUR", fx=True)

        assert row["ead_final"] == pytest.approx(_DRAWN * 0.85)
        assert row["currency_mismatch_multiplier_applied"] is expected_applied
        assert row["risk_weight"] == pytest.approx(expected_rw)
        assert row["rwa_final"] == pytest.approx(_DRAWN * 0.85 * expected_rw)

    def test_crr_unaffected(self) -> None:
        row, _ = _run("crr", income="GBP", currency="EUR", fx=True)

        assert row["risk_weight"] == pytest.approx(0.35)
        assert row["rwa_final"] == pytest.approx(_DRAWN * 0.85 * 0.35)
