"""
Unit tests: the real-estate splitter's qualification and LTV carriers
(review CL-07 / RE-09, RE-17, CL-10).

Pipeline position under test:
    CRMProcessor -> RealEstateSplitter (engine/re_split/splitter.py)
        -> SA calculator

Key responsibilities pinned here:
- CL-07 / RE-09 (CRR): a split candidate whose property is explicitly NOT
  qualifying (``is_qualifying_re=False``) is secured up to the full property
  value — CRR Art. 124(1)'s limit for the part "treated as fully secured by
  immovable property" — not the Art. 125(2)(d) 80%, because the Art. 125 weight
  is not available to it; the SA stage then weights that part at Art. 124(1)'s
  100%. A null or True attestation keeps the 80% cap.
- RE-17 (CRR): the CRE secured row no longer carries ``has_income_cover=True``.
  That flag is "materially dependent on the property's cash flows", which under
  Art. 126(2)(b) DENIES the 50% weight; the splitter used to set it to grant it.
- CL-10 (Basel 3.1): the Art. 124H(3) whole-loan row keeps the Art. 124C LTV
  the hierarchy supplied (it includes prior and pari-passu charges, Art.
  124C(3)); it falls back to exposure / property value only when none exists.

Rule text (verbatim):
- CRR Art. 124(1): "The part of an exposure that is treated as fully secured by
  immovable property shall not be greater than the pledged amount of the market
  value ... of the immovable property in question."
- CRR Art. 125(2)(d): "the part of the loan to which the 35 % risk weight is
  assigned does not exceed 80 % of the market value of the property".
- PS1/26 Art. 124C(3): "The amount of the loan which is used for the
  calculation of the LTV shall include all other loans secured with charges
  ranking in priority ahead of or pari passu with the charge that the exposure
  is secured by."

References:
- CRR Art. 124(1), 125(2)(d), 126(2)(b); PS1/26 Art. 124C, 124H(3)
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.re_split import RealEstateSplitter
from tests.fixtures.resolved_bundle import make_crm_bundle

_REPORTING_DATE = date(2026, 12, 31)


def _bundle(**overrides: Any) -> CRMAdjustedBundle:
    """One split candidate; ``overrides`` replace the defaults below."""
    row: dict[str, Any] = {
        "exposure_reference": "EXP1",
        "counterparty_reference": "CP1",
        "exposure_class": "corporate",
        "approach": "standardised",
        "ead_final": 900.0,
        "provision_allocated": 0.0,
        "re_split_target_class": "residential_mortgage",
        "re_split_mode": "split",
        "re_split_property_type": "residential",
        "re_split_property_value": 1_000.0,
        "re_split_residential_value": 1_000.0,
        "re_split_commercial_value": 0.0,
        "re_split_residential_eligible": True,
        "re_split_commercial_eligible": False,
        "re_split_cre_rental_coverage_met": False,
        "ltv": 0.9,
        "property_type": "residential",
        "has_income_cover": False,
        "prior_charge_ltv": 0.0,
        "property_collateral_value": 1_000.0,
        "residential_collateral_value": 1_000.0,
        "cp_is_natural_person": False,
        "is_sme": False,
        "is_qualifying_re": None,
    }
    row.update(overrides)
    frame = pl.DataFrame([row], schema_overrides={"is_qualifying_re": pl.Boolean})
    return make_crm_bundle(exposures=frame.lazy())


def _config(regime: str) -> CalculationConfig:
    if regime == "b31":
        return CalculationConfig.basel_3_1(reporting_date=date(2027, 3, 31))
    return CalculationConfig.crr(reporting_date=_REPORTING_DATE)


def _split(bundle: CRMAdjustedBundle, regime: str) -> pl.DataFrame:
    return RealEstateSplitter().split(bundle, _config(regime)).exposures.collect()


def _role(df: pl.DataFrame, role: str) -> dict[str, Any]:
    rows = df.filter(pl.col("re_split_role") == role)
    assert rows.height == 1, f"expected one {role} row, got {rows.height}"
    return rows.row(0, named=True)


class TestCrrNonQualifyingSecuredPart:
    """CL-07 / RE-09: an explicitly non-qualifying CRR split is secured to 100% of value."""

    @pytest.mark.parametrize(
        ("is_qualifying_re", "secured", "residual"),
        [
            # Art. 124(1): secured up to the 1,000 property value -> all 900.
            # Pre-fix: the Art. 125(2)(d) 80% cap, 800 / 100.
            (False, 900.0, 0.0),
            # Qualifying or unreported: the Art. 125(2)(d) 80% cap.
            (True, 800.0, 100.0),
            (None, 800.0, 100.0),
        ],
    )
    def test_secured_cap_follows_the_qualification(
        self, is_qualifying_re: bool | None, secured: float, residual: float
    ) -> None:
        # Act
        df = _split(_bundle(is_qualifying_re=is_qualifying_re), "crr")

        # Assert
        assert _role(df, "secured")["ead_final"] == pytest.approx(secured)
        assert _role(df, "residual")["ead_final"] == pytest.approx(residual)
        assert _role(df, "secured")["is_qualifying_re"] is is_qualifying_re

    def test_loan_above_the_property_value_leaves_the_excess_unsecured(self) -> None:
        """1,200 on a 1,000 property: 1,000 secured, 200 at the counterparty weight."""
        # Act
        df = _split(_bundle(ead_final=1_200.0, ltv=1.2, is_qualifying_re=False), "crr")

        # Assert
        assert _role(df, "secured")["ead_final"] == pytest.approx(1_000.0)
        assert _role(df, "residual")["ead_final"] == pytest.approx(200.0)

    def test_basel_3_1_cap_unchanged(self) -> None:
        """Control: Basel 3.1 keeps the Art. 124F 55% cap (the secured row goes to 124J)."""
        # Act
        df = _split(_bundle(is_qualifying_re=False), "b31")

        # Assert
        assert _role(df, "secured")["ead_final"] == pytest.approx(550.0)


class TestCrrCommercialSecuredRowIsNotMateriallyDependent:
    """RE-17: the CRR CRE secured row carries has_income_cover=False."""

    def test_cre_secured_row_is_not_flagged_materially_dependent(self) -> None:
        # Arrange
        bundle = _bundle(
            ead_final=400.0,
            ltv=0.4,
            property_type="commercial",
            re_split_target_class="commercial_mortgage",
            re_split_property_type="commercial",
            re_split_residential_value=0.0,
            re_split_commercial_value=1_000.0,
            re_split_residential_eligible=False,
            re_split_commercial_eligible=True,
            re_split_cre_rental_coverage_met=True,
        )

        # Act
        df = _split(bundle, "crr")

        # Assert — Art. 126(2)(b) needs the risk NOT to depend on the property;
        # pre-fix the splitter set True so the inverted gate returned 50%.
        assert _role(df, "secured")["has_income_cover"] is False


class TestB31WholeLoanKeepsTheArt124cLtv:
    """CL-10: the Art. 124H(3) whole-loan row keeps the input LTV."""

    def _whole(self, ltv: float | None) -> dict[str, Any]:
        bundle = _bundle(
            ead_final=70.0,
            ltv=ltv,
            prior_charge_ltv=0.2,
            property_type="commercial",
            re_split_target_class="commercial_mortgage",
            re_split_mode="whole",
            re_split_property_type="commercial",
            re_split_property_value=100.0,
            re_split_residential_value=0.0,
            re_split_commercial_value=100.0,
            re_split_residential_eligible=False,
            re_split_commercial_eligible=True,
            property_collateral_value=100.0,
            residential_collateral_value=0.0,
        )
        df = _split(bundle, "b31")
        assert df.height == 1, "whole mode emits one row per parent"
        return df.row(0, named=True)

    def test_whole_row_keeps_the_supplied_ltv(self) -> None:
        """Input LTV 0.9 (own 70 + prior 20 on 100). Pre-fix: overwritten with 0.7."""
        # Act
        row = self._whole(0.9)

        # Assert
        assert row["re_split_role"] == "whole"
        assert row["exposure_class"] == "commercial_mortgage"
        assert row["ltv"] == pytest.approx(0.9)

    def test_whole_row_without_an_ltv_falls_back_to_exposure_over_value(self) -> None:
        # Act
        row = self._whole(None)

        # Assert
        assert row["ltv"] == pytest.approx(0.7)
