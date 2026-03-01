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

from dataclasses import dataclass
from decimal import Decimal
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
from rwa_calc.data.tables.crr_slotting import (
    lookup_slotting_rw,
)
from rwa_calc.domain.enums import ApproachType

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


@dataclass
class SlottingCalculationError:
    """Error during slotting calculation."""

    error_type: str
    message: str
    exposure_reference: str | None = None


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
        self._slotting_table: pl.DataFrame | None = None

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
        errors: list[SlottingCalculationError] = []

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

        # Apply calculation pipeline using registered namespace
        exposures = (
            exposures.slotting.prepare_columns()
            .slotting.apply_slotting_weights(config)
            .slotting.calculate_rwa()
        )

        # Build audit trail
        audit = exposures.slotting.build_audit()

        return SlottingResultBundle(
            results=exposures,
            calculation_audit=audit,
            errors=[],
        )

    def calculate_single_exposure(
        self,
        ead: Decimal,
        category: str,
        is_hvcre: bool = False,
        sl_type: str = "project_finance",
        is_short_maturity: bool = False,
        is_pre_operational: bool = False,
        config: CalculationConfig | None = None,
    ) -> dict:
        """
        Calculate RWA for a single slotting exposure (convenience method).

        Args:
            ead: Exposure at default
            category: Slotting category (strong, good, satisfactory, weak, default)
            is_hvcre: Whether this is high-volatility commercial real estate
            sl_type: Specialised lending type
            is_short_maturity: Whether remaining maturity < 2.5 years (CRR)
            is_pre_operational: Whether PF is pre-operational (Basel 3.1)
            config: Calculation configuration (defaults to CRR)

        Returns:
            Dictionary with calculation results
        """
        from datetime import date

        import rwa_calc.engine.slotting.namespace  # noqa: F401
        from rwa_calc.contracts.config import CalculationConfig

        if config is None:
            config = CalculationConfig.crr(reporting_date=date.today())

        # Look up risk weight
        if config.is_crr:
            risk_weight = lookup_slotting_rw(category, is_hvcre, is_short_maturity)
        else:
            risk_weight = self._get_basel31_slotting_rw(category, is_hvcre, is_pre_operational)
        # Use expression namespace for lookup logic
        df = pl.DataFrame(
            {
                "slotting_category": [category],
                "is_hvcre": [is_hvcre],
                "is_short_maturity": [is_short_maturity],
                "is_pre_operational": [is_pre_operational],
            }
        )

        rw_expr = col("slotting_category").slotting.lookup_rw(
            is_crr=config.is_crr,
            is_hvcre=col("is_hvcre"),
            is_short=col("is_short_maturity"),
            is_preop=col("is_pre_operational"),
        )

        risk_weight = Decimal(str(df.select(rw_expr).item()))

        # Calculate RWA
        rwa = ead * risk_weight

        return {
            "ead": float(ead),
            "category": category,
            "is_hvcre": is_hvcre,
            "sl_type": sl_type,
            "risk_weight": float(risk_weight),
            "rwa": float(rwa),
            "framework": "CRR" if config.is_crr else "Basel 3.1",
        }

    def _get_basel31_slotting_rw(
        self,
        category: str,
        is_hvcre: bool,
        is_pre_operational: bool = False,
    ) -> Decimal:
        """Get Basel 3.1 slotting risk weight (BCBS CRE33)."""
        import rwa_calc.engine.slotting.namespace  # noqa: F401

        # Use expression namespace for lookup logic
        df = pl.DataFrame(
            {
                "slotting_category": [category],
                "is_hvcre": [is_hvcre],
                "is_pre_operational": [is_pre_operational],
            }
        )

        rw_expr = col("slotting_category").slotting.lookup_rw(
            is_crr=False,
            is_hvcre=col("is_hvcre"),
            is_preop=col("is_pre_operational"),
        )

        return Decimal(str(df.select(rw_expr).item()))


def create_slotting_calculator() -> SlottingCalculator:
    """
    Create a slotting calculator instance.

    Returns:
        SlottingCalculator ready for use
    """
    return SlottingCalculator()
