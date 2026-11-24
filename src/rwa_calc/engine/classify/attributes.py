"""
Entity / exposure attribute derivation for the classification stage.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (engine/classify) -> CRMProcessor
    Sub-module of the classify stage package; consumed by ``classifier``
    (counterparty join, SL join, independent flags) and ``subtypes``
    (shared SME size-test expression).

Key responsibilities:
- Join the 20+ ``cp_*`` counterparty columns and derive the consolidated
  SME size metric (``sme_size_metric_gbp`` / ``sme_size_source``) from the
  group figures.
- Read the hierarchy's consolidated figures (max over the entity and EVERY
  org ancestor) into ``cp_group_annual_revenue`` / ``cp_group_total_assets``
  (``group_size_exprs``): the highest-consolidation figures read by the SME
  size test, the Art. 147(4C)(b)(ii) large-corporate F-IRB-only subclass test
  and (Basel 3.1) the large-FSE asset test.
- Join specialised-lending metadata (``sl_type`` / ``slotting_category`` /
  ``is_hvcre`` / ``sl_project_phase``) and resolve the project-finance phase
  the exposure is treated as being in (``resolve_sl_project_phase``).
- Derive every flag that depends only on raw input columns
  (``derive_independent_flags``): exposure classes, is_mortgage,
  is_defaulted, is_adc, qualifies_as_retail, has_income_cover, …
- Host the shared SME size-test expression (``is_sme_by_size_expr``)
  consumed by every SME classification gate (here and in ``subtypes``).

Scratch-column coupling (load-bearing):
    ``derive_independent_flags`` batch 1 creates the scratch columns
    ``_sa_class`` / ``_irb_class`` / ``_pt_upper`` which the expression
    builders ``_build_is_mortgage_expr`` / ``_build_is_adc_expr`` /
    ``_build_qualifies_as_retail_expr`` read inside batch 2 before the
    scratch is dropped. These builders MUST stay in this module next to
    ``derive_independent_flags`` — calling them from a frame that does not
    carry the scratch columns is a programming error.

References:
- CRR Art. 112 / Art. 147: SA / IRB exposure-class mapping by entity type
- CRR Art. 4(1)(128D) / Commission Rec 2003/361/EC Art. 2: SME size test
  (CRR: turnover or balance-sheet total); PS1/26 glossary SME: turnover only,
  "not more than GBP 44 million", on "the highest consolidated accounts of the
  group to which the enterprise belongs"; Art. 153(4) "consolidated group"
- CRR Art. 123: retail threshold; PS1/26, paragraph 123A: retail criteria
- CRR Art. 178 / Art. 153: default detection (counterparty + row-level)
- PRA PS1/26 Art. 124(3) / Art. 124K: ADC classification
- PRA PS1/26 Art. 124E(1)(a)/(b), (2): three-property re-route to the
  materially-dependent track, sparing a single primary residence
- CRR Art. 128 (UK-omitted by SI 2021/1078) / PS1/26 Art. 128: high-risk class
- PRA PS1/26 Art. 122B(2)(c)-(5): project-finance phase weights
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.schemas import (
    LARGE_CORPORATE_TEST_ENTITY_TYPES,
    NATURAL_PERSON_ENTITY_TYPES,
)
from rwa_calc.domain.enums import ExposureClass, ProjectPhase, SpecialisedLendingType
from rwa_calc.engine.entity_class_maps import (
    entity_type_to_irb_class,
    entity_type_to_sa_class,
)
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.engine.utils import partition_by_nullable
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

# PRA PS1/26 Art. 124E(1)(b) three-property limit resolved from the b31 pack once
# at module load (Basel-3.1-only; the consumer is gated on the
# ``b31_art_124e_three_property_limit_applies`` Feature). Integer count compared
# int-to-int against ``cp_qualifying_property_count`` (no float coercion).
_B31_PACK = resolve("b31", date(2027, 1, 1))
_RRE_THREE_PROPERTY_LIMIT = _B31_PACK.int_param("b31_rre_three_property_limit").value
# Optional 0.2% retail-granularity test (BCBS CRE20.66) a firm may elect to evidence
# PS1/26 Art. 123A(1)(b)(iii) — NOT a PS1/26 limb (RE-04). Decimal, float()-ed at the
# call site below; read direct from the b31 pack.
_RETAIL_GRANULARITY_LIMIT = _B31_PACK.scalar("b31_retail_granularity_limit")


# =========================================================================
# Counterparty attribute join
# =========================================================================


def add_counterparty_attributes(
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
    reclassification, Art. 123A retail qualification) and by the IRB
    Art. 153(4) correlation adjustment, from the GROUP figures:
    - sme_size_metric_gbp = coalesce(cp_group_annual_revenue, cp_group_total_assets)
    - sme_size_source     = "turnover" | "assets" | null
    The SME definition sizes the enterprise on its group — PS1/26 glossary SME
    (1) "the annual turnover shall be calculated on the basis of the highest
    consolidated accounts of the group to which the enterprise belongs";
    Art. 153(4) (both regimes) "the consolidated group of which the entity is a
    part". Whether the "assets" source can make an SME is the regime's
    ``sme_size_assets_fallback`` Feature (``is_sme_by_size_expr``).
    The Art. 501 supporting factor additionally requires the entity's own
    ``cp_annual_revenue`` (Art. 501(2)(b) turnover-only gate).

    ``cp_group_annual_revenue`` / ``cp_group_total_assets`` are the
    highest-level-of-consolidation figures the hierarchy put on the lookup (the
    max over the entity and every org ancestor, ``group_size_exprs``).
    ``cp_annual_revenue`` / ``cp_total_assets`` stay the entity's own figures.

    The lookup is sealed against ``CP_LOOKUP_COUNTERPARTIES_EDGE``
    (``CounterpartyLookup.__post_init__``), so every declared column is
    guaranteed present — values may be null, and each consumer applies
    its own null-VALUE semantics (e.g. ``cp_is_managed_as_retail``
    ``fill_null(True)`` in ``_build_qualifies_as_retail_expr``).
    """
    group_revenue, group_assets = group_size_exprs()
    select_cols = [
        pl.col("counterparty_reference"),
        pl.col("entity_type").str.to_lowercase().alias("cp_entity_type"),
        pl.col("country_code").alias("cp_country_code"),
        pl.col("annual_revenue").alias("cp_annual_revenue"),
        pl.col("total_assets").alias("cp_total_assets"),
        pl.col("default_status").alias("cp_default_status"),
        pl.col("apply_fi_scalar").alias("cp_apply_fi_scalar"),
        # Retail pool management — Art. 123A(1)(b)(iii) condition 3 and
        # SME retail treatment (Art. 123). Null handled downstream.
        pl.col("is_managed_as_retail").alias("cp_is_managed_as_retail"),
        # Natural person flag — Art. 124H CRE counterparty type
        pl.col("is_natural_person").alias("cp_is_natural_person"),
        # Three-property limit count — PRA PS1/26 Art. 124E(1)(b): drives the
        # income-producing re-route for natural-person RRE.
        pl.col("qualifying_property_count").alias("cp_qualifying_property_count"),
        # Social housing flag — Art. 124L RRE residual RW routing
        pl.col("is_social_housing").alias("cp_is_social_housing"),
        # FSE flag — Art. 147A(1)(e) approach restriction
        pl.col("is_financial_sector_entity").alias("cp_is_financial_sector_entity"),
        # Basel 3.1 SCRA / investment-grade fields
        pl.col("scra_grade").alias("cp_scra_grade"),
        pl.col("is_investment_grade").alias("cp_is_investment_grade"),
        # CCP fields (CRR Art. 300-311, CRE54.14-15)
        pl.col("is_ccp_client_cleared").alias("cp_is_ccp_client_cleared"),
        # QCCP flag (CRR Art. 272 Def (88)) — gates the Art. 306(1) 2%/4% trade
        # exposure pin; a ``ccp`` entity_type with an explicit is_qccp=False is
        # classified CORPORATE (Art. 107(2)(b), see derive_independent_flags).
        pl.col("is_qccp").alias("cp_is_qccp"),
        # Currency mismatch (Basel 3.1 Art. 123B / CRE20.93)
        pl.col("borrower_income_currency").alias("cp_borrower_income_currency"),
        # Sovereign floor for FX institution exposures (Art. 121(6) / CRE20.22)
        pl.col("sovereign_cqs").alias("cp_sovereign_cqs"),
        # CRR Art. 116(5) third-country supervisory-equivalence determination —
        # gates the Art. 116(1)/(2)/(3) PSE treatments. Null-VALUE semantics are
        # applied downstream in engine/sa/risk_weights.py: null means NOT
        # equivalent, so only an explicit True opens the PSE tables.
        pl.col("is_equivalent_jurisdiction").alias("cp_is_equivalent_jurisdiction"),
        pl.col("local_currency").alias("cp_local_currency"),
        # ECA / MEIP score for unrated sovereign Art. 137(1)-(2) Table 9 path.
        pl.col("eca_score").alias("cp_eca_score"),
        # Covered bond issuer institution CQS (Art. 129(5) derivation)
        pl.col("institution_cqs").alias("cp_institution_cqs"),
        # Internal-model id resolved by the rating-inheritance pipeline onto the
        # counterparty lookup. Traditional lending rows already carry ``model_id``
        # (enrich.attach_counterparty_rating renames internal_model_id ->
        # model_id per exposure), but synthetic CCR rows are appended AFTER that
        # attach and reach the classifier with ``model_id = null``. Surfacing the
        # counterparty's ``internal_model_id`` here lets _resolve_model_permissions
        # coalesce it into ``model_id`` so an IRB-permissioned counterparty's CCR
        # derivative exposure routes through F-IRB/A-IRB instead of falling back
        # to SA (CRR Art. 153(1) corporate IRB; CRR Art. 162(2)(b) derivative M).
        pl.col("internal_model_id").alias("cp_internal_model_id"),
        # Highest-level-of-consolidation figures (see group_size_exprs):
        # the SME size test, the PS1/26 Art. 147(4C)(b)(ii) large-corporate
        # subclass test and the Basel 3.1 large-FSE asset test read these;
        # cp_annual_revenue / cp_total_assets stay the entity's own figures.
        group_revenue.alias("cp_group_annual_revenue"),
        group_assets.alias("cp_group_total_assets"),
    ]

    cp_cols = counterparties.select(select_cols)

    joined = exposures.join(
        cp_cols,
        on="counterparty_reference",
        how="left",
    )

    # SME size metric on the consolidated group's figures: turnover when
    # present, total assets otherwise. Every SME classification gate
    # downstream reads sme_size_metric_gbp together with sme_size_source so
    # the threshold can be turnover- or balance-sheet-keyed without re-reading
    # the raw cp_ columns. Null on both fields → null metric → no SME treatment.
    metric, source = sme_size_exprs(
        pl.col("cp_group_annual_revenue"), pl.col("cp_group_total_assets")
    )
    return joined.with_columns(metric.alias("sme_size_metric_gbp"), source.alias("sme_size_source"))


