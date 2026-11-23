"""
A small synthetic PRA001 corpus that reaches the rule-engine paths no shipped return reaches.

Pipeline position:
    packaged PRA001 v4.1.1 pack and rule book
        ->  build_corpus (the returns) / corpus_rulebook (packaged + hand-built rules)
        ->  engine_golden.run_corpus  ->  tests/boe/test_engine_equivalence.py

Key responsibilities:
- Build every return in code, from the packaged pack and a fixed seed. There is
  no binary fixture and nothing to regenerate: a pack, rule-book or generator
  change shows as a changed corpus fingerprint, apart from a changed verdict.
- Hold the shapes the package's own returns and its Arelle oracle returns do
  not (measured 2026-11-22: 0 facts on an open-row table, 0 facts with no member
  on an open axis and 0 reported cells a rule turns away, over 18 benchmark
  returns and 44 oracle returns):
    - ``open_axes``: countries on OF 09.01 / OF 09.02 written both as local
      names and as QNames, one country written BOTH ways on the same cells, an
      unknown key, a default sheet (OF 08.06), and three dozen facts with NO
      member mixed in among the membered ones — the input that makes a selector
      index places of two shapes;
    - ``open_rows``: thirteen of PRA001's eighteen open-row tables (the five
      left out are siblings of OF 24.03.01.04) — several rows per sheet, keys
      given as numbers and as text, as QNames and as local names, a duplicate
      key, a missing key, rows under an open sheet axis, a sheet whose summed
      rule reads more cells than a failure records, and an accuracy of the
      caller's own;
    - ``designed``: hand-placed figures for the hand-built rules, so each
      comparison operator is met below, on and above its bound;
    - ``wide``: a seeded random return over most of the module, every template
      declared, with stripped codes, wrongly typed values and unknown codes;
    - ``empty``: two templates declared filed and not one fact.
- Supply the rules no packaged PRA001 rule stands in for
  (``hand_built_rules``): a where clause, nested conditionals, a filter on a
  cell's own value, a formula that closes a dimension a reported cell carries,
  and one rule for each way a rule can fail to be evaluable.
- Stay cheap: the whole corpus is under 12,000 facts.

Determinism: every choice is drawn from ``random.Random(seed).random()``, the
one method whose sequence Python guarantees across versions; ``choice``,
``sample`` and ``shuffle`` are not used. Two facts never share coordinates
unless they are alike in every column, because the structure check orders
facts by coordinate with an unstable sort and such a tie would have no defined
order to pin.

References:
- Bank of England Banking Taxonomy v4.1.1 (PRA001) — the packaged pack and rules
- docs/plans/rwa-filer-performance-review-2026-11-22.md — "Guards that land with
  the changes"
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import date
from functools import cache
from typing import TYPE_CHECKING, Final

import polars as pl

from pack_builders import VALID_LEI
from rwa_filer.boe.catalogue import Rule
from rwa_filer.boe.deny import DENY_DEACTIVATED, DENY_DOWNGRADED, DenyEntry
from rwa_filer.boe.engine import Accuracy
from rwa_filer.model import DECIMALS_EXACT, FACT_SCHEMA, CanonicalReturn, ReturnHeader
from rwa_filer.release import resolve_release

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from rwa_filer.boe.catalogue import RuleBook
    from rwa_filer.release import Release
    from rwa_filer.taxonomy.pack import OpenKey, TaxonomyPack

# =============================================================================
# Constants
# =============================================================================

MODULE: Final = "PRA001"
TAXONOMY: Final = "4.1.1"
#: The run date. It fixes which deny-list entries are in force, so the corpus's
#: verdicts do not move with the calendar.
RUN_DATE: Final = date(2026, 11, 22)
REFERENCE_DATE: Final = date(2027, 3, 31)
SEED: Final = 20261122

#: The two geographical tables: an open country axis with no default sheet.
GEO_EXPOSURES: Final = "OF09.01.01.01"
GEO_IRB: Final = "OF09.02.01.01"
GEO_DIMENSION: Final = "eba_dim:CEG"
GEO_TOTAL: Final = "eba_GA:x1"
#: Specialised lending by type: an open axis whose default member is a sheet.
DEFAULT_SHEET: Final = "OF08.06.01.01"
#: Obligor grades, and the class totals they are summed against.
GRADES: Final = "OF08.02.01.01"
CLASS_TOTALS: Final = "OF08.01.01.01"
COUNTERPARTIES: Final = "C34.06.01.01"
#: Open rows under an open sheet axis, which no packaged rule reads; and daily
#: VaR, keyed by one text key as the counterparties are by theirs.
RATINGS: Final = "OF08.05.01.02"
DAILY_VAR: Final = "OF24.03.01.04"
#: Where ``open_rows`` breaks boe_b0735: inside the footprint of the known issue
#: that labels it (PI-24), then outside it.
FOOTPRINT_RULE: Final = "boe_b0735"
FOOTPRINT_SHEETS: Final = ("0002", "0006")
#: A plain 10 x 3 monetary table two packaged rules read: where the hand-built
#: rules' figures are placed (``designed``).
MATRIX: Final = "OF25.03.01.02"
DATES: Final = "OF24.02.01.01"
ENTITY_DETAILS: Final = "OF700.00.01.01"
#: Own funds requirements: two of its rows show one data point.
OWN_FUNDS: Final = "OF02.00.01.01"
#: A table no packaged rule reads: only ``corpus_deactivated`` reads its cell.
UNRULED: Final = "OF16.00.01.01"

#: Countries as ``open_axes`` writes them: by local name and by QName.
COUNTRIES: Final = ("x1", "GB", "eba_GA:FR", "DE", "eba_GA:US", "JP", "eba_GA:IE", "NL")
#: How much of each geographical table each country reports, in ``COUNTRIES`` order.
_COUNTRY_SHARES: Final = (1.0, 1.0, 0.7, 0.7, 0.4, 0.4, 0.2, 0.2)
#: Left unreported by every country, so a member-less fact there is at a place
#: no membered cell extends.
STRAY_ONLY_COLUMNS: Final[Mapping[str, str]] = {GEO_EXPOSURES: "0090", GEO_IRB: "0130"}
#: Facts with no member on an open axis that has no default sheet, per table.
STRAYS: Final[Mapping[str, int]] = {GEO_EXPOSURES: 22, GEO_IRB: 10, "C09.04.01.01": 4}
#: Obligor grades on the one sheet whose sum reads more cells than a failure records.
MANY_GRADES: Final = 70

#: A dimension the ``MATRIX`` cells of rows 0010 to 0090 carry with a member
#: other than the default. Row 0100, the indices, does not carry it.
MATRIX_DIMENSION: Final = "eba_dim:CPS"
#: The currency the value-filter rules name, and the one ``designed`` reports.
CURRENCY_NAMED: Final = "eba_CU:GBP"
CURRENCY_REPORTED: Final = "eba_CU:EUR"

_NUMBERS: Final = (1.0, 2.0, 5.0, 100.0, 1000.0, -3.0, 0.5, 0.004, 12345.67, 1e6)
_DECIMALS: Final = (None, None, None, 0, 2, -3, DECIMALS_EXACT)
_DATES: Final = ("2026-12-31", "2027-03-31", "2028-01-01")
_TEXTS: Final = ("abc", "X1", "GB", VALID_LEI)
_BOOLEANS: Final = ("true", "false", "TRUE", "0")
_NUMERIC_TYPES: Final = ("monetary", "percentage", "integer", "decimal")

#: The comparison operators, by the name a rule code carries.
_OPERATORS: Final = (
    ("eq", "="),
    ("ne", "!="),
    ("le", "<="),
    ("lt", "<"),
    ("ge", ">="),
    ("gt", ">"),
)

#: One fact, in ``FACT_SCHEMA`` column order.
_Fact = tuple[str, str | None, str | None, str, str, float | None, str | None, int | None]
#: One reportable cell of a table: (row, column, sheet, data point).
_Cell = tuple[str | None, str, str | None, int]


# =============================================================================
# Public entry points
# =============================================================================


@cache
def corpus_release() -> Release:
    """The packaged PRA001 release as it stood on ``RUN_DATE``, plus three deny entries.

    The Bank's list holds only deactivations for PRA001, and of packaged rules.
    The corpus adds a downgrade of a hand-built Error, a downgrade of one that
    is already a Warning, and a deactivation of the one rule that reads a cell
    nothing else does — so every way the gateway's configuration changes a
    result, and the trace behind it, is on the corpus's path.
    """
    release = resolve_release(MODULE, TAXONOMY, today=RUN_DATE)
    applied = date(2026, 11, 1)
    own = (
        DenyEntry("corpus_icmp_le", MODULE, DENY_DOWNGRADED, applied),
        DenyEntry("corpus_warning", MODULE, DENY_DOWNGRADED, applied),
        DenyEntry("corpus_deactivated", MODULE, DENY_DEACTIVATED, applied),
    )
    denied = replace(release.deny_list, entries=(*release.deny_list.entries, *own))
    return replace(release, deny_list=denied)


@cache
def corpus_rulebook() -> RuleBook:
    """The packaged PRA001 rule book with the hand-built rules after its own.

    After, so the packaged rules' evaluations and the order their cells are
    first read in are what they are without the hand-built ones.
    """
    packaged = corpus_release().rulebook
    assert packaged is not None, f"taxonomy {TAXONOMY} packages no rule book for {MODULE}"
    rules = (*packaged.rules, *hand_built_rules())
    return replace(packaged, rules=rules, file=None, content_sha256="")


@cache
def hand_built_rules() -> tuple[Rule, ...]:
    """The rules no packaged PRA001 rule stands in for.

    Each is evaluated on every corpus return that reports its tables;
    ``designed`` places figures for them. Their codes start ``corpus_``.
    """
    return (
        *_comparison_rules(),
        *_clause_rules(),
        *_turned_away_rules(),
        *_open_axis_rules(),
        *_open_row_rules(),
        *_value_rules(),
        *_not_evaluable_rules(),
    )


@dataclass(frozen=True)
class CorpusReturn:
    """One return of the corpus, and the accuracy it is evaluated at.

    ``accuracy`` is ``None`` for the engine's default. ``open_rows`` states one,
    so every entry point's handling of a caller's accuracy is on the corpus's
    path: a third of its figures state no ``decimals`` of their own.
    """

    ret: CanonicalReturn
    accuracy: Accuracy | None = None


@cache
def build_corpus() -> Mapping[str, CorpusReturn]:
    """Every corpus return by name, in a fixed order. Built once per process."""
    pack = corpus_release().pack
    cells = _cells_by_table(pack)
    return {
        "open_axes": CorpusReturn(_open_axes(pack, cells)),
        "open_rows": CorpusReturn(_open_rows(pack, cells), Accuracy(0, 2)),
        "designed": CorpusReturn(_designed(pack)),
        "wide": CorpusReturn(_wide(pack, cells)),
        "empty": CorpusReturn(_empty(pack)),
    }


def return_from(
    facts: Sequence[_Fact], indicators: Mapping[str, bool] | None = None
) -> CanonicalReturn:
    """A PRA001 return holding ``facts`` in the order given."""
    header = ReturnHeader(VALID_LEI, REFERENCE_DATE, MODULE)
    frame = pl.DataFrame(list(facts), schema=dict(FACT_SCHEMA), orient="row")
    return CanonicalReturn.from_frame(header, frame, indicators)


# =============================================================================
# Private helpers — the hand-built rules
# =============================================================================


def _ref(  # noqa: PLR0913 - one keyword per reference key
    table: str,
    *,
    r: str | None = None,
    c: str | None = None,
    dv: str | None = "0",
    seq: bool = False,
    flt: str | None = None,
    var: str = "v0",
) -> str:
    """One reference in the published syntax, e.g. ``{t: .., c: 0010, dv: 0, seq: False, id: v0}``."""
    parts = [f"t: {table}"]
    for key, value in (("r", r), ("c", c), ("dv", dv), ("filter", flt)):
        if value is not None:
            parts.append(f"{key}: {value}")
    parts.extend((f"seq: {seq}", f"id: {var}", "f: corpus", "fv: corpus"))
    return "{" + ", ".join(parts) + "}"


def _rule(rule_id: str, expression: str, *tables: str, **fields: object) -> Rule:
    """A hand-built rule the module enforces, as an Error unless ``fields`` says otherwise."""
    content: dict[str, object] = {
        "rule_id": rule_id,
        "framework_version": "corpus",
        "expression": expression,
        "severities": {MODULE: "ERROR"},
        "tables": tables,
    }
    return Rule(**{**content, **fields})  # type: ignore[arg-type]


def _matrix(column: str, variable: str, dv: str | None = "0") -> str:
    """One MATRIX column, read row by row."""
    return _ref(MATRIX, c=column, dv=dv, var=variable)


def _comparison_rules() -> tuple[Rule, ...]:
    """Every comparison operator on numbers, on text, and across the two."""
    a, b = _matrix("0010", "v0"), _matrix("0020", "v1")
    since = _ref(DATES, c="0090", dv="CreateDate(1900,01,01)", var="v0")
    until = _ref(DATES, c="0100", dv="CreateDate(1900,01,01)", var="v1")
    number = _ref(MATRIX, r="0010", c="0010")
    name = _ref(ENTITY_DETAILS, r="0020", c="0010", dv='""', var="v1")
    empty_a, empty_c = (
        _matrix("0010", "v0", "emptySequence()"),
        _matrix("0030", "v2", "emptySequence()"),
    )
    return (
        # Exact and with the rounding allowance, once per MATRIX row: `designed`
        # puts a row below, on and above each bound.
        *(_rule(f"corpus_cmp_{code}", f"{a} {op} {b}", MATRIX) for code, op in _OPERATORS),
        *(_rule(f"corpus_icmp_{code}", f"{a} i{op} {b}", MATRIX) for code, op in _OPERATORS),
        # Text is ordered as text: dates before, on and after one another.
        *(_rule(f"corpus_date_{code}", f"{since} {op} {until}", DATES) for code, op in _OPERATORS),
        # A number against text: only `!=` can hold.
        _rule("corpus_mixed_ne", f"{number} != {name}", MATRIX, ENTITY_DETAILS),
        _rule("corpus_mixed_eq", f"{number} = {name}", MATRIX, ENTITY_DETAILS),
        _rule("corpus_mixed_le", f"{number} <= {name}", MATRIX, ENTITY_DETAILS),
        # Booleans have no order: `>=` between two of them never holds.
        _rule("corpus_bool_order", f"isNull({empty_c}) >= isNull({empty_a})", MATRIX),
        # A Warning, which the corpus's deny list "downgrades" all the same.
        _rule("corpus_warning", f"{a} i>= {b}", MATRIX, severities={MODULE: "WARNING"}),
    )


def _clause_rules() -> tuple[Rule, ...]:
    """Where clauses and conditionals: comparisons somewhere other than the top of the rule."""
    a, b, c = _matrix("0010", "v0"), _matrix("0020", "v1"), _matrix("0030", "v2")
    unbound = _matrix("0030", "v2", None)
    nested = f"if {a} i>= {b} then {a} i- {b} i<= {c} else {a} != 0"
    return (
        # Evaluated only on the rows the clause admits, the clause's own
        # comparisons traced under `where`.
        _rule("corpus_where", f"{a} i>= {b}", MATRIX, where=f"{c} > 0 and {a} != 7"),
        # A where-only reference with NO default: no evaluation where it is empty.
        _rule("corpus_where_unbound", f"{a} i<= {b}", MATRIX, where=f"{unbound} >= 2"),
        # A conditional inside a conditional: five branches a comparison can be in.
        _rule("corpus_conditional", f"if {c} > 0 then ({nested}) else {b} >= 0", MATRIX),
        # A conditional does not excuse a reference from needing its cell: with
        # NO default, there is no evaluation where the cell is not reported,
        # though the branch that reads it is not the one taken.
        _rule(
            "corpus_unbound_in_branch",
            f"if {c} > 4 then {_matrix('0020', 'v1', None)} >= 0 else true()",
            MATRIX,
        ),
        _rule(
            "corpus_unbound_sum_in_branch",
            f"if {c} > 4 then count({_ref(MATRIX, c='0020', dv=None, seq=True, var='v1')}) >= 1 "
            "else true()",
            MATRIX,
        ),
    )


def _turned_away_rules() -> tuple[Rule, ...]:
    """A reported cell the rule's formula, or its text, does not admit."""
    a, b = _matrix("0010", "v0"), _matrix("0020", "v1")
    currency = _ref(
        ENTITY_DETAILS, r="0060", c="0010", dv="[Default]", flt=f"this() = [{CURRENCY_NAMED}]"
    )
    start = _ref(ENTITY_DETAILS, r="0040", c="0010", dv="emptySequence()", var="v1")
    first_a = _ref(MATRIX, r="0010", c="0010")
    first_b = _ref(MATRIX, r="0010", c="0020", var="v1")
    closed = frozenset({MATRIX_DIMENSION})
    return (
        # The formula closes, for v1 alone, a dimension MATRIX's sector rows
        # carry: there v1's reported cell is turned away and read at its default.
        _rule("corpus_shut_variable", f"{a} i= {b}", MATRIX, closed_by_variable={"v1": closed}),
        # ... and with NO default there is no evaluation where the cell is
        # turned away, in whichever branch it is read.
        _rule(
            "corpus_shut_unbound_in_branch",
            f"if {_matrix('0030', 'v2')} > 4 then {_matrix('0020', 'v1', None)} >= 0 else {a} >= 0",
            MATRIX,
            closed_by_variable={"v1": closed},
        ),
        # ... and for every variable of a rule that reads one sector row:
        # nothing can bind, and the rule is not evaluated.
        _rule("corpus_shut_rule", f"{first_a} i= {first_b}", MATRIX, closed=closed),
        # A filter on the cell's own value: a reported cell holding another
        # member is not the cell the rule names. Run regardless, and then
        # beside a second cell that gives it a place.
        _rule(
            "corpus_value_filter",
            f"{currency} != [{CURRENCY_NAMED}]",
            ENTITY_DETAILS,
            always_execute=True,
        ),
        _rule(
            "corpus_value_filter_beside",
            f"if not(isNull({start})) then {currency} = [{CURRENCY_NAMED}] else true()",
            ENTITY_DETAILS,
        ),
    )


