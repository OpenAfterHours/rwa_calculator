"""
The rule engine — Bank of England validation rules over a canonical return.

Pipeline position:
    CanonicalReturn + TaxonomyPack + rules  ->  evaluate_rules
        ->  RuleResult per rule (satisfied / unsatisfied evaluations, failures)
    the same  ->  trace_rules  ->  RuleTrace (the results, and every evaluation
        with the cells each side of the rule read — what a comparison of two
        returns points at)

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
   ``seq: True`` reference instead takes ALL the cells it lists at once, for a
   sum or a count — and of an open-row table's rows, or an open sheet axis's
   members, all those its formula's variable COVERS (``spans_by_variable``).
   A row or member it leaves uncovered is iterated and lined up with the rest
   of the rule, as for a single cell; the text alone cannot tell the two
   apart, and is read only where the rule book does not say. An evaluation
   exists wherever at least one of the rule's cells is reported; a coordinate
   where nothing is reported is not evaluated — unless the rule is marked
   "always execute", which runs it once regardless.

3. *What is an unreported cell?* Whatever the reference's own ``dv`` says:
   zero, false, no member, an empty sequence. A reference with NO ``dv`` cannot
   stand in for an unreported cell, and the evaluation does not happen.

4. *How are numbers compared?* An operator with the ``i`` prefix carries a
   rounding allowance: each fact's is ``10^(-decimals) / 2``, a literal's and a
   default's is zero; ``isum`` and ``i+`` add allowances, products and
   quotients propagate them. ``a i= b`` holds when ``|a - b|`` is within the
   two allowances together. An operator without the prefix compares the
   reported values exactly. ``sum`` and ``abs`` without it are XPath's, and
   their result is a plain number with NO allowance: ``sum(...)`` allows
   nothing for the facts it adds, where ``isum(...)`` allows each one's, and
   ``abs`` likewise against ``iabs`` — measured against Arelle on the Bank's
   ``boe_b0770``, ``boe_b0794`` and their siblings. Plain ``max`` and ``min``
   are not measured, because no packaged rule calls them; they are read as
   ``imax`` and ``imin`` are, and the chosen fact keeps its allowance.

5. *Where is a fact with no member on an open sheet axis?* At the dimension's
   default member. On an axis that accepts the default (OF 08.06's "all types"
   sheet) that is a sheet like any other: the rule is evaluated there once,
   and the sheet's cells are not read into any other member's evaluation.

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
from rwa_filer.progress import PHASE_RULES, Progress, notify
from rwa_filer.validate.structure import (
    IS_KEY,
    filing_indicators,
    key_text,
    local_name,
    resolve_datapoints,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence

    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.boe.deny import DenyEntry
    from rwa_filer.boe.grammar import Default, Node, ScopeGroup
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.progress import ProgressCallback
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
#: The Bank has deactivated the rule at its gateway (its validations deny list,
#: ``boe.deny``): the gateway does not run it, so a reporter is not expected to
#: meet it. Never set by the engine itself — ``validate.execution`` sets it after
#: evaluation, keeping what the taxonomy's formula found on ``RuleResult.formula``.
#: Like ``closed_by_formula``, it is not a gap in the check.
REASON_DEACTIVATED_BY_PUBLISHER: Final = "deactivated_by_publisher"

#: Where the ``decimals`` a numeric fact is compared at came from: the fact's
#: own, the run's ``Accuracy`` for its data type, or an integer's unit.
DECIMALS_STATED: Final = "stated"
DECIMALS_ACCURACY: Final = "accuracy"
DECIMALS_INTEGER: Final = "integer"

#: Failing evaluations recorded per rule, by default: enough for a report to
#: show where a rule breaks. A viewer marking every broken cell on a template
#: asks for them all (``max_failures=None``).
MAX_FAILURES: Final = 5
#: Cell addresses recorded per failing evaluation. A summed sequence can read
#: hundreds of cells; a viewer marking them needs the first screenful, not all.
MAX_ADDRESSES: Final = 64

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
class CellAddress:
    """One cell an unsatisfied evaluation read, in the publisher's coordinates.

    Attributes:
        table: The table code.
        sheet: The fixed-axis sheet code, or ``None`` for a table without one.
        open_key: The open-axis member's local name, or ``None``.
        row: The row code.
        column: The column code.
        reported: ``False`` for a cell the rule read at its default because the
            return leaves it empty — often the cell the break is really about.
    """

    table: str
    sheet: str | None
    open_key: str | None
    row: str
    column: str
    reported: bool = True


@dataclass(frozen=True)
class Failure:
    """One unsatisfied evaluation: where it was, and what the rule's cells held.

    ``cells`` describes the cells in words, for a report; ``addresses`` locates
    them, up to ``MAX_ADDRESSES``, for anything that marks them on a template.
    """

    place: str
    cells: tuple[str, ...]
    addresses: tuple[CellAddress, ...] = ()


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
        failures: The first unsatisfied evaluations, in place order — up to
            ``MAX_FAILURES`` unless the caller asked for another limit.
        tables: The tables the rule reads.
        deny: The Bank's deny-list entry that changed how the gateway runs the
            rule, where one is in force (``validate.execution``); ``None``
            otherwise. The engine never sets it.
        formula: The result as the taxonomy's formula has it, where ``deny``
            changed it — the verdict an XBRL processor running the formula
            reaches, which is what the referee compares; ``None`` otherwise.
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
    deny: DenyEntry | None = None
    formula: RuleResult | None = None

    @property
    def evaluations(self) -> int:
        return self.satisfied + self.unsatisfied


def evaluate_rules(  # noqa: PLR0913 - the return, its rules, and how to report them
    ret: CanonicalReturn,
    pack: TaxonomyPack,
    rules: Iterable[Rule],
    *,
    accuracy: Accuracy | None = None,
    progress: ProgressCallback | None = None,
    max_failures: int | None = MAX_FAILURES,
) -> list[RuleResult]:
    """Evaluate ``rules`` over ``ret``. One result per rule, in the order given.

    Never raises for a condition in the return or in a rule: a rule that cannot
    be evaluated is a result with a reason. ``progress``, when given, hears how
    many of the rules are done: once before the first, then after each one.
    ``max_failures`` is how many unsatisfied evaluations each result records,
    the first in place order; ``None`` records every one. Every one is counted
    either way.
    """
    store = _Store(ret, pack, accuracy or Accuracy())
    return _evaluate_indexed(store, rules, progress=progress, max_failures=max_failures)


@dataclass(frozen=True)
class Evaluation:
    """One evaluation of one rule: where it was made, what it read, whether it held.

    Attributes:
        rule_id: The rule code.
        place: The evaluation's place — one value per axis the rule iterates —
            as ``(axis, value)`` pairs. The same rule at the same place in two
            returns is the same check, which is how a comparison pairs them.
        holds: Whether the evaluation was satisfied.
        relation: The comparison at the top of the rule (``=``, ``<=``, ...);
            ``None`` for a rule that is not one comparison.
        left / right: The cells each side of that comparison read, in rule
            order, a cell read at its default marked ``reported=False``. A rule
            that is not one comparison has every cell on the left.
        left_value / right_value: Each side's number, where it is one; ``None``
            otherwise. Their difference is how far a broken equality is out.
        comparisons: Every comparison the evaluation executed, in the order the
            engine executed it — with each operand's value and allowance, the
            cells it read and the cells it read at their default. ``and`` /
            ``or`` stop at the first operand that decides them, and a
            conditional runs one branch, so a comparison never reached is not
            here.
    """

    rule_id: str
    place: tuple[tuple[str, str], ...]
    holds: bool
    relation: str | None
    left: tuple[CellAddress, ...]
    right: tuple[CellAddress, ...] = ()
    left_value: float | None = None
    right_value: float | None = None
    comparisons: tuple[Comparison, ...] = ()

    @property
    def cells(self) -> frozenset[CellAddress]:
        """Every cell the evaluation read: each side's, and each comparison's operands'."""
        found = {*self.left, *self.right}
        for comparison in self.comparisons:
            found.update(comparison.left.cells)
            found.update(comparison.right.cells)
        return frozenset(found)


