"""
Margined Replacement Cost fixture builder for P8.11 SA-CCR unit tests.

Pipeline position:
    fixture-builder output -> test-writer (tests/unit/ccr/test_rc_margined.py)
    -> engine-implementer (rwa_calc.engine.ccr.rc.compute_rc_margined)

Key responsibilities:
- Expose four named scenario rows (NS_A through NS_D) whose ``rc_margined``
  expected values are pre-verified against the formula
  ``RC = max(V - C, TH + MTA - NICA, 0)`` per CRR Art. 275(2) / BCBS CRE52.11.
- ``make_rc_margined_frame()`` assembles those rows into a ``pl.LazyFrame``
  with all ``NETTING_SET_SCHEMA`` columns plus the upstream-derived
  ``v_net`` and ``c_net`` columns.
- ``EXPECTED_RC`` maps ``netting_set_id`` to the expected ``rc_margined``
  value (``None`` for the unmargined NS_D pass-through row).

No parquet output is required: this is a Python-only builder consumed by
unit tests that construct the input frame inline.

Formula verification (hand-calc):
    NS_A: max(2_000_000 - 1_850_000,  250_000 + 100_000 - 50_000,  0) = max(150k, 300k, 0) = 300_000
    NS_B: max(1_500_000 -   400_000,  100_000 +  50_000 - 25_000,  0) = max(1.1M, 125k, 0) = 1_100_000
    NS_C: max(  -500_000 -       0,    50_000 +  10_000 - 200_000, 0) = max(-500k, -140k, 0) = 0
    NS_D: is_margined=False -> rc_margined is null (pass-through, not computed)

References:
    - CRR Art. 275(2): margined RC formula
    - BCBS CRE52.11: RC = max(V - C, TH + MTA - NICA, 0)
    - src/rwa_calc/data/schemas.py — NETTING_SET_SCHEMA
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import NETTING_SET_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

#: Netting set identifiers for each row.
NS_A_ID: str = "NS_A"
NS_B_ID: str = "NS_B"
NS_C_ID: str = "NS_C"
NS_D_ID: str = "NS_D"

#: Counterparty references (not driving the test logic — unique strings only).
CP_A_REF: str = "CP_A"
CP_B_REF: str = "CP_B"
CP_C_REF: str = "CP_C"
CP_D_REF: str = "CP_D"

#: Expected rc_margined per netting set (None = pass-through, not computed).
EXPECTED_RC: dict[str, float | None] = {
    NS_A_ID: 300_000.0,
    NS_B_ID: 1_100_000.0,
    NS_C_ID: 0.0,
    NS_D_ID: None,
}

# ---------------------------------------------------------------------------
# Per-row scenario dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RcMarginedRow:
    """
    One netting-set row for the margined RC unit test.

    Fields mirror ``NETTING_SET_SCHEMA`` (excluding ``netting_agreement_type``,
    ``mpor_days``, and ``margin_agreement_id`` which are null for these
    scenarios) plus the upstream-derived ``v_net`` and ``c_net`` columns.

    References:
        - CRR Art. 275(2): V_net and C_net are netting-set-grain aggregates
          produced upstream of the RC calculation stage.
    """

    netting_set_id: str
    counterparty_reference: str
    is_legally_enforceable: bool
    is_margined: bool
    margin_threshold: float | None
    minimum_transfer_amount: float | None
    nica: float | None
    # Upstream-derived: net mark-to-market value and net collateral held.
    v_net: float
    c_net: float

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict for ``pl.DataFrame`` construction."""
        return {
            "netting_set_id": self.netting_set_id,
            "counterparty_reference": self.counterparty_reference,
            "is_legally_enforceable": self.is_legally_enforceable,
            "is_margined": self.is_margined,
            # Nullable NETTING_SET_SCHEMA columns (schema fields without a row value).
            "netting_agreement_type": None,
            "margin_threshold": self.margin_threshold,
            "minimum_transfer_amount": self.minimum_transfer_amount,
            "nica": self.nica,
            "mpor_days": None,
            "margin_agreement_id": None,
            # Upstream-derived columns (not in NETTING_SET_SCHEMA — added by aggregator).
            "v_net": self.v_net,
            "c_net": self.c_net,
        }


