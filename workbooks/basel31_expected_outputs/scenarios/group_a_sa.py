"""
Group A: Standardised Approach (SA) Scenarios

Scenarios A1-A10 covering basic SA risk weight lookups for different
exposure classes: sovereign, institution, corporate, retail, and real estate.

Usage:
    uv run marimo edit workbooks/rwa_expected_outputs/scenarios/group_a_sa.py
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
    import json

    # Add project root to path
    project_root = Path(__file__).parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from workbooks.rwa_expected_outputs.data.fixture_loader import load_fixtures
    from workbooks.rwa_expected_outputs.calculations.sa_risk_weights import (
        get_cgcb_risk_weight,
        get_institution_risk_weight,
        get_corporate_risk_weight,
        get_retail_risk_weight,
        get_mortgage_risk_weight,
        calculate_sa_rwa,
    )
    from workbooks.rwa_expected_outputs.calculations.ccf import (
        get_ccf,
        calculate_ead_from_contingent,
    )
    return (
        calculate_ead_from_contingent,
        calculate_sa_rwa,
        get_corporate_risk_weight,
        get_institution_risk_weight,
        get_mortgage_risk_weight,
        get_retail_risk_weight,
        get_cgcb_risk_weight,
        load_fixtures,
        mo,
        pl,
    )


@app.cell
def _(mo):
    """Header."""
    mo.md("""
    # Group A: Standardised Approach Scenarios

    This workbook calculates expected RWA values for SA scenarios A1-A10.

    **Regulatory References:**
    - CRE20.7: Sovereign risk weights
    - CRE20.16: Institution risk weights (ECRA)
    - CRE20.25-26: Corporate risk weights
    - CRE20.66: Retail risk weight (75%)
    - CRE20.71-73: Residential mortgage risk weights (LTV-based)
    - CRE20.83-85: Commercial real estate risk weights
    - CRE20.93-98: Credit conversion factors
    - PRA PS9/24: UK deviation for institution CQS2 (30% instead of 50%)
    """)
    return


@app.cell
def _(load_fixtures):
    """Load test fixtures."""
    fixtures = load_fixtures()
    return (fixtures,)


@app.cell
def _(fixtures, mo):
    """Display available loans for SA scenarios."""
    loans_df = fixtures.loans.collect()
    mo.md(f"**Available loans:** {len(loans_df)} records")
    return


@app.cell
def _():
    """Scenario result dataclass."""
    from dataclasses import dataclass, asdict
    from typing import Any

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
def _(mo):
    """Scenario A1 Header."""
    mo.md("""
    ---
    ## Scenario A1: UK Sovereign - 0% Risk Weight

    **Input:** £1m loan to UK Government (CQS 1)
    **Expected:** 0% RW, £0 RWA
    **Reference:** CRE20.7
    """)
    return


@app.cell
def _(ScenarioResult, calculate_sa_rwa, fixtures, get_cgcb_risk_weight):
    """Calculate Scenario A1: UK Sovereign."""
    # Load data
    loan_a1 = fixtures.get_loan("LOAN_SOV_UK_001")
    cpty_a1 = fixtures.get_counterparty("SOV_UK_001")
    rating_a1 = fixtures.get_rating("SOV_UK_001")

    # Get CQS from rating (UK Government is CQS 1)
    cqs_a1 = rating_a1["cqs"] if rating_a1 else 1

    # Calculate
    ead_a1 = loan_a1["drawn_amount"]
    rw_a1 = get_cgcb_risk_weight(cqs_a1)
    rwa_a1 = calculate_sa_rwa(ead_a1, rw_a1)

    # Create result
    result_a1 = ScenarioResult(
        scenario_id="A1",
        scenario_group="A",
        description="UK Sovereign exposure - 0% RW",
        exposure_reference="LOAN_SOV_UK_001",
        counterparty_reference="SOV_UK_001",
        approach="SA",
        exposure_class="CENTRAL_GOVT_CENTRAL_BANK",
        ead=ead_a1,
        risk_weight=rw_a1,
        rwa=rwa_a1,
        calculation_details={
            "counterparty_name": cpty_a1["counterparty_name"],
            "country_code": cpty_a1["country_code"],
            "cqs": cqs_a1,
            "formula": "RWA = EAD × RW",
            "calculation": f"RWA = £{ead_a1:,.0f} × {rw_a1*100:.0f}% = £{rwa_a1:,.0f}",
        },
        regulatory_reference="CRE20.7",
    )

    print(f"A1: EAD=£{ead_a1:,.0f}, RW={rw_a1*100:.0f}%, RWA=£{rwa_a1:,.0f}")
    return (result_a1,)


@app.cell
def _(mo):
    """Scenario A2 Header."""
    mo.md("""
    ---
    ## Scenario A2: Unrated Corporate - 100% Risk Weight

    **Input:** £1m loan to unrated corporate
    **Expected:** 100% RW, £1m RWA
    **Reference:** CRE20.26
    """)
    return


@app.cell
def _(ScenarioResult, calculate_sa_rwa, fixtures, get_corporate_risk_weight):
    """Calculate Scenario A2: Unrated Corporate."""
    loan_a2 = fixtures.get_loan("LOAN_CORP_UR_001")
    cpty_a2 = fixtures.get_counterparty("CORP_UR_001")
    rating_a2 = fixtures.get_rating("CORP_UR_001")

    # Unrated = CQS 0
    cqs_a2 = rating_a2["cqs"] if rating_a2 else 0

    ead_a2 = loan_a2["drawn_amount"]
    rw_a2 = get_corporate_risk_weight(cqs_a2)
    rwa_a2 = calculate_sa_rwa(ead_a2, rw_a2)

    result_a2 = ScenarioResult(
        scenario_id="A2",
        scenario_group="A",
        description="Unrated corporate - 100% RW",
        exposure_reference="LOAN_CORP_UR_001",
        counterparty_reference="CORP_UR_001",
        approach="SA",
        exposure_class="CORPORATE",
        ead=ead_a2,
        risk_weight=rw_a2,
        rwa=rwa_a2,
        calculation_details={
            "counterparty_name": cpty_a2["counterparty_name"],
            "cqs": cqs_a2,
            "rating_status": "unrated",
            "formula": "RWA = EAD × RW",
            "calculation": f"RWA = £{ead_a2:,.0f} × {rw_a2*100:.0f}% = £{rwa_a2:,.0f}",
        },
        regulatory_reference="CRE20.26",
    )

    print(f"A2: EAD=£{ead_a2:,.0f}, RW={rw_a2*100:.0f}%, RWA=£{rwa_a2:,.0f}")
    return (result_a2,)


@app.cell
def _(mo):
    """Scenario A3 Header."""
    mo.md("""
    ---
    ## Scenario A3: Rated Corporate CQS 2 - 50% Risk Weight

    **Input:** £1m loan to A-rated corporate (Rolls-Royce)
    **Expected:** 50% RW, £500k RWA
    **Reference:** CRE20.25
    """)
    return


@app.cell
def _(ScenarioResult, calculate_sa_rwa, fixtures, get_corporate_risk_weight):
    """Calculate Scenario A3: Rated Corporate CQS 2."""
    loan_a3 = fixtures.get_loan("LOAN_CORP_UK_003")
    cpty_a3 = fixtures.get_counterparty("CORP_UK_003")
    rating_a3 = fixtures.get_rating("CORP_UK_003")

    cqs_a3 = rating_a3["cqs"] if rating_a3 else 2

    ead_a3 = loan_a3["drawn_amount"]
    rw_a3 = get_corporate_risk_weight(cqs_a3)
    rwa_a3 = calculate_sa_rwa(ead_a3, rw_a3)

    result_a3 = ScenarioResult(
        scenario_id="A3",
        scenario_group="A",
        description="Rated corporate CQS 2 - 50% RW",
        exposure_reference="LOAN_CORP_UK_003",
        counterparty_reference="CORP_UK_003",
        approach="SA",
        exposure_class="CORPORATE",
        ead=ead_a3,
        risk_weight=rw_a3,
        rwa=rwa_a3,
        calculation_details={
            "counterparty_name": cpty_a3["counterparty_name"],
            "cqs": cqs_a3,
            "rating_value": rating_a3["rating_value"] if rating_a3 else "A",
            "formula": "RWA = EAD × RW",
            "calculation": f"RWA = £{ead_a3:,.0f} × {rw_a3*100:.0f}% = £{rwa_a3:,.0f}",
        },
        regulatory_reference="CRE20.25",
    )

    print(f"A3: EAD=£{ead_a3:,.0f}, RW={rw_a3*100:.0f}%, RWA=£{rwa_a3:,.0f}")
    return (result_a3,)


@app.cell
def _(mo):
    """Scenario A4 Header."""
    mo.md("""
    ---
    ## Scenario A4: UK Institution CQS 2 - 30% Risk Weight (UK Deviation)

    **Input:** £1m loan to UK bank with CQS 2 rating
    **Expected:** 30% RW, £300k RWA (UK deviation from Basel 50%)
    **Reference:** CRE20.16, PRA PS9/24 Ch.3
    """)
    return


@app.cell
def _(ScenarioResult, calculate_sa_rwa, fixtures, get_institution_risk_weight):
    """Calculate Scenario A4: UK Institution CQS 2."""
    loan_a4 = fixtures.get_loan("LOAN_INST_UK_003")
    cpty_a4 = fixtures.get_counterparty("INST_UK_003")
    rating_a4 = fixtures.get_rating("INST_UK_003")

    cqs_a4 = rating_a4["cqs"] if rating_a4 else 2

    ead_a4 = loan_a4["drawn_amount"]
    # Use UK deviation for CQS 2 institutions
    rw_a4 = get_institution_risk_weight(cqs_a4, use_uk_deviation=True)
    rwa_a4 = calculate_sa_rwa(ead_a4, rw_a4)

    result_a4 = ScenarioResult(
        scenario_id="A4",
        scenario_group="A",
        description="UK Institution CQS 2 - 30% RW (UK deviation)",
        exposure_reference="LOAN_INST_UK_003",
        counterparty_reference="INST_UK_003",
        approach="SA",
        exposure_class="INSTITUTION",
        ead=ead_a4,
        risk_weight=rw_a4,
        rwa=rwa_a4,
        calculation_details={
            "counterparty_name": cpty_a4["counterparty_name"],
            "cqs": cqs_a4,
            "uk_deviation": True,
            "basel_standard_rw": 0.50,
            "uk_rw": 0.30,
            "formula": "RWA = EAD × RW",
            "calculation": f"RWA = £{ead_a4:,.0f} × {rw_a4*100:.0f}% = £{rwa_a4:,.0f}",
        },
        regulatory_reference="CRE20.16, PRA PS9/24",
    )

    print(f"A4: EAD=£{ead_a4:,.0f}, RW={rw_a4*100:.0f}%, RWA=£{rwa_a4:,.0f}")
    return (result_a4,)


@app.cell
def _(mo):
    """Scenario A5 Header."""
    mo.md("""
    ---
    ## Scenario A5: Residential Mortgage 60% LTV - 20% Risk Weight

    **Input:** £500k mortgage, £833k property value (60% LTV)
    **Expected:** 20% RW, £100k RWA
    **Reference:** CRE20.71
    """)
    return


@app.cell
def _(
    ScenarioResult,
    calculate_sa_rwa,
    fixtures,
    get_mortgage_risk_weight,
    pl,
):
    """Calculate Scenario A5: Residential Mortgage 60% LTV."""
    loan_a5 = fixtures.get_loan("LOAN_RTL_MTG_001")
    cpty_a5 = fixtures.get_counterparty("RTL_MTG_001")

    # Get collateral for LTV
    coll_a5 = fixtures.collateral.filter(
        pl.col("beneficiary_reference") == "LOAN_RTL_MTG_001"
    ).collect()

    # LTV from collateral record or calculate
    if coll_a5.height > 0:
        ltv_a5 = coll_a5[0, "property_ltv"]
    else:
        # 60% LTV from scenario definition
        ltv_a5 = 0.60

    ead_a5 = loan_a5["drawn_amount"]
    rw_a5 = get_mortgage_risk_weight(ltv_a5, property_type="residential")
    rwa_a5 = calculate_sa_rwa(ead_a5, rw_a5)

    result_a5 = ScenarioResult(
        scenario_id="A5",
        scenario_group="A",
        description="Residential mortgage 60% LTV - 20% RW",
        exposure_reference="LOAN_RTL_MTG_001",
        counterparty_reference="RTL_MTG_001",
        approach="SA",
        exposure_class="RETAIL_MORTGAGE",
        ead=ead_a5,
        risk_weight=rw_a5,
        rwa=rwa_a5,
        calculation_details={
            "counterparty_name": cpty_a5["counterparty_name"] if cpty_a5 else "Mortgage borrower",
            "ltv": ltv_a5,
            "property_value": ead_a5 / ltv_a5,
            "ltv_band": "≤60%",
            "formula": "RWA = EAD × RW (based on LTV band)",
            "calculation": f"RWA = £{ead_a5:,.0f} × {rw_a5*100:.0f}% = £{rwa_a5:,.0f}",
        },
        regulatory_reference="CRE20.71",
    )

    print(f"A5: EAD=£{ead_a5:,.0f}, LTV={ltv_a5*100:.0f}%, RW={rw_a5*100:.0f}%, RWA=£{rwa_a5:,.0f}")
    return (result_a5,)


@app.cell
def _(mo):
    """Scenario A6 Header."""
    mo.md("""
    ---
    ## Scenario A6: Residential Mortgage 85% LTV - 35% Risk Weight

    **Input:** £850k mortgage, £1m property value (85% LTV)
    **Expected:** 35% RW, £297.5k RWA
    **Reference:** CRE20.71
    """)
    return


@app.cell
def _(ScenarioResult, calculate_sa_rwa, fixtures, get_mortgage_risk_weight):
    """Calculate Scenario A6: Residential Mortgage 85% LTV."""
    loan_a6 = fixtures.get_loan("LOAN_RTL_MTG_002")
    cpty_a6 = fixtures.get_counterparty("RTL_MTG_002")

    ltv_a6 = 0.85  # 85% LTV

    ead_a6 = loan_a6["drawn_amount"]
    rw_a6 = get_mortgage_risk_weight(ltv_a6, property_type="residential")
    rwa_a6 = calculate_sa_rwa(ead_a6, rw_a6)

    result_a6 = ScenarioResult(
        scenario_id="A6",
        scenario_group="A",
        description="Residential mortgage 85% LTV - 35% RW",
        exposure_reference="LOAN_RTL_MTG_002",
        counterparty_reference="RTL_MTG_002",
        approach="SA",
        exposure_class="RETAIL_MORTGAGE",
        ead=ead_a6,
        risk_weight=rw_a6,
        rwa=rwa_a6,
        calculation_details={
            "counterparty_name": cpty_a6["counterparty_name"] if cpty_a6 else "Mortgage borrower",
            "ltv": ltv_a6,
            "property_value": ead_a6 / ltv_a6,
            "ltv_band": "80% < LTV ≤ 90%",
            "formula": "RWA = EAD × RW (based on LTV band)",
            "calculation": f"RWA = £{ead_a6:,.0f} × {rw_a6*100:.0f}% = £{rwa_a6:,.0f}",
        },
        regulatory_reference="CRE20.71",
    )

    print(f"A6: EAD=£{ead_a6:,.0f}, LTV={ltv_a6*100:.0f}%, RW={rw_a6*100:.0f}%, RWA=£{rwa_a6:,.0f}")
    return (result_a6,)


@app.cell
def _(mo):
    """Scenario A7 Header."""
    mo.md("""
    ---
    ## Scenario A7: Commercial Real Estate 60% LTV - 60% Risk Weight

    **Input:** £600k loan, £1m property value (60% LTV)
    **Expected:** 60% RW, £360k RWA
    **Reference:** CRE20.83
    """)
    return


@app.cell
def _(ScenarioResult, calculate_sa_rwa, get_mortgage_risk_weight):
    """Calculate Scenario A7: Commercial Real Estate 60% LTV."""
    # This scenario uses hypothetical values as we may not have a specific CRE loan
    ltv_a7 = 0.60
    ead_a7 = 600_000.0  # £600k loan

    rw_a7 = get_mortgage_risk_weight(ltv_a7, property_type="commercial")
    rwa_a7 = calculate_sa_rwa(ead_a7, rw_a7)

    result_a7 = ScenarioResult(
        scenario_id="A7",
        scenario_group="A",
        description="Commercial real estate 60% LTV - 60% RW",
        exposure_reference="LOAN_CRE_001",
        counterparty_reference="CORP_CRE_001",
        approach="SA",
        exposure_class="CRE",
        ead=ead_a7,
        risk_weight=rw_a7,
        rwa=rwa_a7,
        calculation_details={
            "ltv": ltv_a7,
            "property_value": ead_a7 / ltv_a7,
            "ltv_band": "LTV ≤ 60%",
            "property_type": "commercial",
            "formula": "RWA = EAD × RW (based on LTV band)",
            "calculation": f"RWA = £{ead_a7:,.0f} × {rw_a7*100:.0f}% = £{rwa_a7:,.0f}",
        },
        regulatory_reference="CRE20.83",
    )

    print(f"A7: EAD=£{ead_a7:,.0f}, LTV={ltv_a7*100:.0f}%, RW={rw_a7*100:.0f}%, RWA=£{rwa_a7:,.0f}")
    return (result_a7,)


@app.cell
def _(mo):
    """Scenario A8 Header."""
    mo.md("""
    ---
    ## Scenario A8: Off-Balance Sheet Commitment - 40% CCF

    **Input:** £1m undrawn committed facility
    **Expected:** 40% CCF, £400k EAD
    **Reference:** CRE20.94-96
    """)
    return


@app.cell
def _(
    ScenarioResult,
    calculate_ead_from_contingent,
    calculate_sa_rwa,
    get_corporate_risk_weight,
):
    """Calculate Scenario A8: Off-Balance Sheet Commitment."""
    nominal_a8 = 1_000_000.0  # £1m commitment
    ccf_category_a8 = "committed_facility"

    ead_result_a8 = calculate_ead_from_contingent(
        nominal_amount=nominal_a8,
        ccf_category=ccf_category_a8,
        drawn_amount=0.0,
    )

    ead_a8 = ead_result_a8["total_ead"]
    # Assume unrated corporate for RW
    rw_a8 = get_corporate_risk_weight(0)  # 100% for unrated
    rwa_a8 = calculate_sa_rwa(ead_a8, rw_a8)

    result_a8 = ScenarioResult(
        scenario_id="A8",
        scenario_group="A",
        description="Off-balance sheet commitment - 40% CCF",
        exposure_reference="CONT_CCF_001",
        counterparty_reference="CORP_OBS_001",
        approach="SA",
        exposure_class="CORPORATE",
        ead=ead_a8,
        risk_weight=rw_a8,
        rwa=rwa_a8,
        calculation_details={
            "nominal_amount": nominal_a8,
            "ccf_category": ccf_category_a8,
            "ccf": ead_result_a8["ccf"],
            "formula": "EAD = Nominal × CCF, then RWA = EAD × RW",
            "ead_calculation": f"EAD = £{nominal_a8:,.0f} × {ead_result_a8['ccf']*100:.0f}% = £{ead_a8:,.0f}",
            "rwa_calculation": f"RWA = £{ead_a8:,.0f} × {rw_a8*100:.0f}% = £{rwa_a8:,.0f}",
        },
        regulatory_reference="CRE20.94-96",
    )

    print(f"A8: Nominal=£{nominal_a8:,.0f}, CCF={ead_result_a8['ccf']*100:.0f}%, EAD=£{ead_a8:,.0f}, RWA=£{rwa_a8:,.0f}")
    return (result_a8,)


@app.cell
def _(mo):
    """Scenario A9 Header."""
    mo.md("""
    ---
    ## Scenario A9: Retail Exposure - 75% Risk Weight

    **Input:** £50k personal loan
    **Expected:** 75% RW, £37.5k RWA
    **Reference:** CRE20.66
    """)
    return


@app.cell
def _(ScenarioResult, calculate_sa_rwa, fixtures, get_retail_risk_weight):
    """Calculate Scenario A9: Retail Exposure."""
    loan_a9 = fixtures.get_loan("LOAN_RTL_IND_001")
    cpty_a9 = fixtures.get_counterparty("RTL_IND_001")

    ead_a9 = loan_a9["drawn_amount"]
    rw_a9 = get_retail_risk_weight()  # 75%
    rwa_a9 = calculate_sa_rwa(ead_a9, rw_a9)

    result_a9 = ScenarioResult(
        scenario_id="A9",
        scenario_group="A",
        description="Retail exposure - 75% RW",
        exposure_reference="LOAN_RTL_IND_001",
        counterparty_reference="RTL_IND_001",
        approach="SA",
        exposure_class="RETAIL",
        ead=ead_a9,
        risk_weight=rw_a9,
        rwa=rwa_a9,
        calculation_details={
            "counterparty_name": cpty_a9["counterparty_name"] if cpty_a9 else "Individual",
            "formula": "RWA = EAD × 75%",
            "calculation": f"RWA = £{ead_a9:,.0f} × {rw_a9*100:.0f}% = £{rwa_a9:,.0f}",
        },
        regulatory_reference="CRE20.66",
    )

    print(f"A9: EAD=£{ead_a9:,.0f}, RW={rw_a9*100:.0f}%, RWA=£{rwa_a9:,.0f}")
    return (result_a9,)


@app.cell
def _(mo):
    """Scenario A10 Header."""
    mo.md("""
    ---
    ## Scenario A10: SME Retail - 75% Risk Weight

    **Input:** £500k loan to SME (turnover < £880k)
    **Expected:** 75% RW (retail treatment), £375k RWA
    **Reference:** CRE20.66
    """)
    return


@app.cell
def _(ScenarioResult, calculate_sa_rwa, fixtures, get_retail_risk_weight):
    """Calculate Scenario A10: SME Retail."""
    loan_a10 = fixtures.get_loan("LOAN_RTL_SME_001")
    cpty_a10 = fixtures.get_counterparty("RTL_SME_001")

    ead_a10 = loan_a10["drawn_amount"]
    rw_a10 = get_retail_risk_weight()  # 75% for retail SME
    rwa_a10 = calculate_sa_rwa(ead_a10, rw_a10)

    result_a10 = ScenarioResult(
        scenario_id="A10",
        scenario_group="A",
        description="SME retail - 75% RW",
        exposure_reference="LOAN_RTL_SME_001",
        counterparty_reference="RTL_SME_001",
        approach="SA",
        exposure_class="RETAIL_SME",
        ead=ead_a10,
        risk_weight=rw_a10,
        rwa=rwa_a10,
        calculation_details={
            "counterparty_name": cpty_a10["counterparty_name"] if cpty_a10 else "SME",
            "sme_treatment": "retail",
            "turnover_threshold": "< £880k",
            "formula": "RWA = EAD × 75%",
            "calculation": f"RWA = £{ead_a10:,.0f} × {rw_a10*100:.0f}% = £{rwa_a10:,.0f}",
        },
        regulatory_reference="CRE20.66",
    )

    print(f"A10: EAD=£{ead_a10:,.0f}, RW={rw_a10*100:.0f}%, RWA=£{rwa_a10:,.0f}")
    return (result_a10,)


@app.cell
def _(mo):
    """Summary Section."""
    mo.md("""
    ---
    ## Summary: Group A Results
    """)
    return


@app.cell
def _(
    mo,
    pl,
    result_a1,
    result_a10,
    result_a2,
    result_a3,
    result_a4,
    result_a5,
    result_a6,
    result_a7,
    result_a8,
    result_a9,
):
    """Compile all Group A results."""
    group_a_results = [
        result_a1, result_a2, result_a3, result_a4, result_a5,
        result_a6, result_a7, result_a8, result_a9, result_a10,
    ]

    # Create summary DataFrame
    summary_data = []
    for r in group_a_results:
        summary_data.append({
            "Scenario": r.scenario_id,
            "Description": r.description,
            "EAD (£)": f"{r.ead:,.0f}",
            "Risk Weight": f"{r.risk_weight*100:.0f}%",
            "RWA (£)": f"{r.rwa:,.0f}",
            "Reference": r.regulatory_reference,
        })

    summary_df = pl.DataFrame(summary_data)
    mo.ui.table(summary_df)
    return (group_a_results,)


@app.cell
def _(group_a_results):
    """Export function for use by main workbook."""
    def get_group_a_results():
        """Return all Group A scenario results."""
        return group_a_results
    return


if __name__ == "__main__":
    app.run()
