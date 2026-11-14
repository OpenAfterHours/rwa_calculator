"""
The rule language's parser: what the tree is, and what is refused.

The expressions are in the published syntax. The claim "this parses every
published rule" is pinned separately, against the packaged rule books, in
``test_packaged_rulebooks.py``.
"""

from __future__ import annotations

import pytest

from rwa_filer.boe.grammar import (
    DEFAULT_DATE,
    DEFAULT_EMPTY,
    DEFAULT_FALSE,
    DEFAULT_MEMBER_KIND,
    DEFAULT_STRING,
    DEFAULT_ZERO,
    Binary,
    Call,
    Conditional,
    Default,
    DimensionFilter,
    GrammarError,
    JoinEquality,
    JoinKey,
    Logical,
    Member,
    Negate,
    Number,
    Reference,
    ScopeGroup,
    Text,
    parse_expression,
    parse_join,
    parse_scope,
    references,
)

A = "{t: T1, r: 0010, c: 0010, dv: 0, seq: False, id: v0, f: banking, fv: x}"
B = "{t: T1, r: 0020, c: 0010, dv: 0, seq: False, id: v1, f: banking, fv: x}"
C = "{t: T1, r: 0030, c: 0010, dv: 0, seq: False, id: v2, f: banking, fv: x}"
REF_A = Reference("T1", ("0010",), ("0010",), (), Default(DEFAULT_ZERO), None, False, "v0")
REF_B = Reference("T1", ("0020",), ("0010",), (), Default(DEFAULT_ZERO), None, False, "v1")
REF_C = Reference("T1", ("0030",), ("0010",), (), Default(DEFAULT_ZERO), None, False, "v2")


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------


def test_a_reference_carries_its_table_codes_default_and_binding() -> None:
    # Act
    node = parse_expression(
        "{t: OF07.00.01.01, r: 0351; 0352, c: 0070, z: 0001, dv: emptySequence(), "
        "seq: True, id: v1, f: banking, fv: banking_reporting}"
    )

    # Assert — codes keep their order and their leading zeros.
    assert node == Reference(
        table="OF07.00.01.01",
        rows=("0351", "0352"),
        columns=("0070",),
        sheets=("0001",),
        default=Default(DEFAULT_EMPTY),
        sequence=True,
        variable="v1",
    )


def test_a_reference_with_no_dv_has_no_default() -> None:
    """Not the same as a default of zero: the rule is not run where the cell is missing."""
    node = parse_expression("{t: T1, r: 0010, c: 0010, seq: False, id: v0, f: b, fv: x}")

    assert isinstance(node, Reference) and node.default is None


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("0", Default(DEFAULT_ZERO)),
        ("emptySequence()", Default(DEFAULT_EMPTY)),
        ("false()", Default(DEFAULT_FALSE)),
        ("[Default]", Default(DEFAULT_MEMBER_KIND, "Default")),
        ('""', Default(DEFAULT_STRING)),
        ("\"''\"", Default(DEFAULT_STRING)),
        ("CreateDate(1900,01,01)", Default(DEFAULT_DATE, "1900-01-01")),
    ],
)
def test_every_published_default_value_is_understood(written: str, expected: Default) -> None:
    node = parse_expression(f"{{t: T1, c: 0010, dv: {written}, seq: False, f: b, fv: x}}")

    assert isinstance(node, Reference) and node.default == expected


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        (
            "dim(this(), [eba_dim:CEG]) = [eba_GA:x1]",
            DimensionFilter("eba_dim:CEG", "eba_GA:x1"),
        ),
        (
            "not(dim(this(), [eba_dim:RIO]) = [eba_GA:x0])",
            DimensionFilter("eba_dim:RIO", "eba_GA:x0", negated=True),
        ),
        ("this() = [eba_BT:x16]", DimensionFilter(None, "eba_BT:x16")),
    ],
)
def test_the_three_filter_forms(written: str, expected: DimensionFilter) -> None:
    node = parse_expression(f"{{t: T1, c: 0010, filter: {written}, seq: False, f: b, fv: x}}")

    assert isinstance(node, Reference) and node.dimension_filter == expected


def test_codes_are_kept_as_written() -> None:
    """Some tables write three digits and most four; the table decides, not the parser."""
    assert parse_expression("{SR801.03.01.01, x:010}") == Reference(
        "SR801.03.01.01", columns=("010",)
    )
    three = parse_expression("{t: MR700.00.01.01, r: 020, c: 010, seq: False, f: b, fv: mrel}")
    assert isinstance(three, Reference) and (three.rows, three.columns) == (("020",), ("010",))


def test_a_dimension_reference_is_kept_apart_from_a_cell_reference() -> None:
    node = parse_expression("{d: [eba_dim:RDT], dv: emptySequence(), seq: False, id: v0}")

    assert isinstance(node, Reference)
    assert (node.table, node.key_dimension) == (None, "eba_dim:RDT")


# ---------------------------------------------------------------------------
# Operators and precedence
# ---------------------------------------------------------------------------


def test_the_interval_prefix_is_recorded_per_operator() -> None:
    # Act
    node = parse_expression(f"{A} i= {B} + {C}")

    # Assert — the comparison is tolerant, the addition is exact.
    assert node == Binary("=", REF_A, Binary("+", REF_B, REF_C), interval=True)


def test_addition_and_subtraction_associate_to_the_left() -> None:
    """``a - b + c`` is ``(a - b) + c``; right-association gives a different number."""
    node = parse_expression(f"{A} i- {B} i+ {C}")

    assert node == Binary("+", Binary("-", REF_A, REF_B, True), REF_C, True)


