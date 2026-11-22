"""
The process entry of ``rwa-filer``: collector off for one command, frozen heap at exit.

Pipeline position:
    the ``rwa-filer`` console script  ->  rwa_filer.entry.run  ->  rwa_filer.cli.main

The entry switches the cyclic garbage collector off for a one-shot command and
freezes the heap before the interpreter shuts down. Two things can go wrong
with that, and neither shows in any output:

- memory that grows silently, because a command starts creating cyclic garbage
  the collector is no longer there to reclaim;
- a command that never ends — a server — left running without a collector.

So what is pinned here is counted, not timed, and every count is taken in a
child process: this test session's own collector is never switched.

- the console script IS the entry, and a real ``validate`` through it runs no
  collection of any generation and ends with the heap frozen;
- the command's exit code, output and written files are what ``main`` gives;
- ``main`` called in-process leaves the collector exactly as it found it — on
  or off — the dashboard command included;
- every sub-command the parser knows is listed as one-shot or long-lived, and
  each long-lived one is shown to have its collector back before it serves;
- with the collector off, the unreachable objects left by a ``validate`` are
  few, and the SAME number at two sizes of one return, whether it is read from
  a fact table, an XBRL instance or a workbook. The workbook reader makes
  cyclic garbage for every sheet, so its read runs with the collector on;
- ``RWA_FILER_COLLECTOR=on`` keeps the collector on, and the heap unfrozen,
  for the whole command; any other value is today's policy.

References:
- packages/rwa-filer/src/rwa_filer/entry.py
- packages/rwa-filer/tests/referee/test_worker_exit.py — the same policy for the Arelle worker
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
import tomllib
import zipfile
from dataclasses import dataclass
from datetime import date
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest

import rwa_filer
from pack_builders import VALID_LEI
from rwa_filer.cli import EXIT_FAILED, EXIT_INCOMPLETE, EXIT_OK, build_parser, main
from rwa_filer.model import ReturnHeader
from rwa_filer.readers import read_return
from rwa_filer.readers.excel import write_workbook
from rwa_filer.release import resolve_release
from rwa_filer.xbrl.writer import write_instance

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

SCRIPT = "rwa-filer"
#: What ``[project.scripts]`` must name: the process entry, not ``cli.main``.
ENTRY = "rwa_filer.entry:run"
#: The switch that keeps the collector on for a run, as the entry documents it.
#: Every child starts without it unless a test sets it, so a developer's shell
#: that sets it cannot change what these tests see.
SWITCH = "RWA_FILER_COLLECTOR"

HEADER_ARGS = ["--entity", VALID_LEI, "--reference-date", "2027-03-31", "--module", "PRA001"]
BASE = f"{VALID_LEI}_PRA001_2027-03-31"

#: Two facts in real PRA001 cells whose rules break: ``validate`` exits 1.
BROKEN_CSV = (
    "table,sheet,row,column,value\n"
    "OF07.00.01.01,0008,0010,0010,1000000\n"
    "OF07.00.01.01,0008,0010,0030,-5000\n"
)
#: One reported zero. Nothing blocks (exit 0); OF 07.00 alone leaves out
#: templates its rules read, so the check is incomplete (exit 3 when asked).
CLEAN_CSV = "table,sheet,row,column,value\nOF07.00.01.01,0008,0010,0010,0\n"

#: The marker a child writes its probe after, on stderr.
PROBE = "@@probe "
#: Why "the collector ran" is read as collections in any generation. Which
#: generation ``gc.get_stats()`` counts a young pass under depends on the
#: interpreter: CPython 3.14.4's incremental collector counts them under
#: generation 1 and never under 0, where 3.13 and 3.14.6 count them under 0.
_COUNTED_ANYWHERE = "no collection ran in any generation while the collector was meant to be on"

#: Runs the declared console script's target as the generated script does
#: (``sys.exit(target())``), with a probe that reports at interpreter exit. The
#: probe is registered before the entry runs, so it is the last exit hook to
#: run. ``gc.collect()`` first, so that the counts start from zero and loading
#: the entry itself cannot tip a collection (it allocates about 50 objects, 130
#: with nothing byte-compiled, against a threshold of 2,000).
ENTRY_CHILD = f"""
import atexit, gc, json, sys
from importlib.metadata import entry_points

