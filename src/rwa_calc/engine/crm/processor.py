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
from rwa_calc.engine.ccf import CCFCalculator
from rwa_calc.engine.crm.haircuts import HaircutCalculator
from rwa_calc.data.tables.crr_firb_lgd import get_firb_lgd_table

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

        # Step 1: Apply CCF to calculate EAD for contingents
        exposures = self._apply_ccf(exposures, config)

        # Step 2: Initialize EAD columns
        exposures = self._initialize_ead(exposures)

        # Step 3: Apply collateral (if available and valid)
        if self._is_valid_for_processing(data.collateral, self.COLLATERAL_REQUIRED_COLUMNS):
            exposures = self.apply_collateral(exposures, data.collateral, config)
        else:
            # No collateral: still need to set F-IRB supervisory LGD based on seniority
            exposures = self._apply_firb_supervisory_lgd_no_collateral(exposures)

        # Step 4: Apply guarantees (if available and valid)
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

        # Step 5: Apply provisions (if available and valid)
        if self._is_valid_for_processing(data.provisions, self.PROVISION_REQUIRED_COLUMNS):
            exposures = self.apply_provisions(exposures, data.provisions, config)

        # Step 6: Calculate final EAD after all CRM adjustments
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
        Initialize EAD columns.

        Sets up the EAD waterfall:
        - ead_gross: drawn + CCF-adjusted undrawn
        - ead_after_collateral: EAD after collateral
        - ead_after_guarantee: EAD after guarantee substitution
        - ead_after_provision: Final EAD after provision deduction
        """
        return exposures.with_columns([
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

            # Initialize provision-related columns
            pl.lit(0.0).alias("provision_allocated"),
            pl.lit(0.0).alias("provision_deducted"),

            # LGD for IRB (may be adjusted by collateral)
            pl.col("lgd").fill_null(0.45).alias("lgd_pre_crm"),
            pl.col("lgd").fill_null(0.45).alias("lgd_post_crm"),
        ])

    def _finalize_ead(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Finalize EAD after all CRM adjustments.

        Sets ead_final based on the CRM waterfall:
        - ead_after_collateral (after collateral reduction)
        - minus provision deduction

        Also updates ead_after_guarantee for audit trail.
        """
        # Use ead_after_collateral if it exists, otherwise ead_gross
        return exposures.with_columns([
            # Set final EAD after provisions
            (
                pl.col("ead_after_collateral") - pl.col("provision_deducted")
            ).clip(lower_bound=0).alias("ead_final"),
            # Copy to ead_after_guarantee for audit
            pl.col("ead_after_collateral").alias("ead_after_guarantee"),
        ])

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

        # Aggregate collateral by beneficiary
        # Use maturity-adjusted value if available, otherwise use haircut value
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

        # Join collateral to exposures
        exposures = exposures.join(
            collateral_by_exposure,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        )

        # Fill nulls for exposures without collateral
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
        collateral_with_lgd = collateral.with_columns([
            pl.when(
                pl.col("collateral_type").str.to_lowercase().is_in([
                    "cash", "deposit", "gold", "financial_collateral",
                    "government_bond", "corporate_bond", "equity"
                ])
            ).then(pl.lit(0.0))  # Financial collateral: 0%
            .when(
                pl.col("collateral_type").str.to_lowercase().is_in([
                    "receivables", "trade_receivables"
                ])
            ).then(pl.lit(0.35))  # Receivables: 35%
            .when(
                pl.col("collateral_type").str.to_lowercase().is_in([
                    "real_estate", "property", "rre", "cre",
                    "residential_re", "commercial_re",
                    "residential", "commercial",
                    "residential_property", "commercial_property"
                ])
            ).then(pl.lit(0.35))  # Real estate: 35%
            .when(
                pl.col("collateral_type").str.to_lowercase().is_in([
                    "other_physical", "equipment", "inventory", "other"
                ])
            ).then(pl.lit(0.40))  # Other physical: 40%
            .otherwise(pl.lit(0.45))  # Unknown: treat as unsecured
            .alias("collateral_lgd"),
        ])

        # Get adjusted collateral value (prefer maturity-adjusted, then haircut)
        collateral_with_lgd = collateral_with_lgd.with_columns([
            pl.coalesce(
                pl.col("value_after_maturity_adj") if "value_after_maturity_adj" in collateral_schema.names() else pl.lit(None),
                pl.col("value_after_haircut") if "value_after_haircut" in collateral_schema.names() else pl.lit(None),
                pl.col("market_value"),
            ).alias("adjusted_value"),
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
            collateral_by_exposure = collateral_with_lgd.group_by(
                "beneficiary_reference"
            ).agg([
                pl.col("adjusted_value").sum().alias("total_collateral_for_lgd"),
                (pl.col("adjusted_value") * pl.col("collateral_lgd")).sum().alias("weighted_lgd_sum"),
            ])

            collateral_by_exposure = collateral_by_exposure.with_columns([
                pl.when(pl.col("total_collateral_for_lgd") > 0)
                .then(pl.col("weighted_lgd_sum") / pl.col("total_collateral_for_lgd"))
                .otherwise(pl.lit(0.45))
                .alias("lgd_secured"),
            ])

            exposures = exposures.join(
                collateral_by_exposure.select([
                    pl.col("beneficiary_reference"),
                    pl.col("total_collateral_for_lgd"),
                    pl.col("lgd_secured"),
                ]),
                left_on="exposure_reference",
                right_on="beneficiary_reference",
                how="left",
            )

            exposures = exposures.with_columns([
                pl.col("total_collateral_for_lgd").fill_null(0.0),
                pl.col("lgd_secured").fill_null(0.45),
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

        For facility/counterparty level collateral, values are allocated pro-rata
        across exposures based on their EAD share at that level.

        Args:
            exposures: Exposures with ead_gross, parent_facility_reference, counterparty_reference
            collateral: Collateral with beneficiary_type, adjusted_value, collateral_lgd

        Returns:
            Exposures with total_collateral_for_lgd and lgd_secured columns
        """
        # Helper to aggregate collateral by level
        def aggregate_by_level(coll: pl.LazyFrame, level: str) -> pl.LazyFrame:
            """Aggregate collateral values and weighted LGD for a specific beneficiary level."""
            level_filter = ["exposure", "loan"] if level == "direct" else [level]
            return coll.filter(
                pl.col("beneficiary_type").str.to_lowercase().is_in(level_filter)
            ).group_by("beneficiary_reference").agg([
                pl.col("adjusted_value").sum().alias(f"coll_{level}"),
                (pl.col("adjusted_value") * pl.col("collateral_lgd")).sum().alias(f"wlgd_{level}"),
            ])

        # Aggregate at each level
        coll_direct = aggregate_by_level(collateral, "direct")
        coll_facility = aggregate_by_level(collateral, "facility")
        coll_counterparty = aggregate_by_level(collateral, "counterparty")

        # Calculate EAD totals for pro-rata allocation
        # Facility total: sum of EAD for all exposures under each facility
        facility_ead_totals = exposures.filter(
            pl.col("parent_facility_reference").is_not_null()
        ).group_by("parent_facility_reference").agg([
            pl.col("ead_gross").sum().alias("facility_ead_total"),
        ])

        # Counterparty total: sum of EAD for all exposures for each counterparty
        counterparty_ead_totals = exposures.group_by("counterparty_reference").agg([
            pl.col("ead_gross").sum().alias("cp_ead_total"),
        ])

        # Join direct-level collateral (full value to that exposure)
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

        # Fill nulls
        exposures = exposures.with_columns([
            pl.col("coll_direct").fill_null(0.0),
            pl.col("wlgd_direct").fill_null(0.0),
            pl.col("coll_facility").fill_null(0.0),
            pl.col("wlgd_facility").fill_null(0.0),
            pl.col("coll_counterparty").fill_null(0.0),
            pl.col("wlgd_counterparty").fill_null(0.0),
            pl.col("facility_ead_total").fill_null(0.0),
            pl.col("cp_ead_total").fill_null(0.0),
        ])

        # Calculate allocation weights for pro-rata distribution
        exposures = exposures.with_columns([
            # Facility allocation weight (exposure's EAD / facility total EAD)
            pl.when(pl.col("facility_ead_total") > 0)
            .then(pl.col("ead_gross") / pl.col("facility_ead_total"))
            .otherwise(pl.lit(0.0))
            .alias("facility_weight"),
            # Counterparty allocation weight (exposure's EAD / counterparty total EAD)
            pl.when(pl.col("cp_ead_total") > 0)
            .then(pl.col("ead_gross") / pl.col("cp_ead_total"))
            .otherwise(pl.lit(0.0))
            .alias("cp_weight"),
        ])

        # Calculate total allocated collateral and weighted LGD sum
        exposures = exposures.with_columns([
            # Total collateral: direct + (facility * weight) + (counterparty * weight)
            (
                pl.col("coll_direct") +
                (pl.col("coll_facility") * pl.col("facility_weight")) +
                (pl.col("coll_counterparty") * pl.col("cp_weight"))
            ).alias("total_collateral_for_lgd"),
            # Weighted LGD sum for calculating average LGD of secured portion
            (
                pl.col("wlgd_direct") +
                (pl.col("wlgd_facility") * pl.col("facility_weight")) +
                (pl.col("wlgd_counterparty") * pl.col("cp_weight"))
            ).alias("total_weighted_lgd_sum"),
        ])

        # Calculate average LGD for secured portion
        exposures = exposures.with_columns([
            pl.when(pl.col("total_collateral_for_lgd") > 0)
            .then(pl.col("total_weighted_lgd_sum") / pl.col("total_collateral_for_lgd"))
            .otherwise(pl.lit(0.45))  # Default to unsecured if no collateral
            .alias("lgd_secured"),
        ])

        # Drop intermediate columns
        exposures = exposures.drop([
            "coll_direct", "wlgd_direct",
            "coll_facility", "wlgd_facility",
            "coll_counterparty", "wlgd_counterparty",
            "facility_ead_total", "cp_ead_total",
            "facility_weight", "cp_weight",
            "total_weighted_lgd_sum",
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

        # Fill nulls
        exposures = exposures.with_columns([
            pl.col("total_guarantee_amount").fill_null(0.0).alias("guarantee_amount"),
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

        # Look up guarantor's CQS from ratings
        if rating_inheritance is not None:
            exposures = exposures.join(
                rating_inheritance.select([
                    pl.col("counterparty_reference"),
                    pl.col("cqs").alias("guarantor_cqs"),
                ]),
                left_on="guarantor_reference",
                right_on="counterparty_reference",
                how="left",
            )
        else:
            exposures = exposures.with_columns([
                pl.lit(None).cast(pl.Int8).alias("guarantor_cqs"),
            ])

        # Fill nulls for exposures without guarantees
        exposures = exposures.with_columns([
            pl.col("guarantor_entity_type").fill_null("").alias("guarantor_entity_type"),
        ])

        return exposures

    def apply_provisions(
        self,
        exposures: pl.LazyFrame,
        provisions: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply provision deduction from EAD.

        For SA, specific provisions are deducted from EAD.
        For IRB, provisions are compared to EL for shortfall/excess.

        Args:
            exposures: Exposures with EAD
            provisions: Provision data
            config: Calculation configuration

        Returns:
            Exposures with provision effects applied
        """
        # Aggregate provisions by beneficiary (exposure)
        provisions_by_exposure = provisions.group_by(
            "beneficiary_reference"
        ).agg([
            pl.col("amount").sum().alias("total_provision"),
            pl.col("provision_type").first().alias("primary_provision_type"),
        ])

        # Join provisions to exposures
        exposures = exposures.join(
            provisions_by_exposure,
            left_on="exposure_reference",
            right_on="beneficiary_reference",
            how="left",
        )

        # Fill nulls and update provision columns
        exposures = exposures.with_columns([
            pl.col("total_provision").fill_null(0.0).alias("provision_allocated"),
        ])

        # Calculate provision deduction (for SA, deduct from EAD)
        exposures = exposures.with_columns([
            pl.when(pl.col("approach") == ApproachType.SA.value)
            .then(pl.col("provision_allocated"))
            .otherwise(pl.lit(0.0))
            .alias("provision_deducted"),
        ])

        return exposures

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
        ])


def create_crm_processor() -> CRMProcessor:
    """
    Create a CRM processor instance.

    Returns:
        CRMProcessor ready for use
    """
    return CRMProcessor()
