"""
Contract tests (R14): the CRR Art. 148 ``is_under_irb_rollout`` carrier is
whitelisted on every sealed edge from the raw lending tables through to the
aggregator exit, so it reaches COREP C 08.07 / OF 08.07 col 0040 ("% subject to
a roll-out plan").

Unlike the ``intragroup_zero_rw_eligible`` scope carrier (stripped at the branch
exit — it is calculation machinery), this flag IS a reporting measure, so it must
survive the calc branch edges and land on the aggregator exit. It is a pure
pass-through INPUT: no stage sets it and it changes no RWA/EAD figure.

References:
- CRR Art. 148 (sequential IRB implementation / roll-out plans); Art. 150
  (permanent partial use).
- Reg (EU) 2021/451 Annex II C 08.07; PRA PS1/26 Annex I/II OF 08.07.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.edges import (
    AGGREGATOR_EXIT_EDGE,
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

_CARRIER = "is_under_irb_rollout"

# Every intermediate engine edge that must carry the flag from the raw lending
# tables through to the calc branches.
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
    """The flag auto-derives onto the three raw lending edges from the schemas."""
    edge = RAW_TABLE_EDGES[table]
    assert _CARRIER in edge.columns
    assert edge.columns[_CARRIER].dtype == pl.Boolean


@pytest.mark.parametrize("edge", _INTERMEDIATE_EDGES, ids=lambda e: e.name)
def test_intermediate_edges_carry_the_carrier(edge) -> None:
    """The flag survives every seal from hierarchy through RE-split."""
    assert _CARRIER in edge.columns, f"{edge.name} must declare {_CARRIER}"


def test_hierarchy_carrier_is_conservative_optional_boolean() -> None:
    """Optional Boolean, default False, null-filled — CCR/SFT/gap rows are 'not
    under a roll-out plan'."""
    col = HIERARCHY_RESOLVED_EDGE.columns[_CARRIER]
    assert col.dtype == pl.Boolean
    assert col.required is False
    assert col.default is False
    assert col.fill_null_default is True


@pytest.mark.parametrize("branch", ["sa_branch", "irb_branch", "slotting_branch"])
def test_carrier_reaches_the_branch_edges(branch: str) -> None:
    """Unlike the scope carriers, this reporting flag survives the branch edge."""
    assert _CARRIER in CALC_BRANCH_EDGES[branch].columns


def test_aggregator_exit_declares_the_carrier() -> None:
    """The flag lands on the aggregator exit as a conditional column (R6 pattern):
    present when the lending chain carried it, never injected onto a frame that
    never had it."""
    assert _CARRIER in AGGREGATOR_EXIT_EDGE.columns
    col = AGGREGATOR_EXIT_EDGE.columns[_CARRIER]
    assert col.dtype == pl.Boolean
    assert col.required is False
    assert col.inject is False
