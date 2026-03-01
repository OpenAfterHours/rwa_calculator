"""
Polars LazyFrame namespaces for Equity calculations.

Provides fluent API for equity exposure RWA calculation via registered namespaces:
- `lf.equity.prepare_columns(config)` - Ensure required columns exist
- `lf.equity.apply_equity_weights_sa()` - Apply Article 133 SA risk weights
- `lf.equity.apply_equity_weights_irb_simple()` - Apply Article 155 IRB Simple risk weights
- `lf.equity.calculate_rwa()` - Calculate RWA

Usage:
    import polars as pl
    from rwa_calc.contracts.config import CalculationConfig
    import rwa_calc.engine.equity.namespace  # Register namespace

    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    result = (exposures
        .equity.prepare_columns(config)
        .equity.apply_equity_weights_sa()
        .equity.calculate_rwa()
    )

References:
- CRR Art. 133: Equity exposures under SA
- CRR Art. 155: Simple risk weight approach under IRB
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# EQUITY RISK WEIGHTS
# =============================================================================

# Article 133 - Standardised Approach
SA_EQUITY_WEIGHTS = {
    "central_bank": 0.00,
    "listed": 1.00,
    "exchange_traded": 1.00,
    "government_supported": 1.00,
    "unlisted": 2.50,
    "speculative": 4.00,
    "private_equity": 2.50,
    "private_equity_diversified": 2.50,
    "ciu": 2.50,
    "other": 2.50,
}

# Article 155 - IRB Simple Risk Weight Method
IRB_SIMPLE_EQUITY_WEIGHTS = {
    "central_bank": 0.00,
    "private_equity_diversified": 1.90,
    "private_equity": 3.70,
    "exchange_traded": 2.90,
    "listed": 2.90,
    "government_supported": 1.90,
    "unlisted": 3.70,
    "speculative": 3.70,
    "ciu": 3.70,
    "other": 3.70,
}


# =============================================================================
# LAZYFRAME NAMESPACE
# =============================================================================


@pl.api.register_lazyframe_namespace("equity")
class EquityLazyFrame:
    """
    Equity calculation namespace for Polars LazyFrames.

    Provides fluent API for equity exposure RWA calculation.

    Example:
        result = (exposures
            .equity.prepare_columns(config)
            .equity.apply_equity_weights_sa()
            .equity.calculate_rwa()
        )
    """

    def __init__(self, lf: pl.LazyFrame) -> None:
        self._lf = lf

    # =========================================================================
    # PREPARATION METHODS
    # =========================================================================

    def prepare_columns(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Ensure all required columns exist with defaults.

        Adds/normalizes:
        - ead_final: Exposure at default (from fair_value/carrying_value)
        - equity_type: Type of equity exposure
        - is_diversified_portfolio: Whether in diversified portfolio
        - is_speculative: Whether speculative unlisted
        - is_exchange_traded: Whether exchange traded
        - is_government_supported: Whether government supported

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with all required columns
        """
        schema = self._lf.collect_schema()
        lf = self._lf

        # EAD - use fair_value, then carrying_value, then ead
        if "ead_final" not in schema.names():
            if "fair_value" in schema.names():
                lf = lf.with_columns([pl.col("fair_value").alias("ead_final")])
            elif "carrying_value" in schema.names():
                lf = lf.with_columns([pl.col("carrying_value").alias("ead_final")])
            elif "ead" in schema.names():
                lf = lf.with_columns([pl.col("ead").alias("ead_final")])
            else:
                lf = lf.with_columns([pl.lit(0.0).alias("ead_final")])

        # Refresh schema
        schema = lf.collect_schema()

        # Equity type
        if "equity_type" not in schema.names():
            lf = lf.with_columns([pl.lit("other").alias("equity_type")])

        # Boolean flags
        if "is_diversified_portfolio" not in schema.names():
            lf = lf.with_columns([pl.lit(False).alias("is_diversified_portfolio")])

        if "is_speculative" not in schema.names():
            lf = lf.with_columns([pl.lit(False).alias("is_speculative")])

        if "is_exchange_traded" not in schema.names():
            lf = lf.with_columns([pl.lit(False).alias("is_exchange_traded")])

        if "is_government_supported" not in schema.names():
            lf = lf.with_columns([pl.lit(False).alias("is_government_supported")])

        return lf

    # =========================================================================
    # RISK WEIGHT APPLICATION
    # =========================================================================

    def apply_equity_weights_sa(self) -> pl.LazyFrame:
        """
        Apply Article 133 (SA) equity risk weights.

        Risk weights:
        - Central bank: 0%
        - Listed/Exchange-traded/Government-supported: 100%
        - Unlisted/Private equity: 250%
        - Speculative: 400%

        Returns:
            LazyFrame with risk_weight column added
        """
        return self._lf.with_columns(
            [
                pl.when(pl.col("equity_type").str.to_lowercase() == "central_bank")
                .then(pl.lit(SA_EQUITY_WEIGHTS["central_bank"]))
                # Speculative takes precedence
                .when(pl.col("is_speculative") == True)  # noqa: E712
                .then(pl.lit(SA_EQUITY_WEIGHTS["speculative"]))
                .when(pl.col("equity_type").str.to_lowercase() == "speculative")
                .then(pl.lit(SA_EQUITY_WEIGHTS["speculative"]))
                # Exchange traded
                .when(pl.col("is_exchange_traded") == True)  # noqa: E712
                .then(pl.lit(SA_EQUITY_WEIGHTS["exchange_traded"]))
                .when(pl.col("equity_type").str.to_lowercase() == "listed")
                .then(pl.lit(SA_EQUITY_WEIGHTS["listed"]))
                .when(pl.col("equity_type").str.to_lowercase() == "exchange_traded")
                .then(pl.lit(SA_EQUITY_WEIGHTS["exchange_traded"]))
                # Government supported
                .when(pl.col("is_government_supported") == True)  # noqa: E712
                .then(pl.lit(SA_EQUITY_WEIGHTS["government_supported"]))
                .when(pl.col("equity_type").str.to_lowercase() == "government_supported")
                .then(pl.lit(SA_EQUITY_WEIGHTS["government_supported"]))
                # Unlisted / Private equity
                .when(pl.col("equity_type").str.to_lowercase() == "unlisted")
                .then(pl.lit(SA_EQUITY_WEIGHTS["unlisted"]))
                .when(pl.col("equity_type").str.to_lowercase() == "private_equity")
                .then(pl.lit(SA_EQUITY_WEIGHTS["private_equity"]))
                .when(pl.col("equity_type").str.to_lowercase() == "private_equity_diversified")
                .then(pl.lit(SA_EQUITY_WEIGHTS["private_equity_diversified"]))
                .when(pl.col("equity_type").str.to_lowercase() == "ciu")
                .then(pl.lit(SA_EQUITY_WEIGHTS["ciu"]))
                .otherwise(pl.lit(SA_EQUITY_WEIGHTS["other"]))
                .alias("risk_weight"),
            ]
        )

    def apply_equity_weights_irb_simple(self) -> pl.LazyFrame:
        """
        Apply Article 155 (IRB Simple) equity risk weights.

        Risk weights:
        - Central bank: 0%
        - Private equity (diversified portfolio): 190%
        - Government supported: 190%
        - Exchange-traded/Listed: 290%
        - Other equity: 370%

        Returns:
            LazyFrame with risk_weight column added
        """
        return self._lf.with_columns(
            [
                pl.when(pl.col("equity_type").str.to_lowercase() == "central_bank")
                .then(pl.lit(IRB_SIMPLE_EQUITY_WEIGHTS["central_bank"]))
                # Private equity diversified
                .when(pl.col("equity_type").str.to_lowercase() == "private_equity_diversified")
                .then(pl.lit(IRB_SIMPLE_EQUITY_WEIGHTS["private_equity_diversified"]))
                .when(
                    (pl.col("equity_type").str.to_lowercase() == "private_equity")
                    & (pl.col("is_diversified_portfolio") == True)  # noqa: E712
                )
                .then(pl.lit(IRB_SIMPLE_EQUITY_WEIGHTS["private_equity_diversified"]))
                # Government supported (treated as 190%)
                .when(pl.col("is_government_supported") == True)  # noqa: E712
                .then(pl.lit(IRB_SIMPLE_EQUITY_WEIGHTS["government_supported"]))
                .when(pl.col("equity_type").str.to_lowercase() == "government_supported")
                .then(pl.lit(IRB_SIMPLE_EQUITY_WEIGHTS["government_supported"]))
                # Exchange traded / Listed
                .when(pl.col("is_exchange_traded") == True)  # noqa: E712
                .then(pl.lit(IRB_SIMPLE_EQUITY_WEIGHTS["exchange_traded"]))
                .when(pl.col("equity_type").str.to_lowercase() == "listed")
                .then(pl.lit(IRB_SIMPLE_EQUITY_WEIGHTS["listed"]))
                .when(pl.col("equity_type").str.to_lowercase() == "exchange_traded")
                .then(pl.lit(IRB_SIMPLE_EQUITY_WEIGHTS["exchange_traded"]))
                # All others get 370%
                .otherwise(pl.lit(IRB_SIMPLE_EQUITY_WEIGHTS["other"]))
                .alias("risk_weight"),
            ]
        )

    # =========================================================================
    # RWA CALCULATION
    # =========================================================================

    def calculate_rwa(self) -> pl.LazyFrame:
        """
        Calculate RWA = EAD x Risk Weight.

        Returns:
            LazyFrame with rwa and rwa_final columns
        """
        return self._lf.with_columns(
            [
                (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa"),
                (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa_final"),
            ]
        )

    # =========================================================================
    # CONVENIENCE / PIPELINE METHODS
    # =========================================================================

    def apply_all_sa(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply full equity SA calculation pipeline.

        Steps:
        1. Prepare columns
        2. Apply SA equity weights (Article 133)
        3. Calculate RWA

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with all equity calculations
        """
        return (
            self._lf.equity.prepare_columns(config)
            .equity.apply_equity_weights_sa()
            .equity.calculate_rwa()
        )

    def apply_all_irb_simple(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply full equity IRB Simple calculation pipeline.

        Steps:
        1. Prepare columns
        2. Apply IRB Simple equity weights (Article 155)
        3. Calculate RWA

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with all equity calculations
        """
        return (
            self._lf.equity.prepare_columns(config)
            .equity.apply_equity_weights_irb_simple()
            .equity.calculate_rwa()
        )

    def build_audit(self, approach: str = "sa") -> pl.LazyFrame:
        """
        Build equity calculation audit trail.

        Args:
            approach: "sa" for Article 133, "irb_simple" for Article 155

        Returns:
            LazyFrame with audit columns including equity_calculation string
        """
        schema = self._lf.collect_schema()
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

        audit = self._lf.select(select_cols)

        article = "Art. 133 SA" if approach == "sa" else "Art. 155 IRB Simple"

        if "rwa" in available_cols:
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


# =============================================================================
# EXPRESSION NAMESPACE
# =============================================================================


@pl.api.register_expr_namespace("equity")
class EquityExpr:
    """
    Equity calculation namespace for Polars Expressions.

    Provides column-level operations for equity calculations.

    Example:
        df.with_columns(
            pl.col("equity_type").equity.lookup_rw(approach="sa"),
        )
    """

    def __init__(self, expr: pl.Expr) -> None:
        self._expr = expr

    def lookup_rw(self, approach: str = "sa") -> pl.Expr:
        """
        Look up risk weight based on equity type.

        Args:
            approach: "sa" for Article 133, "irb_simple" for Article 155

        Returns:
            Expression with risk weight
        """
        weights = IRB_SIMPLE_EQUITY_WEIGHTS if approach == "irb_simple" else SA_EQUITY_WEIGHTS

        return (
            pl.when(self._expr.str.to_lowercase() == "central_bank")
            .then(pl.lit(weights["central_bank"]))
            .when(self._expr.str.to_lowercase() == "speculative")
            .then(pl.lit(weights["speculative"]))
            .when(self._expr.str.to_lowercase() == "listed")
            .then(pl.lit(weights["listed"]))
            .when(self._expr.str.to_lowercase() == "exchange_traded")
            .then(pl.lit(weights["exchange_traded"]))
            .when(self._expr.str.to_lowercase() == "government_supported")
            .then(pl.lit(weights["government_supported"]))
            .when(self._expr.str.to_lowercase() == "unlisted")
            .then(pl.lit(weights["unlisted"]))
            .when(self._expr.str.to_lowercase() == "private_equity")
            .then(pl.lit(weights["private_equity"]))
            .when(self._expr.str.to_lowercase() == "private_equity_diversified")
            .then(pl.lit(weights["private_equity_diversified"]))
            .when(self._expr.str.to_lowercase() == "ciu")
            .then(pl.lit(weights["ciu"]))
            .otherwise(pl.lit(weights["other"]))
        )
