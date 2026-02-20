"""
IRB (Internal Ratings-Based) formulas for RWA calculation.

Implements the capital requirement (K) formula and related calculations
for F-IRB and A-IRB approaches.

Key formulas:
- Capital requirement K = LGD × N[(1-R)^(-0.5) × G(PD) + (R/(1-R))^(0.5) × G(0.999)] - PD × LGD
- Maturity adjustment MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
- RWA = K × 12.5 × [1.06] × EAD × MA (1.06 for CRR only)

Implementation architecture:
- Vectorized expressions: Pure Polars expressions for bulk processing
- Scalar wrappers: Thin wrappers around vectorized expressions for single-value calculations
- Stats backend: Uses polars-normal-stats for native Polars statistical functions

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

from rwa_calc.engine.irb.stats_backend import normal_cdf, normal_ppf

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# CONSTANTS
# =============================================================================

# Pre-calculated G(0.999) ≈ 3.0902323061678132
G_999 = 3.0902323061678132


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
    # Ensure requires_fi_scalar column exists (for FI scalar in correlation)
    # This is normally set by the classifier, default to False if not present
    schema = exposures.collect_schema()
    if "requires_fi_scalar" not in schema.names():
        exposures = exposures.with_columns(pl.lit(False).alias("requires_fi_scalar"))

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
    # Pass EUR/GBP rate from config to convert GBP turnover to EUR for SME adjustment
    eur_gbp_rate = float(config.eur_gbp_rate)
    exposures = exposures.with_columns(
        _polars_correlation_expr(eur_gbp_rate=eur_gbp_rate).alias("correlation")
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

    # Step 10: Override for defaulted exposures (CRR Art. 153(1)(ii) / 154(1)(i))
    schema = exposures.collect_schema()
    if "is_defaulted" in schema.names():
        is_defaulted = pl.col("is_defaulted").fill_null(False)

        # Determine A-IRB flag
        is_airb = (
            pl.col("is_airb").fill_null(False)
            if "is_airb" in schema.names()
            else pl.lit(False)
        )

        # BEEL column
        beel = (
            pl.col("beel").fill_null(0.0)
            if "beel" in schema.names()
            else pl.lit(0.0)
        )

        # Scaling for defaulted: CRR 1.06 for non-retail, 1.0 for retail
        defaulted_scaling = (
            pl.when(is_retail).then(pl.lit(1.0)).otherwise(pl.lit(scaling_factor))
        )

        k_defaulted = (
            pl.when(is_airb)
            .then(pl.max_horizontal(pl.lit(0.0), pl.col("lgd_floored") - beel))
            .otherwise(pl.lit(0.0))
        )

        rwa_defaulted = k_defaulted * 12.5 * defaulted_scaling * pl.col("ead_final")
        rw_defaulted = k_defaulted * 12.5 * defaulted_scaling

        el_defaulted = (
            pl.when(is_airb)
            .then(beel * pl.col("ead_final"))
            .otherwise(pl.col("lgd_floored") * pl.col("ead_final"))
        )

        exposures = exposures.with_columns([
            pl.when(is_defaulted).then(k_defaulted).otherwise(pl.col("k")).alias("k"),
            pl.when(is_defaulted).then(pl.lit(0.0)).otherwise(pl.col("correlation")).alias("correlation"),
            pl.when(is_defaulted).then(pl.lit(1.0)).otherwise(pl.col("maturity_adjustment")).alias("maturity_adjustment"),
            pl.when(is_defaulted).then(rwa_defaulted).otherwise(pl.col("rwa")).alias("rwa"),
            pl.when(is_defaulted).then(rw_defaulted).otherwise(pl.col("risk_weight")).alias("risk_weight"),
            pl.when(is_defaulted).then(el_defaulted).otherwise(pl.col("expected_loss")).alias("expected_loss"),
        ])

    return exposures


# Backward compatibility alias
apply_irb_formulas_numpy = apply_irb_formulas


# =============================================================================
# PURE POLARS EXPRESSION FUNCTIONS
# =============================================================================


def _polars_correlation_expr(
    sme_threshold: float = 50.0,
    eur_gbp_rate: float = 0.8732,
) -> pl.Expr:
    """
    Pure Polars expression for correlation calculation.

    Supports all exposure classes with proper correlation formulas:
    - Corporate/Institution/Sovereign: PD-dependent (decay=50)
    - Retail mortgage: Fixed 0.15
    - QRRE: Fixed 0.04
    - Other retail: PD-dependent (decay=35)

    Includes:
    - SME firm size adjustment for corporates (turnover converted from GBP to EUR)
    - FI scalar (1.25x) for large/unregulated financial sector entities (CRR Art. 153(2))

    Args:
        sme_threshold: SME threshold in EUR millions (default 50.0)
        eur_gbp_rate: EUR/GBP exchange rate for converting GBP turnover to EUR (default 0.8732)
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
    # The SME threshold is in EUR, but turnover_m is stored in GBP millions
    # Convert GBP turnover to EUR: turnover_eur = turnover_gbp / eur_gbp_rate
    # s_clamped = max(5, min(turnover_eur, 50))
    # adjustment = 0.04 × (1 - (s_clamped - 5) / 45)
    # Cast to Float64 first to handle null dtype, then convert to EUR and clip
    turnover_float = turnover.cast(pl.Float64)
    turnover_eur = turnover_float / eur_gbp_rate
    s_clamped = turnover_eur.clip(5.0, sme_threshold)
    sme_adjustment = 0.04 * (1.0 - (s_clamped - 5.0) / 45.0)

    # Corporate with SME adjustment (when turnover_eur < threshold and is corporate)
    is_corporate = exp_class.str.contains("CORPORATE")
    # Use is_not_null() and is_finite() to check for valid turnover values
    # is_finite() returns false for NaN and infinities, handles null dtype gracefully
    has_valid_turnover = turnover_eur.is_not_null() & turnover_eur.is_finite()
    is_sme = has_valid_turnover & (turnover_eur < sme_threshold)

    r_corporate_with_sme = (
        pl.when(is_corporate & is_sme)
        .then(r_corporate - sme_adjustment)
        .otherwise(r_corporate)
    )

    # Build base correlation based on exposure class
    base_correlation = (
        pl.when(exp_class.str.contains("MORTGAGE") | exp_class.str.contains("RESIDENTIAL"))
        .then(pl.lit(0.15))
        .when(exp_class.str.contains("QRRE"))
        .then(pl.lit(0.04))
        .when(exp_class.str.contains("RETAIL"))
        .then(r_retail_other)
        .otherwise(r_corporate_with_sme)
    )

    # Apply FI scalar (1.25x) for large/unregulated financial sector entities
    # Per CRR Article 153(2): "For all exposures to large financial sector entities,
    # the coefficient of correlation is multiplied by 1.25. For all exposures to
    # unregulated financial sector entities, the coefficients of correlation are
    # multiplied by 1.25."
    # Note: The requires_fi_scalar column is set by the classifier
    fi_scalar = (
        pl.when(pl.col("requires_fi_scalar").fill_null(False) == True)  # noqa: E712
        .then(pl.lit(1.25))
        .otherwise(pl.lit(1.0))
    )

    return base_correlation * fi_scalar


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
    "CENTRAL_GOVT_CENTRAL_BANK": CorrelationParams("pd_dependent", 0.12, 0.24, 0.0, 50.0),
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
    if "CENTRAL_GOVT" in class_upper or "GOVERNMENT" in class_upper:
        return CORRELATION_PARAMS["CENTRAL_GOVT_CENTRAL_BANK"]
    if "INSTITUTION" in class_upper:
        return CORRELATION_PARAMS["INSTITUTION"]

    return CORRELATION_PARAMS["CORPORATE"]


