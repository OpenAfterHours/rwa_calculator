#!/usr/bin/env python3
"""
Filing-mapping ratchet — how much of what we generate has a place in the taxonomy.

Pipeline position:
    (no pipeline stage — gates the estate-wide measurement of the pipeline's
    reporting output)
    RUNS (Basel 3.1)  ->  COREPGenerator  ->  filing.build_canonical_return
        ->  placed / unplaced cells  ->  scripts/filing_mapping_baseline.json

A submission is written from cells the regulator's taxonomy HAS. A figure this
calculator computes and puts in a row, column or sheet the taxonomy does not
have cannot be filed at all — and nothing else in the estate can see that,
because our template generators and our own tests share one idea of the layout
(``.claude/LESSONS.md`` B3: a test written from the same sentence as the code
proves nothing). The taxonomy pack is the independent source: it is compiled
from the Bank of England's own DPM files.

This script runs every Basel 3.1 portfolio in the supervisory register's matrix
(``RUNS``, imported and never re-declared), re-addresses each generated COREP
cell to the taxonomy's coordinates, and counts:

- ``placed_cells`` — distinct cells that landed on a taxonomy data point.
  May not FALL.
- ``unplaced_figures`` — distinct cells carrying a NON-ZERO figure that the
  taxonomy has no place for. May not RISE. Broken down per
  ``(template, reason)``, and no cell of that breakdown may rise either, so a
  fix in one template cannot hide a regression in another.

- ``structure_findings`` — facts that ARE placed and still cannot be filed: a
  value of the wrong type for its cell, or two cells the taxonomy treats as one
  data point holding different values. May not RISE, in total or for any
  ``(finding code, table)``. Counted as the most offending facts any one
  portfolio produces, so it does not grow merely because a portfolio is added.

- ``error_rule_breaks`` — Error-severity validation rules of the Bank's v4.1.1
  rule book that the placed return breaks, counted as (rule, portfolio) pairs.
  May not RISE, in total or for any one rule. An Error break rejects the whole
  submission, so this is the count that stands between a return that can be
  written and one that would be accepted. The rules are evaluated as the
  Bank's gateway evaluates them (``rwa_filer.boe``), which the referee
  differential holds to Arelle's verdicts.

All are absolute counts of the thing that matters (LESSONS B8): a ratio would
improve by deleting a template. A zero in a cell the taxonomy lacks loses
nothing and is not counted.

A rule in ``error_rules_by_rule`` is not thereby OUR defect (LESSONS C5): a few
published rules cannot be satisfied by any return that follows the Bank's own
instructions. The baseline's ``_note`` and
``tests/expected_outputs/reporting/validation_known_breaks.json`` say which;
the ratchet only guarantees that the list cannot grow unseen.

The breakdown is the work list. Its largest entry today is the IRB templates'
sheet axis: ours is per exposure class, the published one also splits by
approach and by SME / non-SME, so a figure on one of our sheets cannot be
assigned to any single published sheet.

Usage:
    uv run python scripts/filing_mapping_report.py              # measure and print
    uv run python scripts/filing_mapping_report.py --check      # gate against the baseline
    uv run python scripts/filing_mapping_report.py --update-baseline

Bank a deliberate move with ``--update-baseline`` — re-measure it, never type
the numbers — and say why in the baseline's ``_note`` and the commit message.

Exit codes:
    0 = measured (and, with --check, nothing moved the wrong way)
    1 = a ratcheted number moved the wrong way, or the matrix changed

References:
- Bank of England Banking Taxonomy v4.1.1 (PRA001) — the cells that exist
- src/rwa_calc/reporting/filing/canonical.py — the re-addressing and the reasons
- docs/development/workspace.md
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.acceptance.reporting.test_supervisory_validations import RUNS  # noqa: E402

from rwa_calc.engine.pipeline import PipelineOrchestrator  # noqa: E402
from rwa_calc.reporting.corep.generator import COREPGenerator  # noqa: E402
from rwa_calc.reporting.filing.canonical import (  # noqa: E402
    FILING_MODULE,
    build_canonical_return,
)
from rwa_filer.boe.catalogue import SEVERITY_ERROR  # noqa: E402
from rwa_filer.boe.engine import STATUS_FAIL  # noqa: E402
from rwa_filer.model import ReturnHeader  # noqa: E402
from rwa_filer.rules.catalogue import FRAMEWORK_BASEL_3_1  # noqa: E402
from rwa_filer.taxonomy.pack import resolve_pack  # noqa: E402
from rwa_filer.validate.returns import validate_return  # noqa: E402

BASELINE_PATH = _REPO_ROOT / "scripts" / "filing_mapping_baseline.json"

#: A reference date inside the PRA001 taxonomy's validity (it applies from
#: 1 January 2027). Fixed, so the pack the ratchet reads does not drift with
#: the wall clock.
REFERENCE_DATE = date(2027, 3, 31)
#: A checksum-valid LEI. The mapping does not depend on who is reporting.
ENTITY_IDENTIFIER = "5493001KJTIIGC8Y1R12"

#: Ratcheted totals and the direction each may not move.
RATCHET_MIN = ("placed_cells",)
RATCHET_MAX = ("unplaced_figures", "structure_findings", "error_rule_breaks")

#: Each ratcheted-maximum total and the breakdown whose every cell is held too.
BREAKDOWNS = {
    "unplaced_figures": "unplaced_by_reason",
    "structure_findings": "structure_by_table",
    "error_rule_breaks": "error_rules_by_rule",
}

BASELINE_COMMENT = (
    "Filing-mapping ratchet baseline (scripts/filing_mapping_report.py --check). "
    "placed_cells may not DECREASE; unplaced_figures, structure_findings and "
    "error_rule_breaks, and every cell of their breakdowns (unplaced_by_reason, "
    "structure_by_table, error_rules_by_rule), may not INCREASE. "
    "Re-measure with --update-baseline after a deliberate change and say why in _note; never "
    "type the numbers."
)
UNEXPLAINED_NOTE = "unexplained — say why this baseline was re-banked"

#: Unplaced breakdown rows printed. The whole breakdown always goes to the baseline.
PRINTED_ROWS = 30


def main() -> int:
    """Measure, then print, gate or re-bank as asked."""
    parser = argparse.ArgumentParser(
        description="Measure how much of the generated Basel 3.1 COREP estate has a place "
        "in the PRA001 taxonomy, and ratchet it.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="fail if a ratcheted number moved the wrong way"
    )
    mode.add_argument(
        "--update-baseline", action="store_true", help="re-bank the baseline from this run"
    )
    args = parser.parse_args()

    started = time.perf_counter()
    measured = measure()
    print_report(measured, time.perf_counter() - started)

    if args.update_baseline:
        write_baseline(measured)
        print(f"\nWrote {BASELINE_PATH.relative_to(_REPO_ROOT).as_posix()}")
        return 0
    if args.check:
        problems = check_against_baseline(measured, load_baseline())
        print("\nFiling-mapping ratchet")
        if problems:
            for problem in problems:
                print(f"  [FAIL] {problem}")
            return 1
        print("  [OK] no metric moved")
    return 0


# =============================================================================
# Measurement
# =============================================================================


def measure() -> dict[str, Any]:
    """Run every Basel 3.1 portfolio in ``RUNS`` and accumulate the mapping facts.

    Cells are accumulated as SETS across runs, so a cell several portfolios
    populate counts once: the numbers are properties of the estate's layout, not
    of how many portfolios happen to exercise it.
    """
    header = ReturnHeader(ENTITY_IDENTIFIER, REFERENCE_DATE, FILING_MODULE)
    pack = resolve_pack(FILING_MODULE, REFERENCE_DATE)
    runs = filed_runs()
    placed: set[tuple[str, str | None, str | None, str, str]] = set()
    unplaced: dict[tuple[str, str], set[tuple[str | None, str, str]]] = {}
    structure: dict[str, int] = {}
    rule_breaks: dict[str, int] = {}

    for index, run in enumerate(runs, start=1):
        print(f"  [{index}/{len(runs)}] {run.regime}/{run.portfolio} ...", flush=True)
        result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
        corep = COREPGenerator().generate_from_lazyframe(result.results, framework=run.framework)
        mapping = build_canonical_return(corep, header, pack=pack)

        placed.update(
            mapping.canonical.facts.select(
                "table", "sheet", "open_key", "row", "column"
            ).iter_rows()
        )
        for template, sheet, row, column, reason in mapping.unplaced_figures.select(
            "template", "sheet", "row", "column", "reason"
        ).iter_rows():
            unplaced.setdefault((template, reason), set()).add((sheet, row, column))
        validation = validate_return(mapping.canonical, pack)
        for finding in validation.structure:
            key = f"{finding.code}|{finding.subject}"
            structure[key] = max(structure.get(key, 0), _offending_facts(finding.actual))
        if validation.report is None:
            raise SystemExit(f"no rule book is packaged for module {FILING_MODULE}")
        for outcome in validation.report.results:
            if outcome.status == STATUS_FAIL and outcome.severity == SEVERITY_ERROR:
                rule_breaks[outcome.rule_id] = rule_breaks.get(outcome.rule_id, 0) + 1

        del result, corep, mapping, validation
        gc.collect()

    breakdown = {
        f"{template}|{reason}": len(cells) for (template, reason), cells in sorted(unplaced.items())
    }
    return {
        "placed_cells": len(placed),
        "unplaced_figures": sum(breakdown.values()),
        "unplaced_by_reason": breakdown,
        "structure_findings": sum(structure.values()),
        "structure_by_table": dict(sorted(structure.items())),
        "error_rule_breaks": sum(rule_breaks.values()),
        "error_rules_by_rule": dict(sorted(rule_breaks.items())),
        "provenance": provenance(),
    }


def _offending_facts(actual: str) -> int:
    """The fact count a structure finding reports (``"3 fact(s)"``); 1 if it reports none."""
    head = actual.split(" ", 1)[0]
    return int(head) if head.isdigit() else 1


def filed_runs() -> list[Any]:
    """The portfolios measured: every Basel 3.1 run in the register's matrix.

    PRA001 is the Basel 3.1 return, so a CRR run has nothing to place in it.
    """
    return [run for run in RUNS if run.framework == FRAMEWORK_BASEL_3_1]


def provenance() -> dict[str, Any]:
    """The matrix the numbers are measured over — ordered, and costing no pipeline run.

    Every number here is a union across the runs, so a banked number means
    nothing apart from the matrix that produced it. Ordered, not merely counted:
    exchanging one portfolio for another leaves the count unchanged.
    """
    runs = filed_runs()
    return {
        "runs": len(runs),
        "portfolios": [{"regime": run.regime, "portfolio": run.portfolio} for run in runs],
    }


# =============================================================================
# Baseline
# =============================================================================


def load_baseline() -> dict[str, Any]:
    """Read the committed baseline. A missing one is a failure, never a pass."""
    if not BASELINE_PATH.exists():
        raise SystemExit(
            f"{BASELINE_PATH} does not exist. A ratchet with no baseline gates nothing: "
            "create it with --update-baseline."
        )
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def write_baseline(measured: dict[str, Any]) -> None:
    """Re-bank the baseline from this run, preserving a hand-written ``_note``."""
    note = UNEXPLAINED_NOTE
    if BASELINE_PATH.exists():
        note = json.loads(BASELINE_PATH.read_text(encoding="utf-8")).get("_note", note)
    payload = {"_comment": BASELINE_COMMENT, "_note": note, **measured}
    BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def check_against_baseline(measured: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Every way ``measured`` is worse than — or not comparable with — ``baseline``."""
    problems: list[str] = []
    if measured["provenance"] != baseline.get("provenance"):
        problems.append(
            "the portfolio matrix differs from the one the baseline was measured over, so "
            "the numbers are not comparable. Re-measure and bank with --update-baseline, "
            "saying why; do not drop a portfolio to make the banked numbers fit."
        )
        return problems

    unbanked = [name for name in (*RATCHET_MIN, *RATCHET_MAX) if name not in baseline]
    if unbanked:
        problems.append(
            f"the baseline does not bank {', '.join(unbanked)}, so nothing holds it. "
            "Re-measure and bank with --update-baseline."
        )
        return problems

    for name in RATCHET_MIN:
        if measured[name] < baseline[name]:
            problems.append(f"{name} fell: {baseline[name]} -> {measured[name]} (may not fall)")
    for name in RATCHET_MAX:
        if measured[name] > baseline[name]:
            problems.append(f"{name} rose: {baseline[name]} -> {measured[name]} (may not rise)")

    banked = baseline.get("unplaced_by_reason", {})
    for key, count in measured["unplaced_by_reason"].items():
        before = banked.get(key, 0)
        if count > before:
            template, reason = key.split("|", 1)
            problems.append(
                f"unplaced figures in {template} ({reason}) rose: {before} -> {count} "
                "(no cell of the breakdown may rise)"
            )
    banked = baseline.get("structure_by_table", {})
    for key, count in measured["structure_by_table"].items():
        before = banked.get(key, 0)
        if count > before:
            code, table = key.split("|", 1)
            problems.append(
                f"structure findings {code} in {table} rose: {before} -> {count} "
                "(no cell of the breakdown may rise)"
            )
    banked = baseline.get("error_rules_by_rule", {})
    for rule, count in measured["error_rules_by_rule"].items():
        before = banked.get(rule, 0)
        if count > before:
            problems.append(
                f"Error-severity rule {rule} is broken on more portfolios: {before} -> {count} "
                "(no rule's count may rise)"
            )
    return problems


