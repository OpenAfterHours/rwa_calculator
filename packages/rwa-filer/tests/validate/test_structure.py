"""
Structure checks: is every fact something the taxonomy lets a firm report?

Each check is pinned on the synthetic pack (``pack_builders``), one behaviour
per test, and — because a structure checker that flags everything is as useless
as one that flags nothing — against a clean return that must yield no finding.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from pack_builders import build_pack, build_return
from rwa_filer.model import CanonicalReturn
from rwa_filer.rules.catalogue import SEVERITY_ERROR
from rwa_filer.taxonomy.pack import TaxonomyPack
from rwa_filer.validate.structure import (
    FINDING_CELL_NOT_REPORTABLE,
    FINDING_DUPLICATE_FACT,
    FINDING_EMPTY_RETURN,
    FINDING_HEADER_INVALID,
    FINDING_INCONSISTENT_DATAPOINT,
    FINDING_INDICATOR_INVALID,
    FINDING_OPEN_KEY_INVALID,
    FINDING_SHEET_INVALID,
    FINDING_UNKNOWN_TABLE,
    FINDING_VALUE_TYPE,
    IS_KEY,
    MAX_EXAMPLES,
    check_structure,
    filing_indicators,
    is_valid_lei,
    resolve_datapoints,
)


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path)


def facts(*rows: tuple[object, ...]) -> pl.DataFrame:
    """Facts from ``(table, sheet, open_key, row, column, value, text_value)`` tuples."""
    return pl.DataFrame(
        list(rows),
        schema={
            "table": pl.String,
            "sheet": pl.String,
            "open_key": pl.String,
            "row": pl.String,
            "column": pl.String,
            "value": pl.Float64,
            "text_value": pl.String,
        },
        orient="row",
    )


def codes(findings: list) -> list[str]:
    return [finding.code for finding in findings]


#: A return that uses every kind of table correctly.
CLEAN = facts(
    ("T01.00.01.01", None, None, "0010", "0010", 100.0, None),
    ("T01.00.01.01", None, None, "0010", "0020", 0.25, None),
    ("T01.00.01.01", None, None, "0010", "0030", None, "a comment"),
    ("T02.00.01.01", "0001", None, "0010", "0010", 60.0, None),
    ("T02.00.01.01", "0002", None, "0010", "0010", 40.0, None),
    ("T03.00.01.01", None, "x1", "0010", "0010", 100.0, None),
    ("T03.00.01.01", None, "GB", "0010", "0010", 70.0, None),
    ("T04.00.01.01", None, None, "1", "0005", 1.0, None),
    ("T04.00.01.01", None, None, "1", "0010", 5.0, None),
    ("T04.00.01.01", None, None, "1", "0020", 3.0, None),
    ("T04.00.01.01", None, None, "2", "0005", 2.0, None),
    ("T04.00.01.01", None, None, "2", "0010", 6.0, None),
    ("T05.00.01.01", None, None, "0010", "0010", 9.0, None),
    ("T05.00.01.02", None, None, "0010", "0010", 9.0, None),
    ("T06.00.01.01", None, None, "0010", "0010", None, "true"),
    ("T06.00.01.01", None, None, "0010", "0020", None, "2027-03-31"),
    ("T06.00.01.01", None, None, "0010", "0030", None, "tst_ZZ:x1"),
)


# ---------------------------------------------------------------------------
# The clean control
# ---------------------------------------------------------------------------


def test_a_structurally_sound_return_yields_no_finding(pack: TaxonomyPack) -> None:
    # Act
    findings = check_structure(build_return(CLEAN), pack)

    # Assert
    assert findings == []


def test_every_structure_finding_is_error_severity(pack: TaxonomyPack) -> None:
    # Arrange
    frame = facts(("ZZ99", None, None, "0010", "0010", 1.0, None))

    # Act
    findings = check_structure(build_return(frame), pack)

    # Assert
    assert findings and all(f.severity == SEVERITY_ERROR and f.is_blocking for f in findings)


# ---------------------------------------------------------------------------
# One check each
# ---------------------------------------------------------------------------


def test_a_table_the_module_does_not_have_is_reported(pack: TaxonomyPack) -> None:
    # Arrange
    frame = facts(
        ("ZZ99.00.01.01", None, None, "0010", "0010", 1.0, None),
        ("ZZ99.00.01.01", None, None, "0020", "0010", 2.0, None),
    )

    # Act
    findings = check_structure(build_return(frame), pack)

    # Assert
    assert codes(findings) == [FINDING_UNKNOWN_TABLE]
    assert findings[0].subject == "ZZ99.00.01.01" and "2 fact(s)" in findings[0].message


def test_a_fact_in_a_greyed_cell_is_reported(pack: TaxonomyPack) -> None:
    # Arrange — (0030, 0020) is the one cell of T01 the taxonomy does not accept.
    frame = facts(("T01.00.01.01", None, None, "0030", "0020", 0.5, None))

    # Act
    findings = check_structure(build_return(frame), pack)

    # Assert
    assert codes(findings) == [FINDING_CELL_NOT_REPORTABLE]
    assert "T01.00.01.01[r0030][c0020]" in findings[0].message


@pytest.mark.parametrize(("row", "column"), [("9999", "0010"), ("0010", "9999")])
def test_an_unknown_row_or_column_code_is_reported(
    pack: TaxonomyPack, row: str, column: str
) -> None:
    # Arrange
    frame = facts(("T01.00.01.01", None, None, row, column, 1.0, None))

    # Act / Assert
    assert codes(check_structure(build_return(frame), pack)) == [FINDING_CELL_NOT_REPORTABLE]


def test_a_sheet_the_table_does_not_have_is_reported_once(pack: TaxonomyPack) -> None:
    """Under its root cause only: the row code is fine, so no STR002 beside it."""
    # Arrange
    frame = facts(("T02.00.01.01", "0099", None, "0010", "0010", 1.0, None))

    # Act
    findings = check_structure(build_return(frame), pack)

    # Assert
    assert codes(findings) == [FINDING_SHEET_INVALID]
    assert "0001, 0002" in findings[0].message


def test_a_missing_sheet_on_a_sheeted_table_is_reported(pack: TaxonomyPack) -> None:
    # Arrange
    frame = facts(("T02.00.01.01", None, None, "0010", "0010", 1.0, None))

    # Act / Assert
    assert codes(check_structure(build_return(frame), pack)) == [FINDING_SHEET_INVALID]


def test_a_sheet_on_a_table_with_no_sheet_axis_is_reported(pack: TaxonomyPack) -> None:
    # Arrange
    frame = facts(("T01.00.01.01", "0001", None, "0010", "0010", 1.0, None))

    # Act
    findings = check_structure(build_return(frame), pack)

    # Assert
    assert codes(findings) == [FINDING_SHEET_INVALID]
    assert "no sheet axis" in findings[0].message


def test_an_open_key_outside_the_accepted_members_is_reported(pack: TaxonomyPack) -> None:
    # Arrange
    frame = facts(("T03.00.01.01", None, "ZZ", "0010", "0010", 1.0, None))

    # Act
    findings = check_structure(build_return(frame), pack)

    # Assert
    assert codes(findings) == [FINDING_OPEN_KEY_INVALID]
    assert "eba_dim:CEG" in findings[0].message


def test_an_open_key_may_be_given_as_a_full_qname(pack: TaxonomyPack) -> None:
    # Arrange
    frame = facts(("T03.00.01.01", None, "eba_GA:GB", "0010", "0010", 1.0, None))

    # Act / Assert
    assert check_structure(build_return(frame), pack) == []


def test_a_missing_open_key_is_reported(pack: TaxonomyPack) -> None:
    # Arrange
    frame = facts(("T03.00.01.01", None, None, "0010", "0010", 1.0, None))

    # Act / Assert
    assert codes(check_structure(build_return(frame), pack)) == [FINDING_OPEN_KEY_INVALID]


def test_an_open_key_on_a_table_with_no_open_axis_is_reported(pack: TaxonomyPack) -> None:
    # Arrange
    frame = facts(("T01.00.01.01", None, "GB", "0010", "0010", 1.0, None))

    # Act
    findings = check_structure(build_return(frame), pack)

    # Assert
    assert codes(findings) == [FINDING_OPEN_KEY_INVALID]
    assert "no open sheet axis" in findings[0].message


def test_the_same_cell_reported_twice_is_a_duplicate_even_when_values_agree(
    pack: TaxonomyPack,
) -> None:
    # Arrange
    frame = facts(
        ("T01.00.01.01", None, None, "0010", "0010", 1.0, None),
        ("T01.00.01.01", None, None, "0010", "0010", 1.0, None),
    )

    # Act / Assert
    assert codes(check_structure(build_return(frame), pack)) == [FINDING_DUPLICATE_FACT]


def test_open_rows_are_matched_on_column_and_keep_their_own_row_ids(pack: TaxonomyPack) -> None:
    # Arrange — any row id is acceptable; an unknown COLUMN is not.
    frame = facts(
        ("T04.00.01.01", None, None, "anything", "0005", 7.0, None),
        ("T04.00.01.01", None, None, "anything", "0010", 1.0, None),
        ("T04.00.01.01", None, None, "anything", "9999", 1.0, None),
    )

    # Act
    findings = check_structure(build_return(frame), pack)

    # Assert
    assert codes(findings) == [FINDING_CELL_NOT_REPORTABLE]
    assert "[ranything][c9999]" in findings[0].message


def test_a_row_key_reports_no_data_point_and_is_not_an_unknown_cell(pack: TaxonomyPack) -> None:
    """Column 0005 of the open-row table is its key: accepted, though it has no cell."""
    # Arrange
    frame = facts(
        ("T04.00.01.01", None, None, "1", "0005", 1.0, None),
        ("T04.00.01.01", None, None, "1", "0010", 5.0, None),
    )

    # Act
    resolved = resolve_datapoints(build_return(frame), pack).sort("column")

    # Assert
    assert check_structure(build_return(frame), pack) == []
    assert resolved[IS_KEY].to_list() == [True, False]
    assert resolved["datapoint"].null_count() == 1


def test_a_row_with_figures_and_no_key_is_reported(pack: TaxonomyPack) -> None:
    # Arrange — row "2" has an exposure and nothing to say whose it is.
    frame = facts(
        ("T04.00.01.01", None, None, "1", "0005", 1.0, None),
        ("T04.00.01.01", None, None, "1", "0010", 5.0, None),
        ("T04.00.01.01", None, None, "2", "0010", 6.0, None),
    )

    # Act
    findings = check_structure(build_return(frame), pack)

    # Assert
    assert codes(findings) == [FINDING_OPEN_KEY_INVALID]
    assert "no key" in findings[0].message and "[r2][c0010]" in findings[0].message
    assert "column 0005" in findings[0].message


@pytest.mark.parametrize(
    ("value", "text"),
    [(1.5, None), (None, "grade-A")],
    ids=["fraction", "text"],
)
def test_a_row_key_must_be_of_the_keys_type(
    pack: TaxonomyPack, value: float | None, text: str | None
) -> None:
    """The key is a typed integer dimension: a fraction or a word is not a member."""
    # Arrange
    frame = facts(
        ("T04.00.01.01", None, None, "1", "0005", value, text),
        ("T04.00.01.01", None, None, "1", "0010", 5.0, None),
    )

    # Act
    findings = check_structure(build_return(frame), pack)

    # Assert
    assert codes(findings) == [FINDING_OPEN_KEY_INVALID]
    assert "not of the key's type" in findings[0].message


def test_a_whole_number_key_may_be_given_as_text(pack: TaxonomyPack) -> None:
    frame = facts(
        ("T04.00.01.01", None, None, "1", "0005", None, "7"),
        ("T04.00.01.01", None, None, "1", "0010", 5.0, None),
    )

    assert check_structure(build_return(frame), pack) == []


def test_two_rows_with_the_same_key_are_the_same_facts_twice(pack: TaxonomyPack) -> None:
    # Arrange — different row identifiers, one obligor grade; "3" is fine.
    frame = facts(
        ("T04.00.01.01", None, None, "a", "0005", 1.0, None),
        ("T04.00.01.01", None, None, "a", "0010", 5.0, None),
        ("T04.00.01.01", None, None, "b", "0005", None, "1"),
        ("T04.00.01.01", None, None, "b", "0010", 6.0, None),
        ("T04.00.01.01", None, None, "c", "0005", 3.0, None),
        ("T04.00.01.01", None, None, "c", "0010", 7.0, None),
    )

    # Act
    findings = check_structure(build_return(frame), pack)

    # Assert
    assert codes(findings) == [FINDING_DUPLICATE_FACT]
    assert findings[0].actual == "2 fact(s)" and "[rc]" not in findings[0].message


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "value", "text"),
    [
        ("0010", None, "n/a"),  # text in a monetary cell
        ("0030", 5.0, None),  # a number in a string cell
    ],
    ids=["text-in-number-cell", "number-in-text-cell"],
)
def test_a_value_of_the_wrong_kind_is_reported(
    pack: TaxonomyPack, column: str, value: float | None, text: str | None
) -> None:
    # Arrange
    frame = facts(("T01.00.01.01", None, None, "0010", column, value, text))

    # Act / Assert
    assert codes(check_structure(build_return(frame), pack)) == [FINDING_VALUE_TYPE]


def test_a_fractional_count_is_reported(pack: TaxonomyPack) -> None:
    # Arrange — column 0020 of T04 is an integer metric.
    frame = facts(
        ("T04.00.01.01", None, None, "1", "0005", 1.0, None),
        ("T04.00.01.01", None, None, "1", "0020", 2.5, None),
    )

    # Act / Assert
    assert codes(check_structure(build_return(frame), pack)) == [FINDING_VALUE_TYPE]


@pytest.mark.parametrize(
    ("column", "text", "is_valid"),
    [
        ("0010", "true", True),
        ("0010", "FALSE", True),
        ("0010", "yes", False),
        ("0020", "2027-03-31", True),
        ("0020", "31/03/2027", False),
    ],
)
def test_booleans_and_dates_must_be_well_formed(
    pack: TaxonomyPack, column: str, text: str, is_valid: bool
) -> None:
    # Arrange
    frame = facts(("T06.00.01.01", None, None, "0010", column, None, text))

    # Act
    findings = check_structure(build_return(frame), pack)

    # Assert
    assert (findings == []) is is_valid


# ---------------------------------------------------------------------------
# One data point, two cells
# ---------------------------------------------------------------------------


def test_a_data_point_shown_in_two_tables_must_carry_one_value(pack: TaxonomyPack) -> None:
    # Arrange
    frame = facts(
        ("T05.00.01.01", None, None, "0010", "0010", 9.0, None),
        ("T05.00.01.02", None, None, "0010", "0010", 10.0, None),
    )

    # Act
    findings = check_structure(build_return(frame), pack)

    # Assert — both cells are named, one finding per table.
    assert codes(findings) == [FINDING_INCONSISTENT_DATAPOINT] * 2
    assert {finding.subject for finding in findings} == {"T05.00.01.01", "T05.00.01.02"}


def test_agreeing_values_for_a_shared_data_point_are_fine(pack: TaxonomyPack) -> None:
    # Arrange
    frame = facts(
        ("T05.00.01.01", None, None, "0010", "0010", 9.0, None),
        ("T05.00.01.02", None, None, "0010", "0010", 9.0, None),
    )

    # Act / Assert
    assert check_structure(build_return(frame), pack) == []


def test_open_rows_sharing_a_data_point_template_are_not_inconsistent(pack: TaxonomyPack) -> None:
    """Every open row maps to the same template cell; they are different facts."""
    # Arrange
    frame = facts(
        ("T04.00.01.01", None, None, "1", "0005", 1.0, None),
        ("T04.00.01.01", None, None, "1", "0010", 5.0, None),
        ("T04.00.01.01", None, None, "2", "0005", 2.0, None),
        ("T04.00.01.01", None, None, "2", "0010", 6.0, None),
    )

    # Act / Assert
    assert check_structure(build_return(frame), pack) == []


def test_two_countries_reporting_one_cell_are_not_inconsistent(pack: TaxonomyPack) -> None:
    # Arrange
    frame = facts(
        ("T03.00.01.01", None, "GB", "0010", "0010", 70.0, None),
        ("T03.00.01.01", None, "FR", "0010", "0010", 30.0, None),
    )

    # Act / Assert
    assert check_structure(build_return(frame), pack) == []


# ---------------------------------------------------------------------------
# Header and emptiness
# ---------------------------------------------------------------------------


def test_an_empty_return_is_reported_not_passed(pack: TaxonomyPack) -> None:
    # Act
    findings = check_structure(build_return(CLEAN.clear()), pack)

    # Assert
    assert codes(findings) == [FINDING_EMPTY_RETURN]


@pytest.mark.parametrize(
    ("override", "subject"),
    [
        ({"entity_identifier": "NOT-AN-LEI"}, "entity_identifier"),
        ({"currency": "pounds"}, "currency"),
        ({"module": "OTHER"}, "module"),
        ({"reference_date": date(2026, 12, 31)}, "reference_date"),
    ],
)
def test_a_header_the_regulator_would_reject_is_reported(
    pack: TaxonomyPack, override: dict[str, object], subject: str
) -> None:
    # Act
    findings = check_structure(build_return(CLEAN, **override), pack)

    # Assert
    assert [(f.code, f.subject) for f in findings] == [(FINDING_HEADER_INVALID, subject)]


def test_a_non_lei_scheme_is_not_held_to_the_lei_format(pack: TaxonomyPack) -> None:
    # Act
    findings = check_structure(
        build_return(CLEAN, entity_identifier="123456", entity_scheme="http://example.test/frn"),
        pack,
    )

    # Assert
    assert findings == []


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("5493001KJTIIGC8Y1R12", True),
        ("5493001KJTIIGC8Y1R13", False),  # wrong check digits
        ("5493001KJTIIGC8Y1R1", False),  # 19 characters
        ("5493001kjtiigc8y1r12", False),  # lower case
        ("", False),
    ],
)
def test_lei_validation_checks_length_alphabet_and_check_digits(
    identifier: str, expected: bool
) -> None:
    assert is_valid_lei(identifier) is expected


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_many_offending_facts_roll_up_to_one_finding_with_a_count(pack: TaxonomyPack) -> None:
    # Arrange — eight facts on rows the table does not have.
    frame = facts(*(("T01.00.01.01", None, None, f"9{i:03d}", "0010", 1.0, None) for i in range(8)))

    # Act
    findings = check_structure(build_return(frame), pack)

    # Assert
    assert codes(findings) == [FINDING_CELL_NOT_REPORTABLE]
    assert findings[0].actual == "8 fact(s)"
    assert findings[0].message.count("[r9") == MAX_EXAMPLES
    assert f"first {MAX_EXAMPLES} of 8" in findings[0].message


def test_resolve_datapoints_adds_the_data_point_and_keeps_every_fact(pack: TaxonomyPack) -> None:
    # Arrange
    frame = facts(
        ("T01.00.01.01", None, None, "0010", "0010", 1.0, None),
        ("T01.00.01.01", None, None, "0030", "0020", 1.0, None),
    )

    # Act
    resolved = resolve_datapoints(build_return(frame), pack).sort("row")

    # Assert
    assert resolved["datapoint"].to_list() == [0, None]


# ---------------------------------------------------------------------------
# Filing indicators
# ---------------------------------------------------------------------------


def test_undeclared_indicators_follow_the_facts(pack: TaxonomyPack) -> None:
    """Every template with a fact is reported; the rest are not mentioned."""
    # Arrange — T05's two tables share one indicator.
    frame = facts(
        ("T01.00.01.01", None, None, "0010", "0010", 5.0, None),
        ("T05.00.01.01", None, None, "0010", "0010", 9.0, None),
        ("T05.00.01.02", None, None, "0010", "0010", 9.0, None),
    )

    # Act / Assert
    assert filing_indicators(build_return(frame), pack) == {"T01.00.01": True, "T05.00.01": True}


def test_declared_indicators_are_taken_as_given(pack: TaxonomyPack) -> None:
    """A template may be reported with no facts, or declared not reported."""
    # Arrange
    base = build_return(facts(("T01.00.01.01", None, None, "0010", "0010", 5.0, None)))
    declared = {"T02.00.01": True, "T01.00.01": True, "T03.00.01": False}
    ret = CanonicalReturn(base.header, base.facts, declared)

    # Act / Assert
    assert check_structure(ret, pack) == []
    assert filing_indicators(ret, pack) == {
        "T01.00.01": True,
        "T02.00.01": True,
        "T03.00.01": False,
    }


def test_a_fact_in_a_template_not_declared_as_reported_is_an_error(pack: TaxonomyPack) -> None:
    """Filing Manual rule 1.7.1 — whether the indicator is negative or simply absent."""
    # Arrange
    base = build_return(
        facts(
            ("T01.00.01.01", None, None, "0010", "0010", 5.0, None),
            ("T02.00.01.01", "0001", None, "0010", "0010", 6.0, None),
            ("T06.00.01.01", None, None, "0010", "0010", None, "true"),
        )
    )
    ret = CanonicalReturn(base.header, base.facts, {"T01.00.01": True, "T02.00.01": False})

    # Act
    findings = check_structure(ret, pack)

    # Assert — one finding per offending table, naming its indicator.
    assert codes(findings) == [FINDING_INDICATOR_INVALID, FINDING_INDICATOR_INVALID]
    assert [finding.subject for finding in findings] == ["T02.00.01.01", "T06.00.01.01"]
    assert "filing indicator T02.00.01" in findings[0].message


def test_a_declared_indicator_the_module_does_not_have_is_an_error(pack: TaxonomyPack) -> None:
    # Arrange
    base = build_return(facts(("T01.00.01.01", None, None, "0010", "0010", 5.0, None)))
    ret = CanonicalReturn(base.header, base.facts, {"T01.00.01": True, "T99.00.01": True})

    # Act
    findings = check_structure(ret, pack)

    # Assert
    assert codes(findings) == [FINDING_INDICATOR_INVALID]
    assert "T99.00.01" in findings[0].message
