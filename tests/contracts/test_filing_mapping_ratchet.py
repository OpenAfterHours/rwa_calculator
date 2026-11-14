"""
Filing-mapping ratchet gates.

Pipeline position:
    (no pipeline stage — gates the estate-wide measurement of the pipeline's
    reporting output)
    scripts/filing_mapping_report.py --check -> scripts/filing_mapping_baseline.json

``scripts/filing_mapping_report.py`` measures how much of the generated Basel 3.1
COREP estate has a place in the PRA001 taxonomy: ``placed_cells`` may not FALL,
``unplaced_figures`` — and every ``(template, reason)`` cell of its breakdown —
may not RISE. The taxonomy pack is compiled from the Bank of England's own DPM
files, so this is the one measure of our template layout that our generators
and our own tests cannot drift with (``.claude/LESSONS.md`` B3).

Cheap-vs-expensive split — the same one ``test_coverage_ratchet.py`` makes, for
the same reason. The real measurement is 13 pipeline runs; a test that adds that
to the dev loop is a test somebody switches off. So:

- **Always-on structural tests** that run no pipeline. They cannot see a mapping
  regression, but they catch every way the ratchet can be disarmed without one:
  a baseline that does not parse or does not foot, a number with no direction, a
  reason the adapter no longer emits, numbers measured over a matrix that no
  longer exists, a baseline weakened in the working tree, a re-bank nobody
  explained, the comparison itself going soft, and the CI job being deleted.
- One ``slow`` test that shells out to the real ``--check``. Its real home is
  the ``filing-mapping`` CI job, which invokes the script directly.

References:
- scripts/filing_mapping_report.py — the measurement and the ratchet
- scripts/filing_mapping_baseline.json — the banked values (never weaken to clear a red)
- src/rwa_calc/reporting/filing/canonical.py — the re-addressing and the reasons
- tests/contracts/test_coverage_ratchet.py — the same shape, over rule coverage
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from tests.contracts._ci_workflow import WORKFLOW_REL, gate_wiring_problems

from rwa_calc.reporting.filing import canonical
from rwa_filer.boe.catalogue import SEVERITY_ERROR, rulebook_for_module
from rwa_filer.taxonomy.pack import resolve_pack
from rwa_filer.validate import structure

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "filing_mapping_report.py"
BASELINE_PATH = REPO_ROOT / "scripts" / "filing_mapping_baseline.json"

#: Repo-relative and forward-slashed: the form ``git show <ref>:<path>`` wants and
#: the form the workflow file spells.
BASELINE_REL = "scripts/filing_mapping_baseline.json"
SCRIPT_REL = "scripts/filing_mapping_report.py"

REBANK = f"  uv run python {SCRIPT_REL} --update-baseline"

#: The workflow job that owns the measurement.
CI_JOB = "filing-mapping"
_INVOKES_CHECK = re.compile(re.escape(SCRIPT_REL) + r"[^\n]*?--check")

BREAKDOWN_KEY = "unplaced_by_reason"
STRUCTURE_KEY = "structure_by_table"
RULES_KEY = "error_rules_by_rule"
#: Keys the baseline carries beside its ratcheted totals. ``provenance`` and the
#: breakdowns are each asserted in their own right below; the other two are prose.
NON_METRIC_KEYS = frozenset(
    {"_comment", "_note", "provenance", BREAKDOWN_KEY, STRUCTURE_KEY, RULES_KEY}
)


def _load_script() -> Any:
    """Import the script as a module, so names and directions come from their owner."""
    spec = importlib.util.spec_from_file_location("_filing_mapping_report", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, f"no import spec for {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MAPPING = _load_script()


def _baseline() -> dict[str, Any]:
    assert BASELINE_PATH.exists(), (
        f"No filing-mapping baseline at {BASELINE_PATH}. Capture it:\n{REBANK}"
    )
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _known_reasons() -> set[str]:
    """Every reason the adapter can give, read from the adapter itself."""
    return {
        value
        for name, value in vars(canonical).items()
        if name.startswith("REASON_") and isinstance(value, str)
    }


# =============================================================================
# The baseline is a usable ratchet
# =============================================================================


def test_the_baseline_is_well_formed_and_every_total_declares_a_direction() -> None:
    """Every number in the baseline is ratcheted, exactly one way.

    Arrange: the committed baseline and the script's direction declarations.
    Act:     read the baseline's totals.
    Assert:  they are exactly the directed names, each a non-negative integer.
    """
    # Arrange
    baseline = _baseline()
    minimums, maximums = set(MAPPING.RATCHET_MIN), set(MAPPING.RATCHET_MAX)

    # Act
    banked = set(baseline) - NON_METRIC_KEYS

    # Assert
    assert not minimums & maximums, f"ratcheted both ways: {sorted(minimums & maximums)}"
    assert banked == minimums | maximums, (
        "the baseline's totals and the script's ratchet declarations disagree.\n"
        f"  banked but undirected (guarded by nothing): {sorted(banked - (minimums | maximums))}\n"
        f"  directed but unbanked (--check would KeyError): "
        f"{sorted((minimums | maximums) - banked)}\n{REBANK}"
    )
    bad = {
        name: baseline[name]
        for name in banked
        if isinstance(baseline[name], bool)
        or not isinstance(baseline[name], int)
        or baseline[name] < 0
    }
    assert not bad, f"baseline totals must be non-negative integers: {bad}.\n{REBANK}"


def test_the_breakdown_foots_to_its_total_and_names_only_known_reasons() -> None:
    """The per-(template, reason) breakdown is the total, and every reason is live.

    A breakdown that does not sum to ``unplaced_figures`` was edited by hand. A
    key naming a reason the adapter no longer emits is a cell of the ratchet
    that can never be compared with anything, so its banked count is a
    permanent allowance nobody is using.

    Arrange: the committed baseline and the adapter's reasons.
    Act:     split each breakdown key.
    Assert:  the counts foot, are positive, and every reason is the adapter's.
    """
    # Arrange
    baseline = _baseline()
    breakdown: dict[str, int] = baseline[BREAKDOWN_KEY]
    reasons = _known_reasons()

    # Act
    unknown = sorted(key for key in breakdown if key.split("|", 1)[-1] not in reasons)
    malformed = sorted(key for key in breakdown if key.count("|") != 1)

    # Assert
    assert reasons, "the adapter declares no REASON_* constants — nothing to check against"
    assert not malformed, f"breakdown keys must read `template|reason`: {malformed}"
    assert not unknown, (
        f"the baseline banks a reason the adapter cannot give: {unknown}. Known: "
        f"{sorted(reasons)}.\n{REBANK}"
    )
    assert all(isinstance(count, int) and count > 0 for count in breakdown.values()), (
        f"breakdown counts must be positive integers (a zero entry is not written).\n{REBANK}"
    )
    assert sum(breakdown.values()) == baseline["unplaced_figures"], (
        f"the breakdown sums to {sum(breakdown.values())} but unplaced_figures is "
        f"{baseline['unplaced_figures']}: the baseline was edited by hand.\n{REBANK}"
    )


def test_every_ratcheted_maximum_has_a_breakdown_that_foots_to_it() -> None:
    """Each may-not-rise total is held per cell too, and the cells are the total.

    Arrange: the committed baseline and the script's breakdown declarations.
    Act:     sum each breakdown.
    Assert:  every may-not-rise total names a breakdown, and it foots.
    """
    # Arrange
    baseline = _baseline()

    # Act / Assert
    assert set(MAPPING.BREAKDOWNS) == set(MAPPING.RATCHET_MAX), (
        "a may-not-rise total has no per-cell breakdown, so a fix in one table could hide "
        "a regression in another"
    )
    for total, breakdown in MAPPING.BREAKDOWNS.items():
        assert breakdown in baseline, f"the baseline has no {breakdown}.\n{REBANK}"
        assert sum(baseline[breakdown].values()) == baseline[total], (
            f"{breakdown} sums to {sum(baseline[breakdown].values())} but {total} is "
            f"{baseline[total]}: the baseline was edited by hand.\n{REBANK}"
        )


def test_the_structure_breakdown_names_real_finding_codes_and_tables() -> None:
    """A key no structure check can produce is an allowance nobody is using."""
    # Arrange
    keys = _baseline()[STRUCTURE_KEY]
    pack = resolve_pack(canonical.FILING_MODULE, MAPPING.REFERENCE_DATE)
    codes = {
        value
        for name, value in vars(structure).items()
        if name.startswith("FINDING_") and isinstance(value, str)
    }

    # Act
    unknown = sorted(
        key
        for key in keys
        if key.count("|") != 1
        or key.split("|")[0] not in codes
        or key.split("|")[1] not in {*pack.tables, pack.info.module}
    )

    # Assert
    assert codes, "rwa_filer.validate.structure declares no FINDING_* codes"
    assert not unknown, (
        f"the baseline banks structure findings no check can produce: {unknown}.\n{REBANK}"
    )


def test_the_rule_breakdown_names_error_rules_the_module_enforces() -> None:
    """A banked rule the rule book does not enforce as an Error is an allowance for nothing."""
    # Arrange
    banked = _baseline()[RULES_KEY]
    enforced = {
        rule.rule_id: rule.severity(canonical.FILING_MODULE)
        for rule in rulebook_for_module(canonical.FILING_MODULE).enforced(canonical.FILING_MODULE)
    }
    portfolios = _baseline()["provenance"]["runs"]

    # Act
    unknown = sorted(rule for rule in banked if enforced.get(rule) != SEVERITY_ERROR)
    impossible = sorted(rule for rule, count in banked.items() if not 1 <= count <= portfolios)

    # Assert
    assert not unknown, (
        f"the baseline banks rule breaks for rules that are not enforced Error rules of "
        f"{canonical.FILING_MODULE}: {unknown}.\n{REBANK}"
    )
    assert not impossible, (
        f"a rule cannot be broken on fewer than 1 or more than {portfolios} portfolios: "
        f"{impossible}.\n{REBANK}"
    )


def test_the_baseline_says_why_it_was_banked() -> None:
    """A re-bank carries its reason; the script's placeholder is not one."""
    note = _baseline().get("_note", "")

    assert note and note != MAPPING.UNEXPLAINED_NOTE, (
        f"{BASELINE_REL} was re-banked without saying why. Replace `_note` with the reason "
        "the numbers moved — which template, which direction, and what changed."
    )


