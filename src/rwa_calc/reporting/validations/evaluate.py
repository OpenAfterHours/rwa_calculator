"""
Expression parsing and evaluation for one supervisory validation rule.

Pipeline position:
    ValidationRule -> parse_expression -> Expression
    Expression + Coordinate + TemplateIndex -> evaluate_at -> CoordinateOutcome

Key responsibilities:
- Parse BOTH publishers' reference grammars onto one AST. The EBA writes
  ``{C 08.01.a, r0070, c0020}`` and hoists the loop into spreadsheet scope
  columns; the BoE writes ``{t: OF08.01.01.01, r: 0070, c: 0020, z: 0002}`` and
  hoists it into a ``scope(...)`` expression. Neither formula is self-contained.
- Evaluate one coordinate with the publisher's own semantics: the
  ``Interval`` / ``Point`` tolerance split, and the ``treat as zero`` /
  ``do not run rule`` missing-value split — which give materially different
  answers on the same figures.
- Refuse, loudly and by name, every construct that is not supported. A rule that
  cannot be evaluated is NOT_EVALUATED with a reason; it is never a silent pass
  and never a break.

Distinctions that are load-bearing here:

- A structurally ABSENT cell (row / column / sheet this estate never emitted) is
  not a zero and not a break — it is a skip. Collapsing the two produces a false
  positive on any rule that sums template rows a credit-risk calculator does not
  produce.
- An all-null / all-zero comparison is VACUOUS, not a PASS. A vacuous pass is no
  evidence of correctness and is counted separately.

References:
- docs/reference/validation-rules/index.md — the formula grammar for both sources
- COREP Annex II; PRA PS1/26 Annex II (the templates the coordinates address)
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from rwa_calc.reporting.validations.rules import (
    ARITHMETIC_POINT,
    MISSING_ZERO,
)
from rwa_calc.reporting.validations.scope import (
    SHEET_INDEX_MAPS,
    SINGLE_SHEET,
    SKIP_COLUMN_NOT_EMITTED,
    SKIP_ROW_NOT_EMITTED,
    SKIP_SHEET_NOT_EMITTED,
    resolve_sheet_codes,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from rwa_calc.reporting.validations.scope import Coordinate, TemplateIndex

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

STATUS_PASS: Final = "PASS"
STATUS_FAIL: Final = "FAIL"
STATUS_VACUOUS: Final = "VACUOUS"
STATUS_NOT_EVALUATED: Final = "NOT_EVALUATED"

#: Golden convention, shared with reporting/tieouts.py: relative 1e-9 with a
#: small absolute floor for near-zero sums. Used for every ``Interval``
#: (rounding-tolerant) comparison; a ``Point`` rule compares exactly.
DEFAULT_RTOL: Final = 1e-9
DEFAULT_ATOL: Final = 1e-6

SKIP_UNSUPPORTED_GRAMMAR: Final = "unsupported_grammar"
SKIP_NO_EXPRESSION: Final = "no_expression"
SKIP_MISSING_VALUE_DO_NOT_RUN: Final = "missing_value_do_not_run"
SKIP_CELL_NOT_EMITTED: Final = "cell_not_emitted"
SKIP_AMBIGUOUS_AXIS: Final = "ambiguous_axis"
SKIP_NON_FINITE_VALUE: Final = "non_finite_value"
SKIP_PRECONDITION_UNSUPPORTED: Final = "precondition_unsupported"
SKIP_WHERE_UNSUPPORTED: Final = "where_unsupported"

#: Constructs this evaluator deliberately does not implement, each mapped to the
#: reason recorded on the skipped rule. Evaluating any of them approximately
#: would produce findings that look authoritative and are not.
_UNSUPPORTED_MARKERS: Final[tuple[tuple[str, str], ...]] = (
    ("if ", "conditional (if/then) rule"),
    ("then", "conditional (if/then) rule"),
    ("where(", "where(...) row filter"),
    ("count(", "count(...) aggregate"),
    ("isnull", "isNull(...) predicate"),
    ("true()", "boolean literal"),
    (" and ", "boolean conjunction"),
    (" or ", "boolean disjunction"),
    ("empty(", "empty(...) function form"),
    ("not(", "negated dimensional filter"),
)

# ── Dimensional filters ──────────────────────────────────────────────────────
# Only ONE dimensional filter is understood: the counterparty-geography
# dimension restricted to the all-geographies member, which selects the total
# sheet of our per-country C 09.0x dicts. Every other dimension / member is
# refused by name.
#
# ``eba_GA:x1`` is the TOTAL across all geographies, not "domestic". Three
# independent sources, none of them the pass/fail outcome of the rules:
#
#   * v8732_m states it arithmetically in the taxonomy's own language —
#     ``sum(members except x0) - x1 = x1``, i.e. sum(individual countries) = x1.
#     A member equal to the sum of all the others is the total.
#   * The ``eba_GA`` domain's country members are ISO 3166 alpha-2 codes
#     (``GB``, ``US``, …, enumerated by v4023_a); ``x0`` / ``x1`` / ``x28`` sit
#     in the separate numeric namespace the DPM uses for non-country members, so
#     x1 cannot BE a country.
#   * PS1/26 Annex II §3.4 para 85: "All institutions shall submit information
#     aggregated at a total level", with the per-country breakdown conditional on
#     the Article 5(5) threshold. A rule that must hold for every filer — and 290
#     BoE / 216 EBA rules carry this filter — can only address the total level.
#
# ``x0`` (2 uses, the "no geography" member) is deliberately NOT mapped.
_GEOGRAPHY_DIMENSION: Final = "CEG"
_GEOGRAPHY_TOTAL_MEMBER: Final = "eba_GA:x1"

#: Our per-country C 09.01 / C 09.02 dicts key the whole population under this
#: sheet name (``reporting/corep/c09.py`` emits ``("TOTAL", data)`` first, then
#: one frame per counterparty country).
GEOGRAPHY_TOTAL_SHEET: Final = "TOTAL"

#: BoE ``filter: [eba_dim:CEG] = [eba_GA:x1]`` / EBA ``[CEG=eba_GA:x1]``.
_BOE_FILTER = re.compile(r"^\[eba_dim:(?P<dim>[A-Za-z_]+)\]\s*=\s*\[(?P<member>[^]]+)\]$")
# No `\s*` after the "=": `[^]]+` already accepts the separating space, so having
# both makes their boundary ambiguous and the engine tries every split of the gap
# on a filter that fails to match. ``_parse_filter`` strips both groups anyway.
_EBA_FILTER = re.compile(r"^\[(?P<dim>[A-Za-z_]+)\s*=(?P<member>[^]]+)\]$")

#: Aggregate functions whose arguments expand every unbound axis to ALL values,
#: rather than inheriting the current coordinate.
_AGGREGATES: Final[frozenset[str]] = frozenset({"sum", "max", "min"})

#: ``{C 08.02, rNNN}`` — the open-row wildcard for variable-row templates.
_OPEN_ROW_WILDCARD: Final = re.compile(r"\br[Nn]{2,}\b")

_TOKEN = re.compile(
    r"""
    (?P<ref>\{[^{}]*\})
  | (?P<number>\d*\.?\d+\s*%?)
  | (?P<ident>[A-Za-z_][A-Za-z_0-9]*)
  | (?P<compare>==|>=|<=|!=|=|>|<)
  | (?P<punct>[+\-*/(),])
  | (?P<space>\s+)
    """,
    re.VERBOSE,
)

# EBA reference tokens: ``r0010`` / ``c0090`` / ``s0003`` / ``(s0003-0004)``.
_EBA_AXIS = re.compile(r"^(?P<axis>[rcs])(?P<id>\d{3,5})$")
_EBA_SHEET_RANGE = re.compile(r"^\(s(?P<start>\d{3,4})\s*-\s*s?(?P<end>\d{3,4})\)$")
# BoE reference tokens: ``t: X`` / ``r: 0010; 0020`` / ``z: 0001;0002``.
_BOE_KEY = re.compile(r"^(?P<key>[a-z]+)\s*:\s*(?P<value>.*)$", re.DOTALL)


class UnsupportedExpression(Exception):
    """The expression uses a construct this evaluator refuses to approximate."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


