"""
The defect-injection harness spawns exactly what it declares, or it scores nothing.

Pipeline position:
    (no pipeline stage — a contract on ``scripts/defect_injection.py``, the gate
    runner behind the nightly ``Nightly Defect Injection`` campaign)

A gate scores a mutant by its exit code and nothing else, so anything that turns
a gate red for a reason unrelated to the mutant is scored as a detection. These
tests cover the two such ways that are about the spawn:

- **A partially retargeted ladder.** ``DEFECT_INJECTION_PYTHON`` rewrites the
  ``uv run …`` commands through a named interpreter. If one spawn site skipped the
  rewrite, its gate would fail to start on every mutant, score every mutant
  ``DETECTED``, and nothing in the scorecard would say so.
- **An interpreter that cannot start.** Every gate goes red, the campaign reports
  ~100% detection with zero escapes, and that is arithmetically indistinguishable
  from an airtight estate. On this project's own sandbox the default ``uv run``
  path exits 2 with "Could not acquire lock … Read-only file system".

They do not cover a gate that is red on the unmutated tree for a reason of its
own while the interpreter starts and imports the engine. The pre-flight passes,
and every mutant that gets past the rungs below that gate is scored ``DETECTED``
at it. Two instances: on a runner with no ``uv``, the ``contracts`` rung is red
on the clean tree, because ``tests/contracts/test_wheel_install_gate.py``
requires ``uv`` on ``PATH``; and an override interpreter that imports the engine
but has no ``pytest`` (a wheel-only or ``--no-dev`` environment) turns every
pytest gate red.
Closing that needs every gate run once on the clean tree before any mutant,
which is a change to the harness, not a test here.

The override and the spawn pre-flight shipped with a hand-run check and no test,
and the escape log recorded that as owed. These are the tests. Every spawn site
(``preflight``, ``run_gate``, ``_prepare_gate_baselines``) is observed through a
recorder on ``subprocess.run``, so the real ``uv`` is never executed. The only
real processes are the pre-flight's deliberately broken interpreters, one control
that exits 0, a ``uv`` stub, and one adequacy check that ``rwa_calc`` itself
imports under ``-S``. ``PATH`` holds nothing a test did not put there.
So with the override unset, the pre-flight's ``uv`` is either unfindable or that
stub, and the stub fails the way the sandbox's ``uv`` did: "Could not acquire
lock … Read-only file system" on stderr, exit 2. The stub case models the
bullet's sandbox: the harness started from the venv's Python, the override unset,
and the inner ``uv`` failing on its lock. It does not model the nightly on a day
its ``uv`` breaks outright: the nightly starts the harness through ``uv run``, so
that day fails before ``main()`` is reached.

References:
- scripts/defect_injection.py — ``resolve_command``, ``preflight``, ``main``,
  ``injected``
- docs/development/defect-injection.md — "Running it", "Safety"
- docs/development/escape-log.md — the injection-harness runner override entry
"""

from __future__ import annotations

import re
import shlex
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from scripts import defect_injection
from scripts.defect_catalogue import Mutant

import rwa_calc

_ENV = defect_injection.INTERPRETER_ENV_VAR

#: What the default ``uv run`` path gave on this project's sandbox. It is the
#: bullet's measured motivation, and every exit-2 case below reproduces it.
_UV_LOCK_FAILURE = "error: Could not acquire lock: Read-only file system (os error 30)"
_UV_LOCK_EXIT = 2

#: A ``uv`` that fails exactly that way, for the cases where the override is unset.
_UV_LOCK_FAILURE_STUB = (
    f"#!/bin/sh\necho {shlex.quote(_UV_LOCK_FAILURE)} >&2\nexit {_UV_LOCK_EXIT}\n"
)

#: An override interpreter that fails the same way: same stderr, same exit. The
#: message is hex-encoded in the source because the abort prints the command line
#: as well. Spelled out, that line alone would satisfy a match on the message, and
#: an abort that dropped the interpreter's own output would still pass.
_PYTHON_LOCK_FAILURE = (
    f"import sys; sys.stderr.write(bytes.fromhex({_UV_LOCK_FAILURE.encode().hex()!r}).decode());"
    f" raise SystemExit({_UV_LOCK_EXIT})"
)