def test_baseline_provenance_matches_the_live_matrix() -> None:
    """The banked numbers name the matrix they were measured over, and it is current.

    Every number is a union across the runs, so it means nothing apart from the
    matrix that produced it. Failing here costs a fraction of a second and reads
    as "the comparison is invalid", never as "the mapping regressed".

    Arrange: the committed baseline and the live matrix.
    Act:     read both provenances.
    Assert:  the ordered (regime, portfolio) lists agree, and are not empty.
    """
    # Arrange
    banked = _baseline().get("provenance")

    # Act
    live = MAPPING.provenance()

    # Assert
    assert live["runs"] > 0, "no Basel 3.1 run is in the register's matrix — nothing is measured"
    assert banked == live, (
        "the portfolio matrix moved since the baseline was banked, so its numbers describe "
        "a different estate. This is NOT a mapping regression, and the fix is never to "
        f"drop a portfolio — re-measure and bank the new matrix, saying why:\n{REBANK}"
    )


def test_the_baseline_is_not_weakened_against_the_committed_copy() -> None:
    """A working-tree edit may not move a number the permissive way.

    Compares the working tree with ``HEAD``, so it binds where the damage is done
    casually — a red ratchet, an edited number, and on. Once committed it passes,
    by design: a re-bank after a real, explained change is legitimate. Vacuous
    on a CI checkout, where the tree equals the commit.

    Arrange: the baseline as of HEAD.
    Act:     run the ratchet's own comparison, working tree against HEAD.
    Assert:  nothing moved the permissive way.
    """
    # Arrange
    shown = subprocess.run(
        ["git", "show", f"HEAD:{BASELINE_REL}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if shown.returncode != 0:
        pytest.skip(f"git cannot supply {BASELINE_REL} at HEAD (untracked, or no git)")
    committed = json.loads(shown.stdout)
    working = _baseline()
    if committed.get("provenance") != working.get("provenance"):
        pytest.skip("HEAD and the working tree were measured over different matrices")

    # A total introduced since HEAD cannot have been weakened: HEAD never held it.
    for total, breakdown in MAPPING.BREAKDOWNS.items():
        committed.setdefault(total, working[total])
        committed.setdefault(breakdown, working[breakdown])

    # Act — the working tree plays "measured": worse than HEAD means weakened.
    weakened = MAPPING.check_against_baseline(working, committed)

    # Assert
    assert not weakened, (
        f"{BASELINE_REL} was edited to be more permissive than the committed copy:\n  "
        + "\n  ".join(weakened)
        + f"\nNever type the numbers. Fix the mapping, or re-measure:\n{REBANK}"
    )


# =============================================================================
# The comparison goes red when it should
# =============================================================================


@pytest.fixture
def banked() -> dict[str, Any]:
    """A small baseline of the real shape, independent of the committed one."""
    return {
        "placed_cells": 100,
        "unplaced_figures": 10,
        BREAKDOWN_KEY: {"c07_00|cell_not_reportable": 6, "c08_01|row_not_in_taxonomy": 4},
        "structure_findings": 3,
        STRUCTURE_KEY: {"STR007|OF02.00.01.01": 2, "STR006|OF08.03.01.01": 1},
        "error_rule_breaks": 5,
        RULES_KEY: {"boe_b0713": 3, "boe_b0904": 2},
        "provenance": {"runs": 1, "portfolios": [{"regime": "b31", "portfolio": "rich"}]},
    }


def test_an_unchanged_measurement_passes(banked: dict[str, Any]) -> None:
    assert MAPPING.check_against_baseline(copy.deepcopy(banked), banked) == []


def test_an_improvement_passes(banked: dict[str, Any]) -> None:
    # Arrange — more placed, fewer unplaced, one breakdown cell gone entirely.
    measured = copy.deepcopy(banked)
    measured["placed_cells"] = 104
    measured["unplaced_figures"] = 6
    measured[BREAKDOWN_KEY] = {"c07_00|cell_not_reportable": 6}

    # Act / Assert
    assert MAPPING.check_against_baseline(measured, banked) == []


def test_fewer_placed_cells_fails(banked: dict[str, Any]) -> None:
    measured = copy.deepcopy(banked) | {"placed_cells": 99}

    problems = MAPPING.check_against_baseline(measured, banked)

    assert len(problems) == 1 and "placed_cells fell: 100 -> 99" in problems[0]


def test_more_unplaced_figures_fails(banked: dict[str, Any]) -> None:
    # Arrange
    measured = copy.deepcopy(banked)
    measured["unplaced_figures"] = 11
    measured[BREAKDOWN_KEY]["c07_00|cell_not_reportable"] = 7

    # Act
    problems = MAPPING.check_against_baseline(measured, banked)

    # Assert — the total, and the cell of the breakdown that moved.
    assert any("unplaced_figures rose: 10 -> 11" in problem for problem in problems)
    assert any("c07_00 (cell_not_reportable) rose: 6 -> 7" in problem for problem in problems)


def test_a_fix_in_one_template_cannot_hide_a_regression_in_another(
    banked: dict[str, Any],
) -> None:
    """The total FALLS, and the gate still fails: the breakdown is ratcheted per cell."""
    # Arrange — c07_00 improves by four, c08_01 worsens by two: net minus two.
    measured = copy.deepcopy(banked)
    measured["unplaced_figures"] = 8
    measured[BREAKDOWN_KEY] = {"c07_00|cell_not_reportable": 2, "c08_01|row_not_in_taxonomy": 6}

    # Act
    problems = MAPPING.check_against_baseline(measured, banked)

    # Assert
    assert len(problems) == 1 and "c08_01 (row_not_in_taxonomy) rose: 4 -> 6" in problems[0]


def test_a_new_kind_of_unplaced_figure_fails_even_when_the_total_holds(
    banked: dict[str, Any],
) -> None:
    # Arrange — a (template, reason) the baseline has never seen.
    measured = copy.deepcopy(banked)
    measured[BREAKDOWN_KEY] = {
        "c07_00|cell_not_reportable": 5,
        "c08_01|row_not_in_taxonomy": 4,
        "c09_01|open_key_not_a_member": 1,
    }

    # Act
    problems = MAPPING.check_against_baseline(measured, banked)

    # Assert
    assert len(problems) == 1 and "c09_01 (open_key_not_a_member) rose: 0 -> 1" in problems[0]


def test_more_structure_findings_fail_in_total_and_per_table(banked: dict[str, Any]) -> None:
    # Arrange — one more inconsistent data point in OF 02.00.
    measured = copy.deepcopy(banked)
    measured["structure_findings"] = 4
    measured[STRUCTURE_KEY]["STR007|OF02.00.01.01"] = 3

    # Act
    problems = MAPPING.check_against_baseline(measured, banked)

    # Assert
    assert any("structure_findings rose: 3 -> 4" in problem for problem in problems)
    assert any("STR007 in OF02.00.01.01 rose: 2 -> 3" in problem for problem in problems)


def test_a_new_structure_finding_fails_even_when_another_was_fixed(
    banked: dict[str, Any],
) -> None:
    # Arrange — the STR006 is fixed, and a table that was clean now has a finding.
    measured = copy.deepcopy(banked)
    measured[STRUCTURE_KEY] = {"STR007|OF02.00.01.01": 2, "STR002|OF07.00.01.01": 1}

    # Act
    problems = MAPPING.check_against_baseline(measured, banked)

    # Assert — the total is unchanged at 3; the new cell is what fails.
    assert len(problems) == 1 and "STR002 in OF07.00.01.01 rose: 0 -> 1" in problems[0]


def test_a_rule_broken_on_more_portfolios_fails_in_total_and_for_the_rule(
    banked: dict[str, Any],
) -> None:
    # Arrange — one more portfolio breaks the OF 07.00 total-sheet rule.
    measured = copy.deepcopy(banked)
    measured["error_rule_breaks"] = 6
    measured[RULES_KEY]["boe_b0713"] = 4

    # Act
    problems = MAPPING.check_against_baseline(measured, banked)

    # Assert
    assert any("error_rule_breaks rose: 5 -> 6" in problem for problem in problems)
    assert any("boe_b0713 is broken on more portfolios: 3 -> 4" in problem for problem in problems)


def test_a_newly_broken_rule_fails_even_when_another_was_fixed(banked: dict[str, Any]) -> None:
    """A fix must not be able to pay for a new break (LESSONS C4: read every rule that moved)."""
    # Arrange — boe_b0904 is fixed on both portfolios; a rule that held now breaks on two.
    measured = copy.deepcopy(banked)
    measured[RULES_KEY] = {"boe_b0713": 3, "boe_b0471": 2}

    # Act
    problems = MAPPING.check_against_baseline(measured, banked)

    # Assert — the total is unchanged at 5; the new rule is what fails.
    assert len(problems) == 1
    assert "boe_b0471 is broken on more portfolios: 0 -> 2" in problems[0]


def test_a_fixed_rule_passes_and_leaves_the_baseline_to_be_re_banked(
    banked: dict[str, Any],
) -> None:
    # Arrange
    measured = copy.deepcopy(banked)
    measured["error_rule_breaks"] = 3
    measured[RULES_KEY] = {"boe_b0713": 3}

    # Act / Assert
    assert MAPPING.check_against_baseline(measured, banked) == []


def test_a_baseline_that_does_not_bank_a_total_is_a_failure_not_a_crash(
    banked: dict[str, Any],
) -> None:
    """A metric added to the script and not re-banked must read as red, in words."""
    # Arrange
    measured = copy.deepcopy(banked)
    del banked["structure_findings"]

    # Act
    problems = MAPPING.check_against_baseline(measured, banked)

    # Assert
    assert len(problems) == 1 and "does not bank structure_findings" in problems[0]


def test_a_moved_matrix_is_reported_as_incomparable_not_as_a_regression(
    banked: dict[str, Any],
) -> None:
    """One message, about the matrix — never a delta computed across two estates."""
    # Arrange — a different matrix AND numbers that would otherwise read as worse.
    measured = copy.deepcopy(banked) | {"placed_cells": 1}
    measured["provenance"] = {"runs": 2, "portfolios": [*banked["provenance"]["portfolios"], {}]}

    # Act
    problems = MAPPING.check_against_baseline(measured, banked)

    # Assert
    assert len(problems) == 1
    assert "not comparable" in problems[0] and "do not drop a portfolio" in problems[0]


# =============================================================================
# Something runs it
# =============================================================================


def test_the_filing_mapping_ratchet_is_invoked_by_ci() -> None:
    """CI runs ``--check`` in a step that is enabled and whose failure is fatal.

    A ratchet nothing runs is prose with extra steps. Nothing else runs this
    one: it is not in ``arch_check``, and the test below that shells out to it
    is ``slow``-marked, so both the dev loop and CI's ``test`` job deselect it.
    """
    problems = gate_wiring_problems(CI_JOB, _INVOKES_CHECK)

    assert not problems, (
        f"the filing-mapping ratchet is not wired into {WORKFLOW_REL}:\n  " + "\n  ".join(problems)
    )


@pytest.mark.slow
def test_filing_mapping_check_passes_against_the_committed_baseline() -> None:
    """The real measurement, against the committed baseline (13 pipeline runs)."""
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, (
        f"{SCRIPT_REL} --check failed:\n{completed.stdout[-4000:]}\n{completed.stderr[-2000:]}"
    )
