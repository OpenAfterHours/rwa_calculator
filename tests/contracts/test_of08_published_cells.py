"""
The Basel 3.1 OF 08.01 cell grid against the cells the Bank of England publishes.

Why this file exists: the OF 08.01 generator computes every column on every
active row and reported all of it, but the PRA001 taxonomy holds no data point
for 279 of the template's row-by-column positions on any sheet, plus seven
positions that depend on the sheet. Nothing compared the layout's cells with the
published grid — ``test_of08_published_sheets.py`` holds the sheet AXIS and the
column axis, never the cells — so 60 distinct non-zero figures sat in cells no
return can carry, banked by the filing-mapping ratchet as the state.

The source of truth is the PRA001 taxonomy pack, compiled from the Bank's own
data point model (tables ``OF08.01.01.01`` and ``OF08.01.01.02``, which partition
one template's columns): a (row, column) the pack holds on no sheet is a cell
the template greys out, and one it holds on some sheets only is greyed on the
others. The declaration in ``corep/of08_published_cells.py`` must equal it
exactly, sheet by sheet and in both directions — a cell blanked that the sheet
has loses a figure, and one left that it lacks cannot be filed.

The seven sheet-dependent positions are pinned by name, because each is the
Bank's own anomaly or its correction, and a taxonomy release that changes any of
them must be read before the declaration is re-held to it:

- r0080 c0251 / c0252 on sheets 0002 and 0010, r0170 c0251 on 0001 and 0002 —
  known-issues log item 17, "Amended in release 4.1.1".
- r0017 and r0020 c0035 absent on sheet 0019 only — known-issues log item 25
  (19.10.2026): "erroneously greyed out in sheet 0019 ... the PRA requests that
  firms report this data in the total AIRB sheet s0001 but do not report it
  separately until the next taxonomy update".
- r0017 c0310 on sheet 0010 only and r0180 c0030 on sheet 0016 only — present
  in the linkbase, greyed in the annotated template; not in the log.

References:
- PRA PS1/26 Annex I (OF 08.01 template) and Annex II §3.3.2-§3.3.3
- Bank of England Banking Taxonomy v4.1.1, module PRA001; known-issues log
  (November 2026), items 17 and 25
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.irb_sheets import B31_SHEET_KEYS
from rwa_calc.reporting.corep.of08_published_cells import get_c08_01_unreported_cells
from rwa_calc.reporting.corep.templates import get_c08_columns, get_irb_row_sections
from rwa_calc.reporting.filing.canonical import FILING_MODULE, FILING_TAXONOMY
from rwa_filer.release import resolve_release

FRAMEWORK = "BASEL_3_1"
TABLE_PREFIX = "OF08.01.01."

#: Published rows our layout does not generate, each with its owning plan item.
#: Row 0001 is the 40% conversion-factor bucket (P2.1).
ROWS_NOT_IN_LAYOUT = {"0001"}

#: The positions published on some sheets and not others: (row, column) -> the
#: sheet codes that HAVE the cell (module docstring).
SHEET_DEPENDENT = {
    ("0017", "0035"): set(B31_SHEET_KEYS) - {"0019"},
    ("0020", "0035"): set(B31_SHEET_KEYS) - {"0019"},
    ("0017", "0310"): {"0010"},
    ("0080", "0251"): {"0002", "0010"},
    ("0080", "0252"): {"0002", "0010"},
    ("0170", "0251"): {"0001", "0002"},
    ("0180", "0030"): {"0016"},
}

#: A sheet key no published code names (an A-IRB institution, Art. 147A).
OFF_AXIS_KEY = "institution_airb"


@pytest.fixture(scope="module")
def published() -> dict[str, set[tuple[str, str]]]:
    """Published sheet code -> every (row, column) OF 08.01 has a data point for."""
    cells = resolve_release(FILING_MODULE, FILING_TAXONOMY).pack.cells.filter(
        pl.col("table").str.starts_with(TABLE_PREFIX)
    )
    by_sheet: dict[str, set[tuple[str, str]]] = {}
    for row, column, sheet in cells.select("row", "column", "sheet").iter_rows():
        by_sheet.setdefault(sheet, set()).add((row, column))
    return by_sheet


def _grid(published: dict[str, set[tuple[str, str]]]) -> set[tuple[str, str]]:
    """Every published row crossed with every published column."""
    cells = set().union(*published.values())
    rows = {row for row, _ in cells}
    columns = {column for _, column in cells}
    return {(row, column) for row in rows for column in columns}


def _declared(sheet_key: str) -> set[tuple[str, str]]:
    return {
        (row, column)
        for row, columns in get_c08_01_unreported_cells(FRAMEWORK, sheet_key).items()
        for column in columns
    }


def _layout_rows() -> set[str]:
    return {row.ref for section in get_irb_row_sections(FRAMEWORK) for row in section.rows}


def _layout_columns() -> set[str]:
    return {column.ref for column in get_c08_columns(FRAMEWORK)}


@pytest.mark.parametrize("code", sorted(B31_SHEET_KEYS))
def test_the_declared_blank_cells_are_exactly_the_cells_the_sheet_lacks(
    published: dict[str, set[tuple[str, str]]], code: str
) -> None:
    # Arrange
    declared = _declared(B31_SHEET_KEYS[code])

    # Act
    lacking = {cell for cell in _grid(published) if cell not in published[code]}

    # Assert
    assert sorted(lacking - declared) == [], f"sheet {code}: cells it lacks that are still reported"
    assert sorted(declared - lacking) == [], f"sheet {code}: cells it HAS that are being blanked"


def test_the_published_sheets_are_the_declared_sheets(
    published: dict[str, set[tuple[str, str]]],
) -> None:
    # Arrange / Act
    codes = set(published)

    # Assert
    assert codes == set(B31_SHEET_KEYS)


def test_every_row_of_the_layout_is_published_and_only_the_owned_rows_are_missing(
    published: dict[str, set[tuple[str, str]]],
) -> None:
    # Arrange
    published_rows = {row for row, _ in _grid(published)}

    # Act
    layout = _layout_rows()

    # Assert
    assert sorted(layout - published_rows) == [], "layout rows OF 08.01 does not publish"
    assert published_rows - layout == ROWS_NOT_IN_LAYOUT


def test_the_layout_columns_are_the_published_columns(
    published: dict[str, set[tuple[str, str]]],
) -> None:
    # Arrange
    published_columns = {column for _, column in _grid(published)}

    # Act
    layout = _layout_columns()

    # Assert
    assert layout == published_columns


def test_the_sheet_dependent_cells_are_exactly_the_seven_known_ones(
    published: dict[str, set[tuple[str, str]]],
) -> None:
    # Arrange
    codes = set(published)

    # Act
    dependent = {
        cell: {code for code in codes if cell in published[code]}
        for cell in _grid(published)
        if 0 < sum(cell in published[code] for code in codes) < len(codes)
    }

    # Assert
    assert dependent == SHEET_DEPENDENT


def test_a_key_off_the_published_axis_blanks_only_the_cells_no_sheet_has(
    published: dict[str, set[tuple[str, str]]],
) -> None:
    """An off-axis sheet is still reported and counted in its Total
    (``c08_sheets``); it has no published grid of its own, so only what no
    sheet can carry is left out of it."""
    # Arrange
    on_some_sheet = set().union(*published.values())

    # Act
    declared = _declared(OFF_AXIS_KEY)

    # Assert
    assert declared == _grid(published) - on_some_sheet


def test_nothing_is_declared_blank_under_crr() -> None:
    """The CRR layout is not checked here: no EBA taxonomy is held to check it
    against, so nothing is blanked on it. A declaration appearing for CRR must
    arrive with its own source."""
    # Arrange / Act
    declared = {
        key: get_c08_01_unreported_cells("CRR", key) for key in ("corporate", "retail_qrre")
    }

    # Assert
    assert all(dict(cells) == {} for cells in declared.values())
