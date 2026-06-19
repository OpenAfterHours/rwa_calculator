"""
Shared result-reader helpers for acceptance tests.

Pipeline position:
    Read-only consumers of the ``AggregatedResultBundle`` produced by
    ``PipelineOrchestrator.run_with_data`` — used by the CRR / Basel 3.1
    acceptance scenario modules to locate result rows and sum numeric fields.

Key responsibilities:
- ``find_exposure_rows`` — collect every result row (across the SA, IRB, and
  slotting result sets) whose ``exposure_reference`` contains a given substring.
- ``total_field`` — sum one numeric field across rows, treating missing / null
  values as zero (handles guarantee sub-row splits).
- ``get_guaranteed_row`` — select the single ``__G_`` guaranteed-portion sub-row
  for a loan reference from an already-collected result DataFrame.
- ``get_total_rwa`` — sum ``rwa_final`` across all sub-rows of a loan reference
  (``__G_`` guaranteed portion plus ``__REM`` remainder).

These functions were byte-identical private copies (``_find_rows`` / ``_total``,
``_get_guaranteed_row`` / ``_get_total_rwa``) in several acceptance modules. They
are pure readers over the result bundle / result DataFrame — no scenario
semantics — so they are lifted here, the nearest common parent of the
``basel31/`` and ``crr/`` acceptance directories, and imported as
``from tests.acceptance.conftest import find_exposure_rows, total_field``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle


def find_exposure_rows(results: AggregatedResultBundle, loan_ref: str) -> list[dict]:
    """Return all result rows whose exposure_reference contains *loan_ref*."""
    rows: list[dict] = []
    for lf in [results.sa_results, results.irb_results, results.slotting_results]:
        if lf is None:
            continue
        df = lf.filter(pl.col("exposure_reference").str.contains(loan_ref)).collect()
        rows.extend(df.to_dicts())
    return rows


def total_field(rows: list[dict], field: str) -> float:
    """Sum *field* across all rows (handles guarantee sub-row splits)."""
    return sum(r.get(field, 0.0) or 0.0 for r in rows)


def get_guaranteed_row(df: pl.DataFrame, loan_ref: str) -> dict:
    """
    Return the guaranteed-portion (``__G_``) sub-row for *loan_ref*.

    The CRM processor splits a guaranteed loan into:
      - ``<loan_ref>__G_<guarantor>``: guaranteed portion (carries the
        substituted / guarantor risk weight).
      - ``<loan_ref>__REM``: remainder (ead_final = 0 when fully covered).

    Asserts exactly one ``__G_`` sub-row exists for the loan and returns it as a
    dict.
    """
    rows = df.filter(
        (pl.col("parent_exposure_reference") == loan_ref)
        & pl.col("exposure_reference").str.contains("__G_")
    ).to_dicts()
    assert len(rows) == 1, (
        f"Expected exactly 1 guaranteed-portion row for {loan_ref!r}, got {len(rows)}. "
        f"All rows: "
        f"{df.select(['exposure_reference', 'parent_exposure_reference']).to_dicts()}"
    )
    return rows[0]


def get_total_rwa(df: pl.DataFrame, loan_ref: str) -> float:
    """
    Return total ``rwa_final`` for *loan_ref* (sum across all sub-rows).

    Both the ``__G_`` guaranteed portion and the ``__REM`` remainder carry
    ``parent_exposure_reference == loan_ref``. Summing ``rwa_final`` gives the
    consolidated RWA. For a 100%-covered loan the ``__REM`` sub-row has
    ead_final = 0 → rwa_final = 0, so the total equals the guaranteed sub-row's
    rwa_final.
    """
    sub_rows = df.filter(pl.col("parent_exposure_reference") == loan_ref)
    return sub_rows["rwa_final"].sum()
