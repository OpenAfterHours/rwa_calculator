"""
Numeric change-impact report — what moved, where, and who accounted for it.

Pipeline position:
    reporting fixture portfolios x {CRR, Basel 3.1}
        -> PipelineOrchestrator -> AggregatedResultBundle
        -> COREPGenerator / Pillar3Generator
        -> four-grain snapshot -> diff against a captured baseline

Key responsibilities:
- Capture a snapshot of everything a change could move, at four grains:
    1. ``total``  total RWA / EAD / leg count per (regime, portfolio) plus a
                  per-regime roll-up — the headline movement;
    2. ``class``  RWA by (sealed ``reporting_approach``, ``reporting_class``) —
                  where it moved;
    3. ``cell``   every generated COREP / Pillar 3 template cell, keyed
                  ``(regime, portfolio, template, sheet, row, col)`` — the grain
                  at which reporting defects actually appear;
    4. ``error``  the ``(category, severity, code)`` histogram.
- Diff two snapshots and report **appeared** / **disappeared** / **nulled** /
  **populated** cells separately from **changed** ones. Absence is this
  project's dominant escape class (``.claude/LESSONS.md`` B4/B6): a naive diff
  hides a vanished cell as "not in the comparison set", so a cell that goes
  non-null -> null is a headline here, not a footnote.
- Block on **unexplained** movement. Movement itself is not a failure; movement
  nobody has written a reason for is. ``scripts/impact_allowlist.json`` is the
  register of accepted movements, in the same preserve-or-fix style as the
  reporting goldens and the supervisory validation register.

Why this is not ``scripts/parity_gate.py``:
    ``parity_gate`` proves a refactor moved *nothing*, over the 10k stress set,
    at per-row grain. It has no template-cell grain at all, and it is only run
    for migration phases that are meant to be numerically inert. This harness is
    the standing report for every change: it *expects* movement and demands an
    account of it. The two are complementary; ``parity_gate`` is untouched.

Why the reporting fixture portfolios and not the stress set:
    They are small enough to run in-process without exhausting memory, and each
    one produces BOTH a full pipeline result AND generated templates — so all
    four grains come from one set of runs. The run matrix is imported from
    ``tests/acceptance/reporting/test_supervisory_validations.py::RUNS`` rather
    than restated, so a portfolio added for the supervisory gate is covered here
    automatically (``.claude/LESSONS.md`` B5: a silently reduced matrix is how
    coverage rots).

Usage:
    uv run python scripts/impact_report.py capture --out <dir>
    uv run python scripts/impact_report.py compare --baseline <dir> \
        [--current <dir>] [--markdown <path>] [--json <path>] [--stale-check]

Exit codes:
    0 = no movement, or every movement is allowlisted
    1 = unexplained movement
    2 = usage error, missing baseline, or a malformed allowlist entry
    3 = stale allowlist entries (only with --stale-check, and only when there
        is no unexplained movement — an unexplained movement outranks it)

References:
- docs/plans/independent-validation-system.md (C1)
- docs/development/impact-report.md (operator guide)
- .claude/LESSONS.md B4/B6 (absence), E1 (preserve-or-fix decisions)
"""

from __future__ import annotations

import argparse
import dataclasses
import fnmatch
import json
import math
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Snapshots live inside the repo or in a sibling baseline directory; confine
# every CLI-supplied path to the repo's parent so a faulty argument cannot read
# or write elsewhere. Duplicated from scripts/parity_gate.py rather than
# imported — that module runs the 10k stress dataset at import-adjacent scope
# and this harness must stay independent of it.
_ALLOWED_ROOT = REPO_ROOT.parent

from tests.acceptance.reporting.test_supervisory_validations import RUNS  # noqa: E402

from rwa_calc.engine.pipeline import PipelineOrchestrator  # noqa: E402
from rwa_calc.reporting.corep.generator import COREPGenerator  # noqa: E402
from rwa_calc.reporting.pillar3.generator import Pillar3Generator  # noqa: E402

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Float comparison tolerance. Polars' multi-threaded Float64 group-by summation
#: is NOT deterministic across processes (the Phase 2 parity finding), so an
#: exact comparison of an aggregate would report movement that no change caused.
#: These are the established project figures (scripts/parity_gate.py).
RTOL = 1e-9
ATOL = 1e-6

GRAIN_TOTAL = "total"
GRAIN_CLASS = "class"
GRAIN_CELL = "cell"
GRAIN_ERROR = "error"
GRAINS: tuple[str, ...] = (GRAIN_TOTAL, GRAIN_CLASS, GRAIN_CELL, GRAIN_ERROR)

GRAIN_TITLES: dict[str, str] = {
    GRAIN_TOTAL: "Totals (per regime / portfolio)",
    GRAIN_CLASS: "RWA by (approach, exposure class)",
    GRAIN_CELL: "Template cells",
    GRAIN_ERROR: "Error-code histogram",
}

#: The coordinate fields behind each grain's ``|``-joined key, for the report.
GRAIN_KEY_FIELDS: dict[str, tuple[str, ...]] = {
    GRAIN_TOTAL: ("regime", "portfolio", "metric"),
    GRAIN_CLASS: ("regime", "portfolio", "approach", "exposure_class"),
    GRAIN_CELL: ("regime", "portfolio", "template", "sheet", "row", "col"),
    GRAIN_ERROR: ("regime", "portfolio", "category", "severity", "code"),
}

STATUS_CHANGED = "changed"
STATUS_APPEARED = "appeared"
STATUS_DISAPPEARED = "disappeared"
STATUS_NULLED = "nulled"
STATUS_POPULATED = "populated"

