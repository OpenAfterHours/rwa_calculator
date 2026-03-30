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
# PD AND LGD FLOOR EXPRESSION HELPERS
# =============================================================================


def _pd_floor_expression(
    config: CalculationConfig,
    *,
    has_transactor_col: bool = True,
) -> pl.Expr:
    """
    Build Polars expression for per-exposure-class PD floor.

    Under CRR (Art. 163): Uniform 0.03% floor for all exposure classes.
    Under Basel 3.1 (CRE30.55): Differentiated floors:
        - Corporate/SME: 0.05%
        - Retail mortgage: 0.05%
        - QRRE transactors: 0.03%, revolvers: 0.10%
        - Retail other: 0.05%

    Args:
        config: Calculation configuration
        has_transactor_col: Whether the LazyFrame has an is_qrre_transactor column.
            When True (pipeline path), uses per-row transactor/revolver distinction.
            When False (isolated expressions), defaults to conservative revolver floor.

    Returns a Polars expression evaluating to the per-row PD floor value.
    """
    floors = config.pd_floors

    # Optimisation: if all floors are the same (CRR case), return a scalar
    all_values = {
        floors.corporate,
        floors.corporate_sme,
        floors.retail_mortgage,
        floors.retail_other,
        floors.retail_qrre_transactor,
        floors.retail_qrre_revolver,
    }
    if len(all_values) == 1:
        return pl.lit(float(all_values.pop()))

    # Basel 3.1: differentiated floors by exposure class
    exp_class = pl.col("exposure_class").cast(pl.String).fill_null("CORPORATE").str.to_uppercase()

    # QRRE transactor/revolver distinction (CRE30.55):
    # Transactors (repay in full each period) get 0.03% floor;
    # revolvers (carry balance) get 0.10% floor.
    if has_transactor_col:
        qrre_floor = (
            pl.when(pl.col("is_qrre_transactor").fill_null(False))
            .then(pl.lit(float(floors.retail_qrre_transactor)))
            .otherwise(pl.lit(float(floors.retail_qrre_revolver)))
        )
    else:
        # Conservative default: revolver floor (0.10% under Basel 3.1)
        qrre_floor = pl.lit(float(floors.retail_qrre_revolver))

    return (
        pl.when(exp_class.str.contains("QRRE"))
        .then(qrre_floor)
        .when(exp_class.str.contains("MORTGAGE") | exp_class.str.contains("RESIDENTIAL"))
        .then(pl.lit(float(floors.retail_mortgage)))
        .when(exp_class.str.contains("RETAIL"))
        .then(pl.lit(float(floors.retail_other)))
        .when(exp_class == "CORPORATE_SME")
        .then(pl.lit(float(floors.corporate_sme)))
        .otherwise(pl.lit(float(floors.corporate)))
    )


def _lgd_floor_expression(
    config: CalculationConfig,
    *,
    has_seniority: bool = False,
) -> pl.Expr:
    """
    Build Polars expression for LGD floor (no collateral_type column).

    Under CRR: No LGD floors (returns 0.0).
    Under Basel 3.1 (CRE30.41): Differentiated floors for A-IRB:
        - Unsecured (senior): 25%
        - Unsecured (subordinated): 50%
        - Financial collateral: 0%
        - Receivables: 10%
        - CRE: 10%, RRE: 5%
        - Other physical: 15%

    Without a collateral_type column, defaults to unsecured floor (25%/50%).
    When has_seniority=True, checks seniority column for subordinated (50%).

    Returns a Polars expression evaluating to the per-row LGD floor value.
    """
    if config.is_crr:
        return pl.lit(0.0)

    floors = config.lgd_floors

    if has_seniority:
        is_subordinated = (
            pl.col("seniority").fill_null("senior").str.to_lowercase().str.contains("sub")
        )
        return (
            pl.when(is_subordinated)
            .then(pl.lit(float(floors.subordinated_unsecured)))
            .otherwise(pl.lit(float(floors.unsecured)))
        )

    # Default to unsecured floor (25%) — most conservative for senior
    return pl.lit(float(floors.unsecured))


