"""
Collateral haircut calculator for credit risk mitigation.

Pipeline position:
    Classifier -> CRMProcessor -> HaircutCalculator -> SA/IRB Calculators

Key responsibilities:
- Apply supervisory haircuts by collateral type, CQS, and maturity
- Framework-conditional logic: CRR (Art. 224) vs Basel 3.1 (CRE22.52-53)
- FX mismatch haircuts (8%, same under both frameworks)
- Maturity mismatch adjustments (CRR Art. 238)

References:
    CRR Art. 224: Supervisory haircuts (3 maturity bands)
    CRE22.52-53: Basel 3.1 supervisory haircuts (5 maturity bands, higher equity/long-dated)
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

    Supports both CRR and Basel 3.1 frameworks:

    CRR (Art. 224) — 3 maturity bands:
    - Government bonds: 0.5% - 6%
    - Corporate bonds: 1% - 8%
    - Equity (main index): 15%, (other): 25%

    Basel 3.1 (CRE22.52-53) — 5 maturity bands:
    - Government bonds: 0.5% - 12% (higher for long-dated CQS 2-3)
    - Corporate bonds: 1% - 15% (significantly higher for long-dated)
    - Equity (main index): 25%, (other): 35%

    Cash: 0%, Gold: 15%, FX mismatch: 8% — same under both frameworks.
    """

    def __init__(self, is_basel_3_1: bool = False) -> None:
        """Initialize haircut calculator with lookup tables.

        Args:
            is_basel_3_1: True for Basel 3.1 haircuts, False for CRR
        """
        self._is_basel_3_1 = is_basel_3_1
        self._haircut_table = get_haircut_table(is_basel_3_1=is_basel_3_1)

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
        is_b31 = config.is_basel_3_1

        # Add maturity band for bond haircut lookup
        collateral = collateral.with_columns(
            [self._maturity_band_expression(is_b31).alias("maturity_band")]
        )

        # Calculate collateral-specific haircut based on type
        collateral = self._apply_collateral_haircuts(collateral, is_b31)

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

    @staticmethod
    def _maturity_band_expression(is_basel_3_1: bool) -> pl.Expr:
        """Build Polars expression to classify residual maturity into bands.

        CRR: 3 bands (0-1y, 1-5y, 5y+)
        Basel 3.1: 5 bands (0-1y, 1-3y, 3-5y, 5-10y, 10y+)
        """
        mat = pl.col("residual_maturity_years")
        if is_basel_3_1:
            return (
                pl.when(mat.is_null())
                .then(pl.lit("10y_plus"))
                .when(mat <= 1.0)
                .then(pl.lit("0_1y"))
                .when(mat <= 3.0)
                .then(pl.lit("1_3y"))
                .when(mat <= 5.0)
                .then(pl.lit("3_5y"))
                .when(mat <= 10.0)
                .then(pl.lit("5_10y"))
                .otherwise(pl.lit("10y_plus"))
            )
        return (
            pl.when(mat.is_null())
            .then(pl.lit("5y_plus"))
            .when(mat <= 1.0)
            .then(pl.lit("0_1y"))
            .when(mat <= 5.0)
            .then(pl.lit("1_5y"))
            .otherwise(pl.lit("5y_plus"))
        )

    def _apply_collateral_haircuts(
        self,
        collateral: pl.LazyFrame,
        is_basel_3_1: bool = False,
    ) -> pl.LazyFrame:
        """
        Apply collateral-type-specific haircuts.

        Args:
            collateral: Collateral with collateral_type column
            is_basel_3_1: Whether to use Basel 3.1 haircut values

        Returns:
            LazyFrame with collateral_haircut column added
        """
        # Equity haircut values differ by framework
        equity_main = 0.25 if is_basel_3_1 else 0.15
        equity_other = 0.35 if is_basel_3_1 else 0.25

        # Bond haircuts — build the when/then chain
        # Government bonds by CQS and maturity band
        expr = self._build_govt_bond_haircut_chain(is_basel_3_1)

        # Corporate bonds by CQS and maturity band
        expr = self._extend_corp_bond_haircut_chain(expr, is_basel_3_1)

        return collateral.with_columns(
            [
                # Cash - 0%
                pl.when(pl.col("collateral_type").str.to_lowercase().is_in(["cash", "deposit"]))
                .then(pl.lit(0.00))
                # Gold - 15%
                .when(pl.col("collateral_type").str.to_lowercase() == "gold")
                .then(pl.lit(0.15))
                # Government and corporate bonds via chain
                .when(expr.is_not_null())
                .then(expr)
                # Equity
                .when(
                    (
                        pl.col("collateral_type")
                        .str.to_lowercase()
                        .is_in(["equity", "shares", "stock"])
                    )
                    & (pl.col("is_eligible_financial_collateral") == True)  # noqa: E712
                )
                .then(pl.lit(equity_main))
                .when(
                    pl.col("collateral_type")
                    .str.to_lowercase()
                    .is_in(["equity", "shares", "stock"])
                )
                .then(pl.lit(equity_other))
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

    def _build_govt_bond_haircut_chain(self, is_basel_3_1: bool) -> pl.Expr:
        """Build Polars expression for government bond haircuts by CQS and maturity band."""
        govt_types = pl.col("collateral_type").str.to_lowercase().is_in(
            ["govt_bond", "sovereign_bond", "government_bond", "gilt"]
        ) | (
            (pl.col("collateral_type").str.to_lowercase() == "bond")
            & (pl.col("issuer_type").str.to_lowercase() == "sovereign")
        )

        if is_basel_3_1:
            return (
                # CQS 1
                pl.when(
                    govt_types & (pl.col("issuer_cqs") == 1) & (pl.col("maturity_band") == "0_1y")
                )
                .then(pl.lit(0.005))
                .when(
                    govt_types & (pl.col("issuer_cqs") == 1) & (pl.col("maturity_band") == "1_3y")
                )
                .then(pl.lit(0.02))
                .when(
                    govt_types & (pl.col("issuer_cqs") == 1) & (pl.col("maturity_band") == "3_5y")
                )
                .then(pl.lit(0.02))
                .when(
                    govt_types & (pl.col("issuer_cqs") == 1) & (pl.col("maturity_band") == "5_10y")
                )
                .then(pl.lit(0.04))
                .when(
                    govt_types
                    & (pl.col("issuer_cqs") == 1)
                    & (pl.col("maturity_band") == "10y_plus")
                )
                .then(pl.lit(0.04))
                # CQS 2-3
                .when(
                    govt_types
                    & pl.col("issuer_cqs").is_in([2, 3])
                    & (pl.col("maturity_band") == "0_1y")
                )
                .then(pl.lit(0.01))
                .when(
                    govt_types
                    & pl.col("issuer_cqs").is_in([2, 3])
                    & (pl.col("maturity_band") == "1_3y")
                )
                .then(pl.lit(0.03))
                .when(
                    govt_types
                    & pl.col("issuer_cqs").is_in([2, 3])
                    & (pl.col("maturity_band") == "3_5y")
                )
                .then(pl.lit(0.04))
                .when(
                    govt_types
                    & pl.col("issuer_cqs").is_in([2, 3])
                    & (pl.col("maturity_band") == "5_10y")
                )
                .then(pl.lit(0.06))
                .when(
                    govt_types
                    & pl.col("issuer_cqs").is_in([2, 3])
                    & (pl.col("maturity_band") == "10y_plus")
                )
                .then(pl.lit(0.12))
                .otherwise(pl.lit(None))
            )
        return (
            # CQS 1
            pl.when(govt_types & (pl.col("issuer_cqs") == 1) & (pl.col("maturity_band") == "0_1y"))
            .then(pl.lit(0.005))
            .when(govt_types & (pl.col("issuer_cqs") == 1) & (pl.col("maturity_band") == "1_5y"))
            .then(pl.lit(0.02))
            .when(govt_types & (pl.col("issuer_cqs") == 1))
            .then(pl.lit(0.04))
            # CQS 2-3
            .when(
                govt_types
                & pl.col("issuer_cqs").is_in([2, 3])
                & (pl.col("maturity_band") == "0_1y")
            )
            .then(pl.lit(0.01))
            .when(
                govt_types
                & pl.col("issuer_cqs").is_in([2, 3])
                & (pl.col("maturity_band") == "1_5y")
            )
            .then(pl.lit(0.03))
            .when(govt_types & pl.col("issuer_cqs").is_in([2, 3]))
            .then(pl.lit(0.06))
            .otherwise(pl.lit(None))
        )

    def _extend_corp_bond_haircut_chain(self, base_expr: pl.Expr, is_basel_3_1: bool) -> pl.Expr:
        """Build Polars expression for corporate bond haircuts by CQS and maturity band.

        Returns a standalone expression (not chained off base_expr) — caller uses
        coalesce-like when/then to merge government and corporate results.
        """
        corp_types = (
            pl.col("collateral_type").str.to_lowercase().is_in(["corp_bond", "corporate_bond"])
        )

        if is_basel_3_1:
            return (
                # CQS 1-2
                pl.when(
                    corp_types
                    & pl.col("issuer_cqs").is_in([1, 2])
                    & (pl.col("maturity_band") == "0_1y")
                )
                .then(pl.lit(0.01))
                .when(
                    corp_types
                    & pl.col("issuer_cqs").is_in([1, 2])
                    & (pl.col("maturity_band") == "1_3y")
                )
                .then(pl.lit(0.04))
                .when(
                    corp_types
                    & pl.col("issuer_cqs").is_in([1, 2])
                    & (pl.col("maturity_band") == "3_5y")
                )
                .then(pl.lit(0.06))
                .when(
                    corp_types
                    & pl.col("issuer_cqs").is_in([1, 2])
                    & (pl.col("maturity_band") == "5_10y")
                )
                .then(pl.lit(0.10))
                .when(
                    corp_types
                    & pl.col("issuer_cqs").is_in([1, 2])
                    & (pl.col("maturity_band") == "10y_plus")
                )
                .then(pl.lit(0.12))
                # CQS 3
                .when(
                    corp_types & (pl.col("issuer_cqs") == 3) & (pl.col("maturity_band") == "0_1y")
                )
                .then(pl.lit(0.02))
                .when(
                    corp_types & (pl.col("issuer_cqs") == 3) & (pl.col("maturity_band") == "1_3y")
                )
                .then(pl.lit(0.06))
                .when(
                    corp_types & (pl.col("issuer_cqs") == 3) & (pl.col("maturity_band") == "3_5y")
                )
                .then(pl.lit(0.08))
                .when(
                    corp_types & (pl.col("issuer_cqs") == 3) & (pl.col("maturity_band") == "5_10y")
                )
                .then(pl.lit(0.15))
                .when(
                    corp_types
                    & (pl.col("issuer_cqs") == 3)
                    & (pl.col("maturity_band") == "10y_plus")
                )
                .then(pl.lit(0.15))
                .otherwise(base_expr)
            )
        return (
            # CQS 1-2
            pl.when(
                corp_types
                & pl.col("issuer_cqs").is_in([1, 2])
                & (pl.col("maturity_band") == "0_1y")
            )
            .then(pl.lit(0.01))
            .when(
                corp_types
                & pl.col("issuer_cqs").is_in([1, 2])
                & (pl.col("maturity_band") == "1_5y")
            )
            .then(pl.lit(0.04))
            .when(corp_types & pl.col("issuer_cqs").is_in([1, 2]))
            .then(pl.lit(0.06))
            # CQS 3
            .when(corp_types & (pl.col("issuer_cqs") == 3) & (pl.col("maturity_band") == "0_1y"))
            .then(pl.lit(0.02))
            .when(corp_types & (pl.col("issuer_cqs") == 3) & (pl.col("maturity_band") == "1_5y"))
            .then(pl.lit(0.06))
            .when(corp_types & (pl.col("issuer_cqs") == 3))
            .then(pl.lit(0.08))
            .otherwise(base_expr)
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
            is_basel_3_1=self._is_basel_3_1,
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


def create_haircut_calculator(is_basel_3_1: bool = False) -> HaircutCalculator:
    """
    Create a haircut calculator instance.

    Args:
        is_basel_3_1: True for Basel 3.1 haircuts, False for CRR

    Returns:
        HaircutCalculator ready for use
    """
    return HaircutCalculator(is_basel_3_1=is_basel_3_1)
