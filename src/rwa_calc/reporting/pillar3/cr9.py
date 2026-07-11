"""
Pillar 3 CR9 / CR9.1 — IRB PD back-testing, declarative (Basel 3.1 only).

Pipeline position:
    sealed aggregator-exit ledger -> _prepare() -> one TemplateSpec per
    approach x Art. 147 leaf class -> cellspec.execute() -> dict[key, DataFrame]

Cell semantics (the recorded F3 close-out —
docs/plans/phase7-declarative-reporting.md §6):

- Sheets key on the OBLIGOR basis — ``reporting_class_origin`` x
  ``reporting_approach_origin`` — refined by the Annex XXII leaf taxonomy
  (``CR9ClassSpec`` discriminators ``is_sme`` / ``property_type`` /
  ``cp_is_financial_sector_entity``, resolved by the module-owned
  ``_leaf_expr`` with the recorded absent-column degradation: a missing
  discriminator drops its clause, except ``financial_large=True`` which
  becomes match-nothing so residual corporates collapse onto the non-SME
  leaf). The instructions mandate the obligor basis verbatim ("for each
  obligor assigned to this exposure class (without considering any
  substitution effects due to CRM)") — substitution never moves a sheet.
- PD-band rows reuse the 17 fixed CR6 ranges, allocated half-open on the
  derived ``cr9_alloc_pd`` (pre-input-floor ``pd``, falling back to
  ``pd_floored``), with defaulted rows forced to the 100% band via the
  normalized default flag ("All defaulted exposures shall be included in
  the bucket representing PD of 100%" — the same recorded fix as CR6).
  ONLY populated bands are emitted (plus the Total row, ref 18) — the
  retired sparse-emission convention, preserved and recorded (CR6 by
  contrast emits all 17 bands and nulls the empty ones).
- Columns (single-run point-in-time PROXIES, preserved and recorded as the
  F6-family follow-up — a true back-testing series needs prior-period
  carriers the engine does not produce):
  c = Σ ``prior_year_obligor_count`` when supplied, else the CURRENT
  distinct-obligor count; d = distinct defaulted obligors (normalized
  ``is_defaulted``, falling back to post-floor PD >= 100%); e = d/c x100
  (0.0 when c is 0); f = EAD-weighted post-floor PD x100 (arithmetic mean
  when no EAD column); g = arithmetic mean post-floor PD x100;
  h = mean ``historical_annual_default_rate`` x100 when supplied, else a
  copy of e.
- Columns a (class display label) and b (PD-range label) are String cells
  injected by a module post-step (the executor is Float64-only).

CR9.1 (Art. 180(1)(f) ECAI-mapping back-testing) shares the class taxonomy
and the c-h verbs but groups rows by the firm's ECAI grade
(``external_rating_equivalent``) instead of PD bands, scoped to obligors
flagged ``ecai_pd_mapping``. Neither column is produced by the engine, so
CR9.1 is empty on the real pipeline (the recorded S1 accept-empty
decision); it comes alive only on seeded frames.

References:
- PRA PS1/26 Art. 452(h), Art. 180(1)(f), Annex XXII paras 12-15
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8, F3 close-out)
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Count,
    Formula,
    Mean,
    RowPredicate,
    Sum,
    TemplateSpec,
    WeightedAvg,
    execute,
)
from rwa_calc.reporting.pillar3.templates import (
    CR6_PD_RANGES,
    CR9_AIRB_CLASSES,
    CR9_COLUMN_REFS,
    CR9_FIRB_CLASSES,
    P3Row,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_calc.reporting.pillar3.templates import CR9ClassSpec

# The origin-approach blocks, in the retained emission order.
_APPROACH_CLASSES: tuple[tuple[str, tuple[tuple[str, str, CR9ClassSpec], ...]], ...] = (
    ("foundation_irb", tuple(CR9_FIRB_CLASSES)),
    ("advanced_irb", tuple(CR9_AIRB_CLASSES)),
)

# The derived PD-band allocation column (pre-floor PD; defaulted -> 1.0).
_ALLOC_COL = "cr9_alloc_pd"

# The Float64 value columns the executor computes (a/b are String post-steps).
_VALUE_REFS: tuple[str, ...] = tuple(ref for ref in CR9_COLUMN_REFS if ref not in ("a", "b"))

_CR9_ROWS: tuple[P3Row, ...] = tuple(
    P3Row(ref, label) for _lower, _upper, ref, label in CR6_PD_RANGES
) + (P3Row("18", "Total", is_total=True),)

_BAND_BY_REF: dict[str, tuple[float, float]] = {
    ref: (lower, upper) for lower, upper, ref, _label in CR6_PD_RANGES
}


def _observed_rate(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """Column e = d / c x100 (0.0 when the obligor count is zero)."""
    obligors = cells["c"] or 0.0
    if obligors <= 0:
        return 0.0
    return (cells["d"] or 0.0) / obligors * 100.0


def _copy_of_e(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """Column h fallback: the observed rate (no historical series carrier)."""
    return cells["e"]


def _leaf_expr(leaf: CR9ClassSpec, cols: set[str]) -> pl.Expr:
    """Resolve a CR9 leaf-class descriptor into a row-filter expression.

    Ports the retired ``_cr9_class_predicate`` verbatim, with the class term
    retargeted onto the obligor ``reporting_class_origin`` (recorded F3
    close-out). Degrades gracefully when a discriminator column is absent:
    the clause is dropped (residual corporate rows collapse onto the non-SME
    leaf), except ``financial_large=True`` which becomes match-nothing.

    References:
        PRA PS1/26 Annex XXII, Art. 147(2)(b)-(d), 147A.
    """
    predicate = pl.col("reporting_class_origin").is_in(list(leaf.exposure_classes))
    if leaf.is_sme is not None and "is_sme" in cols:
        predicate = predicate & (pl.col("is_sme") == leaf.is_sme)
    if leaf.property_type is not None and "property_type" in cols:
        predicate = predicate & (pl.col("property_type") == leaf.property_type)
    if leaf.financial_large is not None:
        if "cp_is_financial_sector_entity" in cols:
            flag = pl.col("cp_is_financial_sector_entity").fill_null(value=False)
            predicate = predicate & (flag == leaf.financial_large)
        elif leaf.financial_large:
            predicate = pl.lit(value=False)
    return predicate


def _prepare(
    data: pl.DataFrame, cols: set[str], report_source: str, alloc_source: str | None
) -> pl.DataFrame:
    """Add the normalized default flag and (for CR9) the allocation column.

    ``is_defaulted`` is normalized to the retired detection ladder — the flag
    when present (nulls as False), else post-floor PD >= 100% — so the strict
    ``RowPredicate.is_defaulted`` field drives the defaulted-obligor count.
    ``cr9_alloc_pd`` allocates on the pre-floor PD with defaulted rows forced
    to the 100% band (the recorded CR6-family fix).
    """
    if "is_defaulted" in cols:
        defaulted = pl.col("is_defaulted").fill_null(value=False)
    elif report_source in cols:
        defaulted = (pl.col(report_source) >= 1.0).fill_null(value=False)
    else:
        defaulted = pl.lit(value=False)
    exprs = [defaulted.alias("is_defaulted")]
    if alloc_source is not None:
        exprs.append(
            pl.when(defaulted).then(pl.lit(1.0)).otherwise(pl.col(alloc_source)).alias(_ALLOC_COL)
        )
    return data.with_columns(exprs)


def _backtest_cells(
    cols: set[str], report_source: str, member: RowPredicate
) -> dict[str, CellSpec]:
    """The c-h value bindings for one back-testing row (CR9 band / CR9.1
    grade / Total), over an already-narrowed membership predicate."""
    if "prior_year_obligor_count" in cols:
        obligors = CellSpec(Sum("prior_year_obligor_count"), predicate=member)
    else:
        obligors = CellSpec(Count("counterparty_reference", distinct=True), predicate=member)
    if "ead_final" in cols or "reporting_ead" in cols:
        ewa_pd = CellSpec(
            WeightedAvg(report_source, weight="reporting_ead", scale=100.0), predicate=member
        )
    else:
        ewa_pd = CellSpec(Mean(report_source, scale=100.0), predicate=member)
    if "historical_annual_default_rate" in cols:
        hist = CellSpec(Mean("historical_annual_default_rate", scale=100.0), predicate=member)
    else:
        hist = CellSpec(Formula(refs=("e",), fn=_copy_of_e))

    defaulted_member = replace(member, is_defaulted=True)
    return {
        "c": obligors,
        "d": CellSpec(Count("counterparty_reference", distinct=True), predicate=defaulted_member),
        "e": CellSpec(Formula(refs=("c", "d"), fn=_observed_rate)),
        "f": ewa_pd,
        "g": CellSpec(Mean(report_source, scale=100.0), predicate=member),
        "h": hist,
    }


def _build_cr9_spec(cols: set[str], report_source: str) -> TemplateSpec:
    """The per-sheet CR9 spec (shared across sheets — the class narrowing
    happens before execution; rows carry only the PD-band terms)."""
    cells: dict[tuple[str, str], CellSpec] = {}
    for row in _CR9_ROWS:
        if row.is_total:
            member = RowPredicate()
        else:
            lower, upper = _BAND_BY_REF[row.ref]
            high = upper if not math.isinf(upper) else float("inf")
            member = RowPredicate(between=((_ALLOC_COL, lower, high),))
        for col_ref, cell in _backtest_cells(cols, report_source, member).items():
            cells[(row.ref, col_ref)] = cell
    return TemplateSpec(
        name="cr9",
        rows=_CR9_ROWS,
        column_refs=_VALUE_REFS,
        cells=cells,
        empty_cell="null",
    )


@cites("PS1/26, paragraph 147.2")
def generate_cr9(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute CR9 per approach x leaf class over the sealed ledger.

    Preserves the imperative generator's contracts: Basel 3.1 only; missing
    class/approach columns record "CR9: missing required columns"; a missing
    PD source records the skip error; an empty IRB population yields ``{}``
    silently; a leaf with no rows produces no dict entry.
    """
    if framework != "BASEL_3_1":
        return {}
    if "exposure_class" not in cols or not ({"approach_applied", "approach"} & cols):
        errors.append("CR9: missing required columns (exposure_class, approach)")
        return {}
    alloc_source = "pd" if "pd" in cols else ("pd_floored" if "pd_floored" in cols else None)
    if alloc_source is None:
        errors.append("CR9: no PD column available — skipping PD backtesting")
        return {}
    report_source = "pd_floored" if "pd_floored" in cols else alloc_source

    data = results.collect()
    population = data.filter(
        pl.col("reporting_approach_origin").is_in(["foundation_irb", "advanced_irb"])
    )
    if population.height == 0:
        return {}
    population = _prepare(population, cols, report_source, alloc_source)
    spec = _build_cr9_spec(cols, report_source)

    result: dict[str, pl.DataFrame] = {}
    for approach_val, class_defs in _APPROACH_CLASSES:
        approach_data = population.filter(pl.col("reporting_approach_origin") == approach_val)
        if approach_data.height == 0:
            continue
        for class_key, class_display, leaf in class_defs:
            class_data = approach_data.filter(_leaf_expr(leaf, cols))
            if class_data.height == 0:
                continue
            frame = execute(spec, class_data)
            frame = _drop_empty_bands(frame, class_data)
            result[f"{approach_val} - {class_key}"] = _with_labels(frame, class_display)
    return result


