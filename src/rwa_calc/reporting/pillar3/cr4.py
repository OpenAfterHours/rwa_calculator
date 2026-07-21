"""
Pillar 3 CR4 — SA exposure and CRM effects, as a declarative TemplateSpec.

Pipeline position:
    sealed aggregator-exit ledger -> build_cr4_spec(framework)
        -> cellspec.execute() -> CR4 DataFrame

Cell semantics (the recorded F3 class-basis decision —
docs/plans/phase7-declarative-reporting.md §6):

- The template narrows to the ORIGIN standardised population
  (``reporting_approach_origin`` — the same membership as the retired
  ``approach_applied`` filter; a post-substitution APPROACH retarget remains
  an open F-decision, matching OV1) MINUS the non-credit-risk synthetic legs.
  CR4 is SA CREDIT risk excluding counterparty credit risk and settlement
  risk (disclosed in CCR1-CCR8), so ``sa_scope.sa_credit_risk_population``
  drops the SA-CCR / FCCM-SFT netting sets, default-fund and failed-trade
  legs BEFORE execution — over ALL columns, so a row's RWEA (col e) never
  covers exposure the on/off-balance-sheet columns (a-d) omit — and
  reclassifies the ``facility_undrawn`` commitment leg to off-balance-sheet.
  See ``pillar3/sa_scope.py`` for the recorded population/BS decision.
- Columns a/b ("exposures before CF/CCF and CRM": gross drawn+interest /
  nominal+undrawn) key each class row on ``reporting_class_origin`` — the
  obligor's applied Art. 112 class, the COREP C 07.00 column 0010 "original
  exposure" basis (Annex II ¶56 first-step assignment). Uniform across a
  guaranteed exposure's physical legs, so leg gross amounts re-sum to the
  obligor's original exposure.
- Columns c/d (post-CF/post-CRM exposure value), e (RWEAs) and f (density
  e/(c+d)) key on ``reporting_class`` — the post-substitution class
  (C 07.00 column 0200 basis: the covered leg lands in the protection
  provider's row per Annex II ¶56A/¶65 and EBA Q&A 2018_4093). Defaulted
  exposures sit in row 10 under BOTH bases (Art. 112(2) assessment order).
- Rows with no mapped pipeline class (11 high risk, 13 short-term claims,
  14 CIU; B31 9a-9e RE memo sub-rows) stay unbound -> all-null.
- Bound cells a-e report 0.0 for an empty subset (per-cell zero override on
  the Pillar 3 null template); density f is a Formula e/(c+d) so its
  denominator is exactly the on- plus off-BS post amounts, null when zero.

References:
- CRR Art. 444(e); PRA PS1/26 Annex XX (UK/UKB CR4 instructions)
- COREP Annex II C 07.00 ¶40-43, ¶56/56A/¶65 (two-step class assignment)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8, decision F3)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Formula,
    RowPredicate,
    SafeSum,
    Sum,
    TemplateSpec,
    execute,
)
from rwa_calc.reporting.pillar3.sa_scope import sa_credit_risk_population
from rwa_calc.reporting.pillar3.templates import get_cr4_columns, get_cr4_rows

if TYPE_CHECKING:
    from collections.abc import Mapping

    import polars as pl

    from rwa_calc.reporting.pillar3.templates import P3Row


def _density(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """Column f = e / (c + d) — RWEA density over the post-CRM amounts."""
    denominator = (cells["c"] or 0.0) + (cells["d"] or 0.0)
    if denominator <= 0 or cells["e"] is None:
        return None
    return cells["e"] / denominator


def _row_cells(row: P3Row) -> dict[str, CellSpec] | None:
    """The column bindings for one CR4 row (None = row stays unbound/null)."""
    if not row.is_total and not row.exposure_classes:
        return None
    classes = row.exposure_classes  # () on the total row -> no class term
    return {
        "a": CellSpec(
            SafeSum(("reporting_gross_drawn", "reporting_gross_interest")),
            predicate=RowPredicate(classes_origin=classes, on_balance_sheet=True),
            empty_cell="zero",
        ),
        "b": CellSpec(
            SafeSum(("reporting_gross_nominal", "reporting_gross_undrawn")),
            predicate=RowPredicate(classes_origin=classes, on_balance_sheet=False),
            empty_cell="zero",
        ),
        "c": CellSpec(
            Sum("reporting_ead"),
            predicate=RowPredicate(classes=classes, on_balance_sheet=True),
            empty_cell="zero",
        ),
        "d": CellSpec(
            Sum("reporting_ead"),
            predicate=RowPredicate(classes=classes, on_balance_sheet=False),
            empty_cell="zero",
        ),
        "e": CellSpec(
            Sum("rwa_final"),
            predicate=RowPredicate(classes=classes),
            empty_cell="zero",
        ),
        "f": CellSpec(Formula(refs=("c", "d", "e"), fn=_density)),
    }


@cites("CRR Art. 444")
def build_cr4_spec(framework: str) -> TemplateSpec:
    """Build the CR4 TemplateSpec for one framework's row set.

    Carries the Art. 444(e) citation for the SA exposure-and-CRM-effects
    disclosure, with the class rows keyed per the recorded F3 decision
    (origin class for the pre-CRM columns, post-substitution class for the
    post-CRM columns).
    """
    rows = tuple(get_cr4_rows(framework))
    cells: dict[tuple[str, str], CellSpec] = {}
    for row in rows:
        row_cells = _row_cells(row)
        if row_cells is None:
            continue
        for col_ref, cell in row_cells.items():
            cells[(row.ref, col_ref)] = cell
    return TemplateSpec(
        name="cr4",
        rows=rows,
        column_refs=tuple(col.ref for col in get_cr4_columns(framework)),
        cells=cells,
        predicate=RowPredicate(approaches_origin=("standardised",)),
        empty_cell="null",
    )


_CR4_SPECS: dict[str, TemplateSpec] = {
    framework: build_cr4_spec(framework) for framework in ("CRR", "BASEL_3_1")
}


def generate_cr4(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> pl.DataFrame | None:
    """Execute CR4 over the full sealed ledger.

    Preserves the imperative generator's error contract: a missing
    ``ead_final`` or RWA column (impossible on the sealed ledger; reachable
    via direct invocation with synthetic frames) records the CR4 error and
    yields no template. The population is first narrowed to the SA credit-risk
    book (counterparty-credit-risk and settlement legs dropped; the
    facility_undrawn commitment reclassified off-balance-sheet) so every
    column reports over one population — ``sa_scope.sa_credit_risk_population``.
    """
    if "ead_final" not in cols or not ({"rwa_final", "rwa"} & cols):
        errors.append("CR4: missing EAD or RWA column")
        return None
    spec = _CR4_SPECS.get(framework) or build_cr4_spec(framework)
    return execute(spec, sa_credit_risk_population(results, cols))