class SkipCoordinate(Exception):
    """This coordinate cannot be evaluated (absent cell, missing value, NaN)."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


# =============================================================================
# AST
# =============================================================================


@dataclass(frozen=True)
class Ref:
    """One ``{...}`` cell reference, normalised across both grammars.

    An axis left as ``None`` is NOT unconstrained — it binds to the current
    coordinate (or, inside an aggregate, to every emitted value).

    ``geography`` carries a dimensional restriction that names one of our sheets
    directly (today only the all-geographies total of the per-country C 09.0x
    dicts). It selects the sheet exactly as an explicit ``sheets`` would.
    """

    table: str | None
    rows: tuple[str, ...] | None
    columns: tuple[str, ...] | None
    sheets: tuple[str, ...] | None
    geography: str | None = None


@dataclass(frozen=True)
class Number:
    """A numeric literal; percentages are already divided out."""

    value: float


@dataclass(frozen=True)
class EmptyLiteral:
    """The ``empty`` keyword — "this cell must not be reported"."""


@dataclass(frozen=True)
class Call:
    """``sum(...)`` / ``abs(...)`` / ``max(...)`` / ``min(...)``."""

    name: str
    args: tuple[object, ...]


@dataclass(frozen=True)
class BinOp:
    """An arithmetic node (``+ - * /``)."""

    op: str
    lhs: object
    rhs: object


@dataclass(frozen=True)
class Compare:
    """The rule's top-level comparison."""

    op: str
    lhs: object
    rhs: object


