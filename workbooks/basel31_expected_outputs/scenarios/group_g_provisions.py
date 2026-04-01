"""
Group G: Provisions & Impairments Scenarios

Scenarios G1-G3 covering provision treatment for SA and IRB.

Usage:
    uv run marimo edit workbooks/rwa_expected_outputs/scenarios/group_g_provisions.py
"""

import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import sys
    from dataclasses import asdict, dataclass
    from pathlib import Path
    from typing import Any

    import marimo as mo
    import polars as pl

    project_root = Path(__file__).parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from workbooks.rwa_expected_outputs.calculations.correlation import calculate_correlation
    from workbooks.rwa_expected_outputs.calculations.irb_formulas import (
        calculate_expected_loss,
        calculate_irb_rwa,
    )
    from workbooks.rwa_expected_outputs.calculations.sa_risk_weights import (
        calculate_sa_rwa,
        get_corporate_risk_weight,
    )
    from workbooks.rwa_expected_outputs.data.fixture_loader import load_fixtures

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
        calculate_sa_rwa,
        calculate_irb_rwa,
        calculate_expected_loss,
        calculate_correlation,
        ScenarioResult,
    )


@app.cell
def _(mo):
    mo.md("""
    # Group G: Provisions & Impairments Scenarios

    Scenarios demonstrating provision treatment:
    - **SA:** Specific provisions (SCRA) reduce EAD
    - **IRB:** Expected Loss (EL) compared to provisions for capital adjustment

    **Key Concepts:**
    - SCRA: Specific Credit Risk Adjustment (reduces EAD for SA)
    - GCRA: General Credit Risk Adjustment
    - IFRS9 Stages: Stage 1 (12m ECL), Stage 2 (lifetime ECL), Stage 3 (defaulted)
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
    ## Scenario G1: SA with SCRA

    **Input:** £1m exposure, £50k specific provision
    **Expected:** Net EAD = £950k for RWA calculation
    """)
    return


@app.cell
def _(get_corporate_risk_weight, calculate_sa_rwa, ScenarioResult):
    # G1: SA with SCRA
    ead_gross_g1 = 1_000_000.0
    provision_g1 = 50_000.0  # Specific provision

    # Net EAD after provision deduction
    ead_net_g1 = ead_gross_g1 - provision_g1

    rw_g1 = get_corporate_risk_weight(0)  # 100% unrated
    rwa_g1 = calculate_sa_rwa(ead_net_g1, rw_g1)

    result_g1 = ScenarioResult(
        scenario_id="G1",
        scenario_group="G",
        description="SA with SCRA provision",
        exposure_reference="LOAN_PROV_G1_001",
        counterparty_reference="CORP_PROV_G1_001",
        approach="SA",
        exposure_class="CORPORATE",
        ead=ead_net_g1,
        risk_weight=rw_g1,
        rwa=rwa_g1,
        calculation_details={
            "ead_gross": ead_gross_g1,
            "specific_provision": provision_g1,
            "provision_type": "SCRA",
            "ead_net": ead_net_g1,
            "formula": "EAD_net = EAD_gross - SCRA",
        },
        regulatory_reference="CRR Art 111",
    )

    print(f"G1: Gross EAD=£{ead_gross_g1:,.0f}, Provision=£{provision_g1:,.0f}")
    print(f"    Net EAD=£{ead_net_g1:,.0f}, RWA=£{rwa_g1:,.0f}")
    return result_g1, ead_gross_g1, provision_g1, ead_net_g1, rw_g1, rwa_g1


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario G2: IRB Stage 1 Provision

    **Input:** £1m exp, PD=1%, LGD=45%, £10k Stage 1 ECL
    **Expected:** Compare EL to provision for capital adjustment
    """)
    return


@app.cell
def _(calculate_irb_rwa, calculate_expected_loss, calculate_correlation, ScenarioResult):
    # G2: IRB with Stage 1 provision
    ead_g2 = 1_000_000.0
    pd_g2 = 0.01
    lgd_g2 = 0.45
    provision_g2 = 10_000.0  # Stage 1 ECL

    # Calculate EL
    el_g2 = calculate_expected_loss(pd_g2, lgd_g2, ead_g2)

    # EL vs Provision comparison
    el_shortfall_g2 = max(el_g2 - provision_g2, 0)  # Deducted from CET1
    el_excess_g2 = max(provision_g2 - el_g2, 0)  # Added back to T2 (capped)

    corr_g2 = calculate_correlation(pd_g2, "CORPORATE")
    irb_result_g2 = calculate_irb_rwa(
        ead=ead_g2,
        pd=pd_g2,
        lgd=lgd_g2,
        correlation=corr_g2,
        maturity=2.5,
        exposure_class="CORPORATE",
    )

    rwa_g2 = irb_result_g2["rwa"]

    result_g2 = ScenarioResult(
        scenario_id="G2",
        scenario_group="G",
        description="IRB Stage 1 provision",
        exposure_reference="LOAN_PROV_G2_001",
        counterparty_reference="CORP_PROV_G2_001",
        approach="FIRB",
        exposure_class="CORPORATE",
        ead=ead_g2,
        risk_weight=rwa_g2 / ead_g2,
        rwa=rwa_g2,
        calculation_details={
            "pd": pd_g2,
            "lgd": lgd_g2,
            "expected_loss": el_g2,
            "provision_stage_1": provision_g2,
            "el_shortfall": el_shortfall_g2,
            "el_excess": el_excess_g2,
            "formula": "EL = PD × LGD × EAD",
        },
        regulatory_reference="CRE35.1-3",
    )

    print(f"G2: EL = {pd_g2 * 100:.1f}% × {lgd_g2 * 100:.0f}% × £{ead_g2:,.0f} = £{el_g2:,.0f}")
    print(f"    Provision=£{provision_g2:,.0f}")
    print(f"    EL shortfall=£{el_shortfall_g2:,.0f}, EL excess=£{el_excess_g2:,.0f}")
    print(f"    RWA=£{rwa_g2:,.0f}")
    return (
        result_g2,
        ead_g2,
        pd_g2,
        lgd_g2,
        provision_g2,
        el_g2,
        el_shortfall_g2,
        el_excess_g2,
        corr_g2,
        irb_result_g2,
        rwa_g2,
    )


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario G3: IRB Stage 3 (Defaulted)

    **Input:** £1m defaulted exposure, PD=100%, LGD=45%, £400k Stage 3 provision
    **Expected:** Use LGD-in-default approach
    """)
    return


