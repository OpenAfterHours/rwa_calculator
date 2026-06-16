"""Unit tests for the rulebook rule-shape vocabulary (``rulebook/model.py``)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rwa_calc.rulebook.model import (
    BandedTable,
    CategoryMap,
    Citation,
    DecisionTable,
    Feature,
    FormulaParams,
    IntParam,
    LookupTable,
    ScalarParam,
    Schedule,
)

# ---------------------------------------------------------------------------
# Citation
# ---------------------------------------------------------------------------


def test_citation_crr_string_form() -> None:
    # Arrange / Act
    citation = Citation("CRR", "153(1)")

    # Assert
    assert str(citation) == "CRR Art. 153(1)"


def test_citation_ps126_uses_paragraph_form() -> None:
    # Arrange / Act
    citation = Citation("PS1/26", "92(5)")

    # Assert
    assert str(citation) == "PS1/26, paragraph 92(5)"


def test_citation_empty_framework_raises() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="framework"):
        Citation("", "153(1)")


def test_citation_empty_article_raises() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="article"):
        Citation("CRR", "")


# ---------------------------------------------------------------------------
# Shape construction
# ---------------------------------------------------------------------------


def test_all_shapes_construct() -> None:
    # Arrange
    citation = Citation("CRR", "1")

    # Act
    scalar = ScalarParam("s", Decimal("1.06"), citation)
    lookup = LookupTable("l", {1: Decimal("0.2")}, "cqs", citation)
    banded = BandedTable(
        "b", ((Decimal("1"), Decimal("0.5")), (None, Decimal("1.0"))), "x", citation
    )
    schedule = Schedule("sc", ((date(2027, 1, 1), Decimal("0.6")),), Decimal("0.0"), citation)
    decision = DecisionTable("d", ("a",), (((1,), Decimal("0.3")),), citation)
    formula = FormulaParams("f", {"k": Decimal("0.5")}, citation)
    feature = Feature("ft", True, citation)

    # Assert
    assert scalar.value == Decimal("1.06")
    assert lookup.key == "cqs"
    assert banded.input == "x"
    assert schedule.before_first == Decimal("0.0")
    assert decision.key_names == ("a",)
    assert formula.get("k") == Decimal("0.5")
    assert feature.enabled is True


def test_int_param_constructs_and_holds_int() -> None:
    # Arrange / Act
    param = IntParam("mpor_floor_days", 5, Citation("CRR", "285"))

    # Assert — the int sibling of ScalarParam keeps an integer value end-to-end
    assert param.value == 5
    assert isinstance(param.value, int)


def test_category_map_constructs_and_holds_str_entries() -> None:
    # Arrange / Act
    cmap = CategoryMap(
        name="entity_type_to_sa_class",
        entries={"sovereign": "central_govt_central_bank", "corporate": "corporate"},
        key="entity_type",
        citation=Citation("CRR", "112"),
    )

    # Assert — the string-valued sibling of LookupTable: category labels, no default
    assert cmap.entries["sovereign"] == "central_govt_central_bank"
    assert cmap.default is None


# ---------------------------------------------------------------------------
# Schedule.resolve — carry-forward semantics
# ---------------------------------------------------------------------------


@pytest.fixture
def output_floor_schedule() -> Schedule:
    return Schedule(
        name="output_floor_pct",
        steps=(
            (date(2027, 1, 1), Decimal("0.60")),
            (date(2028, 1, 1), Decimal("0.65")),
            (date(2030, 1, 1), Decimal("0.725")),
        ),
        before_first=Decimal("0.0"),
        citation=Citation("PS1/26", "92(5)"),
    )


def test_schedule_before_first_step(output_floor_schedule: Schedule) -> None:
    # Act / Assert
    assert output_floor_schedule.resolve(date(2026, 12, 31)) == Decimal("0.0")


def test_schedule_on_step_date(output_floor_schedule: Schedule) -> None:
    # Act / Assert
    assert output_floor_schedule.resolve(date(2027, 1, 1)) == Decimal("0.60")


def test_schedule_carry_forward_between_steps(output_floor_schedule: Schedule) -> None:
    # Act / Assert — 2029 has no step, carries 2028's value forward
    assert output_floor_schedule.resolve(date(2029, 6, 1)) == Decimal("0.65")


def test_schedule_after_last_step(output_floor_schedule: Schedule) -> None:
    # Act / Assert
    assert output_floor_schedule.resolve(date(2031, 1, 1)) == Decimal("0.725")


def test_schedule_empty_steps_raises() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="non-empty"):
        Schedule("s", (), Decimal("0.0"), Citation("PS1/26", "92(5)"))


def test_schedule_unsorted_steps_raises() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="sorted"):
        Schedule(
            "s",
            ((date(2028, 1, 1), Decimal("0.65")), (date(2027, 1, 1), Decimal("0.60"))),
            Decimal("0.0"),
            Citation("PS1/26", "92(5)"),
        )


# ---------------------------------------------------------------------------
# BandedTable validation
# ---------------------------------------------------------------------------


def test_banded_two_none_bounds_raises() -> None:
    # Act / Assert — only the last band may have a None bound
    with pytest.raises(ValueError, match="last band"):
        BandedTable(
            "b",
            ((None, Decimal("0.5")), (None, Decimal("1.0"))),
            "x",
            Citation("CRR", "1"),
        )


def test_banded_non_increasing_bounds_raises() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="strictly increasing"):
        BandedTable(
            "b",
            (
                (Decimal("2"), Decimal("0.5")),
                (Decimal("1"), Decimal("0.7")),
                (None, Decimal("1.0")),
            ),
            "x",
            Citation("CRR", "1"),
        )


def test_banded_empty_raises() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="non-empty"):
        BandedTable("b", (), "x", Citation("CRR", "1"))


# ---------------------------------------------------------------------------
# DecisionTable validation
# ---------------------------------------------------------------------------


def test_decision_row_key_length_mismatch_raises() -> None:
    # Act / Assert — key-tuple length must equal len(key_names)
    with pytest.raises(ValueError, match="expected 2"):
        DecisionTable(
            "d",
            ("a", "b"),
            (((1,), Decimal("0.3")),),
            Citation("CRR", "1"),
        )
