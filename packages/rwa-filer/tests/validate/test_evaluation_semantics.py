"""
Evaluation semantics: the five distinctions a submission gate cannot collapse.

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
- Nothing reported. Where none of a Bank rule's cells is a fact, the gateway
  does not evaluate the rule unless it is marked "always execute", so a failing
  comparison over zero-filled blanks is a named skip, never a break; a holding
  one stays VACUOUS, and a reported zero is still evaluated. Pinned on the
  packaged boe_b0778, with its EBA twin v09796_m pinned as unchanged.

Why: a false negative in this evaluator is worse than no evaluator, because it
gives false confidence that a return is submittable. Each test below is one way
the machinery could produce one.

References:
- COREP Annex II; PRA PS1/26 Annex II — the templates the coordinates address
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from filer_builders import (
    build_frame,
    build_index,
    evaluate,
    evaluate_c02,
)
from rwa_filer.rules.catalogue import (
    ARITHMETIC_INTERVAL,
    ARITHMETIC_NOT_APPLICABLE,
    ARITHMETIC_POINT,
    FRAMEWORK_BASEL_3_1,
    FRAMEWORK_CRR,
    MISSING_SKIP,
    MISSING_ZERO,
    RuleSet,
    load_rules,
)
from rwa_filer.validate.checker import evaluate_index
from rwa_filer.validate.evaluate import (
    SKIP_CELL_NOT_EMITTED,
    SKIP_COLUMN_NOT_EMITTED,
    SKIP_MISSING_VALUE_DO_NOT_RUN,
    SKIP_NON_FINITE_VALUE,
    SKIP_NOTHING_REPORTED,
    SKIP_ROW_NOT_EMITTED,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    STATUS_VACUOUS,
    evaluate_at,
    parse_expression,
)
from rwa_filer.validate.index import (
    SINGLE_SHEET,
    SKIP_SHEET_NOT_EMITTED,
    Coordinate,
    expand_rule,
)

if TYPE_CHECKING:
    from filer_builders import Cells
    from rwa_filer.validate.checker import RuleOutcome
    from rwa_filer.validate.evaluate import CoordinateOutcome

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


def test_a_sum_over_a_sheet_the_summed_table_does_not_carry_is_skipped_not_widened() -> None:
    """A sum with no sheet of its own reads the sheet the rule is evaluated on.

    ``boe_b0752_*`` compare OF 08.01 row 0070 on one sheet with the sum of the
    same column of OF 08.02 on THAT sheet. Where OF 08.02 does not carry the
    sheet (it excludes slotting, so the FIRB-and-slotting sheet can be absent),
    the sum has nothing to read. It used to fall back to every OF 08.02 sheet and
    compare one sheet's total with the whole template's.
    """
    # Arrange — OF 08.01 has the institutions sheet; OF 08.02 only corporates.
    index = build_index(
        FRAMEWORK_BASEL_3_1,
        c08_01={"institution": build_frame({"0070": {"0110": 5.0}})},
        c08_02={"corporate": build_frame({"grade_1": {"0110": 99.0}})},
    )

    # Act
    outcome = evaluate(
        "{OF08.01.01.01, r0070, c0110} = sum({OF08.02.01.01, c0110})",
        index,
        table="OF08.01.01.01",
        sheet="institution",
    )

    # Assert
    assert (outcome.status, outcome.reason) == (STATUS_NOT_EVALUATED, SKIP_SHEET_NOT_EMITTED)


def test_a_sum_with_no_sheet_context_still_spans_every_sheet() -> None:
    """The fallback the fix keeps: a rule on a single-sheet template summing a
    per-sheet one has no sheet to follow, so it reads them all."""
    # Arrange
    index = build_index(
        FRAMEWORK_BASEL_3_1,
        of_02_01=build_frame({"0010": {"0010": 104.0}}),
        c08_02={
            "corporate": build_frame({"grade_1": {"0110": 99.0}}),
            "institution": build_frame({"grade_1": {"0110": 5.0}}),
        },
    )

    # Act
    outcome = evaluate(
        "{OF02.01.01.01, r0010, c0010} = sum({OF08.02.01.01, c0110})",
        index,
        table="OF02.01.01.01",
    )

    # Assert
    assert (outcome.status, outcome.rhs) == (STATUS_PASS, 104.0)


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


# ---------------------------------------------------------------------------
# Nothing reported
# ---------------------------------------------------------------------------
#
# These run the PACKAGED rules through ``evaluate_index``, so each one fails on
# an assertion about the published rule rather than on a hand-built stand-in.
# boe_b0778 reads ``isum({t: OF08.07.01.01, c: 0030; 0040; 0050, dv:
# emptySequence(), seq: True}) i= 1`` over rows 0180-0260 and is not marked
# "always execute". Its reference carries a default, so the engine zero-fills an
# unreported share; the guard is what stops that zero being compared with 1.


def _packaged_rule_outcome(framework: str, rule_id: str, cells: Cells) -> RuleOutcome:
    """Run one packaged rule over a single-sheet roll-out table built from ``cells``."""
    rules = load_rules(framework)
    rule = next(rule for rule in rules.enforced if rule.rule_id == rule_id)
    ruleset = RuleSet(framework=framework, publisher=rules.publisher, source={}, rules=(rule,))
    index = build_index(framework, c08_07=build_frame(cells))
    return evaluate_index(index, ruleset).outcomes[0]


def _shares(*shares: float | None) -> dict[str, float | None]:
    """One roll-out row's three share columns (0030 / 0040 / 0050)."""
    return dict(zip(("0030", "0040", "0050"), shares, strict=True))


