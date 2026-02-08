"""
Group CRR-A: CRR Standardised Approach (SA) Scenarios

Scenarios CRR-A1 to CRR-A12 covering CRR SA risk weight lookups for different
exposure classes: sovereign, institution, corporate, retail, real estate,
and SME supporting factor.

Usage:
    uv run marimo edit workbooks/crr_expected_outputs/scenarios/group_crr_a_sa.py

Key CRR References:
    - Art. 114: Sovereign risk weights
    - Art. 120-121: Institution risk weights
    - Art. 122: Corporate risk weights
    - Art. 123: Retail risk weight (75%)
    - Art. 125: Residential mortgage (35%/75% split at 80% LTV)
    - Art. 126: Commercial real estate
    - Art. 501: SME supporting factor (0.7619)
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
    from workbooks.crr_expected_outputs.calculations.crr_risk_weights import (
        get_cgcb_rw,
        get_institution_rw,
        get_corporate_rw,
        get_retail_rw,
        get_residential_mortgage_rw,
        get_commercial_re_rw,
        calculate_sa_rwa,
    )
    from workbooks.crr_expected_outputs.calculations.crr_ccf import (
        get_ccf,
        calculate_ead_off_balance_sheet,
    )
    from workbooks.crr_expected_outputs.calculations.crr_supporting_factors import (
        apply_sme_supporting_factor,
        is_sme_eligible,
    )
    return (
        Decimal,
        apply_sme_supporting_factor,
        calculate_ead_off_balance_sheet,
        calculate_sa_rwa,
        get_ccf,
        get_commercial_re_rw,
        get_corporate_rw,
        get_institution_rw,
        get_residential_mortgage_rw,
        get_retail_rw,
        get_cgcb_rw,
        is_sme_eligible,
        load_fixtures,
        mo,
        pl,
    )


@app.cell
def _(mo):
    """Header."""
    mo.md("""
    # Group CRR-A: CRR Standardised Approach Scenarios

    This workbook calculates expected RWA values for CRR SA scenarios CRR-A1 to CRR-A12.

    **Regulatory Framework:** CRR (Capital Requirements Regulation)
    **Effective:** Until 31 December 2026

    **Key CRR References:**
    - Art. 114: Sovereign risk weights (0% to 150% based on CQS)
    - Art. 120-121: Institution risk weights (UK deviation: 30% for CQS 2)
    - Art. 122: Corporate risk weights (20% to 150% based on CQS)
    - Art. 123: Retail risk weight (75%)
    - Art. 125: Residential mortgage (35% for LTV ≤ 80%, 75% on excess)
    - Art. 126: Commercial real estate (50% for LTV ≤ 50% with income cover)
    - Art. 501: SME supporting factor (0.7619)

    **Key differences from Basel 3.1:**
    - SME supporting factor available (reduces RWA by ~24%)
    - Simpler residential mortgage treatment (35%/75% split vs LTV bands)
    - No output floor
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
    class CRRScenarioResult:
        """Container for a single CRR scenario calculation result."""
        scenario_id: str
        scenario_group: str
        description: str
        exposure_reference: str
        counterparty_reference: str
        approach: str
        exposure_class: str
        ead: float
        risk_weight: float
        rwa_before_sf: float
        supporting_factor: float
        rwa_after_sf: float
        calculation_details: dict
        regulatory_reference: str

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)
    return (CRRScenarioResult,)


@app.cell
def _(mo):
    """Scenario CRR-A1 Header."""
    mo.md("""
    ---
    ## Scenario CRR-A1: UK Sovereign - 0% Risk Weight

    **Input:** £1m loan to UK Government (CQS 1)
    **Expected:** 0% RW, £0 RWA
    **Reference:** CRR Art. 114
    """)
    return


