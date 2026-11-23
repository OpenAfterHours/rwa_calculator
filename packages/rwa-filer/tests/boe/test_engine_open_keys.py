"""
Which member of an open sheet axis a fact's key names — however the key is written.

Pipeline position:
    CanonicalReturn (``open_key``: ``eba_GA:GB``, ``GB``, or nothing)
        ->  boe.engine (each fact placed at a member of its table's open axis)
        ->  the place every rule over the table is evaluated at

What is pinned, on the synthetic pack:
- a key written as the member's QName and one written as its local name are the
  SAME place: results, evaluations and cells are identical;
- on an axis where two members share a local name, the local name is the first
  of them in the axis's order;
- a key that is a member's whole name is that member, before any member it is
  merely the local name of;
- a key the axis does not have — bare, or a known code under an unknown prefix —
  is kept as written, and is still a place.

Why this file exists: the engine used to find a key's member by walking the
axis's member list for every fact (252 members on the Bank's country axis), and
now reads a per-table dictionary. The packaged packs cannot tell a correct
dictionary from one that prefers the last duplicate or the local name over the
whole name — none of the nine packaged open-axis tables has a duplicate local
name or an unprefixed member — so the order of preference is pinned here on an
axis built to have both.

Observed red before it was trusted (2026-11-22, one line of the dictionary
mutated at a time): last duplicate wins; local name over whole name; no local
names at all; an unknown key dropped.

References:
- rwa_filer.model — a source may write an open key by its local name
- docs/plans/rwa-filer-performance-review-2026-11-22.md, item 4
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

import polars as pl
import pytest

from boe_builders import T03, ref, rule
from pack_builders import SAMPLE_COMPILED, SAMPLE_VALID_FROM, build_pack, build_return
from rwa_filer.boe.engine import STATUS_PASS, Accuracy, trace_rules
from rwa_filer.model import DECIMALS_EXACT
from rwa_filer.taxonomy.pack import load_pack, write_pack

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import TaxonomyPack

COLUMNS = ["table", "sheet", "open_key", "row", "column", "value", "text_value", "decimals"]
EXACT = Accuracy(monetary_decimals=DECIMALS_EXACT, percentage_decimals=DECIMALS_EXACT)
#: The place axis a rule iterates T03's countries on.
COUNTRY_AXIS = "open:eba_dim:CEG"

#: Exposure (row 0010) is not negative: evaluated once per member reported.
PER_MEMBER = rule("per-member", f"{ref(T03, '0010', '0010')} >= 0", tables=(T03,))
#: RWEA (0020) at most exposure (0010), per member: two cells at each place.
CAPPED = rule("capped", f"{ref(T03, '0020', '0010')} i<= {ref(T03, '0010', '0010')}", tables=(T03,))

#: An axis no packaged table has: ``GB`` is the local name of two members, and
#: ``FR`` is both a member's whole name and the local name of an earlier one.
AWKWARD_MEMBERS = ("eba_GA:x1", "eba_GA:GB", "alt_GA:GB", "eba_GA:FR", "FR")


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path / "pack")


@pytest.fixture
def awkward(tmp_path: Path) -> TaxonomyPack:
    """The synthetic pack with T03's country axis listing ``AWKWARD_MEMBERS``."""
    compiled = copy.deepcopy(SAMPLE_COMPILED)
    (axis,) = compiled["tables"][T03]["z"]
    axis["members"] = list(AWKWARD_MEMBERS)
    write_pack(compiled, tmp_path / "awkward", valid_from=SAMPLE_VALID_FROM)
    return load_pack(tmp_path / "awkward")


