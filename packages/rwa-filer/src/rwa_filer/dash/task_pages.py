"""
The progress page — how far a validation or a build has got, while it runs.

Pipeline position:
    form handler  ->  TaskBoard.start  ->  follow(task)
        ->  the result at once (quick work)  |  303 to /tasks/{id}
    browser  ->  /tasks/{id}  ->  task.html (asks again at once)
        ->  /tasks/{id}?wait=1, held until the work ends or a second passes
        ->  task.html again  |  303 to the result

Key responsibilities:
- Answer a form that started long work as it was answered before the work
  moved off the request thread, whenever the work is quick: wait a moment, and
  if it has ended, go straight to the page it leads to or draw the refusal.
  Only work still going after that moment gets a progress page.
- Draw the progress page: each step of the work, which are done and which is
  under way, how many rules are evaluated out of how many, and how long it has
  been going — asking again until the work ends, then moving on.
- Move on the moment the work ends. The page cannot ask sooner than a whole
  second later by itself (it carries no script), so it asks again at once and
  the wait is held here instead: a request that says it is waiting is answered
  when the work ends, or after ``REFRESH_SECONDS`` with the progress so far.
- Show nothing that was not measured: the rules are counted as the engine
  evaluates them, and the other steps are shown only as started or done.

References:
- rwa_filer.progress — the steps and the count
- dash.tasks — the work itself
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import RedirectResponse
from starlette.routing import Route

from rwa_filer.dash.context import link
from rwa_filer.dash.tasks import STATUS_DONE, STATUS_FAILED
from rwa_filer.progress import PHASE_LABELS, elapsed

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from rwa_filer.dash.context import DashContext
    from rwa_filer.dash.tasks import Task

#: Seconds between two drawings of the progress page while the work goes on:
#: the longest a waiting request is held before it is answered with the progress so far.
REFRESH_SECONDS: Final = 1
#: The query parameter, and its value, by which the progress page says its
#: request may be held until the work ends.
WAIT_PARAMETER: Final = "wait"
WAITING: Final = "1"

#: A step that has finished, the one under way, and one not reached yet.
STEP_DONE: Final = "done"
STEP_CURRENT: Final = "current"
STEP_PENDING: Final = "pending"


# =============================================================================
# Public entry point
# =============================================================================


def routes(context: DashContext) -> list[Route]:
    """The progress page, bound to ``context``."""
    pages = TaskPages(context)
    return [Route("/tasks/{task_id}", pages.task, name="task")]


async def follow(context: DashContext, request: Request, task: Task) -> Response:
    """Answer the form that started ``task``.

    Waits up to ``context.progress_after`` seconds for the work: work that ends
    within it is answered as the form always was — the page it leads to, or
    the refusal — and only work still going is sent to its progress page.
    """
    await run_in_threadpool(task.wait, context.progress_after)
    return outcome(request, task) or RedirectResponse(f"/tasks/{task.task_id}", status_code=303)


def outcome(request: Request, task: Task) -> Response | None:
    """Where ended work leads: its result, or its refusal; ``None`` while it runs."""
    if task.status == STATUS_DONE and task.destination is not None:
        return RedirectResponse(task.destination, status_code=303)
    if task.status == STATUS_FAILED:
        return task.refused(request, task.error or "", task.error_status)
    return None


@dataclass(frozen=True)
class StepView:
    """One step of the work as the progress page lists it."""

    phase: str
    label: str
    state: str
    detail: str = ""


@dataclass(frozen=True)
class TaskView:
    """What the progress page draws for a running task."""

    steps: tuple[StepView, ...]
    done: int
    total: int
    percent: int | None
    elapsed: str

    @property
    def counted(self) -> bool:
        """Whether the step under way is counted, so the bar has something to show."""
        return self.total > 0


class TaskPages:
    """The handler of the progress page."""

    def __init__(self, context: DashContext) -> None:
        self.context = context

    def task(self, request: Request) -> Response:
        """The work's progress while it runs; its result, or its refusal, once it has ended.

        A request that says it is waiting is held until the work ends, for at
        most ``REFRESH_SECONDS``. This handler is a plain function on purpose:
        the server runs it in a worker thread, so the wait holds up no other
        page. Made a coroutine, it would stop the whole server for the wait.
        """
        task = self.context.tasks.get(str(request.path_params["task_id"]))
        if task is None:
            raise HTTPException(status_code=404, detail="No work is under way at that address.")
        if task.running and request.query_params.get(WAIT_PARAMETER) == WAITING:
            task.wait(REFRESH_SECONDS)
        ended = outcome(request, task)
        if ended is not None:
            return ended
        return self.context.render(
            request,
            "task.html",
            section="task",
            task=task,
            view=task_view(task, now=datetime.now(UTC)),
            refresh=REFRESH_SECONDS,
            ask_again=link(f"/tasks/{task.task_id}", **{WAIT_PARAMETER: WAITING}),
        )


def task_view(task: Task, *, now: datetime) -> TaskView:
    """``task`` as the progress page draws it, at ``now``."""
    progress = task.progress
    current = task.phases.index(progress.phase) if progress and progress.phase in task.phases else 0
    steps = tuple(
        StepView(
            phase=phase,
            label=PHASE_LABELS.get(phase, phase),
            state=STEP_DONE
            if index < current
            else STEP_CURRENT
            if index == current
            else STEP_PENDING,
            detail=progress.subject if progress and index == current else "",
        )
        for index, phase in enumerate(task.phases)
    )
    counted = progress is not None and progress.counted
    return TaskView(
        steps=steps,
        done=progress.done if progress and counted else 0,
        total=progress.total if progress and counted else 0,
        percent=progress.percent if progress and counted else None,
        elapsed=elapsed((now - task.started_at).total_seconds()),
    )
