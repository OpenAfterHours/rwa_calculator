"""
RWA Expected Outputs - Main Orchestrator

This workbook consolidates all scenario groups (A-H) and generates
expected output files for pytest consumption.

Usage:
    # Interactive editing
    uv run marimo edit workbooks/rwa_expected_outputs/main.py

    # Generate outputs (non-interactive)
    uv run marimo run workbooks/rwa_expected_outputs/main.py
"""

import marimo

__generated_with = "0.19.4"
app = marimo.App(width="full")


@app.cell
def _():
    """Imports and setup."""
    import marimo as mo
    import polars as pl
    import json
    import sys
    from pathlib import Path
    from datetime import datetime
    from dataclasses import dataclass, asdict
    from typing import Any

    project_root = Path(__file__).parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    return Any, Path, asdict, dataclass, datetime, json, mo, pl, project_root


@app.cell
def _(mo):
    """Header and documentation."""
    mo.md("""
    # RWA Expected Outputs Generator

    This workbook calculates and exports expected RWA values for all 40+ acceptance test scenarios.

    **Scenario Groups:**
    | Group | Description | Scenarios | Count |
    |-------|-------------|-----------|-------|
    | A | Standardised Approach | A1-A10 | 10 |
    | B | Foundation IRB | B1-B6 | 6 |
    | C | Advanced IRB | C1-C3 | 3 |
    | D | Credit Risk Mitigation | D1-D6 | 6 |
    | E | Specialised Lending | E1-E4 | 4 |
    | F | Output Floor | F1-F3 | 3 |
    | G | Provisions | G1-G3 | 3 |
    | H | Complex/Combined | H1-H4 | 4 |
    | **Total** | | | **39** |

    **Outputs:**
    - `tests/expected_outputs/expected_rwa.parquet` - Polars DataFrame format
    - `tests/expected_outputs/expected_rwa.json` - JSON format for pytest fixtures
    """)
    return


@app.cell
def _(Path, project_root):
    """Define paths."""
    scenarios_path = Path(__file__).parent / "scenarios"
    output_path = project_root / "tests" / "expected_outputs" / "basel31"
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Scenarios path: {scenarios_path}")
    print(f"Output path: {output_path}")
    return (output_path,)


@app.cell
def _(mo):
    """Load scenario modules header."""
    mo.md("---\n## Loading Scenario Groups")
    return


@app.cell
def _(Any, asdict, dataclass):
    """Import all scenario results."""
    # from dataclasses import dataclass, asdict
    # from typing import Any

    @dataclass
    class ScenarioResult:
        """Container for a single scenario calculation result."""
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
    return (ScenarioResult,)


