"""
Grammar of the supervisory validation-rule expression parser.

Pipeline position:
    publisher formula -> parse_expression -> Expression -> evaluate_at

Key responsibilities:
- Pin every reference form BOTH publishers actually write: the EBA
  ``{C 08.01.a, r0070, c0020}`` / ``{c0090}`` / ``(s0003-0004)`` shapes and the
  BoE ``{t: …, r: …, c: …, z: …}`` keyed shape, plus the whole-table ``{t: T}``
  reference whose axes come entirely from the rule's scope.
- Pin the arithmetic surface: ``+ - * /``, percentage literals, parentheses,
  ``abs`` / ``sum`` / ``max`` / ``min``, leading unary sign, and every
  comparison operator.
- Pin the AXIS FACTS the parser reports (``needs_row_axis`` /
  ``needs_column_axis``), because scope expansion decides what to iterate from
  them: get one wrong and a rule is evaluated at the wrong cells.

Why the figures are trivial: a false negative here is a rule that silently
holds on a broken return, so every expected value is one a reader can check
without running anything.

References:
- docs/reference/validation-rules/index.md — the formula grammar for both sources
"""

from __future__ import annotations

import pytest

from rwa_calc.reporting.validations.evaluate import (
    SKIP_UNSUPPORTED_GRAMMAR,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    UnsupportedExpression,
    parse_expression,
)
from rwa_calc.reporting.validations.rules import ARITHMETIC_POINT
from tests.unit.reporting.validations._builders import (
    build_frame,
    build_index,
    evaluate,
    evaluate_c02,
)

# ---------------------------------------------------------------------------
# EBA reference forms
# ---------------------------------------------------------------------------


def test_column_only_refs_take_their_row_from_the_coordinate() -> None:
    """``{c0090} = {c0050}+{c0060}`` reads three columns of the coordinate's row."""
    # Arrange: one row whose 0090 is exactly the sum of 0050 and 0060.
    cells = {"0010": {"0090": 30.0, "0050": 10.0, "0060": 20.0}}

    # Act
    outcome = evaluate_c02("{c0090} = {c0050}+{c0060}", cells, row="0010")

    # Assert
    assert (outcome.status, outcome.lhs, outcome.rhs) == (STATUS_PASS, 30.0, 30.0)


def test_row_only_refs_take_their_column_from_the_coordinate() -> None:
    """``{r0010} = {r0070}+{r0080}`` reads three rows of the coordinate's column."""
    # Arrange: column 0010 down three rows, the first footing the other two.
    cells = {
        "0010": {"0010": 30.0},
        "0070": {"0010": 10.0},
        "0080": {"0010": 20.0},
    }

    # Act
    outcome = evaluate_c02("{r0010} = {r0070}+{r0080}", cells, column="0010")

    # Assert
    assert (outcome.status, outcome.lhs, outcome.rhs) == (STATUS_PASS, 30.0, 30.0)


@pytest.mark.parametrize(
    ("shape", "formula", "expected"),
    [
        ("row-scoped", "{c0090} = {c0050}+{c0060}", (True, False)),
        ("column-scoped", "{r0010} = {r0070}+{r0080}", (False, True)),
        ("fully qualified", "{r0140, c0215} = 0", (False, False)),
        ("whole-table sign", "{C 07.00.a} >= 0", (True, True)),
    ],
)
def test_the_axis_inference_reports_which_axis_is_the_loop(
    shape: str, formula: str, expected: tuple[bool, bool]
) -> None:
    """Which axis the rule ITERATES vs which its formula addresses.

    The subtlest inference in the module, and scope expansion is built entirely
    on it: report the wrong axis and the rule is evaluated at the wrong cells,
    which looks like a finding rather than an error. All four published shapes are
    pinned together so none can drift alone.
    """
    # Arrange / Act
    expression = parse_expression(formula)

    # Assert
    assert (expression.needs_row_axis, expression.needs_column_axis) == expected, shape


def test_percentage_literal_is_divided_out() -> None:
    """``* 2%`` multiplies by 0.02, not by 2."""
    # Arrange: 200 * 2% = 4.
    cells = {"0150": {"0215": 4.0, "0200": 200.0}}

    # Act
    outcome = evaluate_c02("{r0150, c0215} = {r0150, c0200} * 2%", cells)

    # Assert
    assert (outcome.status, outcome.rhs) == (STATUS_PASS, 4.0)


