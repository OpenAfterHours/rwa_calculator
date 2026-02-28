"""
Polars namespaces for audit trail generation.

Provides shared formatting utilities and audit trail builders:
- `expr.audit.format_currency(decimals)` - Format as currency
- `expr.audit.format_percent(decimals)` - Format as percentage
- `lf.audit.build_sa_calculation()` - Build SA audit string
- `lf.audit.build_irb_calculation()` - Build IRB audit string

Usage:
    import polars as pl
    import rwa_calc.engine.audit_namespace  # Register namespace

    result = df.with_columns(
        pl.col("ead").audit.format_currency().alias("ead_formatted"),
        pl.col("risk_weight").audit.format_percent().alias("rw_formatted"),
    )

Audit strings follow the pattern:
    {APPROACH}: {inputs} -> {output}

Examples:
- SA: EAD=100000 x RW=20.0% x SF=100.00% -> RWA=20000
- IRB: PD=1.50%, LGD=45.0%, R=18.25%, K=4.234%, MA=1.050 -> RWA=53000
- Slotting: Category=satisfactory (HVCRE), RW=100% -> RWA=50000
"""

from __future__ import annotations

import polars as pl

# =============================================================================
# EXPRESSION NAMESPACE
# =============================================================================


@pl.api.register_expr_namespace("audit")
class AuditExpr:
    """
    Audit formatting namespace for Polars Expressions.

    Provides column-level formatting for audit trails.

    Example:
        df.with_columns(
            pl.col("ead").audit.format_currency().alias("ead_formatted"),
        )
    """

    def __init__(self, expr: pl.Expr) -> None:
        self._expr = expr

    def format_currency(self, decimals: int = 0) -> pl.Expr:
        """
        Format value as currency (no symbol, with thousand separators conceptually).

        Args:
            decimals: Number of decimal places

        Returns:
            Expression formatted as string
        """
        return self._expr.round(decimals).cast(pl.String)

    def format_percent(self, decimals: int = 1) -> pl.Expr:
        """
        Format value as percentage.

        Args:
            decimals: Number of decimal places

        Returns:
            Expression formatted as percentage string (e.g., "20.0%")
        """
        return pl.concat_str(
            [
                (self._expr * 100).round(decimals).cast(pl.String),
                pl.lit("%"),
            ]
        )

    def format_ratio(self, decimals: int = 3) -> pl.Expr:
        """
        Format value as ratio/decimal.

        Args:
            decimals: Number of decimal places

        Returns:
            Expression formatted as string
        """
        return self._expr.round(decimals).cast(pl.String)

    def format_bps(self, decimals: int = 0) -> pl.Expr:
        """
        Format value as basis points.

        Args:
            decimals: Number of decimal places

        Returns:
            Expression formatted as basis points string (e.g., "150 bps")
        """
        return pl.concat_str(
            [
                (self._expr * 10000).round(decimals).cast(pl.String),
                pl.lit(" bps"),
            ]
        )


# =============================================================================
# LAZYFRAME NAMESPACE
# =============================================================================