@app.cell
def _(ScenarioResult):
    """Create all scenario results inline (standalone mode)."""

    # Group A: SA Scenarios
    group_a = [
        ScenarioResult("A1", "A", "UK Sovereign - 0% RW", "LOAN_SOV_UK_001", "SOV_UK_001", "SA", "CENTRAL_GOVT_CENTRAL_BANK", 1000000, 0.00, 0, {"cqs": 1}, "CRE20.7"),
        ScenarioResult("A2", "A", "Unrated corporate - 100% RW", "LOAN_CORP_UR_001", "CORP_UR_001", "SA", "CORPORATE", 1000000, 1.00, 1000000, {"cqs": 0}, "CRE20.26"),
        ScenarioResult("A3", "A", "Rated corporate CQS 2 - 50% RW", "LOAN_CORP_UK_003", "CORP_UK_003", "SA", "CORPORATE", 1000000, 0.50, 500000, {"cqs": 2}, "CRE20.25"),
        ScenarioResult("A4", "A", "UK Institution CQS 2 - 30% RW", "LOAN_INST_UK_003", "INST_UK_003", "SA", "INSTITUTION", 1000000, 0.30, 300000, {"cqs": 2, "uk_deviation": True}, "CRE20.16"),
        ScenarioResult("A5", "A", "Residential mortgage 60% LTV - 20% RW", "LOAN_RTL_MTG_001", "RTL_MTG_001", "SA", "RETAIL_MORTGAGE", 500000, 0.20, 100000, {"ltv": 0.60}, "CRE20.71"),
        ScenarioResult("A6", "A", "Residential mortgage 85% LTV - 35% RW", "LOAN_RTL_MTG_002", "RTL_MTG_002", "SA", "RETAIL_MORTGAGE", 850000, 0.35, 297500, {"ltv": 0.85}, "CRE20.71"),
        ScenarioResult("A7", "A", "Commercial RE 60% LTV - 60% RW", "LOAN_CRE_001", "CORP_CRE_001", "SA", "CRE", 600000, 0.60, 360000, {"ltv": 0.60}, "CRE20.83"),
        ScenarioResult("A8", "A", "Off-balance sheet - 40% CCF", "CONT_CCF_001", "CORP_OBS_001", "SA", "CORPORATE", 400000, 1.00, 400000, {"ccf": 0.40, "nominal": 1000000}, "CRE20.96"),
        ScenarioResult("A9", "A", "Retail exposure - 75% RW", "LOAN_RTL_IND_001", "RTL_IND_001", "SA", "RETAIL", 50000, 0.75, 37500, {}, "CRE20.66"),
        ScenarioResult("A10", "A", "SME retail - 75% RW", "LOAN_RTL_SME_001", "RTL_SME_001", "SA", "RETAIL_SME", 500000, 0.75, 375000, {"sme": True}, "CRE20.66"),
    ]

    # Group B: F-IRB Scenarios (with calculated values)
    group_b = [
        ScenarioResult("B1", "B", "Corporate unsecured F-IRB", "LOAN_FIRB_CORP_001", "CORP_FIRB_001", "FIRB", "CORPORATE", 1000000, 0.8234, 823400, {"pd": 0.01, "lgd": 0.45}, "CRE31-32"),
        ScenarioResult("B2", "B", "Corporate with financial collateral", "LOAN_FIRB_CORP_002", "CORP_FIRB_002", "FIRB", "CORPORATE", 1000000, 0.4117, 411700, {"pd": 0.01, "lgd": 0.225}, "CRE32.9-12"),
        ScenarioResult("B3", "B", "Corporate with RE collateral", "LOAN_FIRB_CORP_003", "CORP_FIRB_003", "FIRB", "CORPORATE", 1000000, 0.6404, 640400, {"pd": 0.01, "lgd": 0.35}, "CRE32.9-12"),
        ScenarioResult("B4", "B", "Retail mortgage IRB", "LOAN_IRB_MTG_001", "RTL_IRB_MTG_001", "FIRB", "RETAIL_MORTGAGE", 500000, 0.0686, 34300, {"pd": 0.005, "lgd": 0.10, "r": 0.15}, "CRE31.8"),
        ScenarioResult("B5", "B", "QRRE IRB", "LOAN_IRB_QRRE_001", "RTL_IRB_QRRE_001", "FIRB", "RETAIL_QRRE", 10000, 0.4752, 4752, {"pd": 0.005, "lgd": 0.85, "r": 0.04}, "CRE31.9"),
        ScenarioResult("B6", "B", "PD floor test", "LOAN_FIRB_FLOOR_001", "CORP_FIRB_FLOOR_001", "FIRB", "CORPORATE", 1000000, 0.4948, 494800, {"pd_raw": 0.0001, "pd_floor": 0.0003}, "CRE31.6"),
    ]

    # Group C: A-IRB Scenarios
    group_c = [
        ScenarioResult("C1", "C", "Corporate own LGD A-IRB", "LOAN_AIRB_CORP_001", "CORP_AIRB_001", "AIRB", "CORPORATE", 1000000, 0.6404, 640400, {"pd": 0.01, "lgd": 0.35}, "CRE32.20"),
        ScenarioResult("C2", "C", "LGD floor test", "LOAN_AIRB_FLOOR_001", "CORP_AIRB_FLOOR_001", "AIRB", "CORPORATE", 1000000, 0.4573, 457300, {"lgd_raw": 0.05, "lgd_floor": 0.25}, "CRE32.20"),
        ScenarioResult("C3", "C", "Retail own estimates", "LOAN_AIRB_RTL_001", "RTL_AIRB_001", "AIRB", "RETAIL", 100000, 0.0716, 7160, {"pd": 0.003, "lgd": 0.15}, "CRE31.8-9"),
    ]

    # Group D: CRM Scenarios
    group_d = [
        ScenarioResult("D1", "D", "Cash collateral", "LOAN_CRM_D1_001", "CORP_CRM_D1_001", "SA", "CORPORATE", 500000, 1.00, 500000, {"collateral": 500000, "haircut": 0}, "CRE22.52"),
        ScenarioResult("D2", "D", "Govt bond collateral", "LOAN_CRM_D2_001", "CORP_CRM_D2_001", "SA", "CORPORATE", 412000, 1.00, 412000, {"collateral": 600000, "haircut": 0.02}, "CRE22.52-53"),
        ScenarioResult("D3", "D", "Equity collateral", "LOAN_CRM_D3_001", "CORP_CRM_D3_001", "SA", "CORPORATE", 700000, 1.00, 700000, {"collateral": 400000, "haircut": 0.25}, "CRE22.52"),
        ScenarioResult("D4", "D", "Guarantee substitution", "LOAN_CRM_D4_001", "CORP_CRM_D4_001", "SA", "CORPORATE", 1000000, 0.52, 520000, {"guarantee": 600000, "guarantor_rw": 0.20}, "CRE22.70-71"),
        ScenarioResult("D5", "D", "Maturity mismatch", "LOAN_CRM_D5_001", "CORP_CRM_D5_001", "SA", "CORPORATE", 815789, 1.00, 815789, {"mat_adj": 0.368}, "CRE22.65-66"),
        ScenarioResult("D6", "D", "Currency mismatch", "LOAN_CRM_D6_001", "CORP_CRM_D6_001", "SA", "CORPORATE", 540000, 1.00, 540000, {"fx_haircut": 0.08}, "CRE22.54"),
    ]

    # Group E: Slotting Scenarios
    group_e = [
        ScenarioResult("E1", "E", "Project finance - Strong", "SL_PF_001", "SPV_PF_001", "SLOTTING", "SPECIALISED_LENDING", 10000000, 0.70, 7000000, {"category": "strong"}, "CRE33.5"),
        ScenarioResult("E2", "E", "Project finance - Good", "SL_PF_002", "SPV_PF_002", "SLOTTING", "SPECIALISED_LENDING", 10000000, 0.90, 9000000, {"category": "good"}, "CRE33.5"),
        ScenarioResult("E3", "E", "IPRE - Satisfactory", "SL_IPRE_001", "SPV_IPRE_001", "SLOTTING", "SPECIALISED_LENDING", 5000000, 1.15, 5750000, {"category": "satisfactory"}, "CRE33.5"),
        ScenarioResult("E4", "E", "HVCRE - Good", "SL_HVCRE_001", "SPV_HVCRE_001", "SLOTTING", "SPECIALISED_LENDING", 5000000, 1.125, 5625000, {"category": "good", "hvcre": True}, "CRE33.5-6"),
    ]

    # Group F: Output Floor Scenarios
    group_f = [
        ScenarioResult("F1", "F", "Output floor binding", "PORTFOLIO_IRB_001", "PORTFOLIO", "IRB", "PORTFOLIO", 0, 0, 72500000, {"irb_rwa": 50000000, "sa_rwa": 100000000, "floor_pct": 0.725}, "CRE99"),
        ScenarioResult("F2", "F", "Output floor not binding", "PORTFOLIO_IRB_002", "PORTFOLIO", "IRB", "PORTFOLIO", 0, 0, 80000000, {"irb_rwa": 80000000, "sa_rwa": 100000000, "floor_pct": 0.725}, "CRE99"),
        ScenarioResult("F3", "F", "Transitional floor 2027", "PORTFOLIO_IRB_003", "PORTFOLIO", "IRB", "PORTFOLIO", 0, 0, 60000000, {"irb_rwa": 50000000, "sa_rwa": 100000000, "floor_pct": 0.60}, "CRE99"),
    ]

    # Group G: Provision Scenarios
    group_g = [
        ScenarioResult("G1", "G", "SA with SCRA", "LOAN_PROV_G1_001", "CORP_PROV_G1_001", "SA", "CORPORATE", 950000, 1.00, 950000, {"provision": 50000}, "CRR Art 111"),
        ScenarioResult("G2", "G", "IRB Stage 1", "LOAN_PROV_G2_001", "CORP_PROV_G2_001", "FIRB", "CORPORATE", 1000000, 0.8234, 823400, {"el": 4500, "provision": 10000}, "CRE35.1-3"),
        ScenarioResult("G3", "G", "IRB Stage 3 defaulted", "LOAN_PROV_G3_001", "CORP_DF_PROV_001", "FIRB", "DEFAULTED", 1000000, 0.0625, 62500, {"el": 450000, "provision": 400000}, "CRE35.4"),
    ]

    # Group H: Complex Scenarios
    group_h = [
        ScenarioResult("H1", "H", "Facility with multiple loans", "FAC_HIER_001", "CORP_GRP1_PARENT", "SA", "CORPORATE", 4500000, 0.50, 2250000, {"loans": 3}, "CRR Art 166"),
        ScenarioResult("H2", "H", "Counterparty group", "GROUP_ORG_001", "CORP_GRP1_PARENT", "SA", "CORPORATE", 3500000, 0.50, 1750000, {"entities": 3, "inheritance": True}, "CRR Art 122"),
        ScenarioResult("H3", "H", "Mixed approach portfolio", "PORTFOLIO_MIXED", "PORTFOLIO", "MIXED", "PORTFOLIO", 20000000, 0.3555, 7110000, {"sa_rwa": 6500000, "irb_rwa": 4100000}, "CRR Art 150"),
        ScenarioResult("H4", "H", "Full CRM chain", "LOAN_FAC_CORP_002_A", "CORP_UK_002", "SA", "CORPORATE", 18000000, 0.2889, 5200000, {"collateral": 10000000, "guarantee": 15000000, "provision": 1000000}, "CRE22"),
    ]

    all_results = group_a + group_b + group_c + group_d + group_e + group_f + group_g + group_h

    print(f"Total scenarios: {len(all_results)}")
    return (all_results,)


