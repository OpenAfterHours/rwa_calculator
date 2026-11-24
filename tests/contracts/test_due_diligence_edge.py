"""
Contract tests (P1.368): the PS1/26 Art. 110A due-diligence inputs are declared
on every sealed edge from the raw lending tables to the SA calculator.

Pipeline position:
    Loader (raw loans / contingents) -> HierarchyResolver (unify, then the
    ``hierarchy_resolved`` seal) -> Classifier -> CRMProcessor -> RealEstateSplitter
    -> SACalculator

Why this file exists:
``EdgeContract.conform`` emits only the columns an edge declares, so an input the
loader accepts but no downstream edge declares is stripped with no error and no
warning (LESSONS B1). That is how ``due_diligence_performed`` and
``due_diligence_override_rw`` reached the loader seal and then vanished before
classification, leaving the Art. 110A override unreachable from any input and the
SA004 guard reading a column that was never there. These tests pin the
declarations; the end-to-end proof that a populated value reaches ``risk_weight``
is ``tests/acceptance/test_p1_368_due_diligence_override.py``.

The attestation carrier must stay NULLABLE with no default. Facility-undrawn,
SA-CCR and SFT rows have no input field to attest on, and they reach the SA
calculator as nulls. A Boolean default with a null fill (the
``is_under_irb_rollout`` pattern) would turn every one of them into an explicit
``False``, and the value-reading SA004 census would then fire on every book with a
facility or a derivative: a saturated alarm (LESSONS B9).

References:
- PRA PS1/26 Art. 110A(2), (5): the due-diligence obligation and its exemptions.
- PRA PS1/26 Art. 120(4), 122(4), 129(4A): the "at least one credit quality step
  higher" risk weight the override carries.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.edges import (
    AGGREGATOR_EXIT_EDGE,
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
    SA_BRANCH_EDGE,
)

_PERFORMED = "due_diligence_performed"
_OVERRIDE = "due_diligence_override_rw"
_APPLIED = "due_diligence_override_applied"

#: The two carriers and the dtype each must keep on every edge.
_CARRIERS: dict[str, pl.DataType] = {_PERFORMED: pl.Boolean(), _OVERRIDE: pl.Float64()}

#: Every engine edge between the hierarchy seal and the calculator input.
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


@pytest.mark.parametrize("table", ["loans", "contingents"])
@pytest.mark.parametrize("carrier", sorted(_CARRIERS))
def test_raw_lending_edges_accept_the_carrier(table: str, carrier: str) -> None:
    """The loader seal accepts both inputs on loans and contingents (the input home)."""
    # Arrange
    edge = RAW_TABLE_EDGES[table]

    # Act / Assert
    assert carrier in edge.columns
    assert edge.columns[carrier].dtype == _CARRIERS[carrier]


@pytest.mark.parametrize("edge", _INTERMEDIATE_EDGES, ids=lambda e: e.name)
@pytest.mark.parametrize("carrier", sorted(_CARRIERS))
def test_intermediate_edges_carry_the_carrier(edge, carrier: str) -> None:
    """Both carriers survive every seal from the hierarchy exit to the RE-split exit."""
    # Arrange / Act
    declared = edge.columns.get(carrier)

    # Assert
    assert declared is not None, f"{edge.name} strips {carrier}: the Art. 110A input dies there"
    assert declared.dtype == _CARRIERS[carrier]


@pytest.mark.parametrize("carrier", sorted(_CARRIERS))
def test_hierarchy_carrier_is_nullable_with_no_default(carrier: str) -> None:
    """Optional, injected as a typed null, never defaulted or null-filled.

    A null means "this row type has no attestation field" (facility-undrawn,
    SA-CCR, SFT). Filling it would turn those rows into explicit ``False`` and
    saturate the SA004 census on every facility or derivatives book.
    """
    # Arrange
    col = HIERARCHY_RESOLVED_EDGE.columns[carrier]

    # Act / Assert
    assert col.required is False
    assert col.inject is True
    assert col.default is None
    assert col.fill_null_default is False
    assert col.null_meaning, f"{carrier} must document what its null means"


@pytest.mark.parametrize("edge", [SA_BRANCH_EDGE, AGGREGATOR_EXIT_EDGE], ids=lambda e: e.name)
def test_override_audit_flag_reaches_the_output(edge) -> None:
    """The documented ``due_diligence_override_applied`` audit flag is not stripped.

    Conditional (inject=False): the override step writes it on every Basel 3.1
    run and never under CRR, so it must be validated where present and never
    fabricated where absent.
    """
    # Arrange
    col = edge.columns.get(_APPLIED)

    # Act / Assert
    assert col is not None, f"{edge.name} strips {_APPLIED}"
    assert col.dtype == pl.Boolean()
    assert col.required is False
    assert col.inject is False
