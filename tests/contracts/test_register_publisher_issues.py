"""
Publisher-issue labels in the supervisory register: every citation real, no Bank-rule break unlabelled.

Pipeline position:
    (no pipeline stage — reads the committed register and the packaged
    publisher-issue register; nothing here runs a pipeline)
    validation_known_breaks.json reasons  <->  rwa_filer.boe.issues (release 4.1.1)

A published rule can itself be wrong. ``rwa_filer.boe.issues`` is the curated,
evidenced register of the Bank's rules known to be wrong for a taxonomy release
(rendered as ``docs/rwa-filer/publisher-issues.md``), and the supervisory register
(``tests/expected_outputs/reporting/validation_known_breaks.json``) is where our
own tolerated breaks are explained. This file makes the two speak one language,
in both directions, so a limit of the Bank's rule can never sit in the register
under an "our defect" reason, and an "our defect" can never hide behind a
"limit of the published rule" nobody has evidenced.

The label grammar (also in the register's own ``notes``,
``reading_publisher_issue_labels``):

- ``publisher issue PI-nn`` anywhere in a reason ATTRIBUTES the entry to that
  issue: the published rule is the cause. The issue must name the entry's rule as
  its SUBJECT — the only role in which an issue says the rule is wrong, the only
  one ``rwa_filer.boe.issues.issues_for`` returns, and the only one
  ``rwa_filer.validate.issue_labels`` puts a label on a result for. Citing an
  issue against a rule it names only as a control, a contradiction or a related
  rule would label a break the issue itself says a correct return does not have.
  On a BREAK (``known_broken_rules``, ``known_gateway_breaks``) the issue's effect
  must also be ``fails_correct_returns``, as ``issue_labels`` requires before it
  labels a FAIL: an issue saying the rule passes wrong returns, or never runs,
  cannot be why it fails.
- ``publisher issue PI-nn, in part`` is the same attribution for a pair whose
  places have two causes — some the issue's case, the rest ours. The register is
  keyed per (rule, portfolio) and holds one reason per pair, so such a pair cites
  the issue (a grep for the Bank's share finds it) and names "our defect", with
  its ``OWNER: P<n>.<n>``, for the rest in the same reason (nothing of ours hides
  behind the citation either; ``tests/contracts/test_register_owners.py`` holds the
  owner to an open plan bullet).
- ``not PI-nn - <cause>`` (``not PI-aa, PI-bb - ...`` for several) at the START
  of a reason REBUTS the issue: the issue names the rule, and this break is not
  it — ours, our engine's, or (rarely) another issue's cited in the same reason. The issue must name the rule as its SUBJECT (it
  would otherwise explain the break) or as a CONTROL (the issue's own evidence is
  that a correct return satisfies the rule, which is the strongest statement
  available that the break is ours). A contradicting or related rule is not
  rebutted: the issue makes no claim either way about its breaks.
- Any further mention of an issue already cited or rebutted in the same reason is
  commentary and free; a mention of an issue the reason neither cites nor rebuts
  is not — say which it is.
- The issue register is the Bank's, for the PRA001 rules of release 4.1.1: a CRR
  entry (an EBA rule) cites no issue.

And the requirement, Basel 3.1 breaks only (``known_broken_rules`` and
``known_gateway_breaks``): a break on a rule that an issue with the effect
``fails_correct_returns`` names as its SUBJECT must cite that issue or rebut it.
Open or fixed alike — the register is release 4.1.1's, and a rule the Bank fixes
in a later release is as wrong under 4.1.1 as before; only a withdrawn issue
(no longer considered one) is owed nothing.
Plus the converse for prose: a Basel 3.1 reason that calls its break a "limit of
the published rule" must cite the issue that documents it.

References:
- packages/rwa-filer/src/rwa_filer/boe/issues.py — the issue register and its roles
- tests/acceptance/reporting/test_supervisory_validations.py — REGISTER_NOTES and the legs
- docs/rwa-filer/publisher-issues.md — the register rendered for sharing
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from rwa_calc.reporting.filing.canonical import FILING_MODULE, FILING_TAXONOMY
from rwa_filer.boe.issues import (
    EFFECT_FAILS_CORRECT_RETURNS,
    ROLE_CONTROL,
    ROLE_SUBJECT,
    STATUS_FIXED,
    STATUS_WITHDRAWN,
    IssueRegister,
    load_issues,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTER_PATH = (
    REPO_ROOT / "tests" / "expected_outputs" / "reporting" / "validation_known_breaks.json"
)

#: The regime whose rules the issue register covers: PRA001 is the Basel 3.1 return.
ISSUE_REGIME = "b31"
#: The sections whose entries name one rule each.
RULE_SECTIONS = (
    "known_broken_rules",
    "known_vacuous_rules",
    "known_gateway_breaks",
    "known_engine_disagreements",
)
#: The sections that hold a break: the requirement applies to these.
BREAK_SECTIONS = ("known_broken_rules", "known_gateway_breaks")
#: The register note that explains the labels to a reader of the JSON.
LABEL_NOTE = "reading_publisher_issue_labels"

ISSUE_ID = r"PI-[0-9]{2}[a-z]?"
CITATION = re.compile(rf"\bpublisher issue ({ISSUE_ID})\b")
#: A citation of an issue that is only part of the cause: a pair whose places
#: have two causes cites the issue this way and names our share beside it.
PARTIAL_CITATION = re.compile(rf"\bpublisher issue ({ISSUE_ID}), in part\b")
REBUTTAL = re.compile(rf"^not ({ISSUE_ID}(?:, {ISSUE_ID})*) - ")
MENTION = re.compile(rf"\b({ISSUE_ID})\b")
#: How a reason says its cause is the published rule.
BLAMES_THE_RULE = re.compile(r"limit(?:ation)? of the published rule", re.IGNORECASE)
#: How a reason names the share of a mixed-cause pair that is ours.
OUR_SHARE = re.compile(r"\bour defect\b")

ATTRIBUTION_ROLES = (ROLE_SUBJECT,)
REBUTTAL_ROLES = (ROLE_SUBJECT, ROLE_CONTROL)
#: The effect an issue must have to be the cause of a BREAK: it is the only one
#: ``rwa_filer.validate.issue_labels`` labels a FAIL with.
BREAK_EFFECTS = (EFFECT_FAILS_CORRECT_RETURNS,)


# ---------------------------------------------------------------------------
# The check, on one entry
# ---------------------------------------------------------------------------


def cited(reason: str) -> set[str]:
    """The issues a reason attributes its entry to."""
    return set(CITATION.findall(reason))


def rebutted(reason: str) -> set[str]:
    """The issues a reason's leading clause rebuts."""
    found = REBUTTAL.match(reason)
    return set(found.group(1).split(", ")) if found else set()