@dataclass(frozen=True)
class RuleTrace:
    """``evaluate_rules``'s results, with every evaluation behind them.

    ``cells`` holds every reported cell an evaluation read, once, with the
    accuracy its comparisons allowed for.
    """

    results: tuple[RuleResult, ...]
    evaluations: tuple[Evaluation, ...]
    cells: Mapping[CellAddress, CellFact] = field(default_factory=dict)


def trace_rules(  # noqa: PLR0913 - evaluate_rules's arguments
    ret: CanonicalReturn,
    pack: TaxonomyPack,
    rules: Iterable[Rule],
    *,
    accuracy: Accuracy | None = None,
    progress: ProgressCallback | None = None,
    max_failures: int | None = MAX_FAILURES,
) -> RuleTrace:
    """Evaluate ``rules`` as ``evaluate_rules`` does, keeping every evaluation.

    The results are exactly ``evaluate_rules``'s. Each evaluation the engine
    made — satisfied or not, unlike ``RuleResult.failures``, which keeps the
    first ``max_failures`` unsatisfied ones — is kept with every cell it read,
    uncapped. ``progress`` hears how many rules are done, as for
    ``evaluate_rules``.
    """
    store = _Store(ret, pack, accuracy or Accuracy())
    return _trace_indexed(store, rules, progress=progress, max_failures=max_failures)


@dataclass(frozen=True)
class DefaultedCell:
    """A cell a reference read at its default, because the return leaves it empty.

    Attributes:
        reference: The reference as the rule writes it, e.g. ``C01.00.01.01 r0080 c0010``.
        default: The kind of default (``zero``, ``false``, ``empty``, ``member``,
            ``string``, ``date``) — the reference's ``dv``.
        default_value: The member, text or date for a default that names one.
        address: The cell, where the reference names exactly one; ``None`` for
            a sequence, which has no cell to name when it is empty.
    """

    reference: str
    default: str
    default_value: str | None = None
    address: CellAddress | None = None


@dataclass(frozen=True)
class Operand:
    """One side of a comparison, as the engine compared it.

    Attributes:
        value: The side's value — a number, text or a boolean; ``None`` where
            it has none (an empty sequence, or one of several values).
        allowance: Its rounding allowance as the engine propagated it: a
            fact's ``10^(-decimals) / 2``, summed over ``i+``, and so on. Zero
            for a literal, a default, or arithmetic without the ``i`` prefix.
        cells: The reported cells it read.
        defaulted: The cells it read at their default.
    """

    value: float | str | bool | None
    allowance: float
    cells: tuple[CellAddress, ...] = ()
    defaulted: tuple[DefaultedCell, ...] = ()


@dataclass(frozen=True)
class Comparison:
    """One comparison an evaluation executed, and why it held or did not.

    With numbers on both sides, ``difference`` is ``left - right`` and
    ``tolerance`` is what the comparison allowed for: both operands'
    allowances with the ``i`` prefix, zero without it. Then ``=`` holds iff
    ``|difference| <= tolerance``; ``!=`` iff ``|difference| > tolerance``;
    ``<=`` iff ``difference <= tolerance``; ``<`` iff ``difference < tolerance``;
    ``>=`` iff ``difference >= -tolerance``; ``>`` iff ``difference > -tolerance``.
    Equivalently: each side is the interval ``value +/- allowance``, and ``i=``
    holds when the two overlap.

    Attributes:
        operator: ``=``, ``!=``, ``<=``, ``<``, ``>=`` or ``>``.
        interval: The ``i`` prefix.
        left / right: The two operands.
        difference: ``left - right`` where both are numbers; ``None`` otherwise.
        tolerance: See above; zero where the operands are not both numbers.
        excess: How far the difference is beyond the bound the operator sets
            — zero when it holds, and zero for a strict comparison that fails
            exactly on its bound. ``None`` for ``!=`` and for non-numbers.
        holds: Whether the comparison held.
        branch: Where in the rule it was executed: ``rule`` or ``where``, then
            ``if`` / ``then`` / ``else`` for each conditional entered, joined
            by ``/`` (``rule/then``).
    """

    operator: str
    interval: bool
    left: Operand
    right: Operand
    difference: float | None
    tolerance: float
    excess: float | None
    holds: bool
    branch: str


@dataclass(frozen=True)
class CellFact:
    """A reported cell an evaluation read, and the accuracy it was compared at.

    Attributes:
        address: The cell.
        datapoint: The index of the data point it reports, in the pack.
        metric: The data point's metric.
        data_type: The metric's DPM type.
        value: What the rule language read: a number, text or a boolean.
        decimals: The ``decimals`` a numeric fact was compared at; ``None``
            for a fact that is not a number.
        decimals_source: ``stated``, ``accuracy`` or ``integer`` (see the
            ``DECIMALS_*`` constants); empty for a fact that is not a number.
        allowance: ``10^(-decimals) / 2``, or zero for a figure stated exact.
    """

    address: CellAddress
    datapoint: int
    metric: str
    data_type: str
    value: float | str | bool | None
    decimals: int | None
    decimals_source: str
    allowance: float


