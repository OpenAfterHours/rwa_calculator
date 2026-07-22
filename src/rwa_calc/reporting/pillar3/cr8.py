"""
Pillar 3 CR8 — RWEA flow statement for IRB, as a declarative TemplateSpec.

Pipeline position:
    sealed aggregator-exit ledger (IRB non-slotting subset)
        -> cr8_plans() -> SheetPlan -> cellspec.execute() -> CR8 DataFrame

The first template through the ONE executor (Phase 7 S7 pilot). Cell
semantics (unchanged from the imperative generator, golden-gated):

- Row 9 (closing RWEA)  = Sum of the current period's ``rwa_final``.
- Row 1 (opening RWEA)  = the same sum over the prior-period frame; null when
  no prior period was supplied.
- Row 8 (Other)         = the signed residual ``closing - opening`` when a
  prior period exists (a None side coerces to zero — PS1/26 Annex XXII §11),
  null otherwise.
- Rows 2-7 (per-driver flow components) stay null — they need exposure-level
  period-over-period lineage two point-in-time snapshots cannot provide.

Input selection (the IRB non-slotting subset and the lenient prior-period
column handling) deliberately stays with the generator's dispatch router:
``previous_period_results`` is an EXTERNAL prior-run frame that may predate
the sealed reporting-ledger columns, so its filtering keeps the legacy
column fallbacks until the S8 retarget records otherwise.

Lineage-instrumented (R20): ``cr8_plans`` exposes the single (current-period)
execution plan so ``reporting.lineage`` can drill into a reported cell; the
prior-period opening/residual rows are out of the current-period view (row 1 is
a ``prior_period`` cell, row 8 a ``formula`` cell — neither is row-backed).

References:
- CRR Part 8 Art. 438(h); PRA PS1/26 Annex XXII §11
- docs/plans/phase7-declarative-reporting.md §3.2 (S7)
- docs/features/report-cell-lineage.md (per-template lineage recipe)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.reporting.cellspec import CellSpec, Formula, PriorPeriod, Sum, TemplateSpec, execute
from rwa_calc.reporting.kernel import pick
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.pillar3.templates import CR8_COLUMNS, CR8_ROWS
from rwa_calc.reporting.plans import SheetPlan

if TYPE_CHECKING:
    from collections.abc import Mapping

# Single-frame lineage key: CR8 has no sheet axis, so its one plan keys under a
# canonical name (see reporting.plans / _resolve_sheet_key single_frame path).
_SHEET_KEY = "cr8"


def _other_flow(cells: Mapping[str, float | None], prior_available: bool) -> float | None:
    """Row 8 residual: ``closing - opening`` with a prior period, else null."""
    if not prior_available:
        return None
    return (cells["9"] or 0.0) - (cells["1"] or 0.0)


CR8_SPEC = TemplateSpec(
    name="cr8",
    rows=tuple(CR8_ROWS),
    column_refs=tuple(col.ref for col in CR8_COLUMNS),
    cells={
        ("1", "a"): CellSpec(PriorPeriod(Sum("rwa_final"))),
        ("8", "a"): CellSpec(Formula(refs=("9", "1"), fn=_other_flow)),
        ("9", "a"): CellSpec(Sum("rwa_final")),
    },
    empty_cell="null",
)


def irb_non_slotting_population(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    """Filter to F-IRB and A-IRB exposures (excluding slotting).

    The CR8 flow statement covers IRB credit-risk RWEA only; slotting reports on
    CR10. Presence-tolerant: with no approach carrier the population is empty
    (the sealed ledger always carries ``approach_applied``). Shared with the
    generator's dispatch router so the lineage view and the reported figure read
    the SAME population.
    """
    approach_col = pick(cols, "approach_applied", "approach")
    if not approach_col:
        return results.filter(pl.lit(value=False))
    return results.filter(pl.col(approach_col).is_in(["foundation_irb", "advanced_irb"]))


def cr8_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the single (current-period) CR8 execution plan for lineage.

    Narrows the full sealed ledger to the IRB non-slotting population itself
    (the same ``irb_non_slotting_population`` the dispatch router applies) and
    keys the one plan under the single-frame canonical key. Preserves the
    imperative generator's error contract: a missing ``rwa_final`` column records
    the CR8 error and yields no plan. No prior-period frame is threaded here —
    the current-period view leaves the opening (row 1) and residual (row 8) rows
    null, exactly as the dispatch does without a prior period.
    """
    if "rwa_final" not in cols:
        errors.append("CR8: missing RWA column")
        return {}
    frame = irb_non_slotting_population(results, cols).collect()
    return {
        _SHEET_KEY: SheetPlan(
            spec=CR8_SPEC,
            frame=frame,
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    }


def cr8_frames(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Render the current-period CR8 frame for lineage (keyed like ``cr8_plans``).

    The lineage-facing generator: it mirrors ``cr8_plans`` and executes each
    plan, so a cell's reported value and its spec are looked up under the same
    key. CR8 has no post-execute passes, so this is a plain ``execute``.
    """
    return {
        key: execute(plan.spec, plan.frame, plan.ctx)
        for key, plan in cr8_plans(results, cols, framework, errors).items()
    }


def generate_cr8(
    irb_data: pl.LazyFrame,
    prior_irb_data: pl.LazyFrame | None,
    cols: set[str],
    errors: list[str],
) -> pl.DataFrame | None:
    """Execute CR8 over the pre-filtered IRB (non-slotting) subset.

    Preserves the imperative generator's contract: a missing ``rwa_final``
    column (impossible on the sealed ledger; reachable via direct invocation
    with synthetic frames) records the CR8 error and yields no template. This
    dispatch entry threads the EXTERNAL prior-period frame (which the
    current-period lineage view cannot carry); the population narrowing is done
    by the router via ``irb_non_slotting_population``.
    """
    if "rwa_final" not in cols:
        errors.append("CR8: missing RWA column")
        return None
    ctx = ReportingContext(template_set=None, previous_period_results=prior_irb_data)
    return execute(CR8_SPEC, irb_data, ctx)