# =============================================================================
# SCALAR WRAPPER HELPER
# =============================================================================


def _run_scalar_via_vectorized(
    inputs: dict[str, float | str | bool | None],
    output_col: str,
) -> float:
    """
    Execute a scalar calculation via vectorized expressions.

    Creates a 1-row LazyFrame, applies the appropriate expression based on
    output_col, and extracts the scalar result. This ensures scalar functions
    use the exact same implementation as vectorized processing.

    Args:
        inputs: Dictionary of input values (column names to values)
        output_col: Name of the output column to extract

    Returns:
        Scalar result from the vectorized expression
    """
    # Build 1-row DataFrame from inputs
    data = {k: [v] for k, v in inputs.items()}
    lf = pl.LazyFrame(data)

    # Apply the appropriate expression based on output column
    if output_col == "correlation":
        eur_gbp_rate = inputs.get("eur_gbp_rate", 0.8732)
        expr = _polars_correlation_expr(eur_gbp_rate=float(eur_gbp_rate))
    elif output_col == "k":
        expr = _polars_capital_k_expr()
    elif output_col == "maturity_adjustment":
        expr = _polars_maturity_adjustment_expr()
    elif output_col == "cdf":
        expr = normal_cdf(pl.col("x"))
    elif output_col == "ppf":
        expr = normal_ppf(pl.col("p"))
    else:
        msg = f"Unknown output column: {output_col}"
        raise ValueError(msg)

    result = lf.with_columns(expr.alias(output_col)).collect()
    return float(result[output_col][0])


