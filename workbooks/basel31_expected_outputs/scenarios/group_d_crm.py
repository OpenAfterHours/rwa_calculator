"""
Group D: Credit Risk Mitigation (CRM) Scenarios

Scenarios D1-D6 covering collateral haircuts, guarantee substitution,
and maturity/FX mismatch adjustments.

Usage:
    uv run marimo edit workbooks/rwa_expected_outputs/scenarios/group_d_crm.py
"""

import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import polars as pl
    import sys
    from pathlib import Path
    from dataclasses import dataclass, asdict
    from typing import Any

    project_root = Path(__file__).parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from workbooks.rwa_expected_outputs.data.fixture_loader import load_fixtures
    from workbooks.rwa_expected_outputs.calculations.sa_risk_weights import (
        get_corporate_risk_weight,
        get_institution_risk_weight,
        calculate_sa_rwa,
    )
    from workbooks.rwa_expected_outputs.calculations.crm_haircuts import (
        get_collateral_haircut,
        calculate_adjusted_collateral_value,
        apply_maturity_mismatch,
        apply_fx_mismatch,
        calculate_guarantee_substitution,
    )

    @dataclass
    class ScenarioResult:
        scenario_id: str
        scenario_group: str
        description: str
        exposure_reference: str
        counterparty_reference: str
        approach: str
        exposure_class: str
        ead: float
        risk_weight: float
        rwa: float
        calculation_details: dict
        regulatory_reference: str

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)

    return (
        mo,
        pl,
        Path,
        load_fixtures,
        get_corporate_risk_weight,
        get_institution_risk_weight,
        calculate_sa_rwa,
        get_collateral_haircut,
        calculate_adjusted_collateral_value,
        apply_maturity_mismatch,
        apply_fx_mismatch,
        calculate_guarantee_substitution,
        ScenarioResult,
    )


@app.cell
def _(mo):
    mo.md("""
    # Group D: Credit Risk Mitigation (CRM) Scenarios

    Scenarios D1-D6 demonstrate CRM calculations including:
    - Collateral haircuts (cash, govt bonds, equity)
    - Guarantee substitution approach
    - Maturity mismatch adjustment
    - Currency (FX) mismatch adjustment

    **Reference:** CRE22
    """)
    return


@app.cell
def _(load_fixtures):
    fixtures = load_fixtures()
    return (fixtures,)


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario D1: Cash Collateral (SA)

    **Input:** £1m exposure, £500k cash collateral
    **Expected:** 0% haircut, £500k EAD after CRM
    """)
    return


@app.cell
def _(get_corporate_risk_weight, calculate_sa_rwa, get_collateral_haircut, ScenarioResult):
    # D1: Cash collateral
    ead_gross_d1 = 1_000_000.0
    collateral_d1 = 500_000.0

    haircut_d1 = get_collateral_haircut("cash")  # 0%
    collateral_adj_d1 = collateral_d1 * (1 - haircut_d1)
    ead_net_d1 = max(ead_gross_d1 - collateral_adj_d1, 0)

    rw_d1 = get_corporate_risk_weight(0)  # 100% unrated
    rwa_d1 = calculate_sa_rwa(ead_net_d1, rw_d1)

    result_d1 = ScenarioResult(
        scenario_id="D1",
        scenario_group="D",
        description="Cash collateral (SA)",
        exposure_reference="LOAN_CRM_D1_001",
        counterparty_reference="CORP_CRM_D1_001",
        approach="SA",
        exposure_class="CORPORATE",
        ead=ead_net_d1,
        risk_weight=rw_d1,
        rwa=rwa_d1,
        calculation_details={
            "ead_gross": ead_gross_d1,
            "collateral_value": collateral_d1,
            "haircut": haircut_d1,
            "collateral_adjusted": collateral_adj_d1,
            "ead_net": ead_net_d1,
            "formula": "EAD_net = EAD_gross - C_adj",
        },
        regulatory_reference="CRE22.52",
    )

    print(
        f"D1: Gross EAD=£{ead_gross_d1:,.0f}, Cash=£{collateral_d1:,.0f}, Haircut={haircut_d1 * 100:.0f}%"
    )
    print(f"    Net EAD=£{ead_net_d1:,.0f}, RWA=£{rwa_d1:,.0f}")
    return (
        result_d1,
        ead_gross_d1,
        collateral_d1,
        haircut_d1,
        collateral_adj_d1,
        ead_net_d1,
        rw_d1,
        rwa_d1,
    )


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario D2: Government Bond Collateral

    **Input:** £1m exposure, £600k UK gilts (5yr maturity)
    **Expected:** 2% supervisory haircut for sovereign CQS1, 3-5yr maturity
    """)
    return