@pl.api.register_lazyframe_namespace("audit")
class AuditLazyFrame:
    """
    Audit trail namespace for Polars LazyFrames.

    Provides methods to build standardized audit strings for different approaches.

    Example:
        result = exposures.audit.build_sa_calculation()
    """

    def __init__(self, lf: pl.LazyFrame) -> None:
        self._lf = lf

    def build_sa_calculation(self) -> pl.LazyFrame:
        """
        Build SA calculation audit trail.

        Format: SA: EAD={ead} x RW={rw}% x SF={sf}% -> RWA={rwa}

        Returns:
            LazyFrame with sa_calculation column
        """
        schema = self._lf.collect_schema()
        cols = schema.names()

        # Build calculation string based on available columns
        has_sf = "supporting_factor" in cols and "rwa_post_factor" in cols
        rwa_col = (
            "rwa_post_factor"
            if has_sf
            else ("rwa_pre_factor" if "rwa_pre_factor" in cols else "rwa")
        )
        ead_col = "ead_final" if "ead_final" in cols else "ead"

        if has_sf:
            return self._lf.with_columns(
                [
                    pl.concat_str(
                        [
                            pl.lit("SA: EAD="),
                            pl.col(ead_col).round(0).cast(pl.String),
                            pl.lit(" x RW="),
                            (pl.col("risk_weight") * 100).round(1).cast(pl.String),
                            pl.lit("% x SF="),
                            (pl.col("supporting_factor") * 100).round(2).cast(pl.String),
                            pl.lit("% -> RWA="),
                            pl.col(rwa_col).round(0).cast(pl.String),
                        ]
                    ).alias("sa_calculation"),
                ]
            )
        else:
            return self._lf.with_columns(
                [
                    pl.concat_str(
                        [
                            pl.lit("SA: EAD="),
                            pl.col(ead_col).round(0).cast(pl.String),
                            pl.lit(" x RW="),
                            (pl.col("risk_weight") * 100).round(1).cast(pl.String),
                            pl.lit("% -> RWA="),
                            pl.col(rwa_col).round(0).cast(pl.String),
                        ]
                    ).alias("sa_calculation"),
                ]
            )

    def build_irb_calculation(self) -> pl.LazyFrame:
        """
        Build IRB calculation audit trail.

        Format: IRB: PD={pd}%, LGD={lgd}%, R={corr}%, K={k}%, MA={ma} -> RWA={rwa}

        Returns:
            LazyFrame with irb_calculation column
        """
        schema = self._lf.collect_schema()
        cols = schema.names()

        pd_col = "pd_floored" if "pd_floored" in cols else "pd"
        lgd_col = "lgd_floored" if "lgd_floored" in cols else "lgd"
        rwa_col = "rwa"

        return self._lf.with_columns(
            [
                pl.concat_str(
                    [
                        pl.lit("IRB: PD="),
                        (pl.col(pd_col) * 100).round(2).cast(pl.String),
                        pl.lit("%, LGD="),
                        (pl.col(lgd_col) * 100).round(1).cast(pl.String),
                        pl.lit("%, R="),
                        (pl.col("correlation") * 100).round(2).cast(pl.String)
                        if "correlation" in cols
                        else pl.lit("N/A"),
                        pl.lit("%, K="),
                        (pl.col("k") * 100).round(3).cast(pl.String)
                        if "k" in cols
                        else pl.lit("N/A"),
                        pl.lit("%, MA="),
                        pl.col("maturity_adjustment").round(3).cast(pl.String)
                        if "maturity_adjustment" in cols
                        else pl.lit("1.000"),
                        pl.lit(" -> RWA="),
                        pl.col(rwa_col).round(0).cast(pl.String),
                    ]
                ).alias("irb_calculation"),
            ]
        )

    def build_slotting_calculation(self) -> pl.LazyFrame:
        """
        Build slotting calculation audit trail.

        Format: Slotting: Category={cat} (HVCRE?), RW={rw}% -> RWA={rwa}

        Returns:
            LazyFrame with slotting_calculation column
        """
        return self._lf.with_columns(
            [
                pl.concat_str(
                    [
                        pl.lit("Slotting: Category="),
                        pl.col("slotting_category"),
                        pl.when(pl.col("is_hvcre")).then(pl.lit(" (HVCRE)")).otherwise(pl.lit("")),
                        pl.lit(", RW="),
                        (pl.col("risk_weight") * 100).round(0).cast(pl.String),
                        pl.lit("% -> RWA="),
                        pl.col("rwa").round(0).cast(pl.String),
                    ]
                ).alias("slotting_calculation"),
            ]
        )

    def build_crm_calculation(self) -> pl.LazyFrame:
        """
        Build CRM/EAD waterfall audit trail.

        Format: EAD: gross={gross}; coll={coll}; guar={guar}; prov={prov}; final={final}

        Returns:
            LazyFrame with crm_calculation column
        """
        schema = self._lf.collect_schema()
        cols = schema.names()

        return self._lf.with_columns(
            [
                pl.concat_str(
                    [
                        pl.lit("EAD: gross="),
                        pl.col("ead_gross").round(0).cast(pl.String)
                        if "ead_gross" in cols
                        else pl.lit("N/A"),
                        pl.lit("; coll="),
                        pl.col("collateral_adjusted_value").round(0).cast(pl.String)
                        if "collateral_adjusted_value" in cols
                        else pl.lit("0"),
                        pl.lit("; guar="),
                        pl.col("guarantee_amount").round(0).cast(pl.String)
                        if "guarantee_amount" in cols
                        else pl.lit("0"),
                        pl.lit("; prov="),
                        pl.col("provision_allocated").round(0).cast(pl.String)
                        if "provision_allocated" in cols
                        else pl.lit("0"),
                        pl.lit("; final="),
                        pl.col("ead_final").round(0).cast(pl.String)
                        if "ead_final" in cols
                        else pl.lit("N/A"),
                    ]
                ).alias("crm_calculation"),
            ]
        )

    def build_haircut_calculation(self) -> pl.LazyFrame:
        """
        Build haircut audit trail.

        Format: MV={mv}; Hc={hc}%; Hfx={hfx}%; Adj={adj}

        Returns:
            LazyFrame with haircut_calculation column
        """
        schema = self._lf.collect_schema()
        cols = schema.names()

        return self._lf.with_columns(
            [
                pl.concat_str(
                    [
                        pl.lit("MV="),
                        pl.col("market_value").round(0).cast(pl.String)
                        if "market_value" in cols
                        else pl.lit("N/A"),
                        pl.lit("; Hc="),
                        (pl.col("collateral_haircut") * 100).round(1).cast(pl.String)
                        if "collateral_haircut" in cols
                        else pl.lit("0"),
                        pl.lit("%; Hfx="),
                        (pl.col("fx_haircut") * 100).round(1).cast(pl.String)
                        if "fx_haircut" in cols
                        else pl.lit("0"),
                        pl.lit("%; Adj="),
                        pl.col("value_after_haircut").round(0).cast(pl.String)
                        if "value_after_haircut" in cols
                        else pl.lit("N/A"),
                    ]
                ).alias("haircut_calculation"),
            ]
        )

    def build_floor_calculation(self) -> pl.LazyFrame:
        """
        Build output floor audit trail.

        Format: Floor: IRB RWA={irb}; Floor RWA={floor} ({pct}%); Final={final}; Binding={binding}

        Returns:
            LazyFrame with floor_calculation column
        """
        schema = self._lf.collect_schema()
        cols = schema.names()

        if "floor_rwa" not in cols:
            return self._lf

        return self._lf.with_columns(
            [
                pl.concat_str(
                    [
                        pl.lit("Floor: IRB RWA="),
                        pl.col("rwa_pre_floor").round(0).cast(pl.String),
                        pl.lit("; Floor RWA="),
                        pl.col("floor_rwa").round(0).cast(pl.String),
                        pl.lit(" ("),
                        (pl.col("output_floor_pct") * 100).round(1).cast(pl.String),
                        pl.lit("%); Final="),
                        pl.col("rwa_final").round(0).cast(pl.String),
                        pl.lit("; Binding="),
                        pl.col("is_floor_binding").cast(pl.String),
                    ]
                ).alias("floor_calculation"),
            ]
        )