#: Everything ``main()`` must not reach once the pre-flight has failed: the
#: baseline digest, the gate baselines, any mutant, any gate.
_DOWNSTREAM_OF_PREFLIGHT = (
    "stable_baseline",
    "output_digest",
    "_prepare_gate_baselines",
    "run_campaign",
    "probe_reachable",
    "injected",
    "run_gate",
)

#: At least one per failure branch of ``preflight`` (the non-zero-exit branch has
#: two: a positive exit and a signal): how to build the override from a scratch
#: directory, a pattern for the reason the abort must give, and a pre-flight
#: timeout.
_UNUSABLE_INTERPRETERS = [
    pytest.param(
        lambda root: shlex.quote(str(root / "missing" / "python")),
        "the executable does not exist",
        None,
        id="does-not-exist",
    ),
    pytest.param(
        lambda root: shlex.quote(str(root)),
        "it could not be executed",
        None,
        id="not-executable",
    ),
    # uv's lock failure, stderr included: a refusal keyed on what the interpreter
    # printed, rather than on its exit code, would let this through. The abort
    # must also quote the interpreter's own error, so the operator sees the cause.
    pytest.param(
        lambda _root: shlex.join((sys.executable, "-c", _PYTHON_LOCK_FAILURE)),
        rf"(?s)it exited {_UV_LOCK_EXIT}\n.*{re.escape(_UV_LOCK_FAILURE)}",
        None,
        id="exits-2-like-uv-lock",
    ),
    # An OOM kill on a small runner. ``subprocess`` reports a signal as a negative
    # exit code, so a refusal of only positive codes would let it through.
    # ``signal.SIGKILL`` exists only on POSIX. It is read with ``getattr`` so that
    # importing this module on Windows (a supported dev platform) cannot stop the
    # whole session's collection; the case itself is skipped there.
    pytest.param(
        lambda _root: shlex.join(
            (sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)")
        ),
        rf"it exited -{int(getattr(signal, 'SIGKILL', 9))}\b",
        None,
        id="killed-by-signal",
        marks=pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="no SIGKILL off POSIX"),
    ),
    pytest.param(
        lambda _root: f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(60)'",
        "it did not finish within",
        1.0,
        id="hangs",
    ),
]

#: The three ways ``main()`` meets an unusable interpreter. Each gives the override
#: built from a scratch directory (``None`` = unset), the ``uv`` script to put on
#: ``PATH`` (``None`` = no ``uv`` at all), and the fragments the abort must print.
#: Both unset cases take the default path, the one the nightly configures (it sets
#: no override), with the harness started from a Python that does not need ``uv``:
#: - ``uv`` unfindable takes the pre-flight's ``FileNotFoundError`` branch;
#: - ``uv`` exiting 2 with its lock error takes the non-zero-exit branch. That is
#:   the bullet's measured motivation. Of the three, it is the only one that goes
#:   red if the refusal is made conditional on the override, or tolerates "lock"
#:   in stderr.
_MAIN_INTERPRETERS = [
    pytest.param(
        lambda root: str(root / "missing" / "python"),
        None,
        lambda root: (
            f"command   {root / 'missing' / 'python'} -c ",
            "the executable does not exist",
        ),
        id="override-does-not-exist",
    ),
    pytest.param(
        lambda _root: None,
        None,
        lambda _root: ("command   uv run python -c ", "the executable does not exist"),
        id="unset-uv-unfindable",
    ),
    pytest.param(
        lambda _root: None,
        _UV_LOCK_FAILURE_STUB,
        lambda _root: (
            "command   uv run python -c ",
            f"it exited {_UV_LOCK_EXIT}",
            _UV_LOCK_FAILURE,
        ),
        id="unset-uv-exits-2-on-its-lock",
        # The ``uv`` stub is a ``#!/bin/sh`` script, which ``shutil.which`` will not
        # find on Windows without a PATHEXT extension.
        marks=pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell stub"),
    ),
]


@pytest.fixture(autouse=True)
def _nothing_on_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An empty ``PATH``: only an interpreter named by absolute path can spawn.

    Every process this module means to start is named that way, or is the ``uv``
    stub a test installs as the sole entry on ``PATH``. So a regression that drops
    the override can fail these tests but can never reach the real ``uv``, which
    on a read-only sandbox exits 2 and anywhere else syncs an env.
    """
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))


# =============================================================================
# (i) No override: the default is what the docstring says you can type
# =============================================================================


def test_with_no_override_every_spawn_is_byte_identical_to_its_declaration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Unset, the pre-flight, every gate and every ``baseline_cmd`` spawn as declared."""
    # Arrange — an operator shell may export the override; this is the unset case.
    monkeypatch.delenv(_ENV, raising=False)
    declared = _declared_spawns(tmp_path)

    # Act
    spawned = _spawn_at_every_site(monkeypatch, tmp_path)

    # Assert
    assert any(gate.baseline_cmd for gate in defect_injection.LADDER), (
        "no gate declares a baseline_cmd - the baseline spawn site would go unobserved"
    )
    assert spawned == declared