@app.cell
def _(CRRScenarioResult, Decimal, calculate_sa_rwa, fixtures, get_cgcb_rw):
    """Calculate Scenario CRR-A1: UK Sovereign."""
    # Load data
    loan_a1 = fixtures.get_loan("LOAN_SOV_UK_001")
    cpty_a1 = fixtures.get_counterparty("SOV_UK_001")
    rating_a1 = fixtures.get_rating("SOV_UK_001")

    # Get CQS from rating (UK Government is CQS 1)
    cqs_a1 = rating_a1["cqs"] if rating_a1 else 1

    # Calculate
    ead_a1 = Decimal(str(loan_a1["drawn_amount"]))
    rw_a1 = get_cgcb_rw(cqs_a1)
    rwa_a1 = calculate_sa_rwa(ead_a1, rw_a1)

    # Create result (no SME factor for sovereign)
    result_crr_a1 = CRRScenarioResult(
        scenario_id="CRR-A1",
        scenario_group="CRR-A",
        description="UK Sovereign exposure - 0% RW",
        exposure_reference="LOAN_SOV_UK_001",
        counterparty_reference="SOV_UK_001",
        approach="SA",
        exposure_class="CENTRAL_GOVT_CENTRAL_BANK",
        ead=float(ead_a1),
        risk_weight=float(rw_a1),
        rwa_before_sf=float(rwa_a1),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a1),
        calculation_details={
            "counterparty_name": cpty_a1["counterparty_name"],
            "country_code": cpty_a1["country_code"],
            "cqs": cqs_a1,
            "formula": "RWA = EAD × RW",
            "calculation": f"RWA = £{ead_a1:,.0f} × {rw_a1*100:.0f}% = £{rwa_a1:,.0f}",
        },
        regulatory_reference="CRR Art. 114",
    )

    print(f"CRR-A1: EAD=£{ead_a1:,.0f}, RW={rw_a1*100:.0f}%, RWA=£{rwa_a1:,.0f}")
    return (result_crr_a1,)


@app.cell
def _(mo):
    """Scenario CRR-A2 Header."""
    mo.md("""
    ---
    ## Scenario CRR-A2: Unrated Corporate - 100% Risk Weight

    **Input:** £1m loan to unrated corporate
    **Expected:** 100% RW, £1m RWA
    **Reference:** CRR Art. 122
    """)
    return


@app.cell
def _(CRRScenarioResult, Decimal, calculate_sa_rwa, fixtures, get_corporate_rw):
    """Calculate Scenario CRR-A2: Unrated Corporate."""
    loan_a2 = fixtures.get_loan("LOAN_CORP_UR_001")
    cpty_a2 = fixtures.get_counterparty("CORP_UR_001")
    rating_a2 = fixtures.get_rating("CORP_UR_001")

    # Unrated = None for CQS
    cqs_a2 = rating_a2["cqs"] if rating_a2 else None

    ead_a2 = Decimal(str(loan_a2["drawn_amount"]))
    rw_a2 = get_corporate_rw(cqs_a2)
    rwa_a2 = calculate_sa_rwa(ead_a2, rw_a2)

    result_crr_a2 = CRRScenarioResult(
        scenario_id="CRR-A2",
        scenario_group="CRR-A",
        description="Unrated corporate - 100% RW",
        exposure_reference="LOAN_CORP_UR_001",
        counterparty_reference="CORP_UR_001",
        approach="SA",
        exposure_class="CORPORATE",
        ead=float(ead_a2),
        risk_weight=float(rw_a2),
        rwa_before_sf=float(rwa_a2),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a2),
        calculation_details={
            "counterparty_name": cpty_a2["counterparty_name"],
            "cqs": cqs_a2,
            "rating_status": "unrated",
            "formula": "RWA = EAD × RW",
            "calculation": f"RWA = £{ead_a2:,.0f} × {rw_a2*100:.0f}% = £{rwa_a2:,.0f}",
        },
        regulatory_reference="CRR Art. 122",
    )

    print(f"CRR-A2: EAD=£{ead_a2:,.0f}, RW={rw_a2*100:.0f}%, RWA=£{rwa_a2:,.0f}")
    return (result_crr_a2,)


@app.cell
def _(mo):
    """Scenario CRR-A3 Header."""
    mo.md("""
    ---
    ## Scenario CRR-A3: Rated Corporate CQS 2 - 50% Risk Weight

    **Input:** £1m loan to A-rated corporate
    **Expected:** 50% RW, £500k RWA
    **Reference:** CRR Art. 122
    """)
    return


@app.cell
def _(CRRScenarioResult, Decimal, calculate_sa_rwa, fixtures, get_corporate_rw):
    """Calculate Scenario CRR-A3: Rated Corporate CQS 2."""
    loan_a3 = fixtures.get_loan("LOAN_CORP_UK_003")
    cpty_a3 = fixtures.get_counterparty("CORP_UK_003")
    rating_a3 = fixtures.get_rating("CORP_UK_003")

    cqs_a3 = rating_a3["cqs"] if rating_a3 else 2

    ead_a3 = Decimal(str(loan_a3["drawn_amount"]))
    rw_a3 = get_corporate_rw(cqs_a3)
    rwa_a3 = calculate_sa_rwa(ead_a3, rw_a3)

    result_crr_a3 = CRRScenarioResult(
        scenario_id="CRR-A3",
        scenario_group="CRR-A",
        description="Rated corporate CQS 2 - 50% RW",
        exposure_reference="LOAN_CORP_UK_003",
        counterparty_reference="CORP_UK_003",
        approach="SA",
        exposure_class="CORPORATE",
        ead=float(ead_a3),
        risk_weight=float(rw_a3),
        rwa_before_sf=float(rwa_a3),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a3),
        calculation_details={
            "counterparty_name": cpty_a3["counterparty_name"],
            "cqs": cqs_a3,
            "rating_value": rating_a3["rating_value"] if rating_a3 else "A",
            "formula": "RWA = EAD × RW",
            "calculation": f"RWA = £{ead_a3:,.0f} × {rw_a3*100:.0f}% = £{rwa_a3:,.0f}",
        },
        regulatory_reference="CRR Art. 122",
    )

    print(f"CRR-A3: EAD=£{ead_a3:,.0f}, RW={rw_a3*100:.0f}%, RWA=£{rwa_a3:,.0f}")
    return (result_crr_a3,)


