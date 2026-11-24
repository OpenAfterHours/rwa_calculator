"""
Owners in the supervisory register: a break of ours names its plan bullet, and that bullet is open.

Pipeline position:
    (no pipeline stage — reads the committed register and IMPLEMENTATION_PLAN.md;
    nothing here runs a pipeline)
    validation_known_breaks.json reasons  <->  IMPLEMENTATION_PLAN.md open bullets

A break the estate agrees to tolerate is a liability someone must own
(`.claude/LESSONS.md` B7). ``tests/contracts/test_register_publisher_issues.py``
holds the Bank's share of a break to its evidence; this file holds OUR share to an
owner, in two halves.

**A reason that is not wholly the Bank's names its owner.** On every break section
(``known_broken_rules``, ``known_gateway_breaks``, ``known_engine_disagreements``) a
reason owes an ``OWNER: P<n>.<n>`` token — the grammar of
``scripts/tolerated_findings.py``, written after the reason's leading label — when
ANY of these holds:

- it says "our defect", in any case;
- it cites a publisher issue only "in part" (the rest of the cause is ours);
- it cites no publisher issue in full: an "unattributed - needs investigation", a
  rebuttal (``not PI-nn - ...``) that cites no other issue, an unlabelled reason —
  and every CRR entry, whose rule is the EBA's and can cite no issue.

The second condition is redundant on a register the publisher-issue gate holds
green: that gate requires an in-part citation to name "our defect" beside it, so
the first condition already fires, and an in-part citation with no full one beside
it meets the third. It adds a case only for a reason that gate rejects (an in-part
citation beside a full one, with no "our defect"), and is kept so this check is
right on its own rather than right only while another file's check is.

A reason wholly attributed to a publisher issue owes none: the published rule is
its cause. The trigger is ATTRIBUTION, not the word "capital". Of the four reasons
that parked a missing guarantor-eligibility gate with no owner while P1.384 owned
the fix (escape log 2026-11-16), two said "capital-affecting, not changed here" and
two pointed at the same cause only with "(see boe_b0283)"; a keyword gate would have
let half of them through. ``plan item P<n>.<n>`` in prose is NOT an owner: reasons
cite closed bullets as history ("plan item P2.65 measured the gap"), which is why
``owner_of`` accepts only the token.

**An owner is an open bullet.** Every ``OWNER:`` token in any register reason or note
names a bullet IMPLEMENTATION_PLAN.md still holds open (any status box but ``[x]``; closed
bullets are pruned, so a missing bullet is a closed one). Every token, not only the
first: the first is the entry's owner (``owner_of``), but a note can park several
decisions with an owner each, and a token naming a closed bullet as history still
reads as an owner to ``grep 'OWNER: P'`` — history is written as prose. Measured: at
``d426393`` the plan marked P1.369 ``[x]`` while four ``OWNER: P1.369`` tokens - three
register reasons and one note - were still in the register, and every gate was green.

Because the second half reads the plan, a change that closes or prunes an owning
bullet turns this file red. That is the design: the change that closes a bullet is
the one that must re-own or remove the entries it owned, or reopen the bullet.

References:
- scripts/tolerated_findings.py — OWNER_TOKEN, owner_of, open_bullets, stale_owners,
  closed_owners
- scripts/check_parked_registers.py — the same open-owner rule on the declared registers
- tests/contracts/test_register_publisher_issues.py — the label grammar reused here
- docs/development/escape-log.md — 2026-11-16, ``caught-and-parked``
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import pytest
from scripts.check_parked_registers import read_open_bullets
from scripts.tolerated_findings import (
    STALE_OWNER_GUIDANCE,
    UNOWNED_GUIDANCE,
    closed_owners,
    open_bullets,
    owner_of,
    stale_owners,
)
from tests.contracts.test_register_publisher_issues import (
    ISSUE_REGIME,
    PARTIAL_CITATION,
    REGISTER_PATH,
    cited,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

#: The sections whose entries are breaks: a reason here that is ours owes an owner.
OWNED_SECTIONS = ("known_broken_rules", "known_gateway_breaks", "known_engine_disagreements")
#: The register's header of notes, written from REGISTER_NOTES on regen.
NOTES_SECTION = "notes"
#: The register note that tells a reader of the JSON how an owner is written.
OWNER_NOTE = "reading_an_owner"
#: How a reason says (part of) its cause is ours. Any case: three reasons open "Our defect".
OUR_SIDE = re.compile(r"\bour defect\b", re.IGNORECASE)
#: A lexical "capital root cause" detector — the trigger the plan bullet first
#: proposed, kept only to show the gate is NOT built on it.
SAYS_CAPITAL = re.compile(r"\bcapital\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# The check, on one entry and on a whole register
# ---------------------------------------------------------------------------


def owes_an_owner(entry: dict[str, Any]) -> bool:
    """Whether a break's reason names a cause of ours, so it must name who fixes it."""
    reason = entry["reason"]
    if entry["regime"] != ISSUE_REGIME:
        return True
    partial = set(PARTIAL_CITATION.findall(reason))
    wholly_the_bank_s = bool(cited(reason) - partial)
    return bool(OUR_SIDE.search(reason) or partial) or not wholly_the_bank_s


