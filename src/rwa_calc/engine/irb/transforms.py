"""
IRB calculation transforms over Polars LazyFrames and expressions.

Plain typed functions implementing the IRB RWA pipeline — approach
classification, F-IRB supervisory LGD, the maturity priority chain, PD/LGD
floors, correlation, capital requirement (K), maturity adjustment, RWA,
expected loss, defaulted treatment, post-model adjustments, EL
shortfall/excess and guarantee substitution. ``IRBCalculator`` composes them
via ``LazyFrame.pipe``; tests call them directly.

Uses pure Polars expressions with polars-normal-stats for statistical
functions, enabling full lazy evaluation, query optimization, and streaming.

Pipeline position:
    CRMProcessor -> IRBCalculator -> Aggregation

Usage:
    import polars as pl
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.engine.irb.transforms import (
        apply_all_formulas,
        apply_firb_lgd,
        classify_approach,
        prepare_columns,
    )

    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    result = (
        lf.pipe(classify_approach, config)
        .pipe(apply_firb_lgd, config)
        .pipe(prepare_columns, config)
        .pipe(apply_all_formulas, config)
    )

References:
- CRR Art. 153-154: IRB risk weight functions
- CRR Art. 161: F-IRB supervisory LGD
- CRR Art. 162-163: Maturity and PD floors
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.tables.firb_lgd import get_firb_lgd_table_for_framework
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.irb.adjustments import (
    apply_defaulted_treatment as _apply_defaulted_treatment,
)
from rwa_calc.engine.irb.adjustments import (
    apply_post_model_adjustments as _apply_post_model_adjustments,
)
from rwa_calc.engine.irb.adjustments import (
    compute_el_shortfall_excess as _compute_el_shortfall_excess,
)
from rwa_calc.engine.irb.formulas import (
    _lgd_floor_blended_expression,
    _lgd_floor_expression,
    _lgd_floor_expression_with_collateral,
    _pd_floor_expression,
    _polars_capital_k_expr,
    _polars_correlation_expr,
    _polars_maturity_adjustment_expr,
)
from rwa_calc.engine.irb.guarantee import (
    apply_guarantee_substitution as _apply_guarantee_substitution,  # noqa: E501
)
from rwa_calc.engine.utils import (
    exact_fractional_years_expr as _exact_fractional_years_expr,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError

logger = logging.getLogger(__name__)


# =============================================================================
# MODULE CONSTANTS
# =============================================================================

# Repeated audit-string fragment (S1192).
_AUDIT_LGD_LABEL = "%, LGD="

# Art. 162(3) carve-out: one-day maturity floor expressed in years.
_ONE_DAY_YEARS = 1.0 / 365.0


# =============================================================================
# SETUP / CLASSIFICATION TRANSFORMS
# =============================================================================


def classify_approach(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """
    Classify exposures as F-IRB or A-IRB.

    Adds columns:
    - approach: The IRB approach (foundation_irb or advanced_irb)
    - is_airb: Boolean flag for A-IRB exposures

    Args:
        lf: IRB exposures frame
        config: Calculation configuration

    Returns:
        LazyFrame with approach classification
    """
    lf = ensure_columns(
        lf,
        {"approach": ColumnSpec(pl.String, default=ApproachType.FIRB.value, required=False)},
    )
    return lf.with_columns(
        [
            (pl.col("approach") == ApproachType.AIRB.value).alias("is_airb"),
        ]
    )


def apply_firb_lgd(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """
    Apply F-IRB supervisory LGD for Foundation IRB exposures.

    CRR Art. 161(1)(a): Senior unsecured 45%, subordinated 75%
    Basel 3.1 Art. 161(1)(a)/(aa): FSE senior 45%, non-FSE senior 40%, sub 75%

    For F-IRB exposures with collateral, the CRM processor calculates
    the effective LGD (lgd_post_crm) based on collateral type and coverage.
    This function uses lgd_post_crm as the input LGD for risk weight calculation.

    A-IRB exposures retain their own LGD estimates.

    Args:
        lf: IRB exposures frame
        config: Calculation configuration

    Returns:
        LazyFrame with F-IRB LGD applied
    """
    # Use framework-appropriate supervisory LGD values
    lgd_table = get_firb_lgd_table_for_framework(config.is_basel_3_1)
    default_lgd = float(lgd_table["unsecured_senior"])
    sub_lgd = float(lgd_table["subordinated"])

    # PRA PS1/26 / CRR Art. 161(1)(e)/(f)/(g): purchased-receivables sub-type LGDs.
    # Takes precedence over the seniority-based selector when populated.
    pr_senior_lgd = float(lgd_table["purchased_receivables_senior"])
    pr_sub_lgd = float(lgd_table["purchased_receivables_subordinated"])
    pr_dilution_lgd = float(lgd_table["dilution_risk"])

    # Under Basel 3.1, FSE senior unsecured = 45% (Art. 161(1)(a));
    # non-FSE = 40% (Art. 161(1)(aa)). Under CRR, all = 45%.
    if config.is_basel_3_1:
        fse_lgd = float(lgd_table["unsecured_senior_fse"])
        default_lgd_expr = (
            pl.when(pl.col("cp_is_financial_sector_entity").fill_null(False))
            .then(pl.lit(fse_lgd))
            .otherwise(pl.lit(default_lgd))
        )
    else:
        default_lgd_expr = pl.lit(default_lgd)

    # Build the seniority-based supervisory LGD expression (used both as the
    # F-IRB fallback for null lgd and as the override base for purchased
    # receivables routing below).
    seniority_based_lgd_expr = (
        pl.when(pl.col("seniority").fill_null("senior").str.to_lowercase().str.contains("sub"))
        .then(pl.lit(sub_lgd))
        .otherwise(default_lgd_expr)
    )

    # Art. 161(1)(e)/(f)/(g) routing: when purchased_receivables_subtype is set
    # the engine MUST dispatch via the subtype (not via seniority), because
    # subordinated purchased receivables (100%) and dilution risk (100% B3.1
    # / 75% CRR) deviate from the standard subordinated (75%) and senior
    # (40%/45%) supervisory LGDs respectively.
    pr_subtype = pl.col("purchased_receivables_subtype")
    firb_lgd_expr = (
        pl.when(pr_subtype == "senior")
        .then(pl.lit(pr_senior_lgd))
        .when(pr_subtype == "subordinated")
        .then(pl.lit(pr_sub_lgd))
        .when(pr_subtype == "dilution_risk")
        .then(pl.lit(pr_dilution_lgd))
        .otherwise(seniority_based_lgd_expr)
    )

    lf = lf.with_columns(
        [
            pl.when((pl.col("approach") == ApproachType.FIRB.value) & pl.col("lgd").is_null())
            .then(firb_lgd_expr)
            .otherwise(pl.col("lgd").fill_null(default_lgd))
            .alias("lgd"),
        ]
    )

    # For lgd_input, use lgd_post_crm (from CRM processor).
    # This ensures collateral-adjusted LGD is used for F-IRB risk weight calculation.
    # Purchased-receivables sub-type LGDs (Art. 161(1)(e)/(f)/(g)) override the
    # CRM-derived lgd_post_crm because they are unsecured supervisory rates that
    # do not benefit from generic seniority/collateral adjustments.
    lgd_input_expr = (
        pl.when((pl.col("approach") == ApproachType.FIRB.value) & pr_subtype.is_not_null())
        .then(pl.col("lgd"))
        .when(pl.col("approach") == ApproachType.FIRB.value)
        .then(pl.col("lgd_post_crm"))
        .otherwise(pl.col("lgd"))
    )
    return lf.with_columns([lgd_input_expr.alias("lgd_input")])


def prepare_columns(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """
    Ensure all required columns exist with defaults.

    Single schema check followed by one with_columns() for all defaults.

    Args:
        lf: IRB exposures frame
        config: Calculation configuration

    Returns:
        LazyFrame with all required columns
    """
    # Maturity priority chain (highest wins) — see ``_build_maturity_exprs``:
    #   1. effective_maturity input populated → firm override, clipped [1 day, 5y]
    #   2. has_one_day_maturity_floor flag → M = 1/365 (Art. 162(3) carve-out:
    #      daily-margined SFTs/derivatives/margin lending, short-term trade)
    #   3. Basel 3.1 revolving + facility_termination_date (Art. 162(2A)(k))
    #   4. maturity_date standard derivation, clipped [1y, 5y]
    #   5. Fallback default 2.5y
    # CRR F-IRB SFT supervisory M = 0.5y (Art. 162(1)) is applied to the base
    # chain (4/3) but is superseded by the two explicit overrides above.
    names = set(lf.collect_schema().names())
    exprs = _prepare_columns_exprs(config, names)
    if exprs:
        return lf.with_columns(exprs)
    return lf


# =============================================================================
# INDIVIDUAL FORMULA STEPS
# =============================================================================


@cites("CRR Art. 163")
@cites("PS1/26, paragraph 163")
def apply_pd_floor(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """
    Apply PD floor based on configuration.

    CRR (Art. 163): 0.03% for all classes
    Basel 3.1 (CRE30.55): Differentiated by class
        - Corporate/SME: 0.05%
        - Retail mortgage: 0.05%
        - QRRE revolvers: 0.10%, transactors: 0.03%
        - Retail other: 0.05%

    Args:
        lf: IRB exposures frame
        config: Calculation configuration

    Returns:
        LazyFrame with pd_floored column
    """
    pd_floor_expr = _pd_floor_expression(config)
    return lf.with_columns(pl.max_horizontal(pl.col("pd"), pd_floor_expr).alias("pd_floored"))


@cites("CRR Art. 164")
@cites("PS1/26, paragraph 164")
def apply_lgd_floor(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """
    Apply LGD floor for Basel 3.1 A-IRB exposures.

    Uses lgd_input (which contains collateral-adjusted LGD for F-IRB)
    as the base for flooring.

    CRR: No LGD floor (A-IRB models LGD freely)
    Basel 3.1: Differentiated floors by collateral type and exposure class:
        - Corporate unsecured (senior & subordinated): 25% (Art. 161(5))
        - Retail QRRE unsecured: 50% (Art. 164(4)(b)(i))
        - Financial: 0%, Receivables: 10%
        - RRE: 10%, CRE: 10%, Other physical: 15%

    LGD floors only apply to A-IRB own-estimate LGDs. F-IRB supervisory
    LGDs are regulatory values and don't need flooring.

    Args:
        lf: IRB exposures frame
        config: Calculation configuration

    Returns:
        LazyFrame with lgd_floored column
    """
    schema = lf.collect_schema()
    schema_names = schema.names()
    lgd_col = "lgd_input" if "lgd_input" in schema_names else "lgd"

    if config.is_basel_3_1:
        if "collateral_type" in schema_names:
            lgd_floor_expr = _lgd_floor_expression_with_collateral(
                config,
                has_seniority=True,
                has_exposure_class=True,
            )
        else:
            lgd_floor_expr = _lgd_floor_expression(
                config,
                has_seniority=True,
                has_exposure_class=True,
            )

        # Art. 164(4)(c) blended floor for retail with mixed collateral
        # Use blended floor where applicable (retail_other/qrre with collateral),
        # fall back to single-type floor otherwise
        blended_expr = _lgd_floor_blended_expression(config)
        lgd_floor_expr = (
            pl.when(blended_expr.is_not_null()).then(blended_expr).otherwise(lgd_floor_expr)
        )

        # LGD floors only apply to A-IRB (CRE30.41); F-IRB uses supervisory LGD
        is_airb = pl.col("is_airb").fill_null(False) if "is_airb" in schema_names else pl.lit(False)
        floored_lgd = pl.max_horizontal(pl.col(lgd_col), lgd_floor_expr)
        return lf.with_columns(
            pl.when(is_airb).then(floored_lgd).otherwise(pl.col(lgd_col)).alias("lgd_floored")
        )
    return lf.with_columns(pl.col(lgd_col).alias("lgd_floored"))


@cites("CRR Art. 153(1)")
def calculate_correlation(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """
    Calculate asset correlation using pure Polars expressions.

    Supports:
    - Corporate/Institution/Sovereign: PD-dependent (0.12-0.24)
    - Retail mortgage: Fixed 0.15
    - QRRE: Fixed 0.04
    - Other retail: PD-dependent (0.03-0.16)
    - SME adjustment for corporates (turnover converted from GBP to EUR)
    - FI scalar (1.25x) for large/unregulated financial sector entities

    Args:
        lf: IRB exposures frame
        config: Calculation configuration

    Returns:
        LazyFrame with correlation column
    """
    # B31 uses GBP-native thresholds (Art. 153(4)); CRR converts GBP→EUR via rate
    eur_gbp_rate = float(config.eur_gbp_rate)
    sme_turnover_m = float(config.thresholds.sme_turnover_threshold) / 1_000_000
    return lf.with_columns(
        _polars_correlation_expr(
            eur_gbp_rate=eur_gbp_rate,
            is_b31=config.is_basel_3_1,
            sme_turnover_threshold_m=sme_turnover_m,
        ).alias("correlation")
    )


@cites("CRR Art. 153(1)")
def calculate_k(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """
    Calculate capital requirement (K) using pure Polars with polars-normal-stats.

    K = LGD × N[(1-R)^(-0.5) × G(PD) + (R/(1-R))^(0.5) × G(0.999)] - PD × LGD

    Args:
        lf: IRB exposures frame
        config: Calculation configuration

    Returns:
        LazyFrame with k column
    """
    return lf.with_columns(_polars_capital_k_expr().alias("k"))


@cites("CRR Art. 162")
def calculate_maturity_adjustment(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """
    Calculate maturity adjustment for non-retail exposures.

    MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
    where b = (0.11852 - 0.05478 × ln(PD))²

    Retail exposures get MA = 1.0.

    Reads ``has_one_day_maturity_floor`` to gate the 1-year M floor
    (CRR Art. 162(3) carve-out); defaulted to False if absent.

    Args:
        lf: IRB exposures frame
        config: Calculation configuration

    Returns:
        LazyFrame with maturity_adjustment column
    """
    is_retail = (
        pl.col("exposure_class")
        .cast(pl.String)
        .fill_null("CORPORATE")
        .str.to_uppercase()
        .str.contains("RETAIL")
    )

    return lf.with_columns(
        pl.when(is_retail)
        .then(pl.lit(1.0))
        .otherwise(_polars_maturity_adjustment_expr())
        .alias("maturity_adjustment")
    )


def calculate_rwa(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """
    Calculate RWA and related metrics.

    RWA = K × 12.5 × [1.06] × EAD × MA
    Risk weight = K × 12.5 × [1.06] × MA

    The 1.06 scaling factor applies only under CRR.

    Args:
        lf: IRB exposures frame
        config: Calculation configuration

    Returns:
        LazyFrame with rwa, risk_weight, scaling_factor columns
    """
    scaling_factor = 1.06 if config.is_crr else 1.0

    return lf.with_columns(
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
        ]
    )


def calculate_expected_loss(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """
    Calculate expected loss.

    EL = PD × LGD × EAD

    Args:
        lf: IRB exposures frame
        config: Calculation configuration

    Returns:
        LazyFrame with expected_loss column
    """
    return lf.with_columns(
        (pl.col("pd_floored") * pl.col("lgd_floored") * pl.col("ead_final")).alias("expected_loss")
    )


# =============================================================================
# DEFAULTED EXPOSURE TREATMENT
# =============================================================================


def apply_defaulted_treatment(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Apply regulatory treatment for defaulted exposures (PD=100%).

    Delegates to ``adjustments.apply_defaulted_treatment``.
    """
    return _apply_defaulted_treatment(lf)


