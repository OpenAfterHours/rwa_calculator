"""
The XBRL reader's data-point index: one per pack, small, read-only and exact.

Pipeline position:
    TaxonomyPack  ->  pack.derived(reader._index_of)  ->  _DataPointIndex.match(fact)
        ->  reader._place  ->  the cells of a CanonicalReturn

Why this exists: the reader finds the data point a fact reports through an
index over every data point of the module. It used to build that index afresh
for every file it read — half a second and 110 MB for PRA001, twice for a
comparison of two files, once per file a dashboard opens. The index is now built
once and kept with the pack, which moves the risk from cost to correctness:

- a kept index that is too big, or that the garbage collector has to walk, is
  paid for by every later collection in the process and again at exit;
- an index kept under the wrong key answers for another pack;
- an index shared by every reader, on every thread, must never change;
- and the compact form keys a data point by a sorted tuple of its fixed members
  where the old form used a set, so a pack whose members are not sorted, or a
  data point that shares its key with another, is where it could diverge.

The exactness test is a property that needs no second implementation to compare
with: every data point of every packaged pack, written as a fact, is matched to
exactly itself.
"""

from __future__ import annotations

import dataclasses
import gc
import threading
import tracemalloc
from typing import TYPE_CHECKING

import polars as pl
import pytest

from pack_builders import build_pack
from reader_builders import HandFact, instance_of
from rwa_filer.release import resolve_release
from rwa_filer.taxonomy.pack import (
    CELL_SCHEMA,
    MEMBER_OPEN_OPTIONAL,
    MEMBER_TYPED_PREFIX,
    DataPoint,
    TaxonomyPack,
    available_packs,
    load_packaged,
)
from rwa_filer.validate.identity import facts_sha256
from rwa_filer.xbrl import reader
from rwa_filer.xbrl.reader import InstanceReading, read_instance

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

#: The collector-tracked objects an index may keep alive. The form it replaced
#: kept 240,322 for PRA001; this one keeps at most a dictionary per metric (293
#: on CPython 3.14, and none on 3.13, which stops tracking a dictionary whose
#: keys and values it need not walk).
MAX_TRACKED_OBJECTS = 2_000
#: The memory an index may keep. The form it replaced kept 110 MB for PRA001;
#: this one keeps under 5 MB.
MAX_INDEX_BYTES = 16 * 1024 * 1024

AMOUNT = HandFact("tst_met:mi1", (("tst_dim:BAS", "tst_BA:x1"),), "1500")
OTHER_AMOUNT = HandFact("tst_met:mi1", (("tst_dim:BAS", "tst_BA:x2"),), "25")
NO_DATA_POINT = HandFact("tst_met:mi1", (("tst_dim:BAS", "tst_BA:x9"),), "7")


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path)