def report():
    after = gc.get_stats()
    sys.stderr.write({PROBE!r} + json.dumps({{
        "collector_on": gc.isenabled(),
        "collections": [a["collections"] - b["collections"] for a, b in zip(after, before)],
        "frozen": gc.get_freeze_count(),
        "unfrozen": len(gc.get_objects()),
        "package": sys.modules["rwa_filer"].__file__,
        "command_line_loaded": "rwa_filer.cli" in sys.modules,
    }}) + "\\n")

(script,) = entry_points(group="console_scripts", name={SCRIPT!r})
sys.argv = [{SCRIPT!r}, *sys.argv[1:]]
atexit.register(report)
gc.collect()
before = gc.get_stats()
sys.exit(script.load()())
"""

#: The dashboard through the entry, with the server and the file opening
#: replaced by probes of the collector's state.
DASH_CHILD = f"""
import atexit, gc, json, sys
from importlib.metadata import entry_points
import rwa_filer.dash
from rwa_filer.dash import Workspace

seen = {{}}
opening = Workspace.open

def open_(self, *args, **options):
    seen["collector_on_while_opening"] = gc.isenabled()
    return opening(self, *args, **options)

def serve(workspace, **options):
    seen["collector_on_while_serving"] = gc.isenabled()
    seen["returns_open"] = len(workspace.returns())

Workspace.open = open_
rwa_filer.dash.serve = serve
atexit.register(lambda: sys.stderr.write({PROBE!r} + json.dumps(seen) + "\\n"))
(script,) = entry_points(group="console_scripts", name={SCRIPT!r})
sys.argv = [{SCRIPT!r}, *sys.argv[1:]]
sys.exit(script.load()())
"""

#: ``main`` called in-process by a host that runs with its collector OFF.
HOST_CHILD = f"""
import gc, json, sys
import rwa_filer.dash
from rwa_filer.cli import main

seen = {{}}
rwa_filer.dash.serve = lambda workspace, **options: seen.update(
    collector_on_while_serving=gc.isenabled()
)
gc.disable()
before = gc.get_stats()
code = main(sys.argv[1:])
seen.update(
    code=code,
    collector_on_after=gc.isenabled(),
    frozen=gc.get_freeze_count(),
    collections=[a["collections"] - b["collections"] for a, b in zip(gc.get_stats(), before)],
)
sys.stderr.write({PROBE!r} + json.dumps(seen) + "\\n")
"""

#: One command through the entry, then, just before the entry freezes the heap,
#: a collection: what the command left unreachable for the end of the process.
GARBAGE_CHILD = f"""
import gc, json, sys
from rwa_filer.entry import run

freeze = gc.freeze

def probe_then_freeze():
    sys.stdout.flush()
    sys.stderr.write({PROBE!r} + json.dumps({{"unreachable": gc.collect()}}) + "\\n")
    freeze()

