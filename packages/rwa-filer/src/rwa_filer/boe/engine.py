"""
The rule engine — Bank of England validation rules over a canonical return.

Pipeline position:
    CanonicalReturn + TaxonomyPack + rules  ->  evaluate_rules
        ->  RuleResult per rule (satisfied / unsatisfied evaluations, failures)

Key responsibilities:
- Evaluate each rule the way the taxonomy's formula is evaluated by the Bank's
  gateway, so that a rule passes or fails here exactly when it would there.
- Count EVALUATIONS, not cells: one rule is run once for every combination of
  cells its references leave open, and each run is satisfied or unsatisfied.
- Never guess. A rule that uses something this engine does not implement is
  reported as not evaluated, with the reason.

How a rule is evaluated

1. *Is it run at all?* A rule is run only when every table it reads is
   reported (a positive filing indicator). Otherwise it is blocked: neither
   satisfied nor unsatisfied.

2. *Which evaluations exist?* Each reference names a table and, optionally,
   rows, columns and sheets. An axis it leaves open — or for which the rule's
   scope lists several codes — is ITERATED: the rule is run once per value,
   and references that share an open axis are read at the same value. A
   ``seq: True`` reference instead takes ALL the cells it lists (and all the
   rows of an open-row table) at once, for a sum or a count. An evaluation
   exists wherever at least one of the rule's cells is reported; a coordinate
   where nothing is reported is not evaluated — unless the rule is marked
   "always execute", which runs it once regardless.

3. *What is an unreported cell?* Whatever the reference's own ``dv`` says:
   zero, false, no member, an empty sequence. A reference with NO ``dv`` cannot
   stand in for an unreported cell, and the evaluation does not happen.

4. *How are numbers compared?* An operator with the ``i`` prefix carries a
   rounding allowance: each fact's is ``10^(-decimals) / 2``, a literal's and a
   default's is zero; sums add allowances, products and quotients propagate
   them. ``a i= b`` holds when ``|a - b|`` is within the two allowances
   together. An operator without the prefix compares the reported values
   exactly.

References:
- Bank of England Banking Taxonomy v4.1.1 — validation workbooks ("Note"
  sheet) and formula linkbases; interval-arithmetics function linkbase v1.1.1
- XBRL Formula 1.0 / Variables 1.0: implicit filtering, fallback values,
  bind-as-sequence
- BoE XBRL Filing Manual v1.0.1, rule 2.18 (interpretation of decimals)
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import polars as pl

from rwa_filer.boe.formulas import DEFAULT_MEMBER
from rwa_filer.boe.grammar import (
    DEFAULT_EMPTY,
    DEFAULT_FALSE,
    DEFAULT_ZERO,
    Binary,
    Call,
    Conditional,
    GrammarError,
    JoinEquality,
    JoinKey,
    Logical,
    Member,
    Negate,
    Number,
    Reference,
    Text,
    references,
)
from rwa_filer.model import DECIMALS_EXACT
from rwa_filer.validate.structure import (
    IS_KEY,
    filing_indicators,
    key_text,
    local_name,
    resolve_datapoints,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.boe.grammar import Default, Node, ScopeGroup
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import Table, TaxonomyPack

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

STATUS_PASS: Final = "PASS"
STATUS_FAIL: Final = "FAIL"
STATUS_NOT_EVALUATED: Final = "NOT_EVALUATED"

#: A table the rule reads is not reported, so the gateway does not run the rule.
REASON_NOT_REPORTED: Final = "template_not_reported"
#: The rule was run and no evaluation took place: none of its cells is reported.
REASON_NO_DATA: Final = "no_data"
#: The rule's cells are reported, but the taxonomy's own formula for the rule
#: cannot bind them: it closes a dimension they carry. The gateway never
#: evaluates such a rule, so neither does the engine.
REASON_CLOSED_BY_FORMULA: Final = "closed_by_formula"
#: The rule reads a table the module's taxonomy pack does not have.
REASON_UNKNOWN_TABLE: Final = "table_not_in_taxonomy"
#: The rule does not parse, or uses something the engine does not implement.
REASON_UNSUPPORTED: Final = "unsupported"

#: Failing evaluations recorded per rule.
MAX_FAILURES: Final = 5

AXIS_ROW: Final = "r"
AXIS_COLUMN: Final = "c"
AXIS_SHEET: Final = "z"
_AXIS_OPEN: Final = "open:"
_AXIS_KEY: Final = "key:"
#: Joins an axis to the variable that ranges over it alone (``c@v1``).
_AXIS_OWN: Final = "@"

#: Every function the engine implements, by lower-cased name and accepted arity.
#: A rule calling anything else is reported as unsupported before it is run.
SUPPORTED_FUNCTIONS: Final[Mapping[str, tuple[int, ...]]] = {
    "true": (0,),
    "false": (0,),
    "eulerconst": (0,),
    "isum": (1,),
    "sum": (1,),
    "iabs": (1,),
    "abs": (1,),
    "imax": (1, 2, 3),
    "max": (1, 2, 3),
    "imin": (1, 2, 3),
    "min": (1, 2, 3),
    "count": (1,),
    "isnull": (1,),
    "not": (1,),
    "matches": (2,),
    "stringlength": (1,),
    "exp": (3,),
    "log": (1, 2),
    "dim": (2,),
}

_NUMERIC_TYPES: Final = frozenset({"monetary", "percentage", "integer", "decimal"})
_TRUE: Final = frozenset({"true", "1"})

#: An evaluation's place: one value for each axis the rule iterates.
_Env = tuple[tuple[str, str], ...]


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class Accuracy:
    """The accuracy facts are stated to where they do not state their own.

    These are the ``decimals`` the XBRL writer will give such facts, so the
    rounding allowances used here are the ones the gateway will use on the
    written file.
    """

    monetary_decimals: int = -3
    percentage_decimals: int = 4


@dataclass(frozen=True)
class Failure:
    """One unsatisfied evaluation: where it was, and what the rule's cells held."""

    place: str
    cells: tuple[str, ...]