def unowned_problems(register: dict[str, Any]) -> list[str]:
    """Every break whose reason owes an owner and names none."""
    return [
        f"{section} {_where(entry)}: the reason is not wholly a publisher issue's "
        "(it names our defect, cites an issue only in part, or cites none) and carries "
        "no `OWNER: P<n>.<n>`"
        for section in OWNED_SECTIONS
        for entry in register.get(section, [])
        if owes_an_owner(entry) and owner_of(entry["reason"]) is None
    ]


def closed_owner_problems(register: dict[str, Any], open_ids: Collection[str]) -> list[str]:
    """One problem per ``OWNER:`` token, in any reason or note, naming a bullet not open.

    Every token, not only the first: a closed bullet named after an open one owns
    nothing either. The notes header is read too: a note can park a decision on an
    owner as surely as a reason can (at ``d426393`` one of the four ``OWNER: P1.369``
    tokens was in a note), and can park several, one owner each.
    """
    texts = {
        (section, index, _where(entry)): str(entry.get("reason", ""))
        for section, entries in register.items()
        if isinstance(entries, list)
        for index, entry in enumerate(entries)
        if isinstance(entry, dict)
    }
    texts |= {
        (NOTES_SECTION, 0, name): str(note)
        for name, note in register.get(NOTES_SECTION, {}).items()
    }
    return [
        f"{section} {where}: OWNER: {owner} is not an open IMPLEMENTATION_PLAN.md bullet"
        for section, index, where in stale_owners(texts, open_ids)
        for owner in closed_owners(texts[section, index, where], open_ids)
    ]


# ---------------------------------------------------------------------------
# The committed register
# ---------------------------------------------------------------------------


def test_every_break_reason_that_is_not_wholly_the_bank_s_names_its_owner() -> None:
    """A break whose cause is (partly) ours says which plan bullet owns the fix.

    Arrange: the committed register.
    Act:     find break reasons that owe an owner and name none.
    Assert:  there are none.
    """
    # Arrange
    register = _register()

    # Act
    problems = unowned_problems(register)

    # Assert
    assert not problems, "\n".join(problems) + f"\n{UNOWNED_GUIDANCE}"


def test_every_owner_in_the_register_is_an_open_plan_bullet() -> None:
    """An owner the plan has closed or pruned owns nothing.

    Arrange: the committed register and the open bullets of IMPLEMENTATION_PLAN.md.
    Act:     find register reasons whose owner is not open.
    Assert:  there are none.
    """
    # Arrange
    register, open_ids = _register(), read_open_bullets()

    # Act
    problems = closed_owner_problems(register, open_ids)

    # Assert
    assert not problems, "\n".join(problems) + f"\n{STALE_OWNER_GUIDANCE}"


