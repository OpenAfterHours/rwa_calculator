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
- Answer the loan forensic's two remaining trail-breakers: WHICH template rows a
  key reached on each side (``placement_panel``), and WHICH ``_recon_key`` an
  inbound link built from an exposure reference alone means
  (``resolve_recon_key``).

Bucket label constants are imported from the engine (its single source) so the
UI and the engine summaries never drift.

References:
- Canonical components: data/schemas.RECONCILABLE_COMPONENTS
- Config grammar: api/reconciliation.load_reconciliation_config
- Placement grain: reporting/membership.MEMBERSHIP_SCHEMA
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, SupportsFloat, cast

import polars as pl

from rwa_calc.analysis.recon_registry import RECONCILABLE_COMPONENTS_BY_NAME
from rwa_calc.analysis.reconciliation import (
    _KEY_SEP,  # the ONE definition of the composite-key separator; never re-spelled here
    BUCKET_BREAK,
    BUCKET_EXACT,
    BUCKET_MISSING_LEFT,
    BUCKET_MISSING_RIGHT,
    BUCKET_WITHIN,
)
from rwa_calc.analysis.return_recon import KEY_COLUMNS
from rwa_calc.ui.views import method_split
from rwa_calc.ui.views.method_split import METHOD_ORDER  # presentation order of the sections
from rwa_calc.ui.views.return_recon import TEMPLATE_CODES

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from rwa_calc.analysis.return_recon import ReturnRecon, SideView
    from rwa_calc.api.models import ReconciliationResponse
    from rwa_calc.ui.app.recon_signoff import Decision

logger = logging.getLogger(__name__)

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

# Map your approach/method column to SPLIT the asset-class allocation by methodology
# (STD / FIRB / AIRB / SLOTTING / EQUITY), the way COREP reports each class per method
# (SA on C 07.00, IRB on C 08.0x). Without it the allocation stays combined — the legacy
# side has no method to split on. value_map must land on OUR approach labels or the two
# sides cannot join; a REC007 warning names any value that did not resolve.
# [components.approach]
# legacy_column = "Method"
# value_map = { STD = "standardised", "IRB-F" = "foundation_irb", "IRB-A" = "advanced_irb" }

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

# =============================================================================
# "Where this exposure lands" — the placement panel's vocabulary
# =============================================================================

# Which side(s) of the comparison reached a template row. THREE answers, three
# strings. A row only one side reaches is the finding the panel exists to
# surface, so it never renders as the blank that reads like agreement.
PLACEMENT_BOTH = "both"
PLACEMENT_OURS_ONLY = "ours only"
PLACEMENT_THEIRS_ONLY = "theirs only"

# What a side prints for a row it did / did not reach. ``NOT_REACHED_DISPLAY`` is
# a word, never an empty cell and never a zero — this codebase's standing rule is
# that a blank is never a zero and the kinds of blank are not each other.
REACHED_DISPLAY = "reached"
NOT_REACHED_DISPLAY = "not reached"

# A side that reached rows but none that can be ranked. Distinct from
# ``NOT_REACHED_DISPLAY``: "we hold this leg but no single row is its place" and
# "we do not hold this leg here" are different statements about the same blank.
UNDECIDED_DISPLAY = "no single leaf row"

# ``is_parent_row`` is TRI-STATE (reporting/membership.py::_parent_flags) and is
# kept tri-state here: ``None`` means another row holds exactly the same legs, so
# containment cannot decide — which is neither a parent nor a leaf.
PARENT_ROW = "parent"
LEAF_ROW = "leaf"
PARENT_INDISTINGUISHABLE = "indistinguishable"

# The FOURTH hierarchy state, and it is not one of the flag's three: this side
# does not hold the exposure in this row at all, so it makes no containment
# claim about it. Without it, "not reached" would render as
# ``PARENT_INDISTINGUISHABLE`` — the flag is ``None`` in both cases, and they are
# not the same statement.
HIERARCHY_NOT_REACHED = NOT_REACHED_DISPLAY

# What each state means to anyone tempted to add rows up.
_PARENT_NOTES: dict[str, str] = {
    PARENT_ROW: (
        "A PARENT row: its legs contain another row's in this group, so it "
        "double-counts against its children. Never add it to them."
    ),
    LEAF_ROW: "Provably contains and duplicates no other row in this group.",
    PARENT_INDISTINGUISHABLE: (
        "Whether this row is a parent is INDISTINGUISHABLE from the data — "
        "another row holds exactly the same legs. Treat it as 'may double "
        "count', never as a leaf."
    ),
    HIERARCHY_NOT_REACHED: (
        "This side does not hold the exposure in this row, so it makes no "
        "containment claim about it either way."
    ),
}

