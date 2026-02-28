"""
Collateral haircut calculator for credit risk mitigation.

Applies supervisory haircuts to collateral per CRR Article 224.

Classes:
    HaircutCalculator: Calculator for collateral haircuts

Usage:
    from rwa_calc.engine.crm.haircuts import HaircutCalculator

    calculator = HaircutCalculator()
    adjusted_collateral = calculator.apply_haircuts(collateral, config)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.data.tables.crr_haircuts import (
    FX_HAIRCUT,
    calculate_adjusted_collateral_value,
    calculate_maturity_mismatch_adjustment,
    get_haircut_table,
    lookup_collateral_haircut,
    lookup_fx_haircut,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


@dataclass
class HaircutResult:
    """Result of haircut calculation for collateral."""

    original_value: Decimal
    collateral_haircut: Decimal
    fx_haircut: Decimal
    maturity_adjustment: Decimal
    adjusted_value: Decimal
    description: str


class HaircutCalculator:
    """
    Calculate and apply haircuts to collateral.

    Implements CRR Article 224 supervisory haircuts:
    - Cash: 0%
    - Government bonds: 0.5% - 6% by CQS and maturity
    - Corporate bonds: 1% - 8% by CQS and maturity
    - Equity (main index): 15%
    - Equity (other): 25%
    - FX mismatch: 8% additional

    Also handles maturity mismatch adjustments per CRR Article 238.
    """

    def __init__(self) -> None:
        """Initialize haircut calculator with lookup tables."""
        self._haircut_table = get_haircut_table()

    def apply_haircuts(
        self,
        collateral: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply haircuts to collateral.

        Expects exposure_currency and exposure_maturity columns to already be
        present on collateral (joined via _join_collateral_to_lookups before calling).

        Args:
            collateral: Collateral data with market values, exposure_currency, exposure_maturity
            config: Calculation configuration

        Returns:
            LazyFrame with haircut-adjusted collateral values
        """
        # Add maturity band for bond haircut lookup
        collateral = collateral.with_columns(
            [
                pl.when(pl.col("residual_maturity_years").is_null())
                .then(pl.lit("5y_plus"))
                .when(pl.col("residual_maturity_years") <= 1.0)
                .then(pl.lit("0_1y"))
                .when(pl.col("residual_maturity_years") <= 5.0)
                .then(pl.lit("1_5y"))
                .otherwise(pl.lit("5y_plus"))
                .alias("maturity_band"),
            ]
        )

        # Calculate collateral-specific haircut based on type
        collateral = self._apply_collateral_haircuts(collateral)

        # Apply FX haircut
        collateral = collateral.with_columns(
            [
                pl.when(pl.col("currency") != pl.col("exposure_currency"))
                .then(pl.lit(float(FX_HAIRCUT)))
                .otherwise(pl.lit(0.0))
                .alias("fx_haircut"),
            ]
        )

        # Calculate adjusted value after haircuts
        collateral = collateral.with_columns(
            [
                (
                    pl.col("market_value")
                    * (1.0 - pl.col("collateral_haircut") - pl.col("fx_haircut"))
                ).alias("value_after_haircut"),
            ]
        )

        # Add haircut audit trail
        collateral = collateral.with_columns(
            [
                pl.concat_str(
                    [
                        pl.lit("MV="),
                        pl.col("market_value").round(0).cast(pl.String),
                        pl.lit("; Hc="),
                        (pl.col("collateral_haircut") * 100).round(1).cast(pl.String),
                        pl.lit("%; Hfx="),
                        (pl.col("fx_haircut") * 100).round(1).cast(pl.String),
                        pl.lit("%; Adj="),
                        pl.col("value_after_haircut").round(0).cast(pl.String),
                    ]
                ).alias("haircut_calculation"),
            ]
        )

        return collateral

    def _apply_collateral_haircuts(
        self,
        collateral: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Apply collateral-type-specific haircuts.

        Args:
            collateral: Collateral with collateral_type column

        Returns:
            LazyFrame with collateral_haircut column added
        """
        return collateral.with_columns(
            [
                # Cash - 0%
                pl.when(pl.col("collateral_type").str.to_lowercase().is_in(["cash", "deposit"]))
                .then(pl.lit(0.00))
                # Gold - 15%
                .when(pl.col("collateral_type").str.to_lowercase() == "gold")
                .then(pl.lit(0.15))
                # Government bonds - by CQS and maturity
                # Match explicit govt bond types or generic "bond" with sovereign issuer
                .when(
                    (
                        pl.col("collateral_type")
                        .str.to_lowercase()
                        .is_in(["govt_bond", "sovereign_bond", "government_bond", "gilt"])
                        | (
                            (pl.col("collateral_type").str.to_lowercase() == "bond")
                            & (pl.col("issuer_type").str.to_lowercase() == "sovereign")
                        )
                    )
                    & (pl.col("issuer_cqs") == 1)
                    & (pl.col("maturity_band") == "0_1y")
                )
                .then(pl.lit(0.005))
                .when(
                    (
                        pl.col("collateral_type")
                        .str.to_lowercase()
                        .is_in(["govt_bond", "sovereign_bond", "government_bond", "gilt"])
                        | (
                            (pl.col("collateral_type").str.to_lowercase() == "bond")
                            & (pl.col("issuer_type").str.to_lowercase() == "sovereign")
                        )
                    )
                    & (pl.col("issuer_cqs") == 1)
                    & (pl.col("maturity_band") == "1_5y")
                )
                .then(pl.lit(0.02))
                .when(
                    (
                        pl.col("collateral_type")
                        .str.to_lowercase()
                        .is_in(["govt_bond", "sovereign_bond", "government_bond", "gilt"])
                        | (
                            (pl.col("collateral_type").str.to_lowercase() == "bond")
                            & (pl.col("issuer_type").str.to_lowercase() == "sovereign")
                        )
                    )
                    & (pl.col("issuer_cqs") == 1)
                )
                .then(pl.lit(0.04))
                .when(
                    (
                        pl.col("collateral_type")
                        .str.to_lowercase()
                        .is_in(["govt_bond", "sovereign_bond", "government_bond", "gilt"])
                        | (
                            (pl.col("collateral_type").str.to_lowercase() == "bond")
                            & (pl.col("issuer_type").str.to_lowercase() == "sovereign")
                        )
                    )
                    & (pl.col("issuer_cqs").is_in([2, 3]))
                    & (pl.col("maturity_band") == "0_1y")
                )
                .then(pl.lit(0.01))
                .when(
                    (
                        pl.col("collateral_type")
                        .str.to_lowercase()
                        .is_in(["govt_bond", "sovereign_bond", "government_bond", "gilt"])
                        | (
                            (pl.col("collateral_type").str.to_lowercase() == "bond")
                            & (pl.col("issuer_type").str.to_lowercase() == "sovereign")
                        )
                    )
                    & (pl.col("issuer_cqs").is_in([2, 3]))
                    & (pl.col("maturity_band") == "1_5y")
                )
                .then(pl.lit(0.03))
                .when(
                    (
                        pl.col("collateral_type")
                        .str.to_lowercase()
                        .is_in(["govt_bond", "sovereign_bond", "government_bond", "gilt"])
                        | (
                            (pl.col("collateral_type").str.to_lowercase() == "bond")
                            & (pl.col("issuer_type").str.to_lowercase() == "sovereign")
                        )
                    )
                    & (pl.col("issuer_cqs").is_in([2, 3]))
                )
                .then(pl.lit(0.06))
                # Corporate bonds CQS 1-2
                .when(
                    (
                        pl.col("collateral_type")
                        .str.to_lowercase()
                        .is_in(["corp_bond", "corporate_bond"])
                    )
                    & (pl.col("issuer_cqs").is_in([1, 2]))
                    & (pl.col("maturity_band") == "0_1y")
                )
                .then(pl.lit(0.01))
                .when(
                    (
                        pl.col("collateral_type")
                        .str.to_lowercase()
                        .is_in(["corp_bond", "corporate_bond"])
                    )
                    & (pl.col("issuer_cqs").is_in([1, 2]))
                    & (pl.col("maturity_band") == "1_5y")
                )
                .then(pl.lit(0.04))
                .when(
                    (
                        pl.col("collateral_type")
                        .str.to_lowercase()
                        .is_in(["corp_bond", "corporate_bond"])
                    )
                    & (pl.col("issuer_cqs").is_in([1, 2]))
                )
                .then(pl.lit(0.06))
                # Corporate bonds CQS 3
                .when(
                    (
                        pl.col("collateral_type")
                        .str.to_lowercase()
                        .is_in(["corp_bond", "corporate_bond"])
                    )
                    & (pl.col("issuer_cqs") == 3)
                    & (pl.col("maturity_band") == "0_1y")
                )
                .then(pl.lit(0.02))
                .when(
                    (
                        pl.col("collateral_type")
                        .str.to_lowercase()
                        .is_in(["corp_bond", "corporate_bond"])
                    )
                    & (pl.col("issuer_cqs") == 3)
                    & (pl.col("maturity_band") == "1_5y")
                )
                .then(pl.lit(0.06))
                .when(
                    (
                        pl.col("collateral_type")
                        .str.to_lowercase()
                        .is_in(["corp_bond", "corporate_bond"])
                    )
                    & (pl.col("issuer_cqs") == 3)
                )
                .then(pl.lit(0.08))
                # Equity - main index 15%, other 25%
                .when(
                    (
                        pl.col("collateral_type")
                        .str.to_lowercase()
                        .is_in(["equity", "shares", "stock"])
                    )
                    & (pl.col("is_eligible_financial_collateral") == True)  # noqa: E712
                )
                .then(pl.lit(0.15))  # Main index
                .when(
                    pl.col("collateral_type")
                    .str.to_lowercase()
                    .is_in(["equity", "shares", "stock"])
                )
                .then(pl.lit(0.25))  # Other equity
                # Receivables - 20%
                .when(
                    pl.col("collateral_type")
                    .str.to_lowercase()
                    .is_in(["receivables", "trade_receivables"])
                )
                .then(pl.lit(0.20))
                # Real estate - no haircut (LTV-based treatment)
                .when(
                    pl.col("collateral_type")
                    .str.to_lowercase()
                    .is_in(
                        [
                            "real_estate",
                            "property",
                            "rre",
                            "cre",
                            "residential_property",
                            "commercial_property",
                        ]
                    )
                )
                .then(pl.lit(0.00))
                # Other physical - 40%
                .otherwise(pl.lit(0.40))
                .alias("collateral_haircut"),
            ]
        )

    def apply_maturity_mismatch(
        self,
        collateral: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Apply maturity mismatch adjustment per CRR Article 238.

        Args:
            collateral: Collateral with value_after_haircut and exposure_maturity

        Returns:
            LazyFrame with maturity-adjusted collateral values
        """
        # Calculate residual maturities
        collateral = collateral.with_columns(
            [
                # Collateral residual maturity
                pl.col("residual_maturity_years").fill_null(10.0).alias("coll_maturity"),
            ]
        )

        # Join to get exposure maturity (already joined in apply_haircuts)
        # Calculate maturity mismatch adjustment
        collateral = collateral.with_columns(
            [
                # If collateral maturity >= exposure maturity, no adjustment
                pl.when(
                    pl.col("coll_maturity") >= 5.0  # Assume 5y cap
                )
                .then(pl.lit(1.0))
                # If collateral < 3 months, no protection
                .when(pl.col("coll_maturity") < 0.25)
                .then(pl.lit(0.0))
                # Apply adjustment: (t - 0.25) / (T - 0.25)
                .otherwise(
                    (pl.col("coll_maturity") - 0.25) / (5.0 - 0.25)  # Simplified with T=5
                )
                .alias("maturity_adjustment_factor"),
            ]
        )

        # Apply maturity adjustment
        collateral = collateral.with_columns(
            [
                (pl.col("value_after_haircut") * pl.col("maturity_adjustment_factor")).alias(
                    "value_after_maturity_adj"
                ),
            ]
        )

        return collateral

    def calculate_single_haircut(
        self,
        collateral_type: str,
        market_value: Decimal,
        collateral_currency: str,
        exposure_currency: str,
        cqs: int | None = None,
        residual_maturity_years: float | None = None,
        is_main_index: bool = False,
        collateral_maturity_years: float | None = None,
        exposure_maturity_years: float | None = None,
    ) -> HaircutResult:
        """
        Calculate haircut for a single collateral item (convenience method).

        Args:
            collateral_type: Type of collateral
            market_value: Market value of collateral
            collateral_currency: Currency of collateral
            exposure_currency: Currency of exposure
            cqs: Credit quality step of issuer
            residual_maturity_years: Residual maturity for bonds
            is_main_index: Whether equity is on main index
            collateral_maturity_years: For maturity mismatch
            exposure_maturity_years: For maturity mismatch

        Returns:
            HaircutResult with all haircut details
        """
        # Get collateral haircut
        coll_haircut = lookup_collateral_haircut(
            collateral_type=collateral_type,
            cqs=cqs,
            residual_maturity_years=residual_maturity_years,
            is_main_index=is_main_index,
        )

        # Get FX haircut
        fx_haircut = lookup_fx_haircut(exposure_currency, collateral_currency)

        # Calculate adjusted value after haircuts
        adjusted = calculate_adjusted_collateral_value(
            collateral_value=market_value,
            collateral_haircut=coll_haircut,
            fx_haircut=fx_haircut,
        )

        # Apply maturity mismatch if applicable
        maturity_adj = Decimal("1.0")
        if collateral_maturity_years and exposure_maturity_years:
            adjusted, _ = calculate_maturity_mismatch_adjustment(
                collateral_value=adjusted,
                collateral_maturity_years=collateral_maturity_years,
                exposure_maturity_years=exposure_maturity_years,
            )
            if adjusted > Decimal("0"):
                maturity_adj = adjusted / (market_value * (1 - coll_haircut - fx_haircut))

        description = (
            f"MV={market_value:,.0f}; Hc={coll_haircut:.1%}; "
            f"Hfx={fx_haircut:.1%}; Adj={adjusted:,.0f}"
        )

        return HaircutResult(
            original_value=market_value,
            collateral_haircut=coll_haircut,
            fx_haircut=fx_haircut,
            maturity_adjustment=maturity_adj,
            adjusted_value=adjusted,
            description=description,
        )


def create_haircut_calculator() -> HaircutCalculator:
    """
    Create a haircut calculator instance.

    Returns:
        HaircutCalculator ready for use
    """
    return HaircutCalculator()