def test_cross_table_refs_read_each_named_table() -> None:
    """``{C 07.00.a, c0200} = {C 07.00.b, c0210}`` addresses two table codes."""
    # Arrange: the DPM splits C 07.00 a/b as column partitions of ONE frame.
    index = build_index(c07_00={"corporate": build_frame({"0010": {"0200": 7.0, "0210": 7.0}})})

    # Act
    outcome = evaluate(
        "{C 07.00.a, c0200} = {C 07.00.b, c0210}",
        index,
        table="C 07.00.a",
        sheet="corporate",
        row="0010",
    )

    # Assert
    assert (outcome.status, outcome.lhs, outcome.rhs) == (STATUS_PASS, 7.0, 7.0)


def test_sheet_range_sums_every_sheet_it_spans() -> None:
    """``(s0003-0004)`` expands to both codes and sums the sheets they map to."""
    # Arrange: C 08.01 codes 0003 (F-IRB) and 0004 (A-IRB) both map to sovereigns.
    index = build_index(c08_01={"central_govt_central_bank": build_frame({"0010": {"0010": 9.0}})})

    # Act
    outcome = evaluate(
        "{C 08.01.a, r0010, c0010, (s0003-0004)} = 9",
        index,
        table="C 08.01.a",
        sheet="central_govt_central_bank",
    )

    # Assert: one emitted sheet behind two codes contributes once.
    assert (outcome.status, outcome.lhs) == (STATUS_PASS, 9.0)


# ---------------------------------------------------------------------------
# BoE reference forms
# ---------------------------------------------------------------------------


def test_boe_keyed_reference_form_resolves_all_four_axes() -> None:
    """``{t: …, r: …, c: …, z: …}`` binds table, row, column and sheet."""
    # Arrange: OF 07.00 z:0002 is Art. 112(1)(a) central governments.
    index = build_index(
        "BASEL_3_1",
        c07_00={"central_govt_central_bank": build_frame({"0140": {"0220": 12.0}})},
    )

    # Act
    outcome = evaluate(
        "{t: OF07.00.01.01, r: 0140, c: 0220, z: 0002} = 12",
        index,
        table="OF07.00.01.01",
        sheet="central_govt_central_bank",
    )

    # Assert
    assert (outcome.status, outcome.lhs) == (STATUS_PASS, 12.0)


def test_boe_multi_valued_axis_sums_the_listed_ids() -> None:
    """``r: 0010; 0020`` is one reference spanning two rows, summed."""
    # Arrange
    index = build_index(
        "BASEL_3_1",
        c07_00={"corporate": build_frame({"0010": {"0010": 4.0}, "0020": {"0010": 6.0}})},
    )

    # Act
    outcome = evaluate(
        "{t: OF07.00.01.01, r: 0010; 0020, c: 0010} = 10",
        index,
        table="OF07.00.01.01",
        sheet="corporate",
    )

    # Assert
    assert (outcome.status, outcome.lhs) == (STATUS_PASS, 10.0)


def test_whole_table_reference_takes_both_axes_from_the_rules_scope() -> None:
    """``{t: T} = 0`` carries no axis of its own — both must be iterated."""
    # Arrange / Act
    expression = parse_expression("{t: OF07.00.01.01} = 0")

    # Assert: the scope, not the formula, supplies the row and column.
    assert (expression.needs_row_axis, expression.needs_column_axis) == (True, True)


def test_whole_table_reference_evaluates_at_the_scoped_coordinate() -> None:
    """A whole-table reference reads the single cell the coordinate names."""
    # Arrange: the 0% risk-weight row must carry a zero RWEA.
    index = build_index("BASEL_3_1", c07_00={"corporate": build_frame({"0140": {"0220": 3.0}})})

    # Act
    outcome = evaluate(
        "{t: OF07.00.01.01} = 0",
        index,
        table="OF07.00.01.01",
        sheet="corporate",
        row="0140",
        column="0220",
    )

    # Assert
    assert (outcome.status, outcome.lhs, outcome.rhs) == (STATUS_FAIL, 3.0, 0.0)


# ---------------------------------------------------------------------------
# Arithmetic and comparison surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("operator", "lhs", "rhs", "expected"),
    [
        ("=", 5.0, 5.0, STATUS_PASS),
        ("=", 5.0, 4.0, STATUS_FAIL),
        (">=", 5.0, 5.0, STATUS_PASS),
        (">=", 4.0, 5.0, STATUS_FAIL),
        ("<=", 5.0, 5.0, STATUS_PASS),
        ("<=", 6.0, 5.0, STATUS_FAIL),
        (">", 6.0, 5.0, STATUS_PASS),
        (">", 4.0, 5.0, STATUS_FAIL),
        ("<", 4.0, 5.0, STATUS_PASS),
        ("<", 6.0, 5.0, STATUS_FAIL),
    ],
)
def test_comparison_operators_hold_both_ways(
    operator: str, lhs: float, rhs: float, expected: str
) -> None:
    """Every operator the publishers use passes and fails on the right side of the line."""
    # Arrange
    cells = {"0010": {"0010": lhs, "0020": rhs}}

    # Act
    outcome = evaluate_c02(f"{{c0010}} {operator} {{c0020}}", cells, row="0010")

    # Assert
    assert outcome.status == expected


