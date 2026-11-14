"""
Reading a GitHub Actions workflow well enough to assert a gate is still wired.

Pipeline position:
    (no pipeline stage — shared by the contract tests that assert a ratchet's CI
    job exists, is enabled, and can fail the build)

A ratchet nothing runs is prose with extra steps, so each ratchet's contract
test asserts that CI invokes it. A substring search over the workflow file is
not that assertion: it stays green when the ``run:`` line is commented out, when
the job carries ``if: false`` or ``continue-on-error``, and when the workflow's
triggers are removed — and goes red on three working reformats of the command.

So the workflow is read structurally, but WITHOUT a YAML parser: ``pyyaml`` is
importable here only as a transitive dependency and is not declared in
``pyproject.toml``. Whole-line comments are stripped (what stops a commented
command satisfying anything), each ``run:`` scalar is folded to one line (what
makes the reformats equivalent), and the disabling keys are found by name.

Known and deliberately not covered: a flag moved into an ``env:`` variable and
referenced from the command reads as missing. Accepting arbitrary indirection
would mean accepting a value these helpers cannot see.

References:
- tests/contracts/test_coverage_ratchet.py — the first user, and the history
- tests/contracts/test_filing_mapping_ratchet.py
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
WORKFLOW_REL = ".github/workflows/ci.yml"

#: A job-level or step-level ``if:``. Anchored per line under ``re.MULTILINE`` so it
#: cannot match the word inside a command or a comment (comments are stripped before
#: this is applied). ``if: false`` is a one-word disable, so its absence is asserted.
JOB_CONDITIONAL = re.compile(r"^[ \t]*(?:-[ \t]+)?if:", re.MULTILINE)


def gate_wiring_problems(job: str, invocation: re.Pattern[str]) -> list[str]:
    """Every way the ``job`` fails to run a gate fatally. Empty means it is wired.

    Args:
        job: The CI job's key, e.g. ``coverage-ratchet``.
        invocation: Matches a folded ``run:`` command that invokes the gate.
    """
    if not WORKFLOW_PATH.exists():
        return [f"no CI workflow at {WORKFLOW_PATH}"]
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    block = job_block(workflow, job)
    if block is None:
        return [f"{WORKFLOW_REL} has no `{job}` job"]

    live = without_comments(block)
    commands = run_commands(live)
    problems: list[str] = []
    if not any(invocation.search(command) for command in commands):
        problems.append(
            f"the `{job}` job runs no command matching `{invocation.pattern}` (a "
            "commented-out `run:` does not count). Commands found: "
            + ("; ".join(commands) or "(none)")
        )
    if "continue-on-error" in live:
        problems.append(
            f"the `{job}` job carries `continue-on-error`, so the gate runs, reports, and "
            "cannot fail the build"
        )
    if JOB_CONDITIONAL.search(live):
        problems.append(
            f"the `{job}` job carries an `if:` condition; `if: false` is a one-word disable"
        )
    if not push_to_master_triggers_ci(workflow):
        problems.append(
            f"{WORKFLOW_REL} no longer runs on a push to master, so every job in it is dead"
        )
    return problems


def without_comments(text: str) -> str:
    """``text`` with whole-line YAML comments removed.

    Whole-line only. A trailing ``# ...`` on a live line leaves that line live, and
    stripping it properly would need to know about quoting. Whole-line removal is
    what matters here: it is what stops a commented-out step, or a command left
    behind in a note, from satisfying an assertion about what CI executes.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def job_block(workflow: str, job: str) -> str | None:
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


def run_commands(job: str) -> list[str]:
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


def push_to_master_triggers_ci(workflow: str) -> bool:
    """Whether pushing ``master`` still starts this workflow.

    Asserted because every other check in the CI test is vacuous if the workflow
    never fires — removing ``on:`` was one of the five disarms that left the old
    substring assertion green. A ``push:`` with no ``branches`` filter fires on every
    branch, so it covers master; ``'**'`` does too.
    """
    live = without_comments(workflow)
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
