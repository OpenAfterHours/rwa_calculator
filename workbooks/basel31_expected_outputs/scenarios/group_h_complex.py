"""
Group H: Complex/Combined Scenarios

Scenarios H1-H4 covering hierarchy tests, rating inheritance, mixed approaches,
and full CRM chains.

Usage:
    uv run marimo edit workbooks/rwa_expected_outputs/scenarios/group_h_complex.py
"""

import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import polars as pl
    import sys
    from pathlib import Path
    from dataclasses import dataclass, asdict
    from typing import Any

    project_root = Path(__file__).parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from workbooks.rwa_expected_outputs.data.fixture_loader import load_fixtures
    from workbooks.rwa_expected_outputs.calculations.sa_risk_weights import (
        get_corporate_risk_weight,
        calculate_sa_rwa,
    )
    from workbooks.rwa_expected_outputs.calculations.crm_haircuts import (
        calculate_adjusted_collateral_value,
        calculate_guarantee_substitution,
    )

    @dataclass
    class ScenarioResult:
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

    return (
        mo,
        pl,
        Path,
        load_fixtures,
        get_corporate_risk_weight,
        calculate_sa_rwa,
        calculate_adjusted_collateral_value,
        calculate_guarantee_substitution,
        ScenarioResult,
    )


@app.cell
def _(mo):
    mo.md("""
    # Group H: Complex/Combined Scenarios

    These scenarios test:
    - H1: Facility with multiple loans (exposure hierarchy)
    - H2: Counterparty group (org hierarchy, rating inheritance)
    - H3: Mixed approach portfolio (SA and IRB separation)
    - H4: Full CRM chain (collateral + guarantee + provision)
    """)
    return


@app.cell
def _(load_fixtures):
    fixtures = load_fixtures()
    return (fixtures,)


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario H1: Facility with Multiple Loans

    **Input:** £5m facility with 3 loans drawn (£1.5m + £2.0m + £1.0m = £4.5m)
    **Expected:** Aggregate RWA = sum of individual loan RWAs
    """)
    return


@app.cell
def _(fixtures, get_corporate_risk_weight, calculate_sa_rwa, ScenarioResult):
    # H1: Multiple loans under single facility
    # Loans: LOAN_HIER_001_A (1.5m), LOAN_HIER_001_B (2.0m), LOAN_HIER_001_C (1.0m)

    loan_h1_a = fixtures.get_loan("LOAN_HIER_001_A")
    loan_h1_b = fixtures.get_loan("LOAN_HIER_001_B")
    loan_h1_c = fixtures.get_loan("LOAN_HIER_001_C")

    loans_h1 = []
    total_ead_h1 = 0
    total_rwa_h1 = 0

    rw_h1 = get_corporate_risk_weight(2)  # CQS 2 = 50%

    for loan_ref, loan_data in [
        ("LOAN_HIER_001_A", loan_h1_a),
        ("LOAN_HIER_001_B", loan_h1_b),
        ("LOAN_HIER_001_C", loan_h1_c),
    ]:
        if loan_data:
            ead = loan_data["drawn_amount"]
            rwa = calculate_sa_rwa(ead, rw_h1)
            loans_h1.append(
                {
                    "reference": loan_ref,
                    "ead": ead,
                    "rwa": rwa,
                }
            )
            total_ead_h1 += ead
            total_rwa_h1 += rwa

    result_h1 = ScenarioResult(
        scenario_id="H1",
        scenario_group="H",
        description="Facility with multiple loans",
        exposure_reference="FAC_HIER_001",
        counterparty_reference="CORP_GRP1_PARENT",
        approach="SA",
        exposure_class="CORPORATE",
        ead=total_ead_h1,
        risk_weight=rw_h1,
        rwa=total_rwa_h1,
        calculation_details={
            "facility_limit": 5_000_000,
            "loans": loans_h1,
            "total_drawn": total_ead_h1,
            "undrawn": 5_000_000 - total_ead_h1,
            "aggregation": "Sum of individual loan RWAs",
        },
        regulatory_reference="CRR Art 166",
    )

    print(f"H1: Facility £5m, Total drawn=£{total_ead_h1:,.0f}")
    for l in loans_h1:
        print(f"    {l['reference']}: EAD=£{l['ead']:,.0f}, RWA=£{l['rwa']:,.0f}")
    print(f"    Total RWA=£{total_rwa_h1:,.0f}")
    return result_h1, loan_h1_a, loan_h1_b, loan_h1_c, loans_h1, total_ead_h1, total_rwa_h1, rw_h1


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario H2: Counterparty Group (Rating Inheritance)

    **Input:** Parent (CQS 2) + 2 unrated subsidiaries
    **Expected:** Subsidiaries inherit parent rating for RW determination
    """)
    return


