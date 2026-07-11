"""
COREP OF 02.01 — output floor comparison (Basel 3.1 only), declarative.

Pipeline position:
    sealed aggregator-exit ledger + OutputFloorConfig gate
        -> ONE TemplateSpec -> cellspec.execute() -> DataFrame | None

Cell semantics (recorded decisions, this slice):

- B31-only: CRR returns None (a None bundle field, no frame — the golden
  manifest records ``of_02_01: null`` and omits the frame).
- The entity gate stays OUTSIDE the executor: framework check, then
  ``OutputFloorConfig.is_floor_applicable()`` (a bare boolean — OF 02.01
  reads NOTHING else off the config and nothing off OutputFloorSummary),
  then the column-presence guard with the retired error string.
- Rows 0010 (credit risk excl. CCR) and 0080 (Total) carry IDENTICAL
  full-portfolio values — the recorded "S1871 collapse" for a credit-risk-
  only calculator; 0080 is NOT the sum of rows 0010-0070. Rows 0020-0070
  (CCR/CVA/securitisation/market/op-risk/other) are a FIXED all-null set.
- Column 0010 sums ``rwa_pre_floor`` — the PRE-floor modelled RWA (the
  mirror image of the estate-wide "rwa_final is already post-floor" trap:
  here the pre-floor carrier is deliberately the source). Columns
  0020/0040 sum ``sa_rwa``; column 0030 (U-TREA) = 0010 + 0020, an
  intra-row Formula (the retired Annex II §1.3.2 convention).
- NO empty-frame early return: an empty portfolio still yields the 8-row
  frame with 0.0 on the populated rows.

References:
- PRA PS1/26 Art. 92 para 2A/3A (output floor scope); Annex II §1.3.2
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Formula,
    Sum,
    TemplateSpec,
    execute,
)
from rwa_calc.reporting.corep.templates import (
    OF_02_01_COLUMN_REFS,
    OF_02_01_ROW_SECTIONS,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_calc.contracts.config import OutputFloorConfig

# The fixed all-null risk-type rows (out of scope for a credit-risk-only
# calculator): CCR, CVA, securitisation, market risk, op risk, other.
_NULL_ROWS: tuple[str, ...] = ("0020", "0030", "0040", "0050", "0060", "0070")

_POPULATED_ROWS: tuple[str, ...] = ("0010", "0080")


def _u_trea(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0030 (U-TREA) = 0010 + 0020 — the retired intra-row sum."""
    return (cells["0010"] or 0.0) + (cells["0020"] or 0.0)


@cites("PS1/26, paragraph 1.3")
def generate_of_02_01(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
    *,
    output_floor_config: OutputFloorConfig | None = None,
) -> pl.DataFrame | None:
    """Execute OF 02.01 (modelled U-TREA vs standardised S-TREA)."""
    if framework != "BASEL_3_1":
        return None
    # Exempt entities do not report the output floor comparison
    # (Art. 92 para 2A restricts the floor to 3 entity-type/basis combos).
    if output_floor_config is not None and not output_floor_config.is_floor_applicable():
        return None
    if "rwa_pre_floor" not in cols or "sa_rwa" not in cols:
        errors.append(
            "OF 02.01 skipped: rwa_pre_floor and/or sa_rwa columns not found "
            "(output floor not applied)"
        )
        return None
    rows = tuple(row for section in OF_02_01_ROW_SECTIONS for row in section.rows)
    column_refs = tuple(OF_02_01_COLUMN_REFS)
    cells: dict[tuple[str, str], CellSpec] = {}
    for ref in _POPULATED_ROWS:
        cells[(ref, "0010")] = CellSpec(Sum("rwa_pre_floor"))
        cells[(ref, "0020")] = CellSpec(Sum("sa_rwa"))
        cells[(ref, "0030")] = CellSpec(Formula(refs=("0010", "0020"), fn=_u_trea))
        cells[(ref, "0040")] = CellSpec(Sum("sa_rwa"))
    spec = TemplateSpec(
        name="of_02_01", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
    )
    frame = execute(spec, results)
    return _null_fixed_rows(frame, list(_NULL_ROWS))


def _null_fixed_rows(frame: pl.DataFrame, row_refs: list[str]) -> pl.DataFrame:
    """Render the FIXED out-of-scope row set all-null (exact null positions
    are golden-gated; the zero policy would otherwise render 0.0)."""
    if not row_refs:
        return frame
    value_cols = [col for col in frame.columns if col not in ("row_ref", "row_name")]
    return frame.with_columns(
        pl.when(pl.col("row_ref").is_in(row_refs))
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col(col))
        .alias(col)
        for col in value_cols
    )
