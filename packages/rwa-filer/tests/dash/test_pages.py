"""The read-only pages, through HTTP: open a return, its overview, its rules, its templates."""

from __future__ import annotations

import re
from html import unescape
from typing import TYPE_CHECKING

from dash_builders import HEADER_FORM
from rwa_filer.boe.engine import STATUS_FAIL, STATUS_PASS

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.testclient import TestClient

    from rwa_filer.dash import OpenedReturn, Workspace


def _open(client: TestClient, path: Path, **fields: str) -> str:
    """Open ``path`` through the form and return the address it redirects to."""
    response = client.post("/open", data={"path": str(path), **fields}, follow_redirects=False)
    assert response.status_code == 303, response.text
    return response.headers["location"]


# ---------------------------------------------------------------------------
# Opening a return
# ---------------------------------------------------------------------------


def test_the_open_page_offers_every_packaged_module(client: TestClient) -> None:
    # Act
    page = client.get("/").text

    # Assert
    assert '<option value="PRA001"' in page and '<option value="LVR001"' in page


def test_a_fact_table_with_its_header_opens_on_its_overview(
    client: TestClient, broken_csv: Path
) -> None:
    # Act
    location = _open(client, broken_csv, **HEADER_FORM)
    page = client.get(location).text

    # Assert
    assert re.fullmatch(r"/returns/[0-9a-f]{8}", location)
    assert 'data-verdict="blocked"' in page
    assert "PRA001 return at 31 March 2027" in page


def test_an_uploaded_file_is_opened_like_a_named_one(
    client: TestClient, workspace: Workspace, broken_csv: Path
) -> None:
    # Act
    response = client.post(
        "/open",
        files={"file": ("../../etc/broken.csv", broken_csv.read_bytes())},
        data=HEADER_FORM,
        follow_redirects=False,
    )

    # Assert — opened, and kept inside the workspace under a name of its own.
    assert response.status_code == 303
    (opened,) = workspace.returns()
    assert opened.path.is_relative_to(workspace.directory)
    assert opened.path.name == "broken.csv"


def test_a_return_nothing_blocks_reads_submittable(client: TestClient, clean_csv: Path) -> None:
    # Act
    page = client.get(_open(client, clean_csv, **HEADER_FORM)).text

    # Assert
    assert 'data-verdict="submittable"' in page
    assert "SUBMITTABLE" in page


def test_a_fact_table_without_its_header_is_refused_with_the_reason(
    client: TestClient, broken_csv: Path
) -> None:
    # Act
    response = client.post("/open", data={"path": str(broken_csv)})

    # Assert
    assert response.status_code == 400
    assert "carries no header" in response.text


def test_a_missing_file_is_refused_not_a_traceback(client: TestClient, tmp_path: Path) -> None:
    # Act
    response = client.post("/open", data={"path": str(tmp_path / "absent.xbrl")})

    # Assert
    assert response.status_code == 400
    assert "file not found" in response.text


def test_a_reference_date_that_is_not_a_date_is_refused(
    client: TestClient, broken_csv: Path
) -> None:
    # Act
    response = client.post(
        "/open", data={"path": str(broken_csv), **HEADER_FORM, "reference_date": "31/03/2027"}
    )

    # Assert
    assert response.status_code == 400
    assert "is not a date" in unescape(response.text)


