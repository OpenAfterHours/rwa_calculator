"""
Group CRR-H: CRR Complex/Combined Scenarios

Scenarios CRR-H1 to CRR-H4 covering complex scenarios that combine multiple features:
- Facility with multiple loans (hierarchy)
- Counterparty group (rating inheritance)
- SME chain with supporting factor
- Full CRM chain (collateral + guarantee + provision)

Usage:
    uv run marimo edit workbooks/crr_expected_outputs/scenarios/group_crr_h_complex.py

Key CRR References:
    - Art. 113: Exposure aggregation
    - Art. 142: Rating inheritance
    - Art. 501: SME supporting factor
    - Art. 207-236: CRM framework
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
        calculate_adjusted_collateral_value,
    )
    from workbooks.crr_expected_outputs.calculations.crr_supporting_factors import (
        apply_sme_supporting_factor,
    )
    from workbooks.crr_expected_outputs.data.crr_params import (
        CRR_SME_SUPPORTING_FACTOR,
    )
    return (
        CRR_SME_SUPPORTING_FACTOR,
        Decimal,
        apply_sme_supporting_factor,
        calculate_adjusted_collateral_value,
        calculate_sa_rwa,
        get_collateral_haircut,
        get_corporate_rw,
        get_institution_rw,
        load_fixtures,
        mo,
        pl,
    )


@app.cell
def _(mo):
    """Header."""
    mo.md("""
    # Group CRR-H: CRR Complex/Combined Scenarios

    This workbook calculates expected RWA values for complex scenarios CRR-H1 to CRR-H4.

    **Regulatory Framework:** CRR (Capital Requirements Regulation)
    **Effective:** Until 31 December 2026

    **Complex Scenarios Cover:**
    1. **Facility Hierarchy** - Multiple loans under one facility
    2. **Counterparty Groups** - Parent/subsidiary rating inheritance
    3. **SME with Supporting Factor** - Complete SME chain calculation
    4. **Full CRM Integration** - Collateral + Guarantee + Provision combined

    These scenarios test the integration of multiple CRR components and validate
    that the calculation pipeline handles complex real-world structures correctly.
    """)
    return


@app.cell
def _(load_fixtures):
    """Load test fixtures."""
    fixtures = load_fixtures()
    return (fixtures,)


@app.cell
def _():
    """Scenario result dataclass for Complex scenarios."""
    from dataclasses import dataclass, asdict
    from typing import Any

    @dataclass
    class CRRComplexResult:
        """Container for a single CRR complex scenario calculation result."""
        scenario_id: str
        scenario_group: str
        description: str
        # Structure
        num_exposures: int
        exposures: list[dict]
        # Aggregation
        total_ead: float
        total_rwa: float
        # Key features used
        features_tested: list[str]
        calculation_details: dict
        regulatory_reference: str

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)
    return (CRRComplexResult,)


@app.cell
def _(mo):
    """Scenario CRR-H1 Header."""
    mo.md("""
    ---
    ## Scenario CRR-H1: Facility with Multiple Loans

    **Input:** £5m revolving facility with 3 drawn loans
    - Loan 1: £2m term loan
    - Loan 2: £1.5m trade finance
    - Loan 3: £500k overdraft
    - Undrawn: £1m (50% CCF)

    **Expected:** Aggregate RWA from all exposures under facility

    **Testing:**
    - Facility-to-loan hierarchy
    - Mixed on-balance and off-balance sheet
    - CCF application for undrawn

    **Reference:** CRR Art. 111, 113
    """)
    return


@app.cell
def _(CRRComplexResult, Decimal, calculate_sa_rwa, get_corporate_rw):
    """Calculate Scenario CRR-H1: Facility with Multiple Loans."""
    # Corporate counterparty (unrated = 100% RW)
    rw_h1 = get_corporate_rw(None)

    # Individual exposures under facility
    exposures_h1 = [
        {
            "name": "Term Loan",
            "type": "drawn",
            "amount": Decimal("2000000"),
            "ccf": Decimal("1.00"),
        },
        {
            "name": "Trade Finance",
            "type": "drawn",
            "amount": Decimal("1500000"),
            "ccf": Decimal("1.00"),
        },
        {
            "name": "Overdraft",
            "type": "drawn",
            "amount": Decimal("500000"),
            "ccf": Decimal("1.00"),
        },
        {
            "name": "Undrawn Commitment",
            "type": "undrawn",
            "amount": Decimal("1000000"),
            "ccf": Decimal("0.50"),  # >1 year commitment
        },
    ]

    # Calculate EAD and RWA for each
    total_ead_h1 = Decimal("0")
    total_rwa_h1 = Decimal("0")
    exposure_details_h1 = []

    for exp in exposures_h1:
        ead = exp["amount"] * exp["ccf"]
        rwa = calculate_sa_rwa(ead, rw_h1)
        total_ead_h1 += ead
        total_rwa_h1 += rwa
        exposure_details_h1.append({
            "name": exp["name"],
            "nominal": float(exp["amount"]),
            "ccf": float(exp["ccf"]),
            "ead": float(ead),
            "rw": float(rw_h1),
            "rwa": float(rwa),
        })

    result_crr_h1 = CRRComplexResult(
        scenario_id="CRR-H1",
        scenario_group="CRR-H",
        description="Facility with multiple loans - hierarchy aggregation",
        num_exposures=len(exposures_h1),
        exposures=exposure_details_h1,
        total_ead=float(total_ead_h1),
        total_rwa=float(total_rwa_h1),
        features_tested=[
            "Facility-loan hierarchy",
            "On-balance sheet aggregation",
            "Off-balance sheet CCF",
            "Aggregate RWA",
        ],
        calculation_details={
            "facility_limit": 5000000,
            "drawn": 4000000,
            "undrawn": 1000000,
            "undrawn_ccf": 0.50,
            "aggregation": "Sum of individual loan RWAs",
        },
        regulatory_reference="CRR Art. 111, 113",
    )

    print(f"CRR-H1: Facility with {len(exposures_h1)} exposures")
    print(f"  Total EAD=£{total_ead_h1:,.0f}, Total RWA=£{total_rwa_h1:,.0f}")
    for e in exposure_details_h1:
        print(f"    {e['name']}: EAD=£{e['ead']:,.0f}, RWA=£{e['rwa']:,.0f}")
    return (result_crr_h1,)


@app.cell
def _(mo):
    """Scenario CRR-H2 Header."""
    mo.md("""
    ---
    ## Scenario CRR-H2: Counterparty Group (Rating Inheritance)

    **Input:** Corporate group with parent and 2 subsidiaries
    - Parent: Rated A (CQS 2 = 50% RW)
    - Sub 1: Unrated (inherits parent rating)
    - Sub 2: Rated BBB (CQS 3 = 100% RW, own rating)

    **Expected:** Unrated subsidiary uses parent's rating

    **Testing:**
    - Organisation hierarchy
    - Rating inheritance rules
    - CQS to risk weight mapping

    **Reference:** CRR Art. 142
    """)
    return


@app.cell
def _(CRRComplexResult, Decimal, calculate_sa_rwa, get_corporate_rw):
    """Calculate Scenario CRR-H2: Counterparty Group."""
    # Group structure
    group_members_h2 = [
        {
            "entity": "Parent Corp",
            "role": "parent",
            "own_cqs": 2,  # A-rated
            "effective_cqs": 2,
            "exposure": Decimal("3000000"),
        },
        {
            "entity": "Subsidiary 1",
            "role": "subsidiary",
            "own_cqs": None,  # Unrated
            "effective_cqs": 2,  # Inherits from parent
            "exposure": Decimal("1500000"),
        },
        {
            "entity": "Subsidiary 2",
            "role": "subsidiary",
            "own_cqs": 3,  # BBB-rated
            "effective_cqs": 3,  # Uses own rating
            "exposure": Decimal("500000"),
        },
    ]

    # Calculate RWA for each
    total_ead_h2 = Decimal("0")
    total_rwa_h2 = Decimal("0")
    exposure_details_h2 = []

    for member in group_members_h2:
        ead = member["exposure"]
        rw = get_corporate_rw(member["effective_cqs"])
        rwa = calculate_sa_rwa(ead, rw)
        total_ead_h2 += ead
        total_rwa_h2 += rwa

        exposure_details_h2.append({
            "entity": member["entity"],
            "role": member["role"],
            "own_cqs": member["own_cqs"],
            "effective_cqs": member["effective_cqs"],
            "ead": float(ead),
            "rw": float(rw),
            "rwa": float(rwa),
            "rating_source": "own" if member["own_cqs"] else "inherited",
        })

    result_crr_h2 = CRRComplexResult(
        scenario_id="CRR-H2",
        scenario_group="CRR-H",
        description="Counterparty group - rating inheritance",
        num_exposures=len(group_members_h2),
        exposures=exposure_details_h2,
        total_ead=float(total_ead_h2),
        total_rwa=float(total_rwa_h2),
        features_tested=[
            "Organisation hierarchy",
            "Parent-subsidiary relationship",
            "Rating inheritance",
            "CQS mapping",
        ],
        calculation_details={
            "parent_rating": "A (CQS 2)",
            "inheritance_rule": "Unrated subsidiary inherits parent rating",
            "sub1_treatment": "Inherits CQS 2 from parent",
            "sub2_treatment": "Uses own BBB rating (CQS 3)",
        },
        regulatory_reference="CRR Art. 142",
    )

    print(f"CRR-H2: Counterparty group with {len(group_members_h2)} members")
    print(f"  Total EAD=£{total_ead_h2:,.0f}, Total RWA=£{total_rwa_h2:,.0f}")
    for e in exposure_details_h2:
        print(f"    {e['entity']}: CQS={e['effective_cqs']}, RW={e['rw']*100:.0f}%, RWA=£{e['rwa']:,.0f}")
    return (result_crr_h2,)


@app.cell
def _(mo):
    """Scenario CRR-H3 Header."""
    mo.md("""
    ---
    ## Scenario CRR-H3: SME Chain with Supporting Factor

    **Input:** £2m loan to SME corporate (turnover £25m)
    **Expected:** 100% RW × 0.7619 SME factor = 76.19% effective RW

    **Testing:**
    - SME eligibility check (turnover < £44m)
    - Supporting factor application
    - End-to-end SME treatment

    **Reference:** CRR Art. 501
    """)
    return


@app.cell
def _(
    CRR_SME_SUPPORTING_FACTOR,
    CRRComplexResult,
    Decimal,
    apply_sme_supporting_factor,
    calculate_sa_rwa,
    get_corporate_rw,
):
    """Calculate Scenario CRR-H3: SME Chain."""
    # SME corporate
    ead_h3 = Decimal("2000000")
    turnover_h3 = Decimal("25000000")  # £25m < £44m threshold
    rw_h3 = get_corporate_rw(None)  # 100% (unrated)

    # Calculate RWA before supporting factor
    rwa_before_sf_h3 = calculate_sa_rwa(ead_h3, rw_h3)

    # Apply SME supporting factor
    rwa_after_sf_h3, sf_applied_h3, sf_desc_h3 = apply_sme_supporting_factor(
        rwa=rwa_before_sf_h3,
        is_sme=True,
        turnover=turnover_h3,
        currency="GBP",
    )

    # Calculate effective RW
    effective_rw_h3 = float(rwa_after_sf_h3) / float(ead_h3)

    exposure_details_h3 = [{
        "entity": "SME Corporate",
        "turnover_gbp": float(turnover_h3),
        "sme_threshold_gbp": 44000000,
        "is_sme": True,
        "ead": float(ead_h3),
        "base_rw": float(rw_h3),
        "rwa_before_sf": float(rwa_before_sf_h3),
        "supporting_factor": float(CRR_SME_SUPPORTING_FACTOR),
        "rwa_after_sf": float(rwa_after_sf_h3),
        "effective_rw": effective_rw_h3,
    }]

    result_crr_h3 = CRRComplexResult(
        scenario_id="CRR-H3",
        scenario_group="CRR-H",
        description="SME chain - supporting factor application",
        num_exposures=1,
        exposures=exposure_details_h3,
        total_ead=float(ead_h3),
        total_rwa=float(rwa_after_sf_h3),
        features_tested=[
            "SME eligibility (turnover check)",
            "SME supporting factor (0.7619)",
            "Effective RW calculation",
            "CRR-specific treatment",
        ],
        calculation_details={
            "turnover": f"£{turnover_h3:,.0f}",
            "sme_threshold": "£44,000,000",
            "is_eligible": True,
            "base_rw": "100%",
            "supporting_factor": float(CRR_SME_SUPPORTING_FACTOR),
            "effective_rw": f"{effective_rw_h3*100:.2f}%",
            "rwa_reduction": float(rwa_before_sf_h3 - rwa_after_sf_h3),
            "note": "SME factor NOT available under Basel 3.1",
        },
        regulatory_reference="CRR Art. 501",
    )

    print(f"CRR-H3: SME with Supporting Factor")
    print(f"  Turnover=£{turnover_h3:,.0f}, EAD=£{ead_h3:,.0f}")
    print(f"  RWA before SF=£{rwa_before_sf_h3:,.0f}")
    print(f"  SF={CRR_SME_SUPPORTING_FACTOR}, RWA after SF=£{rwa_after_sf_h3:,.0f}")
    print(f"  Effective RW={effective_rw_h3*100:.2f}%")
    return (result_crr_h3,)


@app.cell
def _(mo):
    """Scenario CRR-H4 Header."""
    mo.md("""
    ---
    ## Scenario CRR-H4: Full CRM Chain

    **Input:** £2m corporate exposure with multiple CRM techniques
    - £500k cash collateral
    - £400k bank guarantee (CQS 2 = 30% RW UK)
    - £100k specific provision

    **Expected:** Combined effect of all CRM techniques

    **Testing:**
    - Collateral haircut application
    - Guarantee substitution
    - Provision deduction
    - Sequential CRM application

    **Reference:** CRR Art. 207-236
    """)
    return


@app.cell
def _(
    CRRComplexResult,
    Decimal,
    calculate_adjusted_collateral_value,
    calculate_sa_rwa,
    get_collateral_haircut,
    get_corporate_rw,
    get_institution_rw,
):
    """Calculate Scenario CRR-H4: Full CRM Chain."""
    # Base exposure
    gross_exp_h4 = Decimal("2000000")
    borrower_rw_h4 = get_corporate_rw(None)  # 100%

    # Step 1: Specific provision reduces EAD (SA treatment)
    provision_h4 = Decimal("100000")
    exp_after_prov_h4 = gross_exp_h4 - provision_h4

    # Step 2: Cash collateral (0% haircut)
    cash_coll_h4 = Decimal("500000")
    cash_haircut_h4 = get_collateral_haircut("cash")
    cash_adjusted_h4 = calculate_adjusted_collateral_value(
        cash_coll_h4, cash_haircut_h4, Decimal("0.00")
    )
    exp_after_cash_h4 = exp_after_prov_h4 - cash_adjusted_h4

    # Step 3: Bank guarantee (substitution approach)
    guarantee_amount_h4 = Decimal("400000")
    guarantor_rw_h4 = get_institution_rw(cqs=2, country="GB", use_uk_deviation=True)  # 30%

    # Split remaining exposure
    guaranteed_portion_h4 = min(guarantee_amount_h4, exp_after_cash_h4)
    non_guaranteed_h4 = exp_after_cash_h4 - guaranteed_portion_h4

    # Calculate final RWA
    rwa_guaranteed_h4 = calculate_sa_rwa(guaranteed_portion_h4, guarantor_rw_h4)
    rwa_non_guaranteed_h4 = calculate_sa_rwa(non_guaranteed_h4, borrower_rw_h4)
    total_rwa_h4 = rwa_guaranteed_h4 + rwa_non_guaranteed_h4

    # Compare to pre-CRM
    rwa_pre_crm_h4 = calculate_sa_rwa(gross_exp_h4, borrower_rw_h4)
    rwa_reduction_h4 = rwa_pre_crm_h4 - total_rwa_h4

    exposure_details_h4 = [{
        "step": "Gross Exposure",
        "amount": float(gross_exp_h4),
        "rw": float(borrower_rw_h4),
        "rwa": float(rwa_pre_crm_h4),
        "description": "Pre-CRM",
    }, {
        "step": "After Provision",
        "amount": float(exp_after_prov_h4),
        "rw": None,
        "rwa": None,
        "description": f"Less £{provision_h4:,.0f} provision",
    }, {
        "step": "After Cash Collateral",
        "amount": float(exp_after_cash_h4),
        "rw": None,
        "rwa": None,
        "description": f"Less £{cash_adjusted_h4:,.0f} cash",
    }, {
        "step": "Guaranteed Portion",
        "amount": float(guaranteed_portion_h4),
        "rw": float(guarantor_rw_h4),
        "rwa": float(rwa_guaranteed_h4),
        "description": "Bank guarantee (30% RW)",
    }, {
        "step": "Non-Guaranteed Portion",
        "amount": float(non_guaranteed_h4),
        "rw": float(borrower_rw_h4),
        "rwa": float(rwa_non_guaranteed_h4),
        "description": "Borrower risk (100% RW)",
    }]

    result_crr_h4 = CRRComplexResult(
        scenario_id="CRR-H4",
        scenario_group="CRR-H",
        description="Full CRM chain - collateral + guarantee + provision",
        num_exposures=1,
        exposures=exposure_details_h4,
        total_ead=float(exp_after_cash_h4),  # Net of cash and provision
        total_rwa=float(total_rwa_h4),
        features_tested=[
            "Specific provision (EAD reduction)",
            "Cash collateral (0% haircut)",
            "Bank guarantee (substitution)",
            "Sequential CRM application",
            "Split RW treatment",
        ],
        calculation_details={
            "gross_exposure": float(gross_exp_h4),
            "provision": float(provision_h4),
            "cash_collateral": float(cash_coll_h4),
            "guarantee": float(guarantee_amount_h4),
            "borrower_rw": float(borrower_rw_h4),
            "guarantor_rw": float(guarantor_rw_h4),
            "rwa_pre_crm": float(rwa_pre_crm_h4),
            "rwa_post_crm": float(total_rwa_h4),
            "rwa_reduction": float(rwa_reduction_h4),
            "reduction_pct": float(rwa_reduction_h4 / rwa_pre_crm_h4 * 100),
        },
        regulatory_reference="CRR Art. 207-236",
    )

    print(f"CRR-H4: Full CRM Chain")
    print(f"  Gross=£{gross_exp_h4:,.0f}")
    print(f"  Provision=£{provision_h4:,.0f}, Cash=£{cash_coll_h4:,.0f}, Guarantee=£{guarantee_amount_h4:,.0f}")
    print(f"  RWA pre-CRM=£{rwa_pre_crm_h4:,.0f}")
    print(f"  RWA post-CRM=£{total_rwa_h4:,.0f}")
    print(f"  Reduction=£{rwa_reduction_h4:,.0f} ({float(rwa_reduction_h4/rwa_pre_crm_h4*100):.1f}%)")
    return (result_crr_h4,)


@app.cell
def _(mo):
    """Summary Section."""
    mo.md("""
    ---
    ## Summary: Group CRR-H Complex Scenario Results

    Key observations from complex scenarios:

    **H1 - Facility Hierarchy:**
    - Correctly aggregates on-balance and off-balance sheet exposures
    - Applies appropriate CCFs to undrawn commitments

    **H2 - Counterparty Groups:**
    - Demonstrates rating inheritance for unrated subsidiaries
    - Entities with own ratings use their own CQS

    **H3 - SME Chain:**
    - Complete end-to-end SME treatment
    - 23.81% RWA reduction from supporting factor
    - Key CRR advantage over Basel 3.1

    **H4 - Full CRM:**
    - Sequential application of multiple CRM techniques
    - Significant RWA reduction possible with comprehensive CRM
    - Demonstrates substitution approach for guarantees
    """)
    return


@app.cell
def _(mo, pl, result_crr_h1, result_crr_h2, result_crr_h3, result_crr_h4):
    """Compile all Group CRR-H results."""
    group_crr_h_results = [
        result_crr_h1, result_crr_h2, result_crr_h3, result_crr_h4,
    ]

    # Create summary DataFrame
    summary_data_h = []
    for r in group_crr_h_results:
        summary_data_h.append({
            "Scenario": r.scenario_id,
            "Description": r.description[:40] + "...",
            "Exposures": r.num_exposures,
            "Total EAD (£)": f"{r.total_ead:,.0f}",
            "Total RWA (£)": f"{r.total_rwa:,.0f}",
            "Features": ", ".join(r.features_tested[:2]),
        })

    summary_df_h = pl.DataFrame(summary_data_h)
    mo.ui.table(summary_df_h)
    return (group_crr_h_results,)


@app.cell
def _(group_crr_h_results):
    """Export function for use by main workbook."""
    def get_group_crr_h_results():
        """Return all Group CRR-H scenario results."""
        return group_crr_h_results
    return (get_group_crr_h_results,)


if __name__ == "__main__":
    app.run()
