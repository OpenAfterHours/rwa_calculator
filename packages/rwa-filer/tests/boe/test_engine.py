"""
The rule engine's semantics, one behaviour per test, on the synthetic pack.

Each test states a rule in the published syntax, a handful of facts, and the
number of evaluations that must be satisfied and unsatisfied. Counts, not just
verdicts: counting evaluations is what distinguishes "run once per cell" from
"run once over the sum", which give the same verdict on most data and a
different one on the data that matters.

That these semantics are the TAXONOMY's is not established here — it is
established against Arelle, on the Bank's own sample, in
``test_sample_oracle.py``. These tests pin what was established.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from boe_builders import T01, T02, T03, T04, T05A, T06, T07, ref, rule, scope
from pack_builders import build_pack, build_return
from rwa_filer.boe.catalogue import Rule
from rwa_filer.boe.engine import (
    MAX_FAILURES,
    REASON_NO_DATA,
    REASON_NOT_REPORTED,
    REASON_UNKNOWN_TABLE,
    REASON_UNSUPPORTED,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    Accuracy,
    RuleResult,
    evaluate_rules,
)
from rwa_filer.model import DECIMALS_EXACT, CanonicalReturn
from rwa_filer.taxonomy.pack import TaxonomyPack

COLUMNS = ["table", "sheet", "open_key", "row", "column", "value", "text_value", "decimals"]

#: Exact accuracy, so that tests about counting are not also tests about rounding.
EXACT = Accuracy(monetary_decimals=DECIMALS_EXACT, percentage_decimals=DECIMALS_EXACT)


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path / "pack")


def ret(*rows: tuple[object, ...]) -> CanonicalReturn:
    padded = [(*row, *([None] * (len(COLUMNS) - len(row)))) for row in rows]
    return build_return(pl.DataFrame(padded, schema=COLUMNS, orient="row"))


def t01(row: str, column: str, value: float, decimals: int | None = None) -> tuple[object, ...]:
    return (T01, None, None, row, column, value, None, decimals)


def t02(sheet: str, row: str, value: float) -> tuple[object, ...]:
    return (T02, sheet, None, row, "0010", value)


def run(
    pack: TaxonomyPack, a_rule: Rule, *rows: tuple[object, ...], accuracy: Accuracy = EXACT
) -> RuleResult:
    (result,) = evaluate_rules(ret(*rows), pack, [a_rule], accuracy=accuracy)
    return result


def counts(result: RuleResult) -> tuple[int, int]:
    return result.satisfied, result.unsatisfied


TOTAL = f"{ref(T01, '0010', '0010')} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}"
FOOTING = rule("footing", TOTAL, tables=(T01,))
#: RWEA (row 0020) may not exceed exposure (row 0010) — on every sheet of T02.
CAP = rule("cap", f"{ref(T02, '0020', '0010')} i<= {ref(T02, '0010', '0010')}", tables=(T02,))


# ---------------------------------------------------------------------------
# Whether a rule is run at all
# ---------------------------------------------------------------------------


def test_a_rule_holds_or_does_not(pack: TaxonomyPack) -> None:
    # Act
    holds = run(
        pack, FOOTING, t01("0010", "0010", 100), t01("0020", "0010", 60), t01("0030", "0010", 40)
    )
    broken = run(
        pack, FOOTING, t01("0010", "0010", 100), t01("0020", "0010", 60), t01("0030", "0010", 30)
    )

    # Assert
    assert (holds.status, counts(holds)) == (STATUS_PASS, (1, 0))
    assert (broken.status, counts(broken)) == (STATUS_FAIL, (0, 1))


def test_a_rule_is_not_run_when_a_table_it_reads_is_not_reported(pack: TaxonomyPack) -> None:
    """The gateway blocks it: neither satisfied nor unsatisfied."""
    # Arrange — the rule reads T01 and T02; only T01 is in the return.
    cross = rule(
        "cross",
        f"{ref(T01, '0010', '0010')} i= {ref(T02, '0010', '0010', '0001')}",
        tables=(T01, T02),
    )

    # Act
    result = run(pack, cross, t01("0010", "0010", 100))

    # Assert
    assert (result.status, result.reason, result.detail) == (
        STATUS_NOT_EVALUATED,
        REASON_NOT_REPORTED,
        T02,
    )


def test_a_template_reported_with_no_facts_is_all_zero_to_the_rule(pack: TaxonomyPack) -> None:
    """Declared as reported, so the rule runs — and 100 is not the 0 the empty table holds."""
    # Arrange
    cross = rule(
        "cross",
        f"{ref(T01, '0010', '0010')} i= {ref(T02, '0010', '0010', '0001')}",
        tables=(T01, T02),
    )
    base = ret(t01("0010", "0010", 100))
    declared = CanonicalReturn(base.header, base.facts, {"T01.00.01": True, "T02.00.01": True})

    # Act
    (result,) = evaluate_rules(declared, pack, [cross], accuracy=EXACT)

    # Assert
    assert (result.status, counts(result)) == (STATUS_FAIL, (0, 1))


def test_a_rule_on_a_table_the_module_does_not_have_is_not_evaluated(pack: TaxonomyPack) -> None:
    other = rule(
        "other",
        "{t: X99.00.01.01, r: 0010, c: 0010, dv: 0, seq: False, f: t, fv: t} >= 0",
        tables=("X99.00.01.01",),
    )

    result = run(pack, other, t01("0010", "0010", 100))

    assert (result.status, result.reason) == (STATUS_NOT_EVALUATED, REASON_UNKNOWN_TABLE)


def test_a_rule_using_something_the_engine_lacks_says_so(pack: TaxonomyPack) -> None:
    odd = rule("odd", f"distinct({ref(T01, '0010', '0010')}) = 1", tables=(T01,))

    result = run(pack, odd, t01("0010", "0010", 100))

    assert (result.status, result.reason) == (STATUS_NOT_EVALUATED, REASON_UNSUPPORTED)
    assert "distinct" in result.detail


def test_a_rule_that_does_not_parse_is_not_evaluated_and_does_not_raise(pack: TaxonomyPack) -> None:
    broken = rule("broken", "{t: T01.00.01.01, r: 0010", tables=(T01,))

    result = run(pack, broken, t01("0010", "0010", 100))

    assert (result.status, result.reason) == (STATUS_NOT_EVALUATED, REASON_UNSUPPORTED)


# ---------------------------------------------------------------------------
# Unreported cells
# ---------------------------------------------------------------------------


def test_an_unreported_cell_is_what_its_reference_says_it_is(pack: TaxonomyPack) -> None:
    """``dv: 0`` — the total is reported and its parts are not, so 100 is not 0 + 0."""
    result = run(pack, FOOTING, t01("0010", "0010", 100))

    assert counts(result) == (0, 1)


def test_a_reference_with_no_default_cannot_stand_in_for_a_missing_cell(pack: TaxonomyPack) -> None:
    """No ``dv``: where that cell is not reported, the rule is not evaluated."""
    # Arrange — the same identity, but the total has no default.
    strict = rule(
        "strict",
        f"{ref(T01, '0010', '0010', dv=None)} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}",
        tables=(T01,),
    )

    # Act — only a part is reported.
    result = run(pack, strict, t01("0020", "0010", 60))

    # Assert
    assert (result.status, result.reason, counts(result)) == (
        STATUS_NOT_EVALUATED,
        REASON_NO_DATA,
        (0, 0),
    )


def test_a_place_where_nothing_is_reported_is_not_evaluated(pack: TaxonomyPack) -> None:
    """Sheet 0002 is empty: a wholly unreported coordinate is never a failure."""
    result = run(pack, CAP, t02("0001", "0010", 60), t02("0001", "0020", 30))

    assert counts(result) == (1, 0)


def test_always_execute_runs_the_rule_even_where_nothing_is_reported(pack: TaxonomyPack) -> None:
    """What lets "this cell must be reported" fail when it is not."""
    # Arrange — T01 is reported (another cell), the required cell is not.
    required = f"not(isNull({ref(T01, '0010', '0010', dv='emptySequence()')}))"
    ordinary = rule("ordinary", required, tables=(T01,))
    always = rule("always", required, tables=(T01,), always_execute=True)

    # Act
    quiet = run(pack, ordinary, t01("0020", "0010", 5))
    loud = run(pack, always, t01("0020", "0010", 5))

    # Assert
    assert (quiet.status, quiet.reason) == (STATUS_NOT_EVALUATED, REASON_NO_DATA)
    assert (loud.status, counts(loud)) == (STATUS_FAIL, (0, 1))


# ---------------------------------------------------------------------------
# One evaluation per place
# ---------------------------------------------------------------------------


def test_an_axis_the_rule_leaves_open_is_run_once_per_value(pack: TaxonomyPack) -> None:
    """No sheet is named: the rule is run on each sheet, its two cells read together."""
    result = run(
        pack,
        CAP,
        t02("0001", "0010", 60),
        t02("0001", "0020", 30),
        t02("0002", "0010", 40),
        t02("0002", "0020", 50),
    )

    assert counts(result) == (1, 1)
    assert result.failures[0].place == "sheet 0002"


def test_several_codes_in_a_reference_are_separate_evaluations_not_a_sum(
    pack: TaxonomyPack,
) -> None:
    """``r: 0020; 0030`` without ``seq`` is two cells, each tested — never their total."""
    # Arrange — each part may be at most 50. Their sum is 80.
    each = rule("each", f"{ref(T01, '0020; 0030', '0010')} <= 50", tables=(T01,))

    # Act
    result = run(pack, each, t01("0020", "0010", 60), t01("0030", "0010", 20))

    # Assert — one cell breaks, one holds. A sum would be one evaluation.
    assert counts(result) == (1, 1)
    assert result.failures[0].place == "row 0020"


def test_a_sequence_reference_takes_all_its_cells_at_once(pack: TaxonomyPack) -> None:
    # Arrange
    total = rule(
        "total",
        f"{ref(T01, '0010', '0010')} i= isum({ref(T01, '0020; 0030', '0010', dv='emptySequence()', seq=True)})",
        tables=(T01,),
    )

    # Act
    result = run(
        pack, total, t01("0010", "0010", 100), t01("0020", "0010", 60), t01("0030", "0010", 40)
    )

    # Assert
    assert counts(result) == (1, 0)


def test_a_scope_runs_the_rule_once_per_listed_code(pack: TaxonomyPack) -> None:
    """Sheet 0002 breaks, but the scope lists only 0001."""
    # Arrange
    scoped = rule("scoped", CAP.expression, tables=(T02,), scope=scope(T02, z="0001"))
    rows = (
        t02("0001", "0010", 60),
        t02("0001", "0020", 30),
        t02("0002", "0010", 40),
        t02("0002", "0020", 50),
    )

    # Act
    result = run(pack, scoped, *rows)

    # Assert
    assert counts(result) == (1, 0)


def test_a_scope_iterates_even_a_sequence_reference(pack: TaxonomyPack) -> None:
    """The sum is taken per scoped sheet — the scope is never summed across."""
    # Arrange — exposure + RWEA per sheet must be at most 100.
    per_sheet = rule(
        "per-sheet",
        f"isum({ref(T02, '0010; 0020', '0010', dv='emptySequence()', seq=True)}) i<= 100",
        tables=(T02,),
        scope=scope(T02, z="0001;0002"),
    )

    # Act — 60 + 30 on one sheet, 40 + 50 on the other; 180 across both.
    result = run(
        pack,
        per_sheet,
        t02("0001", "0010", 60),
        t02("0001", "0020", 30),
        t02("0002", "0010", 40),
        t02("0002", "0020", 50),
    )

    # Assert
    assert counts(result) == (2, 0)


def test_references_reported_at_different_places_are_each_evaluated(pack: TaxonomyPack) -> None:
    """Exposure only on sheet 0001, RWEA only on sheet 0002: two evaluations, one each."""
    result = run(pack, CAP, t02("0001", "0010", 60), t02("0002", "0020", 50))

    # Sheet 0001: 0 <= 60 holds. Sheet 0002: 50 <= 0 does not.
    assert counts(result) == (1, 1)


# ---------------------------------------------------------------------------
# Open axes and open rows
# ---------------------------------------------------------------------------


def geo(member: str, row: str, value: float) -> tuple[object, ...]:
    return (T03, None, member, row, "0010", value)


def test_an_open_axis_is_run_once_per_reported_member(pack: TaxonomyPack) -> None:
    # Arrange — RWEA (0020) at most exposure (0010), per country.
    per_country = rule(
        "geo", f"{ref(T03, '0020', '0010')} i<= {ref(T03, '0010', '0010')}", tables=(T03,)
    )

    # Act
    result = run(
        pack,
        per_country,
        geo("GB", "0010", 70),
        geo("GB", "0020", 20),
        geo("FR", "0010", 30),
        geo("FR", "0020", 40),
    )

    # Assert
    assert counts(result) == (1, 1)
    assert result.failures[0].place == "CEG FR"


def test_a_filter_names_one_member_of_an_open_axis(pack: TaxonomyPack) -> None:
    # Arrange — only the all-countries total (x1) is tested.
    total_only = rule(
        "geo-total",
        f"{ref(T03, '0020', '0010', flt='dim(this(), [eba_dim:CEG]) = [eba_GA:x1]')} i<= "
        f"{ref(T03, '0010', '0010', flt='dim(this(), [eba_dim:CEG]) = [eba_GA:x1]')}",
        tables=(T03,),
    )

    # Act — France breaks; the total does not.
    result = run(
        pack,
        total_only,
        geo("x1", "0010", 100),
        geo("x1", "0020", 60),
        geo("FR", "0010", 30),
        geo("FR", "0020", 40),
    )

    # Assert
    assert counts(result) == (1, 0)


def grade(
    row: str, column: str, value: float | None, text: str | None = None
) -> tuple[object, ...]:
    return (T04, None, None, row, column, value, text)


GRADES = (
    grade("a", "0005", 1.0),
    grade("a", "0010", 500.0),
    grade("a", "0020", 12.0),
    grade("b", "0005", 2.0),
    grade("b", "0010", 250.0),
    grade("b", "0020", 0.0),
)


def test_an_open_row_table_is_run_once_per_row(pack: TaxonomyPack) -> None:
    """A row with exposure must have obligors: grade 2 has 250 and none."""
    # Arrange
    populated = rule(
        "populated",
        f"if {ref(T04, c='0010')} > 0 then {ref(T04, c='0020')} > 0",
        tables=(T04,),
    )

    # Act
    result = run(pack, populated, *GRADES)

    # Assert
    assert counts(result) == (1, 1)
    assert result.failures[0].place == "OGR 2"


def test_a_sequence_reference_takes_every_row_of_an_open_row_table(pack: TaxonomyPack) -> None:
    # Arrange — the shared total equals the sum over all grades.
    summed = rule(
        "grades-total",
        f"{ref(T05A, '0010', '0010')} i= isum({ref(T04, c='0010', dv='emptySequence()', seq=True)})",
        tables=(T05A, T04),
    )

    # Act
    result = run(pack, summed, *GRADES, (T05A, None, None, "0010", "0010", 750.0))

    # Assert
    assert counts(result) == (1, 0)


def test_count_counts_the_rows_reported(pack: TaxonomyPack) -> None:
    two = rule(
        "two", f"count({ref(T04, c='0010', dv='emptySequence()', seq=True)}) = 2", tables=(T04,)
    )

    assert counts(run(pack, two, *GRADES)) == (1, 0)


# ---------------------------------------------------------------------------
# Rounding allowances
# ---------------------------------------------------------------------------


def test_an_interval_comparison_allows_for_each_facts_stated_accuracy(pack: TaxonomyPack) -> None:
    """100,000 against 60,000 + 39,200: 800 apart, three facts each good to +/- 500."""
    # Arrange
    rows = (
        t01("0010", "0010", 100_000, -3),
        t01("0020", "0010", 60_000, -3),
        t01("0030", "0010", 39_200, -3),
    )
    exact_rows = tuple((*row[:7], 0) for row in rows)

    # Act
    to_thousands = run(pack, FOOTING, *rows)
    to_units = run(pack, FOOTING, *exact_rows)

    # Assert
    assert counts(to_thousands) == (1, 0)
    assert counts(to_units) == (0, 1)


def test_an_exact_comparison_ignores_stated_accuracy(pack: TaxonomyPack) -> None:
    # Arrange — the same identity with plain operators.
    plain = rule(
        "plain",
        f"{ref(T01, '0010', '0010')} = {ref(T01, '0020', '0010')} + {ref(T01, '0030', '0010')}",
        tables=(T01,),
    )

    # Act
    result = run(
        pack,
        plain,
        t01("0010", "0010", 100_000, -3),
        t01("0020", "0010", 60_000, -3),
        t01("0030", "0010", 39_200, -3),
    )

    # Assert
    assert counts(result) == (0, 1)


def test_a_fact_without_decimals_takes_the_default_for_its_type(pack: TaxonomyPack) -> None:
    """The default is what the file will be written with, so it decides the verdict."""
    # Arrange — 800 apart, no decimals stated on any fact.
    rows = (t01("0010", "0010", 100_000), t01("0020", "0010", 60_000), t01("0030", "0010", 39_200))

    # Act
    thousands = run(pack, FOOTING, *rows, accuracy=Accuracy(monetary_decimals=-3))
    pence = run(pack, FOOTING, *rows, accuracy=Accuracy(monetary_decimals=2))

    # Assert
    assert counts(thousands) == (1, 0)
    assert counts(pence) == (0, 1)


def test_a_literal_and_a_default_carry_no_allowance(pack: TaxonomyPack) -> None:
    """``x i<= 100`` with x = 100,400 to thousands: within x's own 500, so it holds."""
    limit = rule("limit", f"{ref(T01, '0010', '0010')} i<= 100000", tables=(T01,))

    assert counts(run(pack, limit, t01("0010", "0010", 100_400, -3))) == (1, 0)
    assert counts(run(pack, limit, t01("0010", "0010", 100_600, -3))) == (0, 1)