@app.cell
def _(all_results, mo, pl):
    """Display summary table."""
    mo.md("---\n## All Scenarios Summary")

    summary_df = pl.DataFrame([{
        "ID": r.scenario_id,
        "Group": r.scenario_group,
        "Description": r.description,
        "Approach": r.approach,
        "EAD": r.ead,
        "RW": f"{r.risk_weight*100:.1f}%",
        "RWA": r.rwa,
        "Ref": r.regulatory_reference,
    } for r in all_results])

    mo.ui.table(summary_df)
    return


@app.cell
def _(mo):
    """Export section header."""
    mo.md("---\n## Export Outputs")
    return


@app.cell
def _(all_results, datetime, json, output_path, pl):
    """Export to parquet and JSON."""

    # Convert to records for export
    records = []
    for r in all_results:
        records.append({
            "scenario_id": r.scenario_id,
            "scenario_group": r.scenario_group,
            "description": r.description,
            "exposure_reference": r.exposure_reference,
            "counterparty_reference": r.counterparty_reference,
            "approach": r.approach,
            "exposure_class": r.exposure_class,
            "ead": r.ead,
            "risk_weight": r.risk_weight,
            "rwa": r.rwa,
            "calculation_details": json.dumps(r.calculation_details),
            "regulatory_reference": r.regulatory_reference,
        })

    # Create DataFrame
    output_df = pl.DataFrame(records)

    # Export to parquet
    parquet_path = output_path / "expected_rwa.parquet"
    output_df.write_parquet(parquet_path)
    print(f"Exported parquet: {parquet_path}")

    # Export to JSON
    json_path = output_path / "expected_rwa.json"
    json_output = {
        "generated_at": datetime.now().isoformat(),
        "scenario_count": len(all_results),
        "scenarios": [r.to_dict() for r in all_results],
    }
    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2)
    print(f"Exported JSON: {json_path}")
    return


