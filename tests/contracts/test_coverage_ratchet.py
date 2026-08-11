"""
Reporting-coverage ratchet gates (P5.21 / independent validation plan C5).

Pipeline position:
    (no pipeline stage — gates the estate-wide measurement of the pipeline's
    reporting output)
    scripts/coverage_report.py --check -> scripts/coverage_baseline.json

``scripts/coverage_report.py`` measures how much of the published rulebook the
gates can actually SEE, over the same portfolio x regime matrix the supervisory
register runs (``RUNS``, imported and never re-declared). It emits six
ratchetable numbers: ``union_binding_rules_crr`` / ``union_binding_rules_b31``,
``cells_live`` and ``template_cell_liveness_bp`` may not FALL, ``dead_cells`` and
``never_evaluated_rules`` may not RISE.

``cells_live`` is the one that makes destroying cell coverage fail, and it is worth
knowing why before reading a green. ``template_cell_liveness_bp`` is a RATIO whose
denominator moves with its numerator, and ``dead_cells`` is ``declared - live``, so
both IMPROVE when declared cells are dropped faster than live ones. Measured over all
16 leave-one-out deletions of the current matrix: on **4 of 16 both cell metrics
moved the passing way while live cells were destroyed** — worst is ``b31/rich``,
which loses 689 live cells while liveness rises 1285 -> 1374 bp and dead cells fall
55553 -> 47123 — on 6 more exactly one of the two passed, and only 4 of 16 were
caught by both. ``cells_live`` is an absolute count, so a shrinking denominator
cannot flatter it: it fell on all 14 deletions that cost live cells and never rose on
a loss. The two it did not move for, ``crr/art199`` and ``b31/art199``, cost zero
live cells — neither contributes a uniquely-live cell, so there was nothing to catch.

``--check`` was implemented and invoked by NOTHING — absent from
``.github/workflows/ci.yml``, from ``scripts/arch_check.py``, and from every
test. A ratchet nothing runs is prose with extra steps: a change could kill a
live cell, un-bind a published rule, or open a fresh blind spot with every gate
green, because the supervisory register FAILS OPEN and an unreachable rule is
indistinguishable from a clean estate (``.claude/LESSONS.md`` B5, C3).

Cheap-vs-expensive split, and why it is this way
------------------------------------------------
The real measurement costs 24 full pipeline runs (16 portfolio x regime, plus a
prior-period run for each of the 8 with IRB permission) plus two reporting
generators per run — **measured 117-169s across five runs on the reference dev box
with fixtures already on disk** (117.1, 118.1, 124.7, 136.2, 169.0), and slower on a
cold first run. An earlier "~46s warm" figure here predated the matrix growing to 16
and understated the cost by more than half. A test that adds two minutes to the dev
loop is a test somebody switches off, and a switched-off ratchet is the very failure
mode above. So the work is split, deliberately unevenly:

- Five **always-on structural tests** that run no pipeline at all (~0.5s, all of
  it importing the script). They cannot see a coverage regression, but they catch
  every way the ratchet can be silently disarmed *without* one: a baseline that
  does not parse, a metric present in the baseline with no direction declared, a
  ratcheted name that ``summarise()`` no longer emits (which would otherwise
  surface as a ``KeyError`` two minutes into a CI job), a baseline whose numbers
  were measured over a matrix that no longer exists, a portfolio that never
  entered the gated matrix at all, a baseline weakened in the working tree, and
  the CI job itself being deleted.
- One ``slow`` test that shells out to the real ``--check``. Excluded from the
  dev loop by the marker, so it binds only where something opts in.

The expensive half's real home is the ``coverage-ratchet`` CI job, which invokes
the script directly so the exit code is the gate's own. The ``slow`` test exists
so the measurement is reachable from pytest for a local operator
(``-m slow``) — not so that anybody's dev loop pays two minutes. This mirrors
``tests/contracts/test_template_cell_coverage.py``, whose fast/slow split was
built for the same reason over the neighbouring per-COLUMN measure.

``coverage_report.py``'s two ``LESSONS`` graduation checks
(``check_portfolios_registered`` / ``check_builders_registered``) ARE asserted
here, and they also gate ``--check``'s exit code. Neither was true before: the
portfolio check reported a permanent FALSE POSITIVE against
``reporting_funded_protection_portfolio.py``, which is withheld from ``RUNS``
deliberately and at length (see the DELIBERATELY NOT REGISTERED comment in
``tests/acceptance/reporting/test_supervisory_validations.py``), because the script
had no allowlist to record the deliberate omission. It now has
``EXCLUDED_PORTFOLIOS``, keyed exactly as the check reports a finding and mirroring
``check_template_cell_coverage.py``'s field of the same name; a STALE entry there
fails the check rather than being ignored, because an allowlist that outlives its
reason is a hole in the gate that reads as a pass. The allowlist landed FIRST and
the exit-code binding second, deliberately in that order — binding a check with a
known false red only teaches the next reader to ignore a red.

Baseline provenance, and why the list is ordered
-----------------------------------------------
``dead_cells`` and ``template_cell_liveness_bp`` are **not comparable across a
change to** ``RUNS``. Registering a portfolio DECLARES its templates' cells, and
most of them no other portfolio fills — so the two cell metrics get WORSE on
precisely the change ``.claude/LESSONS.md`` B5 demands.

That is measured, not hypothetical. ``RUNS`` is sixteen (``re-split`` x2 and
``art199`` x2 arrived with the real-estate carrier batch) and the old baseline was a
TWELVE-run measurement — but of an older tree, and its figures no longer reproduce
at either matrix size: re-measuring the 12-run matrix as it stood at the baseline
commit gives ``253 / 279 / 1300 / 52803`` against the banked
``251 / 277 / 1298 / 52817``. So the banked numbers cannot be reproduced and must not
be used as a target. ``--check`` reported ``dead_cells 52817 -> 55553`` and
``liveness 1298 -> 1285`` as REGRESSIONS on a tree that had in fact gained coverage.

What settles it is holding the MATRIX constant, not the direction the metrics moved:
"the cell metrics fell while the rule metrics rose" is equally consistent with a real
cell loss plus an unrelated rule gain, because the two families are independent. The
decisive figures are absolute. Live cells rose ``7891 -> 8193`` while declared rose
``60694 -> 63746``; coverage cannot have fallen. Every one of the 2873 newly-dead
cells is on the C 07.00 / OF 07.00 ``residential_mortgage`` sheet that no 12-run
portfolio emitted at all, and 123 previously-dead cells went live. A live cell also
*cannot* go dead across a matrix growth, because liveness is a union accumulator over
runs and runs 1-12 are identical in both measurements.

Nothing in the baseline recorded which matrix produced its numbers, so the staleness
stayed invisible until a gate finally ran the ratchet.

The baseline therefore carries ``provenance``: ``runs`` plus the ORDERED
``[{"regime": ..., "portfolio": ...}]`` from ``RUNS``.
``coverage_report.py::_check_baseline`` compares it BEFORE computing any delta and
refuses across a mismatch; ``test_baseline_provenance_matches_the_live_runs_matrix``
below asserts the same in ~0.3s, so a matrix change fails in the dev loop rather
than two minutes into a CI job. ORDERED and not merely counted, because exchanging one
portfolio for another leaves ``len(RUNS)`` unchanged. Same shape as
``scripts/check_template_cell_coverage.py``, which solved this first and pins both
halves the same way.

One consequence is worth stating because getting it wrong is worse than not having
the field: a provenance mismatch must NOT be reported as a coverage regression, and
its message must not tell anybody to put the old numbers back. On a grown matrix
the cell metrics legitimately worsen, so the cheapest way to clear that red is to
delete the portfolio that caused it — destroying real coverage to satisfy a stale
number, which is B5 exactly inverted. ``coverage_report.py::_MATRIX_MOVED`` carries
wording that says the comparison is INVALID and names the only correct action;
``_check_baseline``'s "coverage went backwards" text is reserved for a real
regression, which by then is known to have been measured over the same matrix.

References:
- scripts/coverage_report.py — the measurement and the four-way ratchet
- scripts/coverage_baseline.json — the banked values (never weaken to clear a red)
- tests/contracts/test_template_cell_coverage.py — the same shape, per COLUMN
- .claude/LESSONS.md B5 — the register fails open; a dead cell reads as clean
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "coverage_report.py"
BASELINE_PATH = REPO_ROOT / "scripts" / "coverage_baseline.json"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: Repo-relative, forward-slashed — the form ``git show <ref>:<path>`` wants and
#: the form the workflow file spells. Held as strings and used verbatim in the
#: failure messages: deriving them back with ``Path.relative_to`` raises when a
#: test rebinds a path constant to a scratch copy, which turns a clean assertion
#: failure into an error.
BASELINE_REL = "scripts/coverage_baseline.json"
SCRIPT_REL = "scripts/coverage_report.py"
WORKFLOW_REL = ".github/workflows/ci.yml"

REBANK = f"  uv run python {SCRIPT_REL} --update-baseline"

#: The workflow job that owns the expensive measurement.
CI_JOB = "coverage-ratchet"

#: A folded ``run:`` command that invokes the gate. Applied to a command already
#: normalised to one line by ``_run_commands``, so any amount of whitespace, a
#: block scalar and a shell continuation all reduce to the same subject — the three
#: working reformats that reddened the old substring form.
_INVOKES_CHECK = re.compile(re.escape(SCRIPT_REL) + r"[^\n]*?--check")

#: A job-level or step-level ``if:``. Anchored per line under ``re.MULTILINE`` so it
#: cannot match the word inside a command or a comment (comments are stripped before
#: this is applied). ``if: false`` is a one-word disable, so its absence is asserted.
_JOB_CONDITIONAL = re.compile(r"^[ \t]*(?:-[ \t]+)?if:", re.MULTILINE)

#: Non-metric keys the baseline is allowed to carry alongside its metrics. Anything
#: else in the file must be a metric with a declared direction, so a number cannot
#: be parked in the baseline where no ratchet reads it.
#:
#: ``provenance`` earns its place by being asserted in its own right below, against
#: the live ``RUNS`` — it is not free text that nothing reads. ``_comment`` is the
#: standing contract and ``_note`` the reason for the current bank, both prose.
NON_METRIC_KEYS = frozenset({"_comment", "_note", "provenance"})


def _load_coverage_module() -> Any:
    """Import the coverage script as a module.

    Imported rather than re-derived so the metric names and their ratchet
    DIRECTIONS come from the one place that owns them. A hand-written copy here
    would drift exactly when this test needs to fire, which is
    ``.claude/LESSONS.md`` B3: a test that shares production's assumption
    because both were written from the same sentence validates nothing.
    """
    spec = importlib.util.spec_from_file_location("_coverage_report", SCRIPT_PATH)
    assert spec is not None, f"no import spec for {SCRIPT_PATH}"
    assert spec.loader is not None, f"import spec for {SCRIPT_PATH} carries no loader"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


COVERAGE = _load_coverage_module()


def test_coverage_baseline_is_well_formed_and_every_metric_declares_a_direction() -> None:
    """The banked baseline parses, and every number in it is actually ratcheted.

    A metric in the baseline that appears in neither ``_RATCHET_MIN`` nor
    ``_RATCHET_MAX`` is guarded by nothing, and a name in those tuples that
    ``summarise()`` no longer emits turns the gate into a ``KeyError`` two
    minutes into a CI job. Both are checked here, for free.

    This earned its place within an hour of landing. ``cells_live`` was added to
    ``_RATCHET_MIN`` in the same change that introduced it, and the baseline was
    not re-banked in the same breath — so ``--check`` would have raised
    ``KeyError: 'cells_live'`` about 150s into the new CI job, on every run, with
    no coverage defect anywhere. This test failed in 0.30s instead, naming the
    metric and the fix::

        directed but unbanked (--check would KeyError): ['cells_live']

    That is the whole argument for the cheap half of this file: the expensive gate
    cannot report its own disarming, because it dies before it computes anything.

    Arrange: the committed baseline and the script's direction declarations.
    Act:     read the baseline's metric keys and the metric names the script
             emits, using an empty observation so no pipeline runs.
    Assert:  the key sets agree, no metric is undirected or doubly directed, and
             every value is a plain non-negative integer.
    """
    # Arrange
    assert BASELINE_PATH.exists(), (
        f"No coverage ratchet baseline at {BASELINE_PATH}. Capture it:\n{REBANK}"
    )
    baseline: dict[str, Any] = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    minimums = set(COVERAGE._RATCHET_MIN)
    maximums = set(COVERAGE._RATCHET_MAX)

    # Act — summarising an EMPTY observation costs nothing and still exercises the
    # real metric-name construction, so a rename cannot slip past.
    emitted = set(COVERAGE.summarise(COVERAGE.Observation())["metrics"])
    banked = set(baseline) - NON_METRIC_KEYS

    # Assert — directions are declared, exactly once each
    assert not minimums & maximums, (
        "a metric is declared as both may-not-decrease and may-not-increase, so its "
        f"ratchet is unsatisfiable: {sorted(minimums & maximums)}"
    )
    assert banked == minimums | maximums, (
        "the baseline's metrics and the script's ratchet declarations disagree.\n"
        f"  banked but undirected (guarded by nothing): {sorted(banked - (minimums | maximums))}\n"
        f"  directed but unbanked (--check would KeyError): "
        f"{sorted((minimums | maximums) - banked)}\n{REBANK}"
    )

    # Assert — every ratcheted name is a metric the script really produces
    assert (minimums | maximums) <= emitted, (
        "a ratcheted metric name is not emitted by summarise(), so --check cannot "
        f"read it: {sorted((minimums | maximums) - emitted)}. Fix the name in "
        f"{SCRIPT_REL}'s _RATCHET_MIN / _RATCHET_MAX."
    )

    # Assert — the values are usable as a ratchet
    non_integers = {
        name: value
        for name, value in baseline.items()
        if name not in NON_METRIC_KEYS and (isinstance(value, bool) or not isinstance(value, int))
    }
    assert not non_integers, (
        f"baseline metrics must be plain integers; these are not: {non_integers}.\n{REBANK}"
    )
    negatives = {
        name: value
        for name, value in baseline.items()
        if name not in NON_METRIC_KEYS and int(value) < 0
    }
    assert not negatives, f"baseline metrics cannot be negative: {negatives}.\n{REBANK}"


def test_baseline_provenance_matches_the_live_runs_matrix() -> None:
    """The banked numbers name the matrix they were measured over, and it is current.

    Every metric here is a UNION across ``RUNS``, so a banked number means nothing
    apart from the matrix that produced it. This is the fast half of the check
    ``coverage_report.py::_check_baseline`` performs before it computes any delta: a
    matrix change fails here in ~0.3s instead of two minutes into a CI job, and it fails as
    "the comparison is invalid", never as "coverage regressed".

    The ORDERED list is pinned, not merely the run count, because exchanging one
    portfolio for another leaves ``len(RUNS)`` unchanged — a count alone cannot see
    a swap. Both halves come from ``COVERAGE.provenance()`` rather than being
    re-derived here, so the test and the gate cannot describe the matrix differently
    (``.claude/LESSONS.md`` B3).

    Arrange: the committed baseline and the live matrix.
    Act:     read the banked provenance and the live one.
    Assert:  the run count and the ordered (regime, portfolio) list agree.
    """
    # Arrange
    baseline: dict[str, Any] = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    live = COVERAGE.provenance()

    # Act
    banked = baseline.get("provenance")

    # Assert — the field is there at all. A baseline without it cannot be compared
    # with anything: the matrix behind its numbers is simply unknown.
    assert isinstance(banked, dict), (
        f"{BASELINE_REL} records no provenance, so nothing says which portfolio x regime "
        "matrix produced its numbers — which is how a grown RUNS arrives as a mystery "
        f"regression instead of as a re-bank.\n{REBANK}"
    )

    # Assert — the matrix has not grown or shrunk under the banked numbers
    assert banked.get("runs") == live["runs"], (
        f"the baseline was measured over {banked.get('runs')} runs but RUNS is now "
        f"{live['runs']}. These metrics are a union over the matrix, so the two are NOT "
        "comparable and this is not a coverage regression: registering a portfolio "
        "declares its templates' cells, most of which no other portfolio fills, so "
        "dead_cells rises and liveness falls on exactly the change .claude/LESSONS.md B5 "
        "asks for. Do not drop a portfolio to make the banked numbers fit — re-measure "
        f"and bank the new matrix:\n{REBANK}"
    )

    # Assert — and no portfolio was swapped for another behind an equal count
    assert [
        (entry.get("regime"), entry.get("portfolio")) for entry in banked.get("portfolios", ())
    ] == [(entry["regime"], entry["portfolio"]) for entry in live["portfolios"]], (
        "the portfolio x regime matrix moved since the baseline was banked, without "
        "changing the run count — one portfolio was exchanged for another, or the order "
        f"changed. Either way the banked numbers describe a different estate:\n{REBANK}"
    )


def test_the_lessons_graduation_checks_pass() -> None:
    """Every reporting portfolio is in ``RUNS`` or allowlisted; every builder registered.

    These are ``coverage_report.py``'s two ``LESSONS`` graduations, and they gate
    ``--check``'s exit code. Asserted here too because they are pure AST/file scans
    costing ~0.1s: there is no reason to make an operator wait for a two-minute CI job to
    learn that a portfolio never entered the gate.

    They were deliberately left unasserted until ``EXCLUDED_PORTFOLIOS`` existed.
    The portfolio check used to report a permanent FALSE POSITIVE against
    ``reporting_funded_protection_portfolio.py``, which is withheld from ``RUNS``
    deliberately and at length, and asserting a known false red would only have
    taught the next reader to ignore it.

    Arrange: nothing — both checks read the tree.
    Act:     run them.
    Assert:  neither reports an unregistered entry or a stale allowlist entry.
    """
    # Arrange / Act
    portfolios = COVERAGE.check_portfolios_registered()
    builders = COVERAGE.check_builders_registered()

    # Assert — B5: a portfolio outside RUNS makes its rules NOT_EVALUATED, which
    # reads exactly like a clean estate.
    assert portfolios["unregistered"] == [], (
        "reporting portfolio fixture(s) build a bundle that no entry in RUNS uses:\n  "
        + "\n  ".join(portfolios["unregistered"])
        + "\nEvery rule over the columns they would have populated is NOT_EVALUATED, which "
        "is indistinguishable from a clean estate (.claude/LESSONS.md B5). Register them in "
        "tests/acceptance/reporting/test_supervisory_validations.py::RUNS, or — if the "
        "omission is deliberate — add a reasoned entry to "
        f"{SCRIPT_REL}::EXCLUDED_PORTFOLIOS."
    )

    # Assert — an allowlist entry that outlives its reason is a hole reading as a pass
    assert portfolios["stale_allowlist"] == [], (
        "EXCLUDED_PORTFOLIOS entr(ies) no longer describe an unregistered portfolio — the "
        "builder has since been registered in RUNS, or renamed, or deleted:\n  "
        + "\n  ".join(portfolios["stale_allowlist"])
        + f"\nDelete them from {SCRIPT_REL}: an allowlist entry that outlives its reason "
        "silently excuses the next portfolio that matches it."
    )

    # Assert — an unregistered parquet builder works locally, fails on a fresh checkout
    assert builders["unregistered"] == [], (
        "fixture module(s) write a parquet but are not called from "
        "tests/fixtures/generate_all.py:\n  "
        + "\n  ".join(entry["module"] for entry in builders["unregistered"])
        + "\nThe parquet is already on disk locally, so this passes here and fails on a "
        f"fresh checkout. Register them, or allowlist them in "
        f"{SCRIPT_REL}::_REGISTRATION_ALLOWLIST with a reason."
    )


def test_the_coverage_ratchet_is_invoked_by_ci() -> None:
    """CI runs ``--check``, in a step that is ENABLED and whose failure is fatal.

    The ratchet was fully implemented and called by nothing for its whole life.
    Asserting the invocation exists is what stops that state returning quietly:
    delete the job and this test goes red, rather than the estate going blind.

    Why this is not a substring search
    ----------------------------------
    It used to be ``f"{SCRIPT_REL} --check" in workflow``, and a skeptic defeated
    that FIVE ways, each leaving the test green while the gate was dead: commenting
    the ``run:`` line out, ``if: false`` on the job, ``continue-on-error: true`` on
    the step, deleting the step but leaving the command in a comment, and removing
    the workflow's ``on:`` triggers. It also went red on three *working* reformats
    (a ``|`` block scalar, a ``\\`` continuation, two spaces before the flag), which
    is the same brittleness pointing the other way.

    The false-green half is what made this urgent rather than tidy: this job was RED
    on arrival, and every one of those five disarms is a plausible first reaction to
    a red CI. A guard whose whole purpose is "the ratchet is still wired" has to
    survive the exact move somebody makes to unwire it.

    So the workflow is read structurally but WITHOUT a YAML parser — ``pyyaml``
    imports in this venv only as a transitive dependency and is absent from
    ``pyproject.toml``, so a contract test importing it would rest on an undeclared
    dep. Instead whole-line comments are stripped (which is what stops a commented
    command satisfying anything), each ``run:`` scalar is folded to a single line
    (which is what makes the three reformats equivalent), and the disabling keys are
    asserted absent by name.

    Known and deliberately not covered: moving ``--check`` into an ``env:`` variable
    and referencing it in the command still reads as missing. Accepting arbitrary
    indirection would mean accepting a value this test cannot see, which is the
    property that made the substring form weak in the first place.

    Arrange: the CI workflow file.
    Act:     isolate the coverage-ratchet job and fold its run commands.
    Assert:  a live step invokes --check, nothing disables it, and master still fires.
    """
    # Arrange
    assert WORKFLOW_PATH.exists(), f"no CI workflow at {WORKFLOW_PATH}"
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    # Act
    job = _job_block(workflow, CI_JOB)
    assert job is not None, (
        f"{WORKFLOW_REL} has no `{CI_JOB}` job. The coverage ratchet is implemented but "
        "unrun, which is how it spent its whole life before P5.21: a change can kill a "
        "live cell or un-bind a published rule with every gate still green "
        "(.claude/LESSONS.md B5). Restore the job."
    )
    # Comments are stripped ONCE, here: every assertion below must read the job as
    # CI will execute it, and a commented-out line executes nothing.
    live = _without_comments(job)
    commands = _run_commands(live)

    # Assert — a real, uncommented step invokes the gate
    assert any(_INVOKES_CHECK.search(command) for command in commands), (
        f"the `{CI_JOB}` job in {WORKFLOW_REL} runs no command invoking "
        f"`{SCRIPT_REL} ... --check`. A commented-out `run:` does not count, which is the "
        "point: the ratchet was unrun for its whole life, and the estate goes blind "
        "quietly rather than loudly.\nCommands found in the job:\n  "
        + ("\n  ".join(commands) or "(none)")
    )

    # Assert — and nothing renders its failure harmless
    assert "continue-on-error" not in live, (
        f"the `{CI_JOB}` job in {WORKFLOW_REL} carries `continue-on-error`, so the ratchet "
        "runs, reports, and cannot fail the build. That is indistinguishable from not "
        "running it — and it is the cheapest way to silence a red gate, which is exactly "
        "why it is asserted here."
    )
    assert not _JOB_CONDITIONAL.search(live), (
        f"the `{CI_JOB}` job in {WORKFLOW_REL} carries an `if:` condition. This gate has no "
        "legitimate reason to be conditional, and `if: false` is a one-word disable that "
        "leaves every other assertion in this test green."
    )

    # Assert — the workflow still fires on the branch the gate has to protect
    assert _push_to_master_triggers_ci(workflow), (
        f"{WORKFLOW_REL} no longer runs on a push to master, so every job in it — this "
        "ratchet included — is dead regardless of how it is written. Restore the "
        "`on: push: branches:` filter (`'**'` covers master)."
    )


def _without_comments(text: str) -> str:
    """``text`` with whole-line YAML comments removed.

    Whole-line only. A trailing ``# ...`` on a live line leaves that line live, and
    stripping it properly would need to know about quoting. Whole-line removal is
    what matters here: it is what stops a commented-out step, or a command left
    behind in a note, from satisfying an assertion about what CI executes.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _job_block(workflow: str, job: str) -> str | None:
    """One job's lines, from its key to the next key at the same indentation.

    Extracted rather than searched for across the whole file so that ``if:`` and
    ``continue-on-error`` are attributed to THIS job — a neighbouring job legitimately
    carrying either must not make this test red, and must not excuse this job either.
    """
    lines = workflow.splitlines()
    opener = re.compile(rf"^  {re.escape(job)}:[ \t]*$")
    start = next((index for index, line in enumerate(lines) if opener.match(line)), None)
    if start is None:
        return None
    for index in range(start + 1, len(lines)):
        # The next key at job indentation, or any top-level key, ends this block.
        if re.match(r"^  \S", lines[index]) or re.match(r"^\S", lines[index]):
            return "\n".join(lines[start:index])
    return "\n".join(lines[start:])


