"""
Credit Conversion Factor (CCF) calculator for off-balance sheet items.

Calculates EAD for contingent exposures using regulatory CCFs:
- SA: CRR Article 111 (0%, 20%, 50%, 100%)
- F-IRB: CRR Article 166(8) (75% for undrawn commitments)
- F-IRB Exception: CRR Article 166(9) (20% for short-term trade LCs)

CCF is part of exposure measurement, not credit risk mitigation.
It converts nominal/notional amounts to credit-equivalent EAD.

Classes:
    CCFCalculator: Calculator for credit conversion factors

Usage:
    from rwa_calc.engine.ccf import CCFCalculator

    calculator = CCFCalculator()
    exposures_with_ead = calculator.apply_ccf(exposures, config)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.data.tables.crr_ccf import (
    get_ccf_table,
    get_firb_ccf_table,
)
from rwa_calc.domain.enums import ApproachType

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


class CCFCalculator:
    """
    Calculate credit conversion factors for off-balance sheet items.

    Implements CRR CCF rules:
    - SA (Art. 111): 0%, 20%, 50%, 100% by commitment type
    - F-IRB (Art. 166(8)): 75% for undrawn commitments (except 0% for cancellable)
    - F-IRB (Art. 166(9)): 20% for short-term trade LCs arising from goods movement

    The approach determines which CCF table to use:
    - SA exposures use standard CCFs (0%, 20%, 50%, 100%)
    - F-IRB exposures use 75% for most undrawn commitments
    - F-IRB short-term trade LCs retain 20% CCF (Art. 166(9) exception)
    - A-IRB exposures use own estimates (passed through as-is)
    """

    def __init__(self) -> None:
        """Initialize CCF calculator with lookup tables."""
        self._sa_ccf_table = get_ccf_table()
        self._firb_ccf_table = get_firb_ccf_table()

    def apply_ccf(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply CCF to calculate EAD for off-balance sheet exposures.

        CCF determination follows CRR Art. 111 categories based on risk_type:
        - SA: FR=100%, MR=50%, MLR=20%, LR=0%
        - F-IRB: FR=100%, MR/MLR=75% (CRR Art. 166(8)), LR=0%
        - F-IRB Exception: MLR with is_short_term_trade_lc=True retains 20% (Art. 166(9))
        - A-IRB: Uses ccf_modelled if provided, otherwise falls back to SA

        Args:
            exposures: Exposures with nominal_amount, risk_type, and approach columns
            config: Calculation configuration

        Returns:
            LazyFrame with ead_from_ccf and ccf columns added
        """
        # Check if risk_type column exists
        schema = exposures.collect_schema()
        has_risk_type = "risk_type" in schema.names()
        has_approach = "approach" in schema.names()
        has_ccf_modelled = "ccf_modelled" in schema.names()
        has_short_term_trade_lc = "is_short_term_trade_lc" in schema.names()

        # Calculate CCF from risk_type for SA approach
        # FR=100%, MR=50%, MLR=20%, LR=0%
        if has_risk_type:
            exposures = exposures.with_columns([
                pl.col("risk_type").fill_null("").str.to_lowercase().alias("_risk_type_normalized"),
            ])

            exposures = exposures.with_columns([
                pl.when(pl.col("_risk_type_normalized").is_in(["fr", "full_risk"]))
                .then(pl.lit(1.0))
                .when(pl.col("_risk_type_normalized").is_in(["mr", "medium_risk"]))
                .then(pl.lit(0.5))
                .when(pl.col("_risk_type_normalized").is_in(["mlr", "medium_low_risk"]))
                .then(pl.lit(0.2))
                .when(pl.col("_risk_type_normalized").is_in(["lr", "low_risk"]))
                .then(pl.lit(0.0))
                .otherwise(pl.lit(0.5))  # Default to MR (50%) for SA
                .alias("_sa_ccf_from_risk_type"),
            ])

            # Calculate CCF from risk_type for F-IRB approach
            # FR=100%, MR/MLR=75% (CRR Art. 166(8)), LR=0%
            # Exception: Short-term trade LCs retain 20% (CRR Art. 166(9))
            if has_short_term_trade_lc:
                exposures = exposures.with_columns([
                    pl.when(pl.col("_risk_type_normalized").is_in(["fr", "full_risk"]))
                    .then(pl.lit(1.0))
                    .when(pl.col("_risk_type_normalized").is_in(["lr", "low_risk"]))
                    .then(pl.lit(0.0))
                    # Art. 166(9) exception: short-term trade LCs for goods movement retain 20%
                    .when(
                        pl.col("_risk_type_normalized").is_in(["mlr", "medium_low_risk"])
                        & pl.col("is_short_term_trade_lc").fill_null(False)
                    )
                    .then(pl.lit(0.2))  # Art. 166(9) exception
                    .when(pl.col("_risk_type_normalized").is_in(["mr", "medium_risk", "mlr", "medium_low_risk"]))
                    .then(pl.lit(0.75))  # F-IRB 75% rule per CRR Art. 166(8)
                    .otherwise(pl.lit(0.75))  # Default to 75% for F-IRB
                    .alias("_firb_ccf_from_risk_type"),
                ])
            else:
                exposures = exposures.with_columns([
                    pl.when(pl.col("_risk_type_normalized").is_in(["fr", "full_risk"]))
                    .then(pl.lit(1.0))
                    .when(pl.col("_risk_type_normalized").is_in(["mr", "medium_risk", "mlr", "medium_low_risk"]))
                    .then(pl.lit(0.75))  # F-IRB 75% rule per CRR Art. 166(8)
                    .when(pl.col("_risk_type_normalized").is_in(["lr", "low_risk"]))
                    .then(pl.lit(0.0))
                    .otherwise(pl.lit(0.75))  # Default to 75% for F-IRB
                    .alias("_firb_ccf_from_risk_type"),
                ])
        else:
            # No risk_type column - use default CCFs
            exposures = exposures.with_columns([
                pl.lit(0.5).alias("_sa_ccf_from_risk_type"),   # Default to MR (50%) for SA
                pl.lit(0.75).alias("_firb_ccf_from_risk_type"),  # Default to 75% for F-IRB
            ])

        # Select final CCF based on approach
        if has_approach:
            if has_ccf_modelled:
                # Full logic with A-IRB ccf_modelled support
                exposures = exposures.with_columns([
                    pl.when(pl.col("nominal_amount") == 0)
                    .then(pl.lit(0.0))  # Loans with no contingent - no CCF
                    .when(pl.col("approach") == ApproachType.AIRB.value)
                    .then(
                        # A-IRB: use ccf_modelled if provided, else fall back to SA
                        pl.col("ccf_modelled").fill_null(pl.col("_sa_ccf_from_risk_type"))
                    )
                    .when(pl.col("approach") == ApproachType.FIRB.value)
                    .then(pl.col("_firb_ccf_from_risk_type"))  # F-IRB: 75% rule
                    .otherwise(pl.col("_sa_ccf_from_risk_type"))  # SA
                    .alias("ccf"),
                ])
            else:
                # No ccf_modelled column
                exposures = exposures.with_columns([
                    pl.when(pl.col("nominal_amount") == 0)
                    .then(pl.lit(0.0))  # Loans with no contingent - no CCF
                    .when(pl.col("approach") == ApproachType.FIRB.value)
                    .then(pl.col("_firb_ccf_from_risk_type"))  # F-IRB: 75% rule
                    .when(pl.col("approach") == ApproachType.AIRB.value)
                    .then(pl.col("_sa_ccf_from_risk_type"))  # A-IRB: use SA as fallback
                    .otherwise(pl.col("_sa_ccf_from_risk_type"))  # SA
                    .alias("ccf"),
                ])
        else:
            # Default to SA CCF when approach not specified
            exposures = exposures.with_columns([
                pl.when(pl.col("nominal_amount") == 0)
                .then(pl.lit(0.0))  # Loans with no contingent - no CCF
                .otherwise(pl.col("_sa_ccf_from_risk_type"))  # SA
                .alias("ccf"),
            ])

        # Calculate EAD from undrawn/nominal amount
        exposures = exposures.with_columns([
            # EAD from CCF = nominal_amount * CCF
            (pl.col("nominal_amount") * pl.col("ccf")).alias("ead_from_ccf"),
        ])

        # Calculate total EAD (drawn + CCF-adjusted undrawn)
        exposures = exposures.with_columns([
            (pl.col("drawn_amount") + pl.col("ead_from_ccf")).alias("ead_pre_crm"),
        ])

        # Add CCF audit trail
        if has_risk_type:
            exposures = exposures.with_columns([
                pl.concat_str([
                    pl.lit("CCF="),
                    (pl.col("ccf") * 100).round(0).cast(pl.String),
                    pl.lit("%; risk_type="),
                    pl.col("risk_type").fill_null("unknown"),
                    pl.lit("; nominal="),
                    pl.col("nominal_amount").round(0).cast(pl.String),
                    pl.lit("; ead_ccf="),
                    pl.col("ead_from_ccf").round(0).cast(pl.String),
                ]).alias("ccf_calculation"),
            ])
        else:
            exposures = exposures.with_columns([
                pl.concat_str([
                    pl.lit("CCF="),
                    (pl.col("ccf") * 100).round(0).cast(pl.String),
                    pl.lit("%; nominal="),
                    pl.col("nominal_amount").round(0).cast(pl.String),
                    pl.lit("; ead_ccf="),
                    pl.col("ead_from_ccf").round(0).cast(pl.String),
                ]).alias("ccf_calculation"),
            ])

        # Clean up temporary columns
        temp_columns = [
            "_risk_type_normalized",
            "_sa_ccf_from_risk_type",
            "_firb_ccf_from_risk_type",
        ]
        existing_temp_cols = [c for c in temp_columns if c in exposures.collect_schema().names()]
        if existing_temp_cols:
            exposures = exposures.drop(existing_temp_cols)

        return exposures


def create_ccf_calculator() -> CCFCalculator:
    """
    Create a CCF calculator instance.

    Returns:
        CCFCalculator ready for use
    """
    return CCFCalculator()
