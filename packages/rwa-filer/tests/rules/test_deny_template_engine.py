"""
The template-level engine honours the Bank's deny list — the same packaged data the gateway engine reads.

Pipeline position:
    rules/data/basel31-boe-v<release>-credit-risk.json + boe/data/deny/<release>.json
        ->  rules.catalogue.load_rules  ->  RuleSet.enforced  ->  validate.checker

What is pinned: a rule the Bank deactivated at its gateway, on or before the
date the extract is loaded for, is not enforced (so it is not evaluated and not
reported); a downgraded one is a Warning; the extract's own liveness — what the
taxonomy publishes — is unchanged and is still what DPM variant columns are
derived from; and an EBA (CRR) extract has no deny list.

References:
- Bank of England, "Banking validations deny list" (November 2026)
- rwa_filer.boe.deny — the packaged list
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from filer_builders import build_frame, build_index
from rwa_filer.boe.deny import (
    DENY_DEACTIVATED,
    DENY_DOWNGRADED,
    DenyEntry,
    DenyList,
    load_deny_list,
)
from rwa_filer.rules import catalogue
from rwa_filer.rules.catalogue import (
    FRAMEWORK_BASEL_3_1,
    FRAMEWORK_CRR,
    SEVERITY_WARNING,
    RuleSet,
    is_currently_enforced,
    load_rules,
)
from rwa_filer.validate.checker import (
    FINDING_RULE_ERROR,
    FINDING_RULE_WARNING,
    evaluate_index,
    findings_for,
)
from rwa_filer.validate.evaluate import STATUS_FAIL

if TYPE_CHECKING:
    from collections.abc import Iterator

BEFORE = date(2026, 10, 18)
AFTER = date(2026, 11, 16)
DEACTIVATED_FOR_PRA001 = ("boe_b0710", "boe_b0710_1", "boe_b0710_2", "boe_b0710_3", "boe_b0746")


def _only(ruleset: RuleSet, rule_id: str) -> RuleSet:
    """``ruleset`` cut down to one rule, so the assertion is about that rule alone."""
    return RuleSet(
        framework=ruleset.framework,
        publisher=ruleset.publisher,
        source=ruleset.source,
        rules=tuple(rule for rule in ruleset.rules if rule.rule_id == rule_id),
    )


def _breaking_b0710():  # noqa: ANN202 - a TemplateIndex
    """OF 07.00, corporates: fully adjusted exposure 100, its CCF breakdown (0160-0190) all zero."""
    return build_index(
        FRAMEWORK_BASEL_3_1,
        c07_00={
            "corporate": build_frame(
                {
                    "0010": {
                        "0150": 100.0,
                        "0160": 0.0,
                        "0170": 0.0,
                        "0171": 0.0,
                        "0180": 0.0,
                        "0190": 0.0,
                    }
                }
            )
        },
    )


def test_boe_b0710_breaks_on_the_template_level_engine_before_the_bank_deactivated_it() -> None:
    """The leg that stays red: the frame really does break the rule's published form."""
    ruleset = _only(load_rules(FRAMEWORK_BASEL_3_1, on=BEFORE), "boe_b0710")

    report = evaluate_index(_breaking_b0710(), ruleset)

    assert [(item.rule_id, item.status) for item in report.outcomes] == [("boe_b0710", STATUS_FAIL)]
    assert [item.code for item in findings_for(report)] == [FINDING_RULE_ERROR]


def test_boe_b0710_is_not_enforced_once_the_bank_has_deactivated_it() -> None:
    ruleset = _only(load_rules(FRAMEWORK_BASEL_3_1, on=AFTER), "boe_b0710")

    report = evaluate_index(_breaking_b0710(), ruleset)

    assert report.outcomes == ()
    assert "boe_b0710" not in {item.subject for item in findings_for(report)}


def test_every_deactivated_pra001_rule_leaves_the_enforced_set() -> None:
    enforced = {rule.rule_id for rule in load_rules(FRAMEWORK_BASEL_3_1, on=AFTER).enforced}
    before = {rule.rule_id for rule in load_rules(FRAMEWORK_BASEL_3_1, on=BEFORE).enforced}

    assert set(DEACTIVATED_FOR_PRA001) <= before
    assert enforced.isdisjoint(DEACTIVATED_FOR_PRA001)


