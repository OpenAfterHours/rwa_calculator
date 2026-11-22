"""
Scaling gate for the explanation step of ``compare``: cost in the number of countries.

Pipeline position:
    two geographical returns  ->  compare.compare_returns  ->  explain.explain_differences
    The comparison is run whole, once, to take the differences and both rule
    traces as ``compare`` hands them over; ``explain_differences`` is then
    measured on its own, at two country counts.

Key responsibilities:
- Pin the SHAPE of the explanation step in the size of an open axis, not a
  wall-clock number: four times the countries may make no more than 4.4 times
  the function calls. A call count is the same on a loaded box as on a quiet
  one; a CPU-time ratio is kept beside it as a coarser second line.
- Cover each loop that grew with the square of the countries, on a pair where
  it dominates: sibling sheets where every country states one accuracy,
  sibling sheets where countries state different ones (a walk that is linear
  only for a single allowance passes the first and fails the second), and a
  total that does not add up in every country.
- Keep the measured path live (LESSONS B4 / C11): assert that every sibling
  group holds one differing cell per country and that the countries end up in
  one finding, or that one finding holds a broken total per country - so the
  loop a shape is there to measure is not skipped by its fixture.

The escape this closes
----------------------
``explain`` linked sibling sheets by testing every pair of countries in every
row and column, and worked out each total's breakdown by rescanning every
check of its finding. Both grow with the square of the country count. A
parallel run of two systems that differ systematically - every country's
figures off - is the comparison this tool exists for: at 200 countries the
explanation took 6.7 s where 0.4 s suffices. No fixture had more than two
countries, where it is invisible. It is the third quadratic of this family
(the classifier 2026-09-05, rule evaluation 2026-11-20).

Calls counted with ``sys.setprofile`` on this file's returns, 40 against 160
countries (the count is the same on every run):

======================================  ==========  =======================  =====
shape                                   every pair  breakdown by rescanning  fixed
======================================  ==========  =======================  =====
every class restated, one allowance     12.8x       4.0x                     4.0x
every class restated, mixed allowances  12.7x       4.0x                     4.0x
every total overlaid                    13.5x       8.5x                     3.9x
======================================  ==========  =======================  =====

References:
- rwa_filer.workflow.explain._Links._link_siblings, _first_at_each_total
- tests/workflow/test_explain_siblings.py, test_explain_breakdown.py — the
  same change held to its result
- tests/boe/test_engine_scaling.py — the gate of the same shape for the engine
"""

from __future__ import annotations

import gc
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest

from compare_builders import (
    ALL_COUNTRIES,
    GEO_CLASSES,
    GEO_COLUMNS,
    GEO_TOTAL,
    country_codes,
    geographical_return,
)
from rwa_filer.readers import SourceReading
from rwa_filer.workflow import compare as compare_module
from rwa_filer.workflow.explain import (
    CATEGORY_MATERIAL,
    KIND_CALCULATION,
    KIND_DOES_NOT_ADD_UP,
    Discrepancy,
    explain_differences,
)

if TYPE_CHECKING:
    from types import FrameType

SMALL = 40
LARGE = 160
#: Linear cost gives 4x the calls for 4x the countries; either loop back gives 7x or more.
MAX_CALL_RATIO = 4.4
#: The second line, on CPU time: looser, because a clock is noisier than a count.
MAX_TIME_RATIO = 8.0
REPEATS = 5
#: Added to every country's total alone, so each breaks boe_b0730 by the same amount.
OVERLAY = 7_000.0


@dataclass(frozen=True)
class Shape:
    """How the candidate differs from the baseline, in every country.

    Attributes:
        accuracies: The ``decimals`` countries state, turn about.
        restated: Every class in every column restated by the country's own amount.
        overlaid: Every column's total overlaid by ``OVERLAY``.
    """

    accuracies: tuple[int, int]
    restated: bool = False
    overlaid: bool = False


SHAPES = {
    "every_class_restated_one_allowance": Shape((-3, -3), restated=True),
    "every_class_restated_mixed_allowances": Shape((-3, -2), restated=True),
    "every_total_overlaid": Shape((-3, -3), overlaid=True),
}


