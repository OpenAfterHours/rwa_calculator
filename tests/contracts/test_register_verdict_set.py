"""
The supervisory register's verdict set — legs (m)/(n), driven without a pipeline.

Pipeline position:
    (no pipeline stage — drives the register's verdict-set predicates and legs
    with synthetic sets, and reads the committed register; nothing here runs a
    pipeline)
    validation_known_breaks.json rules_with_a_verdict  <->  legs (m)/(n)

The register (``tests/acceptance/reporting/test_supervisory_validations.py``)
holds, in ``rules_with_a_verdict``, every (regime, rule) that the template-level
engine brings to PASS, FAIL or VACUOUS on at least one run of ``RUNS``. Leg (m)
fails when a listed rule reaches no verdict on any run - the ``PASS ->
NOT_EVALUATED`` move that legs (a)-(g) cannot see, nor the gateway legs unless
the gateway engine itself then fails the rule - and leg (n) when a rule with a
verdict is not listed, so the set cannot go stale under (m).

Watching either leg fail through the acceptance file costs the whole run matrix
and a fixture change. These tests drive the two predicates, the two legs
and the section's read/write path with synthetic sets in milliseconds, so both
directions are demonstrated on every run rather than argued from the code. Four
properties are pinned:

- the DIRECTION of each predicate. Leg (m) fails on what LEAVES the measured set
  (``diff().removed``); its sibling under it in the module, leg (f)'s
  ``_rules_newly_vacuous``, fails on what JOINS its population
  (``diff().added``). Copying the sibling would point (m) the wrong way;
- the SET, not the count. One rule lost and another gained leaves every count
  where it was - the netting that lets ``scripts/coverage_report.py``'s
  ``never_evaluated_rules`` / ``union_binding_rules_*`` counts miss a darkened
  rule (``.claude/LESSONS.md`` B8, C8) - and both must still be reported;
- the REGIME in the key. 85 rule ids appear in both published extracts, so a set
  of bare ids would let a CRR rule going dark hide behind its Basel 3.1 twin;
- fail-CLOSED on an absent section. With nothing banked, (m) would have nothing
  to lose and would pass whatever went dark.

The last test reads the committed register: every rule it banks as broken or as
vacuous reached a verdict (FAIL or VACUOUS), so it must be listed as evaluated
too. A hand edit that drops a rule from the verdict set while it still breaks is
caught here without the pipeline.

References:
- tests/acceptance/reporting/test_supervisory_validations.py — the register, legs (m)/(n)
- scripts/tolerated_findings.py — the shared ``diff``
- .claude/LESSONS.md B8 (ratchet the accumulator), C12 (watch a gate fail)
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
import tests.acceptance.reporting.test_supervisory_validations as register
from tests.acceptance.reporting.test_supervisory_validations import (
    BASELINE_PATH,
    EVALUATED_SECTION,
    GateRun,
    RuleKey,
    RunVerdicts,
    _baseline_from,
    _rule_set,
    _rule_set_entries,
    _rules_newly_evaluated,
    _rules_newly_unevaluated,
)

# Imported under names pytest does not collect: they are the register's legs, and
# collected here they would ask for the register's whole-matrix ``gate_run`` fixture.
from tests.acceptance.reporting.test_supervisory_validations import (
    test_no_banked_rule_loses_its_last_verdict as leg_m,
)
from tests.acceptance.reporting.test_supervisory_validations import (
    test_no_rule_reaches_a_verdict_without_being_banked as leg_n,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

#: The bullet's worked example: v3335_i has a verdict on crr/rich alone, v0207_m on
#: every CRR run, and a C 02.00 r0160 row-drop darkens both on crr/rich.
LAST_VERDICT = RuleKey("crr", "v3335_i")
STILL_EVALUATED = RuleKey("crr", "v0207_m")
FIRST_VERDICT = RuleKey("crr", "v9999_x")

#: An id both published extracts carry (``v09779_m``, the C 08.04 flow rule).
SHARED_ID = "v09779_m"


def _gate(evaluated: frozenset[RuleKey], runs: tuple[RunVerdicts, ...] = ()) -> GateRun:
    """A gate result holding only a verdict set and the runs behind it — all (m)/(n) read."""
    return GateRun(
        broken={},
        uncovered={},
        summary={},
        vacuous={},
        gateway={},
        disagreements={},
        evaluated=evaluated,
        runs=runs,
    )


def _run(portfolio: str, *outcomes: tuple[RuleKey, str, str]) -> RunVerdicts:
    """One CRR run whose template-level report holds ``(rule, severity, status)`` outcomes.

    Only the three fields the legs' messages read are set; the report is a stand-in
    for ``ValidationReport``, which a synthetic case has no bundle to build.
    """
    report = SimpleNamespace(
        outcomes=tuple(
            SimpleNamespace(rule_id=key.rule_id, severity=severity, status=status)
            for key, severity, status in outcomes
        )
    )
    return RunVerdicts("crr", portfolio, report, {}, {})  # type: ignore[arg-type]


def _bank(path: Path, keys: frozenset[RuleKey] | None) -> Path:
    """Write a register holding ``keys`` as its verdict set, or no section at all."""
    payload = {} if keys is None else {EVALUATED_SECTION: _rule_set_entries(keys)}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The two predicates
# ---------------------------------------------------------------------------


def test_leg_m_names_the_banked_rule_that_lost_its_last_verdict() -> None:
    """A banked rule evaluated nowhere is leg (m)'s finding, and only that rule.

    Arrange: a bank of two rules; the estate still evaluates one and has gained another.
    Act:     ask leg (m)'s predicate what left.
    Assert:  exactly the rule with no verdict, not the one gained.
    """
    # Arrange
    banked = {LAST_VERDICT, STILL_EVALUATED}
    measured = {STILL_EVALUATED, FIRST_VERDICT}

    # Act
    dark = _rules_newly_unevaluated(measured, banked)

    # Assert
    assert dark == (LAST_VERDICT,)


def test_leg_n_names_the_rule_that_reached_its_first_verdict() -> None:
    """A rule with a verdict that the bank does not list is leg (n)'s finding, and only that.

    Arrange: the same bank and estate as leg (m)'s case.
    Act:     ask leg (n)'s predicate what joined.
    Assert:  exactly the gained rule, not the one that went dark.
    """
    # Arrange
    banked = {LAST_VERDICT, STILL_EVALUATED}
    measured = {STILL_EVALUATED, FIRST_VERDICT}

    # Act
    gained = _rules_newly_evaluated(measured, banked)

    # Assert
    assert gained == (FIRST_VERDICT,)


def test_one_rule_lost_and_one_gained_is_reported_both_ways_though_no_count_moved() -> None:
    """The netting a count ratchet cannot see is two findings here, not zero.

    Arrange: an estate that lost one rule and gained another, so its size is unchanged.
    Act:     run both predicates.
    Assert:  each reports its rule.
    """
    # Arrange
    banked = {LAST_VERDICT, STILL_EVALUATED}
    measured = {STILL_EVALUATED, FIRST_VERDICT}
    assert len(measured) == len(banked), "the case must hold every count still to mean anything"

    # Act
    moves = (_rules_newly_unevaluated(measured, banked), _rules_newly_evaluated(measured, banked))

    # Assert
    assert moves == ((LAST_VERDICT,), (FIRST_VERDICT,))


def test_a_crr_rule_going_dark_is_not_hidden_by_its_basel_3_1_twin() -> None:
    """The key is (regime, rule_id): an id shared by both extracts is two rules.

    Arrange: the CRR rule has gone dark while its Basel 3.1 namesake is still evaluated.
    Act:     ask leg (m)'s predicate what left.
    Assert:  the CRR rule.
    """
    # Arrange
    banked = {RuleKey("crr", SHARED_ID), RuleKey("b31", SHARED_ID)}
    measured = {RuleKey("b31", SHARED_ID)}

    # Act
    dark = _rules_newly_unevaluated(measured, banked)

    # Assert
    assert dark == (RuleKey("crr", SHARED_ID),)


# ---------------------------------------------------------------------------
# The two legs, on a register written to a temporary file
# ---------------------------------------------------------------------------


def test_leg_m_fails_naming_a_banked_rule_no_run_evaluates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leg (m) itself, not only its predicate, goes red on the bullet's example.

    Arrange: a register banking v3335_i and v0207_m; an estate evaluating only v0207_m.
    Act:     run leg (m).
    Assert:  it fails, naming v3335_i.
    """
    # Arrange
    banked = frozenset({LAST_VERDICT, STILL_EVALUATED})
    monkeypatch.setattr(register, "BASELINE_PATH", _bank(tmp_path / "register.json", banked))

    # Act / Assert
    with pytest.raises(AssertionError, match=r"reach NO verdict on any run[\s\S]*crr/v3335_i"):
        leg_m(_gate(frozenset({STILL_EVALUATED})))