def _lgd_floor_expression_with_collateral(
    config: CalculationConfig,
    *,
    has_seniority: bool = False,
) -> pl.Expr:
    """
    Build Polars expression for per-collateral-type LGD floor when collateral_type
    column is available.

    This is used when the dataframe has a collateral_type column, allowing
    precise per-row LGD floors based on the primary collateral type.

    When has_seniority=True, subordinated unsecured exposures get the higher
    50% floor instead of 25% (CRE30.41).
    """
    if config.is_crr:
        return pl.lit(0.0)

    floors = config.lgd_floors
    coll = pl.col("collateral_type").fill_null("unsecured").str.to_lowercase()

    # Determine unsecured floor: 50% for subordinated, 25% for senior (CRE30.41)
    if has_seniority:
        is_subordinated = (
            pl.col("seniority").fill_null("senior").str.to_lowercase().str.contains("sub")
        )
        unsecured_floor = (
            pl.when(is_subordinated)
            .then(pl.lit(float(floors.subordinated_unsecured)))
            .otherwise(pl.lit(float(floors.unsecured)))
        )
    else:
        unsecured_floor = pl.lit(float(floors.unsecured))

    return (
        pl.when(coll.is_in(["financial_collateral", "cash", "deposit", "gold", "financial"]))
        .then(pl.lit(float(floors.financial_collateral)))
        .when(coll.is_in(["receivables", "trade_receivables"]))
        .then(pl.lit(float(floors.receivables)))
        .when(coll.is_in(["residential_re", "rre", "residential", "residential_property"]))
        .then(pl.lit(float(floors.residential_real_estate)))
        .when(coll.is_in(["commercial_re", "cre", "commercial", "commercial_property"]))
        .then(pl.lit(float(floors.commercial_real_estate)))
        .when(coll.is_in(["real_estate", "property", "immovable"]))
        .then(pl.lit(float(floors.commercial_real_estate)))
        .when(coll.is_in(["other_physical", "equipment", "inventory"]))
        .then(pl.lit(float(floors.other_physical)))
        .otherwise(unsecured_floor)
    )


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
    apply_scaling = config.is_crr
    scaling_factor = 1.06 if apply_scaling else 1.0

    # Ensure required columns exist
    schema = exposures.collect_schema()
    schema_names = schema.names()
    if "maturity" not in schema_names:
        exposures = exposures.with_columns(pl.lit(2.5).alias("maturity"))
    if "turnover_m" not in schema_names:
        exposures = exposures.with_columns(pl.lit(None).cast(pl.Float64).alias("turnover_m"))
    # Ensure requires_fi_scalar column exists (for FI scalar in correlation)
    # This is normally set by the classifier, default to False if not present
    if "requires_fi_scalar" not in schema_names:
        exposures = exposures.with_columns(pl.lit(False).alias("requires_fi_scalar"))

    # Step 1: Apply per-exposure-class PD floor (CRR: uniform, Basel 3.1: differentiated)
    has_transactor = "is_qrre_transactor" in schema_names
    pd_floor_expr = _pd_floor_expression(config, has_transactor_col=has_transactor)
    exposures = exposures.with_columns(
        pl.max_horizontal(pl.col("pd"), pd_floor_expr).alias("pd_floored")
    )

    # Step 2: Apply LGD floor (Basel 3.1 A-IRB only, CRR has no LGD floors)
    # LGD floors only apply to A-IRB own-estimate LGDs (CRE30.41).
    # F-IRB supervisory LGDs are regulatory values and don't need flooring.
    if config.is_basel_3_1:
        has_collateral_type = "collateral_type" in schema_names
        has_seniority = "seniority" in schema_names
        if has_collateral_type:
            lgd_floor_expr = _lgd_floor_expression_with_collateral(
                config, has_seniority=has_seniority
            )
        else:
            lgd_floor_expr = _lgd_floor_expression(config, has_seniority=has_seniority)
        is_airb = pl.col("is_airb").fill_null(False) if "is_airb" in schema_names else pl.lit(False)
        floored_lgd = pl.max_horizontal(pl.col("lgd"), lgd_floor_expr)
        exposures = exposures.with_columns(
            pl.when(is_airb).then(floored_lgd).otherwise(pl.col("lgd")).alias("lgd_floored")
        )
    else:
        exposures = exposures.with_columns(pl.col("lgd").alias("lgd_floored"))

    # Step 3: Calculate correlation using pure Polars expressions
    # Pass EUR/GBP rate from config to convert GBP turnover to EUR for SME adjustment
    eur_gbp_rate = float(config.eur_gbp_rate)
    exposures = exposures.with_columns(
        _polars_correlation_expr(eur_gbp_rate=eur_gbp_rate).alias("correlation")
    )

    # Step 4: Calculate K using pure Polars with polars-normal-stats
    exposures = exposures.with_columns(_polars_capital_k_expr().alias("k"))

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
    exposures = exposures.with_columns(
        [
            pl.lit(scaling_factor).alias("scaling_factor"),
            (
                pl.col("k")
                * 12.5
                * scaling_factor
                * pl.col("ead_final")
                * pl.col("maturity_adjustment")
            ).alias("rwa"),
            (pl.col("k") * 12.5 * scaling_factor * pl.col("maturity_adjustment")).alias(
                "risk_weight"
            ),
            (pl.col("pd_floored") * pl.col("lgd_floored") * pl.col("ead_final")).alias(
                "expected_loss"
            ),
        ]
    )

    # Step 10: Override for defaulted exposures (CRR Art. 153(1)(ii) / 154(1)(i))
    schema = exposures.collect_schema()
    if "is_defaulted" in schema.names():
        is_defaulted = pl.col("is_defaulted").fill_null(False)

        # Determine A-IRB flag
        is_airb = (
            pl.col("is_airb").fill_null(False) if "is_airb" in schema.names() else pl.lit(False)
        )

        # BEEL column
        beel = pl.col("beel").fill_null(0.0) if "beel" in schema.names() else pl.lit(0.0)

        # Scaling for defaulted: CRR 1.06 for non-retail, 1.0 for retail
        defaulted_scaling = pl.when(is_retail).then(pl.lit(1.0)).otherwise(pl.lit(scaling_factor))

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

        exposures = exposures.with_columns(
            [
                pl.when(is_defaulted).then(k_defaulted).otherwise(pl.col("k")).alias("k"),
                pl.when(is_defaulted)
                .then(pl.lit(0.0))
                .otherwise(pl.col("correlation"))
                .alias("correlation"),
                pl.when(is_defaulted)
                .then(pl.lit(1.0))
                .otherwise(pl.col("maturity_adjustment"))
                .alias("maturity_adjustment"),
                pl.when(is_defaulted).then(rwa_defaulted).otherwise(pl.col("rwa")).alias("rwa"),
                pl.when(is_defaulted)
                .then(rw_defaulted)
                .otherwise(pl.col("risk_weight"))
                .alias("risk_weight"),
                pl.when(is_defaulted)
                .then(el_defaulted)
                .otherwise(pl.col("expected_loss"))
                .alias("expected_loss"),
            ]
        )

    return exposures


