"""
Pillar 3 CR7-A — Extent of the use of CRM techniques (IRB), declarative.

Pipeline position:
    sealed aggregator-exit ledger -> cr7a_plans() -> one SheetPlan per origin
        approach -> cellspec.execute() -> dict[approach, DataFrame]

Lineage-instrumented (R22): ``cr7a_plans`` exposes the per-approach execution
plans so ``reporting.lineage`` can drill into a reported cell. CR7-A is one of
the first two multi-sheet instrumentations since C 07.00 — its sheet axis is the
ORIGIN approach (foundation_irb / advanced_irb), so ``plans()`` and
``generate_cr7a()`` key their sheets identically. No prep and no post-execute
pass beyond the in-spec Formula (column c), so ``generate_cr7a`` is the provider
generator directly.

Cell semantics (recorded decisions, this slice):

- One frame per ORIGIN approach (``reporting_approach_origin`` foundation_irb
  / advanced_irb; an approach with no rows produces no dict entry), with
  rows keyed on the obligor's applied Art. 147 class
  (``reporting_class_origin``) — "exposures shall be disclosed in accordance
  with the exposure class applicable to the obligor, without taking into
  account any substitution effects due to the existence of a guarantee"
  (Annex XXII column a, both regimes).
- Column a = total EAD; the FCP/UFCP percentage columns divide each
  collateral-allocation sum by the row EAD x100 (b financial, d immovable
  property, e receivables, f other physical, k guarantees); c = d + e + f
  (null when all are zero, the imperative convention).
- The four funded-collateral numerators (b/d/e/f, and so c) are "capped at the
  individual exposure value" — the cap binds PER LEG, before the ratio sums it,
  via the derived ``cr7a_capped_*`` columns. Capping the summed numerator
  against the summed EAD is a DIFFERENT computation: it lets an
  over-collateralised leg subsidise an under-collateralised one on the same
  row. Column k (guarantees) carries no such clause in either instruction set
  and stays uncapped, as does COREP C 08.01/02 cols 0180-0210 reading the same
  carriers — the cap is recorded per template, not derived once (RD-2).
- Columns m and n are BOTH the actual Sum of ``rwa_final`` — the "RWEA
  without substitution effects" (m) vs "with substitution effects" (n)
  distinction the instructions draw needs a hypothetical no-substitution
  RWEA the ledger does not carry; the retired m == n approximation is
  preserved and recorded (plan §7 / F7 family — the two-leg ledger now
  makes the n-side computable; the m-side needs a pre-substitution RWA
  carrier).
- Columns g/h/i/j (other-funded-CP sub-splits), l (credit derivatives) and
  the B31 slotting pair o/p stay unbound — permanently null, the recorded
  F6 not-separately-tracked cells.

References:
- CRR Art. 453(g); PRA PS1/26 Annex XXII (UK/UKB CR7-A)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Formula,
    Ratio,
    RowPredicate,
    Sum,
    TemplateSpec,
    execute,
)
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.pillar3.templates import (
    CR7A_AIRB_ROWS,
    CR7A_FIRB_ROWS,
    get_cr7a_columns,
)
from rwa_calc.reporting.plans import SheetPlan

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_calc.reporting.pillar3.templates import P3Row

# The two CR7-A sub-templates: origin approach -> row layout.
_APPROACH_ROWS: tuple[tuple[str, tuple[P3Row, ...]], ...] = (
    ("foundation_irb", tuple(CR7A_FIRB_ROWS)),
    ("advanced_irb", tuple(CR7A_AIRB_ROWS)),
)

# FCP/UFCP percentage columns: column ref -> collateral-allocation source.
_PCT_SOURCES: dict[str, str] = {
    "b": "collateral_financial_value",
    "d": "collateral_re_value",
    "e": "collateral_receivables_value",
    "f": "collateral_other_physical_value",
    "k": "guaranteed_portion",
}

# The sources whose numerator the instructions cap at the individual exposure
# value (cols b/d/e/f — the clause repeats verbatim per column and per approach
# limb), reported through the derived per-leg column below. The UFCP source
# (col k) carries no cap clause and is absent here.
_CAPPED_SOURCES: tuple[str, ...] = (
    "collateral_financial_value",
    "collateral_re_value",
    "collateral_receivables_value",
    "collateral_other_physical_value",
)

# Prefix of the derived per-leg capped numerators added by
# ``_with_capped_collateral`` (the module-owned derived-column pattern —
# cf. ``cr5_rw_bucket``).
_CAPPED_PREFIX = "cr7a_capped_"


def _other_collateral(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """Column c = d + e + f, null when every component is zero/absent."""
    d_val = cells["d"] or 0.0
    e_val = cells["e"] or 0.0
    f_val = cells["f"] or 0.0
    if not (d_val or e_val or f_val):
        return None
    return d_val + e_val + f_val


def _row_cells(row: P3Row) -> dict[str, CellSpec] | None:
    """The column bindings for one CR7-A row (None = row stays unbound)."""
    if not row.is_total and not row.exposure_classes:
        return None
    member = RowPredicate(classes_origin=row.exposure_classes)
    cells = {
        "a": CellSpec(Sum("reporting_ead"), predicate=member, empty_cell="zero"),
        "c": CellSpec(Formula(refs=("d", "e", "f"), fn=_other_collateral)),
        "m": CellSpec(Sum("rwa_final"), predicate=member),
        "n": CellSpec(Sum("rwa_final"), predicate=member),
    }
    for col_ref, source in _PCT_SOURCES.items():
        cells[col_ref] = CellSpec(
            Ratio(_numerator(source), "reporting_ead", scale=100.0), predicate=member
        )
    return cells


def _numerator(source: str) -> str:
    """The ratio numerator for one collateral source.

    The derived per-leg capped column where the instructions cap the amount at
    the individual exposure value, else the raw carrier.
    """
    return f"{_CAPPED_PREFIX}{source}" if source in _CAPPED_SOURCES else source


@cites("CRR Art. 453")
def build_cr7a_spec(framework: str, approach: str, rows: tuple[P3Row, ...]) -> TemplateSpec:
    """Build the CR7-A TemplateSpec for one framework x origin approach.

    Carries the Art. 453(g) citation for the extent-of-CRM disclosure.
    """
    cells: dict[tuple[str, str], CellSpec] = {}
    for row in rows:
        row_cells = _row_cells(row)
        if row_cells is None:
            continue
        for col_ref, cell in row_cells.items():
            cells[(row.ref, col_ref)] = cell
    return TemplateSpec(
        name=f"cr7a:{approach}",
        rows=rows,
        column_refs=tuple(col.ref for col in get_cr7a_columns(framework)),
        cells=cells,
        predicate=RowPredicate(approaches_origin=(approach,)),
        empty_cell="null",
    )


_CR7A_SPECS: dict[tuple[str, str], TemplateSpec] = {
    (framework, approach): build_cr7a_spec(framework, approach, rows)
    for framework in ("CRR", "BASEL_3_1")
    for approach, rows in _APPROACH_ROWS
}


def cr7a_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-origin-approach CR7-A execution plans for lineage.

    Preserves ``generate_cr7a``'s contracts: missing EAD/RWA/approach columns
    record the CR7-A error and yield ``{}``; an approach with no rows produces
    no plan entry, so ``plans()`` and ``generate_cr7a()`` key their sheets
    IDENTICALLY (the origin approach). The plan frame is the FULL sealed ledger
    — each spec's own ``approaches_origin`` predicate narrows it per sheet — and
    CR7-A carries no "(-)"-labelled deduction column, so ``negative_cols`` is
    empty. The plan frame carries the derived ``cr7a_capped_*`` numerators, so
    the collateral cells' bindings read columns the frame holds.
    """
    if (
        "ead_final" not in cols
        or not ({"rwa_final", "rwa"} & cols)
        or not ({"approach_applied", "approach"} & cols)
    ):
        errors.append("CR7-A: missing required columns")
        return {}
    data = _with_capped_collateral(results, cols).collect()
    plans: dict[str, SheetPlan] = {}
    for approach, rows in _APPROACH_ROWS:
        if data.filter(pl.col("reporting_approach_origin") == approach).height == 0:
            continue
        spec = _CR7A_SPECS.get((framework, approach)) or build_cr7a_spec(framework, approach, rows)
        plans[approach] = SheetPlan(
            spec=spec, frame=data, ctx=ReportingContext(), negative_cols=frozenset()
        )
    return plans