# ---------------------------------------------------------------------------
# Named scenario rows
# ---------------------------------------------------------------------------

#: NS_A — strongly in-the-money; TH+MTA-NICA dominates over V-C.
#: RC = max(150_000, 300_000, 0) = 300_000
_ROW_NS_A = RcMarginedRow(
    netting_set_id=NS_A_ID,
    counterparty_reference=CP_A_REF,
    is_legally_enforceable=True,
    is_margined=True,
    margin_threshold=250_000.0,
    minimum_transfer_amount=100_000.0,
    nica=50_000.0,
    v_net=2_000_000.0,
    c_net=1_850_000.0,
)

#: NS_B — V-C dominates over TH+MTA-NICA.
#: RC = max(1_100_000, 125_000, 0) = 1_100_000
_ROW_NS_B = RcMarginedRow(
    netting_set_id=NS_B_ID,
    counterparty_reference=CP_B_REF,
    is_legally_enforceable=True,
    is_margined=True,
    margin_threshold=100_000.0,
    minimum_transfer_amount=50_000.0,
    nica=25_000.0,
    v_net=1_500_000.0,
    c_net=400_000.0,
)

#: NS_C — both terms are negative; floor at zero applies.
#: RC = max(-500_000, -140_000, 0) = 0
_ROW_NS_C = RcMarginedRow(
    netting_set_id=NS_C_ID,
    counterparty_reference=CP_C_REF,
    is_legally_enforceable=True,
    is_margined=True,
    margin_threshold=50_000.0,
    minimum_transfer_amount=10_000.0,
    nica=200_000.0,
    v_net=-500_000.0,
    c_net=0.0,
)

#: NS_D — unmargined; rc_margined must be null (pass-through).
#: Margin parameters are null for unmargined netting sets per NETTING_SET_SCHEMA.
_ROW_NS_D = RcMarginedRow(
    netting_set_id=NS_D_ID,
    counterparty_reference=CP_D_REF,
    is_legally_enforceable=False,
    is_margined=False,
    margin_threshold=None,
    minimum_transfer_amount=None,
    nica=None,
    v_net=80.0,
    c_net=0.0,
)

_ALL_ROWS: list[RcMarginedRow] = [_ROW_NS_A, _ROW_NS_B, _ROW_NS_C, _ROW_NS_D]

# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

#: Full dtype map from NETTING_SET_SCHEMA — used to cast schema columns.
_NETTING_SET_DTYPES: dict[str, pl.DataType] = dtypes_of(NETTING_SET_SCHEMA)

#: Dtype map for the two upstream-derived columns (Float64 by convention).
_DERIVED_DTYPES: dict[str, pl.DataType] = {
    "v_net": pl.Float64,
    "c_net": pl.Float64,
}


def make_rc_margined_frame() -> pl.LazyFrame:
    """
    Build a four-row ``pl.LazyFrame`` for the P8.11 margined RC unit test.

    Columns include all fields from ``NETTING_SET_SCHEMA`` plus the
    upstream-derived ``v_net`` and ``c_net`` (Float64).  Schema is enforced
    via ``dtypes_of(NETTING_SET_SCHEMA)`` for schema columns and explicit
    Float64 for the two derived columns.

    The unmargined NS_D row has null ``margin_threshold``,
    ``minimum_transfer_amount``, and ``nica`` — matching the conservative
    NETTING_SET_SCHEMA defaults for unmargined netting sets.

    Returns:
        ``pl.LazyFrame`` with 4 rows and full schema coverage for
        ``compute_rc_margined``.
    """
    records = [row.to_dict() for row in _ALL_ROWS]
    schema = {**_NETTING_SET_DTYPES, **_DERIVED_DTYPES}
    return pl.DataFrame(records, schema=schema).lazy()
