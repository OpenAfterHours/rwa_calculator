"""
Declined guarantees on IRB off-balance-sheet legs beside a recognised one — the
portfolio that can tell a guarantee the IRB stage declines from one it applies.

Pipeline position:
    build_reporting_declined_guarantee_bundle() -> RawDataBundle
        -> PipelineOrchestrator -> AggregatedResultBundle -> COREPGenerator

Why it exists (P1.398). The CRM stage re-values the covered part of an F-IRB /
A-IRB leg at the Standardised Approach conversion factor as soon as its guarantor
routes to risk-weight substitution, and the IRB stage decides only afterwards
whether the guarantee is recognised. A DECLINED guarantee is not recognised, so the
exposure keeps the IRB exposure value of an unprotected exposure — CRR
Art. 166(8)-(10) with Art. 193(1)/(3), PS1/26 Art. 166A-166D with Art. 193(2A) —
but nothing reverted the swap, so the covered undrawn amount stayed on the SA
factor. No registered portfolio held a declined SA-routed guarantee on an IRB leg
with an off-balance-sheet amount (measured over every ``RUNS`` entry before this
portfolio existed: zero such rows, both regimes), so no gate could see it
(LESSONS B5).

Every obligor is a corporate above the SME ceiling with an internal PD of 0.3%,
one drawn loan under one committed facility, and one facility-level percentage
guarantee from an ECAI-rated corporate with no internal PD (so the guarantor
routes to SA substitution). A CQS 3 guarantor (100% CRR / 75% Basel 3.1) sits
above every obligor's IRB weight, so its guarantee is DECLINED in both regimes; a
CQS 1 guarantor (20%) sits below it, so its guarantee is RECOGNISED. Distinct
amounts per obligor keep each cell's contributor identifiable from its value.

    DG-FIRB — F-IRB commitment, declined. Moves under CRR (Art. 166(8)(d) 75%
              against the SA 50%); cannot move under Basel 3.1, where
              Art. 166C(1) makes the F-IRB factor the SA one.
    DG-AIRB — A-IRB revolving commitment with an own CCF of 80%, declined. Moves
              in BOTH regimes (Art. 166(8) own estimate / Art. 166D(1)(a)).
    DG-LC   — F-IRB short-term trade letter of credit booked medium-risk issued,
              declined. The RWA-REDUCING corner: Art. 166(8)(b) 20% against the
              swap's SA 50%.
    DG-KEPT — F-IRB commitment, RECOGNISED. The leg that must SURVIVE the fix
              (LESSONS B5's two-leg rule): its covered part stays on the SA factor.

Hand calculation — exposure value (drawn + CCF x undrawn, per leg; the covered
share of the undrawn amount is ``COVER``):

                     drawn    undrawn  cover  CRR own   CRR swapped   B31 own
    DG-FIRB        500,000    300,000   60%   725,000     680,000     650,000
    DG-AIRB        400,000    350,000   50%   680,000     627,500     680,000 (B31 swapped 627,500)
    DG-LC          300,000    250,000   40%   350,000     380,000     425,000
    DG-KEPT        600,000    400,000   70%   830,000 kept            800,000 kept

    CRR swapped = drawn + cover x undrawn x SA + (1 - cover) x undrawn x own.
    Basel 3.1 F-IRB own = the Art. 111 factor (Art. 166C(1)): 50% for the
    medium-risk commitment and for the medium-risk issued LC alike, so DG-FIRB
    and DG-LC cannot move there; only DG-AIRB (own CCF 80%) does.

Assembled IN MEMORY (as ``reporting_over_collateralised_portfolio`` is), so there
is no parquet to register in ``generate_all.py``. Registered in the supervisory
``RUNS`` matrix under both regimes with the IRB config and a prior frame.

References:
- CRR Art. 166(8)(b)/(d), 166(10), 193(1)/(3); PS1/26 Art. 166C(1), 166D(1),
  193(2A), 235(1)
- COREP Annex II / PS1/26 Annex II, C 08.01 / OF 08.01 col 0110 (exposure value)
  and cols 0070-0080 (substitution outflows / inflows)
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
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

CP_FIRB: str = "DG-CP-FIRB"
CP_AIRB: str = "DG-CP-AIRB"
CP_LC: str = "DG-CP-LC"
CP_KEPT: str = "DG-CP-KEPT"

#: The two guarantors: ECAI-rated corporates with no internal PD (SA-routed).
GTOR_DECLINED: str = "DG-GTOR-CQS3"
GTOR_RECOGNISED: str = "DG-GTOR-CQS1"

OBLIGORS: tuple[str, ...] = (CP_FIRB, CP_AIRB, CP_LC, CP_KEPT)

#: Per obligor: (approach, drawn, limit, cover, guarantor).
LEGS: dict[str, tuple[str, float, float, float, str]] = {
    CP_FIRB: ("foundation_irb", 500_000.0, 800_000.0, 0.60, GTOR_DECLINED),
    CP_AIRB: ("advanced_irb", 400_000.0, 750_000.0, 0.50, GTOR_DECLINED),
    CP_LC: ("foundation_irb", 300_000.0, 550_000.0, 0.40, GTOR_DECLINED),
    CP_KEPT: ("foundation_irb", 600_000.0, 1_000_000.0, 0.70, GTOR_RECOGNISED),
}

OBLIGOR_PD: float = 0.003
OWN_LGD: float = 0.45
OWN_CCF: float = 0.80

#: The obligors whose guarantee the IRB stage declines.
DECLINED: tuple[str, ...] = (CP_FIRB, CP_AIRB, CP_LC)

_MODEL_FIRB: str = "DG-MODEL-FIRB"
_MODEL_AIRB: str = "DG-MODEL-AIRB"
_VALUE_DATE: date = date(2020, 1, 1)
#: Short enough that the A-IRB obligor's Basel 3.1 weight (own LGD 45%) stays below
#: the CQS 3 guarantor's 75% at both Basel 3.1 dates, so its guarantee is declined;
#: beyond both reporting dates and their priors.
_MATURITY: date = date(2029, 12, 31)


def facility_reference(obligor: str) -> str:
    """The obligor's facility reference (its undrawn leg is ``<this>_UNDRAWN``)."""
    return obligor.replace("-CP-", "-FAC-")


