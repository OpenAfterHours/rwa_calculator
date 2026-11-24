"""
Off-balance-sheet CRM substitution portfolio — the pre-conversion basis of the flows.

Pipeline position:
    build_reporting_offbs_substitution_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator

Why this portfolio: COREP books a guarantee's substitution flows — C 07.00 cols
0050/0060/0090/0100, C 08.01/02 cols 0040/0050/0070/0080 — as "the covered part of
the Original Exposure pre-conversion factors" (CRR Annex II pp.88/100; PS1/26 Annex
II pp.84/104, which adds "separate each exposure, prior to the application of
conversion factors, into a covered part and an uncovered part"). The engine's covered
carrier ``guaranteed_portion`` is the covered EXPOSURE VALUE, i.e. AFTER the
conversion factor, so the two differ exactly when the covered part includes an
undrawn or issued amount. No registered portfolio held such a leg (every guaranteed
leg in ``RUNS`` was a drawn loan), so the flows were booked post-CCF beside a pre-CCF
col 0010/0020 and nothing could see it (LESSONS B5).

Three facilities and a control loan, one per route, each a round-number shape with
no 0% weight on either side, so a cell on the wrong basis is identifiable from its
value alone:

    route   obligor      guarantor                 limit      drawn    cover
    IRBSA   F-IRB corp   CQS 1 corporate (SA)      1,000,000  600,000  70%
    SASA    SA corp      CQS 1 corporate (SA)        900,000  500,000  60%
    IRBIRB  F-IRB corp   IRB institution           1,100,000  300,000  80%
    CTRL    SA corp      CQS 1 corporate (SA)        (loan)   450,000  40%

IRBSA is the cross-approach case (an IRB leg whose guarantor routes to SA risk-weight
substitution, ``engine/crm/guarantees.py::_apply_cross_approach_ccf``): its covered
part is converted at the SA factor, not the obligor's F-IRB one, which under CRR
(F-IRB 75% for this commitment, SA 50%) is a second difference from the uncovered
part. SASA and IRBIRB are the same basis question with no factor swap. Every
facility is a ``risk_type="MR"`` committed revolving line, 50% under SA in both
regimes, so the covered undrawn part is visible at half its nominal on a post-CCF
basis.

CTRL is the leg that must NOT move (B5's two-leg pattern): a drawn loan, guaranteed
and part-collateralised by cash. Its covered part has no conversion factor to undo,
so its flows equal its covered exposure value before and after any change to the
basis; a "share of the gross" implementation would instead also deduct the
collateralised part, which this leg's col 0130 already reports.

The facility guarantees are PERCENTAGE covers so each child leg (the drawn loan and
the synthetic ``<facility>_UNDRAWN`` leg) is covered at the same fraction and the
hand-calculation is one multiplication per leg.

References:
- CRR Annex II C 07.00 cols 0090-0100, C 08.01 cols 0070-0080 (pre-CCF flows)
- PRA PS1/26 Annex II OF 07.00 cols 0050-0100, OF 08.01 cols 0040-0080
- CRR Art. 235 / 236 (covered and uncovered parts), Art. 111 (SA conversion factors)
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    GUARANTEE_SCHEMA,
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

#: Above every SME ceiling, so no supporting factor touches a cell under test.
_LARGE_CORPORATE_REVENUE: float = 600_000_000.0

#: Obligor and guarantor PDs. The IRB institution guarantor's PD is well below the
#: obligor's, so parameter substitution is beneficial and the leg migrates.
PD_OBLIGOR: float = 0.0200
PD_IRB_GUARANTOR: float = 0.0010

#: The SA guarantors' credit quality step (20% corporate weight in both regimes).
CQS_SA_GUARANTOR: int = 1

ROUTE_IRBSA: str = "IRBSA"
ROUTE_SASA: str = "SASA"
ROUTE_IRBIRB: str = "IRBIRB"

#: route -> (facility limit, drawn amount, fraction covered)
FACILITY_ROUTES: dict[str, tuple[float, float, float]] = {
    ROUTE_IRBSA: (1_000_000.0, 600_000.0, 0.70),
    ROUTE_SASA: (900_000.0, 500_000.0, 0.60),
    ROUTE_IRBIRB: (1_100_000.0, 300_000.0, 0.80),
}

#: The control loan: drawn amount, fraction covered, cash collateral pledged.
CTRL_DRAWN: float = 450_000.0
CTRL_COVER: float = 0.40
CTRL_CASH: float = 100_000.0

#: The SA conversion factor of every facility here (``risk_type="MR"``), both regimes.
SA_CCF_MR: float = 0.50

_VALUE_DATE: date = date(2020, 1, 1)
_MATURITY: date = date(2031, 12, 31)  # beyond both reporting dates
_GUARANTEE_MATURITY: date = date(2032, 12, 31)  # outlives the exposure: no mismatch


def obligor(route: str) -> str:
    """The obligor counterparty of one route."""
    return f"OBS-OB-{route}"


def guarantor(route: str) -> str:
    """The guarantor counterparty of one route."""
    return f"OBS-GT-{route}"


def facility(route: str) -> str:
    """The committed facility of one facility route."""
    return f"OBS-FAC-{route}"


def loan(route: str) -> str:
    """The drawn loan of one route (a facility child, or the control loan)."""
    return f"OBS-LN-{route}"


ROUTE_CTRL: str = "CTRL"


def covered_pre_ccf(route: str) -> tuple[float, float]:
    """(on-balance, off-balance) covered part of one facility route, PRE-CCF."""
    limit, drawn, cover = FACILITY_ROUTES[route]
    return drawn * cover, (limit - drawn) * cover


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_offbs_substitution_bundle() -> RawDataBundle:
    """Assemble the off-balance-sheet substitution portfolio as a sealed bundle.

    Run it through ``PipelineOrchestrator().run_with_data`` under either regime with
    ``PermissionMode.IRB``: the F-IRB obligors and the institution guarantor carry an
    internal PD and the matching model permission; the SA obligors and guarantors
    carry none, so they stay standardised.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        ratings=_ratings(),
        loans=_loans(),
        facilities=_facilities(),
        facility_mappings=_facility_mappings(),
        guarantees=_guarantees(),
        collateral=_collateral(),
        model_permissions=create_full_irb_model_permissions(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """One obligor and one guarantor per route, all GB large corporates but one."""
    rows: list[dict] = []
    for route in (*FACILITY_ROUTES, ROUTE_CTRL):
        rows.append(_corporate(obligor(route)))
        if route == ROUTE_IRBIRB:
            rows.append(
                {
                    "counterparty_reference": guarantor(route),
                    "entity_type": "institution",
                    "country_code": "GB",
                }
            )
        else:
            rows.append(_corporate(guarantor(route)))
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """Internal PDs route IRBSA / IRBIRB obligors and the institution IRB; ECAI
    ratings keep the corporate guarantors standardised. SASA's and CTRL's obligors
    are unrated, so they stay SA at the unrated corporate weight."""
    rows: list[dict] = [
        _internal(obligor(ROUTE_IRBSA), PD_OBLIGOR),
        _internal(obligor(ROUTE_IRBIRB), PD_OBLIGOR),
        _internal(guarantor(ROUTE_IRBIRB), PD_IRB_GUARANTOR),
        _external(guarantor(ROUTE_IRBSA)),
        _external(guarantor(ROUTE_SASA)),
        _external(guarantor(ROUTE_CTRL)),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans() -> pl.DataFrame:
    """The three facility draws and the control loan."""
    rows: list[dict] = [
        _loan(loan(route), obligor(route), drawn)
        for route, (_, drawn, _) in FACILITY_ROUTES.items()
    ]
    rows.append(_loan(loan(ROUTE_CTRL), obligor(ROUTE_CTRL), CTRL_DRAWN))
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _facilities() -> pl.DataFrame:
    """Three committed medium-risk revolving lines (SA 50% in both regimes)."""
    rows: list[dict] = [
        {
            "facility_reference": facility(route),
            "counterparty_reference": obligor(route),
            "product_type": "revolving_credit_facility",
            "limit": limit,
            "risk_type": "MR",
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "committed": True,
            "is_revolving": True,
        }
        for route, (limit, _, _) in FACILITY_ROUTES.items()
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_SCHEMA))


def _facility_mappings() -> pl.DataFrame:
    """Each draw sits under its facility, so the undrawn leg is limit minus drawn."""
    rows: list[dict] = [
        {
            "parent_facility_reference": facility(route),
            "child_reference": loan(route),
            "child_type": "loan",
        }
        for route in FACILITY_ROUTES
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _guarantees() -> pl.DataFrame:
    """A percentage facility guarantee per facility route, and one on the control loan."""
    rows: list[dict] = [
        _guarantee(route, "facility", facility(route), cover)
        for route, (_, _, cover) in FACILITY_ROUTES.items()
    ]
    rows.append(_guarantee(ROUTE_CTRL, "loan", loan(ROUTE_CTRL), CTRL_COVER))
    return pl.DataFrame(rows, schema_overrides=dtypes_of(GUARANTEE_SCHEMA))


def _collateral() -> pl.DataFrame:
    """Cash pledged against the control loan only."""
    return pl.DataFrame(
        [
            {
                "collateral_reference": "OBS-COLL-CTRL",
                "collateral_type": "cash",
                "is_eligible_financial_collateral": True,
                "market_value": CTRL_CASH,
                "currency": "GBP",
                "beneficiary_type": "loan",
                "beneficiary_reference": loan(ROUTE_CTRL),
            }
        ],
        schema_overrides=dtypes_of(COLLATERAL_SCHEMA),
    )


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _corporate(counterparty_reference: str) -> dict:
    return {
        "counterparty_reference": counterparty_reference,
        "entity_type": "corporate",
        "country_code": "GB",
        "annual_revenue": _LARGE_CORPORATE_REVENUE,
    }


def _internal(counterparty_reference: str, pd: float) -> dict:
    return {
        "rating_reference": f"OBS-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "pd": pd,
        "model_id": _MODEL_ID,
        "rating_date": _VALUE_DATE,
    }


def _external(counterparty_reference: str) -> dict:
    return {
        "rating_reference": f"OBS-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "external",
        "rating_agency": "S&P",
        "cqs": CQS_SA_GUARANTOR,
        "rating_date": _VALUE_DATE,
        "is_solicited": True,
    }


def _loan(loan_reference: str, counterparty_reference: str, drawn_amount: float) -> dict:
    return {
        "loan_reference": loan_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "term_loan",
        "drawn_amount": drawn_amount,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
        "has_sufficient_collateral_data": False,
    }


def _guarantee(route: str, beneficiary_type: str, beneficiary: str, cover: float) -> dict:
    return {
        "guarantee_reference": f"OBS-G-{route}",
        "guarantor": guarantor(route),
        "currency": "GBP",
        "maturity_date": _GUARANTEE_MATURITY,
        "percentage_covered": cover,
        "beneficiary_type": beneficiary_type,
        "beneficiary_reference": beneficiary,
        "protection_type": "guarantee",
        "includes_restructuring": True,
        "original_maturity_years": 12.0,
        "guarantor_seniority": "senior",
        "is_unilaterally_cancellable": False,
        "is_unilaterally_changeable": False,
    }
