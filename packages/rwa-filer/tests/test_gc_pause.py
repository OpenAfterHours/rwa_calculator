"""
``rwa_filer._gc.collector_paused``: the collector is handed back as it was found.

Pipeline position:
    a bulk loader  ->  collector_paused()  ->  the build  ->  the caller's collector state

Why this exists: the pause flips a switch that belongs to the whole interpreter
from inside library code. The saving is worth having only if the switch can
never be left in the wrong position — off for a host that had it on, or on for
a command line that had deliberately switched it off. Every test here is about
that: the state before and after, with the collector on and off, when the body
raises, when pauses nest, and when two threads pause at once.

Every test restores the collector itself (``_collector``), so a failure here
cannot leave it off for the rest of the session.
"""

from __future__ import annotations

import gc
import threading
from typing import TYPE_CHECKING

import pytest

from rwa_filer._gc import collector_paused

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _collector() -> Iterator[None]:
    """Put the collector back as the session had it, whatever a test did to it."""
    was_enabled = gc.isenabled()
    yield
    if was_enabled:
        gc.enable()
    else:
        gc.disable()


# ---------------------------------------------------------------------------
# One pause
# ---------------------------------------------------------------------------


def test_a_collector_that_was_on_is_off_inside_and_on_again_after() -> None:
    # Arrange
    gc.enable()

    # Act
    with collector_paused():
        inside = gc.isenabled()

    # Assert
    assert inside is False
    assert gc.isenabled() is True


def test_a_collector_that_was_off_stays_off() -> None:
    """Under a caller that has switched it off, the pause must not switch it on."""
    # Arrange
    gc.disable()

    # Act
    with collector_paused():
        inside = gc.isenabled()

    # Assert
    assert inside is False
    assert gc.isenabled() is False


@pytest.mark.parametrize("was_enabled", [True, False])
def test_the_collector_is_as_it_was_when_the_body_raises(was_enabled: bool) -> None:
    # Arrange
    (gc.enable if was_enabled else gc.disable)()

    # Act
    with pytest.raises(LookupError, match="mid-build"), collector_paused():
        raise LookupError("mid-build")

    # Assert
    assert gc.isenabled() is was_enabled


def test_pauses_nest_and_only_the_outermost_switches_the_collector_back_on() -> None:
    # Arrange
    gc.enable()
    states = []

    # Act
    with collector_paused():
        with collector_paused():
            states.append(gc.isenabled())
        states.append(gc.isenabled())
    states.append(gc.isenabled())

    # Assert — off inside the inner pause, still off after it, on after the outer.
    assert states == [False, False, True]


def test_no_collection_runs_inside_a_pause() -> None:
    """A count: tens of thousands of new containers, and the collector is not started once.

    Read at the end of the block, not after it: the collector may well run the
    moment it is switched back on, and that pass is not the pause's to prevent.
    """
    # Arrange
    gc.enable()
    passes: list[int] = []

    def watch(phase: str, info: dict[str, int]) -> None:
        if phase == "start":
            passes.append(info["generation"])

    def churn() -> list[list[int]]:
        return [[number] for number in range(50_000)]

    gc.callbacks.append(watch)
    try:
        kept = churn()
        unpaused = len(passes)

        # Act
        with collector_paused():
            kept += churn()
            paused = len(passes) - unpaused
    finally:
        gc.callbacks.remove(watch)

    # Assert
    assert len(kept) == 100_000
    assert unpaused >= 1, "the same work unpaused starts no collection - a zero would say nothing"
    assert paused == 0


# ---------------------------------------------------------------------------
# The decorator form
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("was_enabled", [True, False])
def test_a_decorated_function_runs_paused_and_hands_the_collector_back(was_enabled: bool) -> None:
    # Arrange
    (gc.enable if was_enabled else gc.disable)()

    @collector_paused()
    def build(count: int) -> tuple[bool, int]:
        return gc.isenabled(), count

    # Act
    first, second = build(1), build(2)

    # Assert — each call is its own pause.
    assert (first, second) == ((False, 1), (False, 2))
    assert gc.isenabled() is was_enabled


def test_a_decorated_function_that_raises_hands_the_collector_back() -> None:
    # Arrange
    gc.enable()

    @collector_paused()
    def build() -> None:
        raise LookupError("mid-build")

    # Act
    with pytest.raises(LookupError, match="mid-build"):
        build()

    # Assert
    assert gc.isenabled() is True


# ---------------------------------------------------------------------------
# Two threads
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("first_out", ["the first in", "the second in"])
def test_two_overlapping_pauses_end_with_the_collector_on(first_out: str) -> None:
    """Whichever thread finishes first, the collector is never left off."""
    # Arrange
    gc.enable()
    entered = {name: threading.Event() for name in ("the first in", "the second in")}
    leave = {name: threading.Event() for name in entered}
    left = {name: threading.Event() for name in entered}

    def pause(name: str) -> None:
        with collector_paused():
            entered[name].set()
            leave[name].wait(timeout=30)
        left[name].set()

    threads = {name: threading.Thread(target=pause, args=(name,)) for name in entered}
    last_out = next(name for name in entered if name != first_out)

    # Act — both pauses are open at once, then they close in the order under test.
    threads["the first in"].start()
    assert entered["the first in"].wait(timeout=30)
    threads["the second in"].start()
    assert entered["the second in"].wait(timeout=30)
    both_open = gc.isenabled()
    leave[first_out].set()
    assert left[first_out].wait(timeout=30)
    leave[last_out].set()
    for thread in threads.values():
        thread.join(timeout=30)

    # Assert
    assert both_open is False
    assert gc.isenabled() is True
