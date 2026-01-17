"""
CRR Supporting Factors (CRR2 Art. 501).

Implements SME and infrastructure supporting factors unique to CRR.
These factors are NOT available under Basel 3.1.

SME Supporting Factor - Tiered Approach (CRR2 Art. 501):
- Exposures up to €2.5m (£2.2m): factor of 0.7619 (23.81% RWA reduction)
- Exposures above €2.5m (£2.2m): factor of 0.85 (15% RWA reduction)

The effective factor is calculated as:
    SME_factor = [min(E, threshold) × 0.7619 + max(E - threshold, 0) × 0.85] / E

This means smaller SME exposures get more capital relief than larger ones.

References:
- CRR2 Art. 501 (EU 2019/876 amending EU 575/2013)
- CRR Art. 501a: Infrastructure supporting factor
"""

from decimal import Decimal
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from workbooks.crr_expected_outputs.data.crr_params import (
    CRR_SME_SUPPORTING_FACTOR,
    CRR_SME_SUPPORTING_FACTOR_TIER1,
    CRR_SME_SUPPORTING_FACTOR_TIER2,
    CRR_SME_EXPOSURE_THRESHOLD_EUR,
    CRR_SME_EXPOSURE_THRESHOLD_GBP,
    CRR_INFRASTRUCTURE_SUPPORTING_FACTOR,
    CRR_SME_TURNOVER_THRESHOLD_EUR,
    CRR_SME_TURNOVER_THRESHOLD_GBP,
)


def is_sme_eligible(
    turnover: Decimal | None,
    currency: str = "GBP"
) -> bool:
    """
    Check if counterparty qualifies as SME for supporting factor.

    Args:
        turnover: Annual turnover
        currency: Currency of turnover figure

    Returns:
        True if SME eligible (turnover < threshold)

    Threshold:
    - EUR 50m (standard)
    - GBP 44m (UK approximation)
    """
    if turnover is None:
        return False

    if currency.upper() in ("GBP", "£"):
        return turnover < CRR_SME_TURNOVER_THRESHOLD_GBP
    else:
        return turnover < CRR_SME_TURNOVER_THRESHOLD_EUR


def calculate_sme_supporting_factor(
    total_exposure: Decimal,
    currency: str = "GBP"
) -> Decimal:
    """
    Calculate the effective SME supporting factor based on total exposure.

    The SME supporting factor uses a tiered structure (CRR2 Art. 501):
    - Exposures up to €2.5m (£2.2m): factor of 0.7619
    - Exposures above €2.5m (£2.2m): factor of 0.85

    Formula:
        factor = [min(E, threshold) × 0.7619 + max(E - threshold, 0) × 0.85] / E

    Args:
        total_exposure: Total exposure amount to the SME
        currency: Currency of exposure (GBP or EUR)

    Returns:
        Effective supporting factor (between 0.7619 and 0.85)

    Examples:
        - €1m exposure: factor = 0.7619
        - €2.5m exposure: factor = 0.7619
        - €4m exposure: factor = (2.5m × 0.7619 + 1.5m × 0.85) / 4m = 0.7952
        - €10m exposure: factor = (2.5m × 0.7619 + 7.5m × 0.85) / 10m = 0.8280
    """
    if total_exposure <= 0:
        return Decimal("1.0")

    # Get threshold based on currency
    if currency.upper() in ("GBP", "£"):
        threshold = CRR_SME_EXPOSURE_THRESHOLD_GBP
    else:
        threshold = CRR_SME_EXPOSURE_THRESHOLD_EUR

    # Calculate tiered factor
    tier1_amount = min(total_exposure, threshold)
    tier2_amount = max(total_exposure - threshold, Decimal("0"))

    weighted_factor = (
        tier1_amount * CRR_SME_SUPPORTING_FACTOR_TIER1 +
        tier2_amount * CRR_SME_SUPPORTING_FACTOR_TIER2
    )

    effective_factor = weighted_factor / total_exposure

    return effective_factor


def apply_sme_supporting_factor(
    rwa: Decimal,
    total_exposure: Decimal,
    is_sme: bool,
    turnover: Decimal | None = None,
    currency: str = "GBP"
) -> tuple[Decimal, Decimal, bool, str]:
    """
    Apply SME supporting factor (CRR2 Art. 501).

    Uses tiered approach based on total exposure amount:
    - Up to €2.5m (£2.2m): factor of 0.7619
    - Above €2.5m (£2.2m): factor of 0.85

    Args:
        rwa: RWA before factor
        total_exposure: Total exposure to the SME (for tiered calculation)
        is_sme: Whether counterparty is known to be SME
        turnover: Annual turnover (for eligibility check)
        currency: Currency of exposure/turnover

    Returns:
        Tuple of (adjusted_rwa, factor_applied, was_applied, description)

    Note: This factor is NOT available under Basel 3.1
    """
    # Check eligibility
    eligible = is_sme or (turnover is not None and is_sme_eligible(turnover, currency))

    if not eligible:
        return rwa, Decimal("1.0"), False, "SME factor not applied (not eligible)"

    # Calculate tiered factor
    factor = calculate_sme_supporting_factor(total_exposure, currency)
    adjusted_rwa = rwa * factor
    reduction = rwa - adjusted_rwa

    # Get threshold for description
    if currency.upper() in ("GBP", "£"):
        threshold = CRR_SME_EXPOSURE_THRESHOLD_GBP
        threshold_str = f"£{threshold/1000000:.1f}m"
    else:
        threshold = CRR_SME_EXPOSURE_THRESHOLD_EUR
        threshold_str = f"€{threshold/1000000:.1f}m"

    # Build description
    if total_exposure <= threshold:
        desc = f"SME factor applied: {factor:.4f} (Tier 1 only - exposure ≤ {threshold_str})"
    else:
        tier1_pct = (threshold / total_exposure) * 100
        tier2_pct = 100 - float(tier1_pct)
        desc = (
            f"SME factor applied: {factor:.4f} "
            f"(Tier 1: {tier1_pct:.1f}% @ 0.7619, Tier 2: {tier2_pct:.1f}% @ 0.85). "
            f"RWA reduced by {reduction:,.0f}"
        )

    return adjusted_rwa, factor, True, desc


