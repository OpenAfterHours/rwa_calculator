"""
Group CRR-E: CRR Specialised Lending (Slotting) Scenarios

Scenarios CRR-E1 to CRR-E4 covering slotting approach for specialised lending:
- Project Finance
- Income-Producing Real Estate (IPRE)
- High Volatility Commercial Real Estate (HVCRE)
- Object Finance

Usage:
    uv run marimo edit workbooks/crr_expected_outputs/scenarios/group_crr_e_slotting.py

Key CRR References:
    - Art. 153(5): Slotting approach for specialised lending
    - Art. 147(8): Specialised lending definition
    - Five slotting categories: Strong, Good, Satisfactory, Weak, Default

Note: Banks without A-IRB approval for specialised lending must use slotting.
This is the alternative to A-IRB for specialised lending exposures.
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
    from workbooks.crr_expected_outputs.data.crr_params import (
        CRR_SLOTTING_RW,
        CRR_SLOTTING_RW_HVCRE,
    )
    return (
        CRR_SLOTTING_RW,
        CRR_SLOTTING_RW_HVCRE,
        Decimal,
        load_fixtures,
        mo,
        pl,
    )


@app.cell
def _(mo):
    """Header."""
    mo.md("""
    # Group CRR-E: CRR Specialised Lending (Slotting) Scenarios

    This workbook calculates expected RWA values for CRR slotting scenarios CRR-E1 to CRR-E4.

    **Regulatory Framework:** CRR (Capital Requirements Regulation)
    **Effective:** Until 31 December 2026

    **Specialised Lending Categories (Art. 147(8)):**
    1. **Project Finance (PF)** - Large, complex infrastructure projects
    2. **Object Finance (OF)** - Physical assets (ships, aircraft, satellites)
    3. **Commodities Finance (CF)** - Reserve-based lending
    4. **Income-Producing Real Estate (IPRE)** - Commercial RE repaid from property income
    5. **High Volatility Commercial Real Estate (HVCRE)** - Higher risk CRE (land, ADC)

    **CRR Slotting Risk Weights (Art. 153(5), >=2.5yr maturity):**

    | Category | Non-HVCRE | HVCRE |
    |----------|-----------|-------|
    | Strong | 70% | 95% |
    | Good | 90% | 120% |
    | Satisfactory | 115% | 140% |
    | Weak | 250% | 250% |
    | Default | 0% (provisioned) | 0% |

    **Maturity split (<2.5yr remaining maturity):**
    | Category | Non-HVCRE | HVCRE |
    |----------|-----------|-------|
    | Strong | 50% | 70% |
    | Good | 70% | 95% |

    **Key CRR difference from Basel 3.1:**
    - CRR differentiates by maturity (<2.5yr vs >=2.5yr)
    - CRR has separate HVCRE table with higher weights
    - Basel 3.1 differentiates by HVCRE/PF pre-op/operational
    """)
    return


@app.cell
def _(load_fixtures):
    """Load test fixtures."""
    fixtures = load_fixtures()
    return (fixtures,)


@app.cell
def _():
    """Helper functions for slotting calculations."""
    from decimal import Decimal

    def get_slotting_rw(
        category: str,
        is_hvcre: bool = False
    ) -> Decimal:
        """
        Get CRR slotting risk weight for specialised lending (>=2.5yr maturity).

        CRR Art. 153(5) defines separate tables for non-HVCRE and HVCRE,
        each with maturity splits. This function returns the >=2.5yr weights
        (test fixtures use 5yr maturity).

        Args:
            category: Slotting category (strong, good, satisfactory, weak, default)
            is_hvcre: Whether this is HVCRE

        Returns:
            Risk weight as Decimal
        """
        if is_hvcre:
            # CRR HVCRE (Table 2) — remaining maturity >= 2.5yr
            weights = {
                "strong": Decimal("0.95"),
                "good": Decimal("1.20"),
                "satisfactory": Decimal("1.40"),
                "weak": Decimal("2.50"),
                "default": Decimal("0.00"),
            }
        else:
            # CRR Non-HVCRE (Table 1) — remaining maturity >= 2.5yr
            weights = {
                "strong": Decimal("0.70"),
                "good": Decimal("0.90"),
                "satisfactory": Decimal("1.15"),
                "weak": Decimal("2.50"),
                "default": Decimal("0.00"),
            }
        return weights.get(category.lower(), Decimal("1.15"))

    def calculate_slotting_rwa(
        ead: Decimal,
        category: str,
        is_hvcre: bool = False
    ) -> tuple[Decimal, Decimal]:
        """
        Calculate RWA using slotting approach.

        Args:
            ead: Exposure at default
            category: Slotting category
            is_hvcre: Whether HVCRE

        Returns:
            Tuple of (risk_weight, rwa)
        """
        rw = get_slotting_rw(category, is_hvcre)
        rwa = ead * rw
        return rw, rwa

    return (calculate_slotting_rwa, get_slotting_rw,)


@app.cell
def _():
    """Scenario result dataclass for Slotting."""
    from dataclasses import dataclass, asdict
    from typing import Any

    @dataclass
    class CRRSlottingResult:
        """Container for a single CRR slotting scenario calculation result."""
        scenario_id: str
        scenario_group: str
        description: str
        exposure_reference: str
        counterparty_reference: str
        approach: str
        exposure_class: str
        lending_type: str
        slotting_category: str
        is_hvcre: bool
        ead: float
        risk_weight: float
        rwa: float
        calculation_details: dict
        regulatory_reference: str

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)
    return (CRRSlottingResult,)


@app.cell
def _(mo):
    """Scenario CRR-E1 Header."""
    mo.md("""
    ---
    ## Scenario CRR-E1: Project Finance - Strong Category

    **Input:** £10m project finance exposure, Strong category, >=2.5yr maturity
    **Expected:** 70% RW, £7m RWA

    **CRR Treatment (Art. 153(5), >=2.5yr maturity):**
    - Strong category: 70% RW (50% if <2.5yr remaining maturity)
    - Good category: 90% RW (70% if <2.5yr remaining maturity)

    **Strong Category Characteristics:**
    - Project has very robust economics
    - Project entity has very strong financial structure
    - Sponsors are investment grade with strong commitment
    - Proven technology and conservative design

    **Reference:** CRR Art. 153(5)
    """)
    return


@app.cell
def _(CRRSlottingResult, Decimal, calculate_slotting_rwa):
    """Calculate Scenario CRR-E1: Project Finance - Strong."""
    # Input
    ead_e1 = Decimal("10000000")
    category_e1 = "strong"
    is_hvcre_e1 = False

    # Calculate
    rw_e1, rwa_e1 = calculate_slotting_rwa(ead_e1, category_e1, is_hvcre_e1)

    result_crr_e1 = CRRSlottingResult(
        scenario_id="CRR-E1",
        scenario_group="CRR-E",
        description="Project finance - Strong category (70% RW, >=2.5yr maturity)",
        exposure_reference="LOAN_SL_PF_001",
        counterparty_reference="SL_PF_STRONG",
        approach="Slotting",
        exposure_class="SPECIALISED_LENDING",
        lending_type="Project Finance",
        slotting_category="Strong",
        is_hvcre=is_hvcre_e1,
        ead=float(ead_e1),
        risk_weight=float(rw_e1),
        rwa=float(rwa_e1),
        calculation_details={
            "crr_rw": "70% (>=2.5yr), 50% (<2.5yr)",
            "basel31_rw": "70% operational, 80% PF pre-op",
            "formula": "RWA = EAD × RW",
            "calculation": f"RWA = £{ead_e1:,.0f} × 70% = £{rwa_e1:,.0f}",
            "note": "CRR Strong=70% for non-HVCRE with >=2.5yr maturity",
        },
        regulatory_reference="CRR Art. 153(5)",
    )

    print(f"CRR-E1: Project Finance (Strong)")
    print(f"  EAD=£{ead_e1:,.0f}, RW={rw_e1*100:.0f}%, RWA=£{rwa_e1:,.0f}")
    return (result_crr_e1,)


@app.cell
def _(mo):
    """Scenario CRR-E2 Header."""
    mo.md("""
    ---
    ## Scenario CRR-E2: Project Finance - Good Category

    **Input:** £10m project finance exposure, Good category, >=2.5yr maturity
    **Expected:** 90% RW, £9m RWA

    **Good Category Characteristics:**
    - Project has robust economics
    - Project entity has sound financial structure
    - Sponsors have good track record and commitment
    - Tested technology

    **Reference:** CRR Art. 153(5)
    """)
    return


@app.cell
def _(CRRSlottingResult, Decimal, calculate_slotting_rwa):
    """Calculate Scenario CRR-E2: Project Finance - Good."""
    ead_e2 = Decimal("10000000")
    category_e2 = "good"
    is_hvcre_e2 = False

    rw_e2, rwa_e2 = calculate_slotting_rwa(ead_e2, category_e2, is_hvcre_e2)

    result_crr_e2 = CRRSlottingResult(
        scenario_id="CRR-E2",
        scenario_group="CRR-E",
        description="Project finance - Good category (90% RW, >=2.5yr maturity)",
        exposure_reference="LOAN_SL_PF_002",
        counterparty_reference="SL_PF_GOOD",
        approach="Slotting",
        exposure_class="SPECIALISED_LENDING",
        lending_type="Project Finance",
        slotting_category="Good",
        is_hvcre=is_hvcre_e2,
        ead=float(ead_e2),
        risk_weight=float(rw_e2),
        rwa=float(rwa_e2),
        calculation_details={
            "crr_rw": "90% (>=2.5yr), 70% (<2.5yr)",
            "basel31_rw": "90% operational",
            "formula": "RWA = EAD × RW",
            "calculation": f"RWA = £{ead_e2:,.0f} × {rw_e2*100:.0f}% = £{rwa_e2:,.0f}",
        },
        regulatory_reference="CRR Art. 153(5)",
    )

    print(f"CRR-E2: Project Finance (Good)")
    print(f"  EAD=£{ead_e2:,.0f}, RW={rw_e2*100:.0f}%, RWA=£{rwa_e2:,.0f}")
    return (result_crr_e2,)


@app.cell
def _(mo):
    """Scenario CRR-E3 Header."""
    mo.md("""
    ---
    ## Scenario CRR-E3: IPRE - Weak Category

    **Input:** £5m income-producing real estate, Weak category
    **Expected:** 250% RW, £12.5m RWA

    **IPRE Definition:**
    - Commercial real estate where repayment depends primarily on
      cash flows generated by the property
    - Rental income from tenants

    **Weak Category Characteristics:**
    - High vacancy rates or declining market
    - Thin or negative debt service coverage
    - Significant re-letting risk
    - Below-average property quality

    **Reference:** CRR Art. 153(5)
    """)
    return


@app.cell
def _(CRRSlottingResult, Decimal, calculate_slotting_rwa):
    """Calculate Scenario CRR-E3: IPRE - Weak."""
    ead_e3 = Decimal("5000000")
    category_e3 = "weak"
    is_hvcre_e3 = False  # IPRE, not HVCRE

    rw_e3, rwa_e3 = calculate_slotting_rwa(ead_e3, category_e3, is_hvcre_e3)

    result_crr_e3 = CRRSlottingResult(
        scenario_id="CRR-E3",
        scenario_group="CRR-E",
        description="IPRE - Weak category (250% RW)",
        exposure_reference="LOAN_SL_IPRE_001",
        counterparty_reference="SL_IPRE_WEAK",
        approach="Slotting",
        exposure_class="SPECIALISED_LENDING",
        lending_type="Income-Producing Real Estate (IPRE)",
        slotting_category="Weak",
        is_hvcre=is_hvcre_e3,
        ead=float(ead_e3),
        risk_weight=float(rw_e3),
        rwa=float(rwa_e3),
        calculation_details={
            "crr_rw": "250%",
            "basel31_rw": "150% (lower than CRR)",
            "formula": "RWA = EAD × RW",
            "calculation": f"RWA = £{ead_e3:,.0f} × 250% = £{rwa_e3:,.0f}",
            "note": "Weak category has punitive RW - close monitoring required",
        },
        regulatory_reference="CRR Art. 153(5)",
    )

    print(f"CRR-E3: IPRE (Weak)")
    print(f"  EAD=£{ead_e3:,.0f}, RW={rw_e3*100:.0f}%, RWA=£{rwa_e3:,.0f}")
    return (result_crr_e3,)


@app.cell
def _(mo):
    """Scenario CRR-E4 Header."""
    mo.md("""
    ---
    ## Scenario CRR-E4: HVCRE - Strong Category

    **Input:** £5m high volatility commercial real estate, Strong category, >=2.5yr maturity
    **Expected:** 95% RW, £4.75m RWA

    **HVCRE Definition:**
    - Land acquisition
    - Development and construction (ADC)
    - Commercial real estate with higher price volatility
    - Loans where repayment depends on sale of property

    **CRR Treatment (Art. 153(5) Table 2):**
    - HVCRE Strong (>=2.5yr): 95% RW (70% if <2.5yr)
    - Higher than non-HVCRE Strong (70%)

    **Reference:** CRR Art. 153(5)
    """)
    return


@app.cell
def _(CRRSlottingResult, Decimal, calculate_slotting_rwa):
    """Calculate Scenario CRR-E4: HVCRE - Strong."""
    ead_e4 = Decimal("5000000")
    category_e4 = "strong"
    is_hvcre_e4 = True  # High Volatility CRE

    rw_e4, rwa_e4 = calculate_slotting_rwa(ead_e4, category_e4, is_hvcre_e4)

    result_crr_e4 = CRRSlottingResult(
        scenario_id="CRR-E4",
        scenario_group="CRR-E",
        description="HVCRE - Strong category (95% RW, >=2.5yr maturity)",
        exposure_reference="LOAN_SL_HVCRE_001",
        counterparty_reference="SL_HVCRE_STRONG",
        approach="Slotting",
        exposure_class="SPECIALISED_LENDING",
        lending_type="High Volatility Commercial Real Estate (HVCRE)",
        slotting_category="Strong",
        is_hvcre=is_hvcre_e4,
        ead=float(ead_e4),
        risk_weight=float(rw_e4),
        rwa=float(rwa_e4),
        calculation_details={
            "crr_rw": "95% (>=2.5yr), 70% (<2.5yr)",
            "basel31_rw": "95% (HVCRE Strong)",
            "formula": "RWA = EAD × RW",
            "calculation": f"RWA = £{ead_e4:,.0f} × {rw_e4*100:.0f}% = £{rwa_e4:,.0f}",
            "note": "CRR HVCRE has higher weights than non-HVCRE",
        },
        regulatory_reference="CRR Art. 153(5)",
    )

    print(f"CRR-E4: HVCRE (Strong)")
    print(f"  EAD=£{ead_e4:,.0f}, RW={rw_e4*100:.0f}%, RWA=£{rwa_e4:,.0f}")
    return (result_crr_e4,)


@app.cell
def _(mo):
    """Summary Section."""
    mo.md("""
    ---
    ## Summary: Group CRR-E Slotting Results

    Key CRR slotting observations (Art. 153(5), >=2.5yr maturity):
    1. **Non-HVCRE** - Strong=70%, Good=90%, Satisfactory=115%, Weak=250%
    2. **HVCRE** - Higher weights: Strong=95%, Good=120%, Satisfactory=140%, Weak=250%
    3. **Maturity split** - Lower weights for <2.5yr remaining maturity
    4. **Default = 0%** - Assumed 100% provisioned

    **CRR vs Basel 3.1 Comparison (>=2.5yr maturity):**

    | Category | CRR (Non-HVCRE) | CRR (HVCRE) | Basel 3.1 (Operational) | Basel 3.1 (HVCRE) |
    |----------|-----------------|-------------|------------------------|-------------------|
    | Strong | 70% | 95% | 70% | 95% |
    | Good | 90% | 120% | 90% | 120% |
    | Satisfactory | 115% | 140% | 115% | 140% |
    | Weak | 250% | 250% | 250% | 250% |
    | Default | 0% | 0% | 0% | 0% |
    """)
    return


@app.cell
def _(mo, pl, result_crr_e1, result_crr_e2, result_crr_e3, result_crr_e4):
    """Compile all Group CRR-E results."""
    group_crr_e_results = [
        result_crr_e1, result_crr_e2, result_crr_e3, result_crr_e4,
    ]

    # Create summary DataFrame
    summary_data_e = []
    for r in group_crr_e_results:
        summary_data_e.append({
            "Scenario": r.scenario_id,
            "Lending Type": r.lending_type,
            "Category": r.slotting_category,
            "HVCRE": "Yes" if r.is_hvcre else "No",
            "EAD (£)": f"{r.ead:,.0f}",
            "RW": f"{r.risk_weight*100:.0f}%",
            "RWA (£)": f"{r.rwa:,.0f}",
        })

    summary_df_e = pl.DataFrame(summary_data_e)
    mo.ui.table(summary_df_e)
    return (group_crr_e_results,)


@app.cell
def _(group_crr_e_results):
    """Export function for use by main workbook."""
    def get_group_crr_e_results():
        """Return all Group CRR-E scenario results."""
        return group_crr_e_results
    return (get_group_crr_e_results,)


if __name__ == "__main__":
    app.run()
