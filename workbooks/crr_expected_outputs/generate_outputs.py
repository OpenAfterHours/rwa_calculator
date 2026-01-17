"""
CRR Expected Outputs Generator

Generates expected RWA output files for CRR scenarios.
Outputs are saved to tests/expected_outputs/crr/

Usage:
    uv run python workbooks/crr_expected_outputs/generate_outputs.py
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from dataclasses import dataclass, asdict
from typing import Any

import polars as pl

# Add project root to path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from workbooks.shared.fixture_loader import load_fixtures
from workbooks.crr_expected_outputs.calculations.crr_risk_weights import (
    get_sovereign_rw,
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
from workbooks.crr_expected_outputs.calculations.crr_irb import (
    apply_pd_floor,
    get_firb_lgd,
    calculate_irb_rwa,
    calculate_irb_rwa_with_turnover,
)
from workbooks.shared.correlation import calculate_correlation
from workbooks.shared.irb_formulas import (
    calculate_irb_rwa as base_calculate_irb_rwa,
    calculate_expected_loss,
    apply_pd_floor as base_apply_pd_floor,
)
from workbooks.crr_expected_outputs.calculations.crr_haircuts import (
    get_collateral_haircut,
    get_fx_haircut,
    calculate_adjusted_collateral_value,
    apply_maturity_mismatch,
)
from workbooks.crr_expected_outputs.data.crr_params import (
    CRR_SME_SUPPORTING_FACTOR,
    CRR_PD_FLOOR,
    CRR_SLOTTING_RW,
)


@dataclass
class CRRScenarioOutput:
    """Expected output for a CRR scenario."""
    scenario_id: str
    scenario_group: str
    description: str
    regulatory_framework: str
    approach: str
    exposure_class: str
    exposure_reference: str
    counterparty_reference: str
    # Inputs
    ead: float
    pd: float | None
    lgd: float | None
    maturity: float | None
    cqs: int | None
    ltv: float | None
    turnover: float | None
    # Outputs
    risk_weight: float
    rwa_before_sf: float
    supporting_factor: float
    rwa_after_sf: float
    expected_loss: float | None
    # Metadata
    regulatory_reference: str
    calculation_notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decimal_to_float(obj):
    """JSON encoder for Decimal types."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def generate_crr_a_scenarios(fixtures) -> list[CRRScenarioOutput]:
    """Generate CRR Group A (SA) scenario outputs."""
    scenarios = []

    # CRR-A1: UK Sovereign - 0% RW
    loan_a1 = fixtures.get_loan("LOAN_SOV_UK_001")
    cpty_a1 = fixtures.get_counterparty("SOV_UK_001")
    rating_a1 = fixtures.get_rating("SOV_UK_001")
    cqs_a1 = rating_a1["cqs"] if rating_a1 else 1
    ead_a1 = Decimal(str(loan_a1["drawn_amount"]))
    rw_a1 = get_sovereign_rw(cqs_a1)
    rwa_a1 = calculate_sa_rwa(ead_a1, rw_a1)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-A1",
        scenario_group="CRR-A",
        description="UK Sovereign exposure - 0% RW",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="SOVEREIGN",
        exposure_reference="LOAN_SOV_UK_001",
        counterparty_reference="SOV_UK_001",
        ead=float(ead_a1),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=cqs_a1,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_a1),
        rwa_before_sf=float(rwa_a1),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a1),
        expected_loss=None,
        regulatory_reference="CRR Art. 114",
        calculation_notes=f"CQS {cqs_a1} -> 0% RW per Art. 114",
    ))

    # CRR-A2: Unrated Corporate - 100% RW
    loan_a2 = fixtures.get_loan("LOAN_CORP_UR_001")
    cpty_a2 = fixtures.get_counterparty("CORP_UR_001")
    ead_a2 = Decimal(str(loan_a2["drawn_amount"]))
    rw_a2 = get_corporate_rw(None)  # Unrated
    rwa_a2 = calculate_sa_rwa(ead_a2, rw_a2)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-A2",
        scenario_group="CRR-A",
        description="Unrated corporate - 100% RW",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_CORP_UR_001",
        counterparty_reference="CORP_UR_001",
        ead=float(ead_a2),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_a2),
        rwa_before_sf=float(rwa_a2),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a2),
        expected_loss=None,
        regulatory_reference="CRR Art. 122",
        calculation_notes="Unrated corporate -> 100% RW per Art. 122",
    ))

    # CRR-A3: Rated Corporate CQS 2 - 50% RW
    loan_a3 = fixtures.get_loan("LOAN_CORP_UK_003")
    rating_a3 = fixtures.get_rating("CORP_UK_003")
    cqs_a3 = rating_a3["cqs"] if rating_a3 else 2
    ead_a3 = Decimal(str(loan_a3["drawn_amount"]))
    rw_a3 = get_corporate_rw(cqs_a3)
    rwa_a3 = calculate_sa_rwa(ead_a3, rw_a3)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-A3",
        scenario_group="CRR-A",
        description="Rated corporate CQS 2 - 50% RW",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_CORP_UK_003",
        counterparty_reference="CORP_UK_003",
        ead=float(ead_a3),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=cqs_a3,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_a3),
        rwa_before_sf=float(rwa_a3),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a3),
        expected_loss=None,
        regulatory_reference="CRR Art. 122",
        calculation_notes=f"CQS {cqs_a3} -> 50% RW per Art. 122",
    ))

    # CRR-A4: UK Institution CQS 2 - 30% RW (UK Deviation)
    loan_a4 = fixtures.get_loan("LOAN_INST_UK_003")
    rating_a4 = fixtures.get_rating("INST_UK_003")
    cqs_a4 = rating_a4["cqs"] if rating_a4 else 2
    ead_a4 = Decimal(str(loan_a4["drawn_amount"]))
    rw_a4 = get_institution_rw(cqs_a4, country="GB", use_uk_deviation=True)
    rwa_a4 = calculate_sa_rwa(ead_a4, rw_a4)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-A4",
        scenario_group="CRR-A",
        description="UK Institution CQS 2 - 30% RW (UK deviation)",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="INSTITUTION",
        exposure_reference="LOAN_INST_UK_003",
        counterparty_reference="INST_UK_003",
        ead=float(ead_a4),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=cqs_a4,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_a4),
        rwa_before_sf=float(rwa_a4),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a4),
        expected_loss=None,
        regulatory_reference="CRR Art. 120-121 (UK deviation)",
        calculation_notes="UK deviation: CQS 2 -> 30% RW (standard Basel is 50%)",
    ))

    # CRR-A5: Residential Mortgage 60% LTV - 35% RW
    loan_a5 = fixtures.get_loan("LOAN_RTL_MTG_001")
    ead_a5 = Decimal(str(loan_a5["drawn_amount"]))
    ltv_a5 = Decimal("0.60")  # Assume 60% LTV
    rw_a5, rw_desc_a5 = get_residential_mortgage_rw(ltv_a5)
    rwa_a5 = calculate_sa_rwa(ead_a5, rw_a5)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-A5",
        scenario_group="CRR-A",
        description="Residential mortgage 60% LTV - 35% RW",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="RETAIL_MORTGAGE",
        exposure_reference="LOAN_RTL_MTG_001",
        counterparty_reference="RTL_MTG_001",
        ead=float(ead_a5),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=float(ltv_a5),
        turnover=None,
        risk_weight=float(rw_a5),
        rwa_before_sf=float(rwa_a5),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a5),
        expected_loss=None,
        regulatory_reference="CRR Art. 125",
        calculation_notes=f"{rw_desc_a5}. CRR uses 35%/75% split at 80% LTV.",
    ))

    # CRR-A6: Residential Mortgage 85% LTV - Split Treatment
    loan_a6 = fixtures.get_loan("LOAN_RTL_MTG_002")
    ead_a6 = Decimal(str(loan_a6["drawn_amount"]))
    ltv_a6 = Decimal("0.85")
    rw_a6, rw_desc_a6 = get_residential_mortgage_rw(ltv_a6)
    rwa_a6 = calculate_sa_rwa(ead_a6, rw_a6)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-A6",
        scenario_group="CRR-A",
        description="Residential mortgage 85% LTV - split treatment",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="RETAIL_MORTGAGE",
        exposure_reference="LOAN_RTL_MTG_002",
        counterparty_reference="RTL_MTG_002",
        ead=float(ead_a6),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=float(ltv_a6),
        turnover=None,
        risk_weight=float(rw_a6),
        rwa_before_sf=float(rwa_a6),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a6),
        expected_loss=None,
        regulatory_reference="CRR Art. 125",
        calculation_notes=f"{rw_desc_a6}. 35% on portion up to 80% LTV, 75% on excess.",
    ))

    # CRR-A7: Commercial RE 40% LTV - 50% RW
    ead_a7 = Decimal("400000")
    ltv_a7 = Decimal("0.40")
    rw_a7, rw_desc_a7 = get_commercial_re_rw(ltv_a7, has_income_cover=True)
    rwa_a7 = calculate_sa_rwa(ead_a7, rw_a7)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-A7",
        scenario_group="CRR-A",
        description="Commercial RE 40% LTV - 50% RW",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CRE",
        exposure_reference="LOAN_CRE_001",
        counterparty_reference="CORP_CRE_001",
        ead=float(ead_a7),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=float(ltv_a7),
        turnover=None,
        risk_weight=float(rw_a7),
        rwa_before_sf=float(rwa_a7),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a7),
        expected_loss=None,
        regulatory_reference="CRR Art. 126",
        calculation_notes=f"{rw_desc_a7}",
    ))

    # CRR-A8: Off-Balance Sheet - 50% CCF
    nominal_a8 = Decimal("1000000")
    ead_a8, ccf_a8, ead_desc_a8 = calculate_ead_off_balance_sheet(
        nominal_amount=nominal_a8,
        commitment_type="undrawn_long_term",
        original_maturity_years=2.0,
    )
    rw_a8 = get_corporate_rw(None)
    rwa_a8 = calculate_sa_rwa(ead_a8, rw_a8)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-A8",
        scenario_group="CRR-A",
        description="Off-balance sheet commitment - 50% CCF",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CORPORATE",
        exposure_reference="CONT_CCF_001",
        counterparty_reference="CORP_OBS_001",
        ead=float(ead_a8),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_a8),
        rwa_before_sf=float(rwa_a8),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a8),
        expected_loss=None,
        regulatory_reference="CRR Art. 111",
        calculation_notes=f"Nominal £{nominal_a8:,.0f} × {ccf_a8:.0%} CCF = £{ead_a8:,.0f} EAD",
    ))

    # CRR-A9: Retail - 75% RW
    loan_a9 = fixtures.get_loan("LOAN_RTL_IND_001")
    ead_a9 = Decimal(str(loan_a9["drawn_amount"]))
    rw_a9 = get_retail_rw()
    rwa_a9 = calculate_sa_rwa(ead_a9, rw_a9)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-A9",
        scenario_group="CRR-A",
        description="Retail exposure - 75% RW",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="RETAIL",
        exposure_reference="LOAN_RTL_IND_001",
        counterparty_reference="RTL_IND_001",
        ead=float(ead_a9),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_a9),
        rwa_before_sf=float(rwa_a9),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a9),
        expected_loss=None,
        regulatory_reference="CRR Art. 123",
        calculation_notes="Retail -> 75% RW per Art. 123",
    ))

    # CRR-A10: SME Corporate with Supporting Factor
    loan_a10 = fixtures.get_loan("LOAN_CORP_SME_001")
    ead_a10 = Decimal(str(loan_a10["drawn_amount"]))
    turnover_a10 = Decimal("30000000")  # £30m
    rw_a10 = get_corporate_rw(None)
    rwa_before_sf_a10 = calculate_sa_rwa(ead_a10, rw_a10)
    rwa_after_sf_a10, sf_applied_a10, sf_desc_a10 = apply_sme_supporting_factor(
        rwa=rwa_before_sf_a10,
        is_sme=True,
        turnover=turnover_a10,
        currency="GBP",
    )
    sf_a10 = Decimal("0.7619") if sf_applied_a10 else Decimal("1.0")

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-A10",
        scenario_group="CRR-A",
        description="SME corporate with supporting factor",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CORPORATE_SME",
        exposure_reference="LOAN_CORP_SME_001",
        counterparty_reference="CORP_SME_001",
        ead=float(ead_a10),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=float(turnover_a10),
        risk_weight=float(rw_a10),
        rwa_before_sf=float(rwa_before_sf_a10),
        supporting_factor=float(sf_a10),
        rwa_after_sf=float(rwa_after_sf_a10),
        expected_loss=None,
        regulatory_reference="CRR Art. 122 + Art. 501",
        calculation_notes=f"{sf_desc_a10}. NOT available under Basel 3.1.",
    ))

    # CRR-A11: SME Retail with Supporting Factor
    loan_a11 = fixtures.get_loan("LOAN_RTL_SME_001")
    ead_a11 = Decimal(str(loan_a11["drawn_amount"]))
    turnover_a11 = Decimal("750000")
    rw_a11 = get_retail_rw()
    rwa_before_sf_a11 = calculate_sa_rwa(ead_a11, rw_a11)
    rwa_after_sf_a11, sf_applied_a11, sf_desc_a11 = apply_sme_supporting_factor(
        rwa=rwa_before_sf_a11,
        is_sme=True,
        turnover=turnover_a11,
        currency="GBP",
    )
    sf_a11 = Decimal("0.7619") if sf_applied_a11 else Decimal("1.0")

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-A11",
        scenario_group="CRR-A",
        description="SME retail with supporting factor",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="RETAIL_SME",
        exposure_reference="LOAN_RTL_SME_001",
        counterparty_reference="RTL_SME_001",
        ead=float(ead_a11),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=float(turnover_a11),
        risk_weight=float(rw_a11),
        rwa_before_sf=float(rwa_before_sf_a11),
        supporting_factor=float(sf_a11),
        rwa_after_sf=float(rwa_after_sf_a11),
        expected_loss=None,
        regulatory_reference="CRR Art. 123 + Art. 501",
        calculation_notes=f"{sf_desc_a11}. NOT available under Basel 3.1.",
    ))

    # CRR-A12: Large Corporate - No Factor
    loan_a12 = fixtures.get_loan("LOAN_CORP_UK_001")
    ead_a12 = Decimal(str(loan_a12["drawn_amount"]))
    turnover_a12 = Decimal("500000000")  # £500m
    rw_a12 = get_corporate_rw(None)
    rwa_a12 = calculate_sa_rwa(ead_a12, rw_a12)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-A12",
        scenario_group="CRR-A",
        description="Large corporate (no supporting factor)",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_CORP_UK_001",
        counterparty_reference="CORP_UK_001",
        ead=float(ead_a12),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=float(turnover_a12),
        risk_weight=float(rw_a12),
        rwa_before_sf=float(rwa_a12),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_a12),
        expected_loss=None,
        regulatory_reference="CRR Art. 122",
        calculation_notes="Turnover > £44m threshold, SME factor not applicable.",
    ))

    return scenarios


