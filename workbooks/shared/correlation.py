"""
Asset correlation calculations for IRB approach.

Implements correlation formulas per CRR Art. 153 / CRE31.5 for different
exposure classes. The correlation formula is the same for CRR and Basel 3.1.

This is a shared module used by both CRR and Basel 3.1 workbooks.
"""

import math
from typing import TypedDict


class CorrelationParams(TypedDict):
    """Parameters for asset correlation calculation."""
    type: str           # "fixed" or "pd_dependent"
    r_min: float        # Minimum correlation (at high PD)
    r_max: float        # Maximum correlation (at low PD)
    fixed: float        # Fixed correlation value
    decay_factor: float # K factor in formula (50 for corp, 35 for retail)


# Asset correlation parameters (same for CRR and Basel 3.1)
CORRELATION_PARAMS: dict[str, CorrelationParams] = {
    # Corporate: R = 0.12 * f(PD) + 0.24 * (1 - f(PD))
    # where f(PD) = (1 - e^(-50*PD)) / (1 - e^(-50))
    "CORPORATE": {
        "type": "pd_dependent",
        "r_min": 0.12,
        "r_max": 0.24,
        "fixed": 0.0,
        "decay_factor": 50.0,
    },
    "CORPORATE_SME": {
        "type": "pd_dependent",
        "r_min": 0.12,
        "r_max": 0.24,
        "fixed": 0.0,
        "decay_factor": 50.0,
    },
    "CORPORATES": {  # CRR exposure class name
        "type": "pd_dependent",
        "r_min": 0.12,
        "r_max": 0.24,
        "fixed": 0.0,
        "decay_factor": 50.0,
    },
    "CENTRAL_GOVT_CENTRAL_BANK": {
        "type": "pd_dependent",
        "r_min": 0.12,
        "r_max": 0.24,
        "fixed": 0.0,
        "decay_factor": 50.0,
    },
    "CENTRAL_GOVERNMENTS_CENTRAL_BANKS": {  # CRR exposure class name
        "type": "pd_dependent",
        "r_min": 0.12,
        "r_max": 0.24,
        "fixed": 0.0,
        "decay_factor": 50.0,
    },
    "INSTITUTION": {
        "type": "pd_dependent",
        "r_min": 0.12,
        "r_max": 0.24,
        "fixed": 0.0,
        "decay_factor": 50.0,
    },
    "INSTITUTIONS": {  # CRR exposure class name
        "type": "pd_dependent",
        "r_min": 0.12,
        "r_max": 0.24,
        "fixed": 0.0,
        "decay_factor": 50.0,
    },
    # Retail mortgage: R = 0.15 (fixed)
    "RETAIL_MORTGAGE": {
        "type": "fixed",
        "r_min": 0.15,
        "r_max": 0.15,
        "fixed": 0.15,
        "decay_factor": 0.0,
    },
    "SECURED_BY_REAL_ESTATE": {  # CRR - residential portion
        "type": "fixed",
        "r_min": 0.15,
        "r_max": 0.15,
        "fixed": 0.15,
        "decay_factor": 0.0,
    },
    # QRRE: R = 0.04 (fixed)
    "RETAIL_QRRE": {
        "type": "fixed",
        "r_min": 0.04,
        "r_max": 0.04,
        "fixed": 0.04,
        "decay_factor": 0.0,
    },
    # Other retail: R = 0.03 * f(PD) + 0.16 * (1 - f(PD)), decay factor = 35
    "RETAIL": {
        "type": "pd_dependent",
        "r_min": 0.03,
        "r_max": 0.16,
        "fixed": 0.0,
        "decay_factor": 35.0,
    },
    "RETAIL_SME": {
        "type": "pd_dependent",
        "r_min": 0.03,
        "r_max": 0.16,
        "fixed": 0.0,
        "decay_factor": 35.0,
    },
}


def _pd_weight_factor(pd: float, decay_factor: float) -> float:
    """
    Calculate the PD-dependent weight factor.

    Formula: f(PD) = (1 - e^(-decay_factor * PD)) / (1 - e^(-decay_factor))

    Args:
        pd: Probability of default
        decay_factor: K parameter (50 for corporate, 35 for retail)

    Returns:
        Weight factor between 0 and 1
    """
    if decay_factor <= 0:
        return 0.5  # Default for fixed correlation

    numerator = 1 - math.exp(-decay_factor * pd)
    denominator = 1 - math.exp(-decay_factor)

    return numerator / denominator