# =============================================================================
# (ii) An override: every spawn moves, or the harness refuses
# =============================================================================


def test_an_override_retargets_every_spawn_and_leaves_none_on_uv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``uv run python X`` -> ``<interp> X``; ``uv run pytest X`` -> ``<interp> -m pytest X``."""
    # Arrange — a multi-token override, so the shlex split is exercised too.
    interpreter = (str(tmp_path / "venv" / "bin" / "python"), "-X", "utf8")
    monkeypatch.setenv(_ENV, shlex.join(interpreter))
    declared = _declared_spawns(tmp_path)

    # Act
    spawned = _spawn_at_every_site(monkeypatch, tmp_path)

    # Assert
    assert {"python", "pytest"} <= {cmd[2] for cmd in declared}, (
        "the ladder must exercise both rewrite branches, or one goes unchecked"
    )
    assert len(spawned) == len(declared)
    for before, after in zip(declared, spawned, strict=True):
        runner = ("-m", "pytest") if before[2] == "pytest" else ()
        assert after == (*interpreter, *runner, *before[3:]), f"{before} spawned as {after}"


@pytest.mark.parametrize(
    "cmd",
    [
        ("python", "scripts/arch_check.py"),  # not in ``uv run`` form at all
        ("uv", "run", "watchfire", "check"),  # a tool with no interpreter form
        ("uv", "python", "scripts/arch_check.py"),  # ``uv`` without ``run``
    ],
    ids=["bare-python", "unknown-tool", "uv-without-run"],
)
def test_an_override_refuses_a_command_it_cannot_retarget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cmd: tuple[str, ...]
) -> None:
    """A silent pass-through would leave that gate on ``uv`` — a partial retarget."""
    # Arrange
    monkeypatch.setenv(_ENV, str(tmp_path / "python"))

    # Act / Assert
    with pytest.raises(SystemExit, match=_ENV):
        defect_injection.resolve_command(cmd)


# =============================================================================
# (iii) The pre-flight refuses every interpreter that cannot run a gate
# =============================================================================


@pytest.mark.parametrize(("interpreter", "reason", "timeout_seconds"), _UNUSABLE_INTERPRETERS)
def test_preflight_raises_on_an_interpreter_that_cannot_run_a_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    interpreter: Callable[[Path], str],
    reason: str,
    timeout_seconds: float | None,
) -> None:
    """Each failure branch aborts with ``InterpreterUnusable``, naming what it tried."""
    # Arrange
    override = interpreter(tmp_path)
    monkeypatch.setenv(_ENV, override)
    if timeout_seconds is not None:
        monkeypatch.setattr(defect_injection, "_PREFLIGHT_TIMEOUT_SECONDS", timeout_seconds)

    # Act
    with pytest.raises(defect_injection.InterpreterUnusable, match=reason) as refused:
        defect_injection.preflight()

    # Assert — the probe ran through the override, not through some other spawn.
    assert f"command   {shlex.split(override)[0]} " in str(refused.value)


def test_preflight_passes_an_interpreter_that_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The control: a pre-flight that refused everything would refute nothing above."""
    # Arrange — ``-c pass`` consumes the probe's own ``-c`` as argv and exits 0.
    monkeypatch.setenv(_ENV, f"{shlex.quote(sys.executable)} -c pass")

    # Act
    defect_injection.preflight()

    # Assert
    assert "Spawn pre-flight OK" in capsys.readouterr().out