def _open_axis_rules() -> tuple[Rule, ...]:
    """What a rule without a formula does on an open sheet axis."""
    total_only = f"dim(this(), [{GEO_DIMENSION}]) = [{GEO_TOTAL}]"
    total = _ref(GEO_EXPOSURES, r="0170", c="0010")
    parts = _ref(
        GEO_EXPOSURES, r="0010; 0020; 0030", c="0010", dv="emptySequence()", seq=True, var="v1"
    )
    of_total = _ref(GEO_EXPOSURES, r="0170", c="0010", flt=total_only, var="v1")
    of_others = _ref(GEO_EXPOSURES, r="0170", c="0010", flt=f"not({total_only})")
    reported = _ref(GEO_EXPOSURES, r="0170", c="0010", dv="emptySequence()")
    every = _ref(GEO_EXPOSURES, r="0170", c="0010", dv="emptySequence()", seq=True)
    return (
        # "Row 0170 is the sum of rows 0010 to 0030", country by country: the
        # summed reference is lined up with the total's country, and reads a
        # member-less fact at every country.
        _rule("corpus_stray_sum", f"{total} i= isum({parts})", GEO_EXPOSURES),
        # A single cell beside a NAMED member ranges over the members by itself.
        _rule("corpus_named_member", f"{total} i<= {of_total}", GEO_EXPOSURES),
        _rule("corpus_excluded_member", f"{of_others} i<= {of_total}", GEO_EXPOSURES),
        # ... and a summed one takes every member at once.
        _rule("corpus_all_members", f"isum({every}) i>= {of_total}", GEO_EXPOSURES),
        # dim() of a cell on the open axis is the member its sheet is.
        _rule(
            "corpus_dim_of_sheet",
            f"dim({reported}, [{GEO_DIMENSION}]) != [{GEO_TOTAL}]",
            GEO_EXPOSURES,
        ),
        # ... also of a cell the formula turns away: dim() asks only whether
        # the cell is reported. (An open dimension is one its cells carry.)
        _rule(
            "corpus_dim_of_shut_cell",
            f"dim({reported}, [{GEO_DIMENSION}]) != [{GEO_TOTAL}] "
            f"and {_ref(GEO_EXPOSURES, r='0010', c='0010', var='v1')} >= 0",
            GEO_EXPOSURES,
            closed_by_variable={"v0": frozenset({GEO_DIMENSION})},
        ),
    )


