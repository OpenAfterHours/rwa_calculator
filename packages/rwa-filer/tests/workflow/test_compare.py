"""
Comparing two returns: what differs, and which side the evidence points at.

Every return is a few real PRA001 cells (``compare_builders``), judged by the
packaged rule book, so the findings rest on the Bank's own rules rather than on
synthetic ones written to agree with this code. Each test changes one thing
between the two returns and asserts the finding that one change produces — and
the first asserts that nothing at all is found when nothing differs, because a
comparison that finds something on every pair carries no information.
"""

from __future__ import annotations

import json

import pytest

from compare_builders import CORPORATES, TABLE, corporate_return, unreported_return
from rwa_filer.boe.engine import CellAddress, Evaluation
from rwa_filer.readers import SourceReading
from rwa_filer.taxonomy.pack import resolve_pack
from rwa_filer.validate.checker import Finding
from rwa_filer.validate.structure import check_structure
from rwa_filer.workflow.compare import ReturnComparison, compare_returns
from rwa_filer.workflow.explain import (
    CATEGORY_MATERIAL,
    CATEGORY_ROUNDING,
    CATEGORY_SAME,
    CATEGORY_SCOPE,
    CATEGORY_ZERO_OR_BLANK,
    KIND_CALCULATION,
    KIND_DOES_NOT_ADD_UP,
    KIND_ONE_SIDED,
    KIND_RULE_ONLY,
    KIND_UNEXPECTED_ZERO,
    POINTS_AT_INPUTS,
    SIDE_BASELINE,
    SIDE_CANDIDATE,
    STANDING_BREAKS,
    STANDING_HOLDS,
    Cell,
    Names,
    explain_differences,
)


def compare(baseline: dict[str, object], candidate: dict[str, object]) -> ReturnComparison:
    """Compare two corporates returns built from ``corporate_return`` keyword arguments."""
    readings = []
    for differences in (baseline, candidate):
        ret = corporate_return(**differences)
        pack = resolve_pack(ret.header.module, ret.header.reference_date)
        assert check_structure(ret, pack) == [], "the fixture must be a valid PRA001 return"
        readings.append(SourceReading(ret=ret))
    return compare_returns(*readings, names=Names("the old system", "rwa-filer"))


def kinds(comparison: ReturnComparison) -> list[str]:
    return [item.kind for item in comparison.findings]


# ---------------------------------------------------------------------------
# Nothing differs
# ---------------------------------------------------------------------------


def test_two_identical_returns_are_equivalent_and_find_nothing() -> None:
    comparison = compare({}, {})

    assert comparison.is_equivalent
    assert comparison.findings == ()
    assert set(comparison.counts()) >= {CATEGORY_SAME}
    assert comparison.counts()[CATEGORY_SAME] == comparison.cells.height


def test_rules_both_returns_break_are_shared_and_not_a_finding() -> None:
    """Neither return fills OF 07.00 cols 0160-0190, so boe_b0710 breaks in both."""
    comparison = compare({}, {})

    assert "boe_b0710" in comparison.shared_breaks
    assert comparison.is_equivalent


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def test_figures_within_the_accuracy_both_files_state_are_rounding() -> None:
    """Both state thousands (decimals -3): each is good to 500, so 400 apart is the same."""
    comparison = compare({"decimals": -3}, {"decimals": -3, "nudge": 400.0})

    assert comparison.counts()[CATEGORY_ROUNDING] == 4
    assert comparison.counts()[CATEGORY_MATERIAL] == 0
    assert comparison.is_equivalent


def test_figures_beyond_the_stated_accuracy_are_material() -> None:
    comparison = compare({"decimals": -3}, {"decimals": -3, "nudge": 1_200.0})

    assert comparison.counts()[CATEGORY_MATERIAL] > 0
    assert not comparison.is_equivalent


def test_figures_that_state_no_accuracy_are_exact_unless_a_tolerance_is_given() -> None:
    readings = [
        SourceReading(ret=corporate_return()),
        SourceReading(ret=corporate_return(nudge=0.4)),
    ]

    exact = compare_returns(*readings)
    tolerant = compare_returns(*readings, tolerance=1.0)

    assert exact.counts()[CATEGORY_MATERIAL] > 0
    assert tolerant.counts()[CATEGORY_MATERIAL] == 0


def test_a_zero_against_a_blank_that_no_rule_minds_is_not_a_difference() -> None:
    """Col 0235 = 0 where the other return leaves it empty; boe_b0703 holds either way."""
    comparison = compare({"ecai_columns": True}, {"ecai_columns": True})
    baseline_only = compare({}, {})

    assert comparison.is_equivalent
    assert baseline_only.counts()[CATEGORY_ZERO_OR_BLANK] == 0


