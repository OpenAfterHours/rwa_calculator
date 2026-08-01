"""
Evaluation semantics: the four distinctions a submission gate cannot collapse.

Pipeline position:
    Expression + Coordinate + TemplateIndex -> evaluate_at -> CoordinateOutcome

Key responsibilities:
- Missing-value policy. ``treat as zero/empty string`` substitutes 0.0;
  ``do not run rule`` refuses the cell. They give materially different answers
  on the same figures, and the difference is asserted directly.
- Arithmetic approach. ``Interval`` tolerates a rounding-scale delta; ``Point``
  does not. Asserted on ONE delta that separates them.
- Structural absence. A row, column, sheet or template this estate never emitted
  is a skip with a named reason — never a break, and emphatically never 0.0.
  This is the ``v0204_m`` lesson: that rule foots C 02.00 across market,
  operational and settlement risk rows a credit-risk calculator does not produce.
- Vacuity. Operands that are all null or all zero make a comparison VACUOUS, not
  PASS: a vacuous pass is no evidence of correctness.

Why: a false negative in this evaluator is worse than no evaluator, because it
gives false confidence that a return is submittable. Each test below is one way
the machinery could produce one.

References:
- COREP Annex II; PRA PS1/26 Annex II — the templates the coordinates address
"""

from __future__ import annotations

import math

from rwa_calc.reporting.validations.evaluate import (
    SKIP_CELL_NOT_EMITTED,
    SKIP_COLUMN_NOT_EMITTED,
    SKIP_MISSING_VALUE_DO_NOT_RUN,
    SKIP_NON_FINITE_VALUE,
    SKIP_ROW_NOT_EMITTED,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    STATUS_VACUOUS,
    parse_expression,
)
from rwa_calc.reporting.validations.rules import (
    ARITHMETIC_INTERVAL,
    ARITHMETIC_NOT_APPLICABLE,
    ARITHMETIC_POINT,
    MISSING_SKIP,
    MISSING_ZERO,
    load_rules,
)
from rwa_calc.reporting.validations.scope import (
    SKIP_SHEET_NOT_EMITTED,
    Coordinate,
    expand_rule,
)
from tests.unit.reporting.validations._builders import (
    build_frame,
    build_index,
    evaluate,
    evaluate_c02,
)

# A cell reported as blank, against two cells that foot without it.
_ONE_NULL_OPERAND = {"0010": {"0090": 30.0, "0050": 30.0, "0060": None}}

# ---------------------------------------------------------------------------
# Missing-value policy
# ---------------------------------------------------------------------------


def test_treat_as_zero_substitutes_zero_for_an_unreported_cell() -> None:
    """Under ``treat as zero`` a blank cell contributes 0.0 and the rule still runs."""
    # Arrange / Act
    outcome = evaluate_c02(
        "{c0090} = {c0050}+{c0060}", _ONE_NULL_OPERAND, row="0010", missing_value=MISSING_ZERO
    )

    # Assert: 30 = 30 + 0.
    assert (outcome.status, outcome.rhs) == (STATUS_PASS, 30.0)


def test_do_not_run_rule_skips_the_cell_instead_of_zero_filling_it() -> None:
    """Under ``do not run rule`` the SAME data yields a skip, not a verdict.

    Load-bearing: inventing a 0.0 for a cell the publisher did not ask us to
    default turns an unreported figure into an assertion.
    """
    # Arrange / Act
    outcome = evaluate_c02(
        "{c0090} = {c0050}+{c0060}", _ONE_NULL_OPERAND, row="0010", missing_value=MISSING_SKIP
    )

    # Assert
    assert (outcome.status, outcome.reason) == (STATUS_NOT_EVALUATED, SKIP_MISSING_VALUE_DO_NOT_RUN)


def test_the_two_missing_value_policies_disagree_on_the_same_figures() -> None:
    """The policies are not interchangeable — one verdict, one refusal, one dataset."""
    # Arrange
    kwargs = {"row": "0010"}

    # Act
    zero_filled = evaluate_c02(
        "{c0090} = {c0050}+{c0060}", _ONE_NULL_OPERAND, missing_value=MISSING_ZERO, **kwargs
    )
    skipped = evaluate_c02(
        "{c0090} = {c0050}+{c0060}", _ONE_NULL_OPERAND, missing_value=MISSING_SKIP, **kwargs
    )

    # Assert
    assert zero_filled.status != skipped.status


def test_zero_fill_really_substitutes_zero_rather_than_dropping_the_term() -> None:
    """A blank operand under zero-fill BREAKS an identity that needed its value.

    Distinguishes "substitute 0.0" from "ignore this term", which would let a
    missing figure silently satisfy the sum.
    """
    # Arrange: 30 on the left needs 10 + <blank>, so zero-filling must break it.
    cells = {"0010": {"0090": 30.0, "0050": 10.0, "0060": None}}

    # Act
    outcome = evaluate_c02(
        "{c0090} = {c0050}+{c0060}", cells, row="0010", missing_value=MISSING_ZERO
    )

    # Assert
    assert (outcome.status, outcome.rhs) == (STATUS_FAIL, 10.0)


