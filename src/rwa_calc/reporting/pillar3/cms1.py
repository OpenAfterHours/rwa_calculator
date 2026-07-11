"""
Pillar 3 CMS1 — Modelled vs standardised RWEA comparison by risk type,
declarative (Basel 3.1 only).

Pipeline position:
    sealed aggregator-exit ledger -> build_cms1_spec() -> cellspec.execute()
        -> CMS1 DataFrame

Cell semantics (recorded decisions, this slice):

- Basel 3.1 only ("shall be completed only by firms that use the internal
  model approaches set out in Article 92(3A)"); returns None under CRR.
- Only the credit-risk row 0010 and the Total row 0080 are populated (with
  identical portfolio-level values); rows 0020-0070 (CCR, CVA,
  securitisation, market, operational, residual) are outside the
  credit-risk engine's scope — recorded-empty.
- Column a sums the actual ``rwa_final`` of the MODELLED origin approaches
  (F-IRB / A-IRB / slotting); column b sums the actual RWA of the
  standardised-approaches portfolio — the explicit origin-approach
  complement ``("standardised", "equity")``, because "exposures calculated
  according to the SA for credit risk include equity exposures subject to
  the IRB Equity Transitional" (the OV1 row-2 precedent); column c = a + b
  (total actual, post-output-floor since ``rwa_final`` is the floored
  figure); column d sums ``sa_rwa`` — the full-standardised S-TREA basis
  the output floor applies to. ``sa_rwa`` is the pre-supporting-factor
  SA-equivalent (the engine's floor convention; the post-factor variant
  and the floor's fallback-path divergence are recorded follow-ups).

References:
- PRA PS1/26 Art. 456(1)(a), Art. 2a(1); Annex II (UKB CMS1 instructions)
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
from rwa_calc.reporting.pillar3.templates import CMS1_COLUMNS, CMS1_ROWS

if TYPE_CHECKING:
    from collections.abc import Mapping

    import polars as pl

# The origin-approach split: modelled vs the explicit standardised-side
# complement (equity counts as SA under the Basel 3.1 equity transitional).
MODELLED_APPROACHES: tuple[str, ...] = ("foundation_irb", "advanced_irb", "slotting")
STANDARDISED_APPROACHES: tuple[str, ...] = ("standardised", "equity")

# The two populated row refs (credit risk + Total — identical values).
_POPULATED_REFS: tuple[str, ...] = ("0010", "0080")


def _total_actual(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """Column c = a + b (the total actual RWA)."""
    return (cells["a"] or 0.0) + (cells["b"] or 0.0)


@cites("PS1/26, paragraph 456")
def build_cms1_spec() -> TemplateSpec:
    """Build the CMS1 TemplateSpec (single Basel 3.1 layout).

    Carries the Art. 456(1)(a) citation for the by-risk-type modelled vs
    standardised RWEA comparison.
    """
    cells: dict[tuple[str, str], CellSpec] = {}
    for ref in _POPULATED_REFS:
        cells[(ref, "a")] = CellSpec(
            Sum("rwa_final"),
            predicate=RowPredicate(approaches_origin=MODELLED_APPROACHES),
            empty_cell="zero",
        )
        cells[(ref, "b")] = CellSpec(
            Sum("rwa_final"),
            predicate=RowPredicate(approaches_origin=STANDARDISED_APPROACHES),
            empty_cell="zero",
        )
        cells[(ref, "c")] = CellSpec(Formula(refs=("a", "b"), fn=_total_actual))
        cells[(ref, "d")] = CellSpec(Sum("sa_rwa"))
    return TemplateSpec(
        name="cms1",
        rows=tuple(CMS1_ROWS),
        column_refs=tuple(col.ref for col in CMS1_COLUMNS),
        cells=cells,
        empty_cell="null",
    )


_CMS1_SPEC: TemplateSpec = build_cms1_spec()


def generate_cms1(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> pl.DataFrame | None:
    """Execute CMS1 over the full sealed ledger (Basel 3.1 only).

    Preserves the imperative generator's contracts: None under CRR; a
    missing RWA column records "CMS1: missing RWA column" and yields no
    template; column d is null when ``sa_rwa`` is absent (CRR-style frames
    or portfolios outside the output-floor scope).
    """
    if framework != "BASEL_3_1":
        return None
    if not ({"rwa_final", "rwa"} & cols):
        errors.append("CMS1: missing RWA column")
        return None
    return execute(_CMS1_SPEC, results)
