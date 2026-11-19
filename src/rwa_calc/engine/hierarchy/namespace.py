"""
Cross-table exposure_reference namespace resolution for the hierarchy stage.

Pipeline position:
    securitisation_allocator -> [namespace] -> HierarchyResolver -> ccr_sa_ccr
    Called by the hierarchy stage adapter (``engine/stages/hierarchy.py``) on the
    raw bundle before ``HierarchyResolver.resolve`` and on the securitisation
    lookup before it is attached.

Key responsibilities:
- Keep apart the loan / contingent rows whose reference another exposure
  namespace also claims (review finding RC-10): each colliding row is re-keyed
  to ``<reference>#<type>`` (``X1#loan`` / ``X1#contingent``).
- Resolve every TYPED pointer to such a row to its new key by the type it
  declares: facility mappings (``child_type``), short-term rating scopes
  (``scope_type``), collateral / collateral-link / guarantee / provision
  beneficiaries (``beneficiary_type``) and securitisation allocations
  (``exposure_type``). A pointer whose type does not name the row
  (``beneficiary_type`` ``'exposure'`` or null) is left as it is, so it matches
  neither row — the conservative reading of an ambiguous pointer.

Why re-key rather than make each join type-aware: uniqueness was declared per
table only, so every join, de-duplication and window keyed on the bare reference
merged the two rows — the IRB model-permission de-duplication kept one of them
(EAD 2m -> 1m), a guarantee on the loan covered the contingent too (EAD 2m ->
1m, RWA 1m -> 0). Re-keying at the one place every consumer reads from makes
all of them type-aware at once, including any added later.

The collisions are the input gate's DQ019 findings
(``contracts/validation.py::validate_duplicate_keys``, already on the bundle's
``errors`` when the stage runs): the re-key reads them rather than re-deriving
them, so the resolution and the error describing it cannot disagree, and a clean
book — no DQ019 — leaves every frame untouched.

References:
- CRR / PS1/26 Art. 111(1): each item's exposure value is measured
- CRR / PS1/26 Art. 213(1)(a): "the credit protection is direct"
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.edges import RAW_TABLE_EDGES, seal
from rwa_calc.contracts.errors import ERROR_EXPOSURE_REFERENCE_COLLISION
from rwa_calc.data.schemas import EXPOSURE_REFERENCE_QUALIFIER, VALID_CHILD_TYPES

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import RawDataBundle

logger = logging.getLogger(__name__)


def colliding_references(data: RawDataBundle) -> list[str]:
    """The references the input gate found claimed by several namespaces (DQ019).

    Sorted and unique. Empty — the overwhelmingly common case — means there is
    nothing to re-key.
    """
    return sorted(
        {
            error.exposure_reference
            for error in data.errors
            if error.code == ERROR_EXPOSURE_REFERENCE_COLLISION
            and error.exposure_reference is not None
        }
    )


def qualify_colliding_references(data: RawDataBundle, collided: list[str]) -> RawDataBundle:
    """Re-key colliding loan / contingent rows and every typed pointer to them.

    Args:
        data: The raw bundle the hierarchy stage resolves.
        collided: :func:`colliding_references` of ``data``.

    Returns:
        ``data`` itself when nothing collides; otherwise a bundle whose loans /
        contingents carry ``<reference>#<type>`` for each colliding reference,
        and whose facility mappings, ratings, collateral, collateral links,
        guarantees and provisions point at those keys by their declared type.
        Every rewritten frame is re-sealed to its raw edge.
    """
    if not collided:
        return data
    logger.warning(
        "re-keying %d exposure_reference(s) claimed by more than one namespace (DQ019)",
        len(collided),
    )
    updates: dict[str, pl.LazyFrame] = {
        "loans": _qualify_rows(data.loans, "loan_reference", "loan", collided),
        "facility_mappings": _qualify_pointers(
            data.facility_mappings, "child_reference", "child_type", collided
        ),
    }
    if data.contingents is not None:
        updates["contingents"] = _qualify_rows(
            data.contingents, "contingent_reference", "contingent", collided
        )
    pointers = {
        "ratings": ("scope_id", "scope_type"),
        "collateral": ("beneficiary_reference", "beneficiary_type"),
        "collateral_links": ("beneficiary_reference", "beneficiary_type"),
        "guarantees": ("beneficiary_reference", "beneficiary_type"),
        "provisions": ("beneficiary_reference", "beneficiary_type"),
    }
    for field, (reference, kind) in pointers.items():
        frame = getattr(data, field)
        if frame is not None:
            updates[field] = _qualify_pointers(frame, reference, kind, collided)
    return replace(
        data,
        **{field: seal(frame, RAW_TABLE_EDGES[field]) for field, frame in updates.items()},
    )


def qualify_securitisation_lookup(
    lookup: pl.LazyFrame | None, collided: list[str]
) -> pl.LazyFrame | None:
    """Point the resolved securitisation lookup at the re-keyed rows.

    The lookup is keyed on ``(exposure_reference, exposure_type)`` as supplied;
    an allocation to ``(X1, loan)`` must follow the loan to ``X1#loan``.
    """
    if lookup is None or not collided:
        return lookup
    return _qualify_pointers(lookup, "exposure_reference", "exposure_type", collided)


def _qualify_rows(
    frame: pl.LazyFrame, reference: str, exposure_type: str, collided: list[str]
) -> pl.LazyFrame:
    """Re-key the rows of one exposure table whose reference collides."""
    return frame.with_columns(
        pl.when(pl.col(reference).is_in(collided))
        .then(pl.col(reference) + pl.lit(EXPOSURE_REFERENCE_QUALIFIER + exposure_type))
        .otherwise(pl.col(reference))
        .alias(reference)
    )


def _qualify_pointers(
    frame: pl.LazyFrame, reference: str, kind: str, collided: list[str]
) -> pl.LazyFrame:
    """Re-key the pointers whose declared type names a colliding loan / contingent.

    The type is read case-insensitively, exactly as the consumers read it, and
    becomes the qualifier, so ``('loan', 'X1')`` points at ``X1#loan``. A
    pointer of any other type — a facility, a counterparty, the generic
    ``'exposure'`` or null — is left unchanged.
    """
    declared = pl.col(kind).str.strip_chars().str.to_lowercase()
    hit = declared.is_in(sorted(VALID_CHILD_TYPES - {"facility"})).eq_missing(True) & pl.col(
        reference
    ).is_in(collided)
    return frame.with_columns(
        pl.when(hit)
        .then(pl.col(reference) + pl.lit(EXPOSURE_REFERENCE_QUALIFIER) + declared)
        .otherwise(pl.col(reference))
        .alias(reference)
    )
