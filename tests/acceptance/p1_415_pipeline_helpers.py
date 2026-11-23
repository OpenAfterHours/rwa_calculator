"""
Shared pipeline plumbing for the P1.415 Foundation Collateral Method prior-claim scenarios.

Pipeline position:
    (P1.235 parquet fixtures + a prior charge) -> build_prior_claim_bundle
        -> PipelineOrchestrator.run_with_data

Key responsibilities:
- Rebuild the P1.235 *attested* real-estate F-IRB scenario (senior non-FSE corporate,
  10m drawn, 10m residential property pledged at facility level, attested
  IRB-eligible) with ``prior_charge_ltv`` set on the property row, so the prior
  claim is the only lever that differs from the P1.235 control. Optionally re-spell
  the property's ``collateral_type`` (a real-estate synonym) or give it a maturity
  date before the loan's (an Art. 237-239 maturity mismatch).
- Build the P1.248 Basel 3.1 corporate A-IRB property case (own LGD 5%, collateral
  modelled and attested) with a prior charge, so the PS1/26 Art. 161(5)(b) LGD input
  floor — LGD* on the Foundation Collateral Method — can be measured.
- Run each end to end and return the loan's result row plus the run's error codes.

The collateral frame is re-sealed through ``make_raw_bundle`` rather than mutated on a
sealed bundle (a transformed frame loses its edge brand). A plain importable module, not
a conftest, so both ``tests/acceptance/crr/`` and ``tests/acceptance/basel31/`` can use
it.

References:
    - CRR Art. 229(1): property valued net of any prior claims.
    - PS1/26 Art. 229(1)(b): value reduced by P / (1 - HC - Hfx).
    - PS1/26 Art. 161(5)(b): A-IRB LGD input floor = LGD* (Foundation Collateral Method).
    - IMPLEMENTATION_PLAN.md: P1.415.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.p1_190_pipeline_helpers import find_loan_rows
from tests.fixtures.p1_235.p1_235 import SCENARIOS
from tests.fixtures.raw_bundle import make_raw_bundle

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "p1_235"

#: Reporting dates. CRR: the P1.235 date (M = 3.0y on the 3-year loan). Basel 3.1: the
#: first half-year of the regime, so the same loan still has 2.0y to run (M = 2.0y).
CRR_REPORTING_DATE = date(2026, 6, 30)
B31_REPORTING_DATE = date(2027, 6, 30)

#: The P1.248 A-IRB case: reported 2027-01-01, maturing 2030-01-01 (M = 3.0y).
AIRB_REPORTING_DATE = date(2027, 1, 1)
AIRB_MATURITY_DATE = date(2030, 1, 1)
AIRB_LOAN_REF = "P1415-AIRB-L"
AIRB_EAD = 10_000_000.0
AIRB_PROPERTY_MV = 10_000_000.0
AIRB_OWN_LGD = 0.05  # below every candidate floor, so lgd_floored is the floor
AIRB_PD = 0.02
_AIRB_MODEL_ID = "P1415-CORP-AIRB"


@dataclass(frozen=True)
class PriorClaimRun:
    """The loan's single F-IRB result row and the run's error codes."""

    row: dict
    error_codes: frozenset[str]


def run_prior_claim(
    regime: str,
    prior_charge_ltv: float | None,
    *,
    collateral_type: str | None = None,
    collateral_maturity_date: date | None = None,
) -> PriorClaimRun:
    """Run the attested-RE F-IRB scenario with ``prior_charge_ltv`` on the property.

    Args:
        regime: ``"crr"`` or ``"b31"`` — selects the P1.235 attested scenario and config.
        prior_charge_ltv: Claims ranking ahead of the institution, as a share of the
            property's market value (``None`` leaves the input null).
        collateral_type: Re-spells the property's ``collateral_type`` (``None`` keeps
            the fixture's ``"real_estate"``).
        collateral_maturity_date: Gives the property a maturity date (``None`` keeps
            the fixture's null — no maturity mismatch).

    Returns:
        The loan's result row and the set of error codes the run raised.
    """
    scenario = SCENARIOS[f"{regime}_attested_re"]
    bundle = build_prior_claim_bundle(
        scenario.label,
        prior_charge_ltv,
        collateral_type=collateral_type,
        collateral_maturity_date=collateral_maturity_date,
    )
    if regime == "crr":
        config = CalculationConfig.crr(
            reporting_date=CRR_REPORTING_DATE, permission_mode=PermissionMode.IRB
        )
    else:
        config = CalculationConfig.basel_3_1(
            reporting_date=B31_REPORTING_DATE, permission_mode=PermissionMode.IRB
        )
    result = PipelineOrchestrator().run_with_data(bundle, config)
    rows = find_loan_rows(result, scenario.loan_ref)
    assert len(rows) == 1, f"P1.415 {regime}: expected one F-IRB row, got {len(rows)}"
    assert rows[0]["approach"] == "foundation_irb", "the scenario must route to F-IRB"
    return PriorClaimRun(rows[0], frozenset(e.code for e in result.errors))


def build_prior_claim_bundle(
    scenario_label: str,
    prior_charge_ltv: float | None,
    *,
    collateral_type: str | None = None,
    collateral_maturity_date: date | None = None,
) -> RawDataBundle:
    """Build the P1.235 bundle for ``scenario_label`` with a prior charge on the property."""
    scenario = SCENARIOS[scenario_label]
    collateral = pl.scan_parquet(_FIXTURES_DIR / f"collateral_{scenario_label}.parquet")
    collateral = collateral.with_columns(
        pl.lit(prior_charge_ltv, dtype=pl.Float64).alias("prior_charge_ltv")
    )
    if collateral_type is not None:
        collateral = collateral.with_columns(pl.lit(collateral_type).alias("collateral_type"))
    if collateral_maturity_date is not None:
        collateral = collateral.with_columns(
            pl.lit(collateral_maturity_date, dtype=pl.Date).alias("maturity_date")
        )
    return make_raw_bundle(
        facilities=pl.scan_parquet(_FIXTURES_DIR / f"facility_{scenario_label}.parquet"),
        loans=pl.scan_parquet(_FIXTURES_DIR / f"loan_{scenario_label}.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / f"counterparty_{scenario_label}.parquet"),
        collateral=collateral,
        ratings=pl.scan_parquet(_FIXTURES_DIR / f"rating_{scenario_label}.parquet"),
        model_permissions=pl.scan_parquet(
            _FIXTURES_DIR / f"model_permission_{scenario_label}.parquet"
        ),
        facility_mappings=pl.LazyFrame(
            {
                "parent_facility_reference": [scenario.fac_ref],
                "child_reference": [scenario.loan_ref],
                "child_type": ["loan"],
            },
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            },
        ),
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
    )


def run_airb_prior_claim(prior_charge_ltv: float | None) -> PriorClaimRun:
    """Run the P1.248 Basel 3.1 A-IRB property case with a prior charge on the property.

    One senior corporate loan (revenue 100m: CORPORATE, A-IRB permitted), EAD 10m, own
    LGD 5%, PD 2%, M 3.0y, secured by a 10m commercial property that is attested
    (``is_eligible_irb_collateral``) and modelled (``is_airb_model_collateral``), with
    ``has_sufficient_collateral_data`` on the loan — the PS1/26 Art. 161(5)(b) limb,
    whose floor is LGD* computed with the Foundation Collateral Method.

    Args:
        prior_charge_ltv: Claims ranking ahead of the institution, as a share of the
            property's market value (``None`` leaves the input null).

    Returns:
        The loan's A-IRB result row and the set of error codes the run raised.
    """
    result = PipelineOrchestrator().run_with_data(
        build_airb_prior_claim_bundle(prior_charge_ltv),
        CalculationConfig.basel_3_1(
            reporting_date=AIRB_REPORTING_DATE, permission_mode=PermissionMode.IRB
        ),
    )
    assert result.irb_results is not None, "the A-IRB case must produce IRB results"
    rows = result.irb_results.filter(pl.col("exposure_reference") == AIRB_LOAN_REF).collect()
    assert rows.height == 1, f"P1.415 A-IRB: expected one row, got {rows.height}"
    row = rows.to_dicts()[0]
    assert row["is_airb"] is True, f"the case must route to A-IRB, got {row['approach']}"
    return PriorClaimRun(row, frozenset(e.code for e in result.errors))


def build_airb_prior_claim_bundle(prior_charge_ltv: float | None) -> RawDataBundle:
    """Build the single-loan P1.248 ``L-RE`` A-IRB bundle with a prior charge."""
    counterparty = {
        "counterparty_reference": "P1415-AIRB-CP",
        "counterparty_name": "P1.415 A-IRB Corporate",
        "entity_type": "corporate",
        "country_code": "GB",
        "default_status": False,
        "is_financial_sector_entity": False,
        "apply_fi_scalar": False,
        "annual_revenue": 100_000_000.0,
    }
    facility = {
        "facility_reference": "P1415-AIRB-F",
        "counterparty_reference": "P1415-AIRB-CP",
        "currency": "GBP",
        "value_date": AIRB_REPORTING_DATE,
        "maturity_date": AIRB_MATURITY_DATE,
        "limit": AIRB_EAD,
        "committed": True,
        "seniority": "senior",
        "risk_type": "FR",
    }
    loan = {
        "loan_reference": AIRB_LOAN_REF,
        "counterparty_reference": "P1415-AIRB-CP",
        "currency": "GBP",
        "value_date": AIRB_REPORTING_DATE,
        "maturity_date": AIRB_MATURITY_DATE,
        "drawn_amount": AIRB_EAD,
        "interest": 0.0,
        "seniority": "senior",
        "lgd": AIRB_OWN_LGD,
        "has_sufficient_collateral_data": True,
    }
    rating = {
        "rating_reference": "P1415-AIRB-RTG",
        "counterparty_reference": "P1415-AIRB-CP",
        "rating_type": "internal",
        "pd": AIRB_PD,
        "model_id": _AIRB_MODEL_ID,
        "rating_date": AIRB_REPORTING_DATE,
    }
    collateral = {
        "collateral_reference": "P1415-AIRB-C",
        "collateral_type": "real_estate",
        "currency": "GBP",
        "market_value": AIRB_PROPERTY_MV,
        "beneficiary_type": "loan",
        "beneficiary_reference": AIRB_LOAN_REF,
        "is_eligible_financial_collateral": False,
        "is_eligible_irb_collateral": True,
        "is_airb_model_collateral": True,
        "property_type": "commercial",
        "original_maturity_years": 10.0,
        "prior_charge_ltv": prior_charge_ltv,
    }
    permission = {
        "model_id": _AIRB_MODEL_ID,
        "exposure_class": "corporate",
        "approach": "advanced_irb",
        "country_codes": None,
        "excluded_book_codes": None,
    }
    return make_raw_bundle(
        facilities=pl.DataFrame([facility], schema=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.DataFrame([loan], schema=dtypes_of(LOAN_SCHEMA)),
        counterparties=pl.DataFrame([counterparty], schema=dtypes_of(COUNTERPARTY_SCHEMA)),
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        collateral=pl.DataFrame([collateral], schema=dtypes_of(COLLATERAL_SCHEMA)),
        ratings=pl.DataFrame([rating], schema=dtypes_of(RATINGS_SCHEMA)),
        model_permissions=pl.DataFrame([permission], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA)),
    )