def _open_row_rules() -> tuple[Rule, ...]:
    """Open-row shapes no packaged PRA001 rule reads."""
    rating = _ref(RATINGS, c="0006", dv='""')
    ratings = _ref(RATINGS, c="0006", dv="emptySequence()", seq=True)
    trades = _ref(COUNTERPARTIES, c="0070")
    at_risk = _ref(DAILY_VAR, c="0020", var="v1")
    return (
        # Open rows UNDER an open sheet axis, one row at a time and summed: a
        # row with no member on the axis is at a place of another shape.
        _rule("corpus_rows_under_open_axis", f"StringLength({rating}) > 2", RATINGS),
        _rule("corpus_rows_counted_under_open_axis", f"count({ratings}) >= 3", RATINGS),
        # A join that names one table's row key by ANOTHER dimension: the
        # counterparty key goes by the name of the VaR table's key, which sorts
        # before the counterparty table's other key and not after it.
        _rule(
            "corpus_join_alias",
            f"{trades} i>= {at_risk}",
            COUNTERPARTIES,
            DAILY_VAR,
            join=f"join(dim({trades}, [eba_dim:CPT]) = dim({at_risk}, [boe_dim:UDI]))",
        ),
    )


def _value_rules() -> tuple[Rule, ...]:
    """Values the packaged rules never produce on these returns: empty, a sequence, a zero divisor."""
    a, b = _matrix("0010", "v0"), _matrix("0020", "v1")
    empty_c = _matrix("0030", "v2", "emptySequence()")
    each_c = _ref(MATRIX, c="0030", dv="emptySequence()", seq=True, var="v2")
    some_c = _ref(MATRIX, r="0010; 0020; 0040", c="0030", dv="emptySequence()", seq=True, var="v2")
    name = _ref(ENTITY_DETAILS, r="0020", c="0010", dv='""')
    twice = _ref(OWN_FUNDS, r="0050; 0060", c="0010")
    again = _ref(OWN_FUNDS, r="0580; 5870", c="0020")
    lone = _ref(UNRULED, r="0010", c="0010", dv='""')
    empties = (
        f"iabs({empty_c}) i>= 0",
        f"imax({empty_c}) i>= 0",
        f"exp({empty_c}, 1, 2) >= 0",
        f'matches({empty_c}, "x")',
        f"{empty_c} i+ {a} i>= {b}",
    )
    return (
        # A divisor of zero: no evaluation.
        _rule("corpus_divide", f"{a} / {b} >= 1", MATRIX),
        _rule("corpus_idivide", f"{a} i/ {b} i<= 1", MATRIX),
        # A summed reference with a zero default, read row by row.
        _rule(
            "corpus_sum_default",
            f"isum({_ref(MATRIX, c='0030', seq=True, var='v2')}) i>= {a} i- {b}",
            MATRIX,
        ),
        # A sequence used as a number: one item is that item, none or several is nothing.
        _rule("corpus_sequence_compared", f"{each_c} >= {a}", MATRIX),
        _rule("corpus_sequence_on_right", f"{a} <= {each_c}", MATRIX),
        _rule("corpus_sequence_added", f"{each_c} i+ {a} i>= {b}", MATRIX),
        _rule("corpus_sequence_span", f"{some_c} = 3", MATRIX),
        # Every function handed nothing.
        _rule("corpus_empty_operands", " or ".join(empties), MATRIX),
        _rule(
            "corpus_text_functions",
            f'StringLength({name}) > 3 and matches({name}, "^Corpus")',
            ENTITY_DETAILS,
        ),
        # Rows named with no column, and a table named with neither.
        _rule(
            "corpus_rows_only",
            f"{_ref(MATRIX, r='0010')} i>= {_ref(MATRIX, r='0020', var='v1')}",
            MATRIX,
        ),
        _rule("corpus_any_cell", f"{_ref(MATRIX, dv=None)} > -100", MATRIX),
        # Two rows that show ONE data point: the second place reads the same
        # fact. In the first pair `designed` reports both rows, in the second
        # only one, and the other is shown its figure.
        _rule("corpus_twice_shown", f"{twice} i>= 0", OWN_FUNDS),
        _rule("corpus_shown_again", f"{again} i>= 0", OWN_FUNDS),
        # The corpus's deny list deactivates this one; nothing else reads its cell.
        _rule("corpus_deactivated", f"StringLength({lone}) > 0", UNRULED),
    )


