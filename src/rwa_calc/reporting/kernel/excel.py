"""
Shared Excel sheet writer for the COREP and Pillar 3 generators.

Pipeline position:
    {COREPGenerator, Pillar3Generator}.export_to_excel -> write_template_sheet -> .xlsx

Key responsibilities:
- Write one template DataFrame to its own worksheet with a two-row header band:
  a human-readable column-name banner (row 0) sitting directly above the
  regulatory column-reference codes (row 1), with the data rows below.
- Build the ``{ref: readable name}`` banner map from a template's column
  definitions (``COREPColumn`` / ``P3Column`` — both expose ``.ref`` and ``.name``).
- Replace non-finite floats (NaN, +/-Inf) with null so xlsxwriter writes a blank
  cell instead of raising / emitting an Excel ``#NUM!`` error.
- Write a simple two-column label/value sheet (``write_metadata_sheet``) — used
  by the COREP / Pillar 3 generators for the filing-metadata sheet
  (``reporting/facts.py::FilingMetadata``).

Why: the template frames are keyed by regulatory column refs (e.g. ``"0010"``,
``"a"``) so downstream consumers and the ndjson goldens stay code-stable. This
writer surfaces the readable name (``COREPColumn.name`` / ``P3Column.name``) as a
banner *above* the code for human readers, without changing the DataFrame schema.

References:
- Regulation (EU) 2021/451, Annex I/II (COREP templates)
- CRR Part 8 (Pillar 3 disclosure templates)
- PRA PS1/26 (Basel 3.1 reporting amendments)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from xlsxwriter import Workbook

# Characters Excel forbids in worksheet names; sheet names also clamp to 31 chars.
_EXCEL_SHEET_INVALID_RE = re.compile(r"[\[\]:*?/\\]")

# Banner labels for the two structural columns every template frame leads with.
# These are not regulatory column refs, so they are absent from the per-template
# name map and get their own fixed readable labels here.
_STRUCTURAL_BANNER: dict[str, str] = {
    "row_ref": "Row code",
    "row_name": "Row name",
}

# Height (points) of the banner row — generous enough for a wrapped 2-3 line
# column name at the default font.
_BANNER_ROW_HEIGHT = 60.0


class _RefNamed(Protocol):
    """Structural view of a template column: a regulatory ref and a readable name.

    Members are read-only properties so frozen dataclass columns
    (``COREPColumn`` / ``P3Column``) satisfy the protocol.
    """

    @property
    def ref(self) -> str: ...

    @property
    def name(self) -> str: ...


def column_name_map(columns: Iterable[_RefNamed]) -> dict[str, str]:
    """Build a ``{ref: readable name}`` map from a template's column definitions."""
    return {col.ref: col.name for col in columns}


def sanitise_sheet_name(name: str) -> str:
    """Strip Excel-illegal characters and clamp to the 31-char worksheet-name limit."""
    return _EXCEL_SHEET_INVALID_RE.sub("", name)[:31]


def write_template_sheet(
    workbook: Workbook,
    df: pl.DataFrame,
    sheet_name: str,
    name_by_ref: Mapping[str, str],
) -> int:
    """Write *df* to a new worksheet with a readable-name banner above the ref codes.

    Layout written into the sheet:
        row 0   readable column-name banner — "Row code"/"Row name" over the two
                structural columns, then ``name_by_ref[ref]`` over each value column
        row 1   the DataFrame header (regulatory refs: ``row_ref``, ``row_name``,
                ``0010``, ...) written by ``write_excel``
        row 2+  the data rows

    A column ref absent from *name_by_ref* falls back to the ref itself, so the
    banner is always fully populated even for a dynamically added column. Only
    Excel cells are written — the DataFrame schema is untouched — so the ndjson
    goldens (which key on refs) are unaffected.

    Returns the number of data rows written (``df.height``).
    """
    sheet = sanitise_sheet_name(sheet_name)
    worksheet = workbook.add_worksheet(sheet)

    banner_format = workbook.add_format(
        {"bold": True, "text_wrap": True, "valign": "top", "bottom": 1}
    )
    worksheet.set_row(0, _BANNER_ROW_HEIGHT)
    for col_idx, ref in enumerate(df.columns):
        label = _STRUCTURAL_BANNER.get(ref) or name_by_ref.get(ref, ref)
        worksheet.write(0, col_idx, label, banner_format)

    # Data table starts at row 1 (its own header row carries the refs), leaving
    # row 0 for the readable-name banner. Non-finite floats become null so
    # xlsxwriter can write them as blanks rather than #NUM! errors.
    _finite_only(df).write_excel(
        workbook=workbook,
        worksheet=worksheet,
        position=(1, 0),
        autofit=True,
    )

    # Freeze the banner + ref-code rows so both stay visible while scrolling the
    # (often wide) template. Applied after the table write so it is not reset.
    worksheet.freeze_panes(2, 0)
    return df.height


def write_metadata_sheet(
    workbook: Workbook,
    fields: Mapping[str, str],
    sheet_name: str = "metadata",
) -> None:
    """Write a two-column ``Field`` / ``Value`` sheet — e.g. filing metadata.

    Deliberately generic (a plain ordered label/value mapping) rather than
    typed on ``FilingMetadata`` directly, so this module does not have to
    import ``reporting/facts.py`` — the caller (a generator's
    ``export_to_excel``) builds the mapping via
    ``FilingMetadata.as_sheet_fields()`` and passes it in.

    Every cell is written with ``write_string`` — not the type-sniffing
    ``write`` — because a value (``entity_identifier`` is caller-supplied REST
    input, e.g. from ``/api/export/{fmt}?entity_identifier=...``) may start
    with ``=``, ``+``, ``-`` or ``@``, which xlsxwriter's default ``write``
    would otherwise emit as a live formula rather than a literal string. This
    workbook is a regulatory artefact handed to a filing tool, so a value must
    never turn into executable spreadsheet content.
    """
    worksheet = workbook.add_worksheet(sanitise_sheet_name(sheet_name))
    bold = workbook.add_format({"bold": True})
    worksheet.write_string(0, 0, "Field", bold)
    worksheet.write_string(0, 1, "Value", bold)
    for row_idx, (label, value) in enumerate(fields.items(), start=1):
        worksheet.write_string(row_idx, 0, label)
        worksheet.write_string(row_idx, 1, value)


def _finite_only(df: pl.DataFrame) -> pl.DataFrame:
    """Replace non-finite floats (NaN, +/-Inf) with null so the cell can be written.

    xlsxwriter's ``write_number`` rejects NaN/Inf unless the workbook is opened
    with ``nan_inf_to_errors`` (which would emit Excel error cells). A template
    value that is mathematically undefined — e.g. a ratio over a zero denominator
    in an empty class/geography segment — is better shown blank than as ``#NUM!``,
    so non-finite floats become null here. Existing nulls and non-float columns
    are untouched (only float columns can carry NaN/Inf).
    """
    float_cols = [name for name, dtype in df.schema.items() if dtype in (pl.Float32, pl.Float64)]
    if not float_cols:
        return df
    return df.with_columns(
        pl.when(pl.col(c).is_finite()).then(pl.col(c)).otherwise(None).alias(c) for c in float_cols
    )
