"""
A deterministic thin carve of the Bank of England's PRA001 sample instance.

The Bank's sample holds one fact for every data point of the module — 61,428 —
which is more than the reference XBRL processor can evaluate rules over in
ordinary memory. A carve keeps the structure and sheds the bulk: a few sheets
per table, a few rows per open-row table. It is defined here, once, so that
the instance an oracle was measured on can be rebuilt exactly from the Bank's
file wherever that file is available.

The sample is the Bank's own and is not redistributed; nothing here contains it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from pack_builders import VALID_LEI
from rwa_filer.model import CanonicalReturn

if TYPE_CHECKING:
    from collections.abc import Collection

    from rwa_filer.xbrl.reader import InstanceReading

#: The four credit-risk template groups the first oracle was measured on.
CREDIT_INDICATORS = frozenset({"OF02.00.01", "OF07.00.01", "OF08.01.01", "OF09.01.01"})


def thin_carve(
    reading: InstanceReading,
    indicators: Collection[str] | None = None,
    *,
    sheets_per_table: int = 2,
    open_rows_per_sheet: int = 3,
) -> CanonicalReturn:
    """A thin return carved from ``reading``, declaring exactly the templates it keeps.

    Args:
        reading: The Bank's sample, as read.
        indicators: The template groups (filing-indicator codes) to keep;
            ``None`` keeps every template.
        sheets_per_table: Fixed sheets, and open-axis members, kept per table —
            the first by code, and the first by name.
        open_rows_per_sheet: Rows kept per open-row table.

    The header is given a checksum-valid LEI and a date the taxonomy applies
    on: the sample's own are placeholders the structure checks reject.
    """
    pack, ret = reading.pack, reading.ret
    kept: list[pl.DataFrame] = []
    for code, table in pack.tables.items():
        if indicators is not None and table.filing_indicator not in indicators:
            continue
        part = ret.facts.filter(pl.col("table") == code)
        if part.is_empty():
            continue
        if table.fixed_axis is not None:
            part = part.filter(pl.col("sheet").is_in(list(table.sheet_codes[:sheets_per_table])))
        if table.open_axis is not None:
            members = sorted(part["open_key"].drop_nulls().unique().to_list())[:sheets_per_table]
            part = part.filter(pl.col("open_key").is_null() | pl.col("open_key").is_in(members))
        if table.open_rows:
            rows = sorted(part["row"].unique().to_list())[:open_rows_per_sheet]
            part = part.filter(pl.col("row").is_in(rows))
        kept.append(part)
    facts = pl.concat(kept) if kept else ret.facts.clear()
    reported = sorted(
        {pack.tables[table].filing_indicator for table in facts["table"].unique().to_list()}
    )
    header = replace(ret.header, entity_identifier=VALID_LEI, reference_date=date(2027, 3, 31))
    return CanonicalReturn(header, facts, dict.fromkeys(reported, True))
