"""
Builders for Bank of England rules in the published syntax, over the synthetic pack.

A rule is written here as its workbook cell is written, so a test reads like
the rule it pins. ``ref`` composes one reference; ``rule`` and ``book`` wrap
expressions as a ``Rule`` / ``RuleBook`` for the synthetic module ``TST001``.
"""

from __future__ import annotations

from typing import Any

from pack_builders import SAMPLE_MODULE
from rwa_filer.boe.catalogue import Rule, RuleBook

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