@dataclass(frozen=True)
class RuleResult:
    """What evaluating one rule established.

    Attributes:
        rule_id: The rule code.
        severity: ``"ERROR"`` or ``"WARNING"`` for the return's module.
        status: ``PASS`` (evaluated, never unsatisfied), ``FAIL`` (unsatisfied
            at least once) or ``NOT_EVALUATED``.
        reason: Why a rule was not evaluated; empty otherwise.
        detail: Free text expanding on ``reason``.
        satisfied / unsatisfied: Evaluations that held / did not hold.
        failures: Up to ``MAX_FAILURES`` unsatisfied evaluations.
        tables: The tables the rule reads.
    """

    rule_id: str
    severity: str
    status: str
    reason: str = ""
    detail: str = ""
    satisfied: int = 0
    unsatisfied: int = 0
    failures: tuple[Failure, ...] = ()
    tables: tuple[str, ...] = ()

    @property
    def evaluations(self) -> int:
        return self.satisfied + self.unsatisfied


def evaluate_rules(
    ret: CanonicalReturn,
    pack: TaxonomyPack,
    rules: Iterable[Rule],
    *,
    accuracy: Accuracy | None = None,
) -> list[RuleResult]:
    """Evaluate ``rules`` over ``ret``. One result per rule, in the order given.

    Never raises for a condition in the return or in a rule: a rule that cannot
    be evaluated is a result with a reason.
    """
    store = _Store(ret, pack, accuracy or Accuracy())
    module = pack.info.module
    results = [_evaluate_rule(rule, store, module) for rule in rules]
    logger.info(
        "evaluated %d rule(s) for %s: %d failed, %d not evaluated",
        len(results),
        module,
        sum(result.status == STATUS_FAIL for result in results),
        sum(result.status == STATUS_NOT_EVALUATED for result in results),
    )
    return results


# =============================================================================
# Private helpers — the return, indexed for evaluation
# =============================================================================


@dataclass(frozen=True)
class _Amount:
    """A number with its rounding allowance."""

    value: float
    allowance: float = 0.0


#: A cell's key in a table: (sheet code, open-axis member, row, column).
_CellKey = tuple[str | None, str | None, str, str]


@dataclass
class _TableData:
    """One table's reported cells, indexed the ways a reference selects them."""

    table: Table
    cells: dict[_CellKey, object] = field(default_factory=dict)
    #: The data point each reported cell holds. Two cells of one data point —
    #: some figures are shown twice — are ONE fact to the gateway.
    points: dict[_CellKey, int] = field(default_factory=dict)
    by_row_column: dict[tuple[str, str], list[_CellKey]] = field(default_factory=dict)
    by_column: dict[str, list[_CellKey]] = field(default_factory=dict)
    by_row: dict[str, list[_CellKey]] = field(default_factory=dict)
    #: Open-row tables: (sheet, member, row id) -> {key dimension: value}.
    row_keys: dict[tuple[str | None, str | None, str], dict[str, str]] = field(default_factory=dict)
    #: ... and back: (sheet, member, sorted key items) -> row id.
    rows_by_key: dict[tuple[str | None, str | None, tuple[tuple[str, str], ...]], str] = field(
        default_factory=dict
    )
    #: The dimensions each data point carries with a member other than the
    #: default — what a formula that closes a dimension turns away.
    carried: dict[int, frozenset[str]] = field(default_factory=dict)

    def add(self, key: _CellKey, value: object, point: int) -> None:
        self.cells[key] = value
        self.points[key] = point
        _sheet, _member, row, column = key
        self.by_row_column.setdefault((row, column), []).append(key)
        self.by_column.setdefault(column, []).append(key)
        self.by_row.setdefault(row, []).append(key)


class _Store:
    """The return's facts as typed cell values, per table."""

    def __init__(self, ret: CanonicalReturn, pack: TaxonomyPack, accuracy: Accuracy) -> None:
        self.pack = pack
        self.reported = {code for code, filed in filing_indicators(ret, pack).items() if filed}
        self.tables: dict[str, _TableData] = {}
        types = [
            pack.metrics[point.metric].data_type if point.metric in pack.metrics else ""
            for point in pack.datapoints
        ]
        enumerations = [
            pack.enumerations.get(pack.metrics[point.metric].enumeration or "", ())
            if point.metric in pack.metrics
            else ()
            for point in pack.datapoints
        ]
        resolved = resolve_datapoints(ret, pack).with_columns(key_text().alias("_key"))
        keys = resolved.filter(pl.col(IS_KEY))
        data = _shown_in_every_reported_table(
            resolved.filter(~pl.col(IS_KEY) & pl.col("datapoint").is_not_null()),
            pack,
            self.reported,
        )

        for row in keys.iter_rows(named=True):
            table = pack.tables[row["table"]]
            holder = self._data(table)
            dimension = next(
                (key.dimension for key in table.open_keys if key.code == row["column"]), None
            )
            if dimension is None or row["_key"] is None:
                continue
            member = self._member(table, row["open_key"])
            holder.row_keys.setdefault((row["sheet"], member, row["row"]), {})[dimension] = row[
                "_key"
            ]
        for holder in self.tables.values():
            for (sheet, member, row_id), values in holder.row_keys.items():
                holder.rows_by_key[(sheet, member, tuple(sorted(values.items())))] = row_id

        for row in data.iter_rows(named=True):
            table = pack.tables[row["table"]]
            number = row["datapoint"]
            value = _typed(row, types[number], enumerations[number], accuracy)
            if value is None:
                continue
            key = (row["sheet"], self._member(table, row["open_key"]), row["row"], row["column"])
            holder = self._data(table)
            holder.add(key, value, number)
            if number not in holder.carried:
                holder.carried[number] = frozenset(
                    dimension
                    for dimension, member in pack.datapoints[number].dimensions
                    if member.rpartition(":")[2] != DEFAULT_MEMBER
                )

    def data(self, table: str) -> _TableData | None:
        """The table's cells; an empty holder for a table with no reported cell."""
        if table not in self.pack.tables:
            return None
        return self._data(self.pack.tables[table])

    def is_reported(self, table: str) -> bool:
        definition = self.pack.tables.get(table)
        return definition is not None and definition.filing_indicator in self.reported

    def _data(self, table: Table) -> _TableData:
        holder = self.tables.get(table.code)
        if holder is None:
            holder = self.tables[table.code] = _TableData(table)
        return holder

    @staticmethod
    def _member(table: Table, open_key: str | None) -> str | None:
        """An open-axis key as the member's QName."""
        axis = table.open_axis
        if axis is None or open_key is None:
            return None
        if open_key in axis.members:
            return open_key
        return next((m for m in axis.members if local_name(m) == open_key), open_key)


