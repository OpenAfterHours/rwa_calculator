"""The read-only pages, through HTTP: open a return, its overview, its rules, its templates."""

from __future__ import annotations

import json
import re
from html import unescape
from typing import TYPE_CHECKING

import pytest

from dash_builders import HEADER, HEADER_FORM, make_fileable
from rwa_filer.boe.engine import STATUS_FAIL, STATUS_PASS
from rwa_filer.dash.views import rules_page
from rwa_filer.extras import MissingExtraError
from rwa_filer.release import shipped_releases

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


def test_the_evidence_behind_the_verdict_downloads_as_json_lines(
    client: TestClient, broken_csv: Path
) -> None:
    # Arrange
    overview = client.get(_open(client, broken_csv, **HEADER_FORM)).text
    (link,) = re.findall(r'id="evidence-download" href="([^"]+)"', overview)

    # Act
    response = client.get(link)

    # Assert
    lines = [json.loads(line) for line in response.text.splitlines()]
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert "broken.evidence.jsonl" in response.headers["content-disposition"]
    assert lines[0]["record"] == "header" and lines[-1]["record"] == "trailer"
    assert lines[0]["status"] == "BLOCKED"
    assert lines[0]["identity"]["input"]["file"] == "broken.csv"


def test_the_evidence_answers_for_the_return_with_its_drafted_overrides(
    client: TestClient, broken: OpenedReturn
) -> None:
    """Like every page of a return, the evidence is of what a build would file now."""
    # Arrange
    link = f"/returns/{broken.return_id}/evidence.jsonl"
    as_opened = json.loads(client.get(link).text.splitlines()[0])

    # Act
    make_fileable(client, broken)
    with_drafts = json.loads(client.get(link).text.splitlines()[0])

    # Assert — other figures, the same source file.
    assert (as_opened["status"], with_drafts["status"]) == ("BLOCKED", "INCOMPLETE")
    opened_input, drafted_input = as_opened["identity"]["input"], with_drafts["identity"]["input"]
    assert opened_input["facts_sha256"] != drafted_input["facts_sha256"]
    assert opened_input["file_sha256"] == drafted_input["file_sha256"] is not None


def test_an_unblocked_return_left_incomplete_says_so(client: TestClient, clean_csv: Path) -> None:
    """Nothing blocks the clean return, but OF 07.00 alone leaves out linked templates."""
    # Act
    page = unescape(client.get(_open(client, clean_csv, **HEADER_FORM)).text)

    # Assert
    assert 'data-status="INCOMPLETE"' in page
    assert "Validation status: INCOMPLETE — linked templates not reported" in page


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