@app.cell
def _(get_corporate_risk_weight, calculate_sa_rwa, ScenarioResult):
    # H2: Counterparty group with rating inheritance
    # Parent: CORP_GRP1_PARENT (CQS 2)
    # Subsidiaries: CORP_GRP1_SUB1, CORP_GRP1_SUB2 (unrated, inherit parent)

    parent_cqs_h2 = 2
    parent_rw_h2 = get_corporate_risk_weight(parent_cqs_h2)  # 50%

    group_exposures_h2 = [
        {"entity": "CORP_GRP1_PARENT", "ead": 2_000_000, "own_rating": True},
        {"entity": "CORP_GRP1_SUB1", "ead": 1_000_000, "own_rating": False},
        {"entity": "CORP_GRP1_SUB2", "ead": 500_000, "own_rating": False},
    ]

    total_ead_h2 = 0
    total_rwa_h2 = 0

    for exp in group_exposures_h2:
        # All use parent's rating (inheritance)
        rw = parent_rw_h2
        rwa = calculate_sa_rwa(exp["ead"], rw)
        exp["inherited_cqs"] = parent_cqs_h2
        exp["risk_weight"] = rw
        exp["rwa"] = rwa
        total_ead_h2 += exp["ead"]
        total_rwa_h2 += rwa

    result_h2 = ScenarioResult(
        scenario_id="H2",
        scenario_group="H",
        description="Counterparty group (rating inheritance)",
        exposure_reference="GROUP_ORG_001",
        counterparty_reference="CORP_GRP1_PARENT",
        approach="SA",
        exposure_class="CORPORATE",
        ead=total_ead_h2,
        risk_weight=parent_rw_h2,
        rwa=total_rwa_h2,
        calculation_details={
            "parent_cqs": parent_cqs_h2,
            "parent_rw": parent_rw_h2,
            "group_exposures": group_exposures_h2,
            "inheritance_rule": "Unrated subsidiaries inherit parent CQS",
        },
        regulatory_reference="CRR Art 122",
    )

    print(f"H2: Parent CQS={parent_cqs_h2}, RW={parent_rw_h2 * 100:.0f}%")
    for exp in group_exposures_h2:
        print(f"    {exp['entity']}: EAD=£{exp['ead']:,.0f}, RWA=£{exp['rwa']:,.0f}")
    print(f"    Total RWA=£{total_rwa_h2:,.0f}")
    return result_h2, parent_cqs_h2, parent_rw_h2, group_exposures_h2, total_ead_h2, total_rwa_h2


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario H3: Mixed Approach Portfolio

    **Input:** Portfolio with both SA and IRB exposures
    **Expected:** Correct separation and aggregation by approach
    """)
    return


@app.cell
def _(ScenarioResult):
    # H3: Mixed approach portfolio
    # Some exposures use SA, others use IRB

    sa_exposures_h3 = [
        {"reference": "LOAN_SA_001", "ead": 5_000_000, "rw": 1.00, "class": "CORPORATE"},
        {"reference": "LOAN_SA_002", "ead": 2_000_000, "rw": 0.75, "class": "RETAIL"},
    ]

    irb_exposures_h3 = [
        {"reference": "LOAN_IRB_001", "ead": 10_000_000, "rwa": 3_500_000, "class": "CORPORATE"},
        {"reference": "LOAN_IRB_002", "ead": 3_000_000, "rwa": 600_000, "class": "RETAIL_MORTGAGE"},
    ]

    # Calculate SA RWA
    sa_rwa_h3 = sum(exp["ead"] * exp["rw"] for exp in sa_exposures_h3)
    sa_ead_h3 = sum(exp["ead"] for exp in sa_exposures_h3)

    # IRB RWA (pre-calculated)
    irb_rwa_h3 = sum(exp["rwa"] for exp in irb_exposures_h3)
    irb_ead_h3 = sum(exp["ead"] for exp in irb_exposures_h3)

    total_rwa_h3 = sa_rwa_h3 + irb_rwa_h3
    total_ead_h3 = sa_ead_h3 + irb_ead_h3

    result_h3 = ScenarioResult(
        scenario_id="H3",
        scenario_group="H",
        description="Mixed approach portfolio",
        exposure_reference="PORTFOLIO_MIXED",
        counterparty_reference="PORTFOLIO",
        approach="MIXED",
        exposure_class="PORTFOLIO",
        ead=total_ead_h3,
        risk_weight=total_rwa_h3 / total_ead_h3,
        rwa=total_rwa_h3,
        calculation_details={
            "sa_exposures": sa_exposures_h3,
            "sa_total_ead": sa_ead_h3,
            "sa_total_rwa": sa_rwa_h3,
            "irb_exposures": irb_exposures_h3,
            "irb_total_ead": irb_ead_h3,
            "irb_total_rwa": irb_rwa_h3,
            "approach_separation": True,
        },
        regulatory_reference="CRR Art 150",
    )

    print(f"H3: Mixed portfolio")
    print(f"    SA: EAD=£{sa_ead_h3:,.0f}, RWA=£{sa_rwa_h3:,.0f}")
    print(f"    IRB: EAD=£{irb_ead_h3:,.0f}, RWA=£{irb_rwa_h3:,.0f}")
    print(f"    Total RWA=£{total_rwa_h3:,.0f}")
    return (
        result_h3,
        sa_exposures_h3,
        irb_exposures_h3,
        sa_rwa_h3,
        sa_ead_h3,
        irb_rwa_h3,
        irb_ead_h3,
        total_rwa_h3,
        total_ead_h3,
    )


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Scenario H4: Full CRM Chain

    **Input:** £30m exposure with collateral + guarantee + provision
    **Expected:** Apply all CRM in correct order
    """)
    return