def test_the_empty_literal_ignores_the_missing_value_policy() -> None:
    """``{ref} = empty`` asks whether a cell was REPORTED, so a null is the pass."""
    # Arrange: the cell is blank, under the policy that otherwise refuses nulls.
    cells = {"0010": {"0090": None}}

    # Act
    outcome = evaluate_c02("{c0090} = empty", cells, row="0010", missing_value=MISSING_SKIP)

    # Assert: an unreported cell satisfies the rule (vacuously — nothing was read).
    assert outcome.status == STATUS_VACUOUS


def test_the_empty_literal_breaks_when_the_cell_carries_a_figure() -> None:
    """A reported cell where the rule requires none is a break."""
    # Arrange
    cells = {"0010": {"0090": 3.0}}

    # Act
    outcome = evaluate_c02("{c0090} = empty", cells, row="0010")

    # Assert
    assert outcome.status == STATUS_FAIL


# ---------------------------------------------------------------------------
# Arithmetic approach
# ---------------------------------------------------------------------------

# One delta, chosen to sit inside the golden rounding tolerance at this scale.
_ROUNDING_SCALE_CELLS = {"0010": {"0090": 1_000_000_000.0, "0050": 1_000_000_000.001}}


def test_interval_arithmetic_tolerates_a_rounding_scale_delta() -> None:
    """A rule the publisher declared rounding-tolerant is not broken by float dust."""
    # Arrange / Act
    outcome = evaluate_c02(
        "{c0090} = {c0050}", _ROUNDING_SCALE_CELLS, row="0010", arithmetic=ARITHMETIC_INTERVAL
    )

    # Assert
    assert outcome.status == STATUS_PASS


def test_point_arithmetic_rejects_the_same_delta() -> None:
    """``Point`` compares exactly — the same figures now break."""
    # Arrange / Act
    outcome = evaluate_c02(
        "{c0090} = {c0050}", _ROUNDING_SCALE_CELLS, row="0010", arithmetic=ARITHMETIC_POINT
    )

    # Assert
    assert outcome.status == STATUS_FAIL


def test_not_applicable_arithmetic_takes_the_tolerant_path() -> None:
    """The publisher's marker for "not an arithmetic comparison" must not invent breaks.

    Only ``Point`` compares exactly. That distinction is not biting today — no
    current break has a delta under 1e-3, so nothing in the register is float dust
    — but a future change moving a Point-rule figure by a few ULP would flip it to
    FAIL, and this is where to look when that happens.
    """
    # Arrange / Act
    outcome = evaluate_c02(
        "{c0090} = {c0050}",
        _ROUNDING_SCALE_CELLS,
        row="0010",
        arithmetic=ARITHMETIC_NOT_APPLICABLE,
    )

    # Assert
    assert outcome.status == STATUS_PASS


def test_point_arithmetic_folds_negative_zero_onto_zero() -> None:
    """``-0.0`` and ``0.0`` are the same reported figure, even with no tolerance."""
    # Arrange
    cells = {"0010": {"0090": -0.0, "0050": 0.0}}

    # Act
    outcome = evaluate_c02("{c0090} = {c0050}", cells, row="0010", arithmetic=ARITHMETIC_POINT)

    # Assert: vacuous rather than pass — both operands are zero.
    assert outcome.status == STATUS_VACUOUS


# ---------------------------------------------------------------------------
# Structural absence is not zero
# ---------------------------------------------------------------------------


def test_a_column_this_estate_never_emits_is_skipped_by_name() -> None:
    """An absent column is ``column_not_emitted``, not a break and not a 0.0."""
    # Arrange: 0090 is reported, 9999 is not a column of this template at all.
    cells = {"0010": {"0090": 1.0}}

    # Act
    outcome = evaluate_c02("{c0090} = {c9999}", cells, row="0010")

    # Assert
    assert (outcome.status, outcome.reason) == (STATUS_NOT_EVALUATED, SKIP_COLUMN_NOT_EMITTED)


def test_a_row_this_estate_never_emits_is_skipped_by_name() -> None:
    """An absent row is ``row_not_emitted`` — the structural-gap statement."""
    # Arrange
    cells = {"0010": {"0090": 1.0, "0050": 1.0}}

    # Act: the coordinate names a row the frame does not carry.
    outcome = evaluate_c02("{c0090} = {c0050}", cells, row="9999")

    # Assert
    assert (outcome.status, outcome.reason) == (STATUS_NOT_EVALUATED, SKIP_ROW_NOT_EMITTED)


