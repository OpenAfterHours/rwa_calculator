"""
The two ratchets that hold the Bank's gateway verdicts name the same Error breaks.

Pipeline position:
    (no pipeline stage — reads two committed JSON files and drives four
    predicates with synthetic pairs; nothing here runs a pipeline)
    validation_known_breaks.json known_gateway_breaks  <->  filing_mapping_baseline.json

Two committed files hold what the gateway engine (``rwa_filer.boe``, pinned to
Arelle) finds broken on our filed Basel 3.1 returns:

- ``tests/expected_outputs/reporting/validation_known_breaks.json``,
  ``known_gateway_breaks`` — every (rule, portfolio) pair, Error and Warning,
  each with a written reason; ratcheted by legs (h)/(i) of
  ``tests/acceptance/reporting/test_supervisory_validations.py``;
- ``scripts/filing_mapping_baseline.json``, ``error_rules_by_rule`` — the Error
  breaks as a count of portfolios per rule; ratcheted by
  ``scripts/filing_mapping_report.py --check``.

Both are measured through one function
(``scripts/filing_mapping_report.py::file_on_gateway``), but each is re-banked
by its own command, and before this test nothing stopped one moving without the
other: 52 gateway breaks sat in the second file as bare counts with no reason
and no portfolio, and ``boe_b1055`` spreading from two portfolios to seven was
found by a review, not by a gate (design record O-03). So this holds the Error
half of the first equal to the second, rule for rule and count for count, over
the same portfolio matrix. A change that re-banks one re-banks the other in the
same commit, or this fails.

Known divergence to watch: the register files the COREP generated WITH the
prior-period frame (it is the bundle the template leg reads), the filing-mapping
ratchet WITHOUT one. Verdicts are identical today because C 08.04 is not placed
(P2.73); when it is, this test is where the difference first shows.

The six gateway predicates are driven here too, with synthetic pairs: watching
legs (h)-(l) fail through the acceptance file costs thirty pipeline runs, while
four predicates are a set difference and two a count comparison that these tests
can feed directly, including the ``boe_b1055`` shape (a banked rule breaking on
one more portfolio) and leg (l)'s (a banked pair failing in one more place: the
key does not move, the ``by_portfolio`` unsatisfied count does). So is the
path that records a gateway result (``_gateway_findings``), with results passed
through the Bank's deny list (``apply_deny_list``): a downgraded rule is recorded
at WARNING, a deactivated one not at all, and a banked ERROR the Bank downgrades
moves legs (h) and (i). No packaged PRA001 deny list downgrades a rule today, so
no registered portfolio exercises that path.

And the register must read back whole: ``_baseline_from`` refuses a key held by
two entries (one (rule, portfolio, severity) under two reasons), which a hand
edit of one entry's reason can leave behind and a plain dict would resolve by
silently keeping the last reason; and every committed gateway pair must carry
its banked count, or leg (l) is blind to that pair.

References:
- tests/acceptance/reporting/test_supervisory_validations.py — the register and its legs
- scripts/filing_mapping_report.py — the filing-mapping ratchet and ``file_on_gateway``
- docs/development/workspace.md — how the gates relate
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from tests.acceptance.reporting.test_supervisory_validations import (
    BASELINE_PATH as REGISTER_PATH,
)
from tests.acceptance.reporting.test_supervisory_validations import (
    GATEWAY_FRAMEWORK,
    GATEWAY_REGIME,
    RUNS,
    CountMove,
    DisagreementKey,
    GatewayKey,
    _baseline_from,
    _disagreements_added,
    _disagreements_removed,
    _gateway_breaks_added,
    _gateway_breaks_removed,
    _gateway_counts_fallen,
    _gateway_counts_risen,
    _gateway_findings,
)

from rwa_calc.reporting.filing.canonical import FILING_MODULE
from rwa_filer.boe.deny import DENY_DEACTIVATED, DENY_DOWNGRADED, DenyEntry, DenyList
from rwa_filer.boe.engine import STATUS_FAIL, RuleResult
from rwa_filer.validate.execution import apply_deny_list

REPO_ROOT = Path(__file__).resolve().parents[2]
FILING_BASELINE_PATH = REPO_ROOT / "scripts" / "filing_mapping_baseline.json"

GATEWAY_SECTION = "known_gateway_breaks"
DISAGREEMENT_SECTION = "known_engine_disagreements"
ERROR = "ERROR"

REBANK = (
    "Re-bank BOTH in the same change, from the same tree:\n"
    "  REGEN_VALIDATION_BASELINE=1 uv run pytest "
    "tests/acceptance/reporting/test_supervisory_validations.py -n 0\n"
    "  uv run python scripts/filing_mapping_report.py --update-baseline\n"
    "and write a reason for every new known_gateway_breaks pair."
)


def _register() -> dict[str, Any]:
    return json.loads(REGISTER_PATH.read_text(encoding="utf-8"))


def _filing_baseline() -> dict[str, Any]:
    return json.loads(FILING_BASELINE_PATH.read_text(encoding="utf-8"))


def _error_portfolios_by_rule(register: dict[str, Any]) -> dict[str, int]:
    """The register's Error gateway breaks, as the filing baseline counts them."""
    pairs: dict[str, set[str]] = {}
    for entry in register.get(GATEWAY_SECTION, []):
        if entry["severity"] == ERROR:
            pairs.setdefault(entry["rule_id"], set()).update(entry["portfolios"])
    return {rule_id: len(portfolios) for rule_id, portfolios in sorted(pairs.items())}


