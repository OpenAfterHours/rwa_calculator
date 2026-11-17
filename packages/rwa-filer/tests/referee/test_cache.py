"""
The referee's result cache: a worker's result, reused when nothing it depends on changed.

Pipeline position:
    run_referees -> per worker: cache key -> hit: the stored result, no worker
                                          -> miss: the worker, then store its result

An Arelle worker is a pure function of what it is handed: the instance's
bytes, the taxonomy package's bytes, the overlay's contents, the filing-rule
plug-in, the spec's settings, the Arelle release and the referee's own code.
The key is a SHA-256 over exactly those — never over a path, so the same
return written to another folder still hits. A hit skips the worker only; the
merge, and every comparison made of the result, run as before.

What is pinned here, with the stand-in worker of ``referee_builders``:
- a second run reuses every result and launches no worker, and the reused
  result is the worker's raw result;
- each keyed input, changed alone, misses — a new release of one of Arelle's
  dependencies included; a path changed alone hits;
- a corrupt or truncated entry, or one whose digest line does not match its
  content, is ignored, recomputed and replaced;
- a worker that failed, wrote nothing or was killed is never stored, and nor
  is a finished one that left an assertion unanswered or logged an error or
  an exception;
- a cache that cannot be written, or an Arelle release that cannot be named,
  costs the reuse and nothing else.

References:
- packages/rwa-filer/src/rwa_filer/referee/runner.py — ``run_referees(cache_dir=...)``
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest

from referee_builders import (
    FAKE_WORKER,
    INVALID_FACT,
    REWRITE_OVERLAP,
    SINGLE_CURRENCY,
    Referee,
    counts,
)
from rwa_filer.referee import runner

IDENTITY = "arelle-release 2.47.5 / python 3.13"
#: The identity the runner computes, before the autouse fixture stands in for it.
REAL_IDENTITY = runner._arelle_identity
#: What the identity probe reports from an Arelle interpreter.
PROBE = {
    "arelle-release": "2.47.5",
    "python": "3.13.1",
    "distributions": ["arelle-release==2.47.5", "lxml==6.1.3", "regex==2026.11.15"],
}


@pytest.fixture(autouse=True)
def arelle_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stand-in worker runs where no arelle-release is installed: name one."""
    monkeypatch.setattr(runner, "_arelle_identity", lambda _python: IDENTITY)


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    return tmp_path / "cache"


def launches(referee: Referee) -> list[str]:
    """Every worker the stand-in was launched as, in order."""
    log = referee.script.parent / "launches.txt"
    return log.read_text(encoding="utf-8").split() if log.exists() else []


def entries(cache: Path) -> list[Path]:
    return sorted(cache.rglob(f"*{runner._ENTRY_SUFFIX}"))


def body(entry: Path) -> bytes:
    """What an entry holds after its digest line: the worker's raw result."""
    return entry.read_bytes().split(b"\n", 1)[1]


# ---------------------------------------------------------------------------
# Reuse
# ---------------------------------------------------------------------------


def test_a_second_run_reuses_every_result_and_launches_no_worker(
    trimmed: Referee, cache: Path
) -> None:
    # Act
    first = trimmed.run(cache_dir=cache)
    second = trimmed.run(cache_dir=cache)

    # Assert — two workers ran, once; the second result is the first.
    assert launches(trimmed) == ["instance/chunk0", "instance/chunk1"]
    assert [chunk.cached for chunk in first.chunks] == [False, False]
    assert [chunk.cached for chunk in second.chunks] == [True, True]
    assert all(chunk.ok for chunk in second.chunks)
    assert second.rules == first.rules
    assert (second.messages, second.skipped, second.lost) == (
        first.messages,
        first.skipped,
        first.lost,
    )


def test_a_cached_result_is_the_workers_raw_result(trimmed: Referee, cache: Path) -> None:
    # Act
    trimmed.run(cache_dir=cache)
    raw = sorted((trimmed.workdir / f"chunk{index}.json").read_bytes() for index in (0, 1))

    # Assert — stored byte for byte, and handed back byte for byte on a hit.
    assert sorted(body(path) for path in entries(cache)) == raw
    trimmed.run(cache_dir=cache)
    assert sorted((trimmed.workdir / f"chunk{index}.json").read_bytes() for index in (0, 1)) == raw


def test_a_hit_refreshes_the_entrys_time(trimmed: Referee, cache: Path) -> None:
    """CI prunes by modification time what a run did not use; a used entry must look used."""
    # Arrange — two good entries, aged a day.
    trimmed.run(cache_dir=cache)
    day_ago = time.time() - 86_400
    for entry in entries(cache):
        os.utime(entry, (day_ago, day_ago))
    started = time.time()

    # Act
    trimmed.run(cache_dir=cache)

    # Assert
    assert all(entry.stat().st_mtime >= started - 1 for entry in entries(cache))


