"""
Test helpers for single-exposure calculation via calculate_branch.

These helpers build a single-row LazyFrame and call the calculator's
calculate_branch method, exercising the real pipeline code path.

Usage:
    from tests.fixtures.single_exposure import calculate_single_sa_exposure

    result = calculate_single_sa_exposure(
        sa_calculator, ead=Decimal("1000000"),
        exposure_class="CORPORATE", cqs=3, config=crr_config,
    )
    assert result["risk_weight"] == pytest.approx(1.0)
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.tables.crr_firb_lgd import lookup_firb_lgd
from rwa_calc.engine.equity.calculator import EquityCalculator
from rwa_calc.engine.irb.calculator import IRBCalculator
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.engine.slotting.calculator import SlottingCalculator


def calculate_single_sa_exposure(
    calculator: SACalculator,
    *,
    ead: Decimal,
    exposure_class: str,
    config: CalculationConfig,
    cqs: int | None = None,
    ltv: Decimal | None = None,
    is_sme: bool = False,
    is_infrastructure: bool = False,
    is_managed_as_retail: bool = False,
    qualifies_as_retail: bool = True,
    has_income_cover: bool = False,
    property_type: str | None = None,
    is_adc: bool = False,
    is_presold: bool = False,
    seniority: str = "senior",
    scra_grade: str | None = None,
    is_investment_grade: bool = False,
    is_defaulted: bool = False,
    provision_allocated: Decimal | None = None,
    provision_deducted: Decimal | None = None,
    currency: str | None = None,
    country_code: str | None = None,
    borrower_income_currency: str | None = None,
    residual_maturity_years: float | None = None,
    entity_type: str | None = None,
    is_short_term_trade_lc: bool = False,
    collateral_re_value: Decimal | None = None,
    collateral_receivables_value: Decimal | None = None,
    collateral_other_physical_value: Decimal | None = None,
    cp_is_natural_person: bool = False,
    cp_is_social_housing: bool = False,
    prior_charge_ltv: Decimal | None = None,
    is_payroll_loan: bool = False,
) -> dict:
    """Calculate SA RWA for a single exposure via calculate_branch."""
    data: dict = {
        "exposure_reference": ["SINGLE"],
        "ead_final": [float(ead)],
        "exposure_class": [exposure_class],
        "cqs": [cqs],
        "ltv": [float(ltv) if ltv is not None else None],
        "is_sme": [is_sme],
        "is_infrastructure": [is_infrastructure],
        "has_income_cover": [has_income_cover],
        "cp_is_managed_as_retail": [is_managed_as_retail],
        "qualifies_as_retail": [qualifies_as_retail],
        "property_type": [property_type],
        "is_adc": [is_adc],
        "is_presold": [is_presold],
        "seniority": [seniority],
        "cp_scra_grade": [scra_grade],
        "cp_is_investment_grade": [is_investment_grade],
        "is_defaulted": [is_defaulted],
        "provision_allocated": [float(provision_allocated) if provision_allocated else 0.0],
        "provision_deducted": [float(provision_deducted) if provision_deducted else 0.0],
        "currency": [currency],
        "cp_country_code": [country_code],
        "borrower_income_currency": [borrower_income_currency],
        "residual_maturity_years": [residual_maturity_years],
        "cp_entity_type": [entity_type],
        "is_short_term_trade_lc": [is_short_term_trade_lc],
        "cp_is_natural_person": [cp_is_natural_person],
        "cp_is_social_housing": [cp_is_social_housing],
        "is_payroll_loan": [is_payroll_loan],
    }
    if prior_charge_ltv is not None:
        data["prior_charge_ltv"] = [float(prior_charge_ltv)]
    if collateral_re_value is not None:
        data["collateral_re_value"] = [float(collateral_re_value)]
    if collateral_receivables_value is not None:
        data["collateral_receivables_value"] = [float(collateral_receivables_value)]
    if collateral_other_physical_value is not None:
        data["collateral_other_physical_value"] = [float(collateral_other_physical_value)]

    df = pl.DataFrame(data).lazy()

    result = calculator.calculate_branch(df, config).collect().to_dicts()[0]
    # Alias rwa_post_factor as rwa for consistency with other calculators
    result["rwa"] = result["rwa_post_factor"]
    return result


def calculate_single_irb_exposure(
    calculator: IRBCalculator,
    *,
    ead: Decimal,
    pd: Decimal,
    config: CalculationConfig,
    lgd: Decimal | None = None,
    maturity: Decimal = Decimal("2.5"),
    exposure_class: str = "CORPORATE",
    turnover_m: Decimal | None = None,
    collateral_type: str | None = None,
    is_subordinated: bool = False,
) -> dict:
    """Calculate IRB RWA for a single exposure via calculate_branch."""
    seniority = "subordinated" if is_subordinated else "senior"

    data: dict = {
        "exposure_reference": ["SINGLE"],
        "ead": [float(ead)],
        "pd": [float(pd)],
        "maturity": [float(maturity)],
        "exposure_class": [exposure_class],
        "seniority": [seniority],
    }

    if lgd is not None:
        data["lgd"] = [float(lgd)]

    if turnover_m is not None:
        data["turnover_m"] = [float(turnover_m)]

    if collateral_type is not None:
        data["lgd_post_crm"] = [float(lookup_firb_lgd(collateral_type, is_subordinated))]

    df = pl.DataFrame(data).lazy()
    return calculator.calculate_branch(df, config).collect().to_dicts()[0]


def calculate_single_equity_exposure(
    calculator: EquityCalculator,
    *,
    ead: Decimal,
    equity_type: str,
    config: CalculationConfig,
    is_diversified: bool = False,
    is_speculative: bool = False,
    is_exchange_traded: bool = False,
    is_government_supported: bool = False,
    ciu_approach: str | None = None,
    ciu_mandate_rw: float | None = None,
    ciu_third_party_calc: bool | None = None,
) -> dict:
    """Calculate equity RWA for a single exposure via calculate_branch."""
    df = pl.DataFrame(
        {
            "exposure_reference": ["SINGLE"],
            "ead_final": [float(ead)],
            "equity_type": [equity_type],
            "is_diversified_portfolio": [is_diversified],
            "is_speculative": [is_speculative],
            "is_exchange_traded": [is_exchange_traded],
            "is_government_supported": [is_government_supported],
            "ciu_approach": [ciu_approach],
            "ciu_mandate_rw": [ciu_mandate_rw],
            "ciu_third_party_calc": [ciu_third_party_calc],
        }
    ).lazy()

    result = calculator.calculate_branch(df, config).collect().to_dicts()[0]
    # Add approach metadata for tests that check approach determination
    approach = calculator._determine_approach(config)
    result["approach"] = approach
    result["article"] = "133" if approach == "sa" else "155"
    return result


def calculate_single_slotting_exposure(
    calculator: SlottingCalculator,
    *,
    ead: Decimal,
    category: str,
    config: CalculationConfig,
    is_hvcre: bool = False,
    sl_type: str = "project_finance",
    is_short_maturity: bool = False,
    is_pre_operational: bool = False,
    is_infrastructure: bool | None = None,
    is_sme: bool | None = None,
) -> dict:
    """Calculate slotting RWA for a single exposure via calculate_branch."""
    data: dict = {
        "exposure_reference": ["SINGLE"],
        "ead": [float(ead)],
        "slotting_category": [category],
        "is_hvcre": [is_hvcre],
        "sl_type": [sl_type],
        "is_short_maturity": [is_short_maturity],
        "is_pre_operational": [is_pre_operational],
    }
    if is_infrastructure is not None:
        data["is_infrastructure"] = [is_infrastructure]
    if is_sme is not None:
        data["is_sme"] = [is_sme]

    df = pl.DataFrame(data).lazy()

    return calculator.calculate_branch(df, config).collect().to_dicts()[0]
