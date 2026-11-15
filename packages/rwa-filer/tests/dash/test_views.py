"""The page models, without HTTP: overview, rules, the grid, file names, value formatting."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from rwa_filer.boe.engine import STATUS_FAIL, STATUS_NOT_EVALUATED, STATUS_PASS
from rwa_filer.dash.grid import display_value, failure_marks, template_grid
from rwa_filer.dash.views import RULES_PER_PAGE, overview, rule_label, rules_page, title_case
from rwa_filer.dash.workspace import safe_file_name

if TYPE_CHECKING:
    from rwa_filer.dash import OpenedReturn, Workspace


def test_the_overview_counts_are_the_reports_own(broken: OpenedReturn) -> None:
    # Arrange
    report = broken.validation.report
    assert report is not None

    # Act
    view = overview(broken)

    # Assert
    assert view.status_counts == report.status_counts()
    assert (view.enforced, view.executed) == (report.rules_enforced, report.rules_executed)
    assert [item.code for item in view.templates] == list(report.templates_reported)
    assert view.errors + view.warnings == report.status_counts()[STATUS_FAIL]
    assert view.submittable is broken.validation.is_submittable is False


def test_the_overview_lists_the_templates_the_reported_ones_are_checked_against(
    broken: OpenedReturn,
) -> None:
    """OF 07.00 alone: the rules tying it to other templates did not run."""
    # Arrange
    report = broken.validation.report
    assert report is not None
    assert report.templates_missing, "the fixture must leave one out"

    # Act
    missing = overview(broken).missing

    # Assert — every one, with its title, the most-checked first.
    assert {item.code for item in missing} == {item.code for item in report.templates_missing}
    assert all(item.title and item.title != item.code for item in missing)
    assert [item.rules for item in missing] == sorted(
        (item.rules for item in missing), reverse=True
    )
    assert {code for item in missing for code in item.linked_from} == {"OF07.00.01"}


def test_the_overview_lists_errors_before_warnings(broken: OpenedReturn) -> None:
    # Act
    severities = [row.severity for row in overview(broken).breaks]

    # Assert
    assert "WARNING" in severities, "the fixture must break a Warning rule"
    assert severities == sorted(severities)


@pytest.mark.parametrize("status", [STATUS_FAIL, STATUS_PASS, STATUS_NOT_EVALUATED])
def test_each_status_lists_exactly_its_rules(broken: OpenedReturn, status: str) -> None:
    # Arrange
    report = broken.validation.report
    assert report is not None

    # Act
    view = rules_page(broken, status=status)

    # Assert
    assert view.matched == report.status_counts()[status]
    assert {row.status for row in view.rows} <= {status}


def test_the_rules_list_is_paged(broken: OpenedReturn) -> None:
    # Arrange
    total = rules_page(broken, status=STATUS_NOT_EVALUATED).matched
    assert total > RULES_PER_PAGE, "the fixture must leave more rules unevaluated than one page"

    # Act
    first = rules_page(broken, status=STATUS_NOT_EVALUATED)
    beyond = rules_page(broken, status=STATUS_NOT_EVALUATED, page=10_000)

    # Assert — every page full but the last; a page past the end is the last.
    assert len(first.rows) == RULES_PER_PAGE
    assert beyond.page == beyond.pages
    assert len(beyond.rows) == total - (beyond.pages - 1) * RULES_PER_PAGE


def test_a_rule_named_in_the_address_is_detailed_whatever_the_filter(broken: OpenedReturn) -> None:
    # Arrange
    failed = next(row.rule_id for row in rules_page(broken).rows)

    # Act
    view = rules_page(broken, status=STATUS_PASS, rule_id=failed)

    # Assert
    assert view.selected is not None and view.selected.row.rule_id == failed
    assert view.selected.failures


def test_every_failure_address_becomes_a_mark(broken: OpenedReturn) -> None:
    # Arrange
    report = broken.validation.report
    assert report is not None
    expected = {
        (address.table, address.sheet, address.open_key, address.row, address.column)
        for result in report.results
        if result.status == STATUS_FAIL
        for failure in result.failures
        for address in failure.addresses
    }

    # Act
    marks = failure_marks(broken.validation)

    # Assert
    assert expected and set(marks) == expected


def test_the_grid_opens_on_a_flagged_sheet_with_a_flagged_cell_picked(
    workspace: Workspace, broken: OpenedReturn
) -> None:
    # Act
    grid = template_grid(workspace.working(broken))

    # Assert
    assert grid is not None
    assert grid.page.marks > 0
    assert grid.cell is not None and grid.cell.marks


def test_the_picked_cell_carries_each_rule_that_read_it_in_full(
    workspace: Workspace, broken: OpenedReturn
) -> None:
    """The cell panel explains a rule in place, so it needs the rule's text, not just its ID."""
    # Arrange — OF 07.00 r0010 c0010 on sheet 0008, read by several broken rules.
    place = ("OF07.00.01.01", "0008", None, "0010", "0010")

    # Act
    grid = template_grid(
        workspace.working(broken), table=place[0], sheet=place[1], row=place[3], column=place[4]
    )

    # Assert — one entry per mark, each with the publisher's label and expression.
    assert grid is not None
    assert grid.cell is not None
    rules = grid.cell.rules
    assert [item.mark for item in rules] == list(grid.cell.marks)
    assert all(item.rule.row.label == rule_label("PRA001", item.mark.rule_id) for item in rules)
    assert all(item.rule.row.label and item.rule.expression for item in rules)