@dataclass(frozen=True)
class Expression:
    """A parsed rule expression plus the axis facts scope expansion needs."""

    root: Compare
    needs_row_axis: bool
    needs_column_axis: bool
    needs_sheet_axis: bool


@dataclass(frozen=True)
class CoordinateOutcome:
    """The result of evaluating one rule at one coordinate."""

    coordinate: Coordinate
    status: str
    lhs: float | None = None
    rhs: float | None = None
    reason: str = ""
    detail: str = ""


# =============================================================================
# Public API
# =============================================================================


def parse_expression(text: str | None) -> Expression:
    """Parse a publisher formula / expression into an evaluable ``Expression``.

    Raises:
        UnsupportedExpression: the text is empty, uses a construct this
            evaluator refuses to approximate, or is not a single comparison.
    """
    if not text or not text.strip():
        raise UnsupportedExpression(SKIP_NO_EXPRESSION, "rule carries no formula")

    lowered = text.lower()
    for marker, detail in _UNSUPPORTED_MARKERS:
        if marker in lowered:
            raise UnsupportedExpression(SKIP_UNSUPPORTED_GRAMMAR, detail)
    if _OPEN_ROW_WILDCARD.search(text):
        raise UnsupportedExpression(SKIP_UNSUPPORTED_GRAMMAR, "open-row wildcard")

    parser = _Parser(_tokenise(text))
    root = parser.parse_comparison()
    refs = tuple(_walk_refs(root, aggregated=False))
    return Expression(
        root=root,
        needs_row_axis=any(ref.rows is None for ref in refs),
        needs_column_axis=any(ref.columns is None for ref in refs),
        # A reference that names its own sheet — positionally or through a
        # dimensional filter — does not need the coordinate grid to iterate
        # sheets. Without this, a geography-filtered cross-table identity would
        # be re-evaluated identically once per country sheet and counted twice.
        needs_sheet_axis=any(ref.sheets is None and ref.geography is None for ref in refs),
    )


