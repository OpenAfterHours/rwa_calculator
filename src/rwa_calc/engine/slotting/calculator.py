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

from rwa_calc.contracts.bundles import CRMAdjustedBundle, SlottingResultBundle
from rwa_calc.contracts.errors import (
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    LazyFrameResult,
)
from rwa_calc.data.tables.crr_slotting import (
    get_slotting_table,
    lookup_slotting_rw,
    SLOTTING_RISK_WEIGHTS,
    SLOTTING_RISK_WEIGHTS_HVCRE,
)
from rwa_calc.domain.enums import ApproachType, SlottingCategory

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
            empty_frame = pl.LazyFrame({
                "exposure_reference": pl.Series([], dtype=pl.String),
                "slotting_category": pl.Series([], dtype=pl.String),
                "is_hvcre": pl.Series([], dtype=pl.Boolean),
                "ead_final": pl.Series([], dtype=pl.Float64),
                "risk_weight": pl.Series([], dtype=pl.Float64),
                "rwa": pl.Series([], dtype=pl.Float64),
            })
            return SlottingResultBundle(
                results=empty_frame,
                calculation_audit=empty_frame,
                errors=[],
            )

        # Step 1: Ensure required columns exist
        exposures = self._prepare_columns(exposures, config)

        # Step 2: Look up risk weights based on slotting category
        exposures = self._apply_slotting_weights(exposures, config)

        # Step 3: Calculate RWA
        exposures = self._calculate_rwa(exposures)

        # Step 4: Build audit trail
        audit = self._build_audit(exposures)

        return SlottingResultBundle(
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
        Apply slotting weights to slotting rows on a unified frame.

        Uses filter-process-merge to isolate slotting processing from
        other approaches' columns.

        Args:
            exposures: Unified frame with all approaches
            config: Calculation configuration

        Returns:
            Unified frame with slotting columns populated for slotting rows
        """
        is_slotting = pl.col("approach") == ApproachType.SLOTTING.value

        # Split: separate slotting rows from non-slotting
        non_slotting = exposures.filter(~is_slotting)
        slotting = exposures.filter(is_slotting)

        # Process: run slotting chain on slotting rows only
        slotting = self._prepare_columns(slotting, config)
        slotting = self._apply_slotting_weights(slotting, config)
        slotting = self._calculate_rwa(slotting)

        # Merge: concat slotting results back with non-slotting rows
        return pl.concat([non_slotting, slotting], how="diagonal_relaxed")

    def calculate_branch(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Calculate Slotting RWA on pre-filtered slotting-only rows.

        Unlike calculate_unified(), expects only slotting rows — no
        filter/concat wrapper needed.

        Args:
            exposures: Pre-filtered slotting rows only
            config: Calculation configuration

        Returns:
            LazyFrame with slotting RWA columns populated
        """
        exposures = self._prepare_columns(exposures, config)
        exposures = self._apply_slotting_weights(exposures, config)
        exposures = self._calculate_rwa(exposures)
        return exposures

    def _prepare_columns(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Ensure all required columns exist with defaults."""
        schema = exposures.collect_schema()

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

        # Slotting category
        if "slotting_category" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit("satisfactory").alias("slotting_category"),
            ])

        # HVCRE flag
        if "is_hvcre" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit(False).alias("is_hvcre"),
            ])

        # Specialised lending type
        if "sl_type" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit("project_finance").alias("sl_type"),
            ])

        # CRR maturity flag (default >= 2.5yr = more conservative)
        if "is_short_maturity" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit(False).alias("is_short_maturity"),
            ])

        # Basel 3.1 pre-operational flag (default operational)
        if "is_pre_operational" not in schema.names():
            exposures = exposures.with_columns([
                pl.lit(False).alias("is_pre_operational"),
            ])

        return exposures

    def _apply_slotting_weights(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply slotting risk weights based on category, HVCRE flag, and maturity.

        CRR: Maturity-based split with separate HVCRE table (Art. 153(5)).
        Basel 3.1: HVCRE and PF pre-operational differentiated (BCBS CRE33).
        """
        if config.is_crr:
            return self._apply_crr_weights(exposures)
        else:
            return self._apply_basel31_weights(exposures)

    def _apply_crr_weights(self, exposures: pl.LazyFrame) -> pl.LazyFrame:
        """Apply CRR slotting weights with maturity and HVCRE differentiation."""
        from rwa_calc.engine.slotting.namespace import (
            CRR_SLOTTING_WEIGHTS,
            CRR_SLOTTING_WEIGHTS_SHORT,
            CRR_SLOTTING_WEIGHTS_HVCRE,
            CRR_SLOTTING_WEIGHTS_HVCRE_SHORT,
        )

        cat = pl.col("slotting_category").str.to_lowercase()
        is_hvcre = pl.col("is_hvcre")
        is_short = pl.col("is_short_maturity")

        return exposures.with_columns([
            # Non-HVCRE, >= 2.5yr
            pl.when(~is_hvcre & ~is_short & (cat == "strong"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS["strong"]))
            .when(~is_hvcre & ~is_short & (cat == "good"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS["good"]))
            .when(~is_hvcre & ~is_short & (cat == "satisfactory"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS["satisfactory"]))
            .when(~is_hvcre & ~is_short & (cat == "weak"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS["weak"]))
            .when(~is_hvcre & ~is_short & (cat == "default"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS["default"]))

            # Non-HVCRE, < 2.5yr
            .when(~is_hvcre & is_short & (cat == "strong"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS_SHORT["strong"]))
            .when(~is_hvcre & is_short & (cat == "good"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS_SHORT["good"]))
            .when(~is_hvcre & is_short & (cat == "satisfactory"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS_SHORT["satisfactory"]))
            .when(~is_hvcre & is_short & (cat == "weak"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS_SHORT["weak"]))
            .when(~is_hvcre & is_short & (cat == "default"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS_SHORT["default"]))

            # HVCRE, >= 2.5yr
            .when(is_hvcre & ~is_short & (cat == "strong"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS_HVCRE["strong"]))
            .when(is_hvcre & ~is_short & (cat == "good"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS_HVCRE["good"]))
            .when(is_hvcre & ~is_short & (cat == "satisfactory"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS_HVCRE["satisfactory"]))
            .when(is_hvcre & ~is_short & (cat == "weak"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS_HVCRE["weak"]))
            .when(is_hvcre & ~is_short & (cat == "default"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS_HVCRE["default"]))

            # HVCRE, < 2.5yr
            .when(is_hvcre & is_short & (cat == "strong"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS_HVCRE_SHORT["strong"]))
            .when(is_hvcre & is_short & (cat == "good"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS_HVCRE_SHORT["good"]))
            .when(is_hvcre & is_short & (cat == "satisfactory"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS_HVCRE_SHORT["satisfactory"]))
            .when(is_hvcre & is_short & (cat == "weak"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS_HVCRE_SHORT["weak"]))
            .when(is_hvcre & is_short & (cat == "default"))
            .then(pl.lit(CRR_SLOTTING_WEIGHTS_HVCRE_SHORT["default"]))

            .otherwise(pl.lit(CRR_SLOTTING_WEIGHTS["satisfactory"]))
            .alias("risk_weight"),
        ])

    def _apply_basel31_weights(self, exposures: pl.LazyFrame) -> pl.LazyFrame:
        """Apply Basel 3.1 slotting weights (BCBS CRE33)."""
        from rwa_calc.engine.slotting.namespace import (
            BASEL31_SLOTTING_WEIGHTS,
            BASEL31_SLOTTING_WEIGHTS_PF_PREOP,
            BASEL31_SLOTTING_WEIGHTS_HVCRE,
        )

        cat = pl.col("slotting_category").str.to_lowercase()
        is_hvcre = pl.col("is_hvcre")
        is_preop = pl.col("is_pre_operational")

        return exposures.with_columns([
            # HVCRE weights
            pl.when(is_hvcre & (cat == "strong"))
            .then(pl.lit(BASEL31_SLOTTING_WEIGHTS_HVCRE["strong"]))
            .when(is_hvcre & (cat == "good"))
            .then(pl.lit(BASEL31_SLOTTING_WEIGHTS_HVCRE["good"]))
            .when(is_hvcre & (cat == "satisfactory"))
            .then(pl.lit(BASEL31_SLOTTING_WEIGHTS_HVCRE["satisfactory"]))
            .when(is_hvcre & (cat == "weak"))
            .then(pl.lit(BASEL31_SLOTTING_WEIGHTS_HVCRE["weak"]))
            .when(is_hvcre & (cat == "default"))
            .then(pl.lit(BASEL31_SLOTTING_WEIGHTS_HVCRE["default"]))

            # PF pre-operational weights
            .when(~is_hvcre & is_preop & (cat == "strong"))
            .then(pl.lit(BASEL31_SLOTTING_WEIGHTS_PF_PREOP["strong"]))
            .when(~is_hvcre & is_preop & (cat == "good"))
            .then(pl.lit(BASEL31_SLOTTING_WEIGHTS_PF_PREOP["good"]))
            .when(~is_hvcre & is_preop & (cat == "satisfactory"))
            .then(pl.lit(BASEL31_SLOTTING_WEIGHTS_PF_PREOP["satisfactory"]))
            .when(~is_hvcre & is_preop & (cat == "weak"))
            .then(pl.lit(BASEL31_SLOTTING_WEIGHTS_PF_PREOP["weak"]))
            .when(~is_hvcre & is_preop & (cat == "default"))
            .then(pl.lit(BASEL31_SLOTTING_WEIGHTS_PF_PREOP["default"]))

            # Non-HVCRE operational weights (default)
            .when(~is_hvcre & ~is_preop & (cat == "strong"))
            .then(pl.lit(BASEL31_SLOTTING_WEIGHTS["strong"]))
            .when(~is_hvcre & ~is_preop & (cat == "good"))
            .then(pl.lit(BASEL31_SLOTTING_WEIGHTS["good"]))
            .when(~is_hvcre & ~is_preop & (cat == "satisfactory"))
            .then(pl.lit(BASEL31_SLOTTING_WEIGHTS["satisfactory"]))
            .when(~is_hvcre & ~is_preop & (cat == "weak"))
            .then(pl.lit(BASEL31_SLOTTING_WEIGHTS["weak"]))
            .when(~is_hvcre & ~is_preop & (cat == "default"))
            .then(pl.lit(BASEL31_SLOTTING_WEIGHTS["default"]))

            .otherwise(pl.lit(BASEL31_SLOTTING_WEIGHTS["satisfactory"]))
            .alias("risk_weight"),
        ])

    def _calculate_rwa(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Calculate RWA = EAD x RW."""
        return exposures.with_columns([
            (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa"),
            (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa_final"),
        ])

    def _build_audit(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Build slotting calculation audit trail."""
        schema = exposures.collect_schema()
        available_cols = schema.names()

        # Select available audit columns
        select_cols = ["exposure_reference"]
        optional_cols = [
            "counterparty_reference",
            "exposure_class",
            "sl_type",
            "slotting_category",
            "is_hvcre",
            "ead_final",
            "risk_weight",
            "rwa",
        ]

        for col in optional_cols:
            if col in available_cols:
                select_cols.append(col)

        audit = exposures.select(select_cols)

        # Add calculation string
        audit = audit.with_columns([
            pl.concat_str([
                pl.lit("Slotting: Category="),
                pl.col("slotting_category"),
                pl.when(pl.col("is_hvcre"))
                .then(pl.lit(" (HVCRE)"))
                .otherwise(pl.lit("")),
                pl.lit(", RW="),
                (pl.col("risk_weight") * 100).round(0).cast(pl.String),
                pl.lit("%, RWA="),
                pl.col("rwa").round(0).cast(pl.String),
            ]).alias("slotting_calculation"),
        ])

        return audit

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
        from rwa_calc.contracts.config import CalculationConfig

        if config is None:
            config = CalculationConfig.crr(reporting_date=date.today())

        # Look up risk weight
        if config.is_crr:
            risk_weight = lookup_slotting_rw(category, is_hvcre, is_short_maturity)
        else:
            risk_weight = self._get_basel31_slotting_rw(
                category, is_hvcre, is_pre_operational
            )

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
        cat_lower = category.lower()

        if is_hvcre:
            weights = {
                "strong": Decimal("0.95"),
                "good": Decimal("1.20"),
                "satisfactory": Decimal("1.40"),
                "weak": Decimal("2.50"),
                "default": Decimal("0.00"),
            }
        elif is_pre_operational:
            weights = {
                "strong": Decimal("0.80"),
                "good": Decimal("1.00"),
                "satisfactory": Decimal("1.20"),
                "weak": Decimal("3.50"),
                "default": Decimal("0.00"),
            }
        else:
            weights = {
                "strong": Decimal("0.70"),
                "good": Decimal("0.90"),
                "satisfactory": Decimal("1.15"),
                "weak": Decimal("2.50"),
                "default": Decimal("0.00"),
            }

        return weights.get(cat_lower, Decimal("1.15"))


def create_slotting_calculator() -> SlottingCalculator:
    """
    Create a slotting calculator instance.

    Returns:
        SlottingCalculator ready for use
    """
    return SlottingCalculator()
