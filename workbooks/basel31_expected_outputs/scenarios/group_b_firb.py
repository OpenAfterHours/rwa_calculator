"""
Group B: Foundation IRB (F-IRB) Scenarios

Scenarios B1-B6 covering F-IRB calculations with supervisory LGD values.

Usage:
    uv run marimo edit workbooks/rwa_expected_outputs/scenarios/group_b_firb.py
"""

import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium")


@app.cell
def _():
    """Imports and setup."""
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
    from workbooks.rwa_expected_outputs.data.regulatory_params import (
        FIRB_LGD,
        PD_FLOORS,
    )
    from workbooks.rwa_expected_outputs.calculations.irb_formulas import (
        calculate_irb_rwa,
        apply_pd_floor,
    )
    from workbooks.rwa_expected_outputs.calculations.correlation import (
        calculate_correlation,
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
        project_root,
        load_fixtures,
        FIRB_LGD,
        PD_FLOORS,
        calculate_irb_rwa,
        apply_pd_floor,
        calculate_correlation,
        ScenarioResult,
    )


@app.cell
def _(mo):
    mo.md("""
    # Group B: Foundation IRB (F-IRB) Scenarios

    Scenarios B1-B6 demonstrate F-IRB RWA calculations using:
    - Bank-estimated PD
    - Supervisory LGD values (45% unsecured senior, 75% subordinated)
    - Supervisory EAD (drawn + CCF × undrawn)

    **Key Formulas:**
    - K = LGD × N[(1-R)^(-0.5) × G(PD) + (R/(1-R))^(0.5) × G(0.999)] - PD × LGD
    - RWA = K × 12.5 × EAD × MA
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
    ## Scenario B1: Corporate Unsecured

    **Input:** PD=1%, LGD=45% (supervisory), M=2.5y, EAD=£1m
    **Reference:** CRE31-32
    """)
    return


