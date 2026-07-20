"""Unit guard: the aggregator summary producers conform to their edge contracts.

Runs the REAL generate_summary_by_* functions on a small in-memory reporting
ledger and strict-seals each output against its edge, so producer/contract drift
is caught here in the unit tier rather than only transitively via acceptance:

- a dropped required column or a changed dtype raises inside ``seal``;
- an added, undeclared column (which ``conform`` would silently strip) is caught
  by the explicit subset assertion.

References:
- contracts/edges.py (SUMMARY_BY_* edges)
- engine/aggregator/_summaries.py (the producers)
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.edges import (
    SUMMARY_BY_APPROACH_EDGE,
    SUMMARY_BY_CLASS_EDGE,
    SUMMARY_BY_CLASS_METHOD_EDGE,
    EdgeContract,
    seal,
    sealed_edge_of,
)
from rwa_calc.engine.aggregator._summaries import (
    generate_summary_by_approach,
    generate_summary_by_class,
    generate_summary_by_class_method,
)


def _ledger(*, with_floor: bool) -> pl.LazyFrame:
    """A minimal per-leg reporting ledger the summary producers group over."""
    data: dict[str, list] = {
        "exposure_reference": ["E1", "E2"],
        "reporting_class": ["corporate", "retail"],
        "reporting_approach": ["standardised", "foundation_irb"],
        "reporting_method": ["STD", "FIRB"],
        "reporting_ead": [100.0, 200.0],
        "reporting_rw": [1.0, 0.5],
        "rwa_final": [100.0, 100.0],
        "expected_loss": [1.0, 2.0],
        "el_shortfall": [0.0, 0.5],
        "el_excess": [0.0, 0.0],
    }
    if with_floor:
        # Present only when the output floor ran — drives the conditional
        # floor_binding_count / total_floor_impact columns.
        data["is_floor_binding"] = [True, True]
        data["floor_impact_rwa"] = [10.0, 20.0]
    return pl.LazyFrame(data)


def _assert_conforms(out: pl.LazyFrame, edge: EdgeContract) -> None:
    # An undeclared column would be silently stripped by conform — assert the
    # producer emits nothing outside the contract so an added column fails loud.
    undeclared = set(out.collect_schema().names()) - set(edge.columns)
    assert not undeclared, f"{edge.name}: producer emits undeclared column(s) {undeclared}"
    # Missing-required and dtype drift raise inside the strict seal.
    assert sealed_edge_of(seal(out, edge)) == edge.name


@pytest.mark.parametrize("with_floor", [False, True])
def test_summary_by_class_output_conforms_to_edge(with_floor: bool) -> None:
    _assert_conforms(
        generate_summary_by_class(_ledger(with_floor=with_floor)), SUMMARY_BY_CLASS_EDGE
    )


@pytest.mark.parametrize("with_floor", [False, True])
def test_summary_by_approach_output_conforms_to_edge(with_floor: bool) -> None:
    _assert_conforms(
        generate_summary_by_approach(_ledger(with_floor=with_floor)), SUMMARY_BY_APPROACH_EDGE
    )


@pytest.mark.parametrize("with_floor", [False, True])
def test_summary_by_class_method_output_conforms_to_edge(with_floor: bool) -> None:
    _assert_conforms(
        generate_summary_by_class_method(_ledger(with_floor=with_floor)),
        SUMMARY_BY_CLASS_METHOD_EDGE,
    )
