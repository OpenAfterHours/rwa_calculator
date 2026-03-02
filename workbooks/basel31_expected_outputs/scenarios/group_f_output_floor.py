"""
Group F: Output Floor Scenarios

Scenarios F1-F3 covering Basel 3.1 output floor calculations.

Usage:
    uv run marimo edit workbooks/rwa_expected_outputs/scenarios/group_f_output_floor.py
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
    from workbooks.rwa_expected_outputs.data.regulatory_params import (
        OUTPUT_FLOOR_PERCENTAGE,
        OUTPUT_FLOOR_TRANSITIONAL,
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

    return mo, pl, Path, load_fixtures, OUTPUT_FLOOR_PERCENTAGE, OUTPUT_FLOOR_TRANSITIONAL, ScenarioResult


@app.cell
def _(mo, OUTPUT_FLOOR_PERCENTAGE, OUTPUT_FLOOR_TRANSITIONAL):
    mo.md(f"""
    # Group F: Output Floor Scenarios

    Basel 3.1 introduces an output floor that limits the benefit from IRB models.

    **Formula:** Final RWA = max(IRB RWA, Floor % × SA RWA)

    **Floor at full implementation:** {OUTPUT_FLOOR_PERCENTAGE*100:.1f}%

    **Transitional schedule:**
    | Year | Floor |
    |------|-------|
    | 2027 | {OUTPUT_FLOOR_TRANSITIONAL[2027]*100:.0f}% |
    | 2028 | {OUTPUT_FLOOR_TRANSITIONAL[2028]*100:.0f}% |
    | 2029 | {OUTPUT_FLOOR_TRANSITIONAL[2029]*100:.0f}% |
    | 2030 | {OUTPUT_FLOOR_TRANSITIONAL[2030]*100:.0f}% |
    | 2031 | {OUTPUT_FLOOR_TRANSITIONAL[2031]*100:.0f}% |
    | 2032+ | {OUTPUT_FLOOR_TRANSITIONAL[2032]*100:.1f}% |
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
    ## Scenario F1: Floor Binding

    **Input:** IRB RWA=£50m, SA RWA=£100m
    **Expected:** Floor (72.5% × £100m = £72.5m) > IRB, so use floor
    """)
    return


@app.cell
def _(OUTPUT_FLOOR_PERCENTAGE, ScenarioResult):
    # F1: Floor binding
    rwa_irb_f1 = 50_000_000.0
    rwa_sa_f1 = 100_000_000.0

    floor_f1 = OUTPUT_FLOOR_PERCENTAGE * rwa_sa_f1  # 72.5m
    rwa_final_f1 = max(rwa_irb_f1, floor_f1)
    floor_binding_f1 = floor_f1 > rwa_irb_f1

    result_f1 = ScenarioResult(
        scenario_id="F1",
        scenario_group="F",
        description="Output floor binding",
        exposure_reference="PORTFOLIO_IRB_001",
        counterparty_reference="PORTFOLIO",
        approach="IRB",
        exposure_class="PORTFOLIO",
        ead=0,  # Portfolio level
        risk_weight=0,  # N/A at portfolio level
        rwa=rwa_final_f1,
        calculation_details={
            "rwa_irb": rwa_irb_f1,
            "rwa_sa_equivalent": rwa_sa_f1,
            "floor_percentage": OUTPUT_FLOOR_PERCENTAGE,
            "floor_rwa": floor_f1,
            "rwa_final": rwa_final_f1,
            "is_floor_binding": floor_binding_f1,
            "floor_impact": floor_f1 - rwa_irb_f1 if floor_binding_f1 else 0,
            "formula": "RWA = max(IRB, 72.5% × SA)",
        },
        regulatory_reference="CRE99",
    )

    print(f"F1: IRB RWA=£{rwa_irb_f1/1e6:.1f}m, SA RWA=£{rwa_sa_f1/1e6:.1f}m")
    print(f"    Floor={OUTPUT_FLOOR_PERCENTAGE*100:.1f}% × SA = £{floor_f1/1e6:.1f}m")
    print(f"    Final RWA=£{rwa_final_f1/1e6:.1f}m (floor binding: {floor_binding_f1})")
    return result_f1, rwa_irb_f1, rwa_sa_f1, floor_f1, rwa_final_f1, floor_binding_f1


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario F2: Floor Not Binding

    **Input:** IRB RWA=£80m, SA RWA=£100m
    **Expected:** IRB (£80m) > Floor (£72.5m), so use IRB
    """)
    return


