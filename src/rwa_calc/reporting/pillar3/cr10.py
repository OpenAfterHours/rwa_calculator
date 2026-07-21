"""
Pillar 3 CR10 — Specialised lending (slotting) and CRR equity, declarative.

Pipeline position:
    sealed aggregator-exit ledger -> one TemplateSpec per subtemplate family
    (a shared slotting spec + the CR10.5 equity spec) -> cellspec.execute()
    -> dict[sl_key, DataFrame]

Cell semantics (recorded decisions, this slice):

- Each subtemplate draws its OWN population. CR10.1-4 (specialised lending)
  read the ORIGIN slotting book (``reporting_approach_origin == "slotting"``);
  a guaranteed slotting exposure's covered leg leaves the slotting approach
  entirely, so the origin basis is the obligor basis by construction. CR10.5
  (CRR only) reads the Art. 155(2) simple-RW equity legs
  (``reporting_approach_origin == "equity"`` AND ``equity_method ==
  "irb_simple"``) — Art. 133 SA equity and Art. 155(3) PD/LGD equity are
  excluded, because the sealed ``reporting_method`` collapses every equity leg
  to ``EQUITY`` and cannot tell the CRR equity methods apart on its own.
- Subtemplates split on ``sl_type`` per the regime's Art. 153(5) table:
  CRR groups IPRE + HVCRE under CR10.2 and carries the CR10.5 equity
  simple-RW sheet (force-emitted even when empty); Basel 3.1 keeps HVCRE as
  its own CR10.5 and has NO equity sheet (Art. 147A removes IRB equity). An
  empty non-equity subtemplate produces no dict entry.
- Slotting rows are the five supervisory categories (Strong/Good/Satisfactory/
  Weak/Default, matched on ``slotting_category``) plus Total. Column a/b are the
  gross on-/off-BS amounts; d/e/f sum ``reporting_ead`` / ``rwa_final`` /
  ``expected_loss`` (null on an empty category — the recorded a-b-zero vs
  d-f-null asymmetry the goldens pin).
- Equity (CR10.5) rows are the three fixed Art. 155(2) supervisory bands
  (190/290/370%) plus Total, in Art. 155(2)(a)/(b)/(c) order; a leg lands in a
  band by its applied ``reporting_rw``. Equity is an on-balance-sheet
  banking-book asset with no CCF / off-BS component and no gross-carrier split,
  so col a (on-BS) mirrors col d (exposure value) and col b (off-BS) stays null;
  col f sums the Art. 158(7) equity expected loss. An empty band's a/d/e/f are
  null.
- Column c is the FIXED regulatory risk weight ("This is a fixed column. It
  shall not be altered" — Art. 153(5) Table A / Art. 155(2)), injected by a
  module post-step from the template constants (x100; Total row null) —
  populated even on empty rows. The slotting constants carry the >= 2.5y
  reference weights; the short-maturity preferential column-c variant and
  pack-homing of the display constants are recorded follow-ups (plan §7).

References:
- CRR Art. 438(e); Art. 153(5) (Table 1) / Art. 155(2) (CRR equity);
  PRA PS1/26 Annex XXIV (UKB CR10, Table A)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8)
"""

from __future__ import annotations

from dataclasses import replace

import polars as pl
from watchfire import cites

from rwa_calc.domain.enums import EquityApproach
from rwa_calc.reporting.cellspec import (
    CellSpec,
    RowPredicate,
    SafeSum,
    Sum,
    TemplateSpec,
    execute,
)
from rwa_calc.reporting.pillar3.templates import (
    CR10_CATEGORY_MAP,
    CR10_EQUITY_RISK_WEIGHTS,
    CR10_EQUITY_ROWS,
    CR10_SLOTTING_ROWS,
    HVCRE_RISK_WEIGHTS,
    SLOTTING_RISK_WEIGHTS,
    get_cr10_columns,
    get_cr10_subtemplates,
)

# Half-width of the inclusive band that matches an equity leg's applied simple
# risk weight (``reporting_rw``) to its CR10.5 row. The bands (190/290/370%) are
# ~1.0 apart, so ±0.05 isolates each without overlap while absorbing Float64
# round-trip dust.
_EQUITY_RW_TOL = 0.05