# ---------------------------------------------------------------------------
# The two committed files agree
# ---------------------------------------------------------------------------


def test_the_register_and_the_filing_mapping_baseline_name_the_same_error_breaks() -> None:
    """Every Error rule, with the same number of portfolios, on both sides.

    Arrange: the register's known_gateway_breaks and the filing baseline.
    Act:     count the register's Error pairs per rule.
    Assert:  the counts equal error_rules_by_rule exactly.
    """
    # Arrange
    register = _register()
    banked = _filing_baseline()["error_rules_by_rule"]

    # Act
    held = _error_portfolios_by_rule(register)

    # Assert
    differences = {
        rule_id: (held.get(rule_id, 0), banked.get(rule_id, 0))
        for rule_id in sorted(set(held) | set(banked))
        if held.get(rule_id, 0) != banked.get(rule_id, 0)
    }
    detail = "\n".join(
        f"  {rule_id}: register {mine} portfolio(s), filing baseline {theirs}"
        for rule_id, (mine, theirs) in differences.items()
    )
    assert not differences, (
        f"{GATEWAY_SECTION} and error_rules_by_rule disagree on {len(differences)} Error "
        f"rule(s):\n{detail}\n{REBANK}"
    )


def test_the_two_files_were_measured_over_the_register_s_basel_3_1_runs() -> None:
    """Both files speak of the Basel 3.1 runs in RUNS, and of nothing else.

    A gateway pair on a portfolio the filing baseline never measured would make
    the count comparison above meaningless, and so would a filing baseline
    measured over another matrix.

    Arrange: the B31 portfolios in RUNS, the filing baseline's provenance, and
             every portfolio either gateway section names.
    Act:     compare them.
    Assert:  provenance is exactly the B31 RUNS portfolios, and every portfolio
             the register names is one of them.
    """
    # Arrange
    runs = [run.portfolio for run in RUNS if run.framework == GATEWAY_FRAMEWORK]
    provenance = [item["portfolio"] for item in _filing_baseline()["provenance"]["portfolios"]]
    register = _register()
    named = {
        portfolio
        for section in (GATEWAY_SECTION, DISAGREEMENT_SECTION)
        for entry in register.get(section, [])
        for portfolio in entry["portfolios"]
    }
    regimes = {
        entry["regime"]
        for section in (GATEWAY_SECTION, DISAGREEMENT_SECTION)
        for entry in register.get(section, [])
    }

    # Act
    unknown = sorted(named - set(runs))

    # Assert
    assert provenance == runs, (
        "scripts/filing_mapping_baseline.json was measured over another matrix than the "
        f"register's Basel 3.1 runs.\n{REBANK}"
    )
    assert not unknown, f"the gateway sections name portfolios no B31 run has: {unknown}"
    assert regimes <= {GATEWAY_REGIME}, f"a gateway entry outside Basel 3.1: {sorted(regimes)}"