def _not_evaluable_rules() -> tuple[Rule, ...]:
    """One rule for each way a rule cannot be evaluated."""
    a, b = _matrix("0010", "v0"), _matrix("0020", "v1")
    elsewhere = _ref("NOT.A.TABLE", r="0010", c="0010")
    foreign = _ref(MATRIX, c="0010", flt=f"dim(this(), [{GEO_DIMENSION}]) = [{GEO_TOTAL}]")
    key = f"{{d: [{GEO_DIMENSION}], dv: emptySequence(), seq: False, id: v0}}"
    c = _matrix("0030", "v2")
    return (
        _rule("corpus_unparsable", f"{a} i>=", MATRIX),
        _rule("corpus_unknown_table", f"{elsewhere} >= 0", "NOT.A.TABLE"),
        _rule("corpus_unlisted_table", f"{elsewhere} >= 0", MATRIX),
        _rule("corpus_unknown_function", f"foo({a}) > 0", MATRIX),
        _rule("corpus_wrong_arity", f"isum({a}, {b}) > 0", MATRIX),
        _rule("corpus_dimension_reference", f"{key} != [{GEO_TOTAL}]", MATRIX),
        _rule("corpus_foreign_filter", f"{foreign} >= 0", MATRIX),
        _rule("corpus_dim_of_number", f"dim({a} i+ 1, [{GEO_DIMENSION}]) != [{GEO_TOTAL}]", MATRIX),
        # Unsupported only where column 0030 exceeds 4: the rows before that
        # one are evaluated, and traced, before the rule is found unevaluable.
        _rule(
            "corpus_dim_without_dimension",
            f"if {c} > 4 then dim({a}, 5) != [{GEO_TOTAL}] else true()",
            MATRIX,
        ),
    )


