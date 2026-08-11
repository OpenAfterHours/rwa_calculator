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
-- and measures five things:

``union_binding_rules_crr`` / ``union_binding_rules_b31``
    Distinct rules reaching PASS or FAIL in at least one run. VACUOUS is
    excluded: a rule whose every operand was null or zero asserted nothing.
    This is the honest headline the per-run summary cannot produce.
``cells_live``
    Template cells carrying a value in at least one run, as an ABSOLUTE count.
    The cell-coverage floor: it falls if and only if the estate stopped
    reporting a figure it used to report.
``template_cell_liveness``
    The same thing as a fraction of declared cells. Useful reading, **not** a
    floor: its denominator moves with its numerator, so it can improve while
    coverage is destroyed.
``dead_cells``
    Cells never non-null in any run. Either the portfolio matrix is deficient
    or the cell is broken; both are work items, so both are listed. Also not a
    floor in disguise — it is ``declared - live``.
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
    uv run python scripts/coverage_report.py            # measure and print
    uv run python scripts/coverage_report.py --check     # measure and GATE

Output:
    scripts/coverage_metrics.json (override with --out), plus a human summary.

How this gates
--------------
``--check`` ratchets six metrics against ``scripts/coverage_baseline.json``
and exits non-zero on a regression: the two ``union_binding_rules_*`` counts,
``cells_live`` and ``template_cell_liveness_bp`` may not FALL, ``dead_cells`` and
``never_evaluated_rules`` may not RISE.

Of those, ``cells_live`` is the one that makes destroying cell coverage fail. The
ratio and the dead-cell count are **sometimes anti-signal** — both improve when
declared cells are dropped faster than live ones, and deleting a single run has been
measured doing exactly that. See the note on ``_RATCHET_MIN``. Two gates invoke it:

- the ``coverage-ratchet`` job in ``.github/workflows/ci.yml``, which runs the
  script directly so the exit code is the gate's own; and
- ``tests/contracts/test_coverage_ratchet.py``, which mirrors it as a ``slow``
  test and adds three always-on structural tests over the baseline itself —
  including one asserting the CI job still invokes ``--check``, because for its
  whole earlier life this ratchet was implemented and called by nothing.

Deliberately NOT in ``scripts/arch_metrics.json``: that ratchet runs on every
commit via the pre-commit hook, and measuring these costs a full-matrix pipeline
run. **Measured on the reference dev box over the 16-run ``RUNS``, fixtures already
on disk: 117-169s across five runs** (117.1, 118.1, 124.7, 136.2, 169.0), and slower
still on a cold first run. An earlier "~46s warm" figure in this file predated the
matrix growing to 16 and understated it by more than half. A gate that adds two
minutes to every commit is a gate somebody switches off.

One property to know before reading a red: the cell metrics are **not comparable
across a change to** ``RUNS``. Registering a portfolio declares its templates'
cells, most of which no other portfolio fills, so ``dead_cells`` rises and
liveness falls on exactly the change ``.claude/LESSONS.md`` B5 asks for. When the
matrix grows, re-measure and bank the new numbers with the reason — do not chase
the old ones back.

That property is why the baseline carries a ``provenance`` block naming the run
count and the ORDERED ``(regime, portfolio)`` matrix it was measured over, and why
``--check`` compares it FIRST and refuses to compute any delta across a mismatch.
Without it a matrix change arrives as a mystery regression: the four runs the
real-estate carrier batch added were measured as ``dead_cells 52817 -> 55553`` and
``liveness 1298 -> 1285`` on a tree whose coverage had strictly improved — and the
cheapest way to clear that red is to delete the portfolio that caused it. The
ordered list, not just the count, because swapping one portfolio for another
leaves ``len(RUNS)`` unchanged.