def test_the_register_tells_its_reader_how_an_owner_is_written() -> None:
    """The JSON says what an owner is, so a reader without this file can find one.

    Arrange: the register's notes header (written from REGISTER_NOTES on regen).
    Act:     read the owner note.
    Assert:  it exists, states the token, and names the gate.
    """
    # Arrange / Act
    note = _register().get(NOTES_SECTION, {}).get(OWNER_NOTE, "")

    # Assert
    assert "OWNER: P" in note and "test_register_owners.py" in note, (
        f"notes.{OWNER_NOTE} is missing or does not state the owner token; add it to "
        "REGISTER_NOTES in tests/acceptance/reporting/test_supervisory_validations.py and "
        "to the register's notes"
    )


# ---------------------------------------------------------------------------
# The check itself, on deliberately wrong entries — the gate watched failing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("regime", "reason"),
    [
        pytest.param("b31", "our defect, plan item P2.100: r0095 counts the leg", id="b31-ours"),
        pytest.param("b31", "Our defect, plan item P2.100. r0095 counts the leg", id="b31-Ours"),
        pytest.param(
            "b31",
            "publisher issue PI-24: rows 0010 and 0020 are the rule's case; row 0190 is our defect",
            id="b31-ours-beside-a-full-citation",
        ),
        pytest.param(
            "b31",
            "Our defect at row 0190, beside publisher issue PI-24: rows 0010 and 0020 are the "
            "rule's case",
            id="b31-Ours-beside-a-full-citation",
        ),
        pytest.param(
            "b31",
            "publisher issue PI-29, in part: slotting rows have no PD; publisher issue PI-24: "
            "row 0010 includes slotting",
            id="b31-in-part-beside-a-full-citation",
        ),
        pytest.param(
            "b31",
            "publisher issue PI-29, in part: slotting rows have no PD; the third place is "
            "our defect, plan item P2.81",
            id="b31-in-part",
        ),
        pytest.param(
            "b31", "not PI-23 - our engine: an unreported share read as zero", id="b31-rebuttal"
        ),
        pytest.param(
            "b31", "unattributed - needs investigation: c0110 above c0020", id="b31-unattributed"
        ),
        pytest.param(
            "crr",
            "our defect (design record O-14), not the EBA's: the binding hands over the frame",
            id="crr-ours",
        ),
        pytest.param(
            "crr", "limit of the published rule: an averaged column is summed", id="crr-eba-rule"
        ),
        pytest.param("crr", "publisher issue PI-23: shares do not total one", id="crr-cites-a-pi"),
    ],
)
def test_a_reason_of_ours_with_no_owner_fails_and_passes_once_owned(
    regime: str, reason: str
) -> None:
    """Every form a reason of ours is written in owes the token; the token discharges it.

    Each condition of :func:`owes_an_owner` has a case that only it makes owe:

    - ``*-beside-a-full-citation`` with "our defect" / "Our defect": the reason cites
      PI-24 in full, so only :data:`OUR_SIDE` — and its ignoring of case — makes it
      owe. A reason of this shape is one the publisher-issue gate accepts.
    - ``b31-in-part-beside-a-full-citation``: an in-part citation beside a full one,
      with no "our defect" — only the in-part condition makes it owe. The
      publisher-issue gate would reject this reason (an in-part citation must name
      "our defect" beside it), so on a register that gate holds green the in-part
      condition is redundant with :data:`OUR_SIDE`; it is kept so this check is
      right on its own, and this case is what pins it.
    - every other case cites no issue in full, so the no-full-citation condition
      makes it owe whatever the other two do. ``b31-in-part`` is the register's own
      mixed-cause shape (``boe_b0356``) and fires all three; it pins no one
      condition.

    ``plan item P<n>.<n>`` is prose, not an owner. A CRR reason can cite no
    publisher issue — the register is the Bank's PRA001 rules, so a citation on an
    EBA rule attributes nothing — and even one that blames the EBA's rule owes an
    owner.

    Arrange: a break entry in the given form, and the same entry with an owner.
    Act:     run the unowned check on a register holding each.
    Assert:  the first is reported once, naming the rule; the second is not.
    """
    # Arrange
    bare = _entry("boe_b0990", reason, regime=regime)
    owned = _entry("boe_b0990", f"{reason}; OWNER: P2.100", regime=regime)

    # Act
    problems = unowned_problems({"known_gateway_breaks": [bare]})
    discharged = unowned_problems({"known_gateway_breaks": [owned]})

    # Assert
    assert len(problems) == 1 and "boe_b0990" in problems[0]
    assert discharged == []


