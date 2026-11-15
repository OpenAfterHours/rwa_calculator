"""Every page of a return shows it as a build would file it now — with its drafted overrides.

A preparer drafts an override on the template grid to clear a break, then goes
back to the overview, the rules and the grid to see where the return stands.
Each of those pages, and the verdict in the top bar, must answer for the return
with the overrides applied: an override that clears a break clears it
everywhere, and withdrawing it brings the break back everywhere. The Build &
sign off page says what the overrides change without being asked, and never
counts a broken rule the overrides merely stopped from running as fixed.

The return is BROKEN from ``dash_builders``: three rules break as it comes, and
the two overrides ``make_fileable`` drafts leave nothing blocking it.
"""

from __future__ import annotations

import re
from html import unescape
from typing import TYPE_CHECKING

import pytest

from dash_builders import CELL, draft, make_fileable
from rwa_filer.boe.engine import STATUS_FAIL
from rwa_filer.workflow.adjustments import Adjustment

if TYPE_CHECKING:
    from starlette.testclient import TestClient

    from rwa_filer.dash import OpenedReturn, Workspace

#: Every page of an opened return, by the suffix of its address.
RETURN_PAGES = ("", "/rules", "/templates", "/filing", "/compare", "/referee")
SHEET_0008 = {"table": "OF07.00.01.01", "sheet": "0008"}


def _failed(opened: OpenedReturn) -> set[str]:
    """The rules ``opened`` breaks as it was opened."""
    report = opened.validation.report
    assert report is not None
    return {result.rule_id for result in report.results if result.status == STATUS_FAIL}


def _top_bar_verdict(page: str) -> str:
    """The verdict chip beside the return's name in the top bar."""
    match = re.search(
        r'<div class="file-chip">.*?<span class="chip [^"]*">([^<]+)</span>', page, re.S
    )
    assert match is not None
    return match.group(1)


def _cell_classes(page: str, column: str) -> str:
    """The classes of row 0010's cell in ``column`` on the grid."""
    match = re.search(
        rf'<td class="([^"]*)"[^>]*><a [^>]*aria-label="Row 0010, column {column}[,"]', page
    )
    assert match is not None
    return match.group(1)


def _changes(page: str) -> dict[str, str]:
    """Each rule the Build & sign off page says the overrides change, and how."""
    found = re.findall(r'data-change="([a-z]+)" data-rule="([^"]+)"', page)
    return {rule: change for change, rule in found}


# ---------------------------------------------------------------------------
# Every page answers for the return with its overrides
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", RETURN_PAGES, ids=lambda suffix: suffix or "/overview")
def test_every_page_of_a_return_carries_the_verdict_with_its_drafted_overrides(
    client: TestClient, broken: OpenedReturn, suffix: str
) -> None:
    # Arrange
    address = f"/returns/{broken.return_id}{suffix}"
    before = client.get(address).text
    make_fileable(client, broken)

    # Act
    after = client.get(address).text

    # Assert — the top bar follows the overrides, and the page says it does.
    assert _top_bar_verdict(before) == "BLOCKED"
    assert _top_bar_verdict(after) == "SUBMITTABLE"
    assert 'id="overrides-applied"' not in before
    assert 'id="overrides-applied"' in after


