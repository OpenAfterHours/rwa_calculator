"""
Profile full pipeline with per-stage timing breakdown.

Decomposes the pipeline into individual stages and times each one,
including CRM sub-stages and materialization barriers.

Usage:
    # With parquet data directory:
    PYTHONPATH=. uv run python tests/benchmarks/profile_stages.py --path /path/to/parquet/data

    # With synthetic 100K benchmark data (default):
    PYTHONPATH=. uv run python tests/benchmarks/profile_stages.py

    # With specific config:
    PYTHONPATH=. uv run python tests/benchmarks/profile_stages.py --framework crr --irb full
    PYTHONPATH=. uv run python tests/benchmarks/profile_stages.py --framework basel31

    # Control number of runs:
    PYTHONPATH=. uv run python tests/benchmarks/profile_stages.py --runs 5
"""

from __future__ import annotations

import argparse
import time
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.crm import collateral as collateral_mod
from rwa_calc.engine.crm.haircuts import HaircutCalculator
from rwa_calc.engine.crm.processor import (
    CRMProcessor,
    _build_exposure_lookups,
    _join_collateral_to_lookups,
    _join_netting_amounts,
    _resolve_pledge_from_joined,
)
from rwa_calc.engine.hierarchy import HierarchyResolver
from rwa_calc.engine.irb.calculator import IRBCalculator
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.engine.slotting.calculator import SlottingCalculator
from rwa_calc.engine.utils import has_required_columns

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import ClassifiedExposuresBundle, RawDataBundle


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------


def _time(fn, label: str, results: list[tuple[str, float]]) -> object:
    """Time a function call, append (label, elapsed_ms) to results, return fn result."""
    t0 = time.perf_counter()
    result = fn()
    elapsed = (time.perf_counter() - t0) * 1000
    results.append((label, elapsed))
    return result


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_from_parquet(path: str) -> RawDataBundle:
    """Load RawDataBundle from a parquet directory."""
    from rwa_calc.engine.loader import ParquetLoader

    loader = ParquetLoader(base_path=path)
    return loader.load()


def _load_synthetic_100k() -> RawDataBundle:
    """Load synthetic 100K benchmark dataset."""
    from tests.benchmarks.data_generators import get_or_create_dataset
    from tests.benchmarks.test_pipeline_benchmark import create_raw_data_bundle

    print("Generating/loading synthetic 100K dataset...")
    dataset = get_or_create_dataset(
        scale="100k",
        n_counterparties=100_000,
        hierarchy_depth=3,
        seed=42,
    )
    return create_raw_data_bundle(dataset)


# ---------------------------------------------------------------------------
# Per-stage profiling
# ---------------------------------------------------------------------------


