"""
Inspect LazyFrame query plan complexity at each CRM stage.

Usage:
    PYTHONPATH=. uv run python tests/benchmarks/profile_plan.py
"""

from __future__ import annotations

import time
from datetime import date

import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.hierarchy import HierarchyResolver
from rwa_calc.engine.utils import has_required_columns
from tests.benchmarks.data_generators import get_or_create_dataset
from tests.benchmarks.test_pipeline_benchmark import create_raw_data_bundle

REPORTING_DATE = date(2026, 1, 1)


def count_plan_nodes(plan_str: str) -> dict[str, int]:
    """Count operations in a query plan string."""
    lines = plan_str.strip().split("\n")
    return {
        "total_lines": len(lines),
        "joins": sum(1 for line in lines if "JOIN" in line.upper()),
        "filters": sum(1 for line in lines if "FILTER" in line or "σ" in line),
        "projections": sum(
            1 for line in lines if "PROJECT" in line or "π" in line or "SELECT" in line
        ),
        "with_columns": sum(
            1 for line in lines if "WITH_COLUMNS" in line or "WITH COLUMNS" in line.upper()
        ),
        "group_by": sum(1 for line in lines if "GROUP" in line.upper() or "AGG" in line.upper()),
        "unions": sum(1 for line in lines if "UNION" in line.upper() or "CONCAT" in line.upper()),
        "sorts": sum(1 for line in lines if "SORT" in line.upper()),
    }


def measure_plan(label: str, lf: pl.LazyFrame) -> None:
    """Print plan metrics for a LazyFrame."""
    try:
        optimized = lf.explain(optimized=True)
        unoptimized = lf.explain(optimized=False)
    except Exception as e:
        print(f"\n--- {label} ---")
        print(f"  ERROR getting plan: {e}")
        return

    opt_stats = count_plan_nodes(optimized)
    unopt_stats = count_plan_nodes(unoptimized)

    # Measure optimization time
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        _ = lf.explain(optimized=True)
        times.append(time.perf_counter() - t0)
    opt_time = min(times)

    # Measure collect time
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        _ = lf.collect()
        times.append(time.perf_counter() - t0)
    collect_time = min(times)

    print(f"\n--- {label} ---")
    print(f"  Unoptimized plan: {unopt_stats['total_lines']} lines")
    print(f"  Optimized plan:   {opt_stats['total_lines']} lines")
    print(f"  Optimization time: {opt_time * 1000:.1f}ms")
    print(f"  Collect time:      {collect_time * 1000:.1f}ms")
    print(f"  Plan ops: {opt_stats}")