def test_preflight_raises_on_an_interpreter_that_spawns_but_cannot_import_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe imports an engine entry point, not the package's lazy ``__init__``.

    ``-S`` drops site-packages, so polars is gone, while ``PYTHONPATH`` naming only
    ``src`` keeps ``import rwa_calc`` working. That is the escape log's
    ``/usr/bin/python3``: it starts and imports the package, then reddens every gate.
    A probe weakened to ``import rwa_calc``, or to nothing, passes it.
    """
    # Arrange — PYTHONPATH is explicit: under ``-S`` an editable install's ``.pth``
    # is not read, so without it the package import would fail too.
    monkeypatch.setenv(_ENV, f"{shlex.quote(sys.executable)} -S")
    monkeypatch.setenv("PYTHONPATH", str(Path(rwa_calc.__file__).resolve().parents[1]))
    package_only = subprocess.run(
        (sys.executable, "-S", "-c", "import rwa_calc"),
        cwd=defect_injection._REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert package_only.returncode == 0, (
        "the package itself does not import here, so a probe weakened to "
        f"`import rwa_calc` would also be refused:\n{package_only.stderr}"
    )

    # Act
    with pytest.raises(defect_injection.InterpreterUnusable, match="it exited 1") as refused:
        defect_injection.preflight()

    # Assert — it was the engine's dependency stack that failed, not the probe itself.
    assert "ModuleNotFoundError" in str(refused.value)


@pytest.mark.parametrize(("override", "uv_script", "abort_says"), _MAIN_INTERPRETERS)
@pytest.mark.parametrize(
    "ladder_args",
    [
        (),
        ("--ladder", "full"),
        ("--ladder", "fast"),
        # The escape log's own verified-red invocation, and a resumed campaign: a
        # pre-flight made conditional on either flag would skip it for that run.
        ("--ladder", "fast", "--mutants", "control-reachable-output-floor-schedule"),
        ("--ladder", "fast", "--resume"),
        # The chunking pair LESSONS G names, and a per-gate timeout: a pre-flight
        # made conditional on --categories or --timeout would also skip it.
        ("--ladder", "fast", "--categories", "control"),
        ("--ladder", "fast", "--timeout", "1"),
    ],
    ids=[
        "legacy-default",
        "full",
        "fast",
        "fast-named-mutant",
        "fast-resume",
        "fast-categories",
        "fast-timeout",
    ],
)
def test_an_unusable_interpreter_exits_2_before_the_baseline_and_before_any_mutant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    ladder_args: tuple[str, ...],
    override: Callable[[Path], str | None],
    uv_script: str | None,
    abort_says: Callable[[Path], tuple[str, ...]],
) -> None:
    """``main()`` converts the refusal to exit 2 and measures, mutates and writes nothing."""
    # Arrange — the real pre-flight runs; everything after it is a tripwire.
    root = tmp_path.resolve()
    out = root / "scorecard.json"
    reached: list[str] = []
    interpreter = override(root)
    if interpreter is None:
        monkeypatch.delenv(_ENV, raising=False)
    else:
        monkeypatch.setenv(_ENV, interpreter)
    uv = None if uv_script is None else _put_uv_on_path(monkeypatch, root, uv_script)
    assert shutil.which("uv") == uv, (
        "the uv on PATH is not the one this case built, so the unset pre-flight would "
        "spawn something other than the failure under test - possibly a working uv"
    )
    monkeypatch.setattr(defect_injection, "_REPO_ROOT", root)
    monkeypatch.setattr(defect_injection, "_ALLOWED_ROOT", root)
    # Stubbed, not skipped: a dirty shared tree would return 1 before the pre-flight.
    monkeypatch.setattr(
        defect_injection, "assert_targets_clean", lambda: reached.append("assert_targets_clean")
    )
    # Provenance is read before the pre-flight (P5.46: a --resume mismatch knowable
    # from the file is refused before anything is spawned), and ``root`` is no git
    # checkout, so the commit is stubbed as the probe tests stub it.
    monkeypatch.setattr(defect_injection, "head_commit", lambda: "0" * 40)
    for name in _DOWNSTREAM_OF_PREFLIGHT:
        monkeypatch.setattr(defect_injection, name, _tripwire(name, reached))
    monkeypatch.setattr(sys, "argv", ["defect_injection.py", *ladder_args, "--out", str(out)])

    # Act
    code = defect_injection.main()

    # Assert
    assert code == 2
    assert reached == ["assert_targets_clean"]
    assert not out.exists()
    stderr = capsys.readouterr().err
    assert "NOTHING SCORED" in stderr
    assert [said for said in abort_says(root) if said not in stderr] == []


# =============================================================================
# The restore machinery, off the happy path
# =============================================================================


def test_a_mutant_is_restored_and_its_exit_hook_disarmed_when_the_body_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A gate that crashes mid-mutation must not leave ``src/`` mutated."""
    # Arrange
    target, mutant = _declared_target(monkeypatch, tmp_path)
    original = target.read_bytes()
    hooks = _ExitHooks()
    monkeypatch.setattr(defect_injection, "atexit", hooks)

    # Act
    with pytest.raises(RuntimeError, match="gate crashed"), defect_injection.injected(mutant):
        mutated = target.read_bytes()
        raise RuntimeError("gate crashed")

    # Assert
    assert mutated != original, "the mutant never applied - restoring it would prove nothing"
    assert target.read_bytes() == original
    assert hooks.armed == [], "a stale exit hook outlived its mutant"


