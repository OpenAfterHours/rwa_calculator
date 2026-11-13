"""The workbook layout: write a return, read it back, and get the same return."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from openpyxl import load_workbook

from pack_builders import build_header, build_pack, build_return
from rwa_filer.model import FACT_SCHEMA
from rwa_filer.readers import read_return
from rwa_filer.readers.excel import RETURN_SHEET, read_workbook, write_workbook
from rwa_filer.taxonomy.pack import TaxonomyPack


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path / "pack")


def facts(*rows: tuple[object, ...]) -> pl.DataFrame:
    names = FACT_SCHEMA.names()[: len(rows[0])]
    return pl.DataFrame(
        list(rows), schema={name: FACT_SCHEMA[name] for name in names}, orient="row"
    ).with_columns(pl.lit(None, dtype=FACT_SCHEMA["decimals"]).alias("decimals"))


#: A return touching every kind of table: single sheet, fixed sheets, open
#: sheets, open rows, and text / boolean / date cells.
FULL = facts(
    ("T01.00.01.01", None, None, "0010", "0010", 100.0, None),
    ("T01.00.01.01", None, None, "0010", "0030", None, "a comment"),
    ("T02.00.01.01", "0001", None, "0010", "0010", 60.0, None),
    ("T02.00.01.01", "0002", None, "0020", "0010", 50.0, None),
    ("T03.00.01.01", None, "GB", "0010", "0010", 70.0, None),
    ("T03.00.01.01", None, "x1", "0010", "0010", 100.0, None),
    ("T04.00.01.01", None, None, "1", "0005", 1.0, None),
    ("T04.00.01.01", None, None, "1", "0010", 5.0, None),
    ("T04.00.01.01", None, None, "2", "0005", 2.0, None),
    ("T04.00.01.01", None, None, "2", "0010", 6.0, None),
    ("T06.00.01.01", None, None, "0010", "0010", None, "true"),
    ("T06.00.01.01", None, None, "0010", "0020", None, "2027-03-31"),
)


def _sorted(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.sort(frame.columns, nulls_last=False)


def test_a_written_return_reads_back_as_the_same_return(pack: TaxonomyPack, tmp_path: Path) -> None:
    # Arrange
    ret = build_return(FULL, entity_name="Example Bank")
    path = tmp_path / "return.xlsx"

    # Act
    write_workbook(pack, path, ret=ret)
    back = read_workbook(path)

    # Assert
    assert back.header == ret.header
    assert _sorted(back.facts).equals(_sorted(ret.facts))


def test_one_worksheet_per_reported_table_sheet_and_open_key(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    # Act
    written = write_workbook(pack, tmp_path / "return.xlsx", ret=build_return(FULL))

    # Assert — T01, T02 x2 sheets, T03 x2 countries, T04, T06.
    assert written == 7


def test_a_blank_template_has_every_fixed_sheet_and_no_figures(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    # Arrange
    path = tmp_path / "blank.xlsx"

    # Act
    written = write_workbook(pack, path, tables=["T02.00.01.01", "T03.00.01.01"])
    back = read_workbook(path, build_header())

    # Assert — two fixed sheets of T02, one open-key sheet of T03 to copy.
    assert written == 3
    assert back.facts.is_empty()


def test_an_open_row_template_has_its_key_column_first(pack: TaxonomyPack, tmp_path: Path) -> None:
    """The key column reports no data point, but it is what a filer must fill in."""
    # Arrange
    path = tmp_path / "open.xlsx"

    # Act
    write_workbook(pack, path, tables=["T04.00.01.01"])
    worksheet = load_workbook(path).worksheets[-1]
    codes = [cell.value for cell in worksheet[5][2:]]

    # Assert
    assert codes == ["0005", "0010", "0020"]


def test_a_blank_template_shades_the_cells_the_taxonomy_does_not_accept(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    # Arrange
    path = tmp_path / "blank.xlsx"
    write_workbook(pack, path, tables=["T01.00.01.01"])

    # Act — row 0030 is the third data row (Excel row 9); column 0020 is column D.
    worksheet = load_workbook(path)["T01.00.01.01"]
    greyed = worksheet["D9"].fill.fgColor.rgb
    accepted = worksheet["C9"].fill.fgColor.rgb

    # Assert
    assert greyed == "FFBBBBBB"
    assert accepted != "FFBBBBBB"


def test_the_reader_goes_by_markers_not_by_worksheet_name(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    # Arrange — rename every table worksheet to something meaningless.
    path = tmp_path / "return.xlsx"
    write_workbook(pack, path, ret=build_return(FULL))
    workbook = load_workbook(path)
    for number, worksheet in enumerate(workbook.worksheets):
        if worksheet.title != RETURN_SHEET:
            worksheet.title = f"Tab {number}"
    workbook.save(path)

    # Act
    back = read_workbook(path)

    # Assert
    assert _sorted(back.facts).equals(_sorted(build_return(FULL).facts))


def test_codes_stored_as_numbers_get_their_leading_zeros_back(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    """A code typed into a spreadsheet is routinely stored as a number."""
    # Arrange
    path = tmp_path / "return.xlsx"
    write_workbook(pack, path, ret=build_return(FULL))
    workbook = load_workbook(path)
    worksheet = workbook["T02.00.01.01 z0001"]
    worksheet["B2"] = 1  # sheet code 0001
    worksheet["A7"] = 10  # row code 0010
    worksheet["C5"] = 10  # column code 0010
    workbook.save(path)

    # Act
    table = read_workbook(path).table_facts("T02.00.01.01").filter(pl.col("value") == 60.0)

    # Assert
    assert table.row(0)[:5] == ("T02.00.01.01", "0001", None, "0010", "0010")


def test_a_worksheet_without_a_table_marker_is_ignored(pack: TaxonomyPack, tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "return.xlsx"
    write_workbook(pack, path, ret=build_return(FULL))
    workbook = load_workbook(path)
    notes = workbook.create_sheet("Notes")
    notes.append(["Row", "anything", 123])
    notes.append([10, "looks like data", 999])
    workbook.save(path)

    # Act / Assert
    assert read_workbook(path).facts.height == FULL.height


def test_a_figure_typed_into_a_greyed_cell_is_read_so_structure_can_report_it(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    # Arrange
    path = tmp_path / "return.xlsx"
    write_workbook(pack, path, tables=["T01.00.01.01"])
    workbook = load_workbook(path)
    workbook["T01.00.01.01"]["D9"] = 0.5  # row 0030, column 0020: greyed
    workbook.save(path)

    # Act
    facts_read = read_workbook(path, build_header()).facts

    # Assert
    assert facts_read.row(0)[3:6] == ("0030", "0020", 0.5)


def test_a_header_argument_overrides_the_workbooks_own(pack: TaxonomyPack, tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "return.xlsx"
    write_workbook(pack, path, ret=build_return(FULL))
    other = build_header(currency="EUR")

    # Act / Assert
    assert read_return(path, other).header.currency == "EUR"


def test_a_blank_template_needs_a_header_from_somewhere(pack: TaxonomyPack, tmp_path: Path) -> None:
    """A blank Return sheet has no entity identifier; reading it says so."""
    # Arrange
    path = tmp_path / "blank.xlsx"
    write_workbook(pack, path, tables=["T01.00.01.01"])

    # Act / Assert
    with pytest.raises(ValueError, match="Entity identifier"):
        read_workbook(path)


def test_an_unknown_table_in_a_template_request_is_refused(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="ZZ99"):
        write_workbook(pack, tmp_path / "x.xlsx", tables=["ZZ99"])
