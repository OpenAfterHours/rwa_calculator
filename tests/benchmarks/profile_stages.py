"""Profile full pipeline stages to find bottlenecks."""
from __future__ import annotations
import time
from datetime import date
import polars as pl
from tests.benchmarks.data_generators import get_or_create_dataset
from tests.benchmarks.test_pipeline_benchmark import create_raw_data_bundle
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.engine.pipeline import PipelineOrchestrator

REPORTING_DATE = date(2026, 1, 1)
RUNS = 8

print("Generating 100K dataset...")
dataset = get_or_create_dataset(
    scale="100k", n_counterparties=100_000, hierarchy_depth=3, seed=42,
)
raw_data = create_raw_data_bundle(dataset)
config = CalculationConfig.crr(
    REPORTING_DATE, irb_permissions=IRBPermissions.full_irb(),
)

pipeline = PipelineOrchestrator()

print(f"\nFull pipeline (CRR 100K) — {RUNS} runs:")
times = []
for i in range(RUNS):
    t0 = time.perf_counter()
    result = pipeline.run_with_data(raw_data, config)
    elapsed = time.perf_counter() - t0
    times.append(elapsed)
    print(f"  run {i+1}: {elapsed*1000:.0f}ms")

mean = sum(times) / len(times)
best = min(times)
worst = max(times)
print(f"\n  mean: {mean*1000:.0f}ms  best: {best*1000:.0f}ms  worst: {worst*1000:.0f}ms")
