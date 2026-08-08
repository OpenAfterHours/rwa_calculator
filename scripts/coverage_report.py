"""
Estate-wide reporting coverage metrics (independent validation plan, C5).

The supervisory register **fails open**. A rule it cannot reach is
``NOT_EVALUATED``, which on the error channel is indistinguishable from a clean
estate, and the per-run summary in
``tests/expected_outputs/reporting/validation_known_breaks.json`` cannot show
the estate-wide picture: it says how each portfolio did, never how much of the
published rulebook binds anywhere at all.

This script answers that. It runs the same portfolio x regime matrix the gate
runs -- imported from ``RUNS``, never re-declared, so it cannot silently shrink
-- and measures four things:

``union_binding_rules_crr`` / ``union_binding_rules_b31``
    Distinct rules reaching PASS or FAIL in at least one run. VACUOUS is
    excluded: a rule whose every operand was null or zero asserted nothing.
    This is the honest headline the per-run summary cannot produce.
``template_cell_liveness``
    Fraction of declared template cells carrying a value in at least one run.
``dead_cells``
    Cells never non-null in any run. Either the portfolio matrix is deficient
    or the cell is broken; both are work items, so both are listed.
``never_evaluated_rules``
    Rules NOT_EVALUATED on every run, with the reason. Ranked by severity --
    an ERROR-severity rule that never runs anywhere is the worst case in the
    estate and heads the report.

It also runs two ``LESSONS.md`` graduations, because both bear directly on
whether the numbers above mean anything:

- every reporting fixture portfolio that builds a bundle is referenced in
  ``RUNS`` (B5 -- an unregistered portfolio makes every rule over its columns
  NOT_EVALUATED, which reads exactly like a clean estate); and
- every fixture builder that writes a parquet is registered in
  ``tests/fixtures/generate_all.py`` (an unregistered builder works locally and
  fails on a fresh checkout).

Run:
    uv run python scripts/coverage_report.py

Output:
    scripts/coverage_metrics.json (override with --out), plus a human summary.

This script computes and prints. It does not gate: wiring the ratchets into
``arch_metrics.json`` is deliberately somebody else's commit.
"""

from __future__ import annotations

import argparse
import ast
import gc
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import polars as pl  # noqa: E402
from tests.acceptance.reporting.test_supervisory_validations import RUNS  # noqa: E402

from rwa_calc.engine.pipeline import PipelineOrchestrator  # noqa: E402
from rwa_calc.reporting.corep.generator import COREPGenerator  # noqa: E402
from rwa_calc.reporting.pillar3.generator import Pillar3Generator  # noqa: E402
from rwa_calc.reporting.validations import (  # noqa: E402
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    evaluate_all,
)
from rwa_calc.reporting.validations.scope import SINGLE_SHEET, build_template_index  # noqa: E402

if TYPE_CHECKING:
    from rwa_calc.reporting.validations.checker import ValidationReport

DEFAULT_OUT = _REPO_ROOT / "scripts" / "coverage_metrics.json"
FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures"
GENERATE_ALL = FIXTURES_DIR / "generate_all.py"

# Parquet-writing fixture modules deliberately NOT registered in generate_all.py.
# An entry needs a written reason; an entry with no reason is not an entry. Verified
# 2026-08-08: both write parquet only inside save_*_fixtures() called from main()
# behind a __main__ guard, neither has any parquet on disk under tests/fixtures/ccr/
# (a10 and a13 do), and the acceptance tests import build_ccr_a{4,6}_bundle directly
# and build in memory. So nothing reads a parquet these would fail to produce, and
# registering them would generate files the suite does not consume.
_REGISTRATION_ALLOWLIST: dict[str, str] = {
    "tests/fixtures/ccr/golden_ccr_a4.py": (
        "standalone dump behind a __main__ guard; no a4 parquet exists and "
        "tests/acceptance/ccr/test_ccr_a4_credit_index_cds.py builds in memory "
        "via build_ccr_a4_bundle"
    ),
    "tests/fixtures/ccr/golden_ccr_a6.py": (
        "standalone dump behind a __main__ guard; no a6 parquet exists and "
        "tests/acceptance/ccr/test_ccr_a6_equity_index_option.py builds in memory "
        "via build_ccr_a6_bundle"
    ),
}

