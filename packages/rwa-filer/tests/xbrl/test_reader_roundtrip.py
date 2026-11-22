"""
The XBRL reader on open rows and open members: what is written is what is read.

Pipeline position:
    CanonicalReturn  ->  write_instance  ->  read_instance  ->  the same CanonicalReturn

Why this exists: an open-row table is where the reader does the most work a
plain table never asks of it. It matches a fact to a data point that leaves one
or two dimensions open, tells a typed member from a listed one, puts each row's
keys back as cells of their own and names the row after them. None of the
benchmark returns the reader's cost work was measured on has such a table, so
"the same output on every benchmark return" says nothing about any of it. These
tests are the statement that does.

Equality here is of the whole return — header, declared filing indicators and
every column of every fact, ``decimals`` included — and of its content digest
(``validate.identity.facts_sha256``), which is what an evidence file records.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest

from pack_builders import VALID_LEI, build_pack, build_return
from reader_builders import OPEN_ROW_TABLES, open_row_return
from rwa_filer.model import FACT_SCHEMA, CanonicalReturn, ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate.identity import facts_sha256
from rwa_filer.validate.structure import check_structure
from rwa_filer.xbrl.reader import read_instance
from rwa_filer.xbrl.writer import write_instance

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.taxonomy.pack import TaxonomyPack

ROWS_PER_TABLE = 3


@pytest.fixture(scope="module")
def pra001() -> TaxonomyPack:
    return resolve_release("PRA001").pack


def _same_return(read: CanonicalReturn, written: CanonicalReturn) -> bool:
    """Header, filing indicators and every fact column equal, whatever the row order."""
    columns = FACT_SCHEMA.names()
    return (
        read.header == written.header
        and dict(read.indicators or {}) == dict(written.indicators or {})
        and read.facts.sort(columns, nulls_last=False).equals(
            written.facts.sort(columns, nulls_last=False)
        )
    )


def _open_members_supplied(pack: TaxonomyPack, ret: CanonicalReturn) -> dict[int, int]:
    """How many of the return's cells sit on a data point leaving 1, 2, ... dimensions open."""
    opened = {
        number: sum(member.startswith("*") for _dimension, member in point.dimensions)
        for number, point in enumerate(pack.datapoints)
    }
    by_column = {
        (table, sheet, column): opened[point]
        for table, sheet, column, point in pack.cells.select(
            "table", "sheet", "column", "datapoint"
        ).iter_rows()
    }
    counts: dict[int, int] = {}
    for table, sheet, column in ret.facts.select("table", "sheet", "column").iter_rows():
        supplied = by_column.get((table, sheet, column))
        if supplied:
            counts[supplied] = counts.get(supplied, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# The sample pack: one typed key, a listed open member, an optional one
# ---------------------------------------------------------------------------


def test_typed_keys_and_local_name_open_members_read_back_as_the_same_return(
    tmp_path: Path,
) -> None:
    """A typed row key, an open sheet named by a member's local name, and the default sheet."""
    # Arrange
    pack = build_pack(tmp_path)
    columns = ["table", "sheet", "open_key", "row", "column", "value", "text_value", "decimals"]
    rows = [
        ("T03.00.01.01", None, "GB", "0010", "0010", 70.0, None, -3),
        ("T03.00.01.01", None, "x1", "0020", "0010", 100.0, None, -3),
        ("T04.00.01.01", None, None, "3", "0005", None, "3", None),
        ("T04.00.01.01", None, None, "3", "0010", 500.0, None, -3),
        ("T04.00.01.01", None, None, "3", "0020", 12.0, None, 0),
        ("T04.00.01.01", None, None, "8", "0005", None, "8", None),
        ("T04.00.01.01", None, None, "8", "0010", 250.0, None, -3),
        ("T07.00.01.01", None, None, "0010", "0010", 100.0, None, -3),
        ("T07.00.01.01", None, "x1", "0010", "0010", 40.0, None, -3),
    ]
    plain = build_return(pl.DataFrame(rows, schema=columns, orient="row"))
    written = CanonicalReturn(
        plain.header, plain.facts, {"T03.00.01": True, "T04.00.01": True, "T07.00.01": True}
    )

    # Act
    reading = read_instance(write_instance(written, pack).content, pack=pack)

    # Assert
    assert reading.findings == ()
    assert _same_return(reading.ret, written)
    assert facts_sha256(reading.ret) == facts_sha256(written)


# ---------------------------------------------------------------------------
# PRA001: every kind of open-row table the module has
# ---------------------------------------------------------------------------


def test_an_open_row_return_reads_back_as_the_same_return(pra001: TaxonomyPack) -> None:
    # Arrange
    header = ReturnHeader(VALID_LEI, date(2027, 3, 31), "PRA001")
    written = open_row_return(pra001, header, ROWS_PER_TABLE)
    instance = write_instance(written, pra001)
    supplied = _open_members_supplied(pra001, written)
    assert check_structure(written, pra001) == [], "the return is not one a firm could file"
    assert sorted(written.tables) == sorted(OPEN_ROW_TABLES)
    assert instance.content.count(b"<xbrldi:typedMember") > 100, "no typed member was written"
    assert supplied.get(1, 0) > 100, "no cell leaves one dimension open"
    assert supplied.get(2, 0) > 100, (
        "no cell leaves two dimensions open at once - the most any data point of this module "
        "does, and the case a reader that tries too few of a fact's open dimensions gets wrong"
    )

    # Act
    reading = read_instance(instance.content, pack=pra001)

    # Assert
    assert reading.findings == ()
    assert reading.facts == instance.facts
    assert _same_return(reading.ret, written)
    assert facts_sha256(reading.ret) == facts_sha256(written)


def test_an_open_row_instance_is_rewritten_byte_for_byte(pra001: TaxonomyPack) -> None:
    # Arrange
    header = ReturnHeader(VALID_LEI, date(2027, 3, 31), "PRA001")
    first = write_instance(open_row_return(pra001, header, ROWS_PER_TABLE), pra001).content

    # Act
    second = write_instance(read_instance(first, pack=pra001).ret, pra001).content

    # Assert
    assert second == first
