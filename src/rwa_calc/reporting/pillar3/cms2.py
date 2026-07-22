"""
Pillar 3 CMS2 — Modelled vs standardised RWEA comparison by asset class,
declarative (Basel 3.1 only).

Pipeline position:
    sealed aggregator-exit ledger -> build_cms2_spec() -> cellspec.execute()
        -> CMS2 DataFrame

Cell semantics (recorded decisions, this slice):

- Basel 3.1 only (the Art. 92(3A) internal-model gate); None under CRR.
- Rows key the ORIGINATION class (the sealed raw ``exposure_class`` column,
  via tolerant per-value limbs) — the CR6-A recorded pattern: the row axis
  is Art. 147-shaped (the "of which" sub-rows are IRB-only concepts) with
  no defaulted sink, and column b is defined as the SA recomputation "of
  exposures reported in column (a)" — the same population, never
  re-bucketed, so substitution moves no row (the CR6/CR9 obligor family).
- Column a sums the actual ``rwa_final`` of the MODELLED origin approaches
  within the row's classes; column b sums their ``sa_rwa`` SA-equivalent
  (pre-supporting-factor — the engine's S-TREA/floor convention, recorded);
  column c is the row's TOTAL actual RWA across all approaches — the
  RECORDED FIX: the retired code added only the ``standardised`` approach's
  RWA, silently dropping equity-approach rows ("exposures calculated
  according to the SA for credit risk include equity exposures subject to
  the IRB Equity Transitional"), which zeroed the equity row 0030 and left
  the Total 2.5M short of CMS1 on the reference portfolio; column d sums
  ``sa_rwa`` over the row's SA-mapped classes (``CMS2_SA_CLASS_MAP``)
  across the whole book — the per-class full-SA output-floor base.
- Bespoke sub-rows preserved: 0041 (corporates of-which F-IRB; column c is
  the F-IRB corporate sub-population's own actual RWA. Annex II defines
  col c as the sum of "IRB RWA + SA RWA" of the ROW's population; an
  "of which F-IRB" row holds no SA legs, so col c collapses to column a —
  exactly as the 0042 A-IRB sibling mirrors a. The RECORDED FIX (R18): the
  retired predicate added the whole corporate class's standardised + equity
  RWA on top of the F-IRB RWA, over-stating an of-which sub-row by the
  entire SA book. Column d still compares at the parent corporate level),
  0042 (of-which A-IRB; column c mirrors a, column d recorded-null),
  0044/0045/0054 (IPRE-HVCRE and purchased-receivables splits — no engine
  discriminators, recorded-null), 0070 Total.

Lineage-instrumented (R21): ``cms2_plans`` exposes the single (no sheet axis)
execution plan — its frame is the full sealed ledger (CMS2 keys the raw
origination ``exposure_class`` directly, so no prepared discriminators) — so
``reporting.lineage`` can drill into a reported cell. CMS2 is Basel 3.1 only, so
``cms2_plans`` (like ``generate_cms2``) yields NOTHING under CRR: lineage then
degrades to a clean "no lineage" 404, never a crash.

References:
- PRA PS1/26 Art. 456(1)(b), Art. 2a(2); Annex II (UKB CMS2 instructions)
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
from rwa_calc.reporting.pillar3.cms1 import MODELLED_APPROACHES
from rwa_calc.reporting.pillar3.templates import (
    CMS2_COLUMNS,
    CMS2_ROWS,
    CMS2_SA_CLASS_MAP,
)
from rwa_calc.reporting.plans import SheetPlan

if TYPE_CHECKING:
    from collections.abc import Mapping

    import polars as pl

# Single-frame lineage key: CMS2 has no sheet axis, so its one plan keys under a
# canonical name (see reporting.plans / _resolve_sheet_key single_frame path).
_SHEET_KEY = "cms2"

# Sub-rows with no engine discriminator — recorded permanently-null.
_NULL_REFS: frozenset[str] = frozenset({"0044", "0045", "0054"})

# The corporates parent classes (rows 0041/0042 narrow them by approach).
_CORPORATE_CLASSES: tuple[str, ...] = CMS2_SA_CLASS_MAP["0040"]


def _copy_of_a(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """Row 0042's column c mirrors a (no SA-portfolio add — sub-row shape)."""
    return cells["a"]


def _class_member(
    classes: tuple[str, ...], approaches_origin: tuple[str, ...] = ()
) -> RowPredicate:
    """Origination-class membership (tolerant per-value limbs over the sealed
    raw ``exposure_class`` column), optionally narrowed by origin approach."""
    limbs = tuple(RowPredicate(equals=(("exposure_class", value),)) for value in classes)
    if len(limbs) == 1:
        return RowPredicate(equals=limbs[0].equals, approaches_origin=approaches_origin)
    return RowPredicate(any_of=limbs, approaches_origin=approaches_origin)