def effective_decimals(decimals: object, data_type: str, accuracy: Accuracy) -> tuple[int, str]:
    """The ``decimals`` a numeric fact is compared at, and where it came from.

    A fact that states its own is compared at that. One that does not takes the
    run's ``accuracy`` for its type; an integer is exact to the unit. THE one
    implementation: the rounding allowance and a report of it both read this.
    """
    if isinstance(decimals, int):
        return decimals, DECIMALS_STATED
    if data_type == "monetary":
        return accuracy.monetary_decimals, DECIMALS_ACCURACY
    if data_type == "integer":
        return 0, DECIMALS_INTEGER
    return accuracy.percentage_decimals, DECIMALS_ACCURACY


# =============================================================================
# Private helpers — a return already indexed
# =============================================================================


def _evaluate_indexed(
    store: _Store,
    rules: Iterable[Rule],
    *,
    progress: ProgressCallback | None = None,
    max_failures: int | None = MAX_FAILURES,
) -> list[RuleResult]:
    """``evaluate_rules`` over a return that is already indexed (``store``).

    For a caller inside the package that runs more than one pass over one
    return — a validation's rule pass, then its publisher-issue pass — and
    would otherwise index the return once per pass. Not for callers outside it:
    nothing here checks that ``store`` is the return, the pack and the accuracy
    the caller means, and a wrong one gives a wrong verdict silently.

    Sharing one store between passes is sound because evaluating writes nothing
    to it but an empty holder for a table with no reported cell, and tracing
    nothing but a reported cell's address (``_TableData.addresses``) — each what
    the next pass would have made, from the cell alone; everything worked out
    per rule is kept on that rule's ``_Evaluation``, and what a trace collects
    on the trace.
    """
    module = store.pack.info.module
    results = [
        _evaluate_rule(rule, store, module, max_failures=max_failures)
        for rule in _counted(tuple(rules), progress)
    ]
    logger.info(
        "evaluated %d rule(s) for %s: %d failed, %d not evaluated",
        len(results),
        module,
        sum(result.status == STATUS_FAIL for result in results),
        sum(result.status == STATUS_NOT_EVALUATED for result in results),
    )
    return results


def _trace_indexed(
    store: _Store,
    rules: Iterable[Rule],
    *,
    progress: ProgressCallback | None = None,
    max_failures: int | None = MAX_FAILURES,
    comparisons: bool = True,
) -> RuleTrace:
    """``trace_rules`` over a return that is already indexed; see ``_evaluate_indexed``.

    With ``comparisons`` false, the trace is ``_trace_lean``'s.
    """
    module = store.pack.info.module
    evaluations: list[Evaluation] = []
    cells: dict[CellAddress, CellFact] = {}
    results = tuple(
        _evaluate_rule(
            rule,
            store,
            module,
            evaluations,
            cells,
            max_failures=max_failures,
            comparisons=comparisons,
        )
        for rule in _counted(tuple(rules), progress)
    )
    kind = RuleTrace if comparisons else _LeanTrace
    return kind(results=results, evaluations=tuple(evaluations), cells=cells)


def _trace_lean(  # noqa: PLR0913 - trace_rules's arguments
    ret: CanonicalReturn,
    pack: TaxonomyPack,
    rules: Iterable[Rule],
    *,
    accuracy: Accuracy | None = None,
    progress: ProgressCallback | None = None,
    max_failures: int | None = MAX_FAILURES,
) -> RuleTrace:
    """``trace_rules`` without the comparisons: for a caller that reads only each side.

    The results are ``trace_rules``'s, and so is every evaluation — its place,
    verdict, relation, both sides' cells and both sides' values — except that
    ``Evaluation.comparisons`` is empty. So each evaluation's ``cells`` holds
    its sides' cells alone, and ``RuleTrace.cells`` lacks the cells only a
    where clause reads (a where clause is no side of the rule), and holds the
    rest in the order the sides first read them rather than the comparisons.
    Logging every comparison with its operands was about half of what a trace
    cost beyond the verdict (measured on a 200-country return), and a
    comparison of two returns reads none of it.

    Not for evidence, which records the comparisons. The trace returned is a
    ``_LeanTrace``, so a caller can tell it from a full one; ``dataclasses.replace``
    and ``validate.execution.trace_as_run`` keep it one.
    """
    store = _Store(ret, pack, accuracy or Accuracy())
    return _trace_indexed(
        store, rules, progress=progress, max_failures=max_failures, comparisons=False
    )


class _LeanTrace(RuleTrace):
    """A ``RuleTrace`` made without the comparisons (``_trace_lean``): never evidence.

    How a caller tells a lean trace from a full one: ``isinstance(trace,
    _LeanTrace)``. A class, not a field: a field would be on every full trace
    too, and so in everything that reads or records one. The class survives
    ``dataclasses.replace``, copying and pickling; code that builds a new
    ``RuleTrace`` from a lean one's parts makes one that looks full, so code
    that narrows a trace uses ``replace`` (``validate.execution.trace_as_run``).
    """


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
#: A selector's matching cells by where they sit: the axes a place names, then
#: the place's values on those axes, then the cells there in ``_matching`` order.
_PlaceIndex = dict[tuple[str, ...], dict[tuple[str, ...], list[_CellKey]]]
#: The same, with each cell given by its position in ``_matching`` order.
_PositionIndex = dict[tuple[str, ...], dict[tuple[str, ...], list[int]]]


@dataclass
class _TableData:
    """One table's reported cells, indexed the ways a reference selects them."""

    table: Table
    #: The member of the table's open sheet axis that a fact reported with no
    #: member is at: the dimension's default, where the axis accepts it as a
    #: sheet of its own (OF 08.06's "all types", ``eba_TA:x0``); else ``None``.
    default_member: str | None = None
    cells: dict[_CellKey, object] = field(default_factory=dict)
    #: The data point each reported cell holds. Two cells of one data point —
    #: some figures are shown twice — are ONE fact to the gateway.
    points: dict[_CellKey, int] = field(default_factory=dict)
    #: The ``decimals`` each reported cell states, where it states one.
    decimals: dict[_CellKey, int] = field(default_factory=dict)
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
    #: A reported cell's address, made the first time a trace reads the cell
    #: (``_Evaluation._register``) and shared by every evaluation that reads
    #: it, where a trace made the address again at every read.
    addresses: dict[_CellKey, CellAddress] = field(default_factory=dict)

    def add(self, key: _CellKey, value: object, point: int, decimals: object = None) -> None:
        self.cells[key] = value
        self.points[key] = point
        if isinstance(decimals, int):
            self.decimals[key] = decimals
        _sheet, _member, row, column = key
        self.by_row_column.setdefault((row, column), []).append(key)
        self.by_column.setdefault(column, []).append(key)
        self.by_row.setdefault(row, []).append(key)


