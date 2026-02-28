# Benchmark Tests

This guide covers the performance and scale testing infrastructure for validating calculator performance from 10K to 10M counterparties.

## Overview

Benchmark tests validate that the RWA calculator meets performance requirements at various scales. The tests cover:

- **Hierarchy Resolution** - Building counterparty and facility hierarchies
- **Pipeline Execution** - End-to-end RWA calculation
- **Memory Usage** - Peak memory consumption at scale
- **Component Performance** - Individual calculator components

## Test Structure

```
tests/benchmarks/
├── test_hierarchy_benchmark.py   # HierarchyResolver performance
└── test_pipeline_benchmark.py    # End-to-end pipeline performance
```

## Running Benchmarks

Benchmark tests are marked with `@pytest.mark.benchmark` and are skipped by default (`--benchmark-skip` in pyproject.toml). Use `--benchmark-only` or override `addopts` to run them.

### All Benchmarks (10K + 100K)

```bash
# Run all benchmarks except 1M/10M (recommended)
uv run pytest tests/benchmarks/ -m "benchmark and not slow" -k "not 1m and not 1M" -o "addopts=" --benchmark-only -v

# With detailed timing on failure
uv run pytest tests/benchmarks/ -m "benchmark and not slow" -k "not 1m" -o "addopts=" --benchmark-only -v --tb=short
```

### By Scale

```bash
# Quick tests (10K counterparties)
uv run pytest tests/benchmarks/ -m scale_10k -o "addopts=" --benchmark-only -v

# Standard benchmarks (100K counterparties)
uv run pytest tests/benchmarks/ -m scale_100k -o "addopts=" --benchmark-only -v

# Large scale (1M counterparties) - requires significant memory
uv run pytest tests/benchmarks/ -m scale_1m -o "addopts=" --benchmark-only -v

# Enterprise scale (10M counterparties) - very slow
uv run pytest tests/benchmarks/ -m scale_10m -o "addopts=" --benchmark-only -v
```

### Skip Slow Tests

```bash
# Skip 1M+ scale tests (default recommendation)
uv run pytest tests/benchmarks/ -m "benchmark and not slow" -o "addopts=" --benchmark-only -v
```

### Profiling Scripts

In addition to pytest benchmarks, standalone profiling scripts provide stage-by-stage breakdowns:

```bash
# Full pipeline stage breakdown (hierarchy → classifier → CRM → calculators)
uv run python -m tests.benchmarks.profile_stage_breakdown

# Hierarchy and classifier sub-stage profiling
uv run python -m tests.benchmarks.profile_hierarchy_classifier
```

## Test Markers

| Marker | Description | Typical Duration |
|--------|-------------|------------------|
| `@pytest.mark.scale_10k` | 10K counterparty tests | < 5 seconds |
| `@pytest.mark.scale_100k` | 100K counterparty tests | < 30 seconds |
| `@pytest.mark.scale_1m` | 1M counterparty tests | < 5 minutes |
| `@pytest.mark.scale_10m` | 10M counterparty tests | < 30 minutes |
| `@pytest.mark.slow` | Long-running tests (1M+) | Minutes |
| `@pytest.mark.benchmark` | Memory/performance benchmarks | Varies |

---

## Hierarchy Benchmarks

Tests for `HierarchyResolver` performance at scale.

### Test Classes

#### `TestHierarchyBenchmark10K`

Quick validation tests at 10K scale:

| Test | Target | Description |
|------|--------|-------------|
| `test_full_resolve_10k` | < 1 sec | Full hierarchy resolution |
| `test_counterparty_lookup_10k` | - | Counterparty lookup building |
| `test_exposure_unification_10k` | - | Exposure unification |

#### `TestHierarchyBenchmark100K`

Standard benchmark at 100K scale:

| Test | Target | Description |
|------|--------|-------------|
| `test_full_resolve_100k` | < 5 sec | Full hierarchy resolution |
| `test_counterparty_lookup_100k` | < 2 sec | Counterparty lookup building |
| `test_org_hierarchy_depth_100k` | - | Verify hierarchy depth >= 2 |
| `test_facility_hierarchy_depth_100k` | - | Verify facility depth >= 2 |

#### `TestHierarchyBenchmark1M`

Large scale tests (marked `@pytest.mark.slow`):