def _count_builds(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count every index constructed from here on; the list grows by one per build."""
    built: list[int] = []
    construct = reader._DataPointIndex.__init__

    def counting(self: object, *args: object, **kwargs: object) -> None:
        built.append(1)
        construct(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(reader._DataPointIndex, "__init__", counting)
    return built


def _placed(reading: InstanceReading) -> list[tuple[object, ...]]:
    coordinates = ["table", "sheet", "open_key", "row", "column"]
    return reading.ret.facts.select(*coordinates, "value").sort(coordinates).rows()


def _as_fact(point: DataPoint, *, optional_absent: bool = False) -> reader._Fact:
    """``point`` as a fact reporting it: a member for every dimension, open ones supplied."""
    members: list[tuple[str, tuple[str, str | None]]] = []
    for dimension, member in point.dimensions:
        if member == MEMBER_OPEN_OPTIONAL and optional_absent:
            continue
        if member.startswith(MEMBER_TYPED_PREFIX):
            members.append((dimension, ("a key", member[len(MEMBER_TYPED_PREFIX) :])))
        elif member.startswith("*"):
            members.append((dimension, ("any:member", None)))
        else:
            members.append((dimension, (member, None)))
    return reader._Fact(point.metric, tuple(sorted(members)), 1.0, None, 0)


def _with_datapoints(pack: TaxonomyPack, points: list[DataPoint]) -> TaxonomyPack:
    """``pack`` with ``points`` as its data points and no cell showing them: for matching alone."""
    return dataclasses.replace(
        pack, datapoints=tuple(points), cells=pl.DataFrame(schema=CELL_SCHEMA)
    )


# ---------------------------------------------------------------------------
# One index per pack
# ---------------------------------------------------------------------------


def test_reading_many_files_against_one_pack_builds_its_index_once(
    pack: TaxonomyPack, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    built = _count_builds(monkeypatch)
    files = [instance_of(pack, [AMOUNT]), instance_of(pack, [OTHER_AMOUNT, NO_DATA_POINT])]

    # Act
    readings = [read_instance(content, pack=pack) for content in (*files, *files)]

    # Assert
    assert [len(_placed(reading)) for reading in readings] == [1, 1, 1, 1], "nothing was read"
    assert len(built) == 1, f"the index was built {len(built)} times for four reads of one pack"


def test_each_pack_object_has_an_index_of_its_own(
    pack: TaxonomyPack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Equal content is not the same pack: nothing is kept under a name or a digest."""
    # Arrange
    built = _count_builds(monkeypatch)
    twin = dataclasses.replace(pack)
    content = instance_of(pack, [AMOUNT])

    # Act
    for target in (pack, twin, pack, twin):
        read_instance(content, pack=target)

    # Assert
    assert twin is not pack
    assert twin.datapoints is pack.datapoints
    assert len(built) == 2, f"{len(built)} indexes built for two packs"


def test_a_pack_differing_only_in_its_data_points_is_read_through_its_own_index(
    pack: TaxonomyPack,
) -> None:
    """Same module, same version, same tables — and the fact belongs in another row."""
    # Arrange — the two packs show BAS=x1 in row 0010 and in row 0020.
    points = list(pack.datapoints)
    points[0], points[3] = points[3], points[0]
    swapped = dataclasses.replace(pack, datapoints=tuple(points))
    content = instance_of(pack, [AMOUNT])
    assert swapped.info == pack.info

    # Act
    rows = [
        [row[3] for row in _placed(read_instance(content, pack=target))]
        for target in (pack, swapped, pack)
    ]

    # Assert
    assert rows == [["0010"], ["0020"], ["0010"]]


def test_two_threads_reading_at_once_end_with_one_index_and_equal_readings(
    pack: TaxonomyPack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both threads find no index yet and both build one; one is kept, and both read alike."""
    # Arrange — each thread waits inside the build for the other to arrive there.
    content = instance_of(pack, [AMOUNT, OTHER_AMOUNT, NO_DATA_POINT])
    build: Callable[[TaxonomyPack], reader._DataPointIndex] = reader._index_of
    both_building = threading.Barrier(2, timeout=30)
    built: list[reader._DataPointIndex] = []
    racing = True

    def build_together(target: TaxonomyPack) -> reader._DataPointIndex:
        if racing:
            both_building.wait()
        index = build(target)
        built.append(index)
        return index

    monkeypatch.setattr(reader, "_index_of", build_together)
    readings: list[InstanceReading] = []
    failures: list[BaseException] = []

    def read() -> None:
        try:
            readings.append(read_instance(content, pack=pack))
        except BaseException as error:  # noqa: BLE001 - reported by the assertion below
            failures.append(error)

    threads = [threading.Thread(target=read) for _ in range(2)]

    # Act
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    racing = False
    raced = len(built)
    readings.append(read_instance(content, pack=pack))

    # Assert
    assert failures == []
    assert raced == 2, f"{raced} index(es) built by the two threads: their reads did not overlap"
    assert len(built) == 2, "a read after the race built another index: none was kept"
    assert any(pack.derived(build_together) is index for index in built)
    assert len(readings) == 3
    assert {facts_sha256(reading.ret) for reading in readings} == {facts_sha256(readings[0].ret)}
    assert {reading.findings for reading in readings} == {readings[0].findings}
    assert [len(_placed(reading)) for reading in readings] == [2, 2, 2]


# ---------------------------------------------------------------------------
# Small, and nothing for the collector to walk
# ---------------------------------------------------------------------------


def test_the_index_of_the_largest_pack_keeps_almost_nothing_the_collector_tracks() -> None:
    """Every later collection in the process walks what is kept, and so does exit."""
    # Arrange
    pra001 = resolve_release("PRA001").pack
    assert len(pra001.datapoints) > 50_000, "a small pack cannot show what a large index costs"
    gc.collect()
    before = len(gc.get_objects())

    # Act
    index = reader._index_of(pra001)
    gc.collect()
    kept = len(gc.get_objects()) - before

    # Assert
    assert index.match(_as_fact(pra001.datapoints[0])) == [0], "the index does not answer"
    assert kept < MAX_TRACKED_OBJECTS, (
        f"the index keeps {kept} collector-tracked objects alive for the life of the process"
    )


def test_the_index_of_the_largest_pack_is_kept_in_a_few_megabytes() -> None:
    """Strings and tuples are not tracked by the collector, so a count of objects misses them."""
    # Arrange
    pra001 = resolve_release("PRA001").pack
    assert len(pra001.datapoints) > 50_000, "a small pack cannot show what a large index costs"
    gc.collect()
    already_tracing = tracemalloc.is_tracing()
    tracemalloc.start()
    before, _peak = tracemalloc.get_traced_memory()

    # Act
    try:
        index = reader._index_of(pra001)
        kept, _peak = tracemalloc.get_traced_memory()
    finally:
        if not already_tracing:
            tracemalloc.stop()

    # Assert
    assert index.match(_as_fact(pra001.datapoints[0])) == [0], "the index does not answer"
    assert kept - before < MAX_INDEX_BYTES, (
        f"the index keeps {(kept - before) / 1e6:.1f} MB for the life of the process"
    )


def test_reading_leaves_the_index_exactly_as_it_was_built(pack: TaxonomyPack) -> None:
    """It is shared by every reader of the pack, on every thread."""
    # Arrange
    index = pack.derived(reader._index_of)
    as_built = dataclasses.asdict(index)
    content = instance_of(pack, [AMOUNT, OTHER_AMOUNT, NO_DATA_POINT])

    # Act
    reading = read_instance(content, pack=pack)

    # Assert
    assert len(_placed(reading)) == 2
    assert len(reading.findings) == 1
    assert pack.derived(reader._index_of) is index
    assert dataclasses.asdict(index) == as_built
    with pytest.raises(dataclasses.FrozenInstanceError):
        index.most_open = 9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Exact: a fact finds its own data point, and only that
# ---------------------------------------------------------------------------


def test_every_data_point_of_every_packaged_pack_is_matched_to_exactly_itself() -> None:
    """Written as a fact, and again with each optional open member left out."""
    # Arrange
    packs = [load_packaged(info.key) for info in available_packs()]
    assert len(packs) >= 14, "packs are missing from the package"

    # Act
    tried = two_open = 0
    wrong: list[tuple[str, int]] = []
    for target in packs:
        index = reader._index_of(target)
        for number, point in enumerate(target.datapoints):
            placeholders = [member for _dimension, member in point.dimensions if member[:1] == "*"]
            facts = [_as_fact(point)]
            if MEMBER_OPEN_OPTIONAL in placeholders:
                facts.append(_as_fact(point, optional_absent=True))
            tried += len(facts)
            two_open += len(placeholders) >= 2
            if any(index.match(fact) != [number] for fact in facts):
                wrong.append((target.info.module, number))

    # Assert
    assert tried > 85_000, "the packaged packs were not walked"
    assert two_open > 100, "no data point leaves two dimensions open - the bound is not tried"
    assert wrong == []


def test_data_points_sharing_fixed_members_are_matched_in_data_point_order(
    pack: TaxonomyPack,
) -> None:
    """Whatever order a pack lists a data point's members in, and with one listed twice."""
    # Arrange
    a, b = ("tst_dim:AAA", "tst_BA:x1"), ("tst_dim:BBB", "tst_BA:x2")
    points = [
        DataPoint("tst_met:mi1", (b, a)),  # 0: out of order
        DataPoint("tst_met:mi1", (a, b)),  # 1: in order - the same members as 0
        DataPoint("tst_met:mi2", (a, b)),  # 2: another metric
        DataPoint("tst_met:mi1", (a, a, b)),  # 3: one member twice - the same members again
        DataPoint("tst_met:mi1", (("tst_dim:AAA", "*open"), b)),  # 4: leaves AAA open
        DataPoint("tst_met:mi1", (b, ("tst_dim:AAA", "*open?"))),  # 5: AAA optional, out of order
        DataPoint("tst_met:mi1", (b,)),  # 6: shares the key of 4 and 5, fixes nothing else
    ]
    index = reader._index_of(_with_datapoints(pack, points))
    both = reader._Fact(
        "tst_met:mi1", (("tst_dim:AAA", (a[1], None)), (b[0], (b[1], None))), 1, "", 0
    )
    unsorted = reader._Fact("tst_met:mi1", ((b[0], (b[1], None)), (a[0], (a[1], None))), 1, "", 0)
    only_b = reader._Fact("tst_met:mi1", ((b[0], (b[1], None)),), 1, "", 0)

    # Act
    matches = [index.match(fact) for fact in (both, unsorted, only_b)]

    # Assert
    assert matches == [[0, 1, 3, 4, 5], [0, 1, 3, 4, 5], [5, 6]]


def test_an_open_dimension_is_matched_only_by_the_kind_of_member_it_asks_for(
    pack: TaxonomyPack,
) -> None:
    """A typed value in the element the data point names, or a listed member — not the other."""
    # Arrange
    points = [
        DataPoint("tst_met:mi1", (("tst_dim:AAA", "*typed:tst_typ:ID"),)),
        DataPoint("tst_met:mi1", (("tst_dim:AAA", "*open"),)),
    ]
    index = reader._index_of(_with_datapoints(pack, points))
    supplied: list[tuple[str, str | None]] = [
        ("5", "tst_typ:ID"),
        ("5", "tst_typ:OTHER"),
        ("tst_BA:x1", None),
    ]

    # Act
    matches = [
        index.match(reader._Fact("tst_met:mi1", (("tst_dim:AAA", value),), 1.0, None, 0))
        for value in supplied
    ]

    # Assert
    assert matches == [[0], [], [1]]


def test_a_typed_value_spelling_a_fixed_members_name_does_not_match_it(
    pack: TaxonomyPack,
) -> None:
    """A member a data point fixes is a listed one; a typed value is never that member."""
    # Arrange
    points = [DataPoint("tst_met:mi1", (("tst_dim:BAS", "tst_BA:x1"),))]
    index = reader._index_of(_with_datapoints(pack, points))
    listed = reader._Fact("tst_met:mi1", (("tst_dim:BAS", ("tst_BA:x1", None)),), 1.0, None, 0)
    typed = reader._Fact(
        "tst_met:mi1", (("tst_dim:BAS", ("tst_BA:x1", "tst_typ:ID")),), 1.0, None, 0
    )

    # Act
    matches = [index.match(listed), index.match(typed)]

    # Assert
    assert matches == [[0], []]
