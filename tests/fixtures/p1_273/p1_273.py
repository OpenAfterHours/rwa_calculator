"""
P1.273 fixtures: CRR Art. 199(7)/211 lease exposures treated as collateralised.

Where the Art. 211 conditions are met, an exposure arising from a leasing
transaction "may be treated in the same manner as loans collateralised by the
type of property leased" (CRR Art. 199(7); PRA PS1/26 Art. 199(7), both retaining
Art. 211). The leased asset is supplied as an ordinary non-financial collateral
row (``other_physical`` for equipment/plant leases) pledged to the lease exposure,
and the lessor attests the lease-specific Art. 211 conditions via
``is_lease_collateral_attested`` — an INDEPENDENT F-IRB recognition route that does
not require the general ``is_eligible_irb_collateral`` flag.

Each scenario is a £10m senior corporate F-IRB lease exposure secured by a £10m
leased asset (``other_physical``, so a 40% Art. 230(2) FCM haircut applies);
only the Art. 211 attestation differs:

    <regime>_lease_attested    — Art. 211 attested -> leased asset recognised,
                                 secured LGD substitutes and RWA falls.
    <regime>_lease_unattested  — no attestation (null) -> not recognised, the FCM
                                 gate zeroes it and LGD reverts to the senior
                                 unsecured supervisory value (the conservative
                                 pre-P1.273 lessor treatment).

CRR: attested LGD* = 0.428571 (Art. 230(2) haircut 40%, OC=1.4×, LGDS other_physical 40%,
LGDU 45%); unattested = LGDU 0.45. B31: attested LGD* = 0.31; unattested = LGDU
0.40 (Art. 161(1)(aa) non-FSE).

The bundle is assembled IN MEMORY (mirroring P1.271) — no parquet dependency, so
the acceptance tests are reproducible on a fresh checkout without a fixture-
generation step.

References:
    - CRR Art. 199(7): lease exposures treated as collateralised per Art. 211.
    - CRR Art. 211: requirements for treating lease exposures as collateralised.
    - CRR Art. 230 / Art. 230(2): F-IRB Foundation Collateral Method — OC ratios
      and the non-financial-collateral FCM haircut (other-physical 40%).
    - CRR Art. 161(1)(a) / PS1/26 Art. 161(1)(aa): senior unsecured LGDU.
    - IMPLEMENTATION_PLAN.md: P1.273.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl
from dateutil.relativedelta import relativedelta
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

DRAWN_AMOUNT: float = 10_000_000.00
COLLATERAL_MV: float = 10_000_000.00
LEASE_TERM_YEARS: float = 7.0
PD: float = 0.02

# Expected F-IRB LGD outcomes (post-floor lgd_floored).
CRR_ATTESTED_LGD: float = 0.428571  # Art. 230(2) haircut 40%, OC=1.4×, LGDS 40% / LGDU 45%
CRR_UNATTESTED_LGD: float = 0.45  # FCM gate zeroes ES -> LGDU (Art. 161(1)(a))
B31_ATTESTED_LGD: float = 0.31  # B31 FCM continuous formula, LGDU 40%
B31_UNATTESTED_LGD: float = 0.40  # FCM gate zeroes ES -> LGDU (Art. 161(1)(aa))


@dataclass(frozen=True)
class Scenario:
    """One P1.273 acceptance scenario."""

    label: str
    is_lease_collateral_attested: bool | None
    expected_lgd: float

    @property
    def cp_ref(self) -> str:
        return f"P1273-CP-{self.label}"

    @property
    def loan_ref(self) -> str:
        return f"P1273-L-{self.label}"

    @property
    def coll_ref(self) -> str:
        return f"P1273-C-{self.label}"

    @property
    def model_id(self) -> str:
        return f"P1273-CORP-FIRB-{self.label}"


SCENARIOS: dict[str, Scenario] = {
    "crr_lease_attested": Scenario("crr_lease_attested", True, CRR_ATTESTED_LGD),
    "crr_lease_unattested": Scenario("crr_lease_unattested", None, CRR_UNATTESTED_LGD),
    "b31_lease_attested": Scenario("b31_lease_attested", True, B31_ATTESTED_LGD),
    "b31_lease_unattested": Scenario("b31_lease_unattested", None, B31_UNATTESTED_LGD),
}


def _counterparty(s: Scenario) -> dict:
    return {
        "counterparty_reference": s.cp_ref,
        "counterparty_name": f"P1.273 F-IRB Lessor ({s.label})",
        "entity_type": "corporate",
        "country_code": "GB",
        "default_status": False,
        "is_financial_sector_entity": False,
        "apply_fi_scalar": False,
    }


def _loan(s: Scenario, reporting_date: date) -> dict:
    return {
        "loan_reference": s.loan_ref,
        "counterparty_reference": s.cp_ref,
        "currency": "GBP",
        "value_date": reporting_date,
        "maturity_date": reporting_date + relativedelta(years=3),
        "drawn_amount": DRAWN_AMOUNT,
        "interest": 0.0,
        "seniority": "senior",
    }


def _collateral(s: Scenario) -> dict:
    """£10m leased asset (other_physical) pledged to the lease exposure.

    is_eligible_irb_collateral is deliberately False: recognition of an attested
    row comes SOLELY from the Art. 211 lease attestation, proving the independent
    route. original_maturity_years = the lease term (a lease intrinsically has one).
    """
    return {
        "collateral_reference": s.coll_ref,
        "collateral_type": "other_physical",
        "currency": "GBP",
        "market_value": COLLATERAL_MV,
        "beneficiary_type": "loan",
        "beneficiary_reference": s.loan_ref,
        "is_eligible_financial_collateral": False,
        "is_eligible_irb_collateral": False,
        "is_lease_collateral_attested": s.is_lease_collateral_attested,
        "original_maturity_years": LEASE_TERM_YEARS,
    }


def _rating(s: Scenario, reporting_date: date) -> dict:
    return {
        "rating_reference": f"RTG-P1273-{s.label}",
        "counterparty_reference": s.cp_ref,
        "rating_type": "internal",
        "pd": PD,
        "model_id": s.model_id,
        "rating_date": reporting_date,
    }


def _model_permission(s: Scenario) -> dict:
    return {
        "model_id": s.model_id,
        "exposure_class": "corporate",
        "approach": "foundation_irb",
        "country_codes": None,
        "excluded_book_codes": None,
    }


def build_p1_273_bundle(scenario_labels: list[str], reporting_date: date) -> RawDataBundle:
    """Assemble an in-memory RawDataBundle for the named P1.273 scenarios."""
    scenarios = [SCENARIOS[label] for label in scenario_labels]
    counterparties = pl.DataFrame(
        [_counterparty(s) for s in scenarios], schema=dtypes_of(COUNTERPARTY_SCHEMA)
    )
    loans = pl.DataFrame(
        [_loan(s, reporting_date) for s in scenarios], schema=dtypes_of(LOAN_SCHEMA)
    )
    collateral = pl.DataFrame(
        [_collateral(s) for s in scenarios], schema=dtypes_of(COLLATERAL_SCHEMA)
    )
    ratings = pl.DataFrame(
        [_rating(s, reporting_date) for s in scenarios], schema=dtypes_of(RATINGS_SCHEMA)
    )
    model_permissions = pl.DataFrame(
        [_model_permission(s) for s in scenarios], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA)
    )
    return make_raw_bundle(
        counterparties=counterparties,
        loans=loans,
        collateral=collateral,
        ratings=ratings,
        model_permissions=model_permissions,
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
    )
