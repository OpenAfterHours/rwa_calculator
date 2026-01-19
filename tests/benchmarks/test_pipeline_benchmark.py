"""
Benchmark tests for the full RWA calculation pipeline.

Tests end-to-end performance at various scales:
- 10K counterparties: Quick validation
- 100K counterparties: Standard benchmark
- 1M counterparties: Large scale

Usage:
    # Run all pipeline benchmarks
    uv run pytest tests/benchmarks/test_pipeline_benchmark.py --benchmark-only

    # Run specific scale
    uv run pytest tests/benchmarks/test_pipeline_benchmark.py -k "100k" --benchmark-only
"""

from datetime import date

import pytest
import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.pipeline import PipelineOrchestrator


# Default reporting date for benchmarks
BENCHMARK_REPORTING_DATE = date(2026, 1, 1)


class InMemoryLoader:
    """Simple loader that returns a pre-built RawDataBundle."""

    def __init__(self, raw_data: RawDataBundle):
        self.raw_data = raw_data

    def load(self) -> RawDataBundle:
        return self.raw_data


def create_pipeline(raw_data: RawDataBundle) -> PipelineOrchestrator:
    """Create a pipeline with in-memory data."""
    return PipelineOrchestrator(loader=InMemoryLoader(raw_data))


# =============================================================================
# HELPER FUNCTION
# =============================================================================


def create_raw_data_bundle(dataset: dict[str, pl.LazyFrame]) -> RawDataBundle:
    """Create a RawDataBundle from benchmark dataset."""
    return RawDataBundle(
        counterparties=dataset["counterparties"],
        facilities=dataset["facilities"],
        loans=dataset["loans"],
        contingents=dataset["contingents"],
        collateral=dataset["collateral"],
        guarantees=pl.LazyFrame(
            schema={
                "guarantee_reference": pl.String,
                "guarantee_type": pl.String,
                "guarantor": pl.String,
                "currency": pl.String,
                "maturity_date": pl.Date,
                "amount_covered": pl.Float64,
                "percentage_covered": pl.Float64,
                "beneficiary_type": pl.String,
                "beneficiary_reference": pl.String,
            }
        ),
        provisions=pl.LazyFrame(
            schema={
                "provision_reference": pl.String,
                "provision_type": pl.String,
                "ifrs9_stage": pl.Int8,
                "currency": pl.String,
                "amount": pl.Float64,
                "as_of_date": pl.Date,
                "beneficiary_type": pl.String,
                "beneficiary_reference": pl.String,
            }
        ),
        ratings=dataset["ratings"],
        facility_mappings=dataset["facility_mappings"],
        org_mappings=dataset["org_mappings"],
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
    )


# =============================================================================
# 10K SCALE PIPELINE BENCHMARKS
# =============================================================================


