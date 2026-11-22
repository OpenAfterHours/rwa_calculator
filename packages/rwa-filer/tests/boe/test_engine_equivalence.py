"""
The engine golden — the rule engine says today what it said when the golden was banked.

Pipeline position:
    engine_corpus (five synthetic PRA001 returns, the packaged rules + hand-built ones)
        ->  engine_golden.run_corpus  (evaluate_rules, evaluate_rules with every
            failure, trace_rules, validate_return, trace_return)
        ->  engine_golden.golden_from  ->  this file, against
            tests/boe/data/engine_equivalence.json

Key responsibilities:
- Hold ``boe.engine``, and ``validate_return`` / ``trace_return`` above it, to
  their banked output RULE BY RULE and IN ORDER on a corpus that reaches what the
  package's other returns do not: facts with no member on an open axis, open
  rows, a reported cell a rule turns away, where clauses, nested conditionals.
  The 2026-11 review showed by mutation that every other test and the shared
  behaviour snapshot are blind there: an engine that returned the cells of a
  two-shape reference in reverse order passed 815 tests.
- Keep the corpus adequate (LESSONS C11): each shape is asserted to be IN the
  corpus, and the rules that read it to be evaluated, so a pack or generator
  change cannot leave the golden comparing nothing.
- Pin in plain sight the one order the review found unguarded: the cells a
  summed reference reads where member-less and membered facts sit together.

When the golden test fails
--------------------------
The message names each return, output and rule that moved. ``engine_golden.py
--dump`` writes the text behind every digest, to diff between two checkouts.
The golden is re-banked only for a deliberate, explained change of behaviour,
never to make a speed-up pass: see ``engine_golden``'s docstring.

Observed red before it was trusted (2026-11-22, on the unchanged engine with one
line mutated at a time): the two-shape branch of ``_keys_at`` reversed;
``_addresses`` applying ``_accepts``; ``<`` for ``<=`` on text in ``_compare``;
``<=`` for ``<`` in the failure cap.

References:
- docs/plans/rwa-filer-performance-review-2026-11-22.md — "Guards that land with
  the changes"
- .claude/LESSONS.md C11 (a fixture is a claim), C12 (a green probe needs
  evidence), E1 (never bulk-regenerate a golden)
"""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest

