"""
Aggregator utility functions.

Internal module — not part of the public API.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from polars._typing import PolarsDataType


def resolve_rwa_col(col_names: frozenset[str] | list[str] | set[str]) -> str | None:
    """
    Resolve which RWA column to use with a consistent fallback chain.

    Order: rwa_post_factor -> rwa_final -> rwa.

    Returns:
        Column name, or None if no RWA column found.
    """
    names = col_names if isinstance(col_names, (frozenset, set)) else set(col_names)
    if "rwa_post_factor" in names:
        return "rwa_post_factor"
    if "rwa_final" in names:
        return "rwa_final"
    if "rwa" in names:
        return "rwa"
    return None


def resolve_own_approach_rwa_col(col_names: frozenset[str] | list[str] | set[str]) -> str | None:
    """Resolve the PRE-FLOOR own-approach RWA column of a results frame.

    Order: ``rwa_final`` -> ``rwa_post_factor`` -> ``rwa``.

    Distinct from :func:`resolve_rwa_col`'s chain, and the difference is
    load-bearing. At the HEAD of the aggregator the output floor has not run, so
    ``rwa_final`` still carries each branch's own post-supporting-factor RWA, and
    it is the exact column ``_floor.py`` aliases to ``rwa_pre_floor`` before
    summing it into U-TREA — so a ranking on it optimises the quantity the floor
    optimises.

    ``rwa_post_factor`` may not lead, because NEITHER of the other two carriers
    is populated on every branch. Measured on the frame this function's caller
    reads:

    ==================  =========================  =========================
    carrier             CRR                        Basel 3.1
    ==================  =========================  =========================
    ``rwa_post_factor`` SA and IRB populated       SA populated, IRB **null**
    ``rwa``             IRB populated, SA **null** IRB populated, SA **null**
    ``rwa_final``       every row                  every row
    ==================  =========================  =========================

    The IRB null is NOT the supporting factors being unavailable under PS1/26 as
    such, and it is NOT the ``rwa_post_factor``-to-``rwa`` rename in
    ``engine/irb/calculator.py`` (that rename copies the value INTO ``rwa`` and
    leaves ``rwa_post_factor`` populated — and it runs only on the enabled path).
    The cause is the IRB branch's OWN early return in
    ``IRBCalculator._apply_supporting_factors``: with the ``supporting_factors``
    pack Feature off it writes ``supporting_factor = 1.0`` and returns, never
    reaching ``SupportingFactorCalculator.apply_factors``, whose disabled path
    would otherwise write ``rwa_post_factor = rwa_pre_factor``. The SA branch
    calls that function directly, which is why SA rows carry the column in both
    regimes. So the gap is regime-DEPENDENT — it follows the Feature, and CRR IRB
    rows are populated — and it lands on precisely the modelled rows a pre-floor
    ranking exists to rank.

    A coalesce over the carriers would be worse than a wrong single choice: it
    would rank SA candidates on ``rwa_post_factor`` and IRB ones on ``rwa``,
    which is a divergent basis within one comparison.

    Returns:
        Column name, or None if no RWA column found.
    """
    names = col_names if isinstance(col_names, (frozenset, set)) else set(col_names)
    for carrier in ("rwa_final", "rwa_post_factor", "rwa"):
        if carrier in names:
            return carrier
    return None


def collect_views(views: dict[str, pl.LazyFrame]) -> dict[str, pl.DataFrame]:
    """Materialise a batch of aggregator views together, in one pass.

    The calculator branches arrive already eager (collected by
    ``materialise_branches`` at the calculator edge), so every view here is a
    plan over in-memory data.  Collecting the batch with a single
    ``pl.collect_all`` lets Polars share the common subplans (the combined
    concat + residual multiplier) across views via comm-subplan elimination.
    The caller wraps each eager result back with ``.lazy()`` so the bundle
    fields stay LazyFrame-typed; any downstream collect on them is then a
    near-free shallow collect instead of a plan re-execution.

    This is deliberately a plain ``pl.collect_all`` rather than
    ``materialise_branches``: the latter records per-frame EdgeEvents in the
    run capture, and the aggregator's internal summary views are not stage
    edges (the documented edge inventory in
    tests/integration/test_stage_edges.py pins the stage-exit sequence).

    It lives here rather than in ``aggregator.py`` because the facility-share
    resolver needs the same one-pass materialisation at the aggregator's HEAD,
    and a second ``pl.collect_all`` site would be a second answer to the same
    question.
    """
    collected = pl.collect_all(list(views.values()))
    return dict(zip(views, collected, strict=True))


def col_or_default(
    name: str,
    cols: frozenset[str] | set[str],
    default: pl.Expr | None = None,
    dtype: PolarsDataType = pl.String,
) -> pl.Expr:
    """
    Return ``pl.col(name)`` if the column exists, otherwise a default expression.

    Args:
        name: Column name to look for.
        cols: Available column names.
        default: Default expression. If None, uses ``pl.lit(None).cast(dtype)``.
        dtype: Data type for the null literal when no default is provided.
    """
    if name in cols:
        return pl.col(name)
    if default is not None:
        return default.alias(name)
    return pl.lit(None).cast(dtype).alias(name)


def empty_frame(schema: Mapping[str, PolarsDataType]) -> pl.LazyFrame:
    """Create an empty LazyFrame from a schema dict."""
    return pl.LazyFrame({name: pl.Series([], dtype=dtype) for name, dtype in schema.items()})