@app.cell
def _(
    get_corporate_risk_weight, calculate_sa_rwa, calculate_adjusted_collateral_value, ScenarioResult
):
    # D2: Govt bond collateral
    ead_gross_d2 = 1_000_000.0
    collateral_value_d2 = 600_000.0

    coll_result_d2 = calculate_adjusted_collateral_value(
        collateral_market_value=collateral_value_d2,
        collateral_type="sovereign_debt",
        issuer_type="sovereign",
        cqs=1,  # UK Govt CQS1
        residual_maturity_years=5.0,
        exposure_maturity_years=5.0,
        exposure_currency="GBP",
        collateral_currency="GBP",
    )

    ead_net_d2 = max(ead_gross_d2 - coll_result_d2["adjusted_value"], 0)
    rw_d2 = get_corporate_risk_weight(0)
    rwa_d2 = calculate_sa_rwa(ead_net_d2, rw_d2)

    result_d2 = ScenarioResult(
        scenario_id="D2",
        scenario_group="D",
        description="Govt bond collateral (SA)",
        exposure_reference="LOAN_CRM_D2_001",
        counterparty_reference="CORP_CRM_D2_001",
        approach="SA",
        exposure_class="CORPORATE",
        ead=ead_net_d2,
        risk_weight=rw_d2,
        rwa=rwa_d2,
        calculation_details={
            "ead_gross": ead_gross_d2,
            **coll_result_d2,
            "ead_net": ead_net_d2,
        },
        regulatory_reference="CRE22.52-53",
    )

    print(
        f"D2: Gilts=£{collateral_value_d2:,.0f}, Haircut={coll_result_d2['base_haircut'] * 100:.1f}%"
    )
    print(f"    Adjusted collateral=£{coll_result_d2['adjusted_value']:,.0f}")
    print(f"    Net EAD=£{ead_net_d2:,.0f}, RWA=£{rwa_d2:,.0f}")
    return result_d2, ead_gross_d2, collateral_value_d2, coll_result_d2, ead_net_d2, rw_d2, rwa_d2


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario D3: Equity Collateral

    **Input:** £1m exposure, £400k listed equity (main index)
    **Expected:** 25% haircut for main index equity
    """)
    return


@app.cell
def _(get_corporate_risk_weight, calculate_sa_rwa, get_collateral_haircut, ScenarioResult):
    # D3: Equity collateral
    ead_gross_d3 = 1_000_000.0
    collateral_d3 = 400_000.0

    haircut_d3 = get_collateral_haircut("equity")  # 25%
    collateral_adj_d3 = collateral_d3 * (1 - haircut_d3)
    ead_net_d3 = max(ead_gross_d3 - collateral_adj_d3, 0)

    rw_d3 = get_corporate_risk_weight(0)
    rwa_d3 = calculate_sa_rwa(ead_net_d3, rw_d3)

    result_d3 = ScenarioResult(
        scenario_id="D3",
        scenario_group="D",
        description="Equity collateral (SA)",
        exposure_reference="LOAN_CRM_D3_001",
        counterparty_reference="CORP_CRM_D3_001",
        approach="SA",
        exposure_class="CORPORATE",
        ead=ead_net_d3,
        risk_weight=rw_d3,
        rwa=rwa_d3,
        calculation_details={
            "ead_gross": ead_gross_d3,
            "collateral_value": collateral_d3,
            "haircut": haircut_d3,
            "collateral_adjusted": collateral_adj_d3,
            "ead_net": ead_net_d3,
        },
        regulatory_reference="CRE22.52",
    )

    print(f"D3: Equity=£{collateral_d3:,.0f}, Haircut={haircut_d3 * 100:.0f}%")
    print(f"    Adjusted=£{collateral_adj_d3:,.0f}, Net EAD=£{ead_net_d3:,.0f}")
    print(f"    RWA=£{rwa_d3:,.0f}")
    return (
        result_d3,
        ead_gross_d3,
        collateral_d3,
        haircut_d3,
        collateral_adj_d3,
        ead_net_d3,
        rw_d3,
        rwa_d3,
    )


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario D4: Guarantee Substitution

    **Input:** £1m corp exposure (100% RW), £600k bank guarantee (20% RW)
    **Expected:** Split calculation - covered at 20%, uncovered at 100%
    """)
    return


