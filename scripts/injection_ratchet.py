"""
Detection-rate ratchet for the defect-injection campaign (independent validation, S.3).

Pipeline position:
    .github/workflows/nightly-injection.yml
      -> scripts/defect_injection.py --ladder legacy   (scorecard JSON)
      -> scripts/defect_injection.py --ladder full     (scorecard JSON)
      -> scripts/injection_ratchet.py --summary        renders; NOT a gate
      -> scripts/injection_ratchet.py --check          THE gate

Key responsibilities:
- Read one scorecard per ladder and render the before/after board, the mean tier
  of detection, and the ``ESCAPED`` list, which is the load-bearing output.
- Refuse to draw any conclusion from a scorecard that cannot be trusted: a
  filtered campaign, a mutant whose reachability verdict contradicts the
  catalogue, a gate that timed out, an ``ERROR`` verdict.
- Ratchet the ABSOLUTE verdict SETS per ladder, two ways, against
  ``scripts/injection_baseline.json``.
- Fail loudly, and non-zero, while that baseline is un-banked.

Why sets and not the rate
-------------------------
The headline detection rate is ``detected / (detected + escaped)`` with
``UNREACHABLE`` excluded from both halves, so its denominator moves with its
numerator. A mutant that drifts onto a dead path leaves the scored pool
entirely: absolute detection falls and the rate can RISE. That is
``.claude/LESSONS.md`` B8 exactly — ratchet the accumulator, never the ratio —
so the gate is stated on three id SETS per ladder and the rate is reported only.

``UNREACHABLE`` is therefore ratcheted too. Letting the unreachable set grow
silently is the one move that lets the published rate improve while the estate's
measured coverage shrinks.

Why the known-defect floor uses a fixed denominator
---------------------------------------------------
The plan's absolute target is >= 90% detection on the ``known_defect`` mutants:
they have already escaped once, so failing to catch them again is inexcusable.
It is expressed here as ``detected / <catalogue count of known_defect>`` — the
denominator comes from the CATALOGUE, not from the verdicts — so an unreachable
known-defect mutant counts AGAINST the floor. It has to: an unreachable one
means the twin site the mutant is applied to is dead, and we cannot demonstrate
the estate would catch a defect that already got through.

References:
- docs/development/defect-injection.md — the harness, the ladder, the verdicts
- .claude/LESSONS.md B8 — ratchet the quantity, not a ratio of it
- .claude/LESSONS.md E1 — a ratchet going red because you fixed something is the
  design working; bank the improvement deliberately, never regenerate to green
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.defect_catalogue import CATALOGUE  # noqa: E402

#: Every path this script reads or writes must resolve inside the repository.
#: The nightly workflow only ever passes repo-relative paths
#: (`nightly-injection/scorecard-*.json`, `nightly-injection/summary*.md`, and the
#: default baseline); the `$GITHUB_STEP_SUMMARY` append is done by `cat` in the
#: workflow shell, never by this script, so nothing legitimate needs to escape.
_ALLOWED_ROOT = _REPO_ROOT


def _confine_path(raw: Path) -> Path:
    """Resolve a CLI-supplied path and reject anything outside ``_ALLOWED_ROOT``.

    Same guard as ``scripts/coverage_report.py`` and ``scripts/parity_gate.py``:
    ``--scorecard``, ``--baseline`` and ``--out`` are operator-supplied, and
    resolving FIRST collapses ``..`` segments so the containment check cannot be
    bypassed by a traversal sequence.

    Defined above every read/write site on purpose: the taint engine only treats
    a helper as a sanitiser when its definition precedes the call it guards.
    """
    resolved = raw.expanduser().resolve()
    if not resolved.is_relative_to(_ALLOWED_ROOT):
        raise SystemExit(f"path escapes {_ALLOWED_ROOT}: {raw}")
    return resolved


DEFAULT_BASELINE = _REPO_ROOT / "scripts" / "injection_baseline.json"

STATUS_UNBANKED = "UNBANKED"
STATUS_BANKED = "BANKED"

VERDICT_DETECTED = "DETECTED"
VERDICT_ESCAPED = "ESCAPED"
VERDICT_UNREACHABLE = "UNREACHABLE"
OUTCOME_TIMEOUT = "TIMEOUT"

#: The two ladders the nightly runs. Both are required to bank, because the
#: before/after pair from one build is the whole point of running two.
REQUIRED_LADDERS = ("legacy", "full")

#: Printed by every un-banked / bank-required failure, and mirrored in
#: ``scripts/injection_baseline.json`` under ``bank_command``. ``--note`` is
#: mandatory: a baseline that moved for a reason nobody wrote down is
#: indistinguishable from one someone widened to clear a red gate.
BANK_COMMAND = (
    "uv run python scripts/injection_ratchet.py --bank "
    "--note '<why this baseline moved>' "
    "--scorecard nightly-injection/scorecard-legacy.json "
    "--scorecard nightly-injection/scorecard-full.json"
)


# =============================================================================
# Reading a scorecard
# =============================================================================


@dataclass(frozen=True)
class Board:
    """One ladder's scorecard, reduced to what the ratchet and the board need."""

    ladder: str
    path: Path
    interpreter: str
    gates: tuple[str, ...]
    runtime_seconds: float
    mutants_total: int
    detected: frozenset[str]
    escaped: frozenset[str]
    unreachable: frozenset[str]
    detection_rate: float | None
    mean_tier: float | None
    #: mutant id -> the gate that caught it, for the board.
    caught_by: dict[str, str]
    #: mutant id -> list of gate names that timed out. Never empty when present.
    timeouts: dict[str, list[str]]
    #: mutant id -> the harness's own expectation-mismatch note.
    notes: dict[str, str]
    #: Verdicts that are neither detected, escaped nor unreachable (ERROR, PROBED).
    other_verdicts: dict[str, str]
    escaped_rows: tuple[tuple[str, str, str], ...]

    def known_defect_detected(self) -> frozenset[str]:
        return self.detected & _catalogue_ids_by_category("known_defect")