# =============================================================================
# PURE POLARS EXPRESSION FUNCTIONS
# =============================================================================


def _correlation_expr_from_pd(
    pd_expr: pl.Expr,
    sme_threshold: float = 50.0,
    eur_gbp_rate: float = 0.8732,
) -> pl.Expr:
    """
    Shared correlation expression accepting an arbitrary PD expression.

    Supports all exposure classes with proper correlation formulas:
    - Corporate/Institution/Sovereign: PD-dependent (decay=50)
    - Retail mortgage: Fixed 0.15
    - QRRE: Fixed 0.04
    - Other retail: PD-dependent (decay=35)

    Includes:
    - SME firm size adjustment for corporates (turnover converted from GBP to EUR)
    - FI scalar (1.25x) for large/unregulated financial sector entities (CRR Art. 153(2))

    Reads exposure_class, turnover_m, requires_fi_scalar columns from the LazyFrame.

    Args:
        pd_expr: Polars expression for the PD value to use
        sme_threshold: SME threshold in EUR millions (default 50.0)
        eur_gbp_rate: EUR/GBP exchange rate for converting GBP turnover to EUR (default 0.8732)
    """
    exp_class = pl.col("exposure_class").cast(pl.String).fill_null("CORPORATE").str.to_uppercase()

    # Pre-calculate decay denominators (constants)
    corporate_denom = 1.0 - math.exp(-50.0)
    retail_denom = 1.0 - math.exp(-35.0)

    # f(PD) for corporate (decay = 50)
    f_pd_corp = (1.0 - (-50.0 * pd_expr).exp()) / corporate_denom

    # f(PD) for retail (decay = 35)
    f_pd_retail = (1.0 - (-35.0 * pd_expr).exp()) / retail_denom

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
    turnover_float = pl.col("turnover_m").cast(pl.Float64)
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
        pl.when(is_corporate & is_sme).then(r_corporate - sme_adjustment).otherwise(r_corporate)
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
    # Per CRR Article 153(2)
    fi_scalar = (
        pl.when(pl.col("requires_fi_scalar").fill_null(False) == True)  # noqa: E712
        .then(pl.lit(1.25))
        .otherwise(pl.lit(1.0))
    )

    return base_correlation * fi_scalar


