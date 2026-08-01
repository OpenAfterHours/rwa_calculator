"""
Scope expansion: which cells a rule is actually evaluated at.

Pipeline position:
    ValidationRule + TemplateIndex -> expand_rule -> [Coordinate] | skip reason

Key responsibilities:
- Pin the publisher doctrine that the SCOPED axis is the loop: a row-scoped rule
  fires once per listed row, a column-scoped one once per column, and a rule
  scoping neither while addressing neither runs over rows x columns.
- Pin the BoE ``scope(...)`` binding as a first-class source of axes — the
  ``boe_b0529`` shape, whose expression is the bare ``{t: OF07.00.01.01} = 0``
  and whose row, column and sheet all live in the scope expression.
- Pin every refusal path by name. A scoped row, column, sheet or table this
  estate never emitted must empty the grid with a diagnostic reason, so a
  structural gap can never be read as an arithmetic assertion.
- Pin sheet-map closure: our sheets are in places a COARSER partition than the
  publisher's z-axis, so a scoped subset is only safe when the code set is
  CLOSED under the mapping.

References:
- CRR Art. 112(1)(a)-(q); COREP Annex II §3.3.2 — the indexed exposure classes
- PRA PS1/26 Annex II OF 07.00 / OF 09.01
"""

from __future__ import annotations

import pytest

from rwa_calc.reporting.validations.rules import (
    SCOPE_ALL,
    SCOPE_LIST,
    RuleScope,
    TableScope,
    load_rules,
)
from rwa_calc.reporting.validations.scope import (
    SHEET_INDEX_MAPS,
    SINGLE_SHEET,
    SKIP_COLUMN_NOT_EMITTED,
    SKIP_PREREQUISITE_TABLE_ABSENT,
    SKIP_ROW_NOT_EMITTED,
    SKIP_SHEET_INDEX_MAP_UNKNOWN,
    SKIP_SHEET_NOT_EMITTED,
    SKIP_SHEET_SCOPE_NOT_CLOSED,
    SKIP_TABLE_NOT_EMITTED,
    build_template_index,
    expand_rule,
    resolve_sheet_codes,
)
from tests.unit.reporting.validations._builders import (
    build_corep,
    build_frame,
    build_index,
    build_rule,
)

# A two-row, two-column C 02.00 — small enough that every expansion is countable.
_TWO_BY_TWO = {
    "0010": {"0010": 1.0, "0020": 2.0},
    "0020": {"0010": 3.0, "0020": 4.0},
}


def _c02_index():
    """Index carrying only the two-by-two C 02.00 frame."""
    return build_index(c_02_00=build_frame(_TWO_BY_TWO))


def _expand(rule, index, *, rows: bool = False, columns: bool = False):
    """Expand a rule, spelling the two axis facts the parser would supply."""
    return expand_rule(rule, index, needs_row_axis=rows, needs_column_axis=columns)


# ---------------------------------------------------------------------------
# The scoped axis is the loop
# ---------------------------------------------------------------------------


def test_a_row_scoped_rule_fires_once_per_listed_row() -> None:
    """Row scope ``0010;0020`` produces two coordinates, one per row."""
    # Arrange
    rule = build_rule(
        table_scopes=(TableScope("C 02.00", rows=RuleScope(SCOPE_LIST, ("0010", "0020"))),)
    )

    # Act
    expansion = _expand(rule, _c02_index())

    # Assert
    assert [c.row for c in expansion.coordinates] == ["0010", "0020"]


def test_a_column_scoped_rule_fires_once_per_listed_column() -> None:
    """Column scope produces one coordinate per column, with no row bound."""
    # Arrange
    rule = build_rule(
        table_scopes=(TableScope("C 02.00", columns=RuleScope(SCOPE_LIST, ("0010", "0020"))),)
    )

    # Act
    expansion = _expand(rule, _c02_index())

    # Assert
    assert [(c.row, c.column) for c in expansion.coordinates] == [
        (None, "0010"),
        (None, "0020"),
    ]


