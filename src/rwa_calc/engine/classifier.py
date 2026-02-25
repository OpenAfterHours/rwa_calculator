"""
Exposure classification for RWA calculator.

Pipeline position:
    HierarchyResolver -> ExposureClassifier -> CRMProcessor

Key responsibilities:
- Determines exposure class (central_govt_central_bank, institution, corporate, retail, etc.)
- Assigns calculation approach (SA, F-IRB, A-IRB, slotting)
- Checks SME and retail thresholds
- Identifies defaulted exposures
- Splits exposures by approach for downstream calculators

The classifier uses 4 batched .with_columns() calls (one per regulatory concept)
to keep the LazyFrame query plan shallow, avoiding Polars optimizer segfaults
when combined with downstream CRM processor stages.

References:
- CRR Art. 112-134: Exposure classes
- CRR Art. 147-153: IRB approach assignment
- CRR Art. 501: SME supporting factor definition

Classes:
    ExposureClassifier: Main classifier implementing ClassifierProtocol

Usage:
    from rwa_calc.engine.classifier import ExposureClassifier

    classifier = ExposureClassifier()
    classified = classifier.classify(resolved_data, config)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.config.fx_rates import CRR_REGULATORY_THRESHOLDS_EUR
from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    ResolvedHierarchyBundle,
)
from rwa_calc.domain.enums import (
    ApproachType,
    ExposureClass,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


# =============================================================================
# ENTITY TYPE TO EXPOSURE CLASS MAPPINGS
# =============================================================================

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
    "rgla_sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "rgla_institution": ExposureClass.INSTITUTION.value,
    "pse_sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "pse_institution": ExposureClass.INSTITUTION.value,
    "mdb": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "international_org": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
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
    "pse_institution",
    "rgla_institution",
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
    The classifier batches expressions into 4 .with_columns() calls
    to keep the query plan shallow (5 nodes instead of 21).
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

        # Step 1: Join counterparty attributes (1 node)
        exposures = self._add_counterparty_attributes(
            data.exposures,
            data.counterparty_lookup.counterparties,
        )

        # Single schema check for conditional column logic
        schema_names = set(exposures.collect_schema().names())

        # Step 2: Derive all independent flags (1 .with_columns)
        classified = self._derive_independent_flags(exposures, config, schema_names)

        # Step 3: SME + retail classification (1 .with_columns)
        classified = self._classify_sme_and_retail(classified, config)

        # Step 4: Corporate → retail reclassification (1 .with_columns)
        classified = self._reclassify_corporate_to_retail(
            classified, config, schema_names,
        )

        # Step 5: Approach assignment + finalization (1 .with_columns)
        classified = self._determine_approach_and_finalize(classified, config)

        # Step 6: Split by approach (filter/select — no depth added)
        sa_exposures = self._filter_by_approach(classified, ApproachType.SA)
        irb_exposures = self._filter_irb_exposures(classified)
        slotting_exposures = self._filter_by_approach(classified, ApproachType.SLOTTING)
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

    # =========================================================================
    # Phase 1: Counterparty join (retained unchanged)
    # =========================================================================

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

        return exposures.join(
            cp_cols,
            on="counterparty_reference",
            how="left",
        )

    # =========================================================================
    # Phase 2: Independent flags (1 .with_columns — 11 expressions)
    # =========================================================================

    def _derive_independent_flags(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        schema_names: set[str],
    ) -> pl.LazyFrame:
        """
        Compute all flags that depend only on raw input columns.

        Single .with_columns() replacing 7 old methods. Every expression here
        reads only from the original joined columns, not from each other.

        Sets: exposure_class_sa, exposure_class_irb, exposure_class, is_mortgage,
              is_defaulted, exposure_class_for_sa, is_infrastructure,
              is_financial_sector_entity, qualifies_as_retail,
              retail_threshold_exclusion_applied, slotting_category, sl_type
        """
        max_retail_exposure = float(config.retail_thresholds.max_exposure_threshold)

        return exposures.with_columns([
            # --- Exposure class mappings (from _classify_exposure_class) ---
            pl.col("cp_entity_type")
            .replace_strict(ENTITY_TYPE_TO_SA_CLASS, default=ExposureClass.OTHER.value)
            .alias("exposure_class_sa"),

            pl.col("cp_entity_type")
            .replace_strict(ENTITY_TYPE_TO_IRB_CLASS, default=ExposureClass.OTHER.value)
            .alias("exposure_class_irb"),

            pl.col("cp_entity_type")
            .replace_strict(ENTITY_TYPE_TO_SA_CLASS, default=ExposureClass.OTHER.value)
            .alias("exposure_class"),

            # --- Mortgage flag (from _apply_retail_classification) ---
            self._build_is_mortgage_expr(schema_names),

            # --- Default flags (from _identify_defaults) ---
            (pl.col("cp_default_status") == True)  # noqa: E712
            .alias("is_defaulted"),

            pl.when(pl.col("cp_default_status") == True)  # noqa: E712
            .then(pl.lit(ExposureClass.DEFAULTED.value))
            .otherwise(
                pl.col("cp_entity_type")
                .replace_strict(
                    ENTITY_TYPE_TO_SA_CLASS, default=ExposureClass.OTHER.value,
                )
            )
            .alias("exposure_class_for_sa"),

            # --- Infrastructure flag (from _apply_infrastructure_classification) ---
            pl.col("product_type").str.to_uppercase().str.contains("INFRASTRUCTURE")
            .alias("is_infrastructure"),

            # --- Financial sector entity flag (from _apply_fi_scalar_classification) ---
            pl.col("cp_entity_type")
            .is_in(FINANCIAL_SECTOR_ENTITY_TYPES)
            .alias("is_financial_sector_entity"),

            # --- Retail threshold check (from _apply_retail_classification) ---
            pl.when(
                pl.col("lending_group_adjusted_exposure") > max_retail_exposure
            ).then(pl.lit(False))
            .when(
                (pl.col("lending_group_adjusted_exposure") == 0)
                & (pl.col("exposure_for_retail_threshold") > max_retail_exposure)
            ).then(pl.lit(False))
            .otherwise(pl.lit(True))
            .alias("qualifies_as_retail"),

            pl.when(pl.col("residential_collateral_value") > 0)
            .then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("retail_threshold_exclusion_applied"),

            # --- Slotting metadata (from _enrich_slotting_exposures) ---
            self._build_slotting_category_expr(),
            self._build_sl_type_expr(schema_names),
        ])

    # =========================================================================
    # Phase 3: SME + retail classification (1 .with_columns — 5 expressions)
    # =========================================================================

    def _classify_sme_and_retail(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Merge SME and retail classification into a single .with_columns().

        Works because they operate on non-overlapping initial exposure_class values:
        SME only touches "corporate", retail only touches "retail_other".

        Also derives FI scalar flags which depend on is_financial_sector_entity
        (set in Phase 2) but not on exposure_class mutations.

        Sets: exposure_class (updated), is_sme, is_large_financial_sector_entity,
              requires_fi_scalar, is_hvcre
        """
        sme_threshold_gbp = float(
            config.supporting_factors.sme_turnover_threshold_eur * config.eur_gbp_rate
        )
        lfse_threshold_gbp = float(
            CRR_REGULATORY_THRESHOLDS_EUR["lfse_total_assets"] * config.eur_gbp_rate
        )

        # Conditions reused across expressions (reading Phase 2 columns)
        is_corporate_sme = (
            (pl.col("exposure_class") == ExposureClass.CORPORATE.value)
            & (pl.col("cp_annual_revenue") < sme_threshold_gbp)
            & (pl.col("cp_annual_revenue") > 0)
        )
        is_retail_sme = (
            (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
            & (pl.col("qualifies_as_retail") == False)  # noqa: E712
            & (pl.col("cp_annual_revenue") < sme_threshold_gbp)
            & (pl.col("cp_annual_revenue") > 0)
        )

        return exposures.with_columns([
            # --- exposure_class update (SME + retail combined) ---
            # Priority order matters: mortgage first, then SME retail, then
            # non-qualifying retail, then corporate SME, then keep current.
            pl.when(
                # Retail mortgage — stays RETAIL_MORTGAGE regardless of threshold
                (pl.col("is_mortgage") == True)  # noqa: E712
                & (
                    (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
                    | (pl.col("cp_entity_type") == "individual")
                )
            ).then(pl.lit(ExposureClass.RETAIL_MORTGAGE.value))
            .when(
                # SME retail that doesn't qualify → CORPORATE_SME
                is_retail_sme
            ).then(pl.lit(ExposureClass.CORPORATE_SME.value))
            .when(
                # Other retail that doesn't qualify → CORPORATE
                (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
                & (pl.col("qualifies_as_retail") == False)  # noqa: E712
            ).then(pl.lit(ExposureClass.CORPORATE.value))
            .when(
                # Corporate with SME revenue → CORPORATE_SME
                is_corporate_sme
            ).then(pl.lit(ExposureClass.CORPORATE_SME.value))
            .otherwise(pl.col("exposure_class"))
            .alias("exposure_class"),

            # --- is_sme flag ---
            # True for: corporate SME OR retail reclassified to CORPORATE_SME
            (is_corporate_sme | is_retail_sme).alias("is_sme"),

            # --- FI scalar flags (depend on is_financial_sector_entity from Phase 2) ---
            (
                (pl.col("is_financial_sector_entity") == True)  # noqa: E712
                & (pl.col("cp_total_assets") >= lfse_threshold_gbp)
            ).alias("is_large_financial_sector_entity"),

            pl.when(
                (pl.col("is_financial_sector_entity") == True)  # noqa: E712
                & (pl.col("cp_total_assets") >= lfse_threshold_gbp)
            ).then(pl.lit(True))
            .when(
                (pl.col("is_financial_sector_entity") == True)  # noqa: E712
                & (pl.col("cp_is_regulated") == False)  # noqa: E712
            ).then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("requires_fi_scalar"),

            # --- HVCRE flag (depends on sl_type from Phase 2) ---
            (pl.col("sl_type") == "hvcre").alias("is_hvcre"),
        ])

    # =========================================================================
    # Phase 4: Corporate → retail reclassification (1 .with_columns)
    # =========================================================================

    def _reclassify_corporate_to_retail(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        schema_names: set[str],
    ) -> pl.LazyFrame:
        """
        Reclassify qualifying corporates to retail for AIRB treatment.

        Per CRR Art. 147(5) / Basel CRE30.16-17, corporate exposures can be
        treated as retail if:
        1. Managed as part of a retail pool (is_managed_as_retail=True)
        2. Aggregated exposure < EUR 1m (qualifies_as_retail=True)
        3. Has internally modelled LGD (lgd IS NOT NULL)
        4. Turnover < EUR 50m (SME definition per CRR Art. 501)

        Only applies when AIRB is permitted for retail but not for corporate.
        """
        airb_for_retail = config.irb_permissions.is_permitted(
            ExposureClass.RETAIL_OTHER, ApproachType.AIRB,
        )
        airb_for_corporate = config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.AIRB,
        )

        # Short-circuit: reclassification not relevant
        if airb_for_corporate or not airb_for_retail:
            return exposures.with_columns([
                pl.lit(False).alias("reclassified_to_retail"),
                pl.lit(False).alias("has_property_collateral"),
            ])

        sme_turnover_threshold = float(
            config.supporting_factors.sme_turnover_threshold_eur * config.eur_gbp_rate
        )

        # Reclassification eligibility expression (inlined — not a column ref)
        reclassification_expr = (
            (pl.col("exposure_class").is_in([
                ExposureClass.CORPORATE.value,
                ExposureClass.CORPORATE_SME.value,
            ]))
            & (pl.col("cp_is_managed_as_retail") == True)  # noqa: E712
            & (pl.col("qualifies_as_retail") == True)  # noqa: E712
            & (pl.col("lgd").is_not_null())
            & (pl.col("cp_annual_revenue") < sme_turnover_threshold)
            & (pl.col("cp_annual_revenue") > 0)
        )

        # Has property collateral expression (inlined)
        has_property_expr = self._build_has_property_expr(schema_names)

        # Single .with_columns: reclassified_to_retail, has_property_collateral,
        # exposure_class update — all using inlined expressions (not column refs)
        return exposures.with_columns([
            reclassification_expr.alias("reclassified_to_retail"),
            has_property_expr.alias("has_property_collateral"),
            pl.when(reclassification_expr & has_property_expr)
            .then(pl.lit(ExposureClass.RETAIL_MORTGAGE.value))
            .when(reclassification_expr)
            .then(pl.lit(ExposureClass.RETAIL_OTHER.value))
            .otherwise(pl.col("exposure_class"))
            .alias("exposure_class"),
        ])

    # =========================================================================
    # Phase 5: Approach assignment + finalization (1 .with_columns)
    # =========================================================================

    def _determine_approach_and_finalize(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Determine calculation approach and finalize classification.

        Single .with_columns() computing approach, LGD clearing for FIRB,
        and the classification audit string. Permission checks are inlined
        as pl.lit(bool) to avoid intermediate columns.

        Sets: approach, lgd (cleared for FIRB), classification_reason
        """
        # Pre-compute all permission booleans (Python-side, not Polars)
        airb_corporate = config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.AIRB,
        )
        airb_corporate_sme = config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE_SME, ApproachType.AIRB,
        )
        airb_retail_mortgage = config.irb_permissions.is_permitted(
            ExposureClass.RETAIL_MORTGAGE, ApproachType.AIRB,
        )
        airb_retail_other = config.irb_permissions.is_permitted(
            ExposureClass.RETAIL_OTHER, ApproachType.AIRB,
        )
        airb_retail_qrre = config.irb_permissions.is_permitted(
            ExposureClass.RETAIL_QRRE, ApproachType.AIRB,
        )
        airb_institution = config.irb_permissions.is_permitted(
            ExposureClass.INSTITUTION, ApproachType.AIRB,
        )
        airb_cgcb = config.irb_permissions.is_permitted(
            ExposureClass.CENTRAL_GOVT_CENTRAL_BANK, ApproachType.AIRB,
        )

        firb_corporate = config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE, ApproachType.FIRB,
        )
        firb_corporate_sme = config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE_SME, ApproachType.FIRB,
        )
        firb_institution = config.irb_permissions.is_permitted(
            ExposureClass.INSTITUTION, ApproachType.FIRB,
        )
        firb_cgcb = config.irb_permissions.is_permitted(
            ExposureClass.CENTRAL_GOVT_CENTRAL_BANK, ApproachType.FIRB,
        )

        sl_airb = self._check_sl_airb_permitted(config)
        sl_slotting = self._check_slotting_permitted(config)

        # Managed-as-retail-without-LGD must use SA
        managed_as_retail_without_lgd = (
            (pl.col("cp_is_managed_as_retail") == True)  # noqa: E712
            & (pl.col("qualifies_as_retail") == True)  # noqa: E712
            & (pl.col("lgd").is_null())
        )

        # --- Approach expression ---
        approach_expr = (
            pl.when(managed_as_retail_without_lgd)
            .then(pl.lit(ApproachType.SA.value))
            # SL A-IRB takes precedence over slotting
            .when(
                (pl.col("exposure_class") == ExposureClass.SPECIALISED_LENDING.value)
                & sl_airb
            ).then(pl.lit(ApproachType.AIRB.value))
            # SL slotting fallback
            .when(
                (pl.col("exposure_class") == ExposureClass.SPECIALISED_LENDING.value)
                & sl_slotting
            ).then(pl.lit(ApproachType.SLOTTING.value))
            # A-IRB for retail
            .when(
                (pl.col("exposure_class") == ExposureClass.RETAIL_MORTGAGE.value)
                & pl.lit(airb_retail_mortgage)
            ).then(pl.lit(ApproachType.AIRB.value))
            .when(
                (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
                & pl.lit(airb_retail_other)
            ).then(pl.lit(ApproachType.AIRB.value))
            .when(
                (pl.col("exposure_class") == ExposureClass.RETAIL_QRRE.value)
                & pl.lit(airb_retail_qrre)
            ).then(pl.lit(ApproachType.AIRB.value))
            # A-IRB for corporate
            .when(
                (pl.col("exposure_class") == ExposureClass.CORPORATE.value)
                & pl.lit(airb_corporate)
            ).then(pl.lit(ApproachType.AIRB.value))
            .when(
                (pl.col("exposure_class") == ExposureClass.CORPORATE_SME.value)
                & pl.lit(airb_corporate_sme)
            ).then(pl.lit(ApproachType.AIRB.value))
            # A-IRB for institution/CGCB
            .when(
                (pl.col("exposure_class") == ExposureClass.INSTITUTION.value)
                & pl.lit(airb_institution)
            ).then(pl.lit(ApproachType.AIRB.value))
            .when(
                (pl.col("exposure_class")
                 == ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value)
                & pl.lit(airb_cgcb)
            ).then(pl.lit(ApproachType.AIRB.value))
            # F-IRB for corporate/institution/CGCB
            .when(
                (pl.col("exposure_class") == ExposureClass.CORPORATE.value)
                & pl.lit(firb_corporate)
            ).then(pl.lit(ApproachType.FIRB.value))
            .when(
                (pl.col("exposure_class") == ExposureClass.CORPORATE_SME.value)
                & pl.lit(firb_corporate_sme)
            ).then(pl.lit(ApproachType.FIRB.value))
            .when(
                (pl.col("exposure_class") == ExposureClass.INSTITUTION.value)
                & pl.lit(firb_institution)
            ).then(pl.lit(ApproachType.FIRB.value))
            .when(
                (pl.col("exposure_class")
                 == ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value)
                & pl.lit(firb_cgcb)
            ).then(pl.lit(ApproachType.FIRB.value))
            .otherwise(pl.lit(ApproachType.SA.value))
            .alias("approach")
        )

        # --- FIRB LGD clearing condition (inlined, not referencing approach column) ---
        # Classes eligible for FIRB: corporate, corporate_sme, institution, cgcb
        # Clear LGD when FIRB permitted AND NOT AIRB permitted for that class
        firb_clear_condition = (
            (
                (pl.col("exposure_class") == ExposureClass.CORPORATE.value)
                & pl.lit(firb_corporate)
                & pl.lit(not airb_corporate)
            )
            | (
                (pl.col("exposure_class") == ExposureClass.CORPORATE_SME.value)
                & pl.lit(firb_corporate_sme)
                & pl.lit(not airb_corporate_sme)
            )
            | (
                (pl.col("exposure_class") == ExposureClass.INSTITUTION.value)
                & pl.lit(firb_institution)
                & pl.lit(not airb_institution)
            )
            | (
                (pl.col("exposure_class")
                 == ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value)
                & pl.lit(firb_cgcb)
                & pl.lit(not airb_cgcb)
            )
        )
        # Also clear for managed-as-retail-without-LGD going to SA (lgd already null)
        # and we must NOT clear for reclassified retail exposures

        lgd_expr = (
            pl.when(firb_clear_condition & ~pl.col("reclassified_to_retail"))
            .then(pl.lit(None).cast(pl.Float64))
            .otherwise(pl.col("lgd"))
            .alias("lgd")
        )

        # --- Classification audit string ---
        audit_expr = pl.concat_str([
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
        ]).alias("classification_reason")

        return exposures.with_columns([
            approach_expr,
            lgd_expr,
            audit_expr,
        ])

    # =========================================================================
    # Expression builders (static helpers returning pl.Expr)
    # =========================================================================

    @staticmethod
    def _build_is_mortgage_expr(schema_names: set[str]) -> pl.Expr:
        """Build is_mortgage expression, conditional on available columns."""
        base = (
            pl.col("product_type").str.to_uppercase().str.contains("MORTGAGE")
            | pl.col("product_type").str.to_uppercase().str.contains("HOME_LOAN")
        )
        if (
            "property_collateral_value" in schema_names
            and "has_facility_property_collateral" in schema_names
        ):
            return (
                base
                | (pl.col("property_collateral_value") > 0)
                | (pl.col("has_facility_property_collateral") == True)  # noqa: E712
            ).alias("is_mortgage")
        if "property_collateral_value" in schema_names:
            return (
                base | (pl.col("property_collateral_value") > 0)
            ).alias("is_mortgage")
        return base.alias("is_mortgage")

    @staticmethod
    def _build_slotting_category_expr() -> pl.Expr:
        """Build slotting_category expression from counterparty_reference patterns."""
        return (
            pl.when(
                pl.col("counterparty_reference").str.to_uppercase()
                .str.contains("_STRONG")
            ).then(pl.lit("strong"))
            .when(
                pl.col("counterparty_reference").str.to_uppercase()
                .str.contains("_GOOD")
            ).then(pl.lit("good"))
            .when(
                pl.col("counterparty_reference").str.to_uppercase()
                .str.contains("_WEAK")
            ).then(pl.lit("weak"))
            .when(
                pl.col("counterparty_reference").str.to_uppercase()
                .str.contains("_DEFAULT")
            ).then(pl.lit("default"))
            .when(
                pl.col("counterparty_reference").str.to_uppercase()
                .str.contains("_SATISFACTORY")
            ).then(pl.lit("satisfactory"))
            .otherwise(pl.lit("satisfactory"))
            .alias("slotting_category")
        )

    @staticmethod
    def _build_sl_type_expr(schema_names: set[str]) -> pl.Expr:
        """Build sl_type expression from product_type and counterparty_reference."""
        cp_ref_chain = (
            pl.when(
                pl.col("counterparty_reference").str.to_uppercase()
                .str.contains("_PF_")
            ).then(pl.lit("project_finance"))
            .when(
                pl.col("counterparty_reference").str.to_uppercase()
                .str.contains("_IPRE_")
            ).then(pl.lit("ipre"))
            .when(
                pl.col("counterparty_reference").str.to_uppercase()
                .str.contains("_HVCRE_")
            ).then(pl.lit("hvcre"))
            .otherwise(pl.lit("project_finance"))
        )

        if "product_type" not in schema_names:
            return cp_ref_chain.alias("sl_type")

        return (
            pl.when(
                pl.col("product_type").str.to_uppercase().str.contains("PROJECT")
            ).then(pl.lit("project_finance"))
            .when(
                pl.col("product_type").str.to_uppercase().str.contains("OBJECT")
            ).then(pl.lit("object_finance"))
            .when(
                pl.col("product_type").str.to_uppercase().str.contains("COMMOD")
            ).then(pl.lit("commodities_finance"))
            .when(pl.col("product_type").str.to_uppercase() == "IPRE")
            .then(pl.lit("ipre"))
            .when(pl.col("product_type").str.to_uppercase() == "HVCRE")
            .then(pl.lit("hvcre"))
            .when(
                pl.col("counterparty_reference").str.to_uppercase()
                .str.contains("_PF_")
            ).then(pl.lit("project_finance"))
            .when(
                pl.col("counterparty_reference").str.to_uppercase()
                .str.contains("_IPRE_")
            ).then(pl.lit("ipre"))
            .when(
                pl.col("counterparty_reference").str.to_uppercase()
                .str.contains("_HVCRE_")
            ).then(pl.lit("hvcre"))
            .otherwise(pl.lit("project_finance"))
            .alias("sl_type")
        )

    @staticmethod
    def _build_has_property_expr(schema_names: set[str]) -> pl.Expr:
        """Build has_property_collateral expression, conditional on schema."""
        expr = pl.lit(False)

        if "property_collateral_value" in schema_names:
            expr = expr | (pl.col("property_collateral_value") > 0)

        if "has_facility_property_collateral" in schema_names:
            expr = expr | (pl.col("has_facility_property_collateral") == True)  # noqa: E712

        if "collateral_type" in schema_names:
            expr = expr | pl.col("collateral_type").is_in(
                ["immovable", "residential", "commercial"],
            )

        return expr

    # =========================================================================
    # Permission helpers (retained unchanged)
    # =========================================================================

    def _check_slotting_permitted(self, config: CalculationConfig) -> pl.Expr:
        """Check if slotting is permitted."""
        if config.irb_permissions.is_permitted(
            ExposureClass.SPECIALISED_LENDING, ApproachType.SLOTTING,
        ):
            return pl.lit(True)
        return pl.lit(False)

    def _check_sl_airb_permitted(self, config: CalculationConfig) -> pl.Expr:
        """Check if A-IRB is permitted specifically for SPECIALISED_LENDING."""
        if config.irb_permissions.is_permitted(
            ExposureClass.SPECIALISED_LENDING, ApproachType.AIRB,
        ):
            return pl.lit(True)
        return pl.lit(False)

    # =========================================================================
    # Filters and audit trail (retained unchanged)
    # =========================================================================

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
            (pl.col("approach") == ApproachType.FIRB.value)
            | (pl.col("approach") == ApproachType.AIRB.value)
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
