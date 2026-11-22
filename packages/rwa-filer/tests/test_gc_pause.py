"""
``rwa_filer._gc``: the collector is paused, or run, and handed back as it was found.

Pipeline position:
    a bulk loader  ->  collector_paused()  ->  the build  ->  the caller's collector state
    a workbook read  ->  collector_running()  ->  the read  ->  the caller's collector state

Why this exists: both helpers flip a switch that belongs to the whole
interpreter from inside library code. That is worth doing only if the switch
can never be left in the wrong position — off for a host that had it on, or on
for a command line that had deliberately switched it off. Every test here is
about that: the state before and after, with the collector on and off, when the
body raises, when blocks nest, and when two threads run one at once. For
``collector_running`` also: it acts only in a one-shot command, where the
process entry's policy holds the collector off — collections run inside it, and
what the block left is freed by the time it ends — and changes nothing
anywhere else, including a collecting process whose collector is off only
because another thread is inside a pause.

Every test restores the collector itself (``_collector``), so a failure here
cannot leave it off for the rest of the session.
"""

from __future__ import annotations

import gc
import threading
import weakref
from typing import TYPE_CHECKING

import pytest

from rwa_filer import entry
from rwa_filer._gc import collector_paused, collector_running

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


# ---------------------------------------------------------------------------
# collector_running: the one exception to the command line's policy
# ---------------------------------------------------------------------------


@pytest.fixture
def one_shot(monkeypatch: pytest.MonkeyPatch) -> None:
    """This process as the entry leaves it for a one-shot command: collector off, by its policy.

    The entry's own state, set as ``rwa_filer.entry.run`` sets it and put back
    after the test; ``_collector`` puts the collector back.
    """
    monkeypatch.setattr(entry, "_collector_switched_off", True)
    gc.disable()


class _Node:
    """An object that can be weakly referenced and can refer to itself."""

    other: _Node | None = None


def _collected_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    """Record every ``gc.collect`` call from here on, and still collect."""
    calls: list[tuple[object, ...]] = []
    collect = gc.collect

    def counted(*args: int) -> int:
        calls.append(args)
        return collect(*args)

    monkeypatch.setattr(gc, "collect", counted)
    return calls


@pytest.mark.usefixtures("one_shot")
def test_in_a_one_shot_command_the_collector_is_on_inside_and_off_again_after() -> None:
    # Act
    with collector_running():
        inside = gc.isenabled()

    # Assert
    assert inside is True
    assert gc.isenabled() is False


@pytest.mark.usefixtures("one_shot")
def test_what_a_block_left_is_freed_when_it_switches_the_collector_back_off() -> None:
    """A cycle made inside the block is gone after it: it is not held to the end of a command."""
    # Act — a self-referencing object no reference count will ever free.
    with collector_running():
        node = _Node()
        node.other = node
        left = weakref.ref(node)
        del node
        alive_inside = left() is not None

    # Assert — alive while the block ran (the test could see it), freed by its end.
    assert alive_inside, "the cycle was freed before the block ended - nothing is proven"
    assert left() is None
    assert gc.isenabled() is False


@pytest.mark.usefixtures("one_shot")
def test_collections_run_inside_a_block_and_not_outside_it() -> None:
    """A count: the same churn in a one-shot command, outside a block and inside one."""
    # Arrange
    passes: list[int] = []

    def watch(phase: str, info: dict[str, int]) -> None:
        if phase == "start":
            passes.append(info["generation"])

    def churn() -> list[list[int]]:
        return [[number] for number in range(50_000)]

    gc.callbacks.append(watch)
    try:
        kept = churn()
        outside = len(passes)

        # Act
        with collector_running():
            kept += churn()
            inside = len(passes) - outside
    finally:
        gc.callbacks.remove(watch)

    # Assert
    assert len(kept) == 100_000
    assert outside == 0, "the collector ran while it was off - the setup is wrong"
    assert inside >= 1


@pytest.mark.usefixtures("one_shot")
def test_the_collector_is_off_again_when_a_running_block_raises() -> None:
    # Act
    with pytest.raises(LookupError, match="mid-read"), collector_running():
        raise LookupError("mid-read")

    # Assert
    assert gc.isenabled() is False


@pytest.mark.usefixtures("one_shot")
def test_running_blocks_nest_and_only_the_outermost_switches_off_and_collects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    calls = _collected_calls(monkeypatch)
    states = []

    # Act
    with collector_running():
        with collector_running():
            states.append(gc.isenabled())
        states.append((gc.isenabled(), len(calls)))
    states.append((gc.isenabled(), len(calls)))

    # Assert — on inside both; still on, nothing collected yet, after the
    # inner; off after the outer, which collected once, in full.
    assert states == [True, (True, 0), (False, 1)]
    assert calls == [()]