def test_the_overview_names_each_linked_template_not_in_the_return(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange
    report = broken.validation.report
    assert report is not None
    assert report.templates_missing, "the fixture must leave one out"

    # Act
    page = client.get(f"/returns/{broken.return_id}").text

    # Assert
    assert 'id="missing-templates"' in page
    assert all(item.code in page for item in report.templates_missing)


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


def _cell_panel(client: TestClient, broken: OpenedReturn, **params: str) -> str:
    """The selected-cell panel of OF 07.00 r0010 c0010 on sheet 0008, unescaped."""
    page = client.get(
        f"/returns/{broken.return_id}/templates",
        params={"table": "OF07.00.01.01", "sheet": "0008", "row": "0010", "col": "0010", **params},
    ).text
    panel = page[page.index('aria-label="Selected cell"') :]
    return unescape(panel[: panel.index("</aside>")])


def test_the_cell_panel_explains_each_broken_rule_without_leaving_the_page(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange — boe_b0713, read at this cell, with the words and values a reader needs.
    report = broken.validation.report
    assert report is not None
    rule = next(item for item in report.results if item.rule_id == "boe_b0713")
    detail = rules_page(broken, rule_id=rule.rule_id).selected
    assert detail is not None
    assert detail.row.label
    assert detail.expression
    reading = next(
        failure
        for failure in rule.failures
        if any((a.sheet, a.row, a.column) == ("0008", "0010", "0010") for a in failure.addresses)
    )

    # Act
    panel = _cell_panel(client, broken)

    # Assert — its label on the card, and the rule in full in a section that expands in place.
    card = panel[panel.index(rule.rule_id) :]
    card = card[: card.index("</details>")]
    assert detail.row.label in card
    assert "<details" in card
    assert detail.expression in card
    assert all(cell in card for cell in reading.cells)


def test_the_cell_panel_still_links_each_rule_to_the_rules_page(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Act
    panel = _cell_panel(client, broken)

    # Assert
    assert f'href="/returns/{broken.return_id}/rules?rule=boe_b0713"' in panel


def test_the_focused_rule_opens_expanded_and_the_others_closed(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Act
    panel = _cell_panel(client, broken, focus="boe_b0713")

    # Assert
    opened = re.findall(r'<details class="mark-more" data-rule="([^"]+)" open>', panel)
    closed = re.findall(r'<details class="mark-more" data-rule="([^"]+)">', panel)
    assert opened == ["boe_b0713"]
    assert "boe_b0708" in closed


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


def test_a_workbook_without_the_excel_extra_is_refused_with_the_remedy(
    client: TestClient, workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading a workbook needs openpyxl; without it the page says how to get it."""
    # Arrange — opening raises what readers.excel raises when openpyxl is missing.
    message = "Reading a workbook needs openpyxl, from the rwa-filer[excel] extra."

    def missing_extra(*_args: object, **_kwargs: object) -> None:
        raise MissingExtraError(message, name="openpyxl")

    monkeypatch.setattr(workspace, "open", missing_extra)
    workbook = tmp_path / "return.xlsx"
    workbook.write_bytes(b"PK")

    # Act
    response = client.post("/open", data={"path": str(workbook)})

    # Assert
    assert response.status_code == 400
    assert "rwa-filer[excel]" in response.text


# ---------------------------------------------------------------------------
# Taxonomy releases
# ---------------------------------------------------------------------------


def test_the_open_page_offers_the_default_and_every_shipped_release(client: TestClient) -> None:
    page = client.get("/").text

    assert '<option value="">Default: the release live for the module</option>' in page
    for version in shipped_releases():
        assert f'<option value="{version}"' in page


def test_every_page_of_a_return_says_which_release_it_was_validated_against(
    client: TestClient, broken_csv: Path
) -> None:
    # Act
    location = _open(client, broken_csv, **HEADER_FORM)
    pages = [client.get(f"{location}{suffix}").text for suffix in ("", "/rules", "/templates")]

    # Assert
    for page in pages:
        chip = page[page.index('id="taxonomy-release"') :]
        assert "Taxonomy 4.1.1" in chip[:400] and "PRA001" in chip[:600]


def test_a_return_opened_against_a_release_that_is_not_shipped_is_refused(
    client: TestClient, broken_csv: Path
) -> None:
    # Act
    response = client.post(
        "/open", data={"path": str(broken_csv), **HEADER_FORM, "taxonomy": "9.9.9"}
    )

    # Assert
    assert response.status_code == 400
    assert "Taxonomy 9.9.9 is not shipped" in response.text


def test_switching_to_the_release_already_used_keeps_the_return(
    client: TestClient, broken_csv: Path
) -> None:
    location = _open(client, broken_csv, **HEADER_FORM)

    response = client.post(
        f"{location}/taxonomy", data={"taxonomy": "4.1.1"}, follow_redirects=False
    )

    assert response.status_code == 303 and response.headers["location"] == location


def test_switching_to_a_release_that_is_not_shipped_says_why(
    client: TestClient, broken_csv: Path
) -> None:
    location = _open(client, broken_csv, **HEADER_FORM)

    response = client.post(f"{location}/taxonomy", data={"taxonomy": "9.9.9"})

    assert response.status_code == 400
    assert "Taxonomy 9.9.9 is not shipped" in response.text


def test_a_return_reopened_against_a_named_release_is_kept_beside_the_first(
    workspace: Workspace, broken_csv: Path
) -> None:
    # Arrange
    first = workspace.open(broken_csv, HEADER)

    # Act
    second = workspace.reopen(first, "4.1.1")

    # Assert
    assert second.return_id != first.return_id
    assert (first.release.chosen_by, second.release.chosen_by) == ("default", "version")
    assert second.ret.header == first.ret.header
    assert {item.return_id for item in workspace.returns()} >= {first.return_id, second.return_id}


def test_the_rules_page_says_the_bank_switched_a_rule_off_and_when(
    client: TestClient, broken: OpenedReturn
) -> None:
    """boe_b0710 is on the Bank's validations deny list (known issue #22) from 19 October 2026."""
    # Arrange
    report = broken.validation.report
    assert report is not None
    result = next(item for item in report.results if item.rule_id == "boe_b0710")
    assert result.deny is not None, "the dashboard validates on today's date, after 2026-10-19"

    # Act
    page = unescape(
        client.get(f"/returns/{broken.return_id}/rules?status=NOT_EVALUATED&rule=boe_b0710").text
    )

    # Assert — on the list, and in the detail, with the date and the known issue.
    detail = page[page.index('id="rule-detail"') :]
    assert "Switched off by the Bank" in page
    assert (
        "This rule was deactivated by the Bank of England on 19 October 2026 "
        "(validations deny list; known issues log #22)."
    ) in detail
    assert "deactivated_by_publisher" in detail


def test_the_reference_page_marks_the_rules_on_the_banks_deny_list(client: TestClient) -> None:
    page = unescape(client.get("/reference/PRA001?release=4.1.1&q=boe_b0710").text)

    assert "On the Bank's deny list" in page
    assert "deactivated by the Bank of England on 19 October 2026" in page