def citation_problems(section: str, entry: dict[str, Any], register: IssueRegister) -> list[str]:
    """Every way an entry's PI references fail the grammar or the issue register."""
    reason = entry["reason"]
    where = f"{section} {entry['regime']}/{entry['rule_id']}"
    mentioned = set(MENTION.findall(reason))
    if not mentioned:
        return []
    if entry["regime"] != ISSUE_REGIME:
        return [
            f"{where}: cites {sorted(mentioned)}, but the issue register holds the Bank's "
            f"{FILING_MODULE} rules; an EBA rule under CRR is another rule"
        ]
    attributed, rebuts = cited(reason), rebutted(reason)
    problems = [
        f"{where}: {issue_id} is mentioned but neither cited ('publisher issue {issue_id}') "
        f"nor rebutted at the start ('not {issue_id} - ...') - say which it is"
        for issue_id in sorted(mentioned - attributed - rebuts)
    ]
    problems += [
        f"{where}: {issue_id} is both cited and rebutted"
        for issue_id in sorted(attributed & rebuts)
    ]
    for issue_id, roles, form in (
        *((issue_id, ATTRIBUTION_ROLES, "cited") for issue_id in sorted(attributed)),
        *((issue_id, REBUTTAL_ROLES, "rebutted") for issue_id in sorted(rebuts)),
    ):
        problems += _role_problems(where, issue_id, entry["rule_id"], roles, form, register)
    if section in BREAK_SECTIONS:
        problems += _effect_problems(where, attributed, register)
    problems += [
        f"{where}: cites {issue_id} in part but does not name the rest of the cause - a "
        "mixed-cause pair says which of its places are 'our defect' (with its OWNER) in "
        "the same reason"
        for issue_id in sorted(set(PARTIAL_CITATION.findall(reason)))
        if not OUR_SHARE.search(reason)
    ]
    return problems