# =============================================================================
# Private helpers — the returns
# =============================================================================


class _Dice:
    """Seeded choices drawn from ``random.Random.random()`` alone (see the module docstring)."""

    def __init__(self, seed: int) -> None:
        self._random = random.Random(seed)  # noqa: S311 - test data, not a secret

    def chance(self, probability: float) -> bool:
        return self._random.random() < probability

    def index(self, length: int) -> int:
        return int(self._random.random() * length)

    def pick[T](self, items: Sequence[T]) -> T:
        return items[self.index(len(items))]

    def shuffled[T](self, items: Sequence[T]) -> list[T]:
        keyed = [(self._random.random(), position) for position in range(len(items))]
        return [items[position] for _key, position in sorted(keyed)]


def _cells_by_table(pack: TaxonomyPack) -> Mapping[str, list[_Cell]]:
    """Each table's reportable cells, in the pack's own order."""
    found: dict[str, list[_Cell]] = {}
    for table, row, column, sheet, datapoint in pack.cells.select(
        "table", "row", "column", "sheet", "datapoint"
    ).iter_rows():
        found.setdefault(table, []).append((row, column, sheet, datapoint))
    return found


def _value(
    pack: TaxonomyPack, dice: _Dice, datapoint: int, *, zeros: float, faults: float = 0.0
) -> tuple[float | None, str | None, int | None]:
    """A (value, text, decimals) of the cell's type; with ``faults``, sometimes of the wrong one."""
    metric = pack.metrics.get(pack.datapoints[datapoint].metric)
    kind = metric.data_type if metric is not None else ""
    if kind in _NUMERIC_TYPES:
        if dice.chance(faults):
            return None, "not a number", None
        number = 0.0 if dice.chance(zeros) else dice.pick(_NUMBERS)
        return number, None, dice.pick(_DECIMALS)
    if dice.chance(faults):
        return (None, "junk", None) if dice.chance(0.5) else (1.0, None, None)
    if kind == "boolean":
        return None, dice.pick(_BOOLEANS), None
    if kind == "date":
        return None, dice.pick(_DATES), None
    members = pack.enumerations.get(metric.enumeration or "", ()) if metric is not None else ()
    if kind == "enumeration" and members:
        member = dice.pick(members)
        return None, member if dice.chance(0.5) else _local(member), None
    return None, dice.pick(_TEXTS), None