@pytest.mark.parametrize("section", OWNED_SECTIONS)
def test_every_break_section_is_held_to_an_owner(section: str) -> None:
    """A reason of ours owes an owner whichever break section holds it.

    Arrange: one unowned reason of ours in the given section.
    Act:     run the unowned check.
    Assert:  it is reported, naming the section.
    """
    # Arrange
    register = {section: [_entry("boe_b0703", "our defect, plan item P2.1: no c0230")]}

    # Act
    problems = unowned_problems(register)

    # Assert
    assert len(problems) == 1 and problems[0].startswith(section)


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param(
            "publisher issue PI-24: OF 08.01 row 0010 includes slotting and OF 08.03 does not",
            id="cited",
        ),
        pytest.param(
            "not PI-08 - the CCR rows are empty, so PI-08's overlap cannot arise. publisher "
            "issue PI-24: OF 08.01 row 0010 includes slotting and OF 08.03 does not",
            id="rebuts-one-cites-another",
        ),
    ],
)
def test_a_reason_wholly_the_bank_s_owes_no_owner(reason: str) -> None:
    """The Bank's rule is the cause, so there is no fix of ours to own.

    The second form is gateway ``boe_b0737``: it rebuts PI-08 and attributes the
    break in full to PI-24. A rebuttal owes an owner only when it cites nothing.

    Arrange: a Basel 3.1 break wholly attributed to a publisher issue.
    Act:     run the unowned check.
    Assert:  nothing is reported.
    """
    # Arrange
    register = {"known_gateway_breaks": [_entry("boe_b0737", reason)]}

    # Act / Assert
    assert unowned_problems(register) == []


def test_the_four_reasons_that_parked_the_eligibility_gate_each_fail() -> None:
    """Replayed from ``59e3c07``: four reasons of ours, no owner, P1.384 owning the fix.

    The adequacy half shows why the trigger is attribution: only two of the four
    say "capital", so a gate keyed on the word would have passed the other two.

    Arrange: the four reasons as they stood at 59e3c07 (abridged, cause intact).
    Act:     run the unowned check, and a lexical 'capital' predicate.
    Assert:  all four are reported; the lexical predicate flags only two.
    """
    # Arrange
    register = {
        "known_broken_rules": [_entry(rule, reason) for rule, reason in _ELIGIBILITY_GATE_PARKED]
    }

    # Act
    problems = unowned_problems(register)
    says_capital = [
        rule for rule, reason in _ELIGIBILITY_GATE_PARKED if SAYS_CAPITAL.search(reason)
    ]

    # Assert
    assert len(problems) == 4, "\n".join(problems)
    assert says_capital == ["boe_b0283", "boe_b0284"], (
        "the replay no longer shows a keyword gate missing half the cases - it proves nothing"
    )