def evaluate_at(
    expression: Expression,
    coordinate: Coordinate,
    index: TemplateIndex,
    *,
    missing_value: str,
    arithmetic: str,
) -> CoordinateOutcome:
    """Evaluate one parsed rule at one coordinate.

    Returns a ``CoordinateOutcome`` with status ``PASS`` / ``FAIL`` /
    ``VACUOUS`` / ``NOT_EVALUATED``; it never raises for a data condition.
    """
    context = _Context(index=index, coordinate=coordinate, missing_value=missing_value)
    root = expression.root
    try:
        if isinstance(root.rhs, EmptyLiteral) or isinstance(root.lhs, EmptyLiteral):
            return _evaluate_emptiness(root, context, coordinate)
        lhs = _value_of(root.lhs, context, aggregated=False)
        rhs = _value_of(root.rhs, context, aggregated=False)
    except SkipCoordinate as skip:
        return CoordinateOutcome(
            coordinate, STATUS_NOT_EVALUATED, reason=skip.reason, detail=skip.detail
        )

    if not (math.isfinite(lhs) and math.isfinite(rhs)):
        return CoordinateOutcome(
            coordinate, STATUS_NOT_EVALUATED, lhs, rhs, SKIP_NON_FINITE_VALUE, "NaN/inf operand"
        )
    if not _compare(root.op, lhs, rhs, arithmetic):
        return CoordinateOutcome(coordinate, STATUS_FAIL, lhs, rhs)
    if context.vacuous:
        return CoordinateOutcome(coordinate, STATUS_VACUOUS, lhs, rhs)
    return CoordinateOutcome(coordinate, STATUS_PASS, lhs, rhs)


# =============================================================================
# Parsing
# =============================================================================


def _tokenise(text: str) -> list[tuple[str, str]]:
    """Split an expression into ``(kind, text)`` tokens, dropping whitespace."""
    tokens: list[tuple[str, str]] = []
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            raise UnsupportedExpression(
                SKIP_UNSUPPORTED_GRAMMAR,
                f"unparseable at offset {position}: {text[position : position + 20]!r}",
            )
        position = match.end()
        kind = match.lastgroup or ""
        if kind != "space":
            tokens.append((kind, match.group().strip()))
    return tokens


class _Parser:
    """Recursive-descent parser over the token list (one comparison per rule)."""

    def __init__(self, tokens: Sequence[tuple[str, str]]) -> None:
        self._tokens = tokens
        self._position = 0

    def parse_comparison(self) -> Compare:
        """``Sum (op Sum)`` — the rule's single top-level comparison."""
        lhs = self._parse_sum()
        kind, text = self._peek()
        if kind != "compare":
            raise UnsupportedExpression(SKIP_UNSUPPORTED_GRAMMAR, "no top-level comparison")
        self._advance()
        rhs = self._parse_sum()
        if self._position != len(self._tokens):
            raise UnsupportedExpression(
                SKIP_UNSUPPORTED_GRAMMAR,
                f"trailing tokens after comparison: {self._tokens[self._position :]}",
            )
        return Compare(text, lhs, rhs)

    def _parse_sum(self) -> object:
        node = self._parse_product()
        while self._peek() == ("punct", "+") or self._peek() == ("punct", "-"):
            op = self._advance()[1]
            node = BinOp(op, node, self._parse_product())
        return node

    def _parse_product(self) -> object:
        node = self._parse_unary()
        while self._peek() == ("punct", "*") or self._peek() == ("punct", "/"):
            op = self._advance()[1]
            node = BinOp(op, node, self._parse_unary())
        return node

    def _parse_unary(self) -> object:
        kind, text = self._peek()
        if kind == "punct" and text in ("+", "-"):
            self._advance()
            operand = self._parse_unary()
            return operand if text == "+" else BinOp("-", Number(0.0), operand)
        return self._parse_atom()

    def _parse_atom(self) -> object:
        kind, text = self._advance()
        if kind == "ref":
            return _parse_ref(text)
        if kind == "number":
            return _parse_number(text)
        if kind == "ident":
            return self._parse_ident(text)
        if kind == "punct" and text == "(":
            node = self._parse_sum()
            self._expect(")")
            return node
        raise UnsupportedExpression(SKIP_UNSUPPORTED_GRAMMAR, f"unexpected token {text!r}")

    def _parse_ident(self, name: str) -> object:
        lowered = name.lower()
        if lowered == "empty":
            return EmptyLiteral()
        if self._peek() != ("punct", "("):
            raise UnsupportedExpression(SKIP_UNSUPPORTED_GRAMMAR, f"bare identifier {name!r}")
        self._advance()
        args: list[object] = [self._parse_sum()]
        while self._peek() == ("punct", ","):
            self._advance()
            args.append(self._parse_sum())
        self._expect(")")
        if lowered not in _AGGREGATES and lowered != "abs":
            raise UnsupportedExpression(SKIP_UNSUPPORTED_GRAMMAR, f"function {name}(...)")
        return Call(lowered, tuple(args))

    def _peek(self) -> tuple[str, str]:
        if self._position >= len(self._tokens):
            return ("", "")
        return self._tokens[self._position]

    def _advance(self) -> tuple[str, str]:
        if self._position >= len(self._tokens):
            raise UnsupportedExpression(SKIP_UNSUPPORTED_GRAMMAR, "expression ended early")
        token = self._tokens[self._position]
        self._position += 1
        return token

    def _expect(self, text: str) -> None:
        kind, actual = self._advance()
        if kind != "punct" or actual != text:
            raise UnsupportedExpression(
                SKIP_UNSUPPORTED_GRAMMAR, f"expected {text!r}, got {actual!r}"
            )