#: How many dead cells and never-evaluated rules to print. The full lists always
#: go to the JSON -- truncation is a courtesy to the terminal, never to the
#: record.
PRINTED_ROWS = 20

#: Severity ordering for the never-evaluated report. An ERROR-severity rule that
#: never runs anywhere is the worst case: the estate is unchecked exactly where
#: the publisher said a break is fatal.
SEVERITY_RANK = {"ERROR": 0, "WARNING": 1, "INFO": 2}


class CellAddress(NamedTuple):
    """One template cell, regime-qualified. The unit of the liveness metric."""

    regime: str
    template: str
    sheet: str
    row: str
    column: str

    def describe(self) -> str:
        sheet = "" if self.sheet == SINGLE_SHEET else f"[{self.sheet}]"
        return f"{self.regime}/{self.template}{sheet}[r{self.row}][c{self.column}]"


class Observation:
    """Everything the matrix produced, accumulated across runs.

    Accumulating sets rather than keeping the frames is what makes this fit in
    memory: eighteen pipeline runs (twelve, plus a prior-period run for each of
    the six IRB-permission ones) never coexist.
    """

    def __init__(self) -> None:
        # (regime, rule_id) -> statuses seen across runs
        self.rule_statuses: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.rule_severity: dict[tuple[str, str], str] = {}
        self.rule_label: dict[tuple[str, str], str] = {}
        self.rule_tables: dict[tuple[str, str], tuple[str, ...]] = {}
        self.rule_reasons: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        self.rules_enforced: dict[str, int] = {}
        self.cells_declared: set[CellAddress] = set()
        self.cells_live: set[CellAddress] = set()
        self.cells_nonzero: set[CellAddress] = set()
        self.run_summaries: list[dict[str, Any]] = []


# =============================================================================
# Running the matrix
# =============================================================================


def observe_runs(limit: int | None = None) -> Observation:
    """Run every (portfolio, regime) in ``RUNS`` and accumulate the coverage facts."""
    observation = Observation()
    runs = RUNS[:limit] if limit else RUNS

    for index, run in enumerate(runs, start=1):
        regime, framework, portfolio = run.regime, run.framework, run.portfolio
        started = time.perf_counter()
        print(f"  [{index}/{len(runs)}] {regime}/{portfolio} ...", flush=True)

        result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
        prior = (
            PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_prior_config())
            if run.build_prior_config is not None
            else None
        )
        corep = COREPGenerator().generate_from_lazyframe(
            result.results,
            framework=framework,
            previous_period_results=None if prior is None else prior.results,
        )
        pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)

        report = evaluate_all(corep, pillar3, framework)
        _absorb_rules(observation, regime, report)
        _absorb_cells(observation, regime, corep, pillar3, framework)

        observation.run_summaries.append(
            {
                "regime": regime,
                "portfolio": portfolio,
                "seconds": round(time.perf_counter() - started, 1),
                **report.status_counts(),
                "rules_enforced": report.rules_enforced,
                "rules_executed": report.rules_executed,
                "templates_emitted": len(report.templates_emitted),
                "templates_uncovered": len(report.templates_uncovered),
            }
        )

        del result, prior, corep, pillar3, report
        gc.collect()

    return observation


def _absorb_rules(observation: Observation, regime: str, report: ValidationReport) -> None:
    """Fold one run's rule outcomes into the estate-wide accumulators."""
    observation.rules_enforced[regime] = report.rules_enforced
    for outcome in report.outcomes:
        key = (regime, outcome.rule_id)
        observation.rule_statuses[key].add(outcome.status)
        observation.rule_severity[key] = outcome.severity
        observation.rule_label[key] = outcome.label or ""
        observation.rule_tables[key] = outcome.tables
        if outcome.status == STATUS_NOT_EVALUATED:
            observation.rule_reasons[key][outcome.reason or "unknown"] += 1


