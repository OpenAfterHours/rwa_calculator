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
- the automatic number of workers, from a stand-in ``/proc/meminfo`` and a
  stand-in cgroup memory limit (v1 and v2, set on the process's own group or
  an ancestor), and its fallback to one where there is no ``/proc``;
- that workers do run at once, and that the result does not depend on the
  order they finish in;
- that a worker killed in a pool loses its own rules and nobody else's;
- that a real SIGINT, or a SIGTERM under ``interrupt_on_sigterm``, ends a run
  in seconds and kills the workers it is running — in a process that has
  imported polars, as every real caller has, and in which a signal can land on
  a thread other than the one waiting on the pool;
- that any other exception in the pool kills its workers too.

References:
- packages/rwa-filer/src/rwa_filer/referee/runner.py — ``resolve_jobs``,
  ``prepare_referee``, ``run_referees``
- Linux ``proc(5)`` — ``MemAvailable`` in ``/proc/meminfo``
- Linux cgroup v1 ``memory.limit_in_bytes`` and v2 ``memory.max``
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import textwrap
import threading
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


GIB = 1 << 30


def fake_cgroup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    membership: str,
    groups: dict[str, dict[str, str]],
) -> None:
    """A stand-in ``/proc/self/cgroup`` (``membership``) and cgroup mount (``groups``).

    ``groups`` maps a folder under the mount to the files in it.
    """
    (tmp_path / "proc" / "self").mkdir(parents=True, exist_ok=True)
    (tmp_path / "proc" / "self" / "cgroup").write_text(membership, encoding="utf-8")
    mount = tmp_path / "cgroup"
    for folder, files in groups.items():
        (mount / folder).mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (mount / folder / name).write_text(text, encoding="utf-8")
    mount.mkdir(exist_ok=True)
    monkeypatch.setattr(runner, "_CGROUP", mount)


def v1_group(limit: int, usage: int, inactive: int) -> dict[str, str]:
    return {
        "memory.limit_in_bytes": f"{limit}\n",
        "memory.usage_in_bytes": f"{usage}\n",
        "memory.stat": f"cache 1\ninactive_file 0\ntotal_inactive_file {inactive}\n",
    }


def v2_group(limit: str, current: int, inactive: int) -> dict[str, str]:
    return {
        "memory.max": f"{limit}\n",
        "memory.current": f"{current}\n",
        "memory.stat": f"anon 1\ninactive_file {inactive}\n",
    }


#: What the kernel reports for "no limit" in cgroup v1.
V1_UNLIMITED = 9223372036854771712

#: (membership, groups): each leaves 7 GiB under its limit, where the machine
#: has 14 GiB available — room for one 4 GB worker, not three.
CGROUPS = {
    # A container's --memory under cgroup v1: limit 8, using 2 of which 1 is
    # inactive page cache the kernel reclaims first.
    "v1": ("4:memory:/box/shell\n1:cpu:/\n", {"memory/box/shell": v1_group(8 * GIB, 2 * GIB, GIB)}),
    "v2": ("0::/box\n", {"box": v2_group(str(8 * GIB), 2 * GIB, GIB)}),
    # The limit is set on a parent; the process's own group has none.
    "v1-ancestor": (
        "4:memory:/box/shell\n",
        {
            "memory/box": v1_group(8 * GIB, 2 * GIB, GIB),
            "memory/box/shell": v1_group(V1_UNLIMITED, GIB, 0),
        },
    ),
    "v2-ancestor": (
        "0::/box/shell\n",
        {"box": v2_group(str(8 * GIB), 2 * GIB, GIB), "box/shell": v2_group("max", GIB, 0)},
    ),
    # Inside a cgroup namespace, or a container that mounts its own group as
    # the root: the path /proc names is not under the mount.
    "v1-namespaced": ("4:memory:/docker/abc\n", {"memory": v1_group(8 * GIB, 2 * GIB, GIB)}),
}


@pytest.mark.parametrize("layout", list(CGROUPS))
def test_auto_jobs_fits_the_workers_in_a_cgroup_memory_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str
) -> None:
    """A container's limit, not the host's free memory, is what the OOM killer enforces."""
    # Arrange
    fake_proc(tmp_path, monkeypatch, 14.0)
    monkeypatch.setattr(runner, "_cpu_count", lambda: 4)
    fake_cgroup(tmp_path, monkeypatch, *CGROUPS[layout])

    # Act / Assert — (7 - 1.5) / 4 = 1.4, where the host alone gives (14 - 1.5) / 4 = 3.
    assert runner.resolve_jobs(None, 4.0) == 1


@pytest.mark.parametrize(
    "groups",
    [
        {"memory/box": v1_group(V1_UNLIMITED, 2 * GIB, 0)},
        {"box": v2_group("max", 2 * GIB, 0)},
        {},
    ],
    ids=["v1-unlimited", "v2-max", "no-memory-controller-mounted"],
)
def test_a_cgroup_without_a_memory_limit_leaves_the_machines_memory_to_decide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, groups: dict[str, dict[str, str]]
) -> None:
    # Arrange
    fake_proc(tmp_path, monkeypatch, 14.0)
    monkeypatch.setattr(runner, "_cpu_count", lambda: 4)
    fake_cgroup(tmp_path, monkeypatch, "4:memory:/box\n0::/box\n", groups)

    # Act / Assert
    assert runner.resolve_jobs(None, 4.0) == 3


def test_an_explicit_number_of_jobs_is_taken_as_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — memory for one 9 GB worker only.
    fake_proc(tmp_path, monkeypatch, 12.0)

    # Act / Assert
    assert runner.resolve_jobs(3, 9.0) == 3
    with pytest.raises(ValueError, match="at least 1"):
        runner.resolve_jobs(0, 9.0)


