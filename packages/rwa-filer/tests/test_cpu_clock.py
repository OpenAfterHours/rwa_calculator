"""
The scaling gates' CPU clock reads work shorter than one of its own steps.

On Windows ``time.thread_time`` moves in 15.625 ms ticks, so a single run of a
fast call read as 0.0 s and the explain scaling gate divided by it. These tests
hold ``cpu_clock.best_cpu_seconds`` to the two things the gates rely on, on any
platform: a fast call never reads as zero, and twice the work reads as about
twice the time.
"""

from __future__ import annotations

from cpu_clock import best_cpu_seconds, clock_step

#: A unit of pure-Python work, far below a Windows tick (tens of microseconds).
WORK = 2_000
#: Twice the work should read as twice the time; the band allows for noise, not for a zero.
MIN_DOUBLING_RATIO = 1.4
MAX_DOUBLING_RATIO = 2.8


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


def test_twice_the_work_reads_as_about_twice_the_time() -> None:
    """The ratio a scaling gate takes is meaningful below one clock step."""
    # Arrange / Act
    once = best_cpu_seconds(lambda: _work(WORK), repeats=3)
    twice = best_cpu_seconds(lambda: _work(2 * WORK), repeats=3)

    # Assert
    ratio = twice / once
    assert MIN_DOUBLING_RATIO < ratio < MAX_DOUBLING_RATIO, (
        f"twice the work read as {ratio:.2f}x the time ({twice:.2e}s against {once:.2e}s)"
    )


def _work(n: int) -> int:
    """``n`` additions in a Python loop - work the interpreter cannot skip."""
    total = 0
    for i in range(n):
        total += i
    return total