def group_size_exprs() -> tuple[pl.Expr, pl.Expr]:
    """The consolidated revenue and total assets read off a counterparty lookup row.

    ``max(own, group)`` of the lookup's ``group_annual_revenue`` /
    ``group_total_assets`` (the hierarchy's max over the entity and every org
    ancestor — ``engine/hierarchy/graph.py::with_group_size_figures``) and the
    entity's own figure: identical to the group figure on a hierarchy-built
    lookup, and the own figure on a hand-built one that carries no group
    columns. Shared by the counterparty-attribute join and the CLS0xx audit so
    both size on one definition.
    """
    return (
        pl.max_horizontal("annual_revenue", "group_annual_revenue"),
        pl.max_horizontal("total_assets", "group_total_assets"),
    )


def join_specialised_lending(
    exposures: pl.LazyFrame,
    sl_data: pl.LazyFrame | None,
) -> pl.LazyFrame:
    """Join specialised lending metadata onto exposures by counterparty.

    Adds ``sl_type``, ``slotting_category``, ``is_hvcre`` and
    ``sl_project_phase`` (the input ``project_phase``, sealed onto the raw
    specialised-lending edge so always present). The phase was once dropped
    here, which left the PS1/26 Art. 122B(2)(c)/(4) phase weights
    unreachable from the loader (review IV-01). When no SL data is
    supplied, the columns are added as null literals so downstream helpers
    can rely on their presence.
    """
    if sl_data is not None:
        return exposures.join(
            sl_data.select(
                "counterparty_reference",
                "sl_type",
                "slotting_category",
                "is_hvcre",
                pl.col("project_phase").alias("sl_project_phase"),
            ),
            on="counterparty_reference",
            how="left",
        )
    return exposures.with_columns(
        pl.lit(None).cast(pl.String).alias("sl_type"),
        pl.lit(None).cast(pl.String).alias("slotting_category"),
        pl.lit(None).cast(pl.Boolean).alias("is_hvcre"),
        pl.lit(None).cast(pl.String).alias("sl_project_phase"),
    )


