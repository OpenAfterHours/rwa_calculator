"""
IRB (Internal Ratings-Based) formulas for RWA calculation.

Implements the capital requirement (K) formula and related calculations
for F-IRB and A-IRB approaches using pure Polars expressions for
vectorized operations.

Key formulas:
- Capital requirement K = LGD × N[(1-R)^(-0.5) × G(PD) + (R/(1-R))^(0.5) × G(0.999)] - PD × LGD
- Maturity adjustment MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
- RWA = K × 12.5 × [1.06] × EAD × MA (1.06 for CRR only)

References:
- CRR Art. 153-154: IRB risk weight functions
- CRR Art. 162: Maturity
- CRR Art. 163: PD floors
- CRE31: Basel 3.1 IRB approach
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import numpy as np
import polars as pl
from scipy import stats

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# CONSTANTS
# =============================================================================

# Pre-calculated G(0.999) ≈ 3.0902323061678132
G_999 = 3.0902323061678132

# Abramowitz & Stegun approximation constants for norm_cdf
_P_AS = 0.2316419
_B1 = 0.319381530
_B2 = -0.356563782
_B3 = 1.781477937
_B4 = -1.821255978
_B5 = 1.330274429

# Rational approximation coefficients for norm_ppf (Peter J. Acklam's algorithm)
_PPF_A = [
    -3.969683028665376e+01, 2.209460984245205e+02,
    -2.759285104469687e+02, 1.383577518672690e+02,
    -3.066479806614716e+01, 2.506628277459239e+00,
]
_PPF_B = [
    -5.447609879822406e+01, 1.615858368580409e+02,
    -1.556989798598866e+02, 6.680131188771972e+01,
    -1.328068155288572e+01,
]
_PPF_C = [
    -7.784894002430293e-03, -3.223964580411365e-01,
    -2.400758277161838e+00, -2.549732539343734e+00,
    4.374664141464968e+00, 2.938163982698783e+00,
]
_PPF_D = [
    7.784695709041462e-03, 3.224671290700398e-01,
    2.445134137142996e+00, 3.754408661907416e+00,
]
_PPF_P_LOW = 0.02425
_PPF_P_HIGH = 1 - _PPF_P_LOW


# =============================================================================
# POLARS EXPRESSION BUILDERS
# =============================================================================


def norm_cdf_expr(x: pl.Expr) -> pl.Expr:
    """
    Polars expression for standard normal CDF using Abramowitz & Stegun approximation.

    Accuracy: absolute error < 7.5e-8.

    For x >= 0:
        Φ(x) ≈ 1 - φ(x)(b₁t + b₂t² + b₃t³ + b₄t⁴ + b₅t⁵)
        where t = 1/(1 + px), p = 0.2316419
        φ(x) = exp(-x²/2) / √(2π)

    For x < 0: Φ(x) = 1 - Φ(-x)
    """
    # Use absolute value for calculation
    abs_x = x.abs()

    # t = 1 / (1 + p * |x|)
    t = 1.0 / (1.0 + _P_AS * abs_x)

    # Polynomial: b₁t + b₂t² + b₃t³ + b₄t⁴ + b₅t⁵
    # Horner's method: t*(b1 + t*(b2 + t*(b3 + t*(b4 + t*b5))))
    poly = t * (_B1 + t * (_B2 + t * (_B3 + t * (_B4 + t * _B5))))

    # φ(x) = exp(-x²/2) / √(2π)
    # √(2π) ≈ 2.5066282746310002
    phi = (-abs_x.pow(2) / 2.0).exp() / 2.5066282746310002

    # For |x|: Φ(|x|) ≈ 1 - φ(|x|) * poly
    cdf_abs = 1.0 - phi * poly

    # For negative x: Φ(x) = 1 - Φ(-x)
    return pl.when(x >= 0).then(cdf_abs).otherwise(1.0 - cdf_abs)


def norm_ppf_expr(p: pl.Expr) -> pl.Expr:
    """
    Polars expression for inverse standard normal CDF (percent point function).

    Uses Peter J. Acklam's rational approximation.
    Accuracy: absolute error < 1.15e-9.
    """
    # Clamp p to valid range to avoid infinities
    p_safe = p.clip(1e-10, 1.0 - 1e-10)

    # Low tail: p < 0.02425
    q_low = (-2.0 * p_safe.log()).sqrt()
    low_result = (
        (((((_PPF_C[0] * q_low + _PPF_C[1]) * q_low + _PPF_C[2]) * q_low + _PPF_C[3]) * q_low + _PPF_C[4]) * q_low + _PPF_C[5]) /
        ((((_PPF_D[0] * q_low + _PPF_D[1]) * q_low + _PPF_D[2]) * q_low + _PPF_D[3]) * q_low + 1.0)
    )

    # High tail: p > 0.97575
    q_high = (-2.0 * (1.0 - p_safe).log()).sqrt()
    high_result = -(
        (((((_PPF_C[0] * q_high + _PPF_C[1]) * q_high + _PPF_C[2]) * q_high + _PPF_C[3]) * q_high + _PPF_C[4]) * q_high + _PPF_C[5]) /
        ((((_PPF_D[0] * q_high + _PPF_D[1]) * q_high + _PPF_D[2]) * q_high + _PPF_D[3]) * q_high + 1.0)
    )

    # Middle region: 0.02425 <= p <= 0.97575
    q_mid = p_safe - 0.5
    r_mid = q_mid * q_mid
    mid_result = (
        (((((_PPF_A[0] * r_mid + _PPF_A[1]) * r_mid + _PPF_A[2]) * r_mid + _PPF_A[3]) * r_mid + _PPF_A[4]) * r_mid + _PPF_A[5]) * q_mid /
        (((((_PPF_B[0] * r_mid + _PPF_B[1]) * r_mid + _PPF_B[2]) * r_mid + _PPF_B[3]) * r_mid + _PPF_B[4]) * r_mid + 1.0)
    )

    # Select based on p region
    return (
        pl.when(p_safe < _PPF_P_LOW).then(low_result)
        .when(p_safe > _PPF_P_HIGH).then(high_result)
        .otherwise(mid_result)
    )


def correlation_expr(
    pd_col: pl.Expr,
    exposure_class_col: pl.Expr,
    turnover_m_col: pl.Expr | None = None,
    sme_threshold: float = 50.0,
) -> pl.Expr:
    """
    Polars expression for asset correlation calculation.

    Corporate: R = 0.12 × f(PD) + 0.24 × (1 - f(PD)), decay = 50
    Retail mortgage: R = 0.15 (fixed)
    QRRE: R = 0.04 (fixed)
    Other retail: R = 0.03 × f(PD) + 0.16 × (1 - f(PD)), decay = 35

    where f(PD) = (1 - e^(-k×PD)) / (1 - e^(-k))
    """
    # Pre-calculate decay denominators
    corporate_denom = 1.0 - math.exp(-50.0)  # ≈ 1.0
    retail_denom = 1.0 - math.exp(-35.0)     # ≈ 1.0

    # f(PD) for corporate (decay = 50)
    f_pd_corp = (1.0 - (-50.0 * pd_col).exp()) / corporate_denom

    # f(PD) for retail (decay = 35)
    f_pd_retail = (1.0 - (-35.0 * pd_col).exp()) / retail_denom

    # Corporate correlation: 0.12 × f(PD) + 0.24 × (1 - f(PD))
    r_corporate = 0.12 * f_pd_corp + 0.24 * (1.0 - f_pd_corp)

    # Other retail correlation: 0.03 × f(PD) + 0.16 × (1 - f(PD))
    r_retail_other = 0.03 * f_pd_retail + 0.16 * (1.0 - f_pd_retail)

    # Build correlation based on exposure class
    exp_upper = exposure_class_col.str.to_uppercase()

    base_correlation = (
        pl.when(exp_upper.str.contains("MORTGAGE") | exp_upper.str.contains("RESIDENTIAL"))
        .then(pl.lit(0.15))  # Fixed retail mortgage
        .when(exp_upper.str.contains("QRRE"))
        .then(pl.lit(0.04))  # Fixed QRRE
        .when(exp_upper.str.contains("RETAIL"))
        .then(r_retail_other)  # Other retail PD-dependent
        .otherwise(r_corporate)  # Corporate/Institution/Sovereign PD-dependent
    )

    # Apply SME firm size adjustment for corporates
    if turnover_m_col is not None:
        # SME adjustment: R_adj = R - 0.04 × (1 - (max(S, 5) - 5) / 45)
        s_clamped = turnover_m_col.clip(5.0, sme_threshold)
        sme_adjustment = 0.04 * (1.0 - (s_clamped - 5.0) / 45.0)

        # Apply only to corporates with turnover < threshold
        is_corporate = exp_upper.str.contains("CORPORATE")
        is_sme = turnover_m_col.is_not_null() & (turnover_m_col < sme_threshold)

        return pl.when(is_corporate & is_sme).then(
            base_correlation - sme_adjustment
        ).otherwise(base_correlation)

    return base_correlation


def capital_k_expr(
    pd_col: pl.Expr,
    lgd_col: pl.Expr,
    correlation_col: pl.Expr,
) -> pl.Expr:
    """
    Polars expression for capital requirement (K) calculation.

    K = LGD × N[(1-R)^(-0.5) × G(PD) + (R/(1-R))^(0.5) × G(0.999)] - PD × LGD

    where N is standard normal CDF and G is inverse normal CDF.
    """
    # Clamp PD to avoid edge cases
    pd_safe = pd_col.clip(1e-10, 0.9999)

    # G(PD) = inverse normal CDF of PD
    g_pd = norm_ppf_expr(pd_safe)

    # Terms for the conditional default probability
    # term1 = sqrt(1/(1-R)) × G(PD)
    # term2 = sqrt(R/(1-R)) × G(0.999)
    one_minus_r = 1.0 - correlation_col
    term1 = (1.0 / one_minus_r).sqrt() * g_pd
    term2 = (correlation_col / one_minus_r).sqrt() * G_999

    # Conditional PD = N(term1 + term2)
    conditional_pd = norm_cdf_expr(term1 + term2)

    # K = LGD × conditional_pd - PD × LGD
    k = lgd_col * conditional_pd - pd_col * lgd_col

    # Floor at 0
    return k.clip(lower_bound=0.0)


def maturity_adjustment_expr(
    pd_col: pl.Expr,
    maturity_col: pl.Expr,
    maturity_floor: float = 1.0,
    maturity_cap: float = 5.0,
) -> pl.Expr:
    """
    Polars expression for maturity adjustment calculation.

    b = (0.11852 - 0.05478 × ln(PD))²
    MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
    """
    # Clamp maturity to bounds
    m = maturity_col.clip(maturity_floor, maturity_cap)

    # Safe PD for log calculation
    pd_safe = pd_col.clip(lower_bound=1e-10)

    # b = (0.11852 - 0.05478 × ln(PD))²
    b = (0.11852 - 0.05478 * pd_safe.log()).pow(2)

    # MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
    return (1.0 + (m - 2.5) * b) / (1.0 - 1.5 * b)


# =============================================================================
# CORRELATION PARAMETERS (for scalar functions)
# =============================================================================


@dataclass(frozen=True)
class CorrelationParams:
    """Parameters for asset correlation calculation."""
    correlation_type: str  # "fixed" or "pd_dependent"
    r_min: float           # Minimum correlation (at high PD)
    r_max: float           # Maximum correlation (at low PD)
    fixed: float           # Fixed correlation value
    decay_factor: float    # K factor in formula (50 for corp, 35 for retail)


CORRELATION_PARAMS: dict[str, CorrelationParams] = {
    "CORPORATE": CorrelationParams("pd_dependent", 0.12, 0.24, 0.0, 50.0),
    "CORPORATE_SME": CorrelationParams("pd_dependent", 0.12, 0.24, 0.0, 50.0),
    "SOVEREIGN": CorrelationParams("pd_dependent", 0.12, 0.24, 0.0, 50.0),
    "INSTITUTION": CorrelationParams("pd_dependent", 0.12, 0.24, 0.0, 50.0),
    "RETAIL_MORTGAGE": CorrelationParams("fixed", 0.15, 0.15, 0.15, 0.0),
    "RETAIL_QRRE": CorrelationParams("fixed", 0.04, 0.04, 0.04, 0.0),
    "RETAIL": CorrelationParams("pd_dependent", 0.03, 0.16, 0.0, 35.0),
    "RETAIL_OTHER": CorrelationParams("pd_dependent", 0.03, 0.16, 0.0, 35.0),
    "RETAIL_SME": CorrelationParams("pd_dependent", 0.03, 0.16, 0.0, 35.0),
}


def get_correlation_params(exposure_class: str) -> CorrelationParams:
    """Get correlation parameters for an exposure class."""
    class_upper = exposure_class.upper().replace(" ", "_")

    if class_upper in CORRELATION_PARAMS:
        return CORRELATION_PARAMS[class_upper]

    if "MORTGAGE" in class_upper or "RESIDENTIAL" in class_upper:
        return CORRELATION_PARAMS["RETAIL_MORTGAGE"]
    if "QRRE" in class_upper:
        return CORRELATION_PARAMS["RETAIL_QRRE"]
    if "RETAIL" in class_upper:
        return CORRELATION_PARAMS["RETAIL"]
    if "SOVEREIGN" in class_upper or "GOVERNMENT" in class_upper:
        return CORRELATION_PARAMS["SOVEREIGN"]
    if "INSTITUTION" in class_upper:
        return CORRELATION_PARAMS["INSTITUTION"]

    return CORRELATION_PARAMS["CORPORATE"]


# =============================================================================
# SCALAR CALCULATIONS (for single-exposure convenience methods)
# =============================================================================


def _norm_cdf(x: float) -> float:
    """Scalar standard normal CDF."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_ppf(p: float) -> float:
    """Scalar inverse standard normal CDF."""
    if p <= 0:
        return float('-inf')
    if p >= 1:
        return float('inf')

    if p < _PPF_P_LOW:
        q = math.sqrt(-2 * math.log(p))
        return ((((((_PPF_C[0]*q + _PPF_C[1])*q + _PPF_C[2])*q + _PPF_C[3])*q + _PPF_C[4])*q + _PPF_C[5]) /
               ((((_PPF_D[0]*q + _PPF_D[1])*q + _PPF_D[2])*q + _PPF_D[3])*q + 1))
    elif p <= _PPF_P_HIGH:
        q = p - 0.5
        r = q * q
        return ((((((_PPF_A[0]*r + _PPF_A[1])*r + _PPF_A[2])*r + _PPF_A[3])*r + _PPF_A[4])*r + _PPF_A[5])*q /
               (((((_PPF_B[0]*r + _PPF_B[1])*r + _PPF_B[2])*r + _PPF_B[3])*r + _PPF_B[4])*r + 1))
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((((_PPF_C[0]*q + _PPF_C[1])*q + _PPF_C[2])*q + _PPF_C[3])*q + _PPF_C[4])*q + _PPF_C[5]) /
                ((((_PPF_D[0]*q + _PPF_D[1])*q + _PPF_D[2])*q + _PPF_D[3])*q + 1)))


