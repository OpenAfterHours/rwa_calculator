"""
Polars LazyFrame and Expr namespaces for IRB calculations.

Provides fluent API for IRB RWA calculations via registered namespaces:
- `lf.irb.apply_all_formulas(config)` - Full IRB pipeline
- `lf.irb.classify_approach(config)` - F-IRB vs A-IRB classification
- `pl.col("pd").irb.floor_pd(0.0003)` - Column-level PD flooring

Uses pure Polars expressions with polars-normal-stats for statistical functions,
enabling full lazy evaluation, query optimization, and streaming.

Usage:
    import polars as pl
    from rwa_calc.contracts.config import CalculationConfig
    import rwa_calc.engine.irb.namespace  # Register namespace

    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    result = (lf
        .irb.classify_approach(config)
        .irb.apply_firb_lgd(config)
        .irb.prepare_columns(config)
        .irb.apply_all_formulas(config)
    )

References:
- CRR Art. 153-154: IRB risk weight functions
- CRR Art. 161: F-IRB supervisory LGD
- CRR Art. 162-163: Maturity and PD floors
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.data.tables.crr_firb_lgd import get_firb_lgd_table_for_framework
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


# =============================================================================
# LAZYFRAME NAMESPACE
# =============================================================================


@pl.api.register_lazyframe_namespace("irb")
class IRBLazyFrame:
    """
    IRB calculation namespace for Polars LazyFrames.

    Provides fluent API for IRB RWA calculations.

    Example:
        result = (exposures
            .irb.classify_approach(config)
            .irb.apply_firb_lgd(config)
            .irb.prepare_columns(config)
            .irb.apply_all_formulas(config)
        )
    """

    def __init__(self, lf: pl.LazyFrame) -> None:
        self._lf = lf

    # =========================================================================
    # SETUP / CLASSIFICATION METHODS
    # =========================================================================

    def classify_approach(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Classify exposures as F-IRB or A-IRB.

        Adds columns:
        - approach: The IRB approach (foundation_irb or advanced_irb)
        - is_airb: Boolean flag for A-IRB exposures

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with approach classification
        """
        schema = self._lf.collect_schema()

        lf = self._lf
        if "approach" not in schema.names():
            lf = lf.with_columns(
                [
                    pl.lit(ApproachType.FIRB.value).alias("approach"),
                ]
            )

        return lf.with_columns(
            [
                (pl.col("approach") == ApproachType.AIRB.value).alias("is_airb"),
            ]
        )

    def apply_firb_lgd(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply F-IRB supervisory LGD for Foundation IRB exposures.

        CRR Art. 161(1)(a): Senior unsecured 45%, subordinated 75%
        Basel 3.1 Art. 161(1)(a)/(aa): FSE senior 45%, non-FSE senior 40%, sub 75%

        For F-IRB exposures with collateral, the CRM processor calculates
        the effective LGD (lgd_post_crm) based on collateral type and coverage.
        This method uses lgd_post_crm as the input LGD for risk weight calculation.

        A-IRB exposures retain their own LGD estimates.

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with F-IRB LGD applied
        """
        schema = self._lf.collect_schema()
        schema_names = schema.names()
        has_seniority = "seniority" in schema_names
        has_lgd_post_crm = "lgd_post_crm" in schema_names

        lf = self._lf
        if "lgd" not in schema_names:
            lf = lf.with_columns(
                [
                    pl.lit(None).cast(pl.Float64).alias("lgd"),
                ]
            )
        elif schema["lgd"] != pl.Float64:
            # Cast lgd to Float64 if it's not already (handles String type from Excel imports)
            lf = lf.with_columns(
                [
                    pl.col("lgd").cast(pl.Float64, strict=False).alias("lgd"),
                ]
            )

        # Use framework-appropriate supervisory LGD values
        lgd_table = get_firb_lgd_table_for_framework(config.is_basel_3_1)
        default_lgd = float(lgd_table["unsecured_senior"])
        sub_lgd = float(lgd_table["subordinated"])

        # Under Basel 3.1, FSE senior unsecured = 45% (Art. 161(1)(a));
        # non-FSE = 40% (Art. 161(1)(aa)). Under CRR, all = 45%.
        has_fse_col = (
            config.is_basel_3_1 and "cp_is_financial_sector_entity" in schema_names
        )
        if has_fse_col:
            fse_lgd = float(lgd_table["unsecured_senior_fse"])
            default_lgd_expr = (
                pl.when(pl.col("cp_is_financial_sector_entity").fill_null(False))
                .then(pl.lit(fse_lgd))
                .otherwise(pl.lit(default_lgd))
            )
        else:
            default_lgd_expr = pl.lit(default_lgd)

        lf = lf.with_columns(
            [
                pl.when((pl.col("approach") == ApproachType.FIRB.value) & pl.col("lgd").is_null())
                .then(
                    pl.when(
                        has_seniority
                        and pl.col("seniority")
                        .fill_null("senior")
                        .str.to_lowercase()
                        .str.contains("sub")
                    )
                    .then(pl.lit(sub_lgd))
                    .otherwise(default_lgd_expr)
                )
                .otherwise(pl.col("lgd").fill_null(default_lgd))
                .alias("lgd"),
            ]
        )

        # For lgd_input, use lgd_post_crm (from CRM processor) if available
        # This ensures collateral-adjusted LGD is used for F-IRB risk weight calculation
        if has_lgd_post_crm:
            return lf.with_columns(
                [
                    pl.when(pl.col("approach") == ApproachType.FIRB.value)
                    .then(pl.col("lgd_post_crm"))
                    .otherwise(pl.col("lgd"))
                    .alias("lgd_input"),
                ]
            )
        else:
            return lf.with_columns(
                [
                    pl.col("lgd").alias("lgd_input"),
                ]
            )

    def prepare_columns(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Ensure all required columns exist with defaults.

        Single schema check followed by one with_columns() for all defaults.

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with all required columns
        """
        schema = self._lf.collect_schema()
        names = set(schema.names())
        exprs: list[pl.Expr] = []

        # PD
        if "pd" not in names:
            exprs.append(pl.lit(0.01).alias("pd"))

        # EAD
        if "ead_final" not in names:
            if "ead" in names:
                exprs.append(pl.col("ead").alias("ead_final"))
            else:
                exprs.append(pl.lit(0.0).alias("ead_final"))

        # Maturity
        if "maturity" not in names:
            if "maturity_date" in names:
                exprs.append(
                    pl.when(pl.col("maturity_date").is_not_null())
                    .then(
                        _exact_fractional_years_expr(config.reporting_date, "maturity_date").clip(
                            1.0, 5.0
                        )
                    )
                    .otherwise(pl.lit(2.5))
                    .alias("maturity"),
                )
            else:
                exprs.append(pl.lit(2.5).alias("maturity"))

        # Turnover for SME correlation adjustment
        if "turnover_m" not in names:
            if "cp_annual_revenue" in names:
                exprs.append((pl.col("cp_annual_revenue") / 1_000_000.0).alias("turnover_m"))
            else:
                exprs.append(pl.lit(None).cast(pl.Float64).alias("turnover_m"))

        # Exposure class
        if "exposure_class" not in names:
            exprs.append(pl.lit("CORPORATE").alias("exposure_class"))

        # Defaulted exposure columns
        if "is_defaulted" not in names:
            exprs.append(pl.lit(False).alias("is_defaulted"))
        if "beel" not in names:
            exprs.append(pl.lit(0.0).alias("beel"))

        if exprs:
            return self._lf.with_columns(exprs)
        return self._lf

    # =========================================================================
    # INDIVIDUAL FORMULA STEPS
    # =========================================================================

    def apply_pd_floor(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply PD floor based on configuration.

        CRR (Art. 163): 0.03% for all classes
        Basel 3.1 (CRE30.55): Differentiated by class
            - Corporate/SME: 0.05%
            - Retail mortgage: 0.05%
            - QRRE revolvers: 0.10%, transactors: 0.03%
            - Retail other: 0.05%

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with pd_floored column
        """
        has_transactor = "is_qrre_transactor" in self._lf.collect_schema().names()
        pd_floor_expr = _pd_floor_expression(config, has_transactor_col=has_transactor)
        return self._lf.with_columns(
            pl.max_horizontal(pl.col("pd"), pd_floor_expr).alias("pd_floored")
        )

    def apply_lgd_floor(self, config: CalculationConfig) -> pl.LazyFrame:
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
            config: Calculation configuration

        Returns:
            LazyFrame with lgd_floored column
        """
        schema = self._lf.collect_schema()
        schema_names = schema.names()
        lgd_col = "lgd_input" if "lgd_input" in schema_names else "lgd"

        if config.is_basel_3_1:
            has_collateral_type = "collateral_type" in schema_names
            has_seniority = "seniority" in schema_names
            has_exposure_class = "exposure_class" in schema_names
            if has_collateral_type:
                lgd_floor_expr = _lgd_floor_expression_with_collateral(
                    config,
                    has_seniority=has_seniority,
                    has_exposure_class=has_exposure_class,
                )
            else:
                lgd_floor_expr = _lgd_floor_expression(
                    config,
                    has_seniority=has_seniority,
                    has_exposure_class=has_exposure_class,
                )

            # LGD floors only apply to A-IRB (CRE30.41); F-IRB uses supervisory LGD
            is_airb = (
                pl.col("is_airb").fill_null(False) if "is_airb" in schema_names else pl.lit(False)
            )
            floored_lgd = pl.max_horizontal(pl.col(lgd_col), lgd_floor_expr)
            return self._lf.with_columns(
                pl.when(is_airb).then(floored_lgd).otherwise(pl.col(lgd_col)).alias("lgd_floored")
            )
        return self._lf.with_columns(pl.col(lgd_col).alias("lgd_floored"))

    def calculate_correlation(self, config: CalculationConfig) -> pl.LazyFrame:
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
            config: Calculation configuration

        Returns:
            LazyFrame with correlation column
        """
        # Ensure requires_fi_scalar column exists (defaults to False if not set by classifier)
        schema = self._lf.collect_schema()
        lf = self._lf
        if "requires_fi_scalar" not in schema.names():
            lf = lf.with_columns(pl.lit(False).alias("requires_fi_scalar"))

        # Pass EUR/GBP rate from config to convert GBP turnover to EUR for SME adjustment
        eur_gbp_rate = float(config.eur_gbp_rate)
        return lf.with_columns(
            _polars_correlation_expr(eur_gbp_rate=eur_gbp_rate).alias("correlation")
        )

    def calculate_k(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Calculate capital requirement (K) using pure Polars with polars-normal-stats.

        K = LGD × N[(1-R)^(-0.5) × G(PD) + (R/(1-R))^(0.5) × G(0.999)] - PD × LGD

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with k column
        """
        return self._lf.with_columns(_polars_capital_k_expr().alias("k"))

    def calculate_maturity_adjustment(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Calculate maturity adjustment for non-retail exposures.

        MA = (1 + (M - 2.5) × b) / (1 - 1.5 × b)
        where b = (0.11852 - 0.05478 × ln(PD))²

        Retail exposures get MA = 1.0.

        Args:
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

        return self._lf.with_columns(
            pl.when(is_retail)
            .then(pl.lit(1.0))
            .otherwise(_polars_maturity_adjustment_expr())
            .alias("maturity_adjustment")
        )

    def calculate_rwa(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Calculate RWA and related metrics.

        RWA = K × 12.5 × [1.06] × EAD × MA
        Risk weight = K × 12.5 × [1.06] × MA

        The 1.06 scaling factor applies only under CRR.

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with rwa, risk_weight, scaling_factor columns
        """
        scaling_factor = 1.06 if config.is_crr else 1.0

        return self._lf.with_columns(
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

    def calculate_expected_loss(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Calculate expected loss.

        EL = PD × LGD × EAD

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with expected_loss column
        """
        return self._lf.with_columns(
            (pl.col("pd_floored") * pl.col("lgd_floored") * pl.col("ead_final")).alias(
                "expected_loss"
            )
        )

    # =========================================================================
    # DEFAULTED EXPOSURE TREATMENT
    # =========================================================================

    def apply_defaulted_treatment(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply regulatory treatment for defaulted exposures (PD=100%).

        Delegates to ``adjustments.apply_defaulted_treatment``.
        """
        return _apply_defaulted_treatment(self._lf, config)

    # =========================================================================
    # POST-MODEL ADJUSTMENTS (Basel 3.1)
    # =========================================================================

    def apply_post_model_adjustments(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply post-model adjustments to IRB RWEA and EL (Basel 3.1 only).

        Delegates to ``adjustments.apply_post_model_adjustments``.
        """
        return _apply_post_model_adjustments(self._lf, config)

    # =========================================================================
    # EL SHORTFALL / EXCESS
    # =========================================================================

    def compute_el_shortfall_excess(self) -> pl.LazyFrame:
        """Compute EL shortfall and excess for IRB exposures.

        Delegates to ``adjustments.compute_el_shortfall_excess``.
        """
        return _compute_el_shortfall_excess(self._lf)

    # =========================================================================
    # GUARANTEE SUBSTITUTION
    # =========================================================================

    def apply_guarantee_substitution(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply guarantee substitution for IRB exposures.

        Delegates to ``guarantee.apply_guarantee_substitution``.
        """
        return _apply_guarantee_substitution(self._lf, config)

    # =========================================================================
    # CONVENIENCE / PIPELINE METHODS
    # =========================================================================

    def apply_all_formulas(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply full IRB formula pipeline in 4 batched with_columns.

        Batch 1: Ensure defaults + PD floor + LGD floor (read only input cols)
        Batch 2: Correlation + maturity adjustment (read pd_floored from batch 1)
        Batch 3: K (reads correlation from batch 2)
        Batch 4: RWA + risk weight + expected loss (read k, maturity_adjustment)
        Then: defaulted treatment override

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with all IRB calculations
        """
        schema = self._lf.collect_schema()
        schema_names = set(schema.names())
        lf = self._lf

        # --- Batch 1: defaults + PD floor + LGD floor ---
        batch1: list[pl.Expr] = []

        if "turnover_m" not in schema_names:
            batch1.append(pl.lit(None).cast(pl.Float64).alias("turnover_m"))
        if "maturity" not in schema_names:
            batch1.append(pl.lit(2.5).alias("maturity"))
        if "requires_fi_scalar" not in schema_names:
            batch1.append(pl.lit(False).alias("requires_fi_scalar"))

        # Per-exposure-class PD floor (CRR: uniform, Basel 3.1: differentiated)
        has_transactor = "is_qrre_transactor" in schema_names
        pd_floor_expr = _pd_floor_expression(config, has_transactor_col=has_transactor)
        batch1.append(pl.max_horizontal(pl.col("pd"), pd_floor_expr).alias("pd_floored"))

        # LGD floor (CRR: none, Basel 3.1: per-collateral-type for A-IRB only)
        # F-IRB supervisory LGDs are regulatory values — don't floor them (CRE30.41)
        lgd_col = "lgd_input" if "lgd_input" in schema_names else "lgd"
        if config.is_basel_3_1:
            has_collateral_type = "collateral_type" in schema_names
            has_seniority = "seniority" in schema_names
            has_exposure_class = "exposure_class" in schema_names
            if has_collateral_type:
                lgd_floor_expr = _lgd_floor_expression_with_collateral(
                    config,
                    has_seniority=has_seniority,
                    has_exposure_class=has_exposure_class,
                )
            else:
                lgd_floor_expr = _lgd_floor_expression(
                    config,
                    has_seniority=has_seniority,
                    has_exposure_class=has_exposure_class,
                )
            is_airb = (
                pl.col("is_airb").fill_null(False) if "is_airb" in schema_names else pl.lit(False)
            )
            floored_lgd = pl.max_horizontal(pl.col(lgd_col), lgd_floor_expr)
            batch1.append(
                pl.when(is_airb).then(floored_lgd).otherwise(pl.col(lgd_col)).alias("lgd_floored")
            )
        else:
            batch1.append(pl.col(lgd_col).alias("lgd_floored"))

        lf = lf.with_columns(batch1)

        # --- Batch 2: Correlation + maturity adjustment (read pd_floored) ---
        eur_gbp_rate = float(config.eur_gbp_rate)
        is_retail = (
            pl.col("exposure_class")
            .cast(pl.String)
            .fill_null("CORPORATE")
            .str.to_uppercase()
            .str.contains("RETAIL")
        )
        lf = lf.with_columns(
            [
                _polars_correlation_expr(eur_gbp_rate=eur_gbp_rate).alias("correlation"),
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
        return lf.irb.apply_defaulted_treatment(config)

    def select_expected_loss(self) -> pl.LazyFrame:
        """
        Select expected loss columns for provision comparison.

        Returns:
            LazyFrame with EL columns: exposure_reference, pd, lgd, ead, expected_loss
        """
        return self._lf.select(
            [
                pl.col("exposure_reference"),
                pl.col("pd_floored").alias("pd"),
                pl.col("lgd_floored").alias("lgd"),
                pl.col("ead_final").alias("ead"),
                pl.col("expected_loss"),
            ]
        )

    def build_audit(self) -> pl.LazyFrame:
        """
        Build IRB calculation audit trail.

        Selects key calculation columns and creates a human-readable
        calculation string.

        Returns:
            LazyFrame with audit columns including irb_calculation string
        """
        schema = self._lf.collect_schema()
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

        audit = self._lf.select(select_cols)

        # Build audit string with defaulted treatment indicator
        has_is_defaulted = "is_defaulted" in available_cols
        has_is_airb = "is_airb" in available_cols

        if has_is_defaulted:
            # Defaulted rows get a specific audit string
            defaulted_str = (
                pl.when(
                    has_is_airb and pl.col("is_airb").fill_null(False)
                    if has_is_airb
                    else pl.lit(False)
                )
                .then(
                    pl.concat_str(
                        [
                            pl.lit("IRB DEFAULTED A-IRB: K=max(0, LGD-BEEL)="),
                            (pl.col("k") * 100).round(3).cast(pl.String),
                            pl.lit("%, LGD="),
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
                    pl.lit("%, LGD="),
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
                        pl.lit("%, LGD="),
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
# EXPRESSION NAMESPACE
# =============================================================================


@pl.api.register_expr_namespace("irb")
class IRBExpr:
    """
    IRB calculation namespace for Polars Expressions.

    Provides column-level operations for IRB calculations.

    Example:
        df.with_columns(
            pl.col("pd").irb.floor_pd(0.0003),
            pl.col("lgd").irb.floor_lgd(0.25),
        )
    """

    def __init__(self, expr: pl.Expr) -> None:
        self._expr = expr

    def floor_pd(self, floor_value: float) -> pl.Expr:
        """
        Apply PD floor to expression.

        Args:
            floor_value: Minimum PD value (e.g., 0.0003 for 0.03%)

        Returns:
            Expression with floored PD
        """
        return self._expr.clip(lower_bound=floor_value)

    def floor_lgd(self, floor_value: float) -> pl.Expr:
        """
        Apply LGD floor to expression.

        Args:
            floor_value: Minimum LGD value (e.g., 0.25 for 25%)

        Returns:
            Expression with floored LGD
        """
        return self._expr.clip(lower_bound=floor_value)

    def clip_maturity(self, floor: float = 1.0, cap: float = 5.0) -> pl.Expr:
        """
        Clip maturity to regulatory bounds.

        Per CRR Art. 162: floor of 1 year, cap of 5 years.

        Args:
            floor: Minimum maturity in years (default 1.0)
            cap: Maximum maturity in years (default 5.0)

        Returns:
            Expression with clipped maturity
        """
        return self._expr.clip(lower_bound=floor, upper_bound=cap)