@app.cell
def _(calculate_correlation, calculate_irb_rwa, FIRB_LGD, ScenarioResult):
    # B1: Corporate unsecured
    pd_b1 = 0.01  # 1%
    lgd_b1 = FIRB_LGD["unsecured"]["senior"]  # 45%
    ead_b1 = 1_000_000.0
    maturity_b1 = 2.5

    corr_b1 = calculate_correlation(pd_b1, "CORPORATE")
    irb_result_b1 = calculate_irb_rwa(
        ead=ead_b1,
        pd=pd_b1,
        lgd=lgd_b1,
        correlation=corr_b1,
        maturity=maturity_b1,
        exposure_class="CORPORATE",
    )

    rwa_b1 = irb_result_b1["rwa"]
    rw_b1 = rwa_b1 / ead_b1  # Effective risk weight

    result_b1 = ScenarioResult(
        scenario_id="B1",
        scenario_group="B",
        description="Corporate unsecured F-IRB",
        exposure_reference="LOAN_FIRB_CORP_001",
        counterparty_reference="CORP_FIRB_001",
        approach="FIRB",
        exposure_class="CORPORATE",
        ead=ead_b1,
        risk_weight=rw_b1,
        rwa=rwa_b1,
        calculation_details=irb_result_b1,
        regulatory_reference="CRE31-32",
    )

    print(f"B1: PD={pd_b1 * 100:.2f}%, LGD={lgd_b1 * 100:.0f}%, R={corr_b1:.4f}")
    print(f"    K={irb_result_b1['k']:.6f}, MA={irb_result_b1['maturity_adjustment']:.4f}")
    print(f"    RWA=£{rwa_b1:,.0f} (effective RW={rw_b1 * 100:.1f}%)")
    return result_b1, pd_b1, lgd_b1, ead_b1, maturity_b1, corr_b1, irb_result_b1, rwa_b1, rw_b1


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario B2: Corporate with Financial Collateral

    **Input:** PD=1%, £500k cash collateral, EAD=£1m
    **Expected:** Adjusted LGD for collateralised portion
    """)
    return


@app.cell
def _(calculate_correlation, calculate_irb_rwa, ScenarioResult):
    # B2: Corporate with financial collateral
    pd_b2 = 0.01
    ead_b2 = 1_000_000.0
    collateral_b2 = 500_000.0  # Cash collateral

    # For F-IRB with financial collateral, LGD = 0% on covered portion
    covered_portion = collateral_b2 / ead_b2
    # Blended LGD: covered at 0%, uncovered at 45%
    lgd_b2 = 0.45 * (1 - covered_portion) + 0.00 * covered_portion  # = 22.5%

    corr_b2 = calculate_correlation(pd_b2, "CORPORATE")
    irb_result_b2 = calculate_irb_rwa(
        ead=ead_b2,
        pd=pd_b2,
        lgd=lgd_b2,
        correlation=corr_b2,
        maturity=2.5,
        exposure_class="CORPORATE",
    )

    rwa_b2 = irb_result_b2["rwa"]
    rw_b2 = rwa_b2 / ead_b2

    result_b2 = ScenarioResult(
        scenario_id="B2",
        scenario_group="B",
        description="Corporate with financial collateral (F-IRB)",
        exposure_reference="LOAN_FIRB_CORP_002",
        counterparty_reference="CORP_FIRB_002",
        approach="FIRB",
        exposure_class="CORPORATE",
        ead=ead_b2,
        risk_weight=rw_b2,
        rwa=rwa_b2,
        calculation_details={
            **irb_result_b2,
            "collateral_value": collateral_b2,
            "covered_portion": covered_portion,
            "blended_lgd": lgd_b2,
        },
        regulatory_reference="CRE32.9-12",
    )

    print(f"B2: Collateral=£{collateral_b2:,.0f}, Blended LGD={lgd_b2 * 100:.1f}%")
    print(f"    RWA=£{rwa_b2:,.0f} (effective RW={rw_b2 * 100:.1f}%)")
    return (
        result_b2,
        pd_b2,
        ead_b2,
        collateral_b2,
        covered_portion,
        lgd_b2,
        corr_b2,
        irb_result_b2,
        rwa_b2,
        rw_b2,
    )


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario B3: Corporate with Real Estate Collateral

    **Input:** PD=1%, £1m property (LTV 60%), EAD=£1m
    **Expected:** LGD=35% for RE-secured portion (F-IRB supervisory)
    """)
    return