gc.freeze = probe_then_freeze
sys.argv = [{SCRIPT!r}, *sys.argv[1:]]
run()
"""

#: The two geographical-breakdown tables, each with an open country axis: the
#: return grows by one copy of their cells per country, and its workbook by one
#: worksheet per table per country.
OPEN_TABLES = ("OF09.01.01.01", "OF09.02.01.01")
SMALL_COUNTRIES = 5
LARGE_COUNTRIES = 40
#: The return's input kinds, by suffix: each has its own reader.
INPUT_KINDS = ("parquet", "xbrl", "xlsx")
#: Unreachable objects a ``validate`` through the entry may leave for the end of
#: the process. Measured, the same at 2,770 and 22,160 facts: 1,667 from a fact
#: table and 1,694 from an XBRL instance — the argument parser's cycles and
#: nothing of the return's — and 849 from a workbook, whose read ends with a
#: collection. The ceiling is about twice the largest. One cycle per fact would
#: add 19,390.
MAX_UNREACHABLE = 3_500
#: The blank workbook the ``template`` fixture writes: three tables, 18 sheets.
WORKBOOK_TABLES = ("OF02.01.01.01", "OF07.00.01.01", "OF09.01.01.01")
WORKBOOK_SHEETS = 18


@dataclass(frozen=True)
class Child:
    """One child process: how it ended, what it printed, what its probe saw."""

    code: int
    out: str
    err: str
    probe: dict[str, Any]


def _child(source: str, *argv: str, env: Mapping[str, str] | None = None) -> Child:
    """Run ``source`` in a fresh interpreter with ``argv`` and read its probe.

    The child gets this process's environment without ``SWITCH``, plus ``env``.
    """
    environment = {name: value for name, value in os.environ.items() if name != SWITCH}
    done = subprocess.run(  # noqa: S603 - this interpreter, the test's own source
        [sys.executable, "-c", source, *argv],
        capture_output=True,
        text=True,
        check=False,
        env=environment | dict(env or {}),
    )
    probes = [line for line in done.stderr.splitlines() if line.startswith(PROBE)]
    assert len(probes) == 1, f"the child wrote {len(probes)} probe line(s):\n{done.stderr}"
    err = "".join(
        line for line in done.stderr.splitlines(keepends=True) if not line.startswith(PROBE)
    )
    return Child(done.returncode, done.stdout, err, json.loads(probes[0][len(PROBE) :]))


def _csv(folder: Path, text: str, name: str = "facts.csv") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text)
    return path


@pytest.fixture(scope="module")
def workdir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("entry")


@pytest.fixture(scope="module")
def validated(workdir: Path) -> Child:
    """A real ``validate`` through the entry: broken rules, evidence written."""
    return _child(
        ENTRY_CHILD,
        "validate",
        str(_csv(workdir / "validated", BROKEN_CSV)),
        *HEADER_ARGS,
        "--evidence",
        str(workdir / "validated" / "run.evidence.jsonl.gz"),
        "--no-timestamp",
    )


@pytest.fixture(scope="module")
def built(workdir: Path) -> Child:
    """A real ``build`` through the entry: instance, zip and manifest written."""
    return _child(
        ENTRY_CHILD,
        "build",
        str(_csv(workdir / "built", CLEAN_CSV)),
        "--out",
        str(workdir / "built" / "out"),
        *HEADER_ARGS,
        "--zip",
        "--no-timestamp",
    )


@dataclass(frozen=True)
class Sized:
    """One return, written once in each input kind the command line reads."""

    facts: int
    sheets: int
    files: dict[str, Path]


@pytest.fixture(scope="module")
def geographical(workdir: Path) -> dict[int, Sized]:
    """The geographical return at two sizes, as a fact table, an XBRL instance and a workbook."""
    pack = resolve_release("PRA001", "4.1.1").pack
    header = ReturnHeader(
        entity_identifier=VALID_LEI, reference_date=date(2027, 3, 31), module="PRA001"
    )
    sized = {}
    for countries in (SMALL_COUNTRIES, LARGE_COUNTRIES):
        files = {kind: workdir / f"geographical-{countries}.{kind}" for kind in INPUT_KINDS}
        ret = read_return(_geographical_table(files["parquet"], countries), header)
        files["xbrl"].write_bytes(write_instance(ret, pack).content)
        sheets = write_workbook(pack, files["xlsx"], ret=ret)
        sized[countries] = Sized(facts=ret.facts.height, sheets=sheets, files=files)
    return sized


@pytest.fixture(scope="module")
def template(workdir: Path) -> tuple[Child, Path]:
    """A blank workbook of three tables, written through the entry."""
    workbook = workdir / "template.xlsx"
    arguments = ["--module", "PRA001", "--tables", *WORKBOOK_TABLES, "--out", str(workbook)]
    return _child(ENTRY_CHILD, "template", *arguments), workbook


# ---------------------------------------------------------------------------
# The console script is the entry
# ---------------------------------------------------------------------------


def test_the_console_script_is_declared_and_installed_as_the_process_entry() -> None:
    # Arrange
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text("utf-8"))

    # Act
    declared = project["project"]["scripts"][SCRIPT]
    (installed,) = entry_points(group="console_scripts", name=SCRIPT)

    # Assert — ``cli:main`` here would run every command with the collector on.
    assert declared == ENTRY
    assert installed.value == declared, (
        f"the environment's {SCRIPT} script is {installed.value!r}, not what pyproject.toml "
        "declares: run `uv sync` so the script is regenerated"
    )


def test_a_validate_through_the_entry_runs_no_garbage_collection(validated: Child) -> None:
    # Assert — the child ran this checkout's command line, and ran it to a verdict.
    assert validated.probe["package"] == rwa_filer.__file__
    assert validated.probe["command_line_loaded"] and validated.out.startswith("BLOCKED")
    # Not a young, a middle or a full collection, from loading the entry to the exit.
    assert validated.probe["collector_on"] is False
    assert validated.probe["collections"] == [0, 0, 0]


def test_the_entry_freezes_the_heap_after_the_command_and_before_exit(validated: Child) -> None:
    # Assert — what the command built is in the permanent generation, which the
    # interpreter's shutdown does not walk; only what came after the freeze is not.
    # Measured: 731,792 objects frozen, 2 not.
    assert validated.out.startswith("BLOCKED"), "no command ran: there was no heap to freeze"
    assert validated.probe["frozen"] > 100_000
    assert validated.probe["unfrozen"] < 1_000


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        pytest.param(["taxonomy", "list", "--module", "pra001"], EXIT_OK, id="0-done"),
        pytest.param(["validate", "ABSENT", *HEADER_ARGS], EXIT_FAILED, id="1-failed"),
        pytest.param(["no-such-command"], 2, id="2-usage-error"),
        pytest.param(
            ["validate", "CLEAN", *HEADER_ARGS, "--require-complete"],
            EXIT_INCOMPLETE,
            id="3-incomplete",
        ),
    ],
)
def test_the_entry_exits_with_the_commands_own_code(
    arguments: list[str], expected: int, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    files = {"CLEAN": _csv(tmp_path, CLEAN_CSV), "ABSENT": tmp_path / "absent.csv"}
    argv = [str(files[item]) if item in files else item for item in arguments]

    # Act — through the entry in a child, and in-process through ``main``.
    child = _child(ENTRY_CHILD, *argv)
    try:
        in_process: object = main(argv)
    except SystemExit as usage:
        in_process = usage.code
    printed = capsys.readouterr()

    # Assert — the same code and the same words, and the heap frozen on every way out.
    assert (child.code, in_process) == (expected, expected)
    assert (child.out, child.err) == (printed.out, printed.err)
    assert child.out or child.err, "the command said nothing: no output was compared"
    assert child.probe["frozen"] > 0


def test_the_files_written_through_the_entry_are_the_files_main_writes(
    validated: Child,
    built: Child,
    workdir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Nothing is left for a finaliser to flush: every byte is on disk at exit."""
    # Arrange
    evidence = tmp_path / "run.evidence.jsonl.gz"
    out = tmp_path / "out"

    # Act — the two commands again, in-process.
    main(
        [
            "validate",
            str(_csv(tmp_path / "validated", BROKEN_CSV)),
            *HEADER_ARGS,
            "--evidence",
            str(evidence),
            "--no-timestamp",
        ]
    )
    main(
        [
            "build",
            str(_csv(tmp_path / "built", CLEAN_CSV)),
            "--out",
            str(out),
            *HEADER_ARGS,
            "--zip",
            "--no-timestamp",
        ]
    )
    capsys.readouterr()
    # A file that a finaliser (``__del__``) completes is completed when the
    # collector frees its owner. This process has a collector and the entry's
    # never runs one, so the comparison is with what a collecting process ends
    # up with on disk.
    gc.collect()

    # Assert — byte for byte: the compressed evidence, the instance, the zip, the manifest.
    assert (validated.code, built.code) == (EXIT_FAILED, EXIT_OK)
    written = workdir / "validated" / "run.evidence.jsonl.gz"
    assert written.read_bytes() == evidence.read_bytes()
    names = sorted(path.name for path in out.iterdir())
    assert names == [f"{BASE}.manifest.json", f"{BASE}.xbrl", f"{BASE}.zip"]
    for name in names:
        assert (workdir / "built" / "out" / name).read_bytes() == (out / name).read_bytes(), name