def calculate_correlation(
    pd: float,
    exposure_class: str,
    turnover_m: float | None = None,
    sme_threshold: float = 50.0,
) -> float:
    """Scalar correlation calculation."""
    params = get_correlation_params(exposure_class)

    if params.correlation_type == "fixed":
        return params.fixed

    if params.decay_factor > 0:
        numerator = 1 - math.exp(-params.decay_factor * pd)
        denominator = 1 - math.exp(-params.decay_factor)
        f_pd = numerator / denominator
    else:
        f_pd = 0.5

    correlation = params.r_min * f_pd + params.r_max * (1 - f_pd)

    if turnover_m is not None and turnover_m < sme_threshold:
        if "CORPORATE" in exposure_class.upper():
            s = max(5.0, min(turnover_m, sme_threshold))
            adjustment = 0.04 * (1 - (s - 5.0) / 45.0)
            correlation = correlation - adjustment

    return correlation


def calculate_k(pd: float, lgd: float, correlation: float) -> float:
    """Scalar capital requirement calculation."""
    if pd >= 1.0:
        return lgd
    if pd <= 0:
        return 0.0

    g_pd = _norm_ppf(pd)
    term1 = math.sqrt(1 / (1 - correlation)) * g_pd
    term2 = math.sqrt(correlation / (1 - correlation)) * G_999
    conditional_pd = _norm_cdf(term1 + term2)
    k = lgd * conditional_pd - pd * lgd

    return max(k, 0.0)