# =============================================================================
# SCALAR CALCULATIONS (wrappers around vectorized expressions)
# =============================================================================


def _norm_cdf(x: float) -> float:
    """Scalar standard normal CDF.

    Wrapper around vectorized normal_cdf expression.
    """
    return _run_scalar_via_vectorized({"x": x}, "cdf")


def _norm_ppf(p: float) -> float:
    """Scalar inverse standard normal CDF.

    Wrapper around vectorized normal_ppf expression.
    """
    if p <= 0:
        return float("-inf")
    if p >= 1:
        return float("inf")
    return _run_scalar_via_vectorized({"p": p}, "ppf")


def calculate_correlation(
    pd: float,
    exposure_class: str,
    turnover_m: float | None = None,
    sme_threshold: float = 50.0,
    apply_fi_scalar: bool = False,
    eur_gbp_rate: float = 0.8732,
) -> float:
    """
    Scalar correlation calculation.

    Wrapper around _polars_correlation_expr() - uses the same implementation
    as vectorized processing.

    Args:
        pd: Probability of default
        exposure_class: Exposure class string
        turnover_m: Turnover in GBP millions (for SME adjustment, will be converted to EUR)
        sme_threshold: SME threshold in EUR millions (default 50.0)
        apply_fi_scalar: Whether to apply 1.25x FI scalar (CRR Art. 153(2))
                        for large/unregulated financial sector entities
        eur_gbp_rate: EUR/GBP exchange rate for converting GBP turnover to EUR (default 0.8732)

    Returns:
        Asset correlation value
    """
    return _run_scalar_via_vectorized(
        {
            "pd_floored": pd,
            "exposure_class": exposure_class,
            "turnover_m": turnover_m,
            "requires_fi_scalar": apply_fi_scalar,
            "eur_gbp_rate": eur_gbp_rate,
        },
        "correlation",
    )


def calculate_k(pd: float, lgd: float, correlation: float) -> float:
    """Scalar capital requirement calculation.

    Wrapper around _polars_capital_k_expr() - uses the same implementation
    as vectorized processing.

    Args:
        pd: Probability of default (floored)
        lgd: Loss given default (floored)
        correlation: Asset correlation

    Returns:
        Capital requirement K value
    """
    # Handle edge cases that vectorized expression clips
    if pd >= 1.0:
        return lgd
    if pd <= 0:
        return 0.0

    return _run_scalar_via_vectorized(
        {
            "pd_floored": pd,
            "lgd_floored": lgd,
            "correlation": correlation,
        },
        "k",
    )


def calculate_maturity_adjustment(
    pd: float,
    maturity: float,
    maturity_floor: float = 1.0,
    maturity_cap: float = 5.0,
) -> float:
    """Scalar maturity adjustment calculation.

    Wrapper around _polars_maturity_adjustment_expr() - uses the same
    implementation as vectorized processing.

    Args:
        pd: Probability of default (floored)
        maturity: Effective maturity in years
        maturity_floor: Minimum maturity (default 1.0)
        maturity_cap: Maximum maturity (default 5.0)

    Returns:
        Maturity adjustment factor
    """
    # Pre-apply floor/cap to match vectorized behavior
    m = max(maturity_floor, min(maturity_cap, maturity))
    pd_safe = max(pd, 1e-10)

    return _run_scalar_via_vectorized(
        {
            "pd_floored": pd_safe,
            "maturity": m,
        },
        "maturity_adjustment",
    )


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
    """Scalar RWA calculation.

    Orchestrates scalar wrappers for K and maturity adjustment.
    Keeps dict return format for backward compatibility.

    Args:
        ead: Exposure at default
        pd: Probability of default (raw)
        lgd: Loss given default (raw)
        correlation: Asset correlation
        maturity: Effective maturity in years
        apply_maturity_adjustment: Whether to apply maturity adjustment
        apply_scaling_factor: Whether to apply CRR 1.06 scaling
        pd_floor: PD floor to apply
        lgd_floor: LGD floor to apply (None = no floor)

    Returns:
        Dictionary with all calculation components
    """
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
    """Calculate expected loss: EL = PD x LGD x EAD.

    Simple multiplication - no need for vectorized wrapper.
    """
    return pd * lgd * ead
