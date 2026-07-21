"""
Unit tests: reporting-hierarchy tree builder (ui.views.hierarchy).

Pins the pure registry-rows -> tree transform behind the ``/hierarchy`` page:
parent links nest into a single-root forest, apex/parent/leaf nodes advertise the
right scope-headship, display names fall back to the reference, and every kind of
malformed row (unknown / self / cyclic parent, blank / duplicate reference) lands
loudly in the ``unattached`` list instead of vanishing or overflowing the stack.
"""

from __future__ import annotations

from rwa_calc.ui.views import hierarchy


def _row(
    reference: str,
    *,
    name: str | None = None,
    lei: str | None = None,
    parent: str | None = None,
    institution_type: str | None = None,
    core_uk_group: object = False,
) -> dict:
    """One six-column registry row as ``read_reporting_entities`` returns it."""
    return {
        "entity_reference": reference,
        "entity_name": name,
        "lei": lei,
        "parent_entity_reference": parent,
        "institution_type": institution_type,
        "core_uk_group": core_uk_group,
    }


# =============================================================================
# Tree shape (parent links -> nested structure)
# =============================================================================


def test_parent_links_nest_children_under_apex() -> None:
    # Arrange — an apex with two children (scrambled input order).
    rows = [_row("BANK_B", parent="GRP"), _row("GRP"), _row("BANK_A", parent="GRP")]

    # Act
    view = hierarchy.build_hierarchy(rows)

    # Assert — one rooted apex, children nested and sorted deterministically.
    assert [r.reference for r in view.roots] == ["GRP"]
    assert [c.reference for c in view.roots[0].children] == ["BANK_A", "BANK_B"]
    assert not view.unattached


def test_deep_chain_nests_to_the_leaf() -> None:
    # Arrange — GRP -> SUB -> LEAF.
    rows = [_row("GRP"), _row("SUB", parent="GRP"), _row("LEAF", parent="SUB")]

    # Act
    view = hierarchy.build_hierarchy(rows)

    # Assert
    leaf = view.roots[0].children[0].children[0]
    assert leaf.reference == "LEAF"
    assert view.entity_count == 3


# =============================================================================
# Apex detection + scope-headship labels
# =============================================================================


def test_apex_heads_consolidated_and_individual() -> None:
    # Arrange
    rows = [_row("GRP"), _row("BANK_A", parent="GRP")]

    # Act
    grp = hierarchy.build_hierarchy(rows).roots[0]

    # Assert — the apex heads a consolidated and an individual submission.
    assert grp.is_apex
    assert [s.basis for s in grp.scopes] == ["consolidated", "individual"]


def test_non_apex_parent_heads_sub_consolidated() -> None:
    # Arrange — a mid-tree parent (has a parent AND children).
    rows = [_row("GRP"), _row("SUB", parent="GRP"), _row("LEAF", parent="SUB")]

    # Act
    sub = hierarchy.build_hierarchy(rows).roots[0].children[0]

    # Assert
    assert not sub.is_apex
    assert [s.basis for s in sub.scopes] == ["sub_consolidated", "individual"]


def test_leaf_heads_individual_only() -> None:
    # Arrange
    rows = [_row("GRP"), _row("BANK_A", parent="GRP")]

    # Act
    leaf = hierarchy.build_hierarchy(rows).roots[0].children[0]

    # Assert — a childless node heads only its own individual submission.
    assert [s.basis for s in leaf.scopes] == ["individual"]


# =============================================================================
# Field mapping (name fallback, core_uk_group coercion)
# =============================================================================


def test_name_falls_back_to_reference_when_absent() -> None:
    assert hierarchy.build_hierarchy([_row("GRP")]).roots[0].name == "GRP"
    assert hierarchy.build_hierarchy([_row("GRP", name="Group PLC")]).roots[0].name == "Group PLC"


def test_core_uk_group_coerced_from_bool_and_string() -> None:
    # parquet yields Python bools; a CSV registry can yield "true"/"false" strings.
    assert hierarchy.build_hierarchy([_row("A", core_uk_group=True)]).roots[0].core_uk_group is True
    assert (
        hierarchy.build_hierarchy([_row("B", core_uk_group="true")]).roots[0].core_uk_group is True
    )
    assert (
        hierarchy.build_hierarchy([_row("C", core_uk_group=None)]).roots[0].core_uk_group is False
    )


# =============================================================================
# Malformed registries -> unattached (never crash)
# =============================================================================


def test_unknown_parent_lands_in_unattached() -> None:
    # Arrange
    rows = [_row("GRP"), _row("STRAY", parent="MISSING")]

    # Act
    view = hierarchy.build_hierarchy(rows)

    # Assert — the apex forest is intact; the stray is surfaced with a reason.
    assert [r.reference for r in view.roots] == ["GRP"]
    assert len(view.unattached) == 1
    assert view.unattached[0].node.reference == "STRAY"
    assert "unknown parent" in view.unattached[0].reason


def test_orphan_top_keeps_its_valid_children() -> None:
    # Arrange — an orphan whose own child links validly to it.
    rows = [_row("STRAY", parent="MISSING"), _row("CHILD", parent="STRAY")]

    # Act
    view = hierarchy.build_hierarchy(rows)

    # Assert — the orphan renders as a subtree, not two loose rows.
    assert not view.roots
    assert len(view.unattached) == 1
    assert [c.reference for c in view.unattached[0].node.children] == ["CHILD"]


def test_self_parent_is_unattached() -> None:
    # Act
    view = hierarchy.build_hierarchy([_row("LOOP", parent="LOOP")])

    # Assert
    assert not view.roots
    assert view.unattached[0].reason == "entity is its own parent"


def test_parent_cycle_does_not_recurse_forever() -> None:
    # Arrange — a two-node cycle: A's parent is B, B's parent is A.
    rows = [_row("A", parent="B"), _row("B", parent="A")]

    # Act — must terminate; neither node is a true apex.
    view = hierarchy.build_hierarchy(rows)

    # Assert — the cycle surfaces once (as a reachable subtree), both nodes counted.
    assert not view.roots
    assert {item.node.reference for item in view.unattached} == {"A"}
    assert any(item.reason == "parent cycle" for item in view.unattached)
    assert view.entity_count == 2


def test_duplicate_reference_is_unattached() -> None:
    # Arrange — the same reference twice; the first wins the tree slot.
    rows = [_row("GRP"), _row("GRP", name="Duplicate")]

    # Act
    view = hierarchy.build_hierarchy(rows)

    # Assert
    assert [r.reference for r in view.roots] == ["GRP"]
    assert "duplicate entity_reference" in [item.reason for item in view.unattached]


def test_blank_reference_is_unattached() -> None:
    # Act
    view = hierarchy.build_hierarchy([_row("", name="Nameless")])

    # Assert
    assert not view.roots
    assert view.unattached[0].reason == "missing entity_reference"
    assert view.unattached[0].node.reference == "(missing reference)"


# =============================================================================
# Empty state
# =============================================================================


def test_empty_registry_is_empty() -> None:
    view = hierarchy.build_hierarchy([])
    assert view.is_empty
    assert view.entity_count == 0


def test_all_unattached_registry_is_not_empty() -> None:
    # A registry with only malformed rows still has content to show (loudly).
    view = hierarchy.build_hierarchy([_row("STRAY", parent="MISSING")])
    assert not view.is_empty
