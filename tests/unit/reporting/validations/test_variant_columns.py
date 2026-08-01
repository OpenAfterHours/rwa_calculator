"""
Unit tests for DPM variant column scoping.

Several publisher table codes bind to ONE of our frames — our single C 09.01
carries the union of ``C 09.01.a`` and ``C 09.01.b``, which the DPM splits by
column. Without a column set on the binding, a rule scoped ``columns: (All)`` on
one variant iterates the other variant's columns and reports breaks against
cells it does not govern. That is what made ``v6051_m`` fail by exactly
1,000,000 while ``v6050_m`` — the same formula on ``.a``, differing only by
including r0100 — passed on all its coordinates.

The sets are DERIVED from the rule extract rather than hand-written, and the
derivation is self-limiting: it scopes a group only when the variants' column
sets are non-empty and pairwise disjoint, the signature of a genuine column
partition. These tests pin both halves of that — the scoping where it applies,
and the REFUSAL where it does not, because the refusal is the half a future
maintainer is likely to "complete" by hand.

References:
- src/rwa_calc/reporting/validations/scope.py — ``derive_variant_columns``
"""

from __future__ import annotations

import itertools

import pytest

from rwa_calc.reporting.validations.scope import (
    ABSENT_CELL,
    SINGLE_SHEET,
    derive_variant_columns,
)

from ._builders import build_frame, build_index

# One C 09.01 frame carrying the UNION of both variants' columns, exactly as our
# generator emits it: c0010 belongs to `.a`, c0020/c0040 to `.b`.
_UNION_FRAME = {"0010": {"0010": 1_000_000.0, "0020": 25.0, "0040": 50.0}}

# The two frameworks' shared-frame groups that the derivation scopes today.
_SCOPED_PAIRS = [
    pytest.param("CRR", "C 09.01.a", "C 09.01.b", id="crr-c09.01"),
    pytest.param("CRR", "C 08.01.a", "C 08.01.b", id="crr-c08.01"),
    pytest.param("BASEL_3_1", "OF08.01.01.01", "OF08.01.01.02", id="b31-of08.01"),
]


@pytest.mark.parametrize(("framework", "first", "second"), _SCOPED_PAIRS)
def test_column_partitioned_variants_are_scoped_disjointly(
    framework: str, first: str, second: str
) -> None:
    """A genuine column partition gives each variant its own non-overlapping set."""
    # Arrange / Act
    scoped = derive_variant_columns(framework)

    # Assert
    assert scoped[first] and scoped[second]
    assert not scoped[first] & scoped[second]


@pytest.mark.parametrize(
    ("framework", "family"),
    [
        pytest.param("CRR", "C 07.00.", id="crr-c07.00"),
        pytest.param("BASEL_3_1", "OF07.00.01.", id="b31-of07.00"),
    ],
)
def test_row_partitioned_variants_are_left_unscoped(framework: str, family: str) -> None:
    """The C 07.00 family must NOT be column-scoped — it partitions by ROW.

    ``.c`` / ``.d`` are the memorandum rows (0290-0320) over the SAME column
    space as ``.a``, so a column set is the wrong model for them. Forcing one
    would silently suppress real C 07.00 findings, which is the worst outcome
    for a control whose job is to surface them. This test exists so nobody
    "completes" the table by hand later.
    """
    # Arrange / Act
    scoped = derive_variant_columns(framework)

    # Assert
    assert not [table for table in scoped if table.startswith(family)]


def test_every_scoped_group_is_pairwise_disjoint() -> None:
    """The invariant the derivation guarantees, over whatever it scopes today.

    Asserted generically rather than against a fixed list, so a future taxonomy
    refresh that brings a new variant into scope is held to the same rule.
    """
    # Arrange / Act
    for framework in ("CRR", "BASEL_3_1"):
        scoped = derive_variant_columns(framework)

        # Assert — no column is claimed by two table codes bound to one frame
        for first, second in itertools.combinations(sorted(scoped), 2):
            if first.rsplit(".", 1)[0] != second.rsplit(".", 1)[0]:
                continue
            assert not scoped[first] & scoped[second], f"{first} and {second} share columns"


def test_column_refs_returns_only_the_addressed_variants_columns() -> None:
    """``columns: (All)`` on ``.b`` must iterate ``.b``'s columns, not the union.

    This is the ``v6051_m`` mechanism: the frame carries all three columns, but
    the two table codes see different slices of it.
    """
    # Arrange
    index = build_index(c09_01={"TOTAL": build_frame(_UNION_FRAME)})

    # Act
    on_a = index.column_refs("C 09.01.a", "TOTAL")
    on_b = index.column_refs("C 09.01.b", "TOTAL")

    # Assert
    assert on_a == ("0010",)
    assert on_b == ("0020", "0040")


def test_a_cell_outside_the_variant_reads_as_absent_not_as_its_value() -> None:
    """Reaching a sibling variant's column through the wrong code yields ABSENT.

    Absent, not the value: the cell exists on the frame but this table code does
    not govern it, so a rule addressing it is skipped rather than judged against
    a figure belonging to a different DPM table.
    """
    # Arrange
    index = build_index(c09_01={"TOTAL": build_frame(_UNION_FRAME)})

    # Act
    own = index.cell("C 09.01.a", "TOTAL", "0010", "0010")
    foreign = index.cell("C 09.01.b", "TOTAL", "0010", "0010")

    # Assert
    assert own.value == 1_000_000.0
    assert foreign == ABSENT_CELL


def test_a_sole_binding_keeps_the_whole_frame() -> None:
    """A code that is the only binding for its member is never column-restricted.

    C 02.00 is not a variant of anything, so scoping it would add risk with no
    benefit — the frame IS that table.
    """
    # Arrange
    index = build_index(c_02_00=build_frame({"0010": {"0010": 5.0, "0020": 7.0}}))

    # Act
    refs = index.column_refs("C 02.00", SINGLE_SHEET)

    # Assert
    assert refs == ("0010", "0020")
