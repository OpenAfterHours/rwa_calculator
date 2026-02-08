"""
CRR Expected Outputs Main Workbook

Orchestrates all CRR scenario calculations and exports expected outputs.
This workbook generates expected RWA values under the CRR (Basel 3.0) framework,
which is effective in the UK until 31 December 2026.

Usage:
    uv run marimo edit workbooks/crr_expected_outputs/main.py
    uv run marimo run workbooks/crr_expected_outputs/main.py --export-json

Key CRR Features:
    - SME supporting factor (0.7619) - Art. 501
    - Infrastructure supporting factor (0.75) - Art. 501a
    - No output floor
    - 35%/75% residential mortgage split at 80% LTV
    - Single PD floor (0.03%) for all exposure classes
    - No A-IRB LGD floors
"""

import marimo

__generated_with = "0.19.4"
app = marimo.App(width="medium")


@app.cell
def _():
    """Imports and setup."""
    import marimo as mo
    import polars as pl
    import sys
    import json
    from pathlib import Path
    from datetime import datetime
    from decimal import Decimal

    # Add project root to path
    project_root = Path(__file__).parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    return (
        Decimal,
        Path,
        datetime,
        json,
        mo,
        pl,
        project_root,
    )


@app.cell
def _(mo):
    """Header."""
    mo.md("""
    # CRR Expected Outputs Workbook

    This workbook generates expected RWA values under the **CRR (Capital Requirements Regulation)**
    framework, which is the current UK implementation of Basel 3.0.

    **Effective:** Until 31 December 2026 (Basel 3.1 takes effect 1 January 2027)

    ## Regulatory Framework Summary

    | Feature | CRR (Current) | Basel 3.1 (Future) |
    |---------|---------------|-------------------|
    | SME Supporting Factor | 0.7619 (Art. 501) | Not available |
    | Infrastructure Factor | 0.75 (Art. 501a) | Not available |
    | Output Floor | None | 72.5% |
    | Residential Mortgage | 35%/75% at 80% LTV | LTV bands (20%-70%) |
    | PD Floor | 0.03% (single) | 0.03%/0.05%/0.10% |
    | A-IRB LGD Floor | None | Varies by exposure |

    ## Scenario Groups

    - **CRR-A**: Standardised Approach (SA)
    - **CRR-B**: Foundation IRB (F-IRB)
    - **CRR-C**: Advanced IRB (A-IRB)
    - **CRR-D**: Credit Risk Mitigation (CRM)
    - **CRR-E**: Specialised Lending (Slotting)
    - **CRR-F**: Supporting Factors (SME/Infrastructure)
    - **CRR-G**: Provisions Treatment
    - **CRR-H**: Complex Scenarios
    """)
    return


@app.cell
def _(project_root):
    """Load scenario modules."""
    import importlib.util

    # Load SA scenarios
    sa_spec = importlib.util.spec_from_file_location(
        "group_crr_a_sa",
        project_root / "workbooks" / "crr_expected_outputs" / "scenarios" / "group_crr_a_sa.py"
    )
    if sa_spec and sa_spec.loader:
        group_crr_a_sa = importlib.util.module_from_spec(sa_spec)

    # Load F-IRB scenarios
    firb_spec = importlib.util.spec_from_file_location(
        "group_crr_b_firb",
        project_root / "workbooks" / "crr_expected_outputs" / "scenarios" / "group_crr_b_firb.py"
    )
    if firb_spec and firb_spec.loader:
        group_crr_b_firb = importlib.util.module_from_spec(firb_spec)

    return


@app.cell
def _(mo):
    """Group CRR-A Summary."""
    mo.md("""
    ---
    ## Group CRR-A: Standardised Approach Results

    The SA scenarios cover basic risk weight lookups including:
    - Sovereign exposures (0% for CQS 1)
    - Institution exposures (UK deviation: 30% for CQS 2)
    - Corporate exposures (rated and unrated)
    - Retail exposures (75%)
    - Residential mortgages (35%/75% split at 80% LTV)
    - Commercial real estate (50%/100%)
    - Off-balance sheet items (CCF application)
    - SME supporting factor (0.7619)

    **Key CRR difference:** Residential mortgages use simple 35%/75% split at 80% LTV,
    not the granular LTV bands in Basel 3.1.
    """)
    return