def profile_pipeline_stages(
    raw_data: RawDataBundle,
    config: CalculationConfig,
) -> list[tuple[str, float]]:
    """
    Profile each pipeline stage individually.

    Returns list of (stage_name, elapsed_ms) tuples.
    """
    results: list[tuple[str, float]] = []

    # --- Stage 1: Hierarchy ---
    hierarchy_resolver = HierarchyResolver()
    resolved = _time(
        lambda: hierarchy_resolver.resolve(raw_data, config),
        "Hierarchy resolve",
        results,
    )

    # --- Stage 2: Classifier ---
    classifier = ExposureClassifier()
    classified: ClassifiedExposuresBundle = _time(
        lambda: classifier.classify(resolved, config),
        "Classifier",
        results,
    )

    # --- Stage 3: CRM sub-stages ---
    crm = CRMProcessor(is_basel_3_1=config.is_basel_3_1)
    data = classified
    exposures = data.all_exposures

    # 3a: Provisions
    has_provisions = has_required_columns(data.provisions, crm.PROVISION_REQUIRED_COLUMNS)
    if has_provisions:
        exposures = _time(
            lambda: crm.resolve_provisions(exposures, data.provisions, config),
            "CRM: provisions",
            results,
        )

    # 3b: CCF
    exposures = _time(
        lambda: crm._apply_ccf(exposures, config),
        "CRM: CCF",
        results,
    )

    # 3c: Initialize EAD
    exposures = _time(
        lambda: crm._initialize_ead(exposures),
        "CRM: init_ead",
        results,
    )

    # 3d: Collect #1 (provisions + CCF + init_ead)
    exposures = _time(
        lambda: exposures.collect().lazy(),
        "CRM: collect #1 (prov+CCF+ead)",
        results,
    )

    # 3e: Netting collateral
    netting_collateral = _time(
        lambda: collateral_mod.generate_netting_collateral(exposures),
        "CRM: netting collateral gen",
        results,
    )

    collateral = data.collateral
    if netting_collateral is not None:
        exposures = _join_netting_amounts(exposures, netting_collateral)
        if collateral is not None and has_required_columns(
            collateral, crm.COLLATERAL_REQUIRED_COLUMNS
        ):
            collateral = pl.concat([collateral, netting_collateral], how="diagonal")
        else:
            collateral = netting_collateral
    else:
        exposures = exposures.with_columns(pl.lit(0.0).alias("on_bs_netting_amount"))

    # 3f: Collateral sub-stages
    has_collateral = has_required_columns(collateral, crm.COLLATERAL_REQUIRED_COLUMNS)

    if has_collateral:
        # 3f-i: Build exposure lookups (lazy plan construction)
        def _build_lookups():
            return _build_exposure_lookups(exposures)

        direct_lookup, facility_lookup, cp_lookup = _time(
            _build_lookups,
            "CRM: build exposure lookups (lazy)",
            results,
        )

        # 3f-ii: Collect 3 lookups in parallel via collect_all
        def _collect_lookups():
            d, f, c = pl.collect_all([direct_lookup, facility_lookup, cp_lookup])
            return d.lazy(), f.lazy(), c.lazy()

        direct_lookup, facility_lookup, cp_lookup = _time(
            _collect_lookups,
            "CRM: collect_all lookups (3x)",
            results,
        )

        # 3f-iii: Join + haircuts + allocation
        haircut_calc = HaircutCalculator(is_basel_3_1=config.is_basel_3_1)

        facility_ead_totals = facility_lookup.select(
            pl.col("_ben_ref_facility").alias("parent_facility_reference"),
            pl.col("_ead_facility").alias("_fac_ead_total"),
        )
        cp_ead_totals = cp_lookup.select(
            pl.col("_ben_ref_cp").alias("counterparty_reference"),
            pl.col("_ead_cp").alias("_cp_ead_total"),
        )

        coll_joined = _time(
            lambda: _join_collateral_to_lookups(
                collateral, direct_lookup, facility_lookup, cp_lookup
            ),
            "CRM: join collateral to lookups",
            results,
        )
        coll_resolved = _time(
            lambda: _resolve_pledge_from_joined(coll_joined),
            "CRM: resolve pledges",
            results,
        )

        adjusted_collateral = _time(
            lambda: haircut_calc.apply_haircuts(coll_resolved, config),
            "CRM: apply haircuts (lazy)",
            results,
        )
        adjusted_collateral = _time(
            lambda: haircut_calc.apply_maturity_mismatch(adjusted_collateral),
            "CRM: maturity mismatch (lazy)",
            results,
        )

        exposures = _time(
            lambda: collateral_mod._apply_collateral_unified(
                exposures,
                adjusted_collateral,
                config,
                facility_ead_totals,
                cp_ead_totals,
                config.is_basel_3_1,
            ),
            "CRM: collateral allocation (lazy)",
            results,
        )
    else:
        exposures = _time(
            lambda: collateral_mod.apply_firb_supervisory_lgd_no_collateral(
                exposures, config.is_basel_3_1
            ),
            "CRM: firb_lgd_no_collateral",
            results,
        )

    # 3g: Collect exposures + guarantee lookups in parallel
    has_guarantees = (
        has_required_columns(data.guarantees, crm.GUARANTEE_REQUIRED_COLUMNS)
        and data.counterparty_lookup is not None
    )
    if has_guarantees:

        def _collect_guarantee_inputs():
            e, g, cp, ri = pl.collect_all(
                [
                    exposures,
                    data.guarantees,
                    data.counterparty_lookup.counterparties,
                    data.counterparty_lookup.rating_inheritance,
                ]
            )
            return e.lazy(), g.lazy(), cp.lazy(), ri.lazy()

        exposures, guar_lf, cp_lf, ri_lf = _time(
            _collect_guarantee_inputs,
            "CRM: collect_all (exp+guar lookups)",
            results,
        )

        exposures = _time(
            lambda: crm.apply_guarantees(exposures, guar_lf, cp_lf, config, ri_lf),
            "CRM: guarantees (on materialized)",
            results,
        )
    else:
        exposures = _time(
            lambda: exposures.collect().lazy(),
            "CRM: collect #2 (post-collateral)",
            results,
        )

    # 3i: Finalize + audit
    exposures = _time(
        lambda: crm._finalize_ead(exposures),
        "CRM: finalize_ead",
        results,
    )
    exposures = _time(
        lambda: crm._add_crm_audit(exposures),
        "CRM: audit trail",
        results,
    )

    # --- Stage 4: Pre-split collect ---
    exposures = _time(
        lambda: exposures.collect().lazy(),
        "Pipeline: collect #3 (pre-split)",
        results,
    )

    # --- Stage 5: SA unified (if output floor) ---
    sa_calc = SACalculator()
    irb_calc = IRBCalculator()
    slotting_calc = SlottingCalculator()

    if config.output_floor.enabled:
        exposures = _time(
            lambda: sa_calc.calculate_unified(exposures, config),
            "SA: calculate_unified (floor)",
            results,
        )

    # --- Stage 6: Approach split + calculators ---
    from rwa_calc.domain.enums import ApproachType

    is_irb = (pl.col("approach") == ApproachType.FIRB.value) | (
        pl.col("approach") == ApproachType.AIRB.value
    )
    is_slotting = pl.col("approach") == ApproachType.SLOTTING.value

    sa_branch = exposures.filter(~is_irb & ~is_slotting)
    irb_branch = exposures.filter(is_irb)
    slotting_branch = exposures.filter(is_slotting)

    # Time lazy plan construction for each calculator
    if config.output_floor.enabled:
        sa_result = sa_branch
    else:
        sa_result = _time(
            lambda: sa_calc.calculate_branch(sa_branch, config),
            "SA: calculate_branch (lazy)",
            results,
        )

    irb_result = _time(
        lambda: irb_calc.calculate_branch(irb_branch, config),
        "IRB: calculate_branch (lazy)",
        results,
    )
    slotting_result = _time(
        lambda: slotting_calc.calculate_branch(slotting_branch, config),
        "Slotting: calculate_branch (lazy)",
        results,
    )

    # Standardize output columns
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    sa_result = PipelineOrchestrator._standardize_branch_output(sa_result)
    irb_result = PipelineOrchestrator._standardize_branch_output(irb_result)
    slotting_result = PipelineOrchestrator._standardize_branch_output(slotting_result)

    # --- Stage 7: collect_all ---
    sa_df, irb_df, slotting_df = _time(
        lambda: pl.collect_all([sa_result, irb_result, slotting_result]),
        "collect_all (SA+IRB+Slotting)",
        results,
    )

    # --- Stage 8: Aggregation ---
    from rwa_calc.engine.aggregator import OutputAggregator

    aggregator = OutputAggregator()

    def _run_aggregation():
        return aggregator.aggregate(
            sa_results=sa_df.lazy(),
            irb_results=irb_df.lazy(),
            slotting_results=slotting_df.lazy(),
            equity_bundle=None,
            config=config,
        )

    _time(_run_aggregation, "Aggregation", results)

    return results


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _print_results(results: list[tuple[str, float]], run_label: str = "") -> None:
    """Print a formatted table of stage timings."""
    total = sum(ms for _, ms in results)

    if run_label:
        print(f"\n{'=' * 72}")
        print(f"  {run_label}")
        print(f"{'=' * 72}")

    print(f"\n  {'Stage':<42} {'Time (ms)':>10} {'%':>7} {'Cum %':>7}")
    print(f"  {'-' * 42} {'-' * 10} {'-' * 7} {'-' * 7}")

    cumulative = 0.0
    for label, ms in results:
        pct = (ms / total * 100) if total > 0 else 0
        cumulative += pct
        print(f"  {label:<42} {ms:>10.1f} {pct:>6.1f}% {cumulative:>6.1f}%")

    print(f"  {'-' * 42} {'-' * 10}")
    print(f"  {'TOTAL':<42} {total:>10.1f}")

    # Show row counts
    print()


