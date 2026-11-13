"""
Readers — turn a file into a canonical return.

Pipeline position:
    file (.parquet / .csv / .xlsx)  ->  read_return  ->  CanonicalReturn
        ->  validate.validate_return

Key responsibilities:
- Read each supported file format into the one canonical shape
  (``rwa_filer.model``). A reader's whole job is coordinates and types; it makes
  no judgment about the figures.
- Never lose a fact silently. A cell a reader cannot make sense of is kept, as
  text, so the structure check reports it — a reader that dropped it would turn
  a filer's typo into an unreported figure.

Module map:
- ``tabular`` — long-format fact tables: Parquet and CSV
- ``excel``   — the workbook layout (one worksheet per table and sheet), and
                the blank-template writer that produces it

References:
- rwa_filer.model — the canonical fact schema
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rwa_filer.readers.tabular import read_csv, read_parquet

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.model import CanonicalReturn, ReturnHeader

__all__ = ["SUPPORTED_SUFFIXES", "read_csv", "read_parquet", "read_return"]

#: File suffixes ``read_return`` understands.
SUPPORTED_SUFFIXES: tuple[str, ...] = (".parquet", ".csv", ".xlsx")


def read_return(path: Path, header: ReturnHeader | None = None) -> CanonicalReturn:
    """Read ``path`` into a canonical return, choosing the reader by suffix.

    Args:
        path: A ``.parquet`` or ``.csv`` long-format fact table, or a ``.xlsx``
            workbook in the template layout.
        header: Who is reporting and for which date. REQUIRED for Parquet and
            CSV, which carry facts only. A workbook carries its own header on
            its ``Return`` sheet; pass one to override it.

    Raises:
        ValueError: the suffix is not supported, or a tabular file was given
            without a header. (Usage errors — not conditions in the data.)
    """
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        from rwa_filer.readers.excel import read_workbook

        return read_workbook(path, header)
    if suffix not in (".parquet", ".csv"):
        supported = ", ".join(SUPPORTED_SUFFIXES)
        raise ValueError(f"Unsupported file type {suffix!r}; expected one of {supported}")
    if header is None:
        raise ValueError(
            f"{path.name} carries facts only: supply the return header "
            "(entity identifier, reference date, module)"
        )
    return read_parquet(path, header) if suffix == ".parquet" else read_csv(path, header)
