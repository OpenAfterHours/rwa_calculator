"""
Group C: Advanced IRB (A-IRB) Scenarios

Scenarios C1-C3 covering A-IRB calculations with bank-estimated LGD.

Usage:
    uv run marimo edit workbooks/rwa_expected_outputs/scenarios/group_c_airb.py
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
        apply_lgd_floor,
        calculate_irb_rwa,
    )
    from workbooks.rwa_expected_outputs.data.fixture_loader import load_fixtures
    from workbooks.rwa_expected_outputs.data.regulatory_params import AIRB_LGD_FLOORS

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
        AIRB_LGD_FLOORS,
        calculate_irb_rwa,
        apply_lgd_floor,
        calculate_correlation,
        ScenarioResult,
    )


@app.cell
def _(mo):
    mo.md("""
    # Group C: Advanced IRB (A-IRB) Scenarios

    Scenarios C1-C3 demonstrate A-IRB calculations using bank-estimated LGD
    subject to regulatory floors.

    **Key Differences from F-IRB:**
    - Bank estimates own LGD (subject to floors)
    - LGD floors: 25% unsecured corporate, 5% residential RE, 10% commercial RE
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
    ## Scenario C1: Corporate Own LGD

    **Input:** PD=1%, own LGD=35%, M=2.5y, EAD=£1m
    **Expected:** Use bank's LGD estimate (above floor)
    """)
    return


@app.cell
def _(calculate_correlation, calculate_irb_rwa, ScenarioResult):
    # C1: Corporate own LGD (above floor)
    pd_c1 = 0.01
    lgd_own_c1 = 0.35  # Bank's estimate (above 25% floor)
    ead_c1 = 1_000_000.0

    corr_c1 = calculate_correlation(pd_c1, "CORPORATE")
    irb_result_c1 = calculate_irb_rwa(
        ead=ead_c1,
        pd=pd_c1,
        lgd=lgd_own_c1,
        correlation=corr_c1,
        maturity=2.5,
        exposure_class="CORPORATE",
    )

    rwa_c1 = irb_result_c1["rwa"]
    rw_c1 = rwa_c1 / ead_c1

    result_c1 = ScenarioResult(
        scenario_id="C1",
        scenario_group="C",
        description="Corporate own LGD (A-IRB)",
        exposure_reference="LOAN_AIRB_CORP_001",
        counterparty_reference="CORP_AIRB_001",
        approach="AIRB",
        exposure_class="CORPORATE",
        ead=ead_c1,
        risk_weight=rw_c1,
        rwa=rwa_c1,
        calculation_details={
            **irb_result_c1,
            "lgd_own_estimate": lgd_own_c1,
            "lgd_floor": 0.25,
            "floor_applied": False,
        },
        regulatory_reference="CRE32.20",
    )

    print(f"C1: PD={pd_c1 * 100:.2f}%, Own LGD={lgd_own_c1 * 100:.0f}%")
    print(f"    RWA=£{rwa_c1:,.0f} (effective RW={rw_c1 * 100:.1f}%)")
    return result_c1, pd_c1, lgd_own_c1, ead_c1, corr_c1, irb_result_c1, rwa_c1, rw_c1


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario C2: LGD Floor Test

    **Input:** Internal LGD=5%, Floor=25% (unsecured corporate)
    **Expected:** Uses floored LGD of 25%
    """)
    return