def _absorb_cells(
    observation: Observation,
    regime: str,
    corep: Any,
    pillar3: Any,
    framework: str,
) -> None:
    """Fold one run's generated template cells into the liveness accumulators.

    A cell is *declared* when the run emitted a frame containing it, and *live*
    when it carries a value. Declaring is deliberately taken from the emitted
    frames rather than from a template definition: the frame's shape IS the
    estate's declaration of what it reports, and a row or column the generator
    never emits at all is a different (and larger) problem than one that emits
    null -- the register already reports that as ``sheet_not_emitted``.
    """
    index = build_template_index(corep, pillar3, framework)
    template_of = _template_codes(index.bindings)

    for attribute, sheets in index.frames.items():
        template = template_of.get(attribute, attribute)
        for sheet, frame in sheets.items():
            if frame.is_empty():
                continue
            rows = _row_refs(frame)
            for column, dtype in zip(frame.columns, frame.dtypes, strict=True):
                # Template cells are numeric. The string columns are the row
                # axis labels (row_ref / row_name / label), which carry no
                # assertion and would inflate the denominator.
                if not dtype.is_numeric():
                    continue
                values = frame.get_column(column).to_list()
                for row, value in zip(rows, values, strict=True):
                    address = CellAddress(regime, template, sheet, row, column)
                    observation.cells_declared.add(address)
                    if value is not None:
                        observation.cells_live.add(address)
                        if value != 0:
                            observation.cells_nonzero.add(address)


def _template_codes(bindings: Any) -> dict[str, str]:
    """Bundle attribute -> publisher table code, e.g. ``c07_00`` -> ``C 07.00``.

    Several table codes can share one attribute (the ``.a`` / ``.b`` DPM
    variants are column partitions of a single frame), so the shortest code
    wins: it is the one a reader recognises.
    """
    best: dict[str, str] = {}
    for code, binding in sorted(bindings.items()):
        attribute = getattr(binding, "attribute", None)
        if attribute is None:
            continue
        current = best.get(attribute)
        if current is None or len(code) < len(current):
            best[attribute] = code
    return best


def _row_refs(frame: pl.DataFrame) -> list[str]:
    """The row axis of a generated template, as strings."""
    for candidate in ("row_ref", "row_label", "label", "row_name"):
        if candidate in frame.columns:
            return [str(value) for value in frame.get_column(candidate).to_list()]
    return [str(position) for position in range(frame.height)]


# =============================================================================
# Metrics
# =============================================================================