def calculate_maturity_adjustment(
    pd: float,
    maturity: float,
    maturity_floor: float = 1.0,
    maturity_cap: float = 5.0,
) -> float:
    """Scalar maturity adjustment calculation."""
    m = max(maturity_floor, min(maturity_cap, maturity))
    pd_safe = max(pd, 0.00001)
    b = (0.11852 - 0.05478 * math.log(pd_safe)) ** 2
    ma = (1 + (m - 2.5) * b) / (1 - 1.5 * b)
    return ma


def calculate_irb_rwa(
    ead: float,
    pd: float,
    lgd: float,
    correlation: float,
    maturity: float = 2.5,
    apply_maturity_adjustment: bool = True,
    apply_scaling_factor: bool = True,
    pd_floor: float = 0.0003,
    lgd_floor: float | None = None,
) -> dict:
    """Scalar RWA calculation."""
    pd_floored = max(pd, pd_floor)
    lgd_floored = lgd if lgd_floor is None else max(lgd, lgd_floor)

    k = calculate_k(pd_floored, lgd_floored, correlation)

    if apply_maturity_adjustment:
        ma = calculate_maturity_adjustment(pd_floored, maturity)
    else:
        ma = 1.0

    scaling = 1.06 if apply_scaling_factor else 1.0
    rwa = k * 12.5 * scaling * ead * ma
    risk_weight = (k * 12.5 * scaling * ma) if ead > 0 else 0.0

    return {
        "pd_raw": pd,
        "pd_floored": pd_floored,
        "lgd_raw": lgd,
        "lgd_floored": lgd_floored,
        "correlation": correlation,
        "k": k,
        "maturity_adjustment": ma,
        "scaling_factor": scaling,
        "risk_weight": risk_weight,
        "rwa": rwa,
        "ead": ead,
    }