@app.cell
def _(calculate_correlation, calculate_irb_rwa, apply_lgd_floor, AIRB_LGD_FLOORS, ScenarioResult):
    # C2: LGD floor test
    pd_c2 = 0.01
    lgd_raw_c2 = 0.05  # Bank's estimate (below floor)
    lgd_floored_c2 = apply_lgd_floor(lgd_raw_c2, "unsecured", "CORPORATE")
    ead_c2 = 1_000_000.0

    corr_c2 = calculate_correlation(pd_c2, "CORPORATE")
    irb_result_c2 = calculate_irb_rwa(
        ead=ead_c2,
        pd=pd_c2,
        lgd=lgd_floored_c2,  # Use floored LGD
        correlation=corr_c2,
        maturity=2.5,
        exposure_class="CORPORATE",
    )

    rwa_c2 = irb_result_c2["rwa"]
    rw_c2 = rwa_c2 / ead_c2

    result_c2 = ScenarioResult(
        scenario_id="C2",
        scenario_group="C",
        description="LGD floor test (A-IRB)",
        exposure_reference="LOAN_AIRB_FLOOR_001",
        counterparty_reference="CORP_AIRB_FLOOR_001",
        approach="AIRB",
        exposure_class="CORPORATE",
        ead=ead_c2,
        risk_weight=rw_c2,
        rwa=rwa_c2,
        calculation_details={
            **irb_result_c2,
            "lgd_raw": lgd_raw_c2,
            "lgd_floor": AIRB_LGD_FLOORS["unsecured"],
            "lgd_used": lgd_floored_c2,
            "floor_applied": True,
        },
        regulatory_reference="CRE32.20",
    )

    print(
        f"C2: Raw LGD={lgd_raw_c2 * 100:.0f}%, Floor={AIRB_LGD_FLOORS['unsecured'] * 100:.0f}%, Used={lgd_floored_c2 * 100:.0f}%"
    )
    print(f"    RWA=£{rwa_c2:,.0f} (effective RW={rw_c2 * 100:.1f}%)")
    return (
        result_c2,
        pd_c2,
        lgd_raw_c2,
        lgd_floored_c2,
        ead_c2,
        corr_c2,
        irb_result_c2,
        rwa_c2,
        rw_c2,
    )


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario C3: Retail with Own Estimates

    **Input:** PD=0.3%, LGD=15%, EAD=£100k
    **Expected:** Retail correlation, no maturity adjustment
    """)
    return


@app.cell
def _(calculate_correlation, calculate_irb_rwa, ScenarioResult):
    # C3: Retail with own estimates
    pd_c3 = 0.003  # 0.3%
    lgd_c3 = 0.15  # 15%
    ead_c3 = 100_000.0

    corr_c3 = calculate_correlation(pd_c3, "RETAIL")
    irb_result_c3 = calculate_irb_rwa(
        ead=ead_c3,
        pd=pd_c3,
        lgd=lgd_c3,
        correlation=corr_c3,
        maturity=2.5,
        exposure_class="RETAIL",
        apply_maturity_adjustment=False,
    )

    rwa_c3 = irb_result_c3["rwa"]
    rw_c3 = rwa_c3 / ead_c3

    result_c3 = ScenarioResult(
        scenario_id="C3",
        scenario_group="C",
        description="Retail with own estimates (A-IRB)",
        exposure_reference="LOAN_AIRB_RTL_001",
        counterparty_reference="RTL_AIRB_001",
        approach="AIRB",
        exposure_class="RETAIL",
        ead=ead_c3,
        risk_weight=rw_c3,
        rwa=rwa_c3,
        calculation_details={
            **irb_result_c3,
            "correlation_type": "pd_dependent",
        },
        regulatory_reference="CRE31.8-9",
    )

    print(f"C3: PD={pd_c3 * 100:.2f}%, LGD={lgd_c3 * 100:.0f}%, R={corr_c3:.4f}")
    print(f"    RWA=£{rwa_c3:,.0f} (effective RW={rw_c3 * 100:.1f}%)")
    return result_c3, pd_c3, lgd_c3, ead_c3, corr_c3, irb_result_c3, rwa_c3, rw_c3


@app.cell
def _(mo):
    mo.md("---\n## Summary: Group C Results")
    return


@app.cell
def _(result_c1, result_c2, result_c3, pl, mo):
    group_c_results = [result_c1, result_c2, result_c3]

    summary_data_c = [
        {
            "Scenario": r.scenario_id,
            "Description": r.description,
            "EAD (£)": f"{r.ead:,.0f}",
            "Eff. RW": f"{r.risk_weight * 100:.1f}%",
            "RWA (£)": f"{r.rwa:,.0f}",
        }
        for r in group_c_results
    ]

    mo.ui.table(pl.DataFrame(summary_data_c))
    return group_c_results, summary_data_c


@app.cell
def _(group_c_results):
    def get_group_c_results():
        return group_c_results

    return (get_group_c_results,)


if __name__ == "__main__":
    app.run()
