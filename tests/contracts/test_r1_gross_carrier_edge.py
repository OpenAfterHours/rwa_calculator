"""
Contract tests: the four floored gross-exposure carriers
(``reporting_gross_drawn`` / ``_interest`` / ``_nominal`` / ``_undrawn``) are
whitelisted on the sealed aggregator-exit edge alongside the other
``reporting_*`` projection columns, and — like ``reporting_ead`` — are produced
by the aggregator, so they must NOT appear on the calculator branch edges.

References:
- CRR Art. 111 (SA gross exposure value); Art. 166 (IRB exposure value)
- src/rwa_calc/engine/aggregator/aggregator.py::_add_reporting_projection
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.edges import AGGREGATOR_EXIT_EDGE, CALC_BRANCH_EDGES

_GROSS_CARRIERS = (
    "reporting_gross_drawn",
    "reporting_gross_interest",
    "reporting_gross_nominal",
    "reporting_gross_undrawn",
)


@pytest.mark.parametrize("carrier", _GROSS_CARRIERS)
def test_aggregator_exit_declares_gross_carrier(carrier: str) -> None:
    """Each floored gross carrier is a Float64 column on the aggregator exit."""
    assert carrier in AGGREGATOR_EXIT_EDGE.columns
    assert AGGREGATOR_EXIT_EDGE.columns[carrier].dtype == pl.Float64


@pytest.mark.parametrize("carrier", _GROSS_CARRIERS)
@pytest.mark.parametrize("branch", ["sa_branch", "irb_branch", "slotting_branch"])
def test_gross_carrier_absent_from_branch_edges(carrier: str, branch: str) -> None:
    """The carriers are aggregator-produced (like reporting_ead) — not branch columns."""
    assert carrier not in CALC_BRANCH_EDGES[branch].columns
