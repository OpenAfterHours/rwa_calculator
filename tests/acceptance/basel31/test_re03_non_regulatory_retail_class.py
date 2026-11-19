"""
RE-03 — a natural person that fails regulatory retail stays retail under Basel 3.1.

End-to-end through ``PipelineOrchestrator.run_with_data`` on an in-memory bundle,
both regimes (LESSONS C7), SA permission mode.

Rule text (read from the primary sources, quoted verbatim):

- PS1/26 Art. 123(1): "an exposure shall be categorised as a retail exposure if it
  is either: (a) an exposure to one or more natural persons and not an exposure to
  an SME".
- PS1/26 Art. 123(3)(c): "all other retail exposures that do not qualify as
  regulatory retail exposures shall be assigned a risk weight of 100%".
- PS1/26 Art. 123B(1): "an institution shall apply a 1.5 times multiplier to the
  applicable risk weight ... subject to a maximum risk weight of 150%, to any
  unhedged retail exposures ... where: (a) the obligor is a natural person and the
  lending currency differs from the currency of the obligor's source of income".
- CRR Art. 123 (last sub-paragraph): "Exposures that do not comply with the criteria
  referred to in points (a) to (c) of the first subparagraph shall not be eligible
  for the retail exposures class."

Hand calculation (EUR 1,000,000 personal loan, no FX rates supplied, so EAD is the
drawn amount; GBP income; pool-managed natural person):

- Basel 3.1: aggregate 1,000,000 > GBP 880,000 -> not regulatory retail, but still
  retail (Art. 123(1)(a)) -> 100% (Art. 123(3)(c)) x 1.5 (Art. 123B(1)(a), EUR vs
  GBP, unhedged) = 150% (= the 150% cap) -> RWA 1,500,000.
  Before RE-03: class ``corporate``, 100%, no multiplier, RWA 1,000,000.
- CRR: aggregate 1,000,000 > EUR 1m x 0.8732 -> not eligible for the retail class
  -> ``corporate`` 100%, RWA 1,000,000 (unchanged; no Art. 123B under CRR).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

_B31_DATE = date(2027, 3, 31)
_CRR_DATE = date(2026, 12, 31)
_LOAN = "RE03_EUR_PERSONAL"
_DRAWN = 1_000_000.0

_EMPTY_FACILITY_MAPPINGS = pl.DataFrame(
    schema={
        "parent_facility_reference": pl.String,
        "child_reference": pl.String,
        "child_type": pl.String,
    }
)


def _bundle(*, is_managed_as_retail: bool, currency: str, drawn: float) -> Any:
    counterparties = pl.DataFrame(
        {
            "counterparty_reference": ["RE03_NP"],
            "counterparty_name": ["RE03 natural person"],
            "entity_type": ["individual"],
            "country_code": ["GB"],
            "default_status": [False],
            "is_natural_person": [True],
            "is_managed_as_retail": [is_managed_as_retail],
            "borrower_income_currency": ["GBP"],
        }
    )
    loans = pl.DataFrame(
        {
            "loan_reference": [_LOAN],
            "product_type": ["personal_loan"],
            "book_code": ["RETAIL"],
            "counterparty_reference": ["RE03_NP"],
            "value_date": [date(2026, 6, 1)],
            "maturity_date": [date(2031, 6, 1)],
            "currency": [currency],
            "drawn_amount": [drawn],
            "interest": [0.0],
            "seniority": ["senior"],
        }
    )
    return make_raw_bundle(
        counterparties=counterparties,
        loans=loans,
        facility_mappings=_EMPTY_FACILITY_MAPPINGS,
    )


def _run(regime: str, **bundle_kwargs: Any) -> dict[str, Any]:
    if regime == "b31":
        config = CalculationConfig.basel_3_1(
            reporting_date=_B31_DATE, permission_mode=PermissionMode.STANDARDISED
        )
    else:
        config = CalculationConfig.crr(
            reporting_date=_CRR_DATE, permission_mode=PermissionMode.STANDARDISED
        )
    result = PipelineOrchestrator().run_with_data(_bundle(**bundle_kwargs), config)
    df = result.results.collect().filter(pl.col("exposure_reference") == _LOAN)
    assert df.height == 1, f"expected one result row for {_LOAN}, got {df.height}"
    return df.to_dicts()[0]


class TestOverThresholdForeignCurrencyLoan:
    """Pool-managed natural person, EUR 1,000,000 personal loan, GBP income."""

    def test_b31_stays_retail_other_with_currency_mismatch_multiplier(self) -> None:
        row = _run("b31", is_managed_as_retail=True, currency="EUR", drawn=_DRAWN)

        assert row["exposure_class"] == "retail_other"
        assert row["currency_mismatch_multiplier_applied"] is True
        assert row["risk_weight"] == pytest.approx(1.50)
        assert row["rwa_final"] == pytest.approx(1_500_000.0)

    def test_crr_leaves_retail_class_for_corporate(self) -> None:
        row = _run("crr", is_managed_as_retail=True, currency="EUR", drawn=_DRAWN)

        assert row["exposure_class"] == "corporate"
        assert row["risk_weight"] == pytest.approx(1.00)
        assert row["rwa_final"] == pytest.approx(1_000_000.0)


class TestIndividuallyManagedDomesticLoan:
    """``is_managed_as_retail=False`` (the loader default when the flag is omitted).

    Art. 123A(1)(b)(iii) fails, so the exposure is not regulatory retail; under
    Basel 3.1 it is still a retail exposure at 100% — the same weight the old
    CORPORATE routing produced, so only the class moves. CRR ignores the flag for
    natural persons (threshold test only) and keeps the 75% regulatory weight.
    """

    @pytest.mark.parametrize(
        ("regime", "expected_class", "expected_rw"),
        [("b31", "retail_other", 1.00), ("crr", "retail_other", 0.75)],
    )
    def test_class_and_weight(self, regime: str, expected_class: str, expected_rw: float) -> None:
        row = _run(regime, is_managed_as_retail=False, currency="GBP", drawn=50_000.0)

        assert row["exposure_class"] == expected_class
        assert row["risk_weight"] == pytest.approx(expected_rw)
        assert row["rwa_final"] == pytest.approx(50_000.0 * expected_rw)
