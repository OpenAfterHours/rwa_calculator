"""
Structure findings carry every fact they are about, uncapped.

A finding's message quotes the first few cells so it stays readable; triage
needs all of them. ``Finding.positions`` holds every one, with what it holds
and, where it differs fact by fact, what is wrong with it; the report counts
them (``positions_total``) and the evidence export lists them.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from boe_builders import T01
from pack_builders import build_pack, build_return
from rwa_filer.evidence import collect_evidence, read_evidence, write_evidence
from rwa_filer.model import CanonicalReturn
from rwa_filer.taxonomy.pack import TaxonomyPack
from rwa_filer.validate.report import to_record
from rwa_filer.validate.structure import (
    FINDING_CELL_NOT_REPORTABLE,
    FINDING_DUPLICATE_FACT,
    FINDING_UNKNOWN_TABLE,
    FINDING_VALUE_TYPE,
    MAX_EXAMPLES,
    check_structure,
)

SCHEMA = {
    "table": pl.String,
    "sheet": pl.String,
    "open_key": pl.String,
    "row": pl.String,
    "column": pl.String,
    "value": pl.Float64,
    "text_value": pl.String,
}
#: More stray rows than a message quotes.
STRAYS = [(T01, None, None, f"9{index}00", "0010", float(index), None) for index in range(7)]


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path / "pack")


def facts(*rows: tuple[object, ...]) -> CanonicalReturn:
    return build_return(pl.DataFrame(list(rows), schema=SCHEMA, orient="row"))


def test_every_fact_in_an_unreportable_cell_is_a_position(pack: TaxonomyPack) -> None:
    # Arrange — adequacy: more than the message quotes.
    assert len(STRAYS) > MAX_EXAMPLES

    # Act
    (finding,) = check_structure(facts(*STRAYS), pack)

    # Assert
    assert finding.code == FINDING_CELL_NOT_REPORTABLE
    assert f"(first {MAX_EXAMPLES} of {len(STRAYS)})" in finding.message
    assert [(p.table, p.row, p.column, p.value) for p in finding.positions] == [
        (T01, row, column, value) for _t, _s, _k, row, column, value, _x in STRAYS
    ]


def test_a_position_says_what_is_wrong_with_that_fact(pack: TaxonomyPack) -> None:
    # Arrange — a cell reported twice, and a number in a text cell.
    ret = facts(
        (T01, None, None, "0010", "0010", 1.0, None),
        (T01, None, None, "0010", "0010", 1.0, None),
        (T01, None, None, "0010", "0030", 5.0, None),
    )

    # Act
    found = {finding.code: finding for finding in check_structure(ret, pack)}

    # Assert
    (duplicate,) = found[FINDING_DUPLICATE_FACT].positions
    assert (duplicate.row, duplicate.column, duplicate.detail) == (
        "0010",
        "0010",
        "reported 2 times",
    )
    (wrong_type,) = found[FINDING_VALUE_TYPE].positions
    assert wrong_type.column == "0030" and wrong_type.detail.startswith("the cell takes a ")


def test_every_fact_of_a_table_the_module_lacks_is_a_position(pack: TaxonomyPack) -> None:
    # Act
    (finding,) = check_structure(
        facts(*[("T99.00.01.01", None, None, f"00{i}0", "0010", 1.0, None) for i in range(1, 4)]),
        pack,
    )

    # Assert
    assert finding.code == FINDING_UNKNOWN_TABLE
    assert [p.row for p in finding.positions] == ["0010", "0020", "0030"]


def test_the_report_counts_the_positions_and_the_evidence_lists_them(
    pack: TaxonomyPack, tmp_path: Path
) -> None:
    # Arrange
    ret = facts(*STRAYS)
    evidence = collect_evidence(ret, pack)

    # Act
    record = to_record(ret, evidence.validation)
    document = read_evidence(write_evidence(evidence, tmp_path / "evidence.jsonl").path)

    # Assert
    (stray,) = [item for item in record["findings"] if item["code"] == FINDING_CELL_NOT_REPORTABLE]
    assert stray["positions_total"] == len(STRAYS)
    index = next(
        item["index"] for item in document.findings if item["code"] == FINDING_CELL_NOT_REPORTABLE
    )
    listed = [item for item in document.structure_exceptions if item["finding"] == index]
    assert sorted(item["position"]["row"] for item in listed) == sorted(s[3] for s in STRAYS)
