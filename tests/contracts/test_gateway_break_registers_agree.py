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

The four gateway predicates are driven here too, with synthetic pairs: watching
legs (h)-(k) fail through the acceptance file costs thirty pipeline runs, while
each predicate is a set difference these tests can feed directly, including the
``boe_b1055`` shape (a banked rule breaking on one more portfolio).

References:
- tests/acceptance/reporting/test_supervisory_validations.py — the register and its legs
- scripts/filing_mapping_report.py — the filing-mapping ratchet and ``file_on_gateway``
- docs/development/workspace.md — how the gates relate
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.acceptance.reporting.test_supervisory_validations import (
    BASELINE_PATH as REGISTER_PATH,
)
from tests.acceptance.reporting.test_supervisory_validations import (
    GATEWAY_FRAMEWORK,
    GATEWAY_REGIME,
    RUNS,
    DisagreementKey,
    GatewayKey,
    _disagreements_added,
    _disagreements_removed,
    _gateway_breaks_added,
    _gateway_breaks_removed,
)

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
# The predicates behind legs (h)-(k), driven synthetically
# ---------------------------------------------------------------------------


def test_a_gateway_break_on_one_more_portfolio_is_new() -> None:
    """The boe_b1055 shape: a banked rule that spreads is a new break, not a held one.

    Arrange: a baseline holding the rule on two portfolios; a measurement on three.
    Act:     ask for the added pairs.
    Assert:  exactly the third portfolio's pair.
    """
    # Arrange
    baseline = {
        GatewayKey("boe_b1055", "crm-substitution"): "a reason",
        GatewayKey("boe_b1055", "irb-shapes"): "a reason",
    }
    measured = {
        GatewayKey("boe_b1055", "crm-substitution"): None,
        GatewayKey("boe_b1055", "irb-shapes"): None,
        GatewayKey("boe_b1055", "rich"): None,
    }

    # Act
    added = _gateway_breaks_added(measured, baseline)

    # Assert
    assert added == (GatewayKey("boe_b1055", "rich"),)


def test_a_gateway_break_that_has_gone_is_reported_as_removed() -> None:
    """A fix on one portfolio removes that pair and leaves the rule's other pairs held.

    Arrange: a baseline on two portfolios; a measurement on one.
    Act:     ask for the removed and the added pairs.
    Assert:  the fixed pair is removed and nothing is added.
    """
    # Arrange
    baseline = {
        GatewayKey("boe_b0742", "facility-share-binding"): "a reason",
        GatewayKey("boe_b0742", "irb-shapes"): "a reason",
    }
    measured = {GatewayKey("boe_b0742", "irb-shapes"): None}

    # Act
    removed = _gateway_breaks_removed(measured, baseline)
    added = _gateway_breaks_added(measured, baseline)

    # Assert
    assert (removed, added) == ((GatewayKey("boe_b0742", "facility-share-binding"),), ())


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


def test_an_unchanged_estate_moves_no_predicate() -> None:
    """The control: a measurement equal to the baseline reports nothing either way.

    Without it the three tests above would pass on predicates that always report
    everything.

    Arrange: identical measured and banked pairs for both sections.
    Act:     run all four predicates.
    Assert:  each returns nothing.
    """
    # Arrange
    breaks = {GatewayKey("boe_b0793", "rich"): "a reason"}
    opposed = {DisagreementKey("boe_b1055", "rich", "PASS", "FAIL"): "a reason"}

    # Act
    moved = (
        _gateway_breaks_added(breaks, breaks),
        _gateway_breaks_removed(breaks, breaks),
        _disagreements_added(opposed, opposed),
        _disagreements_removed(opposed, opposed),
    )

    # Assert
    assert moved == ((), (), (), ())