def requirement_problems(entry: dict[str, Any], register: IssueRegister) -> list[str]:
    """A Basel 3.1 break on the subject of a failing issue that does not account for it."""
    if entry["regime"] != ISSUE_REGIME:
        return []
    reason = entry["reason"]
    accounted = cited(reason) | rebutted(reason)
    owed = [
        issue.id
        for issue in register.for_rule(FILING_MODULE, entry["rule_id"])
        # Not only the open ones: an issue the Bank fixes in a LATER release
        # leaves this release's rule as wrong as it was.
        if issue.effect == EFFECT_FAILS_CORRECT_RETURNS and issue.labels
    ]
    return [
        f"{entry['regime']}/{entry['rule_id']}: the rule is the subject of {issue_id} "
        f"(fails_correct_returns) and the reason neither cites it ('publisher issue "
        f"{issue_id}: ...') nor starts by rebutting it ('not {issue_id} - <our defect>')"
        for issue_id in owed
        if issue_id not in accounted
    ]


def blame_problems(entry: dict[str, Any]) -> list[str]:
    """A Basel 3.1 reason that blames the published rule without naming the issue."""
    if entry["regime"] != ISSUE_REGIME or not BLAMES_THE_RULE.search(entry["reason"]):
        return []
    if cited(entry["reason"]):
        return []
    return [
        f"{entry['regime']}/{entry['rule_id']}: calls its break a limit of the published "
        "rule but cites no publisher issue - cite the PI that evidences it, or, if none "
        "does, it is not established as the Bank's and must not say so"
    ]


# ---------------------------------------------------------------------------
# The committed register
# ---------------------------------------------------------------------------


def test_every_issue_cited_in_the_register_exists_and_names_the_entry_s_rule() -> None:
    """Every PI id in a rule entry's reason is a real issue, naming that rule in a citable role.

    Arrange: the committed register and the packaged 4.1.1 issue register.
    Act:     check every rule entry's PI references (all four rule sections).
    Assert:  none fails the grammar, names an unknown issue, or names an issue
             that does not list the entry's rule in the role the form needs.
    """
    # Arrange
    register, issues = _register(), _issues()

    # Act
    problems = [
        problem
        for section in RULE_SECTIONS
        for entry in register.get(section, [])
        for problem in citation_problems(section, entry, issues)
    ]

    # Assert
    assert not problems, "\n".join(problems)


def test_every_basel_3_1_break_on_the_subject_of_a_failing_issue_is_labelled() -> None:
    """A break on a Bank rule an issue says fails correct returns cites it or rebuts it.

    Arrange: the Basel 3.1 entries of known_broken_rules and known_gateway_breaks.
    Act:     find each issue that names the entry's rule as subject with the effect
             fails_correct_returns, and is not withdrawn.
    Assert:  each is cited or rebutted by the entry's reason.
    """
    # Arrange
    register, issues = _register(), _issues()

    # Act
    problems = [
        problem
        for section in BREAK_SECTIONS
        for entry in register.get(section, [])
        for problem in requirement_problems(entry, issues)
    ]

    # Assert
    assert not problems, "\n".join(problems)


