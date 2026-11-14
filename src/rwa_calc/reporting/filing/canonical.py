"""
Canonical return — our generated COREP estate, in the supervisor's own coordinates.

Pipeline position:
    COREPTemplateBundle  ->  build_canonical_return
        ->  CanonicalMapping(canonical return, what could not be placed)
        ->  rwa_filer (structure checks, rules, XBRL)

Key responsibilities:
- Re-address every figure we generate from OUR coordinates (bundle member,
  class-named sheet, row and column reference) to the taxonomy's: the published
  table code, the published sheet (z) code, and the row and column codes — the
  shape ``rwa_filer.model.CanonicalReturn`` holds and a submission is written
  from.
- Decide, for each cell, whether the taxonomy has a place for it, by looking it
  up in the taxonomy pack — never by assuming our template layout matches the
  regulator's.
- Account for EVERY cell that has no place. Nothing is dropped silently: each
  unplaced cell is returned with the reason, so a figure we compute and the
  regulator has no cell for is a visible finding, not a quiet omission.
- File ONE value for a data point that several of our cells show. The taxonomy
  makes some cells of different templates one data point (the SA total is
  OF 02.00 rows 0050 and 0060 and the OF 07.00 Total sheet); each template adds
  the same exposures up in its own order, and two orders of addition are not
  reliably the same float. Where the cells agree to rounding the return carries
  one value; where they do not, both are kept and the structure check refuses
  the return (``STR007``) — a real disagreement is never smoothed over.

Why a cell can have no place
- ``sheet_coarser_than_published_axis``: several published sheet codes map onto
  ONE of our sheets (our IRB sheets are per exposure class; the published axis
  also splits by approach, and by SME / non-SME). A figure on such a sheet
  cannot be assigned to any single published sheet.
- ``sheet_has_no_published_code``: our sheet key appears in no published code.
- ``open_key_not_a_member``: a per-sheet key (a country, a lending type) that is
  not a member the table's open axis accepts.
- ``open_rows_not_mapped``: the published table has no fixed rows — its rows are
  keyed by a typed dimension — and we do not yet key ours that way.
- ``row_not_in_taxonomy`` / ``column_not_in_taxonomy``: a row or column code the
  published table does not have.
- ``cell_not_reportable``: the row and column both exist, but the taxonomy does
  not accept a figure at their intersection on that sheet (a greyed cell).

A ZERO in a cell the taxonomy has no place for loses nothing — there is nothing
to report there. A NON-ZERO figure with no place is a real gap between what we
generate and what can be filed; ``CanonicalMapping.unplaced_figures`` counts
exactly those, and ``scripts/filing_mapping_report.py`` ratchets it.

Scope: the Basel 3.1 estate (module PRA001). Only numeric cells are mapped;
label cells (a PD-band caption, say) carry no figure.

References:
- Bank of England Banking Taxonomy v4.1.1 (PRA001) — the cells that exist
- PRA PS1/26 Annex II — the OF templates this estate generates
- docs/development/workspace.md — the adapter boundary
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import polars as pl

from rwa_calc.reporting.filing.bindings import build_template_index
from rwa_filer.model import FACT_SCHEMA, CanonicalReturn
from rwa_filer.rules.catalogue import FRAMEWORK_BASEL_3_1
from rwa_filer.taxonomy.pack import resolve_pack
from rwa_filer.validate.evaluate import GEOGRAPHY_TOTAL_SHEET
from rwa_filer.validate.index import SINGLE_SHEET
from rwa_filer.validate.structure import local_name

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_filer.model import ReturnHeader
    from rwa_filer.taxonomy.pack import Table, TaxonomyPack
    from rwa_filer.validate.index import SheetCode, TableBinding

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: The reporting module our Basel 3.1 COREP estate is filed under.
FILING_MODULE: Final = "PRA001"

REASON_SHEET_COARSER: Final = "sheet_coarser_than_published_axis"
REASON_SHEET_UNPUBLISHED: Final = "sheet_has_no_published_code"
REASON_OPEN_KEY: Final = "open_key_not_a_member"
REASON_OPEN_ROWS: Final = "open_rows_not_mapped"
REASON_ROW: Final = "row_not_in_taxonomy"
REASON_COLUMN: Final = "column_not_in_taxonomy"
REASON_CELL: Final = "cell_not_reportable"

#: The open-axis member that is the all-geographies total — keyed
#: ``GEOGRAPHY_TOTAL_SHEET`` in our per-country bundles.
_GEOGRAPHY_TOTAL_MEMBER: Final = "x1"

#: The DPM data type of a yes/no metric.
_TYPE_BOOLEAN: Final = "boolean"

#: Two cells of one data point are the SAME figure when they agree to eleven
#: significant figures — summation-order rounding is of the order of 1e-13 of a
#: total even over a million exposures, and a penny on a 50m figure is 2e-10,
#: so a penny is a disagreement and rounding is not — or when they differ by a
#: millionth of a unit, for a sum that cancels to zero in one order and leaves
#: a residue in another. Anything larger is the two templates disagreeing.
_SAME_FIGURE_RELATIVE: Final = 1e-11
_SAME_FIGURE_ABSOLUTE: Final = 1e-6

#: Frame columns that are labels, not reportable cells.
_LABEL_COLUMNS: Final[frozenset[str]] = frozenset({"row_ref", "row_name", "row_label", "label"})

#: The unplaced-cell table, in column order. ``template`` is OUR bundle member
#: and ``sheet`` OUR sheet key: an unplaced cell has no published address.
UNPLACED_SCHEMA: Final = pl.Schema(
    {
        "template": pl.String,
        "sheet": pl.String,
        "row": pl.String,
        "column": pl.String,
        "value": pl.Float64,
        "reason": pl.String,
    }
)

_LONG_SCHEMA: Final = pl.Schema({"row": pl.String, "column": pl.String, "value": pl.Float64})

#: The columns this adapter fills. ``decimals`` is left to the canonical model's
#: default: the figures are computed, and are stated to the accuracy the filing
#: options choose.
_PLACED_SCHEMA: Final = pl.Schema(
    {name: FACT_SCHEMA[name] for name in FACT_SCHEMA.names() if name != "decimals"}
)


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class CanonicalMapping:
    """Our estate in canonical form, with a full account of what did not fit.

    Attributes:
        canonical: The placed figures, as a canonical return.
        unplaced: Every reported cell the taxonomy has no place for
            (``UNPLACED_SCHEMA``), in OUR coordinates, with the reason.
    """

    canonical: CanonicalReturn
    unplaced: pl.DataFrame

    @property
    def placed_cells(self) -> int:
        """How many of our cells were placed."""
        return self.canonical.facts.height

    @property
    def unplaced_figures(self) -> pl.DataFrame:
        """The unplaced cells that carry a NON-ZERO figure — the real gap."""
        return self.unplaced.filter(pl.col("value") != 0)

    def unplaced_by_reason(self) -> dict[tuple[str, str], int]:
        """Non-zero unplaced figures per ``(template, reason)``, sorted."""
        counts = (
            self.unplaced_figures.group_by("template", "reason").len().sort("template", "reason")
        )
        return {(template, reason): count for template, reason, count in counts.iter_rows()}


def build_canonical_return(
    corep: COREPTemplateBundle,
    header: ReturnHeader,
    *,
    pack: TaxonomyPack | None = None,
) -> CanonicalMapping:
    """Re-address a generated Basel 3.1 COREP bundle to the taxonomy's coordinates.

    Args:
        corep: The generated COREP bundle (Basel 3.1 framework).
        header: Who is reporting and for which date. Its module must be
            ``PRA001``; its reference date selects the taxonomy version.
        pack: The taxonomy to place the figures in. Defaults to the packaged
            pack in force on the header's reference date.

    Returns:
        The canonical return of every figure that has a place, and the table of
        every cell that does not. Never raises for a condition in the data.

    Raises:
        ValueError: ``header.module`` is not ``PRA001``.
        PackNotFoundError: no ``pack`` was given and none is packaged for the
            reference date (the PRA001 taxonomy applies from 1 January 2027).
    """
    if header.module.upper() != FILING_MODULE:
        raise ValueError(
            f"The Basel 3.1 COREP estate is filed under {FILING_MODULE}, not {header.module!r}"
        )
    pack = pack or resolve_pack(header.module, header.reference_date)
    index = build_template_index(corep, None, FRAMEWORK_BASEL_3_1)
    flags = [
        number
        for number, point in enumerate(pack.datapoints)
        if point.metric in pack.metrics and pack.metrics[point.metric].data_type == _TYPE_BOOLEAN
    ]

    tables_of: dict[str, list[str]] = {}
    for table, binding in index.bindings.items():
        if table in pack.tables:
            tables_of.setdefault(binding.attribute, []).append(table)

    placed: list[pl.DataFrame] = []
    unplaced: list[pl.DataFrame] = []
    for template, sheets in index.frames.items():
        tables = tables_of.get(template, [])
        binding = next(b for b in index.bindings.values() if b.attribute == template)
        for sheet_key, frame in sheets.items():
            figures = _figures(frame)
            if figures.is_empty():
                continue
            facts, leftover = _place_sheet(
                figures,
                template=template,
                sheet_key=sheet_key,
                tables=tables,
                binding=binding,
                sheet_map=index.sheet_maps.get(binding.sheet_map or ""),
                pack=pack,
                flags=flags,
            )
            placed.append(facts)
            unplaced.append(leftover)

    facts = pl.concat(placed, how="vertical") if placed else _empty_facts()
    facts = _one_value_per_data_point(facts, pack)
    leftover = (
        pl.concat(unplaced, how="vertical") if unplaced else pl.DataFrame(schema=UNPLACED_SCHEMA)
    )
    mapping = CanonicalMapping(
        canonical=CanonicalReturn.from_frame(header, facts),
        unplaced=leftover.sort("template", "sheet", "row", "column"),
    )
    logger.info(
        "canonical return (%s %s): %d cells placed, %d unplaced (%d non-zero)",
        pack.info.module,
        pack.info.version,
        mapping.placed_cells,
        mapping.unplaced.height,
        mapping.unplaced_figures.height,
    )
    return mapping


# =============================================================================
# Private helpers
# =============================================================================


def _figures(frame: pl.DataFrame) -> pl.DataFrame:
    """One template frame as long ``(row, column, value)`` rows of reported figures.

    Only numeric columns are read, and only cells that carry a value: a null
    cell reports nothing, and a non-finite one is not a reportable figure.
    """
    if "row_ref" not in frame.columns:
        return pl.DataFrame(schema=_LONG_SCHEMA)
    numeric = [
        name
        for name in frame.columns
        if name not in _LABEL_COLUMNS and frame.schema[name].is_numeric()
    ]
    if not numeric:
        return pl.DataFrame(schema=_LONG_SCHEMA)
    return (
        frame.select(pl.col("row_ref").cast(pl.String).alias("row"), *numeric)
        .unpivot(index="row", on=numeric, variable_name="column", value_name="value")
        .cast(_LONG_SCHEMA)
        .filter(pl.col("value").is_finite())
    )


def _place_sheet(
    figures: pl.DataFrame,
    *,
    template: str,
    sheet_key: str,
    tables: list[str],
    binding: TableBinding,
    sheet_map: Mapping[str, SheetCode] | None,
    pack: TaxonomyPack,
    flags: list[int],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Place one of our sheets' figures; return ``(facts, unplaced)``.

    ``flags`` are the data points whose metric is a boolean. Our frames are
    numeric throughout and carry a yes/no cell as 1 / 0; the taxonomy takes it
    as ``true`` / ``false``. Any other number in such a cell is left as it is,
    for the structure check to report.
    """

    def none_placed(reason: str) -> tuple[pl.DataFrame, pl.DataFrame]:
        return _empty_facts(), _unplaced(figures, template, sheet_key, pl.lit(reason))

    if not tables:
        return none_placed(REASON_SHEET_UNPUBLISHED)

    sheet_code: str | None = None
    open_key: str | None = None
    if sheet_key != SINGLE_SHEET:
        if sheet_map is not None:
            codes = [code for code, entry in sheet_map.items() if sheet_key in entry.bundle_keys]
            if not codes:
                return none_placed(REASON_SHEET_UNPUBLISHED)
            if len(codes) > 1:
                return none_placed(REASON_SHEET_COARSER)
            sheet_code = codes[0]
        elif binding.per_sheet:
            open_key = _GEOGRAPHY_TOTAL_MEMBER if sheet_key == GEOGRAPHY_TOTAL_SHEET else sheet_key

    candidates = [pack.tables[table] for table in tables]
    if all(table.open_rows for table in candidates):
        return none_placed(REASON_OPEN_ROWS)
    if open_key is not None and not any(_accepts(table, open_key) for table in candidates):
        return none_placed(REASON_OPEN_KEY)

    closed = [table.code for table in candidates if not table.open_rows]
    cells = pack.cells.filter(pl.col("table").is_in(closed)).select(
        "table", "row", "column", "sheet", "datapoint"
    )
    joined = figures.with_columns(pl.lit(sheet_code, pl.String).alias("sheet")).join(
        cells, on=["row", "column", "sheet"], how="left", nulls_equal=True
    )
    is_flag = pl.col("datapoint").is_in(flags) & pl.col("value").is_in([0.0, 1.0])
    facts = joined.filter(pl.col("table").is_not_null()).select(
        "table",
        "sheet",
        pl.lit(open_key, pl.String).alias("open_key"),
        "row",
        "column",
        pl.when(is_flag).then(None).otherwise(pl.col("value")).alias("value"),
        # A flag is exactly 0 or 1 here, so its boolean reads "false" or "true".
        pl.when(is_flag)
        .then(pl.col("value").cast(pl.Boolean).cast(pl.String))
        .otherwise(None)
        .alias("text_value"),
    )
    known_rows = cells["row"].unique().to_list()
    known_columns = cells["column"].unique().to_list()
    reason = (
        pl.when(~pl.col("row").is_in(known_rows))
        .then(pl.lit(REASON_ROW))
        .when(~pl.col("column").is_in(known_columns))
        .then(pl.lit(REASON_COLUMN))
        .otherwise(pl.lit(REASON_CELL))
    )
    leftover = _unplaced(joined.filter(pl.col("table").is_null()), template, sheet_key, reason)
    return facts, leftover