def generate_crr_b_scenarios(fixtures) -> list[CRRScenarioOutput]:
    """Generate CRR Group B (F-IRB) scenario outputs."""
    scenarios = []

    # CRR-B1: Corporate F-IRB - Low PD
    loan_b1 = fixtures.get_loan("LOAN_CORP_UK_001")
    ead_b1 = float(loan_b1["drawn_amount"])
    pd_raw_b1 = 0.001  # 0.10%
    pd_floored_b1 = apply_pd_floor(pd_raw_b1)
    lgd_b1 = float(get_firb_lgd("unsecured"))
    maturity_b1 = 2.5
    correlation_b1 = calculate_correlation(pd_floored_b1, "CORPORATE")

    result_b1 = calculate_irb_rwa(
        ead=ead_b1,
        pd=pd_raw_b1,
        lgd=lgd_b1,
        correlation=correlation_b1,
        maturity=maturity_b1,
        exposure_class="CORPORATE",
    )

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-B1",
        scenario_group="CRR-B",
        description="Corporate F-IRB - low PD",
        regulatory_framework="CRR",
        approach="F-IRB",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_CORP_UK_001",
        counterparty_reference="CORP_UK_001",
        ead=ead_b1,
        pd=pd_floored_b1,
        lgd=lgd_b1,
        maturity=maturity_b1,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=result_b1["rwa"] / ead_b1 if ead_b1 > 0 else 0,
        rwa_before_sf=result_b1["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_b1["rwa"],
        expected_loss=pd_floored_b1 * lgd_b1 * ead_b1,
        regulatory_reference="CRR Art. 153, 161, 162, 163",
        calculation_notes=f"PD {pd_raw_b1:.2%}, LGD {lgd_b1:.0%} (supervisory), K={result_b1['k']:.4f}",
    ))

    # CRR-B2: Corporate F-IRB - High PD
    ead_b2 = 5_000_000.0
    pd_raw_b2 = 0.05  # 5.00%
    pd_floored_b2 = apply_pd_floor(pd_raw_b2)
    lgd_b2 = float(get_firb_lgd("unsecured"))
    maturity_b2 = 3.0
    correlation_b2 = calculate_correlation(pd_floored_b2, "CORPORATE")

    result_b2 = calculate_irb_rwa(
        ead=ead_b2,
        pd=pd_raw_b2,
        lgd=lgd_b2,
        correlation=correlation_b2,
        maturity=maturity_b2,
        exposure_class="CORPORATE",
    )

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-B2",
        scenario_group="CRR-B",
        description="Corporate F-IRB - high PD",
        regulatory_framework="CRR",
        approach="F-IRB",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_CORP_UK_002",
        counterparty_reference="CORP_UK_002",
        ead=ead_b2,
        pd=pd_floored_b2,
        lgd=lgd_b2,
        maturity=maturity_b2,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=result_b2["rwa"] / ead_b2 if ead_b2 > 0 else 0,
        rwa_before_sf=result_b2["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_b2["rwa"],
        expected_loss=pd_floored_b2 * lgd_b2 * ead_b2,
        regulatory_reference="CRR Art. 153, 161, 162",
        calculation_notes=f"High PD {pd_raw_b2:.2%} -> lower correlation {correlation_b2:.3f}",
    ))

    # CRR-B3: Subordinated - 75% LGD
    ead_b3 = 2_000_000.0
    pd_b3 = 0.01
    lgd_b3 = float(get_firb_lgd("unsecured", is_subordinated=True))  # 75%
    maturity_b3 = 4.0
    correlation_b3 = calculate_correlation(pd_b3, "CORPORATE")

    result_b3 = calculate_irb_rwa(
        ead=ead_b3,
        pd=pd_b3,
        lgd=lgd_b3,
        correlation=correlation_b3,
        maturity=maturity_b3,
        exposure_class="CORPORATE",
    )

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-B3",
        scenario_group="CRR-B",
        description="Subordinated exposure - 75% LGD",
        regulatory_framework="CRR",
        approach="F-IRB",
        exposure_class="CORPORATE_SUBORDINATED",
        exposure_reference="LOAN_SUB_001",
        counterparty_reference="CORP_SUB_001",
        ead=ead_b3,
        pd=pd_b3,
        lgd=lgd_b3,
        maturity=maturity_b3,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=result_b3["rwa"] / ead_b3 if ead_b3 > 0 else 0,
        rwa_before_sf=result_b3["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_b3["rwa"],
        expected_loss=pd_b3 * lgd_b3 * ead_b3,
        regulatory_reference="CRR Art. 153, 161",
        calculation_notes=f"Subordinated: LGD {lgd_b3:.0%} (vs 45% senior)",
    ))

    # CRR-B4: SME Corporate F-IRB - Firm Size Adjustment
    # Demonstrates the SME correlation adjustment (CRR Art. 153(4))
    ead_b4 = 3_000_000.0
    pd_raw_b4 = 0.015  # 1.50%
    lgd_b4 = float(get_firb_lgd("unsecured"))  # 45%
    maturity_b4 = 2.5
    turnover_b4 = 25.0  # EUR 25m - qualifies for firm size adjustment

    # Use new function with turnover for SME adjustment
    result_b4 = calculate_irb_rwa_with_turnover(
        ead=ead_b4,
        pd=pd_raw_b4,
        lgd=lgd_b4,
        maturity=maturity_b4,
        exposure_class="CORPORATE",
        turnover_m=turnover_b4,
    )

    # Also calculate without SME adjustment for comparison
    correlation_no_sme = calculate_correlation(result_b4["pd_floored"], "CORPORATE")
    correlation_with_sme = result_b4["correlation"]

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-B4",
        scenario_group="CRR-B",
        description="SME Corporate F-IRB - firm size adjustment",
        regulatory_framework="CRR",
        approach="F-IRB",
        exposure_class="CORPORATE_SME",
        exposure_reference="LOAN_CORP_SME_002",
        counterparty_reference="CORP_SME_002",
        ead=ead_b4,
        pd=result_b4["pd_floored"],
        lgd=lgd_b4,
        maturity=maturity_b4,
        cqs=None,
        ltv=None,
        turnover=turnover_b4 * 1_000_000,  # Convert to actual EUR value
        risk_weight=result_b4["rwa"] / ead_b4 if ead_b4 > 0 else 0,
        rwa_before_sf=result_b4["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_b4["rwa"],
        expected_loss=result_b4["pd_floored"] * lgd_b4 * ead_b4,
        regulatory_reference="CRR Art. 153(4), 161, 162",
        calculation_notes=(
            f"SME firm size adjustment: R={correlation_with_sme:.4f} "
            f"(vs {correlation_no_sme:.4f} without). "
            f"Turnover EUR {turnover_b4}m < EUR 50m threshold."
        ),
    ))

    # CRR-B5: SME Corporate F-IRB with both adjustments
    # Demonstrates BOTH firm size adjustment AND SME supporting factor
    ead_b5 = 2_000_000.0
    pd_raw_b5 = 0.02  # 2.00%
    lgd_b5 = float(get_firb_lgd("unsecured"))  # 45%
    maturity_b5 = 3.0
    turnover_b5 = 15.0  # EUR 15m - qualifies for both adjustments

    result_b5 = calculate_irb_rwa_with_turnover(
        ead=ead_b5,
        pd=pd_raw_b5,
        lgd=lgd_b5,
        maturity=maturity_b5,
        exposure_class="CORPORATE",
        turnover_m=turnover_b5,
    )

    # Apply SME supporting factor to the RWA
    sf_b5 = float(CRR_SME_SUPPORTING_FACTOR)
    rwa_after_sf_b5 = result_b5["rwa"] * sf_b5

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-B5",
        scenario_group="CRR-B",
        description="SME Corporate F-IRB - both adjustments",
        regulatory_framework="CRR",
        approach="F-IRB",
        exposure_class="CORPORATE_SME",
        exposure_reference="LOAN_CORP_SME_003",
        counterparty_reference="CORP_SME_003",
        ead=ead_b5,
        pd=result_b5["pd_floored"],
        lgd=lgd_b5,
        maturity=maturity_b5,
        cqs=None,
        ltv=None,
        turnover=turnover_b5 * 1_000_000,  # Convert to actual EUR value
        risk_weight=result_b5["rwa"] / ead_b5 if ead_b5 > 0 else 0,
        rwa_before_sf=result_b5["rwa"],
        supporting_factor=sf_b5,
        rwa_after_sf=rwa_after_sf_b5,
        expected_loss=result_b5["pd_floored"] * lgd_b5 * ead_b5,
        regulatory_reference="CRR Art. 153(4), 161, 162, 501",
        calculation_notes=(
            f"SME with both adjustments: "
            f"(1) Firm size R={result_b5['correlation']:.4f}, "
            f"(2) Supporting factor {sf_b5:.4f}. "
            f"RWA reduced from {result_b5['rwa']:,.0f} to {rwa_after_sf_b5:,.0f}."
        ),
    ))

    # CRR-B6: Corporate at SME threshold boundary
    # Turnover exactly at EUR 50m - no firm size adjustment but within SME supporting factor
    ead_b6 = 4_000_000.0
    pd_raw_b6 = 0.01  # 1.00%
    lgd_b6 = float(get_firb_lgd("unsecured"))  # 45%
    maturity_b6 = 2.5
    turnover_b6 = 50.0  # EUR 50m - boundary case (no firm size adjustment)

    result_b6 = calculate_irb_rwa_with_turnover(
        ead=ead_b6,
        pd=pd_raw_b6,
        lgd=lgd_b6,
        maturity=maturity_b6,
        exposure_class="CORPORATE",
        turnover_m=turnover_b6,
    )

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-B6",
        scenario_group="CRR-B",
        description="Corporate F-IRB - at SME threshold",
        regulatory_framework="CRR",
        approach="F-IRB",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_CORP_UK_004",
        counterparty_reference="CORP_UK_004",
        ead=ead_b6,
        pd=result_b6["pd_floored"],
        lgd=lgd_b6,
        maturity=maturity_b6,
        cqs=None,
        ltv=None,
        turnover=turnover_b6 * 1_000_000,
        risk_weight=result_b6["rwa"] / ead_b6 if ead_b6 > 0 else 0,
        rwa_before_sf=result_b6["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_b6["rwa"],
        expected_loss=result_b6["pd_floored"] * lgd_b6 * ead_b6,
        regulatory_reference="CRR Art. 153, 161, 162",
        calculation_notes=(
            f"At EUR 50m threshold: no firm size adjustment "
            f"(R={result_b6['correlation']:.4f}, sme_adj={result_b6['sme_adjustment_applied']}). "
            f"Turnover at boundary."
        ),
    ))

    return scenarios