#: Reported FIRST and separately. A key that vanished, or a cell that stopped
#: carrying a figure, is invisible to any check that only compares the keys both
#: sides have (.claude/LESSONS.md B4/B6).
ABSENCE_STATUSES: tuple[str, ...] = (STATUS_DISAPPEARED, STATUS_NULLED)
PRESENCE_STATUSES: tuple[str, ...] = (STATUS_APPEARED, STATUS_POPULATED)
ALL_STATUSES: tuple[str, ...] = (*ABSENCE_STATUSES, *PRESENCE_STATUSES, STATUS_CHANGED)

#: Roll-up portfolio label used by the per-regime headline row.
ALL_PORTFOLIOS = "*ALL*"

#: Sheet label for a template that is a single frame rather than a per-class dict.
SINGLE_SHEET = "-"

ALLOWLIST_PATH = REPO_ROOT / "scripts" / "impact_allowlist.json"

#: An entry with no written reason is not an entry. Mirrors the goldens'
#: preserve-or-fix convention and the validation register's written-reason gate.
MIN_REASON_CHARS = 20
MIN_REASON_WORDS = 4
PLACEHOLDER_REASONS = frozenset(
    {
        "",
        "-",
        "--",
        "?",
        "n/a",
        "na",
        "none",
        "tbd",
        "todo",
        "fixme",
        "wip",
        "unknown",
        "unclassified",
        "expected",
        "as discussed",
        "see pr",
        "refactor",
        "no reason",
    }
)

#: The row axis of every generated template frame. ``row_name`` is deliberately
#: NOT excluded from the cell set: a row RE-LABEL is a movement worth reporting.
ROW_REF_COL = "row_ref"

_EXIT_OK = 0
_EXIT_UNEXPLAINED = 1
_EXIT_USAGE = 2
_EXIT_STALE = 3

_DEFAULT_TOP = 25


# ---------------------------------------------------------------------------
# Snapshot records
# ---------------------------------------------------------------------------


class Value(NamedTuple):
    """One snapshotted figure.

    ``dtype`` distinguishes a numeric cell from a string cell; ``num``/``text``
    are both ``None`` for a cell that EXISTS but carries no value. That
    distinction is the whole point: "present and null" and "absent" are
    different findings and are reported as different statuses.
    """

    dtype: str
    num: float | None
    text: str | None

    def is_null(self) -> bool:
        """True when the coordinate exists but carries no figure."""
        return self.num is None and self.text is None

    def render(self) -> str:
        """Human rendering for a report line."""
        if self.text is not None:
            return repr(self.text)
        if self.num is None:
            return "null"
        return f"{self.num:,.4f}"


@dataclasses.dataclass(frozen=True)
class Snapshot:
    """A captured run of the whole matrix, at all four grains."""

    meta: dict[str, Any]
    grains: dict[str, dict[str, Value]]


@dataclasses.dataclass(frozen=True)
class Movement:
    """One coordinate that differs between two snapshots."""

    grain: str
    key: str
    status: str
    before: Value | None
    after: Value | None
    delta: float | None
    relative: float | None

    @property
    def magnitude(self) -> float:
        """Absolute size of the movement, for "biggest first" ordering."""
        if self.delta is not None:
            return abs(self.delta)
        for side in (self.after, self.before):
            if side is not None and side.num is not None and math.isfinite(side.num):
                return abs(side.num)
        return 0.0

    def describe(self) -> str:
        """One-line rendering: coordinate, both figures, absolute + relative delta."""
        before = "-" if self.before is None else self.before.render()
        after = "-" if self.after is None else self.after.render()
        parts = [f"`{self.key}`", f"{before} -> {after}"]
        if self.delta is not None:
            parts.append(f"delta {self.delta:+,.4f}")
        if self.relative is not None:
            parts.append(f"({self.relative:+.4%})")
        return "  ".join(parts)


@dataclasses.dataclass(frozen=True)
class AllowEntry:
    """One recorded decision: a movement someone accounted for, in writing."""

    grain: str
    key: str
    reason: str
    accepted_under: str

    def matches(self, grain: str, key: str) -> bool:
        """Exact match, or ``fnmatch`` when the recorded key carries a glob."""
        if grain != self.grain:
            return False
        if any(ch in self.key for ch in "*?["):
            return fnmatch.fnmatchcase(key, self.key)
        return key == self.key


@dataclasses.dataclass(frozen=True)
class Comparison:
    """The full result of diffing two snapshots against the allowlist."""

    movements: list[Movement]
    allowed: dict[int, list[Movement]]
    unexplained: list[Movement]
    stale: list[AllowEntry]
    entries: list[AllowEntry]
    baseline_meta: dict[str, Any]
    current_meta: dict[str, Any]
    #: Set when the two sides did not run the same portfolio/regime matrix. Every
    #: coordinate from a dropped run then reads as "disappeared", which is true
    #: but is an artefact of the filter, not of the change under test.
    matrix_warning: str | None


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def capture(out_dir: Path, *, portfolios: set[str] | None, regimes: set[str] | None) -> Snapshot:
    """Run the matrix and write a snapshot to ``out_dir``."""
    snapshot = run_matrix(portfolios=portfolios, regimes=regimes)
    _write_snapshot(out_dir, snapshot)
    print(
        f"[capture] {sum(len(v) for v in snapshot.grains.values())} coordinates "
        f"({len(snapshot.grains[GRAIN_CELL])} cells) -> {out_dir} "
        f"in {snapshot.meta['wall_seconds']}s"
    )
    return snapshot


