"""Unit tests for the Hierarchy Polars namespace.

Tests cover:
- Namespace registration and availability
- Ultimate parent resolution
- Rating inheritance
- Lending group calculations
- Collateral LTV addition
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.engine import HierarchyLazyFrame  # noqa: F401

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def counterparties() -> pl.LazyFrame:
    """Return basic counterparty data."""
    return pl.LazyFrame(
        {
            "counterparty_reference": ["CP001", "CP002", "CP003", "CP004"],
        }
    )


@pytest.fixture
def org_mappings() -> pl.LazyFrame:
    """Return organization hierarchy mappings."""
    return pl.LazyFrame(
        {
            "child_counterparty_reference": ["CP002", "CP003", "CP004"],
            "parent_counterparty_reference": ["CP001", "CP001", "CP002"],
        }
    )


@pytest.fixture
def ratings() -> pl.LazyFrame:
    """Return rating data."""
    return pl.LazyFrame(
        {
            "counterparty_reference": ["CP001", "CP003"],
            "cqs": [1, 3],
            "pd": [0.001, 0.01],
            "rating_value": ["AAA", "BBB"],
        }
    )


@pytest.fixture
def exposures() -> pl.LazyFrame:
    """Return exposure data."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP001", "EXP002"],
            "counterparty_reference": ["CP001", "CP002"],
            "drawn_amount": [1_000_000.0, 500_000.0],
        }
    )


@pytest.fixture
def lending_mappings() -> pl.LazyFrame:
    """Return lending group mappings."""
    return pl.LazyFrame(
        {
            "parent_counterparty_reference": ["CP001"],
            "child_counterparty_reference": ["CP002"],
        }
    )


@pytest.fixture
def collateral() -> pl.LazyFrame:
    """Return collateral with LTV."""
    return pl.LazyFrame(
        {
            "collateral_reference": ["COLL001", "COLL002"],
            "beneficiary_reference": ["EXP001", "EXP002"],
            "property_ltv": [0.65, 0.85],
        }
    )


# =============================================================================
# Namespace Registration Tests
# =============================================================================


class TestHierarchyNamespaceRegistration:
    """Tests for namespace registration and availability."""

    def test_lazyframe_namespace_registered(self, counterparties: pl.LazyFrame) -> None:
        """LazyFrame should have .hierarchy namespace available."""
        assert hasattr(counterparties, "hierarchy")

    def test_namespace_methods_available(self, counterparties: pl.LazyFrame) -> None:
        """Namespace should have expected methods."""
        hierarchy = counterparties.hierarchy
        expected_methods = [
            "resolve_ultimate_parent",
            "calculate_hierarchy_depth",
            "inherit_ratings",
            "coalesce_ratings",
            "calculate_lending_group_totals",
            "add_lending_group_reference",
            "add_collateral_ltv",
        ]
        for method in expected_methods:
            assert hasattr(hierarchy, method), f"Missing method: {method}"


# =============================================================================
# Ultimate Parent Resolution Tests
# =============================================================================


class TestResolveUltimateParent:
    """Tests for ultimate parent resolution."""

    def test_resolves_direct_parent(
        self,
        counterparties: pl.LazyFrame,
        org_mappings: pl.LazyFrame,
    ) -> None:
        """Should resolve direct parent relationships."""
        result = counterparties.hierarchy.resolve_ultimate_parent(org_mappings).collect()

        # CP002's ultimate parent should be CP001
        cp002 = result.filter(pl.col("counterparty_reference") == "CP002")
        assert cp002["ultimate_parent_reference"][0] == "CP001"

    def test_resolves_transitive_parent(
        self,
        counterparties: pl.LazyFrame,
        org_mappings: pl.LazyFrame,
    ) -> None:
        """Should resolve transitive parent relationships."""
        result = counterparties.hierarchy.resolve_ultimate_parent(org_mappings).collect()

        # CP004's ultimate parent should be CP001 (via CP002)
        cp004 = result.filter(pl.col("counterparty_reference") == "CP004")
        assert cp004["ultimate_parent_reference"][0] == "CP001"

    def test_root_entity_is_own_parent(
        self,
        counterparties: pl.LazyFrame,
        org_mappings: pl.LazyFrame,
    ) -> None:
        """Root entity should be its own ultimate parent."""
        result = counterparties.hierarchy.resolve_ultimate_parent(org_mappings).collect()

        # CP001 is the root, should be its own parent
        cp001 = result.filter(pl.col("counterparty_reference") == "CP001")
        assert cp001["ultimate_parent_reference"][0] == "CP001"

    def test_hierarchy_depth_calculated(
        self,
        counterparties: pl.LazyFrame,
        org_mappings: pl.LazyFrame,
    ) -> None:
        """Hierarchy depth should be calculated."""
        result = counterparties.hierarchy.resolve_ultimate_parent(org_mappings).collect()

        assert "hierarchy_depth" in result.columns