@cites("PS1/26, paragraph 122B")
def resolve_sl_project_phase(
    exposures: pl.LazyFrame,
    *,
    pack: ResolvedRulepack,
) -> pl.LazyFrame:
    """Resolve the phase a project-finance exposure is treated as being in.

    PRA PS1/26 Art. 122B(2)(c): "project finance exposures shall be assigned
    a risk weight of 130% during the pre-operational phase, and (subject to
    paragraph 4) 100% during the operational phase"; Art. 122B(3) defines the
    operational phase as the one in which the project entity has "(a) a
    positive net cash-flow that is sufficient to cover any remaining
    contractual obligations relating to the completion of the project; and
    (b) declining long-term debt". The operational phase is therefore a
    condition the firm shows, and a project-finance row whose
    ``project_phase`` is null or outside ``ProjectPhase`` is treated as
    PRE_OPERATIONAL (owner decision, review IV-01). Recognised values are
    lower-cased, matching the case-insensitive input-domain gate.

    Gated on the ``sa_pf_phase_defaults_pre_operational`` pack Feature (Basel
    3.1 only — CRR has no SA phase weights, so the supplied value is carried
    unchanged). ``_sl_project_phase_defaulted`` marks the defaulted rows for
    the SA006 roll-up in ``audit.collect_classified_frame_warnings``; it is
    intra-stage scratch, stripped by the classifier-exit seal.

    The resolved ``sl_project_phase`` is the carrier the SA risk weight
    (``engine/sa/b31_risk_weight_tables.py::b31_sa_sl_rw_expr``, including
    the output-floor SA-equivalent of slotted rows) and the OF 07.00
    project-finance phase rows read, so the reported phase and the applied
    weight cannot disagree.
    """
    if not pack.feature("sa_pf_phase_defaults_pre_operational"):
        return exposures.with_columns(pl.lit(False).alias("_sl_project_phase_defaulted"))

    phase = pl.col("sl_project_phase").str.to_lowercase()
    is_project_finance = (
        pl.col("sl_type")
        .str.to_lowercase()
        .eq_missing(SpecialisedLendingType.PROJECT_FINANCE.value)
    )
    unevidenced = is_project_finance & (
        phase.is_null() | ~phase.is_in([member.value for member in ProjectPhase])
    )
    return exposures.with_columns(
        pl.when(unevidenced)
        .then(pl.lit(ProjectPhase.PRE_OPERATIONAL.value))
        .when(is_project_finance)
        .then(phase)
        .otherwise(pl.col("sl_project_phase"))
        .alias("sl_project_phase"),
        unevidenced.alias("_sl_project_phase_defaulted"),
    )


