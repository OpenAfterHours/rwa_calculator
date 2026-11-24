"""
P1.444 (review CL-03): the link allocator credits a repeated collateral row once.

``collateral_reference`` is a unique identifier on the collateral table; a
repeat breaches the input contract and draws DQ004 at the input gate. When the
firm also supplies a ``collateral_links`` table, the allocator used to join the
collateral table onto its link edges by ``collateral_reference`` twice — once
for the finite value, once for the row attributes — and both joins fanned out
on the repeat: an item stated twice at 60 reached its beneficiary as two rows
of 60, i.e. 120 credited from a 60 item. The seeded value also depended on
which duplicate sorted first.

PS1/26 Art. 193(7)(b): each portion of an item of eligible collateral is
allocated to one of the exposures it covers "without any double-counting".

Owner decision (sign-off brief P1.444): the allocator uses ONE row per
collateral_reference, the duplicate stating the SMALLEST value, so no item is
credited more than any single row states. Not the max / keep-largest rule of
``engine/crm/protection_value.py`` (guarantee pools), which can lower RWA.
Rows without a links table, and every row when
``enable_collateral_link_splitting`` is False, never reach the allocator and
stay applied as stated; so does a duplicate the links table does not name,
which passes through the allocator untouched. Because the duplicate no longer inflates the item's
link fan-out, the item also draws in the well-formed order, so the fix can
move RWA either way against the old duplicated result.

Scope: these tests pin the allocator only. Real-estate property attributes
(read row by row in the hierarchy stage, which never reads
``collateral_links``) and third-party deposits (split out of the collateral
frame before the allocator runs) are still applied once per row even when
links name the item -- a recorded residual of P1.444, not covered here.

References:
- PS1/26 Art. 193(2), 193(7)(a)-(c)
- CRR Art. 230-231: sequential allocation of collateral
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.crm.link_allocation import CollateralLinkAllocator


@pytest.fixture
def config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2026, 1, 1))


def _exposures() -> pl.LazyFrame:
    """L1 (demand 100, denser) ranks before L2 (demand 100)."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["L1", "L2"],
            "ead_for_crm": [100.0, 100.0],
            "_link_rank_metric": [1.0, 0.5],
            "parent_facility_reference": [None, None],
            "counterparty_reference": [None, None],
        },
        schema_overrides={
            "parent_facility_reference": pl.String,
            "counterparty_reference": pl.String,
        },
    )


def _collateral(rows: list[tuple[str | None, float, str, str]]) -> pl.LazyFrame:
    """Rows of (collateral_reference, market_value, currency, beneficiary_reference)."""
    return pl.LazyFrame(
        {
            "collateral_reference": [r[0] for r in rows],
            "collateral_type": ["cash"] * len(rows),
            "market_value": [r[1] for r in rows],
            "currency": [r[2] for r in rows],
            "beneficiary_type": ["loan"] * len(rows),
            "beneficiary_reference": [r[3] for r in rows],
        },
        schema_overrides={"collateral_reference": pl.String},
    )


def _links() -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "collateral_reference": ["C1", "C1"],
            "beneficiary_type": ["loan", "loan"],
            "beneficiary_reference": ["L1", "L2"],
        }
    )


def _expanded_c1(collateral: pl.LazyFrame, config: CalculationConfig) -> pl.DataFrame:
    result = CollateralLinkAllocator().allocate_links(_exposures(), collateral, _links(), config)
    assert result.collateral is not None
    return result.collateral.filter(pl.col("collateral_reference") == "C1").collect()


