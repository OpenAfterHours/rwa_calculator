"""
Slotting Calculator for Specialised Lending RWA.

Implements CRR Art. 153(5) for supervisory slotting approach.
Supports both CRR and Basel 3.1 frameworks with appropriate risk weights.

Pipeline position:
    CRMProcessor -> SlottingCalculator -> OutputAggregator

Key responsibilities:
- Map slotting categories to risk weights
- Handle HVCRE (High Volatility Commercial Real Estate) distinction
- Handle maturity-based splits (CRR: <2.5yr / >=2.5yr)
- Handle PF pre-operational vs operational distinction (Basel 3.1)
- Calculate RWA = EAD x RW
- Build audit trail of calculations

Specialised Lending Types:
- Project Finance (PF)
- Object Finance (OF)
- Commodities Finance (CF)
- Income-Producing Real Estate (IPRE)
- High Volatility Commercial Real Estate (HVCRE)

References:
- CRR Art. 153(5): Supervisory slotting approach (Tables 1 & 2)
- CRR Art. 147(8): Specialised lending definition
- BCBS CRE33: Basel 3.1 specialised lending slotting
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from polars import col

from rwa_calc.contracts.bundles import CRMAdjustedBundle, SlottingResultBundle
from rwa_calc.contracts.errors import (
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    LazyFrameResult,
)
from rwa_calc.domain.enums import ApproachType

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


class SlottingCalculator:
    """
    Calculate RWA using supervisory slotting approach for specialised lending.

    Implements SlottingCalculatorProtocol for CRR Art. 153(5).

    The slotting approach maps exposures to five categories with framework-specific weights:

    CRR (Art. 153(5)) — weights depend on maturity (>=2.5yr shown):
    - Non-HVCRE: Strong=70%, Good=90%, Satisfactory=115%, Weak=250%, Default=0%
    - HVCRE: Strong=95%, Good=120%, Satisfactory=140%, Weak=250%, Default=0%

    Basel 3.1 (BCBS CRE33):
    - Operational: Strong=70%, Good=90%, Satisfactory=115%, Weak=250%, Default=0%
    - PF Pre-op: Strong=80%, Good=100%, Satisfactory=120%, Weak=350%, Default=0%
    - HVCRE: Strong=95%, Good=120%, Satisfactory=140%, Weak=250%, Default=0%

    Usage:
        calculator = SlottingCalculator()
        result = calculator.calculate(crm_bundle, config)
    """

    def __init__(self) -> None:
        """Initialize slotting calculator."""

    def calculate_unified(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply slotting weights on unified frame (single-pass pipeline).

        Filters slotting rows, applies the namespace chain, then concats
        back with non-slotting rows to preserve the unified frame.

        Args:
            exposures: Unified frame with all approaches
            config: Calculation configuration

        Returns:
            Unified frame with slotting columns populated for slotting rows
        """
        is_slotting = col("approach") == ApproachType.SLOTTING.value

        non_slotting = exposures.filter(~is_slotting)
        slotting = exposures.filter(is_slotting)

        slotting = self.calculate_branch(slotting, config)

        return pl.concat([non_slotting, slotting], how="diagonal_relaxed")

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Calculate Slotting RWA on pre-filtered slotting-only rows.

        Unlike calculate_unified(), expects only slotting rows — no
        approach guards needed.

        Args:
            exposures: Pre-filtered slotting rows only
            config: Calculation configuration

        Returns:
            LazyFrame with slotting RWA columns populated
        """
        return (
            exposures.slotting.prepare_columns(config)
            .slotting.apply_slotting_weights(config)
            .slotting.calculate_rwa()
        )

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate RWA using supervisory slotting approach.

        Args:
            data: CRM-adjusted exposures (uses slotting_exposures)
            config: Calculation configuration

        Returns:
            LazyFrameResult with slotting RWA calculations
        """
        bundle = self.get_slotting_result_bundle(data, config)

        # Convert bundle errors to CalculationErrors
        calc_errors = [
            CalculationError(
                code="SLOTTING001",
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

    def get_slotting_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> SlottingResultBundle:
        """
        Calculate slotting RWA and return as a bundle.

        Args:
            data: CRM-adjusted exposures
            config: Calculation configuration

        Returns:
            SlottingResultBundle with results and audit trail
        """
        # Get slotting exposures (may be None)
        exposures = data.slotting_exposures

        # Handle case where there are no slotting exposures
        if exposures is None:
            empty_frame = pl.LazyFrame(
                {
                    "exposure_reference": pl.Series([], dtype=pl.String),
                    "slotting_category": pl.Series([], dtype=pl.String),
                    "is_hvcre": pl.Series([], dtype=pl.Boolean),
                    "ead_final": pl.Series([], dtype=pl.Float64),
                    "risk_weight": pl.Series([], dtype=pl.Float64),
                    "rwa": pl.Series([], dtype=pl.Float64),
                }
            )
            return SlottingResultBundle(
                results=empty_frame,
                calculation_audit=empty_frame,
                errors=[],
            )

        # Apply calculation pipeline
        exposures = self.calculate_branch(exposures, config)

        # Build audit trail
        audit = exposures.slotting.build_audit()

        return SlottingResultBundle(
            results=exposures,
            calculation_audit=audit,
            errors=[],
        )


def create_slotting_calculator() -> SlottingCalculator:
    """
    Create a slotting calculator instance.

    Returns:
        SlottingCalculator ready for use
    """
    return SlottingCalculator()
