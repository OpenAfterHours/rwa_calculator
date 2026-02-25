"""
Standardised Approach (SA) Calculator for RWA.

Implements CRR Art. 112-134 risk weight lookups and RWA calculation.
Supports both CRR and Basel 3.1 frameworks with appropriate risk weights.

Pipeline position:
    CRMProcessor -> SACalculator -> OutputAggregator

Key responsibilities:
- Risk weight lookup by exposure class and CQS
- LTV-based weights for real estate
- Supporting factor application (CRR only)
- RWA calculation (EAD × RW × supporting factor)

References:
- CRR Art. 112-134: SA risk weights
- CRR Art. 501: SME supporting factor
- CRR Art. 501a: Infrastructure supporting factor
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import CRMAdjustedBundle, SAResultBundle
from rwa_calc.contracts.errors import (
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    LazyFrameResult,
)
from rwa_calc.data.tables.crr_risk_weights import (
    get_combined_cqs_risk_weights,
    RESIDENTIAL_MORTGAGE_PARAMS,
    COMMERCIAL_RE_PARAMS,
    RETAIL_RISK_WEIGHT,
)
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.sa.supporting_factors import SupportingFactorCalculator

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


@dataclass
class SACalculationError:
    """Error during SA calculation."""

    error_type: str
    message: str
    exposure_reference: str | None = None


class SACalculator:
    """
    Calculate RWA using Standardised Approach.

    Implements SACalculatorProtocol for:
    - CQS-based risk weight lookup (sovereign, institution, corporate)
    - Fixed retail risk weight (75%)
    - LTV-based real estate risk weights
    - Supporting factor application (CRR only)

    Usage:
        calculator = SACalculator()
        result = calculator.calculate(crm_bundle, config)
    """

    def __init__(self) -> None:
        """Initialize SA calculator with sub-components."""
        self._supporting_factor_calc = SupportingFactorCalculator()
        self._risk_weight_tables: dict[str, pl.DataFrame] | None = None

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate RWA using Standardised Approach.

        Args:
            data: CRM-adjusted exposures (uses sa_exposures)
            config: Calculation configuration

        Returns:
            LazyFrameResult with SA RWA calculations
        """
        bundle = self.get_sa_result_bundle(data, config)

        # Convert bundle errors to CalculationErrors
        calc_errors = [
            CalculationError(
                code="SA001",
                message=str(err),
                severity=ErrorSeverity.ERROR,
                category=ErrorCategory.CALCULATION,
            )
            for err in bundle.errors
        ]

        return LazyFrameResult(
            frame=bundle.results,
            errors=calc_errors,
        )

    def get_sa_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> SAResultBundle:
        """
        Calculate SA RWA and return as a bundle.

        Args:
            data: CRM-adjusted exposures
            config: Calculation configuration

        Returns:
            SAResultBundle with results and audit trail
        """
        errors: list[SACalculationError] = []

        # Get SA exposures
        exposures = data.sa_exposures

        # Step 1: Look up risk weights
        exposures = self._apply_risk_weights(exposures, config)

        # Step 2: Apply guarantee substitution (blended risk weight)
        exposures = self._apply_guarantee_substitution(exposures, config)

        # Step 3: Calculate pre-factor RWA
        exposures = self._calculate_rwa(exposures)

        # Step 4: Apply supporting factors (CRR only)
        exposures = self._apply_supporting_factors(exposures, config)

        # Step 5: Build audit trail
        audit = self._build_audit(exposures)

        return SAResultBundle(
            results=exposures,
            calculation_audit=audit,
            errors=errors,
        )

    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply SA risk weights to SA rows on a unified frame.

        Operates on the full unified frame (SA + IRB + slotting rows together).
        Only modifies columns for rows where approach == 'standardised'.

        Steps:
        1. Join risk weight table (unconditional — SA-equivalent RW for output floor)
        2. Apply SA-specific RW overrides (mortgage LTV, retail fixed, etc.)
        3. Apply SA guarantee substitution
        4. Calculate RWA = EAD x RW (SA rows only)
        5. Apply supporting factors (SA rows only)

        Args:
            exposures: Unified frame with all approaches
            config: Calculation configuration

        Returns:
            Unified frame with SA columns populated for SA rows
        """
        is_sa = pl.col("approach") == ApproachType.SA.value

        # Step 1-2: Apply risk weights (runs unconditionally — also provides
        # SA-equivalent RW for IRB output floor)
        exposures = self._apply_risk_weights(exposures, config)

        # Step 3: Guarantee substitution (already conditional on guaranteed_portion > 0)
        exposures = self._apply_guarantee_substitution(exposures, config)

        # Step 4: Calculate pre-factor RWA (SA rows only)
        schema = exposures.collect_schema()
        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"
        exposures = exposures.with_columns([
            pl.when(is_sa)
            .then(pl.col(ead_col) * pl.col("risk_weight"))
            .otherwise(pl.col("rwa_pre_factor") if "rwa_pre_factor" in schema.names() else pl.lit(None).cast(pl.Float64))
            .alias("rwa_pre_factor"),
        ])

        # Step 5: Apply supporting factors (SA rows only)
        exposures = self._apply_supporting_factors(exposures, config)

        return exposures

    def _apply_risk_weights(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Look up and apply risk weights based on exposure class.

        Handles:
        - CQS-based lookups (sovereign, institution, corporate)
        - Fixed retail (75%)
        - LTV-based real estate (split treatment)

        Args:
            exposures: SA exposures with classification
            config: Calculation configuration

        Returns:
            Exposures with risk_weight column added
        """
        # Get CQS-based risk weight table (includes UK deviation for institutions)
        use_uk_deviation = config.base_currency == "GBP"
        rw_table = get_combined_cqs_risk_weights(use_uk_deviation).lazy()

        # Ensure required columns exist
        schema = exposures.collect_schema()
        if "ltv" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit(None).cast(pl.Float64).alias("ltv"),
            ])
        if "has_income_cover" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit(False).alias("has_income_cover"),
            ])
        if "book_code" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit("").alias("book_code"),
            ])
        if "cp_is_managed_as_retail" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit(False).alias("cp_is_managed_as_retail"),
            ])

        # Prepare exposures for join
        # Normalize exposure class names for matching
        # Use sentinel value -1 for null CQS to allow join (null != null in joins)
        exposures = exposures.with_columns([
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
        exposures = exposures.join(
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

        exposures = exposures.with_columns([
            # Order matters: check specific classes before generic ones
            # 1. Residential mortgage: LTV-based (must come before retail)
            pl.when(pl.col("exposure_class").str.contains("(?i)mortgage|residential"))
            .then(
                pl.when(pl.col("ltv").fill_null(0.0) <= resi_threshold)
                .then(pl.lit(resi_rw_low))
                # High LTV: weighted average
                .otherwise(
                    # portion_low = threshold / ltv
                    # portion_high = (ltv - threshold) / ltv
                    # avg_rw = rw_low * portion_low + rw_high * portion_high
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

            # 4. Corporate SME: 100% RW (then reduced by SME supporting factor)
            .when(pl.col("exposure_class").str.contains("(?i)corporate.*sme|sme.*corporate"))
            .then(pl.lit(1.0))

            # 5. Retail (non-mortgage): 75% flat
            .when(pl.col("exposure_class").str.contains("(?i)retail"))
            .then(pl.lit(retail_rw))

            # 5. Default: use joined CQS-based risk weight, or 100%
            .otherwise(pl.col("risk_weight").fill_null(1.0))
            .alias("risk_weight"),
        ])

        # Clean up temporary columns
        exposures = exposures.drop([
            col for col in ["_lookup_class", "_lookup_cqs", "risk_weight_rw"]
            if col in exposures.collect_schema().names()
        ])

        return exposures

    def _apply_guarantee_substitution(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply guarantee substitution for unfunded credit protection.

        For guaranteed portions, the risk weight is substituted with the
        guarantor's risk weight. The final RWA is calculated using blended
        risk weight based on guaranteed vs unguaranteed portions.

        CRR Art. 213-217: Unfunded credit protection

        Args:
            exposures: Exposures with risk_weight and guarantee columns
            config: Calculation configuration

        Returns:
            Exposures with guarantee substitution applied
        """
        schema = exposures.collect_schema()
        cols = schema.names()

        # Check if guarantee columns exist
        if "guaranteed_portion" not in cols or "guarantor_entity_type" not in cols:
            # No guarantee data, return as-is
            return exposures

        # Preserve pre-CRM risk weight before any guarantee substitution
        # This is needed for regulatory reporting (pre-CRM vs post-CRM views)
        exposures = exposures.with_columns([
            pl.col("risk_weight").alias("pre_crm_risk_weight"),
        ])

        # Calculate guarantor's risk weight based on entity type and CQS
        # Use UK deviation for institutions (30% for CQS 2 instead of 50%)
        use_uk_deviation = config.base_currency == "GBP"

        # Guarantor risk weights by entity type and CQS
        # Sovereign: 0%, 20%, 50%, 100%, 100%, 150%
        # Institution (UK): 20%, 30%, 50%, 100%, 100%, 150%
        # Corporate: 20%, 50%, 100%, 100%, 150%, 150%
        exposures = exposures.with_columns([
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
                .otherwise(pl.lit(1.0))  # Unrated
            )
            # Institution guarantors (UK deviation: CQS 2 = 30%)
            .when(pl.col("guarantor_entity_type").str.contains("(?i)institution"))
            .then(
                pl.when(pl.col("guarantor_cqs") == 1).then(pl.lit(0.20))
                .when(pl.col("guarantor_cqs") == 2).then(pl.lit(0.30) if use_uk_deviation else pl.lit(0.50))
                .when(pl.col("guarantor_cqs") == 3).then(pl.lit(0.50))
                .when(pl.col("guarantor_cqs").is_in([4, 5])).then(pl.lit(1.0))
                .when(pl.col("guarantor_cqs") == 6).then(pl.lit(1.50))
                .otherwise(pl.lit(0.40))  # Unrated
            )
            # Corporate guarantors
            .when(pl.col("guarantor_entity_type").str.contains("(?i)corporate"))
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

        # Check if guarantee is beneficial (guarantor RW < borrower RW)
        # Non-beneficial guarantees should NOT be applied per CRR Art. 213
        exposures = exposures.with_columns([
            pl.when(
                (pl.col("guaranteed_portion") > 0) &
                (pl.col("guarantor_rw").is_not_null()) &
                (pl.col("guarantor_rw") < pl.col("pre_crm_risk_weight"))
            )
            .then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("is_guarantee_beneficial"),
        ])

        # Calculate blended risk weight using substitution approach
        # Only apply if guarantee is beneficial
        # RWA = (unguaranteed_portion * borrower_rw + guaranteed_portion * guarantor_rw) / ead_final
        ead_col = "ead_final" if "ead_final" in cols else "ead"

        exposures = exposures.with_columns([
            # Blended risk weight when guarantee exists AND is beneficial
            pl.when(
                (pl.col("guaranteed_portion") > 0) &
                (pl.col("guarantor_rw").is_not_null()) &
                (pl.col("is_guarantee_beneficial"))
            ).then(
                # weighted average of borrower and guarantor risk weights
                (
                    pl.col("unguaranteed_portion") * pl.col("pre_crm_risk_weight") +
                    pl.col("guaranteed_portion") * pl.col("guarantor_rw")
                ) / pl.col(ead_col)
            )
            # No guarantee, no guarantor RW, or non-beneficial - use original risk weight
            .otherwise(pl.col("pre_crm_risk_weight"))
            .alias("risk_weight"),
        ])

        # Track guarantee status for reporting
        exposures = exposures.with_columns([
            pl.when(pl.col("guaranteed_portion") <= 0)
            .then(pl.lit("NO_GUARANTEE"))
            .when(~pl.col("is_guarantee_beneficial"))
            .then(pl.lit("GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"))
            .otherwise(pl.lit("SA_RW_SUBSTITUTION"))
            .alias("guarantee_status"),

            # Calculate RW benefit from guarantee (positive = RW reduced)
            pl.when(pl.col("is_guarantee_beneficial"))
            .then(pl.col("pre_crm_risk_weight") - pl.col("risk_weight"))
            .otherwise(pl.lit(0.0))
            .alias("guarantee_benefit_rw"),
        ])

        return exposures

    def _calculate_rwa(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Calculate RWA = EAD × Risk Weight.

        Args:
            exposures: Exposures with ead_final and risk_weight

        Returns:
            Exposures with rwa_pre_factor column
        """
        # Determine EAD column (ead_final preferred, fallback to ead)
        schema = exposures.collect_schema()
        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"

        return exposures.with_columns([
            (pl.col(ead_col) * pl.col("risk_weight")).alias("rwa_pre_factor"),
        ])

    def _apply_supporting_factors(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply SME and infrastructure supporting factors.

        Args:
            exposures: Exposures with rwa_pre_factor
            config: Calculation configuration

        Returns:
            Exposures with supporting factors applied
        """
        # Ensure required columns exist for supporting factor calculation
        schema = exposures.collect_schema()

        if "is_sme" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit(False).alias("is_sme"),
            ])

        if "is_infrastructure" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit(False).alias("is_infrastructure"),
            ])

        if "ead_final" not in schema.names():
            exposures = exposures.with_columns([
                pl.col("ead").alias("ead_final"),
            ])

        return self._supporting_factor_calc.apply_factors(exposures, config)

    def _build_audit(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Build SA calculation audit trail.

        Args:
            exposures: Calculated exposures

        Returns:
            Audit trail LazyFrame
        """
        schema = exposures.collect_schema()
        available_cols = schema.names()

        # Select available audit columns
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

        audit = exposures.select(select_cols)

        # Add calculation string
        audit = audit.with_columns([
            pl.concat_str([
                pl.lit("SA: EAD="),
                pl.col("ead_final").round(0).cast(pl.String),
                pl.lit(" × RW="),
                (pl.col("risk_weight") * 100).round(1).cast(pl.String),
                pl.lit("% × SF="),
                (pl.col("supporting_factor") * 100).round(2).cast(pl.String),
                pl.lit("% → RWA="),
                pl.col("rwa_post_factor").round(0).cast(pl.String),
            ]).alias("sa_calculation"),
        ])

        return audit

    def calculate_single_exposure(
        self,
        ead: Decimal,
        exposure_class: str,
        cqs: int | None = None,
        ltv: Decimal | None = None,
        is_sme: bool = False,
        is_infrastructure: bool = False,
        is_managed_as_retail: bool = False,
        config: CalculationConfig | None = None,
    ) -> dict:
        """
        Calculate RWA for a single exposure (convenience method).

        Args:
            ead: Exposure at default
            exposure_class: Exposure class
            cqs: Credit quality step (1-6 or None for unrated)
            ltv: Loan-to-value ratio (for real estate)
            is_sme: Whether SME supporting factor applies
            is_infrastructure: Whether infrastructure factor applies
            is_managed_as_retail: Whether SME is managed on pooled retail basis (CRR Art. 123)
            config: Calculation configuration (defaults to CRR)

        Returns:
            Dictionary with calculation results
        """
        from datetime import date
        from rwa_calc.contracts.config import CalculationConfig

        if config is None:
            config = CalculationConfig.crr(reporting_date=date.today())

        # Create single-row DataFrame
        df = pl.DataFrame({
            "exposure_reference": ["SINGLE"],
            "ead_final": [float(ead)],
            "exposure_class": [exposure_class],
            "cqs": [cqs],
            "ltv": [float(ltv) if ltv else None],
            "is_sme": [is_sme],
            "is_infrastructure": [is_infrastructure],
            "has_income_cover": [False],
            "cp_is_managed_as_retail": [is_managed_as_retail],
        }).lazy()

        # Apply risk weights
        df = self._apply_risk_weights(df, config)
        df = self._calculate_rwa(df)
        df = self._apply_supporting_factors(df, config)

        # Collect result
        result = df.collect().to_dicts()[0]

        return {
            "ead": ead,
            "exposure_class": exposure_class,
            "cqs": cqs,
            "risk_weight": Decimal(str(result["risk_weight"])),
            "rwa_pre_factor": Decimal(str(result["rwa_pre_factor"])),
            "supporting_factor": Decimal(str(result["supporting_factor"])),
            "rwa": Decimal(str(result["rwa_post_factor"])),
            "supporting_factor_applied": result["supporting_factor_applied"],
        }


def create_sa_calculator() -> SACalculator:
    """
    Create an SA calculator instance.

    Returns:
        SACalculator ready for use
    """
    return SACalculator()
