"""
Slotting Calculator for Specialised Lending RWA and Expected Loss.

Implements CRR Art. 153(5) for supervisory slotting approach (risk weights)
and CRR Art. 158(6) Table B for expected loss rates.

Pipeline position:
    CRMProcessor -> SlottingCalculator -> Aggregation

Key responsibilities:
- Map slotting categories to risk weights (Art. 153(5))
- Map slotting categories to expected loss rates (Art. 158(6) Table B)
- Handle HVCRE (High Volatility Commercial Real Estate) distinction
- Handle maturity-based splits (CRR: <2.5yr / >=2.5yr)
- Handle PF pre-operational vs operational distinction (Basel 3.1)
- Calculate RWA = EAD x RW
- Apply supporting factors (CRR Art. 501/501a: SME + infrastructure)
- Calculate EL = EL_rate x EAD
- Compute EL shortfall/excess for T2 credit cap and CET1/T2 deductions
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
- CRR Art. 158(6), Table B: Expected loss rates for slotting
- CRR Art. 159: EL shortfall/excess treatment
- CRR Art. 501a: Infrastructure supporting factor (0.75)
- BCBS CRE33: Basel 3.1 specialised lending slotting
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import CRMAdjustedBundle, SlottingResultBundle
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.engine.sa.supporting_factors import SupportingFactorCalculator

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

    Basel 3.1 (PRA PS1/26 Art. 153(5) Table A):
    - All SL (incl. PF pre-op): Strong=70%, Good=90%, Satisfactory=115%, Weak=250%, Default=0%
    - HVCRE: Strong=95%, Good=120%, Satisfactory=140%, Weak=250%, Default=0%
    Note: PRA did not adopt the BCBS CRE33 separate pre-operational PF table.

    Usage:
        calculator = SlottingCalculator()
        result = calculator.calculate_branch(exposures, config)
    """

    def __init__(self) -> None:
        """Initialize slotting calculator."""

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """
        Calculate Slotting RWA and Expected Loss on pre-filtered slotting-only rows.

        Computes risk weights (Art. 153(5)), RWA, supporting factors (Art. 501/501a),
        expected loss rates (Art. 158(6) Table B), and EL shortfall/excess for the
        portfolio EL summary.

        Args:
            exposures: Pre-filtered slotting rows only
            config: Calculation configuration
            errors: Optional error accumulator for data quality warnings

        Returns:
            LazyFrame with slotting RWA, expected_loss, el_shortfall, el_excess
        """
        exposures = (
            exposures.slotting.prepare_columns(config)
            .slotting.apply_slotting_weights(config)
            .slotting.calculate_rwa()
        )

        # Apply supporting factors (CRR Art. 501/501a) — same pattern as IRB
        exposures = self._apply_supporting_factors(exposures, config, errors=errors)

        exposures = exposures.slotting.apply_el_rates(config).slotting.compute_el_shortfall_excess(
            errors=errors
        )

        # Standardize output for aggregator
        schema = exposures.collect_schema()
        rwa_col = "rwa_final" if "rwa_final" in schema.names() else "rwa"
        approach_expr = pl.col("approach") if "approach" in schema.names() else pl.lit("slotting")
        return exposures.with_columns(
            approach_expr.alias("approach_applied"),
            pl.col(rwa_col).alias("rwa_final"),
        )

    def _apply_supporting_factors(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """
        Apply SME and infrastructure supporting factors (CRR Art. 501/501a).

        Infrastructure project finance in slotting can qualify for the 0.75
        infrastructure supporting factor. Under Basel 3.1, supporting factors
        are disabled.

        Args:
            exposures: Exposures with rwa computed
            config: Calculation configuration
            errors: Optional error accumulator for data quality warnings

        Returns:
            Exposures with supporting factors applied
        """
        if not config.supporting_factors.enabled:
            return exposures.with_columns(pl.lit(1.0).alias("supporting_factor"))

        # Rename rwa to rwa_pre_factor for the SupportingFactorCalculator
        exposures = exposures.with_columns(pl.col("rwa").alias("rwa_pre_factor"))

        # Ensure supporting-factor flags exist (classifier may not have set them).
        exposures = ensure_columns(
            exposures,
            {
                "is_sme": ColumnSpec(pl.Boolean, default=False, required=False),
                "is_infrastructure": ColumnSpec(pl.Boolean, default=False, required=False),
            },
        )

        sf_calc = SupportingFactorCalculator()
        exposures = sf_calc.apply_factors(exposures, config, errors=errors)

        # Update rwa and rwa_final with post-factor values
        if "rwa_post_factor" in exposures.collect_schema().names():
            exposures = exposures.with_columns(
                pl.col("rwa_post_factor").alias("rwa"),
                pl.col("rwa_post_factor").alias("rwa_final"),
            )

        return exposures

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

        # Apply calculation pipeline (with error collection)
        sf_errors: list[CalculationError] = []
        exposures = (
            exposures.slotting.prepare_columns(config)
            .slotting.apply_slotting_weights(config)
            .slotting.calculate_rwa()
        )
        exposures = self._apply_supporting_factors(exposures, config, errors=sf_errors)
        exposures = exposures.slotting.apply_el_rates(config).slotting.compute_el_shortfall_excess(
            errors=sf_errors
        )

        # Build audit trail
        audit = exposures.slotting.build_audit()

        return SlottingResultBundle(
            results=exposures,
            calculation_audit=audit,
            errors=sf_errors,
        )


def create_slotting_calculator() -> SlottingCalculator:
    """
    Create a slotting calculator instance.

    Returns:
        SlottingCalculator ready for use
    """
    return SlottingCalculator()