@app.cell
def _(mo):
    """Scenario CRR-A4 Header."""
    mo.md("""
    ---
    ## Scenario CRR-A4: UK Institution CQS 2 - 30% Risk Weight (UK Deviation)

    **Input:** £1m loan to UK bank with CQS 2 rating
    **Expected:** 30% RW, £300k RWA (UK deviation from standard 50%)
    **Reference:** CRR Art. 120-121 (UK deviation)
    """)
    return


@app.cell
def _(CRRScenarioResult, Decimal, calculate_sa_rwa, fixtures, get_institution_rw):
    """Calculate Scenario CRR-A4: UK Institution CQS 2."""
    loan_a4 = fixtures.get_loan("LOAN_INST_UK_003")
    cpty_a4 = fixtures.get_counterparty("INST_UK_003")
    rating_a4 = fixtures.get_rating("INST_UK_003")

    cqs_a4 = rating_a4["cqs"] if rating_a4 else 2

    ead_a4 = Decimal(str(loan_a4["drawn_amount"]))
    # Use UK deviation for CQS 2 institutions
    rw_a4 = get_institution_rw(cqs_a4, country="GB", use_uk_deviation=True)
    rwa_a4 = calculate_sa_rwa(ead_a4, rw_a4)

    result_crr_a4 = CRRScenarioResult(
        scenario_id="CRR-A4",
        scenario_group="CRR-A",
        description="UK Institution CQS 2 - 30% RW (UK deviation)",
        exposure_reference="LOAN_INST_UK_003",
        counterparty_reference="INST_UK_003",
        approach="SA",
        exposure_class="INSTITUTION",
        ead=float(ead_a4),
        risk_weight=float(rw_a4),
        rwa_before_sf=float(rwa_a4),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a4),
        calculation_details={
            "counterparty_name": cpty_a4["counterparty_name"],
            "cqs": cqs_a4,
            "uk_deviation": True,
            "standard_rw": 0.50,
            "uk_rw": 0.30,
            "formula": "RWA = EAD × RW",
            "calculation": f"RWA = £{ead_a4:,.0f} × {rw_a4*100:.0f}% = £{rwa_a4:,.0f}",
        },
        regulatory_reference="CRR Art. 120-121",
    )

    print(f"CRR-A4: EAD=£{ead_a4:,.0f}, RW={rw_a4*100:.0f}%, RWA=£{rwa_a4:,.0f}")
    return (result_crr_a4,)


@app.cell
def _(mo):
    """Scenario CRR-A5 Header."""
    mo.md("""
    ---
    ## Scenario CRR-A5: Residential Mortgage 60% LTV - 35% Risk Weight

    **Input:** £500k mortgage, £833k property value (60% LTV)
    **Expected:** 35% RW, £175k RWA

    **CRR Treatment (Art. 125):**
    - LTV ≤ 80%: 35% on whole exposure
    - LTV > 80%: 35% on portion up to 80%, 75% on excess

    *Note: Basel 3.1 uses granular LTV bands (20% at 60% LTV)*
    **Reference:** CRR Art. 125
    """)
    return


