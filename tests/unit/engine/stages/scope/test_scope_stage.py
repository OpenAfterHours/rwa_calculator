"""
Scope resolver stage adapter — identity no-op, republication, and the
end-to-end multi-entity fixture counts.

The hard invariant I1: an unscoped run (no ``reporting_entity``) returns the
context object unchanged, so the pipeline behaves byte-identically to today.
When a scope IS configured, the stage republishes the SAME RAW_DATA key with a
filtered bundle.

References:
- CRR Part One Title II (Art. 6, 11-18): levels of application.
- docs/plans/multi-entity-reporting.md: scope resolver specification.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.context import PipelineContext
from rwa_calc.domain.enums import ReportingBasis
from rwa_calc.engine.loader import ParquetLoader
from rwa_calc.engine.orchestrator import RAW_DATA
from rwa_calc.engine.stages.scope import run as scope_run

_FIXTURE_DIR = Path(__file__).resolve().parents[4] / "fixtures" / "multi_entity"

_TREE = pl.DataFrame(
    {
        "entity_reference": ["GRP", "BANK_A", "BANK_B"],
        "parent_entity_reference": [None, "GRP", "GRP"],
    }
)
_MAPPING = pl.DataFrame(
    {"book_code": ["BOOK_A", "BOOK_B"], "reporting_entity_reference": ["BANK_A", "BANK_B"]}
)


def _loans() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "loan_reference": ["LA", "LB"],
            "book_code": ["BOOK_A", "BOOK_B"],
            "counterparty_reference": ["CP1", "CP2"],
            "intragroup_entity_reference": [None, None],
        }
    )


def _ctx(bundle) -> PipelineContext:
    return PipelineContext.empty().put(RAW_DATA, bundle)


# ---------------------------------------------------------------------------
# Identity no-op (I1)
# ---------------------------------------------------------------------------


def test_unscoped_run_returns_context_unchanged():
    bundle = make_raw_bundle(
        loans=_loans(), reporting_entities=_TREE, book_entity_mappings=_MAPPING
    )
    ctx = _ctx(bundle)
    config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))  # no reporting_entity

    result = scope_run(ctx, None, config)

    assert result is ctx


def test_unscoped_run_leaves_raw_data_bundle_identical():
    bundle = make_raw_bundle(
        loans=_loans(), reporting_entities=_TREE, book_entity_mappings=_MAPPING
    )
    ctx = _ctx(bundle)
    config = CalculationConfig.crr(reporting_date=date(2026, 1, 1))

    result = scope_run(ctx, None, config)

    assert result.get(RAW_DATA) is bundle


# ---------------------------------------------------------------------------
# Republication under scope
# ---------------------------------------------------------------------------


def test_scoped_run_republishes_filtered_bundle_on_same_key():
    bundle = make_raw_bundle(
        loans=_loans(), reporting_entities=_TREE, book_entity_mappings=_MAPPING
    )
    ctx = _ctx(bundle)
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 1),
        reporting_entity="BANK_A",
        reporting_basis=ReportingBasis.INDIVIDUAL,
    )

    result = scope_run(ctx, None, config)

    filtered = result.get(RAW_DATA)
    assert filtered is not bundle
    assert set(filtered.loans.collect()["loan_reference"].to_list()) == {"LA"}


# ---------------------------------------------------------------------------
# End-to-end: the multi-entity fixture loaded through ParquetLoader
# ---------------------------------------------------------------------------


def _resolve_loaded(entity: str, basis: ReportingBasis):
    from rwa_calc.engine.stages.scope import resolve_scope

    bundle = ParquetLoader(base_path=_FIXTURE_DIR).load()
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 1), reporting_entity=entity, reporting_basis=basis
    )
    return resolve_scope(bundle, config)


def test_fixture_grp_consolidated_has_three_loans_no_scope_errors():
    result = _resolve_loaded("GRP", ReportingBasis.CONSOLIDATED)

    assert result.loans.collect().height == 3
    assert [e.code for e in result.errors if e.code.startswith("SCP")] == []


def test_fixture_bank_a_individual_has_three_loans_no_scope_errors():
    result = _resolve_loaded("BANK_A", ReportingBasis.INDIVIDUAL)

    assert result.loans.collect().height == 3
    assert [e.code for e in result.errors if e.code.startswith("SCP")] == []


def test_fixture_bank_b_individual_has_two_loans_no_scope_errors():
    result = _resolve_loaded("BANK_B", ReportingBasis.INDIVIDUAL)

    assert result.loans.collect().height == 2
    assert [e.code for e in result.errors if e.code.startswith("SCP")] == []


def test_fixture_consolidated_eliminates_intragroup_but_solo_keeps_it():
    # Solo BANK_A (3) + solo BANK_B (2) = 5 raw loans, but consolidated GRP = 3:
    # the two intragroup loans are counted once solo, eliminated at group level.
    grp = _resolve_loaded("GRP", ReportingBasis.CONSOLIDATED).loans.collect().height
    bank_a = _resolve_loaded("BANK_A", ReportingBasis.INDIVIDUAL).loans.collect().height
    bank_b = _resolve_loaded("BANK_B", ReportingBasis.INDIVIDUAL).loans.collect().height

    assert (grp, bank_a + bank_b) == (3, 5)
