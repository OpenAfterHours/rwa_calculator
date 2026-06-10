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

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    ResolvedHierarchyBundle,
)
from rwa_calc.contracts.errors import (
    ERROR_FSE_COLUMN_MISSING,
    ERROR_LARGE_CORP_REVENUE_NULL,
    ERROR_MODEL_PERMISSION_UNMATCHED,
    ERROR_QRRE_COLUMNS_MISSING,
    ERROR_RETAIL_POOL_MGMT_MISSING,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    beel_on_non_defaulted_exposure_warning,
    classification_warning,
)
from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.schemas import (
    B31_SOVEREIGN_LIKE_ENTITY_TYPES,
    RGLA_PSE_ENTITY_TYPES,
)
from rwa_calc.data.tables.b31_risk_weights import (
    B31_RETAIL_GRANULARITY_LIMIT,
    B31_RRE_THREE_PROPERTY_LIMIT,
)
from rwa_calc.data.tables.entity_class_mapping import (
    ENTITY_TYPE_TO_IRB_CLASS,
    ENTITY_TYPE_TO_SA_CLASS,
)
from rwa_calc.data.tables.eu_sovereign import (
    build_eu_domestic_currency_expr,
    denomination_currency_expr,
)
from rwa_calc.domain.enums import (
    ApproachType,
    ExposureClass,
    ExposureSubclass,
    PermissionMode,
    SpecialisedLendingType,
)
from rwa_calc.engine.materialise import materialise_barrier
from rwa_calc.engine.utils import partition_by_nullable

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)


# Entity-type → exposure-class mappings live in ``data/tables/entity_class_mapping``.
# Re-exported here because ``rwa_calc.engine.classifier`` is the long-standing
# public-import location for ``ENTITY_TYPE_TO_SA_CLASS`` and
# ``ENTITY_TYPE_TO_IRB_CLASS``; downstream tests, notebooks, and the engine's
# own SA / IRB / CRM guarantee branches import them via this module.
# ``ENTITY_TYPES_BY_SA_CLASS`` is consumed only by ``engine/hierarchy.py``,
# which imports it directly from ``data.tables.entity_class_mapping``.

# SL types restricted to slotting-only under B31 Art. 147A(1)(c)
_B31_SLOTTING_ONLY_SL_TYPES = {
    SpecialisedLendingType.IPRE.value,
    SpecialisedLendingType.HVCRE.value,
}