def _shown_in_every_reported_table(
    data: pl.DataFrame, pack: TaxonomyPack, reported: set[str]
) -> pl.DataFrame:
    """``data`` with each fact also in every other reported cell of its data point.

    The taxonomy shows some data points in two tables — the A-IRB total is a row
    of OF 02.00 and the total of an OF 08.01 sheet — and the fact is ONE fact
    wherever it is shown: the gateway's formulas bind to the fact, not to a
    cell. A return read back from its file already names every cell
    (``xbrl.reader``); one built cell by cell may name only the cell its source
    happened to fill, and a rule that reads the other would see nothing there.
    (Measured 2026-11-13: ``boe_b0622`` failed 80,755.66 against a default 0 on
    a return whose file the same engine passed.)

    A cell the return names itself is left as it is — two values for one data
    point is the structure check's finding (``STR007``), not settled here. A
    table that is not reported gains nothing: showing a data point does not
    file a template. Open-row tables are left out, as the structure check
    leaves them out: their rows share a cell and are told apart by their key.
    """
    if data.is_empty():
        return data
    closed = {code: table for code, table in pack.tables.items() if not table.open_rows}
    keyed_by_member = [code for code, table in closed.items() if table.open_axis is not None]
    targets = pack.cells.filter(
        pl.col("table").is_in(
            [code for code, table in closed.items() if table.filing_indicator in reported]
        )
    ).select(
        pl.col("table").alias("_table"),
        pl.col("sheet").alias("_sheet"),
        pl.col("row").alias("_row"),
        pl.col("column").alias("_column"),
        "datapoint",
    )
    address = ["table", "sheet", "open_key", "row", "column"]
    twins = (
        data.filter(pl.col("table").is_in(list(closed)))
        .sort(address, nulls_last=False)
        .unique(subset=["datapoint", "open_key"], keep="first", maintain_order=True)
        .join(targets, on="datapoint", how="inner")
        # An open-axis member places a fact only in a table that has the axis.
        .filter(pl.col("open_key").is_not_null() == pl.col("_table").is_in(keyed_by_member))
        .with_columns(
            pl.col("_table").alias("table"),
            pl.col("_sheet").alias("sheet"),
            pl.col("_row").alias("row"),
            pl.col("_column").alias("column"),
        )
        .select(data.columns)
        .join(data.select(address), on=address, how="anti", nulls_equal=True)
    )
    return pl.concat([data, twins], how="vertical") if twins.height else data


def _typed(
    row: Mapping[str, object], data_type: str, enumeration: Sequence[str], accuracy: Accuracy
) -> object | None:
    """A fact as the value the rule language sees: a number, a boolean or text."""
    if data_type in _NUMERIC_TYPES:
        value = row["value"]
        if not isinstance(value, (int, float)):
            return None
        return _Amount(float(value), _allowance(row["decimals"], data_type, accuracy))
    text = row["text_value"]
    if not isinstance(text, str):
        return None
    if data_type == "boolean":
        return text.strip().lower() in _TRUE
    if data_type == "enumeration" and ":" not in text:
        return next((member for member in enumeration if local_name(member) == text), text)
    return text


def _allowance(decimals: object, data_type: str, accuracy: Accuracy) -> float:
    """``10^(-decimals) / 2`` — zero for a figure stated to be exact."""
    if not isinstance(decimals, int):
        if data_type == "monetary":
            decimals = accuracy.monetary_decimals
        elif data_type == "integer":
            decimals = 0
        else:
            decimals = accuracy.percentage_decimals
    if decimals >= DECIMALS_EXACT:
        return 0.0
    return 10.0 ** (-decimals) / 2.0


# =============================================================================
# Private helpers — one rule
# =============================================================================


class _Unsupported(Exception):  # noqa: N818 - control flow, not an error condition
    """The rule uses something the engine does not implement."""


class _NotBound(Exception):  # noqa: N818 - control flow
    """A reference with no default has no reported cell: no evaluation here."""