def test_a_product_propagates_the_allowance(pack: TaxonomyPack) -> None:
    """amount (100, +/- 0.5) times ratio (0.5, +/- 0.005): allowance 0.5*0.5 + 100*0.005 + ..."""
    # Arrange — row 0020 amount must equal row 0010 amount times its ratio.
    product = rule(
        "product",
        f"{ref(T01, '0020', '0010')} i= {ref(T01, '0010', '0010')} i* {ref(T01, '0010', '0020')}",
        tables=(T01,),
    )
    base = (t01("0010", "0010", 100, 0), t01("0010", "0020", 0.5, 2))

    # Act — 50 expected; allowance 0.5 (lhs) + 0.7525 (product) = 1.2525.
    near = run(pack, product, *base, t01("0020", "0010", 51.2, 0))
    far = run(pack, product, *base, t01("0020", "0010", 51.3, 0))

    # Assert
    assert counts(near) == (1, 0)
    assert counts(far) == (0, 1)


# ---------------------------------------------------------------------------
# Conditions, text and functions
# ---------------------------------------------------------------------------


def typed(column: str, text: str) -> tuple[object, ...]:
    return (T06, None, None, "0010", column, None, text)


def test_a_conditional_with_no_else_holds_when_the_condition_is_false(pack: TaxonomyPack) -> None:
    conditional = rule(
        "conditional",
        f"if {ref(T01, '0010', '0010')} > 0 then {ref(T01, '0020', '0010')} > 0",
        tables=(T01,),
    )

    assert counts(run(pack, conditional, t01("0010", "0010", 0), t01("0020", "0010", 0))) == (1, 0)
    assert counts(run(pack, conditional, t01("0010", "0010", 5), t01("0020", "0010", 0))) == (0, 1)


