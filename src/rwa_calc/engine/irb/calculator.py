"""
IRB (Internal Ratings-Based) Calculator for RWA.

Implements CRR Art. 153-154 for F-IRB and A-IRB approaches.
Supports both CRR and Basel 3.1 frameworks with appropriate floors.

Pipeline position:
    CRMProcessor -> IRBCalculator -> Aggregation

Key responsibilities:
- Apply PD floors (differentiated for Basel 3.1)
- Determine LGD (supervisory for F-IRB, own estimates for A-IRB)
- Calculate asset correlation (with SME adjustment)
- Calculate capital requirement (K)
- Apply maturity adjustment
- Apply 1.06 scaling factor (CRR only)
- Calculate RWA = K × 12.5 × [1.06] × EAD × MA
- Apply post-model adjustments (Basel 3.1: mortgage RW floor, PMAs)
- Calculate expected loss for provision comparison

References:
- CRR Art. 153-154: IRB risk weight functions
- CRR Art. 161: F-IRB supervisory LGD
- CRR Art. 162: Maturity
- CRR Art. 163: PD floors
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

# Import namespace to ensure it's registered
import rwa_calc.engine.irb.namespace  # noqa: F401
from rwa_calc.contracts.bundles import CRMAdjustedBundle, IRBResultBundle
from rwa_calc.contracts.errors import (
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    LazyFrameResult,
)
from rwa_calc.engine.sa.supporting_factors import SupportingFactorCalculator

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


class IRBCalculator:
    """
    Calculate RWA using IRB approach.

    Implements IRBCalculatorProtocol for:
    - F-IRB: Supervisory LGD, bank's PD
    - A-IRB: Bank's own LGD and PD estimates

    Supports both CRR and Basel 3.1 frameworks:
    - CRR: Single PD floor (0.03%), no LGD floors, 1.06 scaling
    - Basel 3.1: Differentiated PD floors, LGD floors for A-IRB, no scaling

    All methods delegate to the IRB namespace for formula calculations,
    then apply supporting factors and wrap results.

    Usage:
        calculator = IRBCalculator()
        result = calculator.calculate(crm_bundle, config)
    """

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

        # Convert bundle errors to CalculationErrors, preserving any
        # CalculationError objects already created by sub-components
        calc_errors: list[CalculationError] = []
        for err in bundle.errors:
            if isinstance(err, CalculationError):
                calc_errors.append(err)
            else:
                calc_errors.append(
                    CalculationError(
                        code="IRB001",
                        message=str(err),
                        severity=ErrorSeverity.ERROR,
                        category=ErrorCategory.CALCULATION,
                    )
                )

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
        Calculate IRB RWA and return as a bundle with audit trail.

        Args:
            data: CRM-adjusted exposures
            config: Calculation configuration

        Returns:
            IRBResultBundle with results, expected loss, and audit trail
        """
        sf_errors: list[CalculationError] = []
        exposures = self._run_irb_chain(data.irb_exposures, config, sf_errors=sf_errors)

        return IRBResultBundle(
            results=exposures,
            expected_loss=exposures.irb.select_expected_loss(),
            calculation_audit=exposures.irb.build_audit(),
            errors=sf_errors,
        )

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Calculate IRB RWA on pre-filtered IRB-only rows.

        Args:
            exposures: Pre-filtered IRB rows only
            config: Calculation configuration

        Returns:
            LazyFrame with IRB RWA columns populated
        """
        return self._run_irb_chain(exposures, config)

    def calculate_expected_loss(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate expected loss for IRB exposures.

        EL = PD × LGD × EAD

        Emits IRB004/IRB005 warnings when PD/LGD columns are absent and
        supervisory defaults (PD=1%, LGD=45%) are substituted.

        Args:
            data: CRM-adjusted exposures
            config: Calculation configuration

        Returns:
            LazyFrameResult with expected loss calculations
        """
        exposures = data.irb_exposures
        errors: list[CalculationError] = []

        # Ensure required columns — emit warnings when absent
        schema = exposures.collect_schema()
        if "pd" not in schema.names():
            exposures = exposures.with_columns(pl.lit(0.01).alias("pd"))
            errors.append(
                CalculationError(
                    code="IRB004",
                    message=(
                        "PD column absent from IRB exposures; defaulting to 1%. "
                        "Expected loss figures may be unreliable. "
                        "Ensure PD is computed upstream (IRB namespace prepare_columns)."
                    ),
                    severity=ErrorSeverity.WARNING,
                    category=ErrorCategory.DATA_QUALITY,
                    regulatory_reference="CRR Art. 160 / PRA Art. 160",
                    field_name="pd",
                    expected_value="PD from internal model or supervisory floor",
                    actual_value="default 0.01",
                )
            )
        if "lgd" not in schema.names():
            exposures = exposures.with_columns(pl.lit(0.45).alias("lgd"))
            errors.append(
                CalculationError(
                    code="IRB005",
                    message=(
                        "LGD column absent from IRB exposures; defaulting to 45%. "
                        "Expected loss figures may be unreliable. "
                        "Ensure LGD is computed upstream (F-IRB supervisory or A-IRB own estimate)."
                    ),
                    severity=ErrorSeverity.WARNING,
                    category=ErrorCategory.DATA_QUALITY,
                    regulatory_reference="CRR Art. 161 / PRA Art. 161",
                    field_name="lgd",
                    expected_value="LGD from supervisory table or own estimate",
                    actual_value="default 0.45",
                )
            )

        ead_col = "ead_final" if "ead_final" in schema.names() else "ead"

        exposures = exposures.with_columns(
            (pl.col("pd") * pl.col("lgd") * pl.col(ead_col)).alias("expected_loss"),
        )

        return LazyFrameResult(
            frame=exposures.select("exposure_reference", "pd", "lgd", ead_col, "expected_loss"),
            errors=errors,
        )

    def _run_irb_chain(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        sf_errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """Run the full IRB namespace chain plus supporting factors."""
        exposures = (
            exposures.irb.classify_approach(config)
            .irb.apply_firb_lgd(config)
            .irb.prepare_columns(config)
            .irb.apply_all_formulas(config)
            .irb.apply_post_model_adjustments(config)
            .irb.compute_el_shortfall_excess(errors=sf_errors)
            .irb.apply_guarantee_substitution(config)
        )
        exposures = self._apply_supporting_factors(exposures, config, errors=sf_errors)

        # Standardize output for aggregator
        return exposures.with_columns(
            pl.col("approach").alias("approach_applied"),
            pl.col("rwa").alias("rwa_final"),
        )

    def _apply_supporting_factors(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
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
            return exposures.with_columns(
                [
                    pl.lit(1.0).alias("supporting_factor"),
                ]
            )

        # Prepare RWA column for factor application
        # The rwa column from formulas is pre-factor
        exposures = exposures.with_columns(
            [
                pl.col("rwa").alias("rwa_pre_factor"),
            ]
        )

        # Use the SA supporting factor calculator
        sf_calc = SupportingFactorCalculator()
        exposures = sf_calc.apply_factors(exposures, config, errors=errors)

        # Rename rwa_post_factor back to rwa for consistency
        if "rwa_post_factor" in exposures.collect_schema().names():
            exposures = exposures.with_columns(
                [
                    pl.col("rwa_post_factor").alias("rwa"),
                ]
            )

        return exposures


def create_irb_calculator() -> IRBCalculator:
    """
    Create an IRB calculator instance.

    Returns:
        IRBCalculator ready for use
    """
    return IRBCalculator()