# =========================================================================
# Independent flags (1 .with_columns — 11 expressions)
# =========================================================================


@cites("CRR Art. 147")
@cites("PS1/26, paragraph 147")
def derive_independent_flags(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    schema_names: set[str],
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """
    Compute all flags that depend only on raw input columns.

    Uses two .with_columns() batches: the first pre-computes shared
    intermediates (uppercase strings, entity-type mapping) that the
    second batch references, avoiding redundant str.to_uppercase()
    and replace_strict() calls.

    Sets: exposure_class_sa, exposure_class_irb, exposure_class, is_mortgage,
          is_defaulted, is_infrastructure,
          qualifies_as_retail, retail_threshold_exclusion_applied, is_adc

    Art. 123A enforcement (Basel 3.1 only):
    - Art. 123A(1)(a): SME entities (revenue > 0 and < threshold) auto-qualify
      for retail treatment without needing conditions 1/3.
    - Art. 123A(1)(b)(iii): Non-SME entities must be managed as part of a
      retail pool (cp_is_managed_as_retail=True). Null defaults to True for
      backward compatibility (the loader seals an omitted flag to False).
    - CRR: threshold check only (no Art. 123A).
    ``qualifies_as_retail`` is REGULATORY retail; whether a failing row leaves
    the retail class is decided in ``subtypes.classify_exposure_subtypes``.

    ADC derivation (PRA PS1/26 Art. 124(3) / Art. 124K):
    - Derives ``is_adc=True`` for corporate (non-natural-person) exposures
      whose financed property is under construction (``is_under_construction``
      on the loan/facility) or whose product type signals development finance.
    - A real-estate collateral row flagged ``is_adc=True`` (propagated by the
      hierarchy stage as ``re_collateral_is_adc``) is a third signal, OR-ed in
      behind the same corporate gate; its ``is_presold`` is carried as
      ``is_presold`` for the Art. 124K(2) weight.
    - Natural persons fail the corporate gate even when
      ``is_under_construction=True``.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    max_retail_exposure = float(
        regulatory_threshold(resolved_pack, "retail_max_exposure", config.eur_gbp_rate)
    )

    # SL override: exposures with sl_type (from specialised_lending join) get
    # SPECIALISED_LENDING class regardless of counterparty entity_type.
    sl_override = pl.col("sl_type").is_not_null()

    # Batch 1: Pre-compute shared intermediates to avoid redundant work.
    # - _sa_class: entity type → SA class mapping (used 3× below)
    # - _irb_class: entity type → IRB class mapping
    # - _pt_upper: product_type uppercased (used in is_mortgage, infrastructure)
    # Bind the entity-class maps for THIS run's regime rather than the module
    # default. Both maps live in the common pack and are currently identical
    # under CRR and Basel 3.1, so this changes no number today — but it is what
    # makes a regime-divergent override in ``packs/b31.py`` take effect instead
    # of being silently ignored, which is the trap P1.276 and P1.286 each died
    # on (P1.311).
    sa_class_map = entity_type_to_sa_class(pack)
    irb_class_map = entity_type_to_irb_class(pack)
    exposures = exposures.with_columns(
        [
            pl.col("cp_entity_type")
            .replace_strict(sa_class_map, default=ExposureClass.OTHER.value)
            .alias("_sa_class"),
            pl.col("cp_entity_type")
            .replace_strict(irb_class_map, default=ExposureClass.OTHER.value)
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
    if not resolved_pack.feature("b31_high_risk_class_applicable"):
        exposures = exposures.with_columns(
            pl.when(pl.col("_sa_class") == ExposureClass.HIGH_RISK.value)
            .then(pl.lit(ExposureClass.OTHER.value))
            .otherwise(pl.col("_sa_class"))
            .alias("_sa_class"),
        )

    # CRR Art. 147(3)(b) admits only the Art. 117(2) named (0% RW) MDBs to the
    # central-government IRB class; Art. 147(4)(c) assigns "exposures to
    # multilateral development banks which are not assigned a 0 % risk weight
    # under Article 117" to the INSTITUTIONS class. PS1/26 Art. 147(3)(f) drops
    # the split — every MDB is quasi-sovereign there — so the reroute reads the
    # cited CRR-only pack Feature and the base map stays framework-invariant
    # (same shape as the high-risk demotion above). ``mdb_named`` is untouched
    # in both regimes (P1.276).
    if resolved_pack.feature("crr_non_named_mdb_institution_irb_class"):
        exposures = exposures.with_columns(
            pl.when(pl.col("cp_entity_type") == "mdb")
            .then(pl.lit(ExposureClass.INSTITUTION.value))
            .otherwise(pl.col("_irb_class"))
            .alias("_irb_class"),
        )

    # CRR Art. 107(2)(b) = PS1/26 Art. 107(2)(b): exposures to a NON-qualifying
    # CCP are treated "as exposures to a corporate" — the Section 9 trade
    # exposures too, since CCR (CRR) Part Art. 306(1)(b) gives them "the risk
    # weight ... as set out in Article 107(2)(b)". ``is_qccp`` False demotes,
    # and the loader defaults an unsupplied column to False (an unreported
    # qualification is not shown), so only a supplied True — or an explicit
    # null — keeps the base map's institution class (Art. 107(2)(a)), the
    # convention the Art. 306 pin reads (CC-11; the class used to stay
    # institution for both).
    is_non_qualifying_ccp = pl.col("cp_entity_type").eq_missing("ccp") & pl.col(
        "cp_is_qccp"
    ).eq_missing(False)
    exposures = exposures.with_columns(
        pl.when(is_non_qualifying_ccp)
        .then(pl.lit(ExposureClass.CORPORATE.value))
        .otherwise(pl.col(name))
        .alias(name)
        for name in ("_sa_class", "_irb_class")
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
            _build_is_mortgage_expr(),
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
            _build_is_defaulted_expr(),
            # --- Infrastructure flag (uses _pt_upper) ---
            pl.col("_pt_upper").str.contains("INFRASTRUCTURE").alias("is_infrastructure"),
            # --- ADC classification (PRA PS1/26 Art. 124(3) / Art. 124K) ---
            # Derive ``is_adc`` from the loan/facility ``is_under_construction``
            # flag, a development-finance product_type or the linked collateral's
            # ``is_adc``, gated on a corporate / non-natural-person counterparty.
            _build_is_adc_expr(schema_names),
            # PS1/26 Art. 124K(2)(b)(i) pre-sale / pre-lease attestation from the
            # linked real-estate collateral (review RE-02); read only on the
            # Basel 3.1 ADC branch (``b31_adc_rw_expr``).
            pl.col("re_collateral_is_presold").alias("is_presold"),
            # --- Retail threshold check + Art. 123A conditions (B31) ---
            _build_qualifies_as_retail_expr(config, max_retail_exposure, pack=resolved_pack),
            pl.when(pl.col("residential_collateral_value") > 0)
            .then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("retail_threshold_exclusion_applied"),
        ]
    ).drop(["_sa_class", "_irb_class", "_pt_upper"])

    # PRA PS1/26 Art. 124E(1)(b)/(2) — Basel 3.1 only: re-route natural-person
    # residential exposures to the materially-dependent track (Art. 124G) when
    # the borrower breaches the three-property limit, unless the exposure is
    # secured by a single property that is the obligor's primary residence
    # (Art. 124E(1)(a), P1.473). An explicit upstream income flag still wins.
    # CRR routing is untouched.
    if resolved_pack.feature("b31_art_124e_three_property_limit_applies"):
        exposures = exposures.with_columns(
            _build_has_income_cover_expr(),
        )

    return exposures


# =========================================================================
# SME size-test helper (shared by every SME-classification gate)
# =========================================================================


@cites("CRR Art. 153(4)")
@cites("PS1/26, paragraph 122")
def is_sme_by_size_expr(
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
    metric: pl.Expr | None = None,
    source: pl.Expr | None = None,
) -> pl.Expr:
    """
    Return an expression that flags a counterparty as SME-sized.

    Reads ``sme_size_metric_gbp`` (= coalesce(group annual revenue, group total
    assets), see ``add_counterparty_attributes``) and ``sme_size_source``
    ("turnover" | "assets" | null) — or the ``metric`` / ``source`` expressions
    a caller passes to size on other figures (the CLS016 audit's own-figure
    test). Returns False when both figures are null. The regime decides the
    shape of the test through two cited pack Features:

    - ``sme_size_assets_fallback``: whether a balance-sheet total can make an
      SME. CRR: yes — Art. 4(1)(128D) defines SME by Commission Rec 2003/361/EC,
      whose Annex Art. 2 admits a turnover OR a balance-sheet limb. Basel 3.1:
      no — the PS1/26 glossary SME is "a micro, small or medium enterprise with
      an annual turnover of not more than GBP 44 million", turnover only (total
      assets substitute only inside the Art. 153(4) correlation, "when total
      annual revenue is not a meaningful indicator of entity size", which this
      size test does not model).
    - ``sme_turnover_threshold_inclusive``: Basel 3.1 "not more than GBP 44
      million" is inclusive (``<=``); CRR keeps the strict ``<`` of Art. 153(4)
      "less than EUR 50 million".

    CRR Art. 501 supporting factor (Art. 501(2)(b)) is keyed on annual
    turnover only and is gated separately in engine/supporting_factors.py.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    turnover_threshold = float(
        regulatory_threshold(resolved_pack, "sme_turnover_threshold", config.eur_gbp_rate)
    )
    size = pl.col("sme_size_metric_gbp") if metric is None else metric
    size_source = pl.col("sme_size_source") if source is None else source
    within_turnover = (
        size <= turnover_threshold
        if resolved_pack.feature("sme_turnover_threshold_inclusive")
        else size < turnover_threshold
    )
    turnover_branch = (size_source == "turnover") & (size > 0) & within_turnover
    if not resolved_pack.feature("sme_size_assets_fallback"):
        return turnover_branch
    balance_sheet_threshold = float(
        regulatory_threshold(resolved_pack, "sme_balance_sheet_threshold", config.eur_gbp_rate)
    )
    assets_branch = (size_source == "assets") & (size > 0) & (size < balance_sheet_threshold)
    return turnover_branch | assets_branch


