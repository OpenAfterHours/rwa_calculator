"""
The lean trace — every evaluation as ``trace_rules`` traces it, without the comparison log.

Pipeline position:
    CanonicalReturn + TaxonomyPack + rules  ->  boe.engine._trace_lean
        ->  RuleTrace (a ``_LeanTrace``)  ->  workflow.compare, which reads each
            evaluation's place, verdict, relation, sides and side values only

Key responsibilities:
- Pin that a lean trace is the default trace with ``Evaluation.comparisons``
  emptied: the same results, places, verdicts, sides and side values, and the
  same reported cells but for those only a where clause reads — a where clause
  is no side of the rule. Logging every comparison with its operands is most
  of what tracing costs beyond the verdict, and a comparison of two returns
  reads none of it.
- ``RuleTrace.cells`` is compared as a mapping, not in order: a full trace
  first reads a cell when a comparison that reads it runs, a lean one when a
  side is traced, in rule order. Nothing reads a lean trace's cells in order.
- Pin that a caller can tell a lean trace from a full one, so evidence — which
  records the comparisons — is never written from one.

The hand-built rule has both a where clause and a conditional, because those
are where comparisons happen other than at the top of a rule, and no packaged
PRA001 rule has a where clause: the corpus's are the engine's only other cover.

References:
- docs/plans/rwa-filer-performance-review-2026-11-22.md — trace-06 / compare-02
"""

from __future__ import annotations

from dataclasses import replace
from functools import cache
from typing import TYPE_CHECKING

import polars as pl
import pytest

from boe_builders import T01, T02, ref, rule
from engine_corpus import MODULE, build_corpus, corpus_release, corpus_rulebook
from pack_builders import build_pack, build_return
from rwa_filer.boe.engine import (
    STATUS_FAIL,
    STATUS_PASS,
    Accuracy,
    CellAddress,
    _LeanTrace,
    _trace_lean,
    trace_rules,
)
from rwa_filer.model import DECIMALS_EXACT

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.boe.engine import RuleTrace
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import TaxonomyPack

COLUMNS = ["table", "sheet", "open_key", "row", "column", "value", "text_value", "decimals"]
EXACT = Accuracy(monetary_decimals=DECIMALS_EXACT, percentage_decimals=DECIMALS_EXACT)

#: RWEA may not exceed the exposure — where it applies at all (the where
#: clause), and only to the part a conditional on another table lets through.
#: Run once per sheet of T02.
CAPPED = rule(
    "capped",
    f"{ref(T02, '0020', '0010')} i<= "
    f"(if {ref(T01, '0020', '0010')} > 0 then {ref(T02, '0010', '0010')} else 0)",
    tables=(T01, T02),
    where=f"{ref(T01, '0010', '0010')} > 0",
)
#: The cell only the where clause reads: no side of the rule reads it.
WHERE_ONLY = CellAddress(T01, None, None, "0010", "0010")


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path / "pack")


def test_a_lean_trace_is_the_full_trace_without_its_comparisons(pack: TaxonomyPack) -> None:
    """Same results, evaluations and side values; the where clause's cell alone is not read."""
    # Arrange - sheet 0001 breaks (50 > 40), sheet 0002 holds (30 <= 40).
    a_return = _capped_return()
    full = trace_rules(a_return, pack, [CAPPED], accuracy=EXACT)

    # Adequacy: both sheets are evaluated, the where clause and the conditional
    # each log a comparison, and the where clause reads a cell no side reads.
    assert [result.status for result in full.results] == [STATUS_FAIL]
    assert len(full.evaluations) == 2
    branches = {item.branch for evaluation in full.evaluations for item in evaluation.comparisons}
    assert branches == {"where", "rule/if", "rule"}, branches
    assert WHERE_ONLY in full.cells
    assert all(WHERE_ONLY not in (*item.left, *item.right) for item in full.evaluations)

    # Act
    lean = _trace_lean(a_return, pack, [CAPPED], accuracy=EXACT)

    # Assert
    assert lean.results == full.results
    assert lean.evaluations == tuple(
        replace(evaluation, comparisons=()) for evaluation in full.evaluations
    )
    assert dict(lean.cells) == {
        address: fact for address, fact in full.cells.items() if address != WHERE_ONLY
    }
    assert all(
        evaluation.cells == {*evaluation.left, *evaluation.right} for evaluation in lean.evaluations
    )


