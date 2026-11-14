"""
An input that is not the file a command reads ends in one line that names it.

Each command that opens a workbook or a taxonomy package can be given a file
that is not one: a text file named ``.xlsx``, a ``.csv``, a zip holding no
workbook, a taxonomy "package" that is neither a folder nor a zip, a package
with a linkbase that is not well-formed XML. Each must end the way any other
refusal ends: exit 1 and one ``rwa-filer: ...`` line on stderr that names the
file at fault, so that with three inputs (``taxonomy compile``) the user is told
which. Not a traceback whose last line says only ``File is not a zip file``.

Every other input on each command line is real, so each command fails on the
named file and on nothing else.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

import taxonomy_builders
from pack_builders import VALID_LEI
from rwa_filer.cli import EXIT_FAILED, main

#: A real PRA001 fact, so a fact table beside the bad file reads cleanly.
FACTS_CSV = "table,sheet,row,column,value\nOF07.00.01.01,0008,0010,0010,0\n"
HEADER_ARGS = ["--entity", VALID_LEI, "--reference-date", "2027-03-31", "--module", "PRA001"]

#: One BoE validation rule, in the columns ``boe.importer`` requires.
RULE_COLUMNS = {
    "Rule code": "boe_b0001",
    "Framework version code": "test_fw",
    "Expression": "{t: T1, r: 0010, c: 0010, dv: 0, seq: False, id: v0, f: banking, fv: test_fw} >= 0",
    "Include in XBRL": "yes",
    "Deactivated": "no",
    "Always execute": "no",
    "Severity and modules": "ERROR - TST001|",
}

#: The taxonomy compile command line; ``{annotated}`` etc. are keys of ``inputs``.
COMPILE = [
    "taxonomy",
    "compile",
    "--annotated",
    "{annotated}",
    "--dictionary",
    "{dictionary}",
    "--taxonomy",
    "{taxonomy}",
    "--module",
    taxonomy_builders.MODULE,
    "--valid-from",
    "2027-01-01",
    "--out",
    "{out}",
]

#: Path of the module's presentation linkbase and of one table's definition
#: linkbase inside the miniature package.
PRESENTATION = "www.example.test/fws/demo/2026-01-01/mod/demo01-pre.xml"
DEFINITION = "www.example.test/fws/demo/2026-01-01/tab/t01.00.01.01/t01.00.01.01-def.xml"

#: case -> (command line, the input it names that is at fault). ``{text}`` is a
#: text file named .xlsx; ``{csv}`` a .csv; ``{archive}`` a zip holding no workbook.
CASES: dict[str, tuple[list[str], str]] = {
    "validate": (["validate", "{text}"], "text"),
    "validate, workbook that is a zip of something else": (["validate", "{archive}"], "archive"),
    "build": (["build", "{text}", "--out", "{out}"], "text"),
    "diff, the second file": (["diff", "{facts}", "{text}", *HEADER_ARGS], "text"),
    "rules import boe": (
        ["rules", "import", "--publisher", "boe", "{text}", "--out", "{out}/x.json"],
        "text",
    ),
    "rules check boe": (["rules", "check", "--publisher", "boe", "{text}"], "text"),
    "rules import eba": (
        ["rules", "import", "--publisher", "eba", "{text}", "--out", "{out}/x.json"],
        "text",
    ),
    "rules check eba": (["rules", "check", "--publisher", "eba", "{text}"], "text"),
    "rules check, a .csv": (["rules", "check", "--publisher", "boe", "{csv}"], "csv"),
    "rules check, a zip of something else": (
        ["rules", "check", "--publisher", "boe", "{archive}"],
        "archive",
    ),
    "rulebook import": (["rulebook", "import", "{text}", "--out", "{out}"], "text"),
    "rulebook check": (["rulebook", "check", "{text}"], "text"),
    "rulebook check, a .csv": (["rulebook", "check", "{csv}"], "csv"),
    "rulebook check, the taxonomy package": (
        ["rulebook", "check", "{rules}", "--taxonomy-package", "{text_zip}"],
        "text_zip",
    ),
    "taxonomy compile, --annotated": (
        [arg.replace("{annotated}", "{text}") for arg in COMPILE],
        "text",
    ),
    "taxonomy compile, --annotated given the package zip": (
        [arg.replace("{annotated}", "{taxonomy_zip}") for arg in COMPILE],
        "taxonomy_zip",
    ),
    "taxonomy compile, --dictionary": (
        [arg.replace("{dictionary}", "{text}") for arg in COMPILE],
        "text",
    ),
    "taxonomy compile, --taxonomy": (
        [arg.replace("{taxonomy}", "{text_zip}") for arg in COMPILE],
        "text_zip",
    ),
    "taxonomy compile, a malformed presentation linkbase": (
        [arg.replace("{taxonomy}", "{malformed_presentation}") for arg in COMPILE],
        "presentation",
    ),
    "taxonomy compile, a malformed definition linkbase": (
        [arg.replace("{taxonomy}", "{malformed_definition}") for arg in COMPILE],
        "definition",
    ),
}


@pytest.fixture
def inputs(tmp_path: Path) -> dict[str, str]:
    """Every path the command lines name: the bad files and real ones beside them."""
    text = tmp_path / "not-a-workbook.xlsx"
    text.write_text("plain text, not a workbook\n")
    text_zip = tmp_path / "not-a-package.zip"
    text_zip.write_text("plain text, not a zip\n")
    csv = tmp_path / "rules.csv"
    csv.write_text("Rule code,Expression\nboe_b0001,{c: 0010} = {c: 0020}\n")
    archive = tmp_path / "zip-of-other-things.xlsx"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("readme.txt", "a zip, but no workbook in it")
    facts = tmp_path / "facts.csv"
    facts.write_text(FACTS_CSV)
    taxonomy = taxonomy_builders.build_taxonomy_package(tmp_path / "taxonomy")
    return {
        "text": str(text),
        "text_zip": str(text_zip),
        "csv": str(csv),
        "archive": str(archive),
        "facts": str(facts),
        "rules": str(_rule_workbook(tmp_path / "Validations Test v9.8.7.xlsx")),
        "annotated": str(taxonomy_builders.build_annotated_workbook(tmp_path / "annotated.xlsx")),
        "dictionary": str(taxonomy_builders.build_dictionary_workbook(tmp_path / "dpm.xlsx")),
        "taxonomy": str(taxonomy),
        "taxonomy_zip": str(taxonomy_builders.zip_package(taxonomy, tmp_path / "taxonomy.zip")),
        "malformed_presentation": str(_malformed(tmp_path / "bad-pre", PRESENTATION)),
        "malformed_definition": str(_malformed(tmp_path / "bad-def", DEFINITION)),
        "presentation": PRESENTATION,
        "definition": DEFINITION,
        "out": str(tmp_path / "out"),
    }


@pytest.mark.parametrize("case", list(CASES))
def test_an_unreadable_input_fails_in_one_line_that_names_it(
    case: str, inputs: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    template, culprit = CASES[case]
    argv = [argument.format(**inputs) for argument in template]

    # Act
    code = main(argv)

    # Assert — the CLI's own failure path, naming the file at fault
    captured = capsys.readouterr()
    lines = captured.err.splitlines()
    assert code == EXIT_FAILED
    assert len(lines) == 1, captured.err
    assert lines[0].startswith("rwa-filer: ")
    assert inputs[culprit] in lines[0]
    assert "Traceback" not in captured.err
    assert not Path(inputs["out"]).exists()


def _rule_workbook(path: Path) -> Path:
    """A one-rule BoE validation workbook: a ``Note`` sheet and one data sheet."""
    book = Workbook()
    book.active.title = "Note"
    sheet = book.create_sheet("test_fw")
    sheet.append(list(RULE_COLUMNS))
    sheet.append(list(RULE_COLUMNS.values()))
    book.save(path)
    return path


def _malformed(root: Path, member: str) -> Path:
    """The miniature taxonomy package with ``member`` cut off mid-element."""
    taxonomy_builders.build_taxonomy_package(root)
    (root / member).write_text('<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"><')
    return root
