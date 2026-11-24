"""
The defect-injection ratchet gate: every finding kind goes red alone, a clean pair goes green.

Pipeline position:
    (no pipeline stage — a contract on ``scripts/injection_ratchet.py``, the last
    step of the ``Nightly Defect Injection`` workflow, whose exit code is the job)

``check()`` is the gate. It requires both ladders and reports four groups of
findings — trust, the known-defect floor, the baseline's status, and (once
banked) the two-way set ratchet per ladder — and exits non-zero if any fired. Until this
file nothing called ``check()``, ``ratchet()``, ``known_defect_floor()`` or
``render_summary()``, and until the first bank (from the 2026-11-23 nightly's
scorecards) the committed baseline was ``UNBANKED``, so the nightly could not
reach the ``BANKED`` branch or the return-0 path either. A gate that has never
been seen to pass cannot be shown to tell a good run from a bad one
(``.claude/LESSONS.md`` B9), and a gate whose branches have never been seen to
fire can lose one silently in a refactor. A banked nightly still only ever shows
the branches its own campaign happens to reach — on a clean night, none of the
``BANKED`` findings.

So this pins both halves, on synthetic ``Board`` objects with no pipeline run:

- a trust-clean, floor-clean ``BANKED`` pair whose sets equal the baseline returns
  0 — the state no nightly reached before the first bank;
- each of the 18 finding kinds, perturbed ALONE on top of that clean pair, returns
  1 with exactly one finding that names it — per ladder where the check is per
  ladder, so a check that only ever looked at one ladder fails too. The
  unrecognised status is reached two ways, a wrong value and no ``status`` key
  at all, because reading an absent status as ``BANKED`` is the quiet direction;
- the floor is read from the baseline (a missing key means 90%), and a set
  missing from a banked entry reads as empty, never as the board's own set;
- the gate is not fail-fast, and an untrusted ladder's sets are skipped while the
  other ladder is still compared - its missing baseline entry too - and a banked
  baseline with no ``ladders`` key is one missing-entry finding per ladder;
- a known defect with no DETECTED verdict - UNREACHABLE, another verdict, or none -
  fails the floor as well as trust: the floor's denominator is the catalogue, not
  the scored pool the headline rate uses, and trust alone would hide the loss;
- ``--summary`` publishes every section, in order, with its content - each
  per-ladder section on BOTH ladders, ``legacy`` first - and its alarms
  discriminate: the not-evidence banner and the trust all-clear are each run on
  a clean pair, on each ladder failing trust alone, and on both failing, and
  must differ between the clean case and each failing one (``.claude/LESSONS.md``
  B9). Its quiet branches - no
  unreachable mutant, a ladder that caught nothing, a floor with every known
  defect detected - are pinned exactly too. A floor that passes while still
  missing a known defect is not quiet: it names the defect, and that is pinned.

The number 18 is not asserted anywhere: a count of checks still passes when one
of them is changed to return nothing. Each case asserting its own finding is
what makes a lost check red.

References:
- scripts/injection_ratchet.py — ``check``, ``render_summary``
- docs/development/defect-injection.md — "The ratchet, and its baseline"
- .claude/LESSONS.md B9 — a gate must be seen to pass and to fail
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from scripts import injection_ratchet
from scripts.defect_catalogue import CATALOGUE
from scripts.injection_ratchet import (
    STATUS_BANKED,
    STATUS_UNBANKED,
    VERDICT_DETECTED,
    VERDICT_ESCAPED,
    VERDICT_UNREACHABLE,
    Board,
)

_LADDERS = ("legacy", "full")
_SUMMARIES = {mutant.id: (mutant.category, mutant.summary) for mutant in CATALOGUE}
_ALL_IDS = frozenset(_SUMMARIES)
_KNOWN_DEFECTS = sorted(m.id for m in CATALOGUE if m.category == "known_defect")
_DEAD_BY_DESIGN = sorted(m.id for m in CATALOGUE if m.expect_unreachable)
_LIVE = sorted(m.id for m in CATALOGUE if m.category != "known_defect" and not m.expect_unreachable)
_FLOOR = 0.9

#: A known defect, a mutant flagged expect_unreachable, and an ordinary live one.
#: Chosen from the catalogue by property so a catalogue edit cannot silently turn
#: a case into a different one.
_KNOWN = _KNOWN_DEFECTS[0]
_CONTROL = _DEAD_BY_DESIGN[0]
_LIVE_ID = _LIVE[0]


# =============================================================================
# The clean pair, and the one state no nightly reached before the first bank
# =============================================================================


def test_the_catalogue_supports_a_clean_board() -> None:
    """The cases below rely on these three populations existing and being disjoint."""
    # Arrange
    known, dead = set(_KNOWN_DEFECTS), set(_DEAD_BY_DESIGN)

    # Act
    overlap = known & dead

    # Assert
    assert known, "no known_defect mutant - the floor cases would test nothing"
    assert dead, "no expect_unreachable mutant - the control cases would test nothing"
    assert _LIVE, "no ordinary live mutant to perturb"
    assert not overlap, f"a known defect flagged expect_unreachable fails the floor: {overlap}"
    assert _FLOOR * len(known) > len(known) - 1, "one missed known defect must breach the floor"


def test_check_passes_a_clean_banked_pair(capsys: pytest.CaptureFixture[str]) -> None:
    """Both ladders trusted, every known defect caught, sets equal to the banked baseline."""
    # Arrange
    boards, baseline = _clean()

    # Act
    rc = injection_ratchet.check(boards, baseline)
    out = capsys.readouterr().out

    # Assert
    assert rc == 0, out
    assert "RATCHET PASSED" in out
    for ladder in _LADDERS:
        assert f"{ladder:<8} ok — every banked set held exactly" in out


# =============================================================================
# Every finding kind, alone
# =============================================================================


@dataclass(frozen=True)
class _Case:
    """One finding kind: how to perturb the clean pair, and the finding it must raise."""

    kind: str
    arrange: Callable[[str], tuple[dict[str, Board], dict[str, Any]]]
    finding: Callable[[str], str]
    per_ladder: bool = True


def _perturb_board(
    change: Callable[[Board], Board], *, rebank: bool = False
) -> Callable[[str], tuple[dict[str, Board], dict[str, Any]]]:
    """Change one ladder's board; bank the baseline before (default) or after."""

    def arrange(ladder: str) -> tuple[dict[str, Board], dict[str, Any]]:
        boards, baseline = _clean()
        boards[ladder] = change(boards[ladder])
        return boards, _bank(boards) if rebank else baseline

    return arrange