def sme_size_exprs(revenue: pl.Expr, assets: pl.Expr) -> tuple[pl.Expr, pl.Expr]:
    """The SME size metric and its source from a revenue and a total-assets figure.

    ``(coalesce(revenue, assets), "turnover" | "assets" | null)`` — turnover
    when present, the balance-sheet total otherwise, null when neither is
    known. ``add_counterparty_attributes`` feeds it the consolidated group
    figures; the CLS016 audit feeds it the entity's own figures too, so both
    sides of that comparison are sized by one definition.
    """
    metric = pl.coalesce([revenue, assets])
    source = (
        pl.when(revenue.is_not_null())
        .then(pl.lit("turnover"))
        .when(assets.is_not_null())
        .then(pl.lit("assets"))
        .otherwise(pl.lit(None, dtype=pl.String))
    )
    return metric, source


@cites("CRR Art. 147(5)")
@cites("PS1/26, paragraph 147")
def natural_person_expr() -> pl.Expr:
    """Return an expression flagging a counterparty as a natural person.

    CRR Art. 147(5)(a)(i) / PS1/26 Art. 147(5)(a)(i): exposures to natural
    persons enter the IRB retail exposure class with NO monetary cap, unlike
    the SME limb (a)(ii). The signal is the explicit ``is_natural_person``
    flag OR one of the documented natural-person ``entity_type`` aliases
    (``individual`` / ``natural_person`` / ``retail`` — all mapping to
    RETAIL_OTHER). A null flag AND a non-natural entity type resolve to
    False, so an unknown obligor is treated as NOT a natural person and the
    monetary cap keeps binding (conservative direction of error).
    """
    return pl.col("cp_is_natural_person").fill_null(False) | pl.col("cp_entity_type").is_in(
        list(NATURAL_PERSON_ENTITY_TYPES)
    )


