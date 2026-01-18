"""
IRB (Internal Ratings-Based) Calculator for RWA.

Implements CRR Art. 153-154 for F-IRB and A-IRB approaches.
Supports both CRR and Basel 3.1 frameworks with appropriate floors.

Pipeline position:
    CRMProcessor -> IRBCalculator -> OutputAggregator

Key responsibilities:
- Apply PD floors (differentiated for Basel 3.1)
- Determine LGD (supervisory for F-IRB, own estimates for A-IRB)
- Calculate asset correlation (with SME adjustment)
- Calculate capital requirement (K)
- Apply maturity adjustment
- Apply 1.06 scaling factor (CRR only)
- Calculate RWA = K × 12.5 × [1.06] × EAD × MA
- Calculate expected loss for provision comparison

References:
- CRR Art. 153-154: IRB risk weight functions
- CRR Art. 161: F-IRB supervisory LGD
- CRR Art. 162: Maturity
- CRR Art. 163: PD floors
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import CRMAdjustedBundle, IRBResultBundle
from rwa_calc.contracts.errors import (
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    LazyFrameResult,
)
from rwa_calc.data.tables.crr_firb_lgd import (
    get_firb_lgd_table,
    lookup_firb_lgd,
    FIRB_SUPERVISORY_LGD,
)
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.irb.formulas import (
    apply_irb_formulas,
    calculate_correlation,
    calculate_irb_rwa,
    calculate_k,
    calculate_maturity_adjustment,
    calculate_expected_loss,
)
from rwa_calc.engine.sa.supporting_factors import SupportingFactorCalculator

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


@dataclass
class IRBCalculationError:
    """Error during IRB calculation."""

    error_type: str
    message: str
    exposure_reference: str | None = None


class IRBCalculator:
    """
    Calculate RWA using IRB approach.

    Implements IRBCalculatorProtocol for:
    - F-IRB: Supervisory LGD, bank's PD
    - A-IRB: Bank's own LGD and PD estimates

    Supports both CRR and Basel 3.1 frameworks:
    - CRR: Single PD floor (0.03%), no LGD floors, 1.06 scaling
    - Basel 3.1: Differentiated PD floors, LGD floors for A-IRB, no scaling

    Usage:
        calculator = IRBCalculator()
        result = calculator.calculate(crm_bundle, config)
    """

    def __init__(self) -> None:
        """Initialize IRB calculator."""
        self._firb_lgd_table: pl.DataFrame | None = None

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate RWA using IRB approach.

        Args:
            data: CRM-adjusted exposures (uses irb_exposures)
            config: Calculation configuration

        Returns:
            LazyFrameResult with IRB RWA calculations
        """
        bundle = self.get_irb_result_bundle(data, config)

        # Convert bundle errors to CalculationErrors
        calc_errors = [
            CalculationError(
                code="IRB001",
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

    def get_irb_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> IRBResultBundle:
        """
        Calculate IRB RWA and return as a bundle.

        Args:
            data: CRM-adjusted exposures
            config: Calculation configuration

        Returns:
            IRBResultBundle with results and audit trail
        """
        errors: list[IRBCalculationError] = []

        # Get IRB exposures
        exposures = data.irb_exposures

        # Step 1: Determine approach (F-IRB vs A-IRB)
        exposures = self._classify_irb_approach(exposures, config)

        # Step 2: Apply F-IRB supervisory LGD where applicable
        exposures = self._apply_firb_lgd(exposures, config)

        # Step 3: Ensure required columns exist
        exposures = self._prepare_columns(exposures, config)

        # Step 4: Apply IRB formulas (PD floor, correlation, K, MA, RWA)
        exposures = apply_irb_formulas(exposures, config)

        # Step 5: Apply supporting factors (CRR only - Art. 501)
        exposures = self._apply_supporting_factors(exposures, config)

        # Step 6: Build audit trail
        audit = self._build_audit(exposures)

        # Step 6: Calculate expected loss
        el_frame = self._calculate_expected_loss(exposures)

        return IRBResultBundle(
            results=exposures,
            expected_loss=el_frame,
            calculation_audit=audit,
            errors=errors,
        )

    def calculate_expected_loss(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate expected loss for IRB exposures.

        EL = PD × LGD × EAD

        Args:
            data: CRM-adjusted exposures
            config: Calculation configuration

        Returns:
            LazyFrameResult with expected loss calculations
        """
        exposures = data.irb_exposures

        # Ensure required columns
        schema = exposures.collect_schema()
        if "pd" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit(0.01).alias("pd"),
            ])
        if "lgd" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit(0.45).alias("lgd"),
            ])

        # Determine EAD column
        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"

        # Calculate EL
        exposures = exposures.with_columns([
            (pl.col("pd") * pl.col("lgd") * pl.col(ead_col)).alias("expected_loss"),
        ])

        return LazyFrameResult(
            frame=exposures.select([
                "exposure_reference",
                "pd", "lgd", ead_col,
                "expected_loss",
            ]),
            errors=[],
        )

    def _classify_irb_approach(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Classify exposures as F-IRB or A-IRB."""
        schema = exposures.collect_schema()

        if "approach" not in schema.names():
            # Default to F-IRB
            exposures = exposures.with_columns([
                pl.lit(ApproachType.FIRB.value).alias("approach"),
            ])

        # Add is_airb flag
        exposures = exposures.with_columns([
            (pl.col("approach") == ApproachType.AIRB.value).alias("is_airb"),
        ])

        return exposures

    def _apply_firb_lgd(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply F-IRB supervisory LGD for Foundation IRB exposures.

        F-IRB uses supervisory LGD values per CRR Art. 161:
        - Senior unsecured: 45%
        - Subordinated: 75%
        - Financial collateral: 0% (after haircuts)
        - Real estate: 35%
        - Other physical: 40%

        A-IRB exposures use their own LGD estimates.
        """
        schema = exposures.collect_schema()

        # Check for seniority and collateral type columns
        has_seniority = "seniority" in schema.names()
        has_collateral = "collateral_type" in schema.names()

        # For F-IRB exposures without LGD, apply supervisory values
        if "lgd" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit(None).cast(pl.Float64).alias("lgd"),
            ])

        # Apply supervisory LGD for F-IRB where LGD is null
        # Default to senior unsecured (45%)
        default_lgd = float(FIRB_SUPERVISORY_LGD["unsecured_senior"])
        sub_lgd = float(FIRB_SUPERVISORY_LGD["subordinated"])

        exposures = exposures.with_columns([
            pl.when(
                (pl.col("approach") == ApproachType.FIRB.value) &
                pl.col("lgd").is_null()
            )
            .then(
                # Use subordinated LGD if flagged, else senior unsecured
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

        # Store original LGD for audit
        exposures = exposures.with_columns([
            pl.col("lgd").alias("lgd_input"),
        ])

        return exposures

    def _prepare_columns(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Ensure all required columns exist with defaults."""
        schema = exposures.collect_schema()

        # PD
        if "pd" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit(0.01).alias("pd"),  # Default 1%
            ])

        # EAD
        if "ead_final" not in schema.names():
            if "ead" in schema.names():
                exposures = exposures.with_columns([
                    pl.col("ead").alias("ead_final"),
                ])
            else:
                exposures = exposures.with_columns([
                    pl.lit(0.0).alias("ead_final"),
                ])

        # Maturity calculation per CRR Art. 162
        # Floor: 1 year, Cap: 5 years
        maturity_floor = 1.0
        maturity_cap = 5.0
        default_maturity = 5.0  # Default if no maturity date available

        if "maturity" not in schema.names():
            if "maturity_date" in schema.names():
                # Calculate maturity from maturity_date - reporting_date
                reporting_date = config.reporting_date
                exposures = exposures.with_columns([
                    pl.when(pl.col("maturity_date").is_not_null())
                    .then(
                        # Calculate years to maturity, apply floor and cap
                        ((pl.col("maturity_date") - pl.lit(reporting_date)).dt.total_days() / 365.0)
                        .clip(maturity_floor, maturity_cap)
                    )
                    .otherwise(pl.lit(default_maturity))
                    .alias("maturity"),
                ])
            else:
                # No maturity date available, use default
                exposures = exposures.with_columns([
                    pl.lit(default_maturity).alias("maturity"),
                ])

        # Turnover for SME correlation adjustment
        # Derive turnover_m (in millions) from cp_annual_revenue if available
        if "turnover_m" not in schema.names():
            if "cp_annual_revenue" in schema.names():
                # Convert annual_revenue to turnover in millions
                exposures = exposures.with_columns([
                    (pl.col("cp_annual_revenue") / 1_000_000.0).alias("turnover_m"),
                ])
            else:
                exposures = exposures.with_columns([
                    pl.lit(None).cast(pl.Float64).alias("turnover_m"),
                ])

        # Exposure class
        if "exposure_class" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit("CORPORATE").alias("exposure_class"),
            ])

        return exposures

    def _apply_supporting_factors(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply SME and infrastructure supporting factors (CRR Art. 501).

        Supporting factors reduce RWA for qualifying exposures:
        - SME factor: 0.7619 (tiered approach for large exposures)
        - Infrastructure factor: 0.75

        Under Basel 3.1, supporting factors are not available.
        """
        if not config.supporting_factors.enabled:
            # Basel 3.1 or supporting factors disabled - no adjustment
            return exposures.with_columns([
                pl.lit(1.0).alias("supporting_factor"),
            ])

        schema = exposures.collect_schema()

        # Prepare RWA column for factor application
        # The rwa column from formulas is pre-factor
        exposures = exposures.with_columns([
            pl.col("rwa").alias("rwa_pre_factor"),
        ])

        # Use the SA supporting factor calculator
        sf_calc = SupportingFactorCalculator()
        exposures = sf_calc.apply_factors(exposures, config)

        # Rename rwa_post_factor back to rwa for consistency
        if "rwa_post_factor" in exposures.collect_schema().names():
            exposures = exposures.with_columns([
                pl.col("rwa_post_factor").alias("rwa"),
            ])

        return exposures

    def _calculate_expected_loss(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Calculate expected loss for provision comparison."""
        return exposures.select([
            pl.col("exposure_reference"),
            pl.col("pd_floored").alias("pd"),
            pl.col("lgd_floored").alias("lgd"),
            pl.col("ead_final").alias("ead"),
            pl.col("expected_loss"),
        ])

    def _build_audit(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Build IRB calculation audit trail."""
        schema = exposures.collect_schema()
        available_cols = schema.names()

        # Select available audit columns
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

        audit = exposures.select(select_cols)

        # Add calculation string
        audit = audit.with_columns([
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

        return audit

    def calculate_single_exposure(
        self,
        ead: Decimal,
        pd: Decimal,
        lgd: Decimal | None = None,
        maturity: Decimal = Decimal("2.5"),
        exposure_class: str = "CORPORATE",
        turnover_m: Decimal | None = None,
        collateral_type: str | None = None,
        is_subordinated: bool = False,
        config: CalculationConfig | None = None,
    ) -> dict:
        """
        Calculate RWA for a single exposure (convenience method).

        Args:
            ead: Exposure at default
            pd: Probability of default
            lgd: Loss given default (None for F-IRB supervisory)
            maturity: Effective maturity in years
            exposure_class: Exposure class
            turnover_m: Annual turnover in millions (for SME adjustment)
            collateral_type: Collateral type for F-IRB LGD
            is_subordinated: Whether subordinated (for F-IRB LGD)
            config: Calculation configuration (defaults to CRR)

        Returns:
            Dictionary with calculation results
        """
        from datetime import date
        from rwa_calc.contracts.config import CalculationConfig

        if config is None:
            config = CalculationConfig.crr(reporting_date=date.today())

        # Determine LGD
        if lgd is None:
            # F-IRB supervisory LGD
            lgd = lookup_firb_lgd(collateral_type, is_subordinated)

        # Calculate correlation
        turnover_float = float(turnover_m) if turnover_m else None
        correlation = calculate_correlation(
            pd=float(pd),
            exposure_class=exposure_class,
            turnover_m=turnover_float,
        )

        # Check if retail (no MA, no scaling)
        is_retail = "RETAIL" in exposure_class.upper()

        # Get configuration parameters
        pd_floor = float(config.pd_floors.corporate)
        lgd_floor = float(config.lgd_floors.unsecured) if config.is_basel_3_1 else None
        apply_scaling = config.is_crr and not is_retail
        apply_ma = not is_retail

        # Calculate IRB RWA
        result = calculate_irb_rwa(
            ead=float(ead),
            pd=float(pd),
            lgd=float(lgd),
            correlation=correlation,
            maturity=float(maturity),
            apply_maturity_adjustment=apply_ma,
            apply_scaling_factor=apply_scaling,
            pd_floor=pd_floor,
            lgd_floor=lgd_floor,
        )

        # Add expected loss
        result["expected_loss"] = calculate_expected_loss(
            result["pd_floored"],
            result["lgd_floored"],
            float(ead),
        )

        return result


def create_irb_calculator() -> IRBCalculator:
    """
    Create an IRB calculator instance.

    Returns:
        IRBCalculator ready for use
    """
    return IRBCalculator()