@app.cell
def _():
    """Placeholder for SA results when scenarios are run."""
    # In a full implementation, this would import and run the SA scenarios
    # For now, provide structure for expected output format

    crr_a_expected = [
        {"scenario_id": "CRR-A1", "exposure_class": "CENTRAL_GOVT_CENTRAL_BANK", "rw": 0.00, "sf": 1.0},
        {"scenario_id": "CRR-A2", "exposure_class": "CORPORATE", "rw": 1.00, "sf": 1.0},
        {"scenario_id": "CRR-A3", "exposure_class": "CORPORATE", "rw": 0.50, "sf": 1.0},
        {"scenario_id": "CRR-A4", "exposure_class": "INSTITUTION", "rw": 0.30, "sf": 1.0},
        {"scenario_id": "CRR-A5", "exposure_class": "RETAIL_MORTGAGE", "rw": 0.35, "sf": 1.0},
        {"scenario_id": "CRR-A6", "exposure_class": "RETAIL_MORTGAGE", "rw": 0.374, "sf": 1.0},
        {"scenario_id": "CRR-A7", "exposure_class": "CRE", "rw": 0.50, "sf": 1.0},
        {"scenario_id": "CRR-A8", "exposure_class": "CORPORATE", "rw": 1.00, "sf": 1.0},
        {"scenario_id": "CRR-A9", "exposure_class": "RETAIL", "rw": 0.75, "sf": 1.0},
        {"scenario_id": "CRR-A10", "exposure_class": "CORPORATE_SME", "rw": 1.00, "sf": 0.7619},
        {"scenario_id": "CRR-A11", "exposure_class": "RETAIL_SME", "rw": 0.75, "sf": 0.7619},
        {"scenario_id": "CRR-A12", "exposure_class": "CORPORATE", "rw": 1.00, "sf": 1.0},
    ]
    return (crr_a_expected,)


@app.cell
def _(mo):
    """Group CRR-B Summary."""
    mo.md("""
    ---
    ## Group CRR-B: Foundation IRB Results

    The F-IRB scenarios cover IRB calculations with supervisory LGD:
    - Corporate exposures (low and high PD)
    - Subordinated exposures (75% LGD)
    - Financial collateral (reduced LGD)
    - SME with correlation adjustment and supporting factor
    - PD floor binding cases (0.03%)
    - Retail IRB (no maturity adjustment)
    - Long maturity (5 year cap)

    **Key CRR differences:**
    - Single 0.03% PD floor (vs Basel 3.1 differentiated floors)
    - SME supporting factor (0.7619) available
    - No A-IRB LGD floors
    """)
    return


@app.cell
def _():
    """Placeholder for F-IRB results."""
    crr_b_expected = [
        {"scenario_id": "CRR-B1", "exposure_class": "CORPORATE", "approach": "F-IRB", "sf": 1.0},
        {"scenario_id": "CRR-B2", "exposure_class": "CORPORATE", "approach": "F-IRB", "sf": 1.0},
        {"scenario_id": "CRR-B3", "exposure_class": "CORPORATE_SUBORDINATED", "approach": "F-IRB", "sf": 1.0},
        {"scenario_id": "CRR-B4", "exposure_class": "CORPORATE_SECURED", "approach": "F-IRB", "sf": 1.0},
        {"scenario_id": "CRR-B5", "exposure_class": "CORPORATE_SME", "approach": "F-IRB", "sf": 0.7619},
        {"scenario_id": "CRR-B6", "exposure_class": "CORPORATE", "approach": "F-IRB", "sf": 1.0},
        {"scenario_id": "CRR-B7", "exposure_class": "RETAIL_OTHER", "approach": "F-IRB", "sf": 1.0},
        {"scenario_id": "CRR-B8", "exposure_class": "CORPORATE", "approach": "F-IRB", "sf": 1.0},
    ]
    return (crr_b_expected,)


@app.cell
def _(mo):
    """Export format section."""
    mo.md("""
    ---
    ## Expected Output Format

    The expected outputs are structured for use in acceptance testing:

    ```json
    {
        "framework": "CRR",
        "version": "1.0",
        "generated_at": "2024-XX-XX",
        "scenarios": [
            {
                "scenario_id": "CRR-A1",
                "scenario_group": "CRR-A",
                "description": "UK Sovereign exposure - 0% RW",
                "approach": "SA",
                "exposure_class": "CENTRAL_GOVT_CENTRAL_BANK",
                "inputs": {
                    "ead": 1000000,
                    "cqs": 1
                },
                "outputs": {
                    "risk_weight": 0.00,
                    "rwa_before_sf": 0,
                    "supporting_factor": 1.0,
                    "rwa_after_sf": 0
                },
                "regulatory_reference": "CRR Art. 114"
            }
        ]
    }
    ```
    """)
    return