@app.cell
def _(
    get_corporate_risk_weight,
    get_institution_risk_weight,
    calculate_guarantee_substitution,
    ScenarioResult,
):
    # D4: Guarantee substitution
    exposure_d4 = 1_000_000.0
    guarantee_d4 = 600_000.0

    rw_underlying_d4 = get_corporate_risk_weight(0)  # 100% unrated corp
    rw_guarantor_d4 = get_institution_risk_weight(1)  # 20% CQS1 bank

    guar_result_d4 = calculate_guarantee_substitution(
        exposure_amount=exposure_d4,
        exposure_risk_weight=rw_underlying_d4,
        guarantee_amount=guarantee_d4,
        guarantor_risk_weight=rw_guarantor_d4,
    )

    result_d4 = ScenarioResult(
        scenario_id="D4",
        scenario_group="D",
        description="Guarantee substitution (SA)",
        exposure_reference="LOAN_CRM_D4_001",
        counterparty_reference="CORP_CRM_D4_001",
        approach="SA",
        exposure_class="CORPORATE",
        ead=exposure_d4,
        risk_weight=guar_result_d4["total_rwa"] / exposure_d4,  # Blended RW
        rwa=guar_result_d4["total_rwa"],
        calculation_details={
            **guar_result_d4,
            "underlying_rw": rw_underlying_d4,
            "guarantor_rw": rw_guarantor_d4,
            "formula": "RWA = (covered × RW_guarantor) + (uncovered × RW_underlying)",
        },
        regulatory_reference="CRE22.70-71",
    )

    print(f"D4: Exposure=£{exposure_d4:,.0f}, Guarantee=£{guarantee_d4:,.0f}")
    print(
        f"    Covered RWA=£{guar_result_d4['covered_rwa']:,.0f} (at {rw_guarantor_d4 * 100:.0f}%)"
    )
    print(
        f"    Uncovered RWA=£{guar_result_d4['uncovered_rwa']:,.0f} (at {rw_underlying_d4 * 100:.0f}%)"
    )
    print(f"    Total RWA=£{guar_result_d4['total_rwa']:,.0f}")
    return result_d4, exposure_d4, guarantee_d4, rw_underlying_d4, rw_guarantor_d4, guar_result_d4


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario D5: Maturity Mismatch

    **Input:** £1m exp (5yr), £500k collateral (2yr residual)
    **Expected:** Adjusted collateral value using (t-0.25)/(T-0.25) formula
    """)
    return


@app.cell
def _(get_corporate_risk_weight, calculate_sa_rwa, apply_maturity_mismatch, ScenarioResult):
    # D5: Maturity mismatch
    ead_gross_d5 = 1_000_000.0
    collateral_d5 = 500_000.0
    exp_maturity_d5 = 5.0  # years
    coll_maturity_d5 = 2.0  # years

    collateral_adj_d5 = apply_maturity_mismatch(
        collateral_value=collateral_d5,
        collateral_maturity_years=coll_maturity_d5,
        exposure_maturity_years=exp_maturity_d5,
    )

    ead_net_d5 = max(ead_gross_d5 - collateral_adj_d5, 0)
    rw_d5 = get_corporate_risk_weight(0)
    rwa_d5 = calculate_sa_rwa(ead_net_d5, rw_d5)

    # Manual calculation verification
    # Adjustment = (t - 0.25) / (T - 0.25) = (2 - 0.25) / (5 - 0.25) = 1.75 / 4.75 = 0.368
    mat_adj_factor = (coll_maturity_d5 - 0.25) / (exp_maturity_d5 - 0.25)

    result_d5 = ScenarioResult(
        scenario_id="D5",
        scenario_group="D",
        description="Maturity mismatch (SA)",
        exposure_reference="LOAN_CRM_D5_001",
        counterparty_reference="CORP_CRM_D5_001",
        approach="SA",
        exposure_class="CORPORATE",
        ead=ead_net_d5,
        risk_weight=rw_d5,
        rwa=rwa_d5,
        calculation_details={
            "ead_gross": ead_gross_d5,
            "collateral_value": collateral_d5,
            "exposure_maturity": exp_maturity_d5,
            "collateral_maturity": coll_maturity_d5,
            "maturity_adjustment_factor": mat_adj_factor,
            "collateral_adjusted": collateral_adj_d5,
            "ead_net": ead_net_d5,
            "formula": "C_adj = C × (t - 0.25) / (T - 0.25)",
        },
        regulatory_reference="CRE22.65-66",
    )

    print(f"D5: Coll maturity={coll_maturity_d5}yr, Exp maturity={exp_maturity_d5}yr")
    print(f"    Adjustment factor={(mat_adj_factor):.3f}")
    print(f"    Adjusted collateral=£{collateral_adj_d5:,.0f}")
    print(f"    RWA=£{rwa_d5:,.0f}")
    return (
        result_d5,
        ead_gross_d5,
        collateral_d5,
        exp_maturity_d5,
        coll_maturity_d5,
        collateral_adj_d5,
        mat_adj_factor,
        ead_net_d5,
        rw_d5,
        rwa_d5,
    )


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario D6: Currency Mismatch

    **Input:** £1m GBP exposure, €500k EUR collateral
    **Expected:** 8% FX haircut applied
    """)
    return