def test_a_lean_trace_keeps_each_sides_value(pack: TaxonomyPack) -> None:
    """compare states how far a broken evaluation is out from the two side values."""
    # Act
    lean = _trace_lean(_capped_return(), pack, [CAPPED], accuracy=EXACT)

    # Assert
    held = {
        dict(item.place)["z"]: (item.holds, item.left_value, item.right_value)
        for item in lean.evaluations
    }
    assert held == {"0001": (False, 50.0, 40.0), "0002": (True, 30.0, 40.0)}


def test_a_lean_trace_can_be_told_from_a_full_one(pack: TaxonomyPack) -> None:
    """Evidence records the comparisons, so it must be able to refuse a trace without them."""
    # Arrange
    a_return = _capped_return()

    # Act
    lean = _trace_lean(a_return, pack, [CAPPED], accuracy=EXACT)
    full = trace_rules(a_return, pack, [CAPPED], accuracy=EXACT)

    # Assert
    assert isinstance(lean, _LeanTrace)
    assert not isinstance(full, _LeanTrace)
    assert isinstance(replace(lean, results=()), _LeanTrace)


@pytest.mark.parametrize("name", ["open_axes", "open_rows", "designed"])
def test_on_the_engine_corpus_a_lean_trace_differs_only_by_the_comparisons(name: str) -> None:
    """Open axes, open rows, member-less cells, where clauses: all the same but the log."""
    # Arrange
    item = build_corpus()[name]
    pack = corpus_release().pack
    full = trace_rules(item.ret, pack, _corpus_rules(), accuracy=item.accuracy)

    # Adequacy: the return's rules are traced, and log comparisons to leave out.
    assert sum(result.status in (STATUS_PASS, STATUS_FAIL) for result in full.results) > 0
    assert any(evaluation.comparisons for evaluation in full.evaluations)

    # Act
    lean = _trace_lean(item.ret, pack, _corpus_rules(), accuracy=item.accuracy)

    # Assert
    assert lean.results == full.results
    assert lean.evaluations == tuple(
        replace(evaluation, comparisons=()) for evaluation in full.evaluations
    )
    sides = {address for evaluation in lean.evaluations for address in evaluation.cells}
    assert dict(lean.cells) == {
        address: fact for address, fact in full.cells.items() if address in sides
    }
    assert _where_only_cells(full) == set(full.cells) - set(lean.cells)


# =============================================================================
# Helpers
# =============================================================================


@cache
def _corpus_rules() -> tuple[Rule, ...]:
    return corpus_rulebook().enforced(MODULE)


def _capped_return() -> CanonicalReturn:
    rows = [
        (T01, None, None, "0010", "0010", 5.0),
        (T01, None, None, "0020", "0010", 1.0),
        (T02, "0001", None, "0010", "0010", 40.0),
        (T02, "0001", None, "0020", "0010", 50.0),
        (T02, "0002", None, "0010", "0010", 40.0),
        (T02, "0002", None, "0020", "0010", 30.0),
    ]
    padded = [(*row, None, None) for row in rows]
    return build_return(pl.DataFrame(padded, schema=COLUMNS, orient="row"))


def _where_only_cells(trace: RuleTrace) -> set[CellAddress]:
    """The reported cells that only a where clause's comparisons read, in a full trace."""
    by_sides = {
        address
        for evaluation in trace.evaluations
        for address in (*evaluation.left, *evaluation.right)
    }
    in_where = {
        address
        for evaluation in trace.evaluations
        for comparison in evaluation.comparisons
        if comparison.branch.startswith("where")
        for address in (*comparison.left.cells, *comparison.right.cells)
    }
    return in_where - by_sides