def test_a_reason_that_blames_the_published_rule_names_the_issue() -> None:
    """'Limit of the published rule' is a claim; on a Bank rule it needs its evidence.

    Arrange: every Basel 3.1 rule entry.
    Act:     find reasons that blame the published rule.
    Assert:  each cites a publisher issue.
    """
    # Arrange
    register = _register()

    # Act
    problems = [
        problem
        for section in RULE_SECTIONS
        for entry in register.get(section, [])
        for problem in blame_problems(entry)
    ]

    # Assert
    assert not problems, "\n".join(problems)


def test_the_notes_and_template_entries_cite_only_issues_that_exist() -> None:
    """Text with no rule of its own may name issues, but only real ones.

    Arrange: the register's notes and its uncovered-template reasons.
    Act:     collect every PI id they name.
    Assert:  each is an issue of the 4.1.1 register.
    """
    # Arrange
    register, issues = _register(), _issues()
    texts = [
        *register.get("notes", {}).values(),
        *(entry["reason"] for entry in register.get("known_uncovered_templates", [])),
    ]

    # Act
    unknown = sorted(
        {issue_id for text in texts for issue_id in MENTION.findall(text)}
        - {issue.id for issue in issues.issues}
    )

    # Assert
    assert not unknown, f"the register's notes name issues that do not exist: {unknown}"


def test_the_register_explains_its_labels_to_its_reader() -> None:
    """The JSON says how to read a label, so a reader without this file can.

    Arrange: the register's notes header (written from REGISTER_NOTES on regen).
    Act:     read the label note.
    Assert:  it exists and states both forms.
    """
    # Arrange / Act
    note = _register().get("notes", {}).get(LABEL_NOTE, "")

    # Assert
    assert "publisher issue PI-" in note and "not PI-" in note, (
        f"notes.{LABEL_NOTE} is missing or does not state the two label forms; add it to "
        "REGISTER_NOTES in tests/acceptance/reporting/test_supervisory_validations.py and "
        "regenerate"
    )


# ---------------------------------------------------------------------------
# The check itself, on deliberately wrong entries
# ---------------------------------------------------------------------------


def test_the_check_rejects_an_issue_that_does_not_name_the_rule() -> None:
    """PI-23 is about OF 08.07; citing it on boe_b0346 (PI-26's subject) is wrong.

    Arrange: a wrong entry.
    Act:     check its citations.
    Assert:  one problem, naming the issue and the rule.
    """
    # Arrange
    entry = _entry("boe_b0346", "publisher issue PI-23: average LGD below the defaulted one")

    # Act
    problems = citation_problems("known_gateway_breaks", entry, _issues())

    # Assert
    assert len(problems) == 1 and "PI-23" in problems[0] and "boe_b0346" in problems[0]


def test_the_check_rejects_an_attribution_to_a_rule_the_issue_names_only_as_a_control() -> None:
    """PI-26 names boe_b0349 as a control: a correct return satisfies it, so no label.

    Arrange: an entry attributing a boe_b0349 break to PI-26.
    Act:     check its citations.
    Assert:  rejected for the role.
    """
    # Arrange
    entry = _entry("boe_b0349", "publisher issue PI-26: of-which above the total")

    # Act
    problems = citation_problems("known_gateway_breaks", entry, _issues())

    # Assert
    assert len(problems) == 1 and "control" in problems[0]


