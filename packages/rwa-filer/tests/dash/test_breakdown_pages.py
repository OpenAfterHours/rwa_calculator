"""The dashboard with a return opened as a detail: the cell split, Investigate, and breaking down later."""

from __future__ import annotations

import re
from html import unescape
from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from dash_builders import BASE_URL
from detail_builders import (
    ASSET_FINANCE,
    CORPORATES,
    HEADER_FIELDS,
    HEADER_FORM,
    TABLE,
    write_detail,
)
from rwa_filer.dash import create_app
from rwa_filer.readers import DetailSpec

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.dash import OpenedReturn, Workspace


@pytest.fixture
def detail_csv(tmp_path: Path) -> Path:
    return write_detail(tmp_path / "detail.csv")


@pytest.fixture
def broken_down(workspace: Workspace, detail_csv: Path) -> OpenedReturn:
    return workspace.open(
        detail_csv, HEADER_FIELDS, detail=DetailSpec(breakdown=("business_unit", "source"))
    )


def _text(page: str) -> str:
    """A page's text with its tags and runs of space taken out."""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", page)))


def test_the_open_form_reads_a_file_as_a_detail_when_given_breakdown_columns(
    client: TestClient, detail_csv: Path
) -> None:
    # Act
    response = client.post(
        "/open",
        data={"path": str(detail_csv), **HEADER_FORM, "breakdown": "business_unit, source"},
        follow_redirects=False,
    )
    page = client.get(response.headers["location"]).text

    # Assert
    assert response.status_code == 303
    assert 'id="breakdown"' in page
    assert "Summed from 208 rows" in _text(page)


def test_the_open_form_refuses_an_answer_to_a_repeat_that_is_not_a_choice(
    client: TestClient, detail_csv: Path
) -> None:
    # Act
    response = client.post(
        "/open",
        data={"path": str(detail_csv), **HEADER_FORM, "breakdown": "source", "on_repeat": "skip"},
    )

    # Assert
    assert response.status_code == 400
    assert "is not stop, keep-one" in unescape(response.text)


def test_the_cell_panel_splits_the_picked_cell_and_names_who_breaks_its_rule(
    client: TestClient, broken_down: OpenedReturn
) -> None:
    # Act: the on-balance-sheet exposure value, which boe_b0556 reads.
    page = client.get(
        f"/returns/{broken_down.return_id}/templates",
        params={"table": TABLE, "sheet": CORPORATES, "row": "0070", "col": "0200"},
    ).text

    # Assert
    text = _text(page)
    assert 'id="cell-breakdown"' in page
    assert "Where this figure comes from" in text
    assert "All of the 100,000 is in Asset Finance." in text
    assert "The other 3 business_unit members meet the rule on their own figures." in text


def test_the_cell_panel_splits_by_the_column_the_address_names(
    client: TestClient, broken_down: OpenedReturn
) -> None:
    # Act
    page = client.get(
        f"/returns/{broken_down.return_id}/templates",
        params={"table": TABLE, "sheet": CORPORATES, "row": "0070", "col": "0200", "by": "source"},
    ).text

    # Assert
    assert "All of the 100,000 is in LEASING." in _text(page)


def test_investigate_sets_each_broken_rule_against_the_members_that_break_it(
    client: TestClient, broken_down: OpenedReturn
) -> None:
    # Act
    page = client.get(f"/returns/{broken_down.return_id}/investigate").text

    # Assert
    text = _text(page)
    assert 'id="matrix"' in page
    assert "22 of 22" in text, "every break traced to one unit"
    assert "Hold in the return, break inside a member" in text and "boe_b0708" in text
    assert f"On {ASSET_FINANCE}'s figures alone" in text, "the first breaking member is picked"


def test_investigate_works_the_attribution_out_once(
    client: TestClient, workspace: Workspace, broken_down: OpenedReturn
) -> None:
    # Act
    client.get(f"/returns/{broken_down.return_id}/investigate")
    working = workspace.working(broken_down)
    first = workspace.kept_attribution(working, "business_unit")
    client.get(f"/returns/{broken_down.return_id}/investigate?m=1")

    # Assert
    assert first is not None
    assert workspace.kept_attribution(working, "business_unit") is first


