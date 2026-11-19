"""
Unit tests: the hierarchy stage's real-estate evidence (review RE-01, RE-02, RE-10).

Pipeline position:
    Loader -> HierarchyResolver (engine/hierarchy) -> Classifier

Key responsibilities pinned here:
- ``re_ltv.derive_missing_ltv``: a null LTV is derived as the PS1/26 Art. 124C
  amount of the loan over the linked property value — per level (direct /
  facility / counterparty), with prior charges in the numerator — and flagged
  ``ltv_derived``; a supplied LTV is never overridden.
- ``enrich.add_collateral_ltv``: a real-estate row without ``property_ltv``
  still delivers its property attributes, an LTV-bearing row wins the per-level
  keep-first whatever its input position, and the loan row's own ``ltv``
  survives a collateral file that does not link to it.
- ``enrich.enrich_with_property_coverage``: collateral ``is_adc`` /
  ``is_presold`` reach every exposure the pledge covers, any-True.

Rule text (verbatim, PS1/26 Art. 124C): "1. The loan-to-value (LTV) ... is the
amount of the loan divided by the value of the property. 2. The amount of the
loan shall include the outstanding loan amount and any undrawn committed amount
of the mortgage loan ... 3. The amount of the loan which is used for the
calculation of the LTV shall include all other loans secured with charges
ranking in priority ahead of or pari passu with the charge that the exposure is
secured by."

References:
- PS1/26 Art. 124C, 124K; CRR Art. 125(2)(d)
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.hierarchy import HierarchyResolver
from tests.fixtures.raw_bundle import make_raw_bundle

_CP: dict[str, Any] = {
    "counterparty_reference": "CP1",
    "counterparty_name": "CP1",
    "entity_type": "individual",
    "country_code": "GB",
    "default_status": False,
    "is_natural_person": True,
}


def _loan(ref: str, drawn: float, **extra: Any) -> dict[str, Any]:
    return {
        "loan_reference": ref,
        "product_type": "mortgage",
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


def _property(ref: str, level: str, beneficiary: str, value: float | None, **extra: Any) -> dict:
    return {
        "collateral_reference": ref,
        "collateral_type": "real_estate",
        "currency": "GBP",
        "market_value": value,
        "beneficiary_type": level,
        "beneficiary_reference": beneficiary,
        "property_type": "residential",
        "property_ltv": None,
        **extra,
    }


def _frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    keys: list[str] = []
    for row in rows:
        keys.extend(k for k in row if k not in keys)
    return pl.DataFrame({k: [row.get(k) for row in rows] for k in keys}, strict=False)


def _resolve(
    loans: list[dict[str, Any]],
    collateral: list[dict[str, Any]] | None,
    *,
    facilities: list[dict[str, Any]] | None = None,
    mappings: list[dict[str, Any]] | None = None,
) -> pl.DataFrame:
    """Resolve the hierarchy on a tiny bundle and return the exposure frame."""
    kwargs: dict[str, Any] = {}
    if collateral is not None:
        kwargs["collateral"] = _frame(collateral)
    if facilities is not None:
        kwargs["facilities"] = _frame(facilities)
    bundle = make_raw_bundle(
        counterparties=_frame([_CP]),
        loans=_frame(loans),
        facility_mappings=_frame(mappings)
        if mappings
        else pl.DataFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        **kwargs,
    )
    config = CalculationConfig.basel_3_1(reporting_date=date(2027, 3, 31))
    return HierarchyResolver().resolve(bundle, config).exposures.collect()


def _row(df: pl.DataFrame, ref: str) -> dict[str, Any]:
    rows = df.filter(pl.col("exposure_reference") == ref)
    assert rows.height == 1, f"{ref} not emitted once: {df['exposure_reference'].to_list()}"
    return rows.row(0, named=True)


class TestDeriveMissingLtv:
    """``re_ltv.derive_missing_ltv`` — PS1/26 Art. 124C(1)-(3)."""

    def test_direct_property_without_ltv_is_derived(self) -> None:
        # Act: 95,000 drawn on a 100,000 property, no property_ltv.
        df = _resolve([_loan("L1", 95_000.0)], [_property("P1", "loan", "L1", 100_000.0)])

        # Assert
        row = _row(df, "L1")
        assert row["ltv"] == pytest.approx(0.95)
        assert row["ltv_derived"] is True

    def test_accrued_interest_is_in_the_amount_of_the_loan(self) -> None:
        """Art. 124C(2): the outstanding amount — drawn plus accrued interest."""
        df = _resolve(
            [_loan("L1", 90_000.0, interest=5_000.0)],
            [_property("P1", "loan", "L1", 100_000.0)],
        )
        assert _row(df, "L1")["ltv"] == pytest.approx(0.95)

    def test_prior_charges_are_in_the_numerator(self) -> None:
        """Art. 124C(3): 40,000 own + 20,000 ahead over 100,000 -> 0.60."""
        df = _resolve(
            [_loan("L1", 40_000.0)],
            [_property("P1", "loan", "L1", 100_000.0, prior_charge_ltv=0.20)],
        )
        assert _row(df, "L1")["ltv"] == pytest.approx(0.60)

    def test_supplied_ltv_is_kept_and_not_flagged(self) -> None:
        df = _resolve(
            [_loan("L1", 95_000.0)],
            [_property("P1", "loan", "L1", 100_000.0, property_ltv=0.40)],
        )
        row = _row(df, "L1")
        assert row["ltv"] == pytest.approx(0.40)
        assert row["ltv_derived"] is False

    def test_unvalued_property_gives_no_ltv(self) -> None:
        """No market value, no LTV: nothing to divide by, and nothing fabricated."""
        df = _resolve([_loan("L1", 95_000.0)], [_property("P1", "loan", "L1", None)])
        row = _row(df, "L1")
        assert row["ltv"] is None
        assert row["ltv_derived"] is False

    def test_no_collateral_file_leaves_ltv_null(self) -> None:
        df = _resolve([_loan("L1", 95_000.0)], None)
        row = _row(df, "L1")
        assert row["ltv"] is None
        assert row["ltv_derived"] is False

    def test_counterparty_pledge_ltv_is_the_obligor_total_over_the_value(self) -> None:
        """A counterparty-level pledge secures every exposure: (60k + 40k) / 200k = 0.5."""
        # Act
        df = _resolve(
            [_loan("L1", 60_000.0), _loan("L2", 40_000.0)],
            [_property("P1", "counterparty", "CP1", 200_000.0)],
        )

        # Assert: both exposures carry the obligor-level LTV, not their own share.
        assert _row(df, "L1")["ltv"] == pytest.approx(0.5)
        assert _row(df, "L2")["ltv"] == pytest.approx(0.5)

    def test_facility_pledge_counts_drawn_and_undrawn_committed(self) -> None:
        """Art. 124C(2): a 100k committed facility, 60k drawn, on a 200k property -> 0.5.

        The undrawn headroom row (drawn 0) gets the same facility LTV: a pro-rata
        by drawn amount would have handed it no property value and no LTV.
        """
        # Arrange
        facility = {
            "facility_reference": "F1",
            "product_type": "mortgage",
            "book_code": "B",
            "counterparty_reference": "CP1",
            "value_date": date(2024, 1, 1),
            "maturity_date": date(2045, 1, 1),
            "currency": "GBP",
            "limit": 100_000.0,
            "committed": True,
            "seniority": "senior",
            "risk_type": "MR",
        }
        mapping = {"parent_facility_reference": "F1", "child_reference": "L1", "child_type": "loan"}

        # Act
        df = _resolve(
            [_loan("L1", 60_000.0)],
            [_property("P1", "facility", "F1", 200_000.0)],
            facilities=[facility],
            mappings=[mapping],
        )

        # Assert
        undrawn = df.filter(pl.col("exposure_reference") != "L1")
        assert undrawn.height == 1, "the facility headroom row is the adequacy condition"
        assert _row(df, "L1")["ltv"] == pytest.approx(0.5)
        assert undrawn["ltv"].item() == pytest.approx(0.5)

    def test_direct_pledge_wins_over_counterparty_pledge(self) -> None:
        df = _resolve(
            [_loan("L1", 50_000.0), _loan("L2", 50_000.0)],
            [
                _property("P1", "loan", "L1", 100_000.0),
                _property("P2", "counterparty", "CP1", 1_000_000.0),
            ],
        )
        assert _row(df, "L1")["ltv"] == pytest.approx(0.5)
        assert _row(df, "L2")["ltv"] == pytest.approx(0.1)


class TestCollateralLtvAttributes:
    """``enrich.add_collateral_ltv`` keeps the property data a null-LTV row carries."""

    def test_null_ltv_row_still_delivers_its_attributes(self) -> None:
        """Pre-fix, the row was dropped whole, so a non-qualifying commercial
        property read as qualifying and residential (null -> qualifying)."""
        df = _resolve(
            [_loan("L1", 50_000.0)],
            [
                _property(
                    "P1",
                    "loan",
                    "L1",
                    100_000.0,
                    property_type="commercial",
                    is_qualifying_re=False,
                    is_income_producing=True,
                )
            ],
        )
        row = _row(df, "L1")
        assert row["property_type"] == "commercial"
        assert row["is_qualifying_re"] is False
        assert row["has_income_cover"] is True

    @pytest.mark.parametrize("ltv_row_first", [True, False])
    def test_ltv_bearing_row_wins_the_level_whatever_its_position(
        self, ltv_row_first: bool
    ) -> None:
        # Arrange: two direct pledges, only one with an LTV.
        with_ltv = _property("P_LTV", "loan", "L1", 100_000.0, property_ltv=0.30)
        without = _property("P_NULL", "loan", "L1", 100_000.0, property_type="commercial")
        rows = [with_ltv, without] if ltv_row_first else [without, with_ltv]

        # Act
        df = _resolve([_loan("L1", 50_000.0)], rows)

        # Assert: the supplied 0.30 and its residential type, in both orders.
        row = _row(df, "L1")
        assert row["ltv"] == pytest.approx(0.30)
        assert row["property_type"] == "residential"
        assert row["ltv_derived"] is False

    def test_loan_level_ltv_survives_an_unrelated_collateral_file(self) -> None:
        df = _resolve(
            [_loan("L1", 50_000.0, ltv=0.6)],
            [
                {
                    "collateral_reference": "CASH",
                    "collateral_type": "cash",
                    "currency": "GBP",
                    "market_value": 1_000.0,
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "OTHER",
                }
            ],
        )
        assert _row(df, "L1")["ltv"] == pytest.approx(0.6)

    def test_collateral_ltv_wins_over_loan_level_ltv(self) -> None:
        df = _resolve(
            [_loan("L1", 50_000.0, ltv=0.9)],
            [_property("P1", "loan", "L1", 100_000.0, property_ltv=0.4)],
        )
        assert _row(df, "L1")["ltv"] == pytest.approx(0.4)


class TestCollateralAdcFlags:
    """``re_collateral_is_adc`` / ``re_collateral_is_presold`` — PS1/26 Art. 124K."""

    def test_flags_reach_the_pledged_exposure(self) -> None:
        df = _resolve(
            [_loan("L1", 50_000.0)],
            [_property("P1", "loan", "L1", 100_000.0, is_adc=True, is_presold=True)],
        )
        row = _row(df, "L1")
        assert row["re_collateral_is_adc"] is True
        assert row["re_collateral_is_presold"] is True

    def test_any_true_per_beneficiary_whatever_the_order(self) -> None:
        """Two pledges, one ADC: the exposure is ADC (any-True, not keep-first)."""
        for order in ([True, False], [False, True]):
            rows = [
                _property(f"P{i}", "loan", "L1", 100_000.0, is_adc=flag)
                for i, flag in enumerate(order)
            ]
            df = _resolve([_loan("L1", 50_000.0)], rows)
            assert _row(df, "L1")["re_collateral_is_adc"] is True, f"order {order}"

    def test_counterparty_pledge_flags_every_exposure(self) -> None:
        df = _resolve(
            [_loan("L1", 50_000.0), _loan("L2", 50_000.0)],
            [_property("P1", "counterparty", "CP1", 100_000.0, is_adc=True)],
        )
        assert _row(df, "L1")["re_collateral_is_adc"] is True
        assert _row(df, "L2")["re_collateral_is_adc"] is True

    def test_flags_are_false_without_adc_collateral(self) -> None:
        df = _resolve([_loan("L1", 50_000.0)], None)
        row = _row(df, "L1")
        assert row["re_collateral_is_adc"] is False
        assert row["re_collateral_is_presold"] is False
