"""
Reporting-coverage ratchet gates (P5.21 / independent validation plan C5).

Pipeline position:
    (no pipeline stage — gates the estate-wide measurement of the pipeline's
    reporting output)
    scripts/coverage_report.py --check -> scripts/coverage_baseline.json

``scripts/coverage_report.py`` measures how much of the published rulebook the
gates can actually SEE, over the same portfolio x regime matrix the supervisory
register runs (``RUNS``, imported and never re-declared). It emits seven
ratchetable numbers: ``union_binding_rules_crr`` / ``union_binding_rules_b31``,
``cells_live``, ``cells_nonzero`` and ``template_cell_liveness_bp`` may not FALL,
``dead_cells`` and ``never_evaluated_rules`` may not RISE.

``cells_live`` tests NULL-ness and ``cells_nonzero`` ZERO-ness, and neither is
redundant: a figure falling to 0.00 stays live and fails only ``cells_nonzero``; a
filed 0.00 becoming a blank fails only ``cells_live``. ``cells_nonzero`` counts cell
ADDRESSES (regime, template, sheet, row, column), so it fails on a figure zeroed on one
sheet while the same column stays lit on another — the move the per-column template
census cannot see — and each of the five parts of that key is pinned by its own leg. A
cell counts as non-zero only above ``NONZERO_TOLERANCE``, so summation-order dust that
varies with the Polars thread count cannot move it. Both are NET counts — a figure
moving from one address to another fails neither — and the zero-ness tests below pin
each of these facts, the limit included, through the script's real ``_absorb_frame``.

``cells_live`` is what makes destroying cell coverage fail, and it is worth
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
- Eight **always-on zero-ness tests** that fold hand-built frames through the
  script's own ``_absorb_frame`` / ``summarise`` / ``_ratchet_deltas`` (no
  pipeline): what ``cells_nonzero`` catches — including a figure zeroed on one
  sheet while its (template, column) pair stays lit on another, which the template
  census cannot see — what only ``cells_live`` catches, the cell-to-cell move
  neither catches, the always-zero address list (live 0.00s, not dead blanks), each
  of the five parts of the cell key on its own, and the zero tolerance at both ends
  (measured dust not counted, the smallest real figure counted, and a cell flipping
  between 0.0 and dust moving nothing).
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
- scripts/coverage_report.py — the measurement and the seven-metric ratchet
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
from typing import Any, NamedTuple

import polars as pl
import pytest
from tests.contracts._ci_workflow import (
    JOB_CONDITIONAL,
    job_block,
    push_to_master_triggers_ci,
    run_commands,
    without_comments,
)

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
#: normalised to one line by ``run_commands``, so any amount of whitespace, a
#: block scalar and a shell continuation all reduce to the same subject — the three
#: working reformats that reddened the old substring form.
_INVOKES_CHECK = re.compile(re.escape(SCRIPT_REL) + r"[^\n]*?--check")

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
    job = job_block(workflow, CI_JOB)
    assert job is not None, (
        f"{WORKFLOW_REL} has no `{CI_JOB}` job. The coverage ratchet is implemented but "
        "unrun, which is how it spent its whole life before P5.21: a change can kill a "
        "live cell or un-bind a published rule with every gate still green "
        "(.claude/LESSONS.md B5). Restore the job."
    )
    # Comments are stripped ONCE, here: every assertion below must read the job as
    # CI will execute it, and a commented-out line executes nothing.
    live = without_comments(job)
    commands = run_commands(live)

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
    assert not JOB_CONDITIONAL.search(live), (
        f"the `{CI_JOB}` job in {WORKFLOW_REL} carries an `if:` condition. This gate has no "
        "legitimate reason to be conditional, and `if: false` is a one-word disable that "
        "leaves every other assertion in this test green."
    )

    # Assert — the workflow still fires on the branch the gate has to protect
    assert push_to_master_triggers_ci(workflow), (
        f"{WORKFLOW_REL} no longer runs on a push to master, so every job in it — this "
        "ratchet included — is dead regardless of how it is written. Restore the "
        "`on: push: branches:` filter (`'**'` covers master)."
    )


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


class _Shape(NamedTuple):
    """One template column carried on two sheets of the same template.

    ``sheet`` and ``sibling`` both carry ``column``. That is the shape the template
    census (``check_template_cell_coverage.py``) cannot resolve: its unit is the
    (template, column) pair, which stays live while ANY one sheet holds a figure, so
    a figure zeroed on ``sibling`` is invisible to it while ``sheet`` stays lit.
    """

    regime: str
    template: str
    sheet: str
    sibling: str
    column: str

    def address(self, sheet: str, row: str) -> Any:
        """The regime-qualified ``CellAddress`` of ``row`` on ``sheet`` in this column."""
        return COVERAGE.CellAddress(self.regime, self.template, sheet, row, self.column)


#: Real addresses from each regime's estate, so the legs fold cells shaped like the
#: ones ``--check`` folds. CRR: C 08.01's SME-supporting-factor column 0256 on
#: ``corporate_sme`` beside ``corporate`` — the shape that motivated the metric (plan
#: P5.71). Column 0256 does not exist under Basel 3.1 (supporting factors are gone —
#: ``reporting/corep/templates.py``), so b31 uses OF 08.01's mortgage-RW-floor column
#: 0253, the column ``.claude/LESSONS.md`` B5 records as having held 0.00 in every
#: golden portfolio.
#:
#: The fold path is regime-independent, so the two cases check the address shape;
#: they are NOT two independent proofs. What each part of the key does — the regime
#: included — is pinned on its own by
#: ``test_every_part_of_the_cell_address_keeps_a_lost_figure_from_being_masked``.
_CRR_SHAPE = _Shape("crr", "C 08.01.a", "corporate_sme", "corporate", "0256")
_B31_SHAPE = _Shape(
    "b31",
    "OF08.01.01.01",
    "retail_residential_re_non_sme_airb",
    "retail_other_non_sme_airb",
    "0253",
)
_ZERO_NESS_CASES = [
    pytest.param(_CRR_SHAPE, id="crr"),
    pytest.param(_B31_SHAPE, id="b31"),
]


def _fold(cells: dict[Any, float | None]) -> tuple[Any, dict[str, Any]]:
    """Cells keyed by ``CellAddress``, folded through the REAL ``_absorb_frame``.

    The cells are grouped into one emitted frame per (regime, template, sheet), the
    unit ``_absorb_cells`` hands to ``_absorb_frame``, with one row per row ref and
    one ``Float64`` column per column named, and every frame is accumulated into ONE
    ``Observation`` the way a matrix run accumulates every sheet of every run. A
    (row, column) of a frame that ``cells`` leaves out is a blank: declared, never
    live, and the same in any two measurements that name the same addresses.

    Built through the script's own accumulator rather than by filling the sets by
    hand, so the test reads liveness and zero-ness exactly as ``--check`` does
    (``.claude/LESSONS.md`` B3) — a hand-filled set would share whatever assumption
    the test's author made about which values count.
    """
    sheets: dict[tuple[str, str, str], dict[str, dict[str, float | None]]] = {}
    for address, value in cells.items():
        rows = sheets.setdefault((address.regime, address.template, address.sheet), {})
        rows.setdefault(address.row, {})[address.column] = value

    observation = COVERAGE.Observation()
    for (regime, template, sheet), rows in sheets.items():
        columns = sorted({column for row in rows.values() for column in row})
        frame = pl.DataFrame(
            {
                "row_ref": list(rows),
                **{column: [row.get(column) for row in rows.values()] for column in columns},
            },
            schema={"row_ref": pl.String, **dict.fromkeys(columns, pl.Float64)},
        )
        COVERAGE._absorb_frame(observation, regime, template, sheet, frame)
    return observation, COVERAGE.summarise(observation)


def _fold_shape(
    shape: _Shape, sheets: dict[str, dict[str, float | None]]
) -> tuple[Any, dict[str, Any]]:
    """Fold ``{sheet: {row_ref: value}}`` under the shape's regime, template and column."""
    return _fold(
        {
            shape.address(sheet, row): value
            for sheet, rows in sheets.items()
            for row, value in rows.items()
        }
    )


