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

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.data.tables.crr_firb_lgd import FIRB_SUPERVISORY_LGD
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.irb.formulas import (
    _polars_correlation_expr,
    _polars_capital_k_expr,
    _polars_maturity_adjustment_expr,
)


def _exact_fractional_years_expr(
    start_date: date,
    end_col: str,
) -> pl.Expr:
    """
    Calculate fractional years between a fixed start date and an end date column.

    Uses the year fraction method where each day represents 1/365 of a year,
    regardless of leap years. This provides consistent treatment across all
    periods and is standard for regulatory maturity calculations (CRR Article 162).

    Formula:
        years = (end_year - start_year) + (end_ordinal/365) - (start_ordinal/365)

    This treats each day-of-year as a fraction of 365, ensuring leap days don't
    cause inconsistencies in maturity calculations.

    Works with LazyFrames and streaming (pure expression-based).

    Args:
        start_date: The fixed start date (e.g., reporting_date from config)
        end_col: Name of the end date column

    Returns:
        Polars expression calculating fractional years
    """
    end = pl.col(end_col)

    # Pre-compute start date components (scalar values)
    start_year = start_date.year
    start_ordinal = start_date.timetuple().tm_yday
    start_frac = start_ordinal / 365.0

    # End date components (from column)
    end_year = end.dt.year()
    end_ordinal = end.dt.ordinal_day()
    end_frac = end_ordinal.cast(pl.Float64) / 365.0

    # Year fraction = year difference + ordinal adjustment
    return (end_year - start_year).cast(pl.Float64) + (end_frac - pl.lit(start_frac))


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
        has_seniority = "seniority" in schema.names()
        has_lgd_post_crm = "lgd_post_crm" in schema.names()

        lf = self._lf
        if "lgd" not in schema.names():
            lf = lf.with_columns([
                pl.lit(None).cast(pl.Float64).alias("lgd"),
            ])
        elif schema["lgd"] != pl.Float64:
            # Cast lgd to Float64 if it's not already (handles String type from Excel imports)
            lf = lf.with_columns([
                pl.col("lgd").cast(pl.Float64, strict=False).alias("lgd"),
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

        # For lgd_input, use lgd_post_crm (from CRM processor) if available
        # This ensures collateral-adjusted LGD is used for F-IRB risk weight calculation
        if has_lgd_post_crm:
            return lf.with_columns([
                pl.when(pl.col("approach") == ApproachType.FIRB.value)
                .then(pl.col("lgd_post_crm"))
                .otherwise(pl.col("lgd"))
                .alias("lgd_input"),
            ])
        else:
            return lf.with_columns([
                pl.col("lgd").alias("lgd_input"),
            ])

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
                        _exact_fractional_years_expr(
                            config.reporting_date, "maturity_date"
                        ).clip(1.0, 5.0)
                    )
                    .otherwise(pl.lit(5.0))
                    .alias("maturity"),
                )
            else:
                exprs.append(pl.lit(5.0).alias("maturity"))

        # Turnover for SME correlation adjustment
        if "turnover_m" not in names:
            if "cp_annual_revenue" in names:
                exprs.append(
                    (pl.col("cp_annual_revenue") / 1_000_000.0).alias("turnover_m")
                )
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

        Uses lgd_input (which contains collateral-adjusted LGD for F-IRB)
        as the base for flooring.

        CRR: No LGD floor
        Basel 3.1: 25% unsecured, varies by collateral

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with lgd_floored column
        """
        # Use lgd_input which has collateral-adjusted LGD for F-IRB
        schema = self._lf.collect_schema()
        lgd_col = "lgd_input" if "lgd_input" in schema.names() else "lgd"

        if config.is_basel_3_1:
            lgd_floor = float(config.lgd_floors.unsecured)
            return self._lf.with_columns(
                pl.col(lgd_col).clip(lower_bound=lgd_floor).alias("lgd_floored")
            )
        return self._lf.with_columns(
            pl.col(lgd_col).alias("lgd_floored")
        )

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
    # DEFAULTED EXPOSURE TREATMENT
    # =========================================================================

    def apply_defaulted_treatment(self, config: CalculationConfig) -> pl.LazyFrame:
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
            config: Calculation configuration

        Returns:
            LazyFrame with defaulted rows overwritten
        """
        schema = self._lf.collect_schema()
        cols = schema.names()

        # No-op if is_defaulted column doesn't exist
        if "is_defaulted" not in cols:
            return self._lf

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
        lf = self._lf
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
        lf = lf.with_columns([
            pl.when(is_defaulted).then(k_defaulted).otherwise(pl.col("k")).alias("k"),
            pl.when(is_defaulted).then(pl.lit(0.0)).otherwise(pl.col("correlation")).alias("correlation"),
            pl.when(is_defaulted).then(pl.lit(1.0)).otherwise(pl.col("maturity_adjustment")).alias("maturity_adjustment"),
            pl.when(is_defaulted).then(rwa_defaulted).otherwise(pl.col("rwa")).alias("rwa"),
            pl.when(is_defaulted).then(rw_defaulted).otherwise(pl.col("risk_weight")).alias("risk_weight"),
            pl.when(is_defaulted).then(el_defaulted).otherwise(pl.col("expected_loss")).alias("expected_loss"),
        ])

        return lf

    # =========================================================================
    # GUARANTEE SUBSTITUTION
    # =========================================================================

    def apply_guarantee_substitution(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply guarantee substitution for IRB exposures with unfunded credit protection.

        For guaranteed portions with eligible guarantors (e.g., sovereign CQS 1),
        the RWA for the guaranteed portion is calculated using the guarantor's
        risk characteristics instead of the borrower's.

        Under CRR Art. 215-217 for IRB:
        - For sovereign guarantors with CQS 1: apply 0% RW to guaranteed portion
        - For other guarantors: apply SA risk weight based on guarantor entity type/CQS
        - Unguaranteed portion uses borrower's IRB-calculated RWA

        The final RWA is a blend of:
        - Unguaranteed portion × borrower's IRB RWA
        - Guaranteed portion × guarantor's equivalent RWA (0 for sovereign CQS 1)

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with guarantee-adjusted RWA
        """
        schema = self._lf.collect_schema()
        cols = schema.names()

        # Check if guarantee columns exist
        if "guaranteed_portion" not in cols or "guarantor_entity_type" not in cols:
            # No guarantee data, return as-is
            return self._lf

        # Check if expected_loss column exists (may not be present in all pipelines)
        has_expected_loss = "expected_loss" in cols

        # Store original IRB values before substitution (pre-CRM values)
        # These are needed for regulatory reporting (pre-CRM vs post-CRM views)
        store_originals = [
            pl.col("rwa").alias("rwa_irb_original"),
            pl.col("risk_weight").alias("risk_weight_irb_original"),
            # Consistent naming for pre-CRM reporting
            pl.col("risk_weight").alias("pre_crm_risk_weight"),
            pl.col("rwa").alias("pre_crm_rwa"),
        ]
        if has_expected_loss:
            store_originals.append(pl.col("expected_loss").alias("expected_loss_irb_original"))

        lf = self._lf.with_columns(store_originals)

        # Calculate guarantor's risk weight based on entity type and CQS
        # Using SA risk weights for substitution (per CRR Art. 215-217)
        use_uk_deviation = config.base_currency == "GBP"

        lf = lf.with_columns([
            pl.when(pl.col("guaranteed_portion").fill_null(0) <= 0)
            .then(pl.lit(None).cast(pl.Float64))
            # Sovereign guarantors - CQS 1 gets 0%
            .when(pl.col("guarantor_entity_type").fill_null("").str.contains("(?i)sovereign"))
            .then(
                pl.when(pl.col("guarantor_cqs") == 1).then(pl.lit(0.0))
                .when(pl.col("guarantor_cqs") == 2).then(pl.lit(0.20))
                .when(pl.col("guarantor_cqs") == 3).then(pl.lit(0.50))
                .when(pl.col("guarantor_cqs").is_in([4, 5])).then(pl.lit(1.0))
                .when(pl.col("guarantor_cqs") == 6).then(pl.lit(1.50))
                .otherwise(pl.lit(1.0))  # Unrated
            )
            # Institution guarantors (UK deviation: CQS 2 = 30%)
            .when(pl.col("guarantor_entity_type").fill_null("").str.contains("(?i)institution"))
            .then(
                pl.when(pl.col("guarantor_cqs") == 1).then(pl.lit(0.20))
                .when(pl.col("guarantor_cqs") == 2).then(pl.lit(0.30) if use_uk_deviation else pl.lit(0.50))
                .when(pl.col("guarantor_cqs") == 3).then(pl.lit(0.50))
                .when(pl.col("guarantor_cqs").is_in([4, 5])).then(pl.lit(1.0))
                .when(pl.col("guarantor_cqs") == 6).then(pl.lit(1.50))
                .otherwise(pl.lit(0.40))  # Unrated
            )
            # Corporate guarantors
            .when(pl.col("guarantor_entity_type").fill_null("").str.contains("(?i)corporate"))
            .then(
                pl.when(pl.col("guarantor_cqs") == 1).then(pl.lit(0.20))
                .when(pl.col("guarantor_cqs") == 2).then(pl.lit(0.50))
                .when(pl.col("guarantor_cqs").is_in([3, 4])).then(pl.lit(1.0))
                .when(pl.col("guarantor_cqs").is_in([5, 6])).then(pl.lit(1.50))
                .otherwise(pl.lit(1.0))  # Unrated
            )
            # Unknown entity type - no substitution
            .otherwise(pl.lit(None).cast(pl.Float64))
            .alias("guarantor_rw"),
        ])

        # Determine EAD column
        ead_col = "ead_final" if "ead_final" in cols else "ead"

        # Check if guarantee is beneficial (guarantor RW < borrower IRB RW)
        # Non-beneficial guarantees should NOT be applied per CRR Art. 213
        lf = lf.with_columns([
            pl.when(
                (pl.col("guaranteed_portion").fill_null(0) > 0) &
                (pl.col("guarantor_rw").is_not_null()) &
                (pl.col("guarantor_rw") < pl.col("risk_weight_irb_original"))
            )
            .then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("is_guarantee_beneficial"),
        ])

        # Calculate blended RWA using substitution approach
        # Only apply if guarantee is beneficial
        # For guaranteed portion: use guarantor_rw × guaranteed_portion
        # For unguaranteed portion: use IRB-calculated RWA proportionally
        lf = lf.with_columns([
            # Calculate RWA for guaranteed portion using guarantor RW
            # Only if guarantee is beneficial
            pl.when(
                (pl.col("guaranteed_portion").fill_null(0) > 0) &
                (pl.col("guarantor_rw").is_not_null()) &
                (pl.col("is_guarantee_beneficial"))
            ).then(
                # Blended RWA = unguaranteed_IRB_RWA + guaranteed_portion × guarantor_RW
                # The IRB RWA is for the full exposure, so we need to pro-rate it
                pl.col("rwa_irb_original") * (pl.col("unguaranteed_portion") / pl.col(ead_col)).fill_null(1.0) +
                pl.col("guaranteed_portion") * pl.col("guarantor_rw")
            )
            # No guarantee, no guarantor RW, or non-beneficial - use original IRB RWA
            .otherwise(pl.col("rwa_irb_original"))
            .alias("rwa"),
        ])

        # Calculate blended risk weight for reporting
        lf = lf.with_columns([
            (pl.col("rwa") / pl.col(ead_col)).fill_null(0.0).alias("risk_weight"),
        ])

        # Adjust expected loss for SA-guaranteed portion
        # SA has no EL concept (CRR Art. 158-159), so only unguaranteed portion retains IRB EL
        # For IRB guarantors, EL unchanged (PD substitution not yet implemented)
        if has_expected_loss:
            lf = lf.with_columns([
                pl.when(
                    (pl.col("guaranteed_portion").fill_null(0) > 0) &
                    (pl.col("guarantor_rw").is_not_null()) &
                    (pl.col("is_guarantee_beneficial")) &
                    (pl.col("guarantor_approach").fill_null("") == "sa")
                ).then(
                    # SA portion has no EL — only unguaranteed portion retains IRB EL
                    pl.col("expected_loss_irb_original") * (
                        pl.col("unguaranteed_portion") / pl.col(ead_col)
                    ).fill_null(1.0)
                )
                .otherwise(pl.col("expected_loss_irb_original"))
                .alias("expected_loss"),
            ])

        # Track guarantee status for reporting
        lf = lf.with_columns([
            pl.when(pl.col("guaranteed_portion").fill_null(0) <= 0)
            .then(pl.lit("NO_GUARANTEE"))
            .when(~pl.col("is_guarantee_beneficial"))
            .then(pl.lit("GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"))
            .otherwise(pl.lit("SA_RW_SUBSTITUTION"))
            .alias("guarantee_status"),

            # Track which method was used (SA RW for now, PD substitution not yet implemented)
            pl.when(
                (pl.col("guaranteed_portion").fill_null(0) > 0) &
                (pl.col("is_guarantee_beneficial"))
            )
            .then(pl.lit("SA_RW_SUBSTITUTION"))
            .otherwise(pl.lit("NO_SUBSTITUTION"))
            .alias("guarantee_method_used"),

            # Calculate RW benefit from guarantee (positive = RW reduced)
            pl.when(pl.col("is_guarantee_beneficial"))
            .then(pl.col("risk_weight_irb_original") - pl.col("risk_weight"))
            .otherwise(pl.lit(0.0))
            .alias("guarantee_benefit_rw"),
        ])

        return lf

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

        pd_floor = float(config.pd_floors.corporate)
        batch1.append(
            pl.col("pd").clip(lower_bound=pd_floor).alias("pd_floored")
        )

        lgd_col = "lgd_input" if "lgd_input" in schema_names else "lgd"
        if config.is_basel_3_1:
            lgd_floor = float(config.lgd_floors.unsecured)
            batch1.append(
                pl.col(lgd_col).clip(lower_bound=lgd_floor).alias("lgd_floored")
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
        lf = lf.with_columns([
            _polars_correlation_expr(eur_gbp_rate=eur_gbp_rate).alias("correlation"),
            pl.when(is_retail)
            .then(pl.lit(1.0))
            .otherwise(_polars_maturity_adjustment_expr())
            .alias("maturity_adjustment"),
        ])

        # --- Batch 3: K (reads correlation from batch 2) ---
        lf = lf.with_columns(
            _polars_capital_k_expr().alias("k")
        )

        # --- Batch 4: RWA + risk weight + expected loss ---
        scaling_factor = 1.06 if config.is_crr else 1.0
        lf = lf.with_columns([
            pl.lit(scaling_factor).alias("scaling_factor"),
            (
                pl.col("k") * 12.5 * scaling_factor
                * pl.col("ead_final") * pl.col("maturity_adjustment")
            ).alias("rwa"),
            (
                pl.col("k") * 12.5 * scaling_factor
                * pl.col("maturity_adjustment")
            ).alias("risk_weight"),
            (
                pl.col("pd_floored") * pl.col("lgd_floored") * pl.col("ead_final")
            ).alias("expected_loss"),
        ])

        # Defaulted treatment (overrides for PD=100% exposures)
        return lf.irb.apply_defaulted_treatment(config)

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
                    if has_is_airb else pl.lit(False)
                )
                .then(
                    pl.concat_str([
                        pl.lit("IRB DEFAULTED A-IRB: K=max(0, LGD-BEEL)="),
                        (pl.col("k") * 100).round(3).cast(pl.String),
                        pl.lit("%, LGD="),
                        (pl.col("lgd_floored") * 100).round(1).cast(pl.String),
                        pl.lit("%, BEEL="),
                        (pl.col("beel").fill_null(0.0) * 100).round(1).cast(pl.String) if "beel" in available_cols else pl.lit("0.0"),
                        pl.lit("% → RWA="),
                        pl.col("rwa").round(0).cast(pl.String),
                    ])
                )
                .otherwise(
                    pl.lit("IRB DEFAULTED F-IRB: K=0, RW=0 → RWA=0")
                )
            )

            standard_str = pl.concat_str([
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
            ])

            return audit.with_columns([
                pl.when(pl.col("is_defaulted").fill_null(False))
                .then(defaulted_str)
                .otherwise(standard_str)
                .alias("irb_calculation"),
            ])

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
