"""
P1.324 - the hierarchy flags residential security on EVERY route the CRM follows.

Pipeline position:
    Loader -> HierarchyResolver (engine/hierarchy) -> Classifier -> ... -> IRB

``re_collateral_may_be_residential`` is the residential-presence carrier the
Basel 3.1 IRB floors read to tell a retail exposure secured by residential
immovable property (PS1/26 Art. 147(5B), the (d)(ii) subclass) from one secured
only on commercial property (Art. 147(5C), other retail). Wherever it misses a
house the CRM recognises, a house-secured exposure loses three floors, so it has
to see the house on every shape the other carriers cannot:

- ``residential_collateral_value`` (and its uncapped twin) is allocated pro rata
  to DRAWN amounts at the immediate parent facility and the counterparty, so a
  facility's undrawn headroom row carries 0 however much a house secures, and a
  pledge at a grandparent facility reaches nothing;
- ``property_type`` is keep-first by input row order, so a house-plus-shop
  security reads ``commercial`` whenever the shop row comes first;
- neither reads the M:N ``collateral_links`` table nor a real-estate
  ``collateral_type`` synonym (``residential_property``), both of which the CRM
  credits.

The flag is any-True per beneficiary, OR-ed across the direct / every-ancestor
facility / counterparty levels and the link beneficiaries, never weighted, so it
is the same on every row a house covers whatever order the rows arrive in. Real
estate of unreported kind counts as possibly residential.

References:
- PS1/26 Art. 147(5B)/(5C), 154(4A)(b), 163(1)(b), 164(4)(a)
- CRR Art. 230-231 (the CRM's facility cascade and link allocation)
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

_FACILITY: dict[str, Any] = {
    "facility_reference": "F1",
    "product_type": "mortgage",
    "book_code": "B",
    "counterparty_reference": "CP1",
    "value_date": date(2024, 1, 1),
    "maturity_date": date(2045, 1, 1),
    "currency": "GBP",
    "limit": 500_000.0,
    "committed": True,
    "seniority": "senior",
    "risk_type": "MR",
}

_MAPPING: dict[str, Any] = {
    "parent_facility_reference": "F1",
    "child_reference": "L1",
    "child_type": "loan",
}


def _loan(ref: str, drawn: float) -> dict[str, Any]:
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
    }


def _property(
    ref: str,
    level: str,
    beneficiary: str,
    value: float,
    kind: str | None,
    collateral_type: str = "real_estate",
) -> dict[str, Any]:
    return {
        "collateral_reference": ref,
        "collateral_type": collateral_type,
        "currency": "GBP",
        "market_value": value,
        "beneficiary_type": level,
        "beneficiary_reference": beneficiary,
        "property_type": kind,
        "property_ltv": None,
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
    with_facility: bool = False,
    facilities: list[dict[str, Any]] | None = None,
    mappings: list[dict[str, Any]] | None = None,
    links: list[dict[str, Any]] | None = None,
) -> pl.DataFrame:
    """Resolve the hierarchy on a tiny bundle and return the exposure frame."""
    kwargs: dict[str, Any] = {}
    if collateral is not None:
        kwargs["collateral"] = _frame(collateral)
    if links is not None:
        kwargs["collateral_links"] = _frame(links)
    if with_facility:
        facilities, mappings = [_FACILITY], [_MAPPING]
    if facilities is not None:
        kwargs["facilities"] = _frame(facilities)
    if mappings is not None:
        mapping_frame = _frame(mappings)
    else:
        mapping_frame = pl.DataFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        )
    bundle = make_raw_bundle(
        counterparties=_frame([_CP]),
        loans=_frame(loans),
        facility_mappings=mapping_frame,
        **kwargs,
    )
    config = CalculationConfig.basel_3_1(reporting_date=date(2027, 3, 31))
    return HierarchyResolver().resolve(bundle, config).exposures.collect()


def _undrawn_row(df: pl.DataFrame) -> dict[str, Any]:
    rows = df.filter(pl.col("exposure_reference") != "L1")
    assert rows.height == 1, "the facility headroom row is the adequacy condition"
    return rows.row(0, named=True)


def _row(df: pl.DataFrame, ref: str) -> dict[str, Any]:
    rows = df.filter(pl.col("exposure_reference") == ref)
    assert rows.height == 1, f"{ref} not emitted once: {df['exposure_reference'].to_list()}"
    return rows.row(0, named=True)


_HOUSE = _property("HOUSE", "facility", "F1", 500_000.0, "residential")
_SHOP = _property("SHOP", "facility", "F1", 200_000.0, "commercial")


class TestReCollateralMayBeResidential:
    """Any-True, OR-ed across levels and links, order-invariant, never weighted."""

    @pytest.mark.parametrize(
        "collateral", [[_SHOP, _HOUSE], [_HOUSE, _SHOP]], ids=["shop_first", "house_first"]
    )
    def test_facility_house_reaches_the_undrawn_row_whatever_the_order(
        self, collateral: list[dict[str, Any]]
    ) -> None:
        """A house-plus-shop facility: both its rows are residential-secured."""
        # Act
        df = _resolve([_loan("L1", 300_000.0)], collateral, with_facility=True)
        drawn, undrawn = _row(df, "L1"), _undrawn_row(df)

        # Assert - the undrawn row is blind on the value carrier (the trap)
        assert undrawn["residential_collateral_value_uncapped"] == pytest.approx(0.0)
        # Assert - the flag is not
        assert drawn["re_collateral_may_be_residential"] is True
        assert undrawn["re_collateral_may_be_residential"] is True

    def test_keep_first_property_type_reads_commercial_on_a_mixed_security(self) -> None:
        """Adequacy: with the shop first, ``property_type`` alone would call it commercial."""
        # Act
        df = _resolve([_loan("L1", 300_000.0)], [_SHOP, _HOUSE], with_facility=True)

        # Assert
        assert _undrawn_row(df)["property_type"] == "commercial"
        assert _undrawn_row(df)["re_collateral_may_be_residential"] is True

    def test_commercial_only_facility_is_not_residential(self) -> None:
        """A shop-only facility: no row of it carries residential security."""
        # Act
        df = _resolve([_loan("L1", 300_000.0)], [_SHOP], with_facility=True)

        # Assert
        assert _row(df, "L1")["re_collateral_may_be_residential"] is False
        assert _undrawn_row(df)["re_collateral_may_be_residential"] is False

    def test_direct_house_on_a_zero_drawn_loan_is_residential(self) -> None:
        """House + shop pledged to a drawn=0 loan, shop first: capped value is 0."""
        # Arrange
        collateral = [
            _property("SHOP", "loan", "L1", 200_000.0, "commercial"),
            _property("HOUSE", "loan", "L1", 500_000.0, "residential"),
        ]

        # Act
        row = _row(_resolve([_loan("L1", 0.0)], collateral), "L1")

        # Assert
        assert row["residential_collateral_value"] == pytest.approx(0.0)
        assert row["re_collateral_may_be_residential"] is True

    def test_counterparty_house_reaches_every_exposure(self) -> None:
        """A counterparty-level house covers each of the obligor's exposures."""
        # Act
        df = _resolve(
            [_loan("L1", 50_000.0), _loan("L2", 0.0)],
            [_property("HOUSE", "counterparty", "CP1", 500_000.0, "residential")],
        )

        # Assert
        assert _row(df, "L1")["re_collateral_may_be_residential"] is True
        assert _row(df, "L2")["re_collateral_may_be_residential"] is True

    def test_no_collateral_file_is_not_residential(self) -> None:
        """No collateral at all: the flag is a definite False, never null."""
        # Act
        row = _row(_resolve([_loan("L1", 50_000.0)], None), "L1")

        # Assert
        assert row["re_collateral_may_be_residential"] is False