def _ratchet(before: dict[str, Any], after: dict[str, Any]) -> tuple[list[str], list[str]]:
    """``(regressions, improvements)`` of ``after`` against ``before``, as ``--check`` does."""
    return COVERAGE._ratchet_deltas(
        COVERAGE._ratchet_values(before), COVERAGE._ratchet_values(after)
    )


def _census_unit(observation: Any) -> set[tuple[str, str]]:
    """The non-zero cells projected onto the template census's unit, (template, column).

    ``check_template_cell_coverage.py`` keys a column by (family, template, column) —
    deliberately not by regime or sheet — and calls it live when any run puts a
    non-zero value anywhere in it. Projecting the same accumulator onto that unit
    shows what the census would see of a fixture, without running its pipelines.
    """
    return {(address.template, address.column) for address in observation.cells_nonzero}


@pytest.mark.parametrize("shape", _ZERO_NESS_CASES)
def test_a_net_loss_of_non_zero_cells_is_a_coverage_regression(shape: _Shape) -> None:
    """A reported figure falling to 0.00, uncompensated, fails the ratchet.

    ``cells_live`` tests NULL-ness: a cell that drops from a figure to 0.00 is still
    "carrying a value", so it stays live and every cell metric is unchanged. Before
    ``cells_nonzero`` was ratcheted that move failed nothing here.

    What this guards is a NET count, not each cell — see
    ``test_a_figure_moving_to_another_cell_is_not_caught_by_the_net_count`` below.

    Arrange: one cell holding 5.0, and the same cell holding 0.0.
    Act:     ratchet the second measurement against the first.
    Assert:  the only regression is ``cells_nonzero``.
    """
    # Arrange
    _, before = _fold_shape(shape, {shape.sheet: {"0010": 5.0}})
    _, after = _fold_shape(shape, {shape.sheet: {"0010": 0.0}})
    assert before["metrics"]["cells_live"] == after["metrics"]["cells_live"] == 1, (
        "both states must hold one LIVE cell — otherwise cells_live can catch the move "
        "and this test proves nothing about zero-ness"
    )

    # Act
    regressions, improvements = _ratchet(before, after)

    # Assert
    assert regressions == ["cells_nonzero: 1 -> 0 (may not decrease)"], (
        f"{shape.regime}: a figure falling to 0.00 must fail the coverage ratchet as a "
        f"lost non-zero cell, and nothing else moved; got regressions {regressions}"
    )
    assert improvements == []