def calculate_expected_loss(pd: float, lgd: float, ead: float) -> float:
    """Calculate expected loss: EL = PD × LGD × EAD."""
    return pd * lgd * ead


# =============================================================================
# NUMPY VECTORIZED FUNCTIONS (10x faster than Polars expressions)
# =============================================================================


def _numpy_correlation(
    pd_arr: np.ndarray,
    exposure_class_arr: np.ndarray,
    turnover_m_arr: np.ndarray | None = None,
    sme_threshold: float = 50.0,
) -> np.ndarray:
    """
    NumPy vectorized correlation calculation.

    Supports all exposure classes with proper correlation formulas:
    - Corporate/Institution/Sovereign: PD-dependent (decay=50)
    - Retail mortgage: Fixed 0.15
    - QRRE: Fixed 0.04
    - Other retail: PD-dependent (decay=35)
    """
    n = len(pd_arr)
    correlation = np.zeros(n, dtype=np.float64)

    # Pre-calculate decay denominators
    corporate_denom = 1.0 - np.exp(-50.0)
    retail_denom = 1.0 - np.exp(-35.0)

    # f(PD) for corporate (decay = 50)
    f_pd_corp = (1.0 - np.exp(-50.0 * pd_arr)) / corporate_denom

    # f(PD) for retail (decay = 35)
    f_pd_retail = (1.0 - np.exp(-35.0 * pd_arr)) / retail_denom

    # Corporate correlation: 0.12 × f(PD) + 0.24 × (1 - f(PD))
    r_corporate = 0.12 * f_pd_corp + 0.24 * (1.0 - f_pd_corp)

    # Retail other correlation: 0.03 × f(PD) + 0.16 × (1 - f(PD))
    r_retail_other = 0.03 * f_pd_retail + 0.16 * (1.0 - f_pd_retail)

    # Classify by exposure class
    exp_upper = np.char.upper(exposure_class_arr.astype(str))

    # Mortgage: fixed 0.15
    is_mortgage = np.char.find(exp_upper, "MORTGAGE") >= 0
    is_residential = np.char.find(exp_upper, "RESIDENTIAL") >= 0
    correlation[is_mortgage | is_residential] = 0.15

    # QRRE: fixed 0.04
    is_qrre = np.char.find(exp_upper, "QRRE") >= 0
    correlation[is_qrre] = 0.04

    # Retail (non-mortgage, non-QRRE): PD-dependent
    is_retail = np.char.find(exp_upper, "RETAIL") >= 0
    is_retail_other = is_retail & ~is_mortgage & ~is_qrre
    correlation[is_retail_other] = r_retail_other[is_retail_other]

    # Corporate/Institution/Sovereign: PD-dependent (default)
    is_non_retail = ~is_retail
    correlation[is_non_retail] = r_corporate[is_non_retail]

    # Apply SME firm size adjustment for corporates
    if turnover_m_arr is not None:
        is_corporate = np.char.find(exp_upper, "CORPORATE") >= 0
        has_turnover = ~np.isnan(turnover_m_arr)
        is_sme = has_turnover & (turnover_m_arr < sme_threshold)
        sme_mask = is_corporate & is_sme

        if np.any(sme_mask):
            s_clamped = np.clip(turnover_m_arr[sme_mask], 5.0, sme_threshold)
            sme_adjustment = 0.04 * (1.0 - (s_clamped - 5.0) / 45.0)
            correlation[sme_mask] = correlation[sme_mask] - sme_adjustment

    return correlation


