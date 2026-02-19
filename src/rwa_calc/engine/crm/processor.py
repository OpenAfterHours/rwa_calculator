"""
Credit Risk Mitigation (CRM) processor for RWA calculator.

Applies all CRM techniques to exposures:
- CCF for off-balance sheet items
- Collateral haircuts and allocation
- Guarantee substitution
- Provision deduction

Classes:
    CRMProcessor: Main processor implementing CRMProcessorProtocol

Usage:
    from rwa_calc.engine.crm.processor import CRMProcessor

    processor = CRMProcessor()
    adjusted = processor.apply_crm(classified_data, config)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    CRMAdjustedBundle,
)
from rwa_calc.contracts.errors import LazyFrameResult
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.ccf import CCFCalculator, drawn_for_ead, on_balance_ead, sa_ccf_expression
from rwa_calc.engine.classifier import ENTITY_TYPE_TO_SA_CLASS
from rwa_calc.engine.crm.haircuts import HaircutCalculator
from rwa_calc.data.tables.crr_firb_lgd import get_firb_lgd_table

# Transient columns used during guarantee processing but dropped from output
# These values can be obtained via joins on guarantor_reference
TRANSIENT_GUARANTEE_COLUMNS = [
    "guarantor_entity_type",
    "guarantor_cqs",
    "guarantor_pd",
    "guarantor_rating_type",
    "guarantor_rating_source",
    "guarantor_exposure_class",
]

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


@dataclass
class CRMError:
    """Error encountered during CRM processing."""

    error_type: str
    message: str
    exposure_reference: str | None = None
    context: dict = field(default_factory=dict)


class CRMProcessor:
    """
    Apply credit risk mitigation to exposures.

    Implements CRMProcessorProtocol for:
    - CCF application for off-balance sheet items (CRR Art. 111)
    - Collateral haircuts and allocation (CRR Art. 223-224)
    - Guarantee substitution (CRR Art. 213-215)
    - Provision deduction (CRR Art. 110)

    The CRM process follows this order:
    1. Apply CCF to calculate base EAD for contingents
    2. Apply collateral (reduce EAD for SA, reduce LGD for IRB)
    3. Apply guarantees (substitution approach)
    4. Deduct provisions from EAD
    """

    # Required columns for each CRM data type
    COLLATERAL_REQUIRED_COLUMNS = {"beneficiary_reference", "market_value"}
    GUARANTEE_REQUIRED_COLUMNS = {"beneficiary_reference", "amount_covered", "guarantor"}
    PROVISION_REQUIRED_COLUMNS = {"beneficiary_reference", "amount"}

    def __init__(self) -> None:
        """Initialize CRM processor with sub-calculators."""
        self._ccf_calculator = CCFCalculator()
        self._haircut_calculator = HaircutCalculator()

    def _is_valid_for_processing(
        self,
        data: pl.LazyFrame | None,
        required_columns: set[str],
    ) -> bool:
        """
        Check if optional CRM data is valid for processing.

        This provides defense-in-depth validation to ensure data has:
        - At least one row
        - All required columns for the CRM operation

        Args:
            data: Optional LazyFrame to validate
            required_columns: Set of column names that must be present

        Returns:
            True if data is valid for processing, False otherwise
        """
        if data is None:
            return False

        try:
            # Check schema has required columns
            schema = data.collect_schema()
            if not required_columns.issubset(set(schema.names())):
                return False

            # Check if there's at least one row
            return data.head(1).collect().height > 0
        except Exception:
            return False

    def apply_crm(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> LazyFrameResult:
        """
        Apply credit risk mitigation to exposures.

        Args:
            data: Classified exposures from classifier
            config: Calculation configuration

        Returns:
            LazyFrameResult with CRM-adjusted exposures and any errors
        """
        bundle = self.get_crm_adjusted_bundle(data, config)

        # Convert to LazyFrameResult format
        return LazyFrameResult(
            frame=bundle.exposures,
            errors=[],  # CRMError objects would need conversion to CalculationError
        )

    def get_crm_adjusted_bundle(
        self,
        data: ClassifiedExposuresBundle,
        config: CalculationConfig,
    ) -> CRMAdjustedBundle:
        """
        Apply CRM and return as a bundle.

        Args:
            data: Classified exposures from classifier
            config: Calculation configuration

        Returns:
            CRMAdjustedBundle with adjusted exposures
        """
        errors: list[CRMError] = []

        # Start with all exposures
        exposures = data.all_exposures

        # Step 1: Resolve provisions BEFORE CCF (CRR Art. 111(2))
        # This adds provision_on_drawn, provision_on_nominal, nominal_after_provision
        # so CCF can use the provision-adjusted nominal amount
        if self._is_valid_for_processing(data.provisions, self.PROVISION_REQUIRED_COLUMNS):
            exposures = self.resolve_provisions(exposures, data.provisions, config)

        # Step 2: Apply CCF to calculate EAD for contingents
        # Uses nominal_after_provision when available
        exposures = self._apply_ccf(exposures, config)

        # Step 3: Initialize EAD columns
        exposures = self._initialize_ead(exposures)

        # Step 4: Apply collateral (if available and valid)
        if self._is_valid_for_processing(data.collateral, self.COLLATERAL_REQUIRED_COLUMNS):
            exposures = self.apply_collateral(exposures, data.collateral, config)
        else:
            # No collateral: still need to set F-IRB supervisory LGD based on seniority
            exposures = self._apply_firb_supervisory_lgd_no_collateral(exposures)

        # Step 5: Apply guarantees (if available and valid)
        if (
            self._is_valid_for_processing(data.guarantees, self.GUARANTEE_REQUIRED_COLUMNS)
            and data.counterparty_lookup is not None
        ):
            exposures = self.apply_guarantees(
                exposures,
                data.guarantees,
                data.counterparty_lookup.counterparties,
                config,
                data.counterparty_lookup.rating_inheritance,
            )

        # Step 6: Calculate final EAD after all CRM adjustments
        # Provisions already baked into ead_pre_crm — no double deduction
        exposures = self._finalize_ead(exposures)

        # Step 7: Add CRM audit trail
        exposures = self._add_crm_audit(exposures)

        # Strategic collect to materialize all CRM processing
        # This breaks up the complex query plan for better downstream performance
        exposures = exposures.collect().lazy()

        # Split by approach for output
        sa_exposures = exposures.filter(pl.col("approach") == ApproachType.SA.value)
        irb_exposures = exposures.filter(
            (pl.col("approach") == ApproachType.FIRB.value) |
            (pl.col("approach") == ApproachType.AIRB.value)
        )
        slotting_exposures = exposures.filter(
            pl.col("approach") == ApproachType.SLOTTING.value
        )

        return CRMAdjustedBundle(
            exposures=exposures,
            sa_exposures=sa_exposures,
            irb_exposures=irb_exposures,
            slotting_exposures=slotting_exposures,
            equity_exposures=data.equity_exposures,  # Pass through equity (no CRM)
            crm_audit=self._build_crm_audit(exposures),
            collateral_allocation=None,  # Would be populated from collateral processing
            crm_errors=errors,
        )

    def _apply_ccf(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply CCF to off-balance sheet exposures.

        Args:
            exposures: All exposures
            config: Calculation configuration

        Returns:
            Exposures with CCF and ead_from_ccf columns
        """
        return self._ccf_calculator.apply_ccf(exposures, config)

    def _initialize_ead(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Initialize EAD columns and preserve pre-CRM attributes.

        Sets up the EAD waterfall:
        - ead_gross: drawn + CCF-adjusted undrawn
        - ead_after_collateral: EAD after collateral
        - ead_after_guarantee: EAD after guarantee substitution
        - ead_after_provision: Final EAD after provision deduction

        Also captures pre-CRM state for regulatory reporting:
        - pre_crm_counterparty_reference: Original borrower reference
        - pre_crm_exposure_class: Original exposure class before substitution
        """
        schema = exposures.collect_schema()
        has_provision_cols = "provision_allocated" in schema.names()

        # Provision columns: preserve if already set by resolve_provisions,
        # otherwise initialize to zero
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

        return exposures.with_columns([
            # Pre-CRM attributes for regulatory reporting
            # These capture the original (pre-CRM) state before any substitution
            pl.col("counterparty_reference").alias("pre_crm_counterparty_reference"),
            pl.col("exposure_class").alias("pre_crm_exposure_class"),

            # Gross EAD = drawn + CCF-adjusted contingent
            pl.col("ead_pre_crm").alias("ead_gross"),

            # Initialize subsequent EAD columns (will be adjusted by CRM)
            pl.col("ead_pre_crm").alias("ead_after_collateral"),
            pl.col("ead_pre_crm").alias("ead_after_guarantee"),
            pl.col("ead_pre_crm").alias("ead_final"),

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
            pl.col("lgd").fill_null(0.45).alias("lgd_pre_crm"),
            pl.col("lgd").fill_null(0.45).alias("lgd_post_crm"),

            # Initialize guarantee tracking columns
            pl.lit(False).alias("is_guaranteed"),
            pl.lit(0.0).alias("guaranteed_portion"),
            pl.lit(0.0).alias("unguaranteed_portion"),

            # Initialize post-CRM columns (will be updated by apply_guarantees if called)
            # For exposures without guarantees, post-CRM = pre-CRM
            pl.col("counterparty_reference").alias("post_crm_counterparty_guaranteed"),
            pl.col("exposure_class").alias("post_crm_exposure_class_guaranteed"),
            pl.lit("").alias("guarantor_exposure_class"),

            # Cross-approach CCF substitution columns
            pl.col("ccf").alias("ccf_original"),
            pl.col("ccf").alias("ccf_guaranteed"),
            pl.col("ccf").alias("ccf_unguaranteed"),
            pl.lit(0.0).alias("guarantee_ratio"),
            pl.lit("").alias("guarantor_approach"),
        ])

    def _finalize_ead(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Finalize EAD after all CRM adjustments.

        Provisions are already baked into ead_pre_crm (deducted before CCF),
        so finalize_ead does NOT subtract provision_deducted again.

        Sets ead_final = ead_after_collateral floored at 0.
        """
        return exposures.with_columns([
            pl.col("ead_after_collateral").clip(lower_bound=0).alias("ead_final"),
            pl.col("ead_after_collateral").alias("ead_after_guarantee"),
        ])

    def _resolve_pledge_percentages(
        self,
        collateral: pl.LazyFrame,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Resolve percentage-based collateral pledges to absolute market values.

        When collateral has pledge_percentage set instead of market_value, computes
        market_value = pledge_percentage * beneficiary_total_ead. The base EAD depends
        on the beneficiary level:
        - Direct (exposure/loan/contingent): that exposure's ead_gross
        - Facility: sum of ead_gross for all exposures under that facility
        - Counterparty: sum of ead_gross for all exposures of that counterparty

        market_value takes precedence when non-null and non-zero.

        Args:
            collateral: Collateral data, may or may not have pledge_percentage column
            exposures: Exposures with ead_gross, parent_facility_reference, counterparty_reference

        Returns:
            Collateral with market_value resolved from pledge_percentage where applicable
        """
        coll_schema = collateral.collect_schema()
        if "pledge_percentage" not in coll_schema.names():
            return collateral

        # Determine which rows need resolution:
        # market_value is null or 0, AND pledge_percentage is set and > 0
        needs_resolve = (
            (pl.col("market_value").is_null() | (pl.col("market_value") == 0.0)) &
            pl.col("pledge_percentage").is_not_null() &
            (pl.col("pledge_percentage") > 0.0)
        )

        has_beneficiary_type = "beneficiary_type" in coll_schema.names()

        # Build EAD lookups at each level
        # Direct: exposure_reference → ead_gross
        direct_ead = exposures.select([
            pl.col("exposure_reference").alias("_ben_ref"),
            pl.col("ead_gross").alias("_beneficiary_ead"),
        ])

        # Facility: parent_facility_reference → sum(ead_gross)
        exp_schema = exposures.collect_schema()
        if "parent_facility_reference" in exp_schema.names():
            facility_ead = exposures.filter(
                pl.col("parent_facility_reference").is_not_null()
            ).group_by("parent_facility_reference").agg(
                pl.col("ead_gross").sum().alias("_beneficiary_ead"),
            ).select(
                pl.col("parent_facility_reference").cast(pl.String).alias("_ben_ref"),
                pl.col("_beneficiary_ead"),
            )
        else:
            facility_ead = pl.LazyFrame(
                schema={"_ben_ref": pl.String, "_beneficiary_ead": pl.Float64}
            )

        # Counterparty: counterparty_reference → sum(ead_gross)
        counterparty_ead = exposures.group_by("counterparty_reference").agg(
            pl.col("ead_gross").sum().alias("_beneficiary_ead"),
        ).rename({"counterparty_reference": "_ben_ref"})

        if has_beneficiary_type:
            # Split by beneficiary_type, join to correct lookup, concat back
            bt_lower = pl.col("beneficiary_type").str.to_lowercase()

            direct_types = ["exposure", "loan", "contingent"]
            coll_direct = collateral.filter(bt_lower.is_in(direct_types))
            coll_facility = collateral.filter(bt_lower == "facility")
            coll_counterparty = collateral.filter(bt_lower == "counterparty")

            # Join each split to its EAD lookup
            coll_direct = coll_direct.join(
                direct_ead, left_on="beneficiary_reference", right_on="_ben_ref", how="left",
            )
            coll_facility = coll_facility.join(
                facility_ead, left_on="beneficiary_reference", right_on="_ben_ref", how="left",
            )
            coll_counterparty = coll_counterparty.join(
                counterparty_ead, left_on="beneficiary_reference", right_on="_ben_ref", how="left",
            )

            collateral = pl.concat([coll_direct, coll_facility, coll_counterparty], how="diagonal_relaxed")
        else:
            # Legacy: join beneficiary_reference to exposure_reference
            collateral = collateral.join(
                direct_ead, left_on="beneficiary_reference", right_on="_ben_ref", how="left",
            )

        # Fill null EAD (no match found)
        collateral = collateral.with_columns(
            pl.col("_beneficiary_ead").fill_null(0.0),
        )

        # Resolve: when needs_resolve, set market_value = pledge_percentage * beneficiary_ead
        collateral = collateral.with_columns(
            pl.when(needs_resolve)
            .then(pl.col("pledge_percentage") * pl.col("_beneficiary_ead"))
            .otherwise(pl.col("market_value"))
            .alias("market_value"),
        )

        # Drop helper column
        collateral = collateral.drop("_beneficiary_ead")

        return collateral

    def apply_collateral(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply collateral to reduce EAD (SA) or LGD (IRB).

        Args:
            exposures: Exposures with ead_gross
            collateral: Collateral data
            config: Calculation configuration

        Returns:
            Exposures with collateral effects applied
        """
        # Resolve percentage-based collateral to absolute market values
        collateral = self._resolve_pledge_percentages(collateral, exposures)

        # Apply haircuts to collateral
        adjusted_collateral = self._haircut_calculator.apply_haircuts(
            collateral, exposures, config
        )

        # Apply maturity mismatch
        adjusted_collateral = self._haircut_calculator.apply_maturity_mismatch(
            adjusted_collateral, exposures
        )

        # Filter to only eligible financial collateral for EAD reduction
        # Real estate collateral affects risk weight (via LTV) but does NOT reduce EAD
        # Check if is_eligible_financial_collateral column exists
        collateral_schema = adjusted_collateral.collect_schema()
        if "is_eligible_financial_collateral" in collateral_schema:
            eligible_collateral = adjusted_collateral.filter(
                pl.col("is_eligible_financial_collateral") == True  # noqa: E712
            )
        else:
            # If column doesn't exist, exclude real estate by type
            eligible_collateral = adjusted_collateral.filter(
                ~pl.col("collateral_type").str.to_lowercase().is_in([
                    "real_estate", "property", "rre", "cre",
                    "residential_property", "commercial_property"
                ])
            )

        # Allocate collateral for SA EAD reduction
        # Check if multi-level linking (beneficiary_type) is available
        eligible_schema = eligible_collateral.collect_schema()
        has_beneficiary_type = "beneficiary_type" in eligible_schema.names()

        if has_beneficiary_type:
            exposures = self._allocate_collateral_multi_level_for_ead(
                exposures, eligible_collateral
            )
        else:
            # Legacy: direct-only join
            collateral_by_exposure = eligible_collateral.group_by(
                "beneficiary_reference"
            ).agg([
                pl.coalesce(
                    pl.col("value_after_maturity_adj"),
                    pl.col("value_after_haircut")
                ).sum().alias("total_collateral_adjusted"),
                pl.col("market_value").sum().alias("total_collateral_market"),
                pl.len().alias("collateral_count"),
            ])

            exposures = exposures.join(
                collateral_by_exposure,
                left_on="exposure_reference",
                right_on="beneficiary_reference",
                how="left",
            )

            exposures = exposures.with_columns([
                pl.col("total_collateral_adjusted").fill_null(0.0).alias("collateral_adjusted_value"),
                pl.col("total_collateral_market").fill_null(0.0).alias("collateral_market_value"),
            ])

        # Apply collateral effect based on approach
        exposures = exposures.with_columns([
            # For SA: Reduce EAD by collateral (simple substitution)
            pl.when(pl.col("approach") == ApproachType.SA.value)
            .then(
                (pl.col("ead_gross") - pl.col("collateral_adjusted_value")).clip(lower_bound=0)
            )
            # For IRB: Keep EAD, collateral affects LGD (handled below)
            .otherwise(pl.col("ead_gross"))
            .alias("ead_after_collateral"),
        ])

        # For F-IRB: Calculate effective LGD with collateral
        # A-IRB uses modelled LGD, so no adjustment needed
        exposures = self._calculate_irb_lgd_with_collateral(
            exposures, adjusted_collateral, config
        )

        return exposures

    def _calculate_irb_lgd_with_collateral(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Calculate effective LGD for F-IRB exposures with collateral.

        For F-IRB, collateral reduces LGD using supervisory values (CRR Art. 161):
        - Financial collateral: 0% LGD
        - Receivables: 35% LGD
        - Real estate (residential/commercial): 35% LGD
        - Other physical: 40% LGD
        - Unsecured senior: 45% LGD
        - Subordinated: 75% LGD

        For partially secured exposures, effective LGD is the weighted average:
        LGD_eff = (LGD_secured * secured_portion + LGD_unsecured * unsecured_portion) / EAD

        Note: A-IRB uses internally modelled LGD - no adjustment is made here.

        Args:
            exposures: Exposures with ead_gross and lgd_pre_crm
            collateral: All collateral (not just financial) with haircut-adjusted values
            config: Calculation configuration

        Returns:
            Exposures with lgd_post_crm updated for F-IRB
        """
        # Check if collateral has required columns
        collateral_schema = collateral.collect_schema()
        if "collateral_type" not in collateral_schema.names():
            # No collateral type info, cannot calculate LGD adjustment
            return exposures

        # Categorize collateral types for LGD lookup
        # Map to F-IRB supervisory LGD categories
        # Also assign overcollateralisation ratio and min threshold per CRR Art. 230 / CRE32.9-12
        _financial_types = [
            "cash", "deposit", "gold", "financial_collateral",
            "government_bond", "corporate_bond", "equity"
        ]
        _receivable_types = ["receivables", "trade_receivables"]
        _real_estate_types = [
            "real_estate", "property", "rre", "cre",
            "residential_re", "commercial_re",
            "residential", "commercial",
            "residential_property", "commercial_property"
        ]
        _other_physical_types = ["other_physical", "equipment", "inventory", "other"]

        coll_type_lower = pl.col("collateral_type").str.to_lowercase()

        collateral_with_lgd = collateral.with_columns([
            pl.when(coll_type_lower.is_in(_financial_types))
            .then(pl.lit(0.0))
            .when(coll_type_lower.is_in(_receivable_types))
            .then(pl.lit(0.35))
            .when(coll_type_lower.is_in(_real_estate_types))
            .then(pl.lit(0.35))
            .when(coll_type_lower.is_in(_other_physical_types))
            .then(pl.lit(0.40))
            .otherwise(pl.lit(0.45))
            .alias("collateral_lgd"),

            # Overcollateralisation ratio (CRR Art. 230 / CRE32.9-12)
            pl.when(coll_type_lower.is_in(_financial_types))
            .then(pl.lit(1.0))
            .when(coll_type_lower.is_in(_receivable_types))
            .then(pl.lit(1.25))
            .when(coll_type_lower.is_in(_real_estate_types))
            .then(pl.lit(1.40))
            .when(coll_type_lower.is_in(_other_physical_types))
            .then(pl.lit(1.40))
            .otherwise(pl.lit(1.0))
            .alias("overcollateralisation_ratio"),

            # Minimum collateralisation threshold
            pl.when(coll_type_lower.is_in(_financial_types))
            .then(pl.lit(0.0))
            .when(coll_type_lower.is_in(_receivable_types))
            .then(pl.lit(0.0))
            .when(coll_type_lower.is_in(_real_estate_types))
            .then(pl.lit(0.30))
            .when(coll_type_lower.is_in(_other_physical_types))
            .then(pl.lit(0.30))
            .otherwise(pl.lit(0.0))
            .alias("min_collateralisation_threshold"),

            # Flag for financial vs non-financial (for min threshold split)
            coll_type_lower.is_in(_financial_types).alias("is_financial_collateral_type"),
        ])

        # Get adjusted collateral value (prefer maturity-adjusted, then haircut)
        # Then calculate effectively_secured = adjusted_value / overcollateralisation_ratio
        collateral_with_lgd = collateral_with_lgd.with_columns([
            pl.coalesce(
                pl.col("value_after_maturity_adj") if "value_after_maturity_adj" in collateral_schema.names() else pl.lit(None),
                pl.col("value_after_haircut") if "value_after_haircut" in collateral_schema.names() else pl.lit(None),
                pl.col("market_value"),
            ).alias("adjusted_value"),
        ])
        collateral_with_lgd = collateral_with_lgd.with_columns([
            (pl.col("adjusted_value") / pl.col("overcollateralisation_ratio"))
            .alias("effectively_secured"),
        ])

        # Aggregate collateral by beneficiary with weighted LGD at each linking level
        # Supports three levels: direct (exposure), facility, counterparty

        # Check for beneficiary_type column for multi-level linking
        has_beneficiary_type = "beneficiary_type" in collateral_schema.names()

        if has_beneficiary_type:
            # Multi-level collateral allocation
            exposures = self._allocate_collateral_multi_level_for_lgd(
                exposures, collateral_with_lgd
            )
        else:
            # Legacy: direct linking only
            # Aggregate financial and non-financial separately for min threshold check
            collateral_by_exposure = collateral_with_lgd.group_by(
                "beneficiary_reference"
            ).agg([
                # Financial collateral aggregates
                pl.col("effectively_secured")
                .filter(pl.col("is_financial_collateral_type"))
                .sum().alias("eff_fin"),
                (pl.col("effectively_secured") * pl.col("collateral_lgd"))
                .filter(pl.col("is_financial_collateral_type"))
                .sum().alias("wlgd_fin"),

                # Non-financial collateral aggregates
                pl.col("effectively_secured")
                .filter(~pl.col("is_financial_collateral_type"))
                .sum().alias("eff_nf"),
                (pl.col("effectively_secured") * pl.col("collateral_lgd"))
                .filter(~pl.col("is_financial_collateral_type"))
                .sum().alias("wlgd_nf"),

                # Raw non-financial adjusted_value for min threshold check
                pl.col("adjusted_value")
                .filter(~pl.col("is_financial_collateral_type"))
                .sum().alias("raw_nf"),
            ])

            exposures = exposures.join(
                collateral_by_exposure,
                left_on="exposure_reference",
                right_on="beneficiary_reference",
                how="left",
            )

            exposures = exposures.with_columns([
                pl.col("eff_fin").fill_null(0.0),
                pl.col("wlgd_fin").fill_null(0.0),
                pl.col("eff_nf").fill_null(0.0),
                pl.col("wlgd_nf").fill_null(0.0),
                pl.col("raw_nf").fill_null(0.0),
            ])

            # Apply min threshold: if raw non-financial < 30% of EAD, zero it out
            exposures = exposures.with_columns([
                pl.when(pl.col("raw_nf") >= 0.30 * pl.col("ead_gross"))
                .then(pl.col("eff_nf"))
                .otherwise(pl.lit(0.0))
                .alias("eff_nf_final"),
                pl.when(pl.col("raw_nf") >= 0.30 * pl.col("ead_gross"))
                .then(pl.col("wlgd_nf"))
                .otherwise(pl.lit(0.0))
                .alias("wlgd_nf_final"),
            ])

            # Combine financial + non-financial
            exposures = exposures.with_columns([
                (pl.col("eff_fin") + pl.col("eff_nf_final")).alias("total_collateral_for_lgd"),
                (pl.col("wlgd_fin") + pl.col("wlgd_nf_final")).alias("total_weighted_lgd_sum"),
            ])

            exposures = exposures.with_columns([
                pl.when(pl.col("total_collateral_for_lgd") > 0)
                .then(pl.col("total_weighted_lgd_sum") / pl.col("total_collateral_for_lgd"))
                .otherwise(pl.lit(0.45))
                .alias("lgd_secured"),
            ])

            # Drop intermediate columns
            exposures = exposures.drop([
                "eff_fin", "wlgd_fin", "eff_nf", "wlgd_nf",
                "raw_nf", "eff_nf_final", "wlgd_nf_final",
                "total_weighted_lgd_sum",
            ])

        # Determine LGD for unsecured portion based on seniority
        exposures = exposures.with_columns([
            pl.when(
                pl.col("seniority").str.to_lowercase().is_in(["subordinated", "junior"])
            ).then(pl.lit(0.75))
            .otherwise(pl.lit(0.45))  # Senior unsecured
            .alias("lgd_unsecured"),
        ])

        # Calculate effective LGD for F-IRB exposures
        # LGD_eff = (LGD_secured * secured_portion + LGD_unsecured * unsecured_portion) / EAD
        exposures = exposures.with_columns([
            pl.when(
                (pl.col("approach") == ApproachType.FIRB.value) &
                (pl.col("ead_gross") > 0) &
                (pl.col("total_collateral_for_lgd") > 0)
            ).then(
                # Weighted average LGD
                (
                    (pl.col("lgd_secured") * pl.col("total_collateral_for_lgd").clip(upper_bound=pl.col("ead_gross"))) +
                    (pl.col("lgd_unsecured") * (pl.col("ead_gross") - pl.col("total_collateral_for_lgd")).clip(lower_bound=0))
                ) / pl.col("ead_gross")
            )
            .when(
                (pl.col("approach") == ApproachType.FIRB.value) &
                (pl.col("ead_gross") > 0)
            ).then(
                # No collateral: use unsecured LGD
                pl.col("lgd_unsecured")
            )
            .otherwise(
                # A-IRB or other: keep modelled LGD
                pl.col("lgd_pre_crm")
            )
            .alias("lgd_post_crm"),
        ])

        # Add audit columns for LGD calculation
        exposures = exposures.with_columns([
            # Secured percentage for audit
            pl.when(pl.col("ead_gross") > 0)
            .then(
                (pl.col("total_collateral_for_lgd").clip(upper_bound=pl.col("ead_gross")) / pl.col("ead_gross") * 100)
            )
            .otherwise(pl.lit(0.0))
            .alias("collateral_coverage_pct"),
        ])

        return exposures

    def _apply_firb_supervisory_lgd_no_collateral(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Apply F-IRB supervisory LGD when no collateral is available.

        For F-IRB exposures without collateral, uses supervisory LGD values:
        - Senior unsecured: 45%
        - Subordinated: 75%

        A-IRB exposures keep their modelled LGD.

        Args:
            exposures: Exposures with lgd_pre_crm

        Returns:
            Exposures with lgd_post_crm set for F-IRB
        """
        # Add collateral-related columns with zero values for consistency
        exposures = exposures.with_columns([
            pl.lit(0.0).alias("total_collateral_for_lgd"),
            pl.lit(0.0).alias("collateral_coverage_pct"),
        ])

        # Check if seniority column exists
        schema_names = set(exposures.collect_schema().names())
        if "seniority" in schema_names:
            # Determine LGD based on seniority for F-IRB
            exposures = exposures.with_columns([
                pl.when(
                    (pl.col("approach") == ApproachType.FIRB.value) &
                    (pl.col("seniority").fill_null("").str.to_lowercase().is_in(["subordinated", "junior"]))
                ).then(pl.lit(0.75))  # Subordinated
                .when(pl.col("approach") == ApproachType.FIRB.value)
                .then(pl.lit(0.45))  # Senior unsecured
                .otherwise(pl.col("lgd_pre_crm"))  # A-IRB or SA: keep existing
                .alias("lgd_post_crm"),
            ])
        else:
            # No seniority column: use 45% for all F-IRB (senior unsecured default)
            exposures = exposures.with_columns([
                pl.when(pl.col("approach") == ApproachType.FIRB.value)
                .then(pl.lit(0.45))  # Senior unsecured
                .otherwise(pl.col("lgd_pre_crm"))  # A-IRB or SA: keep existing
                .alias("lgd_post_crm"),
            ])

        return exposures

    def _allocate_collateral_multi_level_for_lgd(
        self,
        exposures: pl.LazyFrame,
        collateral: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Allocate collateral from multiple linking levels for LGD calculation.

        Supports three levels of collateral linking based on beneficiary_type:
        1. Direct (exposure/loan): beneficiary_reference matches exposure_reference
        2. Facility: beneficiary_reference matches parent_facility_reference
        3. Counterparty: beneficiary_reference matches counterparty_reference

        Tracks financial and non-financial collateral separately to apply:
        - Overcollateralisation ratios (CRR Art. 230 / CRE32.9-12)
        - Minimum collateralisation thresholds (30% for RE/other physical)

        Args:
            exposures: Exposures with ead_gross, parent_facility_reference, counterparty_reference
            collateral: Collateral with beneficiary_type, adjusted_value, effectively_secured,
                        collateral_lgd, is_financial_collateral_type

        Returns:
            Exposures with total_collateral_for_lgd and lgd_secured columns
        """
        # Helper to aggregate collateral by level, split by financial/non-financial
        def aggregate_by_level(coll: pl.LazyFrame, level: str) -> pl.LazyFrame:
            """Aggregate collateral values and weighted LGD for a specific beneficiary level."""
            level_filter = ["exposure", "loan"] if level == "direct" else [level]
            is_fin = pl.col("is_financial_collateral_type")
            return coll.filter(
                pl.col("beneficiary_type").str.to_lowercase().is_in(level_filter)
            ).group_by("beneficiary_reference").agg([
                # Financial collateral
                pl.col("effectively_secured").filter(is_fin).sum().alias(f"eff_fin_{level}"),
                (pl.col("effectively_secured") * pl.col("collateral_lgd")).filter(is_fin).sum().alias(f"wlgd_fin_{level}"),
                # Non-financial collateral
                pl.col("effectively_secured").filter(~is_fin).sum().alias(f"eff_nf_{level}"),
                (pl.col("effectively_secured") * pl.col("collateral_lgd")).filter(~is_fin).sum().alias(f"wlgd_nf_{level}"),
                # Raw non-financial (for min threshold check)
                pl.col("adjusted_value").filter(~is_fin).sum().alias(f"raw_nf_{level}"),
            ])

        # Aggregate at each level
        coll_direct = aggregate_by_level(collateral, "direct")
        coll_facility = aggregate_by_level(collateral, "facility")
        coll_counterparty = aggregate_by_level(collateral, "counterparty")

        # Calculate EAD totals for pro-rata allocation
        facility_ead_totals = exposures.filter(
            pl.col("parent_facility_reference").is_not_null()
        ).group_by("parent_facility_reference").agg([
            pl.col("ead_gross").sum().alias("facility_ead_total"),
        ])

        counterparty_ead_totals = exposures.group_by("counterparty_reference").agg([
            pl.col("ead_gross").sum().alias("cp_ead_total"),
        ])

        # Join direct-level collateral
        exposures = exposures.join(
            coll_direct,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        )

        # Join facility-level collateral and totals
        exposures = exposures.join(
            coll_facility,
            left_on="parent_facility_reference",
            right_on="beneficiary_reference",
            how="left",
        ).join(
            facility_ead_totals,
            on="parent_facility_reference",
            how="left",
        )

        # Join counterparty-level collateral and totals
        exposures = exposures.join(
            coll_counterparty,
            left_on="counterparty_reference",
            right_on="beneficiary_reference",
            how="left",
        ).join(
            counterparty_ead_totals,
            on="counterparty_reference",
            how="left",
        )

        # Fill nulls for all aggregate columns
        fill_cols = []
        for level in ["direct", "facility", "counterparty"]:
            for prefix in ["eff_fin_", "wlgd_fin_", "eff_nf_", "wlgd_nf_", "raw_nf_"]:
                fill_cols.append(pl.col(f"{prefix}{level}").fill_null(0.0))
        fill_cols.extend([
            pl.col("facility_ead_total").fill_null(0.0),
            pl.col("cp_ead_total").fill_null(0.0),
        ])
        exposures = exposures.with_columns(fill_cols)

        # Calculate allocation weights for pro-rata distribution
        exposures = exposures.with_columns([
            pl.when(pl.col("facility_ead_total") > 0)
            .then(pl.col("ead_gross") / pl.col("facility_ead_total"))
            .otherwise(pl.lit(0.0))
            .alias("facility_weight"),
            pl.when(pl.col("cp_ead_total") > 0)
            .then(pl.col("ead_gross") / pl.col("cp_ead_total"))
            .otherwise(pl.lit(0.0))
            .alias("cp_weight"),
        ])

        # Allocate financial collateral (no min threshold)
        exposures = exposures.with_columns([
            (
                pl.col("eff_fin_direct") +
                (pl.col("eff_fin_facility") * pl.col("facility_weight")) +
                (pl.col("eff_fin_counterparty") * pl.col("cp_weight"))
            ).alias("eff_fin_allocated"),
            (
                pl.col("wlgd_fin_direct") +
                (pl.col("wlgd_fin_facility") * pl.col("facility_weight")) +
                (pl.col("wlgd_fin_counterparty") * pl.col("cp_weight"))
            ).alias("wlgd_fin_allocated"),
        ])

        # Allocate non-financial collateral
        exposures = exposures.with_columns([
            (
                pl.col("eff_nf_direct") +
                (pl.col("eff_nf_facility") * pl.col("facility_weight")) +
                (pl.col("eff_nf_counterparty") * pl.col("cp_weight"))
            ).alias("eff_nf_allocated"),
            (
                pl.col("wlgd_nf_direct") +
                (pl.col("wlgd_nf_facility") * pl.col("facility_weight")) +
                (pl.col("wlgd_nf_counterparty") * pl.col("cp_weight"))
            ).alias("wlgd_nf_allocated"),
            # Raw non-financial for min threshold check
            (
                pl.col("raw_nf_direct") +
                (pl.col("raw_nf_facility") * pl.col("facility_weight")) +
                (pl.col("raw_nf_counterparty") * pl.col("cp_weight"))
            ).alias("raw_nf_allocated"),
        ])

        # Apply min threshold: if raw non-financial < 30% of EAD, zero out non-financial
        exposures = exposures.with_columns([
            pl.when(pl.col("raw_nf_allocated") >= 0.30 * pl.col("ead_gross"))
            .then(pl.col("eff_nf_allocated"))
            .otherwise(pl.lit(0.0))
            .alias("eff_nf_final"),
            pl.when(pl.col("raw_nf_allocated") >= 0.30 * pl.col("ead_gross"))
            .then(pl.col("wlgd_nf_allocated"))
            .otherwise(pl.lit(0.0))
            .alias("wlgd_nf_final"),
        ])

        # Combine financial + non-financial
        exposures = exposures.with_columns([
            (pl.col("eff_fin_allocated") + pl.col("eff_nf_final"))
            .alias("total_collateral_for_lgd"),
            (pl.col("wlgd_fin_allocated") + pl.col("wlgd_nf_final"))
            .alias("total_weighted_lgd_sum"),
        ])

        # Calculate average LGD for secured portion
        exposures = exposures.with_columns([
            pl.when(pl.col("total_collateral_for_lgd") > 0)
            .then(pl.col("total_weighted_lgd_sum") / pl.col("total_collateral_for_lgd"))
            .otherwise(pl.lit(0.45))
            .alias("lgd_secured"),
        ])

        # Drop intermediate columns
        drop_cols = []
        for level in ["direct", "facility", "counterparty"]:
            for prefix in ["eff_fin_", "wlgd_fin_", "eff_nf_", "wlgd_nf_", "raw_nf_"]:
                drop_cols.append(f"{prefix}{level}")
        drop_cols.extend([
            "facility_ead_total", "cp_ead_total",
            "facility_weight", "cp_weight",
            "eff_fin_allocated", "wlgd_fin_allocated",
            "eff_nf_allocated", "wlgd_nf_allocated",
            "raw_nf_allocated", "eff_nf_final", "wlgd_nf_final",
            "total_weighted_lgd_sum",
        ])
        exposures = exposures.drop(drop_cols)

        return exposures

    def _allocate_collateral_multi_level_for_ead(
        self,
        exposures: pl.LazyFrame,
        eligible_collateral: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Allocate eligible financial collateral from multiple linking levels for SA EAD reduction.

        Supports three levels of collateral linking based on beneficiary_type:
        1. Direct (exposure/loan): beneficiary_reference matches exposure_reference
        2. Facility: beneficiary_reference matches parent_facility_reference (pro-rata by EAD)
        3. Counterparty: beneficiary_reference matches counterparty_reference (pro-rata by EAD)

        Args:
            exposures: Exposures with ead_gross, parent_facility_reference, counterparty_reference
            eligible_collateral: Eligible financial collateral with beneficiary_type,
                                 value_after_maturity_adj/value_after_haircut, market_value

        Returns:
            Exposures with collateral_adjusted_value and collateral_market_value columns
        """
        # Value expression: prefer maturity-adjusted, fallback to haircut
        val_expr = pl.coalesce(
            pl.col("value_after_maturity_adj"),
            pl.col("value_after_haircut"),
        )

        bt_lower = pl.col("beneficiary_type").str.to_lowercase()
        direct_types = ["exposure", "loan", "contingent"]

        # --- Aggregate at each level ---
        coll_direct = eligible_collateral.filter(
            bt_lower.is_in(direct_types)
        ).group_by("beneficiary_reference").agg([
            val_expr.sum().alias("_coll_direct"),
            pl.col("market_value").sum().alias("_mv_direct"),
        ])

        coll_facility = eligible_collateral.filter(
            bt_lower == "facility"
        ).group_by("beneficiary_reference").agg([
            val_expr.sum().alias("_coll_facility"),
            pl.col("market_value").sum().alias("_mv_facility"),
        ])

        coll_counterparty = eligible_collateral.filter(
            bt_lower == "counterparty"
        ).group_by("beneficiary_reference").agg([
            val_expr.sum().alias("_coll_counterparty"),
            pl.col("market_value").sum().alias("_mv_counterparty"),
        ])

        # --- EAD totals for pro-rata allocation ---
        exp_schema = exposures.collect_schema()
        if "parent_facility_reference" in exp_schema.names():
            facility_ead_totals = exposures.filter(
                pl.col("parent_facility_reference").is_not_null()
            ).group_by("parent_facility_reference").agg(
                pl.col("ead_gross").sum().alias("_fac_ead_total"),
            )
        else:
            facility_ead_totals = pl.LazyFrame(
                schema={"parent_facility_reference": pl.String, "_fac_ead_total": pl.Float64}
            )

        cp_ead_totals = exposures.group_by("counterparty_reference").agg(
            pl.col("ead_gross").sum().alias("_cp_ead_total"),
        )

        # --- Join direct-level ---
        exposures = exposures.join(
            coll_direct,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        )

        # --- Join facility-level and totals ---
        if "parent_facility_reference" in exp_schema.names():
            exposures = exposures.join(
                coll_facility,
                left_on="parent_facility_reference",
                right_on="beneficiary_reference",
                how="left",
            ).join(
                facility_ead_totals,
                on="parent_facility_reference",
                how="left",
            )
        else:
            exposures = exposures.with_columns([
                pl.lit(0.0).alias("_coll_facility"),
                pl.lit(0.0).alias("_mv_facility"),
                pl.lit(0.0).alias("_fac_ead_total"),
            ])

        # --- Join counterparty-level and totals ---
        exposures = exposures.join(
            coll_counterparty,
            left_on="counterparty_reference",
            right_on="beneficiary_reference",
            how="left",
        ).join(
            cp_ead_totals,
            on="counterparty_reference",
            how="left",
        )

        # --- Fill nulls ---
        exposures = exposures.with_columns([
            pl.col("_coll_direct").fill_null(0.0),
            pl.col("_mv_direct").fill_null(0.0),
            pl.col("_coll_facility").fill_null(0.0),
            pl.col("_mv_facility").fill_null(0.0),
            pl.col("_coll_counterparty").fill_null(0.0),
            pl.col("_mv_counterparty").fill_null(0.0),
            pl.col("_fac_ead_total").fill_null(0.0),
            pl.col("_cp_ead_total").fill_null(0.0),
        ])

        # --- Pro-rata weights ---
        exposures = exposures.with_columns([
            pl.when(pl.col("_fac_ead_total") > 0)
            .then(pl.col("ead_gross") / pl.col("_fac_ead_total"))
            .otherwise(pl.lit(0.0))
            .alias("_fac_weight"),
            pl.when(pl.col("_cp_ead_total") > 0)
            .then(pl.col("ead_gross") / pl.col("_cp_ead_total"))
            .otherwise(pl.lit(0.0))
            .alias("_cp_weight"),
        ])

        # --- Combine all levels ---
        exposures = exposures.with_columns([
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

        # --- Drop intermediate columns ---
        exposures = exposures.drop([
            "_coll_direct", "_mv_direct",
            "_coll_facility", "_mv_facility",
            "_coll_counterparty", "_mv_counterparty",
            "_fac_ead_total", "_cp_ead_total",
            "_fac_weight", "_cp_weight",
        ])

        return exposures

    def apply_guarantees(
        self,
        exposures: pl.LazyFrame,
        guarantees: pl.LazyFrame,
        counterparty_lookup: pl.LazyFrame,
        config: CalculationConfig,
        rating_inheritance: pl.LazyFrame | None = None,
    ) -> pl.LazyFrame:
        """
        Apply guarantee substitution.

        For guaranteed portion, substitute borrower RW with guarantor RW.

        Args:
            exposures: Exposures with EAD
            guarantees: Guarantee data
            counterparty_lookup: For guarantor risk weights
            config: Calculation configuration
            rating_inheritance: For guarantor CQS lookup

        Returns:
            Exposures with guarantee effects applied
        """
        # Aggregate guarantees by beneficiary
        guarantees_by_exposure = guarantees.group_by(
            "beneficiary_reference"
        ).agg([
            pl.col("amount_covered").sum().alias("total_guarantee_amount"),
            pl.col("percentage_covered").first().alias("percentage_covered"),
            pl.col("guarantor").first().alias("primary_guarantor"),
            pl.len().alias("guarantee_count"),
        ])

        # Join guarantees to exposures
        exposures = exposures.join(
            guarantees_by_exposure,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        )

        # Calculate effective guarantee amount
        # If amount_covered is null/0 but percentage_covered is provided, derive from EAD
        # percentage_covered: 1 = 100%, 0.5 = 50%
        exposures = exposures.with_columns([
            pl.when(
                (pl.col("total_guarantee_amount").is_null() | (pl.col("total_guarantee_amount") == 0)) &
                (pl.col("percentage_covered").is_not_null()) &
                (pl.col("percentage_covered") > 0)
            )
            .then(pl.col("percentage_covered") * pl.col("ead_after_collateral"))
            .otherwise(pl.col("total_guarantee_amount").fill_null(0.0))
            .alias("guarantee_amount"),
            pl.col("primary_guarantor").alias("guarantor_reference"),
        ])

        # Calculate guaranteed vs unguaranteed portions
        exposures = exposures.with_columns([
            # Guaranteed amount (capped at EAD)
            pl.min_horizontal(
                pl.col("guarantee_amount"),
                pl.col("ead_after_collateral")
            ).alias("guaranteed_portion"),
        ])

        exposures = exposures.with_columns([
            # Unguaranteed portion
            (
                pl.col("ead_after_collateral") - pl.col("guaranteed_portion")
            ).alias("unguaranteed_portion"),
        ])

        # Look up guarantor's entity type and CQS for risk weight substitution
        # Join with counterparty to get guarantor's entity type
        exposures = exposures.join(
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

            exposures = exposures.join(
                rating_inheritance.select(ri_cols),
                left_on="guarantor_reference",
                right_on="counterparty_reference",
                how="left",
            )

            if "rating_type" not in ri_schema.names():
                exposures = exposures.with_columns([
                    pl.lit(None).cast(pl.String).alias("guarantor_rating_type"),
                ])
        else:
            exposures = exposures.with_columns([
                pl.lit(None).cast(pl.Int8).alias("guarantor_cqs"),
                pl.lit(None).cast(pl.String).alias("guarantor_rating_type"),
            ])

        # Fill nulls for exposures without guarantees
        exposures = exposures.with_columns([
            pl.col("guarantor_entity_type").fill_null("").alias("guarantor_entity_type"),
        ])

        # Derive guarantor's exposure class from their entity type
        # This is needed for post-CRM reporting where the guaranteed portion
        # is reported under the guarantor's exposure class
        exposures = exposures.with_columns([
            pl.col("guarantor_entity_type")
            .replace_strict(ENTITY_TYPE_TO_SA_CLASS, default="")
            .alias("guarantor_exposure_class"),
        ])

        # Determine guarantor approach from IRB permissions AND rating type.
        # A guarantor is treated under IRB only if:
        # 1. The firm has IRB permission for the guarantor's exposure class, AND
        # 2. The guarantor has an internal rating (PD) — indicating the firm
        #    actively rates this counterparty under its IRB model.
        # Counterparties with only external ratings (CQS) are treated under SA.
        irb_exposure_class_values = set()
        for ec, approaches in config.irb_permissions.permissions.items():
            if ApproachType.FIRB in approaches or ApproachType.AIRB in approaches:
                irb_exposure_class_values.add(ec.value)

        exposures = exposures.with_columns([
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

        # Cross-approach CCF substitution (CRR Art. 111 / COREP C07)
        # When IRB exposure guaranteed by SA counterparty, use SA CCFs for guaranteed portion
        exposures = self._apply_cross_approach_ccf(exposures)

        # Add post-CRM composite attributes for regulatory reporting
        # For the guaranteed portion, the post-CRM counterparty is the guarantor
        exposures = exposures.with_columns([
            # Post-CRM counterparty for guaranteed portion (guarantor or original)
            pl.when(pl.col("guaranteed_portion") > 0)
            .then(pl.col("guarantor_reference"))
            .otherwise(pl.col("counterparty_reference"))
            .alias("post_crm_counterparty_guaranteed"),

            # Post-CRM exposure class for guaranteed portion (guarantor's class or original)
            pl.when(
                (pl.col("guaranteed_portion") > 0) &
                (pl.col("guarantor_exposure_class") != "")
            )
            .then(pl.col("guarantor_exposure_class"))
            .otherwise(pl.col("exposure_class"))
            .alias("post_crm_exposure_class_guaranteed"),

            # Flag indicating whether exposure has an effective guarantee
            (pl.col("guaranteed_portion") > 0).alias("is_guaranteed"),
        ])

        # Note: Transient columns (guarantor_entity_type, guarantor_cqs, etc.) are kept
        # because downstream SA/IRB calculators need them for risk weight substitution.
        # They can be dropped in the final output aggregation if needed.

        return exposures

    def _apply_cross_approach_ccf(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Apply cross-approach CCF substitution for guaranteed exposures.

        When an IRB exposure (F-IRB or A-IRB) is guaranteed by an SA counterparty,
        the guaranteed portion must use SA CCFs for COREP C07 reporting.
        If the guarantor is also IRB, the original IRB CCF is retained.

        This recalculates EAD by splitting on-balance-sheet and off-balance-sheet
        amounts proportionally by guarantee_ratio, applying the appropriate CCF
        to each nominal split.

        Returns:
            Exposures with CCF-adjusted guaranteed/unguaranteed portions
        """
        schema = exposures.collect_schema()
        has_interest = "interest" in schema.names()
        has_risk_type = "risk_type" in schema.names()

        if not has_risk_type:
            return exposures

        # Compute guarantee ratio
        exposures = exposures.with_columns([
            pl.when(pl.col("ead_after_collateral") > 0)
            .then(
                (pl.col("guaranteed_portion") / pl.col("ead_after_collateral"))
                .clip(upper_bound=1.0)
            )
            .otherwise(pl.lit(0.0))
            .alias("guarantee_ratio"),
        ])

        # Determine if cross-approach substitution is needed
        # Only IRB exposures with SA guarantors and off-balance-sheet items
        needs_ccf_sub = (
            pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value]) &
            (pl.col("guarantor_approach") == "sa") &
            (pl.col("guaranteed_portion") > 0) &
            (pl.col("nominal_amount") > 0)
        )

        # Compute SA CCF for the guaranteed portion
        sa_ccf = sa_ccf_expression()

        exposures = exposures.with_columns([
            # Preserve original CCF
            pl.col("ccf").alias("ccf_original"),
            # CCF for guaranteed portion: SA CCF if cross-approach, else original
            pl.when(needs_ccf_sub)
            .then(sa_ccf)
            .otherwise(pl.col("ccf"))
            .alias("ccf_guaranteed"),
            # CCF for unguaranteed portion: always original
            pl.col("ccf").alias("ccf_unguaranteed"),
        ])

        # Recalculate EAD with split CCFs when cross-approach substitution applies
        # Use provision-adjusted on-balance and nominal when available
        has_provision_cols = "provision_on_drawn" in schema.names()

        if has_provision_cols and has_interest:
            on_bal = (
                drawn_for_ead() - pl.col("provision_on_drawn")
            ).clip(lower_bound=0.0) + pl.col("interest").fill_null(0.0)
        elif has_provision_cols:
            on_bal = (
                drawn_for_ead() - pl.col("provision_on_drawn")
            ).clip(lower_bound=0.0)
        elif has_interest:
            on_bal = on_balance_ead()
        else:
            on_bal = drawn_for_ead()

        # Use nominal_after_provision if available, else nominal_amount
        nominal_col = (
            pl.col("nominal_after_provision")
            if "nominal_after_provision" in schema.names()
            else pl.col("nominal_amount")
        )
        ratio = pl.col("guarantee_ratio")

        new_guaranteed = (on_bal * ratio) + (nominal_col * ratio * pl.col("ccf_guaranteed"))
        new_unguaranteed = (on_bal * (pl.lit(1.0) - ratio)) + (
            nominal_col * (pl.lit(1.0) - ratio) * pl.col("ccf_unguaranteed")
        )

        exposures = exposures.with_columns([
            pl.when(needs_ccf_sub)
            .then(new_guaranteed)
            .otherwise(pl.col("guaranteed_portion"))
            .alias("guaranteed_portion"),

            pl.when(needs_ccf_sub)
            .then(new_unguaranteed)
            .otherwise(pl.col("unguaranteed_portion"))
            .alias("unguaranteed_portion"),
        ])

        # Update ead_after_collateral and ead_from_ccf when substitution occurs
        exposures = exposures.with_columns([
            pl.when(needs_ccf_sub)
            .then(pl.col("guaranteed_portion") + pl.col("unguaranteed_portion"))
            .otherwise(pl.col("ead_after_collateral"))
            .alias("ead_after_collateral"),

            pl.when(needs_ccf_sub)
            .then(
                nominal_col * ratio * pl.col("ccf_guaranteed")
                + nominal_col * (pl.lit(1.0) - ratio) * pl.col("ccf_unguaranteed")
            )
            .otherwise(pl.col("ead_from_ccf"))
            .alias("ead_from_ccf"),
        ])

        return exposures

    def resolve_provisions(
        self,
        exposures: pl.LazyFrame,
        provisions: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Resolve provisions with multi-level beneficiary and drawn-first deduction.

        This is called *before* CCF so that nominal_after_provision feeds into
        the CCF calculation: ``ead_from_ccf = nominal_after_provision * ccf``.

        Resolution levels (based on beneficiary_type):
        1. Direct (loan/exposure/contingent): join on exposure_reference
        2. Facility: join on parent_facility_reference, pro-rata by exposure weight
        3. Counterparty: join on counterparty_reference, pro-rata by exposure weight

        SA drawn-first deduction (CRR Art. 111(2)):
        - ``floored_drawn = max(0, drawn_amount)``
        - ``provision_on_drawn = min(provision_allocated, floored_drawn)``
        - ``provision_on_nominal = min(remainder, nominal_amount)``
        - Interest is never reduced by provision.

        IRB/Slotting: provision_on_drawn=0, provision_on_nominal=0 (provisions
        feed into EL shortfall/excess instead). provision_allocated is tracked.

        Args:
            exposures: Exposures with drawn_amount, interest, nominal_amount, approach
            provisions: Provision data with beneficiary_reference, amount,
                        and optionally beneficiary_type
            config: Calculation configuration

        Returns:
            Exposures with provision_allocated, provision_on_drawn,
            provision_on_nominal, provision_deducted, nominal_after_provision
        """
        prov_schema = provisions.collect_schema()
        exp_schema = exposures.collect_schema()
        has_beneficiary_type = "beneficiary_type" in prov_schema.names()
        has_parent_facility = "parent_facility_reference" in exp_schema.names()

        if has_beneficiary_type:
            exposures = self._resolve_provisions_multi_level(
                exposures, provisions, has_parent_facility
            )
        else:
            # Fallback: direct-only join (backward compat)
            provisions_agg = provisions.group_by("beneficiary_reference").agg(
                pl.col("amount").sum().alias("provision_allocated"),
            )
            exposures = exposures.join(
                provisions_agg,
                left_on="exposure_reference",
                right_on="beneficiary_reference",
                how="left",
            ).with_columns(
                pl.col("provision_allocated").fill_null(0.0),
            )

        # --- SA drawn-first deduction; IRB/Slotting: no deduction ---
        is_sa = pl.col("approach") == ApproachType.SA.value

        floored_drawn = pl.col("drawn_amount").clip(lower_bound=0.0)

        # provision_on_drawn: min(allocated, floored_drawn) for SA; 0 for IRB
        provision_on_drawn = (
            pl.when(is_sa)
            .then(pl.min_horizontal("provision_allocated", floored_drawn))
            .otherwise(pl.lit(0.0))
        )

        exposures = exposures.with_columns(
            provision_on_drawn.alias("provision_on_drawn"),
        )

        # provision_on_nominal: min(remaining, nominal) for SA; 0 for IRB
        remaining = (pl.col("provision_allocated") - pl.col("provision_on_drawn")).clip(lower_bound=0.0)
        provision_on_nominal = (
            pl.when(is_sa)
            .then(pl.min_horizontal(remaining, pl.col("nominal_amount")))
            .otherwise(pl.lit(0.0))
        )

        exposures = exposures.with_columns(
            provision_on_nominal.alias("provision_on_nominal"),
        )

        # provision_deducted = on_drawn + on_nominal
        exposures = exposures.with_columns(
            (pl.col("provision_on_drawn") + pl.col("provision_on_nominal"))
            .alias("provision_deducted"),
        )

        # nominal_after_provision for CCF: nominal - provision_on_nominal
        exposures = exposures.with_columns(
            (pl.col("nominal_amount") - pl.col("provision_on_nominal"))
            .alias("nominal_after_provision"),
        )

        return exposures

    def _resolve_provisions_multi_level(
        self,
        exposures: pl.LazyFrame,
        provisions: pl.LazyFrame,
        has_parent_facility: bool,
    ) -> pl.LazyFrame:
        """
        Resolve provisions from direct, facility, and counterparty levels.

        For facility and counterparty levels, provisions are allocated pro-rata
        based on ``max(0, drawn) + interest + nominal`` as the weight proxy.

        Args:
            exposures: Exposures LazyFrame
            provisions: Provisions with beneficiary_type column
            has_parent_facility: Whether exposures have parent_facility_reference

        Returns:
            Exposures with provision_allocated column added
        """
        bt_lower = pl.col("beneficiary_type").str.to_lowercase()

        # --- 1. Direct-level provisions ---
        direct_types = ["loan", "exposure", "contingent"]
        direct_provs = (
            provisions
            .filter(bt_lower.is_in(direct_types))
            .group_by("beneficiary_reference")
            .agg(pl.col("amount").sum().alias("_prov_direct"))
        )

        exposures = exposures.join(
            direct_provs,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        ).with_columns(pl.col("_prov_direct").fill_null(0.0))

        # --- Compute exposure weight for pro-rata allocation ---
        weight_expr = (
            pl.col("drawn_amount").clip(lower_bound=0.0)
            + pl.col("interest").fill_null(0.0)
            + pl.col("nominal_amount")
        )
        exposures = exposures.with_columns(weight_expr.alias("_exp_weight"))

        # --- 2. Facility-level provisions ---
        if has_parent_facility:
            fac_provs = (
                provisions
                .filter(bt_lower == "facility")
                .group_by("beneficiary_reference")
                .agg(pl.col("amount").sum().alias("_prov_facility"))
            )

            fac_totals = (
                exposures
                .filter(pl.col("parent_facility_reference").is_not_null())
                .group_by("parent_facility_reference")
                .agg(pl.col("_exp_weight").sum().alias("_fac_total_weight"))
            )

            exposures = (
                exposures
                .join(
                    fac_provs,
                    left_on="parent_facility_reference",
                    right_on="beneficiary_reference",
                    how="left",
                )
                .join(fac_totals, on="parent_facility_reference", how="left")
                .with_columns([
                    pl.col("_prov_facility").fill_null(0.0),
                    pl.col("_fac_total_weight").fill_null(0.0),
                ])
                .with_columns(
                    pl.when(pl.col("_fac_total_weight") > 0)
                    .then(
                        pl.col("_prov_facility")
                        * pl.col("_exp_weight")
                        / pl.col("_fac_total_weight")
                    )
                    .otherwise(pl.lit(0.0))
                    .alias("_prov_facility_alloc"),
                )
            )
        else:
            exposures = exposures.with_columns(pl.lit(0.0).alias("_prov_facility_alloc"))

        # --- 3. Counterparty-level provisions ---
        cp_provs = (
            provisions
            .filter(bt_lower == "counterparty")
            .group_by("beneficiary_reference")
            .agg(pl.col("amount").sum().alias("_prov_cp"))
        )

        cp_totals = (
            exposures
            .group_by("counterparty_reference")
            .agg(pl.col("_exp_weight").sum().alias("_cp_total_weight"))
        )

        exposures = (
            exposures
            .join(
                cp_provs,
                left_on="counterparty_reference",
                right_on="beneficiary_reference",
                how="left",
            )
            .join(cp_totals, on="counterparty_reference", how="left")
            .with_columns([
                pl.col("_prov_cp").fill_null(0.0),
                pl.col("_cp_total_weight").fill_null(0.0),
            ])
            .with_columns(
                pl.when(pl.col("_cp_total_weight") > 0)
                .then(
                    pl.col("_prov_cp")
                    * pl.col("_exp_weight")
                    / pl.col("_cp_total_weight")
                )
                .otherwise(pl.lit(0.0))
                .alias("_prov_cp_alloc"),
            )
        )

        # --- Combine all levels ---
        exposures = exposures.with_columns(
            (
                pl.col("_prov_direct")
                + pl.col("_prov_facility_alloc")
                + pl.col("_prov_cp_alloc")
            ).alias("provision_allocated"),
        )

        # --- Drop temporary columns ---
        drop_cols = [
            "_prov_direct", "_exp_weight",
            "_prov_facility_alloc", "_prov_cp_alloc",
            "_prov_cp", "_cp_total_weight",
        ]
        if has_parent_facility:
            drop_cols.extend(["_prov_facility", "_fac_total_weight"])
        exposures = exposures.drop(drop_cols)

        return exposures

    def apply_provisions(
        self,
        exposures: pl.LazyFrame,
        provisions: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply provision deduction from EAD (legacy method).

        Delegates to resolve_provisions for the full multi-level resolution
        and drawn-first deduction logic.

        Args:
            exposures: Exposures with EAD
            provisions: Provision data
            config: Calculation configuration

        Returns:
            Exposures with provision effects applied
        """
        return self.resolve_provisions(exposures, provisions, config)

    def _add_crm_audit(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Add CRM processing audit trail."""
        return exposures.with_columns([
            pl.concat_str([
                pl.lit("EAD: gross="),
                pl.col("ead_gross").round(0).cast(pl.String),
                pl.lit("; coll="),
                pl.col("collateral_adjusted_value").round(0).cast(pl.String),
                pl.lit("; guar="),
                pl.col("guarantee_amount").round(0).cast(pl.String),
                pl.lit("; prov="),
                pl.col("provision_allocated").round(0).cast(pl.String),
                pl.lit("; final="),
                pl.col("ead_final").round(0).cast(pl.String),
            ]).alias("crm_calculation"),
        ])

    def _build_crm_audit(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Build CRM audit trail for reporting."""
        return exposures.select([
            pl.col("exposure_reference"),
            pl.col("counterparty_reference"),
            pl.col("approach"),
            pl.col("ead_gross"),
            pl.col("ead_from_ccf"),
            pl.col("ccf"),
            pl.col("collateral_adjusted_value"),
            pl.col("guarantee_amount"),
            pl.col("provision_allocated"),
            pl.col("ead_final"),
            pl.col("lgd_pre_crm"),
            pl.col("lgd_post_crm"),
            pl.col("crm_calculation"),
            # Pre/Post CRM tracking columns
            pl.col("pre_crm_counterparty_reference"),
            pl.col("pre_crm_exposure_class"),
            pl.col("post_crm_counterparty_guaranteed"),
            pl.col("post_crm_exposure_class_guaranteed"),
            pl.col("is_guaranteed"),
            pl.col("guaranteed_portion"),
            pl.col("unguaranteed_portion"),
            pl.col("guarantor_reference"),
            # Cross-approach CCF columns
            pl.col("ccf_original"),
            pl.col("ccf_guaranteed"),
            pl.col("ccf_unguaranteed"),
            pl.col("guarantee_ratio"),
            pl.col("guarantor_approach"),
        ])


def create_crm_processor() -> CRMProcessor:
    """
    Create a CRM processor instance.

    Returns:
        CRMProcessor ready for use
    """
    return CRMProcessor()
