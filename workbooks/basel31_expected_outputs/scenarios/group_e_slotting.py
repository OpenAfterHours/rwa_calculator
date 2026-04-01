"""
Group E: Specialised Lending (Slotting) Scenarios

Scenarios E1-E4 covering slotting approach for specialised lending.

Usage:
    uv run marimo edit workbooks/rwa_expected_outputs/scenarios/group_e_slotting.py
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

    from workbooks.rwa_expected_outputs.calculations.sa_risk_weights import (
        calculate_sa_rwa,
        get_slotting_risk_weight,
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

    return mo, pl, Path, load_fixtures, get_slotting_risk_weight, calculate_sa_rwa, ScenarioResult


@app.cell
def _(mo):
    mo.md("""
    # Group E: Specialised Lending (Slotting) Scenarios

    Scenarios E1-E4 demonstrate slotting approach for:
    - Project finance
    - Income-producing real estate (IPRE)
    - High-volatility commercial real estate (HVCRE)
    - Object finance

    **Slotting Risk Weights (CRE33.5):**
    | Category | RW | RW (<2.5yr) |
    |----------|-----|-------------|
    | Strong | 70% | 50% |
    | Good | 90% | 70% |
    | Satisfactory | 115% | 115% |
    | Weak | 250% | 250% |
    | Default | 0% | 0% |

    HVCRE: Apply 1.25x multiplier to base RW
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
    ## Scenario E1: Project Finance - Strong

    **Input:** £10m project finance, Strong category
    **Expected:** 70% RW, £7m RWA
    """)
    return


@app.cell
def _(get_slotting_risk_weight, calculate_sa_rwa, ScenarioResult):
    # E1: Project Finance - Strong
    ead_e1 = 10_000_000.0
    category_e1 = "strong"
    maturity_e1 = 5.0  # > 2.5 years

    rw_e1 = get_slotting_risk_weight(category_e1, maturity_e1, is_hvcre=False)
    rwa_e1 = calculate_sa_rwa(ead_e1, rw_e1)

    result_e1 = ScenarioResult(
        scenario_id="E1",
        scenario_group="E",
        description="Project finance - Strong",
        exposure_reference="SL_PF_001",
        counterparty_reference="SPV_PF_001",
        approach="SLOTTING",
        exposure_class="SPECIALISED_LENDING",
        ead=ead_e1,
        risk_weight=rw_e1,
        rwa=rwa_e1,
        calculation_details={
            "sl_type": "project_finance",
            "slotting_category": category_e1,
            "remaining_maturity": maturity_e1,
            "is_hvcre": False,
        },
        regulatory_reference="CRE33.5",
    )

    print(f"E1: PF Strong, EAD=£{ead_e1:,.0f}, RW={rw_e1 * 100:.0f}%, RWA=£{rwa_e1:,.0f}")
    return result_e1, ead_e1, category_e1, maturity_e1, rw_e1, rwa_e1


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario E2: Project Finance - Good

    **Input:** £10m project finance, Good category
    **Expected:** 90% RW, £9m RWA
    """)
    return