def test_boe_b0778_is_not_broken_on_a_roll_out_class_that_reports_no_share() -> None:
    """A class with no exposure reports no share, so the Bank's rule has nothing to test there.

    The gateway evaluates boe_b0778 only where one of its three share cells is
    a fact. Row 0180 reports none of them: it is not an evaluation, and reading
    it as 0 + 0 + 0 against 1 is a break the gateway never raises.
    """
    # Arrange: one class with no share reported, one class and the total at 100 / 0 / 0.
    cells = {
        "0180": _shares(None, None, None),
        "0210": _shares(1.0, 0.0, 0.0),
        "0260": _shares(1.0, 0.0, 0.0),
    }

    # Act
    outcome = _packaged_rule_outcome(FRAMEWORK_BASEL_3_1, "boe_b0778", cells)

    # Assert: the two reported rows are evaluated and hold; the empty one is not counted.
    assert (outcome.status, outcome.passed, outcome.failed) == (STATUS_PASS, 2, 0)


def test_boe_b0778_records_the_empty_row_as_skipped_rather_than_dropping_it() -> None:
    """The row the guard leaves out is still counted, as a skip, never silently absent."""
    # Arrange
    cells = {"0180": _shares(None, None, None), "0210": _shares(1.0, 0.0, 0.0)}

    # Act
    outcome = _packaged_rule_outcome(FRAMEWORK_BASEL_3_1, "boe_b0778", cells)

    # Assert
    assert (outcome.evaluated, outcome.skipped) == (1, 1)


def test_boe_b0778_still_breaks_where_the_reported_shares_do_not_total_one() -> None:
    """The control: a real break survives the guard, and the empty row is not a second one."""
    # Arrange
    cells = {
        "0180": _shares(None, None, None),
        "0210": _shares(0.5, 0.2, 0.2),
        "0260": _shares(1.0, 0.0, 0.0),
    }

    # Act
    outcome = _packaged_rule_outcome(FRAMEWORK_BASEL_3_1, "boe_b0778", cells)

    # Assert
    assert (outcome.status, outcome.passed, outcome.failed) == (STATUS_FAIL, 1, 1)


def test_boe_b0778_is_evaluated_on_a_row_that_reports_zero_shares() -> None:
    """A reported 0.0 is a fact: the guard keys on REPORTED, not on non-zero.

    Pins the guard against being widened to "every operand is zero", which
    would let a return that reports 0 / 0 / 0 for a class with exposure pass.
    """
    # Arrange
    cells = {"0180": _shares(0.0, 0.0, 0.0), "0210": _shares(1.0, 0.0, 0.0)}

    # Act
    outcome = _packaged_rule_outcome(FRAMEWORK_BASEL_3_1, "boe_b0778", cells)

    # Assert
    assert (outcome.status, outcome.passed, outcome.failed) == (STATUS_FAIL, 1, 1)


def test_the_eba_twin_v09796_m_keeps_its_treat_as_zero_reading_under_crr() -> None:
    """CRR is deliberately unchanged: the EBA publishes no "always execute" column.

    v09796_m (``{c0030} + {c0040} + {c0050} = 1``, treat as zero) is the same
    check on C 08.07. Whether the EBA runs it where no share is reported is not
    settled by the EBA's own workbook, and no EBA taxonomy package is held to
    measure it, so every EBA rule keeps ``always_execute`` and this row still
    breaks. Change it only with that evidence.
    """
    # Arrange
    cells = {"0010": _shares(None, None, None), "0020": _shares(1.0, 0.0, 0.0)}

    # Act
    outcome = _packaged_rule_outcome(FRAMEWORK_CRR, "v09796_m", cells)

    # Assert
    assert (outcome.status, outcome.passed, outcome.failed) == (STATUS_FAIL, 1, 1)


def _evaluate_on_blanks(expression: str, *, always_execute: bool) -> CoordinateOutcome:
    """Evaluate ``expression`` on C 02.00 row 0010, where 0090 and 0050 are reported blank."""
    return evaluate_at(
        parse_expression(expression),
        Coordinate("C 02.00", SINGLE_SHEET, "0010", None),
        build_index(c_02_00=build_frame({"0010": {"0090": None, "0050": None}})),
        missing_value=MISSING_ZERO,
        arithmetic=ARITHMETIC_INTERVAL,
        always_execute=always_execute,
    )


def test_an_unreported_place_that_fails_is_skipped_as_nothing_reported() -> None:
    """At coordinate level the place left out carries its own reason, not a generic skip."""
    # Arrange / Act: ``0 = 1`` over a blank, on a rule that is not always-execute.
    outcome = _evaluate_on_blanks("{c0090} = 1", always_execute=False)

    # Assert
    assert (outcome.status, outcome.reason) == (STATUS_NOT_EVALUATED, SKIP_NOTHING_REPORTED)


def test_an_unreported_place_that_holds_stays_vacuous_under_the_guard() -> None:
    """The guard only removes a FAILING empty place; one that holds is still VACUOUS.

    The vacuity count is what the dead-cell defence reads, so a comparison over
    unreported cells that holds must keep reporting as VACUOUS rather than vanish.
    """
    # Arrange / Act: ``0 = 0`` over two blanks, on a rule that is not always-execute.
    outcome = _evaluate_on_blanks("{c0090} = {c0050}", always_execute=False)

    # Assert
    assert outcome.status == STATUS_VACUOUS


def test_an_always_execute_rule_still_breaks_where_nothing_is_reported() -> None:
    """A rule the publisher runs regardless keeps its zero-filled break."""
    # Arrange / Act
    outcome = _evaluate_on_blanks("{c0090} = 1", always_execute=True)

    # Assert
    assert outcome.status == STATUS_FAIL