def calculate_correlation(
    pd: float,
    exposure_class: str,
    turnover: float | None = None,
    sme_threshold: float = 50.0,
    eur_gbp_rate: float = 0.8732,
    turnover_currency: str = "GBP",
) -> float:
    """
    Calculate asset correlation for IRB formula.

    Args:
        pd: Probability of default
        exposure_class: Exposure class (CORPORATE, RETAIL, etc.)
        turnover: Annual turnover in millions (for SME adjustment)
        sme_threshold: SME turnover threshold in EUR millions (default EUR 50m)
        eur_gbp_rate: EUR/GBP exchange rate for converting GBP turnover to EUR
        turnover_currency: Currency of turnover ("GBP" or "EUR")

    Returns:
        Asset correlation (R)

    Formulas (CRR Art. 153 / CRE31.5):
        Corporate: R = 0.12 * f(PD) + 0.24 * (1 - f(PD))
            where f(PD) = (1 - e^(-50*PD)) / (1 - e^(-50))

        Retail (other): R = 0.03 * f(PD) + 0.16 * (1 - f(PD))
            where f(PD) = (1 - e^(-35*PD)) / (1 - e^(-35))

        Retail mortgage: R = 0.15 (fixed)
        QRRE: R = 0.04 (fixed)

    For SME corporates (turnover < threshold), apply firm size adjustment:
        R_adjusted = R - 0.04 * (1 - (max(S, 5) - 5) / 45)
        where S = annual turnover in EUR millions, capped at threshold
    """
    # Get correlation parameters for exposure class
    params = CORRELATION_PARAMS.get(
        exposure_class,
        CORRELATION_PARAMS.get("CORPORATE")  # Default to corporate
    )

    if params is None:
        # Fallback defaults
        return 0.15

    # Fixed correlation
    if params["type"] == "fixed":
        return params["fixed"]

    # PD-dependent correlation
    r_min = params["r_min"]
    r_max = params["r_max"]
    decay = params["decay_factor"]

    # Calculate weight factor
    f_pd = _pd_weight_factor(pd, decay)

    # R = r_min * f(PD) + r_max * (1 - f(PD))
    correlation = r_min * f_pd + r_max * (1 - f_pd)

    # SME firm size adjustment (CRR Art. 153(4) / CRE31.5)
    if exposure_class in ["CORPORATE", "CORPORATE_SME", "CORPORATES"] and turnover is not None:
        # Convert GBP turnover to EUR for comparison against EUR threshold
        turnover_eur = turnover
        if turnover_currency.upper() == "GBP":
            turnover_eur = turnover / eur_gbp_rate
        correlation = _apply_sme_adjustment(correlation, turnover_eur, sme_threshold)

    return correlation


def _apply_sme_adjustment(
    correlation: float,
    turnover: float,
    sme_threshold: float = 50.0,
) -> float:
    """
    Apply SME firm size adjustment to corporate correlation.

    Args:
        correlation: Base correlation
        turnover: Annual turnover in millions (EUR/GBP)
        sme_threshold: Threshold for SME treatment (default EUR 50m)

    Returns:
        Adjusted correlation

    Formula (CRR Art. 153(4) / CRE31.5):
        R_adjusted = R - 0.04 * (1 - (max(S, 5) - 5) / 45)
        where S = annual turnover capped at threshold

    The adjustment reduces correlation for smaller firms (turnover < threshold)
    """
    SME_FLOOR = 5.0
    SME_RANGE = 45.0  # 50 - 5 = 45

    if turnover >= sme_threshold:
        return correlation  # No adjustment for large corporates

    # Cap at threshold, floor at 5
    s = max(SME_FLOOR, min(turnover, sme_threshold))

    # Calculate adjustment
    # Adjustment = 0.04 * (1 - (S - 5) / 45)
    # At S = 5: adjustment = 0.04 * 1 = 0.04
    # At S = 50: adjustment = 0.04 * 0 = 0
    adjustment = 0.04 * (1 - (s - SME_FLOOR) / SME_RANGE)

    return correlation - adjustment


def get_correlation_for_class(exposure_class: str) -> CorrelationParams:
    """
    Get correlation parameters for an exposure class.

    Args:
        exposure_class: The exposure class

    Returns:
        Dictionary with correlation parameters
    """
    return CORRELATION_PARAMS.get(
        exposure_class,
        CORRELATION_PARAMS.get("CORPORATE", {
            "type": "pd_dependent",
            "r_min": 0.12,
            "r_max": 0.24,
            "fixed": 0.0,
            "decay_factor": 50.0,
        })
    )
