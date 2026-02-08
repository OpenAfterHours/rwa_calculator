"""
Polars LazyFrame namespaces for Credit Risk Mitigation (CRM) calculations.

Provides fluent API for CRM processing via registered namespaces:
- `lf.crm.initialize_ead_waterfall()` - Initialize EAD tracking columns
- `lf.crm.apply_collateral(collateral, config)` - Apply collateral effects
- `lf.crm.apply_guarantees(guarantees, config)` - Apply guarantee substitution
- `lf.crm.apply_provisions(provisions, config)` - Apply provision deduction
- `lf.crm.finalize_ead()` - Calculate final EAD

Usage:
    import polars as pl
    from rwa_calc.contracts.config import CalculationConfig
    import rwa_calc.engine.crm.namespace  # Register namespace

    config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
    result = (exposures
        .crm.initialize_ead_waterfall()
        .crm.apply_collateral(collateral, config)
        .crm.apply_guarantees(guarantees, counterparty_lookup, config)
        .crm.apply_provisions(provisions, config)
        .crm.finalize_ead()
    )

References:
- CRR Art. 110: Provision deduction
- CRR Art. 111: CCF application (off-balance sheet)
- CRR Art. 213-217: Guarantee substitution
- CRR Art. 223-224: Collateral haircuts
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.ccf import sa_ccf_expression
from rwa_calc.engine.classifier import ENTITY_TYPE_TO_SA_CLASS

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# LAZYFRAME NAMESPACE
# =============================================================================


@pl.api.register_lazyframe_namespace("crm")
class CRMLazyFrame:
    """
    CRM calculation namespace for Polars LazyFrames.

    Provides fluent API for Credit Risk Mitigation processing.

    Example:
        result = (exposures
            .crm.initialize_ead_waterfall()
            .crm.apply_collateral(collateral, config)
            .crm.apply_guarantees(guarantees, counterparty_lookup, config)
            .crm.apply_provisions(provisions, config)
            .crm.finalize_ead()
        )
    """

    def __init__(self, lf: pl.LazyFrame) -> None:
        self._lf = lf

    # =========================================================================
    # EAD WATERFALL INITIALIZATION
    # =========================================================================

    def initialize_ead_waterfall(self) -> pl.LazyFrame:
        """
        Initialize EAD tracking columns for CRM waterfall.

        Sets up the EAD waterfall:
        - ead_gross: Starting EAD (drawn + CCF-adjusted undrawn)
        - ead_after_collateral: EAD after collateral
        - ead_after_guarantee: EAD after guarantee substitution
        - ead_final: Final EAD after provision deduction

        Returns:
            LazyFrame with EAD waterfall columns initialized
        """
        schema = self._lf.collect_schema()
        lf = self._lf

        # Determine base EAD column
        if "ead_pre_crm" in schema.names():
            base_ead_col = "ead_pre_crm"
        elif "ead" in schema.names():
            base_ead_col = "ead"
        elif "drawn_amount" in schema.names():
            base_ead_col = "drawn_amount"
        else:
            # No EAD column found, create placeholder
            lf = lf.with_columns([pl.lit(0.0).alias("ead_pre_crm")])
            base_ead_col = "ead_pre_crm"

        return lf.with_columns([
            # Gross EAD = drawn + CCF-adjusted contingent
            pl.col(base_ead_col).alias("ead_gross"),

            # Initialize subsequent EAD columns
            pl.col(base_ead_col).alias("ead_after_collateral"),
            pl.col(base_ead_col).alias("ead_after_guarantee"),
            pl.col(base_ead_col).alias("ead_final"),

            # Initialize collateral-related columns
            pl.lit(0.0).alias("collateral_allocated"),
            pl.lit(0.0).alias("collateral_adjusted_value"),

            # Initialize guarantee-related columns
            pl.lit(0.0).alias("guarantee_amount"),
            pl.lit(None).cast(pl.String).alias("guarantor_reference"),
            pl.lit(None).cast(pl.Float64).alias("substitute_rw"),

            # Initialize provision-related columns
            pl.lit(0.0).alias("provision_allocated"),
            pl.lit(0.0).alias("provision_deducted"),

            # LGD for IRB (may be adjusted by collateral)
            pl.col("lgd").fill_null(0.45).alias("lgd_pre_crm") if "lgd" in schema.names() else pl.lit(0.45).alias("lgd_pre_crm"),
            pl.col("lgd").fill_null(0.45).alias("lgd_post_crm") if "lgd" in schema.names() else pl.lit(0.45).alias("lgd_post_crm"),
        ])

    # =========================================================================
    # COLLATERAL APPLICATION
    # =========================================================================

    def apply_collateral(
        self,
        collateral: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply collateral to reduce EAD (SA) or LGD (IRB).

        For SA exposures: Collateral reduces EAD directly.
        For IRB exposures: Collateral affects LGD but not EAD.

        Args:
            collateral: Collateral data with adjusted values
            config: Calculation configuration

        Returns:
            LazyFrame with collateral effects applied
        """
        schema = self._lf.collect_schema()

        # Get collateral value column
        collateral_schema = collateral.collect_schema()
        if "value_after_maturity_adj" in collateral_schema.names():
            value_col = "value_after_maturity_adj"
        elif "value_after_haircut" in collateral_schema.names():
            value_col = "value_after_haircut"
        elif "market_value" in collateral_schema.names():
            value_col = "market_value"
        else:
            # No collateral value, return unchanged
            return self._lf

        # Filter to eligible financial collateral (excluding real estate)
        if "is_eligible_financial_collateral" in collateral_schema.names():
            eligible_collateral = collateral.filter(
                pl.col("is_eligible_financial_collateral") == True  # noqa: E712
            )
        else:
            eligible_collateral = collateral.filter(
                ~pl.col("collateral_type").str.to_lowercase().is_in([
                    "real_estate", "property", "rre", "cre",
                    "residential_property", "commercial_property"
                ])
            )

        # Aggregate collateral by beneficiary
        collateral_by_exposure = eligible_collateral.group_by(
            "beneficiary_reference"
        ).agg([
            pl.col(value_col).sum().alias("total_collateral_adjusted"),
            pl.col("market_value").sum().alias("total_collateral_market") if "market_value" in collateral_schema.names() else pl.lit(0.0).alias("total_collateral_market"),
            pl.len().alias("collateral_count"),
        ])

        # Join collateral to exposures
        lf = self._lf.join(
            collateral_by_exposure,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        )

        # Fill nulls for exposures without collateral
        lf = lf.with_columns([
            pl.col("total_collateral_adjusted").fill_null(0.0).alias("collateral_adjusted_value"),
            pl.col("total_collateral_market").fill_null(0.0).alias("collateral_market_value"),
        ])

        # Determine approach column
        has_approach = "approach" in schema.names()

        # Apply collateral effect based on approach
        if has_approach:
            lf = lf.with_columns([
                # For SA: Reduce EAD by collateral (simple substitution)
                pl.when(pl.col("approach") == ApproachType.SA.value)
                .then(
                    (pl.col("ead_gross") - pl.col("collateral_adjusted_value")).clip(lower_bound=0)
                )
                # For IRB: Keep EAD, collateral affects LGD (handled elsewhere)
                .otherwise(pl.col("ead_gross"))
                .alias("ead_after_collateral"),
            ])
        else:
            # Default to SA behavior
            lf = lf.with_columns([
                (pl.col("ead_gross") - pl.col("collateral_adjusted_value")).clip(lower_bound=0).alias("ead_after_collateral"),
            ])

        return lf

    def apply_collateral_to_lgd(
        self,
        collateral: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Adjust LGD for collateral (IRB approach).

        For IRB exposures, eligible collateral reduces LGD rather than EAD.

        Args:
            collateral: Collateral data with adjusted values
            config: Calculation configuration

        Returns:
            LazyFrame with LGD adjusted for collateral
        """
        schema = self._lf.collect_schema()

        # Get collateral value column
        collateral_schema = collateral.collect_schema()
        if "value_after_maturity_adj" in collateral_schema.names():
            value_col = "value_after_maturity_adj"
        elif "value_after_haircut" in collateral_schema.names():
            value_col = "value_after_haircut"
        else:
            return self._lf

        # Aggregate collateral by beneficiary
        collateral_by_exposure = collateral.group_by(
            "beneficiary_reference"
        ).agg([
            pl.col(value_col).sum().alias("total_collateral_for_lgd"),
        ])

        # Join collateral to exposures
        lf = self._lf.join(
            collateral_by_exposure,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        )

        # Calculate LGD adjustment
        # Simplified: LGD_adjusted = LGD * (1 - collateral/EAD)
        # Full CRR formula is more complex
        ead_col = "ead_gross" if "ead_gross" in schema.names() else "ead_final"

        lf = lf.with_columns([
            pl.when(pl.col("total_collateral_for_lgd").is_not_null() & (pl.col(ead_col) > 0))
            .then(
                pl.col("lgd_pre_crm") * (
                    1 - pl.col("total_collateral_for_lgd") / pl.col(ead_col)
                ).clip(lower_bound=0)
            )
            .otherwise(pl.col("lgd_pre_crm"))
            .alias("lgd_post_crm"),
        ])

        return lf

    # =========================================================================
    # GUARANTEE APPLICATION
    # =========================================================================

    def apply_guarantees(
        self,
        guarantees: pl.LazyFrame,
        counterparty_lookup: pl.LazyFrame,
        config: CalculationConfig,
        rating_inheritance: pl.LazyFrame | None = None,
    ) -> pl.LazyFrame:
        """
        Apply guarantee substitution.

        For guaranteed portion, substitute borrower RW with guarantor RW.

        Args:
            guarantees: Guarantee data
            counterparty_lookup: For guarantor risk weights
            config: Calculation configuration
            rating_inheritance: For guarantor CQS lookup

        Returns:
            LazyFrame with guarantee effects applied
        """
        schema = self._lf.collect_schema()

        # Aggregate guarantees by beneficiary
        guarantees_by_exposure = guarantees.group_by(
            "beneficiary_reference"
        ).agg([
            pl.col("amount_covered").sum().alias("total_guarantee_amount"),
            pl.col("guarantor").first().alias("primary_guarantor"),
            pl.len().alias("guarantee_count"),
        ])

        # Join guarantees to exposures
        lf = self._lf.join(
            guarantees_by_exposure,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        )

        # Fill nulls
        lf = lf.with_columns([
            pl.col("total_guarantee_amount").fill_null(0.0).alias("guarantee_amount"),
            pl.col("primary_guarantor").alias("guarantor_reference"),
        ])

        # Calculate guaranteed vs unguaranteed portions
        ead_col = "ead_after_collateral" if "ead_after_collateral" in schema.names() else "ead_final"

        lf = lf.with_columns([
            # Guaranteed amount (capped at EAD)
            pl.min_horizontal(
                pl.col("guarantee_amount"),
                pl.col(ead_col)
            ).alias("guaranteed_portion"),
        ])

        lf = lf.with_columns([
            # Unguaranteed portion
            (pl.col(ead_col) - pl.col("guaranteed_portion")).alias("unguaranteed_portion"),
        ])

        # Look up guarantor's entity type and CQS
        lf = lf.join(
            counterparty_lookup.select([
                pl.col("counterparty_reference"),
                pl.col("entity_type").alias("guarantor_entity_type"),
            ]),
            left_on="guarantor_reference",
            right_on="counterparty_reference",
            how="left",
        )

        # Look up guarantor's CQS and rating type from ratings
        if rating_inheritance is not None:
            ri_schema = rating_inheritance.collect_schema()
            ri_cols = [
                pl.col("counterparty_reference"),
                pl.col("cqs").alias("guarantor_cqs"),
            ]
            if "rating_type" in ri_schema.names():
                ri_cols.append(pl.col("rating_type").alias("guarantor_rating_type"))

            lf = lf.join(
                rating_inheritance.select(ri_cols),
                left_on="guarantor_reference",
                right_on="counterparty_reference",
                how="left",
            )

            if "rating_type" not in ri_schema.names():
                lf = lf.with_columns([
                    pl.lit(None).cast(pl.String).alias("guarantor_rating_type"),
                ])
        else:
            lf = lf.with_columns([
                pl.lit(None).cast(pl.Int8).alias("guarantor_cqs"),
                pl.lit(None).cast(pl.String).alias("guarantor_rating_type"),
            ])

        # Fill nulls
        lf = lf.with_columns([
            pl.col("guarantor_entity_type").fill_null("").alias("guarantor_entity_type"),
        ])

        # Derive guarantor exposure class and approach
        lf = lf.with_columns([
            pl.col("guarantor_entity_type")
            .replace_strict(ENTITY_TYPE_TO_SA_CLASS, default="")
            .alias("guarantor_exposure_class"),
        ])

        # Determine guarantor approach from IRB permissions AND rating type.
        # IRB only if: firm has IRB permission AND guarantor has internal rating.
        irb_exposure_class_values = set()
        for ec, approaches in config.irb_permissions.permissions.items():
            if ApproachType.FIRB in approaches or ApproachType.AIRB in approaches:
                irb_exposure_class_values.add(ec.value)

        lf = lf.with_columns([
            pl.when(
                (pl.col("guarantor_exposure_class") != "") &
                pl.col("guarantor_exposure_class").is_in(list(irb_exposure_class_values)) &
                (pl.col("guarantor_rating_type").fill_null("") == "internal")
            )
            .then(pl.lit("irb"))
            .when(pl.col("guarantor_exposure_class") != "")
            .then(pl.lit("sa"))
            .otherwise(pl.lit(""))
            .alias("guarantor_approach"),
        ])

        # Cross-approach CCF substitution
        has_risk_type = "risk_type" in schema.names()
        has_nominal = "nominal_amount" in schema.names()
        has_approach = "approach" in schema.names()
        has_interest = "interest" in schema.names()

        if has_risk_type and has_nominal and has_approach:
            # Compute guarantee ratio
            lf = lf.with_columns([
                pl.when(pl.col(ead_col) > 0)
                .then(
                    (pl.col("guaranteed_portion") / pl.col(ead_col))
                    .clip(upper_bound=1.0)
                )
                .otherwise(pl.lit(0.0))
                .alias("guarantee_ratio"),
            ])

            needs_ccf_sub = (
                pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value]) &
                (pl.col("guarantor_approach") == "sa") &
                (pl.col("guaranteed_portion") > 0) &
                (pl.col("nominal_amount") > 0)
            )

            sa_ccf = sa_ccf_expression()
            lf = lf.with_columns([
                pl.col("ccf").alias("ccf_original"),
                pl.when(needs_ccf_sub).then(sa_ccf).otherwise(pl.col("ccf")).alias("ccf_guaranteed"),
                pl.col("ccf").alias("ccf_unguaranteed"),
            ])

            on_bal = pl.col("drawn_amount") + (
                pl.col("interest").fill_null(0.0) if has_interest else pl.lit(0.0)
            )
            ratio = pl.col("guarantee_ratio")
            new_guaranteed = (on_bal * ratio) + (pl.col("nominal_amount") * ratio * pl.col("ccf_guaranteed"))
            new_unguaranteed = (on_bal * (pl.lit(1.0) - ratio)) + (
                pl.col("nominal_amount") * (pl.lit(1.0) - ratio) * pl.col("ccf_unguaranteed")
            )

            lf = lf.with_columns([
                pl.when(needs_ccf_sub).then(new_guaranteed).otherwise(pl.col("guaranteed_portion")).alias("guaranteed_portion"),
                pl.when(needs_ccf_sub).then(new_unguaranteed).otherwise(pl.col("unguaranteed_portion")).alias("unguaranteed_portion"),
            ])

            lf = lf.with_columns([
                pl.when(needs_ccf_sub)
                .then(pl.col("guaranteed_portion") + pl.col("unguaranteed_portion"))
                .otherwise(pl.col(ead_col))
                .alias("ead_after_collateral" if "ead_after_collateral" in schema.names() else "ead_final"),
            ])

        return lf

    # =========================================================================
    # PROVISION APPLICATION
    # =========================================================================

    def apply_provisions(
        self,
        provisions: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply provision deduction from EAD.

        For SA, specific provisions are deducted from EAD.
        For IRB, provisions are compared to EL for shortfall/excess.

        Args:
            provisions: Provision data
            config: Calculation configuration

        Returns:
            LazyFrame with provision effects applied
        """
        schema = self._lf.collect_schema()

        # Aggregate provisions by beneficiary (exposure)
        provisions_by_exposure = provisions.group_by(
            "beneficiary_reference"
        ).agg([
            pl.col("amount").sum().alias("total_provision"),
            pl.col("provision_type").first().alias("primary_provision_type"),
        ])

        # Join provisions to exposures
        lf = self._lf.join(
            provisions_by_exposure,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        )

        # Fill nulls and update provision columns
        lf = lf.with_columns([
            pl.col("total_provision").fill_null(0.0).alias("provision_allocated"),
        ])

        # Determine approach column
        has_approach = "approach" in schema.names()

        # Calculate provision deduction (for SA, deduct from EAD)
        if has_approach:
            lf = lf.with_columns([
                pl.when(pl.col("approach") == ApproachType.SA.value)
                .then(pl.col("provision_allocated"))
                .otherwise(pl.lit(0.0))
                .alias("provision_deducted"),
            ])
        else:
            # Default to SA behavior
            lf = lf.with_columns([
                pl.col("provision_allocated").alias("provision_deducted"),
            ])

        return lf

    # =========================================================================
    # EAD FINALIZATION
    # =========================================================================

    def finalize_ead(self) -> pl.LazyFrame:
        """
        Finalize EAD after all CRM adjustments.

        Sets ead_final based on the CRM waterfall:
        - ead_after_collateral (after collateral reduction)
        - minus provision deduction

        Returns:
            LazyFrame with finalized EAD
        """
        schema = self._lf.collect_schema()

        # Determine intermediate EAD column
        if "ead_after_collateral" in schema.names():
            intermediate_ead = "ead_after_collateral"
        elif "ead_gross" in schema.names():
            intermediate_ead = "ead_gross"
        else:
            intermediate_ead = "ead_final"

        # Get provision column
        provision_col = "provision_deducted" if "provision_deducted" in schema.names() else pl.lit(0.0)

        return self._lf.with_columns([
            # Set final EAD after provisions
            (
                pl.col(intermediate_ead) - (
                    pl.col("provision_deducted") if "provision_deducted" in schema.names() else pl.lit(0.0)
                )
            ).clip(lower_bound=0).alias("ead_final"),
            # Copy to ead_after_guarantee for audit
            pl.col(intermediate_ead).alias("ead_after_guarantee"),
        ])

    # =========================================================================
    # CONVENIENCE / PIPELINE METHODS
    # =========================================================================

    def apply_all_crm(
        self,
        collateral: pl.LazyFrame | None,
        guarantees: pl.LazyFrame | None,
        provisions: pl.LazyFrame | None,
        counterparty_lookup: pl.LazyFrame | None,
        config: CalculationConfig,
        rating_inheritance: pl.LazyFrame | None = None,
    ) -> pl.LazyFrame:
        """
        Apply full CRM pipeline.

        Steps:
        1. Initialize EAD waterfall
        2. Apply collateral (if provided)
        3. Apply guarantees (if provided)
        4. Apply provisions (if provided)
        5. Finalize EAD

        Args:
            collateral: Collateral data (optional)
            guarantees: Guarantee data (optional)
            provisions: Provision data (optional)
            counterparty_lookup: For guarantor lookup (required if guarantees provided)
            config: Calculation configuration
            rating_inheritance: For guarantor CQS lookup (optional)

        Returns:
            LazyFrame with all CRM effects applied
        """
        lf = self._lf.crm.initialize_ead_waterfall()

        if collateral is not None:
            lf = lf.crm.apply_collateral(collateral, config)

        if guarantees is not None and counterparty_lookup is not None:
            lf = lf.crm.apply_guarantees(guarantees, counterparty_lookup, config, rating_inheritance)

        if provisions is not None:
            lf = lf.crm.apply_provisions(provisions, config)

        return lf.crm.finalize_ead()

    def build_ead_audit(self) -> pl.LazyFrame:
        """
        Build CRM/EAD calculation audit trail.

        Returns:
            LazyFrame with audit columns including crm_calculation string
        """
        schema = self._lf.collect_schema()
        available_cols = schema.names()

        select_cols = ["exposure_reference"]
        optional_cols = [
            "counterparty_reference",
            "approach",
            "ead_gross",
            "collateral_adjusted_value",
            "guarantee_amount",
            "provision_allocated",
            "ead_after_collateral",
            "ead_after_guarantee",
            "ead_final",
            "lgd_pre_crm",
            "lgd_post_crm",
        ]

        for col in optional_cols:
            if col in available_cols:
                select_cols.append(col)

        audit = self._lf.select(select_cols)

        # Add calculation string
        audit = audit.with_columns([
            pl.concat_str([
                pl.lit("EAD: gross="),
                pl.col("ead_gross").round(0).cast(pl.String),
                pl.lit("; coll="),
                pl.col("collateral_adjusted_value").round(0).cast(pl.String) if "collateral_adjusted_value" in available_cols else pl.lit("0"),
                pl.lit("; guar="),
                pl.col("guarantee_amount").round(0).cast(pl.String) if "guarantee_amount" in available_cols else pl.lit("0"),
                pl.lit("; prov="),
                pl.col("provision_allocated").round(0).cast(pl.String) if "provision_allocated" in available_cols else pl.lit("0"),
                pl.lit("; final="),
                pl.col("ead_final").round(0).cast(pl.String),
            ]).alias("crm_calculation"),
        ])

        return audit