def run_matrix(*, portfolios: set[str] | None, regimes: set[str] | None) -> Snapshot:
    """Run every selected portfolio/regime and build the four-grain snapshot.

    The SINGLE production path for a snapshot. ``capture`` writes what this
    returns and ``compare`` calls it directly when no ``--current`` snapshot was
    supplied — a second, parallel extraction path could drift and make a
    snapshot-vs-snapshot comparison disagree with a snapshot-vs-live one.
    """
    started = time.perf_counter()
    grains: dict[str, dict[str, Value]] = {grain: {} for grain in GRAINS}
    runs: list[dict[str, Any]] = []

    for spec in _selected_runs(portfolios, regimes):
        regime, framework, portfolio, build_bundle, build_config, build_prior = spec
        run_started = time.perf_counter()
        result = PipelineOrchestrator().run_with_data(build_bundle(), build_config())
        prior = (
            PipelineOrchestrator().run_with_data(build_bundle(), build_prior())
            if build_prior is not None
            else None
        )
        prior_results = None if prior is None else prior.results

        corep = COREPGenerator().generate_from_lazyframe(
            result.results, framework=framework, previous_period_results=prior_results
        )
        pillar3 = Pillar3Generator().generate_from_lazyframe(
            result.results, framework=framework, previous_period_results=prior_results
        )

        totals, class_rwa, nonfinite_legs = _pipeline_grains(regime, portfolio, result)
        grains[GRAIN_TOTAL].update(totals)
        grains[GRAIN_CLASS].update(class_rwa)
        grains[GRAIN_ERROR].update(_error_grain(regime, portfolio, result))

        cells = _bundle_cells(regime, portfolio, corep) | _bundle_cells(regime, portfolio, pillar3)
        grains[GRAIN_CELL].update(cells)

        elapsed = time.perf_counter() - run_started
        nonfinite_cells = sum(
            1 for value in cells.values() if value.num is not None and not math.isfinite(value.num)
        )
        runs.append(
            {
                "regime": regime,
                "portfolio": portfolio,
                "framework": framework,
                "prior_period": build_prior is not None,
                "cells": len(cells),
                "nonfinite_cells": nonfinite_cells,
                "nonfinite_legs": nonfinite_legs,
                "errors": sum(
                    int(value.num or 0)
                    for key, value in grains[GRAIN_ERROR].items()
                    if key.startswith(f"{regime}|{portfolio}|")
                ),
                "seconds": round(elapsed, 2),
            }
        )
        print(
            f"[capture] {regime}/{portfolio}: {len(cells)} cells, "
            f"{nonfinite_cells} non-finite, {elapsed:.1f}s"
        )

    grains[GRAIN_TOTAL].update(_regime_rollup(grains[GRAIN_TOTAL]))

    meta: dict[str, Any] = {
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": _git_state(),
        "polars": pl.__version__,
        "python": sys.version.split()[0],
        "rtol": RTOL,
        "atol": ATOL,
        "runs": runs,
        "grain_sizes": {grain: len(values) for grain, values in grains.items()},
        "cells_per_regime": _cells_per_regime(grains[GRAIN_CELL]),
        "wall_seconds": round(time.perf_counter() - started, 2),
        "peak_rss_mb": _peak_rss_mb(),
    }
    return Snapshot(meta=meta, grains=grains)


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------


def compare(
    baseline_dir: Path,
    *,
    current_dir: Path | None,
    portfolios: set[str] | None,
    regimes: set[str] | None,
) -> Comparison:
    """Diff a baseline snapshot against the current tree (or a second snapshot)."""
    baseline = _read_snapshot(baseline_dir)
    current = (
        _read_snapshot(current_dir)
        if current_dir is not None
        else run_matrix(portfolios=portfolios, regimes=regimes)
    )
    entries = _read_allowlist()

    movements: list[Movement] = []
    for grain in GRAINS:
        movements.extend(_diff_grain(grain, baseline.grains[grain], current.grains[grain]))
    movements.sort(key=lambda m: (-m.magnitude, m.grain, m.key))

    allowed: dict[int, list[Movement]] = {index: [] for index in range(len(entries))}
    unexplained: list[Movement] = []
    for movement in movements:
        index = next(
            (i for i, entry in enumerate(entries) if entry.matches(movement.grain, movement.key)),
            None,
        )
        if index is None:
            unexplained.append(movement)
        else:
            allowed[index].append(movement)

    stale = [entry for index, entry in enumerate(entries) if not allowed[index]]
    return Comparison(
        movements=movements,
        allowed=allowed,
        unexplained=unexplained,
        stale=stale,
        entries=entries,
        baseline_meta=baseline.meta,
        current_meta=current.meta,
        matrix_warning=_matrix_warning(baseline.meta, current.meta),
    )


def render_json(comparison: Comparison, *, max_detail: int) -> dict[str, Any]:
    """Machine-readable form of the comparison."""
    by_grain: dict[str, Any] = {}
    for grain in GRAINS:
        grain_moves = [m for m in comparison.movements if m.grain == grain]
        grain_unexplained = [m for m in comparison.unexplained if m.grain == grain]
        detail = grain_unexplained[:max_detail]
        by_grain[grain] = {
            "key_fields": list(GRAIN_KEY_FIELDS[grain]),
            "counts": {
                status: sum(1 for m in grain_moves if m.status == status) for status in ALL_STATUSES
            },
            "moved": len(grain_moves),
            "unexplained": len(grain_unexplained),
            "unexplained_detail": [_movement_json(m) for m in detail],
            "unexplained_detail_truncated": len(grain_unexplained) - len(detail),
        }
    return {
        "verdict": "PASS" if not comparison.unexplained else "UNEXPLAINED_MOVEMENT",
        "matrix_warning": comparison.matrix_warning,
        "moved": len(comparison.movements),
        "unexplained": len(comparison.unexplained),
        "allowlisted": len(comparison.movements) - len(comparison.unexplained),
        "stale_allowlist_entries": [
            {"grain": e.grain, "key": e.key, "accepted_under": e.accepted_under}
            for e in comparison.stale
        ],
        "allowlist_coverage": [
            {
                "grain": entry.grain,
                "key": entry.key,
                "accepted_under": entry.accepted_under,
                "matched": len(comparison.allowed[index]),
            }
            for index, entry in enumerate(comparison.entries)
        ],
        "headline": [_movement_json(m) for m in _headline_movements(comparison)],
        "by_grain": by_grain,
        "baseline_meta": comparison.baseline_meta,
        "current_meta": comparison.current_meta,
    }


