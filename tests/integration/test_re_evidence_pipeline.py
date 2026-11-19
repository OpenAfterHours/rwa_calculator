"""
Integration tests: real-estate evidence through the full pipeline (RE-01, RE-02,
RE-10, CL-08).

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
        -> RealEstateSplitter -> SACalculator -> Aggregator

Key responsibilities (each pinned in BOTH regimes, hand-calculated):
- RE-01: an ``is_adc`` flag supplied on a COLLATERAL row reaches the exposure,
  so ADC lending is no longer loan-split onto the regulatory-RE tables.
- RE-02: a collateral ``is_presold`` flag reaches the Basel 3.1 ADC weight, so
  the Art. 124K(2) 100% residential-ADC weight is reachable.
- RE-10: a property supplied without ``property_ltv`` is priced on its derived
  LTV (amount of the loan / value of the property), not on a filled one.
- CL-08: a mortgage-labelled loan with no property collateral and no LTV is not
  given preferential real-estate weights; it takes its counterparty class and a
  ``RE005`` warning.

Rule text relied on (quoted verbatim from the primary text):
- PS1/26 Art. 124(3): "An institution shall apply the risk weights set out in
  Article 124K to ADC exposures."
- PS1/26 Art. 124K(1): "Subject to paragraph 2, an institution shall assign a
  risk weight of 150% to an ADC exposure."
- PS1/26 Art. 124K(2): "An institution may assign a risk weight of 100% to an ADC
  exposure financing ... the development and construction of residential real
  estate if: (a) the exposure is subject to prudent underwriting standards ...;
  and (b) at least one of the following conditions is met: (i) legally binding
  pre-sale or pre-lease contracts ... amount to a significant portion of total
  contracts; or (ii) the borrower has substantial equity at risk."
- PS1/26 Glossary, "ADC exposure": "means an exposure to a corporate or special
  purpose entity financing any land acquisition for development and construction
  purposes, or financing development and construction of any residential real
  estate or commercial real estate."
- PS1/26 Glossary, "real estate exposure": "means an ADC exposure or an exposure
  secured by a charge on immovable property."
- PS1/26 Art. 124C(1): "The loan-to-value (LTV) ... is the amount of the loan
  divided by the value of the property." Art. 124C(2): "The amount of the loan
  shall include the outstanding loan amount and any undrawn committed amount of
  the mortgage loan ..."
- CRR Art. 125(1)(a): "exposures or any part of an exposure fully and completely
  secured by mortgages on residential property which is or shall be occupied or
  let by the owner ... shall be assigned a risk weight of 35 %"; Art. 125(2)(d):
  "the part of the loan to which the 35 % risk weight is assigned does not exceed
  80 % of the market value of the property in question".
- CRR Art. 124(1): "An exposure or any part of an exposure fully and completely
  secured by mortgages on immovable property shall be assigned a risk weight of
  100 %, where the conditions set out in Article 125 or 126 are not met".

References:
- PS1/26 Art. 124, 124A, 124C, 124F, 124K, 124L
- CRR Art. 124, 125
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

_INDIVIDUAL: dict[str, Any] = {
    "counterparty_reference": "CP1",
    "counterparty_name": "CP1",
    "entity_type": "individual",
    "country_code": "GB",
    "annual_revenue": None,
    "total_assets": None,
    "default_status": False,
    "is_natural_person": True,
    "is_managed_as_retail": True,
}

_DEVELOPER: dict[str, Any] = {
    **_INDIVIDUAL,
    "entity_type": "corporate",
    "annual_revenue": 100_000_000.0,
    "is_natural_person": False,
    "is_managed_as_retail": False,
}


def _loan(drawn: float, product: str, **extra: Any) -> dict[str, Any]:
    return {
        "loan_reference": "L1",
        "product_type": product,
        "book_code": "B",
        "counterparty_reference": "CP1",
        "value_date": date(2024, 1, 1),
        "maturity_date": date(2045, 1, 1),
        "currency": "GBP",
        "drawn_amount": drawn,
        "interest": 0.0,
        "seniority": "senior",
        **extra,
    }


def _property(market_value: float, property_type: str, ltv: float | None, **extra: Any) -> dict:
    return {
        "collateral_reference": "C1",
        "collateral_type": "real_estate",
        "currency": "GBP",
        "market_value": market_value,
        "nominal_value": market_value,
        "beneficiary_type": "loan",
        "beneficiary_reference": "L1",
        "property_type": property_type,
        "property_ltv": ltv,
        "is_qualifying_re": True,
        **extra,
    }


def _frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    keys: list[str] = []
    for row in rows:
        keys.extend(k for k in row if k not in keys)
    return pl.DataFrame({k: [row.get(k) for row in rows] for k in keys}, strict=False)


def _run(
    regime: str,
    counterparty: dict[str, Any],
    loan: dict[str, Any],
    collateral: list[dict[str, Any]] | None,
    *,
    enforce_retail_granularity: bool = True,
) -> tuple[pl.DataFrame, list[str]]:
    """Run the full pipeline on a one-loan bundle; return (results, error codes).

    ``enforce_retail_granularity=False`` switches off the Basel 3.1
    Art. 123A(1)(b)(ii) 0.2% limb, which a one-obligor portfolio always fails,
    so a natural person can be regulatory retail here.
    """
    kwargs: dict[str, Any] = {}
    if collateral is not None:
        kwargs["collateral"] = _frame(collateral)
    bundle = make_raw_bundle(
        counterparties=_frame([counterparty]),
        loans=_frame([loan]),
        facility_mappings=pl.DataFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        **kwargs,
    )
    if regime == "b31":
        config = CalculationConfig.basel_3_1(
            reporting_date=_B31_DATE,
            permission_mode=PermissionMode.STANDARDISED,
            enforce_retail_granularity=enforce_retail_granularity,
        )
    else:
        config = CalculationConfig.crr(
            reporting_date=_CRR_DATE, permission_mode=PermissionMode.STANDARDISED
        )
    result = PipelineOrchestrator().run_with_data(bundle, config)
    return result.results.collect(), [error.code for error in result.errors]


def _single(df: pl.DataFrame) -> dict[str, Any]:
    """The one ledger row a whole (unsplit) exposure produces."""
    assert df.height == 1, f"expected one unsplit row, got {df['exposure_reference'].to_list()}"
    return df.row(0, named=True)


# ---------------------------------------------------------------------------
# RE-01 / RE-02 — collateral-level ADC flags
# ---------------------------------------------------------------------------


class TestCollateralAdcFlagReachesExposure:
    """RE-01: a collateral ``is_adc=True`` makes the exposure an ADC exposure."""

    @pytest.mark.parametrize(
        ("regime", "expected_rw", "expected_rwa"),
        [
            # PS1/26 Art. 124(3) + 124K(1): ADC exposure -> 150% on the whole loan.
            # Pre-fix: split onto Art. 124F, L1_sec 20% -> RWA 100,000.
            ("b31", 1.50, 750_000.0),
            # CRR: ADC lending is not owner-occupied (Art. 125(1)(a)) and the
            # engine keeps ADC whole (the re_split ADC exclusion), so the loan
            # takes the unrated corporate 100% (Art. 122). Pre-fix: 35% / 175,000.
            ("crr", 1.00, 500_000.0),
        ],
    )
    def test_collateral_adc_flag_prices_whole_loan_as_adc(
        self, regime: str, expected_rw: float, expected_rwa: float
    ) -> None:
        # Arrange
        collateral = [_property(1_000_000.0, "residential", 0.5, is_adc=True, is_presold=False)]

        # Act
        df, _codes = _run(regime, _DEVELOPER, _loan(500_000.0, "term_loan"), collateral)

        # Assert
        row = _single(df)
        assert row["is_adc"] is True
        assert row["risk_weight"] == pytest.approx(expected_rw)
        assert row["rwa_final"] == pytest.approx(expected_rwa)

    @pytest.mark.parametrize(
        ("regime", "expected_rwa"),
        [("b31", 100_000.0), ("crr", 175_000.0)],
    )
    def test_collateral_without_adc_flag_keeps_loan_split(
        self, regime: str, expected_rwa: float
    ) -> None:
        """Control: ``is_adc=False`` leaves the regulatory-RE split untouched."""
        # Arrange
        collateral = [_property(1_000_000.0, "residential", 0.5, is_adc=False)]

        # Act
        df, _codes = _run(regime, _DEVELOPER, _loan(500_000.0, "term_loan"), collateral)

        # Assert
        assert not df["is_adc"].any()
        assert df["rwa_final"].sum() == pytest.approx(expected_rwa)

    @pytest.mark.parametrize("regime", ["b31", "crr"])
    def test_collateral_adc_flag_on_natural_person_is_not_adc(self, regime: str) -> None:
        """The ADC definition reaches corporates / SPEs only — a natural person is not ADC."""
        # Arrange
        collateral = [_property(1_000_000.0, "residential", 0.5, is_adc=True)]

        # Act
        df, _codes = _run(regime, _INDIVIDUAL, _loan(500_000.0, "mortgage"), collateral)

        # Assert
        assert not df["is_adc"].any()


class TestResidentialAdcPresold:
    """RE-02: a collateral ``is_presold=True`` reaches the Art. 124K(2) weight."""

    @pytest.mark.parametrize(
        ("regime", "property_type", "expected_rw", "expected_rwa"),
        [
            # Art. 124K(2): residential ADC with pre-sales -> 100%.
            # Pre-fix: 150% / 750,000 (is_presold never reached the SA stage).
            ("b31", "residential", 1.00, 500_000.0),
            # Art. 124K(2) is residential only: commercial ADC stays 150%.
            ("b31", "commercial", 1.50, 750_000.0),
            # CRR has no ADC weight: corporate 100% either way.
            ("crr", "residential", 1.00, 500_000.0),
            ("crr", "commercial", 1.00, 500_000.0),
        ],
    )
    def test_presold_adc_weight(
        self, regime: str, property_type: str, expected_rw: float, expected_rwa: float
    ) -> None:
        # Arrange
        collateral = [_property(1_000_000.0, property_type, 0.5, is_adc=True, is_presold=True)]

        # Act
        df, _codes = _run(regime, _DEVELOPER, _loan(500_000.0, "term_loan"), collateral)

        # Assert
        row = _single(df)
        assert row["is_adc"] is True
        assert row["risk_weight"] == pytest.approx(expected_rw)
        assert row["rwa_final"] == pytest.approx(expected_rwa)


# ---------------------------------------------------------------------------
# RE-10 / CL-08 — LTV derivation and evidence of security
# ---------------------------------------------------------------------------


class TestLtvDerivedFromPropertyValue:
    """RE-10: a null ``property_ltv`` is derived from the property's market value."""

    @pytest.mark.parametrize(
        ("regime", "drawn", "expected_ltv", "expected_rw", "expected_rwa"),
        [
            # LTV = 95,000 / 100,000 = 0.95.
            # CRR Art. 125: 35% x 0.80/0.95 + 75% x 0.15/0.95 = 0.413158.
            # Pre-fix: ltv null filled 0.0 -> 35% / 33,250.
            ("crr", 95_000.0, 0.95, 0.3925 / 0.95, 39_250.0),
            # B31 Art. 124F: 20% x 0.55/0.95 + 75% x 0.40/0.95 = 0.431579.
            # Pre-fix: ltv null filled 1.0 -> 0.4475 / 42,512.50.
            ("b31", 95_000.0, 0.95, 0.41 / 0.95, 41_000.0),
            # LTV = 150,000 / 100,000 = 1.5.
            # CRR: 35% x 0.8/1.5 + 75% x 0.7/1.5 = 0.536667. Pre-fix 35% / 52,500.
            ("crr", 150_000.0, 1.5, 0.805 / 1.5, 80_500.0),
            # B31: 20% x 0.55/1.5 + 75% x 0.95/1.5 = 0.548333. Pre-fix 0.4475 / 67,125.
            ("b31", 150_000.0, 1.5, 0.8225 / 1.5, 82_250.0),
        ],
    )
    def test_null_property_ltv_is_derived(
        self,
        regime: str,
        drawn: float,
        expected_ltv: float,
        expected_rw: float,
        expected_rwa: float,
    ) -> None:
        # Arrange
        collateral = [_property(100_000.0, "residential", None)]

        # Act
        df, codes = _run(regime, _INDIVIDUAL, _loan(drawn, "mortgage"), collateral)

        # Assert
        row = _single(df)
        assert row["exposure_class"] == "retail_mortgage"
        assert row["ltv"] == pytest.approx(expected_ltv)
        assert row["risk_weight"] == pytest.approx(expected_rw)
        assert row["rwa_final"] == pytest.approx(expected_rwa)
        assert "RE006" in codes

    @pytest.mark.parametrize(
        ("regime", "expected_rw", "expected_rwa"),
        [
            # Derived LTV = 40,000 / 100,000 + prior charges 0.20 = 0.60
            # (Art. 124C(3): prior charges are in the LTV numerator).
            # CRR Art. 125: 0.60 <= 0.80 -> 35%.
            ("crr", 0.35, 14_000.0),
            # B31 Art. 124F(2): 55% reduced by 20% -> 35%; share = 0.35/0.60.
            # 20% x 0.583333 + 75% x 0.416667 = 0.429167.
            ("b31", 0.2575 / 0.60, 17_166.666667),
        ],
    )
    def test_derived_ltv_includes_prior_charges(
        self, regime: str, expected_rw: float, expected_rwa: float
    ) -> None:
        # Arrange
        collateral = [_property(100_000.0, "residential", None, prior_charge_ltv=0.20)]

        # Act
        df, _codes = _run(regime, _INDIVIDUAL, _loan(40_000.0, "mortgage"), collateral)

        # Assert
        row = _single(df)
        assert row["ltv"] == pytest.approx(0.60)
        assert row["risk_weight"] == pytest.approx(expected_rw)
        assert row["rwa_final"] == pytest.approx(expected_rwa)

    @pytest.mark.parametrize("regime", ["b31", "crr"])
    def test_supplied_property_ltv_is_not_overridden(self, regime: str) -> None:
        """A supplied ``property_ltv`` wins over the derivation and raises no RE006."""
        # Arrange: value implies 0.95 but the firm supplies 0.50.
        collateral = [_property(100_000.0, "residential", 0.50)]

        # Act
        df, codes = _run(regime, _INDIVIDUAL, _loan(95_000.0, "mortgage"), collateral)

        # Assert
        assert _single(df)["ltv"] == pytest.approx(0.50)
        assert "RE006" not in codes


