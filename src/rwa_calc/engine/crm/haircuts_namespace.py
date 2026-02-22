"""
Polars LazyFrame namespaces for collateral haircut calculations.

Provides fluent API for haircut processing via registered namespaces:
- `lf.haircuts.classify_maturity_band()` - Classify collateral maturity bands
- `lf.haircuts.apply_collateral_haircuts(config)` - Apply supervisory haircuts
- `lf.haircuts.apply_fx_haircut(exposure_currency_col)` - Apply FX haircut
- `lf.haircuts.apply_maturity_mismatch(exposure_maturity_col)` - Apply maturity mismatch

Usage:
    import polars as pl
    from rwa_calc.contracts.config import CalculationConfig
    import rwa_calc.engine.crm.haircuts_namespace  # Register namespace

    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    result = (collateral
        .haircuts.classify_maturity_band()
        .haircuts.apply_collateral_haircuts(config)
        .haircuts.apply_fx_haircut("exposure_currency")
        .haircuts.calculate_adjusted_value()
    )

References:
- CRR Art. 224: Supervisory haircuts
- CRR Art. 238: Maturity mismatch adjustment
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.data.tables.crr_haircuts import FX_HAIRCUT

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# LAZYFRAME NAMESPACE
# =============================================================================


@pl.api.register_lazyframe_namespace("haircuts")
class HaircutsLazyFrame:
    """
    Haircut calculation namespace for Polars LazyFrames.

    Provides fluent API for collateral haircut calculations.

    Example:
        result = (collateral
            .haircuts.classify_maturity_band()
            .haircuts.apply_collateral_haircuts(config)
            .haircuts.apply_fx_haircut("exposure_currency")
            .haircuts.calculate_adjusted_value()
        )
    """

    def __init__(self, lf: pl.LazyFrame) -> None:
        self._lf = lf

    # =========================================================================
    # MATURITY CLASSIFICATION
    # =========================================================================

    def classify_maturity_band(self) -> pl.LazyFrame:
        """
        Classify collateral into maturity bands for haircut lookup.

        Bands:
        - 0_1y: residual maturity <= 1 year
        - 1_5y: 1 < residual maturity <= 5 years
        - 5y_plus: residual maturity > 5 years

        Returns:
            LazyFrame with maturity_band column added
        """
        return self._lf.with_columns([
            pl.when(pl.col("residual_maturity_years").is_null())
            .then(pl.lit("5y_plus"))
            .when(pl.col("residual_maturity_years") <= 1.0)
            .then(pl.lit("0_1y"))
            .when(pl.col("residual_maturity_years") <= 5.0)
            .then(pl.lit("1_5y"))
            .otherwise(pl.lit("5y_plus"))
            .alias("maturity_band"),
        ])

    # =========================================================================
    # HAIRCUT APPLICATION
    # =========================================================================

    def apply_collateral_haircuts(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply supervisory haircuts based on collateral type, CQS, and maturity.

        Haircuts per CRR Art. 224:
        - Cash: 0%
        - Gold: 15%
        - Government bonds: 0.5%-6% (CQS/maturity dependent)
        - Corporate bonds: 1%-8% (CQS/maturity dependent)
        - Equity (main index): 15%
        - Equity (other): 25%
        - Other physical: 40%

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with collateral_haircut column added
        """
        schema = self._lf.collect_schema()

        # Add maturity band if not present
        lf = self._lf
        if "maturity_band" not in schema.names():
            lf = lf.haircuts.classify_maturity_band()
            # Refresh schema after maturity band addition
            schema = lf.collect_schema()

        # Add is_eligible_financial_collateral if not present
        if "is_eligible_financial_collateral" not in schema.names():
            lf = lf.with_columns([pl.lit(False).alias("is_eligible_financial_collateral")])

        # Build issuer type check expression
        has_issuer_type = "issuer_type" in schema.names()

        # Create sovereign bond condition
        if has_issuer_type:
            is_sovereign_bond = (
                pl.col("collateral_type").str.to_lowercase().is_in([
                    "govt_bond", "sovereign_bond", "government_bond", "gilt"
                ]) |
                ((pl.col("collateral_type").str.to_lowercase() == "bond") &
                 (pl.col("issuer_type").str.to_lowercase() == "sovereign"))
            )
        else:
            is_sovereign_bond = pl.col("collateral_type").str.to_lowercase().is_in([
                "govt_bond", "sovereign_bond", "government_bond", "gilt"
            ])

        return lf.with_columns([
            # Cash - 0%
            pl.when(pl.col("collateral_type").str.to_lowercase().is_in(["cash", "deposit"]))
            .then(pl.lit(0.00))
            # Gold - 15%
            .when(pl.col("collateral_type").str.to_lowercase() == "gold")
            .then(pl.lit(0.15))

            # Government bonds CQS 1
            .when(is_sovereign_bond & (pl.col("issuer_cqs") == 1) & (pl.col("maturity_band") == "0_1y"))
            .then(pl.lit(0.005))
            .when(is_sovereign_bond & (pl.col("issuer_cqs") == 1) & (pl.col("maturity_band") == "1_5y"))
            .then(pl.lit(0.02))
            .when(is_sovereign_bond & (pl.col("issuer_cqs") == 1))
            .then(pl.lit(0.04))

            # Government bonds CQS 2-3
            .when(is_sovereign_bond & pl.col("issuer_cqs").is_in([2, 3]) & (pl.col("maturity_band") == "0_1y"))
            .then(pl.lit(0.01))
            .when(is_sovereign_bond & pl.col("issuer_cqs").is_in([2, 3]) & (pl.col("maturity_band") == "1_5y"))
            .then(pl.lit(0.03))
            .when(is_sovereign_bond & pl.col("issuer_cqs").is_in([2, 3]))
            .then(pl.lit(0.06))

            # Corporate bonds CQS 1-2
            .when(
                pl.col("collateral_type").str.to_lowercase().is_in(["corp_bond", "corporate_bond"]) &
                pl.col("issuer_cqs").is_in([1, 2]) & (pl.col("maturity_band") == "0_1y")
            ).then(pl.lit(0.01))
            .when(
                pl.col("collateral_type").str.to_lowercase().is_in(["corp_bond", "corporate_bond"]) &
                pl.col("issuer_cqs").is_in([1, 2]) & (pl.col("maturity_band") == "1_5y")
            ).then(pl.lit(0.04))
            .when(
                pl.col("collateral_type").str.to_lowercase().is_in(["corp_bond", "corporate_bond"]) &
                pl.col("issuer_cqs").is_in([1, 2])
            ).then(pl.lit(0.06))

            # Corporate bonds CQS 3
            .when(
                pl.col("collateral_type").str.to_lowercase().is_in(["corp_bond", "corporate_bond"]) &
                (pl.col("issuer_cqs") == 3) & (pl.col("maturity_band") == "0_1y")
            ).then(pl.lit(0.02))
            .when(
                pl.col("collateral_type").str.to_lowercase().is_in(["corp_bond", "corporate_bond"]) &
                (pl.col("issuer_cqs") == 3) & (pl.col("maturity_band") == "1_5y")
            ).then(pl.lit(0.06))
            .when(
                pl.col("collateral_type").str.to_lowercase().is_in(["corp_bond", "corporate_bond"]) &
                (pl.col("issuer_cqs") == 3)
            ).then(pl.lit(0.08))

            # Equity - main index 15%, other 25%
            .when(
                pl.col("collateral_type").str.to_lowercase().is_in(["equity", "shares", "stock"]) &
                pl.col("is_eligible_financial_collateral").fill_null(False)
            ).then(pl.lit(0.15))
            .when(pl.col("collateral_type").str.to_lowercase().is_in(["equity", "shares", "stock"]))
            .then(pl.lit(0.25))

            # Receivables - 20%
            .when(pl.col("collateral_type").str.to_lowercase().is_in(["receivables", "trade_receivables"]))
            .then(pl.lit(0.20))

            # Real estate - no haircut (LTV-based treatment)
            .when(pl.col("collateral_type").str.to_lowercase().is_in([
                "real_estate", "property", "rre", "cre",
                "residential_property", "commercial_property"
            ]))
            .then(pl.lit(0.00))

            # Other physical - 40%
            .otherwise(pl.lit(0.40))
            .alias("collateral_haircut"),
        ])

    def apply_fx_haircut(self, exposure_currency_col: str = "exposure_currency") -> pl.LazyFrame:
        """
        Apply FX haircut for currency mismatch.

        FX haircut = 8% when collateral and exposure currencies differ.

        Args:
            exposure_currency_col: Column name for exposure currency

        Returns:
            LazyFrame with fx_haircut column added
        """
        schema = self._lf.collect_schema()

        if exposure_currency_col not in schema.names():
            # No exposure currency to compare, no FX haircut
            return self._lf.with_columns([
                pl.lit(0.0).alias("fx_haircut"),
            ])

        return self._lf.with_columns([
            pl.when(pl.col("currency") != pl.col(exposure_currency_col))
            .then(pl.lit(float(FX_HAIRCUT)))
            .otherwise(pl.lit(0.0))
            .alias("fx_haircut"),
        ])

    def apply_maturity_mismatch(self, exposure_maturity_years: float = 5.0) -> pl.LazyFrame:
        """
        Apply maturity mismatch adjustment per CRR Art. 238.

        When collateral maturity < exposure maturity:
        - If < 3 months: no protection (factor = 0)
        - Otherwise: factor = (t - 0.25) / (T - 0.25)

        Args:
            exposure_maturity_years: Assumed exposure maturity (default 5 years)

        Returns:
            LazyFrame with maturity_adjustment_factor column
        """
        schema = self._lf.collect_schema()
        maturity_col = "residual_maturity_years" if "residual_maturity_years" in schema.names() else "coll_maturity"

        if maturity_col not in schema.names():
            # No maturity data, assume full protection
            return self._lf.with_columns([
                pl.lit(1.0).alias("maturity_adjustment_factor"),
            ])

        return self._lf.with_columns([
            # If collateral maturity >= exposure maturity, no adjustment
            pl.when(pl.col(maturity_col) >= exposure_maturity_years)
            .then(pl.lit(1.0))
            # If collateral < 3 months, no protection
            .when(pl.col(maturity_col) < 0.25)
            .then(pl.lit(0.0))
            # Apply adjustment: (t - 0.25) / (T - 0.25)
            .otherwise(
                (pl.col(maturity_col) - 0.25) / (exposure_maturity_years - 0.25)
            )
            .alias("maturity_adjustment_factor"),
        ])

    def calculate_adjusted_value(self) -> pl.LazyFrame:
        """
        Calculate adjusted collateral value after all haircuts.

        value_after_haircut = market_value × (1 - collateral_haircut - fx_haircut)
        value_after_maturity_adj = value_after_haircut × maturity_adjustment_factor

        Returns:
            LazyFrame with adjusted value columns
        """
        schema = self._lf.collect_schema()
        lf = self._lf

        # Ensure required columns exist with defaults
        if "collateral_haircut" not in schema.names():
            lf = lf.with_columns([pl.lit(0.0).alias("collateral_haircut")])
        if "fx_haircut" not in schema.names():
            lf = lf.with_columns([pl.lit(0.0).alias("fx_haircut")])
        if "maturity_adjustment_factor" not in schema.names():
            lf = lf.with_columns([pl.lit(1.0).alias("maturity_adjustment_factor")])

        return lf.with_columns([
            (
                pl.col("market_value") *
                (1.0 - pl.col("collateral_haircut") - pl.col("fx_haircut"))
            ).alias("value_after_haircut"),
        ]).with_columns([
            (
                pl.col("value_after_haircut") *
                pl.col("maturity_adjustment_factor")
            ).alias("value_after_maturity_adj"),
        ])

    # =========================================================================
    # CONVENIENCE / PIPELINE METHODS
    # =========================================================================

    def apply_all_haircuts(
        self,
        exposure_currency_col: str = "exposure_currency",
        exposure_maturity_years: float = 5.0,
        config: CalculationConfig | None = None,
    ) -> pl.LazyFrame:
        """
        Apply full haircut pipeline.

        Steps:
        1. Classify maturity band
        2. Apply collateral haircuts
        3. Apply FX haircut
        4. Apply maturity mismatch
        5. Calculate adjusted value

        Args:
            exposure_currency_col: Column name for exposure currency
            exposure_maturity_years: Assumed exposure maturity
            config: Calculation configuration (optional)

        Returns:
            LazyFrame with all haircuts applied
        """
        from rwa_calc.contracts.config import CalculationConfig
        from datetime import date

        if config is None:
            config = CalculationConfig.crr(reporting_date=date.today())

        return (self._lf
            .haircuts.classify_maturity_band()
            .haircuts.apply_collateral_haircuts(config)
            .haircuts.apply_fx_haircut(exposure_currency_col)
            .haircuts.apply_maturity_mismatch(exposure_maturity_years)
            .haircuts.calculate_adjusted_value()
        )

    def build_haircut_audit(self) -> pl.LazyFrame:
        """
        Build haircut calculation audit trail.

        Returns:
            LazyFrame with audit columns including haircut_calculation string
        """
        schema = self._lf.collect_schema()
        available_cols = schema.names()

        select_cols = ["collateral_reference"] if "collateral_reference" in available_cols else []
        optional_cols = [
            "collateral_type",
            "market_value",
            "collateral_haircut",
            "fx_haircut",
            "maturity_adjustment_factor",
            "value_after_haircut",
            "value_after_maturity_adj",
        ]

        for col in optional_cols:
            if col in available_cols:
                select_cols.append(col)

        if not select_cols:
            return self._lf

        audit = self._lf.select(select_cols)

        # Add calculation string
        if "value_after_haircut" in available_cols:
            audit = audit.with_columns([
                pl.concat_str([
                    pl.lit("MV="),
                    pl.col("market_value").round(0).cast(pl.String),
                    pl.lit("; Hc="),
                    (pl.col("collateral_haircut") * 100).round(1).cast(pl.String),
                    pl.lit("%; Hfx="),
                    (pl.col("fx_haircut") * 100).round(1).cast(pl.String) if "fx_haircut" in available_cols else pl.lit("0"),
                    pl.lit("%; Adj="),
                    pl.col("value_after_haircut").round(0).cast(pl.String),
                ]).alias("haircut_calculation"),
            ])

        return audit


# =============================================================================
# EXPRESSION NAMESPACE
# =============================================================================


@pl.api.register_expr_namespace("haircuts")
class HaircutsExpr:
    """
    Haircut calculation namespace for Polars Expressions.

    Provides column-level operations for haircut calculations.

    Example:
        df.with_columns(
            pl.col("market_value").haircuts.apply_haircut(0.15),
        )
    """

    def __init__(self, expr: pl.Expr) -> None:
        self._expr = expr

    def apply_haircut(self, haircut: float) -> pl.Expr:
        """
        Apply a haircut to the value.

        Args:
            haircut: Haircut percentage (e.g., 0.15 for 15%)

        Returns:
            Expression with haircut applied
        """
        return self._expr * (1.0 - haircut)

    def apply_fx_adjustment(self, fx_mismatch: pl.Expr, fx_rate: float = 0.08) -> pl.Expr:
        """
        Apply FX adjustment conditionally.

        Args:
            fx_mismatch: Boolean expression indicating currency mismatch
            fx_rate: FX haircut rate (default 8%)

        Returns:
            Expression with conditional FX adjustment
        """
        return pl.when(fx_mismatch).then(self._expr * (1.0 - fx_rate)).otherwise(self._expr)
