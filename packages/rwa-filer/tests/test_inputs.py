"""
``rwa_filer.inputs``: a file that is not a workbook, or not a zip, is refused by name.

These are the exceptions openpyxl and ``zipfile`` raise for each kind of file
that is not what it should be; ``test_cli_paths.py`` drives the
same files through every command that opens one.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from rwa_filer.inputs import load_workbook, open_zip

#: The arguments ``extras.import_openpyxl`` is given, for its missing-extra message.
EXTRA = {"needed_for": "Reading a test workbook", "command": "test"}


def test_a_workbook_is_opened_with_its_cell_values(tmp_path: Path) -> None:
    # Arrange
    book = Workbook()
    book.active.append(["code", 10])
    path = tmp_path / "real.xlsx"
    book.save(path)

    # Act
    opened = load_workbook(path, **EXTRA)

    # Assert
    try:
        assert next(opened.active.iter_rows(values_only=True)) == ("code", 10)
    finally:
        opened.close()


@pytest.mark.parametrize("read_only", [True, False])
@pytest.mark.parametrize(
    "kind", ["text file", "empty file", "csv", "old xls", "zip of other things", "damaged part"]
)
def test_a_file_that_is_not_a_workbook_is_a_value_error_naming_it(
    kind: str, read_only: bool, tmp_path: Path
) -> None:
    # Arrange
    path = _not_a_workbook(kind, tmp_path)

    # Act / Assert
    with pytest.raises(ValueError, match="is not a readable .xlsx workbook") as raised:
        load_workbook(path, read_only=read_only, **EXTRA)
    assert str(path) in str(raised.value)


def test_a_zip_archive_is_opened(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "real.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("member.xml", "<a/>")

    # Act
    with open_zip(path) as archive:
        names = archive.namelist()

    # Assert
    assert names == ["member.xml"]


def test_a_file_that_is_not_a_zip_is_a_value_error_naming_it(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "package.zip"
    path.write_text("plain text, not a zip\n")

    # Act / Assert
    with pytest.raises(ValueError, match=r"package\.zip is not a zip archive"):
        open_zip(path)


def _not_a_workbook(kind: str, tmp_path: Path) -> Path:
    """A file of ``kind``; each is refused by openpyxl with a different exception."""
    if kind == "text file":
        path = tmp_path / "text.xlsx"
        path.write_text("plain text\n")
    elif kind == "empty file":
        path = tmp_path / "empty.xlsx"
        path.write_bytes(b"")
    elif kind == "csv":
        path = tmp_path / "table.csv"
        path.write_text("a,b\n1,2\n")
    elif kind == "old xls":
        path = tmp_path / "legacy.xls"
        path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(504))
    elif kind == "zip of other things":
        path = tmp_path / "archive.xlsx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("readme.txt", "no workbook here")
    else:
        good = tmp_path / "good.xlsx"
        Workbook().save(good)
        path = tmp_path / "damaged.xlsx"
        with zipfile.ZipFile(good) as source, zipfile.ZipFile(path, "w") as target:
            for member in source.infolist():
                damaged = member.filename == "xl/workbook.xml"
                target.writestr(member, b"<workbook" if damaged else source.read(member))
    return path
