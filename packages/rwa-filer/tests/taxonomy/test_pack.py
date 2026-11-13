"""The taxonomy pack: write, load, and resolve by reference date."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from pack_builders import SAMPLE_COMPILED, SAMPLE_MODULE, build_pack
from rwa_filer.taxonomy.pack import (
    AXIS_FIXED,
    AXIS_OPEN,
    CELL_SCHEMA,
    CELLS_FILE,
    DATAPOINTS_FILE,
    MEMBER_OPEN,
    PACK_FILE,
    SOURCE_LINKBASE,
    DataPoint,
    PackInfo,
    PackNotFoundError,
    load_pack,
    select_pack,
    write_pack,
)

# ---------------------------------------------------------------------------
# Write and load
# ---------------------------------------------------------------------------


def test_a_written_pack_is_three_files(tmp_path: Path) -> None:
    # Act
    build_pack(tmp_path)

    # Assert
    assert sorted(p.name for p in tmp_path.iterdir()) == [CELLS_FILE, DATAPOINTS_FILE, PACK_FILE]


def test_pack_json_is_ascii_sorted_and_carries_the_validity_window(tmp_path: Path) -> None:
    # Act
    build_pack(tmp_path, valid_to=date(2027, 12, 31))
    text = (tmp_path / PACK_FILE).read_text(encoding="utf-8")
    payload = json.loads(text)

    # Assert
    assert text.isascii()
    assert list(payload) == sorted(payload)
    assert payload["info"]["valid_from"] == "2027-01-01"
    assert payload["info"]["valid_to"] == "2027-12-31"
    assert "cells" not in payload["tables"]["T01.00.01.01"], "cells belong in the Arrow file"


def test_load_restores_tables_axes_and_cells(tmp_path: Path) -> None:
    # Act
    pack = build_pack(tmp_path)

    # Assert
    assert pack.info.module == SAMPLE_MODULE
    assert sorted(pack.tables) == sorted(SAMPLE_COMPILED["tables"])
    assert pack.cells.schema == CELL_SCHEMA
    assert pack.cells.height == sum(len(t["cells"]) for t in SAMPLE_COMPILED["tables"].values())
    assert len(pack.datapoints) == len(SAMPLE_COMPILED["datapoints"])


def test_a_fixed_axis_lists_its_sheets_in_publisher_order(tmp_path: Path) -> None:
    # Act
    table = build_pack(tmp_path).tables["T02.00.01.01"]

    # Assert
    assert table.fixed_axis is not None and table.fixed_axis.kind == AXIS_FIXED
    assert table.open_axis is None
    assert table.sheet_codes == ("0001", "0002")
    assert table.fixed_axis.sheets[0].members == (("tst_dim:EXC", "tst_EC:x1"),)


def test_an_open_axis_names_its_dimension_and_members(tmp_path: Path) -> None:
    # Act
    table = build_pack(tmp_path).tables["T03.00.01.01"]

    # Assert
    assert table.fixed_axis is None and table.sheet_codes == ()
    assert table.open_axis is not None and table.open_axis.kind == AXIS_OPEN
    assert table.open_axis.dimension == "eba_dim:CEG"
    assert table.open_axis.members == ("eba_GA:x1", "eba_GA:GB", "eba_GA:FR")


def test_an_open_row_table_has_keys_and_no_row_codes(tmp_path: Path) -> None:
    # Act
    pack = build_pack(tmp_path)
    table = pack.tables["T04.00.01.01"]

    # Assert
    assert table.open_rows and table.row_codes == ()
    assert [key.dimension for key in table.open_keys] == ["tst_dim:OGR"]
    # The key column is filled in but reports no data point, so it is not a data column.
    assert table.key_codes == ("0005",) and "0005" not in table.column_codes
    assert [code for code, _label in table.entry_columns] == ["0005", "0010", "0020"]
    assert pack.cells.filter(pl.col("table") == "T04.00.01.01")["row"].null_count() == 2


def test_a_cell_resolves_to_its_data_point(tmp_path: Path) -> None:
    # Arrange
    pack = build_pack(tmp_path)

    # Act
    index = pack.cells.filter((pl.col("table") == "T03.00.01.01") & (pl.col("row") == "0010"))[
        "datapoint"
    ][0]

    # Assert
    assert pack.datapoint(index) == DataPoint("tst_met:mi4", (("eba_dim:CEG", MEMBER_OPEN),))


def test_one_data_point_may_sit_in_two_cells(tmp_path: Path) -> None:
    # Act
    cells = build_pack(tmp_path).cells.filter(pl.col("datapoint") == 16)

    # Assert
    assert sorted(cells["table"].to_list()) == ["T05.00.01.01", "T05.00.01.02"]


def test_the_source_of_each_cells_reportability_survives(tmp_path: Path) -> None:
    # Act
    cells = build_pack(tmp_path).cells

    # Assert
    assert cells.filter(pl.col("source") == SOURCE_LINKBASE).height == 1


def test_filing_indicators_are_distinct_and_sorted(tmp_path: Path) -> None:
    # Act
    indicators = build_pack(tmp_path).filing_indicators

    # Assert — the two T05 tables share one indicator.
    assert indicators == (
        "T01.00.01",
        "T02.00.01",
        "T03.00.01",
        "T04.00.01",
        "T05.00.01",
        "T06.00.01",
    )


def test_metrics_know_whether_they_carry_a_number(tmp_path: Path) -> None:
    # Act
    metrics = build_pack(tmp_path).metrics

    # Assert
    assert metrics["tst_met:mi1"].is_numeric and metrics["tst_met:pi1"].is_numeric
    assert metrics["tst_met:ii1"].is_numeric
    assert not metrics["tst_met:si1"].is_numeric and not metrics["tst_met:bi1"].is_numeric
    assert metrics["tst_met:ei1"].enumeration == "tst_ZZ:ZZ1"


def test_writing_twice_gives_the_same_content(tmp_path: Path) -> None:
    # Act
    first = build_pack(tmp_path / "a")
    second = build_pack(tmp_path / "b")

    # Assert
    assert (tmp_path / "a" / PACK_FILE).read_bytes() == (tmp_path / "b" / PACK_FILE).read_bytes()
    assert first.cells.equals(second.cells)
    assert first.datapoints == second.datapoints


def test_an_unknown_compiled_format_is_refused(tmp_path: Path) -> None:
    # Arrange
    compiled = {**SAMPLE_COMPILED, "format": 99}

    # Act / Assert
    with pytest.raises(ValueError, match="format"):
        write_pack(compiled, tmp_path, valid_from=date(2027, 1, 1))


def test_a_pack_in_an_unreadable_format_is_refused(tmp_path: Path) -> None:
    # Arrange
    build_pack(tmp_path)
    payload = json.loads((tmp_path / PACK_FILE).read_text(encoding="utf-8"))
    payload["format"] = 99
    (tmp_path / PACK_FILE).write_text(json.dumps(payload), encoding="utf-8")

    # Act / Assert
    with pytest.raises(ValueError, match="not supported"):
        load_pack(tmp_path)


# ---------------------------------------------------------------------------
# Resolution by reference date
# ---------------------------------------------------------------------------


def _info(version: str, valid_from: date, valid_to: date | None = None) -> PackInfo:
    return PackInfo("PRA001", "Own funds", "boe-banking", version, "http://x", valid_from, valid_to)


def test_a_reference_date_selects_the_release_in_force() -> None:
    # Arrange
    old = _info("4.0.0", date(2026, 1, 1), date(2026, 12, 31))
    new = _info("4.1.1", date(2027, 1, 1))

    # Act / Assert
    assert select_pack([old, new], "PRA001", date(2026, 6, 30)) is old
    assert select_pack([old, new], "pra001", date(2027, 3, 31)) is new


def test_the_validity_window_is_inclusive_at_both_ends() -> None:
    # Arrange
    info = _info("4.0.0", date(2026, 1, 1), date(2026, 12, 31))

    # Act / Assert
    assert info.applies_to(date(2026, 1, 1)) and info.applies_to(date(2026, 12, 31))
    assert not info.applies_to(date(2025, 12, 31)) and not info.applies_to(date(2027, 1, 1))


def test_no_pack_for_the_date_names_what_is_packaged() -> None:
    # Arrange
    infos = [_info("4.1.1", date(2027, 1, 1))]

    # Act / Assert
    with pytest.raises(PackNotFoundError, match=r"PRA001 4\.1\.1 \(2027-01-01 to onwards\)"):
        select_pack(infos, "PRA001", date(2026, 12, 31))


def test_an_unknown_module_is_not_found() -> None:
    with pytest.raises(PackNotFoundError, match="LVR001"):
        select_pack([_info("4.1.1", date(2027, 1, 1))], "LVR001", date(2027, 3, 31))


def test_overlapping_releases_resolve_to_the_later_one() -> None:
    # Arrange
    first = _info("4.1.0", date(2027, 1, 1))
    second = _info("4.1.1", date(2027, 1, 1))

    # Act / Assert
    assert select_pack([first, second], "PRA001", date(2027, 6, 30)) is second


def test_the_pack_key_is_module_and_version_lower_cased() -> None:
    assert _info("4.1.1", date(2027, 1, 1)).key == "pra001-4.1.1"