def test_a_deactivated_rule_carries_the_entry_that_switched_it_off() -> None:
    ruleset = load_rules(FRAMEWORK_BASEL_3_1, on=AFTER)

    rule = next(item for item in ruleset.rules if item.rule_id == "boe_b0710")

    assert rule.deny == load_deny_list("4.1.1").entry("PRA001", "boe_b0710")
    assert rule.deny is not None and rule.deny.deny_type == DENY_DEACTIVATED
    assert not is_currently_enforced(rule)
    assert rule.status == ("live",), "the extract's own status is the taxonomy's, unchanged"


def test_an_entry_for_another_module_does_not_reach_pra001s_rule() -> None:
    """boe_b1022 is deactivated for PRA115; PRA001's boe_b1022 is a different, enforced rule."""
    ruleset = load_rules(FRAMEWORK_BASEL_3_1, on=AFTER)

    rule = next(item for item in ruleset.rules if item.rule_id == "boe_b1022")

    assert rule.deny is None
    assert is_currently_enforced(rule)


def test_the_published_liveness_is_kept_beside_the_gateways() -> None:
    """DPM variant columns are derived from the taxonomy's scope, which the list never alters."""
    ruleset = load_rules(FRAMEWORK_BASEL_3_1, on=AFTER)

    published = {rule.rule_id for rule in ruleset.published_in_force}
    enforced = {rule.rule_id for rule in ruleset.enforced}

    assert published - enforced == set(DEACTIVATED_FOR_PRA001)


def test_the_eba_extract_has_no_deny_list() -> None:
    ruleset = load_rules(FRAMEWORK_CRR, on=AFTER)

    assert all(rule.deny is None for rule in ruleset.rules)
    assert ruleset.enforced == ruleset.published_in_force


@pytest.fixture
def downgraded_b0710(monkeypatch: pytest.MonkeyPatch) -> Iterator[date]:
    """A deny list that DOWNGRADES boe_b0710 for PRA001 (no shipped entry downgrades a B31 extract rule).

    The extract is cached per (framework, day), so the cache is cleared on the way
    in and out: no other test sees the synthetic list.
    """
    applied = date(2026, 10, 19)
    synthetic = DenyList(
        release="4.1.1",
        entries=(
            DenyEntry(
                rule_id="boe_b0710",
                module="PRA001",
                deny_type=DENY_DOWNGRADED,
                date_applied=applied,
                known_issue=None,
            ),
        ),
    )
    monkeypatch.setattr(catalogue, "release_deny_list", lambda _release: synthetic)
    catalogue._load_rules.cache_clear()
    yield applied
    catalogue._load_rules.cache_clear()


def test_a_downgraded_rule_is_still_enforced_as_a_warning(downgraded_b0710: date) -> None:
    """DENY-01 follow-up: 'submissions that fail this rule will be accepted' - a warning, not an error."""
    # Arrange
    ruleset = _only(load_rules(FRAMEWORK_BASEL_3_1, on=AFTER), "boe_b0710")
    rule = ruleset.rules[0]

    # Act
    report = evaluate_index(_breaking_b0710(), ruleset)
    findings = [item for item in findings_for(report) if item.subject == "boe_b0710"]

    # Assert
    assert rule.deny is not None and rule.deny.deny_type == DENY_DOWNGRADED
    assert (rule.severity, is_currently_enforced(rule)) == (SEVERITY_WARNING, True)
    assert [(item.rule_id, item.status) for item in report.outcomes] == [("boe_b0710", STATUS_FAIL)]
    assert [item.code for item in findings] == [FINDING_RULE_WARNING]


def test_a_downgrade_applies_only_from_its_date(downgraded_b0710: date) -> None:
    # Arrange
    before = _only(load_rules(FRAMEWORK_BASEL_3_1, on=date(2026, 10, 18)), "boe_b0710")

    # Act
    report = evaluate_index(_breaking_b0710(), before)

    # Assert
    assert before.rules[0].deny is None
    assert [item.code for item in findings_for(report) if item.subject == "boe_b0710"] == [
        FINDING_RULE_ERROR
    ]