@app.cell
def _(ScenarioResult):
    # G3: IRB Stage 3 (defaulted)
    ead_g3 = 1_000_000.0
    pd_g3 = 1.0  # 100% PD for defaulted
    lgd_best_estimate_g3 = 0.45
    provision_g3 = 400_000.0  # Stage 3

    # For defaulted exposures, RWA is based on unexpected loss
    # UL = LGD - EL = LGD - (PD × LGD) = LGD × (1 - PD) for PD=100% this is 0
    # But best estimate LGD used for EL calculation
    el_g3 = ead_g3 * lgd_best_estimate_g3  # Best estimate EL

    # Shortfall/excess
    el_shortfall_g3 = max(el_g3 - provision_g3, 0)
    el_excess_g3 = max(provision_g3 - el_g3, 0)

    # For defaulted, RWA = max(0, LGD_BE - provision) × 12.5
    # Simplified: EL-based treatment
    rwa_g3 = max(el_g3 - provision_g3, 0) * 12.5

    result_g3 = ScenarioResult(
        scenario_id="G3",
        scenario_group="G",
        description="IRB Stage 3 (defaulted)",
        exposure_reference="LOAN_PROV_G3_001",
        counterparty_reference="CORP_DF_PROV_001",
        approach="FIRB",
        exposure_class="DEFAULTED",
        ead=ead_g3,
        risk_weight=rwa_g3 / ead_g3 if ead_g3 > 0 else 0,
        rwa=rwa_g3,
        calculation_details={
            "pd": pd_g3,
            "lgd_best_estimate": lgd_best_estimate_g3,
            "expected_loss": el_g3,
            "provision_stage_3": provision_g3,
            "el_shortfall": el_shortfall_g3,
            "el_excess": el_excess_g3,
            "defaulted_treatment": True,
        },
        regulatory_reference="CRE35.4",
    )

    print(
        f"G3 (defaulted): Best estimate EL = £{ead_g3:,.0f} × {lgd_best_estimate_g3 * 100:.0f}% = £{el_g3:,.0f}"
    )
    print(f"    Stage 3 provision=£{provision_g3:,.0f}")
    print(f"    EL shortfall=£{el_shortfall_g3:,.0f} (deducted from CET1)")
    print(f"    RWA=£{rwa_g3:,.0f}")
    return (
        result_g3,
        ead_g3,
        pd_g3,
        lgd_best_estimate_g3,
        provision_g3,
        el_g3,
        el_shortfall_g3,
        el_excess_g3,
        rwa_g3,
    )


@app.cell
def _(mo):
    mo.md("---\n## Summary: Group G Results")
    return


@app.cell
def _(result_g1, result_g2, result_g3, pl, mo):
    group_g_results = [result_g1, result_g2, result_g3]

    summary_data_g = [
        {
            "Scenario": r.scenario_id,
            "Description": r.description,
            "EAD (£)": f"{r.ead:,.0f}",
            "RWA (£)": f"{r.rwa:,.0f}",
        }
        for r in group_g_results
    ]

    mo.ui.table(pl.DataFrame(summary_data_g))
    return group_g_results, summary_data_g


@app.cell
def _(group_g_results):
    def get_group_g_results():
        return group_g_results

    return (get_group_g_results,)


if __name__ == "__main__":
    app.run()
