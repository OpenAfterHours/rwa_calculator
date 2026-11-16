"""
Long work in the dashboard: opening, re-validating and building a return show their progress.

A full PRA001 return takes tens of seconds to validate. Before, the form that
asked for it simply did not answer until it was done, and the page looked
frozen. Now the work runs as a task: a form waits a moment for it, and work
still going after that moment sends the person to a progress page that says
which step is under way and how many rules are evaluated.

How the tests catch the work mid-run without racing it: the REAL validation
runs, and the progress callback it is handed pauses on a gate partway through
the rules (``_Pause``). The page is read while the work is held there, so what
it shows is the engine's own count, not one invented for the test. Every client
here waits zero seconds, so the progress page is always what a form answers
with while the work is held.
"""

from __future__ import annotations

import re
import threading
import time
from html import unescape
from typing import TYPE_CHECKING, Any

import pytest
from starlette.testclient import TestClient

from dash_builders import BASE_URL, CELL, GRID, HEADER, HEADER_FORM
from rwa_filer.dash import create_app, filing_pages
from rwa_filer.progress import PHASE_READING, PHASE_RULES, PHASE_STRUCTURE, PHASE_WRITING

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from rwa_filer.dash import OpenedReturn, Workspace
    from rwa_filer.progress import Progress, ProgressCallback

#: The rule the work is held after: far enough in that the count has moved.
HELD_AT = 5
#: Seconds any wait in these tests may last before it is a failure, not a hang.
PATIENCE = 60.0


class _Pause:
    """A progress callback that holds the work after ``HELD_AT`` rules, until released."""

    def __init__(self) -> None:
        self.reached = threading.Event()
        self.released = threading.Event()
        self.heard: list[Progress] = []

    def watching(self, progress: ProgressCallback | None) -> ProgressCallback:
        """``progress``, held partway through the rules."""

        def watched(event: Progress) -> None:
            self.heard.append(event)
            if progress is not None:
                progress(event)
            if event.phase == PHASE_RULES and event.done == HELD_AT:
                self.reached.set()
                self.released.wait(PATIENCE)

        return watched

    @property
    def total(self) -> int:
        """How many rules the engine said it would evaluate."""
        return next(event.total for event in self.heard if event.phase == PHASE_RULES)


@pytest.fixture
def eager(workspace: Workspace) -> TestClient:
    """A client whose forms never wait for their work."""
    return TestClient(create_app(workspace, progress_after=0.0), base_url=BASE_URL)


