"""
Polars LazyFrame and Expr namespaces for SA calculations.

Provides fluent API for Standardised Approach RWA calculations via registered namespaces:
- `lf.sa.apply_risk_weights(config)` - Apply risk weights
- `lf.sa.calculate_rwa()` - Calculate RWA
- `lf.sa.apply_all(config)` - Full SA pipeline

Delegates to risk weight lookup tables for CQS-based and LTV-based weights.

Usage:
    import polars as pl
    from rwa_calc.contracts.config import CalculationConfig
    import rwa_calc.engine.sa.namespace  # Register namespace

    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    result = (lf
        .sa.prepare_columns(config)
        .sa.apply_risk_weights(config)
        .sa.calculate_rwa()
        .sa.apply_supporting_factors(config)
    )

References:
- CRR Art. 112-134: SA risk weights
- CRR Art. 501: SME supporting factor
- CRR Art. 501a: Infrastructure supporting factor
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.data.tables.crr_risk_weights import (
    get_combined_cqs_risk_weights,
    RESIDENTIAL_MORTGAGE_PARAMS,
    COMMERCIAL_RE_PARAMS,
    RETAIL_RISK_WEIGHT,
)
from rwa_calc.domain.enums import ApproachType

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# LAZYFRAME NAMESPACE
# =============================================================================


@pl.api.register_lazyframe_namespace("sa")
class SALazyFrame:
    """
    SA calculation namespace for Polars LazyFrames.

    Provides fluent API for Standardised Approach RWA calculations.

    Example:
        result = (exposures
            .sa.prepare_columns(config)
            .sa.apply_risk_weights(config)
            .sa.calculate_rwa()
            .sa.apply_supporting_factors(config)
        )
    """

    def __init__(self, lf: pl.LazyFrame) -> None:
        self._lf = lf

    # =========================================================================
    # SETUP / PREPARATION METHODS
    # =========================================================================

    def prepare_columns(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Ensure all required columns exist with defaults.

        Adds/normalizes:
        - ead_final: Exposure at default
        - exposure_class: Exposure classification
        - cqs: Credit quality step
        - ltv: Loan-to-value ratio
        - is_sme: SME flag
        - is_infrastructure: Infrastructure flag

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with all required columns
        """
        schema = self._lf.collect_schema()
        lf = self._lf

        # EAD
        if "ead_final" not in schema.names():
            if "ead" in schema.names():
                lf = lf.with_columns([pl.col("ead").alias("ead_final")])
            elif "ead_pre_crm" in schema.names():
                lf = lf.with_columns([pl.col("ead_pre_crm").alias("ead_final")])
            else:
                lf = lf.with_columns([pl.lit(0.0).alias("ead_final")])

        # Refresh schema
        schema = lf.collect_schema()

        # Exposure class
        if "exposure_class" not in schema.names():
            lf = lf.with_columns([pl.lit("CORPORATE").alias("exposure_class")])

        # CQS
        if "cqs" not in schema.names():
            lf = lf.with_columns([pl.lit(None).cast(pl.Int8).alias("cqs")])

        # LTV
        if "ltv" not in schema.names():
            lf = lf.with_columns([pl.lit(None).cast(pl.Float64).alias("ltv")])

        # SME flag
        if "is_sme" not in schema.names():
            lf = lf.with_columns([pl.lit(False).alias("is_sme")])

        # Infrastructure flag
        if "is_infrastructure" not in schema.names():
            lf = lf.with_columns([pl.lit(False).alias("is_infrastructure")])

        # Has income cover (for CRE)
        if "has_income_cover" not in schema.names():
            lf = lf.with_columns([pl.lit(False).alias("has_income_cover")])

        # Book code (legacy - kept for backward compatibility)
        if "book_code" not in schema.names():
            lf = lf.with_columns([pl.lit("").alias("book_code")])

        # Managed as retail flag (CRR Art. 123 - for SME retail treatment)
        if "cp_is_managed_as_retail" not in schema.names():
            lf = lf.with_columns([pl.lit(False).alias("cp_is_managed_as_retail")])

        return lf

    # =========================================================================
    # RISK WEIGHT APPLICATION METHODS
    # =========================================================================

    def apply_risk_weights(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply risk weights based on exposure class and CQS/LTV.

        Handles:
        - CQS-based lookups (sovereign, institution, corporate)
        - Fixed retail (75%)
        - LTV-based real estate (split treatment)

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with risk_weight column added
        """
        # Get CQS-based risk weight table (includes UK deviation for institutions)
        use_uk_deviation = config.base_currency == "GBP"
        rw_table = get_combined_cqs_risk_weights(use_uk_deviation).lazy()

        # Prepare exposures for join
        lf = self._lf.with_columns([
            # Map detailed classes to lookup classes
            pl.when(pl.col("exposure_class").str.contains("(?i)central_govt"))
            .then(pl.lit("CENTRAL_GOVT_CENTRAL_BANK"))
            .when(pl.col("exposure_class").str.contains("(?i)institution"))
            .then(pl.lit("INSTITUTION"))
            .when(pl.col("exposure_class").str.contains("(?i)corporate"))
            .then(pl.lit("CORPORATE"))
            .otherwise(pl.col("exposure_class").str.to_uppercase())
            .alias("_lookup_class"),

            # Use -1 as sentinel for null CQS (for join matching)
            pl.col("cqs").fill_null(-1).cast(pl.Int8).alias("_lookup_cqs"),
        ])

        # Prepare risk weight table with same sentinel for null CQS
        rw_table = rw_table.with_columns([
            pl.col("cqs").fill_null(-1).cast(pl.Int8).alias("cqs"),
        ])

        # Join risk weight table
        lf = lf.join(
            rw_table.select(["exposure_class", "cqs", "risk_weight"]),
            left_on=["_lookup_class", "_lookup_cqs"],
            right_on=["exposure_class", "cqs"],
            how="left",
            suffix="_rw",
        )

        # Apply class-specific risk weights
        retail_rw = float(RETAIL_RISK_WEIGHT)
        resi_threshold = float(RESIDENTIAL_MORTGAGE_PARAMS["ltv_threshold"])
        resi_rw_low = float(RESIDENTIAL_MORTGAGE_PARAMS["rw_low_ltv"])
        resi_rw_high = float(RESIDENTIAL_MORTGAGE_PARAMS["rw_high_ltv"])
        cre_threshold = float(COMMERCIAL_RE_PARAMS["ltv_threshold"])
        cre_rw_low = float(COMMERCIAL_RE_PARAMS["rw_low_ltv"])
        cre_rw_standard = float(COMMERCIAL_RE_PARAMS["rw_standard"])

        lf = lf.with_columns([
            # Order matters: check specific classes before generic ones
            # 1. Residential mortgage: LTV-based
            pl.when(pl.col("exposure_class").str.contains("(?i)mortgage|residential"))
            .then(
                pl.when(pl.col("ltv").fill_null(0.0) <= resi_threshold)
                .then(pl.lit(resi_rw_low))
                .otherwise(
                    (resi_rw_low * resi_threshold / pl.col("ltv").fill_null(1.0) +
                     resi_rw_high * (pl.col("ltv").fill_null(1.0) - resi_threshold) /
                     pl.col("ltv").fill_null(1.0))
                )
            )

            # 2. Commercial RE: LTV + income cover based
            .when(pl.col("exposure_class").str.contains("(?i)commercial.*re|cre"))
            .then(
                pl.when(
                    (pl.col("ltv").fill_null(1.0) <= cre_threshold) &
                    pl.col("has_income_cover").fill_null(False)
                )
                .then(pl.lit(cre_rw_low))
                .otherwise(pl.lit(cre_rw_standard))
            )

            # 3. SME managed as retail: 75% RW (CRR Art. 123)
            .when(
                (pl.col("exposure_class").str.contains("(?i)sme")) &
                (pl.col("cp_is_managed_as_retail") == True)  # noqa: E712
            )
            .then(pl.lit(retail_rw))

            # 4. Corporate SME: 100% RW
            .when(pl.col("exposure_class").str.contains("(?i)corporate.*sme|sme.*corporate"))
            .then(pl.lit(1.0))

            # 5. Retail (non-mortgage): 75% flat
            .when(pl.col("exposure_class").str.contains("(?i)retail"))
            .then(pl.lit(retail_rw))

            # 6. Default: use joined CQS-based risk weight, or 100%
            .otherwise(pl.col("risk_weight").fill_null(1.0))
            .alias("risk_weight"),
        ])

        # Clean up temporary columns
        lf = lf.drop([
            col for col in ["_lookup_class", "_lookup_cqs", "risk_weight_rw"]
            if col in lf.collect_schema().names()
        ])

        return lf

    def apply_residential_mortgage_rw(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply LTV-based risk weights for residential mortgages.

        CRR split treatment:
        - LTV <= 80%: 35% risk weight
        - LTV > 80%: weighted average of 35% and 75%

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with residential mortgage risk weights
        """
        threshold = float(RESIDENTIAL_MORTGAGE_PARAMS["ltv_threshold"])
        rw_low = float(RESIDENTIAL_MORTGAGE_PARAMS["rw_low_ltv"])
        rw_high = float(RESIDENTIAL_MORTGAGE_PARAMS["rw_high_ltv"])

        return self._lf.with_columns([
            pl.when(pl.col("ltv").fill_null(0.0) <= threshold)
            .then(pl.lit(rw_low))
            .otherwise(
                (rw_low * threshold / pl.col("ltv").fill_null(1.0) +
                 rw_high * (pl.col("ltv").fill_null(1.0) - threshold) /
                 pl.col("ltv").fill_null(1.0))
            )
            .alias("risk_weight"),
        ])

    def apply_commercial_re_rw(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply risk weights for commercial real estate.

        - LTV <= 60% with income cover: 50%
        - Otherwise: 100%

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with commercial RE risk weights
        """
        threshold = float(COMMERCIAL_RE_PARAMS["ltv_threshold"])
        rw_low = float(COMMERCIAL_RE_PARAMS["rw_low_ltv"])
        rw_standard = float(COMMERCIAL_RE_PARAMS["rw_standard"])

        return self._lf.with_columns([
            pl.when(
                (pl.col("ltv").fill_null(1.0) <= threshold) &
                pl.col("has_income_cover").fill_null(False)
            )
            .then(pl.lit(rw_low))
            .otherwise(pl.lit(rw_standard))
            .alias("risk_weight"),
        ])

    def apply_cqs_based_rw(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply CQS-based risk weights via table lookup.

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with CQS-based risk weights
        """
        use_uk_deviation = config.base_currency == "GBP"
        rw_table = get_combined_cqs_risk_weights(use_uk_deviation).lazy()

        # Prepare for join
        lf = self._lf.with_columns([
            pl.col("cqs").fill_null(-1).cast(pl.Int8).alias("_lookup_cqs"),
        ])

        rw_table = rw_table.with_columns([
            pl.col("cqs").fill_null(-1).cast(pl.Int8).alias("cqs"),
        ])

        # Join
        lf = lf.join(
            rw_table.select(["exposure_class", "cqs", "risk_weight"]),
            left_on=["exposure_class", "_lookup_cqs"],
            right_on=["exposure_class", "cqs"],
            how="left",
            suffix="_lookup",
        )

        # Apply looked-up weight
        lf = lf.with_columns([
            pl.coalesce(pl.col("risk_weight_lookup"), pl.lit(1.0)).alias("risk_weight"),
        ])

        # Clean up
        return lf.drop(["_lookup_cqs", "risk_weight_lookup"])

    # =========================================================================
    # GUARANTEE SUBSTITUTION METHODS
    # =========================================================================

    def apply_guarantee_substitution(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply guarantee substitution for unfunded credit protection.

        For guaranteed portions, the risk weight is substituted with the
        guarantor's risk weight. The final risk weight is blended based on
        guaranteed vs unguaranteed portions.

        CRR Art. 213-217: Unfunded credit protection

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with guarantee substitution applied
        """
        schema = self._lf.collect_schema()
        cols = schema.names()

        # Check if guarantee columns exist
        if "guaranteed_portion" not in cols or "guarantor_entity_type" not in cols:
            return self._lf

        use_uk_deviation = config.base_currency == "GBP"

        # Calculate guarantor's risk weight based on entity type and CQS
        lf = self._lf.with_columns([
            pl.when(pl.col("guaranteed_portion") <= 0)
            .then(pl.lit(None).cast(pl.Float64))
            # Sovereign guarantors
            .when(pl.col("guarantor_entity_type").str.contains("(?i)sovereign"))
            .then(
                pl.when(pl.col("guarantor_cqs") == 1).then(pl.lit(0.0))
                .when(pl.col("guarantor_cqs") == 2).then(pl.lit(0.20))
                .when(pl.col("guarantor_cqs") == 3).then(pl.lit(0.50))
                .when(pl.col("guarantor_cqs").is_in([4, 5])).then(pl.lit(1.0))
                .when(pl.col("guarantor_cqs") == 6).then(pl.lit(1.50))
                .otherwise(pl.lit(1.0))
            )
            # Institution guarantors (UK deviation: CQS 2 = 30%)
            .when(pl.col("guarantor_entity_type").str.contains("(?i)institution"))
            .then(
                pl.when(pl.col("guarantor_cqs") == 1).then(pl.lit(0.20))
                .when(pl.col("guarantor_cqs") == 2).then(pl.lit(0.30) if use_uk_deviation else pl.lit(0.50))
                .when(pl.col("guarantor_cqs") == 3).then(pl.lit(0.50))
                .when(pl.col("guarantor_cqs").is_in([4, 5])).then(pl.lit(1.0))
                .when(pl.col("guarantor_cqs") == 6).then(pl.lit(1.50))
                .otherwise(pl.lit(0.40))
            )
            # Corporate guarantors
            .when(pl.col("guarantor_entity_type").str.contains("(?i)corporate"))
            .then(
                pl.when(pl.col("guarantor_cqs") == 1).then(pl.lit(0.20))
                .when(pl.col("guarantor_cqs") == 2).then(pl.lit(0.50))
                .when(pl.col("guarantor_cqs").is_in([3, 4])).then(pl.lit(1.0))
                .when(pl.col("guarantor_cqs").is_in([5, 6])).then(pl.lit(1.50))
                .otherwise(pl.lit(1.0))
            )
            .otherwise(pl.lit(None).cast(pl.Float64))
            .alias("guarantor_rw"),
        ])

        return lf

    def blend_guarantee_rw(self) -> pl.LazyFrame:
        """
        Calculate blended risk weight for guaranteed exposures.

        Blends borrower and guarantor risk weights based on portions.

        Returns:
            LazyFrame with blended risk_weight
        """
        schema = self._lf.collect_schema()
        cols = schema.names()

        if "guarantor_rw" not in cols or "guaranteed_portion" not in cols:
            return self._lf

        ead_col = "ead_final" if "ead_final" in cols else "ead"

        return self._lf.with_columns([
            pl.when(
                (pl.col("guaranteed_portion") > 0) &
                (pl.col("guarantor_rw").is_not_null())
            ).then(
                (
                    pl.col("unguaranteed_portion") * pl.col("risk_weight") +
                    pl.col("guaranteed_portion") * pl.col("guarantor_rw")
                ) / pl.col(ead_col)
            )
            .otherwise(pl.col("risk_weight"))
            .alias("risk_weight"),
        ])

    # =========================================================================
    # RWA CALCULATION METHODS
    # =========================================================================

    def calculate_rwa(self) -> pl.LazyFrame:
        """
        Calculate RWA = EAD x Risk Weight.

        Returns:
            LazyFrame with rwa_pre_factor column
        """
        schema = self._lf.collect_schema()
        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"

        return self._lf.with_columns([
            (pl.col(ead_col) * pl.col("risk_weight")).alias("rwa_pre_factor"),
        ])

    # =========================================================================
    # SUPPORTING FACTORS METHODS
    # =========================================================================

    def apply_supporting_factors(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply SME and infrastructure supporting factors.

        Delegates to SupportingFactorCalculator.

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with supporting factors applied
        """
        from rwa_calc.engine.sa.supporting_factors import SupportingFactorCalculator

        calculator = SupportingFactorCalculator()
        return calculator.apply_factors(self._lf, config)

    # =========================================================================
    # CONVENIENCE / PIPELINE METHODS
    # =========================================================================

    def apply_all(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply full SA calculation pipeline.

        Steps:
        1. Prepare columns
        2. Apply risk weights
        3. Calculate RWA
        4. Apply supporting factors

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with all SA calculations
        """
        return (self._lf
            .sa.prepare_columns(config)
            .sa.apply_risk_weights(config)
            .sa.calculate_rwa()
            .sa.apply_supporting_factors(config)
        )

    def build_audit(self) -> pl.LazyFrame:
        """
        Build SA calculation audit trail.

        Returns:
            LazyFrame with audit columns including sa_calculation string
        """
        schema = self._lf.collect_schema()
        available_cols = schema.names()

        select_cols = ["exposure_reference"]
        optional_cols = [
            "counterparty_reference",
            "exposure_class",
            "cqs",
            "ltv",
            "ead_final",
            "risk_weight",
            "rwa_pre_factor",
            "supporting_factor",
            "rwa_post_factor",
            "supporting_factor_applied",
        ]

        for col in optional_cols:
            if col in available_cols:
                select_cols.append(col)

        audit = self._lf.select(select_cols)

        # Add calculation string
        if "rwa_post_factor" in available_cols:
            audit = audit.with_columns([
                pl.concat_str([
                    pl.lit("SA: EAD="),
                    pl.col("ead_final").round(0).cast(pl.String),
                    pl.lit(" x RW="),
                    (pl.col("risk_weight") * 100).round(1).cast(pl.String),
                    pl.lit("% x SF="),
                    (pl.col("supporting_factor") * 100).round(2).cast(pl.String),
                    pl.lit("% -> RWA="),
                    pl.col("rwa_post_factor").round(0).cast(pl.String),
                ]).alias("sa_calculation"),
            ])
        elif "rwa_pre_factor" in available_cols:
            audit = audit.with_columns([
                pl.concat_str([
                    pl.lit("SA: EAD="),
                    pl.col("ead_final").round(0).cast(pl.String),
                    pl.lit(" x RW="),
                    (pl.col("risk_weight") * 100).round(1).cast(pl.String),
                    pl.lit("% -> RWA="),
                    pl.col("rwa_pre_factor").round(0).cast(pl.String),
                ]).alias("sa_calculation"),
            ])

        return audit


# =============================================================================
# EXPRESSION NAMESPACE
# =============================================================================


@pl.api.register_expr_namespace("sa")
class SAExpr:
    """
    SA calculation namespace for Polars Expressions.

    Provides column-level operations for SA calculations.

    Example:
        df.with_columns(
            pl.col("ltv").sa.apply_ltv_weight(
                [0.8, 1.0],
                [0.35, 0.75, 1.0]
            ),
        )
    """

    def __init__(self, expr: pl.Expr) -> None:
        self._expr = expr

    def apply_ltv_weight(
        self,
        thresholds: list[float],
        weights: list[float],
    ) -> pl.Expr:
        """
        Apply LTV-based risk weight using thresholds.

        Args:
            thresholds: LTV threshold values (ascending)
            weights: Risk weights for each band (one more than thresholds)

        Returns:
            Expression with risk weight based on LTV
        """
        if len(weights) != len(thresholds) + 1:
            raise ValueError("weights must have one more element than thresholds")

        # Build nested when/then for thresholds
        result = pl.when(self._expr <= thresholds[0]).then(pl.lit(weights[0]))

        for i, threshold in enumerate(thresholds[1:], start=1):
            result = result.when(self._expr <= threshold).then(pl.lit(weights[i]))

        return result.otherwise(pl.lit(weights[-1]))

    def lookup_cqs_rw(
        self,
        exposure_class: str,
        use_uk_deviation: bool = False,
    ) -> pl.Expr:
        """
        Look up CQS-based risk weight.

        Args:
            exposure_class: Exposure class (CENTRAL_GOVT_CENTRAL_BANK, INSTITUTION, CORPORATE)
            use_uk_deviation: Whether to use UK deviation for institutions

        Returns:
            Expression with risk weight based on CQS
        """
        rw_table = get_combined_cqs_risk_weights(use_uk_deviation)

        # Filter to relevant class
        class_rw = rw_table.filter(pl.col("exposure_class") == exposure_class)

        # Build lookup
        if exposure_class == "CENTRAL_GOVT_CENTRAL_BANK":
            return (
                pl.when(self._expr == 1).then(pl.lit(0.0))
                .when(self._expr == 2).then(pl.lit(0.20))
                .when(self._expr == 3).then(pl.lit(0.50))
                .when(self._expr.is_in([4, 5])).then(pl.lit(1.0))
                .when(self._expr == 6).then(pl.lit(1.50))
                .otherwise(pl.lit(1.0))
            )
        elif exposure_class == "INSTITUTION":
            cqs2_rw = 0.30 if use_uk_deviation else 0.50
            return (
                pl.when(self._expr == 1).then(pl.lit(0.20))
                .when(self._expr == 2).then(pl.lit(cqs2_rw))
                .when(self._expr == 3).then(pl.lit(0.50))
                .when(self._expr.is_in([4, 5])).then(pl.lit(1.0))
                .when(self._expr == 6).then(pl.lit(1.50))
                .otherwise(pl.lit(0.40))
            )
        else:  # CORPORATE
            return (
                pl.when(self._expr == 1).then(pl.lit(0.20))
                .when(self._expr == 2).then(pl.lit(0.50))
                .when(self._expr.is_in([3, 4])).then(pl.lit(1.0))
                .when(self._expr.is_in([5, 6])).then(pl.lit(1.50))
                .otherwise(pl.lit(1.0))
            )
