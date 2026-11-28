"""Attributing a return's breaks to the members of a breakdown column, on the packaged PRA001 rules."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from detail_builders import (
    ASSET_FINANCE,
    COMMERCIAL,
    CORPORATE,
    CORPORATES,
    DOUBLED_COLLATERAL,
    HEADER_FIELDS,
    LATE_FACILITY,
    MOVED_PROVISION,
    PRIVATE,
    TABLE,
    clean_rows,
    write_detail,
)
from rwa_filer.readers import DetailSpec, open_source
from rwa_filer.validate.returns import validate_return
from rwa_filer.workflow import attribution
from rwa_filer.workflow.adjustments import Adjustment, apply_adjustments
from rwa_filer.workflow.attribution import as_record, attribute, describe

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.readers import SourceReading
    from rwa_filer.validate.returns import ReturnValidation

SPEC = DetailSpec(breakdown=("business_unit", "source"), line_ref="line_id")


def _opened(path: Path) -> tuple[SourceReading, ReturnValidation]:
    source = open_source(path, HEADER_FIELDS, detail=SPEC)
    return source, validate_return(source.ret, release=source.release, max_failures=None)


@pytest.fixture(scope="module")
def book(tmp_path_factory: pytest.TempPathFactory) -> tuple[SourceReading, ReturnValidation]:
    """The book with its three planted defects, read and validated."""
    return _opened(write_detail(tmp_path_factory.mktemp("book") / "detail.csv"))


@pytest.fixture(scope="module")
def by_unit(book: tuple[SourceReading, ReturnValidation]) -> attribution.Attribution:
    source, validation = book
    assert source.detail is not None
    return attribute(source.ret, validation, source.detail, "business_unit")


def test_every_break_of_the_return_is_set_against_every_member(
    book: tuple[SourceReading, ReturnValidation], by_unit: attribution.Attribution
) -> None:
    # Arrange
    _, validation = book
    assert validation.report is not None
    breaks = sum(result.unsatisfied for result in validation.report.results)

    # Assert
    assert breaks > 0, "the book must break something, or this test proves nothing"
    assert len(by_unit.broken) == breaks
    assert all(len(item.standings) == len(by_unit.members) for item in by_unit.broken)


def test_the_doubled_collateral_is_traced_to_asset_finance_alone(
    by_unit: attribution.Attribution,
) -> None:
    # Arrange
    collateral = [item for item in by_unit.broken if item.rule_id in ("boe_b0471", "boe_b0556")]

    # Assert
    assert collateral, "boe_b0471 and boe_b0556 break on the doubled collateral"
    for item in collateral:
        assert [standing.member for standing in item.breaking] == [ASSET_FINANCE]
        assert item.standing(ASSET_FINANCE).gap == DOUBLED_COLLATERAL  # type: ignore[union-attr]
        assert item.gap == DOUBLED_COLLATERAL


def test_the_late_journal_is_traced_to_its_unit_and_by_source_to_the_journal(
    book: tuple[SourceReading, ReturnValidation], by_unit: attribution.Attribution
) -> None:
    # Arrange
    source, validation = book
    assert source.detail is not None
    by_source = attribute(source.ret, validation, source.detail, "source")
    totals = [item for item in by_unit.broken if item.rule_id == "boe_b0719"]

    # Assert
    assert totals
    assert all(COMMERCIAL in {s.member for s in item.breaking} for item in totals)
    assert all(item.gap == LATE_FACILITY for item in totals)
    journal = [item for item in by_source.broken if item.rule_id == "boe_b0719"]
    assert all([s.member for s in item.breaking] == ["JNL-1"] for item in journal)


def test_the_members_gaps_add_up_to_the_returns(by_unit: attribution.Attribution) -> None:
    # Assert: every rule here is a sum or a difference of the detail's figures.
    assert all(item.unexplained == 0 for item in by_unit.broken)
    assert all(item.explained == item.gap for item in by_unit.broken)


def test_a_break_the_total_hides_is_found_on_the_units_that_offset_it(
    by_unit: attribution.Attribution,
) -> None:
    # Arrange
    hidden = [item for item in by_unit.hidden if item.rule_id == "boe_b0708"]

    # Assert
    assert hidden, "c0040 = c0010 + c0030 holds in total and breaks for both units"
    for item in hidden:
        assert item.holds
        gaps = {standing.member: standing.gap for standing in item.breaking}
        assert gaps == {CORPORATE: MOVED_PROVISION, PRIVATE: -MOVED_PROVISION}


def test_on_a_book_with_nothing_wrong_there_is_nothing_to_attribute_or_hide(
    tmp_path: Path, by_unit: attribution.Attribution
) -> None:
    # Arrange: the alarm must stay quiet where nothing is wrong, and fire where
    # something is — the second half is what makes the first worth asserting.
    source, validation = _opened(write_detail(tmp_path / "clean.csv", clean_rows()))
    assert source.detail is not None

    # Act
    clean = attribute(source.ret, validation, source.detail, "business_unit")

    # Assert
    assert clean.broken == () and clean.hidden == ()
    assert clean.searched_hidden and clean.rules_run > 0
    assert by_unit.broken and by_unit.hidden


def test_an_override_on_a_figure_a_rule_reads_is_in_no_members_rows(
    book: tuple[SourceReading, ReturnValidation],
) -> None:
    # Arrange: 7 more exposure value on the Corporates total, drafted as an override.
    source, validation = book
    assert source.detail is not None
    cell = (TABLE, CORPORATES, None, "0010", "0200")
    held = source.ret.facts.filter(
        (source.ret.facts["sheet"] == CORPORATES)
        & (source.ret.facts["row"] == "0010")
        & (source.ret.facts["column"] == "0200")
    )["value"][0]
    adjusted, _ = apply_adjustments(
        source.ret,
        [Adjustment(TABLE, "0010", "0200", "test", sheet=CORPORATES, value=held + 7)],
    )
    checked = validate_return(adjusted, release=source.release, max_failures=None)

    # Act
    found = attribute(adjusted, checked, source.detail, "business_unit", rule_ids={"boe_b0471"})

    # Assert
    reading = found.reading(cell, "boe_b0471")
    assert len(reading) == 1
    assert reading[0].unexplained == pytest.approx(7)
    assert reading[0].explained == DOUBLED_COLLATERAL


def test_only_the_rules_asked_for_are_run_again_once_per_member_and_once_for_the_return(
    book: tuple[SourceReading, ReturnValidation], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: count the work, not the time.
    source, validation = book
    assert source.detail is not None
    runs: list[tuple[str, ...]] = []
    real = attribution._trace_indexed

    def counted(*args: object, **kwargs: object) -> object:
        runs.append(tuple(rule.rule_id for rule in args[1]))  # type: ignore[attr-defined]
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(attribution, "_trace_indexed", counted)

    # Act
    found = attribute(
        source.ret,
        validation,
        source.detail,
        "business_unit",
        rule_ids={"boe_b0556"},
        search_hidden=False,
    )

    # Assert
    assert runs == [("boe_b0556",)] * (len(found.members) + 1)
    assert {item.rule_id for item in found.broken} == {"boe_b0556"}
    assert found.hidden == () and not found.searched_hidden


def test_a_column_that_is_not_a_breakdown_column_is_refused(
    book: tuple[SourceReading, ReturnValidation],
) -> None:
    # Arrange
    source, validation = book
    assert source.detail is not None

    # Act / Assert
    with pytest.raises(KeyError, match="'desk' is not a breakdown column"):
        attribute(source.ret, validation, source.detail, "desk")


def test_the_text_names_each_rule_and_the_members_that_break_it(
    by_unit: attribution.Attribution,
) -> None:
    # Act
    text = "\n".join(describe(by_unit, labels={"boe_b0471": "the published label"}))

    # Assert
    assert "boe_b0471 (Error), 4 break(s)\n    the published label\n" in text
    assert "Asset Finance breaks all 4, out by +100,000" in text
    assert "Private Banking breaks 2 of 4, out by -5,000" in text
    assert "Hold in the return, break on one business_unit's figures alone: 8" in text


def test_the_record_carries_every_member_of_every_break(by_unit: attribution.Attribution) -> None:
    # Act
    record = as_record(by_unit)

    # Assert
    assert record["dimension"] == "business_unit"
    assert len(record["broken"]) == len(by_unit.broken)
    first = record["broken"][0]
    assert {member["member"] for member in first["members"]} == set(by_unit.members)
    assert record["hidden"] is not None


def test_only_evaluations_over_amounts_can_be_hidden_breaks(
    book: tuple[SourceReading, ReturnValidation],
) -> None:
    # Arrange: two evaluations that hold in the return and break on one member's
    # rows — one reading amounts, one reading a PD. A PD on part of the rows is
    # not a figure the rule can be judged on, so only the first is a finding.
    from rwa_filer.boe.engine import CellAddress, Evaluation

    _, validation = book
    standings = (
        attribution.Standing(member="A", evaluated=True, holds=False, left=1.0, right=0.0),
    )
    amounts = Evaluation(
        rule_id="r_amounts",
        place=(("r", "0010"),),
        holds=True,
        relation="=",
        left=(CellAddress(TABLE, CORPORATES, None, "0010", "0200"),),
        right=(CellAddress(TABLE, CORPORATES, None, "0010", "0150"),),
    )
    rates = Evaluation(
        rule_id="r_rates",
        place=(("r", "0001"),),
        holds=True,
        relation="=",
        left=(CellAddress("OF08.01.01.01", "0001", None, "0001", "0010"),),
        right=(CellAddress("OF08.01.01.01", "0001", None, "0001", "0020"),),
    )

    # Act
    found = attribution._over_amounts(  # noqa: SLF001 - the one place the filter is made
        [(amounts, standings), (rates, standings)],
        validation,
        {"r_amounts": "ERROR", "r_rates": "ERROR"},
    )

    # Assert
    assert [item.rule_id for item in found] == ["r_amounts"]