@pytest.mark.parametrize("shape", _ZERO_NESS_CASES)
def test_a_figure_zeroed_on_one_sheet_fails_while_its_column_stays_lit_on_another(
    shape: _Shape,
) -> None:
    """The case this metric exists for: the template census cannot see it.

    ``check_template_cell_coverage.py`` counts (template, column) pairs, so a pair
    stays live while ANY sheet holds a figure in it. On the CRR shape, C 08.01
    column 0256 carries a figure on ``corporate_sme``; if it falls to 0.00 on
    ``corporate`` the pair is still lit and the census reports nothing. Only a count
    per cell ADDRESS — sheet and row included — can fail on that. A metric built at
    the census's column granularity passes the leg above (one cell, one column) and
    fails this one, which is why this leg exists.

    Arrange: the column holds 5.0 on both sheets; then 5.0 on ``sheet`` and 0.0 on
             ``sibling``. Guard: the census unit is lit, unchanged, in both.
    Act:     ratchet the second measurement against the first.
    Assert:  the only regression is ``cells_nonzero: 2 -> 1``.
    """
    # Arrange
    observed_before, before = _fold_shape(
        shape, {shape.sheet: {"0010": 5.0}, shape.sibling: {"0010": 5.0}}
    )
    observed_after, after = _fold_shape(
        shape, {shape.sheet: {"0010": 5.0}, shape.sibling: {"0010": 0.0}}
    )
    pair = {(shape.template, shape.column)}
    assert _census_unit(observed_before) == _census_unit(observed_after) == pair, (
        "the (template, column) pair must be lit in BOTH measurements — otherwise the "
        "census could catch this move too, and the leg would not show what only the "
        "per-address count sees"
    )

    # Act
    regressions, improvements = _ratchet(before, after)

    # Assert
    assert regressions == ["cells_nonzero: 2 -> 1 (may not decrease)"], (
        f"{shape.regime}: {shape.address(shape.sibling, '0010').describe()} fell to 0.00 "
        f"while {shape.address(shape.sheet, '0010').describe()} stayed lit; that must "
        f"fail as a lost non-zero cell; got regressions {regressions}"
    )
    assert improvements == []