def test_an_owner_whose_bullet_was_closed_fails_at_the_closing_change() -> None:
    """Replayed from the plan before and after P1.369 closed, against the same reasons.

    At ``65a6026`` P1.369 was ``[ ]`` and its four tokens - three reasons and one
    note - were rightly owned; at ``d426393`` the plan closed it ``[x]`` with all four
    unchanged. The gate must pass the first and fail the second: the plan-closing
    change, not the code fix, is the one that has to re-own or remove the entries.

    Arrange: the three P1.369-owned reasons, the P1.369-owned note, and the bullet's
             line at each commit.
    Act:     run the closed-owner check against each plan.
    Assert:  nothing while open; all four once closed, the note among them.
    """
    # Arrange
    note_name, note = _P1_369_OWNED_NOTE
    register = {
        NOTES_SECTION: {note_name: note},
        "known_broken_rules": [_entry(rule, reason) for rule, reason in _P1_369_OWNED],
    }

    # Act
    while_open = closed_owner_problems(register, open_bullets(_P1_369_OPEN_LINE))
    once_closed = closed_owner_problems(register, open_bullets(_P1_369_CLOSED_LINE))

    # Assert
    assert while_open == []
    assert len(once_closed) == 4 and all("P1.369" in problem for problem in once_closed)
    assert any(problem.startswith(f"{NOTES_SECTION} ") for problem in once_closed)


def test_every_owner_a_reason_or_note_names_is_held_open_not_only_the_first() -> None:
    """A closed bullet behind an open one is still a stale owner.

    A note can park two decisions, one owner each, and a reason can carry a token
    for a bullet that has closed after the one it leads with. Reading the first
    token alone passes both, because the open bullet comes first.

    Arrange: a note and a reason, each naming open P2.1 first and closed P1.369
             second.
    Act:     run the closed-owner check with only P2.1 open, then with both open.
    Assert:  each is reported once, naming P1.369 and not P2.1; nothing once both
             are open.
    """
    # Arrange
    register = {
        NOTES_SECTION: {
            "two_decisions": "decision A is OWNER: P2.1; decision B is OWNER: P1.369 and is "
            "NOT made here"
        },
        "known_broken_rules": [_entry("boe_b0703", "our defect, OWNER: P2.1; was OWNER: P1.369")],
    }

    # Act
    second_closed = closed_owner_problems(register, frozenset({"P2.1"}))
    both_open = closed_owner_problems(register, frozenset({"P2.1", "P1.369"}))

    # Assert
    assert len(second_closed) == 2, second_closed
    assert all("OWNER: P1.369 " in problem for problem in second_closed), second_closed
    assert not any("P2.1" in problem for problem in second_closed), second_closed
    assert {problem.split(" ", 1)[0] for problem in second_closed} == {
        NOTES_SECTION,
        "known_broken_rules",
    }
    assert both_open == []


def test_an_owner_pruned_from_the_real_plan_fails() -> None:
    """The plan prunes closed bullets, so an owner it no longer holds is a closed one.

    Arrange: a reason in each kind of section owned by P1.369, which the real plan
             closed and pruned, and the real plan's open bullets.
    Act:     run the closed-owner check.
    Assert:  each is reported, whichever section holds it.
    """
    # Arrange
    open_ids = read_open_bullets()
    assert "P1.369" not in open_ids, "P1.369 is open again - pick a pruned bullet for this test"
    reason = "our defect, OWNER: P1.369 - the add-on has no reported home"
    register = {
        "known_broken_rules": [_entry("boe_b0751", reason)],
        "known_vacuous_rules": [_entry("boe_b0763", reason)],
        "known_uncovered_templates": [{"regime": "b31", "template": "of_08_01", "reason": reason}],
    }

    # Act
    problems = closed_owner_problems(register, open_ids)

    # Assert
    assert len(problems) == 3, "\n".join(problems)