The two ``LESSONS`` graduation checks below also gate ``--check``'s exit code. They
did not until ``EXCLUDED_PORTFOLIOS`` landed: the portfolio check reported a
permanent FALSE POSITIVE against
``tests/fixtures/reporting_funded_protection_portfolio.py``, which is withheld from
``RUNS`` deliberately, and a gate with a known false red teaches the next reader to
ignore a red. The allowlist came first, the binding second — deliberately in that
order.
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

#: The metrics JSON may land inside the repo or in a sibling directory, never
#: anywhere else — a faulty ``--out`` must not be able to write elsewhere.
_ALLOWED_ROOT = _REPO_ROOT.parent

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

#: Reporting portfolio bundle-builders deliberately NOT referenced in ``RUNS``,
#: keyed exactly as ``check_portfolios_registered`` reports them
#: (``<module>.py::<builder>``) so the allowlist and the finding cannot drift into
#: different spellings. An entry needs a written reason; an entry with no reason is
#: not an entry.
#:
#: This mirrors ``scripts/check_template_cell_coverage.py::EXCLUDED_PORTFOLIOS``,
#: which has carried the same exclusion since that census was built. Without an
#: allowlist here the B5 graduation check below reported a permanent FALSE
#: POSITIVE — which is the reason its result went unread, and is why the allowlist
#: had to land BEFORE the check was bound to the exit code. A gate with a known
#: false red teaches the next reader to ignore a red.
EXCLUDED_PORTFOLIOS: dict[str, str] = {
    "reporting_funded_protection_portfolio.py::build_reporting_fcsm_bundle": (
        "WITHHELD from RUNS deliberately, not an oversight. Registering it needs a config "
        "electing the Art. 222 financial-collateral SIMPLE Method, which is not a parameter "
        "of _sa_config; registered against that factory (it defaults to comprehensive) the "
        "fixture would sit in the gate with the one feature it exists to exercise silenced "
        "— C 07.00 col 0070 reads 0.00 under comprehensive and non-zero under SIMPLE on the "
        "identical bundle. Registered CORRECTLY it exposes two ERROR-severity supervisory "
        "breaks (boe_b0471, v0308_m) that PRE-DATE the carrier-conservation fix, so the "
        "registration is filed as a Tier 1 item together with the residual Art. 222 defect "
        "rather than banked here. Full reasoning: the DELIBERATELY NOT REGISTERED comment "
        "in tests/acceptance/reporting/test_supervisory_validations.py."
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
    memory: twenty-four pipeline runs never coexist — ``len(RUNS)`` is 16, of which
    exactly 8 carry a ``build_prior_config`` and so drive a second, prior-period
    run each.

    Counted from ``RUNS`` rather than written from memory, because this docstring
    said "eighteen (twelve, plus ... six)" until 2026-08-09: numbers that were right
    for the pre-RE-carrier matrix and then quietly weren't. That is the same
    staleness the baseline's ``provenance`` field exists to make impossible, one
    screen below it.
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
            if not frame.is_empty():
                _absorb_frame(observation, regime, template, sheet, frame)


def _absorb_frame(
    observation: Observation,
    regime: str,
    template: str,
    sheet: str,
    frame: pl.DataFrame,
) -> None:
    """Fold one emitted sheet's numeric cells into the liveness sets."""
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
    """Turn the accumulated facts into the ratcheted metrics plus their evidence."""
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
        # Ratchet: may not decrease. THE cell-coverage floor, and the only one of
        # the three cell numbers that behaves like a floor — see the note on
        # _RATCHET_MIN. An absolute count of cells some run puts a value in: it can
        # only fall if the estate really stopped reporting a figure it used to
        # report, whatever happens to the denominator.
        "cells_live": live,
        # Ratchet: may not decrease — but read the note on _RATCHET_MIN before
        # trusting it. A RATIO whose denominator shrinks with its numerator, so it
        # can IMPROVE while coverage is destroyed. Kept because it is the plan's
        # published headline and a useful reading, not because it is a floor.
        # Emitted as a float and as an integer basis-point mirror, because
        # arch_metrics.json values are integers.
        "template_cell_liveness": round(liveness, 6),
        "template_cell_liveness_bp": int(round(liveness * 10_000)),
        # Ratchet: may not increase. Also not a floor in disguise: this is
        # declared - live, so dropping declared cells lowers it.
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

    ``EXCLUDED_PORTFOLIOS`` carries the deliberate omissions, each with its
    reason. A STALE entry — one naming a builder that is now registered, or one
    that no longer exists — fails the check rather than being ignored: an
    allowlist that outlives its reason is a hole in the gate that reads as a pass,
    and this check exists precisely to stop a hole reading as a pass.
    """
    registered = {run.build_bundle.__name__ for run in RUNS}
    declared: dict[str, list[str]] = {}
    for path in sorted(FIXTURES_DIR.glob("reporting_*.py")):
        builders = _bundle_builders(path)
        if builders:
            declared[path.name] = builders

    unregistered = sorted(
        f"{module}::{builder}"
        for module, builders in declared.items()
        for builder in builders
        if builder not in registered
    )
    missing = [entry for entry in unregistered if entry not in EXCLUDED_PORTFOLIOS]
    stale = sorted(set(EXCLUDED_PORTFOLIOS) - set(unregistered))
    return {
        "name": "every reporting portfolio fixture is referenced in RUNS",
        "portfolio_modules": len(declared),
        "bundle_builders": sum(len(builders) for builders in declared.values()),
        "registered_in_runs": len(registered),
        "unregistered": missing,
        # Same key and same entry shape as check_builders_registered's allowlist,
        # so one reader and one printer serve both checks.
        "allowlisted": [
            {"module": entry, "reason": EXCLUDED_PORTFOLIOS[entry]}
            for entry in unregistered
            if entry in EXCLUDED_PORTFOLIOS
        ],
        "stale_allowlist": stale,
        "passed": not missing and not stale,
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

    print()
    print("=" * 78)
    print("REPORTING COVERAGE - estate-wide, union over the RUNS matrix")
    print("=" * 78)

    _print_binding(metrics)
    _print_cells(metrics, payload["cells"])
    _print_never_evaluated(payload["never_evaluated_list"])
    _print_dead_cells(payload["dead_cell_list"], payload["dead_cells_by_template"])
    _print_checks(payload["checks"])

    print("\nRatcheted metrics:")
    for name in (*_RATCHET_MIN, *_RATCHET_MAX):
        direction = "may not fall" if name in _RATCHET_MIN else "may not rise"
        print(f"  {name:<32} {metrics[name]:>8}   {direction}")


def _print_binding(metrics: dict[str, Any]) -> None:
    print("\nBinding rules (PASS or FAIL somewhere; VACUOUS excluded)")
    for regime in ("crr", "b31"):
        binding = metrics.get(f"union_binding_rules_{regime}")
        if binding is None:
            continue
        enforced = metrics.get(f"rules_enforced_{regime}", 0)
        pct = metrics.get(f"union_binding_pct_{regime}", 0.0)
        print(f"  {regime:4} {binding:>5} of {enforced:>5} enforced   {pct:>6.2f}%")


def _print_cells(metrics: dict[str, Any], cells: dict[str, Any]) -> None:
    print("\nTemplate cells")
    print(f"  declared             {cells['declared']:>7}")
    print(f"  live (non-null)      {cells['live']:>7}")
    print(f"  dead                 {cells['dead']:>7}")
    print(f"  live but always zero {cells['live_but_always_zero']:>7}")
    print(f"  liveness             {metrics['template_cell_liveness']:>7.4f}")


def _print_never_evaluated(never: list[dict[str, Any]]) -> None:
    errors = [entry for entry in never if entry["severity"] == "ERROR"]
    print(f"\nNever-evaluated rules: {len(never)} ({len(errors)} at ERROR severity)")
    if not errors:
        return
    print("  ERROR severity - the estate is unchecked where a break is fatal:")
    for entry in errors[:PRINTED_ROWS]:
        reasons = ", ".join(entry["reasons"]) or "unknown"
        tables = ",".join(entry["tables"][:3])
        print(f"    {entry['regime']:4} {entry['rule_id']:<16} {tables:<28} {reasons}")
    if len(errors) > PRINTED_ROWS:
        print(f"    ... {len(errors) - PRINTED_ROWS} more (full list in the JSON)")


def _print_dead_cells(dead_list: list[str], rollup: list[dict[str, Any]]) -> None:
    if not dead_list:
        return
    print(f"\nDead cells: {len(dead_list)}, worst templates first")
    for entry in rollup[:PRINTED_ROWS]:
        print(f"    {entry['regime']:4} {entry['template']:<24} {entry['dead']:>6}")
    if len(rollup) > PRINTED_ROWS:
        print(f"    ... {len(rollup) - PRINTED_ROWS} more templates")
    print(f"    first dead cell: {dead_list[0]}")
    print("    (full per-cell list in the JSON)")


def _print_checks(checks: dict[str, Any]) -> None:
    print("\nChecks")
    for check in checks.values():
        status = "PASS" if check["passed"] else "FAIL"
        print(f"  [{status}] {check['name']}")
        for entry in check["unregistered"]:
            print(f"           {entry if isinstance(entry, str) else entry['module']}")
        # An allowlist entry that no longer applies is its own failure: it would
        # keep excusing a portfolio that has since been registered or renamed.
        for entry in check.get("stale_allowlist", ()):
            print(f"           stale allowlist entry, delete it: {entry}")
        for entry in check.get("allowlisted", ()):
            print(f"           (allowlisted) {entry['module']}")


def _display(path: Path) -> str:
    """Repo-relative when it can be, absolute otherwise."""
    try:
        return str(path.relative_to(_REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _confine_path(raw: Path) -> Path:
    """Resolve a CLI-supplied path and reject anything outside ``_ALLOWED_ROOT``.

    Same guard as ``scripts/parity_gate.py``: ``--out`` is operator-supplied,
    and resolving first collapses ``..`` segments so the containment check
    cannot be bypassed.
    """
    resolved = raw.expanduser().resolve()
    if not resolved.is_relative_to(_ALLOWED_ROOT):
        raise SystemExit(f"path escapes {_ALLOWED_ROOT}: {raw}")
    return resolved


BASELINE_PATH = _REPO_ROOT / "scripts" / "coverage_baseline.json"

# Coverage must ratchet the RIGHT WAY on each metric. Binding rules, LIVE CELLS
# and cell liveness may not fall; dead cells and never-evaluated rules may not rise.
#
# `cells_live` is the cell-coverage floor, and it is here because the other two cell
# numbers are not floors at all — they are sometimes ANTI-signal:
#
#   - `template_cell_liveness_bp` is a RATIO whose denominator shrinks with its
#     numerator, and `dead_cells` is `declared - live`. So dropping N declared cells
#     of which K are live IMPROVES both whenever K/N is at or below the current
#     liveness (~0.1285 today).
#   - Measured over all 16 leave-one-out deletions of the current matrix, not
#     theorised. On 4 of 16, BOTH cell metrics moved the passing way while live cells
#     were destroyed: b31/rich (-689 live, bp 1285->1374, dead 55553->47123),
#     crr/sa-classes (-441), b31/sa-classes (-367, bp ->1458), b31/re-split (-141).
#     On 6 more exactly one of the two passed. Only 4 of the 16 were caught by both.
#   - `cells_live` fell on every deletion that actually cost live cells — 14 of 16 —
#     and never rose on a loss. The two exceptions, crr/art199 and b31/art199, cost
#     ZERO live cells: neither contributes a uniquely-live cell, so there was nothing
#     for a cell metric to catch. (Cells only; this probe did not measure whether
#     those two runs are load-bearing for RULE binding, which they may well be.)
#   - It is an absolute count, so a shrinking denominator cannot flatter it.
#
# The ratio is retained (it is the plan's published headline and reads well next to
# the absolute counts) but it is NOT what makes destroying coverage fail.
#
# This deliberately does NOT live in arch_check.py's ratchet, which runs on
# every commit via the pre-commit hook: measuring these costs a full-matrix
# pipeline run of ~120-170s (see the module docstring for the measurements), and a
# gate that adds two minutes to every commit is a gate somebody switches off. Run
# `--check` in CI instead.
_RATCHET_MIN = (
    "union_binding_rules_crr",
    "union_binding_rules_b31",
    "cells_live",
    "template_cell_liveness_bp",
)
_RATCHET_MAX = ("dead_cells", "never_evaluated_rules")

#: The baseline's self-describing header. A constant so the committed file and this
#: script cannot drift apart, as in ``check_template_cell_coverage.py``.
BASELINE_COMMENT = (
    "Coverage ratchet baseline (scripts/coverage_report.py --check). union_binding_*, "
    "cells_live and template_cell_liveness_bp may not DECREASE; dead_cells and "
    "never_evaluated_rules may not INCREASE. Update only after a deliberate, recorded "
    "improvement — never to clear a red gate. READ THIS BEFORE TRUSTING A GREEN: "
    "cells_live is the cell-coverage floor. template_cell_liveness_bp is a RATIO whose "
    "denominator shrinks with its numerator and dead_cells is declared-minus-live, so both "
    "can IMPROVE while coverage is destroyed — measured, deleting the b31/rich run loses "
    "689 live cells while moving liveness 1285->1374bp and dead 55553->47123. Only "
    "cells_live and the binding-rule counts fail on that. Separately, every metric is a "
    "UNION over the portfolio x regime matrix recorded in provenance, so growing RUNS makes "
    "dead_cells RISE and template_cell_liveness_bp FALL by declaring cells no portfolio "
    "fills yet; on a matrix change --check reports the comparison as INVALID rather than as "
    "a regression, and the right response is to re-measure and bank the new matrix with the "
    "reason in _note — never to drop a portfolio so the old numbers fit again."
)

#: Written into a re-banked baseline that carries no hand-written reason. ``_note``
#: is PRESERVED across ``--update-baseline`` precisely so the reason survives a
#: re-measurement; this placeholder is what an unexplained bank looks like.
UNEXPLAINED_NOTE = "unexplained — say why this baseline was re-banked"

#: Printed when the baseline's matrix does not match the live ``RUNS``.
#:
#: Deliberately NOT the "coverage went backwards, put it back" wording used for a
#: real regression. On a GROWN matrix the two cell metrics legitimately worsen,
#: because registering a portfolio DECLARES its templates' cells and most of them
#: no other portfolio fills. Telling a reader to put those numbers back invites
#: deleting a portfolio from ``RUNS`` to clear the red — destroying real coverage to
#: satisfy a stale number, which is ``.claude/LESSONS.md`` B5 exactly inverted. So
#: this text says the comparison is INVALID, says in terms that it is not a
#: regression, and names the only correct action.
_MATRIX_MOVED = """
These metrics are a UNION over the matrix, so numbers measured over two different
matrices are not comparable: nothing above says coverage got worse. Registering a
portfolio DECLARES its templates' cells, most of which no other portfolio fills,
so dead_cells RISES and template_cell_liveness_bp FALLS on exactly the change
.claude/LESSONS.md B5 asks for.

Do NOT drop a portfolio from RUNS to make the banked numbers fit again, and do not
chase the cell metrics back to their banked values — either would destroy real
coverage to satisfy a stale number. Re-measure and bank the new matrix, saying why
in the baseline's _note and in the commit message:
  uv run python scripts/coverage_report.py --update-baseline"""


def _ratchet_values(payload: dict[str, Any]) -> dict[str, int]:
    metrics = payload["metrics"]
    return {name: int(metrics[name]) for name in (*_RATCHET_MIN, *_RATCHET_MAX)}


def provenance() -> dict[str, Any]:
    """The portfolio x regime matrix the metrics were measured over.

    Banked beside the numbers because a union metric is only meaningful next to
    the matrix that produced it, and because a matrix change otherwise arrives as
    a mystery regression — which is how the four runs the real-estate carrier
    batch added read as a coverage loss.

    The ORDERED portfolio list is recorded, not merely the count: exchanging one
    portfolio for another leaves ``len(RUNS)`` unchanged, so a count alone cannot
    detect a swap. Same shape and same reasoning as
    ``check_template_cell_coverage.py``'s ``provenance``.
    """
    return {
        "runs": len(RUNS),
        "portfolios": [{"regime": run.regime, "portfolio": run.portfolio} for run in RUNS],
    }


def _provenance_mismatch(baseline: dict[str, Any]) -> list[str] | None:
    """How the baseline's matrix differs from the live one, or ``None`` if it does not."""
    live = provenance()
    banked = baseline.get("provenance")
    if not isinstance(banked, dict):
        return [
            "  baseline: NO provenance recorded — it predates this field, so the matrix",
            "            it was measured over is unknown and cannot be compared",
            f"  now:      {live['runs']} runs",
        ]

    banked_pairs = [
        (entry.get("regime"), entry.get("portfolio")) for entry in banked.get("portfolios", ())
    ]
    live_pairs = [(entry["regime"], entry["portfolio"]) for entry in live["portfolios"]]
    if banked.get("runs") == live["runs"] and banked_pairs == live_pairs:
        return None

    lines = [f"  baseline: {banked.get('runs')} runs", f"  now:      {live['runs']} runs"]
    dropped = sorted(set(banked_pairs) - set(live_pairs))
    added = sorted(set(live_pairs) - set(banked_pairs))
    if dropped:
        lines.append("  in the baseline only: " + ", ".join(f"{r}/{p}" for r, p in dropped))
    if added:
        lines.append("  in the live matrix only: " + ", ".join(f"{r}/{p}" for r, p in added))
    if banked_pairs == live_pairs:
        # The banked list agrees with the live matrix and only the banked COUNT
        # disagrees, so the baseline's two provenance fields contradict each other:
        # it was hand-edited rather than measured.
        lines.append(
            "  the recorded portfolio LIST matches the live matrix but the recorded run "
            "COUNT does not, so the baseline's own provenance is self-contradictory — it "
            "was hand-edited rather than measured"
        )
    elif not dropped and not added:
        # Order alone. The union is order-independent, so say so rather than
        # implying the numbers are wrong — but still refuse, because an ordered
        # comparison is what stops a real swap hiding behind an unchanged count.
        lines.append(
            "  the same portfolios in a DIFFERENT ORDER: the union metrics are themselves "
            "order-independent, but the recorded matrix must match the live one so that a "
            "genuine swap cannot hide behind an unchanged count"
        )
    return lines


def _ratchet_deltas(
    baseline: dict[str, Any], measured: dict[str, int]
) -> tuple[list[str], list[str]]:
    """(regressions, improvements) of the measured metrics against the baseline."""
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
    return regressions, improvements


def _write_baseline(payload: dict[str, Any], *, partial: bool) -> int:
    """Bank the metrics together with the matrix that produced them.

    ``_note`` — why THIS baseline was banked — is carried over from the committed
    file rather than regenerated: a re-measurement must not silently erase the
    record of why the previous numbers were accepted. It is the operator's line to
    edit, and the reminder below says so on every write.
    """
    if partial:
        print("\nREFUSING to write a baseline from a partial matrix (--limit).")
        return 1
    note = _existing_note()
    matrix = provenance()
    BASELINE_PATH.write_text(
        json.dumps(
            {
                "_comment": BASELINE_COMMENT,
                "_note": note,
                "provenance": matrix,
                **_ratchet_values(payload),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote baseline {BASELINE_PATH.relative_to(_REPO_ROOT)} over {matrix['runs']} runs")
    print(f"  _note: {note}")
    print("  _note is PRESERVED, not regenerated — update it to say why THIS bank happened.")
    return 0


def _existing_note() -> str:
    """The hand-written ``_note`` from the committed baseline, or the placeholder."""
    if not BASELINE_PATH.exists():
        return UNEXPLAINED_NOTE
    try:
        banked = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return UNEXPLAINED_NOTE
    note = banked.get("_note")
    return note if isinstance(note, str) and note.strip() else UNEXPLAINED_NOTE


def _check_baseline(payload: dict[str, Any], *, partial: bool) -> int:
    if partial:
        print("\nREFUSING to ratchet against a partial matrix (--limit): the metrics")
        print("are computed as a union across runs and a short matrix understates them.")
        return 1
    if not BASELINE_PATH.exists():
        print(f"\nNo baseline at {BASELINE_PATH.relative_to(_REPO_ROOT)}; --update-baseline first.")
        return 1

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    # Provenance FIRST, before any delta is computed. A delta against a different
    # matrix is not a delta at all, and PRINTING one is the harm: it names a metric
    # as regressed when it is not, and the cheapest way to make that red go away is
    # to delete the portfolio that caused it.
    mismatch = _provenance_mismatch(baseline)
    if mismatch is not None:
        print("\nCoverage ratchet")
        print("  [INVALID] the baseline was measured over a DIFFERENT portfolio x regime")
        print("            matrix, so no comparison was attempted and NO metric is claimed")
        print("            to have regressed.")
        for line in mismatch:
            print(line)
        print(_MATRIX_MOVED)
        return 1

    regressions, improvements = _ratchet_deltas(baseline, _ratchet_values(payload))

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


def _check_graduations(payload: dict[str, Any]) -> int:
    """Fail ``--check`` when either ``LESSONS`` graduation check is failing.

    Bound to the exit code only once ``EXCLUDED_PORTFOLIOS`` existed. Before that
    the portfolio check reported a permanent false positive, and binding a known
    false red teaches the next reader to ignore a red — which is how BOTH checks'
    results went unread for this script's whole life while the exit code watched
    only the ratcheted metrics.
    """
    failing = [check for check in payload["checks"].values() if not check["passed"]]
    if not failing:
        return 0

    print("\nLESSONS graduation checks FAILED")
    for check in failing:
        print(f"  [FAIL] {check['name']}")
        for entry in check["unregistered"]:
            print(f"         {entry if isinstance(entry, str) else entry['module']}")
        for entry in check.get("stale_allowlist", ()):
            print(f"         stale allowlist entry, delete it: {entry}")
    print(
        "\nA reporting portfolio missing from RUNS makes every rule over the columns it "
        "would\nhave populated NOT_EVALUATED, which reads exactly like a clean estate "
        "(.claude/LESSONS.md\nB5); a parquet-writing builder missing from generate_all.py "
        "works locally and fails on\na fresh checkout. Register it — or, if the omission is "
        "deliberate, add a reasoned entry\nto EXCLUDED_PORTFOLIOS / _REGISTRATION_ALLOWLIST "
        "in this script."
    )
    return 1


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
        "and exit non-zero on a regression (CI, not pre-commit — measured 117-169s "
        "over the 16-run matrix with fixtures already on disk)",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="rewrite scripts/coverage_baseline.json from this run. Only ever "
        "after a deliberate, recorded improvement — never to clear a red gate",
    )
    args = parser.parse_args()
    out = _confine_path(args.out)

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

    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print_summary(payload)
    print(f"\nWrote {_display(out)} in {payload['runtime_seconds']}s")

    if args.update_baseline:
        return _write_baseline(payload, partial=bool(args.limit))
    if args.check:
        # Both run before the exit code is decided: a reader facing a red is owed
        # every failure this measurement found, not just the first one.
        ratchet = _check_baseline(payload, partial=bool(args.limit))
        graduations = _check_graduations(payload)
        return max(ratchet, graduations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