def test_the_exit_hook_armed_for_a_mutant_restores_the_target_on_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The ``atexit`` guard is a restorer in its own right, not a placeholder."""
    # Arrange
    target, mutant = _declared_target(monkeypatch, tmp_path)
    original = target.read_bytes()
    hooks = _ExitHooks()
    monkeypatch.setattr(defect_injection, "atexit", hooks)

    # Act — fire the hook as interpreter exit would, while still mutated.
    with defect_injection.injected(mutant):
        mutated = target.read_bytes()
        (hook,) = hooks.armed
        hook()
        after_hook = target.read_bytes()

    # Assert
    assert mutated != original, "the mutant never applied - restoring it would prove nothing"
    assert after_hook == original


# =============================================================================
# Helpers
# =============================================================================


def _declared_spawns(baseline_dir: Path) -> list[tuple[str, ...]]:
    """Every command the harness spawns, as declared, in the order it spawns them."""

    def _fill(cmd: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(part.format(baseline=baseline_dir.as_posix()) for part in cmd)

    return [
        _fill(defect_injection._PREFLIGHT_CMD),
        *(_fill(gate.cmd) for gate in defect_injection.LADDER),
        *(
            _fill(gate.baseline_cmd)
            for gate in defect_injection.LADDER
            if gate.baseline_cmd is not None
        ),
    ]


def _spawn_at_every_site(
    monkeypatch: pytest.MonkeyPatch, baseline_dir: Path
) -> list[tuple[str, ...]]:
    """Drive each spawn site over the whole ladder and record the argv it hands the OS."""
    spawned: list[tuple[str, ...]] = []

    def _record(cmd: tuple[str, ...], *_args: object, **_kwargs: object) -> object:
        spawned.append(tuple(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(defect_injection.subprocess, "run", _record)
    defect_injection.preflight()
    for gate in defect_injection.LADDER:
        defect_injection.run_gate(gate, baseline_dir)
    defect_injection._prepare_gate_baselines(defect_injection.LADDER, baseline_dir)
    return spawned


def _put_uv_on_path(monkeypatch: pytest.MonkeyPatch, root: Path, script: str) -> str:
    """Install ``script`` as an executable ``uv``, make it ``PATH``'s only entry, return it."""
    bin_dir = root / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(script, encoding="utf-8")
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    return str(uv)


def _tripwire(name: str, reached: list[str]) -> Callable[..., object]:
    """Record the call, then fail loudly: nothing downstream may run."""

    def _reached(*_args: object, **_kwargs: object) -> object:
        reached.append(name)
        raise AssertionError(f"{name} ran after the spawn pre-flight failed")

    return _reached


def _declared_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Mutant]:
    """A scratch module declared as the only mutation target, and a mutant for it."""
    target = tmp_path / "pkg" / "mod.py"
    target.parent.mkdir()
    target.write_bytes(b"a = 1\nb = 2\n")
    monkeypatch.setattr(defect_injection, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(defect_injection, "targets", lambda: frozenset({"pkg/mod.py"}))
    mutant = Mutant(
        id="test-restore",
        category="generic",
        target="pkg/mod.py",
        old="b = 2",
        new="b = 3",
        summary="a one-line edit to a scratch module",
        rationale="restoration must survive the unhappy paths",
    )
    return target, mutant


class _ExitHooks:
    """Stands in for ``atexit``: records what is armed, so it can be fired or inspected."""

    def __init__(self) -> None:
        self.armed: list[Callable[[], None]] = []

    def register(self, hook: Callable[[], None]) -> Callable[[], None]:
        self.armed.append(hook)
        return hook

    def unregister(self, hook: Callable[[], None]) -> None:
        self.armed = [armed for armed in self.armed if armed is not hook]
