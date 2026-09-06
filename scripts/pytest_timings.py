"""
Per-test timing capture and report for the pytest estate.

Two roles in one module, so the measurement that backs
``docs/plans/test-suite-runtime-proposal.md`` is reproducible from the repo
rather than from a scratch directory:

1. **pytest plugin** — load with ``-p`` and it records every test's setup /
   call / teardown duration, tagged with the xdist worker that ran it, into a
   JSON file. The hook runs on the controller, where xdist forwards every
   worker's ``TestReport``, so one file covers the whole fleet::

       PYTHONPATH=scripts PERF_SLOT=before uv run pytest tests/ -p pytest_timings

2. **report CLI** — summarise that capture: where the time goes by band, by
   directory, by file, by phase, by worker (busy time vs the loadfile tail)::

       uv run python scripts/pytest_timings.py --slot before

Captures go to named slots under ``.pytest_timings/`` (git-ignored) rather than
to a caller-supplied path: an operator string — argv or an environment variable —
must never construct a path here, because the security taint analysis treats both
as attacker-controlled and the resulting finding fails the ``new_security_rating``
quality gate (the sibling rule is arch_check check 19). ``PERF_SLOT`` and
``--slot`` NAME a slot; the name indexes a literal mapping and the value used is
a constant. A caller needing another location imports :func:`report`.

Nothing here changes what runs or how it is asserted; it only observes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

_RECORDS: list[dict[str, Any]] = []
_T0 = time.time()

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: Named capture slots. ``PERF_SLOT`` / ``--slot`` select one of these constants
#: BY NAME; no operator string is ever used to construct a path.
_SLOT_ROOT = _REPO_ROOT / ".pytest_timings"
_SLOTS: dict[str, Path] = {
    name: _SLOT_ROOT / f"{name}.json" for name in ("before", "after", "current")
}
_DEFAULT_SLOT = "current"

# Per-test totals bucketed by wall time. The top band is what "about a second"
# tests look like from the outside; the bottom band is what pytest's own
# per-test overhead looks like.
_BANDS: tuple[tuple[float, float], ...] = (
    (0.0, 0.01),
    (0.01, 0.05),
    (0.05, 0.1),
    (0.1, 0.25),
    (0.25, 0.5),
    (0.5, 1.0),
    (1.0, 2.0),
    (2.0, 5.0),
    (5.0, float("inf")),
)


# =============================================================================
# pytest plugin hooks
# =============================================================================


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Record one phase (setup / call / teardown) of one test."""
    node = getattr(report, "node", None)
    gateway = getattr(node, "gateway", None) if node is not None else None
    worker = getattr(gateway, "id", None) or "main"
    _RECORDS.append(
        {
            "nodeid": report.nodeid,
            "when": report.when,
            "outcome": report.outcome,
            "duration": report.duration,
            "recv": time.time() - _T0,
            "worker": worker,
        }
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Write the capture on the controller only (workers hold a partial view).

    ``PERF_SLOT`` names a slot; an unknown name falls back to the default rather
    than becoming a path, so the written location is always one of the constants
    in ``_SLOTS``.
    """
    if hasattr(session.config, "workerinput"):
        return
    out = _SLOTS.get(os.environ.get("PERF_SLOT", _DEFAULT_SLOT), _SLOTS[_DEFAULT_SLOT])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"wall": time.time() - _T0, "records": _RECORDS}), encoding="utf-8")
    print(f"\npytest_timings: wrote {out}")


# =============================================================================
# Report
# =============================================================================


def report(path: Path, *, top: int = 40) -> None:
    """Print the timing summary for one capture file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = data["records"]
    wall: float = data["wall"]

    per_test = _per_test_phases(records)
    grand = sum(sum(v.values()) for v in per_test.values())
    by_phase = {
        phase: sum(v[phase] for v in per_test.values()) for phase in ("setup", "call", "teardown")
    }
    print(
        f"tests={len(per_test)} wall={wall:.0f}s "
        f"setup={by_phase['setup']:.0f}s call={by_phase['call']:.0f}s "
        f"teardown={by_phase['teardown']:.0f}s total={grand:.0f}s"
    )

    _print_bands(per_test, grand)
    _print_grouped(per_test, _top_level_dir, "per top-level dir", limit=None)
    _print_grouped(per_test, _file_of, f"top {top} files by total time", limit=top)
    _print_workers(records)
    _print_slowest(per_test, top)
    _print_setup_heavy(per_test, 20)


def _per_test_phases(records: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    per_test: dict[str, dict[str, float]] = defaultdict(
        lambda: {"setup": 0.0, "call": 0.0, "teardown": 0.0}
    )
    for rec in records:
        per_test[rec["nodeid"]][rec["when"]] += rec["duration"]
    return per_test


def _file_of(nodeid: str) -> str:
    return nodeid.split("::")[0]


def _top_level_dir(nodeid: str) -> str:
    parts = _file_of(nodeid).split("/")
    return "/".join(parts[:2]) if len(parts) > 2 else parts[0]


def _print_bands(per_test: dict[str, dict[str, float]], grand: float) -> None:
    print("\n=== distribution of per-test total (setup+call+teardown) ===")
    print(f"{'band':>14} {'count':>7} {'sum_s':>8} {'cum%':>6}")
    cum = 0.0
    for lo, hi in _BANDS:
        totals = [sum(v.values()) for v in per_test.values() if lo <= sum(v.values()) < hi]
        cum += sum(totals)
        label = f"{lo}-{'inf' if hi == float('inf') else hi}"
        print(f"{label:>14} {len(totals):>7} {sum(totals):>8.1f} {100 * cum / grand:>5.1f}%")


def _print_grouped(
    per_test: dict[str, dict[str, float]],
    key_of: Any,
    title: str,
    *,
    limit: int | None,
) -> None:
    grouped: dict[str, dict[str, float]] = defaultdict(
        lambda: {"setup": 0.0, "call": 0.0, "teardown": 0.0, "n": 0.0}
    )
    for nodeid, phases in per_test.items():
        key = key_of(nodeid)
        for phase, secs in phases.items():
            grouped[key][phase] += secs
        grouped[key]["n"] += 1
    ranked = sorted(
        grouped.items(), key=lambda kv: -(kv[1]["setup"] + kv[1]["call"] + kv[1]["teardown"])
    )
    print(f"\n=== {title} ===")
    for key, v in ranked[:limit]:
        total = v["setup"] + v["call"] + v["teardown"]
        print(
            f"{total:>7.1f}s n={int(v['n']):>5} setup={v['setup']:>6.1f} "
            f"call={v['call']:>7.1f} {key}"
        )


def _print_workers(records: list[dict[str, Any]]) -> None:
    busy: dict[str, float] = defaultdict(float)
    first: dict[str, float] = defaultdict(lambda: float("inf"))
    last: dict[str, float] = defaultdict(float)
    for rec in records:
        worker = rec["worker"]
        busy[worker] += rec["duration"]
        first[worker] = min(first[worker], rec["recv"])
        last[worker] = max(last[worker], rec["recv"])
    print("\n=== per worker: busy seconds, first report (collection), last report (tail) ===")
    for worker in sorted(busy):
        print(
            f"{worker:<6} busy={busy[worker]:>7.1f}s first={first[worker]:>6.1f}s "
            f"last={last[worker]:>6.1f}s"
        )


def _print_slowest(per_test: dict[str, dict[str, float]], top: int) -> None:
    print(f"\n=== top {top} slowest tests ===")
    ranked = sorted(per_test.items(), key=lambda kv: -sum(kv[1].values()))
    for nodeid, v in ranked[:top]:
        print(f"{sum(v.values()):>6.2f}s setup={v['setup']:>5.2f} call={v['call']:>6.2f} {nodeid}")


def _print_setup_heavy(per_test: dict[str, dict[str, float]], top: int) -> None:
    setup: dict[str, float] = defaultdict(float)
    for nodeid, v in per_test.items():
        setup[_file_of(nodeid)] += v["setup"]
    print(f"\n=== top {top} files by SETUP time (fixture cost) ===")
    for key, secs in sorted(setup.items(), key=lambda kv: -kv[1])[:top]:
        print(f"setup={secs:>6.1f}s {key}")


def main() -> int:
    """Report on one named slot.

    ``--slot`` selects a constant from ``_SLOTS``; argv never constructs a path.
    A caller needing another location imports :func:`report` and passes a
    ``Path`` it built itself.
    """
    parser = argparse.ArgumentParser(description="Summarise a pytest timing capture.")
    parser.add_argument("--slot", choices=sorted(_SLOTS), default=_DEFAULT_SLOT)
    parser.add_argument("--top", type=int, default=40)
    args = parser.parse_args()
    capture = _SLOTS[args.slot]
    if not capture.is_file():
        print(f"no capture in slot {args.slot!r} — run pytest with PERF_SLOT={args.slot} first")
        return 2
    report(capture, top=args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
