"""
Registry-tree validation and membership resolution for the scope resolver.

Covers ``_analyse_registry`` (duplicate key, unknown parent, multiple roots,
cycle), ``_membership`` (subtree vs individual), and the loud-fail SCP004 /
SCP006 paths through ``resolve_scope`` (invalid registry / unknown requested
entity -> empty selection).

References:
- CRR Part One Title II (Art. 6, 11-18): levels of application.
- docs/plans/multi-entity-reporting.md: scope resolver specification.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity, ReportingBasis
from rwa_calc.engine.stages.scope import resolver

# GRP apex; BANK_A / BANK_B under GRP; SUB under BANK_A (a 3-level tree).
_TREE = [("GRP", None), ("BANK_A", "GRP"), ("BANK_B", "GRP"), ("SUB", "BANK_A")]


def _registry(rows: list[tuple[str, str | None]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "entity_reference": [ref for ref, _ in rows],
            "parent_entity_reference": [parent for _, parent in rows],
        }
    )


def _loans(rows: list[tuple[str, str, str, str | None]]) -> pl.DataFrame:
    """rows: (loan_reference, book_code, counterparty_reference, intragroup)."""
    return pl.DataFrame(
        {
            "loan_reference": [r[0] for r in rows],
            "book_code": [r[1] for r in rows],
            "counterparty_reference": [r[2] for r in rows],
            "intragroup_entity_reference": [r[3] for r in rows],
        }
    )


def _resolve(bundle, entity: str, basis: ReportingBasis):
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 1), reporting_entity=entity, reporting_basis=basis
    )
    return resolver.resolve_scope(bundle, config)


# ---------------------------------------------------------------------------
# _analyse_registry
# ---------------------------------------------------------------------------


def test_valid_tree_has_no_reason():
    _entity_set, _children, reason = resolver._analyse_registry(_registry(_TREE))

    assert reason is None


def test_valid_tree_exposes_children_map():
    _entity_set, children, _reason = resolver._analyse_registry(_registry(_TREE))

    assert set(children["GRP"]) == {"BANK_A", "BANK_B"}


def test_duplicate_entity_reference_is_invalid():
    rows = [("GRP", None), ("BANK_A", "GRP"), ("BANK_A", "GRP")]

    _entity_set, _children, reason = resolver._analyse_registry(_registry(rows))

    assert reason is not None
    assert "duplicate" in reason


def test_unknown_parent_is_invalid():
    rows = [("GRP", None), ("BANK_A", "MISSING")]

    _entity_set, _children, reason = resolver._analyse_registry(_registry(rows))

    assert reason is not None
    assert "MISSING" in reason


def test_multiple_roots_is_invalid():
    rows = [("GRP", None), ("OTHER", None), ("BANK_A", "GRP")]

    _entity_set, _children, reason = resolver._analyse_registry(_registry(rows))

    assert reason is not None
    assert "root" in reason


def test_cycle_is_invalid():
    # A valid root (GRP) plus a disconnected 2-cycle (A<-B, B<-A): the cycle
    # nodes are unreachable from the single root.
    rows = [("GRP", None), ("A", "B"), ("B", "A")]

    _entity_set, _children, reason = resolver._analyse_registry(_registry(rows))

    assert reason is not None
    assert "cycle" in reason


def test_rootless_registry_is_invalid():
    # Every node has a parent -> no root -> a cycle by pigeonhole; flagged.
    rows = [("A", "B"), ("B", "A")]

    _entity_set, _children, reason = resolver._analyse_registry(_registry(rows))

    assert reason is not None


# ---------------------------------------------------------------------------
# _membership
# ---------------------------------------------------------------------------


def test_consolidated_membership_is_inclusive_subtree():
    _entity_set, children, _reason = resolver._analyse_registry(_registry(_TREE))

    members = resolver._membership("GRP", ReportingBasis.CONSOLIDATED, children)

    assert members == frozenset({"GRP", "BANK_A", "BANK_B", "SUB"})


def test_sub_consolidated_membership_equals_consolidated():
    _entity_set, children, _reason = resolver._analyse_registry(_registry(_TREE))

    consolidated = resolver._membership("BANK_A", ReportingBasis.CONSOLIDATED, children)
    sub = resolver._membership("BANK_A", ReportingBasis.SUB_CONSOLIDATED, children)

    assert consolidated == sub == frozenset({"BANK_A", "SUB"})


def test_individual_membership_is_the_entity_alone():
    _entity_set, children, _reason = resolver._analyse_registry(_registry(_TREE))

    members = resolver._membership("GRP", ReportingBasis.INDIVIDUAL, children)

    assert members == frozenset({"GRP"})


# ---------------------------------------------------------------------------
# resolve_scope loud-fail paths (SCP004 / SCP006)
# ---------------------------------------------------------------------------


def test_invalid_registry_empties_selection_with_scp004():
    bundle = make_raw_bundle(
        loans=_loans([("L1", "BOOK_A", "CP1", None)]),
        reporting_entities=_registry([("A", "B"), ("B", "A")]),
        book_entity_mappings=pl.DataFrame(
            {"book_code": ["BOOK_A"], "reporting_entity_reference": ["A"]}
        ),
    )

    result = _resolve(bundle, "A", ReportingBasis.CONSOLIDATED)

    assert result.loans.collect().height == 0
    assert [e.code for e in result.errors] == [resolver.SCP_INVALID_REGISTRY]


def test_unknown_requested_entity_empties_selection_with_scp006():
    bundle = make_raw_bundle(
        loans=_loans([("L1", "BOOK_A", "CP1", None)]),
        reporting_entities=_registry(_TREE),
        book_entity_mappings=pl.DataFrame(
            {"book_code": ["BOOK_A"], "reporting_entity_reference": ["BANK_A"]}
        ),
    )

    result = _resolve(bundle, "GHOST", ReportingBasis.CONSOLIDATED)

    assert result.loans.collect().height == 0
    assert [e.code for e in result.errors] == [resolver.SCP_UNKNOWN_REQUESTED_ENTITY]


@pytest.mark.parametrize(
    "code", [resolver.SCP_INVALID_REGISTRY, resolver.SCP_UNKNOWN_REQUESTED_ENTITY]
)
def test_loud_fail_errors_are_scope_category(code):
    # Both loud-fail paths carry the SCOPE category and the Art. 6 / 11-18 ref.
    bundle_invalid = make_raw_bundle(
        loans=_loans([("L1", "BOOK_A", "CP1", None)]),
        reporting_entities=(
            _registry([("A", "B"), ("B", "A")])
            if code == resolver.SCP_INVALID_REGISTRY
            else _registry(_TREE)
        ),
    )
    entity = "A" if code == resolver.SCP_INVALID_REGISTRY else "GHOST"

    result = _resolve(bundle_invalid, entity, ReportingBasis.CONSOLIDATED)

    error = next(e for e in result.errors if e.code == code)
    assert error.category.value == "scope"
    assert error.regulatory_reference == "CRR Art. 6 / 11-18"


def test_self_parenting_single_node_is_invalid():
    # A single row whose parent is itself has no null-parent root -> SCP004.
    _entity_set, _children, reason = resolver._analyse_registry(_registry([("A", "A")]))

    assert reason is not None


# ---------------------------------------------------------------------------
# Error accumulation + loud-fail frame semantics
# ---------------------------------------------------------------------------


def test_scope_errors_are_appended_not_replacing_prior_errors():
    prior = CalculationError(
        code="DQ999",
        message="a pre-existing loader error",
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
    )
    bundle = make_raw_bundle(
        loans=_loans([("L1", "BOOK_A", "CP1", None)]),
        reporting_entities=_registry(_TREE),
        book_entity_mappings=pl.DataFrame(
            {"book_code": ["BOOK_A"], "reporting_entity_reference": ["BANK_A"]}
        ),
        errors=[prior],
    )

    result = _resolve(bundle, "GHOST", ReportingBasis.CONSOLIDATED)  # triggers SCP006

    codes = [e.code for e in result.errors]
    assert codes[0] == "DQ999"  # prior error preserved, ahead of the scope error
    assert resolver.SCP_UNKNOWN_REQUESTED_ENTITY in codes


def test_guarantees_survive_inert_on_loud_fail_path():
    # SCP006 empties the exposure-bearing frames but leaves guarantees intact
    # (protection with no exposures to attach to — records the intended behaviour).
    bundle = make_raw_bundle(
        loans=_loans([("L1", "BOOK_A", "CP1", None)]),
        guarantees=pl.DataFrame(
            {
                "guarantee_reference": ["G1"],
                "beneficiary_reference": ["L1"],
                "guarantor_entity_reference": [None],
            }
        ),
        reporting_entities=_registry(_TREE),
        book_entity_mappings=pl.DataFrame(
            {"book_code": ["BOOK_A"], "reporting_entity_reference": ["BANK_A"]}
        ),
    )

    result = _resolve(bundle, "GHOST", ReportingBasis.CONSOLIDATED)

    assert result.loans.collect().height == 0
    assert result.guarantees.collect().height == 1