# ---------------------------------------------------------------------------
# The plan reader
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ident", "is_open"),
    [
        pytest.param("P2.100", True, id="open-box"),
        pytest.param("P2.1", True, id="partial-tilde"),
        pytest.param("P7.4", True, id="partial-word"),
        pytest.param("P8.48", True, id="bold-runs-past-the-id"),
        pytest.param("P1.9", True, id="detail-section-status"),
        pytest.param("P1.369", False, id="closed-box"),
        pytest.param("P2.65", False, id="do-not-refile-line"),
        pytest.param("P1.305", False, id="dated-do-not-refile-line"),
        pytest.param("P1.334", False, id="prose-saying-stays-open"),
        pytest.param("P1.288", False, id="lettered-sub-bullet"),
        pytest.param("P1.330", False, id="comment-and-reference-list"),
        pytest.param("P9.99", False, id="absent"),
    ],
)
def test_the_plan_reader_reads_each_status_form(ident: str, is_open: bool) -> None:
    """Every shape IMPLEMENTATION_PLAN.md states a status in, and every shape that is not one.

    The lines are the plan's own, abridged: a box other than ``[x]`` is open,
    including ``[partial]`` and a bold lead that runs past the id; a detail section
    states its box on a Status line; a line with no box states no status.

    Arrange: a plan excerpt holding one line of each shape.
    Act:     read its open bullets.
    Assert:  the id is open exactly when its line says so.
    """
    # Arrange / Act
    open_ids = open_bullets(_PLAN_SHAPES)

    # Assert
    assert (ident in open_ids) is is_open


def test_the_plan_reader_finds_the_real_plan_s_open_bullets() -> None:
    """A reader that finds nothing would make every owner stale, or none checkable.

    Arrange: the committed plan.
    Act:     read its open bullets.
    Assert:  it finds well over a hundred (the plan holds several hundred).
    """
    # Arrange / Act
    open_ids = read_open_bullets()

    # Assert
    assert len(open_ids) > 100, f"only {len(open_ids)} open bullets read from the plan"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _register() -> dict[str, Any]:
    return json.loads(REGISTER_PATH.read_text(encoding="utf-8"))


def _entry(rule_id: str, reason: str, *, regime: str = ISSUE_REGIME) -> dict[str, Any]:
    return {"regime": regime, "rule_id": rule_id, "reason": reason}


def _where(entry: Mapping[Any, Any]) -> str:
    """``regime/rule``, plus the portfolios that tell two entries on one rule apart."""
    subject = entry.get("rule_id") or entry.get("template")
    portfolios = entry.get("portfolios") or entry.get("portfolio") or []
    if isinstance(portfolios, str):
        portfolios = [portfolios]
    shown = ", ".join(portfolios) if len(portfolios) <= 3 else f"{len(portfolios)} portfolios"
    return f"{entry.get('regime')}/{subject}" + (f" ({shown})" if portfolios else "")


#: ``known_broken_rules`` at ``59e3c07``: the reasons that parked the missing
#: guarantor-eligibility gate (P1.384 owned the fix). Abridged to the cause, citations dropped.
_ELIGIBILITY_GATE_PARKED = (
    (
        "boe_b0283",
        "attributed - the S2 guarantee on the crm-substitution portfolio: an F-IRB "
        "corporate loan whose covered part is guaranteed by a RETAIL counterparty. The root "
        "cause is upstream: a retail counterparty is not an eligible protection provider, "
        "so the guarantee should not have been recognised at all (a missing eligibility "
        "gate in engine/crm/, capital-affecting, not changed here).",
    ),
    (
        "boe_b0284",
        "attributed - the S2 guarantee on the crm-substitution portfolio: an F-IRB "
        "corporate loan whose covered part is guaranteed by a RETAIL counterparty. The root "
        "cause is upstream: a retail counterparty is not an eligible protection provider, "
        "so the guarantee should not have been recognised at all (a missing eligibility "
        "gate in engine/crm/, capital-affecting, not changed here).",
    ),
    (
        "boe_b1054",
        "attributed - two causes, one per portfolio. irb-shapes: OF 09.02 classifies "
        "'financial and large corporates' from cp_apply_fi_scalar where OF 02.00 / OF 08 "
        "read exposure_subclass (see boe_b1053). crm-substitution: the S2 retail-guarantor "
        "leg, kept on its obligor's corporate sheet by OF 08 and counted as retail by OF "
        "09.02 (see boe_b0283).",
    ),
    (
        "boe_b1055",
        "attributed - two causes, one per portfolio. irb-shapes: OF 09.02 classifies "
        "'financial and large corporates' from cp_apply_fi_scalar where OF 02.00 / OF 08 "
        "read exposure_subclass (see boe_b1053). crm-substitution: the S2 retail-guarantor "
        "leg, kept on its obligor's corporate sheet by OF 08 and counted as retail by OF "
        "09.02 (see boe_b0283).",
    ),
)