def _run_commands(job: str) -> list[str]:
    """Every ``run:`` command in a job, each folded onto a single line.

    Folding is what makes formatting irrelevant, in both directions. A ``run: |``
    block scalar owns every following line indented deeper than its own ``run:``; a
    same-line command owns any line the shell continued with a trailing ``\\``. Both
    fold to the string a reader would call "the command", so ``run: |`` + newline,
    a ``\\`` continuation and a double space all become the same subject — the three
    working reformats that reddened the old substring assertion.

    Anchored per line (equivalent to ``re.MULTILINE``) so ``run:`` must be the first
    token after its indentation; ``job`` is expected to be comment-stripped already,
    which is what excludes a leading ``#``.
    """
    lines = job.splitlines()
    opener = re.compile(r"^([ \t]*)run:[ \t]*(\|[-+]?)?[ \t]*(.*)$")
    commands: list[str] = []
    index = 0
    while index < len(lines):
        match = opener.match(lines[index])
        if match is None:
            index += 1
            continue
        indent, block, inline = match.group(1), match.group(2), match.group(3)
        parts = [inline] if inline.strip() else []
        index += 1
        while index < len(lines):
            following = lines[index]
            deeper = bool(following.strip()) and len(following) - len(following.lstrip()) > len(
                indent
            )
            continued = bool(parts) and parts[-1].rstrip().endswith("\\")
            if not (block and deeper) and not continued:
                break
            parts.append(following.strip())
            index += 1
        commands.append(" ".join(part.rstrip("\\").strip() for part in parts).strip())
    return commands


