"""
Shared fixtures and helpers for CRM processor unit tests.

Provides the mechanical scaffolding common to the guarantee/CRM test
modules in this directory:

- ``crr_config`` / ``basel31_config`` — framework configurations
- ``crm_processor`` — a fresh :class:`CRMProcessor` per test
- ``_counterparty_lookup`` — builds a :class:`CounterpartyLookup` with the
  empty fixed-schema parent / ultimate-parent / rating-inheritance frames that
  every guarantee scenario reuses

Per-test scenario data (exposures, guarantees, counterparties, ratings) stays
inline in the individual test modules per DAMP.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures.resolved_bundle import make_counterparty_lookup

from rwa_calc.contracts.bundles import CounterpartyLookup
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.crm.processor import CRMProcessor


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


@pytest.fixture
def basel31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 1, 1))


@pytest.fixture
def crm_processor() -> CRMProcessor:
    return CRMProcessor()


def _counterparty_lookup(
    counterparties: pl.LazyFrame,
    rating_inheritance: pl.LazyFrame | None = None,
) -> CounterpartyLookup:
    if rating_inheritance is None:
        rating_inheritance = pl.LazyFrame(
            schema={
                "counterparty_reference": pl.String,
                "cqs": pl.Int8,
                "pd": pl.Float64,
            }
        )
    return make_counterparty_lookup(
        counterparties=counterparties,
        parent_mappings=pl.LazyFrame(
            schema={
                "child_counterparty_reference": pl.String,
                "parent_counterparty_reference": pl.String,
            }
        ),
        ultimate_parent_mappings=pl.LazyFrame(
            schema={
                "counterparty_reference": pl.String,
                "ultimate_parent_reference": pl.String,
                "hierarchy_depth": pl.Int32,
            }
        ),
        rating_inheritance=rating_inheritance,
    )