class _Store:
    """The return's facts as typed cell values, per table."""

    def __init__(self, ret: CanonicalReturn, pack: TaxonomyPack, accuracy: Accuracy) -> None:
        self.pack = pack
        self.accuracy = accuracy
        self.reported = {code for code, filed in filing_indicators(ret, pack).items() if filed}
        self.tables: dict[str, _TableData] = {}
        #: Per table with an open sheet axis: each key that names a member, and
        #: the member it names (``_member``). Built when the table's first
        #: keyed fact is placed.
        self._members: dict[str, dict[str, str]] = {}
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
            holder.add(key, value, number, row["decimals"])
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

    def fact(self, data: _TableData, key: _CellKey, address: CellAddress) -> CellFact:
        """A reported cell as the evidence records it."""
        point = data.points[key]
        metric = self.pack.datapoints[point].metric
        definition = self.pack.metrics.get(metric)
        data_type = definition.data_type if definition is not None else ""
        value = data.cells[key]
        if isinstance(value, _Amount):
            decimals, source = effective_decimals(data.decimals.get(key), data_type, self.accuracy)
            return CellFact(
                address, point, metric, data_type, value.value, decimals, source, value.allowance
            )
        shown = value if isinstance(value, (str, bool)) else None
        return CellFact(address, point, metric, data_type, shown, None, "", 0.0)

    def is_reported(self, table: str) -> bool:
        definition = self.pack.tables.get(table)
        return definition is not None and definition.filing_indicator in self.reported

    def _data(self, table: Table) -> _TableData:
        holder = self.tables.get(table.code)
        if holder is None:
            holder = self.tables[table.code] = _TableData(table, self._default_member(table))
        return holder

    def _default_member(self, table: Table) -> str | None:
        """The default member of ``table``'s open sheet axis, where it is a sheet of its own."""
        axis = table.open_axis
        if axis is None or not axis.default_allowed or axis.dimension is None:
            return None
        dimension = self.pack.dimensions.get(axis.dimension)
        return None if dimension is None else dimension.default

    def _member(self, table: Table, open_key: str | None) -> str | None:
        """An open-axis key as the member's QName.

        A fact with no key is at the dimension's DEFAULT member (XBRL
        Dimensions), which is written by leaving the dimension out: on an axis
        that accepts it, that is a sheet like any other, so the fact is given
        the default's QName — the place the gateway evaluates it at.

        A key is the member whose QName it is; else the first member, in the
        axis's order, whose local name it is (``GB``); else it is kept as
        written. Looked up in a dictionary made once per table: walking the
        member list for each fact (252 members on the Bank's country axis) made
        local-name keys — the form sources are told to write, and the form the
        XBRL reader gives — cost three times as much to index as QNames.
        """
        axis = table.open_axis
        if axis is None:
            return None
        if open_key is None:
            return self._data(table).default_member
        named = self._members.get(table.code)
        if named is None:
            named = self._members[table.code] = _members_by_key(axis.members)
        return named.get(open_key, open_key)


def _members_by_key(members: Sequence[str]) -> dict[str, str]:
    """An open axis's members by each key that names one: its QName, or its local name.

    The same answer as a walk of ``members`` for each key: a local name two
    members share names the first of them, and a key that is one member's QName
    names that member before any member it is merely the local name of.
    """
    named: dict[str, str] = {}
    for member in members:
        named.setdefault(local_name(member), member)
    named.update({member: member for member in members})
    return named


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
    effective, _source = effective_decimals(decimals, data_type, accuracy)
    if effective >= DECIMALS_EXACT:
        return 0.0
    return 10.0 ** (-effective) / 2.0


# =============================================================================
# Private helpers — one rule
# =============================================================================


class _Unsupported(Exception):  # noqa: N818 - control flow, not an error condition
    """The rule uses something the engine does not implement."""


class _NotBound(Exception):  # noqa: N818 - control flow
    """A reference with no default has no reported cell: no evaluation here."""


#: How ``_Evaluation._locate`` reads one axis of a cell: the place axis it is
#: read at and the codes accepted there (``None`` for any), or — for an axis the
#: reference does not iterate — ``(None, None, code)``, the one code it names.
_AxisPlan = tuple[str | None, frozenset[str] | None, str | None]


@dataclass(frozen=True)
class _Selector:
    """A reference resolved against its table and the rule's scope.

    For each axis: the codes the reference accepts (``None`` for "any"). How a
    cell is found at a place (the ``*_plan`` fields, ``member_axis``,
    ``fixed_member``) and the place a cell sits at (``place_plan``) are worked
    out here once for every evaluation of the rule, not again at each one.

    Kept by ``id()`` and never compared or hashed: it holds the table's data.
    """

    reference: Reference
    data: _TableData
    rows: tuple[str, ...] | None
    columns: tuple[str, ...] | None
    sheets: tuple[str, ...] | None
    member: str | None
    member_excluded: bool
    value_member: str | None
    closed: frozenset[str]
    column_plan: _AxisPlan
    #: ``None`` for a table with no fixed sheet axis.
    sheet_plan: _AxisPlan | None
    #: ``None`` for a table with open rows: a row is found by its key.
    row_plan: _AxisPlan | None
    #: The place axis the open-axis member is read at, where the reference
    #: does not fix one; else the member it fixes (``fixed_member``).
    member_axis: str | None
    fixed_member: str | None
    #: Open rows: (key dimension, the place axis it is read at), by dimension.
    key_plan: tuple[tuple[str, str], ...]
    #: Each iterated axis, by name: (axis, its kind — ``r``, ``c``, ``z``,
    #: ``open:`` or ``key:`` — and for a row key its dimension, else ``""``).
    place_plan: tuple[tuple[str, str, str], ...]

    @property
    def table(self) -> Table:
        return self.data.table


