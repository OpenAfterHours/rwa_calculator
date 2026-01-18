"""
Exposure classification for RWA calculator.

Classifies exposures by exposure class and calculation approach:
- Determines exposure class (sovereign, institution, corporate, retail, etc.)
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
from rwa_calc.domain.enums import (
    ApproachType,
    ExposureClass,
    SlottingCategory,
    SpecialisedLendingType,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


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

        # Step 5: Identify defaulted exposures
        classified = self._identify_defaults(classified)

        # Step 6: Determine calculation approach
        classified = self._determine_approach(
            classified,
            config,
        )

        # Step 7: Add classification audit trail
        classified = self._add_classification_audit(classified)

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
            equity_exposures=None,  # TODO: Add equity exposure handling
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
        - entity_type
        - annual_revenue (for SME check)
        - default_status
        - country_code
        - sector flags (is_pse, is_mdb, etc.)
        """
        # Select relevant counterparty columns
        cp_cols = counterparties.select([
            pl.col("counterparty_reference"),
            pl.col("entity_type").alias("cp_entity_type"),
            pl.col("country_code").alias("cp_country_code"),
            pl.col("annual_revenue").alias("cp_annual_revenue"),
            pl.col("default_status").alias("cp_default_status"),
            pl.col("is_financial_institution").alias("cp_is_financial_institution"),
            pl.col("is_regulated").alias("cp_is_regulated"),
            pl.col("is_pse").alias("cp_is_pse"),
            pl.col("is_mdb").alias("cp_is_mdb"),
            pl.col("is_international_org").alias("cp_is_international_org"),
            pl.col("is_central_counterparty").alias("cp_is_central_counterparty"),
            pl.col("is_regional_govt_local_auth").alias("cp_is_rgla"),
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
        Determine exposure class based on counterparty attributes.

        Classification logic (in priority order):
        1. Sovereign: government entities, central banks
        2. RGLA: Regional governments and local authorities
        3. PSE: Public sector entities
        4. MDB: Multilateral development banks
        5. Institution: Banks, regulated financial institutions, CCPs
        6. Corporate: Non-financial corporates
        7. Retail: Individuals, small businesses meeting retail criteria
        8. Specialised Lending: Project finance, object finance, etc.
        """
        return exposures.with_columns([
            pl.when(
                (pl.col("cp_entity_type") == "sovereign") |
                (pl.col("cp_entity_type") == "central_bank")
            ).then(pl.lit(ExposureClass.SOVEREIGN.value))
            .when(pl.col("cp_is_rgla") == True)  # noqa: E712
            .then(pl.lit(ExposureClass.RGLA.value))
            .when(pl.col("cp_is_pse") == True)  # noqa: E712
            .then(pl.lit(ExposureClass.PSE.value))
            .when(pl.col("cp_is_mdb") == True)  # noqa: E712
            .then(pl.lit(ExposureClass.MDB.value))
            .when(pl.col("cp_is_international_org") == True)  # noqa: E712
            .then(pl.lit(ExposureClass.MDB.value))  # Treat as MDB for RW purposes
            .when(
                (pl.col("cp_entity_type") == "institution") |
                (pl.col("cp_entity_type") == "bank") |
                (pl.col("cp_is_financial_institution") == True) |  # noqa: E712
                (pl.col("cp_is_central_counterparty") == True)  # noqa: E712
            ).then(pl.lit(ExposureClass.INSTITUTION.value))
            .when(
                (pl.col("cp_entity_type") == "individual") |
                (pl.col("cp_entity_type") == "retail")
            ).then(pl.lit(ExposureClass.RETAIL_OTHER.value))  # Will be refined later
            .when(
                (pl.col("cp_entity_type") == "corporate") |
                (pl.col("cp_entity_type") == "company")
            ).then(pl.lit(ExposureClass.CORPORATE.value))
            .when(pl.col("cp_entity_type") == "specialised_lending")
            .then(pl.lit(ExposureClass.SPECIALISED_LENDING.value))
            .otherwise(pl.lit(ExposureClass.OTHER.value))
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
        - Aggregated exposure to lending group < threshold
        - CRR: EUR 1m (GBP 880k)
        - Basel 3.1: GBP 880k

        Mortgage classification:
        - Product type indicates mortgage
        - Secured by residential property
        """
        max_retail_exposure = float(config.retail_thresholds.max_exposure_threshold)

        # First, check if exposure exceeds retail threshold
        exposures = exposures.with_columns([
            # Check if lending group total exceeds retail threshold
            pl.when(
                pl.col("lending_group_total_exposure") > max_retail_exposure
            ).then(pl.lit(False))
            .when(
                # For standalone (no lending group), check individual exposure
                (pl.col("lending_group_total_exposure") == 0) &
                (pl.col("drawn_amount") + pl.col("nominal_amount") > max_retail_exposure)
            ).then(pl.lit(False))
            .otherwise(pl.lit(True))
            .alias("qualifies_as_retail"),
        ])

        # Apply mortgage classification
        exposures = exposures.with_columns([
            pl.when(
                (pl.col("product_type").str.to_uppercase().str.contains("MORTGAGE")) |
                (pl.col("product_type").str.to_uppercase().str.contains("HOME_LOAN"))
            ).then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("is_mortgage"),
        ])

        # Update exposure class for retail
        exposures = exposures.with_columns([
            pl.when(
                # Retail mortgage
                (pl.col("is_mortgage") == True) &  # noqa: E712
                (
                    (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value) |
                    (pl.col("cp_entity_type") == "individual")
                )
            ).then(pl.lit(ExposureClass.RETAIL_MORTGAGE.value))
            .when(
                # Corporate that doesn't qualify as retail due to threshold
                (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value) &
                (pl.col("qualifies_as_retail") == False)  # noqa: E712
            ).then(pl.lit(ExposureClass.CORPORATE.value))  # Reclassify as corporate
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

    def _determine_approach(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Determine calculation approach based on permissions.

        Logic:
        1. Check if IRB is permitted for the exposure class
        2. If F-IRB or A-IRB permitted, assign appropriate approach
        3. Default to SA if no IRB permission
        4. Specialised lending uses slotting if permitted
        """
        # Build approach mapping based on permissions
        # For simplicity, we'll check each class against permissions

        return exposures.with_columns([
            # Determine if F-IRB permitted
            pl.when(
                self._check_firb_permitted(config)
            ).then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("firb_permitted"),

            # Determine if A-IRB permitted
            pl.when(
                self._check_airb_permitted(config)
            ).then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("airb_permitted"),
        ]).with_columns([
            # Assign approach
            pl.when(
                # Specialised lending with slotting permission
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
                # A-IRB for corporates if permitted
                (pl.col("exposure_class").is_in([
                    ExposureClass.CORPORATE.value,
                    ExposureClass.CORPORATE_SME.value,
                ])) &
                (pl.col("airb_permitted") == True)  # noqa: E712
            ).then(pl.lit(ApproachType.AIRB.value))
            .when(
                # F-IRB for corporates/institutions/sovereigns if A-IRB not permitted
                (pl.col("exposure_class").is_in([
                    ExposureClass.CORPORATE.value,
                    ExposureClass.CORPORATE_SME.value,
                    ExposureClass.INSTITUTION.value,
                    ExposureClass.SOVEREIGN.value,
                ])) &
                (pl.col("firb_permitted") == True) &  # noqa: E712
                (pl.col("airb_permitted") == False)  # noqa: E712
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
                pl.lit("; is_sme="),
                pl.col("is_sme").cast(pl.String),
                pl.lit("; is_mortgage="),
                pl.col("is_mortgage").cast(pl.String),
                pl.lit("; is_defaulted="),
                pl.col("is_defaulted").cast(pl.String),
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
            pl.col("approach"),
            pl.col("is_sme"),
            pl.col("is_mortgage"),
            pl.col("is_defaulted"),
            pl.col("qualifies_as_retail"),
            pl.col("classification_reason"),
        ])


def create_exposure_classifier() -> ExposureClassifier:
    """
    Create an exposure classifier instance.

    Returns:
        ExposureClassifier ready for use
    """
    return ExposureClassifier()