def test_boolean_and_enumeration_cells_compare_with_their_literals(pack: TaxonomyPack) -> None:
    # Arrange — if the flag is set, the choice must be x2.
    flagged = rule(
        "flagged",
        f"if {ref(T06, '0010', '0010', dv='false()')} = true() "
        f"then {ref(T06, '0010', '0030', dv='[Default]')} = [tst_ZZ:x2]",
        tables=(T06,),
    )

    # Act — the member may be given by local name.
    right = run(pack, flagged, typed("0010", "true"), typed("0030", "x2"))
    wrong = run(pack, flagged, typed("0010", "true"), typed("0030", "tst_ZZ:x1"))
    unset = run(pack, flagged, typed("0010", "false"), typed("0030", "tst_ZZ:x1"))

    # Assert
    assert [counts(result) for result in (right, wrong, unset)] == [(1, 0), (0, 1), (1, 0)]


def test_an_unreported_enumeration_cell_equals_the_default_member(pack: TaxonomyPack) -> None:
    unchosen = rule(
        "unchosen",
        f"if {ref(T06, '0010', '0010', dv='false()')} = true() "
        f"then {ref(T06, '0010', '0030', dv='[Default]')} != [Default]",
        tables=(T06,),
    )

    assert counts(run(pack, unchosen, typed("0010", "true"))) == (0, 1)


