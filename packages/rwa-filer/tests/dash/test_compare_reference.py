"""The Compare page and the Reference pages, through HTTP."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from compare_builders import corporate_csv
from dash_builders import HEADER, HEADER_FORM
from rwa_filer.boe.engine import STATUS_FAIL
from rwa_filer.dash.compare import compare_page
from rwa_filer.extras import MissingExtraError
from rwa_filer.release import resolve_release, shipped_releases
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
# Compare — why two returns differ
# ---------------------------------------------------------------------------


def _pair(
    workspace: Workspace, tmp_path: Path, **later: object
) -> tuple[OpenedReturn, OpenedReturn]:
    """The old system's corporates return (50%, ECAI columns filled) and a later one."""
    (tmp_path / "old-system.csv").write_text(
        corporate_csv(risk_weight_row="0200", ecai_columns=True)
    )
    (tmp_path / "rwa-filer.csv").write_text(corporate_csv(**later))
    return (
        workspace.open(tmp_path / "old-system.csv", HEADER),
        workspace.open(tmp_path / "rwa-filer.csv", HEADER),
    )


def test_the_page_says_why_the_two_differ_and_what_each_finding_points_at(
    client: TestClient, workspace: Workspace, tmp_path: Path
) -> None:
    # Arrange — 75% in rwa-filer, and the ECAI columns left empty.
    earlier, later = _pair(workspace, tmp_path, risk_weight_row="0220")

    # Act
    page = client.get(f"/returns/{later.return_id}/compare?against={earlier.return_id}").text
    section = page[page.index('id="findings"') : page.index('id="rule-changes"')]

    # Assert
    assert "2 findings to explain" in section
    assert "Points at the inputs" in section
    assert (
        "Corporates row 0220 (75%) by rwa-filer.csv and row 0200 (50%) by old-system.csv" in section
    )
    assert "Points at rwa-filer.csv" in section
    assert "boe_b0703 · holds → breaks" in section


def test_the_category_filter_lists_only_that_category(
    client: TestClient, workspace: Workspace, tmp_path: Path
) -> None:
    # Arrange
    earlier, later = _pair(workspace, tmp_path, risk_weight_row="0220")
    base = f"/returns/{later.return_id}/compare?against={earlier.return_id}"

    # Act
    page = client.get(f"{base}&category=material").text
    table = page[page.index('id="changes"') :]

    # Assert
    rows = re.findall(r'<td class="small category">([^<·]+)', table)
    assert rows, "the material filter must list the material cells"
    assert {row.strip() for row in rows} == {"Material"}


def test_the_finding_filter_lists_that_findings_cells(
    client: TestClient, workspace: Workspace, tmp_path: Path
) -> None:
    # Arrange
    earlier, later = _pair(workspace, tmp_path, risk_weight_row="0220")
    comparison = workspace.comparison(earlier, later)
    expected = comparison.by_finding(2).height

    # Act
    page = client.get(
        f"/returns/{later.return_id}/compare?against={earlier.return_id}&finding=2"
    ).text
    table = page[page.index('id="changes"') :]

    # Assert
    assert "Cells of finding 2" in page
    assert table.count('href="#finding-2"') == expected > 0


def test_two_equivalent_returns_are_called_equivalent(
    client: TestClient, workspace: Workspace, tmp_path: Path
) -> None:
    earlier, later = _pair(workspace, tmp_path, risk_weight_row="0200", ecai_columns=True)

    page = client.get(f"/returns/{later.return_id}/compare?against={earlier.return_id}").text

    assert "<h2>Equivalent</h2>" in page


def test_a_rule_the_gateway_has_switched_off_is_named_on_the_page(
    client: TestClient, workspace: Workspace, tmp_path: Path
) -> None:
    """The 4.1.1 deny list has switched boe_b0710 off since 19 October 2026.

    Both returns break its published formula; the page judges them as the
    gateway runs them today, so it is named as switched off, not broken in both.
    """
    earlier, later = _pair(workspace, tmp_path, risk_weight_row="0200", ecai_columns=True)

    page = client.get(f"/returns/{later.return_id}/compare?against={earlier.return_id}").text
    also = page[page.index('id="also"') :]

    switched = re.search(r"Switched off at the gateway</strong> — ([^:]*):", also)
    assert switched is not None
    assert "boe_b0710" in switched.group(1).split(", ")
    broken = re.search(r"Broken in both</strong> — ([^:]*):", also)
    assert broken is None or "boe_b0710" not in broken.group(1).split(", ")


def test_a_pair_is_compared_once_however_often_the_page_is_drawn(
    workspace: Workspace, tmp_path: Path
) -> None:
    """Every rule runs on both returns; a filter click must not run them again."""
    earlier, later = _pair(workspace, tmp_path, risk_weight_row="0220")

    assert workspace.comparison(earlier, later) is workspace.comparison(earlier, later)
    assert workspace.comparison(later, earlier) is not workspace.comparison(earlier, later)


# ---------------------------------------------------------------------------
# Reference
# ---------------------------------------------------------------------------


def test_the_reference_lists_every_shipped_pack_under_its_release(client: TestClient) -> None:
    # Act
    page = client.get("/reference").text

    # Assert
    shipped = shipped_releases()
    packs = [info for info in available_packs() if info.version in shipped]
    assert packs, "no shipped pack: the page would be checked against nothing"
    for info in packs:
        assert f'href="/reference/{info.module}?release={info.version}"' in page


def test_a_module_page_lists_its_tables_and_finds_rules_by_their_words(
    client: TestClient,
) -> None:
    # Arrange
    rulebook = resolve_release("PRA001").rulebook
    assert rulebook is not None
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


def test_a_release_that_does_not_ship_the_module_is_not_found(client: TestClient) -> None:
    assert client.get("/reference/PRA001?release=0.0.0").status_code == 404


def test_a_workbook_without_the_excel_extra_is_refused_on_compare_too(
    client: TestClient,
    workspace: Workspace,
    broken: OpenedReturn,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — opening raises what readers.excel raises when openpyxl is missing.
    def missing_extra(*_args: object, **_kwargs: object) -> None:
        raise MissingExtraError(
            "Reading a workbook needs openpyxl, from the rwa-filer[excel] extra."
        )

    monkeypatch.setattr(workspace, "open", missing_extra)
    workbook = tmp_path / "filed.xlsx"
    workbook.write_bytes(b"PK")

    # Act
    response = client.post(f"/returns/{broken.return_id}/compare", data={"path": str(workbook)})

    # Assert
    assert response.status_code == 400
    assert 'id="compare-error"' in response.text and "rwa-filer[excel]" in response.text
