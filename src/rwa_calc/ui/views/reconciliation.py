"""
Framework-agnostic parallel-run reconciliation views.

Pipeline position:
    ReconciliationResponse (api/models.py, wrapping engine/reconciliation.py)
        -> ui.views.reconciliation -> plain dicts / Polars DataFrames

Key responsibilities:
- Turn a ``ReconciliationResponse`` into presentation-ready data structures for
  the four drill-down tiers (headline tie-out, per-component summary, segment
  tables, the break worklist, and the per-key forensic frame) with NO
  UI-framework imports, so the FastAPI/Jinja app renders the same numbers the
  ``CreditRiskCalc.reconcile()`` API produces.
- Project the very wide ``component_reconciliation`` frame down to a readable set
  of columns for on-screen display; the full forensic detail (explain / input
  drivers, relative deltas) stays available via the CSV export.

Bucket label constants are imported from the engine (its single source) so the
UI and the engine summaries never drift.

References:
- Canonical components: data/schemas.RECONCILABLE_COMPONENTS
- Config grammar: api/reconciliation.load_reconciliation_config
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.engine.reconciliation import (
    BUCKET_BREAK,
    BUCKET_EXACT,
    BUCKET_MISSING_LEFT,
    BUCKET_MISSING_RIGHT,
    BUCKET_WITHIN,
)

if TYPE_CHECKING:
    from rwa_calc.api.models import ReconciliationResponse

# The default mapping shown in the page's TOML editor. Kept as the single source
# the page route, the REST default and the tests all reference. ``legacy_file``
# is resolved relative to the submitted data path (see api.reconciliation).
DEFAULT_MAPPING_TOML = """\
# Edit this mapping to match your legacy output file.
legacy_file   = "./legacy_output.csv"
legacy_format = "csv"
legacy_keys   = ["exposure_reference"]
our_keys      = ["exposure_reference"]
top_n         = 50

[components.rwa]
legacy_column = "RWA"
# scale = 1_000_000   # if legacy RWA is in millions

[components.ead]
legacy_column = "EAD"

# [components.risk_weight]
# legacy_column = "RW_pct"
# unit = "percent"

# [components.exposure_class]
# legacy_column = "Asset_Class"
# value_map = { CORP = "corporate", RETAIL = "retail" }
"""

# The pseudo-bucket "(all)" plus the engine's five row-level buckets, in the
# order the forensic-tier filter offers them (break first — the default view).
ALL_BUCKETS = "(all)"
BUCKET_CHOICES: tuple[str, ...] = (
    ALL_BUCKETS,
    BUCKET_BREAK,
    BUCKET_WITHIN,
    BUCKET_EXACT,
    BUCKET_MISSING_LEFT,
    BUCKET_MISSING_RIGHT,
)

# On-screen forensic row cap; the full frame is available via the CSV export.
_FORENSIC_LIMIT = 200


def headline_stats(response: ReconciliationResponse) -> list[dict]:
    """Tier 1 — one tie-out stat per additive component (our vs legacy total)."""
    tie = response.collect_totals_tie_out()
    stats: list[dict] = []
    for row in tie.iter_rows(named=True):
        delta_pct = row.get("delta_pct")
        stats.append(
            {
                "component": str(row["component"]),
                "our_total": _f(row.get("our_total")),
                "legacy_total": _f(row.get("legacy_total")),
                "delta_pct": float(delta_pct) if delta_pct is not None else None,
            }
        )
    return stats


def summary_by_component_table(response: ReconciliationResponse) -> pl.DataFrame:
    """Tier 1 — per-component bucket counts, summed |delta| and break rate."""
    return response.collect_summary_by_component()


def segment_tables(response: ReconciliationResponse) -> dict[str, pl.DataFrame]:
    """Tier 2 — where breaks concentrate: by bucket, exposure class and approach."""
    by_class: pl.DataFrame = response.bundle.summary_by_exposure_class.collect()
    by_approach: pl.DataFrame = response.bundle.summary_by_approach.collect()
    return {
        "by_bucket": response.collect_summary_by_bucket(),
        "by_class": by_class,
        "by_approach": by_approach,
    }


def breaks_table(response: ReconciliationResponse) -> pl.DataFrame:
    """Tier 3 — the long-format break worklist, already ranked by materiality."""
    return response.collect_breaks_detail()


def forensic_table(
    response: ReconciliationResponse, bucket: str, *, limit: int = _FORENSIC_LIMIT
) -> tuple[list[str], list[dict], int]:
    """Tier 4 — per-key reconciliation, filtered by row bucket and projected.

    Returns ``(columns, rows, total)`` where *total* is the row count before the
    on-screen ``limit`` is applied, so the template can show "N of M". The wide
    explain / input / relative-delta columns are dropped here — they remain in the
    CSV export.
    """
    df = response.collect_component_reconciliation()
    if bucket != ALL_BUCKETS and "row_bucket" in df.columns:
        df = df.filter(pl.col("row_bucket") == bucket)
    total = df.height
    columns = _readable_recon_columns(df)
    rows = df.select(columns).head(limit).fill_nan(None).to_dicts()
    return columns, rows, total


def tie_out_chart_items(response: ReconciliationResponse) -> list[tuple[str, float, float]]:
    """Grouped-bar items (component, legacy_total, our_total) for the tie-out chart."""
    tie = response.collect_totals_tie_out()
    return [
        (str(row["component"]).upper(), _f(row.get("legacy_total")), _f(row.get("our_total")))
        for row in tie.iter_rows(named=True)
    ]


def abs_delta_chart_items(response: ReconciliationResponse) -> list[tuple[str, float]]:
    """Horizontal-bar items (component, sum_abs_delta) — where the money differs."""
    summary = response.collect_summary_by_component()
    if "sum_abs_delta" not in summary.columns:
        return []
    items = [
        (str(row["component"]).upper(), _f(row.get("sum_abs_delta")))
        for row in summary.iter_rows(named=True)
        if row.get("sum_abs_delta") is not None
    ]
    return sorted(items, key=lambda it: it[1], reverse=True)


# =============================================================================
# Private helpers
# =============================================================================


def _readable_recon_columns(df: pl.DataFrame) -> list[str]:
    """Project the wide per-key frame to a display-friendly column set.

    Keeps the join key, then ``legacy_/our_/<bucket>/abs_delta`` per active
    component (in the frame's natural registry order), then the row rollups.
    Drops relative deltas, explain and input columns — too wide for a screen.
    """
    present = df.columns
    cols: list[str] = []
    if "_recon_key" in present:
        cols.append("_recon_key")
    for name in _component_names(present):
        for candidate in (f"legacy_{name}", f"our_{name}", f"{name}_bucket", f"abs_delta_{name}"):
            if candidate in present and candidate not in cols:
                cols.append(candidate)
    for rollup in ("worst_component", "row_bucket"):
        if rollup in present and rollup not in cols:
            cols.append(rollup)
    return cols or present


def _component_names(columns: list[str]) -> list[str]:
    """Active component names, in column order, inferred from ``<name>_bucket``."""
    suffix = "_bucket"
    return [c[: -len(suffix)] for c in columns if c.endswith(suffix) and c != "row_bucket"]


def _f(value: object) -> float:
    """Coerce a possibly-null numeric cell to a float (null -> 0.0)."""
    return float(value) if value is not None else 0.0  # type: ignore[arg-type]
