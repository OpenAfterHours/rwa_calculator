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
    ResolvedHierarchyBundle,
    create_empty_counterparty_lookup,
)
from rwa_calc.contracts.edges import HIERARCHY_EXIT_EDGE, seal_lenient


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
    return ResolvedHierarchyBundle(exposures=seal_hierarchy_exit(exposures), **kwargs)
