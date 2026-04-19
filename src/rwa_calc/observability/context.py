"""
Correlation-ID and stage-timing primitives for the observability layer.

Pipeline position:
    Cross-cutting — called by api entry points (to open a run), the pipeline
    orchestrator (to wrap each stage), and by the logging filter that injects
    the active run_id onto every LogRecord.

Key responsibilities:
- Store the active run_id in a `contextvars.ContextVar` so it is isolated
  across asyncio tasks and threads (critical under the FastAPI/marimo server)
- Provide `new_run_id` / `bind_run_id` / `clear_run_id` for explicit lifecycle
- Provide `stage_timer` for uniform stage entry/exit instrumentation
- Provide `RunIdFilter` so formatters can unconditionally reference `%(run_id)s`

References:
- docs/specifications/observability.md
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

_run_id_var: ContextVar[str | None] = ContextVar("rwa_run_id", default=None)


def new_run_id() -> tuple[str, Token[str | None]]:
    """Generate a fresh 12-hex-char run_id and bind it to the current context.

    Returns the id and the reset token; pass the token to `clear_run_id`.
    """
    run_id = uuid.uuid4().hex[:12]
    token = _run_id_var.set(run_id)
    return run_id, token


def bind_run_id(run_id: str) -> Token[str | None]:
    """Bind an existing run_id to the current context. Returns a reset token."""
    return _run_id_var.set(run_id)


def clear_run_id(token: Token[str | None]) -> None:
    """Reset the run_id context to its prior value using the token from `new_run_id` / `bind_run_id`."""
    _run_id_var.reset(token)


def current_run_id() -> str | None:
    """Return the active run_id, or None if no run is in progress."""
    return _run_id_var.get()


class RunIdFilter(logging.Filter):
    """Inject the active run_id (or '-' when unset) onto every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = current_run_id() or "-"
        return True


@contextmanager
def stage_timer(
    logger: logging.Logger,
    stage: str,
    **extra: Any,
) -> Iterator[None]:
    """Emit INFO entry/exit records bracketing a pipeline stage.

    Entry record: "stage entered" with `extra={"stage": stage, **extra}`.
    Exit record:  "stage completed" with `extra={..., "elapsed_ms": <float>}`.

    Exceptions propagate unchanged; the exit record is still emitted so
    timing is visible even for failed stages, at WARNING level.
    """
    base_extra = {"stage": stage, **extra}
    logger.info("stage entered", extra=base_extra)
    start = time.perf_counter()
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        exit_extra = {**base_extra, "elapsed_ms": elapsed_ms}
        if failed:
            logger.warning("stage failed", extra=exit_extra)
        else:
            logger.info("stage completed", extra=exit_extra)
