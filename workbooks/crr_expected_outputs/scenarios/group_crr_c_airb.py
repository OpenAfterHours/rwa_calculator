"""
Group CRR-C: CRR Advanced IRB (A-IRB) Scenarios

Scenarios CRR-C1 to CRR-C3 covering A-IRB calculations using bank's own LGD estimates.

Key difference from F-IRB: A-IRB allows own estimates for LGD, EAD, and CCF.
Under CRR, there are NO LGD floors for A-IRB (unlike Basel 3.1 which introduces them).

Usage:
    uv run marimo edit workbooks/crr_expected_outputs/scenarios/group_crr_c_airb.py

Key CRR References:
    - Art. 143: Permission to use IRB
    - Art. 153: IRB risk weight formula for non-retail
    - Art. 154: IRB risk weight formula for retail
    - Art. 163: PD floor (0.03% - single floor for all classes)
    - No LGD floors under CRR A-IRB (unlike Basel 3.1)
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
    from pathlib import Path
    from datetime import date
    from decimal import Decimal
    import json

    # Add project root to path
    project_root = Path(__file__).parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from workbooks.shared.fixture_loader import load_fixtures
    from workbooks.shared.correlation import calculate_correlation
    from workbooks.shared.irb_formulas import (
        calculate_irb_rwa,
        calculate_expected_loss,
        apply_pd_floor,
    )
    from workbooks.crr_expected_outputs.data.crr_params import (
        CRR_PD_FLOOR,
    )
    return (
        CRR_PD_FLOOR,
        Decimal,
        apply_pd_floor,
        calculate_correlation,
        calculate_expected_loss,
        calculate_irb_rwa,
        load_fixtures,
        mo,
        pl,
    )


@app.cell
def _(mo):
    """Header."""
    mo.md("""
    # Group CRR-C: CRR Advanced IRB (A-IRB) Scenarios

    This workbook calculates expected RWA values for CRR A-IRB scenarios CRR-C1 to CRR-C3.

    **Regulatory Framework:** CRR (Capital Requirements Regulation)
    **Effective:** Until 31 December 2026

    **Key CRR A-IRB Features:**
    - Bank provides own estimates for PD, LGD, EAD (and CCF for off-balance sheet)
    - **No LGD floors under CRR** - banks can use their own LGD estimates without floors
    - Single PD floor: 0.03% for all exposure classes
    - 1.06 scaling factor applied
    - Full scope permitted for all exposure classes (retail, corporate, etc.)

    **Key differences from Basel 3.1 A-IRB:**
    - CRR has NO LGD floors (Basel 3.1 has 25% unsecured, 0-15% secured)
    - CRR has single 0.03% PD floor (Basel 3.1 has differentiated floors)
    - CRR allows A-IRB for large corporates (Basel 3.1 restricts to <EUR 500m revenue)
    - CRR has 1.06 scaling factor (removed in Basel 3.1)

    **Retail treatment:**
    - Retail exposures under IRB MUST use A-IRB (F-IRB not available for retail)
    - Retail uses specific correlation formulas (fixed 0.15 for mortgages, 0.04 for QRRE)
    - No maturity adjustment for retail
    """)
    return


@app.cell
def _(load_fixtures):
    """Load test fixtures."""
    fixtures = load_fixtures()
    return (fixtures,)


@app.cell
def _():
    """Scenario result dataclass for A-IRB."""
    from dataclasses import dataclass, asdict
    from typing import Any

    @dataclass
    class CRRAIRBResult:
        """Container for a single CRR A-IRB scenario calculation result."""
        scenario_id: str
        scenario_group: str
        description: str
        exposure_reference: str
        counterparty_reference: str
        approach: str
        exposure_class: str
        ead: float
        pd_raw: float
        pd_floored: float
        lgd_internal: float
        lgd_floored: float  # Same as internal under CRR (no floor)
        correlation: float
        maturity: float
        maturity_adjustment: float
        k: float
        rwa: float
        expected_loss: float
        calculation_details: dict
        regulatory_reference: str

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)
    return (CRRAIRBResult,)


@app.cell
def _(mo):
    """Scenario CRR-C1 Header."""
    mo.md("""
    ---
    ## Scenario CRR-C1: Corporate A-IRB - Own LGD Estimate

    **Input:** £5m corporate loan, PD 1.00%, internal LGD 35% (below F-IRB 45%)
    **Expected:** Lower RWA than F-IRB due to better LGD estimate

    **CRR A-IRB Treatment:**
    - Bank's own LGD estimate (35%) used directly
    - No LGD floor applied (unlike Basel 3.1 which would floor at 25%)
    - Maturity adjustment applies (wholesale exposure)

    **Reference:** CRR Art. 143, 153
    """)
    return


@app.cell
def _(
    CRR_PD_FLOOR,
    CRRAIRBResult,
    apply_pd_floor,
    calculate_correlation,
    calculate_expected_loss,
    calculate_irb_rwa,
):
    """Calculate Scenario CRR-C1: Corporate A-IRB with own LGD."""
    # Input parameters - own estimates
    ead_c1 = 5_000_000.0
    pd_raw_c1 = 0.01  # 1.00%
    lgd_internal_c1 = 0.35  # Bank's own estimate (35% < 45% F-IRB)
    maturity_c1 = 2.5

    # Apply PD floor (CRR single floor)
    pd_floored_c1 = apply_pd_floor(pd_raw_c1, float(CRR_PD_FLOOR))

    # Under CRR, no LGD floor - use internal estimate directly
    lgd_floored_c1 = lgd_internal_c1  # No floor

    # Calculate correlation
    correlation_c1 = calculate_correlation(pd_floored_c1, "CORPORATE")

    # Calculate RWA
    result_dict_c1 = calculate_irb_rwa(
        ead=ead_c1,
        pd=pd_raw_c1,
        lgd=lgd_floored_c1,
        correlation=correlation_c1,
        maturity=maturity_c1,
        pd_floor=float(CRR_PD_FLOOR),
        lgd_floor=None,  # CRR A-IRB has NO LGD floor
        apply_maturity_adjustment=True,
        is_retail=False,
        apply_scaling_factor=True,  # CRR 1.06 scaling
    )

    # Expected loss
    el_c1 = calculate_expected_loss(pd_floored_c1, lgd_floored_c1, ead_c1)

    result_crr_c1 = CRRAIRBResult(
        scenario_id="CRR-C1",
        scenario_group="CRR-C",
        description="Corporate A-IRB - own LGD estimate (35%)",
        exposure_reference="LOAN_CORP_AIRB_001",
        counterparty_reference="CORP_AIRB_001",
        approach="A-IRB",
        exposure_class="CORPORATE",
        ead=ead_c1,
        pd_raw=pd_raw_c1,
        pd_floored=pd_floored_c1,
        lgd_internal=lgd_internal_c1,
        lgd_floored=lgd_floored_c1,
        correlation=correlation_c1,
        maturity=maturity_c1,
        maturity_adjustment=result_dict_c1["maturity_adjustment"],
        k=result_dict_c1["k"],
        rwa=result_dict_c1["rwa"],
        expected_loss=el_c1,
        calculation_details={
            "pd_floor": float(CRR_PD_FLOOR),
            "lgd_floor": "None (CRR A-IRB)",
            "lgd_internal": lgd_internal_c1,
            "lgd_vs_firb": f"Internal {lgd_internal_c1*100:.0f}% vs F-IRB 45%",
            "scaling_factor": 1.06,
            "crr_vs_basel31": "No LGD floor under CRR (Basel 3.1 would floor at 25%)",
        },
        regulatory_reference="CRR Art. 143, 153",
    )

    print(f"CRR-C1: EAD=£{ead_c1:,.0f}, PD={pd_floored_c1*100:.2f}%, LGD={lgd_floored_c1*100:.0f}%")
    print(f"  RWA=£{result_dict_c1['rwa']:,.0f}")
    return (result_crr_c1,)


@app.cell
def _(mo):
    """Scenario CRR-C2 Header."""
    mo.md("""
    ---
    ## Scenario CRR-C2: Retail A-IRB - Own Estimates

    **Input:** £100k retail loan, PD 0.30%, internal LGD 15%
    **Expected:** Retail IRB calculation with no maturity adjustment

    **CRR Retail A-IRB Treatment:**
    - Retail MUST use A-IRB (F-IRB not available for retail)
    - Own LGD estimate used directly (no floor under CRR)
    - No maturity adjustment for retail exposures
    - Retail correlation formula applies (PD-dependent: 3% to 16%)

    **Reference:** CRR Art. 154
    """)
    return


@app.cell
def _(
    CRR_PD_FLOOR,
    CRRAIRBResult,
    apply_pd_floor,
    calculate_correlation,
    calculate_expected_loss,
    calculate_irb_rwa,
):
    """Calculate Scenario CRR-C2: Retail A-IRB with own estimates."""
    # Retail exposure - own estimates
    ead_c2 = 100_000.0
    pd_raw_c2 = 0.003  # 0.30%
    lgd_internal_c2 = 0.15  # Bank's own estimate (15%)
    maturity_c2 = 0.0  # Retail has no maturity adjustment

    # Apply PD floor
    pd_floored_c2 = apply_pd_floor(pd_raw_c2, float(CRR_PD_FLOOR))

    # No LGD floor under CRR
    lgd_floored_c2 = lgd_internal_c2

    # Retail correlation (PD-dependent: 3% to 16%)
    correlation_c2 = calculate_correlation(pd_floored_c2, "RETAIL")

    # Calculate RWA - retail has no MA, no scaling factor for retail typically
    result_dict_c2 = calculate_irb_rwa(
        ead=ead_c2,
        pd=pd_raw_c2,
        lgd=lgd_floored_c2,
        correlation=correlation_c2,
        maturity=2.5,  # Ignored for retail
        pd_floor=float(CRR_PD_FLOOR),
        lgd_floor=None,  # CRR A-IRB has NO LGD floor
        apply_maturity_adjustment=False,  # No MA for retail
        is_retail=True,
        apply_scaling_factor=True,  # CRR 1.06 still applies
    )

    el_c2 = calculate_expected_loss(pd_floored_c2, lgd_floored_c2, ead_c2)

    result_crr_c2 = CRRAIRBResult(
        scenario_id="CRR-C2",
        scenario_group="CRR-C",
        description="Retail A-IRB - own estimates (PD 0.3%, LGD 15%)",
        exposure_reference="LOAN_RTL_AIRB_001",
        counterparty_reference="RTL_AIRB_001",
        approach="A-IRB",
        exposure_class="RETAIL",
        ead=ead_c2,
        pd_raw=pd_raw_c2,
        pd_floored=pd_floored_c2,
        lgd_internal=lgd_internal_c2,
        lgd_floored=lgd_floored_c2,
        correlation=correlation_c2,
        maturity=maturity_c2,
        maturity_adjustment=1.0,  # No adjustment for retail
        k=result_dict_c2["k"],
        rwa=result_dict_c2["rwa"],
        expected_loss=el_c2,
        calculation_details={
            "pd_floor": float(CRR_PD_FLOOR),
            "lgd_floor": "None (CRR A-IRB)",
            "correlation_type": "Retail PD-dependent (3%-16%)",
            "maturity_adjustment": "Not applicable for retail",
            "scaling_factor": 1.06,
            "note": "Retail must use A-IRB (F-IRB not available)",
        },
        regulatory_reference="CRR Art. 154",
    )

    print(f"CRR-C2: EAD=£{ead_c2:,.0f}, PD={pd_floored_c2*100:.2f}%, LGD={lgd_floored_c2*100:.0f}%")
    print(f"  Correlation={correlation_c2:.4f}, RWA=£{result_dict_c2['rwa']:,.0f}")
    return (result_crr_c2,)


@app.cell
def _(mo):
    """Scenario CRR-C3 Header."""
    mo.md("""
    ---
    ## Scenario CRR-C3: Specialised Lending A-IRB (Project Finance)

    **Input:** £10m project finance loan, PD 1.50%, internal LGD 25%
    **Expected:** A-IRB calculation for specialised lending

    **CRR Treatment:**
    - Banks with A-IRB approval for specialised lending use own estimates
    - Alternative: use slotting approach (CRR Art. 153(5))
    - No LGD floor under CRR A-IRB

    **Note:** This scenario demonstrates A-IRB for specialised lending.
    Slotting approach is covered in CRR-E scenarios.

    **Reference:** CRR Art. 153
    """)
    return


@app.cell
def _(
    CRR_PD_FLOOR,
    CRRAIRBResult,
    apply_pd_floor,
    calculate_correlation,
    calculate_expected_loss,
    calculate_irb_rwa,
):
    """Calculate Scenario CRR-C3: Specialised Lending A-IRB."""
    # Specialised lending (project finance) - own estimates
    ead_c3 = 10_000_000.0
    pd_raw_c3 = 0.015  # 1.50%
    lgd_internal_c3 = 0.25  # Bank's own estimate (25%)
    maturity_c3 = 4.0  # Project finance typically longer maturity

    # Apply PD floor
    pd_floored_c3 = apply_pd_floor(pd_raw_c3, float(CRR_PD_FLOOR))

    # No LGD floor under CRR
    lgd_floored_c3 = lgd_internal_c3

    # Specialised lending uses corporate correlation
    correlation_c3 = calculate_correlation(pd_floored_c3, "CORPORATE")

    # Calculate RWA
    result_dict_c3 = calculate_irb_rwa(
        ead=ead_c3,
        pd=pd_raw_c3,
        lgd=lgd_floored_c3,
        correlation=correlation_c3,
        maturity=maturity_c3,
        pd_floor=float(CRR_PD_FLOOR),
        lgd_floor=None,  # CRR A-IRB has NO LGD floor
        apply_maturity_adjustment=True,
        is_retail=False,
        apply_scaling_factor=True,  # CRR 1.06 scaling
    )

    el_c3 = calculate_expected_loss(pd_floored_c3, lgd_floored_c3, ead_c3)

    result_crr_c3 = CRRAIRBResult(
        scenario_id="CRR-C3",
        scenario_group="CRR-C",
        description="Specialised lending A-IRB - project finance",
        exposure_reference="LOAN_SL_AIRB_001",
        counterparty_reference="SL_PF_001",
        approach="A-IRB",
        exposure_class="SPECIALISED_LENDING",
        ead=ead_c3,
        pd_raw=pd_raw_c3,
        pd_floored=pd_floored_c3,
        lgd_internal=lgd_internal_c3,
        lgd_floored=lgd_floored_c3,
        correlation=correlation_c3,
        maturity=maturity_c3,
        maturity_adjustment=result_dict_c3["maturity_adjustment"],
        k=result_dict_c3["k"],
        rwa=result_dict_c3["rwa"],
        expected_loss=el_c3,
        calculation_details={
            "pd_floor": float(CRR_PD_FLOOR),
            "lgd_floor": "None (CRR A-IRB)",
            "lgd_internal": lgd_internal_c3,
            "lending_type": "Project Finance",
            "alternative_approach": "Slotting (CRR Art. 153(5))",
            "scaling_factor": 1.06,
        },
        regulatory_reference="CRR Art. 153",
    )

    print(f"CRR-C3: EAD=£{ead_c3:,.0f}, PD={pd_floored_c3*100:.2f}%, LGD={lgd_floored_c3*100:.0f}%")
    print(f"  Maturity={maturity_c3}y, RWA=£{result_dict_c3['rwa']:,.0f}")
    return (result_crr_c3,)


@app.cell
def _(mo):
    """Summary Section."""
    mo.md("""
    ---
    ## Summary: Group CRR-C A-IRB Results

    Key CRR A-IRB observations:
    1. **No LGD floors** - Banks can use their own LGD estimates without floors
       - This contrasts with Basel 3.1 which has 25% unsecured, 0-15% secured
    2. **Single PD floor** - 0.03% for all exposure classes
    3. **Full scope** - A-IRB permitted for all exposure classes including large corporates
    4. **Retail treatment** - Must use A-IRB (F-IRB not available), no maturity adjustment
    5. **1.06 scaling factor** - Applied to all IRB exposures under CRR
    """)
    return


@app.cell
def _(mo, pl, result_crr_c1, result_crr_c2, result_crr_c3):
    """Compile all Group CRR-C results."""
    group_crr_c_results = [
        result_crr_c1, result_crr_c2, result_crr_c3,
    ]

    # Create summary DataFrame
    summary_data_c = []
    for r in group_crr_c_results:
        summary_data_c.append({
            "Scenario": r.scenario_id,
            "Description": r.description,
            "Exp Class": r.exposure_class,
            "EAD (£)": f"{r.ead:,.0f}",
            "PD": f"{r.pd_floored*100:.2f}%",
            "LGD (internal)": f"{r.lgd_internal*100:.0f}%",
            "LGD (floored)": f"{r.lgd_floored*100:.0f}%",
            "RWA (£)": f"{r.rwa:,.0f}",
        })

    summary_df_c = pl.DataFrame(summary_data_c)
    mo.ui.table(summary_df_c)
    return (group_crr_c_results,)


@app.cell
def _(group_crr_c_results):
    """Export function for use by main workbook."""
    def get_group_crr_c_results():
        """Return all Group CRR-C scenario results."""
        return group_crr_c_results
    return (get_group_crr_c_results,)


if __name__ == "__main__":
    app.run()