def _row_cells(row_name: str, *, is_total: bool) -> dict[str, CellSpec]:
    """The Float64 column bindings for one slotting CR10 row (col c is a post-step)."""
    if is_total:
        member = RowPredicate()
    else:
        member = RowPredicate(equals=(("slotting_category", CR10_CATEGORY_MAP[row_name]),))

    return {
        "a": CellSpec(
            SafeSum(("reporting_gross_drawn", "reporting_gross_interest")),
            predicate=replace(member, on_balance_sheet=True),
        ),
        "b": CellSpec(
            SafeSum(("reporting_gross_nominal", "reporting_gross_undrawn")),
            predicate=replace(member, on_balance_sheet=False),
        ),
        "d": CellSpec(Sum("reporting_ead"), predicate=member),
        "e": CellSpec(Sum("rwa_final"), predicate=member),
        "f": CellSpec(Sum("expected_loss"), predicate=member),
    }


def _equity_row_cells(row_ref: str, *, is_total: bool) -> dict[str, CellSpec]:
    """The Float64 column bindings for one CR10.5 equity band row.

    A band row narrows to the legs whose applied ``reporting_rw`` sits in the
    band; the Total row is the whole (already equity-simple) population. Equity
    is on-balance-sheet with no off-BS component, so col a == col d and col b is
    left unbound (null). Col c is a post-step.
    """
    if is_total:
        member = RowPredicate()
    else:
        rw = CR10_EQUITY_RISK_WEIGHTS[row_ref]
        member = RowPredicate(rw_between=(rw - _EQUITY_RW_TOL, rw + _EQUITY_RW_TOL))

    return {
        "a": CellSpec(Sum("reporting_ead"), predicate=member),
        "d": CellSpec(Sum("reporting_ead"), predicate=member),
        "e": CellSpec(Sum("rwa_final"), predicate=member),
        "f": CellSpec(Sum("expected_loss"), predicate=member),
    }


@cites("CRR Art. 438")
def build_cr10_spec(framework: str) -> TemplateSpec:
    """Build the CR10 slotting TemplateSpec (shared across a regime's slotting
    subtemplates — the ``sl_type`` narrowing happens before execution).

    Carries the Art. 438(e) citation for the slotting disclosure.
    """
    rows = tuple(CR10_SLOTTING_ROWS)
    cells: dict[tuple[str, str], CellSpec] = {}
    for row in rows:
        for col_ref, cell in _row_cells(row.name, is_total=row.is_total).items():
            cells[(row.ref, col_ref)] = cell
    return TemplateSpec(
        name="cr10",
        rows=rows,
        column_refs=tuple(col.ref for col in get_cr10_columns(framework)),
        cells=cells,
        empty_cell="null",
    )


@cites("CRR Art. 438")
@cites("CRR Art. 155(2)")
def build_cr10_equity_spec(framework: str) -> TemplateSpec:
    """Build the CR10.5 equity (Art. 155(2) IRB simple-RW) TemplateSpec.

    Rows are the three fixed supervisory bands + Total; a leg is placed by its
    applied ``reporting_rw``. The caller pre-narrows the frame to the
    simple-RW equity population, so this spec carries no population predicate.
    """
    rows = tuple(CR10_EQUITY_ROWS)
    cells: dict[tuple[str, str], CellSpec] = {}
    for row in rows:
        for col_ref, cell in _equity_row_cells(row.ref, is_total=row.is_total).items():
            cells[(row.ref, col_ref)] = cell
    return TemplateSpec(
        name="cr10_equity",
        rows=rows,
        column_refs=tuple(col.ref for col in get_cr10_columns(framework)),
        cells=cells,
        empty_cell="null",
    )


_CR10_SPECS: dict[str, TemplateSpec] = {
    framework: build_cr10_spec(framework) for framework in ("CRR", "BASEL_3_1")
}

_CR10_EQUITY_SPECS: dict[str, TemplateSpec] = {
    framework: build_cr10_equity_spec(framework) for framework in ("CRR", "BASEL_3_1")
}


