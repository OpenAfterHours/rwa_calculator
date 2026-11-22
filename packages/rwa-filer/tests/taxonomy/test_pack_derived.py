"""
``TaxonomyPack.derived``: the one home for a value worked out from a pack.

Pipeline position:
    load_pack  ->  TaxonomyPack  ->  pack.derived(build)  ->  the reader's fact index,
        the structure check's tables, anything else that is a function of the pack alone

Why this exists: a value kept "with the pack" can go wrong in ways a recomputed
one cannot. It can be kept somewhere that outlives the pack, or under a key
another pack later reuses; it can follow a pack through ``dataclasses.replace``
into an object whose fields differ; it can leak into the pack's equality or its
pickle; two threads can each end up holding their own. Each test below pins one
of those, on the small sample pack.
"""

from __future__ import annotations

import copy
import dataclasses
import gc
import pickle
import threading
import weakref
from typing import TYPE_CHECKING, Any

import pytest

from pack_builders import build_pack
from rwa_filer.taxonomy.pack import TaxonomyPack

if TYPE_CHECKING:
    from pathlib import Path

FIELD_NAMES = {field.name for field in dataclasses.fields(TaxonomyPack)}


class _Summary:
    """A stand-in derived value: what it was built from, and an identity of its own."""

    def __init__(self, pack: TaxonomyPack) -> None:
        self.tables = tuple(pack.tables)


class _Builds:
    """A builder that counts how often it is asked to build."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, pack: TaxonomyPack) -> _Summary:
        self.count += 1
        return _Summary(pack)


def _table_count(pack: TaxonomyPack) -> list[int]:
    return [len(pack.tables)]


def _outcome(action: Any) -> tuple[str, Any]:
    """What ``action`` returns, or the type and text of what it raises."""
    try:
        return ("returned", action())
    except Exception as error:  # noqa: BLE001 - the outcome before is the specification
        return ("raised", (type(error), str(error)))


# ---------------------------------------------------------------------------
# Built once, kept with the pack
# ---------------------------------------------------------------------------


def test_a_derived_value_is_built_once_and_handed_back_each_time(tmp_path: Path) -> None:
    # Arrange
    pack = build_pack(tmp_path)
    build = _Builds()

    # Act
    answers = [pack.derived(build) for _ in range(5)]

    # Assert
    assert build.count == 1
    assert all(answer is answers[0] for answer in answers)
    assert answers[0].tables == tuple(pack.tables)


def test_each_builder_keeps_its_own_value(tmp_path: Path) -> None:
    # Arrange
    pack = build_pack(tmp_path)

    # Act
    summary, count = pack.derived(_Summary), pack.derived(_table_count)

    # Assert
    assert isinstance(summary, _Summary) and count == [len(pack.tables)]
    assert pack.derived(_Summary) is summary and pack.derived(_table_count) is count


def test_each_pack_keeps_its_own_value(tmp_path: Path) -> None:
    # Arrange
    first, second = build_pack(tmp_path / "a"), build_pack(tmp_path / "b")
    build = _Builds()

    # Act
    kept = first.derived(build), second.derived(build)

    # Assert
    assert build.count == 2
    assert kept[0] is not kept[1]
    assert (first.derived(build), second.derived(build)) == kept


def test_a_builder_that_raises_keeps_nothing(tmp_path: Path) -> None:
    # Arrange
    pack = build_pack(tmp_path)
    attempts = []

    def build(_pack: TaxonomyPack) -> str:
        attempts.append(len(attempts))
        if len(attempts) == 1:
            raise RuntimeError("the first build fails")
        return "built"

    # Act
    with pytest.raises(RuntimeError, match="the first build fails"):
        pack.derived(build)
    second = pack.derived(build)

    # Assert
    assert second == "built" and attempts == [0, 1]


def test_a_derived_value_lives_exactly_as_long_as_its_pack(tmp_path: Path) -> None:
    """Nothing beside the pack holds the value: when the pack goes, so does it."""
    # Arrange
    pack = build_pack(tmp_path)
    value = weakref.ref(pack.derived(_Summary))
    assert value() is not None, "the value was not kept at all - there is nothing to outlive"

    # Act
    del pack
    gc.collect()

    # Assert
    assert value() is None


# ---------------------------------------------------------------------------
# A different pack object starts with nothing
# ---------------------------------------------------------------------------


def test_a_replaced_pack_starts_with_nothing_derived(tmp_path: Path) -> None:
    # Arrange
    pack = build_pack(tmp_path)
    build = _Builds()
    original = pack.derived(build)
    fewer = dict(list(pack.tables.items())[:2])

    # Act
    replaced = dataclasses.replace(pack, tables=fewer)
    rebuilt = replaced.derived(build)

    # Assert
    assert build.count == 2
    assert rebuilt.tables == tuple(fewer) != original.tables
    assert pack.derived(build) is original


def _through_pickle(pack: TaxonomyPack) -> TaxonomyPack:
    return pickle.loads(pickle.dumps(pack))


@pytest.mark.parametrize("duplicate", [copy.copy, copy.deepcopy, _through_pickle])
def test_a_copied_or_unpickled_pack_starts_with_nothing_derived(
    tmp_path: Path, duplicate: Any
) -> None:
    # Arrange
    pack = build_pack(tmp_path)
    build = _Builds()
    pack.derived(build)

    # Act
    twin = duplicate(pack)
    twin.derived(build)

    # Assert
    assert build.count == 2
    assert twin.datapoints == pack.datapoints and twin.cells.equals(pack.cells)
    assert set(vars(duplicate(pack))) == FIELD_NAMES


def test_a_pack_pickles_whatever_has_been_derived_from_it(tmp_path: Path) -> None:
    """A derived value need not be picklable: it is not part of the pack's pickle."""
    # Arrange
    pack = build_pack(tmp_path)
    lock = pack.derived(_lock)
    with pytest.raises(TypeError):
        pickle.dumps(lock)

    # Act
    twin = pickle.loads(pickle.dumps(pack))

    # Assert
    assert set(vars(twin)) == FIELD_NAMES
    assert twin.datapoints == pack.datapoints and twin.tables == pack.tables


