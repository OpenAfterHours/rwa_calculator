"""
Progress of a long check — which step it is on, and how far through that step it is.

Pipeline position:
    validate.returns / boe.engine / filing.build_filing (and whoever reads the file)
        ->  ProgressCallback(Progress)
        ->  StreamProgress (a command's stderr)  |  a dashboard task (its progress page)

Key responsibilities:
- Name the steps a validation goes through, in the order it takes them, so the
  command line and the dashboard describe the same run in the same words.
- Count only what can honestly be counted. The published rules are evaluated
  one by one and are where nearly all the time of a full return goes, so they
  are counted rule by rule; reading the file and checking its structure are
  single steps, reported as they start. No figure is ever invented to make a
  bar move.
- Write progress to a terminal as one line rewritten in place, and to anything
  else (a log, a pipe) as one line per step and per tenth of the rules — never
  to stdout, which carries the command's result.

References:
- rwa_filer.validate.returns.validate_return — the steps a validation reports
- rwa_filer.cli — ``--progress`` / ``--no-progress``
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Self, TextIO

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

#: Reading the return's file into canonical form.
PHASE_READING: Final = "reading"
#: Checking the return's structure against the taxonomy.
PHASE_STRUCTURE: Final = "structure"
#: Evaluating the published rules, counted rule by rule.
PHASE_RULES: Final = "rules"
#: Writing the filing package: the instance, the zip and the manifest. The
#: steps come in the order of these constants; a run may skip one (a return
#: already in memory is not read; a validation writes nothing), never reorder.
PHASE_WRITING: Final = "writing"

#: Each step as a person reads it.
PHASE_LABELS: Final = {
    PHASE_READING: "Reading the file",
    PHASE_STRUCTURE: "Checking the structure against the taxonomy",
    PHASE_RULES: "Evaluating the published rules",
    PHASE_WRITING: "Writing the filing package",
}

#: Seconds between two redraws of a live line: often enough to look alive, not
#: so often that drawing costs anything beside the rules.
_REDRAW_SECONDS: Final = 0.1
#: A log line is written each time a counted step passes another tenth.
_LOG_STEPS: Final = 10


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class Progress:
    """Where a check has got to: the step it is on, and how much of it is done.

    Attributes:
        phase: One of the ``PHASE_*`` constants.
        done: How many of the step's items are finished; 0 for a step that is
            not counted.
        total: How many items the step has; 0 when it is not counted.
        subject: What the step is about, where that helps: the file being read,
            the taxonomy release the structure is checked against.
    """

    phase: str
    done: int = 0
    total: int = 0
    subject: str = ""

    @property
    def label(self) -> str:
        """The step, as a person reads it."""
        return PHASE_LABELS.get(self.phase, self.phase)

    @property
    def counted(self) -> bool:
        """Whether the step is counted item by item."""
        return self.total > 0

    @property
    def percent(self) -> int | None:
        """How much of a counted step is done, rounded down; ``None`` when it is not counted."""
        if not self.counted:
            return None
        return min(100, self.done * 100 // self.total)

    def describe(self) -> str:
        """One line saying what is being done: ``Evaluating the published rules: 612 of
        1,441 (42%)``, ``Reading return.xbrl``."""
        if self.phase == PHASE_READING and self.subject:
            return f"Reading {self.subject}"
        if self.phase == PHASE_STRUCTURE and self.subject:
            return f"Checking the structure against taxonomy {self.subject}"
        if self.counted:
            return f"{self.label}: {self.done:,} of {self.total:,} ({self.percent}%)"
        return self.label


#: What a long check is handed to say how far it has got. Called on the
#: thread doing the work, so it must be quick and must not raise.
type ProgressCallback = Callable[[Progress], None]


def notify(progress: ProgressCallback | None, event: Progress) -> None:
    """Hand ``event`` to ``progress``, when there is one to hand it to."""
    if progress is not None:
        progress(event)


class StreamProgress:
    """Progress written to a stream — a command's stderr — for a person watching it run.

    On a terminal (``live``) it is one line, rewritten in place at most every
    tenth of a second and cleared on ``close``, so the result printed after it
    stands alone. Anywhere else it is one line per step, and one per tenth of a
    counted step: a log that reads top to bottom.

    Each line carries the time since the printer was made, so a step that takes
    a while is visibly still going. Only plain ASCII control is used — a
    carriage return and spaces — so no terminal needs escape sequences.

    Use it as a context manager, or call ``close`` when the work is done.
    """

    def __init__(
        self,
        stream: TextIO,
        *,
        live: bool,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.stream = stream
        self.live = live
        self._clock = clock
        self._started = clock()
        self._drawn_at: float | None = None
        self._phase: str | None = None
        self._logged_tenth = -1
        self._width = 0

    def __call__(self, event: Progress) -> None:
        """Show ``event``, if it is time to."""
        changed = event.phase != self._phase
        self._phase = event.phase
        if self.live:
            self._draw_live(event, changed=changed)
        else:
            self._draw_log(event, changed=changed)

    def close(self) -> None:
        """Clear the live line, leaving the stream as it was found."""
        if self.live and self._width:
            self.stream.write("\r" + " " * self._width + "\r")
            self.stream.flush()
        self._width = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # -- drawing ------------------------------------------------------------------

    def _draw_live(self, event: Progress, *, changed: bool) -> None:
        now = self._clock()
        finished = event.counted and event.done >= event.total
        due = self._drawn_at is None or now - self._drawn_at >= _REDRAW_SECONDS
        if not (changed or finished or due):
            return
        self._drawn_at = now
        line = self._line(event, now)[: _columns() - 1]
        drawn = line.ljust(self._width)
        self.stream.write("\r" + drawn)
        self.stream.flush()
        self._width = len(drawn)

    def _draw_log(self, event: Progress, *, changed: bool) -> None:
        if changed:
            self._logged_tenth = -1
        tenth = (event.percent // _LOG_STEPS) if event.counted and event.percent is not None else 0
        if not changed and tenth <= self._logged_tenth:
            return
        self._logged_tenth = tenth
        self.stream.write(self._line(event, self._clock()) + "\n")
        self.stream.flush()

    def _line(self, event: Progress, now: float) -> str:
        return f"{event.describe()} - {elapsed(now - self._started)}"


def elapsed(seconds: float) -> str:
    """A duration as a person reads it at a glance: ``8s``, ``1m 05s``."""
    whole = int(seconds)
    if whole < 60:  # noqa: PLR2004 - seconds in a minute
        return f"{whole}s"
    return f"{whole // 60}m {whole % 60:02d}s"


# =============================================================================
# Private helpers
# =============================================================================


def _columns() -> int:
    """How wide the terminal is, so a live line never wraps and stops being rewritable."""
    return shutil.get_terminal_size().columns
