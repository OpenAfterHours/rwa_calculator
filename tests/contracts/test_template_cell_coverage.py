"""
Template (template, column) coverage gates (P5.21 / LESSONS B5 graduation).

``.claude/LESSONS.md`` B5 recurred in a form that registering a portfolio in
``RUNS`` cannot catch: the portfolio was registered and the CELL was dead. C
08.01 r0253 held ``0.00`` in all six golden portfolios, so the mandatory Tier 2
gate was structurally incapable of seeing a change to that column and passed
green over a simulated fix. The same blindness let the real-estate loan-splitter
duplicate ~34 inherited numeric columns across split legs.

``scripts/check_template_cell_coverage.py`` turns "are all the template fields
correct?" into a tracked number: which (template, column) pairs does the whole
portfolio estate never put a non-zero figure into. Two gates guard it:

- a FAST integrity test over the committed baseline — it runs in the dev loop,
  performs no pipeline run, and still catches the cheap failure (a column
  renamed or removed out from under the baseline) plus the expensive one (a dead
  column banked with no reason anybody can review); and
- a ``slow`` ratchet that re-measures the census and fails BOTH ways: a live
  column going dead is a regression, a dead column going live is an improvement
  that must be banked.

The slow test is excluded from the dev loop and from CI's default selection, so
it needs its own CI job — a ratchet nothing runs is prose with extra steps.

References:
- scripts/check_template_cell_coverage.py — the census and the two-way ratchet
- scripts/coverage_report.py — the neighbouring per-CELL COREP measure
- tests/contracts/test_docs_freshness.py — the same script-plus-ratchet shape
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_template_cell_coverage.py"
BASELINE_PATH = REPO_ROOT / "scripts" / "template_cell_coverage_baseline.json"

REGENERATE = "  uv run python scripts/check_template_cell_coverage.py --update-baseline"

#: Every dead entry must say which of these it is. The distinction is the whole
#: point: it separates a column that legitimately has no data from one we owe a
#: scenario.
VALID_STATUSES = frozenset({"always_zero", "never_emitted"})


def _load_census_module() -> Any:
    """Import the census script as a module.

    Imported rather than re-derived so the live column layout the integrity test
    checks against comes from the ONE place that reads the frozen template
    definitions. A second derivation here would be a hand-written list wearing a
    function's clothes, and would drift exactly when this test needs to fire
    (``.claude/LESSONS.md`` B3).
    """
    spec = importlib.util.spec_from_file_location("_template_cell_census", SCRIPT_PATH)
    assert spec is not None, f"no import spec for {SCRIPT_PATH}"
    assert spec.loader is not None, f"import spec for {SCRIPT_PATH} carries no loader"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CENSUS = _load_census_module()


def test_coverage_baseline_is_internally_coherent_and_still_addresses_real_columns() -> None:
    """The banked census parses, explains every dead column, and has not rotted.

    Arrange: the committed baseline plus the frozen template layouts.
    Act:     read the two column populations and the declared layout columns.
    Assert:  counts foot, every dead entry is classified, and every banked
             column still exists somewhere in the layouts.
    """
    # Arrange
    assert BASELINE_PATH.exists(), (
        f"No template-cell-coverage baseline at {BASELINE_PATH}. Capture it:\n{REGENERATE}"
    )
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    live: list[str] = payload["live_columns"]
    dead: list[dict[str, Any]] = payload["dead_columns"]
    counts: dict[str, Any] = payload["counts"]
    dead_ids = [entry["id"] for entry in dead]

    # Act
    declared = {key.describe() for key in CENSUS.declared_columns()}
    banked = set(live) | set(dead_ids)
    unclassified = [
        entry["id"]
        for entry in dead
        if entry.get("reason_code") not in CENSUS.REASON_CODES
        or not str(entry.get("reason", "")).strip()
        or entry.get("reason") == CENSUS.UNCLASSIFIED
    ]
    orphaned = sorted(banked - declared)

    # Assert — the population is well formed
    assert len(set(live)) == len(live), "duplicate id in live_columns"
    assert len(set(dead_ids)) == len(dead_ids), "duplicate id in dead_columns"
    assert not set(live) & set(dead_ids), "a column is banked as both live and dead"
    assert counts["live"] == len(live), (
        f"live count disagrees with the list: counts say {counts['live']} live, "
        f"the list holds {len(live)}.\n{REGENERATE}"
    )
    assert counts["dead"] == len(dead), (
        f"dead count disagrees with the list: counts say {counts['dead']} dead, "
        f"the list holds {len(dead)}.\n{REGENERATE}"
    )
    assert counts["template_column_pairs"] == len(banked), (
        f"template_column_pairs ({counts['template_column_pairs']}) is not "
        f"live + dead ({len(banked)}).\n{REGENERATE}"
    )

    # Assert — every dead column is reviewable
    assert not unclassified, (
        f"{len(unclassified)} dead column(s) carry no valid reason code + reason. A dead "
        "column with no written reason is an unreviewable number: say whether it is "
        f"{CENSUS.REASON_CODES[0]} (the engine does not hold the input) or "
        f"{CENSUS.REASON_CODES[1]} (a coverage gap we owe a scenario) and why:\n  "
        + "\n  ".join(unclassified)
    )
    assert all(entry.get("status") in VALID_STATUSES for entry in dead), (
        f"a dead entry carries a status outside {sorted(VALID_STATUSES)}.\n{REGENERATE}"
    )

    # Assert — the baseline still describes columns that exist
    assert not orphaned, (
        f"{len(orphaned)} banked column(s) no longer exist in any template layout — they "
        "were renamed or removed, so the ratchet has been silently guarding nothing:\n  "
        + "\n  ".join(orphaned)
        + f"\nRe-measure and bank the new layout:\n{REGENERATE}"
    )

    # Assert — the provenance says what the census actually covers
    provenance = payload["provenance"]
    assert provenance["runs"] == CENSUS.EXPECTED_RUNS, (
        f"the baseline was measured over {provenance['runs']} runs but the matrix is now "
        f"{CENSUS.EXPECTED_RUNS}. A census over a different portfolio set is a different "
        f"number:\n{REGENERATE}"
    )
    assert [(spec.source, spec.portfolio, spec.regime) for spec in CENSUS.run_specs()] == [
        (entry["source"], entry["portfolio"], entry["regime"]) for entry in provenance["portfolios"]
    ], f"the portfolio x regime matrix moved since the baseline was banked:\n{REGENERATE}"

    # Assert — every banked caveat identity is normalised, and names a real run.
    # The identities are the C 02.00 reconciliation stranding the census ratchets
    # two ways (P1.327). They are checked here, in the FAST test, because a
    # malformed or orphaned identity would otherwise only surface in the slow
    # ratchet, where it reads as a portfolio change rather than a broken record.
    known_runs = {f"{e['source']}/{e['portfolio']}/{e['regime']}" for e in provenance["portfolios"]}
    for identity in payload["caveat_identities"]:
        assert "<amount>" in identity, (
            f"caveat identity is not normalised, so float dust will redden the ratchet: "
            f"{identity!r}\n{REGENERATE}"
        )
        run_ref = identity.split(":", 1)[0]
        assert run_ref in known_runs, (
            f"caveat identity names {run_ref!r}, which is not in the census matrix. An "
            f"orphaned identity can never clear, so the ratchet is stuck red:\n{REGENERATE}"
        )


@pytest.mark.slow
def test_template_cell_coverage_matches_the_baseline() -> None:
    """Re-measure the estate and ratchet it both ways against the baseline.

    Excluded from the dev loop because it runs 30 pipeline runs (24 portfolio x
    regime combinations plus a prior-period run for each of the six that emit
    C 08.04) and 48 template generations — ~4 minutes measured. It needs its own
    CI job.

    Arrange: the committed baseline.
    Act:     re-run the whole portfolio x regime census.
    Assert:  no live column went dead, and no dead column went live unbanked.
    """
    # Arrange / Act
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    # Assert
    assert result.returncode == 0, (
        "Template cell coverage moved off the baseline. A LIVE column going dead is a "
        "REGRESSION — some portfolio stopped reporting a figure it used to report, and "
        "every gate written over that column just went blind (.claude/LESSONS.md B5); fix "
        "the reporting defect rather than banking it. A DEAD column going live is an "
        "IMPROVEMENT that must be banked, with a reason code for any newly dead column:\n"
        f"{REGENERATE}\n"
        f"{result.stdout[-4000:]}\n{result.stderr}"
    )
