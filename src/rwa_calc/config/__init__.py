"""Configuration module for RWA calculator."""

from .fx_rates import (
    CRR_REGULATORY_THRESHOLDS_EUR,
    EUR_GBP_RATE,
    eur_to_gbp,
    gbp_to_eur,
    get_crr_threshold_gbp,
)

__all__ = [
    "EUR_GBP_RATE",
    "eur_to_gbp",
    "gbp_to_eur",
    "CRR_REGULATORY_THRESHOLDS_EUR",
    "get_crr_threshold_gbp",
]
