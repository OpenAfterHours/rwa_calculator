"""
Profile individual pipeline stages to identify bottlenecks.

Usage:
    PYTHONPATH=. uv run python tests/benchmarks/profile_stages.py
"""

from __future__ import annotations

import time
from datetime import date

import polars as pl

from tests.benchmarks.data_generators import get_or_create_dataset
from tests.benchmarks.test_pipeline_benchmark import create_raw_data_bundle, create_pipeline

from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.engine.hierarchy import HierarchyResolver
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.engine.irb.calculator import IRBCalculator
from rwa_calc.engine.utils import has_rows, has_required_columns


REPORTING_DATE = date(2026, 1, 1)
WARMUP_RUNS = 2
TIMED_RUNS = 5


def profile_pipeline_stages(dataset: dict[str, pl.LazyFrame]) -> None:
    """Profile top-level pipeline stages."""
    raw_data = create_raw_data_bundle(dataset)
    config = CalculationConfig.crr(REPORTING_DATE)

    hierarchy_resolver = HierarchyResolver()
    classifier = ExposureClassifier()
    crm_processor = CRMProcessor()
    sa_calculator = SACalculator()

    print("=" * 72)
    print("TOP-LEVEL PIPELINE STAGES (SA-only, 10K counterparties)")
    print("=" * 72)

    # Warmup
    for _ in range(WARMUP_RUNS):
        resolved = hierarchy_resolver.resolve(raw_data, config)
        classified = classifier.classify(resolved, config)
        crm_adjusted = crm_processor.get_crm_adjusted_bundle(classified, config)
        sa_result = sa_calculator.get_sa_result_bundle(crm_adjusted, config)
        _ = sa_result.results.collect()

    timings: dict[str, list[float]] = {
        "hierarchy": [],
        "classifier": [],
        "crm_processor": [],
        "sa_calculator+collect": [],
    }

    for _ in range(TIMED_RUNS):
        t0 = time.perf_counter()
        resolved = hierarchy_resolver.resolve(raw_data, config)
        timings["hierarchy"].append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        classified = classifier.classify(resolved, config)
        timings["classifier"].append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        crm_adjusted = crm_processor.get_crm_adjusted_bundle(classified, config)
        timings["crm_processor"].append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        sa_result = sa_calculator.get_sa_result_bundle(crm_adjusted, config)
        _ = sa_result.results.collect(engine="streaming")
        timings["sa_calculator+collect"].append(time.perf_counter() - t0)

    _print_timings(timings)