def test_a_template_only_one_return_reports_is_scope_and_not_equivalent() -> None:
    """The candidate declares OF 09.01 reported, with no facts: every cell of it is zero."""
    comparison = compare({}, {"indicators": {"OF07.00.01": True, "OF09.01.01": True}})

    assert comparison.indicators == {"OF09.01.01": (None, True)}
    assert not comparison.is_equivalent


def test_cells_of_a_template_the_other_return_does_not_report_are_scope() -> None:
    """The baseline declares OF 07.00 not reported: everything the candidate has there is scope."""
    baseline = SourceReading(ret=unreported_return({"OF07.00.01": False}))

    comparison = compare_returns(baseline, SourceReading(ret=corporate_return()))

    assert comparison.counts()[CATEGORY_SCOPE] == comparison.cells.height > 0
    assert comparison.indicators == {"OF07.00.01": (False, True)}


def test_a_fact_the_reader_could_not_place_is_kept_and_not_equivalent() -> None:
    """A fact with no cell in the module is in neither return to the Bank: say so, never drop it."""
    unplaced = Finding("XBR001", "ERROR", "1 fact(s) are not data points", "", "XBR001", "", "")
    baseline = SourceReading(ret=corporate_return(), findings=(unplaced,))

    comparison = compare_returns(baseline, SourceReading(ret=corporate_return()))

    assert comparison.baseline_unplaced == (unplaced,)
    assert not comparison.is_equivalent


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def test_a_figure_in_another_row_is_one_finding_that_points_at_the_inputs() -> None:
    """50% in the old system, 75% in rwa-filer: one exposure, two calculations."""
    comparison = compare({"risk_weight_row": "0200"}, {"risk_weight_row": "0220"})

    (finding,) = comparison.findings
    assert (finding.kind, finding.points_at) == (KIND_CALCULATION, POINTS_AT_INPUTS)
    (move,) = finding.moves
    assert (move.table, move.sheet, move.baseline_row, move.candidate_row) == (
        TABLE,
        CORPORATES,
        "0200",
        "0220",
    )
    assert move.amount == 1_000_000
    assert set(move.columns) >= {"0010", "0150", "0200"}


def test_a_move_between_rate_rows_is_checked_against_the_column_that_applies_the_rate() -> None:
    """1,000,000 x (75% - 50%) is the 250,000 the RWEA column moved: the move explains it."""
    comparison = compare({"risk_weight_row": "0200"}, {"risk_weight_row": "0220"})

    check = comparison.findings[0].rate_check
    assert check is not None
    assert (check.column, check.implied, check.observed, check.consistent) == (
        "0220",
        250_000,
        250_000,
        True,
    )


def test_every_differing_cell_of_a_consistent_difference_is_in_its_one_finding() -> None:
    comparison = compare({"risk_weight_row": "0200"}, {"risk_weight_row": "0220"})

    material = comparison.cells.filter(comparison.cells["category"] == CATEGORY_MATERIAL)
    assert material.height > 2, "a move touches several cells, or this test proves nothing"
    assert material["finding"].to_list() == [1] * material.height


def test_a_total_that_does_not_add_up_in_one_return_points_at_that_return() -> None:
    """The old system adds 50,000 to the RWEA total and to nothing it is the sum of."""
    comparison = compare({"total_overlay": 50_000.0}, {})

    (finding,) = comparison.findings
    assert (finding.kind, finding.points_at, finding.gap) == (
        KIND_DOES_NOT_ADD_UP,
        SIDE_BASELINE,
        50_000,
    )
    (part,) = finding.breakdown
    assert (part.cell, part.delta, part.explained, part.unexplained) == (
        (TABLE, CORPORATES, None, "0010", "0220"),
        -50_000,
        0,
        -50_000,
    )
    assert {rule.baseline for rule in finding.rules} == {STANDING_BREAKS}
    assert {rule.candidate for rule in finding.rules} == {STANDING_HOLDS}


def test_a_column_only_one_return_fills_points_at_the_return_whose_rules_break() -> None:
    """rwa-filer leaves col 0230 empty and breaks boe_b0703; the old system fills it."""
    comparison = compare({"ecai_columns": True}, {})

    (finding,) = comparison.findings
    assert (finding.kind, finding.points_at) == (KIND_ONE_SIDED, SIDE_CANDIDATE)
    assert {cell[4] for cell in finding.cells} == {"0230"}
    assert [(r.rule_id, r.baseline, r.candidate) for r in finding.rules] == [
        ("boe_b0703", STANDING_HOLDS, STANDING_BREAKS)
    ]