def _polars_correlation_expr(
    sme_threshold: float = 50.0,
    eur_gbp_rate: float = 0.8732,
) -> pl.Expr:
    """
    Pure Polars expression for correlation calculation using pd_floored column.

    Thin wrapper around ``_correlation_expr_from_pd`` that reads ``pl.col("pd_floored")``.

    Args:
        sme_threshold: SME threshold in EUR millions (default 50.0)
        eur_gbp_rate: EUR/GBP exchange rate for converting GBP turnover to EUR (default 0.8732)
    """
    return _correlation_expr_from_pd(pl.col("pd_floored"), sme_threshold, eur_gbp_rate)


def _capital_k_expr_from_params(
    pd_expr: pl.Expr,
    lgd_expr: pl.Expr,
    correlation_expr: pl.Expr,
) -> pl.Expr:
    """
    Shared K formula accepting arbitrary PD, LGD, and correlation expressions.

    K = LGD × N[(1-R)^(-0.5) × G(PD) + (R/(1-R))^(0.5) × G(0.999)] - PD × LGD

    Uses polars-normal-stats for normal_cdf and normal_ppf functions.

    Args:
        pd_expr: Polars expression for PD (will be clipped to [1e-10, 0.9999])
        lgd_expr: Polars expression for LGD
        correlation_expr: Polars expression for asset correlation
    """
    pd_safe = pd_expr.clip(1e-10, 0.9999)

    # G(PD) = inverse normal CDF of PD
    g_pd = normal_ppf(pd_safe)

    # Calculate conditional default probability terms
    one_minus_r = 1.0 - correlation_expr
    term1 = (1.0 / one_minus_r).sqrt() * g_pd
    term2 = (correlation_expr / one_minus_r).sqrt() * G_999

    # Conditional PD = N(term1 + term2)
    conditional_pd = normal_cdf(term1 + term2)

    # K = LGD × conditional_pd - PD × LGD
    k = lgd_expr * conditional_pd - pd_safe * lgd_expr

    # Floor at 0
    return pl.max_horizontal(k, pl.lit(0.0))


def _polars_capital_k_expr() -> pl.Expr:
    """
    Pure Polars expression for K using pd_floored, lgd_floored, correlation columns.

    Thin wrapper around ``_capital_k_expr_from_params``.
    """
    return _capital_k_expr_from_params(
        pl.col("pd_floored"), pl.col("lgd_floored"), pl.col("correlation")
    )


def _maturity_adjustment_expr_from_pd(
    pd_expr: pl.Expr,
    maturity_floor: float = 1.0,
    maturity_cap: float = 5.0,
) -> pl.Expr:
    """
    Shared maturity adjustment expression accepting an arbitrary PD expression.

    b = (0.11852 - 0.05478 × ln(PD))²
    MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)

    Retail exposures should have MA=1.0 applied externally (this function
    does not check exposure class).

    Args:
        pd_expr: Polars expression for PD
        maturity_floor: Minimum maturity in years (default 1.0)
        maturity_cap: Maximum maturity in years (default 5.0)
    """
    m = pl.col("maturity").clip(maturity_floor, maturity_cap)

    # Safe PD for log calculation
    pd_safe = pd_expr.clip(lower_bound=1e-10)

    # b = (0.11852 - 0.05478 × ln(PD))²
    b = (0.11852 - 0.05478 * pd_safe.log()) ** 2

    # MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
    return (1.0 + (m - 2.5) * b) / (1.0 - 1.5 * b)


def _polars_maturity_adjustment_expr(
    maturity_floor: float = 1.0,
    maturity_cap: float = 5.0,
) -> pl.Expr:
    """
    Pure Polars expression for maturity adjustment using pd_floored column.

    Thin wrapper around ``_maturity_adjustment_expr_from_pd``.
    """
    return _maturity_adjustment_expr_from_pd(
        pl.col("pd_floored"), maturity_floor, maturity_cap
    )


