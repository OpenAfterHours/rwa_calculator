"""
Supervisory validation-rule catalogue — load and normalise the packaged extracts.

Pipeline position:
    rules/*.json (package data)  ->  load_rules(framework)  ->  RuleSet
        ->  scope.expand_rule  ->  evaluate.evaluate_rule

Key responsibilities:
- Read the two committed rule extracts that ship INSIDE the wheel
  (``rwa_calc/reporting/validations/rules/*.json``) via ``importlib.resources``,
  so a production install carries them without needing the repo checkout.
- Normalise the two very different publisher schemas (EBA row/column/sheet scope
  columns; BoE ``scope(...)`` expressions) onto ONE ``ValidationRule`` shape, so
  scope expansion and evaluation are written once.
- Answer the liveness question correctly: a rule is *currently enforced* when it
  is ``live`` **or** carries a ``reactivated_on`` date, in both cases excluding
  ``deleted``. Filtering on ``status`` alone silently drops the 153 EBA rules
  that were deactivated and later switched back on.

Missing-value policy, and where each publisher states it: the EBA sheet has a
dedicated ``If value missing`` column. The BoE sheet has NO equivalent column —
its policy is carried per reference in the RAW expression as ``dv``, the XBRL
formula DEFAULT VALUE substituted when a fact is not reported. That is the
taxonomy's own statement of the policy, not an inference from the token's
presence: the vocabulary is visible in ``boe_b0076``, which carries
``dv: false()`` on a boolean cell alongside ``dv: 0`` on numeric ones. ``dv: 0``
is therefore the direct analogue of the EBA "treat as zero".

Why: the published validation rules are the supervisor's own arithmetic checks
on a submitted return. An Error-severity break rejects the whole submission, so
they are the most precise available oracle for the COREP estate this project
produces — but only if the catalogue is read with the publisher's own
liveness, missing-value and tolerance semantics intact.

References:
- docs/reference/validation-rules/index.md — provenance, schema, formula grammar
- EBA DPM 3.0(3.0.1) validation rules (CRR framework)
- BoE banking_reporting v4.0.0 validation rules (PS1/26 / Basel 3.1 framework)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

FRAMEWORK_CRR: Final = "CRR"
FRAMEWORK_BASEL_3_1: Final = "BASEL_3_1"

#: Packaged extract per framework. These live under this package (NOT under
#: docs/) because ``pyproject.toml`` ships only ``src/rwa_calc`` — an extract in
#: docs/ would never reach an installed wheel.
_RULES_PACKAGE: Final = "rwa_calc.reporting.validations"
#: The extracts sit in a plain DATA directory beside this module, anchored on the
#: parent package. It must stay free of an ``__init__.py``: this module is
#: ``validations.rules`` and the directory is ``validations/rules/``, and a real
#: module only outranks a same-named namespace-package directory — adding an
#: ``__init__.py`` there would turn the directory into a regular package and
#: shadow this module. Verified against a built wheel, not just the source tree.
_RULES_DIRECTORY: Final = "rules"
_EXTRACT_FILES: Final[dict[str, str]] = {
    FRAMEWORK_CRR: "crr-eba-v3.0-credit-risk.json",
    FRAMEWORK_BASEL_3_1: "basel31-boe-v4.0.0-credit-risk.json",
}

# Severity, as normalised by the extractor (both publishers use the same two).
SEVERITY_ERROR: Final = "ERROR"
SEVERITY_WARNING: Final = "WARNING"

# Missing-value policy (the EBA "If value missing" column). These are NOT
# interchangeable: "zero" invents a 0.0 for an unreported cell, "skip" refuses
# to evaluate the cell at all, and they give materially different answers on the
# same data.
MISSING_ZERO: Final = "zero"
MISSING_SKIP: Final = "skip"

# Comparison arithmetic (the EBA "Arithmetic approach" column; the BoE encodes
# the same distinction as the ``i=`` / ``i>=`` interval operators in the RAW
# expression, which the simplified form drops).
ARITHMETIC_INTERVAL: Final = "interval"
ARITHMETIC_POINT: Final = "point"
ARITHMETIC_NOT_APPLICABLE: Final = "not_applicable"

# Scope kinds, mirroring the extractor's `rows_scope` / `columns_scope` vocabulary.
SCOPE_NONE: Final = "none"
SCOPE_ALL: Final = "all"
SCOPE_LIST: Final = "list"

#: The BoE raw expression marks a rounding-tolerant comparison with an ``i``
#: prefix (``i=``, ``i>=``, ``i<=``, ``i>``). 654 of the 820 raw expressions use
#: one; the simplified expression drops them, losing the tolerance semantics, so
#: the arithmetic approach is recovered from the RAW form.
_BOE_INTERVAL_OPERATOR = re.compile(r"(?<![A-Za-z0-9_])i\s*(?:=|>=|<=|>|<)")

#: ``scope({t: T, r:0010;0020, c:0030, z:0001;0002, f: banking, ...}, {t: T2, ...})``
#: — one brace group per table, each with multi-valued r / c / z lists.
_BOE_SCOPE_GROUP = re.compile(r"\{([^{}]*)\}")
_BOE_SCOPE_KEY = re.compile(r"\b([a-z]+)\s*:\s*([^,}]*)")

#: EBA prerequisites read as ``"C 07.00.a and C 07.00.b"`` — a conjunction of
#: table codes that must be reported for the rule to run at all.
#: `(?<!\s)` gates the leading run so a match can only START where the run does.
#: Without it the search re-enters the same run of spaces at every offset, which
#: is quadratic in the run's length; the cost is across start positions, so a
#: possessive quantifier does NOT fix it. A leftmost match always begins at the
#: run's start, so the gate rejects only positions that could never have matched.
_PREREQUISITE_SPLIT = re.compile(r"(?<!\s)\s+and\s+", re.IGNORECASE)


# =============================================================================
# Normalised rule shape
# =============================================================================


@dataclass(frozen=True)
class RuleScope:
    """One axis (row / column / sheet) of a rule's iteration domain.

    ``kind`` is ``"none"`` (the axis is not scoped — the formula addresses it, or
    it must be expanded from the data), ``"all"`` (the literal ``(All)``) or
    ``"list"`` (the explicit ids in ``ids``). Ids are kept VERBATIM: the
    extractor never zero-pads legacy 3-digit ids onto the modern 4-digit grid,
    because the historical mapping is not a zero-pad.
    """

    kind: str = SCOPE_NONE
    ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableScope:
    """The row / column / sheet scope that applies to ONE table of a rule.

    The EBA keeps a single rule-level scope in dedicated spreadsheet columns; the
    BoE inlines a per-table ``scope(...)`` expression and may carry a different
    binding for each table a rule touches. Both normalise to a tuple of these.
    """

    table: str
    rows: RuleScope = RuleScope()
    columns: RuleScope = RuleScope()
    sheets: RuleScope = RuleScope()


@dataclass(frozen=True)
class ValidationRule:
    """One supervisory validation rule, normalised across both publishers.

    Attributes:
        rule_id: Publisher rule id (``v0305_m`` / ``boe_b0694``).
        publisher: ``"EBA"`` or ``"BoE"``.
        framework: ``"CRR"`` or ``"BASEL_3_1"``.
        severity: ``"ERROR"`` (blocks the submission) or ``"WARNING"``.
        rule_type: Publisher rule type (``Manual`` / ``Identity`` / ``Sign`` /
            …); empty for BoE, which does not classify.
        tables: Every table code the rule touches, in publisher order. The first
            BINDABLE one is treated as the rule's home table.
        expression: The formula to evaluate, in the publisher's own syntax
            (EBA ``formula`` / BoE ``Simplified Expression``).
        expression_raw: The BoE full ``Expression``; ``None`` for the EBA. Kept
            because it is the only carrier of the interval operators.
        table_scopes: Per-table iteration domains (see ``TableScope``).
        missing_value: ``MISSING_ZERO`` or ``MISSING_SKIP``.
        arithmetic: ``ARITHMETIC_INTERVAL`` / ``_POINT`` / ``_NOT_APPLICABLE``.
        prerequisites: Table codes that must all be reported for the rule to run.
        precondition / where: Publisher gating expressions. Both are empty across
            the whole of the current extract; they are carried so the evaluator
            can refuse (rather than silently ignore) a future taxonomy that
            populates them.
        status: ``("live",)`` or any of ``deactivated`` / ``deleted`` /
            ``not_in_xbrl``.
        reactivated_on: ISO date a deactivated rule was switched back on.
        label: The publisher's human description (EBA ``narrative`` / BoE
            ``short_label``), quoted verbatim in a finding.
    """

    rule_id: str
    publisher: str
    framework: str
    severity: str
    rule_type: str
    tables: tuple[str, ...]
    expression: str | None
    expression_raw: str | None
    table_scopes: tuple[TableScope, ...]
    missing_value: str
    arithmetic: str
    prerequisites: tuple[str, ...]
    precondition: str | None
    where: str | None
    status: tuple[str, ...]
    reactivated_on: str | None
    label: str | None

    def scope_for(self, table: str) -> TableScope:
        """Return the iteration domain bound to ``table`` (empty when unscoped)."""
        for scope in self.table_scopes:
            if scope.table == table:
                return scope
        return TableScope(table=table)


@dataclass(frozen=True)
class RuleSet:
    """A loaded, normalised extract for one framework."""

    framework: str
    publisher: str
    source: dict[str, Any]
    rules: tuple[ValidationRule, ...]

    @property
    def enforced(self) -> tuple[ValidationRule, ...]:
        """The rules currently in force (see ``is_currently_enforced``)."""
        return tuple(rule for rule in self.rules if is_currently_enforced(rule))


# =============================================================================
# Public API
# =============================================================================


@cache
def load_rules(framework: str) -> RuleSet:
    """Load and normalise the packaged rule extract for ``framework``.

    Args:
        framework: ``"CRR"`` or ``"BASEL_3_1"``.

    Returns:
        The parsed ``RuleSet``. Cached — the extracts are immutable package data.

    Raises:
        ValueError: ``framework`` is not one of the two supported frameworks.
            (A programming error, not a data-quality issue, so it raises.)
    """
    filename = _EXTRACT_FILES.get(framework)
    if filename is None:
        supported = ", ".join(sorted(_EXTRACT_FILES))
        raise ValueError(
            f"Unknown validation-rule framework {framework!r}; expected one of {supported}"
        )

    extract = resources.files(_RULES_PACKAGE).joinpath(_RULES_DIRECTORY, filename)
    payload = json.loads(extract.read_text(encoding="utf-8"))
    source = payload["source"]
    publisher = source["publisher"]
    parse = _parse_eba_rule if publisher == "EBA" else _parse_boe_rule
    rules = tuple(parse(raw, framework) for raw in payload["rules"])
    logger.debug("loaded %d %s validation rules from %s", len(rules), publisher, filename)
    return RuleSet(framework=framework, publisher=publisher, source=source, rules=rules)


def is_currently_enforced(rule: ValidationRule) -> bool:
    """Whether a rule is in force today.

    ``live`` alone is not the answer for the EBA: 153 matched rules were
    deactivated and later reactivated, so they report as ``deactivated`` while
    still being enforced. The wider "not permanently withdrawn" population is
    ``live`` OR ``reactivated_on``, in both cases excluding ``deleted``
    (741 EBA rules, against 588 on ``status`` alone). The BoE taxonomy has no
    reactivation concept, so the second limb never fires there.
    """
    if "deleted" in rule.status:
        return False
    return rule.status == ("live",) or rule.reactivated_on is not None


def rules_for_tables(
    rules: Iterable[ValidationRule], tables: Iterable[str]
) -> list[ValidationRule]:
    """Filter rules to those touching ANY of ``tables``.

    A rule is included if *any* of its table codes matches, never just the first
    — a cross-table rule lists both sides and either may be the one of interest.
    """
    wanted = tuple(tables)
    return [rule for rule in rules if any(t.startswith(wanted) for t in rule.tables)]


def build_rule_reference(publisher: str, tables: Iterable[str]) -> str:
    """Docstring-style regulatory reference for a rule, for a finding.

    Template-annex references live on the finding rather than as ``@cites``
    decorators: the watchfire grammar targets a code path implementing a single
    article, not a cross-template validation rule addressing several.
    """
    codes = ", ".join(tables)
    if publisher == "EBA":
        return f"EBA DPM 3.0(3.0.1) validation rules; COREP Annex II {codes}"
    return f"BoE banking_reporting v4.0.0 validation rules; PRA PS1/26 Annex II {codes}"


# =============================================================================
# Private helpers — per-publisher normalisation
# =============================================================================


def _parse_eba_rule(raw: dict[str, Any], framework: str) -> ValidationRule:
    """Normalise one EBA rule object onto ``ValidationRule``."""
    tables = tuple(raw["tables"])
    scope = TableScope(
        table=tables[0] if tables else "",
        rows=RuleScope(raw["rows_scope"], tuple(raw["rows"])),
        columns=RuleScope(raw["columns_scope"], tuple(raw["columns"])),
        sheets=RuleScope(raw["sheets_scope"], tuple(raw["sheets"])),
    )
    return ValidationRule(
        rule_id=raw["id"],
        publisher="EBA",
        framework=framework,
        severity=raw["severity"],
        rule_type=raw["type"],
        tables=tables,
        expression=raw["formula"],
        expression_raw=None,
        table_scopes=(scope,) if tables else (),
        missing_value=_eba_missing_value(raw["if_value_missing"]),
        arithmetic=_eba_arithmetic(raw["arithmetic_approach"]),
        prerequisites=_split_prerequisites(raw["prerequisites"]),
        precondition=None,
        where=None,
        status=tuple(raw["status"]),
        reactivated_on=raw["reactivated_on"],
        label=raw["narrative"],
    )


def _parse_boe_rule(raw: dict[str, Any], framework: str) -> ValidationRule:
    """Normalise one BoE rule object onto ``ValidationRule``."""
    expression_raw = raw["expression_raw"]
    return ValidationRule(
        rule_id=raw["id"],
        publisher="BoE",
        framework=framework,
        severity=raw["severity"],
        rule_type="",
        tables=tuple(raw["tables"]),
        expression=raw["expression"],
        expression_raw=expression_raw,
        table_scopes=_parse_boe_scope(raw["scope"]),
        # ``dv`` is the XBRL formula default value for an unreported fact — the
        # taxonomy's own statement of the missing-value policy, standing in for
        # the EBA's dedicated column (see the module docstring). Absent ``dv``,
        # skip rather than invent a zero.
        missing_value=MISSING_ZERO if "dv:" in (expression_raw or "") else MISSING_SKIP,
        arithmetic=_boe_arithmetic(expression_raw),
        prerequisites=(),
        precondition=raw["precondition"] or raw["precondition_raw"],
        where=raw["where"],
        status=tuple(raw["status"]),
        reactivated_on=None,
        label=raw["short_label"],
    )


def _eba_missing_value(value: str | None) -> str:
    """Map the EBA ``If value missing`` column onto the two-way policy.

    ``treat as zero/empty string`` -> ``MISSING_ZERO``. Everything else
    (``do not run rule``, ``not applicable``, blank) -> ``MISSING_SKIP``: the
    conservative reading, because inventing a 0.0 for a cell the publisher did
    not ask us to default turns an unreported figure into an assertion.
    """
    if value and value.strip().lower().startswith("treat as zero"):
        return MISSING_ZERO
    return MISSING_SKIP


def _eba_arithmetic(value: str | None) -> str:
    """Map the EBA ``Arithmetic approach`` column (case-insensitive; ``Mixed`` is tolerant).

    The sheet spells the same value several ways (``Interval`` / ``interval``,
    ``Not applicable`` / ``Not Applicable``), so the comparison is folded.
    ``Mixed`` is treated as ``Interval`` — the tolerant reading, so a rounding
    difference is never reported as a break.
    """
    normalised = (value or "").strip().lower()
    if normalised.startswith("interval") or normalised.startswith("mixed"):
        return ARITHMETIC_INTERVAL
    if normalised.startswith("point"):
        return ARITHMETIC_POINT
    return ARITHMETIC_NOT_APPLICABLE


def _boe_arithmetic(expression_raw: str | None) -> str:
    """Recover the BoE comparison semantics from the RAW expression.

    The simplified expression collapses ``i=`` to ``=``, losing the tolerance;
    the raw one keeps it. An interval operator anywhere in the raw expression
    means the comparison is rounding-tolerant.
    """
    if expression_raw and _BOE_INTERVAL_OPERATOR.search(expression_raw):
        return ARITHMETIC_INTERVAL
    return ARITHMETIC_POINT


def _parse_boe_scope(scope: str | None) -> tuple[TableScope, ...]:
    """Parse a ``scope({t: T, r:..., c:..., z:...}, …)`` expression.

    Returns one ``TableScope`` per brace group. An axis absent from the group
    stays ``SCOPE_NONE`` — the BoE omits an axis precisely when the expression
    addresses it, mirroring the EBA's blank scope cell.
    """
    if not scope:
        return ()
    scopes: list[TableScope] = []
    for group in _BOE_SCOPE_GROUP.findall(scope):
        keys = {key: value.strip() for key, value in _BOE_SCOPE_KEY.findall(group)}
        table = keys.get("t")
        if not table:
            continue
        scopes.append(
            TableScope(
                table=table,
                rows=_boe_axis(keys.get("r")),
                columns=_boe_axis(keys.get("c")),
                sheets=_boe_axis(keys.get("z")),
            )
        )
    return tuple(scopes)


def _boe_axis(value: str | None) -> RuleScope:
    """Turn a ``0010;0020;0030`` scope value into a ``RuleScope``."""
    if not value:
        return RuleScope()
    ids = tuple(token.strip() for token in value.split(";") if token.strip())
    return RuleScope(SCOPE_LIST, ids) if ids else RuleScope()


def _split_prerequisites(value: str | None) -> tuple[str, ...]:
    """Split ``"C 07.00.a and C 07.00.b"`` into its table codes."""
    if not value:
        return ()
    return tuple(token.strip() for token in _PREREQUISITE_SPLIT.split(value) if token.strip())