# The panel's own degraded reasons. A comparison that cannot be built is a
# different answer from an exposure that reached no instrumented row, and only
# the first is an "unavailable" panel.
PLACEMENT_NO_COMPARISON = (
    "No return-template comparison is available for this reconciliation, so "
    "where this exposure landed on the firm's side cannot be shown."
)
PLACEMENT_NO_KEY = "No reconciliation key was supplied, so there is nothing to place."

# A composite key that names no exposure identity column at all (counterparty +
# class, say). Nothing in it links a reconciled row to a membership leg, and
# matching on a non-identity segment is what leaked another exposure's
# placements onto the page — see ``_identity_tokens``.
PLACEMENT_NO_IDENTITY_KEY = (
    "This reconciliation's join key names no exposure reference, so its rows "
    "cannot be matched to the legs a return template reports. Add "
    "exposure_reference (or source_exposure_reference) to the mapping's "
    "our_keys to enable this panel."
)

# A reconciliation that produced no keyed frame at all (it failed, or the mapping
# named no comparable component). Distinct from "this key is not in the frame".
_NO_KEYED_FRAME = (
    "This reconciliation produced no per-key frame, so no exposure can be looked "
    "up in it. Re-run it with the join keys and at least one component mapped."
)

# How many rows of the per-key frame are read to recover the mapping's key
# columns. The concatenation is identical on every row, so a head is enough;
# several rows are read only so a column that coincides with a segment on ONE row
# cannot be mistaken for the key column.
_KEY_COLUMN_SAMPLE = 50

# Column namespaces the reconcile join DERIVES. Only the raw columns carried
# verbatim beside ``_recon_key`` can be the mapping's key columns, so the derived
# ones are excluded before any segment is matched back to a name.
_DERIVED_PREFIXES: tuple[str, ...] = (
    "our_",
    "legacy_",
    "abs_delta_",
    "rel_delta_",
    "signoff_",
    "_",
)
_DERIVED_COLUMNS: frozenset[str] = frozenset(
    {"row_bucket", "worst_component", "gross_exposure", "is_immaterial", "method"}
)

# The placeholder for a key position no carried column reproduces (a categorical
# key the join normalised before concatenating). Named, never guessed at.
_UNKNOWN_KEY_COLUMN = "?"


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
    hide_immaterial: bool = False
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


@dataclass(frozen=True, slots=True)
class PlacementRow:
    """One template row this exposure reached, ours beside theirs.

    ``in_ours`` / ``in_theirs`` are INDEPENDENT facts and both are rendered:
    ``our_display`` and ``their_display`` are always a word, so a row only one
    side reaches reads as a finding rather than as a half-empty line that looks
    like agreement.

    ``our_parent`` / ``their_parent`` carry ``is_parent_row`` unchanged, tri-state
    and all — ``None`` is "another row holds exactly the same legs", which is not
    ``False``.

    **The hierarchy state is rendered PER SIDE, and that is a correctness
    requirement, not a layout choice.** A single collapsed state taking ours and
    falling back to theirs shipped here and was caught in review: on a row that
    is ``False`` on our side and ``None`` on theirs — measured, and reachable
    whenever our side has two populated children under a parent and theirs has
    one — it rendered ``leaf`` with the note "Provably contains and duplicates no
    other row in this group". That note is a claim about BOTH sides and it is
    false for theirs. The tri-state was preserved perfectly in the fields above
    and then flattened one step before the analyst saw it, which is where the
    whole point of keeping it tri-state was lost.

    ``*_parent_state`` therefore has FOUR values, not three: the flag's own
    ``parent`` / ``leaf`` / ``indistinguishable``, plus ``HIERARCHY_NOT_REACHED``
    for a side that does not hold the exposure in this row and so makes no
    containment claim at all. Collapsing that fourth into ``indistinguishable``
    would be the same defect one level down — the flag is ``None`` in both cases
    and they are not the same statement.
    """

    row_ref: str
    row_name: str
    in_ours: bool
    in_theirs: bool
    our_parent: bool | None
    their_parent: bool | None
    side: str
    our_display: str
    their_display: str
    our_parent_state: str
    their_parent_state: str
    parent_note: str


@dataclass(frozen=True, slots=True)
class PlacementGroup:
    """Where one exposure landed in ONE template sheet's population group.

    The grain is the membership grain — ``(template_id, sheet, predicate_key)`` —
    and not the sheet, because a template row does not have one population: the
    origin-basis and post-substitution groups on a row hold different legs, and
    a panel that merged them would show a leg twice as though it had moved.

    ``our_placement`` / ``their_placement`` are the single provably-LEAF row on
    each side (``is_parent_row is False``), which is the same rule
    ``analysis.return_recon._group_legs`` places a leg by. ``""`` means the side
    has no single leaf — either it reached no row here, or every row holding the
    leg is a parent or indistinguishable — and the ``*_name`` field says which of
    those two it was. ``moved`` is only ever True when BOTH sides decided.
    """

    template_id: str
    template_label: str
    sheet: str
    predicate_key: str
    columns: tuple[str, ...]
    rows: tuple[PlacementRow, ...]
    our_placement: str
    our_placement_name: str
    their_placement: str
    their_placement_name: str
    moved: bool