@pytest.fixture
def pause(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> _Pause:
    """Opening a return in ``workspace`` holds partway through its rules."""
    held, real_open = _Pause(), workspace.open

    def open_held(path: Path, fields: Any = None, **options: Any) -> OpenedReturn:
        options["progress"] = held.watching(options.get("progress"))
        return real_open(path, fields, **options)

    monkeypatch.setattr(workspace, "open", open_held)
    return held


def _settle(client: TestClient, response: httpx.Response) -> httpx.Response:
    """Follow a form's answer to where its work ends, reloading the progress page until it moves on."""
    deadline = time.monotonic() + PATIENCE
    while response.status_code == 303 and response.headers["location"].startswith("/tasks/"):
        location = response.headers["location"]
        response = client.get(location, follow_redirects=False)
        while response.status_code == 200:  # still the progress page
            assert time.monotonic() < deadline, "the work never ended"
            time.sleep(0.02)
            response = client.get(location, follow_redirects=False)
    return response


def _held_page(client: TestClient, response: httpx.Response, pause: _Pause) -> str:
    """The progress page a form was sent to, read while its work is held."""
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    assert location.startswith("/tasks/"), location
    assert pause.reached.wait(PATIENCE), "the work never reached the rules"
    page = client.get(location)
    assert page.status_code == 200
    return unescape(page.text)


def _text(page: str) -> str:
    """What a person reads on ``page``: its tags dropped, its spaces collapsed."""
    return " ".join(re.sub(r"<[^>]+>", " ", page).split())


def _state(page: str, phase: str) -> str:
    """The state the progress page gives ``phase``'s step."""
    marker = f'data-phase="{phase}" data-state="'
    start = page.index(marker) + len(marker)
    return page[start : page.index('"', start)]


# ---------------------------------------------------------------------------
# Opening a return
# ---------------------------------------------------------------------------


def test_a_return_still_validating_shows_which_step_is_under_way(
    eager: TestClient, pause: _Pause, broken_csv: Path
) -> None:
    # Act
    response = eager.post(
        "/open", data={"path": str(broken_csv), **HEADER_FORM}, follow_redirects=False
    )
    page = _held_page(eager, response, pause)
    pause.released.set()

    # Assert
    assert "Validating broken.csv" in page
    assert _state(page, PHASE_READING) == "done"
    assert _state(page, PHASE_STRUCTURE) == "done"
    assert _state(page, PHASE_RULES) == "current"
    assert f"{HELD_AT} of {pause.total:,} rules evaluated" in _text(page)
    assert f'<progress id="task-progress" max="{pause.total}" value="{HELD_AT}">' in page
    assert '<meta http-equiv="refresh" content="1">' in page


def test_the_progress_page_moves_on_to_the_overview_when_the_work_is_done(
    eager: TestClient, pause: _Pause, broken_csv: Path
) -> None:
    # Arrange
    response = eager.post(
        "/open", data={"path": str(broken_csv), **HEADER_FORM}, follow_redirects=False
    )
    _held_page(eager, response, pause)

    # Act
    pause.released.set()
    ended = _settle(eager, response)

    # Assert
    assert ended.status_code == 303
    assert ended.headers["location"].startswith("/returns/")
    overview = eager.get(ended.headers["location"]).text
    assert 'data-verdict="blocked"' in overview


def test_work_under_way_is_listed_on_every_page_until_it_ends(
    eager: TestClient, pause: _Pause, broken_csv: Path
) -> None:
    # Arrange
    response = eager.post(
        "/open", data={"path": str(broken_csv), **HEADER_FORM}, follow_redirects=False
    )
    _held_page(eager, response, pause)
    task_id = response.headers["location"].rsplit("/", 1)[1]

    # Act
    while_held = eager.get("/").text
    pause.released.set()
    _settle(eager, response)
    afterwards = eager.get("/").text

    # Assert
    assert f'id="task-link-{task_id}"' in while_held
    assert "Validating broken.csv" in while_held
    assert f'id="task-link-{task_id}"' not in afterwards


def test_a_file_that_cannot_be_read_is_refused_on_the_open_page_with_the_form_kept(
    eager: TestClient, tmp_path: Path
) -> None:
    # Arrange
    absent = tmp_path / "absent.xbrl"

    # Act
    response = eager.post(
        "/open", data={"path": str(absent), "entity": "X1"}, follow_redirects=False
    )
    ended = _settle(eager, response)

    # Assert
    assert ended.status_code == 400
    assert "file not found" in ended.text
    assert f'value="{absent}"' in ended.text, "the path typed is offered again"


def test_a_form_the_dashboard_can_refuse_itself_is_refused_without_starting_work(
    eager: TestClient, broken_csv: Path
) -> None:
    # Act — a fact table with no header: nothing needs reading to refuse it.
    response = eager.post("/open", data={"path": str(broken_csv)}, follow_redirects=False)

    # Assert
    assert response.status_code == 400
    assert "carries no header" in response.text
    assert "Under way" not in response.text


def test_an_unexpected_failure_is_reported_not_lost(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, broken_csv: Path
) -> None:
    # Arrange
    def broken_open(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("the disk caught fire")

    monkeypatch.setattr(workspace, "open", broken_open)
    client = TestClient(create_app(workspace, progress_after=PATIENCE), base_url=BASE_URL)

    # Act
    response = client.post("/open", data={"path": str(broken_csv), **HEADER_FORM})

    # Assert
    assert response.status_code == 500
    assert "stopped unexpectedly: the disk caught fire" in response.text


def test_an_address_no_work_has_is_not_found(eager: TestClient) -> None:
    # Act
    response = eager.get("/tasks/00000000")

    # Assert
    assert response.status_code == 404
    assert "No work is under way at that address" in response.text


def test_opening_another_version_to_compare_shows_its_progress_too(
    eager: TestClient, broken: OpenedReturn, pause: _Pause, clean_csv: Path
) -> None:
    # Act
    response = eager.post(
        f"/returns/{broken.return_id}/compare",
        data={"path": str(clean_csv), **HEADER_FORM},
        follow_redirects=False,
    )
    page = _held_page(eager, response, pause)
    pause.released.set()
    ended = _settle(eager, response)

    # Assert
    assert "Validating clean.csv to compare" in page
    assert ended.headers["location"].startswith(f"/returns/{broken.return_id}/compare?against=")


# ---------------------------------------------------------------------------
# Re-validating with an override, and building
# ---------------------------------------------------------------------------


def test_drafting_an_override_shows_the_revalidation_then_returns_to_the_grid(
    eager: TestClient, workspace: Workspace, broken: OpenedReturn, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — hold the re-validation the draft calls for; a page drawn meanwhile is not held.
    held, real_working = _Pause(), workspace.working

    def working_held(opened: OpenedReturn, *, progress: ProgressCallback | None = None) -> Any:
        return real_working(opened, progress=held.watching(progress) if progress else None)

    monkeypatch.setattr(workspace, "working", working_held)
    base = f"/returns/{broken.return_id}"
    back = base + GRID

    # Act
    response = eager.post(
        f"{base}/adjustments",
        data={
            **CELL,
            "col": "0010",
            "data_type": "monetary",
            "value": "0",
            "reason": "R",
            "next": back,
        },
        follow_redirects=False,
    )
    page = _held_page(eager, response, held)
    held.released.set()
    ended = _settle(eager, response)

    # Assert
    assert "with its drafted overrides" in page
    assert 'data-phase="reading"' not in page, "an opened return is not read again"
    assert _state(page, PHASE_RULES) == "current"
    assert ended.headers["location"] == back
    assert "1 drafted override applied" in eager.get(back).text


def test_a_build_shows_writing_as_its_last_step(
    eager: TestClient,
    broken: OpenedReturn,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — hold the build's own validation partway through its rules.
    held, real_build = _Pause(), filing_pages.build_package

    def build_held(*args: Any, progress: ProgressCallback | None = None, **kwargs: Any) -> int:
        return real_build(*args, progress=held.watching(progress), **kwargs)

    monkeypatch.setattr(filing_pages, "build_package", build_held)
    base = f"/returns/{broken.return_id}"

    # Act
    response = eager.post(
        f"{base}/build",
        data={"directory": str(tmp_path / "out"), "force": "yes"},
        follow_redirects=False,
    )
    page = _held_page(eager, response, held)
    held.released.set()
    ended = _settle(eager, response)

    # Assert
    assert f"Building the filing package for {broken.name}" in page
    assert _state(page, PHASE_WRITING) == "pending"
    assert ended.headers["location"] == f"{base}/filing#build"
    assert [event.phase for event in held.heard][-1] == PHASE_WRITING


# ---------------------------------------------------------------------------
# The workspace reports what the pages show
# ---------------------------------------------------------------------------


def test_opening_in_the_workspace_reports_reading_then_validating(
    workspace: Workspace, broken_csv: Path
) -> None:
    # Arrange
    heard: list[Progress] = []

    # Act
    opened = workspace.open(broken_csv, HEADER, progress=heard.append)

    # Assert
    phases = [event.phase for event in heard]
    assert phases[:2] == [PHASE_READING, PHASE_STRUCTURE]
    assert set(phases[2:]) == {PHASE_RULES}
    assert opened.validation.report is not None
    assert heard[-1].done == heard[-1].total == opened.validation.report.rules_enforced