def test_a_template_this_run_never_produced_is_skipped_by_name() -> None:
    """A reference to an unemitted table is ``cell_not_emitted``, never a break."""
    # Arrange: this run emitted C 02.00 only.
    index = build_index(c_02_00=build_frame({"0010": {"0010": 1.0}}))

    # Act
    outcome = evaluate("{c0010} = {C 08.07, r0010, c0010}", index, row="0010")

    # Assert
    assert (outcome.status, outcome.reason) == (STATUS_NOT_EVALUATED, SKIP_CELL_NOT_EMITTED)


def test_a_sheet_class_this_estate_does_not_produce_is_skipped_by_name() -> None:
    """A z-code addressing an exposure class we never emit is ``sheet_not_emitted``."""
    # Arrange: only corporates emitted; s0007 indexes institutions.
    index = build_index(c07_00={"corporate": build_frame({"0010": {"0010": 5.0}})})

    # Act
    outcome = evaluate(
        "{C 07.00.a, r0010, c0010, s0007} = 5", index, table="C 07.00.a", sheet="corporate"
    )

    # Assert
    assert (outcome.status, outcome.reason) == (STATUS_NOT_EVALUATED, SKIP_SHEET_NOT_EMITTED)


def test_v0204_m_over_unproduced_risk_rows_is_skipped_not_broken() -> None:
    """The canonical case: C 02.00 rows a credit-risk calculator never produces.

    ``v0204_m`` foots total RWEA across the credit, market, operational and
    settlement risk rows. A credit-risk-only estate emits a strict subset, and
    zero-filling the rest would manufacture a break on an otherwise sound return.
    """
    # Arrange: the real rule, against a frame carrying only the credit-risk rows.
    rule = next(r for r in load_rules("CRR").enforced if r.rule_id == "v0204_m")
    index = build_index(c_02_00=build_frame({"0010": {"0010": 800.0}, "0040": {"0010": 800.0}}))
    expression = parse_expression(rule.expression)
    expansion = expand_rule(
        rule,
        index,
        needs_row_axis=expression.needs_row_axis,
        needs_column_axis=expression.needs_column_axis,
    )

    # Act
    outcome = evaluate(
        rule.expression,
        index,
        table=expansion.coordinates[0].table,
        missing_value=rule.missing_value,
        arithmetic=rule.arithmetic,
    )

    # Assert: the identity would hold at 800 = 800 if the absent rows were zeros —
    # the point is that it must refuse to say so.
    assert (outcome.status, outcome.reason) == (STATUS_NOT_EVALUATED, SKIP_ROW_NOT_EMITTED)


def test_a_non_finite_cell_is_skipped_rather_than_compared() -> None:
    """A NaN operand cannot be compared, so the coordinate is refused."""
    # Arrange
    cells = {"0010": {"0090": math.nan, "0050": 1.0}}

    # Act
    outcome = evaluate_c02("{c0090} = {c0050}", cells, row="0010")

    # Assert
    assert (outcome.status, outcome.reason) == (STATUS_NOT_EVALUATED, SKIP_NON_FINITE_VALUE)


# ---------------------------------------------------------------------------
# Vacuity
# ---------------------------------------------------------------------------


def test_all_zero_operands_are_vacuous_not_passing() -> None:
    """0 = 0 is no evidence of correctness, so it is counted separately."""
    # Arrange
    cells = {"0010": {"0090": 0.0, "0050": 0.0}}

    # Act
    outcome = evaluate_c02("{c0090} = {c0050}", cells, row="0010")

    # Assert
    assert outcome.status == STATUS_VACUOUS


def test_all_null_operands_are_vacuous_even_when_zero_filled() -> None:
    """A zero-filled blank is not an observation — it cannot make a rule meaningful."""
    # Arrange
    cells = {"0010": {"0090": None, "0050": None}}

    # Act
    outcome = evaluate_c02("{c0090} = {c0050}", cells, row="0010", missing_value=MISSING_ZERO)

    # Assert
    assert outcome.status == STATUS_VACUOUS


def test_one_non_zero_operand_makes_a_holding_rule_a_real_pass() -> None:
    """A single reported figure is enough to turn vacuity into evidence."""
    # Arrange
    cells = {"0010": {"0090": 7.0, "0050": 7.0}}

    # Act
    outcome = evaluate_c02("{c0090} = {c0050}", cells, row="0010")

    # Assert
    assert outcome.status == STATUS_PASS


def test_a_coordinate_with_no_row_is_described_without_one() -> None:
    """A fully-qualified rule's coordinate has no row/column to name."""
    # Arrange / Act
    described = Coordinate("C 02.00", "__single__", None, None).describe()

    # Assert
    assert described == "C 02.00"
