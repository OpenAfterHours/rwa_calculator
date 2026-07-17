"""
P1.234 — Art. 197(1)(h) securitisation-position financial collateral, end-to-end.

Pipeline position:
    fixture-builder output -> test-writer -> engine
    (engine/crm/haircuts.py securitisation branch + eligibility gate;
    rulebook/packs/{crr,b31}.py Art. 224 Table 1 securitisation haircut rows)

Scenario (SA; unrated corporate borrower = 100% RW both regimes). Five GBP
1,000,000 drawn loans, each collateralised by a single GBP 500,000 debt security
with collateral_type="bond", issuer_type="securitisation", issuer_cqs=1, residual
maturity 4.0y. They differ only in the Art. 197(1)(h) eligibility inputs:

    | loan          | resec | position RW | eligible? | Art. 224 haircut |
    |---------------|-------|-------------|-----------|------------------|
    | LN_BASELINE   | (no collateral)     | -         | -                |
    | LN_ELIGIBLE   | False | 0.20        | YES       | 8% (CQS1 securit)|
    | LN_RESEC      | TRUE  | 0.20        | NO        | zeroed           |
    | LN_HIGH_RW    | False | 1.50        | NO (>100%)| zeroed           |
    | LN_NULL_RW    | False | null        | NO (conserv)| zeroed         |

The securitisation CQS-1 haircut is 8% at a 4y residual under BOTH regimes
(CRR 1_5y band = 8%; B31 3_5y band = 8%), so every expected value is
regime-identical.

Post-fix (EAD 1,000,000; MV 500,000; unrated-corp 100% RW):
    LN_ELIGIBLE: E* = 1,000,000 - 500,000 x (1 - 0.08) = 540,000 -> RWA 540,000.
    LN_RESEC / LN_HIGH_RW / LN_NULL_RW / LN_BASELINE: collateral gives NO benefit
        -> E* = 1,000,000 -> RWA 1,000,000.

Pre-fix (bug): securitisation collateral has no branch, so it falls to the flat
Art. 230(2) "other_physical" 40% haircut with NO Art. 197 gate. EVERY loan then
gets E* = 1,000,000 - 500,000 x (1 - 0.40) = 700,000 -> RWA 700,000 — the eligible
one over-stated (should be 540,000) and the three ineligible ones under-stated
(should be 1,000,000, a capital understatement on resecuritisation / >100%-RW /
unknown-RW securitisation collateral).

References:
    - CRR / PS1-26 Art. 197(1)(h): non-resecuritisation securitisation positions
      with RW <= 100% are eligible financial collateral.
    - CRR / PS1-26 Art. 224 Table 1: securitisation haircut column (2x corporate).
    - docs/plans/compliance-audit-crr-111-241-rectification.md §5 WS3, P1.234.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

CP_B_REF = "CP_B234"  # unrated corporate borrower -> 100%

LN_BASELINE = "LN_BASELINE"
LN_ELIGIBLE = "LN_ELIGIBLE"  # non-resec, RW 0.20 -> eligible, 8% haircut
LN_RESEC = "LN_RESEC"  # resecuritisation -> ineligible
LN_HIGH_RW = "LN_HIGH_RW"  # position RW 1.50 (>100%) -> ineligible
LN_NULL_RW = "LN_NULL_RW"  # position RW null -> ineligible (conservative)

DRAWN = 1_000_000.0
COLL_MV = 500_000.0
RESIDUAL_YEARS = 4.0  # CQS1 securitisation haircut = 8% under both regimes at 4y

EXPECTED_RWA_ELIGIBLE = 540_000.0  # 1,000,000 - 500,000 x (1 - 0.08)
EXPECTED_RWA_NO_BENEFIT = 1_000_000.0  # ineligible / baseline -> full borrower basis


def _loan(loan_ref: str, reporting_date: date) -> dict:
    return {
        "loan_reference": loan_ref,
        "counterparty_reference": CP_B_REF,
        "currency": "GBP",
        "value_date": reporting_date - timedelta(days=30),
        # Short (6m) exposure so the 4y securitisation collateral OUTLIVES it —
        # no Art. 238 maturity-mismatch adjustment, isolating the Art. 224 haircut.
        "maturity_date": reporting_date + timedelta(days=183),
        "drawn_amount": DRAWN,
        "interest": 0.0,
        "seniority": "senior",
    }


def _collateral(
    coll_ref: str,
    beneficiary: str,
    reporting_date: date,
    *,
    is_resecuritisation: bool,
    position_rw: float | None,
) -> dict:
    return {
        "collateral_reference": coll_ref,
        "collateral_type": "bond",
        "issuer_type": "securitisation",
        "issuer_cqs": 1,
        "currency": "GBP",
        "market_value": COLL_MV,
        # 10-day liquidation period => no Art. 224(2) sqrt-scaling; the base
        # Art. 224 Table 1 securitisation haircut applies directly.
        "liquidation_period_days": 10,
        "residual_maturity_years": RESIDUAL_YEARS,
        "maturity_date": reporting_date + timedelta(days=int(RESIDUAL_YEARS * 365.25)),
        "beneficiary_type": "loan",
        "beneficiary_reference": beneficiary,
        "is_eligible_financial_collateral": True,
        "is_resecuritisation": is_resecuritisation,
        "securitisation_position_risk_weight": position_rw,
    }


def build_p234_bundle(reporting_date: date) -> RawDataBundle:
    """Assemble the P1.234 RawDataBundle for a given reporting date."""
    counterparties = [
        {
            "counterparty_reference": CP_B_REF,
            "counterparty_name": "P1.234 Unrated Corporate Borrower",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 600_000_000.0,
            "total_assets": 500_000_000.0,
            "default_status": False,
            "apply_fi_scalar": False,
        }
    ]
    loans = [
        _loan(LN_BASELINE, reporting_date),
        _loan(LN_ELIGIBLE, reporting_date),
        _loan(LN_RESEC, reporting_date),
        _loan(LN_HIGH_RW, reporting_date),
        _loan(LN_NULL_RW, reporting_date),
    ]
    collateral = [
        _collateral(
            "COLL_ELIGIBLE",
            LN_ELIGIBLE,
            reporting_date,
            is_resecuritisation=False,
            position_rw=0.20,
        ),
        _collateral(
            "COLL_RESEC", LN_RESEC, reporting_date, is_resecuritisation=True, position_rw=0.20
        ),
        _collateral(
            "COLL_HIGH_RW", LN_HIGH_RW, reporting_date, is_resecuritisation=False, position_rw=1.50
        ),
        _collateral(
            "COLL_NULL_RW", LN_NULL_RW, reporting_date, is_resecuritisation=False, position_rw=None
        ),
    ]
    return make_raw_bundle(
        facilities=pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.DataFrame(loans, schema=dtypes_of(LOAN_SCHEMA)).lazy(),
        counterparties=pl.DataFrame(counterparties, schema=dtypes_of(COUNTERPARTY_SCHEMA)).lazy(),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        collateral=pl.DataFrame(collateral, schema=dtypes_of(COLLATERAL_SCHEMA)).lazy(),
    )
