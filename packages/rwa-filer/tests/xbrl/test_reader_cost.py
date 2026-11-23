"""
What reading an XBRL instance costs: counted, not timed.

Pipeline position:
    instance bytes  ->  read_instance (collector paused)
        ->  _parse (one scope per set of namespace declarations)
        ->  _distinct_facts (a context's members worked out once per context)
        ->  _place  ->  InstanceReading

Why this exists: none of what these tests pin shows in any output. A reader
that rebuilds its prefix table for every element, re-derives a context's
members for every fact that uses it, or lets the garbage collector re-walk the
half-read file a few hundred times, returns exactly the same reading — later.
The reader did all three, and no test noticed. So each saving has a gate
of its own, and none of them reads a clock: a count of function calls at two
file sizes, a count of scopes built, a count of contexts worked out, and a count
of collector passes.

Each count is asserted beside a statement that the measured path ran — the
facts were read and placed — so a test cannot pass by reading nothing.
"""

from __future__ import annotations

import gc
import re
import sys
import threading
from typing import TYPE_CHECKING, Any

import pytest

from pack_builders import build_pack
from reader_builders import many_rows_return
from rwa_filer.xbrl import reader
from rwa_filer.xbrl.reader import InstanceFormatError, InstanceReading, read_instance
from rwa_filer.xbrl.writer import write_instance

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from rwa_filer.taxonomy.pack import TaxonomyPack

#: Four times the facts may cost at most this many times the function calls.
MAX_CALL_RATIO = 4.4
SMALL_ROWS = 300
LARGE_ROWS = 4 * SMALL_ROWS


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path)


@pytest.fixture(autouse=True)
def _collector() -> Iterator[None]:
    """Put the collector back as the session had it, whatever a test did to it."""
    was_enabled = gc.isenabled()
    yield
    if was_enabled:
        gc.enable()
    else:
        gc.disable()


def _instance(pack: TaxonomyPack, rows: int) -> bytes:
    """``rows`` open rows: two facts and one context each."""
    return write_instance(many_rows_return(rows), pack).content


def _redeclaring_on_each_fact(content: bytes, pack: TaxonomyPack) -> tuple[bytes, bytes]:
    """``content`` with every fact declaring its own prefix, to the namespace the root gives it.

    Returns the rewritten file and the declaration it repeats.
    """
    prefix = next(iter(pack.metrics)).partition(":")[0]
    declaration = f' xmlns:{prefix}="{pack.namespaces[prefix]}"'.encode()
    start_tag = re.compile(rb"(<" + re.escape(prefix.encode()) + rb":\w+)")
    return start_tag.sub(lambda match: match.group(1) + declaration, content), declaration


def _calls_to_read(content: bytes, pack: TaxonomyPack) -> tuple[int, InstanceReading]:
    """Read ``content`` and count the function calls it took, Python and built-in alike."""
    count = 0

    def watch(_frame: Any, event: str, _argument: object) -> None:
        nonlocal count
        if event in ("call", "c_call"):
            count += 1

    previous = sys.getprofile()
    sys.setprofile(watch)
    try:
        reading = read_instance(content, pack=pack)
    finally:
        sys.setprofile(previous)
    return count, reading


def _count_calls(monkeypatch: pytest.MonkeyPatch, owner: object, name: str) -> list[int]:
    """Count calls of ``owner.name`` from here on; the list grows by one per call."""
    calls: list[int] = []
    original = getattr(owner, name)

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, counting)
    return calls


# ---------------------------------------------------------------------------
# Cost grows with the file, and no faster
# ---------------------------------------------------------------------------


def test_four_times_the_facts_cost_under_four_point_four_times_the_function_calls(
    pack: TaxonomyPack,
) -> None:
    # Arrange — a first read builds the pack's index, which is not a cost of either file.
    small, large = _instance(pack, SMALL_ROWS), _instance(pack, LARGE_ROWS)
    read_instance(small, pack=pack)

    # Act
    small_calls, small_reading = _calls_to_read(small, pack)
    large_calls, large_reading = _calls_to_read(large, pack)

    # Assert — every fact of both files was read and placed, keys included.
    for rows, reading in ((SMALL_ROWS, small_reading), (LARGE_ROWS, large_reading)):
        assert (reading.facts, reading.ret.facts.height) == (2 * rows, 3 * rows)
        assert reading.findings == ()
    assert small_calls > 10 * SMALL_ROWS, "the read was not measured"
    ratio = large_calls / small_calls
    assert ratio < MAX_CALL_RATIO, (
        f"4x the facts cost {ratio:.2f}x the function calls ({small_calls} -> {large_calls})"
    )


