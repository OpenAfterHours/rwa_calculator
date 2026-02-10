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
        "is_managed_as_retail": [False, False, False, False],
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
        "risk_type": ["FR", "FR", "FR"],  # Full risk for drawn loans
        "ccf_modelled": [None, None, None],  # No modelled CCF
        "is_short_term_trade_lc": [None, None, None],  # N/A for loans
    }).lazy()


@pytest.fixture
def simple_contingents() -> pl.LazyFrame:
    """Simple contingents for testing."""
    return pl.DataFrame({
        "contingent_reference": ["CONT001", "CONT002"],
        "product_type": ["FINANCIAL_GUARANTEE", "LETTER_OF_CREDIT"],
        "book_code": ["CORP", "CORP"],
        "counterparty_reference": ["CP002", "CP004"],
        "value_date": [date(2023, 1, 1)] * 2,
        "maturity_date": [date(2025, 1, 1)] * 2,
        "currency": ["GBP", "GBP"],
        "nominal_amount": [250000.0, 100000.0],
        "lgd": [0.45, 0.45],
        "beel": [0.01, 0.01],
        "seniority": ["senior", "senior"],
        "risk_type": ["MR", "MR"],  # Medium risk
        "ccf_modelled": [None, None],  # No modelled CCF
        "is_short_term_trade_lc": [False, False],  # Not trade LCs
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
        "is_managed_as_retail": [False, False, False, False],
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
        "risk_type": ["FR", "FR", "FR", "FR"],  # Full risk for drawn loans
        "ccf_modelled": [None, None, None, None],  # No modelled CCF
        "is_short_term_trade_lc": [None, None, None, None],  # N/A for loans
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
            None,  # No facilities for this test
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
            None,  # No facilities for this test
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
            None,  # No facilities for this test
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
                "product_type": pl.String,
                "book_code": pl.String,
                "counterparty_reference": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "currency": pl.String,
                "nominal_amount": pl.Float64,
                "lgd": pl.Float64,
                "beel": pl.Float64,
                "seniority": pl.String,
                "risk_type": pl.String,
                "ccf_modelled": pl.Float64,
                "is_short_term_trade_lc": pl.Boolean,
            }),
            None,  # No facilities for this test
            pl.LazyFrame(schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }),
            counterparty_lookup,
        )

        # Calculate residential property coverage (empty for this test)
        residential_coverage = resolver._calculate_residential_property_coverage(
            exposures,
            None,  # No collateral
        )

        lending_group_totals, errors = resolver._calculate_lending_group_totals(
            exposures,
            lending_group_mappings,
            residential_coverage,
        )

        df = lending_group_totals.collect()

        # Should have one lending group
        assert len(df) == 1
        assert df["lending_group_reference"][0] == "LG_ANCHOR"

        # Total should be sum of anchor + members (300k + 200k + 400k = 900k)
        assert df["total_drawn"][0] == 900000.0
        # Adjusted exposure should equal total (no residential collateral)
        assert df["adjusted_exposure"][0] == 900000.0

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
                "product_type": pl.String,
                "book_code": pl.String,
                "counterparty_reference": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "currency": pl.String,
                "nominal_amount": pl.Float64,
                "lgd": pl.Float64,
                "beel": pl.Float64,
                "seniority": pl.String,
                "risk_type": pl.String,
                "ccf_modelled": pl.Float64,
                "is_short_term_trade_lc": pl.Boolean,
            }),
            None,  # No facilities for this test
            pl.LazyFrame(schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }),
            counterparty_lookup,
        )

        # Calculate residential property coverage (empty for this test)
        residential_coverage = resolver._calculate_residential_property_coverage(
            exposures,
            None,  # No collateral
        )

        # Add lending group totals
        lending_group_totals, _ = resolver._calculate_lending_group_totals(
            exposures,
            lending_group_mappings,
            residential_coverage,
        )

        enriched_exposures = resolver._add_lending_group_totals_to_exposures(
            exposures,
            lending_group_mappings,
            lending_group_totals,
            residential_coverage,
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
                "risk_type": pl.String,
                "ccf_modelled": pl.Float64,
                "is_short_term_trade_lc": pl.Boolean,
            }),
            contingents=pl.LazyFrame(schema={
                "contingent_reference": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "counterparty_reference": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "currency": pl.String,
                "nominal_amount": pl.Float64,
                "lgd": pl.Float64,
                "beel": pl.Float64,
                "seniority": pl.String,
                "risk_type": pl.String,
                "ccf_modelled": pl.Float64,
                "is_short_term_trade_lc": pl.Boolean,
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


# =============================================================================
# Facility Undrawn Calculation Tests
# =============================================================================


class TestFacilityUndrawnCalculation:
    """Tests for _calculate_facility_undrawn method."""

    @pytest.fixture
    def facilities_with_undrawn(self) -> pl.LazyFrame:
        """Facilities for testing undrawn calculation."""
        return pl.DataFrame({
            "facility_reference": ["FAC001", "FAC002", "FAC003", "FAC004", "FAC005"],
            "product_type": ["RCF", "TERM", "OVERDRAFT", "RCF", "RCF"],
            "book_code": ["CORP", "CORP", "CORP", "CORP", "CORP"],
            "counterparty_reference": ["CP001", "CP002", "CP003", "CP004", "CP005"],
            "value_date": [date(2023, 1, 1)] * 5,
            "maturity_date": [date(2028, 1, 1)] * 5,
            "currency": ["GBP"] * 5,
            "limit": [5000000.0, 1000000.0, 500000.0, 1000000.0, 1000000.0],
            "committed": [True, True, True, True, True],
            "lgd": [0.45] * 5,
            "beel": [0.01] * 5,
            "is_revolving": [True, False, True, True, True],
            "seniority": ["senior"] * 5,
            "risk_type": ["MR", "MR", "MR", "MR", "LR"],  # MR=50% CCF, LR=0% CCF
            "ccf_modelled": [None, None, None, 0.80, None],  # FAC004 has modelled CCF
            "is_short_term_trade_lc": [False, False, False, False, False],
        }).lazy()

    @pytest.fixture
    def loans_for_facilities(self) -> pl.LazyFrame:
        """Loans linked to facilities."""
        return pl.DataFrame({
            "loan_reference": ["LOAN001", "LOAN002", "LOAN003", "LOAN004"],
            "product_type": ["TERM_LOAN", "TERM_LOAN", "OVERDRAFT_DRAW", "TERM_LOAN"],
            "book_code": ["CORP"] * 4,
            "counterparty_reference": ["CP001", "CP001", "CP002", "CP003"],
            "value_date": [date(2023, 6, 1)] * 4,
            "maturity_date": [date(2028, 1, 1)] * 4,
            "currency": ["GBP"] * 4,
            "drawn_amount": [4000000.0, 500000.0, 1000000.0, 700000.0],
            "lgd": [0.45] * 4,
            "beel": [0.01] * 4,
            "seniority": ["senior"] * 4,
        }).lazy()

    @pytest.fixture
    def facility_loan_mappings(self) -> pl.LazyFrame:
        """Mappings between facilities and loans."""
        return pl.DataFrame({
            "parent_facility_reference": ["FAC001", "FAC001", "FAC002", "FAC003"],
            "child_reference": ["LOAN001", "LOAN002", "LOAN003", "LOAN004"],
            "child_type": ["loan", "loan", "loan", "loan"],
        }).lazy()

    def test_normal_facility_undrawn_calculation(
        self,
        resolver: HierarchyResolver,
        facilities_with_undrawn: pl.LazyFrame,
        loans_for_facilities: pl.LazyFrame,
        facility_loan_mappings: pl.LazyFrame,
    ) -> None:
        """Normal facility should have undrawn = limit - drawn."""
        # FAC001: limit=5M, drawn=4.5M (LOAN001 + LOAN002), undrawn=500k
        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities_with_undrawn,
            loans_for_facilities,
            None,
            facility_loan_mappings,
        )
        df = facility_undrawn.collect()

        fac001 = df.filter(pl.col("exposure_reference") == "FAC001_UNDRAWN")
        assert len(fac001) == 1
        assert fac001["undrawn_amount"][0] == pytest.approx(500000.0)  # 5M - 4.5M = 500k
        assert fac001["nominal_amount"][0] == pytest.approx(500000.0)
        assert fac001["exposure_type"][0] == "facility_undrawn"
        assert fac001["risk_type"][0] == "MR"

    def test_fully_drawn_facility_not_included(
        self,
        resolver: HierarchyResolver,
        facilities_with_undrawn: pl.LazyFrame,
        loans_for_facilities: pl.LazyFrame,
        facility_loan_mappings: pl.LazyFrame,
    ) -> None:
        """Fully drawn facility (undrawn=0) should not create exposure."""
        # FAC002: limit=1M, drawn=1M (LOAN003), undrawn=0
        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities_with_undrawn,
            loans_for_facilities,
            None,
            facility_loan_mappings,
        )
        df = facility_undrawn.collect()

        # FAC002 should NOT be in the output since undrawn = 0
        fac002 = df.filter(pl.col("exposure_reference") == "FAC002_UNDRAWN")
        assert len(fac002) == 0

    def test_facility_with_no_loans_100_percent_undrawn(
        self,
        resolver: HierarchyResolver,
        facilities_with_undrawn: pl.LazyFrame,
        loans_for_facilities: pl.LazyFrame,
        facility_loan_mappings: pl.LazyFrame,
    ) -> None:
        """Facility with no linked loans should be 100% undrawn."""
        # FAC004: limit=1M, no linked loans, undrawn=1M
        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities_with_undrawn,
            loans_for_facilities,
            None,
            facility_loan_mappings,
        )
        df = facility_undrawn.collect()

        fac004 = df.filter(pl.col("exposure_reference") == "FAC004_UNDRAWN")
        assert len(fac004) == 1
        assert fac004["undrawn_amount"][0] == pytest.approx(1000000.0)
        # Should inherit ccf_modelled from facility
        assert fac004["ccf_modelled"][0] == pytest.approx(0.80)

    def test_overdrawn_facility_capped_at_zero(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Overdrawn facility (drawn > limit) should have undrawn capped at 0."""
        facilities = pl.DataFrame({
            "facility_reference": ["OVERDRAWN_FAC"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [1000000.0],
            "committed": [True],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["OVERDRAWN_LOAN"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 6, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [1200000.0],  # Drawn > limit
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        mappings = pl.DataFrame({
            "parent_facility_reference": ["OVERDRAWN_FAC"],
            "child_reference": ["OVERDRAWN_LOAN"],
            "child_type": ["loan"],
        }).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, None, mappings
        )
        df = facility_undrawn.collect()

        # Should not create exposure since undrawn is capped at 0
        assert len(df) == 0

    def test_negative_drawn_amount_treated_as_zero(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Negative drawn amount should be treated as zero for undrawn calculation.

        If a loan has a negative drawn amount (e.g., credit balance), it should
        not increase the facility's undrawn headroom beyond the limit.
        Formula: undrawn = max(0, limit - max(0, drawn))
        """
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_NEG"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [1000000.0],
            "committed": [True],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN_NEG"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 6, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [-50000.0],  # Negative drawn (credit balance)
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_NEG"],
            "child_reference": ["LOAN_NEG"],
            "child_type": ["loan"],
        }).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, None, mappings
        )
        df = facility_undrawn.collect()

        # Undrawn should be exactly the limit (1M), not limit + |negative| (1.05M)
        fac = df.filter(pl.col("exposure_reference") == "FAC_NEG_UNDRAWN")
        assert len(fac) == 1
        assert fac["undrawn_amount"][0] == pytest.approx(1000000.0)

    def test_mixed_positive_negative_drawn_amounts(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Mixed positive and negative drawn amounts - negatives treated as zero.

        When multiple loans are linked to a facility, only positive drawn amounts
        should count towards the total drawn. Negative amounts are floored at 0.
        """
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_MIX"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [1000000.0],
            "committed": [True],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        # Two loans: one positive (400k), one negative (-100k)
        # Total drawn should be 400k (not 300k), undrawn = 600k
        loans = pl.DataFrame({
            "loan_reference": ["LOAN_POS", "LOAN_NEG"],
            "product_type": ["TERM_LOAN", "TERM_LOAN"],
            "book_code": ["CORP", "CORP"],
            "counterparty_reference": ["CP001", "CP001"],
            "value_date": [date(2023, 6, 1), date(2023, 6, 1)],
            "maturity_date": [date(2028, 1, 1), date(2028, 1, 1)],
            "currency": ["GBP", "GBP"],
            "drawn_amount": [400000.0, -100000.0],
            "lgd": [0.45, 0.45],
            "seniority": ["senior", "senior"],
        }).lazy()

        mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_MIX", "FAC_MIX"],
            "child_reference": ["LOAN_POS", "LOAN_NEG"],
            "child_type": ["loan", "loan"],
        }).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, None, mappings
        )
        df = facility_undrawn.collect()

        # Undrawn = 1M - 400k = 600k (NOT 1M - 300k = 700k)
        fac = df.filter(pl.col("exposure_reference") == "FAC_MIX_UNDRAWN")
        assert len(fac) == 1
        assert fac["undrawn_amount"][0] == pytest.approx(600000.0)

    def test_all_negative_drawn_amounts(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """All negative drawn amounts should result in full limit as undrawn."""
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_ALL_NEG"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [500000.0],
            "committed": [True],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN_NEG1", "LOAN_NEG2"],
            "product_type": ["TERM_LOAN", "TERM_LOAN"],
            "book_code": ["CORP", "CORP"],
            "counterparty_reference": ["CP001", "CP001"],
            "value_date": [date(2023, 6, 1), date(2023, 6, 1)],
            "maturity_date": [date(2028, 1, 1), date(2028, 1, 1)],
            "currency": ["GBP", "GBP"],
            "drawn_amount": [-25000.0, -75000.0],  # Both negative
            "lgd": [0.45, 0.45],
            "seniority": ["senior", "senior"],
        }).lazy()

        mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_ALL_NEG", "FAC_ALL_NEG"],
            "child_reference": ["LOAN_NEG1", "LOAN_NEG2"],
            "child_type": ["loan", "loan"],
        }).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, None, mappings
        )
        df = facility_undrawn.collect()

        # Both loans are negative, so total_drawn = 0, undrawn = full limit
        fac = df.filter(pl.col("exposure_reference") == "FAC_ALL_NEG_UNDRAWN")
        assert len(fac) == 1
        assert fac["undrawn_amount"][0] == pytest.approx(500000.0)

    def test_facility_uncommitted_lr_risk_type(
        self,
        resolver: HierarchyResolver,
        facilities_with_undrawn: pl.LazyFrame,
        loans_for_facilities: pl.LazyFrame,
        facility_loan_mappings: pl.LazyFrame,
    ) -> None:
        """Uncommitted facility with LR risk type should create exposure with LR."""
        # FAC005: limit=1M, no linked loans, risk_type=LR (0% CCF)
        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities_with_undrawn,
            loans_for_facilities,
            None,
            facility_loan_mappings,
        )
        df = facility_undrawn.collect()

        fac005 = df.filter(pl.col("exposure_reference") == "FAC005_UNDRAWN")
        assert len(fac005) == 1
        assert fac005["undrawn_amount"][0] == pytest.approx(1000000.0)
        assert fac005["risk_type"][0] == "LR"  # Low risk = 0% CCF

    def test_facility_partial_draw_calculation(
        self,
        resolver: HierarchyResolver,
        facilities_with_undrawn: pl.LazyFrame,
        loans_for_facilities: pl.LazyFrame,
        facility_loan_mappings: pl.LazyFrame,
    ) -> None:
        """Partially drawn facility should have correct undrawn amount."""
        # FAC003: limit=500k, drawn=700k (LOAN004), but loan is mapped to FAC003
        # Wait - looking at the test data, LOAN004 (700k) is mapped to FAC003 (limit 500k)
        # This would result in negative undrawn, which should be capped at 0
        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities_with_undrawn,
            loans_for_facilities,
            None,
            facility_loan_mappings,
        )
        df = facility_undrawn.collect()

        # FAC003 has limit 500k but drawn 700k, so undrawn is capped at 0
        fac003 = df.filter(pl.col("exposure_reference") == "FAC003_UNDRAWN")
        assert len(fac003) == 0

    def test_facility_undrawn_inherits_ccf_fields(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Facility undrawn should inherit CCF-related fields from facility."""
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_CCF"],
            "product_type": ["TRADE_LC"],
            "book_code": ["TRADE"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2024, 6, 1)],
            "currency": ["GBP"],
            "limit": [500000.0],
            "committed": [True],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MLR"],  # Medium-low risk (20% SA, 75% F-IRB, or 20% if trade LC)
            "ccf_modelled": [0.65],
            "is_short_term_trade_lc": [True],  # Art. 166(9) exception
        }).lazy()

        loans = pl.LazyFrame(schema={
            "loan_reference": pl.String,
            "product_type": pl.String,
            "book_code": pl.String,
            "counterparty_reference": pl.String,
            "value_date": pl.Date,
            "maturity_date": pl.Date,
            "currency": pl.String,
            "drawn_amount": pl.Float64,
            "lgd": pl.Float64,
            "seniority": pl.String,
        })

        mappings = pl.LazyFrame(schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        })

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, None, mappings
        )
        df = facility_undrawn.collect()

        assert len(df) == 1
        assert df["exposure_reference"][0] == "FAC_CCF_UNDRAWN"
        assert df["risk_type"][0] == "MLR"
        assert df["ccf_modelled"][0] == pytest.approx(0.65)
        assert df["is_short_term_trade_lc"][0] is True
        assert df["nominal_amount"][0] == pytest.approx(500000.0)

    def test_empty_facilities_returns_empty(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Empty facilities should return empty LazyFrame."""
        facilities = pl.LazyFrame(schema={
            "facility_reference": pl.String,
            "limit": pl.Float64,
        })

        loans = pl.LazyFrame(schema={
            "loan_reference": pl.String,
            "drawn_amount": pl.Float64,
        })

        mappings = pl.LazyFrame(schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        })

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, None, mappings
        )
        df = facility_undrawn.collect()

        assert len(df) == 0


class TestFacilityUndrawnInUnifyExposures:
    """Tests for facility undrawn integration in _unify_exposures."""

    def test_unify_exposures_includes_facility_undrawn(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """_unify_exposures should include facility_undrawn exposure type."""
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_UNIFY"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [1000000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN_UNIFY"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [600000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_UNIFY"],
            "child_reference": ["LOAN_UNIFY"],
            "child_type": ["loan"],
        }).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        exposures, errors = resolver._unify_exposures(
            loans,
            None,  # No contingents
            facilities,
            facility_mappings,
            counterparty_lookup,
        )

        df = exposures.collect()

        # Should have loan + facility_undrawn
        assert len(df) == 2

        # Check exposure types
        exposure_types = df["exposure_type"].to_list()
        assert "loan" in exposure_types
        assert "facility_undrawn" in exposure_types

        # Check facility_undrawn record
        facility_undrawn = df.filter(pl.col("exposure_type") == "facility_undrawn")
        assert facility_undrawn["exposure_reference"][0] == "FAC_UNIFY_UNDRAWN"
        assert facility_undrawn["undrawn_amount"][0] == pytest.approx(400000.0)  # 1M - 600k
        assert facility_undrawn["nominal_amount"][0] == pytest.approx(400000.0)
        assert facility_undrawn["risk_type"][0] == "MR"

    def test_full_resolve_includes_facility_undrawn(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Full resolve() should include facility_undrawn exposures."""
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_RESOLVE"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP_RESOLVE"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [2000000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN_RESOLVE"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP_RESOLVE"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [500000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        counterparties = pl.DataFrame({
            "counterparty_reference": ["CP_RESOLVE"],
            "counterparty_name": ["Test Corp"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [50000000.0],
            "total_assets": [100000000.0],
            "default_status": [False],
            "sector_code": ["MANU"],
            "is_regulated": [False],
            "is_managed_as_retail": [False],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_RESOLVE"],
            "child_reference": ["LOAN_RESOLVE"],
            "child_type": ["loan"],
        }).lazy()

        bundle = RawDataBundle(
            facilities=facilities,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=facility_mappings,
            org_mappings=None,
            lending_mappings=pl.LazyFrame(schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }),
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Should have loan + facility_undrawn
        assert len(df) == 2

        # Check exposure types
        exposure_types = df["exposure_type"].unique().to_list()
        assert "loan" in exposure_types
        assert "facility_undrawn" in exposure_types

        # Check facility_undrawn amounts
        facility_undrawn = df.filter(pl.col("exposure_type") == "facility_undrawn")
        assert facility_undrawn["undrawn_amount"][0] == pytest.approx(1500000.0)  # 2M - 500k

    def test_facility_undrawn_excludes_interest_from_calculation(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Facility undrawn should be limit - drawn_amount (excluding interest).

        Per the plan:
        - Facility limit: 1000
        - Drawn loan: 500
        - Interest: 10
        - Undrawn = 1000 - 500 = 500 (interest excluded from undrawn calc)
        - On-balance-sheet = 500 + 10 = 510
        """
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_INT"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP_INT"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [1000.0],  # Limit = 1000
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN_INT"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP_INT"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [500.0],  # Drawn = 500
            "interest": [10.0],  # Interest = 10 (should NOT reduce undrawn)
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        counterparties = pl.DataFrame({
            "counterparty_reference": ["CP_INT"],
            "counterparty_name": ["Interest Test Corp"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [50000000.0],
            "total_assets": [100000000.0],
            "default_status": [False],
            "sector_code": ["MANU"],
            "is_regulated": [False],
            "is_managed_as_retail": [False],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_INT"],
            "child_reference": ["LOAN_INT"],
            "child_type": ["loan"],
        }).lazy()

        bundle = RawDataBundle(
            facilities=facilities,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=facility_mappings,
            org_mappings=None,
            lending_mappings=pl.LazyFrame(schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }),
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Should have loan + facility_undrawn = 2 exposures
        assert len(df) == 2

        # Check the loan exposure has interest included
        loan_exp = df.filter(pl.col("exposure_type") == "loan")
        assert loan_exp["drawn_amount"][0] == pytest.approx(500.0)
        assert loan_exp["interest"][0] == pytest.approx(10.0)

        # Check facility_undrawn uses only drawn_amount (not interest)
        # Undrawn = limit (1000) - drawn (500) = 500
        facility_undrawn = df.filter(pl.col("exposure_type") == "facility_undrawn")
        assert facility_undrawn["undrawn_amount"][0] == pytest.approx(500.0)
        # Facility undrawn should have interest = 0
        assert facility_undrawn["interest"][0] == pytest.approx(0.0)


# =============================================================================
# Same Reference Tests (facility_reference = loan_reference)
# =============================================================================


class TestSameFacilityAndLoanReference:
    """Tests for scenarios where facility_reference equals loan_reference.

    In some source systems, the facility and loan share the same reference ID.
    This is a valid business scenario that must be supported. The system
    differentiates them by:
    - exposure_type: "loan" vs "facility_undrawn"
    - Facility undrawn gets "_UNDRAWN" suffix in exposure_reference
    - Different tables (facilities vs loans) with different schemas
    """

    @pytest.fixture
    def same_ref_facility(self) -> pl.LazyFrame:
        """Facility with reference that matches its loan."""
        return pl.DataFrame({
            "facility_reference": ["REF001"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP_SAME_REF"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [1000000.0],
            "committed": [True],
            "lgd": [0.45],
            "beel": [0.01],
            "is_revolving": [True],
            "seniority": ["senior"],
            "risk_type": ["MR"],
            "ccf_modelled": [None],
            "is_short_term_trade_lc": [False],
        }).lazy()

    @pytest.fixture
    def same_ref_loan(self) -> pl.LazyFrame:
        """Loan with reference that matches its parent facility."""
        return pl.DataFrame({
            "loan_reference": ["REF001"],  # Same as facility_reference
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP_SAME_REF"],
            "value_date": [date(2023, 6, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [600000.0],
            "interest": [5000.0],
            "lgd": [0.45],
            "beel": [0.01],
            "seniority": ["senior"],
        }).lazy()

    @pytest.fixture
    def same_ref_mapping(self) -> pl.LazyFrame:
        """Facility mapping linking facility REF001 to loan REF001."""
        return pl.DataFrame({
            "parent_facility_reference": ["REF001"],
            "child_reference": ["REF001"],  # Same reference for both
            "child_type": ["loan"],
        }).lazy()

    @pytest.fixture
    def same_ref_counterparty(self) -> pl.LazyFrame:
        """Counterparty for same-reference test."""
        return pl.DataFrame({
            "counterparty_reference": ["CP_SAME_REF"],
            "counterparty_name": ["Same Reference Corp"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [50000000.0],
            "total_assets": [100000000.0],
            "default_status": [False],
            "sector_code": ["MANU"],
            "is_regulated": [False],
            "is_managed_as_retail": [False],
        }).lazy()

    def test_undrawn_calculation_with_same_reference(
        self,
        resolver: HierarchyResolver,
        same_ref_facility: pl.LazyFrame,
        same_ref_loan: pl.LazyFrame,
        same_ref_mapping: pl.LazyFrame,
    ) -> None:
        """Undrawn calculation should work when facility and loan share reference.

        Facility REF001: limit=1M
        Loan REF001: drawn=600k
        Expected undrawn = 1M - 600k = 400k
        """
        facility_undrawn = resolver._calculate_facility_undrawn(
            same_ref_facility,
            same_ref_loan,
            None,
            same_ref_mapping,
        )
        df = facility_undrawn.collect()

        # Should create one undrawn exposure with _UNDRAWN suffix
        assert len(df) == 1
        assert df["exposure_reference"][0] == "REF001_UNDRAWN"
        assert df["undrawn_amount"][0] == pytest.approx(400000.0)
        assert df["exposure_type"][0] == "facility_undrawn"

    def test_unify_exposures_differentiates_same_reference(
        self,
        resolver: HierarchyResolver,
        same_ref_facility: pl.LazyFrame,
        same_ref_loan: pl.LazyFrame,
        same_ref_mapping: pl.LazyFrame,
        same_ref_counterparty: pl.LazyFrame,
    ) -> None:
        """Unified exposures should correctly differentiate loan from facility_undrawn.

        Even though facility_reference = loan_reference = "REF001":
        - Loan exposure: exposure_reference = "REF001", exposure_type = "loan"
        - Facility undrawn: exposure_reference = "REF001_UNDRAWN", exposure_type = "facility_undrawn"
        """
        # Build counterparty lookup
        enriched_counterparties = same_ref_counterparty.with_columns([
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

        exposures, errors = resolver._unify_exposures(
            same_ref_loan,
            None,  # No contingents
            same_ref_facility,
            same_ref_mapping,
            counterparty_lookup,
        )

        df = exposures.collect()

        # Should have 2 exposures: loan + facility_undrawn
        assert len(df) == 2

        # Check loan exposure
        loan_exp = df.filter(pl.col("exposure_type") == "loan")
        assert len(loan_exp) == 1
        assert loan_exp["exposure_reference"][0] == "REF001"
        assert loan_exp["drawn_amount"][0] == pytest.approx(600000.0)
        assert loan_exp["interest"][0] == pytest.approx(5000.0)

        # Check facility_undrawn exposure
        undrawn_exp = df.filter(pl.col("exposure_type") == "facility_undrawn")
        assert len(undrawn_exp) == 1
        assert undrawn_exp["exposure_reference"][0] == "REF001_UNDRAWN"
        assert undrawn_exp["undrawn_amount"][0] == pytest.approx(400000.0)

    def test_loan_correctly_linked_to_parent_facility_with_same_reference(
        self,
        resolver: HierarchyResolver,
        same_ref_facility: pl.LazyFrame,
        same_ref_loan: pl.LazyFrame,
        same_ref_mapping: pl.LazyFrame,
        same_ref_counterparty: pl.LazyFrame,
    ) -> None:
        """Loan should be correctly linked to parent facility even with same reference.

        The loan "REF001" should have parent_facility_reference = "REF001".
        This is not a circular reference - they are different entity types.
        """
        # Build counterparty lookup
        enriched_counterparties = same_ref_counterparty.with_columns([
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

        exposures, errors = resolver._unify_exposures(
            same_ref_loan,
            None,
            same_ref_facility,
            same_ref_mapping,
            counterparty_lookup,
        )

        df = exposures.collect()

        # Check loan has parent facility reference set
        loan_exp = df.filter(pl.col("exposure_type") == "loan")
        assert loan_exp["exposure_has_parent"][0] is True
        assert loan_exp["parent_facility_reference"][0] == "REF001"

        # Facility undrawn SHOULD have parent_facility_reference set to its source facility
        # This enables facility-level collateral to be allocated to undrawn amounts
        undrawn_exp = df.filter(pl.col("exposure_type") == "facility_undrawn")
        assert undrawn_exp["exposure_has_parent"][0] is True
        assert undrawn_exp["parent_facility_reference"][0] == "REF001"

    def test_full_resolve_with_same_reference(
        self,
        resolver: HierarchyResolver,
        same_ref_facility: pl.LazyFrame,
        same_ref_loan: pl.LazyFrame,
        same_ref_mapping: pl.LazyFrame,
        same_ref_counterparty: pl.LazyFrame,
        crr_config: CalculationConfig,
    ) -> None:
        """Full resolve() should work correctly with same facility/loan reference."""
        bundle = RawDataBundle(
            facilities=same_ref_facility,
            loans=same_ref_loan,
            contingents=None,
            counterparties=same_ref_counterparty,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=same_ref_mapping,
            org_mappings=None,
            lending_mappings=pl.LazyFrame(schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }),
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Should have 2 exposures
        assert len(df) == 2

        # Check both exposure types are present
        exposure_types = set(df["exposure_type"].to_list())
        assert exposure_types == {"loan", "facility_undrawn"}

        # Verify loan details
        loan_exp = df.filter(pl.col("exposure_type") == "loan")
        assert loan_exp["exposure_reference"][0] == "REF001"
        assert loan_exp["drawn_amount"][0] == pytest.approx(600000.0)
        assert loan_exp["parent_facility_reference"][0] == "REF001"
        assert loan_exp["exposure_has_parent"][0] is True

        # Verify facility_undrawn details
        undrawn_exp = df.filter(pl.col("exposure_type") == "facility_undrawn")
        assert undrawn_exp["exposure_reference"][0] == "REF001_UNDRAWN"
        assert undrawn_exp["undrawn_amount"][0] == pytest.approx(400000.0)
        assert undrawn_exp["nominal_amount"][0] == pytest.approx(400000.0)

    def test_multiple_loans_with_same_reference_pattern(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Multiple facilities can each have loans with matching references.

        This tests that the pattern works for multiple independent facility-loan pairs.
        """
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_A", "FAC_B"],
            "product_type": ["RCF", "TERM"],
            "book_code": ["CORP", "CORP"],
            "counterparty_reference": ["CP_A", "CP_B"],
            "value_date": [date(2023, 1, 1)] * 2,
            "maturity_date": [date(2028, 1, 1)] * 2,
            "currency": ["GBP", "GBP"],
            "limit": [500000.0, 800000.0],
            "lgd": [0.45, 0.45],
            "seniority": ["senior", "senior"],
            "risk_type": ["MR", "MR"],
        }).lazy()

        # Loans with SAME references as their parent facilities
        loans = pl.DataFrame({
            "loan_reference": ["FAC_A", "FAC_B"],  # Same as facility references
            "product_type": ["TERM_LOAN", "TERM_LOAN"],
            "book_code": ["CORP", "CORP"],
            "counterparty_reference": ["CP_A", "CP_B"],
            "value_date": [date(2023, 6, 1)] * 2,
            "maturity_date": [date(2028, 1, 1)] * 2,
            "currency": ["GBP", "GBP"],
            "drawn_amount": [300000.0, 500000.0],
            "lgd": [0.45, 0.45],
            "seniority": ["senior", "senior"],
        }).lazy()

        # Mappings where parent = child reference
        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_A", "FAC_B"],
            "child_reference": ["FAC_A", "FAC_B"],
            "child_type": ["loan", "loan"],
        }).lazy()

        counterparties = pl.DataFrame({
            "counterparty_reference": ["CP_A", "CP_B"],
            "counterparty_name": ["Corp A", "Corp B"],
            "entity_type": ["corporate", "corporate"],
            "country_code": ["GB", "GB"],
            "annual_revenue": [50000000.0, 60000000.0],
            "total_assets": [100000000.0, 120000000.0],
            "default_status": [False, False],
            "sector_code": ["MANU", "MANU"],
            "is_regulated": [False, False],
            "is_managed_as_retail": [False, False],
        }).lazy()

        bundle = RawDataBundle(
            facilities=facilities,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=facility_mappings,
            org_mappings=None,
            lending_mappings=pl.LazyFrame(schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }),
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Should have 4 exposures: 2 loans + 2 facility_undrawn
        assert len(df) == 4

        # Check loan exposures
        loans_df = df.filter(pl.col("exposure_type") == "loan").sort("exposure_reference")
        assert loans_df["exposure_reference"].to_list() == ["FAC_A", "FAC_B"]
        assert loans_df["parent_facility_reference"].to_list() == ["FAC_A", "FAC_B"]

        # Check facility_undrawn exposures
        undrawn_df = df.filter(pl.col("exposure_type") == "facility_undrawn").sort("exposure_reference")
        assert undrawn_df["exposure_reference"].to_list() == ["FAC_A_UNDRAWN", "FAC_B_UNDRAWN"]

        # Verify undrawn amounts
        fac_a_undrawn = undrawn_df.filter(pl.col("exposure_reference") == "FAC_A_UNDRAWN")
        assert fac_a_undrawn["undrawn_amount"][0] == pytest.approx(200000.0)  # 500k - 300k

        fac_b_undrawn = undrawn_df.filter(pl.col("exposure_reference") == "FAC_B_UNDRAWN")
        assert fac_b_undrawn["undrawn_amount"][0] == pytest.approx(300000.0)  # 800k - 500k

    def test_same_ref_with_sub_facility_no_row_duplication(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Loan should not be duplicated when sub-facility shares the same reference.

        Scenario:
            FAC_PARENT (parent facility, limit=2M)
              |-- SUB001 (child_type="facility")   <- sub-facility
              |-- SUB001 (child_type="loan")       <- loan with same ref

        facility_mappings has TWO rows with child_reference="SUB001".
        Without the fix, the left join in _unify_exposures produces a cartesian
        product, duplicating the loan exposure row.
        """
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_PARENT"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP_SUB"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [2000000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["SUB001"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP_SUB"],
            "value_date": [date(2023, 6, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [500000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        # Two rows for SUB001: one as a sub-facility, one as a loan
        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_PARENT", "FAC_PARENT"],
            "child_reference": ["SUB001", "SUB001"],
            "child_type": ["facility", "loan"],
        }).lazy()

        counterparties = pl.DataFrame({
            "counterparty_reference": ["CP_SUB"],
            "counterparty_name": ["Sub-Facility Corp"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [50000000.0],
            "total_assets": [100000000.0],
            "default_status": [False],
            "sector_code": ["MANU"],
            "is_regulated": [False],
            "is_managed_as_retail": [False],
        }).lazy()

        bundle = RawDataBundle(
            facilities=facilities,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=facility_mappings,
            org_mappings=None,
            lending_mappings=pl.LazyFrame(schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }),
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Loan SUB001 should appear exactly once (not duplicated by the facility mapping row)
        loan_rows = df.filter(
            (pl.col("exposure_type") == "loan") &
            (pl.col("exposure_reference") == "SUB001")
        )
        assert len(loan_rows) == 1, (
            f"Expected 1 loan row for SUB001, got {len(loan_rows)}. "
            f"Facility mapping join likely caused duplication."
        )

    def test_same_reference_fully_drawn_no_undrawn_exposure(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """When facility is fully drawn, only loan exposure should exist."""
        facilities = pl.DataFrame({
            "facility_reference": ["FULL_DRAW"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP_FULL"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [500000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        # Loan with same reference, fully drawn
        loans = pl.DataFrame({
            "loan_reference": ["FULL_DRAW"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP_FULL"],
            "value_date": [date(2023, 6, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [500000.0],  # Fully drawn = limit
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FULL_DRAW"],
            "child_reference": ["FULL_DRAW"],
            "child_type": ["loan"],
        }).lazy()

        counterparties = pl.DataFrame({
            "counterparty_reference": ["CP_FULL"],
            "counterparty_name": ["Fully Drawn Corp"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [50000000.0],
            "total_assets": [100000000.0],
            "default_status": [False],
            "sector_code": ["MANU"],
            "is_regulated": [False],
            "is_managed_as_retail": [False],
        }).lazy()

        bundle = RawDataBundle(
            facilities=facilities,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=facility_mappings,
            org_mappings=None,
            lending_mappings=pl.LazyFrame(schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }),
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # Should have only 1 exposure: the loan (no undrawn since fully drawn)
        assert len(df) == 1
        assert df["exposure_type"][0] == "loan"
        assert df["exposure_reference"][0] == "FULL_DRAW"
        assert df["drawn_amount"][0] == pytest.approx(500000.0)


# =============================================================================
# Lending Group Duplicate Membership Tests
# =============================================================================


class TestLendingGroupDuplicateMembership:
    """Tests for lending group duplication when counterparty appears in multiple groups.

    Bug 2: When a counterparty appears in multiple lending groups or as both
    a parent and child across groups, the pl.concat of lending_groups and
    parent_as_member can produce duplicate member_counterparty_reference entries,
    causing row duplication when joined to exposures.
    """

    def _build_counterparty_lookup(
        self, counterparties: pl.LazyFrame
    ) -> CounterpartyLookup:
        """Helper to build a minimal counterparty lookup for lending group tests."""
        enriched = counterparties.with_columns([
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
        return CounterpartyLookup(
            counterparties=enriched,
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

    def test_counterparty_in_multiple_groups_no_row_duplication(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Counterparty in multiple lending groups should not duplicate exposure rows.

        Scenario:
            LG_A -> SHARED_CP (child)
            LG_B -> SHARED_CP (child)

        SHARED_CP appears in all_members twice (once per group). Without the fix,
        joining exposures to all_members duplicates the loan row.
        """
        counterparties = pl.DataFrame({
            "counterparty_reference": ["LG_A", "LG_B", "SHARED_CP"],
            "counterparty_name": ["Group A", "Group B", "Shared CP"],
            "entity_type": ["individual", "individual", "individual"],
            "country_code": ["GB", "GB", "GB"],
            "annual_revenue": [0.0, 0.0, 0.0],
            "total_assets": [0.0, 0.0, 0.0],
            "default_status": [False, False, False],
            "sector_code": ["RETAIL", "RETAIL", "RETAIL"],
            "is_regulated": [False, False, False],
            "is_managed_as_retail": [False, False, False],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN_SHARED"],
            "product_type": ["PERSONAL"],
            "book_code": ["RETAIL"],
            "counterparty_reference": ["SHARED_CP"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [100000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        lending_mappings = pl.DataFrame({
            "parent_counterparty_reference": ["LG_A", "LG_B"],
            "child_counterparty_reference": ["SHARED_CP", "SHARED_CP"],
        }).lazy()

        bundle = RawDataBundle(
            facilities=None,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=pl.LazyFrame(schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }),
            org_mappings=None,
            lending_mappings=lending_mappings,
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # SHARED_CP's loan should appear exactly once
        loan_rows = df.filter(pl.col("exposure_reference") == "LOAN_SHARED")
        assert len(loan_rows) == 1, (
            f"Expected 1 row for LOAN_SHARED, got {len(loan_rows)}. "
            f"Lending group join likely caused duplication."
        )

    def test_counterparty_as_parent_and_child_in_different_group(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """Counterparty that is both a child in one group and parent of another.

        Scenario:
            LG_A -> CP_DUAL (child)
            CP_DUAL -> CP_OTHER (parent of its own group)

        CP_DUAL appears in all_members twice: once from lending_groups (as child of
        LG_A) and once from parent_as_member (as parent of the CP_DUAL group).
        Without the fix, LOAN_DUAL is duplicated.
        """
        counterparties = pl.DataFrame({
            "counterparty_reference": ["LG_A", "CP_DUAL", "CP_OTHER"],
            "counterparty_name": ["Group A", "Dual Role CP", "Other CP"],
            "entity_type": ["individual", "individual", "individual"],
            "country_code": ["GB", "GB", "GB"],
            "annual_revenue": [0.0, 0.0, 0.0],
            "total_assets": [0.0, 0.0, 0.0],
            "default_status": [False, False, False],
            "sector_code": ["RETAIL", "RETAIL", "RETAIL"],
            "is_regulated": [False, False, False],
            "is_managed_as_retail": [False, False, False],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN_DUAL", "LOAN_OTHER"],
            "product_type": ["PERSONAL", "PERSONAL"],
            "book_code": ["RETAIL", "RETAIL"],
            "counterparty_reference": ["CP_DUAL", "CP_OTHER"],
            "value_date": [date(2023, 1, 1), date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1), date(2028, 1, 1)],
            "currency": ["GBP", "GBP"],
            "drawn_amount": [200000.0, 150000.0],
            "lgd": [0.45, 0.45],
            "seniority": ["senior", "senior"],
        }).lazy()

        # CP_DUAL is a child of LG_A, AND CP_DUAL is a parent of CP_OTHER
        lending_mappings = pl.DataFrame({
            "parent_counterparty_reference": ["LG_A", "CP_DUAL"],
            "child_counterparty_reference": ["CP_DUAL", "CP_OTHER"],
        }).lazy()

        bundle = RawDataBundle(
            facilities=None,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=pl.LazyFrame(schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }),
            org_mappings=None,
            lending_mappings=lending_mappings,
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # LOAN_DUAL should appear exactly once
        dual_rows = df.filter(pl.col("exposure_reference") == "LOAN_DUAL")
        assert len(dual_rows) == 1, (
            f"Expected 1 row for LOAN_DUAL, got {len(dual_rows)}. "
            f"Lending group parent_as_member caused duplication."
        )

        # Total should be 2 rows (LOAN_DUAL + LOAN_OTHER)
        assert len(df) == 2, (
            f"Expected 2 total rows, got {len(df)}."
        )


class TestNegativeDrawnAmountInHierarchy:
    """Tests for negative drawn amounts in hierarchy calculations.

    Credit balances (negative drawn) should not reduce exposure totals
    used in property coverage or lending group calculations.
    """

    def test_negative_drawn_property_coverage(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """total_exposure_amount in property coverage should floor at 0."""
        counterparties = pl.DataFrame({
            "counterparty_reference": ["CP001"],
            "counterparty_name": ["Test"],
            "entity_type": ["individual"],
            "country_code": ["GB"],
            "annual_revenue": [0.0],
            "total_assets": [0.0],
            "default_status": [False],
            "sector_code": ["RETAIL"],
            "is_financial_institution": [False],
            "is_regulated": [False],
            "is_pse": [False],
            "is_mdb": [False],
            "is_international_org": [False],
            "is_central_counterparty": [False],
            "is_regional_govt_local_auth": [False],
            "is_managed_as_retail": [False],
        }).lazy()

        enriched_counterparties = counterparties.with_columns([
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

        loans = pl.DataFrame({
            "loan_reference": ["LOAN_NEG"],
            "product_type": ["MORTGAGE"],
            "book_code": ["RETAIL"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [-50000.0],
            "lgd": [0.15],
            "beel": [0.01],
            "seniority": ["senior"],
            "risk_type": ["FR"],
            "ccf_modelled": [None],
            "is_short_term_trade_lc": [None],
        }).lazy()

        exposures, _ = resolver._unify_exposures(
            loans,
            pl.LazyFrame(schema={
                "contingent_reference": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "counterparty_reference": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "currency": pl.String,
                "nominal_amount": pl.Float64,
                "lgd": pl.Float64,
                "beel": pl.Float64,
                "seniority": pl.String,
                "risk_type": pl.String,
                "ccf_modelled": pl.Float64,
                "is_short_term_trade_lc": pl.Boolean,
            }),
            None,
            pl.LazyFrame(schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }),
            counterparty_lookup,
        )

        coverage = resolver._calculate_residential_property_coverage(
            exposures,
            None,
        )

        df = coverage.collect()
        row = df.filter(pl.col("exposure_reference") == "LOAN_NEG")

        # total_exposure_amount should be 0, not -50000
        assert row["exposure_for_retail_threshold"][0] >= 0.0

    def test_negative_drawn_lending_group_totals(
        self,
        resolver: HierarchyResolver,
        lending_group_mappings: pl.LazyFrame,
    ) -> None:
        """Lending group totals should floor negative drawn amounts at 0."""
        counterparties = pl.DataFrame({
            "counterparty_reference": ["LG_ANCHOR", "LG_MEMBER1", "LG_MEMBER2"],
            "counterparty_name": ["Anchor", "Member 1", "Member 2"],
            "entity_type": ["individual", "individual", "corporate"],
            "country_code": ["GB", "GB", "GB"],
            "annual_revenue": [0.0, 0.0, 500000.0],
            "total_assets": [0.0, 0.0, 1000000.0],
            "default_status": [False, False, False],
            "sector_code": ["RETAIL", "RETAIL", "RETAIL"],
            "is_financial_institution": [False, False, False],
            "is_regulated": [False, False, False],
            "is_pse": [False, False, False],
            "is_mdb": [False, False, False],
            "is_international_org": [False, False, False],
            "is_central_counterparty": [False, False, False],
            "is_regional_govt_local_auth": [False, False, False],
            "is_managed_as_retail": [False, False, False],
        }).lazy()

        enriched_counterparties = counterparties.with_columns([
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

        # Member1 has negative drawn (credit balance on current account)
        loans = pl.DataFrame({
            "loan_reference": ["LG_LOAN1", "LG_LOAN2", "LG_LOAN3"],
            "product_type": ["MORTGAGE", "PERSONAL", "BUSINESS"],
            "book_code": ["RETAIL", "RETAIL", "RETAIL"],
            "counterparty_reference": ["LG_ANCHOR", "LG_MEMBER1", "LG_MEMBER2"],
            "value_date": [date(2023, 1, 1)] * 3,
            "maturity_date": [date(2028, 1, 1)] * 3,
            "currency": ["GBP", "GBP", "GBP"],
            "drawn_amount": [300000.0, -50000.0, 400000.0],
            "lgd": [0.15, 0.45, 0.45],
            "beel": [0.01, 0.01, 0.01],
            "seniority": ["senior", "senior", "senior"],
            "risk_type": ["FR", "FR", "FR"],
            "ccf_modelled": [None, None, None],
            "is_short_term_trade_lc": [None, None, None],
        }).lazy()

        exposures, _ = resolver._unify_exposures(
            loans,
            pl.LazyFrame(schema={
                "contingent_reference": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "counterparty_reference": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "currency": pl.String,
                "nominal_amount": pl.Float64,
                "lgd": pl.Float64,
                "beel": pl.Float64,
                "seniority": pl.String,
                "risk_type": pl.String,
                "ccf_modelled": pl.Float64,
                "is_short_term_trade_lc": pl.Boolean,
            }),
            None,
            pl.LazyFrame(schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }),
            counterparty_lookup,
        )

        residential_coverage = resolver._calculate_residential_property_coverage(
            exposures,
            None,
        )

        lending_group_totals, _ = resolver._calculate_lending_group_totals(
            exposures,
            lending_group_mappings,
            residential_coverage,
        )

        df = lending_group_totals.collect()

        # total_drawn should floor the -50k at 0: 300k + 0 + 400k = 700k
        assert df["total_drawn"][0] == pytest.approx(700000.0)
        # total_exposure should also floor: (300k+0) + (0+0) + (400k+0) = 700k
        assert df["total_exposure"][0] == pytest.approx(700000.0)


# =============================================================================
# Duplicate Mapping Bug Fix Tests
# =============================================================================


class TestDuplicateMappingBugFixes:
    """Tests for bugs where duplicate facility_mappings rows cause:
    - Drawn total inflation (Bug 1) — silently drops facility_undrawn
    - Row duplication in _unify_exposures (Bug 2)
    - Missing type column fallback crash (Bug 3)
    """

    def test_duplicate_loan_mappings_do_not_inflate_drawn_total(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Duplicate (child_reference, parent_facility_reference) pairs in
        facility_mappings must not double-count drawn amounts.

        1 facility (limit=1M), 1 loan (drawn=600k), duplicate mapping row.
        Without the fix: total_drawn=1.2M, undrawn=0, facility silently dropped.
        With the fix: total_drawn=600k, undrawn=400k.
        """
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_DUP"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP_DUP"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [1000000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN_DUP"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP_DUP"],
            "value_date": [date(2023, 6, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [600000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        # Duplicate mapping row for the same loan → facility link
        mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_DUP", "FAC_DUP"],
            "child_reference": ["LOAN_DUP", "LOAN_DUP"],
            "child_type": ["loan", "loan"],
        }).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, None, mappings
        )
        df = facility_undrawn.collect()

        # Should produce 1 undrawn row with correct amount
        fac = df.filter(pl.col("exposure_reference") == "FAC_DUP_UNDRAWN")
        assert len(fac) == 1, (
            f"Expected 1 facility_undrawn row, got {len(fac)}. "
            f"Duplicate mappings likely inflated drawn total."
        )
        assert fac["undrawn_amount"][0] == pytest.approx(400000.0)  # 1M - 600k

    def test_duplicate_exposure_mappings_do_not_duplicate_rows(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Duplicate child_reference rows in facility_mappings must not
        duplicate exposure rows in _unify_exposures.

        1 facility, 1 loan, duplicate mapping row.
        Without the fix: loan appears twice, total rows = 3.
        With the fix: loan appears once, total rows = 2 (loan + facility_undrawn).
        """
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_EXPDUP"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [1000000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN_EXPDUP"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [600000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        # Duplicate mapping: same child_reference appears twice
        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_EXPDUP", "FAC_EXPDUP"],
            "child_reference": ["LOAN_EXPDUP", "LOAN_EXPDUP"],
            "child_type": ["loan", "loan"],
        }).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties,
            simple_org_mappings,
            simple_ratings,
        )

        exposures, errors = resolver._unify_exposures(
            loans,
            None,
            facilities,
            facility_mappings,
            counterparty_lookup,
        )

        df = exposures.collect()

        # Loan should appear exactly once
        loan_rows = df.filter(pl.col("exposure_type") == "loan")
        assert len(loan_rows) == 1, (
            f"Expected 1 loan row, got {len(loan_rows)}. "
            f"Duplicate mapping rows caused row duplication in _unify_exposures."
        )

        # Total rows = loan + facility_undrawn
        assert len(df) == 2

    def test_facility_undrawn_with_no_type_column(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """facility_mappings with neither child_type nor node_type column
        should still produce correct facility_undrawn rows (Bug 3 fallback).
        """
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_NOTYPE"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP_NOTYPE"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [1000000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN_NOTYPE"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP_NOTYPE"],
            "value_date": [date(2023, 6, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [300000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        # No child_type or node_type column at all
        mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_NOTYPE"],
            "child_reference": ["LOAN_NOTYPE"],
        }).lazy()

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, None, mappings
        )
        df = facility_undrawn.collect()

        fac = df.filter(pl.col("exposure_reference") == "FAC_NOTYPE_UNDRAWN")
        assert len(fac) == 1
        assert fac["undrawn_amount"][0] == pytest.approx(700000.0)  # 1M - 300k


class TestLargerDatasetFacilityUndrawn:
    """Integration test: facility_undrawn survives in a multi-group dataset
    with org hierarchy, lending groups, and duplicate mappings.
    """

    def test_facility_undrawn_survives_in_multi_group_dataset(
        self,
        resolver: HierarchyResolver,
        crr_config: CalculationConfig,
    ) -> None:
        """All facility_undrawn rows should be present with correct amounts
        in a realistic dataset with:
        - 4 counterparties in org hierarchy
        - 3 facilities with undrawn headroom
        - 4 loans
        - Lending groups
        - Duplicate mapping rows
        """
        counterparties = pl.DataFrame({
            "counterparty_reference": ["CP_PAR", "CP_CH1", "CP_CH2", "CP_CH3"],
            "counterparty_name": ["Parent Corp", "Child 1", "Child 2", "Child 3"],
            "entity_type": ["corporate", "corporate", "corporate", "corporate"],
            "country_code": ["GB", "GB", "GB", "GB"],
            "annual_revenue": [100e6, 20e6, 30e6, 15e6],
            "total_assets": [500e6, 100e6, 150e6, 75e6],
            "default_status": [False, False, False, False],
            "sector_code": ["MANU", "MANU", "MANU", "MANU"],
            "is_financial_institution": [False, False, False, False],
            "is_regulated": [False, False, False, False],
            "is_pse": [False, False, False, False],
            "is_mdb": [False, False, False, False],
            "is_international_org": [False, False, False, False],
            "is_central_counterparty": [False, False, False, False],
            "is_regional_govt_local_auth": [False, False, False, False],
            "is_managed_as_retail": [False, False, False, False],
        }).lazy()

        org_mappings = pl.DataFrame({
            "parent_counterparty_reference": ["CP_PAR", "CP_PAR", "CP_PAR"],
            "child_counterparty_reference": ["CP_CH1", "CP_CH2", "CP_CH3"],
        }).lazy()

        facilities = pl.DataFrame({
            "facility_reference": ["FAC_A", "FAC_B", "FAC_C"],
            "product_type": ["RCF", "RCF", "TERM"],
            "book_code": ["CORP", "CORP", "CORP"],
            "counterparty_reference": ["CP_CH1", "CP_CH2", "CP_CH3"],
            "value_date": [date(2023, 1, 1)] * 3,
            "maturity_date": [date(2028, 1, 1)] * 3,
            "currency": ["GBP"] * 3,
            "limit": [2000000.0, 1500000.0, 800000.0],
            "lgd": [0.45] * 3,
            "seniority": ["senior"] * 3,
            "risk_type": ["MR", "MR", "MR"],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LN_1", "LN_2", "LN_3", "LN_4"],
            "product_type": ["TERM_LOAN"] * 4,
            "book_code": ["CORP"] * 4,
            "counterparty_reference": ["CP_CH1", "CP_CH1", "CP_CH2", "CP_CH3"],
            "value_date": [date(2023, 6, 1)] * 4,
            "maturity_date": [date(2028, 1, 1)] * 4,
            "currency": ["GBP"] * 4,
            "drawn_amount": [800000.0, 400000.0, 1000000.0, 300000.0],
            "lgd": [0.45] * 4,
            "seniority": ["senior"] * 4,
        }).lazy()

        # Duplicate mapping rows for LN_1 (simulating real-world data issue)
        facility_mappings = pl.DataFrame({
            "parent_facility_reference": [
                "FAC_A", "FAC_A", "FAC_A",  # LN_1 duplicate + LN_2
                "FAC_B",                      # LN_3
                "FAC_C",                      # LN_4
            ],
            "child_reference": [
                "LN_1", "LN_1", "LN_2",  # LN_1 appears twice
                "LN_3",
                "LN_4",
            ],
            "child_type": ["loan", "loan", "loan", "loan", "loan"],
        }).lazy()

        lending_mappings = pl.DataFrame({
            "parent_counterparty_reference": ["LG_01", "LG_01"],
            "child_counterparty_reference": ["CP_CH1", "CP_CH2"],
        }).lazy()

        bundle = RawDataBundle(
            facilities=facilities,
            loans=loans,
            contingents=None,
            counterparties=counterparties,
            collateral=None,
            guarantees=None,
            provisions=None,
            ratings=None,
            facility_mappings=facility_mappings,
            org_mappings=org_mappings,
            lending_mappings=lending_mappings,
        )

        result = resolver.resolve(bundle, crr_config)
        df = result.exposures.collect()

        # All 3 facility_undrawn rows must be present
        undrawn = df.filter(pl.col("exposure_type") == "facility_undrawn").sort(
            "exposure_reference"
        )
        assert len(undrawn) == 3, (
            f"Expected 3 facility_undrawn rows, got {len(undrawn)}. "
            f"Refs present: {undrawn['exposure_reference'].to_list()}"
        )

        # FAC_A: limit=2M, drawn=800k+400k=1.2M, undrawn=800k
        fac_a = undrawn.filter(pl.col("exposure_reference") == "FAC_A_UNDRAWN")
        assert fac_a["undrawn_amount"][0] == pytest.approx(800000.0)

        # FAC_B: limit=1.5M, drawn=1M, undrawn=500k
        fac_b = undrawn.filter(pl.col("exposure_reference") == "FAC_B_UNDRAWN")
        assert fac_b["undrawn_amount"][0] == pytest.approx(500000.0)

        # FAC_C: limit=800k, drawn=300k, undrawn=500k
        fac_c = undrawn.filter(pl.col("exposure_reference") == "FAC_C_UNDRAWN")
        assert fac_c["undrawn_amount"][0] == pytest.approx(500000.0)

        # 4 loan rows should not be duplicated
        loan_rows = df.filter(pl.col("exposure_type") == "loan")
        assert len(loan_rows) == 4, (
            f"Expected 4 loan rows, got {len(loan_rows)}. "
            f"Duplicate mappings caused loan row duplication."
        )


# =============================================================================
# Facility Root Lookup Tests (multi-level facility hierarchy)
# =============================================================================


class TestBuildFacilityRootLookup:
    """Tests for _build_facility_root_lookup method."""

    def test_single_level_returns_parent_as_root(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Sub-facility → parent: root = parent, depth = 1."""
        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_PARENT"],
            "child_reference": ["FAC_CHILD"],
            "child_type": ["facility"],
        }).lazy()

        lookup = resolver._build_facility_root_lookup(facility_mappings)
        df = lookup.collect()

        assert len(df) == 1
        row = df.row(0, named=True)
        assert row["child_facility_reference"] == "FAC_CHILD"
        assert row["root_facility_reference"] == "FAC_PARENT"
        assert row["facility_hierarchy_depth"] == 1

    def test_two_level_hierarchy_resolves_to_root(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """sub2 → sub1 → root: root = root, depth = 2."""
        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_ROOT", "FAC_SUB1"],
            "child_reference": ["FAC_SUB1", "FAC_SUB2"],
            "child_type": ["facility", "facility"],
        }).lazy()

        lookup = resolver._build_facility_root_lookup(facility_mappings)
        df = lookup.collect()

        # Both sub1 and sub2 should be in lookup
        assert len(df) == 2

        sub1 = df.filter(pl.col("child_facility_reference") == "FAC_SUB1")
        assert sub1["root_facility_reference"][0] == "FAC_ROOT"
        assert sub1["facility_hierarchy_depth"][0] == 1

        sub2 = df.filter(pl.col("child_facility_reference") == "FAC_SUB2")
        assert sub2["root_facility_reference"][0] == "FAC_ROOT"
        assert sub2["facility_hierarchy_depth"][0] == 2

    def test_multiple_branches_same_root(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Two sub-facilities under one parent both resolve to same root."""
        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_ROOT", "FAC_ROOT"],
            "child_reference": ["SUB_A", "SUB_B"],
            "child_type": ["facility", "facility"],
        }).lazy()

        lookup = resolver._build_facility_root_lookup(facility_mappings)
        df = lookup.collect()

        assert len(df) == 2
        roots = df["root_facility_reference"].unique().to_list()
        assert roots == ["FAC_ROOT"]

    def test_no_facility_type_column_returns_empty(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """No child_type/node_type column → cannot detect sub-facilities, return empty."""
        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_ROOT"],
            "child_reference": ["SUB_A"],
        }).lazy()

        lookup = resolver._build_facility_root_lookup(facility_mappings)
        df = lookup.collect()

        assert len(df) == 0

    def test_empty_mappings(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Empty facility mappings → empty lookup."""
        facility_mappings = pl.DataFrame({
            "parent_facility_reference": pl.Series([], dtype=pl.String),
            "child_reference": pl.Series([], dtype=pl.String),
            "child_type": pl.Series([], dtype=pl.String),
        }).lazy()

        lookup = resolver._build_facility_root_lookup(facility_mappings)
        df = lookup.collect()

        assert len(df) == 0


class TestMultiLevelFacilityUndrawn:
    """Tests for multi-level facility undrawn aggregation."""

    def test_multi_level_undrawn_aggregates_to_root(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Parent (limit=2M) with two sub-facilities containing loans.

        FAC_PARENT (limit=2M)
        ├── SUB001 (limit=1M) → LOAN01 (drawn=0.5M)
        └── SUB002 (limit=0.5M) → LOAN02 (drawn=0.25M)

        Expected: FAC_PARENT_UNDRAWN = 2M - 0.75M = 1.25M
        """
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_PARENT", "SUB001", "SUB002"],
            "product_type": ["RCF", "RCF", "RCF"],
            "book_code": ["CORP", "CORP", "CORP"],
            "counterparty_reference": ["CP001", "CP001", "CP001"],
            "value_date": [date(2023, 1, 1)] * 3,
            "maturity_date": [date(2028, 1, 1)] * 3,
            "currency": ["GBP"] * 3,
            "limit": [2000000.0, 1000000.0, 500000.0],
            "lgd": [0.45] * 3,
            "seniority": ["senior"] * 3,
            "risk_type": ["MR"] * 3,
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN01", "LOAN02"],
            "product_type": ["TERM_LOAN", "TERM_LOAN"],
            "book_code": ["CORP", "CORP"],
            "counterparty_reference": ["CP001", "CP001"],
            "value_date": [date(2023, 6, 1)] * 2,
            "maturity_date": [date(2028, 1, 1)] * 2,
            "currency": ["GBP"] * 2,
            "drawn_amount": [500000.0, 250000.0],
            "lgd": [0.45] * 2,
            "seniority": ["senior"] * 2,
        }).lazy()

        # Mappings: sub-facilities under parent, loans under sub-facilities
        facility_mappings = pl.DataFrame({
            "parent_facility_reference": [
                "FAC_PARENT", "FAC_PARENT",  # sub-facilities under parent
                "SUB001", "SUB002",           # loans under sub-facilities
            ],
            "child_reference": [
                "SUB001", "SUB002",
                "LOAN01", "LOAN02",
            ],
            "child_type": [
                "facility", "facility",
                "loan", "loan",
            ],
        }).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, None, facility_mappings, facility_root_lookup,
        )
        df = facility_undrawn.collect()

        # Only root facility should produce undrawn exposure
        parent_undrawn = df.filter(
            pl.col("exposure_reference") == "FAC_PARENT_UNDRAWN"
        )
        assert len(parent_undrawn) == 1
        assert parent_undrawn["undrawn_amount"][0] == pytest.approx(1250000.0)

    def test_sub_facilities_excluded_from_undrawn(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Sub-facilities should NOT produce their own undrawn exposures."""
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_PARENT", "SUB001"],
            "product_type": ["RCF", "RCF"],
            "book_code": ["CORP", "CORP"],
            "counterparty_reference": ["CP001", "CP001"],
            "value_date": [date(2023, 1, 1)] * 2,
            "maturity_date": [date(2028, 1, 1)] * 2,
            "currency": ["GBP"] * 2,
            "limit": [2000000.0, 1000000.0],
            "lgd": [0.45] * 2,
            "seniority": ["senior"] * 2,
            "risk_type": ["MR"] * 2,
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN01"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 6, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [500000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_PARENT", "SUB001"],
            "child_reference": ["SUB001", "LOAN01"],
            "child_type": ["facility", "loan"],
        }).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, None, facility_mappings, facility_root_lookup,
        )
        df = facility_undrawn.collect()

        # SUB001 should NOT have its own undrawn exposure
        sub_undrawn = df.filter(
            pl.col("exposure_reference") == "SUB001_UNDRAWN"
        )
        assert len(sub_undrawn) == 0

        # Only FAC_PARENT should have undrawn
        assert len(df) == 1
        assert df["exposure_reference"][0] == "FAC_PARENT_UNDRAWN"

    def test_single_level_undrawn_unchanged(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """No regression: simple facility→loan (no sub-facilities) still works."""
        facilities = pl.DataFrame({
            "facility_reference": ["FAC001"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [1000000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN01"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 6, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [600000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC001"],
            "child_reference": ["LOAN01"],
            "child_type": ["loan"],
        }).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, None, facility_mappings, facility_root_lookup,
        )
        df = facility_undrawn.collect()

        assert len(df) == 1
        assert df["exposure_reference"][0] == "FAC001_UNDRAWN"
        assert df["undrawn_amount"][0] == pytest.approx(400000.0)


class TestMultiLevelUnifyExposures:
    """Integration tests for multi-level facility hierarchy in _unify_exposures."""

    def test_multi_level_root_facility_reference_correct(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Loan under sub-facility gets root = parent facility."""
        loans = pl.DataFrame({
            "loan_reference": ["LOAN01"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [500000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        facilities = pl.DataFrame({
            "facility_reference": ["FAC_ROOT", "SUB001"],
            "product_type": ["RCF", "RCF"],
            "book_code": ["CORP", "CORP"],
            "counterparty_reference": ["CP001", "CP001"],
            "value_date": [date(2023, 1, 1)] * 2,
            "maturity_date": [date(2028, 1, 1)] * 2,
            "currency": ["GBP"] * 2,
            "limit": [2000000.0, 1000000.0],
            "lgd": [0.45] * 2,
            "seniority": ["senior"] * 2,
            "risk_type": ["MR"] * 2,
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_ROOT", "SUB001"],
            "child_reference": ["SUB001", "LOAN01"],
            "child_type": ["facility", "loan"],
        }).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties, simple_org_mappings, simple_ratings,
        )

        exposures, errors = resolver._unify_exposures(
            loans, None, facilities, facility_mappings, counterparty_lookup,
        )
        df = exposures.collect()

        # Loan's root_facility_reference should be the ultimate root
        loan_row = df.filter(pl.col("exposure_reference") == "LOAN01")
        assert loan_row["root_facility_reference"][0] == "FAC_ROOT"

    def test_multi_level_facility_hierarchy_depth_correct(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Loan under sub-facility → depth=2 for two-level hierarchy."""
        loans = pl.DataFrame({
            "loan_reference": ["LOAN01"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [500000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        facilities = pl.DataFrame({
            "facility_reference": ["FAC_ROOT", "SUB001"],
            "product_type": ["RCF", "RCF"],
            "book_code": ["CORP", "CORP"],
            "counterparty_reference": ["CP001", "CP001"],
            "value_date": [date(2023, 1, 1)] * 2,
            "maturity_date": [date(2028, 1, 1)] * 2,
            "currency": ["GBP"] * 2,
            "limit": [2000000.0, 1000000.0],
            "lgd": [0.45] * 2,
            "seniority": ["senior"] * 2,
            "risk_type": ["MR"] * 2,
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC_ROOT", "SUB001"],
            "child_reference": ["SUB001", "LOAN01"],
            "child_type": ["facility", "loan"],
        }).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties, simple_org_mappings, simple_ratings,
        )

        exposures, errors = resolver._unify_exposures(
            loans, None, facilities, facility_mappings, counterparty_lookup,
        )
        df = exposures.collect()

        # Loan under sub-facility should have depth 2
        loan_row = df.filter(pl.col("exposure_reference") == "LOAN01")
        assert loan_row["facility_hierarchy_depth"][0] == 2

    def test_standalone_loan_depth_is_zero(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Loan with no facility parent gets depth=0."""
        loans = pl.DataFrame({
            "loan_reference": ["STANDALONE_LOAN"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [100000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": pl.Series([], dtype=pl.String),
            "child_reference": pl.Series([], dtype=pl.String),
            "child_type": pl.Series([], dtype=pl.String),
        }).lazy()

        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties, simple_org_mappings, simple_ratings,
        )

        exposures, errors = resolver._unify_exposures(
            loans, None, None, facility_mappings, counterparty_lookup,
        )
        df = exposures.collect()

        loan_row = df.filter(pl.col("exposure_reference") == "STANDALONE_LOAN")
        assert loan_row["facility_hierarchy_depth"][0] == 0
        assert loan_row["root_facility_reference"][0] is None


# =============================================================================
# Contingent in Facility Undrawn Calculation Tests
# =============================================================================


class TestContingentInFacilityUndrawn:
    """Tests for including contingents in facility undrawn calculations.

    Contingents mapped to a facility consume headroom and should reduce
    the facility's undrawn amount. Additionally, drawn contingents (ONB)
    should be treated as on-balance-sheet items in unified exposures.
    """

    def test_contingent_reduces_facility_undrawn(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """OFB contingent nominal_amount should reduce parent facility undrawn.

        FAC001 (limit=1M) → LOAN01 (drawn=0.5M) + CONT01 (OFB, nominal=0.1M)
        Expected undrawn: 1M - 0.5M - 0.1M = 0.4M
        """
        facilities = pl.DataFrame({
            "facility_reference": ["FAC001"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [1000000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN01"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 6, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [500000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        contingents = pl.DataFrame({
            "contingent_reference": ["CONT01"],
            "product_type": ["FINANCIAL_GUARANTEE"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2025, 1, 1)],
            "currency": ["GBP"],
            "nominal_amount": [100000.0],
            "lgd": [0.45],
            "beel": [0.01],
            "seniority": ["senior"],
            "risk_type": ["MR"],
            "ccf_modelled": [None],
            "is_short_term_trade_lc": [False],
            "bs_type": ["OFB"],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC001", "FAC001"],
            "child_reference": ["LOAN01", "CONT01"],
            "child_type": ["loan", "contingent"],
        }).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, contingents, facility_mappings, facility_root_lookup,
        )
        df = facility_undrawn.collect()

        fac001 = df.filter(pl.col("exposure_reference") == "FAC001_UNDRAWN")
        assert len(fac001) == 1
        assert fac001["undrawn_amount"][0] == pytest.approx(400000.0)

    def test_drawn_contingent_reduces_facility_undrawn(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """ONB (drawn) contingent nominal_amount should also reduce facility undrawn.

        FAC001 (limit=1M) → LOAN01 (drawn=0.5M) + CONT01 (ONB, nominal=0.25M)
        Expected undrawn: 1M - 0.5M - 0.25M = 0.25M
        """
        facilities = pl.DataFrame({
            "facility_reference": ["FAC001"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [1000000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN01"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 6, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [500000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        contingents = pl.DataFrame({
            "contingent_reference": ["CONT01"],
            "product_type": ["FINANCIAL_GUARANTEE"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2025, 1, 1)],
            "currency": ["GBP"],
            "nominal_amount": [250000.0],
            "lgd": [0.45],
            "beel": [0.01],
            "seniority": ["senior"],
            "risk_type": ["MR"],
            "ccf_modelled": [None],
            "is_short_term_trade_lc": [False],
            "bs_type": ["ONB"],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC001", "FAC001"],
            "child_reference": ["LOAN01", "CONT01"],
            "child_type": ["loan", "contingent"],
        }).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, contingents, facility_mappings, facility_root_lookup,
        )
        df = facility_undrawn.collect()

        fac001 = df.filter(pl.col("exposure_reference") == "FAC001_UNDRAWN")
        assert len(fac001) == 1
        assert fac001["undrawn_amount"][0] == pytest.approx(250000.0)

    def test_drawn_contingent_has_drawn_amount(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """ONB contingent in unified exposures should have drawn_amount = nominal, nominal = 0."""
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties, simple_org_mappings, simple_ratings,
        )

        loans = pl.DataFrame({
            "loan_reference": ["LOAN01"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP002"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2026, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [100000.0],
            "lgd": [0.45],
            "beel": [0.01],
            "seniority": ["senior"],
        }).lazy()

        contingents = pl.DataFrame({
            "contingent_reference": ["CONT01"],
            "product_type": ["FINANCIAL_GUARANTEE"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP002"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2025, 1, 1)],
            "currency": ["GBP"],
            "nominal_amount": [250000.0],
            "lgd": [0.45],
            "beel": [0.01],
            "seniority": ["senior"],
            "risk_type": ["MR"],
            "ccf_modelled": [None],
            "is_short_term_trade_lc": [False],
            "bs_type": ["ONB"],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": pl.Series([], dtype=pl.String),
            "child_reference": pl.Series([], dtype=pl.String),
            "child_type": pl.Series([], dtype=pl.String),
        }).lazy()

        exposures, _ = resolver._unify_exposures(
            loans, contingents, None, facility_mappings, counterparty_lookup,
        )
        df = exposures.collect()

        cont = df.filter(pl.col("exposure_reference") == "CONT01")
        assert len(cont) == 1
        assert cont["drawn_amount"][0] == pytest.approx(250000.0)
        assert cont["nominal_amount"][0] == pytest.approx(0.0)

    def test_undrawn_contingent_preserves_current_behaviour(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """OFB contingent retains current behaviour: drawn=0, nominal=X, CCF fields preserved."""
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties, simple_org_mappings, simple_ratings,
        )

        loans = pl.DataFrame({
            "loan_reference": ["LOAN01"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP002"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2026, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [100000.0],
            "lgd": [0.45],
            "beel": [0.01],
            "seniority": ["senior"],
        }).lazy()

        contingents = pl.DataFrame({
            "contingent_reference": ["CONT01"],
            "product_type": ["LETTER_OF_CREDIT"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP002"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2025, 1, 1)],
            "currency": ["GBP"],
            "nominal_amount": [100000.0],
            "lgd": [0.45],
            "beel": [0.01],
            "seniority": ["senior"],
            "risk_type": ["MR"],
            "ccf_modelled": [0.75],
            "is_short_term_trade_lc": [True],
            "bs_type": ["OFB"],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": pl.Series([], dtype=pl.String),
            "child_reference": pl.Series([], dtype=pl.String),
            "child_type": pl.Series([], dtype=pl.String),
        }).lazy()

        exposures, _ = resolver._unify_exposures(
            loans, contingents, None, facility_mappings, counterparty_lookup,
        )
        df = exposures.collect()

        cont = df.filter(pl.col("exposure_reference") == "CONT01")
        assert len(cont) == 1
        assert cont["drawn_amount"][0] == pytest.approx(0.0)
        assert cont["nominal_amount"][0] == pytest.approx(100000.0)
        assert cont["risk_type"][0] == "MR"
        assert cont["ccf_modelled"][0] == pytest.approx(0.75)
        assert cont["is_short_term_trade_lc"][0] is True

    def test_drawn_contingent_nullifies_ccf_fields(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """ONB contingent should have null risk_type, ccf_modelled, is_short_term_trade_lc."""
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties, simple_org_mappings, simple_ratings,
        )

        loans = pl.DataFrame({
            "loan_reference": ["LOAN01"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP002"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2026, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [100000.0],
            "lgd": [0.45],
            "beel": [0.01],
            "seniority": ["senior"],
        }).lazy()

        contingents = pl.DataFrame({
            "contingent_reference": ["CONT01"],
            "product_type": ["FINANCIAL_GUARANTEE"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP002"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2025, 1, 1)],
            "currency": ["GBP"],
            "nominal_amount": [250000.0],
            "lgd": [0.45],
            "beel": [0.01],
            "seniority": ["senior"],
            "risk_type": ["MR"],
            "ccf_modelled": [0.5],
            "is_short_term_trade_lc": [True],
            "bs_type": ["ONB"],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": pl.Series([], dtype=pl.String),
            "child_reference": pl.Series([], dtype=pl.String),
            "child_type": pl.Series([], dtype=pl.String),
        }).lazy()

        exposures, _ = resolver._unify_exposures(
            loans, contingents, None, facility_mappings, counterparty_lookup,
        )
        df = exposures.collect()

        cont = df.filter(pl.col("exposure_reference") == "CONT01")
        assert cont["risk_type"][0] is None
        assert cont["ccf_modelled"][0] is None
        assert cont["is_short_term_trade_lc"][0] is None

    def test_bs_type_defaults_to_ofb(
        self,
        resolver: HierarchyResolver,
        simple_counterparties: pl.LazyFrame,
        simple_org_mappings: pl.LazyFrame,
        simple_ratings: pl.LazyFrame,
    ) -> None:
        """Contingent without bs_type should behave as OFB (current default behaviour)."""
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            simple_counterparties, simple_org_mappings, simple_ratings,
        )

        loans = pl.DataFrame({
            "loan_reference": ["LOAN01"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP002"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2026, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [100000.0],
            "lgd": [0.45],
            "beel": [0.01],
            "seniority": ["senior"],
        }).lazy()

        # No bs_type column at all
        contingents = pl.DataFrame({
            "contingent_reference": ["CONT01"],
            "product_type": ["FINANCIAL_GUARANTEE"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP002"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2025, 1, 1)],
            "currency": ["GBP"],
            "nominal_amount": [100000.0],
            "lgd": [0.45],
            "beel": [0.01],
            "seniority": ["senior"],
            "risk_type": ["MR"],
            "ccf_modelled": [None],
            "is_short_term_trade_lc": [False],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": pl.Series([], dtype=pl.String),
            "child_reference": pl.Series([], dtype=pl.String),
            "child_type": pl.Series([], dtype=pl.String),
        }).lazy()

        exposures, _ = resolver._unify_exposures(
            loans, contingents, None, facility_mappings, counterparty_lookup,
        )
        df = exposures.collect()

        cont = df.filter(pl.col("exposure_reference") == "CONT01")
        assert cont["drawn_amount"][0] == pytest.approx(0.0)
        assert cont["nominal_amount"][0] == pytest.approx(100000.0)
        assert cont["risk_type"][0] == "MR"

    def test_mixed_loans_and_contingents_facility_undrawn(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Full scenario: loans + drawn + undrawn contingents under facility.

        FAC001 (limit=1M)
        ├── LOAN01 (drawn=0.5M)
        ├── CONT01 (ONB, nominal=0.1M)  — drawn contingent
        └── CONT02 (OFB, nominal=0.2M)  — undrawn contingent

        Expected undrawn: 1M - 0.5M - 0.1M - 0.2M = 0.2M
        """
        facilities = pl.DataFrame({
            "facility_reference": ["FAC001"],
            "product_type": ["RCF"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 1, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "limit": [1000000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
            "risk_type": ["MR"],
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN01"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 6, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [500000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        contingents = pl.DataFrame({
            "contingent_reference": ["CONT01", "CONT02"],
            "product_type": ["FINANCIAL_GUARANTEE", "LETTER_OF_CREDIT"],
            "book_code": ["CORP", "CORP"],
            "counterparty_reference": ["CP001", "CP001"],
            "value_date": [date(2023, 1, 1)] * 2,
            "maturity_date": [date(2025, 1, 1)] * 2,
            "currency": ["GBP", "GBP"],
            "nominal_amount": [100000.0, 200000.0],
            "lgd": [0.45, 0.45],
            "beel": [0.01, 0.01],
            "seniority": ["senior", "senior"],
            "risk_type": ["MR", "MR"],
            "ccf_modelled": [None, None],
            "is_short_term_trade_lc": [False, False],
            "bs_type": ["ONB", "OFB"],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": ["FAC001", "FAC001", "FAC001"],
            "child_reference": ["LOAN01", "CONT01", "CONT02"],
            "child_type": ["loan", "contingent", "contingent"],
        }).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, contingents, facility_mappings, facility_root_lookup,
        )
        df = facility_undrawn.collect()

        fac001 = df.filter(pl.col("exposure_reference") == "FAC001_UNDRAWN")
        assert len(fac001) == 1
        assert fac001["undrawn_amount"][0] == pytest.approx(200000.0)

    def test_multi_level_hierarchy_with_contingents(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Contingents under sub-facilities should roll up to root for undrawn calc.

        FAC_PARENT (limit=2M)
        ├── SUB001 (limit=1M) → LOAN01 (drawn=0.5M) + CONT01 (OFB, nominal=0.25M)
        └── SUB002 (limit=0.5M) → CONT02 (ONB, nominal=0.25M)

        Expected: FAC_PARENT undrawn = 2M - 0.5M - 0.25M - 0.25M = 1M
        """
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_PARENT", "SUB001", "SUB002"],
            "product_type": ["RCF", "RCF", "RCF"],
            "book_code": ["CORP", "CORP", "CORP"],
            "counterparty_reference": ["CP001", "CP001", "CP001"],
            "value_date": [date(2023, 1, 1)] * 3,
            "maturity_date": [date(2028, 1, 1)] * 3,
            "currency": ["GBP"] * 3,
            "limit": [2000000.0, 1000000.0, 500000.0],
            "lgd": [0.45] * 3,
            "seniority": ["senior"] * 3,
            "risk_type": ["MR"] * 3,
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN01"],
            "product_type": ["TERM_LOAN"],
            "book_code": ["CORP"],
            "counterparty_reference": ["CP001"],
            "value_date": [date(2023, 6, 1)],
            "maturity_date": [date(2028, 1, 1)],
            "currency": ["GBP"],
            "drawn_amount": [500000.0],
            "lgd": [0.45],
            "seniority": ["senior"],
        }).lazy()

        contingents = pl.DataFrame({
            "contingent_reference": ["CONT01", "CONT02"],
            "product_type": ["LETTER_OF_CREDIT", "FINANCIAL_GUARANTEE"],
            "book_code": ["CORP", "CORP"],
            "counterparty_reference": ["CP001", "CP001"],
            "value_date": [date(2023, 1, 1)] * 2,
            "maturity_date": [date(2025, 1, 1)] * 2,
            "currency": ["GBP", "GBP"],
            "nominal_amount": [250000.0, 250000.0],
            "lgd": [0.45, 0.45],
            "beel": [0.01, 0.01],
            "seniority": ["senior", "senior"],
            "risk_type": ["MR", "MR"],
            "ccf_modelled": [None, None],
            "is_short_term_trade_lc": [False, False],
            "bs_type": ["OFB", "ONB"],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": [
                "FAC_PARENT", "FAC_PARENT",
                "SUB001", "SUB001",
                "SUB002",
            ],
            "child_reference": [
                "SUB001", "SUB002",
                "LOAN01", "CONT01",
                "CONT02",
            ],
            "child_type": [
                "facility", "facility",
                "loan", "contingent",
                "contingent",
            ],
        }).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, contingents, facility_mappings, facility_root_lookup,
        )
        df = facility_undrawn.collect()

        # Only root facility should produce undrawn
        assert len(df) == 1
        parent_undrawn = df.filter(
            pl.col("exposure_reference") == "FAC_PARENT_UNDRAWN"
        )
        assert parent_undrawn["undrawn_amount"][0] == pytest.approx(1000000.0)

    def test_full_scenario_from_spec(
        self,
        resolver: HierarchyResolver,
    ) -> None:
        """Full scenario from requirements.

        FAC_PARENT (limit=2M)
        ├── SUB001 (limit=1M) → LOAN01 (drawn=0.5M) + CONT01 (ONB, nominal=0.25M)
        └── SUB002 (limit=0.5M) → LOAN02 (drawn=0.25M) + CONT02 (OFB, nominal=0.25M)

        Total utilised: 0.5M + 0.25M + 0.25M + 0.25M = 1.25M
        Expected: FAC_PARENT undrawn = 2M - 1.25M = 0.75M
        Sub-facilities should not produce undrawn records.
        """
        facilities = pl.DataFrame({
            "facility_reference": ["FAC_PARENT", "SUB001", "SUB002"],
            "product_type": ["RCF", "RCF", "RCF"],
            "book_code": ["CORP", "CORP", "CORP"],
            "counterparty_reference": ["CP001", "CP001", "CP001"],
            "value_date": [date(2023, 1, 1)] * 3,
            "maturity_date": [date(2028, 1, 1)] * 3,
            "currency": ["GBP"] * 3,
            "limit": [2000000.0, 1000000.0, 500000.0],
            "lgd": [0.45] * 3,
            "seniority": ["senior"] * 3,
            "risk_type": ["MR"] * 3,
        }).lazy()

        loans = pl.DataFrame({
            "loan_reference": ["LOAN01", "LOAN02"],
            "product_type": ["TERM_LOAN", "TERM_LOAN"],
            "book_code": ["CORP", "CORP"],
            "counterparty_reference": ["CP001", "CP001"],
            "value_date": [date(2023, 6, 1)] * 2,
            "maturity_date": [date(2028, 1, 1)] * 2,
            "currency": ["GBP"] * 2,
            "drawn_amount": [500000.0, 250000.0],
            "lgd": [0.45] * 2,
            "seniority": ["senior"] * 2,
        }).lazy()

        contingents = pl.DataFrame({
            "contingent_reference": ["CONT01", "CONT02"],
            "product_type": ["FINANCIAL_GUARANTEE", "LETTER_OF_CREDIT"],
            "book_code": ["CORP", "CORP"],
            "counterparty_reference": ["CP001", "CP001"],
            "value_date": [date(2023, 1, 1)] * 2,
            "maturity_date": [date(2025, 1, 1)] * 2,
            "currency": ["GBP", "GBP"],
            "nominal_amount": [250000.0, 250000.0],
            "lgd": [0.45, 0.45],
            "beel": [0.01, 0.01],
            "seniority": ["senior", "senior"],
            "risk_type": ["MR", "MR"],
            "ccf_modelled": [None, None],
            "is_short_term_trade_lc": [False, False],
            "bs_type": ["ONB", "OFB"],
        }).lazy()

        facility_mappings = pl.DataFrame({
            "parent_facility_reference": [
                "FAC_PARENT", "FAC_PARENT",
                "SUB001", "SUB001",
                "SUB002", "SUB002",
            ],
            "child_reference": [
                "SUB001", "SUB002",
                "LOAN01", "CONT01",
                "LOAN02", "CONT02",
            ],
            "child_type": [
                "facility", "facility",
                "loan", "contingent",
                "loan", "contingent",
            ],
        }).lazy()

        facility_root_lookup = resolver._build_facility_root_lookup(facility_mappings)

        facility_undrawn = resolver._calculate_facility_undrawn(
            facilities, loans, contingents, facility_mappings, facility_root_lookup,
        )
        df = facility_undrawn.collect()

        # Only root facility should produce undrawn
        assert len(df) == 1
        parent_undrawn = df.filter(
            pl.col("exposure_reference") == "FAC_PARENT_UNDRAWN"
        )
        assert parent_undrawn["undrawn_amount"][0] == pytest.approx(750000.0)

        # Sub-facilities should NOT have undrawn records
        sub_refs = df["exposure_reference"].to_list()
        assert "SUB001_UNDRAWN" not in sub_refs
        assert "SUB002_UNDRAWN" not in sub_refs
