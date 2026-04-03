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

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    ResolvedHierarchyBundle,
)
from rwa_calc.data.tables.eu_sovereign import build_eu_domestic_currency_expr
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
    "covered_bond": ExposureClass.COVERED_BOND.value,
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
    "covered_bond": ExposureClass.COVERED_BOND.value,
}


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
        # Step 1: Join counterparty attributes (1 node)
        exposures = self._add_counterparty_attributes(
            data.exposures,
            data.counterparty_lookup.counterparties,
        )

        # Step 1b: Join specialised lending metadata (by counterparty)
        sl_data = data.specialised_lending
        if sl_data is not None:
            exposures = exposures.join(
                sl_data.select(
                    ["counterparty_reference", "sl_type", "slotting_category", "is_hvcre"]
                ),
                on="counterparty_reference",
                how="left",
            )
        else:
            exposures = exposures.with_columns(
                pl.lit(None).cast(pl.String).alias("sl_type"),
                pl.lit(None).cast(pl.String).alias("slotting_category"),
                pl.lit(None).cast(pl.Boolean).alias("is_hvcre"),
            )

        # Single schema check for conditional column logic
        schema_names = set(exposures.collect_schema().names())

        # Step 2: Derive all independent flags (1 .with_columns)
        classified = self._derive_independent_flags(exposures, config, schema_names)

        # Step 3: SME + retail classification (1 .with_columns)
        classified = self._classify_sme_and_retail(classified, config, schema_names)

        # Step 4: Corporate → retail reclassification (1 .with_columns)
        classified = self._reclassify_corporate_to_retail(
            classified,
            config,
            schema_names,
        )

        # Step 4b: Model-level permission resolution (optional, 1 join + filter)
        # When model_permissions data is present, resolve per-row AIRB/FIRB permissions.
        # Otherwise, falls back to org-wide IRBPermissions in _determine_approach_and_finalize.
        model_permissions = data.model_permissions
        if model_permissions is not None:
            classified = self._resolve_model_permissions(
                classified, model_permissions, schema_names
            )

        # Step 5: Approach assignment + finalization (1 .with_columns)
        classified = self._determine_approach_and_finalize(
            classified,
            config,
            schema_names,
            has_model_permissions=model_permissions is not None,
        )

        # Step 6: Split by approach (filter/select — no depth added)
        sa_exposures = classified.filter(pl.col("approach") == ApproachType.SA.value)
        irb_exposures = classified.filter(
            pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value])
        )
        slotting_exposures = classified.filter(pl.col("approach") == ApproachType.SLOTTING.value)
        classification_audit = self._build_audit_trail(classified)

        return ClassifiedExposuresBundle(
            all_exposures=classified,
            sa_exposures=sa_exposures,
            irb_exposures=irb_exposures,
            slotting_exposures=slotting_exposures,
            equity_exposures=data.equity_exposures,
            ciu_holdings=data.ciu_holdings,
            collateral=data.collateral,
            guarantees=data.guarantees,
            provisions=data.provisions,
            counterparty_lookup=data.counterparty_lookup,
            classification_audit=classification_audit,
            classification_errors=[],
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
        - apply_fi_scalar (for FI scalar - LFSE/unregulated FSE)
        - is_managed_as_retail (for SME retail treatment)
        """
        cp_schema = counterparties.collect_schema()
        cp_col_names = cp_schema.names()

        select_cols = [
            pl.col("counterparty_reference"),
            pl.col("entity_type").str.to_lowercase().alias("cp_entity_type"),
            pl.col("country_code").alias("cp_country_code"),
            pl.col("annual_revenue").alias("cp_annual_revenue"),
            pl.col("total_assets").alias("cp_total_assets"),
            pl.col("default_status").alias("cp_default_status"),
            pl.col("apply_fi_scalar").alias("cp_apply_fi_scalar"),
            pl.col("is_managed_as_retail").alias("cp_is_managed_as_retail"),
        ]

        # Basel 3.1 fields — propagate if present (optional in input data)
        if "scra_grade" in cp_col_names:
            select_cols.append(pl.col("scra_grade").alias("cp_scra_grade"))
        if "is_investment_grade" in cp_col_names:
            select_cols.append(pl.col("is_investment_grade").alias("cp_is_investment_grade"))

        # CCP fields (CRR Art. 300-311, CRE54.14-15)
        if "is_ccp_client_cleared" in cp_col_names:
            select_cols.append(pl.col("is_ccp_client_cleared").alias("cp_is_ccp_client_cleared"))

        # Currency mismatch (Basel 3.1 Art. 123B / CRE20.93)
        if "borrower_income_currency" in cp_col_names:
            select_cols.append(
                pl.col("borrower_income_currency").alias("cp_borrower_income_currency")
            )

        cp_cols = counterparties.select(select_cols)

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

        Uses two .with_columns() batches: the first pre-computes shared
        intermediates (uppercase strings, entity-type mapping) that the
        second batch references, avoiding redundant str.to_uppercase()
        and replace_strict() calls.

        Sets: exposure_class_sa, exposure_class_irb, exposure_class, is_mortgage,
              is_defaulted, exposure_class_for_sa, is_infrastructure,
              qualifies_as_retail, retail_threshold_exclusion_applied
        """
        max_retail_exposure = float(config.retail_thresholds.max_exposure_threshold)

        # SL override: exposures with sl_type (from specialised_lending join) get
        # SPECIALISED_LENDING class regardless of counterparty entity_type.
        sl_override = pl.col("sl_type").is_not_null()

        # Batch 1: Pre-compute shared intermediates to avoid redundant work.
        # - _sa_class: entity type → SA class mapping (used 3× below)
        # - _irb_class: entity type → IRB class mapping
        # - _pt_upper: product_type uppercased (used in is_mortgage, infrastructure)
        exposures = exposures.with_columns(
            [
                pl.col("cp_entity_type")
                .replace_strict(ENTITY_TYPE_TO_SA_CLASS, default=ExposureClass.OTHER.value)
                .alias("_sa_class"),
                pl.col("cp_entity_type")
                .replace_strict(ENTITY_TYPE_TO_IRB_CLASS, default=ExposureClass.OTHER.value)
                .alias("_irb_class"),
                pl.col("product_type").str.to_uppercase().alias("_pt_upper"),
            ]
        )

        sl_class = pl.lit(ExposureClass.SPECIALISED_LENDING.value)

        # Batch 2: Derive all flags from pre-computed intermediates.
        return exposures.with_columns(
            [
                # --- Exposure class mappings (SL table overrides entity_type) ---
                pl.when(sl_override)
                .then(sl_class)
                .otherwise(pl.col("_sa_class"))
                .alias("exposure_class_sa"),
                pl.when(sl_override)
                .then(sl_class)
                .otherwise(pl.col("_irb_class"))
                .alias("exposure_class_irb"),
                pl.when(sl_override)
                .then(sl_class)
                .otherwise(pl.col("_sa_class"))
                .alias("exposure_class"),
                # --- Mortgage flag ---
                self._build_is_mortgage_expr(schema_names),
                # --- Default flags ---
                (pl.col("cp_default_status") == True)  # noqa: E712
                .alias("is_defaulted"),
                pl.when(pl.col("cp_default_status") == True)  # noqa: E712
                .then(pl.lit(ExposureClass.DEFAULTED.value))
                .when(sl_override)
                .then(sl_class)
                .otherwise(pl.col("_sa_class"))
                .alias("exposure_class_for_sa"),
                # --- Infrastructure flag (uses _pt_upper) ---
                pl.col("_pt_upper").str.contains("INFRASTRUCTURE").alias("is_infrastructure"),
                # --- Retail threshold check ---
                pl.when(pl.col("lending_group_adjusted_exposure") > max_retail_exposure)
                .then(pl.lit(False))
                .when(
                    (
                        pl.col("lending_group_adjusted_exposure")
                        .cast(pl.Float64, strict=False)
                        .abs()
                        < 1e-10
                    )
                    & (pl.col("exposure_for_retail_threshold") > max_retail_exposure)
                )
                .then(pl.lit(False))
                .otherwise(pl.lit(True))
                .alias("qualifies_as_retail"),
                pl.when(pl.col("residential_collateral_value") > 0)
                .then(pl.lit(True))
                .otherwise(pl.lit(False))
                .alias("retail_threshold_exclusion_applied"),
            ]
        ).drop(["_sa_class", "_irb_class", "_pt_upper"])

    # =========================================================================
    # Phase 3: SME + retail classification (1 .with_columns — 5 expressions)
    # =========================================================================

    def _classify_sme_and_retail(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        schema_names: set[str],
    ) -> pl.LazyFrame:
        """
        Merge SME, retail, and QRRE classification into a single .with_columns().

        Works because they operate on non-overlapping initial exposure_class values:
        SME only touches "corporate", retail only touches "retail_other",
        QRRE specialises qualifying revolving retail.

        Also derives requires_fi_scalar directly from the user-supplied
        apply_fi_scalar flag (no entity-type gate).

        Sets: exposure_class (updated), is_sme, requires_fi_scalar, is_hvcre
        """
        sme_threshold_gbp = float(
            config.supporting_factors.sme_turnover_threshold_eur * config.eur_gbp_rate
        )
        qrre_max_limit = float(config.retail_thresholds.qrre_max_limit)

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

        # QRRE qualification: revolving, retail, under QRRE limit (CRR Art. 147(5))
        has_revolving = "is_revolving" in schema_names
        has_facility_limit = "facility_limit" in schema_names

        is_qrre = pl.lit(False)
        if has_revolving and has_facility_limit:
            is_qrre = (
                (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
                & (pl.col("qualifies_as_retail") == True)  # noqa: E712
                & (pl.col("is_revolving") == True)  # noqa: E712
                & (pl.col("facility_limit").fill_null(float("inf")) <= qrre_max_limit)
            )

        return exposures.with_columns(
            [
                # --- exposure_class update (SME + retail + QRRE combined) ---
                # Priority order: mortgage, QRRE, SME retail, non-qualifying retail,
                # corporate SME, keep current.
                pl.when(
                    # Retail mortgage — stays RETAIL_MORTGAGE regardless of threshold
                    (pl.col("is_mortgage") == True)  # noqa: E712
                    & (
                        (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
                        | (pl.col("cp_entity_type") == "individual")
                    )
                )
                .then(pl.lit(ExposureClass.RETAIL_MORTGAGE.value))
                .when(
                    # QRRE: qualifying revolving retail under QRRE limit (Art. 147(5))
                    is_qrre
                )
                .then(pl.lit(ExposureClass.RETAIL_QRRE.value))
                .when(
                    # SME retail that doesn't qualify → CORPORATE_SME
                    is_retail_sme
                )
                .then(pl.lit(ExposureClass.CORPORATE_SME.value))
                .when(
                    # Other retail that doesn't qualify → CORPORATE
                    (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
                    & (pl.col("qualifies_as_retail") == False)  # noqa: E712
                )
                .then(pl.lit(ExposureClass.CORPORATE.value))
                .when(
                    # Corporate with SME revenue → CORPORATE_SME
                    is_corporate_sme
                )
                .then(pl.lit(ExposureClass.CORPORATE_SME.value))
                .otherwise(pl.col("exposure_class"))
                .alias("exposure_class"),
                # --- is_sme flag ---
                # True for: corporate SME OR retail reclassified to CORPORATE_SME
                (is_corporate_sme | is_retail_sme).alias("is_sme"),
                # --- FI scalar: user flag is authoritative (CRR Art. 153(2)) ---
                (pl.col("cp_apply_fi_scalar") == True)  # noqa: E712
                .fill_null(False)
                .alias("requires_fi_scalar"),
                # --- HVCRE flag (from specialised lending join, null → False) ---
                pl.col("is_hvcre").fill_null(False).alias("is_hvcre"),
            ]
        )

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
            ExposureClass.RETAIL_OTHER,
            ApproachType.AIRB,
        )
        airb_for_corporate = config.irb_permissions.is_permitted(
            ExposureClass.CORPORATE,
            ApproachType.AIRB,
        )

        # Short-circuit: reclassification not relevant
        if airb_for_corporate or not airb_for_retail:
            return exposures.with_columns(
                [
                    pl.lit(False).alias("reclassified_to_retail"),
                    pl.lit(False).alias("has_property_collateral"),
                ]
            )

        sme_turnover_threshold = float(
            config.supporting_factors.sme_turnover_threshold_eur * config.eur_gbp_rate
        )

        # Reclassification eligibility expression (inlined — not a column ref)
        reclassification_expr = (
            (
                pl.col("exposure_class").is_in(
                    [
                        ExposureClass.CORPORATE.value,
                        ExposureClass.CORPORATE_SME.value,
                    ]
                )
            )
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
        return exposures.with_columns(
            [
                reclassification_expr.alias("reclassified_to_retail"),
                has_property_expr.alias("has_property_collateral"),
                pl.when(reclassification_expr & has_property_expr)
                .then(pl.lit(ExposureClass.RETAIL_MORTGAGE.value))
                .when(reclassification_expr)
                .then(pl.lit(ExposureClass.RETAIL_OTHER.value))
                .otherwise(pl.col("exposure_class"))
                .alias("exposure_class"),
            ]
        )

    # =========================================================================
    # Phase 4b: Model-level permission resolution (optional)
    # =========================================================================

    def _resolve_model_permissions(
        self,
        exposures: pl.LazyFrame,
        model_permissions: pl.LazyFrame,
        schema_names: set[str],
    ) -> pl.LazyFrame:
        """
        Join exposures with model_permissions to produce per-row permission flags.

        model_id originates on internal ratings and is propagated to exposures by
        the rating inheritance pipeline. This method resolves which IRB approach each
        exposure is permitted to use based on:
        - model_id match (rating's model_id must exist in model_permissions)
        - exposure_class match
        - Geography filter: country_codes is null OR cp_country_code is in the list
        - Book code exclusion: excluded_book_codes is null OR book_code NOT in the list

        Priority: AIRB > FIRB. If a model has both, AIRB wins for exposures that
        also have modelled LGD; otherwise FIRB is used if the exposure has internal_pd.

        Sets: model_airb_permitted (bool), model_firb_permitted (bool),
              model_slotting_permitted (bool)

        Exposures without a model_id get all flags as False (→ SA fallback).
        """
        # Ensure model_id column exists on exposures
        if "model_id" not in schema_names:
            return exposures.with_columns(
                pl.lit(False).alias("model_airb_permitted"),
                pl.lit(False).alias("model_firb_permitted"),
                pl.lit(False).alias("model_slotting_permitted"),
            )

        # Cast model_id to String to handle null-typed columns (all values null)
        exposures = exposures.with_columns(pl.col("model_id").cast(pl.String))

        # Ensure optional columns exist (may be absent when user omits geography/book filters)
        mp_schema_names = set(model_permissions.collect_schema().names())
        if "country_codes" not in mp_schema_names:
            model_permissions = model_permissions.with_columns(
                pl.lit(None).cast(pl.String).alias("country_codes")
            )
        if "excluded_book_codes" not in mp_schema_names:
            model_permissions = model_permissions.with_columns(
                pl.lit(None).cast(pl.String).alias("excluded_book_codes")
            )

        # Join exposures with model_permissions on model_id
        # Each exposure may match multiple permission rows (AIRB + FIRB for same model)
        joined = exposures.join(
            model_permissions.select(
                pl.col("model_id").alias("mp_model_id"),
                pl.col("exposure_class").alias("mp_exposure_class"),
                pl.col("approach").alias("mp_approach"),
                pl.col("country_codes").alias("mp_country_codes"),
                pl.col("excluded_book_codes").alias("mp_excluded_book_codes"),
            ),
            left_on="model_id",
            right_on="mp_model_id",
            how="left",
        )

        # Apply filters: exposure_class match, geography, book code exclusion
        # A permission row is valid when:
        # 1. exposure_class matches
        # 2. geography passes (country_codes is null OR cp_country_code in list)
        # 3. book code not excluded (excluded_book_codes is null OR book_code NOT in list)
        exposure_class_match = pl.col("exposure_class") == pl.col("mp_exposure_class")

        geo_passes = pl.col("mp_country_codes").is_null() | (
            pl.col("mp_country_codes").str.contains(pl.col("cp_country_code"))
        )

        book_not_excluded = pl.col("mp_excluded_book_codes").is_null() | ~(
            pl.col("mp_excluded_book_codes").str.contains(pl.col("book_code"))
        )

        permission_valid = exposure_class_match & geo_passes & book_not_excluded

        # Compute per-row permission flags
        airb_permitted = (
            permission_valid & (pl.col("mp_approach") == ApproachType.AIRB.value)
        ).alias("_airb_match")
        firb_permitted = (
            permission_valid & (pl.col("mp_approach") == ApproachType.FIRB.value)
        ).alias("_firb_match")
        slotting_permitted = (
            permission_valid & (pl.col("mp_approach") == ApproachType.SLOTTING.value)
        ).alias("_slotting_match")

        # Add match flags then aggregate: group by all original columns,
        # take max of the match flags (any valid AIRB/FIRB/slotting permission → True)
        result = joined.with_columns(airb_permitted, firb_permitted, slotting_permitted)

        # Aggregate back to one row per exposure using .over() to avoid group_by
        result = result.with_columns(
            pl.col("_airb_match").max().over("exposure_reference").alias("model_airb_permitted"),
            pl.col("_firb_match").max().over("exposure_reference").alias("model_firb_permitted"),
            pl.col("_slotting_match")
            .max()
            .over("exposure_reference")
            .alias("model_slotting_permitted"),
        )

        # Drop the join columns and keep only one row per exposure
        result = result.select(
            pl.exclude(
                "mp_exposure_class",
                "mp_approach",
                "mp_country_codes",
                "mp_excluded_book_codes",
                "_airb_match",
                "_firb_match",
                "_slotting_match",
            )
        ).unique(subset=["exposure_reference"], keep="first")

        return result

    # =========================================================================
    # Phase 5: Approach assignment + finalization (1 .with_columns)
    # =========================================================================

    def _determine_approach_and_finalize(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        schema_names: set[str],
        *,
        has_model_permissions: bool = False,
    ) -> pl.LazyFrame:
        """
        Determine calculation approach and finalize classification.

        Single .with_columns() computing approach, LGD clearing for FIRB,
        and the classification audit string. Permission checks are inlined
        as pl.lit(bool) to avoid intermediate columns.

        When has_model_permissions=True, uses per-row model_airb_permitted /
        model_firb_permitted columns (set by _resolve_model_permissions) instead
        of org-wide pl.lit(bool) permission flags. AIRB additionally requires
        lgd to be non-null (bank-modelled LGD).

        Sets: approach, lgd (cleared for FIRB)
        """
        # Ensure internal_pd exists (added by hierarchy resolver; may be absent
        # when classifier is invoked directly in tests without full pipeline)
        if "internal_pd" not in schema_names:
            exposures = exposures.with_columns(pl.lit(None).cast(pl.Float64).alias("internal_pd"))

        if has_model_permissions:
            # Model-level SL permissions: per-row flags from _resolve_model_permissions
            sl_airb = pl.col("model_airb_permitted")
            sl_slotting = pl.col("model_slotting_permitted")
        else:
            # Org-wide SL permissions from config (STD mode or IRB fallback)
            sl_airb = pl.lit(
                config.irb_permissions.is_permitted(
                    ExposureClass.SPECIALISED_LENDING,
                    ApproachType.AIRB,
                )
            )
            sl_slotting = pl.lit(
                config.irb_permissions.is_permitted(
                    ExposureClass.SPECIALISED_LENDING,
                    ApproachType.SLOTTING,
                )
            )

        # Managed-as-retail-without-LGD must use SA
        managed_as_retail_without_lgd = (
            (pl.col("cp_is_managed_as_retail") == True)  # noqa: E712
            & (pl.col("qualifies_as_retail") == True)  # noqa: E712
            & (pl.col("lgd").is_null())
        )

        # IRB requires an internal rating (PD from the firm's IRB model).
        # Counterparties with only external ratings fall through to SA.
        has_internal_rating = pl.col("internal_pd").is_not_null()
        has_modelled_lgd = pl.col("lgd").is_not_null()

        if has_model_permissions:
            # --- Model-level permissions: per-row flags from _resolve_model_permissions ---
            # model_airb_permitted / model_firb_permitted are boolean columns
            # already filtered by exposure_class, geography, and book code.
            # AIRB additionally requires modelled LGD (bank-estimated LGD).
            airb_permitted_expr = (
                pl.col("model_airb_permitted") & has_internal_rating & has_modelled_lgd
            )
            firb_permitted_expr = pl.col("model_firb_permitted") & has_internal_rating
            firb_clear_expr = (
                pl.col("model_firb_permitted")
                & has_internal_rating
                & ~(pl.col("model_airb_permitted") & has_modelled_lgd)
            )
        else:
            # --- Org-wide permissions: pre-compute booleans Python-side ---
            airb_permitted_expr, firb_permitted_expr, firb_clear_expr = (
                self._build_orgwide_permission_exprs(config, has_internal_rating)
            )

        # Art. 114(3)/(4): EU domestic sovereign exposures must use SA
        # to receive the 0% RW — forced to standardised regardless of IRB permissions.
        _is_eu_domestic_sovereign = (
            pl.col("exposure_class") == ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value
        ) & build_eu_domestic_currency_expr("cp_country_code", "currency")

        # --- Approach expression ---
        # CCP exposures must always use SA (CRR Art. 300-311, CRE54)
        is_ccp = pl.col("cp_entity_type") == "ccp"

        approach_expr = (
            pl.when(managed_as_retail_without_lgd)
            .then(pl.lit(ApproachType.SA.value))
            # Art. 114(4): EU CGCB in domestic currency → forced SA (0% RW)
            .when(_is_eu_domestic_sovereign)
            .then(pl.lit(ApproachType.SA.value))
            # Qualifying CCP trade exposures — always SA with prescribed RW (CRE54.14-15)
            .when(is_ccp)
            .then(pl.lit(ApproachType.SA.value))
            # SL A-IRB takes precedence over slotting
            .when(
                (pl.col("exposure_class") == ExposureClass.SPECIALISED_LENDING.value)
                & sl_airb
                & has_internal_rating
            )
            .then(pl.lit(ApproachType.AIRB.value))
            # SL slotting fallback (slotting does not require internal rating)
            .when(
                (pl.col("exposure_class") == ExposureClass.SPECIALISED_LENDING.value) & sl_slotting
            )
            .then(pl.lit(ApproachType.SLOTTING.value))
            # A-IRB (model or org-wide)
            .when(airb_permitted_expr)
            .then(pl.lit(ApproachType.AIRB.value))
            # F-IRB (model or org-wide)
            .when(firb_permitted_expr)
            .then(pl.lit(ApproachType.FIRB.value))
            .otherwise(pl.lit(ApproachType.SA.value))
            .alias("approach")
        )

        # --- FIRB LGD clearing ---
        # Clear LGD when FIRB approach is chosen (FIRB uses regulatory supervisory LGD).
        # Must NOT clear for reclassified retail exposures.
        lgd_expr = (
            pl.when(firb_clear_expr & ~pl.col("reclassified_to_retail"))
            .then(pl.lit(None).cast(pl.Float64))
            .otherwise(pl.col("lgd"))
            .alias("lgd")
        )

        return exposures.with_columns(
            [
                approach_expr,
                lgd_expr,
            ]
        )

    @staticmethod
    def _build_orgwide_permission_exprs(
        config: CalculationConfig,
        has_internal_rating: pl.Expr,
    ) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
        """Build org-wide permission expressions (backward compat when no model_permissions).

        Returns (airb_permitted_expr, firb_permitted_expr, firb_clear_expr).
        """
        perms = config.irb_permissions.permissions
        airb_classes = [
            ec.value for ec, approaches in perms.items() if ApproachType.AIRB in approaches
        ]
        firb_classes = [
            ec.value for ec, approaches in perms.items() if ApproachType.FIRB in approaches
        ]
        firb_only_classes = [
            ec.value
            for ec, approaches in perms.items()
            if ApproachType.FIRB in approaches and ApproachType.AIRB not in approaches
        ]

        airb_expr = pl.col("exposure_class").is_in(airb_classes) & has_internal_rating
        firb_expr = pl.col("exposure_class").is_in(firb_classes) & has_internal_rating
        firb_clear = pl.col("exposure_class").is_in(firb_only_classes) & has_internal_rating

        return airb_expr, firb_expr, firb_clear

    # =========================================================================
    # Expression builders (static helpers returning pl.Expr)
    # =========================================================================

    @staticmethod
    def _build_is_mortgage_expr(schema_names: set[str]) -> pl.Expr:
        """Build is_mortgage expression, conditional on available columns.

        Uses _pt_upper (pre-computed uppercase product_type) when available.
        """
        base = pl.col("_pt_upper").str.contains("MORTGAGE") | pl.col("_pt_upper").str.contains(
            "HOME_LOAN"
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
            return (base | (pl.col("property_collateral_value") > 0)).alias("is_mortgage")
        return base.alias("is_mortgage")

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
    # Audit trail
    # =========================================================================

    def _build_audit_trail(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Build classification audit trail.

        Computes classification_reason here (deferred from main pipeline)
        since it's only needed for audit, not by downstream CRM/calculators.
        """
        return exposures.select(
            [
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
                pl.col("requires_fi_scalar"),
                pl.col("qualifies_as_retail"),
                pl.col("retail_threshold_exclusion_applied"),
                pl.col("residential_collateral_value"),
                pl.col("lending_group_adjusted_exposure"),
                pl.col("reclassified_to_retail"),
                pl.concat_str(
                    [
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
                    ]
                ).alias("classification_reason"),
            ]
        )