def test_a_whole_table_rule_runs_over_rows_times_columns() -> None:
    """A rule addressing neither axis iterates the full emitted grid."""
    # Arrange: the ``{t: T} = 0`` shape — both axes must be supplied.
    rule = build_rule()

    # Act
    expansion = _expand(rule, _c02_index(), rows=True, columns=True)

    # Assert
    assert [c.describe() for c in expansion.coordinates] == [
        "C 02.00[r0010][c0010]",
        "C 02.00[r0010][c0020]",
        "C 02.00[r0020][c0010]",
        "C 02.00[r0020][c0020]",
    ]


def test_the_literal_all_scope_expands_to_every_emitted_id() -> None:
    """``(All)`` means every row the frame carries, not a fixed regulatory list."""
    # Arrange
    rule = build_rule(table_scopes=(TableScope("C 02.00", rows=RuleScope(SCOPE_ALL, ())),))

    # Act
    expansion = _expand(rule, _c02_index())

    # Assert
    assert [c.row for c in expansion.coordinates] == ["0010", "0020"]


def test_a_fully_qualified_rule_yields_one_unbound_coordinate() -> None:
    """When the formula addresses both axes there is nothing to iterate."""
    # Arrange
    rule = build_rule()

    # Act
    expansion = _expand(rule, _c02_index())

    # Assert
    assert [(c.row, c.column) for c in expansion.coordinates] == [(None, None)]


# ---------------------------------------------------------------------------
# The BoE scope expression as a source of axes
# ---------------------------------------------------------------------------


def test_the_boe_scope_supplies_the_axes_its_expression_omits() -> None:
    """``boe_b0529``: expression ``{t: OF07.00.01.01} = 0``, axes from ``scope``.

    The canonical case for the BoE shape — row 0140 (the 0% risk-weight band),
    column 0220 (RWEA) and a 16-code z-list all live in the scope expression, so
    an evaluator reading only the formula would have no coordinate at all.
    """
    # Arrange: three SA classes emitted, of the sixteen the rule scopes.
    rule = next(r for r in load_rules("BASEL_3_1").enforced if r.rule_id == "boe_b0529")
    sheet = build_frame({"0140": {"0220": 0.0}})
    index = build_index(
        "BASEL_3_1",
        c07_00={"corporate": sheet, "institution": sheet, "retail_qrre": sheet},
    )

    # Act
    expansion = _expand(rule, index, rows=True, columns=True)

    # Assert: one coordinate per emitted sheet, each at r0140/c0220.
    assert [c.describe() for c in expansion.coordinates] == [
        "OF07.00.01.01[institution][r0140][c0220]",
        "OF07.00.01.01[corporate][r0140][c0220]",
        "OF07.00.01.01[retail_qrre][r0140][c0220]",
    ]


def test_an_unscoped_sheet_axis_means_every_emitted_sheet() -> None:
    """A blank z-scope is "holds on each sheet", never "the total sheet"."""
    # Arrange: our estate emits no total sheet at all.
    rule = build_rule(tables=("C 07.00.a",))
    index = build_index(
        c07_00={
            "corporate": build_frame({"0010": {"0010": 1.0}}),
            "institution": build_frame({"0010": {"0010": 2.0}}),
        }
    )

    # Act
    expansion = _expand(rule, index)

    # Assert
    assert [c.sheet for c in expansion.coordinates] == ["corporate", "institution"]


def test_a_flat_template_expands_to_the_single_sheet_sentinel() -> None:
    """A template with no z-axis carries one nameless sheet."""
    # Arrange / Act
    expansion = _expand(build_rule(), _c02_index())

    # Assert
    assert [c.sheet for c in expansion.coordinates] == [SINGLE_SHEET]


# ---------------------------------------------------------------------------
# Structural absence empties the grid with a named reason
# ---------------------------------------------------------------------------