def generate_crr_c_scenarios(fixtures) -> list[CRRScenarioOutput]:
    """Generate CRR Group C (A-IRB) scenario outputs."""
    scenarios = []

    # CRR-C1: Corporate A-IRB - Own LGD Estimate
    ead_c1 = 5_000_000.0
    pd_raw_c1 = 0.01  # 1.00%
    lgd_internal_c1 = 0.35  # Bank's own estimate (35% < 45% F-IRB)
    maturity_c1 = 2.5
    pd_floored_c1 = apply_pd_floor(pd_raw_c1)
    correlation_c1 = calculate_correlation(pd_floored_c1, "CORPORATE")

    result_c1 = base_calculate_irb_rwa(
        ead=ead_c1,
        pd=pd_raw_c1,
        lgd=lgd_internal_c1,
        correlation=correlation_c1,
        maturity=maturity_c1,
        pd_floor=float(CRR_PD_FLOOR),
        lgd_floor=None,  # CRR A-IRB has NO LGD floor
        apply_maturity_adjustment=True,
        is_retail=False,
        apply_scaling_factor=True,
    )

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-C1",
        scenario_group="CRR-C",
        description="Corporate A-IRB - own LGD estimate (35%)",
        regulatory_framework="CRR",
        approach="A-IRB",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_CORP_AIRB_001",
        counterparty_reference="CORP_AIRB_001",
        ead=ead_c1,
        pd=pd_floored_c1,
        lgd=lgd_internal_c1,
        maturity=maturity_c1,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=result_c1["rwa"] / ead_c1 if ead_c1 > 0 else 0,
        rwa_before_sf=result_c1["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_c1["rwa"],
        expected_loss=calculate_expected_loss(pd_floored_c1, lgd_internal_c1, ead_c1),
        regulatory_reference="CRR Art. 143, 153",
        calculation_notes="CRR A-IRB: No LGD floor. Internal LGD 35% vs F-IRB 45%.",
    ))

    # CRR-C2: Retail A-IRB - Own Estimates
    ead_c2 = 100_000.0
    pd_raw_c2 = 0.003  # 0.30%
    lgd_internal_c2 = 0.15  # Bank's own estimate (15%)
    pd_floored_c2 = apply_pd_floor(pd_raw_c2)
    correlation_c2 = calculate_correlation(pd_floored_c2, "RETAIL")

    result_c2 = base_calculate_irb_rwa(
        ead=ead_c2,
        pd=pd_raw_c2,
        lgd=lgd_internal_c2,
        correlation=correlation_c2,
        maturity=2.5,
        pd_floor=float(CRR_PD_FLOOR),
        lgd_floor=None,
        apply_maturity_adjustment=False,  # No MA for retail
        is_retail=True,
        apply_scaling_factor=True,
    )

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-C2",
        scenario_group="CRR-C",
        description="Retail A-IRB - own estimates (PD 0.3%, LGD 15%)",
        regulatory_framework="CRR",
        approach="A-IRB",
        exposure_class="RETAIL",
        exposure_reference="LOAN_RTL_AIRB_001",
        counterparty_reference="RTL_AIRB_001",
        ead=ead_c2,
        pd=pd_floored_c2,
        lgd=lgd_internal_c2,
        maturity=None,  # No maturity for retail
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=result_c2["rwa"] / ead_c2 if ead_c2 > 0 else 0,
        rwa_before_sf=result_c2["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_c2["rwa"],
        expected_loss=calculate_expected_loss(pd_floored_c2, lgd_internal_c2, ead_c2),
        regulatory_reference="CRR Art. 154",
        calculation_notes="Retail must use A-IRB. No maturity adjustment. No LGD floor.",
    ))

    # CRR-C3: Specialised Lending A-IRB (Project Finance)
    ead_c3 = 10_000_000.0
    pd_raw_c3 = 0.015  # 1.50%
    lgd_internal_c3 = 0.25  # Bank's own estimate (25%)
    maturity_c3 = 4.0
    pd_floored_c3 = apply_pd_floor(pd_raw_c3)
    correlation_c3 = calculate_correlation(pd_floored_c3, "CORPORATE")

    result_c3 = base_calculate_irb_rwa(
        ead=ead_c3,
        pd=pd_raw_c3,
        lgd=lgd_internal_c3,
        correlation=correlation_c3,
        maturity=maturity_c3,
        pd_floor=float(CRR_PD_FLOOR),
        lgd_floor=None,
        apply_maturity_adjustment=True,
        is_retail=False,
        apply_scaling_factor=True,
    )

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-C3",
        scenario_group="CRR-C",
        description="Specialised lending A-IRB - project finance",
        regulatory_framework="CRR",
        approach="A-IRB",
        exposure_class="SPECIALISED_LENDING",
        exposure_reference="LOAN_SL_AIRB_001",
        counterparty_reference="SL_PF_001",
        ead=ead_c3,
        pd=pd_floored_c3,
        lgd=lgd_internal_c3,
        maturity=maturity_c3,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=result_c3["rwa"] / ead_c3 if ead_c3 > 0 else 0,
        rwa_before_sf=result_c3["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_c3["rwa"],
        expected_loss=calculate_expected_loss(pd_floored_c3, lgd_internal_c3, ead_c3),
        regulatory_reference="CRR Art. 153",
        calculation_notes="Project finance with A-IRB approval. Alternative: slotting.",
    ))

    return scenarios