def test_neither_a_file_nor_a_path_asks_for_one(client: TestClient) -> None:
    # Act
    response = client.post("/open", data={})

    # Assert
    assert response.status_code == 400
    assert "Choose a file to open" in response.text


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def test_the_overview_states_how_many_rules_ran_and_why_others_did_not(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange
    report = broken.validation.report
    assert report is not None and report.not_evaluated_reasons()

    # Act
    page = client.get(f"/returns/{broken.return_id}").text

    # Assert — the executed count, and every not-evaluated reason, are on the page.
    assert f"{report.rules_executed:,}" in page
    for reason in report.not_evaluated_reasons():
        assert reason in page


def test_the_overview_lists_each_broken_rule(client: TestClient, broken: OpenedReturn) -> None:
    # Arrange
    report = broken.validation.report
    assert report is not None
    failed = [result.rule_id for result in report.results if result.status == STATUS_FAIL]
    assert failed, "the fixture must break a rule, or this test checks nothing"

    # Act
    page = client.get(f"/returns/{broken.return_id}").text

    # Assert
    assert all(rule_id in page for rule_id in failed)


def test_an_unknown_return_is_not_found(client: TestClient) -> None:
    # Act
    response = client.get("/returns/00000000/rules")

    # Assert
    assert response.status_code == 404
    assert "No return is open under that address" in response.text


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def test_the_rules_page_details_a_broken_rule_and_its_cells(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange
    report = broken.validation.report
    assert report is not None
    result = next(item for item in report.results if item.status == STATUS_FAIL)
    address = result.failures[0].addresses[0]

    # Act
    page = unescape(client.get(f"/returns/{broken.return_id}/rules?rule={result.rule_id}").text)

    # Assert — the rule's own text, and a link to each cell it read on the grid.
    detail = page[page.index('id="rule-detail"') :]
    assert result.rule_id in detail
    assert (
        f"table={address.table}" in detail and f"row={address.row}&col={address.column}" in detail
    )


def test_the_rules_page_filters_by_status(client: TestClient, broken: OpenedReturn) -> None:
    # Arrange
    report = broken.validation.report
    assert report is not None
    passed = next(item.rule_id for item in report.results if item.status == STATUS_PASS)
    failed = next(item.rule_id for item in report.results if item.status == STATUS_FAIL)

    # Act
    page = client.get(f"/returns/{broken.return_id}/rules?status=PASS&rule={passed}").text
    listed = page[: page.index('id="rule-detail"')]

    # Assert
    assert passed in listed and failed not in listed


def test_the_rules_page_searches_rule_ids(client: TestClient, broken: OpenedReturn) -> None:
    # Arrange
    report = broken.validation.report
    assert report is not None
    first, second = [item.rule_id for item in report.results if item.status == STATUS_FAIL][:2]

    # Act
    page = client.get(f"/returns/{broken.return_id}/rules?q={first}").text
    listed = page[: page.index('id="rule-detail"')]

    # Assert
    assert first in listed and second not in listed


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def test_the_grid_marks_a_cell_a_broken_rule_read(client: TestClient, broken: OpenedReturn) -> None:
    # Arrange — a reported cell read by a broken Error rule.
    report = broken.validation.report
    assert report is not None
    address = next(
        address
        for result in report.results
        if result.status == STATUS_FAIL and result.severity == "ERROR"
        for failure in result.failures
        for address in failure.addresses
        if address.reported
    )

    # Act
    page = client.get(
        f"/returns/{broken.return_id}/templates",
        params={
            "table": address.table,
            "sheet": address.sheet or "",
            "row": address.row,
            "col": address.column,
        },
    ).text

    # Assert — the cell's <td> carries the error mark and the selection.
    cell = re.search(
        rf'<td class="([^"]*)"><a [^>]*aria-label="Row {address.row}, column {address.column}[,"]',
        page,
    )
    assert cell is not None
    assert "cell-error" in cell.group(1) and "cell-selected" in cell.group(1)


def test_the_grid_greys_cells_the_sheet_does_not_accept(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange — a cell of OF 07.00 the taxonomy does not accept on sheet 0008.
    pack = broken.pack
    table = pack.tables["OF07.00.01.01"]
    accepted = {
        (row, column)
        for row, column in pack.cells.filter(
            (pack.cells["table"] == table.code) & (pack.cells["sheet"] == "0008")
        )
        .select("row", "column")
        .iter_rows()
    }
    locked = next(
        (row, column)
        for row in table.row_codes
        for column in table.column_codes
        if (row, column) not in accepted
    )

    # Act
    page = client.get(
        f"/returns/{broken.return_id}/templates", params={"table": table.code, "sheet": "0008"}
    ).text

    # Assert
    cell = re.search(
        rf'<td class="([^"]*)"><a [^>]*aria-label="Row {locked[0]}, column {locked[1]}[,"]', page
    )
    assert cell is not None and "cell-locked" in cell.group(1)


def test_focusing_one_rule_leaves_the_others_cells_unmarked(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange — two rules that read different cells of sheet 0008.
    marks_page = client.get(
        f"/returns/{broken.return_id}/templates", params={"table": "OF07.00.01.01", "sheet": "0008"}
    ).text
    focused = client.get(
        f"/returns/{broken.return_id}/templates",
        params={"table": "OF07.00.01.01", "sheet": "0008", "focus": "boe_b0721"},
    ).text

    # Assert — boe_b0708 marks column 0040; boe_b0721 does not read it.
    def column_0040(page: str) -> str:
        match = re.search(
            r'<td class="([^"]*)"><a [^>]*aria-label="Row 0010, column 0040[,"]', page
        )
        assert match is not None
        return match.group(1)

    assert "cell-error" in column_0040(marks_page)
    assert "cell-error" not in column_0040(focused)


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


def test_dark_is_the_default_look_and_light_is_remembered(client: TestClient) -> None:
    # Act
    before = client.get("/").text
    switch = client.post("/theme", data={"theme": "light", "next": "/"}, follow_redirects=False)
    after = client.get("/").text

    # Assert
    assert '<html lang="en" class="t-dark">' in before
    assert switch.status_code == 303
    assert '<html lang="en" class="t-light">' in after


def test_the_theme_switch_never_redirects_off_the_dashboard(client: TestClient) -> None:
    # Act
    response = client.post(
        "/theme", data={"theme": "dark", "next": "//elsewhere.example/"}, follow_redirects=False
    )

    # Assert
    assert response.headers["location"] == "/"
