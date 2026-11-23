"""
Scaling gate for the Bank of England rule engine: cost in the size of an open axis or open rows.

Pipeline position:
    CanonicalReturn + TaxonomyPack + rules  ->  boe.engine.evaluate_rules / trace_rules
    This file drives the engine directly on PRA001 returns built from the
    packaged v4.1.1 taxonomy pack, each at two sizes: countries on OF 09.01 /
    OF 09.02, or obligor grades on OF 08.02.

Key responsibilities:
- Pin the ASYMPTOTIC SHAPE of rule evaluation in the number of members a
  return reports on an open sheet axis (countries on OF 09.01 / OF 09.02), not a
  single wall-clock number, so an evaluation that goes quadratic in the axis
  fails here rather than in a reporter's run.
- Pin the same shape where a FEW cells have no country at all, in the rows of
  an open-row table, and for a TRACE (what evidence and a comparison of two
  returns are made from), and the cost of indexing a return whose countries are
  written by their code alone (``DE``).
- Carry the verdict on a count of function calls where one sees the defect: it
  reads no clock, so a loaded box or a parallel test run cannot move it. CPU
  time is the second line, for the cost a count cannot see (a scan inside a
  comprehension makes no call).
- Keep the measured path live: assert the summed rules both run and run once per
  column and country, so the timing is not measuring blocked or empty rules
  (LESSONS B4 / C11).

The escape this closes
----------------------
Each rule of the form "row total = isum(listed rows)" over OF 09.01 / OF 09.02
(``boe_b0730``, ``boe_b0731``, ``boe_b0783``, ``boe_b0785``, ``boe_b0786``) is
evaluated once per column and country, and its summed reference reads the listed
rows at that column and country. The engine used to find those cells by
scanning every cell the reference could read, at every evaluation, and joined
the references' places pair by pair. Both evaluations and cells grow with the
country count, so the cost grew with its square: on the ``rich`` portfolio with
its country facts copied out, the whole PRA001 rule book took 0.2 s at 2
countries, 12 s at 100 and 49 s at 200. Every fixture return reports at most two
countries, where the cost is invisible, so no gate measured it.

Why a RATIO and not only an absolute budget
-------------------------------------------
The same reasoning as ``tests/unit/classifier/test_p1_320_qrre_aggregate_scaling.py``
at the root: an absolute threshold measures this box on this day and has to be
loose enough for a loaded CI worker; the defect is a change of SHAPE, and a
ratio across two sizes measures shape. The budget is a coarse second line.

Measured 2026-11-20 by the clock (``time.perf_counter``, best of 3, in a 4-core
Linux container) on this file's return, the 44 rules that read OF 09.01 / OF
09.02 alone — before this gate read function calls and CPU time (see the table
under "Open rows, and tracing" for those):

=================  ===============  ==================
countries          scan (defect)    indexed (fixed)
=================  ===============  ==================
10                 1.15 - 1.22 s    0.20 - 0.22 s
40                 16.1 - 17.6 s    0.73 - 0.87 s
ratio (4x)         13.2x - 14.4x    3.7x - 4.0x
=================  ===============  ==================

so ``MAX_SCALING_RATIO = 8.0`` sits close to the geometric midpoint, with about
2x headroom below it for the fixed form and about 1.7x above it for the defect.

The second escape: a few blank country cells
--------------------------------------------
The 2026-11-20 fix indexed a summed reference's cells by place, and fell back to
the scan where the places have two shapes. A cell with NO country — a blank
country column in a few rows of a CSV, the input error validation exists to
report — has a place that leaves the country out, so one such cell under a
summed reference put every evaluation of the rule back on the scan; and the
step that drops a place another place extends compared every pair of places.
Twenty such cells per table (forty facts) were enough. No fixture return held
one, and at this file's first sizes (10 and 40 countries) the ratio stayed under
the limit above.

Measured 2026-11-22 on this file's blank-country return (the five summed rules;
calls are cProfile's total, CPU is ``time.thread_time``, best of 3):

=====================  ====================  ====================  =============
countries              calls, defect         CPU, defect           CPU, fixed
=====================  ====================  ====================  =============
30                     1,443,829             0.35 s                0.16 s
120                    8,662,737             4.91 s                0.62 s
ratio (4x)             6.00x                 13.9x                 3.2x - 3.9x
=====================  ====================  ====================  =============

The fixed engine makes 3.82x the calls. The two halves of the defect are seen
by different lines, so neither assertion is a spare: the pairwise comparison of
places makes calls (5.65x with only it left in), while the scan is a
comprehension, which makes none (3.79x the calls with only it left in), and is
seen by CPU time alone (10.3x - 11.9x).

Indexing 40 countries from the END of the country list (a return holding no
rule at all, so the index is all that is measured) took 455,568 calls and
0.13 s with the keys written as QNames, and 10,826,448 calls and 0.50 s written
as local names (23.8x the calls), because each fact's key was looked for by
walking the member list; fixed, 501,405 calls and about 0.085 s either way.

Open rows, and tracing
----------------------
Two shapes no fixture return held, both measured linear (P6.60 a): the rows of
an open-row table, and a trace. These gates are ratchets on a property that
holds, so that a later per-evaluation search fails here first. The open-row
return is every cell of OF 08.02 for N obligor grades on four of its sheets,
beside OF 08.01's class totals declared filed with no figure: of the 72 rules
that read the grades, 20 run grade by grade and 52 sum every grade. The trace is
of the five summed rules, which read a total cell and a summed side at every
column and country.

Measured 2026-11-22: calls are cProfile's total; CPU is ``time.thread_time``,
best of 3, over two to three runs. "Before" is the engine as the blank-country
fix left it, "after" with each selector's look-up worked out once per rule and
each cell looked up once per place:

==============================  ===============  ===============  ============
gate (4x the input)             calls, before    calls, after     CPU, after
==============================  ===============  ===============  ============
countries, evaluate (10 / 40)   3.78x (6.94M)    3.68x (4.73M)    4.0x - 4.3x
blank cells, evaluate (30/120)  3.82x (5.72M)    3.76x (4.19M)    3.6x - 4.4x
grades, evaluate (20 / 80)      3.52x (4.46M)    3.33x (3.05M)    3.2x - 4.8x
countries, trace (10 / 40)      3.62x (2.36M)    3.50x (1.71M)    3.2x - 4.0x
==============================  ===============  ===============  ============

(calls at the larger size in brackets.) Each call line was seen red on the
engine with one per-evaluation search put back: placing every cell a summed
reference could read, for the one-shape look-up (13.73x the calls, countries);
trying every row of the sheet for a row's key (10.18x, grades); placing every
cell a summed side could read, to trace it (13.97x, trace). The CPU line is the
coarser one here: the same search of the rows inside a generator, which makes
no counted call, cost under 0.1 s at 80 grades and passed both lines (3.36x the
calls, 3.93x the CPU) — at these sizes a per-row search is seen only where it
calls.

References:
- Bank of England Banking Taxonomy v4.1.1 (PRA001) — OF 09.01 / OF 09.02 and
  their validation rules
- docs/development/escape-log.md, 2026-11-20
- docs/plans/rwa-filer-performance-review-2026-11-22.md, items 4 and 5, and
  engine-07 (P6.60 a)
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from datetime import date
from functools import cache
from typing import TYPE_CHECKING

import polars as pl

from pack_builders import VALID_LEI
from rwa_filer.boe.engine import STATUS_FAIL, STATUS_PASS, evaluate_rules, trace_rules
from rwa_filer.boe.grammar import references
from rwa_filer.model import FACT_SCHEMA, CanonicalReturn, ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate.structure import local_name

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from types import FrameType

    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.boe.engine import RuleResult
    from rwa_filer.release import Release

MODULE = "PRA001"
TAXONOMY = "4.1.1"
#: The two geographical-breakdown tables, each with an open country axis.
TABLES = ("OF09.01.01.01", "OF09.02.01.01")
#: Rules of the "total = isum(listed rows)" shape, iterated per column and country.
SUMMED_RULES = ("boe_b0730", "boe_b0731", "boe_b0783", "boe_b0785", "boe_b0786")

SMALL = 10
LARGE = 40
#: Linear cost gives about 4x for 4x the countries, quadratic about 16x.
MAX_SCALING_RATIO = 8.0
#: A coarse second line at LARGE countries; the ratio is the guard.
BUDGET_SECONDS = 5.0
REPEATS = 3

#: Linear cost gives 4x the function calls for 4x the countries, less the part
#: that does not grow; anything above this has a term in their square.
MAX_CALL_RATIO = 4.4
#: The blank-country case is measured where the unfixed engine is clear of the
#: limit on both lines (6.0x the calls, 13.9x the CPU time).
BLANK_SMALL = 30
BLANK_LARGE = 120
#: The cells reported with NO country, per table: (rows, columns). Twenty a
#: table — a few blank cells, not a copy of it. They sit on each summed rule's
#: total row AND on a row it sums, at columns its scope lists, so both of the
#: rule's references hold a place that names no country.
BLANK_CELLS: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "OF09.01.01.01": (("0170", "0010", "0140", "0141"), ("0010", "0050", "0055", "0060", "0061")),
    "OF09.02.01.01": (("0150", "0030", "0060", "0042", "0071"), ("0010", "0030", "0040", "0050")),
}
BLANK_PER_TABLE = 20
#: Writing a country by its code alone may cost this much more to index, in
#: function calls and in CPU time. It costs the same; a walk of the member list
#: per fact cost 23.8x the calls and 3.9x the time.
MAX_SPELLING_CALL_RATIO = 1.1
MAX_SPELLING_CPU_RATIO = 2.5
#: The open-row case: the obligor grades of OF 08.02, one row per grade, on four
#: of its exposure-class sheets, beside the class totals of OF 08.01 they are
#: summed against — declared filed with no figure, so that everything reported
#: grows with the rows.
GRADES = "OF08.02.01.01"
CLASS_TOTALS = "OF08.01.01.01"
GRADE_SHEETS = ("0001", "0002", "0006", "0009")
ROWS_SMALL = 20
ROWS_LARGE = 80


def test_rule_evaluation_scales_linearly_in_the_number_of_countries() -> None:
    """Four times the countries: under 4.4x the function calls and under 8x the CPU time."""
    # Arrange
    release = _release()
    rules = _rules()
    small, large = _geographical_return(SMALL), _geographical_return(LARGE)

    # Adequacy: the summed rules run, once per column and country, at both sizes.
    small_results = _summed(evaluate_rules(small, release.pack, rules))
    large_results = _summed(evaluate_rules(large, release.pack, rules))
    missing = sorted(set(SUMMED_RULES) - set(small_results))
    assert not missing, (
        f"summed rule(s) {missing} not in the rule book - the return no longer exercises "
        "the path this test times"
    )
    for rule_id in SUMMED_RULES:
        assert small_results[rule_id].status == STATUS_PASS, (
            f"{rule_id} was not evaluated ({small_results[rule_id].reason}) - "
            "timing it would time nothing"
        )
        assert large_results[rule_id].evaluations == 4 * small_results[rule_id].evaluations > 0, (
            f"{rule_id}: {small_results[rule_id].evaluations} evaluations at {SMALL} countries, "
            f"{large_results[rule_id].evaluations} at {LARGE} - not one per column and country"
        )

    # Act
    small_calls = _calls(lambda: evaluate_rules(small, release.pack, rules))
    large_calls = _calls(lambda: evaluate_rules(large, release.pack, rules))
    small_seconds = _best_cpu(lambda: evaluate_rules(small, release.pack, rules))
    large_seconds = _best_cpu(lambda: evaluate_rules(large, release.pack, rules))

    # Assert
    assert large_calls < MAX_CALL_RATIO * small_calls, (
        f"{LARGE} countries took {large_calls:,} function calls against {small_calls:,} for "
        f"{SMALL}: {large_calls / small_calls:.2f}x for 4x the countries. Rule evaluation has "
        "gone super-linear in the size of an open axis - look for every cell a reference could "
        "read being placed at each evaluation"
    )
    ratio = large_seconds / small_seconds
    assert ratio < MAX_SCALING_RATIO, (
        f"{LARGE} countries took {large_seconds:.3f}s of CPU against {small_seconds:.3f}s for "
        f"{SMALL}: {ratio:.1f}x for 4x the countries, where the function calls grew "
        f"{large_calls / small_calls:.2f}x - look for a scan of every cell inside the "
        "per-evaluation loop"
    )
    assert large_seconds < BUDGET_SECONDS, (
        f"{LARGE} countries took {large_seconds:.2f}s, over the {BUDGET_SECONDS}s budget"
    )


def test_rule_evaluation_scales_linearly_in_the_rows_of_an_open_row_table() -> None:
    """Four times the obligor grades a sheet: under 4.4x the calls and under 8x the CPU time."""
    # Arrange
    release = _release()
    rules = _grade_rules()
    small, large = _graded_return(ROWS_SMALL), _graded_return(ROWS_LARGE)

    # Adequacy: every rule that reads the grades runs at both sizes. Those read
    # grade by grade run four times as often; those that sum every grade, as
    # often, over four times the cells.
    assert large.facts.height == 4 * small.facts.height > 0
    small_results = {
        result.rule_id: result for result in evaluate_rules(small, release.pack, rules)
    }
    large_results = {
        result.rule_id: result for result in evaluate_rules(large, release.pack, rules)
    }
    not_run = sorted(
        rule_id
        for rule_id, result in small_results.items()
        if result.status not in (STATUS_PASS, STATUS_FAIL)
    )
    assert not not_run, f"rule(s) {not_run} not evaluated - timing them would time nothing"
    growth = Counter(
        large_results[rule_id].evaluations / small_results[rule_id].evaluations
        for rule_id in small_results
    )
    assert set(growth) == {1.0, 4.0}, f"evaluations grew by {dict(growth)} for 4x the rows"

    # Act
    small_calls = _calls(lambda: evaluate_rules(small, release.pack, rules))
    large_calls = _calls(lambda: evaluate_rules(large, release.pack, rules))
    small_cpu = _best_cpu(lambda: evaluate_rules(small, release.pack, rules))
    large_cpu = _best_cpu(lambda: evaluate_rules(large, release.pack, rules))

    # Assert
    assert large_calls < MAX_CALL_RATIO * small_calls, (
        f"{ROWS_LARGE} grades a sheet took {large_calls:,} function calls against "
        f"{small_calls:,} for {ROWS_SMALL}: {large_calls / small_calls:.2f}x for 4x the rows. "
        "Rule evaluation has gone super-linear in an open-row table's rows - look for every row "
        "of a sheet searched for one row's key"
    )
    assert large_cpu / small_cpu < MAX_SCALING_RATIO, (
        f"{ROWS_LARGE} grades a sheet took {large_cpu:.3f}s of CPU against {small_cpu:.3f}s for "
        f"{ROWS_SMALL}: {large_cpu / small_cpu:.1f}x for 4x the rows, where the function calls "
        f"grew {large_calls / small_calls:.2f}x"
    )


def test_tracing_scales_linearly_in_the_number_of_countries() -> None:
    """A trace keeps every evaluation and cell read: 4x the countries, under 4.4x the calls.

    The summed rules alone: each reads a total cell and a summed side at every
    column and country, the two ways a side is traced, for a sixth of the cost
    of every rule that reads the two tables.
    """
    # Arrange
    release = _release()
    rules = tuple(rule for rule in _rules() if rule.rule_id in SUMMED_RULES)
    small, large = _geographical_return(SMALL), _geographical_return(LARGE)

    # Adequacy: the summed rules are traced once per column and country, and
    # the cells the trace keeps grow with the countries.
    small_trace = trace_rules(small, release.pack, rules)
    large_trace = trace_rules(large, release.pack, rules)
    small_traced = Counter(evaluation.rule_id for evaluation in small_trace.evaluations)
    large_traced = Counter(evaluation.rule_id for evaluation in large_trace.evaluations)
    assert sorted(small_traced) == sorted(SUMMED_RULES)
    for rule_id in SUMMED_RULES:
        assert large_traced[rule_id] == 4 * small_traced[rule_id] > 0, (
            f"{rule_id}: {small_traced[rule_id]} traced evaluations at {SMALL} countries, "
            f"{large_traced[rule_id]} at {LARGE} - not one per column and country"
        )
    assert len(large_trace.cells) == 4 * len(small_trace.cells) > 0

    # Act
    small_calls = _calls(lambda: trace_rules(small, release.pack, rules))
    large_calls = _calls(lambda: trace_rules(large, release.pack, rules))
    small_cpu = _best_cpu(lambda: trace_rules(small, release.pack, rules))
    large_cpu = _best_cpu(lambda: trace_rules(large, release.pack, rules))

    # Assert
    assert large_calls < MAX_CALL_RATIO * small_calls, (
        f"tracing {LARGE} countries took {large_calls:,} function calls against {small_calls:,} "
        f"for {SMALL}: {large_calls / small_calls:.2f}x for 4x the countries. Tracing has gone "
        "super-linear in the size of an open axis - look for every cell a side could read "
        "being placed at each evaluation"
    )
    assert large_cpu / small_cpu < MAX_SCALING_RATIO, (
        f"tracing {LARGE} countries took {large_cpu:.3f}s of CPU against {small_cpu:.3f}s for "
        f"{SMALL}: {large_cpu / small_cpu:.1f}x for 4x the countries, where the function calls "
        f"grew {large_calls / small_calls:.2f}x"
    )


def test_a_few_cells_with_no_country_leave_rule_evaluation_linear_in_the_countries() -> None:
    """Twenty blank country cells a table: 4x the countries is under 4.4x the calls."""
    # Arrange
    release = _release()
    rules = tuple(rule for rule in _rules() if rule.rule_id in SUMMED_RULES)
    small = _geographical_return(BLANK_SMALL, blank=BLANK_CELLS)
    large = _geographical_return(BLANK_LARGE, blank=BLANK_CELLS)

    # Adequacy: the blank cells are there, few, and under both references of every
    # summed rule; each rule reads them beside a country's cells; and the rules
    # still run once per column and country.
    for ret in (small, large):
        assert _blank_facts(ret) == dict.fromkeys(TABLES, BLANK_PER_TABLE), (
            "the return does not hold twenty cells with no country in each table"
        )
    assert sorted(rule.rule_id for rule in rules) == sorted(SUMMED_RULES)
    for rule in rules:
        assert _blank_under_both_references(rule), (
            f"{rule.rule_id}: no column of its scope has a blank cell on its total row and on a "
            "row it sums - its places would have one shape and nothing here would be measured"
        )
    mixed = _rules_reading_blank_and_keyed_cells(small, release, rules)
    assert mixed == set(SUMMED_RULES), (
        f"only {sorted(mixed)} read a cell with no country beside a country's cells in one "
        "evaluation - the two-shape lookup this test measures is not taken by the others"
    )
    small_results = _summed(evaluate_rules(small, release.pack, rules))
    large_results = _summed(evaluate_rules(large, release.pack, rules))
    for rule_id in SUMMED_RULES:
        assert small_results[rule_id].status == STATUS_PASS, (
            f"{rule_id} was not evaluated ({small_results[rule_id].reason})"
        )
        assert large_results[rule_id].evaluations == 4 * small_results[rule_id].evaluations > 0, (
            f"{rule_id}: {small_results[rule_id].evaluations} evaluations at {BLANK_SMALL} "
            f"countries, {large_results[rule_id].evaluations} at {BLANK_LARGE}"
        )

    # Act
    small_calls = _calls(lambda: evaluate_rules(small, release.pack, rules))
    large_calls = _calls(lambda: evaluate_rules(large, release.pack, rules))
    small_cpu = _best_cpu(lambda: evaluate_rules(small, release.pack, rules))
    large_cpu = _best_cpu(lambda: evaluate_rules(large, release.pack, rules))

    # Assert
    assert large_calls < MAX_CALL_RATIO * small_calls, (
        f"{BLANK_LARGE} countries took {large_calls:,} function calls against {small_calls:,} "
        f"for {BLANK_SMALL}: {large_calls / small_calls:.2f}x for 4x the countries. A few cells "
        "with no country have made rule evaluation super-linear - look for places compared "
        "pair by pair"
    )
    assert large_cpu / small_cpu < MAX_SCALING_RATIO, (
        f"{BLANK_LARGE} countries took {large_cpu:.3f}s of CPU against {small_cpu:.3f}s for "
        f"{BLANK_SMALL}: {large_cpu / small_cpu:.1f}x for 4x the countries, where the function "
        f"calls grew {large_calls / small_calls:.2f}x - look for a scan of every cell a reference "
        "could read inside the per-evaluation loop"
    )


def test_indexing_a_return_costs_the_same_however_its_countries_are_written() -> None:
    """``DE`` for ``eba_GA:DE`` is the documented form and the XBRL reader's: not a slow path."""
    # Arrange - the countries at the END of the axis's list, where a walk of it is longest.
    release = _release()
    rules = _rules()
    qualified = _geographical_return(LARGE, last=True)
    bare = _geographical_return(LARGE, last=True, local_names=True)

    # Adequacy: the two returns spell the same countries the two ways, and the
    # engine reads them as the same return.
    assert all(":" in key for key in qualified.facts["open_key"])
    assert not any(":" in key for key in bare.facts["open_key"])
    assert bare.facts.height == qualified.facts.height > 0
    as_qualified = evaluate_rules(qualified, release.pack, rules)
    assert evaluate_rules(bare, release.pack, rules) == as_qualified
    assert all(_summed(as_qualified)[rule_id].status == STATUS_PASS for rule_id in SUMMED_RULES)

    # Act - no rule: indexing the return is all that is measured.
    qualified_calls = _calls(lambda: evaluate_rules(qualified, release.pack, ()))
    bare_calls = _calls(lambda: evaluate_rules(bare, release.pack, ()))
    qualified_cpu = _best_cpu(lambda: evaluate_rules(qualified, release.pack, ()))
    bare_cpu = _best_cpu(lambda: evaluate_rules(bare, release.pack, ()))

    # Assert
    assert qualified_calls > qualified.facts.height, "indexing made fewer calls than it has facts"
    assert bare_calls < MAX_SPELLING_CALL_RATIO * qualified_calls, (
        f"indexing {bare.facts.height:,} facts took {bare_calls:,} function calls with the "
        f"countries written by code alone against {qualified_calls:,} written as QNames: "
        f"{bare_calls / qualified_calls:.1f}x. Each fact's key is being looked for in the axis's "
        "member list"
    )
    assert bare_cpu < MAX_SPELLING_CPU_RATIO * qualified_cpu, (
        f"indexing took {bare_cpu:.3f}s of CPU with the countries written by code alone against "
        f"{qualified_cpu:.3f}s written as QNames"
    )