@app.cell
def _(calculate_correlation, calculate_irb_rwa, FIRB_LGD, ScenarioResult):
    # B3: Corporate with real estate
    pd_b3 = 0.01
    ead_b3 = 1_000_000.0
    property_value_b3 = 1_000_000.0
    ltv_b3 = 0.60

    # F-IRB: LGD = 35% for CRE secured (with 140% haircut requirement)
    lgd_b3 = FIRB_LGD["commercial_re"]["senior"]  # 35%

    corr_b3 = calculate_correlation(pd_b3, "CORPORATE")
    irb_result_b3 = calculate_irb_rwa(
        ead=ead_b3,
        pd=pd_b3,
        lgd=lgd_b3,
        correlation=corr_b3,
        maturity=2.5,
        exposure_class="CORPORATE",
    )

    rwa_b3 = irb_result_b3["rwa"]
    rw_b3 = rwa_b3 / ead_b3

    result_b3 = ScenarioResult(
        scenario_id="B3",
        scenario_group="B",
        description="Corporate with real estate collateral (F-IRB)",
        exposure_reference="LOAN_FIRB_CORP_003",
        counterparty_reference="CORP_FIRB_003",
        approach="FIRB",
        exposure_class="CORPORATE",
        ead=ead_b3,
        risk_weight=rw_b3,
        rwa=rwa_b3,
        calculation_details={
            **irb_result_b3,
            "property_value": property_value_b3,
            "ltv": ltv_b3,
            "supervisory_lgd": lgd_b3,
        },
        regulatory_reference="CRE32.9-12",
    )

    print(
        f"B3: Property=£{property_value_b3:,.0f}, LTV={ltv_b3 * 100:.0f}%, LGD={lgd_b3 * 100:.0f}%"
    )
    print(f"    RWA=£{rwa_b3:,.0f} (effective RW={rw_b3 * 100:.1f}%)")
    return (
        result_b3,
        pd_b3,
        ead_b3,
        property_value_b3,
        ltv_b3,
        lgd_b3,
        corr_b3,
        irb_result_b3,
        rwa_b3,
        rw_b3,
    )


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario B4: Retail Mortgage

    **Input:** PD=0.5%, LGD=10%, EAD=£500k
    **Expected:** Use retail mortgage correlation (R=0.15 fixed)
    """)
    return


@app.cell
def _(calculate_correlation, calculate_irb_rwa, ScenarioResult):
    # B4: Retail mortgage
    pd_b4 = 0.005  # 0.5%
    lgd_b4 = 0.10  # 10% for mortgage
    ead_b4 = 500_000.0

    corr_b4 = calculate_correlation(pd_b4, "RETAIL_MORTGAGE")  # Fixed 0.15
    irb_result_b4 = calculate_irb_rwa(
        ead=ead_b4,
        pd=pd_b4,
        lgd=lgd_b4,
        correlation=corr_b4,
        maturity=2.5,  # Not used for retail
        exposure_class="RETAIL_MORTGAGE",
        apply_maturity_adjustment=False,  # No MA for retail
    )

    rwa_b4 = irb_result_b4["rwa"]
    rw_b4 = rwa_b4 / ead_b4

    result_b4 = ScenarioResult(
        scenario_id="B4",
        scenario_group="B",
        description="Retail mortgage (IRB)",
        exposure_reference="LOAN_IRB_MTG_001",
        counterparty_reference="RTL_IRB_MTG_001",
        approach="FIRB",
        exposure_class="RETAIL_MORTGAGE",
        ead=ead_b4,
        risk_weight=rw_b4,
        rwa=rwa_b4,
        calculation_details={
            **irb_result_b4,
            "correlation_type": "fixed",
            "no_maturity_adjustment": True,
        },
        regulatory_reference="CRE31.8",
    )

    print(f"B4: PD={pd_b4 * 100:.2f}%, LGD={lgd_b4 * 100:.0f}%, R={corr_b4:.2f} (fixed)")
    print(f"    RWA=£{rwa_b4:,.0f} (effective RW={rw_b4 * 100:.1f}%)")
    return result_b4, pd_b4, lgd_b4, ead_b4, corr_b4, irb_result_b4, rwa_b4, rw_b4


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario B5: QRRE (Qualifying Revolving Retail Exposure)

    **Input:** PD=0.5%, LGD=85%, EAD=£10k
    **Expected:** Use QRRE correlation (R=0.04 fixed)
    """)
    return


