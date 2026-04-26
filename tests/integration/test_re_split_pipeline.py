"""
Integration tests: end-to-end pipeline with the RE loan-splitter active.

Verifies that a property-collateralised non-RE exposure flows through:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
        -> RealEstateSplitter -> SACalculator -> Aggregator

and produces the expected secured + residual rows under both CRR and
Basel 3.1 configs.

References:
- CRR Art. 125: RRE 35% on portion up to 80% LTV.
- PRA PS1/26 Art. 124F: B3.1 RRE loan-splitting (cap 55% less prior charges).
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator

_REPORTING_DATE = date(2026, 12, 31)
_VALUE_DATE = date(2024, 1, 1)
_MATURITY_DATE = date(2029, 12, 31)


def _build_corporate_with_residential_collateral_bundle() -> RawDataBundle:
    """Corporate borrower (CP1), £1m loan (LOAN1), £1m residential property collateral.

    The exposure is unrated (CQS null), so the residual gets the corporate
    unrated 100% RW. The secured row gets the regulator-specific RRE RW
    (35% under CRR, 20% under B3.1).
    """
    fac_map = pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        }
    )
    lend_map = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )
    return RawDataBundle(
        counterparties=pl.LazyFrame(
            {
                "counterparty_reference": ["CP1"],
                "counterparty_name": ["Test Corp"],
                "entity_type": ["corporate"],
                "country_code": ["GB"],
                "annual_revenue": [200_000_000.0],
                "total_assets": [None],
                "default_status": [False],
                "sector_code": [None],
                "apply_fi_scalar": [None],
                "is_managed_as_retail": [False],
                "is_natural_person": [False],
                "is_social_housing": [False],
                "is_financial_sector_entity": [False],
                "scra_grade": [None],
                "is_investment_grade": [None],
                "is_ccp_client_cleared": [False],
                "borrower_income_currency": [None],
                "sovereign_cqs": [None],
                "local_currency": [None],
                "institution_cqs": [None],
            }
        ),
        facilities=pl.LazyFrame(
            schema={
                "facility_reference": pl.String,
                "product_type": pl.String,
                "book_code": pl.String,
                "counterparty_reference": pl.String,
                "value_date": pl.Date,
                "maturity_date": pl.Date,
                "currency": pl.String,
                "limit": pl.Float64,
                "committed": pl.Boolean,
                "lgd": pl.Float64,
                "lgd_unsecured": pl.Float64,
                "has_sufficient_collateral_data": pl.Boolean,
                "beel": pl.Float64,
                "is_revolving": pl.Boolean,
                "is_qrre_transactor": pl.Boolean,
                "seniority": pl.String,
                "risk_type": pl.String,
                "underlying_risk_type": pl.String,
                "ccf_modelled": pl.Float64,
                "ead_modelled": pl.Float64,
                "is_short_term_trade_lc": pl.Boolean,
                "is_payroll_loan": pl.Boolean,
                "is_buy_to_let": pl.Boolean,
                "has_one_day_maturity_floor": pl.Boolean,
                "facility_termination_date": pl.Date,
            }
        ),
        loans=pl.LazyFrame(
            {
                "loan_reference": ["LOAN1"],
                "product_type": ["term_loan"],
                "book_code": ["BANK"],
                "counterparty_reference": ["CP1"],
                "value_date": [_VALUE_DATE],
                "maturity_date": [_MATURITY_DATE],
                "currency": ["GBP"],
                "drawn_amount": [1_000_000.0],
                "interest": [0.0],
                "lgd": [0.45],
                "lgd_unsecured": [0.45],
                "has_sufficient_collateral_data": [True],
                "beel": [None],
                "seniority": ["senior"],
                "is_payroll_loan": [False],
                "is_buy_to_let": [False],
                "has_one_day_maturity_floor": [False],
                "has_netting_agreement": [False],
                "netting_facility_reference": [None],
                "due_diligence_performed": [None],
                "due_diligence_override_rw": [None],
            }
        ),
        facility_mappings=fac_map,
        lending_mappings=lend_map,
        collateral=pl.LazyFrame(
            {
                "collateral_reference": ["RRE_COLL_1"],
                "collateral_type": ["real_estate"],
                "currency": ["GBP"],
                "maturity_date": [None],
                "market_value": [1_000_000.0],
                "nominal_value": [1_000_000.0],
                "pledge_percentage": [None],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["LOAN1"],
                "issuer_cqs": [None],
                "issuer_type": [None],
                "residual_maturity_years": [None],
                "original_maturity_years": [None],
                "is_eligible_financial_collateral": [False],
                "is_eligible_irb_collateral": [True],
                "is_main_index": [None],
                "valuation_date": [_REPORTING_DATE],
                "valuation_type": ["market"],
                "property_type": ["residential"],
                "property_ltv": [1.0],
                "is_income_producing": [False],
                "is_adc": [False],
                "is_presold": [False],
                "is_qualifying_re": [True],
                "prior_charge_ltv": [0.0],
                "liquidation_period_days": [None],
                "qualifies_for_zero_haircut": [False],
                "insurer_risk_weight": [None],
                "credit_event_reduction": [0.0],
                "rental_to_interest_ratio": [None],
            }
        ),
    )


def _run(config: CalculationConfig) -> pl.DataFrame:
    bundle = _build_corporate_with_residential_collateral_bundle()
    result = PipelineOrchestrator().run_with_data(bundle, config)
    assert result.results is not None
    df = result.results.collect()
    assert isinstance(df, pl.DataFrame)
    return df


# ---------------------------------------------------------------------------
# CRR end-to-end
# ---------------------------------------------------------------------------


def test_crr_corporate_with_rre_splits_into_two_rows() -> None:
    """Corporate £1m / property £1m / CRR → secured £800k @ 35%, residual £200k @ 100%."""
    config = CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    df = _run(config)

    children = df.filter(pl.col("exposure_reference").str.contains("LOAN1"))
    assert children.height == 2
    rows = {r["re_split_role"]: r for r in children.to_dicts()}

    secured = rows["secured"]
    residual = rows["residual"]

    assert secured["exposure_class"] == "residential_mortgage"
    assert secured["ead_final"] == pytest.approx(800_000.0, rel=1e-6)
    assert secured["risk_weight"] == pytest.approx(0.35, rel=1e-6)

    assert residual["exposure_class"] == "corporate"
    assert residual["ead_final"] == pytest.approx(200_000.0, rel=1e-6)
    assert residual["risk_weight"] == pytest.approx(1.0, rel=1e-6)

    # Sum of children EAD reconciles to the parent.
    assert (secured["ead_final"] + residual["ead_final"]) == pytest.approx(1_000_000.0)


# ---------------------------------------------------------------------------
# Basel 3.1 end-to-end
# ---------------------------------------------------------------------------


def test_b31_corporate_with_rre_splits_into_two_rows() -> None:
    """Corporate £1m / property £1m / B3.1 → secured £550k @ 20%, residual £450k @ corporate RW.

    Basel 3.1 unrated corporate RW under PRA PS1/26 Art. 122 = 100%
    (no IG assessment elected in this fixture).
    """
    config = CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    df = _run(config)

    children = df.filter(pl.col("exposure_reference").str.contains("LOAN1"))
    assert children.height == 2
    rows = {r["re_split_role"]: r for r in children.to_dicts()}

    secured = rows["secured"]
    residual = rows["residual"]

    assert secured["exposure_class"] == "residential_mortgage"
    assert secured["ead_final"] == pytest.approx(550_000.0, rel=1e-6)
    # b31_residential_rw_expr returns 20% when secured_share = 1 (LTV ≤ 0.55).
    assert secured["risk_weight"] == pytest.approx(0.20, rel=1e-6)

    assert residual["exposure_class"] == "corporate"
    assert residual["ead_final"] == pytest.approx(450_000.0, rel=1e-6)
    assert residual["risk_weight"] == pytest.approx(1.0, rel=1e-6)

    assert (secured["ead_final"] + residual["ead_final"]) == pytest.approx(1_000_000.0)


def test_b31_split_total_rwa_matches_blended() -> None:
    """Sum of secured + residual RWA equals the blended whole-loan RWA.

    Blended = 550k × 20% + 450k × 100% = 110k + 450k = 560k.
    """
    config = CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    df = _run(config)

    total_rwa = df.filter(pl.col("exposure_reference").str.contains("LOAN1"))["rwa_final"].sum()
    assert total_rwa == pytest.approx(560_000.0, rel=1e-3)
