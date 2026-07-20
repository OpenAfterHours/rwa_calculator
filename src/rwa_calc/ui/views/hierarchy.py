"""
Reporting-hierarchy presentation builder (the ``/hierarchy`` page's tree model).

Pipeline position:
    config/reporting_entities rows (list[dict]) -> ui.views.hierarchy
        -> HierarchyView (nested EntityNode tree + unattached list) -> Jinja

Key responsibilities:
- Fold the flat reporting-entities registry (``entity_reference`` +
  optional ``parent_entity_reference`` links) into a tree of ``EntityNode``,
  falling back to the reference when a row carries no display name.
- Label which regulatory scopes each node can *head*: consolidated at the group
  apex, sub-consolidated at any non-apex parent, individual at every node
  (CRR Art. 6 / 11-18).
- Never crash on a malformed registry: rows whose parent is unknown, self-
  referential, part of a cycle, or whose reference is blank/duplicated are
  surfaced in a clearly-marked "unattached" list instead of silently vanishing
  or raising.

This is a pure, presentation-only transform (no IO): the page route reads the
registry via ``api.rest.read_reporting_entities`` and hands the rows here, so
the tree logic is unit-testable without a filesystem.

References:
- CRR Part One Title II (Art. 6, 11-18): individual / sub-consolidated /
  consolidated reporting levels.
- docs/plans/multi-entity-reporting.md: "UI hierarchy view".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


# =============================================================================
# View data model (returned to the template)
# =============================================================================


@dataclass(frozen=True)
class ScopeHeadship:
    """One reporting scope a node can head (a ``ReportingBasis`` value + label)."""

    basis: str  # ReportingBasis value: individual | sub_consolidated | consolidated
    label: str


@dataclass(frozen=True)
class EntityNode:
    """One reporting entity and the subtree it heads.

    ``name`` falls back to ``reference`` when the row carries no display name.
    ``is_apex`` is True only for a true group apex (no parent link); an
    unattached row whose parent is merely unknown is *not* an apex.
    """

    reference: str
    name: str
    lei: str | None
    institution_type: str | None
    core_uk_group: bool
    is_apex: bool
    scopes: tuple[ScopeHeadship, ...]
    children: tuple[EntityNode, ...] = ()


@dataclass(frozen=True)
class UnattachedEntity:
    """A subtree that could not be placed under a group apex, with the reason."""

    node: EntityNode
    reason: str


@dataclass(frozen=True)
class ExpectedColumn:
    """One documented ``config/reporting_entities`` column (for the empty state)."""

    name: str
    required: bool
    notes: str


@dataclass(frozen=True)
class HierarchyView:
    """The reporting-hierarchy tree: rooted forest + any unattached subtrees."""

    roots: tuple[EntityNode, ...]
    unattached: tuple[UnattachedEntity, ...]
    entity_count: int

    @property
    def is_empty(self) -> bool:
        """No entities at all — the registry is absent or has zero rows."""
        return not self.roots and not self.unattached


# The columns the empty-state help panel documents, so an operator with no
# config/reporting_entities file knows what to author. Mirrors the plan's data
# model and REPORTING_ENTITY_SCHEMA (data/schemas.py).
EXPECTED_COLUMNS: tuple[ExpectedColumn, ...] = (
    ExpectedColumn("entity_reference", required=True, notes="Unique key for the entity."),
    ExpectedColumn(
        "entity_name", required=False, notes="Display name (falls back to the reference)."
    ),
    ExpectedColumn("lei", required=False, notes="Legal Entity Identifier."),
    ExpectedColumn(
        "parent_entity_reference",
        required=False,
        notes="Parent link; leave blank for the group apex.",
    ),
    ExpectedColumn("institution_type", required=False, notes="Mirrors the InstitutionType values."),
    ExpectedColumn(
        "core_uk_group",
        required=False,
        notes="Art. 113(6) permission perimeter (default false).",
    ),
)

# The three scope-headship badges, cited once so the tree and its legend stay in
# lock-step with the ReportingBasis vocabulary.
_INDIVIDUAL = ScopeHeadship("individual", "Individual")
_SUB_CONSOLIDATED = ScopeHeadship("sub_consolidated", "Sub-consolidated")
_CONSOLIDATED = ScopeHeadship("consolidated", "Consolidated")

# Legend rows for the template — every scope a node in this view can head.
SCOPE_LEGEND: tuple[ScopeHeadship, ...] = (_CONSOLIDATED, _SUB_CONSOLIDATED, _INDIVIDUAL)


# =============================================================================
# Main entry point
# =============================================================================


def build_hierarchy(rows: Iterable[Mapping[str, object]]) -> HierarchyView:
    """Fold registry rows into a ``HierarchyView`` (single-root tree + strays).

    ``rows`` are the six-column dicts returned by ``read_reporting_entities``
    (``entity_reference`` always present; the rest optional/nullable). A true
    apex (blank ``parent_entity_reference``) heads the main forest; any row that
    cannot be reached from an apex — unknown/self/cyclic parent, or a
    blank/duplicate reference — becomes a clearly-labelled unattached subtree so
    a malformed registry renders loudly rather than crashing.
    """
    parsed = [_Raw.from_row(row) for row in rows]

    # Unique index by reference; blank or duplicate references are invalid rows
    # that cannot anchor a tree edge, so they are held aside for the strays list.
    by_ref: dict[str, _Raw] = {}
    invalid: list[tuple[_Raw, str]] = []
    for raw in parsed:
        if not raw.reference:
            invalid.append((raw, "missing entity_reference"))
        elif raw.reference in by_ref:
            invalid.append((raw, "duplicate entity_reference"))
        else:
            by_ref[raw.reference] = raw

    # Child adjacency is built only from VALID parent links (parent present in
    # the index and not self-referential); every other row is classified as a
    # display root — an apex (no parent) or an unattached top (broken parent).
    children: dict[str, list[str]] = {ref: [] for ref in by_ref}
    apex_refs: list[str] = []
    orphan_tops: list[tuple[str, str]] = []
    for ref, raw in by_ref.items():
        parent = raw.parent
        if parent is None:
            apex_refs.append(ref)
        elif parent == ref:
            orphan_tops.append((ref, "entity is its own parent"))
        elif parent not in by_ref:
            orphan_tops.append((ref, f"unknown parent '{parent}'"))
        else:
            children[parent].append(ref)

    visited: set[str] = set()
    roots = tuple(_build_node(ref, by_ref, children, visited) for ref in sorted(apex_refs))
    unattached: list[UnattachedEntity] = [
        UnattachedEntity(_build_node(ref, by_ref, children, visited), reason)
        for ref, reason in sorted(orphan_tops)
    ]

    # Any valid entity still unvisited is inside a parent cycle (every member
    # points at another member, so none is a display root) — surface each once,
    # with its reachable subtree, rather than dropping the whole cycle.
    for ref in sorted(by_ref):
        if ref not in visited:
            node = _build_node(ref, by_ref, children, visited)
            unattached.append(UnattachedEntity(node, "parent cycle"))

    # Rows too malformed to hold an edge (blank / duplicate reference) render as
    # childless leaves in the strays list.
    for raw, reason in invalid:
        unattached.append(UnattachedEntity(_leaf_node(raw), reason))

    entity_count = sum(_count(node) for node in roots) + sum(
        _count(item.node) for item in unattached
    )
    return HierarchyView(roots=roots, unattached=tuple(unattached), entity_count=entity_count)


# =============================================================================
# Private helpers
# =============================================================================


@dataclass(frozen=True)
class _Raw:
    """A cleaned registry row (blank strings coerced to None)."""

    reference: str
    name: str | None
    lei: str | None
    parent: str | None
    institution_type: str | None
    core_uk_group: bool

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> _Raw:
        return cls(
            reference=_clean_str(row.get("entity_reference")) or "",
            name=_clean_str(row.get("entity_name")),
            lei=_clean_str(row.get("lei")),
            parent=_clean_str(row.get("parent_entity_reference")),
            institution_type=_clean_str(row.get("institution_type")),
            core_uk_group=_as_bool(row.get("core_uk_group")),
        )


def _build_node(
    ref: str,
    by_ref: Mapping[str, _Raw],
    children: Mapping[str, list[str]],
    visited: set[str],
) -> EntityNode:
    """Build one node and its (deterministically ordered) subtree.

    ``visited`` guards against cycles: a child already reached by another path
    is not recursed into again, so a malformed self/mutual parent link renders
    finitely instead of overflowing the stack.
    """
    visited.add(ref)
    raw = by_ref[ref]
    kids = tuple(
        _build_node(child, by_ref, children, visited)
        for child in sorted(children.get(ref, ()))
        if child not in visited
    )
    is_apex = raw.parent is None
    return EntityNode(
        reference=raw.reference,
        name=raw.name or raw.reference,
        lei=raw.lei,
        institution_type=raw.institution_type,
        core_uk_group=raw.core_uk_group,
        is_apex=is_apex,
        scopes=_scopes_for(is_apex=is_apex, has_children=bool(kids)),
        children=kids,
    )


def _leaf_node(raw: _Raw) -> EntityNode:
    """A childless node for a malformed row (blank/duplicate reference).

    A malformed row heads no scope, so its scope list is empty; it is only shown
    in the unattached section to make the registry error visible.
    """
    label = raw.reference or "(missing reference)"
    return EntityNode(
        reference=label,
        name=raw.name or label,
        lei=raw.lei,
        institution_type=raw.institution_type,
        core_uk_group=raw.core_uk_group,
        is_apex=False,
        scopes=(),
        children=(),
    )


def _scopes_for(*, is_apex: bool, has_children: bool) -> tuple[ScopeHeadship, ...]:
    """Scopes a node can head: consolidated apex / sub-consolidated parent / individual.

    Every node can head an individual submission; a parent additionally heads a
    consolidated submission at the group apex, or a sub-consolidated one below.
    """
    scopes: list[ScopeHeadship] = []
    if has_children:
        scopes.append(_CONSOLIDATED if is_apex else _SUB_CONSOLIDATED)
    scopes.append(_INDIVIDUAL)
    return tuple(scopes)


def _count(node: EntityNode) -> int:
    """Total nodes in a subtree (the node plus every descendant)."""
    return 1 + sum(_count(child) for child in node.children)


def _clean_str(value: object) -> str | None:
    """Coerce a cell to a non-empty stripped string, else None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_bool(value: object) -> bool:
    """Coerce a registry cell to bool, tolerating parquet bools and CSV strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "t", "yes", "y", "1"}
    return False