def _perturb_banked(
    key: str, edit: Callable[[set[str]], set[str]], board: Callable[[Board], Board] | None = None
) -> Callable[[str], tuple[dict[str, Board], dict[str, Any]]]:
    """Move one banked set of one ladder; optionally change that ladder's board first."""

    def arrange(ladder: str) -> tuple[dict[str, Board], dict[str, Any]]:
        boards, _ = _clean()
        if board is not None:
            boards[ladder] = board(boards[ladder])
        baseline = _bank(boards)
        entry = baseline["ladders"][ladder]
        entry[key] = sorted(edit(set(entry[key])))
        return boards, baseline

    return arrange


def _without_ladder(ladder: str) -> tuple[dict[str, Board], dict[str, Any]]:
    boards, baseline = _clean()
    del boards[ladder]
    return boards, baseline


def _banked_without_ladder(ladder: str) -> tuple[dict[str, Board], dict[str, Any]]:
    boards, baseline = _clean()
    del baseline["ladders"][ladder]
    return boards, baseline


def _without_status(_ladder: str) -> tuple[dict[str, Board], dict[str, Any]]:
    boards, baseline = _clean()
    del baseline["status"]
    return boards, baseline


def _with_status(status: str) -> Callable[[str], tuple[dict[str, Board], dict[str, Any]]]:
    def arrange(_ladder: str) -> tuple[dict[str, Board], dict[str, Any]]:
        boards, baseline = _clean()
        baseline["status"] = status
        return boards, baseline

    return arrange