def generate_crr_d_scenarios(fixtures) -> list[CRRScenarioOutput]:
    """Generate CRR Group D (CRM) scenario outputs."""
    scenarios = []

    # CRR-D1: Cash Collateral
    exposure_d1 = Decimal("1000000")
    coll_value_d1 = Decimal("500000")
    rw_d1 = get_corporate_rw(None)  # 100%
    coll_haircut_d1 = get_collateral_haircut("cash")  # 0%
    coll_adjusted_d1 = calculate_adjusted_collateral_value(coll_value_d1, coll_haircut_d1, Decimal("0.00"))
    ead_post_d1 = exposure_d1 - coll_adjusted_d1
    rwa_post_d1 = calculate_sa_rwa(ead_post_d1, rw_d1)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-D1",
        scenario_group="CRR-D",
        description="Cash collateral - 0% haircut",
        regulatory_framework="CRR",
        approach="SA-CRM",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_CRM_D1",
        counterparty_reference="CORP_CRM_D1",
        ead=float(ead_post_d1),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_d1),
        rwa_before_sf=float(rwa_post_d1),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_post_d1),
        expected_loss=None,
        regulatory_reference="CRR Art. 207, 224",
        calculation_notes=f"Cash 0% haircut. EAD reduced from £{exposure_d1:,.0f} to £{ead_post_d1:,.0f}",
    ))

    # CRR-D2: Government Bond Collateral
    exposure_d2 = Decimal("1000000")
    coll_value_d2 = Decimal("600000")
    coll_haircut_d2 = get_collateral_haircut("govt_bond", cqs=1, residual_maturity_years=6.0)  # 4%
    coll_adjusted_d2 = calculate_adjusted_collateral_value(coll_value_d2, coll_haircut_d2, Decimal("0.00"))
    ead_post_d2 = exposure_d2 - coll_adjusted_d2
    rwa_post_d2 = calculate_sa_rwa(ead_post_d2, rw_d1)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-D2",
        scenario_group="CRR-D",
        description="Government bond collateral - 4% haircut",
        regulatory_framework="CRR",
        approach="SA-CRM",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_CRM_D2",
        counterparty_reference="CORP_CRM_D2",
        ead=float(ead_post_d2),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_d1),
        rwa_before_sf=float(rwa_post_d2),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_post_d2),
        expected_loss=None,
        regulatory_reference="CRR Art. 224",
        calculation_notes=f"CQS 1 govt bond >5y: {coll_haircut_d2*100:.1f}% haircut",
    ))

    # CRR-D3: Equity Collateral (Main Index)
    exposure_d3 = Decimal("1000000")
    coll_value_d3 = Decimal("400000")
    coll_haircut_d3 = get_collateral_haircut("equity", is_main_index=True)  # 15%
    coll_adjusted_d3 = calculate_adjusted_collateral_value(coll_value_d3, coll_haircut_d3, Decimal("0.00"))
    ead_post_d3 = exposure_d3 - coll_adjusted_d3
    rwa_post_d3 = calculate_sa_rwa(ead_post_d3, rw_d1)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-D3",
        scenario_group="CRR-D",
        description="Equity collateral (main index) - 15% haircut",
        regulatory_framework="CRR",
        approach="SA-CRM",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_CRM_D3",
        counterparty_reference="CORP_CRM_D3",
        ead=float(ead_post_d3),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_d1),
        rwa_before_sf=float(rwa_post_d3),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_post_d3),
        expected_loss=None,
        regulatory_reference="CRR Art. 224",
        calculation_notes="Main index equity: 15% haircut (other equity: 25%)",
    ))

    # CRR-D4: Guarantee Substitution
    exposure_d4 = Decimal("1000000")
    guarantee_d4 = Decimal("600000")
    rw_guarantor_d4 = get_institution_rw(cqs=2, country="GB", use_uk_deviation=True)  # 30%
    rw_borrower_d4 = get_corporate_rw(None)  # 100%
    non_guaranteed_d4 = exposure_d4 - guarantee_d4
    rwa_post_d4 = calculate_sa_rwa(guarantee_d4, rw_guarantor_d4) + calculate_sa_rwa(non_guaranteed_d4, rw_borrower_d4)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-D4",
        scenario_group="CRR-D",
        description="Bank guarantee - substitution approach",
        regulatory_framework="CRR",
        approach="SA-CRM",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_CRM_D4",
        counterparty_reference="CORP_CRM_D4",
        ead=float(exposure_d4),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rwa_post_d4 / exposure_d4),
        rwa_before_sf=float(rwa_post_d4),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_post_d4),
        expected_loss=None,
        regulatory_reference="CRR Art. 213-217",
        calculation_notes=f"Guarantor 30% RW, Borrower 100% RW. Split treatment.",
    ))

    # CRR-D5: Maturity Mismatch
    exposure_d5 = Decimal("1000000")
    coll_value_d5 = Decimal("500000")
    coll_maturity_d5 = 2.0
    exposure_maturity_d5 = 5.0
    coll_adjusted_d5, mm_desc_d5 = apply_maturity_mismatch(coll_value_d5, coll_maturity_d5, exposure_maturity_d5)
    ead_post_d5 = exposure_d5 - coll_adjusted_d5
    rwa_post_d5 = calculate_sa_rwa(ead_post_d5, rw_d1)
    mat_adj_d5 = (coll_maturity_d5 - 0.25) / (exposure_maturity_d5 - 0.25)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-D5",
        scenario_group="CRR-D",
        description="Maturity mismatch - 2y collateral, 5y exposure",
        regulatory_framework="CRR",
        approach="SA-CRM",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_CRM_D5",
        counterparty_reference="CORP_CRM_D5",
        ead=float(ead_post_d5),
        pd=None,
        lgd=None,
        maturity=exposure_maturity_d5,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_d1),
        rwa_before_sf=float(rwa_post_d5),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_post_d5),
        expected_loss=None,
        regulatory_reference="CRR Art. 238",
        calculation_notes=f"Maturity adjustment: {mat_adj_d5:.4f}. {mm_desc_d5}",
    ))

    # CRR-D6: Currency Mismatch
    exposure_d6 = Decimal("1000000")
    coll_value_d6 = Decimal("500000")
    fx_haircut_d6 = get_fx_haircut("GBP", "EUR")  # 8%
    coll_adjusted_d6 = calculate_adjusted_collateral_value(coll_value_d6, Decimal("0.00"), fx_haircut_d6)
    ead_post_d6 = exposure_d6 - coll_adjusted_d6
    rwa_post_d6 = calculate_sa_rwa(ead_post_d6, rw_d1)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-D6",
        scenario_group="CRR-D",
        description="Currency mismatch - GBP exposure, EUR collateral",
        regulatory_framework="CRR",
        approach="SA-CRM",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_CRM_D6",
        counterparty_reference="CORP_CRM_D6",
        ead=float(ead_post_d6),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_d1),
        rwa_before_sf=float(rwa_post_d6),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_post_d6),
        expected_loss=None,
        regulatory_reference="CRR Art. 224",
        calculation_notes=f"FX mismatch: {fx_haircut_d6*100:.0f}% additional haircut",
    ))

    return scenarios


