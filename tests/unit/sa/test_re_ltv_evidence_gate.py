"""
Unit tests: the SA dispatchers' real-estate LTV gate (review CL-08 / RE-10).

Pipeline position:
    CRMProcessor -> SACalculator (engine/sa/risk_weights.py,
    engine/sa/b31_risk_weight_tables.py::b31_real_estate_route)

Key responsibilities pinned here, in BOTH regimes:
- A real-estate class with NO LTV and NO property data — a mortgage product
  label — is not priced on the LTV tables; it takes its counterparty-class
  weight. This matters for the rows the classifier does not re-class: IRB rows,
  whose Standardised-equivalent weight is the Basel 3.1 output floor.
  Pre-fix: CRR filled the null LTV to 0.0 (35%), Basel 3.1 to 1.0 (44.75%).
- Property data with no LTV (an unvalued property) is still real estate:
  Basel 3.1 Art. 124J (Art. 124A(1)(d) cannot be met), CRR Art. 124(1) 100% for
  commercial property. Neither may come out BELOW its pre-fix weight.
- A known LTV keeps the regulatory-RE tables (the controls).

Rule text (verbatim):
- CRR Art. 125(2)(d): "the part of the loan to which the 35 % risk weight is
  assigned does not exceed 80 % of the market value of the property in question".
- CRR Art. 124(1): "An exposure or any part of an exposure fully and completely
  secured by mortgages on immovable property shall be assigned a risk weight of
  100 %, where the conditions set out in Article 125 or 126 are not met".
- PS1/26 Art. 124A(1): "A real estate exposure is a regulatory real estate
  exposure if ... (d) the value of the property is determined in accordance
  with Article 124D".
- PS1/26 Art. 124J(3): "... a risk weight that is the higher of: (a) 60%; and
  (b) the risk weight of the counterparty in accordance with Article 124L."

References:
- CRR Art. 124, 125, 126; PS1/26 Art. 124A, 124F, 124J, 124L
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa import SACalculator
from tests.fixtures.single_exposure import calculate_single_sa_exposure


@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()


def _config(regime: str) -> CalculationConfig:
    if regime == "b31":
        return CalculationConfig.basel_3_1(reporting_date=date(2027, 3, 31))
    return CalculationConfig.crr(reporting_date=date(2026, 12, 31))


def _risk_weight(sa_calculator: SACalculator, regime: str, **kwargs: object) -> float:
    result = calculate_single_sa_exposure(
        sa_calculator, ead=Decimal("100000"), config=_config(regime), **kwargs
    )
    return float(result["risk_weight"])


class TestMortgageLabelWithoutLtv:
    """No LTV, no property data: counterparty-class (regulatory retail) weight."""

    @pytest.mark.parametrize(
        ("regime", "pre_fix_rw"),
        [("crr", 0.35), ("b31", 0.4475)],
    )
    def test_retail_mortgage_without_ltv_takes_the_retail_weight(
        self, sa_calculator: SACalculator, regime: str, pre_fix_rw: float
    ) -> None:
        # Act
        rw = _risk_weight(
            sa_calculator,
            regime,
            exposure_class="retail_mortgage",
            ltv=None,
            cp_is_natural_person=True,
            qualifies_as_retail=True,
        )

        # Assert: CRR Art. 123 / PS1/26 Art. 123 regulatory retail 75%.
        assert rw == pytest.approx(0.75)
        assert rw != pytest.approx(pre_fix_rw)

    @pytest.mark.parametrize(
        ("regime", "expected_rw"),
        [
            # CRR Art. 125: LTV 0.60 <= 0.80 -> 35%.
            ("crr", 0.35),
            # B31 Art. 124F: 20% x 0.55/0.60 + 75% x 0.05/0.60.
            ("b31", (0.2 * 0.55 + 0.75 * 0.05) / 0.60),
        ],
    )
    def test_retail_mortgage_with_ltv_keeps_the_real_estate_weight(
        self, sa_calculator: SACalculator, regime: str, expected_rw: float
    ) -> None:
        rw = _risk_weight(
            sa_calculator,
            regime,
            exposure_class="retail_mortgage",
            ltv=Decimal("0.60"),
            cp_is_natural_person=True,
            qualifies_as_retail=True,
        )
        assert rw == pytest.approx(expected_rw)


class TestUnvaluedPropertyStaysRealEstate:
    """Property data with no LTV is still a real-estate exposure — never cheaper."""

    @pytest.mark.parametrize(
        ("regime", "income_cover", "expected_rw", "pre_fix_rw"),
        [
            # CRR Art. 124(1): CRE not meeting Art. 126 -> 100%. Pre-fix, with
            # income cover, the Art. 126 blend at an assumed LTV of 1.0 gave
            # 50% x 0.5 + 20% x 0.5 = 35%.
            ("crr", True, 1.00, 0.35),
            ("crr", False, 1.00, 1.00),
            # B31 Art. 124J(1): materially dependent on the property -> 150%.
            # Pre-fix Art. 124I at an assumed LTV of 1.0 -> 110%.
            ("b31", True, 1.50, 1.10),
            # B31 Art. 124J(3): max(60%, Art. 124L(e) counterparty RW 20%) = 60%.
            # Pre-fix Art. 124H(3): max(60%, min(20%, 124I)) = 60%.
            ("b31", False, 0.60, 0.60),
        ],
    )
    def test_rated_corporate_on_unvalued_commercial_property(
        self,
        sa_calculator: SACalculator,
        regime: str,
        income_cover: bool,
        expected_rw: float,
        pre_fix_rw: float,
    ) -> None:
        rw = _risk_weight(
            sa_calculator,
            regime,
            exposure_class="corporate",
            cqs=1,
            ltv=None,
            property_type="commercial",
            has_income_cover=income_cover,
        )
        assert rw == pytest.approx(expected_rw)
        assert rw >= pre_fix_rw, "an unvalued property must never price below the old fill"

    def test_b31_unvalued_residential_property_is_art_124j(
        self, sa_calculator: SACalculator
    ) -> None:
        """Art. 124J(2): the Art. 124L(a) natural-person 75% (pre-fix 124F 44.75%)."""
        rw = _risk_weight(
            sa_calculator,
            "b31",
            exposure_class="retail_mortgage",
            ltv=None,
            property_type="residential",
            cp_is_natural_person=True,
            qualifies_as_retail=True,
        )
        assert rw == pytest.approx(0.75)