def _numpy_capital_k(
    pd_arr: np.ndarray,
    lgd_arr: np.ndarray,
    correlation_arr: np.ndarray,
) -> np.ndarray:
    """
    NumPy vectorized capital requirement (K) calculation using SciPy.

    K = LGD × N[(1-R)^(-0.5) × G(PD) + (R/(1-R))^(0.5) × G(0.999)] - PD × LGD

    Uses scipy.stats.norm for ~10x speedup vs Polars expressions.
    """
    # Clamp PD to avoid edge cases
    pd_safe = np.clip(pd_arr, 1e-10, 0.9999)

    # G(PD) = inverse normal CDF of PD (using scipy)
    g_pd = stats.norm.ppf(pd_safe)

    # Calculate conditional default probability
    one_minus_r = 1.0 - correlation_arr
    term1 = np.sqrt(1.0 / one_minus_r) * g_pd
    term2 = np.sqrt(correlation_arr / one_minus_r) * G_999

    # Conditional PD = N(term1 + term2) (using scipy)
    conditional_pd = stats.norm.cdf(term1 + term2)

    # K = LGD × conditional_pd - PD × LGD
    k = lgd_arr * conditional_pd - pd_safe * lgd_arr

    # Floor at 0
    return np.maximum(k, 0.0)


