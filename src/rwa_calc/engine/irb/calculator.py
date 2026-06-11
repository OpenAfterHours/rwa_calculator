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

import logging
from typing import TYPE_CHECKING

import polars as pl

# Import namespace to ensure it's registered
import rwa_calc.engine.irb.namespace  # noqa: F401
from rwa_calc.contracts.errors import (
    CalculationError,
)
from rwa_calc.engine.supporting_factors import SupportingFactorCalculator

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)


class IRBCalculator:
    """
    Calculate RWA using IRB approach.

    Implements IRBCalculatorProtocol for:
    - F-IRB: Supervisory LGD, bank's PD
    - A-IRB: Bank's own LGD and PD estimates

    Supports both CRR and Basel 3.1 frameworks:
    - CRR: Single PD floor (0.03%), no LGD floors, 1.06 scaling
    - Basel 3.1: Differentiated PD floors, LGD floors for A-IRB, no scaling

    Delegates to the IRB namespace for formula calculations, then applies
    supporting factors and standardises the output for the aggregator.

    Usage:
        calculator = IRBCalculator()
        result = calculator.calculate_branch(irb_exposures, config)
    """

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """
        Calculate IRB RWA on pre-filtered IRB-only rows.

        Args:
            exposures: Pre-filtered IRB rows only
            config: Calculation configuration
            errors: Optional error accumulator for data quality warnings
                (SF001 SME aggregation, EL shortfall/excess diagnostics)

        Returns:
            LazyFrame with IRB RWA columns populated
        """
        return self._run_irb_chain(exposures, config, sf_errors=errors)

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
            pl.col("maturity").alias("irb_maturity_m"),
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