def test_multiplication_binds_tighter_than_addition() -> None:
    node = parse_expression(f"{A} + {B} * 12.5")

    assert node == Binary("+", REF_A, Binary("*", REF_B, Number(12.5)))


def test_and_binds_tighter_than_or() -> None:
    node = parse_expression(f"{A} >= 0 or {B} >= 0 and {C} >= 0")

    assert isinstance(node, Logical) and node.operator == "or"
    assert isinstance(node.operands[1], Logical) and node.operands[1].operator == "and"


def test_unary_minus_and_parentheses() -> None:
    node = parse_expression(f"-({A} + 1) < 0")

    assert node == Binary("<", Negate(Binary("+", REF_A, Number(1.0))), Number(0.0))


def test_a_comparison_cannot_be_chained() -> None:
    with pytest.raises(GrammarError, match="chained"):
        parse_expression(f"{A} <= {B} <= {C}")


def test_the_upper_case_interval_prefix_is_read() -> None:
    """One published rule writes ``I<=``."""
    node = parse_expression(f"{A} I<= {B}")

    assert node == Binary("<=", REF_A, REF_B, interval=True)


# ---------------------------------------------------------------------------
# Conditionals, logic and functions
# ---------------------------------------------------------------------------


def test_the_whole_and_expression_is_the_then_branch() -> None:
    # Act
    node = parse_expression(f"if {A} = true() then ({B} i= {C} i/ 0.08) and {B} >= 0 else true()")

    # Assert
    assert isinstance(node, Conditional)
    assert isinstance(node.then, Logical) and len(node.then.operands) == 2
    assert node.otherwise == Call("true", ())


def test_a_missing_else_is_left_out_of_the_tree() -> None:
    node = parse_expression(f"If {A} > 0 Then {B} > 0")

    assert isinstance(node, Conditional) and node.otherwise is None


def test_keywords_and_function_names_are_case_insensitive() -> None:
    node = parse_expression(f"IsNull({A}) AND Not(isnull({B}))")

    assert node == Logical(
        "and", (Call("isnull", (REF_A,)), Call("not", (Call("isnull", (REF_B,)),)))
    )


def test_a_string_may_contain_braces_and_brackets() -> None:
    """Strings are regular expressions; they are lexed before references."""
    node = parse_expression(f'matches({A}, "^[A-Z0-9]{{18}}[0-9]{{2}}$")')

    assert node == Call("matches", (REF_A, Text("^[A-Z0-9]{18}[0-9]{2}$")))


def test_members_with_and_without_the_dollar_prefix() -> None:
    assert parse_expression(f"{A} = [eba_GA:AL]") == Binary("=", REF_A, Member("eba_GA:AL"))
    assert parse_expression(f"{A} = $[eba_GA:AL]") == Binary("=", REF_A, Member("eba_GA:AL"))


def test_references_are_listed_in_the_order_written() -> None:
    node = parse_expression(f"if {A} > 0 then isum({B}) i= {C}")

    assert references(node) == (REF_A, REF_B, REF_C)


# ---------------------------------------------------------------------------
# Scope and join
# ---------------------------------------------------------------------------


def test_a_scope_lists_the_codes_per_table_and_axis() -> None:
    # Act
    groups = parse_scope(
        "scope({t: OF08.01.01.01, r:0010;0020,z:0001;0002, f: banking, fv: x},"
        "{t: OF08.02.01.01, z:0001;0002, f: banking, fv: x})"
    )

    # Assert
    assert groups == (
        ScopeGroup("OF08.01.01.01", rows=("0010", "0020"), sheets=("0001", "0002")),
        ScopeGroup("OF08.02.01.01", sheets=("0001", "0002")),
    )


def test_an_empty_scope_cell_is_no_scope() -> None:
    assert parse_scope("") == () and parse_scope("  ") == ()


def test_the_two_join_forms() -> None:
    # Arrange
    left = "{t: T1, c: 0010, seq: False, id: v0, f: b, fv: x}"
    right = "{t: T2, c: 0020, seq: False, id: v1, f: b, fv: x}"

    # Act
    keyed = parse_join(f"join(JoinDimensions({left}, [boe_dim:ISU]))")
    equal = parse_join(f"join(dim({left}, [boe_dim:UDI]) = dim({right}, [boe_dim:UDI]))")

    # Assert
    assert isinstance(keyed[0], JoinKey) and keyed[0].dimension == "boe_dim:ISU"
    assert isinstance(equal[0], JoinEquality)
    assert (equal[0].left.table, equal[0].right.table) == ("T1", "T2")


# ---------------------------------------------------------------------------
# What is refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{t: T1, c: 0010", "unterminated reference"),
        ('matches({t: T1, c: 0010, f: b, fv: x}, "abc)', "unterminated string"),
        ("{t: T1, q: 1, f: b, fv: x} > 0", "unknown reference key"),
        ("{t: T1, c: 10, f: b, fv: x} > 0", "not a row, column or sheet code"),
        ("{t: T1, c: 0010, dv: maybe, f: b, fv: x} > 0", "unknown default"),
        ("{t: T1, c: 0010, f: b, fv: x} > ", "ends too soon"),
        ("{t: T1, c: 0010, f: b, fv: x} > 0 extra", "after the expression"),
        ("{t: T1, c: 0010, f: b, fv: x} > total", "is not followed by"),
        ("{t: T1, c: 0010, f: b, fv: x} # 0", "unexpected character"),
    ],
)
def test_a_cell_that_is_not_in_the_language_is_refused(text: str, message: str) -> None:
    with pytest.raises(GrammarError, match=message):
        parse_expression(text)