class TestDuplicateCollateralRowIsCreditedOnce:
    def test_single_row_control_credits_its_value(self, config: CalculationConfig) -> None:
        # Arrange — the well-formed input: C1 stated once at 60.
        collateral = _collateral([("C1", 60.0, "GBP", "L1")])

        # Act
        expanded = _expanded_c1(collateral, config)

        # Assert — 60 to L1 (denser), nothing left for L2.
        assert expanded["market_value"].sum() == pytest.approx(60.0)
        assert expanded["beneficiary_reference"].to_list() == ["L1"]

    def test_identical_duplicate_rows_credit_one_value(self, config: CalculationConfig) -> None:
        # Arrange — C1 repeated at 60 (one row per beneficiary). HEAD: 120.
        collateral = _collateral([("C1", 60.0, "GBP", "L1"), ("C1", 60.0, "GBP", "L2")])

        # Act
        expanded = _expanded_c1(collateral, config)

        # Assert
        assert expanded["market_value"].sum() == pytest.approx(60.0)
        assert expanded["beneficiary_reference"].to_list() == ["L1"]

    def test_differing_duplicates_credit_the_smallest_value(
        self, config: CalculationConfig
    ) -> None:
        # Arrange — the rows differ in value AND in a non-override attribute
        # (currency), so a bare unique() on the lookups keeps both. HEAD: 120.
        collateral = _collateral([("C1", 60.0, "GBP", "L1"), ("C1", 40.0, "EUR", "L2")])

        # Act
        expanded = _expanded_c1(collateral, config)

        # Assert — one slice per (item, beneficiary), at the smaller stated
        # value, carrying the attributes of the row that states it.
        assert expanded["market_value"].sum() == pytest.approx(40.0)
        assert expanded.select("beneficiary_reference", "currency").rows() == [("L1", "EUR")]

    def test_the_chosen_row_does_not_depend_on_input_order(self, config: CalculationConfig) -> None:
        # Arrange — the same two rows, supplied the other way round.
        collateral = _collateral([("C1", 40.0, "EUR", "L2"), ("C1", 60.0, "GBP", "L1")])

        # Act
        expanded = _expanded_c1(collateral, config)

        # Assert
        assert expanded["market_value"].sum() == pytest.approx(40.0)
        assert expanded.select("beneficiary_reference", "currency").rows() == [("L1", "EUR")]

    def test_unlinked_null_reference_rows_pass_through_uncollapsed(
        self, config: CalculationConfig
    ) -> None:
        # Arrange — two unnamed rows (a null reference is legal, e.g. a policy)
        # beside the linked duplicate: keying a de-duplication on the reference
        # must not fold them into one.
        collateral = _collateral(
            [
                ("C1", 60.0, "GBP", "L1"),
                ("C1", 60.0, "GBP", "L2"),
                (None, 10.0, "GBP", "L1"),
                (None, 15.0, "GBP", "L2"),
            ]
        )

        # Act
        result = CollateralLinkAllocator().allocate_links(
            _exposures(), collateral, _links(), config
        )
        assert result.collateral is not None
        unnamed = result.collateral.filter(pl.col("collateral_reference").is_null()).collect()

        # Assert
        assert sorted(unnamed["market_value"].to_list()) == [10.0, 15.0]

    def test_duplicate_the_links_do_not_name_passes_through_as_stated(
        self, config: CalculationConfig
    ) -> None:
        # Arrange — a links table is supplied, but it names only C1. C2 is
        # stated twice and named by no link, so it takes the same path as a
        # duplicate with no links table at all: every row applied as stated.
        collateral = _collateral(
            [
                ("C1", 60.0, "GBP", "L1"),
                ("C2", 30.0, "GBP", "L1"),
                ("C2", 25.0, "EUR", "L2"),
            ]
        )

        # Act
        result = CollateralLinkAllocator().allocate_links(
            _exposures(), collateral, _links(), config
        )
        assert result.collateral is not None
        c2 = result.collateral.filter(pl.col("collateral_reference") == "C2").collect()

        # Assert — both C2 rows, unchanged, on their own beneficiaries.
        assert sorted(c2.select("beneficiary_reference", "market_value", "currency").rows()) == [
            ("L1", 30.0, "GBP"),
            ("L2", 25.0, "EUR"),
        ]
