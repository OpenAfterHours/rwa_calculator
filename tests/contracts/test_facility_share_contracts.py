"""
Contract tests: the facility-share carriers survive every sealed edge.

``EdgeContract.conform`` selects only the columns a contract DECLARES and drops
everything else with no error and no warning (``edges.py``). So a column that the
hierarchy stage emits but one edge in the chain forgets to declare is silently
gone by the next stage — and the facility-share resolver at the head of the
aggregator would then see no candidates, keep the single row it already sees, and
pass every test that only checks "one undrawn row per facility". That is
LESSONS B1 in its purest form: the feature becomes a green no-op.

The chain the two carriers must survive is nine contracts long. Six of them are
reached through ``_hierarchy_resolved_columns()``, which spreads into the
hierarchy exit, the classifier exit, the CRM exit and the RE-split exit; the
three calculator-branch edges and the aggregator exit are literal dicts and have
to name the column themselves. Enumerating the chain here rather than trusting
the spread is the point — a contract whose declaration is inherited and one whose
declaration is typed look identical from the consumer side, and only one of them
breaks when someone re-keys the literal dict.

``facility_share_group`` alone is required on the aggregator exit: the winner
survives to reporting carrying its group, while the candidate flag has done its
work by then.

Also pinned here, because each is a field a later wave must ADD rather than a
behaviour it must change:

- ``AggregatedResultBundle.facility_share_resolution`` — the per-candidate audit
  frame, which is the only place an attribution flip under the floor-aware metric
  is visible. Nullable, because most portfolios have no share.
- ``OutputFloorSummary.facility_share_metric_used`` /
  ``facility_share_trea_alternative`` — which of the two assignments won, and
  what the other one came to.
- ``CalculationConfig.facility_share_metric`` — the firm election. It lives on
  the CONFIG rather than in the rulepack because it is a firm choice, not a
  regime rule; the regime gate is the existing ``output_floor`` Feature, and
  arch_check check 17 bans branching on the regime boolean.

References:
- docs/plans/facility-share-riskiest-member.md Section 4 (the nine edges) and
  Section 6.4 (the election).
- .claude/state/fs1-scenario-proposal.md Sections 6.1 and 6.2.
- src/rwa_calc/contracts/edges.py::EdgeContract.conform — the silent drop.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import date
from inspect import signature
from typing import get_type_hints

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, OutputFloorSummary
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import (
    AGGREGATOR_EXIT_EDGE,
    CLASSIFIER_EXIT_EDGE,
    CRM_EXIT_EDGE,
    HIERARCHY_EXIT_EDGE,
    HIERARCHY_RESOLVED_EDGE,
    IRB_BRANCH_EDGE,
    RE_SPLIT_EXIT_EDGE,
    SA_BRANCH_EDGE,
    SLOTTING_BRANCH_EDGE,
    EdgeContract,
)

#: The group carrier and the candidate flag, with the dtype each edge must
#: declare. A dtype violation on a sealed edge reddens the WHOLE acceptance
#: suite and no unit test can see the omission (LESSONS D3), so the dtype is
#: asserted alongside the name every time.
_CARRIERS: tuple[tuple[str, pl.DataType], ...] = (
    ("facility_share_group", pl.String),
    ("is_facility_share_candidate", pl.Boolean),
)

#: Every edge between the hierarchy stage that EMITS the carriers and the
#: aggregator stage that CONSUMES them. Named individually rather than derived
#: from a registry: the six inherited declarations and the three typed ones fail
#: for different reasons and a derived list would hide which.
_CHAIN: tuple[tuple[str, EdgeContract], ...] = (
    ("hierarchy_resolved", HIERARCHY_RESOLVED_EDGE),
    ("hierarchy_exit", HIERARCHY_EXIT_EDGE),
    ("classifier_exit", CLASSIFIER_EXIT_EDGE),
    ("crm_exit", CRM_EXIT_EDGE),
    ("re_split_exit", RE_SPLIT_EXIT_EDGE),
    ("sa_branch", SA_BRANCH_EDGE),
    ("irb_branch", IRB_BRANCH_EDGE),
    ("slotting_branch", SLOTTING_BRANCH_EDGE),
)


# ---------------------------------------------------------------------------
# The edge chain
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("carrier", "dtype"), _CARRIERS)
@pytest.mark.parametrize(("edge_name", "edge"), _CHAIN, ids=[name for name, _ in _CHAIN])
def test_facility_share_carrier_declared_on_edge(
    edge_name: str, edge: EdgeContract, carrier: str, dtype: pl.DataType
) -> None:
    """Each carrier is declared, with the right dtype, on each edge in the chain.

    Arrange: one sealed edge contract from the hierarchy-to-calculator chain.
    Act:     read its declared columns.
    Assert:  the carrier is declared and carries the contract dtype.

    A missing declaration here is not a null downstream — it is an ABSENT
    column, because ``conform`` ends in ``lf.select(emitted)``.
    """
    assert carrier in edge.columns, (
        f"{carrier} is not declared on the {edge_name} edge, so conform() drops "
        "it there with no error - the fan-out becomes a silent no-op from that "
        "stage onward"
    )
    assert edge.columns[carrier].dtype == dtype


def test_facility_share_group_declared_on_the_aggregator_exit() -> None:
    """The surviving winner carries its group to reporting.

    Arrange: the sealed aggregator exit.
    Act:     read its declared columns.
    Assert:  ``facility_share_group`` is declared as a String.

    The candidate flag is deliberately NOT required here: by the aggregator exit
    the losers are gone and every surviving row is an ordinary exposure, so the
    flag would carry no information. The group does — it is what lets a reader of
    the ledger tell an allocated undrawn from an ordinary one.
    """
    assert "facility_share_group" in AGGREGATOR_EXIT_EDGE.columns
    assert AGGREGATOR_EXIT_EDGE.columns["facility_share_group"].dtype == pl.String


def test_facility_share_carriers_survive_a_conform_round_trip() -> None:
    """A frame carrying both columns keeps them through every edge in the chain.

    Arrange: a one-row frame built from each edge's own empty frame, so it is
             schema-complete by construction and cannot fail for an unrelated
             missing column.
    Act:     conform it through every edge in order.
    Assert:  both carriers are still present and still typed, at every step.

    Declaring the column and CONFORMING it are two claims, and the second is the
    one production makes. Asserting the declaration alone would pass on a
    contract whose ``conform`` had been narrowed.
    """
    for edge_name, edge in _CHAIN:
        schema = edge.conform(edge.empty_frame()).collect_schema()
        for carrier, dtype in _CARRIERS:
            assert carrier in schema.names(), (
                f"{carrier} did not survive conform() on the {edge_name} edge"
            )
            assert schema[carrier] == dtype


# ---------------------------------------------------------------------------
# Bundle and summary fields
# ---------------------------------------------------------------------------


def test_aggregated_bundle_carries_the_facility_share_resolution_frame() -> None:
    """``AggregatedResultBundle`` exposes the per-candidate audit frame.

    Arrange: the bundle dataclass.
    Act:     read its field names and annotations.
    Assert:  ``facility_share_resolution`` is declared, nullable, and defaults to
             ``None``.

    Nullable because most portfolios hold no facility share at all. Its default
    must be ``None`` rather than an empty frame so a consumer can tell "no share
    in this book" from "a share the resolver failed to record".
    """
    names = {field.name for field in fields(AggregatedResultBundle)}
    assert "facility_share_resolution" in names, (
        "the audit frame is the ONLY place an attribution flip under the "
        "floor-aware metric is visible; without it a moved COREP row is the "
        "first anyone hears of it"
    )
    hints = get_type_hints(AggregatedResultBundle)
    assert "None" in str(hints["facility_share_resolution"])
    field = next(f for f in fields(AggregatedResultBundle) if f.name == "facility_share_resolution")
    assert field.default is None


@pytest.mark.parametrize(
    ("field_name", "expected"),
    [("facility_share_metric_used", str), ("facility_share_trea_alternative", float)],
)
def test_output_floor_summary_records_which_assignment_won(field_name: str, expected: type) -> None:
    """``OutputFloorSummary`` names the metric that decided the allocation.

    Arrange: the summary dataclass.
    Act:     read its fields.
    Assert:  both fields exist, are optional and default to ``None``.

    Under the floor-aware default the assignment can flip with the floor state,
    with the Art. 92(5) phase-in step, and between reporting scopes. That is a
    designed consequence, but it may never be SILENT — these two fields are how a
    reader learns which branch won and what the other one came to.
    """
    names = {field.name for field in fields(OutputFloorSummary)}
    assert field_name in names
    hints = get_type_hints(OutputFloorSummary)
    annotation = str(hints[field_name])
    assert expected.__name__ in annotation
    assert "None" in annotation
    field = next(f for f in fields(OutputFloorSummary) if f.name == field_name)
    assert field.default is None


# ---------------------------------------------------------------------------
# The firm election
# ---------------------------------------------------------------------------


def test_calculation_config_carries_the_facility_share_metric_election() -> None:
    """``facility_share_metric`` defaults to ``"floor_aware"`` on the config.

    Arrange: the config dataclass and both regime factories.
    Act:     read the field and construct one config per regime.
    Assert:  the field exists, defaults to ``"floor_aware"``, and both factories
             carry that default through.

    The election lives on the CONFIG rather than in the rulepack because it is a
    firm choice — like ``OutputFloorConfig.skip_transitional`` — and the regime
    gate is the existing ``output_floor`` Feature. arch_check check 17 bans
    engine code branching on ``config.is_basel_3_1``, which is exactly what a
    pack-side election would tempt.
    """
    names = {field.name for field in fields(CalculationConfig)}
    assert "facility_share_metric" in names
    field = next(f for f in fields(CalculationConfig) if f.name == "facility_share_metric")
    assert field.default == "floor_aware", (
        "the default must be the capital-maximising floor-aware rule; the "
        "own_approach election LOWERS RWA where the floor binds and is opt-in "
        "for that reason"
    )


def test_facility_share_metric_accepts_the_own_approach_election() -> None:
    """Both regime factories accept ``own_approach`` and keep it.

    Arrange: the two factories.
    Act:     build a config under each with the election set.
    Assert:  the value survives onto the config.

    A firm may set the election once and run both regimes: under CRR the floor
    Feature is off, so P0 applies either way and the election is inert.
    """
    factories = (
        (CalculationConfig.crr, {"reporting_date": date(2025, 12, 31)}),
        (CalculationConfig.basel_3_1, {"reporting_date": date(2027, 6, 1)}),
    )
    for factory, kwargs in factories:
        # Signature FIRST: a missing keyword raises TypeError, which reports a
        # broken test rather than an unimplemented field.
        assert "facility_share_metric" in signature(factory).parameters, (
            f"{factory.__qualname__} does not accept the election; a firm that "
            "sets it once cannot then run both regimes"
        )
        config = factory(**kwargs, facility_share_metric="own_approach")
        assert config.facility_share_metric == "own_approach"