@app.cell
def _(OUTPUT_FLOOR_PERCENTAGE, ScenarioResult):
    # F2: Floor not binding
    rwa_irb_f2 = 80_000_000.0
    rwa_sa_f2 = 100_000_000.0

    floor_f2 = OUTPUT_FLOOR_PERCENTAGE * rwa_sa_f2
    rwa_final_f2 = max(rwa_irb_f2, floor_f2)
    floor_binding_f2 = floor_f2 > rwa_irb_f2

    result_f2 = ScenarioResult(
        scenario_id="F2",
        scenario_group="F",
        description="Output floor not binding",
        exposure_reference="PORTFOLIO_IRB_002",
        counterparty_reference="PORTFOLIO",
        approach="IRB",
        exposure_class="PORTFOLIO",
        ead=0,
        risk_weight=0,
        rwa=rwa_final_f2,
        calculation_details={
            "rwa_irb": rwa_irb_f2,
            "rwa_sa_equivalent": rwa_sa_f2,
            "floor_percentage": OUTPUT_FLOOR_PERCENTAGE,
            "floor_rwa": floor_f2,
            "rwa_final": rwa_final_f2,
            "is_floor_binding": floor_binding_f2,
            "floor_impact": 0,
            "formula": "RWA = max(IRB, 72.5% × SA)",
        },
        regulatory_reference="CRE99",
    )

    print(f"F2: IRB RWA=£{rwa_irb_f2/1e6:.1f}m, SA RWA=£{rwa_sa_f2/1e6:.1f}m")
    print(f"    Floor={OUTPUT_FLOOR_PERCENTAGE*100:.1f}% × SA = £{floor_f2/1e6:.1f}m")
    print(f"    Final RWA=£{rwa_final_f2/1e6:.1f}m (floor binding: {floor_binding_f2})")
    return result_f2, rwa_irb_f2, rwa_sa_f2, floor_f2, rwa_final_f2, floor_binding_f2


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario F3: Transitional Floor (2027)

    **Input:** IRB RWA=£50m, SA RWA=£100m, Year=2027
    **Expected:** Floor at 60% in 2027 = £60m
    """)
    return


@app.cell
def _(OUTPUT_FLOOR_TRANSITIONAL, ScenarioResult):
    # F3: Transitional floor (2027)
    rwa_irb_f3 = 50_000_000.0
    rwa_sa_f3 = 100_000_000.0
    year_f3 = 2027

    floor_pct_f3 = OUTPUT_FLOOR_TRANSITIONAL[year_f3]  # 50% (first year under PRA PS9/24)
    floor_f3 = floor_pct_f3 * rwa_sa_f3
    rwa_final_f3 = max(rwa_irb_f3, floor_f3)
    floor_binding_f3 = floor_f3 > rwa_irb_f3

    result_f3 = ScenarioResult(
        scenario_id="F3",
        scenario_group="F",
        description=f"Transitional floor ({year_f3})",
        exposure_reference="PORTFOLIO_IRB_003",
        counterparty_reference="PORTFOLIO",
        approach="IRB",
        exposure_class="PORTFOLIO",
        ead=0,
        risk_weight=0,
        rwa=rwa_final_f3,
        calculation_details={
            "rwa_irb": rwa_irb_f3,
            "rwa_sa_equivalent": rwa_sa_f3,
            "floor_percentage": floor_pct_f3,
            "reporting_year": year_f3,
            "floor_rwa": floor_f3,
            "rwa_final": rwa_final_f3,
            "is_floor_binding": floor_binding_f3,
            "transitional_schedule": OUTPUT_FLOOR_TRANSITIONAL,
        },
        regulatory_reference="CRE99, PRA PS9/24",
    )

    print(f"F3 ({year_f3}): IRB=£{rwa_irb_f3/1e6:.1f}m, SA=£{rwa_sa_f3/1e6:.1f}m")
    print(f"    Transitional floor={floor_pct_f3*100:.0f}% × SA = £{floor_f3/1e6:.1f}m")
    print(f"    Final RWA=£{rwa_final_f3/1e6:.1f}m")
    return result_f3, rwa_irb_f3, rwa_sa_f3, year_f3, floor_pct_f3, floor_f3, rwa_final_f3, floor_binding_f3


@app.cell
def _(mo):
    mo.md("---\n## Summary: Group F Results")
    return


@app.cell
def _(result_f1, result_f2, result_f3, pl, mo):
    group_f_results = [result_f1, result_f2, result_f3]

    summary_data_f = [{
        "Scenario": r.scenario_id,
        "Description": r.description,
        "IRB RWA": f"£{r.calculation_details['rwa_irb']/1e6:.1f}m",
        "SA RWA": f"£{r.calculation_details['rwa_sa_equivalent']/1e6:.1f}m",
        "Floor %": f"{r.calculation_details['floor_percentage']*100:.1f}%",
        "Final RWA": f"£{r.rwa/1e6:.1f}m",
        "Binding": r.calculation_details['is_floor_binding'],
    } for r in group_f_results]

    mo.ui.table(pl.DataFrame(summary_data_f))
    return group_f_results, summary_data_f


@app.cell
def _(group_f_results):
    def get_group_f_results():
        return group_f_results
    return (get_group_f_results,)


if __name__ == "__main__":
    app.run()