def _parse_number(text: str) -> Number:
    """Parse a numeric literal, dividing a trailing ``%`` out."""
    body = text.replace(" ", "")
    if body.endswith("%"):
        return Number(float(body[:-1]) / 100.0)
    return Number(float(body))


def _parse_ref(text: str) -> Ref:
    """Parse one ``{...}`` reference in either publisher's grammar."""
    body = text.strip("{}").strip()
    if not body:
        raise UnsupportedExpression(SKIP_UNSUPPORTED_GRAMMAR, "empty reference")

    table: str | None = None
    rows: list[str] = []
    columns: list[str] = []
    sheets: list[str] = []
    geography: str | None = None
    for token in (part.strip() for part in body.split(",")):
        if not token:
            continue
        keyed = _BOE_KEY.match(token)
        if keyed is not None and keyed.group("key") in (
            "t",
            "r",
            "c",
            "z",
            "dv",
            "seq",
            "id",
            "f",
            "fv",
            "filter",
        ):
            key, value = keyed.group("key"), keyed.group("value").strip()
            if key == "t":
                table = value
            elif key == "r":
                rows.extend(_split_ids(value))
            elif key == "c":
                columns.extend(_split_ids(value))
            elif key == "z":
                sheets.extend(_split_ids(value))
            elif key == "filter":
                geography = _parse_filter(_BOE_FILTER, value)
            continue
        if token.startswith("["):
            geography = _parse_filter(_EBA_FILTER, token)
            continue
        axis = _EBA_AXIS.match(token)
        if axis is not None:
            target = {"r": rows, "c": columns, "s": sheets}[axis.group("axis")]
            target.append(axis.group("id"))
            continue
        span = _EBA_SHEET_RANGE.match(token)
        if span is not None:
            sheets.extend(_expand_sheet_range(span.group("start"), span.group("end")))
            continue
        if table is None:
            table = token
            continue
        raise UnsupportedExpression(
            SKIP_UNSUPPORTED_GRAMMAR, f"unrecognised reference part {token!r}"
        )

    return Ref(
        table=table,
        rows=tuple(rows) or None,
        columns=tuple(columns) or None,
        sheets=tuple(sheets) or None,
        geography=geography,
    )


def _parse_filter(pattern: re.Pattern[str], text: str) -> str:
    """Resolve a dimensional filter to the sheet it selects, or refuse by name.

    Only ``CEG = eba_GA:x1`` (counterparty geography, all-geographies total) is
    understood. Every other dimension or member — the ``RIO`` obligor-residence
    breakdown, the ``TSL`` specialised-lending type, the ``x0`` no-geography
    member — raises, because guessing which of our sheets it selects would
    produce confident findings on the wrong population.
    """
    match = pattern.match(text.strip())
    if match is None:
        raise UnsupportedExpression(SKIP_UNSUPPORTED_GRAMMAR, f"dimensional filter {text!r}")
    dimension = match.group("dim").strip()
    member = match.group("member").strip()
    if dimension != _GEOGRAPHY_DIMENSION or member != _GEOGRAPHY_TOTAL_MEMBER:
        raise UnsupportedExpression(
            SKIP_UNSUPPORTED_GRAMMAR, f"dimensional filter [{dimension}] = [{member}]"
        )
    return GEOGRAPHY_TOTAL_SHEET


def _split_ids(value: str) -> list[str]:
    """Split a ``0010; 0020; 0030`` multi-valued axis into ids."""
    return [token.strip() for token in value.split(";") if token.strip()]