@pytest.mark.usefixtures("one_shot")
def test_a_pause_inside_a_running_block_hands_it_back_on_and_the_block_ends_off() -> None:
    # Arrange
    states = []

    # Act — the state inside the read, inside the pause, after the pause, after both.
    with collector_running():
        states.append(gc.isenabled())
        with collector_paused():
            states.append(gc.isenabled())
        states.append(gc.isenabled())
    states.append(gc.isenabled())

    # Assert
    assert states == [True, False, True, False]


@pytest.mark.usefixtures("one_shot")
def test_a_decorated_function_runs_collected_and_hands_the_collector_back() -> None:
    # Arrange
    @collector_running()
    def read(count: int) -> tuple[bool, int]:
        return gc.isenabled(), count

    # Act
    first, second = read(1), read(2)

    # Assert — each call is its own block.
    assert (first, second) == ((True, 1), (True, 2))
    assert gc.isenabled() is False


@pytest.mark.usefixtures("one_shot")
@pytest.mark.parametrize("first_out", ["the first in", "the second in"])
def test_two_overlapping_running_blocks_end_with_the_collector_off(first_out: str) -> None:
    """In a one-shot command the collector is never left on, whichever block ends first."""
    # Arrange
    entered = {name: threading.Event() for name in ("the first in", "the second in")}
    leave = {name: threading.Event() for name in entered}
    left = {name: threading.Event() for name in entered}

    def read(name: str) -> None:
        with collector_running():
            entered[name].set()
            leave[name].wait(timeout=30)
        left[name].set()

    threads = {name: threading.Thread(target=read, args=(name,)) for name in entered}
    last_out = next(name for name in entered if name != first_out)

    # Act — both blocks are open at once, then they close in the order under test.
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
    assert both_open is True
    assert gc.isenabled() is False


# ---------------------------------------------------------------------------
# collector_running outside a one-shot command: it does nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("was_enabled", [True, False])
def test_outside_a_one_shot_command_a_running_block_changes_nothing(
    was_enabled: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A test session, a host calling main(), rwa-calc: their collector is theirs, on or off."""
    # Arrange
    (gc.enable if was_enabled else gc.disable)()
    calls = _collected_calls(monkeypatch)
    assert entry.collector_switched_off() is False, "this session is under the entry's policy"

    # Act
    with collector_running():
        inside = gc.isenabled()

    # Assert
    assert (inside, gc.isenabled()) == (was_enabled, was_enabled)
    assert calls == []


@pytest.mark.usefixtures("one_shot")
def test_once_a_command_hands_the_collector_back_a_running_block_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dashboard, once it serves: the entry's policy no longer holds, and nor does this."""
    # Arrange
    entry.keep_collecting()
    calls = _collected_calls(monkeypatch)
    gc.disable()  # as a pause in another thread would have it, for a moment

    # Act
    with collector_running():
        inside = gc.isenabled()

    # Assert
    assert entry.collector_switched_off() is False
    assert (inside, gc.isenabled()) == (False, False)
    assert calls == []


@pytest.mark.parametrize("first_out", ["the pause", "the read"])
@pytest.mark.parametrize("first_in", ["the pause", "the read"])
def test_in_a_process_that_collects_an_overlapping_pause_and_read_leave_it_on(
    first_in: str, first_out: str
) -> None:
    """A dashboard reading an XBRL instance and a workbook at once, on two threads.

    The case this guards: the pause opens (collector off), the read opens and
    finds it off, the pause closes (back on), then the read closes. A read that
    took the off it found for its caller's state would switch the collector off
    there, for the rest of the server's life.
    """
    # Arrange
    gc.enable()
    names = ("the pause", "the read")
    entered = {name: threading.Event() for name in names}
    leave = {name: threading.Event() for name in names}
    left = {name: threading.Event() for name in names}
    blocks = {"the pause": collector_paused, "the read": collector_running}

    def work(name: str) -> None:
        with blocks[name]():
            entered[name].set()
            leave[name].wait(timeout=30)
        left[name].set()

    threads = {name: threading.Thread(target=work, args=(name,)) for name in names}
    second_in = next(name for name in names if name != first_in)
    last_out = next(name for name in names if name != first_out)

    # Act — both open, in the order under test; then both close, in the order under test.
    threads[first_in].start()
    assert entered[first_in].wait(timeout=30)
    threads[second_in].start()
    assert entered[second_in].wait(timeout=30)
    leave[first_out].set()
    assert left[first_out].wait(timeout=30)
    leave[last_out].set()
    for thread in threads.values():
        thread.join(timeout=30)

    # Assert
    assert gc.isenabled() is True
