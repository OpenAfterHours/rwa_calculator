"""
Report-template viewer — the presentation view over the generated templates.

Pipeline position:
    {COREPTemplateBundle, Pillar3TemplateBundle} -> reporting.catalog
        -> report_templates (this module) -> report_templates.html

Key responsibilities:
- Turn one template sheet into rendered rows and cells: formatted values, a
  null-vs-zero distinction the grid must not flatten, and the grouped column
  header band.
- Stamp every value cell with its **cell key** (``template_id``, ``sheet``,
  ``row_ref``, ``col_ref``) — the address a report cell is known by, and the
  handle the lineage drill-down attaches to.

A cell is rendered exactly as the generator produced it. Nothing here
recomputes, re-signs, or re-fills a value: a null cell is a null cell (an
inert/empty row, or a structurally never-produced source), and a 0.0 cell is a
reported zero. Conflating the two would be a reporting error, so the two render
differently.

References:
- Regulation (EU) 2021/451, Annex I/II (COREP); CRR Part 8 (Pillar 3)
- docs/plans/report-cell-lineage.md §3 (Phase A — the template viewer)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rwa_calc.reporting import catalog, lineage

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle

logger = logging.getLogger(__name__)

# What an empty cell renders as. The templates carry two deliberate empty
# semantics (COREP reports 0.0; Pillar 3 reports null — a recorded drift, never
# unified), so the grid must show them differently.
_NULL_DISPLAY = "—"

_THOUSAND = 1000.0


@dataclass(frozen=True)
class TemplateCell:
    """One value cell, addressed by its column ref and rendered for display."""

    ref: str
    display: str
    is_null: bool


@dataclass(frozen=True)
class TemplateRow:
    """One template row: its regulatory row ref, its name, and its value cells."""

    row_ref: str
    row_name: str
    cells: tuple[TemplateCell, ...]


@dataclass(frozen=True)
class ColumnGroup:
    """A span of consecutive columns sharing a logical group (the header band)."""

    name: str
    span: int


@dataclass(frozen=True)
class TemplatePage:
    """Everything the viewer page renders for one run + one selected sheet.

    ``has_lineage`` says whether this template's cells can be explained (see
    ``reporting.lineage``). Cells are only offered as drill-down links where
    there is a truthful answer to give — never a link that leads to a shrug.
    """

    run_id: str
    framework: str
    templates: tuple[catalog.TemplateInfo, ...]
    selected: catalog.TemplateInfo | None
    sheet: str | None
    groups: tuple[ColumnGroup, ...]
    columns: tuple[catalog.ColumnHeader, ...]
    rows: tuple[TemplateRow, ...]
    has_lineage: bool = False


def template_page(
    corep: COREPTemplateBundle | None,
    pillar3: Pillar3TemplateBundle | None,
    *,
    run_id: str,
    framework: str,
    template_id: str | None = None,
    sheet: str | None = None,
) -> TemplatePage:
    """Build the viewer page for a run, selecting one template sheet.

    ``template_id`` defaults to the first template with content, and ``sheet``
    to that template's first sheet — so the page is reachable without knowing
    what a run produced. An unknown template or sheet renders the picker with no
    grid rather than raising: the templates a run produced are data, not a
    contract.
    """
    infos = catalog.template_index(corep, pillar3)
    if not infos:
        return TemplatePage(
            run_id=run_id,
            framework=framework,
            templates=(),
            selected=None,
            sheet=None,
            groups=(),
            columns=(),
            rows=(),
        )

    chosen = template_id or infos[0].id
    view = catalog.template_sheet(corep, pillar3, chosen, sheet)
    if view is None:
        logger.warning("template viewer: no sheet for template=%s sheet=%s", chosen, sheet)
        return TemplatePage(
            run_id=run_id,
            framework=framework,
            templates=infos,
            selected=None,
            sheet=None,
            groups=(),
            columns=(),
            rows=(),
        )

    return TemplatePage(
        run_id=run_id,
        framework=framework,
        templates=infos,
        selected=view.info,
        sheet=view.sheet,
        groups=column_groups(view.columns),
        columns=view.columns,
        rows=_rows(view),
        has_lineage=lineage.is_instrumented(view.info.id),
    )


def column_groups(columns: tuple[catalog.ColumnHeader, ...]) -> tuple[ColumnGroup, ...]:
    """Collapse consecutive same-group columns into header-band spans.

    Returns ``()`` when no column declares a group — the band is then omitted
    rather than rendered as one meaningless empty span.
    """
    if not any(col.group for col in columns):
        return ()
    groups: list[ColumnGroup] = []
    for col in columns:
        if groups and groups[-1].name == col.group:
            groups[-1] = ColumnGroup(col.group, groups[-1].span + 1)
        else:
            groups.append(ColumnGroup(col.group, 1))
    return tuple(groups)


def format_value(value: object) -> tuple[str, bool]:
    """Render one cell value; returns ``(display, is_null)``.

    Null and non-finite (NaN / +-Inf) render as the null glyph — a blank cell,
    matching the Excel export. A reported 0.0 renders as ``0``, distinctly from
    null. Magnitudes carry thousands separators; sub-unit values (rates, PDs)
    keep 4 decimal places so they do not round to nothing.
    """
    if value is None:
        return _NULL_DISPLAY, True
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value), False
    number = float(value)
    if not math.isfinite(number):
        return _NULL_DISPLAY, True
    if number == 0.0:
        return "0", False
    magnitude = abs(number)
    if magnitude >= _THOUSAND:
        return f"{number:,.0f}", False
    if magnitude >= 1.0:
        return f"{number:,.2f}", False
    return f"{number:.4f}", False


# =============================================================================
# Private helpers
# =============================================================================


def _rows(view: catalog.TemplateSheet) -> tuple[TemplateRow, ...]:
    """The sheet's rows, each cell formatted and keyed by its column ref."""
    refs = [col.ref for col in view.columns]
    rows: list[TemplateRow] = []
    for record in view.frame.to_dicts():
        cells: list[TemplateCell] = []
        for ref in refs:
            display, is_null = format_value(record.get(ref))
            cells.append(TemplateCell(ref=ref, display=display, is_null=is_null))
        rows.append(
            TemplateRow(
                row_ref=str(record.get("row_ref") or ""),
                row_name=str(record.get("row_name") or ""),
                cells=tuple(cells),
            )
        )
    return tuple(rows)
