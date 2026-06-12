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

# Production loader dtypes (data/schemas.py COLLATERAL_SCHEMA) for the columns
# the synthetic netting-collateral frame also emits. The CRM processor
# diagonally concatenates input collateral with that synthetic frame whenever
# the exposures carry a ``netting_agreement_reference`` column — which, post
# classifier-exit seal, is always (typed null when unspecified). The concat
# requires matching dtypes on overlapping columns; production collateral is
# loader-sealed to these dtypes, so hand-rolled test frames must match or the
# merged frame fails schema resolution and collateral CRM is skipped (CRM001).
COLLATERAL_DTYPES: dict[str, pl.DataType] = {
    "collateral_reference": pl.String(),
    "collateral_type": pl.String(),
    "currency": pl.String(),
    "maturity_date": pl.Date(),
    "market_value": pl.Float64(),
    "nominal_value": pl.Float64(),
    "pledge_percentage": pl.Float64(),
    "beneficiary_type": pl.String(),
    "beneficiary_reference": pl.String(),
    "issuer_cqs": pl.Int8(),
    "issuer_type": pl.String(),
    "residual_maturity_years": pl.Float64(),
    "is_eligible_financial_collateral": pl.Boolean(),
    "is_eligible_irb_collateral": pl.Boolean(),
    "valuation_date": pl.Date(),
    "valuation_type": pl.String(),
    "property_type": pl.String(),
    "property_ltv": pl.Float64(),
    "is_income_producing": pl.Boolean(),
    "is_adc": pl.Boolean(),
    "is_presold": pl.Boolean(),
}


def normalise_collateral(frame: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """Cast a hand-rolled collateral frame to production loader dtypes.

    Only columns present on the frame AND shared with the synthetic netting
    frame are cast; everything else passes through untouched. Mirrors the
    loader-edge seal the production collateral table always goes through.
    """
    lf = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    schema = lf.collect_schema()
    casts = [
        pl.col(name).cast(dtype)
        for name, dtype in COLLATERAL_DTYPES.items()
        if name in schema.names() and schema[name] != dtype
    ]
    return lf.with_columns(casts) if casts else lf


def with_ancestor_facilities(frame: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """Derive ``ancestor_facilities`` from ``parent_facility_reference``.

    Production hierarchy always emits the ancestor closure (parent + all
    ancestors up to root); post classifier-exit seal the column exists as a
    typed null when a test omits it, which disables the engine's absent-column
    fallback and silently de-activates facility-level collateral/guarantee
    cascades. Single-level test fixtures get the production-equivalent
    1-element ``[parent_facility_reference]`` list.
    """
    lf = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    names = lf.collect_schema().names()
    if "ancestor_facilities" in names or "parent_facility_reference" not in names:
        return lf
    return lf.with_columns(
        pl.concat_list(pl.col("parent_facility_reference").cast(pl.String)).alias(
            "ancestor_facilities"
        )
    )


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