def _evaluate_rule(  # noqa: PLR0913 - the rule, where it runs, and what to keep of it
    rule: Rule,
    store: _Store,
    module: str,
    trace: list[Evaluation] | None = None,
    cells: dict[CellAddress, CellFact] | None = None,
    *,
    max_failures: int | None = MAX_FAILURES,
    comparisons: bool = True,
) -> RuleResult:
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
        evaluation = _Evaluation(rule, store, cells)
        satisfied, failures, unsatisfied = evaluation.run(
            trace, max_failures, comparisons=comparisons
        )
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

    def __init__(
        self, rule: Rule, store: _Store, cells: dict[CellAddress, CellFact] | None = None
    ) -> None:
        self._rule = rule
        self._store = store
        #: The rule's parsed parts, read off it ONCE and used from here alone.
        #: Selectors are keyed by ``id()`` of the reference nodes of these
        #: trees, and the rule could hand out another parse of the same text
        #: if asked again — two threads filling an unlocked cache did — whose
        #: nodes no selector is keyed by.
        self._tree = rule.tree
        self._where = rule.where_tree
        joins = rule.joins
        #: Tracing only: the reported cells read so far, and the comparisons
        #: the current evaluation has executed and where in the rule.
        self._cells_out = cells
        self._log: list[Comparison] | None = None
        self._branch: list[str] = []
        self._aliases = _key_aliases(joins)
        self._selectors: dict[int, _Selector] = {}
        #: Per selector, worked out once and kept for the rule's every
        #: evaluation: the cells it accepts, and those cells by place.
        self._matched: dict[int, list[_CellKey]] = {}
        self._by_place: dict[int, _PlaceIndex] = {}
        #: ... and, for a selector whose cells sit at places of two shapes,
        #: their positions in ``_matched`` by place (``_keys_at``).
        self._by_position: dict[int, _PositionIndex] = {}
        #: ... and the cells it accepts as a set, to ask of one cell (``_accepting``).
        self._accepted: dict[int, frozenset[_CellKey]] = {}
        #: At the place being evaluated: the cell each selector reads there
        #: (``_cell``), and the two values the rule's own comparison compared
        #: (``_value``). Both are emptied at every place (``run``).
        self._here: dict[int, _CellKey | None] = {}
        self._operands: tuple[object, object] | None = None
        scope = {group.table: group for group in rule.scope_groups}
        trees = [self._tree, *([self._where] if self._where is not None else [])]
        self._references = [ref for tree in trees for ref in references(tree)]
        for item in joins:
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

    def run(
        self,
        trace: list[Evaluation] | None = None,
        max_failures: int | None = MAX_FAILURES,
        *,
        comparisons: bool = True,
    ) -> tuple[int, list[Failure], int]:
        """Every evaluation: counted, the first failures kept, each traced if asked.

        ``max_failures`` is how many failures are kept; ``None`` keeps them all.
        A traced evaluation keeps the comparisons it executed unless
        ``comparisons`` is false (``_trace_lean``).
        """
        satisfied = unsatisfied = 0
        failures: list[Failure] = []
        seen: set[tuple[object, ...]] = set()
        for env in self._environments():
            # Everything below is read at this one place, so what was found at
            # the last place is no answer here.
            self._here = {}
            self._operands = None
            if trace is not None and comparisons:
                self._log = []
            holds = self._verdict(env, seen)
            # Stop logging before anything re-reads the rule's sides to report
            # them: the log is what the verdict itself executed.
            executed, self._log = tuple(self._log or ()), None
            if holds is None:
                continue
            if trace is not None:
                trace.append(self._traced(env, holds=holds, comparisons=executed))
            if holds:
                satisfied += 1
                continue
            unsatisfied += 1
            if max_failures is None or len(failures) < max_failures:
                failures.append(self._failure(dict(env)))
        return satisfied, failures, unsatisfied

    def _verdict(self, env: _Env, seen: set[tuple[object, ...]]) -> bool | None:
        """Whether the evaluation at ``env`` holds; ``None`` where there is no evaluation."""
        values = dict(env)
        facts = self._facts_bound(values)
        # A reference with no default and no reported cell cannot be bound:
        # the evaluation does not exist.
        if facts is None:
            return None
        # Nothing reported here at all: not evaluated, unless the rule is
        # one the gateway runs regardless.
        if not any(facts) and not self._rule.always_execute:
            return None
        # The gateway evaluates over FACTS. Two places that read exactly
        # the same facts — a figure the table shows in two cells — are one
        # evaluation.
        if facts in seen:
            return None
        seen.add(facts)
        try:
            if self._where is not None and self._branched("where", self._where, values) is not True:
                return None
            return self._branched("rule", self._tree, values) is True
        except (_NotBound, ZeroDivisionError):
            return None

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
                facts = frozenset(self._fact(selector, key) for key in self._keys_at(selector, env))
                entry: object = facts or None
            else:
                key = self._cell(selector, env)
                entry = None
                if key is not None and key in self._accepting(selector):
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
        for reference in references(self._tree):
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
            environments = _maximal(_outer_join(environments, partial))
        if not environments and self._rule.always_execute:
            return [()]
        return sorted(environments)

    def _place(self, selector: _Selector, key: _CellKey) -> _Env | None:
        """The place a reported cell sits at, over the axes ``selector`` iterates."""
        sheet, member, row, column = key
        place: list[tuple[str, str]] = []
        for axis, kind, dimension in selector.place_plan:
            if kind == AXIS_ROW:
                place.append((axis, row))
            elif kind == AXIS_COLUMN:
                place.append((axis, column))
            elif kind == AXIS_SHEET:
                if sheet is None:
                    return None
                place.append((axis, sheet))
            elif kind == _AXIS_OPEN:
                # No member on an axis with no default sheet: a fact the axis
                # cannot hold (the structure check's STR finding). It is read
                # wherever the rest of the rule is; one at the default sheet
                # has the default's member (``_Store._member``), and a place.
                if member is None:
                    continue
                place.append((axis, member))
            else:
                value = selector.data.row_keys.get((sheet, member, row), {}).get(dimension)
                if value is None:
                    return None
                place.append((axis, value))
        return tuple(place)

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
        # What a summed reference spans, in the formula's word; ``None`` where
        # the rule book does not say (built without a taxonomy package), and the
        # text alone decides. The text cannot: ``isum({.., seq: True})`` is the
        # same whether the formula's variable covers an open dimension — and so
        # takes every row or member of it at once — or leaves it uncovered, to
        # be lined up with the rest of the rule (implicit filtering).
        spans = (
            self._rule.spans_by_variable.get(reference.variable)
            if reference.sequence and reference.variable
            else None
        )
        if open_axis is not None and (member is None or excluded):
            shared = f"{_AXIS_OPEN}{open_axis.dimension}"
            if spans is not None:
                # Every member at once where the variable covers the dimension
                # (the Bank's ``boe_b0816``: all of OF 08.06's sheets, though no
                # member is named); otherwise one member at a time, shared.
                if open_axis.dimension not in spans:
                    free.add(shared)
            elif open_axis.dimension not in self._named_dimensions:
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
        for key in table.open_keys if table.open_rows else ():
            if reference.sequence and (spans is None or key.dimension in spans):
                # The sum takes every row at once: "the class total equals the
                # sum over all grades" (``boe_b0752``). A row key the formula
                # leaves uncovered is instead read row by row, at the row the
                # rest of the rule is read at — "each grade's total outflow
                # equals the sum of its own parts" (``boe_b0761``).
                continue
            name = f"{_AXIS_KEY}{self._aliases.get((table.code, key.dimension), key.dimension)}"
            key_axes[name] = key.dimension
            free.add(name)

        def plan(kind: str, accepted: tuple[str, ...] | None) -> _AxisPlan:
            """How ``_locate`` reads the ``kind`` axis: at the place, or at the one code named."""
            name = own_axes.get(kind, kind)
            if name in free:
                return (name, None if accepted is None else frozenset(accepted), None)
            return (None, None, accepted[0] if accepted else None)

        member_axis = None
        if open_axis is not None and (member is None or excluded):
            shared = f"{_AXIS_OPEN}{open_axis.dimension}"
            member_axis = own_axes.get(shared, shared)
        return _Selector(
            reference=reference,
            data=data,
            rows=rows,
            columns=columns,
            sheets=sheets,
            member=member,
            member_excluded=excluded,
            value_member=value_member,
            closed=self._rule.closed
            | self._rule.closed_by_variable.get(reference.variable or "", frozenset()),
            column_plan=plan(AXIS_COLUMN, columns),
            sheet_plan=None if table.fixed_axis is None else plan(AXIS_SHEET, sheets),
            row_plan=None if table.open_rows else plan(AXIS_ROW, rows),
            member_axis=member_axis,
            fixed_member=None if excluded else member,
            # A table's key dimensions are distinct, so this is their order by
            # dimension, as a cell's row is looked up by (``rows_by_key``).
            key_plan=tuple(sorted((dimension, name) for name, dimension in key_axes.items())),
            # In name order: the names are distinct, so a place built in this
            # order is already sorted, as ``_Env`` is.
            place_plan=tuple(
                (name, _axis_kind(name, own_axes), key_axes.get(name, "")) for name in sorted(free)
            ),
        )

    def _matching(self, selector: _Selector) -> list[_CellKey]:
        """The reported cells ``selector`` accepts, whatever the place. Worked out once."""
        found = self._matched.get(id(selector))
        if found is None:
            found = [key for key in self._candidates(selector) if self._accepts(selector, key)]
            self._matched[id(selector)] = found
        return found

    def _accepting(self, selector: _Selector) -> frozenset[_CellKey]:
        """``_matching(selector)`` as a set: whether a cell is reported AND accepted, in one test.

        The same answer as ``key in cells and _accepts(selector, key)`` for a
        cell ``_cell`` finds: such a cell lies on the rows and columns the
        selector names (or it names none), so it is among ``_candidates``
        wherever it is reported. Asking it at every read ran the selector's
        filters again on a cell they had already decided.
        """
        found = self._accepted.get(id(selector))
        if found is None:
            found = self._accepted[id(selector)] = frozenset(self._matching(selector))
        return found

    def _keys_at(self, selector: _Selector, env: Mapping[str, str]) -> Sequence[_CellKey]:
        """The cells of ``_matching(selector)`` that sit at ``env``, in that order.

        A cell sits at ``env`` when it has a place (``_place``) and ``env``
        holds that place's value on every axis the place names.

        Looked up, not scanned. A summed reference is read at every evaluation,
        and scanning every cell it could read for the few at this place made a
        rule's cost the product of its evaluations and its cells — both of which
        grow with an open axis, so a return's rules took time in the SQUARE of
        its countries. Each matching cell's place is worked out once instead,
        and the cells are indexed by it. The result may be the index's own list:
        read it, never change it.
        """
        index = self._by_place.get(id(selector))
        if index is None:
            index = self._by_place[id(selector)] = self._place_index(selector)
        if len(index) == 1:
            ((axes, cells),) = index.items()
            return cells.get(tuple(env.get(axis) for axis in axes), [])
        # A cell with no member on an open axis has a place that does not name
        # the axis (``_place``), so a selector can index places of two shapes.
        # Each shape is looked up, and the cells come back in ``_matching``
        # order by their positions in it. Filtering ``_matching`` for the cells
        # found instead read every cell the selector accepts at every
        # evaluation: a few blank country cells were enough to bring back the
        # cost in the square of the countries.
        positions = self._by_position.get(id(selector))
        if positions is None:
            positions = self._by_position[id(selector)] = self._position_index(selector)
        matching = self._matching(selector)
        hit = sorted(
            position
            for axes, at in positions.items()
            for position in at.get(tuple(env.get(axis) for axis in axes), ())
        )
        return [matching[position] for position in hit]

    def _place_index(self, selector: _Selector) -> _PlaceIndex:
        """``_matching(selector)`` by place: a cell with no place (``_place``) sits nowhere."""
        index: _PlaceIndex = {}
        for key in self._matching(selector):
            place = self._place(selector, key)
            if place is None:
                continue
            axes = tuple(axis for axis, _value in place)
            values = tuple(value for _axis, value in place)
            index.setdefault(axes, {}).setdefault(values, []).append(key)
        return index

    def _position_index(self, selector: _Selector) -> _PositionIndex:
        """``_place_index``, each cell given by its position in ``_matching(selector)``.

        A cell listed twice there is at both positions, under its one place.
        """
        index: _PositionIndex = {}
        for position, key in enumerate(self._matching(selector)):
            place = self._place(selector, key)
            if place is None:
                continue
            axes = tuple(axis for axis, _value in place)
            values = tuple(value for _axis, value in place)
            index.setdefault(axes, {}).setdefault(values, []).append(position)
        return index

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
            values = [selector.data.cells[key] for key in self._keys_at(selector, env)]
            if values:
                return values
            if reference.default is None:
                raise _NotBound
            return [] if reference.default.kind == DEFAULT_EMPTY else [_default(reference.default)]

        key = self._cell(selector, env)
        if key is not None and key in self._accepting(selector):
            return selector.data.cells[key]
        if reference.default is None:
            raise _NotBound
        return _default(reference.default)

    def _cell(self, selector: _Selector, env: Mapping[str, str]) -> _CellKey | None:
        """The one cell a non-sequence reference reads at ``env``; ``None`` if it has none.

        Looked up once per place (``_locate``) and kept until the next one:
        binding the references, evaluating the expression, tracing each
        side and its comparisons and describing a failure all ask for the same
        cell, at the one place ``run`` is evaluating. Each caller still decides
        for itself what the cell is to it — reported and accepted, or reported
        at all — so the answer kept is the cell alone.
        """
        here = self._here
        if id(selector) in here:
            return here[id(selector)]
        found = here[id(selector)] = self._locate(selector, env)
        return found

    def _locate(self, selector: _Selector, env: Mapping[str, str]) -> _CellKey | None:
        """``_cell``, worked out: the selector's plans read at ``env``."""
        column = _axis_code(selector.column_plan, env)
        if column is None:
            return None
        sheet = None
        if selector.sheet_plan is not None:
            sheet = _axis_code(selector.sheet_plan, env)
            if sheet is None:
                return None
        member = selector.fixed_member
        if selector.member_axis is not None:
            member = env.get(selector.member_axis)
        if selector.row_plan is not None:
            row = _axis_code(selector.row_plan, env)
            return None if row is None else (sheet, member, row, column)
        wanted = tuple((dimension, env.get(axis)) for dimension, axis in selector.key_plan)
        if any(value is None for _dimension, value in wanted):
            return None
        row_id = selector.data.rows_by_key.get((sheet, member, wanted))  # type: ignore[arg-type]
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
            if self._branched("if", node.condition, env) is True:
                return self._branched("then", node.then, env)
            return True if node.otherwise is None else self._branched("else", node.otherwise, env)
        if isinstance(node, Binary):
            left, right = self._value(node.left, env), self._value(node.right, env)
            if node.is_comparison:
                if node is self._tree:
                    # What the trace states each side came to (``_traced``):
                    # the values compared, rather than each side evaluated again.
                    self._operands = (left, right)
                holds = _compare(node.operator, left, right, node.interval)
                if self._log is not None:
                    self._log.append(self._comparison(node, left, right, env, holds=holds))
                return holds
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
        # ``isum`` / ``iabs`` are the interval functions (``iaf:sum``): they keep
        # the allowances of the facts they read. ``sum`` / ``abs`` are XPath's,
        # whose result is a plain number — not a fact — and carries none
        # (``iaf:splitValueThreshold``). Measured against Arelle on boe_b0770,
        # boe_b0794, boe_b0820-b0823, boe_b0829 and boe_b1037_ss.
        if name in ("isum", "sum"):
            items = [_amount(item) for item in _sequence(values[0])]
            present = [item for item in items if item is not None]
            allowance = math.fsum(item.allowance for item in present) if name == "isum" else 0.0
            return _Amount(math.fsum(item.value for item in present), allowance)
        if name in ("iabs", "abs"):
            operand = _amount(values[0])
            if operand is None:
                return None
            return _Amount(abs(operand.value), operand.allowance if name == "iabs" else 0.0)
        # Plain ``max`` / ``min`` are deliberately read as ``imax`` / ``imin``, the
        # chosen fact keeping its allowance, and that reading is UNMEASURED: no
        # packaged rule calls them, so Arelle cannot be asked through a Bank
        # formula. test_no_packaged_rule_calls_plain_max_or_min fails on the first
        # release that adds one; measure it with Arelle before trusting this.
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
        addresses: dict[CellAddress, None] = {}
        seen: set[int] = set()
        for reference in references(self._tree):
            if id(reference) in seen:
                continue
            seen.add(id(reference))
            selector = self._selectors[id(reference)]
            label = _describe(reference)
            addresses.update(dict.fromkeys(self._addresses(reference, env)))
            if reference.sequence:
                keys = self._keys_at(selector, env)
                values = [selector.data.cells[key] for key in keys]
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
        return Failure(
            place=place,
            cells=tuple(cells[:8]),
            addresses=tuple(addresses)[:MAX_ADDRESSES],
        )

    def _traced(
        self, env: _Env, *, holds: bool, comparisons: tuple[Comparison, ...] = ()
    ) -> Evaluation:
        """One evaluation as the trace keeps it: each side's cells and number."""
        tree = self._tree
        values = dict(env)
        if isinstance(tree, Binary) and tree.is_comparison:
            # An evaluation is traced only once its verdict is reached, and the
            # verdict of a rule that is one comparison is that comparison's.
            operands = self._operands
            assert operands is not None  # noqa: S101 - run() traces after the verdict
            left, right = operands
            return Evaluation(
                rule_id=self._rule.rule_id,
                place=env,
                holds=holds,
                relation=tree.operator,
                left=self._side(tree.left, values),
                right=self._side(tree.right, values),
                left_value=_figure(left),
                right_value=_figure(right),
                comparisons=comparisons,
            )
        return Evaluation(
            rule_id=self._rule.rule_id,
            place=env,
            holds=holds,
            relation=None,
            left=self._side(tree, values),
            comparisons=comparisons,
        )

    def _branched(self, branch: str, node: Node, env: Mapping[str, str]) -> object:
        """``node``'s value, with the branch it is in noted while comparisons are logged."""
        if self._log is None:
            return self._value(node, env)
        self._branch.append(branch)
        try:
            return self._value(node, env)
        finally:
            self._branch.pop()

    def _comparison(
        self, node: Binary, left: object, right: object, env: Mapping[str, str], *, holds: bool
    ) -> Comparison:
        """A comparison just executed, as the evidence records it."""
        first, second = _single(left), _single(right)
        difference = excess = None
        tolerance = 0.0
        if isinstance(first, _Amount) and isinstance(second, _Amount):
            difference = first.value - second.value
            tolerance = first.allowance + second.allowance if node.interval else 0.0
            excess = _excess(node.operator, difference, tolerance)
        return Comparison(
            operator=node.operator,
            interval=node.interval,
            left=self._operand(node.left, first, env),
            right=self._operand(node.right, second, env),
            difference=difference,
            tolerance=tolerance,
            excess=excess,
            holds=holds,
            branch="/".join(self._branch),
        )

    def _operand(self, node: Node, value: object, env: Mapping[str, str]) -> Operand:
        """One side of a comparison: its value, its allowance and the cells behind it."""
        read: dict[CellAddress, None] = {}
        defaulted: list[DefaultedCell] = []
        for reference in references(node):
            selector = self._selectors[id(reference)]
            if reference.sequence:
                keys = self._keys_at(selector, env)
                read.update(dict.fromkeys(self._register(selector, key) for key in keys))
                if not keys and reference.default is not None:
                    defaulted.append(_defaulted(reference, None))
                continue
            key = self._cell(selector, env)
            if key is not None and key in self._accepting(selector):
                read[self._register(selector, key)] = None
            elif reference.default is not None:
                cell = None if key is None else _address(selector.data, key, reported=False)
                defaulted.append(_defaulted(reference, cell))
        if isinstance(value, _Amount):
            shown: float | str | bool | None = value.value
            allowance = value.allowance
        else:
            shown = value if isinstance(value, (str, bool)) else None
            allowance = 0.0
        return Operand(shown, allowance, tuple(read), tuple(defaulted))

    def _register(self, selector: _Selector, key: _CellKey) -> CellAddress:
        """A reported cell's address, recorded in the trace's cells if tracing."""
        data = selector.data
        address = data.addresses.get(key)
        if address is None:
            address = data.addresses[key] = _address(data, key, reported=True)
        if self._cells_out is not None and address not in self._cells_out:
            self._cells_out[address] = self._store.fact(data, key, address)
        return address

    def _side(self, node: Node, env: Mapping[str, str]) -> tuple[CellAddress, ...]:
        """Every cell the references in ``node`` read at ``env``, once each, in rule order."""
        found: dict[CellAddress, None] = {}
        for reference in references(node):
            found.update(dict.fromkeys(self._addresses(reference, env)))
        return tuple(found)

    def _addresses(self, reference: Reference, env: Mapping[str, str]) -> list[CellAddress]:
        """The cells one reference reads at ``env``; a cell read at its default is unreported."""
        selector = self._selectors[id(reference)]
        if reference.sequence:
            keys = self._keys_at(selector, env)
            return [self._register(selector, key) for key in keys]
        key = self._cell(selector, env)
        if key is None:
            return []
        if key in selector.data.cells:
            return [self._register(selector, key)]
        return [_address(selector.data, key, reported=False)]


