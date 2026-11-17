"""
The referee's worker pool: several Arelle workers at once, under a memory budget.

Pipeline position:
    prepare_referee (one per instance) -> run_referees (ONE pool for every chunk
        of every instance) -> RefereeResult per instance, merged in plan order

A worker is single-threaded and spends most of its minute in Arelle, so a run
of many chunks is bounded by how many workers can be held in memory at once.
Each worker may grow to its cap before the guard kills it, so the cap — not a
typical peak — is what the automatic choice budgets: as many workers as fit in
the memory the kernel reports available, less a headroom, and no more than one
per CPU.

What is pinned here, with the stand-in worker of ``referee_builders``:
- the automatic number of workers, from a stand-in ``/proc/meminfo``, and its
  fallback to one where there is no ``/proc``;
- that workers do run at once, and that the result does not depend on the
  order they finish in;
- that a worker killed in a pool loses its own rules and nobody else's;
- that an interrupted pool kills the workers it is running.

References:
- packages/rwa-filer/src/rwa_filer/referee/runner.py — ``resolve_jobs``,
  ``prepare_referee``, ``run_referees``
- Linux ``proc(5)`` — ``MemAvailable`` in ``/proc/meminfo``
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from referee_builders import (
    CHUNK_MB,
    EXAMPLES,
    INVALID_FACT,
    UNUSED_PREFIX,
    VERDICTS,
    Referee,
    counts,
    write_instance,
)
from rwa_filer.referee import RefereeResult, runner

KB_PER_GB = 1024 * 1024

needs_proc = pytest.mark.skipif(
    not Path("/proc/self/status").is_file(),
    reason="the memory guard reads /proc, which this platform does not have",
)


def fake_proc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, available_gb: float | None) -> None:
    """A stand-in ``/proc`` whose meminfo reports ``available_gb`` (None: no such line)."""
    proc = tmp_path / "proc"
    proc.mkdir()
    lines = ["MemTotal:       16000000 kB", "MemFree:         1000000 kB"]
    if available_gb is not None:
        lines.append(f"MemAvailable:   {int(available_gb * KB_PER_GB)} kB")
    (proc / "meminfo").write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(runner, "_PROC", proc)


def run_pool(
    referee: Referee,
    instances: list[Path],
    script: dict[str, Any] | None = None,
    **options: Any,
) -> tuple[RefereeResult, ...]:
    """Prepare each instance in its own folder, then run them all through one pool."""
    scripted = {"verdicts": VERDICTS, "examples": EXAMPLES} | (script or {})
    referee.script.write_text(json.dumps(scripted), encoding="utf-8")
    prepared = [
        runner.prepare_referee(
            instance, referee.package, workdir=referee.workdir / instance.stem, chunk_mb=CHUNK_MB
        )
        for instance in instances
    ]
    options.setdefault("python", Path(sys.executable))
    return runner.run_referees(prepared, **options)


# ---------------------------------------------------------------------------
# How many workers at once
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("available_gb", "cap_gb", "cpus", "expected"),
    [
        (14.0, 4.0, 4, 3),  # (14 - 1.5) / 4 = 3.1
        (14.0, 9.0, 4, 1),  # one 9 GB worker fits, two do not
        (14.0, 10.0, 4, 1),
        (64.0, 4.0, 4, 4),  # memory for 15, CPUs for 4
        (64.0, 4.0, 2, 2),
        (3.0, 4.0, 4, 1),  # not even one fits at its cap: still one, as before
    ],
)
def test_auto_jobs_is_the_workers_that_fit_in_available_memory_at_their_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    available_gb: float,
    cap_gb: float,
    cpus: int,
    expected: int,
) -> None:
    # Arrange
    fake_proc(tmp_path, monkeypatch, available_gb)
    monkeypatch.setattr(runner, "_cpu_count", lambda: cpus)

    # Act / Assert
    assert runner.resolve_jobs(None, cap_gb) == expected


def test_the_headroom_is_left_free_of_every_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exactly two caps fit with the headroom to spare; a byte less and one does not."""
    # Arrange
    monkeypatch.setattr(runner, "_cpu_count", lambda: 8)
    fake_proc(tmp_path, monkeypatch, 2 * 4.0 + runner.MEMORY_HEADROOM_GB)

    # Act
    two = runner.resolve_jobs(None, 4.0)
    (tmp_path / "proc" / "meminfo").write_text(
        f"MemAvailable: {int((2 * 4.0 + runner.MEMORY_HEADROOM_GB) * KB_PER_GB) - 1} kB\n",
        encoding="utf-8",
    )
    one = runner.resolve_jobs(None, 4.0)

    # Assert
    assert (two, one) == (2, 1)


@pytest.mark.parametrize("meminfo", ["absent", "no MemAvailable line"])
def test_auto_jobs_is_one_where_available_memory_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, meminfo: str
) -> None:
    # Arrange
    monkeypatch.setattr(runner, "_cpu_count", lambda: 8)
    if meminfo == "absent":
        monkeypatch.setattr(runner, "_PROC", tmp_path / "no-proc")
    else:
        fake_proc(tmp_path, monkeypatch, None)

    # Act / Assert
    assert runner.resolve_jobs(None, 1.0) == 1


