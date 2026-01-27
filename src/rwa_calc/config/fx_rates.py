"""
FX Rate Configuration for CRR Regulatory Thresholds.

CRR (EU 575/2013) specifies various thresholds in EUR. For UK implementation,
these need to be converted to GBP. This module provides:
- A configurable EUR/GBP exchange rate
- Conversion functions
- Canonical EUR thresholds from CRR regulation
- Functions to derive GBP equivalents

The EUR amounts are the regulatory source of truth. GBP equivalents are
calculated at runtime using the configured rate.

Note: Basel 3.1 (UK implementation via PRA PS9/24) specifies thresholds
directly in GBP, so this conversion is not needed for Basel 3.1 calculations.

Usage:
    from src.rwa_calc.config import EUR_GBP_RATE, get_crr_threshold_gbp

    # Get current rate
    rate = EUR_GBP_RATE  # e.g., 0.88

    # Get GBP equivalent of a threshold
    sme_threshold_gbp = get_crr_threshold_gbp("sme_exposure")

    # Convert arbitrary amounts
    gbp_amount = eur_to_gbp(Decimal("1000000"))

To update the rate:
    Modify EUR_GBP_RATE in this file. All dependent GBP thresholds will
    automatically reflect the new rate.
"""

from decimal import Decimal
from typing import Literal


# =============================================================================
# CONFIGURABLE FX RATE
# =============================================================================

# EUR to GBP exchange rate
# This rate should be periodically reviewed and updated.
# Rate represents: 1 EUR = X GBP
# Example: 0.88 means 1 EUR = 0.88 GBP
EUR_GBP_RATE: Decimal = Decimal("0.8732")


# =============================================================================
# CONVERSION FUNCTIONS
# =============================================================================

def eur_to_gbp(eur_amount: Decimal) -> Decimal:
    """
    Convert EUR amount to GBP using the configured rate.

    Args:
        eur_amount: Amount in EUR

    Returns:
        Equivalent amount in GBP

    Example:
        >>> eur_to_gbp(Decimal("1000000"))
        Decimal('880000')  # with rate of 0.88
    """
    return eur_amount * EUR_GBP_RATE


def gbp_to_eur(gbp_amount: Decimal) -> Decimal:
    """
    Convert GBP amount to EUR using the configured rate.

    Args:
        gbp_amount: Amount in GBP

    Returns:
        Equivalent amount in EUR

    Example:
        >>> gbp_to_eur(Decimal("880000"))
        Decimal('1000000')  # with rate of 0.88
    """
    return gbp_amount / EUR_GBP_RATE


# =============================================================================
# CANONICAL EUR THRESHOLDS (CRR Regulatory Values)
# =============================================================================

# These are the official EUR amounts from CRR regulation.
# Do not modify these - they are regulatory constants.

ThresholdKey = Literal[
    "sme_exposure",
    "sme_turnover",
]

CRR_REGULATORY_THRESHOLDS_EUR: dict[ThresholdKey, Decimal] = {
    # SME exposure threshold for tiered supporting factor (CRR2 Art. 501)
    # Exposures up to this amount get 0.7619 factor
    # Exposures above get 0.85 factor
    "sme_exposure": Decimal("2500000"),  # EUR 2.5m

    # SME turnover threshold for eligibility (CRR Art. 501)
    # Counterparties with turnover below this qualify as SME
    "sme_turnover": Decimal("50000000"),  # EUR 50m
}


# =============================================================================
# DERIVED GBP THRESHOLDS
# =============================================================================

def get_crr_threshold_gbp(threshold_key: ThresholdKey) -> Decimal:
    """
    Get the GBP equivalent of a CRR regulatory threshold.

    The EUR amount is the canonical regulatory value. This function
    converts it to GBP using the current EUR_GBP_RATE.

    Args:
        threshold_key: Key identifying the threshold
            - "sme_exposure": EUR 2.5m threshold for tiered SME factor
            - "sme_turnover": EUR 50m threshold for SME eligibility

    Returns:
        GBP equivalent of the threshold

    Example:
        >>> get_crr_threshold_gbp("sme_exposure")
        Decimal('2200000')  # with rate of 0.88
    """
    eur_amount = CRR_REGULATORY_THRESHOLDS_EUR[threshold_key]
    return eur_to_gbp(eur_amount)


def get_all_crr_thresholds_gbp() -> dict[ThresholdKey, Decimal]:
    """
    Get all CRR thresholds converted to GBP.

    Returns:
        Dictionary of threshold keys to GBP amounts
    """
    return {
        key: eur_to_gbp(eur_amount)
        for key, eur_amount in CRR_REGULATORY_THRESHOLDS_EUR.items()
    }
