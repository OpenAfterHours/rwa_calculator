"""
Row filters shared by the COREP and Pillar 3 generators.

Pipeline position:
    OutputAggregator -> {COREPGenerator, Pillar3Generator}
    (applied to pipeline result frames to slice rows per template cell)

Key responsibilities:
- Filter results to a single calculation approach (``approach_applied``)
- Split exposures into on-balance-sheet and off-balance-sheet subsets for
  templates that report the two sides separately (C 07.00 / C 08.x, CR4,
  CR5, CR6, CR10)

Missing-column policy: every filter here returns an EMPTY frame when none
of its discriminator columns is present. A missing discriminator must be a
detectable failure (an empty template cell), never a silent pass-through —
see ``filter_on_bs`` for the recorded drift decision.

References:
- Regulation (EU) 2021/451, Annex I/II (COREP templates)
- CRR Part 8 (Pillar 3 disclosure templates)
- PRA PS1/26 (Basel 3.1 reporting amendments)
"""

from __future__ import annotations

import polars as pl

from rwa_calc.reporting.kernel.columns import pick

# Default candidate names for the approach discriminator column. The COREP
# generator recognises only the canonical pipeline name; the Pillar 3
# generator additionally accepts the legacy ``approach`` alias and passes
# its own candidate tuple explicitly.
DEFAULT_APPROACH_CANDIDATES: tuple[str, ...] = ("approach_applied",)


def filter_by_approach(
    results: pl.LazyFrame,
    approach_value: str,
    cols: set[str],
    *,
    candidates: tuple[str, ...] = DEFAULT_APPROACH_CANDIDATES,
) -> pl.LazyFrame:
    """Filter results to a specific approach value.

    The approach column is resolved from *candidates* (first present wins).
    Returns an empty frame when no candidate column exists — a missing
    approach discriminator must not silently pass rows through.
    """
    approach_col = pick(cols, *candidates)
    if approach_col is None:
        return results.filter(pl.lit(False))
    return results.filter(pl.col(approach_col) == approach_value)


def filter_on_bs(data: pl.DataFrame, cols: set[str]) -> pl.DataFrame:
    """Filter to on-balance-sheet exposures.

    Uses ``bs_type == "ONB"`` when available, falling back to
    ``exposure_type == "loan"``.

    Missing-column decision (recorded during the kernel extraction): when
    NEITHER ``bs_type`` nor ``exposure_type`` is present, return an EMPTY
    frame. The two generator-private copies had drifted — COREP returned
    empty, Pillar 3 returned ALL rows. Returning all rows is anti-
    conservative: with no balance-sheet indicator, both the on-BS and
    off-BS template cells would otherwise receive the full population,
    double-counting every exposure. An empty cell is the detectable,
    conservative failure mode, so both generators now unify on it.
    """
    if "bs_type" in cols:
        return data.filter(pl.col("bs_type") == "ONB")
    if "exposure_type" in cols:
        return data.filter(pl.col("exposure_type") == "loan")
    return data.clear()


def filter_off_bs(data: pl.DataFrame, cols: set[str]) -> pl.DataFrame:
    """Filter to off-balance-sheet exposures.

    Uses ``bs_type == "OFB"`` when available, falling back to
    ``exposure_type in {"facility", "contingent", "facility_undrawn"}``.
    ``facility_undrawn`` is the unified pipeline's undrawn-commitment headroom
    leg (an off-balance-sheet Art. 111 commitment); ``"facility"`` is a dead
    legacy value kept for pre-unification synthetic frames. Returns an EMPTY
    frame when neither column is present (same missing-column decision as
    ``filter_on_bs`` — both generator copies already agreed on empty here).
    """
    if "bs_type" in cols:
        return data.filter(pl.col("bs_type") == "OFB")
    if "exposure_type" in cols:
        return data.filter(
            pl.col("exposure_type").is_in(["facility", "contingent", "facility_undrawn"])
        )
    return data.clear()
