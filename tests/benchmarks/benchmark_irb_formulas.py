"""
Benchmark for IRB formulas implementation.

The IRB formulas use pure Polars expressions with polars-normal-stats:
- Full Polars lazy evaluation (query optimization, streaming)
- polars-normal-stats for statistical functions (normal_cdf, normal_ppf)
- No scipy/numpy dependency in production code

This benchmark demonstrates performance at various scales.

Run with:
    uv run python tests/benchmarks/benchmark_irb_formulas.py
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from datetime import date

import numpy as np  # For test data generation only
import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb.formulas import apply_irb_formulas


@dataclass
class BenchmarkResult:
    """Result from a benchmark run."""
    n_rows: int
    times: list[float]
    mean_time: float
    std_dev: float
    min_time: float
    max_time: float


def generate_irb_exposure_data(n_rows: int, seed: int = 42) -> pl.LazyFrame:
    """
    Generate synthetic IRB exposure data for benchmarking.

    Args:
        n_rows: Number of exposure rows to generate
        seed: Random seed for reproducibility

    Returns:
        LazyFrame with IRB exposure data
    """
    rng = np.random.default_rng(seed)

    # Generate PDs with realistic distribution
    pd_base = rng.uniform(0.0003, 0.05, size=n_rows)

    # Generate LGDs
    lgd_values = rng.choice([0.25, 0.35, 0.45, 0.55, 0.75], size=n_rows, p=[0.1, 0.15, 0.50, 0.15, 0.1])

    # Generate EADs
    ead_values = rng.uniform(10_000, 10_000_000, size=n_rows)

    # Generate exposure classes
    exposure_classes = rng.choice(
        ["CORPORATE", "CORPORATE_SME", "RETAIL_MORTGAGE", "RETAIL_OTHER", "INSTITUTION"],
        size=n_rows,
        p=[0.40, 0.25, 0.15, 0.10, 0.10]
    )

    # Generate maturities
    maturities = rng.uniform(1.0, 5.0, size=n_rows)

    # Generate turnover for SME adjustment
    turnover_m = rng.uniform(1, 100, size=n_rows)
    turnover_m = np.where(
        np.char.find(exposure_classes.astype(str), "CORPORATE") >= 0,
        turnover_m,
        np.nan
    )

    return pl.DataFrame({
        "exposure_reference": [f"EXP_{i:08d}" for i in range(n_rows)],
        "pd": pd_base,
        "lgd": lgd_values,
        "ead_final": ead_values,
        "exposure_class": exposure_classes,
        "maturity": maturities,
        "turnover_m": turnover_m,
    }).lazy()


def run_benchmark(
    data: pl.LazyFrame,
    config: CalculationConfig,
    n_runs: int = 5,
    warmup_runs: int = 2,
) -> BenchmarkResult:
    """
    Run benchmark for the IRB formulas implementation.

    Args:
        data: Input LazyFrame
        config: Calculation configuration
        n_runs: Number of timed runs
        warmup_runs: Number of warmup runs

    Returns:
        BenchmarkResult with timing statistics
    """
    # Warmup
    for _ in range(warmup_runs):
        _ = apply_irb_formulas(data, config).collect()

    # Timed runs
    times = []
    for _ in range(n_runs):
        start = time.perf_counter()
        _ = apply_irb_formulas(data, config).collect()
        times.append(time.perf_counter() - start)

    n_rows = data.collect().height

    return BenchmarkResult(
        n_rows=n_rows,
        times=times,
        mean_time=statistics.mean(times),
        std_dev=statistics.stdev(times) if len(times) > 1 else 0.0,
        min_time=min(times),
        max_time=max(times),
    )


def main():
    """Run the IRB formulas benchmark."""
    print("=" * 70)
    print("IRB Formulas Benchmark (Pure Polars with polars-normal-stats)")
    print("=" * 70)
    print()
    print("Implementation: Pure Polars expressions + polars-normal-stats")
    print("Benefits:")
    print("  - Full lazy evaluation (query optimization, streaming)")
    print("  - No scipy/numpy dependency in production code")
    print("  - Enables streaming for large datasets")
    print()

    row_counts = [1_000, 10_000, 100_000]
    n_runs = 5
    warmup_runs = 2

    config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))

    results = []

    for n_rows in row_counts:
        print(f"Benchmarking {n_rows:,} rows...")
        data = generate_irb_exposure_data(n_rows)
        result = run_benchmark(data, config, n_runs=n_runs, warmup_runs=warmup_runs)
        results.append(result)
        print(f"  Mean: {result.mean_time * 1000:.1f} ms, Std: {result.std_dev * 1000:.1f} ms")

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"{'Rows':>12} | {'Mean (ms)':>10} | {'Std (ms)':>10} | {'Throughput':>15}")
    print("-" * 55)

    for r in results:
        throughput = r.n_rows / r.mean_time
        print(
            f"{r.n_rows:>12,} | "
            f"{r.mean_time * 1000:>10.1f} | "
            f"{r.std_dev * 1000:>10.1f} | "
            f"{throughput:>12,.0f} rows/s"
        )

    print()
    print("Implementation details:")
    print("  - Correlation: Pure Polars expressions (exposure class dependent)")
    print("  - Capital K: polars-normal-stats (normal_ppf/normal_cdf)")
    print("  - Maturity Adjustment: Pure Polars expressions")
    print("  - RWA/Risk Weight/EL: Pure Polars expressions")
    print("  - Full lazy evaluation preserved throughout")


if __name__ == "__main__":
    main()
