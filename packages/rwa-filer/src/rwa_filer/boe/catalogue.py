"""
The Bank of England rule books — every published validation rule, per reporting module.

Pipeline position:
    data/<framework version>-<taxonomy>.json  ->  load_rulebook / rulebook_for_module
        -> RuleBook(rules)  ->  boe.engine

Key responsibilities:
- Load the packaged rule books (built by ``boe.importer`` from the Bank's rule
  workbooks) and present each rule with its parts parsed: the expression tree,
  the scope, the join.
- Say which rules a module ENFORCES. A rule is enforced for a module when the
  Bank's gateway would run it: it names the module in its severity cell, it is
  serialised to the taxonomy ("Include in XBRL"), and it is not deactivated.
- Keep a rule that cannot be parsed IN the rule book, marked as such. A rule
  this package cannot read is a rule it cannot check, and that must be visible
  — it is counted, not dropped.

A rule's identity is its framework version AND its code: the same code names
different rules in different workbooks.

References:
- Bank of England Banking Taxonomy v4.1.1 — validation rule workbooks
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import cache, cached_property
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

from rwa_filer.boe.grammar import (
    GrammarError,
    JoinEquality,
    JoinKey,
    Node,
    ScopeGroup,
    parse_expression,
    parse_join,
    parse_scope,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

RULEBOOKS_PACKAGE: Final = "rwa_filer.boe"
RULEBOOKS_DIRECTORY: Final = "data"
RULEBOOK_FORMAT: Final = 1

SEVERITY_ERROR: Final = "ERROR"
SEVERITY_WARNING: Final = "WARNING"


class RuleBookNotFoundError(LookupError):
    """No packaged rule book covers the requested module."""


# =============================================================================
# The rule book
# =============================================================================


@dataclass(frozen=True)
class Rule:
    """One published validation rule, as the workbook states it.

    Attributes:
        rule_id: The rule code, e.g. ``boe_b0021``. Unique within a rule book.
        framework_version: The workbook's framework version code.
        expression: The RAW expression cell.
        severities: ``{module: "ERROR" | "WARNING"}`` — the modules the rule
            belongs to and how a break is treated in each.
        tables: The tables the rule reads. The rule is run only when every one
            of them is reported.
        scope / where / join: The corresponding cells, where the rule has them.
        in_xbrl: The rule is serialised to the taxonomy, so the gateway runs it.
        deactivated: The publisher has switched the rule off.
        always_execute: The rule is run once even where none of its cells is
            reported — what lets "this cell must be reported" fail.
        label: The publisher's short description.
        truncated: The workbook cell was cut at the spreadsheet cell limit, so
            the expression is incomplete.
    """

    rule_id: str
    framework_version: str
    expression: str
    severities: Mapping[str, str]
    tables: tuple[str, ...]
    scope: str | None = None
    where: str | None = None
    join: str | None = None
    in_xbrl: bool = True
    deactivated: bool = False
    always_execute: bool = False
    label: str | None = None
    truncated: bool = False

    def is_enforced(self, module: str) -> bool:
        """Whether the gateway runs this rule on a return of ``module``."""
        return module in self.severities and self.in_xbrl and not self.deactivated

    def severity(self, module: str) -> str:
        """How a break is treated for ``module``; an Error unless stated otherwise."""
        return self.severities.get(module, SEVERITY_ERROR)

    @cached_property
    def parse_error(self) -> str | None:
        """Why the rule cannot be read, or ``None`` when every part parses."""
        if self.truncated:
            return "the workbook cell is cut at the spreadsheet cell limit"
        try:
            parse_expression(self.expression)
            parse_scope(self.scope or "")
            parse_join(self.join or "")
            if self.where:
                parse_expression(self.where)
        except GrammarError as error:
            return str(error)
        return None

    @cached_property
    def tree(self) -> Node:
        """The parsed expression. Raises ``GrammarError`` if it does not parse."""
        return parse_expression(self.expression)

    @cached_property
    def scope_groups(self) -> tuple[ScopeGroup, ...]:
        return parse_scope(self.scope or "")

    @cached_property
    def joins(self) -> tuple[JoinKey | JoinEquality, ...]:
        return parse_join(self.join or "")

    @cached_property
    def where_tree(self) -> Node | None:
        return parse_expression(self.where) if self.where else None


@dataclass(frozen=True)
class RuleBook:
    """Every rule of one framework version at one taxonomy release."""

    framework_version: str
    taxonomy: str
    modules: tuple[str, ...]
    source: Mapping[str, Any]
    rules: tuple[Rule, ...]

    def enforced(self, module: str) -> tuple[Rule, ...]:
        """The rules the gateway runs on a return of ``module``."""
        return tuple(rule for rule in self.rules if rule.is_enforced(module))

    def rule(self, rule_id: str) -> Rule | None:
        """The rule with this code, or ``None``."""
        return next((rule for rule in self.rules if rule.rule_id == rule_id), None)


# =============================================================================
# Public API
# =============================================================================


def available_rulebooks() -> tuple[str, ...]:
    """The packaged rule-book file names, sorted."""
    root = resources.files(RULEBOOKS_PACKAGE).joinpath(RULEBOOKS_DIRECTORY)
    if not root.is_dir():
        return ()
    return tuple(sorted(entry.name for entry in root.iterdir() if entry.name.endswith(".json")))


@cache
def load_rulebook(file_name: str) -> RuleBook:
    """Load one packaged rule book by file name. Cached: rule books are immutable.

    Raises:
        RuleBookNotFoundError: no such packaged file.
        ValueError: the file is in a format this version cannot read.
    """
    resource = resources.files(RULEBOOKS_PACKAGE).joinpath(RULEBOOKS_DIRECTORY, file_name)
    if not resource.is_file():
        raise RuleBookNotFoundError(f"No packaged rule book named {file_name!r}")
    return rulebook_from(json.loads(resource.read_text(encoding="utf-8")))


def rulebook_from(payload: Mapping[str, Any]) -> RuleBook:
    """Build a ``RuleBook`` from an importer's rule-book dict."""
    if payload.get("format") != RULEBOOK_FORMAT:
        raise ValueError(
            f"Rule book format {payload.get('format')!r} is not supported "
            f"(expected {RULEBOOK_FORMAT})"
        )
    framework_version = str(payload["framework_version"])
    rules = tuple(
        Rule(
            rule_id=entry["id"],
            framework_version=framework_version,
            expression=entry["expression"],
            severities=dict(entry.get("severity", {})),
            tables=tuple(entry.get("tables", ())),
            scope=entry.get("scope"),
            where=entry.get("where"),
            join=entry.get("join"),
            in_xbrl=bool(entry.get("in_xbrl", True)),
            deactivated=bool(entry.get("deactivated", False)),
            always_execute=bool(entry.get("always_execute", False)),
            label=entry.get("label"),
            truncated=bool(entry.get("truncated", False)),
        )
        for entry in payload["rules"]
    )
    return RuleBook(
        framework_version=framework_version,
        taxonomy=str(payload["source"]["taxonomy"]),
        modules=tuple(payload.get("modules", ())),
        source=dict(payload["source"]),
        rules=rules,
    )


def rulebook_for_module(module: str) -> RuleBook:
    """The packaged rule book that covers ``module`` (matched case-insensitively).

    Raises:
        RuleBookNotFoundError: no packaged rule book names the module.
    """
    wanted = module.upper()
    for file_name in available_rulebooks():
        rulebook = load_rulebook(file_name)
        if wanted in (name.upper() for name in rulebook.modules):
            return rulebook
    raise RuleBookNotFoundError(f"No packaged rule book covers module {module!r}")
