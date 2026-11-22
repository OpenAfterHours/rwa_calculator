"""
A pack load and the cyclic garbage collector.

Pipeline position:
    load_packaged  ->  load_pack (paused: ``rwa_filer._gc.collector_paused``)  ->  TaxonomyPack

Why this exists: a pack is tens of thousands of long-lived objects with no
reference cycles among them, and the collector re-walking the half-built pack
was about half the CPU of a cold load. ``load_pack`` therefore runs with the
collector paused. Two things have to hold for that to be a saving and not a
hazard, and neither shows in any output: the collector really does not run
while the pack is built (a count of collector passes, not a clock), and the
caller gets its collector back exactly as it left it — on or off, and also
when the load raises.
"""

from __future__ import annotations

import gc
import json
from importlib import resources
from typing import TYPE_CHECKING, Any

import pytest

from pack_builders import build_pack
from rwa_filer.taxonomy import pack as pack_module
from rwa_filer.taxonomy.pack import (
    PACK_FILE,
    PACKS_DIRECTORY,
    PACKS_PACKAGE,
    TaxonomyPack,
    available_packs,
    load_pack,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from importlib.resources.abc import Traversable
    from pathlib import Path


@pytest.fixture(autouse=True)
def _collector() -> Iterator[None]:
    """Put the collector back as the session had it, whatever a test did to it."""
    was_enabled = gc.isenabled()
    yield
    if was_enabled:
        gc.enable()
    else:
        gc.disable()


def _largest_packaged_pack() -> Traversable:
    """The directory of the packaged pack with the most data points to build: PRA001."""
    newest = max(
        (info for info in available_packs() if info.module == "PRA001"),
        key=lambda info: info.valid_from,
    )
    return resources.files(PACKS_PACKAGE).joinpath(PACKS_DIRECTORY, newest.key)


class _Assembly:
    """Stands in for ``TaxonomyPack`` inside ``load_pack`` and notes the collector as it is called.

    ``load_pack`` assembles the pack as its last step, with everything already
    built. What is noted there is what happened DURING the build; the collector
    may run the moment the pause ends, and that pass is not the pause's to prevent.
    """

    def __init__(self) -> None:
        self.passes: list[int] = []
        self.enabled_at_assembly: bool | None = None
        self.passes_at_assembly: list[int] | None = None

    def watch(self, phase: str, info: dict[str, int]) -> None:
        if phase == "start":
            self.passes.append(info["generation"])

    def __call__(self, **fields: Any) -> TaxonomyPack:
        self.enabled_at_assembly = gc.isenabled()
        self.passes_at_assembly = list(self.passes)
        return TaxonomyPack(**fields)


def _load_noting_the_collector(
    monkeypatch: pytest.MonkeyPatch, directory: Traversable
) -> tuple[_Assembly, TaxonomyPack]:
    """Load ``directory`` and say what the collector did while the pack was built."""
    assembly = _Assembly()
    monkeypatch.setattr(pack_module, "TaxonomyPack", assembly)
    gc.callbacks.append(assembly.watch)
    try:
        pack = load_pack(directory)
    finally:
        gc.callbacks.remove(assembly.watch)
    return assembly, pack


# ---------------------------------------------------------------------------
# The collector does not run while a pack is built
# ---------------------------------------------------------------------------


def test_no_collection_of_any_generation_runs_while_a_pack_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a full (generation 2) pass, and not a young one either."""
    # Arrange
    directory = _largest_packaged_pack()
    gc.enable()

    # Act
    assembly, pack = _load_noting_the_collector(monkeypatch, directory)

    # Assert
    assert len(pack.datapoints) > 50_000, "the pack is too small for the collector to have run"
    assert assembly.passes_at_assembly == []
    assert assembly.enabled_at_assembly is False


def test_the_same_load_with_the_pause_disarmed_does_run_the_collector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control for the test above: its zero is the pause's doing, not the workload's."""
    # Arrange
    directory = _largest_packaged_pack()
    gc.enable()
    monkeypatch.setattr(gc, "disable", lambda: None)

    # Act
    assembly, pack = _load_noting_the_collector(monkeypatch, directory)

    # Assert
    assert len(pack.datapoints) > 50_000
    assert assembly.enabled_at_assembly is True
    assert assembly.passes_at_assembly, "an unpaused load of this pack starts no collection"


# ---------------------------------------------------------------------------
# The caller's collector is handed back as it was
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("was_enabled", [True, False])
def test_a_load_leaves_the_collector_as_the_caller_had_it(
    tmp_path: Path, was_enabled: bool
) -> None:
    # Arrange
    build_pack(tmp_path)
    (gc.enable if was_enabled else gc.disable)()

    # Act
    pack = load_pack(tmp_path)

    # Assert
    assert pack.tables
    assert gc.isenabled() is was_enabled


@pytest.mark.parametrize("was_enabled", [True, False])
def test_a_load_that_is_refused_leaves_the_collector_as_the_caller_had_it(
    tmp_path: Path, was_enabled: bool
) -> None:
    # Arrange
    build_pack(tmp_path)
    payload = json.loads((tmp_path / PACK_FILE).read_text(encoding="utf-8"))
    payload["format"] = 99
    (tmp_path / PACK_FILE).write_text(json.dumps(payload), encoding="utf-8")
    (gc.enable if was_enabled else gc.disable)()

    # Act
    with pytest.raises(ValueError, match="not supported"):
        load_pack(tmp_path)

    # Assert
    assert gc.isenabled() is was_enabled


def test_a_load_of_a_missing_pack_leaves_the_collector_on(tmp_path: Path) -> None:
    # Arrange
    gc.enable()

    # Act
    with pytest.raises(FileNotFoundError):
        load_pack(tmp_path / "no-such-pack")

    # Assert
    assert gc.isenabled() is True