def test_a_file_declaring_its_namespaces_on_the_root_builds_one_scope(
    pack: TaxonomyPack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not one per element: a filing has thousands of elements and one set of prefixes."""
    # Arrange
    content = _instance(pack, SMALL_ROWS)
    scopes = _count_calls(monkeypatch, reader, "_Scope")

    # Act
    reading = read_instance(content, pack=pack)

    # Assert
    assert reading.facts == 2 * SMALL_ROWS
    assert reading.findings == ()
    assert len(scopes) == 1, f"{len(scopes)} scopes built for a file with one set of prefixes"


def test_a_file_repeating_the_roots_declaration_on_every_fact_still_builds_one_scope(
    pack: TaxonomyPack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A declaration that changes nothing is no new set of prefixes.

    Some writers declare a fact's own prefix on the fact, every time, with the
    namespace the root already gives it. A scope per such declaration copied the
    whole declaration list once per fact — 20,000 facts read in about 8 s and
    1.77 GB, against 0.8 s for the same facts declared once on the root. The
    function-call ratio above does not see this: the copy is one built-in call
    however long the list it copies.
    """
    # Arrange
    plain = _instance(pack, SMALL_ROWS)
    content, declaration = _redeclaring_on_each_fact(plain, pack)
    expected = read_instance(plain, pack=pack)
    scopes = _count_calls(monkeypatch, reader, "_Scope")

    # Act
    reading = read_instance(content, pack=pack)

    # Assert — the file repeats the root's declaration on every fact, and reads as without it.
    assert plain.count(declaration) == 1, "the root does not declare the facts' prefix"
    assert content.count(declaration) == 1 + reading.facts == 1 + 2 * SMALL_ROWS
    assert reading.findings == ()
    assert reading.ret.facts.equals(expected.ret.facts)
    assert len(scopes) == 1, (
        f"{len(scopes)} scopes built for a file whose {reading.facts} redeclarations change nothing"
    )


def test_a_context_shared_by_several_facts_is_worked_out_once(
    pack: TaxonomyPack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its members in the pack's prefixes, sorted: the same for every fact that refers to it."""
    # Arrange
    content = _instance(pack, SMALL_ROWS)
    contexts = content.count(b"<xbrli:context ")
    worked_out = _count_calls(monkeypatch, reader, "_members_in_pack_prefixes")

    # Act
    reading = read_instance(content, pack=pack)

    # Assert
    assert reading.facts == 2 * SMALL_ROWS
    assert reading.findings == ()
    assert contexts == SMALL_ROWS + 1, "the file does not share a context between facts"
    assert 0 < len(worked_out) <= contexts, (
        f"members worked out {len(worked_out)} times for {contexts} contexts "
        f"and {reading.facts} facts"
    )


# ---------------------------------------------------------------------------
# The collector does not run while a file is read
# ---------------------------------------------------------------------------


class _Assembly:
    """Stands in for ``InstanceReading`` and notes the collector as the reading is assembled.

    ``read_instance`` assembles the reading as its last step, with everything
    read and placed. What is noted there is what happened DURING the read; the
    collector may run the moment the pause ends, which is not the pause's to prevent.
    """

    def __init__(self) -> None:
        # Only passes started on the thread that builds are this build's: under
        # pytest-xdist another test file's thread may still call gc.collect().
        self.thread = threading.get_ident()
        self.passes: list[int] = []
        self.enabled_at_assembly: bool | None = None
        self.passes_at_assembly: list[int] | None = None

    def watch(self, phase: str, info: dict[str, int]) -> None:
        if phase == "start" and threading.get_ident() == self.thread:
            self.passes.append(info["generation"])

    def __call__(self, **fields: Any) -> InstanceReading:
        self.enabled_at_assembly = gc.isenabled()
        self.passes_at_assembly = list(self.passes)
        return InstanceReading(**fields)


def _read_noting_the_collector(
    monkeypatch: pytest.MonkeyPatch, content: bytes, pack: TaxonomyPack
) -> tuple[_Assembly, InstanceReading]:
    """Read ``content`` and say what the collector did while it was read."""
    assembly = _Assembly()
    monkeypatch.setattr(reader, "InstanceReading", assembly)
    gc.callbacks.append(assembly.watch)
    try:
        reading = read_instance(content, pack=pack)
    finally:
        gc.callbacks.remove(assembly.watch)
    return assembly, reading


def test_no_collection_of_any_generation_runs_while_a_file_is_read(
    pack: TaxonomyPack, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    content = _instance(pack, LARGE_ROWS)
    gc.enable()

    # Act
    assembly, reading = _read_noting_the_collector(monkeypatch, content, pack)

    # Assert
    assert reading.facts == 2 * LARGE_ROWS
    assert assembly.passes_at_assembly == []
    assert assembly.enabled_at_assembly is False


def test_the_same_read_with_the_pause_disarmed_does_run_the_collector(
    pack: TaxonomyPack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the test above: its zero is the pause's doing, not the file's size."""
    # Arrange
    content = _instance(pack, LARGE_ROWS)
    gc.enable()
    monkeypatch.setattr(gc, "disable", lambda: None)

    # Act
    assembly, reading = _read_noting_the_collector(monkeypatch, content, pack)

    # Assert
    assert reading.facts == 2 * LARGE_ROWS
    assert assembly.enabled_at_assembly is True
    assert assembly.passes_at_assembly, "an unpaused read of this file starts no collection"


@pytest.mark.parametrize("was_enabled", [True, False])
def test_a_read_leaves_the_collector_as_the_caller_had_it(
    pack: TaxonomyPack, was_enabled: bool
) -> None:
    # Arrange
    content = _instance(pack, 3)
    (gc.enable if was_enabled else gc.disable)()

    # Act
    reading = read_instance(content, pack=pack)

    # Assert
    assert reading.facts == 6
    assert gc.isenabled() is was_enabled


@pytest.mark.parametrize("was_enabled", [True, False])
def test_a_file_that_is_refused_leaves_the_collector_as_the_caller_had_it(
    pack: TaxonomyPack, was_enabled: bool
) -> None:
    # Arrange
    (gc.enable if was_enabled else gc.disable)()

    # Act
    with pytest.raises(InstanceFormatError, match="not xbrli:xbrl"):
        read_instance(b"<root xmlns='urn:x'/>", pack=pack)

    # Assert
    assert gc.isenabled() is was_enabled
