"""
The publisher-issue register's loader: what an issue says, which rules it names, and where.

Pipeline position:
    boe/data/issues/<release>.json  ->  issues_from / load_issues  ->  IssueRegister

What is pinned, on registers built in memory (the packaged one has its own
contract tests in ``test_publisher_issues.py``):
- a register is read, and refused when its format, an id, a status, an effect,
  a cause or a role is not one this version knows;
- a rule named twice by ONE issue is refused; two issues may name one rule,
  each with its own footprint;
- an issue names a rule only by its fingerprint: the same code with a changed
  expression is a different rule, and the issue does not apply to it;
- an unsatisfied evaluation is inside an issue's footprint when any cell it
  read matches any of its selectors; an issue with no footprint covers the
  whole rule;
- each status says what it means in one sentence, the one every surface uses.

References:
- rwa_filer.boe.issues — the register
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

import pytest

from boe_builders import T01, T02, ref, rule
from pack_builders import SAMPLE_MODULE
from rwa_filer.boe.engine import CellAddress
from rwa_filer.boe.issues import (
    EFFECT_FAILS_CORRECT_RETURNS,
    ROLE_SUBJECT,
    STATUS_ACKNOWLEDGED,
    STATUS_DRAFT,
    STATUS_FIXED,
    STATUS_RAISED,
    CellSelector,
    IssueRegister,
    issues_from,
)

FOOTING = rule(
    "tst_0001",
    f"{ref(T01, '0010', '0010')} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}",
    tables=(T01,),
)


def _payload(**issue: Any) -> dict[str, Any]:
    """A one-issue register naming FOOTING as its subject, with ``issue``'s fields over it."""
    base: dict[str, Any] = {
        "id": "PI-01",
        "title": "The total is not the sum of its parts",
        "status": STATUS_DRAFT,
        "raised": None,
        "publisher_reference": None,
        "publisher_log": [],
        "fixed_in": None,
        "effect": EFFECT_FAILS_CORRECT_RETURNS,
        "causes": ["contradicts_instructions"],
        "rules": [
            {
                "module": SAMPLE_MODULE,
                "rule_id": FOOTING.rule_id,
                "role": ROLE_SUBJECT,
                "severity": "ERROR",
                "rule_sha256": FOOTING.fingerprint(SAMPLE_MODULE),
                "footprint": None,
                "attribution": "certain",
            }
        ],
        "requirement": "Row 0010 equals rows 0020 and 0030 together.",
        "authority": [],
        "why_correct_return_fails": "Row 0010 also holds what neither part holds.",
        "example": None,
        "alternatives_considered": "",
        "proposed_fix": "",
        "eba_precedent": "",
        "reach": "",
        "meanwhile": "",
    }
    base.update(issue)
    return {
        "format": 1,
        "release": "1.0.0",
        "publisher": "Bank of England",
        "documents": {},
        "issues": [base],
    }


def _addresses(*cells: tuple[str, str | None, str, str]) -> tuple[CellAddress, ...]:
    return tuple(
        CellAddress(table=table, sheet=sheet, open_key=None, row=row, column=column)
        for table, sheet, row, column in cells
    )


# ---------------------------------------------------------------------------
# Reading a register
# ---------------------------------------------------------------------------


def test_a_register_is_read_with_its_issues_and_their_rules() -> None:
    # Act
    register = issues_from(_payload())

    # Assert
    issue = register.issue("PI-01")
    assert issue is not None
    assert (register.release, len(register.issues)) == ("1.0.0", 1)
    assert [item.rule_id for item in issue.subject_rules] == ["tst_0001"]
    assert register.for_rule(SAMPLE_MODULE, "tst_0001") == (issue,)
    assert register.for_rule(SAMPLE_MODULE, "tst_0002") == ()
    assert register.content_sha256


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "PI-1"),
        ("id", "PI-05-NEW"),
        ("status", "open"),
        ("effect", "rejects_everything"),
        ("causes", ["a_cause_nobody_defined"]),
    ],
)
def test_a_register_with_a_field_this_version_does_not_know_is_refused(
    field: str, value: object
) -> None:
    # Act / Assert
    with pytest.raises(ValueError, match=field.rstrip("s")):
        issues_from(_payload(**{field: value}))


def test_a_register_in_another_format_is_refused() -> None:
    # Arrange
    payload = _payload()
    payload["format"] = 2

    # Act / Assert
    with pytest.raises(ValueError, match="format"):
        issues_from(payload)


def test_an_issue_naming_one_rule_twice_is_refused() -> None:
    # Arrange
    payload = _payload()
    rules = payload["issues"][0]["rules"]
    rules.append(copy.deepcopy(rules[0]))

    # Act / Assert
    with pytest.raises(ValueError, match="tst_0001"):
        issues_from(payload)