@app.cell
def _(calculate_correlation, calculate_irb_rwa, ScenarioResult):
    # B5: QRRE
    pd_b5 = 0.005  # 0.5%
    lgd_b5 = 0.85  # 85% for QRRE (unsecured revolving)
    ead_b5 = 10_000.0

    corr_b5 = calculate_correlation(pd_b5, "RETAIL_QRRE")  # Fixed 0.04
    irb_result_b5 = calculate_irb_rwa(
        ead=ead_b5,
        pd=pd_b5,
        lgd=lgd_b5,
        correlation=corr_b5,
        maturity=2.5,
        exposure_class="RETAIL_QRRE",
        apply_maturity_adjustment=False,
    )

    rwa_b5 = irb_result_b5["rwa"]
    rw_b5 = rwa_b5 / ead_b5

    result_b5 = ScenarioResult(
        scenario_id="B5",
        scenario_group="B",
        description="QRRE (IRB)",
        exposure_reference="LOAN_IRB_QRRE_001",
        counterparty_reference="RTL_IRB_QRRE_001",
        approach="FIRB",
        exposure_class="RETAIL_QRRE",
        ead=ead_b5,
        risk_weight=rw_b5,
        rwa=rwa_b5,
        calculation_details={
            **irb_result_b5,
            "correlation_type": "fixed",
        },
        regulatory_reference="CRE31.9",
    )

    print(f"B5: PD={pd_b5 * 100:.2f}%, LGD={lgd_b5 * 100:.0f}%, R={corr_b5:.2f} (fixed)")
    print(f"    RWA=£{rwa_b5:,.0f} (effective RW={rw_b5 * 100:.1f}%)")
    return result_b5, pd_b5, lgd_b5, ead_b5, corr_b5, irb_result_b5, rwa_b5, rw_b5


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario B6: PD Floor Test

    **Input:** Internal PD=0.01%, Floor=0.03% (corporate)
    **Expected:** Uses floored PD of 0.03%
    """)
    return


@app.cell
def _(calculate_correlation, calculate_irb_rwa, apply_pd_floor, PD_FLOORS, ScenarioResult):
    # B6: PD floor test
    pd_raw_b6 = 0.0001  # 0.01% (below floor)
    pd_floored_b6 = apply_pd_floor(pd_raw_b6, "CORPORATE")  # Should be 0.03%

    lgd_b6 = 0.45
    ead_b6 = 1_000_000.0

    corr_b6 = calculate_correlation(pd_floored_b6, "CORPORATE")
    irb_result_b6 = calculate_irb_rwa(
        ead=ead_b6,
        pd=pd_raw_b6,  # Will be floored internally
        lgd=lgd_b6,
        correlation=corr_b6,
        maturity=2.5,
        exposure_class="CORPORATE",
        apply_pd_floor_flag=True,
    )

    rwa_b6 = irb_result_b6["rwa"]
    rw_b6 = rwa_b6 / ead_b6

    result_b6 = ScenarioResult(
        scenario_id="B6",
        scenario_group="B",
        description="PD floor test (F-IRB)",
        exposure_reference="LOAN_FIRB_FLOOR_001",
        counterparty_reference="CORP_FIRB_FLOOR_001",
        approach="FIRB",
        exposure_class="CORPORATE",
        ead=ead_b6,
        risk_weight=rw_b6,
        rwa=rwa_b6,
        calculation_details={
            **irb_result_b6,
            "pd_raw": pd_raw_b6,
            "pd_floor": PD_FLOORS["CORPORATE"],
            "pd_used": pd_floored_b6,
            "floor_applied": True,
        },
        regulatory_reference="CRE31.6",
    )

    print(
        f"B6: Raw PD={pd_raw_b6 * 100:.3f}%, Floor={PD_FLOORS['CORPORATE'] * 100:.2f}%, Used PD={pd_floored_b6 * 100:.2f}%"
    )
    print(f"    RWA=£{rwa_b6:,.0f} (effective RW={rw_b6 * 100:.1f}%)")
    return (
        result_b6,
        pd_raw_b6,
        pd_floored_b6,
        lgd_b6,
        ead_b6,
        corr_b6,
        irb_result_b6,
        rwa_b6,
        rw_b6,
    )


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Summary: Group B Results
    """)
    return


@app.cell
def _(result_b1, result_b2, result_b3, result_b4, result_b5, result_b6, pl, mo):
    group_b_results = [result_b1, result_b2, result_b3, result_b4, result_b5, result_b6]

    summary_data_b = []
    for r in group_b_results:
        summary_data_b.append(
            {
                "Scenario": r.scenario_id,
                "Description": r.description,
                "EAD (£)": f"{r.ead:,.0f}",
                "Eff. RW": f"{r.risk_weight * 100:.1f}%",
                "RWA (£)": f"{r.rwa:,.0f}",
            }
        )

    summary_df_b = pl.DataFrame(summary_data_b)
    mo.ui.table(summary_df_b)
    return group_b_results, summary_data_b, summary_df_b


@app.cell
def _(group_b_results):
    def get_group_b_results():
        return group_b_results

    return (get_group_b_results,)


if __name__ == "__main__":
    app.run()