def test_without_a_cache_dir_nothing_is_stored_or_reused(trimmed: Referee, tmp_path: Path) -> None:
    # Act
    trimmed.run()
    trimmed.run()

    # Assert
    assert len(launches(trimmed)) == 4
    assert not list(tmp_path.rglob("*.json.tmp"))


def test_the_same_return_in_another_folder_hits(trimmed: Referee, cache: Path) -> None:
    """Paths are not keyed: the instance, the package and the workdir all move."""
    # Arrange
    trimmed.run(cache_dir=cache)
    elsewhere = trimmed.instance.parent / "elsewhere"
    elsewhere.mkdir()
    instance = Path(shutil.copy(trimmed.instance, elsewhere / "copy.xbrl"))
    package = Path(shutil.copy(trimmed.package, elsewhere / "copy.zip"))

    # Act
    result = runner.run_referee(
        instance,
        package,
        python=Path(sys.executable),
        workdir=elsewhere / "work",
        chunk_mb=600 / 1e6,
        cache_dir=cache,
    )

    # Assert
    assert len(launches(trimmed)) == 2
    assert [chunk.cached for chunk in result.chunks] == [True, True]


# ---------------------------------------------------------------------------
# What the key holds
# ---------------------------------------------------------------------------


def _change_instance(referee: Referee, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    with referee.instance.open("a", encoding="utf-8") as stream:
        stream.write("<!-- one byte more -->\n")
    return {}


def _change_package(referee: Referee, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    with zipfile.ZipFile(referee.package, "a") as archive:
        archive.writestr("tst-package/README.txt", "republished")
    return {}


def _change_arelle(_referee: Referee, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(runner, "_arelle_identity", lambda _python: IDENTITY + " (patched)")
    return {}


def _change_worker(referee: Referee, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    edited = referee.script.parent / "fake_worker_v2.py"
    edited.write_text(FAKE_WORKER + "\n# a later revision of the worker\n", encoding="utf-8")
    monkeypatch.setattr(runner, "WORKER_SCRIPT", edited)
    return {}


def _change_runner(_referee: Referee, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(runner, "_code_sha256", lambda: "0" * 64)
    return {}


def _change_examples(_referee: Referee, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return {"max_examples": 5}


def _change_filing_rules(_referee: Referee, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return {"filing_rules": False}


def _change_chunking(_referee: Referee, _monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    # Every assertion in one worker: a different overlay, of other contents.
    return {"chunk_mb": 1.0}


@pytest.mark.parametrize(
    "change",
    [
        _change_instance,
        _change_package,
        _change_arelle,
        _change_worker,
        _change_runner,
        _change_examples,
        _change_filing_rules,
        _change_chunking,
    ],
    ids=lambda change: change.__name__.removeprefix("_change_"),
)
def test_each_keyed_input_changed_alone_misses(
    trimmed: Referee, cache: Path, monkeypatch: pytest.MonkeyPatch, change: Any
) -> None:
    # Arrange
    trimmed.run(cache_dir=cache)
    before = len(launches(trimmed))

    # Act
    options = change(trimmed, monkeypatch)
    result = trimmed.run(cache_dir=cache, **options)

    # Assert — every worker of the second run ran.
    assert len(launches(trimmed)) == before + len(result.chunks)
    assert not any(chunk.cached for chunk in result.chunks)


def test_a_new_release_of_one_of_arelles_dependencies_misses(
    trimmed: Referee, cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``arelle-release==X`` leaves lxml, regex and the rest unpinned: a new lxml alone re-runs.

    Otherwise every scheduled run after a dependency release would replay the
    verdicts of the old libraries, and store them again.
    """
    # Arrange — the identity computed from a probe, and a run that reuses with it.
    monkeypatch.setattr(runner, "_arelle_identity", REAL_IDENTITY)
    monkeypatch.setattr(runner, "_probe_interpreter", lambda _python: PROBE)
    trimmed.run(cache_dir=cache)
    reused = trimmed.run(cache_dir=cache)
    upgraded = PROBE | {
        "distributions": ["arelle-release==2.47.5", "lxml==6.2.0", "regex==2026.11.15"]
    }
    monkeypatch.setattr(runner, "_probe_interpreter", lambda _python: upgraded)

    # Act
    result = trimmed.run(cache_dir=cache)

    # Assert
    assert [chunk.cached for chunk in reused.chunks] == [True, True]
    assert launches(trimmed)[2:] == ["instance/chunk0", "instance/chunk1"]
    assert not any(chunk.cached for chunk in result.chunks)


def test_the_identity_probe_lists_every_distribution_of_the_interpreter() -> None:
    """Run for real, isolated as a worker is, on the interpreter running these tests."""
    # Act
    probe = runner._probe_interpreter(Path(sys.executable))

    # Assert
    assert probe is not None
    assert f"pytest=={pytest.__version__}" in probe["distributions"]
    assert probe["distributions"] == sorted(probe["distributions"])
    assert probe["python"] == sys.version


def test_an_interpreter_without_arelle_has_no_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr(
        runner, "_probe_interpreter", lambda _python: PROBE | {"arelle-release": None}
    )

    # Act / Assert
    assert REAL_IDENTITY(Path(sys.executable)) is None


def test_the_worker_the_runner_and_the_planner_are_all_keyed() -> None:
    # Act
    sources = runner._code_sources()

    # Assert
    assert [path.name for path in sources] == ["worker.py", "plan.py", "runner.py"]


def test_the_cache_key_reads_no_path(trimmed: Referee, tmp_path: Path) -> None:
    """The same spec with every path moved, its files copied, has the same key."""
    # Arrange
    trimmed.run()
    spec = trimmed.spec(1)
    moved = tmp_path / "moved"
    moved.mkdir()
    copies = {
        key: shutil.copy(spec[key], moved / Path(spec[key]).name) for key in ("instance", "plugin")
    }
    packages = [shutil.copy(path, moved / Path(path).name) for path in spec["packages"]]
    elsewhere = spec | copies | {"packages": packages, "xdg": str(moved / "xdg")}
    keyed = runner._ResultCache(tmp_path / "c", arelle=IDENTITY)

    # Act / Assert
    assert keyed.key(elsewhere) == keyed.key(spec)
    assert keyed.key(spec | {"max_examples": 3}) != keyed.key(spec)


# ---------------------------------------------------------------------------
# What is never stored, and what is never trusted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("behaviour", "options"),
    [
        ({"exit": 1, "stderr": "Traceback ...\nMemoryError\n"}, {}),
        ({"silent": True}, {}),
        ({"garbage": True}, {}),
        ({"sleep": 60}, {"timeout": 0.5}),
    ],
    ids=["failed", "wrote-nothing", "wrote-no-result", "killed"],
)
def test_a_worker_that_did_not_finish_is_never_stored(
    trimmed: Referee, cache: Path, behaviour: dict[str, Any], options: dict[str, Any]
) -> None:
    # Act — worker 1 does not finish; then the same run, with nothing wrong.
    failed = trimmed.run({"chunk1": behaviour}, cache_dir=cache, **options)
    again = trimmed.run(cache_dir=cache)

    # Assert — only worker 0 was stored, so only worker 1 ran again.
    assert failed.complete is False
    assert len(entries(cache)) == 2
    assert launches(trimmed)[2:] == ["instance/chunk1"]
    assert [chunk.cached for chunk in again.chunks] == [True, False]
    assert again.complete is True


def _result(**fields: Any) -> bytes:
    """A worker result of the right outline, with ``fields`` in place of the defaults."""
    shape: dict[str, Any] = {"assertions": {}, "examples": {}, "messages": [], "timings": {}}
    return json.dumps(shape | fields).encode()


#: Damage to an entry's content. Each is re-sealed with a valid digest, so that
#: it is the shape check that has to refuse it.
DAMAGE = {
    "truncated": lambda raw: raw[: len(raw) // 2],
    "empty": lambda _raw: b"",
    "not-json": lambda _raw: b"not json",
    "missing-keys": lambda _raw: json.dumps({"assertions": {}}).encode(),
    "bad-counts": lambda _raw: _result(assertions={"a": "x"}),
    "not-an-object": lambda _raw: json.dumps([1, 2]).encode(),
    "example-not-an-object": lambda _raw: _result(examples={"a": ["text"]}),
    "example-without-facts": lambda _raw: _result(
        examples={"a": [{"level": "ERROR", "text": "t"}]}
    ),
    "fact-not-an-object": lambda _raw: _result(
        examples={"a": [{"level": "ERROR", "text": "t", "facts": [1]}]}
    ),
}


@pytest.mark.parametrize("damage", list(DAMAGE.values()), ids=list(DAMAGE))
def test_a_corrupt_entry_is_ignored_recomputed_and_replaced(
    trimmed: Referee, cache: Path, damage: Any
) -> None:
    # Arrange — worker 0's entry damaged after a good run.
    first = trimmed.run(cache_dir=cache)
    raw = (trimmed.workdir / "chunk0.json").read_bytes()
    entry = next(path for path in entries(cache) if body(path) == raw)
    stored = entry.read_bytes()
    entry.write_bytes(runner._seal(damage(raw)))

    # Act
    second = trimmed.run(cache_dir=cache)

    # Assert — worker 0 ran again, the result is unchanged, the entry is whole again.
    assert launches(trimmed)[2:] == ["instance/chunk0"]
    assert [chunk.cached for chunk in second.chunks] == [False, True]
    assert counts(second) == counts(first)
    assert entry.read_bytes() == stored


@pytest.mark.parametrize(
    "tamper",
    [
        lambda stored: stored.replace(b"[3, 0]", b"[3, 1]"),
        lambda stored: stored.split(b"\n", 1)[1],
    ],
    ids=["content-edited", "no-digest-line"],
)
def test_an_entry_whose_digest_does_not_match_is_never_trusted(
    trimmed: Referee, cache: Path, tamper: Any
) -> None:
    """Still a well-formed result — a count changed by hand — but not what was stored."""
    # Arrange
    first = trimmed.run(cache_dir=cache)
    entry = next(path for path in entries(cache) if b"[3, 0]" in path.read_bytes())
    stored = entry.read_bytes()
    entry.write_bytes(tamper(stored))

    # Act
    second = trimmed.run(cache_dir=cache)

    # Assert
    assert launches(trimmed)[2:] == ["instance/chunk0"]
    assert counts(second) == counts(first)
    assert entry.read_bytes() == stored


def test_a_result_that_left_an_assertion_unanswered_is_never_stored(
    trimmed: Referee, cache: Path
) -> None:
    """Silence is a lost rule, and one bad run must not be replayed on every run after it."""
    # Act — worker 1 finishes but says nothing of boe_b0002; then the same run, healthy.
    failed = trimmed.run({"chunk1": {"omit": ["boe_boe_b0002"]}}, cache_dir=cache)
    again = trimmed.run(cache_dir=cache)

    # Assert
    assert failed.lost == ("boe_b0002",)
    assert launches(trimmed)[2:] == ["instance/chunk1"]
    assert [chunk.cached for chunk in again.chunks] == [True, False]
    assert again.complete is True


@pytest.mark.parametrize(
    "message",
    [
        INVALID_FACT,
        {"code": "xbrl:internalError", "level": "CRITICAL", "text": "unexpected"},
        {"code": "exception:MemoryError", "level": "WARNING", "text": "while evaluating"},
    ],
    ids=["error", "critical", "exception"],
)
def test_a_result_with_an_error_or_an_exception_is_never_stored(
    trimmed: Referee, cache: Path, message: dict[str, str]
) -> None:
    """An exception Arelle caught and logged can be transient; a stored one is forever."""
    # Act
    trimmed.run({"chunk1": {"messages": [message]}}, cache_dir=cache)
    again = trimmed.run({"chunk1": {"messages": [message]}}, cache_dir=cache)

    # Assert — worker 1 ran both times; worker 0, clean, was reused.
    assert launches(trimmed) == ["instance/chunk0", "instance/chunk1", "instance/chunk1"]
    assert [chunk.cached for chunk in again.chunks] == [True, False]


def test_a_message_the_merge_drops_does_not_stop_a_result_being_stored(
    trimmed: Referee, cache: Path
) -> None:
    """Package-overlap noise and the known false EBA.3.1 cannot change a result."""
    # Arrange
    script = {"every": {"messages": [REWRITE_OVERLAP, SINGLE_CURRENCY]}}

    # Act
    trimmed.run(script, cache_dir=cache)
    again = trimmed.run(script, cache_dir=cache)

    # Assert
    assert [chunk.cached for chunk in again.chunks] == [True, True]


def test_a_cache_that_cannot_be_written_costs_the_reuse_only(
    trimmed: Referee, cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An entry is written to a temporary file and renamed: a failed rename leaves neither."""

    # Arrange
    def refuse(*_args: object) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(os, "replace", refuse)

    # Act
    result = trimmed.run(cache_dir=cache)

    # Assert
    assert result.complete is True
    assert entries(cache) == []
    assert [path.name for path in cache.rglob("*") if path.is_file()] == []


def test_an_arelle_that_cannot_be_named_is_run_without_the_cache(
    trimmed: Referee,
    cache: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    monkeypatch.setattr(runner, "_arelle_identity", lambda _python: None)
    caplog.set_level(logging.WARNING, logger=runner.__name__)

    # Act
    trimmed.run(cache_dir=cache)
    result = trimmed.run(cache_dir=cache)

    # Assert
    assert len(launches(trimmed)) == 4
    assert result.complete is True
    assert entries(cache) == []
    assert any("cache" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# Where the cache is
# ---------------------------------------------------------------------------


def test_the_environment_variable_names_the_cache_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    default = tmp_path / "default"

    # Act / Assert
    monkeypatch.delenv(runner.ENV_REFEREE_CACHE, raising=False)
    assert runner.referee_cache_dir(default) == default
    monkeypatch.setenv(runner.ENV_REFEREE_CACHE, "")
    assert runner.referee_cache_dir(default) == default
    monkeypatch.setenv(runner.ENV_REFEREE_CACHE, str(tmp_path / "shared"))
    assert runner.referee_cache_dir(default) == tmp_path / "shared"