def load_board(path: Path) -> Board:
    """Reduce one ``defect_injection.py`` scorecard JSON to a ``Board``."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    board = payload["scorecard"]
    results = payload["results"]

    by_verdict: dict[str, set[str]] = {
        VERDICT_DETECTED: set(),
        VERDICT_ESCAPED: set(),
        VERDICT_UNREACHABLE: set(),
    }
    caught_by: dict[str, str] = {}
    timeouts: dict[str, list[str]] = {}
    notes: dict[str, str] = {}
    other: dict[str, str] = {}
    escaped_rows: list[tuple[str, str, str]] = []

    for entry in results:
        mutant_id = entry["mutant_id"]
        verdict = entry["verdict"]
        if verdict in by_verdict:
            by_verdict[verdict].add(mutant_id)
        else:
            other[mutant_id] = verdict
        if entry.get("caught_by"):
            caught_by[mutant_id] = entry["caught_by"]
        if entry.get("note"):
            notes[mutant_id] = entry["note"]
        timed_out = [
            gate["gate"]
            for gate in entry.get("gates", [])
            if gate.get("outcome") == OUTCOME_TIMEOUT
        ]
        if timed_out:
            timeouts[mutant_id] = timed_out
        if verdict == VERDICT_ESCAPED:
            escaped_rows.append((mutant_id, entry["category"], entry["summary"]))

    return Board(
        ladder=payload["ladder"],
        path=path,
        interpreter=payload.get("interpreter", ""),
        gates=tuple(payload.get("gates", ())),
        runtime_seconds=payload.get("runtime_seconds", 0.0),
        mutants_total=board["mutants_total"],
        detected=frozenset(by_verdict[VERDICT_DETECTED]),
        escaped=frozenset(by_verdict[VERDICT_ESCAPED]),
        unreachable=frozenset(by_verdict[VERDICT_UNREACHABLE]),
        detection_rate=board["detection_rate"],
        mean_tier=board["mean_tier_of_detection"],
        caught_by=caught_by,
        timeouts=timeouts,
        notes=notes,
        other_verdicts=other,
        escaped_rows=tuple(sorted(escaped_rows)),
    )


def load_boards(paths: list[Path]) -> dict[str, Board]:
    """One board per ladder. Two scorecards for the same ladder is an error."""
    boards: dict[str, Board] = {}
    for path in paths:
        board = load_board(path)
        if board.ladder in boards:
            raise SystemExit(
                f"two scorecards for ladder {board.ladder!r}: "
                f"{boards[board.ladder].path} and {path}"
            )
        boards[board.ladder] = board
    return boards


def _catalogue_ids_by_category(category: str) -> frozenset[str]:
    return frozenset(mutant.id for mutant in CATALOGUE if mutant.category == category)


def _plural(count: int, noun: str) -> str:
    """``1 mutant`` / ``3 mutants``. These messages are the product; read them."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