@app.cell
def _(
    get_corporate_risk_weight,
    calculate_sa_rwa,
    calculate_adjusted_collateral_value,
    calculate_guarantee_substitution,
    ScenarioResult,
):
    # H4: Full CRM chain
    # Exposure: £30m corporate loan
    # Collateral: £10m CRE
    # Guarantee: £15m bank guarantee
    # Provision: £1m specific

    ead_gross_h4 = 30_000_000.0
    collateral_h4 = 10_000_000.0
    guarantee_h4 = 15_000_000.0
    provision_h4 = 1_000_000.0

    # Step 1: Deduct provision (SCRA)
    ead_after_prov_h4 = ead_gross_h4 - provision_h4  # 29m

    # Step 2: Apply collateral
    coll_result_h4 = calculate_adjusted_collateral_value(
        collateral_market_value=collateral_h4,
        collateral_type="commercial_re",
        issuer_type="corporate",
        residual_maturity_years=5.0,
        exposure_maturity_years=5.0,
    )
    ead_after_coll_h4 = max(ead_after_prov_h4 - coll_result_h4["adjusted_value"], 0)

    # Step 3: Apply guarantee (substitution approach)
    rw_underlying_h4 = get_corporate_risk_weight(0)  # 100%
    rw_guarantor_h4 = get_corporate_risk_weight(1)  # 20% (bank CQS1)

    # Guarantee applies to remaining exposure after collateral
    guar_result_h4 = calculate_guarantee_substitution(
        exposure_amount=ead_after_coll_h4,
        exposure_risk_weight=rw_underlying_h4,
        guarantee_amount=guarantee_h4,
        guarantor_risk_weight=rw_guarantor_h4,
    )

    rwa_h4 = guar_result_h4["total_rwa"]

    result_h4 = ScenarioResult(
        scenario_id="H4",
        scenario_group="H",
        description="Full CRM chain",
        exposure_reference="LOAN_FAC_CORP_002_A",
        counterparty_reference="CORP_UK_002",
        approach="SA",
        exposure_class="CORPORATE",
        ead=ead_after_coll_h4,
        risk_weight=rwa_h4 / ead_after_coll_h4 if ead_after_coll_h4 > 0 else 0,
        rwa=rwa_h4,
        calculation_details={
            "ead_gross": ead_gross_h4,
            "step_1_provision": provision_h4,
            "ead_after_provision": ead_after_prov_h4,
            "step_2_collateral": coll_result_h4,
            "ead_after_collateral": ead_after_coll_h4,
            "step_3_guarantee": guar_result_h4,
            "final_rwa": rwa_h4,
            "crm_order": ["provision", "collateral", "guarantee"],
        },
        regulatory_reference="CRE22",
    )

    print(f"H4: Full CRM chain")
    print(f"    Gross EAD: £{ead_gross_h4:,.0f}")
    print(f"    After provision (£{provision_h4:,.0f}): £{ead_after_prov_h4:,.0f}")
    print(
        f"    After collateral (adj £{coll_result_h4['adjusted_value']:,.0f}): £{ead_after_coll_h4:,.0f}"
    )
    print(
        f"    Guarantee coverage: £{guar_result_h4['covered_amount']:,.0f} at {rw_guarantor_h4 * 100:.0f}%"
    )
    print(f"    Final RWA: £{rwa_h4:,.0f}")
    return (
        result_h4,
        ead_gross_h4,
        collateral_h4,
        guarantee_h4,
        provision_h4,
        ead_after_prov_h4,
        coll_result_h4,
        ead_after_coll_h4,
        rw_underlying_h4,
        rw_guarantor_h4,
        guar_result_h4,
        rwa_h4,
    )


@app.cell
def _(mo):
    mo.md("---\n## Summary: Group H Results")
    return


@app.cell
def _(result_h1, result_h2, result_h3, result_h4, pl, mo):
    group_h_results = [result_h1, result_h2, result_h3, result_h4]

    summary_data_h = [
        {
            "Scenario": r.scenario_id,
            "Description": r.description,
            "EAD (£)": f"{r.ead:,.0f}",
            "RWA (£)": f"{r.rwa:,.0f}",
        }
        for r in group_h_results
    ]

    mo.ui.table(pl.DataFrame(summary_data_h))
    return group_h_results, summary_data_h


@app.cell
def _(group_h_results):
    def get_group_h_results():
        return group_h_results

    return (get_group_h_results,)


if __name__ == "__main__":
    app.run()
