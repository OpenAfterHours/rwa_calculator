"""
Builders for Bank of England rules in the published syntax, over the synthetic pack.

A rule is written here as its workbook cell is written, so a test reads like
the rule it pins. ``ref`` composes one reference; ``rule`` and ``book`` wrap
expressions as a ``Rule`` / ``RuleBook`` for the synthetic module ``TST001``;
``issue_register`` names one of them in a one-issue publisher-issue register.
"""

from __future__ import annotations

from typing import Any

from pack_builders import SAMPLE_MODULE
from rwa_filer.boe.catalogue import Rule, RuleBook
from rwa_filer.boe.issues import EFFECT_FAILS_CORRECT_RETURNS, IssueRegister, issues_from

T01 = "T01.00.01.01"
T02 = "T02.00.01.01"
T03 = "T03.00.01.01"
T04 = "T04.00.01.01"
T05A = "T05.00.01.01"
T06 = "T06.00.01.01"
T07 = "T07.00.01.01"

_TAIL = "f: test, fv: test"


def ref(  # noqa: PLR0913 - one keyword per reference key
    table: str,
    r: str | None = None,
    c: str | None = None,
    z: str | None = None,
    *,
    dv: str | None = "0",
    seq: bool = False,
    flt: str | None = None,
    var: str | None = None,
) -> str:
    """One reference, e.g. ``{t: T01.., r: 0010, c: 0010, dv: 0, seq: False, f: .., fv: ..}``."""
    parts = [f"t: {table}"]
    for key, value in (("r", r), ("c", c), ("z", z), ("dv", dv), ("filter", flt)):
        if value is not None:
            parts.append(f"{key}: {value}")
    parts.append(f"seq: {seq}")
    if var is not None:
        parts.append(f"id: {var}")
    parts.append(_TAIL)
    return "{" + ", ".join(parts) + "}"


def scope(table: str, **axes: str) -> str:
    """A one-table scope cell, e.g. ``scope({t: T02.., z:0001;0002, ..})``."""
    listed = ", ".join(f"{axis}:{codes}" for axis, codes in axes.items())
    return f"scope({{t: {table}, {listed}, {_TAIL}}})"


def rule(rule_id: str, expression: str, *, tables: tuple[str, ...], **overrides: Any) -> Rule:
    """A rule enforced as an Error for the synthetic module unless overridden."""
    fields: dict[str, Any] = {
        "rule_id": rule_id,
        "framework_version": "test",
        "expression": expression,
        "severities": {SAMPLE_MODULE: "ERROR"},
        "tables": tables,
    }
    fields.update(overrides)
    return Rule(**fields)


def book(*rules: Rule) -> RuleBook:
    return RuleBook(
        framework_version="test",
        taxonomy="1.0.0",
        modules=(SAMPLE_MODULE,),
        source={"taxonomy": "1.0.0"},
        rules=tuple(rules),
    )


def issue_register(
    target: Rule,
    *,
    footprint: list[dict[str, Any]] | None = None,
    effect: str = EFFECT_FAILS_CORRECT_RETURNS,
    sha: str | None = None,
    status: str = "draft",
    attribution: str = "certain",
) -> IssueRegister:
    """One issue, PI-01, naming ``target`` as its subject for the synthetic module."""
    return issues_from(
        {
            "format": 1,
            "release": "1.0.0",
            "publisher": "Bank of England",
            "documents": {},
            "checked_against": [],
            "issues": [
                {
                    "id": "PI-01",
                    "title": "The total is not the sum of its parts",
                    "status": status,
                    "raised": None,
                    "publisher_reference": None,
                    "publisher_log": [],
                    "fixed_in": None,
                    "effect": effect,
                    "causes": ["contradicts_instructions"],
                    "rules": [
                        {
                            "module": SAMPLE_MODULE,
                            "rule_id": target.rule_id,
                            "role": "subject",
                            "severity": "ERROR",
                            "rule_sha256": sha or target.fingerprint(SAMPLE_MODULE),
                            "footprint": footprint,
                            "attribution": attribution,
                        }
                    ],
                    "requirement": "",
                    "authority": [],
                    "why_correct_return_fails": "",
                    "example": None,
                    "alternatives_considered": "",
                    "proposed_fix": "",
                    "eba_precedent": "",
                    "reach": "",
                    "meanwhile": "",
                }
            ],
        },
        file="1.0.0.json",
    )
