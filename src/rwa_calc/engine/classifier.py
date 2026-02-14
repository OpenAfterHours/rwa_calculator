"""
Exposure classification for RWA calculator.

Classifies exposures by exposure class and calculation approach:
- Determines exposure class (central_govt_central_bank, institution, corporate, retail, etc.)
- Assigns calculation approach (SA, F-IRB, A-IRB, slotting)
- Checks SME and retail thresholds
- Identifies defaulted exposures
- Splits exposures by approach for downstream calculators

Classes:
    ExposureClassifier: Main classifier implementing ClassifierProtocol

Usage:
    from rwa_calc.engine.classifier import ExposureClassifier

    classifier = ExposureClassifier()
    classified = classifier.classify(resolved_data, config)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    ResolvedHierarchyBundle,
)
from rwa_calc.config.fx_rates import CRR_REGULATORY_THRESHOLDS_EUR
from rwa_calc.domain.enums import (
    ApproachType,
    ExposureClass,
    SlottingCategory,
    SpecialisedLendingType,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# ENTITY TYPE TO EXPOSURE CLASS MAPPINGS
# =============================================================================

# Valid entity_type values for validation — canonical source in schemas.py
from rwa_calc.data.schemas import VALID_ENTITY_TYPES

# entity_type → SA exposure class (for risk weight lookup)
ENTITY_TYPE_TO_SA_CLASS: dict[str, str] = {
    "sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "central_bank": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "rgla_sovereign": ExposureClass.RGLA.value,
    "rgla_institution": ExposureClass.RGLA.value,
    "pse_sovereign": ExposureClass.PSE.value,
    "pse_institution": ExposureClass.PSE.value,
    "mdb": ExposureClass.MDB.value,
    "international_org": ExposureClass.MDB.value,
    "institution": ExposureClass.INSTITUTION.value,
    "bank": ExposureClass.INSTITUTION.value,
    "ccp": ExposureClass.INSTITUTION.value,
    "financial_institution": ExposureClass.INSTITUTION.value,
    "corporate": ExposureClass.CORPORATE.value,
    "company": ExposureClass.CORPORATE.value,
    "individual": ExposureClass.RETAIL_OTHER.value,
    "retail": ExposureClass.RETAIL_OTHER.value,
    "specialised_lending": ExposureClass.SPECIALISED_LENDING.value,
    "equity": ExposureClass.EQUITY.value,
}

# entity_type → IRB exposure class (for IRB formula selection)
ENTITY_TYPE_TO_IRB_CLASS: dict[str, str] = {
    "sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "central_bank": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "rgla_sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,  # Central govt IRB treatment
    "rgla_institution": ExposureClass.INSTITUTION.value,  # Institution IRB treatment
    "pse_sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,  # Central govt IRB treatment
    "pse_institution": ExposureClass.INSTITUTION.value,  # Institution IRB treatment
    "mdb": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,  # Central govt IRB treatment (CRR Art. 147(3))
    "international_org": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,  # Central govt IRB treatment
    "institution": ExposureClass.INSTITUTION.value,
    "bank": ExposureClass.INSTITUTION.value,
    "ccp": ExposureClass.INSTITUTION.value,
    "financial_institution": ExposureClass.INSTITUTION.value,
    "corporate": ExposureClass.CORPORATE.value,
    "company": ExposureClass.CORPORATE.value,
    "individual": ExposureClass.RETAIL_OTHER.value,
    "retail": ExposureClass.RETAIL_OTHER.value,
    "specialised_lending": ExposureClass.SPECIALISED_LENDING.value,
    "equity": ExposureClass.EQUITY.value,
}

# Financial sector entity types (for FI scalar determination per CRR Art. 153(2))
# Note: MDB and international_org are excluded as they receive sovereign IRB treatment
FINANCIAL_SECTOR_ENTITY_TYPES: set[str] = {
    "institution",
    "bank",
    "ccp",
    "financial_institution",
    "pse_institution",  # PSE treated as institution = financial sector
    "rgla_institution",  # RGLA treated as institution = financial sector
}


@dataclass
class ClassificationError:
    """Error encountered during exposure classification."""

    error_type: str
    message: str
    exposure_reference: str | None = None
    context: dict = field(default_factory=dict)


class ExposureClassifier:
    """
    Classify exposures by exposure class and approach.

    Implements ClassifierProtocol for:
    - Mapping counterparty types to exposure classes
    - Checking SME criteria (turnover thresholds)
    - Checking retail criteria (aggregate exposure thresholds)
    - Determining IRB eligibility based on permissions
    - Identifying specialised lending for slotting
    - Splitting exposures by calculation approach

    All operations use Polars LazyFrames for deferred execution.
    """

    def classify(
        self,
        data: ResolvedHierarchyBundle,
        config: CalculationConfig,
    ) -> ClassifiedExposuresBundle:
        """
        Classify exposures and split by approach.

        Args:
            data: Hierarchy-resolved data from HierarchyResolver
            config: Calculation configuration

        Returns:
            ClassifiedExposuresBundle with exposures split by approach
        """
        errors: list[ClassificationError] = []

        # Step 1: Add counterparty attributes to exposures
        exposures_with_cp = self._add_counterparty_attributes(
            data.exposures,
            data.counterparty_lookup.counterparties,
        )

        # Step 2: Determine exposure class for each exposure
        classified = self._classify_exposure_class(
            exposures_with_cp,
            config,
        )

        # Step 3: Check and apply SME classification
        classified = self._apply_sme_classification(
            classified,
            config,
        )

        # Step 4: Check and apply retail classification
        classified = self._apply_retail_classification(
            classified,
            data.lending_group_totals,
            config,
        )

        # Step 4a: Check and apply corporate → retail reclassification
        # For qualifying SME corporates with modelled LGD under hybrid IRB permissions
        classified = self._apply_corporate_to_retail_reclassification(
            classified,
            config,
        )

        # Step 5: Identify defaulted exposures
        classified = self._identify_defaults(classified)

        # Step 5a: Identify infrastructure exposures
        classified = self._apply_infrastructure_classification(classified)

        # Step 5b: Derive FI scalar flags for IRB correlation adjustment
        classified = self._apply_fi_scalar_classification(classified, config)

        # Step 6: Determine calculation approach
        classified = self._determine_approach(
            classified,
            config,
        )

        # Step 6a: Clear internal LGD for FIRB exposures
        # FIRB uses supervisory LGD values, not internal models
        classified = self._clear_lgd_for_firb(classified)

        # Step 7: Add classification audit trail
        classified = self._add_classification_audit(classified)

        # Step 7a: Enrich slotting exposures with slotting metadata
        # This must happen before splitting so metadata flows through CRM processor
        classified = self._enrich_slotting_exposures(classified)

        # Strategic collect to materialize all classification processing
        # This breaks up the complex query plan for better downstream performance
        classified = classified.collect().lazy()

        # Step 8: Split by approach
        sa_exposures = self._filter_by_approach(classified, ApproachType.SA)
        irb_exposures = self._filter_irb_exposures(classified)
        slotting_exposures = self._filter_by_approach(classified, ApproachType.SLOTTING)

        # Build classification audit
        classification_audit = self._build_audit_trail(classified)

        return ClassifiedExposuresBundle(
            all_exposures=classified,
            sa_exposures=sa_exposures,
            irb_exposures=irb_exposures,
            slotting_exposures=slotting_exposures,
            equity_exposures=data.equity_exposures,
            collateral=data.collateral,
            guarantees=data.guarantees,
            provisions=data.provisions,
            counterparty_lookup=data.counterparty_lookup,
            classification_audit=classification_audit,
            classification_errors=errors,
        )

    def _add_counterparty_attributes(
        self,
        exposures: pl.LazyFrame,
        counterparties: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Add counterparty attributes needed for classification.

        Joins exposures with counterparty data to get:
        - entity_type (single source of truth for exposure class)
        - annual_revenue (for SME check)
        - total_assets (for large financial sector entity threshold)
        - default_status
        - country_code
        - is_regulated (for FI scalar - unregulated FSE)
        - is_managed_as_retail (for SME retail treatment)
        """
        # Select relevant counterparty columns
        cp_cols = counterparties.select([
            pl.col("counterparty_reference"),
            pl.col("entity_type").alias("cp_entity_type"),
            pl.col("country_code").alias("cp_country_code"),
            pl.col("annual_revenue").alias("cp_annual_revenue"),
            pl.col("total_assets").alias("cp_total_assets"),
            pl.col("default_status").alias("cp_default_status"),
            pl.col("is_regulated").alias("cp_is_regulated"),
            pl.col("is_managed_as_retail").alias("cp_is_managed_as_retail"),
        ])

        # Join with exposures
        return exposures.join(
            cp_cols,
            on="counterparty_reference",
            how="left",
        )

    def _classify_exposure_class(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Determine exposure class based on entity_type.

        Uses direct mapping from entity_type to exposure class via
        ENTITY_TYPE_TO_SA_CLASS and ENTITY_TYPE_TO_IRB_CLASS constants.

        Sets:
        - exposure_class: SA exposure class (for SA RW lookup, backwards compat)
        - exposure_class_sa: SA exposure class (explicit)
        - exposure_class_irb: IRB exposure class (for IRB formula selection)
        """
        return exposures.with_columns([
            # SA exposure class (used for SA risk weight lookup)
            pl.col("cp_entity_type")
            .replace_strict(ENTITY_TYPE_TO_SA_CLASS, default=ExposureClass.OTHER.value)
            .alias("exposure_class_sa"),

            # IRB exposure class (used for IRB formula selection)
            # Note: PSE/RGLA map to sovereign or institution based on entity_type suffix
            # MDB/international_org map to sovereign for IRB
            pl.col("cp_entity_type")
            .replace_strict(ENTITY_TYPE_TO_IRB_CLASS, default=ExposureClass.OTHER.value)
            .alias("exposure_class_irb"),

            # Unified exposure_class (SA class for backwards compatibility)
            pl.col("cp_entity_type")
            .replace_strict(ENTITY_TYPE_TO_SA_CLASS, default=ExposureClass.OTHER.value)
            .alias("exposure_class"),
        ])

    def _apply_sme_classification(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply SME classification for corporate exposures.

        SME criteria (CRR Art. 501):
        - Annual revenue < EUR 50m (GBP 44m at 0.88 FX rate)
        - Only applies to corporates

        CRR uses EUR thresholds, Basel 3.1 uses GBP.
        """
        # Convert EUR threshold to GBP
        sme_threshold_gbp = float(
            config.supporting_factors.sme_turnover_threshold_eur * config.eur_gbp_rate
        )

        return exposures.with_columns([
            # SME flag
            pl.when(
                (pl.col("exposure_class") == ExposureClass.CORPORATE.value) &
                (pl.col("cp_annual_revenue") < sme_threshold_gbp) &
                (pl.col("cp_annual_revenue") > 0)  # Exclude missing/zero revenue
            ).then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("is_sme"),

            # Update exposure class for SME corporates
            pl.when(
                (pl.col("exposure_class") == ExposureClass.CORPORATE.value) &
                (pl.col("cp_annual_revenue") < sme_threshold_gbp) &
                (pl.col("cp_annual_revenue") > 0)
            ).then(pl.lit(ExposureClass.CORPORATE_SME.value))
            .otherwise(pl.col("exposure_class"))
            .alias("exposure_class"),
        ])

    def _apply_retail_classification(
        self,
        exposures: pl.LazyFrame,
        lending_group_totals: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply retail classification and threshold checks.

        Retail criteria (CRR Art. 123, Basel 3.1 CRE20.65-70):
        - Aggregated exposure to lending group < threshold (EUR 1m / GBP 880k)
        - Exposures secured by residential property are EXCLUDED from threshold
          calculation per CRR Art. 123(c) (SA treatment only)

        Threshold treatment by approach:
        - SA residential mortgages: Stay as RETAIL_MORTGAGE regardless of threshold
          (assigned to Article 112(i) residential property class)
        - IRB SMEs exceeding threshold: Reclassify to CORPORATE_SME
        - Other retail exceeding threshold: Reclassify to CORPORATE

        Mortgage classification:
        - Product type indicates mortgage/home loan, OR
        - Secured by immovable property (residential or commercial)
        """
        max_retail_exposure = float(config.retail_thresholds.max_exposure_threshold)

        # Check schema for property collateral columns
        schema = exposures.collect_schema()
        schema_names = set(schema.names())
        has_property_col = "property_collateral_value" in schema_names
        has_facility_property_flag = "has_facility_property_collateral" in schema_names

        # First, apply mortgage classification (needed for exclusion logic)
        # An exposure is a "mortgage" if:
        # 1. Product type indicates mortgage/home loan, OR
        # 2. Secured by immovable property (property_collateral_value > 0), OR
        # 3. Parent facility has property collateral (for undrawn exposures which have 0 drawn_amount)
        if has_property_col and has_facility_property_flag:
            # Best case: use both property_collateral_value and the facility flag
            exposures = exposures.with_columns([
                pl.when(
                    (pl.col("product_type").str.to_uppercase().str.contains("MORTGAGE")) |
                    (pl.col("product_type").str.to_uppercase().str.contains("HOME_LOAN")) |
                    (pl.col("property_collateral_value") > 0) |
                    (pl.col("has_facility_property_collateral") == True)  # noqa: E712
                ).then(pl.lit(True))
                .otherwise(pl.lit(False))
                .alias("is_mortgage"),
            ])
        elif has_property_col:
            exposures = exposures.with_columns([
                pl.when(
                    (pl.col("product_type").str.to_uppercase().str.contains("MORTGAGE")) |
                    (pl.col("product_type").str.to_uppercase().str.contains("HOME_LOAN")) |
                    (pl.col("property_collateral_value") > 0)
                ).then(pl.lit(True))
                .otherwise(pl.lit(False))
                .alias("is_mortgage"),
            ])
        else:
            exposures = exposures.with_columns([
                pl.when(
                    (pl.col("product_type").str.to_uppercase().str.contains("MORTGAGE")) |
                    (pl.col("product_type").str.to_uppercase().str.contains("HOME_LOAN"))
                ).then(pl.lit(True))
                .otherwise(pl.lit(False))
                .alias("is_mortgage"),
            ])

        # Check if exposure exceeds retail threshold using ADJUSTED amounts
        # (excluding residential property collateral per CRR Art. 123(c))
        # The columns lending_group_adjusted_exposure and exposure_for_retail_threshold
        # already exclude residential property value from hierarchy.py
        exposures = exposures.with_columns([
            # Check if lending group adjusted total exceeds retail threshold
            pl.when(
                pl.col("lending_group_adjusted_exposure") > max_retail_exposure
            ).then(pl.lit(False))
            .when(
                # For standalone (no lending group), check individual adjusted exposure
                (pl.col("lending_group_adjusted_exposure") == 0) &
                (pl.col("exposure_for_retail_threshold") > max_retail_exposure)
            ).then(pl.lit(False))
            .otherwise(pl.lit(True))
            .alias("qualifies_as_retail"),

            # Track whether residential property exclusion was applied
            pl.when(pl.col("residential_collateral_value") > 0)
            .then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("retail_threshold_exclusion_applied"),
        ])

        # Get SME threshold for checking if retail exposures should move to CORPORATE_SME
        sme_threshold_gbp = float(
            config.supporting_factors.sme_turnover_threshold_eur * config.eur_gbp_rate
        )

        # Update exposure class for retail with differentiated treatment
        exposures = exposures.with_columns([
            pl.when(
                # Retail mortgage - stays as RETAIL_MORTGAGE regardless of threshold
                # Under SA, these are assigned to Article 112(i) residential property class
                # and excluded from the EUR 1m aggregation
                (pl.col("is_mortgage") == True) &  # noqa: E712
                (
                    (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value) |
                    (pl.col("cp_entity_type") == "individual")
                )
            ).then(pl.lit(ExposureClass.RETAIL_MORTGAGE.value))
            .when(
                # SME retail that doesn't qualify as retail due to threshold
                # Check SME criteria directly (turnover < EUR 50m) since is_sme flag
                # is only set for exposures already classified as CORPORATE
                # Reclassify to CORPORATE_SME (retains firm-size adjustment under IRB)
                (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value) &
                (pl.col("qualifies_as_retail") == False) &  # noqa: E712
                (pl.col("cp_annual_revenue") < sme_threshold_gbp) &
                (pl.col("cp_annual_revenue") > 0)
            ).then(pl.lit(ExposureClass.CORPORATE_SME.value))
            .when(
                # Other retail that doesn't qualify due to threshold
                # (either large corporates or missing revenue data)
                # Reclassify to CORPORATE
                (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value) &
                (pl.col("qualifies_as_retail") == False)  # noqa: E712
            ).then(pl.lit(ExposureClass.CORPORATE.value))
            .otherwise(pl.col("exposure_class"))
            .alias("exposure_class"),
        ])

        # Update is_sme flag for exposures that were reclassified to CORPORATE_SME
        exposures = exposures.with_columns([
            pl.when(
                pl.col("exposure_class") == ExposureClass.CORPORATE_SME.value
            ).then(pl.lit(True))
            .otherwise(pl.col("is_sme"))
            .alias("is_sme"),
        ])

        return exposures

    def _apply_corporate_to_retail_reclassification(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Reclassify qualifying corporates to retail for AIRB treatment.

        Per CRR Art. 147(5) / Basel CRE30.16-17, corporate exposures can be
        treated as retail ("regulatory retail") if:
        1. Managed as part of a retail pool (is_managed_as_retail=True)
        2. Aggregated exposure < EUR 1m (qualifies_as_retail=True)
        3. Has internally modelled LGD (lgd IS NOT NULL)
        4. Turnover < EUR 50m (SME definition per CRR Art. 501)

        Reclassification target:
        - With property collateral → RETAIL_MORTGAGE
        - Without property collateral → RETAIL_OTHER
        - NOT eligible for QRRE (even if revolving facility)

        This enables AIRB treatment for small corporates when the firm has
        AIRB approval for retail but only FIRB approval for corporates.
        """
        # Check if this reclassification is relevant
        # Only applies when AIRB is permitted for retail but not for corporate
        airb_for_retail = config.irb_permissions.is_permitted(
            ExposureClass.RETAIL_OTHER, ApproachType.AIRB
        )
        airb_for_corporate = config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.AIRB
        )

        # If AIRB is permitted for corporate, no need to reclassify
        # If AIRB is not permitted for retail, can't reclassify to get AIRB
        if airb_for_corporate or not airb_for_retail:
            # Add placeholder columns for consistency
            return exposures.with_columns([
                pl.lit(False).alias("reclassified_to_retail"),
                pl.lit(False).alias("has_property_collateral"),
            ])

        # Check schema for available columns
        schema = exposures.collect_schema()

        # Get SME turnover threshold (EUR 50m converted to GBP)
        sme_turnover_threshold = float(
            config.supporting_factors.sme_turnover_threshold_eur * config.eur_gbp_rate
        )

        # Add flag for reclassification eligibility
        # All conditions must be met: managed as retail, below threshold, has LGD, SME turnover
        reclassification_expr = (
            (pl.col("exposure_class").is_in([
                ExposureClass.CORPORATE.value,
                ExposureClass.CORPORATE_SME.value,
            ])) &
            (pl.col("cp_is_managed_as_retail") == True) &  # noqa: E712
            (pl.col("qualifies_as_retail") == True) &  # noqa: E712
            (pl.col("lgd").is_not_null()) &
            (pl.col("cp_annual_revenue") < sme_turnover_threshold) &  # SME turnover check
            (pl.col("cp_annual_revenue") > 0)  # Exclude missing/zero revenue
        )

        exposures = exposures.with_columns([
            pl.when(reclassification_expr)
            .then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("reclassified_to_retail"),
        ])

        # Determine if exposure has property collateral (residential OR commercial)
        # Check property_collateral_value (from hierarchy) which includes both types
        # For retail_mortgage classification, ANY immovable property qualifies
        has_property_expr = pl.lit(False)
        schema_names = set(schema.names())

        # Primary check: property_collateral_value includes both residential and commercial
        if "property_collateral_value" in schema_names:
            has_property_expr = has_property_expr | (pl.col("property_collateral_value") > 0)

        # Check facility-level property collateral flag (for undrawn exposures)
        if "has_facility_property_collateral" in schema_names:
            has_property_expr = has_property_expr | (pl.col("has_facility_property_collateral") == True)  # noqa: E712

        # Fallback: check residential_collateral_value (for backwards compatibility)
        if "residential_collateral_value" in schema_names:
            has_property_expr = has_property_expr | (pl.col("residential_collateral_value") > 0)

        # Fallback: check collateral_type at exposure level if available
        if "collateral_type" in schema_names:
            has_property_expr = has_property_expr | (
                pl.col("collateral_type").is_in(["immovable", "residential", "commercial"])
            )

        exposures = exposures.with_columns([
            has_property_expr.alias("has_property_collateral"),
        ])

        # Reclassify eligible corporates
        # - With property collateral → RETAIL_MORTGAGE
        # - Without property collateral → RETAIL_OTHER
        exposures = exposures.with_columns([
            pl.when(
                (pl.col("reclassified_to_retail") == True) &  # noqa: E712
                (pl.col("has_property_collateral") == True)  # noqa: E712
            ).then(pl.lit(ExposureClass.RETAIL_MORTGAGE.value))
            .when(pl.col("reclassified_to_retail") == True)  # noqa: E712
            .then(pl.lit(ExposureClass.RETAIL_OTHER.value))
            .otherwise(pl.col("exposure_class"))
            .alias("exposure_class"),
        ])

        return exposures

    def _identify_defaults(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Identify defaulted exposures.

        Default criteria:
        - Counterparty default_status = True
        - 90+ days past due (would need additional data)
        """
        return exposures.with_columns([
            # Is defaulted flag
            pl.when(pl.col("cp_default_status") == True)  # noqa: E712
            .then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("is_defaulted"),

            # Update exposure class for defaults (only for SA)
            # For IRB, defaulted exposures keep their class but use default LGD
            pl.when(pl.col("cp_default_status") == True)  # noqa: E712
            .then(pl.lit(ExposureClass.DEFAULTED.value))
            .otherwise(pl.col("exposure_class"))
            .alias("exposure_class_for_sa"),
        ])

    def _apply_infrastructure_classification(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Identify infrastructure exposures for supporting factor application.

        Infrastructure criteria (CRR Art. 501a):
        - Product type indicates infrastructure lending
        - Eligible for 0.75 supporting factor under CRR

        Note: Basel 3.1 does NOT have an infrastructure supporting factor.
        """
        return exposures.with_columns([
            pl.when(
                pl.col("product_type").str.to_uppercase().str.contains("INFRASTRUCTURE")
            ).then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("is_infrastructure"),
        ])

    def _apply_fi_scalar_classification(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Derive FI scalar flags for IRB correlation adjustment.

        Per CRR Article 153(2), correlation is multiplied by 1.25 for:
        - Large financial sector entities (total assets >= EUR 70bn)
        - Unregulated financial sector entities

        Sets:
        - is_financial_sector_entity: Entity type is in FINANCIAL_SECTOR_ENTITY_TYPES
        - is_large_financial_sector_entity: FSE with total assets >= EUR 70bn threshold
        - requires_fi_scalar: Either LFSE or unregulated FSE
        """
        # Large FSE threshold: EUR 70bn (CRR Art. 4(1)(146))
        lfse_threshold_gbp = float(
            CRR_REGULATORY_THRESHOLDS_EUR["lfse_total_assets"] * config.eur_gbp_rate
        )

        return exposures.with_columns([
            # Is this a financial sector entity type?
            pl.col("cp_entity_type")
            .is_in(FINANCIAL_SECTOR_ENTITY_TYPES)
            .alias("is_financial_sector_entity"),
        ]).with_columns([
            # Is this a large financial sector entity? (total assets >= EUR 70bn)
            pl.when(
                (pl.col("is_financial_sector_entity") == True) &  # noqa: E712
                (pl.col("cp_total_assets") >= lfse_threshold_gbp)
            ).then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("is_large_financial_sector_entity"),

            # Does this exposure require the FI scalar (1.25x correlation)?
            # Either: Large FSE OR (FSE AND unregulated)
            pl.when(
                # Large FSE
                (pl.col("is_financial_sector_entity") == True) &  # noqa: E712
                (pl.col("cp_total_assets") >= lfse_threshold_gbp)
            ).then(pl.lit(True))
            .when(
                # Unregulated FSE
                (pl.col("is_financial_sector_entity") == True) &  # noqa: E712
                (pl.col("cp_is_regulated") == False)  # noqa: E712
            ).then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("requires_fi_scalar"),
        ])

    def _determine_approach(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Determine calculation approach based on permissions.

        Logic:
        1. Check if IRB is permitted FOR EACH EXPOSURE CLASS
        2. If F-IRB or A-IRB permitted for that class, assign appropriate approach
        3. Default to SA if no IRB permission for the class
        4. Specialised lending uses slotting if permitted
        """
        # Build per-exposure-class permission checks
        # Check AIRB permissions per exposure class
        airb_corporate = config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.AIRB
        )
        airb_corporate_sme = config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE_SME, ApproachType.AIRB
        )
        airb_retail_mortgage = config.irb_permissions.is_permitted(
            ExposureClass.RETAIL_MORTGAGE, ApproachType.AIRB
        )
        airb_retail_other = config.irb_permissions.is_permitted(
            ExposureClass.RETAIL_OTHER, ApproachType.AIRB
        )
        airb_retail_qrre = config.irb_permissions.is_permitted(
            ExposureClass.RETAIL_QRRE, ApproachType.AIRB
        )
        airb_institution = config.irb_permissions.is_permitted(
            ExposureClass.INSTITUTION, ApproachType.AIRB
        )
        airb_cgcb = config.irb_permissions.is_permitted(
            ExposureClass.CENTRAL_GOVT_CENTRAL_BANK, ApproachType.AIRB
        )

        # Check FIRB permissions per exposure class
        firb_corporate = config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.FIRB
        )
        firb_corporate_sme = config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE_SME, ApproachType.FIRB
        )
        firb_institution = config.irb_permissions.is_permitted(
            ExposureClass.INSTITUTION, ApproachType.FIRB
        )
        firb_cgcb = config.irb_permissions.is_permitted(
            ExposureClass.CENTRAL_GOVT_CENTRAL_BANK, ApproachType.FIRB
        )

        # Identify exposures managed as retail but without internal LGD
        # These must use SA (cannot use FIRB without own LGD models)
        managed_as_retail_without_lgd = (
            (pl.col("cp_is_managed_as_retail") == True) &  # noqa: E712
            (pl.col("qualifies_as_retail") == True) &  # noqa: E712
            (pl.col("lgd").is_null())
        )

        return exposures.with_columns([
            # Determine if F-IRB permitted for this exposure class
            pl.when(
                (pl.col("exposure_class") == ExposureClass.CORPORATE.value) &
                pl.lit(firb_corporate)
            ).then(pl.lit(True))
            .when(
                (pl.col("exposure_class") == ExposureClass.CORPORATE_SME.value) &
                pl.lit(firb_corporate_sme)
            ).then(pl.lit(True))
            .when(
                (pl.col("exposure_class") == ExposureClass.INSTITUTION.value) &
                pl.lit(firb_institution)
            ).then(pl.lit(True))
            .when(
                (pl.col("exposure_class") == ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value) &
                pl.lit(firb_cgcb)
            ).then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("firb_permitted"),

            # Determine if A-IRB permitted for this exposure class
            pl.when(
                (pl.col("exposure_class") == ExposureClass.CORPORATE.value) &
                pl.lit(airb_corporate)
            ).then(pl.lit(True))
            .when(
                (pl.col("exposure_class") == ExposureClass.CORPORATE_SME.value) &
                pl.lit(airb_corporate_sme)
            ).then(pl.lit(True))
            .when(
                (pl.col("exposure_class") == ExposureClass.RETAIL_MORTGAGE.value) &
                pl.lit(airb_retail_mortgage)
            ).then(pl.lit(True))
            .when(
                (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value) &
                pl.lit(airb_retail_other)
            ).then(pl.lit(True))
            .when(
                (pl.col("exposure_class") == ExposureClass.RETAIL_QRRE.value) &
                pl.lit(airb_retail_qrre)
            ).then(pl.lit(True))
            .when(
                (pl.col("exposure_class") == ExposureClass.INSTITUTION.value) &
                pl.lit(airb_institution)
            ).then(pl.lit(True))
            .when(
                (pl.col("exposure_class") == ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value) &
                pl.lit(airb_cgcb)
            ).then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("airb_permitted"),
        ]).with_columns([
            # Assign approach
            pl.when(
                # Exposures managed as retail but without internal LGD must use SA
                # They cannot use FIRB (no own LGD models) and don't qualify for retail AIRB
                managed_as_retail_without_lgd
            ).then(pl.lit(ApproachType.SA.value))
            .when(
                # Specialised lending with A-IRB permission (models for PD/LGD available)
                # A-IRB takes precedence over slotting when SPECIFICALLY permitted for SL
                (pl.col("exposure_class") == ExposureClass.SPECIALISED_LENDING.value) &
                self._check_sl_airb_permitted(config)
            ).then(pl.lit(ApproachType.AIRB.value))
            .when(
                # Specialised lending with slotting permission (fallback)
                (pl.col("exposure_class") == ExposureClass.SPECIALISED_LENDING.value) &
                self._check_slotting_permitted(config)
            ).then(pl.lit(ApproachType.SLOTTING.value))
            .when(
                # A-IRB for retail (retail requires A-IRB, not F-IRB)
                (pl.col("exposure_class").is_in([
                    ExposureClass.RETAIL_MORTGAGE.value,
                    ExposureClass.RETAIL_OTHER.value,
                    ExposureClass.RETAIL_QRRE.value,
                ])) &
                (pl.col("airb_permitted") == True)  # noqa: E712
            ).then(pl.lit(ApproachType.AIRB.value))
            .when(
                # A-IRB for corporates if permitted FOR THAT CLASS
                (pl.col("exposure_class").is_in([
                    ExposureClass.CORPORATE.value,
                    ExposureClass.CORPORATE_SME.value,
                ])) &
                (pl.col("airb_permitted") == True)  # noqa: E712
            ).then(pl.lit(ApproachType.AIRB.value))
            .when(
                # F-IRB for corporates/institutions/sovereigns if permitted
                (pl.col("exposure_class").is_in([
                    ExposureClass.CORPORATE.value,
                    ExposureClass.CORPORATE_SME.value,
                    ExposureClass.INSTITUTION.value,
                    ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
                ])) &
                (pl.col("firb_permitted") == True)  # noqa: E712
            ).then(pl.lit(ApproachType.FIRB.value))
            .otherwise(pl.lit(ApproachType.SA.value))
            .alias("approach"),
        ])

    def _check_firb_permitted(self, config: CalculationConfig) -> pl.Expr:
        """Check if F-IRB is permitted for any class."""
        # Check if any class has F-IRB permission
        for exposure_class in ExposureClass:
            if config.irb_permissions.is_permitted(exposure_class, ApproachType.FIRB):
                return pl.lit(True)
        return pl.lit(False)

    def _check_airb_permitted(self, config: CalculationConfig) -> pl.Expr:
        """Check if A-IRB is permitted for any class."""
        for exposure_class in ExposureClass:
            if config.irb_permissions.is_permitted(exposure_class, ApproachType.AIRB):
                return pl.lit(True)
        return pl.lit(False)

    def _check_slotting_permitted(self, config: CalculationConfig) -> pl.Expr:
        """Check if slotting is permitted."""
        if config.irb_permissions.is_permitted(
            ExposureClass.SPECIALISED_LENDING, ApproachType.SLOTTING
        ):
            return pl.lit(True)
        return pl.lit(False)

    def _check_sl_airb_permitted(self, config: CalculationConfig) -> pl.Expr:
        """Check if A-IRB is permitted specifically for SPECIALISED_LENDING."""
        if config.irb_permissions.is_permitted(
            ExposureClass.SPECIALISED_LENDING, ApproachType.AIRB
        ):
            return pl.lit(True)
        return pl.lit(False)

    def _clear_lgd_for_firb(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Clear internal LGD for F-IRB exposures.

        F-IRB uses supervisory LGD values per CRR Art. 161, not internal models.
        This ensures that exposures reclassified from retail (which may have
        internal LGD from retail models) use the correct supervisory LGD
        when treated as F-IRB corporate exposures.

        The CRM processor will apply the appropriate supervisory LGD based on:
        - Collateral type (financial: 0%, real estate: 35%, receivables: 35%, other: 40%)
        - Seniority (senior unsecured: 45%, subordinated: 75%)

        A-IRB exposures retain their internal LGD estimates.
        """
        return exposures.with_columns([
            pl.when(pl.col("approach") == ApproachType.FIRB.value)
            .then(pl.lit(None).cast(pl.Float64))
            .otherwise(pl.col("lgd"))
            .alias("lgd"),
        ])

    def _add_classification_audit(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Add classification reasoning for audit trail."""
        return exposures.with_columns([
            # Build classification reason string
            pl.concat_str([
                pl.lit("entity_type="),
                pl.col("cp_entity_type").fill_null("unknown"),
                pl.lit("; exp_class_sa="),
                pl.col("exposure_class_sa").fill_null("unknown"),
                pl.lit("; exp_class_irb="),
                pl.col("exposure_class_irb").fill_null("unknown"),
                pl.lit("; is_sme="),
                pl.col("is_sme").cast(pl.String),
                pl.lit("; is_mortgage="),
                pl.col("is_mortgage").cast(pl.String),
                pl.lit("; is_defaulted="),
                pl.col("is_defaulted").cast(pl.String),
                pl.lit("; is_infrastructure="),
                pl.col("is_infrastructure").cast(pl.String),
                pl.lit("; requires_fi_scalar="),
                pl.col("requires_fi_scalar").cast(pl.String),
                pl.lit("; qualifies_as_retail="),
                pl.col("qualifies_as_retail").cast(pl.String),
                pl.lit("; reclassified_to_retail="),
                pl.col("reclassified_to_retail").cast(pl.String),
            ]).alias("classification_reason"),
        ])

    def _filter_by_approach(
        self,
        exposures: pl.LazyFrame,
        approach: ApproachType,
    ) -> pl.LazyFrame:
        """Filter exposures by calculation approach."""
        return exposures.filter(pl.col("approach") == approach.value)

    def _filter_irb_exposures(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Filter exposures using IRB approach (F-IRB or A-IRB)."""
        return exposures.filter(
            (pl.col("approach") == ApproachType.FIRB.value) |
            (pl.col("approach") == ApproachType.AIRB.value)
        )

    def _enrich_slotting_exposures(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """
        Add slotting metadata to specialised lending exposures.

        Derives slotting_category, sl_type, and is_hvcre from counterparty reference
        and product type patterns.

        Slotting categories: strong, good, satisfactory, weak, default
        """
        schema = exposures.collect_schema()

        # Derive slotting_category from counterparty_reference pattern
        # Pattern: SL_*_STRONG -> strong, SL_*_GOOD -> good, SL_*_WEAK -> weak, etc.
        exposures = exposures.with_columns([
            pl.when(pl.col("counterparty_reference").str.to_uppercase().str.contains("_STRONG"))
            .then(pl.lit("strong"))
            .when(pl.col("counterparty_reference").str.to_uppercase().str.contains("_GOOD"))
            .then(pl.lit("good"))
            .when(pl.col("counterparty_reference").str.to_uppercase().str.contains("_WEAK"))
            .then(pl.lit("weak"))
            .when(pl.col("counterparty_reference").str.to_uppercase().str.contains("_DEFAULT"))
            .then(pl.lit("default"))
            .when(pl.col("counterparty_reference").str.to_uppercase().str.contains("_SATISFACTORY"))
            .then(pl.lit("satisfactory"))
            .otherwise(pl.lit("satisfactory"))  # Default to satisfactory
            .alias("slotting_category"),
        ])

        # Derive sl_type from product_type or counterparty reference
        if "product_type" in schema.names():
            exposures = exposures.with_columns([
                pl.when(pl.col("product_type").str.to_uppercase().str.contains("PROJECT"))
                .then(pl.lit("project_finance"))
                .when(pl.col("product_type").str.to_uppercase().str.contains("OBJECT"))
                .then(pl.lit("object_finance"))
                .when(pl.col("product_type").str.to_uppercase().str.contains("COMMOD"))
                .then(pl.lit("commodities_finance"))
                .when(pl.col("product_type").str.to_uppercase() == "IPRE")
                .then(pl.lit("ipre"))
                .when(pl.col("product_type").str.to_uppercase() == "HVCRE")
                .then(pl.lit("hvcre"))
                .when(pl.col("counterparty_reference").str.to_uppercase().str.contains("_PF_"))
                .then(pl.lit("project_finance"))
                .when(pl.col("counterparty_reference").str.to_uppercase().str.contains("_IPRE_"))
                .then(pl.lit("ipre"))
                .when(pl.col("counterparty_reference").str.to_uppercase().str.contains("_HVCRE_"))
                .then(pl.lit("hvcre"))
                .otherwise(pl.lit("project_finance"))
                .alias("sl_type"),
            ])
        else:
            exposures = exposures.with_columns([
                pl.when(pl.col("counterparty_reference").str.to_uppercase().str.contains("_PF_"))
                .then(pl.lit("project_finance"))
                .when(pl.col("counterparty_reference").str.to_uppercase().str.contains("_IPRE_"))
                .then(pl.lit("ipre"))
                .when(pl.col("counterparty_reference").str.to_uppercase().str.contains("_HVCRE_"))
                .then(pl.lit("hvcre"))
                .otherwise(pl.lit("project_finance"))
                .alias("sl_type"),
            ])

        # Set is_hvcre flag
        exposures = exposures.with_columns([
            (pl.col("sl_type") == "hvcre").alias("is_hvcre"),
        ])

        return exposures

    def _build_audit_trail(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Build classification audit trail."""
        return exposures.select([
            pl.col("exposure_reference"),
            pl.col("counterparty_reference"),
            pl.col("cp_entity_type"),
            pl.col("exposure_class"),
            pl.col("exposure_class_sa"),
            pl.col("exposure_class_irb"),
            pl.col("approach"),
            pl.col("is_sme"),
            pl.col("is_mortgage"),
            pl.col("is_defaulted"),
            pl.col("is_financial_sector_entity"),
            pl.col("is_large_financial_sector_entity"),
            pl.col("requires_fi_scalar"),
            pl.col("qualifies_as_retail"),
            pl.col("retail_threshold_exclusion_applied"),
            pl.col("residential_collateral_value"),
            pl.col("lending_group_adjusted_exposure"),
            pl.col("reclassified_to_retail"),
            pl.col("classification_reason"),
        ])


def create_exposure_classifier() -> ExposureClassifier:
    """
    Create an exposure classifier instance.

    Returns:
        ExposureClassifier ready for use
    """
    return ExposureClassifier()