def test_the_check_accepts_a_rebuttal_of_a_control_and_of_a_subject() -> None:
    """The control form is the evidence the break is ours; the subject form disowns the issue.

    Arrange: two rebuttals, one of a control (PI-26 / boe_b0349), one of a
             subject (PI-23 / boe_b0778).
    Act:     check both, and the requirement for the subject.
    Assert:  nothing is reported.
    """
    # Arrange
    issues = _issues()
    control = _entry("boe_b0349", "not PI-26 - our defect: the subset is not a subset")
    subject = _entry("boe_b0778", "not PI-23 - our engine: an unreported share read as zero")

    # Act
    problems = [
        *citation_problems("known_gateway_breaks", control, issues),
        *citation_problems("known_broken_rules", subject, issues),
        *requirement_problems(subject, issues),
    ]

    # Assert
    assert problems == []


def test_the_check_rejects_an_unlabelled_break_on_the_subject_of_a_failing_issue() -> None:
    """boe_b0779 is PI-23's subject: an 'our defect' reason with no rebuttal is not enough.

    Arrange: an entry whose reason does not mention PI-23.
    Act:     check the requirement.
    Assert:  PI-23 is reported as owed.
    """
    # Arrange
    entry = _entry("boe_b0779", "our defect: the share column is summed down the rows")

    # Act
    problems = requirement_problems(entry, _issues())

    # Assert
    assert len(problems) == 1 and "PI-23" in problems[0]


def test_the_check_wants_the_rebuttal_at_the_start() -> None:
    """A rebuttal buried mid-sentence is not greppable as one, so it does not count.

    Arrange: an entry that says 'not PI-23' only after other words.
    Act:     check the citations and the requirement.
    Assert:  the mention is unclassified and PI-23 is still owed.
    """
    # Arrange
    entry = _entry("boe_b0779", "our defect, and not PI-23 - the share column is summed")

    # Act
    problems = [
        *citation_problems("known_broken_rules", entry, _issues()),
        *requirement_problems(entry, _issues()),
    ]

    # Assert
    assert len(problems) == 2 and all("PI-23" in problem for problem in problems)


def test_the_check_rejects_citing_and_rebutting_one_issue() -> None:
    """An entry cannot be both the issue and not the issue.

    Arrange: an entry that rebuts PI-23 and cites it.
    Act:     check its citations.
    Assert:  the contradiction is reported.
    """
    # Arrange
    entry = _entry("boe_b0779", "not PI-23 - ours; publisher issue PI-23 says otherwise")

    # Act
    problems = citation_problems("known_broken_rules", entry, _issues())

    # Assert
    assert problems == ["known_broken_rules b31/boe_b0779: PI-23 is both cited and rebutted"]


def test_the_check_rejects_an_issue_cited_on_a_crr_entry() -> None:
    """v09796_m under CRR is the EBA's rule, not one of the Bank's PRA001 rules.

    Arrange: a CRR entry citing an issue.
    Act:     check its citations.
    Assert:  rejected.
    """
    # Arrange
    entry = _entry("v09796_m", "publisher issue PI-23: shares do not total one", regime="crr")

    # Act
    problems = citation_problems("known_broken_rules", entry, _issues())

    # Assert
    assert len(problems) == 1 and "CRR" in problems[0]


def test_the_check_rejects_citing_an_issue_that_does_not_fail_correct_returns() -> None:
    """PI-33 says boe_b0359 PASSES wrong returns: it cannot be the cause of a break.

    ``rwa_filer.validate.issue_labels`` labels a FAIL only with an issue whose
    effect is ``fails_correct_returns``; a citation on a break is held to the same.

    Arrange: a gateway break on PI-33's subject, attributed to PI-33.
    Act:     check its citations.
    Assert:  rejected for the effect.
    """
    # Arrange
    entry = _entry("boe_b0359", "publisher issue PI-33: the range check is too wide")

    # Act
    problems = citation_problems("known_gateway_breaks", entry, _issues())

    # Assert
    assert len(problems) == 1 and "passes_wrong_returns" in problems[0]