def test_matches_tests_a_text_cell_against_a_pattern(pack: TaxonomyPack) -> None:
    dated = rule(
        "dated", f'matches({ref(T06, "0010", "0020", dv=chr(34) * 2)}, "^2027-")', tables=(T06,)
    )

    assert counts(run(pack, dated, typed("0020", "2027-03-31"))) == (1, 0)
    assert counts(run(pack, dated, typed("0020", "2026-12-31"))) == (0, 1)


def test_and_or_and_not_combine_conditions(pack: TaxonomyPack) -> None:
    # Arrange — both parts non-negative, or the total is zero.
    combined = rule(
        "combined",
        f"({ref(T01, '0020', '0010')} >= 0 and {ref(T01, '0030', '0010')} >= 0) "
        f"or not({ref(T01, '0010', '0010')} != 0)",
        tables=(T01,),
    )

    # Act / Assert
    assert counts(run(pack, combined, t01("0020", "0010", 5), t01("0030", "0010", 5))) == (1, 0)
    assert counts(run(pack, combined, t01("0020", "0010", -5), t01("0010", "0010", 0))) == (1, 0)
    assert counts(run(pack, combined, t01("0020", "0010", -5), t01("0010", "0010", 9))) == (0, 1)


@pytest.mark.parametrize(
    ("expression", "holds"),
    [
        ("imax({a}, {b}) = 60", True),
        ("imin({a}, {b}, 10) = 10", True),
        ("iabs({a} i- {b}) = 20", True),
        ("-{a} < 0", True),
        ("exp({a}, 1, 2) > 7.7", True),  # 60 ^ (1/2)
        ("log({a}, eulerConst()) > 4", True),  # ln 60
        ("{a} / {b} = 1.5", True),
        ("isNull({a})", False),
        ("StringLength({a}) = 2", False),  # a number has no length
    ],
)
def test_the_functions_the_published_rules_use(
    pack: TaxonomyPack, expression: str, holds: bool
) -> None:
    # Arrange — a = 60, b = 40.
    text = expression.format(a=ref(T01, "0020", "0010"), b=ref(T01, "0030", "0010"))
    a_rule = rule("function", text, tables=(T01,))

    # Act
    result = run(pack, a_rule, t01("0020", "0010", 60), t01("0030", "0010", 40))

    # Assert
    assert counts(result) == ((1, 0) if holds else (0, 1))


