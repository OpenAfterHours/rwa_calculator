"""
Report-cell lineage view — the drill-down panel behind a clicked cell.

Pipeline position:
    reporting.lineage.drilldown -> lineage (this module) -> cell_lineage.html

Key responsibilities:
- Say, in plain English, what the clicked cell means: the metric it aggregates,
  the criteria a leg must satisfy to be in it, and the scope of the population
  that was considered.
- Reconcile the contributing legs with the figure ACTUALLY REPORTED, making the
  Annex II §1.3 sign convention explicit rather than letting the drill-down look
  like it disagrees with the return.
- Say plainly when a cell cannot be explained by exposures at all — it derives
  from other cells, it comes from outside the ledger, or its sources are never
  produced (a reported 0.0 that is not a measured zero).

References:
- Regulation (EU) 2021/451, Annex I/II (COREP)
- docs/plans/report-cell-lineage.md §5 (Phase C)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rwa_calc.ui.views.report_templates import format_value

if TYPE_CHECKING:
    from rwa_calc.reporting.lineage import CellLineage, CellQuery, FilterTerm

logger = logging.getLogger(__name__)

# What each cell kind means, for a reader who did not write the template.
_KIND_SUMMARY: dict[str, str] = {
    "rows": "Aggregates the exposure legs listed below.",
    "formula": "Derived from other cells of this template — not directly from exposures.",
    "side_context": "Supplied from outside the exposure ledger.",
    "prior_period": "Evaluated over the previous reporting period.",
    "constant": "Not produced — this cell has no source in the calculation ledger.",
    "unbound": "Not bound to a value — reports the template's empty-cell policy.",
}

_METRIC_LABEL: dict[str, str] = {
    "sum": "Sum of",
    "mean": "Average (unweighted) of",
    "weighted_avg": "Exposure-weighted average of",
    "ratio": "Ratio of",
    "count": "Count of",
    "first_non_null": "First reported value of",
    "side_context": "Out-of-frame value",
}

_RECONCILE_TOLERANCE = 1e-6


@dataclass(frozen=True)
class LineagePanel:
    """Everything the drill-down page renders for one clicked cell."""

    run_id: str
    template_id: str
    template_title: str
    sheet: str | None
    row_ref: str
    row_name: str
    col_ref: str
    col_name: str
    kind: str
    summary: str
    metric: str | None
    criteria: tuple[str, ...]
    scope: tuple[str, ...]
    basis: str
    sign: str
    cell_display: str
    contribution_display: str | None
    reconciles: bool | None
    warning: str | None
    refs: tuple[str, ...]
    total_rows: int
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    back_url: str


def lineage_panel(
    result: CellLineage,
    *,
    run_id: str,
    template_title: str,
    col_name: str,
    back_url: str,
) -> LineagePanel:
    """Build the drill-down panel for one explained cell."""
    query = result.query
    cell_display, _ = format_value(result.cell_value)
    contribution_display = _contribution_display(result)

    return LineagePanel(
        run_id=run_id,
        template_id=query.template_id,
        template_title=template_title,
        sheet=query.sheet,
        row_ref=query.row_ref,
        row_name=query.row_name,
        col_ref=query.col_ref,
        col_name=col_name,
        kind=query.kind,
        summary=_KIND_SUMMARY.get(query.kind, ""),
        metric=_metric_phrase(query),
        criteria=criteria(query),
        scope=query.scope,
        basis=query.basis,
        sign=query.sign,
        cell_display=cell_display,
        contribution_display=contribution_display,
        reconciles=_reconciles(result),
        warning=_warning(query, result),
        refs=query.refs,
        total_rows=result.total_rows,
        columns=tuple(result.rows.columns),
        rows=_rows(result),
        back_url=back_url,
    )


def criteria(query: CellQuery) -> tuple[str, ...]:
    """The cell's row-selection criteria, in terms a reviewer can check.

    A criterion on a template-derived discriminator (a risk-weight band, a CCF
    bucket) is marked as such, so it is not mistaken for a sealed fact about the
    exposure.
    """
    return tuple(_criterion(term) for term in query.filter_terms)


# =============================================================================
# Private helpers
# =============================================================================


def _criterion(term: FilterTerm) -> str:
    suffix = " (template-derived)" if term.source == "derived" else ""
    value = term.value
    if term.op == "in" and isinstance(value, (tuple, list)):
        values = ", ".join(str(item) for item in value)
        return f"{term.column} is one of: {values}{suffix}"
    if term.op == "between" and isinstance(value, (tuple, list)) and len(value) == 2:  # noqa: PLR2004 - a band is (low, high)
        low, high = value
        return f"{term.column} is between {low} and {high}{suffix}"
    if term.op == "any_of":
        return f"matches any of several alternatives ({term.column}){suffix}"
    return f"{term.column} = {value}{suffix}"


def _metric_phrase(query: CellQuery) -> str | None:
    if query.metric is None:
        return None
    label = _METRIC_LABEL.get(query.metric, query.metric)
    if not query.metric_columns:
        return label
    return f"{label} {', '.join(query.metric_columns)}"


def _contribution_display(result: CellLineage) -> str | None:
    if result.contribution_total is None:
        return None
    display, _ = format_value(result.contribution_total)
    return display


def _reconciles(result: CellLineage) -> bool | None:
    """Whether the legs sum back to the REPORTED cell, across the sign convention.

    None when the question does not apply (no summed contribution, or a cell with
    no reported value) — never a False that merely means "not checked".
    """
    total = result.contribution_total
    value = result.cell_value
    if total is None or value is None:
        return None
    expected = -value if result.query.sign == "negated" else value
    return math.isclose(total, expected, rel_tol=1e-9, abs_tol=_RECONCILE_TOLERANCE)


def _warning(query: CellQuery, result: CellLineage) -> str | None:
    """The one thing a reader must not get wrong about this cell."""
    if query.kind == "rows" and not query.is_source_backed:
        missing = ", ".join(query.missing_columns)
        return (
            f"This cell reports {format_value(result.cell_value)[0]}, but the engine does not "
            f"produce its source column(s) ({missing}). That figure is the template's empty-cell "
            "policy, not a measured value — it does not mean the amount is zero."
        )
    if query.kind == "rows" and result.total_rows == 0:
        return (
            "No exposure legs match this cell's criteria, so there is nothing to attribute. "
            "The reported figure is the template's empty-cell policy."
        )
    if query.sign == "negated":
        return (
            "This is a deduction column: the cell is reported as a negative figure (COREP "
            "Annex II §1.3), while the legs below contribute positive magnitudes."
        )
    return None


def _rows(result: CellLineage) -> tuple[tuple[str, ...], ...]:
    """The contributing legs, formatted cell by cell."""
    return tuple(
        tuple(format_value(value)[0] for value in record.values())
        for record in result.rows.to_dicts()
    )