# =============================================================================
# Reporting
# =============================================================================


def print_report(measured: dict[str, Any], seconds: float) -> None:
    """Print the totals and the unplaced breakdown, largest first."""
    print("\nRatcheted metrics:")
    print(f"  {'placed_cells':<24}{measured['placed_cells']:>8}   may not fall")
    print(f"  {'unplaced_figures':<24}{measured['unplaced_figures']:>8}   may not rise")
    print(f"  {'structure_findings':<24}{measured['structure_findings']:>8}   may not rise")
    print(f"  {'error_rule_breaks':<24}{measured['error_rule_breaks']:>8}   may not rise")
    breakdown = sorted(measured["unplaced_by_reason"].items(), key=lambda item: (-item[1], item[0]))
    if breakdown:
        print("\nNon-zero figures with no place in the taxonomy (template | reason):")
        for key, count in breakdown[:PRINTED_ROWS]:
            template, reason = key.split("|", 1)
            print(f"  {count:>6}  {template:<10} {reason}")
        if len(breakdown) > PRINTED_ROWS:
            print(f"  ... and {len(breakdown) - PRINTED_ROWS} more (all are in the baseline)")
    if measured["structure_by_table"]:
        print("\nPlaced facts that cannot be filed (finding | table | most in one portfolio):")
        for key, count in sorted(measured["structure_by_table"].items()):
            code, table = key.split("|", 1)
            print(f"  {count:>6}  {code}  {table}")
    if measured["error_rules_by_rule"]:
        print("\nError-severity rules the placed return breaks (portfolios | rule):")
        for rule, count in sorted(
            measured["error_rules_by_rule"].items(), key=lambda item: (-item[1], item[0])
        ):
            print(f"  {count:>6}  {rule}")
    print(f"\nMeasured {measured['provenance']['runs']} runs in {seconds:.1f}s")


if __name__ == "__main__":
    sys.exit(main())
