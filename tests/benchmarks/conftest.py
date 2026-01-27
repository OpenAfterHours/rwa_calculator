"""
Benchmark test fixtures and configuration.

Provides pytest fixtures for benchmark testing at various scales:
- 10K: Quick validation (~1s)
- 100K: Standard benchmark (~5s)
- 1M: Large scale (~60s)
- 10M: Production scale (~10min, slow marker)

Dataset Caching:
- Datasets are cached to parquet files in tests/benchmarks/data/
- By default, cached datasets are loaded for fast benchmark runs
- Use --benchmark-regenerate to force regeneration of all datasets
- Use --benchmark-regenerate-scale=10k to regenerate a specific scale

Usage:
    # Normal run (uses cached data)
    uv run pytest tests/benchmarks/ --benchmark-only

    # Force regenerate all datasets
    uv run pytest tests/benchmarks/ --benchmark-only --benchmark-regenerate

    # Force regenerate specific scale
    uv run pytest tests/benchmarks/ --benchmark-only --benchmark-regenerate-scale=100k
"""

import logging

import pytest
import polars as pl

from tests.benchmarks.data_generators import (
    BenchmarkDataConfig,
    generate_benchmark_dataset,
    get_dataset_statistics,
    get_or_create_dataset,
)

# Configure logging for benchmark data generation
logger = logging.getLogger("rwa_calc.benchmarks")


# =============================================================================
# PYTEST COMMAND-LINE OPTIONS
# =============================================================================


def pytest_addoption(parser):
    """Add benchmark-specific command-line options."""
    parser.addoption(
        "--benchmark-regenerate",
        action="store_true",
        default=False,
        help="Force regeneration of all cached benchmark datasets",
    )
    parser.addoption(
        "--benchmark-regenerate-scale",
        action="store",
        default=None,
        help="Force regeneration of a specific scale (10k, 100k, 1m, 10m)",
    )


@pytest.fixture(scope="session")
def force_regenerate(request) -> bool:
    """Get the global regenerate flag from command line."""
    return request.config.getoption("--benchmark-regenerate")


@pytest.fixture(scope="session")
def regenerate_scale(request) -> str | None:
    """Get the specific scale to regenerate from command line."""
    return request.config.getoption("--benchmark-regenerate-scale")


def should_regenerate(force_all: bool, scale: str | None, current_scale: str) -> bool:
    """Determine if a specific scale should be regenerated."""
    if force_all:
        return True
    if scale is not None and scale.lower() == current_scale.lower():
        return True
    return False


# =============================================================================
# CONFIGURATION FIXTURES
# =============================================================================


@pytest.fixture(scope="session")
def benchmark_config_10k() -> BenchmarkDataConfig:
    """Configuration for 10K counterparty benchmark (quick validation)."""
    return BenchmarkDataConfig(
        n_counterparties=10_000,
        hierarchy_depth=3,
        loans_per_counterparty=3,
        seed=42,
    )


@pytest.fixture(scope="session")
def benchmark_config_100k() -> BenchmarkDataConfig:
    """Configuration for 100K counterparty benchmark (standard)."""
    return BenchmarkDataConfig(
        n_counterparties=100_000,
        hierarchy_depth=3,
        loans_per_counterparty=3,
        seed=42,
    )


@pytest.fixture(scope="session")
def benchmark_config_1m() -> BenchmarkDataConfig:
    """Configuration for 1M counterparty benchmark (large scale)."""
    return BenchmarkDataConfig(
        n_counterparties=1_000_000,
        hierarchy_depth=4,
        loans_per_counterparty=3,
        seed=42,
    )


@pytest.fixture(scope="session")
def benchmark_config_10m() -> BenchmarkDataConfig:
    """Configuration for 10M counterparty benchmark (production scale)."""
    return BenchmarkDataConfig(
        n_counterparties=10_000_000,
        hierarchy_depth=4,
        loans_per_counterparty=3,
        seed=42,
    )


# =============================================================================
# DATASET FIXTURES - 10K Scale
# =============================================================================


@pytest.fixture(scope="session")
def dataset_10k(
    benchmark_config_10k: BenchmarkDataConfig,
    force_regenerate: bool,
    regenerate_scale: str | None,
) -> dict[str, pl.LazyFrame]:
    """Load or generate 10K scale benchmark dataset."""
    regenerate = should_regenerate(force_regenerate, regenerate_scale, "10k")
    return get_or_create_dataset(
        scale="10k",
        n_counterparties=benchmark_config_10k.n_counterparties,
        hierarchy_depth=benchmark_config_10k.hierarchy_depth,
        seed=benchmark_config_10k.seed,
        force_regenerate=regenerate,
    )


@pytest.fixture(scope="session")
def dataset_10k_stats(dataset_10k: dict[str, pl.LazyFrame]) -> dict:
    """Statistics for 10K dataset."""
    return get_dataset_statistics(dataset_10k)


# =============================================================================
# DATASET FIXTURES - 100K Scale
# =============================================================================


@pytest.fixture(scope="session")
def dataset_100k(
    benchmark_config_100k: BenchmarkDataConfig,
    force_regenerate: bool,
    regenerate_scale: str | None,
) -> dict[str, pl.LazyFrame]:
    """Load or generate 100K scale benchmark dataset."""
    regenerate = should_regenerate(force_regenerate, regenerate_scale, "100k")
    return get_or_create_dataset(
        scale="100k",
        n_counterparties=benchmark_config_100k.n_counterparties,
        hierarchy_depth=benchmark_config_100k.hierarchy_depth,
        seed=benchmark_config_100k.seed,
        force_regenerate=regenerate,
    )


