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

from rwa_calc.domain.enums import ApproachType

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


def drawn_for_ead() -> pl.Expr:
    """Drawn amount floored at 0 for EAD calculations.

    Negative drawn (credit balances) should not reduce EAD without a netting agreement.
    """
    return pl.col("drawn_amount").clip(lower_bound=0.0)


def on_balance_ead() -> pl.Expr:
    """On-balance-sheet EAD: max(0, drawn) + accrued interest.

    Combines the floored drawn amount with accrued interest for a single
    reusable expression. Interest is fill_null(0) so this works even when
    the interest column contains nulls.
    """
    return pl.col("drawn_amount").clip(lower_bound=0.0) + pl.col("interest").fill_null(0.0)


def sa_ccf_expression(
    risk_type_col: str = "risk_type",
    is_basel_3_1: bool = False,
) -> pl.Expr:
    """
    Return a Polars expression that maps risk_type to SA CCFs.

    CRR (Art. 111):
    - FR / full_risk: 100%
    - MR / medium_risk: 50%
    - MLR / medium_low_risk: 20%
    - LR / low_risk: 0%

    Basel 3.1 (CRE20.88): LR (unconditionally cancellable) changes to 10%.

    Args:
        risk_type_col: Name of the risk_type column (default "risk_type")
        is_basel_3_1: Whether to apply Basel 3.1 CCF values

    Returns:
        Polars expression resolving to Float64 SA CCF values
    """
    normalized = pl.col(risk_type_col).fill_null("").str.to_lowercase()
    # Basel 3.1: UCC/LR gets 10% instead of 0% (CRE20.88)
    lr_ccf = 0.10 if is_basel_3_1 else 0.0
    return (
        pl.when(normalized.is_in(["fr", "full_risk"]))
        .then(pl.lit(1.0))
        .when(normalized.is_in(["mr", "medium_risk"]))
        .then(pl.lit(0.5))
        .when(normalized.is_in(["mlr", "medium_low_risk"]))
        .then(pl.lit(0.2))
        .when(normalized.is_in(["lr", "low_risk"]))
        .then(pl.lit(lr_ccf))
        .otherwise(pl.lit(0.5))  # Default to MR (50%) for SA
    )


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
        """Initialize CCF calculator."""
        pass

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
        # Check if columns exist
        schema = exposures.collect_schema()
        has_risk_type = "risk_type" in schema.names()
        has_approach = "approach" in schema.names()
        has_ccf_modelled = "ccf_modelled" in schema.names()
        has_short_term_trade_lc = "is_short_term_trade_lc" in schema.names()
        has_interest = "interest" in schema.names()

        is_b31 = config.is_basel_3_1

        # Calculate CCF from risk_type for SA approach
        # FR=100%, MR=50%, MLR=20%, LR=0% (CRR) or 10% (Basel 3.1)
        if has_risk_type:
            exposures = exposures.with_columns(
                [
                    pl.col("risk_type")
                    .fill_null("")
                    .str.to_lowercase()
                    .alias("_risk_type_normalized"),
                    sa_ccf_expression(is_basel_3_1=is_b31).alias("_sa_ccf_from_risk_type"),
                ]
            )

            # Calculate CCF from risk_type for F-IRB approach
            # FR=100%, MR/MLR=75% (CRR Art. 166(8)), LR=0% (CRR) or 10% (Basel 3.1)
            # Exception: Short-term trade LCs retain 20% (CRR Art. 166(9))
            firb_lr_ccf = 0.10 if is_b31 else 0.0
            if has_short_term_trade_lc:
                exposures = exposures.with_columns(
                    [
                        pl.when(pl.col("_risk_type_normalized").is_in(["fr", "full_risk"]))
                        .then(pl.lit(1.0))
                        .when(pl.col("_risk_type_normalized").is_in(["lr", "low_risk"]))
                        .then(pl.lit(firb_lr_ccf))
                        # Art. 166(9) exception: short-term trade LCs for goods movement retain 20%
                        .when(
                            pl.col("_risk_type_normalized").is_in(["mlr", "medium_low_risk"])
                            & pl.col("is_short_term_trade_lc").fill_null(False)
                        )
                        .then(pl.lit(0.2))  # Art. 166(9) exception
                        .when(
                            pl.col("_risk_type_normalized").is_in(
                                ["mr", "medium_risk", "mlr", "medium_low_risk"]
                            )
                        )
                        .then(pl.lit(0.75))  # F-IRB 75% rule per CRR Art. 166(8)
                        .otherwise(pl.lit(0.75))  # Default to 75% for F-IRB
                        .alias("_firb_ccf_from_risk_type"),
                    ]
                )
            else:
                exposures = exposures.with_columns(
                    [
                        pl.when(pl.col("_risk_type_normalized").is_in(["fr", "full_risk"]))
                        .then(pl.lit(1.0))
                        .when(
                            pl.col("_risk_type_normalized").is_in(
                                ["mr", "medium_risk", "mlr", "medium_low_risk"]
                            )
                        )
                        .then(pl.lit(0.75))  # F-IRB 75% rule per CRR Art. 166(8)
                        .when(pl.col("_risk_type_normalized").is_in(["lr", "low_risk"]))
                        .then(pl.lit(firb_lr_ccf))
                        .otherwise(pl.lit(0.75))  # Default to 75% for F-IRB
                        .alias("_firb_ccf_from_risk_type"),
                    ]
                )
        else:
            # No risk_type column - use default CCFs
            exposures = exposures.with_columns(
                [
                    pl.lit(0.5).alias("_sa_ccf_from_risk_type"),  # Default to MR (50%) for SA
                    pl.lit(0.75).alias("_firb_ccf_from_risk_type"),  # Default to 75% for F-IRB
                ]
            )

        # Select final CCF based on approach
        if has_approach:
            if has_ccf_modelled:
                # Cast ccf_modelled to Float64 in case it's stored as String
                ccf_modelled_expr = pl.col("ccf_modelled").cast(pl.Float64, strict=False)

                # A-IRB CCF with Basel 3.1 floor enforcement (CRE32.27):
                # modelled CCF must be at least 50% of the SA CCF
                if is_b31:
                    airb_ccf_expr = pl.max_horizontal(
                        ccf_modelled_expr.fill_null(pl.col("_sa_ccf_from_risk_type")),
                        pl.col("_sa_ccf_from_risk_type") * 0.5,
                    )
                else:
                    airb_ccf_expr = ccf_modelled_expr.fill_null(pl.col("_sa_ccf_from_risk_type"))

                # Full logic with A-IRB ccf_modelled support
                exposures = exposures.with_columns(
                    [
                        pl.when(pl.col("nominal_amount") == 0)
                        .then(pl.lit(0.0))  # Loans with no contingent - no CCF
                        .when(pl.col("approach") == ApproachType.AIRB.value)
                        .then(airb_ccf_expr)
                        .when(pl.col("approach") == ApproachType.FIRB.value)
                        .then(pl.col("_firb_ccf_from_risk_type"))  # F-IRB: 75% rule
                        .otherwise(pl.col("_sa_ccf_from_risk_type"))  # SA
                        .alias("ccf"),
                    ]
                )
            else:
                # No ccf_modelled column
                exposures = exposures.with_columns(
                    [
                        pl.when(pl.col("nominal_amount") == 0)
                        .then(pl.lit(0.0))  # Loans with no contingent - no CCF
                        .when(pl.col("approach") == ApproachType.FIRB.value)
                        .then(pl.col("_firb_ccf_from_risk_type"))  # F-IRB: 75% rule
                        .when(pl.col("approach") == ApproachType.AIRB.value)
                        .then(pl.col("_sa_ccf_from_risk_type"))  # A-IRB: use SA as fallback
                        .otherwise(pl.col("_sa_ccf_from_risk_type"))  # SA
                        .alias("ccf"),
                    ]
                )
        else:
            # Default to SA CCF when approach not specified
            exposures = exposures.with_columns(
                [
                    pl.when(pl.col("nominal_amount") == 0)
                    .then(pl.lit(0.0))  # Loans with no contingent - no CCF
                    .otherwise(pl.col("_sa_ccf_from_risk_type"))  # SA
                    .alias("ccf"),
                ]
            )

        # Calculate EAD from undrawn/nominal amount
        # When provision columns are present, use nominal_after_provision
        # to implement CRR Art. 111(2): SCRA deducted before CCF
        has_provision_cols = (
            "nominal_after_provision" in schema.names() and "provision_on_drawn" in schema.names()
        )

        if has_provision_cols:
            nominal_for_ccf = pl.col("nominal_after_provision")
        else:
            nominal_for_ccf = pl.col("nominal_amount")

        exposures = exposures.with_columns(
            [
                (nominal_for_ccf * pl.col("ccf")).alias("ead_from_ccf"),
            ]
        )

        # Calculate total EAD (drawn + interest + CCF-adjusted undrawn)
        # When provision columns exist, subtract provision_on_drawn from the
        # on-balance-sheet component (interest is never reduced by provision)
        if has_provision_cols and has_interest:
            on_bal = (drawn_for_ead() - pl.col("provision_on_drawn")).clip(
                lower_bound=0.0
            ) + pl.col("interest").fill_null(0.0)
            exposures = exposures.with_columns(
                [
                    (on_bal + pl.col("ead_from_ccf")).alias("ead_pre_crm"),
                ]
            )
        elif has_provision_cols:
            on_bal = (drawn_for_ead() - pl.col("provision_on_drawn")).clip(lower_bound=0.0)
            exposures = exposures.with_columns(
                [
                    (on_bal + pl.col("ead_from_ccf")).alias("ead_pre_crm"),
                ]
            )
        elif has_interest:
            exposures = exposures.with_columns(
                [
                    (on_balance_ead() + pl.col("ead_from_ccf")).alias("ead_pre_crm"),
                ]
            )
        else:
            # Legacy: no interest column, EAD = drawn + CCF-adjusted undrawn
            exposures = exposures.with_columns(
                [
                    (drawn_for_ead() + pl.col("ead_from_ccf")).alias("ead_pre_crm"),
                ]
            )

        # Add CCF audit trail
        if has_risk_type and has_interest:
            exposures = exposures.with_columns(
                [
                    pl.concat_str(
                        [
                            pl.lit("CCF="),
                            (pl.col("ccf") * 100).round(0).cast(pl.String),
                            pl.lit("%; risk_type="),
                            pl.col("risk_type").fill_null("unknown"),
                            pl.lit("; drawn="),
                            pl.col("drawn_amount").round(0).cast(pl.String),
                            pl.lit("; interest="),
                            pl.col("interest").fill_null(0.0).round(0).cast(pl.String),
                            pl.lit("; nominal="),
                            pl.col("nominal_amount").round(0).cast(pl.String),
                            pl.lit("; ead_ccf="),
                            pl.col("ead_from_ccf").round(0).cast(pl.String),
                        ]
                    ).alias("ccf_calculation"),
                ]
            )
        elif has_risk_type:
            exposures = exposures.with_columns(
                [
                    pl.concat_str(
                        [
                            pl.lit("CCF="),
                            (pl.col("ccf") * 100).round(0).cast(pl.String),
                            pl.lit("%; risk_type="),
                            pl.col("risk_type").fill_null("unknown"),
                            pl.lit("; nominal="),
                            pl.col("nominal_amount").round(0).cast(pl.String),
                            pl.lit("; ead_ccf="),
                            pl.col("ead_from_ccf").round(0).cast(pl.String),
                        ]
                    ).alias("ccf_calculation"),
                ]
            )
        elif has_interest:
            exposures = exposures.with_columns(
                [
                    pl.concat_str(
                        [
                            pl.lit("CCF="),
                            (pl.col("ccf") * 100).round(0).cast(pl.String),
                            pl.lit("%; drawn="),
                            pl.col("drawn_amount").round(0).cast(pl.String),
                            pl.lit("; interest="),
                            pl.col("interest").fill_null(0.0).round(0).cast(pl.String),
                            pl.lit("; nominal="),
                            pl.col("nominal_amount").round(0).cast(pl.String),
                            pl.lit("; ead_ccf="),
                            pl.col("ead_from_ccf").round(0).cast(pl.String),
                        ]
                    ).alias("ccf_calculation"),
                ]
            )
        else:
            exposures = exposures.with_columns(
                [
                    pl.concat_str(
                        [
                            pl.lit("CCF="),
                            (pl.col("ccf") * 100).round(0).cast(pl.String),
                            pl.lit("%; nominal="),
                            pl.col("nominal_amount").round(0).cast(pl.String),
                            pl.lit("; ead_ccf="),
                            pl.col("ead_from_ccf").round(0).cast(pl.String),
                        ]
                    ).alias("ccf_calculation"),
                ]
            )

        # Clean up temporary columns
        temp_columns = ["_sa_ccf_from_risk_type", "_firb_ccf_from_risk_type"]
        if has_risk_type:
            temp_columns.append("_risk_type_normalized")
        exposures = exposures.drop(temp_columns)

        return exposures


def create_ccf_calculator() -> CCFCalculator:
    """
    Create a CCF calculator instance.

    Returns:
        CCFCalculator ready for use
    """
    return CCFCalculator()
