"""
Unit tests: real-estate collateral spread over several loans by ``collateral_links``
(P1.450, review CL-13).

Pipeline position:
    Loader -> HierarchyResolver (engine/hierarchy) -> Classifier

Key responsibilities pinned here:
- ``re_links.expand_real_estate_links`` feeds the hierarchy's property
  enrichment a view in which each linked real-estate item is replaced by one
  row per link. Every linked beneficiary then carries the property's
  attributes, a share of its value, and an LTV over all the loans the item
  secures (PS1/26 Art. 124C(3)).
- The share of value is pro rata to the PS1/26 Art. 124C(2) amount of each
  linked loan (drawn + interest + undrawn committed), capped by the link's
  ``max_pledge_amount``; the shares never sum above the property value. That
  is the owner-approved sharing convention for the Art. 124F / 124H 55% band
  across the firm's own pari passu exposures (sign-off brief P1.450).
- The collateral row's own beneficiary is REPLACED by the link rows, not added
  to, and the bundle's collateral frame is left untouched for the CRM stage's
  own link allocator.

Rule text (verbatim, PS1/26 Art. 124C(3)): "The amount of the loan which is
used for the calculation of the LTV shall include all other loans secured with
charges ranking in priority ahead of or pari passu with the charge that the
exposure is secured by. If there is insufficient information to determine the
ranking of other charges the institution shall rank the other charges pari
passu with the charge that the exposure is secured by."

CRR Art. 124(1) (watchfire snapshot of legislation.gov.uk): "The part of an
exposure that is treated as fully secured by immovable property shall not be
greater than the pledged amount of the market value ... of the immovable
property in question."

References:
- PS1/26 Art. 124, 124C(2)-(3), 124F(1), 124K(1)
- CRR Art. 124(1), 125(2)(d), 126(2)(d)
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.hierarchy import HierarchyResolver
from tests.fixtures.raw_bundle import make_raw_bundle

_PROPERTY_VALUE = 300_000.0
_LN_A_AMOUNT = 100_000.0
# LN_B carries accrued interest, so the Art. 124C(2) loan amount (120k) differs
# from the drawn-only basis the counterparty-pledge sibling uses (100k).
_LN_B_DRAWN = 100_000.0
_LN_B_INTEREST = 20_000.0
_LN_B_AMOUNT = _LN_B_DRAWN + _LN_B_INTEREST
_POOLED_LTV = (_LN_A_AMOUNT + _LN_B_AMOUNT) / _PROPERTY_VALUE  # 0.7333...


def _counterparty(ref: str) -> dict[str, Any]:
    return {
        "counterparty_reference": ref,
        "counterparty_name": ref,
        "entity_type": "individual",
        "country_code": "GB",
        "default_status": False,
        "is_natural_person": True,
    }


def _loan(ref: str, drawn: float, *, cp: str = "CP1", interest: float = 0.0) -> dict[str, Any]:
    return {
        "loan_reference": ref,
        "product_type": "RESIDENTIAL_MORTGAGE",
        "book_code": "B",
        "counterparty_reference": cp,
        "value_date": date(2024, 1, 1),
        "maturity_date": date(2045, 1, 1),
        "currency": "GBP",
        "drawn_amount": drawn,
        "interest": interest,
        "seniority": "senior",
    }


def _item(ref: str, beneficiary: str, value: float, **extra: Any) -> dict[str, Any]:
    return {
        "collateral_reference": ref,
        "collateral_type": "real_estate",
        "currency": "GBP",
        "market_value": value,
        "beneficiary_type": "loan",
        "beneficiary_reference": beneficiary,
        "property_type": "residential",
        "property_ltv": None,
        "is_qualifying_re": True,
        **extra,
    }


def _link(item: str, beneficiary: str, cap: float | None = None) -> dict[str, Any]:
    return {
        "collateral_reference": item,
        "beneficiary_type": "loan",
        "beneficiary_reference": beneficiary,
        "max_pledge_amount": cap,
    }


def _frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    keys: list[str] = []
    for row in rows:
        keys.extend(k for k in row if k not in keys)
    return pl.DataFrame({k: [row.get(k) for row in rows] for k in keys}, strict=False)


_EMPTY_MAPPINGS = pl.DataFrame(
    schema={
        "parent_facility_reference": pl.String,
        "child_reference": pl.String,
        "child_type": pl.String,
    }
)

_CONFIGS = {
    "crr": CalculationConfig.crr(reporting_date=date(2026, 6, 30)),
    "b31": CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30)),
}


def _default_loans() -> list[dict[str, Any]]:
    """LN_A and LN_B are linked to C1; LN_C, the same obligor's, is not."""
    return [
        _loan("LN_A", _LN_A_AMOUNT),
        _loan("LN_B", _LN_B_DRAWN, interest=_LN_B_INTEREST),
        _loan("LN_C", 50_000.0),
    ]