@pytest.fixture(scope="session")
def dataset_100k_stats(dataset_100k: dict[str, pl.LazyFrame]) -> dict:
    """Statistics for 100K dataset."""
    return get_dataset_statistics(dataset_100k)


# =============================================================================
# DATASET FIXTURES - 1M Scale (requires --benchmark-enable-slow)
# =============================================================================


@pytest.fixture(scope="session")
def dataset_1m(
    benchmark_config_1m: BenchmarkDataConfig,
    force_regenerate: bool,
    regenerate_scale: str | None,
) -> dict[str, pl.LazyFrame]:
    """Load or generate 1M scale benchmark dataset."""
    regenerate = should_regenerate(force_regenerate, regenerate_scale, "1m")
    return get_or_create_dataset(
        scale="1m",
        n_counterparties=benchmark_config_1m.n_counterparties,
        hierarchy_depth=benchmark_config_1m.hierarchy_depth,
        seed=benchmark_config_1m.seed,
        force_regenerate=regenerate,
    )


@pytest.fixture(scope="session")
def dataset_1m_stats(dataset_1m: dict[str, pl.LazyFrame]) -> dict:
    """Statistics for 1M dataset."""
    return get_dataset_statistics(dataset_1m)


# =============================================================================
# DATASET FIXTURES - 10M Scale (requires --benchmark-enable-slow)
# =============================================================================


@pytest.fixture(scope="session")
def dataset_10m(
    benchmark_config_10m: BenchmarkDataConfig,
    force_regenerate: bool,
    regenerate_scale: str | None,
) -> dict[str, pl.LazyFrame]:
    """Load or generate 10M scale benchmark dataset."""
    regenerate = should_regenerate(force_regenerate, regenerate_scale, "10m")
    return get_or_create_dataset(
        scale="10m",
        n_counterparties=benchmark_config_10m.n_counterparties,
        hierarchy_depth=benchmark_config_10m.hierarchy_depth,
        seed=benchmark_config_10m.seed,
        force_regenerate=regenerate,
    )


@pytest.fixture(scope="session")
def dataset_10m_stats(dataset_10m: dict[str, pl.LazyFrame]) -> dict:
    """Statistics for 10M dataset."""
    return get_dataset_statistics(dataset_10m)


# =============================================================================
# COLLECTED DATA FIXTURES (Eager DataFrames for benchmark functions)
# =============================================================================


@pytest.fixture(scope="session")
def counterparties_10k(dataset_10k: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    """Collected counterparties for 10K benchmark."""
    return dataset_10k["counterparties"].collect()


@pytest.fixture(scope="session")
def counterparties_100k(dataset_100k: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    """Collected counterparties for 100K benchmark."""
    return dataset_100k["counterparties"].collect()


@pytest.fixture(scope="session")
def loans_10k(dataset_10k: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    """Collected loans for 10K benchmark."""
    return dataset_10k["loans"].collect()


@pytest.fixture(scope="session")
def loans_100k(dataset_100k: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    """Collected loans for 100K benchmark."""
    return dataset_100k["loans"].collect()


@pytest.fixture(scope="session")
def org_mappings_10k(dataset_10k: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    """Collected org_mappings for 10K benchmark."""
    return dataset_10k["org_mappings"].collect()


@pytest.fixture(scope="session")
def org_mappings_100k(dataset_100k: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    """Collected org_mappings for 100K benchmark."""
    return dataset_100k["org_mappings"].collect()


@pytest.fixture(scope="session")
def facility_mappings_10k(dataset_10k: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    """Collected facility_mappings for 10K benchmark."""
    return dataset_10k["facility_mappings"].collect()


@pytest.fixture(scope="session")
def facility_mappings_100k(dataset_100k: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    """Collected facility_mappings for 100K benchmark."""
    return dataset_100k["facility_mappings"].collect()


@pytest.fixture(scope="session")
def ratings_10k(dataset_10k: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    """Collected ratings for 10K benchmark."""
    return dataset_10k["ratings"].collect()


@pytest.fixture(scope="session")
def ratings_100k(dataset_100k: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    """Collected ratings for 100K benchmark."""
    return dataset_100k["ratings"].collect()


# =============================================================================
# HELPER FIXTURES
# =============================================================================


@pytest.fixture
def memory_tracker():
    """
    Context manager for tracking memory usage during benchmark.

    Usage:
        def test_memory(memory_tracker):
            with memory_tracker as tracker:
                # do work
            assert tracker.peak_mb < 500
    """
    import tracemalloc

    class MemoryTracker:
        def __init__(self):
            self.peak_mb = 0
            self.current_mb = 0

        def __enter__(self):
            tracemalloc.start()
            return self

        def __exit__(self, *args):
            current, peak = tracemalloc.get_traced_memory()
            self.current_mb = current / (1024 * 1024)
            self.peak_mb = peak / (1024 * 1024)
            tracemalloc.stop()

    return MemoryTracker()


# =============================================================================
# PYTEST CONFIGURATION
# =============================================================================


def pytest_configure(config):
    """Add custom markers for benchmark tests."""
    config.addinivalue_line(
        "markers",
        "benchmark: mark test as a benchmark (deselect with --benchmark-skip)",
    )
    config.addinivalue_line(
        "markers",
        "slow: mark test as slow (10M+ scale, may take several minutes)",
    )
    config.addinivalue_line(
        "markers",
        "scale_10k: benchmark at 10K counterparty scale",
    )
    config.addinivalue_line(
        "markers",
        "scale_100k: benchmark at 100K counterparty scale",
    )
    config.addinivalue_line(
        "markers",
        "scale_1m: benchmark at 1M counterparty scale",
    )
    config.addinivalue_line(
        "markers",
        "scale_10m: benchmark at 10M counterparty scale",
    )