def _expand_sheet_range(start: str, end: str) -> list[str]:
    """Expand ``(s0003-0004)`` into every code it spans, at the source width."""
    width = max(len(start), len(end))
    return [str(code).zfill(width) for code in range(int(start), int(end) + 1)]


def _walk_refs(node: object, *, aggregated: bool) -> list[Ref]:
    """Collect refs OUTSIDE any aggregate.

    A ref inside ``sum(...)`` expands its own unbound axes, so it must not force
    the rule's coordinate grid to iterate that axis.
    """
    if isinstance(node, Ref):
        return [] if aggregated else [node]
    if isinstance(node, Call):
        inner = aggregated or node.name in _AGGREGATES
        return [ref for arg in node.args for ref in _walk_refs(arg, aggregated=inner)]
    if isinstance(node, BinOp | Compare):
        return _walk_refs(node.lhs, aggregated=aggregated) + _walk_refs(
            node.rhs, aggregated=aggregated
        )
    return []


# =============================================================================
# Evaluation
# =============================================================================


@dataclass
class _Context:
    """Mutable evaluation state for one coordinate."""

    index: TemplateIndex
    coordinate: Coordinate
    missing_value: str
    vacuous: bool = True

    def observe(self, value: float) -> None:
        """Record a contributing cell; a non-zero one makes the rule non-vacuous.

        Vacuity is an exact-zero property — a rule over cells that are all
        precisely 0.0 proves nothing — so this tests the float's own truthiness
        rather than comparing against a tolerance, which would silently declare
        a rule vacuous over small but real numbers.
        """
        if value:
            self.vacuous = False


def _value_of(node: object, context: _Context, *, aggregated: bool) -> float:
    """Evaluate an AST node to a scalar."""
    if isinstance(node, Number):
        return node.value
    if isinstance(node, Ref):
        return _sum_cells(node, context, aggregated=aggregated)
    if isinstance(node, BinOp):
        return _apply_binop(node, context, aggregated=aggregated)
    if isinstance(node, Call):
        return _apply_call(node, context, aggregated=aggregated)
    raise UnsupportedExpression(SKIP_UNSUPPORTED_GRAMMAR, f"cannot evaluate {type(node).__name__}")


def _apply_binop(node: BinOp, context: _Context, *, aggregated: bool) -> float:
    """Apply an arithmetic operator, refusing division by zero.

    The divisor guard is an exact-zero test (a falsy float is ``0.0`` or
    ``-0.0``): only a true zero makes the quotient undefined, and refusing
    divisors merely *close* to zero would skip coordinates the rule can answer.
    """
    lhs = _value_of(node.lhs, context, aggregated=aggregated)
    rhs = _value_of(node.rhs, context, aggregated=aggregated)
    if node.op == "+":
        return lhs + rhs
    if node.op == "-":
        return lhs - rhs
    if node.op == "*":
        return lhs * rhs
    if not rhs:
        raise SkipCoordinate(SKIP_NON_FINITE_VALUE, "division by zero")
    return lhs / rhs


def _apply_call(node: Call, context: _Context, *, aggregated: bool) -> float:
    """Apply ``abs`` / ``sum`` / ``max`` / ``min``."""
    if node.name == "abs":
        return abs(_value_of(node.args[0], context, aggregated=aggregated))
    if node.name == "sum":
        return sum(_value_of(arg, context, aggregated=True) for arg in node.args)
    values = [_cell_values(arg, context) for arg in node.args]
    flat = [value for group in values for value in group]
    if not flat:
        raise SkipCoordinate(SKIP_CELL_NOT_EMITTED, f"{node.name}(...) over no emitted cell")
    return max(flat) if node.name == "max" else min(flat)


def _cell_values(node: object, context: _Context) -> list[float]:
    """Every individual cell behind a node, for ``max`` / ``min``."""
    if isinstance(node, Ref):
        return list(_resolve_cells(node, context, aggregated=True))
    return [_value_of(node, context, aggregated=True)]