# Target exposure-class labels used by the RE loan-splitter. Sourced from
# ``ExposureClass`` so the lowercase enum convention (e.g. ``"retail_mortgage"``)
# extends consistently to the loan-splitter outputs. The SA calculator's RE
# branch in ``engine/sa/namespace.py`` uppercases ``exposure_class`` before
# substring-matching, so either case routes correctly.
_SECURED_TARGET_RESIDENTIAL = ExposureClass.RESIDENTIAL_MORTGAGE.value
_SECURED_TARGET_COMMERCIAL = ExposureClass.COMMERCIAL_MORTGAGE.value


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

    @cites("CRR Art. 112")
    @cites("CRR Art. 147")
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
        # Reads top-to-bottom as a recipe; each helper owns one regulatory
        # concept. See section banners below for per-step regulatory references.
        exposures = self._add_counterparty_attributes(
            data.exposures,
            data.counterparty_lookup.counterparties,
        )
        exposures = self._join_specialised_lending(exposures, data.specialised_lending)

        # Single schema snapshot — used by every downstream helper to gate
        # schema-conditional expressions without re-scanning the LazyFrame.
        schema_names = set(exposures.collect_schema().names())

        classification_errors = self._collect_input_warnings(data, schema_names, config)

        classified = self._derive_independent_flags(exposures, config, schema_names)
        classified = self._classify_exposure_subtypes(classified, config, schema_names)
        classified = self._reclassify_corporate_to_retail(classified, config, schema_names)
        classified = self._flag_property_reclassification_candidates(
            classified, config, schema_names
        )
        classified = self._sync_irb_exposure_class(classified)

        has_model_permissions = data.model_permissions is not None
        if has_model_permissions:
            classified = self._resolve_model_permissions(
                classified, data.model_permissions, schema_names
            )

        classified = self._assign_approach(
            classified,
            config,
            schema_names,
            has_model_permissions=has_model_permissions,
        )
        classified = self._derive_exposure_subclass(classified, config, schema_names)

        # Single materialisation barrier — both diagnostic emits below run
        # against in-memory data instead of re-executing the upstream lazy
        # plan, and the bundle returned downstream (CRMProcessor) reuses the
        # same materialised data instead of paying upstream cost a third time.
        # At 100K scale this saves ~880 ms / ~14 % of total pipeline time
        # vs the previous "emit-then-materialise-later" arrangement.
        classified = materialise_barrier(classified, config, "classifier_output")

        classification_errors.extend(
            self._collect_beel_on_non_defaulted_warnings(classified, schema_names)
        )
        if has_model_permissions:
            classification_errors.extend(self._emit_model_permission_diagnostics(classified))
            classified = classified.drop("_model_permission_diagnostic")

        return self._build_bundle(classified, data, classification_errors)

    @staticmethod
    def _join_specialised_lending(
        exposures: pl.LazyFrame,
        sl_data: pl.LazyFrame | None,
    ) -> pl.LazyFrame:
        """Join specialised lending metadata onto exposures by counterparty.

        Adds ``sl_type``, ``slotting_category``, ``is_hvcre``. When no SL
        data is supplied, the columns are added as null literals so
        downstream helpers can rely on their presence.
        """
        if sl_data is not None:
            return exposures.join(
                sl_data.select(
                    ["counterparty_reference", "sl_type", "slotting_category", "is_hvcre"]
                ),
                on="counterparty_reference",
                how="left",
            )
        return exposures.with_columns(
            pl.lit(None).cast(pl.String).alias("sl_type"),
            pl.lit(None).cast(pl.String).alias("slotting_category"),
            pl.lit(None).cast(pl.Boolean).alias("is_hvcre"),
        )

    @staticmethod
    def _sync_irb_exposure_class(exposures: pl.LazyFrame) -> pl.LazyFrame:
        """Sync exposure_class_irb with the (possibly mutated) exposure_class.

        Subtype classification and corporate→retail reclassification mutate
        ``exposure_class`` in place without touching ``exposure_class_irb``,
        which was set once in ``_add_counterparty_attributes``. Re-align them
        so downstream IRB permission lookups and approach filters see the
        reclassified class.

        rgla_* / pse_* entity types are excluded because their SA and IRB
        classes are definitionally different (CRR Art. 147(3)/147(4)(b)) —
        ``exposure_class_irb`` already carries the correct CGCB / INSTITUTION
        value from ``ENTITY_TYPE_TO_IRB_CLASS`` and must not be overwritten.
        """
        return exposures.with_columns(
            pl.when(pl.col("cp_entity_type").is_in(list(RGLA_PSE_ENTITY_TYPES)))
            .then(pl.col("exposure_class_irb"))
            .otherwise(pl.col("exposure_class"))
            .alias("exposure_class_irb")
        )

    @staticmethod
    def _emit_model_permission_diagnostics(
        classified: pl.LazyFrame,
    ) -> list[CalculationError]:
        """Emit CLS006 warnings for IRB-eligible exposures that failed model match.

        Reads ``_model_permission_diagnostic`` (added by
        ``_resolve_model_permissions``) and rolls up the failure causes
        (``null_model_id`` / ``unmatched_model_id`` / ``filter_rejected``)
        into one warning per cause. The caller must drop the diagnostic
        column from the frame after this returns.

        This runs **after** the classifier's single materialise barrier so
        the underlying ``.collect()`` reads in-memory data rather than
        re-executing the upstream join plan. See ``classify()``.
        """
        diagnostic_counts = (
            classified.filter(pl.col("internal_pd").is_not_null())
            .filter(pl.col("_model_permission_diagnostic").is_not_null())
            .group_by("_model_permission_diagnostic")
            .agg(pl.len().alias("n"))
            .collect()
        )
        return [
            _build_model_permission_warning(row["_model_permission_diagnostic"], row["n"])
            for row in diagnostic_counts.iter_rows(named=True)
        ]

    @staticmethod
    def _collect_beel_on_non_defaulted_warnings(
        classified: pl.LazyFrame,
        schema_names: set[str],
    ) -> list[CalculationError]:
        """Emit a single aggregate DQ008 warning summing ``(is_defaulted=False ∧ beel>0)`` rows.

        PS1/26 Art. 181(1)(h)(ii) and CRR Art. 158(5) define BEEL only for
        defaulted exposures, but a firm's A-IRB model pipeline may emit a
        BEEL-style value alongside LGD on performing rows. The classifier
        deliberately does NOT treat ``beel > 0`` as a default trigger (see
        ``_build_is_defaulted_expr``); this companion check surfaces the
        input contradiction as a non-blocking data-quality warning so the
        audit trail is explicit.

        Returns an empty list when ``beel`` is absent from the schema or
        no rows are offending. Otherwise returns a single-element list
        carrying the total count, matching the CLS006 / CLS008 roll-up
        pattern used by every other classifier-stage warning. Reads the
        *derived* ``is_defaulted`` so rows that the counterparty cascade
        legitimately routes to defaulted are NOT flagged — those rows
        correctly consume BEEL in the IRB defaulted formula.
        """
        if "beel" not in schema_names:
            return []
        offender_count = (
            classified.filter(
                ~pl.col("is_defaulted").fill_null(False) & (pl.col("beel").fill_null(0.0) > 0.0)
            )
            .select(pl.len())
            .collect()
            .item()
        )
        if offender_count == 0:
            return []
        return [beel_on_non_defaulted_exposure_warning(n=offender_count)]

    def _build_bundle(
        self,
        classified: pl.LazyFrame,
        data: ResolvedHierarchyBundle,
        classification_errors: list[CalculationError],
    ) -> ClassifiedExposuresBundle:
        """Split classified exposures by approach and assemble the output bundle."""
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
            collateral_links=data.collateral_links,
            guarantees=data.guarantees,
            provisions=data.provisions,
            counterparty_lookup=data.counterparty_lookup,
            classification_audit=classification_audit,
            securitisation_audit=data.securitisation_audit,
            classification_errors=classification_errors,
        )

    # =========================================================================
    # Counterparty attribute join
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
        - annual_revenue (primary SME size signal — CRR Art. 4(1)(128D))
        - total_assets (SME size fallback when annual_revenue is null;
          also feeds the LFSE threshold and equity NAV check)
        - default_status
        - country_code
        - apply_fi_scalar (for FI scalar - LFSE/unregulated FSE)
        - is_managed_as_retail (for SME retail treatment)

        Also derives the consolidated SME size metric used by every
        classification gate (corporate-SME, retail-SME, SL-SME, Art. 123
        reclassification, Art. 123A retail qualification, Art. 147A(1)(d)
        large-corporate F-IRB restriction) and by the IRB Art. 153(4)
        correlation adjustment:
        - sme_size_metric_gbp = coalesce(cp_annual_revenue, cp_total_assets)
        - sme_size_source     = "turnover" | "assets" | null
        Art. 501 supporting factor deliberately ignores this column and
        keys off cp_annual_revenue directly (Art. 501(2)(c)).
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

        # Three-property limit count — PRA PS1/26 Art. 124E(1)(b): drives the
        # income-producing re-route for natural-person RRE (optional in input data).
        if "qualifying_property_count" in cp_col_names:
            select_cols.append(
                pl.col("qualifying_property_count").alias("cp_qualifying_property_count")
            )

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

        # QCCP flag (CRR Art. 272 Def (88)) — gates the Art. 306(1) 2%/4% trade
        # exposure pin so a ``ccp`` entity_type with an explicit is_qccp=False
        # falls through to the standard institution ladder (Art. 107(2)(a)).
        if "is_qccp" in cp_col_names:
            select_cols.append(pl.col("is_qccp").alias("cp_is_qccp"))

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

        # ECA / MEIP score for unrated sovereign Art. 137(1)-(2) Table 9 path.
        if "eca_score" in cp_col_names:
            select_cols.append(pl.col("eca_score").alias("cp_eca_score"))

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

        # SME size metric (CRR Art. 4(1)(128D) / Commission Rec 2003/361/EC):
        # turnover when present, total assets otherwise. Every SME
        # classification gate downstream reads sme_size_metric_gbp together
        # with sme_size_source so the threshold can be turnover- or
        # balance-sheet-keyed without re-reading the raw cp_ columns.
        # Null on both fields → null metric → no SME treatment.
        joined = joined.with_columns(
            [
                pl.coalesce([pl.col("cp_annual_revenue"), pl.col("cp_total_assets")]).alias(
                    "sme_size_metric_gbp"
                ),
                pl.when(pl.col("cp_annual_revenue").is_not_null())
                .then(pl.lit("turnover"))
                .when(pl.col("cp_total_assets").is_not_null())
                .then(pl.lit("assets"))
                .otherwise(pl.lit(None, dtype=pl.String))
                .alias("sme_size_source"),
            ]
        )
        return joined

    # =========================================================================
    # Input-data warnings (non-blocking; collected as CalculationError list)
    # =========================================================================

    # Counterparty-data optional columns that gate B3.1 restrictions when
    # absent. Each tuple drives one CLS warning emitted by
    # ``_collect_input_warnings``: (cp_column, error_code, message, ref).
    # The warning fires when the column is missing from the ORIGINAL
    # counterparty schema AND the firm is on Basel 3.1.
    _CP_B31_REQUIRED_COLUMNS: tuple[tuple[str, str, str, str], ...] = (
        (
            "is_managed_as_retail",
            ERROR_RETAIL_POOL_MGMT_MISSING,
            (
                "Art. 123A(1)(b)(iii) pool management condition cannot be "
                "enforced — 'is_managed_as_retail' column missing from "
                "counterparty data. Non-SME retail exposures will default "
                "to qualifying status (75% RW) without verification."
            ),
            "PRA PS1/26 Art. 123A(1)(b)(iii)",
        ),
        (
            "is_financial_sector_entity",
            ERROR_FSE_COLUMN_MISSING,
            (
                "Art. 147A(1)(e) FSE A-IRB restriction cannot be enforced — "
                "'is_financial_sector_entity' column missing from counterparty "
                "data; FSE exposures may receive A-IRB treatment in violation "
                "of the restriction."
            ),
            "PRA PS1/26 Art. 147A(1)(e)",
        ),
    )

    def _collect_input_warnings(
        self,
        data: ResolvedHierarchyBundle,
        schema_names: set[str],
        config: CalculationConfig,
    ) -> list[CalculationError]:
        """Collect non-blocking warnings for missing or null input data.

        Three categories of warning fire here, all surfaced as
        ``CalculationError`` entries with severity WARNING:

        - **QRRE prerequisites** (CRR Art. 147(5)): when ``is_revolving`` or
          ``facility_limit`` are absent from the exposure schema, qualifying
          revolving retail silently routes to RETAIL_OTHER instead of
          RETAIL_QRRE. Regime-agnostic.
        - **B3.1 optional CP columns** (Art. 123A(1)(b)(iii) and 147A(1)(e)):
          when ``is_managed_as_retail`` or ``is_financial_sector_entity`` is
          missing from the *original* counterparty schema (not the
          post-join exposures schema, which always carries the column after
          ``_add_counterparty_attributes`` adds a null default), the
          corresponding restriction cannot be enforced.
        - **Large-corp F-IRB restriction conservatism** (Art. 147A(1)(d)):
          when ``annual_revenue`` is null on any corporate counterparty,
          the engine treats the row as large-corp by default (see
          ``_is_large_corp`` in ``_assign_approach``) and emits CLS008.

        The QRRE check reads the post-join exposures schema; the CP-side
        checks read the original counterparty schema. The null-revenue
        check materialises a count and is the only branch that triggers a
        ``.collect()``.
        """
        errors: list[CalculationError] = []

        # QRRE prerequisites — exposures-schema check, regime-agnostic.
        # Missing columns cause all revolving retail to silently become
        # RETAIL_OTHER.
        missing_qrre_cols = [c for c in ("is_revolving", "facility_limit") if c not in schema_names]
        if missing_qrre_cols:
            errors.append(
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

        # B3.1 optional CP columns — fire when missing under B3.1 only.
        # Reads the ORIGINAL CP schema, not schema_names (which always has
        # the column after _add_counterparty_attributes adds a null default).
        cp_columns = set(data.counterparty_lookup.counterparties.collect_schema().names())
        if config.is_basel_3_1:
            for column, code, message, ref in self._CP_B31_REQUIRED_COLUMNS:
                if column not in cp_columns:
                    errors.append(
                        classification_warning(
                            code=code,
                            message=message,
                            regulatory_reference=ref,
                        )
                    )

        # Art. 147A(1)(d): null annual_revenue triggers the conservative
        # large-corp F-IRB restriction — emit CLS008 to flag the conservatism.
        # Corporate-only count to avoid spurious warnings for non-corporate
        # entity types where annual_revenue is genuinely irrelevant. The
        # warning is suppressed when total_assets is populated AND below the
        # SME balance-sheet threshold (CRR Art. 4(1)(128D) / Commission Rec
        # 2003/361/EC Art. 2 fallback) — in that case the counterparty is
        # definitively SME-sized and the restriction is not applied.
        if config.is_basel_3_1 and "annual_revenue" in cp_columns:
            balance_sheet_threshold = float(config.thresholds.sme_balance_sheet_threshold)
            unresolved_filter = (pl.col("entity_type").fill_null("") == "corporate") & pl.col(
                "annual_revenue"
            ).is_null()
            if "total_assets" in cp_columns:
                unresolved_filter = unresolved_filter & (
                    pl.col("total_assets").is_null()
                    | (pl.col("total_assets") >= balance_sheet_threshold)
                )
            unresolved_count = (
                data.counterparty_lookup.counterparties.filter(unresolved_filter)
                .select(pl.len())
                .collect()
                .item()
            )
            if unresolved_count > 0:
                errors.append(
                    CalculationError(
                        code=ERROR_LARGE_CORP_REVENUE_NULL,
                        message=(
                            f"Art. 147A(1)(d) large-corporate F-IRB restriction applied "
                            f"conservatively for {unresolved_count} corporate counterparty "
                            f"row(s) with null annual_revenue and no SME-confirming "
                            f"total_assets — could not confirm size is below the GBP 440m "
                            f"threshold."
                        ),
                        severity=ErrorSeverity.WARNING,
                        category=ErrorCategory.CLASSIFICATION,
                        regulatory_reference="PRA PS1/26 Art. 147A(1)(d)",
                        field_name="annual_revenue",
                    )
                )

        return errors

    # =========================================================================
    # Independent flags (1 .with_columns — 11 expressions)
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
              qualifies_as_retail, retail_threshold_exclusion_applied, is_adc

        Art. 123A enforcement (Basel 3.1 only):
        - Art. 123A(1)(a): SME entities (revenue > 0 and < threshold) auto-qualify
          for retail treatment without needing conditions 1/3.
        - Art. 123A(1)(b)(iii): Non-SME entities must be managed as part of a
          retail pool (cp_is_managed_as_retail=True). Null defaults to True for
          backward compatibility.
        - CRR: threshold check only (no Art. 123A).

        ADC derivation (PRA PS1/26 Art. 124(3) / Art. 124K):
        - Derives ``is_adc=True`` for corporate (non-natural-person) exposures
          whose financed property is under construction (``is_under_construction``
          on the loan/facility) or whose product type signals development finance.
        - Natural persons fail the corporate gate even when
          ``is_under_construction=True``.
        - Any pre-existing non-null ``is_adc`` on the input row (e.g. propagated
          from collateral by upstream stages) takes precedence via
          ``pl.coalesce`` so the derivation cannot override an explicit
          user-supplied flag.
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

        # CRR Art. 128 (high-risk class, 150%) was OMITTED from the UK onshored
        # CRR text by SI 2021/1078 reg. 6(3)(a) with effect from 1 January 2022.
        # Under CRR, entity types that map to HIGH_RISK fall through to the
        # residual OTHER class. The 150% high-risk treatment is re-introduced
        # under PRA PS1/26 Basel 3.1 (Art. 128), so the SA-class label is
        # preserved as HIGH_RISK in that regime.
        if not config.is_basel_3_1:
            exposures = exposures.with_columns(
                pl.when(pl.col("_sa_class") == ExposureClass.HIGH_RISK.value)
                .then(pl.lit(ExposureClass.OTHER.value))
                .otherwise(pl.col("_sa_class"))
                .alias("_sa_class"),
            )

        sl_class = pl.lit(ExposureClass.SPECIALISED_LENDING.value)
        # Art. 112 Table A2: Under SA, specialised lending is a corporate sub-type
        # (Art. 112(1)(g)), not a separate exposure class.  exposure_class_sa reflects
        # this by mapping SL → CORPORATE.  exposure_class retains SPECIALISED_LENDING
        # because approach routing needs it for slotting/AIRB selection.
        sl_sa_class = pl.lit(ExposureClass.CORPORATE.value)

        # Batch 2: Derive all flags from pre-computed intermediates.
        exposures = exposures.with_columns(
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
                # Per-exposure default detection per CRR Art. 178: an exposure
                # is defaulted when EITHER (a) the counterparty is in default
                # (cp_default_status — propagates to all that counterparty's
                # exposures), OR (b) a row-level ``is_defaulted`` flag has been
                # set upstream (e.g. by the loan parquet, letting a single
                # defaulted exposure on an otherwise-performing counterparty
                # trigger Art. 153(1)(ii) / 154(1)(i)). ``beel`` is consumed by
                # the A-IRB defaulted formula (Art. 154(1)(i)) and Pool C of
                # Art. 158(5) but is NOT itself a trigger — see
                # ``_build_is_defaulted_expr`` and the DQ008 companion check.
                self._build_is_defaulted_expr(schema_names),
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
                # --- ADC classification (PRA PS1/26 Art. 124(3) / Art. 124K) ---
                # Derive ``is_adc`` from the loan/facility ``is_under_construction``
                # flag (or a development-finance product_type) gated on a corporate
                # / non-natural-person counterparty. Coalesce with any pre-existing
                # ``is_adc`` value so an explicit user-supplied flag wins.
                self._build_is_adc_expr(schema_names),
                # --- Retail threshold check + Art. 123A conditions (B31) ---
                self._build_qualifies_as_retail_expr(config, schema_names, max_retail_exposure),
                pl.when(pl.col("residential_collateral_value") > 0)
                .then(pl.lit(True))
                .otherwise(pl.lit(False))
                .alias("retail_threshold_exclusion_applied"),
            ]
        ).drop(["_sa_class", "_irb_class", "_pt_upper"])

        # PRA PS1/26 Art. 124E(1)(b)/(2) — Basel 3.1 only: re-route natural-person
        # residential exposures to the income-producing whole-loan track (Art. 124G)
        # when the borrower breaches the three-property limit. An explicit upstream
        # income flag still wins (coalesce precedence). CRR routing is untouched.
        if config.is_basel_3_1 and "has_income_cover" in schema_names:
            exposures = exposures.with_columns(
                self._build_has_income_cover_expr(schema_names),
            )

        return exposures

    # =========================================================================
    # SME size-test helper (shared by every SME-classification gate)
    # =========================================================================

    @staticmethod
    def _is_sme_by_size_expr(config: CalculationConfig) -> pl.Expr:
        """
        Return an expression that flags a counterparty as SME-sized.

        Reads ``sme_size_metric_gbp`` (= coalesce(annual_revenue, total_assets))
        and ``sme_size_source`` ("turnover" | "assets" | null), comparing
        against the appropriate threshold for each source. Implements CRR
        Art. 4(1)(128D) / Commission Recommendation 2003/361/EC Art. 2:
        annual turnover < EUR 50m OR balance-sheet total < EUR 43m. Returns
        False when both fields are null.

        CRR Art. 501 supporting factor (Art. 501(2)(c)) is keyed on annual
        turnover only and is gated separately in sa/supporting_factors.py.
        """
        turnover_threshold = float(config.thresholds.sme_turnover_threshold)
        balance_sheet_threshold = float(config.thresholds.sme_balance_sheet_threshold)
        metric = pl.col("sme_size_metric_gbp")
        source = pl.col("sme_size_source")
        turnover_branch = (source == "turnover") & (metric > 0) & (metric < turnover_threshold)
        assets_branch = (source == "assets") & (metric > 0) & (metric < balance_sheet_threshold)
        return turnover_branch | assets_branch

    # =========================================================================
    # Exposure subtype classification (1 .with_columns — 5 expressions)
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
        qrre_max_limit = float(config.thresholds.qrre_max_limit)
        is_sme_by_size = self._is_sme_by_size_expr(config)

        # PRA PS1/26 Art. 124(3) / Art. 124K: ADC exposures retain the CORPORATE
        # class and route to the 150% Art. 124K(1) ADC RW — they must not be
        # reclassified to CORPORATE_SME. ``is_adc`` is always present after
        # ``_derive_independent_flags``.
        is_adc = pl.col("is_adc").fill_null(False)

        # Conditions reused across expressions. ``is_sme_by_size`` evaluates
        # CRR Art. 4(1)(128D) / Commission Rec 2003/361/EC using turnover when
        # present and total assets as a fallback. Art. 501 supporting factor
        # eligibility is handled separately in sa/supporting_factors.py and
        # remains turnover-only per Art. 501(2)(c).
        is_corporate_sme = (
            (pl.col("exposure_class") == ExposureClass.CORPORATE.value) & is_sme_by_size & ~is_adc
        )
        is_retail_sme = (
            (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
            & (pl.col("qualifies_as_retail") == False)  # noqa: E712
            & is_sme_by_size
        )
        # Specialised lending is a corporate sub-type (Art. 112(1)(g)) and is
        # flagged as SME when the counterparty meets the size test. The
        # exposure_class must remain SPECIALISED_LENDING so approach assignment
        # routes it to the slotting calculator; only the is_sme flag is set.
        # Art. 501 supporting-factor eligibility is gated separately on
        # turnover non-null in sa/supporting_factors.py.
        is_sl_sme = (
            pl.col("exposure_class") == ExposureClass.SPECIALISED_LENDING.value
        ) & is_sme_by_size

        # QRRE qualification: revolving, retail, under QRRE limit (CRR Art. 147(5)).
        # CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c) cap the *aggregate* nominal
        # exposure to any single individual across the QRRE sub-portfolio at the
        # limit (EUR 100k / GBP 90k), not each facility individually. Aggregate
        # ``facility_limit`` (the committed/nominal basis) per
        # ``counterparty_reference`` before comparing.
        has_revolving = "is_revolving" in schema_names
        has_facility_limit = "facility_limit" in schema_names

        is_qrre = pl.lit(False)
        if has_revolving and has_facility_limit:
            # The QRRE sub-portfolio is the qualifying revolving retail population.
            # Only those rows contribute to the per-individual aggregate; non-QRRE
            # facilities (e.g. a term loan to the same obligor) are masked to 0.
            is_qrre_candidate = (
                (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
                & (pl.col("qualifies_as_retail") == True)  # noqa: E712
                & (pl.col("is_revolving") == True)  # noqa: E712
            )
            facility_limit = pl.col("facility_limit").fill_null(float("inf"))
            candidate_limit = pl.when(is_qrre_candidate).then(facility_limit).otherwise(pl.lit(0.0))
            # Guard the nullable ``counterparty_reference`` partition: a null key
            # would otherwise pool all unmapped rows into a single bucket (see
            # ``partition_by_nullable`` / ``NULLABLE_PARTITION_KEYS``). Null-keyed
            # rows fall back to their own per-row candidate limit.
            obligor_aggregate_limit = partition_by_nullable(
                candidate_limit.sum().over("counterparty_reference"),
                "counterparty_reference",
                candidate_limit,
            )
            is_qrre = is_qrre_candidate & (obligor_aggregate_limit <= qrre_max_limit)

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
                # True for: corporate SME, retail reclassified to CORPORATE_SME,
                # or specialised lending with SME counterparty (keeps SPECIALISED_LENDING class).
                (is_corporate_sme | is_retail_sme | is_sl_sme).alias("is_sme"),
                # --- FI scalar: user flag is authoritative (CRR Art. 153(2)) ---
                (pl.col("cp_apply_fi_scalar") == True)  # noqa: E712
                .fill_null(False)
                .alias("requires_fi_scalar"),
                # --- HVCRE flag (from specialised lending join, null → False) ---
                pl.col("is_hvcre").fill_null(False).alias("is_hvcre"),
            ]
        )

    # =========================================================================
    # Corporate → retail reclassification (1 .with_columns)
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
        4. Counterparty is SME-sized (CRR Art. 4(1)(128D) — turnover <
           EUR 50m OR balance-sheet total < EUR 43m when turnover null)

        Reclassification is an exposure-class decision, independent of
        approach permissions. The approach (AIRB/FIRB/SA) is determined
        later by _assign_approach using model_permissions.
        """
        is_sme_by_size = self._is_sme_by_size_expr(config)

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
            & is_sme_by_size
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
    # Real estate loan-split candidate flagging
    # =========================================================================

    def _flag_property_reclassification_candidates(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        schema_names: set[str],
    ) -> pl.LazyFrame:
        """
        Flag SA-bound exposures eligible for the RE loan-split.

        Adds the candidate columns consumed by the downstream
        ``RealEstateSplitter`` stage (re_split_target_class,
        re_split_mode, re_split_property_value, re_split_property_type,
        re_split_cre_rental_coverage_met). Does NOT duplicate rows —
        physical splitting happens in the splitter, after CRM has run.

        Decision logic per regime:

        - **CRR Art. 125 (RRE):** any non-mortgage SA exposure with
          residential property collateral becomes a split candidate.
          Secured cap = 80% LTV, secured RW = 35%.
        - **CRR Art. 126 (CRE):** commercial property collateral is a
          candidate only when the rental-income coverage test
          (>= 1.5x interest costs) is met. The flag
          re_split_cre_rental_coverage_met carries the test outcome;
          the splitter emits ``RE004`` when False.
        - **B3.1 Art. 124F (RRE):** loan-split with cap = 55% × property
          value (less prior charges per Art. 124F(2)), secured RW = 20%.
        - **B3.1 Art. 124H(1)-(2) (CRE NP/SME):** loan-split with cap
          55%, secured RW = 60%.
        - **B3.1 Art. 124H(3) (CRE other):** ``re_split_mode = "whole"``
          — single ``COMMERCIAL_MORTGAGE`` row so the existing
          ``b31_commercial_rw_expr`` Art. 124H(3) branch
          (max(60%, min(cp_rw, Art. 124I RW))) handles it.

        **Mixed RRE+CRE collateral (PRA PS1/26 Art. 124(4) and CRR Art.
        124(1) "any part" wording):** when an exposure carries both
        residential and commercial property collateral, the per-component
        columns ``re_split_residential_value`` /
        ``re_split_commercial_value`` and the per-component eligibility
        flags ``re_split_residential_eligible`` /
        ``re_split_commercial_eligible`` are emitted so the splitter can
        materialise a secured row per property type plus a single residual.
        The legacy ``re_split_target_class`` /
        ``re_split_property_type`` / ``re_split_property_value`` columns
        are kept populated for audit and warning consumers — for mixed
        rows ``re_split_property_type = "mixed"`` and
        ``re_split_property_value = rre_v + cre_v``.

        Exclusions (higher-priority Art. 112 classes must not be
        downgraded): defaulted, securitisation, covered bond, equity,
        CIU, subordinated, high-risk, and exposures already classified
        as RESIDENTIAL_MORTGAGE / RETAIL_MORTGAGE / COMMERCIAL_MORTGAGE.
        """
        # Without property_collateral_value (set by the hierarchy resolver),
        # there is nothing to split — emit null/zero defaults so downstream
        # consumers can rely on every re_split_* column being present.
        if "property_collateral_value" not in schema_names:
            return self._re_split_null_defaults(exposures)

        primitives = self._re_split_property_primitives(schema_names)
        gates = self._re_split_candidate_gates(schema_names, primitives)
        eligibility = self._re_split_per_component_eligibility(primitives, gates, config)
        legacy_outputs = self._re_split_legacy_outputs(primitives, gates, eligibility, config)
        per_component_values = self._re_split_per_component_values(primitives, eligibility)

        return exposures.with_columns(
            [
                legacy_outputs["re_split_target_class"].alias("re_split_target_class"),
                legacy_outputs["re_split_mode"].alias("re_split_mode"),
                legacy_outputs["re_split_property_type"].alias("re_split_property_type"),
                legacy_outputs["re_split_property_value"].alias("re_split_property_value"),
                per_component_values["re_split_residential_value"].alias(
                    "re_split_residential_value"
                ),
                per_component_values["re_split_commercial_value"].alias(
                    "re_split_commercial_value"
                ),
                eligibility["rre_eligible"].alias("re_split_residential_eligible"),
                eligibility["cre_eligible"].alias("re_split_commercial_eligible"),
                primitives["cre_rental_coverage_met"].alias("re_split_cre_rental_coverage_met"),
                eligibility["force_other_re"].alias("re_split_force_other_re"),
            ]
        )

    @staticmethod
    def _re_split_null_defaults(exposures: pl.LazyFrame) -> pl.LazyFrame:
        """Emit null/zero re_split_* columns when property data is absent."""
        return exposures.with_columns(
            [
                pl.lit(None).cast(pl.String).alias("re_split_target_class"),
                pl.lit(None).cast(pl.String).alias("re_split_mode"),
                pl.lit(None).cast(pl.String).alias("re_split_property_type"),
                pl.lit(0.0).cast(pl.Float64).alias("re_split_property_value"),
                pl.lit(0.0).cast(pl.Float64).alias("re_split_residential_value"),
                pl.lit(0.0).cast(pl.Float64).alias("re_split_commercial_value"),
                pl.lit(False).alias("re_split_residential_eligible"),
                pl.lit(False).alias("re_split_commercial_eligible"),
                pl.lit(False).alias("re_split_cre_rental_coverage_met"),
                pl.lit(False).alias("re_split_force_other_re"),
            ]
        )

    @staticmethod
    def _re_split_property_primitives(schema_names: set[str]) -> dict[str, pl.Expr]:
        """Build the property-value primitives consumed by every later block.

        Returns expressions for residential / commercial / total property
        value, the corresponding ``has_*`` predicates, residential-dominance,
        and the CRR CRE rental-coverage test (≥ 1.5× interest costs;
        conservative default of False when ``rental_to_interest_ratio`` is
        absent).
        """
        # Loan-split component values use the UNCAPPED RE collateral values
        # (PRA PS1/26 Art. 124(4) pro-rata is by raw collateral value, and the
        # 0.55xV cap is on raw property value). Fall back to the capped columns
        # when the uncapped variants are absent (older fixtures / direct calls).
        if (
            "residential_collateral_value_uncapped" in schema_names
            and "commercial_collateral_value_uncapped" in schema_names
        ):
            residential_value = pl.col("residential_collateral_value_uncapped").fill_null(0.0)
            commercial_value = pl.col("commercial_collateral_value_uncapped").fill_null(0.0)
            property_value = residential_value + commercial_value
        else:
            residential_value = (
                pl.col("residential_collateral_value").fill_null(0.0)
                if "residential_collateral_value" in schema_names
                else pl.lit(0.0)
            )
            property_value = pl.col("property_collateral_value").fill_null(0.0)
            commercial_value = (property_value - residential_value).clip(lower_bound=0.0)

        if "rental_to_interest_ratio" in schema_names:
            cre_rental_coverage_met = pl.col("rental_to_interest_ratio").fill_null(0.0) >= 1.5
        else:
            cre_rental_coverage_met = pl.lit(False)

        # PRA PS1/26 Art. 124(4): per-beneficiary flag (set by the hierarchy
        # resolver) marking that at least one RE collateral component fails
        # Art. 124A. Drives the all-or-nothing gate for mixed-RE exposures.
        re_collateral_non_qualifying = (
            pl.col("re_collateral_non_qualifying").fill_null(False)
            if "re_collateral_non_qualifying" in schema_names
            else pl.lit(False)
        )

        return {
            "residential_value": residential_value,
            "property_value": property_value,
            "commercial_value": commercial_value,
            "has_property": property_value > 0.0,
            "has_rre": residential_value > 0.0,
            "has_cre": commercial_value > 0.0,
            "is_residential_dominant": residential_value >= commercial_value,
            "cre_rental_coverage_met": cre_rental_coverage_met,
            "re_collateral_non_qualifying": re_collateral_non_qualifying,
        }

    @staticmethod
    def _re_split_candidate_gates(
        schema_names: set[str],
        primitives: dict[str, pl.Expr],
    ) -> dict[str, pl.Expr]:
        """Build the row-level eligibility predicates that gate the split.

        - ``is_candidate``: row may be considered for splitting (eligible class,
          has property collateral, not income-producing).
        - ``is_npsme``: counterparty is natural-person OR SME — drives the
          B3.1 Art. 124H(3) whole-loan path for pure-CRE non-NP/SME corporates.

        Already-classified RE rows are excluded because they're handled by the
        existing whole-loan path (CRR ``_apply_residential_mortgage_rw`` /
        B3.1 ``b31_residential_rw_expr``). Higher-priority Art. 112 classes
        (defaulted, equity, covered bond, high-risk) are also excluded — they
        must never be downgraded. ADC-flagged rows (PRA PS1/26 Art. 124(3)) are
        also excluded so the 150% Art. 124K(1) ADC RW applies to the whole
        exposure rather than a loan-split residential / corporate residual.
        """
        existing_re_classes = [
            _SECURED_TARGET_RESIDENTIAL,
            _SECURED_TARGET_COMMERCIAL,
            ExposureClass.RETAIL_MORTGAGE.value,
        ]
        excluded_classes = existing_re_classes + [
            ExposureClass.DEFAULTED.value,
            ExposureClass.EQUITY.value,
            ExposureClass.COVERED_BOND.value,
            ExposureClass.HIGH_RISK.value,
        ]
        is_eligible_class = ~pl.col("exposure_class").is_in(excluded_classes) & ~pl.col(
            "is_defaulted"
        )

        # Income-producing RE goes through the existing whole-loan path
        # (Art. 124G / Art. 124I bands), not the split mechanism.
        is_income_producing = (
            pl.col("has_income_cover").fill_null(False)
            if "has_income_cover" in schema_names
            else pl.lit(False)
        )

        # PRA PS1/26 Art. 124(3) / Art. 124K: ADC exposures route to the 150%
        # ADC path on the whole exposure — they must not be loan-split.
        is_adc = pl.col("is_adc").fill_null(False)

        is_candidate = (
            is_eligible_class & primitives["has_property"] & ~is_income_producing & ~is_adc
        )

        is_natural_person = (
            pl.col("cp_is_natural_person").fill_null(False)
            if "cp_is_natural_person" in schema_names
            else pl.lit(False)
        )
        is_sme_flag = pl.col("is_sme").fill_null(False)

        return {
            "is_candidate": is_candidate,
            "is_npsme": is_natural_person | is_sme_flag,
        }

    @staticmethod
    @cites("PS1/26, paragraph 124.4")
    def _re_split_per_component_eligibility(
        primitives: dict[str, pl.Expr],
        gates: dict[str, pl.Expr],
        config: CalculationConfig,
    ) -> dict[str, pl.Expr]:
        """Build per-component eligibility flags for the RE loan splitter.

        Implements the PRA PS1/26 Art. 124(4) mixed-RE rule (and CRR Art.
        124(1) "any part of an exposure" wording): each property component
        is evaluated against its own regime gate. Under CRR, CRE additionally
        requires the rental-coverage test. ``is_mixed`` flags rows where
        both components are eligible — the splitter materialises one secured
        row per eligible component plus a single residual.

        Art. 124(4) all-or-nothing qualifying gate (Basel 3.1 only): the
        preferential Art. 124F-124I tables apply to a mixed-RE exposure only
        when BOTH components separately qualify under Art. 124A. If either
        component fails (``re_collateral_non_qualifying``), ``force_other_re``
        fires and the splitter routes BOTH secured rows through Art. 124J
        (Other RE) — no partial preference. CRR has no Art. 124(4) limb, so
        the gate is suppressed on the CRR path.
        """
        rre_eligible = gates["is_candidate"] & primitives["has_rre"]
        if config.is_basel_3_1:
            cre_eligible = gates["is_candidate"] & primitives["has_cre"]
        else:
            cre_eligible = (
                gates["is_candidate"]
                & primitives["has_cre"]
                & primitives["cre_rental_coverage_met"]
            )
        is_mixed = rre_eligible & cre_eligible
        force_other_re = (
            is_mixed & primitives["re_collateral_non_qualifying"]
            if config.is_basel_3_1
            else pl.lit(False)
        )
        return {
            "rre_eligible": rre_eligible,
            "cre_eligible": cre_eligible,
            "is_mixed": is_mixed,
            "force_other_re": force_other_re,
        }

    @staticmethod
    def _re_split_legacy_outputs(
        primitives: dict[str, pl.Expr],
        gates: dict[str, pl.Expr],
        eligibility: dict[str, pl.Expr],
        config: CalculationConfig,
    ) -> dict[str, pl.Expr]:
        """Build the legacy single-target output expressions.

        These columns predate the per-component split and are kept populated
        for audit and warning consumers. For mixed rows
        ``re_split_property_type = "mixed"`` and
        ``re_split_property_value = rre_v + cre_v``.

        ``re_split_mode`` is regime-gated:
        - **B3.1**: ``"whole"`` for the Art. 124H(3) pure-CRE non-NP/SME
          corporate path (existing behaviour preserved); ``"split"`` for
          NP/SME or any RRE-eligible row.
        - **CRR**: ``"split"`` whenever any component is eligible (Art. 125
          RRE / Art. 126 CRE).
        """
        is_candidate = gates["is_candidate"]
        is_mixed = eligibility["is_mixed"]
        is_residential_dominant = primitives["is_residential_dominant"]
        rre_eligible = eligibility["rre_eligible"]
        cre_eligible = eligibility["cre_eligible"]

        if config.is_basel_3_1:
            cre_only_whole = (~rre_eligible) & cre_eligible & (~gates["is_npsme"])
            mode_expr = (
                pl.when(~is_candidate)
                .then(pl.lit(None, dtype=pl.String))
                .when(cre_only_whole)
                .then(pl.lit("whole"))  # B3.1 CRE Art. 124H(3) pure-CRE non-NP/SME
                .when(rre_eligible | cre_eligible)
                .then(pl.lit("split"))
                .otherwise(pl.lit(None, dtype=pl.String))
            )
        else:
            mode_expr = (
                pl.when(~is_candidate)
                .then(pl.lit(None, dtype=pl.String))
                .when(rre_eligible | cre_eligible)
                .then(pl.lit("split"))  # CRR Art. 125 / Art. 126 (per-component)
                .otherwise(pl.lit(None, dtype=pl.String))
            )

        target_class_expr = (
            pl.when(~is_candidate)
            .then(pl.lit(None, dtype=pl.String))
            .when(is_mixed)
            .then(pl.lit(None, dtype=pl.String))
            .when(is_residential_dominant)
            .then(pl.lit(_SECURED_TARGET_RESIDENTIAL))
            .otherwise(pl.lit(_SECURED_TARGET_COMMERCIAL))
        )

        property_type_expr = (
            pl.when(~is_candidate)
            .then(pl.lit(None, dtype=pl.String))
            .when(is_mixed)
            .then(pl.lit("mixed"))
            .when(is_residential_dominant)
            .then(pl.lit("residential"))
            .otherwise(pl.lit("commercial"))
        )

        property_value_expr = (
            pl.when(is_mixed)
            .then(primitives["residential_value"] + primitives["commercial_value"])
            .when(is_residential_dominant)
            .then(primitives["residential_value"])
            .otherwise(primitives["commercial_value"])
        )

        return {
            "re_split_target_class": target_class_expr,
            "re_split_mode": mode_expr,
            "re_split_property_type": property_type_expr,
            "re_split_property_value": property_value_expr,
        }

    @staticmethod
    def _re_split_per_component_values(
        primitives: dict[str, pl.Expr],
        eligibility: dict[str, pl.Expr],
    ) -> dict[str, pl.Expr]:
        """Build per-component property value expressions.

        Always emitted so the splitter can rely on their presence;
        ineligible components carry zero so allocation expressions
        naturally short-circuit.
        """
        return {
            "re_split_residential_value": (
                pl.when(eligibility["rre_eligible"])
                .then(primitives["residential_value"])
                .otherwise(pl.lit(0.0))
            ),
            "re_split_commercial_value": (
                pl.when(eligibility["cre_eligible"])
                .then(primitives["commercial_value"])
                .otherwise(pl.lit(0.0))
            ),
        }

    # =========================================================================
    # Model-level permission resolution (optional)
    # =========================================================================

    @cites("CRR Art. 143")
    @cites("CRR Art. 148")
    @cites("CRR Art. 150")
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
                pl.lit(None).cast(pl.String).alias("ppu_reason"),
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
        # ppu_reason is optional (CRR Art. 150(1)/Art. 148 SA-routing provenance).
        # Absent on frames that omit it → all null (no PPU/roll-out labelling).
        if "ppu_reason" not in mp_schema_names:
            model_permissions = model_permissions.with_columns(
                pl.lit(None).cast(pl.String).alias("ppu_reason")
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
                pl.col("ppu_reason").alias("mp_ppu_reason"),
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
        # 1. exposure_class_irb matches (use IRB class so rgla/pse entities typed
        #    as institution / sovereign match model permissions keyed on
        #    INSTITUTION / CGCB per CRR Art. 147(3)-(4))
        # 2. geography passes (country_codes is null OR cp_country_code in list)
        # 3. book code not excluded (excluded_book_codes is null OR book_code NOT in list)
        exposure_class_match = pl.col("exposure_class_irb") == pl.col("mp_exposure_class")

        # Null-safe filter logic (P1.114):
        # Polars `str.contains(<expr>)` propagates null when the needle is null,
        # producing kleene-3-valued OR results (null | null = null) that silently
        # block permission grants. Guard each branch:
        #   - geo: a null cp_country_code cannot prove scope-in, so it fails the
        #     filter when mp_country_codes is non-null (conservative).
        #   - book: a null book_code cannot be in any exclusion list, so the
        #     contains() result is coerced to False before negation.
        geo_passes = pl.col("mp_country_codes").is_null() | (
            pl.col("cp_country_code").is_not_null()
            & pl.col("mp_country_codes").str.contains(pl.col("cp_country_code"))
        )

        book_not_excluded = pl.col("mp_excluded_book_codes").is_null() | ~(
            pl.col("mp_excluded_book_codes").str.contains(pl.col("book_code")).fill_null(False)
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

        # SA-precedence (P1.145, CRR Art. 150(1) PPU carve-out): when the same
        # (model_id, exposure_class) yields both an IRB permission row and a
        # standardised row, the standardised row wins. AIRB-wins via .max()
        # would silently expand IRB scope beyond the firm's permission.
        sa_block = (permission_valid & (pl.col("mp_approach") == ApproachType.SA.value)).alias(
            "_sa_block_match"
        )

        # CRR Art. 150(1) PPU / Art. 148 roll-out provenance: capture the ppu_reason
        # from the surviving SA-precedence row only. Null on non-SA rows so the
        # max().over() roll-up below picks up the SA row's label (and stays null
        # when no SA-routing permission applied).
        sa_ppu_reason = (
            pl.when(sa_block).then(pl.col("mp_ppu_reason")).otherwise(None).alias("_sa_ppu_reason")
        )

        # Add match flags then aggregate: group by all original columns,
        # take max of the match flags (any valid AIRB/FIRB/slotting permission → True),
        # then AND-NOT the SA block to apply the SA-precedence rule.
        result = joined.with_columns(
            airb_permitted, firb_permitted, slotting_permitted, sa_block, sa_ppu_reason
        )

        # Aggregate back to one row per exposure using .over() to avoid group_by.
        # SA-precedence override is applied AFTER the .max() roll-up so any SA
        # row with permission_valid=True flips all IRB flags to False.
        result = result.with_columns(
            pl.col("_sa_block_match").max().over("exposure_reference").alias("_sa_block"),
            pl.col("_mp_row_joined").max().over("exposure_reference").alias("_mp_joined_any"),
            pl.col("_sa_ppu_reason").max().over("exposure_reference").alias("ppu_reason"),
        ).with_columns(
            (pl.col("_airb_match").max().over("exposure_reference") & ~pl.col("_sa_block")).alias(
                "model_airb_permitted"
            ),
            (pl.col("_firb_match").max().over("exposure_reference") & ~pl.col("_sa_block")).alias(
                "model_firb_permitted"
            ),
            (
                pl.col("_slotting_match").max().over("exposure_reference") & ~pl.col("_sa_block")
            ).alias("model_slotting_permitted"),
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

        # Drop the join columns and keep one row per exposure deterministically
        # (P1.145, Step 3): sort by a total-order key so that whichever row of
        # the duplicate-permission join survives `unique(keep="first")` does
        # not depend on the physical row order of the input parquet. The
        # priority key keeps the most-informative diagnostic on the surviving
        # row (null > filter_rejected > unmatched_model_id > null_model_id).
        diagnostic_priority = (
            pl.when(pl.col("_model_permission_diagnostic").is_null())
            .then(pl.lit(0))
            .when(pl.col("_model_permission_diagnostic") == "filter_rejected")
            .then(pl.lit(1))
            .when(pl.col("_model_permission_diagnostic") == "unmatched_model_id")
            .then(pl.lit(2))
            .otherwise(pl.lit(3))
            .alias("_diagnostic_priority")
        )
        result = (
            result.with_columns(diagnostic_priority)
            .sort(
                [
                    "exposure_reference",
                    "_diagnostic_priority",
                    "mp_approach",
                    "mp_country_codes",
                    "mp_excluded_book_codes",
                ],
                nulls_last=True,
                maintain_order=True,
            )
            .unique(subset=["exposure_reference"], keep="first", maintain_order=True)
            .select(
                pl.exclude(
                    "mp_exposure_class",
                    "mp_approach",
                    "mp_country_codes",
                    "mp_excluded_book_codes",
                    "mp_ppu_reason",
                    "_sa_ppu_reason",
                    "_airb_match",
                    "_firb_match",
                    "_slotting_match",
                    "_sa_block_match",
                    "_sa_block",
                    "_mp_row_joined",
                    "_mp_joined_any",
                    "_diagnostic_priority",
                )
            )
        )

        return result

    # =========================================================================
    # Approach assignment (1 .with_columns)
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

        Reads as a recipe of four named steps:
          1. Build permission expressions (model-level / org-wide / IRB-mode).
          2. Apply Basel 3.1 Art. 147A approach restrictions (FSE, large corp,
             institution AIRB block, sovereign-like SA-only).
          3. Compose the ``pl.when`` decision ladder for ``approach``.
          4. Apply post-decision LGD clearing and rgla/pse exposure_class
             re-alignment.

        Sets: approach, lgd (cleared for FIRB), exposure_class (re-aligned
        for IRB-routed rgla_* / pse_*).
        """
        # Ensure internal_pd exists (added by hierarchy resolver; may be absent
        # when classifier is invoked directly in tests without full pipeline)
        if "internal_pd" not in schema_names:
            exposures = exposures.with_columns(pl.lit(None).cast(pl.Float64).alias("internal_pd"))

        # IRB requires an internal rating (PD from the firm's IRB model).
        # Counterparties with only external ratings fall through to SA.
        has_internal_rating = pl.col("internal_pd").is_not_null()
        has_modelled_lgd = pl.col("lgd").is_not_null()

        # Step 1: permission expressions
        airb_expr, firb_expr, firb_clear_expr, sl_airb, sl_slotting = self._build_permission_exprs(
            config,
            has_internal_rating=has_internal_rating,
            has_modelled_lgd=has_modelled_lgd,
            has_model_permissions=has_model_permissions,
        )

        # Step 2: B3.1 Art. 147A restrictions (no-op under CRR)
        airb_expr, firb_expr, firb_clear_expr = self._apply_b31_approach_restrictions(
            airb_expr,
            firb_expr,
            firb_clear_expr,
            config,
            schema_names,
        )

        # Step 3: approach decision ladder
        approach_expr = self._build_approach_expr(
            schema_names=schema_names,
            config=config,
            airb_expr=airb_expr,
            firb_expr=firb_expr,
            sl_airb=sl_airb,
            sl_slotting=sl_slotting,
            has_internal_rating=has_internal_rating,
            has_modelled_lgd=has_modelled_lgd,
        )

        # FIRB LGD clearing — clear LGD when FIRB approach is chosen (FIRB uses
        # regulatory supervisory LGD). Must NOT clear for reclassified retail.
        lgd_expr = (
            pl.when(firb_clear_expr & ~pl.col("reclassified_to_retail"))
            .then(pl.lit(None).cast(pl.Float64))
            .otherwise(pl.col("lgd"))
            .alias("lgd")
        )

        # Step 4: align exposure_class for IRB-routed rgla_* / pse_*
        return self._align_irb_exposure_class(exposures.with_columns([approach_expr, lgd_expr]))

    @staticmethod
    @cites("PS1/26, paragraph 147A.1")
    def _derive_exposure_subclass(
        exposures: pl.LazyFrame,
        config: CalculationConfig,
        schema_names: set[str],
    ) -> pl.LazyFrame:
        """Derive the Basel 3.1 corporate ``exposure_subclass`` (PRA PS1/26 Art. 147A(1)).

        Basel 3.1 only — under CRR the column is null. For rows whose
        ``exposure_class`` is corporate / corporate_sme, the three-way split is:

          - ``corporate_financial_large`` — FSE (``cp_is_financial_sector_entity``)
            OR large corporate (``cp_annual_revenue`` > the Art. 147A(1)(d) GBP 440m
            threshold). Art. 147A(1)(e).
          - ``corporate_sme`` — ``is_sme`` (turnover <= GBP 44m). Art. 147A(1)(f).
          - ``corporate_other`` — otherwise. Art. 147A(1)(f).

        Reuses the FSE predicate and the large-corporate revenue threshold accessor
        (``config.thresholds.large_corporate_revenue_threshold``) shared with
        ``_apply_b31_approach_restrictions``; non-corporate rows stay null.
        """
        null_subclass = pl.lit(None, dtype=pl.String).alias("exposure_subclass")
        if not config.is_basel_3_1:
            return exposures.with_columns(null_subclass)

        is_corporate = pl.col("exposure_class").is_in(
            [ExposureClass.CORPORATE.value, ExposureClass.CORPORATE_SME.value]
        )

        is_fse = pl.lit(False)
        if "cp_is_financial_sector_entity" in schema_names:
            is_fse = (pl.col("cp_is_financial_sector_entity") == True).fill_null(False)  # noqa: E712

        is_large_by_revenue = pl.lit(False)
        if "cp_annual_revenue" in schema_names:
            is_large_by_revenue = (
                pl.col("cp_annual_revenue")
                > float(config.thresholds.large_corporate_revenue_threshold)
            ).fill_null(False)

        is_sme = pl.col("is_sme").fill_null(False)

        subclass = (
            pl.when(~is_corporate)
            .then(pl.lit(None, dtype=pl.String))
            .when(is_fse | is_large_by_revenue)
            .then(pl.lit(ExposureSubclass.CORPORATE_FINANCIAL_LARGE.value))
            .when(is_sme)
            .then(pl.lit(ExposureSubclass.CORPORATE_SME.value))
            .otherwise(pl.lit(ExposureSubclass.CORPORATE_OTHER.value))
            .alias("exposure_subclass")
        )
        return exposures.with_columns(subclass)

    @staticmethod
    def _build_permission_exprs(
        config: CalculationConfig,
        *,
        has_internal_rating: pl.Expr,
        has_modelled_lgd: pl.Expr,
        has_model_permissions: bool,
    ) -> tuple[pl.Expr, pl.Expr, pl.Expr, pl.Expr, pl.Expr]:
        """Build the five permission expressions consumed by the approach ladder.

        Returns ``(airb_expr, firb_expr, firb_clear_expr, sl_airb, sl_slotting)``.

        Three permission sources:
        - **Model-level** (``has_model_permissions=True``): per-row flags set
          by ``_resolve_model_permissions``, already filtered by exposure_class,
          geography, and book code. AIRB additionally requires modelled LGD.
        - **IRB mode without model_permissions**: no exposure can be granted
          IRB — every flag is ``pl.lit(False)``, falling back to SA.
        - **Org-wide** (default): booleans pre-computed from
          ``config.irb_permissions``, lifted via ``pl.lit``.

        ``firb_clear_expr`` identifies rows whose LGD should be cleared (FIRB
        uses supervisory LGD). Under model-level permissions, this excludes
        rows that also qualify for AIRB.
        """
        if has_model_permissions:
            sl_airb = pl.col("model_airb_permitted")
            sl_slotting = pl.col("model_slotting_permitted")
            airb_expr = pl.col("model_airb_permitted") & has_internal_rating & has_modelled_lgd
            firb_expr = pl.col("model_firb_permitted") & has_internal_rating
            firb_clear_expr = (
                pl.col("model_firb_permitted")
                & has_internal_rating
                & ~(pl.col("model_airb_permitted") & has_modelled_lgd)
            )
            return airb_expr, firb_expr, firb_clear_expr, sl_airb, sl_slotting

        if config.permission_mode == PermissionMode.IRB:
            # IRB mode requires model_permissions to gate per-model approval.
            # Without it, no exposure can be granted IRB — fall back to SA.
            false_expr = pl.lit(False)
            return false_expr, false_expr, false_expr, false_expr, false_expr

        # Org-wide SL permissions from config
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
        airb_expr, firb_expr, firb_clear_expr = ExposureClassifier._build_orgwide_permission_exprs(
            config, has_internal_rating
        )
        return airb_expr, firb_expr, firb_clear_expr, sl_airb, sl_slotting

    @staticmethod
    def _apply_b31_approach_restrictions(
        airb_expr: pl.Expr,
        firb_expr: pl.Expr,
        firb_clear_expr: pl.Expr,
        config: CalculationConfig,
        schema_names: set[str],
    ) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
        """Apply Basel 3.1 Art. 147A approach restrictions.

        Returns the inputs unchanged when ``not config.is_basel_3_1``.
        Under Basel 3.1, removes A-IRB eligibility for FSE / large-corporate /
        institution exposures (Art. 147A(1)(b)/(d)/(e)) and removes both A-IRB
        and F-IRB for sovereign-like entity types (Art. 147A(1)(a)). Also
        widens ``firb_clear_expr`` to include rows whose A-IRB was blocked but
        which still receive F-IRB.

        These supplement the permissions-level restrictions in
        ``full_irb_b31()`` with data-dependent checks that cannot be encoded
        in the permission map.
        """
        if not config.is_basel_3_1:
            return airb_expr, firb_expr, firb_clear_expr

        # Art. 147A(1)(d)/(e): FSE → no A-IRB
        is_fse = pl.lit(False)
        if "cp_is_financial_sector_entity" in schema_names:
            is_fse = (
                (pl.col("cp_is_financial_sector_entity") == True)  # noqa: E712
                .fill_null(False)
            )
        # Art. 147A(1)(d): the large-corporate F-IRB restriction applies ONLY
        # to counterparties of entity_type == "corporate". Non-corporate
        # entity types are governed by their own Art. 147A sub-clauses and
        # must never trip this branch. Within the corporate slice:
        #   - When annual_revenue is non-null, compare to the large-corp
        #     threshold (GBP 440m).
        #   - When annual_revenue is null but total_assets indicates the
        #     counterparty is SME-sized (assets < EUR 43m per Commission
        #     Rec 2003/361/EC Art. 2), it is definitively not large.
        #   - Otherwise (both fields null, or null revenue with assets that
        #     don't resolve the question) treat conservatively as large;
        #     CLS008 is emitted to flag the missing data.
        balance_sheet_threshold = float(config.thresholds.sme_balance_sheet_threshold)
        is_corporate_cp = pl.col("cp_entity_type").fill_null("") == "corporate"
        is_large_corp = is_corporate_cp & (
            pl.when(pl.col("cp_annual_revenue").is_not_null())
            .then(
                pl.col("cp_annual_revenue")
                > float(config.thresholds.large_corporate_revenue_threshold)
            )
            .when(pl.col("cp_total_assets").is_not_null())
            .then(pl.col("cp_total_assets") >= balance_sheet_threshold)
            .otherwise(pl.lit(True))
        )
        # Art. 147A(1)(b): Institution (including RGLAs/PSEs treated as
        # institutions per Art. 147(4)(b)) → F-IRB only. Key on
        # exposure_class_irb so rgla_institution / pse_institution inherit
        # the restriction.
        b31_institution_no_airb = pl.col("exposure_class_irb") == ExposureClass.INSTITUTION.value
        b31_airb_blocked = is_fse | is_large_corp | b31_institution_no_airb

        # Art. 147A(1)(a) read with Art. 147(3): sovereigns and
        # quasi-sovereigns with 0% SA RW → SA only. See
        # ``B31_SOVEREIGN_LIKE_ENTITY_TYPES`` for the full list.
        b31_sa_only = pl.col("cp_entity_type").is_in(list(B31_SOVEREIGN_LIKE_ENTITY_TYPES))

        # Art. 155 / CRE60 / PRA PS1/26: equity exposures are SA-only under
        # Basel 3.1 (IRB equity approaches withdrawn from 1 Jan 2027). Block
        # both A-IRB and F-IRB so the decision ladder falls through to the
        # equity branch in ``_build_approach_expr``.
        b31_equity_sa_only = pl.col("exposure_class_irb") == ExposureClass.EQUITY.value
        b31_sa_only_combined = b31_sa_only | b31_equity_sa_only

        new_airb = airb_expr & ~b31_airb_blocked & ~b31_sa_only_combined
        new_firb_clear = firb_clear_expr | (firb_expr & b31_airb_blocked)
        new_firb = firb_expr & ~b31_sa_only_combined
        return new_airb, new_firb, new_firb_clear

    @staticmethod
    def _build_approach_expr(
        *,
        schema_names: set[str],
        config: CalculationConfig,
        airb_expr: pl.Expr,
        firb_expr: pl.Expr,
        sl_airb: pl.Expr,
        sl_slotting: pl.Expr,
        has_internal_rating: pl.Expr,
        has_modelled_lgd: pl.Expr,
    ) -> pl.Expr:
        """Compose the ``pl.when`` decision ladder for ``approach``.

        Branch order (top wins):
        1. Managed-as-retail without LGD → SA
        2. Art. 114(4) EU domestic sovereign → SA (forced 0% RW)
        3. CCP trade exposures → SA (CRE54.14-15)
        4. Basel 3.1 Art. 147A(1)(c) IPRE/HVCRE → slotting
        5. SL A-IRB (PD + modelled LGD required, CRR Art. 153(1)-(4))
        6. SL slotting fallback (no internal rating required)
        7. A-IRB (model or org-wide, with B3.1 FSE/large-corp restriction applied)
        8. F-IRB (model or org-wide)
        9. Equity → EQUITY approach
        10. Otherwise → SA
        """
        managed_as_retail_without_lgd = (
            (pl.col("cp_is_managed_as_retail") == True)  # noqa: E712
            & (pl.col("qualifies_as_retail") == True)  # noqa: E712
            & (pl.col("lgd").is_null())
        )

        # Art. 114(4)/(7): EU domestic sovereign → SA. Use original
        # (pre-FX) denomination — `currency` is overwritten by the FX
        # converter with the reporting currency, which would otherwise
        # reject legitimate Art. 114(4) treatment for any non-base-currency
        # exposure. Gated to Basel 3.1: under CRR, Art. 114(4) sets only the
        # SA *risk weight*, not the *approach* — Art. 150(1) PPU is an
        # election ("may apply"), so a firm holding CGCB IRB permission must
        # be allowed to route to IRB. Under B31 (PS1/26 Art. 147A(1)(a)),
        # sovereign-like exposures are SA-only as a mandatory restriction,
        # also backstopped by the `b31_sa_only` IRB-blocker.
        is_eu_domestic_sovereign = (
            pl.lit(config.is_basel_3_1)
            & (pl.col("exposure_class") == ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value)
            & build_eu_domestic_currency_expr(
                "cp_country_code", denomination_currency_expr(schema_names)
            )
        )

        # Art. 147A(1)(c): IPRE/HVCRE → slotting only (overrides model perms)
        b31_ipre_hvcre_forced_slotting = pl.lit(False)
        if config.is_basel_3_1:
            b31_ipre_hvcre_forced_slotting = (
                pl.col("exposure_class") == ExposureClass.SPECIALISED_LENDING.value
            ) & pl.col("sl_type").is_in(list(_B31_SLOTTING_ONLY_SL_TYPES))

        # CCP exposures must always use SA (CRR Art. 300-311, CRE54)
        is_ccp = pl.col("cp_entity_type") == "ccp"

        is_sl = pl.col("exposure_class") == ExposureClass.SPECIALISED_LENDING.value

        return (
            pl.when(managed_as_retail_without_lgd)
            .then(pl.lit(ApproachType.SA.value))
            .when(is_eu_domestic_sovereign)
            .then(pl.lit(ApproachType.SA.value))
            .when(is_ccp)
            .then(pl.lit(ApproachType.SA.value))
            .when(b31_ipre_hvcre_forced_slotting)
            .then(pl.lit(ApproachType.SLOTTING.value))
            # SL A-IRB takes precedence over slotting (non-IPRE/HVCRE under B31).
            # Requires both PD and modelled LGD — without LGD, fall through to
            # slotting (CRR Art. 153(1)-(4) vs Art. 153(5)).
            .when(is_sl & sl_airb & has_internal_rating & has_modelled_lgd)
            .then(pl.lit(ApproachType.AIRB.value))
            # SL slotting fallback (slotting does not require internal rating)
            .when(is_sl & sl_slotting)
            .then(pl.lit(ApproachType.SLOTTING.value))
            .when(airb_expr)
            .then(pl.lit(ApproachType.AIRB.value))
            .when(firb_expr)
            .then(pl.lit(ApproachType.FIRB.value))
            # Equity exposure class → EQUITY approach (routes to SA equity RW
            # logic; full equity treatment requires the dedicated
            # equity_exposures table).
            .when(pl.col("exposure_class") == ExposureClass.EQUITY.value)
            .then(pl.lit(ApproachType.EQUITY.value))
            .otherwise(pl.lit(ApproachType.SA.value))
            .alias("approach")
        )

    @staticmethod
    @cites("CRR Art. 147")
    def _align_irb_exposure_class(exposures: pl.LazyFrame) -> pl.LazyFrame:
        """Align exposure_class with exposure_class_irb for rgla/pse rows.

        For IRB-routed rgla_* / pse_* rows, the IRB calculator (which reads
        exposure_class for correlation/LGD selection) needs CGCB / INSTITUTION
        rather than the SA labels RGLA / PSE. Scoped to these entity types
        because later phases (retail reclassification, SME/QRRE) mutate
        exposure_class in place without updating exposure_class_irb — a
        blanket rewrite would revert those legitimate adjustments.
        """
        needs_alignment = pl.col("cp_entity_type").is_in(list(RGLA_PSE_ENTITY_TYPES))
        return exposures.with_columns(
            pl.when(
                pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.AIRB.value])
                & needs_alignment
            )
            .then(pl.col("exposure_class_irb"))
            .otherwise(pl.col("exposure_class"))
            .alias("exposure_class")
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

        # Key IRB permission lookup on exposure_class_irb (not exposure_class) so
        # rgla_institution / pse_institution route via the INSTITUTION IRB class
        # (CRR Art. 147(4)(b)) and rgla_sovereign / pse_sovereign via CGCB
        # (CRR Art. 147(3)). exposure_class is the SA class and would otherwise
        # exclude these rows from IRB permission entries keyed on INSTITUTION / CGCB.
        airb_expr = pl.col("exposure_class_irb").is_in(airb_classes) & has_internal_rating
        firb_expr = pl.col("exposure_class_irb").is_in(firb_classes) & has_internal_rating
        firb_clear = pl.col("exposure_class_irb").is_in(firb_only_classes) & has_internal_rating

        return airb_expr, firb_expr, firb_clear

    # =========================================================================
    # Expression builders (static helpers returning pl.Expr)
    # =========================================================================

    @staticmethod
    def _build_is_adc_expr(schema_names: set[str]) -> pl.Expr:
        """Build is_adc derivation expression (PRA PS1/26 Art. 124(3) / Art. 124K).

        Derives ``is_adc=True`` when:
            - the financed property is under construction
              (``is_under_construction=True`` on the loan/facility), OR
            - ``product_type`` indicates development finance / construction,
        AND the borrower passes the corporate gate:
            - counterparty entity_type is one of {corporate, company,
              specialised_lending}, AND
            - counterparty is NOT a natural person.

        Any pre-existing non-null ``is_adc`` (e.g. propagated from collateral
        upstream) wins via ``pl.coalesce`` — the derivation only fires when
        ``is_adc`` is null on the input row.

        Returns a ``pl.Expr`` aliased ``is_adc`` (Boolean).
        """
        is_under_construction = (
            pl.col("is_under_construction").fill_null(False)
            if "is_under_construction" in schema_names
            else pl.lit(False)
        )
        is_adc_product = pl.col("_pt_upper").is_in(["DEVELOPMENT_FINANCE", "CONSTRUCTION_LOAN"])
        # Corporate gate: entity types treated as corporate under SA Art. 112(1)(g).
        is_corporate_entity = pl.col("cp_entity_type").is_in(
            ["corporate", "company", "specialised_lending"]
        )
        is_natural_person = (
            pl.col("cp_is_natural_person").fill_null(False)
            if "cp_is_natural_person" in schema_names
            else pl.lit(False)
        )
        derived = (
            is_corporate_entity & ~is_natural_person & (is_under_construction | is_adc_product)
        )

        if "is_adc" in schema_names:
            return pl.coalesce(pl.col("is_adc"), derived).fill_null(False).alias("is_adc")
        return derived.alias("is_adc")

    @staticmethod
    @cites("PS1/26, paragraph 124E")
    def _build_has_income_cover_expr(schema_names: set[str]) -> pl.Expr:
        """Build ``has_income_cover`` with the Art. 124E three-property re-route.

        PRA PS1/26 Art. 124E(1)(b) restricts the owner-occupied preferential
        residential treatment (Art. 124F loan-split / Art. 124L) to natural-person
        borrowers whose total residential RE exposure is secured on no more than
        three residential properties. When the count strictly exceeds three
        (``cp_qualifying_property_count > B31_RRE_THREE_PROPERTY_LIMIT``), the
        exposure is materially dependent on property cash flows (Art. 124E(2))
        and routes to the income-producing whole-loan track (Art. 124G).

        Boundary: the comparison is strict ``> 3`` — count=3 stays owner-occupied,
        count=4 re-routes.

        Coalesce precedence: any explicit upstream ``has_income_cover=True`` (set
        from collateral ``is_income_producing`` in the hierarchy stage) wins, so a
        caller-supplied income flag is never overridden by a low property count.

        Returns a ``pl.Expr`` aliased ``has_income_cover`` (Boolean). When the
        gating columns are absent the existing ``has_income_cover`` passes through
        unchanged.
        """
        if "cp_qualifying_property_count" not in schema_names:
            return pl.col("has_income_cover").fill_null(False).alias("has_income_cover")

        is_natural_person = (
            pl.col("cp_is_natural_person").fill_null(False)
            if "cp_is_natural_person" in schema_names
            else pl.lit(False)
        )
        # Strict > 3: count=3 stays owner-occupied; count=4 re-routes (Art. 124E(1)(b)).
        breaches_limit = pl.col("cp_qualifying_property_count") > B31_RRE_THREE_PROPERTY_LIMIT
        materially_dependent = is_natural_person & breaches_limit

        explicit = pl.col("has_income_cover").fill_null(False)
        # Explicit upstream income flag wins; otherwise the derived re-route applies.
        return (explicit | materially_dependent).alias("has_income_cover")

    @staticmethod
    @cites("CRR Art. 178")
    @cites("CRR Art. 153")
    def _build_is_defaulted_expr(schema_names: set[str]) -> pl.Expr:
        """Build per-exposure ``is_defaulted`` flag.

        Combines two explicit default signals so detection works at any
        granularity:

        - counterparty-level ``cp_default_status`` (propagates to all that
          counterparty's exposures);
        - explicit row-level ``is_defaulted`` carried on the loan/contingent
          parquet (lets a single-default exposure on an otherwise non-defaulted
          counterparty trigger the Art. 153(1)(ii) / 154(1)(i) defaulted
          treatment).

        Either one being true sets ``is_defaulted=True``.

        ``beel`` is deliberately **not** a trigger. PS1/26 Art. 181(1)(h)(ii)
        and CRR Art. 158(5) define BEEL only for defaulted exposures, but
        firms whose A-IRB models emit a BEEL-style value alongside LGD on
        performing exposures would otherwise see those rows silently
        reclassified as defaulted. The post-classification step
        ``_collect_beel_on_non_defaulted_warnings`` flags the contradictory
        combination (``is_defaulted=False ∧ beel>0``) as a DQ008 warning so
        the input contradiction is visible without changing routing.
        """
        cp_default = pl.col("cp_default_status") == True  # noqa: E712
        row_default = (
            pl.col("is_defaulted").fill_null(False)
            if "is_defaulted" in schema_names
            else pl.lit(False)
        )
        return (cp_default | row_default).alias("is_defaulted")

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
    @cites("CRR Art. 123")
    @cites("PS1/26, paragraph 123A")
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
        - Art. 123A(1)(b)(ii): an obligor's aggregate exposure must not exceed
          GBP 880k (threshold limb) AND no single obligor's aggregate exposure may
          exceed 0.2% of the total regulatory-retail portfolio (granularity limb,
          BCBS CRE20.66). Both limbs are Basel-3.1-only. The granularity limb is
          gated on ``config.enforce_retail_granularity`` (default True) so it can
          be suppressed under CRE20.66's national-discretion clause.
        - Art. 123A(1)(b)(iii): Non-SME entities must be managed as part of a
          retail pool (cp_is_managed_as_retail=True) to qualify.  Null values
          default to True for backward compatibility.

        References:
            PRA PS1/26 Art. 123A(1)(a)-(b), CRR Art. 123
        """
        # Hierarchy resolver now populates lending_group_adjusted_exposure with the
        # counterparty aggregate when no lending group exists, so the threshold
        # check is a single comparison across both cases.
        threshold_fail = pl.col("lending_group_adjusted_exposure") > max_retail_exposure

        if not config.is_basel_3_1:
            # CRR: threshold check only
            return (
                pl.when(threshold_fail)
                .then(pl.lit(False))
                .otherwise(pl.lit(True))
                .alias("qualifies_as_retail")
            )

        # Basel 3.1: Art. 123A two-path qualifying criteria.
        # Art. 123A(1)(a): SME auto-qualification — counterparty meets the
        # Art. 4(1)(128D) SME size test (turnover < EUR 50m OR balance-sheet
        # total < EUR 43m when turnover null).
        is_sme_for_art_123a = ExposureClassifier._is_sme_by_size_expr(config)

        # Art. 123A(1)(b)(ii) granularity limb (BCBS CRE20.66): no single obligor's
        # aggregate exposure may exceed 0.2% of the total regulatory-retail
        # portfolio. Candidate-retail rows are the entity-type RETAIL_OTHER
        # population (``_sa_class``); the denominator counts each obligor once by
        # dividing the per-obligor aggregate (``lending_group_adjusted_exposure``)
        # by the obligor's line-count, masking non-retail rows to 0, then summing.
        granularity_limit = float(B31_RETAIL_GRANULARITY_LIMIT)
        is_retail_candidate = pl.col("_sa_class") == ExposureClass.RETAIL_OTHER.value
        obligor_agg = pl.col("lending_group_adjusted_exposure")
        # Guard the nullable ``counterparty_reference`` partition: a null key would
        # otherwise pool all unmapped rows into a single bucket (see
        # ``partition_by_nullable`` / ``NULLABLE_PARTITION_KEYS``). Null-keyed rows
        # count as their own single-line obligor.
        obligor_line_count = partition_by_nullable(
            pl.len().over("counterparty_reference"),
            "counterparty_reference",
            pl.lit(1),
        )
        portfolio_total = (
            pl.when(is_retail_candidate)
            .then(obligor_agg / obligor_line_count)
            .otherwise(pl.lit(0.0))
        ).sum()
        granularity_fail = (
            is_retail_candidate
            & (portfolio_total > 0)
            & (obligor_agg / portfolio_total > granularity_limit)
        )

        expr = (
            pl.when(threshold_fail)
            .then(pl.lit(False))
            # Art. 123A(1)(a): SMEs auto-qualify — no condition 3 needed
            .when(is_sme_for_art_123a)
            .then(pl.lit(True))
        )

        # Art. 123A(1)(b)(ii) granularity limb: > 0.2% of the retail portfolio.
        # Gated on config.enforce_retail_granularity (default True) so the limb
        # can be suppressed where granularity is assessed by another method under
        # CRE20.66's national-discretion clause, or to isolate the other limbs.
        if config.enforce_retail_granularity:
            expr = expr.when(granularity_fail).then(pl.lit(False))

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
