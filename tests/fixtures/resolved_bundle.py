"""
Contract-derived ResolvedHierarchyBundle builder (migration Phase 3).

The sanctioned way tests construct hierarchy-stage outputs: the unified
exposures frame is sealed against the ``hierarchy_exit`` edge contract
(leniently — tests under-specify columns exactly like sparse production
inputs, and the seal injects the rest as typed nulls), so test bundles are
shape-identical to the frame the classifier receives from the pipeline.

Usage:
    from tests.fixtures.resolved_bundle import make_resolved_bundle

    bundle = make_resolved_bundle(
        exposures=pl.LazyFrame({...}),
        counterparty_lookup=...,   # defaults to the empty lookup
    )

References:
- docs/plans/target-architecture-migration.md (Phase 3)
- contracts/edges.py (HIERARCHY_EXIT_EDGE)
"""

from __future__ import annotations

from typing import Any

import polars as pl

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CounterpartyLookup,
    ResolvedHierarchyBundle,
    create_empty_counterparty_lookup,
)
from rwa_calc.contracts.edges import (
    CLASSIFIER_EXIT_EDGE,
    CP_LOOKUP_EDGES,
    HIERARCHY_EXIT_EDGE,
    seal_lenient,
)
from tests.fixtures.raw_bundle import seal_raw_table


def seal_hierarchy_exit(frame: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """Seal a hand-rolled exposures frame against the hierarchy_exit edge.

    Lenient by design: missing declared columns become typed nulls (the
    classifier's input is always the full 80-column contract shape).
    """
    lf = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    sealed, _missing = seal_lenient(lf, HIERARCHY_EXIT_EDGE)
    return sealed


def make_resolved_bundle(
    exposures: pl.LazyFrame | pl.DataFrame,
    **kwargs: Any,
) -> ResolvedHierarchyBundle:
    """Drop-in replacement for direct ``ResolvedHierarchyBundle(...)``.

    Same keyword surface; ``exposures`` is sealed against hierarchy_exit,
    ``counterparty_lookup`` defaults to the empty lookup, every other
    field passes through untouched.
    """
    kwargs.setdefault("counterparty_lookup", create_empty_counterparty_lookup())
    # Registered pass-through fields must carry their loader-edge brands.
    for raw_field in (
        "collateral_links",
        "ciu_holdings",
        "specialised_lending",
        "model_permissions",
    ):
        frame = kwargs.get(raw_field)
        if frame is not None:
            kwargs[raw_field] = seal_raw_table(frame, raw_field)
    return ResolvedHierarchyBundle(exposures=seal_hierarchy_exit(exposures), **kwargs)


def make_counterparty_lookup(
    counterparties: pl.LazyFrame | pl.DataFrame | None = None,
    parent_mappings: pl.LazyFrame | pl.DataFrame | None = None,
    ultimate_parent_mappings: pl.LazyFrame | pl.DataFrame | None = None,
    rating_inheritance: pl.LazyFrame | pl.DataFrame | None = None,
) -> CounterpartyLookup:
    """Drop-in replacement for direct ``CounterpartyLookup(...)``.

    Each frame is sealed (leniently) against its cp_lookup_* edge contract;
    unspecified frames default to sealed empties.
    """
    frames: dict[str, pl.LazyFrame] = {}
    supplied = {
        "counterparties": counterparties,
        "parent_mappings": parent_mappings,
        "ultimate_parent_mappings": ultimate_parent_mappings,
        "rating_inheritance": rating_inheritance,
    }
    for field_name, frame in supplied.items():
        edge = CP_LOOKUP_EDGES[field_name]
        if frame is None:
            frames[field_name] = edge.empty_frame()
        else:
            lf = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
            sealed, _missing = seal_lenient(lf, edge)
            frames[field_name] = sealed
    return CounterpartyLookup(**frames)


def seal_classifier_exit(frame: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """Seal a hand-rolled classified frame against the classifier_exit edge.

    Lenient by design: missing declared columns become typed nulls (the
    CRM stage's input is always the full contract shape).
    """
    lf = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    sealed, _missing = seal_lenient(lf, CLASSIFIER_EXIT_EDGE)
    return sealed


def make_classified_bundle(
    all_exposures: pl.LazyFrame | pl.DataFrame,
    **kwargs: Any,
) -> ClassifiedExposuresBundle:
    """Drop-in replacement for direct ``ClassifiedExposuresBundle(...)``.

    Same keyword surface; ``all_exposures`` is sealed against
    classifier_exit, registered pass-through fields are sealed against
    their loader edges, everything else passes through untouched.
    """
    from tests.fixtures.raw_bundle import seal_raw_table

    for raw_field in ("collateral_links", "ciu_holdings"):
        frame = kwargs.get(raw_field)
        if frame is not None:
            kwargs[raw_field] = seal_raw_table(frame, raw_field)
    return ClassifiedExposuresBundle(
        all_exposures=seal_classifier_exit(all_exposures), **kwargs
    )