@pytest.mark.parametrize("shape", _ZERO_NESS_CASES)
def test_a_zero_falling_to_null_regresses_cells_live_but_not_cells_nonzero(
    shape: _Shape,
) -> None:
    """The mirror leg: the two cell floors are not redundant in either direction.

    A filed 0.00 that becomes a blank is what the "uninteresting zeros" clean-ups do
    (``.claude/LESSONS.md`` B4), and it is ``cells_live`` — not ``cells_nonzero`` —
    that moves on it. So neither floor can be retired in favour of the other: this
    leg is caught only by ``cells_live``, the ones above only by ``cells_nonzero``.

    Arrange: one cell holding 0.0, and the same cell null.
    Act:     ratchet the second measurement against the first.
    Assert:  ``cells_live`` regresses and ``cells_nonzero`` does not.
    """
    # Arrange
    _, before = _fold_shape(shape, {shape.sheet: {"0010": 0.0}})
    _, after = _fold_shape(shape, {shape.sheet: {"0010": None}})

    # Act
    regressions, _ = _ratchet(before, after)

    # Assert
    assert "cells_live: 1 -> 0 (may not decrease)" in regressions, (
        f"{shape.regime}: a 0.00 becoming a blank must still fail cells_live; got {regressions}"
    )
    assert not [line for line in regressions if line.startswith("cells_nonzero")], (
        f"{shape.regime}: cells_nonzero counted a 0.00 as a figure; got {regressions}"
    )


@pytest.mark.parametrize("shape", _ZERO_NESS_CASES)
def test_a_figure_moving_to_another_cell_is_not_caught_by_the_net_count(shape: _Shape) -> None:
    """Pins the LIMIT of ``cells_nonzero``: it is a net count, not a per-cell guard.

    Kept so that nobody later cites this ratchet as a guard against a row re-key or
    a misroute (``.claude/LESSONS.md`` B6). A figure that leaves one address and
    lands on another leaves the count unchanged, and so passes; so does a zeroing
    offset by cells lit since the last bank, because an unbanked improvement exits 0.
    If this test ever goes red, the ratchet has become per-address — update the
    docstrings that say it is not.

    Arrange: two cells, the figure on row 0010; then the figure on row 0020.
    Act:     ratchet the second measurement against the first.
    Assert:  an address really lost its figure, and no metric regressed.
    """
    # Arrange
    observed_before, before = _fold_shape(shape, {shape.sheet: {"0010": 5.0, "0020": 0.0}})
    observed_after, after = _fold_shape(shape, {shape.sheet: {"0010": 0.0, "0020": 5.0}})
    lost = observed_before.cells_nonzero - observed_after.cells_nonzero
    assert lost == {shape.address(shape.sheet, "0010")}, (
        "the fixture must really move a figure off an address, or there is no limit to pin"
    )

    # Act
    regressions, _ = _ratchet(before, after)

    # Assert
    assert regressions == [], (
        f"{shape.regime}: the net-count ratchet now reports a cell-to-cell move "
        f"({regressions}). That makes it a per-address guard — update the docstrings "
        "that say it is not."
    )


