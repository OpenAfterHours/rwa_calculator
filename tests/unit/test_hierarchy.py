"""Unit tests for the hierarchy resolver module.

Tests cover:
- Parent and ultimate parent lookup building
- Rating inheritance from parents
- Exposure unification (loans + contingents)
- Lending group exposure aggregation
- Full hierarchy resolution pipeline
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    CounterpartyLookup,
    RawDataBundle,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.hierarchy import (
    HierarchyError,
    HierarchyResolver,
    create_hierarchy_resolver,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def resolver() -> HierarchyResolver:
    """Return a HierarchyResolver instance."""
    return HierarchyResolver()


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Return a CRR configuration."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def fixtures_path() -> Path:
    """Return path to test fixtures directory."""
    return Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def simple_counterparties() -> pl.LazyFrame:
    """Simple counterparties LazyFrame for testing."""
    return pl.DataFrame({
        "counterparty_reference": ["CP001", "CP002", "CP003", "CP004"],
        "counterparty_name": ["Parent Corp", "Child Corp 1", "Child Corp 2", "Standalone"],
        "entity_type": ["corporate", "corporate", "corporate", "corporate"],
        "country_code": ["GB", "GB", "GB", "GB"],
        "annual_revenue": [100000000.0, 20000000.0, 30000000.0, 5000000.0],
        "total_assets": [500000000.0, 100000000.0, 150000000.0, 25000000.0],
        "default_status": [False, False, False, False],
        "sector_code": ["MANU", "MANU", "MANU", "SERV"],
        "is_financial_institution": [False, False, False, False],
        "is_regulated": [False, False, False, False],
        "is_pse": [False, False, False, False],
        "is_mdb": [False, False, False, False],
        "is_international_org": [False, False, False, False],
        "is_central_counterparty": [False, False, False, False],
        "is_regional_govt_local_auth": [False, False, False, False],
    }).lazy()


@pytest.fixture
def simple_org_mappings() -> pl.LazyFrame:
    """Simple org mappings for single-level hierarchy."""
    return pl.DataFrame({
        "parent_counterparty_reference": ["CP001", "CP001"],
        "child_counterparty_reference": ["CP002", "CP003"],
    }).lazy()


@pytest.fixture
def multi_level_org_mappings() -> pl.LazyFrame:
    """Multi-level org hierarchy for testing transitive resolution."""
    return pl.DataFrame({
        "parent_counterparty_reference": ["ULTIMATE", "HOLDING", "HOLDING"],
        "child_counterparty_reference": ["HOLDING", "OPSUB1", "OPSUB2"],
    }).lazy()


@pytest.fixture
def simple_ratings() -> pl.LazyFrame:
    """Simple ratings - only parent has rating."""
    return pl.DataFrame({
        "rating_reference": ["RAT001"],
        "counterparty_reference": ["CP001"],
        "rating_type": ["external"],
        "rating_agency": ["MOODYS"],
        "rating_value": ["A2"],
        "cqs": [2],
        "pd": [0.001],
        "rating_date": [date(2024, 6, 1)],
        "is_solicited": [True],
    }).lazy()


@pytest.fixture
def simple_loans() -> pl.LazyFrame:
    """Simple loans for testing."""
    return pl.DataFrame({
        "loan_reference": ["LOAN001", "LOAN002", "LOAN003"],
        "product_type": ["TERM_LOAN", "TERM_LOAN", "TERM_LOAN"],
        "book_code": ["CORP", "CORP", "CORP"],
        "counterparty_reference": ["CP002", "CP003", "CP004"],
        "value_date": [date(2023, 1, 1)] * 3,
        "maturity_date": [date(2026, 1, 1)] * 3,
        "currency": ["GBP", "GBP", "GBP"],
        "drawn_amount": [1000000.0, 2000000.0, 500000.0],
        "lgd": [0.45, 0.45, 0.45],
        "beel": [0.01, 0.01, 0.01],
        "seniority": ["senior", "senior", "senior"],
    }).lazy()


@pytest.fixture
def simple_contingents() -> pl.LazyFrame:
    """Simple contingents for testing."""
    return pl.DataFrame({
        "contingent_reference": ["CONT001", "CONT002"],
        "contract_type": ["GUARANTEE", "LC"],
        "product_type": ["FINANCIAL_GUARANTEE", "LETTER_OF_CREDIT"],
        "book_code": ["CORP", "CORP"],
        "counterparty_reference": ["CP002", "CP004"],
        "value_date": [date(2023, 1, 1)] * 2,
        "maturity_date": [date(2025, 1, 1)] * 2,
        "currency": ["GBP", "GBP"],
        "nominal_amount": [250000.0, 100000.0],
        "lgd": [0.45, 0.45],
        "beel": [0.01, 0.01],
        "ccf_category": ["MEDIUM_RISK", "MEDIUM_RISK"],
        "seniority": ["senior", "senior"],
    }).lazy()


@pytest.fixture
def simple_facility_mappings() -> pl.LazyFrame:
    """Simple facility mappings."""
    return pl.DataFrame({
        "parent_facility_reference": ["FAC001", "FAC001", "FAC002"],
        "child_reference": ["LOAN001", "CONT001", "LOAN002"],
        "child_type": ["loan", "contingent", "loan"],
    }).lazy()


@pytest.fixture
def lending_group_mappings() -> pl.LazyFrame:
    """Lending group mappings for retail threshold testing."""
    return pl.DataFrame({
        "parent_counterparty_reference": ["LG_ANCHOR", "LG_ANCHOR"],
        "child_counterparty_reference": ["LG_MEMBER1", "LG_MEMBER2"],
    }).lazy()


@pytest.fixture
def lending_group_counterparties() -> pl.LazyFrame:
    """Counterparties for lending group testing."""
    return pl.DataFrame({
        "counterparty_reference": ["LG_ANCHOR", "LG_MEMBER1", "LG_MEMBER2", "STANDALONE"],
        "counterparty_name": ["Anchor Person", "Member 1", "Member 2", "Standalone"],
        "entity_type": ["individual", "individual", "corporate", "individual"],
        "country_code": ["GB", "GB", "GB", "GB"],
        "annual_revenue": [0.0, 0.0, 500000.0, 0.0],
        "total_assets": [0.0, 0.0, 1000000.0, 0.0],
        "default_status": [False, False, False, False],
        "sector_code": ["RETAIL", "RETAIL", "RETAIL", "RETAIL"],
        "is_financial_institution": [False, False, False, False],
        "is_regulated": [False, False, False, False],
        "is_pse": [False, False, False, False],
        "is_mdb": [False, False, False, False],
        "is_international_org": [False, False, False, False],
        "is_central_counterparty": [False, False, False, False],
        "is_regional_govt_local_auth": [False, False, False, False],
    }).lazy()


@pytest.fixture
def lending_group_loans() -> pl.LazyFrame:
    """Loans for lending group testing."""
    return pl.DataFrame({
        "loan_reference": ["LG_LOAN1", "LG_LOAN2", "LG_LOAN3", "STANDALONE_LOAN"],
        "product_type": ["MORTGAGE", "PERSONAL", "BUSINESS", "PERSONAL"],
        "book_code": ["RETAIL", "RETAIL", "RETAIL", "RETAIL"],
        "counterparty_reference": ["LG_ANCHOR", "LG_MEMBER1", "LG_MEMBER2", "STANDALONE"],
        "value_date": [date(2023, 1, 1)] * 4,
        "maturity_date": [date(2028, 1, 1)] * 4,
        "currency": ["GBP", "GBP", "GBP", "GBP"],
        "drawn_amount": [300000.0, 200000.0, 400000.0, 50000.0],
        "lgd": [0.15, 0.45, 0.45, 0.45],
        "beel": [0.01, 0.01, 0.01, 0.01],
        "seniority": ["senior", "senior", "senior", "senior"],
    }).lazy()


@pytest.fixture
def empty_lazyframe() -> pl.LazyFrame:
    """Empty LazyFrame for testing edge cases."""
    return pl.LazyFrame()


@pytest.fixture
def simple_raw_data_bundle(
    simple_counterparties: pl.LazyFrame,
    simple_org_mappings: pl.LazyFrame,
    simple_ratings: pl.LazyFrame,
    simple_loans: pl.LazyFrame,
    simple_contingents: pl.LazyFrame,
    simple_facility_mappings: pl.LazyFrame,
) -> RawDataBundle:
    """Simple raw data bundle for testing."""
    return RawDataBundle(
        facilities=pl.LazyFrame(),
        loans=simple_loans,
        contingents=simple_contingents,
        counterparties=simple_counterparties,
        collateral=pl.LazyFrame(),
        guarantees=pl.LazyFrame(),
        provisions=pl.LazyFrame(),
        ratings=simple_ratings,
        facility_mappings=simple_facility_mappings,
        org_mappings=simple_org_mappings,
        lending_mappings=pl.LazyFrame(schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }),
    )


# =============================================================================
# Ultimate Parent Lookup Tests (LazyFrame-based)
# =============================================================================


class TestBuildUltimateParentLazy:
    """Tests for _build_ultimate_parent_lazy method."""

    def test_single_level_hierarchy(
        self,
        resolver: HierarchyResolver,
        simple_org_mappings: pl.LazyFrame,
    ) -> None:
        """Single-level hierarchy should have correct ultimate parent."""
        ultimate_parents = resolver._build_ultimate_parent_lazy(simple_org_mappings)
        df = ultimate_parents.collect()

        # CP002 -> CP001, CP003 -> CP001
        cp002 = df.filter(pl.col("counterparty_reference") == "CP002")
        cp003 = df.filter(pl.col("counterparty_reference") == "CP003")

        assert cp002["ultimate_parent_reference"][0] == "CP001"
        assert cp003["ultimate_parent_reference"][0] == "CP001"

    def test_multi_level_hierarchy(
        self,
        resolver: HierarchyResolver,
        multi_level_org_mappings: pl.LazyFrame,
    ) -> None:
        """Multi-level hierarchy should resolve ultimate parent correctly."""
        ultimate_parents = resolver._build_ultimate_parent_lazy(multi_level_org_mappings)
        df = ultimate_parents.collect()

        # All should ultimately resolve to "ULTIMATE"
        holding = df.filter(pl.col("counterparty_reference") == "HOLDING")
        opsub1 = df.filter(pl.col("counterparty_reference") == "OPSUB1")
        opsub2 = df.filter(pl.col("counterparty_reference") == "OPSUB2")

        assert holding["ultimate_parent_reference"][0] == "ULTIMATE"
        assert opsub1["ultimate_parent_reference"][0] == "ULTIMATE"
        assert opsub2["ultimate_parent_reference"][0] == "ULTIMATE"

        # Verify hierarchy depths
        assert holding["hierarchy_depth"][0] == 1
        assert opsub1["hierarchy_depth"][0] == 2
        assert opsub2["hierarchy_depth"][0] == 2

    def test_empty_mappings(self, resolver: HierarchyResolver) -> None:
        """Empty mappings should return empty LazyFrame."""
        empty_mappings = pl.LazyFrame(schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        })

        ultimate_parents = resolver._build_ultimate_parent_lazy(empty_mappings)
        df = ultimate_parents.collect()

        assert df.height == 0


# =============================================================================
# Rating Inheritance Tests (LazyFrame-based)
# =============================================================================


class TestBuildRatingInheritanceLazy:
    """Tests for _build_rating_inheritance_lazy method."""

    def test_entity_with_own_rating(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
    ) -> None:
        """Entity with own rating should not inherit."""
        ultimate_parents = resolver._build_ultimate_parent_lazy(simple_org_mappings)

        rating_inheritance = resolver._build_rating_inheritance_lazy(
            simple_counterparties,
            simple_ratings,
            ultimate_parents,
        )
        df = rating_inheritance.collect()

        # CP001 has own rating
        cp001 = df.filter(pl.col("counterparty_reference") == "CP001")
        assert cp001["cqs"][0] == 2
        assert cp001["inherited"][0] is False
        assert cp001["source_counterparty"][0] == "CP001"
        assert cp001["inheritance_reason"][0] == "own_rating"

    def test_entity_inherits_from_parent(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
    ) -> None:
        """Unrated child should inherit parent rating."""
        ultimate_parents = resolver._build_ultimate_parent_lazy(simple_org_mappings)

        rating_inheritance = resolver._build_rating_inheritance_lazy(
            simple_counterparties,
            simple_ratings,
            ultimate_parents,
        )
        df = rating_inheritance.collect()

        # CP002 inherits from CP001
        cp002 = df.filter(pl.col("counterparty_reference") == "CP002")
        assert cp002["cqs"][0] == 2
        assert cp002["inherited"][0] is True
        assert cp002["source_counterparty"][0] == "CP001"
        assert cp002["inheritance_reason"][0] == "parent_rating"

    def test_standalone_unrated_entity(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Standalone unrated entity should be marked as unrated."""
        # Empty org mappings - no hierarchy
        empty_mappings = pl.LazyFrame(schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        })
        ultimate_parents = resolver._build_ultimate_parent_lazy(empty_mappings)

        rating_inheritance = resolver._build_rating_inheritance_lazy(
            simple_counterparties,
            simple_ratings,
            ultimate_parents,
        )
        df = rating_inheritance.collect()

        # CP004 is standalone and unrated
        cp004 = df.filter(pl.col("counterparty_reference") == "CP004")
        assert cp004["cqs"][0] is None
        assert cp004["inherited"][0] is False
        assert cp004["inheritance_reason"][0] == "unrated"


