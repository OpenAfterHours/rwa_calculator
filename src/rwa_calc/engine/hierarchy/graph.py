"""
Counterparty and facility graph resolution for the hierarchy stage.

Pipeline position:
    Loader -> HierarchyResolver (engine/hierarchy) -> Classifier
    Sub-module of the hierarchy stage package; consumed by ``resolver``
    (CounterpartyLookup build), ``unify`` (facility root lookup + ancestor
    closure) and ``facility_undrawn`` (shared mapping helpers).

Key responsibilities:
- Build and seal the 4-frame CounterpartyLookup (dedup org mappings,
  ultimate parents, rating inheritance, enriched counterparties).
- Resolve counterparty and facility parent graphs via eager dict traversal
  (ultimate parent, root facility, ancestor closure).
- Shared facility-mapping helpers (root resolution, child-type filtering).
- Make the facility-mapping graph the tree every consumer assumes
  (review findings RC-01 / RC-02 / SF-03): one parent per sub-facility (the
  lowest reference, DQ021), every member of a cycle a root (DQ022), and one
  root per loan / contingent (that of its lowest-referenced parent) —
  deterministically, whatever the row order.
- Emit DQ004 duplicate-key and HIE003 depth-truncation warnings.

References:
- CRR Art. 4(1)(39): Group of connected clients (hierarchy resolution)
- CRR Art. 230-231: collateral cascade over nested facility hierarchies
  (ancestor closure consumer lives in the CRM stage)
- CRR Art. 4(1)(56) / PS1/26 Glossary "conversion factor": a commitment's
  undrawn amount is "determined by the advised limit", which one drawing
  reduces once; CRR / PS1/26 Art. 111(1): every commitment is measured
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import polars as pl

from rwa_calc.contracts.bundles import CounterpartyLookup
from rwa_calc.contracts.edges import CP_LOOKUP_EDGES, RAW_TABLE_EDGES, seal
from rwa_calc.contracts.errors import (
    ERROR_DUPLICATE_KEY,
    ERROR_HIERARCHY_DEPTH,
    CalculationError,
    facility_mapping_cycle_warning,
    facility_multi_parent_warning,
)
from rwa_calc.data.schemas import VALID_CHILD_TYPES
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity
from rwa_calc.engine.hierarchy.ratings import build_rating_inheritance_lazy
from rwa_calc.engine.utils import has_required_columns

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FacilityGraph:
    """The facility -> facility edges the hierarchy stage walks, made a forest.

    ``edges`` holds one row per sub-facility (``child_facility_reference`` ->
    ``parent_facility_reference``), sorted, with at most one parent per child
    and no cycle; None when the mappings frame cannot carry an edge.
    ``errors`` are the DQ021 / DQ022 WARNINGs naming every repair made to get
    there — empty for a well-formed hierarchy.
    """

    edges: pl.DataFrame | None
    errors: tuple[CalculationError, ...] = ()


def build_counterparty_lookup(
    counterparties: pl.LazyFrame,
    org_mappings: pl.LazyFrame | None,
    ratings: pl.LazyFrame | None,
) -> tuple[CounterpartyLookup, list[CalculationError]]:
    """
    Build counterparty hierarchy lookup using pure LazyFrame operations.

    Returns:
        Tuple of (CounterpartyLookup, list of errors)
    """
    errors: list[CalculationError] = []

    # If org_mappings is None, create empty LazyFrame with expected schema
    if org_mappings is None:
        org_mappings = pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        )

    # Deduplicate org_mappings on child_counterparty_reference (first-row-
    # wins by input order). Without this, downstream joins fan out — one
    # exposure on the duplicated child becomes one row per parent. Emit a
    # DQ004 WARNING per duplicated child so operators can trace the bad
    # rows back to their input file.
    org_mappings, dup_errors = _dedup_org_mappings(org_mappings)
    errors.extend(dup_errors)

    # Build ultimate parent mapping (LazyFrame). The frame carries an
    # internal ``truncated`` column flagging chains that hit ``max_depth``;
    # we synthesise one HIE003 WARNING per truncated row and then drop the
    # column so downstream consumers see the published schema.
    ultimate_parents = build_ultimate_parent_lazy(org_mappings)
    errors.extend(_extract_hierarchy_depth_errors(ultimate_parents))
    ultimate_parents = ultimate_parents.drop("truncated")

    # If ratings is None, use the canonical empty sealed frame so the
    # rating-inheritance pipeline sees the full RATINGS_SCHEMA column set.
    if ratings is None:
        ratings = RAW_TABLE_EDGES["ratings"].empty_frame()

    # Build rating inheritance (LazyFrame)
    rating_info = build_rating_inheritance_lazy(counterparties, ratings, ultimate_parents)

    # Enrich counterparties with hierarchy info
    enriched_counterparties = _enrich_counterparties_with_hierarchy(
        counterparties,
        org_mappings,
        ratings,
        ultimate_parents,
        rating_info,
    )

    # Producer seal (Phase 3): pure plan-level conform + brand per
    # lookup frame — the classifier's cp_* enrichment and the CRM
    # guarantor resolution consume these shapes as contract.
    return CounterpartyLookup(
        counterparties=seal(enriched_counterparties, CP_LOOKUP_EDGES["counterparties"]),
        parent_mappings=seal(
            org_mappings.select(
                [
                    "child_counterparty_reference",
                    "parent_counterparty_reference",
                ]
            ),
            CP_LOOKUP_EDGES["parent_mappings"],
        ),
        ultimate_parent_mappings=seal(
            ultimate_parents, CP_LOOKUP_EDGES["ultimate_parent_mappings"]
        ),
        rating_inheritance=seal(rating_info, CP_LOOKUP_EDGES["rating_inheritance"]),
    ), errors


def build_ultimate_parent_lazy(
    org_mappings: pl.LazyFrame,
    max_depth: int = 10,
) -> pl.LazyFrame:
    """
    Build ultimate parent mapping using eager graph traversal.

    Collects the small edge data eagerly, resolves the full graph via dict
    traversal, and returns the result as a LazyFrame for downstream joins.

    Returns LazyFrame with columns:
    - counterparty_reference: The entity
    - ultimate_parent_reference: Its deepest reachable parent (the true
      root, or the parent at ``max_depth`` if the chain was truncated)
    - hierarchy_depth: Number of levels traversed
    - truncated: True iff the chain was cut off at ``max_depth``; consumed
      by ``build_counterparty_lookup`` to synthesise HIE003 WARNINGs and
      stripped before the LazyFrame is exposed on ``CounterpartyLookup``.
    """
    edges = (
        org_mappings.select(
            [
                "child_counterparty_reference",
                "parent_counterparty_reference",
            ]
        )
        .unique()
        .collect()
    )

    resolved = _resolve_graph_eager(
        edges,
        child_col="child_counterparty_reference",
        parent_col="parent_counterparty_reference",
        max_depth=max_depth,
    )

    return resolved.rename(
        {
            "entity": "counterparty_reference",
            "root": "ultimate_parent_reference",
            "depth": "hierarchy_depth",
        }
    ).lazy()


def collect_facility_graph(facility_mappings: pl.LazyFrame) -> FacilityGraph:
    """Collect the facility -> facility edges once (small data) and make them a forest.

    Both facility graph lookups (:func:`build_facility_root_lookup`,
    :func:`build_facility_ancestor_closure`) walk this edge set, so the
    hierarchy stage collects it once and hands it to both via ``edges=``.

    The mappings are consumed everywhere as a TREE, and nothing used to make
    them one (review findings RC-02 / SF-03):

    - a sub-facility with two parents had its root picked by a last-wins dict
      over an unordered ``unique()``, so the RWA changed from run to run;
    - a cycle made every member somebody's child, and only roots emit an
      undrawn row, so every member's commitment vanished.

    Both are malformed input. The repair is deterministic and conservative, and
    each instance is named: a second parent is dropped — the sub-facility keeps
    its LOWEST-referenced parent (DQ021) — and every member of a cycle becomes a
    root of its own, keeping its own limit and undrawn commitment (DQ022). No
    commitment is dropped and none is netted against another twice.

    Null ``child_type`` values (legacy mappings) yield no facility-typed rows.

    Returns:
        :class:`FacilityGraph` — the forest's edges (``child_facility_reference``
        / ``parent_facility_reference``, sorted) and the repairs' warnings.
    """
    if not has_required_columns(
        facility_mappings, {"parent_facility_reference", "child_reference"}
    ):
        return FacilityGraph(edges=None)
    raw = (
        facility_mappings.filter(
            pl.col("child_type").fill_null("").str.to_lowercase() == "facility"
        )
        .select(
            [
                pl.col("child_reference").alias("child_facility_reference"),
                pl.col("parent_facility_reference"),
            ]
        )
        .unique()
        .collect()
    )
    return _resolve_facility_forest(raw)


def collect_facility_edges(facility_mappings: pl.LazyFrame) -> pl.DataFrame | None:
    """The forest edges of :func:`collect_facility_graph`, without its warnings.

    For callers that need only the edges (the root lookup and the ancestor
    closure when no ``edges=`` was handed in); the hierarchy stage itself calls
    :func:`collect_facility_graph` so the repairs are reported.

    Returns:
        DataFrame with ``child_facility_reference`` / ``parent_facility_reference``,
        or None when the mappings frame cannot carry any edge (missing columns).
    """
    return collect_facility_graph(facility_mappings).edges


def resolve_exposure_mappings(
    facility_mappings: pl.LazyFrame,
    facility_edges: pl.DataFrame | None,
    root_lookup: pl.LazyFrame,
) -> pl.LazyFrame:
    """The facility mappings every hierarchy consumer reads, made a tree.

    - Facility rows are replaced by the forest of :func:`collect_facility_graph`
      (one parent per sub-facility, no cycle).
    - A loan / contingent mapped under facilities of MORE THAN ONE ROOT keeps
      only the mappings under ONE root: the root of its lowest-referenced parent
      (review finding RC-01 — a drawing is made under one commitment; reducing
      every root it was mapped to understated the undrawn exposure). Mappings to
      several facilities of THAT root are all kept: an overlapping sub-limit
      genuinely constrains the same drawing, so each sub-limit's own headroom is
      reduced by it, while ``facility_undrawn.facility_utilisation_rows`` reduces
      the root's headroom once (SF-03). DQ021 names every such child
      (``facility_warnings``).
    - Every other row (a null or unrecognised ``child_type``, a null reference)
      passes through unchanged.

    Lazy: the primary root is a group-by over the mapping rows, joined back.

    Args:
        facility_mappings: The sealed facility mappings.
        facility_edges: The forest edges (:func:`collect_facility_graph`); None
            — the mappings cannot carry an edge, i.e. lack the reference
            columns — returns ``facility_mappings`` unchanged (no schema is
            re-resolved here: the graph collection already answered that).
        root_lookup: :func:`build_facility_root_lookup` over those edges.

    Returns:
        A LazyFrame with the mappings' three columns.
    """
    if facility_edges is None:
        return facility_mappings
    columns = ["parent_facility_reference", "child_reference", "child_type"]
    kind = pl.col("child_type").str.to_lowercase()
    is_facility = kind.eq_missing("facility")
    is_exposure = (
        kind.is_in(sorted(VALID_CHILD_TYPES - {"facility"})).eq_missing(True)
        & pl.col("parent_facility_reference").is_not_null()
        & pl.col("child_reference").is_not_null()
    )

    others = facility_mappings.filter(~is_facility & ~is_exposure).select(columns)
    forest = facility_edges.lazy().select(
        pl.col("parent_facility_reference"),
        pl.col("child_facility_reference").alias("child_reference"),
        pl.lit("facility").alias("child_type"),
    )
    parts = [others, forest]

    exposure_rows = resolve_to_root_facility(
        facility_mappings.filter(is_exposure).select(columns).with_columns(kind.alias("_kind")),
        root_lookup,
    )
    primary_roots = exposure_rows.group_by(["_kind", "child_reference"]).agg(
        pl.col("aggregation_facility")
        .sort_by("parent_facility_reference")
        .first()
        .alias("_primary_root")
    )
    parts.append(
        exposure_rows.join(primary_roots, on=["_kind", "child_reference"], how="inner")
        .filter(pl.col("aggregation_facility") == pl.col("_primary_root"))
        .select(columns)
    )
    return pl.concat(parts, how="vertical_relaxed")


def build_facility_root_lookup(
    facility_mappings: pl.LazyFrame,
    max_depth: int = 10,
    *,
    edges: pl.DataFrame | None = None,
) -> pl.LazyFrame:
    """
    Build root facility lookup using eager graph traversal.

    Collects the small facility edge data eagerly (or reuses ``edges``),
    resolves the full graph via dict traversal, and returns the result as a
    LazyFrame.

    Args:
        facility_mappings: Facility mappings with ``parent_facility_reference``,
                         ``child_reference``, and ``child_type`` columns
                         (sealed at the loader edge, so ``child_type``
                         always exists — typed null when unreported).
        max_depth: Maximum hierarchy depth to traverse
        edges: Facility edges already collected by :func:`collect_facility_edges`
            (None: collect them here)

    Returns:
        LazyFrame with columns:
        - child_facility_reference: The sub-facility
        - root_facility_reference: Its ultimate root facility
        - facility_hierarchy_depth: Number of levels traversed
    """
    empty_result = pl.LazyFrame(
        schema={
            "child_facility_reference": pl.String,
            "root_facility_reference": pl.String,
            "facility_hierarchy_depth": pl.Int32,
        }
    )

    facility_edges = edges if edges is not None else collect_facility_edges(facility_mappings)
    if facility_edges is None or facility_edges.height == 0:
        return empty_result

    # The HIE003 channel is counterparty-scoped; drop the new ``truncated``
    # marker column so the facility lookup keeps its established schema.
    resolved = _resolve_graph_eager(
        facility_edges,
        child_col="child_facility_reference",
        parent_col="parent_facility_reference",
        max_depth=max_depth,
    ).drop("truncated")

    return resolved.rename(
        {
            "entity": "child_facility_reference",
            "root": "root_facility_reference",
            "depth": "facility_hierarchy_depth",
        }
    ).lazy()


def build_facility_ancestor_closure(
    facility_mappings: pl.LazyFrame,
    max_depth: int = 10,
    *,
    edges: pl.DataFrame | None = None,
) -> pl.LazyFrame:
    """Build the facility ancestor closure for multi-level collateral cascade.

    Walks the facility→facility graph and, for every sub-facility, collects
    the facility itself plus every ancestor facility up to the root. The CRM
    stage uses this so collateral pledged at any ancestor facility (parent,
    grandparent, ... root) cascades pro-rata to the whole descendant subtree
    (CRR Art. 230-231). Only facilities that appear as a child in a
    facility→facility mapping are included; roots / single-level facilities
    are absent and handled by the ``[parent]`` fallback at the call site.

    Args:
        facility_mappings: Facility mappings with ``parent_facility_reference``,
            ``child_reference`` and ``child_type`` (sealed at the loader
            edge, so ``child_type`` always exists).
        max_depth: Maximum hierarchy depth to traverse.
        edges: Facility edges already collected by :func:`collect_facility_edges`
            (None: collect them here).

    Returns:
        LazyFrame with columns:
        - child_facility_reference: the sub-facility
        - ancestor_facilities: list[str] of the facility + all ancestors
          (incl. self).
    """
    empty_result = pl.LazyFrame(
        schema={
            "child_facility_reference": pl.String,
            "ancestor_facilities": pl.List(pl.String),
        }
    )
    facility_edges = edges if edges is not None else collect_facility_edges(facility_mappings)
    if facility_edges is None or facility_edges.height == 0:
        return empty_result

    closure = _resolve_ancestors_eager(
        facility_edges,
        child_col="child_facility_reference",
        parent_col="parent_facility_reference",
        max_depth=max_depth,
    )
    return (
        closure.lazy()
        .group_by("descendant")
        .agg(pl.col("ancestor").alias("ancestor_facilities"))
        .rename({"descendant": "child_facility_reference"})
    )


def resolve_to_root_facility(
    frame: pl.LazyFrame,
    root_lookup: pl.LazyFrame,
) -> pl.LazyFrame:
    """Map each row's parent_facility_reference to the root facility.

    Adds an ``aggregation_facility`` column that is the root facility for
    multi-level hierarchies, or falls back to ``parent_facility_reference``
    for single-level ones.
    """
    return (
        frame.join(
            root_lookup.select(
                [
                    pl.col("child_facility_reference"),
                    pl.col("root_facility_reference").alias("_root_fac"),
                ]
            ),
            left_on="parent_facility_reference",
            right_on="child_facility_reference",
            how="left",
        )
        .with_columns(
            pl.coalesce(
                pl.col("_root_fac"),
                pl.col("parent_facility_reference"),
            ).alias("aggregation_facility"),
        )
        .drop("_root_fac")
    )


def filter_mappings_by_child_type(
    facility_mappings: pl.LazyFrame,
    child_type: str,
) -> pl.LazyFrame:
    """Return facility_mappings filtered to a single child_type, deduped on child+parent.

    Order is load-bearing: ``unique`` runs *before* ``filter`` so duplicate
    ``(child_reference, parent_facility_reference)`` pairs that differ only in
    ``child_type`` (e.g. when ``facility_reference == loan_reference``) are
    absorbed by the dedup; reversing to ``filter → unique`` would silently
    diverge on dirty inputs.

    Assumes ``facility_mappings`` is sealed at the loader edge so that
    ``child_type`` always exists. A null ``child_type`` value (legacy inputs
    with no discriminator) fills to "" via ``fill_null`` and never matches a
    real type — yielding an empty filtered frame, which is the correct "no
    children of this type" semantic.
    """
    return facility_mappings.unique(subset=["child_reference", "parent_facility_reference"]).filter(
        pl.col("child_type").fill_null("").str.to_lowercase() == child_type
    )


def _enrich_counterparties_with_hierarchy(
    counterparties: pl.LazyFrame,
    org_mappings: pl.LazyFrame,
    ratings: pl.LazyFrame,
    ultimate_parents: pl.LazyFrame,
    rating_inheritance: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Enrich counterparties with hierarchy and rating information.

    Adds columns:
    - counterparty_has_parent: bool
    - parent_counterparty_reference: str | null
    - ultimate_parent_reference: str | null
    - counterparty_hierarchy_depth: int
    - cqs, pd, internal_pd, external_cqs, internal_model_id: from ratings
    """
    # Join with org_mappings to get parent
    enriched = counterparties.join(
        org_mappings.select(
            [
                pl.col("child_counterparty_reference"),
                pl.col("parent_counterparty_reference"),
            ]
        ),
        left_on="counterparty_reference",
        right_on="child_counterparty_reference",
        how="left",
    )

    # Join with ultimate parents and rating inheritance in sequence,
    # then derive flags in a single with_columns batch.
    enriched = (
        enriched.join(
            ultimate_parents.select(
                [
                    pl.col("counterparty_reference").alias("_up_cp"),
                    pl.col("ultimate_parent_reference"),
                    pl.col("hierarchy_depth").alias("counterparty_hierarchy_depth"),
                ]
            ),
            left_on="counterparty_reference",
            right_on="_up_cp",
            how="left",
        )
        .join(
            rating_inheritance.select(
                [
                    pl.col("counterparty_reference").alias("_ri_cp"),
                    pl.col("cqs"),
                    pl.col("pd"),
                    pl.col("internal_pd"),
                    pl.col("external_cqs"),
                    pl.col("external_rating_is_issue_specific"),
                    pl.col("internal_model_id"),
                ]
            ),
            left_on="counterparty_reference",
            right_on="_ri_cp",
            how="left",
        )
        .with_columns(
            [
                pl.col("parent_counterparty_reference")
                .is_not_null()
                .alias("counterparty_has_parent"),
                pl.col("counterparty_hierarchy_depth").fill_null(0),
            ]
        )
    )

    return enriched