def _one_value_per_data_point(facts: pl.DataFrame, pack: TaxonomyPack) -> pl.DataFrame:
    """Give the cells of one data point one value, where they agree to rounding.

    One data point shown in several cells is one fact in the submission. Each
    cell is its own template's sum, so the values can differ in the last binary
    place; the fact takes the value of the first cell in table, sheet, row,
    column order, and every cell of the data point then carries it.

    ONLY rounding is reconciled (``_SAME_FIGURE_RELATIVE`` /
    ``_SAME_FIGURE_ABSOLUTE``). Cells further apart than that are left exactly
    as generated, so ``rwa_filer``'s structure check still sees two values and
    refuses the return.

    Open-row tables are left alone, as the structure check leaves them: their
    rows share a template cell and are told apart by their key.
    """
    open_tables = [code for code, table in pack.tables.items() if table.open_rows]
    keyed = facts.join(
        pack.cells.select("table", "sheet", "row", "column", "datapoint"),
        on=["table", "sheet", "row", "column"],
        how="left",
        nulls_equal=True,
        maintain_order="left",
    )
    shown_twice = (
        pl.col("datapoint").is_not_null()
        & pl.col("value").is_not_null()
        & ~pl.col("table").is_in(open_tables)
    )
    spread = pl.col("_high") - pl.col("_low")
    allowed = pl.max_horizontal(
        pl.lit(_SAME_FIGURE_ABSOLUTE),
        _SAME_FIGURE_RELATIVE * pl.max_horizontal(pl.col("_low").abs(), pl.col("_high").abs()),
    )
    agreeing = (
        keyed.filter(shown_twice)
        .sort("table", "sheet", "row", "column", nulls_last=False)
        .group_by("datapoint", "open_key", maintain_order=True)
        .agg(
            pl.col("value").first().alias("_filed"),
            pl.col("value").min().alias("_low"),
            pl.col("value").max().alias("_high"),
        )
        .filter((spread > 0) & (spread <= allowed))
        .select("datapoint", "open_key", "_filed")
    )
    if agreeing.is_empty():
        return facts
    logger.info(
        "canonical return: %d data point(s) shown in more than one cell agreed to rounding "
        "and are filed with one value",
        agreeing.height,
    )
    return (
        keyed.join(
            agreeing,
            on=["datapoint", "open_key"],
            how="left",
            nulls_equal=True,
            maintain_order="left",
        )
        .with_columns(
            pl.when(shown_twice & pl.col("_filed").is_not_null())
            .then(pl.col("_filed"))
            .otherwise(pl.col("value"))
            .alias("value")
        )
        .select(facts.columns)
    )


def _accepts(table: Table, open_key: str) -> bool:
    """Whether a table's open axis accepts ``open_key`` as a member."""
    axis = table.open_axis
    return axis is not None and any(local_name(member) == open_key for member in axis.members)


def _unplaced(
    figures: pl.DataFrame, template: str, sheet_key: str, reason: pl.Expr
) -> pl.DataFrame:
    """Figures that found no place, in OUR coordinates, with the reason."""
    return figures.select(
        pl.lit(template).alias("template"),
        pl.lit(None if sheet_key == SINGLE_SHEET else sheet_key, pl.String).alias("sheet"),
        "row",
        "column",
        "value",
        reason.alias("reason"),
    ).cast(UNPLACED_SCHEMA)


def _empty_facts() -> pl.DataFrame:
    """An empty fact frame, in the columns this adapter fills."""
    return pl.DataFrame(schema=_PLACED_SCHEMA)
