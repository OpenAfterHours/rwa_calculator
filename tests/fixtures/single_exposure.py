"""
Test helpers for single-exposure calculation via calculate_branch.

These helpers build a single-row LazyFrame and call the calculator's
calculate_branch method, exercising the real pipeline code path.

Usage:
    from tests.fixtures.single_exposure import calculate_single_sa_exposure

    result = calculate_single_sa_exposure(
        sa_calculator, ead=Decimal("1000000"),
        exposure_class=ExposureClass.CORPORATE.value, cqs=3, config=crr_config,
    )
    assert result["risk_weight"] == pytest.approx(1.0)

``exposure_class`` must be an ``ExposureClass`` value — what the classifier
writes, lowercase and never null (P5.69). The SA, IRB and slotting builders run
``require_exposure_class_values`` on the frame they hand to ``calculate_branch``
— the frame itself, not the argument — so a class that is absent, null, an
upper-case spelling or an invented one is refused before a calculator's
exact-``.value`` gate can take a branch production never takes. A test that
deliberately exercises the engine's case tolerance builds its own frame with
``member.value.upper()``.

The equity builder writes no class, because production does not: the equity
calculator's input is the raw ``equity_exposures`` table, which carries no
``exposure_class`` (``RAW_TABLE_EDGES["equity_exposures"]``), and the aggregator
stamps ``equity`` / ``ciu`` from ``equity_type`` afterwards when the calculator
has written no class (``engine/aggregator/_equity_prep.py``; the CRR PD/LGD
branch writes ``"CORPORATE"`` itself, a known production defect declared in
``KNOWN_PRODUCTION_CLASS_DEFECTS``). Writing one here would hand the
calculator a state production never does.
``tests/contracts/test_harness_exposure_class_domain.py`` records the frame each
builder hands its calculator and holds both rules.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.equity.calculator import EquityCalculator
from rwa_calc.engine.irb.calculator import IRBCalculator
from rwa_calc.engine.irb.formulas import firb_supervisory_lgd_values
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.engine.slotting.calculator import SlottingCalculator
from rwa_calc.rulebook.resolve import resolve
from rwa_calc.rulebook.v0 import RulepackV0
from tests.fixtures.contract_columns import require_exposure_class_values


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
    funding_currency: str | None = None,
    funding_currency_null: bool = False,
    is_qualifying_re: bool | None = None,
) -> dict:
    """Calculate SA RWA for a single exposure via calculate_branch.

    ``exposure_class`` must be an ``ExposureClass`` value: the frame handed to
    ``calculate_branch`` is checked, and a ValueError raised otherwise.

    ``funding_currency`` / ``funding_currency_null`` (P1.314, CRR Art. 114(4)/
    (7)/115(5) via Art. 235(3)): "column absent" and "column present and null"
    are DIFFERENT code paths in ``eu_sovereign.funding_currency_expr`` — the
    former falls back to the denomination currency without ever naming the
    column, the latter names it and ``fill_null``s row-by-row. Both defaults
    are off, which leaves the frame with no ``funding_currency`` column at all
    — the column-absent path every existing caller of this helper takes today,
    unchanged.
    """
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
        # The real-estate qualification attestation (CRR Art. 125(2)/126(2);
        # PS1/26 Art. 124A). None = not reported, the input contract's null.
        "is_qualifying_re": pl.Series([is_qualifying_re], dtype=pl.Boolean),
    }
    if prior_charge_ltv is not None:
        data["prior_charge_ltv"] = [float(prior_charge_ltv)]
    if collateral_re_value is not None:
        data["collateral_re_value"] = [float(collateral_re_value)]
    if collateral_receivables_value is not None:
        data["collateral_receivables_value"] = [float(collateral_receivables_value)]
    if collateral_other_physical_value is not None:
        data["collateral_other_physical_value"] = [float(collateral_other_physical_value)]

    schema_overrides: dict[str, pl.PolarsDataType] = {}
    if funding_currency is not None:
        data["funding_currency"] = [funding_currency]
    elif funding_currency_null:
        # Column PRESENT and null — distinct from column ABSENT (the default).
        # Force String rather than Null so the frame matches the edge dtype
        # (contracts/edges.py: EdgeColumn(dtype=pl.String, ...)).
        data["funding_currency"] = [None]
        schema_overrides["funding_currency"] = pl.String

    df = pl.DataFrame(data, schema_overrides=schema_overrides).lazy()
    require_exposure_class_values(df, "sa_branch")

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
    exposure_class: str = ExposureClass.CORPORATE.value,
    turnover_m: Decimal | None = None,
    collateral_type: str | None = None,
    is_subordinated: bool = False,
) -> dict:
    """Calculate IRB RWA for a single exposure via calculate_branch.

    ``exposure_class`` must be an ``ExposureClass`` value: the frame handed to
    ``calculate_branch`` is checked, and a ValueError raised otherwise.
    """
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
        # Property-security carriers (P1.324): no property evidence.
        "property_type": [None],
        "residential_collateral_value_uncapped": [0.0],
        "re_collateral_may_be_residential": [False],
        "is_uk_residential_mortgage_commitment": [False],
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
            "property_type": pl.String,
        },
    ).lazy()
    require_exposure_class_values(df, "irb_branch")
    return calculator.calculate_branch(df, config).collect().to_dicts()[0]


def calculate_single_equity_exposure(
    calculator: EquityCalculator,
    *,
    ead: Decimal,
    equity_type: str,
    config: CalculationConfig,
    is_speculative: bool = False,
    is_exchange_traded: bool = False,
    is_government_supported: bool = False,
    ciu_approach: str | None = None,
    ciu_mandate_rw: float | None = None,
    ciu_third_party_calc: bool | None = None,
    ciu_look_through_rw: float | None = None,
    ciu_unrestricted_access: bool | None = None,
) -> dict:
    """Calculate equity RWA for a single exposure via calculate_branch.

    Writes no ``exposure_class``, as production does not: the equity
    calculator's input is the raw ``equity_exposures`` table, which carries none
    (see the module docstring). Do not add one.
    """
    df = pl.DataFrame(
        {
            "exposure_reference": ["SINGLE"],
            "ead_final": [float(ead)],
            "equity_type": [equity_type],
            "is_speculative": [is_speculative],
            "is_exchange_traded": [is_exchange_traded],
            "is_government_supported": [is_government_supported],
            "ciu_approach": [ciu_approach],
            "ciu_mandate_rw": [ciu_mandate_rw],
            "ciu_third_party_calc": [ciu_third_party_calc],
            "ciu_look_through_rw": [ciu_look_through_rw],
            "ciu_unrestricted_access": [ciu_unrestricted_access],
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
    """Calculate slotting RWA for a single exposure via calculate_branch.

    The frame handed to ``calculate_branch`` must carry an ``ExposureClass``
    value (ValueError otherwise) — always ``specialised_lending`` here.
    """
    # The slotting branch input is sealed in production (crm_exit edge) —
    # contract columns are read directly, so carry them explicitly with
    # production-realistic values.
    #
    # ``exposure_class`` is one of them and was missing until the CRR
    # Art. 501a(1)(a) class gate started reading it: ``engine/classify/
    # approach.py`` routes to slotting only when ``exposure_class ==
    # specialised_lending``, so a slotting row cannot exist with any other
    # value, and leaving it absent made every caller take the gate's
    # permissive column-absent fallback rather than its real class limb.
    data: dict = {
        "exposure_reference": ["SINGLE"],
        "ead_final": [float(ead)],
        "approach": ["slotting"],
        "exposure_class": [ExposureClass.SPECIALISED_LENDING.value],
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
    require_exposure_class_values(df, "slotting_branch")

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
