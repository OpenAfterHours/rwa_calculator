"""
Every entry of the Bank's newest known-issues log is accounted for, for every shipped release.

Pipeline position:
    docs/assets/boe-banking-known-issues-<month>-<year>.xlsx (the newest; git-ignored)
        x  rwa-filer's packaged deny list (``boe/data/deny/<release>.json``, ``known_issue``)
        x  rwa-filer's publisher-issue register (``boe/data/issues/<release>.json``,
           ``publisher_log[].entry``)
        x  tests/contracts/data/known_issues_dispositions.json (every other entry)

The Bank's known-issues log is where it says a published rule is wrong, will be
switched off, or how to report until the taxonomy is fixed - and it is updated
between taxonomy releases. An entry nothing here reads reaches no gate: the
2026-11-16 escape-log entry is a rule closed as a "limit of the published rule"
four weeks after the Bank had switched it off. So every entry of the newest log
must be accounted for, for each release ``rwa-filer`` ships, in exactly one way:

- the packaged deny list carries it (a deny entry's ``known_issue``); or
- a publisher issue logs it (``publisher_log[].entry``, any relation); or
- ``known_issues_dispositions.json`` dispositions it, with a reason.

Keyed on the log's entry NUMBER, not on rule codes (a code persists across
releases, so code-only matching flags entries fixed long ago, and misses entries
that name no rule but carry an instruction) and not on ``publisher_reference``
(free text, rendered only for acknowledged issues).

A disposition's kind is not taken on trust; the log decides it:

- ``amended``: the entry's Status says "Amended in <version>", at or before the
  release.
- ``owed``: the entry is open and names a rule one of the release's rule books
  ships (read by code from its title and description, in each spelling the Bank
  uses: ``boe-b0141-3_ss`` for ``boe_b0141-3_ss``, ``v0830_m`` for
  ``boe_v0830_m``, ``boe_b04006_1`` for ``boe_b4006_1``, and codes run together,
  ``boe_b0057_and_boe_b0058``; every code the release's rule books hold is held
  to be named by its own spelling). It belongs on the deny list or in the
  register, so it can only be parked, with an ``OWNER: P<n>.<n>`` token naming
  the plan bullet that will put it there. A reason alone cannot wave it through.
- ``no_rule``: the entry is open and names no rule of the release. Where the
  repository acts on it (an interim reporting instruction), ``implemented_at``
  names each file that does, and each must exist and name the entry.

An owner is an OPEN bullet, as it is for every other parked register (P5.83,
``scripts/tolerated_findings.py``): every ``OWNER:`` token in a disposition, of any
kind, names a bullet ``IMPLEMENTATION_PLAN.md`` holds open. A token that merely
parses owns nothing - the first cut of this file parked entries 10, 11, 12 and 19
on ``OWNER: P5.91``, a bullet the plan had closed for an unrelated fix, and every
check was green (`.claude/LESSONS.md` B7). That check reads only this file and the
plan, so it runs on every dev-loop pytest run, with or without the Bank's log, and
closing the owning bullet turns it red until the four are deny-listed, logged on a
publisher issue, or re-owned.

The log is git-ignored, so the accounting test skips without it - a local gate,
and a gate in the scheduled Bank Publications workflow, which sets
``RWA_BANK_FILES_REQUIRED`` so a missing log fails there. The checks on the
disposition file, and the legs that show the accounting can fail, need no file.

References:
- docs/development/escape-log.md — 2026-11-16, the deny-list entry
- scripts/build_filer_release.py ``--deny-list`` — the packaged list's import
- rwa_filer.boe.issues — the publisher-issue register
- IMPLEMENTATION_PLAN.md P5.77
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any

import pytest
from scripts.check_parked_registers import read_open_bullets
from scripts.tolerated_findings import (
    OWNER_TOKEN,
    STALE_OWNER_GUIDANCE,
    closed_owners,
    open_bullets,
    owner_of,
)
from tests.contracts._bank_files import known_issues_rows, newest_known_issues_log
from tests.contracts._ci_workflow import REPO_ROOT

from rwa_filer.boe.catalogue import load_rulebook
from rwa_filer.boe.deny_importer import resolve_code
from rwa_filer.release import (
    release_deny_list,
    release_issues,
    release_rulebooks,
    shipped_releases,
    version_key,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping
    from pathlib import Path

DISPOSITIONS_PATH = REPO_ROOT / "tests" / "contracts" / "data" / "known_issues_dispositions.json"

KIND_AMENDED = "amended"
KIND_NO_RULE = "no_rule"
KIND_OWED = "owed"
KINDS = (KIND_AMENDED, KIND_NO_RULE, KIND_OWED)
#: The keys a disposition may carry.
DISPOSITION_KEYS = frozenset({"kind", "reason", "implemented_at"})

#: The log's columns this reads.
COLUMN_TITLE = "Issue title"
COLUMN_DESCRIPTION = "Issue description"
COLUMN_STATUS = "Status"

#: A rule code as the log writes one. Rule books have ``boe_b0710_1``,
#: ``boe_b0063-1_ss``, ``v11871_m`` and, with one digit, PRA_MEM's ``boe_b1_m``; the
#: log also writes ``boe-b0141-3_ss`` (its entry 20) and ``v0830_m`` (the rule book's
#: ``boe_v0830_m``). Any number of digits: the first cut read three to five, and
#: named neither ``boe_b1_m`` nor ``boe_b2_m`` in any spelling.
_CODE = re.compile(r"(?<![A-Za-z0-9_\-])(?:boe[_-])?[a-z]{1,2}\d+(?:[_-][a-z0-9]+)*", re.IGNORECASE)
#: Splits a token into its parts, keeping the separators: ``boe_b0141-3_ss`` ->
#: ``boe``, ``_``, ``b0141``, ``-``, ``3``, ``_``, ``ss``.
_PARTS = re.compile(r"([_-])")
#: A part that is a code's letters and digits (``b0057``, ``v11871``).
_CODE_HEAD = re.compile(r"[a-z]{1,2}\d+", re.IGNORECASE)
#: A Status line that leads with "Amended in <version>". Anchored to the line's
#: start, so "Not amended in 4.1.1; to be amended in 4.2.0" is not read as amended.
_AMENDED_IN = re.compile(r"^\s*amended in\b\D*?(\d+\.\d+\.\d+)", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class LogEntry:
    """One entry of the known-issues log, as far as the accounting needs it."""

    number: int
    status: str
    text: str


# ---------------------------------------------------------------------------
# The accounting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("release", shipped_releases())
def test_every_entry_of_the_newest_log_is_accounted_for(release: str) -> None:
    # Arrange
    entries = _log_entries(newest_known_issues_log())
    numbers = [entry.number for entry in entries]
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"the log's entries are not numbered 1..{len(numbers)} ({numbers}): a row was misread "
        "and an entry this test never sees cannot be unaccounted for"
    )

    # Act
    problems = accounting_problems(
        entries,
        release,
        covered=_covered(release),
        dispositions=_dispositions().get(release, {}),
        index=_rule_index(release),
        open_ids=_open_ids(),
    )

    # Assert
    assert not problems, (
        f"Known-issues entries not accounted for in taxonomy {release}. Import the newest "
        "deny list (scripts/build_filer_release.py <release> --deny-list), log the entry on a "
        "publisher issue, or disposition it in tests/contracts/data/"
        "known_issues_dispositions.json:\n  " + "\n  ".join(problems)
    )


@pytest.mark.parametrize("release", shipped_releases())
def test_each_cover_is_load_bearing(release: str) -> None:
    """Take away the one cover of an entry the deny list OR a publisher issue covers: red.

    The leg the premise audit asked for (PI-06's ``publisher_log`` entry 28),
    taken for every singly-covered entry, so no disposition can be shadowing one.
    """
    # Arrange
    entries = _log_entries(newest_known_issues_log())
    covered = _covered(release)
    deny = {entry.known_issue for entry in release_deny_list(release).entries}
    register = {
        log.entry for issue in release_issues(release).issues for log in issue.publisher_log
    }
    single = sorted((deny ^ register) - {None})
    assert single, "no entry is covered by one source alone: this leg would prove nothing"

    # Act
    unmoved = [
        number
        for number in single
        if not any(
            problem.startswith(f"#{number}:")
            for problem in accounting_problems(
                entries,
                release,
                covered={key: value for key, value in covered.items() if key != number},
                dispositions=_dispositions().get(release, {}),
                index=_rule_index(release),
                open_ids=_every_owner(),
            )
        )
    ]

    # Assert
    assert not unmoved, f"dropping the cover of {unmoved} left the accounting green"


@pytest.mark.parametrize("release", shipped_releases())
def test_an_owed_entry_cannot_be_relabelled_away(release: str) -> None:
    """Every ``owed`` entry, relabelled ``no_rule`` or ``amended``, turns the accounting red.

    Entry 11 is the case: LVR002 ``boe_b0057`` is enforced as an ERROR in the
    4.1.1 rule book, the log says it misfires and "will be deactivated", and the
    deny list does not list it.
    """
    # Arrange
    entries = _log_entries(newest_known_issues_log())
    dispositions = _dispositions().get(release, {})
    owed = [number for number, item in dispositions.items() if item["kind"] == KIND_OWED]
    assert owed, "no entry is owed: this leg would prove nothing"

    # Act
    green = [
        (number, kind)
        for number in owed
        for kind in (KIND_NO_RULE, KIND_AMENDED)
        if not accounting_problems(
            entries,
            release,
            covered=_covered(release),
            dispositions={**dispositions, number: {**dispositions[number], "kind": kind}},
            index=_rule_index(release),
            open_ids=_every_owner(),
        )
    ]

    # Assert
    assert not green, f"relabelled owed entries passed: {green}"


# ---------------------------------------------------------------------------
# The rules the accounting applies (no file needed)
# ---------------------------------------------------------------------------

_INDEX: dict[str, frozenset[str]] = {
    "boe_b0057": frozenset({"LVR002"}),
    "boe_b0141-3_ss": frozenset({"PRA116"}),
    "boe_b0710_1": frozenset({"PRA001"}),
    "boe_b1_m": frozenset({"PRA_MEM"}),
    "boe_b4006_1": frozenset({"MRL001"}),
    "boe_v0830_m": frozenset({"RFB004"}),
    "v0172_m": frozenset({"PRA001"}),
    "v11871_m": frozenset({"PRA001", "PRA116"}),
}
_OPEN = "To be reviewed in the next release"
#: The plan bullets these legs treat as open: the one their ``OWNER:`` tokens name.
_OPEN_IDS = frozenset({"P9.99"})


def test_an_entry_nothing_accounts_for_is_reported() -> None:
    # Arrange
    entry = LogEntry(1, _OPEN, "OF08.01.01.01 cells erroneously greyed out")

    # Act
    problems = accounting_problems(
        [entry], "4.1.1", covered={}, dispositions={}, index=_INDEX, open_ids=_OPEN_IDS
    )

    # Assert
    assert len(problems) == 1 and problems[0].startswith("#1: not accounted for")


def test_an_open_entry_naming_a_shipped_rule_is_owed_whatever_it_is_called() -> None:
    # Arrange
    entry = LogEntry(1, _OPEN, "Validation rule boe_b0057")
    as_no_rule = {1: {"kind": KIND_NO_RULE, "reason": "informational"}}
    as_owed = {1: {"kind": KIND_OWED, "reason": "OWNER: P9.99. a publisher issue is owed"}}

    # Act
    relabelled = accounting_problems(
        [entry], "4.1.1", covered={}, dispositions=as_no_rule, index=_INDEX, open_ids=_OPEN_IDS
    )
    parked = accounting_problems(
        [entry], "4.1.1", covered={}, dispositions=as_owed, index=_INDEX, open_ids=_OPEN_IDS
    )

    # Assert
    assert len(relabelled) == 1 and "the log makes it 'owed'" in relabelled[0]
    assert parked == []


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        ("Amended in hotfix release 3.5.1", KIND_AMENDED),
        ("Amended in v4.0.0\nRe-activated in v4.1.1", KIND_AMENDED),
        ("Amended in release 4.1.1 and re-activated", KIND_AMENDED),
        ("Amended in release 4.2.0", KIND_OWED),
        (_OPEN, KIND_OWED),
        ("Not amended in 4.1.1; to be amended in 4.2.0", KIND_OWED),
        ("To be reviewed in the next release; will be amended in 3.5.1", KIND_OWED),
    ],
)
def test_amended_counts_only_at_or_before_the_release(status: str, kind: str) -> None:
    # Arrange
    entry = LogEntry(1, status, "validation rule v11871_m")

    # Act
    expected = expected_kind(entry, "4.1.1", _INDEX)

    # Assert
    assert expected == kind


def test_an_owed_disposition_needs_an_owner() -> None:
    # Arrange
    entry = LogEntry(1, _OPEN, "Validation rule boe_b0057")
    unowned = {1: {"kind": KIND_OWED, "reason": "the Bank says it misfires"}}

    # Act
    problems = accounting_problems(
        [entry], "4.1.1", covered={}, dispositions=unowned, index=_INDEX, open_ids=_OPEN_IDS
    )

    # Assert
    assert len(problems) == 1 and "no OWNER" in problems[0]


def test_an_owner_the_plan_does_not_hold_open_owns_nothing() -> None:
    """Closed (``[x]``) or never filed, an ``OWNER:`` token's bullet owns nothing - any kind.

    The first cut checked only that a token parsed; ``OWNER: P0.0`` passed it.
    """
    # Arrange
    plan = "- **P9.97** [ ] **open**\n- **P9.98** [x] **closed**\n"
    owed = [LogEntry(number, _OPEN, "Validation rule boe_b0057") for number in (1, 2, 3)]
    informational = LogEntry(4, _OPEN, "Row nesting of CL66.01.01.01")
    dispositions = {
        1: {"kind": KIND_OWED, "reason": "OWNER: P9.97. owed"},
        2: {"kind": KIND_OWED, "reason": "OWNER: P9.98. owed, on a closed bullet"},
        3: {"kind": KIND_OWED, "reason": "OWNER: P9.99. owed, on a bullet never filed"},
        4: {"kind": KIND_NO_RULE, "reason": "names no rule; OWNER: P9.98 watches it"},
    }

    # Act
    problems = accounting_problems(
        [*owed, informational],
        "4.1.1",
        covered={},
        dispositions=dispositions,
        index=_INDEX,
        open_ids=open_bullets(plan),
    )

    # Assert
    assert [problem.split(":")[0] for problem in problems] == ["#2", "#3", "#4"]
    assert all("not a bullet IMPLEMENTATION_PLAN.md holds open" in item for item in problems)


def test_a_disposition_for_a_covered_or_absent_entry_is_stale() -> None:
    # Arrange
    entry = LogEntry(1, _OPEN, "Validation rule boe_b0057")
    dispositions = {
        1: {"kind": KIND_OWED, "reason": "OWNER: P9.99. owed"},
        2: {"kind": KIND_NO_RULE, "reason": "an entry the log does not have"},
    }

    # Act
    problems = accounting_problems(
        [entry],
        "4.1.1",
        covered={1: "publisher issue PI-99"},
        dispositions=dispositions,
        index=_INDEX,
        open_ids=_OPEN_IDS,
    )

    # Assert
    assert [problem.split(":")[0] for problem in problems] == ["#1", "#2"]
    assert "covered by publisher issue PI-99" in problems[0]
    assert "the log has no entry 2" in problems[1]


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("Erroneous validation code boe-b0141-3_ss", {"boe_b0141-3_ss"}),
        ("validation rule v0830_m", {"boe_v0830_m"}),
        ("validation rule v11871_m", {"v11871_m"}),
        ("validation rules\nboe_b0057\nboe_b0058", {"boe_b0057"}),
        ("R0280 and C0010 of LV47.00.00.01", set()),
        # One digit: PRA_MEM ships boe_b1_m and boe_b2_m.
        ("validation rule boe_b1_m", {"boe_b1_m"}),
        ("VALIDATION RULE BOE_B1_M", {"boe_b1_m"}),
        # Codes run together: each run of the token's parts that is a rule.
        ("validation rules boe_b0057_and_boe-v0830_m", {"boe_b0057", "boe_v0830_m"}),
        # The Bank's shorthand for _1, _2, _3: the leading rule, enough to make it owed.
        ("validation rules boe_b0710_1_2_3", {"boe_b0710_1"}),
        ("validation rules boe_x9999_and_v11871_m", {"v11871_m"}),
        # The deny list's own typo: a surplus leading zero in the rule number.
        ("Validation rule boe_b04006_1", {"boe_b4006_1"}),
        # Entry 9's title: PRA102's rule, which no 4.1.1 rule book ships, is not
        # PRA001's v0172_m - the part after ``boe_`` starts no code of its own.
        ("Validation rules boe_v0172_m_2 (PRA102, PRA113)", set()),
    ],
)
def test_the_banks_spellings_of_a_rule_code_name_the_rule(text: str, named: set[str]) -> None:
    # Act
    found = named_rules(text, _INDEX)

    # Assert
    assert found == named


@pytest.mark.parametrize("release", shipped_releases())
def test_every_rule_a_shipped_rule_book_holds_is_named_by_its_own_code(release: str) -> None:
    """Anchored to the rule books themselves, not to codes someone picked (LESSONS B3).

    The first cut read a code as ``[a-z]{1,2}\\d{3,5}``, so PRA_MEM's ``boe_b1_m``
    and ``boe_b2_m`` were named by no spelling: an open entry naming either would
    have been read ``no_rule``, which takes a free-text reason and no ``OWNER``.
    """
    # Arrange
    index = _rule_index(release)
    assert len(index) > 1000, f"{release}: {len(index)} rule codes - the rule books were misread"

    # Act
    unnamed = sorted(
        text
        for code in index
        for text in (f"validation rule {code}", f"VALIDATION RULE {code.upper()}")
        if named_rules(text, index) != {code}
    )

    # Assert
    assert not unnamed, f"{release}: {len(unnamed)} spellings name the wrong rules: {unnamed}"


def test_implemented_at_must_exist_and_name_the_entry() -> None:
    # Arrange
    entry = LogEntry(25, _OPEN, "OF08.01.01.01 cells erroneously greyed out in sheet 0019")
    missing = {25: {"kind": KIND_NO_RULE, "reason": "r", "implemented_at": ["src/nowhere.py"]}}
    silent = {25: {"kind": KIND_NO_RULE, "reason": "r", "implemented_at": ["pyproject.toml"]}}

    # Act
    not_there = accounting_problems(
        [entry], "4.1.1", covered={}, dispositions=missing, index={}, open_ids=_OPEN_IDS
    )
    not_named = accounting_problems(
        [entry], "4.1.1", covered={}, dispositions=silent, index={}, open_ids=_OPEN_IDS
    )

    # Assert
    assert len(not_there) == 1 and "src/nowhere.py does not exist" in not_there[0]
    assert len(not_named) == 1 and "pyproject.toml does not name entry 25" in not_named[0]


# ---------------------------------------------------------------------------
# The disposition file (no file from the Bank needed)
# ---------------------------------------------------------------------------


def test_the_dispositions_are_kept_for_exactly_the_shipped_releases() -> None:
    assert sorted(_dispositions()) == sorted(shipped_releases())


def test_every_disposition_has_a_known_kind_a_reason_and_an_open_owner_where_owed() -> None:
    """Reads only this file and IMPLEMENTATION_PLAN.md: closing an owner turns it red."""
    # Act
    problems = disposition_file_problems(_dispositions(), _open_ids())

    # Assert
    assert not problems, "\n".join([*problems, STALE_OWNER_GUIDANCE])


@pytest.mark.parametrize("stale", ["P5.91", "P0.0"])
def test_each_owed_disposition_re_owned_by_a_bullet_the_plan_does_not_hold_open_is_red(
    stale: str,
) -> None:
    """The review's finding, on the real file: P5.91 is closed (an unrelated fix), P0.0 never filed.

    The first cut parked entries 10, 11, 12 and 19 on ``OWNER: P5.91``, and every
    check was green; it was as green on ``OWNER: P0.0``.
    """
    # Arrange
    open_ids = _open_ids()
    assert stale not in open_ids, f"{stale} is open in IMPLEMENTATION_PLAN.md: pick another"
    dispositions = _dispositions()
    owed = [
        (release, number)
        for release, items in dispositions.items()
        for number, item in items.items()
        if item["kind"] == KIND_OWED
    ]
    assert owed, "no entry is owed: this leg would prove nothing"

    # Act
    green = [
        (release, number)
        for release, number in owed
        if not any(
            problem.startswith(f"{release} #{number}:")
            for problem in disposition_file_problems(
                _re_owned(dispositions, release, number, stale), open_ids
            )
        )
    ]

    # Assert
    assert not green, f"owed entries re-owned by {stale} passed: {green}"


def test_every_implemented_at_path_exists_and_names_its_entry() -> None:
    # Act
    problems = [
        f"{release} #{number}: {problem}"
        for release, items in _dispositions().items()
        for number, item in items.items()
        for problem in _implementation_problems(number, item)
    ]

    # Assert
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def accounting_problems(
    entries: Iterable[LogEntry],
    release: str,
    *,
    covered: Mapping[int, str],
    dispositions: Mapping[int, Mapping[str, Any]],
    index: Mapping[str, frozenset[str]],
    open_ids: Collection[str],
) -> list[str]:
    """Every way the log's entries are not accounted for in ``release``, one line each.

    ``open_ids`` is the plan bullets an ``OWNER:`` token may name (``open_bullets``).
    """
    problems: list[str] = []
    numbers: set[int] = set()
    for entry in entries:
        numbers.add(entry.number)
        disposition = dispositions.get(entry.number)
        if entry.number in covered:
            if disposition is not None:
                problems.append(
                    f"#{entry.number}: covered by {covered[entry.number]}, and dispositioned "
                    "too - remove the disposition"
                )
            continue
        expected = expected_kind(entry, release, index)
        if disposition is None:
            problems.append(
                f"#{entry.number}: not accounted for - not deny-listed, in no publisher issue's "
                f"publisher_log, not dispositioned ({_why(entry, release, index)}; "
                f"the log makes it {expected!r})"
            )
            continue
        if disposition.get("kind") != expected:
            problems.append(
                f"#{entry.number}: dispositioned {disposition.get('kind')!r}, but the log makes "
                f"it {expected!r} ({_why(entry, release, index)})"
            )
        problems += [
            f"#{entry.number}: {problem}" for problem in _shape_problems(disposition, open_ids)
        ]
        problems += [
            f"#{entry.number}: {problem}"
            for problem in _implementation_problems(entry.number, disposition)
        ]
    problems += [
        f"#{number}: dispositioned, but the log has no entry {number}"
        for number in sorted(set(dispositions) - numbers)
    ]
    return problems


def disposition_file_problems(
    dispositions: Mapping[str, Mapping[int, Mapping[str, Any]]], open_ids: Collection[str]
) -> list[str]:
    """Every disposition, of every release, with no known kind, no reason, or no open owner."""
    return [
        f"{release} #{number}: {problem}"
        for release, items in dispositions.items()
        for number, item in items.items()
        for problem in _shape_problems(item, open_ids)
    ]


def expected_kind(entry: LogEntry, release: str, index: Mapping[str, frozenset[str]]) -> str:
    """What the log makes an entry no deny entry or publisher issue covers, in ``release``."""
    amended = _AMENDED_IN.search(entry.status)
    if amended is not None and _at_or_before(amended.group(1), release):
        return KIND_AMENDED
    return KIND_OWED if named_rules(entry.text, index) else KIND_NO_RULE


def named_rules(text: str, index: Mapping[str, frozenset[str]]) -> set[str]:
    """The rules of ``index`` that ``text`` names, in any of the Bank's spellings of a code.

    A token is read whole first. Where the whole token is no rule, it is cut
    before each part that starts a code, and each piece names the longest run of
    its leading parts that is a rule: codes run together
    (``boe_b0057_and_boe_b0058``) and the Bank's shorthand for a family
    (``boe_b0710_1_2_3``) name the rules they start with, not nothing. A code's
    own letters and digits after its ``boe_`` start nothing, so entry 9's
    ``boe_v0172_m_2`` (PRA102) does not name PRA001's ``v0172_m``.
    """
    return {code for token in _CODE.findall(text) for code in _codes_in(token, index)}


def _at_or_before(version: str, release: str) -> bool:
    """Whether ``version`` is ``release`` or an earlier one, compared as numbers."""
    return sorted((version, release), key=version_key)[0] == version


def _codes_in(token: str, index: Mapping[str, frozenset[str]]) -> set[str]:
    """The rules of ``index`` a token names: whole, else each piece's longest leading rule."""
    whole = _rules_spelt(token, index)
    if whole:
        return whole
    parts = _PARTS.split(token)  # words at the even positions, separators at the odd
    starts = [at for at in range(0, len(parts), 2) if _starts_code(parts, at)]
    found: set[str] = set()
    for begin, end in zip(starts, [*starts[1:], len(parts) + 1], strict=True):
        piece = parts[begin : end - 1]
        found |= next(
            (
                codes
                for stop in range(len(piece), 0, -2)
                if (codes := _rules_spelt("".join(piece[:stop]), index))
            ),
            set(),
        )
    return found


def _starts_code(parts: list[str], at: int) -> bool:
    """Whether word ``at`` of a split token starts a code: ``boe``, or a head not after one."""
    word = parts[at].lower()
    if word == "boe":
        return True
    return _CODE_HEAD.fullmatch(word) is not None and (at == 0 or parts[at - 2].lower() != "boe")


def _rules_spelt(token: str, index: Mapping[str, frozenset[str]]) -> set[str]:
    """The rules of ``index`` that ``token``, read whole, spells.

    A surplus leading zero in the rule number (``boe_b04006_1``, which the Bank's
    November 2026 deny list writes for ``boe_b4006_1``) is resolved by the deny-list
    import's own rule, ``resolve_code``, so the two readings cannot drift apart.
    """
    found: set[str] = set()
    for spelling in _spellings(token):
        code = spelling if spelling in index else resolve_code(spelling, index)[0]
        if code is not None:
            found.add(code)
    return found


def _spellings(token: str) -> set[str]:
    """``boe-b0141-3_ss`` -> ``boe_b0141-3_ss``; ``v0830_m`` -> itself and ``boe_v0830_m``."""
    code = token.lower().rstrip("_-")
    if code.startswith("boe-"):
        code = f"boe_{code.removeprefix('boe-')}"
    return {code} if code.startswith("boe_") else {code, f"boe_{code}"}


def _why(entry: LogEntry, release: str, index: Mapping[str, frozenset[str]]) -> str:
    named = sorted(named_rules(entry.text, index))
    status = " / ".join(line.strip() for line in entry.status.splitlines() if line.strip())
    return f"status {status!r}; names {', '.join(named) or 'no rule'} of {release}'s rule books"


def _shape_problems(disposition: Mapping[str, Any], open_ids: Collection[str]) -> list[str]:
    problems = []
    unknown = sorted(set(disposition) - DISPOSITION_KEYS)
    if unknown:
        problems.append(f"unknown key(s) {unknown}")
    if disposition.get("kind") not in KINDS:
        problems.append(f"kind {disposition.get('kind')!r} is not one of {KINDS}")
    reason = str(disposition.get("reason") or "").strip()
    if not reason:
        problems.append("no reason")
    elif disposition.get("kind") == KIND_OWED and owner_of(reason) is None:
        problems.append("owed with no OWNER: P<n>.<n> token naming the bullet that owns it")
    problems += [
        f"OWNER: {owner} is not a bullet IMPLEMENTATION_PLAN.md holds open (closed, pruned "
        "or never filed), so it owns nothing"
        for owner in closed_owners(reason, open_ids)
    ]
    return problems


def _implementation_problems(number: int, disposition: Mapping[str, Any]) -> list[str]:
    names_entry = re.compile(rf"(?:item|issue|entry|#)\s*#?{number}\b", re.IGNORECASE)
    problems = []
    for relative in disposition.get("implemented_at", ()):
        path = REPO_ROOT / relative
        if not path.is_file():
            problems.append(f"implemented_at {relative} does not exist")
        elif not names_entry.search(path.read_text(encoding="utf-8")):
            problems.append(f"implemented_at {relative} does not name entry {number}")
    return problems


def _log_entries(path: Path) -> tuple[LogEntry, ...]:
    rows = known_issues_rows(path)
    assert rows, f"{path.name}: no entry read from the 'Known Issues' sheet"
    entries = []
    for number, row in sorted(rows.items()):
        missing = {COLUMN_TITLE, COLUMN_DESCRIPTION, COLUMN_STATUS} - set(row)
        assert not missing, f"{path.name}: no column {sorted(missing)}"
        entries.append(
            LogEntry(number, row[COLUMN_STATUS], f"{row[COLUMN_TITLE]}\n{row[COLUMN_DESCRIPTION]}")
        )
    return tuple(entries)


def _covered(release: str) -> dict[int, str]:
    """Entry number -> what covers it: a deny entry's ``known_issue``, or a publisher issue."""
    covered: dict[int, str] = {}
    for entry in release_deny_list(release).entries:
        if entry.known_issue is not None:
            covered.setdefault(entry.known_issue, f"the deny list ({entry.module} {entry.rule_id})")
    for issue in release_issues(release).issues:
        for log in issue.publisher_log:
            covered.setdefault(log.entry, f"publisher issue {issue.id} ({log.relation})")
    return covered


@cache
def _rule_index(release: str) -> dict[str, frozenset[str]]:
    """Every rule code of ``release``'s rule books -> the modules it has a severity in."""
    index: dict[str, set[str]] = {}
    for file_name in release_rulebooks(release):
        for rule in load_rulebook(file_name).rules:
            index.setdefault(rule.rule_id, set()).update(rule.severities)
    return {code: frozenset(modules) for code, modules in index.items()}


def _re_owned(
    dispositions: Mapping[str, Mapping[int, Mapping[str, Any]]],
    release: str,
    number: int,
    owner: str,
) -> dict[str, dict[int, Mapping[str, Any]]]:
    """``dispositions`` with every ``OWNER:`` token of one entry's reason rewritten to ``owner``."""
    rewritten = {key: dict(items) for key, items in dispositions.items()}
    item = rewritten[release][number]
    rewritten[release][number] = {
        **item,
        "reason": OWNER_TOKEN.sub(f"OWNER: {owner}", str(item["reason"])),
    }
    return rewritten


@cache
def _every_owner() -> frozenset[str]:
    """Every bullet the dispositions name, taken as open: a leg isolated from the plan.

    The load-bearing legs ask whether ONE thing turns the accounting red; with the
    plan's bullets, a closed owner would turn it red for the wrong reason.
    """
    return frozenset(
        owner
        for items in _dispositions().values()
        for item in items.values()
        for owner in OWNER_TOKEN.findall(str(item.get("reason", "")))
    )


@cache
def _open_ids() -> frozenset[str]:
    """The bullets IMPLEMENTATION_PLAN.md holds open, as the other parked registers read them."""
    return read_open_bullets()


@cache
def _dispositions() -> dict[str, dict[int, dict[str, Any]]]:
    payload = json.loads(DISPOSITIONS_PATH.read_text(encoding="utf-8"))
    return {
        release: {int(number): item for number, item in items.items()}
        for release, items in payload["releases"].items()
    }
