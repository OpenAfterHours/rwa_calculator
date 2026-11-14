"""
The ``rwa-filer taxonomy compile`` command: a pack written, or one line saying why not.

Pipeline position:
    shell -> cli.main -> taxonomy.compiler.compile_pack -> taxonomy.pack.write_pack

The publisher's DPM files are not redistributed, so the inputs are the miniature
module ``taxonomy_builders`` lays out — the same three files the compiler's own
tests (``tests/taxonomy/test_compiler.py``) compile.

Key responsibilities pinned here:
- A compile that succeeds writes the pack and says what it wrote.
- An input the compiler refuses — a module the workbook's Table of Contents does
  not list, a taxonomy package with no entry point for the module, a workbook given
  as the dictionary that is not one — ends the way any other refusal ends: one
  ``rwa-filer: ...`` line on stderr that says what was wrong, exit 1, no
  traceback, and no pack written.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

import taxonomy_builders as builders
from rwa_filer.cli import EXIT_FAILED, EXIT_OK, main


@dataclass(frozen=True)
class Inputs:
    """The command's arguments that are not ``--out``."""

    annotated: Path
    dictionary: Path
    taxonomy: Path
    module: str = builders.MODULE


@pytest.fixture(scope="module")
def publisher(tmp_path_factory: pytest.TempPathFactory) -> Inputs:
    """The three miniature publisher files, laid out the way the Bank lays out its own."""
    root = tmp_path_factory.mktemp("publisher")
    return Inputs(
        annotated=builders.build_annotated_workbook(root / "Annotated Templates v9.9.9 Demo.xlsx"),
        dictionary=builders.build_dictionary_workbook(root / "DPM dictionary v9.9.9.xlsx"),
        taxonomy=builders.build_taxonomy_package(root / "taxonomy"),
    )


@pytest.fixture(scope="module")
def package_without_the_module(publisher: Inputs, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The same taxonomy package with the module's entry-point schema taken out."""
    package = shutil.copytree(publisher.taxonomy, tmp_path_factory.mktemp("other") / "taxonomy")
    (entry_point,) = package.rglob(f"mod/{builders.MODULE.lower()}.xsd")
    entry_point.unlink()
    return package


def test_taxonomy_compile_writes_the_pack_and_says_what_it_wrote(
    publisher: Inputs, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    out = tmp_path / "pack"

    # Act
    code = main(_compile(publisher, out))

    # Assert
    captured = capsys.readouterr()
    assert code == EXIT_OK
    assert (out / "pack.json").is_file()
    assert captured.out.startswith(f"wrote {out} ({builders.MODULE} ")
    assert captured.err == ""


@pytest.mark.parametrize(
    ("case", "named"),
    [
        pytest.param("unknown module", "'NOPE99'", id="module-not-in-the-table-of-contents"),
        pytest.param("package without the module", "no entry point", id="module-not-in-package"),
        pytest.param("workbook as dictionary", "Domains", id="dictionary-is-not-a-dictionary"),
    ],
)
def test_an_input_the_compiler_refuses_fails_in_one_line_that_says_why(
    case: str,
    named: str,
    publisher: Inputs,
    package_without_the_module: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    inputs = {
        "unknown module": replace(publisher, module="NOPE99"),
        "package without the module": replace(publisher, taxonomy=package_without_the_module),
        "workbook as dictionary": replace(publisher, dictionary=publisher.annotated),
    }[case]
    out = tmp_path / "pack"

    # Act
    code = main(_compile(inputs, out))

    # Assert — the CLI's own failure path: one diagnostic line, nothing else
    captured = capsys.readouterr()
    assert code == EXIT_FAILED
    assert captured.err.startswith("rwa-filer: ")
    assert captured.err.count("\n") == 1
    assert named in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    assert not out.exists()


def _compile(inputs: Inputs, out: Path) -> list[str]:
    """The ``taxonomy compile`` command line for ``inputs``, writing to ``out``."""
    return [
        "taxonomy",
        "compile",
        "--annotated",
        str(inputs.annotated),
        "--dictionary",
        str(inputs.dictionary),
        "--taxonomy",
        str(inputs.taxonomy),
        "--module",
        inputs.module,
        "--valid-from",
        "2027-01-01",
        "--out",
        str(out),
    ]