def test_the_gateway_section_is_banked_at_all() -> None:
    """An absent or empty section must not pass the agreement test by accident.

    The count comparison would also hold with both sides empty; the filing
    baseline is not empty, so neither may the register's section be.

    Arrange: the register.
    Act:     read the section.
    Assert:  it exists and holds at least one Error pair.
    """
    # Arrange / Act
    held = _error_portfolios_by_rule(_register())

    # Assert
    assert held, f"{REGISTER_PATH.name} holds no Error entry under {GATEWAY_SECTION}.\n{REBANK}"


# ---------------------------------------------------------------------------
# The predicates behind legs (h)-(l), driven synthetically
# ---------------------------------------------------------------------------


def test_a_gateway_break_on_one_more_portfolio_is_new() -> None:
    """The boe_b1055 shape: a banked rule that spreads is a new break, not a held one.

    Arrange: a baseline holding the rule on two portfolios; a measurement on three.
    Act:     ask for the added pairs.
    Assert:  exactly the third portfolio's pair.
    """
    # Arrange
    baseline = {
        GatewayKey("boe_b1055", "crm-substitution", "ERROR"): "a reason",
        GatewayKey("boe_b1055", "irb-shapes", "ERROR"): "a reason",
    }
    measured = {
        GatewayKey("boe_b1055", "crm-substitution", "ERROR"): None,
        GatewayKey("boe_b1055", "irb-shapes", "ERROR"): None,
        GatewayKey("boe_b1055", "rich", "ERROR"): None,
    }

    # Act
    added = _gateway_breaks_added(measured, baseline)

    # Assert
    assert added == (GatewayKey("boe_b1055", "rich", "ERROR"),)


def test_a_gateway_break_that_has_gone_is_reported_as_removed() -> None:
    """A fix on one portfolio removes that pair and leaves the rule's other pairs held.

    Arrange: a baseline on two portfolios; a measurement on one.
    Act:     ask for the removed and the added pairs.
    Assert:  the fixed pair is removed and nothing is added.
    """
    # Arrange
    baseline = {
        GatewayKey("boe_b0742", "facility-share-binding", "ERROR"): "a reason",
        GatewayKey("boe_b0742", "irb-shapes", "ERROR"): "a reason",
    }
    measured = {GatewayKey("boe_b0742", "irb-shapes", "ERROR"): None}

    # Act
    removed = _gateway_breaks_removed(measured, baseline)
    added = _gateway_breaks_added(measured, baseline)

    # Assert
    assert (removed, added) == ((GatewayKey("boe_b0742", "facility-share-binding", "ERROR"),), ())


def test_a_disagreement_that_changes_direction_is_new_and_the_old_one_gone() -> None:
    """The verdicts are part of the key, so a flip is never read as 'still held'.

    Arrange: a banked template-FAIL / gateway-PASS pair; a measurement where
             the same rule and portfolio disagree the other way.
    Act:     ask for the added and the removed disagreements.
    Assert:  the flipped pair is added and the banked one removed.
    """
    # Arrange
    before = DisagreementKey("boe_b0778", "netting", "FAIL", "PASS")
    after = DisagreementKey("boe_b0778", "netting", "PASS", "FAIL")

    # Act
    added = _disagreements_added({after: None}, {before: "a reason"})
    removed = _disagreements_removed({after: None}, {before: "a reason"})

    # Assert
    assert (added, removed) == ((after,), (before,))


def test_a_downgraded_rule_is_recorded_at_its_downgraded_severity() -> None:
    """The gateway leg records a break as the gateway runs it, after the deny list.

    No packaged PRA001 deny list downgrades a rule today, so no registered
    portfolio exercises this path; a synthetic result does.

    Arrange: an ERROR break, and a deny list downgrading its rule before the run date.
    Act:     apply the deny list and record the result as the gateway leg does.
    Assert:  one break, at WARNING.
    """
    # Arrange
    results = _as_the_gateway_runs([_error_break("boe_b0742")], DENY_DOWNGRADED)

    # Act
    breaks, _opposed = _gateway_findings("irb-shapes", results, {})

    # Assert
    assert [fact.severity for fact in breaks.values()] == ["WARNING"]