def test_investigate_filters_mixed_occurrences_and_keeps_the_full_attribution(
    client: TestClient, workspace: Workspace, tmp_path: Path
) -> None:
    source = tmp_path / "mixed-detail.csv"
    source.write_text(
        "table,sheet,row,column,value,team\n"
        "OF08.01.01.01,0006,0010,0101,0,Loans\n"
        "OF08.01.01.01,0006,0010,0102,1,Loans\n"
    )
    opened = workspace.open(source, HEADER_FIELDS, detail=DetailSpec(breakdown=("team",)))
    base = f"/returns/{opened.return_id}"
    original = client.get(f"{base}/investigate.csv").text
    assert len([line for line in original.splitlines() if "boe_b1039" in line]) == 2
    working = workspace.working(opened)
    kept = workspace.kept_attribution(working, "team")

    client.post(f"{base}/review", data={"hide_zero": "1", "section": "investigate"})
    filtered = client.get(f"{base}/investigate.csv").text
    (nonzero,) = [line for line in filtered.splitlines() if "boe_b1039" in line]
    assert "0102" in nonzero
    assert workspace.kept_attribution(working, "team") is kept
    client.post(f"{base}/review", data={"reset": "1", "section": "investigate"})
    assert client.get(f"{base}/investigate.csv").text == original


def test_investigate_runs_behind_the_progress_page_when_it_takes_a_while(
    workspace: Workspace, broken_down: OpenedReturn
) -> None:
    # Arrange
    impatient = TestClient(create_app(workspace, progress_after=0.0), base_url=BASE_URL)

    # Act
    response = impatient.get(
        f"/returns/{broken_down.return_id}/investigate", follow_redirects=False
    )

    # Assert
    assert response.status_code == 303
    assert response.headers["location"].startswith("/tasks/")


def test_the_breaks_download_as_csv_for_one_member(
    client: TestClient, broken_down: OpenedReturn
) -> None:
    # Arrange
    client.get(f"/returns/{broken_down.return_id}/investigate")

    # Act
    response = client.get(f"/returns/{broken_down.return_id}/investigate.csv?m=0")

    # Assert
    lines = response.text.splitlines()
    assert response.headers["content-type"].startswith("text/csv")
    assert lines[0].startswith("business_unit,rule_id,severity,in_the_return")
    assert all(line.startswith(ASSET_FINANCE) for line in lines[1:])
    assert any(",boe_b0471,ERROR,breaks," in line and ",yes," in line for line in lines)


def test_a_return_opened_without_a_breakdown_offers_its_other_columns(
    client: TestClient, workspace: Workspace, detail_csv: Path
) -> None:
    # Arrange
    opened = workspace.open(detail_csv, HEADER_FIELDS)

    # Act
    overview = client.get(f"/returns/{opened.return_id}").text
    investigate = client.get(f"/returns/{opened.return_id}/investigate").text

    # Assert
    assert 'id="breakdown-offer"' in overview
    assert 'name="breakdown" value="business_unit"' in investigate
    assert 'name="breakdown" value="line_id"' in investigate


def test_breaking_a_return_down_later_opens_it_again_beside_the_first(
    client: TestClient, workspace: Workspace, detail_csv: Path
) -> None:
    # Arrange
    opened = workspace.open(detail_csv, HEADER_FIELDS)

    # Act
    response = client.post(
        f"/returns/{opened.return_id}/breakdown",
        data={"breakdown": ["business_unit"], "line_ref": "line_id", "on_repeat": "stop"},
        follow_redirects=False,
    )

    # Assert
    location = response.headers["location"]
    again = workspace.get(location.split("/")[2])
    assert response.status_code == 303 and location.endswith("/investigate")
    assert again is not None and again.detail is not None
    assert again.detail.spec == DetailSpec(breakdown=("business_unit",), line_ref="line_id")
    assert workspace.get(opened.return_id) is opened


def test_breaking_down_by_nothing_is_refused(
    client: TestClient, workspace: Workspace, detail_csv: Path
) -> None:
    # Arrange
    opened = workspace.open(detail_csv, HEADER_FIELDS)

    # Act
    response = client.post(f"/returns/{opened.return_id}/breakdown", data={"line_ref": ""})

    # Assert
    assert response.status_code == 400
    assert "Choose at least one column" in response.text


def test_a_new_draft_is_a_new_attribution(workspace: Workspace, broken_down: OpenedReturn) -> None:
    # Arrange
    from rwa_filer.workflow.adjustments import Adjustment

    before = workspace.attribution(workspace.working(broken_down), "business_unit")
    workspace.set_adjustment(
        broken_down.return_id,
        Adjustment(TABLE, "0010", "0200", "test", sheet=CORPORATES, value=1.0),
    )

    # Act
    after = workspace.attribution(workspace.working(broken_down), "business_unit")

    # Assert
    assert after is not before
    assert any(item.unexplained for item in after.broken)