@pytest.mark.parametrize("operator", [">", "<"])
def test_strict_inequality_on_an_exact_tie_passes_under_interval_arithmetic(
    operator: str,
) -> None:
    """A STRICT comparison of two equal figures passes when the rule is interval-typed.

    Recorded, not incidental: ``Interval`` widens the passing region by the
    rounding tolerance in the direction of the operator, so ``a > b`` holds at
    ``a == b``. No currently-enforced rule in either extract uses a bare ``>`` or
    ``<`` (both populations are ``=``/``==``/``>=``/``<=`` only), so this is
    latent — but a future taxonomy adding one would get a tie waved through.
    """
    # Arrange: an exact tie, which no rounding could explain away.
    cells = {"0010": {"0010": 5.0, "0020": 5.0}}

    # Act
    outcome = evaluate_c02(f"{{c0010}} {operator} {{c0020}}", cells, row="0010")

    # Assert
    assert outcome.status == STATUS_PASS


@pytest.mark.parametrize("operator", [">", "<"])
def test_strict_inequality_on_an_exact_tie_fails_under_point_arithmetic(
    operator: str,
) -> None:
    """With no tolerance the same tie breaks — the contrast that isolates the cause."""
    # Arrange
    cells = {"0010": {"0010": 5.0, "0020": 5.0}}

    # Act
    outcome = evaluate_c02(
        f"{{c0010}} {operator} {{c0020}}", cells, row="0010", arithmetic=ARITHMETIC_POINT
    )

    # Assert
    assert outcome.status == STATUS_FAIL


def test_leading_unary_plus_is_a_no_op() -> None:
    """The EBA writes ``+{ref}`` at the head of a sum; the sign must not change."""
    # Arrange
    cells = {"0010": {"0010": 4.0, "0020": 4.0}}

    # Act
    outcome = evaluate_c02("+{c0010} = {c0020}", cells, row="0010")

    # Assert
    assert (outcome.status, outcome.lhs) == (STATUS_PASS, 4.0)


def test_leading_unary_minus_negates() -> None:
    """``-{ref}`` negates, so it can never be confused with the no-op ``+``."""
    # Arrange
    cells = {"0010": {"0010": 4.0, "0020": -4.0}}

    # Act
    outcome = evaluate_c02("-{c0010} = {c0020}", cells, row="0010")

    # Assert
    assert (outcome.status, outcome.lhs) == (STATUS_PASS, -4.0)


def test_abs_folds_a_negative_operand() -> None:
    """``abs({c0090}) <= {c0040}`` compares magnitude, not signed value."""
    # Arrange: -5 breaks the bare comparison but holds under abs().
    cells = {"0010": {"0090": -5.0, "0040": 7.0}}

    # Act
    outcome = evaluate_c02("abs({c0090}) <= {c0040}", cells, row="0010")

    # Assert
    assert (outcome.status, outcome.lhs) == (STATUS_PASS, 5.0)


def test_parentheses_override_operator_precedence() -> None:
    """``({a}+{b})*2`` is not ``{a}+({b}*2)``."""
    # Arrange: (1+2)*2 = 6, whereas 1+(2*2) = 5.
    cells = {"0010": {"0010": 1.0, "0020": 2.0, "0030": 6.0}}

    # Act
    outcome = evaluate_c02("{c0030} = ({c0010}+{c0020})*2", cells, row="0010")

    # Assert
    assert (outcome.status, outcome.rhs) == (STATUS_PASS, 6.0)


def test_division_precedes_addition() -> None:
    """``{a} + {b}/{c}`` divides before it adds."""
    # Arrange: 1 + 6/2 = 4.
    cells = {"0010": {"0010": 1.0, "0020": 6.0, "0030": 2.0, "0040": 4.0}}

    # Act
    outcome = evaluate_c02("{c0040} = {c0010} + {c0020}/{c0030}", cells, row="0010")

    # Assert
    assert outcome.status == STATUS_PASS


