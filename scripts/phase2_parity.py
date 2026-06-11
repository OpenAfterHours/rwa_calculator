"""
Phase 2 parity gate: byte-identical RWA on the 10k stress set.

Migration Phase 2 (docs/plans/target-architecture-migration.md) deletes dead
code paths and must not move a single output number. This harness captures a
full snapshot of the pipeline output on the deterministic 10k stress dataset
(all four framework/permission configs) before the deletions, then re-runs and
compares after: every output frame exactly equal, error lists allowed to GROW
only (restored branch-path accumulation), never shrink or mutate.

Usage:
    uv run python scripts/phase2_parity.py capture --out <dir>
    uv run python scripts/phase2_parity.py compare --baseline <dir>

References:
- docs/plans/target-architecture-migration.md (Phase 2 validation)
- tests/acceptance/stress/conftest.py (deterministic dataset builders)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tests.acceptance.stress.conftest import (  # noqa: E402
    STRESS_REPORTING_DATE,
    build_stress_dataset,
    run_pipeline,
)

from rwa_calc.contracts.bundles import AggregatedResultBundle  # noqa: E402
from rwa_calc.contracts.config import CalculationConfig  # noqa: E402
from rwa_calc.domain.enums import PermissionMode  # noqa: E402

N_COUNTERPARTIES = 10_000
SEED = 42

# Aggregate-sum frames: Polars' multi-threaded group-by float summation is
# NOT deterministic across processes (verified 2026-06-12: two fresh runs of
# identical code differ in the last 1-2 ulps of 41k-row sums). Per-row frames
# are compared exactly; these are compared to within float-reassociation
# tolerance only.
_SUM_AGGREGATE_FRAMES = {
    "pre_crm_summary",
    "post_crm_summary",
    "summary_by_class",
    "summary_by_approach",
    "securitisation_summary",
}

# Every LazyFrame-valued field on AggregatedResultBundle is snapshotted.
_FRAME_FIELDS = [
    "results",
    "sa_results",
    "irb_results",
    "slotting_results",
    "equity_results",
    "floor_impact",
    "supporting_factor_impact",
    "summary_by_class",
    "summary_by_approach",
    "pre_crm_summary",
    "post_crm_detailed",
    "post_crm_summary",
    "securitisation_summary",
    "securitisation_audit",
]


def _configs() -> dict[str, CalculationConfig]:
    return {
        "crr_sa": CalculationConfig.crr(
            reporting_date=STRESS_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        ),
        "crr_irb": CalculationConfig.crr(
            reporting_date=STRESS_REPORTING_DATE,
            permission_mode=PermissionMode.IRB,
        ),
        "b31_sa": CalculationConfig.basel_3_1(
            reporting_date=STRESS_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        ),
        "b31_irb": CalculationConfig.basel_3_1(
            reporting_date=STRESS_REPORTING_DATE,
            permission_mode=PermissionMode.IRB,
        ),
    }


def _canonical(df: pl.DataFrame) -> pl.DataFrame:
    """Sort rows by every sortable column so snapshots are order-independent."""
    sortable = [
        name
        for name, dtype in df.schema.items()
        if not isinstance(dtype, (pl.List, pl.Struct, pl.Array))
    ]
    return df.sort(sortable) if sortable else df


def _error_counts(result: AggregatedResultBundle) -> dict[str, int]:
    counts = Counter(
        f"{err.category.value}|{err.severity.value}|{err.code}" for err in result.errors
    )
    return dict(sorted(counts.items()))


def _snapshot_run(name: str, config: CalculationConfig) -> tuple[dict[str, pl.DataFrame], dict]:
    dataset = build_stress_dataset(N_COUNTERPARTIES, seed=SEED)
    result = run_pipeline(dataset, config)

    frames: dict[str, pl.DataFrame] = {}
    for field_name in _FRAME_FIELDS:
        lf = getattr(result, field_name)
        if lf is None:
            continue
        frames[field_name] = _canonical(lf.collect())

    meta = {
        "run": name,
        "polars": pl.__version__,
        "rows": {field_name: df.height for field_name, df in frames.items()},
        "errors": _error_counts(result),
    }
    return frames, meta


def capture(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, config in _configs().items():
        frames, meta = _snapshot_run(name, config)
        run_dir = out_dir / name
        run_dir.mkdir(exist_ok=True)
        for field_name, df in frames.items():
            df.write_parquet(run_dir / f"{field_name}.parquet")
        (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(
            f"[capture] {name}: {meta['rows']['results']} result rows, "
            f"{sum(meta['errors'].values())} errors -> {run_dir}"
        )


def compare(baseline_dir: Path) -> int:
    failures: list[str] = []
    for name, config in _configs().items():
        run_dir = baseline_dir / name
        if not run_dir.exists():
            failures.append(f"{name}: no baseline at {run_dir}")
            continue
        frames, meta = _snapshot_run(name, config)
        baseline_meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))

        baseline_frames = {p.stem for p in run_dir.glob("*.parquet")}
        current_frames = set(frames)
        for missing in sorted(baseline_frames - current_frames):
            failures.append(f"{name}/{missing}: frame present in baseline, absent now")
        for added in sorted(current_frames - baseline_frames):
            failures.append(f"{name}/{added}: frame absent in baseline, present now")

        for field_name in sorted(baseline_frames & current_frames):
            expected = pl.read_parquet(run_dir / f"{field_name}.parquet")
            try:
                if field_name in _SUM_AGGREGATE_FRAMES:
                    assert_frame_equal(
                        frames[field_name],
                        expected,
                        check_exact=False,
                        rtol=1e-9,
                        atol=1e-6,
                    )
                else:
                    assert_frame_equal(frames[field_name], expected, check_exact=True)
            except AssertionError as exc:
                failures.append(f"{name}/{field_name}: NOT identical\n{exc}")

        # Error lists may grow (restored accumulation) but never shrink/mutate.
        before_errors: dict[str, int] = baseline_meta["errors"]
        after_errors = meta["errors"]
        for key, before_count in before_errors.items():
            after_count = after_errors.get(key, 0)
            if after_count < before_count:
                failures.append(f"{name}: error {key} shrank {before_count} -> {after_count}")
        grown = {
            key: (before_errors.get(key, 0), count)
            for key, count in after_errors.items()
            if count > before_errors.get(key, 0)
        }
        status = "OK" if not any(f.startswith(name) for f in failures) else "FAIL"
        print(f"[compare] {name}: {status}" + (f" (errors grew: {grown})" if grown else ""))

    if failures:
        print("\n=== PARITY FAILURES ===")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("\nParity gate PASSED: all frames byte-identical, error lists monotone.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    cap = sub.add_parser("capture", help="snapshot the current outputs")
    cap.add_argument("--out", type=Path, required=True)
    cmp_ = sub.add_parser("compare", help="re-run and compare to a baseline")
    cmp_.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()

    if args.mode == "capture":
        capture(args.out)
        return 0
    return compare(args.baseline)


if __name__ == "__main__":
    raise SystemExit(main())
