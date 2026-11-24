"""
Retail secured by COMMERCIAL immovable property — the A-IRB retail CRE sheets.

Pipeline position:
    build_reporting_retail_cre_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Why it exists (P1.324). Before it, no registered portfolio in either regime held a
single retail exposure secured only on commercial property, so:

- the Basel 3.1 OF 08.01 sheets 0018 / 0019 ("Retail – Secured by commercial
  immovable property", SME / non-SME, A-IRB; Annex II 3.3 items 4.3 / 4.4) were
  never emitted, and no published rule over them was ever evaluated;
- the three PS1/26 treatments that read RESIDENTIAL security — the
  Art. 154(4A)(b) 10% RWEA floor, the Art. 163(1)(b) 0.10% PD floor and the
  Art. 164(4)(a) flat 5% LGD floor — were applied to commercial-only security
  by class, and nothing in the estate could see it.

The classifier keeps these rows in ``retail_mortgage`` (R = 0.15 under Art. 154(3)
covers any immovable property, and the CRR Art. 164(4) 15% commercial bucket and
the CRE sheets need them there). Under Basel 3.1 they now take the (c) "all other
retail exposures" PD floor, no 10% floor, and the Art. 164(4)(c) LGD* blend.

Composition (every leg A-IRB retail, GB, 300,000 drawn, PD 0.04%, own LGD 3%):

    ref          | obligor              | security                 | B31 OF 08.01 sheet
    -------------|----------------------|--------------------------|-------------------
    LN_CRE       | natural person       | shop, 200,000            | 0019 (CRE non-SME)
    LN_CRE_SME   | SME managed as retail| shop, 200,000            | 0018 (CRE SME)
    LN_RRE       | natural person       | house, 200,000           | 0021 (RRE non-SME)

Two legs MOVE and one SURVIVES (LESSONS B5's two-leg shape). ``LN_RRE`` is the
live-cell control: its own PD and LGD sit below the residential floors, so its
modelled risk weight sits below the 10% floor and its column 0253 add-on is
POSITIVE before and after the change. The two CRE legs are the demonstration:
column 0253 is 0 on their sheets because Art. 154(4A)(b) does not reach them, and
their column 0260 RWEA is the higher LGD*-floored figure, not zero.

Each property is 200,000 against a 300,000 loan, so after the 40% immovable
property haircut of the Foundation Collateral Method 120,000 is recognised: 40%
cover. That is the PARTIALLY secured case Art. 164(4)(c) reads, and the only one
in which the LGD floor moves. A fully covered row would floor at the 10% LGDS
alone, and an own LGD above the floor would leave it inert.

References:
- PS1/26 Art. 147(5B)/(5C), 154(3), 154(4A)(b), 163(1)(b)/(c), 164(4)(a)-(c)
- CRR Art. 154(3), 163(1), 164(4)
- PS1/26 Annex II (reporting instructions) 3.3 items 4.1-4.4, column 0253
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: Must match ``create_full_irb_model_permissions`` or no row routes IRB.
_MODEL_ID: str = "TEST_FULL_IRB"

CP_CRE: str = "RCRE-CP-CRE"
CP_CRE_SME: str = "RCRE-CP-CRE-SME"
CP_RRE: str = "RCRE-CP-RRE"

LN_CRE: str = "RCRE-LN-CRE"
LN_CRE_SME: str = "RCRE-LN-CRE-SME"
LN_RRE: str = "RCRE-LN-RRE"

#: Drawn amount of every leg (EAD; no undrawn headroom, no CCF).
DRAWN: float = 300_000.0
#: Market value of every property: 200,000 against 300,000 -> 40% recognised
#: cover after the 40% immovable-property haircut.
PROPERTY_VALUE: float = 200_000.0
#: Own-estimate PD: above CRR's flat 0.03% floor (so CRR keeps it) and below both
#: Basel 3.1 retail floors (0.05% / 0.10%), so the Basel 3.1 floor IS the result.
PD_RETAIL: float = 0.0004
#: Own-estimate LGD below every Basel 3.1 retail LGD floor.
LGD_RETAIL: float = 0.03
#: Revenue of the SME obligor: an SME (Art. 501 / PS1/26 Art. 147(5)), small
#: enough to be managed as retail.
SME_REVENUE: float = 10_000_000.0

#: Every leg's expected exposure class (the class is NOT what P1.324 changes).
RETAIL_CRE_EXPECTED_CLASS: dict[str, str] = {
    LN_CRE: "retail_mortgage",
    LN_CRE_SME: "retail_mortgage",
    LN_RRE: "retail_mortgage",
}

#: Every leg's expected Basel 3.1 OF 08.01 sheet key (``irb_sheets.B31_IRB_SHEETS``).
RETAIL_CRE_EXPECTED_B31_SHEET: dict[str, str] = {
    LN_CRE: "retail_commercial_re_non_sme_airb",
    LN_CRE_SME: "retail_commercial_re_sme_airb",
    LN_RRE: "retail_residential_re_non_sme_airb",
}

_VALUE_DATE: date = date(2020, 1, 1)
_MATURITY: date = date(2031, 12, 31)  # > both reporting dates (CRR 2025, B31 2027)


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_retail_cre_bundle() -> RawDataBundle:
    """Assemble the retail CRE portfolio as a sealed bundle.

    Sealed against the loader edge contracts by ``make_raw_bundle``, so it is
    shape-identical to a parquet-loaded production bundle. Run it through
    ``PipelineOrchestrator().run_with_data`` under either regime with
    ``PermissionMode.IRB``.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        facility_mappings=pl.DataFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        ratings=_ratings(),
        model_permissions=create_full_irb_model_permissions(),
        collateral=_collateral(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """Two natural persons and one SME managed as retail, all GB, none defaulted."""
    rows: list[dict] = [
        {
            "counterparty_reference": CP_CRE,
            "entity_type": "individual",
            "country_code": "GB",
            "is_natural_person": True,
            "is_managed_as_retail": True,
        },
        {
            "counterparty_reference": CP_CRE_SME,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": SME_REVENUE,
            "total_assets": SME_REVENUE,
            "is_managed_as_retail": True,
        },
        {
            "counterparty_reference": CP_RRE,
            "entity_type": "individual",
            "country_code": "GB",
            "is_natural_person": True,
            "is_managed_as_retail": True,
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """One internal PD per obligor — an internal PD plus a permission routes IRB."""
    rows = [_internal(ref) for ref in (CP_CRE, CP_CRE_SME, CP_RRE)]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans() -> pl.DataFrame:
    """One drawn term loan per obligor, each with an own-estimate LGD (A-IRB)."""
    rows = [
        _loan(LN_CRE, CP_CRE),
        _loan(LN_CRE_SME, CP_CRE_SME),
        _loan(LN_RRE, CP_RRE),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _collateral() -> pl.DataFrame:
    """One eligible property per loan, pledged directly; two shops and one house.

    ``is_eligible_irb_collateral=True`` attests the Art. 199(2) conditions, so the
    property is RECOGNISED and the Art. 231 waterfall allocates it — which is what
    puts the commercial-only legs on the Art. 164(4)(c) LGD* blend rather than the
    flat unsecured floor. The currency is stated so it is not an unknown-currency
    mismatch (CRM023).
    """
    return pl.DataFrame(
        [
            _property("RCRE-COLL-SHOP", LN_CRE, "commercial"),
            _property("RCRE-COLL-SHOP-SME", LN_CRE_SME, "commercial"),
            _property("RCRE-COLL-HOUSE", LN_RRE, "residential"),
        ]
    )


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _loan(loan_reference: str, counterparty_reference: str) -> dict:
    """A drawn senior term loan carrying an own LGD estimate (routes A-IRB)."""
    return {
        "loan_reference": loan_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "term_loan",
        "drawn_amount": DRAWN,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
        "lgd": LGD_RETAIL,
        "has_sufficient_collateral_data": True,
    }


def _property(collateral_reference: str, loan_reference: str, property_type: str) -> dict:
    """A recognised real-estate pledge of ``PROPERTY_VALUE`` on one loan."""
    return {
        "collateral_reference": collateral_reference,
        "collateral_type": "real_estate",
        "currency": "GBP",
        "is_eligible_irb_collateral": True,
        "property_type": property_type,
        "market_value": PROPERTY_VALUE,
        "property_ltv": DRAWN / PROPERTY_VALUE,
        "beneficiary_type": "loan",
        "beneficiary_reference": loan_reference,
    }


def _internal(counterparty_reference: str) -> dict:
    """Internal model rating row (PD + model_id — the IRB routing pair)."""
    return {
        "rating_reference": f"RCRE-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "pd": PD_RETAIL,
        "model_id": _MODEL_ID,
        "rating_date": _VALUE_DATE,
    }
