"""
FX Rate Configuration for EUR/GBP Conversion.

Provides a configurable EUR/GBP exchange rate and conversion functions
for use across the RWA calculator.

Note: Regulatory thresholds (CRR EUR source values and Basel 3.1 GBP values)
are consolidated in ``rwa_calc.contracts.config.RegulatoryThresholds``.

Usage:
    from rwa_calc.config import EUR_GBP_RATE, eur_to_gbp

    rate = EUR_GBP_RATE  # e.g., 0.8732
    gbp_amount = eur_to_gbp(Decimal("1000000"))

To update the rate:
    Modify EUR_GBP_RATE in this file.
"""

from __future__ import annotations

from decimal import Decimal

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