@pytest.mark.parametrize("shape", _ZERO_NESS_CASES)
def test_the_always_zero_cells_are_listed_by_address(shape: _Shape) -> None:
    """A cell that is live only as 0.00 is named in the evidence, not just counted.

    ``cells_nonzero`` cannot make a cell that is 0.00 for its whole life visible —
    the C 08.01 column-0253 shape of ``.claude/LESSONS.md`` B5. Listing those
    addresses turns B5's manual step ("confirm the cell you are changing is non-zero
    somewhere") into a lookup in the metrics JSON. Evidence only, never ratcheted.

    The list is the LIVE cells that are never non-zero — not every cell that is
    never non-zero, which would also sweep in the dead (null) cells that
    ``dead_cell_list`` already names, and bury the 0.00s among them.

    Arrange: one sheet with a figure on row 0010, 0.00 on row 0020 and a blank on
             row 0030.
    Act:     summarise it.
    Assert:  exactly row 0020 is listed; the blank row is dead and not listed; the
             count agrees with the list.
    """
    # Arrange / Act
    _, payload = _fold_shape(shape, {shape.sheet: {"0010": 5.0, "0020": 0.0, "0030": None}})
    zero = shape.address(shape.sheet, "0020").describe()
    blank = shape.address(shape.sheet, "0030").describe()
    assert payload["dead_cell_list"] == [blank], (
        "the fixture must hold exactly one dead cell, or the leg cannot tell a 0.00 from a blank"
    )

    # Assert
    assert blank not in payload["always_zero_cell_list"], (
        f"{shape.regime}: a dead (null) cell was listed as always-zero"
    )
    assert payload["always_zero_cell_list"] == [zero]
    assert payload["cells"]["live_but_always_zero"] == len(payload["always_zero_cell_list"])


_A = COVERAGE.CellAddress

#: For each of the five parts of the cell key, two addresses that differ in THAT part
#: only. Every pair but the regime one is two real addresses that both hold a figure
#: in the measured estate (31-run matrix, P5.71 review), so a count keyed without the
#: part would merge two cells that ``--check`` really folds. Without the row it would
#: merge most of them: measured on the 31-run matrix, 4550 of 4755 non-zero addresses
#: share (regime, template, sheet, column) with another non-zero address.
#:
#: No real pair differs only in the regime: the two regimes' table-code spaces are
#: disjoint (``C 08.01.a`` against ``OF08.01.01.01``; no code from
#: ``_template_codes`` is in both), so the regime row places the CRR address under b31
#: as well. It pins the key, not a collision the estate has today — and it is what
#: makes the crr / b31 parametrisation of the other legs mean anything.
_ONE_PART_APART = [
    pytest.param(
        "regime",
        _A("crr", "C 08.01.a", "corporate_sme", "0010", "0256"),
        _A("b31", "C 08.01.a", "corporate_sme", "0010", "0256"),
        id="regime",
    ),
    pytest.param(
        "template",
        _A("crr", "C 08.01.a", "corporate_sme", "0010", "0010"),
        _A("crr", "C 08.04", "corporate_sme", "0010", "0010"),
        id="crr-template",
    ),
    pytest.param(
        "template",
        _A("b31", "OF08.03.01.01", "retail_residential_re_non_sme_airb", "0060", "0010"),
        _A("b31", "OF08.05.00.01", "retail_residential_re_non_sme_airb", "0060", "0010"),
        id="b31-template",
    ),
    pytest.param(
        "sheet",
        _A("crr", "C 08.01.a", "corporate_sme", "0010", "0010"),
        _A("crr", "C 08.01.a", "corporate", "0010", "0010"),
        id="crr-sheet",
    ),
    pytest.param(
        "sheet",
        _A("b31", "OF08.01.01.01", "retail_residential_re_non_sme_airb", "0010", "0253"),
        _A("b31", "OF08.01.01.01", "total_airb", "0010", "0253"),
        id="b31-sheet",
    ),
    pytest.param(
        "row",
        _A("crr", "C 08.01.a", "corporate_sme", "0010", "0256"),
        _A("crr", "C 08.01.a", "corporate_sme", "0020", "0256"),
        id="crr-row",
    ),
    pytest.param(
        "row",
        _A("b31", "OF08.01.01.01", "retail_residential_re_non_sme_airb", "0010", "0253"),
        _A("b31", "OF08.01.01.01", "retail_residential_re_non_sme_airb", "0020", "0253"),
        id="b31-row",
    ),
    pytest.param(
        "column",
        _A("crr", "C 08.01.a", "corporate_sme", "0010", "0256"),
        _A("crr", "C 08.01.a", "corporate_sme", "0010", "0257"),
        id="crr-column",
    ),
    pytest.param(
        "column",
        _A("b31", "OF08.01.01.01", "retail_residential_re_non_sme_airb", "0010", "0253"),
        _A("b31", "OF08.01.01.01", "retail_residential_re_non_sme_airb", "0010", "0251"),
        id="b31-column",
    ),
]