# =============================================================================
# Trust: is this scorecard readable at all?
# =============================================================================


def trust_failures(board: Board) -> list[str]:
    """Reasons no verdict in this scorecard may be believed.

    Each of these makes the headline rate fiction in a KNOWN direction, so they
    are checked before anything is compared against a baseline. A scorecard that
    fails any of them is not a bad result — it is an absent one.
    """
    failures: list[str] = []
    catalogue_ids = frozenset(mutant.id for mutant in CATALOGUE)
    scored_ids = board.detected | board.escaped | board.unreachable | set(board.other_verdicts)

    unscored = catalogue_ids - scored_ids
    missing = sorted(unscored)
    if missing:
        failures.append(
            f"{board.ladder}: {_plural(len(missing), 'catalogue mutant')} carrying no verdict "
            f"({', '.join(missing[:5])}{' ...' if len(missing) > 5 else ''}). A filtered or "
            "sharded campaign cannot be ratcheted — the un-run mutants would bank as if "
            "they did not exist. Note --resume does NOT merge earlier results into the "
            "scorecard it writes, so a resumed run is not a complete one."
        )
    unknown = sorted(scored_ids - catalogue_ids)
    if unknown:
        failures.append(
            f"{board.ladder}: verdicts for {_plural(len(unknown), 'mutant')} that are not in the "
            f"catalogue ({', '.join(unknown[:5])}). The scorecard was measured against a "
            "different catalogue than the one on disk; re-run the campaign."
        )

    # Reachability contradictions. Computed against the catalogue rather than
    # trusting the harness's own note, so a note that stops being written cannot
    # silence the check.
    expected_unreachable = frozenset(mutant.id for mutant in CATALOGUE if mutant.expect_unreachable)
    # `unscored` subtracted so a mutant that never ran is reported once, as
    # missing, rather than a second time as a contradicted expectation.
    wrongly_reachable = sorted(expected_unreachable - board.unreachable - unscored)
    wrongly_unreachable = sorted(board.unreachable - expected_unreachable)
    if wrongly_reachable:
        failures.append(
            f"{board.ladder}: {_plural(len(wrongly_reachable), 'mutant')} flagged expect_unreachable "
            f"came back reachable ({', '.join(wrongly_reachable)}). The reachability probe's "
            "control pair is what licenses every 'not detected' verdict; while a control "
            "disagrees with its flag, no escape in this scorecard is safe to believe."
        )
    if wrongly_unreachable:
        failures.append(
            f"{board.ladder}: {_plural(len(wrongly_unreachable), 'mutant')} expected to be reachable "
            f"moved nothing ({', '.join(wrongly_unreachable)}). Either the probe is too "
            "narrow or the mutated path is dead — both make the denominator wrong."
        )

    if board.timeouts:
        detail = "; ".join(
            f"{mutant_id} [{', '.join(gates)}]"
            for mutant_id, gates in sorted(board.timeouts.items())
        )
        failures.append(
            f"{board.ladder}: {_plural(len(board.timeouts), 'mutant')} had a gate TIME OUT ({detail}). "
            "A timeout is not a pass and not a failure — it is a gate that never finished, "
            "so any ESCAPED verdict resting on it is unproven. Raise the gate timeout or "
            "shard the campaign, then re-measure."
        )

    if board.other_verdicts:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(board.other_verdicts.items()))
        failures.append(
            f"{board.ladder}: {_plural(len(board.other_verdicts), 'mutant')} carrying a verdict that is "
            f"neither DETECTED, ESCAPED nor UNREACHABLE ({detail})."
        )

    if not board.interpreter:
        failures.append(
            f"{board.ladder}: the scorecard records no interpreter, so a reader cannot tell "
            "an override apart from the default. Re-run with a harness that records it."
        )
    return failures