def _dedup_org_mappings(
    org_mappings: pl.LazyFrame,
) -> tuple[pl.LazyFrame, list[CalculationError]]:
    """Deduplicate ``org_mappings`` on ``child_counterparty_reference``.

    Retains the first row (by input order) for each duplicated child and emits
    one ``ERROR_DUPLICATE_KEY`` WARNING per affected child so operators can
    trace back to the offending input rows. Materialises the (typically small)
    mapping table once because we need to detect duplicates and rebuild a
    deterministic single-row-per-child frame; the result is returned as a
    LazyFrame for downstream joins.
    """
    collected = org_mappings.collect()
    if collected.height == 0:
        return collected.lazy(), []

    # Tag each row with its position so first-row-wins is deterministic.
    indexed = collected.with_row_index("_om_idx")
    dup_children = (
        indexed.group_by("child_counterparty_reference")
        .agg(pl.len().alias("_om_count"))
        .filter(pl.col("_om_count") > 1)
        .get_column("child_counterparty_reference")
        .to_list()
    )

    if not dup_children:
        return collected.lazy(), []

    deduped = (
        indexed.sort("_om_idx")
        .unique(subset=["child_counterparty_reference"], keep="first", maintain_order=True)
        .drop("_om_idx")
    )

    errors: list[CalculationError] = [
        CalculationError(
            code=ERROR_DUPLICATE_KEY,
            message=(
                f"Duplicate child_counterparty_reference '{child}' in "
                f"org_mappings; retaining first row (deterministic by input "
                f"order) and discarding remaining rows."
            ),
            severity=ErrorSeverity.WARNING,
            category=ErrorCategory.DATA_QUALITY,
            counterparty_reference=child,
            field_name="child_counterparty_reference",
            actual_value=child,
        )
        for child in dup_children
    ]
    return deduped.lazy(), errors


