"""
Each publisher issue's minimal correct return, held to Arelle — and the issue to its evidence.

Pipeline position:
    boe/data/issues/<release>.json (each issue's example)  ->  issue_returns.build_returns
        ->  the engine, and Arelle's counts kept in
            tests/releases/<release>/oracles/publisher_issues_oracle.json

An issue in the register is a claim about the Bank's published rules: that a
return which follows the reporting instructions fails a rule (or passes one it
should not, or never runs it). The claim is only as good as its evidence, so:
- each example is a well-formed return that writes and reads back unchanged,
  and is the return Arelle measured (fact count and content digest);
- the engine counts every rule exactly as Arelle did, on every example;
- the claim holds in ARELLE's counts: every subject rule of an issue that fails
  correct returns is unsatisfied at least once, one that passes wrong returns
  is satisfied and never unsatisfied, one that never runs is never evaluated;
  and every outcome an example states - a clarification's included - is the
  outcome Arelle measured.
  A release whose Bank fixes the rule turns this red — the issue must then be
  closed (``fixed_in``), not carried silently;
- the example is adequate (``.claude/LESSONS.md`` C11): beside the break, some
  rule of the issue holds, so the return is not simply wrong everywhere;
- every rule the write-up calls a control ("holds on the example") is measured
  on the example and holds there in Arelle's counts - an issue without an
  example has no control rule;
- every unsatisfied evaluation of a subject rule is inside the issue's
  footprint, so the footprint does not leave the issue's own example unexplained;
- the oracle holds one entry per example, no more, no fewer;
- an open issue of one shipped release is carried into the next, or closed.

These run in CI: Arelle was run once and its counts are kept, so nothing here
needs Arelle or the Bank's files.

References:
- rwa_filer.boe.issues — the register
- tests/issue_returns.py — the returns, and how the oracle is re-measured
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import pytest

from issue_returns import build_returns, oracle_path, pack_key
from rwa_filer.boe.engine import evaluate_rules, trace_rules
from rwa_filer.boe.issues import (
    EFFECT_FAILS_CORRECT_RETURNS,
    EFFECT_NEVER_RUNS,
    EFFECT_PASSES_WRONG_RETURNS,
    OUTCOME_NOT_EVALUATED,
    OUTCOME_SATISFIED,
    OUTCOME_UNSATISFIED,
    ROLE_CONTROL,
    STATUS_FIXED,
    load_issues,
)
from rwa_filer.release import release_rulebook, shipped_releases, version_key
from rwa_filer.taxonomy.pack import load_packaged
from rwa_filer.validate.identity import facts_sha256
from rwa_filer.validate.structure import check_structure
from rwa_filer.xbrl.reader import read_instance
from rwa_filer.xbrl.writer import write_instance

if TYPE_CHECKING:
    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.boe.issues import PublisherIssue
    from rwa_filer.model import CanonicalReturn

RELEASES = shipped_releases()

#: Where the engine is KNOWN to count a rule differently from Arelle on an
#: example, with why. Each is xfail(strict): it fails the suite the day the
#: engine agrees, so the entry is removed rather than left to rot.
KNOWN_DISAGREEMENTS: dict[tuple[str, str, str], str] = {
    ("4.1.1", "PI-10", "boe_b0770"): (
        "boe_b0770 is written 'i= sum(...)', which gives the summed rows no rounding "
        "allowance; the engine reads sum() as isum() and allows for them (PI-10's own "
        "finding about this engine)"
    ),
}


def _examples() -> list[tuple[str, str]]:
    return [
        (version, issue.id)
        for version in RELEASES
        for issue in load_issues(version).issues
        if issue.example is not None
    ]


EXAMPLES = _examples()
ISSUES = [(version, issue.id) for version in RELEASES for issue in load_issues(version).issues]


@pytest.fixture(scope="module")
def oracles() -> dict[str, dict[str, Any]]:
    return {
        version: json.loads(oracle_path(version).read_text(encoding="utf-8"))
        for version in RELEASES
    }


@pytest.fixture(scope="module")
def returns() -> dict[str, dict[str, tuple[str, CanonicalReturn]]]:
    return {version: build_returns(version) for version in RELEASES}


def _issue(version: str, issue_id: str) -> PublisherIssue:
    issue = load_issues(version).issue(issue_id)
    assert issue is not None
    return issue


def _rules(version: str, issue: PublisherIssue, module: str) -> list[Rule]:
    """The enforced rules the example is measured on."""
    assert issue.example is not None
    book = release_rulebook(version, module)
    assert book is not None
    return [rule for rule in book.enforced(module) if re.search(issue.example.rules, rule.rule_id)]


def _arelle(oracles: dict[str, Any], version: str, issue_id: str) -> dict[str, list[int]]:
    return oracles[version]["returns"][issue_id]["rules"]


@pytest.mark.parametrize(("version", "issue_id"), EXAMPLES)
def test_the_example_is_well_formed_and_is_the_return_arelle_measured(
    version: str, issue_id: str, oracles: dict[str, Any], returns: dict[str, Any]
) -> None:
    # Arrange
    module, ret = returns[version][issue_id]
    pack = load_packaged(pack_key(module, version))
    measured = oracles[version]["returns"][issue_id]

    # Act
    findings = check_structure(ret, pack)
    instance = write_instance(ret, pack)
    read = read_instance(instance.content, pack=pack)

    # Assert
    assert findings == [], f"{issue_id}: the example is not a well-formed return"
    assert write_instance(read.ret, read.pack).facts == instance.facts, (
        "the example does not read back as written"
    )
    assert (instance.facts, facts_sha256(ret)) == (
        measured["facts"],
        measured["facts_sha256"],
    ), f"{issue_id}: the example changed since Arelle measured it - re-measure the oracle"


@pytest.mark.parametrize(("version", "issue_id"), EXAMPLES)
def test_the_engine_counts_every_rule_as_arelle_counted_it(
    version: str, issue_id: str, oracles: dict[str, Any], returns: dict[str, Any]
) -> None:
    # Arrange
    module, ret = returns[version][issue_id]
    issue = _issue(version, issue_id)
    pack = load_packaged(pack_key(module, version))
    arelle = _arelle(oracles, version, issue_id)

    # Act
    native = {
        result.rule_id: [result.satisfied, result.unsatisfied]
        for result in evaluate_rules(ret, pack, _rules(version, issue, module))
    }

    # Assert
    unmeasured = {rule for rule in set(native) - set(arelle) if native[rule] != [0, 0]}
    assert unmeasured == set(), "the engine evaluated rules Arelle did not run"
    assert set(arelle) <= set(native), "Arelle ran rules the example is not measured on"
    differences = {
        rule: (arelle[rule], native[rule])
        for rule in arelle
        if native[rule] != arelle[rule] and (version, issue_id, rule) not in KNOWN_DISAGREEMENTS
    }
    assert differences == {}, f"(Arelle, engine) differ on {len(differences)} rule(s)"


@pytest.mark.parametrize(
    ("version", "issue_id", "rule_id"),
    [
        pytest.param(*key, marks=pytest.mark.xfail(strict=True, reason=reason))
        for key, reason in KNOWN_DISAGREEMENTS.items()
    ],
)
def test_a_known_disagreement_with_arelle_is_still_one(
    version: str, issue_id: str, rule_id: str, oracles: dict[str, Any], returns: dict[str, Any]
) -> None:
    # Arrange
    module, ret = returns[version][issue_id]
    book = release_rulebook(version, module)
    assert book is not None
    rule = book.rule(rule_id)
    assert rule is not None

    # Act
    result = evaluate_rules(ret, load_packaged(pack_key(module, version)), [rule])[0]

    # Assert
    assert [result.satisfied, result.unsatisfied] == _arelle(oracles, version, issue_id)[rule_id]


@pytest.mark.parametrize(("version", "issue_id"), EXAMPLES)
def test_arelle_shows_what_the_issue_claims_on_every_subject_rule(
    version: str, issue_id: str, oracles: dict[str, Any]
) -> None:
    """The forcing test: a release that fixes a rule turns this red until the issue is closed."""
    # Arrange
    issue = _issue(version, issue_id)
    arelle = _arelle(oracles, version, issue_id)
    subjects = [entry.rule_id for entry in issue.subject_rules]

    # Act
    unmeasured = [rule for rule in subjects if rule not in arelle]
    counts = {rule: arelle[rule] for rule in subjects if rule in arelle}

    # Assert
    if issue.effect == EFFECT_FAILS_CORRECT_RETURNS:
        assert unmeasured == []
        assert {rule for rule, (_sat, unsat) in counts.items() if unsat < 1} == set()
    elif issue.effect == EFFECT_PASSES_WRONG_RETURNS:
        assert unmeasured == []
        assert {rule for rule, (sat, unsat) in counts.items() if unsat or not sat} == set()
    elif issue.effect == EFFECT_NEVER_RUNS:
        assert {rule for rule, pair in counts.items() if pair != [0, 0]} == set()


@pytest.mark.parametrize(("version", "issue_id"), EXAMPLES)
def test_arelle_confirms_the_outcome_each_example_states(
    version: str, issue_id: str, oracles: dict[str, Any]
) -> None:
    """Every issue's example says what it shows - a clarification's as much as a defect's.

    A defect's subject rules are unsatisfied on its example (or satisfied / never
    evaluated, by its effect); a clarification's example shows the outcome of the
    reading it asks about; a control holds. Arelle's counts must agree, rule by rule.
    """
    # Arrange
    issue = _issue(version, issue_id)
    assert issue.example is not None
    arelle = _arelle(oracles, version, issue_id)

    # Act
    measured = {
        rule: (
            OUTCOME_UNSATISFIED
            if arelle.get(rule, [0, 0])[1]
            else OUTCOME_SATISFIED
            if arelle.get(rule, [0, 0])[0]
            else OUTCOME_NOT_EVALUATED
        )
        for rule in issue.example.outcome
    }

    # Assert
    assert issue.example.outcome, f"{issue_id}: the example states no outcome"
    assert {entry.rule_id for entry in issue.subject_rules} <= set(issue.example.outcome), (
        f"{issue_id}: a subject rule has no stated outcome"
    )
    assert measured == dict(issue.example.outcome)


@pytest.mark.parametrize(("version", "issue_id"), EXAMPLES)
def test_the_example_is_adequate_some_rule_of_the_issue_holds_on_it(
    version: str, issue_id: str, oracles: dict[str, Any]
) -> None:
    """A return that broke everything would prove nothing about one rule (LESSONS C11)."""
    # Arrange
    issue = _issue(version, issue_id)
    arelle = _arelle(oracles, version, issue_id)
    if issue.effect != EFFECT_FAILS_CORRECT_RETURNS:
        pytest.skip("only a break needs a control beside it")

    # Act
    controls = {entry.rule_id for entry in issue.rules if entry.role == ROLE_CONTROL}
    holding = sorted(rule for rule, (satisfied, _unsat) in arelle.items() if satisfied >= 1)

    # Assert
    assert holding, f"{issue_id}: no rule the example is measured on holds anywhere on it"
    assert not controls & set(arelle) or controls & set(holding), (
        f"{issue_id}: every control rule measured on the example fails"
    )


@pytest.mark.parametrize(("version", "issue_id"), ISSUES)
def test_every_control_rule_is_measured_on_the_example_and_holds_there(
    version: str, issue_id: str, oracles: dict[str, Any]
) -> None:
    """The write-up says a control rule "holds on the example": Arelle must have said so.

    So an issue with a control rule has an example, the rule is one the example
    is measured on, and Arelle counts it satisfied and never unsatisfied there.
    A rule the example cannot speak to (not evaluated, not measured, or no
    example at all) is "related", not a control.
    """
    # Arrange
    issue = _issue(version, issue_id)
    controls = [entry.rule_id for entry in issue.rules if entry.role == ROLE_CONTROL]
    arelle = _arelle(oracles, version, issue_id) if issue.example is not None else {}

    # Act
    unshown = [
        rule
        for rule in controls
        if arelle.get(rule, [0, 0])[0] < 1 or arelle.get(rule, [0, 0])[1] > 0
    ]

    # Assert
    assert unshown == [], f"{issue_id}: Arelle does not show these controls holding"


@pytest.mark.parametrize(("version", "issue_id"), EXAMPLES)
def test_every_break_of_a_subject_rule_on_the_example_is_inside_the_footprint(
    version: str, issue_id: str, returns: dict[str, Any]
) -> None:
    # Arrange
    module, ret = returns[version][issue_id]
    issue = _issue(version, issue_id)
    book = release_rulebook(version, module)
    assert book is not None
    subjects = {entry.rule_id: entry for entry in issue.subject_rules}
    rules = [rule for rule_id in subjects if (rule := book.rule(rule_id)) is not None]

    # Act
    trace = trace_rules(ret, load_packaged(pack_key(module, version)), rules)
    outside = [
        evaluation.rule_id
        for evaluation in trace.evaluations
        if not evaluation.holds and not subjects[evaluation.rule_id].inside(evaluation.cells)
    ]

    # Assert
    assert outside == [], "the footprint leaves the issue's own example unexplained"


@pytest.mark.parametrize("version", RELEASES)
def test_the_oracle_holds_one_entry_per_example(version: str, oracles: dict[str, Any]) -> None:
    # Act
    measured = set(oracles[version]["returns"])
    examples = {issue_id for item, issue_id in EXAMPLES if item == version}

    # Assert
    assert measured == examples


def test_an_open_issue_is_carried_into_the_next_release_or_closed() -> None:
    """Vacuous while one release ships: it binds the day a second one does.

    For consecutive shipped releases A < B, every issue still open in A is in B's
    register (where its own example must again show it) or is recorded in A as
    fixed in B. An issue cannot vanish between releases.
    """
    # Arrange
    ordered = sorted(RELEASES, key=version_key)

    # Act
    dropped = [
        f"{older}: {issue.id}"
        for older, newer in zip(ordered, ordered[1:], strict=False)
        for issue in load_issues(older).issues
        if issue.is_open
        and load_issues(newer).issue(issue.id) is None
        and not (issue.status == STATUS_FIXED and issue.fixed_in == newer)
    ]

    # Assert
    assert dropped == []
