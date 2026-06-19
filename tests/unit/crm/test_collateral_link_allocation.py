"""
Unit tests for ``CollateralLinkAllocator`` — the finite-value split of one
collateral item across multiple linked beneficiaries.

The allocator expands the M:N collateral_links table into per-beneficiary
collateral rows, splitting each finite value greedily for the most beneficial
RWA impact (highest pre-CRM RWA density first), honouring optional per-link
caps, and never over-claiming (Σ slices ≤ value).

References:
- CRR Art. 193/194/207: CRM eligibility and recognition
- CRR Art. 230-231: substitution / sequential allocation of collateral
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


def _exposures(rows: list[dict]) -> pl.LazyFrame:
    """Build a minimal exposures frame the allocator can rank and size."""
    return pl.LazyFrame(
        rows,
        schema={
            "exposure_reference": pl.String,
            "ead_for_crm": pl.Float64,
            "_link_rank_metric": pl.Float64,
            "parent_facility_reference": pl.String,
            "counterparty_reference": pl.String,
        },
    )


def _collateral(rows: list[dict]) -> pl.LazyFrame:
    return pl.LazyFrame(
        rows,
        schema={
            "collateral_reference": pl.String,
            "collateral_type": pl.String,
            "market_value": pl.Float64,
            "currency": pl.String,
            "beneficiary_type": pl.String,
            "beneficiary_reference": pl.String,
        },
    )


def _links(rows: list[dict]) -> pl.LazyFrame:
    return pl.LazyFrame(
        rows,
        schema={
            "collateral_reference": pl.String,
            "beneficiary_type": pl.String,
            "beneficiary_reference": pl.String,
            "max_pledge_amount": pl.Float64,
            "priority": pl.Int32,
        },
    )


def _allocated(result_lf: pl.LazyFrame) -> dict[str, float]:
    """Map beneficiary_reference -> total allocated market_value."""
    df = result_lf.group_by("beneficiary_reference").agg(pl.col("market_value").sum()).collect()
    return {row["beneficiary_reference"]: row["market_value"] for row in df.to_dicts()}


class TestFiniteValueSplit:
    def test_single_collateral_two_loans_splits_by_finite_value(
        self, config: CalculationConfig
    ) -> None:
        # Arrange — equal RWA density, so lexical tie-break fills L1 then L2.
        exposures = _exposures(
            [
                {
                    "exposure_reference": "L1",
                    "ead_for_crm": 400.0,
                    "_link_rank_metric": 1.0,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
                {
                    "exposure_reference": "L2",
                    "ead_for_crm": 400.0,
                    "_link_rank_metric": 1.0,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
            ]
        )
        collateral = _collateral(
            [
                {
                    "collateral_reference": "C1",
                    "collateral_type": "cash",
                    "market_value": 500.0,
                    "currency": "GBP",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                }
            ]
        )
        links = _links(
            [
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                    "max_pledge_amount": None,
                    "priority": None,
                },
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L2",
                    "max_pledge_amount": None,
                    "priority": None,
                },
            ]
        )

        # Act
        result = CollateralLinkAllocator().allocate_links(exposures, collateral, links, config)
        assert result.collateral is not None
        alloc = _allocated(result.collateral)

        # Assert — finite value 500 split 400 + 100, never exceeding the value.
        assert alloc.get("L1") == pytest.approx(400.0)
        assert alloc.get("L2", 0.0) == pytest.approx(100.0)
        assert sum(alloc.values()) == pytest.approx(500.0)

    def test_rwa_minimising_order(self, config: CalculationConfig) -> None:
        # Arrange — A is a 150% RW loan, B is 20% RW; collateral covers only one.
        exposures = _exposures(
            [
                {
                    "exposure_reference": "A",
                    "ead_for_crm": 300.0,
                    "_link_rank_metric": 1.5,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
                {
                    "exposure_reference": "B",
                    "ead_for_crm": 300.0,
                    "_link_rank_metric": 0.2,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
            ]
        )
        collateral = _collateral(
            [
                {
                    "collateral_reference": "C1",
                    "collateral_type": "cash",
                    "market_value": 300.0,
                    "currency": "GBP",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "A",
                }
            ]
        )
        links = _links(
            [
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "A",
                    "max_pledge_amount": None,
                    "priority": None,
                },
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "B",
                    "max_pledge_amount": None,
                    "priority": None,
                },
            ]
        )

        # Act
        result = CollateralLinkAllocator().allocate_links(exposures, collateral, links, config)
        assert result.collateral is not None
        alloc = _allocated(result.collateral)

        # Assert — all collateral lands on the higher-RWA-density loan A.
        assert alloc.get("A") == pytest.approx(300.0)
        assert alloc.get("B", 0.0) == pytest.approx(0.0)

    def test_no_overclaim_when_demand_exceeds_value(self, config: CalculationConfig) -> None:
        # Arrange — total demand 1000, value only 400.
        exposures = _exposures(
            [
                {
                    "exposure_reference": "L1",
                    "ead_for_crm": 500.0,
                    "_link_rank_metric": 1.0,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
                {
                    "exposure_reference": "L2",
                    "ead_for_crm": 500.0,
                    "_link_rank_metric": 1.0,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
            ]
        )
        collateral = _collateral(
            [
                {
                    "collateral_reference": "C1",
                    "collateral_type": "cash",
                    "market_value": 400.0,
                    "currency": "GBP",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                }
            ]
        )
        links = _links(
            [
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                    "max_pledge_amount": None,
                    "priority": None,
                },
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L2",
                    "max_pledge_amount": None,
                    "priority": None,
                },
            ]
        )

        # Act
        result = CollateralLinkAllocator().allocate_links(exposures, collateral, links, config)
        assert result.collateral is not None
        alloc = _allocated(result.collateral)

        # Assert
        assert sum(alloc.values()) == pytest.approx(400.0)

    def test_max_pledge_amount_sub_limit_respected(self, config: CalculationConfig) -> None:
        # Arrange — L1 is higher density but capped at 100; remainder flows to L2.
        exposures = _exposures(
            [
                {
                    "exposure_reference": "L1",
                    "ead_for_crm": 400.0,
                    "_link_rank_metric": 2.0,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
                {
                    "exposure_reference": "L2",
                    "ead_for_crm": 400.0,
                    "_link_rank_metric": 1.0,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
            ]
        )
        collateral = _collateral(
            [
                {
                    "collateral_reference": "C1",
                    "collateral_type": "cash",
                    "market_value": 500.0,
                    "currency": "GBP",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                }
            ]
        )
        links = _links(
            [
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                    "max_pledge_amount": 100.0,
                    "priority": None,
                },
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L2",
                    "max_pledge_amount": None,
                    "priority": None,
                },
            ]
        )

        # Act
        result = CollateralLinkAllocator().allocate_links(exposures, collateral, links, config)
        assert result.collateral is not None
        alloc = _allocated(result.collateral)

        # Assert — L1 capped at its 100 sub-limit, L2 takes the remaining 400.
        assert alloc.get("L1") == pytest.approx(100.0)
        assert alloc.get("L2") == pytest.approx(400.0)

    def test_priority_override_beats_metric(self, config: CalculationConfig) -> None:
        # Arrange — L2 has higher density but L1 is given explicit priority 1.
        exposures = _exposures(
            [
                {
                    "exposure_reference": "L1",
                    "ead_for_crm": 300.0,
                    "_link_rank_metric": 0.2,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
                {
                    "exposure_reference": "L2",
                    "ead_for_crm": 300.0,
                    "_link_rank_metric": 1.5,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
            ]
        )
        collateral = _collateral(
            [
                {
                    "collateral_reference": "C1",
                    "collateral_type": "cash",
                    "market_value": 300.0,
                    "currency": "GBP",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                }
            ]
        )
        links = _links(
            [
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                    "max_pledge_amount": None,
                    "priority": 1,
                },
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L2",
                    "max_pledge_amount": None,
                    "priority": 2,
                },
            ]
        )

        # Act
        result = CollateralLinkAllocator().allocate_links(exposures, collateral, links, config)
        assert result.collateral is not None
        alloc = _allocated(result.collateral)

        # Assert — priority wins: L1 filled first despite lower density.
        assert alloc.get("L1") == pytest.approx(300.0)
        assert alloc.get("L2", 0.0) == pytest.approx(0.0)

    def test_unlinked_collateral_passes_through_unchanged(self, config: CalculationConfig) -> None:
        # Arrange — C1 is linked (split), C2 has no links (passthrough).
        exposures = _exposures(
            [
                {
                    "exposure_reference": "L1",
                    "ead_for_crm": 400.0,
                    "_link_rank_metric": 1.0,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
                {
                    "exposure_reference": "L3",
                    "ead_for_crm": 999.0,
                    "_link_rank_metric": 1.0,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
            ]
        )
        collateral = _collateral(
            [
                {
                    "collateral_reference": "C1",
                    "collateral_type": "cash",
                    "market_value": 200.0,
                    "currency": "GBP",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                },
                {
                    "collateral_reference": "C2",
                    "collateral_type": "cash",
                    "market_value": 50.0,
                    "currency": "GBP",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L3",
                },
            ]
        )
        links = _links(
            [
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                    "max_pledge_amount": None,
                    "priority": None,
                }
            ]
        )

        # Act
        result = CollateralLinkAllocator().allocate_links(exposures, collateral, links, config)
        assert result.collateral is not None
        df = result.collateral.collect()

        # Assert — C2 survives untouched with its original beneficiary and value.
        c2 = df.filter(pl.col("collateral_reference") == "C2")
        assert c2.height == 1
        assert c2["beneficiary_reference"][0] == "L3"
        assert c2["market_value"][0] == pytest.approx(50.0)

    def test_facility_and_contingent_links_resolve(self, config: CalculationConfig) -> None:
        # Arrange — one item linked to a loan, a contingent, and a facility pool.
        exposures = _exposures(
            [
                {
                    "exposure_reference": "L1",
                    "ead_for_crm": 100.0,
                    "_link_rank_metric": 1.0,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
                {
                    "exposure_reference": "CT1",
                    "ead_for_crm": 100.0,
                    "_link_rank_metric": 1.0,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
                {
                    "exposure_reference": "FL1",
                    "ead_for_crm": 100.0,
                    "_link_rank_metric": 1.0,
                    "parent_facility_reference": "F9",
                    "counterparty_reference": None,
                },
            ]
        )
        collateral = _collateral(
            [
                {
                    "collateral_reference": "C1",
                    "collateral_type": "cash",
                    "market_value": 1000.0,
                    "currency": "GBP",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                }
            ]
        )
        links = _links(
            [
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                    "max_pledge_amount": None,
                    "priority": None,
                },
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "contingent",
                    "beneficiary_reference": "CT1",
                    "max_pledge_amount": None,
                    "priority": None,
                },
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "facility",
                    "beneficiary_reference": "F9",
                    "max_pledge_amount": None,
                    "priority": None,
                },
            ]
        )

        # Act
        result = CollateralLinkAllocator().allocate_links(exposures, collateral, links, config)
        assert result.collateral is not None
        alloc = _allocated(result.collateral)

        # Assert — all three beneficiary types resolve and receive a slice.
        assert alloc.get("L1") == pytest.approx(100.0)
        assert alloc.get("CT1") == pytest.approx(100.0)
        assert alloc.get("F9") == pytest.approx(100.0)


def _facilities(rows: list[dict]) -> pl.LazyFrame:
    """Exposures frame where each row is the sole child of its facility."""
    return _exposures(rows)


class TestJointResidualAllocation:
    """Allocation across MULTIPLE collateral items must share demand residuals.

    These cases only diverge from the legacy per-item greedy when two or more
    items compete for the same beneficiaries; with a single item the joint
    walk reduces to the old cumulative-cap split (covered by
    ``TestFiniteValueSplit``).
    """

    def test_two_items_two_facilities_joint_fill(self, config: CalculationConfig) -> None:
        # Arrange — two 100m items each linked to F1 (RW 37%) and F2 (RW 40%).
        # Legacy greedy dumps BOTH onto F2 (highest RW) → F2 gets 200 of 100
        # demand (100 wasted) and F1 is starved. The joint walk fills F2 from
        # one item then spills the other to F1.
        exposures = _facilities(
            [
                {
                    "exposure_reference": "E1",
                    "ead_for_crm": 100.0,
                    "_link_rank_metric": 0.37,
                    "parent_facility_reference": "F1",
                    "counterparty_reference": None,
                },
                {
                    "exposure_reference": "E2",
                    "ead_for_crm": 100.0,
                    "_link_rank_metric": 0.40,
                    "parent_facility_reference": "F2",
                    "counterparty_reference": None,
                },
            ]
        )
        collateral = _collateral(
            [
                {
                    "collateral_reference": "C1",
                    "collateral_type": "cash",
                    "market_value": 100.0,
                    "currency": "GBP",
                    "beneficiary_type": "facility",
                    "beneficiary_reference": "F1",
                },
                {
                    "collateral_reference": "C2",
                    "collateral_type": "cash",
                    "market_value": 100.0,
                    "currency": "GBP",
                    "beneficiary_type": "facility",
                    "beneficiary_reference": "F2",
                },
            ]
        )
        links = _links(
            [
                {
                    "collateral_reference": ref,
                    "beneficiary_type": "facility",
                    "beneficiary_reference": fac,
                    "max_pledge_amount": None,
                    "priority": None,
                }
                for ref in ("C1", "C2")
                for fac in ("F1", "F2")
            ]
        )

        # Act
        result = CollateralLinkAllocator().allocate_links(exposures, collateral, links, config)
        assert result.collateral is not None
        alloc = _allocated(result.collateral)

        # Assert — both facilities fully covered, nothing wasted.
        assert alloc.get("F1") == pytest.approx(100.0)
        assert alloc.get("F2") == pytest.approx(100.0)
        assert sum(alloc.values()) == pytest.approx(200.0)

    def test_constrained_item_not_stranded(self, config: CalculationConfig) -> None:
        # Arrange — COLL_HIGH can ONLY serve HIGH; COLL_FLEX can serve both.
        # If HIGH greedily draws from the flexible item first, COLL_HIGH is
        # stranded (HIGH already full) and LOW starves. Drawing from the
        # most-constrained item first leaves COLL_FLEX free for LOW.
        exposures = _exposures(
            [
                {
                    "exposure_reference": "HIGH",
                    "ead_for_crm": 100.0,
                    "_link_rank_metric": 1.5,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
                {
                    "exposure_reference": "LOW",
                    "ead_for_crm": 100.0,
                    "_link_rank_metric": 0.2,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                },
            ]
        )
        collateral = _collateral(
            [
                {
                    "collateral_reference": "COLL_FLEX",
                    "collateral_type": "cash",
                    "market_value": 100.0,
                    "currency": "GBP",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "HIGH",
                },
                {
                    "collateral_reference": "COLL_HIGH",
                    "collateral_type": "cash",
                    "market_value": 100.0,
                    "currency": "GBP",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "HIGH",
                },
            ]
        )
        # COLL_FLEX sorts before COLL_HIGH lexically — so only the fanout
        # tie-break (not collateral_reference order) can save COLL_HIGH.
        links = _links(
            [
                {
                    "collateral_reference": "COLL_FLEX",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "HIGH",
                    "max_pledge_amount": None,
                    "priority": None,
                },
                {
                    "collateral_reference": "COLL_FLEX",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "LOW",
                    "max_pledge_amount": None,
                    "priority": None,
                },
                {
                    "collateral_reference": "COLL_HIGH",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "HIGH",
                    "max_pledge_amount": None,
                    "priority": None,
                },
            ]
        )

        # Act
        result = CollateralLinkAllocator().allocate_links(exposures, collateral, links, config)
        assert result.collateral is not None
        alloc = _allocated(result.collateral)

        # Assert — both filled; the constrained item is not wasted.
        assert alloc.get("HIGH") == pytest.approx(100.0)
        assert alloc.get("LOW") == pytest.approx(100.0)
        assert sum(alloc.values()) == pytest.approx(200.0)

    def test_duplicate_link_no_double_spend(self, config: CalculationConfig) -> None:
        # Arrange — the same item↔beneficiary link supplied twice must draw
        # from a single shared demand residual, never double-counting.
        exposures = _exposures(
            [
                {
                    "exposure_reference": "L1",
                    "ead_for_crm": 100.0,
                    "_link_rank_metric": 1.0,
                    "parent_facility_reference": None,
                    "counterparty_reference": None,
                }
            ]
        )
        collateral = _collateral(
            [
                {
                    "collateral_reference": "C1",
                    "collateral_type": "cash",
                    "market_value": 100.0,
                    "currency": "GBP",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                }
            ]
        )
        links = _links(
            [
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                    "max_pledge_amount": None,
                    "priority": None,
                },
                {
                    "collateral_reference": "C1",
                    "beneficiary_type": "loan",
                    "beneficiary_reference": "L1",
                    "max_pledge_amount": None,
                    "priority": None,
                },
            ]
        )

        # Act
        result = CollateralLinkAllocator().allocate_links(exposures, collateral, links, config)
        assert result.collateral is not None
        alloc = _allocated(result.collateral)

        # Assert — L1 capped at its 100 demand, not 200.
        assert alloc.get("L1") == pytest.approx(100.0)
        assert sum(alloc.values()) == pytest.approx(100.0)
