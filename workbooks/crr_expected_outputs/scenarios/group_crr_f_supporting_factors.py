"""
CRR Group F: Supporting Factors Scenarios.

Demonstrates the CRR-specific supporting factors:
- SME supporting factor (CRR2 Art. 501) - Tiered approach
- Infrastructure supporting factor (CRR Art. 501a)

These factors are NOT available under Basel 3.1.

SME Supporting Factor - Tiered Structure:
- Exposures up to €2.5m (~£2.18m): factor of 0.7619 (23.81% reduction)
- Exposures above €2.5m (~£2.18m): factor of 0.85 (15% reduction)

Formula: factor = [min(E, threshold) × 0.7619 + max(E - threshold, 0) × 0.85] / E

References:
- CRR2 Art. 501 (EU 2019/876)
- CRR Art. 501a
"""

from dataclasses import dataclass
from decimal import Decimal
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from workbooks.crr_expected_outputs.calculations.crr_supporting_factors import (
    calculate_sme_supporting_factor,
    apply_sme_supporting_factor,
    apply_infrastructure_supporting_factor,
    is_sme_eligible,
)
from workbooks.crr_expected_outputs.data.crr_params import (
    CRR_SME_EXPOSURE_THRESHOLD_GBP,
    CRR_SME_SUPPORTING_FACTOR_TIER1,
    CRR_SME_SUPPORTING_FACTOR_TIER2,
    CRR_INFRASTRUCTURE_SUPPORTING_FACTOR,
)


@dataclass
class CRRSupportingFactorResult:
    """Result of a supporting factor calculation."""
    scenario_id: str
    scenario_group: str
    description: str
    regulatory_framework: str
    approach: str
    exposure_class: str
    exposure_reference: str
    counterparty_reference: str
    ead: float
    turnover: float | None
    risk_weight: float
    rwa_before_sf: float
    supporting_factor: float
    rwa_after_sf: float
    regulatory_reference: str
    calculation_notes: str


