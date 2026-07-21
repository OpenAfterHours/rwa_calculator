"""
Pillar 3 CR5 — SA risk-weight allocation, as a declarative TemplateSpec.

Pipeline position:
    sealed aggregator-exit ledger -> _with_rw_bucket() -> build_cr5_spec(framework)
        -> cellspec.execute() -> CR5 DataFrame

Cell semantics (the recorded F3 class-basis decision —
docs/plans/phase7-declarative-reporting.md §6):

- The template narrows to the ORIGIN standardised population
  (``reporting_approach_origin``, matching CR4/OV1).
- CR5 carries ONLY post-CF/post-CRM figures (there is no "before CRM" column
  anywhere in the template), so every class row keys uniformly on the
  post-substitution ``reporting_class`` (C 07.00 column 0200 basis: the
  covered leg of a guaranteed exposure bands in the protection provider's
  row at the substituted risk weight).
- Risk-weight band columns allocate ``reporting_ead`` on the derived
  ``cr5_rw_bucket`` column with the generator-heritage ±0.5pp half-open
  window. Rows that fired the Art. 123B 1.5x currency-mismatch multiplier
  band on their PRE-multiplier risk weight (PS1/26 Annex XX: "reported
  against the risk weight which would have applied if the currency mismatch
  multiplier was not applied"); the RWEA elsewhere still reflects the
  multiplier.
- "Other/Deducted" is the residual Formula max(0, Total - Σ bands).
- "Of which: unrated" equals the Total — ``sa_cqs`` is never produced by the
  engine and the seal strips undeclared columns, so the all-unrated fallback
  IS the recorded behaviour (plan F6; an engine rating-presence column is
  the recorded fix path).
- Basel 3.1 rows 9/9f/9g additionally match the physical 55%-LTV split legs
  by ``re_split_role`` ("secured"/"residual") — the Art. 124F/124L legs
  carry reclassified exposure classes, so the role limb (not the class
  limb) pulls them into the "Secured by mortgages" rows. The role lists
  mirror the retired imperative predicate exactly; widening them to the
  splitter's "secured_rre"/"secured_cre"/"whole" roles is a recorded
  follow-up (plan §7), not a silent change.
- Basel 3.1 extras: ba/bb gross on-/off-BS amounts, bc the EAD-weighted
  average CF over off-BS rows, bd the post-CF-and-CRM total.
- Bound cells report 0.0 for an empty subset (per-cell zero override);
  unbound rows (11/13/14, B31 9a-9e) stay all-null; bc stays null when
  off-BS is empty or ``ccf`` is absent.

References:
- CRR Art. 444(e); PRA PS1/26 Annex XX (UK/UKB CR5 instructions, incl. the
  Art. 123B and 55%-LTV two-part reporting overrides)
- COREP Annex II C 07.00 ¶56A/¶65 (substitution reallocation)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8, decision F3)
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Formula,
    RowPredicate,
    SafeSum,
    Sum,
    TemplateSpec,
    WeightedAvg,
    execute,
)
from rwa_calc.reporting.pillar3.templates import (
    get_cr5_columns,
    get_cr5_risk_weights,
    get_cr5_rows,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from rwa_calc.reporting.pillar3.templates import P3Row

# Band-match tolerance: ±0.5pp half-open window around each disclosed risk
# weight (generator heritage — a blended RW like 0.2458 lands in the 25% band).
_BAND_TOL = 0.005

# The derived banding column added by ``_with_rw_bucket``.
_BUCKET_COL = "cr5_rw_bucket"


def _membership(row: P3Row) -> RowPredicate | None:
    """The row-membership predicate for one CR5 row (None = inert row).

    Class membership keys on the post-substitution ``reporting_class``; the
    Basel 3.1 rows carrying ``re_split_roles`` also match the physical
    55%-LTV split legs by role (a union — the legs are reclassified out of
    the row's class tuple).
    """
    if row.is_total:
        return RowPredicate()
    limbs: list[RowPredicate] = []
    if row.exposure_classes:
        limbs.append(RowPredicate(classes=row.exposure_classes))
    limbs.extend(RowPredicate(equals=(("re_split_role", role),)) for role in row.re_split_roles)
    if not limbs:
        return None
    if len(limbs) == 1:
        return limbs[0]
    return RowPredicate(any_of=tuple(limbs))


def _other_deducted_fn(
    band_refs: tuple[str, ...], total_ref: str
) -> Callable[[Mapping[str, float | None], bool], float | None]:
    """Residual Formula: max(0, Total - Σ band allocations)."""

    def fn(cells: Mapping[str, float | None], _prior: bool) -> float | None:
        total = cells[total_ref] or 0.0
        allocated = sum(cells[ref] or 0.0 for ref in band_refs)
        return max(0.0, total - allocated)

    return fn


@cites("CRR Art. 444")
def build_cr5_spec(framework: str) -> TemplateSpec:
    """Build the CR5 TemplateSpec for one framework's band/row layout.

    Carries the Art. 444(e) citation for the SA risk-weight allocation
    disclosure, keyed on the post-substitution class per the recorded F3
    decision.
    """
    rows = tuple(get_cr5_rows(framework))
    bands = get_cr5_risk_weights(framework)
    column_refs = tuple(col.ref for col in get_cr5_columns(framework))
    n = len(bands)
    band_refs = column_refs[:n]
    other_ref, total_ref, unrated_ref = column_refs[n], column_refs[n + 1], column_refs[n + 2]
    is_b31 = framework == "BASEL_3_1"
    residual = _other_deducted_fn(band_refs, total_ref)

    cells: dict[tuple[str, str], CellSpec] = {}
    for row in rows:
        member = _membership(row)
        if member is None:
            continue
        for i, (rw_value, _label) in enumerate(bands):
            band = replace(
                member, between=((_BUCKET_COL, rw_value - _BAND_TOL, rw_value + _BAND_TOL),)
            )
            cells[(row.ref, band_refs[i])] = CellSpec(
                Sum("reporting_ead"), predicate=band, empty_cell="zero"
            )
        cells[(row.ref, other_ref)] = CellSpec(Formula(refs=(*band_refs, total_ref), fn=residual))
        cells[(row.ref, total_ref)] = CellSpec(
            Sum("reporting_ead"), predicate=member, empty_cell="zero"
        )
        cells[(row.ref, unrated_ref)] = CellSpec(
            Sum("reporting_ead"), predicate=member, empty_cell="zero"
        )
        if is_b31:
            cells[(row.ref, "ba")] = CellSpec(
                SafeSum(("reporting_gross_drawn", "reporting_gross_interest")),
                predicate=replace(member, on_balance_sheet=True),
            )
            cells[(row.ref, "bb")] = CellSpec(
                SafeSum(("reporting_gross_nominal", "reporting_gross_undrawn")),
                predicate=replace(member, on_balance_sheet=False),
            )
            cells[(row.ref, "bc")] = CellSpec(
                WeightedAvg("ccf", weight="reporting_ead"),
                predicate=replace(member, on_balance_sheet=False),
            )
            cells[(row.ref, "bd")] = CellSpec(
                Sum("reporting_ead"), predicate=member, empty_cell="zero"
            )
    return TemplateSpec(
        name="cr5",
        rows=rows,
        column_refs=column_refs,
        cells=cells,
        predicate=RowPredicate(approaches_origin=("standardised",)),
        empty_cell="null",
    )


_CR5_SPECS: dict[str, TemplateSpec] = {
    framework: build_cr5_spec(framework) for framework in ("CRR", "BASEL_3_1")
}


def generate_cr5(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> pl.DataFrame | None:
    """Execute CR5 over the full sealed ledger (plus the derived bucket).

    Preserves the imperative generator's error contract: a missing
    ``ead_final`` or ``risk_weight`` column records the CR5 error and yields
    no template.
    """
    if "ead_final" not in cols or "risk_weight" not in cols:
        errors.append("CR5: missing EAD or risk_weight column")
        return None
    spec = _CR5_SPECS.get(framework) or build_cr5_spec(framework)
    return execute(spec, _with_rw_bucket(results, cols))


def _with_rw_bucket(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    """Add the CR5 banding column ``cr5_rw_bucket``.

    PS1/26 Annex XX (UKB CR5): rows that fired the Art. 123B currency-
    mismatch multiplier band on their PRE-multiplier risk weight; everything
    else bands on the sealed per-leg risk weight. Frames without the
    snapshot columns (CRR runs — the stage no-ops) band on it directly.
    """
    base = pl.col("reporting_rw" if "reporting_rw" in cols else "risk_weight")
    if {"risk_weight_pre_currency_mismatch", "currency_mismatch_multiplier_applied"} <= cols:
        bucket = (
            pl.when(pl.col("currency_mismatch_multiplier_applied").fill_null(value=False))
            .then(pl.col("risk_weight_pre_currency_mismatch"))
            .otherwise(base)
        )
    else:
        bucket = base
    return results.with_columns(bucket.alias(_BUCKET_COL))