# =============================================================================
# POST-MODEL ADJUSTMENTS (Basel 3.1)
# =============================================================================


def apply_post_model_adjustments(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Apply post-model adjustments to IRB RWEA and EL (Basel 3.1 only).

    Delegates to ``adjustments.apply_post_model_adjustments``.
    """
    return _apply_post_model_adjustments(lf, config)


# =============================================================================
# EL SHORTFALL / EXCESS
# =============================================================================


def compute_el_shortfall_excess(
    lf: pl.LazyFrame,
    *,
    errors: list[CalculationError] | None = None,
) -> pl.LazyFrame:
    """Compute EL shortfall and excess for IRB exposures.

    Args:
        lf: IRB exposures frame
        errors: Optional error accumulator. Receives a warning if
            ``expected_loss`` column is absent (EL not yet computed).

    Delegates to ``adjustments.compute_el_shortfall_excess``.
    """
    return _compute_el_shortfall_excess(lf, errors=errors)


# =============================================================================
# GUARANTEE SUBSTITUTION
# =============================================================================


def apply_guarantee_substitution(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """Apply guarantee substitution for IRB exposures.

    Delegates to ``guarantee.apply_guarantee_substitution``.
    """
    return _apply_guarantee_substitution(lf, config)


# =============================================================================
# CONVENIENCE / PIPELINE TRANSFORMS
# =============================================================================


def apply_all_formulas(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
    """
    Apply full IRB formula pipeline in 4 batched with_columns.

    Batch 1: PD floor + LGD floor (read only input cols)
    Batch 2: Correlation + maturity adjustment (read pd_floored from batch 1)
    Batch 3: K (reads correlation from batch 2)
    Batch 4: RWA + risk weight + expected loss (read k, maturity_adjustment)
    Then: defaulted treatment override

    Args:
        lf: IRB exposures frame
        config: Calculation configuration

    Returns:
        LazyFrame with all IRB calculations
    """
    schema = lf.collect_schema()
    schema_names = set(schema.names())

    # --- Batch 1: PD floor + LGD floor ---
    batch1: list[pl.Expr] = []

    # Per-exposure-class PD floor (CRR: uniform, Basel 3.1: differentiated)
    pd_floor_expr = _pd_floor_expression(config)
    batch1.append(pl.max_horizontal(pl.col("pd"), pd_floor_expr).alias("pd_floored"))

    # LGD floor (CRR: none, Basel 3.1: per-collateral-type for A-IRB only)
    # F-IRB supervisory LGDs are regulatory values — don't floor them (CRE30.41)
    lgd_col = "lgd_input" if "lgd_input" in schema_names else "lgd"
    batch1.append(_lgd_floored_expr(config, schema_names, lgd_col))

    lf = lf.with_columns(batch1)

    # --- Batch 2: Correlation + maturity adjustment (read pd_floored) ---
    # B31 uses GBP-native thresholds (Art. 153(4)); CRR converts GBP→EUR via rate
    eur_gbp_rate = float(config.eur_gbp_rate)
    sme_turnover_m = float(config.thresholds.sme_turnover_threshold) / 1_000_000
    is_retail = (
        pl.col("exposure_class")
        .cast(pl.String)
        .fill_null("CORPORATE")
        .str.to_uppercase()
        .str.contains("RETAIL")
    )
    lf = lf.with_columns(
        [
            _polars_correlation_expr(
                eur_gbp_rate=eur_gbp_rate,
                is_b31=config.is_basel_3_1,
                sme_turnover_threshold_m=sme_turnover_m,
            ).alias("correlation"),
            pl.when(is_retail)
            .then(pl.lit(1.0))
            .otherwise(_polars_maturity_adjustment_expr())
            .alias("maturity_adjustment"),
        ]
    )

    # --- Batch 3: K (reads correlation from batch 2) ---
    lf = lf.with_columns(_polars_capital_k_expr().alias("k"))

    # --- Batch 4: RWA + risk weight + expected loss ---
    scaling_factor = 1.06 if config.is_crr else 1.0
    lf = lf.with_columns(
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

    # Defaulted treatment (overrides for PD=100% exposures)
    return apply_defaulted_treatment(lf)


def select_expected_loss(lf: pl.LazyFrame) -> pl.LazyFrame:
    """
    Select expected loss columns for provision comparison.

    Returns:
        LazyFrame with EL columns: exposure_reference, pd, lgd, ead, expected_loss
    """
    return lf.select(
        [
            pl.col("exposure_reference"),
            pl.col("pd_floored").alias("pd"),
            pl.col("lgd_floored").alias("lgd"),
            pl.col("ead_final").alias("ead"),
            pl.col("expected_loss"),
        ]
    )


def build_audit(lf: pl.LazyFrame) -> pl.LazyFrame:
    """
    Build IRB calculation audit trail.

    Selects key calculation columns and creates a human-readable
    calculation string.

    Returns:
        LazyFrame with audit columns including irb_calculation string
    """
    schema = lf.collect_schema()
    available_cols = schema.names()

    select_cols = ["exposure_reference"]
    optional_cols = [
        "counterparty_reference",
        "exposure_class",
        "approach",
        "is_airb",
        "is_defaulted",
        "beel",
        "pd_floored",
        "lgd_floored",
        "ead_final",
        "correlation",
        "k",
        "maturity_adjustment",
        "scaling_factor",
        "risk_weight",
        "rwa",
        "expected_loss",
        "expected_loss_irb_original",
    ]

    for col in optional_cols:
        if col in available_cols:
            select_cols.append(col)

    audit = lf.select(select_cols)

    # Build audit string with defaulted treatment indicator
    has_is_defaulted = "is_defaulted" in available_cols
    has_is_airb = "is_airb" in available_cols

    if has_is_defaulted:
        # Defaulted rows get a specific audit string
        defaulted_str = (
            pl.when(
                has_is_airb and pl.col("is_airb").fill_null(False) if has_is_airb else pl.lit(False)
            )
            .then(
                pl.concat_str(
                    [
                        pl.lit("IRB DEFAULTED A-IRB: K=max(0, LGD-BEEL)="),
                        (pl.col("k") * 100).round(3).cast(pl.String),
                        pl.lit(_AUDIT_LGD_LABEL),
                        (pl.col("lgd_floored") * 100).round(1).cast(pl.String),
                        pl.lit("%, BEEL="),
                        (pl.col("beel").fill_null(0.0) * 100).round(1).cast(pl.String)
                        if "beel" in available_cols
                        else pl.lit("0.0"),
                        pl.lit("% → RWA="),
                        pl.col("rwa").round(0).cast(pl.String),
                    ]
                )
            )
            .otherwise(pl.lit("IRB DEFAULTED F-IRB: K=0, RW=0 → RWA=0"))
        )

        standard_str = pl.concat_str(
            [
                pl.lit("IRB: PD="),
                (pl.col("pd_floored") * 100).round(2).cast(pl.String),
                pl.lit(_AUDIT_LGD_LABEL),
                (pl.col("lgd_floored") * 100).round(1).cast(pl.String),
                pl.lit("%, R="),
                (pl.col("correlation") * 100).round(2).cast(pl.String),
                pl.lit("%, K="),
                (pl.col("k") * 100).round(3).cast(pl.String),
                pl.lit("%, MA="),
                pl.col("maturity_adjustment").round(3).cast(pl.String),
                pl.lit(" → RWA="),
                pl.col("rwa").round(0).cast(pl.String),
            ]
        )

        return audit.with_columns(
            [
                pl.when(pl.col("is_defaulted").fill_null(False))
                .then(defaulted_str)
                .otherwise(standard_str)
                .alias("irb_calculation"),
            ]
        )

    return audit.with_columns(
        [
            pl.concat_str(
                [
                    pl.lit("IRB: PD="),
                    (pl.col("pd_floored") * 100).round(2).cast(pl.String),
                    pl.lit(_AUDIT_LGD_LABEL),
                    (pl.col("lgd_floored") * 100).round(1).cast(pl.String),
                    pl.lit("%, R="),
                    (pl.col("correlation") * 100).round(2).cast(pl.String),
                    pl.lit("%, K="),
                    (pl.col("k") * 100).round(3).cast(pl.String),
                    pl.lit("%, MA="),
                    pl.col("maturity_adjustment").round(3).cast(pl.String),
                    pl.lit(" → RWA="),
                    pl.col("rwa").round(0).cast(pl.String),
                ]
            ).alias("irb_calculation"),
        ]
    )


# =============================================================================
# EXPRESSION TRANSFORMS
# =============================================================================


def floor_pd(expr: pl.Expr, floor_value: float) -> pl.Expr:
    """
    Apply PD floor to expression.

    Args:
        expr: PD expression
        floor_value: Minimum PD value (e.g., 0.0003 for 0.03%)

    Returns:
        Expression with floored PD
    """
    return expr.clip(lower_bound=floor_value)


def floor_lgd(expr: pl.Expr, floor_value: float) -> pl.Expr:
    """
    Apply LGD floor to expression.

    Args:
        expr: LGD expression
        floor_value: Minimum LGD value (e.g., 0.25 for 25%)

    Returns:
        Expression with floored LGD
    """
    return expr.clip(lower_bound=floor_value)


def clip_maturity(expr: pl.Expr, floor: float = 1.0, cap: float = 5.0) -> pl.Expr:
    """
    Clip maturity to regulatory bounds.

    Per CRR Art. 162: floor of 1 year, cap of 5 years.

    Args:
        expr: Maturity expression
        floor: Minimum maturity in years (default 1.0)
        cap: Maximum maturity in years (default 5.0)

    Returns:
        Expression with clipped maturity
    """
    return expr.clip(lower_bound=floor, upper_bound=cap)


# =============================================================================
# PRIVATE MATURITY HELPERS (used by prepare_columns)
# =============================================================================


def _maturity_base_expr(config: CalculationConfig) -> pl.Expr:
    """Build the base maturity expression from maturity_date/termination/default."""
    maturity_from_date = (
        pl.when(pl.col("maturity_date").is_not_null())
        .then(_exact_fractional_years_expr(config.reporting_date, "maturity_date").clip(1.0, 5.0))
        .otherwise(pl.lit(2.5))
    )

    if config.is_basel_3_1:
        # B31 Art. 162(2A)(k): revolving + non-null termination date → use termination date
        maturity_from_termination = (
            pl.when(pl.col("facility_termination_date").is_not_null())
            .then(
                _exact_fractional_years_expr(
                    config.reporting_date, "facility_termination_date"
                ).clip(1.0, 5.0)
            )
            .otherwise(maturity_from_date)
        )
        return (
            pl.when(pl.col("is_revolving").fill_null(False))
            .then(maturity_from_termination)
            .otherwise(maturity_from_date)
        )

    return maturity_from_date


def _apply_firb_sft_supervisory_maturity(
    maturity_expr: pl.Expr, config: CalculationConfig
) -> pl.Expr:
    """CRR Art. 162(1): F-IRB fixed supervisory maturity for repo-style SFTs (0.5y).

    B31 deleted Art. 162(1); under B31 all IRB firms calculate M per Art. 162(2A).
    """
    if not config.is_crr:
        return maturity_expr
    return (
        pl.when((pl.col("approach") == ApproachType.FIRB.value) & pl.col("is_sft").fill_null(False))
        .then(pl.lit(0.5))
        .otherwise(maturity_expr)
    )


def _effective_one_day_floor_flag(config: CalculationConfig) -> pl.Expr:
    """Compose the Art. 162(3) one-day maturity floor flag.

    Per CRR Art. 162(3) second sub-paragraph point (b), self-liquidating short-term
    trade-finance transactions with residual maturity <= 1y are eligible for the
    one-day maturity floor. The engine derives ``has_one_day_maturity_floor=True``
    from ``is_short_term_trade_lc=True`` under CRR. An explicit caller-supplied
    True is preserved by ORing the derived flag onto the input column.
    """
    input_floor_flag = pl.col("has_one_day_maturity_floor").fill_null(False)
    if not config.is_crr:
        return input_floor_flag

    residual_years = (
        pl.when(pl.col("maturity_date").is_not_null())
        .then(_exact_fractional_years_expr(config.reporting_date, "maturity_date"))
        .otherwise(pl.lit(None, dtype=pl.Float64))
    )
    derived_floor_flag = (
        pl.col("is_short_term_trade_lc").fill_null(False)
        & residual_years.is_not_null()
        & (residual_years <= 1.0)
    )
    return input_floor_flag | derived_floor_flag


def _build_maturity_exprs(config: CalculationConfig) -> list[pl.Expr]:
    """Build the full maturity priority chain as a list of aliased expressions.

    Returns two expressions: ``maturity`` and ``has_one_day_maturity_floor``.
    See ``prepare_columns`` for the priority chain documentation.
    """
    maturity_expr = _maturity_base_expr(config)
    maturity_expr = _apply_firb_sft_supervisory_maturity(maturity_expr, config)

    effective_floor_flag = _effective_one_day_floor_flag(config)
    maturity_expr = (
        pl.when(effective_floor_flag).then(pl.lit(_ONE_DAY_YEARS)).otherwise(maturity_expr)
    )

    # Explicit firm-supplied effective_maturity — highest priority.
    # Clipped to [1 day, 5 years]; nulls fall through to the chain above.
    maturity_expr = (
        pl.when(pl.col("effective_maturity").is_not_null())
        .then(pl.col("effective_maturity").clip(_ONE_DAY_YEARS, 5.0))
        .otherwise(maturity_expr)
    )

    return [
        maturity_expr.alias("maturity"),
        # Persist the derived flag so downstream consumers (formulas.py
        # _maturity_adjustment_expr_from_pd) see the carve-out.
        effective_floor_flag.alias("has_one_day_maturity_floor"),
    ]


def _prepare_columns_exprs(config: CalculationConfig, names: set[str]) -> list[pl.Expr]:
    """Build the default-column expressions for ``prepare_columns``.

    Extracted as a module-level helper to keep the public function's cognitive
    complexity under the project limit. The order of expressions mirrors the
    original inline construction so column-dependency ordering is preserved.
    """
    exprs: list[pl.Expr] = []

    # Maturity priority chain — see ``prepare_columns`` docstring for details.
    if "maturity" not in names:
        exprs.extend(_build_maturity_exprs(config))

    if "turnover_m" not in names:
        # CRR Art. 153(4) third subparagraph: substitute total assets of the
        # consolidated group for total annual sales when sales are not a
        # meaningful indicator of firm size. The classifier derives
        # ``sme_size_metric_gbp = coalesce(cp_annual_revenue, cp_total_assets)``
        # and sets ``is_sme`` per the size test (turnover < EUR 50m OR
        # balance-sheet total < EUR 43m). The IRB correlation reads
        # turnover_m and re-derives its own SME gate at the EUR 50m / GBP 44m
        # boundary, so we restrict the value carried into the formula to
        # counterparties the classifier already flagged as SME — otherwise a
        # corporate with assets in the band (EUR 43m, EUR 50m equivalent) would
        # receive the IRB SME correlation reduction despite not being SME-classed.
        turnover_expr = (
            pl.when(pl.col("is_sme").cast(pl.Boolean).fill_null(False))
            .then(pl.col("sme_size_metric_gbp") / 1_000_000.0)
            .otherwise(pl.lit(None).cast(pl.Float64))
        )
        exprs.append(turnover_expr.alias("turnover_m"))

    return exprs


# =============================================================================
# PRIVATE LGD-FLOOR HELPER (used by apply_all_formulas)
# =============================================================================


def _lgd_floored_expr(config: CalculationConfig, schema_names: set[str], lgd_col: str) -> pl.Expr:
    """Build the ``lgd_floored`` expression for ``apply_all_formulas``.

    CRR has no LGD floor. Basel 3.1 applies per-collateral-type floors to
    A-IRB only (F-IRB supervisory LGDs are regulatory values — not floored,
    per CRE30.41).
    """
    if not config.is_basel_3_1:
        return pl.col(lgd_col).alias("lgd_floored")

    if "collateral_type" in schema_names:
        lgd_floor_expr = _lgd_floor_expression_with_collateral(
            config,
            has_seniority=True,
            has_exposure_class=True,
        )
    else:
        lgd_floor_expr = _lgd_floor_expression(
            config,
            has_seniority=True,
            has_exposure_class=True,
        )
    # Art. 164(4)(c) blended floor for retail with mixed collateral
    blended_expr = _lgd_floor_blended_expression(config)
    lgd_floor_expr = (
        pl.when(blended_expr.is_not_null()).then(blended_expr).otherwise(lgd_floor_expr)
    )
    is_airb = pl.col("is_airb").fill_null(False) if "is_airb" in schema_names else pl.lit(False)
    floored_lgd = pl.max_horizontal(pl.col(lgd_col), lgd_floor_expr)
    return pl.when(is_airb).then(floored_lgd).otherwise(pl.col(lgd_col)).alias("lgd_floored")