def test_a_scoped_row_this_estate_never_emits_is_dropped_not_zero_filled() -> None:
    """A scoped row absent from the frame empties the grid as ``row_not_emitted``."""
    # Arrange
    rule = build_rule(table_scopes=(TableScope("C 02.00", rows=RuleScope(SCOPE_LIST, ("9999",))),))

    # Act
    expansion = _expand(rule, _c02_index())

    # Assert
    assert (expansion.coordinates, expansion.skip_reason) == ((), SKIP_ROW_NOT_EMITTED)


def test_a_scoped_column_this_estate_never_emits_is_dropped_not_zero_filled() -> None:
    """The column mirror — usually a framework-variant gap rather than scope."""
    # Arrange
    rule = build_rule(
        table_scopes=(TableScope("C 02.00", columns=RuleScope(SCOPE_LIST, ("9999",))),)
    )

    # Act
    expansion = _expand(rule, _c02_index())

    # Assert
    assert (expansion.coordinates, expansion.skip_reason) == ((), SKIP_COLUMN_NOT_EMITTED)


def test_a_partially_emitted_row_scope_keeps_only_the_emitted_rows() -> None:
    """A scope listing one emitted and one absent row evaluates only the emitted one."""
    # Arrange
    rule = build_rule(
        table_scopes=(TableScope("C 02.00", rows=RuleScope(SCOPE_LIST, ("0010", "9999"))),)
    )

    # Act
    expansion = _expand(rule, _c02_index())

    # Assert
    assert [c.row for c in expansion.coordinates] == ["0010"]


def test_a_rule_on_a_template_this_run_never_produced_is_skipped() -> None:
    """No emitted table for any of the rule's codes is ``table_not_emitted``."""
    # Arrange
    rule = build_rule(tables=("C 08.07",))

    # Act
    expansion = _expand(rule, _c02_index())

    # Assert
    assert (expansion.skip_reason, expansion.detail) == (SKIP_TABLE_NOT_EMITTED, "C 08.07")


def test_a_rule_whose_prerequisite_table_is_absent_never_runs() -> None:
    """The EBA prerequisite column gates the rule before any coordinate is formed."""
    # Arrange
    rule = build_rule(prerequisites=("C 08.07",))

    # Act
    expansion = _expand(rule, _c02_index())

    # Assert
    assert expansion.skip_reason == SKIP_PREREQUISITE_TABLE_ABSENT


def test_the_home_table_is_the_first_emitted_code_not_the_first_listed() -> None:
    """A cross-table rule anchors on whichever of its tables this run produced."""
    # Arrange: C 08.07 is listed first but was not emitted.
    rule = build_rule(tables=("C 08.07", "C 02.00"))

    # Act
    expansion = _expand(rule, _c02_index())

    # Assert
    assert expansion.home_table == "C 02.00"


# ---------------------------------------------------------------------------
# Sheet-code resolution
# ---------------------------------------------------------------------------


def test_a_closed_sheet_code_set_resolves_to_our_sheet() -> None:
    """C 08.01 codes 0013 + 0014 together cover our single retail-mortgage sheet."""
    # Arrange / Act
    resolution = resolve_sheet_codes(
        ("0013", "0014"), SHEET_INDEX_MAPS["c08"], ("retail_mortgage",)
    )

    # Assert
    assert (resolution.sheets, resolution.skip_reason) == (("retail_mortgage",), None)


def test_a_sheet_code_subset_that_leaks_exposures_is_refused() -> None:
    """Scoping 0013 alone would evaluate a sheet also carrying 0014's exposures.

    Closure is the load-bearing test: our sheets are a coarser partition than the
    DPM's SME / non-SME split, so an open subset silently widens the population.
    """
    # Arrange / Act
    resolution = resolve_sheet_codes(("0013",), SHEET_INDEX_MAPS["c08"], ("retail_mortgage",))

    # Assert
    assert (resolution.sheets, resolution.skip_reason) == ((), SKIP_SHEET_SCOPE_NOT_CLOSED)