def generate_crr_f_scenarios() -> list[CRRSupportingFactorResult]:
    """
    Generate CRR-F supporting factor scenarios.

    Scenarios cover:
    - F1: SME Tier 1 only (small exposure ≤ threshold)
    - F2: SME Tier 2 blended (medium exposure £4m)
    - F3: SME Tier 2 dominant (large exposure £10m)
    - F4: SME retail with tiered factor
    - F5: Infrastructure supporting factor
    - F6: Large corporate - no SME factor
    - F7: At exposure threshold boundary
    """
    results = []

    # =========================================================================
    # CRR-F1: SME Tier 1 Only (Small Exposure)
    # =========================================================================
    # Exposure £2m (below threshold) - gets full 0.7619 factor
    ead_f1 = Decimal("2000000")
    turnover_f1 = Decimal("30000000")  # £30m < £44m threshold
    rw_f1 = Decimal("1.00")  # 100% unrated corporate
    rwa_before_f1 = ead_f1 * rw_f1

    factor_f1 = calculate_sme_supporting_factor(ead_f1, "GBP")
    rwa_after_f1 = rwa_before_f1 * factor_f1

    results.append(CRRSupportingFactorResult(
        scenario_id="CRR-F1",
        scenario_group="CRR-F",
        description=f"SME Tier 1 only - small exposure (£2m ≤ £{CRR_SME_EXPOSURE_THRESHOLD_GBP/1000000:.2f}m threshold)",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CORPORATE_SME",
        exposure_reference="LOAN_SME_TIER1",
        counterparty_reference="CORP_SME_SMALL",
        ead=float(ead_f1),
        turnover=float(turnover_f1),
        risk_weight=float(rw_f1),
        rwa_before_sf=float(rwa_before_f1),
        supporting_factor=float(factor_f1),
        rwa_after_sf=float(rwa_after_f1),
        regulatory_reference="CRR2 Art. 501",
        calculation_notes=f"Tier 1 only: exposure £2m ≤ £{CRR_SME_EXPOSURE_THRESHOLD_GBP/1000000:.2f}m threshold. Factor = {float(factor_f1):.4f}",
    ))

    # =========================================================================
    # CRR-F2: SME Blended (Medium Exposure)
    # =========================================================================
    # Exposure £4m (above threshold) - blended factor
    ead_f2 = Decimal("4000000")
    turnover_f2 = Decimal("25000000")  # £25m < £44m threshold
    rw_f2 = Decimal("1.00")
    rwa_before_f2 = ead_f2 * rw_f2

    factor_f2 = calculate_sme_supporting_factor(ead_f2, "GBP")
    rwa_after_f2 = rwa_before_f2 * factor_f2

    # Manual calculation for verification (threshold from FX rate):
    threshold_gbp = CRR_SME_EXPOSURE_THRESHOLD_GBP
    tier1_f2 = threshold_gbp * CRR_SME_SUPPORTING_FACTOR_TIER1
    tier2_f2 = (ead_f2 - threshold_gbp) * CRR_SME_SUPPORTING_FACTOR_TIER2
    # Factor: (tier1 + tier2) / ead

    results.append(CRRSupportingFactorResult(
        scenario_id="CRR-F2",
        scenario_group="CRR-F",
        description="SME blended tiers - medium exposure (£4m)",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CORPORATE_SME",
        exposure_reference="LOAN_SME_TIER_BLEND",
        counterparty_reference="CORP_SME_MEDIUM",
        ead=float(ead_f2),
        turnover=float(turnover_f2),
        risk_weight=float(rw_f2),
        rwa_before_sf=float(rwa_before_f2),
        supporting_factor=float(factor_f2),
        rwa_after_sf=float(rwa_after_f2),
        regulatory_reference="CRR2 Art. 501",
        calculation_notes=(
            f"Blended: £{threshold_gbp/1000000:.2f}m @ 0.7619 + £{(ead_f2-threshold_gbp)/1000000:.2f}m @ 0.85. "
            f"Effective factor = {float(factor_f2):.4f}"
        ),
    ))

    # =========================================================================
    # CRR-F3: SME Tier 2 Dominant (Large Exposure)
    # =========================================================================
    # Exposure £10m - Tier 2 is dominant
    ead_f3 = Decimal("10000000")
    turnover_f3 = Decimal("35000000")  # £35m < £44m threshold
    rw_f3 = Decimal("1.00")
    rwa_before_f3 = ead_f3 * rw_f3

    factor_f3 = calculate_sme_supporting_factor(ead_f3, "GBP")
    rwa_after_f3 = rwa_before_f3 * factor_f3

    # Manual calculation (threshold from FX rate):
    tier1_f3 = threshold_gbp * CRR_SME_SUPPORTING_FACTOR_TIER1
    tier2_amount_f3 = ead_f3 - threshold_gbp
    tier2_f3 = tier2_amount_f3 * CRR_SME_SUPPORTING_FACTOR_TIER2
    # Factor: (tier1 + tier2) / ead

    results.append(CRRSupportingFactorResult(
        scenario_id="CRR-F3",
        scenario_group="CRR-F",
        description="SME Tier 2 dominant - large exposure (£10m)",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CORPORATE_SME",
        exposure_reference="LOAN_SME_TIER2_DOM",
        counterparty_reference="CORP_SME_LARGE",
        ead=float(ead_f3),
        turnover=float(turnover_f3),
        risk_weight=float(rw_f3),
        rwa_before_sf=float(rwa_before_f3),
        supporting_factor=float(factor_f3),
        rwa_after_sf=float(rwa_after_f3),
        regulatory_reference="CRR2 Art. 501",
        calculation_notes=(
            f"Tier 2 dominant: £{threshold_gbp/1000000:.2f}m @ 0.7619 + £{tier2_amount_f3/1000000:.2f}m @ 0.85. "
            f"Effective factor = {float(factor_f3):.4f}"
        ),
    ))

    # =========================================================================
    # CRR-F4: SME Retail with Tiered Factor
    # =========================================================================
    # Retail SME exposure - 75% RW + tiered SME factor
    ead_f4 = Decimal("500000")  # Below threshold - pure Tier 1
    turnover_f4 = Decimal("5000000")  # £5m < £44m threshold
    rw_f4 = Decimal("0.75")  # Retail RW
    rwa_before_f4 = ead_f4 * rw_f4

    factor_f4 = calculate_sme_supporting_factor(ead_f4, "GBP")
    rwa_after_f4 = rwa_before_f4 * factor_f4

    results.append(CRRSupportingFactorResult(
        scenario_id="CRR-F4",
        scenario_group="CRR-F",
        description="SME retail with Tier 1 factor (£500k)",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="RETAIL_SME",
        exposure_reference="LOAN_RTL_SME_TIER1",
        counterparty_reference="RTL_SME_SMALL",
        ead=float(ead_f4),
        turnover=float(turnover_f4),
        risk_weight=float(rw_f4),
        rwa_before_sf=float(rwa_before_f4),
        supporting_factor=float(factor_f4),
        rwa_after_sf=float(rwa_after_f4),
        regulatory_reference="CRR Art. 123 + Art. 501",
        calculation_notes=(
            f"Retail 75% RW + Tier 1 SME factor. "
            f"Effective RW = 75% × {float(factor_f4):.4f} = {float(rw_f4 * factor_f4) * 100:.2f}%"
        ),
    ))

    # =========================================================================
    # CRR-F5: Infrastructure Supporting Factor
    # =========================================================================
    # Infrastructure project - fixed 0.75 factor (not tiered)
    ead_f5 = Decimal("50000000")  # £50m infrastructure project
    rw_f5 = Decimal("1.00")
    rwa_before_f5 = ead_f5 * rw_f5

    factor_f5 = CRR_INFRASTRUCTURE_SUPPORTING_FACTOR
    rwa_after_f5 = rwa_before_f5 * factor_f5

    results.append(CRRSupportingFactorResult(
        scenario_id="CRR-F5",
        scenario_group="CRR-F",
        description="Infrastructure supporting factor (0.75)",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_INFRA_001",
        counterparty_reference="CORP_INFRA_001",
        ead=float(ead_f5),
        turnover=None,
        risk_weight=float(rw_f5),
        rwa_before_sf=float(rwa_before_f5),
        supporting_factor=float(factor_f5),
        rwa_after_sf=float(rwa_after_f5),
        regulatory_reference="CRR Art. 501a",
        calculation_notes="Infrastructure factor 0.75 (not tiered). NOT available under Basel 3.1.",
    ))

    # =========================================================================
    # CRR-F6: Large Corporate - No Factor
    # =========================================================================
    # Large corporate (turnover > threshold) - no SME factor
    ead_f6 = Decimal("20000000")
    turnover_f6 = Decimal("200000000")  # £200m > £44m threshold
    rw_f6 = Decimal("1.00")
    rwa_before_f6 = ead_f6 * rw_f6

    # No factor applies - turnover exceeds threshold
    factor_f6 = Decimal("1.0")
    rwa_after_f6 = rwa_before_f6 * factor_f6

    results.append(CRRSupportingFactorResult(
        scenario_id="CRR-F6",
        scenario_group="CRR-F",
        description="Large corporate - no SME factor (turnover > £44m)",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CORPORATE",
        exposure_reference="LOAN_CORP_LARGE",
        counterparty_reference="CORP_LARGE_001",
        ead=float(ead_f6),
        turnover=float(turnover_f6),
        risk_weight=float(rw_f6),
        rwa_before_sf=float(rwa_before_f6),
        supporting_factor=float(factor_f6),
        rwa_after_sf=float(rwa_after_f6),
        regulatory_reference="CRR Art. 501",
        calculation_notes="Turnover £200m exceeds £44m threshold. No SME factor applies.",
    ))

    # =========================================================================
    # CRR-F7: At Exposure Threshold Boundary
    # =========================================================================
    # Exposure exactly at threshold
    ead_f7 = CRR_SME_EXPOSURE_THRESHOLD_GBP  # Use actual threshold value
    turnover_f7 = Decimal("20000000")  # £20m < £44m threshold
    rw_f7 = Decimal("1.00")
    rwa_before_f7 = ead_f7 * rw_f7

    factor_f7 = calculate_sme_supporting_factor(ead_f7, "GBP")
    rwa_after_f7 = rwa_before_f7 * factor_f7

    results.append(CRRSupportingFactorResult(
        scenario_id="CRR-F7",
        scenario_group="CRR-F",
        description=f"At exposure threshold boundary (£{ead_f7/1000000:.2f}m exactly)",
        regulatory_framework="CRR",
        approach="SA",
        exposure_class="CORPORATE_SME",
        exposure_reference="LOAN_SME_BOUNDARY",
        counterparty_reference="CORP_SME_BOUNDARY",
        ead=float(ead_f7),
        turnover=float(turnover_f7),
        risk_weight=float(rw_f7),
        rwa_before_sf=float(rwa_before_f7),
        supporting_factor=float(factor_f7),
        rwa_after_sf=float(rwa_after_f7),
        regulatory_reference="CRR2 Art. 501",
        calculation_notes=(
            f"At threshold: £{ead_f7/1000000:.2f}m exactly = Tier 1 only. "
            f"Factor = {float(factor_f7):.4f}"
        ),
    ))

    return results


if __name__ == "__main__":
    # Generate and display scenarios
    scenarios = generate_crr_f_scenarios()

    print("=" * 80)
    print("CRR-F Supporting Factor Scenarios")
    print("=" * 80)

    for s in scenarios:
        print(f"\n{s.scenario_id}: {s.description}")
        print(f"  EAD: £{s.ead:,.0f}")
        if s.turnover:
            print(f"  Turnover: £{s.turnover:,.0f}")
        print(f"  Risk Weight: {s.risk_weight * 100:.0f}%")
        print(f"  RWA before SF: £{s.rwa_before_sf:,.0f}")
        print(f"  Supporting Factor: {s.supporting_factor:.4f}")
        print(f"  RWA after SF: £{s.rwa_after_sf:,.0f}")
        print(f"  Reduction: £{s.rwa_before_sf - s.rwa_after_sf:,.0f}")
        print(f"  Notes: {s.calculation_notes}")
