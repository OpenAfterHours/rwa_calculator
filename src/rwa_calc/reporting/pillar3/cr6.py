"""
Pillar 3 CR6 — IRB exposures by exposure class and PD range, declarative.

Pipeline position:
    sealed aggregator-exit ledger -> _with_alloc_pd() -> one TemplateSpec per
    obligor exposure class -> cellspec.execute() -> dict[class, DataFrame]

Cell semantics (the recorded F3 second-tranche decision —
docs/plans/phase7-declarative-reporting.md §6):

- Per-class sheets key on ``reporting_class_origin`` — the obligor's applied
  Art. 147 class. The disclosure instructions mandate the obligor basis
  verbatim ("without considering any substitution effects due to CRM" —
  Annex XXII column a, both regimes), and the COREP twin C 08.03 (by PD
  range) carries no substitution-flow columns. This is the OPPOSITE basis
  from the CR4/CR5 tranche; number-neutral for IRB rows (IRB reclassifies
  on the origination class itself and has no defaulted class).
- The population is the ORIGIN F-IRB/A-IRB book (``reporting_approach_origin``
  — slotting is excluded from the PD scale); a class produces a sheet only
  when present in that population and in the ``IRB_EXPOSURE_CLASSES`` axis.
- PD-band rows allocate on the derived ``cr6_alloc_pd`` column, half-open
  [lower, upper): Basel 3.1 allocates on the PRE-input-floor ``pd`` and
  CRR on ``pd_floored`` (PS1/26 Annex XXII column a mandates pre-floor
  allocation; CRR's text draws no pre/post distinction). Defaulted rows are
  forced to the 100% band (row 17) via the derived column — "All defaulted
  exposures shall be included in the bucket representing PD of 100%" — a
  recorded fix: the retired imperative bucketed defaulted rows on their
  model PD (unobservable on the golden portfolio, where the only defaulted
  IRB-style fixture carries pd=1.0 already).
- Column f reports the EAD-weighted POST-floor ``pd_floored`` x100 and
  column h the post-floor ``lgd_floored`` x100 (mandated post-floor basis);
  column i weights ``irb_maturity_m``; g counts distinct obligors; k is the
  RWEA density; l sums ``expected_loss``; m sums ``scra_provision_amount``
  — never produced by the engine, so the cell is recorded permanently null
  (plan F6).
- Column a is the String PD-range label (= the row name), injected after
  the executor runs (the executor's value cells are uniformly Float64).
- An EMPTY PD band renders as an all-null row (the imperative contract);
  a populated band reports 0.0 gross off-BS amounts when its rows are all
  on-BS. The Total row (ref 18) pools the whole class.
- Lineage-instrumented (R25): ``cr6_plans`` exposes the per-obligor-class
  execution plans, and ``generate_cr6`` iterates them so a cell's spec and its
  reported value key identically. Each plan's frame is the WHOLE alloc-PD frame
  (the ``classes_origin`` predicate lives in the cell specs, so the executor
  selects the class); the two post-execute passes (``_null_empty_bands`` and the
  String col ``a`` label injection) stay on the reported frame the drill-down
  reads — col ``a`` is a String label the tie-out sweep skips, and an empty PD
  band's all-null cells drill to zero legs against a null reported value. A
  defaulted leg drills in the 100% band (row 17) via the derived ``cr6_alloc_pd``
  column. CR6 carries no "(-)"-labelled deduction column, so its ``negative_cols``
  is empty (the OBLIGOR basis reports no substitution flow).

References:
- CRR Art. 452(g); PRA PS1/26 Annex XXII (UKB CR6, incl. the pre/post
  input-floor split, Art. 160(1)/163(1) PD floors, 161(5)/164(4) LGD floors)
- COREP Annex II C 08.03 (by-PD-range twin; obligor-class keyed)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8, decision F3)
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Count,
    Ratio,
    RowPredicate,
    SafeSum,
    Sum,
    TemplateSpec,
    WeightedAvg,
    execute,
)
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.pillar3.templates import (
    CR6_PD_RANGES,
    IRB_EXPOSURE_CLASSES,
    P3Row,
    get_cr6_columns,
)
from rwa_calc.reporting.plans import SheetPlan

if TYPE_CHECKING:
    from collections.abc import Iterable

# The origin-approach population of the PD scale (slotting has no PD).
_IRB_APPROACHES: tuple[str, ...] = ("foundation_irb", "advanced_irb")

# The derived PD-band allocation column added by ``_with_alloc_pd``.
_ALLOC_COL = "cr6_alloc_pd"

# The String label column (excluded from the executor's Float64 cells).
_LABEL_REF = "a"

_CR6_ROWS: tuple[P3Row, ...] = tuple(
    P3Row(ref, label) for _lower, _upper, ref, label in CR6_PD_RANGES
) + (P3Row("18", "Total", is_total=True),)


def _band_between(lower: float, upper: float) -> tuple[tuple[str, float, float], ...]:
    """The half-open [lower, upper) band term over the derived alloc column."""
    high = upper if not math.isinf(upper) else float("inf")
    return ((_ALLOC_COL, lower, high),)


def _row_cells(row: P3Row, exposure_class: str) -> dict[str, CellSpec]:
    """The Float64 column bindings for one CR6 row of one class sheet."""
    base = RowPredicate(classes_origin=(exposure_class,))
    member = (
        base if row.is_total else RowPredicate(classes_origin=(exposure_class,), between=_band(row))
    )
    on_bs = RowPredicate(
        classes_origin=(exposure_class,),
        on_balance_sheet=True,
        between=() if row.is_total else _band(row),
    )
    off_bs = RowPredicate(
        classes_origin=(exposure_class,),
        on_balance_sheet=False,
        between=() if row.is_total else _band(row),
    )
    return {
        "b": CellSpec(
            SafeSum(("reporting_gross_drawn", "reporting_gross_interest")), predicate=on_bs
        ),
        "c": CellSpec(
            SafeSum(("reporting_gross_nominal", "reporting_gross_undrawn")), predicate=off_bs
        ),
        "d": CellSpec(WeightedAvg("ccf", weight="reporting_ead"), predicate=off_bs),
        "e": CellSpec(Sum("reporting_ead"), predicate=member, empty_cell="zero"),
        "f": CellSpec(
            WeightedAvg("pd_floored", weight="reporting_ead", scale=100.0), predicate=member
        ),
        "g": CellSpec(Count("counterparty_reference", distinct=True), predicate=member),
        "h": CellSpec(
            WeightedAvg("lgd_floored", weight="reporting_ead", scale=100.0), predicate=member
        ),
        "i": CellSpec(WeightedAvg("irb_maturity_m", weight="reporting_ead"), predicate=member),
        "j": CellSpec(Sum("rwa_final"), predicate=member, empty_cell="zero"),
        "k": CellSpec(Ratio("rwa_final", "reporting_ead"), predicate=member),
        "l": CellSpec(Sum("expected_loss"), predicate=member),
        # F6 recorded fallback: the provision source columns are never
        # produced by the engine, so the cell is permanently null.
        "m": CellSpec(Sum("scra_provision_amount"), predicate=member),
    }


_BAND_BY_REF: dict[str, tuple[float, float]] = {
    ref: (lower, upper) for lower, upper, ref, _label in CR6_PD_RANGES
}


def _band(row: P3Row) -> tuple[tuple[str, float, float], ...]:
    lower, upper = _BAND_BY_REF[row.ref]
    return _band_between(lower, upper)


@cites("CRR Art. 452")
def build_cr6_spec(framework: str, exposure_class: str) -> TemplateSpec:
    """Build the CR6 TemplateSpec for one framework x obligor-class sheet.

    Carries the Art. 452(g) citation for the IRB by-class/by-PD-range
    disclosure, keyed on the obligor applied class per the recorded F3
    second-tranche decision.
    """
    cells: dict[tuple[str, str], CellSpec] = {}
    for row in _CR6_ROWS:
        for col_ref, cell in _row_cells(row, exposure_class).items():
            cells[(row.ref, col_ref)] = cell
    column_refs = tuple(col.ref for col in get_cr6_columns(framework) if col.ref != _LABEL_REF)
    return TemplateSpec(
        name=f"cr6:{exposure_class}",
        rows=_CR6_ROWS,
        column_refs=column_refs,
        cells=cells,
        predicate=RowPredicate(approaches_origin=_IRB_APPROACHES),
        empty_cell="null",
    )


_CR6_SPECS: dict[tuple[str, str], TemplateSpec] = {
    (framework, exposure_class): build_cr6_spec(framework, exposure_class)
    for framework in ("CRR", "BASEL_3_1")
    for exposure_class in IRB_EXPOSURE_CLASSES
}


def cr6_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-obligor-class CR6 execution plans for lineage.

    Keys the per-class plans on the sealed ``reporting_class_origin`` (the
    obligor's applied Art. 147 class — the recorded F3 second-tranche OBLIGOR
    basis; Annex XXII bars substitution effects) over the ORIGIN F-IRB / A-IRB
    book (``reporting_approach_origin`` — slotting has no PD scale), preserving
    ``generate_cr6``'s error contract. Every plan's ``frame`` is the WHOLE
    alloc-PD frame (each class sheet's spec carries the ``classes_origin``
    predicate, so the class filter lives in the cell predicates — the executor
    selects the class inside the spec, not a pre-sliced frame). The derived
    ``cr6_alloc_pd`` column forces defaulted legs into the 100% PD band (row 17),
    so a defaulted leg drills in that band. CR6 carries no "(-)"-labelled
    deduction column, so ``negative_cols`` is empty."""
    if "ead_final" not in cols or not ({"rwa_final", "rwa"} & cols) or "exposure_class" not in cols:
        errors.append("CR6: missing required columns")
        return {}
    alloc_source = _alloc_pd_source(cols, framework)
    if alloc_source is None:
        errors.append("CR6: missing PD column")
        return {}

    data = results.collect()
    population = data.filter(pl.col("reporting_approach_origin").is_in(list(_IRB_APPROACHES)))
    if population.height == 0:
        return {}
    data = _with_alloc_pd(data, alloc_source)

    plans: dict[str, SheetPlan] = {}
    for exposure_class in sorted(_present_classes(population)):
        spec = _CR6_SPECS.get((framework, exposure_class)) or build_cr6_spec(
            framework, exposure_class
        )
        plans[exposure_class] = SheetPlan(
            spec=spec,
            frame=data,
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    return plans


def generate_cr6(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute CR6 per obligor class over the sealed ledger.

    Iterates ``cr6_plans`` (so a cell's spec and its reported value key
    identically) and applies the two post-execute passes on each reported frame —
    the all-null empty-band pass (``_null_empty_bands``) and the String PD-range
    label injection (col ``a``, which the tie-out sweep skips as a String column)
    — the drill-down reads a cell's value from HERE. Preserves the imperative
    generator's contracts: missing EAD/RWA/class columns record "CR6: missing
    required columns"; a missing allocation-PD source records "CR6: missing PD
    column"; an empty IRB population yields ``{}`` silently.
    """
    result: dict[str, pl.DataFrame] = {}
    for exposure_class, plan in cr6_plans(results, cols, framework, errors).items():
        frame = execute(plan.spec, plan.frame)
        class_data = plan.frame.filter(
            pl.col("reporting_approach_origin").is_in(list(_IRB_APPROACHES))
            & (pl.col("reporting_class_origin") == exposure_class)
        )
        frame = _null_empty_bands(frame, class_data)
        result[exposure_class] = _with_label_column(frame, framework)
    return result


def _present_classes(population: pl.DataFrame) -> Iterable[str]:
    present = population["reporting_class_origin"].unique().to_list()
    return [value for value in present if value in IRB_EXPOSURE_CLASSES]


def _alloc_pd_source(cols: set[str], framework: str) -> str | None:
    """The PD-band allocation source (PS1/26: pre-floor ``pd``; CRR:
    ``pd_floored``), mirroring the retired regime split exactly."""
    if framework == "BASEL_3_1" and "pd" in cols:
        return "pd"
    if "pd_floored" in cols:
        return "pd_floored"
    return None


def _with_alloc_pd(data: pl.DataFrame, alloc_source: str) -> pl.DataFrame:
    """Add the derived allocation column, forcing defaulted rows to 100%.

    "All defaulted exposures shall be included in the bucket representing
    PD of 100%" (Annex XXII column a, both regimes) — the engine's defaulted
    treatment overrides K/RWA but never the model PD, so the band allocation
    must impose the 100% landing itself (recorded fix).
    """
    alloc = pl.col(alloc_source)
    if "is_defaulted" in data.columns:
        alloc = (
            pl.when(pl.col("is_defaulted").fill_null(value=False))
            .then(pl.lit(1.0))
            .otherwise(alloc)
        )
    return data.with_columns(alloc.alias(_ALLOC_COL))


def _null_empty_bands(frame: pl.DataFrame, class_data: pl.DataFrame) -> pl.DataFrame:
    """Null out every value cell of a PD-band row whose bucket is empty —
    the imperative contract (an empty bucket renders all-null, while a
    populated bucket reports 0.0 gross amounts for empty on/off-BS sides)."""
    empty_refs = [
        ref
        for lower, upper, ref, _label in CR6_PD_RANGES
        if class_data.filter(
            (pl.col(_ALLOC_COL) >= lower)
            & ((pl.col(_ALLOC_COL) < upper) if not math.isinf(upper) else pl.lit(value=True))
        ).height
        == 0
    ]
    if not empty_refs:
        return frame
    value_cols = [col for col in frame.columns if col not in ("row_ref", "row_name")]
    return frame.with_columns(
        pl.when(pl.col("row_ref").is_in(empty_refs))
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col(col))
        .alias(col)
        for col in value_cols
    )


def _with_label_column(frame: pl.DataFrame, framework: str) -> pl.DataFrame:
    """Inject the String PD-range label column ``a`` (= the row name) and
    restore the template's column order."""
    ordered = ["row_ref", "row_name"] + [col.ref for col in get_cr6_columns(framework)]
    return frame.with_columns(pl.col("row_name").alias(_LABEL_REF)).select(ordered)
