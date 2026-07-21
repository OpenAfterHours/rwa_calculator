"""
Contract tests: the CRR Art. 113(6) ``intragroup_zero_rw_eligible`` carrier is
whitelisted on every sealed edge between the raw lending tables and the SA
risk-weight code, and is stripped again at the branch exit.

The carrier must survive the hierarchy / classifier / CRM / RE-split seals (so
the SA final-RW override can read a row's own eligibility after CRM), but it is
scope machinery — not a reporting measure — so it must NOT leak into the calc
branch-exit / aggregator shape.

References:
- CRR Art. 113(6): core-UK-group 0% risk weight (individual basis).
- docs/plans/multi-entity-reporting.md: Wave 4 design record.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.edges import (
    CALC_BRANCH_EDGES,
    CCR_EXIT_EDGE,
    CLASSIFIER_EXIT_CCR_EDGE,
    CLASSIFIER_EXIT_EDGE,
    CRM_EXIT_CCR_EDGE,
    CRM_EXIT_EDGE,
    HIERARCHY_EXIT_EDGE,
    HIERARCHY_RESOLVED_EDGE,
    RAW_TABLE_EDGES,
    RE_SPLIT_EXIT_CCR_EDGE,
    RE_SPLIT_EXIT_EDGE,
)

_CARRIER = "intragroup_zero_rw_eligible"

# Every intermediate engine edge that must carry the scope carrier from the raw
# lending tables through to the SA risk-weight code.
_INTERMEDIATE_EDGES = [
    HIERARCHY_RESOLVED_EDGE,
    HIERARCHY_EXIT_EDGE,
    CCR_EXIT_EDGE,
    CLASSIFIER_EXIT_EDGE,
    CLASSIFIER_EXIT_CCR_EDGE,
    CRM_EXIT_EDGE,
    CRM_EXIT_CCR_EDGE,
    RE_SPLIT_EXIT_EDGE,
    RE_SPLIT_EXIT_CCR_EDGE,
]


@pytest.mark.parametrize("table", ["facilities", "loans", "contingents"])
def test_raw_lending_edges_carry_the_carrier(table: str) -> None:
    """The carrier auto-derives onto the three raw lending edges from the schemas."""
    edge = RAW_TABLE_EDGES[table]
    assert _CARRIER in edge.columns
    assert edge.columns[_CARRIER].dtype == pl.Boolean


@pytest.mark.parametrize("edge", _INTERMEDIATE_EDGES, ids=lambda e: e.name)
def test_intermediate_edges_carry_the_carrier(edge) -> None:
    """The carrier survives every seal from hierarchy through RE-split."""
    assert _CARRIER in edge.columns, f"{edge.name} must declare {_CARRIER}"


def test_carrier_is_conservative_optional_boolean() -> None:
    """Optional Boolean, default False, null-filled — CCR/SFT/gap rows are 'not eligible'."""
    col = HIERARCHY_RESOLVED_EDGE.columns[_CARRIER]
    assert col.dtype == pl.Boolean
    assert col.required is False
    assert col.default is False
    assert col.fill_null_default is True


@pytest.mark.parametrize("branch", ["sa_branch", "irb_branch", "slotting_branch"])
def test_carrier_is_stripped_at_branch_exit(branch: str) -> None:
    """The carrier is scope machinery — it must not reach the aggregator / reporting."""
    assert _CARRIER not in CALC_BRANCH_EDGES[branch].columns