def _sum_cells(ref: Ref, context: _Context, *, aggregated: bool) -> float:
    """Resolve a reference to a scalar, summing whenever it spans several cells.

    A multi-cell reference arises from an explicit multi-valued axis
    (``r: 0010; 0020``, ``(s0003-0004)``), from an aggregate expanding an unbound
    axis, or from a publisher sheet code that maps onto more than one of our
    sheets. Summation is the publisher's own reading in the first two cases and
    the only additive reading in the third.
    """
    return sum(_resolve_cells(ref, context, aggregated=aggregated))


def _resolve_cells(ref: Ref, context: _Context, *, aggregated: bool) -> list[float]:
    """Read every cell a reference addresses, applying the missing-value policy."""
    table, sheets, rows, columns = _reference_axes(ref, context, aggregated=aggregated)
    values: list[float] = []
    for sheet in sheets:
        for row in rows:
            for column in columns:
                cell = context.index.cell(table, sheet, row, column)
                if not cell.present:
                    raise _absence(context, table, sheet, row, column)
                if cell.value is None:
                    if context.missing_value != MISSING_ZERO:
                        raise SkipCoordinate(
                            SKIP_MISSING_VALUE_DO_NOT_RUN,
                            f"{table}[{sheet}][r{row}][c{column}] is not reported",
                        )
                    values.append(0.0)
                    continue
                context.observe(cell.value)
                values.append(cell.value)
    return values


def _absence(context: _Context, table: str, sheet: str, row: str, column: str) -> SkipCoordinate:
    """Name WHICH axis is missing, so the skip reason is diagnostic.

    The distinction matters to a reader triaging a report: a row the estate never
    emits (a market-risk line in C 02.00) is a scope statement about this
    calculator, whereas a missing column is usually a framework-variant gap.
    """
    where = f"{table}[{sheet}][r{row}][c{column}]"
    if row not in context.index.row_refs(table, sheet):
        return SkipCoordinate(SKIP_ROW_NOT_EMITTED, f"{where}: row {row} is not emitted")
    if column not in context.index.column_refs(table, sheet):
        return SkipCoordinate(SKIP_COLUMN_NOT_EMITTED, f"{where}: column {column} is not emitted")
    return SkipCoordinate(SKIP_CELL_NOT_EMITTED, f"{where} not emitted")


def _reference_axes(
    ref: Ref, context: _Context, *, aggregated: bool
) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Resolve a reference's table and its three axes to concrete ids."""
    coordinate = context.coordinate
    table = ref.table or coordinate.table
    binding = context.index.binding(table)
    if binding is None or not context.index.is_emitted(table):
        raise SkipCoordinate(SKIP_CELL_NOT_EMITTED, f"{table} not emitted")

    sheets = _reference_sheets(ref, table, context, binding.sheet_map, aggregated=aggregated)
    rows = _reference_axis(
        ref.rows,
        coordinate.row,
        lambda sheet: context.index.row_refs(table, sheet),
        sheets,
        aggregated=aggregated,
        axis="row",
    )
    columns = _reference_axis(
        ref.columns,
        coordinate.column,
        lambda sheet: context.index.column_refs(table, sheet),
        sheets,
        aggregated=aggregated,
        axis="column",
    )
    return table, sheets, rows, columns


def _reference_sheets(
    ref: Ref, table: str, context: _Context, sheet_map_name: str | None, *, aggregated: bool
) -> tuple[str, ...]:
    """Resolve the sheet axis of a reference."""
    emitted = context.index.sheet_keys(table)
    if not emitted:
        raise SkipCoordinate(SKIP_CELL_NOT_EMITTED, f"{table} has no emitted sheet")
    if emitted == (SINGLE_SHEET,):
        return emitted

    if ref.geography is not None:
        if ref.geography not in emitted:
            raise SkipCoordinate(
                SKIP_SHEET_NOT_EMITTED, f"{table} has no {ref.geography} geography sheet"
            )
        return (ref.geography,)

    if ref.sheets is not None:
        sheet_map = SHEET_INDEX_MAPS.get(sheet_map_name or "")
        if sheet_map is None:
            raise SkipCoordinate(
                SKIP_AMBIGUOUS_AXIS, f"{table} sheets are not indexed positionally"
            )
        resolution = resolve_sheet_codes(ref.sheets, sheet_map, emitted)
        if resolution.skip_reason is not None:
            raise SkipCoordinate(resolution.skip_reason, resolution.detail)
        return resolution.sheets

    if context.coordinate.sheet in emitted:
        return (context.coordinate.sheet,)
    if aggregated:
        return emitted
    raise SkipCoordinate(SKIP_AMBIGUOUS_AXIS, f"{table} sheet not fixed by the rule's scope")


