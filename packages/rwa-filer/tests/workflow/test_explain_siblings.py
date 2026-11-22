"""
Sibling sheets: which countries' differences are one finding, against every pair tested.

Pipeline position:
    {cell: CellDifference} on an open axis  ->  explain.explain_differences  ->  findings
    No rule trace is given, and each group below is one row and one column, so
    nothing but the sibling link can tie two of its cells together.

Key responsibilities:
- State the rule in its plainest form, ``linked_by_every_pair``: two sheets
  are linked when their differences are within the two cells' allowances
  added together, and a finding is whatever such links connect. This is the
  test every pair of sheets was once put to, kept here as the reference.
- Hold ``explain_differences`` to that reference on generated groups — one
  allowance and several, differences on a grid, repeated, a hair either side
  of the allowance, infinite and not-a-number — and on the named cases a
  faster walk is most likely to get wrong.

Why the reference lives in the test: the shipped code no longer tests every
pair (it sorts and walks, see ``explain._Links._link_siblings``), because
every pair costs the square of the number of countries. Only the grouping is
consumed downstream, so the grouping is what is pinned.

References:
- rwa_filer.workflow.explain — "the same difference on an open-axis sheet and
  its total"
- tests/workflow/test_explain_scaling.py — the cost side of the same change
"""

from __future__ import annotations

import math
import random
from itertools import combinations

import pytest

from compare_builders import GEO_TABLE
from rwa_filer.release import resolve_release
from rwa_filer.workflow.explain import (
    CATEGORY_MATERIAL,
    KIND_CALCULATION,
    KIND_UNLINKED,
    Cell,
    CellDifference,
    explain_differences,
)

COLUMN = "0090"
#: A row per group, so two groups share no sheet row and cannot link to each other.
ROWS = ("0010", "0020", "0030", "0040")
#: Allowances as two files' stated accuracies add up to them, and some that are not sums.
ALLOWANCES = (0.0, 0.005, 0.5, 1.0, 500.0, 500.5, 1_000.0, 1e-9)
STYLES = ("grid", "float", "repeated", "tiny", "boundary", "non_finite")
CASES = 1_500
INFINITY, NOT_A_NUMBER = math.inf, math.nan

Group = dict[str, tuple[float, float]]
"""One sibling group: ``{open key: (difference, allowance)}``."""


# =============================================================================
# The reference
# =============================================================================


def linked_by_every_pair(group: Group) -> set[frozenset[str]]:
    """The sets of open keys every-pair testing links, singletons included."""
    component = {key: {key} for key in group}
    for first, second in combinations(group, 2):
        (delta, allowance), (other_delta, other_allowance) = group[first], group[second]
        if abs(delta - other_delta) <= allowance + other_allowance:
            merged = component[first] | component[second]
            for key in merged:
                component[key] = merged
    return {frozenset(keys) for keys in component.values()}


# =============================================================================
# Generated groups
# =============================================================================


@pytest.mark.parametrize("mixed", [False, True], ids=["one_allowance", "mixed_allowances"])
def test_generated_groups_are_linked_exactly_as_testing_every_pair_links_them(mixed: bool) -> None:
    # Arrange
    generator = random.Random(20261122 + mixed)
    cases = [_generated_case(generator, mixed=mixed) for _ in range(CASES)]
    expected = [[linked_by_every_pair(group) for group in case] for case in cases]
    sizes = [len(keys) for case in expected for links in case for keys in links]
    assert sizes.count(1) > CASES and sum(size > 2 for size in sizes) > CASES, (
        "the generated groups must hold both unlinked sheets and links of three or more"
    )

    # Act
    found = [_linked(case) for case in cases]

    # Assert
    wrong = [
        index for index, pair in enumerate(zip(found, expected, strict=True)) if pair[0] != pair[1]
    ]
    assert not wrong, (
        f"{len(wrong)} of {CASES} generated cases are linked differently from testing every "
        f"pair; the first is {cases[wrong[0]]}: {found[wrong[0]]} against {expected[wrong[0]]}"
    )


# =============================================================================
# Named cases
# =============================================================================