@app.cell
def _(all_results, mo, pl, total_ead, total_rwa):
    """Summary statistics."""
    mo.md("---\n## Summary Statistics")

    # By group
    group_stats = []
    for g in ["A", "B", "C", "D", "E", "F", "G", "H"]:
        group_scenarios = [r for r in all_results if r.scenario_group == g]
        total_summary_ead = sum(r.ead for r in group_scenarios)
        total_summary_rwa = sum(r.rwa for r in group_scenarios)
        group_stats.append({
            "Group": g,
            "Scenarios": len(group_scenarios),
            "Total EAD": f"£{total_ead:,.0f}",
            "Total RWA": f"£{total_rwa:,.0f}",
        })

    stats_df = pl.DataFrame(group_stats)
    mo.ui.table(stats_df)
    return


@app.cell
def _(all_results):
    """Final summary."""
    total_scenarios = len(all_results)
    total_ead = sum(r.ead for r in all_results)
    total_rwa = sum(r.rwa for r in all_results)

    print(f"\n{'='*50}")
    print(f"GENERATION COMPLETE")
    print(f"{'='*50}")
    print(f"Total scenarios: {total_scenarios}")
    print(f"Total EAD: £{total_ead:,.0f}")
    print(f"Total RWA: £{total_rwa:,.0f}")
    print(f"Average RW: {(total_rwa/total_ead)*100:.1f}%" if total_ead > 0 else "N/A")
    return total_ead, total_rwa


if __name__ == "__main__":
    app.run()
