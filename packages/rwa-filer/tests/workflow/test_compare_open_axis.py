"""
Comparing returns that report by country: an open axis, one sheet per member.

Pipeline position:
    two geographical returns (``compare_builders.geographical_return``)
        ->  compare.compare_returns  ->  explain.explain_differences  ->  findings

Key responsibilities:
- The same difference in several countries is ONE finding: sibling sheets
  whose differences agree within the accuracy the files state are linked, and
  sheets whose differences do not agree are not.
- A Bank rule is checked once per country, so it links the differing cells of
  that country only, and a figure moved between two rows is a move in that
  country.
- A cell on an open axis has the same address in the comparison and in the
  rule engine: the member's local name. A rule that breaks in one country
  names that country's cell.

Every other comparison test uses a table with fixed sheets, where none of this
runs: with the country links switched off, those tests all still pass.

References:
- rwa_filer.workflow.explain — how differences are linked into findings
- Bank of England Banking Taxonomy v4.1.1 (PRA001) — OF 09.01 and boe_b0730
"""

from __future__ import annotations

from compare_builders import (
    ALL_COUNTRIES,
    CORPORATE,
    COUNTRIES,
    GEO_COLUMNS,
    GEO_TABLE,
    GEO_TOTAL,
    INSTITUTIONS,
    RETAIL,
    TIED_MOVE,
    geographical_return,
)
from rwa_filer.boe.engine import trace_rules
from rwa_filer.readers import SourceReading
from rwa_filer.release import resolve_release
from rwa_filer.validate.structure import check_structure
from rwa_filer.workflow.compare import ReturnComparison, compare_returns
from rwa_filer.workflow.explain import (
    KIND_CALCULATION,
    KIND_DOES_NOT_ADD_UP,
    POINTS_AT_INPUTS,
    SIDE_CANDIDATE,
    STANDING_BREAKS,
    STANDING_HOLDS,
    Cell,
)

RWEA = "0090"
ORIGINAL_EXPOSURE = "0010"


def compare(baseline: dict[str, object], candidate: dict[str, object]) -> ReturnComparison:
    """Compare two geographical returns built from ``geographical_return`` keyword arguments."""
    readings = []
    for differences in (baseline, candidate):
        ret = geographical_return(**differences)
        pack = resolve_release(ret.header.module).pack
        assert check_structure(ret, pack) == [], "the fixture must be a valid PRA001 return"
        readings.append(SourceReading(ret=ret))
    return compare_returns(*readings)


def cell(country: str, row: str, column: str) -> Cell:
    return (GEO_TABLE, None, country, row, column)


def sheets(comparison: ReturnComparison) -> list[set[str | None]]:
    """The open keys each finding's cells are on, in the order the findings are listed."""
    return [{found[2] for found in item.cells} for item in comparison.findings]


# ---------------------------------------------------------------------------
# The fixture
# ---------------------------------------------------------------------------


def test_two_identical_geographical_returns_are_equivalent() -> None:
    comparison = compare({}, {})

    assert comparison.is_equivalent
    assert comparison.shared_breaks == (), "the return as built must break no rule"


def test_the_rule_engine_addresses_a_country_cell_by_the_key_the_return_gives_it() -> None:
    """Both sides of every link below: a differing cell and a cell a rule read are one address."""
    # Arrange
    ret = geographical_return()
    release = resolve_release(ret.header.module)
    assert release.rulebook is not None

    # Act
    trace = trace_rules(ret, release.pack, release.rulebook.enforced(ret.header.module))

    # Assert
    read = {
        address.open_key
        for evaluation in trace.evaluations
        for address in (*evaluation.left, *evaluation.right)
        if address.table == GEO_TABLE
    }
    assert read == {*COUNTRIES, ALL_COUNTRIES}


# ---------------------------------------------------------------------------
# Sibling sheets
# ---------------------------------------------------------------------------


def test_the_same_restatement_in_every_country_is_one_finding() -> None:
    """Corporate RWEA is 5,000 higher in each country: one cause, so one finding."""
    restated = {(country, CORPORATE, RWEA): 5_000.0 for country in COUNTRIES}

    comparison = compare({}, {"restated": restated})

    together, all_countries = comparison.findings
    assert (together.kind, together.points_at) == (KIND_CALCULATION, POINTS_AT_INPUTS)
    assert set(together.cells) == {
        cell(country, row, RWEA) for country in COUNTRIES for row in (CORPORATE, GEO_TOTAL)
    }
    assert sheets(comparison)[1] == {ALL_COUNTRIES}, (
        "the all-countries sheet moves by three times as much: a finding of its own"
    )
    assert all_countries.kind == KIND_CALCULATION