def _local(qname: str) -> str:
    return qname.rsplit(":", 1)[-1]


def _open_axes(pack: TaxonomyPack, cells: Mapping[str, list[_Cell]]) -> CanonicalReturn:
    """Open sheet axes: countries both ways, a default sheet, and member-less strays."""
    dice = _Dice(SEED + 1)
    facts: list[_Fact] = []
    for table in (GEO_EXPOSURES, GEO_IRB):
        skipped = STRAY_ONLY_COLUMNS[table]
        for country, share in zip(COUNTRIES, _COUNTRY_SHARES, strict=True):
            for row, column, _sheet, datapoint in cells[table]:
                if column != skipped and dice.chance(share):
                    value, text, decimals = _value(pack, dice, datapoint, zeros=0.75)
                    facts.append((table, None, country, str(row), column, value, text, decimals))
    for table, members, share in (
        ("C09.04.01.01", ("x1", "eba_GA:GB", "FR"), 1.0),
        ("C33.00.01.01", ("eba_GA:x1", "GB", "eba_GA:DE"), 0.15),
        ("C33.00.01.02", ("GB",), 1.0),
        # No key at all is the default sheet here; so is the default's own name, below.
        (DEFAULT_SHEET, (None, "x10002", "eba_TA:x132"), 0.8),
    ):
        for member in members:
            for row, column, _sheet, datapoint in cells[table]:
                if dice.chance(share):
                    value, text, decimals = _value(pack, dice, datapoint, zeros=0.6)
                    facts.append((table, None, member, str(row), column, value, text, decimals))
    facts.extend((DEFAULT_SHEET, None, "x0", row, "0010", 9.0, None, 0) for row in ("0010", "0020"))
    # One country written BOTH ways on the same cells: two facts, one cell to the engine.
    facts.extend(
        (GEO_EXPOSURES, None, "eba_GA:GB", row, "0010", 40.0 + index, None, 0)
        for index, row in enumerate(("0010", "0020", "0170"))
    )
    # A key the axis does not have — a bare code, and a known code under an
    # unknown prefix — is still a place to the engine.
    facts.extend(
        (GEO_EXPOSURES, None, key, row, "0010", 3.0, None, 0)
        for key in ("ZZ9", "foo:GB")
        for row in ("0010", "0170")
    )
    # What boe_b0816 and boe_b0190 read beside the open-axis tables.
    facts.extend(
        [
            (CLASS_TOTALS, "0002", None, "0080", "0020", 4.0, None, 0),
            (CLASS_TOTALS, "0010", None, "0080", "0020", 6.0, None, 0),
            ("OF07.00.01.01", "0002", None, "0010", "0010", 1.0, None, 0),
        ]
    )
    for stray in _strays(pack, dice, cells):
        facts.insert(dice.index(len(facts) + 1), stray)
    return return_from(facts)


def _strays(pack: TaxonomyPack, dice: _Dice, cells: Mapping[str, list[_Cell]]) -> list[_Fact]:
    """Facts with no member on an axis with no default sheet: a blank country cell."""
    strays: list[_Fact] = []
    for table, count in STRAYS.items():
        skipped = STRAY_ONLY_COLUMNS.get(table)
        # Where the summed rules read, and at the column no country reports.
        wanted = [cell for cell in cells[table] if cell[1] in ("0010", "0050", skipped)]
        for row, column, _sheet, datapoint in dice.shuffled(wanted)[:count]:
            value, text, decimals = _value(pack, dice, datapoint, zeros=0.3)
            strays.append((table, None, None, str(row), column, value, text, decimals))
    # The same blank cell twice, alike in every column (see the module docstring).
    return [*strays, strays[0]]


