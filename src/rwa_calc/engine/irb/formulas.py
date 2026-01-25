"""
IRB (Internal Ratings-Based) formulas for RWA calculation.

Implements the capital requirement (K) formula and related calculations
for F-IRB and A-IRB approaches.

Key formulas:
- Capital requirement K = LGD × N[(1-R)^(-0.5) × G(PD) + (R/(1-R))^(0.5) × G(0.999)] - PD × LGD
- Maturity adjustment MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
- RWA = K × 12.5 × [1.06] × EAD × MA (1.06 for CRR only)

Implementation uses pure Polars expressions with polars-normal-stats:
- Full lazy evaluation preserved (query optimization, streaming)
- Uses polars-normal-stats for statistical functions (normal_cdf, normal_ppf)
- No NumPy/SciPy dependency - enables true streaming for large datasets

References:
- CRR Art. 153-154: IRB risk weight functions
- CRR Art. 162: Maturity
- CRR Art. 163: PD floors
- CRE31: Basel 3.1 IRB approach
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl
from polars_normal_stats import normal_cdf, normal_ppf

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# CONSTANTS
# =============================================================================

# Pre-calculated G(0.999) ≈ 3.0902323061678132
G_999 = 3.0902323061678132

# Rational approximation coefficients for norm_ppf (Peter J. Acklam's algorithm)
# Used by scalar functions
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
# MAIN VECTORIZED FUNCTION (pure Polars with polars-normal-stats)
# =============================================================================


def apply_irb_formulas(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
) -> pl.LazyFrame:
    """
    Apply IRB formulas to exposures using pure Polars expressions.

    Uses polars-normal-stats for statistical functions (normal_cdf, normal_ppf),
    enabling full lazy evaluation, query optimization, and streaming.

    Expects columns: pd, lgd, ead_final, exposure_class
    Optional: maturity, turnover_m (for SME correlation adjustment)

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
    scaling_factor = 1.06 if apply_scaling else 1.0

    # Ensure required columns exist
    schema = exposures.collect_schema()
    if "maturity" not in schema.names():
        exposures = exposures.with_columns(pl.lit(2.5).alias("maturity"))
    if "turnover_m" not in schema.names():
        exposures = exposures.with_columns(pl.lit(None).cast(pl.Float64).alias("turnover_m"))

    # Step 1: Apply PD floor (pure Polars)
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
    exposures = exposures.with_columns(
        _polars_correlation_expr().alias("correlation")
    )

    # Step 4: Calculate K using pure Polars with polars-normal-stats
    exposures = exposures.with_columns(
        _polars_capital_k_expr().alias("k")
    )

    # Step 5: Calculate maturity adjustment (only for non-retail)
    is_retail = (
        pl.col("exposure_class")
        .cast(pl.String)
        .fill_null("CORPORATE")
        .str.to_uppercase()
        .str.contains("RETAIL")
    )

    exposures = exposures.with_columns(
        pl.when(is_retail)
        .then(pl.lit(1.0))
        .otherwise(_polars_maturity_adjustment_expr())
        .alias("maturity_adjustment")
    )

    # Step 6-9: Final calculations (pure Polars expressions)
    exposures = exposures.with_columns([
        pl.lit(scaling_factor).alias("scaling_factor"),
        (pl.col("k") * 12.5 * scaling_factor * pl.col("ead_final") * pl.col("maturity_adjustment")).alias("rwa"),
        (pl.col("k") * 12.5 * scaling_factor * pl.col("maturity_adjustment")).alias("risk_weight"),
        (pl.col("pd_floored") * pl.col("lgd_floored") * pl.col("ead_final")).alias("expected_loss"),
    ])

    return exposures


# Backward compatibility alias
apply_irb_formulas_numpy = apply_irb_formulas


# =============================================================================
# PURE POLARS EXPRESSION FUNCTIONS
# =============================================================================