@app.cell
def _(
    CRRScenarioResult,
    Decimal,
    calculate_sa_rwa,
    fixtures,
    get_residential_mortgage_rw,
    pl,
):
    """Calculate Scenario CRR-A5: Residential Mortgage 60% LTV."""
    loan_a5 = fixtures.get_loan("LOAN_RTL_MTG_001")
    cpty_a5 = fixtures.get_counterparty("RTL_MTG_001")

    # Get collateral for LTV
    coll_a5 = fixtures.collateral.filter(
        pl.col("beneficiary_reference") == "LOAN_RTL_MTG_001"
    ).collect()

    # LTV from collateral record or calculate
    if coll_a5.height > 0:
        ltv_a5 = Decimal(str(coll_a5[0, "property_ltv"]))
    else:
        # 60% LTV from scenario definition
        ltv_a5 = Decimal("0.60")

    ead_a5 = Decimal(str(loan_a5["drawn_amount"]))
    rw_a5, rw_desc_a5 = get_residential_mortgage_rw(ltv_a5)
    rwa_a5 = calculate_sa_rwa(ead_a5, rw_a5)

    result_crr_a5 = CRRScenarioResult(
        scenario_id="CRR-A5",
        scenario_group="CRR-A",
        description="Residential mortgage 60% LTV - 35% RW",
        exposure_reference="LOAN_RTL_MTG_001",
        counterparty_reference="RTL_MTG_001",
        approach="SA",
        exposure_class="RETAIL_MORTGAGE",
        ead=float(ead_a5),
        risk_weight=float(rw_a5),
        rwa_before_sf=float(rwa_a5),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a5),
        calculation_details={
            "counterparty_name": cpty_a5["counterparty_name"] if cpty_a5 else "Mortgage borrower",
            "ltv": float(ltv_a5),
            "property_value": float(ead_a5 / ltv_a5),
            "ltv_treatment": rw_desc_a5,
            "crr_vs_basel31": "CRR 35% vs Basel 3.1 20% at 60% LTV",
            "formula": "RWA = EAD × RW",
            "calculation": f"RWA = £{ead_a5:,.0f} × {rw_a5*100:.0f}% = £{rwa_a5:,.0f}",
        },
        regulatory_reference="CRR Art. 125",
    )

    print(f"CRR-A5: EAD=£{ead_a5:,.0f}, LTV={ltv_a5*100:.0f}%, RW={rw_a5*100:.0f}%, RWA=£{rwa_a5:,.0f}")
    return (result_crr_a5,)


@app.cell
def _(mo):
    """Scenario CRR-A6 Header."""
    mo.md("""
    ---
    ## Scenario CRR-A6: Residential Mortgage 85% LTV - Split Treatment

    **Input:** £850k mortgage, £1m property value (85% LTV)
    **Expected:** Weighted average RW, ~42% effective RW

    **CRR Treatment (Art. 125):**
    - 35% on portion up to 80% LTV (80/85 = 94.1% of exposure)
    - 75% on excess above 80% LTV (5/85 = 5.9% of exposure)
    - Effective RW = (0.941 × 35%) + (0.059 × 75%) ≈ 37.4%

    *Note: Basel 3.1 would apply 45% RW for 85% LTV*
    **Reference:** CRR Art. 125
    """)
    return


@app.cell
def _(
    CRRScenarioResult,
    Decimal,
    calculate_sa_rwa,
    fixtures,
    get_residential_mortgage_rw,
):
    """Calculate Scenario CRR-A6: Residential Mortgage 85% LTV."""
    loan_a6 = fixtures.get_loan("LOAN_RTL_MTG_002")
    cpty_a6 = fixtures.get_counterparty("RTL_MTG_002")

    ltv_a6 = Decimal("0.85")  # 85% LTV

    ead_a6 = Decimal(str(loan_a6["drawn_amount"]))
    rw_a6, rw_desc_a6 = get_residential_mortgage_rw(ltv_a6)
    rwa_a6 = calculate_sa_rwa(ead_a6, rw_a6)

    result_crr_a6 = CRRScenarioResult(
        scenario_id="CRR-A6",
        scenario_group="CRR-A",
        description="Residential mortgage 85% LTV - split treatment",
        exposure_reference="LOAN_RTL_MTG_002",
        counterparty_reference="RTL_MTG_002",
        approach="SA",
        exposure_class="RETAIL_MORTGAGE",
        ead=float(ead_a6),
        risk_weight=float(rw_a6),
        rwa_before_sf=float(rwa_a6),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a6),
        calculation_details={
            "counterparty_name": cpty_a6["counterparty_name"] if cpty_a6 else "Mortgage borrower",
            "ltv": float(ltv_a6),
            "property_value": float(ead_a6 / ltv_a6),
            "ltv_treatment": rw_desc_a6,
            "portion_at_35pct": 0.80 / 0.85,
            "portion_at_75pct": 0.05 / 0.85,
            "crr_vs_basel31": "CRR ~37% (split) vs Basel 3.1 45% at 85% LTV",
            "formula": "RWA = EAD × weighted_avg_RW",
            "calculation": f"RWA = £{ead_a6:,.0f} × {rw_a6*100:.1f}% = £{rwa_a6:,.0f}",
        },
        regulatory_reference="CRR Art. 125",
    )

    print(f"CRR-A6: EAD=£{ead_a6:,.0f}, LTV={ltv_a6*100:.0f}%, RW={rw_a6*100:.1f}%, RWA=£{rwa_a6:,.0f}")
    return (result_crr_a6,)


