"""
Margin-agreement-level fixture builder for SA-CCR tests.

Pipeline position:
    fixture-builder output -> test-writer (tests/integration/, tests/acceptance/)
    -> engine-implementer (CCR calculator)

Key responsibilities:
- Provide a frozen dataclass ``Margin`` whose fields mirror
  ``MARGIN_AGREEMENT_SCHEMA`` exactly.
- ``make_margin(**overrides)`` produces a single ``Margin`` instance with
  regulatory-minimum defaults (mpor_days=10 per Art. 285(2)(b)).
- ``create_margin_agreements(margins)`` converts a list to a ``pl.DataFrame``
  typed by ``dtypes_of(MARGIN_AGREEMENT_SCHEMA)``.

The unmargined CCR-A1 golden scenario carries zero margin agreements; the
empty-frame path is produced by calling ``create_margin_agreements([])``.

References:
    - CRR Art. 272(7) (margin agreement / CSA definition)
    - CRR Art. 285(2)(b) (10-day minimum MPOR for standard margined netting sets)
    - CRR Art. 285(3)(a) (segregated IM — False by default)
    - src/rwa_calc/data/schemas.py — MARGIN_AGREEMENT_SCHEMA
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import MARGIN_AGREEMENT_SCHEMA

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Margin:
    """
    One margin agreement (CSA/ISDA Credit Support Annex) for SA-CCR input.

    Fields mirror ``MARGIN_AGREEMENT_SCHEMA`` in
    ``src/rwa_calc/data/schemas.py`` exactly.  Required fields (no default)
    correspond to the 2 ``ColumnSpec(required=True)`` entries; optional fields
    carry the same defaults as the ``ColumnSpec`` declarations.

    References:
        - CRR Art. 272(7) (margin agreement definition)
        - CRR Art. 285(2)(b) (mpor_days regulatory minimum = 10)
        - CRR Art. 285(3)(a) (is_segregated_im)
    """

    # Required (2).
    margin_agreement_id: str
    counterparty_reference: str

    # Optional with defaults (5) — match ColumnSpec defaults in MARGIN_AGREEMENT_SCHEMA.
    margin_threshold: float = 0.0
    minimum_transfer_amount: float = 0.0
    nica: float = 0.0
    # CRR Art. 285(2)(b): minimum MPOR for standard margined netting sets = 10 business days.
    mpor_days: int = 10
    is_segregated_im: bool = False

    # Optional nullable (3).
    remargining_frequency_days: int | None = None
    dispute_count_qtr: int | None = None
    governing_law: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for ``pl.DataFrame`` construction."""
        return {
            "margin_agreement_id": self.margin_agreement_id,
            "counterparty_reference": self.counterparty_reference,
            "margin_threshold": self.margin_threshold,
            "minimum_transfer_amount": self.minimum_transfer_amount,
            "nica": self.nica,
            "mpor_days": self.mpor_days,
            "is_segregated_im": self.is_segregated_im,
            "remargining_frequency_days": self.remargining_frequency_days,
            "dispute_count_qtr": self.dispute_count_qtr,
            "governing_law": self.governing_law,
        }


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_margin(**overrides: Any) -> Margin:
    """
    Return a ``Margin`` with regulatory-minimum defaults, optionally overridden.

    Default values use the regulatory minimum MPOR of 10 days (CRR Art.
    285(2)(b)), zero threshold and MTA, zero NICA, and non-segregated IM.

    Args:
        **overrides: Any ``Margin`` field keyword arguments.

    Returns:
        A frozen ``Margin`` instance.
    """
    defaults: dict[str, Any] = {
        "margin_agreement_id": "MA_001",
        "counterparty_reference": "CP_001",
        "margin_threshold": 0.0,
        "minimum_transfer_amount": 0.0,
        "nica": 0.0,
        "mpor_days": 10,
        "is_segregated_im": False,
        "remargining_frequency_days": None,
        "dispute_count_qtr": None,
        "governing_law": None,
    }
    defaults.update(overrides)
    return Margin(**defaults)


def create_margin_agreements(margins: list[Margin]) -> pl.DataFrame:
    """
    Convert a list of ``Margin`` instances into a Polars DataFrame.

    An empty list produces a zero-row DataFrame with full
    ``MARGIN_AGREEMENT_SCHEMA`` column set — the canonical unmargined case.

    Args:
        margins: Zero or more ``Margin`` instances.

    Returns:
        ``pl.DataFrame`` with columns matching ``MARGIN_AGREEMENT_SCHEMA``.
    """
    return pl.DataFrame([m.to_dict() for m in margins], schema=dtypes_of(MARGIN_AGREEMENT_SCHEMA))