def _contingent(ref: str, nominal: float, *, cp: str = "CP1") -> dict[str, Any]:
    """A wholly undrawn commitment: its Art. 124C(2) amount is its nominal."""
    return {
        "contingent_reference": ref,
        "product_type": "LOAN_COMMITMENT",
        "book_code": "B",
        "counterparty_reference": cp,
        "value_date": date(2024, 1, 1),
        "maturity_date": date(2045, 1, 1),
        "currency": "GBP",
        "nominal_amount": nominal,
        "seniority": "senior",
        "risk_type": "full_risk",
        "bs_type": "OFB",
    }


def _resolve(
    *,
    loans: list[dict[str, Any]] | None = None,
    collateral: list[dict[str, Any]] | None = None,
    links: list[dict[str, Any]] | None = None,
    contingents: list[dict[str, Any]] | None = None,
    counterparties: tuple[str, ...] = ("CP1",),
    config: CalculationConfig | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame | None]:
    """Resolve the hierarchy; return the exposure frame and the bundle's collateral."""
    kwargs: dict[str, Any] = {
        "collateral": _frame(collateral or [_item("C1", "LN_A", _PROPERTY_VALUE)]),
    }
    if links is not None:
        kwargs["collateral_links"] = _frame(links)
    if contingents is not None:
        kwargs["contingents"] = _frame(contingents)
    bundle = make_raw_bundle(
        counterparties=_frame([_counterparty(cp) for cp in counterparties]),
        loans=_frame(loans or _default_loans()),
        facility_mappings=_EMPTY_MAPPINGS,
        **kwargs,
    )
    resolved = HierarchyResolver().resolve(bundle, config or _CONFIGS["b31"])
    collateral_out = None if resolved.collateral is None else resolved.collateral.collect()
    return resolved.exposures.collect(), collateral_out


def _row(frame: pl.DataFrame, ref: str) -> dict[str, Any]:
    rows = frame.filter(pl.col("exposure_reference") == ref).to_dicts()
    assert len(rows) == 1, f"expected exactly one exposure row for {ref}, got {len(rows)}"
    return rows[0]


_TWO_LINKS = [_link("C1", "LN_A"), _link("C1", "LN_B")]


