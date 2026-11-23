"""
A total that does not add up: which check its breakdown is read from.

Pipeline position:
    hand-built Evaluations of both returns  ->  explain.explain_differences
        ->  Discrepancy.breakdown (TotalBreakdown per total)

Key responsibilities:
- A finding can hold several checks on one total - two rules that sum it two
  ways, breaking by the same amount. The breakdown is read from the FIRST of
  them, in the order the rules ran, that has the total alone on its left in
  both files. The finding looks each total's check up in a table built once
  (the scan it replaces cost the square of the checks in a finding, one per
  country); these tests hold that table to the scan's two conditions.

The evaluations are built by hand because the rule engine does not produce
either case on a small return: two rules on one total that are out by
different amounts in the file where they hold, and one rule reading a different
left-hand cell in each file.

References:
- rwa_filer.workflow.explain._first_at_each_total
"""

from __future__ import annotations

from compare_builders import CORPORATES, TABLE
from rwa_filer.boe.engine import CellAddress, Evaluation
from rwa_filer.release import resolve_release
from rwa_filer.workflow.explain import (
    CATEGORY_MATERIAL,
    KIND_DOES_NOT_ADD_UP,
    SIDE_CANDIDATE,
    Cell,
    CellDifference,
    TotalBreakdown,
    explain_differences,
)

TOTAL: Cell = (TABLE, CORPORATES, None, "0010", "0220")
ELSEWHERE: Cell = (TABLE, CORPORATES, None, "0070", "0220")
COMPONENT: Cell = (TABLE, CORPORATES, None, "0200", "0220")
#: The total is 100 in the baseline and 150 in the candidate; its components sum to 100.
DIFFERENCES = {TOTAL: CellDifference(TOTAL, CATEGORY_MATERIAL, 100.0, 150.0, 50.0)}


def summed(rule_id: str, *, left: Cell = TOTAL, total: float, components: float) -> Evaluation:
    """``left = sum(components)`` as one return evaluated it; it holds within 1 either way."""
    return Evaluation(
        rule_id=rule_id,
        place=(("z", CORPORATES),),
        holds=abs(total - components) < 1,
        relation="=",
        left=(CellAddress(*left),),
        right=(CellAddress(*COMPONENT),),
        left_value=total,
        right_value=components,
    )


def breakdown(baseline: list[Evaluation], candidate: list[Evaluation]) -> TotalBreakdown:
    findings = explain_differences(DIFFERENCES, baseline, candidate, resolve_release("PRA001").pack)
    (finding,) = (item for item in findings if item.kind == KIND_DOES_NOT_ADD_UP)
    assert (finding.points_at, finding.gap) == (SIDE_CANDIDATE, 50)
    assert len(finding.rules) == len(candidate), "every check must be in the one finding"
    (part,) = finding.breakdown
    return part


def test_a_totals_breakdown_is_read_from_the_first_rule_that_sums_it() -> None:
    """Both rules break by 50 in the candidate; in the baseline the second is out by 0.4."""
    baseline = [
        summed("boe_first", total=100.0, components=100.0),
        summed("boe_second", total=100.0, components=99.6),
    ]
    candidate = [
        summed("boe_first", total=150.0, components=100.0),
        summed("boe_second", total=150.0, components=100.0),
    ]

    part = breakdown(baseline, candidate)

    assert (part.cell, part.delta, part.explained, part.unexplained) == (TOTAL, 50, 0, 50)


def test_a_check_with_another_cell_on_its_left_in_one_file_does_not_explain_the_total() -> None:
    """The first rule read a different left-hand cell in the baseline: it is passed over."""
    baseline = [
        summed("boe_first", left=ELSEWHERE, total=100.4, components=100.0),
        summed("boe_second", total=100.0, components=100.0),
    ]
    candidate = [
        summed("boe_first", total=150.0, components=100.0),
        summed("boe_second", total=150.0, components=100.0),
    ]

    part = breakdown(baseline, candidate)

    assert (part.cell, part.delta, part.explained, part.unexplained) == (TOTAL, 50, 0, 50)