def apply_sme_supporting_factor_simple(
    rwa: Decimal,
    is_sme: bool,
    turnover: Decimal | None = None,
    currency: str = "GBP"
) -> tuple[Decimal, bool, str]:
    """
    Apply SME supporting factor using simple 0.7619 factor.

    This is the legacy approach that applies the base factor to all eligible
    SME exposures. Use apply_sme_supporting_factor() for the full tiered
    calculation per CRR2 Art. 501.

    Args:
        rwa: RWA before factor
        is_sme: Whether counterparty is known to be SME
        turnover: Annual turnover (for eligibility check)
        currency: Currency of turnover

    Returns:
        Tuple of (adjusted_rwa, factor_applied, description)

    Note: This factor is NOT available under Basel 3.1
    """
    # Check eligibility
    eligible = is_sme or (turnover is not None and is_sme_eligible(turnover, currency))

    if not eligible:
        return rwa, False, "SME factor not applied (not eligible)"

    adjusted_rwa = rwa * CRR_SME_SUPPORTING_FACTOR
    reduction = rwa - adjusted_rwa

    return (
        adjusted_rwa,
        True,
        f"SME factor applied: {CRR_SME_SUPPORTING_FACTOR} (RWA reduced by {reduction:,.0f})"
    )


def apply_infrastructure_supporting_factor(
    rwa: Decimal,
    is_qualifying_infrastructure: bool
) -> tuple[Decimal, bool, str]:
    """
    Apply infrastructure supporting factor (CRR Art. 501a).

    Args:
        rwa: RWA before factor
        is_qualifying_infrastructure: Whether exposure qualifies

    Returns:
        Tuple of (adjusted_rwa, factor_applied, description)

    Factor: 0.75 (reduces RWA by 25%)

    Note: This factor is NOT available under Basel 3.1

    Qualifying criteria include:
    - Exposure to entity operating infrastructure project
    - Cash flows generated can cover financial obligations
    - Project finance structure with appropriate covenants
    """
    if not is_qualifying_infrastructure:
        return rwa, False, "Infrastructure factor not applied (not qualifying)"

    adjusted_rwa = rwa * CRR_INFRASTRUCTURE_SUPPORTING_FACTOR
    reduction = rwa - adjusted_rwa

    return (
        adjusted_rwa,
        True,
        f"Infrastructure factor applied: {CRR_INFRASTRUCTURE_SUPPORTING_FACTOR} (RWA reduced by {reduction:,.0f})"
    )


def get_effective_supporting_factor(
    total_exposure: Decimal,
    is_sme: bool,
    is_infrastructure: bool,
    turnover: Decimal | None = None,
    currency: str = "GBP"
) -> Decimal:
    """
    Get the effective supporting factor for an exposure.

    Considers both SME and infrastructure factors, applying the most
    beneficial one.

    Args:
        total_exposure: Total exposure amount (for SME tier calculation)
        is_sme: Whether SME eligible
        is_infrastructure: Whether infrastructure eligible
        turnover: Annual turnover
        currency: Currency

    Returns:
        Applicable supporting factor (lowest = most beneficial)
    """
    sme_eligible = is_sme or (turnover is not None and is_sme_eligible(turnover, currency))

    factors = [Decimal("1.0")]

    if is_infrastructure:
        factors.append(CRR_INFRASTRUCTURE_SUPPORTING_FACTOR)

    if sme_eligible:
        sme_factor = calculate_sme_supporting_factor(total_exposure, currency)
        factors.append(sme_factor)

    # Return the lowest factor (most beneficial)
    return min(factors)


def get_combined_supporting_factor(
    is_sme: bool,
    is_infrastructure: bool,
    turnover: Decimal | None = None,
    currency: str = "GBP"
) -> Decimal:
    """
    Get combined supporting factor (legacy - does not consider exposure size).

    Note: For tiered SME calculation, use get_effective_supporting_factor() instead.

    Args:
        is_sme: Whether SME eligible
        is_infrastructure: Whether infrastructure eligible
        turnover: Annual turnover
        currency: Currency

    Returns:
        Applicable supporting factor
    """
    sme_eligible = is_sme or (turnover is not None and is_sme_eligible(turnover, currency))

    if is_infrastructure:
        return CRR_INFRASTRUCTURE_SUPPORTING_FACTOR
    elif sme_eligible:
        return CRR_SME_SUPPORTING_FACTOR
    else:
        return Decimal("1.0")
