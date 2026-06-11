"""
Template row-dict construction helpers shared by the COREP and Pillar 3 generators.

Pipeline position:
    OutputAggregator -> {COREPGenerator, Pillar3Generator}
    (used while assembling the fixed row layout of each template DataFrame)

Key responsibilities:
- Build an all-null row dict for template rows whose underlying data subset
  cannot be computed (missing discriminator columns, no matching class)

References:
- Regulation (EU) 2021/451, Annex I/II (COREP templates)
- CRR Part 8 (Pillar 3 disclosure templates)
"""

from __future__ import annotations


def null_row(row_ref: str, row_name: str, column_refs: list[str]) -> dict[str, object]:
    """Build a row dict with null values for every template column."""
    row: dict[str, object] = {"row_ref": row_ref, "row_name": row_name}
    for ref in column_refs:
        row[ref] = None
    return row