def test_a_deactivated_rule_never_enters_the_gateway_section() -> None:
    """A rule the Bank switched off is NOT_EVALUATED at the gateway: no break, no entry.

    Arrange: an ERROR break, and a deny list deactivating its rule before the run date.
    Act:     apply the deny list and record the result.
    Assert:  nothing is recorded.
    """
    # Arrange
    results = _as_the_gateway_runs([_error_break("boe_b0710")], DENY_DEACTIVATED)

    # Act
    breaks, opposed = _gateway_findings("rich", results, {})

    # Assert
    assert (breaks, opposed) == ({}, {})


def test_a_banked_error_the_bank_downgrades_is_a_new_break_and_the_old_one_gone() -> None:
    """Severity is part of the gateway key, so a downgrade cannot pass unnoticed.

    A reason written for an ERROR ("rejects the return") is wrong for a WARNING,
    and the filing-mapping ratchet counts Error breaks only, so legs (h)/(i) are
    the gate that must see the move; REGEN then brings the pair back unclassified.

    Arrange: a register holding boe_b0742/irb-shapes at ERROR; the same break
             measured after a downgrade.
    Act:     ask legs (h)/(i)'s predicates for the added and removed pairs.
    Assert:  the WARNING pair is added and the ERROR pair removed.
    """
    # Arrange
    banked = _baseline_from(
        {
            "known_gateway_breaks": [
                {
                    "rule_id": "boe_b0742",
                    "severity": "ERROR",
                    "reason": "a reason",
                    "portfolios": ["irb-shapes"],
                }
            ]
        }
    ).gateway
    results = _as_the_gateway_runs([_error_break("boe_b0742")], DENY_DOWNGRADED)
    measured, _opposed = _gateway_findings("irb-shapes", results, {})

    # Act
    added = _gateway_breaks_added(measured, banked)
    removed = _gateway_breaks_removed(measured, banked)

    # Assert
    assert (added, removed) == (tuple(measured), tuple(banked))


def test_a_banked_pair_failing_in_one_more_place_has_risen() -> None:
    """Leg (l): the pair's key is unchanged, so (h)/(i) see nothing; its count rose.

    Arrange: a banked pair at 2 unsatisfied; the same pair measured at 3.
    Act:     ask legs (h), (i) and (l)'s predicates.
    Assert:  (h) and (i) report nothing; (l) reports the rise with both counts.
    """
    # Arrange
    key = GatewayKey("boe_b0793", "rich", "ERROR")
    banked, measured = {key: 2}, {key: 3}

    # Act
    moved = (_gateway_breaks_added(measured, banked), _gateway_breaks_removed(measured, banked))
    risen = _gateway_counts_risen(measured, banked)

    # Assert
    assert moved == ((), ())
    assert risen == (CountMove(key, banked=2, measured=3),)
    assert risen[0].describe() == "b31/rich: boe_b0793 [ERROR]: 2 -> 3 unsatisfied"


def test_a_banked_pair_failing_in_fewer_places_has_fallen_and_not_risen() -> None:
    """A fall is progress: leg (l) passes on it and reports it for REGEN to bank.

    Arrange: a banked pair at 4 unsatisfied; the same pair measured at 1.
    Act:     ask for the risen and the fallen counts.
    Assert:  nothing has risen; the fall is reported with both counts.
    """
    # Arrange
    key = GatewayKey("boe_b0356", "irb-shapes", "WARNING")
    banked, measured = {key: 4}, {key: 1}

    # Act
    risen = _gateway_counts_risen(measured, banked)
    fallen = _gateway_counts_fallen(measured, banked)

    # Assert
    assert (risen, fallen) == ((), (CountMove(key, banked=4, measured=1),))


