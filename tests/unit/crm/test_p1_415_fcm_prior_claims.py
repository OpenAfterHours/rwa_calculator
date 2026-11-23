"""
P1.415 — Foundation Collateral Method property value net of prior claims.

``HaircutCalculator.apply_haircuts`` is where a real-estate row's Art. 230 value
``value_after_haircut`` is formed. These tests pin the Art. 229(1) prior-claim deduction
at that site, in both regimes:

- CRR Art. 229(1): the market value is "reduced as appropriate ... to take account of
  any prior claims on the immovable property" -> C = MV - P.
- PS1/26 Art. 229(1)(b): the value is reduced by P / (1 - HC - Hfx), so
  ES = (MV - P / (1 - HC - Hfx)) x (1 - HC - Hfx) = MV x (1 - HC - Hfx) - P, and "Where
  the calculations under this paragraph 1 result in a negative value, the institution
  shall assign zero value to the collateral."

One expression serves both: the CRR pack's immovable-property HC is 0% and CRR takes no
Hfx on non-financial collateral (pack Feature ``fcm_hfx_applies_to_non_financial``), so
``max(0, MV x (1 - HC - Hfx) - P)`` is exactly CRR's MV - P. P = ``prior_charge_ltv`` x
``market_value`` (the input is a share of the property value). A null prior charge, or a
frame with no such column (the CCR caller's), deducts nothing.

Which rows read it is fixed against ``collateral_category_expr``, the expression that
files a row under the real-estate CRM category (and so into ``collateral_re_value``,
``crm_alloc_real_estate`` and the C* test): every recognised ``collateral_type`` spelling,
in three letter cases, is categorised by that expression at collection time, and the
deduction must fall on exactly the real-estate ones. A predicate narrower than the
category — e.g. the literal ``== "real_estate"`` the SA LTV derivation reads
(``engine/hierarchy/re_ltv.py``) — would leave a ``"Residential_Property"`` or ``"CRE"``
pledge in the real-estate pool at its full value.

References:
    - CRR Art. 229(1), Art. 230(2) Table 5 (real-estate HC 0%).
    - PS1/26 Art. 229(1)(b), Art. 230(1)-(2) (immovable-property HC 40%, Hfx 8% base).
    - IMPLEMENTATION_PLAN.md: P1.415.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.schemas import RECOGNISED_COLLATERAL_TYPES
from rwa_calc.engine.crm.expressions import collateral_category_expr
from rwa_calc.engine.crm.haircuts import HaircutCalculator

_MV = 100_000.0

#: Haircut value of the property at prior 0.3 with no currency mismatch:
#: CRR MV - P; Basel 3.1 MV x (1 - 40%) - P.
_NET_OF_PRIOR_0_3: dict[str, float] = {"crr": 70_000.0, "b31": 30_000.0}


def _letter_cases(type_string: str) -> list[str]:
    """The spelling as given, upper case, and each underscore-separated word capitalised."""
    capitalised = "_".join(word.capitalize() for word in type_string.split("_"))
    return [type_string, type_string.upper(), capitalised]


def _category_by_type_string() -> dict[str, str]:
    """``collateral_category_expr`` over every recognised spelling in three letter cases."""
    spellings = sorted({c for t in RECOGNISED_COLLATERAL_TYPES for c in _letter_cases(t)})
    frame = pl.DataFrame(
        {"collateral_type": spellings, "issuer_type": [None] * len(spellings)},
        schema={"collateral_type": pl.String, "issuer_type": pl.String},
    )
    categories = frame.select(collateral_category_expr()).to_series().to_list()
    return dict(zip(spellings, categories, strict=True))


_CATEGORY = _category_by_type_string()
_PROPERTY_TYPE_STRINGS = sorted(t for t, c in _CATEGORY.items() if c == "real_estate")
_OTHER_TYPE_STRINGS = sorted(t for t, c in _CATEGORY.items() if c != "real_estate")


def _config(regime: str) -> CalculationConfig:
    if regime == "crr":
        return CalculationConfig.crr(reporting_date=date(2026, 6, 30))
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _collateral(
    *,
    collateral_type: str = "real_estate",
    prior_charge_ltv: float | None = None,
    original_currency: str = "GBP",
    with_prior_column: bool = True,
    issuer_cqs: int | None = None,
    residual_maturity_years: float | None = None,
) -> pl.LazyFrame:
    """One collateral row in the shape ``apply_haircuts`` receives from the CRM stage."""
    data: dict[str, list[object]] = {
        "collateral_reference": ["C1"],
        "collateral_type": [collateral_type],
        "currency": ["GBP"],
        "original_currency": [original_currency],
        "market_value": [_MV],
        "issuer_cqs": [issuer_cqs],
        "residual_maturity_years": [residual_maturity_years],
        "exposure_currency": ["GBP"],
        "is_eligible_financial_collateral": [collateral_type == "cash"],
    }
    schema: dict[str, pl.DataType] = {
        "issuer_cqs": pl.Int8(),
        "residual_maturity_years": pl.Float64(),
    }
    if with_prior_column:
        data["prior_charge_ltv"] = [prior_charge_ltv]
        schema["prior_charge_ltv"] = pl.Float64()
    return pl.LazyFrame(data, schema_overrides=schema)


def _value(regime: str, collateral: pl.LazyFrame) -> float:
    out = HaircutCalculator().apply_haircuts(collateral, _config(regime)).collect()
    return out["value_after_haircut"][0]


class TestPriorClaimDeduction:
    """Real-estate value after haircut is MV x (1 - HC - Hfx) - P, floored at zero."""

    @pytest.mark.parametrize(
        ("regime", "prior", "expected"),
        [
            # CRR: HC 0%, no Hfx -> MV - P.
            ("crr", 0.3, 70_000.0),
            ("crr", 0.6, 40_000.0),
            # Basel 3.1: HC 40% -> 0.60 x MV - P. 0.3 tells MV(1-HC) - P (30,000)
            # from the wrong (MV - P)(1-HC) (42,000).
            ("b31", 0.3, 30_000.0),
            ("b31", 0.6, 0.0),
        ],
    )
    def test_prior_claim_reduces_property_value(
        self, regime: str, prior: float, expected: float
    ) -> None:
        """A prior charge comes off the haircut property value (Art. 229(1))."""
        # Arrange
        collateral = _collateral(prior_charge_ltv=prior)

        # Act
        value = _value(regime, collateral)

        # Assert
        assert value == pytest.approx(expected, abs=1e-6)

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_claims_exceeding_the_property_floor_at_zero(self, regime: str) -> None:
        """A negative result is assigned zero value (PS1/26 Art. 229(1) final sentence)."""
        # Arrange
        collateral = _collateral(prior_charge_ltv=1.2)

        # Act
        value = _value(regime, collateral)

        # Assert
        assert value == 0.0

    def test_b31_currency_mismatch_deducts_p_after_hc_and_hfx(self) -> None:
        """Basel 3.1 with Hfx: ES = MV x (1 - 0.40 - Hfx) - P, Hfx = 8% x sqrt(20/10)."""
        # Arrange
        collateral = _collateral(prior_charge_ltv=0.3, original_currency="EUR")
        hfx = 0.08 * (20 / 10) ** 0.5

        # Act
        value = _value("b31", collateral)

        # Assert
        assert value == pytest.approx(_MV * (1.0 - 0.40 - hfx) - 30_000.0, abs=1e-6)

    def test_crr_currency_mismatch_still_mv_minus_p(self) -> None:
        """CRR takes no Hfx on property, so a mismatch leaves C = MV - P."""
        # Arrange
        collateral = _collateral(prior_charge_ltv=0.3, original_currency="EUR")

        # Act
        value = _value("crr", collateral)

        # Assert
        assert value == pytest.approx(70_000.0, abs=1e-6)


class TestNoPriorClaim:
    """No prior claim reported, or not a property row: the value is unchanged."""

    @pytest.mark.parametrize(("regime", "expected"), [("crr", _MV), ("b31", 60_000.0)])
    @pytest.mark.parametrize("prior", [0.0, None])
    def test_first_charge_property_is_unchanged(
        self, regime: str, expected: float, prior: float | None
    ) -> None:
        """0.0 and an unreported (null) prior charge deduct nothing."""
        # Arrange
        collateral = _collateral(prior_charge_ltv=prior)

        # Act
        value = _value(regime, collateral)

        # Assert
        assert value == pytest.approx(expected, abs=1e-6)

    @pytest.mark.parametrize(("regime", "expected"), [("crr", _MV), ("b31", 60_000.0)])
    def test_frame_without_the_column_is_unchanged(self, regime: str, expected: float) -> None:
        """A caller's frame with no ``prior_charge_ltv`` (the CCR path) still values."""
        # Arrange
        collateral = _collateral(with_prior_column=False)

        # Act
        value = _value(regime, collateral)

        # Assert
        assert value == pytest.approx(expected, abs=1e-6)

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_prior_charge_on_non_property_row_is_ignored(self, regime: str) -> None:
        """Art. 229(1) is an immovable-property rule: cash keeps its full value."""
        # Arrange
        collateral = _collateral(collateral_type="cash", prior_charge_ltv=0.5)

        # Act
        value = _value(regime, collateral)

        # Assert
        assert value == pytest.approx(_MV, abs=1e-6)

    @pytest.mark.parametrize(("regime", "expected"), [("crr", _MV), ("b31", 60_000.0)])
    def test_negative_prior_charge_adds_no_value(self, regime: str, expected: float) -> None:
        """An out-of-domain negative prior charge never raises the value above no-claim."""
        # Arrange
        collateral = _collateral(prior_charge_ltv=-0.2)

        # Act
        value = _value(regime, collateral)

        # Assert
        assert value == pytest.approx(expected, abs=1e-6)


