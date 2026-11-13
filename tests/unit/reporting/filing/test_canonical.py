"""
The canonical return: our generated estate, re-addressed to the taxonomy's coordinates.

Pipeline position:
    COREPTemplateBundle -> filing.build_canonical_return
        -> CanonicalMapping(canonical return, unplaced cells)

What is pinned here is the RE-ADDRESSING — our bundle member and class-named
sheet onto the published table code and sheet code — against the packaged
PRA001 taxonomy pack, which is compiled from the Bank of England's own DPM
files and is therefore an anchor our template generators cannot drift with
(LESSONS B3). Every frame is synthetic; the real estate is measured by
``scripts/filing_mapping_report.py``.

Key responsibilities:
- A cell is placed in the table whose reportable cells contain it: several
  published tables are row / column partitions of one of our frames.
- Our class-named sheet becomes the published sheet code, through the cited
  sheet maps; a per-country sheet becomes an open-axis member.
- NOTHING is dropped silently. Every reported cell is either placed or returned
  as unplaced with a reason — asserted as a conservation identity.
- A zero with no place loses nothing; a non-zero figure with no place is the
  real gap, and is counted apart.

References:
- src/rwa_calc/reporting/filing/canonical.py — the adapter under test
- Bank of England Banking Taxonomy v4.1.1 (PRA001)
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    REASON_CELL,
    REASON_COLUMN,
    REASON_OPEN_KEY,
    REASON_OPEN_ROWS,
    REASON_ROW,
    REASON_SHEET_COARSER,
    REASON_SHEET_UNPUBLISHED,
    UNPLACED_SCHEMA,
    build_canonical_return,
)
from rwa_filer.model import FACT_SCHEMA, ReturnHeader
from rwa_filer.taxonomy.pack import PackNotFoundError, resolve_pack
from rwa_filer.validate.structure import check_structure

from ._builders import build_corep, build_frame

FRAMEWORK = "BASEL_3_1"
REFERENCE_DATE = date(2027, 3, 31)
LEI = "5493001KJTIIGC8Y1R12"


def header(**overrides: Any) -> ReturnHeader:
    fields: dict[str, Any] = {
        "entity_identifier": LEI,
        "reference_date": REFERENCE_DATE,
        "module": FILING_MODULE,
    }
    fields.update(overrides)
    return ReturnHeader(**fields)


def mapping(**templates: Any):
    return build_canonical_return(build_corep(FRAMEWORK, **templates), header())


def placed(result) -> list[tuple]:
    return sorted(
        result.canonical.facts.select(
            "table", "sheet", "open_key", "row", "column", "value"
        ).rows(),
        key=repr,
    )


def unplaced(result) -> list[tuple]:
    return result.unplaced.select("template", "sheet", "row", "column", "value", "reason").rows()


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------


def test_a_class_named_sheet_becomes_its_published_sheet_code() -> None:
    # Arrange — our "corporate" SA sheet is Art. 112(1)(g): published sheet 0008.
    result = mapping(c07_00={"corporate": build_frame({"0010": {"0010": 100.0}})})

    # Act / Assert
    assert placed(result) == [("OF07.00.01.01", "0008", None, "0010", "0010", 100.0)]
    assert result.unplaced.is_empty()


def test_a_cell_is_placed_in_the_table_variant_that_holds_it() -> None:
    """Columns 0210/0211 of our one C 07.00 frame belong to table .02, not .01."""
    # Arrange
    result = mapping(c07_00={"corporate": build_frame({"0010": {"0010": 100.0, "0210": 7.0}})})

    # Act / Assert
    assert placed(result) == [
        ("OF07.00.01.01", "0008", None, "0010", "0010", 100.0),
        ("OF07.00.01.02", "0008", None, "0010", "0210", 7.0),
    ]


def test_a_single_sheet_template_has_no_sheet_code() -> None:
    # Arrange
    result = mapping(c_02_00=build_frame({"0010": {"0010": 1234.5}}))

    # Act / Assert
    assert placed(result) == [("OF02.00.01.01", None, None, "0010", "0010", 1234.5)]


def test_the_all_countries_sheet_becomes_the_total_member() -> None:
    # Arrange
    result = mapping(
        c09_01={
            "TOTAL": build_frame({"0010": {"0010": 100.0}}),
            "GB": build_frame({"0010": {"0010": 70.0}}),
        }
    )

    # Act / Assert
    assert placed(result) == [
        ("OF09.01.01.01", None, "GB", "0010", "0010", 70.0),
        ("OF09.01.01.01", None, "x1", "0010", "0010", 100.0),
    ]


def test_the_facts_are_in_the_canonical_schema_with_the_header_attached() -> None:
    # Act
    result = mapping(c07_00={"corporate": build_frame({"0010": {"0010": 100.0}})})

    # Assert
    assert result.canonical.facts.schema == FACT_SCHEMA
    assert result.canonical.header == header()
    assert result.unplaced.schema == UNPLACED_SCHEMA


def test_null_cells_and_label_columns_are_not_facts() -> None:
    # Arrange — a null figure, and a text label column beside the figures.
    frame = build_frame({"0010": {"0010": 100.0, "0030": None}}).with_columns(
        pl.lit("Total exposures").alias("row_name")
    )

    # Act
    result = mapping(c07_00={"corporate": frame})

    # Assert
    assert placed(result) == [("OF07.00.01.01", "0008", None, "0010", "0010", 100.0)]
    assert result.unplaced.is_empty()


def test_a_yes_no_cell_is_reported_as_true_or_false() -> None:
    """OF 02.00 row 0034, "output floor activated", is a boolean in the taxonomy."""
    # Arrange — our frames are numeric throughout: 1 is yes, 0 is no.
    activated = mapping(c_02_00=build_frame({"0034": {"0030": 1.0}}))
    inactive = mapping(c_02_00=build_frame({"0034": {"0030": 0.0}}))

    # Act
    rows = [
        result.canonical.facts.select("row", "column", "value", "text_value").row(0)
        for result in (activated, inactive)
    ]

    # Assert
    assert rows == [("0034", "0030", None, "true"), ("0034", "0030", None, "false")]


def test_a_number_that_is_not_yes_or_no_is_left_for_the_structure_check() -> None:
    # Arrange
    result = mapping(c_02_00=build_frame({"0034": {"0030": 0.5}}))

    # Act
    findings = check_structure(result.canonical, resolve_pack(FILING_MODULE, REFERENCE_DATE))

    # Assert — not silently coerced: reported as a value of the wrong type.
    assert result.canonical.facts["value"].to_list() == [0.5]
    assert [finding.code for finding in findings] == ["STR006"]


# ---------------------------------------------------------------------------
# What has no place, and why
# ---------------------------------------------------------------------------


def test_an_irb_sheet_spanning_several_published_sheets_cannot_be_placed() -> None:
    """Our "corporate" IRB sheet answers several published codes (by approach)."""
    # Arrange
    result = mapping(c08_01={"corporate": build_frame({"0010": {"0010": 100.0}})})

    # Act / Assert
    assert placed(result) == []
    assert unplaced(result) == [
        ("c08_01", "corporate", "0010", "0010", 100.0, REASON_SHEET_COARSER)
    ]


def test_an_irb_sheet_with_exactly_one_published_code_is_placed() -> None:
    # Arrange — "institution" is published sheet 0006 alone.
    result = mapping(c08_01={"institution": build_frame({"0010": {"0010": 100.0}})})

    # Act / Assert
    assert placed(result) == [("OF08.01.01.01", "0006", None, "0010", "0010", 100.0)]


def test_a_sheet_no_published_code_names_cannot_be_placed() -> None:
    # Arrange
    result = mapping(c07_00={"not_a_class": build_frame({"0010": {"0010": 1.0}})})

    # Act / Assert
    assert [row[-1] for row in unplaced(result)] == [REASON_SHEET_UNPUBLISHED]


def test_an_unknown_row_or_column_is_named_as_such() -> None:
    # Arrange
    result = mapping(
        c07_00={"corporate": build_frame({"9999": {"0010": 1.0}, "0010": {"9998": 2.0}})}
    )

    # Act
    reasons = {(row, column): reason for _t, _s, row, column, _v, reason in unplaced(result)}

    # Assert
    assert reasons == {("9999", "0010"): REASON_ROW, ("0010", "9998"): REASON_COLUMN}


def test_a_figure_in_a_cell_the_taxonomy_greys_is_not_reportable() -> None:
    """Row 0140 of OF 07.00 does not take the CRM substitution columns."""
    # Arrange
    result = mapping(
        c07_00={"central_govt_central_bank": build_frame({"0140": {"0010": 5.0, "0050": 3.0}})}
    )

    # Act / Assert
    assert placed(result) == [("OF07.00.01.01", "0002", None, "0140", "0010", 5.0)]
    assert unplaced(result) == [
        ("c07_00", "central_govt_central_bank", "0140", "0050", 3.0, REASON_CELL)
    ]


def test_a_country_the_open_axis_does_not_accept_cannot_be_placed() -> None:
    # Arrange
    result = mapping(c09_01={"ZZ": build_frame({"0010": {"0010": 1.0}})})

    # Act / Assert
    assert [row[-1] for row in unplaced(result)] == [REASON_OPEN_KEY]


def test_an_open_row_table_is_not_yet_mapped() -> None:
    # Arrange — OF 08.02 has no fixed rows; "institution" has one published sheet.
    result = mapping(c08_02={"institution": build_frame({"0.25% - 0.50%": {"0010": 1.0}})})

    # Act / Assert
    assert [row[-1] for row in unplaced(result)] == [REASON_OPEN_ROWS]


# ---------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------


def test_every_reported_cell_is_either_placed_or_accounted_for() -> None:
    """The conservation identity: nothing is dropped silently."""
    # Arrange — a mix of placeable, greyed, unknown and coarse-sheet cells.
    templates = {
        "c07_00": {
            "corporate": build_frame({"0010": {"0010": 1.0, "0210": 2.0, "9998": 3.0}}),
            "central_govt_central_bank": build_frame({"0140": {"0010": 4.0, "0050": 0.0}}),
        },
        "c08_01": {"corporate": build_frame({"0010": {"0010": 5.0, "0020": 6.0}})},
        "c_02_00": build_frame({"0010": {"0010": 7.0}, "9999": {"0010": 8.0}}),
    }
    frames = [
        frame
        for sheets in templates.values()
        for frame in ([sheets] if isinstance(sheets, pl.DataFrame) else sheets.values())
    ]
    reported = sum(frame.height * (frame.width - 1) for frame in frames)

    # Act
    result = mapping(**templates)

    # Assert
    assert reported == 9
    assert result.placed_cells + result.unplaced.height == reported


def test_a_zero_with_no_place_is_listed_but_is_not_a_gap() -> None:
    # Arrange — the same greyed cell, once with a zero and once with a figure.
    zero = mapping(c07_00={"central_govt_central_bank": build_frame({"0140": {"0050": 0.0}})})
    figure = mapping(c07_00={"central_govt_central_bank": build_frame({"0140": {"0050": 3.0}})})

    # Act / Assert
    assert zero.unplaced.height == 1 and zero.unplaced_figures.is_empty()
    assert figure.unplaced_figures.height == 1
    assert figure.unplaced_by_reason() == {("c07_00", REASON_CELL): 1}
    assert zero.unplaced_by_reason() == {}


def test_an_empty_bundle_yields_an_empty_return_and_nothing_unplaced() -> None:
    # Act
    result = mapping()

    # Assert
    assert result.canonical.facts.is_empty() and result.unplaced.is_empty()


# ---------------------------------------------------------------------------
# Usage errors
# ---------------------------------------------------------------------------


def test_the_estate_is_filed_under_pra001_only() -> None:
    with pytest.raises(ValueError, match=FILING_MODULE):
        build_canonical_return(build_corep(FRAMEWORK), header(module="LVR001"))


def test_a_reference_date_before_the_taxonomy_applies_has_no_pack() -> None:
    with pytest.raises(PackNotFoundError):
        build_canonical_return(build_corep(FRAMEWORK), header(reference_date=date(2026, 12, 31)))


def test_a_pack_may_be_supplied_explicitly() -> None:
    # Arrange
    pack = resolve_pack(FILING_MODULE, REFERENCE_DATE)

    # Act
    result = build_canonical_return(
        build_corep(FRAMEWORK, c_02_00=build_frame({"0010": {"0010": 1.0}})), header(), pack=pack
    )

    # Assert
    assert result.placed_cells == 1