def _push_to_master_triggers_ci(workflow: str) -> bool:
    """Whether pushing ``master`` still starts this workflow.

    Asserted because every other check in the CI test is vacuous if the workflow
    never fires — removing ``on:`` was one of the five disarms that left the old
    substring assertion green. A ``push:`` with no ``branches`` filter fires on every
    branch, so it covers master; ``'**'`` does too.
    """
    live = _without_comments(workflow)
    lines = live.splitlines()
    start = next((index for index, line in enumerate(lines) if re.match(r"^on:", line)), None)
    if start is None:
        return False
    end = next(
        (index for index in range(start + 1, len(lines)) if re.match(r"^\S", lines[index])),
        len(lines),
    )
    triggers = "\n".join(lines[start:end])

    push = re.search(r"^[ \t]+push:[ \t]*$((?:\n[ \t]{3,}.*)*)", triggers, re.MULTILINE)
    if push is None:
        return False
    branches = re.search(r"branches:[ \t]*(.*)", push.group(1))
    if branches is None:
        return True  # `push:` with no branches filter fires on every branch
    return "**" in branches.group(1) or "master" in branches.group(1)


def test_baseline_is_not_weakened_against_the_committed_copy() -> None:
    """A working-tree edit may not move any metric in the permissive direction.

    Scope, stated plainly: this compares the working tree against ``HEAD``, so it
    binds in the window where the damage is done casually — an agent or operator
    facing a red ratchet edits ``dead_cells`` upward and moves on. Once the change
    is COMMITTED it passes, by design: re-banking after a real, recorded
    improvement (or after ``RUNS`` grows, which mechanically worsens the cell
    metrics) is legitimate, and the commit message is where the reason belongs.
    The test's job is to make weakening a deliberate act rather than a quiet one.

    It is therefore vacuous on a CI checkout, where the tree equals the commit.
    That is not a hole this test can close — a gate against a *committed*
    weakening would have to fail the very commit that legitimately re-banks.

    Scoped by provenance, for the same reason ``--check`` is: two copies measured
    over DIFFERENT matrices have no comparable metrics, so no weakening can be read
    off them and asserting one anyway would fail every legitimate re-bank that
    follows a ``RUNS`` change. What still binds in that case is
    ``test_baseline_provenance_matches_the_live_runs_matrix``, which requires the
    working tree's provenance to describe the LIVE matrix — so weakening a number
    behind a provenance edit costs an edit to ``RUNS`` itself, which is a visible,
    reviewable act rather than a quiet one.

    Arrange: the baseline as of HEAD.
    Act:     compare each metric against the working-tree copy, per direction.
    Assert:  nothing moved the permissive way.
    """
    # Arrange
    committed = _baseline_at_head()
    if committed is None:
        pytest.skip(f"git cannot supply {BASELINE_REL} at HEAD (untracked, or no git)")
    working: dict[str, Any] = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if _matrix_of(committed) != _matrix_of(working):
        pytest.skip(
            "HEAD and the working tree record different provenance, so their metrics were "
            "measured over different portfolio x regime matrices and no weakening can be "
            "read off a comparison. test_baseline_provenance_matches_the_live_runs_matrix "
            "is what binds here: it requires the working tree's provenance to describe the "
            "live RUNS."
        )

    # Act
    weakenings = _weakenings(committed, working)

    # Assert
    assert not weakenings, (
        "scripts/coverage_baseline.json has been weakened in the working tree:\n  "
        + "\n  ".join(weakenings)
        + "\nA baseline edited to clear a red gate banks the blind spot as expected "
        "behaviour. Restore the coverage instead. If the weakening is real and "
        "intended — a genuinely larger RUNS matrix, say — re-measure it rather than "
        f"typing it, and commit it with the reason:\n{REBANK}"
    )


