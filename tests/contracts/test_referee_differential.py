"""
The referee differential — the gate that asks Arelle about what we would file.

Pipeline position:
    (no pipeline stage — contract tests on ``scripts/referee_differential.py``,
    its banked baseline and its CI workflow)

The gate itself needs Arelle and the Bank of England's taxonomy package and
takes tens of minutes, so it runs in its own workflow and not here. What is
pinned here is everything about it that does NOT need either: that the banked
state is the state the proposal's Phase 3 gate asks for (no Arelle error, no
disagreement), that the comparison against the baseline is two-way and cannot
pass on an empty or unfinished run, that the banked golden returns are still
portfolios of the live matrix, and that the workflow actually runs the gate.

References:
- scripts/referee_differential.py, scripts/referee_differential_baseline.json
- .github/workflows/referee-differential.yml
- packages/rwa-filer/src/rwa_filer/referee
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import pytest
from scripts import referee_differential as gate
from tests.contracts._ci_workflow import REPO_ROOT, run_commands, without_comments

WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "referee-differential.yml"
INVOCATION = re.compile(r"scripts/referee_differential\.py\b.*--check\b")


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    return json.loads(gate.BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def measured(baseline: dict[str, Any]) -> dict[str, Any]:
    """A measurement identical to what is banked, for each test to move."""
    return copy.deepcopy(
        {key: baseline[key] for key in ("measured_with", "portfolios", "provenance")}
    )


def first(measured: dict[str, Any]) -> dict[str, Any]:
    return next(iter(measured["portfolios"].values()))


# ---------------------------------------------------------------------------
# The banked state
# ---------------------------------------------------------------------------


def test_the_baseline_banks_every_register_for_every_golden_return(
    baseline: dict[str, Any],
) -> None:
    # Assert
    assert baseline["portfolios"], "no golden return is banked: the gate would gate nothing"
    assert sorted(baseline["portfolios"]) == baseline["provenance"]["golden"]
    for name, entry in baseline["portfolios"].items():
        for key in (*gate.REGISTERS, *gate.RATCHET_MIN):
            assert key in entry, f"{name} does not bank {key}"
        assert entry["referee_complete"] is True, f"{name} was banked from an unfinished run"
        assert entry["rules_compared"] > 0, f"{name} was banked with nothing compared"
        assert entry["facts"] > 0


def test_arelle_accepts_every_golden_return_and_agrees_with_the_engine(
    baseline: dict[str, Any],
) -> None:
    """The Phase 3 gate: zero Arelle errors, and an empty disagreement register."""
    for name, entry in baseline["portfolios"].items():
        assert entry["arelle_errors"] == [], f"{name}: Arelle rejects the banked return"
        assert entry["disagreements"] == [], f"{name}: a disagreement is banked as accepted"


def test_the_baseline_says_why_it_was_banked(baseline: dict[str, Any]) -> None:
    assert baseline["_comment"] == gate.BASELINE_COMMENT
    assert baseline["_note"] and baseline["_note"] != gate.UNEXPLAINED_NOTE


def test_the_banked_portfolios_are_the_live_matrix(baseline: dict[str, Any]) -> None:
    """Golden or not, each banked name is a Basel 3.1 run of ``RUNS`` — and none is missing."""
    # Act
    live = sorted(gate.portfolio_key(run) for run in gate.filed_runs())
    banked = sorted([*baseline["provenance"]["golden"], *baseline["provenance"]["not_golden"]])

    # Assert
    assert banked == live


# ---------------------------------------------------------------------------
# The comparison against the baseline
# ---------------------------------------------------------------------------


def test_an_unchanged_measurement_passes(
    measured: dict[str, Any], baseline: dict[str, Any]
) -> None:
    assert gate.run_problems(measured) == []
    assert gate.check_against_baseline(measured, baseline) == []


@pytest.mark.parametrize("register", gate.REGISTERS)
def test_a_new_entry_in_a_register_fails(
    measured: dict[str, Any], baseline: dict[str, Any], register: str
) -> None:
    # Arrange
    first(measured)[register].append("boe_b9999: native PASS [1, 0], Arelle FAIL [0, 1]")

    # Act
    problems = gate.check_against_baseline(measured, baseline)

    # Assert
    assert len(problems) == 1
    assert f"new {register}" in problems[0] and "boe_b9999" in problems[0]


@pytest.mark.parametrize("register", gate.REGISTERS)
def test_an_entry_that_went_away_unrecorded_fails(
    measured: dict[str, Any], baseline: dict[str, Any], register: str
) -> None:
    """Two-way: a banked exception nobody removes is a licence nobody reads."""
    # Arrange — the baseline still names a rule the run no longer finds.
    stale = copy.deepcopy(baseline)
    first(stale)[register].append("boe_b9999: native PASS [1, 0], Arelle FAIL [0, 1]")

    # Act
    problems = gate.check_against_baseline(measured, stale)

    # Assert
    assert len(problems) == 1
    assert "no longer found: boe_b9999" in problems[0]


def test_fewer_rules_compared_fails(measured: dict[str, Any], baseline: dict[str, Any]) -> None:
    # Arrange
    first(measured)["rules_compared"] -= 1

    # Act
    problems = gate.check_against_baseline(measured, baseline)

    # Assert
    assert len(problems) == 1 and "rules_compared fell" in problems[0]


def test_more_rules_compared_passes(measured: dict[str, Any], baseline: dict[str, Any]) -> None:
    first(measured)["rules_compared"] += 5
    assert gate.check_against_baseline(measured, baseline) == []


def test_a_portfolio_that_left_the_gate_is_reported(
    measured: dict[str, Any], baseline: dict[str, Any]
) -> None:
    """It gained a structure finding: nothing was refereed, and that must be seen."""
    # Arrange
    name = measured["provenance"]["golden"].pop()
    del measured["portfolios"][name]
    measured["provenance"]["not_golden"][name] = 1

    # Act
    problems = gate.check_against_baseline(measured, baseline)

    # Assert
    assert len(problems) == 1 and "golden returns changed" in problems[0]


@pytest.mark.parametrize(
    ("key", "value"), [("arelle", "9.9.9"), ("taxonomy_package_sha256", "0" * 64)]
)
def test_a_different_processor_or_publication_is_a_new_measurement(
    measured: dict[str, Any], baseline: dict[str, Any], key: str, value: str
) -> None:
    # Arrange
    measured["measured_with"][key] = value

    # Act
    problems = gate.check_against_baseline(measured, baseline)

    # Assert
    assert len(problems) == 1 and "new measurement" in problems[0]


def test_a_restricted_run_is_held_only_for_what_it_ran(
    measured: dict[str, Any], baseline: dict[str, Any]
) -> None:
    # Arrange — one portfolio only, as ``--portfolio`` gives.
    name = next(iter(measured["portfolios"]))
    only = {
        "measured_with": measured["measured_with"],
        "portfolios": {name: measured["portfolios"][name]},
        "provenance": {"golden": [name], "not_golden": {}},
    }
    broken = copy.deepcopy(only)
    broken["portfolios"][name]["disagreements"].append("boe_b9999: native PASS, Arelle FAIL")

    # Act / Assert
    assert gate.check_against_baseline(only, baseline, restricted=True) == []
    assert len(gate.check_against_baseline(broken, baseline, restricted=True)) == 1


def test_a_baseline_that_does_not_bank_a_register_is_a_failure_not_a_crash(
    measured: dict[str, Any], baseline: dict[str, Any]
) -> None:
    # Arrange
    thin = copy.deepcopy(baseline)
    del first(thin)["disagreements"]
    del first(thin)["rules_compared"]

    # Act
    problems = gate.check_against_baseline(measured, thin)

    # Assert
    assert sorted(problem.split(": ", 1)[1] for problem in problems) == [
        "the baseline does not bank disagreements",
        "the baseline does not bank rules_compared",
    ]


# ---------------------------------------------------------------------------
# The run itself
# ---------------------------------------------------------------------------


def test_an_unfinished_arelle_run_fails_whatever_the_baseline_says(
    measured: dict[str, Any],
) -> None:
    # Arrange
    first(measured)["referee_complete"] = False
    first(measured)["lost"] = ["boe_b0001", "boe_b0002"]

    # Act
    problems = gate.run_problems(measured)

    # Assert
    assert len(problems) == 1 and "did not finish (2 rule(s) lost)" in problems[0]


def test_a_run_that_compared_nothing_fails(measured: dict[str, Any]) -> None:
    # Arrange
    first(measured)["rules_compared"] = 0

    # Act / Assert
    assert any("no rule was compared" in problem for problem in gate.run_problems(measured))


def test_a_run_with_no_golden_return_fails() -> None:
    empty = {"portfolios": {}, "provenance": {"golden": [], "not_golden": {"b31/rich": 1}}}
    assert gate.run_problems(empty) == ["no golden return was filed: nothing was refereed"]


# ---------------------------------------------------------------------------
# The workflow
# ---------------------------------------------------------------------------


def test_the_gate_is_run_by_its_workflow_and_can_fail_it() -> None:
    """Read structurally: a commented-out command, or one that cannot fail, does not count."""
    # Arrange
    assert WORKFLOW_PATH.exists(), f"no workflow at {WORKFLOW_PATH}"
    live = without_comments(WORKFLOW_PATH.read_text(encoding="utf-8"))

    # Act
    commands = run_commands(live)

    # Assert
    assert any(INVOCATION.search(command) for command in commands), commands
    assert "continue-on-error" not in live
    for trigger in ("pull_request:", "schedule:", "workflow_dispatch:"):
        assert trigger in live, f"the workflow lost its {trigger} trigger"


def test_the_workflow_pins_the_publication_and_the_processor_the_baseline_was_measured_with(
    baseline: dict[str, Any],
) -> None:
    """A new taxonomy package or a new Arelle is a re-measurement, not an edit."""
    # Act
    live = without_comments(WORKFLOW_PATH.read_text(encoding="utf-8"))

    # Assert
    assert f"TAXONOMY_SHA256: {baseline['measured_with']['taxonomy_package_sha256']}" in live
    assert f"ARELLE_VERSION: {baseline['measured_with']['arelle']}" in live