def _print_summary(all_runs: list[list[tuple[str, float]]]) -> None:
    """Print aggregated summary across runs."""
    if len(all_runs) < 2:
        return

    # Aggregate by stage name
    stage_names = [label for label, _ in all_runs[0]]
    print(f"\n{'=' * 72}")
    print(f"  SUMMARY ({len(all_runs)} runs)")
    print(f"{'=' * 72}")
    print(f"\n  {'Stage':<42} {'Min':>8} {'Mean':>8} {'Max':>8}")
    print(f"  {'-' * 42} {'-' * 8} {'-' * 8} {'-' * 8}")

    for stage in stage_names:
        times = []
        for run in all_runs:
            for label, ms in run:
                if label == stage:
                    times.append(ms)
                    break
        if times:
            print(
                f"  {stage:<42} {min(times):>8.1f} "
                f"{sum(times) / len(times):>8.1f} {max(times):>8.1f}"
            )

    totals = [sum(ms for _, ms in run) for run in all_runs]
    print(f"  {'-' * 42} {'-' * 8} {'-' * 8} {'-' * 8}")
    print(
        f"  {'TOTAL':<42} {min(totals):>8.1f} {sum(totals) / len(totals):>8.1f} {max(totals):>8.1f}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile RWA pipeline stages")
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="Path to parquet data directory (default: synthetic 100K)",
    )
    parser.add_argument(
        "--framework",
        choices=["crr", "basel31"],
        default="crr",
        help="Regulatory framework (default: crr)",
    )
    parser.add_argument(
        "--irb",
        choices=["none", "full"],
        default="full",
        help="IRB permissions (default: full)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of profiling runs (default: 3)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default="2026-01-01",
        help="Reporting date YYYY-MM-DD (default: 2026-01-01)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reporting_date = date.fromisoformat(args.date)

    # Load data
    if args.path:
        print(f"Loading parquet data from: {args.path}")
        raw_data = _load_from_parquet(args.path)
    else:
        raw_data = _load_synthetic_100k()

    # Build config
    perm_mode = {
        "none": PermissionMode.STANDARDISED,
        "full": PermissionMode.IRB,
    }[args.irb]

    if args.framework == "basel31":
        config = CalculationConfig.basel_3_1(reporting_date, permission_mode=perm_mode)
    else:
        config = CalculationConfig.crr(reporting_date, permission_mode=perm_mode)

    print(f"Framework: {args.framework}, IRB: {args.irb}, Date: {reporting_date}")
    print(f"Running {args.runs} profiling run(s)...")

    # Profile
    all_runs = []
    for i in range(args.runs):
        results = profile_pipeline_stages(raw_data, config)
        all_runs.append(results)
        total = sum(ms for _, ms in results)
        print(f"  run {i + 1}: {total:.0f}ms")

    # Print detailed results for best run
    best_idx = min(range(len(all_runs)), key=lambda i: sum(ms for _, ms in all_runs[i]))
    _print_results(all_runs[best_idx], f"Best run (run {best_idx + 1})")

    # Print summary across runs
    _print_summary(all_runs)


if __name__ == "__main__":
    main()
