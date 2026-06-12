"""
Shared CRM test scaffolding for the ``tests/unit/crm`` cluster.

Provides the empty :class:`CounterpartyLookup` used by the local ``_make_bundle``
helpers across the collateral / netting / guarantee unit tests. The four lookup
frames are genuinely identical across those modules, so the empty-frame
construction is factored here while each test file keeps its own divergent
``_make_bundle`` signature (required ``collateral``, ``collateral | None`` or
``guarantees``).
"""

from __future__ import annotations

import polars as pl
from tests.fixtures.resolved_bundle import make_counterparty_lookup

from rwa_calc.contracts.bundles import CounterpartyLookup


def empty_counterparty_lookup() -> CounterpartyLookup:
    """Build a :class:`CounterpartyLookup` whose four frames are empty.

    Mirrors the post-classifier state for tests that exercise CRM in isolation
    and do not rely on any resolved counterparty hierarchy.
    """
    counterparties = pl.LazyFrame(
        schema={"counterparty_reference": pl.String, "entity_type": pl.String}
    )
    parent_mappings = pl.LazyFrame(
        schema={
            "child_counterparty_reference": pl.String,
            "parent_counterparty_reference": pl.String,
        }
    )
    ultimate_parent_mappings = pl.LazyFrame(
        schema={
            "counterparty_reference": pl.String,
            "ultimate_parent_reference": pl.String,
            "hierarchy_depth": pl.Int32,
        }
    )
    rating_inheritance = pl.LazyFrame(
        schema={"counterparty_reference": pl.String, "cqs": pl.Int8, "rating_type": pl.String}
    )
    return make_counterparty_lookup(
        counterparties=counterparties,
        parent_mappings=parent_mappings,
        ultimate_parent_mappings=ultimate_parent_mappings,
        rating_inheritance=rating_inheritance,
    )