def generate_crr_e_scenarios(fixtures) -> list[CRRScenarioOutput]:
    """Generate CRR Group E (Slotting) scenario outputs."""
    scenarios = []

    slotting_rw = {
        "strong": Decimal("0.70"),
        "good": Decimal("0.70"),
        "satisfactory": Decimal("1.15"),
        "weak": Decimal("2.50"),
        "default": Decimal("0.00"),
    }

    # CRR-E1: Project Finance - Strong
    ead_e1 = Decimal("10000000")
    rw_e1 = slotting_rw["strong"]
    rwa_e1 = ead_e1 * rw_e1

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-E1",
        scenario_group="CRR-E",
        description="Project finance - Strong (70% RW)",
        regulatory_framework="CRR",
        approach="Slotting",
        exposure_class="SPECIALISED_LENDING",
        exposure_reference="LOAN_SL_PF_001",
        counterparty_reference="SL_PF_STRONG",
        ead=float(ead_e1),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_e1),
        rwa_before_sf=float(rwa_e1),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_e1),
        expected_loss=None,
        regulatory_reference="CRR Art. 153(5)",
        calculation_notes="CRR Strong=Good=70% (Basel 3.1 Strong=50%)",
    ))

    # CRR-E2: Project Finance - Good
    ead_e2 = Decimal("10000000")
    rw_e2 = slotting_rw["good"]
    rwa_e2 = ead_e2 * rw_e2

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-E2",
        scenario_group="CRR-E",
        description="Project finance - Good (70% RW)",
        regulatory_framework="CRR",
        approach="Slotting",
        exposure_class="SPECIALISED_LENDING",
        exposure_reference="LOAN_SL_PF_002",
        counterparty_reference="SL_PF_GOOD",
        ead=float(ead_e2),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_e2),
        rwa_before_sf=float(rwa_e2),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_e2),
        expected_loss=None,
        regulatory_reference="CRR Art. 153(5)",
        calculation_notes="Good category = 70% RW",
    ))

    # CRR-E3: IPRE - Weak
    ead_e3 = Decimal("5000000")
    rw_e3 = slotting_rw["weak"]
    rwa_e3 = ead_e3 * rw_e3

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-E3",
        scenario_group="CRR-E",
        description="IPRE - Weak (250% RW)",
        regulatory_framework="CRR",
        approach="Slotting",
        exposure_class="SPECIALISED_LENDING",
        exposure_reference="LOAN_SL_IPRE_001",
        counterparty_reference="SL_IPRE_WEAK",
        ead=float(ead_e3),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_e3),
        rwa_before_sf=float(rwa_e3),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_e3),
        expected_loss=None,
        regulatory_reference="CRR Art. 153(5)",
        calculation_notes="Weak category = 250% RW (punitive)",
    ))

    # CRR-E4: HVCRE - Strong
    ead_e4 = Decimal("5000000")
    rw_e4 = slotting_rw["strong"]  # Same as non-HVCRE under CRR
    rwa_e4 = ead_e4 * rw_e4

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-E4",
        scenario_group="CRR-E",
        description="HVCRE - Strong (70% RW)",
        regulatory_framework="CRR",
        approach="Slotting",
        exposure_class="SPECIALISED_LENDING_HVCRE",
        exposure_reference="LOAN_SL_HVCRE_001",
        counterparty_reference="SL_HVCRE_STRONG",
        ead=float(ead_e4),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_e4),
        rwa_before_sf=float(rwa_e4),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_e4),
        expected_loss=None,
        regulatory_reference="CRR Art. 153(5)",
        calculation_notes="CRR HVCRE = non-HVCRE weights (Basel 3.1 higher for HVCRE)",
    ))

    return scenarios