# =============================================================================
# Helpers
# =============================================================================


@cache
def _release() -> Release:
    """The packaged PRA001 release, loaded once."""
    return resolve_release(MODULE, TAXONOMY)


@cache
def _rules() -> tuple[Rule, ...]:
    """The enforced rules that read the geographical breakdown tables alone."""
    rulebook = _release().rulebook
    assert rulebook is not None, f"taxonomy {TAXONOMY} packages no rule book for {MODULE}"
    return tuple(rule for rule in rulebook.enforced(MODULE) if set(rule.tables) <= set(TABLES))


@cache
def _grade_rules() -> tuple[Rule, ...]:
    """The enforced rules that read the obligor grades, beside the class totals at most."""
    rulebook = _release().rulebook
    assert rulebook is not None, f"taxonomy {TAXONOMY} packages no rule book for {MODULE}"
    return tuple(
        rule
        for rule in rulebook.enforced(MODULE)
        if GRADES in rule.tables and set(rule.tables) <= {GRADES, CLASS_TOTALS}
    )


def _graded_return(grades: int) -> CanonicalReturn:
    """Every cell of OF 08.02 for ``grades`` grades on each of ``GRADE_SHEETS``.

    Each grade is a row keyed by its number; OF 08.01, which the grades are
    summed against, is declared filed and reports nothing.
    """
    pack = _release().pack
    table = pack.tables[GRADES]
    (key,) = table.open_keys
    cells = pack.cells.filter(
        (pl.col("table") == GRADES) & pl.col("sheet").is_in(GRADE_SHEETS)
    ).select("sheet", "column")
    facts: list[tuple[object, ...]] = []
    for grade in range(grades):
        row = f"g{grade:04d}"
        facts.extend(
            (GRADES, sheet, None, row, key.code, float(grade + 1), None, None)
            for sheet in GRADE_SHEETS
        )
        facts.extend(
            (GRADES, sheet, None, row, column, float(grade % 7), None, 0)
            for sheet, column in cells.iter_rows()
        )
    header = ReturnHeader(VALID_LEI, date(2027, 3, 31), MODULE)
    frame = pl.DataFrame(facts, schema=dict(FACT_SCHEMA), orient="row")
    filed = {pack.tables[code].filing_indicator: True for code in (GRADES, CLASS_TOTALS)}
    return CanonicalReturn.from_frame(header, frame, filed)


