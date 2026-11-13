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

Both are absolute counts of the thing that matters (LESSONS B8): a ratio of the
two would improve by deleting a template. A zero in a cell the taxonomy lacks
loses nothing and is not counted.

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
from rwa_filer.model import ReturnHeader  # noqa: E402
from rwa_filer.rules.catalogue import FRAMEWORK_BASEL_3_1  # noqa: E402

BASELINE_PATH = _REPO_ROOT / "scripts" / "filing_mapping_baseline.json"

#: A reference date inside the PRA001 taxonomy's validity (it applies from
#: 1 January 2027). Fixed, so the pack the ratchet reads does not drift with
#: the wall clock.
REFERENCE_DATE = date(2027, 3, 31)
#: A checksum-valid LEI. The mapping does not depend on who is reporting.
ENTITY_IDENTIFIER = "5493001KJTIIGC8Y1R12"

#: Ratcheted totals and the direction each may not move.
RATCHET_MIN = ("placed_cells",)
RATCHET_MAX = ("unplaced_figures",)

BASELINE_COMMENT = (
    "Filing-mapping ratchet baseline (scripts/filing_mapping_report.py --check). "
    "placed_cells may not DECREASE; unplaced_figures, and every (template, reason) cell of "
    "unplaced_by_reason, may not INCREASE. Re-measure with --update-baseline after a "
    "deliberate change and say why in _note; never type the numbers."
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
    runs = filed_runs()
    placed: set[tuple[str, str | None, str | None, str, str]] = set()
    unplaced: dict[tuple[str, str], set[tuple[str | None, str, str]]] = {}

    for index, run in enumerate(runs, start=1):
        print(f"  [{index}/{len(runs)}] {run.regime}/{run.portfolio} ...", flush=True)
        result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
        corep = COREPGenerator().generate_from_lazyframe(result.results, framework=run.framework)
        mapping = build_canonical_return(corep, header)

        placed.update(
            mapping.canonical.facts.select(
                "table", "sheet", "open_key", "row", "column"
            ).iter_rows()
        )
        for template, sheet, row, column, reason in mapping.unplaced_figures.select(
            "template", "sheet", "row", "column", "reason"
        ).iter_rows():
            unplaced.setdefault((template, reason), set()).add((sheet, row, column))

        del result, corep, mapping
        gc.collect()

    breakdown = {
        f"{template}|{reason}": len(cells) for (template, reason), cells in sorted(unplaced.items())
    }
    return {
        "placed_cells": len(placed),
        "unplaced_figures": sum(breakdown.values()),
        "unplaced_by_reason": breakdown,
        "provenance": provenance(),
    }


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
    return problems


# =============================================================================
# Reporting
# =============================================================================


def print_report(measured: dict[str, Any], seconds: float) -> None:
    """Print the totals and the unplaced breakdown, largest first."""
    print("\nRatcheted metrics:")
    print(f"  {'placed_cells':<24}{measured['placed_cells']:>8}   may not fall")
    print(f"  {'unplaced_figures':<24}{measured['unplaced_figures']:>8}   may not rise")
    breakdown = sorted(measured["unplaced_by_reason"].items(), key=lambda item: (-item[1], item[0]))
    if breakdown:
        print("\nNon-zero figures with no place in the taxonomy (template | reason):")
        for key, count in breakdown[:PRINTED_ROWS]:
            template, reason = key.split("|", 1)
            print(f"  {count:>6}  {template:<10} {reason}")
        if len(breakdown) > PRINTED_ROWS:
            print(f"  ... and {len(breakdown) - PRINTED_ROWS} more (all are in the baseline)")
    print(f"\nMeasured {measured['provenance']['runs']} runs in {seconds:.1f}s")


if __name__ == "__main__":
    sys.exit(main())
