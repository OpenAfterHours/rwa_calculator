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

from rwa_calc.data.tables.crr_firb_lgd import FIRB_SUPERVISORY_LGD
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.irb.formulas import (
    _polars_correlation_expr,
    _polars_capital_k_expr,
    _polars_maturity_adjustment_expr,
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
            lf = lf.with_columns([
                pl.lit(ApproachType.FIRB.value).alias("approach"),
            ])

        return lf.with_columns([
            (pl.col("approach") == ApproachType.AIRB.value).alias("is_airb"),
        ])

    def apply_firb_lgd(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply F-IRB supervisory LGD for Foundation IRB exposures.

        F-IRB uses supervisory LGD values per CRR Art. 161:
        - Senior unsecured: 45%
        - Subordinated: 75%

        A-IRB exposures retain their own LGD estimates.

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with F-IRB LGD applied
        """
        schema = self._lf.collect_schema()
        has_seniority = "seniority" in schema.names()

        lf = self._lf
        if "lgd" not in schema.names():
            lf = lf.with_columns([
                pl.lit(None).cast(pl.Float64).alias("lgd"),
            ])

        default_lgd = float(FIRB_SUPERVISORY_LGD["unsecured_senior"])
        sub_lgd = float(FIRB_SUPERVISORY_LGD["subordinated"])

        lf = lf.with_columns([
            pl.when(
                (pl.col("approach") == ApproachType.FIRB.value) &
                pl.col("lgd").is_null()
            )
            .then(
                pl.when(
                    has_seniority and
                    pl.col("seniority").fill_null("senior").str.to_lowercase().str.contains("sub")
                )
                .then(pl.lit(sub_lgd))
                .otherwise(pl.lit(default_lgd))
            )
            .otherwise(pl.col("lgd").fill_null(default_lgd))
            .alias("lgd"),
        ])

        return lf.with_columns([
            pl.col("lgd").alias("lgd_input"),
        ])

    def prepare_columns(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Ensure all required columns exist with defaults.

        Adds/normalizes:
        - pd: Probability of default (default 1%)
        - ead_final: Exposure at default
        - maturity: Effective maturity (floor 1y, cap 5y)
        - turnover_m: Annual turnover in millions
        - exposure_class: Exposure classification

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with all required columns
        """
        schema = self._lf.collect_schema()
        lf = self._lf

        # PD
        if "pd" not in schema.names():
            lf = lf.with_columns([pl.lit(0.01).alias("pd")])

        # EAD
        if "ead_final" not in schema.names():
            if "ead" in schema.names():
                lf = lf.with_columns([pl.col("ead").alias("ead_final")])
            else:
                lf = lf.with_columns([pl.lit(0.0).alias("ead_final")])

        # Refresh schema after potential changes
        schema = lf.collect_schema()

        # Maturity
        maturity_floor = 1.0
        maturity_cap = 5.0
        default_maturity = 5.0

        if "maturity" not in schema.names():
            if "maturity_date" in schema.names():
                reporting_date = config.reporting_date
                lf = lf.with_columns([
                    pl.when(pl.col("maturity_date").is_not_null())
                    .then(
                        ((pl.col("maturity_date") - pl.lit(reporting_date)).dt.total_days() / 365.0)
                        .clip(maturity_floor, maturity_cap)
                    )
                    .otherwise(pl.lit(default_maturity))
                    .alias("maturity"),
                ])
            else:
                lf = lf.with_columns([pl.lit(default_maturity).alias("maturity")])

        # Refresh schema
        schema = lf.collect_schema()

        # Turnover for SME correlation adjustment
        if "turnover_m" not in schema.names():
            if "cp_annual_revenue" in schema.names():
                lf = lf.with_columns([
                    (pl.col("cp_annual_revenue") / 1_000_000.0).alias("turnover_m"),
                ])
            else:
                lf = lf.with_columns([
                    pl.lit(None).cast(pl.Float64).alias("turnover_m"),
                ])

        # Refresh schema
        schema = lf.collect_schema()

        # Exposure class
        if "exposure_class" not in schema.names():
            lf = lf.with_columns([pl.lit("CORPORATE").alias("exposure_class")])

        return lf

    # =========================================================================
    # INDIVIDUAL FORMULA STEPS
    # =========================================================================

    def apply_pd_floor(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply PD floor based on configuration.

        CRR: 0.03% for all classes
        Basel 3.1: Differentiated by class (0.05% corporate, etc.)

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with pd_floored column
        """
        pd_floor = float(config.pd_floors.corporate)
        return self._lf.with_columns(
            pl.col("pd").clip(lower_bound=pd_floor).alias("pd_floored")
        )

    def apply_lgd_floor(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply LGD floor for Basel 3.1 A-IRB.

        CRR: No LGD floor
        Basel 3.1: 25% unsecured, varies by collateral

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with lgd_floored column
        """
        if config.is_basel_3_1:
            lgd_floor = float(config.lgd_floors.unsecured)
            return self._lf.with_columns(
                pl.col("lgd").clip(lower_bound=lgd_floor).alias("lgd_floored")
            )
        return self._lf.with_columns(
            pl.col("lgd").alias("lgd_floored")
        )

    def calculate_correlation(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Calculate asset correlation using pure Polars expressions.

        Supports:
        - Corporate/Institution/Sovereign: PD-dependent (0.12-0.24)
        - Retail mortgage: Fixed 0.15
        - QRRE: Fixed 0.04
        - Other retail: PD-dependent (0.03-0.16)
        - SME adjustment for corporates

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with correlation column
        """
        return self._lf.with_columns(
            _polars_correlation_expr().alias("correlation")
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
        return self._lf.with_columns(
            _polars_capital_k_expr().alias("k")
        )

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

        return self._lf.with_columns([
            pl.lit(scaling_factor).alias("scaling_factor"),
            (pl.col("k") * 12.5 * scaling_factor * pl.col("ead_final") * pl.col("maturity_adjustment")).alias("rwa"),
            (pl.col("k") * 12.5 * scaling_factor * pl.col("maturity_adjustment")).alias("risk_weight"),
        ])

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
            (pl.col("pd_floored") * pl.col("lgd_floored") * pl.col("ead_final")).alias("expected_loss")
        )

    # =========================================================================
    # CONVENIENCE / PIPELINE METHODS
    # =========================================================================

    def apply_all_formulas(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply full IRB formula pipeline.

        Steps:
        1. Ensure required columns exist (turnover_m, maturity)
        2. Apply PD floor
        3. Apply LGD floor (Basel 3.1 only)
        4. Calculate correlation
        5. Calculate K
        6. Calculate maturity adjustment
        7. Calculate RWA and risk weight
        8. Calculate expected loss

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with all IRB calculations
        """
        # Ensure required columns exist for correlation calculation
        schema = self._lf.collect_schema()
        lf = self._lf

        if "turnover_m" not in schema.names():
            lf = lf.with_columns(pl.lit(None).cast(pl.Float64).alias("turnover_m"))

        if "maturity" not in schema.names():
            lf = lf.with_columns(pl.lit(2.5).alias("maturity"))

        return (lf
            .irb.apply_pd_floor(config)
            .irb.apply_lgd_floor(config)
            .irb.calculate_correlation(config)
            .irb.calculate_k(config)
            .irb.calculate_maturity_adjustment(config)
            .irb.calculate_rwa(config)
            .irb.calculate_expected_loss(config)
        )

    def select_expected_loss(self) -> pl.LazyFrame:
        """
        Select expected loss columns for provision comparison.

        Returns:
            LazyFrame with EL columns: exposure_reference, pd, lgd, ead, expected_loss
        """
        return self._lf.select([
            pl.col("exposure_reference"),
            pl.col("pd_floored").alias("pd"),
            pl.col("lgd_floored").alias("lgd"),
            pl.col("ead_final").alias("ead"),
            pl.col("expected_loss"),
        ])

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
        ]

        for col in optional_cols:
            if col in available_cols:
                select_cols.append(col)

        audit = self._lf.select(select_cols)

        return audit.with_columns([
            pl.concat_str([
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
            ]).alias("irb_calculation"),
        ])


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