def render_markdown(comparison: Comparison, *, top: int) -> str:
    """PR-pasteable report: verdict, headline, absence first, then the movers."""
    lines: list[str] = ["# RWA change-impact report", ""]
    lines += _markdown_verdict(comparison)
    lines += _markdown_headline(comparison, top=top)
    lines += _markdown_absence(comparison, top=top)
    lines += _markdown_presence(comparison, top=top)
    lines += _markdown_changed(comparison, top=top)
    lines += _markdown_allowlist(comparison)
    lines += _markdown_reach(comparison)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point. See the module docstring for the exit-code contract."""
    parser = argparse.ArgumentParser(
        description="Numeric change-impact report over the reporting fixture portfolios."
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    cap = sub.add_parser("capture", help="snapshot the current outputs")
    cap.add_argument("--out", type=Path, required=True)
    _add_matrix_flags(cap)

    cmp_ = sub.add_parser("compare", help="diff a baseline against the current tree")
    cmp_.add_argument("--baseline", type=Path, required=True)
    cmp_.add_argument(
        "--current",
        type=Path,
        default=None,
        help="compare against an already-captured snapshot instead of re-running",
    )
    cmp_.add_argument("--json", type=Path, default=None, help="write the machine-readable report")
    cmp_.add_argument("--markdown", type=Path, default=None, help="write the PR-pasteable report")
    cmp_.add_argument("--top", type=int, default=_DEFAULT_TOP, help="movers listed per section")
    cmp_.add_argument(
        "--max-detail", type=int, default=2000, help="unexplained movements detailed per grain"
    )
    cmp_.add_argument(
        "--stale-check",
        action="store_true",
        help="fail (exit 3) when an allowlist entry matches no movement",
    )
    _add_matrix_flags(cmp_)

    args = parser.parse_args(argv)
    portfolios = _split_csv(args.portfolios)
    regimes = _split_csv(args.regimes)

    # Every operator-supplied path is resolved BEFORE any work, so a path
    # mistake fails fast as a usage error and can never be mistaken for the
    # unexplained-movement verdict.
    try:
        paths = {
            name: None if getattr(args, name, None) is None else _confine_path(getattr(args, name))
            for name in ("out", "baseline", "current", "json", "markdown")
        }
    except SystemExit as exc:
        print(exc)
        return _EXIT_USAGE

    if args.mode == "capture":
        capture(_as_path(paths["out"]), portfolios=portfolios, regimes=regimes)
        return _EXIT_OK

    baseline_dir = _as_path(paths["baseline"])
    if not baseline_dir.exists():
        print(f"No baseline snapshot at {baseline_dir}. Capture one first.")
        return _EXIT_USAGE

    try:
        comparison = compare(
            baseline_dir,
            current_dir=paths["current"],
            portfolios=portfolios,
            regimes=regimes,
        )
    except AllowlistError as exc:
        print(f"Malformed allowlist ({ALLOWLIST_PATH.name}): {exc}")
        return _EXIT_USAGE

    report = render_markdown(comparison, top=args.top)
    print(report)
    if paths["markdown"] is not None:
        paths["markdown"].write_text(report, encoding="utf-8")
    if paths["json"] is not None:
        paths["json"].write_text(
            json.dumps(render_json(comparison, max_detail=args.max_detail), indent=2) + "\n",
            encoding="utf-8",
        )

    if comparison.unexplained:
        return _EXIT_UNEXPLAINED
    if args.stale_check and comparison.stale:
        return _EXIT_STALE
    return _EXIT_OK


class AllowlistError(RuntimeError):
    """A recorded decision that is not usable as one."""


# ---------------------------------------------------------------------------
# Private helpers — matrix selection
# ---------------------------------------------------------------------------


def _add_matrix_flags(parser: argparse.ArgumentParser) -> None:
    """Portfolio / regime filters, identical on both subcommands."""
    parser.add_argument(
        "--portfolios",
        default=None,
        help="comma-separated portfolio subset (default: every portfolio in RUNS)",
    )
    parser.add_argument(
        "--regimes", default=None, help="comma-separated regime subset: crr, b31 (default: both)"
    )


def _split_csv(raw: str | None) -> set[str] | None:
    return None if raw is None else {part.strip() for part in raw.split(",") if part.strip()}


def _selected_runs(portfolios: set[str] | None, regimes: set[str] | None) -> list[Any]:
    """The run matrix, filtered. An unknown name is a usage error, not a silent no-op."""
    known_portfolios = {spec.portfolio for spec in RUNS}
    known_regimes = {spec.regime for spec in RUNS}
    if portfolios is not None and not portfolios <= known_portfolios:
        raise SystemExit(f"unknown portfolio(s): {sorted(portfolios - known_portfolios)}")
    if regimes is not None and not regimes <= known_regimes:
        raise SystemExit(f"unknown regime(s): {sorted(regimes - known_regimes)}")
    selected = [
        spec
        for spec in RUNS
        if (portfolios is None or spec.portfolio in portfolios)
        and (regimes is None or spec.regime in regimes)
    ]
    if not selected:
        raise SystemExit("the portfolio/regime filters select no runs")
    return selected


# ---------------------------------------------------------------------------
# Private helpers — grain extraction
# ---------------------------------------------------------------------------


def _pipeline_grains(
    regime: str, portfolio: str, result: AggregatedResultBundle
) -> tuple[dict[str, Value], dict[str, Value], int]:
    """Grains 1 and 2 from one pipeline result, plus the non-finite leg count.

    Reads the SEALED ``reporting_approach`` / ``reporting_class`` projection —
    the same post-substitution basis the templates key on — so a movement here
    and a movement at cell grain describe the same event.
    """
    df = result.results.collect()
    _require_columns(df, ("rwa_final", "ead_final", "reporting_approach", "reporting_class"))

    rwa = df["rwa_final"]
    nonfinite = int(rwa.is_finite().not_().fill_null(True).sum())
    totals = {
        _key(regime, portfolio, "total_rwa"): _num(rwa.sum()),
        _key(regime, portfolio, "total_ead"): _num(df["ead_final"].sum()),
        _key(regime, portfolio, "legs"): _num(float(df.height)),
        _key(regime, portfolio, "nonfinite_rwa_legs"): _num(float(nonfinite)),
    }

    grouped = (
        df.group_by(["reporting_approach", "reporting_class"])
        .agg(pl.col("rwa_final").sum().alias("rwa"))
        .sort(["reporting_approach", "reporting_class"])
    )
    class_rwa = {
        _key(regime, portfolio, _text(row[0]), _text(row[1])): _num(row[2])
        for row in grouped.iter_rows()
    }
    return totals, class_rwa, nonfinite


def _error_grain(regime: str, portfolio: str, result: AggregatedResultBundle) -> dict[str, Value]:
    """Grain 4: ``(category, severity, code) -> count``."""
    counts: dict[str, int] = {}
    for error in result.errors:
        key = _key(regime, portfolio, error.category.value, error.severity.value, error.code)
        counts[key] = counts.get(key, 0) + 1
    return {key: _num(float(count)) for key, count in sorted(counts.items())}


def _bundle_cells(regime: str, portfolio: str, bundle: Any) -> dict[str, Value]:
    """Grain 3: every cell of every frame on a generated template bundle.

    Single-frame fields get the ``-`` sheet label; per-class / per-country /
    per-netting-set dict fields get one sheet per key. ``row_name`` is captured
    as a cell in its own right so a row RE-LABEL is a reported movement rather
    than an invisible one.
    """
    cells: dict[str, Value] = {}
    for field in dataclasses.fields(bundle):
        value = getattr(bundle, field.name)
        if isinstance(value, pl.DataFrame):
            cells |= _frame_cells(regime, portfolio, field.name, SINGLE_SHEET, value)
        elif isinstance(value, dict):
            for sheet, frame in value.items():
                if isinstance(frame, pl.DataFrame):
                    cells |= _frame_cells(regime, portfolio, field.name, str(sheet), frame)
    return cells


def _frame_cells(
    regime: str, portfolio: str, template: str, sheet: str, frame: pl.DataFrame
) -> dict[str, Value]:
    """Flatten one template frame into ``coordinate -> Value``."""
    if frame.height == 0:
        return {}
    row_labels = _row_labels(frame)
    value_cols = [name for name in frame.columns if name != ROW_REF_COL]
    cells: dict[str, Value] = {}
    for column in value_cols:
        series = frame[column]
        is_text = series.dtype == pl.String
        for row_label, raw in zip(row_labels, series.to_list(), strict=True):
            key = _key(regime, portfolio, template, sheet, row_label, column)
            cells[key] = Value("str", None, raw) if is_text else _num(raw)
    return cells


def _row_labels(frame: pl.DataFrame) -> list[str]:
    """Stable per-row labels, de-duplicated when a ``row_ref`` repeats in a frame."""
    if ROW_REF_COL not in frame.columns:
        return [str(index) for index in range(frame.height)]
    seen: dict[str, int] = {}
    labels: list[str] = []
    for raw in frame[ROW_REF_COL].to_list():
        base = "<null>" if raw is None else str(raw)
        seen[base] = seen.get(base, 0) + 1
        labels.append(base if seen[base] == 1 else f"{base}#{seen[base]}")
    return labels


def _regime_rollup(totals: dict[str, Value]) -> dict[str, Value]:
    """Per-regime headline rows: the same metrics summed over every portfolio."""
    rolled: dict[str, float] = {}
    for key, value in totals.items():
        regime, portfolio, metric = key.split("|")
        if portfolio == ALL_PORTFOLIOS or value.num is None:
            continue
        rolled_key = _key(regime, ALL_PORTFOLIOS, metric)
        rolled[rolled_key] = rolled.get(rolled_key, 0.0) + value.num
    return {key: _num(total) for key, total in sorted(rolled.items())}


def _cells_per_regime(cells: dict[str, Value]) -> dict[str, int]:
    """How many template cells the report actually reaches, per regime."""
    counts: dict[str, int] = {}
    for key in cells:
        regime = key.split("|", 1)[0]
        counts[regime] = counts.get(regime, 0) + 1
    return dict(sorted(counts.items()))


def _require_columns(df: pl.DataFrame, needed: tuple[str, ...]) -> None:
    """Fail LOUDLY on a renamed carrier.

    A presence guard that silently skips a missing column is how a whole grain
    stops being captured without anyone noticing (.claude/LESSONS.md B1).
    """
    missing = [name for name in needed if name not in df.columns]
    if missing:
        raise SystemExit(
            f"impact_report: results frame is missing {missing}. The carrier was renamed; "
            "update scripts/impact_report.py rather than letting the grain go dark."
        )


# ---------------------------------------------------------------------------
# Private helpers — diffing
# ---------------------------------------------------------------------------


def _diff_grain(grain: str, before: dict[str, Value], after: dict[str, Value]) -> list[Movement]:
    """Every coordinate that differs, including the ones present on only one side."""
    movements: list[Movement] = []
    for key in sorted(set(before) - set(after)):
        movements.append(Movement(grain, key, STATUS_DISAPPEARED, before[key], None, None, None))
    for key in sorted(set(after) - set(before)):
        movements.append(Movement(grain, key, STATUS_APPEARED, None, after[key], None, None))
    for key in sorted(set(before) & set(after)):
        movement = _diff_value(grain, key, before[key], after[key])
        if movement is not None:
            movements.append(movement)
    return movements


def _diff_value(grain: str, key: str, before: Value, after: Value) -> Movement | None:
    """Compare one coordinate. Null transitions are their own statuses."""
    if before.is_null() and after.is_null():
        return None
    if not before.is_null() and after.is_null():
        return Movement(grain, key, STATUS_NULLED, before, after, None, None)
    if before.is_null() and not after.is_null():
        return Movement(grain, key, STATUS_POPULATED, before, after, None, None)
    if before.dtype != after.dtype or before.text is not None or after.text is not None:
        if before.text == after.text and before.dtype == after.dtype:
            return None
        return Movement(grain, key, STATUS_CHANGED, before, after, None, None)

    # Both sides are non-null numerics by the guards above.
    left = before.num if before.num is not None else 0.0
    right = after.num if after.num is not None else 0.0
    if _close(left, right):
        return None
    delta = right - left
    relative = delta / abs(left) if left != 0.0 and math.isfinite(left) else None
    return Movement(grain, key, STATUS_CHANGED, before, after, delta, relative)


def _close(left: float, right: float) -> bool:
    """Float-reassociation tolerance, with NaN treated as equal to NaN.

    Two NaNs are not a *movement* — but a NaN in the output is a defect in its
    own right, so the capture counts non-finite cells and the report surfaces
    them regardless of whether they moved.
    """
    if math.isnan(left) and math.isnan(right):
        return True
    if math.isnan(left) or math.isnan(right):
        return False
    if math.isinf(left) or math.isinf(right):
        return left == right
    return abs(right - left) <= ATOL + RTOL * abs(left)


def _matrix_warning(baseline_meta: dict[str, Any], current_meta: dict[str, Any]) -> str | None:
    """Flag a comparison whose two sides did not run the same matrix.

    ``--portfolios`` / ``--regimes`` filter the CURRENT run only, so comparing a
    narrowed run against a full baseline reports every coordinate of the dropped
    runs as "disappeared". That is literally true and deliberately loud, but the
    cause is the filter, so say so rather than letting a reader chase it.
    """
    before = _run_set(baseline_meta)
    after = _run_set(current_meta)
    if before == after:
        return None
    dropped = sorted(f"{regime}/{portfolio}" for regime, portfolio in before - after)
    added = sorted(f"{regime}/{portfolio}" for regime, portfolio in after - before)
    parts = []
    if dropped:
        parts.append(f"absent from the current run: {', '.join(dropped)}")
    if added:
        parts.append(f"absent from the baseline: {', '.join(added)}")
    return (
        "The two sides did not run the same matrix (" + "; ".join(parts) + "). "
        "Coordinates from a run present on only one side are reported as "
        "disappeared/appeared - that is the filter, not the change under test."
    )


def _run_set(meta: dict[str, Any]) -> set[tuple[str, str]]:
    return {(run.get("regime", "?"), run.get("portfolio", "?")) for run in meta.get("runs", [])}


def _headline_movements(comparison: Comparison) -> list[Movement]:
    """The per-regime roll-up rows — the first thing a reader should see."""
    return [
        movement
        for movement in comparison.movements
        if movement.grain == GRAIN_TOTAL and f"|{ALL_PORTFOLIOS}|" in movement.key
    ]


def _movement_json(movement: Movement) -> dict[str, Any]:
    fields = GRAIN_KEY_FIELDS[movement.grain]
    parts = movement.key.split("|")
    return {
        "grain": movement.grain,
        "key": movement.key,
        "coordinate": dict(zip(fields, parts, strict=False)),
        "status": movement.status,
        "before": None if movement.before is None else _value_json(movement.before),
        "after": None if movement.after is None else _value_json(movement.after),
        "delta": movement.delta,
        "relative": movement.relative,
        "magnitude": movement.magnitude,
    }


def _value_json(value: Value) -> Any:
    return value.text if value.text is not None else value.num


# ---------------------------------------------------------------------------
# Private helpers — allowlist
# ---------------------------------------------------------------------------


def _read_allowlist() -> list[AllowEntry]:
    """Load the recorded-decision register, rejecting any entry with no reason."""
    if not ALLOWLIST_PATH.exists():
        return []
    payload = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    raw_entries = payload.get("entries", [])
    if not isinstance(raw_entries, list):
        raise AllowlistError("'entries' must be a list")
    entries: list[AllowEntry] = []
    for index, raw in enumerate(raw_entries):
        entries.append(_parse_entry(index, raw))
    return entries


def _parse_entry(index: int, raw: Any) -> AllowEntry:
    """One register line, validated. A placeholder reason is not a reason."""
    where = f"entries[{index}]"
    if not isinstance(raw, dict):
        raise AllowlistError(f"{where} is not an object")
    grain = str(raw.get("grain", ""))
    key = str(raw.get("key", ""))
    reason = str(raw.get("reason", "")).strip()
    accepted_under = str(raw.get("accepted_under", "")).strip()
    if grain not in GRAINS:
        raise AllowlistError(f"{where}: grain {grain!r} not one of {list(GRAINS)}")
    if not key:
        raise AllowlistError(f"{where}: empty key")
    if reason.lower() in PLACEHOLDER_REASONS:
        raise AllowlistError(f"{where} ({key}): reason {reason!r} is a placeholder, not a reason")
    if len(reason) < MIN_REASON_CHARS or len(reason.split()) < MIN_REASON_WORDS:
        raise AllowlistError(
            f"{where} ({key}): reason must be at least {MIN_REASON_CHARS} characters and "
            f"{MIN_REASON_WORDS} words - say what moved and why it is correct"
        )
    if len(accepted_under) < 3:
        raise AllowlistError(f"{where} ({key}): 'accepted_under' must name a commit or PR")
    return AllowEntry(grain=grain, key=key, reason=reason, accepted_under=accepted_under)


# ---------------------------------------------------------------------------
# Private helpers — markdown sections
# ---------------------------------------------------------------------------


def _markdown_verdict(comparison: Comparison) -> list[str]:
    moved = len(comparison.movements)
    unexplained = len(comparison.unexplained)
    verdict = (
        "**PASS** - nothing moved."
        if moved == 0
        else (
            f"**PASS** - {moved} movement(s), all accounted for in `{ALLOWLIST_PATH.name}`."
            if unexplained == 0
            else f"**BLOCKED** - {unexplained} of {moved} movement(s) are UNEXPLAINED."
        )
    )
    baseline_git = comparison.baseline_meta.get("git", {})
    current_git = comparison.current_meta.get("git", {})
    warning = (
        [] if comparison.matrix_warning is None else [f"> **{comparison.matrix_warning}**", ""]
    )
    return [
        verdict,
        "",
        *warning,
        f"- baseline: `{baseline_git.get('sha', '?')}` "
        f"({comparison.baseline_meta.get('captured_at', '?')})",
        f"- current:  `{current_git.get('sha', '?')}` "
        f"({comparison.current_meta.get('captured_at', '?')})",
        f"- tolerance: rtol={RTOL:g}, atol={ATOL:g}",
        "",
    ]


def _markdown_headline(comparison: Comparison, *, top: int) -> list[str]:
    lines = ["## Headline - total RWA per regime", ""]
    headline = _headline_movements(comparison)
    if not headline:
        lines += ["No movement in any per-regime roll-up.", ""]
        return lines
    lines += [
        "| coordinate | before | after | delta | relative |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for movement in headline[:top]:
        before = "-" if movement.before is None else movement.before.render()
        after = "-" if movement.after is None else movement.after.render()
        delta = "-" if movement.delta is None else f"{movement.delta:+,.2f}"
        relative = "-" if movement.relative is None else f"{movement.relative:+.4%}"
        lines.append(f"| `{movement.key}` | {before} | {after} | {delta} | {relative} |")
    lines.append("")
    return lines


def _markdown_absence(comparison: Comparison, *, top: int) -> list[str]:
    """Absence first and loud — the escape class this project keeps paying for."""
    absent = [m for m in comparison.movements if m.status in ABSENCE_STATUSES]
    lines = ["## Absence - disappeared and nulled coordinates", ""]
    if not absent:
        lines += ["None. No coordinate vanished and no cell stopped carrying a figure.", ""]
        return lines
    lines += [
        f"**{len(absent)} coordinate(s) went missing.** A coordinate the current run does not "
        "produce is invisible to any check that only compares what both sides have.",
        "",
    ]
    lines += _movement_table(absent, top=top)
    return lines


def _markdown_presence(comparison: Comparison, *, top: int) -> list[str]:
    appeared = [m for m in comparison.movements if m.status in PRESENCE_STATUSES]
    lines = ["## Appearance - new and newly-populated coordinates", ""]
    if not appeared:
        lines += ["None.", ""]
        return lines
    lines += [f"{len(appeared)} coordinate(s) appeared or became non-null.", ""]
    lines += _movement_table(appeared, top=top)
    return lines


def _markdown_changed(comparison: Comparison, *, top: int) -> list[str]:
    lines: list[str] = []
    for grain in GRAINS:
        changed = [
            m for m in comparison.movements if m.grain == grain and m.status == STATUS_CHANGED
        ]
        lines += [f"## Changed - {GRAIN_TITLES[grain]}", ""]
        if not changed:
            lines += ["None.", ""]
            continue
        lines += [f"{len(changed)} changed, biggest absolute movement first.", ""]
        lines += _movement_table(changed, top=top)
    return lines


def _movement_table(movements: list[Movement], *, top: int) -> list[str]:
    lines = [
        "| status | grain | coordinate | before | after | delta | relative |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for movement in movements[:top]:
        before = "-" if movement.before is None else movement.before.render()
        after = "-" if movement.after is None else movement.after.render()
        delta = "-" if movement.delta is None else f"{movement.delta:+,.4f}"
        relative = "-" if movement.relative is None else f"{movement.relative:+.4%}"
        lines.append(
            f"| {movement.status} | {movement.grain} | `{movement.key}` | "
            f"{before} | {after} | {delta} | {relative} |"
        )
    if len(movements) > top:
        lines.append(f"| ... | | _{len(movements) - top} more_ | | | | |")
    lines.append("")
    return lines


def _markdown_allowlist(comparison: Comparison) -> list[str]:
    lines = ["## Verdict - unexplained movement", ""]
    if not comparison.unexplained:
        lines += ["Every movement above is recorded in `scripts/impact_allowlist.json`.", ""]
    else:
        lines += [
            f"**{len(comparison.unexplained)} movement(s) have no recorded decision.** "
            "Fix the defect, or add an entry with a written reason to "
            "`scripts/impact_allowlist.json`:",
            "",
            "```json",
            json.dumps(
                [
                    {
                        "grain": movement.grain,
                        "key": movement.key,
                        "reason": "WHY this movement is correct - what changed and why the new figure is right",
                        "accepted_under": "<commit sha or PR number>",
                    }
                    for movement in comparison.unexplained[:10]
                ],
                indent=2,
            ),
            "```",
            "",
        ]
    if comparison.stale:
        lines += [
            f"### Stale allowlist entries ({len(comparison.stale)})",
            "",
            "These recorded decisions match no movement in this comparison. A register that is "
            "never pruned silently widens over time - remove them or re-derive them.",
            "",
        ]
        lines += [
            f"- `{entry.grain}` / `{entry.key}` (accepted under {entry.accepted_under})"
            for entry in comparison.stale
        ]
        lines.append("")
    return lines


def _markdown_reach(comparison: Comparison) -> list[str]:
    """How much estate the report actually covers — the number that bounds it."""
    current = comparison.current_meta
    baseline = comparison.baseline_meta
    lines = ["## Reach", "", "| grain | baseline | current |", "| --- | ---: | ---: |"]
    for grain in GRAINS:
        before = baseline.get("grain_sizes", {}).get(grain, "?")
        after = current.get("grain_sizes", {}).get(grain, "?")
        lines.append(f"| {GRAIN_TITLES[grain]} | {before} | {after} |")
    lines.append("")
    per_regime = current.get("cells_per_regime", {})
    if per_regime:
        lines += [
            "Template cells per regime: "
            + ", ".join(f"{k} = {v:,}" for k, v in per_regime.items()),
            "",
        ]
    nonfinite = sum(run.get("nonfinite_cells", 0) for run in current.get("runs", []))
    if nonfinite:
        lines += [
            f"**{nonfinite} non-finite template cell(s) in the current run.** A NaN/Inf figure is "
            "a defect whether or not it moved.",
            "",
        ]
    return lines


# ---------------------------------------------------------------------------
# Private helpers — persistence and environment
# ---------------------------------------------------------------------------


def _write_snapshot(out_dir: Path, snapshot: Snapshot) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for grain, values in snapshot.grains.items():
        keys = sorted(values)
        pl.DataFrame(
            {
                "key": keys,
                "dtype": [values[key].dtype for key in keys],
                "num": [values[key].num for key in keys],
                "text": [values[key].text for key in keys],
            },
            schema={"key": pl.String, "dtype": pl.String, "num": pl.Float64, "text": pl.String},
        ).write_parquet(out_dir / f"{grain}.parquet")
    (out_dir / "meta.json").write_text(json.dumps(snapshot.meta, indent=2) + "\n", encoding="utf-8")


def _read_snapshot(snapshot_dir: Path) -> Snapshot:
    meta_path = snapshot_dir / "meta.json"
    if not meta_path.exists():
        raise SystemExit(f"{snapshot_dir} is not an impact snapshot (no meta.json)")
    grains: dict[str, dict[str, Value]] = {}
    for grain in GRAINS:
        path = snapshot_dir / f"{grain}.parquet"
        if not path.exists():
            raise SystemExit(f"{snapshot_dir}: snapshot is missing the '{grain}' grain")
        df = pl.read_parquet(path)
        grains[grain] = {row[0]: Value(row[1], row[2], row[3]) for row in df.iter_rows()}
    return Snapshot(meta=json.loads(meta_path.read_text(encoding="utf-8")), grains=grains)


def _git_state() -> dict[str, Any]:
    """Commit and dirtiness of the tree the snapshot describes."""

    def _run(*args: str) -> str:
        try:
            return subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return ""

    return {
        "sha": _run("rev-parse", "--short", "HEAD"),
        "dirty": bool(_run("status", "--porcelain")),
    }


def _peak_rss_mb() -> float | None:
    """Peak resident set size, when psutil is available; ``None`` otherwise."""
    try:
        import psutil
    except ImportError:
        return None
    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None) or info.rss
    return round(peak / 1e6, 1)


def _confine_path(raw: Path) -> Path:
    """Resolve a CLI path and reject anything outside ``_ALLOWED_ROOT``.

    Same guard as ``scripts/parity_gate.py``: the capture/compare directories are
    operator-supplied, and resolving first collapses ``..`` segments so the
    containment check cannot be bypassed.
    """
    resolved = raw.expanduser().resolve()
    if not resolved.is_relative_to(_ALLOWED_ROOT):
        raise SystemExit(f"path escapes {_ALLOWED_ROOT}: {raw}")
    return resolved


def _as_path(raw: Path | None) -> Path:
    """Narrow an argparse-required path that the type checker still sees as optional."""
    if raw is None:
        raise SystemExit("required path argument missing")
    return raw


def _key(*parts: str) -> str:
    return "|".join(parts)


def _num(raw: Any) -> Value:
    return Value("num", None if raw is None else float(raw), None)


def _text(raw: Any) -> str:
    return "<null>" if raw is None else str(raw)


if __name__ == "__main__":
    raise SystemExit(main())
