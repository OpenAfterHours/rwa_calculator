"""
The Basel 3.1 OF 08.01 row axis against the rows the Bank of England publishes.

Why this file exists: the OF 08.01 layout was written from a five-row reading of
the conversion-factor breakdown — 0031 10%, 0032 20%, 0033 40%, 0034 50%, 0035
100% — and the test that guarded it was written from the same list, so it passed
while the layout had no row 0001 at all and filed three of the five buckets on
the data point of the NEXT bucket. The published breakdown is six rows, not in
numeric order: 0031 10%, 0032 20%, 0001 40%, 0033 50%, 0034 100%, 0035 "Own
estimate" (PS1/26 Annex II p.116 heads the block "0031, 0032, 0001, 0033, 0035").
An all-null row files no fact, so neither the canonical mapping nor any published
rule could see the shift while the rows were empty.

The source of truth here is the PRA001 taxonomy pack, compiled from the Bank's
own data point model, which our generators and tests cannot drift with:

- the row axis — our layout's row refs are the published rows of
  ``OF08.01.01.01``, every one of them, in published order;
- the bucket rows — the rows ``corep/ccf_buckets.py`` assigns a conversion factor
  to are the published breakdown rows, in published order;
- the meaning of each bucket row — the row the bucket map gives a percentage is
  the row the pack labels with that percentage, and its data points carry that
  percentage's member of the conversion-factor dimension (``eba_dim:CFO``).

The member codes below are the Bank's (``eba_PC`` / ``boe_eba_PC`` member label
linkbases in its v4.1.1 package): written out, not read from the code under
test, so a bucket filed on the wrong member fails here.

References:
- PRA PS1/26 Annex II §3.3.3 rows 0031, 0032, 0001, 0033, 0034, 0035 (p.116)
- PRA PS1/26 Art. 111(1) Table A1 (the 10% / 20% / 40% / 50% / 100% factors);
  Art. 166D(1)(a) and (3) (own estimates of conversion factor and of EAD)
- Bank of England Banking Taxonomy v4.1.1, module PRA001, table ``OF08.01.01.01``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_calc.reporting.corep import ccf_buckets
from rwa_calc.reporting.corep.templates import get_irb_row_sections
from rwa_calc.reporting.filing.canonical import FILING_MODULE, FILING_TAXONOMY
from rwa_filer.release import resolve_release

if TYPE_CHECKING:
    from rwa_filer.taxonomy.pack import Table, TaxonomyPack

FRAMEWORK = "BASEL_3_1"
TABLE = "OF08.01.01.01"
#: The off-balance-sheet row the buckets break down, and the first row after them.
OFF_BALANCE_SHEET_ROW = "0030"
FIRST_ROW_AFTER_BUCKETS = "0040"
CONVERSION_FACTOR_DIMENSION = "eba_dim:CFO"
#: Any sheet: every bucket row is published on all seventeen (``test_of08_published_cells``).
A_SHEET = "0012"
A_COLUMN = "0020"

#: Conversion factor -> (its percentage as the pack's row label states it, its
#: ``eba_dim:CFO`` member in the Bank's v4.1.1 package).
PUBLISHED_BUCKETS: dict[float, tuple[str, str]] = {
    0.1: ("10%", "eba_PC:x6"),
    0.2: ("20%", "eba_PC:x8"),
    0.4: ("40%", "eba_PC:x450"),
    0.5: ("50%", "eba_PC:x10"),
    1.0: ("100%", "eba_PC:x14"),
}
OWN_ESTIMATE_LABEL = "Own estimate"
OWN_ESTIMATE_MEMBER = "boe_eba_PC:x10012"


@pytest.fixture(scope="module")
def pack() -> TaxonomyPack:
    return resolve_release(FILING_MODULE, FILING_TAXONOMY).pack


@pytest.fixture(scope="module")
def table(pack: TaxonomyPack) -> Table:
    return pack.table(TABLE)


def _published_rows(table: Table) -> list[str]:
    return [ref for ref, _label in table.rows]


def _label(table: Table, ref: str) -> str:
    (label,) = [label for row, label in table.rows if row == ref]
    return label


def _member(pack: TaxonomyPack, ref: str) -> str | None:
    """The conversion-factor member of row ``ref``'s data point."""
    (datapoint,) = (
        pack.cells.filter(
            (pl.col("table") == TABLE)
            & (pl.col("row") == ref)
            & (pl.col("sheet") == A_SHEET)
            & (pl.col("column") == A_COLUMN)
        )
        .get_column("datapoint")
        .to_list()
    )
    return dict(pack.datapoint(datapoint).dimensions).get(CONVERSION_FACTOR_DIMENSION)


def _layout_rows() -> list[str]:
    return [row.ref for section in get_irb_row_sections(FRAMEWORK) for row in section.rows]


def test_the_layout_rows_are_the_published_rows_in_published_order(table: Table) -> None:
    # Arrange
    published = _published_rows(table)

    # Act
    layout = _layout_rows()

    # Assert
    assert layout == published


def test_the_bucket_rows_are_the_published_breakdown_of_the_off_balance_sheet_row(
    table: Table,
) -> None:
    # Arrange
    published = _published_rows(table)
    start, end = published.index(OFF_BALANCE_SHEET_ROW), published.index(FIRST_ROW_AFTER_BUCKETS)

    # Act
    breakdown = published[start + 1 : end]

    # Assert
    assert list(ccf_buckets.OF08_01_CCF_ROWS) == breakdown


@pytest.mark.parametrize("factor", sorted(PUBLISHED_BUCKETS))
def test_each_conversion_factor_maps_to_the_row_the_pack_gives_that_factor(
    pack: TaxonomyPack, table: Table, factor: float
) -> None:
    # Arrange
    percentage, member = PUBLISHED_BUCKETS[factor]

    # Act
    row = ccf_buckets.OF08_01_ROW_BY_CCF[factor]

    # Assert
    assert _label(table, row).endswith(percentage), (row, _label(table, row))
    assert _member(pack, row) == member


def test_the_own_estimate_row_is_the_row_the_pack_gives_own_estimates(
    pack: TaxonomyPack, table: Table
) -> None:
    # Arrange / Act
    row = ccf_buckets.OWN_ESTIMATE_ROW

    # Assert
    assert _label(table, row) == OWN_ESTIMATE_LABEL
    assert _member(pack, row) == OWN_ESTIMATE_MEMBER


@pytest.mark.parametrize("factor", sorted(PUBLISHED_BUCKETS))
def test_the_layout_labels_each_bucket_row_with_the_factor_the_pack_gives_it(
    factor: float,
) -> None:
    """Our own row label agrees with the pack's — the label a reader of the
    generated workbook sees is the bucket the figure is filed on."""
    # Arrange
    percentage, _member_code = PUBLISHED_BUCKETS[factor]
    labels = {
        row.ref: row.name for section in get_irb_row_sections(FRAMEWORK) for row in section.rows
    }

    # Act
    rows_labelled = [
        row for row in ccf_buckets.OF08_01_CCF_ROWS if labels.get(row, "").endswith(percentage)
    ]

    # Assert
    assert rows_labelled == [ccf_buckets.OF08_01_ROW_BY_CCF[factor]]