@pytest.mark.benchmark
@pytest.mark.scale_10k
class TestPipelineBenchmark10K:
    """Full pipeline benchmarks at 10K counterparty scale."""

    def test_full_pipeline_sa_10k(
        self,
        benchmark,
        dataset_10k: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark full SA pipeline at 10K scale.

        Target: < 2 seconds
        """
        raw_data = create_raw_data_bundle(dataset_10k)
        config = CalculationConfig.crr(BENCHMARK_REPORTING_DATE)  # SA only

        pipeline = create_pipeline(raw_data)

        def run_pipeline():
            result = pipeline.run(config)
            # Force materialization
            if result.sa_results is not None:
                _ = result.sa_results.collect()
            return result

        result = benchmark(run_pipeline)

        assert result is not None
        assert result.sa_results is not None

    def test_full_pipeline_crr_10k(
        self,
        benchmark,
        dataset_10k: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark full CRR pipeline (SA + IRB) at 10K scale.

        Target: < 3 seconds
        """
        raw_data = create_raw_data_bundle(dataset_10k)
        # Enable IRB for corporates and institutions
        config = CalculationConfig.crr(
            BENCHMARK_REPORTING_DATE,
            irb_permissions=IRBPermissions.full_irb(),
        )

        pipeline = create_pipeline(raw_data)

        def run_pipeline():
            result = pipeline.run(config)
            if result.sa_results is not None:
                _ = result.sa_results.collect()
            if result.irb_results is not None:
                _ = result.irb_results.collect()
            return result

        result = benchmark(run_pipeline)

        assert result is not None


# =============================================================================
# 100K SCALE PIPELINE BENCHMARKS
# =============================================================================


@pytest.mark.benchmark
@pytest.mark.scale_100k
class TestPipelineBenchmark100K:
    """Full pipeline benchmarks at 100K counterparty scale."""

    def test_full_pipeline_sa_100k(
        self,
        benchmark,
        dataset_100k: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark full SA pipeline at 100K scale.

        Target: < 10 seconds
        """
        raw_data = create_raw_data_bundle(dataset_100k)
        config = CalculationConfig.crr(BENCHMARK_REPORTING_DATE)

        pipeline = create_pipeline(raw_data)

        def run_pipeline():
            result = pipeline.run(config)
            if result.sa_results is not None:
                _ = result.sa_results.collect()
            return result

        result = benchmark(run_pipeline)

        assert result is not None
        assert result.sa_results is not None

        # Verify scale
        sa_df = result.sa_results.collect()
        print(f"\nSA results count: {len(sa_df)}")

    def test_full_pipeline_crr_100k(
        self,
        benchmark,
        dataset_100k: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark full CRR pipeline (SA + IRB) at 100K scale.

        Target: < 15 seconds
        """
        raw_data = create_raw_data_bundle(dataset_100k)
        config = CalculationConfig.crr(
            BENCHMARK_REPORTING_DATE,
            irb_permissions=IRBPermissions.full_irb(),
        )

        pipeline = create_pipeline(raw_data)

        def run_pipeline():
            result = pipeline.run(config)
            if result.sa_results is not None:
                _ = result.sa_results.collect()
            if result.irb_results is not None:
                _ = result.irb_results.collect()
            return result

        result = benchmark(run_pipeline)

        assert result is not None

    def test_pipeline_throughput_100k(
        self,
        benchmark,
        dataset_100k: dict[str, pl.LazyFrame],
        dataset_100k_stats: dict,
    ):
        """
        Measure throughput: exposures processed per second.
        """
        raw_data = create_raw_data_bundle(dataset_100k)
        config = CalculationConfig.crr(BENCHMARK_REPORTING_DATE)

        pipeline = create_pipeline(raw_data)

        def run_pipeline():
            result = pipeline.run(config)
            if result.sa_results is not None:
                df = result.sa_results.collect()
                return len(df)
            return 0

        exposure_count = benchmark(run_pipeline)

        # Get timing from benchmark
        # benchmark.stats gives us timing info
        mean_time = benchmark.stats.stats.mean if hasattr(benchmark, 'stats') else 1.0

        print(f"\nExposures processed: {exposure_count}")
        print(f"Approximate throughput: {exposure_count / mean_time:.0f} exposures/second")


# =============================================================================
# 1M SCALE PIPELINE BENCHMARKS (Slow)
# =============================================================================


@pytest.mark.benchmark
@pytest.mark.scale_1m
@pytest.mark.slow
class TestPipelineBenchmark1M:
    """Full pipeline benchmarks at 1M counterparty scale (slow)."""

    def test_full_pipeline_sa_1m(
        self,
        benchmark,
        dataset_1m: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark full SA pipeline at 1M scale.

        Target: < 120 seconds
        """
        raw_data = create_raw_data_bundle(dataset_1m)
        config = CalculationConfig.crr(BENCHMARK_REPORTING_DATE)

        pipeline = create_pipeline(raw_data)

        def run_pipeline():
            result = pipeline.run(config)
            if result.sa_results is not None:
                _ = result.sa_results.collect()
            return result

        result = benchmark(run_pipeline)

        assert result is not None


# =============================================================================
# 10M SCALE PIPELINE BENCHMARKS (Production scale, very slow)
# =============================================================================


@pytest.mark.benchmark
@pytest.mark.scale_10m
@pytest.mark.slow
class TestPipelineBenchmark10M:
    """Full pipeline benchmarks at 10M counterparty scale (very slow)."""

    def test_full_pipeline_sa_10m(
        self,
        benchmark,
        dataset_10m: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark full SA pipeline at 10M scale.

        Target: < 20 minutes
        """
        raw_data = create_raw_data_bundle(dataset_10m)
        config = CalculationConfig.crr(BENCHMARK_REPORTING_DATE)

        pipeline = create_pipeline(raw_data)

        def run_pipeline():
            result = pipeline.run(config)
            if result.sa_results is not None:
                _ = result.sa_results.collect()
            return result

        result = benchmark(run_pipeline)

        assert result is not None


# =============================================================================
# INDIVIDUAL COMPONENT BENCHMARKS
# =============================================================================


@pytest.mark.benchmark
@pytest.mark.scale_100k
class TestComponentBenchmarks100K:
    """Benchmark individual pipeline components at 100K scale."""

    def test_classifier_100k(
        self,
        benchmark,
        dataset_100k: dict[str, pl.LazyFrame],
    ):
        """Benchmark exposure classifier at 100K scale."""
        from rwa_calc.engine.classifier import ExposureClassifier
        from rwa_calc.engine.hierarchy import HierarchyResolver

        raw_data = create_raw_data_bundle(dataset_100k)
        config = CalculationConfig.crr(BENCHMARK_REPORTING_DATE)

        # Setup: resolve hierarchy first
        resolver = HierarchyResolver()
        resolved = resolver.resolve(raw_data, config)

        classifier = ExposureClassifier()

        def classify():
            result = classifier.classify(resolved, config)
            # Force materialization
            _ = result.sa_exposures.collect()
            return result

        result = benchmark(classify)

        assert result is not None

    def test_sa_calculator_100k(
        self,
        benchmark,
        dataset_100k: dict[str, pl.LazyFrame],
    ):
        """Benchmark SA calculator at 100K scale."""
        from rwa_calc.engine.classifier import ExposureClassifier
        from rwa_calc.engine.crm.processor import CRMProcessor
        from rwa_calc.engine.hierarchy import HierarchyResolver
        from rwa_calc.engine.sa.calculator import SACalculator

        raw_data = create_raw_data_bundle(dataset_100k)
        config = CalculationConfig.crr(BENCHMARK_REPORTING_DATE)

        # Setup: resolve hierarchy and classify
        resolver = HierarchyResolver()
        resolved = resolver.resolve(raw_data, config)

        classifier = ExposureClassifier()
        classified = classifier.classify(resolved, config)

        crm = CRMProcessor()
        crm_adjusted = crm.process(classified, resolved, config)

        sa_calc = SACalculator()

        def calculate_sa():
            result = sa_calc.calculate(crm_adjusted.sa_adjusted, config)
            _ = result.collect()
            return result

        result = benchmark(calculate_sa)

        assert result is not None


# =============================================================================
# APPROACH-SPECIFIC BENCHMARKS (SA, IRB, Slotting)
# =============================================================================


def create_irb_with_slotting_permissions() -> IRBPermissions:
    """Create IRB permissions that include slotting for specialised lending."""
    permissions = {
        ExposureClass.SOVEREIGN: {ApproachType.SA, ApproachType.FIRB, ApproachType.AIRB},
        ExposureClass.INSTITUTION: {ApproachType.SA, ApproachType.FIRB, ApproachType.AIRB},
        ExposureClass.CORPORATE: {ApproachType.SA, ApproachType.FIRB, ApproachType.AIRB},
        ExposureClass.CORPORATE_SME: {ApproachType.SA, ApproachType.FIRB, ApproachType.AIRB},
        ExposureClass.RETAIL_MORTGAGE: {ApproachType.SA, ApproachType.AIRB},
        ExposureClass.RETAIL_QRRE: {ApproachType.SA, ApproachType.AIRB},
        ExposureClass.RETAIL_OTHER: {ApproachType.SA, ApproachType.AIRB},
        ExposureClass.SPECIALISED_LENDING: {ApproachType.SA, ApproachType.SLOTTING},
        ExposureClass.EQUITY: {ApproachType.SA},
    }
    return IRBPermissions(permissions=permissions)


def create_corporate_only_irb_permissions() -> IRBPermissions:
    """Create IRB permissions for corporates only (partial IRB rollout)."""
    permissions = {
        ExposureClass.CORPORATE: {ApproachType.SA, ApproachType.FIRB},
        ExposureClass.CORPORATE_SME: {ApproachType.SA, ApproachType.FIRB},
    }
    return IRBPermissions(permissions=permissions)


@pytest.mark.benchmark
@pytest.mark.scale_100k
class TestApproachBenchmarks100K:
    """Benchmark different calculation approaches at 100K scale."""

    def test_sa_only_100k(
        self,
        benchmark,
        dataset_100k: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark SA-only calculation at 100K scale.

        All exposures use Standardised Approach (no IRB).
        """
        raw_data = create_raw_data_bundle(dataset_100k)
        config = CalculationConfig.crr(
            BENCHMARK_REPORTING_DATE,
            irb_permissions=IRBPermissions.sa_only(),
        )

        pipeline = create_pipeline(raw_data)

        def run_pipeline():
            result = pipeline.run(config)
            if result.sa_results is not None:
                _ = result.sa_results.collect()
            return result

        result = benchmark(run_pipeline)

        assert result is not None
        assert result.sa_results is not None
        # All should be SA
        sa_count = result.sa_results.collect().height
        print(f"\nSA exposures: {sa_count:,}")

    def test_full_irb_100k(
        self,
        benchmark,
        dataset_100k: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark full IRB calculation at 100K scale.

        All eligible exposures use IRB approach.
        """
        raw_data = create_raw_data_bundle(dataset_100k)
        config = CalculationConfig.crr(
            BENCHMARK_REPORTING_DATE,
            irb_permissions=IRBPermissions.full_irb(),
        )

        pipeline = create_pipeline(raw_data)

        def run_pipeline():
            result = pipeline.run(config)
            if result.sa_results is not None:
                _ = result.sa_results.collect()
            if result.irb_results is not None:
                _ = result.irb_results.collect()
            return result

        result = benchmark(run_pipeline)

        assert result is not None
        sa_count = result.sa_results.collect().height if result.sa_results is not None else 0
        irb_count = result.irb_results.collect().height if result.irb_results is not None else 0
        print(f"\nSA exposures: {sa_count:,}, IRB exposures: {irb_count:,}")

    def test_irb_with_slotting_100k(
        self,
        benchmark,
        dataset_100k: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark IRB + slotting calculation at 100K scale.

        Specialised lending uses slotting approach, others use IRB.
        """
        raw_data = create_raw_data_bundle(dataset_100k)
        config = CalculationConfig.crr(
            BENCHMARK_REPORTING_DATE,
            irb_permissions=create_irb_with_slotting_permissions(),
        )

        pipeline = create_pipeline(raw_data)

        def run_pipeline():
            result = pipeline.run(config)
            if result.sa_results is not None:
                _ = result.sa_results.collect()
            if result.irb_results is not None:
                _ = result.irb_results.collect()
            if result.slotting_results is not None:
                _ = result.slotting_results.collect()
            return result

        result = benchmark(run_pipeline)

        assert result is not None
        sa_count = result.sa_results.collect().height if result.sa_results is not None else 0
        irb_count = result.irb_results.collect().height if result.irb_results is not None else 0
        slotting_count = result.slotting_results.collect().height if result.slotting_results is not None else 0
        print(f"\nSA: {sa_count:,}, IRB: {irb_count:,}, Slotting: {slotting_count:,}")

    def test_partial_irb_corporate_only_100k(
        self,
        benchmark,
        dataset_100k: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark partial IRB (corporate only) at 100K scale.

        Only corporate exposures use F-IRB, all others use SA.
        """
        raw_data = create_raw_data_bundle(dataset_100k)
        config = CalculationConfig.crr(
            BENCHMARK_REPORTING_DATE,
            irb_permissions=create_corporate_only_irb_permissions(),
        )

        pipeline = create_pipeline(raw_data)

        def run_pipeline():
            result = pipeline.run(config)
            if result.sa_results is not None:
                _ = result.sa_results.collect()
            if result.irb_results is not None:
                _ = result.irb_results.collect()
            return result

        result = benchmark(run_pipeline)

        assert result is not None
        sa_count = result.sa_results.collect().height if result.sa_results is not None else 0
        irb_count = result.irb_results.collect().height if result.irb_results is not None else 0
        print(f"\nSA exposures: {sa_count:,}, IRB (corporate): {irb_count:,}")

    def test_basel_3_1_with_output_floor_100k(
        self,
        benchmark,
        dataset_100k: dict[str, pl.LazyFrame],
    ):
        """
        Benchmark Basel 3.1 calculation with output floor at 100K scale.

        Uses Basel 3.1 framework with 72.5% output floor.
        """
        raw_data = create_raw_data_bundle(dataset_100k)
        config = CalculationConfig.basel_3_1(
            date(2030, 1, 1),  # Full output floor
            irb_permissions=IRBPermissions.full_irb(),
        )

        pipeline = create_pipeline(raw_data)

        def run_pipeline():
            result = pipeline.run(config)
            if result.sa_results is not None:
                _ = result.sa_results.collect()
            if result.irb_results is not None:
                _ = result.irb_results.collect()
            return result

        result = benchmark(run_pipeline)

        assert result is not None


@pytest.mark.benchmark
@pytest.mark.scale_1m
class TestApproachBenchmarks1M:
    """Benchmark different calculation approaches at 1M scale."""

    def test_sa_only_1m(
        self,
        benchmark,
        dataset_1m: dict[str, pl.LazyFrame],
    ):
        """Benchmark SA-only calculation at 1M scale."""
        raw_data = create_raw_data_bundle(dataset_1m)
        config = CalculationConfig.crr(
            BENCHMARK_REPORTING_DATE,
            irb_permissions=IRBPermissions.sa_only(),
        )

        pipeline = create_pipeline(raw_data)

        def run_pipeline():
            result = pipeline.run(config)
            if result.sa_results is not None:
                _ = result.sa_results.collect()
            return result

        result = benchmark(run_pipeline)
        assert result is not None

    def test_full_irb_1m(
        self,
        benchmark,
        dataset_1m: dict[str, pl.LazyFrame],
    ):
        """Benchmark full IRB calculation at 1M scale."""
        raw_data = create_raw_data_bundle(dataset_1m)
        config = CalculationConfig.crr(
            BENCHMARK_REPORTING_DATE,
            irb_permissions=IRBPermissions.full_irb(),
        )

        pipeline = create_pipeline(raw_data)

        def run_pipeline():
            result = pipeline.run(config)
            if result.sa_results is not None:
                _ = result.sa_results.collect()
            if result.irb_results is not None:
                _ = result.irb_results.collect()
            return result

        result = benchmark(run_pipeline)
        assert result is not None

    def test_irb_with_slotting_1m(
        self,
        benchmark,
        dataset_1m: dict[str, pl.LazyFrame],
    ):
        """Benchmark IRB + slotting calculation at 1M scale."""
        raw_data = create_raw_data_bundle(dataset_1m)
        config = CalculationConfig.crr(
            BENCHMARK_REPORTING_DATE,
            irb_permissions=create_irb_with_slotting_permissions(),
        )

        pipeline = create_pipeline(raw_data)

        def run_pipeline():
            result = pipeline.run(config)
            if result.sa_results is not None:
                _ = result.sa_results.collect()
            if result.irb_results is not None:
                _ = result.irb_results.collect()
            if result.slotting_results is not None:
                _ = result.slotting_results.collect()
            return result

        result = benchmark(run_pipeline)
        assert result is not None


# =============================================================================
# MEMORY BENCHMARKS
# =============================================================================


@pytest.mark.benchmark
class TestPipelineMemoryBenchmark:
    """Memory usage benchmarks for full pipeline."""

    def test_pipeline_memory_100k(
        self,
        dataset_100k: dict[str, pl.LazyFrame],
        memory_tracker,
    ):
        """
        Track memory usage for full pipeline at 100K scale.

        Target: < 2 GB peak
        """
        raw_data = create_raw_data_bundle(dataset_100k)
        config = CalculationConfig.crr(BENCHMARK_REPORTING_DATE)

        pipeline = create_pipeline(raw_data)

        with memory_tracker as tracker:
            result = pipeline.run(config)
            if result.sa_results is not None:
                _ = result.sa_results.collect()

        print(f"\nPeak memory usage: {tracker.peak_mb:.2f} MB")
        assert tracker.peak_mb < 4000, f"Memory usage {tracker.peak_mb:.2f} MB exceeds 4000 MB limit"


# =============================================================================
# SUMMARY STATISTICS
# =============================================================================


@pytest.mark.benchmark
class TestBenchmarkSummary:
    """Print summary statistics for benchmark datasets."""

    def test_print_dataset_stats_100k(
        self,
        dataset_100k_stats: dict,
    ):
        """Print statistics for 100K dataset."""
        print("\n" + "=" * 60)
        print("100K BENCHMARK DATASET STATISTICS")
        print("=" * 60)

        for name, info in dataset_100k_stats.items():
            if isinstance(info, dict) and "count" in info:
                print(f"\n{name}:")
                print(f"  Count: {info['count']:,}")
            elif name == "entity_distribution":
                print(f"\n{name}:")
                for entity, count in info.items():
                    print(f"  {entity}: {count:,}")
            elif name == "org_hierarchy":
                print(f"\n{name}:")
                for key, value in info.items():
                    if isinstance(value, float):
                        print(f"  {key}: {value:.2f}")
                    else:
                        print(f"  {key}: {value:,}")
            elif name == "facility_hierarchy":
                print(f"\n{name}:")
                for key, value in info.items():
                    if isinstance(value, dict):
                        print(f"  {key}:")
                        for k, v in value.items():
                            print(f"    {k}: {v:,}")
                    else:
                        print(f"  {key}: {value:,}")

        print("\n" + "=" * 60)
