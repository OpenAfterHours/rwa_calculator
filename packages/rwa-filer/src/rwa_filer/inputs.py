"""
Input files — open a workbook or a zip archive, or say in one line which file is not one.

Pipeline position:
    readers.excel / rules.importer / boe.importer / taxonomy._workbook  ->  load_workbook
    taxonomy._linkbase / boe.formulas / referee.plan                     ->  open_zip
        ->  the open file, or a ValueError that names it
        ->  cli handler  ->  one ``rwa-filer: ...`` line on stderr, exit 1

Key responsibilities:
- Open every workbook the package reads, through ``extras.import_openpyxl``, so
  that a missing extra and a file that is not a workbook are each refused in
  one place for every command, including one added later.
- Turn each way openpyxl and ``zipfile`` say "this is not that kind of file"
  into a ``ValueError`` that names the file. Every command reports a
  ``ValueError`` as one line, and with several inputs (``taxonomy compile``
  takes three) the name is what says which one is wrong. The exception it
  replaces is chained, for a caller that wants it.
- Translate only those. Anything else raised while opening a file is a defect,
  and its traceback is the report.

References:
- ECMA-376 Part 2, Open Packaging Conventions: an .xlsx is a zip whose
  ``[Content_Types].xml`` lists its parts. A zip without one is not a workbook,
  which openpyxl reports as a ``KeyError`` from ``zipfile``.
"""

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING, Any
from xml.etree.ElementTree import ParseError

from rwa_filer.extras import import_openpyxl

if TYPE_CHECKING:
    from pathlib import Path


def load_workbook(path: Path, *, needed_for: str, command: str, read_only: bool = True) -> Any:
    """Open the workbook at ``path``, values only (a formula cell gives its cached result).

    Args:
        path: The ``.xlsx`` file.
        needed_for: What is reading it, for the message when the ``excel`` extra
            is missing; as for ``extras.import_openpyxl``.
        command: The ``rwa-filer`` command to show in that message.
        read_only: openpyxl's streaming mode. ``False`` also loads cell styles,
            comments and merged ranges.

    Returns:
        The openpyxl workbook. The caller closes it.

    Raises:
        MissingExtraError: openpyxl is not installed.
        ValueError: ``path`` is not a readable .xlsx workbook — not a zip at all,
            a file type openpyxl does not open (a .csv, an .xls), a zip that holds
            no workbook, or a workbook part that is not well-formed XML.
    """
    openpyxl = import_openpyxl(needed_for=needed_for, command=command)
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        return openpyxl.load_workbook(path, read_only=read_only, data_only=True)
    except (zipfile.BadZipFile, InvalidFileException, KeyError, ParseError) as exc:
        raise ValueError(f"{path} is not a readable .xlsx workbook") from exc


def open_zip(path: Path) -> zipfile.ZipFile:
    """Open the zip archive at ``path`` for reading.

    Returns:
        The open archive, usable as a context manager. The caller closes it.

    Raises:
        ValueError: ``path`` is not a zip archive.
    """
    try:
        return zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{path} is not a zip archive") from exc