@cites("PS1/26, paragraph 147")
def large_corporate_test_entity_expr(entity_type_column: str) -> pl.Expr:
    """Return an expression flagging the entity types the large-corporate test reads.

    PRA PS1/26 Art. 147(4C)(b)(ii) puts "'large' corporates with annual revenue of
    more than GBP 440 million" in the financial-and-large subclass, which
    Art. 147A(1)(e)(ii) restricts to Foundation IRB. The population is
    ``LARGE_CORPORATE_TEST_ENTITY_TYPES`` — ``corporate`` and its alias
    ``company`` (P1.321). A null entity type is not in it (``nulls_equal=True``
    makes the membership test False rather than null, with no ``fill_null``).

    ONE predicate for both readers, so they cannot drift: the approach
    restriction (``approach._apply_b31_approach_restrictions``, on the exposure
    frame's ``cp_entity_type``) and the CLS008 / CLS011 / CLS015 counts
    (``audit._input_warning_filters``, on the counterparty lookup's
    ``entity_type``). Specialised-lending rows are excluded by each reader in its
    own terms (Art. 147(4C)(a)) — this predicate is about the obligor's type only.
    """
    return pl.col(entity_type_column).is_in(
        list(LARGE_CORPORATE_TEST_ENTITY_TYPES), nulls_equal=True
    )


# =========================================================================
# Expression builders (private helpers returning pl.Expr)
# =========================================================================


def _build_is_adc_expr(schema_names: set[str]) -> pl.Expr:
    """Build is_adc derivation expression (PRA PS1/26 Art. 124(3) / Art. 124K).

    Derives ``is_adc=True`` when:
        - the financed property is under construction
          (``is_under_construction=True`` on the loan/facility), OR
        - ``product_type`` indicates development finance / construction, OR
        - a real-estate collateral row linked to the exposure (at any level)
          carries ``is_adc=True`` (``re_collateral_is_adc``, review RE-01 —
          the flag the input documentation asks for, which before this was
          read by nothing),
    AND the borrower passes the corporate gate:
        - counterparty entity_type is one of {corporate, company,
          specialised_lending}, AND
        - counterparty is NOT a natural person.

    The gate applies to the collateral flag too: the PS1/26 glossary defines
    an ADC exposure as "an exposure to a corporate or special purpose entity
    financing any land acquisition for development and construction
    purposes, or financing development and construction of any residential
    real estate or commercial real estate", so a natural person's
    self-build stays on the real-estate tables. The flag is OR-ed, never
    coalesced: the collateral column is loader-defaulted False, and a False
    must not cancel a construction-loan derivation.

    Returns a ``pl.Expr`` aliased ``is_adc`` (Boolean).
    """
    is_under_construction = pl.col("is_under_construction").fill_null(False)
    is_adc_product = pl.col("_pt_upper").is_in(["DEVELOPMENT_FINANCE", "CONSTRUCTION_LOAN"])
    # Corporate gate: entity types treated as corporate under SA Art. 112(1)(g).
    is_corporate_entity = pl.col("cp_entity_type").is_in(
        ["corporate", "company", "specialised_lending"]
    )
    is_natural_person = pl.col("cp_is_natural_person").fill_null(False)
    adc_signal = is_under_construction | is_adc_product | pl.col("re_collateral_is_adc")
    derived = is_corporate_entity & ~is_natural_person & adc_signal

    # KEEP (presence guard on a non-contract column): an ``is_adc`` column is
    # not declared on hierarchy_exit (the collateral flag arrives as
    # ``re_collateral_is_adc``), so a sealed classifier input never carries
    # it. The coalesce branch preserves explicit-flag precedence for direct
    # expression-level use on hand-built frames.
    if "is_adc" in schema_names:
        return pl.coalesce(pl.col("is_adc"), derived).fill_null(False).alias("is_adc")
    return derived.alias("is_adc")