def generate_crr_g_scenarios(fixtures) -> list[CRRScenarioOutput]:
    """Generate CRR Group G (Provisions) scenario outputs."""
    scenarios = []

    # CRR-G1: SA with Specific Provision
    gross_exp_g1 = Decimal("1000000")
    provision_g1 = Decimal("50000")
    net_exp_g1 = gross_exp_g1 - provision_g1
    rw_g1 = get_corporate_rw(None)  # 100%
    rwa_g1 = calculate_sa_rwa(net_exp_g1, rw_g1)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-G1",
        scenario_group="CRR-G",
        description="SA with specific provision - net EAD",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_PROV_G1",
        counterparty_reference="CORP_PROV_G1",
        ead=float(net_exp_g1),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_g1),
        rwa_before_sf=float(rwa_g1),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_g1),
        expected_loss=None,
        regulatory_reference="CRR Art. 110",
        calculation_notes=f"EAD = Gross - Provision = £{net_exp_g1:,.0f}",
    ))

    # CRR-G2: IRB EL Shortfall
    ead_g2 = 5_000_000.0
    pd_g2 = 0.02  # 2%
    lgd_g2 = 0.45  # 45%
    total_prov_g2 = 30_000.0
    el_g2 = pd_g2 * lgd_g2 * ead_g2  # = 45,000
    shortfall_g2 = max(el_g2 - total_prov_g2, 0)  # = 15,000
    cet1_deduction_g2 = shortfall_g2 * 0.5

    correlation_g2 = calculate_correlation(pd_g2, "CORPORATE")
    result_g2 = calculate_irb_rwa(
        ead=ead_g2,
        pd=pd_g2,
        lgd=lgd_g2,
        correlation=correlation_g2,
        maturity=2.5,
        exposure_class="CORPORATE",
    )

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-G2",
        scenario_group="CRR-G",
        description="IRB EL shortfall - CET1/T2 deduction",
        regulatory_framework="CRR",
        approach="F-IRB",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_PROV_G2",
        counterparty_reference="CORP_PROV_G2",
        ead=ead_g2,
        pd=pd_g2,
        lgd=lgd_g2,
        maturity=2.5,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=result_g2["rwa"] / ead_g2,
        rwa_before_sf=result_g2["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_g2["rwa"],
        expected_loss=el_g2,
        regulatory_reference="CRR Art. 158, 159",
        calculation_notes=f"EL=£{el_g2:,.0f}, Prov=£{total_prov_g2:,.0f}, Shortfall=£{shortfall_g2:,.0f}. 50% CET1 deduct.",
    ))

    # CRR-G3: IRB EL Excess
    ead_g3 = 5_000_000.0
    pd_g3 = 0.005  # 0.5%
    lgd_g3 = 0.45  # 45%
    total_prov_g3 = 50_000.0
    el_g3 = pd_g3 * lgd_g3 * ead_g3  # = 11,250
    excess_g3 = max(total_prov_g3 - el_g3, 0)  # = 38,750

    correlation_g3 = calculate_correlation(pd_g3, "CORPORATE")
    result_g3 = calculate_irb_rwa(
        ead=ead_g3,
        pd=pd_g3,
        lgd=lgd_g3,
        correlation=correlation_g3,
        maturity=2.5,
        exposure_class="CORPORATE",
    )
    t2_cap_g3 = result_g3["rwa"] * 0.006
    t2_credit_g3 = min(excess_g3, t2_cap_g3)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-G3",
        scenario_group="CRR-G",
        description="IRB EL excess - T2 credit (capped)",
        regulatory_framework="CRR",
        approach="F-IRB",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_PROV_G3",
        counterparty_reference="CORP_PROV_G3",
        ead=ead_g3,
        pd=pd_g3,
        lgd=lgd_g3,
        maturity=2.5,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=result_g3["rwa"] / ead_g3,
        rwa_before_sf=result_g3["rwa"],
        supporting_factor=1.0,
        rwa_after_sf=result_g3["rwa"],
        expected_loss=el_g3,
        regulatory_reference="CRR Art. 62(d)",
        calculation_notes=f"EL=£{el_g3:,.0f}, Prov=£{total_prov_g3:,.0f}, Excess=£{excess_g3:,.0f}. T2 credit (capped)=£{t2_credit_g3:,.0f}",
    ))

    return scenarios