def test_a_workbook_written_through_the_entry_is_a_complete_archive(
    template: tuple[Child, Path],
) -> None:
    """The one writer that is not this package's: its archive is closed by ``save``."""
    # Arrange
    child, workbook = template

    # Assert — a zip with its central directory, every member's checksum good.
    assert child.code == EXIT_OK and child.probe["frozen"] > 0
    assert f"{WORKBOOK_SHEETS} worksheet(s)" in child.out
    with zipfile.ZipFile(workbook) as archive:
        assert archive.testzip() is None
        assert "xl/workbook.xml" in archive.namelist()


def test_the_module_run_as_a_script_goes_through_the_entry() -> None:
    """``python -m rwa_filer.cli`` is a process started for one command too."""
    # Arrange — the module run as ``__main__``, with the probe of the entry child.
    source = ENTRY_CHILD.replace(
        "sys.exit(script.load()())",
        "import runpy; runpy.run_module('rwa_filer.cli', run_name='__main__')",
    )
    assert source != ENTRY_CHILD, "the child still calls the console script's target"

    # Act
    child = _child(source, "--version")

    # Assert
    assert child.code == 0 and child.out.startswith("rwa-filer ")
    assert child.probe["collector_on"] is False and child.probe["frozen"] > 0


# ---------------------------------------------------------------------------
# main() in-process touches nothing
# ---------------------------------------------------------------------------