# =============================================================================
# Exposure Unification Tests
# =============================================================================


class TestUnifyExposures:
    """Tests for _unify_exposures method."""

    def test_loans_and_contingents_combined(
        self,
        resolver: HierarchyResolver,
        simple_loans: pl.LazyFrame,
        simple_contingents: pl.LazyFrame,
        simple_facility_mappings: pl.LazyFrame,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Loans and contingents should be unified correctly."""
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        exposures, errors = resolver._unify_exposures(
            simple_loans,
            simple_contingents,
            simple_facility_mappings,
            counterparty_lookup,
        )

        df = exposures.collect()

        # Should have 3 loans + 2 contingents = 5 exposures
        assert len(df) == 5

        # Check exposure types
        loan_count = df.filter(pl.col("exposure_type") == "loan").height
        contingent_count = df.filter(pl.col("exposure_type") == "contingent").height
        assert loan_count == 3
        assert contingent_count == 2

    def test_exposure_references_preserved(
        self,
        resolver: HierarchyResolver,
        simple_loans: pl.LazyFrame,
        simple_contingents: pl.LazyFrame,
        simple_facility_mappings: pl.LazyFrame,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Exposure references should be preserved during unification."""
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        exposures, _ = resolver._unify_exposures(
            simple_loans,
            simple_contingents,
            simple_facility_mappings,
            counterparty_lookup,
        )

        df = exposures.collect()
        refs = df["exposure_reference"].to_list()

        assert "LOAN001" in refs
        assert "LOAN002" in refs
        assert "LOAN003" in refs
        assert "CONT001" in refs
        assert "CONT002" in refs

    def test_facility_hierarchy_added(
        self,
        resolver: HierarchyResolver,
        simple_loans: pl.LazyFrame,
        simple_contingents: pl.LazyFrame,
        simple_facility_mappings: pl.LazyFrame,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Facility hierarchy info should be added to exposures."""
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        exposures, _ = resolver._unify_exposures(
            simple_loans,
            simple_contingents,
            simple_facility_mappings,
            counterparty_lookup,
        )

        df = exposures.collect()

        # LOAN001 is under FAC001
        loan001 = df.filter(pl.col("exposure_reference") == "LOAN001")
        assert loan001["exposure_has_parent"][0] is True
        assert loan001["parent_facility_reference"][0] == "FAC001"


# =============================================================================
# Lending Group Aggregation Tests
# =============================================================================


class TestLendingGroupAggregation:
    """Tests for lending group exposure aggregation."""

    def test_lending_group_totals_calculated(
        self,
        resolver: HierarchyResolver,
        lending_group_counterparties: pl.LazyFrame,
        lending_group_loans: pl.LazyFrame,
        lending_group_mappings: pl.LazyFrame,
    ) -> None:
        """Lending group totals should be correctly calculated."""
        # Build enriched counterparties with required columns
        enriched_counterparties = lending_group_counterparties.with_columns([
            pl.lit(False).alias("counterparty_has_parent"),
            pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"),
            pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"),
            pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"),
            pl.lit(None).cast(pl.Int8).alias("cqs"),
            pl.lit(None).cast(pl.Float64).alias("pd"),
            pl.lit(None).cast(pl.String).alias("rating_value"),
            pl.lit(None).cast(pl.String).alias("rating_agency"),
            pl.lit(False).alias("rating_inherited"),
            pl.lit(None).cast(pl.String).alias("rating_source_counterparty"),
            pl.lit("unrated").alias("rating_inheritance_reason"),
        ])

        counterparty_lookup = CounterpartyLookup(
            counterparties=enriched_counterparties,
            parent_mappings=pl.LazyFrame(schema={
                "child_counterparty_reference": pl.String,
                "parent_counterparty_reference": pl.String,
            }),
            ultimate_parent_mappings=pl.LazyFrame(schema={
                "counterparty_reference": pl.String,
                "ultimate_parent_reference": pl.String,
                "hierarchy_depth": pl.Int32,
            }),
            rating_inheritance=pl.LazyFrame(schema={
                "counterparty_reference": pl.String,
                "cqs": pl.Int8,
                "pd": pl.Float64,
                "rating_value": pl.String,
                "inherited": pl.Boolean,
                "source_counterparty": pl.String,
                "inheritance_reason": pl.String,
            }),
        )

        exposures, _ = resolver._unify_exposures(
            lending_group_loans,
            pl.LazyFrame(schema={
                "contingent_reference": pl.String,
                "contract_type": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "counterparty_reference": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "currency": pl.String,
                "nominal_amount": pl.Float64,
                "lgd": pl.Float64,
                "beel": pl.Float64,
                "ccf_category": pl.String,
                "seniority": pl.String,
            }),
            pl.LazyFrame(schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }),
            counterparty_lookup,
        )

        lending_group_totals, errors = resolver._calculate_lending_group_totals(
            exposures,
            lending_group_mappings,
        )

        df = lending_group_totals.collect()

        # Should have one lending group
        assert len(df) == 1
        assert df["lending_group_reference"][0] == "LG_ANCHOR"

        # Total should be sum of anchor + members (300k + 200k + 400k = 900k)
        assert df["total_drawn"][0] == 900000.0

    def test_standalone_not_in_lending_group(
        self,
        resolver: HierarchyResolver,
        lending_group_counterparties: pl.LazyFrame,
        lending_group_loans: pl.LazyFrame,
        lending_group_mappings: pl.LazyFrame,
    ) -> None:
        """Standalone counterparty should not be in any lending group."""
        # Build enriched counterparties with required columns
        enriched_counterparties = lending_group_counterparties.with_columns([
            pl.lit(False).alias("counterparty_has_parent"),
            pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"),
            pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"),
            pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"),
            pl.lit(None).cast(pl.Int8).alias("cqs"),
            pl.lit(None).cast(pl.Float64).alias("pd"),
            pl.lit(None).cast(pl.String).alias("rating_value"),
            pl.lit(None).cast(pl.String).alias("rating_agency"),
            pl.lit(False).alias("rating_inherited"),
            pl.lit(None).cast(pl.String).alias("rating_source_counterparty"),
            pl.lit("unrated").alias("rating_inheritance_reason"),
        ])

        counterparty_lookup = CounterpartyLookup(
            counterparties=enriched_counterparties,
            parent_mappings=pl.LazyFrame(schema={
                "child_counterparty_reference": pl.String,
                "parent_counterparty_reference": pl.String,
            }),
            ultimate_parent_mappings=pl.LazyFrame(schema={
                "counterparty_reference": pl.String,
                "ultimate_parent_reference": pl.String,
                "hierarchy_depth": pl.Int32,
            }),
            rating_inheritance=pl.LazyFrame(schema={
                "counterparty_reference": pl.String,
                "cqs": pl.Int8,
                "pd": pl.Float64,
                "rating_value": pl.String,
                "inherited": pl.Boolean,
                "source_counterparty": pl.String,
                "inheritance_reason": pl.String,
            }),
        )

        exposures, _ = resolver._unify_exposures(
            lending_group_loans,
            pl.LazyFrame(schema={
                "contingent_reference": pl.String,
                "contract_type": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "counterparty_reference": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "currency": pl.String,
                "nominal_amount": pl.Float64,
                "lgd": pl.Float64,
                "beel": pl.Float64,
                "ccf_category": pl.String,
                "seniority": pl.String,
            }),
            pl.LazyFrame(schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }),
            counterparty_lookup,
        )

        # Add lending group totals
        lending_group_totals, _ = resolver._calculate_lending_group_totals(
            exposures,
            lending_group_mappings,
        )

        enriched_exposures = resolver._add_lending_group_totals_to_exposures(
            exposures,
            lending_group_mappings,
            lending_group_totals,
        )

        df = enriched_exposures.collect()

        # Standalone loan should have 0 lending group total
        standalone = df.filter(pl.col("exposure_reference") == "STANDALONE_LOAN")
        assert standalone["lending_group_total_exposure"][0] == 0.0


# =============================================================================
# Full Resolution Tests
# =============================================================================


class TestFullResolution:
    """Tests for the complete resolve() method."""

    def test_resolve_returns_correct_bundle_type(
        self,
        resolver: HierarchyResolver,
        simple_raw_data_bundle: RawDataBundle,
        crr_config: CalculationConfig,
    ) -> None:
        """resolve() should return a ResolvedHierarchyBundle."""
        result = resolver.resolve(simple_raw_data_bundle, crr_config)
        assert isinstance(result, ResolvedHierarchyBundle)

    def test_resolve_populates_all_fields(
        self,
        resolver: HierarchyResolver,
        simple_raw_data_bundle: RawDataBundle,
        crr_config: CalculationConfig,
    ) -> None:
        """resolve() should populate all required fields."""
        result = resolver.resolve(simple_raw_data_bundle, crr_config)

        assert result.exposures is not None
        assert result.counterparty_lookup is not None
        assert result.collateral is not None
        assert result.guarantees is not None
        assert result.provisions is not None
        assert result.lending_group_totals is not None
        assert isinstance(result.hierarchy_errors, list)

    def test_resolve_with_real_fixtures(
        self,
        resolver: HierarchyResolver,
        fixtures_path: Path,
        crr_config: CalculationConfig,
    ) -> None:
        """resolve() should work with actual test fixtures."""
        if not fixtures_path.exists():
            pytest.skip("Fixtures path does not exist")

        from rwa_calc.engine.loader import ParquetLoader

        loader = ParquetLoader(fixtures_path)
        raw_data = loader.load()

        result = resolver.resolve(raw_data, crr_config)

        # Verify we can collect results
        exposures_df = result.exposures.collect()
        assert len(exposures_df) > 0

        # Verify counterparty lookup is populated
        assert isinstance(result.counterparty_lookup, CounterpartyLookup)


# =============================================================================
# create_hierarchy_resolver Tests
# =============================================================================


class TestCreateHierarchyResolver:
    """Tests for the factory function."""

    def test_creates_instance(self) -> None:
        """Factory should create a HierarchyResolver instance."""
        resolver = create_hierarchy_resolver()
        assert isinstance(resolver, HierarchyResolver)


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_empty_loans_and_contingents(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Should handle empty loans and contingents."""
        empty_bundle = RawDataBundle(
            facilities=pl.LazyFrame(),
            loans=pl.LazyFrame(schema={
                "loan_reference": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "counterparty_reference": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "currency": pl.String,
                "drawn_amount": pl.Float64,
                "lgd": pl.Float64,
                "beel": pl.Float64,
                "seniority": pl.String,
            }),
            contingents=pl.LazyFrame(schema={
                "contingent_reference": pl.String,
                "contract_type": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "counterparty_reference": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "currency": pl.String,
                "nominal_amount": pl.Float64,
                "lgd": pl.Float64,
                "beel": pl.Float64,
                "ccf_category": pl.String,
                "seniority": pl.String,
            }),
            counterparties=pl.LazyFrame(schema={
                "counterparty_reference": pl.String,
            }),
            collateral=pl.LazyFrame(),
            guarantees=pl.LazyFrame(),
            provisions=pl.LazyFrame(),
            ratings=pl.LazyFrame(schema={
                "rating_reference": pl.String,
                "counterparty_reference": pl.String,
                "rating_type": pl.String,
                "rating_agency": pl.String,
                "rating_value": pl.String,
                "cqs": pl.Int8,
                "pd": pl.Float64,
                "rating_date": pl.Date,
                "is_solicited": pl.Boolean,
            }),
            facility_mappings=pl.LazyFrame(schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }),
            org_mappings=pl.LazyFrame(schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }),
            lending_mappings=pl.LazyFrame(schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }),
        )

        result = resolver.resolve(empty_bundle, crr_config)

        # Should not raise and should return valid bundle
        assert isinstance(result, ResolvedHierarchyBundle)
        exposures_df = result.exposures.collect()
        assert len(exposures_df) == 0

    def test_no_org_hierarchy(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_loans: pl.LazyFrame,
        simple_contingents: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Should handle case with no org hierarchy."""
        bundle = RawDataBundle(
            facilities=pl.LazyFrame(),
            loans=simple_loans,
            contingents=simple_contingents,
            counterparties=simple_counterparties,
            collateral=pl.LazyFrame(),
            guarantees=pl.LazyFrame(),
            provisions=pl.LazyFrame(),
            ratings=simple_ratings,
            facility_mappings=pl.LazyFrame(schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }),
            org_mappings=pl.LazyFrame(schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }),
            lending_mappings=pl.LazyFrame(schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }),
        )

        result = resolver.resolve(bundle, crr_config)

        # Should work without org hierarchy
        assert isinstance(result, ResolvedHierarchyBundle)
        assert result.counterparty_lookup.parent_mappings.collect().height == 0