def test_jobs_over_the_memory_budget_is_warned_of_once(
    trimmed: Referee,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The differential script resolves the number to print it, then hands it to the pool."""
    # Arrange — memory for one 2 GB worker; two asked for.
    fake_proc(tmp_path, monkeypatch, 3.6)
    caplog.set_level(logging.WARNING, logger=runner.__name__)

    # Act
    workers = runner.resolve_jobs(2, 2.0)
    run_pool(trimmed, [trimmed.instance], jobs=workers, max_rss_gb=2.0)

    # Assert
    assert workers == 2
    assert [record.getMessage() for record in caplog.records].count(
        "referee: 2 worker(s) at 2.0 GB each can outgrow the 3.6 GB available less 1.5 GB headroom"
    ) == 1


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


def test_an_exception_in_the_pool_kills_the_workers_it_is_running(
    trimmed: Referee, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exception while a minute-long worker runs ends the run in seconds, not a minute."""

    # Arrange — raised as the first worker's progress is written.
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


# ---------------------------------------------------------------------------
# A real signal, in a process that has imported polars
# ---------------------------------------------------------------------------

TESTS_DIR = Path(__file__).resolve().parent.parent

#: A caller of the referee, in a process of its own so that a signal can be sent
#: to it: two stand-in workers that would sleep a minute each, at jobs=2.
DRIVER = textwrap.dedent(
    """
    import json, sys
    from pathlib import Path

    import polars  # noqa: F401 - every real caller has it loaded

    sys.path.insert(0, sys.argv[2])
    from referee_builders import (
        CHUNK_MB, EXAMPLES, FAKE_WORKER, VERDICTS, build_package, write_instance,
    )
    from rwa_filer.referee import interrupt_on_sigterm, runner

    root = Path(sys.argv[1])
    fake = root / "fake_worker.py"
    fake.write_text(FAKE_WORKER, encoding="utf-8")
    runner.WORKER_SCRIPT = fake
    runner.AUTO_FULL_LIMIT_MB = 0.0
    script = {"verdicts": VERDICTS, "examples": EXAMPLES, "every": {"sleep": 60}}
    (root / "script.json").write_text(json.dumps(script), encoding="utf-8")
    prepared = runner.prepare_referee(
        write_instance(root / "instance.xbrl"),
        build_package(root / "taxonomy.zip"),
        workdir=root / "work",
        chunk_mb=CHUNK_MB,
    )
    with interrupt_on_sigterm():
        runner.run_referees([prepared], python=Path(sys.executable), jobs=2)
    """
)


def _alive(pid: int) -> bool:
    """Whether stand-in worker ``pid`` is still running (a zombie has ended)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    return b"fake_worker" in cmdline and stat.rsplit(")", 1)[1].split()[0] != "Z"


@needs_proc
@pytest.mark.parametrize(
    ("signum", "exit_status"),
    [(signal.SIGINT, None), (signal.SIGTERM, 128 + signal.SIGTERM)],
    ids=["SIGINT", "SIGTERM"],
)
def test_a_real_signal_ends_the_run_in_seconds_and_kills_its_workers(
    tmp_path: Path, signum: int, exit_status: int | None
) -> None:
    """CI's cancel sends SIGINT, then SIGTERM; neither may leave 4 GB workers behind.

    A worker runs in a session of its own, so a signal to the run never reaches
    it: the run itself must kill it, and must hear the signal to do so — which
    it does not while its main thread waits on the pool without a timeout and
    the signal is delivered to one of polars' threads.
    """
    # Arrange — both workers started.
    driver = tmp_path / "driver.py"
    driver.write_text(DRIVER, encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(driver), str(tmp_path), str(TESTS_DIR)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    pids_file = tmp_path / "pids.txt"
    pids: list[int] = []
    try:
        deadline = time.monotonic() + 60
        while len(pids) < 2 and time.monotonic() < deadline and process.poll() is None:
            time.sleep(0.1)
            if pids_file.exists():
                pids = [int(line) for line in pids_file.read_text(encoding="utf-8").split()]
        assert len(pids) == 2, process.stderr.read().decode() if process.stderr else ""
        time.sleep(1.0)  # past the first guard sample

        # Act
        sent = time.monotonic()
        process.send_signal(signum)
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=20)
        elapsed = time.monotonic() - sent
        left = [pid for pid in pids if _alive(pid)]

        # Assert
        assert elapsed < 5, f"the run took {elapsed:.1f} s to end after the signal"
        assert left == [], f"workers left running: {left}"
        if exit_status is not None:
            assert process.returncode == exit_status
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        for pid in pids:
            if _alive(pid):
                os.kill(pid, signal.SIGKILL)


def test_interrupt_on_sigterm_restores_the_handler_it_replaced() -> None:
    # Arrange
    before = signal.getsignal(signal.SIGTERM)

    # Act
    with runner.interrupt_on_sigterm():
        inside = signal.getsignal(signal.SIGTERM)

    # Assert
    assert inside is not before
    assert signal.getsignal(signal.SIGTERM) is before


def test_interrupt_on_sigterm_is_a_no_op_off_the_main_thread() -> None:
    """A handler can be installed from the main thread only; elsewhere nothing is tried."""
    # Arrange
    raised: list[BaseException] = []

    def enter() -> None:
        try:
            with runner.interrupt_on_sigterm():
                pass
        except BaseException as exc:  # noqa: BLE001 - the assertion is that nothing is raised
            raised.append(exc)

    # Act
    thread = threading.Thread(target=enter)
    thread.start()
    thread.join()

    # Assert
    assert raised == []