def test_main_called_in_process_leaves_the_collector_as_it_found_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    before = (gc.isenabled(), gc.get_freeze_count(), gc.get_threshold())
    assert before[0] is True, "this session's collector is off: switching it off would not show"

    # Act
    code = main(["validate", str(_csv(tmp_path, BROKEN_CSV)), *HEADER_ARGS])

    # Assert — a test session, or a host, must never have its collector changed.
    assert code == EXIT_FAILED and capsys.readouterr().out.startswith("BLOCKED")
    assert (gc.isenabled(), gc.get_freeze_count(), gc.get_threshold()) == before


def test_main_called_by_a_host_with_its_collector_off_leaves_it_off(tmp_path: Path) -> None:
    """Only the entry switches the collector: ``main`` and the dashboard leave it as it is."""
    # Arrange — the dashboard command: it opens and validates a file, then serves.
    argv = ["dash", str(_csv(tmp_path, CLEAN_CSV)), *HEADER_ARGS, "--no-browser"]

    # Act
    child = _child(HOST_CHILD, *argv, "--workdir", str(tmp_path / "work"))

    # Assert — the command got as far as serving, and the host's collector is
    # still off and its heap unfrozen.
    assert child.probe["code"] == EXIT_OK
    assert child.probe["collector_on_while_serving"] is False
    assert child.probe["collector_on_after"] is False and child.probe["frozen"] == 0


def test_a_workbook_read_for_a_host_with_its_collector_off_runs_no_collection(
    template: tuple[Child, Path],
) -> None:
    """The workbook reader collects for the entry's one-shot policy only, never for a host."""
    # Arrange — a blank workbook: every sheet is read, and none holds a fact.
    wrote, workbook = template
    assert f"{WORKBOOK_SHEETS} worksheet(s)" in wrote.out, wrote.out

    # Act
    child = _child(HOST_CHILD, "validate", str(workbook), *HEADER_ARGS)

    # Assert — the workbook was read (a blank one is reported as holding no
    # facts), and the host's collector stayed off throughout.
    assert child.probe["code"] == EXIT_FAILED and "[STR009]" in child.out
    assert child.probe["collections"] == [0, 0, 0]
    assert child.probe["collector_on_after"] is False and child.probe["frozen"] == 0


# ---------------------------------------------------------------------------
# One-shot or long-lived: every sub-command is one or the other
# ---------------------------------------------------------------------------