@dataclass(frozen=True, slots=True)
class PlacementPanel:
    """The loan forensic's reverse lookup: which return rows this key reached.

    ``available`` false is the DEGRADED panel — there is no second side to place
    the exposure against — and ``reason`` says why, so the analyst gets the
    mapping remedy rather than a blank. An ``available`` panel with no ``groups``
    is a DIFFERENT answer: the comparison exists and this exposure reached no
    instrumented template row. Collapsing the two would report a missing legacy
    ledger as "this loan is in no return".

    **This panel carries NO money column, anywhere, and that is a structural
    property worth keeping.** The standing hazard on membership data is summing
    across ``predicate_key`` — the groups are BASES, not parts, so a substituted
    leg is counted on both and a per-sheet sum over-counts (measured at 3.00x on
    C 07.00 ``retail_other`` and 1.86x on C 08.01 ``corporate``). A panel that
    quotes no EAD and no RWEA cannot express that sum at all, so the defect is
    unreachable here rather than merely avoided. Adding a money column would
    re-open it and would need the per-group scoping rules in
    ``ui.views.return_recon`` to come with it.
    """

    key: str
    available: bool
    reason: str
    groups: tuple[PlacementGroup, ...]


@dataclass(frozen=True, slots=True)
class KeyResolution:
    """What an inbound ``?key=`` means, against the run's real join key.

    ``recon_key`` is the resolved ``_recon_key`` (``""`` when it could not be
    resolved); ``candidates`` are the reconciled keys a partial reference matched
    when more than one did, so the page can offer a choice rather than guess.
    ``key_columns`` names the mapping's ``our_keys`` — recovered from the frame,
    with ``"?"`` for any position no carried column reproduces — so the
    explanation says what the join key actually is.
    """

    requested: str
    recon_key: str
    matched_exactly: bool
    candidates: tuple[str, ...]
    key_columns: tuple[str, ...]
    reason: str


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


def summary_by_component_table(
    response: ReconciliationResponse, *, hide_immaterial: bool = False
) -> pl.DataFrame:
    """Tier 1 — per-component bucket counts, summed |delta| and break rate.

    With ``hide_immaterial`` the counts come from the material-only re-derivation
    (zero-gross-exposure rows removed), falling back to the all-rows summary when
    the material dict is empty.
    """
    if hide_immaterial:
        return response.collect_material_summaries().get(
            "summary_by_component", response.collect_summary_by_component()
        )
    return response.collect_summary_by_component()


def segment_tables(
    response: ReconciliationResponse, *, hide_immaterial: bool = False
) -> dict[str, pl.DataFrame]:
    """Tier 2 — where breaks concentrate: by bucket, exposure class and approach.

    Reads through the cached ``collect_*`` accessors (not the raw lazy bundle
    frames) so the overview render reuses the worker-warmed cache instead of
    re-executing the heavy reconcile join once per segment table. With
    ``hide_immaterial`` the counts come from the material-only re-derivation
    (zero-gross-exposure rows removed), each frame falling back to its all-rows
    accessor when the material dict is empty.
    """
    if hide_immaterial:
        mat = response.collect_material_summaries()
        return {
            "by_bucket": mat.get("summary_by_bucket", response.collect_summary_by_bucket()),
            "by_class": mat.get(
                "summary_by_exposure_class", response.collect_summary_by_exposure_class()
            ),
            "by_approach": mat.get("summary_by_approach", response.collect_summary_by_approach()),
            "by_class_method": mat.get(
                "summary_by_class_method", response.collect_summary_by_class_method()
            ),
        }
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


def class_allocation_by_method_table(response: ReconciliationResponse) -> pl.DataFrame:
    """Tier 2 — the asset-class allocation split by methodology within each class.

    Re-sorted into the presentation ``METHOD_ORDER`` (STD, FIRB, AIRB, SLOTTING, EQUITY,
    then anything unrecognised alphabetically) and then by class, so the table reads in
    the same order as the per-method chart sections beside it. Returns the frame
    untouched when it is empty or carries no ``method`` column — the reconciliation
    produced no by-method split (the ``approach`` component was unmapped), or the bundle
    is the bare empty one, and the page falls back to the combined allocation.
    """
    alloc = response.collect_class_allocation_by_method()
    if alloc.is_empty() or "method" not in alloc.columns:
        return alloc
    rank = pl.col("method").replace_strict(
        {m: i for i, m in enumerate(METHOD_ORDER)},
        default=len(METHOD_ORDER),
        return_dtype=pl.Int32,
    )
    return (
        alloc.with_columns(rank.alias("_method_rank"))
        .sort("_method_rank", "method", "exposure_class", nulls_last=True)
        .drop("_method_rank")
    )


