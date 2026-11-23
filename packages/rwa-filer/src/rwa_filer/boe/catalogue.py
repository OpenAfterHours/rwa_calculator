"""
The Bank of England rule books — every published validation rule, per reporting module.

Pipeline position:
    data/<framework version>-<taxonomy>.json  ->  load_rulebook
        (rwa_filer.release picks the file of the run's release)
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
- Work out what a rule's cells say ONCE. Each cell is parsed the first time
  any of its readers asks, and a fingerprint is digested the first time it is
  asked for; the answer is kept on the rule, and the first one kept is never
  replaced — the engine recognises a rule's references by the tree's own
  nodes, from however many threads.

A rule's identity is its framework version AND its code: the same code names
different rules in different workbooks.

References:
- Bank of England Banking Taxonomy v4.1.1 — validation rule workbooks
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from functools import cache, cached_property
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

from rwa_filer.boe.formulas import KEY_CLOSED, KEY_DIMENSIONS, KEY_OPEN, KEY_SPANS
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
    """No rule book is packaged under the requested file name."""


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
        closed: Dimensions the rule's XBRL formula closes for every variable —
            fixes to the default member, or requires absent. A cell whose data
            point carries one cannot bind in the formula, whatever the text
            above says. Empty for a rule book built without a taxonomy package.
        closed_by_variable: The same, for one variable (``v0``) only.
        spans_by_variable: For each variable the formula binds AS A SEQUENCE
            (a sum or a count), the dimensions its own filters cover: it takes
            every row or member of those at once, and is read at the same row
            or member as the rest of the rule on any open dimension it does not
            cover — the formula's implicit filtering. The text cannot say
            which: ``isum({.., c: 0040; 0050; 0060, seq: True})`` reads the same
            either way. A variable absent here is read from the text alone, as
            is every variable of a rule book built without a taxonomy package.

    What is worked out from the cells — the parsed parts, why the rule cannot
    be read, its fingerprints — is kept on the object after first use. None of
    it is a field: it is not compared, and ``dataclasses.replace`` gives a rule
    with nothing kept, which reads its own cells.
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
    closed: frozenset[str] = frozenset()
    closed_by_variable: Mapping[str, frozenset[str]] = field(default_factory=dict)
    spans_by_variable: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def is_enforced(self, module: str) -> bool:
        """Whether the gateway runs this rule on a return of ``module``."""
        return module in self.severities and self.in_xbrl and not self.deactivated

    def severity(self, module: str) -> str:
        """How a break is treated for ``module``; an Error unless stated otherwise."""
        return self.severities.get(module, SEVERITY_ERROR)

    def fingerprint(self, module: str) -> str:
        """SHA-256 of everything that decides how this rule runs on ``module``.

        The code alone does not identify a rule across releases: the same code
        can carry a changed expression, scope or severity. Two runs whose rules
        share a fingerprint ran the same check.

        Digested once for each severity and kept: of all that is hashed, only
        the severity depends on the module, and every report asks for every
        rule's fingerprint again.
        """
        severity = self.severity(module)
        digest = self._fingerprints.get(severity)
        if digest is None:
            digest = self._fingerprints.setdefault(severity, _fingerprint(self, severity))
        return digest

    @cached_property
    def _fingerprints(self) -> dict[str, str]:
        """The digests ``fingerprint`` has taken so far, by severity."""
        return _keep_first(self, "_fingerprints", {})

    @cached_property
    def parse_error(self) -> str | None:
        """Why the rule cannot be read, or ``None`` when every part parses."""
        if self.truncated:
            return "the workbook cell is cut at the spreadsheet cell limit"
        try:
            # Read through the four parts below, which keep what they parse: a
            # rule found readable here is not parsed again when it is run. In
            # this order, so the first cell that fails is the one reported.
            _ = self.tree, self.scope_groups, self.joins, self.where_tree
        except GrammarError as error:
            return str(error)
        return None

    @cached_property
    def tree(self) -> Node:
        """The parsed expression. Raises ``GrammarError`` if it does not parse."""
        return _keep_first(self, "tree", parse_expression(self.expression))

    @cached_property
    def scope_groups(self) -> tuple[ScopeGroup, ...]:
        return _keep_first(self, "scope_groups", parse_scope(self.scope or ""))

    @cached_property
    def joins(self) -> tuple[JoinKey | JoinEquality, ...]:
        return _keep_first(self, "joins", parse_join(self.join or ""))

    @cached_property
    def where_tree(self) -> Node | None:
        return _keep_first(self, "where_tree", parse_expression(self.where) if self.where else None)


@dataclass(frozen=True)
class RuleBook:
    """Every rule of one framework version at one taxonomy release."""

    framework_version: str
    taxonomy: str
    modules: tuple[str, ...]
    source: Mapping[str, Any]
    rules: tuple[Rule, ...]
    #: The packaged file it was loaded from; ``None`` for one built in memory.
    file: str | None = None
    #: SHA-256 of the rule book's content, in canonical JSON — the same for a
    #: packaged file and the dict it was loaded from. Empty when not known.
    content_sha256: str = ""

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
    return rulebook_from(json.loads(resource.read_text(encoding="utf-8")), file=file_name)


def rulebook_from(payload: Mapping[str, Any], *, file: str | None = None) -> RuleBook:
    """Build a ``RuleBook`` from an importer's rule-book dict.

    Args:
        payload: The rule book, as ``boe.importer`` writes it.
        file: The packaged file it came from, recorded for a report to name.
    """
    if payload.get("format") != RULEBOOK_FORMAT:
        raise ValueError(
            f"Rule book format {payload.get('format')!r} is not supported "
            f"(expected {RULEBOOK_FORMAT})"
        )
    framework_version = str(payload["framework_version"])
    dimensions = frozenset(payload.get(KEY_DIMENSIONS, ()))
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
            # The file lists what a formula leaves OPEN; the rest it closes.
            closed=dimensions - frozenset(entry[KEY_OPEN]) if KEY_OPEN in entry else frozenset(),
            closed_by_variable={
                variable: frozenset(closed)
                for variable, closed in entry.get(KEY_CLOSED, {}).items()
            },
            spans_by_variable={
                variable: frozenset(spans) for variable, spans in entry.get(KEY_SPANS, {}).items()
            },
        )
        for entry in payload["rules"]
    )
    return RuleBook(
        framework_version=framework_version,
        taxonomy=str(payload["source"]["taxonomy"]),
        modules=tuple(payload.get("modules", ())),
        source=dict(payload["source"]),
        rules=rules,
        file=file,
        content_sha256=canonical_sha256(payload),
    )


def canonical_sha256(content: object) -> str:
    """SHA-256 of ``content`` as canonical JSON: sorted keys, no whitespace, UTF-8.

    The one digest every identity in a validation report is taken with, so a
    value hashed in two places gives one answer.
    """
    text = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# =============================================================================
# Private helpers
# =============================================================================


def _keep_first[T](rule: Rule, name: str, value: T) -> T:
    """Keep ``value`` as ``rule``'s ``name`` unless one is kept already; return the one kept.

    ``functools.cached_property`` alone is not enough. Two threads that read a
    part nothing has read yet both work it out, and ``cached_property`` stores
    whatever each hands it: the second tree replaces the first after the first
    reader has gone on to use it. The engine keys a rule's selectors by
    ``id()`` of the nodes of the tree it was handed, so a replaced tree is a
    ``KeyError`` — and the dashboard runs each validation in its own thread.
    ``dict.setdefault`` is one step: whichever value is stored first is the
    one every reader is given, and no later store puts another in its place.
    """
    return rule.__dict__.setdefault(name, value)


def _fingerprint(rule: Rule, severity: str) -> str:
    """The digest of ``rule`` as it runs where a break is treated as ``severity``."""
    content: dict[str, Any] = {
        "rule_id": rule.rule_id,
        "framework_version": rule.framework_version,
        "expression": rule.expression,
        "scope": rule.scope,
        "where": rule.where,
        "join": rule.join,
        "tables": list(rule.tables),
        "severity": severity,
        "always_execute": rule.always_execute,
        "closed": sorted(rule.closed),
        "closed_by_variable": {
            variable: sorted(closed) for variable, closed in sorted(rule.closed_by_variable.items())
        },
    }
    # Stated only where a formula binds a sequence, so a rule without one
    # keeps the fingerprint it has always had.
    if rule.spans_by_variable:
        content["spans_by_variable"] = {
            variable: sorted(spans) for variable, spans in sorted(rule.spans_by_variable.items())
        }
    return canonical_sha256(content)