def test_division_by_zero_is_no_evaluation(pack: TaxonomyPack) -> None:
    ratio = rule(
        "ratio", f"{ref(T01, '0020', '0010')} / {ref(T01, '0030', '0010')} <= 1", tables=(T01,)
    )

    result = run(pack, ratio, t01("0020", "0010", 60), t01("0030", "0010", 0))

    assert (result.status, counts(result)) == (STATUS_NOT_EVALUATED, (0, 0))


def test_an_optional_open_axis_all_sheet_is_read_with_no_member(pack: TaxonomyPack) -> None:
    # Arrange — T07: no open key is the "all" sheet.
    capped = rule("capped", f"{ref(T07, '0010', '0010')} <= 50", tables=(T07,))

    # Act
    result = run(
        pack,
        capped,
        (T07, None, None, "0010", "0010", 100.0),
        (T07, None, "x1", "0010", "0010", 40.0),
    )

    # Assert — one place per sheet: the "all" sheet breaks.
    assert counts(result) == (1, 1)


# ---------------------------------------------------------------------------
# What is recorded
# ---------------------------------------------------------------------------


def test_a_failure_names_its_place_and_the_cells_involved(pack: TaxonomyPack) -> None:
    result = run(pack, CAP, t02("0002", "0010", 40), t02("0002", "0020", 50))

    (failure,) = result.failures
    assert failure.place == "sheet 0002"
    assert failure.cells == (f"{T02} r0020 c0010 = 50", f"{T02} r0010 c0010 = 40")


def test_recorded_failures_are_capped_but_every_one_is_counted(pack: TaxonomyPack) -> None:
    # Arrange — each amount must be negative; eight are not.
    negative = rule("negative", f"{ref(T01, c='0010')} < 0", tables=(T01,))
    rows = [t01(row, "0010", 5) for row in ("0010", "0020", "0030")]
    rows += [geo(member, row, 5) for member in ("GB", "FR") for row in ("0010", "0020")]
    everywhere = rule(
        "everywhere",
        f"{ref(T03, c='0010')} < 0 and {ref(T01, '0010', '0010')} < 0",
        tables=(T01, T03),
    )

    # Act
    few = run(pack, negative, *rows)
    many = run(pack, everywhere, *rows, geo("x1", "0010", 5), geo("x1", "0020", 5))

    # Assert
    assert counts(few) == (0, 3) and len(few.failures) == 3
    assert many.unsatisfied == 6 and len(many.failures) == MAX_FAILURES


def test_severity_is_the_modules(pack: TaxonomyPack) -> None:
    soft = rule("soft", TOTAL, tables=(T01,), severities={"TST001": "WARNING"})

    assert run(pack, soft, t01("0010", "0010", 1)).severity == "WARNING"