def profile_crm_substeps(dataset: dict[str, pl.LazyFrame]) -> None:
    """Profile CRM sub-steps by instrumenting the processor internals."""
    raw_data = create_raw_data_bundle(dataset)
    config = CalculationConfig.crr(REPORTING_DATE)

    hierarchy_resolver = HierarchyResolver()
    classifier = ExposureClassifier()
    crm = CRMProcessor()

    # Get classified data (cached across runs since it has a .collect() inside)
    resolved = hierarchy_resolver.resolve(raw_data, config)
    classified = classifier.classify(resolved, config)

    print("\n" + "=" * 72)
    print("CRM SUB-STEPS BREAKDOWN (SA-only, 10K counterparties)")
    print("=" * 72)

    # Print input context
    data = classified
    has_provisions = has_required_columns(data.provisions, crm.PROVISION_REQUIRED_COLUMNS)
    has_collateral = has_required_columns(data.collateral, crm.COLLATERAL_REQUIRED_COLUMNS)
    has_guarantees = (
        has_required_columns(data.guarantees, crm.GUARANTEE_REQUIRED_COLUMNS)
        and data.counterparty_lookup is not None
    )
    n_exposures = data.all_exposures.select(pl.len()).collect().item()
    print(f"\nInputs: {n_exposures} exposures")
    print(f"  has_provisions: {has_provisions}")
    print(f"  has_collateral: {has_collateral}")
    print(f"  has_guarantees: {has_guarantees}")
    if has_collateral:
        n_coll = data.collateral.select(pl.len()).collect().item()
        print(f"  collateral rows: {n_coll}")

    # Warmup
    for _ in range(WARMUP_RUNS):
        _ = crm.get_crm_adjusted_bundle(classified, config)

    timings: dict[str, list[float]] = {
        "1_resolve_provisions": [],
        "2_apply_ccf": [],
        "3_initialize_ead": [],
        "4_apply_collateral": [],
        "5_apply_guarantees": [],
        "6_finalize_ead": [],
        "7_add_crm_audit": [],
        "8_collect": [],
        "9_filter_splits": [],
        "total": [],
    }

    for _ in range(TIMED_RUNS):
        t_total = time.perf_counter()
        exposures = data.all_exposures

        # Step 1: Provisions
        t0 = time.perf_counter()
        if has_provisions:
            exposures = crm.resolve_provisions(exposures, data.provisions, config)
        timings["1_resolve_provisions"].append(time.perf_counter() - t0)

        # Step 2: CCF
        t0 = time.perf_counter()
        exposures = crm._apply_ccf(exposures, config)
        timings["2_apply_ccf"].append(time.perf_counter() - t0)

        # Step 3: Initialize EAD
        t0 = time.perf_counter()
        exposures = crm._initialize_ead(exposures)
        timings["3_initialize_ead"].append(time.perf_counter() - t0)

        # Step 4: Collateral
        t0 = time.perf_counter()
        if has_collateral:
            exposures = crm.apply_collateral(exposures, data.collateral, config)
        else:
            exposures = crm._apply_firb_supervisory_lgd_no_collateral(exposures)
        timings["4_apply_collateral"].append(time.perf_counter() - t0)

        # Step 5: Guarantees
        t0 = time.perf_counter()
        if has_guarantees:
            exposures = crm.apply_guarantees(
                exposures,
                data.guarantees,
                data.counterparty_lookup.counterparties,
                config,
                data.counterparty_lookup.rating_inheritance,
            )
        timings["5_apply_guarantees"].append(time.perf_counter() - t0)

        # Step 6: Finalize EAD
        t0 = time.perf_counter()
        exposures = crm._finalize_ead(exposures)
        timings["6_finalize_ead"].append(time.perf_counter() - t0)

        # Step 7: CRM audit
        t0 = time.perf_counter()
        exposures = crm._add_crm_audit(exposures)
        timings["7_add_crm_audit"].append(time.perf_counter() - t0)

        # Step 8: The expensive .collect()
        t0 = time.perf_counter()
        exposures = exposures.collect().lazy()
        timings["8_collect"].append(time.perf_counter() - t0)

        # Step 9: Filter splits
        from rwa_calc.domain.enums import ApproachType
        t0 = time.perf_counter()
        sa_exp = exposures.filter(pl.col("approach") == ApproachType.SA.value)
        irb_exp = exposures.filter(
            (pl.col("approach") == ApproachType.FIRB.value)
            | (pl.col("approach") == ApproachType.AIRB.value)
        )
        slotting_exp = exposures.filter(
            pl.col("approach") == ApproachType.SLOTTING.value
        )
        # Force the filters to evaluate
        _ = sa_exp.select(pl.len()).collect().item()
        _ = irb_exp.select(pl.len()).collect().item()
        _ = slotting_exp.select(pl.len()).collect().item()
        timings["9_filter_splits"].append(time.perf_counter() - t0)

        timings["total"].append(time.perf_counter() - t_total)

    _print_timings(timings)


