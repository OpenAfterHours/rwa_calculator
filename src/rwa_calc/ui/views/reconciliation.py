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

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, SupportsFloat, cast

import polars as pl

from rwa_calc.analysis.recon_registry import RECONCILABLE_COMPONENTS_BY_NAME
from rwa_calc.analysis.reconciliation import (
    BUCKET_BREAK,
    BUCKET_EXACT,
    BUCKET_MISSING_LEFT,
    BUCKET_MISSING_RIGHT,
    BUCKET_WITHIN,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_calc.api.models import ReconciliationResponse
    from rwa_calc.ui.app.recon_signoff import Decision

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

# On the default "exposure_reference" key, our sub-rows are automatically
# collapsed back to their pre-concatenation BASE reference before the join:
#   guarantee splits   L1__G_<guarantor> / L1__REM      -> L1
#   real-estate splits M1_rre / M1_cre / M1_res         -> M1
#   facility undrawn   FAC1_UNDRAWN[_<sub>|_RESIDUAL]    -> FAC1  (the facility ref)
# so a legacy file keyed on the ORIGINAL loan / facility reference links straight
# through — you do NOT need to strip our engine's suffixes on the legacy side.
# To key on the base explicitly (e.g. as part of a composite key), use the
# always-present "source_exposure_reference" column:
#   our_keys = ["source_exposure_reference"]
# Synthetic derivative/SFT rows (ccr__/ft__/dfc__) keep their namespace and stay
# as our-only lines unless your legacy file reports those aggregates too.

# A legacy file may split one exposure across several lines (a collateralised
# portion in one risk class, the residual in another). Those lines are SUMMED to
# the key grain, never dropped, so the totals tie out.

[components.rwa]
legacy_column = "RWA"
# scale = 1_000_000   # if legacy RWA is in millions

[components.ead]
legacy_column = "EAD"

# Map your asset-class column to power the asset-class allocation view (ours vs
# legacy EAD/RWA per risk class). value_map translates your labels to ours.
[components.exposure_class]
legacy_column = "Asset_Class"
value_map = { CORP = "corporate", RETAIL = "retail", RRE = "residential_mortgage" }

# [components.risk_weight]
# legacy_column = "RW_pct"
# unit = "percent"

# Map any of these to compare the RWA drivers side-by-side in the single-loan
# forensic view (and the tie-out / explorer / export). Each is optional — an
# unmapped driver simply shows our side only ("legacy not provided").
# [components.pd]
# legacy_column = "PD"
# unit = "decimal"            # 0.012, not 1.2
# [components.lgd]
# legacy_column = "LGD"
# unit = "decimal"
# [components.cqs]
# legacy_column = "CQS"       # credit-quality step / external rating bucket
# [components.collateral]
# legacy_column = "Collateral_Value"     # net eligible collateral after haircuts
# [components.guarantee]
# legacy_column = "Guaranteed_Amount"    # EAD portion covered by the guarantee

# To reconcile each class portion line-by-line (not just per exposure), add the
# class to BOTH keys — a portion in a class on only one side then shows as missing:
# legacy_keys = ["exposure_reference", "Asset_Class"]
# our_keys    = ["exposure_reference", "exposure_class"]
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

# Sign-off status vocabulary. ``open`` is an un-actioned difference; ``accepted`` /
# ``rejected`` are the analyst's two terminal dispositions (both clear the row from
# the default Open worklist); ``matched`` is the implicit status of an exact-match
# row (never a difference, never sign-off-able). ``all`` is the pseudo-filter that
# imposes no status constraint. The on-screen explorer filter offers Open first.
SIGNOFF_OPEN = "open"
SIGNOFF_ACCEPTED = "accepted"
SIGNOFF_REJECTED = "rejected"
SIGNOFF_MATCHED = "matched"
SIGNOFF_ALL = "all"
SIGNOFF_STATUS_CHOICES: tuple[str, ...] = (
    SIGNOFF_OPEN,
    SIGNOFF_ACCEPTED,
    SIGNOFF_REJECTED,
    SIGNOFF_ALL,
)

# On-screen forensic row cap; the full frame is available via the CSV export.
_FORENSIC_LIMIT = 200

# Overview "biggest breaks" worklist size — the ranked top-N shown on the report
# landing page (the engine already sorts breaks_detail by |Δ| desc) so the
# overview never materialises the full diff.
BIGGEST_BREAKS_LIMIT = 50

# Explorer pagination defaults. The page size is clamped to MAX_PAGE_SIZE so a
# hand-crafted URL cannot ask the server to render an unbounded window.
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500

# The wide per-key frame's filterable dimensions and their query-param names.
# Each maps a UI filter to the column it constrains in component_reconciliation.
_FILTER_COLUMNS: dict[str, str] = {
    "bucket": "row_bucket",
    "exposure_class": "our_exposure_class",
    "approach": "our_approach",
    "method": "method",
    "worst_component": "worst_component",
    "status": "signoff_status",
}

# The order an analyst reads a single loan's RWA build. ``loan_detail`` orders the
# active components into this chain for the forensic view; active components not
# listed here are appended (registry order) after the known steps.
_CHAIN_ORDER: tuple[str, ...] = (
    "exposure_class",
    "approach",
    "cqs",
    "pd",
    "lgd",
    "maturity",
    "ccf",
    "collateral",
    "guarantee",
    "ead",
    "risk_weight",
    "supporting_factor",
    "expected_loss",
    "rwa",
)

# Human labels for the chain steps; anything unmapped falls back to the component
# name with underscores spaced.
_STEP_LABELS: dict[str, str] = {
    "exposure_class": "exposure class",
    "approach": "approach",
    "cqs": "CQS / rating",
    "pd": "PD",
    "lgd": "LGD",
    "maturity": "maturity (M)",
    "ccf": "CCF",
    "collateral": "collateral",
    "guarantee": "guarantee",
    "ead": "EAD",
    "risk_weight": "risk weight",
    "supporting_factor": "supporting factor",
    "expected_loss": "expected loss",
    "rwa": "RWA",
}


@dataclass(frozen=True, slots=True)
class ForensicFilters:
    """A server-side filter/sort/page request over the wide per-key frame.

    Every field is optional; an absent filter does not constrain that dimension.
    ``query`` is a literal substring match on ``_recon_key`` (no regex). ``sort``
    is validated against the projected display columns by ``forensic_page`` — an
    unknown column raises ``ValueError`` so the route can answer 400.
    """

    bucket: str | None = None
    exposure_class: str | None = None
    approach: str | None = None
    method: str | None = None
    worst_component: str | None = None
    status: str | None = None
    query: str | None = None
    sort: str | None = None
    descending: bool = True
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE


@dataclass(frozen=True, slots=True)
class ForensicPage:
    """One rendered page of the per-key explorer.

    ``total`` is the filtered row count *before* the page slice, so the template
    can show "rows X–Y of Z" and drive the pager. ``offset`` is the 0-based index
    of the first shown row.
    """

    columns: list[str]
    rows: list[dict]
    total: int
    page: int
    page_size: int
    pages: int
    offset: int
    sort: str | None
    descending: bool


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
    """Tier 2 — where breaks concentrate: by bucket, exposure class and approach.

    Reads through the cached ``collect_*`` accessors (not the raw lazy bundle
    frames) so the overview render reuses the worker-warmed cache instead of
    re-executing the heavy reconcile join once per segment table.
    """
    return {
        "by_bucket": response.collect_summary_by_bucket(),
        "by_class": response.collect_summary_by_exposure_class(),
        "by_approach": response.collect_summary_by_approach(),
        "by_class_method": response.collect_summary_by_class_method(),
    }


def class_allocation_table(response: ReconciliationResponse) -> pl.DataFrame:
    """Tier 2 — asset-class allocation: ours vs legacy EAD/RWA per risk class."""
    return response.collect_class_allocation()


def class_allocation_chart_items(
    response: ReconciliationResponse,
) -> list[tuple[str, float, float]]:
    """Grouped-bar items (class, legacy_rwa, our_rwa) for the allocation chart."""
    alloc = response.collect_class_allocation()
    if "our_rwa" not in alloc.columns:
        return []
    return [
        (str(row["exposure_class"]).upper(), _f(row.get("legacy_rwa")), _f(row.get("our_rwa")))
        for row in alloc.iter_rows(named=True)
    ]


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


def biggest_breaks(
    response: ReconciliationResponse,
    decisions: Mapping[str, Decision] | None = None,
    current_fps: Mapping[str, str] | None = None,
    *,
    limit: int = BIGGEST_BREAKS_LIMIT,
) -> pl.DataFrame:
    """Overview worklist — the ``limit`` most material *open* breaks, ranked.

    ``breaks_detail`` is already sorted by ``|abs_delta|`` descending in the
    engine, so a ``head`` is the top-N. Reads the worker-warmed ``breaks_detail``
    cache (not the wide per-key frame), so the overview never materialises the
    full diff for a large portfolio. A break whose key carries an **unchanged**
    sign-off decision is dropped (the worklist burns down); a **stale** decision —
    one whose difference has moved since sign-off — is kept, so the regression is
    re-reviewed rather than silently waved through.
    """
    df = response.collect_breaks_detail()
    decisions = decisions or {}
    current_fps = current_fps or {}
    if decisions and "_recon_key" in df.columns:
        settled = [k for k, d in decisions.items() if not is_signoff_stale(d, current_fps.get(k))]
        if settled:
            df = df.filter(~pl.col("_recon_key").is_in(settled))
    return df.head(limit).fill_nan(None)


def breaks_signoff_progress(
    response: ReconciliationResponse,
    decisions: Mapping[str, Decision] | None = None,
    current_fps: Mapping[str, str] | None = None,
) -> dict[str, int]:
    """Burndown of the break worklist: how many distinct breaking keys are reviewed.

    Counts distinct ``_recon_key`` in the warmed ``breaks_detail`` (the primary
    worklist) and how many carry an **unchanged** decision, so the overview /
    explorer can show "X of Y reviewed — Z open" without touching the wide per-key
    frame. A **stale** decision (the difference moved since sign-off) counts as open,
    not reviewed, and is also surfaced separately as ``changed``.
    """
    decisions = decisions or {}
    current_fps = current_fps or {}
    df = response.collect_breaks_detail()
    if "_recon_key" not in df.columns:
        return {"total": 0, "reviewed": 0, "open": 0, "accepted": 0, "rejected": 0, "changed": 0}
    break_keys = set(df.get_column("_recon_key").unique().to_list())
    decided = [k for k in break_keys if k in decisions]
    changed = [k for k in decided if is_signoff_stale(decisions[k], current_fps.get(k))]
    reviewed_keys = [k for k in decided if k not in changed]
    accepted = sum(1 for k in reviewed_keys if decisions[k].status == SIGNOFF_ACCEPTED)
    rejected = sum(1 for k in reviewed_keys if decisions[k].status == SIGNOFF_REJECTED)
    total = len(break_keys)
    reviewed = len(reviewed_keys)
    return {
        "total": total,
        "reviewed": reviewed,
        "open": total - reviewed,
        "accepted": accepted,
        "rejected": rejected,
        "changed": len(changed),
    }


def forensic_filter_options(response: ReconciliationResponse) -> dict[str, list[str]]:
    """The distinct filter values offered by the explorer's drop-downs.

    Buckets come from the fixed engine vocabulary; classes / approaches /
    worst-components are read from the small pre-aggregated summaries (cheap), so
    this never touches the wide per-key frame.
    """
    return {
        "bucket": [b for b in BUCKET_CHOICES if b != ALL_BUCKETS],
        "exposure_class": _summary_values(response.collect_summary_by_exposure_class()),
        "approach": _summary_values(response.collect_summary_by_approach()),
        "method": _summary_values(response.collect_summary_by_class_method(), col="method"),
        "worst_component": _summary_values(
            response.collect_summary_by_component(), col="component"
        ),
        "status": list(SIGNOFF_STATUS_CHOICES),
    }


def forensic_page(
    response: ReconciliationResponse,
    filters: ForensicFilters,
    decisions: Mapping[str, Decision] | None = None,
    current_fps: Mapping[str, str] | None = None,
) -> ForensicPage:
    """Tier B explorer — one filtered, sorted, paged window of the per-key frame.

    Collects the wide ``component_reconciliation`` frame once (cached on the
    response), annotates each row with its sign-off ``signoff_status`` /
    ``signoff_reason`` / ``signoff_stale`` from *decisions* (re-flagging a decision
    whose difference has moved), applies the filters (including the ``status``
    dimension), validates ``filters.sort`` against the projected display columns
    (unknown -> ``ValueError``), then sorts and slices a single page — so the browser
    only ever receives ``page_size`` rows. *current_fps* is computed when not
    supplied; the route passes it to avoid a second filtered collect.
    """
    decisions = decisions or {}
    if current_fps is None:
        current_fps = current_fingerprints(response, decisions)
    df = response.collect_component_reconciliation()
    df = annotate_signoff(df, decisions, current_fps)
    df = _apply_forensic_filters(df, filters)
    total = df.height
    columns = _readable_recon_columns(df)
    # signoff_stale / signoff_prior_status ride along in the row dicts (for the badge
    # + the "was accepted, now changed" hint) without becoming visible table columns.
    extra = [c for c in ("signoff_stale", "signoff_prior_status") if c in df.columns]

    sort_col = filters.sort or None
    if sort_col is not None and sort_col not in columns:
        raise ValueError(f"unknown sort column: {sort_col!r}")
    if sort_col is not None:
        df = df.sort(sort_col, descending=filters.descending, nulls_last=True)

    page_size = max(1, min(filters.page_size, MAX_PAGE_SIZE))
    pages = max(1, math.ceil(total / page_size)) if total else 1
    page = min(max(1, filters.page), pages)
    offset = (page - 1) * page_size
    rows = df.select([*columns, *extra]).slice(offset, page_size).fill_nan(None).to_dicts()
    return ForensicPage(
        columns=columns,
        rows=rows,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
        offset=offset,
        sort=sort_col,
        descending=filters.descending,
    )


def loan_detail(response: ReconciliationResponse, recon_key: str) -> dict | None:
    """Tier C — the full per-component forensic for a single loan (join key).

    Filters the lazy per-key frame to one key (filter pushdown keeps it cheap even
    when the eager cache is cold), then surfaces: a per-component panel
    (legacy / ours / Δ / bucket for every active component, matches included), that
    key's break rows, and the *driver* columns (explain / input) dropped from
    every on-screen table today and previously only reachable via the CSV export.
    Returns ``None`` when no row matches the key.
    """
    df = (
        response.scan_component_reconciliation()
        .filter(pl.col("_recon_key") == recon_key)
        .collect()
        .fill_nan(None)
    )
    if df.height == 0:
        return None

    row = df.row(0, named=True)
    components = _component_names(df.columns)
    panels = [
        {
            "component": name,
            "legacy": row.get(f"legacy_{name}"),
            "ours": row.get(f"our_{name}"),
            "abs_delta": row.get(f"abs_delta_{name}"),
            "rel_delta": row.get(f"rel_delta_{name}"),
            "bucket": row.get(f"{name}_bucket"),
        }
        for name in components
    ]

    # Everything not already shown in a panel or the header (and not an internal
    # marker) is a driver column — the explain / input detail this view surfaces.
    shown = {
        "_recon_key",
        "row_bucket",
        "worst_component",
        "our_exposure_class",
        "our_approach",
        "_our_present",
        "_legacy_present",
    }
    for name in components:
        shown.update(
            {
                f"legacy_{name}",
                f"our_{name}",
                f"abs_delta_{name}",
                f"rel_delta_{name}",
                f"{name}_bucket",
            }
        )
    drivers = {c: row.get(c) for c in df.columns if c not in shown}

    breaks = (
        response.scan_breaks_detail()
        .filter(pl.col("_recon_key") == recon_key)
        .collect()
        .fill_nan(None)
    )
    return {
        "recon_key": recon_key,
        "row_bucket": row.get("row_bucket"),
        "worst_component": row.get("worst_component"),
        "exposure_class": row.get("our_exposure_class"),
        "approach": row.get("our_approach"),
        "steps": _driver_chain(row, components),
        "panels": panels,
        "drivers": drivers,
        "breaks": {"columns": breaks.columns, "rows": breaks.to_dicts()},
    }


def annotate_signoff(
    df: pl.DataFrame,
    decisions: Mapping[str, Decision],
    current_fps: Mapping[str, str] | None = None,
) -> pl.DataFrame:
    """Attach ``signoff_status`` / ``signoff_reason`` / ``signoff_stale`` to a frame.

    Left-joins the analyst's stored decisions onto ``component_reconciliation`` by
    ``_recon_key`` and derives ``signoff_status`` per row:

    - ``matched`` for an exact-match row (never a difference — keeps matches out of
      the Open worklist, even if an old decision lingers because the break was
      fixed),
    - ``open`` when the row is a difference the analyst hasn't actioned — **or** has
      actioned but the difference has since *moved* (``signoff_stale=True``), so a
      changed difference is re-reviewed rather than waved through under an old
      approval,
    - the decision's status (``accepted`` / ``rejected``) when one exists and the
      difference is unchanged.

    Staleness compares each decision's stored ``fingerprint`` against *current_fps*
    (``{recon_key: current fingerprint}``); a key absent from *current_fps*, or a
    decision with no stored fingerprint, is treated as *not* stale. ``signoff_reason``
    / ``signoff_prior_status`` carry the decision's reason / status (so a stale row
    can show what it was signed off as, and why). The frame is returned unchanged
    when it has no ``_recon_key`` column.
    """
    if "_recon_key" not in df.columns:
        return df
    dec_df = _decisions_frame(decisions, current_fps or {})
    has_row_bucket = "row_bucket" in df.columns
    is_exact = (pl.col("row_bucket") == BUCKET_EXACT) if has_row_bucket else pl.lit(value=False)
    # A row is "resolved" once it is exact OR within-tolerance — neither needs
    # sign-off, so a decision on a row that improved into either must NOT be
    # re-flagged stale (only rows that are STILL a material difference can go stale).
    is_resolved = (
        pl.col("row_bucket").is_in([BUCKET_EXACT, BUCKET_WITHIN])
        if has_row_bucket
        else pl.lit(value=False)
    )
    has_decision = pl.col("_decision_status").is_not_null()
    stale = (
        has_decision
        & ~is_resolved
        & pl.col("_current_fp").is_not_null()
        & (pl.col("_decision_fp").fill_null("") != "")
        & (pl.col("_decision_fp") != pl.col("_current_fp"))
    )
    return (
        df.join(dec_df, on="_recon_key", how="left", maintain_order="left")
        .with_columns(
            signoff_status=pl.when(is_exact)
            .then(pl.lit(SIGNOFF_MATCHED))
            .when(stale)
            .then(pl.lit(SIGNOFF_OPEN))
            .when(has_decision)
            .then(pl.col("_decision_status"))
            .otherwise(pl.lit(SIGNOFF_OPEN)),
            signoff_stale=stale.fill_null(value=False),
            signoff_prior_status=pl.col("_decision_status").fill_null(""),
            signoff_reason=pl.col("_decision_reason").fill_null(""),
        )
        .drop("_decision_status", "_decision_reason", "_decision_fp", "_current_fp")
    )


def recon_fingerprint(response: ReconciliationResponse, recon_key: str) -> str:
    """The current fingerprint of one row's difference (stored at sign-off time).

    Reads the *cached* wide per-key frame (shared with the explorer render) and
    filters to the single key. Returns ``""`` when the frame has no ``_recon_key``
    column (a failed / empty reconciliation) or no row matches — so a sign-off on a
    failed run can never raise.
    """
    df = response.collect_component_reconciliation()
    if "_recon_key" not in df.columns:
        return ""
    match = df.filter(pl.col("_recon_key") == recon_key).fill_nan(None)
    if match.height == 0:
        return ""
    return _row_fingerprint(match.row(0, named=True), _component_names(df.columns))


def current_fingerprints(
    response: ReconciliationResponse, decisions: Mapping[str, Decision]
) -> dict[str, str]:
    """Map ``{recon_key: current fingerprint}`` for just the *decided* keys.

    Returns ``{}`` immediately when there are no decisions (so a run with no
    sign-offs never touches the wide frame). Otherwise reads the *cached* wide per-key
    frame (``collect_component_reconciliation`` memoises on the response, so the
    explorer / overview / AJAX paths share one collect for the run's lifetime) and
    filters to the decided keys. A column-less frame (failed / empty reconciliation)
    yields ``{}`` rather than raising.
    """
    keys = list(decisions.keys())
    if not keys:
        return {}
    df = response.collect_component_reconciliation()
    if "_recon_key" not in df.columns:
        return {}
    components = _component_names(df.columns)
    sub = df.filter(pl.col("_recon_key").is_in(keys)).fill_nan(None)
    return {
        str(row["_recon_key"]): _row_fingerprint(row, components)
        for row in sub.iter_rows(named=True)
    }


def is_signoff_stale(decision: Decision, current_fp: str | None) -> bool:
    """Whether *decision* no longer matches the row's current difference.

    A decision with no stored fingerprint (pre-fingerprint, or saved against a
    now-absent row) cannot be judged and is treated as *not* stale.
    """
    if not decision.fingerprint or current_fp is None:
        return False
    return decision.fingerprint != current_fp


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
    for extra in ("signoff_status", "signoff_reason"):
        if extra in present and extra not in cols:
            cols.append(extra)
    return cols or present


def _decisions_frame(
    decisions: Mapping[str, Decision], current_fps: Mapping[str, str]
) -> pl.DataFrame:
    """A frame ``{_recon_key, _decision_status, _decision_reason, _decision_fp, _current_fp}``.

    Built from the stored decisions for a left-join onto the per-key frame;
    ``_current_fp`` is each key's *current* fingerprint (``None`` when the key is not
    in *current_fps*, so staleness can't be judged). An empty mapping yields an empty
    (correctly-typed) frame so the join is a no-op.
    """
    keys = list(decisions.keys())
    return pl.DataFrame(
        {
            "_recon_key": keys,
            "_decision_status": [decisions[k].status for k in keys],
            "_decision_reason": [decisions[k].reason for k in keys],
            "_decision_fp": [decisions[k].fingerprint for k in keys],
            "_current_fp": [current_fps.get(k) for k in keys],
        },
        schema={
            "_recon_key": pl.String,
            "_decision_status": pl.String,
            "_decision_reason": pl.String,
            "_decision_fp": pl.String,
            "_current_fp": pl.String,
        },
    )


def _row_fingerprint(row: dict, components: list[str]) -> str:
    """A stable, float-noise-robust signature of one row's *difference*.

    Captures the row bucket plus, for every component that is a material difference
    (a break or missing — exact and within-tolerance are ignored), a
    ``name:bucket:our~legacy`` segment where each value is tokenised by
    :func:`_value_token` — numbers to 4 significant figures (so float-sum noise never
    flips it, while a real >0.01% move does), categoricals normalised (casefold +
    strip). Banding *both sides' values* (not just ``abs_delta``) is essential: a
    categorical break, or a one-sided break, has a null ``abs_delta`` — so a legacy
    reclassification (e.g. retail → sovereign) on an already-accepted class break
    must still change the fingerprint, or the old approval would silently wave the
    moved difference through. The fingerprint therefore changes when a break moves to
    a different component, appears / disappears, changes either side's value
    materially, or the row bucket changes — but not on an identical re-run.
    """
    parts = [str(row.get("row_bucket") or "")]
    for name in sorted(components):
        bucket = row.get(f"{name}_bucket")
        if bucket and bucket not in (BUCKET_EXACT, BUCKET_WITHIN):
            our_token = _value_token(row.get(f"our_{name}"))
            legacy_token = _value_token(row.get(f"legacy_{name}"))
            parts.append(f"{name}:{bucket}:{our_token}~{legacy_token}")
    return "|".join(parts)


def _value_token(value: object) -> str:
    """A stable token for one component value: a banded number or a normalised string.

    Numbers go through :func:`_delta_band` (4 sig figs, noise-robust); strings
    (categoricals such as exposure class) are casefolded + stripped; ``None`` → "".
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).casefold()
    if isinstance(value, (int, float)):
        return _delta_band(value)
    return str(value).strip().casefold()


def _delta_band(value: object, *, sig_figs: int = 4) -> str:
    """A number rounded to *sig_figs* significant figures, as a canonical string.

    Significant-figure (not decimal) rounding so it is scale-correct across money,
    ratios and probabilities, and coarse enough that non-deterministic float-sum
    noise (~12+ sig figs down) never flips it, while a real >0.01% move does. Uses
    Python's normalised scientific notation (mantissa always in ``[1, 10)``), so a
    value sitting a hair below a power of ten (``999.999999999``) and the power of
    ten itself (``1000.0``) both render ``1.000e+03`` — no false break at a decade
    boundary.
    """
    if not isinstance(value, (int, float)):
        return ""
    x = float(value)
    if not math.isfinite(x):
        return "inf"
    # No float-equality check for zero: format() bands any finite value, and adding
    # 0.0 collapses -0.0 to +0.0 so both render the same canonical "0.000e+00".
    return format(x + 0.0, f".{sig_figs - 1}e")


def _component_names(columns: list[str]) -> list[str]:
    """Active component names, in column order, inferred from ``<name>_bucket``."""
    suffix = "_bucket"
    return [c[: -len(suffix)] for c in columns if c.endswith(suffix) and c != "row_bucket"]


def _driver_chain(row: dict, components: list[str]) -> list[dict]:
    """Order the active components into the RWA-driver chain, nesting drivers.

    Each step is ``{step, label, legacy, ours, abs_delta, rel_delta, bucket,
    drivers}``; the component value reads its panel columns (``legacy_/our_/
    abs_delta_/rel_delta_/<name>_bucket``). ``drivers`` are that component's
    registry ``explain_columns`` + ``input_columns`` present on the row, each
    ``{name, ours, legacy, legacy_available}``. Drivers are our-side-only
    (``legacy_available=False``) — a column with a real legacy counterpart is a
    promoted component and gets its own step, so it is excluded from any driver
    list (and each driver is shown once, under its earliest chain-order step).
    """
    active = set(components)
    # Columns that ARE a component value (their own step) must never re-appear as
    # a driver row; seed ``seen`` with them so the dedup below skips them.
    seen: set[str] = set()
    for name in active:
        spec = RECONCILABLE_COMPONENTS_BY_NAME.get(name)
        if spec is not None:
            seen.update(spec.our_columns)

    ordered = [c for c in _CHAIN_ORDER if c in active]
    ordered += [c for c in components if c not in _CHAIN_ORDER]

    steps: list[dict] = []
    for name in ordered:
        spec = RECONCILABLE_COMPONENTS_BY_NAME.get(name)
        drivers: list[dict] = []
        if spec is not None:
            for col in (*spec.explain_columns, *spec.input_columns):
                if col in seen or col not in row:
                    continue
                seen.add(col)
                drivers.append(
                    {"name": col, "ours": row.get(col), "legacy": None, "legacy_available": False}
                )
        steps.append(
            {
                "step": name,
                "label": _STEP_LABELS.get(name, name.replace("_", " ")),
                "legacy": row.get(f"legacy_{name}"),
                "ours": row.get(f"our_{name}"),
                "abs_delta": row.get(f"abs_delta_{name}"),
                "rel_delta": row.get(f"rel_delta_{name}"),
                "bucket": row.get(f"{name}_bucket"),
                "drivers": drivers,
            }
        )
    return steps


def _apply_forensic_filters(df: pl.DataFrame, filters: ForensicFilters) -> pl.DataFrame:
    """Constrain the wide per-key frame by each set explorer filter.

    Categorical filters are exact-match on their backing column; ``query`` is a
    *literal* substring match on ``_recon_key`` (``literal=True`` so a key with
    regex metacharacters cannot break the match). Each filter is skipped when its
    value is unset or its column is absent from the frame.
    """
    for field_name, column in _FILTER_COLUMNS.items():
        value = getattr(filters, field_name)
        if value and column in df.columns:
            df = df.filter(pl.col(column) == value)
    if filters.query and "_recon_key" in df.columns:
        df = df.filter(
            pl.col("_recon_key").cast(pl.String).str.contains(filters.query, literal=True)
        )
    return df


def _summary_values(df: pl.DataFrame, *, col: str | None = None) -> list[str]:
    """Sorted distinct string values of a summary frame's first (or named) column.

    Used to populate the explorer's filter drop-downs from the small
    pre-aggregated summaries. Returns ``[]`` when the column is absent.
    """
    column = col or (df.columns[0] if df.columns else None)
    if column is None or column not in df.columns:
        return []
    return [str(v) for v in df.get_column(column).unique().sort().to_list() if v is not None]


def _f(value: object) -> float:
    """Coerce a possibly-null numeric cell to a float (null -> 0.0)."""
    return float(cast("SupportsFloat", value)) if value is not None else 0.0