def test_the_picked_cell_keeps_only_the_breaks_that_read_it(
    workspace: Workspace, broken: OpenedReturn
) -> None:
    # Arrange — boe_b0713 breaks once per column; only its column 0010 break reads c0010.
    place = ("OF07.00.01.01", "0008", None, "0010", "0010")
    report = broken.validation.report
    assert report is not None
    every = next(result for result in report.results if result.rule_id == "boe_b0713").failures
    assert len(every) > 1, "a rule with one break leaves nothing to narrow — this proves nothing"

    # Act
    grid = template_grid(
        workspace.working(broken), table=place[0], sheet=place[1], row=place[3], column=place[4]
    )

    # Assert
    assert grid is not None
    assert grid.cell is not None
    kept = next(item for item in grid.cell.rules if item.mark.rule_id == "boe_b0713").rule.failures
    assert kept
    assert len(kept) < len(every)
    assert all(
        any((a.table, a.sheet, a.open_key, a.row, a.column) == place for a in failure.addresses)
        for failure in kept
    )


def test_the_grid_lays_a_table_out_in_the_taxonomys_rows_and_columns(
    workspace: Workspace, broken: OpenedReturn
) -> None:
    # Arrange
    table = broken.pack.tables["OF07.00.01.01"]

    # Act
    grid = template_grid(workspace.working(broken), table=table.code, sheet="0008")

    # Assert
    assert grid is not None
    assert [row.code for row in grid.rows] == list(table.row_codes)
    assert [code for code, _ in grid.columns] == list(table.column_codes)
    assert grid.page.sheet == "0008"


@pytest.mark.parametrize(
    ("value", "text", "data_type", "shown"),
    [
        (1_000_000.0, None, "monetary", "1,000,000"),
        (1234.5, None, "monetary", "1,234.50"),
        (0.0045, None, "percentage", "0.45%"),
        (12.0, None, "integer", "12"),
        (None, "true", "boolean", "true"),
        (None, None, "monetary", ""),
    ],
)
def test_values_are_shown_as_a_reader_expects(
    value: float | None, text: str | None, data_type: str, shown: str
) -> None:
    assert display_value(value, text, data_type) == shown


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("return.parquet", "return.parquet"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\return.xbrl", "return.xbrl"),
        ("my return (v2).csv", "my_return_v2_.csv"),
        ("..", "upload"),
    ],
)
def test_an_uploaded_name_cannot_leave_its_folder(given: str, kept: str) -> None:
    assert safe_file_name(given) == kept


def test_titles_read_in_sentence_case_with_their_short_name_kept() -> None:
    assert (
        title_case("CREDIT RISK: IRB APPROACH (CR IRB 1)") == "Credit risk: IRB approach (CR IRB 1)"
    )
    assert title_case("OWN FUNDS REQUIREMENTS (CA2)") == "Own funds requirements (CA2)"