# =============================================================================
# Private helpers — places
# =============================================================================


def _counted(rules: tuple[Rule, ...], progress: ProgressCallback | None) -> Iterator[Rule]:
    """``rules``, one at a time, telling ``progress`` how many are done before each next one.

    The count is reported before the first rule (0 of N) and after every rule,
    the last included (N of N), so a watcher sees the step start and finish.
    """
    total = len(rules)
    notify(progress, Progress(PHASE_RULES, 0, total))
    for done, rule in enumerate(rules, start=1):
        yield rule
        notify(progress, Progress(PHASE_RULES, done, total))


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


def _axis_kind(name: str, own_axes: Mapping[str, str]) -> str:
    """What an iterated axis ``name`` reads off a cell: ``r``, ``c``, ``z``, ``open:`` or ``key:``.

    ``own_axes`` maps an axis kind to the name a reference's own range of it
    goes by (``c@v1``); a kind it does not map goes by its own name.
    """
    if name == own_axes.get(AXIS_ROW, AXIS_ROW):
        return AXIS_ROW
    if name == own_axes.get(AXIS_COLUMN, AXIS_COLUMN):
        return AXIS_COLUMN
    if name == own_axes.get(AXIS_SHEET, AXIS_SHEET):
        return AXIS_SHEET
    if name.startswith(_AXIS_OPEN):
        return _AXIS_OPEN
    return _AXIS_KEY