class TestRoutesTheCrmFollows:
    """The flag follows every route the CRM credits a house on (review F1)."""

    def test_house_reaches_a_loan_through_collateral_links(self) -> None:
        """A house whose own beneficiary is L0, linked to L0 AND L1, flags both."""
        # Arrange - the shop is L1's only DIRECT property, so its values miss the house
        collateral = [
            _property("SHOP", "loan", "L1", 200_000.0, "commercial"),
            _property("HOUSE", "loan", "L0", 1_000_000.0, "residential"),
        ]
        links = [
            {
                "collateral_reference": "HOUSE",
                "beneficiary_type": "loan",
                "beneficiary_reference": b,
            }
            for b in ("L0", "L1")
        ]

        # Act
        df = _resolve([_loan("L0", 300_000.0), _loan("L1", 300_000.0)], collateral, links=links)
        linked = _row(df, "L1")

        # Assert - the keep-first type sees only the shop; since P1.450 the value
        # carriers follow the link (a pro-rata half of the 1,000,000 house)
        assert linked["property_type"] == "commercial"
        assert linked["residential_collateral_value_uncapped"] == pytest.approx(500_000.0)
        # Assert - the flag follows the link
        assert linked["re_collateral_may_be_residential"] is True
        assert _row(df, "L0")["re_collateral_may_be_residential"] is True

    def test_link_to_a_shop_only_is_not_residential(self) -> None:
        """Links carry only what the linked item is: a linked SHOP flags nothing."""
        # Arrange
        collateral = [_property("SHOP", "loan", "L0", 200_000.0, "commercial")]
        links = [
            {"collateral_reference": "SHOP", "beneficiary_type": "loan", "beneficiary_reference": b}
            for b in ("L0", "L1")
        ]

        # Act
        df = _resolve([_loan("L0", 300_000.0), _loan("L1", 300_000.0)], collateral, links=links)

        # Assert
        assert _row(df, "L0")["re_collateral_may_be_residential"] is False
        assert _row(df, "L1")["re_collateral_may_be_residential"] is False

    def test_house_at_the_root_facility_reaches_a_loan_under_a_sub_facility(self) -> None:
        """ROOT -> SUB -> L1: a house pledged at ROOT cascades to L1 (CRM Art. 230-231)."""
        # Arrange
        facilities = [
            {**_FACILITY, "facility_reference": "ROOT", "limit": 300_000.0},
            {**_FACILITY, "facility_reference": "SUB", "limit": 300_000.0},
        ]
        mappings = [
            {
                "parent_facility_reference": "ROOT",
                "child_reference": "SUB",
                "child_type": "facility",
            },
            {"parent_facility_reference": "SUB", "child_reference": "L1", "child_type": "loan"},
        ]
        collateral = [
            _property("SHOP", "loan", "L1", 200_000.0, "commercial"),
            _property("HOUSE", "facility", "ROOT", 1_000_000.0, "residential"),
        ]

        # Act
        row = _row(
            _resolve(
                [_loan("L1", 300_000.0)], collateral, facilities=facilities, mappings=mappings
            ),
            "L1",
        )

        # Assert - adequacy: L1's immediate parent is SUB, and ROOT is an ancestor
        assert row["parent_facility_reference"] == "SUB"
        assert "ROOT" in row["ancestor_facilities"]
        assert row["residential_collateral_value_uncapped"] == pytest.approx(0.0)
        # Assert
        assert row["re_collateral_may_be_residential"] is True

    @pytest.mark.parametrize(
        "collateral_type", ["residential_property", "rre", "residential_re", "residential"]
    )
    def test_residential_collateral_type_synonym_is_residential(self, collateral_type: str) -> None:
        """A synonym the CRM credits as real estate names a house on its own."""
        # Arrange - shop first, so keep-first property_type reads commercial
        collateral = [
            _property("SHOP", "loan", "L1", 200_000.0, "commercial"),
            _property("HOUSE", "loan", "L1", 1_000_000.0, None, collateral_type=collateral_type),
        ]

        # Act
        row = _row(_resolve([_loan("L1", 300_000.0)], collateral), "L1")

        # Assert
        assert row["residential_collateral_value_uncapped"] == pytest.approx(0.0)
        assert row["re_collateral_may_be_residential"] is True

    @pytest.mark.parametrize("kind", [None, "adc"])
    def test_real_estate_of_unreported_or_adc_kind_may_be_residential(
        self, kind: str | None
    ) -> None:
        """Real estate not reported as commercial is not evidence of no house."""
        # Arrange
        collateral = [
            _property("SHOP", "loan", "L1", 200_000.0, "commercial"),
            _property("PROP", "loan", "L1", 500_000.0, kind),
        ]

        # Act
        row = _row(_resolve([_loan("L1", 300_000.0)], collateral), "L1")

        # Assert
        assert row["re_collateral_may_be_residential"] is True

    def test_commercial_synonym_alone_is_not_residential(self) -> None:
        """A shop under a commercial synonym (``cre``) is commercial: no flag."""
        # Arrange
        collateral = [
            _property("SHOP", "loan", "L1", 200_000.0, "commercial", collateral_type="cre")
        ]

        # Act
        row = _row(_resolve([_loan("L1", 300_000.0)], collateral), "L1")

        # Assert
        assert row["re_collateral_may_be_residential"] is False

    def test_non_property_collateral_is_not_residential(self) -> None:
        """Cash with no property type says nothing about a house."""
        # Arrange
        cash = {
            "collateral_reference": "CASH",
            "collateral_type": "cash",
            "currency": "GBP",
            "market_value": 50_000.0,
            "beneficiary_type": "loan",
            "beneficiary_reference": "L1",
        }

        # Act
        row = _row(_resolve([_loan("L1", 300_000.0)], [cash]), "L1")

        # Assert
        assert row["re_collateral_may_be_residential"] is False