@dataclass(frozen=True)
class _Selector:
    """A reference resolved against its table and the rule's scope.

    For each axis: the codes the reference accepts (``None`` for "any"), and
    whether the axis is iterated (in ``free``) or taken as a whole.
    """

    reference: Reference
    data: _TableData
    rows: tuple[str, ...] | None
    columns: tuple[str, ...] | None
    sheets: tuple[str, ...] | None
    member: str | None
    member_excluded: bool
    value_member: str | None
    free: frozenset[str]
    key_axes: Mapping[str, str]
    own_axes: Mapping[str, str]
    closed: frozenset[str]

    @property
    def table(self) -> Table:
        return self.data.table

    def axis(self, kind: str) -> str:
        """The name this selector's ``kind`` axis goes by in an evaluation's place."""
        return self.own_axes.get(kind, kind)


def _evaluate_rule(rule: Rule, store: _Store, module: str) -> RuleResult:
    severity = rule.severity(module)

    def not_evaluated(reason: str, detail: str = "") -> RuleResult:
        return RuleResult(
            rule.rule_id, severity, STATUS_NOT_EVALUATED, reason, detail, tables=rule.tables
        )

    if rule.parse_error is not None:
        return not_evaluated(REASON_UNSUPPORTED, rule.parse_error)
    unknown = [table for table in rule.tables if table not in store.pack.tables]
    if unknown:
        return not_evaluated(REASON_UNKNOWN_TABLE, ", ".join(unknown))
    silent = [table for table in rule.tables if not store.is_reported(table)]
    if silent:
        return not_evaluated(REASON_NOT_REPORTED, ", ".join(silent))

    try:
        evaluation = _Evaluation(rule, store)
        satisfied, failures, unsatisfied = evaluation.run()
    except _Unsupported as unsupported:
        return not_evaluated(REASON_UNSUPPORTED, str(unsupported))
    except GrammarError as error:
        return not_evaluated(REASON_UNSUPPORTED, str(error))

    detail = ""
    if unsatisfied:
        status, reason = STATUS_FAIL, ""
    elif satisfied:
        status, reason = STATUS_PASS, ""
    elif shut := evaluation.shut_out():
        status, reason = STATUS_NOT_EVALUATED, REASON_CLOSED_BY_FORMULA
        detail = (
            "the taxonomy's formula for this rule does not admit the reported cells: "
            f"it closes {', '.join(shut)}, which they carry"
        )
    else:
        status, reason = STATUS_NOT_EVALUATED, REASON_NO_DATA
    return RuleResult(
        rule_id=rule.rule_id,
        severity=severity,
        status=status,
        reason=reason,
        detail=detail,
        satisfied=satisfied,
        unsatisfied=unsatisfied,
        failures=tuple(failures),
        tables=rule.tables,
    )