def _baseline_at_head() -> dict[str, Any] | None:
    """The baseline as committed at ``HEAD``, or ``None`` when git cannot say."""
    result = subprocess.run(
        ["git", "show", f"HEAD:{BASELINE_REL}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _matrix_of(baseline: dict[str, Any]) -> tuple[Any, ...]:
    """The (run count, ordered pairs) a baseline copy says it was measured over.

    A baseline predating ``provenance`` gets its own sentinel value, so it never
    compares equal to one that carries the field: "matrix unknown" is a difference,
    not a match.
    """
    banked = baseline.get("provenance")
    if not isinstance(banked, dict):
        return ("<no provenance recorded>",)
    return (
        banked.get("runs"),
        tuple(
            (entry.get("regime"), entry.get("portfolio")) for entry in banked.get("portfolios", ())
        ),
    )


def _weakenings(committed: dict[str, Any], working: dict[str, Any]) -> list[str]:
    """Metrics the working tree moved in the permissive direction, described.

    A metric absent from either side is not a weakening — the key-set agreement
    is a separate assertion, and reporting it twice would obscure which failed.
    """
    described: list[str] = []
    for name in COVERAGE._RATCHET_MIN:
        if name in committed and name in working and int(working[name]) < int(committed[name]):
            described.append(f"{name}: {committed[name]} -> {working[name]} (lowered a floor)")
    for name in COVERAGE._RATCHET_MAX:
        if name in committed and name in working and int(working[name]) > int(committed[name]):
            described.append(f"{name}: {committed[name]} -> {working[name]} (raised a ceiling)")
    return described


@pytest.mark.slow
def test_measured_coverage_matches_the_baseline() -> None:
    """Re-measure the estate and ratchet all six metrics against the baseline.

    Excluded from the dev loop: 24 pipeline runs (16 portfolio x regime, plus a
    prior-period run for each of the 8 with IRB permission) through both
    reporting generators — 117-169s measured warm, slower cold. The
    ``coverage-ratchet`` CI job is where this normally executes; this test is the
    same gate reachable from pytest via ``-m slow``.

    Arrange: the committed baseline.
    Act:     run the real measurement in --check mode.
    Assert:  no metric moved the permissive way.
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
        "Reporting coverage moved off the baseline. A FALLING binding-rule count or "
        "cells_live means the estate lost sight of something it used to check; a RISING "
        "never-evaluated count means a fresh blind spot. Neither fails "
        "loudly on its own — the supervisory register reports an unreachable rule as "
        "NOT_EVALUATED, which reads exactly like a clean estate (.claude/LESSONS.md B5). "
        "Read cells_live first: it is the cell-coverage floor, whereas a move in "
        "template_cell_liveness_bp or dead_cells can be nothing but the denominator "
        "changing. Fix the coverage rather than banking the loss; if the move is a real "
        "improvement, or RUNS grew, re-measure and bank it deliberately:\n"
        f"{REBANK}\n"
        f"{result.stdout[-4000:]}\n{result.stderr[-2000:]}"
    )