def test_a_zero_the_bank_expects_left_empty_points_at_the_return_that_files_it() -> None:
    comparison = compare({"zero_where_empty": True}, {})

    (finding,) = comparison.findings
    assert (finding.kind, finding.points_at) == (KIND_UNEXPECTED_ZERO, SIDE_BASELINE)
    assert finding.cells == ((TABLE, CORPORATES, None, "0140", "0010"),)
    assert "boe_b0441" in {rule.rule_id for rule in finding.rules}


def test_several_differences_at_once_are_each_found_and_every_material_cell_is_explained() -> None:
    comparison = compare(
        {"risk_weight_row": "0200", "ecai_columns": True, "zero_where_empty": True},
        {"risk_weight_row": "0220"},
    )

    assert kinds(comparison) == [KIND_CALCULATION, KIND_ONE_SIDED, KIND_UNEXPECTED_ZERO]
    material = comparison.cells.filter(comparison.cells["category"] == CATEGORY_MATERIAL)
    assert material["finding"].null_count() == 0
    placed = [cell for item in comparison.findings for cell in item.cells]
    assert len(placed) == len(set(placed)), "a cell is in one finding only"


def test_findings_are_numbered_in_the_order_they_are_listed() -> None:
    comparison = compare({"ecai_columns": True, "zero_where_empty": True}, {})

    assert [item.number for item in comparison.findings] == list(
        range(1, len(comparison.findings) + 1)
    )


def test_findings_name_the_two_returns_as_the_caller_does() -> None:
    comparison = compare({"total_overlay": 50_000.0}, {})

    assert comparison.findings[0].title.startswith("In the old system,")


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "baseline", [{}, {"risk_weight_row": "0220", "ecai_columns": True, "total_overlay": 1.0}]
)
def test_the_record_is_json_ready_and_carries_the_verdict(baseline: dict[str, object]) -> None:
    comparison = compare(baseline, {})

    record = json.loads(json.dumps(comparison.as_record()))

    assert record["equivalent"] is comparison.is_equivalent
    assert len(record["findings"]) == len(comparison.findings)
    assert record["counts"] == comparison.counts()


# ---------------------------------------------------------------------------
# A rule that breaks in one return only
# ---------------------------------------------------------------------------


def test_declaring_a_template_and_leaving_it_empty_breaks_its_ties_in_that_return() -> None:
    """OF 09.01 reported empty: its corporates row is 0 where OF 07.00 says 1,000,000."""
    comparison = compare({}, {"indicators": {"OF07.00.01": True, "OF09.01.01": True}})

    assert comparison.findings, "a template that breaks the Bank's ties must be found"
    assert {item.points_at for item in comparison.findings} == {SIDE_CANDIDATE}
    assert {item.kind for item in comparison.findings} == {KIND_DOES_NOT_ADD_UP}
    assert "boe_b0222" in {rule.rule_id for item in comparison.findings for rule in item.rules}


def _evaluation(rule_id: str, *, holds: bool, cell: Cell) -> Evaluation:
    return Evaluation(
        rule_id=rule_id,
        place=(("r", cell[3]),),
        holds=holds,
        relation="<=",
        left=(CellAddress(*cell),),
    )


def test_a_rule_broken_in_one_return_that_no_finding_explains_is_still_a_finding() -> None:
    """The safety net: a one-sided break is never dropped for want of a differing cell."""
    cell: Cell = (TABLE, CORPORATES, None, "0010", "0220")
    pack = resolve_pack("PRA001", corporate_return().header.reference_date)

    findings = explain_differences(
        {},
        [_evaluation("boe_x", holds=True, cell=cell)],
        [_evaluation("boe_x", holds=False, cell=cell)],
        pack,
    )

    (finding,) = findings
    assert (finding.kind, finding.points_at) == (KIND_RULE_ONLY, SIDE_CANDIDATE)
    assert "No differing cell is behind it" in finding.detail


def test_a_rule_broken_in_both_returns_at_different_places_is_not_one_sided() -> None:
    """A figure moved to another row takes its break with it: the rule breaks in both."""
    first: Cell = (TABLE, CORPORATES, None, "0200", "0220")
    second: Cell = (TABLE, CORPORATES, None, "0220", "0220")
    pack = resolve_pack("PRA001", corporate_return().header.reference_date)

    findings = explain_differences(
        {},
        [_evaluation("boe_x", holds=False, cell=first)],
        [_evaluation("boe_x", holds=False, cell=second)],
        pack,
    )

    assert findings == ()