@app.cell
def _(Decimal, datetime, json):
    """Generate expected output structure."""

    def decimal_default(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        raise TypeError

    def generate_expected_outputs():
        """Generate the full expected outputs structure."""
        return {
            "framework": "CRR",
            "version": "1.0",
            "effective_until": "2026-12-31",
            "generated_at": datetime.now().isoformat(),
            "regulatory_references": {
                "primary": "UK CRR (Regulation (EU) No 575/2013 as retained)",
                "supporting_factors": "CRR Art. 501 (SME), Art. 501a (Infrastructure)",
                "sa_risk_weights": "CRR Art. 112-134",
                "irb_approach": "CRR Art. 142-191",
            },
            "key_differences_from_basel31": [
                "SME supporting factor (0.7619) available under CRR",
                "Infrastructure supporting factor (0.75) available under CRR",
                "No output floor under CRR",
                "Residential mortgage: 35%/75% split at 80% LTV (vs granular LTV bands)",
                "Single PD floor 0.03% for all classes (vs differentiated floors)",
                "No A-IRB LGD floors under CRR",
            ],
            "scenario_groups": {
                "CRR-A": "Standardised Approach",
                "CRR-B": "Foundation IRB",
                "CRR-C": "Advanced IRB",
                "CRR-D": "Credit Risk Mitigation",
                "CRR-E": "Specialised Lending",
                "CRR-F": "Supporting Factors",
                "CRR-G": "Provisions",
                "CRR-H": "Complex Scenarios",
            },
        }

    def export_to_json(data, filepath):
        """Export data to JSON file."""
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=decimal_default)
        return filepath

    return (export_to_json, generate_expected_outputs,)


@app.cell
def _(generate_expected_outputs, mo):
    """Display metadata."""
    metadata = generate_expected_outputs()
    mo.md(f"""
    ### Framework Metadata

    - **Framework:** {metadata['framework']}
    - **Version:** {metadata['version']}
    - **Effective Until:** {metadata['effective_until']}
    - **Generated:** {metadata['generated_at'][:10]}

    ### Key CRR vs Basel 3.1 Differences

    {"".join([f"- {diff}" + chr(10) for diff in metadata['key_differences_from_basel31']])}
    """)
    return (metadata,)


@app.cell
def _(crr_a_expected, crr_b_expected, mo, pl):
    """Summary of all scenarios."""
    all_scenarios = crr_a_expected + crr_b_expected

    summary = pl.DataFrame([
        {
            "Group": s["scenario_id"][:6],
            "Scenario": s["scenario_id"],
            "Exposure Class": s["exposure_class"],
            "Approach": s.get("approach", "SA"),
            "SF Applied": "Yes" if s["sf"] != 1.0 else "No",
        }
        for s in all_scenarios
    ])

    mo.md("### Scenario Summary")
    mo.ui.table(summary)
    return (all_scenarios,)


@app.cell
def _(mo):
    """Usage instructions."""
    mo.md("""
    ---
    ## Usage Instructions

    ### Running the Workbook

    ```bash
    # Interactive mode
    uv run marimo edit workbooks/crr_expected_outputs/main.py

    # Run and export
    uv run marimo run workbooks/crr_expected_outputs/main.py
    ```

    ### Individual Scenario Groups

    ```bash
    # SA scenarios
    uv run marimo edit workbooks/crr_expected_outputs/scenarios/group_crr_a_sa.py

    # F-IRB scenarios
    uv run marimo edit workbooks/crr_expected_outputs/scenarios/group_crr_b_firb.py
    ```

    ### Using Expected Outputs in Tests

    ```python
    from workbooks.crr_expected_outputs.data import load_expected_outputs

    expected = load_expected_outputs()
    scenario_a1 = expected.get_scenario("CRR-A1")

    assert calculated_rwa == scenario_a1["outputs"]["rwa_after_sf"]
    ```
    """)
    return


if __name__ == "__main__":
    app.run()
