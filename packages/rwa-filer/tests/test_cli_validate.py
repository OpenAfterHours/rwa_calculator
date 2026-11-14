"""The ``rwa-filer validate`` / ``template`` / ``taxonomy`` commands, on the packaged pack."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pack_builders import VALID_LEI
from rwa_filer.cli import EXIT_FAILED, EXIT_OK, main

HEADER_ARGS = ["--entity", VALID_LEI, "--reference-date", "2027-03-31", "--module", "PRA001"]

#: Two facts in real PRA001 cells: OF 07.00 corporates, original exposure and
#: value adjustments. Structurally sound — and they break published rules: with
#: nothing else reported, the exposure net of adjustments (column 0040) is zero
#: to the regulator, and 995,000 is not zero.
GOOD_CSV = (
    "table,sheet,row,column,value\n"
    "OF07.00.01.01,0008,0010,0010,1000000\n"
    "OF07.00.01.01,0008,0010,0030,-5000\n"
)

#: One reported zero. Every rule that reads the cell runs, and holds.
CLEAN_CSV = "table,sheet,row,column,value\nOF07.00.01.01,0008,0010,0010,0\n"


def _csv(tmp_path: Path, text: str = GOOD_CSV) -> Path:
    path = tmp_path / "facts.csv"
    path.write_text(text)
    return path


def test_taxonomy_list_shows_the_packaged_pack(capsys: pytest.CaptureFixture[str]) -> None:
    # Act
    code = main(["taxonomy", "list"])

    # Assert
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "PRA001" in out and "4.1.1" in out and "2027-01-01" in out


def test_validate_reports_the_verdict_and_the_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    code = main(["validate", str(_csv(tmp_path)), *HEADER_ARGS])

    # Assert — structurally sound; the rules that read the two cells break.
    out = capsys.readouterr().out
    assert code == EXIT_FAILED
    assert out.startswith("BLOCKED: PRA001 for " + VALID_LEI)
    assert "taxonomy 4.1.1, 2 facts, 1 tables" in out
    assert "structure: 0 finding(s)" in out
    assert "of 1441 executed" in out and "[VAL001] ERROR" in out
    assert "not evaluated because: template_not_reported" in out


def test_validate_exits_zero_on_a_return_whose_rules_all_hold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    code = main(["validate", str(_csv(tmp_path, CLEAN_CSV)), *HEADER_ARGS])

    # Assert — rules ran (it is not clean for want of checking) and none failed.
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert out.startswith("SUBMITTABLE") and "0 failed" in out
    assert "rules: 0 of" not in out and "[VAL" not in out


def test_validate_fails_on_a_structure_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange — sheet 0014 does not exist on OF 07.00.
    path = _csv(tmp_path, "table,sheet,row,column,value\nOF07.00.01.01,0014,0010,0010,1\n")

    # Act
    code = main(["validate", str(path), *HEADER_ARGS])

    # Assert
    out = capsys.readouterr().out
    assert code == EXIT_FAILED
    assert out.startswith("BLOCKED") and "[STR003] ERROR" in out


def test_validate_json_output_is_a_parseable_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    main(["validate", str(_csv(tmp_path)), *HEADER_ARGS, "--format", "json"])

    # Assert
    record = json.loads(capsys.readouterr().out)
    assert record["taxonomy"]["version"] == "4.1.1"
    assert record["facts"] == 2 and record["tables"] == ["OF07.00.01.01"]
    assert record["summary"]["structure_findings"] == 0


def test_validate_writes_the_report_file_when_asked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    report = tmp_path / "out" / "report.json"

    # Act
    main(["validate", str(_csv(tmp_path)), *HEADER_ARGS, "--report", str(report)])

    # Assert
    capsys.readouterr()
    assert json.loads(report.read_text(encoding="utf-8"))["header"]["Module"] == "PRA001"


def test_a_fact_table_without_a_header_is_a_failure_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    code = main(["validate", str(_csv(tmp_path))])

    # Assert
    assert code == EXIT_FAILED
    assert "--entity, --reference-date and --module" in capsys.readouterr().err


def test_a_reference_date_with_no_pack_is_a_failure_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    code = main(
        [
            "validate",
            str(_csv(tmp_path)),
            "--entity",
            VALID_LEI,
            "--reference-date",
            "2026-06-30",
            "--module",
            "PRA001",
        ]
    )

    # Assert
    assert code == EXIT_FAILED
    assert "No taxonomy pack" in capsys.readouterr().err


def test_a_missing_or_unsupported_file_is_a_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    unsupported = tmp_path / "facts.json"
    unsupported.write_text("{}")

    # Act
    missing = main(["validate", str(tmp_path / "absent.csv"), *HEADER_ARGS])
    wrong = main(["validate", str(unsupported), *HEADER_ARGS])

    # Assert
    err = capsys.readouterr().err
    assert (missing, wrong) == (EXIT_FAILED, EXIT_FAILED)
    assert "file not found" in err and "unsupported file type" in err


def test_template_then_validate_round_trips_through_a_workbook(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The workbook a user is given is one ``validate`` reads back."""
    # Arrange
    workbook = tmp_path / "template.xlsx"

    # Act
    wrote = main(
        [
            "template",
            "--module",
            "PRA001",
            "--reference-date",
            "2027-03-31",
            "--tables",
            "OF02.01.01.01",
            "--out",
            str(workbook),
        ]
    )
    validated = main(["validate", str(workbook), *HEADER_ARGS])

    # Assert — a blank template has no facts, which is reported, not passed.
    out = capsys.readouterr().out
    assert wrote == EXIT_OK and "1 worksheet(s), PRA001 4.1.1" in out
    assert validated == EXIT_FAILED and "[STR009]" in out


def test_template_refuses_a_table_the_module_does_not_have(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    code = main(
        [
            "template",
            "--module",
            "PRA001",
            "--reference-date",
            "2027-03-31",
            "--tables",
            "ZZ99",
            "--out",
            str(tmp_path / "x.xlsx"),
        ]
    )

    # Assert
    assert code == EXIT_FAILED
    assert "ZZ99" in capsys.readouterr().err
