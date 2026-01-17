"""
Group CRR-G: CRR Provisions & Impairments Scenarios

Scenarios CRR-G1 to CRR-G3 covering provision treatment for RWA calculations:
- SA with specific provisions
- IRB Expected Loss (EL) shortfall
- IRB EL excess

Usage:
    uv run marimo edit workbooks/crr_expected_outputs/scenarios/group_crr_g_provisions.py

Key CRR References:
    - Art. 110: EAD adjusted for provisions (SA)
    - Art. 158: Expected loss calculation (IRB)
    - Art. 159: EL shortfall treatment (IRB)
    - Art. 62(d): EL excess treatment (T2 credit)
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
    from workbooks.shared.irb_formulas import calculate_expected_loss
    from workbooks.crr_expected_outputs.calculations.crr_risk_weights import (
        get_corporate_rw,
        calculate_sa_rwa,
    )
    from workbooks.crr_expected_outputs.calculations.crr_irb import (
        calculate_irb_rwa,
        apply_pd_floor,
        get_firb_lgd,
    )
    from workbooks.shared.correlation import calculate_correlation
    from workbooks.crr_expected_outputs.data.crr_params import CRR_PD_FLOOR
    return (
        CRR_PD_FLOOR,
        Decimal,
        apply_pd_floor,
        calculate_correlation,
        calculate_expected_loss,
        calculate_irb_rwa,
        calculate_sa_rwa,
        get_corporate_rw,
        get_firb_lgd,
        load_fixtures,
        mo,
        pl,
    )


@app.cell
def _(mo):
    """Header."""
    mo.md("""
    # Group CRR-G: CRR Provisions & Impairments Scenarios

    This workbook calculates expected RWA values for CRR provision scenarios CRR-G1 to CRR-G3.

    **Regulatory Framework:** CRR (Capital Requirements Regulation)
    **Effective:** Until 31 December 2026

    **Key CRR Provision Treatments:**

    **Standardised Approach (Art. 110):**
    - Specific credit risk adjustments (provisions) reduce EAD
    - RWA calculated on net exposure
    - EAD_net = Gross Exposure - Specific Provisions

    **IRB Approach (Art. 158-159):**
    - Expected Loss (EL) = PD × LGD × EAD
    - Compare provisions (specific + general) against EL
    - **EL Shortfall** (Provisions < EL): Deduct from CET1 (50%) and T2 (50%)
    - **EL Excess** (Provisions > EL): Add to T2 capital (capped at 0.6% of RWA)

    **IFRS 9 Treatment:**
    - Stage 1: 12-month ECL (performing)
    - Stage 2: Lifetime ECL (SICR)
    - Stage 3: Lifetime ECL (credit impaired/defaulted)
    """)
    return


@app.cell
def _(load_fixtures):
    """Load test fixtures."""
    fixtures = load_fixtures()
    return (fixtures,)


@app.cell
def _():
    """Scenario result dataclass for Provisions."""
    from dataclasses import dataclass, asdict
    from typing import Any

    @dataclass
    class CRRProvisionResult:
        """Container for a single CRR provision scenario calculation result."""
        scenario_id: str
        scenario_group: str
        description: str
        exposure_reference: str
        counterparty_reference: str
        approach: str
        exposure_class: str
        # Exposure details
        gross_exposure: float
        specific_provision: float
        general_provision: float
        total_provision: float
        net_exposure: float
        # IRB specific (if applicable)
        pd: float | None
        lgd: float | None
        expected_loss: float | None
        el_shortfall: float | None
        el_excess: float | None
        # RWA
        risk_weight: float
        rwa: float
        # Capital impact
        cet1_deduction: float
        t2_credit: float
        calculation_details: dict
        regulatory_reference: str

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)
    return (CRRProvisionResult,)


@app.cell
def _(mo):
    """Scenario CRR-G1 Header."""
    mo.md("""
    ---
    ## Scenario CRR-G1: SA with Specific Provision

    **Input:** £1m corporate exposure, £50k specific provision
    **Expected:** RWA calculated on net exposure (£950k)

    **CRR Treatment (Art. 110):**
    - For SA, specific provisions reduce EAD
    - EAD_net = £1m - £50k = £950k
    - RWA = £950k × 100% = £950k

    **Reference:** CRR Art. 110
    """)
    return


@app.cell
def _(CRRProvisionResult, Decimal, calculate_sa_rwa, get_corporate_rw):
    """Calculate Scenario CRR-G1: SA with Specific Provision."""
    # Input
    gross_exp_g1 = Decimal("1000000")
    specific_prov_g1 = Decimal("50000")
    general_prov_g1 = Decimal("0")

    # Net exposure after provision
    net_exp_g1 = gross_exp_g1 - specific_prov_g1

    # Risk weight (unrated corporate)
    rw_g1 = get_corporate_rw(None)  # 100%

    # Calculate RWA on net exposure
    rwa_g1 = calculate_sa_rwa(net_exp_g1, rw_g1)

    result_crr_g1 = CRRProvisionResult(
        scenario_id="CRR-G1",
        scenario_group="CRR-G",
        description="SA with specific provision - RWA on net exposure",
        exposure_reference="LOAN_PROV_G1",
        counterparty_reference="CORP_PROV_G1",
        approach="SA",
        exposure_class="CORPORATE",
        gross_exposure=float(gross_exp_g1),
        specific_provision=float(specific_prov_g1),
        general_provision=float(general_prov_g1),
        total_provision=float(specific_prov_g1 + general_prov_g1),
        net_exposure=float(net_exp_g1),
        pd=None,
        lgd=None,
        expected_loss=None,
        el_shortfall=None,
        el_excess=None,
        risk_weight=float(rw_g1),
        rwa=float(rwa_g1),
        cet1_deduction=0.0,
        t2_credit=0.0,
        calculation_details={
            "treatment": "Specific provision reduces EAD",
            "formula": "EAD_net = Gross - Specific Provision",
            "calculation": f"EAD_net = £{gross_exp_g1:,.0f} - £{specific_prov_g1:,.0f} = £{net_exp_g1:,.0f}",
            "rwa_calc": f"RWA = £{net_exp_g1:,.0f} × 100% = £{rwa_g1:,.0f}",
        },
        regulatory_reference="CRR Art. 110",
    )

    print(f"CRR-G1: SA with specific provision")
    print(f"  Gross=£{gross_exp_g1:,.0f}, Provision=£{specific_prov_g1:,.0f}")
    print(f"  Net=£{net_exp_g1:,.0f}, RWA=£{rwa_g1:,.0f}")
    return (result_crr_g1,)


@app.cell
def _(mo):
    """Scenario CRR-G2 Header."""
    mo.md("""
    ---
    ## Scenario CRR-G2: IRB EL Shortfall

    **Input:** £5m exposure, PD 2%, LGD 45%, Provisions £30k
    **Expected:** EL shortfall deducted from capital

    **CRR Treatment (Art. 159):**
    - Expected Loss = PD × LGD × EAD
    - EL = 2% × 45% × £5m = £45,000
    - Provisions = £30,000
    - **Shortfall** = £45,000 - £30,000 = £15,000
    - Shortfall deducted: 50% from CET1, 50% from T2

    **Reference:** CRR Art. 158, 159
    """)
    return


@app.cell
def _(
    CRR_PD_FLOOR,
    CRRProvisionResult,
    Decimal,
    apply_pd_floor,
    calculate_correlation,
    calculate_expected_loss,
    calculate_irb_rwa,
    get_firb_lgd,
):
    """Calculate Scenario CRR-G2: IRB EL Shortfall."""
    # Input
    gross_exp_g2 = Decimal("5000000")
    pd_raw_g2 = 0.02  # 2%
    lgd_g2 = float(get_firb_lgd("unsecured"))  # 45%
    maturity_g2 = 2.5

    # Provisions (total: specific + general allocated)
    specific_prov_g2 = Decimal("20000")
    general_prov_g2 = Decimal("10000")
    total_prov_g2 = specific_prov_g2 + general_prov_g2

    # Apply PD floor
    pd_floored_g2 = apply_pd_floor(pd_raw_g2)

    # Calculate Expected Loss
    el_g2 = calculate_expected_loss(pd_floored_g2, lgd_g2, float(gross_exp_g2))

    # EL comparison
    el_shortfall_g2 = max(el_g2 - float(total_prov_g2), 0)
    el_excess_g2 = max(float(total_prov_g2) - el_g2, 0)

    # Capital deduction for shortfall (50/50 CET1/T2)
    cet1_deduction_g2 = el_shortfall_g2 * 0.5
    # T2 deduction would also be 50%

    # Calculate RWA
    correlation_g2 = calculate_correlation(pd_floored_g2, "CORPORATE")
    result_dict_g2 = calculate_irb_rwa(
        ead=float(gross_exp_g2),
        pd=pd_raw_g2,
        lgd=lgd_g2,
        correlation=correlation_g2,
        maturity=maturity_g2,
        exposure_class="CORPORATE",
    )

    result_crr_g2 = CRRProvisionResult(
        scenario_id="CRR-G2",
        scenario_group="CRR-G",
        description="IRB EL shortfall - capital deduction",
        exposure_reference="LOAN_PROV_G2",
        counterparty_reference="CORP_PROV_G2",
        approach="F-IRB",
        exposure_class="CORPORATE",
        gross_exposure=float(gross_exp_g2),
        specific_provision=float(specific_prov_g2),
        general_provision=float(general_prov_g2),
        total_provision=float(total_prov_g2),
        net_exposure=float(gross_exp_g2),  # IRB uses gross for RWA
        pd=pd_floored_g2,
        lgd=lgd_g2,
        expected_loss=el_g2,
        el_shortfall=el_shortfall_g2,
        el_excess=0.0,
        risk_weight=result_dict_g2["k"] * 12.5 * 1.06 * result_dict_g2["maturity_adjustment"],
        rwa=result_dict_g2["rwa"],
        cet1_deduction=cet1_deduction_g2,
        t2_credit=0.0,
        calculation_details={
            "pd_floor": float(CRR_PD_FLOOR),
            "el_formula": "EL = PD × LGD × EAD",
            "el_calculation": f"EL = {pd_floored_g2*100:.2f}% × {lgd_g2*100:.0f}% × £{gross_exp_g2:,.0f} = £{el_g2:,.0f}",
            "provisions": f"£{total_prov_g2:,.0f}",
            "shortfall_calc": f"Shortfall = £{el_g2:,.0f} - £{total_prov_g2:,.0f} = £{el_shortfall_g2:,.0f}",
            "capital_treatment": "50% CET1 deduction, 50% T2 deduction",
            "cet1_deduction": f"£{cet1_deduction_g2:,.0f}",
        },
        regulatory_reference="CRR Art. 158, 159",
    )

    print(f"CRR-G2: IRB EL Shortfall")
    print(f"  EL=£{el_g2:,.0f}, Provisions=£{total_prov_g2:,.0f}")
    print(f"  Shortfall=£{el_shortfall_g2:,.0f}")
    print(f"  CET1 deduction=£{cet1_deduction_g2:,.0f}")
    return (result_crr_g2,)


@app.cell
def _(mo):
    """Scenario CRR-G3 Header."""
    mo.md("""
    ---
    ## Scenario CRR-G3: IRB EL Excess

    **Input:** £5m exposure, PD 0.5%, LGD 45%, Provisions £50k
    **Expected:** EL excess adds to T2 capital (capped)

    **CRR Treatment (Art. 62(d)):**
    - Expected Loss = PD × LGD × EAD
    - EL = 0.5% × 45% × £5m = £11,250
    - Provisions = £50,000
    - **Excess** = £50,000 - £11,250 = £38,750
    - Excess may be added to T2 (capped at 0.6% of IRB RWA)

    **Reference:** CRR Art. 62(d)
    """)
    return


@app.cell
def _(
    CRR_PD_FLOOR,
    CRRProvisionResult,
    Decimal,
    apply_pd_floor,
    calculate_correlation,
    calculate_expected_loss,
    calculate_irb_rwa,
    get_firb_lgd,
):
    """Calculate Scenario CRR-G3: IRB EL Excess."""
    # Input
    gross_exp_g3 = Decimal("5000000")
    pd_raw_g3 = 0.005  # 0.5%
    lgd_g3 = float(get_firb_lgd("unsecured"))  # 45%
    maturity_g3 = 2.5

    # Higher provisions than expected loss
    specific_prov_g3 = Decimal("35000")
    general_prov_g3 = Decimal("15000")
    total_prov_g3 = specific_prov_g3 + general_prov_g3

    # Apply PD floor
    pd_floored_g3 = apply_pd_floor(pd_raw_g3)

    # Calculate Expected Loss
    el_g3 = calculate_expected_loss(pd_floored_g3, lgd_g3, float(gross_exp_g3))

    # EL comparison
    el_shortfall_g3 = max(el_g3 - float(total_prov_g3), 0)
    el_excess_g3 = max(float(total_prov_g3) - el_g3, 0)

    # Calculate RWA
    correlation_g3 = calculate_correlation(pd_floored_g3, "CORPORATE")
    result_dict_g3 = calculate_irb_rwa(
        ead=float(gross_exp_g3),
        pd=pd_raw_g3,
        lgd=lgd_g3,
        correlation=correlation_g3,
        maturity=maturity_g3,
        exposure_class="CORPORATE",
    )

    # T2 credit capped at 0.6% of IRB RWA
    rwa_g3 = result_dict_g3["rwa"]
    t2_cap_g3 = rwa_g3 * 0.006
    t2_credit_g3 = min(el_excess_g3, t2_cap_g3)

    result_crr_g3 = CRRProvisionResult(
        scenario_id="CRR-G3",
        scenario_group="CRR-G",
        description="IRB EL excess - T2 capital credit",
        exposure_reference="LOAN_PROV_G3",
        counterparty_reference="CORP_PROV_G3",
        approach="F-IRB",
        exposure_class="CORPORATE",
        gross_exposure=float(gross_exp_g3),
        specific_provision=float(specific_prov_g3),
        general_provision=float(general_prov_g3),
        total_provision=float(total_prov_g3),
        net_exposure=float(gross_exp_g3),  # IRB uses gross for RWA
        pd=pd_floored_g3,
        lgd=lgd_g3,
        expected_loss=el_g3,
        el_shortfall=0.0,
        el_excess=el_excess_g3,
        risk_weight=result_dict_g3["k"] * 12.5 * 1.06 * result_dict_g3["maturity_adjustment"],
        rwa=rwa_g3,
        cet1_deduction=0.0,
        t2_credit=t2_credit_g3,
        calculation_details={
            "pd_floor": float(CRR_PD_FLOOR),
            "el_formula": "EL = PD × LGD × EAD",
            "el_calculation": f"EL = {pd_floored_g3*100:.2f}% × {lgd_g3*100:.0f}% × £{gross_exp_g3:,.0f} = £{el_g3:,.0f}",
            "provisions": f"£{total_prov_g3:,.0f}",
            "excess_calc": f"Excess = £{total_prov_g3:,.0f} - £{el_g3:,.0f} = £{el_excess_g3:,.0f}",
            "t2_cap": f"0.6% × £{rwa_g3:,.0f} = £{t2_cap_g3:,.0f}",
            "t2_credit": f"min(£{el_excess_g3:,.0f}, £{t2_cap_g3:,.0f}) = £{t2_credit_g3:,.0f}",
            "capital_treatment": "EL excess added to T2, capped at 0.6% of IRB RWA",
        },
        regulatory_reference="CRR Art. 62(d)",
    )

    print(f"CRR-G3: IRB EL Excess")
    print(f"  EL=£{el_g3:,.0f}, Provisions=£{total_prov_g3:,.0f}")
    print(f"  Excess=£{el_excess_g3:,.0f}")
    print(f"  T2 credit (capped)=£{t2_credit_g3:,.0f}")
    return (result_crr_g3,)


@app.cell
def _(mo):
    """Summary Section."""
    mo.md("""
    ---
    ## Summary: Group CRR-G Provision Results

    Key CRR provision observations:

    **Standardised Approach:**
    - Specific provisions reduce EAD directly
    - Simple treatment - RWA on net exposure

    **IRB Approach:**
    - Calculate Expected Loss (EL = PD × LGD × EAD)
    - Compare total provisions against EL
    - **Shortfall**: Deduct 50% from CET1, 50% from T2
    - **Excess**: Add to T2 (capped at 0.6% of IRB RWA)

    **IFRS 9 Interaction:**
    - Stage 1 & 2 provisions may be eligible general provisions
    - Stage 3 provisions are specific provisions
    - ECL basis may differ from regulatory EL basis
    """)
    return


@app.cell
def _(mo, pl, result_crr_g1, result_crr_g2, result_crr_g3):
    """Compile all Group CRR-G results."""
    group_crr_g_results = [
        result_crr_g1, result_crr_g2, result_crr_g3,
    ]

    # Create summary DataFrame
    summary_data_g = []
    for r in group_crr_g_results:
        summary_data_g.append({
            "Scenario": r.scenario_id,
            "Approach": r.approach,
            "Gross (£)": f"{r.gross_exposure:,.0f}",
            "Provision (£)": f"{r.total_provision:,.0f}",
            "EL (£)": f"{r.expected_loss:,.0f}" if r.expected_loss else "-",
            "Shortfall (£)": f"{r.el_shortfall:,.0f}" if r.el_shortfall else "-",
            "Excess (£)": f"{r.el_excess:,.0f}" if r.el_excess else "-",
            "RWA (£)": f"{r.rwa:,.0f}",
            "CET1 Deduct (£)": f"{r.cet1_deduction:,.0f}" if r.cet1_deduction > 0 else "-",
            "T2 Credit (£)": f"{r.t2_credit:,.0f}" if r.t2_credit > 0 else "-",
        })

    summary_df_g = pl.DataFrame(summary_data_g)
    mo.ui.table(summary_df_g)
    return (group_crr_g_results,)


@app.cell
def _(group_crr_g_results):
    """Export function for use by main workbook."""
    def get_group_crr_g_results():
        """Return all Group CRR-G scenario results."""
        return group_crr_g_results
    return (get_group_crr_g_results,)


if __name__ == "__main__":
    app.run()