# =============================================================================
# DOUBLE DEFAULT TREATMENT (CRR Art. 153(3), Basel II para 284-286)
# =============================================================================


def _double_default_multiplier_expr(guarantor_pd_expr: pl.Expr) -> pl.Expr:
    """
    Double default multiplier per CRR Art. 153(3) / Basel II para 284.

    K_dd = K_obligor × (0.15 + 160 × PD_g)

    The multiplier (0.15 + 160 × PD_g) reduces the capital charge by accounting
    for the joint probability that both obligor and guarantor default. For a
    high-quality guarantor (PD_g = 0.03%), the multiplier ≈ 0.198, providing
    ~80% capital relief vs standard substitution.

    Args:
        guarantor_pd_expr: Polars expression for the guarantor's PD (floored)

    Returns:
        Expression computing the double default multiplier (0.15 + 160 × PD_g)
    """
    return pl.lit(0.15) + pl.lit(160.0) * guarantor_pd_expr


def calculate_double_default_k(
    k_obligor: float,
    guarantor_pd: float,
) -> float:
    """
    Scalar double default K calculation.

    K_dd = K_obligor × (0.15 + 160 × PD_g)

    Args:
        k_obligor: Standard IRB K for the obligor (pre-guarantee)
        guarantor_pd: PD of the protection provider (floored)

    Returns:
        Capital requirement under double default treatment
    """
    multiplier = 0.15 + 160.0 * guarantor_pd
    return k_obligor * multiplier


# =============================================================================
# PARAMETRIC IRB RISK WEIGHT (for guarantee parameter substitution)
# =============================================================================


def _parametric_irb_risk_weight_expr(
    pd_expr: pl.Expr,
    lgd: float,
    scaling_factor: float = 1.0,
    eur_gbp_rate: float = 0.8732,
) -> pl.Expr:
    """
    Compute IRB risk weight from arbitrary PD expression and fixed LGD.

    Used for Basel 3.1 parameter substitution (CRE22.70-85): when an IRB
    exposure is guaranteed by an F-IRB counterparty, the guaranteed portion
    uses the guarantor's PD and F-IRB supervisory LGD instead of the
    borrower's parameters.

    Reads exposure_class, turnover_m, maturity, requires_fi_scalar columns
    from the LazyFrame. PD and LGD are substituted externally.

    Args:
        pd_expr: Polars expression for the substituted PD (e.g. guarantor PD, floored)
        lgd: Fixed LGD value (e.g. F-IRB supervisory unsecured senior)
        scaling_factor: 1.06 for CRR, 1.0 for Basel 3.1
        eur_gbp_rate: EUR/GBP rate for SME turnover conversion

    Returns:
        Expression computing risk_weight = K × 12.5 × scaling × MA
    """
    correlation = _correlation_expr_from_pd(pd_expr, eur_gbp_rate=eur_gbp_rate)
    k = _capital_k_expr_from_params(pd_expr, pl.lit(lgd), correlation)
    ma = _maturity_adjustment_expr_from_pd(pd_expr)

    # Retail: no maturity adjustment (MA = 1.0)
    exp_class = pl.col("exposure_class").cast(pl.String).fill_null("CORPORATE").str.to_uppercase()
    is_retail = (
        exp_class.str.contains("RETAIL")
        | exp_class.str.contains("MORTGAGE")
        | exp_class.str.contains("QRRE")
    )
    ma = pl.when(is_retail).then(pl.lit(1.0)).otherwise(ma)

    return k * 12.5 * scaling_factor * ma


# =============================================================================
# CORRELATION PARAMETERS (for scalar functions)
# =============================================================================


@dataclass(frozen=True)
class CorrelationParams:
    """Parameters for asset correlation calculation."""

    correlation_type: str  # "fixed" or "pd_dependent"
    r_min: float  # Minimum correlation (at high PD)
    r_max: float  # Maximum correlation (at low PD)
    fixed: float  # Fixed correlation value
    decay_factor: float  # K factor in formula (50 for corp, 35 for retail)


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

    result: pl.DataFrame = lf.with_columns(expr.alias(output_col)).collect()
    return float(result[output_col][0])


# =============================================================================
# SCALAR CALCULATIONS (wrappers around vectorized expressions)
# =============================================================================



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

    ma = calculate_maturity_adjustment(pd_floored, maturity) if apply_maturity_adjustment else 1.0

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