def _extract_hierarchy_depth_errors(
    ultimate_parents: pl.LazyFrame,
) -> list[CalculationError]:
    """Synthesise HIE003 WARNINGs from the ``truncated`` column.

    Materialises the (small) lookup frame, picks the rows whose chain was cut
    off by the depth guard, and emits one ``ERROR_HIERARCHY_DEPTH`` per row.
    Chains that terminate naturally (or hit the cycle break) are flagged
    ``truncated == False`` upstream and produce no error here, preserving the
    invariant that depth ``<= max_depth`` chains never warn.
    """
    truncated_rows = (
        ultimate_parents.filter(pl.col("truncated"))
        .select(["counterparty_reference", "ultimate_parent_reference", "hierarchy_depth"])
        .collect()
    )
    errors: list[CalculationError] = []
    for row in truncated_rows.iter_rows(named=True):
        entity = row["counterparty_reference"]
        deepest = row["ultimate_parent_reference"]
        max_depth = row["hierarchy_depth"]
        errors.append(
            CalculationError(
                code=ERROR_HIERARCHY_DEPTH,
                message=(
                    f"Counterparty hierarchy chain for '{entity}' exceeds "
                    f"max_depth={max_depth}; resolved ultimate_parent_reference "
                    f"truncated to '{deepest}'. Check org_mappings for chains "
                    f"deeper than max_depth levels."
                ),
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.HIERARCHY,
                counterparty_reference=entity,
                actual_value=deepest,
            )
        )
    return errors