class _Evaluation:
    """One rule against one return: its selectors, its evaluations, its verdicts."""

    def __init__(self, rule: Rule, store: _Store) -> None:
        self._rule = rule
        self._store = store
        self._aliases = _key_aliases(rule.joins)
        self._selectors: dict[int, _Selector] = {}
        scope = {group.table: group for group in rule.scope_groups}
        trees = [rule.tree, *([rule.where_tree] if rule.where_tree is not None else [])]
        self._references = [ref for tree in trees for ref in references(tree)]
        for item in rule.joins:
            joined = [item.reference] if isinstance(item, JoinKey) else [item.left, item.right]
            self._references.extend(joined)
        # Open-axis dimensions a reference of the rule names a member of. Naming
        # one makes the dimension part of the rule: the formula then filters it
        # on EVERY variable, by the whole member list where the text gives none.
        self._named_dimensions = frozenset(
            reference.dimension_filter.dimension
            for reference in self._references
            if reference.dimension_filter is not None
            and reference.dimension_filter.dimension is not None
        )
        for reference in self._references:
            self._selectors[id(reference)] = self._select(reference, scope)
        for tree in trees:
            _check_functions(tree)

    # -- the evaluations -----------------------------------------------------

    def run(self) -> tuple[int, list[Failure], int]:
        satisfied = unsatisfied = 0
        failures: list[Failure] = []
        seen: set[tuple[object, ...]] = set()
        for env in self._environments():
            values = dict(env)
            facts = self._facts_bound(values)
            # A reference with no default and no reported cell cannot be bound:
            # the evaluation does not exist.
            if facts is None:
                continue
            # Nothing reported here at all: not evaluated, unless the rule is
            # one the gateway runs regardless.
            if not any(facts) and not self._rule.always_execute:
                continue
            # The gateway evaluates over FACTS. Two places that read exactly
            # the same facts — a figure the table shows in two cells — are one
            # evaluation.
            if facts in seen:
                continue
            seen.add(facts)
            try:
                if (
                    self._rule.where_tree is not None
                    and self._value(self._rule.where_tree, values) is not True
                ):
                    continue
                verdict = self._value(self._rule.tree, values)
            except (_NotBound, ZeroDivisionError):
                continue
            if verdict is True:
                satisfied += 1
            else:
                unsatisfied += 1
                if len(failures) < MAX_FAILURES:
                    failures.append(self._failure(values))
        return satisfied, failures, unsatisfied

    def _facts_bound(self, env: Mapping[str, str]) -> tuple[object, ...] | None:
        """The fact(s) each reference reads at ``env``; ``None`` if one cannot be bound.

        Every reference of the rule is bound, whether or not the expression
        would go on to use it — a conditional does not excuse a reference from
        needing its cell. An entry is ``None`` where the reference falls back
        on its default.
        """
        bound: list[object] = []
        for reference in self._references:
            selector = self._selectors[id(reference)]
            if reference.sequence:
                facts = frozenset(
                    self._fact(selector, key)
                    for key in self._matching(selector)
                    if self._at(selector, key, env)
                )
                entry: object = facts or None
            else:
                key = self._cell(selector, env)
                entry = None
                if key is not None and key in selector.data.cells and self._accepts(selector, key):
                    entry = self._fact(selector, key)
            if entry is None and reference.default is None:
                return None
            bound.append(entry)
        return tuple(bound)

    @staticmethod
    def _fact(selector: _Selector, key: _CellKey) -> tuple[object, ...]:
        """What identifies the fact a cell holds: its data point and what fills its open members."""
        sheet, member, row, _column = key
        keys = selector.data.row_keys.get((sheet, member, row))
        return (selector.data.points[key], member, tuple(sorted(keys.items())) if keys else None)

    def _environments(self) -> list[_Env]:
        """Every place the rule is evaluated: the outer join of its references' cells.

        Each reference contributes the places its reported cells sit at, over
        the axes it iterates. References sharing an axis are read at the same
        value; a reference with nothing reported at a place falls back there.
        """
        environments: set[_Env] = set()
        for reference in references(self._rule.tree):
            selector = self._selectors[id(reference)]
            partial: set[_Env] = {
                place
                for key in self._matching(selector)
                if (place := self._place(selector, key)) is not None
            }
            if not partial:
                continue
            if not environments:
                environments = partial
                continue
            merged: set[_Env] = set()
            used: set[_Env] = set()
            for env in environments:
                hit = False
                for place in partial:
                    joined = _join(env, place)
                    if joined is not None:
                        merged.add(joined)
                        used.add(place)
                        hit = True
                if not hit:
                    merged.add(env)
            merged.update(partial - used)
            environments = _maximal(merged)
        if not environments and self._rule.always_execute:
            return [()]
        return sorted(environments)

    def _place(self, selector: _Selector, key: _CellKey) -> _Env | None:
        """The place a reported cell sits at, over the axes ``selector`` iterates."""
        sheet, member, row, column = key
        place: dict[str, str] = {}
        for axis in selector.free:
            if axis == selector.axis(AXIS_ROW):
                place[axis] = row
            elif axis == selector.axis(AXIS_COLUMN):
                place[axis] = column
            elif axis == selector.axis(AXIS_SHEET):
                if sheet is None:
                    return None
                place[axis] = sheet
            elif axis.startswith(_AXIS_OPEN):
                if member is None:
                    continue
                place[axis] = member
            else:
                dimension = selector.key_axes[axis]
                value = selector.data.row_keys.get((sheet, member, row), {}).get(dimension)
                if value is None:
                    return None
                place[axis] = value
        return tuple(sorted(place.items()))

    # -- selecting cells -----------------------------------------------------

    def _select(self, reference: Reference, scope: Mapping[str, ScopeGroup]) -> _Selector:
        if reference.key_dimension is not None or reference.table is None:
            raise _Unsupported("a reference to a dimension rather than a cell")
        data = self._store.data(reference.table)
        if data is None:
            raise _Unsupported(f"table {reference.table} is not in the taxonomy pack")
        table = data.table
        group = scope.get(table.code)
        free: set[str] = set()
        own_axes: dict[str, str] = {}

        def axis(
            given: tuple[str, ...],
            scoped: tuple[str, ...],
            name: str,
            written: Callable[[str], str],
        ) -> tuple[str, ...] | None:
            """The codes accepted on one axis; marks the axis iterated where it is.

            Codes are taken as the table itself writes them (``written``): a
            rule may write ``010`` for a table whose codes are ``0010``.
            """
            if given:
                if len(given) > 1 and not reference.sequence:
                    # Codes listed in the reference itself are that VARIABLE's
                    # own range: the formula filters them on the variable, so
                    # nothing lines them up with another variable's. Two
                    # variables listing the same four columns are read in all
                    # sixteen pairs, and one falls back only where none of its
                    # cells is reported. (Codes listed in the SCOPE are shared.)
                    own = f"{name}{_AXIS_OWN}{reference.variable}" if reference.variable else name
                    own_axes[name] = own
                    free.add(own)
                return tuple(written(code) for code in given)
            # An axis the reference leaves to the scope, or leaves open
            # altogether, is run one value at a time.
            free.add(name)
            return tuple(written(code) for code in scoped) or None

        rows = None
        if not table.open_rows:
            rows = axis(reference.rows, group.rows if group else (), AXIS_ROW, table.row_code)
        columns = axis(
            reference.columns, group.columns if group else (), AXIS_COLUMN, table.column_code
        )
        sheets = None
        if table.fixed_axis is not None:
            sheets = axis(
                reference.sheets, group.sheets if group else (), AXIS_SHEET, table.sheet_code
            )

        member, excluded, value_member = None, False, None
        filtered = reference.dimension_filter
        open_axis = table.open_axis
        if filtered is not None and filtered.dimension is None:
            value_member = filtered.member
        elif filtered is not None:
            if open_axis is None or open_axis.dimension != filtered.dimension:
                raise _Unsupported(
                    f"a filter on {filtered.dimension}, which is not {table.code}'s open axis"
                )
            member, excluded = filtered.member, filtered.negated
        if open_axis is not None and (member is None or excluded):
            shared = f"{_AXIS_OPEN}{open_axis.dimension}"
            if open_axis.dimension not in self._named_dimensions:
                # The rule never mentions the dimension: every reference is read
                # at the same member, one member at a time.
                free.add(shared)
            elif not reference.sequence:
                # The rule names a member elsewhere, so this reference ranges
                # over the members by itself, lined up with no other's.
                own = f"{shared}{_AXIS_OWN}{reference.variable}" if reference.variable else shared
                own_axes[shared] = own
                free.add(own)
            # ... and a sequence reference takes every member at once: the
            # axis is not iterated at all. ("The sum over all countries less
            # the total equals the total" — the Bank's ``boe_b0904``.)

        key_axes: dict[str, str] = {}
        if table.open_rows and not reference.sequence:
            for key in table.open_keys:
                name = f"{_AXIS_KEY}{self._aliases.get((table.code, key.dimension), key.dimension)}"
                key_axes[name] = key.dimension
                free.add(name)
        return _Selector(
            reference=reference,
            data=data,
            rows=rows,
            columns=columns,
            sheets=sheets,
            member=member,
            member_excluded=excluded,
            value_member=value_member,
            free=frozenset(free),
            key_axes=key_axes,
            own_axes=own_axes,
            closed=self._rule.closed
            | self._rule.closed_by_variable.get(reference.variable or "", frozenset()),
        )

    def _matching(self, selector: _Selector) -> list[_CellKey]:
        """The reported cells ``selector`` accepts, whatever the place."""
        return [key for key in self._candidates(selector) if self._accepts(selector, key)]

    @staticmethod
    def _candidates(selector: _Selector) -> list[_CellKey]:
        """The reported cells on the rows and columns ``selector`` names."""
        data = selector.data
        if selector.rows is not None and selector.columns is not None:
            return [
                key
                for row in selector.rows
                for column in selector.columns
                for key in data.by_row_column.get((row, column), ())
            ]
        if selector.columns is not None:
            return [key for column in selector.columns for key in data.by_column.get(column, ())]
        if selector.rows is not None:
            return [key for row in selector.rows for key in data.by_row.get(row, ())]
        return list(data.cells)

    @staticmethod
    def _accepts(selector: _Selector, key: _CellKey) -> bool:
        return _Evaluation._names(selector, key) and not _Evaluation._shut_out(selector, key)

    @staticmethod
    def _names(selector: _Selector, key: _CellKey) -> bool:
        """Whether the rule TEXT names the cell: its sheet, member and value."""
        sheet, member, _row, _column = key
        if selector.sheets is not None and sheet not in selector.sheets:
            return False
        if selector.member is not None and (member == selector.member) == selector.member_excluded:
            return False
        if selector.value_member is not None:
            return selector.data.cells.get(key) == selector.value_member
        return True

    @staticmethod
    def _shut_out(selector: _Selector, key: _CellKey) -> frozenset[str]:
        """The dimensions on which the rule's FORMULA turns the cell's fact away.

        The formula is what the gateway runs. Where it closes a dimension the
        cell's data point carries, the fact cannot bind there, and the cell is
        not reported as far as this reference is concerned.
        """
        if not selector.closed:
            return frozenset()
        point = selector.data.points.get(key)
        if point is None:
            return frozenset()
        return selector.closed & selector.data.carried.get(point, frozenset())

    def shut_out(self) -> tuple[str, ...]:
        """Every dimension on which the formula turned away a cell the text names, sorted."""
        dimensions: set[str] = set()
        for selector in self._selectors.values():
            if not selector.closed:
                continue
            for key in self._candidates(selector):
                if self._names(selector, key):
                    dimensions |= self._shut_out(selector, key)
        return tuple(sorted(dimensions))

    # -- reading references --------------------------------------------------

    def _read(self, reference: Reference, env: Mapping[str, str]) -> object:
        selector = self._selectors[id(reference)]
        if reference.sequence:
            values = [
                selector.data.cells[key]
                for key in self._matching(selector)
                if self._at(selector, key, env)
            ]
            if values:
                return values
            if reference.default is None:
                raise _NotBound
            return [] if reference.default.kind == DEFAULT_EMPTY else [_default(reference.default)]

        key = self._cell(selector, env)
        if key is not None and key in selector.data.cells and self._accepts(selector, key):
            return selector.data.cells[key]
        if reference.default is None:
            raise _NotBound
        return _default(reference.default)

    def _at(self, selector: _Selector, key: _CellKey, env: Mapping[str, str]) -> bool:
        """Whether a cell sits at ``env`` on every axis the selector iterates."""
        place = self._place(selector, key)
        return place is not None and all(env.get(axis) == value for axis, value in place)

    def _cell(self, selector: _Selector, env: Mapping[str, str]) -> _CellKey | None:
        """The one cell a non-sequence reference reads at ``env``; ``None`` if it has none."""
        table = selector.table

        def coordinate(kind: str, accepted: tuple[str, ...] | None) -> str | None:
            axis = selector.axis(kind)
            if axis in selector.free:
                value = env.get(axis)
                return value if accepted is None or value in accepted else None
            return accepted[0] if accepted else None

        column = coordinate(AXIS_COLUMN, selector.columns)
        if column is None:
            return None
        sheet = None
        if table.fixed_axis is not None:
            sheet = coordinate(AXIS_SHEET, selector.sheets)
            if sheet is None:
                return None
        member = selector.member if not selector.member_excluded else None
        open_axis = table.open_axis
        if open_axis is not None and (selector.member is None or selector.member_excluded):
            member = env.get(selector.axis(f"{_AXIS_OPEN}{open_axis.dimension}"))
        if not table.open_rows:
            row = coordinate(AXIS_ROW, selector.rows)
            return None if row is None else (sheet, member, row, column)
        wanted = {dimension: env.get(axis) for axis, dimension in selector.key_axes.items()}
        if any(value is None for value in wanted.values()):
            return None
        row_id = selector.data.rows_by_key.get((sheet, member, tuple(sorted(wanted.items()))))  # type: ignore[arg-type]
        return None if row_id is None else (sheet, member, row_id, column)

    # -- the expression ------------------------------------------------------

    def _value(self, node: Node, env: Mapping[str, str]) -> object:  # noqa: C901, PLR0911, PLR0912
        if isinstance(node, Number):
            return _Amount(node.value)
        if isinstance(node, Text):
            return node.value
        if isinstance(node, Member):
            return node.qname
        if isinstance(node, Reference):
            return self._read(node, env)
        if isinstance(node, Negate):
            operand = _amount(self._value(node.operand, env))
            return None if operand is None else _Amount(-operand.value, operand.allowance)
        if isinstance(node, Logical):
            if node.operator == "and":
                return all(self._value(operand, env) is True for operand in node.operands)
            return any(self._value(operand, env) is True for operand in node.operands)
        if isinstance(node, Conditional):
            if self._value(node.condition, env) is True:
                return self._value(node.then, env)
            return True if node.otherwise is None else self._value(node.otherwise, env)
        if isinstance(node, Binary):
            left, right = self._value(node.left, env), self._value(node.right, env)
            if node.is_comparison:
                return _compare(node.operator, left, right, node.interval)
            return _arithmetic(node.operator, _amount(left), _amount(right), node.interval)
        if isinstance(node, Call):
            return self._call(node, env)
        raise _Unsupported(f"{type(node).__name__} in an expression")

    def _call(self, node: Call, env: Mapping[str, str]) -> object:  # noqa: C901, PLR0911, PLR0912
        name, arguments = node.name, node.arguments
        if name == "true":
            return True
        if name == "false":
            return False
        if name == "eulerconst":
            return _Amount(math.e)
        if name == "dim":
            return self._dimension_of(arguments, env)
        values = [self._value(argument, env) for argument in arguments]
        if name in ("isum", "sum"):
            items = [_amount(item) for item in _sequence(values[0])]
            present = [item for item in items if item is not None]
            return _Amount(
                math.fsum(item.value for item in present),
                math.fsum(item.allowance for item in present),
            )
        if name in ("iabs", "abs"):
            operand = _amount(values[0])
            return None if operand is None else _Amount(abs(operand.value), operand.allowance)
        if name in ("imax", "max", "imin", "min"):
            items = [
                item
                for value in values
                for raw in _sequence(value)
                if (item := _amount(raw)) is not None
            ]
            if not items:
                return None
            pick = max if name in ("imax", "max") else min
            return pick(items, key=lambda item: item.value)
        if name == "count":
            return _Amount(float(len(_sequence(values[0]))))
        if name == "isnull":
            return _is_empty(values[0])
        if name == "not":
            return values[0] is not True
        if name == "matches":
            subject, pattern = values
            if not isinstance(subject, str) or not isinstance(pattern, str):
                return False
            return re.search(pattern, subject) is not None
        if name == "stringlength":
            return _Amount(float(len(values[0]) if isinstance(values[0], str) else 0))
        if name == "exp":
            base, numerator, denominator = (_amount(value) for value in values)
            if base is None or numerator is None or denominator is None:
                return None
            return _Amount(base.value ** (numerator.value / denominator.value))
        if name == "log":
            operand = _amount(values[0])
            return (
                None if operand is None or operand.value <= 0 else _Amount(math.log(operand.value))
            )
        raise _Unsupported(f"function {name}()")

    def _dimension_of(self, arguments: tuple[Node, ...], env: Mapping[str, str]) -> object:
        """``dim({cell}, [D])`` — the key the cell's row, or sheet, is reported under."""
        if len(arguments) != 2 or not isinstance(arguments[0], Reference):  # noqa: PLR2004
            raise _Unsupported("dim() of something other than a cell")
        if not isinstance(arguments[1], Member):
            raise _Unsupported("dim() without a dimension")
        reference, dimension = arguments[0], arguments[1].qname
        selector = self._selectors[id(reference)]
        key = self._cell(selector, env)
        if key is None or key not in selector.data.cells:
            if reference.default is None:
                raise _NotBound
            return None
        sheet, member, row, _column = key
        open_axis = selector.table.open_axis
        if open_axis is not None and open_axis.dimension == dimension:
            return member
        return selector.data.row_keys.get((sheet, member, row), {}).get(dimension)

    # -- reporting -----------------------------------------------------------

    def _failure(self, env: Mapping[str, str]) -> Failure:
        cells: list[str] = []
        seen: set[int] = set()
        for reference in references(self._rule.tree):
            if id(reference) in seen:
                continue
            seen.add(id(reference))
            selector = self._selectors[id(reference)]
            label = _describe(reference)
            if reference.sequence:
                values = [
                    selector.data.cells[key]
                    for key in self._matching(selector)
                    if self._at(selector, key, env)
                ]
                amounts = [item.value for value in values if (item := _amount(value)) is not None]
                cells.append(f"{label} = {len(values)} cell(s), sum {_number(math.fsum(amounts))}")
                continue
            key = self._cell(selector, env)
            if key is not None and key in selector.data.cells:
                cells.append(f"{label} = {_show(selector.data.cells[key])}")
            else:
                cells.append(f"{label} not reported")
        place = ", ".join(
            f"{_axis_label(axis)} {local_name(value)}" for axis, value in sorted(env.items())
        )
        return Failure(place=place, cells=tuple(cells[:8]))


