"""
P1.231 — Art. 237(1)/(2)(b) guarantee maturity-eligibility gates, end-to-end.

Pipeline position:
    fixture-builder output -> test-writer -> engine
    (engine/crm/guarantees.py::_apply_maturity_mismatch_to_guarantees)

Scenario (SA, both regimes; corporate CQS-1 guarantor = 20% RW under CRR Table 5
AND PS1/26 Table 6, unrated corporate borrower = 100% under both — so every
expected value is regime-identical):

    Borrower  CP_B231 : GB large corporate, UNRATED -> 100% own basis.
    Guarantor CP_G231 : GB large corporate, external CQS 1 -> 20% RW.

    Six GBP 1,000,000 drawn loans, each (except the baseline) 100%-guaranteed by
    CP_G231. The guarantees differ only in the exposure/guarantee maturities and
    the exposure's one-day IRB maturity floor:

    | loan             | exp T | guar t | 1-day floor | outcome (post-fix)      |
    |------------------|-------|--------|-------------|-------------------------|
    | LN_BASELINE      | 3y    | (none) | -           | borrower basis, 1.00    |
    | LN_1DF_MISMATCH  | 3y    | 1y     | TRUE        | ZEROED (Art. 237(2)(b)) |
    | LN_1DF_CONTROL   | 3y    | 1y     | False       | recognised (scaled)     |
    | LN_237_1_MASKED  | 80d   | 40d    | False       | ZEROED (Art. 237(1))    |
    | LN_237_1_OUTLIVES| 55d   | 74d    | False       | recognised (t>=T)       |
    | LN_237_1_T02_T5  | 5y    | 74d    | False       | ZEROED (sub-3m protn)   |

Post-fix expectations (EAD = 1,000,000, borrower RW = 100%):
    ZEROED loans revert to the borrower's own basis -> total RWA = 1,000,000.
    Recognised loans place (part of) the EAD on the guarantor's 20% RW ->
        total RWA < 1,000,000.

Pre-fix (bug): LN_1DF_MISMATCH is merely scaled (partial benefit) and
LN_237_1_MASKED keeps FULL coverage (both raw residuals < 0.25 floor to 0.25,
masking the mismatch), so both wrongly show a guarantee benefit (RWA < 1,000,000)
— an RWA understatement.

References:
    - CRR / PS1-26 Art. 237(1): <3-month-and-shorter protection ineligibility.
    - CRR Art. 162(3) / Art. 237(2)(b): one-day-floor exposures + any mismatch.
    - CRR Art. 239(3): maturity-mismatch scaling (unchanged).
    - docs/plans/compliance-audit-crr-111-241-rectification.md §5 WS2, P1.231.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    GUARANTEE_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

CP_B_REF = "CP_B231"  # unrated corporate borrower -> 100% own basis
CP_G_REF = "CP_G231"  # external CQS-1 corporate guarantor -> 20% RW

LN_BASELINE = "LN_BASELINE"
LN_1DF_MISMATCH = "LN_1DF_MISMATCH"  # 1-day floor + mismatch -> zeroed (237(2)(b))
LN_1DF_CONTROL = "LN_1DF_CONTROL"  # no floor + mismatch -> recognised (scaled)
LN_237_1_MASKED = "LN_237_1_MASKED"  # t,T both <0.25, t<T -> zeroed (237(1))
LN_237_1_OUTLIVES = "LN_237_1_OUTLIVES"  # t>=T -> recognised
LN_237_1_T02_T5 = "LN_237_1_T02_T5"  # t~0.2, T=5y -> zeroed (sub-3m protection)
LN_NULL_MATURITY = "LN_NULL_MATURITY"  # null exposure maturity + 1-day floor -> zeroed

DRAWN = 1_000_000.0
BORROWER_RW = 1.0  # unrated corporate, both regimes
GUARANTOR_CQS = 1  # corporate CQS 1 -> 20% RW, both regimes

# EAD x borrower RW: the "no guarantee benefit" (zeroed / baseline) RWA.
EXPECTED_RWA_BORROWER_BASIS = DRAWN * BORROWER_RW  # 1,000,000


def _loan(
    loan_ref: str, reporting_date: date, exp_days: int | None, *, one_day_floor: bool
) -> dict:
    return {
        "loan_reference": loan_ref,
        "counterparty_reference": CP_B_REF,
        "currency": "GBP",
        "value_date": reporting_date - timedelta(days=30),
        # exp_days=None => null maturity_date (treated as a 5y exposure by the
        # maturity-mismatch step's conservative null-T default).
        "maturity_date": (
            reporting_date + timedelta(days=exp_days) if exp_days is not None else None
        ),
        "drawn_amount": DRAWN,
        "interest": 0.0,
        "seniority": "senior",
        "has_one_day_maturity_floor": one_day_floor,
    }


def _guarantee(guar_ref: str, beneficiary: str, reporting_date: date, guar_days: int) -> dict:
    return {
        "guarantee_reference": guar_ref,
        "guarantee_type": "corporate_guarantee",
        "guarantor": CP_G_REF,
        "currency": "GBP",
        "maturity_date": reporting_date + timedelta(days=guar_days),
        "amount_covered": DRAWN,
        "percentage_covered": None,
        "beneficiary_type": "loan",
        "beneficiary_reference": beneficiary,
        "protection_type": "guarantee",
        # original_maturity_years left null -> defaults >= 1y, so the upstream
        # Art. 237(2)(a) pre-filter never drops these seasoned short-residual
        # guarantees; the residual (from maturity_date) drives the mismatch.
    }


def build_p231_bundle(reporting_date: date) -> RawDataBundle:
    """Assemble the P1.231 RawDataBundle for a given reporting date."""
    counterparties = [
        {
            "counterparty_reference": CP_B_REF,
            "counterparty_name": "P1.231 Unrated Corporate Borrower",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 600_000_000.0,
            "total_assets": 500_000_000.0,
            "default_status": False,
            "apply_fi_scalar": False,
        },
        {
            "counterparty_reference": CP_G_REF,
            "counterparty_name": "P1.231 CQS-1 Corporate Guarantor",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 600_000_000.0,
            "total_assets": 500_000_000.0,
            "default_status": False,
            "apply_fi_scalar": False,
        },
    ]
    loans = [
        _loan(LN_BASELINE, reporting_date, int(3 * 365.25), one_day_floor=False),
        _loan(LN_1DF_MISMATCH, reporting_date, int(3 * 365.25), one_day_floor=True),
        _loan(LN_1DF_CONTROL, reporting_date, int(3 * 365.25), one_day_floor=False),
        _loan(LN_237_1_MASKED, reporting_date, 80, one_day_floor=False),
        _loan(LN_237_1_OUTLIVES, reporting_date, 55, one_day_floor=False),
        _loan(LN_237_1_T02_T5, reporting_date, int(5 * 365.25), one_day_floor=False),
        _loan(LN_NULL_MATURITY, reporting_date, None, one_day_floor=True),
    ]
    guarantees = [
        _guarantee("GUAR_1DF_MISMATCH", LN_1DF_MISMATCH, reporting_date, 365),
        _guarantee("GUAR_1DF_CONTROL", LN_1DF_CONTROL, reporting_date, 365),
        _guarantee("GUAR_237_1_MASKED", LN_237_1_MASKED, reporting_date, 40),
        _guarantee("GUAR_237_1_OUTLIVES", LN_237_1_OUTLIVES, reporting_date, 74),
        _guarantee("GUAR_237_1_T02_T5", LN_237_1_T02_T5, reporting_date, 74),
        _guarantee("GUAR_NULL_MATURITY", LN_NULL_MATURITY, reporting_date, 365),
    ]
    ratings = [
        {
            "rating_reference": "RTG_G231",
            "counterparty_reference": CP_G_REF,
            "rating_type": "external",
            "rating_agency": "S&P",
            "rating_value": "AAA",
            "cqs": GUARANTOR_CQS,
            "pd": None,
            "rating_date": reporting_date - timedelta(days=180),
            "is_solicited": True,
            "model_id": None,
        }
    ]
    return make_raw_bundle(
        facilities=pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.DataFrame(loans, schema=dtypes_of(LOAN_SCHEMA)).lazy(),
        counterparties=pl.DataFrame(counterparties, schema=dtypes_of(COUNTERPARTY_SCHEMA)).lazy(),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        guarantees=pl.DataFrame(guarantees, schema=dtypes_of(GUARANTEE_SCHEMA)).lazy(),
        ratings=pl.DataFrame(ratings, schema=dtypes_of(RATINGS_SCHEMA)).lazy(),
    )