class TestPooledLtv:
    """PS1/26 Art. 124C(3): every exposure the item secures carries the pooled LTV."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_every_linked_loan_carries_the_pooled_art_124c_ltv(self, regime: str) -> None:
        # Arrange
        assert _LN_B_AMOUNT != _LN_B_DRAWN, (
            "LN_B must carry interest, or the Art. 124C(2) basis cannot be told apart "
            "from the drawn-only basis and this test proves less than it claims"
        )

        # Act
        exposures, _ = _resolve(links=_TWO_LINKS, config=_CONFIGS[regime])

        # Assert - (100k + 120k) / 300k on BOTH loans, each flagged as derived.
        for ref in ("LN_A", "LN_B"):
            row = _row(exposures, ref)
            assert row["ltv"] == pytest.approx(_POOLED_LTV), ref
            assert row["ltv_derived"] is True, ref

    def test_prior_charges_enter_every_linked_loans_ltv(self) -> None:
        # Arrange - a charge ranking ahead worth 10% of the property value.
        collateral = [_item("C1", "LN_A", _PROPERTY_VALUE, prior_charge_ltv=0.10)]

        # Act
        exposures, _ = _resolve(collateral=collateral, links=_TWO_LINKS)

        # Assert - (100k + 120k + 30k) / 300k.
        expected = (_LN_A_AMOUNT + _LN_B_AMOUNT + 0.10 * _PROPERTY_VALUE) / _PROPERTY_VALUE
        for ref in ("LN_A", "LN_B"):
            assert _row(exposures, ref)["ltv"] == pytest.approx(expected), ref

    def test_link_set_spanning_two_obligors_pools_across_both(self) -> None:
        # Arrange - one 600k property securing a 100k loan of CP1 and a 200k loan of
        # CP2. Pooling by counterparty would leave each obligor's LTV on its own loan.
        loans = [_loan("LN_A", 100_000.0), _loan("LN_D", 200_000.0, cp="CP2")]
        collateral = [_item("C2", "LN_A", 600_000.0)]
        links = [_link("C2", "LN_A"), _link("C2", "LN_D")]

        # Act
        exposures, _ = _resolve(
            loans=loans, collateral=collateral, links=links, counterparties=("CP1", "CP2")
        )

        # Assert - (100k + 200k) / 600k on both, and the value shared 200k / 400k.
        for ref, share in (("LN_A", 200_000.0), ("LN_D", 400_000.0)):
            row = _row(exposures, ref)
            assert row["ltv"] == pytest.approx(0.5), ref
            assert row["residential_collateral_value_uncapped"] == pytest.approx(share), ref

    def test_facility_level_link_pools_with_a_direct_link(self) -> None:
        # Arrange - a 600k property linked to facility FAC_1 (LN_A 100k, LN_B 100k
        # + 20k interest, no undrawn headroom) and to CP2's loan LN_D (200k).
        loans = [*_default_loans()[:2], _loan("LN_D", 200_000.0, cp="CP2")]
        facility = {
            "facility_reference": "FAC_1",
            "counterparty_reference": "CP1",
            "currency": "GBP",
            "limit": 200_000.0,
            "value_date": date(2024, 1, 1),
            "maturity_date": date(2045, 1, 1),
        }
        mappings = pl.DataFrame(
            {
                "parent_facility_reference": ["FAC_1", "FAC_1"],
                "child_reference": ["LN_A", "LN_B"],
                "child_type": ["loan", "loan"],
            }
        )
        links = [
            {**_link("C3", "FAC_1"), "beneficiary_type": "facility"},
            _link("C3", "LN_D"),
        ]
        bundle = make_raw_bundle(
            counterparties=_frame([_counterparty("CP1"), _counterparty("CP2")]),
            loans=_frame(loans),
            facilities=_frame([facility]),
            facility_mappings=mappings,
            collateral=_frame([_item("C3", "LN_A", 600_000.0)]),
            collateral_links=_frame(links),
        )

        # Act
        exposures = HierarchyResolver().resolve(bundle, _CONFIGS["b31"]).exposures.collect()

        # Assert - (100k + 120k + 200k) / 600k on all three; the facility's part of
        # the value (600k x 220/420) is spread over its two loans, LN_D keeps 200/420.
        for ref in ("LN_A", "LN_B", "LN_D"):
            assert _row(exposures, ref)["ltv"] == pytest.approx(0.7), ref
        facility_value = sum(
            _row(exposures, ref)["residential_collateral_value_uncapped"]
            for ref in ("LN_A", "LN_B")
        )
        assert facility_value == pytest.approx(600_000.0 * 220.0 / 420.0)
        assert _row(exposures, "LN_D")["residential_collateral_value_uncapped"] == pytest.approx(
            600_000.0 * 200.0 / 420.0
        )


class TestValueShare:
    """The property value is shared pro rata, never double counted."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_linked_loans_share_the_property_value_pro_rata_by_loan_amount(
        self, regime: str
    ) -> None:
        # Act
        exposures, _ = _resolve(links=_TWO_LINKS, config=_CONFIGS[regime])

        # Assert - 300k x 100/220 and 300k x 120/220.
        total = _LN_A_AMOUNT + _LN_B_AMOUNT
        share_a = _row(exposures, "LN_A")["residential_collateral_value_uncapped"]
        share_b = _row(exposures, "LN_B")["residential_collateral_value_uncapped"]
        assert share_a == pytest.approx(_PROPERTY_VALUE * _LN_A_AMOUNT / total)
        assert share_b == pytest.approx(_PROPERTY_VALUE * _LN_B_AMOUNT / total)

    def test_linked_shares_never_sum_above_the_property_value(self) -> None:
        # Guard (green before the fix too: 300k + 0): an over-broadcast fix that
        # gives every linked loan the whole value would fail it.
        exposures, _ = _resolve(links=_TWO_LINKS)

        shares = exposures.filter(pl.col("exposure_reference").is_in(["LN_A", "LN_B"]))
        assert shares["residential_collateral_value_uncapped"].sum() == pytest.approx(
            _PROPERTY_VALUE
        )

    def test_max_pledge_amount_caps_a_link_share(self) -> None:
        # Arrange - the link to LN_A may carry at most 50k of the property.
        links = [_link("C1", "LN_A", cap=50_000.0), _link("C1", "LN_B")]

        # Act
        exposures, _ = _resolve(links=links)

        # Assert - LN_A is secured by 50k only (CRR Art. 124(1) "pledged amount"),
        # so its LTV is its own 100k over that 50k; LN_B keeps its pro-rata share.
        row_a = _row(exposures, "LN_A")
        row_b = _row(exposures, "LN_B")
        assert row_a["residential_collateral_value_uncapped"] == pytest.approx(50_000.0)
        assert row_a["ltv"] == pytest.approx(_LN_A_AMOUNT / 50_000.0)
        share_b = _PROPERTY_VALUE * _LN_B_AMOUNT / (_LN_A_AMOUNT + _LN_B_AMOUNT)
        assert row_b["residential_collateral_value_uncapped"] == pytest.approx(share_b)