@pytest.mark.parametrize("name", SHAPES)
def test_explaining_differences_scales_linearly_in_the_number_of_countries(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Four times the countries may make no more than 4.4 times the function calls."""
    # Arrange
    shape = SHAPES[name]
    small = _handed_to_explain(SMALL, shape, monkeypatch)
    large = _handed_to_explain(LARGE, shape, monkeypatch)

    # Adequacy: the loop this shape measures runs, over every country, at both sizes.
    for countries, handed in ((SMALL, small), (LARGE, large)):
        if shape.restated:
            _assert_sibling_groups_are_full_and_linked(countries, handed)
        if shape.overlaid:
            _assert_one_finding_holds_a_broken_total_per_country(countries, handed)

    # Act
    small_calls, large_calls = _calls(small), _calls(large)
    small_seconds, large_seconds = _best_cpu_time(small), _best_cpu_time(large)

    # Assert
    ratio = large_calls / small_calls
    assert ratio < MAX_CALL_RATIO, (
        f"explaining {LARGE} countries made {large_calls:,} calls against {small_calls:,} for "
        f"{SMALL}: {ratio:.1f}x for 4x the countries. The explanation step has gone "
        "super-linear in the size of an open axis - look for a loop over every pair of "
        "countries, or over every check of a finding per cell"
    )
    assert large_seconds / small_seconds < MAX_TIME_RATIO, (
        f"explaining {LARGE} countries took {large_seconds:.3f}s of CPU against "
        f"{small_seconds:.3f}s for {SMALL}"
    )


# =============================================================================
# Helpers
# =============================================================================


def _handed_to_explain(
    countries: int, shape: Shape, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """What ``compare_returns`` hands ``explain_differences`` for a pair at ``countries``.

    A restated class moves by its country's own amount: 37 apart from the next
    country's, so no two are the same and each is well inside the stated
    accuracy of its neighbours.
    """
    codes = country_codes(countries)
    decimals = {code: shape.accuracies[index % 2] for index, code in enumerate(codes)}
    restated = {
        (code, row, column): 5_000.0 + 37.0 * index
        for index, code in enumerate(codes)
        for row in GEO_CLASSES
        for column in GEO_COLUMNS
        if shape.restated
    }
    overlaid = {
        (code, column): OVERLAY for code in codes for column in GEO_COLUMNS if shape.overlaid
    }
    baseline = geographical_return(codes, decimals=decimals)
    candidate = geographical_return(codes, decimals=decimals, restated=restated, overlaid=overlaid)
    handed: dict[str, Any] = {}

    def keep(*args: Any, **kwargs: Any) -> tuple[Discrepancy, ...]:
        handed.update(args=args, kwargs=kwargs)
        handed["findings"] = explain_differences(*args, **kwargs)
        return handed["findings"]

    monkeypatch.setattr(compare_module, "explain_differences", keep)
    comparison = compare_module.compare_returns(
        SourceReading(ret=baseline), SourceReading(ret=candidate)
    )
    handed["cells"] = comparison.cells
    return handed


def _assert_sibling_groups_are_full_and_linked(countries: int, handed: dict[str, Any]) -> None:
    cells: pl.DataFrame = handed["cells"]
    findings: tuple[Discrepancy, ...] = handed["findings"]
    in_countries = cells.filter(
        (pl.col("category") == CATEGORY_MATERIAL) & (pl.col("open_key") != ALL_COUNTRIES)
    )
    groups = {
        (row, column): count
        for row, column, count in in_countries.group_by("row", "column").len().iter_rows()
    }
    assert len(groups) == (len(GEO_CLASSES) + 1) * len(GEO_COLUMNS), f"sibling groups: {groups}"
    assert set(groups.values()) == {countries}, (
        f"a sibling group does not hold one differing cell per country: {groups}"
    )
    largest = max(
        (item for item in findings if item.kind == KIND_CALCULATION),
        key=lambda item: len(item.cells),
    )
    assert {cell[2] for cell in largest.cells} >= set(country_codes(countries)), (
        "the countries are not linked into one finding - the sibling walk links nothing"
    )


def _assert_one_finding_holds_a_broken_total_per_country(
    countries: int, handed: dict[str, Any]
) -> None:
    findings: tuple[Discrepancy, ...] = handed["findings"]
    totals = [
        item for item in findings if item.kind == KIND_DOES_NOT_ADD_UP and item.gap == OVERLAY
    ]
    assert [len(item.breakdown) for item in totals] == [countries * len(GEO_COLUMNS)], (
        "no one finding holds a total that does not add up in every country and column - "
        "the breakdown of a finding with many totals is not measured"
    )
    assert {part.cell[3] for part in totals[0].breakdown} == {GEO_TOTAL}
    assert {part.unexplained for part in totals[0].breakdown} == {OVERLAY}


def _calls(handed: dict[str, Any]) -> int:
    """How many Python and C functions one ``explain_differences`` calls."""
    count = 0

    def tick(_frame: FrameType, event: str, _arg: object) -> None:
        nonlocal count
        if event in ("call", "c_call"):
            count += 1

    previous = sys.getprofile()
    sys.setprofile(tick)
    try:
        explain_differences(*handed["args"], **handed["kwargs"])
    finally:
        sys.setprofile(previous)
    return count


def _best_cpu_time(handed: dict[str, Any]) -> float:
    """The least CPU time of ``REPEATS`` runs of ``explain_differences``, in seconds.

    The cyclic collector is paused while the clock runs: a collection that
    walks the loaded taxonomy pack costs more than the whole measurement and
    falls on whichever run happens to trigger it.
    """
    best = float("inf")
    collecting = gc.isenabled()
    gc.disable()
    try:
        for _ in range(REPEATS):
            started = time.thread_time()
            explain_differences(*handed["args"], **handed["kwargs"])
            best = min(best, time.thread_time() - started)
    finally:
        if collecting:
            gc.enable()
    return best