def _axis_code(plan: _AxisPlan, env: Mapping[str, str]) -> str | None:
    """The code one axis ``plan`` reads at ``env``; ``None`` where the cell has none there.

    An axis the reference does not iterate reads the one code it names, as it
    is. An iterated axis reads the place's code, and finds none where the place
    names no code on it or one the reference does not accept. A plain function,
    not a method: ``_Evaluation._locate`` calls it for each axis of each
    reference at each place, and it needs nothing of the evaluation.
    """
    axis, accepted, code = plan
    if axis is None:
        return code
    code = env.get(axis)
    if accepted is not None and code not in accepted:
        return None
    return code


def _outer_join(environments: set[_Env], partial: set[_Env]) -> set[_Env]:
    """Each env joined with every place it agrees with; an env or place that meets none, as it is.

    A hash join on the axes the two share. The places are grouped by the axes
    they name and indexed by their values on the axes an env shares with them,
    so an env meets only the places that agree with it, not every place: trying
    every pair made the join's cost the product of the two sets, each of which
    grows with an open axis. The same set as joining every pair with ``_join``.
    """
    groups: dict[tuple[str, ...], list[_Env]] = {}
    for place in partial:
        groups.setdefault(tuple(axis for axis, _value in place), []).append(place)
    indexes: dict[tuple[tuple[str, ...], tuple[str, ...]], dict[tuple[str, ...], list[_Env]]] = {}
    merged: set[_Env] = set()
    used: set[_Env] = set()
    for env in environments:
        values = dict(env)
        hit = False
        for axes, places in groups.items():
            shared = tuple(axis for axis in axes if axis in values)
            index = indexes.get((axes, shared))
            if index is None:
                index = indexes[(axes, shared)] = {}
                for place in places:
                    named = dict(place)
                    index.setdefault(tuple(named[axis] for axis in shared), []).append(place)
            for place in index.get(tuple(values[axis] for axis in shared), ()):
                joined = _join(env, place)
                if joined is not None:
                    merged.add(joined)
                    used.add(place)
                    hit = True
        if not hit:
            merged.add(env)
    merged.update(partial - used)
    return merged


