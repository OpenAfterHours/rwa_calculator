"""
Scope resolver — the whole reporting group's population (RC-07 / RG-02 / RE-12).

``resolve_group_population`` publishes, beside the scope-filtered RAW_DATA, the
population a consolidated run at the registry root would see: every in-registry
book, intragroup claims on registry entities removed. The hierarchy stage sums
the retail-threshold aggregate and the Art. 501 E* over it on a solo /
sub-consolidated run, because those aggregates count debt "owed to the
institution, its parent undertakings, its subsidiaries and subsidiaries of its
parent undertakings" (PS1/26 Art. 123A(1)(b)(ii)) / "owed to the institution,
its subsidiaries, its parent undertakings and other subsidiaries of those parent
undertakings" (CRR Art. 501(1)) — the whole registry tree.

It is None whenever the run's own population is already that population, so
those runs stay byte-identical: no artifact, no group pass.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.context import PipelineContext
from rwa_calc.domain.enums import ReportingBasis
from rwa_calc.engine.orchestrator import GROUP_POPULATION, RAW_DATA
from rwa_calc.engine.scope import resolve_group_population
from rwa_calc.engine.stages.scope import run as scope_run
from rwa_calc.rulebook import RulepackV0

_TREE = pl.DataFrame(
    {
        "entity_reference": ["GRP", "BANK_A", "BANK_B"],
        "parent_entity_reference": [None, "GRP", "GRP"],
    }
)
_MAPPING = pl.DataFrame(
    {
        "book_code": ["BOOK_G", "BOOK_A", "BOOK_B"],
        "reporting_entity_reference": ["GRP", "BANK_A", "BANK_B"],
    }
)


def _loans() -> pl.DataFrame:
    """One external loan per entity, one intragroup claim, one unmapped book.

    ``L_IG`` is BANK_A's claim on BANK_B (a registry entity): a claim on a group
    entity, not debt of a third-party obligor. ``L_UNKNOWN_TAG`` is tagged to an
    entity outside the registry, so it stays (SCP003 treats it as external).
    ``L_UNMAPPED`` has a book no mapping attributes (SCP001).
    """
    return pl.DataFrame(
        {
            "loan_reference": ["L_G", "L_A", "L_B", "L_IG", "L_UNKNOWN_TAG", "L_UNMAPPED"],
            "book_code": ["BOOK_G", "BOOK_A", "BOOK_B", "BOOK_A", "BOOK_B", "BOOK_X"],
            "counterparty_reference": ["CP1", "CP1", "CP1", "BANK_B_CP", "CP2", "CP1"],
            "intragroup_entity_reference": [None, None, None, "BANK_B", "NOT_IN_REG", None],
        }
    )


def _bundle():
    return make_raw_bundle(loans=_loans(), reporting_entities=_TREE, book_entity_mappings=_MAPPING)


def _config(entity: str | None, basis: ReportingBasis | None) -> CalculationConfig:
    scope: dict[str, Any] = {}
    if entity is not None:
        scope = {"reporting_entity": entity, "reporting_basis": basis}
    return CalculationConfig.crr(reporting_date=date(2026, 1, 1), **scope)


def _loan_refs(bundle) -> set[str]:
    return set(bundle.loans.collect()["loan_reference"].to_list())


@pytest.mark.parametrize(
    ("entity", "basis"),
    [
        ("BANK_A", ReportingBasis.INDIVIDUAL),
        ("BANK_A", ReportingBasis.SUB_CONSOLIDATED),
        ("GRP", ReportingBasis.INDIVIDUAL),
    ],
    ids=["bank-a-individual", "bank-a-subconsolidated", "root-individual"],
)
def test_group_population_holds_every_registry_book(entity: str, basis: ReportingBasis) -> None:
    """Every attributable book of every registry entity, intragroup claims removed."""
    population = resolve_group_population(_bundle(), _config(entity, basis))

    assert population is not None
    assert _loan_refs(population) == {"L_G", "L_A", "L_B", "L_UNKNOWN_TAG"}


def test_root_consolidated_run_publishes_nothing() -> None:
    """The root's consolidated population IS the whole group: no second pass."""
    population = resolve_group_population(_bundle(), _config("GRP", ReportingBasis.CONSOLIDATED))

    assert population is None


def test_unknown_entity_publishes_nothing() -> None:
    """No scope resolves (resolve_scope reports SCP006): nothing to widen."""
    population = resolve_group_population(
        _bundle(), _config("NOT_AN_ENTITY", ReportingBasis.INDIVIDUAL)
    )

    assert population is None


def test_invalid_registry_publishes_nothing() -> None:
    """Two roots (resolve_scope reports SCP004): nothing to widen."""
    two_roots = pl.DataFrame(
        {"entity_reference": ["GRP", "BANK_A"], "parent_entity_reference": [None, None]}
    )
    bundle = make_raw_bundle(
        loans=_loans(), reporting_entities=two_roots, book_entity_mappings=_MAPPING
    )

    population = resolve_group_population(bundle, _config("BANK_A", ReportingBasis.INDIVIDUAL))

    assert population is None


def test_scope_stage_publishes_group_population_beside_the_filtered_bundle() -> None:
    """RAW_DATA keeps the solo filter; GROUP_POPULATION carries the whole group."""
    config = _config("BANK_A", ReportingBasis.INDIVIDUAL)
    ctx = PipelineContext.empty().put(RAW_DATA, _bundle())

    result = scope_run(ctx, RulepackV0.from_config(config), config)

    assert _loan_refs(result.get(RAW_DATA)) == {"L_A", "L_IG"}
    population = result.get(GROUP_POPULATION)
    assert population is not None
    assert _loan_refs(population) == {"L_G", "L_A", "L_B", "L_UNKNOWN_TAG"}


def test_unscoped_run_publishes_no_group_population() -> None:
    """I1: the unscoped stage is the identity, so the artifact is never written."""
    config = _config(None, None)
    ctx = PipelineContext.empty().put(RAW_DATA, _bundle())

    result = scope_run(ctx, RulepackV0.from_config(config), config)

    assert result is ctx
    assert not result.has(GROUP_POPULATION)