#: ``known_broken_rules`` at ``d426393``: the reasons owned by P1.369. Abridged.
_P1_369_OWNED = (
    (
        "boe_b0621",
        "attributed - plan item P1.369 (OWNER: P1.369; design record O-12). On the one "
        "registered portfolio whose output floor binds, OF 02.00 r0297 c0010 is the "
        "UN-floored RWEA while OF 08.01 sheet 0012 c0260 sums rwa_final.",
    ),
    (
        "boe_b0751",
        "OWNER: P1.369 - the binding output-floor add-on has no reported home in the IRB "
        "templates. Col 0260 exceeds the sum of cols 0251-0254 by the floor shortfall.",
    ),
    (
        "boe_b0763",
        "OWNER: P1.369 - the binding output-floor add-on has no reported home in the IRB "
        "templates. Col 0260 exceeds the sum of cols 0251-0254 by the floor shortfall.",
    ),
)
#: The fourth ``OWNER: P1.369`` at ``d426393``, in the notes header. Abridged.
_P1_369_OWNED_NOTE = (
    "binding_output_floor_add_on_has_no_home_in_the_ir_templates",
    "The reporting-basis decision - un-floored RWEA in the IRB templates with the floor "
    "at the total level, or an adjustment column - is OWNER: P1.369 and is NOT made here.",
)

#: P1.369's bullet at ``65a6026`` (open) and at ``d426393`` (closed). Abridged.
_P1_369_OPEN_LINE = (
    "- **P1.369** [ ] **NEW (2026-09-05, found by the test wave when FS-1 became the "
    "first registered portfolio with a BINDING floor)**\n"
)
_P1_369_CLOSED_LINE = (
    "- **P1.369** [x] **FIXED 2026-11-16** (`dd267d3`, lane Y) — option (a): Annex II "
    "p.112 builds c0260 from c0251–c0254 and has no cell for the add-on.\n"
)

#: One line of each shape IMPLEMENTATION_PLAN.md writes, abridged from the plan.
_PLAN_SHAPES = """\
#### Tier 2 — harness gaps raised by the 2026-11-16 PRA001 rule review
- **P2.100** [ ] **NEW (2026-11-16, found by the register's gateway leg)** — boe_b0990.
- **P2.1** [~] COREP template rework — see detailed section below.
- **P7.4** [partial] Additional exposure classes — phase 1 securitisation FLAG + EXCLUDE.
- **P8.48 (partial)** [ ] **first-batch (16/16) — partial scope** — `@cites` coverage.
- **P1.369** [x] **FIXED 2026-11-16** (`dd267d3`, lane Y) — option (a).
<!-- Items P1.330-P1.340 below were found by the correctness-proposal batch -->
  - **P1.334 stays open and is now MORE urgent, not less.** It records why.
    - **P1.288a** (blocking) — add the backing-proportion input column.

### P1.9 Output Floor — OF-ADJ, portfolio-level application, U-TREA/S-TREA

- **Status:** [~] Partial — sub-items (a), (b), (d) all FIXED; only (c) remains.

### Closed as not-a-defect — DO NOT RE-FILE

- **P1.305** (2026-08-13) — "the LGD side is missing the PD side's corporate gate".
- **P2.62, P2.64, P2.65, P2.66** (2026-11-16) — rule limits of the Bank's published rules.

## Completed Items (reference list)
  - *Tier 1b docstring corrections* — P1.330, P1.332, P1.334, P1.342, P1.345, P1.373.
"""