def test_sum_expands_an_unbound_axis_over_every_emitted_id() -> None:
    """``sum({c0010})`` sums the column down every emitted row."""
    # Arrange: two rows in column 0010 (10 + 20), totalled in 0020.
    cells = {
        "0010": {"0010": 10.0, "0020": 30.0},
        "0020": {"0010": 20.0, "0020": None},
    }

    # Act: the outer reference is fully qualified, so no axis is bound.
    outcome = evaluate_c02("{r0010, c0020} = sum({c0010})", cells)

    # Assert
    assert (outcome.status, outcome.rhs) == (STATUS_PASS, 30.0)


def test_a_bound_coordinate_axis_wins_over_aggregate_expansion() -> None:
    """Inside ``sum(...)``, an axis the COORDINATE fixes is not expanded.

    Recorded, not incidental. The module's own comment says a reference inside an
    aggregate "expands its own unbound axes", but the resolver consults the
    current coordinate first, so an aggregate collapses to one cell whenever the
    rule's grid happens to iterate that axis. Every ``sum(...)`` in both
    enforced extracts qualifies its inner reference fully (``r:``/``c:``/``z:``
    all given), so nothing reachable today depends on the expansion — but a rule
    combining an unqualified aggregate with a scoped axis would silently sum one
    cell instead of the column.
    """
    # Arrange: the same two rows as above.
    cells = {
        "0010": {"0010": 10.0, "0020": 30.0},
        "0020": {"0010": 20.0, "0020": None},
    }

    # Act: binding the row on the coordinate collapses the aggregate to that row.
    outcome = evaluate_c02("{r0010, c0020} = sum({c0010})", cells, row="0010")

    # Assert: 10, not the 30 the same expression sums with an unbound coordinate.
    assert (outcome.status, outcome.rhs) == (STATUS_FAIL, 10.0)


def test_max_selects_the_largest_individual_cell() -> None:
    """``max(...)`` ranges over cells, not over the summed reference."""
    # Arrange
    cells = {"0010": {"0010": 10.0}, "0020": {"0010": 20.0}}

    # Act
    outcome = evaluate_c02("{r0020, c0010} = max({c0010})", cells, row="0020")

    # Assert
    assert (outcome.status, outcome.rhs) == (STATUS_PASS, 20.0)


def test_min_selects_the_smallest_individual_cell() -> None:
    """``min(...)`` is the mirror of ``max`` — pinned so the two cannot swap."""
    # Arrange
    cells = {"0010": {"0010": 10.0}, "0020": {"0010": 20.0}}

    # Act
    outcome = evaluate_c02("{r0010, c0010} = min({c0010})", cells, row="0010")

    # Assert
    assert (outcome.status, outcome.rhs) == (STATUS_PASS, 10.0)


def test_division_by_zero_is_skipped_not_reported_as_a_break() -> None:
    """A zero denominator makes the cell unevaluable, never a failure."""
    # Arrange
    cells = {"0010": {"0010": 1.0, "0020": 0.0, "0030": 5.0}}

    # Act
    outcome = evaluate_c02("{c0030} = {c0010}/{c0020}", cells, row="0010")

    # Assert
    assert outcome.status == STATUS_NOT_EVALUATED


# ---------------------------------------------------------------------------
# Refusals — every unsupported construct is named, never approximated
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "why"),
    [
        ("if {c0010} > 0 then {c0020} = 1", "conditional"),
        ("{c0010} = count({c0020})", "count aggregate"),
        ("{c0010} = 1 and {c0020} = 2", "boolean conjunction"),
        ("{c0010} = 1 or {c0020} = 2", "boolean disjunction"),
        ("isnull({c0010})", "null predicate"),
        ("{C 08.02, rNNN, c0010} = 0", "open-row wildcard"),
        ("{c0010} = {c0020} & 1", "untokenisable character"),
        ("{c0010}", "no top-level comparison"),
        ("{c0010} =", "truncated expression"),
        ("{} = 0", "empty reference"),
        ("{c0010} = {c0020} {c0030}", "trailing tokens"),
        ("{c0010} = round({c0020})", "unknown function"),
    ],
)
def test_unsupported_constructs_are_refused_by_name(expression: str, why: str) -> None:
    """An unsupported formula raises with a reason, so it can be recorded as a skip.

    Approximating any of these would produce findings that look authoritative and
    are not — the refusal is the feature.
    """
    # Arrange / Act
    with pytest.raises(UnsupportedExpression) as raised:
        parse_expression(expression)

    # Assert
    assert raised.value.reason == SKIP_UNSUPPORTED_GRAMMAR, why


def test_an_absent_formula_is_refused_rather_than_treated_as_holding() -> None:
    """A rule carrying no formula must not evaluate as a silent pass."""
    # Arrange / Act
    with pytest.raises(UnsupportedExpression) as raised:
        parse_expression(None)

    # Assert
    assert raised.value.reason != ""