def profile_crm_collect_incrementally(dataset: dict[str, pl.LazyFrame]) -> None:
    """
    Profile CRM by collecting at each sub-step to isolate actual compute cost.

    This tells us the REAL cost of each step by forcing materialization.
    """
    raw_data = create_raw_data_bundle(dataset)
    config = CalculationConfig.crr(REPORTING_DATE)

    hierarchy_resolver = HierarchyResolver()
    classifier = ExposureClassifier()
    crm = CRMProcessor()

    resolved = hierarchy_resolver.resolve(raw_data, config)
    classified = classifier.classify(resolved, config)
    data = classified

    has_provisions = has_required_columns(data.provisions, crm.PROVISION_REQUIRED_COLUMNS)
    has_collateral = has_required_columns(data.collateral, crm.COLLATERAL_REQUIRED_COLUMNS)
    has_guarantees = (
        has_required_columns(data.guarantees, crm.GUARANTEE_REQUIRED_COLUMNS)
        and data.counterparty_lookup is not None
    )

    print("\n" + "=" * 72)
    print("CRM INCREMENTAL COLLECT (real cost per step, SA-only, 10K)")
    print("=" * 72)

    # Warmup
    for _ in range(WARMUP_RUNS):
        _ = crm.get_crm_adjusted_bundle(classified, config)

    timings: dict[str, list[float]] = {
        "1_resolve_provisions": [],
        "2_apply_ccf": [],
        "3_initialize_ead": [],
        "4_apply_collateral": [],
        "5_finalize_ead+audit": [],
        "6_collect_final": [],
    }

    for _ in range(TIMED_RUNS):
        exposures = data.all_exposures

        # Step 1: Provisions - build + collect
        t0 = time.perf_counter()
        if has_provisions:
            exposures = crm.resolve_provisions(exposures, data.provisions, config)
        exposures = exposures.collect().lazy()
        timings["1_resolve_provisions"].append(time.perf_counter() - t0)

        # Step 2: CCF - build + collect
        t0 = time.perf_counter()
        exposures = crm._apply_ccf(exposures, config)
        exposures = exposures.collect().lazy()
        timings["2_apply_ccf"].append(time.perf_counter() - t0)

        # Step 3: Initialize EAD - build + collect
        t0 = time.perf_counter()
        exposures = crm._initialize_ead(exposures)
        exposures = exposures.collect().lazy()
        timings["3_initialize_ead"].append(time.perf_counter() - t0)

        # Step 4: Collateral - build + collect
        t0 = time.perf_counter()
        if has_collateral:
            exposures = crm.apply_collateral(exposures, data.collateral, config)
        else:
            exposures = crm._apply_firb_supervisory_lgd_no_collateral(exposures)
        exposures = exposures.collect().lazy()
        timings["4_apply_collateral"].append(time.perf_counter() - t0)

        # Step 5: Finalize + audit - build + collect
        t0 = time.perf_counter()
        exposures = crm._finalize_ead(exposures)
        exposures = crm._add_crm_audit(exposures)
        exposures = exposures.collect().lazy()
        timings["5_finalize_ead+audit"].append(time.perf_counter() - t0)

        # Step 6: The "real" final collect when all steps are chained
        # (this is cheap since we already collected at each step)
        t0 = time.perf_counter()
        _ = exposures.collect()
        timings["6_collect_final"].append(time.perf_counter() - t0)

    _print_timings(timings)


def profile_classifier_substeps(dataset: dict[str, pl.LazyFrame]) -> None:
    """Profile classifier internals - the .collect() at line 211."""
    raw_data = create_raw_data_bundle(dataset)
    config = CalculationConfig.crr(REPORTING_DATE)

    hierarchy_resolver = HierarchyResolver()
    classifier = ExposureClassifier()

    resolved = hierarchy_resolver.resolve(raw_data, config)

    print("\n" + "=" * 72)
    print("CLASSIFIER PROFILE (10K counterparties)")
    print("=" * 72)

    # Warmup
    for _ in range(WARMUP_RUNS):
        _ = classifier.classify(resolved, config)

    timings: dict[str, list[float]] = {
        "classify_total": [],
    }

    for _ in range(TIMED_RUNS):
        t0 = time.perf_counter()
        _ = classifier.classify(resolved, config)
        timings["classify_total"].append(time.perf_counter() - t0)

    _print_timings(timings)
    n = resolved.exposures.select(pl.len()).collect().item()
    print(f"\nExposure count: {n}")


def _print_timings(timings: dict[str, list[float]]) -> None:
    """Print timing results."""
    total_key = "total" if "total" in timings else None
    if total_key:
        total_mean = sum(timings[total_key]) / len(timings[total_key])
    else:
        # Use sum of all stage means as reference
        total_mean = sum(
            sum(t) / len(t)
            for k, t in timings.items()
        )

    print(f"\n{'Stage':<30} {'Min':>10} {'Mean':>10} {'Max':>10} {'%Total':>8}")
    print("-" * 70)

    for stage, times in timings.items():
        mean = sum(times) / len(times)
        mn = min(times)
        mx = max(times)
        pct = (mean / total_mean) * 100 if total_mean > 0 else 0
        marker = " <--" if pct > 25.0 else ""
        print(
            f"{stage:<30} {mn*1000:>9.1f}ms {mean*1000:>9.1f}ms "
            f"{mx*1000:>9.1f}ms {pct:>7.1f}%{marker}"
        )


if __name__ == "__main__":
    print("Loading 10K benchmark dataset...")
    dataset = get_or_create_dataset(
        scale="10k",
        n_counterparties=10_000,
        hierarchy_depth=3,
        seed=42,
        force_regenerate=False,
    )
    print("Dataset loaded.\n")

    profile_pipeline_stages(dataset)
    profile_crm_substeps(dataset)
    profile_crm_collect_incrementally(dataset)
    profile_classifier_substeps(dataset)