# =============================================================================
# Private helpers — places
# =============================================================================


def _check_functions(node: Node) -> None:
    """Refuse, before anything is run, a call to a function the engine lacks."""
    if isinstance(node, Call):
        arities = SUPPORTED_FUNCTIONS.get(node.name)
        if arities is None:
            raise _Unsupported(f"function {node.name}()")
        if len(node.arguments) not in arities:
            raise _Unsupported(f"{node.name}() with {len(node.arguments)} argument(s)")
        for argument in node.arguments:
            _check_functions(argument)
    elif isinstance(node, Negate):
        _check_functions(node.operand)
    elif isinstance(node, Binary):
        _check_functions(node.left)
        _check_functions(node.right)
    elif isinstance(node, Logical):
        for operand in node.operands:
            _check_functions(operand)
    elif isinstance(node, Conditional):
        _check_functions(node.condition)
        _check_functions(node.then)
        if node.otherwise is not None:
            _check_functions(node.otherwise)


def _join(env: _Env, place: _Env) -> _Env | None:
    """``env`` extended with ``place``; ``None`` where they disagree on an axis."""
    merged = dict(env)
    for axis, value in place:
        if merged.setdefault(axis, value) != value:
            return None
    return tuple(sorted(merged.items()))


def _maximal(environments: set[_Env]) -> set[_Env]:
    """Drop any place that another place extends: the fuller one is the evaluation."""
    if len({len(env) for env in environments}) <= 1:
        return environments
    kept: set[_Env] = set()
    as_sets = sorted((set(env) for env in environments), key=len, reverse=True)
    fuller: list[set[tuple[str, str]]] = []
    for candidate in as_sets:
        if not any(candidate < other for other in fuller):
            kept.add(tuple(sorted(candidate)))
        fuller.append(candidate)
    return kept


