"""Match reporting units' open rows to the supplied group's rows by their taxonomy keys."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_filer.validate.structure import key_text

if TYPE_CHECKING:
    from rwa_filer.taxonomy.pack import TaxonomyPack


def align_open_rows(
    units: pl.DataFrame, group: pl.DataFrame, column: str, code: str, pack: TaxonomyPack
) -> pl.DataFrame | None:
    """Readdress unit facts for comparisons. The caller retains the original source rows."""
    tables = {name: table.open_keys for name, table in pack.tables.items() if table.open_rows}
    open_units = units.filter(pl.col("table").is_in(list(tables)))
    if open_units.is_empty():
        return None
    address = ["table", "sheet", "open_key", "row"]
    unit_rows = open_units.select(*address, column).unique(maintain_order=True)
    group_rows = group.filter(pl.col("table").is_in(list(tables)))
    fields = [*address, "column", "value", "text_value"]
    both = pl.concat(
        [
            group_rows.select(*fields, pl.lit(code).alias("unit")),
            open_units.select(*fields, pl.col(column).alias("unit")),
        ]
    )
    type Row = tuple[str, str | None, str | None, str, str | None]
    keys: dict[Row, dict[str, list[str]]] = {}
    key_types = {(table, key.code): key for table, required in tables.items() for key in required}
    for table, sheet, axis, row, unit, field, value in (
        both.filter(pl.col("column").is_in(sorted({field for _, field in key_types})))
        .select(*address, "unit", "column", key_text())
        .iter_rows()
    ):
        key = key_types.get((table, field))
        if key is None or value is None:
            continue
        if key.kind == "explicit" and value in key.members:
            value = value.rsplit(":", 1)[-1]
        keys.setdefault((table, sheet, axis, row, unit), {}).setdefault(field, []).append(value)

    # Require a single complete, unambiguous key on each side of a match.
    type Identity = tuple[str, str | None, str | None, tuple[str, ...]]
    owners: dict[tuple[Identity, str | None], list[str]] = {}
    identities: dict[Row, Identity] = {}
    for location, found in keys.items():
        table, sheet, axis, row, unit = location
        parts = [found.get(key.code, []) for key in tables[table]]
        if all(len(values) == 1 for values in parts):
            identity = (table, sheet, axis, tuple(values[0] for values in parts))
            identities[location] = identity
            owners.setdefault((identity, unit), []).append(row)

    # A unit-only row still contributes to its own rules, even when its local
    # number coincides with a different group row. Reserve unused working IDs.
    prefix = "~unit:"
    group_ids = set(group_rows["row"].drop_nulls().to_list())
    while any(row.startswith(prefix) for row in group_ids):
        prefix += "~"
    aligned: list[str] = []
    for index, location in enumerate(unit_rows.iter_rows()):
        identity = identities.get(location)
        matched = owners.get((identity, code), []) if identity is not None else []
        if identity is not None and len(matched) == len(owners[identity, location[-1]]) == 1:
            aligned.append(matched[0])
        else:
            aligned.append(f"{prefix}{index}")
    # Use a fresh name even when a source's breakdown or line reference is named alike.
    target = "_group_row"
    while target in units.columns:
        target += "_"
    return (
        units.join(
            unit_rows.with_columns(pl.Series(target, aligned)),
            on=[*address, column],
            how="left",
            nulls_equal=True,
            maintain_order="left",
        )
        .with_columns(pl.coalesce(target, "row").alias("row"))
        .drop(target)
    )