def _open_rows(pack: TaxonomyPack, cells: Mapping[str, list[_Cell]]) -> CanonicalReturn:
    """Open-row tables: several rows per sheet, with a duplicate key and a missing one."""
    dice = _Dice(SEED + 2)
    facts: list[_Fact] = []
    # (table, rows per sheet, share of columns, the columns kept or None for all)
    plans: tuple[tuple[str, Mapping[str | None, int], float, tuple[str, ...] | None], ...] = (
        (GRADES, {"0001": MANY_GRADES}, 1.0, ("0020", "0040", "0050", "0060", "0070", "0110")),
        (GRADES, {"0002": 6, "0006": 5}, 0.9, None),
        (COUNTERPARTIES, {None: 6}, 1.0, None),
        ("C14.00.01.01", {None: 5}, 0.9, None),
        ("C14.01.01.01", {"0010": 5, "0020": 3, "0040": 2}, 0.9, None),
        ("C06.02.01.01", {None: 5}, 0.9, None),
        ("C32.03.01.01", {None: 4}, 1.0, None),
        ("C32.04.01.01", {None: 4}, 1.0, None),
        ("OF08.05.01.01", {"0001": 4, "0002": 3}, 1.0, None),
        ("OF24.03.01.03", {None: 5}, 1.0, None),
        (DAILY_VAR, {None: 5}, 1.0, ("0020", "0030", "0040")),
        ("OF25.03.01.04", {None: 4}, 1.0, None),
        ("OF25.03.01.06", {None: 3}, 1.0, None),
    )
    for table, rows_by_sheet, share, columns in plans:
        facts.extend(_row_facts(pack, dice, cells, table, rows_by_sheet, share, columns))
    # Open rows under an open sheet axis: a member both ways, and none.
    for member in ("eba_EN:x267", "x268", None):
        facts.extend(_row_facts(pack, dice, cells, RATINGS, {"0001": 3}, 1.0, None, member))
    # The class totals the grades are summed against ...
    for sheet in ("0001", "0002", "0006"):
        for row, column, cell_sheet, datapoint in cells[CLASS_TOTALS]:
            if cell_sheet == sheet and (row == "0070" or dice.chance(0.08)):
                value, text, decimals = _value(pack, dice, datapoint, zeros=0.5)
                facts.append((CLASS_TOTALS, sheet, None, str(row), column, value, text, decimals))
    # ... and the two dates boe_b0917 holds each row's key between.
    facts.extend(
        (ENTITY_DETAILS, None, None, row, "0010", None, day, None)
        for row, day in (("0040", "2026-12-31"), ("0050", "2027-03-31"))
    )
    # Two breaks that exist only at THIS return's accuracy, one inside a known
    # issue's footprint (PI-24 on boe_b0735: sheets 0002 and 0010) and one
    # outside it (sheet 0006): 5 against 100, neither stating its decimals, is
    # within the default allowance of 500 a side and far outside this return's
    # 0.5. A label pass that forgot the caller's accuracy would find no break
    # to classify here.
    facts.extend(
        (table, sheet, None, "0010", column, value, None, None)
        for sheet in FOOTPRINT_SHEETS
        for table, column, value in (
            ("OF08.01.01.02", "0100", 5.0),
            ("OF08.03.01.01", "0020", 100.0),
        )
    )
    return return_from(facts)


def _row_facts(  # noqa: PLR0913 - one table's plan
    pack: TaxonomyPack,
    dice: _Dice,
    cells: Mapping[str, list[_Cell]],
    code: str,
    rows_by_sheet: Mapping[str | None, int],
    share: float,
    columns: tuple[str, ...] | None,
    member: str | None = None,
) -> list[_Fact]:
    """``code``'s rows: each a key per key column, then its data columns.

    On a sheet of four rows or more the last row repeats the first row's key
    and the one before it has no key at all.
    """
    table = pack.tables[code]
    facts: list[_Fact] = []
    for sheet, count in rows_by_sheet.items():
        odd = count >= 4  # noqa: PLR2004 - see the docstring
        for index in range(count):
            row = f"r{index:03d}"
            keyed = 0 if odd and index == count - 1 else index
            if not (odd and index == count - 2):
                for key in table.open_keys:
                    value, text = _key(key, keyed)
                    facts.append((code, sheet, member, row, key.code, value, text, None))
            for _row, column, cell_sheet, datapoint in cells[code]:
                if cell_sheet != sheet or (columns is not None and column not in columns):
                    continue
                if dice.chance(share):
                    value, text, decimals = _value(pack, dice, datapoint, zeros=0.5)
                    facts.append((code, sheet, member, row, column, value, text, decimals))
    return facts


def _key(key: OpenKey, index: int) -> tuple[float | None, str | None]:
    """Row ``index``'s value for one key column, in the forms a source writes it.

    A number key alternates between a number and text; a member key between
    its QName and its local name.
    """
    if key.members:
        member = key.members[index % len(key.members)]
        return None, member if index % 2 == 0 else _local(member)
    if key.typed_type == "integer":
        return (float(index + 1), None) if index % 2 == 0 else (None, str(index + 1))
    if key.typed_type == "date":
        return None, _DATES[index % len(_DATES)]
    return None, f"K{index:03d}"