def test_leg_n_fails_naming_a_rule_the_register_does_not_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leg (n) itself goes red on a verdict the register does not hold.

    Arrange: a register banking v0207_m; an estate evaluating it and one rule more.
    Act:     run leg (n) on a gate whose only run evaluates both.
    Assert:  it fails, naming the new rule and the verdict it reached.
    """
    # Arrange
    banked = frozenset({STILL_EVALUATED})
    monkeypatch.setattr(register, "BASELINE_PATH", _bank(tmp_path / "register.json", banked))
    rich = _run("rich", (STILL_EVALUATED, "ERROR", "PASS"), (FIRST_VERDICT, "ERROR", "PASS"))

    # Act / Assert
    with pytest.raises(AssertionError, match=r"does not list[\s\S]*crr/v9999_x  \[ERROR\] PASS"):
        leg_n(_gate(frozenset({STILL_EVALUATED, FIRST_VERDICT}), (rich,)))


@pytest.mark.parametrize("leg", [leg_m, leg_n], ids=["leg_m", "leg_n"])
def test_both_legs_refuse_a_register_with_no_verdict_set(
    leg: Callable[[GateRun], None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the section absent each leg fails rather than holding nothing.

    Leg (m) is the one that matters: with nothing banked it has nothing to lose,
    and would pass whatever went dark.

    Arrange: a register with no rules_with_a_verdict section.
    Act:     run the leg on an estate that evaluates nothing at all.
    Assert:  it fails, saying the section is missing.
    """
    # Arrange
    monkeypatch.setattr(register, "BASELINE_PATH", _bank(tmp_path / "register.json", None))

    # Act / Assert
    with pytest.raises(AssertionError, match=f"holds no {EVALUATED_SECTION} section"):
        leg(_gate(frozenset()))


