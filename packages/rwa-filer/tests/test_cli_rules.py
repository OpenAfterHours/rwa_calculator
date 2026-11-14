"""The ``rwa-filer rules`` commands: list, import and check."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from rwa_filer.cli import EXIT_FAILED, EXIT_OK, main
from rwa_filer.rules import importer
from rwa_filer.rules.catalogue import EXTRACT_FILES


@pytest.fixture
def boe_workbook(tmp_path: Path) -> Path:
    """A one-rule BoE workbook on the publisher's column positions."""
    row: list[object] = [None] * 21
    row[importer.BOE_COL_OWNER] = "BoE"
    row[importer.BOE_COL_RULE_CODE] = "boe_b0001"
    row[importer.BOE_COL_SIMPLE_EXPRESSION] = "{c: 0010} = {c: 0020}"
    row[importer.BOE_COL_SEVERITY] = "ERROR - PRA001|"
    row[importer.BOE_COL_IN_XBRL] = "Yes"
    row[importer.BOE_COL_TABLES[0]] = "OF07.00.01.01"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = importer.BOE_SHEET
    worksheet.append(["header"] * 21)
    worksheet.append(row)
    path = tmp_path / "boe.xlsx"
    workbook.save(path)
    return path


def test_rules_list_names_every_packaged_extract(capsys: pytest.CaptureFixture[str]) -> None:
    # Act
    code = main(["rules", "list"])

    # Assert
    out = capsys.readouterr().out
    assert code == EXIT_OK
    for filename in EXTRACT_FILES.values():
        assert filename in out
    assert "EBA" in out and "BoE" in out


def test_rules_with_no_action_prints_its_help(capsys: pytest.CaptureFixture[str]) -> None:
    # Act
    code = main(["rules"])

    # Assert
    assert code == EXIT_OK
    assert "usage: rwa-filer rules" in capsys.readouterr().out


def test_rules_import_writes_the_extract(
    boe_workbook: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    out_file = tmp_path / "nested" / "extract.json"

    # Act
    code = main(
        ["rules", "import", "--publisher", "boe", str(boe_workbook), "--out", str(out_file)]
    )

    # Assert
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert code == EXIT_OK
    assert [rule["id"] for rule in payload["rules"]] == ["boe_b0001"]
    assert "1 rules, 1 live" in capsys.readouterr().out


def test_rules_check_passes_on_a_fresh_extract_and_fails_on_an_edited_one(
    boe_workbook: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    extract = tmp_path / "extract.json"
    main(["rules", "import", "--publisher", "boe", str(boe_workbook), "--out", str(extract)])
    check = ["rules", "check", "--publisher", "boe", str(boe_workbook), "--against", str(extract)]

    # Act
    fresh = main(check)
    extract.write_text(extract.read_text(encoding="utf-8").replace("boe_b0001", "boe_b9999"))
    edited = main(check)

    # Assert
    captured = capsys.readouterr()
    assert fresh == EXIT_OK
    assert edited == EXIT_FAILED
    assert "out of date" in captured.err


def test_rules_check_defaults_to_the_packaged_extract(
    boe_workbook: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A one-rule workbook is not the packaged 820-rule extract, and says so."""
    # Act
    code = main(["rules", "check", "--publisher", "boe", str(boe_workbook)])

    # Assert
    assert code == EXIT_FAILED
    assert "packaged extract" in capsys.readouterr().err


def test_a_missing_workbook_is_a_failure_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    code = main(
        ["rules", "import", "--publisher", "eba", str(tmp_path / "absent.xlsx"), "--out", "x.json"]
    )

    # Assert
    assert code == EXIT_FAILED
    assert "workbook not found" in capsys.readouterr().err


@pytest.mark.parametrize("action", ["import", "check"])
@pytest.mark.parametrize(
    ("publisher", "layout", "named"),
    [
        pytest.param("eba", "boe", "no sheet 'v3.0(3.0.1)'", id="another-publishers-workbook"),
        pytest.param("boe", "empty", "is empty", id="empty-rule-sheet"),
        pytest.param("boe", "narrow", "has 2 columns", id="narrower-than-the-layout"),
    ],
)
def test_a_workbook_not_laid_out_for_the_publisher_fails_in_one_line_that_says_why(
    action: str,
    publisher: str,
    layout: str,
    named: str,
    boe_workbook: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    workbook = boe_workbook if layout == "boe" else _rule_sheet(tmp_path / f"{layout}.xlsx", layout)
    extract = tmp_path / "extract.json"
    argv = ["rules", action, "--publisher", publisher, str(workbook)]
    if action == "import":
        argv += ["--out", str(extract)]

    # Act
    code = main(argv)

    # Assert — the CLI's own failure path: one diagnostic line, nothing else
    captured = capsys.readouterr()
    assert code == EXIT_FAILED
    assert captured.err.startswith(f"rwa-filer: {workbook.name} ")
    assert captured.err.count("\n") == 1
    assert named in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    assert not extract.exists()


# ---------------------------------------------------------------------------
# rulebook — the Bank of England rule books
# ---------------------------------------------------------------------------


def test_rulebook_list_shows_every_module_and_what_it_enforces(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Act
    code = main(["rulebook", "list"])

    # Assert
    lines = capsys.readouterr().out.splitlines()
    assert code == EXIT_OK
    assert any(
        line.split() == ["banking_reporting", "4.1.1", "1486", "PRA001", "1441"] for line in lines
    )
    assert any(line.split() == ["leverage_ratio", "4.1.1", "61", "LVR001", "61"] for line in lines)


def test_rulebook_import_and_check_report_a_missing_workbook_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    imported = main(["rulebook", "import", str(tmp_path / "absent.xlsx"), "--out", str(tmp_path)])
    checked = main(["rulebook", "check", str(tmp_path / "absent.xlsx")])

    # Assert
    assert (imported, checked) == (EXIT_FAILED, EXIT_FAILED)
    assert capsys.readouterr().err.count("workbook not found") == 2


def test_rulebook_import_and_check_refuse_a_workbook_with_no_header_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange — one data sheet, and nothing on it
    blank = tmp_path / "blank.xlsx"
    Workbook().save(blank)
    out = tmp_path / "out"

    # Act
    imported = main(["rulebook", "import", str(blank), "--out", str(out)])
    checked = main(["rulebook", "check", str(blank)])

    # Assert — the missing header is a missing column, reported as one
    err = capsys.readouterr().err
    assert (imported, checked) == (EXIT_FAILED, EXIT_FAILED)
    assert err.count("rwa-filer: blank.xlsx: no column(s) ") == 2
    assert err.count("\n") == 2
    assert "Traceback" not in err
    assert not out.exists()


def _rule_sheet(path: Path, layout: str) -> Path:
    """A workbook holding the BoE rule sheet, either ``"empty"`` or two columns wide."""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = importer.BOE_SHEET
    if layout == "narrow":
        worksheet.append(["header", "header"])
        worksheet.append(["BoE", "boe_b0001"])
    workbook.save(path)
    return path