@cites("PS1/26, paragraph 124E")
def _build_has_income_cover_expr() -> pl.Expr:
    """Build ``has_income_cover`` with the Art. 124E three-property re-route.

    PRA PS1/26 Art. 124E(1): a residential RE exposure "is materially dependent
    on the cash-flows generated by the property unless it is: (a) to one or more
    natural persons and the exposure is secured by a single property that is the
    obligor's primary residence; (b) to one or more natural persons that
    individually meet the three property limit". Art. 124E(2): the limit is "no
    more than three qualifying properties", a qualifying property being
    residential RE that "is not the primary residence of the natural person" and
    secures a residential RE exposure to the person (or to a property SPV they
    guarantee), "regardless of which lender has" it.

    A natural person whose ``cp_qualifying_property_count`` strictly exceeds the
    limit fails limb (b), so the exposure routes to the materially-dependent
    track (Art. 124G whole-loan, Art. 124J(1) for other RRE) — UNLESS limb (a)
    holds: the two limbs are independent, so the exposure secured by the
    borrower's single residential primary residence alone
    (``re_collateral_is_primary_residence``, set by the hierarchy; never a
    commercial property, which Art. 124E(6) decides) stays off the
    materially-dependent track whatever the count (P1.473). Every consumer of
    the flag moves with it, so RWA moves either way:
    - down: Art. 124F instead of Art. 124G on a first charge; Art. 124J(2)'s
      counterparty weight instead of Art. 124J(1) 150% on other RRE; Art. 127(3)
      100% instead of Art. 127(1) 150% on a defaulted exposure; and a natural
      person outside a real-estate class (a sole trader booked corporate) becomes
      a loan-split candidate (``re_split/flagging.py``), so one row becomes
      ``_sec`` / ``_res`` legs;
    - up: Art. 124F on a junior charge where the prior charges use up the
      Art. 124F(2)(a) 20% band, above Art. 124G(2)'s Table 6B x 1.25.

    Boundary: the comparison is strict ``> 3`` — count=3 meets the limit,
    count=4 re-routes.

    Precedence: an explicit upstream ``has_income_cover=True`` (set from
    collateral ``is_income_producing`` in the hierarchy stage) is the
    institution's own dependence assessment and wins over both limbs; only the
    derived re-route is ever spared.

    Returns a ``pl.Expr`` aliased ``has_income_cover`` (Boolean, never null). The
    gating columns are sealed-lookup joins (``cp_qualifying_property_count``
    / ``cp_is_natural_person``) and a hierarchy_exit column
    (``re_collateral_is_primary_residence``) — always present; a null count
    never breaches the limit, a null natural-person flag fails the gate and a
    null primary-residence flag is no attestation.
    """
    is_natural_person = pl.col("cp_is_natural_person").fill_null(False)
    # Strict > 3: count=3 meets the limit; count=4 re-routes (Art. 124E(1)(b)).
    breaches_limit = (
        pl.col("cp_qualifying_property_count") > _RRE_THREE_PROPERTY_LIMIT
    ).eq_missing(True)
    # Art. 124E(1)(a) holds on its own, whatever the count (P1.473).
    single_primary_residence = pl.col("re_collateral_is_primary_residence").eq_missing(True)
    materially_dependent = is_natural_person & breaches_limit & ~single_primary_residence

    explicit = pl.col("has_income_cover").fill_null(False)
    # Explicit upstream income flag wins; otherwise the derived re-route applies.
    return (explicit | materially_dependent).alias("has_income_cover")