def test_a_sheet_code_whose_meaning_was_never_established_is_refused() -> None:
    """A code absent from the map is ``sheet_index_map_unknown``, never a guess."""
    # Arrange: OF 08.01 codes 0003-0005 never appear in the extract and are unmapped.
    # Act
    resolution = resolve_sheet_codes(("0003",), SHEET_INDEX_MAPS["of08"], ("institution",))

    # Assert
    assert (resolution.sheets, resolution.skip_reason) == ((), SKIP_SHEET_INDEX_MAP_UNKNOWN)


def test_a_sheet_code_with_no_analogue_in_our_output_is_skipped() -> None:
    """The C 07.00 Total sheet is understood but has no counterpart we emit."""
    # Arrange / Act
    resolution = resolve_sheet_codes(("0001",), SHEET_INDEX_MAPS["c07"], ("corporate",))

    # Assert
    assert (resolution.sheets, resolution.skip_reason) == ((), SKIP_SHEET_NOT_EMITTED)


def test_a_mapped_class_this_run_did_not_produce_is_skipped() -> None:
    """s0007 indexes institutions; a corporates-only run cannot evaluate it."""
    # Arrange / Act
    resolution = resolve_sheet_codes(("0007",), SHEET_INDEX_MAPS["c07"], ("corporate",))

    # Assert
    assert (resolution.sheets, resolution.skip_reason) == ((), SKIP_SHEET_NOT_EMITTED)


# ---------------------------------------------------------------------------
# Template indexing
# ---------------------------------------------------------------------------


def test_an_empty_template_dict_counts_as_not_emitted() -> None:
    """A generator that produced no sheet for a template did not emit it."""
    # Arrange / Act
    index = build_index(c07_00={})

    # Assert
    assert index.is_emitted("C 07.00.a") is False


def test_every_dpm_variant_of_one_template_binds_to_the_same_frame() -> None:
    """C 07.00 a/b/c/d are row/column partitions of ONE frame in our estate."""
    # Arrange
    index = build_index(c07_00={"corporate": build_frame({"0010": {"0010": 1.0}})})

    # Act
    emitted = [index.is_emitted(f"C 07.00.{suffix}") for suffix in ("a", "b", "c", "d")]

    # Assert
    assert emitted == [True, True, True, True]


def test_the_framework_selects_the_table_code_space() -> None:
    """A BoE table code is unbindable under CRR, and vice versa."""
    # Arrange
    corep = build_corep(c07_00={"corporate": build_frame({"0010": {"0010": 1.0}})})

    # Act
    crr = build_template_index(corep, None, "CRR")
    b31 = build_template_index(corep, None, "BASEL_3_1")

    # Assert
    assert (crr.binding("OF07.00.01.01"), b31.binding("C 07.00.a")) == (None, None)


def test_comparing_two_template_indexes_raises_rather_than_answering() -> None:
    """``TemplateIndex`` is a dataclass over Polars frames, so ``==`` is not usable.

    Pinned as a trap, not a feature: a test written as ``assert index == expected``
    fails with an inscrutable ``TypeError`` about DataFrame truthiness rather than
    a diff. Compare the frames, never the index.
    """
    # Arrange
    left = build_index(c_02_00=build_frame({"0010": {"0010": 1.0}}))
    right = build_index(c_02_00=build_frame({"0010": {"0010": 1.0}}))

    # Act / Assert
    with pytest.raises(TypeError, match="truth value of a DataFrame is ambiguous"):
        _ = left == right


def test_absent_columns_and_rows_read_as_absent_rather_than_null() -> None:
    """``cell`` separates "not in the frame" from "in the frame, blank"."""
    # Arrange
    index = build_index(c_02_00=build_frame({"0010": {"0010": None}}))

    # Act
    blank = index.cell("C 02.00", SINGLE_SHEET, "0010", "0010")
    missing_row = index.cell("C 02.00", SINGLE_SHEET, "9999", "0010")

    # Assert
    assert (blank.present, blank.value, missing_row.present) == (True, None, False)
