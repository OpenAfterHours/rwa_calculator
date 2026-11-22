"""
Work the dashboard does once, however many requests ask for it at the same moment.

Validating a return with its drafted overrides, comparing two returns and
collecting the evidence behind a verdict each take seconds on a large return. A
request that asks for one while another is already working it out now waits for
that one and takes its result: a page drawn while an override is validated, a
second browser tab, a second click on Download evidence. Before, each did the
same work again beside the first — and two evidence downloads at once wrote one
file while it was being sent, which could hand back a damaged file with HTTP 200.

The evidence is also written once per validation and handed out from then on: a
second download, or the as-opened return's after every override is withdrawn,
collects nothing again.

How the tests line requests up without racing them: the work is held on a gate
the test opens (``_Gate``), the requests are started, and the test waits until
each is parked — on the gate, or waiting for another — by looking at where its
thread is (``dash_builders.parked_inside``). What it then counts is fixed: how
many times the work was started.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import pytest

import rwa_filer.evidence as evidence_module
from dash_builders import CELL, HEADER, PATIENCE, draft, make_fileable, parked_inside, wait_until
from rwa_filer.dash import Workspace
from rwa_filer.dash import workspace as workspace_module
from rwa_filer.dash.pages import ReturnPages
from rwa_filer.evidence import read_evidence
from rwa_filer.workflow.adjustments import Adjustment

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from starlette.testclient import TestClient

    from rwa_filer.dash import OpenedReturn

#: Two overrides of BROKEN's one row: the second drafted after the first.
FIRST = Adjustment(
    table="OF07.00.01.01", sheet="0008", row="0010", column="0010", value=0.0, reason="Zero"
)
SECOND = Adjustment(
    table="OF07.00.01.01", sheet="0008", row="0010", column="0030", remove=True, reason="Out"
)
#: How many requests ask for the same evidence at once.
DOWNLOADS = 3


class _Gate:
    """Stands in for one piece of work: records each start, and holds it until opened."""

    def __init__(self, real: Callable[..., Any], *, failing_first: bool = False) -> None:
        self.real = real
        self.failing_first = failing_first
        self.starts: list[str] = []
        self.opened = threading.Event()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.starts.append(threading.current_thread().name)
        first = len(self.starts) == 1
        assert self.opened.wait(PATIENCE), "the test never opened the gate"
        if first and self.failing_first:
            raise RuntimeError("the first attempt broke")
        return self.real(*args, **kwargs)


class _Call:
    """``work()`` run in a thread of its own; what it returned, or what it raised."""

    def __init__(self, work: Callable[[], Any]) -> None:
        self.done = threading.Event()
        self._result: Any = None
        self._error: BaseException | None = None
        threading.Thread(target=self._run, args=(work,), daemon=True).start()

    def _run(self, work: Callable[[], Any]) -> None:
        try:
            self._result = work()
        except BaseException as exc:  # noqa: BLE001 - handed to the test by value()
            self._error = exc
        finally:
            self.done.set()

    def value(self) -> Any:
        """What the call returned; re-raises what it raised."""
        assert self.done.wait(PATIENCE), "the call never returned"
        if self._error is not None:
            raise self._error
        return self._result


@pytest.fixture
def validations(monkeypatch: pytest.MonkeyPatch) -> _Gate:
    """Every validation of a return with its drafts, held until the test opens the gate."""
    gate = _Gate(workspace_module.validate_return)
    monkeypatch.setattr(workspace_module, "validate_return", gate)
    return gate


@pytest.fixture
def collections(monkeypatch: pytest.MonkeyPatch) -> _Gate:
    """Every collection of evidence (its trace of the return), held until the gate opens."""
    gate = _Gate(evidence_module.trace_return)
    monkeypatch.setattr(evidence_module, "trace_return", gate)
    return gate


def _evidence_link(opened: OpenedReturn) -> str:
    return f"/returns/{opened.return_id}/evidence.jsonl"


# ---------------------------------------------------------------------------
# A return's validation with its drafted overrides
# ---------------------------------------------------------------------------


def test_a_page_asked_for_while_the_drafts_are_validated_waits_for_that_validation(
    workspace: Workspace, broken: OpenedReturn, validations: _Gate
) -> None:
    # Arrange — the re-validation a draft calls for is under way, held.
    workspace.set_adjustment(broken.return_id, FIRST)
    revalidation = _Call(lambda: workspace.working(broken))
    wait_until(lambda: len(validations.starts) == 1)

    # Act — a page of the same return asks for it meanwhile.
    page = _Call(lambda: workspace.working(broken))
    wait_until(lambda: parked_inside(Workspace.working) == 2 or page.done.is_set())
    started_while_held = len(validations.starts)
    validations.opened.set()

    # Assert — one validation for the one change, and both have its result.
    assert started_while_held == 1, "the page validated the same drafts again"
    assert page.value() is revalidation.value()


def test_a_validation_that_fails_leaves_no_page_waiting_for_it(
    workspace: Workspace, broken: OpenedReturn, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — the first validation breaks once the test lets it go on.
    gate = _Gate(workspace_module.validate_return, failing_first=True)
    monkeypatch.setattr(workspace_module, "validate_return", gate)
    workspace.set_adjustment(broken.return_id, FIRST)
    first = _Call(lambda: workspace.working(broken))
    wait_until(lambda: len(gate.starts) == 1)
    waiting = _Call(lambda: workspace.working(broken))
    wait_until(lambda: parked_inside(Workspace.working) == 2)

    # Act
    gate.opened.set()

    # Assert — the failure is the first caller's; the one waiting validated for itself.
    with pytest.raises(RuntimeError, match="the first attempt broke"):
        first.value()
    assert [item.adjustment for item in waiting.value().applied] == [FIRST]
    assert len(gate.starts) == 2


def test_a_validation_of_superseded_drafts_is_never_handed_to_a_page_of_newer_ones(
    workspace: Workspace, broken: OpenedReturn, validations: _Gate
) -> None:
    # Arrange — the first draft's validation is held; a second draft follows it.
    workspace.set_adjustment(broken.return_id, FIRST)
    superseded = _Call(lambda: workspace.working(broken))
    wait_until(lambda: len(validations.starts) == 1)
    workspace.set_adjustment(broken.return_id, SECOND)

    # Act — a page asks for the return as it now stands.
    newer = _Call(lambda: workspace.working(broken))
    wait_until(
        lambda: (
            len(validations.starts) == 2
            or parked_inside(Workspace.working) == 2
            or newer.done.is_set()
        )
    )
    started_while_held = len(validations.starts)
    validations.opened.set()

    # Assert — the newer drafts were validated for themselves, and are what is kept.
    assert started_while_held == 2, "the page waited for a validation of older drafts"
    assert [item.adjustment for item in newer.value().applied] == [FIRST, SECOND]
    assert [item.adjustment for item in superseded.value().applied] == [FIRST]
    assert workspace.working(broken) is newer.value()


# ---------------------------------------------------------------------------
# A comparison of two returns
# ---------------------------------------------------------------------------


def test_two_requests_for_one_pair_compare_it_once(
    workspace: Workspace,
    broken: OpenedReturn,
    clean_csv: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    clean = workspace.open(clean_csv, HEADER)
    gate = _Gate(workspace_module.compare_returns)
    monkeypatch.setattr(workspace_module, "compare_returns", gate)

    # Act — two tabs ask for the same pair at once.
    tabs = [_Call(lambda: workspace.comparison(clean, broken)) for _ in range(2)]
    wait_until(lambda: parked_inside(Workspace.comparison) == 2)
    started_while_held = len(gate.starts)
    gate.opened.set()

    # Assert
    assert started_while_held == 1, "each tab compared the pair for itself"
    assert tabs[0].value() is tabs[1].value()
    assert workspace.kept_comparison(clean, broken) is tabs[0].value()


# ---------------------------------------------------------------------------
# The evidence download
# ---------------------------------------------------------------------------


def test_downloads_asked_for_at_once_are_one_collection_and_the_same_whole_file(
    client: TestClient, broken: OpenedReturn, collections: _Gate, tmp_path: Path
) -> None:
    """Two clicks at once used to write one file while it was sent: a damaged download, HTTP 200."""
    # Act — the downloads arrive while the first collection is under way.
    link = _evidence_link(broken)
    downloads = [_Call(lambda: client.get(link)) for _ in range(DOWNLOADS)]
    wait_until(lambda: parked_inside(ReturnPages.evidence) == DOWNLOADS)
    collected_while_held = len(collections.starts)
    collections.opened.set()

    # Assert — one collection, and every download is that one complete file.
    assert collected_while_held == 1, "each download collected and wrote the evidence itself"
    answers = [download.value() for download in downloads]
    assert [answer.status_code for answer in answers] == [200] * DOWNLOADS
    assert len({answer.content for answer in answers}) == 1
    copy = tmp_path / "downloaded.evidence.jsonl"
    copy.write_bytes(answers[0].content)
    assert read_evidence(copy).header["status"] == "BLOCKED"


def test_a_second_download_is_handed_the_file_the_first_wrote(
    client: TestClient, broken: OpenedReturn, collections: _Gate
) -> None:
    # Arrange
    collections.opened.set()
    link = _evidence_link(broken)

    # Act
    first = client.get(link)
    second = client.get(link)

    # Assert
    assert len(collections.starts) == 1, "the second download collected the evidence again"
    assert second.content == first.content


def test_withdrawing_every_override_is_handed_the_as_opened_file_again(
    client: TestClient, broken: OpenedReturn, collections: _Gate
) -> None:
    """Kept per validation, not per return: the as-opened one comes back with its file."""
    # Arrange
    collections.opened.set()
    link = _evidence_link(broken)
    as_opened = client.get(link).content
    make_fileable(client, broken)
    with_drafts = client.get(link).content

    # Act
    for column in ("0010", "0030"):
        client.post(f"/returns/{broken.return_id}/adjustments/drop", data={**CELL, "col": column})
    withdrawn = client.get(link).content

    # Assert — the as-opened bytes, and no third collection.
    assert withdrawn == as_opened != with_drafts
    assert len(collections.starts) == 2


def test_of_a_returns_evidence_files_the_as_opened_and_the_latest_are_kept(
    client: TestClient, workspace: Workspace, broken: OpenedReturn
) -> None:
    # Arrange
    link = _evidence_link(broken)
    folder = workspace.directory / "evidence"
    client.get(link)
    as_opened = set(folder.iterdir())
    draft(client, broken, "0010", value="0", reason="Zero")
    client.get(link)
    superseded = set(folder.iterdir()) - as_opened

    # Act — a newer draft's evidence is written.
    draft(client, broken, "0030", remove="yes", reason="Out")
    client.get(link)

    # Assert
    kept = set(folder.iterdir())
    assert len(as_opened) == len(superseded) == 1
    assert as_opened <= kept, "the as-opened file was removed"
    assert not superseded & kept, "the superseded file is still there"
    assert len(kept) == 2