def _designed(pack: TaxonomyPack) -> CanonicalReturn:
    """Hand-placed figures for ``hand_built_rules``; see the comment beside each block."""
    facts: list[_Fact] = []
    rows = pack.tables[MATRIX].row_codes
    # MATRIX column 0010 less column 0020, row by row. With decimals 0 each side
    # allows 0.5, so `i=` holds within 1 and the bounds are -1, 0 and 1.
    for row, difference in zip(rows, (-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0), strict=False):
        facts.append((MATRIX, None, None, row, "0010", 10.0 + difference, None, 0))
        facts.append((MATRIX, None, None, row, "0020", 10.0, None, 0))
    # Then only the left side; a zero against a three, which `corpus_shut_variable`
    # reads as a zero against nothing; and only the right side, on the one row
    # whose cells that rule's formula admits.
    facts.extend(
        [
            (MATRIX, None, None, rows[7], "0010", 7.0, None, 0),
            (MATRIX, None, None, rows[8], "0010", 0.0, None, 0),
            (MATRIX, None, None, rows[8], "0020", 3.0, None, 0),
            (MATRIX, None, None, rows[9], "0020", 5.0, None, 0),
        ]
    )
    # Column 0030 is what the where clauses and the conditional read: positive,
    # zero, and — on the third and ninth rows — not reported.
    thirds = (1.0, 0.0, None, 2.0, 3.0, 0.0, 5.0, 2.0, None, 1.0)
    facts.extend(
        (MATRIX, None, None, row, "0030", value, None, 0)
        for row, value in zip(rows, thirds, strict=True)
        if value is not None
    )
    # Dates: before, equal, after, then one side missing each way.
    pairs = (
        ("0020", "2027-01-01", "2027-06-30"),
        ("0030", "2027-03-31", "2027-03-31"),
        ("0040", "2027-06-30", "2027-01-01"),
        ("0050", "2027-03-31", None),
        ("0060", None, "2027-03-31"),
    )
    for row, since, until in pairs:
        facts.extend(
            (DATES, None, None, row, column, None, day, None)
            for column, day in (("0090", since), ("0100", until))
            if day is not None
        )
    # The entity details: a currency that is NOT the one the value-filter rules
    # name, written by local name; a name; and the two dates.
    facts.extend(
        (ENTITY_DETAILS, None, None, row, "0010", None, text, None)
        for row, text in (
            ("0060", _local(CURRENCY_REPORTED)),
            ("0020", "Corpus Bank plc"),
            ("0040", "2027-01-01"),
            ("0050", "2027-03-31"),
        )
    )
    # One country and one blank: the smallest input for `corpus_stray_sum`.
    facts.extend(
        (GEO_EXPOSURES, None, member, row, "0010", value, None, 0)
        for member, row, value in (
            ("GB", "0010", 1.0),
            ("GB", "0020", 2.0),
            (None, "0020", 4.0),
            ("GB", "0170", 3.0),
        )
    )
    facts.extend(
        [
            # One data point in two rows of OF 02.00 with two values, the later
            # row listed first: OF 07.00, which shows it too, is given the
            # figure of the first cell by coordinate, not the first listed.
            (OWN_FUNDS, None, None, "0060", "0010", 99.0, None, 0),
            (OWN_FUNDS, None, None, "0050", "0010", 12.0, None, 0),
            # Shown again in row 0580 of the same table.
            (OWN_FUNDS, None, None, "5870", "0020", 7.0, None, 0),
            # What boe_b0599 reads: a quotient, a logarithm and Euler's constant.
            ("OF16.00.01.03", None, None, "0010", "0010", 100.0, None, 0),
            ("OF16.00.01.05", None, None, "0050", "0110", 5.0, None, 0),
            ("OF16.00.01.06", None, None, "0010", "0010", 0.5, None, 4),
            (UNRULED, None, None, "0010", "0010", None, "only one rule reads this", None),
            # A number where the cell takes text: not a value the rules can read.
            (ENTITY_DETAILS, None, None, "0070", "0010", 5.0, None, None),
            # Declared NOT filed, below, though it holds a fact.
            ("OF25.03.01.03", None, None, "0010", "0010", 1.0, None, 0),
        ]
    )
    # Declared, not inferred. OF 07.00 and OF 24.03 are filed with no fact at
    # all: the first is shown OF 02.00's figure, the second leaves boe_b0917's
    # dim() nothing to read.
    filed = {facts_table for facts_table, *_rest in facts} | {"OF07.00.01.01", "OF24.03.01.03"}
    indicators = {pack.tables[code].filing_indicator: True for code in sorted(filed)}
    indicators[pack.tables["OF25.03.01.03"].filing_indicator] = False
    return return_from(facts, indicators)


def _wide(pack: TaxonomyPack, cells: Mapping[str, list[_Cell]]) -> CanonicalReturn:
    """A seeded random return over most of the module, every template declared filed."""
    dice = _Dice(SEED + 4)
    facts: list[_Fact] = []
    for code in sorted(pack.tables):
        table = pack.tables[code]
        if table.open_rows or not dice.chance(0.65):
            continue
        share = min(0.6, dice.pick((30, 60, 150)) / len(cells[code]))
        zeros = dice.pick((0.3, 0.8, 1.0))
        axis = table.open_axis
        members: tuple[str | None, ...] = (None,)
        if axis is not None:
            # A member by QName, one by local name and - where no key is not
            # itself a sheet - facts with no member at all.
            keyed = (axis.members[1], _local(axis.members[2]))
            members = keyed if axis.default_allowed else (*keyed, None)
        for member in members:
            for row, column, sheet, datapoint in cells[code]:
                if not dice.chance(share):
                    continue
                value, text, decimals = _value(pack, dice, datapoint, zeros=zeros, faults=0.02)
                # A code that lost its leading zeros in a spreadsheet.
                written = (str(row).lstrip("0") or "0") if dice.chance(0.03) else str(row)
                facts.append((code, sheet, member, written, column, value, text, decimals))
    for code in sorted(pack.tables):
        if pack.tables[code].open_rows and dice.chance(0.5):
            sheets = sorted({sheet for _row, _column, sheet, _point in cells[code]}, key=str)[:2]
            plan = {sheet: 2 + dice.index(3) for sheet in sheets}
            facts.extend(_row_facts(pack, dice, cells, code, plan, 0.5, None))
    # A table and a row the module does not have.
    facts.extend(
        [
            ("NOT.A.TABLE", None, None, "0010", "0010", 1.0, None, None),
            (MATRIX, None, None, "9999", "0010", 1.0, None, None),
        ]
    )
    declared = sorted({table.filing_indicator for table in pack.tables.values()})
    return return_from(dice.shuffled(facts), dict.fromkeys(declared, True))


def _empty(pack: TaxonomyPack) -> CanonicalReturn:
    """Two templates declared filed, and no fact: nothing for any rule to read."""
    declared = {pack.tables[code].filing_indicator: True for code in (GEO_EXPOSURES, MATRIX)}
    return return_from([], declared)
