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
collects nothing again. And no file a download was handed is removed under it:
a download of an older validation that ends last, or a newer one written while
an older download has not opened its file yet, used to delete the other's file —
an HTTP 500, and the current validation's evidence collected a third time.

How the tests line requests up without racing them: the work is held on a gate
the test opens (``_Gate``), the requests are started, and the test waits until
each is parked — on the gate, or waiting for another — by looking at where its
thread is (``dash_builders.parked_inside``). What it then counts is fixed: how
many times the work was started.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from starlette.responses import FileResponse
from starlette.testclient import TestClient

import rwa_filer.dash.pages as pages_module
import rwa_filer.evidence as evidence_module
from dash_builders import (
    BASE_URL,
    CELL,
    HEADER,
    PATIENCE,
    draft,
    make_fileable,
    parked_inside,
    wait_until,
)
from rwa_filer.dash import Workspace
from rwa_filer.dash import workspace as workspace_module
from rwa_filer.dash.pages import ReturnPages
from rwa_filer.evidence import read_evidence
from rwa_filer.workflow.adjustments import Adjustment

if TYPE_CHECKING:
    from collections.abc import Callable

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
    """Stands in for one piece of work: records each start, and holds it until opened.

    ``only_first`` holds the first start alone; every later one goes straight on.
    """

    def __init__(
        self, real: Callable[..., Any], *, failing_first: bool = False, only_first: bool = False
    ) -> None:
        self.real = real
        self.failing_first = failing_first
        self.only_first = only_first
        self.starts: list[str] = []
        self.opened = threading.Event()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.starts.append(threading.current_thread().name)
        first = len(self.starts) == 1
        if first or not self.only_first:
            assert self.opened.wait(PATIENCE), "the test never opened the gate"
        if first and self.failing_first:
            raise RuntimeError("the first attempt broke")
        return self.real(*args, **kwargs)


class _HandOut:
    """Stands in for the evidence page's file response: holds the first before it opens its file.

    Between ``Workspace.evidence`` handing a download its file and the response
    opening it there is a window; this holds the first download in it until
    the test lets it go, and records each file handed out with its bytes then.
    """

    def __init__(self) -> None:
        self.handed: list[tuple[Path, bytes]] = []
        self.released = threading.Event()

    def __call__(self, path: Path, *args: Any, **kwargs: Any) -> FileResponse:
        self.handed.append((Path(path), Path(path).read_bytes()))
        if len(self.handed) == 1:
            assert self.released.wait(PATIENCE), "the test never let the response go"
        return FileResponse(path, *args, **kwargs)


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


def test_an_older_validations_collection_ending_last_leaves_the_current_file_kept(
    client: TestClient, workspace: Workspace, broken: OpenedReturn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What is kept follows the drafts as they stand, not which collection ended last.

    The older download's collection used to remove the current validation's file
    (perhaps already handed to its download) and forget it, so the next
    download of the current validation collected a third time.
    """
    # Arrange — a download of the first draft's validation is collecting, held.
    collections = _Gate(evidence_module.trace_return, only_first=True)
    monkeypatch.setattr(evidence_module, "trace_return", collections)
    link = _evidence_link(broken)
    folder = workspace.directory / "evidence"
    draft(client, broken, "0010", value="0", reason="Zero")
    older = _Call(lambda: client.get(link))
    wait_until(lambda: len(collections.starts) == 1)
    # A second draft follows it, and the current validation's download completes.
    draft(client, broken, "0030", remove="yes", reason="Out")
    current = client.get(link)
    (current_file,) = folder.iterdir()
    assert current.status_code == 200
    assert not older.done.is_set(), "the older collection ended first: nothing to test"

    # Act — the older collection ends last; then the current validation is downloaded again.
    collections.opened.set()
    older_answer = older.value()
    again = client.get(link)

    # Assert
    assert older_answer.status_code == 200
    assert older_answer.content != current.content, "both downloads were of one validation"
    assert current_file.exists(), "the older collection removed the current validation's file"
    assert len(collections.starts) == 2, "the current validation's evidence was collected again"
    assert again.content == current.content


def test_a_superseded_file_handed_out_and_not_yet_sent_is_still_sent_whole(
    client: TestClient, broken: OpenedReturn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A newer validation's evidence used to remove the file an older download had just been
    handed: the response then found no file to send, an HTTP 500."""
    # Arrange — a download is handed the first draft's file and held before it opens it.
    hand_out = _HandOut()
    monkeypatch.setattr(pages_module, "FileResponse", hand_out)
    lenient = TestClient(client.app, base_url=BASE_URL, raise_server_exceptions=False)
    link = _evidence_link(broken)
    draft(client, broken, "0010", value="0", reason="Zero")
    older = _Call(lambda: lenient.get(link))
    wait_until(lambda: len(hand_out.handed) == 1)
    draft(client, broken, "0030", remove="yes", reason="Out")

    # Act — the newer validation's evidence is written and sent; then the held download goes on.
    newer = client.get(link)
    assert not older.done.is_set(), "the held download was sent first: nothing to test"
    hand_out.released.set()
    answer = older.value()

    # Assert — a newer file was written meanwhile, and the held one was sent, every byte.
    (handed_file, handed_bytes), (newer_file, _) = hand_out.handed
    assert newer.status_code == 200
    assert newer_file != handed_file, "the newer download was handed the same file"
    assert handed_bytes, "the handed file was empty"
    assert answer.status_code == 200, "the handed-out file was removed before it was sent"
    assert answer.content == handed_bytes