def generate_cr7a(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute CR7-A per origin approach over the sealed ledger.

    The lineage-facing generator too (keyed like ``cr7a_plans``): it executes
    each plan, so a cell's reported value and its spec are looked up under the
    same approach key. CR7-A has no post-execute passes, so this is a plain
    ``execute``.
    """
    return {
        approach: execute(plan.spec, plan.frame, plan.ctx)
        for approach, plan in cr7a_plans(results, cols, framework, errors).items()
    }


def _with_capped_collateral(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    """Add the per-leg capped collateral numerators ``cr7a_capped_*``.

    PS1/26 Annex XXII / the CRR Pillar 3 IRB instructions cap each collateral
    amount "at the individual exposure value", so the cap binds on the LEG,
    before the ratio sums it — ``Ratio`` divides sum(numerator) by
    sum(denominator), and capping the aggregate instead would let an
    over-collateralised leg subsidise an under-collateralised one on the same
    row. ``when(value > ead)`` rather than ``min_horizontal`` (which drops
    nulls, so a null valuation would report as the full EAD): a null valuation
    stays null and a leg with no sealed EAD stays uncapped. A source the frame
    does not carry is skipped — its column stays absent and the cell resolves
    null exactly as the raw binding did.
    """
    if "reporting_ead" not in cols:
        return results
    ead = pl.col("reporting_ead")
    capped = [
        pl.when(pl.col(source) > ead)
        .then(ead)
        .otherwise(pl.col(source))
        .alias(f"{_CAPPED_PREFIX}{source}")
        for source in _CAPPED_SOURCES
        if source in cols
    ]
    return results.with_columns(capped) if capped else results