class TestPropertyRowsAreTheRealEstateCategory:
    """The deduction falls on exactly the rows ``collateral_category_expr`` files as real estate.

    That category is what carries the row into ``collateral_re_value``,
    ``crm_alloc_real_estate`` and the CRR C* test, so a narrower predicate leaves a
    synonym-spelled property at full value there, and a wider one strips value from
    collateral Art. 229 does not govern.
    """

    def test_category_spans_synonyms_and_letter_cases(self) -> None:
        """Adequacy: the parametrisation is more than the literal ``"real_estate"``."""
        assert {"real_estate", "residential_property", "Residential_Property", "CRE"} <= set(
            _PROPERTY_TYPE_STRINGS
        )
        assert {"cash", "equipment", "Receivables"} <= set(_OTHER_TYPE_STRINGS)

    @pytest.mark.parametrize("collateral_type", _PROPERTY_TYPE_STRINGS)
    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_every_real_estate_spelling_is_net_of_prior_claims(
        self, regime: str, collateral_type: str
    ) -> None:
        """value_after_haircut = MV x (1 - HC - Hfx) - P for every real-estate spelling."""
        # Arrange
        collateral = _collateral(collateral_type=collateral_type, prior_charge_ltv=0.3)

        # Act
        value = _value(regime, collateral)

        # Assert
        assert value == pytest.approx(_NET_OF_PRIOR_0_3[regime], abs=1e-6)

    @pytest.mark.parametrize("collateral_type", _OTHER_TYPE_STRINGS)
    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_no_other_category_reads_prior_claims(self, regime: str, collateral_type: str) -> None:
        """A prior charge on any non-real-estate row leaves its haircut value unchanged.

        A CQS 1 issuer and a 2-year residual give debt securities a haircut value too, so
        the comparison is not between two nulls.
        """
        # Arrange
        with_prior, without_prior = (
            _collateral(
                collateral_type=collateral_type,
                prior_charge_ltv=prior,
                issuer_cqs=1,
                residual_maturity_years=2.0,
            )
            for prior in (0.3, None)
        )

        # Act
        value_with, value_without = _value(regime, with_prior), _value(regime, without_prior)

        # Assert
        assert value_with == value_without
