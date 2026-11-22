"""
Every reportable cell of every packaged pack is placed on its own data point.

Pipeline position:
    CanonicalReturn + TaxonomyPack  ->  resolve_datapoints  ->  the rule
    engine's store and the XBRL writer

Key responsibilities:
- A return holding one fact in each reportable cell of a packaged module, its
  codes written with their leading zeros lost or with one zero too many, is
  placed cell for cell on the data points the pack gives those cells, once
  each, with nothing left unplaced and nothing placed twice.
- A key column of an open-row table, written the same way, is a key and
  reports no data point.

The expectation is read from the pack's own cell table, so the property
holds whatever the alignment and the joins are made of. It runs over every
packaged pack (rulings R0a / R12): most have no open-row table, two write
their codes at three digits, and PRA001 alone hides both.

References:
- Bank of England Banking Taxonomy v4.1.1 — the packaged modules
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from pack_builders import VALID_LEI
from rwa_filer.model import CanonicalReturn, ReturnHeader
from rwa_filer.taxonomy.pack import TaxonomyPack, available_packs, load_packaged
from rwa_filer.validate.structure import IS_KEY, resolve_datapoints

#: The row identifier every fact of an open-row table is given: the filer's own, never aligned.
OPEN_ROW = "R1"


@pytest.mark.parametrize("zeros", ["lost", "gained"])
@pytest.mark.parametrize("key", [info.key for info in available_packs()])
def test_every_reportable_cell_of_a_packaged_pack_is_placed_on_its_own_data_point(
    key: str, zeros: str
) -> None:
    # Arrange
    pack = load_packaged(key)
    cells = pack.cells
    facts = every_cell_respelt(pack, zeros)
    assert facts.height == cells.height + key_columns(pack)
    written = facts.head(cells.height)
    for axis in ("row", "column"):
        assert (written[axis] != cells[axis]).sum() > 0, f"no {axis} code needs aligning"
    ret = CanonicalReturn.from_frame(
        ReturnHeader(VALID_LEI, date(2027, 3, 31), pack.info.module), facts
    )

    # Act
    resolved = resolve_datapoints(ret, pack)

    # Assert
    placed = resolved.filter(~pl.col(IS_KEY))
    keys = resolved.filter(pl.col(IS_KEY))
    assert placed.height == cells.height
    assert keys.height == key_columns(pack)
    assert sorted(placed.select(pl.col("value").cast(pl.Int64), "datapoint").rows()) == [
        (number, point) for number, point in enumerate(cells["datapoint"].to_list())
    ]
    assert keys["datapoint"].null_count() == keys.height


def every_cell_respelt(pack: TaxonomyPack, zeros: str) -> pl.DataFrame:
    """One fact per reportable cell, then one per key column; ``value`` numbers the cells."""
    open_tables = [code for code, table in pack.tables.items() if table.open_rows]
    cells = pack.cells.with_columns(
        pl.when(pl.col("table").is_in(open_tables))
        .then(pl.lit(OPEN_ROW))
        .otherwise(respelt("row", zeros))
        .alias("row"),
        respelt("column", zeros),
        respelt("sheet", zeros),
        pl.int_range(pl.len()).cast(pl.Float64).alias("value"),
    ).select("table", "sheet", "row", "column", "value")
    keys = pl.DataFrame(
        [
            (code, None, OPEN_ROW, key, -1.0)
            for code in open_tables
            for key in pack.tables[code].key_codes
        ],
        schema=cells.schema,
        orient="row",
    ).with_columns(respelt("column", zeros))
    return pl.concat([cells, keys], how="vertical")


def respelt(column: str, zeros: str) -> pl.Expr:
    """A code column with its leading zeros lost (``0010`` -> ``10``) or one gained (``00010``)."""
    code = pl.col(column)
    changed = code.cast(pl.Int64).cast(pl.String) if zeros == "lost" else pl.lit("0") + code
    return changed.alias(column)


def key_columns(pack: TaxonomyPack) -> int:
    return sum(len(table.key_codes) for table in pack.tables.values() if table.open_rows)
