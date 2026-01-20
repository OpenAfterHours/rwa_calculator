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
from rwa_calc.data.tables.crr_firb_lgd import lookup_firb_lgd
from rwa_calc.engine.irb.formulas import (
    calculate_correlation,
    calculate_irb_rwa,
    calculate_k,
    calculate_maturity_adjustment,
    calculate_expected_loss,
)
from rwa_calc.engine.sa.supporting_factors import SupportingFactorCalculator

# Import namespace to ensure it's registered
import rwa_calc.engine.irb.namespace  # noqa: F401

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

        Uses the IRB namespace for fluent calculations:
        1. classify_approach - Determine F-IRB vs A-IRB
        2. apply_firb_lgd - Apply supervisory LGD for F-IRB
        3. prepare_columns - Ensure required columns exist
        4. apply_all_formulas - Apply IRB formulas (PD floor, correlation, K, MA, RWA)

        Args:
            data: CRM-adjusted exposures
            config: Calculation configuration

        Returns:
            IRBResultBundle with results and audit trail
        """
        errors: list[IRBCalculationError] = []

        # Apply IRB calculations using namespace for fluent pipeline
        exposures = (data.irb_exposures
            .irb.classify_approach(config)
            .irb.apply_firb_lgd(config)
            .irb.prepare_columns(config)
            .irb.apply_all_formulas(config)
        )

        # Apply supporting factors (CRR only - Art. 501)
        exposures = self._apply_supporting_factors(exposures, config)

        return IRBResultBundle(
            results=exposures,
            expected_loss=exposures.irb.select_expected_loss(),
            calculation_audit=exposures.irb.build_audit(),
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
