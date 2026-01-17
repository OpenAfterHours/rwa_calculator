"""
Group CRR-D: CRR Credit Risk Mitigation (CRM) Scenarios

Scenarios CRR-D1 to CRR-D6 covering CRM techniques under CRR:
- Collateral haircuts (financial collateral comprehensive approach)
- Guarantee substitution
- Maturity mismatch adjustments
- Currency mismatch haircuts

Usage:
    uv run marimo edit workbooks/crr_expected_outputs/scenarios/group_crr_d_crm.py

Key CRR References:
    - Art. 207-211: Eligibility of collateral
    - Art. 213-217: Unfunded credit protection (guarantees)
    - Art. 223: Adjusted collateral value
    - Art. 224: Supervisory haircuts
    - Art. 238: Maturity mismatch
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
        get_corporate_rw,
        get_institution_rw,
        calculate_sa_rwa,
    )
    from workbooks.crr_expected_outputs.calculations.crr_haircuts import (
        get_collateral_haircut,
        get_fx_haircut,
        calculate_adjusted_collateral_value,
        apply_maturity_mismatch,
    )
    from workbooks.crr_expected_outputs.data.crr_params import (
        CRR_HAIRCUTS,
        CRR_FX_HAIRCUT,
    )
    return (
        CRR_FX_HAIRCUT,
        CRR_HAIRCUTS,
        Decimal,
        apply_maturity_mismatch,
        calculate_adjusted_collateral_value,
        calculate_sa_rwa,
        get_collateral_haircut,
        get_corporate_rw,
        get_fx_haircut,
        get_institution_rw,
        load_fixtures,
        mo,
        pl,
    )


@app.cell
def _(mo):
    """Header."""
    mo.md("""
    # Group CRR-D: CRR Credit Risk Mitigation (CRM) Scenarios

    This workbook calculates expected RWA values for CRR CRM scenarios CRR-D1 to CRR-D6.

    **Regulatory Framework:** CRR (Capital Requirements Regulation)
    **Effective:** Until 31 December 2026

    **Key CRR CRM Features:**
    - **Financial Collateral Comprehensive Approach** - haircuts applied to collateral
    - **Supervisory haircuts** (Art. 224) - standard haircuts by collateral type
    - **Guarantee substitution** - replace borrower RW with guarantor RW
    - **Maturity mismatch adjustment** (Art. 238) - for collateral with shorter maturity
    - **Currency mismatch haircut** - 8% for FX mismatch

    **CRM Haircuts (Art. 224):**
    | Collateral Type | Haircut |
    |-----------------|---------|
    | Cash | 0% |
    | CQS 1 govt bonds (≤1y) | 0.5% |
    | CQS 1 govt bonds (1-5y) | 2% |
    | CQS 1 govt bonds (>5y) | 4% |
    | Main index equity | 15% |
    | Other equity | 25% |
    | Currency mismatch | +8% |
    """)
    return


@app.cell
def _(load_fixtures):
    """Load test fixtures."""
    fixtures = load_fixtures()
    return (fixtures,)


@app.cell
def _():
    """Scenario result dataclass for CRM."""
    from dataclasses import dataclass, asdict
    from typing import Any

    @dataclass
    class CRRCRMResult:
        """Container for a single CRR CRM scenario calculation result."""
        scenario_id: str
        scenario_group: str
        description: str
        exposure_reference: str
        counterparty_reference: str
        approach: str
        exposure_class: str
        # Exposure details
        exposure_value: float
        risk_weight_pre_crm: float
        rwa_pre_crm: float
        # CRM details
        crm_type: str
        collateral_value: float
        collateral_haircut: float
        fx_haircut: float
        maturity_adjustment: float
        adjusted_collateral_value: float
        # Post-CRM
        ead_post_crm: float
        risk_weight_post_crm: float
        rwa_post_crm: float
        rwa_reduction: float
        calculation_details: dict
        regulatory_reference: str

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)
    return (CRRCRMResult,)


@app.cell
def _(mo):
    """Scenario CRR-D1 Header."""
    mo.md("""
    ---
    ## Scenario CRR-D1: Cash Collateral (SA)

    **Input:** £1m corporate exposure, £500k cash collateral
    **Expected:** EAD reduced by collateral value (0% haircut)

    **CRR Treatment (Art. 207, 224):**
    - Cash = 0% haircut
    - EAD_adjusted = EAD - Collateral_adjusted
    - RWA on remaining exposure

    **Reference:** CRR Art. 207, 224
    """)
    return


@app.cell
def _(
    CRRCRMResult,
    Decimal,
    calculate_adjusted_collateral_value,
    calculate_sa_rwa,
    get_collateral_haircut,
    get_corporate_rw,
):
    """Calculate Scenario CRR-D1: Cash Collateral."""
    # Exposure
    exposure_d1 = Decimal("1000000")
    cqs_d1 = None  # Unrated corporate
    rw_d1 = get_corporate_rw(cqs_d1)  # 100%

    # Collateral
    coll_value_d1 = Decimal("500000")
    coll_haircut_d1 = get_collateral_haircut("cash")  # 0%
    fx_haircut_d1 = Decimal("0.00")  # Same currency

    # Calculate adjusted collateral
    coll_adjusted_d1 = calculate_adjusted_collateral_value(
        coll_value_d1, coll_haircut_d1, fx_haircut_d1
    )

    # Pre-CRM RWA
    rwa_pre_d1 = calculate_sa_rwa(exposure_d1, rw_d1)

    # Post-CRM EAD
    ead_post_d1 = exposure_d1 - coll_adjusted_d1
    rwa_post_d1 = calculate_sa_rwa(ead_post_d1, rw_d1)

    result_crr_d1 = CRRCRMResult(
        scenario_id="CRR-D1",
        scenario_group="CRR-D",
        description="Cash collateral - 0% haircut",
        exposure_reference="LOAN_CRM_D1",
        counterparty_reference="CORP_CRM_D1",
        approach="SA",
        exposure_class="CORPORATE",
        exposure_value=float(exposure_d1),
        risk_weight_pre_crm=float(rw_d1),
        rwa_pre_crm=float(rwa_pre_d1),
        crm_type="Cash collateral",
        collateral_value=float(coll_value_d1),
        collateral_haircut=float(coll_haircut_d1),
        fx_haircut=float(fx_haircut_d1),
        maturity_adjustment=1.0,
        adjusted_collateral_value=float(coll_adjusted_d1),
        ead_post_crm=float(ead_post_d1),
        risk_weight_post_crm=float(rw_d1),
        rwa_post_crm=float(rwa_post_d1),
        rwa_reduction=float(rwa_pre_d1 - rwa_post_d1),
        calculation_details={
            "collateral_type": "cash",
            "haircut": "0%",
            "formula": "EAD_adj = EAD - C × (1 - Hc - Hfx)",
            "calculation": f"EAD_adj = £{exposure_d1:,.0f} - £{coll_adjusted_d1:,.0f} = £{ead_post_d1:,.0f}",
        },
        regulatory_reference="CRR Art. 207, 224",
    )

    print(f"CRR-D1: Exposure=£{exposure_d1:,.0f}, Collateral=£{coll_value_d1:,.0f}")
    print(f"  Haircut={coll_haircut_d1*100:.0f}%, EAD_post=£{ead_post_d1:,.0f}, RWA=£{rwa_post_d1:,.0f}")
    return (result_crr_d1,)


@app.cell
def _(mo):
    """Scenario CRR-D2 Header."""
    mo.md("""
    ---
    ## Scenario CRR-D2: Government Bond Collateral

    **Input:** £1m corporate exposure, £600k UK gilts (5 year residual maturity)
    **Expected:** Collateral value reduced by 4% haircut (CQS 1, >5y)

    **CRR Treatment (Art. 224):**
    - CQS 1 sovereign bonds with residual maturity >5y: 4% haircut
    - Adjusted collateral = £600k × (1 - 0.04) = £576k

    **Reference:** CRR Art. 224
    """)
    return


@app.cell
def _(
    CRRCRMResult,
    Decimal,
    calculate_adjusted_collateral_value,
    calculate_sa_rwa,
    get_collateral_haircut,
    get_corporate_rw,
):
    """Calculate Scenario CRR-D2: Government Bond Collateral."""
    # Exposure
    exposure_d2 = Decimal("1000000")
    rw_d2 = get_corporate_rw(None)  # 100% unrated

    # Collateral - UK gilts (CQS 1, 5y maturity)
    coll_value_d2 = Decimal("600000")
    coll_haircut_d2 = get_collateral_haircut(
        "govt_bond", cqs=1, residual_maturity_years=6.0
    )  # 4% for CQS1 >5y
    fx_haircut_d2 = Decimal("0.00")

    # Calculate adjusted collateral
    coll_adjusted_d2 = calculate_adjusted_collateral_value(
        coll_value_d2, coll_haircut_d2, fx_haircut_d2
    )

    # Pre-CRM RWA
    rwa_pre_d2 = calculate_sa_rwa(exposure_d2, rw_d2)

    # Post-CRM EAD
    ead_post_d2 = exposure_d2 - coll_adjusted_d2
    rwa_post_d2 = calculate_sa_rwa(ead_post_d2, rw_d2)

    result_crr_d2 = CRRCRMResult(
        scenario_id="CRR-D2",
        scenario_group="CRR-D",
        description="Government bond collateral - 4% haircut",
        exposure_reference="LOAN_CRM_D2",
        counterparty_reference="CORP_CRM_D2",
        approach="SA",
        exposure_class="CORPORATE",
        exposure_value=float(exposure_d2),
        risk_weight_pre_crm=float(rw_d2),
        rwa_pre_crm=float(rwa_pre_d2),
        crm_type="Government bond",
        collateral_value=float(coll_value_d2),
        collateral_haircut=float(coll_haircut_d2),
        fx_haircut=float(fx_haircut_d2),
        maturity_adjustment=1.0,
        adjusted_collateral_value=float(coll_adjusted_d2),
        ead_post_crm=float(ead_post_d2),
        risk_weight_post_crm=float(rw_d2),
        rwa_post_crm=float(rwa_post_d2),
        rwa_reduction=float(rwa_pre_d2 - rwa_post_d2),
        calculation_details={
            "collateral_type": "UK gilts (CQS 1)",
            "residual_maturity": "6 years",
            "haircut": "4% (CQS 1, >5y)",
            "formula": "C_adj = C × (1 - Hc)",
            "calculation": f"C_adj = £{coll_value_d2:,.0f} × (1 - 4%) = £{coll_adjusted_d2:,.0f}",
        },
        regulatory_reference="CRR Art. 224",
    )

    print(f"CRR-D2: Collateral=£{coll_value_d2:,.0f}, Haircut={coll_haircut_d2*100:.1f}%")
    print(f"  Adjusted=£{coll_adjusted_d2:,.0f}, RWA=£{rwa_post_d2:,.0f}")
    return (result_crr_d2,)


@app.cell
def _(mo):
    """Scenario CRR-D3 Header."""
    mo.md("""
    ---
    ## Scenario CRR-D3: Equity Collateral (Main Index)

    **Input:** £1m corporate exposure, £400k listed equity (FTSE 100)
    **Expected:** 15% haircut for main index equity

    **CRR Treatment (Art. 224):**
    - Main index equity: 15% haircut
    - Other listed equity: 25% haircut

    **Reference:** CRR Art. 224
    """)
    return


@app.cell
def _(
    CRRCRMResult,
    Decimal,
    calculate_adjusted_collateral_value,
    calculate_sa_rwa,
    get_collateral_haircut,
    get_corporate_rw,
):
    """Calculate Scenario CRR-D3: Equity Collateral."""
    # Exposure
    exposure_d3 = Decimal("1000000")
    rw_d3 = get_corporate_rw(None)  # 100%

    # Collateral - main index equity
    coll_value_d3 = Decimal("400000")
    coll_haircut_d3 = get_collateral_haircut("equity", is_main_index=True)  # 15%
    fx_haircut_d3 = Decimal("0.00")

    # Calculate adjusted collateral
    coll_adjusted_d3 = calculate_adjusted_collateral_value(
        coll_value_d3, coll_haircut_d3, fx_haircut_d3
    )

    # Pre-CRM
    rwa_pre_d3 = calculate_sa_rwa(exposure_d3, rw_d3)

    # Post-CRM
    ead_post_d3 = exposure_d3 - coll_adjusted_d3
    rwa_post_d3 = calculate_sa_rwa(ead_post_d3, rw_d3)

    result_crr_d3 = CRRCRMResult(
        scenario_id="CRR-D3",
        scenario_group="CRR-D",
        description="Equity collateral (main index) - 15% haircut",
        exposure_reference="LOAN_CRM_D3",
        counterparty_reference="CORP_CRM_D3",
        approach="SA",
        exposure_class="CORPORATE",
        exposure_value=float(exposure_d3),
        risk_weight_pre_crm=float(rw_d3),
        rwa_pre_crm=float(rwa_pre_d3),
        crm_type="Equity (main index)",
        collateral_value=float(coll_value_d3),
        collateral_haircut=float(coll_haircut_d3),
        fx_haircut=float(fx_haircut_d3),
        maturity_adjustment=1.0,
        adjusted_collateral_value=float(coll_adjusted_d3),
        ead_post_crm=float(ead_post_d3),
        risk_weight_post_crm=float(rw_d3),
        rwa_post_crm=float(rwa_post_d3),
        rwa_reduction=float(rwa_pre_d3 - rwa_post_d3),
        calculation_details={
            "collateral_type": "Main index equity (FTSE 100)",
            "haircut": "15%",
            "other_equity_haircut": "25%",
            "calculation": f"C_adj = £{coll_value_d3:,.0f} × (1 - 15%) = £{coll_adjusted_d3:,.0f}",
        },
        regulatory_reference="CRR Art. 224",
    )

    print(f"CRR-D3: Equity=£{coll_value_d3:,.0f}, Haircut=15%")
    print(f"  Adjusted=£{coll_adjusted_d3:,.0f}, RWA=£{rwa_post_d3:,.0f}")
    return (result_crr_d3,)


@app.cell
def _(mo):
    """Scenario CRR-D4 Header."""
    mo.md("""
    ---
    ## Scenario CRR-D4: Guarantee Substitution

    **Input:** £1m corporate exposure (100% RW), £600k bank guarantee (30% RW)
    **Expected:** Split treatment - guaranteed portion at guarantor RW

    **CRR Treatment (Art. 213-217):**
    - Guaranteed portion: apply guarantor's risk weight
    - Non-guaranteed portion: apply borrower's risk weight
    - RWA = (£600k × 30%) + (£400k × 100%) = £580k

    **Reference:** CRR Art. 213-217
    """)
    return


@app.cell
def _(
    CRRCRMResult,
    Decimal,
    calculate_sa_rwa,
    get_corporate_rw,
    get_institution_rw,
):
    """Calculate Scenario CRR-D4: Guarantee Substitution."""
    # Exposure
    exposure_d4 = Decimal("1000000")
    rw_borrower_d4 = get_corporate_rw(None)  # 100% unrated

    # Guarantee from UK bank (CQS 2 = 30% RW UK deviation)
    guarantee_amount_d4 = Decimal("600000")
    rw_guarantor_d4 = get_institution_rw(cqs=2, country="GB", use_uk_deviation=True)  # 30%

    # Pre-CRM RWA
    rwa_pre_d4 = calculate_sa_rwa(exposure_d4, rw_borrower_d4)

    # Split treatment
    guaranteed_portion_d4 = guarantee_amount_d4
    non_guaranteed_d4 = exposure_d4 - guarantee_amount_d4

    # Post-CRM RWA
    rwa_guaranteed_d4 = calculate_sa_rwa(guaranteed_portion_d4, rw_guarantor_d4)
    rwa_non_guaranteed_d4 = calculate_sa_rwa(non_guaranteed_d4, rw_borrower_d4)
    rwa_post_d4 = rwa_guaranteed_d4 + rwa_non_guaranteed_d4

    result_crr_d4 = CRRCRMResult(
        scenario_id="CRR-D4",
        scenario_group="CRR-D",
        description="Bank guarantee - substitution approach",
        exposure_reference="LOAN_CRM_D4",
        counterparty_reference="CORP_CRM_D4",
        approach="SA",
        exposure_class="CORPORATE",
        exposure_value=float(exposure_d4),
        risk_weight_pre_crm=float(rw_borrower_d4),
        rwa_pre_crm=float(rwa_pre_d4),
        crm_type="Bank guarantee",
        collateral_value=float(guarantee_amount_d4),
        collateral_haircut=0.0,  # N/A for guarantees
        fx_haircut=0.0,
        maturity_adjustment=1.0,
        adjusted_collateral_value=float(guarantee_amount_d4),
        ead_post_crm=float(exposure_d4),  # Full EAD, split RW treatment
        risk_weight_post_crm=0.0,  # N/A - split treatment
        rwa_post_crm=float(rwa_post_d4),
        rwa_reduction=float(rwa_pre_d4 - rwa_post_d4),
        calculation_details={
            "guarantor_type": "UK Bank (CQS 2)",
            "guarantor_rw": float(rw_guarantor_d4),
            "borrower_rw": float(rw_borrower_d4),
            "guaranteed_portion": float(guaranteed_portion_d4),
            "non_guaranteed_portion": float(non_guaranteed_d4),
            "formula": "RWA = (Guaranteed × RW_guarantor) + (Non-guaranteed × RW_borrower)",
            "calculation": f"RWA = (£{guaranteed_portion_d4:,.0f} × 30%) + (£{non_guaranteed_d4:,.0f} × 100%) = £{rwa_post_d4:,.0f}",
        },
        regulatory_reference="CRR Art. 213-217",
    )

    print(f"CRR-D4: Exposure=£{exposure_d4:,.0f}, Guarantee=£{guarantee_amount_d4:,.0f}")
    print(f"  Borrower RW={rw_borrower_d4*100:.0f}%, Guarantor RW={rw_guarantor_d4*100:.0f}%")
    print(f"  RWA=£{rwa_post_d4:,.0f} (saving £{rwa_pre_d4 - rwa_post_d4:,.0f})")
    return (result_crr_d4,)


@app.cell
def _(mo):
    """Scenario CRR-D5 Header."""
    mo.md("""
    ---
    ## Scenario CRR-D5: Maturity Mismatch

    **Input:** £1m exposure (5y), £500k collateral (2y residual maturity)
    **Expected:** Collateral value reduced due to maturity mismatch

    **CRR Treatment (Art. 238):**
    - If collateral maturity < exposure maturity: apply adjustment
    - Adjustment = (t - 0.25) / (T - 0.25)
    - Where t = collateral maturity, T = exposure maturity (capped at 5y)
    - If t < 3 months: collateral not recognised

    **Reference:** CRR Art. 238
    """)
    return


@app.cell
def _(
    CRRCRMResult,
    Decimal,
    apply_maturity_mismatch,
    calculate_adjusted_collateral_value,
    calculate_sa_rwa,
    get_collateral_haircut,
    get_corporate_rw,
):
    """Calculate Scenario CRR-D5: Maturity Mismatch."""
    # Exposure
    exposure_d5 = Decimal("1000000")
    exposure_maturity_d5 = 5.0  # years
    rw_d5 = get_corporate_rw(None)  # 100%

    # Collateral - cash with shorter maturity
    coll_value_d5 = Decimal("500000")
    coll_maturity_d5 = 2.0  # years
    coll_haircut_d5 = get_collateral_haircut("cash")  # 0%

    # First apply collateral haircut
    coll_after_haircut_d5 = calculate_adjusted_collateral_value(
        coll_value_d5, coll_haircut_d5, Decimal("0.00")
    )

    # Then apply maturity mismatch
    coll_adjusted_d5, mm_desc_d5 = apply_maturity_mismatch(
        coll_after_haircut_d5,
        coll_maturity_d5,
        exposure_maturity_d5,
    )

    # Calculate maturity adjustment factor
    t = max(coll_maturity_d5, 0.25)
    T = min(max(exposure_maturity_d5, 0.25), 5.0)
    mat_adj_d5 = (t - 0.25) / (T - 0.25)

    # Pre-CRM
    rwa_pre_d5 = calculate_sa_rwa(exposure_d5, rw_d5)

    # Post-CRM
    ead_post_d5 = exposure_d5 - coll_adjusted_d5
    rwa_post_d5 = calculate_sa_rwa(ead_post_d5, rw_d5)

    result_crr_d5 = CRRCRMResult(
        scenario_id="CRR-D5",
        scenario_group="CRR-D",
        description="Maturity mismatch - 2y collateral, 5y exposure",
        exposure_reference="LOAN_CRM_D5",
        counterparty_reference="CORP_CRM_D5",
        approach="SA",
        exposure_class="CORPORATE",
        exposure_value=float(exposure_d5),
        risk_weight_pre_crm=float(rw_d5),
        rwa_pre_crm=float(rwa_pre_d5),
        crm_type="Cash + maturity mismatch",
        collateral_value=float(coll_value_d5),
        collateral_haircut=float(coll_haircut_d5),
        fx_haircut=0.0,
        maturity_adjustment=mat_adj_d5,
        adjusted_collateral_value=float(coll_adjusted_d5),
        ead_post_crm=float(ead_post_d5),
        risk_weight_post_crm=float(rw_d5),
        rwa_post_crm=float(rwa_post_d5),
        rwa_reduction=float(rwa_pre_d5 - rwa_post_d5),
        calculation_details={
            "exposure_maturity": exposure_maturity_d5,
            "collateral_maturity": coll_maturity_d5,
            "maturity_adjustment_formula": "(t - 0.25) / (T - 0.25)",
            "maturity_adjustment": f"({t} - 0.25) / ({T} - 0.25) = {mat_adj_d5:.4f}",
            "collateral_after_haircut": float(coll_after_haircut_d5),
            "collateral_after_mm": float(coll_adjusted_d5),
            "description": mm_desc_d5,
        },
        regulatory_reference="CRR Art. 238",
    )

    print(f"CRR-D5: Collateral=£{coll_value_d5:,.0f}, Maturity mismatch adj={mat_adj_d5:.4f}")
    print(f"  Adjusted collateral=£{coll_adjusted_d5:,.0f}, RWA=£{rwa_post_d5:,.0f}")
    return (result_crr_d5,)


@app.cell
def _(mo):
    """Scenario CRR-D6 Header."""
    mo.md("""
    ---
    ## Scenario CRR-D6: Currency Mismatch

    **Input:** £1m GBP exposure, €500k EUR collateral
    **Expected:** Additional 8% FX haircut applied

    **CRR Treatment (Art. 224):**
    - When collateral and exposure in different currencies
    - Additional 8% haircut for FX volatility risk

    **Reference:** CRR Art. 224
    """)
    return


@app.cell
def _(
    CRRCRMResult,
    Decimal,
    calculate_adjusted_collateral_value,
    calculate_sa_rwa,
    get_collateral_haircut,
    get_corporate_rw,
    get_fx_haircut,
):
    """Calculate Scenario CRR-D6: Currency Mismatch."""
    # Exposure in GBP
    exposure_d6 = Decimal("1000000")
    exposure_ccy_d6 = "GBP"
    rw_d6 = get_corporate_rw(None)  # 100%

    # Collateral in EUR - assume converted at spot
    coll_value_gbp_d6 = Decimal("500000")  # GBP equivalent
    coll_ccy_d6 = "EUR"
    coll_haircut_d6 = get_collateral_haircut("cash")  # 0% for cash
    fx_haircut_d6 = get_fx_haircut(exposure_ccy_d6, coll_ccy_d6)  # 8%

    # Calculate adjusted collateral (both haircuts)
    coll_adjusted_d6 = calculate_adjusted_collateral_value(
        coll_value_gbp_d6, coll_haircut_d6, fx_haircut_d6
    )

    # Pre-CRM
    rwa_pre_d6 = calculate_sa_rwa(exposure_d6, rw_d6)

    # Post-CRM
    ead_post_d6 = exposure_d6 - coll_adjusted_d6
    rwa_post_d6 = calculate_sa_rwa(ead_post_d6, rw_d6)

    result_crr_d6 = CRRCRMResult(
        scenario_id="CRR-D6",
        scenario_group="CRR-D",
        description="Currency mismatch - GBP exposure, EUR collateral",
        exposure_reference="LOAN_CRM_D6",
        counterparty_reference="CORP_CRM_D6",
        approach="SA",
        exposure_class="CORPORATE",
        exposure_value=float(exposure_d6),
        risk_weight_pre_crm=float(rw_d6),
        rwa_pre_crm=float(rwa_pre_d6),
        crm_type="Cash (FX mismatch)",
        collateral_value=float(coll_value_gbp_d6),
        collateral_haircut=float(coll_haircut_d6),
        fx_haircut=float(fx_haircut_d6),
        maturity_adjustment=1.0,
        adjusted_collateral_value=float(coll_adjusted_d6),
        ead_post_crm=float(ead_post_d6),
        risk_weight_post_crm=float(rw_d6),
        rwa_post_crm=float(rwa_post_d6),
        rwa_reduction=float(rwa_pre_d6 - rwa_post_d6),
        calculation_details={
            "exposure_currency": exposure_ccy_d6,
            "collateral_currency": coll_ccy_d6,
            "collateral_haircut": f"{coll_haircut_d6*100:.0f}%",
            "fx_haircut": f"{fx_haircut_d6*100:.0f}%",
            "total_haircut": f"{(coll_haircut_d6 + fx_haircut_d6)*100:.0f}%",
            "formula": "C_adj = C × (1 - Hc - Hfx)",
            "calculation": f"C_adj = £{coll_value_gbp_d6:,.0f} × (1 - 0% - 8%) = £{coll_adjusted_d6:,.0f}",
        },
        regulatory_reference="CRR Art. 224",
    )

    print(f"CRR-D6: Collateral=£{coll_value_gbp_d6:,.0f} (EUR), FX haircut={fx_haircut_d6*100:.0f}%")
    print(f"  Adjusted=£{coll_adjusted_d6:,.0f}, RWA=£{rwa_post_d6:,.0f}")
    return (result_crr_d6,)


@app.cell
def _(mo):
    """Summary Section."""
    mo.md("""
    ---
    ## Summary: Group CRR-D CRM Results

    Key CRR CRM observations:
    1. **Cash** - 0% haircut, most effective collateral
    2. **Government bonds** - Haircuts vary by CQS and maturity (0.5% to 6%)
    3. **Equity** - 15% main index, 25% other listed
    4. **Guarantees** - Substitution approach, use guarantor's RW
    5. **Maturity mismatch** - Reduces collateral value proportionally
    6. **Currency mismatch** - Additional 8% haircut
    """)
    return


@app.cell
def _(
    mo,
    pl,
    result_crr_d1,
    result_crr_d2,
    result_crr_d3,
    result_crr_d4,
    result_crr_d5,
    result_crr_d6,
):
    """Compile all Group CRR-D results."""
    group_crr_d_results = [
        result_crr_d1, result_crr_d2, result_crr_d3,
        result_crr_d4, result_crr_d5, result_crr_d6,
    ]

    # Create summary DataFrame
    summary_data_d = []
    for r in group_crr_d_results:
        summary_data_d.append({
            "Scenario": r.scenario_id,
            "CRM Type": r.crm_type,
            "Exposure (£)": f"{r.exposure_value:,.0f}",
            "Collateral (£)": f"{r.collateral_value:,.0f}",
            "Haircut": f"{(r.collateral_haircut + r.fx_haircut)*100:.0f}%",
            "Mat Adj": f"{r.maturity_adjustment:.2f}" if r.maturity_adjustment < 1.0 else "-",
            "RWA Pre (£)": f"{r.rwa_pre_crm:,.0f}",
            "RWA Post (£)": f"{r.rwa_post_crm:,.0f}",
            "Reduction (£)": f"{r.rwa_reduction:,.0f}",
        })

    summary_df_d = pl.DataFrame(summary_data_d)
    mo.ui.table(summary_df_d)
    return (group_crr_d_results,)


@app.cell
def _(group_crr_d_results):
    """Export function for use by main workbook."""
    def get_group_crr_d_results():
        """Return all Group CRR-D scenario results."""
        return group_crr_d_results
    return (get_group_crr_d_results,)


if __name__ == "__main__":
    app.run()
