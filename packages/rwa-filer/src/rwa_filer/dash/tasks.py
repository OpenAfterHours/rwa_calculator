"""
Long work off the request thread — opening, re-validating and building a return.

Pipeline position:
    a page's form  ->  TaskBoard.start(work)  ->  thread: work(progress)
        ->  Task (how far it has got, then where to go or why it failed)
        ->  dash.task_pages (the progress page, and the answer to the form)

Key responsibilities:
- Run the work a form asked for in a thread of its own, so the request can be
  answered while it runs: a full PRA001 return takes tens of seconds to
  validate, and a page that does not answer for that long looks frozen.
- Keep the latest ``rwa_filer.progress.Progress`` the work reported, for the
  progress page to draw — which step it is on, and how many rules are done.
- Keep, when the work is done, the address to go to; when it failed, why, in
  the words the page that asked for it would have used — the work's own
  refusal for a condition in the data, and a plain "stopped unexpectedly" for
  anything else, which is also logged with its traceback.
- Be safe to read from the server's worker threads while the work runs.

References:
- rwa_filer.progress — the steps a validation reports
- dash.referee_jobs — the referee's own runs, which take minutes and report
  progress from Arelle's workers instead
"""

from __future__ import annotations

import logging
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from rwa_filer.extras import MissingExtraError
from rwa_filer.release import ReleaseNotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request
    from starlette.responses import Response

    from rwa_filer.progress import Progress, ProgressCallback

logger = logging.getLogger(__name__)

STATUS_RUNNING: Final = "running"
STATUS_DONE: Final = "done"
STATUS_FAILED: Final = "failed"

#: What a task does: given where to report progress, do the work and return the
#: dashboard address to go to when it is done.
type Work = Callable[[ProgressCallback], str]
#: How the page that asked for the work answers when it is refused: the request,
#: why, and the status code to answer with.
type Refusal = Callable[[Request, str, int], Response]

#: The conditions in the data, the file or the release that refuse the work —
#: the ones the pages answered with 400 when they did the work themselves.
REFUSALS: Final = (ValueError, ReleaseNotFoundError, MissingExtraError, OSError)
#: The status code a refusal is answered with, and one for anything else.
REFUSED_STATUS: Final = 400
UNEXPECTED_STATUS: Final = 500


# =============================================================================
# Public entry point
# =============================================================================


@dataclass
class Task:
    """One piece of long work: what it is, how far it has got, how it ended.

    Mutable on purpose: the worker thread fills it in while pages read it.
    Each field is replaced whole, never changed in place, so a page reads
    either the old value or the new one.

    Attributes:
        task_id: The session's id for it, used in the progress page's address.
        title: What is being done, as the progress page's heading says it.
        phases: The ``rwa_filer.progress`` steps the work goes through, in order.
        refused: How the page the work was asked from says why it failed.
        started_at: When it was started.
        status: ``running``, ``done`` or ``failed``.
        progress: The last progress the work reported, or ``None`` before any.
        destination: Where to go now it is done.
        error: Why it failed.
        error_status: The status code to answer the failure with.
        finished_at: When it ended.
    """

    task_id: str
    title: str
    phases: tuple[str, ...]
    refused: Refusal
    started_at: datetime
    status: str = STATUS_RUNNING
    progress: Progress | None = None
    destination: str | None = None
    error: str | None = None
    error_status: int = REFUSED_STATUS
    finished_at: datetime | None = None
    _finished: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def running(self) -> bool:
        """Whether the work is still going."""
        return self.status == STATUS_RUNNING

    def wait(self, timeout: float | None) -> bool:
        """Wait up to ``timeout`` seconds for the work to end; whether it has."""
        return self._finished.wait(timeout)

    def report(self, progress: Progress) -> None:
        """Keep the latest progress the work reported (the work's ``ProgressCallback``)."""
        self.progress = progress

    def finish(
        self,
        *,
        destination: str | None = None,
        error: str | None = None,
        error_status: int = REFUSED_STATUS,
    ) -> None:
        """Record how the work ended, and wake whoever is waiting for it."""
        self.destination = destination
        self.error = error
        self.error_status = error_status
        self.finished_at = datetime.now(UTC)
        self.status = STATUS_FAILED if error is not None else STATUS_DONE
        self._finished.set()
        logger.info("dashboard task %s %s: %s", self.task_id, self.status, self.title)


class TaskBoard:
    """The long work of one dashboard session, running and finished."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def start(
        self,
        title: str,
        work: Work,
        *,
        phases: tuple[str, ...],
        refused: Refusal,
    ) -> Task:
        """Start ``work`` in a thread of its own and return its task at once."""
        task = Task(
            task_id=secrets.token_hex(4),
            title=title,
            phases=phases,
            refused=refused,
            started_at=datetime.now(UTC),
        )
        with self._lock:
            self._tasks[task.task_id] = task
        thread = threading.Thread(
            target=_run, args=(task, work), name=f"dash-task-{task.task_id}", daemon=True
        )
        thread.start()
        return task

    def get(self, task_id: str) -> Task | None:
        """The task with this id, if there is one."""
        with self._lock:
            return self._tasks.get(task_id)

    def running(self) -> list[Task]:
        """The tasks still going, the earliest first."""
        with self._lock:
            tasks = [task for task in self._tasks.values() if task.running]
        return sorted(tasks, key=lambda task: task.started_at)


# =============================================================================
# Private helpers
# =============================================================================


def _run(task: Task, work: Work) -> None:
    """Do ``task``'s work, and record how it ended — whatever happens."""
    try:
        destination = work(task.report)
    except REFUSALS as exc:
        task.finish(error=str(exc), error_status=REFUSED_STATUS)
    except Exception as exc:  # noqa: BLE001 - a background task must report, not vanish
        logger.exception("dashboard task %s (%s) failed", task.task_id, task.title)
        task.finish(error=f"The work stopped unexpectedly: {exc}", error_status=UNEXPECTED_STATUS)
    else:
        task.finish(destination=destination)
