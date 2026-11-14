"""The Compare page and the Reference pages, through HTTP."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from dash_builders import HEADER, HEADER_FORM
from rwa_filer.boe.catalogue import rulebook_for_module
from rwa_filer.boe.engine import STATUS_FAIL
from rwa_filer.dash.compare import compare_page
from rwa_filer.taxonomy.pack import available_packs
from rwa_filer.workflow.diff import diff_returns

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.testclient import TestClient

    from rwa_filer.dash import OpenedReturn, Workspace


def _failed(opened: OpenedReturn) -> set[str]:
    report = opened.validation.report
    assert report is not None
    return {result.rule_id for result in report.results if result.status == STATUS_FAIL}


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------


def test_the_counts_are_the_diffs_own(
    workspace: Workspace, broken: OpenedReturn, clean_csv: Path
) -> None:
    # Arrange
    clean = workspace.open(clean_csv, HEADER)

    # Act
    view = compare_page(broken, clean)

    # Assert
    difference = diff_returns(broken.ret, clean.ret)
    assert view.counts == difference.counts()
    assert view.unchanged == difference.unchanged
    assert view.matched == difference.changes.height > 0


def test_a_fixed_return_lists_every_rule_it_fixed_and_breaks_nothing_new(
    workspace: Workspace, broken: OpenedReturn, clean_csv: Path
) -> None:
    # Arrange
    clean = workspace.open(clean_csv, HEADER)
    assert _failed(broken) and not _failed(clean)

    # Act
    forward = compare_page(broken, clean)
    backward = compare_page(clean, broken)

    # Assert — the same rules, fixed one way and newly broken the other.
    assert {rule.rule_id for rule in forward.fixed} == _failed(broken)
    assert forward.broken == () and backward.fixed == ()
    assert {rule.rule_id for rule in backward.broken} == _failed(broken)


def test_a_return_compared_with_itself_is_identical(
    workspace: Workspace, broken: OpenedReturn, broken_csv: Path
) -> None:
    # Arrange
    again = workspace.open(broken_csv, HEADER)

    # Act
    view = compare_page(broken, again)

    # Assert
    assert view.identical and view.cells == ()


def test_another_version_is_opened_and_compared_from_the_page(
    client: TestClient, broken: OpenedReturn, clean_csv: Path
) -> None:
    # Act
    response = client.post(
        f"/returns/{broken.return_id}/compare",
        data={"path": str(clean_csv), **HEADER_FORM},
        follow_redirects=False,
    )
    page = client.get(response.headers["location"]).text

    # Assert
    assert response.status_code == 303
    assert 'id="counts"' in page and 'id="rule-changes"' in page
    assert all(rule_id in page for rule_id in _failed(broken))


def test_the_kind_filter_lists_only_that_kind(
    client: TestClient, workspace: Workspace, broken: OpenedReturn, clean_csv: Path
) -> None:
    # Arrange — earlier the clean return, later the broken one: one cell changed, one added.
    clean = workspace.open(clean_csv, HEADER)
    base = f"/returns/{broken.return_id}/compare?against={clean.return_id}"
    assert compare_page(clean, broken).counts == {"added": 1, "removed": 0, "changed": 1}

    # Act
    page = client.get(f"{base}&kind=added").text
    table = page[page.index('id="changes"') :]

    # Assert
    kinds = re.findall(r'<span class="chip [^"]*">(changed|added|removed)</span>', table)
    assert kinds == ["added"]


def test_without_another_version_the_page_offers_to_open_one(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Act
    page = client.get(f"/returns/{broken.return_id}/compare").text

    # Assert
    assert "Open and compare" in page and "No other return is open" in page


# ---------------------------------------------------------------------------
# Reference
# ---------------------------------------------------------------------------


def test_the_reference_lists_every_packaged_pack(client: TestClient) -> None:
    # Act
    page = client.get("/reference").text

    # Assert
    for info in available_packs():
        assert f'href="/reference/{info.module}"' in page


def test_a_module_page_lists_its_tables_and_finds_rules_by_their_words(
    client: TestClient,
) -> None:
    # Arrange
    rulebook = rulebook_for_module("PRA001")
    enforced = rulebook.enforced("PRA001")
    target = next(rule for rule in enforced if rule.label and "PD floor" in rule.label)

    # Act
    page = client.get("/reference/PRA001?q=PD floor").text

    # Assert
    assert f"Rules enforced ({len(enforced):,})" in page
    assert "OF08.01.01.01" in page[page.index('id="tables"') :]
    assert target.rule_id in page[page.index('id="rules"') :]


def test_an_unknown_module_is_not_found(client: TestClient) -> None:
    assert client.get("/reference/NOPE").status_code == 404