def _reference_axis(
    explicit: tuple[str, ...] | None,
    current: str | None,
    emitted_for: Callable[[str], tuple[str, ...]],
    sheets: tuple[str, ...],
    *,
    aggregated: bool,
    axis: str,
) -> tuple[str, ...]:
    """Resolve one of the row / column axes of a reference."""
    if explicit is not None:
        return explicit
    if current is not None:
        return (current,)
    if not aggregated:
        raise SkipCoordinate(SKIP_AMBIGUOUS_AXIS, f"{axis} not fixed by the rule's scope")
    # Inside an aggregate an unbound axis expands to every emitted id. The
    # sheets a reference spans always share a template, so the first sheet's
    # axis is the template's axis.
    values = emitted_for(sheets[0])
    if not values:
        raise SkipCoordinate(SKIP_CELL_NOT_EMITTED, f"no {axis} emitted")
    return values


def _evaluate_emptiness(
    root: Compare, context: _Context, coordinate: Coordinate
) -> CoordinateOutcome:
    """Evaluate the ``{ref} = empty`` nonexistence form.

    ``empty`` asks whether the cell was REPORTED, so the missing-value policy
    does not apply: a null cell is the passing state, not a zero.
    """
    ref = root.lhs if isinstance(root.rhs, EmptyLiteral) else root.rhs
    if not isinstance(ref, Ref):
        return CoordinateOutcome(
            coordinate,
            STATUS_NOT_EVALUATED,
            reason=SKIP_UNSUPPORTED_GRAMMAR,
            detail="empty compared to an expression",
        )
    try:
        table, sheets, rows, columns = _reference_axes(ref, context, aggregated=True)
    except SkipCoordinate as skip:
        return CoordinateOutcome(
            coordinate, STATUS_NOT_EVALUATED, reason=skip.reason, detail=skip.detail
        )

    reported: list[float] = []
    for sheet in sheets:
        for row in rows:
            for column in columns:
                cell = context.index.cell(table, sheet, row, column)
                if cell.present and cell.value is not None:
                    reported.append(cell.value)
    is_empty = not reported
    passed = is_empty if root.op in ("=", "==") else not is_empty
    if not passed:
        return CoordinateOutcome(
            coordinate,
            STATUS_FAIL,
            lhs=float(len(reported)),
            rhs=0.0,
            detail=f"{len(reported)} cell(s) reported where the rule requires none",
        )
    return CoordinateOutcome(coordinate, STATUS_VACUOUS if is_empty else STATUS_PASS)


def _compare(op: str, lhs: float, rhs: float, arithmetic: str) -> bool:
    """Compare two figures under the rule's arithmetic approach.

    ``Point`` compares exactly (after folding ``-0.0`` onto ``0.0``, which is the
    same reported figure); ``Interval`` allows the golden rounding tolerance, so
    a rule the publisher declared rounding-tolerant is never reported as a break
    over float dust. ``Not applicable`` — the publisher's marker for a rule that
    is not an arithmetic comparison at all — takes the tolerant path too: the
    conservative choice, since the alternative invents breaks the publisher never
    asked for.
    """
    lhs += 0.0
    rhs += 0.0
    tolerance = (
        0.0
        if arithmetic == ARITHMETIC_POINT
        else DEFAULT_ATOL + DEFAULT_RTOL * max(abs(lhs), abs(rhs))
    )
    if op in ("=", "=="):
        return abs(lhs - rhs) <= tolerance
    if op == "!=":
        return abs(lhs - rhs) > tolerance
    if op == ">=":
        return lhs >= rhs - tolerance
    if op == "<=":
        return lhs <= rhs + tolerance
    if op == ">":
        return lhs > rhs - tolerance
    if op == "<":
        return lhs < rhs + tolerance
    raise UnsupportedExpression(SKIP_UNSUPPORTED_GRAMMAR, f"comparison operator {op!r}")