def _key_aliases(joins: Sequence[JoinKey | JoinEquality]) -> dict[tuple[str, str], str]:
    """Row-key dimensions a join declares equal, each mapped to one shared name."""
    aliases: dict[tuple[str, str], str] = {}
    for item in joins:
        if not isinstance(item, JoinEquality):
            continue
        if item.left.table is None or item.right.table is None:
            continue
        shared = min(item.left_dimension, item.right_dimension)
        aliases[(item.left.table, item.left_dimension)] = shared
        aliases[(item.right.table, item.right_dimension)] = shared
    return aliases


# =============================================================================
# Private helpers — values
# =============================================================================


def _default(default: Default) -> object:
    if default.kind == DEFAULT_ZERO:
        return _Amount(0.0)
    if default.kind == DEFAULT_EMPTY:
        return None
    if default.kind == DEFAULT_FALSE:
        return False
    return default.value or ""


def _sequence(value: object) -> list[object]:
    if isinstance(value, list):
        return list(value)
    return [] if value is None else [value]


def _is_empty(value: object) -> bool:
    return value is None or (isinstance(value, list) and not value)


def _amount(value: object) -> _Amount | None:
    """A value as a number; ``None`` for an empty or non-numeric one."""
    if isinstance(value, _Amount):
        return value
    if isinstance(value, list):
        return _amount(value[0]) if len(value) == 1 else None
    return None