_CASES: tuple[_Case, ...] = (
    # --- the before/after pair ------------------------------------------------
    _Case(
        "ladder-missing",
        _without_ladder,
        lambda ladder: f"no scorecard for ladder(s) {ladder}.",
    ),
    # --- trust (an untrusted ladder's sets are skipped, so each stands alone) --
    _Case(
        "trust-unscored-mutant",
        _perturb_board(lambda b: _drop(b, _LIVE_ID)),
        lambda ladder: f"{ladder}: 1 catalogue mutant carrying no verdict ({_LIVE_ID})",
    ),
    _Case(
        "trust-unknown-mutant",
        _perturb_board(lambda b: _move(b, "not-in-the-catalogue", VERDICT_DETECTED)),
        lambda ladder: f"{ladder}: verdicts for 1 mutant that are not in the catalogue",
    ),
    _Case(
        "trust-control-came-back-reachable",
        _perturb_board(lambda b: _move(b, _CONTROL, VERDICT_DETECTED)),
        lambda ladder: (
            f"{ladder}: 1 mutant flagged expect_unreachable came back reachable ({_CONTROL})"
        ),
    ),
    _Case(
        "trust-live-mutant-moved-nothing",
        _perturb_board(lambda b: _move(b, _LIVE_ID, VERDICT_UNREACHABLE)),
        lambda ladder: f"{ladder}: 1 mutant expected to be reachable moved nothing ({_LIVE_ID})",
    ),
    _Case(
        "trust-gate-timeout",
        _perturb_board(lambda b: replace(b, timeouts={_LIVE_ID: ["unit"]})),
        lambda ladder: f"{ladder}: 1 mutant had a gate TIME OUT ({_LIVE_ID} [unit])",
    ),
    _Case(
        "trust-other-verdict",
        _perturb_board(lambda b: _move(b, _LIVE_ID, "ERROR")),
        lambda ladder: (
            f"{ladder}: 1 mutant carrying a verdict that is neither DETECTED, ESCAPED nor "
            f"UNREACHABLE ({_LIVE_ID}=ERROR)"
        ),
    ),
    _Case(
        "trust-no-interpreter",
        _perturb_board(lambda b: replace(b, interpreter="")),
        lambda ladder: f"{ladder}: the scorecard records no interpreter",
    ),
    # --- the known-defect floor (banked AFTER the miss, so the ratchet holds) --
    _Case(
        "floor-known-defect-missed",
        _perturb_board(lambda b: _move(b, _KNOWN, VERDICT_ESCAPED), rebank=True),
        lambda ladder: (
            f"{ladder}: known-defect detection {len(_KNOWN_DEFECTS) - 1}/{len(_KNOWN_DEFECTS)} "
            f"is below the 90% floor. Not detected: {_KNOWN}."
        ),
    ),
    # --- the baseline's status ------------------------------------------------
    _Case(
        "baseline-unbanked",
        _with_status(STATUS_UNBANKED),
        lambda _ladder: "no baseline banked — run the campaign and bank it.",
        per_ladder=False,
    ),
    _Case(
        "baseline-status-unrecognised",
        _with_status("banked"),
        lambda _ladder: "scripts/injection_baseline.json has status='banked'",
        per_ladder=False,
    ),
    _Case(  # the same finding, reached with no status at all: never read as BANKED
        "baseline-status-absent",
        _without_status,
        lambda _ladder: "scripts/injection_baseline.json has status=None",
        per_ladder=False,
    ),
    _Case(
        "baseline-banked-without-this-ladder",
        _banked_without_ladder,
        lambda ladder: f"{ladder}: the baseline is banked but holds no entry for this ladder.",
    ),
    # --- the two-way set ratchet: three regressions ----------------------------
    _Case(
        "ratchet-detected-lost",
        _perturb_banked("detected_ids", lambda s: s | {_CONTROL}),
        lambda ladder: f"{ladder}: DETECTED regressed by 1 — {_CONTROL}",
    ),
    _Case(
        "ratchet-escaped-gained",
        _perturb_banked(
            "escaped_ids",
            lambda s: s - {_LIVE_ID},
            board=lambda b: _move(b, _LIVE_ID, VERDICT_ESCAPED),
        ),
        lambda ladder: f"{ladder}: ESCAPED regressed by 1 — {_LIVE_ID}",
    ),
    _Case(
        "ratchet-unreachable-gained",
        _perturb_banked("unreachable_ids", lambda s: s - {_CONTROL}),
        lambda ladder: f"{ladder}: UNREACHABLE regressed by 1 — {_CONTROL}",
    ),
    # --- ...and three improvements, which fail too until banked (BANK REQUIRED) -
    _Case(
        "ratchet-detected-gained",
        _perturb_banked("detected_ids", lambda s: s - {_LIVE_ID}),
        lambda ladder: f"{ladder}: DETECTED improved by 1 — {_LIVE_ID}; bank it deliberately",
    ),
    _Case(
        "ratchet-escaped-lost",
        _perturb_banked("escaped_ids", lambda s: s | {_LIVE_ID}),
        lambda ladder: f"{ladder}: ESCAPED improved by 1 — {_LIVE_ID}; bank it deliberately",
    ),
    _Case(
        "ratchet-unreachable-lost",
        _perturb_banked("unreachable_ids", lambda s: s | {_LIVE_ID}),
        lambda ladder: f"{ladder}: UNREACHABLE improved by 1 — {_LIVE_ID}; bank it deliberately",
    ),
)

_PARAMS = [
    pytest.param(case, ladder, id=f"{case.kind}-{ladder}" if case.per_ladder else case.kind)
    for case in _CASES
    for ladder in (_LADDERS if case.per_ladder else _LADDERS[:1])
]