@app.cell
def _(get_slotting_risk_weight, calculate_sa_rwa, ScenarioResult):
    # E2: Project Finance - Good
    ead_e2 = 10_000_000.0
    category_e2 = "good"
    maturity_e2 = 5.0

    rw_e2 = get_slotting_risk_weight(category_e2, maturity_e2, is_hvcre=False)
    rwa_e2 = calculate_sa_rwa(ead_e2, rw_e2)

    result_e2 = ScenarioResult(
        scenario_id="E2",
        scenario_group="E",
        description="Project finance - Good",
        exposure_reference="SL_PF_002",
        counterparty_reference="SPV_PF_002",
        approach="SLOTTING",
        exposure_class="SPECIALISED_LENDING",
        ead=ead_e2,
        risk_weight=rw_e2,
        rwa=rwa_e2,
        calculation_details={
            "sl_type": "project_finance",
            "slotting_category": category_e2,
            "remaining_maturity": maturity_e2,
            "is_hvcre": False,
        },
        regulatory_reference="CRE33.5",
    )

    print(f"E2: PF Good, EAD=£{ead_e2:,.0f}, RW={rw_e2 * 100:.0f}%, RWA=£{rwa_e2:,.0f}")
    return result_e2, ead_e2, category_e2, maturity_e2, rw_e2, rwa_e2


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario E3: IPRE - Satisfactory

    **Input:** £5m income-producing RE, Satisfactory category
    **Expected:** 115% RW, £5.75m RWA
    """)
    return


@app.cell
def _(get_slotting_risk_weight, calculate_sa_rwa, ScenarioResult):
    # E3: IPRE - Satisfactory
    ead_e3 = 5_000_000.0
    category_e3 = "satisfactory"
    maturity_e3 = 5.0

    rw_e3 = get_slotting_risk_weight(category_e3, maturity_e3, is_hvcre=False)
    rwa_e3 = calculate_sa_rwa(ead_e3, rw_e3)

    result_e3 = ScenarioResult(
        scenario_id="E3",
        scenario_group="E",
        description="IPRE - Satisfactory",
        exposure_reference="SL_IPRE_001",
        counterparty_reference="SPV_IPRE_001",
        approach="SLOTTING",
        exposure_class="SPECIALISED_LENDING",
        ead=ead_e3,
        risk_weight=rw_e3,
        rwa=rwa_e3,
        calculation_details={
            "sl_type": "ipre",
            "slotting_category": category_e3,
            "remaining_maturity": maturity_e3,
            "is_hvcre": False,
        },
        regulatory_reference="CRE33.5",
    )

    print(f"E3: IPRE Satisfactory, EAD=£{ead_e3:,.0f}, RW={rw_e3 * 100:.0f}%, RWA=£{rwa_e3:,.0f}")
    return result_e3, ead_e3, category_e3, maturity_e3, rw_e3, rwa_e3


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario E4: HVCRE - Good

    **Input:** £5m high-volatility CRE, Good category
    **Expected:** 90% × 1.25 = 112.5% RW
    """)
    return


@app.cell
def _(get_slotting_risk_weight, calculate_sa_rwa, ScenarioResult):
    # E4: HVCRE - Good
    ead_e4 = 5_000_000.0
    category_e4 = "good"
    maturity_e4 = 5.0

    rw_e4 = get_slotting_risk_weight(category_e4, maturity_e4, is_hvcre=True)
    rwa_e4 = calculate_sa_rwa(ead_e4, rw_e4)

    result_e4 = ScenarioResult(
        scenario_id="E4",
        scenario_group="E",
        description="HVCRE - Good",
        exposure_reference="SL_HVCRE_001",
        counterparty_reference="SPV_HVCRE_001",
        approach="SLOTTING",
        exposure_class="SPECIALISED_LENDING",
        ead=ead_e4,
        risk_weight=rw_e4,
        rwa=rwa_e4,
        calculation_details={
            "sl_type": "hvcre",
            "slotting_category": category_e4,
            "remaining_maturity": maturity_e4,
            "is_hvcre": True,
            "hvcre_multiplier": 1.25,
            "base_rw": 0.90,
        },
        regulatory_reference="CRE33.5-6",
    )

    print(f"E4: HVCRE Good, EAD=£{ead_e4:,.0f}, RW={rw_e4 * 100:.1f}%, RWA=£{rwa_e4:,.0f}")
    return result_e4, ead_e4, category_e4, maturity_e4, rw_e4, rwa_e4


@app.cell
def _(mo):
    mo.md("---\n## Summary: Group E Results")
    return


@app.cell
def _(result_e1, result_e2, result_e3, result_e4, pl, mo):
    group_e_results = [result_e1, result_e2, result_e3, result_e4]

    summary_data_e = [
        {
            "Scenario": r.scenario_id,
            "Description": r.description,
            "EAD (£)": f"{r.ead:,.0f}",
            "RW": f"{r.risk_weight * 100:.1f}%",
            "RWA (£)": f"{r.rwa:,.0f}",
        }
        for r in group_e_results
    ]

    mo.ui.table(pl.DataFrame(summary_data_e))
    return group_e_results, summary_data_e


@app.cell
def _(group_e_results):
    def get_group_e_results():
        return group_e_results

    return (get_group_e_results,)


if __name__ == "__main__":
    app.run()
