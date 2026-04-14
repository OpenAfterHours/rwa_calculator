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
from rwa_calc.contracts.errors import (
    ERROR_MODEL_PERMISSION_UNMATCHED,
    ERROR_QRRE_COLUMNS_MISSING,
    ERROR_RETAIL_POOL_MGMT_MISSING,
    CalculationError,
    classification_warning,
)
from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.tables.eu_sovereign import (
    build_eu_domestic_currency_expr,
    denomination_currency_expr,
)
from rwa_calc.domain.enums import (
    ApproachType,
    ExposureClass,
    PermissionMode,
    SpecialisedLendingType,
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
    "mdb_named": ExposureClass.MDB.value,
    "international_org": ExposureClass.MDB.value,
    "institution": ExposureClass.INSTITUTION.value,
    "bank": ExposureClass.INSTITUTION.value,
    "ccp": ExposureClass.INSTITUTION.value,
    "financial_institution": ExposureClass.INSTITUTION.value,
    "corporate": ExposureClass.CORPORATE.value,
    "company": ExposureClass.CORPORATE.value,
    "individual": ExposureClass.RETAIL_OTHER.value,
    "retail": ExposureClass.RETAIL_OTHER.value,
    # Art. 112(1)(g): SL is a corporate sub-type under SA, not a separate class.
    # The sl_type column (from the specialised_lending join) drives SL-specific
    # risk weight lookup; the exposure_class_sa column is CORPORATE.
    "specialised_lending": ExposureClass.CORPORATE.value,
    "equity": ExposureClass.EQUITY.value,
    "covered_bond": ExposureClass.COVERED_BOND.value,
    "other_cash": ExposureClass.OTHER.value,
    "other_gold": ExposureClass.OTHER.value,
    "other_items_in_collection": ExposureClass.OTHER.value,
    "other_tangible": ExposureClass.OTHER.value,
    "other_residual_lease": ExposureClass.OTHER.value,
    # High-risk items (CRR Art. 128): 150% unconditional
    "high_risk": ExposureClass.HIGH_RISK.value,
    "high_risk_venture_capital": ExposureClass.HIGH_RISK.value,
    "high_risk_private_equity": ExposureClass.HIGH_RISK.value,
    "high_risk_speculative_re": ExposureClass.HIGH_RISK.value,
}

# entity_type → IRB exposure class (for IRB formula selection)
# Other Items (Art. 134) are SA-only — no IRB class exists for these.
# High-risk items (Art. 128) are SA-only — they map to HIGH_RISK for SA treatment.
ENTITY_TYPE_TO_IRB_CLASS: dict[str, str] = {
    "sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "central_bank": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "rgla_sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "rgla_institution": ExposureClass.INSTITUTION.value,
    "pse_sovereign": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "pse_institution": ExposureClass.INSTITUTION.value,
    "mdb": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
    "mdb_named": ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
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
    "other_cash": ExposureClass.OTHER.value,
    "other_gold": ExposureClass.OTHER.value,
    "other_items_in_collection": ExposureClass.OTHER.value,
    "other_tangible": ExposureClass.OTHER.value,
    "other_residual_lease": ExposureClass.OTHER.value,
    # High-risk items (Art. 128) are SA-only — they map to OTHER for IRB
    # (no separate IRB treatment; HIGH_RISK is an SA exposure class).
    "high_risk": ExposureClass.HIGH_RISK.value,
    "high_risk_venture_capital": ExposureClass.HIGH_RISK.value,
    "high_risk_private_equity": ExposureClass.HIGH_RISK.value,
    "high_risk_speculative_re": ExposureClass.HIGH_RISK.value,
}