def inspect_plans(dataset: dict[str, pl.LazyFrame]) -> None:
    """Inspect query plan at each CRM stage."""
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

    print("=" * 72)
    print("QUERY PLAN INSPECTION AT EACH CRM STAGE")
    print("=" * 72)

    exposures = data.all_exposures
    measure_plan("0. Input (classified exposures)", exposures)

    # Step 1: Provisions
    if has_provisions:
        exposures = crm.resolve_provisions(exposures, data.provisions, config)
        measure_plan("1. After resolve_provisions", exposures)

    # Step 2: CCF
    exposures = crm._apply_ccf(exposures, config)
    measure_plan("2. After apply_ccf", exposures)

    # Step 3: Initialize EAD
    exposures = crm._initialize_ead(exposures)
    measure_plan("3. After initialize_ead", exposures)

    # Step 4: Collateral
    if has_collateral:
        exposures = crm.apply_collateral(exposures, data.collateral, config)
        measure_plan("4. After apply_collateral", exposures)
    else:
        exposures = crm._apply_firb_supervisory_lgd_no_collateral(exposures)
        measure_plan("4. After firb_lgd_no_collateral", exposures)

    # Step 5: Guarantees
    if has_guarantees:
        exposures = crm.apply_guarantees(
            exposures,
            data.guarantees,
            data.counterparty_lookup.counterparties,
            config,
            data.counterparty_lookup.rating_inheritance,
        )
        measure_plan("5. After apply_guarantees", exposures)

    # Step 6: Finalize
    exposures = crm._finalize_ead(exposures)
    measure_plan("6. After finalize_ead", exposures)

    # Step 7: Audit
    exposures = crm._add_crm_audit(exposures)
    measure_plan("7. After add_crm_audit (FULL CRM PLAN)", exposures)

    # Now show what happens with a single mid-point collect
    print("\n" + "=" * 72)
    print("WITH STRATEGIC COLLECT AFTER COLLATERAL")
    print("=" * 72)

    exposures = data.all_exposures
    if has_provisions:
        exposures = crm.resolve_provisions(exposures, data.provisions, config)
    exposures = crm._apply_ccf(exposures, config)
    exposures = crm._initialize_ead(exposures)
    if has_collateral:
        exposures = crm.apply_collateral(exposures, data.collateral, config)

    # Strategic collect here
    t0 = time.perf_counter()
    exposures = exposures.collect().lazy()
    mid_collect = time.perf_counter() - t0
    print(f"\nMid-point collect time: {mid_collect * 1000:.1f}ms")

    if has_guarantees:
        exposures = crm.apply_guarantees(
            exposures,
            data.guarantees,
            data.counterparty_lookup.counterparties,
            config,
            data.counterparty_lookup.rating_inheritance,
        )
    exposures = crm._finalize_ead(exposures)
    exposures = crm._add_crm_audit(exposures)
    measure_plan("After guarantees+finalize (post mid-collect)", exposures)

    t0 = time.perf_counter()
    _ = exposures.collect()
    final_collect = time.perf_counter() - t0
    print(f"  Final collect time: {final_collect * 1000:.1f}ms")
    print(f"  Total (mid + final): {(mid_collect + final_collect) * 1000:.1f}ms")


def dump_full_plan(dataset: dict[str, pl.LazyFrame]) -> None:
    """Dump the full optimized plan to understand structure."""
    raw_data = create_raw_data_bundle(dataset)
    config = CalculationConfig.crr(REPORTING_DATE)

    hierarchy_resolver = HierarchyResolver()
    classifier = ExposureClassifier()
    crm = CRMProcessor()

    resolved = hierarchy_resolver.resolve(raw_data, config)
    classified = classifier.classify(resolved, config)
    data = classified

    has_provisions = has_required_columns(data.provisions, crm.PROVISION_REQUIRED_COLUMNS)
    has_collateral = has_required_columns(
        data.collateral,
        crm.COLLATERAL_REQUIRED_REQUIRED_COLUMNS
        if hasattr(crm, "COLLATERAL_REQUIRED_REQUIRED_COLUMNS")
        else crm.COLLATERAL_REQUIRED_COLUMNS,
    )
    has_guarantees = (
        has_required_columns(data.guarantees, crm.GUARANTEE_REQUIRED_COLUMNS)
        and data.counterparty_lookup is not None
    )

    exposures = data.all_exposures
    if has_provisions:
        exposures = crm.resolve_provisions(exposures, data.provisions, config)
    exposures = crm._apply_ccf(exposures, config)
    exposures = crm._initialize_ead(exposures)
    if has_collateral:
        exposures = crm.apply_collateral(exposures, data.collateral, config)
    if has_guarantees:
        exposures = crm.apply_guarantees(
            exposures,
            data.guarantees,
            data.counterparty_lookup.counterparties,
            config,
            data.counterparty_lookup.rating_inheritance,
        )
    exposures = crm._finalize_ead(exposures)
    exposures = crm._add_crm_audit(exposures)

    print("\n" + "=" * 72)
    print("FULL OPTIMIZED CRM PLAN (first 200 lines)")
    print("=" * 72)
    plan = exposures.explain(optimized=True)
    lines = plan.split("\n")
    for i, line in enumerate(lines[:200]):
        print(f"  {i + 1:3d} | {line}")
    if len(lines) > 200:
        print(f"  ... ({len(lines) - 200} more lines)")
    print(f"\n  Total plan lines: {len(lines)}")


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

    inspect_plans(dataset)
    dump_full_plan(dataset)
