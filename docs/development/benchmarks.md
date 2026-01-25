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

### All Benchmarks

```bash
# Run all benchmark tests
uv run pytest tests/benchmarks/ -v

# With detailed timing
uv run pytest tests/benchmarks/ -v --tb=short
```

### By Scale

```bash
# Quick tests (10K counterparties)
uv run pytest tests/benchmarks/ -m scale_10k -v

# Standard benchmarks (100K counterparties)
uv run pytest tests/benchmarks/ -m scale_100k -v

# Large scale (1M counterparties) - slower
uv run pytest tests/benchmarks/ -m scale_1m -v

# Enterprise scale (10M counterparties) - very slow
uv run pytest tests/benchmarks/ -m scale_10m -v
```

### Skip Slow Tests

```bash
# Skip 1M+ scale tests
uv run pytest tests/benchmarks/ -m "not slow" -v

# Only memory benchmarks
uv run pytest tests/benchmarks/ -m benchmark -v
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

The IRB formula implementation uses pure Polars expressions with `polars-normal-stats` for statistical functions, enabling full lazy evaluation and streaming.

#### Performance Results

| Scale | Mean Time | Throughput |
|------:|----------:|-----------:|
| 10,000 | 7.2 ms | 1.4M rows/s |
| 100,000 | 32.3 ms | 3.1M rows/s |
| 1,000,000 | 298 ms | 3.4M rows/s |

Key benefits of the pure Polars implementation:

- **Full lazy evaluation**: Query optimization preserved throughout
- **Streaming-capable**: Datasets larger than memory can be processed
- **No data conversion**: No NumPy/SciPy overhead
- **Sub-second for 1M rows**: 1 million IRB exposures processed in ~300ms

Run the IRB formula benchmark:

```bash
uv run python tests/benchmarks/benchmark_irb_formulas.py
```

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

---

## Writing Benchmark Tests

### Basic Structure

```python
import pytest
import time

class TestMyBenchmark:
    """Benchmark tests for MyComponent."""

    @pytest.mark.scale_100k
    def test_my_component_100k(self, dataset_100k):
        """Test MyComponent at 100K scale."""
        start = time.perf_counter()

        # Run the operation
        result = my_component.process(dataset_100k)

        duration = time.perf_counter() - start

        # Assert performance target
        assert duration < 10.0, f"Expected < 10s, got {duration:.2f}s"

        # Assert correctness
        assert result.is_valid
```

### Using Dataset Generators

The benchmark tests use dataset generators that create realistic data distributions:

```python
@pytest.fixture
def dataset_100k():
    """Generate 100K counterparty dataset."""
    return generate_dataset(
        num_counterparties=100_000,
        facilities_per_counterparty=3,
        loans_per_facility=2,
    )
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
# Run quick benchmarks on every PR
benchmark-quick:
  script:
    - uv run pytest tests/benchmarks/ -m "scale_10k or scale_100k" -v

# Run full benchmarks nightly
benchmark-full:
  schedule: "0 2 * * *"  # 2 AM daily
  script:
    - uv run pytest tests/benchmarks/ -v --tb=short
```

### Performance Regression Detection

Monitor benchmark results over time to detect regressions:

```bash
# Generate benchmark report
uv run pytest tests/benchmarks/ -v --benchmark-json=benchmark.json

# Compare with baseline
uv run pytest-benchmark compare benchmark.json baseline.json
```

## Next Steps

- [Testing Guide](testing.md) - General testing documentation
- [Workbooks](workbooks.md) - Interactive UI and workbooks
- [Architecture](../architecture/pipeline.md) - Pipeline architecture details