def _resolve_graph_eager(
    edges: pl.DataFrame,
    child_col: str,
    parent_col: str,
    max_depth: int = 10,
) -> pl.DataFrame:
    """
    Resolve a parent-child graph eagerly via dict traversal.

    Builds a child→parent dict from collected edge data, then walks each chain
    to find the ultimate root. Adapts to actual hierarchy depth rather than
    iterating a fixed number of times.

    Args:
        edges: Collected DataFrame with child and parent columns
        child_col: Name of the child column in edges
        parent_col: Name of the parent column in edges
        max_depth: Safety limit to prevent infinite loops on bad data

    Returns:
        DataFrame with columns:
        - entity (Utf8): The traversed child
        - root (Utf8): The deepest reachable parent (true root if reached,
          otherwise the parent at depth ``max_depth`` when truncated)
        - depth (Int32): Number of levels traversed
        - truncated (Boolean): True iff the traversal exited because of the
          ``max_depth`` guard rather than reaching the natural root. Callers
          use this column to synthesise HIE003 WARNINGs.
    """
    child_series = edges[child_col].to_list()
    parent_series = edges[parent_col].to_list()

    parent_of: dict[str, str] = {}
    for child, parent in zip(child_series, parent_series, strict=True):
        if child is not None and parent is not None:
            parent_of[child] = parent

    entities: list[str] = []
    roots: list[str] = []
    depths: list[int] = []
    truncated: list[bool] = []

    for entity in parent_of:
        current = entity
        depth = 0
        visited: set[str] = {current}
        while current in parent_of and depth < max_depth:
            next_parent = parent_of[current]
            if next_parent in visited:
                break  # Cycle detected
            visited.add(next_parent)
            current = next_parent
            depth += 1
        # Truncation: depth limit reached AND chain still has further parents.
        # Natural termination (current not in parent_of) and cycle-detected
        # break both leave the loop without tripping this branch, so neither
        # produces a spurious HIE003.
        was_truncated = depth == max_depth and current in parent_of
        entities.append(entity)
        roots.append(current)
        depths.append(depth)
        truncated.append(was_truncated)

    return pl.DataFrame(
        {
            "entity": entities,
            "root": roots,
            "depth": depths,
            "truncated": truncated,
        },
        schema={
            "entity": pl.String,
            "root": pl.String,
            "depth": pl.Int32,
            "truncated": pl.Boolean,
        },
    )