@cites("PS1/26, paragraph 147.2")
def generate_cr9_1(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute CR9.1 per approach x leaf class, grouped by ECAI grade.

    Preserves the imperative generator's contracts: Basel 3.1 only; a
    missing scope column (``ecai_pd_mapping`` / ``external_rating_equivalent``
    / class / approach) yields ``{}`` SILENTLY — the engine produces neither
    scope column, so CR9.1 is empty on the real pipeline (recorded S1
    accept-empty decision); a missing PD source records the skip error.
    """
    if framework != "BASEL_3_1":
        return {}
    if (
        "exposure_class" not in cols
        or not ({"approach_applied", "approach"} & cols)
        or "ecai_pd_mapping" not in cols
        or "external_rating_equivalent" not in cols
    ):
        return {}
    report_source = "pd_floored" if "pd_floored" in cols else ("pd" if "pd" in cols else None)
    if report_source is None:
        errors.append("CR9.1: no PD column available — skipping ECAI backtesting")
        return {}

    data = results.collect()
    population = data.filter(
        pl.col("reporting_approach_origin").is_in(["foundation_irb", "advanced_irb"])
    )
    if population.height == 0:
        return {}
    population = population.filter(pl.col("ecai_pd_mapping"))
    if population.height == 0:
        return {}
    population = _prepare(population, cols, report_source, alloc_source=None)

    result: dict[str, pl.DataFrame] = {}
    for approach_val, class_defs in _APPROACH_CLASSES:
        approach_data = population.filter(pl.col("reporting_approach_origin") == approach_val)
        if approach_data.height == 0:
            continue
        for class_key, class_display, leaf in class_defs:
            class_data = approach_data.filter(_leaf_expr(leaf, cols))
            if class_data.height == 0:
                continue
            frame = _execute_by_grade(class_data, cols, report_source)
            result[f"{approach_val} - {class_key}"] = _with_labels(
                frame, class_display, grade_column=True
            )
    return result


def _execute_by_grade(class_data: pl.DataFrame, cols: set[str], report_source: str) -> pl.DataFrame:
    """Build and run the per-grade CR9.1 spec (rows discovered from the
    frame's distinct ECAI grades, order-preserving, plus a Total row)."""
    grades = class_data["external_rating_equivalent"].unique(maintain_order=True).to_list()
    rows = tuple(P3Row(str(grade), str(grade)) for grade in grades) + (
        P3Row("Total", "Total", is_total=True),
    )
    cells: dict[tuple[str, str], CellSpec] = {}
    for row in rows:
        member = (
            RowPredicate()
            if row.is_total
            else RowPredicate(equals=(("external_rating_equivalent", row.name),))
        )
        for col_ref, cell in _backtest_cells(cols, report_source, member).items():
            cells[(row.ref, col_ref)] = cell
    spec = TemplateSpec(
        name="cr9_1",
        rows=rows,
        column_refs=_VALUE_REFS,
        cells=cells,
        empty_cell="null",
    )
    return execute(spec, class_data)


def _drop_empty_bands(frame: pl.DataFrame, class_data: pl.DataFrame) -> pl.DataFrame:
    """Keep only populated PD-band rows plus the Total row — the retired
    sparse-emission convention (CR6 by contrast renders empty bands as
    all-null rows)."""
    populated = [
        ref
        for lower, upper, ref, _label in CR6_PD_RANGES
        if class_data.filter(
            (pl.col(_ALLOC_COL) >= lower)
            & ((pl.col(_ALLOC_COL) < upper) if not math.isinf(upper) else pl.lit(value=True))
        ).height
        > 0
    ]
    return frame.filter(pl.col("row_ref").is_in([*populated, "18"]))


def _with_labels(
    frame: pl.DataFrame, class_display: str, *, grade_column: bool = False
) -> pl.DataFrame:
    """Inject the String columns: a = the class display label, b = the row
    name (PD-band label / ECAI grade / "Total"); CR9.1 additionally carries
    the dynamic ``external_rating_equivalent`` String column."""
    frame = frame.with_columns(
        pl.lit(class_display).alias("a"),
        pl.col("row_name").alias("b"),
    )
    ordered = ["row_ref", "row_name", "a", "b", *_VALUE_REFS]
    if grade_column:
        frame = frame.with_columns(pl.col("row_name").alias("external_rating_equivalent"))
        ordered.append("external_rating_equivalent")
    return frame.select(ordered)