def _arithmetic(
    operator: str, left: _Amount | None, right: _Amount | None, interval: bool
) -> object:
    """``+ - * /`` — with the ``i`` prefix the rounding allowances are propagated."""
    if left is None or right is None:
        return None
    a, b = left.value, right.value
    da, db = (left.allowance, right.allowance) if interval else (0.0, 0.0)
    if operator == "+":
        return _Amount(a + b, da + db)
    if operator == "-":
        return _Amount(a - b, da + db)
    if operator == "*":
        return _Amount(a * b, abs(a * db) + abs(b * da) + da * db)
    if b == 0:
        raise ZeroDivisionError
    quotient = a / b
    if not interval or (da == 0 and db == 0):
        return _Amount(quotient)
    corners = [
        (a + sa * da) / (b + sb * db) for sa in (-1, 1) for sb in (-1, 1) if b + sb * db != 0
    ]
    return _Amount(quotient, max((abs(corner - quotient) for corner in corners), default=0.0))


def _compare(operator: str, left: object, right: object, interval: bool) -> bool:  # noqa: PLR0911
    """A comparison. With the ``i`` prefix it allows for both operands' rounding."""
    if isinstance(left, list):
        left = left[0] if len(left) == 1 else None
    if isinstance(right, list):
        right = right[0] if len(right) == 1 else None
    if left is None or right is None:
        return False
    if isinstance(left, _Amount) and isinstance(right, _Amount):
        difference = left.value - right.value
        allowance = left.allowance + right.allowance if interval else 0.0
        if operator == "=":
            return abs(difference) <= allowance
        if operator == "!=":
            return abs(difference) > allowance
        if operator == "<=":
            return difference <= allowance
        if operator == "<":
            return difference < allowance
        if operator == ">=":
            return difference >= -allowance
        return difference > -allowance
    if isinstance(left, _Amount) or isinstance(right, _Amount):
        return operator == "!="
    if operator == "=":
        return left == right
    if operator == "!=":
        return left != right
    if isinstance(left, str) and isinstance(right, str):
        # Dates are held in ISO form, which orders as the dates do.
        if operator == "<=":
            return left <= right
        if operator == "<":
            return left < right
        if operator == ">=":
            return left >= right
        return left > right
    return False


def _describe(reference: Reference) -> str:
    parts = [reference.table or "?"]
    for prefix, codes in (("r", reference.rows), ("c", reference.columns), ("z", reference.sheets)):
        if codes:
            shown = ";".join(codes[:3]) + (";.." if len(codes) > 3 else "")  # noqa: PLR2004
            parts.append(f"{prefix}{shown}")
    return " ".join(parts)


def _axis_label(axis: str) -> str:
    kind, _, variable = axis.partition(_AXIS_OWN)
    names = {AXIS_ROW: "row", AXIS_COLUMN: "column", AXIS_SHEET: "sheet"}
    name = names.get(kind) or local_name(kind.split(":", 1)[1])
    return f"{name} of {variable}" if variable else name


def _show(value: object) -> str:
    return _number(value.value) if isinstance(value, _Amount) else str(value)


def _number(value: float) -> str:
    return f"{value:,.6f}".rstrip("0").rstrip(".")