def _join(env: _Env, place: _Env) -> _Env | None:
    """``env`` extended with ``place``; ``None`` where they disagree on an axis."""
    merged = dict(env)
    for axis, value in place:
        if merged.setdefault(axis, value) != value:
            return None
    return tuple(sorted(merged.items()))


def _maximal(environments: set[_Env]) -> set[_Env]:
    """Drop any place that another place extends: the fuller one is the evaluation.

    A place extends another when it names every axis the other names, with the
    same values, and more. The places are grouped by the axes they name — a
    handful of shapes — and a place is dropped when its values are among those
    of a fuller shape's places, cut down to its own axes. Comparing every pair
    of places made this cost the square of their number, which grows with an
    open axis wherever a few cells sit at places of a shorter shape.
    """
    if len({len(env) for env in environments}) <= 1:
        return environments
    shapes: dict[tuple[str, ...], list[_Env]] = {}
    for env in environments:
        shapes.setdefault(tuple(axis for axis, _value in env), []).append(env)
    kept: set[_Env] = set()
    for shape, places in shapes.items():
        named = set(shape)
        extended: set[tuple[str, ...]] = set()
        for fuller, others in shapes.items():
            if named < set(fuller):
                at = [fuller.index(axis) for axis in shape]
                extended.update(tuple(other[index][1] for index in at) for other in others)
        kept.update(
            place for place in places if tuple(value for _axis, value in place) not in extended
        )
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


def _figure(value: object) -> float | None:
    """A value as a number, or ``None`` where it is not one (``Evaluation.left_value``)."""
    amount = _amount(value)
    return None if amount is None else amount.value


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


def _single(value: object) -> object:
    """A value as a comparison reads it: a one-item sequence is its item, a longer one nothing."""
    if isinstance(value, list):
        return value[0] if len(value) == 1 else None
    return value


def _excess(operator: str, difference: float, tolerance: float) -> float | None:
    """How far ``difference`` is beyond the bound ``operator`` sets; see ``Comparison``."""
    if operator == "=":
        return max(0.0, abs(difference) - tolerance)
    if operator in ("<=", "<"):
        return max(0.0, difference - tolerance)
    if operator in (">=", ">"):
        return max(0.0, -tolerance - difference)
    return None


def _defaulted(reference: Reference, address: CellAddress | None) -> DefaultedCell:
    """A reference read at its default."""
    default = reference.default
    assert default is not None  # noqa: S101 - callers check
    return DefaultedCell(_describe(reference), default.kind, default.value, address)


def _address(data: _TableData, key: _CellKey, *, reported: bool) -> CellAddress:
    """A cell key as the address a failure records, in the return's own coordinates.

    A cell on the default sheet is reported with no open key, so it is
    addressed with none.
    """
    sheet, member, row, column = key
    return CellAddress(
        table=data.table.code,
        sheet=sheet,
        open_key=None if member is None or member == data.default_member else local_name(member),
        row=row,
        column=column,
        reported=reported,
    )


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