def test_countries_restated_by_different_amounts_are_separate_findings() -> None:
    restated = {("GB", CORPORATE, RWEA): 5_000.0, ("FR", CORPORATE, RWEA): 9_000.0}

    comparison = compare({}, {"restated": restated})

    assert sorted(sheets(comparison), key=sorted) == [{"FR"}, {"GB"}, {ALL_COUNTRIES}]


def test_restatements_within_the_accuracy_both_files_state_are_the_same_difference() -> None:
    """Thousands on both sides: each difference is good to 1,000, so two are alike within 2,000."""
    restated = {
        ("DE", CORPORATE, RWEA): 5_000.0,
        ("FR", CORPORATE, RWEA): 7_000.0,
        ("GB", CORPORATE, RWEA): 9_001.0,
    }

    comparison = compare({"decimals": -3}, {"decimals": -3, "restated": restated})

    assert sorted(sheets(comparison), key=sorted) == [{"DE", "FR"}, {"GB"}, {ALL_COUNTRIES}]


# ---------------------------------------------------------------------------
# Rules, country by country
# ---------------------------------------------------------------------------


def test_a_figure_moved_between_classes_in_one_country_is_a_move_in_that_country() -> None:
    """France reports 20,000 as corporate where the baseline has it as retail."""
    restated = {
        ("FR", CORPORATE, ORIGINAL_EXPOSURE): 20_000.0,
        ("FR", RETAIL, ORIGINAL_EXPOSURE): -20_000.0,
    }

    comparison = compare({}, {"restated": restated})

    (finding,) = comparison.findings
    assert set(finding.cells) == {
        cell(key, row, ORIGINAL_EXPOSURE)
        for key in ("FR", ALL_COUNTRIES)
        for row in (CORPORATE, RETAIL)
    }
    assert {
        (move.open_key, move.baseline_row, move.candidate_row, move.columns, move.amount)
        for move in finding.moves
    } == {
        ("FR", RETAIL, CORPORATE, (ORIGINAL_EXPOSURE,), 20_000.0),
        (ALL_COUNTRIES, RETAIL, CORPORATE, (ORIGINAL_EXPOSURE,), 20_000.0),
    }


def test_a_rule_links_a_class_to_the_total_of_its_own_country() -> None:
    """Total = sum of classes is checked country by country, so that is how it links.

    No two sheets move by the same amount here, so nothing but the rule links anything.
    """
    restated = {("FR", CORPORATE, RWEA): 9_000.0, ("GB", CORPORATE, RWEA): 5_000.0}

    comparison = compare({}, {"restated": restated})

    assert {item.kind for item in comparison.findings} == {KIND_CALCULATION}
    assert {frozenset(item.cells) for item in comparison.findings} == {
        frozenset({cell(key, CORPORATE, RWEA), cell(key, GEO_TOTAL, RWEA)})
        for key in ("FR", "GB", ALL_COUNTRIES)
    }


def test_of_two_rows_up_by_the_same_amount_a_move_names_the_first_in_cell_order() -> None:
    """Institutions and corporates both rise by what retail falls by: a tie, decided by order.

    Which of the two a move names used to follow the order a set held them in,
    so it changed with Python's hash seed. Twelve ties here, one per sheet and
    column: by chance alone all twelve name the first about once in 4,000 runs.
    """
    comparison = compare({}, {"restated": TIED_MOVE})

    moves = [move for item in comparison.findings for move in item.moves]
    assert {(move.open_key, column) for move in moves for column in move.columns} == {
        (key, column) for key in (*COUNTRIES, ALL_COUNTRIES) for column in GEO_COLUMNS
    }, "a move must be found on every sheet and column, or there is no tie to decide"
    assert {(move.baseline_row, move.candidate_row) for move in moves} == {(RETAIL, INSTITUTIONS)}


# ---------------------------------------------------------------------------
# One address for a cell
# ---------------------------------------------------------------------------


def test_a_country_total_that_does_not_add_up_names_that_countrys_cell() -> None:
    """France's RWEA total is 7,000 more than its classes: boe_b0730 breaks there."""
    comparison = compare({}, {"overlaid": {("FR", RWEA): 7_000.0}})

    (finding,) = (item for item in comparison.findings if item.kind == KIND_DOES_NOT_ADD_UP)
    totals = (cell("FR", GEO_TOTAL, RWEA), cell(ALL_COUNTRIES, GEO_TOTAL, RWEA))
    assert (finding.points_at, finding.gap, finding.cells) == (SIDE_CANDIDATE, 7_000, totals)
    assert [
        (part.cell, part.delta, part.explained, part.unexplained) for part in finding.breakdown
    ] == [(total, 7_000, 0, 7_000) for total in totals]
    assert [(rule.rule_id, rule.baseline, rule.candidate) for rule in finding.rules] == [
        ("boe_b0730", STANDING_HOLDS, STANDING_BREAKS)
    ]