@pytest.mark.parametrize(
    ("group", "expected"),
    [
        pytest.param(
            {"AT": (0.0, 0.0), "BE": (1_000.0, 1_000.0), "CY": (2_000.0, 0.0)},
            [{"AT", "BE", "CY"}],
            id="two_exact_figures_bridged_by_one_stated_to_thousands",
        ),
        pytest.param(
            {
                "AT": (0.0, 0.0),
                "BE": (5_000.0, 5_000.0),
                "CY": (2_000.0, 0.0),
                "DE": (9_000.0, 0.0),
            },
            [{"AT", "BE", "CY", "DE"}],
            id="a_wide_allowance_reaches_past_nearer_figures_on_both_sides",
        ),
        pytest.param(
            {"AT": (0.0, 1_000.0), "BE": (2_000.0, 1_000.0), "CY": (4_000.5, 1_000.0)},
            [{"AT", "BE"}, {"CY"}],
            id="a_gap_of_exactly_the_allowances_links_and_a_hair_more_does_not",
        ),
        pytest.param(
            {
                "AT": (7_000.0, 0.0),
                "BE": (7_000.0, 0.0),
                "CY": (7_000.0, 0.0),
                "DE": (7_001.0, 0.0),
            },
            [{"AT", "BE", "CY"}, {"DE"}],
            id="the_same_exact_difference_links_with_no_allowance_at_all",
        ),
        pytest.param(
            {"AT": (0.0, 500.0), "BE": (900.0, 0.0), "CY": (400.0, 0.0), "DE": (901.0, 0.0)},
            [{"AT", "CY"}, {"BE"}, {"DE"}],
            id="figures_between_two_linked_ones_are_not_linked_by_being_between",
        ),
        pytest.param(
            {"AT": (INFINITY, 1.0), "BE": (INFINITY, 1.0), "CY": (5.0, 1.0), "DE": (6.0, 1.0)},
            [{"AT"}, {"BE"}, {"CY", "DE"}],
            id="two_infinite_differences_are_not_within_anything_of_each_other",
        ),
        pytest.param(
            {
                "AT": (NOT_A_NUMBER, 1.0),
                "BE": (5.0, 1.0),
                "CY": (6.0, 1.0),
                "DE": (NOT_A_NUMBER, 1.0),
            },
            [{"AT"}, {"BE", "CY"}, {"DE"}],
            id="a_difference_that_is_not_a_number_links_to_nothing",
        ),
        pytest.param(
            {"AT": (1.0, INFINITY), "BE": (9e9, 0.0), "CY": (-9e9, 0.0)},
            [{"AT", "BE", "CY"}],
            id="an_unbounded_allowance_reaches_everything",
        ),
    ],
)
def test_sibling_sheets_are_linked_when_within_their_allowances_together(
    group: Group, expected: list[set[str]]
) -> None:
    # Arrange - the reference agrees with the case as written, or the case is wrong.
    assert linked_by_every_pair(group) == {frozenset(keys) for keys in expected}

    # Act
    (found,) = _linked([group])

    # Assert
    assert found == {frozenset(keys) for keys in expected}


# =============================================================================
# Helpers
# =============================================================================


def _linked(case: list[Group]) -> list[set[frozenset[str]]]:
    """Per group of ``case``, the sets of open keys ``explain_differences`` puts together."""
    differences: dict[Cell, CellDifference] = {}
    for row, group in zip(ROWS, case, strict=False):
        for key, (delta, allowance) in group.items():
            cell: Cell = (GEO_TABLE, None, key, row, COLUMN)
            differences[cell] = CellDifference(
                cell, CATEGORY_MATERIAL, 0.0, delta, delta, allowance
            )
    findings = explain_differences(differences, [], [], resolve_release("PRA001").pack)
    assert {item.kind for item in findings} <= {KIND_CALCULATION, KIND_UNLINKED}
    placed = [cell for item in findings for cell in item.cells]
    assert sorted(placed, key=str) == sorted(differences, key=str), "every cell is in one finding"
    linked: list[set[frozenset[str]]] = []
    for row, group in zip(ROWS, case, strict=False):
        together = {
            frozenset(cell[2] or "" for cell in item.cells)
            for item in findings
            if item.kind == KIND_CALCULATION and item.cells[0][3] == row
        }
        alone = set(group) - {key for keys in together for key in keys}
        linked.append(together | {frozenset({key}) for key in alone})
    return linked


def _generated_case(generator: random.Random, *, mixed: bool) -> list[Group]:
    """One to three sibling groups of 2 to 40 sheets, in one style of difference."""
    allowances = generator.sample(ALLOWANCES, generator.choice((2, 3, 4)) if mixed else 1)
    style = generator.choice(STYLES)
    size = generator.choice((2, 3, 5, 8, 13, 25, 40))
    case = []
    for _ in range(generator.choice((1, 1, 2, 3))):
        group: Group = {}
        for index in range(size):
            allowance = generator.choice(allowances)
            group[f"K{index:02d}"] = (_difference(generator, style, allowance), allowance)
        case.append(group)
    return case


def _difference(generator: random.Random, style: str, allowance: float) -> float:
    if style == "grid":
        return generator.randint(-8, 8) * 500.0
    if style == "float":
        return generator.uniform(-5_000.0, 5_000.0)
    if style == "repeated":
        return generator.choice((0.0, 1_000.0, 2_000.0, 2_000.5, -1_000.0, 3_000.0))
    if style == "tiny":
        return generator.choice((0.1, 0.2, 0.3, 0.1 + 0.2, 1e-9, 0.6, 0.7, 1.0))
    if style == "boundary":
        base = generator.choice((0.0, 1e6, 123_456.789))
        steps = generator.choice((0, 1, 2, 3))
        return base + steps * 2 * allowance + generator.choice((0.0, 0.0, 1e-9, -1e-9, 5e-13))
    return generator.choice((INFINITY, -INFINITY, NOT_A_NUMBER, 0.0, 1.0, 1e308, -1e308, 1_000.0))
