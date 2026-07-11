"""
Pillar 3 CR10 — Specialised lending (and CRR equity) under slotting, declarative.

Pipeline position:
    sealed aggregator-exit ledger -> one TemplateSpec (shared) per
    sl_type subtemplate -> cellspec.execute() -> dict[sl_key, DataFrame]

Cell semantics (recorded decisions, this slice):

- The population is the ORIGIN slotting book (``reporting_approach_origin ==
  "slotting"``); a guaranteed slotting exposure's covered leg leaves the
  slotting approach entirely, so the origin basis is the obligor basis by
  construction. CR10 has no exposure-class axis — nothing for F3 to retarget.
- Subtemplates split on ``sl_type`` per the regime's Art. 153(5) table:
  CRR groups IPRE + HVCRE under CR10.2 and carries the CR10.5 equity
  simple-RW sheet (force-emitted even when empty); Basel 3.1 keeps HVCRE as
  its own CR10.5 and has no equity sheet. An empty non-equity subtemplate
  produces no dict entry.
- Rows are the five supervisory categories (Strong/Good/Satisfactory/Weak/
  Default, matched on ``slotting_category`` via the tolerant per-value
  term) plus Total. Column a/b are the gross on-/off-BS amounts; d/e/f sum
  ``reporting_ead`` / ``rwa_final`` / ``expected_loss`` (null on an empty
  category — the recorded a-b-zero vs d-f-null asymmetry the goldens pin).
- Column c is the FIXED regulatory risk weight ("This is a fixed column.
  It shall not be altered" — Art. 153(5) Table A), injected by a module
  post-step from the template constants (x100; Total row null) — populated
  even on empty categories. The constants carry the >= 2.5y reference
  weights; the short-maturity preferential column-c variant and pack-homing
  of the display constants are recorded follow-ups (plan §7).

References:
- CRR Art. 438(e); Art. 153(5) (Table 1) / Art. 155(2) (CRR equity);
  PRA PS1/26 Annex XXIV (UKB CR10, Table A)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8)
"""

from __future__ import annotations

from dataclasses import replace

import polars as pl
from watchfire import cites

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
    CR10_SLOTTING_ROWS,
    HVCRE_RISK_WEIGHTS,
    SLOTTING_RISK_WEIGHTS,
    get_cr10_columns,
    get_cr10_subtemplates,
)


def _row_cells(row_name: str, *, is_total: bool) -> dict[str, CellSpec]:
    """The Float64 column bindings for one CR10 row (col c is a post-step)."""
    if is_total:
        member = RowPredicate()
    else:
        member = RowPredicate(equals=(("slotting_category", CR10_CATEGORY_MAP[row_name]),))

    return {
        "a": CellSpec(
            SafeSum(("drawn_amount", "interest")),
            predicate=replace(member, on_balance_sheet=True),
        ),
        "b": CellSpec(
            SafeSum(("nominal_amount", "undrawn_amount")),
            predicate=replace(member, on_balance_sheet=False),
        ),
        "d": CellSpec(Sum("reporting_ead"), predicate=member),
        "e": CellSpec(Sum("rwa_final"), predicate=member),
        "f": CellSpec(Sum("expected_loss"), predicate=member),
    }


@cites("CRR Art. 438")
def build_cr10_spec(framework: str) -> TemplateSpec:
    """Build the CR10 TemplateSpec (shared across a regime's subtemplates —
    the ``sl_type`` narrowing happens before execution).

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


_CR10_SPECS: dict[str, TemplateSpec] = {
    framework: build_cr10_spec(framework) for framework in ("CRR", "BASEL_3_1")
}


def generate_cr10(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute CR10 per sl_type subtemplate over the sealed ledger.

    Preserves the imperative generator's contracts: missing EAD/RWA columns
    record "CR10: missing required columns"; an empty slotting population
    yields ``{}``; an empty non-equity subtemplate produces no dict entry
    while the CRR equity sheet is force-emitted.
    """
    if "ead_final" not in cols or not ({"rwa_final", "rwa"} & cols):
        errors.append("CR10: missing required columns")
        return {}
    data = results.collect()
    slotting = data.filter(pl.col("reporting_approach_origin") == "slotting")
    if slotting.height == 0:
        return {}
    spec = _CR10_SPECS.get(framework) or build_cr10_spec(framework)

    result: dict[str, pl.DataFrame] = {}
    for sl_key in get_cr10_subtemplates(framework):
        type_data = _type_data(slotting, cols, sl_key, framework)
        if type_data.height == 0 and sl_key != "equity":
            continue
        frame = execute(spec, type_data)
        result[sl_key] = _with_risk_weight_column(frame, sl_key)
    return result


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