#: Commands that do their work and end. They run with the collector off.
ONE_SHOT = frozenset(
    {
        "validate",
        "build",
        "signoff",
        "verify",
        "diff",
        "compare",
        "referee",
        "template",
        "taxonomy",
        "taxonomy list",
        "taxonomy compile",
        "rulebook",
        "rulebook list",
        "rulebook import",
        "rulebook check",
        "rulebook deny-list",
        "rulebook deny-list import",
        "rulebook deny-list check",
        "rulebook issues",
        "rules",
        "rules list",
        "rules import",
        "rules check",
    }
)


def _dash_through_the_entry(folder: Path) -> dict[str, Any]:
    """What the collector was doing while ``dash FILE`` opened its file, and while it served."""
    child = _child(
        DASH_CHILD,
        "dash",
        str(_csv(folder, CLEAN_CSV)),
        *HEADER_ARGS,
        "--no-browser",
        "--workdir",
        str(folder / "work"),
    )
    assert child.code == EXIT_OK, child.err
    return child.probe


#: Commands that go on running after their start-up work, each with the probe
#: that shows what its collector does. A command added here without a probe
#: cannot be written down; one added nowhere fails the test below.
LONG_LIVED: dict[str, Callable[[Path], dict[str, Any]]] = {"dash": _dash_through_the_entry}


def test_every_sub_command_is_listed_as_one_shot_or_long_lived() -> None:
    # Arrange
    registered = set(_sub_commands(build_parser()))

    # Assert — the parser was walked, and the two lists are exactly its commands.
    assert {"validate", "dash", "rulebook deny-list import"} <= registered
    assert ONE_SHOT.isdisjoint(LONG_LIVED)
    unlisted = sorted(registered - ONE_SHOT - set(LONG_LIVED))
    assert not unlisted, (
        f"{unlisted} is in neither ONE_SHOT nor LONG_LIVED. The process entry runs every "
        "command with the garbage collector off: a command that ends with its work belongs in "
        "ONE_SHOT; one that goes on running must call rwa_filer.entry.keep_collecting() before "
        "it does, and belongs in LONG_LIVED with a probe that shows it"
    )
    assert not sorted((ONE_SHOT | set(LONG_LIVED)) - registered), "a listed command is gone"


@pytest.mark.parametrize("command", sorted(LONG_LIVED))
def test_a_long_lived_command_has_its_collector_back_before_it_serves(
    command: str, tmp_path: Path
) -> None:
    # Act
    seen = LONG_LIVED[command](tmp_path)

    # Assert — the start-up work (a file opened and validated) ran with the
    # collector off; the server started with it on.
    assert seen["returns_open"] == 1, "no file was opened: the start-up work did not run"
    assert seen["collector_on_while_opening"] is False
    assert seen["collector_on_while_serving"] is True


# ---------------------------------------------------------------------------
# Memory, by count: what a command leaves unreachable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", INPUT_KINDS)
def test_the_garbage_a_validate_leaves_does_not_grow_with_the_return(
    kind: str, geographical: dict[int, Sized]
) -> None:
    """With no collector, a cycle per fact, sheet or evaluation would be memory per fact.

    The same count at both sizes, not a bound per fact or per sheet: whatever a
    command leaves for the end of the process must not depend on the return.
    """
    # Arrange — the same tables at two sizes: eight times the facts and the sheets.
    small, large = geographical[SMALL_COUNTRIES], geographical[LARGE_COUNTRIES]
    assert large.facts == 8 * small.facts > 2_000, (small, large)
    assert large.sheets == 8 * small.sheets, (small, large)

    # Act
    few = _child(GARBAGE_CHILD, "validate", str(small.files[kind]), *HEADER_ARGS)
    many = _child(GARBAGE_CHILD, "validate", str(large.files[kind]), *HEADER_ARGS)

    # Assert — both read and validated every fact they were given; then the counts.
    assert f", {small.facts} facts, 2 tables" in few.out.splitlines()[0]
    assert f", {large.facts} facts, 2 tables" in many.out.splitlines()[0]
    assert 0 < few.probe["unreachable"] <= MAX_UNREACHABLE, (
        f"{few.probe['unreachable']} unreachable object(s) after a small validate of a .{kind}; "
        "at most 1,694 when this was written, the argument parser's cycles. A new option adds "
        "a few; a jump means a command now creates cyclic garbage of its own"
    )
    assert many.probe["unreachable"] == few.probe["unreachable"], (
        f"{few.probe['unreachable']} unreachable object(s) at {small.facts} facts, "
        f"{many.probe['unreachable']} at {large.facts}, from a .{kind}: reading or validating "
        "now leaves cyclic garbage that grows with the return, which a one-shot command "
        "(collector off) holds until it exits"
    )