def _class_row_cells(ref: str, classes: tuple[str, ...]) -> dict[str, CellSpec]:
    """The standard class-row bindings (cols a/b modelled, c total actual,
    d full-SA over the SA-mapped classes)."""
    sa_classes = CMS2_SA_CLASS_MAP.get(ref, classes)
    return {
        "a": CellSpec(
            Sum("rwa_final"),
            predicate=_class_member(classes, approaches_origin=MODELLED_APPROACHES),
        ),
        "b": CellSpec(
            Sum("sa_rwa"),
            predicate=_class_member(classes, approaches_origin=MODELLED_APPROACHES),
        ),
        "c": CellSpec(Sum("rwa_final"), predicate=_class_member(classes), empty_cell="zero"),
        "d": CellSpec(Sum("sa_rwa"), predicate=_class_member(sa_classes)),
    }


@cites("PS1/26, paragraph 456")
def build_cms2_spec() -> TemplateSpec:
    """Build the CMS2 TemplateSpec (single Basel 3.1 layout).

    Carries the Art. 456(1)(b) citation for the by-asset-class modelled vs
    standardised RWEA comparison.
    """
    cells: dict[tuple[str, str], CellSpec] = {}
    for row in CMS2_ROWS:
        if row.ref in _NULL_REFS:
            continue
        if row.is_total:
            cells[(row.ref, "a")] = CellSpec(
                Sum("rwa_final"), predicate=RowPredicate(approaches_origin=MODELLED_APPROACHES)
            )
            cells[(row.ref, "b")] = CellSpec(
                Sum("sa_rwa"), predicate=RowPredicate(approaches_origin=MODELLED_APPROACHES)
            )
            cells[(row.ref, "c")] = CellSpec(Sum("rwa_final"), empty_cell="zero")
            cells[(row.ref, "d")] = CellSpec(Sum("sa_rwa"))
            continue
        if row.ref == "0041":
            firb = _class_member(_CORPORATE_CLASSES, approaches_origin=("foundation_irb",))
            cells[(row.ref, "a")] = CellSpec(Sum("rwa_final"), predicate=firb)
            cells[(row.ref, "b")] = CellSpec(Sum("sa_rwa"), predicate=firb)
            cells[(row.ref, "c")] = CellSpec(Sum("rwa_final"), predicate=firb, empty_cell="zero")
            cells[(row.ref, "d")] = CellSpec(
                Sum("sa_rwa"), predicate=_class_member(_CORPORATE_CLASSES)
            )
            continue
        if row.ref == "0042":
            airb = _class_member(_CORPORATE_CLASSES, approaches_origin=("advanced_irb",))
            cells[(row.ref, "a")] = CellSpec(Sum("rwa_final"), predicate=airb)
            cells[(row.ref, "b")] = CellSpec(Sum("sa_rwa"), predicate=airb)
            cells[(row.ref, "c")] = CellSpec(Formula(refs=("a",), fn=_copy_of_a))
            continue
        if row.exposure_classes:
            for col_ref, cell in _class_row_cells(row.ref, row.exposure_classes).items():
                cells[(row.ref, col_ref)] = cell
    return TemplateSpec(
        name="cms2",
        rows=tuple(CMS2_ROWS),
        column_refs=tuple(col.ref for col in CMS2_COLUMNS),
        cells=cells,
        empty_cell="null",
    )


_CMS2_SPEC: TemplateSpec = build_cms2_spec()


def cms2_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the single CMS2 execution plan (the lineage seam).

    CMS2 has no sheet axis, so the one plan keys under the single-frame
    canonical key. The plan's frame is the full sealed ledger itself — CMS2
    keys the raw origination ``exposure_class`` directly, so there is no
    ``_prepare`` step. CMS2 is Basel 3.1 only, so a CRR run yields ``{}`` —
    lineage then returns a clean "no lineage" rather than crashing. Preserves
    the imperative generator's error contract: a missing RWA column records the
    CMS2 error and yields no plan. There is no post-execute pass, so
    ``negative_cols`` is empty.
    """
    if framework != "BASEL_3_1":
        return {}
    if not ({"rwa_final", "rwa"} & cols):
        errors.append("CMS2: missing RWA column")
        return {}
    return {
        _SHEET_KEY: SheetPlan(
            spec=_CMS2_SPEC,
            frame=results.collect(),
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    }


def generate_cms2(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute CMS2 over the full sealed ledger (Basel 3.1 only; keyed like
    ``cms2_plans``).

    The thin consumer of ``cms2_plans``: it executes each plan under the same
    key, so a cell's reported value and its spec agree. Preserves the
    imperative generator's contracts: an empty dict under CRR (the dispatch
    router unwraps it to ``None``); a missing RWA column records the CMS2 error
    and yields no frame; columns b/d are null when ``sa_rwa`` is absent. CMS2
    has no post-execute pass, so this is a plain ``execute``.
    """
    return {
        key: execute(plan.spec, plan.frame, plan.ctx)
        for key, plan in cms2_plans(results, cols, framework, errors).items()
    }
