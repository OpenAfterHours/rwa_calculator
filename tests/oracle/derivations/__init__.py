"""
Independent oracle derivations -- the shadow calculator.

Every module in this package re-derives an expected RWA from the regulation
using **only the Python standard library**. Nothing here may import
``rwa_calc``: the whole point of the oracle is that it is a causally
independent second opinion, so a value that came (however indirectly) from the
engine is worthless as evidence about the engine.

That constraint is enforced, not merely documented, by
``tests/oracle/test_oracle.py::test_derivations_never_import_rwa_calc``, which
parses every module in this package (and ``derive.py``) and fails on any
``rwa_calc`` import.

Phases:
    O1  ``sa_crr`` + ``sa_b31``  -- Standardised Approach, every exposure class
    O2  ``irb``                  -- Foundation and Advanced IRB
    O3  ``crm_sa``               -- credit risk mitigation, SA side
    O4  ``specialised``          -- slotting and IRB equity
"""

from __future__ import annotations

from typing import Any

from . import crm_sa, irb, sa_b31, sa_crr, specialised

#: Every derivation module, in the order their oracles appear in the JSON.
MODULES = (sa_crr, sa_b31, irb, crm_sa, specialised)


def all_oracles() -> list[dict[str, Any]]:
    """Every oracle record, sorted by identifier so the JSON is stable."""
    records: list[dict[str, Any]] = []
    for module in MODULES:
        records.extend(module.all_oracles())

    ids = [record["exposure_id"] for record in records]
    duplicates = sorted({oid for oid in ids if ids.count(oid) > 1})
    if duplicates:
        raise ValueError(f"duplicate oracle identifiers: {duplicates}")

    return sorted(records, key=lambda record: record["exposure_id"])