# =============================================================================
# The absolute target: the known-defect floor
# =============================================================================


@dataclass(frozen=True)
class FloorResult:
    total: int
    detected: int
    rate: float | None
    floor: float
    passed: bool
    missing: tuple[str, ...]


def known_defect_floor(board: Board, floor: float) -> FloorResult:
    """>= ``floor`` of the catalogue's ``known_defect`` mutants must be DETECTED.

    Denominator fixed by the catalogue. With 4 known-defect mutants a 90% floor
    is arithmetically "all four" — 3/4 is 75% — which is the intent: a defect
    that already escaped once has no allowance left.
    """
    total_ids = _catalogue_ids_by_category("known_defect")
    hits = board.detected & total_ids
    rate = round(len(hits) / len(total_ids), 4) if total_ids else None
    return FloorResult(
        total=len(total_ids),
        detected=len(hits),
        rate=rate,
        floor=floor,
        passed=rate is not None and rate >= floor,
        missing=tuple(sorted(total_ids - hits)),
    )


# =============================================================================
# The ratchet
# =============================================================================


@dataclass(frozen=True)
class RatchetResult:
    regressions: tuple[str, ...]
    improvements: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.regressions and not self.improvements


def ratchet(board: Board, banked: dict[str, Any]) -> RatchetResult:
    """Two-way, on the three absolute id sets. See the module docstring for why."""
    regressions: list[str] = []
    improvements: list[str] = []

    def compare(name: str, now: frozenset[str], key: str, *, growth_is_good: bool) -> None:
        was = frozenset(banked.get(key, ()))
        gained = sorted(now - was)
        lost = sorted(was - now)
        worse, better = (lost, gained) if growth_is_good else (gained, lost)
        if worse:
            regressions.append(
                f"{board.ladder}: {name} regressed by {len(worse)} — {', '.join(worse)}"
            )
        if better:
            improvements.append(
                f"{board.ladder}: {name} improved by {len(better)} — {', '.join(better)}; "
                "bank it deliberately"
            )

    compare("DETECTED", board.detected, "detected_ids", growth_is_good=True)
    compare("ESCAPED", board.escaped, "escaped_ids", growth_is_good=False)
    compare("UNREACHABLE", board.unreachable, "unreachable_ids", growth_is_good=False)
    return RatchetResult(tuple(regressions), tuple(improvements))


# =============================================================================
# The board, as markdown
# =============================================================================


