"""
Equity Calculator for Equity Exposure RWA.

Implements two approaches under CRR:
- Article 133: Standardised Approach (SA) - Default for SA firms
- Article 155: IRB Simple Risk Weight Method - For firms with IRB permission

Pipeline position:
    CRMProcessor -> EquityCalculator -> OutputAggregator

Key responsibilities:
- Determine equity risk weights based on equity type
- Handle diversified portfolio treatment for private equity
- Calculate RWA = EAD x RW
- Build audit trail of calculations

Risk Weight Summary:

Article 133 (SA):
- Central bank: 0%
- Listed/Exchange-traded/Government-supported: 100%
- Unlisted: 250%
- Speculative: 400%

Article 155 (IRB Simple):
- Private equity (diversified portfolio): 190%
- Exchange-traded: 290%
- Other equity: 370%

References:
- CRR Art. 133: Equity exposures under SA
- CRR Art. 155: Simple risk weight approach under IRB
- EBA Q&A 2023_6716: Strategic equity treatment
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import CRMAdjustedBundle, EquityResultBundle
from rwa_calc.contracts.errors import (
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    LazyFrameResult,
)
from rwa_calc.data.tables.crr_equity_rw import lookup_equity_rw
from rwa_calc.domain.enums import ApproachType

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


@dataclass
class EquityCalculationError:
    """Error during equity calculation."""

    error_type: str
    message: str
    exposure_reference: str | None = None


class EquityCalculator:
    """
    Calculate RWA for equity exposures.

    Supports two approaches under CRR:
    - Article 133: Standardised Approach (100%/250%/400% RW)
    - Article 155: IRB Simple Risk Weight (190%/290%/370% RW)

    The approach is determined by config.irb_approach_option:
    - SA_ONLY: Uses Article 133
    - FIRB/AIRB/FULL_IRB: Uses Article 155

    Usage:
        calculator = EquityCalculator()
        result = calculator.calculate(crm_bundle, config)
    """

    def __init__(self) -> None:
        """Initialize equity calculator."""
        pass

    def calculate(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Calculate RWA for equity exposures.

        Args:
            data: CRM-adjusted exposures (uses equity_exposures)
            config: Calculation configuration

        Returns:
            LazyFrameResult with equity RWA calculations
        """
        bundle = self.get_equity_result_bundle(data, config)

        calc_errors = [
            CalculationError(
                code="EQUITY001",
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

    def get_equity_result_bundle(
        self,
        data: CRMAdjustedBundle,
        config: CalculationConfig,
    ) -> EquityResultBundle:
        """
        Calculate equity RWA and return as a bundle.

        Args:
            data: CRM-adjusted exposures
            config: Calculation configuration

        Returns:
            EquityResultBundle with results and audit trail
        """
        errors: list[EquityCalculationError] = []

        exposures = data.equity_exposures

        if exposures is None:
            empty_frame = pl.LazyFrame(
                {
                    "exposure_reference": pl.Series([], dtype=pl.String),
                    "equity_type": pl.Series([], dtype=pl.String),
                    "ead_final": pl.Series([], dtype=pl.Float64),
                    "risk_weight": pl.Series([], dtype=pl.Float64),
                    "rwa": pl.Series([], dtype=pl.Float64),
                }
            )
            return EquityResultBundle(
                results=empty_frame,
                calculation_audit=empty_frame,
                approach="sa",
                errors=[],
            )

        approach = self._determine_approach(config)

        exposures = self._prepare_columns(exposures, config)

        if approach == "irb_simple":
            exposures = self._apply_equity_weights_irb_simple(exposures, config)
        else:
            exposures = self._apply_equity_weights_sa(exposures, config)

        exposures = self._calculate_rwa(exposures)

        audit = self._build_audit(exposures, approach)

        return EquityResultBundle(
            results=exposures,
            calculation_audit=audit,
            approach=approach,
            errors=errors,
        )

    def _determine_approach(self, config: CalculationConfig) -> str:
        """
        Determine SA vs IRB_SIMPLE based on config.

        Under Basel 3.1 (CRE20.58-62): IRB for equity is removed — all equity
        exposures must use SA treatment. The IRB Simple Risk Weight Method
        (Art. 155: 190%/290%/370%) is no longer available.

        Under CRR: If the firm has IRB permissions (FIRB or AIRB) for any
        exposure class, they must use Article 155 IRB Simple approach for equity.
        If SA-only, use Article 133 SA approach.

        Args:
            config: Calculation configuration

        Returns:
            "sa" for Article 133, "irb_simple" for Article 155
        """
        # Basel 3.1: IRB equity removed — all equity uses SA (CRE20.58-62)
        if config.is_basel_3_1:
            return "sa"

        # CRR: Check if firm has any IRB permissions beyond SA
        # If permissions dict is empty, it's SA-only
        if not config.irb_permissions.permissions:
            return "sa"

        # Check if any exposure class has FIRB or AIRB permission
        for _exposure_class, approaches in config.irb_permissions.permissions.items():
            if ApproachType.FIRB in approaches or ApproachType.AIRB in approaches:
                return "irb_simple"

        return "sa"

    def _prepare_columns(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Ensure all required columns exist with defaults."""
        schema = exposures.collect_schema()

        if "ead_final" not in schema.names():
            if "fair_value" in schema.names():
                exposures = exposures.with_columns(
                    [
                        pl.col("fair_value").alias("ead_final"),
                    ]
                )
            elif "carrying_value" in schema.names():
                exposures = exposures.with_columns(
                    [
                        pl.col("carrying_value").alias("ead_final"),
                    ]
                )
            elif "ead" in schema.names():
                exposures = exposures.with_columns(
                    [
                        pl.col("ead").alias("ead_final"),
                    ]
                )
            else:
                exposures = exposures.with_columns(
                    [
                        pl.lit(0.0).alias("ead_final"),
                    ]
                )

        schema = exposures.collect_schema()

        if "equity_type" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit("other").alias("equity_type"),
                ]
            )

        if "is_diversified_portfolio" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit(False).alias("is_diversified_portfolio"),
                ]
            )

        if "is_speculative" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit(False).alias("is_speculative"),
                ]
            )

        if "is_exchange_traded" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit(False).alias("is_exchange_traded"),
                ]
            )

        if "is_government_supported" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit(False).alias("is_government_supported"),
                ]
            )

        return exposures

    def _apply_equity_weights_sa(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply Article 133 (SA) equity risk weights.

        Risk weights:
        - Central bank: 0%
        - Listed/Exchange-traded/Government-supported: 100%
        - Unlisted: 250%
        - Speculative: 400%
        """
        return exposures.with_columns(
            [
                pl.when(pl.col("equity_type").str.to_lowercase() == "central_bank")
                .then(pl.lit(0.00))
                .when(pl.col("is_speculative") == True)  # noqa: E712
                .then(pl.lit(4.00))
                .when(pl.col("equity_type").str.to_lowercase() == "speculative")
                .then(pl.lit(4.00))
                .when(pl.col("is_exchange_traded") == True)  # noqa: E712
                .then(pl.lit(1.00))
                .when(pl.col("equity_type").str.to_lowercase() == "listed")
                .then(pl.lit(1.00))
                .when(pl.col("equity_type").str.to_lowercase() == "exchange_traded")
                .then(pl.lit(1.00))
                .when(pl.col("is_government_supported") == True)  # noqa: E712
                .then(pl.lit(1.00))
                .when(pl.col("equity_type").str.to_lowercase() == "government_supported")
                .then(pl.lit(1.00))
                .when(pl.col("equity_type").str.to_lowercase() == "unlisted")
                .then(pl.lit(2.50))
                .when(pl.col("equity_type").str.to_lowercase() == "private_equity")
                .then(pl.lit(2.50))
                .when(pl.col("equity_type").str.to_lowercase() == "private_equity_diversified")
                .then(pl.lit(2.50))
                .when(pl.col("equity_type").str.to_lowercase() == "ciu")
                .then(pl.lit(2.50))
                .otherwise(pl.lit(2.50))
                .alias("risk_weight"),
            ]
        )

    def _apply_equity_weights_irb_simple(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply Article 155 (IRB Simple) equity risk weights.

        Risk weights:
        - Central bank: 0%
        - Private equity (diversified portfolio): 190%
        - Exchange-traded: 290%
        - Other equity: 370%
        """
        return exposures.with_columns(
            [
                pl.when(pl.col("equity_type").str.to_lowercase() == "central_bank")
                .then(pl.lit(0.00))
                .when(
                    (pl.col("equity_type").str.to_lowercase() == "private_equity_diversified")
                    | (
                        (pl.col("equity_type").str.to_lowercase() == "private_equity")
                        & (pl.col("is_diversified_portfolio") == True)  # noqa: E712
                    )
                )
                .then(pl.lit(1.90))
                .when(pl.col("is_government_supported") == True)  # noqa: E712
                .then(pl.lit(1.90))
                .when(pl.col("equity_type").str.to_lowercase() == "government_supported")
                .then(pl.lit(1.90))
                .when(pl.col("is_exchange_traded") == True)  # noqa: E712
                .then(pl.lit(2.90))
                .when(pl.col("equity_type").str.to_lowercase() == "listed")
                .then(pl.lit(2.90))
                .when(pl.col("equity_type").str.to_lowercase() == "exchange_traded")
                .then(pl.lit(2.90))
                .otherwise(pl.lit(3.70))
                .alias("risk_weight"),
            ]
        )

    def _calculate_rwa(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Calculate RWA = EAD x RW."""
        return exposures.with_columns(
            [
                (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa"),
                (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa_final"),
            ]
        )

    def _build_audit(
        self,
        exposures: pl.LazyFrame,
        approach: str,
    ) -> pl.LazyFrame:
        """Build equity calculation audit trail."""
        schema = exposures.collect_schema()
        available_cols = schema.names()

        select_cols = ["exposure_reference"]
        optional_cols = [
            "counterparty_reference",
            "equity_type",
            "is_speculative",
            "is_exchange_traded",
            "is_government_supported",
            "is_diversified_portfolio",
            "ead_final",
            "risk_weight",
            "rwa",
        ]

        for col in optional_cols:
            if col in available_cols:
                select_cols.append(col)

        audit = exposures.select(select_cols)

        article = "Art. 133 SA" if approach == "sa" else "Art. 155 IRB Simple"

        audit = audit.with_columns(
            [
                pl.concat_str(
                    [
                        pl.lit(f"Equity ({article}): Type="),
                        pl.col("equity_type"),
                        pl.lit(", RW="),
                        (pl.col("risk_weight") * 100).round(0).cast(pl.String),
                        pl.lit("%, RWA="),
                        pl.col("rwa").round(0).cast(pl.String),
                    ]
                ).alias("equity_calculation"),
            ]
        )

        return audit

    def calculate_single_exposure(
        self,
        ead: Decimal,
        equity_type: str,
        is_diversified: bool = False,
        is_speculative: bool = False,
        is_exchange_traded: bool = False,
        is_government_supported: bool = False,
        config: CalculationConfig | None = None,
    ) -> dict:
        """
        Calculate RWA for a single equity exposure (convenience method).

        Args:
            ead: Exposure at default
            equity_type: Type of equity exposure
            is_diversified: Whether in diversified portfolio (for PE)
            is_speculative: Whether speculative unlisted
            is_exchange_traded: Whether exchange traded
            is_government_supported: Whether government supported
            config: Calculation configuration (defaults to CRR SA)

        Returns:
            Dictionary with calculation results
        """
        from datetime import date

        from rwa_calc.contracts.config import CalculationConfig

        if config is None:
            config = CalculationConfig.crr(reporting_date=date.today())

        approach = self._determine_approach(config)

        if is_speculative:
            effective_type = "speculative"
        elif is_exchange_traded:
            effective_type = "exchange_traded"
        elif is_government_supported:
            effective_type = "government_supported"
        elif equity_type.lower() == "private_equity" and is_diversified:
            effective_type = "private_equity_diversified"
        else:
            effective_type = equity_type

        risk_weight = lookup_equity_rw(effective_type, approach, is_diversified)

        rwa = ead * risk_weight

        return {
            "ead": float(ead),
            "equity_type": equity_type,
            "effective_type": effective_type,
            "is_diversified": is_diversified,
            "is_speculative": is_speculative,
            "is_exchange_traded": is_exchange_traded,
            "is_government_supported": is_government_supported,
            "approach": approach,
            "article": "133" if approach == "sa" else "155",
            "risk_weight": float(risk_weight),
            "rwa": float(rwa),
        }


def create_equity_calculator() -> EquityCalculator:
    """
    Create an equity calculator instance.

    Returns:
        EquityCalculator ready for use
    """
    return EquityCalculator()
