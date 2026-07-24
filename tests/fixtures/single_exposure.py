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

from datetime import date
from decimal import Decimal

import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.equity.calculator import EquityCalculator
from rwa_calc.engine.irb.calculator import IRBCalculator
from rwa_calc.engine.irb.formulas import firb_supervisory_lgd_values
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.engine.slotting.calculator import SlottingCalculator
from rwa_calc.rulebook.resolve import resolve
from rwa_calc.rulebook.v0 import RulepackV0


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
    original_maturity_years: float | None = None,
    entity_type: str | None = None,
    is_short_term_trade_lc: bool = False,
    collateral_re_value: Decimal | None = None,
    collateral_receivables_value: Decimal | None = None,
    collateral_other_physical_value: Decimal | None = None,
    cp_is_natural_person: bool = False,
    cp_is_social_housing: bool = False,
    prior_charge_ltv: Decimal | None = None,
    is_payroll_loan: bool = False,
    sovereign_cqs: int | None = None,
    local_currency: str | None = None,
    institution_cqs: int | None = None,
    is_hedged: bool = False,
    is_equivalent_jurisdiction: bool | None = None,
) -> dict:
    """Calculate SA RWA for a single exposure via calculate_branch."""
    data: dict = {
        "exposure_reference": ["SINGLE"],
        "ead_final": [float(ead)],
        "ead_gross": [float(ead)],
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
        "original_maturity_years": [
            original_maturity_years
            if original_maturity_years is not None
            else residual_maturity_years
        ],
        "cp_entity_type": [entity_type],
        "is_short_term_trade_lc": [is_short_term_trade_lc],
        "cp_is_natural_person": [cp_is_natural_person],
        "cp_is_social_housing": [cp_is_social_housing],
        "is_payroll_loan": [is_payroll_loan],
        "cp_sovereign_cqs": [sovereign_cqs],
        # CRR Art. 116(5) Treasury equivalence determination — None means "not
        # asserted", which for a third-country PSE gates Art. 116(1)/(2)/(3)
        # off and yields a flat 100%.
        "cp_is_equivalent_jurisdiction": [is_equivalent_jurisdiction],
        "cp_local_currency": [local_currency],
        "cp_institution_cqs": [institution_cqs],
        "is_hedged": [is_hedged],
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

    # The IRB branch input is sealed in production (crm_exit edge) — the
    # calculator reads contract columns directly, so the hand frame must
    # carry them with production-realistic values.
    data: dict = {
        "exposure_reference": ["SINGLE"],
        "ead_final": [float(ead)],
        "ead_gross": [float(ead)],
        # CRR Art. 223(4) CCF=100% CRM basis + Art. 223(5) exposure-side
        # volatility haircut: this is a pure on-balance-sheet row, so the basis
        # equals ead_gross and HE is zero (E' = E x (1 + HE) = ead_gross).
        "ead_for_crm": [float(ead)],
        "exposure_volatility_haircut": [0.0],
        "pd": [float(pd)],
        "maturity": [float(maturity)],
        "exposure_class": [exposure_class],
        "seniority": [seniority],
        "lgd": [float(lgd) if lgd is not None else None],
        "purchased_receivables_subtype": [None],
        "cp_is_financial_sector_entity": [False],
        "is_sme": [False],
        "sme_size_metric_gbp": [None],
        "is_infrastructure": [False],
        "is_qrre_transactor": [False],
        "requires_fi_scalar": [False],
        "has_one_day_maturity_floor": [False],
        "is_defaulted": [False],
        "beel": [0.0],
        "total_collateral_for_lgd": [0.0],
        "crm_alloc_financial": [0.0],
        "crm_alloc_covered_bond": [0.0],
        "crm_alloc_receivables": [0.0],
        "crm_alloc_real_estate": [0.0],
        "crm_alloc_other_physical": [0.0],
        "crm_alloc_life_insurance": [0.0],
        "provision_allocated": [0.0],
        "ava_amount": [0.0],
        "other_own_funds_reductions": [0.0],
    }

    if turnover_m is not None:
        data["turnover_m"] = [float(turnover_m)]

    # lgd_post_crm mirrors what the CRM stage would emit: the supervisory
    # LGD for the collateral type when secured, the own/supervisory
    # unsecured LGD otherwise (F-IRB reads lgd_post_crm as lgd_input).
    if collateral_type is not None:
        data["lgd_post_crm"] = [_firb_secured_lgd(collateral_type, is_subordinated)]
    elif lgd is not None:
        data["lgd_post_crm"] = [float(lgd)]
    else:
        table = firb_supervisory_lgd_values(RulepackV0.from_config(config).pack)
        data["lgd_post_crm"] = [
            float(table["subordinated" if is_subordinated else "unsecured_senior"])
        ]

    df = pl.DataFrame(
        data,
        schema_overrides={
            "lgd": pl.Float64,
            "purchased_receivables_subtype": pl.String,
            "sme_size_metric_gbp": pl.Float64,
        },
    ).lazy()
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
    # The slotting branch input is sealed in production (crm_exit edge) —
    # contract columns are read directly, so carry them explicitly with
    # production-realistic values.
    data: dict = {
        "exposure_reference": ["SINGLE"],
        "ead_final": [float(ead)],
        "approach": ["slotting"],
        "slotting_category": [category],
        "is_hvcre": [is_hvcre],
        "sl_type": [sl_type],
        "is_short_maturity": [is_short_maturity],
        "is_pre_operational": [is_pre_operational],
        "maturity_date": [None],
        "is_infrastructure": [bool(is_infrastructure) if is_infrastructure is not None else False],
        "is_sme": [bool(is_sme) if is_sme is not None else False],
        "provision_allocated": [0.0],
        "ava_amount": [0.0],
        "other_own_funds_reductions": [0.0],
    }

    df = pl.DataFrame(data, schema_overrides={"maturity_date": pl.Date}).lazy()

    return calculator.calculate_branch(df, config).collect().to_dicts()[0]


# F-IRB secured-collateral LGD key routing — ported verbatim from the former
# data/tables/firb_lgd.py::lookup_firb_lgd (CRR branch, is_basel_3_1=False,
# non-FSE). The CRR supervisory-LGD values now live in the rulepack; this helper
# routes a collateral_type/seniority to the projected CRR FIRB-dict key and
# returns the LGD as a float, reproducing lookup_firb_lgd's behaviour exactly so
# lgd_post_crm stays byte-identical.
def _firb_secured_lgd(collateral_type: str, is_subordinated: bool) -> float:
    # The secured branch always used the CRR table (lookup_firb_lgd default
    # is_basel_3_1=False), so resolve the CRR pack explicitly.
    table = firb_supervisory_lgd_values(resolve("crr", date(2026, 1, 1)))

    coll_lower = collateral_type.lower()

    # CRR Art. 230 Table 5 subordinated LGDS for the secured portion.
    sub_suffix = "_subordinated" if is_subordinated else ""

    # Covered bonds — Art. 161(1)(d), no subordinated distinction
    if coll_lower in ("covered_bond", "covered_bonds"):
        return float(table["covered_bond"])

    if coll_lower in ("financial_collateral", "cash", "deposit", "gold"):
        key = f"financial_collateral{sub_suffix}"
        return float(table.get(key, table["financial_collateral"]))

    if coll_lower in ("receivables", "trade_receivables"):
        key = f"receivables{sub_suffix}"
        return float(table.get(key, table["receivables"]))

    if coll_lower in ("residential_re", "rre", "residential"):
        key = f"residential_re{sub_suffix}"
        return float(table.get(key, table["residential_re"]))

    if coll_lower in ("commercial_re", "cre", "commercial"):
        key = f"commercial_re{sub_suffix}"
        return float(table.get(key, table["commercial_re"]))

    if coll_lower in ("real_estate", "property"):
        key = f"residential_re{sub_suffix}"
        return float(table.get(key, table["residential_re"]))

    if coll_lower in ("other_physical", "equipment", "inventory"):
        key = f"other_physical{sub_suffix}"
        return float(table.get(key, table["other_physical"]))

    # Unknown — treat as unsecured
    if is_subordinated:
        return float(table["subordinated"])
    return float(table["unsecured_senior"])
