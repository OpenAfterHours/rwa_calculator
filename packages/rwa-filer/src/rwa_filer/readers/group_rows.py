"""Match reporting units' open rows to the supplied group's rows by their taxonomy keys."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_filer.validate.structure import key_text

if TYPE_CHECKING:
    from rwa_filer.taxonomy.pack import OpenKey, TaxonomyPack


_ADDRESS = ("table", "sheet", "open_key", "row")
type _UnitRow = tuple[str, str | None, str | None, str, str | None]


def align_open_rows(
    units: pl.DataFrame, group: pl.DataFrame, column: str, code: str, pack: TaxonomyPack
) -> pl.DataFrame | None:
    """Readdress unit facts for comparisons. The caller retains the original source rows."""
    tables = {name: table.open_keys for name, table in pack.tables.items() if table.open_rows}
    open_units = units.filter(pl.col("table").is_in(list(tables)))
    if open_units.is_empty():
        return None
    unit_rows = open_units.select(*_ADDRESS, column).unique(maintain_order=True)
    group_rows = group.filter(pl.col("table").is_in(list(tables)))
    fields = [*_ADDRESS, "column", "value", "text_value"]
    both = pl.concat(
        [
            group_rows.select(*fields, pl.lit(code).alias("unit")),
            open_units.select(*fields, pl.col(column).alias("unit")),
        ]
    )
    matches = _match_group_rows(both, tables, code)

    # A unit-only row still contributes to its own rules, even when its local
    # number coincides with a different group row. Reserve unused working IDs.
    prefix = "~unit:"
    group_ids = set(group_rows["row"].drop_nulls().to_list())
    while any(row.startswith(prefix) for row in group_ids):
        prefix += "~"
    aligned = [
        matches.get(location, f"{prefix}{index}")
        for index, location in enumerate(unit_rows.iter_rows())
    ]
    # Use a fresh name even when a source's breakdown or line reference is named alike.
    target = "_group_row"
    while target in units.columns:
        target += "_"
    return (
        units.join(
            unit_rows.with_columns(pl.Series(target, aligned)),
            on=[*_ADDRESS, column],
            how="left",
            nulls_equal=True,
            maintain_order="left",
        )
        .with_columns(pl.coalesce(target, "row").alias("row"))
        .drop(target)
    )


def _match_group_rows(
    facts: pl.DataFrame, tables: dict[str, tuple[OpenKey, ...]], group_code: str
) -> dict[_UnitRow, str]:
    """Map a unit row only when its complete key occurs once in that unit and the group."""
    type Identity = tuple[str, str | None, str | None, tuple[str, ...]]
    owners: dict[Identity, dict[str | None, list[_UnitRow]]] = {}
    for location, found in _row_keys(facts, tables).items():
        table, sheet, axis, _, unit = location
        parts = [found.get(key.code, []) for key in tables[table]]
        if all(len(values) == 1 for values in parts):
            identity = (table, sheet, axis, tuple(values[0] for values in parts))
            owners.setdefault(identity, {}).setdefault(unit, []).append(location)

    matches: dict[_UnitRow, str] = {}
    for units in owners.values():
        group = units.get(group_code, [])
        if len(group) == 1:
            for rows in units.values():
                if len(rows) == 1:
                    matches[rows[0]] = group[0][3]
    return matches


def _row_keys(
    facts: pl.DataFrame, tables: dict[str, tuple[OpenKey, ...]]
) -> dict[_UnitRow, dict[str, list[str]]]:
    """Collect all reported values for the taxonomy key columns of each local row."""
    key_types = {(table, key.code): key for table, required in tables.items() for key in required}
    columns = sorted({key.code for key in key_types.values()})
    rows = facts.filter(pl.col("column").is_in(columns)).select(
        *_ADDRESS, "unit", "column", key_text()
    )
    keys: dict[_UnitRow, dict[str, list[str]]] = {}
    for table, sheet, axis, row, unit, field, value in rows.iter_rows():
        key = key_types.get((table, field))
        if key is None or value is None:
            continue
        if key.kind == "explicit" and value in key.members:
            value = value.rsplit(":", 1)[-1]
        keys.setdefault((table, sheet, axis, row, unit), {}).setdefault(field, []).append(value)
    return keys