def test_an_explicit_number_of_jobs_is_taken_as_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — memory for one 9 GB worker only.
    fake_proc(tmp_path, monkeypatch, 12.0)

    # Act / Assert
    assert runner.resolve_jobs(3, 9.0) == 3
    with pytest.raises(ValueError, match="at least 1"):
        runner.resolve_jobs(0, 9.0)


# ---------------------------------------------------------------------------
# Running at once, merging in plan order
# ---------------------------------------------------------------------------


def test_workers_run_at_once_up_to_jobs(trimmed: Referee) -> None:
    # Arrange — two workers of two seconds each.
    script = {"every": {"sleep": 2.0}}

    # Act
    started = time.monotonic()
    (result,) = run_pool(trimmed, [trimmed.instance], script, jobs=2)
    elapsed = time.monotonic() - started

    # Assert — side by side, not one after the other (which takes four).
    assert result.complete is True
    assert elapsed < 3.5


def test_the_result_does_not_depend_on_the_order_workers_finish_in(trimmed: Referee) -> None:
    """Worker 1 finishes first; its message still comes after worker 0's."""
    # Arrange
    script = {
        "chunk0": {"sleep": 1.5, "messages": [UNUSED_PREFIX]},
        "chunk1": {"messages": [INVALID_FACT, UNUSED_PREFIX]},
    }

    # Act
    (parallel,) = run_pool(trimmed, [trimmed.instance], script, jobs=2)
    (serial,) = run_pool(trimmed, [trimmed.instance], script, jobs=1)

    # Assert
    assert [chunk.index for chunk in parallel.chunks] == [0, 1]
    assert [message.code for message in parallel.messages] == ["EBA.3.4", "xbrldie:invalid"]
    assert parallel.rules == serial.rules
    assert parallel.messages == serial.messages
    assert (parallel.skipped, parallel.lost) == (serial.skipped, serial.lost)


def test_progress_lists_the_finished_workers_in_plan_order(trimmed: Referee) -> None:
    # Act — worker 1 finishes first.
    run_pool(trimmed, [trimmed.instance], {"chunk0": {"sleep": 1.0}}, jobs=2)
    progress = json.loads(
        (trimmed.workdir / trimmed.instance.stem / "progress.json").read_text(encoding="utf-8")
    )

    # Assert
    assert progress["chunks_planned"] == 2
    assert [chunk["index"] for chunk in progress["chunks"]] == [0, 1]


def test_one_pool_runs_every_chunk_of_every_instance(trimmed: Referee) -> None:
    # Arrange
    other = write_instance(trimmed.instance.with_name("other.xbrl"))

    # Act
    first, second = run_pool(trimmed, [trimmed.instance, other], jobs=3)
    launches = sorted((trimmed.script.parent / "launches.txt").read_text().split())

    # Assert — one result per instance, in the order given, each complete.
    assert (
        counts(first)
        == counts(second)
        == {
            "boe_b0001": (3, 0),
            "boe_b0002": (1, 2),
            "v0003_m": (0, 0),
        }
    )
    assert first.complete and second.complete
    assert launches == ["instance/chunk0", "instance/chunk1", "other/chunk0", "other/chunk1"]


@pytest.mark.parametrize(
    ("behaviour", "options", "status"),
    [
        ({"sleep": 60}, {"timeout": 1.0}, "killed: timeout 1s"),
        pytest.param(
            {"allocate_mb": 300, "sleep": 60},
            {"max_rss_gb": 0.2},
            "killed: rss",
            marks=needs_proc,
        ),
    ],
    ids=["timeout", "memory"],
)
def test_a_worker_killed_in_a_pool_loses_its_own_rules_only(
    trimmed: Referee, behaviour: dict[str, Any], options: dict[str, Any], status: str
) -> None:
    # Arrange — the other instance's first worker is killed; three run beside it.
    other = write_instance(trimmed.instance.with_name("other.xbrl"))

    # Act
    first, second = run_pool(
        trimmed, [trimmed.instance, other], {"other/chunk0": behaviour}, jobs=4, **options
    )

    # Assert
    assert first.complete is True
    assert first.lost == ()
    assert second.lost == ("boe_b0001",)
    assert second.chunks[0].status.startswith(status)
    assert second.chunks[1].ok is True
    assert counts(second) == {"boe_b0002": (1, 2), "v0003_m": (0, 0)}


def test_an_interrupted_pool_kills_the_workers_it_is_running(
    trimmed: Referee, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interrupt while a minute-long worker runs ends the run in seconds, not a minute."""

    # Arrange — the interrupt arrives as the first worker's progress is written.
    def interrupt(*_args: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "_write_progress", interrupt)

    # Act
    started = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        run_pool(trimmed, [trimmed.instance], {"chunk1": {"sleep": 60}}, jobs=2)

    # Assert
    assert time.monotonic() - started < 15


def test_run_referee_takes_the_number_of_jobs(trimmed: Referee) -> None:
    # Act
    started = time.monotonic()
    result = trimmed.run({"every": {"sleep": 2.0}}, jobs=2)

    # Assert
    assert result.complete is True
    assert time.monotonic() - started < 3.5
