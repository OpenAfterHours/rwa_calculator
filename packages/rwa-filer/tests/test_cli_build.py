"""The ``rwa-filer build`` command and XBRL input to ``validate``, on the packaged pack."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pack_builders import VALID_LEI
from rwa_filer.cli import EXIT_FAILED, EXIT_OK, main

HEADER_ARGS = ["--entity", VALID_LEI, "--reference-date", "2027-03-31", "--module", "PRA001"]
BASE = f"{VALID_LEI}_PRA001_2027-03-31"

#: Two facts in real PRA001 cells: OF 07.00 corporates, original exposure and
#: value adjustments. Structurally sound, and the rules that can run on them pass.
GOOD_CSV = (
    "table,sheet,row,column,value\n"
    "OF07.00.01.01,0008,0010,0010,1000000\n"
    "OF07.00.01.01,0008,0010,0030,-5000\n"
)

#: The same, plus one cell of OF 02.00 on its own. Still structurally sound, but
#: no published rule can run on a single cell of that template, so the return is
#: not shown to be clean (VAL003) and the rule gate stops it.
UNCOVERED_CSV = GOOD_CSV + "OF02.00.01.01,,0010,0010,1234567.89\n"


def _csv(tmp_path: Path, text: str = UNCOVERED_CSV) -> Path:
    path = tmp_path / "facts.csv"
    path.write_text(text)
    return path


def test_build_writes_nothing_while_the_rule_checks_do_not_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    code = main(["build", str(_csv(tmp_path)), "--out", str(tmp_path / "out"), *HEADER_ARGS])

    # Assert
    out = capsys.readouterr().out
    assert code == EXIT_FAILED
    assert "NOT WRITTEN" in out and "--force" in out
    assert not (tmp_path / "out").exists()


def test_build_with_force_writes_the_package_and_still_reports_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act
    code = main(
        [
            "build",
            str(_csv(tmp_path)),
            "--out",
            str(tmp_path / "out"),
            *HEADER_ARGS,
            "--force",
            "--zip",
            "--no-timestamp",
            "--monetary-decimals",
            "2",
        ]
    )

    # Assert — written, but the exit code still says "not submittable".
    out = capsys.readouterr().out
    assert code == EXIT_FAILED
    assert f"{BASE}.xbrl: 3 fact(s) from 3 cell(s), 2 template(s) reported" in out
    assert "this is the file to upload" in out
    assert sorted(path.name for path in (tmp_path / "out").iterdir()) == [
        f"{BASE}.manifest.json",
        f"{BASE}.xbrl",
        f"{BASE}.zip",
    ]
    text = (tmp_path / "out" / f"{BASE}.xbrl").read_text()
    assert 'decimals="2" unitRef="uGBP">1000000<' in text and "creationdate" not in text
    manifest = json.loads((tmp_path / "out" / f"{BASE}.manifest.json").read_text())
    assert manifest["validation"]["submittable"] is False
    assert manifest["instance"]["monetary_decimals"] == 2


def test_build_writes_a_return_that_passes_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Act — no --force: nothing blocks this one.
    code = main(
        ["build", str(_csv(tmp_path, GOOD_CSV)), "--out", str(tmp_path / "out"), *HEADER_ARGS]
    )

    # Assert — and the creation time is stamped unless asked otherwise.
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert out.startswith("SUBMITTABLE") and "NOT WRITTEN" not in out
    assert "creationdate=" in (tmp_path / "out" / f"{BASE}.xbrl").read_text()


def test_build_refuses_a_structure_error_even_when_forced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange — sheet 0014 does not exist on OF 07.00.
    path = _csv(tmp_path, "table,sheet,row,column,value\nOF07.00.01.01,0014,0010,0010,1\n")

    # Act
    code = main(["build", str(path), "--out", str(tmp_path / "out"), *HEADER_ARGS, "--force"])

    # Assert
    out = capsys.readouterr().out
    assert code == EXIT_FAILED
    assert "STR003" in out and "cannot be expressed in the taxonomy" in out
    assert not (tmp_path / "out").exists()


def test_a_written_instance_validates_like_the_table_it_came_from(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``validate`` reads the .xbrl — and the .zip — with no header options at all."""
    # Arrange
    main(
        ["build", str(_csv(tmp_path)), "--out", str(tmp_path / "out"), *HEADER_ARGS]
        + ["--force", "--zip"]
    )
    capsys.readouterr()

    # Act
    main(["validate", str(tmp_path / "out" / f"{BASE}.xbrl"), "--format", "json"])
    from_instance = json.loads(capsys.readouterr().out)
    main(["validate", str(tmp_path / "out" / f"{BASE}.zip"), "--format", "json"])
    from_zip = json.loads(capsys.readouterr().out)
    main(["validate", str(_csv(tmp_path)), *HEADER_ARGS, "--format", "json"])
    from_table = json.loads(capsys.readouterr().out)

    # Assert
    assert from_instance == from_zip
    for key in ("header", "taxonomy", "submittable", "facts", "tables", "summary", "findings"):
        assert from_instance[key] == from_table[key], key


def test_a_file_that_is_not_an_instance_is_a_clean_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    path = tmp_path / "broken.xbrl"
    path.write_text("<not-xbrl/>")

    # Act
    code = main(["validate", str(path)])

    # Assert
    assert code == EXIT_FAILED
    assert "not an XBRL instance" in capsys.readouterr().err