# SL types restricted to slotting-only under B31 Art. 147A(1)(c)
_B31_SLOTTING_ONLY_SL_TYPES = {
    SpecialisedLendingType.IPRE.value,
    SpecialisedLendingType.HVCRE.value,
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

        # Accumulate classification warnings/errors
        classification_errors: list[CalculationError] = []

        # Check for QRRE classification prerequisites — missing columns
        # cause all revolving retail to silently become RETAIL_OTHER
        missing_qrre_cols = [c for c in ("is_revolving", "facility_limit") if c not in schema_names]
        if missing_qrre_cols:
            classification_errors.append(
                classification_warning(
                    code=ERROR_QRRE_COLUMNS_MISSING,
                    message=(
                        f"QRRE classification disabled — column(s) "
                        f"{', '.join(missing_qrre_cols)} missing from exposure data. "
                        f"All qualifying revolving retail exposures will be classified "
                        f"as RETAIL_OTHER instead of RETAIL_QRRE, which may affect "
                        f"risk weights and IRB parameters."
                    ),
                    regulatory_reference="CRR Art. 147(5)",
                )
            )

        # Art. 123A(1)(b)(iii): Under Basel 3.1, non-SME retail qualification
        # requires pool management attestation (is_managed_as_retail).  When the
        # column is absent from the ORIGINAL counterparty data, condition 3 cannot
        # be enforced and all non-SME retail exposures default to qualifying.
        # Check the counterparty source (not schema_names, which always has
        # the column after Phase 1 adds a null default).
        cp_has_managed_flag = "is_managed_as_retail" in set(
            data.counterparty_lookup.counterparties.collect_schema().names()
        )
        if config.is_basel_3_1 and not cp_has_managed_flag:
            classification_errors.append(
                classification_warning(
                    code=ERROR_RETAIL_POOL_MGMT_MISSING,
                    message=(
                        "Art. 123A(1)(b)(iii) pool management condition cannot be "
                        "enforced — 'is_managed_as_retail' column missing from "
                        "counterparty data. Non-SME retail exposures will default "
                        "to qualifying status (75% RW) without verification."
                    ),
                    regulatory_reference="PRA PS1/26 Art. 123A(1)(b)(iii)",
                )
            )

        # Step 2: Derive all independent flags (1 .with_columns)
        classified = self._derive_independent_flags(exposures, config, schema_names)

        # Step 3: Exposure subtype classification (1 .with_columns)
        classified = self._classify_exposure_subtypes(classified, config, schema_names)

        # Step 4: Corporate → retail reclassification (1 .with_columns)
        classified = self._reclassify_corporate_to_retail(
            classified,
            config,
            schema_names,
        )

        # Step 4b: Model-level permission resolution (optional, 1 join + filter)
        # When model_permissions data is present, resolve per-row AIRB/FIRB permissions.
        # Otherwise, falls back to org-wide IRBPermissions in _assign_approach.
        model_permissions = data.model_permissions
        if model_permissions is not None:
            classified = self._resolve_model_permissions(
                classified, model_permissions, schema_names
            )
            # Diagnostic roll-up: count IRB-eligible exposures (internal_pd
            # non-null) that failed to receive a model permission match,
            # grouped by cause. One cheap .collect() over a narrow projection
            # (3-element group_by on a String column). Surfaces CLS006 warnings
            # so users can see WHY exposures silently routed to SA.
            diagnostic_counts = (
                classified.filter(pl.col("internal_pd").is_not_null())
                .filter(pl.col("_model_permission_diagnostic").is_not_null())
                .group_by("_model_permission_diagnostic")
                .agg(pl.len().alias("n"))
                .collect()
            )
            for row in diagnostic_counts.iter_rows(named=True):
                classification_errors.append(
                    _build_model_permission_warning(row["_model_permission_diagnostic"], row["n"])
                )
            classified = classified.drop("_model_permission_diagnostic")

        # Step 5: Approach assignment (1 .with_columns)
        classified = self._assign_approach(
            classified,
            config,
            schema_names,
            has_model_permissions=model_permissions is not None,
        )

        # Step 6: Split by approach (filter/select — no depth added)
        sa_exposures = classified.filter(
            pl.col("approach").is_in([ApproachType.SA.value, ApproachType.EQUITY.value])
        )
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
            classification_errors=classification_errors,
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
        ]

        # is_managed_as_retail — optional; used by Art. 123A(1)(b)(iii) condition 3
        # and SME retail treatment (Art. 123).  When absent, defaults handled downstream.
        if "is_managed_as_retail" in cp_col_names:
            select_cols.append(pl.col("is_managed_as_retail").alias("cp_is_managed_as_retail"))

        # Natural person flag — Art. 124H CRE counterparty type (optional in input data)
        if "is_natural_person" in cp_col_names:
            select_cols.append(pl.col("is_natural_person").alias("cp_is_natural_person"))

        # Social housing flag — Art. 124L RRE residual RW routing (optional in input data)
        if "is_social_housing" in cp_col_names:
            select_cols.append(pl.col("is_social_housing").alias("cp_is_social_housing"))

        # FSE flag — Art. 147A(1)(e) approach restriction (optional in input data)
        if "is_financial_sector_entity" in cp_col_names:
            select_cols.append(
                pl.col("is_financial_sector_entity").alias("cp_is_financial_sector_entity")
            )

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

        # Sovereign floor for FX institution exposures (Art. 121(6) / CRE20.22)
        if "sovereign_cqs" in cp_col_names:
            select_cols.append(pl.col("sovereign_cqs").alias("cp_sovereign_cqs"))
        if "local_currency" in cp_col_names:
            select_cols.append(pl.col("local_currency").alias("cp_local_currency"))

        # Covered bond issuer institution CQS (Art. 129(5) derivation)
        if "institution_cqs" in cp_col_names:
            select_cols.append(pl.col("institution_cqs").alias("cp_institution_cqs"))

        cp_cols = counterparties.select(select_cols)

        joined = exposures.join(
            cp_cols,
            on="counterparty_reference",
            how="left",
        )

        # Ensure cp_is_managed_as_retail always exists — nullable Boolean.
        # When absent from counterparty data, defaults to null (downstream
        # fill_null(True) preserves backward-compatible qualifying behavior).
        joined = ensure_columns(
            joined,
            {"cp_is_managed_as_retail": ColumnSpec(pl.Boolean, required=False)},
        )
        return joined

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

        Art. 123A enforcement (Basel 3.1 only):
        - Art. 123A(1)(a): SME entities (revenue > 0 and < threshold) auto-qualify
          for retail treatment without needing conditions 1/3.
        - Art. 123A(1)(b)(iii): Non-SME entities must be managed as part of a
          retail pool (cp_is_managed_as_retail=True). Null defaults to True for
          backward compatibility.
        - CRR: threshold check only (no Art. 123A).
        """
        max_retail_exposure = float(config.thresholds.retail_max_exposure)

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
        # Art. 112 Table A2: Under SA, specialised lending is a corporate sub-type
        # (Art. 112(1)(g)), not a separate exposure class.  exposure_class_sa reflects
        # this by mapping SL → CORPORATE.  exposure_class retains SPECIALISED_LENDING
        # because approach routing (Phase 5) needs it for slotting/AIRB selection.
        sl_sa_class = pl.lit(ExposureClass.CORPORATE.value)

        # Batch 2: Derive all flags from pre-computed intermediates.
        return exposures.with_columns(
            [
                # --- Exposure class mappings (SL table overrides entity_type) ---
                # SA class: SL is a corporate sub-type (Art. 112(1)(g))
                pl.when(sl_override)
                .then(sl_sa_class)
                .otherwise(pl.col("_sa_class"))
                .alias("exposure_class_sa"),
                # IRB class: SL is a legitimate sub-class (Art. 147(8))
                pl.when(sl_override)
                .then(sl_class)
                .otherwise(pl.col("_irb_class"))
                .alias("exposure_class_irb"),
                # Primary class: retains SPECIALISED_LENDING for approach routing
                pl.when(sl_override)
                .then(sl_class)
                .otherwise(pl.col("_sa_class"))
                .alias("exposure_class"),
                # --- Mortgage flag ---
                self._build_is_mortgage_expr(schema_names),
                # --- Default flags ---
                (pl.col("cp_default_status") == True)  # noqa: E712
                .alias("is_defaulted"),
                # Art. 112 Table A2: HIGH_RISK (priority 4) takes precedence over
                # DEFAULTED (priority 5). A defaulted high-risk item retains 150% per
                # Art. 128, not the provision-based 100%/150% of Art. 127.
                pl.when(
                    (pl.col("cp_default_status") == True)  # noqa: E712
                    & (pl.col("_sa_class") != ExposureClass.HIGH_RISK.value)
                )
                .then(pl.lit(ExposureClass.DEFAULTED.value))
                .when(sl_override)
                .then(sl_sa_class)
                .otherwise(pl.col("_sa_class"))
                .alias("exposure_class_for_sa"),
                # --- Infrastructure flag (uses _pt_upper) ---
                pl.col("_pt_upper").str.contains("INFRASTRUCTURE").alias("is_infrastructure"),
                # --- Retail threshold check + Art. 123A conditions (B31) ---
                self._build_qualifies_as_retail_expr(config, schema_names, max_retail_exposure),
                pl.when(pl.col("residential_collateral_value") > 0)
                .then(pl.lit(True))
                .otherwise(pl.lit(False))
                .alias("retail_threshold_exclusion_applied"),
            ]
        ).drop(["_sa_class", "_irb_class", "_pt_upper"])

    # =========================================================================
    # Phase 3: Exposure subtype classification (1 .with_columns — 5 expressions)
    # =========================================================================

    def _classify_exposure_subtypes(
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
        sme_threshold_gbp = float(config.thresholds.sme_turnover_threshold)
        qrre_max_limit = float(config.thresholds.qrre_max_limit)

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
        Reclassify qualifying corporates to retail.

        Retail outranks corporate in the exposure class waterfall per
        CRR Art. 147(5) / Basel CRE30.16-17. Corporate exposures are
        reclassified to retail when all of:
        1. Managed as part of a retail pool (is_managed_as_retail=True)
        2. Aggregated exposure < EUR 1m (qualifies_as_retail=True)
        3. Has internally modelled LGD (lgd IS NOT NULL)
        4. Turnover < EUR 50m (SME definition per CRR Art. 501)

        Reclassification is an exposure-class decision, independent of
        approach permissions. The approach (AIRB/FIRB/SA) is determined
        later by _assign_approach using model_permissions.
        """
        sme_turnover_threshold = float(config.thresholds.sme_turnover_threshold)

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

        # Track whether the join produced any matching permission row for this
        # exposure (before filters are applied). Used downstream to distinguish
        # "model_id did not match any permission row" from "model_id matched
        # but filters rejected every row", so the diagnostic column can point
        # the user at the right remediation. Note: Polars drops the right
        # join key (mp_model_id) when left_on != right_on, so we probe via
        # mp_exposure_class which stays in the joined frame.
        joined = joined.with_columns(
            pl.col("mp_exposure_class").is_not_null().alias("_mp_row_joined")
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
            pl.col("_mp_row_joined").max().over("exposure_reference").alias("_mp_joined_any"),
        )

        # Diagnostic column: tag WHY a row did not get an IRB permission match.
        # Three causes with distinct remediations:
        #   null_model_id       → rating.model_id is null (fix ratings table)
        #   unmatched_model_id  → model_id absent from model_permissions (stale ref)
        #   filter_rejected     → matched but filtered by class/geo/book scope
        # Null when the exposure DID get a match (happy path).
        has_any_match = (
            pl.col("model_airb_permitted")
            | pl.col("model_firb_permitted")
            | pl.col("model_slotting_permitted")
        )
        result = result.with_columns(
            pl.when(has_any_match)
            .then(pl.lit(None, dtype=pl.String))
            .when(pl.col("model_id").is_null())
            .then(pl.lit("null_model_id"))
            .when(~pl.col("_mp_joined_any"))
            .then(pl.lit("unmatched_model_id"))
            .otherwise(pl.lit("filter_rejected"))
            .alias("_model_permission_diagnostic")
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
                "_mp_row_joined",
                "_mp_joined_any",
            )
        ).unique(subset=["exposure_reference"], keep="first")

        return result

    # =========================================================================
    # Phase 5: Approach assignment (1 .with_columns)
    # =========================================================================

    def _assign_approach(
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
        elif config.permission_mode == PermissionMode.IRB:
            # IRB mode requires model_permissions to gate per-model approval.
            # Without it, no exposure can be granted IRB — fall back to SA.
            sl_airb = pl.lit(False)
            sl_slotting = pl.lit(False)
        else:
            # SA-only mode: org-wide SL permissions from config
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
        elif config.permission_mode == PermissionMode.IRB:
            # IRB mode requires model_permissions to gate per-model approval.
            # Without it, no exposure can be granted IRB — fall back to SA.
            airb_permitted_expr = pl.lit(False)
            firb_permitted_expr = pl.lit(False)
            firb_clear_expr = pl.lit(False)
        else:
            # --- Org-wide permissions: pre-compute booleans Python-side ---
            airb_permitted_expr, firb_permitted_expr, firb_clear_expr = (
                self._build_orgwide_permission_exprs(config, has_internal_rating)
            )

        # Art. 114(3)/(4): EU domestic sovereign exposures must use SA
        # to receive the 0% RW — forced to standardised regardless of IRB permissions.
        # Use original (pre-FX) denomination — `currency` is overwritten by the
        # FX converter with the reporting currency, which would otherwise reject
        # legitimate Art. 114(4) treatment for any non-base-currency exposure.
        _is_eu_domestic_sovereign = (
            pl.col("exposure_class") == ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value
        ) & build_eu_domestic_currency_expr(
            "cp_country_code", denomination_currency_expr(schema_names)
        )

        # --- B31 Art. 147A classifier-level approach restrictions ---
        # These supplement the permissions-level restrictions in full_irb_b31()
        # with data-dependent checks that cannot be encoded in the permission map.
        _b31_ipre_hvcre_forced_slotting = pl.lit(False)
        if config.is_basel_3_1:
            # Art. 147A(1)(c): IPRE/HVCRE → slotting only
            _b31_ipre_hvcre_forced_slotting = (
                pl.col("exposure_class") == ExposureClass.SPECIALISED_LENDING.value
            ) & pl.col("sl_type").is_in(list(_B31_SLOTTING_ONLY_SL_TYPES))

            # Art. 147A(1)(d)/(e): FSE and large corporates → F-IRB only (no A-IRB)
            _is_fse = pl.lit(False)
            if "cp_is_financial_sector_entity" in schema_names:
                _is_fse = (
                    (pl.col("cp_is_financial_sector_entity") == True)  # noqa: E712
                    .fill_null(False)
                )
            _is_large_corp = (
                pl.col("cp_annual_revenue")
                > float(config.thresholds.large_corporate_revenue_threshold)
            ).fill_null(False)

            # Art. 147A(1)(b): Institution → F-IRB only (no A-IRB)
            # Supplements full_irb_b31() org-wide restriction; needed when
            # model_permissions grant AIRB for institutions.
            _b31_institution_no_airb = pl.col("exposure_class") == ExposureClass.INSTITUTION.value

            _b31_airb_blocked = _is_fse | _is_large_corp | _b31_institution_no_airb

            # Art. 147A(1)(a): CGCB, PSE, MDB, RGLA → SA only (no IRB at all)
            # Supplements full_irb_b31() org-wide restriction; ensures these
            # classes use SA even when model_permissions attempt to grant IRB.
            _b31_sa_only = pl.col("exposure_class").is_in(
                [
                    ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value,
                    ExposureClass.PSE.value,
                    ExposureClass.MDB.value,
                    ExposureClass.RGLA.value,
                ]
            )

            # Remove AIRB eligibility for B31-restricted exposures and SA-only classes
            airb_permitted_expr = airb_permitted_expr & ~_b31_airb_blocked & ~_b31_sa_only
            # Expand FIRB LGD clearing to include exposures whose AIRB was blocked
            firb_clear_expr = firb_clear_expr | (firb_permitted_expr & _b31_airb_blocked)
            # Remove FIRB eligibility for SA-only classes
            firb_permitted_expr = firb_permitted_expr & ~_b31_sa_only

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
            # B31 Art. 147A(1)(c): IPRE/HVCRE → slotting only (overrides model perms)
            .when(_b31_ipre_hvcre_forced_slotting)
            .then(pl.lit(ApproachType.SLOTTING.value))
            # SL A-IRB takes precedence over slotting (non-IPRE/HVCRE under B31)
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
            # A-IRB (model or org-wide, with B31 FSE/large-corp restriction applied)
            .when(airb_permitted_expr)
            .then(pl.lit(ApproachType.AIRB.value))
            # F-IRB (model or org-wide)
            .when(firb_permitted_expr)
            .then(pl.lit(ApproachType.FIRB.value))
            # Equity exposure class → EQUITY approach (routes to SA equity RW logic;
            # full equity treatment requires the dedicated equity_exposures table)
            .when(pl.col("exposure_class") == ExposureClass.EQUITY.value)
            .then(pl.lit(ApproachType.EQUITY.value))
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
    def _build_qualifies_as_retail_expr(
        config: CalculationConfig,
        schema_names: set[str],
        max_retail_exposure: float,
    ) -> pl.Expr:
        """Build qualifies_as_retail expression with Art. 123A enforcement.

        CRR: Threshold check only — aggregated exposure ≤ EUR 1m.

        Basel 3.1 Art. 123A adds two-path qualifying criteria:
        - Art. 123A(1)(a): SME entities (revenue > 0 and < GBP 44m) auto-qualify
          without needing pool management attestation.
        - Art. 123A(1)(b)(iii): Non-SME entities must be managed as part of a
          retail pool (cp_is_managed_as_retail=True) to qualify.  Null values
          default to True for backward compatibility.

        References:
            PRA PS1/26 Art. 123A(1)(a)-(b), CRR Art. 123
        """
        # Base conditions: lending group threshold check (CRR + B31)
        threshold_fail = pl.col("lending_group_adjusted_exposure") > max_retail_exposure
        zero_lending_group_fail = (
            pl.col("lending_group_adjusted_exposure").cast(pl.Float64, strict=False).abs() < 1e-10
        ) & (pl.col("exposure_for_retail_threshold") > max_retail_exposure)

        if not config.is_basel_3_1:
            # CRR: threshold check only
            return (
                pl.when(threshold_fail)
                .then(pl.lit(False))
                .when(zero_lending_group_fail)
                .then(pl.lit(False))
                .otherwise(pl.lit(True))
                .alias("qualifies_as_retail")
            )

        # Basel 3.1: Art. 123A two-path qualifying criteria
        sme_threshold = float(config.thresholds.sme_turnover_threshold)

        # Art. 123A(1)(a): SME auto-qualification — revenue > 0 and < threshold
        is_sme_for_art_123a = (pl.col("cp_annual_revenue").fill_null(0.0) > 0) & (
            pl.col("cp_annual_revenue") < sme_threshold
        )

        expr = (
            pl.when(threshold_fail)
            .then(pl.lit(False))
            .when(zero_lending_group_fail)
            .then(pl.lit(False))
            # Art. 123A(1)(a): SMEs auto-qualify — no condition 3 needed
            .when(is_sme_for_art_123a)
            .then(pl.lit(True))
        )

        # Art. 123A(1)(b)(iii): Non-SME must be managed as retail pool
        if "cp_is_managed_as_retail" in schema_names:
            expr = expr.when(
                pl.col("cp_is_managed_as_retail").fill_null(True) == False  # noqa: E712
            ).then(pl.lit(False))

        return expr.otherwise(pl.lit(True)).alias("qualifies_as_retail")

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


# =============================================================================
# Private helpers
# =============================================================================


def _build_model_permission_warning(cause: str, n: int) -> CalculationError:
    """Build a CLS006 classification warning for a model permission miss.

    Three distinct causes, each with a specific remediation:
    - ``null_model_id``: ratings table lacks model_id → fix the ratings input
    - ``unmatched_model_id``: stale reference → fix the model_permissions table
    - ``filter_rejected``: scope mismatch → check exposure_class / country_codes
      / excluded_book_codes filters on the permission row
    """
    messages = {
        "null_model_id": (
            f"{n} exposure(s) with internal ratings were routed to Standardised "
            f"Approach because their rating has no model_id. Check the ratings "
            f"table (model_id column) and rating inheritance."
        ),
        "unmatched_model_id": (
            f"{n} exposure(s) with internal ratings were routed to Standardised "
            f"Approach because their model_id does not appear in the "
            f"model_permissions table. Check for stale model references."
        ),
        "filter_rejected": (
            f"{n} exposure(s) with internal ratings were routed to Standardised "
            f"Approach because all matching model_permissions rows were filtered "
            f"out by exposure_class / country_codes / excluded_book_codes. "
            f"Check permission scope."
        ),
    }
    return classification_warning(
        code=ERROR_MODEL_PERMISSION_UNMATCHED,
        message=messages[cause],
        regulatory_reference="PRA PS1/26 / CRR Art. 143",
    )