def _resolve_ancestors_eager(
    edges: pl.DataFrame,
    child_col: str,
    parent_col: str,
    max_depth: int = 10,
) -> pl.DataFrame:
    """Resolve a parent-child graph to its full ancestor closure.

    Builds a child→parent dict from collected edge data, then for each child
    walks the chain towards the root, emitting one ``(descendant, ancestor)``
    row for every node on the path INCLUDING the child itself (self-edge). Used
    to cascade facility-level collateral over the whole facility subtree: a
    pledge at any ancestor facility reaches every descendant exposure.

    Args:
        edges: Collected DataFrame with child and parent columns.
        child_col: Name of the child column in ``edges``.
        parent_col: Name of the parent column in ``edges``.
        max_depth: Safety limit to prevent infinite loops on bad data; the walk
            also breaks on a revisited node (cycle guard).

    Returns:
        DataFrame with columns:
        - descendant (Utf8): the child facility.
        - ancestor (Utf8): the child itself or one of its ancestor facilities.
    """
    child_series = edges[child_col].to_list()
    parent_series = edges[parent_col].to_list()

    parent_of: dict[str, str] = {}
    for child, parent in zip(child_series, parent_series, strict=True):
        if child is not None and parent is not None:
            parent_of[child] = parent

    descendants: list[str] = []
    ancestors: list[str] = []
    for entity in parent_of:
        # Self-edge: a pledge at the facility itself must still reach it.
        descendants.append(entity)
        ancestors.append(entity)
        current = entity
        depth = 0
        visited: set[str] = {current}
        while current in parent_of and depth < max_depth:
            next_parent = parent_of[current]
            if next_parent in visited:
                break  # Cycle detected
            visited.add(next_parent)
            descendants.append(entity)
            ancestors.append(next_parent)
            current = next_parent
            depth += 1

    return pl.DataFrame(
        {"descendant": descendants, "ancestor": ancestors},
        schema={"descendant": pl.String, "ancestor": pl.String},
    )


