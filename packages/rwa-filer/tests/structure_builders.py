"""
Fact frames and pack variants for the structure-check tests.

``pack_builders.SAMPLE_COMPILED`` pins one behaviour per table, all written at
four digits and none of them an open-row table that also publishes row codes.
The structure check's code alignment and its per-table work need three shapes
that pack cannot express, so they are built here from it:

- ``build_alignment_pack`` — the sample pack plus
  ``T08.00.01.01``, a table that writes its row, column and sheet codes at
  THREE digits (``010`` / ``010`` / ``001``, ``002``) beside the four-digit
  tables, so one return can hold a code that must gain a zero and one that
  must lose one; and with ``T04.00.01.01`` (open rows) made to publish row
  codes ``0010`` / ``0020``, so a row identifier a filer chose can look
  exactly like a code that lost its zeros.
- ``build_wide_pack`` — the sample pack plus any number of extra copies of
  ``T01`` / ``T02`` / ``T04`` under other table codes, so the same return can
  be checked against a small module and a large one.

It is test data, not a statement about any real taxonomy.
"""

from __future__ import annotations

import copy
from datetime import date
from typing import TYPE_CHECKING, Any

import polars as pl

from pack_builders import SAMPLE_COMPILED, SAMPLE_VALID_FROM, VALID_LEI
from rwa_filer.model import CanonicalReturn, ReturnHeader
from rwa_filer.taxonomy.pack import TaxonomyPack, load_pack, write_pack

if TYPE_CHECKING:
    from pathlib import Path

T01 = "T01.00.01.01"
T02 = "T02.00.01.01"
T03 = "T03.00.01.01"
T04 = "T04.00.01.01"
T07 = "T07.00.01.01"
#: The three-digit table of ``build_alignment_pack``.
T08 = "T08.00.01.01"

#: The columns of a fact tuple, all codes as TEXT so nothing is padded on the way in.
FACT_COLUMNS: dict[str, type[pl.DataType]] = {
    "table": pl.String,
    "sheet": pl.String,
    "open_key": pl.String,
    "row": pl.String,
    "column": pl.String,
    "value": pl.Float64,
    "text_value": pl.String,
}


def fact_frame(*rows: tuple[object, ...]) -> pl.DataFrame:
    """Facts from ``(table, sheet, open_key, row, column, value, text_value)`` tuples."""
    return pl.DataFrame(list(rows), schema=FACT_COLUMNS, orient="row")


def packaged_return(module: str, frame: pl.DataFrame) -> CanonicalReturn:
    """A canonical return over ``frame`` for a packaged ``module``, with a valid header."""
    return CanonicalReturn.from_frame(ReturnHeader(VALID_LEI, date(2027, 3, 31), module), frame)


def build_alignment_pack(directory: Path) -> TaxonomyPack:
    """The sample pack with a three-digit table and an open-row table that publishes rows."""
    compiled = copy.deepcopy(SAMPLE_COMPILED)
    first = len(compiled["datapoints"])
    compiled["datapoints"] += [
        ["tst_met:mi2", ["tst_dim:EXC", "tst_EC:x3"]],
        ["tst_met:mi2", ["tst_dim:EXC", "tst_EC:x4"]],
    ]
    compiled["tables"][T04]["rows"] = [["0010", "First"], ["0020", "Second"]]
    compiled["tables"][T08] = {
        "title": "Three-digit codes",
        "group": "T08.00.01",
        "filing_indicator": "T08.00.01",
        "rows": [["010", "Exposure"]],
        "columns": [["010", "Amount"]],
        "open_rows": False,
        "open_keys": [],
        "z": [
            {
                "kind": "fixed",
                "code": "Z1",
                "label": "Sheets",
                "sheets": [
                    {"code": "001", "label": "One", "members": [["tst_dim:EXC", "tst_EC:x3"]]},
                    {"code": "002", "label": "Two", "members": [["tst_dim:EXC", "tst_EC:x4"]]},
                ],
            }
        ],
        "cells": [
            ["010", "010", "001", first, "workbook"],
            ["010", "010", "002", first + 1, "workbook"],
        ],
    }
    return _written(compiled, directory)


def build_wide_pack(directory: Path, *, copies: int) -> TaxonomyPack:
    """The sample pack with ``copies`` extra copies of ``T01``, ``T02`` and ``T04``.

    Each copy is the table under another code (``W001.01.01.01`` ...), with
    its own cells on the same data points: a module with many more tables,
    cells and key columns than the sample, none of which a return on the
    sample's own tables names.
    """
    compiled = copy.deepcopy(SAMPLE_COMPILED)
    for index in range(copies):
        for position, original in enumerate((T01, T02, T04), start=1):
            code = f"W{index:03d}.{position:02d}.01.01"
            table: dict[str, Any] = copy.deepcopy(SAMPLE_COMPILED["tables"][original])
            table["group"] = table["filing_indicator"] = code[:-3]
            compiled["tables"][code] = table
    return _written(compiled, directory)


def _written(compiled: dict[str, Any], directory: Path) -> TaxonomyPack:
    write_pack(compiled, directory, valid_from=SAMPLE_VALID_FROM)
    return load_pack(directory)
