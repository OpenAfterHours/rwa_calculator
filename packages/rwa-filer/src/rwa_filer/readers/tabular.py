"""
Tabular readers — a long-format fact table in Parquet or CSV.

Pipeline position:
    facts.parquet | facts.csv  ->  read_parquet / read_csv  ->  CanonicalReturn

Key responsibilities:
- Read one row per reported cell: ``table``, ``row``, ``column``, ``value``,
  and — where the return needs them — ``sheet``, ``open_key``, ``text_value``.
- Keep every code EXACTLY as written. CSV is read as text throughout, so a
  leading zero cannot be lost to type inference (``0010`` must not become 10).
- Keep a value that is not a number. A ``value`` cell holding ``n/a`` is moved
  to ``text_value`` rather than nulled, so the structure check reports a
  number-typed cell carrying text instead of the fact quietly disappearing.

The expected columns are the canonical ones (``rwa_filer.model.FACT_SCHEMA``).
Column names are matched case-insensitively and surrounding whitespace is
ignored; extra columns are ignored.

References:
- rwa_filer.model — the canonical fact schema
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from rwa_filer.model import FACT_SCHEMA, CanonicalReturn

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.model import ReturnHeader

logger = logging.getLogger(__name__)


def read_parquet(path: Path, header: ReturnHeader) -> CanonicalReturn:
    """Read a long-format Parquet fact table."""
    frame = _rename_to_schema(pl.read_parquet(path))
    logger.info("read %d rows from %s", frame.height, path.name)
    return CanonicalReturn.from_frame(header, _rescue_text_values(frame))


def read_csv(path: Path, header: ReturnHeader) -> CanonicalReturn:
    """Read a long-format CSV fact table.

    Every column is read as text: the codes must keep their leading zeros, and
    ``value`` is parsed here, where a cell that will not parse can be kept.
    """
    frame = _rename_to_schema(pl.read_csv(path, infer_schema=False, encoding="utf8-lossy"))
    logger.info("read %d rows from %s", frame.height, path.name)
    return CanonicalReturn.from_frame(header, _rescue_text_values(frame))


# =============================================================================
# Private helpers
# =============================================================================


def _rename_to_schema(frame: pl.DataFrame) -> pl.DataFrame:
    """Fold the file's column names onto the canonical ones (case and padding)."""
    wanted = {name.lower(): name for name in FACT_SCHEMA.names()}
    renames = {
        column: wanted[column.strip().lower()]
        for column in frame.columns
        if column.strip().lower() in wanted and column != wanted[column.strip().lower()]
    }
    return frame.rename(renames)


def _rescue_text_values(frame: pl.DataFrame) -> pl.DataFrame:
    """Parse a text ``value`` column, moving anything unparseable to ``text_value``.

    Only a ``value`` column that arrived as TEXT needs this (CSV, or a Parquet
    file written with a string column). A numeric column is left alone.
    """
    if "value" not in frame.columns or frame.schema["value"] != pl.String:
        return frame
    raw = pl.col("value").str.strip_chars()
    number = raw.str.replace_all(",", "").cast(pl.Float64, strict=False)
    unparsed = number.is_null() & raw.is_not_null() & (raw.str.len_chars() > 0)
    existing = pl.col("text_value") if "text_value" in frame.columns else pl.lit(None, pl.String)
    return frame.with_columns(
        number.alias("value"),
        pl.when(unparsed & existing.is_null()).then(raw).otherwise(existing).alias("text_value"),
    )