def _numpy_maturity_adjustment(
    pd_arr: np.ndarray,
    maturity_arr: np.ndarray,
    maturity_floor: float = 1.0,
    maturity_cap: float = 5.0,
) -> np.ndarray:
    """
    NumPy vectorized maturity adjustment calculation.

    b = (0.11852 - 0.05478 × ln(PD))²
    MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
    """
    # Clamp maturity to bounds
    m = np.clip(maturity_arr, maturity_floor, maturity_cap)

    # Safe PD for log calculation
    pd_safe = np.maximum(pd_arr, 1e-10)

    # b = (0.11852 - 0.05478 × ln(PD))²
    b = (0.11852 - 0.05478 * np.log(pd_safe)) ** 2

    # MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
    return (1.0 + (m - 2.5) * b) / (1.0 - 1.5 * b)


def apply_irb_formulas_numpy(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
) -> pl.LazyFrame:
    """
    Apply IRB formulas using NumPy/SciPy for ~10x faster computation.

    This function collects the LazyFrame, performs calculations with
    NumPy/SciPy (which is much faster for statistical functions), and
    returns a LazyFrame with results.

    Expects columns: pd, lgd, ead_final, exposure_class
    Optional: maturity, maturity_date, turnover_m, cp_annual_revenue

    Adds columns: pd_floored, lgd_floored, correlation, k, maturity_adjustment,
                  scaling_factor, risk_weight, rwa, expected_loss

    Args:
        exposures: LazyFrame with IRB exposures
        config: Calculation configuration

    Returns:
        LazyFrame with IRB calculations added
    """
    # Collect to DataFrame for NumPy operations
    df = exposures.collect()
    n_rows = len(df)

    if n_rows == 0:
        # Return empty frame with expected columns
        return exposures.with_columns([
            pl.lit(None).cast(pl.Float64).alias("pd_floored"),
            pl.lit(None).cast(pl.Float64).alias("lgd_floored"),
            pl.lit(None).cast(pl.Float64).alias("correlation"),
            pl.lit(None).cast(pl.Float64).alias("k"),
            pl.lit(None).cast(pl.Float64).alias("maturity_adjustment"),
            pl.lit(None).cast(pl.Float64).alias("scaling_factor"),
            pl.lit(None).cast(pl.Float64).alias("risk_weight"),
            pl.lit(None).cast(pl.Float64).alias("rwa"),
            pl.lit(None).cast(pl.Float64).alias("expected_loss"),
        ])

    # Extract arrays
    pd_arr = df["pd"].fill_null(0.01).to_numpy()
    lgd_arr = df["lgd"].fill_null(0.45).to_numpy()
    ead_arr = df["ead_final"].fill_null(0.0).to_numpy()
    exp_class_arr = df["exposure_class"].fill_null("CORPORATE").to_numpy()

    # Get turnover for SME adjustment
    turnover_m_arr = None
    if "turnover_m" in df.columns:
        turnover_m_arr = df["turnover_m"].to_numpy().astype(np.float64)
    elif "cp_annual_revenue" in df.columns:
        turnover_m_arr = df["cp_annual_revenue"].to_numpy().astype(np.float64) / 1_000_000.0

    # Calculate maturity
    if "maturity" in df.columns:
        maturity_arr = df["maturity"].fill_null(2.5).to_numpy()
    elif "maturity_date" in df.columns:
        mat_dates = df["maturity_date"].to_numpy()
        today = np.datetime64(config.reporting_date)
        mat_days = (mat_dates - today).astype("timedelta64[D]").astype(float)
        maturity_arr = np.clip(mat_days / 365.0, 1.0, 5.0)
        maturity_arr = np.nan_to_num(maturity_arr, nan=2.5)
    else:
        maturity_arr = np.full(n_rows, 2.5)

    # Step 1: Apply PD floor
    pd_floor = float(config.pd_floors.corporate)
    pd_floored = np.maximum(pd_arr, pd_floor)

    # Step 2: Apply LGD floor (Basel 3.1 A-IRB only)
    if config.is_basel_3_1:
        lgd_floor = float(config.lgd_floors.unsecured)
        lgd_floored = np.maximum(lgd_arr, lgd_floor)
    else:
        lgd_floored = lgd_arr.copy()

    # Step 3: Calculate correlation
    correlation = _numpy_correlation(
        pd_floored, exp_class_arr, turnover_m_arr
    )

    # Step 4: Calculate K (capital requirement)
    k = _numpy_capital_k(pd_floored, lgd_floored, correlation)

    # Step 5: Calculate maturity adjustment (only for non-retail)
    exp_upper = np.char.upper(exp_class_arr.astype(str))
    is_retail = np.char.find(exp_upper, "RETAIL") >= 0
    ma = _numpy_maturity_adjustment(pd_floored, maturity_arr)
    ma[is_retail] = 1.0  # No MA for retail

    # Step 6: Scaling factor
    scaling = 1.06 if config.is_crr else 1.0

    # Step 7: Calculate RWA = K × 12.5 × scaling × EAD × MA
    rwa = k * 12.5 * scaling * ead_arr * ma

    # Step 8: Calculate risk weight = K × 12.5 × scaling × MA
    risk_weight = k * 12.5 * scaling * ma

    # Step 9: Calculate expected loss = PD × LGD × EAD
    expected_loss = pd_floored * lgd_floored * ead_arr

    # Add calculated columns back to DataFrame
    result = df.with_columns([
        pl.Series("pd_floored", pd_floored),
        pl.Series("lgd_floored", lgd_floored),
        pl.Series("correlation", correlation),
        pl.Series("k", k),
        pl.Series("maturity_adjustment", ma),
        pl.lit(scaling).alias("scaling_factor"),
        pl.Series("risk_weight", risk_weight),
        pl.Series("rwa", rwa),
        pl.Series("expected_loss", expected_loss),
    ])

    return result.lazy()