def class_allocation_method_sections(response: ReconciliationResponse) -> list[dict]:
    """Per-methodology grouped-bar sections (Legacy vs Ours RWA by class).

    Mirrors the results / comparison tabs: one chart per method in ``METHOD_ORDER``,
    sharing one bar scale so a small method reads as genuinely small. Returns ``[]``
    when there is no by-method split, so the template falls back to the single combined
    allocation chart.
    """
    return method_split.grouped_series_sections(
        response.collect_class_allocation_by_method(),
        left_col="legacy_rwa",
        right_col="our_rwa",
        series=("Legacy", "Ours"),
    )


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
    hide_immaterial: bool = False,
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
    if hide_immaterial and "is_immaterial" in df.columns:
        df = df.filter(~pl.col("is_immaterial"))
    # ``is_immaterial`` rides on breaks_detail for the export/filter; it is an
    # internal marker, so drop it from the on-screen worklist projection.
    if "is_immaterial" in df.columns:
        df = df.drop("is_immaterial")
    return df.head(limit).fill_nan(None)


def breaks_signoff_progress(
    response: ReconciliationResponse,
    decisions: Mapping[str, Decision] | None = None,
    current_fps: Mapping[str, str] | None = None,
    *,
    hide_immaterial: bool = False,
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
    if hide_immaterial and "is_immaterial" in df.columns:
        df = df.filter(~pl.col("is_immaterial"))
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

    Filters the *memoised* wide per-key frame (the same eager snapshot the
    explorer renders from) down to one key — never a fresh ``scan_parquet``
    re-read of the results cache — then surfaces: a per-component panel
    (legacy / ours / Δ / bucket for every active component, matches included), that
    key's break rows, and the *driver* columns (explain / input) dropped from
    every on-screen table today and previously only reachable via the CSV export.
    Returns ``None`` when the reconciliation produced no keyed frame, or no row
    matches the key.

    Reading the shared collected snapshot (rather than re-executing the reconcile
    plan against ``last_results.parquet``) is what keeps this view working: a fresh
    re-scan is the one drill path that goes back to disk, so it alone is exposed to
    a torn / mis-written results parquet ("File out of specification: The page
    header reported the wrong page size"). It also makes this view's numbers match
    the explorer exactly, rather than risking a second, independently-summed collect.
    """
    full = response.collect_component_reconciliation()
    if "_recon_key" not in full.columns:
        return None
    df = full.filter(pl.col("_recon_key") == recon_key).fill_nan(None)
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
        "gross_exposure",
        "is_immaterial",
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

    breaks_all = response.collect_breaks_detail()
    breaks = (
        breaks_all.filter(pl.col("_recon_key") == recon_key).fill_nan(None)
        if "_recon_key" in breaks_all.columns
        else breaks_all.fill_nan(None)
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


def resolve_recon_key(response: ReconciliationResponse, key: str) -> KeyResolution:
    """Resolve an inbound ``?key=`` to the run's real ``_recon_key``.

    The return-template page links a leg through on its exposure reference alone
    (``source_exposure_reference or exposure_reference``), while this module
    looks up ``_recon_key`` — which ``analysis.reconciliation._key_expr`` builds
    as a ``_KEY_SEP``-joined concatenation of the mapping's ``our_keys``. On the
    default single-column key the two coincide; under ANY composite mapping they
    do not, and the link dead-ends on a 404 that reads as "this loan does not
    exist". It exists; the link simply addressed it by one of its key columns.

    Resolution is two steps and it never guesses:

    1. An exact ``_recon_key`` — the default mapping's case, unchanged.
    2. A key whose ``_KEY_SEP`` segments contain *key* — the composite case.

    Exactly one match resolves. SEVERAL is a genuine ambiguity (one reference
    reconciled once per class, say) and comes back as ``candidates`` for the page
    to offer — picking the first would answer with a different loan. NONE comes
    back with a reason naming the join key's columns, which is the actionable
    form of the old blanket "No reconciliation row matches that key."
    """

    def unresolved(reason: str, columns: tuple[str, ...] = ()) -> KeyResolution:
        return KeyResolution(
            key, "", matched_exactly=False, candidates=(), key_columns=columns, reason=reason
        )

    df = response.collect_component_reconciliation()
    if "_recon_key" not in df.columns:
        return unresolved(_NO_KEYED_FRAME)
    if not key:
        return unresolved(PLACEMENT_NO_KEY)

    columns = _key_columns(df)
    keys = pl.col("_recon_key").cast(pl.String)
    if df.filter(keys == key).height:
        return KeyResolution(
            key, key, matched_exactly=True, candidates=(), key_columns=columns, reason=""
        )

    candidates = _key_candidates(df, key, columns)
    if len(candidates) == 1:
        logger.info("recon key %r resolved to its composite key by segment match", key)
        return KeyResolution(
            key, candidates[0], matched_exactly=False, candidates=(), key_columns=columns, reason=""
        )
    named = " + ".join(columns) if columns else "an unnamed key"
    if candidates:
        return KeyResolution(
            key,
            "",
            matched_exactly=False,
            candidates=candidates,
            key_columns=columns,
            reason=(
                f"This reconciliation joins on {named}, so {key!r} on its own addresses "
                f"{len(candidates)} reconciled rows rather than one. Pick the one you meant."
            ),
        )
    # The composite hint belongs only on a composite key. On a single-column
    # mapping the reference simply is not in the run, and telling the analyst to
    # look at a composite key would send them to a mapping that does not exist.
    hint = (
        " — a link built from the exposure reference alone cannot address a composite key."
        if len(columns) > 1
        else "."
    )
    return unresolved(
        f"No reconciliation row matches {key!r}. This run joins on {named}{hint}", columns
    )


def placement_panel(
    recon: ReturnRecon | None,
    recon_key: str,
    *,
    key_columns: Sequence[str] = (),
    reason: str = "",
) -> PlacementPanel:
    """Which return-template rows this exposure reached, ours beside theirs.

    The reverse of the template-compare page: that page starts at a cell and
    drills to the exposures behind it, this one starts at an exposure and says
    where it landed. Without it the placement half of "why did this contract move
    band?" stays manual.

    *recon* is the memoised comparison (``ui.views.return_recon.build_comparison``)
    or ``None`` on the degraded path, where *reason* — the typed reason
    ``comparison_inputs`` already returns — is shown instead. Nothing is generated
    here: this reads the membership frames the comparison already holds.

    The exposure is matched on the identity columns membership carries
    (``exposure_reference`` / ``source_exposure_reference``) against the segments
    of *recon_key*, because the reconciliation key and the leg reference are the
    same string only under the default mapping — a composite key carries the
    reference as one segment, and a real-estate or guarantee sub-row carries the
    collapsed parent as its ``source_exposure_reference``.
    """
    if recon is None:
        return PlacementPanel(
            key=recon_key, available=False, reason=reason or PLACEMENT_NO_COMPARISON, groups=()
        )
    tokens = sorted(_identity_tokens(recon_key, key_columns))
    if not tokens:
        # Two ways to get here and they are different answers: no key at all, or
        # a composite key that names no exposure identity column, in which case
        # nothing links its rows to a leg and saying so beats matching widely.
        blocked = PLACEMENT_NO_KEY if not recon_key else PLACEMENT_NO_IDENTITY_KEY
        return PlacementPanel(key=recon_key, available=False, reason=blocked, groups=())

    ours = _placement_membership(recon.ours, tokens)
    theirs = _placement_membership(recon.theirs, tokens)
    addresses = sorted(set(ours) | set(theirs), key=lambda a: (a[0], a[1] or "", a[2]))
    if not addresses:
        logger.info("placement panel: no membership reaches key %r", recon_key)
    return PlacementPanel(
        key=recon_key,
        available=True,
        reason="",
        groups=tuple(
            _placement_group(recon, address, ours.get(address, {}), theirs.get(address, {}))
            for address in addresses
        ),
    )


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


def _identity_tokens(recon_key: str, key_columns: Sequence[str] = ()) -> set[str]:
    """The exposure identities a ``_recon_key`` carries — and ONLY those.

    ``_key_expr`` concatenates the mapping's ``our_keys`` with ``_KEY_SEP``, so a
    composite key holds an exposure reference alongside whatever else it keys on.
    This returns the segments that came from an IDENTITY key column, positionally
    matched against *key_columns*, and nothing else.

    **Taking every segment leaked another exposure's placements onto the page,
    in both directions.** Measured on a ``(counterparty_reference,
    exposure_reference)`` mapping where a second exposure was referenced by the
    counterparty's own reference — an overdraft booked at counterparty level,
    an ordinary shape. Loan ``X`` of counterparty ``CP`` keys as ``CP||X``, whose
    segments are ``{CP, X}``, so the decoy's membership merged in and the panel
    (a) grew a row ``X`` never reached and (b) LOST a real band move: the decoy
    added a second provably-leaf row, ``_placement_leaf`` saw two leaves, and
    ``moved`` fell from True to False. A confident, plausible, wrong answer on a
    regulatory forensic — the failure class this batch exists to catch.

    Note what the fix is NOT. The sibling identity rule at
    ``analysis.return_recon._comparison_key`` resolves ONE identity per leg, and
    copying its column list would not have helped: the column set was never the
    problem (the two-column OR in ``_placement_membership`` is load-bearing for
    split legs, whose ``_recon_key`` is the collapsed parent). The TOKEN SET was
    too wide. The grain is what moved.

    With no *key_columns* the whole key is the single token, unsplit — the safe
    reading, and the right one for the single-column default: a key that is its
    own identity can only ever match its own exposure. Empty segments are
    dropped, since a null key column concatenates as ``""`` and would otherwise
    match every leg with a null reference.
    """
    if len(key_columns) <= 1:
        return {recon_key} if recon_key else set()
    return {
        segment
        for segment, column in zip(recon_key.split(_KEY_SEP), key_columns, strict=False)
        if segment and column in KEY_COLUMNS
    }


def _key_candidates(df: pl.DataFrame, key: str, key_columns: Sequence[str]) -> tuple[str, ...]:
    """Every ``_recon_key`` whose key columns include *key* as one of its values.

    A SEGMENT match, and deliberately only that. An identity-column fallback was
    written here first and removed as dead: the only shape it could serve — a
    composite key keyed on ``source_exposure_reference`` — already puts that
    reference in a segment, and a composite keyed on ``exposure_reference``
    carries the sub-row reference in both the segment and the column, so the
    fallback never resolved anything the segment match did not. A link whose
    reference reaches neither (the collapsed parent of a split, under a composite
    key) is reported with the reason above rather than resolved by a prefix
    guess: ``M1`` prefixes ``M10`` as readily as ``M1_rre``.

    Stays vectorised — the per-key frame is the widest in the run and this is on
    a page render.

    A SINGLE-COLUMN key yields nothing here, and must: its whole value is its
    only segment, so the exact match in ``resolve_recon_key`` has already had its
    chance, and splitting a reference that merely contains ``||`` would resolve a
    fragment of it to the whole loan. Measured on ``L1||A``, where both ``L1``
    and ``A`` came back as that loan.
    """
    if len(key_columns) <= 1:
        return ()
    matched = df.filter(pl.col("_recon_key").cast(pl.String).str.split(_KEY_SEP).list.contains(key))
    if not matched.height:
        return ()
    return tuple(
        str(value)
        for value in matched.get_column("_recon_key").unique().sort().to_list()
        if value is not None
    )


def _key_columns(df: pl.DataFrame) -> tuple[str, ...]:
    """The mapping's ``our_keys``, recovered from the per-key frame itself.

    ``ReconciliationResponse`` does not carry the mapping, but the reconcile does
    carry each key column VERBATIM beside ``_recon_key``
    (``analysis.reconciliation.ReconciliationRunner._prepare_our_side``), so each
    segment can be matched back to the column that reproduces it across a sample
    of rows. Only the raw carried columns are candidates — every ``our_`` /
    ``legacy_`` / delta / bucket column is derived by the join and could coincide
    with a segment by accident.

    A position no column reproduces (a categorical key the join casefolded before
    concatenating) is named ``_UNKNOWN_KEY_COLUMN`` rather than guessed at: a
    wrong column name in the explanation sends the analyst to fix the wrong side
    of the mapping.

    ``_is_carried_column`` is DEFENCE IN DEPTH, not a load-bearing guard, and is
    recorded as such so nobody later mistakes it for one in either direction:
    ``_prepare_our_side`` selects the verbatim key columns immediately after
    ``_recon_key`` and before anything derived, so column order alone already
    reaches the same answer. Removing the filter reddens no test — measured. It
    stays because the intent ("only a carried column can BE a key column") should
    not depend on a select order two modules away.
    """
    if "_recon_key" not in df.columns or df.height == 0:
        return ()
    sample = df.head(_KEY_COLUMN_SAMPLE)
    keys = [str(value or "") for value in sample.get_column("_recon_key").cast(pl.String).to_list()]
    candidates = {
        name: [
            "" if value is None else str(value)
            for value in sample.get_column(name).cast(pl.String, strict=False).to_list()
        ]
        for name in sample.columns
        if _is_carried_column(name)
    }

    # A SINGLE-COLUMN key reproduces ``_recon_key`` WHOLE, and that is tested
    # first so the separator is never read out of data. ``_KEY_SEP`` is two
    # characters a firm may legitimately put in an exposure reference, and
    # splitting on it regardless was measured to do two wrong things at once on
    # a single-column mapping keyed on ``L1||A``: it reported the join key as
    # ``? + ?`` (no column reproduces "L1" or "A", because the column holds the
    # whole string), and it resolved BOTH ``L1`` and ``A`` — half a reference,
    # and a fragment of one — to the whole loan, silently and with no reason
    # given. Under a single-column mapping there is nothing to split on: the
    # separator is data, not structure.
    whole = next((name for name, values in candidates.items() if values == keys), None)
    if whole is not None:
        return (whole,)

    segments = [key.split(_KEY_SEP) for key in keys]
    width = max((len(parts) for parts in segments), default=0)
    names: list[str] = []
    for position in range(width):
        wanted = [parts[position] if position < len(parts) else "" for parts in segments]
        names.append(
            next(
                (name for name, values in candidates.items() if values == wanted),
                _UNKNOWN_KEY_COLUMN,
            )
        )
    return tuple(names)


def _is_carried_column(name: str) -> bool:
    """Whether *name* is a raw column the reconcile carried, not one it derived."""
    return (
        name != "_recon_key"
        and name not in _DERIVED_COLUMNS
        and not name.endswith("_bucket")
        and not name.startswith(_DERIVED_PREFIXES)
    )


def _placement_membership(
    side: SideView, tokens: list[str]
) -> dict[tuple[str, str | None, str], dict[str, bool | None]]:
    """One side's ``{(template, sheet, group): {row_ref: is_parent_row}}`` for a key.

    Deduplicated on the whole address because a split exposure contributes
    several legs under one ``source_exposure_reference``, and they land in the
    same rows — the panel places the EXPOSURE, not each leg. ``is_parent_row`` is
    a property of ``(row, predicate_key)``, so the dedup cannot drop a state.
    """
    legs = side.membership.legs
    if legs.height == 0:
        return {}
    matched = (
        legs.filter(
            pl.col("exposure_reference").is_in(tokens)
            | pl.col("source_exposure_reference").is_in(tokens)
        )
        .select("template_id", "sheet", "row_ref", "predicate_key", "is_parent_row")
        .unique()
    )
    out: dict[tuple[str, str | None, str], dict[str, bool | None]] = {}
    for record in matched.iter_rows(named=True):
        sheet = record["sheet"]
        address = (
            str(record["template_id"]),
            None if sheet is None else str(sheet),
            str(record["predicate_key"]),
        )
        out.setdefault(address, {})[str(record["row_ref"])] = record["is_parent_row"]
    return out


def _placement_group(
    recon: ReturnRecon,
    address: tuple[str, str | None, str],
    ours: dict[str, bool | None],
    theirs: dict[str, bool | None],
) -> PlacementGroup:
    """One ``(template, sheet, predicate group)``, ours beside theirs."""
    template_id, sheet, predicate_key = address
    names = _placement_row_names(recon, template_id, sheet)
    our_leaf = _placement_leaf(ours)
    their_leaf = _placement_leaf(theirs)
    return PlacementGroup(
        template_id=template_id,
        template_label=TEMPLATE_CODES.get(template_id, {}).get(recon.framework, "") or template_id,
        sheet=sheet or "",
        predicate_key=predicate_key,
        columns=_placement_columns(recon, template_id, sheet, predicate_key),
        rows=tuple(
            _placement_row(row_ref, names.get(row_ref, ""), ours, theirs)
            for row_ref in sorted(set(ours) | set(theirs))
        ),
        our_placement=our_leaf,
        our_placement_name=_placement_name(our_leaf, names, reached=bool(ours)),
        their_placement=their_leaf,
        their_placement_name=_placement_name(their_leaf, names, reached=bool(theirs)),
        moved=bool(our_leaf and their_leaf and our_leaf != their_leaf),
    )


def _placement_row(
    row_ref: str, row_name: str, ours: dict[str, bool | None], theirs: dict[str, bool | None]
) -> PlacementRow:
    """One row of a placement group, with BOTH sides stated explicitly."""
    in_ours = row_ref in ours
    in_theirs = row_ref in theirs
    if in_ours and in_theirs:
        side = PLACEMENT_BOTH
    elif in_ours:
        side = PLACEMENT_OURS_ONLY
    else:
        side = PLACEMENT_THEIRS_ONLY
    our_state = _parent_state(ours.get(row_ref), reached=in_ours)
    their_state = _parent_state(theirs.get(row_ref), reached=in_theirs)
    return PlacementRow(
        row_ref=row_ref,
        row_name=row_name,
        in_ours=in_ours,
        in_theirs=in_theirs,
        our_parent=ours.get(row_ref),
        their_parent=theirs.get(row_ref),
        side=side,
        our_display=REACHED_DISPLAY if in_ours else NOT_REACHED_DISPLAY,
        their_display=REACHED_DISPLAY if in_theirs else NOT_REACHED_DISPLAY,
        our_parent_state=our_state,
        their_parent_state=their_state,
        parent_note=_parent_note(our_state, their_state),
    )


def _placement_leaf(flags: dict[str, bool | None]) -> str:
    """The one row a side placed the exposure on, or ``""`` when none decides.

    The single-leaf rule ``analysis.return_recon._group_legs`` places legs by: a
    row counts only where ``is_parent_row`` is provably ``False``, and only a
    SINGLE such row is a placement. ``True`` (a strict parent) and ``None``
    (indistinguishable from another row) are both non-leaves — reporting either
    as the exposure's band would state a containment the data does not support.
    """
    leaves = [row_ref for row_ref, parent in flags.items() if parent is False]
    return leaves[0] if len(leaves) == 1 else ""


def _placement_name(row_ref: str, names: dict[str, str], *, reached: bool) -> str:
    """The placement's row name, or the RIGHT kind of blank when there is none.

    Three outcomes, three strings: the band's name, "we do not hold this leg in
    this group", and "we hold it but no single row is its place". The last two
    are different findings and are never rendered alike.
    """
    if row_ref:
        return names.get(row_ref, row_ref)
    return UNDECIDED_DISPLAY if reached else NOT_REACHED_DISPLAY


def _parent_state(flag: bool | None, *, reached: bool) -> str:
    """One side's hierarchy claim about one row — FOUR states, four labels.

    ``reached`` is checked first and is not a special case of the flag: a side
    that does not hold the exposure in this row carries ``None`` for exactly the
    same reason a genuinely undecidable row does, and reading the two alike
    would report "we cannot tell whether this is a parent" where the truth is
    "we are not in this row".
    """
    if not reached:
        return HIERARCHY_NOT_REACHED
    if flag is True:
        return PARENT_ROW
    if flag is False:
        return LEAF_ROW
    return PARENT_INDISTINGUISHABLE


def _parent_note(our_state: str, their_state: str) -> str:
    """The hierarchy note, ATTRIBUTED whenever the two sides do not agree.

    An unattributed note is a claim about both sides. Where they diverge — our
    side a provable leaf, theirs indistinguishable — there is no single true
    sentence, so the note names each side rather than picking one.
    """
    if our_state == their_state:
        return _PARENT_NOTES[our_state]
    return f"Ours — {_PARENT_NOTES[our_state]} Theirs — {_PARENT_NOTES[their_state]}"


def _placement_row_names(recon: ReturnRecon, template_id: str, sheet: str | None) -> dict[str, str]:
    """``row_ref -> row_name`` off the generated frames, ours winning.

    Read from the frames rather than a row-name table for the same reason the
    template-compare page does: a row emitted on one side only still needs a
    label, and the CRR and Basel 3.1 row axes differ, so any literal list would
    pin one framework.
    """
    names: dict[str, str] = {}
    for side in (recon.theirs, recon.ours):
        frames = side.frames.get(template_id, {})
        if sheet is not None:
            frame = frames.get(sheet)
        else:
            frame = next(iter(frames.values())) if len(frames) == 1 else None
        if frame is None or not {"row_ref", "row_name"} <= set(frame.columns):
            continue
        for record in frame.select("row_ref", "row_name").iter_rows(named=True):
            ref = record["row_ref"]
            if ref is not None:
                names[str(ref)] = str(record["row_name"] or "")
    return names


def _placement_columns(
    recon: ReturnRecon, template_id: str, sheet: str | None, predicate_key: str
) -> tuple[str, ...]:
    """The published columns this predicate group serves, both sides merged.

    A group is only addressable back to a CELL through this mapping — the row
    alone is not enough, because several groups sit on one row.

    THE MERGE IS DELIBERATE AND IS NOT THE COLLAPSE ``PlacementRow`` FORBIDS.
    ``describe_cell`` binds a cell against each side's own sealed columns, so the
    two sides can differ, and this lists a column either binds. That is right
    because the field answers "which cells does this population back" — a
    navigation aid — and a cell one side cannot bind is still a cell the other
    reports. It states nothing per-side, so there is no per-side claim to get
    wrong; the hierarchy state did state one, which is why that one is split.
    """
    refs: list[str] = []
    for side in (recon.ours, recon.theirs):
        frame = side.membership.columns.filter(
            (pl.col("template_id") == template_id)
            & (pl.col("sheet").is_null() if sheet is None else pl.col("sheet") == sheet)
            & (pl.col("predicate_key") == predicate_key)
        )
        for value in frame.get_column("col_ref").to_list():
            if value is not None and str(value) not in refs:
                refs.append(str(value))
    return tuple(refs)


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
    if filters.hide_immaterial and "is_immaterial" in df.columns:
        df = df.filter(~pl.col("is_immaterial"))
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
