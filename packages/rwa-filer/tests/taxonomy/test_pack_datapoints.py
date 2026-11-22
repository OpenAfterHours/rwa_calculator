"""
The data-point build, checked element for element against a row-by-row reference.

Pipeline position:
    taxonomy/data/<module>-<version>/datapoints.arrow
        ->  pack._datapoints_from_frame  ->  TaxonomyPack.datapoints

Why this exists: the loader does not build a pack's data points one row at a
time. It numbers the distinct (dimension, member) pairs and hands every data
point the same pair objects, which is most of what a cold load used to cost. A
builder that got the ORDER of a data point's pairs wrong would pass every other
test of this package and its behaviour snapshot, because every consumer sorts
the pairs or puts them in a set. Only a direct comparison can see it, so this
file makes one: every data point of every packaged pack, same value, same types,
same ``hash()``.

``_row_by_row`` is the loader as it stood before that change, kept HERE rather
than in the package so the reference and the code under test cannot drift
together. It also defines what a damaged frame must do: whatever it returns or
raises, the loader returns or raises the same.
"""

from __future__ import annotations

import io
import random
from importlib import resources
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest

from rwa_filer.taxonomy.pack import (
    DATAPOINT_SCHEMA,
    DATAPOINTS_FILE,
    PACKS_DIRECTORY,
    PACKS_PACKAGE,
    DataPoint,
    _datapoints_from_frame,
    available_packs,
    load_packaged,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

#: Every packaged pack: the equality below is claimed for all of them, not for PRA001.
PACKAGED_KEYS = sorted(info.key for info in available_packs())
#: The largest pack, where nearly all of the cost was: the newest PRA001.
PRA001_KEY = max(key for key in PACKAGED_KEYS if key.startswith("pra001-"))


# ---------------------------------------------------------------------------
# The reference, and how two builds are compared
# ---------------------------------------------------------------------------


def _row_by_row(frame: pl.DataFrame) -> tuple[DataPoint, ...]:
    """The data points read one row at a time: the loader before pairs were shared."""
    ordered = frame.sort("datapoint")
    indices = ordered["datapoint"].to_list()
    if indices != list(range(len(indices))):
        raise ValueError("Taxonomy pack data points are not densely indexed from 0")
    return tuple(
        DataPoint(metric, tuple(zip(dimensions, members, strict=True)))
        for metric, dimensions, members in zip(
            ordered["metric"].to_list(),
            ordered["dimensions"].to_list(),
            ordered["members"].to_list(),
            strict=True,
        )
    )


def _types(points: Sequence[DataPoint]) -> list[Any]:
    """The type of every object a build is made of, in order."""
    return [
        type(points),
        *(
            (
                type(point),
                type(point.metric),
                type(point.dimensions),
                [(type(pair), *(type(part) for part in pair)) for pair in point.dimensions],
            )
            for point in points
        ),
    ]


def _outcome(build: Callable[[pl.DataFrame], tuple[DataPoint, ...]], frame: pl.DataFrame) -> Any:
    """What ``build`` does with ``frame``: its value, types and hashes, or what it raised."""
    try:
        points = build(frame)
    except Exception as error:  # noqa: BLE001 - whatever the reference raises is the specification
        return ("raised", type(error), str(error))
    return ("built", points, _types(points), [hash(point) for point in points])


def _packaged_frame(key: str) -> pl.DataFrame:
    """A packaged pack's data-point table, read straight from its Arrow file."""
    resource = resources.files(PACKS_PACKAGE).joinpath(PACKS_DIRECTORY, key, DATAPOINTS_FILE)
    return pl.read_ipc(io.BytesIO(resource.read_bytes()))


def _frame(rows: list[tuple[Any, ...]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=DATAPOINT_SCHEMA, orient="row")


# ---------------------------------------------------------------------------
# Every packaged pack
# ---------------------------------------------------------------------------


def test_the_comparison_covers_more_than_one_packaged_pack() -> None:
    """A parametrised test over an empty list passes by running nothing."""
    assert PRA001_KEY in PACKAGED_KEYS and len(PACKAGED_KEYS) > 1


@pytest.mark.parametrize("key", PACKAGED_KEYS)
def test_every_data_point_of_a_packaged_pack_equals_the_row_by_row_reference(key: str) -> None:
    # Arrange
    expected = _row_by_row(_packaged_frame(key))
    assert any(point.dimensions != point.dimensions[::-1] for point in expected), (
        "no data point of this pack has two different pairs - a build that got "
        "their order wrong would be invisible here"
    )

    # Act
    built = load_packaged(key).datapoints

    # Assert
    assert built == expected
    assert _types(built) == _types(expected)
    assert [hash(point) for point in built] == [hash(point) for point in expected]


@pytest.mark.parametrize("key", PACKAGED_KEYS)
def test_equal_pairs_of_a_packaged_pack_are_one_shared_object(key: str) -> None:
    """The cost gate: one tuple per distinct pair, however many data points name it.

    A count, not a clock. PRA001 names 518,270 pairs of which 1,442 are distinct;
    built row by row it holds 518,270 tuples for the life of the process.
    """
    # Arrange
    points = load_packaged(key).datapoints
    named = sum(len(point.dimensions) for point in points)
    values = {pair for point in points for pair in point.dimensions}
    assert named > len(values) > 0, "no pair is named twice - there is nothing to share"

    # Act
    objects = {id(pair) for point in points for pair in point.dimensions}

    # Assert
    assert len(objects) == len(values)


def test_a_table_already_in_index_order_is_not_sorted_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A count of sorts by the index: none for a packaged table, one for a shuffled copy.

    Sorting a table copies every list in it; a written pack is already in order.
    """
    # Arrange
    in_order = _packaged_frame(PRA001_KEY)
    shuffled = in_order.sample(fraction=1.0, shuffle=True, seed=7)
    assert shuffled["datapoint"].to_list() != in_order["datapoint"].to_list()
    sorted_by: list[Any] = []
    sort = pl.DataFrame.sort

    def recording(frame: pl.DataFrame, by: Any, *more: Any, **options: Any) -> pl.DataFrame:
        sorted_by.append(by)
        return sort(frame, by, *more, **options)

    monkeypatch.setattr(pl.DataFrame, "sort", recording)

    # Act
    _datapoints_from_frame(in_order)
    for_the_table_in_order = sorted_by.count("datapoint")
    _datapoints_from_frame(shuffled)
    for_both = sorted_by.count("datapoint")

    # Assert
    assert for_both - for_the_table_in_order == 1, "the recorder does not see a sort by the index"
    assert for_the_table_in_order == 0


def test_a_polars_whose_explode_has_no_empty_list_argument_gives_the_same_shared_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loader on an older Polars, stood in for here because the suite runs on one version.

    Before ``explode`` took ``empty_as_null`` it refused the argument and turned
    an empty list into a row holding a null. Every packaged pack has data points
    with no pairs, so a loader that met that explode unprepared would either fail
    or quietly fall back to building every pair again.
    """
    # Arrange
    frame = _packaged_frame(PRA001_KEY)
    expected = _row_by_row(frame)
    assert any(not point.dimensions for point in expected), "the pack has no empty list"
    explode = pl.DataFrame.explode
    refused: list[str] = []

    def as_it_was(table: pl.DataFrame, *columns: Any, **options: Any) -> pl.DataFrame:
        if options:
            refused.extend(options)
            raise TypeError(f"explode() got an unexpected keyword argument {next(iter(options))!r}")
        try:
            return explode(table, *columns, empty_as_null=True)
        except TypeError:
            # The installed Polars is itself one that predates the argument,
            # and its explode already behaves as the stand-in means to.
            return explode(table, *columns)

    monkeypatch.setattr(pl.DataFrame, "explode", as_it_was)

    # Act
    built = _datapoints_from_frame(frame)

    # Assert
    assert refused == ["empty_as_null"], "the loader did not meet the older explode"
    assert built == expected
    assert len({id(pair) for point in built for pair in point.dimensions}) == len(
        {pair for point in built for pair in point.dimensions}
    )


# ---------------------------------------------------------------------------
# Frames no packaged pack has
# ---------------------------------------------------------------------------


def test_an_empty_frame_gives_no_data_points() -> None:
    # Arrange
    frame = _frame([])

    # Act
    built = _datapoints_from_frame(frame)

    # Assert
    assert built == ()
    assert type(built) is tuple


#: Frames the loader must read exactly as the row-by-row reference does.
_READABLE: dict[str, pl.DataFrame] = {
    "empty": _frame([]),
    "one point, no pairs": _frame([(0, "m:a", [], [])]),
    "every list empty": _frame([(0, "m:a", [], []), (1, "m:b", [], [])]),
    "unsorted, with an empty list": _frame(
        [
            (1, "m:b", ["d:x", "d:y"], ["a", "b"]),
            (0, "m:a", ["d:x"], ["a"]),
            (2, "m:c", [], []),
        ]
    ),
    "pairs not in dimension order": _frame(
        [(0, "m:a", ["d:z", "d:x", "d:y"], ["c", "a", "b"]), (1, "m:b", ["d:y", "d:x"], ["b", "a"])]
    ),
    "one pair twice in a data point": _frame(
        [(0, "m:a", ["d:x", "d:x"], ["a", "a"]), (1, "m:b", ["d:x"], ["a"])]
    ),
    "empty strings": _frame([(0, "m:a", ["", "d:y"], ["", ""])]),
    "a member that equals a dimension": _frame([(0, "m:a", ["a", "b"], ["b", "a"])]),
    "a null inside the dimensions": _frame([(0, "m:a", [None, "d:y"], ["a", "b"])]),
    "a null inside the members": _frame([(0, "m:a", ["d:x", "d:y"], ["a", None])]),
    "unsorted, an empty list and an inner null": _frame(
        [(2, "m:c", ["d:x", None], ["a", "b"]), (0, "m:a", [], []), (1, "m:b", ["d:x"], ["a"])]
    ),
    "a null metric": _frame([(0, None, ["d:x"], ["a"])]),
    "a column the loader does not read": _frame([(0, "m:a", ["d:x"], ["a"])]).with_columns(
        pl.lit("ignored").alias("note")
    ),
    "an index of floats": pl.DataFrame(
        {"datapoint": [1.0, 0.0], "metric": ["m:b", "m:a"]}
    ).with_columns(
        pl.Series("dimensions", [["d:x"], []], dtype=pl.List(pl.String)),
        pl.Series("members", [["a"], []], dtype=pl.List(pl.String)),
    ),
    "an index of booleans": pl.DataFrame(
        {"datapoint": [False, True], "metric": ["m:a", "m:b"]}
    ).with_columns(
        pl.Series("dimensions", [["d:x"], []], dtype=pl.List(pl.String)),
        pl.Series("members", [["a"], []], dtype=pl.List(pl.String)),
    ),
    "lists of numbers": pl.DataFrame(
        {"datapoint": [0, 1], "metric": ["m:a", "m:b"], "dimensions": [[1, 2], [3]]}
    ).with_columns(pl.Series("members", [["a", "b"], ["c"]], dtype=pl.List(pl.String))),
    "text where a list belongs": pl.DataFrame(
        {"datapoint": [0], "metric": ["m:a"], "dimensions": ["xy"], "members": ["ab"]}
    ),
    "lists of an untyped null": pl.DataFrame(
        {"datapoint": [0, 1], "metric": ["m:a", "m:b"], "dimensions": [[], []], "members": [[], []]}
    ),
}

#: Frames the reference refuses, with the kind of error it raises. The loader
#: must raise the same type with the same text.
_REFUSED: dict[str, tuple[pl.DataFrame, type[Exception]]] = {
    "more members than dimensions": (_frame([(0, "m:a", ["d:x"], ["a", "b"])]), ValueError),
    "fewer members than dimensions": (
        _frame([(0, "m:a", ["d:x"], ["a"]), (1, "m:b", ["d:x", "d:y"], ["a"])]),
        ValueError,
    ),
    "a member with no dimension at all": (_frame([(0, "m:a", [], ["a"])]), ValueError),
    "a null dimension list": (_frame([(0, "m:a", None, ["a"])]), TypeError),
    "a null member list": (_frame([(0, "m:a", ["d:x"], None)]), TypeError),
    "both lists null": (
        _frame([(0, "m:a", None, None), (1, "m:b", ["d:x"], ["a"])]),
        TypeError,
    ),
    "an index with a gap": (
        _frame([(0, "m:a", ["d:x"], ["a"]), (2, "m:b", ["d:x"], ["a"])]),
        ValueError,
    ),
    "an index that starts at one": (_frame([(1, "m:a", ["d:x"], ["a"])]), ValueError),
    "an index number used twice": (
        _frame([(0, "m:a", ["d:x"], ["a"]), (0, "m:b", ["d:x"], ["a"])]),
        ValueError,
    ),
    "a null index number": (
        _frame([(None, "m:a", ["d:x"], ["a"]), (0, "m:b", ["d:x"], ["a"])]),
        ValueError,
    ),
    "an index of text": (
        pl.DataFrame({"datapoint": ["0", "1"], "metric": ["m:a", "m:b"]}).with_columns(
            pl.Series("dimensions", [["d:x"], []], dtype=pl.List(pl.String)),
            pl.Series("members", [["a"], []], dtype=pl.List(pl.String)),
        ),
        ValueError,
    ),
    "no index column": (
        _frame([(0, "m:a", ["d:x"], ["a"])]).drop("datapoint"),
        pl.exceptions.ColumnNotFoundError,
    ),
    "no metric column": (
        _frame([(0, "m:a", ["d:x"], ["a"])]).drop("metric"),
        pl.exceptions.ColumnNotFoundError,
    ),
    "no dimensions column": (
        _frame([(0, "m:a", ["d:x"], ["a"])]).drop("dimensions"),
        pl.exceptions.ColumnNotFoundError,
    ),
    "no members column": (
        _frame([(0, "m:a", ["d:x"], ["a"])]).drop("members"),
        pl.exceptions.ColumnNotFoundError,
    ),
    "neither metric nor list columns": (
        _frame([(0, "m:a", ["d:x"], ["a"])]).select("datapoint"),
        pl.exceptions.ColumnNotFoundError,
    ),
}


@pytest.mark.parametrize("case", sorted(_READABLE))
def test_a_frame_no_pack_has_is_read_as_the_reference_reads_it(case: str) -> None:
    # Arrange
    frame = _READABLE[case]
    expected = _outcome(_row_by_row, frame)
    assert expected[0] == "built", "the reference refuses this frame - it belongs in _REFUSED"

    # Act
    actual = _outcome(_datapoints_from_frame, frame)

    # Assert
    assert actual == expected


@pytest.mark.parametrize("case", sorted(_REFUSED))
def test_a_frame_the_reference_refuses_is_refused_with_the_same_error(case: str) -> None:
    # Arrange
    frame, error = _REFUSED[case]
    expected = _outcome(_row_by_row, frame)
    assert expected[:2] == ("raised", error), "the reference reads this frame after all"

    # Act
    actual = _outcome(_datapoints_from_frame, frame)

    # Assert
    assert actual == expected


def test_generated_frames_are_read_as_the_reference_reads_them() -> None:
    """Shapes the packs do not have: shuffled indices, repeats, runs of empty lists."""
    # Arrange
    rng = random.Random(20261122)
    frames = [_generated(rng) for _ in range(200)]
    indices = [frame["datapoint"].to_list() for frame in frames]
    sizes = [frame["dimensions"].list.len().to_list() for frame in frames]
    assert any(index != sorted(index) for index in indices), "no generated frame is unsorted"
    assert any(0 in size for size in sizes), "no generated frame has an empty list"
    assert any(max(size, default=0) >= 3 for size in sizes), "no generated point has three pairs"

    # Act
    differing = [
        number
        for number, frame in enumerate(frames)
        if _outcome(_datapoints_from_frame, frame) != _outcome(_row_by_row, frame)
    ]

    # Assert
    assert differing == []


def _generated(rng: random.Random) -> pl.DataFrame:
    """A regular frame of up to 40 data points over a small vocabulary, in any row order."""
    count = rng.randint(0, 40)
    rows = []
    for number in range(count):
        size = rng.choice((0, 0, 1, 2, 3, 5))
        dimensions = [f"d:{rng.randint(0, 5)}" for _ in range(size)]
        members = [rng.choice(("a", "b", "c", "*open", "")) for _ in range(size)]
        rows.append((number, f"m:{rng.randint(0, 3)}", dimensions, members))
    if rng.random() < 0.7:
        rng.shuffle(rows)
    return _frame(rows)