def generate_crr_h_scenarios(fixtures) -> list[CRRScenarioOutput]:
    """Generate CRR Group H (Complex/Combined) scenario outputs."""
    scenarios = []

    # CRR-H1: Facility with Multiple Loans
    rw_h1 = get_corporate_rw(None)  # 100%
    exposures_h1 = [
        ("Term Loan", Decimal("2000000"), Decimal("1.00")),
        ("Trade Finance", Decimal("1500000"), Decimal("1.00")),
        ("Overdraft", Decimal("500000"), Decimal("1.00")),
        ("Undrawn", Decimal("1000000"), Decimal("0.50")),
    ]
    total_ead_h1 = sum(amt * ccf for _, amt, ccf in exposures_h1)
    total_rwa_h1 = total_ead_h1 * rw_h1

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-H1",
        scenario_group="CRR-H",
        description="Facility with multiple loans - hierarchy",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CORPORATE",
        exposure_reference="FAC_MULTI_001",
        counterparty_reference="CORP_FAC_001",
        ead=float(total_ead_h1),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rw_h1),
        rwa_before_sf=float(total_rwa_h1),
        supporting_factor=1.0,
        rwa_after_sf=float(total_rwa_h1),
        expected_loss=None,
        regulatory_reference="CRR Art. 111, 113",
        calculation_notes="Aggregated EAD from 4 sub-exposures including 50% CCF on undrawn",
    ))

    # CRR-H2: Counterparty Group - Rating Inheritance
    members_h2 = [
        ("Parent", Decimal("3000000"), 2),  # CQS 2 = 50%
        ("Sub1", Decimal("1500000"), 2),     # Inherits CQS 2
        ("Sub2", Decimal("500000"), 3),      # Own CQS 3 = 100%
    ]
    total_rwa_h2 = Decimal("0")
    for name, amt, cqs in members_h2:
        rw = get_corporate_rw(cqs)
        total_rwa_h2 += amt * rw
    total_ead_h2 = sum(amt for _, amt, _ in members_h2)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-H2",
        scenario_group="CRR-H",
        description="Counterparty group - rating inheritance",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CORPORATE",
        exposure_reference="GRP_MULTI_001",
        counterparty_reference="CORP_GRP_001",
        ead=float(total_ead_h2),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,  # Mixed
        ltv=None,
        turnover=None,
        risk_weight=float(total_rwa_h2 / total_ead_h2),
        rwa_before_sf=float(total_rwa_h2),
        supporting_factor=1.0,
        rwa_after_sf=float(total_rwa_h2),
        expected_loss=None,
        regulatory_reference="CRR Art. 142",
        calculation_notes="Unrated subsidiary inherits parent CQS 2. Sub2 uses own CQS 3.",
    ))

    # CRR-H3: SME Chain with Supporting Factor
    ead_h3 = Decimal("2000000")
    turnover_h3 = Decimal("25000000")  # £25m
    rw_h3 = get_corporate_rw(None)  # 100%
    rwa_before_sf_h3 = ead_h3 * rw_h3
    rwa_after_sf_h3, sf_applied_h3, _ = apply_sme_supporting_factor(rwa_before_sf_h3, True, turnover_h3, "GBP")
    effective_rw_h3 = rwa_after_sf_h3 / ead_h3

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-H3",
        scenario_group="CRR-H",
        description="SME chain with supporting factor",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CORPORATE_SME",
        exposure_reference="LOAN_SME_CHAIN",
        counterparty_reference="CORP_SME_CHAIN",
        ead=float(ead_h3),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=float(turnover_h3),
        risk_weight=float(rw_h3),
        rwa_before_sf=float(rwa_before_sf_h3),
        supporting_factor=float(CRR_SME_SUPPORTING_FACTOR),
        rwa_after_sf=float(rwa_after_sf_h3),
        expected_loss=None,
        regulatory_reference="CRR Art. 501",
        calculation_notes=f"Effective RW={effective_rw_h3*100:.2f}% after SME factor",
    ))

    # CRR-H4: Full CRM Chain
    gross_h4 = Decimal("2000000")
    provision_h4 = Decimal("100000")
    cash_coll_h4 = Decimal("500000")
    guarantee_h4 = Decimal("400000")

    exp_after_prov_h4 = gross_h4 - provision_h4
    exp_after_cash_h4 = exp_after_prov_h4 - cash_coll_h4

    rw_guarantor_h4 = get_institution_rw(cqs=2, country="GB", use_uk_deviation=True)  # 30%
    rw_borrower_h4 = get_corporate_rw(None)  # 100%

    guaranteed_h4 = min(guarantee_h4, exp_after_cash_h4)
    non_guaranteed_h4 = exp_after_cash_h4 - guaranteed_h4

    rwa_h4 = calculate_sa_rwa(guaranteed_h4, rw_guarantor_h4) + calculate_sa_rwa(non_guaranteed_h4, rw_borrower_h4)
    rwa_pre_crm_h4 = calculate_sa_rwa(gross_h4, rw_borrower_h4)

    scenarios.append(CRRScenarioOutput(
        scenario_id="CRR-H4",
        scenario_group="CRR-H",
        description="Full CRM chain - collateral + guarantee + provision",
        regulatory_framework="CRR",
        approach="SA-CRM",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_CRM_FULL",
        counterparty_reference="CORP_CRM_FULL",
        ead=float(exp_after_cash_h4),
        pd=None,
        lgd=None,
        maturity=None,
        cqs=None,
        ltv=None,
        turnover=None,
        risk_weight=float(rwa_h4 / exp_after_cash_h4) if exp_after_cash_h4 > 0 else 0,
        rwa_before_sf=float(rwa_h4),
        supporting_factor=1.0,
        rwa_after_sf=float(rwa_h4),
        expected_loss=None,
        regulatory_reference="CRR Art. 207-236",
        calculation_notes=f"RWA reduced from £{rwa_pre_crm_h4:,.0f} to £{rwa_h4:,.0f} via CRM chain",
    ))

    return scenarios