| Test | Target | Description |
|------|--------|-------------|
| `test_full_resolve_1m` | < 60 sec | Full hierarchy resolution |

#### `TestHierarchyBenchmark10M`

Enterprise scale tests (marked `@pytest.mark.slow`):

| Test | Target | Description |
|------|--------|-------------|
| `test_full_resolve_10m` | < 10 min | Full hierarchy resolution |

#### `TestHierarchyMemoryBenchmark`

Memory consumption tests:

| Test | Target | Description |
|------|--------|-------------|
| `test_memory_usage_10k` | < 100 MB | Peak memory at 10K |
| `test_memory_usage_100k` | < 500 MB | Peak memory at 100K |

---

## Pipeline Benchmarks

End-to-end RWA calculation pipeline performance.

### Test Classes

#### `TestPipelineBenchmark10K`

Quick pipeline validation:

| Test | Target | Description |
|------|--------|-------------|
| `test_full_pipeline_sa_10k` | < 2 sec | SA-only calculation |
| `test_full_pipeline_crr_10k` | < 3 sec | SA + IRB calculation |

#### `TestPipelineBenchmark100K`

Standard pipeline benchmarks:

| Test | Target | Description |
|------|--------|-------------|
| `test_full_pipeline_sa_100k` | < 10 sec | SA-only calculation |
| `test_full_pipeline_crr_100k` | < 15 sec | SA + IRB calculation |
| `test_pipeline_throughput_100k` | - | Measures exposures/second |

#### `TestPipelineBenchmark1M`

Large scale pipeline tests:

| Test | Target | Description |
|------|--------|-------------|
| `test_full_pipeline_sa_1m` | < 120 sec | SA-only at 1M scale |

#### `TestPipelineBenchmark10M`

Enterprise scale pipeline tests:

| Test | Target | Description |
|------|--------|-------------|
| `test_full_pipeline_sa_10m` | < 20 min | SA-only at 10M scale |

### Approach-Specific Benchmarks

Tests at 100K scale for different calculation approaches:

#### `TestApproachBenchmarks100K`

| Test | Description |
|------|-------------|
| `test_sa_only_100k` | All exposures use SA (no IRB) |
| `test_full_irb_100k` | All eligible exposures use IRB |
| `test_irb_with_slotting_100k` | IRB + Slotting approach |
| `test_partial_irb_corporate_only_100k` | Corporate-only IRB |
| `test_basel_3_1_with_output_floor_100k` | Basel 3.1 with output floor |

#### `TestApproachBenchmarks1M`

| Test | Description |
|------|-------------|
| `test_sa_only_1m` | SA-only at 1M scale |
| `test_full_irb_1m` | Full IRB at 1M scale |
| `test_irb_with_slotting_1m` | IRB + Slotting at 1M scale |

### Component Benchmarks

Individual component performance at 100K scale:

#### `TestComponentBenchmarks100K`

| Test | Description |
|------|-------------|
| `test_classifier_100k` | Exposure classifier performance |
| `test_sa_calculator_100k` | SA calculator performance |

### IRB Formula Benchmarks

The IRB formula implementation uses pure Polars expressions with `polars-normal-stats` for statistical functions, enabling full lazy evaluation.

Key benefits of the pure Polars implementation:

- **Full lazy evaluation**: Query optimization preserved throughout
- **No data conversion**: No NumPy/SciPy overhead
- **Sub-second for 1M rows**: 1 million IRB exposures processed in ~300ms

### Memory Benchmarks

#### `TestPipelineMemoryBenchmark`

| Test | Target | Description |
|------|--------|-------------|
| `test_pipeline_memory_100k` | < 2 GB | Peak memory during pipeline |

---

## Performance Targets Summary

### Hierarchy Resolution

| Scale | Target Time | Memory |
|-------|-------------|--------|
| 10K | < 1 sec | < 100 MB |
| 100K | < 5 sec | < 500 MB |
| 1M | < 60 sec | - |
| 10M | < 10 min | - |

### Pipeline Execution

| Scale | SA Only | SA + IRB |
|-------|---------|----------|
| 10K | < 2 sec | < 3 sec |
| 100K | < 10 sec | < 15 sec |
| 1M | < 120 sec | - |
| 10M | < 20 min | - |