from engine_corpus import (
    COUNTERPARTIES,
    CURRENCY_REPORTED,
    DATES,
    ENTITY_DETAILS,
    FOOTPRINT_RULE,
    GEO_DIMENSION,
    GEO_EXPOSURES,
    GEO_IRB,
    GRADES,
    MANY_GRADES,
    MATRIX,
    STRAY_ONLY_COLUMNS,
    UNRULED,
    build_corpus,
    corpus_release,
    hand_built_rules,
    return_from,
)
from engine_golden import (
    canonical_text,
    differences,
    evaluations_by_rule,
    golden_from,
    load_golden,
    rebank,
    run_corpus,
)
from rwa_filer.boe.deny import DENY_DEACTIVATED, DENY_DOWNGRADED
from rwa_filer.boe.engine import (
    MAX_ADDRESSES,
    MAX_FAILURES,
    REASON_CLOSED_BY_FORMULA,
    REASON_DEACTIVATED_BY_PUBLISHER,
    REASON_UNKNOWN_TABLE,
    REASON_UNSUPPORTED,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    CellAddress,
    evaluate_rules,
    trace_rules,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from engine_golden import Run
    from rwa_filer.boe.engine import Evaluation, RuleResult

#: The "row total = isum(listed rows)" rules of OF 09.01 / OF 09.02, evaluated
#: once per column and country: the references that index places of two shapes.
SUMMED_RULES = ("boe_b0730", "boe_b0731", "boe_b0783", "boe_b0785", "boe_b0786")
#: The place axis a rule iterates the countries on.
COUNTRY_AXIS = f"open:{GEO_DIMENSION}"
EVALUATED = (STATUS_PASS, STATUS_FAIL)
#: The hand-built rules that are NOT evaluated on ``designed``, and why.
NOT_EVALUATED_BY_DESIGN = {
    "corpus_shut_rule": REASON_CLOSED_BY_FORMULA,
    "corpus_unparsable": REASON_UNSUPPORTED,
    "corpus_unknown_table": REASON_UNKNOWN_TABLE,
    "corpus_unlisted_table": REASON_UNSUPPORTED,
    "corpus_unknown_function": REASON_UNSUPPORTED,
    "corpus_wrong_arity": REASON_UNSUPPORTED,
    "corpus_dimension_reference": REASON_UNSUPPORTED,
    "corpus_foreign_filter": REASON_UNSUPPORTED,
    "corpus_dim_of_number": REASON_UNSUPPORTED,
    "corpus_dim_without_dimension": REASON_UNSUPPORTED,
}
#: Deterministic stand-ins for the corpus's cost: it must stay cheap to run.
MAX_CORPUS_FACTS = 12_000
MAX_CORPUS_EVALUATIONS = 20_000
#: Differences quoted in a failure; the count is always given.
QUOTED = 25


@pytest.fixture(scope="module")
def runs() -> Mapping[str, Run]:
    """The engine's five entry points over every corpus return, run once for the file."""
    return run_corpus()


@pytest.fixture(scope="module")
def measured(runs: Mapping[str, Run]) -> dict[str, Any]:
    return golden_from(runs)


@pytest.fixture(scope="module")
def banked() -> dict[str, Any]:
    return load_golden()


# =============================================================================
# The golden
# =============================================================================


def test_the_corpus_is_the_one_the_golden_was_banked_on(
    banked: dict[str, Any], measured: dict[str, Any]
) -> None:
    """A changed pack, rule book or generator is not a changed engine: it is said first."""
    # Act
    moved = differences({"corpus": banked["corpus"]}, {"corpus": measured["corpus"]})

    # Assert
    assert not moved, (
        "the corpus is not the one the golden was banked on - its returns or its rules "
        "changed (the pack, the rule book, engine_corpus.py or the interpreter's random "
        "sequence), so the engine comparison says nothing until that is explained:\n  "
        + "\n  ".join(moved)
    )


def test_the_engine_says_what_it_said_when_the_golden_was_banked(
    banked: dict[str, Any], measured: dict[str, Any]
) -> None:
    """Every result, break, trace and finding, rule by rule and in order."""
    # Act
    moved = differences({"returns": banked["returns"]}, {"returns": measured["returns"]})

    # Assert
    more = f"\n  ... and {len(moved) - QUOTED} more" if len(moved) > QUOTED else ""
    assert not moved, (
        f"{len(moved)} engine output(s) differ from the banked golden. Each line is "
        "return / output / rule; a rule's three digests are its results, its results with "
        "every failure, and its traced evaluations:\n  "
        + "\n  ".join(moved[:QUOTED])
        + more
        + "\nTo see what moved: `python packages/rwa-filer/tests/engine_golden.py --dump DIR` "
        "on both checkouts, then diff. A speed-up may not move any of this; the golden is "
        "re-banked only for a deliberate, explained behaviour change (engine_golden.py)."
    )


def test_a_moved_output_is_named_by_return_output_and_rule(measured: dict[str, Any]) -> None:
    # Arrange — one rule's digests changed on one return.
    doctored = copy.deepcopy(measured)
    doctored["returns"]["designed"]["rules"]["corpus_where"] = "0 0 0"

    # Act
    moved = differences(measured, doctored)

    # Assert
    assert len(moved) == 1
    assert moved[0].startswith("returns / designed / rules / corpus_where: ")


def test_a_moved_finding_is_named_by_its_position(measured: dict[str, Any]) -> None:
    """Findings and labels are banked as lists, in order: a difference says which one."""
    # Arrange
    doctored = copy.deepcopy(measured)
    doctored["returns"]["designed"]["validate"]["rule_findings"][2] = "VAL001 nothing 0"

    # Act
    moved = differences(measured, doctored)

    # Assert
    assert len(moved) == 1
    assert moved[0].startswith("returns / designed / validate / rule_findings / [2]: ")


def test_the_same_items_in_another_order_are_another_text() -> None:
    """The digests are order-sensitive: a mapping is its items in ITS order."""
    assert canonical_text({"a": 1, "b": 2}) != canonical_text({"b": 2, "a": 1})
    assert canonical_text((1, 2)) != canonical_text((2, 1))
    assert canonical_text((1, 2)) != canonical_text([1, 2])


def test_floats_one_step_apart_are_another_text() -> None:
    assert canonical_text(0.1 + 0.2) != canonical_text(0.3)
    assert canonical_text(1.0) != canonical_text(1)


def test_a_rebank_without_a_reason_is_refused() -> None:
    """The golden moves only for a stated reason — never silently, never to go green."""
    with pytest.raises(ValueError, match="what changed and why"):
        rebank("   ")


# =============================================================================
# The order the review found unguarded
# =============================================================================


def test_a_summed_reference_reads_blank_country_cells_where_the_return_lists_them() -> None:
    """Member-less and membered cells of one sum: row by row, then in the return's order.

    A fact with no country sits at a place that does not name the country, so
    the summed reference has cells at places of two shapes and each evaluation
    gathers from both. They come back in the order the reference matched them —
    the rule's rows, and within a row the return's own order — NOT one shape
    after the other. Verdicts cannot see this order (a sum does not depend on
    it); the trace, the evidence file and a failure's addresses are it.
    """
    # Arrange — two countries, and two blank-country cells: one listed BEFORE
    # the countries' own figure for its row, one AFTER.
    stray_sum = next(rule for rule in hand_built_rules() if rule.rule_id == "corpus_stray_sum")
    figures = (
        (None, "0010", 8.0),
        ("GB", "0010", 1.0),
        ("FR", "0010", 1.0),
        ("GB", "0020", 2.0),
        (None, "0020", 4.0),
        ("FR", "0030", 5.0),
        ("GB", "0030", 3.0),
        ("GB", "0170", 99.0),
        ("FR", "0170", 18.0),
    )
    a_return = return_from(
        [
            (GEO_EXPOSURES, None, country, row, "0010", value, None, 0)
            for country, row, value in figures
        ]
    )
    pack = corpus_release().pack

    def cell(country: str | None, row: str) -> CellAddress:
        return CellAddress(GEO_EXPOSURES, None, country, row, "0010")

    # Act
    traced = trace_rules(a_return, pack, [stray_sum])
    (result,) = evaluate_rules(a_return, pack, [stray_sum])

    # Assert — one evaluation per country, in place order; the blank cells' own
    # place, which both countries extend, is not a third.
    france, britain = traced.evaluations
    assert [dict(item.place) for item in (france, britain)] == [
        {COUNTRY_AXIS: "eba_GA:FR"},
        {COUNTRY_AXIS: "eba_GA:GB"},
    ]
    assert britain.left == (cell("GB", "0170"),)
    assert britain.right == (
        cell(None, "0010"),
        cell("GB", "0010"),
        cell("GB", "0020"),
        cell(None, "0020"),
        cell("GB", "0030"),
    )
    assert france.right == (
        cell(None, "0010"),
        cell("FR", "0010"),
        cell(None, "0020"),
        cell("FR", "0030"),
    )
    assert (france.holds, britain.holds) == (True, False)
    assert (britain.left_value, britain.right_value) == (99.0, 18.0)
    (failure,) = result.failures
    assert failure.addresses == (*britain.left, *britain.right)


# =============================================================================
# Adequacy — the shapes are in the corpus, and the rules that read them run
# =============================================================================


def test_a_handful_of_facts_have_no_member_among_thousands_that_do(
    runs: Mapping[str, Run],
) -> None:
    """The input the review measured: a few blank country cells, not a blank copy."""
    # Arrange
    geographical = runs["open_axes"].ret.facts.filter(
        pl.col("table").is_in([GEO_EXPOSURES, GEO_IRB])
    )

    # Act
    blank = geographical.filter(pl.col("open_key").is_null()).height
    keyed = geographical.filter(pl.col("open_key").is_not_null()).height

    # Assert
    assert 20 <= blank <= 40, f"{blank} member-less facts: the corpus is sized for a handful"  # noqa: PLR2004
    assert keyed > 50 * blank, f"only {keyed} membered facts beside {blank} member-less ones"


@pytest.mark.parametrize("rule_id", SUMMED_RULES)
def test_each_summed_rule_reads_blank_and_keyed_cells_in_one_evaluation(
    runs: Mapping[str, Run], rule_id: str
) -> None:
    """The two-shape lookup is live: one evaluation's sum holds cells of both shapes."""
    # Arrange
    run = runs["open_axes"]
    result = _result(run, rule_id)
    evaluations = evaluations_by_rule(run.trace.evaluations)[rule_id]

    # Act
    mixed = [
        item
        for item in evaluations
        if {address.open_key is None for address in item.right} == {True, False}
    ]

    # Assert
    assert result.status in EVALUATED, f"{rule_id} is not evaluated ({result.reason})"
    assert mixed, f"no evaluation of {rule_id} sums a member-less cell with a membered one"


def test_a_blank_country_cell_no_country_extends_is_evaluated_at_its_own_place(
    runs: Mapping[str, Run],
) -> None:
    """Where no country reports the column, the place without a country survives."""
    # Arrange
    column = STRAY_ONLY_COLUMNS[GEO_EXPOSURES]
    evaluations = evaluations_by_rule(runs["open_axes"].trace.evaluations)["boe_b0730"]

    # Act
    places = [dict(item.place) for item in evaluations]

    # Assert
    assert {"c": column} in places, f"no evaluation at column {column} alone"
    assert any(COUNTRY_AXIS in place for place in places), "no evaluation names a country"


def test_open_keys_are_written_as_local_names_and_as_qnames_for_one_cell_too(
    runs: Mapping[str, Run],
) -> None:
    # Arrange
    facts = runs["open_axes"].ret.facts.filter(pl.col("table") == GEO_EXPOSURES)

    # Act
    keys = set(facts["open_key"].drop_nulls().to_list())
    both_ways = facts.filter(
        (pl.col("row") == "0010")
        & (pl.col("column") == "0010")
        & pl.col("open_key").is_in(["GB", "eba_GA:GB"])
    )

    # Assert
    assert any(":" in key for key in keys), "no open key is written as a QName"
    assert any(":" not in key for key in keys), "no open key is written as a local name"
    assert both_ways["open_key"].to_list().count("GB") == 1
    assert both_ways["open_key"].to_list().count("eba_GA:GB") == 1


@pytest.mark.parametrize(
    ("table", "rule_id"),
    [(GRADES, "boe_b0761"), (GRADES, "boe_b0814_01"), (COUNTERPARTIES, "v10488_s")],
)
def test_open_row_tables_hold_several_rows_and_their_rules_are_evaluated(
    runs: Mapping[str, Run], table: str, rule_id: str
) -> None:
    # Arrange
    run = runs["open_rows"]
    rows = (
        run.ret.facts.filter(pl.col("table") == table)
        .group_by("sheet")
        .agg(pl.col("row").n_unique())
    )

    # Act
    result = _result(run, rule_id)

    # Assert
    assert rows["row"].min() >= 2, f"{table} has a sheet with one row: nothing to tell rows apart"  # noqa: PLR2004
    assert result.status in EVALUATED, f"{rule_id} is not evaluated ({result.reason})"
    assert result.evaluations >= 2, f"{rule_id} was evaluated {result.evaluations} time(s)"  # noqa: PLR2004


def test_a_summed_rule_reads_more_cells_than_a_failure_records(runs: Mapping[str, Run]) -> None:
    """One sheet has 70 grades: a broken class total reads them all and records the first 64."""
    # Arrange
    run = runs["open_rows"]
    result = _result(run, "boe_b0814_01")
    broken = [
        item
        for item in evaluations_by_rule(run.trace.evaluations)["boe_b0814_01"]
        if not item.holds
    ]

    # Act
    read = {len(item.left) + len(item.right) for item in broken}
    recorded = {len(failure.addresses) for failure in result.failures}

    # Assert
    assert MANY_GRADES + 1 in read, f"no broken evaluation read {MANY_GRADES} grades and a total"
    assert MAX_ADDRESSES in recorded, f"no failure was cut at {MAX_ADDRESSES} addresses"


def test_a_cell_the_formula_turns_away_is_listed_as_reported_but_read_at_its_default(
    runs: Mapping[str, Run],
) -> None:
    """``corpus_shut_variable`` closes, for its right side, a dimension the cell carries.

    The side lists the cell as the return has it; the comparison did not read
    it. A change that makes the two agree — either way — changes the evidence.
    """
    # Arrange
    turned_away = CellAddress(MATRIX, None, None, "0010", "0020")
    reported = runs["designed"].ret.facts.filter(
        (pl.col("table") == MATRIX) & (pl.col("row") == "0010") & (pl.col("column") == "0020")
    )

    # Act
    evaluation = _at(runs["designed"], "corpus_shut_variable", r="0010")
    (comparison,) = evaluation.comparisons

    # Assert
    assert reported["value"].to_list() == [10.0], "the cell is not in the return"
    assert evaluation.right == (turned_away,)
    assert comparison.right.cells == ()
    assert comparison.right.value == 0.0
    assert [item.address for item in comparison.right.defaulted] == [
        replace(turned_away, reported=False)
    ]


def test_a_cell_the_rules_text_turns_away_is_listed_as_reported_but_read_at_its_default(
    runs: Mapping[str, Run],
) -> None:
    """``corpus_value_filter`` names the cell only where it holds one currency; it holds another."""
    # Arrange
    turned_away = CellAddress(ENTITY_DETAILS, None, None, "0060", "0010")
    run = runs["designed"]
    reported = run.ret.facts.filter((pl.col("table") == ENTITY_DETAILS) & (pl.col("row") == "0060"))

    # Act
    (evaluation,) = evaluations_by_rule(run.trace.evaluations)["corpus_value_filter"]
    (comparison,) = evaluation.comparisons

    # Assert
    assert reported["text_value"].to_list() == [CURRENCY_REPORTED.rsplit(":", 1)[-1]]
    assert evaluation.left == (turned_away,)
    assert comparison.left.cells == ()
    assert comparison.left.value == "Default"
    assert [item.address for item in comparison.left.defaulted] == [
        replace(turned_away, reported=False)
    ]


def test_a_where_clause_is_traced_and_turns_rows_away(runs: Mapping[str, Run]) -> None:
    # Arrange
    run = runs["designed"]
    rows_reported = run.ret.facts.filter(pl.col("table") == MATRIX)["row"].n_unique()

    # Act
    evaluations = evaluations_by_rule(run.trace.evaluations)["corpus_where"]
    branches = {tuple(item.branch for item in evaluation.comparisons) for evaluation in evaluations}

    # Assert — the clause's two comparisons, then the rule's own; fewer
    # evaluations than rows; and both verdicts.
    assert branches == {("where", "where", "rule")}
    assert 0 < len(evaluations) < rows_reported
    assert {item.holds for item in evaluations} == {True, False}


def test_nested_conditionals_trace_the_branch_each_comparison_ran_in(
    runs: Mapping[str, Run],
) -> None:
    # Act
    evaluations = evaluations_by_rule(runs["designed"].trace.evaluations)["corpus_conditional"]
    branches = {item.branch for evaluation in evaluations for item in evaluation.comparisons}

    # Assert
    assert branches == {"rule/if", "rule/then/if", "rule/then/then", "rule/then/else", "rule/else"}


@pytest.mark.parametrize("name", ["open_axes", "open_rows", "designed", "wide"])
def test_a_result_records_the_first_breaks_and_counts_them_all(
    runs: Mapping[str, Run], name: str
) -> None:
    """Past ``MAX_FAILURES`` a result keeps the first five, in place order; asked, it keeps all."""
    # Arrange
    run = runs[name]
    pairs = [
        (result, every)
        for result, every in zip(run.results, run.every_failure, strict=True)
        if result.unsatisfied > MAX_FAILURES
    ]

    # Assert
    assert pairs, f"no rule breaks more than {MAX_FAILURES} times on {name}: nothing is cut"
    for result, every in pairs:
        assert len(result.failures) == MAX_FAILURES, result.rule_id
        assert len(every.failures) == every.unsatisfied == result.unsatisfied, result.rule_id
        assert result.failures == every.failures[:MAX_FAILURES], result.rule_id


def test_a_downgraded_rule_breaks_as_a_warning_and_keeps_what_the_formula_found(
    runs: Mapping[str, Run],
) -> None:
    # Act
    result = _reported(runs["designed"], "corpus_icmp_le")

    # Assert
    assert result.deny is not None and result.deny.deny_type == DENY_DOWNGRADED
    assert (result.status, result.severity) == (STATUS_FAIL, "WARNING")
    assert result.formula is not None and result.formula.severity == "ERROR"


def test_a_deactivated_rule_leaves_the_trace_with_the_cell_only_it_read(
    runs: Mapping[str, Run],
) -> None:
    """``trace_return`` drops what the gateway does not run; ``trace_rules`` keeps it."""
    # Arrange
    run = runs["designed"]
    lone = CellAddress(UNRULED, None, None, "0010", "0010")

    # Act
    result = _reported(run, "corpus_deactivated")

    # Assert
    assert result.deny is not None and result.deny.deny_type == DENY_DEACTIVATED
    assert (result.status, result.reason) == (STATUS_NOT_EVALUATED, REASON_DEACTIVATED_BY_PUBLISHER)
    assert result.formula is not None and result.formula.evaluations == 1
    assert "corpus_deactivated" in evaluations_by_rule(run.trace.evaluations)
    assert "corpus_deactivated" not in evaluations_by_rule(run.traced.evaluations)
    assert lone in run.trace.cells
    assert lone not in run.traced.cells


def test_a_packaged_rule_the_bank_deactivated_breaks_on_the_corpus(runs: Mapping[str, Run]) -> None:
    """Not only a hand-built entry: a rule on the Bank's own list has evaluations to lose."""
    # Act
    switched_off = [
        result
        for run in runs.values()
        for result in _report_results(run)
        if result.reason == REASON_DEACTIVATED_BY_PUBLISHER
        and not result.rule_id.startswith("corpus_")
        and result.formula is not None
        and result.formula.status == STATUS_FAIL
    ]

    # Assert
    assert switched_off, "no rule on the Bank's deny list breaks anywhere in the corpus"


def test_a_known_issue_classifies_breaks_inside_and_outside_its_footprint(
    runs: Mapping[str, Run],
) -> None:
    """The label pass is live on both paths, at the accuracy the caller gave.

    ``open_rows`` breaks one rule twice, on a sheet inside the footprint of the
    issue that labels it and on one outside, and only at its own accuracy:
    ``validate_return`` traces the rule again to classify the breaks,
    ``trace_return`` reads the trace it has, and both must count one each.
    """
    # Arrange
    run = runs["open_rows"]
    assert build_corpus()["open_rows"].accuracy is not None, "the return states no accuracy"
    assert run.validation.report is not None
    assert run.traced_validation.report is not None

    # Act
    (validated,) = run.validation.report.notes_for(FOOTPRINT_RULE)
    (traced,) = run.traced_validation.report.notes_for(FOOTPRINT_RULE)

    # Assert
    assert (validated.inside, validated.outside) == (1, 1)
    assert traced == validated


def test_every_hand_built_rule_is_evaluated_somewhere_unless_it_is_built_not_to_be(
    runs: Mapping[str, Run],
) -> None:
    """No hand-built rule is in the golden only as "nothing to read"."""
    # Act
    outcomes = {
        rule.rule_id: {name: _result(run, rule.rule_id) for name, run in runs.items()}
        for rule in hand_built_rules()
    }

    # Assert
    assert set(NOT_EVALUATED_BY_DESIGN) <= set(outcomes), "a rule named here is no longer built"
    for rule_id, by_return in outcomes.items():
        if rule_id in NOT_EVALUATED_BY_DESIGN:
            designed = by_return["designed"]
            assert (designed.status, designed.reason) == (
                STATUS_NOT_EVALUATED,
                NOT_EVALUATED_BY_DESIGN[rule_id],
            ), rule_id
        else:
            assert any(result.status in EVALUATED for result in by_return.values()), (
                f"{rule_id} is evaluated on no corpus return"
            )


def test_open_rows_under_an_open_axis_are_read_at_places_of_two_shapes(
    runs: Mapping[str, Run],
) -> None:
    """A row with no member on the sheet axis is its own place beside the membered rows'."""
    # Act
    places = [
        dict(item.place) for item in _evaluations(runs["open_rows"], "corpus_rows_under_open_axis")
    ]
    shapes = {tuple(sorted(place)) for place in places}

    # Assert
    assert shapes == {
        ("key:eba_dim:PDT", "open:eba_dim:ECA", "z"),
        ("key:eba_dim:PDT", "z"),
    }


def test_a_join_names_a_row_key_by_the_other_tables_dimension(runs: Mapping[str, Run]) -> None:
    """The counterparty key is lined up with the VaR key, under the VaR key's name."""
    # Act
    evaluations = _evaluations(runs["open_rows"], "corpus_join_alias")
    axes = {tuple(axis for axis, _value in item.place) for item in evaluations}

    # Assert — the aliased key sorts BEFORE the table's other key, though its
    # own dimension (eba_dim:CPT) sorts after it.
    assert axes == {("key:boe_dim:UDI", "key:eba_dim:CLR")}
    assert any(item.left and item.right for item in evaluations), "no place reads both tables"


def test_text_is_compared_before_on_and_after_its_bound(runs: Mapping[str, Run]) -> None:
    """The date rules meet an earlier, an equal and a later date: `<` and `<=` differ on one."""
    # Arrange
    run = runs["designed"]
    assert run.ret.facts.filter(pl.col("table") == DATES).height > 0

    # Act
    less = {dict(item.place)["r"]: item.holds for item in _evaluations(run, "corpus_date_lt")}
    at_most = {dict(item.place)["r"]: item.holds for item in _evaluations(run, "corpus_date_le")}

    # Assert
    assert [row for row in less if less[row] != at_most[row]] == ["0030"]


def test_the_corpus_stays_cheap(runs: Mapping[str, Run]) -> None:
    """Facts and evaluations stand in for CPU: the file must stay well inside a test budget."""
    # Act
    facts = sum(run.ret.facts.height for run in runs.values())
    evaluations = sum(result.evaluations for run in runs.values() for result in run.results)

    # Assert
    assert facts <= MAX_CORPUS_FACTS, f"the corpus has grown to {facts} facts"
    assert 0 < evaluations <= MAX_CORPUS_EVALUATIONS, f"{evaluations} evaluations per pass"


# =============================================================================
# Helpers
# =============================================================================


def _result(run: Run, rule_id: str) -> RuleResult:
    """``evaluate_rules``'s result for one rule."""
    return next(result for result in run.results if result.rule_id == rule_id)


def _report_results(run: Run) -> tuple[RuleResult, ...]:
    """``validate_return``'s results: the engine's, as the gateway runs them."""
    assert run.validation.report is not None
    return run.validation.report.results


def _reported(run: Run, rule_id: str) -> RuleResult:
    return next(result for result in _report_results(run) if result.rule_id == rule_id)


def _evaluations(run: Run, rule_id: str) -> tuple[Evaluation, ...]:
    return evaluations_by_rule(run.trace.evaluations)[rule_id]


def _at(run: Run, rule_id: str, **place: str) -> Evaluation:
    """The one traced evaluation of ``rule_id`` at ``place``."""
    (found,) = [item for item in _evaluations(run, rule_id) if dict(item.place) == place]
    return found
