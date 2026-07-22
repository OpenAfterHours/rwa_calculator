"""
Column discovery helpers shared by the COREP and Pillar 3 generators.

Pipeline position:
    OutputAggregator -> {COREPGenerator, Pillar3Generator}
    (called at generator entry to resolve which result columns are present)

Key responsibilities:
- Materialise the set of available column names from a LazyFrame schema
  without collecting the frame
- Resolve the first present column name from an ordered candidate list
  (pipeline results expose the same quantity under historical aliases,
  e.g. ``ead_final`` / ``final_ead`` / ``ead``)

References:
- Regulation (EU) 2021/451, Annex I/II (COREP templates)
- CRR Part 8 (Pillar 3 disclosure templates)
"""

from __future__ import annotations

import polars as pl


def available_columns(lf: pl.LazyFrame) -> set[str]:
    """Get the set of column names in a LazyFrame without collecting."""
    return set(lf.collect_schema().names())


def pick(cols: set[str], *candidates: str) -> str | None:
    """Return the first column name from *candidates* that exists in *cols*."""
    for c in candidates:
        if c in cols:
            return c
    return None


#: Raw gross-exposure carrier -> its floored ``reporting_gross_*`` twin. The
#: aggregator seals the floored twins (raw amount clipped at 0) so a negative
#: on-balance netting deposit (CRR Art. 195/219) never makes a gross-exposure
#: template cell report a negative figure (CRR Art. 111 SA / Art. 166 IRB).
_GROSS_CARRIER_MAP: dict[str, str] = {
    "drawn_amount": "reporting_gross_drawn",
    "interest": "reporting_gross_interest",
    "nominal_amount": "reporting_gross_nominal",
    "undrawn_amount": "reporting_gross_undrawn",
}


def gross_carrier(cols: set[str], raw_name: str) -> str:
    """Resolve a raw gross carrier to its floored ``reporting_gross_*`` twin.

    Prefers the sealed floored twin when present in *cols*, else falls back to
    the raw column name (older synthetic unit frames that predate the seal).
    A name with no floored twin is returned unchanged.
    """
    floored = _GROSS_CARRIER_MAP.get(raw_name)
    return floored if floored is not None and floored in cols else raw_name


def gross_carriers(cols: set[str], *raw_names: str) -> tuple[str, ...]:
    """Resolve a group of raw gross carriers to their floored twins.

    Order-preserving convenience over :func:`gross_carrier` for the
    ``SafeSum`` gross-exposure cells (COREP C 07/C 08).
    """
    return tuple(gross_carrier(cols, name) for name in raw_names)
