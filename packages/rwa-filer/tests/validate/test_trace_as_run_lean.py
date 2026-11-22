"""
``trace_as_run`` on a lean trace — narrowed by the deny list, still a lean trace.

Pipeline position:
    boe.engine._trace_lean  ->  validate.execution.trace_as_run (the deny list
        applied)  ->  workflow.compare

Key responsibilities:
- Pin that a trace made without its comparisons (``boe.engine._LeanTrace``)
  is still one after ``trace_as_run``, on both of its paths: no rule switched
  off (only the results change) and a rule switched off (its evaluations and
  the cells only they read leave). Evidence must refuse a lean trace, and it
  can only do so while the trace still says what it is.
- Pin that the narrowing itself is what it is for a full trace.

References:
- docs/plans/rwa-filer-performance-review-2026-11-22.md — trace-06, ruling R5
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import polars as pl
import pytest

from boe_builders import T01, T02, ref, rule
from pack_builders import build_pack, build_return
from rwa_filer.boe.engine import (
    REASON_DEACTIVATED_BY_PUBLISHER,
    STATUS_NOT_EVALUATED,
    Accuracy,
    _LeanTrace,
    _trace_lean,
    trace_rules,
)
from rwa_filer.model import DECIMALS_EXACT
from rwa_filer.validate.execution import trace_as_run

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.boe.engine import RuleResult, RuleTrace
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import TaxonomyPack

COLUMNS = ["table", "sheet", "open_key", "row", "column", "value", "text_value", "decimals"]
EXACT = Accuracy(monetary_decimals=DECIMALS_EXACT, percentage_decimals=DECIMALS_EXACT)

#: Row 0010 is the sum of rows 0020 and 0030.
FOOTING = rule(
    "footing",
    f"{ref(T01, '0010', '0010')} i= {ref(T01, '0020', '0010')} i+ {ref(T01, '0030', '0010')}",
    tables=(T01,),
)
#: RWEA may not exceed exposure, once per sheet of T02. Switched off below.
CAP = rule("cap", f"{ref(T02, '0020', '0010')} i<= {ref(T02, '0010', '0010')}", tables=(T02,))


@pytest.fixture
def pack(tmp_path: Path) -> TaxonomyPack:
    return build_pack(tmp_path / "pack")


def test_a_lean_trace_stays_lean_when_no_rule_is_switched_off(pack: TaxonomyPack) -> None:
    # Arrange
    lean = _trace_lean(_return(), pack, [FOOTING, CAP], accuracy=EXACT)

    # Act
    as_run = trace_as_run(lean, lean.results)

    # Assert
    assert isinstance(as_run, _LeanTrace)
    assert as_run == replace(lean, results=lean.results)


def test_a_lean_trace_stays_lean_when_a_rule_is_switched_off(pack: TaxonomyPack) -> None:
    # Arrange
    lean = _trace_lean(_return(), pack, [FOOTING, CAP], accuracy=EXACT)
    results = _cap_switched_off(lean.results)

    # Adequacy: the switched-off rule has evaluations, and cells nothing else reads.
    assert any(evaluation.rule_id == "cap" for evaluation in lean.evaluations)
    assert any(address.table == T02 for address in lean.cells)

    # Act
    as_run = trace_as_run(lean, results)

    # Assert
    assert isinstance(as_run, _LeanTrace)
    assert {evaluation.rule_id for evaluation in as_run.evaluations} == {"footing"}
    assert {address.table for address in as_run.cells} == {T01}


def test_a_full_trace_is_narrowed_as_before(pack: TaxonomyPack) -> None:
    """The narrowing is unchanged: a full trace stays full and loses the switched-off rule."""
    # Arrange
    full = trace_rules(_return(), pack, [FOOTING, CAP], accuracy=EXACT)
    results = _cap_switched_off(full.results)

    # Act
    as_run = trace_as_run(full, results)

    # Assert
    assert type(as_run) is type(full)
    assert as_run.results == results
    assert as_run.evaluations == tuple(
        evaluation for evaluation in full.evaluations if evaluation.rule_id != "cap"
    )
    assert as_run.cells == _cells_read(full, "footing")


# =============================================================================
# Helpers
# =============================================================================


def _return() -> CanonicalReturn:
    rows = [
        (T01, None, None, "0010", "0010", 100.0),
        (T01, None, None, "0020", "0010", 60.0),
        (T01, None, None, "0030", "0010", 40.0),
        (T02, "0001", None, "0010", "0010", 40.0),
        (T02, "0001", None, "0020", "0010", 50.0),
    ]
    padded = [(*row, None, None) for row in rows]
    return build_return(pl.DataFrame(padded, schema=COLUMNS, orient="row"))


def _cap_switched_off(results: tuple[RuleResult, ...]) -> tuple[RuleResult, ...]:
    """``results`` with ``cap`` deactivated at the gateway, its formula's result kept."""
    return tuple(
        replace(
            result,
            status=STATUS_NOT_EVALUATED,
            reason=REASON_DEACTIVATED_BY_PUBLISHER,
            formula=result,
        )
        if result.rule_id == "cap"
        else result
        for result in results
    )


def _cells_read(trace: RuleTrace, rule_id: str) -> dict[object, object]:
    read = {
        address
        for evaluation in trace.evaluations
        if evaluation.rule_id == rule_id
        for address in evaluation.cells
    }
    return {address: fact for address, fact in trace.cells.items() if address in read}