def test_the_check_still_owes_a_label_for_an_issue_fixed_in_a_later_release() -> None:
    """A rule the Bank fixes in a later taxonomy is still wrong under 4.1.1.

    Arrange: the 4.1.1 register with PI-23 marked fixed in a later release, and an
             unlabelled break on its subject boe_b0779.
    Act:     check the requirement.
    Assert:  PI-23 is still owed.
    """
    # Arrange
    issues = _issues()
    pi23 = issues.issue("PI-23")
    assert pi23 is not None
    fixed = IssueRegister(
        release=issues.release,
        issues=(replace(pi23, status=STATUS_FIXED, fixed_in="9.9.9"),),
    )
    entry = _entry("boe_b0779", "our defect: the share column is summed down the rows")

    # Act
    problems = requirement_problems(entry, fixed)

    # Assert
    assert len(problems) == 1 and "PI-23" in problems[0]


def test_the_check_wants_our_share_named_beside_a_partial_citation() -> None:
    """A pair with two causes cites the issue 'in part' and names our share too.

    Arrange: a partial PI-29 citation on boe_b0356 that names no defect of ours,
             and the same citation followed by ours.
    Act:     check both entries' citations.
    Assert:  the first is rejected for the missing share; the second passes.
    """
    # Arrange
    issues = _issues()
    bare = _entry("boe_b0356", "publisher issue PI-29, in part: slotting rows have no PD")
    both = _entry(
        "boe_b0356",
        "publisher issue PI-29, in part: slotting rows have no PD; the other places are "
        "our defect, OWNER: P2.70",
    )

    # Act
    problems = citation_problems("known_gateway_breaks", bare, issues)
    accepted = citation_problems("known_gateway_breaks", both, issues)

    # Assert
    assert len(problems) == 1 and "in part" in problems[0]
    assert accepted == []


def test_the_check_rejects_a_blamed_rule_with_no_issue() -> None:
    """The old wording, 'limit of the published rule' with no evidence, is not a label.

    Arrange: a Basel 3.1 entry blaming the rule and citing nothing.
    Act:     check it.
    Assert:  rejected.
    """
    # Arrange
    entry = _entry("boe_b0703", "limit of the published rule, not of our output: ...")

    # Act
    problems = blame_problems(entry)

    # Assert
    assert len(problems) == 1 and "boe_b0703" in problems[0]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _register() -> dict[str, Any]:
    return json.loads(REGISTER_PATH.read_text(encoding="utf-8"))


def _issues() -> IssueRegister:
    return load_issues(FILING_TAXONOMY)


def _entry(rule_id: str, reason: str, *, regime: str = ISSUE_REGIME) -> dict[str, Any]:
    return {"regime": regime, "rule_id": rule_id, "reason": reason}


def _effect_problems(where: str, attributed: set[str], register: IssueRegister) -> list[str]:
    """Cited issues on a break whose effect cannot cause one."""
    problems = []
    for issue_id in sorted(attributed):
        issue = register.issue(issue_id)
        if issue is not None and issue.effect not in BREAK_EFFECTS:
            problems.append(
                f"{where}: {issue_id}'s effect is {issue.effect}, so it cannot be the cause "
                f"of a break; only an issue that {' or '.join(BREAK_EFFECTS)} can"
            )
    return problems


def _role_problems(
    where: str,
    issue_id: str,
    rule_id: str,
    roles: tuple[str, ...],
    form: str,
    register: IssueRegister,
) -> list[str]:
    issue = register.issue(issue_id)
    if issue is None:
        return [f"{where}: {issue_id} is not an issue of the {FILING_TAXONOMY} register"]
    if issue.status == STATUS_WITHDRAWN:
        return [f"{where}: {issue_id} is withdrawn - it is no longer considered an issue"]
    named = issue.rule(FILING_MODULE, rule_id)
    if named is None:
        return [f"{where}: {issue_id} does not name {rule_id}"]
    if named.role not in roles:
        return [
            f"{where}: {issue_id} names {rule_id} as a {named.role}; a rule may be {form} "
            f"only as {' or '.join(roles)}"
        ]
    return []
