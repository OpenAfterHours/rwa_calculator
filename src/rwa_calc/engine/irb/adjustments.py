"""
Post-formula adjustments for IRB calculations.

Pipeline position:
    IRB formulas -> Adjustments -> Guarantee substitution

Key responsibilities:
- Defaulted exposure treatment (CRR Art. 153(1)(ii) / 154(1)(i), Basel CRE31.3)
- Post-model adjustments for known model deficiencies (Basel 3.1 PRA PS9/24)
- EL shortfall/excess comparison against provisions (CRR Art. 158-159)

References:
- CRR Art. 153(1)(ii), 154(1)(i): Defaulted exposure treatment
- PRA PS9/24 Art. 153(5A), 154(4A), 158(6A): Post-model adjustments
- CRR Art. 158-159: EL shortfall treatment
- CRR Art. 62(d): Excess provisions as T2 capital (capped)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.errors import (
    ERROR_MISSING_EXPECTED_LOSS,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# DEFAULTED EXPOSURE TREATMENT
# =============================================================================


def apply_defaulted_treatment(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """
    Apply regulatory treatment for defaulted exposures (PD=100%).

    Per CRR Art. 153(1)(ii) / 154(1)(i) and Basel CRE31.3, defaulted
    exposures bypass the Vasicek formula entirely:
    - F-IRB: K=0, RW=0 (capital held via provisions)
    - A-IRB: K = max(0, LGD_in_default - BEEL)

    Expected loss for defaulted exposures:
    - F-IRB: EL = LGD × EAD (supervisory LGD)
    - A-IRB: EL = BEEL × EAD (best estimate)

    Runs after calculate_expected_loss (so all standard columns exist)
    and before apply_guarantee_substitution.

    Args:
        lf: LazyFrame with IRB formula results
        config: Calculation configuration

    Returns:
        LazyFrame with defaulted rows overwritten
    """
    schema = lf.collect_schema()
    cols = schema.names()

    # No-op if is_defaulted column doesn't exist
    if "is_defaulted" not in cols:
        return lf

    is_defaulted = pl.col("is_defaulted").fill_null(False)

    # Determine scaling: CRR 1.06 for non-retail, 1.0 for retail; Basel 3.1 always 1.0
    is_retail = (
        pl.col("exposure_class")
        .cast(pl.String)
        .fill_null("CORPORATE")
        .str.to_uppercase()
        .str.contains("RETAIL")
    )

    if config.is_crr:
        scaling = pl.when(is_retail).then(pl.lit(1.0)).otherwise(pl.lit(1.06))
    else:
        scaling = pl.lit(1.0)

    # Ensure beel column exists (default 0.0)
    if "beel" not in cols:
        lf = lf.with_columns([pl.lit(0.0).alias("beel")])

    beel = pl.col("beel").fill_null(0.0)

    # K for defaulted: A-IRB = max(0, lgd_floored - beel), F-IRB = 0
    is_airb = pl.col("is_airb").fill_null(False) if "is_airb" in cols else pl.lit(False)
    k_defaulted = (
        pl.when(is_airb)
        .then(pl.max_horizontal(pl.lit(0.0), pl.col("lgd_floored") - beel))
        .otherwise(pl.lit(0.0))
    )

    # RWA = K × 12.5 × scaling × EAD (no maturity adjustment for defaulted)
    rwa_defaulted = k_defaulted * 12.5 * scaling * pl.col("ead_final")

    # Risk weight = K × 12.5 × scaling
    rw_defaulted = k_defaulted * 12.5 * scaling

    # Expected loss: A-IRB = BEEL × EAD, F-IRB = LGD × EAD
    el_defaulted = (
        pl.when(is_airb)
        .then(beel * pl.col("ead_final"))
        .otherwise(pl.col("lgd_floored") * pl.col("ead_final"))
    )

    # Override only defaulted rows
    return lf.with_columns(
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


# =============================================================================
# POST-MODEL ADJUSTMENTS (Basel 3.1)
# =============================================================================


def apply_post_model_adjustments(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """
    Apply post-model adjustments to IRB RWEA and EL (Basel 3.1 only).

    PRA PS9/24 Art. 153(5A), 154(4A), 158(6A) require firms to apply
    adjustments for known model deficiencies. Three RWEA components:

    1. Mortgage RW floor: min risk weight for residential mortgage exposures
    2. General PMA: scalar add-on to post-floor RWEA (supervisory requirement)
    3. Unrecognised exposure: scalar for model coverage gaps

    Adjustment sequencing per Art. 154(4A):
        (b) Mortgage RW floor applied first — establishes post-floor RWEA base
        (a) General PMA and unrecognised scalars applied to post-floor RWEA

    This ordering matters: PMA scalars must capture the mortgage floor
    increase in their base, otherwise capital is understated for
    exposures that hit the floor.

    EL adjustment mirrors the general PMA scalar, floored at zero
    per Art. 158(6A) — PMAs cannot decrease expected loss.

    Under CRR, no adjustments are applied (returns frame unchanged).

    Produces columns:
        rwa_pre_adjustments: RWEA before any PMAs
        post_model_adjustment_rwa: General PMA RWEA add-on
        mortgage_rw_floor_adjustment: RWEA increase from mortgage floor
        unrecognised_exposure_adjustment: RWEA increase for unrecognised exposures
        el_pre_adjustment: EL before PMAs
        post_model_adjustment_el: General PMA EL add-on (floored at 0)
        el_after_adjustment: EL after all PMAs

    Args:
        lf: LazyFrame with IRB formula results
        config: Calculation configuration

    Returns:
        LazyFrame with post-model adjustment columns
    """
    pma_config = config.post_model_adjustments

    if not pma_config.enabled:
        # CRR or disabled: add zero-valued columns for schema consistency
        return lf.with_columns(
            [
                pl.col("rwa").alias("rwa_pre_adjustments"),
                pl.lit(0.0).alias("post_model_adjustment_rwa"),
                pl.lit(0.0).alias("mortgage_rw_floor_adjustment"),
                pl.lit(0.0).alias("unrecognised_exposure_adjustment"),
                pl.col("expected_loss").alias("el_pre_adjustment"),
                pl.lit(0.0).alias("post_model_adjustment_el"),
                pl.col("expected_loss").alias("el_after_adjustment"),
            ]
        )

    schema = lf.collect_schema()
    cols = schema.names()

    pma_rwa_scalar = float(pma_config.pma_rwa_scalar)
    pma_el_scalar = float(pma_config.pma_el_scalar)
    mortgage_rw_floor = float(pma_config.mortgage_rw_floor)
    unrecognised_scalar = float(pma_config.unrecognised_exposure_scalar)

    # Mortgage RW floor: applies to residential mortgage IRB exposures
    # Adjustment = max(0, floor_rw - modelled_rw) × EAD × 12.5
    is_mortgage = (
        pl.col("exposure_class")
        .cast(pl.String)
        .fill_null("")
        .str.to_uppercase()
        .str.contains("MORTGAGE|RESIDENTIAL")
    )

    rw_col = "risk_weight" if "risk_weight" in cols else None
    if rw_col and mortgage_rw_floor > 0:
        # Floor adjustment: excess of floor RW over modelled RW, converted to RWEA
        floor_rw_increase = pl.max_horizontal(
            pl.lit(0.0),
            pl.lit(mortgage_rw_floor) - pl.col(rw_col),
        )
        mortgage_adj_expr = (
            pl.when(is_mortgage)
            .then(floor_rw_increase * pl.col("ead_final"))
            .otherwise(pl.lit(0.0))
        )
    else:
        mortgage_adj_expr = pl.lit(0.0)

    # EL column detection
    el_col = "expected_loss" if "expected_loss" in cols else None

    # Step 1: Record pre-adjustment values and apply mortgage floor
    # Art. 154(4A)(b) mortgage floor is applied FIRST to establish the post-floor RWEA base
    lf = lf.with_columns(
        [
            pl.col("rwa").alias("rwa_pre_adjustments"),
            mortgage_adj_expr.alias("mortgage_rw_floor_adjustment"),
        ]
    )

    # Apply mortgage floor to RWA — creates the post-floor RWEA base
    lf = lf.with_columns((pl.col("rwa") + pl.col("mortgage_rw_floor_adjustment")).alias("rwa"))

    # Step 2: Apply PMA and unrecognised scalars to POST-FLOOR RWEA
    # Art. 154(4A)(a) / Art. 153(5A): scalars multiply the RWEA that already includes
    # the mortgage floor increase, so the floor portion is also captured in the PMA base.
    general_pma_expr = pl.col("rwa") * pma_rwa_scalar
    unrecognised_expr = pl.col("rwa") * unrecognised_scalar

    lf = lf.with_columns(
        [
            general_pma_expr.alias("post_model_adjustment_rwa"),
            unrecognised_expr.alias("unrecognised_exposure_adjustment"),
        ]
    )

    # Apply PMA and unrecognised adjustments to RWA
    lf = lf.with_columns(
        (
            pl.col("rwa")
            + pl.col("post_model_adjustment_rwa")
            + pl.col("unrecognised_exposure_adjustment")
        ).alias("rwa")
    )

    # Step 3: EL adjustments — Art. 158(6A) requires PMAs cannot decrease EL
    if el_col:
        el_pma_expr = pl.max_horizontal(pl.lit(0.0), pl.col(el_col) * pma_el_scalar)
        lf = lf.with_columns(
            [
                pl.col(el_col).alias("el_pre_adjustment"),
                el_pma_expr.alias("post_model_adjustment_el"),
                (pl.col(el_col) + el_pma_expr).alias("el_after_adjustment"),
            ]
        )
    else:
        lf = lf.with_columns(
            [
                pl.lit(0.0).alias("el_pre_adjustment"),
                pl.lit(0.0).alias("post_model_adjustment_el"),
                pl.lit(0.0).alias("el_after_adjustment"),
            ]
        )

    return lf


# =============================================================================
# EL SHORTFALL / EXCESS
# =============================================================================


def compute_el_shortfall_excess(
    lf: pl.LazyFrame,
    errors: list[CalculationError] | None = None,
) -> pl.LazyFrame:
    """
    Compute EL shortfall and excess for IRB exposures.

    Compares expected loss against Art. 159(1) Pool B to determine
    whether the bank has a shortfall (EL > Pool B) or excess
    (Pool B > EL). Shortfall reduces CET1/T2; excess may be
    added to T2 capital (subject to 0.6% IRB RWA cap).

    Pool B per Art. 159(1) includes:
        (a) General credit risk adjustments (GCRA)
        (b) Specific credit risk adjustments (SCRA) for non-defaulted
        (c) Additional value adjustments (AVAs per Art. 34)
        (d) Other own funds reductions

    Components (a) and (b) are captured via ``provision_allocated``.
    Components (c) and (d) are captured via ``ava_amount`` and
    ``other_own_funds_reductions`` respectively.

    Requires ``expected_loss`` to be computed first. If
    ``provision_allocated`` is absent (no provisions in the input),
    shortfall equals the full EL and excess is zero.

    Produces:
        el_shortfall: max(0, expected_loss - pool_b)
        el_excess:    max(0, pool_b - expected_loss)

    References:
        CRR Art. 158-159: EL shortfall treatment
        CRR Art. 159(1): Pool B composition (provisions + AVA + other)
        CRR Art. 34, Art. 105: Additional value adjustments
        CRR Art. 62(d): Excess provisions as T2 capital (capped)
        CRE35.1-3: Basel 3.1 expected loss calculation
    """
    schema = lf.collect_schema()
    cols = schema.names()

    if "expected_loss" not in cols:
        if errors is not None:
            errors.append(
                CalculationError(
                    code=ERROR_MISSING_EXPECTED_LOSS,
                    message=(
                        "expected_loss column absent — EL shortfall/excess defaulted "
                        "to zero. T2 credit cap and CET1 deduction may be affected."
                    ),
                    severity=ErrorSeverity.WARNING,
                    category=ErrorCategory.DATA_QUALITY,
                    field_name="expected_loss",
                    regulatory_reference="CRR Art. 158-159",
                )
            )
        return lf.with_columns(
            [
                pl.lit(0.0).alias("el_shortfall"),
                pl.lit(0.0).alias("el_excess"),
            ]
        )

    el = pl.col("expected_loss").fill_null(0.0)

    if "provision_allocated" in cols:
        prov = pl.col("provision_allocated").fill_null(0.0)
    else:
        # No provisions resolved — full EL is shortfall
        prov = pl.lit(0.0)

    # Art. 159(1)(c): Additional value adjustments (AVAs per Art. 34)
    ava = pl.col("ava_amount").fill_null(0.0) if "ava_amount" in cols else pl.lit(0.0)
    # Art. 159(1)(d): Other own funds reductions
    other_ofr = (
        pl.col("other_own_funds_reductions").fill_null(0.0)
        if "other_own_funds_reductions" in cols
        else pl.lit(0.0)
    )

    # Pool B = provisions + AVA + other own funds reductions
    pool_b = prov + ava + other_ofr

    return lf.with_columns(
        [
            pl.max_horizontal(pl.lit(0.0), el - pool_b).alias("el_shortfall"),
            pl.max_horizontal(pl.lit(0.0), pool_b - el).alias("el_excess"),
        ]
    )