# =============================================================================
# Rating Inheritance Tests
# =============================================================================


class TestInheritRatings:
    """Tests for rating inheritance."""

    def test_own_rating_preserved(
        self,
        counterparties: pl.LazyFrame,
        ratings: pl.LazyFrame,
    ) -> None:
        """Own ratings should be preserved."""
        result = counterparties.hierarchy.inherit_ratings(ratings).collect()

        # CP001 has own rating
        cp001 = result.filter(pl.col("counterparty_reference") == "CP001")
        assert cp001["cqs"][0] == 1

    def test_unrated_entity_has_null(
        self,
        counterparties: pl.LazyFrame,
        ratings: pl.LazyFrame,
    ) -> None:
        """Unrated entity without parent should have null rating."""
        result = counterparties.hierarchy.inherit_ratings(ratings).collect()

        # CP002 has no own rating and no parent inheritance without ultimate_parents
        cp002 = result.filter(pl.col("counterparty_reference") == "CP002")
        assert cp002["cqs"][0] is None

    def test_rating_inherited_from_parent(
        self,
        counterparties: pl.LazyFrame,
        org_mappings: pl.LazyFrame,
        ratings: pl.LazyFrame,
    ) -> None:
        """Unrated entity should inherit from ultimate parent."""
        # First resolve parents
        with_parents = counterparties.hierarchy.resolve_ultimate_parent(org_mappings)
        ultimate_parents = with_parents.select(
            [
                pl.col("counterparty_reference"),
                pl.col("ultimate_parent_reference"),
            ]
        )

        result = counterparties.hierarchy.inherit_ratings(
            ratings,
            ultimate_parents=ultimate_parents,
        ).collect()

        # CP002 has no own rating but should inherit from CP001
        cp002 = result.filter(pl.col("counterparty_reference") == "CP002")
        assert cp002["cqs"][0] == 1  # Inherited from CP001


# =============================================================================
# Lending Group Tests
# =============================================================================


class TestLendingGroupCalculations:
    """Tests for lending group calculations."""

    def test_calculate_lending_group_totals(
        self,
        exposures: pl.LazyFrame,
        lending_mappings: pl.LazyFrame,
    ) -> None:
        """Should calculate lending group totals."""
        result = exposures.hierarchy.calculate_lending_group_totals(lending_mappings).collect()

        assert "total_exposure" in result.columns
        assert "exposure_count" in result.columns

    def test_add_lending_group_reference(
        self,
        exposures: pl.LazyFrame,
        lending_mappings: pl.LazyFrame,
    ) -> None:
        """Should add lending group reference to exposures."""
        result = exposures.hierarchy.add_lending_group_reference(lending_mappings).collect()

        assert "lending_group_reference" in result.columns


# =============================================================================
# Collateral LTV Tests
# =============================================================================


class TestAddCollateralLTV:
    """Tests for adding collateral LTV."""

    def test_adds_ltv_column(
        self,
        collateral: pl.LazyFrame,
    ) -> None:
        """Should add LTV from collateral."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
                "counterparty_reference": ["CP001", "CP002"],
            }
        )

        result = exposures.hierarchy.add_collateral_ltv(collateral).collect()

        assert "ltv" in result.columns

    def test_ltv_values_correct(
        self,
        collateral: pl.LazyFrame,
    ) -> None:
        """LTV values should match collateral."""
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["EXP001", "EXP002"],
            }
        )

        result = exposures.hierarchy.add_collateral_ltv(collateral).collect()

        exp001 = result.filter(pl.col("exposure_reference") == "EXP001")
        assert exp001["ltv"][0] == pytest.approx(0.65)