# =============================================================================
# MAIN VECTORIZED FUNCTION (Polars expressions - slower but pure lazy)
# =============================================================================


def apply_irb_formulas(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
) -> pl.LazyFrame:
    """
    Apply IRB formulas to exposures using pure Polars expressions.

    This is fully vectorized - no Python loops or map_elements.

    Expects columns: pd, lgd, ead_final, exposure_class, maturity
    Optional: turnover_m (for SME correlation adjustment)

    Adds columns: pd_floored, lgd_floored, correlation, k, maturity_adjustment,
                  scaling_factor, risk_weight, rwa, expected_loss

    Args:
        exposures: LazyFrame with IRB exposures
        config: Calculation configuration

    Returns:
        LazyFrame with IRB calculations added
    """
    pd_floor = float(config.pd_floors.corporate)
    apply_scaling = config.is_crr

    # Ensure required columns exist
    schema = exposures.collect_schema()
    if "maturity" not in schema.names():
        exposures = exposures.with_columns(pl.lit(2.5).alias("maturity"))
    if "turnover_m" not in schema.names():
        exposures = exposures.with_columns(pl.lit(None).cast(pl.Float64).alias("turnover_m"))

    # Step 1: Apply PD floor
    exposures = exposures.with_columns(
        pl.col("pd").clip(lower_bound=pd_floor).alias("pd_floored")
    )

    # Step 2: Apply LGD floor (Basel 3.1 A-IRB only)
    if config.is_basel_3_1:
        lgd_floor = float(config.lgd_floors.unsecured)
        exposures = exposures.with_columns(
            pl.col("lgd").clip(lower_bound=lgd_floor).alias("lgd_floored")
        )
    else:
        exposures = exposures.with_columns(
            pl.col("lgd").alias("lgd_floored")
        )

    # Step 3: Calculate correlation using pure Polars expressions
    exp_class_col = pl.col("exposure_class").cast(pl.String).fill_null("CORPORATE")
    turnover_col = pl.col("turnover_m") if "turnover_m" in schema.names() else None

    exposures = exposures.with_columns(
        correlation_expr(
            pl.col("pd_floored"),
            exp_class_col,
            turnover_col,
        ).alias("correlation")
    )

    # Step 4: Calculate K using pure Polars expressions
    exposures = exposures.with_columns(
        capital_k_expr(
            pl.col("pd_floored"),
            pl.col("lgd_floored"),
            pl.col("correlation"),
        ).alias("k")
    )

    # Step 5: Determine if retail (no MA, no scaling for retail)
    is_retail = exp_class_col.str.to_uppercase().str.contains("RETAIL")

    # Step 6: Calculate maturity adjustment (only for non-retail)
    ma_expr = maturity_adjustment_expr(pl.col("pd_floored"), pl.col("maturity"))
    exposures = exposures.with_columns(
        pl.when(is_retail).then(pl.lit(1.0)).otherwise(ma_expr).alias("maturity_adjustment")
    )

    # Step 7: Scaling factor (CRR only - applies to ALL exposures including retail)
    # Under CRR Art. 153(1), the 1.06 scaling factor applies to all IRB exposures
    # Basel 3.1 removes this scaling factor entirely
    if apply_scaling:
        exposures = exposures.with_columns(
            pl.lit(1.06).alias("scaling_factor")
        )
    else:
        exposures = exposures.with_columns(
            pl.lit(1.0).alias("scaling_factor")
        )

    # Step 8: Calculate RWA = K × 12.5 × scaling × EAD × MA
    exposures = exposures.with_columns(
        (pl.col("k") * 12.5 * pl.col("scaling_factor") * pl.col("ead_final") * pl.col("maturity_adjustment")).alias("rwa")
    )

    # Step 9: Calculate risk weight = K × 12.5 × scaling × MA
    exposures = exposures.with_columns(
        (pl.col("k") * 12.5 * pl.col("scaling_factor") * pl.col("maturity_adjustment")).alias("risk_weight")
    )

    # Step 10: Calculate expected loss = PD × LGD × EAD
    exposures = exposures.with_columns(
        (pl.col("pd_floored") * pl.col("lgd_floored") * pl.col("ead_final")).alias("expected_loss")
    )

    return exposures