@app.cell
def _(get_corporate_risk_weight, calculate_sa_rwa, apply_fx_mismatch, ScenarioResult):
    # D6: Currency mismatch
    ead_gross_d6 = 1_000_000.0
    collateral_d6 = 500_000.0  # EUR value in GBP equivalent

    collateral_adj_d6 = apply_fx_mismatch(
        collateral_value=collateral_d6,
        exposure_currency="GBP",
        collateral_currency="EUR",
    )

    ead_net_d6 = max(ead_gross_d6 - collateral_adj_d6, 0)
    rw_d6 = get_corporate_risk_weight(0)
    rwa_d6 = calculate_sa_rwa(ead_net_d6, rw_d6)

    fx_haircut = 0.08  # 8%

    result_d6 = ScenarioResult(
        scenario_id="D6",
        scenario_group="D",
        description="Currency mismatch (SA)",
        exposure_reference="LOAN_CRM_D6_001",
        counterparty_reference="CORP_CRM_D6_001",
        approach="SA",
        exposure_class="CORPORATE",
        ead=ead_net_d6,
        risk_weight=rw_d6,
        rwa=rwa_d6,
        calculation_details={
            "ead_gross": ead_gross_d6,
            "collateral_value": collateral_d6,
            "exposure_currency": "GBP",
            "collateral_currency": "EUR",
            "fx_haircut": fx_haircut,
            "collateral_adjusted": collateral_adj_d6,
            "ead_net": ead_net_d6,
            "formula": "C_adj = C × (1 - Hfx)",
        },
        regulatory_reference="CRE22.54",
    )

    print(f"D6: Collateral=£{collateral_d6:,.0f} (EUR), FX haircut={fx_haircut * 100:.0f}%")
    print(f"    Adjusted=£{collateral_adj_d6:,.0f}, RWA=£{rwa_d6:,.0f}")
    return (
        result_d6,
        ead_gross_d6,
        collateral_d6,
        collateral_adj_d6,
        fx_haircut,
        ead_net_d6,
        rw_d6,
        rwa_d6,
    )


@app.cell
def _(mo):
    mo.md("---\n## Summary: Group D Results")
    return


@app.cell
def _(result_d1, result_d2, result_d3, result_d4, result_d5, result_d6, pl, mo):
    group_d_results = [result_d1, result_d2, result_d3, result_d4, result_d5, result_d6]

    summary_data_d = [
        {
            "Scenario": r.scenario_id,
            "Description": r.description,
            "EAD (£)": f"{r.ead:,.0f}",
            "RW": f"{r.risk_weight * 100:.0f}%",
            "RWA (£)": f"{r.rwa:,.0f}",
        }
        for r in group_d_results
    ]

    mo.ui.table(pl.DataFrame(summary_data_d))
    return group_d_results, summary_data_d


@app.cell
def _(group_d_results):
    def get_group_d_results():
        return group_d_results

    return (get_group_d_results,)


if __name__ == "__main__":
    app.run()
