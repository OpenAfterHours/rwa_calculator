"""The rule model: which rules a module enforces, and what an unreadable rule looks like."""

from __future__ import annotations

import pytest

from boe_builders import T01, ref, rule
from rwa_filer.boe.catalogue import SEVERITY_ERROR, rulebook_from
from rwa_filer.boe.grammar import GrammarError, Reference, ScopeGroup

EXPRESSION = f"{ref(T01, '0010', '0010')} >= 0"


@pytest.mark.parametrize(
    ("overrides", "enforced"),
    [
        ({}, True),
        ({"in_xbrl": False}, False),
        ({"deactivated": True}, False),
        ({"severities": {"OTHER": "ERROR"}}, False),
        ({"always_execute": True}, True),
    ],
    ids=["plain", "not-in-xbrl", "deactivated", "other-module", "always-execute"],
)
def test_a_rule_is_enforced_when_the_gateway_would_run_it(
    overrides: dict[str, object], enforced: bool
) -> None:
    assert rule("r", EXPRESSION, tables=(T01,), **overrides).is_enforced("TST001") is enforced


def test_severity_is_per_module_and_an_error_unless_stated() -> None:
    mixed = rule("r", EXPRESSION, tables=(T01,), severities={"A": "WARNING", "B": "ERROR"})

    assert (mixed.severity("A"), mixed.severity("B"), mixed.severity("C")) == (
        "WARNING",
        "ERROR",
        SEVERITY_ERROR,
    )


def test_the_parts_of_a_rule_are_parsed_on_demand() -> None:
    # Arrange
    scoped = rule(
        "r", EXPRESSION, tables=(T01,), scope="scope({t: T01.00.01.01, c:0010;0020, f: t, fv: t})"
    )

    # Act / Assert
    assert scoped.parse_error is None
    assert isinstance(scoped.tree.left, Reference)  # type: ignore[union-attr]
    assert scoped.scope_groups == (ScopeGroup(T01, columns=("0010", "0020")),)
    assert scoped.joins == () and scoped.where_tree is None


def test_an_unreadable_rule_says_why_and_stays_in_the_rule_book() -> None:
    # Arrange
    broken = rule("r", "{t: T01.00.01.01, r: 0010", tables=(T01,))
    cut = rule("r", EXPRESSION, tables=(T01,), truncated=True)

    # Act / Assert
    assert "unterminated reference" in (broken.parse_error or "")
    assert "cell limit" in (cut.parse_error or "")
    with pytest.raises(GrammarError):
        _ = broken.tree


def test_a_rule_book_is_built_from_the_importers_payload() -> None:
    # Arrange
    payload = {
        "format": 1,
        "framework_version": "test_fw",
        "modules": ["TST001"],
        "source": {"taxonomy": "9.9.9", "workbook": "w.xlsx"},
        "rules": [
            {
                "id": "b1",
                "expression": EXPRESSION,
                "severity": {"TST001": "WARNING"},
                "tables": [T01],
                "in_xbrl": True,
                "deactivated": False,
                "always_execute": True,
                "label": "Amounts are not negative",
            },
            {"id": "b2", "expression": EXPRESSION, "severity": {}, "tables": [], "in_xbrl": False},
        ],
    }

    # Act
    rulebook = rulebook_from(payload)

    # Assert
    assert (rulebook.framework_version, rulebook.taxonomy) == ("test_fw", "9.9.9")
    assert [r.rule_id for r in rulebook.enforced("TST001")] == ["b1"]
    first = rulebook.rule("b1")
    assert first is not None and first.always_execute and first.label == "Amounts are not negative"
    assert rulebook.rule("missing") is None


def test_a_rule_book_in_another_format_is_refused() -> None:
    with pytest.raises(ValueError, match="format 2"):
        rulebook_from({"format": 2, "framework_version": "x", "source": {}, "rules": []})
