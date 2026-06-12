"""
Contract-derived RawDataBundle builder (migration Phase 3).

The sanctioned way tests construct raw input bundles: every frame field is
sealed against its loader edge contract (``RAW_TABLE_EDGES``) exactly as
the production loader seals it, so test bundles are shape-identical to
production-loaded ones — declared-but-absent columns appear as typed
nulls / defaults, undeclared scratch is stripped, Boolean defaults fill,
and the frame carries the edge brand that ``RawDataBundle.__post_init__``
validates.

Usage:
    from tests.fixtures.raw_bundle import make_raw_bundle

    bundle = make_raw_bundle(
        loans=pl.LazyFrame({...}),
        counterparties=pl.LazyFrame({...}),
    )

References:
- docs/plans/target-architecture-migration.md (Phase 3)
- contracts/edges.py (RAW_TABLE_EDGES, seal_lenient)
"""

from __future__ import annotations

from typing import Any

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.edges import RAW_TABLE_EDGES, seal_lenient

_REQUIRED_TABLES = ("facilities", "loans", "counterparties", "facility_mappings")


def seal_raw_table(
    frame: pl.LazyFrame | pl.DataFrame,
    field_name: str,
) -> pl.LazyFrame:
    """Seal one raw-table frame exactly as the loader does (leniently).

    Missing declared columns become typed nulls / defaults rather than
    errors — tests intentionally under-specify tables, mirroring sparse
    production files.
    """
    lf = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    sealed, _missing = seal_lenient(lf, RAW_TABLE_EDGES[field_name])
    return sealed


def make_raw_bundle(
    facilities: pl.LazyFrame | pl.DataFrame | None = None,
    loans: pl.LazyFrame | pl.DataFrame | None = None,
    counterparties: pl.LazyFrame | pl.DataFrame | None = None,
    facility_mappings: pl.LazyFrame | pl.DataFrame | None = None,
    **kwargs: Any,
) -> RawDataBundle:
    """Drop-in replacement for direct ``RawDataBundle(...)`` construction.

    Same keyword surface as ``RawDataBundle``; every frame field is sealed
    against its loader edge contract before construction, and required
    tables left unspecified default to empty sealed frames. ``ccr`` and
    ``errors`` pass through untouched.
    """
    frames: dict[str, pl.LazyFrame | pl.DataFrame | None] = {
        "facilities": facilities,
        "loans": loans,
        "counterparties": counterparties,
        "facility_mappings": facility_mappings,
    }
    for field_name in RAW_TABLE_EDGES:
        if field_name not in frames:
            frames[field_name] = kwargs.pop(field_name, None)

    sealed: dict[str, Any] = {}
    for field_name, frame in frames.items():
        if frame is None:
            sealed[field_name] = (
                RAW_TABLE_EDGES[field_name].empty_frame()
                if field_name in _REQUIRED_TABLES
                else None
            )
        else:
            sealed[field_name] = seal_raw_table(frame, field_name)

    # kwargs now carries only the non-frame fields (ccr, errors).
    return RawDataBundle(**sealed, **kwargs)
