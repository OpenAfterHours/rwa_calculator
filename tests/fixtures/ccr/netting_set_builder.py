"""
Netting-set-level fixture builder for SA-CCR tests.

Pipeline position:
    fixture-builder output -> test-writer (tests/integration/, tests/acceptance/)
    -> engine-implementer (CCR calculator)

Key responsibilities:
- Provide a frozen dataclass ``NettingSet`` whose fields mirror
  ``NETTING_SET_SCHEMA`` exactly.
- ``make_netting_set(**overrides)`` produces a single ``NettingSet`` with
  defaults matching the CCR-A1 golden scenario (legally enforceable, unmargined).
- ``create_netting_sets(netting_sets)`` converts a list to a ``pl.DataFrame``
  typed by ``dtypes_of(NETTING_SET_SCHEMA)``.

References:
    - CRR Art. 272(4) (netting set definition)
    - CRR Art. 295 (conditions for netting agreement recognition)
    - CRR Art. 285(2)(b) (10-day minimum MPOR for standard margined sets)
    - src/rwa_calc/data/schemas.py — NETTING_SET_SCHEMA
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import NETTING_SET_SCHEMA

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NettingSet:
    """
    One netting set for SA-CCR input.

    Fields mirror ``NETTING_SET_SCHEMA`` in ``src/rwa_calc/data/schemas.py``
    exactly.  Required fields (no default) correspond to the 2
    ``ColumnSpec(required=True)`` entries; optional fields carry the same
    defaults as the ``ColumnSpec`` declarations.

    References:
        - CRR Art. 272(4) (netting set definition)
        - CRR Art. 295 (legal enforceability — conservative default False)
        - CRR Art. 285(2)(b) (mpor_days minimum 10 for standard margined sets)
    """

    # Required (2).
    netting_set_id: str
    counterparty_reference: str

    # Optional with defaults (2) — match ColumnSpec defaults in NETTING_SET_SCHEMA.
    # CRR Art. 295: conservative default False until legal enforceability is confirmed.
    is_legally_enforceable: bool = False
    is_margined: bool = False

    # Optional nullable (6) — null in the unmargined CCR-A1 case.
    netting_agreement_type: str | None = None
    margin_threshold: float | None = None
    minimum_transfer_amount: float | None = None
    nica: float | None = None
    mpor_days: int | None = None
    margin_agreement_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for ``pl.DataFrame`` construction."""
        return {
            "netting_set_id": self.netting_set_id,
            "counterparty_reference": self.counterparty_reference,
            "is_legally_enforceable": self.is_legally_enforceable,
            "is_margined": self.is_margined,
            "netting_agreement_type": self.netting_agreement_type,
            "margin_threshold": self.margin_threshold,
            "minimum_transfer_amount": self.minimum_transfer_amount,
            "nica": self.nica,
            "mpor_days": self.mpor_days,
            "margin_agreement_id": self.margin_agreement_id,
        }


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_netting_set(**overrides: Any) -> NettingSet:
    """
    Return a ``NettingSet`` with CCR-A1 golden defaults, optionally overridden.

    Default values represent the canonical CCR-A1 single-netting-set scenario:
    NS_001 linked to counterparty CP_001, legally enforceable (Art. 295
    condition met), unmargined.  All margined-RC/MF columns are null.

    Args:
        **overrides: Any ``NettingSet`` field keyword arguments.

    Returns:
        A frozen ``NettingSet`` instance.
    """
    defaults: dict[str, Any] = {
        "netting_set_id": "NS_001",
        "counterparty_reference": "CP_001",
        "is_legally_enforceable": True,
        "is_margined": False,
        "netting_agreement_type": None,
        "margin_threshold": None,
        "minimum_transfer_amount": None,
        "nica": None,
        "mpor_days": None,
        "margin_agreement_id": None,
    }
    defaults.update(overrides)
    return NettingSet(**defaults)


def create_netting_sets(netting_sets: list[NettingSet]) -> pl.DataFrame:
    """
    Convert a list of ``NettingSet`` instances into a Polars DataFrame.

    Schema is enforced via ``dtypes_of(NETTING_SET_SCHEMA)``.

    Args:
        netting_sets: One or more ``NettingSet`` instances.

    Returns:
        ``pl.DataFrame`` with columns matching ``NETTING_SET_SCHEMA``.
    """
    return pl.DataFrame([ns.to_dict() for ns in netting_sets], schema=dtypes_of(NETTING_SET_SCHEMA))