def generate_all_outputs():
    """Generate all CRR expected outputs."""
    print("Loading fixtures...")
    fixtures = load_fixtures()

    print("Generating CRR-A (SA) scenarios...")
    crr_a_scenarios = generate_crr_a_scenarios(fixtures)
    print(f"  Generated {len(crr_a_scenarios)} SA scenarios")

    print("Generating CRR-B (F-IRB) scenarios...")
    crr_b_scenarios = generate_crr_b_scenarios(fixtures)
    print(f"  Generated {len(crr_b_scenarios)} F-IRB scenarios")

    print("Generating CRR-C (A-IRB) scenarios...")
    crr_c_scenarios = generate_crr_c_scenarios(fixtures)
    print(f"  Generated {len(crr_c_scenarios)} A-IRB scenarios")

    print("Generating CRR-D (CRM) scenarios...")
    crr_d_scenarios = generate_crr_d_scenarios(fixtures)
    print(f"  Generated {len(crr_d_scenarios)} CRM scenarios")

    print("Generating CRR-E (Slotting) scenarios...")
    crr_e_scenarios = generate_crr_e_scenarios(fixtures)
    print(f"  Generated {len(crr_e_scenarios)} Slotting scenarios")

    print("Generating CRR-G (Provisions) scenarios...")
    crr_g_scenarios = generate_crr_g_scenarios(fixtures)
    print(f"  Generated {len(crr_g_scenarios)} Provision scenarios")

    print("Generating CRR-H (Complex) scenarios...")
    crr_h_scenarios = generate_crr_h_scenarios(fixtures)
    print(f"  Generated {len(crr_h_scenarios)} Complex scenarios")

    all_scenarios = (
        crr_a_scenarios +
        crr_b_scenarios +
        crr_c_scenarios +
        crr_d_scenarios +
        crr_e_scenarios +
        crr_g_scenarios +
        crr_h_scenarios
    )

    # Build output structure
    output = {
        "framework": "CRR",
        "version": "2.0",
        "effective_until": "2026-12-31",
        "generated_at": datetime.now().isoformat(),
        "regulatory_references": {
            "primary": "UK CRR (Regulation (EU) No 575/2013 as retained)",
            "supporting_factors": "CRR Art. 501 (SME), Art. 501a (Infrastructure)",
            "sa_risk_weights": "CRR Art. 112-134",
            "irb_approach": "CRR Art. 142-191",
            "crm": "CRR Art. 207-236",
            "slotting": "CRR Art. 153(5)",
            "provisions": "CRR Art. 110, 158-159, 62(d)",
        },
        "scenario_groups": {
            "CRR-A": {"name": "Standardised Approach", "count": len(crr_a_scenarios)},
            "CRR-B": {"name": "Foundation IRB", "count": len(crr_b_scenarios)},
            "CRR-C": {"name": "Advanced IRB", "count": len(crr_c_scenarios)},
            "CRR-D": {"name": "Credit Risk Mitigation", "count": len(crr_d_scenarios)},
            "CRR-E": {"name": "Specialised Lending (Slotting)", "count": len(crr_e_scenarios)},
            "CRR-G": {"name": "Provisions & Impairments", "count": len(crr_g_scenarios)},
            "CRR-H": {"name": "Complex/Combined", "count": len(crr_h_scenarios)},
        },
        "key_differences_from_basel31": [
            "SME supporting factor (0.7619) available under CRR",
            "Infrastructure supporting factor (0.75) available under CRR",
            "No output floor under CRR",
            "Residential mortgage: 35%/75% split at 80% LTV (vs granular LTV bands)",
            "Single PD floor 0.03% for all classes (vs differentiated floors)",
            "No A-IRB LGD floors under CRR",
            "Slotting: Strong=Good=70% (Basel 3.1 Strong=50%)",
            "HVCRE same weights as non-HVCRE under CRR",
        ],
        "scenario_count": len(all_scenarios),
        "scenarios": [s.to_dict() for s in all_scenarios],
    }

    return output, all_scenarios


def save_outputs(output: dict, scenarios: list[CRRScenarioOutput]):
    """Save outputs to files."""
    output_dir = project_root / "tests" / "expected_outputs" / "crr"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save JSON
    json_path = output_dir / "expected_rwa_crr.json"
    with open(json_path, 'w') as f:
        json.dump(output, f, indent=2, default=decimal_to_float)
    print(f"Saved JSON: {json_path}")

    # Save Parquet using Polars
    df_data = [s.to_dict() for s in scenarios]
    df = pl.DataFrame(df_data)
    parquet_path = output_dir / "expected_rwa_crr.parquet"
    df.write_parquet(parquet_path)
    print(f"Saved Parquet: {parquet_path}")

    # Save CSV for easy viewing
    csv_path = output_dir / "expected_rwa_crr.csv"
    df.write_csv(csv_path)
    print(f"Saved CSV: {csv_path}")

    return json_path, parquet_path, csv_path


def main():
    """Main entry point."""
    print("=" * 60)
    print("CRR Expected Outputs Generator")
    print("=" * 60)

    output, scenarios = generate_all_outputs()

    print("\n" + "-" * 60)
    print("Saving outputs...")
    json_path, parquet_path, csv_path = save_outputs(output, scenarios)

    print("\n" + "=" * 60)
    print("Generation complete!")
    print(f"Total scenarios: {len(scenarios)}")
    print(f"\nOutput files:")
    print(f"  - {json_path}")
    print(f"  - {parquet_path}")
    print(f"  - {csv_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