def test_a_pair_on_one_side_only_is_not_a_count_move() -> None:
    """A new or a gone pair is (h)'s or (i)'s finding, never (l)'s.

    Arrange: one pair banked only, another measured only.
    Act:     ask for the risen and the fallen counts.
    Assert:  neither reports anything.
    """
    # Arrange
    banked = {GatewayKey("boe_b0742", "irb-shapes", "ERROR"): 2}
    measured = {GatewayKey("boe_b1055", "rich", "ERROR"): 5}

    # Act
    moved = (_gateway_counts_risen(measured, banked), _gateway_counts_fallen(measured, banked))

    # Assert
    assert moved == ((), ())


def test_an_unchanged_estate_moves_no_predicate() -> None:
    """The control: a measurement equal to the baseline reports nothing either way.

    Without it the tests above would pass on predicates that always report
    everything.

    Arrange: identical measured and banked pairs for both sections, and counts.
    Act:     run all six predicates.
    Assert:  each returns nothing.
    """
    # Arrange
    breaks = {GatewayKey("boe_b0793", "rich", "ERROR"): "a reason"}
    opposed = {DisagreementKey("boe_b1055", "rich", "PASS", "FAIL"): "a reason"}
    counts = {GatewayKey("boe_b0793", "rich", "ERROR"): 3}

    # Act
    moved = (
        _gateway_breaks_added(breaks, breaks),
        _gateway_breaks_removed(breaks, breaks),
        _disagreements_added(opposed, opposed),
        _disagreements_removed(opposed, opposed),
        _gateway_counts_risen(counts, counts),
        _gateway_counts_fallen(counts, counts),
    )

    # Assert
    assert moved == ((), (), (), (), (), ())


# ---------------------------------------------------------------------------
# Reading the register back loses no reason
# ---------------------------------------------------------------------------
# REGEN writes each pair once, but the re-bank procedure invites a hand edit of
# one entry's reason, and a hand edit can leave a pair in two entries. Read into
# a {pair: reason} map, the second reason would silently replace the first, and
# legs (h)-(k) would compare against a register that is not the one on disk.


def test_a_gateway_pair_in_two_entries_is_refused() -> None:
    """One (rule, portfolio, severity) under two reasons is an error, not a last-wins read.

    Arrange: two known_gateway_breaks entries for boe_b0356 that both name rich.
    Act:     read the register content.
    Assert:  the read fails, naming the pair.
    """
    # Arrange
    payload = {
        GATEWAY_SECTION: [
            _gateway_entry("boe_b0356", "WARNING", "one cause", ["irb-shapes", "rich"]),
            _gateway_entry("boe_b0356", "WARNING", "another cause", ["rich"]),
        ]
    }

    # Act / Assert
    with pytest.raises(ValueError, match=r"boe_b0356.*rich"):
        _baseline_from(payload)


def test_a_disagreement_pair_in_two_entries_is_refused() -> None:
    """The same guard on known_engine_disagreements, whose key carries both verdicts.

    Arrange: two entries for one (rule, portfolio, verdicts) with different reasons.
    Act:     read the register content.
    Assert:  the read fails, naming the pair.
    """
    # Arrange
    payload = {
        DISAGREEMENT_SECTION: [
            _disagreement_entry("boe_b1055", "one cause", ["crm-substitution"]),
            _disagreement_entry("boe_b1055", "another cause", ["crm-substitution", "rich"]),
        ]
    }

    # Act / Assert
    with pytest.raises(ValueError, match=r"boe_b1055.*crm-substitution"):
        _baseline_from(payload)


def test_one_rule_on_two_portfolios_in_two_entries_is_read_whole() -> None:
    """The control: one rule split across entries by portfolio is legal and fully read.

    Without it the two tests above would pass on a reader that refuses any rule
    appearing twice, which is how REGEN writes a rule with two causes.

    Arrange: boe_b0356 in two entries with disjoint portfolios.
    Act:     read the register content.
    Assert:  both pairs are present, each with its own reason.
    """
    # Arrange
    payload = {
        GATEWAY_SECTION: [
            _gateway_entry("boe_b0356", "WARNING", "one cause", ["irb-shapes"]),
            _gateway_entry("boe_b0356", "WARNING", "another cause", ["rich"]),
        ]
    }

    # Act
    gateway = _baseline_from(payload).gateway

    # Assert
    assert gateway == {
        GatewayKey("boe_b0356", "irb-shapes", "WARNING"): "one cause",
        GatewayKey("boe_b0356", "rich", "WARNING"): "another cause",
    }