def _geographical_return(
    countries: int,
    *,
    last: bool = False,
    local_names: bool = False,
    blank: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] | None = None,
) -> CanonicalReturn:
    """Every cell of OF 09.01 and OF 09.02 reported at zero, for ``countries`` countries.

    The first ``countries`` of the axis's list, or the ``last``; written as
    QNames (``eba_GA:DE``), or by ``local_names`` alone (``DE``). ``blank``
    names cells, per table by (rows, columns), reported once more with NO
    country.
    """
    pack = _release().pack
    frames = []
    for table in TABLES:
        axis = pack.tables[table].open_axis
        assert axis is not None, f"{table} has no open axis in taxonomy {TAXONOMY}"
        members = axis.members[-countries:] if last else axis.members[:countries]
        assert len(members) == countries, f"{table} has only {len(axis.members)} members"
        keys = [local_name(member) for member in members] if local_names else list(members)
        cells = pack.cells.filter(pl.col("table") == table).select("table", "row", "column")
        frames.append(
            cells.join(pl.DataFrame({"open_key": keys}), how="cross").with_columns(
                pl.lit(0.0).alias("value")
            )
        )
        if blank is not None:
            rows, columns = blank[table]
            frames.append(
                cells.filter(pl.col("row").is_in(rows) & pl.col("column").is_in(columns)).select(
                    "table",
                    "row",
                    "column",
                    pl.lit(None, dtype=pl.String).alias("open_key"),
                    pl.lit(0.0).alias("value"),
                )
            )
    header = ReturnHeader(VALID_LEI, date(2027, 3, 31), MODULE)
    return CanonicalReturn.from_frame(header, pl.concat(frames))


