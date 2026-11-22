"""
What the structure check costs grows with what the return names, not with the module.

Pipeline position:
    CanonicalReturn + TaxonomyPack  ->  check_structure / resolve_datapoints
    Both run on every validation (the rule engine places the facts again for
    each of its stores) and on every build.

Key responsibilities:
- Code alignment looks each code up once per (table, axis, code), however many
  facts carry it: the number of code lookups is the same for a return and for
  one with ten times its open rows. It follows the distinct codes as written -
  for codes that name something, at most the codes the named tables publish.
- A warm check does no per-table work for the tables a return does not name:
  against a module with twelve times the tables it filters the same frames
  and joins against the same cells as against the small one.

Each gate counts, so it cannot be flaked by a loaded machine, and asserts
first that the path it measures runs.

References:
- docs/plans/rwa-filer-performance-review-2026-11-22.md — structure-01,
  structure-03 and the warm floor
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl
import pytest

from pack_builders import build_pack, build_return
from rwa_filer.taxonomy import pack as pack_module
from rwa_filer.validate.structure import IS_KEY, check_structure, resolve_datapoints
from structure_builders import T01, T02, T03, T04, build_wide_pack, fact_frame

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import TaxonomyPack

#: Open rows in the small return; the large one has ten times as many.
SMALL_ROWS = 20
#: Extra copies of three sample tables in the wide pack: 98 tables against the sample's 8.
WIDE_COPIES = 30

PLACERS: dict[str, Callable[[CanonicalReturn, TaxonomyPack], object]] = {
    "check_structure": check_structure,
    "resolve_datapoints": resolve_datapoints,
}


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path)


def stripped_return(open_rows: int) -> CanonicalReturn:
    """Every code with its leading zeros lost, on four tables, ``open_rows`` rows of ``T04``."""
    rows: list[tuple[object, ...]] = [
        (T01, None, None, row, column, 1.0, None) for row in ("10", "20") for column in ("10", "20")
    ]
    rows += [
        (T02, sheet, None, row, "10", 2.0, None) for sheet in ("1", "2") for row in ("10", "20")
    ]
    rows += [(T03, None, "eba_GA:GB", row, "10", 3.0, None) for row in ("10", "20")]
    for number in range(open_rows):
        rows += [
            (T04, None, None, f"R{number}", "5", float(number), None),
            (T04, None, None, f"R{number}", "10", 4.0, None),
        ]
    return build_return(fact_frame(*rows))


def published_codes(ret: CanonicalReturn, pack: TaxonomyPack) -> int:
    """How many row, column and sheet codes the tables ``ret`` names publish."""
    total = 0
    for code in ret.tables:
        table = pack.tables[code]
        rows = 0 if table.open_rows else len(table.row_codes)
        total += rows + len(table.key_codes) + len(table.column_codes) + len(table.sheet_codes)
    return total


def code_lookups(monkeypatch: pytest.MonkeyPatch, place: Callable[[], object]) -> int:
    """How many times ``place()`` matched a written code against a table's codes."""
    calls = 0
    original = pack_module.match_code

    def counting(codes: Sequence[str], written: str) -> str:
        nonlocal calls
        calls += 1
        return original(codes, written)

    with monkeypatch.context() as patched:
        patched.setattr(pack_module, "match_code", counting)
        place()
    return calls


def frame_work(
    monkeypatch: pytest.MonkeyPatch, place: Callable[[], object]
) -> list[tuple[str, int]]:
    """Each frame ``place()`` filters (its height) and each it joins against (the other's)."""
    work: list[tuple[str, int]] = []
    original_filter, original_join = pl.DataFrame.filter, pl.DataFrame.join

    def counted_filter(self: pl.DataFrame, *args: Any, **kwargs: Any) -> pl.DataFrame:
        work.append(("filter", self.height))
        return original_filter(self, *args, **kwargs)

    def counted_join(
        self: pl.DataFrame, other: pl.DataFrame, *args: Any, **kwargs: Any
    ) -> pl.DataFrame:
        work.append(("join", other.height))
        return original_join(self, other, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(pl.DataFrame, "filter", counted_filter)
        patched.setattr(pl.DataFrame, "join", counted_join)
        place()
    return work


# ---------------------------------------------------------------------------
# Code alignment: one lookup per (table, axis, code)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("placer", list(PLACERS))
def test_code_lookups_do_not_grow_with_the_open_rows(
    pack: TaxonomyPack, monkeypatch: pytest.MonkeyPatch, placer: str
) -> None:
    # Arrange
    small, large = stripped_return(SMALL_ROWS), stripped_return(10 * SMALL_ROWS)
    assert large.facts.height >= 8 * small.facts.height
    assert check_structure(large, pack) == [], "every stripped code must have been aligned"
    placed = resolve_datapoints(large, pack)
    assert placed.filter(pl.col("datapoint").is_null() & ~pl.col(IS_KEY)).is_empty()
    place = PLACERS[placer]

    # Act
    few = code_lookups(monkeypatch, lambda: place(small, pack))
    many = code_lookups(monkeypatch, lambda: place(large, pack))

    # Assert
    assert few > 0, "no code was looked up: the gate measures nothing"
    assert many == few
    assert many <= published_codes(large, pack)


# ---------------------------------------------------------------------------
# The warm floor: no per-table work for tables the return does not name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("placer", list(PLACERS))
def test_a_warm_check_does_the_same_frame_work_against_a_module_with_many_more_tables(
    pack: TaxonomyPack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, placer: str
) -> None:
    # Arrange
    wide = build_wide_pack(tmp_path / "wide", copies=WIDE_COPIES)
    assert len(wide.tables) >= 12 * len(pack.tables) and wide.cells.height >= 12 * pack.cells.height
    ret = stripped_return(SMALL_ROWS)
    place = PLACERS[placer]
    # Warm: whatever is kept per pack is built on the first call, and not measured.
    place(ret, pack)
    place(ret, wide)

    # Act
    small = frame_work(monkeypatch, lambda: place(ret, pack))
    large = frame_work(monkeypatch, lambda: place(ret, wide))

    # Assert
    joined = [rows for kind, rows in small if kind == "join"]
    assert joined and max(joined) > 0, "no cell was joined: the gate measures nothing"
    assert large == small
