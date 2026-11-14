"""
Without the ``rwa-filer[excel]`` extra, every command that needs it says so in one line.

Reading or writing an .xlsx needs openpyxl, which only the ``excel`` extra
installs. A command that reaches a workbook without it must end the way any
other refusal ends — one ``rwa-filer: ...`` line on stderr and exit 1 — not in a
traceback whose last line is the only part worth reading.

The extra is made unimportable with ``sys.modules["openpyxl"] = None``, which is
what an environment without it looks like to ``import``. Every input file is a
real workbook, written before openpyxl is blocked, so each command fails on the
missing extra and on nothing else.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

from rwa_filer import cli
from rwa_filer.cli import EXIT_FAILED, main

#: The two remedies the message must give, spelt so they can be copied.
RUN_WITH_THE_EXTRA = 'uvx "rwa-filer[excel]@latest"'
ADD_THE_EXTRA = 'uv add "rwa-filer[excel]"'

#: The reported command line: a blank workbook of one PRA001 table.
TEMPLATE_ARGS = [
    "template",
    "--module",
    "PRA001",
    "--reference-date",
    "2027-03-31",
    "--tables",
    "OF02.00.01.01",
]

#: Every command line that reaches a workbook; ``{name}`` is a path from ``files``.
COMMANDS: dict[str, list[str]] = {
    "validate": ["validate", "{return}"],
    "build": ["build", "{return}", "--out", "{out}"],
    "diff": ["diff", "{return}", "{return}"],
    "template": [*TEMPLATE_ARGS, "--out", "{out}/template.xlsx"],
    "taxonomy compile": [
        "taxonomy",
        "compile",
        "--annotated",
        "{workbook}",
        "--dictionary",
        "{dictionary}",
        "--taxonomy",
        "{taxonomy}",
        "--module",
        "PRA001",
        "--valid-from",
        "2027-01-01",
        "--out",
        "{out}",
    ],
    "rulebook import": ["rulebook", "import", "{workbook}", "--out", "{out}"],
    "rulebook check": ["rulebook", "check", "{workbook}"],
    "rules import": ["rules", "import", "--publisher", "boe", "{workbook}", "--out", "{out}/x"],
    "rules check": ["rules", "check", "--publisher", "boe", "{workbook}"],
}


@pytest.fixture
def files(tmp_path: Path) -> dict[str, str]:
    """The paths the command lines name, written while openpyxl can still be imported."""
    taxonomy = tmp_path / "taxonomy"
    taxonomy.mkdir()
    return {
        "return": _blank_workbook(tmp_path / "return.xlsx"),
        "workbook": _blank_workbook(tmp_path / "workbook.xlsx"),
        "dictionary": _blank_workbook(tmp_path / "dictionary.xlsx"),
        "taxonomy": str(taxonomy),
        "out": str(tmp_path / "out"),
    }


@pytest.mark.parametrize("command", list(COMMANDS))
def test_a_command_without_the_excel_extra_fails_in_one_line_that_says_how_to_run_it(
    command: str,
    files: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange — openpyxl unimportable, as in an environment without the extra
    argv = [argument.format(**files) for argument in COMMANDS[command]]
    monkeypatch.setitem(sys.modules, "openpyxl", None)

    # Act
    code = main(argv)

    # Assert — the CLI's own failure path: one diagnostic line, nothing else
    captured = capsys.readouterr()
    assert code == EXIT_FAILED
    assert captured.err.startswith("rwa-filer: ")
    assert captured.err.count("\n") == 1
    assert RUN_WITH_THE_EXTRA in captured.err
    assert ADD_THE_EXTRA in captured.err
    assert "Traceback" not in captured.err
    assert not Path(files["out"]).exists()


def test_the_reported_command_run_as_a_process_ends_without_a_traceback(tmp_path: Path) -> None:
    # Arrange — the reported command line, in an interpreter that cannot import openpyxl
    out = tmp_path / "x.xlsx"
    without_openpyxl = (
        "import sys; sys.modules['openpyxl'] = None; "
        "from rwa_filer.cli import main; sys.exit(main(sys.argv[1:]))"
    )

    # Act
    finished = subprocess.run(
        [sys.executable, "-c", without_openpyxl, *TEMPLATE_ARGS, "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )

    # Assert
    assert finished.returncode == EXIT_FAILED
    assert "Traceback" not in finished.stderr
    assert finished.stderr.count("\n") == 1
    assert RUN_WITH_THE_EXTRA in finished.stderr
    assert not out.exists()


def test_an_import_error_that_is_not_a_missing_extra_is_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — a module of the package itself failing to import is a defect, and
    # its traceback is the report; only a missing extra is the user's to fix.
    def broken(_args: object) -> int:
        raise ModuleNotFoundError("No module named 'rwa_filer.nowhere'", name="rwa_filer.nowhere")

    monkeypatch.setattr(cli, "_taxonomy_list", broken)

    # Act / Assert
    with pytest.raises(ModuleNotFoundError, match="rwa_filer.nowhere"):
        main(["taxonomy", "list"])


def _blank_workbook(path: Path) -> str:
    """A real, empty .xlsx; no command reads past the missing extra to its content."""
    Workbook().save(path)
    return str(path)