def render_summary(boards: dict[str, Board], baseline: dict[str, Any]) -> str:
    """The published artefact. Three verdicts stay distinct; timeouts are named."""
    floor = float(baseline.get("known_defect_floor", 0.9))
    lines: list[str] = [
        "## Defect-injection campaign",
        "",
        f"Measured {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} at `{_git_commit()}`.",
        "",
    ]

    unreadable = {ladder: trust_failures(board) for ladder, board in boards.items()}
    if any(unreadable.values()):
        lines += [
            "> **These numbers are not evidence.** At least one scorecard failed a trust",
            "> check, which means its verdicts cannot be believed in a known direction.",
            "> See *Trust checks* below. The ratchet fails for this reason alone.",
            "",
        ]

    # Only claim a before/after when both ladders are actually present: the
    # campaign job renders each leg's own board too, and one ladder cannot
    # answer whether the added gates were worth their cost.
    both = all(ladder in boards for ladder in REQUIRED_LADDERS)
    heading = (
        "### Headline — before (`legacy`) and after (`full`)"
        if both
        else "### Headline — "
        + ", ".join(f"`{ladder}`" for ladder in _ladder_order(boards))
        + " ladder only (no before/after pair)"
    )
    lines += [
        heading,
        "",
        "| Ladder | Mutants | Scored | DETECTED | ESCAPED | UNREACHABLE | Detection rate | Mean tier |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for ladder in _ladder_order(boards):
        board = boards[ladder]
        scored = len(board.detected) + len(board.escaped)
        rate = "n/a" if board.detection_rate is None else f"{board.detection_rate:.1%}"
        tier = "n/a" if board.mean_tier is None else f"{board.mean_tier}"
        lines.append(
            f"| `{ladder}` | {board.mutants_total} | {scored} | {len(board.detected)} | "
            f"{len(board.escaped)} | {len(board.unreachable)} | {rate} | {tier} |"
        )
    lines += [
        "",
        "`UNREACHABLE` is excluded from the rate's numerator and denominator — counting it",
        "either way is a lie in one direction or the other. The rate is REPORTED, not gated;",
        "the gate is on the absolute id sets (LESSONS B8).",
        "",
    ]

    lines += [f"### Known-defect floor (>= {floor:.0%} of the catalogue's known defects)", ""]
    for ladder in _ladder_order(boards):
        result = known_defect_floor(boards[ladder], floor)
        rate = "n/a" if result.rate is None else f"{result.rate:.0%}"
        verdict = "PASS" if result.passed else "FAIL"
        lines.append(f"- `{ladder}`: {result.detected}/{result.total} = {rate} — **{verdict}**")
        if result.missing:
            lines.append(f"  - not detected: {', '.join(f'`{m}`' for m in result.missing)}")
    lines.append("")

    lines += ["### ESCAPED — the deliverable", ""]
    escapes = [
        (ladder, row) for ladder in _ladder_order(boards) for row in boards[ladder].escaped_rows
    ]
    if escapes:
        lines += ["| Ladder | Mutant | Category | Defect |", "|---|---|---|---|"]
        lines += [
            f"| `{ladder}` | `{mutant_id}` | {category} | {summary} |"
            for ladder, (mutant_id, category, summary) in escapes
        ]
    else:
        lines.append("No escapes recorded. Read the trust checks before believing that.")
    lines.append("")

    lines += ["### UNREACHABLE — moved no observable output", ""]
    any_unreachable = False
    for ladder in _ladder_order(boards):
        for mutant_id in sorted(boards[ladder].unreachable):
            any_unreachable = True
            note = boards[ladder].notes.get(mutant_id, "")
            lines.append(f"- `{ladder}` `{mutant_id}`{f' — {note}' if note else ''}")
    if not any_unreachable:
        lines.append("None.")
    lines.append("")

    lines += ["### Trust checks", ""]
    if any(unreadable.values()):
        for ladder in _ladder_order(boards):
            for failure in unreadable[ladder]:
                lines.append(f"- **FAIL** {failure}")
    else:
        lines.append("- All scorecards complete, controls consistent, no gate timed out.")
    lines.append("")

    lines += ["### Where each detection happened", ""]
    for ladder in _ladder_order(boards):
        board = boards[ladder]
        if not board.caught_by:
            continue
        tally: dict[str, int] = {}
        for gate in board.caught_by.values():
            tally[gate] = tally.get(gate, 0) + 1
        rendered = ", ".join(f"{gate} {count}" for gate, count in sorted(tally.items()))
        lines.append(f"- `{ladder}` ({', '.join(board.gates)}): {rendered}")
    lines.append("")

    lines += [
        "### Ratchet",
        "",
        f"Baseline status: **{baseline.get('status', 'MISSING')}**"
        f" (`scripts/injection_baseline.json`).",
        "",
    ]
    if baseline.get("status") != STATUS_BANKED:
        lines += [
            "No baseline has ever been banked, so there is no detection rate to regress",
            "against. This is not a passing state — `--check` exits non-zero until the",
            "first campaign is measured and banked with:",
            "",
            f"```\n{BANK_COMMAND}\n```",
            "",
        ]
    return "\n".join(lines) + "\n"


def _ladder_order(boards: dict[str, Board]) -> list[str]:
    """`legacy` then `full` then anything else, so before precedes after."""
    known = [ladder for ladder in REQUIRED_LADDERS if ladder in boards]
    return known + sorted(set(boards) - set(known))


def _git_commit() -> str:
    proc = subprocess.run(
        ("git", "rev-parse", "--short", "HEAD"),
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() or "unknown"


# =============================================================================
# --check
# =============================================================================


def check(boards: dict[str, Board], baseline: dict[str, Any]) -> int:
    """Report everything, then exit non-zero if anything failed.

    Deliberately not fail-fast: the first manual run needs to see the trust
    checks, the floor and the ratchet in one pass, or banking becomes a
    guess-and-retry loop.
    """
    failures: list[str] = []
    floor = float(baseline.get("known_defect_floor", 0.9))

    print("=" * 78)
    print("DEFECT-INJECTION DETECTION-RATE RATCHET")
    print("=" * 78)
    for ladder in _ladder_order(boards):
        board = boards[ladder]
        print(f"  {ladder:<8} {board.path.name}")
        print(f"           interpreter {board.interpreter!r}  gates {list(board.gates)}")
        rate = "n/a" if board.detection_rate is None else f"{board.detection_rate:.1%}"
        print(
            f"           detected {len(board.detected)}  escaped {len(board.escaped)}  "
            f"unreachable {len(board.unreachable)}  rate {rate} (reported, not gated)"
        )

    missing_ladders = [ladder for ladder in REQUIRED_LADDERS if ladder not in boards]
    if missing_ladders:
        failures.append(
            f"no scorecard for ladder(s) {', '.join(missing_ladders)}. The before/after pair "
            "from one build is the point of running two ladders; a single-ladder run cannot "
            "answer whether the added gates were worth their cost."
        )

    print("\n  TRUST")
    trust_clean = True
    untrusted: set[str] = set()
    for ladder in _ladder_order(boards):
        for failure in trust_failures(boards[ladder]):
            trust_clean = False
            untrusted.add(ladder)
            failures.append(failure)
            print(f"    FAIL {failure}")
    if trust_clean:
        print("    ok — every catalogue mutant scored, controls consistent, no timeouts")

    print(f"\n  KNOWN-DEFECT FLOOR (>= {floor:.0%}, denominator from the catalogue)")
    for ladder in _ladder_order(boards):
        result = known_defect_floor(boards[ladder], floor)
        rate = "n/a" if result.rate is None else f"{result.rate:.0%}"
        print(
            f"    {ladder:<8} {result.detected}/{result.total} = {rate}  "
            f"{'ok' if result.passed else 'FAIL'}"
        )
        if not result.passed:
            failures.append(
                f"{ladder}: known-defect detection {result.detected}/{result.total} is below "
                f"the {floor:.0%} floor. Not detected: {', '.join(result.missing)}. These "
                "defects have already escaped once."
            )

    print("\n  RATCHET")
    status = baseline.get("status")
    if status == STATUS_UNBANKED:
        print(_unbanked_banner(baseline))
        failures.append(
            "no baseline banked — run the campaign and bank it. "
            f"scripts/injection_baseline.json carries status={STATUS_UNBANKED!r}, so there is "
            "no previous detection rate to compare against and nothing is being gated. "
            f"Bank with: {BANK_COMMAND}"
        )
    elif status == STATUS_BANKED:
        banked_ladders = baseline.get("ladders", {})
        for ladder in _ladder_order(boards):
            # An untrustworthy scorecard's verdict SETS are not comparable to
            # anything. Comparing them anyway produces a wall of derived
            # "regressions" that buries the one finding that matters, and — worse
            # — reports the broken half as "improved, bank it deliberately".
            if ladder in untrusted:
                print(
                    f"    {ladder:<8} SKIPPED — failed its trust checks above, sets not comparable"
                )
                continue
            if ladder not in banked_ladders:
                failures.append(
                    f"{ladder}: the baseline is banked but holds no entry for this ladder. "
                    f"Re-bank both ladders together: {BANK_COMMAND}"
                )
                print(f"    {ladder:<8} FAIL not in the banked baseline")
                continue
            result = ratchet(boards[ladder], banked_ladders[ladder])
            for line in result.regressions:
                failures.append(line)
                print(f"    FAIL {line}")
            for line in result.improvements:
                failures.append(line)
                print(f"    BANK REQUIRED {line}")
            if result.passed:
                print(f"    {ladder:<8} ok — every banked set held exactly")
    else:
        failures.append(
            f"scripts/injection_baseline.json has status={status!r}; expected "
            f"{STATUS_UNBANKED!r} or {STATUS_BANKED!r}. An unrecognised status is treated as "
            "un-banked, never as banked, so a typo cannot read as a green gate."
        )
        print(f"    FAIL unrecognised baseline status {status!r}")

    print()
    print("=" * 78)
    if failures:
        print(f"RATCHET FAILED — {len(failures)} finding(s)")
        for failure in failures:
            print(f"  - {failure}")
        print("=" * 78)
        return 1
    print("RATCHET PASSED")
    print("=" * 78)
    return 0


def _unbanked_banner(baseline: dict[str, Any]) -> str:
    lines = [
        "    " + "-" * 70,
        "    NO BASELINE BANKED — RUN THE CAMPAIGN AND BANK IT",
        "    " + "-" * 70,
    ]
    reason = baseline.get("unbanked_reason")
    if reason:
        lines += [f"    {line}" for line in _wrap(reason, 70)]
    for blocker in baseline.get("blockers", ()):
        lines.append("")
        lines.append(f"    BLOCKER {blocker.get('task', '?')}")
        lines += [f"      {line}" for line in _wrap(blocker.get("summary", ""), 68)]
        if blocker.get("state"):
            wrapped = _wrap(blocker["state"], 61)
            lines.append(f"      state: {wrapped[0]}")
            lines += [f"             {line}" for line in wrapped[1:]]
    lines += [
        "",
        "    Bank the first baseline with:",
        f"      {BANK_COMMAND}",
        "    " + "-" * 70,
    ]
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        if current and len(" ".join([*current, word])) > width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


# =============================================================================
# --bank
# =============================================================================


def bank(boards: dict[str, Board], baseline_path: Path, note: str) -> int:
    """Write the first (or a later) baseline. Refuses an untrustworthy scorecard.

    A baseline banked from a scorecard that failed a trust check would enshrine
    fiction as the thing every future run is measured against, so banking runs
    the same trust checks the gate does and refuses on any of them.
    """
    missing_ladders = [ladder for ladder in REQUIRED_LADDERS if ladder not in boards]
    if missing_ladders:
        print(f"refusing to bank: no scorecard for {', '.join(missing_ladders)}")
        return 1

    blocking = [failure for board in boards.values() for failure in trust_failures(board)]
    if blocking:
        print("refusing to bank — these scorecards cannot be trusted:")
        for failure in blocking:
            print(f"  - {failure}")
        return 1

    existing = json.loads(baseline_path.read_text(encoding="utf-8"))
    payload = {
        "_comment": existing["_comment"],
        "status": STATUS_BANKED,
        "_note": note,
        "known_defect_floor": existing.get("known_defect_floor", 0.9),
        "bank_command": BANK_COMMAND,
        "provenance": {
            "banked_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "git_commit": _git_commit(),
            "catalogue_mutants": len(CATALOGUE),
            "ladders": {
                ladder: {
                    "interpreter": boards[ladder].interpreter,
                    "gates": list(boards[ladder].gates),
                    "runtime_seconds": boards[ladder].runtime_seconds,
                    "detection_rate_reported": boards[ladder].detection_rate,
                    "mean_tier_of_detection": boards[ladder].mean_tier,
                }
                for ladder in _ladder_order(boards)
            },
        },
        "ladders": {
            ladder: {
                "detected_ids": sorted(boards[ladder].detected),
                "escaped_ids": sorted(boards[ladder].escaped),
                "unreachable_ids": sorted(boards[ladder].unreachable),
            }
            for ladder in _ladder_order(boards)
        },
    }
    baseline_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Banked {baseline_path.name} over {len(boards)} ladder(s):")
    for ladder in _ladder_order(boards):
        board = boards[ladder]
        print(
            f"  {ladder:<8} detected {len(board.detected)}  escaped {len(board.escaped)}  "
            f"unreachable {len(board.unreachable)}"
        )
    return 0


# =============================================================================
# Entry point
# =============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detection-rate ratchet for the defect-injection campaign (S.3)"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check", action="store_true", help="the gate; exits non-zero on any finding"
    )
    mode.add_argument("--summary", action="store_true", help="render markdown; NOT a gate")
    mode.add_argument("--bank", action="store_true", help="write the baseline from the scorecards")
    parser.add_argument(
        "--scorecard",
        action="append",
        type=Path,
        required=True,
        metavar="PATH",
        help="a defect_injection.py scorecard JSON; repeat once per ladder",
    )
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--out", type=Path, default=None, help="--summary only: markdown output")
    parser.add_argument(
        "--note",
        default="",
        help="--bank only: why this baseline moved. Recorded as _note; required.",
    )
    args = parser.parse_args()

    # Confine every operator-supplied path BEFORE it reaches a read or a write, so
    # each downstream `read_text` / `write_text` / `mkdir` provably operates on a
    # path inside the repository. One choke point, because a containment check
    # cannot be partially applied.
    #
    # The confined values are bound to LOCALS and only the locals are used below.
    # Writing them back onto `args` instead would be equivalent at runtime but is
    # NOT equivalent to a taint analyser: assigning through an attribute of the
    # argparse Namespace leaves `args.baseline` looking like the raw CLI source at
    # every later use, so the sanitiser goes unrecognised and the finding stays
    # open. Measured — the first attempt at this fix did exactly that and
    # pythonsecurity:S2083 survived it. Keep the dataflow
    # `tainted -> _confine_path -> local -> sink` visible and unbroken.
    scorecard_paths = [_confine_path(path) for path in args.scorecard]
    baseline_path = _confine_path(args.baseline)
    out_path = _confine_path(args.out) if args.out is not None else None

    for path in scorecard_paths:
        if not path.exists():
            print(f"scorecard does not exist: {path}", file=sys.stderr)
            return 1
    if not baseline_path.exists():
        print(f"baseline does not exist: {baseline_path}", file=sys.stderr)
        return 1

    boards = load_boards(scorecard_paths)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    if args.bank:
        if not args.note.strip():
            print("--bank requires --note explaining why the baseline moved", file=sys.stderr)
            return 1
        return bank(boards, baseline_path, args.note.strip())

    if args.summary:
        markdown = render_summary(boards, baseline)
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(markdown, encoding="utf-8")
            print(f"wrote {out_path}")
        else:
            print(markdown)
        return 0

    return check(boards, baseline)


if __name__ == "__main__":
    raise SystemExit(main())