def test_the_overview_verdict_follows_the_drafted_overrides(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange
    overview = f"/returns/{broken.return_id}"
    before = client.get(overview).text
    make_fileable(client, broken)

    # Act
    after = unescape(client.get(overview).text)

    # Assert
    assert 'data-verdict="blocked"' in before
    assert 'data-verdict="submittable"' in after
    blocking = len(broken.validation.blocking)
    assert f"As opened: {blocking} blocking" in after


def test_a_rule_the_overrides_fix_is_no_longer_listed_as_failed(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange
    fixed = _failed(broken)
    rules = f"/returns/{broken.return_id}/rules"
    make_fileable(client, broken)

    # Act
    failed = client.get(rules, params={"status": "FAIL"}).text
    passed = {rule: client.get(rules, params={"status": "PASS", "q": rule}).text for rule in fixed}

    # Assert — gone from the broken rules, and listed among those that hold.
    assert fixed
    assert not [rule for rule in fixed if rule in failed]
    assert all(rule in page[: page.index('id="rule-detail"')] for rule, page in passed.items())


def test_the_grid_unmarks_the_cells_of_a_rule_the_overrides_fix(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange — boe_b0708 marks column 0040 as the return was opened.
    grid = f"/returns/{broken.return_id}/templates"
    before = client.get(grid, params=SHEET_0008).text
    make_fileable(client, broken)

    # Act
    after = client.get(grid, params=SHEET_0008).text

    # Assert — the break's cell is clear, and the overridden cell still says so.
    assert "cell-error" in _cell_classes(before, "0040")
    assert "cell-error" not in _cell_classes(after, "0040")
    assert "cell-adjusted" in _cell_classes(after, "0010")


def test_withdrawing_the_overrides_brings_back_the_return_as_opened(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange
    overview = f"/returns/{broken.return_id}"
    make_fileable(client, broken)
    fileable = client.get(overview).text

    # Act
    for column in ("0010", "0030"):
        client.post(f"/returns/{broken.return_id}/adjustments/drop", data={**CELL, "col": column})
    withdrawn = client.get(overview).text

    # Assert
    assert 'data-verdict="submittable"' in fileable
    assert 'data-verdict="blocked"' in withdrawn
    assert 'id="overrides-applied"' not in withdrawn


def test_the_open_page_lists_a_return_with_the_verdict_its_overrides_give_it(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange
    make_fileable(client, broken)

    # Act
    page = client.get("/").text

    # Assert
    item = page[page.index(f'class="rule-item" href="/returns/{broken.return_id}"') :]
    item = item[: item.index("</a>")]
    assert "Submittable" in item and "2 overrides" in item


def test_compare_says_it_compares_the_files_as_opened_while_overrides_are_drafted(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange
    compare = f"/returns/{broken.return_id}/compare"
    undrafted = client.get(compare).text
    make_fileable(client, broken)

    # Act
    drafted = client.get(compare).text

    # Assert
    assert 'id="compare-as-opened"' not in undrafted
    assert 'id="compare-as-opened"' in drafted


# ---------------------------------------------------------------------------
# Build & sign off: what the overrides change
# ---------------------------------------------------------------------------


def test_the_build_page_says_what_the_overrides_change_without_being_asked(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange
    fixed = _failed(broken)
    make_fileable(client, broken)

    # Act
    page = unescape(client.get(f"/returns/{broken.return_id}/filing").text)

    # Assert — every break as opened now holds, and nothing newly breaks.
    blocking = len(broken.validation.blocking)
    assert "With these overrides: nothing blocks submission" in page
    assert f"Blocking findings {blocking} → 0" in page
    changes = _changes(page)
    assert {rule for rule, change in changes.items() if change == "fixed"} == fixed
    assert "broken" not in changes.values()


def test_a_broken_rule_the_overrides_stop_from_running_is_not_counted_as_fixed(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange — take out every figure the broken rules read, instead of correcting one.
    failed = _failed(broken)
    draft(client, broken, "0010", remove="yes", reason="Not ours to report")
    draft(client, broken, "0030", remove="yes", reason="Follows the exposure")

    # Act
    page = unescape(client.get(f"/returns/{broken.return_id}/filing").text)

    # Assert — each break is reported as no longer running, none as fixed.
    changes = _changes(page)
    assert failed
    assert {rule: changes.get(rule) for rule in failed} == dict.fromkeys(failed, "stopped")
    assert "fixed" not in changes.values()


def test_write_it_anyway_is_offered_only_while_the_overrides_leave_the_return_blocked(
    client: TestClient, broken: OpenedReturn
) -> None:
    # Arrange
    filing = f"/returns/{broken.return_id}/filing"
    blocked = client.get(filing).text
    make_fileable(client, broken)

    # Act
    fileable = client.get(filing).text

    # Assert
    assert 'name="force"' in blocked
    assert 'name="force"' not in fileable


# ---------------------------------------------------------------------------
# The workspace validates once per change of the overrides
# ---------------------------------------------------------------------------


def test_the_return_with_its_overrides_is_validated_once_per_change_of_them(
    workspace: Workspace, broken: OpenedReturn
) -> None:
    # Arrange
    override = Adjustment(
        table="OF07.00.01.01", sheet="0008", row="0010", column="0010", value=0.0, reason="Zero"
    )

    # Act
    undrafted = workspace.working(broken)
    workspace.set_adjustment(broken.return_id, override)
    drafted = workspace.working(broken)
    again = workspace.working(broken)
    workspace.drop_adjustment(broken.return_id, override.cell)
    withdrawn = workspace.working(broken)

    # Assert — nothing drafted is the return as opened; a draft is validated once.
    assert undrafted.current is broken and withdrawn.current is broken
    assert drafted.current is not broken and again is drafted
    assert [item.adjustment for item in drafted.applied] == [override]