@app.cell
def _(mo):
    """Scenario CRR-A7 Header."""
    mo.md("""
    ---
    ## Scenario CRR-A7: Commercial Real Estate 40% LTV - 50% Risk Weight

    **Input:** £400k loan, £1m property value (40% LTV), income cover met
    **Expected:** 50% RW, £200k RWA

    **CRR Treatment (Art. 126):**
    - LTV ≤ 50% AND income cover ≥ 1.5x interest: 50% RW
    - Otherwise: 100% RW (no preferential treatment)

    **Reference:** CRR Art. 126
    """)
    return


@app.cell
def _(CRRScenarioResult, Decimal, calculate_sa_rwa, get_commercial_re_rw):
    """Calculate Scenario CRR-A7: Commercial Real Estate 40% LTV."""
    ltv_a7 = Decimal("0.40")
    ead_a7 = Decimal("400000")  # £400k loan
    has_income_cover_a7 = True  # Meets 1.5x interest coverage

    rw_a7, rw_desc_a7 = get_commercial_re_rw(ltv_a7, has_income_cover=has_income_cover_a7)
    rwa_a7 = calculate_sa_rwa(ead_a7, rw_a7)

    result_crr_a7 = CRRScenarioResult(
        scenario_id="CRR-A7",
        scenario_group="CRR-A",
        description="Commercial real estate 40% LTV - 50% RW",
        exposure_reference="LOAN_CRE_001",
        counterparty_reference="CORP_CRE_001",
        approach="SA",
        exposure_class="CRE",
        ead=float(ead_a7),
        risk_weight=float(rw_a7),
        rwa_before_sf=float(rwa_a7),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a7),
        calculation_details={
            "ltv": float(ltv_a7),
            "property_value": float(ead_a7 / ltv_a7),
            "income_cover_met": has_income_cover_a7,
            "treatment": rw_desc_a7,
            "property_type": "commercial",
            "formula": "RWA = EAD × RW",
            "calculation": f"RWA = £{ead_a7:,.0f} × {rw_a7*100:.0f}% = £{rwa_a7:,.0f}",
        },
        regulatory_reference="CRR Art. 126",
    )

    print(f"CRR-A7: EAD=£{ead_a7:,.0f}, LTV={ltv_a7*100:.0f}%, RW={rw_a7*100:.0f}%, RWA=£{rwa_a7:,.0f}")
    return (result_crr_a7,)


@app.cell
def _(mo):
    """Scenario CRR-A8 Header."""
    mo.md("""
    ---
    ## Scenario CRR-A8: Off-Balance Sheet Commitment - 50% CCF

    **Input:** £1m undrawn committed facility (> 1 year original maturity)
    **Expected:** 50% CCF, £500k EAD, 100% RW, £500k RWA
    **Reference:** CRR Art. 111
    """)
    return


@app.cell
def _(
    CRRScenarioResult,
    Decimal,
    calculate_ead_off_balance_sheet,
    calculate_sa_rwa,
    get_corporate_rw,
):
    """Calculate Scenario CRR-A8: Off-Balance Sheet Commitment."""
    nominal_a8 = Decimal("1000000")  # £1m commitment
    commitment_type_a8 = "undrawn_long_term"

    ead_a8, ccf_a8, ead_desc_a8 = calculate_ead_off_balance_sheet(
        nominal_amount=nominal_a8,
        commitment_type=commitment_type_a8,
        original_maturity_years=2.0,
    )

    # Assume unrated corporate for RW
    rw_a8 = get_corporate_rw(None)  # 100% for unrated
    rwa_a8 = calculate_sa_rwa(ead_a8, rw_a8)

    result_crr_a8 = CRRScenarioResult(
        scenario_id="CRR-A8",
        scenario_group="CRR-A",
        description="Off-balance sheet commitment - 50% CCF",
        exposure_reference="CONT_CCF_001",
        counterparty_reference="CORP_OBS_001",
        approach="SA",
        exposure_class="CORPORATE",
        ead=float(ead_a8),
        risk_weight=float(rw_a8),
        rwa_before_sf=float(rwa_a8),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a8),
        calculation_details={
            "nominal_amount": float(nominal_a8),
            "commitment_type": commitment_type_a8,
            "ccf": float(ccf_a8),
            "ead_description": ead_desc_a8,
            "formula": "EAD = Nominal × CCF, then RWA = EAD × RW",
            "ead_calculation": f"EAD = £{nominal_a8:,.0f} × {ccf_a8*100:.0f}% = £{ead_a8:,.0f}",
            "rwa_calculation": f"RWA = £{ead_a8:,.0f} × {rw_a8*100:.0f}% = £{rwa_a8:,.0f}",
        },
        regulatory_reference="CRR Art. 111",
    )

    print(f"CRR-A8: Nominal=£{nominal_a8:,.0f}, CCF={ccf_a8*100:.0f}%, EAD=£{ead_a8:,.0f}, RWA=£{rwa_a8:,.0f}")
    return (result_crr_a8,)