def test_the_banked_count_is_read_back_per_pair() -> None:
    """Leg (l) compares what REGEN wrote: each portfolio's by_portfolio unsatisfied.

    Arrange: one entry on two portfolios with different counts.
    Act:     read the register content.
    Assert:  each pair carries its own count.
    """
    # Arrange
    entry = _gateway_entry("boe_b0356", "WARNING", "a cause", ["irb-shapes", "rich"])
    entry["by_portfolio"] = {"irb-shapes": {"unsatisfied": 4}, "rich": {"unsatisfied": 2}}

    # Act
    counts = _baseline_from({GATEWAY_SECTION: [entry]}).unsatisfied

    # Assert
    assert counts == {
        GatewayKey("boe_b0356", "irb-shapes", "WARNING"): 4,
        GatewayKey("boe_b0356", "rich", "WARNING"): 2,
    }


def test_every_committed_gateway_pair_carries_a_banked_count() -> None:
    """A pair with no banked count is a pair leg (l) cannot see.

    Arrange: the committed register.
    Act:     read its pairs and its counts as the acceptance legs do.
    Assert:  the two key sets are equal, and every count is a positive integer
             (a FAIL has at least one unsatisfied evaluation).
    """
    # Arrange
    baseline = _baseline_from(_register())

    # Act
    uncounted = sorted(key.describe() for key in set(baseline.gateway) - set(baseline.unsatisfied))
    stray = sorted(key.describe() for key in set(baseline.unsatisfied) - set(baseline.gateway))
    not_positive = sorted(
        key.describe()
        for key, count in baseline.unsatisfied.items()
        if not isinstance(count, int) or count < 1
    )

    # Assert
    assert (uncounted, stray, not_positive) == ([], [], []), (
        f"{REGISTER_PATH.name}: pairs with no banked count {uncounted}, counts for no pair "
        f"{stray}, non-positive counts {not_positive}.\n{REBANK}"
    )


def test_the_committed_register_holds_each_pair_once() -> None:
    """The committed file reads back with no pair under two reasons.

    Arrange: the committed register.
    Act:     read it as the acceptance legs do.
    Assert:  the read succeeds (a duplicate raises).
    """
    # Arrange
    register = _register()

    # Act
    baseline = _baseline_from(register)

    # Assert
    assert baseline.gateway, f"{REGISTER_PATH.name} reads back with no gateway pair"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

#: The day the synthetic deny-list entries take effect, and the run date after it.
_APPLIED = date(2026, 1, 1)
_RUN_DATE = date(2026, 11, 16)


def _gateway_entry(
    rule_id: str, severity: str, reason: str, portfolios: list[str]
) -> dict[str, Any]:
    """A known_gateway_breaks entry as REGEN writes it, reduced to what is read back."""
    return {"rule_id": rule_id, "severity": severity, "reason": reason, "portfolios": portfolios}


def _disagreement_entry(rule_id: str, reason: str, portfolios: list[str]) -> dict[str, Any]:
    """A template-PASS / gateway-FAIL known_engine_disagreements entry, as read back."""
    return {
        "rule_id": rule_id,
        "template_level": "PASS",
        "gateway": "FAIL",
        "reason": reason,
        "portfolios": portfolios,
    }


def _error_break(rule_id: str) -> RuleResult:
    """An ERROR-severity rule the formula breaks twice and holds once."""
    return RuleResult(
        rule_id=rule_id, severity="ERROR", status=STATUS_FAIL, satisfied=1, unsatisfied=2
    )


def _as_the_gateway_runs(results: list[RuleResult], deny_type: str) -> tuple[RuleResult, ...]:
    """``results`` after a deny list that applies ``deny_type`` to each of their rules."""
    deny_list = DenyList(
        release="4.1.1",
        entries=tuple(
            DenyEntry(result.rule_id, FILING_MODULE, deny_type, _APPLIED) for result in results
        ),
    )
    return apply_deny_list(results, deny_list, FILING_MODULE, _RUN_DATE)