def loan_reference(obligor: str) -> str:
    """The obligor's drawn loan reference."""
    return obligor.replace("-CP-", "-LN-")


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_declined_guarantee_bundle() -> RawDataBundle:
    """Assemble the portfolio as a sealed bundle.

    Run it through ``PipelineOrchestrator().run_with_data`` under either regime
    with ``PermissionMode.IRB``: each obligor's model permission fixes its
    approach (F-IRB or A-IRB) in both.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        facilities=_facilities(),
        facility_mappings=_facility_mappings(),
        ratings=_ratings(),
        model_permissions=_model_permissions(),
        guarantees=_guarantees(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """Four obligors and two guarantors, every one a large corporate."""
    rows: list[dict] = [
        {
            "counterparty_reference": ref,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 400_000_000.0,
        }
        for ref in (*OBLIGORS, GTOR_DECLINED, GTOR_RECOGNISED)
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """Internal PDs for the obligors; external ratings only for the guarantors."""
    obligors: list[dict] = [
        {
            "rating_reference": f"DG-RTG-{ref}",
            "counterparty_reference": ref,
            "rating_type": "internal",
            "pd": OBLIGOR_PD,
            "model_id": _MODEL_AIRB if LEGS[ref][0] == "advanced_irb" else _MODEL_FIRB,
            "rating_date": _VALUE_DATE,
        }
        for ref in OBLIGORS
    ]
    guarantors: list[dict] = [
        {
            "rating_reference": f"DG-RTG-{ref}",
            "counterparty_reference": ref,
            "rating_type": "external",
            "rating_agency": "S&P",
            "rating_value": value,
            "cqs": cqs,
            "rating_date": _VALUE_DATE,
        }
        for ref, value, cqs in ((GTOR_DECLINED, "BBB", 3), (GTOR_RECOGNISED, "AA", 1))
    ]
    return pl.DataFrame([*obligors, *guarantors], schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _model_permissions() -> pl.DataFrame:
    """One F-IRB and one A-IRB corporate model."""
    rows: list[dict] = [
        {"model_id": _MODEL_FIRB, "exposure_class": "corporate", "approach": "foundation_irb"},
        {"model_id": _MODEL_AIRB, "exposure_class": "corporate", "approach": "advanced_irb"},
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


def _loans() -> pl.DataFrame:
    """One drawn loan per obligor; the A-IRB one carries the firm's own LGD."""
    rows: list[dict] = [
        {
            "loan_reference": loan_reference(ref),
            "counterparty_reference": ref,
            "product_type": "term_loan",
            "drawn_amount": LEGS[ref][1],
            "interest": 0.0,
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "seniority": "senior",
            "lgd": OWN_LGD if LEGS[ref][0] == "advanced_irb" else None,
        }
        for ref in OBLIGORS
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _facilities() -> pl.DataFrame:
    """One committed facility per obligor, each emitting a ``_UNDRAWN`` leg."""

    def _row(ref: str) -> dict:
        approach, _, limit, _, _ = LEGS[ref]
        is_airb = approach == "advanced_irb"
        return {
            "facility_reference": facility_reference(ref),
            "counterparty_reference": ref,
            "product_type": "revolving_credit_facility" if is_airb else "term_loan",
            "limit": limit,
            "committed": True,
            "is_revolving": is_airb,
            "risk_type": "MR_ISSUED" if ref == CP_LC else "medium_risk",
            "is_short_term_trade_lc": ref == CP_LC,
            "ccf_modelled": OWN_CCF if is_airb else None,
            "lgd": OWN_LGD if is_airb else None,
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "seniority": "senior",
        }

    return pl.DataFrame(
        [_row(ref) for ref in OBLIGORS], schema_overrides=dtypes_of(FACILITY_SCHEMA)
    )


def _facility_mappings() -> pl.DataFrame:
    """Each loan under its facility, so the undrawn leg is limit minus drawn."""
    rows: list[dict] = [
        {
            "parent_facility_reference": facility_reference(ref),
            "child_reference": loan_reference(ref),
            "child_type": "loan",
        }
        for ref in OBLIGORS
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _guarantees() -> pl.DataFrame:
    """One facility-level percentage guarantee per obligor, maturing after the loan."""
    rows: list[dict] = [
        {
            "guarantee_reference": f"DG-GTEE-{ref}",
            "guarantee_type": "guarantee",
            "guarantor": LEGS[ref][4],
            "currency": "GBP",
            "maturity_date": date(2030, 12, 31),
            "percentage_covered": LEGS[ref][3],
            "beneficiary_type": "facility",
            "beneficiary_reference": facility_reference(ref),
            "protection_type": "guarantee",
            "includes_restructuring": True,
        }
        for ref in OBLIGORS
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(GUARANTEE_SCHEMA))
