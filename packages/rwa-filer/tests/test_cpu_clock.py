"""
The scaling gates' CPU clock reads work shorter than one of its own steps.

On Windows ``time.thread_time`` moves in 15.625 ms ticks, so a single run of a
fast call read as 0.0 s and the explain scaling gate divided by it. These tests
hold ``cpu_clock.best_cpu_seconds`` to the two things the gates rely on, on any
platform: a fast call never reads as zero, and twice the work reads as about
twice the time.
"""

from __future__ import annotations

import pytest

import cpu_clock
from cpu_clock import best_cpu_seconds, clock_step

#: A unit of pure-Python work, far below a Windows tick (tens of microseconds).
WORK = 2_000


def test_the_clock_is_seen_to_step() -> None:
    """The clock's step is measured as a positive number of seconds."""
    # Arrange / Act
    step = clock_step()

    # Assert
    assert 0 < step < 1, f"thread_time was seen to step by {step}s"


def test_a_call_shorter_than_one_clock_step_reads_above_zero() -> None:
    """A call far shorter than a step still reads as a positive time per run."""
    # Arrange / Act
    seconds = best_cpu_seconds(lambda: _work(WORK), repeats=3)

    # Assert
    assert seconds > 0, f"{WORK} additions read as {seconds}s of CPU"


@pytest.mark.parametrize("tick", [1 / 65_536, 1 / 64], ids=["fine", "coarse"])
def test_per_call_time_recovers_known_durations(
    monkeypatch: pytest.MonkeyPatch, tick: float
) -> None:
    """Measure known work both above the sampling floor and below a single clock tick."""
    elapsed = 0.0
    duration = 1 / 1024

    def advance(seconds: float) -> None:
        nonlocal elapsed
        elapsed += seconds

    # The host's clock is exercised above. Here each read observes only whole ticks.
    monkeypatch.setattr(cpu_clock, "clock_step", lambda: tick)
    monkeypatch.setattr(cpu_clock.time, "thread_time", lambda: (elapsed // tick) * tick)

    once = best_cpu_seconds(lambda: advance(duration), repeats=3)
    twice = best_cpu_seconds(lambda: advance(2 * duration), repeats=3)

    assert (once, twice) == (duration, 2 * duration)


def _work(n: int) -> int:
    """``n`` additions in a Python loop - work the interpreter cannot skip."""
    total = 0
    for i in range(n):
        total += i
    return total
