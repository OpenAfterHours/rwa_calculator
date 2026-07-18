"""
P1.229 — Art. 235(3): the 0% domestic-CGCB extension requires the exposure to be
BOTH denominated AND *funded* in the guarantor's domestic currency.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (engine/eu_sovereign.build_domestic_cgcb_guarantor_expr + funding_currency_expr;
    consumed by engine/sa/rw_adjustments.py, engine/crm/guarantees.py,
    engine/irb/guarantee.py)

Scenario (identical rows exercised under both CRR and Basel 3.1 — Art. 235(3)
and the Art. 114(4)/(7) 0% extension read the same in both regimes; the
guarantor's SA CQS-3 sovereign risk weight is 50% in both packs):

    Borrower  CP_P229_B   : GB corporate, external CQS 5 -> 150% own basis.
    Guarantor CP_P229_SOV : DE sovereign (central govt), external CQS 3 ->
                            50% CGCB risk weight (cgcb_risk_weights[CQS3]).

    Three EUR-denominated GBP-reporting loans, each 100%-guaranteed by the DE
    sovereign in EUR (= DE's domestic currency, so the DENOMINATION limb of
    Art. 114(4)/(7) passes on every loan). They differ only in funding currency:

    | loan               | funding_currency | funded-in-domestic? | guaranteed RW |
    |--------------------|------------------|---------------------|---------------|
    | LN_P229_MISMATCH   | "USD"            | NO  (USD != EUR)    | 0.50 (post)   |
    | LN_P229_MATCHED    | "EUR"            | YES (EUR == EUR)    | 0.00          |
    | LN_P229_NULL       | null             | permissive fallback | 0.00          |
                                              (null -> denomination EUR == EUR)

Defect under test (pre-fix): the engine tests only guarantor-country vs
guarantee-currency (the denomination limb), so ALL THREE loans wrongly receive
the 0% extension on the guaranteed portion. The USD-funded loan is the headline
under-statement: a sovereign CQS-3 covered part weighted at 0% instead of 50%.

Post-fix (Art. 235(3) funding limb ANDed in):
    LN_P229_MISMATCH guaranteed portion -> 0.50 (funding USD != domestic EUR).
    LN_P229_MATCHED  guaranteed portion -> 0.00 (funded in EUR — unchanged).
    LN_P229_NULL     guaranteed portion -> 0.00 (null funding is PERMISSIVE:
        falls back to the EUR denomination, which matches — preserves the
        pre-existing dataset's 0% treatment; mirrors the Art. 237(2)(a) null
        fallback / P1.10 precedent).

Hand-calculation (EAD reported in GBP; risk weight is currency-invariant):
    LN_P229_MISMATCH: EAD 1,000,000 EUR, guaranteed portion RW 0.50.
    LN_P229_MATCHED / LN_P229_NULL: guaranteed portion RW 0.00 -> RWA 0.

References:
    - CRR Art. 114(4)/(7) / PS1/26 Art. 114(4)/(7): 0% RW for a member state
      CGCB denominated AND funded in that state's domestic currency.
    - CRR Art. 235(3) / PS1/26 Art. 235(3): the 0% extension to a centrally-
      guaranteed exposure carries the same "denominated and funded" condition.
    - src/rwa_calc/engine/eu_sovereign.py (build_domestic_cgcb_guarantor_expr,
      funding_currency_expr).
    - docs/plans/compliance-audit-crr-111-241-rectification.md §5 WS2, P1.229.
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    FX_RATES_SCHEMA,
    GUARANTEE_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

CP_B_REF = "CP_P229_B"  # GB corporate borrower, external CQS 5 -> 150% own basis
CP_SOV_REF = "CP_P229_SOV"  # DE sovereign guarantor, external CQS 3 -> 50% CGCB RW

LOAN_MISMATCH_REF = "LN_P229_MISMATCH"  # funding_currency USD -> funding limb fails
LOAN_MATCHED_REF = "LN_P229_MATCHED"  # funding_currency EUR -> funding limb passes
LOAN_NULL_REF = "LN_P229_NULL"  # funding_currency null -> permissive denomination fallback

GUARANTEE_MISMATCH_REF = "GUAR_P229_MISMATCH"
GUARANTEE_MATCHED_REF = "GUAR_P229_MATCHED"
GUARANTEE_NULL_REF = "GUAR_P229_NULL"

VALUE_DATE = date(2024, 1, 1)
MATURITY_DATE = date(2032, 1, 1)  # 8y; guarantee maturity matches -> no Art. 239(3) mismatch

DRAWN_AMOUNT = 1_000_000.0  # EUR, 100% guaranteed

CQS_BORROWER = 5  # CP_P229_B external rating -> corporate 150% (both regimes)
CQS_SOVEREIGN = 3  # CP_P229_SOV external rating -> CGCB 50% (both regimes)

LOAN_CURRENCY = "EUR"  # denomination = DE domestic currency (denomination limb passes)
GUARANTEE_CURRENCY = "EUR"  # guarantee currency = DE domestic currency

# Expected guaranteed-portion risk weights (identical under CRR and Basel 3.1).
EXPECTED_RW_MISMATCH_POSTFIX = 0.50  # sovereign CQS 3 — 0% extension denied
EXPECTED_RW_MISMATCH_PREFIX = 0.00  # bug: 0% granted despite USD funding
EXPECTED_RW_MATCHED = 0.00  # funded in EUR — extension legitimately applies
EXPECTED_RW_NULL = 0.00  # null funding permissive -> denomination EUR match


# ---------------------------------------------------------------------------
# DataFrame factories
# ---------------------------------------------------------------------------


def create_p229_counterparties() -> pl.DataFrame:
    """Return the borrower + DE-sovereign-guarantor counterparties."""
    rows = [
        {
            "counterparty_reference": CP_B_REF,
            "counterparty_name": "P1.229 GB Corporate Borrower (external CQS 5)",
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 600_000_000.0,
            "total_assets": 500_000_000.0,
            "default_status": False,
            "apply_fi_scalar": False,
        },
        {
            "counterparty_reference": CP_SOV_REF,
            "counterparty_name": "P1.229 DE Sovereign Guarantor (external CQS 3)",
            "entity_type": "sovereign",
            "country_code": "DE",
            "annual_revenue": 0.0,
            "total_assets": 0.0,
            "default_status": False,
            "apply_fi_scalar": False,
        },
    ]
    return pl.DataFrame(rows, schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p229_loans() -> pl.DataFrame:
    """Return the three EUR loans differing only in funding_currency."""
    base = {
        "counterparty_reference": CP_B_REF,
        "currency": LOAN_CURRENCY,
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
        "drawn_amount": DRAWN_AMOUNT,
        "interest": 0.0,
        "seniority": "senior",
    }
    rows = [
        {**base, "loan_reference": LOAN_MISMATCH_REF, "funding_currency": "USD"},
        {**base, "loan_reference": LOAN_MATCHED_REF, "funding_currency": "EUR"},
        {**base, "loan_reference": LOAN_NULL_REF, "funding_currency": None},
    ]
    return pl.DataFrame(rows, schema=dtypes_of(LOAN_SCHEMA))


def create_p229_ratings() -> pl.DataFrame:
    """Return external ratings: borrower CQS 5, sovereign guarantor CQS 3."""
    rows = [
        {
            "rating_reference": "RTG_P229_B",
            "counterparty_reference": CP_B_REF,
            "rating_type": "external",
            "rating_agency": "S&P",
            "rating_value": "B",
            "cqs": CQS_BORROWER,
            "pd": None,
            "rating_date": VALUE_DATE,
            "is_solicited": True,
            "model_id": None,
        },
        {
            "rating_reference": "RTG_P229_SOV",
            "counterparty_reference": CP_SOV_REF,
            "rating_type": "external",
            "rating_agency": "S&P",
            "rating_value": "A",
            "cqs": CQS_SOVEREIGN,
            "pd": None,
            "rating_date": VALUE_DATE,
            "is_solicited": True,
            "model_id": None,
        },
    ]
    return pl.DataFrame(rows, schema=dtypes_of(RATINGS_SCHEMA))


def create_p229_guarantees() -> pl.DataFrame:
    """Return one 100%-coverage EUR sovereign guarantee per loan."""
    base = {
        "guarantee_type": "sovereign_guarantee",
        "guarantor": CP_SOV_REF,
        "currency": GUARANTEE_CURRENCY,
        "maturity_date": MATURITY_DATE,
        "amount_covered": DRAWN_AMOUNT,
        "percentage_covered": None,
        "beneficiary_type": "loan",
        "protection_type": "guarantee",
        "original_maturity_years": 8.0,
    }
    rows = [
        {
            **base,
            "guarantee_reference": GUARANTEE_MISMATCH_REF,
            "beneficiary_reference": LOAN_MISMATCH_REF,
        },
        {
            **base,
            "guarantee_reference": GUARANTEE_MATCHED_REF,
            "beneficiary_reference": LOAN_MATCHED_REF,
        },
        {
            **base,
            "guarantee_reference": GUARANTEE_NULL_REF,
            "beneficiary_reference": LOAN_NULL_REF,
        },
    ]
    return pl.DataFrame(rows, schema=dtypes_of(GUARANTEE_SCHEMA))


def create_p229_fx_rates() -> pl.DataFrame:
    """FX rates to the GBP reporting base (EUR/USD amounts convert; USD is a
    funding label only, but a rate is supplied defensively)."""
    rows = [
        {"currency_from": "EUR", "currency_to": "GBP", "rate": 0.86},
        {"currency_from": "USD", "currency_to": "GBP", "rate": 0.78},
        {"currency_from": "GBP", "currency_to": "GBP", "rate": 1.0},
    ]
    return pl.DataFrame(rows, schema=dtypes_of(FX_RATES_SCHEMA))


def build_p229_bundle() -> RawDataBundle:
    """Assemble the P1.229 RawDataBundle (no facilities — loan-scoped)."""
    return make_raw_bundle(
        facilities=pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        loans=create_p229_loans().lazy(),
        counterparties=create_p229_counterparties().lazy(),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        ratings=create_p229_ratings().lazy(),
        guarantees=create_p229_guarantees().lazy(),
        fx_rates=create_p229_fx_rates().lazy(),
    )
