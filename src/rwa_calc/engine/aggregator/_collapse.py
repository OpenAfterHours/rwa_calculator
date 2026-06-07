"""
Sub-row collapse helper for parallel-run reconciliation.

Internal module — not part of the public API.

Our results frame splits a single loan into multiple rows:
- guarantee splits carry ``parent_exposure_reference`` and a suffixed
  ``exposure_reference`` (``__G_<guarantor>`` / ``__REM`` / ``__REM_FL`` /
  ``__REM_SEN``) — see engine/crm/guarantees.py;
- real-estate splits carry ``split_parent_id`` — see engine/re_splitter.py.

A legacy calculator typically reports one row per loan, so before reconciling we
collapse our sub-rows back to a single grain. ``aggregate_to_key_grain`` does this
lazily for either the default exposure grain (coalescing the parent-link columns)
or an arbitrary composite/custom key (e.g. counterparty + facility), summing the
additive money fields, recomputing ratio columns (risk weight) from the summed
numerator/denominator, taking the first value for everything else, and flagging
groups whose categoricals are heterogeneous.
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from rwa_calc.data.schemas import (
    ADDITIVE_OUTPUT_FIELDS,
    RECON_EAD_CANDIDATES,
    RECON_HETEROGENEITY_COLUMNS,
    RECON_PARENT_KEY_COLUMNS,
    RECON_RATIO_COLUMNS,
    RECON_RWA_CANDIDATES,
)

# Default reconciliation grain: one row per (collapsed) exposure.
_DEFAULT_KEY: tuple[str, ...] = ("exposure_reference",)

# Output column flagging a group that aggregated heterogeneous categoricals.
HETEROGENEITY_FLAG: str = "recon_grain_heterogeneous"

_EAD_ZERO_GUARD: float = 1e-10


def aggregate_to_key_grain(
    results: pl.LazyFrame,
    key_columns: Sequence[str] = _DEFAULT_KEY,
) -> pl.LazyFrame:
    """Collapse our results frame to one row per reconciliation key.

    Args:
        results: Our per-exposure results LazyFrame (e.g.
            ``CalculationResponse.scan_results()``), possibly containing guarantee
            and real-estate sub-rows.
        key_columns: The grain to collapse to. The default ``("exposure_reference",)``
            collapses sub-rows back to their parent exposure (coalescing the
            parent-link columns). Any other key (e.g. counterparty + facility) is
            grouped on directly.

    Returns:
        A LazyFrame with one row per key. Additive money fields are summed, ratio
        columns (risk weight) recomputed from summed RWA / EAD, all other columns
        taken from the first row of the group, plus a boolean
        ``recon_grain_heterogeneous`` column.

    Raises:
        ValueError: If a non-default ``key_columns`` references a column absent
            from ``results`` (the caller is expected to validate keys first and
            surface a data-quality error rather than rely on this).
    """
    key_columns = tuple(key_columns)
    schema_names = results.collect_schema().names()
    present = set(schema_names)

    if key_columns == _DEFAULT_KEY:
        results = _coalesce_to_parent(results, present)
        group_cols: list[str] = ["exposure_reference"]
    else:
        missing = [c for c in key_columns if c not in present]
        if missing:
            raise ValueError(f"key columns not present on results frame: {missing}")
        group_cols = list(key_columns)

    rwa_col = _first_present(RECON_RWA_CANDIDATES, present)
    ead_col = _first_present(RECON_EAD_CANDIDATES, present)
    recomputable_ratios = (
        [c for c in RECON_RATIO_COLUMNS if c in present] if (rwa_col and ead_col) else []
    )

    agg_exprs = _build_agg_exprs(schema_names, group_cols, recomputable_ratios)
    agg_exprs.extend(_heterogeneity_aggs(present, group_cols))

    collapsed = results.group_by(group_cols, maintain_order=True).agg(agg_exprs)
    collapsed = _finalise_heterogeneity(collapsed, present, group_cols)
    collapsed = _recompute_ratios(collapsed, recomputable_ratios, rwa_col, ead_col)
    return collapsed


def _coalesce_to_parent(results: pl.LazyFrame, present: set[str]) -> pl.LazyFrame:
    """Rewrite ``exposure_reference`` to its parent so sub-rows group together."""
    parent_cols = [c for c in RECON_PARENT_KEY_COLUMNS if c in present]
    coalesce_args = [pl.col(c) for c in parent_cols] + [pl.col("exposure_reference")]
    return results.with_columns(pl.coalesce(coalesce_args).alias("exposure_reference"))


def _build_agg_exprs(
    schema_names: Sequence[str],
    group_cols: Sequence[str],
    recomputable_ratios: Sequence[str],
) -> list[pl.Expr]:
    """Sum additive money fields, take first for everything else."""
    exprs: list[pl.Expr] = []
    for col in schema_names:
        if col in group_cols or col in recomputable_ratios:
            continue
        if col in ADDITIVE_OUTPUT_FIELDS:
            exprs.append(pl.col(col).sum().alias(col))
        else:
            exprs.append(pl.col(col).first().alias(col))
    return exprs


def _heterogeneity_aggs(present: set[str], group_cols: Sequence[str]) -> list[pl.Expr]:
    """Per-group distinct counts of the categorical columns we flag."""
    return [
        pl.col(c).n_unique().alias(f"__nuniq_{c}")
        for c in RECON_HETEROGENEITY_COLUMNS
        if c in present and c not in group_cols
    ]


def _finalise_heterogeneity(
    collapsed: pl.LazyFrame,
    present: set[str],
    group_cols: Sequence[str],
) -> pl.LazyFrame:
    """Fold the temporary distinct-count columns into a single boolean flag."""
    nuniq_cols = [
        f"__nuniq_{c}" for c in RECON_HETEROGENEITY_COLUMNS if c in present and c not in group_cols
    ]
    if not nuniq_cols:
        return collapsed.with_columns(pl.lit(False).alias(HETEROGENEITY_FLAG))
    flag = pl.any_horizontal([pl.col(c) > 1 for c in nuniq_cols]).alias(HETEROGENEITY_FLAG)
    return collapsed.with_columns(flag).drop(nuniq_cols)


def _recompute_ratios(
    collapsed: pl.LazyFrame,
    recomputable_ratios: Sequence[str],
    rwa_col: str | None,
    ead_col: str | None,
) -> pl.LazyFrame:
    """Recompute ratio columns as sum(rwa) / sum(ead), zero-guarded."""
    if not recomputable_ratios or rwa_col is None or ead_col is None:
        return collapsed
    ratio_expr = (
        pl.when(pl.col(ead_col).abs() > _EAD_ZERO_GUARD)
        .then(pl.col(rwa_col) / pl.col(ead_col))
        .otherwise(0.0)
    )
    return collapsed.with_columns([ratio_expr.alias(c) for c in recomputable_ratios])


def _first_present(candidates: Sequence[str], present: set[str]) -> str | None:
    """Return the first candidate column name present, else None."""
    return next((c for c in candidates if c in present), None)