def _blank_facts(ret: CanonicalReturn) -> dict[str, int]:
    """How many facts of each table have no country."""
    counted = ret.facts.filter(pl.col("open_key").is_null()).group_by("table").len()
    return dict(counted.iter_rows())


def _blank_under_both_references(rule: Rule) -> bool:
    """Whether a column of the rule's scope has a blank cell on its total row and on a summed row."""
    (table,) = rule.tables
    rows, columns = BLANK_CELLS[table]
    total, summed = references(rule.tree)
    scoped = {column for group in rule.scope_groups for column in group.columns}
    return bool(
        scoped & set(columns) and set(total.rows) <= set(rows) and set(summed.rows) & set(rows)
    )


def _rules_reading_blank_and_keyed_cells(
    ret: CanonicalReturn, release: Release, rules: tuple[Rule, ...]
) -> set[str]:
    """The rules with an evaluation whose sum reads a cell with no country and one with."""
    return {
        evaluation.rule_id
        for evaluation in trace_rules(ret, release.pack, rules).evaluations
        if {cell.open_key is None for cell in evaluation.right} == {True, False}
    }


def _summed(results: list[RuleResult]) -> dict[str, RuleResult]:
    """The summed rules' results, by rule."""
    return {result.rule_id: result for result in results if result.rule_id in SUMMED_RULES}


def _calls(act: Callable[[], object]) -> int:
    """How many Python and C functions ``act`` calls on this thread: a cost that reads no clock.

    ``sys.setprofile`` profiles the calling thread alone. ``cProfile`` on Python
    3.12+ counts every thread's calls, and under pytest-xdist a worker may still
    be running another test file's thread (a dashboard task), whose calls would
    land in either count and move the ratio.
    """
    count = 0

    def tick(_frame: FrameType, event: str, _arg: object) -> None:
        nonlocal count
        if event in ("call", "c_call"):
            count += 1

    previous = sys.getprofile()
    sys.setprofile(tick)
    try:
        act()
    finally:
        sys.setprofile(previous)
    return count


def _best_cpu(act: Callable[[], object]) -> float:
    """The least CPU time this thread spent in ``act``, of ``REPEATS`` runs, in seconds.

    This thread's CPU time, not the clock's: the rule loop is pure Python on the
    calling thread, and time spent waiting for a loaded box is not counted.
    """
    best = float("inf")
    for _ in range(REPEATS):
        started = time.thread_time()
        act()
        best = min(best, time.thread_time() - started)
    return best
