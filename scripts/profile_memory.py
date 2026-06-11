"""
Memory profile: in-memory stage edges vs spill-to-parquet edges.

Operator tooling for the migration plan's measured-memory decision gate
(docs/plans/target-architecture-migration.md, Phase 1): runs the full
pipeline over a synthetic dataset twice — once with default in-memory edge
materialisation, once with ``spill_edges=True`` — and reports, per mode:

- peak process RSS (sampled ~every 50 ms by the parent; needs ``psutil``,
  degrades to "n/a" with a clear message when it is not installed)
- total pipeline wall time
- the per-edge rows / bytes / wall-time breakdown from the run manifest's
  ``materialisation_map`` (the run writes an audit cache into a temp dir)

Each mode runs in a fresh subprocess so allocator retention from the first
run cannot inflate the second run's RSS. Peak RSS is poll-sampled, so very
short allocation spikes (< ~50 ms) can be missed — treat the numbers as a
comparative gate, not an exact high-water mark.

The synthetic dataset reuses the benchmark generator
(tests/benchmarks/data_generators.py); ``--rows`` is the target *loan* row
count (the generator emits ~3 loans per counterparty, plus contingents).

Usage:
    uv run python scripts/profile_memory.py                 # 100k loan rows
    uv run python scripts/profile_memory.py --rows 5000
    uv run python scripts/profile_memory.py --framework basel31 --seed 7
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ROWS = 100_000
# tests/benchmarks/data_generators.py BenchmarkDataConfig.loans_per_counterparty
LOANS_PER_COUNTERPARTY = 3
RSS_SAMPLE_INTERVAL_S = 0.05
MODES = ("in-memory", "spill")
_MIB = 1024 * 1024

PSUTIL_MISSING_MSG = (
    "psutil is not installed - peak RSS will be reported as 'n/a'. "
    "Install the dev group (uv sync) or `uv add --group dev psutil` to enable RSS sampling."
)


# ---------------------------------------------------------------------------
# Entry point (parent process)
# ---------------------------------------------------------------------------


def main() -> int:
    """Run both modes in subprocesses, sample RSS, print the comparison."""
    args = _parse_args()

    if args.worker_mode:
        return _run_worker(args)

    try:
        import psutil  # noqa: F401 — availability probe only
    except ImportError:
        psutil = None  # type: ignore[assignment]
        print(PSUTIL_MISSING_MSG)

    print(
        f"Profiling pipeline memory: rows={args.rows:,} framework={args.framework} "
        f"seed={args.seed} date={args.date}"
    )

    results: list[ModeResult] = []
    for mode in MODES:
        print(f"\n--- mode: {mode} ---")
        results.append(_profile_mode(mode, args, rss_available=psutil is not None))

    _print_comparison(results)
    return 0


# ---------------------------------------------------------------------------
# Per-mode subprocess driver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModeResult:
    """Measured outcome of one profiled mode."""

    mode: str
    peak_rss_bytes: int | None
    wall_s: float
    table_rows: dict[str, int]
    edge_map: list[dict[str, Any]]


def _profile_mode(mode: str, args: argparse.Namespace, *, rss_available: bool) -> ModeResult:
    """Spawn a worker for one mode, sample its RSS until exit, read its result."""
    with tempfile.TemporaryDirectory(prefix="rwa_profile_") as tmp:
        result_json = Path(tmp) / "result.json"
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker-mode",
            mode,
            "--rows",
            str(args.rows),
            "--seed",
            str(args.seed),
            "--framework",
            args.framework,
            "--date",
            args.date,
            "--result-json",
            str(result_json),
        ]
        # PYTHONHASHSEED pinned so set/dict iteration order in the dataset
        # generator cannot differ between the two worker processes.
        env = {**os.environ, "PYTHONHASHSEED": "0"}
        proc = subprocess.Popen(cmd, cwd=REPO_ROOT, env=env)
        peak_rss = _sample_peak_rss(proc) if rss_available else _wait_only(proc)
        if proc.returncode != 0:
            raise RuntimeError(f"worker for mode '{mode}' exited with {proc.returncode}")

        payload = json.loads(result_json.read_text(encoding="utf-8"))

    return ModeResult(
        mode=mode,
        peak_rss_bytes=peak_rss,
        wall_s=payload["wall_s"],
        table_rows=payload["table_rows"],
        edge_map=payload["edge_map"],
    )


def _sample_peak_rss(proc: subprocess.Popen[bytes]) -> int:
    """Poll the worker's RSS every ~50 ms until it exits; return the max seen.

    Sums RSS over the spawned process AND its descendants: on Windows a uv
    venv's ``python.exe`` is a small trampoline (~4 MiB) that runs the real
    interpreter as a child, so sampling only ``proc.pid`` measures the shim.
    """
    import psutil

    peak = 0
    try:
        ps_proc = psutil.Process(proc.pid)
        while proc.poll() is None:
            rss = 0
            for candidate in (ps_proc, *_children_of(ps_proc)):
                try:
                    rss += candidate.memory_info().rss
                except psutil.NoSuchProcess:
                    continue
            peak = max(peak, rss)
            time.sleep(RSS_SAMPLE_INTERVAL_S)
    except psutil.NoSuchProcess:
        pass  # worker exited between poll() and the first sample
    finally:
        proc.wait()
    return peak


def _children_of(ps_proc: Any) -> list[Any]:
    """Live descendants of a psutil process (empty when it has gone away)."""
    import psutil

    try:
        return ps_proc.children(recursive=True)
    except psutil.NoSuchProcess:
        return []


def _wait_only(proc: subprocess.Popen[bytes]) -> None:
    """Fallback when psutil is unavailable: just wait for the worker."""
    proc.wait()
    return None


# ---------------------------------------------------------------------------
# Worker (one pipeline run in a fresh process)
# ---------------------------------------------------------------------------


def _run_worker(args: argparse.Namespace) -> int:
    """Generate the dataset, run the pipeline once, write the result JSON."""
    from dataclasses import replace

    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    # The benchmark generator lives under tests/; scripts/ is invoked from the
    # repo root via `uv run`, but the script's own directory is sys.path[0],
    # so the repo root must be added before `tests` becomes importable.
    sys.path.insert(0, str(REPO_ROOT))
    from tests.benchmarks.data_generators import generate_benchmark_dataset
    from tests.benchmarks.test_pipeline_benchmark import create_raw_data_bundle

    n_counterparties = max(args.rows // LOANS_PER_COUNTERPARTY, 10)
    dataset = generate_benchmark_dataset(n_counterparties=n_counterparties, seed=args.seed)
    # Materialise the generated inputs before timing so dataset generation is
    # not attributed to the pipeline (both modes pay the same baseline RSS).
    materialised = {name: lf.collect() for name, lf in dataset.items()}
    table_rows = {name: df.height for name, df in materialised.items()}
    bundle = create_raw_data_bundle({name: df.lazy() for name, df in materialised.items()})

    reporting_date = date.fromisoformat(args.date)
    with tempfile.TemporaryDirectory(prefix="rwa_profile_audit_") as audit_tmp:
        audit_dir = Path(audit_tmp) / "audit"
        factory = (
            CalculationConfig.basel_3_1 if args.framework == "basel31" else CalculationConfig.crr
        )
        # Default (standardised) permission mode: the benchmark dataset has no
        # model_permissions table, so IRB mode would route everything to SA
        # anyway and emit a misleading warning.
        config = factory(
            reporting_date=reporting_date,
            audit_cache_dir=audit_dir,
            log_level="WARNING",  # keep stage INFO logs out of the report
        )
        if args.worker_mode == "spill":
            spill_dir = Path(audit_tmp) / "spill"
            spill_dir.mkdir()
            config = replace(config, spill_edges=True, spill_dir=spill_dir)

        started = time.perf_counter()
        result = PipelineOrchestrator().run_with_data(bundle, config)
        wall_s = time.perf_counter() - started
        if result.results is None:
            raise RuntimeError("pipeline returned no results frame")

        manifests = sorted(audit_dir.glob("*/manifest.json"))
        if not manifests:
            raise RuntimeError(f"no manifest.json written under {audit_dir}")
        manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))

    payload = {
        "mode": args.worker_mode,
        "wall_s": wall_s,
        "table_rows": table_rows,
        "edge_map": manifest["materialisation_map"],
    }
    Path(args.result_json).write_text(json.dumps(payload), encoding="utf-8")
    return 0


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def _print_comparison(results: list[ModeResult]) -> None:
    """Print the per-mode summary table and per-edge breakdowns."""
    first = results[0]
    input_summary = ", ".join(f"{name}={n:,}" for name, n in sorted(first.table_rows.items()))
    print(f"\nInput rows: {input_summary}")

    print(f"\n{'Mode':<12} {'Peak RSS (MiB)':>16} {'Pipeline wall (s)':>19}")
    print(f"{'-' * 12} {'-' * 16} {'-' * 19}")
    for res in results:
        rss = f"{res.peak_rss_bytes / _MIB:.1f}" if res.peak_rss_bytes is not None else "n/a"
        print(f"{res.mode:<12} {rss:>16} {res.wall_s:>19.2f}")

    if all(r.peak_rss_bytes is not None for r in results) and len(results) == 2:
        delta = results[0].peak_rss_bytes - results[1].peak_rss_bytes  # type: ignore[operator]
        print(
            f"\nSpill mode peak RSS delta vs in-memory: {-delta / _MIB:+.1f} MiB "
            f"({-delta / results[0].peak_rss_bytes * 100:+.1f}%)"  # type: ignore[operator]
        )

    for res in results:
        _print_edge_table(res)


def _print_edge_table(res: ModeResult) -> None:
    """Print one mode's per-edge materialisation map."""
    # ASCII-only output: Windows consoles often decode as cp1252.
    print(f"\nPer-edge materialisation map [{res.mode}]:")
    print(f"  {'edge':<28} {'rows':>10} {'MiB':>9} {'wall_ms':>10} {'spilled':>8}")
    print(f"  {'-' * 28} {'-' * 10} {'-' * 9} {'-' * 10} {'-' * 8}")
    for event in res.edge_map:
        print(
            f"  {event['label']:<28} {event['rows']:>10,} "
            f"{event['estimated_bytes'] / _MIB:>9.2f} {event['wall_ms']:>10.1f} "
            f"{'yes' if event['spilled'] else 'no':>8}"
        )
    total_ms = sum(e["wall_ms"] for e in res.edge_map)
    total_bytes = sum(e["estimated_bytes"] for e in res.edge_map)
    print(f"  {'-' * 28} {'-' * 10} {'-' * 9} {'-' * 10}")
    print(f"  {'TOTAL (edges)':<28} {'':>10} {total_bytes / _MIB:>9.2f} {total_ms:>10.1f}")


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile pipeline peak RSS: in-memory vs spill-to-parquet stage edges."
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=DEFAULT_ROWS,
        help=f"Target loan row count for the synthetic dataset (default: {DEFAULT_ROWS:,})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for the synthetic dataset (default: 42)",
    )
    parser.add_argument(
        "--framework",
        choices=["crr", "basel31"],
        default="crr",
        help="Regulatory framework (default: crr)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default="2026-01-01",
        help="Reporting date YYYY-MM-DD (default: 2026-01-01)",
    )
    # Internal flags used for the per-mode worker subprocess.
    parser.add_argument("--worker-mode", choices=list(MODES), default=None, help=argparse.SUPPRESS)
    parser.add_argument("--result-json", type=str, default=None, help=argparse.SUPPRESS)
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