def summarise(observation: Observation) -> dict[str, Any]:
    """Turn the accumulated facts into the four metrics plus their evidence."""
    regimes = sorted(observation.rules_enforced)

    binding: dict[str, int] = {}
    never: dict[str, list[dict[str, Any]]] = {}
    for regime in regimes:
        keys = [key for key in observation.rule_statuses if key[0] == regime]
        binding[regime] = sum(
            1 for key in keys if observation.rule_statuses[key] & {STATUS_PASS, STATUS_FAIL}
        )
        never[regime] = sorted(
            (
                {
                    "regime": regime,
                    "rule_id": key[1],
                    "severity": observation.rule_severity[key],
                    "label": observation.rule_label[key][:160],
                    "tables": list(observation.rule_tables[key]),
                    "reasons": dict(observation.rule_reasons[key].most_common()),
                }
                for key in keys
                if observation.rule_statuses[key] == {STATUS_NOT_EVALUATED}
            ),
            key=lambda entry: (
                SEVERITY_RANK.get(entry["severity"], 9),
                entry["rule_id"],
            ),
        )

    dead = sorted(observation.cells_declared - observation.cells_live)
    declared = len(observation.cells_declared)
    live = len(observation.cells_live)
    liveness = live / declared if declared else 0.0

    metrics: dict[str, Any] = {
        # Ratchet: may not decrease.
        "union_binding_rules_crr": binding.get("crr", 0),
        "union_binding_rules_b31": binding.get("b31", 0),
        # Ratchet: may not decrease. Emitted as a float and as an integer
        # basis-point mirror, because arch_metrics.json values are integers.
        "template_cell_liveness": round(liveness, 6),
        "template_cell_liveness_bp": int(round(liveness * 10_000)),
        # Ratchet: may not increase.
        "dead_cells": len(dead),
        # Ratchet: may not increase.
        "never_evaluated_rules": sum(len(entries) for entries in never.values()),
    }

    for regime in regimes:
        enforced = observation.rules_enforced[regime]
        metrics[f"rules_enforced_{regime}"] = enforced
        metrics[f"union_binding_pct_{regime}"] = (
            round(100.0 * binding[regime] / enforced, 2) if enforced else 0.0
        )
        metrics[f"never_evaluated_rules_{regime}"] = len(never[regime])
        metrics[f"never_evaluated_error_severity_{regime}"] = sum(
            1 for entry in never[regime] if entry["severity"] == "ERROR"
        )

    return {
        "metrics": metrics,
        "cells": {
            "declared": declared,
            "live": live,
            "dead": len(dead),
            # A cell that is only ever 0.00 is present but asserts nothing about
            # the portfolio. Not part of the headline metric (the plan defines
            # liveness as non-null), but a cheap and useful second reading.
            "live_but_always_zero": live - len(observation.cells_nonzero),
        },
        # The full list is the record; the roll-up is what somebody acts on.
        # A template with thousands of dead cells is a portfolio-matrix gap; one
        # with three is probably a broken cell.
        "dead_cells_by_template": [
            {"regime": regime, "template": template, "dead": count}
            for (regime, template), count in sorted(
                Counter((cell.regime, cell.template) for cell in dead).items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
        "dead_cell_list": [address.describe() for address in dead],
        "never_evaluated_list": [entry for regime in regimes for entry in never[regime]],
    }


# =============================================================================
# LESSONS graduations
# =============================================================================


def check_portfolios_registered() -> dict[str, Any]:
    """LESSONS B5: every reporting portfolio fixture is referenced in ``RUNS``.

    An unregistered portfolio does not fail: it makes every rule over the
    columns it would have populated NOT_EVALUATED, which is indistinguishable
    from a clean estate. The C 07.00 CCF block hid four defects behind exactly
    this for the template's whole life.
    """
    registered = {run.build_bundle.__name__ for run in RUNS}
    declared: dict[str, list[str]] = {}
    for path in sorted(FIXTURES_DIR.glob("reporting_*.py")):
        builders = _bundle_builders(path)
        if builders:
            declared[path.name] = builders

    missing = sorted(
        f"{module}::{builder}"
        for module, builders in declared.items()
        for builder in builders
        if builder not in registered
    )
    return {
        "name": "every reporting portfolio fixture is referenced in RUNS",
        "portfolio_modules": len(declared),
        "bundle_builders": sum(len(builders) for builders in declared.values()),
        "registered_in_runs": len(registered),
        "unregistered": missing,
        "passed": not missing,
    }


def check_builders_registered() -> dict[str, Any]:
    """Every fixture builder that writes a parquet is called from generate_all.

    A parquet nobody regenerates works locally -- the file is already on disk --
    and fails on a fresh checkout, which is the worst place to find out.

    ``generate_all.py`` imports its builders by bare module name after inserting
    the group directory on ``sys.path``, so the reference to look for is the
    module stem in an import or a string constant, matched exactly. Substring
    matching would silently accept ``p1_10`` for ``p1_100``.
    """
    referenced = _referenced_names(GENERATE_ALL)
    unregistered: list[dict[str, Any]] = []
    allowed: list[dict[str, Any]] = []
    total = 0
    for path in sorted(FIXTURES_DIR.rglob("*.py")):
        if path.name == "generate_all.py":
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        if "write_parquet" not in source:
            continue
        total += 1
        stem = path.stem
        qualified = f"{path.parent.name}.{stem}"
        if stem in referenced or qualified in referenced:
            continue
        rel = str(path.relative_to(_REPO_ROOT)).replace("\\", "/")
        if rel in _REGISTRATION_ALLOWLIST:
            allowed.append({"module": rel, "reason": _REGISTRATION_ALLOWLIST[rel]})
            continue
        unregistered.append(
            {
                "module": str(path.relative_to(_REPO_ROOT)).replace("\\", "/"),
                # A module whose only parquet write sits behind a __main__ guard
                # is a standalone dump, not a fixture the suite depends on. The
                # distinction is reported rather than assumed, so the reader can
                # decide whether it needs registering.
                "has_main_guard": '__name__ == "__main__"' in source,
            }
        )

    return {
        "name": "every parquet-writing fixture builder is registered in generate_all.py",
        "parquet_builders": total,
        "unregistered": unregistered,
        "allowlisted": allowed,
        "passed": not unregistered,
    }


def _bundle_builders(path: Path) -> list[str]:
    """Top-level ``build_*_bundle`` functions declared by a fixture module."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name.startswith("build_")
        and node.name.endswith("_bundle")
    ]


def _referenced_names(path: Path) -> set[str]:
    """Module names imported or named as string constants by ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
    return names


# =============================================================================
# Reporting
# =============================================================================


def print_summary(payload: dict[str, Any]) -> None:
    """Human summary, ERROR-severity never-evaluated rules first."""
    metrics = payload["metrics"]
    cells = payload["cells"]

    print()
    print("=" * 78)
    print("REPORTING COVERAGE - estate-wide, union over the RUNS matrix")
    print("=" * 78)

    print("\nBinding rules (PASS or FAIL somewhere; VACUOUS excluded)")
    for regime in ("crr", "b31"):
        binding = metrics.get(f"union_binding_rules_{regime}")
        if binding is None:
            continue
        enforced = metrics.get(f"rules_enforced_{regime}", 0)
        pct = metrics.get(f"union_binding_pct_{regime}", 0.0)
        print(f"  {regime:4} {binding:>5} of {enforced:>5} enforced   {pct:>6.2f}%")

    print("\nTemplate cells")
    print(f"  declared             {cells['declared']:>7}")
    print(f"  live (non-null)      {cells['live']:>7}")
    print(f"  dead                 {cells['dead']:>7}")
    print(f"  live but always zero {cells['live_but_always_zero']:>7}")
    print(f"  liveness             {metrics['template_cell_liveness']:>7.4f}")

    never = payload["never_evaluated_list"]
    errors = [entry for entry in never if entry["severity"] == "ERROR"]
    print(f"\nNever-evaluated rules: {len(never)} ({len(errors)} at ERROR severity)")
    if errors:
        print("  ERROR severity - the estate is unchecked where a break is fatal:")
        for entry in errors[:PRINTED_ROWS]:
            reasons = ", ".join(entry["reasons"]) or "unknown"
            tables = ",".join(entry["tables"][:3])
            print(f"    {entry['regime']:4} {entry['rule_id']:<16} {tables:<28} {reasons}")
        if len(errors) > PRINTED_ROWS:
            print(f"    ... {len(errors) - PRINTED_ROWS} more (full list in the JSON)")

    dead_list = payload["dead_cell_list"]
    rollup = payload["dead_cells_by_template"]
    if dead_list:
        print(f"\nDead cells: {len(dead_list)}, worst templates first")
        for entry in rollup[:PRINTED_ROWS]:
            print(f"    {entry['regime']:4} {entry['template']:<24} {entry['dead']:>6}")
        if len(rollup) > PRINTED_ROWS:
            print(f"    ... {len(rollup) - PRINTED_ROWS} more templates")
        print(f"    first dead cell: {dead_list[0]}")
        print("    (full per-cell list in the JSON)")

    print("\nChecks")
    for check in payload["checks"].values():
        status = "PASS" if check["passed"] else "FAIL"
        print(f"  [{status}] {check['name']}")
        for entry in check["unregistered"]:
            print(f"           {entry if isinstance(entry, str) else entry['module']}")

    print("\nMetric names for arch_metrics.json:")
    for name in (
        "union_binding_rules_crr",
        "union_binding_rules_b31",
        "template_cell_liveness_bp",
        "dead_cells",
        "never_evaluated_rules",
    ):
        print(f"  {name:<32} {metrics[name]}")


def _display(path: Path) -> str:
    """Repo-relative when it can be, absolute otherwise."""
    try:
        return str(path.relative_to(_REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


BASELINE_PATH = _REPO_ROOT / "scripts" / "coverage_baseline.json"

# Coverage must ratchet the RIGHT WAY on each metric. Binding rules and cell
# liveness may not fall; dead cells and never-evaluated rules may not rise.
#
# This deliberately does NOT live in arch_check.py's ratchet, which runs on
# every commit via the pre-commit hook: measuring these costs a ~46s full-matrix
# pipeline run, and a gate that adds 46s to every commit is a gate somebody
# switches off. Run `--check` in CI instead.
_RATCHET_MIN = ("union_binding_rules_crr", "union_binding_rules_b31", "template_cell_liveness_bp")
_RATCHET_MAX = ("dead_cells", "never_evaluated_rules")


def _ratchet_values(payload: dict[str, Any]) -> dict[str, int]:
    metrics = payload["metrics"]
    return {name: int(metrics[name]) for name in (*_RATCHET_MIN, *_RATCHET_MAX)}


def _write_baseline(payload: dict[str, Any], *, partial: bool) -> int:
    if partial:
        print("\nREFUSING to write a baseline from a partial matrix (--limit).")
        return 1
    BASELINE_PATH.write_text(
        json.dumps(
            {
                "_comment": (
                    "Coverage ratchet baseline (scripts/coverage_report.py --check). "
                    "union_binding_* and template_cell_liveness_bp may not DECREASE; "
                    "dead_cells and never_evaluated_rules may not INCREASE. Update only "
                    "after a deliberate, recorded improvement — never to clear a red gate."
                ),
                **_ratchet_values(payload),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote baseline {BASELINE_PATH.relative_to(_REPO_ROOT)}")
    return 0


def _check_baseline(payload: dict[str, Any], *, partial: bool) -> int:
    if partial:
        print("\nREFUSING to ratchet against a partial matrix (--limit): the metrics")
        print("are computed as a union across runs and a short matrix understates them.")
        return 1
    if not BASELINE_PATH.exists():
        print(f"\nNo baseline at {BASELINE_PATH.relative_to(_REPO_ROOT)}; --update-baseline first.")
        return 1

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    measured = _ratchet_values(payload)
    regressions: list[str] = []
    improvements: list[str] = []
    for name in _RATCHET_MIN:
        was, now = int(baseline[name]), measured[name]
        if now < was:
            regressions.append(f"{name}: {was} -> {now} (may not decrease)")
        elif now > was:
            improvements.append(f"{name}: {was} -> {now}")
    for name in _RATCHET_MAX:
        was, now = int(baseline[name]), measured[name]
        if now > was:
            regressions.append(f"{name}: {was} -> {now} (may not increase)")
        elif now < was:
            improvements.append(f"{name}: {was} -> {now}")

    print("\nCoverage ratchet")
    for line in improvements:
        print(f"  [IMPROVED] {line}")
    if regressions:
        for line in regressions:
            print(f"  [REGRESSED] {line}")
        print("\nCoverage went backwards. Either restore it, or update the baseline")
        print("deliberately with --update-baseline and say why in the commit message.")
        return 1
    if improvements:
        print("\n  Coverage improved. Re-run with --update-baseline to bank it.")
    else:
        print("  [OK] no metric moved")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="JSON output path")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="run only the first N entries of RUNS (smoke testing only — the "
        "metrics are meaningless on a partial matrix)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="ratchet the measured metrics against scripts/coverage_baseline.json "
        "and exit non-zero on a regression (CI, not pre-commit — this takes ~46s)",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="rewrite scripts/coverage_baseline.json from this run. Only ever "
        "after a deliberate, recorded improvement — never to clear a red gate",
    )
    args = parser.parse_args()

    started = time.perf_counter()
    print(
        f"Running {len(RUNS if not args.limit else RUNS[: args.limit])} portfolio/regime runs ..."
    )
    observation = observe_runs(args.limit)
    payload = summarise(observation)
    payload["checks"] = {
        "portfolios_registered": check_portfolios_registered(),
        "builders_registered": check_builders_registered(),
    }
    payload["runs"] = observation.run_summaries
    payload["runtime_seconds"] = round(time.perf_counter() - started, 1)
    payload["partial"] = bool(args.limit)

    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print_summary(payload)
    print(f"\nWrote {args.out.relative_to(_REPO_ROOT)} in {payload['runtime_seconds']}s")

    if args.update_baseline:
        return _write_baseline(payload, partial=bool(args.limit))
    if args.check:
        return _check_baseline(payload, partial=bool(args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