def _without(part: str, observation: Any) -> set[Any]:
    """The non-zero cells keyed WITHOUT ``part`` — what a coarser count would see."""
    return {address._replace(**{part: ""}) for address in observation.cells_nonzero}


@pytest.mark.parametrize(("part", "kept", "zeroed"), _ONE_PART_APART)
def test_every_part_of_the_cell_address_keeps_a_lost_figure_from_being_masked(
    part: str, kept: Any, zeroed: Any
) -> None:
    """``cells_nonzero`` counts the full five-part address, each part pinned on its own.

    A count keyed without any one part — regime, template, sheet, row or column —
    merges two cells that differ only in that part, so a figure lost from one is
    masked while the other stays lit and the ratchet passes. Dropping the row is the
    row-granular blind spot ``.claude/LESSONS.md`` B5 names. Each case's guard proves
    the coarser count would really read ``1 -> 1`` on it, so the leg fails exactly the
    count that drops its part.

    Arrange: two addresses differing in ``part`` only, both 5.0; then ``zeroed`` 0.0.
    Act:     ratchet the second measurement against the first.
    Assert:  the only regression is ``cells_nonzero: 2 -> 1``.
    """
    # Arrange
    differs = [name for name in kept._fields if getattr(kept, name) != getattr(zeroed, name)]
    assert differs == [part], f"the pair must differ in {part} only; it differs in {differs}"
    observed_before, before = _fold({kept: 5.0, zeroed: 5.0})
    observed_after, after = _fold({kept: 5.0, zeroed: 0.0})
    assert len(_without(part, observed_before)) == len(_without(part, observed_after)) == 1, (
        f"keyed without {part} the non-zero count must read 1 -> 1, or this leg does not "
        "show that the part is needed"
    )

    # Act
    regressions, improvements = _ratchet(before, after)

    # Assert
    assert regressions == ["cells_nonzero: 2 -> 1 (may not decrease)"], (
        f"{zeroed.describe()} fell to 0.00 while {kept.describe()}, which differs only in "
        f"its {part}, stayed lit; that must fail as a lost non-zero cell; got {regressions}"
    )
    assert improvements == []


#: Summation-order dust measured on the real estate (P5.71 review):
#: ``crr/C 08.04[corporate][r0080][c0010]`` on crm-substitution is exactly 0.0 at
#: POLARS_MAX_THREADS=1 and 4 and this at 2 — a closing balance of
#: 34188682.9307958 against an opening of 34188682.930795796.
_MEASURED_DUST = 7.450580596923828e-09

#: The smallest real figure the matrix folds: ``crr/C 09.02[US][r0010][c0080]``.
_SMALLEST_FIGURE = 2e-4