def test_a_member_is_one_place_whether_its_key_is_a_qname_or_a_local_name(
    pack: TaxonomyPack,
) -> None:
    # Arrange - the same figures, each country written one way and then the other.
    figures = [
        ("GB", "0010", 70.0),
        ("GB", "0020", 20.0),
        ("FR", "0010", 30.0),
        ("FR", "0020", 40.0),
    ]
    bare = _return(*((country, row, value) for country, row, value in figures))
    qualified = _return(*((f"eba_GA:{country}", row, value) for country, row, value in figures))

    # Act
    as_bare = trace_rules(bare, pack, [CAPPED, PER_MEMBER], accuracy=EXACT)
    as_qualified = trace_rules(qualified, pack, [CAPPED, PER_MEMBER], accuracy=EXACT)

    # Assert
    assert _members(as_bare.evaluations, "capped") == ["eba_GA:FR", "eba_GA:GB"], (
        "a key written by its local name was not placed at the axis's member"
    )
    assert [(result.satisfied, result.unsatisfied) for result in as_bare.results] == [
        (1, 1),
        (2, 0),
    ]
    assert as_bare == as_qualified


@pytest.mark.parametrize(
    ("written", "member"),
    [
        pytest.param("GB", "eba_GA:GB", id="a-shared-local-name-is-the-first-member-with-it"),
        pytest.param("alt_GA:GB", "alt_GA:GB", id="a-qname-is-its-own-member"),
        pytest.param("FR", "FR", id="a-whole-name-comes-before-a-local-name"),
        pytest.param("eba_GA:FR", "eba_GA:FR", id="the-earlier-member-keeps-its-qname"),
        pytest.param("x1", "eba_GA:x1", id="a-local-name-one-member-has"),
        pytest.param("ZZ", "ZZ", id="an-unknown-code-is-kept-as-written"),
        pytest.param("foo:GB", "foo:GB", id="a-known-code-under-an-unknown-prefix-is-kept"),
    ],
)
def test_a_key_names_the_member_the_axis_lists_it_as(
    awkward: TaxonomyPack, written: str, member: str
) -> None:
    # Arrange
    ret = _return((written, "0010", 5.0))

    # Act
    trace = trace_rules(ret, awkward, [PER_MEMBER], accuracy=EXACT)

    # Assert
    assert [result.status for result in trace.results] == [STATUS_PASS]
    assert _members(trace.evaluations, "per-member") == [member]


def test_keys_that_name_one_member_are_one_cell_and_those_that_do_not_are_apart(
    awkward: TaxonomyPack,
) -> None:
    """Every spelling at once: which share a place, and which figure each place holds."""
    # Arrange - one fact per spelling, each with its own figure.
    spellings = ("GB", "alt_GA:GB", "FR", "eba_GA:FR", "ZZ", "foo:GB", "eba_GA:GB")
    ret = _return(*((key, "0010", float(index)) for index, key in enumerate(spellings, start=1)))

    # Act
    trace = trace_rules(ret, awkward, [PER_MEMBER], accuracy=EXACT)

    # Assert - ``GB`` and ``eba_GA:GB`` are one cell, and the later fact fills it.
    figures = {
        dict(evaluation.place)[COUNTRY_AXIS]: evaluation.left_value
        for evaluation in trace.evaluations
    }
    assert figures == {
        "eba_GA:GB": 7.0,
        "alt_GA:GB": 2.0,
        "FR": 3.0,
        "eba_GA:FR": 4.0,
        "ZZ": 5.0,
        "foo:GB": 6.0,
    }
    assert len(trace.evaluations) == len(figures)


# =============================================================================
# Helpers
# =============================================================================


def _return(*facts: tuple[str, str, float]) -> CanonicalReturn:
    """T03 facts in column 0010, each ``(open key, row, value)``."""
    rows = [(T03, None, key, row, "0010", value, None, None) for key, row, value in facts]
    return build_return(pl.DataFrame(rows, schema=COLUMNS, orient="row"))


def _members(evaluations: tuple[object, ...], rule_id: str) -> list[str]:
    """The country each of the rule's evaluations was made at, in the engine's order."""
    return [
        dict(evaluation.place)[COUNTRY_AXIS]  # type: ignore[attr-defined]
        for evaluation in evaluations
        if evaluation.rule_id == rule_id  # type: ignore[attr-defined]
    ]