def test_two_issues_may_name_one_rule_and_ids_must_be_unique() -> None:
    # Arrange
    payload = _payload()
    second = copy.deepcopy(payload["issues"][0])
    second["id"] = "PI-02"
    payload["issues"].append(second)

    # Act
    register = issues_from(payload)

    # Assert
    assert [issue.id for issue in register.for_rule(SAMPLE_MODULE, "tst_0001")] == [
        "PI-01",
        "PI-02",
    ]
    second["id"] = "PI-01"
    with pytest.raises(ValueError, match="PI-01"):
        issues_from(payload)


def test_the_empty_register_names_no_rule() -> None:
    # Act
    register = IssueRegister.empty("9.9.9")

    # Assert
    assert (register.release, register.issues) == ("9.9.9", ())
    assert register.for_rule(SAMPLE_MODULE, "tst_0001") == ()


# ---------------------------------------------------------------------------
# Which rule an issue is about: by fingerprint, not by code
# ---------------------------------------------------------------------------


def test_an_issue_applies_only_to_the_rule_it_pinned() -> None:
    # Arrange
    pinned = issues_from(_payload()).issues[0].subject_rules[0]
    changed = rule(
        FOOTING.rule_id,
        FOOTING.expression.replace("i+", "i-"),
        tables=FOOTING.tables,
    )

    # Act / Assert
    assert pinned.applies_to(FOOTING, SAMPLE_MODULE)
    assert not pinned.applies_to(changed, SAMPLE_MODULE)
    assert not pinned.applies_to(FOOTING, "PRA001")


# ---------------------------------------------------------------------------
# Where an issue applies
# ---------------------------------------------------------------------------


def test_a_selector_matches_its_table_and_the_codes_it_lists_or_does_not_exclude() -> None:
    # Arrange
    rows = CellSelector(table=T01, rows_except=("0010",))
    sheets = CellSelector(table=T02, sheets=("0002",), columns=("0010",))

    # Act / Assert
    assert rows.matches(_addresses((T01, None, "0020", "0010"))[0])
    assert not rows.matches(_addresses((T01, None, "0010", "0010"))[0])
    assert not rows.matches(_addresses((T02, None, "0020", "0010"))[0])
    assert sheets.matches(_addresses((T02, "0002", "0010", "0010"))[0])
    assert not sheets.matches(_addresses((T02, "0001", "0010", "0010"))[0])
    assert not sheets.matches(_addresses((T02, None, "0010", "0010"))[0])


def test_an_evaluation_is_inside_when_any_cell_it_read_is() -> None:
    # Arrange
    footprint = [{"table": T01, "rows_except": ["0010"]}]
    payload = _payload()
    payload["issues"][0]["rules"][0]["footprint"] = footprint
    pinned = issues_from(payload).issues[0].subject_rules[0]
    whole = issues_from(_payload()).issues[0].subject_rules[0]

    # Act / Assert
    assert pinned.inside(_addresses((T01, None, "0010", "0010"), (T01, None, "0020", "0010")))
    assert not pinned.inside(_addresses((T01, None, "0010", "0010")))
    assert whole.inside(_addresses((T01, None, "0010", "0010")))


def test_a_selector_with_no_table_is_refused() -> None:
    # Arrange
    payload = _payload()
    payload["issues"][0]["rules"][0]["footprint"] = [{"rows": ["0010"]}]

    # Act / Assert
    with pytest.raises(ValueError, match="table"):
        issues_from(payload)


# ---------------------------------------------------------------------------
# What each status says
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "said"),
    [
        ({}, "identified by rwa-filer, not yet raised with the Bank of England"),
        (
            {"status": STATUS_RAISED, "raised": {"date": "2026-12-01", "channel": "email"}},
            "raised with the Bank of England on 1 December 2026",
        ),
        (
            {
                "status": STATUS_ACKNOWLEDGED,
                "publisher_reference": "known issues log #22, 2 October 2026",
            },
            "acknowledged by the Bank of England (known issues log #22, 2 October 2026)",
        ),
        (
            {"status": STATUS_FIXED, "fixed_in": "4.2.0"},
            "fixed by the Bank of England in taxonomy 4.2.0; this release still contains "
            "the published rule",
        ),
    ],
)
def test_each_status_is_said_one_way(fields: dict[str, Any], said: str) -> None:
    # Act
    issue = issues_from(_payload(**fields)).issues[0]

    # Assert
    assert issue.status_text == said


def test_the_date_an_issue_was_raised_is_read_as_a_date() -> None:
    # Act
    issue = issues_from(
        _payload(status=STATUS_RAISED, raised={"date": "2026-12-01", "channel": "email"})
    ).issues[0]

    # Assert
    assert issue.raised is not None
    assert issue.raised.date == date(2026, 12, 1)