@pytest.mark.parametrize(("case", "ladder"), _PARAMS)
def test_check_fails_on_each_finding_kind_alone(
    capsys: pytest.CaptureFixture[str], case: _Case, ladder: str
) -> None:
    """One perturbation of the clean pair -> exit 1 and exactly that one finding."""
    # Arrange
    boards, baseline = case.arrange(ladder)
    expected = case.finding(ladder)

    # Act
    rc = injection_ratchet.check(boards, baseline)
    out = capsys.readouterr().out
    findings = _findings(out)

    # Assert
    assert rc == 1, out
    assert len(findings) == 1, f"expected exactly one finding, got {findings}"
    assert expected in findings[0], f"{expected!r} not in {findings[0]!r}"


# =============================================================================
# How the groups combine
# =============================================================================


def test_check_reports_every_group_in_one_pass(capsys: pytest.CaptureFixture[str]) -> None:
    """Not fail-fast: a missing ladder, a trust failure, a floor miss and the status, together."""
    # Arrange
    boards, baseline = _clean()
    boards["legacy"] = replace(boards["legacy"], interpreter="")
    del boards["full"]
    boards["legacy"] = _move(boards["legacy"], _KNOWN, VERDICT_ESCAPED)
    baseline["status"] = STATUS_UNBANKED

    # Act
    rc = injection_ratchet.check(boards, baseline)
    findings = _findings(capsys.readouterr().out)

    # Assert
    assert rc == 1
    assert _kinds(findings) == [
        "no scorecard for ladder(s) full.",
        "legacy: the scorecard records no interpreter",
        "legacy: known-defect detection",
        "no baseline banked",
    ], findings


