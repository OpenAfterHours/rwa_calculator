"""
The CPU time a callable takes, read above the resolution of the clock that measures it.

Used by:
    tests/boe/test_engine_scaling.py, tests/workflow/test_explain_scaling.py -
    the scaling gates' second line, a CPU-time ratio beside the call-count ratio.

Key responsibilities:
- Measure this thread's CPU time (``time.thread_time``), not the wall clock: the
  code timed is pure Python on the calling thread, and time spent waiting for a
  loaded box is not counted.
- Make every sample span ``STEPS_PER_SAMPLE`` steps of that clock, running the
  callable as many times as it takes, so a sample is never read as zero and the
  rounding to a step is at most 1/20th of it.

Why the step has to be measured
-------------------------------
On Windows a thread's CPU time (``GetThreadTimes``) advances in scheduler ticks
of 15.625 ms, although ``time.get_clock_info("thread_time")`` reports a
resolution of 100 ns. A call that takes less than a tick reads as 0.0 s, so a
gate dividing the large size's time by the small size's raised
``ZeroDivisionError`` there (``test_explain_scaling``, 40 countries, 2026-11-23:
the release of rwa-filer 0.1.6 stopped on it). On Linux the clock steps in well
under a microsecond and a sample is one run, as it was before.
"""

from __future__ import annotations

import time
from functools import cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

#: Each sample covers at least this many steps of the clock: a step is at most 5% of it.
STEPS_PER_SAMPLE = 20
#: Steps watched to find the clock's step: the least of them is taken.
STEPS_OBSERVED = 3


def best_cpu_seconds(act: Callable[[], object], repeats: int) -> float:
    """The least CPU time this thread spent per run of ``act``, over ``repeats`` samples.

    A sample runs ``act`` back to back until it has covered ``STEPS_PER_SAMPLE``
    steps of the clock, and is divided by the runs it took; a sample that falls
    short is discarded and the runs are doubled. Where one run already covers
    them (every rule-engine size on Linux), a sample is one run.

    Args:
        act: The work to time. It is run at least ``repeats`` times.
        repeats: How many samples to take the least of.

    Returns:
        Seconds of this thread's CPU time per run of ``act`` - above zero.
    """
    floor = STEPS_PER_SAMPLE * clock_step()
    runs = 1
    best = float("inf")
    taken = 0
    while taken < repeats:
        elapsed = _cpu_seconds(act, runs)
        if elapsed < floor:
            runs *= 2
            continue
        best = min(best, elapsed / runs)
        taken += 1
    return best


@cache
def clock_step() -> float:
    """The smallest step this thread's CPU clock has been seen to take, in seconds.

    Watched, not read from ``time.get_clock_info``, which reports the unit the
    clock counts in rather than how often it moves. Costs ``STEPS_OBSERVED``
    steps of spinning once per process: about 47 ms on Windows.
    """
    steps: list[float] = []
    previous = time.thread_time()
    while len(steps) < STEPS_OBSERVED:
        now = time.thread_time()
        if now != previous:
            steps.append(now - previous)
            previous = now
    return min(steps)


def _cpu_seconds(act: Callable[[], object], runs: int) -> float:
    """This thread's CPU time over ``runs`` back-to-back runs of ``act``, in seconds."""
    started = time.thread_time()
    for _ in range(runs):
        act()
    return time.thread_time() - started
