"""
Report-cell lineage — which exposures and rules produced this reported figure.

Pipeline position:
    sealed aggregator-exit ledger -> <template>_plans() -> TemplateSpec + frame
        -> lineage (this module) -> {api/rest, ui/views}

Key responsibilities:
- Describe a cell: read its ``CellSpec`` off the template's own ``TemplateSpec``
  and report what it MEANS — the metric, the filter criteria, the scope of the
  population, the sign convention, and which of the six cell kinds it is.
- Drill into a cell: return the ledger legs that fed it, by running that same
  ``RowPredicate`` over the same prepared frame the generator executed.

**Lineage is a query, never a stored index.** A cell's lineage IS its spec:
``spec.predicate`` conjoined with ``spec.cells[(row, col)].predicate``. So this
module reads the specs the generators execute rather than declaring its own —
a second copy of a template's row selection could silently disagree with the
figure actually reported, which is the one thing a lineage feature may never do.
Materialising cell -> row-id memberships would also multiply the ledger by the
cell count per template, for no gain.

Two honesty rules follow from the module post-passes (``_null_empty_rows``,
``_negate_deduction_cols``), which run AFTER ``execute()``:
1. ``cell_value`` is read from the GENERATED template — the number the user
   clicked is ground truth and is never recomputed here.
2. ``contribution_total`` is the sum over the returned rows, and
   ``CellQuery.sign`` records the Annex II §1.3 negation, so the two can be
   reconciled explicitly instead of appearing to disagree.

Coverage: templates whose execution plan is exposed (``LINEAGE_PLANS``). A
template that is not instrumented resolves to ``None`` — a clean "no lineage",
never a re-derived guess.

References:
- Regulation (EU) 2021/451, Annex I/II (COREP); CRR Part 8 (Pillar 3)
- docs/plans/report-cell-lineage.md §4 (Phase B)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import polars as pl

from rwa_calc.reporting.cellspec import (
    Count,
    FirstNonNull,
    Formula,
    Mean,
    PriorPeriod,
    Ratio,
    RowPredicate,
    SafeSum,
    SideContext,
    Sum,
    WeightedAvg,
)
from rwa_calc.reporting.corep.c07 import c07_plans, generate_c07
from rwa_calc.reporting.kernel import available_columns

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from rwa_calc.reporting.cellspec import CellSpec, ValueBinding
    from rwa_calc.reporting.corep.c07 import SheetPlan
    from rwa_calc.reporting.metadata import ResultsSource

logger = logging.getLogger(__name__)

# The sealed edge every lineage query runs on.
BASIS = "aggregator_exit"

# What a contributing leg is shown with: identity, the two-leg guarantee ledger
# (a guaranteed exposure is physically split, so a "row" is a LEG), and the
# figures a reviewer checks the cell against. Projected where present.
_ROW_COLUMNS: tuple[str, ...] = (
    "exposure_reference",
    "source_exposure_reference",
    "reporting_leg_role",
    "reporting_class",
    "reporting_class_origin",
    "reporting_method",
    "reporting_ead",
    "risk_weight",
    "rwa_final",
    "guarantee_rwa_benefit",
)

type CellKind = Literal["rows", "formula", "side_context", "prior_period", "constant", "unbound"]


@dataclass(frozen=True)
class FilterTerm:
    """One row-selection criterion, in the terms a reviewer can check.

    ``source`` says whether the column is a sealed ledger fact (``ledger``) or a
    discriminator the template derives for its own row structure (``derived`` —
    e.g. C 07.00's risk-weight band or CCF bucket).
    """

    column: str
    op: Literal["eq", "in", "between", "any_of"]
    value: object
    source: Literal["ledger", "derived"]


@dataclass(frozen=True)
class CellQuery:
    """What a cell MEANS — read off the template spec; independent of any run."""

    template_id: str
    sheet: str | None
    row_ref: str
    col_ref: str
    row_name: str
    kind: CellKind
    metric: str | None
    metric_columns: tuple[str, ...]
    filter_terms: tuple[FilterTerm, ...]
    scope: tuple[str, ...]
    refs: tuple[str, ...] = ()
    basis: str = BASIS
    sign: Literal["positive", "negated"] = "positive"
    # Metric columns the ledger does not carry. When this is the WHOLE of
    # ``metric_columns``, the cell sums a source the engine never produces — so
    # its reported 0.0 is a structural artefact of the COREP zero policy, not a
    # measured zero (the Phase 7 F6 permanently-null cells). Saying so is the
    # difference between "we computed zero" and "we cannot compute this".
    missing_columns: tuple[str, ...] = ()

    @property
    def is_source_backed(self) -> bool:
        """Whether any metric column this cell sums actually reaches the ledger."""
        return self.kind != "rows" or bool(set(self.metric_columns) - set(self.missing_columns))


@dataclass(frozen=True)
class CellLineage:
    """The lineage of one cell for one run."""

    query: CellQuery
    run_id: str
    cell_value: float | None
    contribution_total: float | None
    total_rows: int
    rows: pl.DataFrame


@dataclass(frozen=True)
class _Provider:
    """How one template exposes its execution plans, and what its scope is."""

    plans: Callable[[pl.LazyFrame, set[str], str, list[str]], dict[str, SheetPlan]]
    generate: Callable[[pl.LazyFrame, set[str], str, list[str]], dict[str, pl.DataFrame]]
    scope: tuple[str, ...]
    sheet_label: str


# Instrumented templates. Adding one = expose its `<t>_plans()` (the same
# extraction c07 made) and register it here. Templates absent from this map have
# no lineage — including C 34.x / CCR1-8, which are still imperative and have no
# TemplateSpec to read.
LINEAGE_PLANS: dict[str, _Provider] = {
    "c07_00": _Provider(
        plans=c07_plans,
        generate=generate_c07,
        scope=(
            "Standardised-approach legs, plus BOTH counterparty-credit-risk "
            "populations — FCCM SFT rows and SA-CCR derivative netting sets. The CCR "
            "rows are admitted by risk type (not by the approach label, which the "
            "output floor relabels), and Annex II breaks them out in rows 0090-0130",
            "Specialised lending is merged into corporate (Art. 112(1)(g): under the "
            "standardised approach SL is a corporate sub-type)",
        ),
        sheet_label="obligor class",
    ),
}


def is_instrumented(template_id: str) -> bool:
    """Whether this template's cells can be explained.

    A template is instrumented when it exposes its execution plans, so lineage
    can read the very spec the generator executes. Consumers use this to offer a
    drill-down only where there is a truthful answer to give.
    """
    return template_id in LINEAGE_PLANS


@dataclass(frozen=True)
class SheetLineage:
    """A lineage resolver bound to one run and one template sheet.

    Holds the sheet's execution plan and its RENDERED frame, so explaining many
    cells of a sheet costs one plan build and one generation — not one per cell.
    """

    template_id: str
    sheet: str | None
    _provider: _Provider
    _plan: SheetPlan
    _rendered: pl.DataFrame | None
    _sealed: set[str]

    def has_cell(self, row_ref: str, col_ref: str) -> bool:
        """Whether the cell is on this template at all."""
        spec = self._plan.spec
        return any(row.ref == row_ref for row in spec.rows) and col_ref in spec.column_refs

    def query(self, row_ref: str, col_ref: str) -> CellQuery | None:
        """What the cell MEANS — read off the spec the generator executes."""
        if not self.has_cell(row_ref, col_ref):
            return None
        return describe_cell(
            self._provider,
            self._plan,
            self.template_id,
            self.sheet,
            row_ref,
            col_ref,
            sealed=self._sealed,
        )

    def cell(
        self, row_ref: str, col_ref: str, *, run_id: str = "", offset: int = 0, limit: int = 50
    ) -> CellLineage | None:
        """The cell's full lineage: its meaning, its reported value, its legs."""
        query = self.query(row_ref, col_ref)
        if query is None:
            return None
        plan = self._plan
        matched = _matching_rows(plan, plan.spec.cells.get((row_ref, col_ref)), query)
        return CellLineage(
            query=query,
            run_id=run_id,
            cell_value=_rendered_value(self._rendered, row_ref, col_ref),
            contribution_total=_contribution(matched, query.metric, query.metric_columns),
            total_rows=matched.height,
            rows=_project(matched, query.metric_columns, offset=offset, limit=limit),
        )


def sheet_lineage(
    source: ResultsSource, template_id: str, sheet: str | None = None
) -> SheetLineage | None:
    """Bind a lineage resolver to one template sheet of one run.

    ``sheet`` defaults to the template's first sheet. Returns ``None`` when the
    template is not instrumented, produced nothing for this run, or has no such
    sheet — never a fallback computation.
    """
    provider = LINEAGE_PLANS.get(template_id)
    if provider is None:
        return None

    results = source.scan_results()
    cols = available_columns(results)
    errors: list[str] = []
    plans = provider.plans(results, cols, source.framework, errors)
    if not plans:
        return None

    key = next(iter(plans)) if sheet is None else sheet
    plan = plans.get(key)
    if plan is None:
        return None

    # The REPORTED frame — the figures the user actually saw. Generated once and
    # reused for every cell of this sheet; a cell's value is read from it, never
    # recomputed (the two post-execute passes live here).
    rendered = provider.generate(results, cols, source.framework, errors).get(key)
    return SheetLineage(
        template_id=template_id,
        sheet=key,
        _provider=provider,
        _plan=plan,
        _rendered=rendered,
        _sealed=cols,
    )


def drilldown(
    source: ResultsSource,
    template_id: str,
    row_ref: str,
    col_ref: str,
    *,
    run_id: str = "",
    sheet: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> CellLineage | None:
    """Explain one reported cell: what it means, and which legs produced it.

    Convenience over ``sheet_lineage`` for a single cell. Returns ``None`` when
    the template is not instrumented, the sheet is unknown, or the cell is not on
    the template — never a fallback computation.
    """
    resolver = sheet_lineage(source, template_id, sheet)
    if resolver is None:
        return None
    return resolver.cell(row_ref, col_ref, run_id=run_id, offset=offset, limit=limit)


def describe_cell(  # noqa: PLR0913 - the cell's full identity plus its two sources
    provider: _Provider,
    plan: SheetPlan,
    template_id: str,
    sheet: str | None,
    row_ref: str,
    col_ref: str,
    *,
    sealed: set[str],
) -> CellQuery:
    """Read one cell's meaning off the template spec the generator executes."""
    cell = plan.spec.cells.get((row_ref, col_ref))
    binding = cell.binding if cell is not None else None
    kind, metric, metric_columns, refs = _binding_facts(binding)

    terms: list[FilterTerm] = []
    if kind == "rows":
        for predicate in (plan.spec.predicate, cell.predicate if cell is not None else None):
            terms.extend(_terms(predicate, sealed))

    scope = provider.scope
    if sheet is not None:
        scope = (*scope, f"Sheet: {provider.sheet_label} = {sheet}")

    # The executor resolves a binding against the PREPARED frame's columns, so
    # that frame — not the raw sealed set — decides whether a source is present.
    present = set(plan.frame.columns)
    missing = tuple(col for col in metric_columns if col not in present) if kind == "rows" else ()

    row_name = next((row.name for row in plan.spec.rows if row.ref == row_ref), "")
    return CellQuery(
        template_id=template_id,
        sheet=sheet,
        row_ref=row_ref,
        col_ref=col_ref,
        row_name=row_name,
        kind=kind,
        metric=metric,
        metric_columns=metric_columns,
        filter_terms=tuple(terms),
        scope=scope,
        refs=refs,
        sign="negated" if col_ref in plan.negative_cols else "positive",
        missing_columns=missing,
    )


# =============================================================================
# Private helpers
# =============================================================================


def _binding_facts(
    binding: ValueBinding | None,
) -> tuple[CellKind, str | None, tuple[str, ...], tuple[str, ...]]:
    """(kind, metric, metric columns, formula refs) for one value binding.

    The six kinds fall straight out of the binding vocabulary — which is what
    lets the drill-down answer honestly for EVERY cell, not just the summable
    ones. A ``Formula`` with no refs is a constant (the recorded structural-null
    and fixed-zero cells: sources the engine never produces), so it is reported
    as ``constant`` rather than as a derivation of nothing.
    """
    if binding is None:
        return "unbound", None, (), ()
    if isinstance(binding, Formula):
        return ("formula" if binding.refs else "constant", None, (), binding.refs)
    if isinstance(binding, SideContext):
        return "side_context", "side_context", (binding.key,), ()
    if isinstance(binding, PriorPeriod):
        _kind, metric, columns, _refs = _binding_facts(binding.binding)
        return "prior_period", metric, columns, ()
    if isinstance(binding, Sum):
        return "rows", "sum", (binding.col,), ()
    if isinstance(binding, SafeSum):
        return "rows", "sum", binding.cols, ()
    if isinstance(binding, Mean):
        return "rows", "mean", (binding.col,), ()
    if isinstance(binding, WeightedAvg):
        return "rows", "weighted_avg", (binding.col, binding.weight), ()
    if isinstance(binding, Ratio):
        return "rows", "ratio", (binding.numerator, binding.denominator), ()
    if isinstance(binding, Count):
        return "rows", "count", (binding.col,) if binding.distinct else (), ()
    if isinstance(binding, FirstNonNull):
        return "rows", "first_non_null", (binding.col,), ()
    raise TypeError(f"unknown value binding: {type(binding).__name__}")


def _terms(predicate: RowPredicate | None, sealed: set[str]) -> list[FilterTerm]:
    """Flatten a row predicate into reviewable criteria."""
    if predicate is None:
        return []

    def term(
        column: str, op: Literal["eq", "in", "between", "any_of"], value: object
    ) -> FilterTerm:
        return FilterTerm(
            column=column,
            op=op,
            value=value,
            source="ledger" if column in sealed else "derived",
        )

    terms: list[FilterTerm] = []
    if predicate.classes:
        terms.append(term("reporting_class", "in", predicate.classes))
    if predicate.classes_origin:
        terms.append(term("reporting_class_origin", "in", predicate.classes_origin))
    if predicate.method is not None:
        terms.append(term("reporting_method", "eq", predicate.method))
    if predicate.approaches_origin:
        terms.append(term("reporting_approach_origin", "in", predicate.approaches_origin))
    if predicate.leg_role is not None:
        terms.append(term("reporting_leg_role", "eq", predicate.leg_role))
    if predicate.on_balance_sheet is not None:
        terms.append(term("reporting_on_balance_sheet", "eq", predicate.on_balance_sheet))
    if predicate.is_defaulted is not None:
        terms.append(term("is_defaulted", "eq", predicate.is_defaulted))
    if predicate.subclass is not None:
        terms.append(term("reporting_subclass", "eq", predicate.subclass))
    if predicate.rw_between is not None:
        terms.append(term("reporting_rw", "between", predicate.rw_between))
    terms.extend(term(column, "eq", value) for column, value in predicate.equals)
    terms.extend(term(column, "between", (low, high)) for column, low, high in predicate.between)
    if predicate.any_of:
        terms.append(
            term(
                "any_of",
                "any_of",
                tuple(tuple(_terms(limb, sealed)) for limb in predicate.any_of),
            )
        )
    return terms


def _matching_rows(plan: SheetPlan, cell: CellSpec | None, query: CellQuery) -> pl.DataFrame:
    """The legs the cell aggregates — the SAME predicate the generator ran.

    A cell that is not row-backed (formula / side context / constant / unbound)
    has no contributing legs; it returns an empty frame rather than a plausible
    but wrong row set.
    """
    if query.kind != "rows" or cell is None:
        return plan.frame.clear()
    frame = plan.frame
    for predicate in (plan.spec.predicate, cell.predicate):
        if predicate is not None:
            frame = predicate.apply(frame)
    return frame


def _contribution(
    rows: pl.DataFrame, metric: str | None, metric_cols: Sequence[str]
) -> float | None:
    """The rows' contribution, where the metric is a sum.

    Sums every PRESENT metric column (a ``SafeSum`` cell adds several — C 07.00
    col 0030 sums the SCRA and GCRA provisions), matching the executor's
    semantics. Only summed metrics reconcile row-by-row to the cell; an average
    or a ratio does not, and is left None rather than reported as a misleading
    total. None when no metric column reaches the ledger (a permanently-null
    cell), which is not the same as a total of zero.
    """
    if metric != "sum":
        return None
    present = [col for col in metric_cols if col in rows.columns]
    if not present:
        return None
    total = sum(float(rows[col].fill_null(0.0).sum() or 0.0) for col in present)
    return float(total)


def _project(
    rows: pl.DataFrame, metric_cols: Sequence[str], *, offset: int, limit: int
) -> pl.DataFrame:
    """The explanatory projection, biggest contributor first."""
    present = [col for col in metric_cols if col in rows.columns]
    wanted = dict.fromkeys(
        [col for col in _ROW_COLUMNS if col in rows.columns] + present,
    )
    projected = rows.select(list(wanted))
    if present:
        projected = projected.sort(present[0], descending=True, nulls_last=True)
    return projected.slice(max(0, offset), max(1, limit))


def _rendered_value(frame: pl.DataFrame | None, row_ref: str, col_ref: str) -> float | None:
    """The cell AS REPORTED — read from the generated template, never recomputed."""
    if frame is None or col_ref not in frame.columns:
        return None
    match = frame.filter(pl.col("row_ref") == row_ref)
    if match.height == 0:
        return None
    value = match[col_ref][0]
    return float(value) if value is not None else None