def test_an_untrusted_ladder_is_skipped_while_the_other_is_compared(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """legacy's set move is NOT reported (its sets are fiction); full's still is."""
    # Arrange
    boards, _ = _clean()
    boards["legacy"] = replace(boards["legacy"], interpreter="")
    baseline = _bank(boards)
    for ladder in _LADDERS:
        entry = baseline["ladders"][ladder]
        entry["detected_ids"] = sorted({*entry["detected_ids"], _CONTROL})

    # Act
    rc = injection_ratchet.check(boards, baseline)
    out = capsys.readouterr().out
    findings = _findings(out)

    # Assert
    assert rc == 1
    assert _kinds(findings) == [
        "legacy: the scorecard records no interpreter",
        f"full: DETECTED regressed by 1 — {_CONTROL}",
    ], findings
    assert "legacy   SKIPPED — failed its trust checks above" in out


@pytest.mark.parametrize("ladder", _LADDERS)
def test_an_untrusted_ladder_missing_from_the_baseline_adds_no_baseline_finding(
    capsys: pytest.CaptureFixture[str], ladder: str
) -> None:
    """The trust skip comes before the baseline-entry lookup, so only trust is reported.

    The missing entry still fails the gate once the ladder is trusted again (the
    ``baseline-banked-without-this-ladder`` case); moving the skip below the lookup
    adds a second, derived finding here.
    """
    # Arrange
    boards, _ = _clean()
    boards[ladder] = replace(boards[ladder], interpreter="")
    baseline = _bank(boards)
    del baseline["ladders"][ladder]

    # Act
    rc = injection_ratchet.check(boards, baseline)
    out = capsys.readouterr().out
    findings = _findings(out)

    # Assert
    assert rc == 1
    assert len(findings) == 1, findings
    assert findings[0].startswith(f"{ladder}: the scorecard records no interpreter"), findings
    assert f"{ladder:<8} SKIPPED — failed its trust checks above" in out


def test_a_banked_baseline_with_no_ladders_key_fails_each_ladder(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No ``ladders`` key reads as no entries: one finding per ladder, never a crash."""
    # Arrange
    boards, baseline = _clean()
    del baseline["ladders"]

    # Act
    rc = injection_ratchet.check(boards, baseline)
    findings = _findings(capsys.readouterr().out)

    # Assert
    assert rc == 1
    assert len(findings) == len(_LADDERS), findings
    assert all(
        finding.startswith(f"{ladder}: the baseline is banked but holds no entry for this ladder.")
        for finding, ladder in zip(findings, _LADDERS, strict=True)
    ), findings


@pytest.mark.parametrize("ladder", _LADDERS)
@pytest.mark.parametrize(
    ("unscore", "trust_finding"),
    [
        pytest.param(
            lambda b: _move(b, _KNOWN, VERDICT_UNREACHABLE),
            f"1 mutant expected to be reachable moved nothing ({_KNOWN})",
            id="unreachable",
        ),
        pytest.param(
            lambda b: _move(b, _KNOWN, "ERROR"),
            "1 mutant carrying a verdict that is neither DETECTED, ESCAPED nor UNREACHABLE",
            id="other-verdict",
        ),
        pytest.param(
            lambda b: _drop(b, _KNOWN),
            f"1 catalogue mutant carrying no verdict ({_KNOWN})",
            id="no-verdict",
        ),
    ],
)
def test_a_known_defect_without_a_verdict_counts_against_the_floor(
    capsys: pytest.CaptureFixture[str],
    unscore: Callable[[Board], Board],
    trust_finding: str,
    ladder: str,
) -> None:
    """The floor's denominator is the catalogue, not the scored pool the headline rate uses.

    So a known defect that is UNREACHABLE, carries another verdict, or never ran
    misses the floor as well as failing trust. The trust finding alone would
    keep the exit code at 1, which is why both findings are asserted: a floor
    over ``detected | escaped``, or one counting UNREACHABLE as a hit, loses the
    second (``scripts/injection_ratchet.py`` module docstring, "Why the
    known-defect floor uses a fixed denominator").
    """
    # Arrange
    boards, _ = _clean()
    boards[ladder] = unscore(boards[ladder])
    baseline = _bank(boards)
    total = len(_KNOWN_DEFECTS)

    # Act
    rc = injection_ratchet.check(boards, baseline)
    findings = _findings(capsys.readouterr().out)

    # Assert
    assert rc == 1
    assert len(findings) == 2, findings
    assert findings[0].startswith(f"{ladder}: {trust_finding}"), findings
    assert findings[1].startswith(
        f"{ladder}: known-defect detection {total - 1}/{total} is below the 90% floor. "
        f"Not detected: {_KNOWN}."
    ), findings


@pytest.mark.parametrize(
    ("floor", "passes"),
    [
        pytest.param(None, False, id="absent-means-90"),
        pytest.param(0.5, True, id="0.5"),
        pytest.param(0.75, True, id="0.75-is-met-exactly"),
        pytest.param(0.8, False, id="0.8"),
    ],
)
def test_the_floor_is_read_from_the_baseline(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    floor: float | None,
    passes: bool,
) -> None:
    """One known defect missed is 3/4 = 75%: the baseline's floor decides, in both outputs.

    A floor hardcoded at 90% fails the 0.5 and 0.75 cases; a missing key read as
    anything but 90% (0, say, which no run could breach) fails the first. The
    summary names the missed defect whether the floor passes or fails: a pass is
    not "nothing missed", so the 0.5 and 0.75 cases fail a renderer that gates
    the "not detected" line on the verdict instead of on what was missed.
    """
    # Arrange
    monkeypatch.setattr(injection_ratchet, "_git_commit", lambda: "abc1234")
    boards, _ = _clean()
    boards["full"] = _move(boards["full"], _KNOWN, VERDICT_ESCAPED)
    baseline = _bank(boards)
    if floor is None:
        del baseline["known_defect_floor"]
    else:
        baseline["known_defect_floor"] = floor
    applied = 0.9 if floor is None else floor
    total = len(_KNOWN_DEFECTS)

    # Act
    rc = injection_ratchet.check(boards, baseline)
    findings = _findings(capsys.readouterr().out)
    markdown = injection_ratchet.render_summary(boards, baseline)

    # Assert
    floor_lines = _section(
        markdown, f"### Known-defect floor (>= {applied:.0%} of the catalogue's known defects)"
    )
    assert rc == (0 if passes else 1), findings
    if passes:
        assert findings == []
    else:
        assert len(findings) == 1, findings
        assert findings[0].startswith(
            f"full: known-defect detection {total - 1}/{total} is below the {applied:.0%} floor."
        ), findings
    assert floor_lines == [
        f"- `legacy`: {total}/{total} = 100% — **PASS**",
        f"- `full`: {total - 1}/{total} = 75% — **{'PASS' if passes else 'FAIL'}**",
        f"  - not detected: `{_KNOWN}`",
    ], floor_lines


@pytest.mark.parametrize("ladder", _LADDERS)
@pytest.mark.parametrize(
    ("key", "finding"),
    [
        pytest.param(
            "detected_ids",
            lambda ladder: (
                f"{ladder}: DETECTED improved by {len(_ALL_IDS) - len(_DEAD_BY_DESIGN)} — "
            ),
            id="detected",
        ),
        pytest.param(
            "unreachable_ids",
            lambda ladder: f"{ladder}: UNREACHABLE regressed by {len(_DEAD_BY_DESIGN)} — ",
            id="unreachable",
        ),
    ],
)
def test_a_banked_entry_missing_a_set_is_compared_against_an_empty_set(
    capsys: pytest.CaptureFixture[str], key: str, finding: Callable[[str], str], ladder: str
) -> None:
    """A set missing from a banked entry reads as empty, never as 'whatever the board holds'.

    So everything the board holds in that set is reported as movement. Read as
    the board's own set instead, a partly banked entry would pass silently.
    """
    # Arrange
    boards, baseline = _clean()
    del baseline["ladders"][ladder][key]

    # Act
    rc = injection_ratchet.check(boards, baseline)
    findings = _findings(capsys.readouterr().out)

    # Assert
    assert rc == 1
    assert len(findings) == 1, findings
    assert findings[0].startswith(finding(ladder)), findings


# =============================================================================
# --summary: the published artefact
# =============================================================================

_NOT_EVIDENCE = "> **These numbers are not evidence.**"
_ALL_CLEAR = "- All scorecards complete, controls consistent, no gate timed out."

_SECTIONS = [
    "### Known-defect floor (>= 90% of the catalogue's known defects)",
    "### ESCAPED — the deliverable",
    "### UNREACHABLE — moved no observable output",
    "### Trust checks",
    "### Where each detection happened",
    "### Ratchet",
]


@pytest.mark.parametrize(
    ("ladders", "headline"),
    [
        pytest.param(_LADDERS, "### Headline — before (`legacy`) and after (`full`)", id="pair"),
        pytest.param(
            ("full",), "### Headline — `full` ladder only (no before/after pair)", id="one-ladder"
        ),
    ],
)
def test_summary_publishes_every_section_in_order(
    monkeypatch: pytest.MonkeyPatch, ladders: tuple[str, ...], headline: str
) -> None:
    """Dropping a section publishes less without any error, so the list is pinned exactly."""
    # Arrange
    monkeypatch.setattr(injection_ratchet, "_git_commit", lambda: "abc1234")
    boards, baseline = _clean()
    boards = {ladder: boards[ladder] for ladder in ladders}

    # Act
    markdown = injection_ratchet.render_summary(boards, baseline)

    # Assert
    headings = [line for line in markdown.splitlines() if line.startswith("#")]
    assert headings == ["## Defect-injection campaign", headline, *_SECTIONS]


def test_summary_carries_each_sections_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """Something in every section on BOTH ladders: each section must publish each, legacy first.

    Every per-ladder section is given a line on each ladder, so a renderer that
    skips one ladder - or only ever looked at the first - loses a line here.
    """
    # Arrange
    monkeypatch.setattr(injection_ratchet, "_git_commit", lambda: "abc1234")
    boards, _ = _clean()
    legacy = _move(boards["legacy"], _LIVE_ID, VERDICT_ESCAPED)
    boards["legacy"] = replace(legacy, timeouts={_LIVE_ID: ["unit"]})
    full = _move(boards["full"], _KNOWN, VERDICT_ESCAPED)
    boards["full"] = replace(full, interpreter="", notes={_CONTROL: "the control, as designed"})
    baseline = {"status": STATUS_UNBANKED, "known_defect_floor": _FLOOR}
    total, dead = len(_KNOWN_DEFECTS), len(_DEAD_BY_DESIGN)
    caught = {ladder: len(boards[ladder].detected) for ladder in _LADDERS}

    # Act
    markdown = injection_ratchet.render_summary(boards, baseline)

    # Assert
    shared = [
        "Measured ",
        _NOT_EVIDENCE,
        f"Baseline status: **{STATUS_UNBANKED}** (`scripts/injection_baseline.json`).",
        injection_ratchet.BANK_COMMAND,
    ]
    per_ladder = [  # (legacy line, full line), one pair per section
        tuple(
            f"| `{ladder}` | {len(CATALOGUE)} | {caught[ladder] + 1} | {caught[ladder]} | 1 | "
            f"{dead} | 100.0% | 1.0 |"
            for ladder in _LADDERS
        ),
        (
            f"- `legacy`: {total}/{total} = 100% — **PASS**",
            f"- `full`: {total - 1}/{total} = {(total - 1) / total:.0%} — **FAIL**\n"
            f"  - not detected: `{_KNOWN}`",
        ),
        tuple(
            f"| `{ladder}` | `{mutant}` | {_SUMMARIES[mutant][0]} | {_SUMMARIES[mutant][1]} |"
            for ladder, mutant in (("legacy", _LIVE_ID), ("full", _KNOWN))
        ),
        (f"- `legacy` `{_CONTROL}`\n", f"- `full` `{_CONTROL}` — the control, as designed"),
        (
            f"- **FAIL** legacy: 1 mutant had a gate TIME OUT ({_LIVE_ID} [unit])",
            "- **FAIL** full: the scorecard records no interpreter",
        ),
        tuple(f"- `{ladder}` (unit, contracts): unit {caught[ladder]}\n" for ladder in _LADDERS),
    ]
    missing = [
        line
        for line in [*shared, *(x for pair in per_ladder for x in pair)]
        if line not in markdown
    ]
    assert not missing, f"absent from the summary: {missing}\n\n{markdown}"
    assert _ALL_CLEAR not in markdown, "the trust all-clear printed under FAIL lines"
    out_of_order = [
        pair for pair in per_ladder if markdown.index(pair[0]) > markdown.index(pair[1])
    ]
    assert not out_of_order, f"full published before legacy: {out_of_order}"


@pytest.mark.parametrize(
    ("status", "shown", "states_bank_command"),
    [
        (STATUS_BANKED, STATUS_BANKED, False),
        (STATUS_UNBANKED, STATUS_UNBANKED, True),
        ("banked", "banked", True),
        (None, "MISSING", True),
    ],
)
def test_summary_asks_for_banking_unless_banked(
    monkeypatch: pytest.MonkeyPatch, status: str | None, shown: str, states_bank_command: bool
) -> None:
    """Only a BANKED baseline drops the banking instructions; a typo or no status does not."""
    # Arrange
    monkeypatch.setattr(injection_ratchet, "_git_commit", lambda: "abc1234")
    boards, baseline = _clean()
    if status is None:
        del baseline["status"]
    else:
        baseline["status"] = status

    # Act
    markdown = injection_ratchet.render_summary(boards, baseline)

    # Assert
    assert f"Baseline status: **{shown}** (`scripts/injection_baseline.json`)." in markdown
    assert (injection_ratchet.BANK_COMMAND in markdown) is states_bank_command
    assert ("No escapes recorded." in markdown) and (_ALL_CLEAR in markdown)


@pytest.mark.parametrize(
    "untrusted",
    [
        pytest.param((), id="clean"),
        pytest.param(("legacy",), id="legacy-only"),
        pytest.param(("full",), id="full-only"),
        pytest.param(_LADDERS, id="both"),
    ],
)
def test_summary_says_not_evidence_exactly_when_a_ladder_fails_trust(
    monkeypatch: pytest.MonkeyPatch, untrusted: tuple[str, ...]
) -> None:
    """The banner and the all-clear must differ between the good case and each bad one.

    The combined board is the artefact meant to survive the gate's failure, so a
    banner that always fires - or fires only when every ladder fails, or looks
    only at the first - carries no information (``.claude/LESSONS.md`` B9). One
    failing ladder is enough, whichever one it is.
    """
    # Arrange
    monkeypatch.setattr(injection_ratchet, "_git_commit", lambda: "abc1234")
    boards, baseline = _clean()
    for ladder in untrusted:
        boards[ladder] = replace(boards[ladder], interpreter="")
    warns = bool(untrusted)

    # Act
    markdown = injection_ratchet.render_summary(boards, baseline)

    # Assert
    trust_lines = _section(markdown, "### Trust checks")
    expected = [
        f"- **FAIL** {ladder}: the scorecard records no interpreter" for ladder in untrusted
    ] or [_ALL_CLEAR]
    assert (_NOT_EVIDENCE in markdown) is warns, markdown
    assert len(trust_lines) == len(expected), trust_lines
    assert all(map(str.startswith, trust_lines, expected)), trust_lines


def test_summary_renders_quiet_sections_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quiet branches: a floor with every known defect detected names nothing, nothing
    unreachable reads 'None.', and a ladder that caught nothing gets no detections line.

    A passing floor that still missed a known defect does name it; that case is
    pinned in ``test_the_floor_is_read_from_the_baseline``.
    """
    # Arrange
    monkeypatch.setattr(injection_ratchet, "_git_commit", lambda: "abc1234")
    boards, baseline = _clean()
    boards = {ladder: replace(board, unreachable=frozenset()) for ladder, board in boards.items()}
    boards["legacy"] = replace(boards["legacy"], caught_by={})
    total = len(_KNOWN_DEFECTS)
    caught = len(boards["full"].caught_by)

    # Act
    markdown = injection_ratchet.render_summary(boards, baseline)

    # Assert
    floor_heading = "### Known-defect floor (>= 90% of the catalogue's known defects)"
    assert _section(markdown, floor_heading) == [
        f"- `{ladder}`: {total}/{total} = 100% — **PASS**" for ladder in _LADDERS
    ]
    assert _section(markdown, "### UNREACHABLE — moved no observable output") == ["None."]
    assert _section(markdown, "### Where each detection happened") == [
        f"- `full` (unit, contracts): unit {caught}"
    ]


# =============================================================================
# Helpers
# =============================================================================


def _clean() -> tuple[dict[str, Board], dict[str, Any]]:
    """Both ladders trust-clean and floor-clean, and a BANKED baseline equal to them."""
    boards = {ladder: _board(ladder) for ladder in _LADDERS}
    return boards, _bank(boards)


def _board(ladder: str) -> Board:
    """What ``load_board`` makes of a complete campaign that caught every live mutant."""
    dead = frozenset(_DEAD_BY_DESIGN)
    live = _ALL_IDS - dead
    return Board(
        ladder=ladder,
        path=Path(f"scorecard-{ladder}.json"),
        interpreter="uv run",
        gates=("unit", "contracts"),
        runtime_seconds=1.0,
        mutants_total=len(CATALOGUE),
        detected=live,
        escaped=frozenset(),
        unreachable=dead,
        probe_unreachable=dead,
        detection_rate=1.0,
        mean_tier=1.0,
        caught_by=dict.fromkeys(sorted(live), "unit"),
        timeouts={},
        notes={},
        other_verdicts={},
        escaped_rows=(),
    )


def _bank(boards: dict[str, Board]) -> dict[str, Any]:
    """The baseline ``--bank`` would write for these boards."""
    return copy.deepcopy(
        {
            "status": STATUS_BANKED,
            "known_defect_floor": _FLOOR,
            "ladders": {
                ladder: {
                    "detected_ids": sorted(board.detected),
                    "escaped_ids": sorted(board.escaped),
                    "unreachable_ids": sorted(board.unreachable),
                }
                for ladder, board in boards.items()
            },
        }
    )


def _move(board: Board, mutant_id: str, verdict: str) -> Board:
    """Give one mutant a new verdict, keeping every derived field consistent."""
    sets = {
        VERDICT_DETECTED: set(board.detected) - {mutant_id},
        VERDICT_ESCAPED: set(board.escaped) - {mutant_id},
        VERDICT_UNREACHABLE: set(board.unreachable) - {mutant_id},
    }
    other = {k: v for k, v in board.other_verdicts.items() if k != mutant_id}
    if verdict in sets:
        sets[verdict].add(mutant_id)
    else:
        other[mutant_id] = verdict
    probe = set(board.probe_unreachable) - {mutant_id}
    if verdict == VERDICT_UNREACHABLE:
        probe.add(mutant_id)
    caught_by = {k: v for k, v in board.caught_by.items() if k != mutant_id}
    if verdict == VERDICT_DETECTED:
        caught_by[mutant_id] = "unit"
    return replace(
        board,
        detected=frozenset(sets[VERDICT_DETECTED]),
        escaped=frozenset(sets[VERDICT_ESCAPED]),
        unreachable=frozenset(sets[VERDICT_UNREACHABLE]),
        probe_unreachable=frozenset(probe),
        caught_by=caught_by,
        other_verdicts=other,
        escaped_rows=tuple(sorted((i, *_SUMMARIES[i]) for i in sets[VERDICT_ESCAPED])),
    )


def _drop(board: Board, mutant_id: str) -> Board:
    """A mutant that never ran: no verdict at all, as in a filtered campaign."""
    return replace(
        board,
        detected=board.detected - {mutant_id},
        caught_by={k: v for k, v in board.caught_by.items() if k != mutant_id},
    )


def _section(markdown: str, heading: str) -> list[str]:
    """The non-blank lines under one ``###`` heading, up to the next heading."""
    lines = markdown.splitlines()
    assert heading in lines, f"no {heading!r} heading in the summary:\n\n{markdown}"
    start = lines.index(heading) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("#")), len(lines))
    return [line for line in lines[start:end] if line.strip()]


def _findings(out: str) -> list[str]:
    """The findings ``check()`` lists under its RATCHET FAILED line, count verified."""
    lines = out.splitlines()
    head = next((i for i, line in enumerate(lines) if line.startswith("RATCHET FAILED")), None)
    if head is None:
        return []
    findings = [line[4:] for line in lines[head + 1 :] if line.startswith("  - ")]
    assert lines[head] == f"RATCHET FAILED — {len(findings)} finding(s)", lines[head]
    return findings


def _kinds(findings: list[str]) -> list[str]:
    """Each finding cut to the prefix the combination tests compare on."""
    prefixes = (
        "no scorecard for ladder(s) full.",
        "legacy: the scorecard records no interpreter",
        "legacy: known-defect detection",
        "no baseline banked",
        f"full: DETECTED regressed by 1 — {_CONTROL}",
    )
    return [next((p for p in prefixes if f.startswith(p)), f) for f in findings]
