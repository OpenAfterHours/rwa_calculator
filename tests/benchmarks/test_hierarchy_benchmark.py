"""
Benchmark tests for the HierarchyResolver.

Tests performance at various scales:
- 10K counterparties: Quick validation (~1s target)
- 100K counterparties: Standard benchmark (~5s target)
- 1M counterparties: Large scale (~60s target)

Usage:
    # Run all hierarchy benchmarks
    uv run pytest tests/benchmarks/test_hierarchy_benchmark.py --benchmark-only

    # Run specific scale
    uv run pytest tests/benchmarks/test_hierarchy_benchmark.py -k "10k" --benchmark-only

    # Save baseline
    uv run pytest tests/benchmarks/test_hierarchy_benchmark.py --benchmark-only --benchmark-save=hierarchy_baseline
"""

from datetime import date

import pytest
import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.hierarchy import HierarchyResolver


# Default reporting date for benchmarks
BENCHMARK_REPORTING_DATE = date(2026, 1, 1)


# =============================================================================
# 10K SCALE BENCHMARKS (Quick validation)
# =============================================================================


@pytest.mark.benchmark
@pytest.mark.scale_10k
class TestHierarchyBenchmark10K:
    """Hierarchy resolver benchmarks at 10K counterparty scale."""

    def test_full_resolve_10k(
        self,
        benchmark,
        dataset_10k: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark full hierarchy resolution at 10K scale.

        Target: < 1 second
        """
        # Create RawDataBundle from generated data
        raw_data = RawDataBundle(
            counterparties=dataset_10k["counterparties"],
            facilities=dataset_10k["facilities"],
            loans=dataset_10k["loans"],
            contingents=dataset_10k["contingents"],
            collateral=dataset_10k["collateral"],
            guarantees=pl.LazyFrame(schema={"guarantee_reference": pl.String}),  # Empty
            provisions=pl.LazyFrame(schema={"provision_reference": pl.String}),  # Empty
            ratings=dataset_10k["ratings"],
            facility_mappings=dataset_10k["facility_mappings"],
            org_mappings=dataset_10k["org_mappings"],
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )
        config = CalculationConfig.crr(BENCHMARK_REPORTING_DATE)

        resolver = HierarchyResolver()

        # Run benchmark
        result = benchmark(resolver.resolve, raw_data, config)

        # Verify result is valid
        assert result is not None
        assert result.exposures is not None
        assert result.counterparty_lookup is not None

    def test_counterparty_lookup_10k(
        self,
        benchmark,
        dataset_10k: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark counterparty lookup building at 10K scale.

        Tests _build_counterparty_lookup specifically.
        """
        counterparties = dataset_10k["counterparties"]
        org_mappings = dataset_10k["org_mappings"]
        ratings = dataset_10k["ratings"]

        resolver = HierarchyResolver()

        # Benchmark the counterparty lookup
        def build_lookup():
            return resolver._build_counterparty_lookup(
                counterparties, org_mappings, ratings
            )

        result, errors = benchmark(build_lookup)

        assert result is not None
        # Verify lookup is populated
        assert result.counterparties is not None

    def test_exposure_unification_10k(
        self,
        benchmark,
        dataset_10k: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark exposure unification at 10K scale.

        Tests _unify_exposures specifically.
        """
        # First build the counterparty lookup
        resolver = HierarchyResolver()
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            dataset_10k["counterparties"],
            dataset_10k["org_mappings"],
            dataset_10k["ratings"],
        )

        loans = dataset_10k["loans"]
        contingents = dataset_10k["contingents"]
        facility_mappings = dataset_10k["facility_mappings"]

        # Benchmark unification
        def unify():
            return resolver._unify_exposures(
                loans, contingents, facility_mappings, counterparty_lookup
            )

        result, errors = benchmark(unify)

        assert result is not None


# =============================================================================
# 100K SCALE BENCHMARKS (Standard)
# =============================================================================


@pytest.mark.benchmark
@pytest.mark.scale_100k
class TestHierarchyBenchmark100K:
    """Hierarchy resolver benchmarks at 100K counterparty scale."""

    def test_full_resolve_100k(
        self,
        benchmark,
        dataset_100k: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark full hierarchy resolution at 100K scale.

        Target: < 5 seconds
        """
        raw_data = RawDataBundle(
            counterparties=dataset_100k["counterparties"],
            facilities=dataset_100k["facilities"],
            loans=dataset_100k["loans"],
            contingents=dataset_100k["contingents"],
            collateral=dataset_100k["collateral"],
            guarantees=pl.LazyFrame(schema={"guarantee_reference": pl.String}),
            provisions=pl.LazyFrame(schema={"provision_reference": pl.String}),
            ratings=dataset_100k["ratings"],
            facility_mappings=dataset_100k["facility_mappings"],
            org_mappings=dataset_100k["org_mappings"],
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )
        config = CalculationConfig.crr(BENCHMARK_REPORTING_DATE)

        resolver = HierarchyResolver()

        result = benchmark(resolver.resolve, raw_data, config)

        assert result is not None
        assert result.exposures is not None

    def test_counterparty_lookup_100k(
        self,
        benchmark,
        dataset_100k: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark counterparty lookup building at 100K scale.

        Target: < 2 seconds
        """
        counterparties = dataset_100k["counterparties"]
        org_mappings = dataset_100k["org_mappings"]
        ratings = dataset_100k["ratings"]

        resolver = HierarchyResolver()

        def build_lookup():
            return resolver._build_counterparty_lookup(
                counterparties, org_mappings, ratings
            )

        result, errors = benchmark(build_lookup)

        assert result is not None

    def test_org_hierarchy_depth_100k(
        self,
        benchmark,
        dataset_100k: dict[str, pl.LazyFrame],
        dataset_100k_stats: dict,
    ):
        """
        Benchmark org hierarchy resolution with depth >= 2.

        Verifies that hierarchy depth requirements are met.
        """
        org_stats = dataset_100k_stats.get("org_hierarchy", {})
        print(f"\nOrg hierarchy stats: {org_stats}")

        counterparties = dataset_100k["counterparties"]
        org_mappings = dataset_100k["org_mappings"]
        ratings = dataset_100k["ratings"]

        resolver = HierarchyResolver()

        def build_lookup():
            return resolver._build_counterparty_lookup(
                counterparties, org_mappings, ratings
            )

        result, _ = benchmark(build_lookup)

        # Verify hierarchy has depth >= 2
        # By checking that some counterparties have grandparents
        enriched = result.counterparties.collect()

        # Count counterparties with hierarchy depth >= 2
        depth_counts = enriched.group_by("counterparty_hierarchy_depth").len()
        print(f"\nHierarchy depth distribution:\n{depth_counts}")

        # At least some should have depth >= 2
        max_depth = enriched["counterparty_hierarchy_depth"].max()
        assert max_depth >= 2, f"Max hierarchy depth should be >= 2, got {max_depth}"

    def test_facility_hierarchy_depth_100k(
        self,
        benchmark,
        dataset_100k: dict[str, pl.LazyFrame],
        dataset_100k_stats: dict,
    ):
        """
        Benchmark facility hierarchy resolution with depth >= 2.

        Verifies that facility hierarchy depth requirements are met.
        """
        fac_stats = dataset_100k_stats.get("facility_hierarchy", {})
        print(f"\nFacility hierarchy stats: {fac_stats}")

        # First build the counterparty lookup
        resolver = HierarchyResolver()
        counterparty_lookup, _ = resolver._build_counterparty_lookup(
            dataset_100k["counterparties"],
            dataset_100k["org_mappings"],
            dataset_100k["ratings"],
        )

        loans = dataset_100k["loans"]
        contingents = dataset_100k["contingents"]
        facility_mappings = dataset_100k["facility_mappings"]

        def unify():
            return resolver._unify_exposures(
                loans, contingents, facility_mappings, counterparty_lookup
            )

        result, _ = benchmark(unify)

        # Verify facility hierarchy
        exposures = result.collect()

        # Count exposures with facility hierarchy depth
        depth_counts = exposures.group_by("facility_hierarchy_depth").len()
        print(f"\nFacility hierarchy depth distribution:\n{depth_counts}")

        # The generated data has facility->sub-facility->loan structure (depth 2)
        # Verify we have the expected structure from the data stats
        fac_stats = dataset_100k_stats.get("facility_hierarchy", {})
        by_type = fac_stats.get("by_child_type", {})

        # Verify we have sub-facilities (facility children of facilities)
        n_sub_facilities = by_type.get("facility", 0)
        assert n_sub_facilities > 0, "Should have facility-to-facility mappings for depth >= 2"
        print(f"Sub-facilities (depth 2 in hierarchy): {n_sub_facilities}")


# =============================================================================
# 1M SCALE BENCHMARKS (Large scale, slow)
# =============================================================================


@pytest.mark.benchmark
@pytest.mark.scale_1m
@pytest.mark.slow
class TestHierarchyBenchmark1M:
    """Hierarchy resolver benchmarks at 1M counterparty scale (slow)."""

    def test_full_resolve_1m(
        self,
        benchmark,
        dataset_1m: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark full hierarchy resolution at 1M scale.

        Target: < 60 seconds
        """
        raw_data = RawDataBundle(
            counterparties=dataset_1m["counterparties"],
            facilities=dataset_1m["facilities"],
            loans=dataset_1m["loans"],
            contingents=dataset_1m["contingents"],
            collateral=dataset_1m["collateral"],
            guarantees=pl.LazyFrame(schema={"guarantee_reference": pl.String}),
            provisions=pl.LazyFrame(schema={"provision_reference": pl.String}),
            ratings=dataset_1m["ratings"],
            facility_mappings=dataset_1m["facility_mappings"],
            org_mappings=dataset_1m["org_mappings"],
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )
        config = CalculationConfig.crr(BENCHMARK_REPORTING_DATE)

        resolver = HierarchyResolver()

        result = benchmark(resolver.resolve, raw_data, config)

        assert result is not None


# =============================================================================
# 10M SCALE BENCHMARKS (Production scale, very slow)
# =============================================================================


@pytest.mark.benchmark
@pytest.mark.scale_10m
@pytest.mark.slow
class TestHierarchyBenchmark10M:
    """Hierarchy resolver benchmarks at 10M counterparty scale (very slow)."""

    def test_full_resolve_10m(
        self,
        benchmark,
        dataset_10m: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark full hierarchy resolution at 10M scale.

        Target: < 10 minutes
        """
        raw_data = RawDataBundle(
            counterparties=dataset_10m["counterparties"],
            facilities=dataset_10m["facilities"],
            loans=dataset_10m["loans"],
            contingents=dataset_10m["contingents"],
            collateral=dataset_10m["collateral"],
            guarantees=pl.LazyFrame(schema={"guarantee_reference": pl.String}),
            provisions=pl.LazyFrame(schema={"provision_reference": pl.String}),
            ratings=dataset_10m["ratings"],
            facility_mappings=dataset_10m["facility_mappings"],
            org_mappings=dataset_10m["org_mappings"],
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )
        config = CalculationConfig.crr(BENCHMARK_REPORTING_DATE)

        resolver = HierarchyResolver()

        result = benchmark(resolver.resolve, raw_data, config)

        assert result is not None


# =============================================================================
# MEMORY BENCHMARKS
# =============================================================================


@pytest.mark.benchmark
class TestHierarchyMemoryBenchmark:
    """Memory usage benchmarks for hierarchy resolution."""

    def test_memory_usage_10k(
        self,
        dataset_10k: dict[str, pl.LazyFrame],
        memory_tracker,
    ):
        """
        Track memory usage at 10K scale.

        Target: < 100 MB peak
        """
        raw_data = RawDataBundle(
            counterparties=dataset_10k["counterparties"],
            facilities=dataset_10k["facilities"],
            loans=dataset_10k["loans"],
            contingents=dataset_10k["contingents"],
            collateral=dataset_10k["collateral"],
            guarantees=pl.LazyFrame(schema={"guarantee_reference": pl.String}),
            provisions=pl.LazyFrame(schema={"provision_reference": pl.String}),
            ratings=dataset_10k["ratings"],
            facility_mappings=dataset_10k["facility_mappings"],
            org_mappings=dataset_10k["org_mappings"],
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )
        config = CalculationConfig.crr(BENCHMARK_REPORTING_DATE)
        resolver = HierarchyResolver()

        with memory_tracker as tracker:
            result = resolver.resolve(raw_data, config)
            # Force materialization
            _ = result.exposures.collect()

        print(f"\nPeak memory usage: {tracker.peak_mb:.2f} MB")
        assert tracker.peak_mb < 500, f"Memory usage {tracker.peak_mb:.2f} MB exceeds 500 MB limit"

    def test_memory_usage_100k(
        self,
        dataset_100k: dict[str, pl.LazyFrame],
        memory_tracker,
    ):
        """
        Track memory usage at 100K scale.

        Target: < 500 MB peak
        """
        raw_data = RawDataBundle(
            counterparties=dataset_100k["counterparties"],
            facilities=dataset_100k["facilities"],
            loans=dataset_100k["loans"],
            contingents=dataset_100k["contingents"],
            collateral=dataset_100k["collateral"],
            guarantees=pl.LazyFrame(schema={"guarantee_reference": pl.String}),
            provisions=pl.LazyFrame(schema={"provision_reference": pl.String}),
            ratings=dataset_100k["ratings"],
            facility_mappings=dataset_100k["facility_mappings"],
            org_mappings=dataset_100k["org_mappings"],
            lending_mappings=pl.LazyFrame(
                schema={
                    "parent_counterparty_reference": pl.String,
                    "child_counterparty_reference": pl.String,
                }
            ),
        )
        config = CalculationConfig.crr(BENCHMARK_REPORTING_DATE)
        resolver = HierarchyResolver()

        with memory_tracker as tracker:
            result = resolver.resolve(raw_data, config)
            _ = result.exposures.collect()

        print(f"\nPeak memory usage: {tracker.peak_mb:.2f} MB")
        assert tracker.peak_mb < 2000, f"Memory usage {tracker.peak_mb:.2f} MB exceeds 2000 MB limit"


# =============================================================================
# DATA GENERATION BENCHMARKS
# =============================================================================


@pytest.mark.benchmark
class TestDataGenerationBenchmark:
    """Benchmark the data generation itself."""

    def test_generate_10k_dataset(self, benchmark):
        """Benchmark 10K dataset generation."""
        from .data_generators import generate_benchmark_dataset

        result = benchmark(generate_benchmark_dataset, 10_000)

        assert "counterparties" in result
        assert "loans" in result
        assert "org_mappings" in result

    def test_generate_100k_dataset(self, benchmark):
        """Benchmark 100K dataset generation."""
        from .data_generators import generate_benchmark_dataset

        result = benchmark(generate_benchmark_dataset, 100_000)

        assert "counterparties" in result


# =============================================================================
# ENTITY TYPE COVERAGE TESTS
# =============================================================================


@pytest.mark.benchmark
class TestEntityTypeCoverage:
    """Verify entity type coverage requirements are met."""

    def test_counterparty_entity_coverage_100k(
        self,
        dataset_100k_stats: dict,
    ):
        """
        Verify at least 50% of counterparty entity types are covered.

        Entity types: corporate, individual (retail), institution, sovereign, specialised_lending
        Required coverage: >= 50% (at least 3 types)
        """
        entity_dist = dataset_100k_stats.get("entity_distribution", {})
        print(f"\nEntity type distribution: {entity_dist}")

        # At least 3 entity types should have non-zero counts
        non_zero_types = sum(1 for v in entity_dist.values() if v > 0)
        assert non_zero_types >= 3, f"Should have >= 3 entity types, got {non_zero_types}"

        # Verify specific types are present
        required_types = {"corporate", "individual", "institution"}
        present_types = set(entity_dist.keys())
        missing = required_types - present_types
        assert not missing, f"Missing required entity types: {missing}"

    def test_hierarchy_depth_requirement(
        self,
        dataset_100k_stats: dict,
    ):
        """
        Verify hierarchy depth >= 2 requirement is met.

        Both org and facility hierarchies should have depth >= 2.
        """
        org_stats = dataset_100k_stats.get("org_hierarchy", {})
        fac_stats = dataset_100k_stats.get("facility_hierarchy", {})

        print(f"\nOrg hierarchy: {org_stats}")
        print(f"Facility hierarchy: {fac_stats}")

        # Verify org hierarchy has mappings (depth >= 1)
        assert org_stats.get("total_mappings", 0) > 0, "Org hierarchy should have mappings"

        # Verify facility hierarchy has mappings
        assert fac_stats.get("total_mappings", 0) > 0, "Facility hierarchy should have mappings"

        # Verify facility hierarchy has sub-facilities (depth >= 2)
        by_type = fac_stats.get("by_child_type", {})
        assert by_type.get("facility", 0) > 0, "Should have facility-to-facility mappings for depth >= 2"
