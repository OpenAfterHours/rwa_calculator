"""Share the occurrences visible on the Rules tab, including those beyond its page limits."""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

from openpyxl import load_workbook

from dash_builders import HEADER, make_fileable
from detail_builders import HEADER_FIELDS
from rwa_filer.dash import views
from rwa_filer.readers import DetailSpec

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch
    from starlette.testclient import TestClient

    from rwa_filer.dash import OpenedReturn, Workspace


def test_export_includes_rules_and_occurrences_beyond_display_limits(
    client: TestClient, workspace: Workspace, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    source = tmp_path / "unadjusted.csv"
    source.write_text(
        "table,sheet,row,column,value\n"
        + "".join(
            f"OF08.01.01.01,{sheet},{row},{column},{value}\n"
            for sheet in ("0001", "0002", "0010")
            for row in ("0001", "0010", "0020", "0070")
            for column, value in (("0251", 100), ("0260", 999000))
        )
    )
    opened = workspace.open(source, HEADER)
    monkeypatch.setattr(views, "RULES_PER_PAGE", 1)
    base = f"/returns/{opened.return_id}/rules"
    filters = {"template": "OF08.01.01", "q": "boe_b0751"}
    assert "Export failures" in client.get(base, params=filters).text
    preview = client.get(base + "/export", params=filters)
    assert "12 occurrences" in preview.text
    report = client.get(base + "/export", params={**filters, "download": "md"})
    assert report.status_code == 200 and "attachment" in report.headers["content-disposition"]
    assert "row 0070, sheet 0010" in report.text
    assert "999000" in report.text.replace(",", "")
    expected = {r.rule_id for r in opened.validation.report.results if r.status == "FAIL"}
    assert len(expected) > 1
    book = load_workbook(BytesIO(client.get(base + "/export?download=xlsx&page=2").content))
    rules = list(book["Rules"].values)
    assert {row[0] for row in rules[1:]} == expected
    assert sum(row[0] == "boe_b0751" for row in book["Failures"].values) == 12


def test_export_filters_the_breakdown_with_its_occurrence(
    client: TestClient, workspace: Workspace, tmp_path: Path
) -> None:
    source = tmp_path / "detail.csv"
    source.write_text(
        "table,sheet,row,column,value,team\n"
        "OF08.01.01.01,0006,0010,0101,0,Hidden team\n"
        "OF08.01.01.01,0006,0010,0102,1,Loans\n"
    )
    opened = workspace.open(source, HEADER_FIELDS, detail=DetailSpec(breakdown=("team",)))
    base = f"/returns/{opened.return_id}"
    client.post(base + "/review", data={"hide_zero": "1", "section": "rules"})
    params = {"q": "boe_b1039", "by": "team", "download": "xlsx"}
    book = load_workbook(BytesIO(client.get(base + "/rules/export", params=params).content))
    rows = list(book["Failures"].values)
    assert len(rows) == 2 and "c0102" in rows[1][4] and "c0101" not in rows[1][4]
    assert "Loans" in str(list(book["Reporting units"].values))
    assert "Hide zero-only" in str(list(book["Summary"].values))
    rule_page = client.get(base + "/rules", params={"q": "boe_b1039", "by": "team"}).text
    assert "Loans" in rule_page and "Reporting-unit breakdown · team" in rule_page
    assert 'value="team" selected' in rule_page
    preview = client.get(base + "/rules/export", params={"q": "boe_b1039", "by": "team"})
    assert "Loans" in preview.text and 'name="hide_zero" value="1"' in preview.text
    client.post(base + "/review", data={"reset": "1", "section": "rules"})
    snapshot = client.get(
        base + "/rules/export", params={**params, "hide_zero": "1", "download": "md"}
    )
    assert "Loans" in snapshot.text and "column of v0 0101" not in snapshot.text


def test_empty_export_and_unknown_format(client: TestClient, broken: OpenedReturn) -> None:
    base = f"/returns/{broken.return_id}/rules/export"
    assert "No failures match" in client.get(base + "?q=no-such-rule").text
    assert client.get(base + "?download=pdf").status_code == 400


def test_search_is_literal_excel_text(client: TestClient, broken: OpenedReturn) -> None:
    response = client.get(
        f"/returns/{broken.return_id}/rules/export", params={"q": "{=1+1}", "download": "xlsx"}
    )
    book = load_workbook(BytesIO(response.content))
    cell = next(row[1] for row in book["Summary"].rows if row[0].value == "Search")
    assert (cell.value, cell.data_type) == ("{=1+1}", "s")


def test_download_uses_effective_severity_and_working_return(
    client: TestClient, broken: OpenedReturn
) -> None:
    base = f"/returns/{broken.return_id}"
    report = broken.validation.report
    expected = {r.rule_id for r in report.results if r.status == "FAIL" and r.severity == "ERROR"}
    assert expected and any(r.status == "FAIL" and r.severity == "WARNING" for r in report.results)
    client.post(base + "/review", data={"errors_only": "1", "section": "rules"})
    # Return-wide errors only takes precedence over a stale Warning selection.
    response = client.get(base + "/rules/export?severity=WARNING&download=xlsx")
    book = load_workbook(BytesIO(response.content))
    assert {row[0] for row in list(book["Rules"].values)[1:]} == expected
    assert "Reporting units" not in book.sheetnames
    make_fileable(client, broken)
    adjusted = client.get(base + "/rules/export?download=md")
    assert "With drafted overrides" in adjusted.text and "0 rules" in adjusted.text
