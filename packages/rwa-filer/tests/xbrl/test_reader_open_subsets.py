"""
The XBRL reader and a fact carrying many open dimensions: a bounded search.

Pipeline position:
    read_instance  ->  reader._place  ->  _DataPointIndex.match(fact)

Why this exists: a data point may leave a dimension open for the filer to
choose. To match a fact, the reader considers which of the fact's dimensions
could be such choices, and tries the subsets of them. It used to try EVERY
subset: a fact carrying k dimensions that some data point of the module leaves
open cost 2**k tries — 65,536 at sixteen, about a second per fact at the
eighteen PRA001 has, so a file with a few hundred such facts stalled the reader
for minutes. No valid fact looks like that; a malformed or hostile file can,
and reporting such facts is what the reader is for.

No data point leaves more than a handful of dimensions open (two, in every
packaged pack that leaves any), and a fact cannot be matched by supplying more
dimensions than its data point leaves open. So subsets larger than that are
never tried. The tests count subsets, not seconds, and pin the two ways the
bound could be wrong: one too small (a valid fact supplying the most a data
point allows stops matching) and undefined (a pack that leaves nothing open).
"""

from __future__ import annotations

import dataclasses
from math import comb
from typing import TYPE_CHECKING

import polars as pl
import pytest

from pack_builders import build_pack
from reader_builders import HandFact, instance_of
from rwa_filer.taxonomy.pack import CELL_SCHEMA, DataPoint, TaxonomyPack
from rwa_filer.xbrl import reader
from rwa_filer.xbrl.reader import FINDING_UNKNOWN_DATAPOINT, InstanceReading, read_instance

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

OPEN_DIMENSIONS = [f"tst_dim:D{number:02d}" for number in range(1, 17)]
#: The most dimensions any data point of ``many_open_pack`` leaves open.
MOST_OPEN = 2

TWO_SUPPLIED = HandFact(
    "tst_met:mi1", ((OPEN_DIMENSIONS[0], "tst_BA:x1"), (OPEN_DIMENSIONS[1], "tst_BA:x2")), "20"
)
ONE_SUPPLIED = HandFact("tst_met:mi1", ((OPEN_DIMENSIONS[2], "tst_BA:x1"),), "10")
SIXTEEN_SUPPLIED = HandFact(
    "tst_met:mi1", tuple((dimension, "tst_BA:x1") for dimension in OPEN_DIMENSIONS), "160"
)


@pytest.fixture
def many_open_pack(tmp_path: Path) -> TaxonomyPack:
    """Sixteen dimensions left open somewhere; no data point leaves more than two open.

    Data point 0 leaves the first two open and is shown in row 0010; data point
    1 leaves the third open and is shown in row 0020; the rest leave one each.
    """
    points = [
        DataPoint("tst_met:mi1", ((OPEN_DIMENSIONS[0], "*open"), (OPEN_DIMENSIONS[1], "*open"))),
        *(DataPoint("tst_met:mi1", ((dimension, "*open"),)) for dimension in OPEN_DIMENSIONS[2:]),
    ]
    cells = [
        ("T01.00.01.01", "0010", "0010", None, 0, "workbook"),
        ("T01.00.01.01", "0020", "0010", None, 1, "workbook"),
    ]
    return dataclasses.replace(
        build_pack(tmp_path),
        datapoints=tuple(points),
        cells=pl.DataFrame(cells, schema=CELL_SCHEMA, orient="row"),
    )


def _count_subsets(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count every subset the reader goes on to try; the list grows by one per subset."""
    tried: list[int] = []
    choose = reader.combinations

    def counting(candidates: list[str], size: int) -> Iterator[tuple[str, ...]]:
        for subset in choose(candidates, size):
            tried.append(size)
            yield subset

    monkeypatch.setattr(reader, "combinations", counting)
    return tried


def _rows(reading: InstanceReading) -> list[tuple[object, ...]]:
    return reading.ret.facts.select("row", "value").sort("row").rows()


def _subsets_up_to(candidates: int, largest: int) -> int:
    return sum(comb(candidates, size) for size in range(min(candidates, largest) + 1))


def test_a_fact_carrying_sixteen_open_dimensions_tries_a_bounded_number_of_subsets(
    many_open_pack: TaxonomyPack, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    tried = _count_subsets(monkeypatch)
    content = instance_of(many_open_pack, [TWO_SUPPLIED, SIXTEEN_SUPPLIED, ONE_SUPPLIED])
    allowed = sum(_subsets_up_to(supplied, MOST_OPEN) for supplied in (2, 16, 1))
    assert allowed == 4 + 137 + 2

    # Act
    reading = read_instance(content, pack=many_open_pack)

    # Assert — the two valid facts are placed, so the search ran and found what is there.
    assert _rows(reading) == [("0010", 20.0), ("0020", 10.0)]
    assert len(tried) <= allowed, (
        f"{len(tried)} subsets tried for three facts, one of them carrying 16 open dimensions"
    )


def test_a_fact_carrying_too_many_open_dimensions_is_reported_as_no_data_point(
    many_open_pack: TaxonomyPack,
) -> None:
    """The finding the unbounded search reached, a second per fact later."""
    # Arrange
    content = instance_of(many_open_pack, [TWO_SUPPLIED, SIXTEEN_SUPPLIED, ONE_SUPPLIED])

    # Act
    reading = read_instance(content, pack=many_open_pack)

    # Assert
    (finding,) = reading.findings
    (position,) = finding.positions
    members = ", ".join(f"{dimension}=tst_BA:x1" for dimension in OPEN_DIMENSIONS)
    assert finding.code == FINDING_UNKNOWN_DATAPOINT
    assert finding.actual == "1 fact(s)"
    assert (position.source_ref, position.value) == (f"tst_met:mi1[{members}]", 160.0)


def test_a_fact_supplying_as_many_dimensions_as_a_data_point_leaves_open_is_matched(
    many_open_pack: TaxonomyPack,
) -> None:
    """The largest subset that can match is still tried: the bound is not one too small."""
    # Arrange
    index = reader._index_of(many_open_pack)
    members = tuple(
        sorted((dimension, (member, None)) for dimension, member in TWO_SUPPLIED.members)
    )
    assert len(members) == MOST_OPEN

    # Act
    matched = index.match(reader._Fact(TWO_SUPPLIED.metric, members, 20.0, None, 0))

    # Assert
    assert matched == [0]


def test_a_pack_that_leaves_nothing_open_tries_one_subset_per_fact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """There is no largest open set to take the bound from; the empty subset is still tried."""
    # Arrange
    closed = dataclasses.replace(
        build_pack(tmp_path),
        datapoints=(DataPoint("tst_met:mi1", (("tst_dim:BAS", "tst_BA:x1"),)),),
        cells=pl.DataFrame(
            [("T01.00.01.01", "0010", "0010", None, 0, "workbook")],
            schema=CELL_SCHEMA,
            orient="row",
        ),
    )
    tried = _count_subsets(monkeypatch)
    placed = HandFact("tst_met:mi1", (("tst_dim:BAS", "tst_BA:x1"),), "5")
    unknown = HandFact("tst_met:mi1", (("tst_dim:BAS", "tst_BA:x2"),), "6")

    # Act
    reading = read_instance(instance_of(closed, [placed, unknown]), pack=closed)

    # Assert
    assert _rows(reading) == [("0010", 5.0)]
    assert [finding.code for finding in reading.findings] == [FINDING_UNKNOWN_DATAPOINT]
    assert tried == [0, 0]