class TestMortgageWithoutPropertyEvidence:
    """CL-08: no property collateral and no LTV -> no real-estate weight."""

    @pytest.mark.parametrize(
        ("regime", "pre_fix_rwa"),
        [
            # Pre-fix: retail_mortgage, ltv null filled 0.0 -> CRR 35% / 28,000.
            ("crr", 28_000.0),
            # Pre-fix: retail_mortgage, ltv null filled 1.0 -> B31 0.4475 / 35,800.
            ("b31", 35_800.0),
        ],
    )
    def test_mortgage_product_without_collateral_takes_counterparty_class(
        self, regime: str, pre_fix_rwa: float
    ) -> None:
        # Act
        df, codes = _run(
            regime,
            _INDIVIDUAL,
            _loan(80_000.0, "mortgage"),
            None,
            enforce_retail_granularity=False,
        )

        # Assert: regulatory retail (CRR Art. 123 / PS1/26 Art. 123) 75% -> 60,000.
        row = _single(df)
        assert row["exposure_class"] == "retail_other"
        assert row["risk_weight"] == pytest.approx(0.75)
        assert row["rwa_final"] == pytest.approx(60_000.0)
        assert row["rwa_final"] != pytest.approx(pre_fix_rwa)
        assert "RE005" in codes

    @pytest.mark.parametrize("regime", ["b31", "crr"])
    def test_mortgage_label_alone_prices_like_any_other_loan_to_the_obligor(
        self, regime: str
    ) -> None:
        """With granularity on, the B31 fallback class follows the obligor, whatever it is.

        The counterparty-class treatment is the class the same obligor's
        non-mortgage loan takes; the product label adds nothing.
        """
        # Act
        mortgage, codes = _run(regime, _INDIVIDUAL, _loan(80_000.0, "mortgage"), None)
        term_loan, _ = _run(regime, _INDIVIDUAL, _loan(80_000.0, "term_loan"), None)

        # Assert
        mortgage_row, control_row = _single(mortgage), _single(term_loan)
        assert mortgage_row["exposure_class"] == control_row["exposure_class"]
        assert mortgage_row["risk_weight"] == pytest.approx(control_row["risk_weight"])
        assert mortgage_row["rwa_final"] == pytest.approx(control_row["rwa_final"])
        assert "RE005" in codes

    @pytest.mark.parametrize(
        ("regime", "expected_rw"),
        [
            # CRR Art. 125: LTV 0.60 <= 0.80 -> 35%.
            ("crr", 0.35),
            # B31 Art. 124F: 20% x 0.55/0.60 + 75% x 0.05/0.60.
            ("b31", (0.2 * 0.55 + 0.75 * 0.05) / 0.60),
        ],
    )
    def test_loan_level_ltv_is_evidence(self, regime: str, expected_rw: float) -> None:
        """A populated LTV (here on the loan row) is evidence: RE weights still apply."""
        # Act
        df, codes = _run(regime, _INDIVIDUAL, _loan(80_000.0, "mortgage", ltv=0.60), None)

        # Assert
        row = _single(df)
        assert row["exposure_class"] == "retail_mortgage"
        assert row["risk_weight"] == pytest.approx(expected_rw)
        assert "RE005" not in codes

    @pytest.mark.parametrize("regime", ["b31", "crr"])
    def test_loan_level_ltv_survives_an_unrelated_collateral_file(self, regime: str) -> None:
        """A collateral file that does not link to the loan must not discard its LTV."""
        # Arrange: cash collateral for some other loan.
        unrelated = [
            {
                "collateral_reference": "CASH1",
                "collateral_type": "cash",
                "currency": "GBP",
                "market_value": 1_000.0,
                "beneficiary_type": "loan",
                "beneficiary_reference": "OTHER",
            }
        ]

        # Act
        df, codes = _run(regime, _INDIVIDUAL, _loan(80_000.0, "mortgage", ltv=0.60), unrelated)

        # Assert
        row = _single(df)
        assert row["ltv"] == pytest.approx(0.60)
        assert row["exposure_class"] == "retail_mortgage"
        assert "RE005" not in codes