@app.cell
def _(mo):
    """Scenario CRR-A9 Header."""
    mo.md("""
    ---
    ## Scenario CRR-A9: Retail Exposure - 75% Risk Weight

    **Input:** £50k personal loan
    **Expected:** 75% RW, £37.5k RWA
    **Reference:** CRR Art. 123
    """)
    return


@app.cell
def _(CRRScenarioResult, Decimal, calculate_sa_rwa, fixtures, get_retail_rw):
    """Calculate Scenario CRR-A9: Retail Exposure."""
    loan_a9 = fixtures.get_loan("LOAN_RTL_IND_001")
    cpty_a9 = fixtures.get_counterparty("RTL_IND_001")

    ead_a9 = Decimal(str(loan_a9["drawn_amount"]))
    rw_a9 = get_retail_rw()  # 75%
    rwa_a9 = calculate_sa_rwa(ead_a9, rw_a9)

    result_crr_a9 = CRRScenarioResult(
        scenario_id="CRR-A9",
        scenario_group="CRR-A",
        description="Retail exposure - 75% RW",
        exposure_reference="LOAN_RTL_IND_001",
        counterparty_reference="RTL_IND_001",
        approach="SA",
        exposure_class="RETAIL",
        ead=float(ead_a9),
        risk_weight=float(rw_a9),
        rwa_before_sf=float(rwa_a9),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a9),
        calculation_details={
            "counterparty_name": cpty_a9["counterparty_name"] if cpty_a9 else "Individual",
            "formula": "RWA = EAD × 75%",
            "calculation": f"RWA = £{ead_a9:,.0f} × {rw_a9*100:.0f}% = £{rwa_a9:,.0f}",
        },
        regulatory_reference="CRR Art. 123",
    )

    print(f"CRR-A9: EAD=£{ead_a9:,.0f}, RW={rw_a9*100:.0f}%, RWA=£{rwa_a9:,.0f}")
    return (result_crr_a9,)


@app.cell
def _(mo):
    """Scenario CRR-A10 Header."""
    mo.md("""
    ---
    ## Scenario CRR-A10: SME Corporate with Supporting Factor - 100% RW × 0.7619

    **Input:** £1m loan to SME corporate (turnover £30m < £44m threshold)
    **Expected:** 100% RW, then × 0.7619 SME factor = £761.9k RWA

    **CRR Treatment (Art. 501):**
    - SME supporting factor = 0.7619 for exposures < €50m (£44m)
    - Reduces RWA by approximately 24%
    - **NOT available under Basel 3.1**

    **Reference:** CRR Art. 122, Art. 501
    """)
    return


@app.cell
def _(
    CRRScenarioResult,
    Decimal,
    apply_sme_supporting_factor,
    calculate_sa_rwa,
    fixtures,
    get_corporate_rw,
):
    """Calculate Scenario CRR-A10: SME Corporate with Supporting Factor."""
    loan_a10 = fixtures.get_loan("LOAN_CORP_SME_001")
    cpty_a10 = fixtures.get_counterparty("CORP_SME_001")

    # SME with turnover < £44m threshold
    turnover_a10 = Decimal("30000000")  # £30m

    ead_a10 = Decimal(str(loan_a10["drawn_amount"]))
    rw_a10 = get_corporate_rw(None)  # 100% for unrated
    rwa_before_sf_a10 = calculate_sa_rwa(ead_a10, rw_a10)

    # Apply SME supporting factor
    rwa_after_sf_a10, sf_applied_a10, sf_desc_a10 = apply_sme_supporting_factor(
        rwa=rwa_before_sf_a10,
        is_sme=True,
        turnover=turnover_a10,
        currency="GBP",
    )

    sf_a10 = Decimal("0.7619") if sf_applied_a10 else Decimal("1.0")

    result_crr_a10 = CRRScenarioResult(
        scenario_id="CRR-A10",
        scenario_group="CRR-A",
        description="SME corporate with supporting factor",
        exposure_reference="LOAN_CORP_SME_001",
        counterparty_reference="CORP_SME_001",
        approach="SA",
        exposure_class="CORPORATE_SME",
        ead=float(ead_a10),
        risk_weight=float(rw_a10),
        rwa_before_sf=float(rwa_before_sf_a10),
        supporting_factor=float(sf_a10),
        rwa_after_sf=float(rwa_after_sf_a10),
        calculation_details={
            "counterparty_name": cpty_a10["counterparty_name"] if cpty_a10 else "SME Corporate",
            "turnover": float(turnover_a10),
            "turnover_threshold": 44000000,  # £44m
            "sme_factor_applied": sf_applied_a10,
            "sme_factor_description": sf_desc_a10,
            "crr_vs_basel31": "SME factor NOT available under Basel 3.1",
            "formula": "RWA = EAD × RW × SME_factor",
            "calculation": f"RWA = £{ead_a10:,.0f} × {rw_a10*100:.0f}% × 0.7619 = £{rwa_after_sf_a10:,.0f}",
        },
        regulatory_reference="CRR Art. 122, Art. 501",
    )

    print(f"CRR-A10: EAD=£{ead_a10:,.0f}, RW={rw_a10*100:.0f}%, SF=0.7619, RWA=£{rwa_after_sf_a10:,.0f}")
    return (result_crr_a10,)