def generate_cr10(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute CR10 per subtemplate over the sealed ledger.

    Preserves the imperative generator's contracts: missing EAD/RWA columns
    record "CR10: missing required columns"; a run with neither a slotting book
    nor Art. 155(2) simple-RW equity yields ``{}``; an empty non-equity
    subtemplate produces no dict entry while the CRR equity sheet is
    force-emitted (populated from the equity-simple population, not slotting).
    """
    if "ead_final" not in cols or not ({"rwa_final", "rwa"} & cols):
        errors.append("CR10: missing required columns")
        return {}
    data = results.collect()
    slotting = data.filter(pl.col("reporting_approach_origin") == "slotting")
    equity_simple = _equity_simple_population(data)
    if slotting.height == 0 and equity_simple.height == 0:
        return {}
    slotting_spec = _CR10_SPECS.get(framework) or build_cr10_spec(framework)
    equity_spec = _CR10_EQUITY_SPECS.get(framework) or build_cr10_equity_spec(framework)

    result: dict[str, pl.DataFrame] = {}
    for sl_key in get_cr10_subtemplates(framework):
        if sl_key == "equity":
            # CRR CR10.5: force-emitted (even when empty) to preserve the
            # always-present contract, drawn from the equity-simple population
            # rather than the slotting book.
            frame = execute(equity_spec, equity_simple)
            result[sl_key] = _with_equity_risk_weight_column(frame)
            continue
        type_data = _type_data(slotting, cols, sl_key, framework)
        if type_data.height == 0:
            continue
        frame = execute(slotting_spec, type_data)
        result[sl_key] = _with_risk_weight_column(frame, sl_key)
    return result


def _equity_simple_population(data: pl.DataFrame) -> pl.DataFrame:
    """The Art. 155(2) simple-RW equity legs — the CR10.5 population.

    Origin approach ``equity`` AND the calculator's ``equity_method`` tag
    ``irb_simple``; Art. 133 SA (100%/250%) and Art. 155(3) PD/LGD equity are
    excluded. An absent ``equity_method`` column (an equity-free run, or a
    pre-seal synthetic frame that never set it) matches nothing.
    """
    if "reporting_approach_origin" not in data.columns or "equity_method" not in data.columns:
        return data.clear()
    return data.filter(
        (pl.col("reporting_approach_origin") == "equity")
        & (pl.col("equity_method") == EquityApproach.IRB_SIMPLE.value)
    )


def _type_data(slotting: pl.DataFrame, cols: set[str], sl_key: str, framework: str) -> pl.DataFrame:
    """Subset the slotting book for one subtemplate: CRR groups IPRE + HVCRE
    under CR10.2; an absent ``sl_type`` column matches nothing."""
    if "sl_type" not in cols:
        return slotting.clear()
    if sl_key == "ipre" and framework != "BASEL_3_1":
        return slotting.filter(pl.col("sl_type").is_in(["ipre", "hvcre"]))
    return slotting.filter(pl.col("sl_type") == sl_key)


def _with_risk_weight_column(frame: pl.DataFrame, sl_key: str) -> pl.DataFrame:
    """Fill column c with the fixed Art. 153(5) Table A risk weight x100 per
    category row (Total stays null) — populated even on empty categories."""
    rw_map = HVCRE_RISK_WEIGHTS if sl_key == "hvcre" else SLOTTING_RISK_WEIGHTS
    expr: pl.Expr = pl.lit(None, dtype=pl.Float64)
    for row in CR10_SLOTTING_ROWS:
        if row.is_total:
            continue
        rw_value = rw_map.get(CR10_CATEGORY_MAP[row.name])
        if rw_value is None:
            continue
        expr = pl.when(pl.col("row_ref") == row.ref).then(pl.lit(rw_value * 100.0)).otherwise(expr)
    ordered = frame.columns
    return frame.with_columns(expr.alias("c")).select(ordered)


def _with_equity_risk_weight_column(frame: pl.DataFrame) -> pl.DataFrame:
    """Fill column c with the fixed Art. 155(2) simple risk weight x100 per band
    row (Total stays null) — populated even on empty bands."""
    expr: pl.Expr = pl.lit(None, dtype=pl.Float64)
    for row in CR10_EQUITY_ROWS:
        if row.is_total:
            continue
        rw_value = CR10_EQUITY_RISK_WEIGHTS.get(row.ref)
        if rw_value is None:
            continue
        expr = pl.when(pl.col("row_ref") == row.ref).then(pl.lit(rw_value * 100.0)).otherwise(expr)
    ordered = frame.columns
    return frame.with_columns(expr.alias("c")).select(ordered)
