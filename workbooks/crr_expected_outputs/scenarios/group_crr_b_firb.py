"""
Group CRR-B: CRR Foundation IRB (F-IRB) Scenarios

Scenarios CRR-B1 to CRR-B7 covering F-IRB calculations using supervisory LGD.
Note: F-IRB only applies to wholesale exposures (corporate, institution, sovereign).
Retail exposures require A-IRB (internal LGD) or must use Standardised Approach.

Usage:
    uv run marimo edit workbooks/crr_expected_outputs/scenarios/group_crr_b_firb.py

Key CRR References:
    - Art. 153: IRB risk weight formula
    - Art. 154: Defaulted exposures
    - Art. 161: Supervisory LGD values for F-IRB
    - Art. 162: Maturity
    - Art. 163: PD floor (0.03% - single floor for all classes)
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
    from workbooks.shared.correlation import calculate_correlation
    from workbooks.crr_expected_outputs.calculations.crr_irb import (
        apply_pd_floor,
        get_firb_lgd,
        calculate_irb_rwa,
        calculate_irb_rwa_with_turnover,
        calculate_maturity_adjustment,
        calculate_expected_loss,
    )
    from workbooks.crr_expected_outputs.calculations.crr_supporting_factors import (
        apply_sme_supporting_factor,
        is_sme_eligible,
    )
    from workbooks.crr_expected_outputs.data.crr_params import (
        CRR_PD_FLOOR,
        CRR_FIRB_LGD,
    )
    return (
        CRR_PD_FLOOR,
        Decimal,
        apply_pd_floor,
        apply_sme_supporting_factor,
        calculate_correlation,
        calculate_expected_loss,
        calculate_irb_rwa,
        calculate_irb_rwa_with_turnover,
        get_firb_lgd,
        load_fixtures,
        mo,
        pl,
    )


@app.cell
def _(mo):
    """Header."""
    mo.md("""
    # Group CRR-B: CRR Foundation IRB (F-IRB) Scenarios

    This workbook calculates expected RWA values for CRR F-IRB scenarios CRR-B1 to CRR-B7.

    **Regulatory Framework:** CRR (Capital Requirements Regulation)
    **Effective:** Until 31 December 2026

    **Key CRR F-IRB Features:**
    - Bank provides own PD estimates
    - Supervisory LGD values (Art. 161):
      - 45% unsecured senior
      - 75% subordinated
      - Reduced LGD for collateralised exposures
    - Single PD floor: 0.03% for all exposure classes
    - Maturity adjustment: 1-5 year floor/cap
    - SME supporting factor (0.7619) available
    - **F-IRB only applies to wholesale exposures** (corporate, institution, sovereign)
      - Retail exposures must use A-IRB (with internal LGD) or Standardised Approach

    **Key differences from Basel 3.1:**
    - CRR has single 0.03% PD floor (Basel 3.1 has differentiated floors)
    - CRR SME factor available (not in Basel 3.1)
    - No output floor under CRR
    """)
    return


@app.cell
def _(load_fixtures):
    """Load test fixtures."""
    fixtures = load_fixtures()
    return (fixtures,)


@app.cell
def _():
    """Scenario result dataclass for F-IRB."""
    from dataclasses import dataclass, asdict
    from typing import Any

    @dataclass
    class CRRFIRBResult:
        """Container for a single CRR F-IRB scenario calculation result."""
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
        lgd: float
        correlation: float
        maturity: float
        maturity_adjustment: float
        k: float
        rwa_before_sf: float
        supporting_factor: float
        rwa_after_sf: float
        expected_loss: float
        calculation_details: dict
        regulatory_reference: str

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)
    return (CRRFIRBResult,)


@app.cell
def _(mo):
    """Scenario CRR-B1 Header."""
    mo.md("""
    ---
    ## Scenario CRR-B1: Corporate F-IRB - Low PD

    **Input:** £10m corporate loan, PD 0.10%, 2.5 year maturity
    **Expected:** F-IRB calculation with supervisory LGD 45%

    **CRR Treatment:**
    - PD floor: 0.03% (CRR Art. 163)
    - LGD: 45% supervisory (CRR Art. 161)
    - Maturity adjustment applied (CRR Art. 162)

    **Reference:** CRR Art. 153, 161, 162, 163
    """)
    return


@app.cell
def _(
    CRRFIRBResult,
    CRR_PD_FLOOR,
    apply_pd_floor,
    calculate_correlation,
    calculate_expected_loss,
    calculate_irb_rwa,
    fixtures,
    get_firb_lgd,
):
    """Calculate Scenario CRR-B1: Corporate F-IRB - Low PD."""
    loan_b1 = fixtures.get_loan("LOAN_CORP_UK_001")
    cpty_b1 = fixtures.get_counterparty("CORP_UK_001")
    internal_rating_b1 = fixtures.get_internal_rating("CORP_UK_001")

    # Validate internal rating exists for F-IRB calculation
    if internal_rating_b1 is None:
        raise ValueError("No internal rating found for CORP_UK_001 - required for F-IRB")

    # Input parameters - PD from internal rating fixture
    ead_b1 = float(loan_b1["drawn_amount"])
    pd_raw_b1 = float(internal_rating_b1["pd"])  # From fixture: 0.0010 (0.10%)
    pd_floored_b1 = apply_pd_floor(pd_raw_b1)
    lgd_b1 = float(get_firb_lgd("unsecured"))
    maturity_b1 = 2.5

    # Calculate correlation
    correlation_b1 = calculate_correlation(pd_floored_b1, "CORPORATE")

    # Calculate RWA
    result_dict_b1 = calculate_irb_rwa(
        ead=ead_b1,
        pd=pd_raw_b1,
        lgd=lgd_b1,
        correlation=correlation_b1,
        maturity=maturity_b1,
        exposure_class="CORPORATE",
        apply_maturity_adjustment=True,
        apply_pd_floor_flag=True,
    )

    # Expected loss
    el_b1 = calculate_expected_loss(ead_b1, pd_floored_b1, lgd_b1)

    result_crr_b1 = CRRFIRBResult(
        scenario_id="CRR-B1",
        scenario_group="CRR-B",
        description="Corporate F-IRB - low PD",
        exposure_reference="LOAN_CORP_UK_001",
        counterparty_reference="CORP_UK_001",
        approach="F-IRB",
        exposure_class="CORPORATE",
        ead=ead_b1,
        pd_raw=pd_raw_b1,
        pd_floored=pd_floored_b1,
        lgd=lgd_b1,
        correlation=correlation_b1,
        maturity=maturity_b1,
        maturity_adjustment=result_dict_b1["maturity_adjustment"],
        k=result_dict_b1["k"],
        rwa_before_sf=result_dict_b1["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_dict_b1["rwa"],
        expected_loss=el_b1,
        calculation_details={
            "counterparty_name": cpty_b1["counterparty_name"],
            "internal_rating_ref": internal_rating_b1["rating_reference"],
            "pd_floor": float(CRR_PD_FLOOR),
            "lgd_source": "supervisory",
            "formula": "K = LGD × [N(G(PD)) - PD × LGD] × MA",
            "rw_formula": "RW = K × 12.5 × 1.06",
        },
        regulatory_reference="CRR Art. 153, 161, 162, 163",
    )

    print(f"CRR-B1: EAD=£{ead_b1:,.0f}, PD={pd_floored_b1*100:.2f}%, LGD={lgd_b1*100:.0f}%, MATURITY={maturity_b1}, MAT ADJ={result_dict_b1["maturity_adjustment"]:,.4f}, CORRELATION={correlation_b1:,.4f}, K={result_dict_b1["k"]:,.4f} RWA=£{result_dict_b1['rwa']:,.0f}")
    return (result_crr_b1,)


@app.cell
def _(mo):
    """Scenario CRR-B2 Header."""
    mo.md("""
    ---
    ## Scenario CRR-B2: Corporate F-IRB - High PD

    **Input:** £5m corporate loan, PD 5.00%, 3 year maturity
    **Expected:** Higher RWA due to increased PD

    **Reference:** CRR Art. 153, 161, 162
    """)
    return


@app.cell
def _(
    CRRFIRBResult,
    CRR_PD_FLOOR,
    apply_pd_floor,
    calculate_correlation,
    calculate_expected_loss,
    calculate_irb_rwa,
    fixtures,
    get_firb_lgd,
):
    """Calculate Scenario CRR-B2: Corporate F-IRB - High PD."""
    loan_b2 = fixtures.get_loan("LOAN_CORP_UK_005")
    cpty_b2 = fixtures.get_counterparty("CORP_UK_005")
    internal_rating_b2 = fixtures.get_internal_rating("CORP_UK_005")

    # Validate internal rating exists for F-IRB calculation
    if internal_rating_b2 is None:
        raise ValueError("No internal rating found for CORP_UK_005 - required for F-IRB")

    # Input parameters - PD from internal rating fixture
    ead_b2 = float(loan_b2["drawn_amount"])
    pd_raw_b2 = float(internal_rating_b2["pd"])  # From fixture: 0.0500 (5.00%)
    pd_floored_b2 = apply_pd_floor(pd_raw_b2)  # No effect as 5% > 0.03%
    lgd_b2 = float(get_firb_lgd("unsecured"))
    maturity_b2 = 3.0

    # Calculate correlation (decreases with higher PD)
    correlation_b2 = calculate_correlation(pd_floored_b2, "CORPORATE")

    # Calculate RWA
    result_dict_b2 = calculate_irb_rwa(
        ead=ead_b2,
        pd=pd_raw_b2,
        lgd=lgd_b2,
        correlation=correlation_b2,
        maturity=maturity_b2,
        exposure_class="CORPORATE",
        apply_maturity_adjustment=True,
        apply_pd_floor_flag=True,
    )

    el_b2 = calculate_expected_loss(ead_b2, pd_floored_b2, lgd_b2)

    result_crr_b2 = CRRFIRBResult(
        scenario_id="CRR-B2",
        scenario_group="CRR-B",
        description="Corporate F-IRB - high PD",
        exposure_reference="LOAN_CORP_UK_005",
        counterparty_reference="CORP_UK_005",
        approach="F-IRB",
        exposure_class="CORPORATE",
        ead=ead_b2,
        pd_raw=pd_raw_b2,
        pd_floored=pd_floored_b2,
        lgd=lgd_b2,
        correlation=correlation_b2,
        maturity=maturity_b2,
        maturity_adjustment=result_dict_b2["maturity_adjustment"],
        k=result_dict_b2["k"],
        rwa_before_sf=result_dict_b2["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_dict_b2["rwa"],
        expected_loss=el_b2,
        calculation_details={
            "counterparty_name": cpty_b2["counterparty_name"],
            "internal_rating_ref": internal_rating_b2["rating_reference"],
            "pd_floor": float(CRR_PD_FLOOR),
            "pd_floor_binding": pd_raw_b2 < float(CRR_PD_FLOOR),
            "lgd_source": "supervisory",
        },
        regulatory_reference="CRR Art. 153, 161, 162",
    )

    print(f"CRR-B2: EAD=£{ead_b2:,.0f}, PD={pd_floored_b2*100:.2f}%, LGD={lgd_b2*100:.0f}%, RWA=£{result_dict_b2['rwa']:,.0f}")
    return (result_crr_b2,)


@app.cell
def _(mo):
    """Scenario CRR-B3 Header."""
    mo.md("""
    ---
    ## Scenario CRR-B3: Subordinated Exposure - 75% LGD

    **Input:** £2m subordinated loan, PD 1.00%
    **Expected:** Higher LGD (75%) for subordinated claims

    **CRR Treatment (Art. 161):**
    - Subordinated claims: 75% LGD
    - Senior unsecured: 45% LGD

    **Reference:** CRR Art. 153, 161
    """)
    return


@app.cell
def _(
    CRRFIRBResult,
    CRR_PD_FLOOR,
    apply_pd_floor,
    calculate_correlation,
    calculate_expected_loss,
    calculate_irb_rwa,
    fixtures,
    get_firb_lgd,
):
    """Calculate Scenario CRR-B3: Subordinated Exposure."""
    loan_b3 = fixtures.get_loan("LOAN_SUB_001")
    cpty_b3 = fixtures.get_counterparty("CORP_UK_004")
    internal_rating_b3 = fixtures.get_internal_rating("CORP_UK_004")

    # Validate internal rating exists for F-IRB calculation
    if internal_rating_b3 is None:
        raise ValueError("No internal rating found for CORP_UK_004 - required for F-IRB")

    # Input parameters - PD from internal rating fixture
    ead_b3 = float(loan_b3["drawn_amount"])
    pd_raw_b3 = float(internal_rating_b3["pd"])  # From fixture: 0.0100 (1.00%)
    pd_floored_b3 = apply_pd_floor(pd_raw_b3)
    lgd_b3 = float(get_firb_lgd("unsecured", is_subordinated=True))  # 75%
    maturity_b3 = 4.0

    correlation_b3 = calculate_correlation(pd_floored_b3, "CORPORATE")

    result_dict_b3 = calculate_irb_rwa(
        ead=ead_b3,
        pd=pd_raw_b3,
        lgd=lgd_b3,
        correlation=correlation_b3,
        maturity=maturity_b3,
        exposure_class="CORPORATE",
        apply_maturity_adjustment=True,
        apply_pd_floor_flag=True,
    )

    el_b3 = calculate_expected_loss(ead_b3, pd_floored_b3, lgd_b3)

    result_crr_b3 = CRRFIRBResult(
        scenario_id="CRR-B3",
        scenario_group="CRR-B",
        description="Subordinated exposure - 75% LGD",
        exposure_reference="LOAN_SUB_001",
        counterparty_reference="CORP_UK_004",
        approach="F-IRB",
        exposure_class="CORPORATE_SUBORDINATED",
        ead=ead_b3,
        pd_raw=pd_raw_b3,
        pd_floored=pd_floored_b3,
        lgd=lgd_b3,
        correlation=correlation_b3,
        maturity=maturity_b3,
        maturity_adjustment=result_dict_b3["maturity_adjustment"],
        k=result_dict_b3["k"],
        rwa_before_sf=result_dict_b3["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_dict_b3["rwa"],
        expected_loss=el_b3,
        calculation_details={
            "counterparty_name": cpty_b3["counterparty_name"],
            "internal_rating_ref": internal_rating_b3["rating_reference"],
            "pd_floor": float(CRR_PD_FLOOR),
            "lgd_source": "supervisory_subordinated",
            "lgd_senior": 0.45,
            "lgd_subordinated": 0.75,
        },
        regulatory_reference="CRR Art. 153, 161",
    )

    print(f"CRR-B3: EAD=£{ead_b3:,.0f}, PD={pd_floored_b3*100:.2f}%, LGD={lgd_b3*100:.0f}%, RWA=£{result_dict_b3['rwa']:,.0f}")
    return (result_crr_b3,)


@app.cell
def _(mo):
    """Scenario CRR-B4 Header."""
    mo.md("""
    ---
    ## Scenario CRR-B4: Financial Collateral - Reduced LGD

    **Input:** £5m loan with cash collateral covering 50%
    **Expected:** Reduced effective LGD for collateralised portion

    **CRR Treatment (Art. 161):**
    - Financial collateral (cash): 0% LGD on collateralised portion
    - Blended LGD for partially collateralised exposures

    **Reference:** CRR Art. 153, 161, 228
    """)
    return


@app.cell
def _(
    CRRFIRBResult,
    CRR_PD_FLOOR,
    apply_pd_floor,
    calculate_correlation,
    calculate_expected_loss,
    calculate_irb_rwa,
    fixtures,
    get_firb_lgd,
):
    """Calculate Scenario CRR-B4: Financial Collateral."""
    loan_b4 = fixtures.get_loan("LOAN_COLL_001")
    cpty_b4 = fixtures.get_counterparty("CORP_SME_002")
    internal_rating_b4 = fixtures.get_internal_rating("CORP_SME_002")

    # Validate internal rating exists for F-IRB calculation
    if internal_rating_b4 is None:
        raise ValueError("No internal rating found for CORP_SME_002 - required for F-IRB")

    # Input parameters - PD from internal rating fixture
    ead_b4 = float(loan_b4["drawn_amount"])
    pd_raw_b4 = float(internal_rating_b4["pd"])  # From fixture: 0.0050 (0.50%)
    pd_floored_b4 = apply_pd_floor(pd_raw_b4)
    maturity_b4 = 2.5

    # 50% cash collateral -> blended LGD
    collateral_coverage_b4 = 0.50
    lgd_unsecured_b4 = float(get_firb_lgd("unsecured"))  # 45%
    lgd_secured_b4 = float(get_firb_lgd("financial_collateral"))  # 0%
    lgd_b4 = (collateral_coverage_b4 * lgd_secured_b4) + ((1 - collateral_coverage_b4) * lgd_unsecured_b4)

    correlation_b4 = calculate_correlation(pd_floored_b4, "CORPORATE")

    result_dict_b4 = calculate_irb_rwa(
        ead=ead_b4,
        pd=pd_raw_b4,
        lgd=lgd_b4,
        correlation=correlation_b4,
        maturity=maturity_b4,
        exposure_class="CORPORATE",
        apply_maturity_adjustment=True,
        apply_pd_floor_flag=True,
    )

    el_b4 = calculate_expected_loss(ead_b4, pd_floored_b4, lgd_b4)

    result_crr_b4 = CRRFIRBResult(
        scenario_id="CRR-B4",
        scenario_group="CRR-B",
        description="Financial collateral - reduced LGD",
        exposure_reference="LOAN_COLL_001",
        counterparty_reference="CORP_SME_002",
        approach="F-IRB",
        exposure_class="CORPORATE_SECURED",
        ead=ead_b4,
        pd_raw=pd_raw_b4,
        pd_floored=pd_floored_b4,
        lgd=lgd_b4,
        correlation=correlation_b4,
        maturity=maturity_b4,
        maturity_adjustment=result_dict_b4["maturity_adjustment"],
        k=result_dict_b4["k"],
        rwa_before_sf=result_dict_b4["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_dict_b4["rwa"],
        expected_loss=el_b4,
        calculation_details={
            "counterparty_name": cpty_b4["counterparty_name"],
            "internal_rating_ref": internal_rating_b4["rating_reference"],
            "pd_floor": float(CRR_PD_FLOOR),
            "collateral_type": "cash",
            "collateral_coverage": collateral_coverage_b4,
            "lgd_unsecured": lgd_unsecured_b4,
            "lgd_secured": lgd_secured_b4,
            "blended_lgd": lgd_b4,
        },
        regulatory_reference="CRR Art. 153, 161, 228",
    )

    print(f"CRR-B4: EAD=£{ead_b4:,.0f}, PD={pd_floored_b4*100:.2f}%, LGD={lgd_b4*100:.1f}%, RWA=£{result_dict_b4['rwa']:,.0f}")
    return (result_crr_b4,)


@app.cell
def _(mo):
    """Scenario CRR-B5 Header."""
    mo.md("""
    ---
    ## Scenario CRR-B5: SME Corporate F-IRB with Supporting Factor

    **Input:** £3m SME loan, PD 2.00%, turnover £25m
    **Expected:** F-IRB RWA × 0.7619 SME factor

    **CRR Treatment:**
    - SME firm size adjustment in correlation
    - SME supporting factor (0.7619) on top
    - Combined effect: significant RWA reduction

    **Reference:** CRR Art. 153, 501
    """)
    return


@app.cell
def _(
    CRRFIRBResult,
    CRR_PD_FLOOR,
    Decimal,
    apply_sme_supporting_factor,
    calculate_expected_loss,
    calculate_irb_rwa_with_turnover,
    fixtures,
    get_firb_lgd,
):
    """Calculate Scenario CRR-B5: SME Corporate F-IRB with Supporting Factor.

    Demonstrates both SME adjustments under CRR:
    1. SME firm size adjustment - reduces asset correlation (CRR Art. 153(4))
       Formula: R_adjusted = R - 0.04 × (1 - (max(S, 5) - 5) / 45)
       where S = turnover in millions EUR

    2. SME supporting factor - reduces RWA by 23.81% (CRR Art. 501)
       Factor: 0.7619
    """
    loan_b5 = fixtures.get_loan("LOAN_CORP_SME_001")
    cpty_b5 = fixtures.get_counterparty("CORP_SME_001")
    internal_rating_b5 = fixtures.get_internal_rating("CORP_SME_001")

    # Validate internal rating exists for F-IRB calculation
    if internal_rating_b5 is None:
        raise ValueError("No internal rating found for CORP_SME_001 - required for F-IRB")

    # Input parameters - PD from internal rating fixture
    ead_b5 = float(loan_b5["drawn_amount"])
    pd_raw_b5 = float(internal_rating_b5["pd"])  # From fixture: 0.0200 (2.00%)
    lgd_b5 = float(get_firb_lgd("unsecured"))
    maturity_b5 = 2.5
    turnover_m_b5 = 25.0  # EUR 25m (or ~£22m) - qualifies for firm size adjustment

    # Use calculate_irb_rwa_with_turnover which handles SME firm size adjustment
    # automatically by calculating correlation with turnover internally
    result_dict_b5 = calculate_irb_rwa_with_turnover(
        ead=ead_b5,
        pd=pd_raw_b5,
        lgd=lgd_b5,
        maturity=maturity_b5,
        exposure_class="CORPORATE",
        turnover_m=turnover_m_b5,  # Turnover in millions EUR for SME adjustment
    )

    # Apply SME supporting factor on top of the firm-size-adjusted RWA
    rwa_before_sf_b5 = Decimal(str(result_dict_b5["rwa"]))
    rwa_after_sf_b5, sf_applied_b5, sf_desc_b5 = apply_sme_supporting_factor(
        rwa=rwa_before_sf_b5,
        is_sme=True,
        turnover=Decimal(str(turnover_m_b5 * 1_000_000)),  # Convert to actual value
        currency="EUR",
    )

    sf_b5 = 0.7619 if sf_applied_b5 else 1.0

    el_b5 = calculate_expected_loss(ead_b5, result_dict_b5["pd_floored"], lgd_b5)

    result_crr_b5 = CRRFIRBResult(
        scenario_id="CRR-B5",
        scenario_group="CRR-B",
        description="SME corporate F-IRB with supporting factor",
        exposure_reference="LOAN_CORP_SME_001",
        counterparty_reference="CORP_SME_001",
        approach="F-IRB",
        exposure_class="CORPORATE_SME",
        ead=ead_b5,
        pd_raw=pd_raw_b5,
        pd_floored=result_dict_b5["pd_floored"],
        lgd=lgd_b5,
        correlation=result_dict_b5["correlation"],
        maturity=maturity_b5,
        maturity_adjustment=result_dict_b5["maturity_adjustment"],
        k=result_dict_b5["k"],
        rwa_before_sf=float(rwa_before_sf_b5),
        supporting_factor=sf_b5,
        rwa_after_sf=float(rwa_after_sf_b5),
        expected_loss=el_b5,
        calculation_details={
            "counterparty_name": cpty_b5["counterparty_name"],
            "internal_rating_ref": internal_rating_b5["rating_reference"],
            "pd_floor": float(CRR_PD_FLOOR),
            "turnover_m": turnover_m_b5,
            "sme_firm_size_adjustment_applied": result_dict_b5["sme_adjustment_applied"],
            "correlation_with_sme_adj": result_dict_b5["correlation"],
            "sme_supporting_factor": sf_b5,
            "sme_factor_description": sf_desc_b5,
            "crr_vs_basel31": "Both SME adjustments NOT available under Basel 3.1",
        },
        regulatory_reference="CRR Art. 153(4), 501",
    )

    print(f"CRR-B5: EAD=£{ead_b5:,.0f}, PD={result_dict_b5['pd_floored']*100:.2f}%")
    print(f"  Correlation (with SME firm size adj): {result_dict_b5['correlation']:.4f}")
    print(f"  SME adjustment applied: {result_dict_b5['sme_adjustment_applied']}")
    print(f"  RWA before SF: £{rwa_before_sf_b5:,.0f}")
    print(f"  Supporting factor: {sf_b5}")
    print(f"  RWA after SF: £{rwa_after_sf_b5:,.0f}")
    return (result_crr_b5,)


@app.cell
def _(mo):
    """Scenario CRR-B6 Header."""
    mo.md("""
    ---
    ## Scenario CRR-B6: PD Floor Binding

    **Input:** £5m loan with very low internal PD estimate (0.01%)
    **Expected:** PD floored to 0.03%

    **CRR Treatment (Art. 163):**
    - Single PD floor: 0.03% for all non-defaulted exposures
    - Unlike Basel 3.1 which has differentiated floors

    **Reference:** CRR Art. 153, 163
    """)
    return


@app.cell
def _(
    CRRFIRBResult,
    CRR_PD_FLOOR,
    apply_pd_floor,
    calculate_correlation,
    calculate_expected_loss,
    calculate_irb_rwa,
    fixtures,
    get_firb_lgd,
):
    """Calculate Scenario CRR-B6: PD Floor Binding."""
    loan_b6 = fixtures.get_loan("LOAN_CORP_UK_002")
    cpty_b6 = fixtures.get_counterparty("CORP_UK_002")
    internal_rating_b6 = fixtures.get_internal_rating("CORP_UK_002")

    # Validate internal rating exists for F-IRB calculation
    if internal_rating_b6 is None:
        raise ValueError("No internal rating found for CORP_UK_002 - required for F-IRB")

    # Input parameters - PD from internal rating fixture
    ead_b6 = float(loan_b6["drawn_amount"])
    pd_raw_b6 = float(internal_rating_b6["pd"])  # From fixture: 0.0001 (0.01%) - very low, will be floored
    pd_floored_b6 = apply_pd_floor(pd_raw_b6)  # Will become 0.03%
    lgd_b6 = float(get_firb_lgd("unsecured"))
    maturity_b6 = 2.0

    # PD floor should be binding
    assert pd_floored_b6 > pd_raw_b6, "PD floor should be binding"

    correlation_b6 = calculate_correlation(pd_floored_b6, "CORPORATE")

    result_dict_b6 = calculate_irb_rwa(
        ead=ead_b6,
        pd=pd_raw_b6,
        lgd=lgd_b6,
        correlation=correlation_b6,
        maturity=maturity_b6,
        exposure_class="CORPORATE",
        apply_maturity_adjustment=True,
        apply_pd_floor_flag=True,
    )

    el_b6 = calculate_expected_loss(ead_b6, pd_floored_b6, lgd_b6)

    result_crr_b6 = CRRFIRBResult(
        scenario_id="CRR-B6",
        scenario_group="CRR-B",
        description="PD floor binding (0.01% -> 0.03%)",
        exposure_reference="LOAN_CORP_UK_002",
        counterparty_reference="CORP_UK_002",
        approach="F-IRB",
        exposure_class="CORPORATE",
        ead=ead_b6,
        pd_raw=pd_raw_b6,
        pd_floored=pd_floored_b6,
        lgd=lgd_b6,
        correlation=correlation_b6,
        maturity=maturity_b6,
        maturity_adjustment=result_dict_b6["maturity_adjustment"],
        k=result_dict_b6["k"],
        rwa_before_sf=result_dict_b6["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_dict_b6["rwa"],
        expected_loss=el_b6,
        calculation_details={
            "counterparty_name": cpty_b6["counterparty_name"],
            "internal_rating_ref": internal_rating_b6["rating_reference"],
            "pd_raw": pd_raw_b6,
            "pd_floor": float(CRR_PD_FLOOR),
            "pd_floored": pd_floored_b6,
            "floor_binding": True,
            "floor_impact": pd_floored_b6 - pd_raw_b6,
            "crr_vs_basel31": "CRR single 0.03% floor vs Basel 3.1 differentiated floors",
        },
        regulatory_reference="CRR Art. 153, 163",
    )

    print(f"CRR-B6: EAD=£{ead_b6:,.0f}, PD={pd_raw_b6*100:.2f}% -> {pd_floored_b6*100:.2f}%, RWA=£{result_dict_b6['rwa']:,.0f}")
    return (result_crr_b6,)


@app.cell
def _(mo):
    """Scenario CRR-B7 Header."""
    mo.md("""
    ---
    ## Scenario CRR-B7: Long Maturity Exposure (5Y Cap)

    **Input:** £8m loan with 7 year maturity (capped at 5)
    **Expected:** Maturity capped at 5 years

    **CRR Treatment (Art. 162):**
    - Maturity floor: 1 year
    - Maturity cap: 5 years

    **Reference:** CRR Art. 153, 162
    """)
    return


@app.cell
def _(
    CRRFIRBResult,
    CRR_PD_FLOOR,
    apply_pd_floor,
    calculate_correlation,
    calculate_expected_loss,
    calculate_irb_rwa,
    fixtures,
    get_firb_lgd,
):
    """Calculate Scenario CRR-B7: Long Maturity (Capped)."""
    loan_b7 = fixtures.get_loan("LOAN_LONG_MAT_001")
    cpty_b7 = fixtures.get_counterparty("CORP_LRG_001")
    internal_rating_b7 = fixtures.get_internal_rating("CORP_LRG_001")

    # Validate internal rating exists for F-IRB calculation
    if internal_rating_b7 is None:
        raise ValueError("No internal rating found for CORP_LRG_001 - required for F-IRB")

    # Input parameters - PD from internal rating fixture
    ead_b7 = float(loan_b7["drawn_amount"])
    pd_raw_b7 = float(internal_rating_b7["pd"])  # From fixture: 0.0080 (0.80%)
    pd_floored_b7 = apply_pd_floor(pd_raw_b7)
    lgd_b7 = float(get_firb_lgd("unsecured"))
    maturity_raw_b7 = 7.0  # Will be capped to 5.0
    maturity_b7 = min(maturity_raw_b7, 5.0)

    correlation_b7 = calculate_correlation(pd_floored_b7, "CORPORATE")

    result_dict_b7 = calculate_irb_rwa(
        ead=ead_b7,
        pd=pd_raw_b7,
        lgd=lgd_b7,
        correlation=correlation_b7,
        maturity=maturity_raw_b7,  # Pass raw, function caps it
        exposure_class="CORPORATE",
        apply_maturity_adjustment=True,
        apply_pd_floor_flag=True,
    )

    el_b7 = calculate_expected_loss(ead_b7, pd_floored_b7, lgd_b7)

    result_crr_b7 = CRRFIRBResult(
        scenario_id="CRR-B7",
        scenario_group="CRR-B",
        description="Long maturity exposure (7Y -> 5Y cap)",
        exposure_reference="LOAN_LONG_MAT_001",
        counterparty_reference="CORP_LRG_001",
        approach="F-IRB",
        exposure_class="CORPORATE",
        ead=ead_b7,
        pd_raw=pd_raw_b7,
        pd_floored=pd_floored_b7,
        lgd=lgd_b7,
        correlation=correlation_b7,
        maturity=maturity_b7,
        maturity_adjustment=result_dict_b7["maturity_adjustment"],
        k=result_dict_b7["k"],
        rwa_before_sf=result_dict_b7["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_dict_b7["rwa"],
        expected_loss=el_b7,
        calculation_details={
            "counterparty_name": cpty_b7["counterparty_name"],
            "internal_rating_ref": internal_rating_b7["rating_reference"],
            "pd_floor": float(CRR_PD_FLOOR),
            "maturity_raw": maturity_raw_b7,
            "maturity_capped": maturity_b7,
            "maturity_cap": 5.0,
            "maturity_floor": 1.0,
        },
        regulatory_reference="CRR Art. 153, 162",
    )

    print(f"CRR-B7: EAD=£{ead_b7:,.0f}, Maturity={maturity_raw_b7}y -> {maturity_b7}y, RWA=£{result_dict_b7['rwa']:,.0f}")
    return (result_crr_b7,)


@app.cell
def _(mo):
    """Summary Section."""
    mo.md("""
    ---
    ## Summary: Group CRR-B F-IRB Results

    Key CRR F-IRB observations:
    1. Single PD floor (0.03%) for all exposure classes
    2. Supervisory LGD: 45% senior, 75% subordinated
    3. SME supporting factor (0.7619) available
    4. Maturity capped at 5 years, floored at 1 year
    5. F-IRB only applies to wholesale exposures (corporate, institution, sovereign)
       - Retail must use A-IRB (internal LGD) or Standardised Approach
    """)
    return


@app.cell
def _(
    mo,
    pl,
    result_crr_b1,
    result_crr_b2,
    result_crr_b3,
    result_crr_b4,
    result_crr_b5,
    result_crr_b6,
    result_crr_b7,
):
    """Compile all Group CRR-B results."""
    group_crr_b_results = [
        result_crr_b1, result_crr_b2, result_crr_b3, result_crr_b4,
        result_crr_b5, result_crr_b6, result_crr_b7,
    ]

    # Create summary DataFrame
    summary_data_b = []
    for r in group_crr_b_results:
        summary_data_b.append({
            "Scenario": r.scenario_id,
            "Description": r.description,
            "EAD (£)": f"{r.ead:,.0f}",
            "PD": f"{r.pd_floored*100:.2f}%",
            "LGD": f"{r.lgd*100:.0f}%",
            "RWA Before SF": f"{r.rwa_before_sf:,.0f}",
            "SF": f"{r.supporting_factor:.4f}" if r.supporting_factor != 1.0 else "-",
            "RWA After SF": f"{r.rwa_after_sf:,.0f}",
        })

    summary_df_b = pl.DataFrame(summary_data_b)
    mo.ui.table(summary_df_b)
    return (group_crr_b_results,)


@app.cell
def _(group_crr_b_results):
    """Export function for use by main workbook."""
    def get_group_crr_b_results():
        """Return all Group CRR-B scenario results."""
        return group_crr_b_results
    return


if __name__ == "__main__":
    app.run()
