"""
Polars LazyFrame namespaces for Slotting calculations.

Provides fluent API for Specialised Lending slotting approach via registered namespaces:
- `lf.slotting.prepare_columns(config)` - Ensure required columns exist
- `lf.slotting.apply_slotting_weights(config)` - Apply slotting risk weights
- `lf.slotting.calculate_rwa()` - Calculate RWA

CRR weights vary by maturity (<2.5yr vs >=2.5yr) and HVCRE flag per Art. 153(5).
Basel 3.1 weights vary by HVCRE flag and PF pre-operational status per BCBS CRE33.

References:
- CRR Art. 153(5): Supervisory slotting approach (Tables 1 & 2)
- BCBS CRE33: Basel 3.1 specialised lending slotting
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from polars import col, lit

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# RISK WEIGHT CONSTANTS
# =============================================================================

# Categories: strong, good, satisfactory, weak, default
# Default weight for unknown categories is 'satisfactory'

SLOTTING_WEIGHTS = {
    # CRR Art. 153(5)
    "crr": {
        "base": {"strong": 0.70, "good": 0.90, "satisfactory": 1.15, "weak": 2.50, "default": 0.00},
        "short": {
            "strong": 0.50,
            "good": 0.70,
            "satisfactory": 1.15,
            "weak": 2.50,
            "default": 0.00,
        },
        "hvcre": {
            "strong": 0.95,
            "good": 1.20,
            "satisfactory": 1.40,
            "weak": 2.50,
            "default": 0.00,
        },
        "hvcre_short": {
            "strong": 0.70,
            "good": 0.95,
            "satisfactory": 1.40,
            "weak": 2.50,
            "default": 0.00,
        },
    },
    # Basel 3.1 BCBS CRE33
    "basel_3_1": {
        "base": {"strong": 0.70, "good": 0.90, "satisfactory": 1.15, "weak": 2.50, "default": 0.00},
        "preop": {
            "strong": 0.80,
            "good": 1.00,
            "satisfactory": 1.20,
            "weak": 3.50,
            "default": 0.00,
        },
        "hvcre": {
            "strong": 0.95,
            "good": 1.20,
            "satisfactory": 1.40,
            "weak": 2.50,
            "default": 0.00,
        },
    },
}


# =============================================================================
# LAZYFRAME NAMESPACE
# =============================================================================


@pl.api.register_lazyframe_namespace("slotting")
class SlottingLazyFrame:
    """
    Slotting calculation namespace for Polars LazyFrames.
    """

    def __init__(self, lf: pl.LazyFrame) -> None:
        self._lf = lf

    def prepare_columns(self) -> pl.LazyFrame:
        """Ensure all required columns exist with defaults."""
        schema = self._lf.collect_schema()

        # Define default columns to add if they don't exist
        defaults = {
            "slotting_category": lit("satisfactory"),
            "is_hvcre": lit(False),
            "sl_type": lit("project_finance"),
            "is_short_maturity": lit(False),
            "is_pre_operational": lit(False),
        }

        # Add EAD logic specifically
        to_add = []
        if "ead_final" not in schema:
            ead_col = (
                col("ead")
                if "ead" in schema
                else col("ead_pre_crm")
                if "ead_pre_crm" in schema
                else lit(0.0)
            )
            to_add.append(ead_col.alias("ead_final"))

        # Add missing default columns
        for name, expr in defaults.items():
            if name not in schema:
                to_add.append(expr.alias(name))

        return self._lf.with_columns(to_add) if to_add else self._lf

    def apply_slotting_weights(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply slotting risk weights based on framework, category, HVCRE flag, and maturity."""
        is_crr = config.is_crr

        if is_crr:
            rw_expr = col("slotting_category").slotting.lookup_rw(
                is_crr=True,
                is_hvcre=col("is_hvcre"),
                is_short=col("is_short_maturity"),
            )
        else:
            rw_expr = col("slotting_category").slotting.lookup_rw(
                is_crr=False,
                is_hvcre=col("is_hvcre"),
                is_preop=col("is_pre_operational"),
            )

        return self._lf.with_columns(risk_weight=rw_expr)

    def calculate_rwa(self) -> pl.LazyFrame:
        """Calculate RWA = EAD x Risk Weight."""
        rwa = col("ead_final") * col("risk_weight")
        return self._lf.with_columns(rwa=rwa, rwa_final=rwa)

    def apply_all(self, config: CalculationConfig) -> pl.LazyFrame:
        """Apply full slotting calculation pipeline."""
        return (
            self.prepare_columns().slotting.apply_slotting_weights(config).slotting.calculate_rwa()
        )

    def build_audit(self) -> pl.LazyFrame:
        """Build slotting calculation audit trail."""
        schema = self._lf.collect_schema()

        base_cols = ["exposure_reference"]
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

        select_cols = [c for c in base_cols + optional_cols if c in schema]
        audit = self._lf.select(select_cols)

        if "rwa" in schema:
            audit = audit.with_columns(
                slotting_calculation=pl.concat_str(
                    [
                        lit("Slotting: Category="),
                        col("slotting_category"),
                        pl.when(col("is_hvcre")).then(lit(" (HVCRE)")).otherwise(lit("")),
                        lit(", RW="),
                        (col("risk_weight") * 100).round(0).cast(pl.String),
                        lit("%, RWA="),
                        col("rwa").round(0).cast(pl.String),
                    ]
                )
            )

        return audit


# =============================================================================
# EXPRESSION NAMESPACE
# =============================================================================


@pl.api.register_expr_namespace("slotting")
class SlottingExpr:
    """
    Slotting calculation namespace for Polars Expressions.
    """

    def __init__(self, expr: pl.Expr) -> None:
        self._expr = expr

    def lookup_rw(
        self,
        is_crr: bool = True,
        is_hvcre: bool | pl.Expr = False,
        is_short: bool | pl.Expr = False,
        is_preop: bool | pl.Expr = False,
    ) -> pl.Expr:
        """Look up risk weight based on slotting category."""
        cat = self._expr.str.to_lowercase()

        is_hvcre_expr = lit(is_hvcre) if isinstance(is_hvcre, bool) else is_hvcre
        is_short_expr = lit(is_short) if isinstance(is_short, bool) else is_short
        is_preop_expr = lit(is_preop) if isinstance(is_preop, bool) else is_preop

        if is_crr:
            weights = SLOTTING_WEIGHTS["crr"]
            return (
                pl.when(is_hvcre_expr.not_() & is_short_expr.not_())
                .then(self._map_category(cat, weights["base"]))
                .when(is_hvcre_expr.not_() & is_short_expr)
                .then(self._map_category(cat, weights["short"]))
                .when(is_hvcre_expr & is_short_expr.not_())
                .then(self._map_category(cat, weights["hvcre"]))
                .otherwise(self._map_category(cat, weights["hvcre_short"]))
            )
        else:
            weights = SLOTTING_WEIGHTS["basel_3_1"]
            return (
                pl.when(is_hvcre_expr)
                .then(self._map_category(cat, weights["hvcre"]))
                .when(is_preop_expr)
                .then(self._map_category(cat, weights["preop"]))
                .otherwise(self._map_category(cat, weights["base"]))
            )

    @staticmethod
    def _map_category(cat_expr: pl.Expr, weights: dict[str, float]) -> pl.Expr:
        """Map category name to risk weight using replace_strict."""
        return cat_expr.replace_strict(
            old=list(weights.keys()),
            new=list(weights.values()),
            default=lit(weights["satisfactory"]),
            return_dtype=pl.Float64,
        )
