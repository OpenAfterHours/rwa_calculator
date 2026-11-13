"""
The Basel 3.1 OF 07.00 layout against the cells the Bank of England publishes.

Why this file exists: the generator's layout — which rows, which columns, and
which of their intersections carry a figure — was written from the template's
headings and never compared, cell by cell, with the template itself. Three
families of figure were being reported where the published template has no
cell: the CRM substitution block on the risk-weight rows, the pre-conversion
columns on the counterparty-credit-risk rows, and a column (0020) OF 07.00 does
not have at all. A return cannot carry any of them.

The source of truth here is the PRA001 taxonomy pack, compiled from the Bank's
own data point model (tables ``OF07.00.01.01`` .. ``.05``): a (row, column) the
pack holds on no sheet is a cell the template greys out. The declared set in
``corep/of07_published_cells.py`` must equal it exactly, in both directions — a cell
blanked that the template does have loses a figure, and one left that it does
not have cannot be filed.

Sheet scope is deliberately NOT held here. The memorandum rows are published on
some sheets only (0300/0320, 0371-0374, 0380), and which sheet our generator
puts them on is the open question recorded as P1.377.

References:
- PRA PS1/26 Annex I (OF 07.00 template) and Annex II §3.2
- Bank of England Banking Taxonomy v4.1.1, module PRA001
"""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from rwa_calc.reporting.corep.of07_published_cells import (
    get_c07_rows_not_on_total,
    get_c07_unreported_cells,
)
from rwa_calc.reporting.corep.templates import (
    C07_00_TOTAL_SHEET_KEY,
    get_c07_columns,
    get_sa_row_sections,
)
from rwa_calc.reporting.filing.canonical import FILING_MODULE
from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS
from rwa_filer.taxonomy.pack import resolve_pack

REFERENCE_DATE = dt.date(2027, 3, 31)
FRAMEWORK = "BASEL_3_1"
TABLE_PREFIX = "OF07.00.01."
TOTAL_SHEET_CODE = "0001"


@pytest.fixture(scope="module")
def published() -> set[tuple[str, str]]:
    """Every (row, column) OF 07.00 has a data point for, on any sheet."""
    cells = resolve_pack(FILING_MODULE, REFERENCE_DATE).cells.filter(
        pl.col("table").str.starts_with(TABLE_PREFIX)
    )
    return set(zip(cells["row"].to_list(), cells["column"].to_list(), strict=True))


def _layout_rows() -> list[str]:
    return [row.ref for section in get_sa_row_sections(FRAMEWORK) for row in section.rows]


def _layout_columns() -> list[str]:
    return [column.ref for column in get_c07_columns(FRAMEWORK)]


def test_every_column_of_the_layout_is_a_published_column(
    published: set[tuple[str, str]],
) -> None:
    # Arrange
    published_columns = {column for _, column in published}

    # Act
    unpublished = [ref for ref in _layout_columns() if ref not in published_columns]

    # Assert
    assert unpublished == [], f"OF 07.00 has no column {unpublished}"


def test_every_published_column_is_in_the_layout(published: set[tuple[str, str]]) -> None:
    # Arrange
    layout = set(_layout_columns())

    # Act
    missing = sorted({column for _, column in published} - layout)

    # Assert
    assert missing == [], f"the layout lacks published OF 07.00 columns {missing}"


def test_the_layout_and_the_published_template_have_the_same_rows(
    published: set[tuple[str, str]],
) -> None:
    # Arrange
    layout = set(_layout_rows())

    # Act
    published_rows = {row for row, _ in published}

    # Assert
    assert layout == published_rows


def test_the_declared_blank_cells_are_exactly_the_cells_the_template_lacks(
    published: set[tuple[str, str]],
) -> None:
    # Arrange
    declared = {
        (row, column)
        for row, columns in get_c07_unreported_cells(FRAMEWORK).items()
        for column in columns
    }

    # Act
    lacking = {
        (row, column)
        for row in _layout_rows()
        for column in _layout_columns()
        if (row, column) not in published
    }

    # Assert
    assert sorted(lacking - declared) == [], "cells the template lacks that are still reported"
    assert sorted(declared - lacking) == [], "cells the template HAS that are being blanked"


def test_nothing_is_declared_blank_under_crr() -> None:
    """The CRR layout is not checked here: no EBA taxonomy is held to check it
    against, so nothing is blanked on it. A declaration appearing for CRR must
    arrive with its own source."""
    # Arrange / Act
    declared = get_c07_unreported_cells("CRR")

    # Assert
    assert dict(declared) == {}


def test_the_rows_kept_off_the_total_sheet_are_exactly_those_it_has_no_cell_for() -> None:
    """The Total sheet is the sum of the class sheets, so it would carry every
    row a class sheet carries — but the template publishes the equity
    transitional memorandum rows for the equity class alone (Annex II ¶55A)."""
    # Arrange
    cells = resolve_pack(FILING_MODULE, REFERENCE_DATE).cells.filter(
        pl.col("table").str.starts_with(TABLE_PREFIX)
    )
    on_total = set(cells.filter(pl.col("sheet") == TOTAL_SHEET_CODE)["row"].to_list())

    # Act
    absent = {row for row in _layout_rows() if row not in on_total}

    # Assert
    assert get_c07_rows_not_on_total(FRAMEWORK) == absent
    assert get_c07_rows_not_on_total("CRR") == frozenset()


@pytest.mark.parametrize("sheet_map", ["c07", "of07"])
def test_the_published_total_sheet_code_addresses_the_generated_total(sheet_map: str) -> None:
    """``sheet_maps.py`` spells the key as a literal (arch_check check 22 reads
    it off the source); this is what keeps the literal and the constant equal."""
    # Arrange / Act
    entry = SHEET_INDEX_MAPS[sheet_map][TOTAL_SHEET_CODE]

    # Assert
    assert entry.bundle_keys == (C07_00_TOTAL_SHEET_KEY,)
