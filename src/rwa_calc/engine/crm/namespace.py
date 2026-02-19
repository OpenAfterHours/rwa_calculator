"""
Polars LazyFrame namespaces for Credit Risk Mitigation (CRM) calculations.

Provides fluent API for CRM processing via registered namespaces:
- `lf.crm.resolve_provisions(provisions, config)` - Resolve provisions (before CCF)
- `lf.crm.initialize_ead_waterfall()` - Initialize EAD tracking columns
- `lf.crm.apply_collateral(collateral, config)` - Apply collateral effects
- `lf.crm.apply_guarantees(guarantees, config)` - Apply guarantee substitution
- `lf.crm.apply_provisions(provisions, config)` - Apply provision deduction (legacy)
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
from rwa_calc.engine.ccf import drawn_for_ead, on_balance_ead, sa_ccf_expression
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

        # Provision columns: preserve if already set by resolve_provisions,
        # otherwise initialize to zero
        has_provision_cols = "provision_allocated" in schema.names()
        has_provision_on_drawn = "provision_on_drawn" in schema.names()

        # Determine base EAD column
        # When provision columns exist and ead_pre_crm hasn't been recalculated
        # by CCF (i.e. namespace chaining without explicit CCF step), recompute
        # ead_pre_crm to reflect provision deductions
        if has_provision_on_drawn and "drawn_amount" in schema.names():
            # Recompute ead_pre_crm with provision-adjusted amounts
            on_bal = (
                drawn_for_ead() - pl.col("provision_on_drawn")
            ).clip(lower_bound=0.0)
            if "interest" in schema.names():
                on_bal = on_bal + pl.col("interest").fill_null(0.0)
            if "nominal_after_provision" in schema.names():
                nominal_col = pl.col("nominal_after_provision")
            elif "nominal_amount" in schema.names():
                nominal_col = pl.col("nominal_amount")
            else:
                nominal_col = pl.lit(0.0)
            # If CCF/ead_from_ccf already computed, use ead_pre_crm as-is
            if "ead_from_ccf" in schema.names():
                base_ead_col = "ead_pre_crm"
            else:
                # No CCF step yet; recalculate from drawn/nominal
                lf = lf.with_columns([
                    (on_bal + nominal_col).alias("ead_pre_crm"),
                ])
                base_ead_col = "ead_pre_crm"
        elif "ead_pre_crm" in schema.names():
            base_ead_col = "ead_pre_crm"
        elif "ead" in schema.names():
            base_ead_col = "ead"
        elif "drawn_amount" in schema.names():
            if "interest" in schema.names():
                lf = lf.with_columns([on_balance_ead().alias("ead_pre_crm")])
            else:
                lf = lf.with_columns([drawn_for_ead().alias("ead_pre_crm")])
            base_ead_col = "ead_pre_crm"
        else:
            # No EAD column found, create placeholder
            lf = lf.with_columns([pl.lit(0.0).alias("ead_pre_crm")])
            base_ead_col = "ead_pre_crm"
        if has_provision_cols:
            provision_cols = [
                pl.col("provision_allocated"),
                pl.col("provision_deducted"),
            ]
        else:
            provision_cols = [
                pl.lit(0.0).alias("provision_allocated"),
                pl.lit(0.0).alias("provision_deducted"),
            ]

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

            # Provision-related columns
            *provision_cols,

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

        # Allocate collateral — multi-level or direct-only
        eligible_schema = eligible_collateral.collect_schema()
        has_beneficiary_type = "beneficiary_type" in eligible_schema.names()
        has_market_value = "market_value" in collateral_schema.names()

        if has_beneficiary_type:
            lf = self._allocate_collateral_multi_level(
                eligible_collateral, value_col, has_market_value,
            )
        else:
            # Legacy: direct-only join
            collateral_by_exposure = eligible_collateral.group_by(
                "beneficiary_reference"
            ).agg([
                pl.col(value_col).sum().alias("total_collateral_adjusted"),
                pl.col("market_value").sum().alias("total_collateral_market") if has_market_value else pl.lit(0.0).alias("total_collateral_market"),
                pl.len().alias("collateral_count"),
            ])

            lf = self._lf.join(
                collateral_by_exposure,
                left_on="exposure_reference",
                right_on="beneficiary_reference",
                how="left",
            )

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

    def _allocate_collateral_multi_level(
        self,
        eligible_collateral: pl.LazyFrame,
        value_col: str,
        has_market_value: bool,
    ) -> pl.LazyFrame:
        """
        Allocate eligible collateral from direct, facility, and counterparty levels.

        Pro-rata allocation by ead_gross for facility and counterparty levels.
        """
        lf = self._lf
        exp_schema = lf.collect_schema()

        val_expr = pl.col(value_col)
        bt_lower = pl.col("beneficiary_type").str.to_lowercase()
        direct_types = ["exposure", "loan", "contingent"]
        mv_expr = pl.col("market_value") if has_market_value else pl.lit(0.0)

        # Aggregate at each level
        coll_direct = eligible_collateral.filter(
            bt_lower.is_in(direct_types)
        ).group_by("beneficiary_reference").agg([
            val_expr.sum().alias("_coll_direct"),
            mv_expr.sum().alias("_mv_direct"),
        ])

        coll_facility = eligible_collateral.filter(
            bt_lower == "facility"
        ).group_by("beneficiary_reference").agg([
            val_expr.sum().alias("_coll_facility"),
            mv_expr.sum().alias("_mv_facility"),
        ])

        coll_counterparty = eligible_collateral.filter(
            bt_lower == "counterparty"
        ).group_by("beneficiary_reference").agg([
            val_expr.sum().alias("_coll_counterparty"),
            mv_expr.sum().alias("_mv_counterparty"),
        ])

        # EAD totals for pro-rata
        if "parent_facility_reference" in exp_schema.names():
            fac_ead = lf.filter(
                pl.col("parent_facility_reference").is_not_null()
            ).group_by("parent_facility_reference").agg(
                pl.col("ead_gross").sum().alias("_fac_ead_total"),
            )
        else:
            fac_ead = pl.LazyFrame(
                schema={"parent_facility_reference": pl.String, "_fac_ead_total": pl.Float64}
            )

        cp_ead = lf.group_by("counterparty_reference").agg(
            pl.col("ead_gross").sum().alias("_cp_ead_total"),
        )

        # Join direct
        lf = lf.join(coll_direct, left_on="exposure_reference", right_on="beneficiary_reference", how="left")

        # Join facility
        if "parent_facility_reference" in exp_schema.names():
            lf = lf.join(
                coll_facility, left_on="parent_facility_reference", right_on="beneficiary_reference", how="left",
            ).join(fac_ead, on="parent_facility_reference", how="left")
        else:
            lf = lf.with_columns([
                pl.lit(0.0).alias("_coll_facility"),
                pl.lit(0.0).alias("_mv_facility"),
                pl.lit(0.0).alias("_fac_ead_total"),
            ])

        # Join counterparty
        lf = lf.join(
            coll_counterparty, left_on="counterparty_reference", right_on="beneficiary_reference", how="left",
        ).join(cp_ead, on="counterparty_reference", how="left")

        # Fill nulls + weights + combine
        lf = lf.with_columns([
            pl.col("_coll_direct").fill_null(0.0),
            pl.col("_mv_direct").fill_null(0.0),
            pl.col("_coll_facility").fill_null(0.0),
            pl.col("_mv_facility").fill_null(0.0),
            pl.col("_coll_counterparty").fill_null(0.0),
            pl.col("_mv_counterparty").fill_null(0.0),
            pl.col("_fac_ead_total").fill_null(0.0),
            pl.col("_cp_ead_total").fill_null(0.0),
        ])

        lf = lf.with_columns([
            pl.when(pl.col("_fac_ead_total") > 0)
            .then(pl.col("ead_gross") / pl.col("_fac_ead_total"))
            .otherwise(pl.lit(0.0))
            .alias("_fac_weight"),
            pl.when(pl.col("_cp_ead_total") > 0)
            .then(pl.col("ead_gross") / pl.col("_cp_ead_total"))
            .otherwise(pl.lit(0.0))
            .alias("_cp_weight"),
        ])

        lf = lf.with_columns([
            (
                pl.col("_coll_direct")
                + (pl.col("_coll_facility") * pl.col("_fac_weight"))
                + (pl.col("_coll_counterparty") * pl.col("_cp_weight"))
            ).alias("collateral_adjusted_value"),
            (
                pl.col("_mv_direct")
                + (pl.col("_mv_facility") * pl.col("_fac_weight"))
                + (pl.col("_mv_counterparty") * pl.col("_cp_weight"))
            ).alias("collateral_market_value"),
        ])

        lf = lf.drop([
            "_coll_direct", "_mv_direct",
            "_coll_facility", "_mv_facility",
            "_coll_counterparty", "_mv_counterparty",
            "_fac_ead_total", "_cp_ead_total",
            "_fac_weight", "_cp_weight",
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

            on_bal = on_balance_ead() if has_interest else drawn_for_ead()
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

    def resolve_provisions(
        self,
        provisions: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Resolve provisions with multi-level beneficiary and drawn-first deduction.

        Called *before* CCF so that nominal_after_provision feeds into the
        CCF calculation: ``ead_from_ccf = nominal_after_provision * ccf``.

        Args:
            provisions: Provision data
            config: Calculation configuration

        Returns:
            LazyFrame with provision columns added
        """
        from rwa_calc.engine.crm.processor import CRMProcessor

        processor = CRMProcessor()
        return processor.resolve_provisions(self._lf, provisions, config)

    def apply_provisions(
        self,
        provisions: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply provision deduction from EAD (legacy method).

        Delegates to resolve_provisions for the full multi-level resolution
        and drawn-first deduction logic.

        Args:
            provisions: Provision data
            config: Calculation configuration

        Returns:
            LazyFrame with provision effects applied
        """
        return self.resolve_provisions(provisions, config)

    # =========================================================================
    # EAD FINALIZATION
    # =========================================================================

    def finalize_ead(self) -> pl.LazyFrame:
        """
        Finalize EAD after all CRM adjustments.

        Provisions are already baked into ead_pre_crm (deducted before CCF),
        so finalize_ead does NOT subtract provision_deducted again.

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

        return self._lf.with_columns([
            pl.col(intermediate_ead).clip(lower_bound=0).alias("ead_final"),
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
        1. Resolve provisions (before CCF, adds nominal_after_provision)
        2. Initialize EAD waterfall
        3. Apply collateral (if provided)
        4. Apply guarantees (if provided)
        5. Finalize EAD (no double-deduction of provisions)

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
        lf = self._lf

        # Step 1: Resolve provisions BEFORE initialize_ead_waterfall (which triggers CCF)
        if provisions is not None:
            lf = lf.crm.resolve_provisions(provisions, config)

        lf = lf.crm.initialize_ead_waterfall()

        if collateral is not None:
            lf = lf.crm.apply_collateral(collateral, config)

        if guarantees is not None and counterparty_lookup is not None:
            lf = lf.crm.apply_guarantees(guarantees, counterparty_lookup, config, rating_inheritance)

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