### Measured Results (100K, v0.1.28)

Results from `pytest-benchmark` on a typical development machine (100K counterparties, ~365K exposures):

| Test | Min (ms) | Mean (ms) |
|------|----------|-----------|
| Hierarchy resolve | 67 | 72 |
| Counterparty lookup | 45 | 51 |
| Exposure unification | 19 | 22 |
| Classifier | 730 | 757 |
| SA calculator | 271 | 310 |
| **Full pipeline (SA only)** | **1,611** | **1,710** |
| **Full pipeline (CRR)** | **1,848** | **1,931** |
| Full pipeline (IRB + slotting) | 2,092 | 2,210 |
| Basel 3.1 with output floor | 2,058 | 2,110 |

#### Pipeline Stage Breakdown (from profiler)

| Stage | Best (ms) | Mean (ms) |
|-------|-----------|-----------|
| Hierarchy | 383 | 400 |
| Classifier | 212 | 230 |
| CRM | 669 | 710 |
| Calculators (SA+IRB+Slotting) | 309 | 340 |
| **Total (stages)** | **1,634** | **1,774** |

---

## Writing Benchmark Tests

### Basic Structure

Tests use the `pytest-benchmark` fixture for accurate timing with multiple rounds:

```python
import pytest

@pytest.mark.benchmark
@pytest.mark.scale_100k
class TestMyBenchmark:
    """Benchmark tests for MyComponent."""

    def test_my_component_100k(self, benchmark, dataset_100k):
        """Benchmark MyComponent at 100K scale."""
        raw_data = create_raw_data_bundle(dataset_100k)
        config = CalculationConfig.crr(date(2026, 1, 1))

        def run():
            result = my_component.process(raw_data, config)
            _ = result.collect()  # Force lazy evaluation
            return result

        result = benchmark(run)
        assert result is not None
```

### Using Dataset Generators

The benchmark tests use dataset generators with cached parquet files for fast loading. Datasets are cached in `tests/benchmarks/data/` and regenerated only when `--benchmark-regenerate` is passed:

```python
# Session-scoped fixture — generates once, cached to parquet
@pytest.fixture(scope="session")
def dataset_100k():
    """Load or generate 100K counterparty dataset."""
    return get_or_create_dataset(
        scale="100k",
        n_counterparties=100_000,
        hierarchy_depth=3,
        seed=42,
    )
```

To regenerate cached datasets:

```bash
# Regenerate all cached datasets
uv run pytest tests/benchmarks/ -o "addopts=" --benchmark-only --benchmark-regenerate -v

# Regenerate specific scale only
uv run pytest tests/benchmarks/ -o "addopts=" --benchmark-only --benchmark-regenerate-scale=100k -v
```

### Memory Testing

```python
import tracemalloc

@pytest.mark.benchmark
def test_memory_usage(self, dataset):
    """Test memory consumption."""
    tracemalloc.start()

    # Run operation
    result = component.process(dataset)

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak / 1024 / 1024
    assert peak_mb < 500, f"Expected < 500 MB, got {peak_mb:.1f} MB"
```

---

## CI/CD Integration

### Recommended CI Configuration

```yaml
# Run quick benchmarks on every PR (10K + 100K, excludes 1M/10M)
benchmark-quick:
  script:
    - uv run pytest tests/benchmarks/ -m "benchmark and not slow" -k "not 1m" -o "addopts=" --benchmark-only -v

# Run full benchmarks nightly (includes 1M)
benchmark-full:
  schedule: "0 2 * * *"  # 2 AM daily
  script:
    - uv run pytest tests/benchmarks/ -m "benchmark and not slow" -o "addopts=" --benchmark-only -v --tb=short
```

### Performance Regression Detection

Monitor benchmark results over time to detect regressions:

```bash
# Generate benchmark report
uv run pytest tests/benchmarks/ -m "benchmark and not slow" -k "not 1m" -o "addopts=" --benchmark-only --benchmark-json=benchmark.json

# Compare with baseline
uv run pytest-benchmark compare benchmark.json baseline.json
```

## Next Steps

- [Testing Guide](testing.md) - General testing documentation
- [Workbooks](workbooks.md) - Interactive UI and workbooks
- [Architecture](../architecture/pipeline.md) - Pipeline architecture details