@cites("CRR Art. 178")
@cites("CRR Art. 153")
def _build_is_defaulted_expr() -> pl.Expr:
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
    reclassified as defaulted. The post-classification roll-up
    ``audit.collect_classified_frame_warnings`` flags the contradictory
    combination (``is_defaulted=False ∧ beel>0``) as a DQ008 warning so
    the input contradiction is visible without changing routing.
    """
    cp_default = pl.col("cp_default_status") == True  # noqa: E712
    row_default = pl.col("is_defaulted").fill_null(False)
    return (cp_default | row_default).alias("is_defaulted")


def _build_is_mortgage_expr() -> pl.Expr:
    """Build is_mortgage expression.

    Uses _pt_upper (pre-computed uppercase product_type) plus the
    hierarchy_exit property-collateral aggregates (contract columns —
    always present, null/False = no property collateral).
    """
    base = pl.col("_pt_upper").str.contains("MORTGAGE") | pl.col("_pt_upper").str.contains(
        "HOME_LOAN"
    )
    return (
        base
        | (pl.col("property_collateral_value") > 0)
        | (pl.col("has_facility_property_collateral") == True)  # noqa: E712
    ).alias("is_mortgage")


@cites("CRR Art. 123")
@cites("PS1/26, paragraph 123A")
def _build_qualifies_as_retail_expr(
    config: CalculationConfig,
    max_retail_exposure: float,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.Expr:
    """Build qualifies_as_retail expression with Art. 123A enforcement.

    CRR: Threshold check only — aggregated exposure ≤ EUR 1m.

    Basel 3.1 Art. 123A adds two-path qualifying criteria:
    - Art. 123A(1)(a): SME entities (revenue > 0 and < GBP 44m) auto-qualify
      without needing pool management attestation.
    - Art. 123A(1)(b)(ii): the total owed by the obligor or group of connected
      clients must not exceed GBP 880,000. That is the whole of the limb.
    - Art. 123A(1)(b)(iii): Non-SME entities must be managed as part of a
      retail pool (cp_is_managed_as_retail=True) to qualify.  Null values
      default to True for backward compatibility.
    - OPTIONAL (RE-04): a firm may evidence (iii) quantitatively with the BCBS
      CRE20.66 test — no obligor above 0.2% of the candidate-retail portfolio —
      by setting ``config.enforce_retail_granularity`` (default False). PS1/26
      contains no 0.2% limb; an earlier reading placed one in (b)(ii).

    References:
        PRA PS1/26 Art. 123A(1)(a)-(b), CRR Art. 123
    """
    # Hierarchy resolver now populates lending_group_adjusted_exposure with the
    # counterparty aggregate when no lending group exists, so the threshold
    # check is a single comparison across both cases. On a solo /
    # sub-consolidated run the amount owed to the reporting group's OTHER
    # entities is added (``out_of_scope_group_adjusted_exposure``, null when
    # nothing is owed elsewhere — sum_horizontal reads it as zero): CRR
    # Art. 123(c) "owed to the institution and parent undertakings and its
    # subsidiaries"; PS1/26 Art. 123A(1)(b)(ii) "owed to the institution, its
    # parent undertakings, its subsidiaries and subsidiaries of its parent
    # undertakings". The granularity limb below keeps the run's own figure.
    threshold_fail = (
        pl.sum_horizontal(
            pl.col("lending_group_adjusted_exposure"),
            pl.col("out_of_scope_group_adjusted_exposure"),
        )
        > max_retail_exposure
    )

    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    if not resolved_pack.feature("retail_art_123a_two_path_applicable"):
        # CRR: threshold check only
        return (
            pl.when(threshold_fail)
            .then(pl.lit(False))
            .otherwise(pl.lit(True))
            .alias("qualifies_as_retail")
        )

    # Basel 3.1: Art. 123A two-path qualifying criteria.
    # Art. 123A(1)(a): SME auto-qualification — the counterparty's group
    # meets the PS1/26 glossary SME test (turnover not more than GBP 44m; no
    # balance-sheet limb — see is_sme_by_size_expr).
    is_sme_for_art_123a = is_sme_by_size_expr(config, pack=resolved_pack)

    # Optional 0.2% granularity test (BCBS CRE20.66; an elected method of
    # evidencing Art. 123A(1)(b)(iii), not a PS1/26 limb): no single obligor's
    # aggregate exposure may exceed 0.2% of the total candidate-retail
    # portfolio. Candidate-retail rows are the entity-type RETAIL_OTHER
    # population (``_sa_class``); the denominator counts each obligor once by
    # dividing the per-obligor aggregate (``lending_group_adjusted_exposure``)
    # by the obligor's line-count, masking non-retail rows to 0, then summing.
    granularity_limit = float(_RETAIL_GRANULARITY_LIMIT)
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
        pl.when(is_retail_candidate).then(obligor_agg / obligor_line_count).otherwise(pl.lit(0.0))
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

    # Elected 0.2% test: > 0.2% of the retail portfolio fails Art. 123A(1)(b)(iii)
    # as the firm evidences it. Off by default (RE-04): PS1/26 has no such limb.
    if config.enforce_retail_granularity:
        expr = expr.when(granularity_fail).then(pl.lit(False))

    # Art. 123A(1)(b)(iii): Non-SME must be managed as retail pool.
    # Null defaults to True (Art. 123A — documented KEEP: a null pool-
    # management flag preserves backward-compatible qualifying behaviour).
    expr = expr.when(
        pl.col("cp_is_managed_as_retail").fill_null(True) == False  # noqa: E712
    ).then(pl.lit(False))

    return expr.otherwise(pl.lit(True)).alias("qualifies_as_retail")
