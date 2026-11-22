"""The ``rwa-filer validate`` / ``template`` / ``taxonomy`` commands, on the packaged pack."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pack_builders import VALID_LEI
from rwa_filer import release as release_module
from rwa_filer.cli import EXIT_FAILED, EXIT_OK, main
from rwa_filer.release import resolve_release

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


def test_taxonomy_list_shows_each_modules_status_in_each_release(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Act
    code = main(["taxonomy", "list", "--module", "pra001"])

    # Assert
    out = capsys.readouterr().out
    lines = [line.split() for line in out.splitlines() if line.startswith("PRA001")]
    assert code == EXIT_OK
    assert len(lines) == 1, "one line per shipped release that has PRA001"
    module, release, status, applies_from, applies_to, default, _entry = lines[0]
    assert (module, release, applies_from, applies_to, default) == (
        "PRA001",
        "4.1.1",
        "2027-01-01",
        "-",
        "yes",
    )
    assert status in ("live", "future")
    assert "release(s) shipped: 4.1.1" in out


def test_taxonomy_list_loads_no_taxonomy_pack(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A listing names each module's default release; it reads none of them."""
    # Arrange — count the packs a release resolution asks for.
    asked: list[str] = []
    load = release_module.load_packaged

    def counted(key: str) -> object:
        asked.append(key)
        return load(key)

    monkeypatch.setattr(release_module, "load_packaged", counted)

    # Act
    code = main(["taxonomy", "list"])

    # Assert — every shipped module is listed with its default, and no pack was loaded.
    lines = [line.split() for line in capsys.readouterr().out.splitlines()[1:] if line.strip()]
    defaults = [line for line in lines if len(line) == 7 and line[5] == "yes"]
    assert code == EXIT_OK
    assert len(defaults) >= 14, "the listing marks no default: nothing was resolved to count"
    assert asked == []


def test_taxonomy_list_marks_the_release_a_run_would_use(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The ``default`` column is ``resolve_release``'s answer, module by module."""
    # Act
    main(["taxonomy", "list"])

    # Assert
    lines = [line.split() for line in capsys.readouterr().out.splitlines()[1:] if line.strip()]
    marked = {line[0]: line[1] for line in lines if len(line) == 7 and line[5] == "yes"}
    assert len(marked) >= 14, "fewer modules than the shipped release has: the listing is short"
    assert marked == {module: resolve_release(module).version for module in marked}


def test_taxonomy_list_refuses_a_module_no_release_has(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["taxonomy", "list", "--module", "XYZ999"]) == EXIT_FAILED
    assert "XYZ999" in capsys.readouterr().err


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
    # OF 07.00 alone leaves out templates its rules read, which is a VAL004
    # warning and does not change the exit code.
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert out.startswith("SUBMITTABLE") and "0 failed" in out
    assert "rules: 0 of" not in out
    assert not {"[VAL001]", "[VAL002]", "[VAL003]"} & set(out.split())


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


def test_a_reference_date_the_release_does_not_cover_is_a_warning_not_a_stop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The release is chosen, not the date: a 2026 return is checked against 4.1.1."""
    # Act
    main(["validate", str(_csv(tmp_path)), *_header("2026-06-30"), "--format", "json"])

    # Assert
    captured = capsys.readouterr()
    record = json.loads(captured.out)
    warnings = [item for item in record["findings"] if item["code"] == "STR011"]
    assert captured.err == ""
    assert record["taxonomy"]["version"] == "4.1.1"
    assert record["taxonomy"]["covers_reference_date"] is False
    assert len(warnings) == 1 and warnings[0]["blocking"] is False


def test_the_text_report_says_which_release_was_used_after_the_verdict_and_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    main(["validate", str(_csv(tmp_path)), *_header("2027-03-31")])

    # Assert
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith(("SUBMITTABLE", "BLOCKED"))
    assert lines[1].startswith("  status: ")
    assert lines[2].startswith("Taxonomy 4.1.1 (default) — PRA001 ")


def test_a_named_release_is_used_and_said_to_be_chosen(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    main(["validate", str(_csv(tmp_path)), *_header("2027-03-31"), "--taxonomy", "4.1.1"])

    # Assert
    assert "Taxonomy 4.1.1 (--taxonomy)" in capsys.readouterr().out


def test_a_release_that_is_not_shipped_is_a_failure_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    code = main(["validate", str(_csv(tmp_path)), *_header("2027-03-31"), "--taxonomy", "9.9.9"])

    # Assert
    assert code == EXIT_FAILED
    assert "Taxonomy 9.9.9 is not shipped" in capsys.readouterr().err


def _header(reference_date: str) -> list[str]:
    return ["--entity", VALID_LEI, "--reference-date", reference_date, "--module", "PRA001"]


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


def test_template_needs_no_reference_date_and_says_which_release_it_is_for(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    code = main(
        [
            "template",
            "--module",
            "PRA001",
            "--tables",
            "OF02.01.01.01",
            "--out",
            str(tmp_path / "x.xlsx"),
        ]
    )

    # Assert
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert out.startswith("Taxonomy 4.1.1 (default) — PRA001 ")
    assert "warning" not in out


def test_template_warns_when_the_release_does_not_cover_the_reference_date(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    code = main(
        [
            "template",
            "--module",
            "PRA001",
            "--taxonomy",
            "4.1.1",
            "--reference-date",
            "2026-12-31",
            "--tables",
            "OF02.01.01.01",
            "--out",
            str(tmp_path / "x.xlsx"),
        ]
    )

    # Assert
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "warning: reference date 2026-12-31 is outside PRA001's dates in taxonomy 4.1.1" in out