def test_a_workbook_is_read_with_the_collector_on_and_the_command_ends_with_it_off(
    geographical: dict[int, Sized],
) -> None:
    """The workbook reader makes cyclic garbage for every sheet: its read collects, nothing else."""
    # Act — through the entry, which switches the collector off for the command.
    child = _child(
        ENTRY_CHILD, "validate", str(geographical[SMALL_COUNTRIES].files["xlsx"]), *HEADER_ARGS
    )

    # Assert — the workbook was read and validated; it collected while it was
    # read, and the collector is off again, as the entry had it, and frozen at exit.
    assert child.out.startswith("SUBMITTABLE"), child.out
    assert sum(child.probe["collections"]) > 0, _COUNTED_ANYWHERE
    assert child.probe["collector_on"] is False
    assert child.probe["frozen"] > 100_000


# ---------------------------------------------------------------------------
# The switch: RWA_FILER_COLLECTOR=on
# ---------------------------------------------------------------------------


def test_the_switch_keeps_the_collector_on_and_the_heap_unfrozen(tmp_path: Path) -> None:
    """The policy can be turned off without a release: the command runs as main() would."""
    # Act
    child = _child(
        ENTRY_CHILD, "validate", str(_csv(tmp_path, BROKEN_CSV)), *HEADER_ARGS, env={SWITCH: "on"}
    )

    # Assert — this checkout's command line ran to a verdict, collecting all along.
    assert child.probe["package"] == rwa_filer.__file__
    assert child.out.startswith("BLOCKED") and child.code == EXIT_FAILED
    assert child.probe["collector_on"] is True
    assert sum(child.probe["collections"]) > 0, _COUNTED_ANYWHERE
    assert child.probe["frozen"] == 0


@pytest.mark.parametrize("value", ["", "off", "ON", "1"])
def test_any_other_value_of_the_switch_keeps_the_policy(value: str, tmp_path: Path) -> None:
    # Act
    child = _child(
        ENTRY_CHILD, "validate", str(_csv(tmp_path, BROKEN_CSV)), *HEADER_ARGS, env={SWITCH: value}
    )

    # Assert — exactly "on" switches the policy off; anything else is today's policy.
    assert child.out.startswith("BLOCKED") and child.code == EXIT_FAILED
    assert child.probe["collector_on"] is False
    assert child.probe["collections"] == [0, 0, 0]
    assert child.probe["frozen"] > 100_000


# =============================================================================
# Helpers
# =============================================================================


def _sub_commands(parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()) -> Iterator[str]:
    """Every sub-command ``parser`` registers, nested ones as ``"group action"``."""
    for action in parser._actions:  # noqa: SLF001 - argparse has no public way to list them
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            for name, sub_parser in action.choices.items():
                yield " ".join((*prefix, name))
                yield from _sub_commands(sub_parser, (*prefix, name))


def _geographical_table(path: Path, countries: int) -> Path:
    """Every cell of OF 09.01 and OF 09.02 at zero for ``countries`` countries, as a fact table."""
    pack = resolve_release("PRA001", "4.1.1").pack
    frames = []
    for table in OPEN_TABLES:
        axis = pack.tables[table].open_axis
        assert axis is not None and len(axis.members) >= countries, table
        cells = pack.cells.filter(pl.col("table") == table).select("table", "row", "column")
        keys = pl.DataFrame({"open_key": axis.members[:countries]})
        frames.append(cells.join(keys, how="cross").with_columns(pl.lit(0.0).alias("value")))
    pl.concat(frames).write_parquet(path)
    return path