@app.cell
def _(mo):
    """Scenario CRR-A11 Header."""
    mo.md("""
    ---
    ## Scenario CRR-A11: SME Retail with Supporting Factor - 75% RW × 0.7619

    **Input:** £500k loan to SME retail (turnover < £880k)
    **Expected:** 75% RW, then × 0.7619 SME factor = £285.7k RWA

    **CRR Treatment (Art. 501):**
    - SME supporting factor applies to retail SME exposures too
    - Combined effect: 75% × 0.7619 = ~57% effective RW
    - **NOT available under Basel 3.1**

    **Reference:** CRR Art. 123, Art. 501
    """)
    return


@app.cell
def _(
    CRRScenarioResult,
    Decimal,
    apply_sme_supporting_factor,
    calculate_sa_rwa,
    fixtures,
    get_retail_rw,
):
    """Calculate Scenario CRR-A11: SME Retail with Supporting Factor."""
    loan_a11 = fixtures.get_loan("LOAN_RTL_SME_001")
    cpty_a11 = fixtures.get_counterparty("RTL_SME_001")

    # SME retail with turnover < £880k
    turnover_a11 = Decimal("750000")  # £750k

    ead_a11 = Decimal(str(loan_a11["drawn_amount"]))
    rw_a11 = get_retail_rw()  # 75%
    rwa_before_sf_a11 = calculate_sa_rwa(ead_a11, rw_a11)

    # Apply SME supporting factor
    rwa_after_sf_a11, sf_applied_a11, sf_desc_a11 = apply_sme_supporting_factor(
        rwa=rwa_before_sf_a11,
        is_sme=True,
        turnover=turnover_a11,
        currency="GBP",
    )

    sf_a11 = Decimal("0.7619") if sf_applied_a11 else Decimal("1.0")

    result_crr_a11 = CRRScenarioResult(
        scenario_id="CRR-A11",
        scenario_group="CRR-A",
        description="SME retail with supporting factor",
        exposure_reference="LOAN_RTL_SME_001",
        counterparty_reference="RTL_SME_001",
        approach="SA",
        exposure_class="RETAIL_SME",
        ead=float(ead_a11),
        risk_weight=float(rw_a11),
        rwa_before_sf=float(rwa_before_sf_a11),
        supporting_factor=float(sf_a11),
        rwa_after_sf=float(rwa_after_sf_a11),
        calculation_details={
            "counterparty_name": cpty_a11["counterparty_name"] if cpty_a11 else "SME Retail",
            "turnover": float(turnover_a11),
            "sme_factor_applied": sf_applied_a11,
            "sme_factor_description": sf_desc_a11,
            "effective_rw": float(rw_a11 * sf_a11),
            "crr_vs_basel31": "SME factor NOT available under Basel 3.1",
            "formula": "RWA = EAD × RW × SME_factor",
            "calculation": f"RWA = £{ead_a11:,.0f} × {rw_a11*100:.0f}% × 0.7619 = £{rwa_after_sf_a11:,.0f}",
        },
        regulatory_reference="CRR Art. 123, Art. 501",
    )

    print(f"CRR-A11: EAD=£{ead_a11:,.0f}, RW={rw_a11*100:.0f}%, SF=0.7619, RWA=£{rwa_after_sf_a11:,.0f}")
    return (result_crr_a11,)


@app.cell
def _(mo):
    """Scenario CRR-A12 Header."""
    mo.md("""
    ---
    ## Scenario CRR-A12: Large Corporate (No Supporting Factor)

    **Input:** £10m loan to large corporate (turnover £500m > £44m threshold)
    **Expected:** 100% RW, no SME factor, £10m RWA

    **CRR Treatment:**
    - Turnover > £44m (€50m) = not eligible for SME factor
    - Full 100% RW applies

    **Reference:** CRR Art. 122
    """)
    return