def _polars_correlation_expr(sme_threshold: float = 50.0) -> pl.Expr:
    """
    Pure Polars expression for correlation calculation.

    Supports all exposure classes with proper correlation formulas:
    - Corporate/Institution/Sovereign: PD-dependent (decay=50)
    - Retail mortgage: Fixed 0.15
    - QRRE: Fixed 0.04
    - Other retail: PD-dependent (decay=35)

    Includes SME firm size adjustment for corporates.
    """
    pd = pl.col("pd_floored")
    exp_class = pl.col("exposure_class").cast(pl.String).fill_null("CORPORATE").str.to_uppercase()
    turnover = pl.col("turnover_m")

    # Pre-calculate decay denominators (constants)
    corporate_denom = 1.0 - math.exp(-50.0)
    retail_denom = 1.0 - math.exp(-35.0)

    # f(PD) for corporate (decay = 50)
    f_pd_corp = (1.0 - (-50.0 * pd).exp()) / corporate_denom

    # f(PD) for retail (decay = 35)
    f_pd_retail = (1.0 - (-35.0 * pd).exp()) / retail_denom

    # Corporate correlation: 0.12 × f(PD) + 0.24 × (1 - f(PD))
    r_corporate = 0.12 * f_pd_corp + 0.24 * (1.0 - f_pd_corp)

    # Retail other correlation: 0.03 × f(PD) + 0.16 × (1 - f(PD))
    r_retail_other = 0.03 * f_pd_retail + 0.16 * (1.0 - f_pd_retail)

    # SME adjustment for corporates: reduce correlation based on turnover
    # s_clamped = max(5, min(turnover, 50))
    # adjustment = 0.04 × (1 - (s_clamped - 5) / 45)
    # Cast to Float64 first to handle null dtype, then clip
    turnover_float = turnover.cast(pl.Float64)
    s_clamped = turnover_float.clip(5.0, sme_threshold)
    sme_adjustment = 0.04 * (1.0 - (s_clamped - 5.0) / 45.0)

    # Corporate with SME adjustment (when turnover < threshold and is corporate)
    is_corporate = exp_class.str.contains("CORPORATE")
    # Use is_not_null() and is_finite() to check for valid turnover values
    # is_finite() returns false for NaN and infinities, handles null dtype gracefully
    has_valid_turnover = turnover_float.is_not_null() & turnover_float.is_finite()
    is_sme = has_valid_turnover & (turnover_float < sme_threshold)

    r_corporate_with_sme = (
        pl.when(is_corporate & is_sme)
        .then(r_corporate - sme_adjustment)
        .otherwise(r_corporate)
    )

    # Build correlation based on exposure class
    return (
        pl.when(exp_class.str.contains("MORTGAGE") | exp_class.str.contains("RESIDENTIAL"))
        .then(pl.lit(0.15))
        .when(exp_class.str.contains("QRRE"))
        .then(pl.lit(0.04))
        .when(exp_class.str.contains("RETAIL"))
        .then(r_retail_other)
        .otherwise(r_corporate_with_sme)
    )


def _polars_capital_k_expr() -> pl.Expr:
    """
    Pure Polars expression for capital requirement (K) calculation.

    K = LGD × N[(1-R)^(-0.5) × G(PD) + (R/(1-R))^(0.5) × G(0.999)] - PD × LGD

    Uses polars-normal-stats for normal_cdf and normal_ppf functions.
    """
    # Safe PD to avoid edge cases
    pd_safe = pl.col("pd_floored").clip(1e-10, 0.9999)
    lgd = pl.col("lgd_floored")
    correlation = pl.col("correlation")

    # G(PD) = inverse normal CDF of PD
    g_pd = normal_ppf(pd_safe)

    # Calculate conditional default probability terms
    one_minus_r = 1.0 - correlation
    term1 = (1.0 / one_minus_r).sqrt() * g_pd
    term2 = (correlation / one_minus_r).sqrt() * G_999

    # Conditional PD = N(term1 + term2)
    conditional_pd = normal_cdf(term1 + term2)

    # K = LGD × conditional_pd - PD × LGD
    k = lgd * conditional_pd - pd_safe * lgd

    # Floor at 0
    return pl.max_horizontal(k, pl.lit(0.0))


def _polars_maturity_adjustment_expr(
    maturity_floor: float = 1.0,
    maturity_cap: float = 5.0,
) -> pl.Expr:
    """
    Pure Polars expression for maturity adjustment calculation.

    b = (0.11852 - 0.05478 × ln(PD))²
    MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
    """
    # Clamp maturity to bounds
    m = pl.col("maturity").clip(maturity_floor, maturity_cap)

    # Safe PD for log calculation
    pd_safe = pl.col("pd_floored").clip(lower_bound=1e-10)

    # b = (0.11852 - 0.05478 × ln(PD))²
    b = (0.11852 - 0.05478 * pd_safe.log()) ** 2

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