def _resolve_facility_forest(raw: pl.DataFrame) -> FacilityGraph:
    """Turn collected facility edges into a forest, naming every repair.

    Deterministic by construction: the edges are read in sorted order, a
    sub-facility keeps its lowest-referenced parent, and cycles are found by
    walking the resulting one-parent graph from each node in sorted order. Every
    member of a cycle loses its own parent edge (becomes a root); an edge INTO a
    cycle member from outside the cycle is kept.
    """
    parents: dict[str, list[str]] = {}
    for child, parent in sorted(
        (c, p)
        for c, p in zip(
            raw["child_facility_reference"].to_list(),
            raw["parent_facility_reference"].to_list(),
            strict=True,
        )
        if c is not None and p is not None
    ):
        parents.setdefault(child, []).append(parent)

    errors: list[CalculationError] = [
        facility_multi_parent_warning(
            child_reference=child,
            child_type="facility",
            parents=listed,
            kept=listed[0],
            ignored=listed[1:],
        )
        for child, listed in parents.items()
        if len(listed) > 1
    ]
    parent_of = {child: listed[0] for child, listed in parents.items()}

    cycles = _find_cycles(parent_of)
    errors.extend(facility_mapping_cycle_warning(members=members) for members in cycles)
    on_cycle = {member for members in cycles for member in members}

    kept = sorted((c, p) for c, p in parent_of.items() if c not in on_cycle)
    edges = pl.DataFrame(
        {
            "child_facility_reference": [c for c, _ in kept],
            "parent_facility_reference": [p for _, p in kept],
        },
        schema={"child_facility_reference": pl.String, "parent_facility_reference": pl.String},
    )
    return FacilityGraph(edges=edges, errors=tuple(errors))


def _find_cycles(parent_of: dict[str, str]) -> list[tuple[str, ...]]:
    """Every cycle of a one-parent graph, each as its sorted members.

    A walk from each node (in sorted order) follows parents until it reaches a
    root, a node an earlier walk finished, or a node already on THIS walk — the
    last is a cycle, made of the walk from that node on. A self-loop is a cycle
    of one.
    """
    finished: set[str] = set()
    cycles: list[tuple[str, ...]] = []
    for start in sorted(parent_of):
        path: list[str] = []
        on_path: set[str] = set()
        node = start
        while node in parent_of and node not in finished and node not in on_path:
            path.append(node)
            on_path.add(node)
            node = parent_of[node]
        if node in on_path:
            cycles.append(tuple(sorted(path[path.index(node) :])))
        finished.update(path)
    return cycles