@app.cell
def _(
    CRRScenarioResult,
    Decimal,
    apply_sme_supporting_factor,
    calculate_sa_rwa,
    fixtures,
    get_corporate_rw,
):
    """Calculate Scenario CRR-A12: Large Corporate (No Supporting Factor)."""
    loan_a12 = fixtures.get_loan("LOAN_CORP_UK_001")
    cpty_a12 = fixtures.get_counterparty("CORP_UK_001")

    # Large corporate with turnover > £44m threshold
    turnover_a12 = Decimal("500000000")  # £500m

    ead_a12 = Decimal(str(loan_a12["drawn_amount"]))
    rw_a12 = get_corporate_rw(None)  # 100% for unrated
    rwa_before_sf_a12 = calculate_sa_rwa(ead_a12, rw_a12)

    # Apply SME supporting factor (should NOT apply)
    rwa_after_sf_a12, sf_applied_a12, sf_desc_a12 = apply_sme_supporting_factor(
        rwa=rwa_before_sf_a12,
        is_sme=False,
        turnover=turnover_a12,
        currency="GBP",
    )

    sf_a12 = Decimal("1.0")  # No factor applied

    result_crr_a12 = CRRScenarioResult(
        scenario_id="CRR-A12",
        scenario_group="CRR-A",
        description="Large corporate (no supporting factor)",
        exposure_reference="LOAN_CORP_UK_001",
        counterparty_reference="CORP_UK_001",
        approach="SA",
        exposure_class="CORPORATE",
        ead=float(ead_a12),
        risk_weight=float(rw_a12),
        rwa_before_sf=float(rwa_before_sf_a12),
        supporting_factor=float(sf_a12),
        rwa_after_sf=float(rwa_after_sf_a12),
        calculation_details={
            "counterparty_name": cpty_a12["counterparty_name"] if cpty_a12 else "Large Corporate",
            "turnover": float(turnover_a12),
            "turnover_threshold": 44000000,  # £44m
            "sme_factor_applied": sf_applied_a12,
            "sme_factor_description": sf_desc_a12,
            "formula": "RWA = EAD × RW (no SME factor)",
            "calculation": f"RWA = £{ead_a12:,.0f} × {rw_a12*100:.0f}% = £{rwa_after_sf_a12:,.0f}",
        },
        regulatory_reference="CRR Art. 122",
    )

    print(f"CRR-A12: EAD=£{ead_a12:,.0f}, RW={rw_a12*100:.0f}%, SF=1.0, RWA=£{rwa_after_sf_a12:,.0f}")
    return (result_crr_a12,)


@app.cell
def _(mo):
    """Summary Section."""
    mo.md("""
    ---
    ## Summary: Group CRR-A Results

    Key CRR-specific observations:
    1. Residential mortgages use simpler 35%/75% split at 80% LTV (vs Basel 3.1 LTV bands)
    2. SME supporting factor (0.7619) reduces RWA by ~24% for eligible exposures
    3. UK deviation: Institution CQS 2 gets 30% RW (not standard 50%)
    """)
    return


@app.cell
def _(
    mo,
    pl,
    result_crr_a1,
    result_crr_a10,
    result_crr_a11,
    result_crr_a12,
    result_crr_a2,
    result_crr_a3,
    result_crr_a4,
    result_crr_a5,
    result_crr_a6,
    result_crr_a7,
    result_crr_a8,
    result_crr_a9,
):
    """Compile all Group CRR-A results."""
    group_crr_a_results = [
        result_crr_a1, result_crr_a2, result_crr_a3, result_crr_a4, result_crr_a5,
        result_crr_a6, result_crr_a7, result_crr_a8, result_crr_a9, result_crr_a10,
        result_crr_a11, result_crr_a12,
    ]

    # Create summary DataFrame
    summary_data = []
    for r in group_crr_a_results:
        summary_data.append({
            "Scenario": r.scenario_id,
            "Description": r.description,
            "EAD (£)": f"{r.ead:,.0f}",
            "Risk Weight": f"{r.risk_weight*100:.0f}%",
            "RWA Before SF (£)": f"{r.rwa_before_sf:,.0f}",
            "SF": f"{r.supporting_factor:.4f}" if r.supporting_factor != 1.0 else "-",
            "RWA After SF (£)": f"{r.rwa_after_sf:,.0f}",
            "Reference": r.regulatory_reference,
        })

    summary_df = pl.DataFrame(summary_data)
    mo.ui.table(summary_df)
    return (group_crr_a_results,)


@app.cell
def _(group_crr_a_results):
    """Export function for use by main workbook."""
    def get_group_crr_a_results():
        """Return all Group CRR-A scenario results."""
        return group_crr_a_results
    return (get_group_crr_a_results,)


if __name__ == "__main__":
    app.run()