class TestAttributes:
    """Every property attribute and flag reaches every linked beneficiary."""

    def test_property_attributes_reach_every_linked_loan(self) -> None:
        # Arrange - a non-qualifying (Art. 124A failure) ADC property.
        collateral = [_item("C1", "LN_A", _PROPERTY_VALUE, is_qualifying_re=False, is_adc=True)]

        # Act
        exposures, _ = _resolve(collateral=collateral, links=_TWO_LINKS)

        # Assert
        row_b = _row(exposures, "LN_B")
        assert row_b["property_type"] == "residential"
        assert row_b["is_qualifying_re"] is False
        assert row_b["re_collateral_non_qualifying"] is True
        assert row_b["re_collateral_is_adc"] is True
        assert row_b["property_collateral_value"] > 0.0

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_contingent_link_takes_the_property_attributes(self, regime: str) -> None:
        # Arrange - a ``contingent`` link (the label the CRM stage requires for a
        # contingent) to a wholly undrawn 100k commitment on a non-qualifying
        # commercial property. At HEAD (before P1.450) CT_1 got no property value
        # and no LTV at all; an earlier draft of this fix read only ``exposure`` /
        # ``loan`` labels as direct and gave it the value and LTV but no property
        # type or qualifying flag.
        collateral = [
            _item("C1", "LN_A", 400_000.0, property_type="commercial", is_qualifying_re=False)
        ]
        links = [
            _link("C1", "LN_A"),
            {**_link("C1", "CT_1"), "beneficiary_type": "contingent"},
        ]

        # Act
        exposures, _ = _resolve(
            loans=[_loan("LN_A", 100_000.0)],
            collateral=collateral,
            links=links,
            contingents=[_contingent("CT_1", 100_000.0)],
            config=_CONFIGS[regime],
        )

        # Assert - the same attributes as LN_A; half the value on its committed amount.
        row = _row(exposures, "CT_1")
        assert row["property_type"] == "commercial"
        assert row["is_qualifying_re"] is False
        assert row["re_collateral_non_qualifying"] is True
        assert row["commercial_collateral_value_uncapped"] == pytest.approx(200_000.0)
        assert row["ltv"] == pytest.approx(0.5)

    def test_unlinked_loan_of_the_same_obligor_takes_nothing(self) -> None:
        # Guard against turning the link set into a counterparty-level pledge: LN_C
        # belongs to the same obligor but no link names it.
        exposures, _ = _resolve(links=_TWO_LINKS)

        row_c = _row(exposures, "LN_C")
        assert row_c["property_collateral_value"] == 0.0
        assert row_c["residential_collateral_value_uncapped"] == 0.0
        assert row_c["ltv"] is None
        assert row_c["property_type"] is None
        assert row_c["re_collateral_non_qualifying"] is False


