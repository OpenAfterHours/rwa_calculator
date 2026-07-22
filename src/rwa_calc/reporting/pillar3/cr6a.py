"""
Pillar 3 CR6-A — Scope of the use of IRB and SA approaches, declarative.

Pipeline position:
    sealed aggregator-exit ledger -> build_cr6a_spec(framework)
        -> cellspec.execute() -> CR6-A DataFrame

Cell semantics (recorded keying decision, this slice):

- Rows key on the ORIGINATION class (the sealed raw ``exposure_class``
  column, via tolerant per-value limbs) — deliberately NOT the applied
  Art. 112 basis (``reporting_class_origin``): the CR6-A row axis is
  Art. 147-shaped (central governments / institutions / corporates /
  retail splits / equity) with no defaulted sink row, so the applied basis
  would silently drop defaulted-SA EAD out of every class row while the
  Total row (whole population) kept it. An SA-treated defaulted corporate
  belongs to the "Corporates" scope row — Art. 452(b) discloses the extent
  of IRB use across the obligor population, not the Art. 112 treatment
  assignment. Recorded in the plan §6 alongside F3.
- Column a = EAD on the IRB-family origin approaches (foundation_irb /
  advanced_irb / slotting); column b = EAD across all approaches; c/d are
  the SA/IRB percentage pair derived from a and b (the SA share is exactly
  b - a — the two approach subsets partition the row); e (% subject to a
  roll-out plan) is the recorded constant 0.0 — roll-out plans are not
  pipeline data.
- Empty class rows report a/b = 0.0 with null percentages; the Total row
  spans the whole frame.

Lineage-instrumented (R20): ``cr6a_plans`` exposes the single (no sheet axis)
execution plan so ``reporting.lineage`` can drill into a reported cell.

References:
- CRR Art. 452(b); PRA PS1/26 Annex XXII (UK/UKB CR6-A)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Formula,
    RowPredicate,
    Sum,
    TemplateSpec,
    execute,
)
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.pillar3.templates import CR6A_COLUMNS, get_cr6a_rows
from rwa_calc.reporting.plans import SheetPlan

if TYPE_CHECKING:
    from collections.abc import Mapping

    import polars as pl

    from rwa_calc.reporting.pillar3.templates import P3Row

# Single-frame lineage key: CR6-A has no sheet axis, so its one plan keys under
# a canonical name (see reporting.plans / _resolve_sheet_key single_frame path).
_SHEET_KEY = "cr6a"

# The origin approaches counted as "IRB" for scope-of-use purposes
# (slotting is an IRB permission — templates and the retired imperative agree).
_IRB_FAMILY: tuple[str, ...] = ("foundation_irb", "advanced_irb", "slotting")


def _sa_percentage(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """Column c = (b - a) / b x100 — the SA (non-IRB) share of the row."""
    total = cells["b"]
    if total is None or total <= 0:
        return None
    return (total - (cells["a"] or 0.0)) / total * 100.0


def _irb_percentage(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """Column d = a / b x100 — the IRB share of the row."""
    total = cells["b"]
    if total is None or total <= 0:
        return None
    return (cells["a"] or 0.0) / total * 100.0


def _rollout_percentage(_cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """Column e — roll-out plans are not pipeline data; recorded 0.0."""
    return 0.0


def _membership(row: P3Row) -> RowPredicate | None:
    """Row membership on the ORIGINATION class (tolerant per-value limbs
    over the sealed raw ``exposure_class`` column — see module docstring)."""
    if row.is_total:
        return RowPredicate()
    if not row.exposure_classes:
        return None
    limbs = tuple(
        RowPredicate(equals=(("exposure_class", value),)) for value in row.exposure_classes
    )
    return limbs[0] if len(limbs) == 1 else RowPredicate(any_of=limbs)


@cites("CRR Art. 452")
def build_cr6a_spec(framework: str) -> TemplateSpec:
    """Build the CR6-A TemplateSpec for one framework's row set.

    Carries the Art. 452(b) citation for the scope-of-IRB-use disclosure.
    """
    rows = tuple(get_cr6a_rows(framework))
    cells: dict[tuple[str, str], CellSpec] = {}
    for row in rows:
        member = _membership(row)
        if member is None:
            continue
        irb_member = (
            RowPredicate(approaches_origin=_IRB_FAMILY)
            if row.is_total
            else RowPredicate(
                approaches_origin=_IRB_FAMILY, any_of=member.any_of, equals=member.equals
            )
        )
        cells[(row.ref, "a")] = CellSpec(
            Sum("reporting_ead"), predicate=irb_member, empty_cell="zero"
        )
        cells[(row.ref, "b")] = CellSpec(Sum("reporting_ead"), predicate=member, empty_cell="zero")
        cells[(row.ref, "c")] = CellSpec(Formula(refs=("a", "b"), fn=_sa_percentage))
        cells[(row.ref, "d")] = CellSpec(Formula(refs=("a", "b"), fn=_irb_percentage))
        cells[(row.ref, "e")] = CellSpec(Formula(refs=(), fn=_rollout_percentage))
    return TemplateSpec(
        name="cr6a",
        rows=rows,
        column_refs=tuple(col.ref for col in CR6A_COLUMNS),
        cells=cells,
        empty_cell="null",
    )


_CR6A_SPECS: dict[str, TemplateSpec] = {
    framework: build_cr6a_spec(framework) for framework in ("CRR", "BASEL_3_1")
}


def cr6a_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the single CR6-A execution plan (the lineage seam).

    CR6-A has no sheet axis and runs over the FULL sealed ledger (its rows key
    on the raw origination ``exposure_class``), so the one plan keys under the
    single-frame canonical key. Preserves the imperative generator's error
    contract: missing EAD, class or approach columns record the CR6-A error and
    yield no plan. There is no post-execute pass, so ``negative_cols`` is empty.
    """
    if (
        "ead_final" not in cols
        or "exposure_class" not in cols
        or not ({"approach_applied", "approach"} & cols)
    ):
        errors.append("CR6-A: missing required columns")
        return {}
    spec = _CR6A_SPECS.get(framework) or build_cr6a_spec(framework)
    return {
        _SHEET_KEY: SheetPlan(
            spec=spec,
            frame=results.collect(),
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    }


def generate_cr6a(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute CR6-A over the full sealed ledger (keyed like ``cr6a_plans``).

    The thin consumer of ``cr6a_plans``: it executes each plan under the same
    key, so a cell's reported value and its spec agree. CR6-A has no
    post-execute pass, so this is a plain ``execute``. The dispatch router
    unwraps the single-frame dict for the ``Pillar3TemplateBundle.cr6a`` field.
    """
    return {
        key: execute(plan.spec, plan.frame, plan.ctx)
        for key, plan in cr6a_plans(results, cols, framework, errors).items()
    }
