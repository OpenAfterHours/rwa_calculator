"""
Pillar 3 CR7 — Effect of credit derivatives on RWEAs, declarative.

Pipeline position:
    sealed aggregator-exit ledger -> build_cr7_spec(framework)
        -> cellspec.execute() -> CR7 DataFrame

Cell semantics (recorded decisions, this slice):

- Rows key on the ORIGIN approach x the obligor's applied Art. 147 class
  (``reporting_approach_origin`` x ``reporting_class_origin``) — column a is
  explicitly "the exposure classes relevant for the exposures to the
  original obligor" (Annex XXII); the substitution movement belongs in the
  a -> b column pair, never a row move.
- Column a (pre-credit-derivatives RWEA) and column b (actual/post-CD RWEA)
  are the IDENTICAL Sum today — the ledger carries no hypothetical
  pre-credit-derivative RWEA, so the retired approximation (a = b, exact
  for a portfolio with no credit derivatives; understates CD relief
  otherwise) is preserved and recorded as an add-to-contract candidate
  (plan §7 / F7 family).
- RECORDED FIX: the CRR row 8 "Retail — Secured by immovable property" now
  sums the A-IRB ``retail_mortgage`` class. The retired handler summed
  ``(retail_other, retail_qrre)`` — byte-identical to row 9 "Retail —
  Other" and contradicting both the row label and the Art. 147 class axis
  the instructions mandate. On the golden portfolio (no A-IRB mortgage)
  row 8 flips populated -> null; row 9 is unchanged.
- Empty row subsets render null (Pillar 3 policy) — e.g. classes with no
  exposures under the row's approach.

Lineage-instrumented (R20): ``cr7_plans`` exposes the single (no sheet axis)
execution plan so ``reporting.lineage`` can drill into a reported cell.

References:
- CRR Art. 453(j); PRA PS1/26 Annex XXII (UK/UKB CR7; CRR rows 1-10 with
  F-IRB/A-IRB subtotals, B31 rows 1-8 adding the slotting subtotal)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    RowPredicate,
    Sum,
    TemplateSpec,
    execute,
)
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.pillar3.templates import CR7_COLUMNS, get_cr7_rows
from rwa_calc.reporting.plans import SheetPlan

if TYPE_CHECKING:
    import polars as pl

# Single-frame lineage key: CR7 has no sheet axis, so its one plan keys under a
# canonical name (see reporting.plans / _resolve_sheet_key single_frame path).
_SHEET_KEY = "cr7"

_FIRB = ("foundation_irb",)
_AIRB = ("advanced_irb",)
_ALL_IRB = ("foundation_irb", "advanced_irb", "slotting")

_CORP_B31 = ("corporate", "corporate_sme", "specialised_lending")
_CORP_CRR = ("corporate", "specialised_lending")
_RETAIL_B31 = ("retail_mortgage", "retail_qrre", "retail_other")
_RETAIL_OTHER_CRR = ("retail_other", "retail_qrre")

# Row predicates per regime: origin approach x obligor applied class.
_CRR_ROW_PREDICATES: dict[str, RowPredicate] = {
    "1": RowPredicate(approaches_origin=_FIRB),
    "2": RowPredicate(approaches_origin=_FIRB, classes_origin=("central_govt_central_bank",)),
    "3": RowPredicate(approaches_origin=_FIRB, classes_origin=("institution",)),
    "4": RowPredicate(approaches_origin=_FIRB, classes_origin=("corporate_sme",)),
    "5": RowPredicate(approaches_origin=_FIRB, classes_origin=_CORP_CRR),
    "6": RowPredicate(approaches_origin=_AIRB),
    "7": RowPredicate(approaches_origin=_AIRB, classes_origin=_CORP_B31),
    # Recorded fix: the retired handler summed (retail_other, retail_qrre)
    # here — identical to row 9 and contradicting the row label.
    "8": RowPredicate(approaches_origin=_AIRB, classes_origin=("retail_mortgage",)),
    "9": RowPredicate(approaches_origin=_AIRB, classes_origin=_RETAIL_OTHER_CRR),
    "10": RowPredicate(approaches_origin=_ALL_IRB),
}

_B31_ROW_PREDICATES: dict[str, RowPredicate] = {
    "1": RowPredicate(approaches_origin=_FIRB),
    "2": RowPredicate(approaches_origin=_FIRB, classes_origin=("institution",)),
    "3": RowPredicate(approaches_origin=_FIRB, classes_origin=_CORP_B31),
    "4": RowPredicate(approaches_origin=_AIRB),
    "5": RowPredicate(approaches_origin=_AIRB, classes_origin=_CORP_B31),
    "6": RowPredicate(approaches_origin=_AIRB, classes_origin=_RETAIL_B31),
    "7": RowPredicate(approaches_origin=("slotting",)),
    "8": RowPredicate(approaches_origin=_ALL_IRB),
}


@cites("CRR Art. 453")
def build_cr7_spec(framework: str) -> TemplateSpec:
    """Build the CR7 TemplateSpec for one framework's row set.

    Carries the Art. 453(j) citation for the credit-derivatives-effect
    disclosure.
    """
    rows = tuple(get_cr7_rows(framework))
    predicates = _B31_ROW_PREDICATES if framework == "BASEL_3_1" else _CRR_ROW_PREDICATES
    cells: dict[tuple[str, str], CellSpec] = {}
    for row in rows:
        predicate = predicates.get(row.ref)
        if predicate is None:
            continue
        cell = CellSpec(Sum("rwa_final"), predicate=predicate)
        cells[(row.ref, "a")] = cell
        cells[(row.ref, "b")] = cell
    return TemplateSpec(
        name="cr7",
        rows=rows,
        column_refs=tuple(col.ref for col in CR7_COLUMNS),
        cells=cells,
        empty_cell="null",
    )


_CR7_SPECS: dict[str, TemplateSpec] = {
    framework: build_cr7_spec(framework) for framework in ("CRR", "BASEL_3_1")
}


def cr7_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the single CR7 execution plan (the lineage seam).

    CR7 has no sheet axis and runs over the FULL sealed ledger (its rows key on
    origin approach x obligor applied class), so the one plan keys under the
    single-frame canonical key. Preserves the imperative generator's error
    contract: a missing RWA or approach column records the CR7 error and yields
    no plan. There is no post-execute pass, so ``negative_cols`` is empty.
    """
    if not ({"rwa_final", "rwa"} & cols) or not ({"approach_applied", "approach"} & cols):
        errors.append("CR7: missing required columns")
        return {}
    spec = _CR7_SPECS.get(framework) or build_cr7_spec(framework)
    return {
        _SHEET_KEY: SheetPlan(
            spec=spec,
            frame=results.collect(),
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    }


def generate_cr7(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute CR7 over the full sealed ledger (keyed like ``cr7_plans``).

    The thin consumer of ``cr7_plans``: it executes each plan under the same
    key, so a cell's reported value and its spec agree. CR7 has no post-execute
    pass, so this is a plain ``execute``. The dispatch router unwraps the
    single-frame dict for the ``Pillar3TemplateBundle.cr7`` field.
    """
    return {
        key: execute(plan.spec, plan.frame, plan.ctx)
        for key, plan in cr7_plans(results, cols, framework, errors).items()
    }
