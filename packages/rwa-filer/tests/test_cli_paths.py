"""
A path that is not what a command needs ends in one line that names it.

Inputs

Each command that opens a workbook or a taxonomy package can be given a file
that is not one: a text file named ``.xlsx``, a ``.csv``, a zip holding no
workbook, a taxonomy "package" that is neither a folder nor a zip, a package
with a linkbase that is not well-formed XML. Each must end the way any other
refusal ends: exit 1 and one ``rwa-filer: ...`` line on stderr that names the
file at fault, so that with three inputs (``taxonomy compile``) the user is told
which. Not a traceback whose last line says only ``File is not a zip file``.

Outputs
Each option naming where a command writes can name an existing file where a
directory is written, a directory where a file is, or a path beneath a file.
Each is refused the same way, before any work is done, and the file in the way
is left as it was — not a ``FileExistsError`` once a compile has finished.

Every other path on each command line is real, so each command fails on the
named path and on nothing else.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

import taxonomy_builders
from pack_builders import VALID_LEI
from rwa_filer.cli import EXIT_FAILED, main
from rwa_filer.rules import importer

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

#: A blank workbook of one PRA001 table.
TEMPLATE = ["template", "--module", "PRA001", "--reference-date", "2027-03-31"]

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
        ["rulebook", "check", "{validations}", "--taxonomy-package", "{text_zip}"],
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


#: case -> (command line, the path it names that is in the way). ``{a_file}`` is
#: an existing file and ``{a_dir}`` an existing directory.
OUTPUT_CASES: dict[str, tuple[list[str], str]] = {
    "taxonomy compile, --out a file": (
        [arg.replace("{out}", "{a_file}") for arg in COMPILE],
        "a_file",
    ),
    "rulebook import, --out a file": (
        ["rulebook", "import", "{validations}", "--out", "{a_file}"],
        "a_file",
    ),
    "rules import, --out a directory": (
        ["rules", "import", "--publisher", "boe", "{boe_rules}", "--out", "{a_dir}"],
        "a_dir",
    ),
    "rules import, --out beneath a file": (
        ["rules", "import", "--publisher", "boe", "{boe_rules}", "--out", "{a_file}/x.json"],
        "a_file",
    ),
    "template, --out a directory": ([*TEMPLATE, "--out", "{a_dir}"], "a_dir"),
    "template, --out beneath a file": ([*TEMPLATE, "--out", "{a_file}/t.xlsx"], "a_file"),
    "build, --out a file": (["build", "{facts}", *HEADER_ARGS, "--out", "{a_file}"], "a_file"),
    "build, --ledger a directory": (
        ["build", "{facts}", *HEADER_ARGS, "--out", "{out}", "--author", "A. Filer"]
        + ["--ledger", "{a_dir}"],
        "a_dir",
    ),
    "validate, --report a directory": (
        ["validate", "{facts}", *HEADER_ARGS, "--report", "{a_dir}"],
        "a_dir",
    ),
    "validate, --report beneath a file": (
        ["validate", "{facts}", *HEADER_ARGS, "--report", "{a_file}/report.json"],
        "a_file",
    ),
}

#: What the file in the way holds, so a test can show it was left alone.
IN_THE_WAY = "an existing file\n"


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
    a_file = tmp_path / "existing-file"
    a_file.write_text(IN_THE_WAY)
    a_dir = tmp_path / "existing-dir"
    a_dir.mkdir()
    return {
        "text": str(text),
        "text_zip": str(text_zip),
        "csv": str(csv),
        "archive": str(archive),
        "facts": str(facts),
        "validations": str(_validation_workbook(tmp_path / "Validations Test v9.8.7.xlsx")),
        "boe_rules": str(_boe_rule_workbook(tmp_path / "boe-rules.xlsx")),
        "annotated": str(taxonomy_builders.build_annotated_workbook(tmp_path / "annotated.xlsx")),
        "dictionary": str(taxonomy_builders.build_dictionary_workbook(tmp_path / "dpm.xlsx")),
        "taxonomy": str(taxonomy),
        "taxonomy_zip": str(taxonomy_builders.zip_package(taxonomy, tmp_path / "taxonomy.zip")),
        "malformed_presentation": str(_malformed(tmp_path / "bad-pre", PRESENTATION)),
        "malformed_definition": str(_malformed(tmp_path / "bad-def", DEFINITION)),
        "presentation": PRESENTATION,
        "definition": DEFINITION,
        "out": str(tmp_path / "out"),
        "a_file": str(a_file),
        "a_dir": str(a_dir),
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


@pytest.mark.parametrize("case", list(OUTPUT_CASES))
def test_an_unwritable_output_path_fails_in_one_line_that_names_what_is_in_the_way(
    case: str, inputs: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    template, culprit = OUTPUT_CASES[case]
    argv = [argument.format(**inputs) for argument in template]

    # Act
    code = main(argv)

    # Assert — one line naming the path in the way, which is left as it was
    captured = capsys.readouterr()
    lines = captured.err.splitlines()
    assert code == EXIT_FAILED
    assert len(lines) == 1, captured.err
    assert lines[0].startswith("rwa-filer: ")
    assert inputs[culprit] in lines[0]
    assert "Traceback" not in captured.err
    assert Path(inputs["a_file"]).read_text() == IN_THE_WAY
    assert not any(Path(inputs["a_dir"]).iterdir())
    assert not Path(inputs["out"]).exists()


def _validation_workbook(path: Path) -> Path:
    """A one-rule BoE validation workbook (``rulebook``): a ``Note`` sheet and one data sheet."""
    book = Workbook()
    book.active.title = "Note"
    sheet = book.create_sheet("test_fw")
    sheet.append(list(RULE_COLUMNS))
    sheet.append(list(RULE_COLUMNS.values()))
    book.save(path)
    return path


def _boe_rule_workbook(path: Path) -> Path:
    """A one-rule BoE workbook (``rules --publisher boe``), on the publisher's column positions."""
    cells: list[object] = [None] * 21
    cells[importer.BOE_COL_OWNER] = "BoE"
    cells[importer.BOE_COL_RULE_CODE] = "boe_b0001"
    cells[importer.BOE_COL_SIMPLE_EXPRESSION] = "{c: 0010} = {c: 0020}"
    cells[importer.BOE_COL_SEVERITY] = "ERROR - PRA001|"
    cells[importer.BOE_COL_IN_XBRL] = "Yes"
    cells[importer.BOE_COL_TABLES[0]] = "OF07.00.01.01"
    book = Workbook()
    book.active.title = importer.BOE_SHEET
    book.active.append(["header"] * 21)
    book.active.append(cells)
    book.save(path)
    return path


def _malformed(root: Path, member: str) -> Path:
    """The miniature taxonomy package with ``member`` cut off mid-element."""
    taxonomy_builders.build_taxonomy_package(root)
    (root / member).write_text('<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"><')
    return root
