"""
P1.232 — Art. 237(2)(a): the original-maturity >=1yr test binds only WHERE a
maturity mismatch exists, end-to-end.

Pipeline position:
    fixture-builder output -> test-writer -> engine
    (engine/crm/guarantees.py: _prepare_guarantees pre-filter removed; the
    <1y-original gate relocated into _apply_maturity_mismatch_to_guarantees)

Scenario (SA, both regimes; corporate CQS-1 guarantor = 20% RW under CRR Table 5
AND PS1/26 Table 6, unrated corporate borrower = 100% under both — every value is
regime-identical). Every guarantee carries original_maturity_years = 0.75 (< 1y):

    Borrower  CP_B232 : GB large corporate, UNRATED -> 100% own basis.
    Guarantor CP_G232 : GB large corporate, external CQS 1 -> 20% RW.

    | loan          | exp T | guar t | mismatch? | outcome (post-fix)          |
    |---------------|-------|--------|-----------|-----------------------------|
    | LN_BASELINE   | 6m    | (none) | -         | borrower basis, 1.00        |
    | LN_MATCHED    | 6m    | 6m     | NO (t==T) | RECOGNISED (guarantor 20%)  |
    | LN_OUTLIVES   | 6m    | 9m     | NO (t>T)  | RECOGNISED (guarantor 20%)  |
    | LN_MISMATCH   | 3y    | 6m     | YES       | ZEROED (Art. 237(2)(a))     |

Post-fix (EAD 1,000,000):
    RECOGNISED loans -> full coverage on the guarantor's 20% RW -> RWA = 200,000.
    ZEROED / baseline loans -> borrower 100% basis -> RWA = 1,000,000.

Pre-fix (bug): the unconditional pre-filter drops EVERY <1y-original guarantee
before any mismatch test, so LN_MATCHED and LN_OUTLIVES are discarded and revert
to the 1,000,000 borrower basis — an RWA over-statement for matched short-dated
(e.g. trade-finance) guarantees. LN_MISMATCH is 1,000,000 both pre- and post-fix
(dropped pre-fix; zeroed by the relocated mismatch-conditioned gate post-fix).

References:
    - CRR / PS1-26 Art. 237(2)(a) + Art. 237(2) chapeau ("where there is a
      maturity mismatch").
    - CRR Art. 239(3): maturity-mismatch scaling.
    - docs/plans/compliance-audit-crr-111-241-rectification.md §5 WS2, P1.232.
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

CP_B_REF = "CP_B232"  # unrated corporate borrower -> 100%
CP_G_REF = "CP_G232"  # external CQS-1 corporate guarantor -> 20%

LN_BASELINE = "LN_BASELINE"
LN_MATCHED = "LN_MATCHED"  # 6m guarantee on 6m exposure -> no mismatch -> recognised
LN_OUTLIVES = "LN_OUTLIVES"  # 9m guarantee on 6m exposure -> no mismatch -> recognised
LN_MISMATCH = "LN_MISMATCH"  # 6m guarantee on 3y exposure -> mismatch -> zeroed

DRAWN = 1_000_000.0
SHORT_ORIGINAL = 0.75  # every guarantee: original maturity < 1y
GUARANTOR_CQS = 1  # corporate CQS 1 -> 20% RW, both regimes

EXPECTED_RWA_BORROWER_BASIS = 1_000_000.0  # EAD x 100% (zeroed / baseline)
EXPECTED_RWA_RECOGNISED = 200_000.0  # EAD x 20% (guarantor CQS 1, full coverage)


def _loan(loan_ref: str, reporting_date: date, exp_days: int) -> dict:
    return {
        "loan_reference": loan_ref,
        "counterparty_reference": CP_B_REF,
        "currency": "GBP",
        "value_date": reporting_date - timedelta(days=30),
        "maturity_date": reporting_date + timedelta(days=exp_days),
        "drawn_amount": DRAWN,
        "interest": 0.0,
        "seniority": "senior",
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
        "original_maturity_years": SHORT_ORIGINAL,  # < 1y on every guarantee
    }


def build_p232_bundle(reporting_date: date) -> RawDataBundle:
    """Assemble the P1.232 RawDataBundle for a given reporting date."""
    counterparties = [
        {
            "counterparty_reference": CP_B_REF,
            "counterparty_name": "P1.232 Unrated Corporate Borrower",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 600_000_000.0,
            "total_assets": 500_000_000.0,
            "default_status": False,
            "apply_fi_scalar": False,
        },
        {
            "counterparty_reference": CP_G_REF,
            "counterparty_name": "P1.232 CQS-1 Corporate Guarantor",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 600_000_000.0,
            "total_assets": 500_000_000.0,
            "default_status": False,
            "apply_fi_scalar": False,
        },
    ]
    loans = [
        _loan(LN_BASELINE, reporting_date, 183),
        _loan(LN_MATCHED, reporting_date, 183),
        _loan(LN_OUTLIVES, reporting_date, 183),
        _loan(LN_MISMATCH, reporting_date, int(3 * 365.25)),
    ]
    guarantees = [
        _guarantee("GUAR_MATCHED", LN_MATCHED, reporting_date, 183),  # t == T
        _guarantee("GUAR_OUTLIVES", LN_OUTLIVES, reporting_date, 274),  # 9m > 6m
        _guarantee("GUAR_MISMATCH", LN_MISMATCH, reporting_date, 183),  # 6m << 3y
    ]
    ratings = [
        {
            "rating_reference": "RTG_G232",
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