@pytest.mark.parametrize("shape", _ZERO_NESS_CASES)
def test_summation_dust_is_not_counted_as_a_figure_and_the_smallest_figure_is(
    shape: _Shape,
) -> None:
    """``cells_nonzero`` reads magnitudes above ``NONZERO_TOLERANCE``, both signs.

    Counted exactly (``!= 0``, as the template census does), the dust cell above
    lit at 2 Polars threads and not at 1 or 4, so the 2-vCPU CI runner and the
    1-thread pytest mirror measured different ``cells_nonzero`` and one of them was
    always red against any bank. The tolerance has to sit between the largest dust
    and the smallest real figure the estate folds; this pins both ends, and both
    signs, because a count of ``value > tolerance`` would silently drop every
    negative figure.

    Arrange: the dust and the smallest real figure, each positive and negative, on
             four rows of one column.
    Act:     summarise it.
    Assert:  the non-zero cells are exactly the two real figures; the two dust cells
             are live, and listed as always-zero.
    """
    # Arrange
    cells = {
        "0010": _MEASURED_DUST,
        "0020": -_MEASURED_DUST,
        "0030": _SMALLEST_FIGURE,
        "0040": -_SMALLEST_FIGURE,
    }

    # Act
    observation, payload = _fold_shape(shape, {shape.sheet: cells})

    # Assert
    figures = {shape.address(shape.sheet, "0030"), shape.address(shape.sheet, "0040")}
    dust = [shape.address(shape.sheet, row).describe() for row in ("0010", "0020")]
    assert observation.cells_nonzero == figures, (
        f"{shape.regime}: expected exactly the ±{_SMALLEST_FIGURE} cells to count as "
        f"figures; counted {sorted(a.describe() for a in observation.cells_nonzero)}"
    )
    assert payload["metrics"]["cells_live"] == 4
    assert payload["always_zero_cell_list"] == dust


@pytest.mark.parametrize("shape", _ZERO_NESS_CASES)
def test_a_cell_flipping_between_zero_and_dust_moves_no_metric(shape: _Shape) -> None:
    """The thread-count flip the tolerance exists for passes in both directions.

    The same tree measured at two Polars thread counts reads the dust cell as 0.0 in
    one and as the dust in the other. Neither is a change in coverage, so neither
    order may regress or improve any metric — otherwise the gate's verdict depends
    on the runner's core count.

    Arrange: one cell at 0.0, and the same cell at the measured dust.
    Act:     ratchet each measurement against the other.
    Assert:  no regression and no improvement either way.
    """
    # Arrange
    _, exact_zero = _fold_shape(shape, {shape.sheet: {"0010": 0.0}})
    _, dusty = _fold_shape(shape, {shape.sheet: {"0010": _MEASURED_DUST}})

    # Act
    forward = _ratchet(exact_zero, dusty)
    backward = _ratchet(dusty, exact_zero)

    # Assert
    assert forward == backward == ([], []), (
        f"{shape.regime}: a cell flipping between 0.0 and {_MEASURED_DUST} moved the "
        f"ratchet (0.0 -> dust: {forward}; dust -> 0.0: {backward})"
    )


@pytest.mark.slow
def test_measured_coverage_matches_the_baseline() -> None:
    """Re-measure the estate and ratchet all seven metrics against the baseline.

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
        "Reporting coverage moved off the baseline. A FALLING binding-rule count, "
        "cells_live or cells_nonzero means the estate lost sight of something it used to "
        "check (a figure that vanished, or one that fell to 0.00); a RISING "
        "never-evaluated count means a fresh blind spot. Neither fails "
        "loudly on its own — the supervisory register reports an unreachable rule as "
        "NOT_EVALUATED, which reads exactly like a clean estate (.claude/LESSONS.md B5). "
        "Read cells_live and cells_nonzero first: they are the cell-coverage floors, "
        "whereas a move in "
        "template_cell_liveness_bp or dead_cells can be nothing but the denominator "
        "changing. Fix the coverage rather than banking the loss; if the move is a real "
        "improvement, or RUNS grew, re-measure and bank it deliberately:\n"
        f"{REBANK}\n"
        f"{result.stdout[-4000:]}\n{result.stderr[-2000:]}"
    )