def _lock(_pack: TaxonomyPack) -> Any:
    return threading.Lock()


# ---------------------------------------------------------------------------
# What a pack has derived is not part of what it is
# ---------------------------------------------------------------------------


def test_deriving_a_value_changes_nothing_the_pack_reports_about_itself(tmp_path: Path) -> None:
    """Its fields, its ``repr``, and whatever ``==`` and ``hash`` did before, they still do."""
    # Arrange
    pack = build_pack(tmp_path)
    twin = dataclasses.replace(pack)

    def reported() -> list[Any]:
        return [
            [field.name for field in dataclasses.fields(pack)],
            repr(pack),
            _outcome(lambda: pack == twin),
            _outcome(lambda: pack == pack),
            _outcome(lambda: hash(pack)),
        ]

    before = reported()

    # Act
    pack.derived(_Summary)

    # Assert
    assert set(vars(pack)) > FIELD_NAMES, "nothing was kept on the pack object"
    assert reported() == before


# ---------------------------------------------------------------------------
# Written once
# ---------------------------------------------------------------------------


def test_two_threads_that_build_at_once_are_handed_the_same_object(tmp_path: Path) -> None:
    # Arrange
    pack = build_pack(tmp_path)
    both_building = threading.Barrier(2, timeout=10)
    built: list[_Summary] = []
    handed: list[_Summary] = []

    def build(inner: TaxonomyPack) -> _Summary:
        # Neither thread returns until both are inside the builder, so neither
        # can find the other's value already kept.
        both_building.wait()
        value = _Summary(inner)
        built.append(value)
        return value

    def ask() -> None:
        handed.append(pack.derived(build))

    threads = [threading.Thread(target=ask) for _ in range(2)]

    # Act
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    # Assert
    assert len(built) == 2 and built[0] is not built[1], "the two builds did not overlap"
    assert len(handed) == 2 and handed[0] is handed[1]
    assert pack.derived(build) is handed[0]
