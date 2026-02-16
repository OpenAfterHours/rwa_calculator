"""
Polars LazyFrame namespaces for Slotting calculations.

Provides fluent API for Specialised Lending slotting approach via registered namespaces:
- `lf.slotting.prepare_columns(config)` - Ensure required columns exist
- `lf.slotting.apply_slotting_weights(config)` - Apply slotting risk weights
- `lf.slotting.calculate_rwa()` - Calculate RWA

CRR weights vary by maturity (<2.5yr vs >=2.5yr) and HVCRE flag per Art. 153(5).
Basel 3.1 weights vary by HVCRE flag and PF pre-operational status per BCBS CRE33.

Usage:
    import polars as pl
    from rwa_calc.contracts.config import CalculationConfig
    import rwa_calc.engine.slotting.namespace  # Register namespace

    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    result = (exposures
        .slotting.prepare_columns(config)
        .slotting.apply_slotting_weights(config)
        .slotting.calculate_rwa()
    )

References:
- CRR Art. 153(5): Supervisory slotting approach (Tables 1 & 2)
- BCBS CRE33: Basel 3.1 specialised lending slotting
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# CRR SLOTTING RISK WEIGHTS (Art. 153(5))
# =============================================================================

# CRR Non-HVCRE (Table 1) — remaining maturity >= 2.5 years
CRR_SLOTTING_WEIGHTS = {
    "strong": 0.70,
    "good": 0.90,
    "satisfactory": 1.15,
    "weak": 2.50,
    "default": 0.00,
}

# CRR Non-HVCRE (Table 1) — remaining maturity < 2.5 years
CRR_SLOTTING_WEIGHTS_SHORT = {
    "strong": 0.50,
    "good": 0.70,
    "satisfactory": 1.15,
    "weak": 2.50,
    "default": 0.00,
}

# CRR HVCRE (Table 2) — remaining maturity >= 2.5 years
CRR_SLOTTING_WEIGHTS_HVCRE = {
    "strong": 0.95,
    "good": 1.20,
    "satisfactory": 1.40,
    "weak": 2.50,
    "default": 0.00,
}

# CRR HVCRE (Table 2) — remaining maturity < 2.5 years
CRR_SLOTTING_WEIGHTS_HVCRE_SHORT = {
    "strong": 0.70,
    "good": 0.95,
    "satisfactory": 1.40,
    "weak": 2.50,
    "default": 0.00,
}

# =============================================================================
# BASEL 3.1 SLOTTING RISK WEIGHTS (BCBS CRE33)
# =============================================================================

# Basel 3.1 non-HVCRE operational (OF, CF, IPRE, PF operational)
BASEL31_SLOTTING_WEIGHTS = {
    "strong": 0.70,
    "good": 0.90,
    "satisfactory": 1.15,
    "weak": 2.50,
    "default": 0.00,
}

# Basel 3.1 Project Finance pre-operational
BASEL31_SLOTTING_WEIGHTS_PF_PREOP = {
    "strong": 0.80,
    "good": 1.00,
    "satisfactory": 1.20,
    "weak": 3.50,
    "default": 0.00,
}

# Basel 3.1 HVCRE
BASEL31_SLOTTING_WEIGHTS_HVCRE = {
    "strong": 0.95,
    "good": 1.20,
    "satisfactory": 1.40,
    "weak": 2.50,
    "default": 0.00,
}


# =============================================================================
# LAZYFRAME NAMESPACE
# =============================================================================


@pl.api.register_lazyframe_namespace("slotting")
class SlottingLazyFrame:
    """
    Slotting calculation namespace for Polars LazyFrames.

    Provides fluent API for Specialised Lending slotting approach.

    Example:
        result = (exposures
            .slotting.prepare_columns(config)
            .slotting.apply_slotting_weights(config)
            .slotting.calculate_rwa()
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
        - ead_final: Exposure at default
        - slotting_category: Slotting category
        - is_hvcre: HVCRE flag
        - sl_type: Specialised lending type
        - is_short_maturity: Maturity < 2.5yr flag (CRR only)
        - is_pre_operational: PF pre-operational flag (Basel 3.1 only)

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with all required columns
        """
        schema = self._lf.collect_schema()
        lf = self._lf

        # EAD
        if "ead_final" not in schema.names():
            if "ead" in schema.names():
                lf = lf.with_columns([pl.col("ead").alias("ead_final")])
            elif "ead_pre_crm" in schema.names():
                lf = lf.with_columns([pl.col("ead_pre_crm").alias("ead_final")])
            else:
                lf = lf.with_columns([pl.lit(0.0).alias("ead_final")])

        # Refresh schema
        schema = lf.collect_schema()

        # Slotting category
        if "slotting_category" not in schema.names():
            lf = lf.with_columns([pl.lit("satisfactory").alias("slotting_category")])

        # HVCRE flag
        if "is_hvcre" not in schema.names():
            lf = lf.with_columns([pl.lit(False).alias("is_hvcre")])

        # Specialised lending type
        if "sl_type" not in schema.names():
            lf = lf.with_columns([pl.lit("project_finance").alias("sl_type")])

        # CRR maturity flag (default >= 2.5yr = more conservative)
        if "is_short_maturity" not in schema.names():
            lf = lf.with_columns([pl.lit(False).alias("is_short_maturity")])

        # Basel 3.1 pre-operational flag (default operational)
        if "is_pre_operational" not in schema.names():
            lf = lf.with_columns([pl.lit(False).alias("is_pre_operational")])

        return lf

    # =========================================================================
    # RISK WEIGHT APPLICATION
    # =========================================================================

    def apply_slotting_weights(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply slotting risk weights based on category, HVCRE flag, and maturity.

        CRR: Maturity-based split (<2.5yr / >=2.5yr) with separate HVCRE table.
        Basel 3.1: HVCRE differentiated, PF pre-operational differentiated.

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with risk_weight column added
        """
        if config.is_crr:
            return self._apply_crr_weights()
        else:
            return self._apply_basel31_weights()

    def _apply_crr_weights(self) -> pl.LazyFrame:
        """
        Apply CRR slotting weights with maturity and HVCRE differentiation.

        CRR Art. 153(5):
        - Table 1 (non-HVCRE): >=2.5yr and <2.5yr maturity splits
        - Table 2 (HVCRE): >=2.5yr and <2.5yr maturity splits
        """
        cat = pl.col("slotting_category").str.to_lowercase()
        is_hvcre = pl.col("is_hvcre")
        is_short = pl.col("is_short_maturity")

        return self._lf.with_columns([
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

            # Default to non-HVCRE >=2.5yr satisfactory
            .otherwise(pl.lit(CRR_SLOTTING_WEIGHTS["satisfactory"]))
            .alias("risk_weight"),
        ])

    def _apply_basel31_weights(self) -> pl.LazyFrame:
        """
        Apply Basel 3.1 slotting weights (BCBS CRE33).

        Three weight tables:
        - Non-HVCRE operational (OF, CF, IPRE, PF operational): 70/90/115/250/0
        - PF pre-operational: 80/100/120/350/0
        - HVCRE: 95/120/140/250/0
        """
        cat = pl.col("slotting_category").str.to_lowercase()
        is_hvcre = pl.col("is_hvcre")
        is_preop = pl.col("is_pre_operational")

        return self._lf.with_columns([
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

            # Default to non-HVCRE operational satisfactory
            .otherwise(pl.lit(BASEL31_SLOTTING_WEIGHTS["satisfactory"]))
            .alias("risk_weight"),
        ])

    # =========================================================================
    # RWA CALCULATION
    # =========================================================================

    def calculate_rwa(self) -> pl.LazyFrame:
        """
        Calculate RWA = EAD x Risk Weight.

        Returns:
            LazyFrame with rwa and rwa_final columns
        """
        return self._lf.with_columns([
            (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa"),
            (pl.col("ead_final") * pl.col("risk_weight")).alias("rwa_final"),
        ])

    # =========================================================================
    # CONVENIENCE / PIPELINE METHODS
    # =========================================================================

    def apply_all(self, config: CalculationConfig) -> pl.LazyFrame:
        """
        Apply full slotting calculation pipeline.

        Steps:
        1. Prepare columns
        2. Apply slotting weights
        3. Calculate RWA

        Args:
            config: Calculation configuration

        Returns:
            LazyFrame with all slotting calculations
        """
        return (self._lf
            .slotting.prepare_columns(config)
            .slotting.apply_slotting_weights(config)
            .slotting.calculate_rwa()
        )

    def build_audit(self) -> pl.LazyFrame:
        """
        Build slotting calculation audit trail.

        Returns:
            LazyFrame with audit columns including slotting_calculation string
        """
        schema = self._lf.collect_schema()
        available_cols = schema.names()

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

        audit = self._lf.select(select_cols)

        # Add calculation string
        if "rwa" in available_cols:
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


# =============================================================================
# EXPRESSION NAMESPACE
# =============================================================================


@pl.api.register_expr_namespace("slotting")
class SlottingExpr:
    """
    Slotting calculation namespace for Polars Expressions.

    Provides column-level operations for slotting calculations.

    Example:
        df.with_columns(
            pl.col("slotting_category").slotting.lookup_rw(is_crr=True),
        )
    """

    def __init__(self, expr: pl.Expr) -> None:
        self._expr = expr

    def lookup_rw(self, is_crr: bool = True, is_hvcre: bool = False) -> pl.Expr:
        """
        Look up risk weight based on slotting category.

        For CRR, uses >= 2.5yr weights (conservative default).
        For Basel 3.1, uses operational weights (non-PF pre-op).

        Args:
            is_crr: Whether to use CRR weights (vs Basel 3.1)
            is_hvcre: Whether to use HVCRE weights

        Returns:
            Expression with risk weight
        """
        if is_crr:
            weights = CRR_SLOTTING_WEIGHTS_HVCRE if is_hvcre else CRR_SLOTTING_WEIGHTS
        elif is_hvcre:
            weights = BASEL31_SLOTTING_WEIGHTS_HVCRE
        else:
            weights = BASEL31_SLOTTING_WEIGHTS

        return (
            pl.when(self._expr.str.to_lowercase() == "strong")
            .then(pl.lit(weights["strong"]))
            .when(self._expr.str.to_lowercase() == "good")
            .then(pl.lit(weights["good"]))
            .when(self._expr.str.to_lowercase() == "satisfactory")
            .then(pl.lit(weights["satisfactory"]))
            .when(self._expr.str.to_lowercase() == "weak")
            .then(pl.lit(weights["weak"]))
            .when(self._expr.str.to_lowercase() == "default")
            .then(pl.lit(weights["default"]))
            .otherwise(pl.lit(weights["satisfactory"]))
        )
