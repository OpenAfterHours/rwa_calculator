"""A supplied group is the same return at every entry point, regardless of the unit evidence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import polars as pl
import pytest

from detail_builders import HEADER_ARGS, HEADER_FIELDS, group_files
from rwa_filer.cli import main
from rwa_filer.readers import DetailSpec, open_source

if TYPE_CHECKING:
    from pathlib import Path


FLAGS = ["--breakdown", "reporting_unit", "--group-code", "Group"]


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    return group_files(tmp_path)


@pytest.mark.parametrize("suffix", [".csv", ".parquet"])
def test_group_facts_keep_their_values_types_order_and_missing_cells(
    files: tuple[Path, Path], suffix: str
) -> None:
    plain, combined = files
    if suffix == ".parquet":
        frame = pl.read_csv(combined, infer_schema=False)
        combined = combined.with_suffix(suffix)
        frame.write_parquet(combined)
    spec = DetailSpec.from_text("Reporting_Unit", group_code="Group")
    source = open_source(combined, HEADER_FIELDS, detail=spec)
    assert source.ret.facts.equals(open_source(plain, HEADER_FIELDS).ret.facts)
    assert source.detail is not None
    assert source.detail.members("reporting_unit") == ("Commercial", "Partial", "Retail")
    commercial = source.detail.member_facts("reporting_unit", "Commercial")
    assert commercial["text_value"].drop_nulls().to_list() == ["Commercial wording"]


def test_cli_group_findings_and_filing_match_group_alone(
    files: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plain, combined = files
    reports = []
    for path, flags in ((plain, []), (combined, FLAGS)):
        main(["validate", str(path), *HEADER_ARGS, *flags, "--format", "json"])
        reports.append(json.loads(capsys.readouterr().out))
        main(
            [
                "build",
                str(path),
                *HEADER_ARGS,
                *flags,
                "--out",
                str(tmp_path / path.stem),
                "--name",
                "return",
                "--force",
                "--no-timestamp",
            ]
        )
        capsys.readouterr()
    assert reports[0]["findings"] == reports[1]["findings"]
    breakdown = reports[1]["breakdown"]
    assert breakdown["detail"]["group_code"] == "Group"
    assert {row["text_value"] for row in breakdown["text_cells"]} == {
        "Group wording",
        "Retail wording",
        "Commercial wording",
    }
    breaks = [b for b in breakdown["by"][0]["broken"] if b["rule_id"] == "boe_b0708"]
    assert breaks
    assert breaks[0]["breaking"] == ["Commercial"]
    assert abs(breaks[0]["unexplained"]) == 10
    assert not next(s for s in breaks[0]["members"] if s["member"] == "Partial")["evaluated"]
    assert (tmp_path / "group/return.xbrl").read_bytes() == (
        tmp_path / "combined/return.xbrl"
    ).read_bytes()
    assert (
        json.loads((tmp_path / "combined/return.manifest.json").read_text())["detail"]["group_code"]
        == "Group"
    )


def test_unknown_group_cannot_turn_into_an_empty_return(files: tuple[Path, Path]) -> None:
    with pytest.raises(ValueError, match="Missing"):
        open_source(
            files[1],
            HEADER_FIELDS,
            detail=DetailSpec.from_text("reporting_unit", group_code="Missing"),
        )
    with pytest.raises(ValueError, match="breakdown"):
        DetailSpec.from_text(group_code="Group")


def test_each_unit_can_supply_its_own_percentage_and_unit_only_cells_stay_out_of_the_return(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rates.csv"
    path.write_text(
        "table,sheet,row,column,value,area\n"
        "OF08.01.01.01,0001,0001,0010,0.025,G\n"
        "OF08.01.01.01,0001,0001,0010,0.01,Retail\n"
        "OF08.01.01.01,0001,0001,0010,0.04,Commercial\n"
        "OF08.01.01.01,0001,0001,0020,100,Commercial\n"
    )
    source = open_source(path, HEADER_FIELDS, detail=DetailSpec.from_text("area", group_code="G"))
    assert source.ret.facts.select("column", "value").rows() == [("0010", 0.025)]
    assert source.detail is not None
    commercial = source.detail.member_facts("area", "Commercial")
    assert commercial.select("column", "value").rows() == [("0010", 0.04), ("0020", 100)]


def test_numeric_open_row_keys_are_never_added_like_amounts(tmp_path: Path) -> None:
    path = tmp_path / "grades.csv"
    path.write_text(
        "table,sheet,row,column,value,area\n"
        "OF08.02.01.01,0001,0010,0005,1,A\n"
        "OF08.02.01.01,0001,0010,0005,1,B\n"
    )
    with pytest.raises(ValueError, match="row identifier"):
        open_source(path, HEADER_FIELDS, detail=DetailSpec(breakdown=("area",)))


def test_duplicate_group_facts_remain_visible_to_structure_validation(tmp_path: Path) -> None:
    from rwa_filer.validate.returns import validate_return

    path = tmp_path / "duplicate.csv"
    path.write_text(
        "table,sheet,row,column,value,area,ref\n"
        "OF07.00.01.01,0008,0010,0010,1,G,X\n"
        "OF07.00.01.01,0008,0010,0010,1,G,X\n"
        "OF07.00.01.01,0008,0010,0010,1,A,X\n"
        "OF07.00.01.01,0008,0010,0010,1,B,X\n"
    )
    spec = DetailSpec.from_text("area", "ref", "keep-one", "G")
    source = open_source(path, HEADER_FIELDS, detail=spec)
    assert source.ret.facts.height == 2
    assert "STR005" in {
        f.code for f in validate_return(source.ret, release=source.release).structure
    }


def test_unit_only_errors_do_not_block_a_clean_group_build(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    combined = tmp_path / "clean.csv"
    combined.write_text(
        "table,sheet,row,column,value,reporting_unit\n"
        "OF07.00.01.01,0008,0010,0010,0,Group\n"
        "OF07.00.01.01,0008,0010,0010,n/a,Retail\n"
    )
    code = main(
        [
            "build",
            str(combined),
            *HEADER_ARGS,
            *FLAGS,
            "--out",
            str(tmp_path),
            "--name",
            "clean-group",
            "--no-timestamp",
        ]
    )
    assert code == 0, capsys.readouterr().err
    assert (tmp_path / "clean-group.xbrl").is_file()


def test_group_open_rows_follow_obligor_grade_across_local_row_numbers(tmp_path: Path) -> None:
    path = tmp_path / "grades.csv"
    table = "OF08.02.01.01"
    path.write_text(
        "table,sheet,row,column,value,area\n"
        + "".join(
            f"{table},0001,{row},0005,{grade},{unit}\n{table},0001,{row},0040,{amount},{unit}\n"
            for unit, row, grade, amount in (
                ("Group", "0010", 1, 100),
                ("A", "0090", 1, 40),
                ("B", "0010", 2, 60),
            )
        )
    )
    source = open_source(
        path, HEADER_FIELDS, detail=DetailSpec.from_text("area", group_code="Group")
    )
    assert source.detail is not None
    cell = (table, "0001", None, "0010", "0040")
    assert source.detail.cell_rows(cell).select("area", "value").rows() == [("A", 40)]
    assert (
        source.detail.member_facts("area", "A").filter(pl.col("column") == "0005")["value"].item()
        == 1
    )