# ---------------------------------------------------------------------------
# The section's read / write path
# ---------------------------------------------------------------------------


def test_the_section_reads_back_the_set_it_was_written_from() -> None:
    """REGEN's writer and the legs' reader agree, regime by regime.

    Arrange: a set holding a shared id under both regimes.
    Act:     write it as the register holds it and read it back.
    Assert:  the same set, written per regime and sorted.
    """
    # Arrange
    keys = frozenset({RuleKey("crr", SHARED_ID), RuleKey("b31", SHARED_ID), LAST_VERDICT})

    # Act
    entries = _rule_set_entries(keys)
    read_back = _baseline_from({EVALUATED_SECTION: entries}).evaluated

    # Assert
    assert (entries, read_back) == (
        {"b31": [SHARED_ID], "crr": [SHARED_ID, LAST_VERDICT.rule_id]},
        keys,
    )


def test_a_rule_listed_twice_is_refused() -> None:
    """A repeated id is a hand edit REGEN never makes, so it is refused, not deduplicated.

    Arrange: a section listing one CRR rule twice.
    Act:     read it.
    Assert:  ValueError naming the rule.
    """
    # Arrange
    section = {"crr": [LAST_VERDICT.rule_id, LAST_VERDICT.rule_id]}

    # Act / Assert
    with pytest.raises(ValueError, match="crr/v3335_i"):
        _rule_set(EVALUATED_SECTION, section)


# ---------------------------------------------------------------------------
# The committed register
# ---------------------------------------------------------------------------


def test_every_banked_break_and_vacuity_is_listed_as_evaluated() -> None:
    """A rule the register banks as FAIL or VACUOUS somewhere reached a verdict there.

    So ``known_broken_rules`` and ``known_vacuous_rules`` must both sit inside
    ``rules_with_a_verdict``. This is the fast check that the section is banked
    at all and that no hand edit has dropped a rule from it while the rule still
    breaks or holds vacuously.

    Arrange: the committed register.
    Act:     find banked broken or vacuous rules absent from the verdict set.
    Assert:  there are none.
    """
    # Arrange
    baseline = _baseline_from(json.loads(BASELINE_PATH.read_text(encoding="utf-8")))

    # Act
    unlisted = sorted((set(baseline.rules) | set(baseline.vacuous)) - baseline.evaluated)

    # Assert
    assert not unlisted, (
        f"{len(unlisted)} rule(s) banked as broken or vacuous are not under "
        f"{EVALUATED_SECTION} in {BASELINE_PATH.name}, though each reached a verdict:\n  "
        + "\n  ".join(key.describe() for key in unlisted)
        + "\nRe-bank with REGEN_VALIDATION_BASELINE=1; never edit the section by hand."
    )