class TestReplacement:
    """The link rows REPLACE the collateral row's own beneficiary."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_item_rows_own_beneficiary_outside_its_link_set_takes_nothing(
        self, regime: str
    ) -> None:
        # Arrange - the item row names LN_A, but its only link names LN_B: the
        # links say what the property secures (as the CRM link allocator reads them).
        links = [_link("C1", "LN_B")]

        # Act
        exposures, _ = _resolve(links=links, config=_CONFIGS[regime])

        # Assert - LN_A is unsecured; LN_B holds the whole value, LTV 120k / 300k.
        row_a = _row(exposures, "LN_A")
        row_b = _row(exposures, "LN_B")
        assert row_a["ltv"] is None
        assert row_a["property_type"] is None
        assert row_a["property_collateral_value"] == 0.0
        assert row_b["residential_collateral_value_uncapped"] == pytest.approx(_PROPERTY_VALUE)
        assert row_b["ltv"] == pytest.approx(_LN_B_AMOUNT / _PROPERTY_VALUE)


_RESIDENTIAL_ITEM = _item("C1", "LN_A", _PROPERTY_VALUE)
_COMMERCIAL_ITEM = _item(
    "C2", "LN_A", 200_000.0, property_type="commercial", is_qualifying_re=False
)
_TWO_ITEM_LINKS = [
    _link("C1", "LN_A"),
    _link("C1", "LN_B"),
    _link("C2", "LN_A"),
    _link("C2", "LN_B"),
]
_REPEATS = 10


def _resolve_repeatedly(
    collateral: list[dict[str, Any]], config: CalculationConfig
) -> list[pl.DataFrame]:
    """Resolve the same two-item, two-loan input ``_REPEATS`` times, rows sorted."""
    loans = [_loan("LN_A", 100_000.0), _loan("LN_B", 100_000.0)]
    return [
        _resolve(loans=loans, collateral=collateral, links=_TWO_ITEM_LINKS, config=config)[0].sort(
            "exposure_reference"
        )
        for _ in range(_REPEATS)
    ]


class TestPrecedence:
    """A loan linked to two items resolves one way, the first-listed item's, every run.

    Each of LN_A and LN_B (100k) is linked to C1 (residential, qualifying,
    300k) and C2 (commercial, failing Art. 124A, 200k). Single-valued
    attributes come from one item: the first in the collateral table's row
    order, the rule the unlinked path applies to two rows naming one loan.
    Before the view's order was fixed the joins returned the link rows in a
    different order on each run, so each loan took C1's or C2's attributes at
    random (four outcomes in twelve runs).
    """

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_loan_linked_to_two_items_resolves_the_same_on_every_run(self, regime: str) -> None:
        # Act
        runs = _resolve_repeatedly([_RESIDENTIAL_ITEM, _COMMERCIAL_ITEM], _CONFIGS[regime])

        # Assert - one outcome across every run, and it is C1's (listed first).
        assert len({tuple(run.rows()) for run in runs}) == 1, "resolution varies run to run"
        for ref in ("LN_A", "LN_B"):
            row = _row(runs[0], ref)
            assert row["property_type"] == "residential", ref
            assert row["is_qualifying_re"] is True, ref
            # The any-True flag and the values read both items, whatever the order:
            # 300k x 100/200 residential + 200k x 100/200 commercial; LTV 100k / 250k.
            assert row["re_collateral_non_qualifying"] is True, ref
            assert row["residential_collateral_value_uncapped"] == pytest.approx(150_000.0), ref
            assert row["commercial_collateral_value_uncapped"] == pytest.approx(100_000.0), ref
            assert row["ltv"] == pytest.approx(0.4), ref

    def test_first_listed_item_wins_whichever_it_is(self) -> None:
        # Arrange - the same input with C2 listed first: the rule is the row order,
        # not a preference for residential or qualifying property.

        # Act
        runs = _resolve_repeatedly([_COMMERCIAL_ITEM, _RESIDENTIAL_ITEM], _CONFIGS["b31"])

        # Assert
        assert len({tuple(run.rows()) for run in runs}) == 1, "resolution varies run to run"
        for ref in ("LN_A", "LN_B"):
            row = _row(runs[0], ref)
            assert row["property_type"] == "commercial", ref
            assert row["is_qualifying_re"] is False, ref


class TestScope:
    """What the expansion leaves alone."""

    def test_bundle_collateral_is_left_untouched_for_crm(self) -> None:
        # The CRM stage expands the links itself; a hierarchy-expanded frame on the
        # bundle would be expanded twice.
        _, collateral = _resolve(links=_TWO_LINKS)

        assert collateral is not None
        assert collateral.height == 1
        assert collateral.row(0, named=True)["beneficiary_reference"] == "LN_A"
        assert collateral.row(0, named=True)["market_value"] == pytest.approx(_PROPERTY_VALUE)

    def test_link_splitting_disabled_keeps_the_collateral_rows_own_beneficiary(self) -> None:
        # Arrange
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 30), enable_collateral_link_splitting=False
        )

        # Act
        exposures, _ = _resolve(links=_TWO_LINKS, config=config)

        # Assert - the single-beneficiary path: LN_A alone, on its own loan.
        assert _row(exposures, "LN_A")["ltv"] == pytest.approx(_LN_A_AMOUNT / _PROPERTY_VALUE)
        assert _row(exposures, "LN_B")["ltv"] is None

    def test_links_naming_only_non_property_collateral_leave_property_unchanged(self) -> None:
        # Arrange - the links table spreads a cash item; the property is unlinked.
        collateral = [
            _item("C1", "LN_A", _PROPERTY_VALUE),
            {
                "collateral_reference": "CASH1",
                "collateral_type": "cash",
                "currency": "GBP",
                "market_value": 10_000.0,
                "beneficiary_type": "loan",
                "beneficiary_reference": "LN_A",
            },
        ]
        links = [_link("CASH1", "LN_A"), _link("CASH1", "LN_B")]

        # Act
        exposures, _ = _resolve(collateral=collateral, links=links)

        # Assert
        assert _row(exposures, "LN_A")["ltv"] == pytest.approx(_LN_A_AMOUNT / _PROPERTY_VALUE)
        assert _row(exposures, "LN_B")["ltv"] is None
        assert _row(exposures, "LN_B")["property_collateral_value"] == 0.0
