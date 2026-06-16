"""
Entity / exposure attribute derivation for the classification stage.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (stages/classify) -> CRMProcessor
    Sub-module of the classify stage package; consumed by ``classifier``
    (counterparty join, SL join, independent flags) and ``subtypes``
    (shared SME size-test expression).

Key responsibilities:
- Join the 20+ ``cp_*`` counterparty columns and derive the consolidated
  SME size metric (``sme_size_metric_gbp`` / ``sme_size_source``).
- Join specialised-lending metadata (``sl_type`` / ``slotting_category`` /
  ``is_hvcre``).
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
- CRR Art. 123: retail threshold; PS1/26, paragraph 123A: retail criteria
- CRR Art. 178 / Art. 153: default detection (counterparty + row-level)
- PRA PS1/26 Art. 124(3) / Art. 124K: ADC classification
- PRA PS1/26 Art. 124E: three-property income-producing re-route
- CRR Art. 128 (UK-omitted by SI 2021/1078) / PS1/26 Art. 128: high-risk class
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.entity_class_maps import (
    ENTITY_TYPE_TO_IRB_CLASS,
    ENTITY_TYPE_TO_SA_CLASS,
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
# PRA PS1/26 Art. 123A(1)(b)(ii) single-obligor 0.2% retail-granularity cap
# (Decimal, float()-ed at the call site below) — read direct from the b31 pack.
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
    reclassification, Art. 123A retail qualification, Art. 147A(1)(d)
    large-corporate F-IRB restriction) and by the IRB Art. 153(4)
    correlation adjustment:
    - sme_size_metric_gbp = coalesce(cp_annual_revenue, cp_total_assets)
    - sme_size_source     = "turnover" | "assets" | null
    Art. 501 supporting factor deliberately ignores this column and
    keys off cp_annual_revenue directly (Art. 501(2)(c)).

    The lookup is sealed against ``CP_LOOKUP_COUNTERPARTIES_EDGE``
    (``CounterpartyLookup.__post_init__``), so every declared column is
    guaranteed present — values may be null, and each consumer applies
    its own null-VALUE semantics (e.g. ``cp_is_managed_as_retail``
    ``fill_null(True)`` in ``_build_qualifies_as_retail_expr``).
    """
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
        # exposure pin so a ``ccp`` entity_type with an explicit is_qccp=False
        # falls through to the standard institution ladder (Art. 107(2)(a)).
        pl.col("is_qccp").alias("cp_is_qccp"),
        # Currency mismatch (Basel 3.1 Art. 123B / CRE20.93)
        pl.col("borrower_income_currency").alias("cp_borrower_income_currency"),
        # Sovereign floor for FX institution exposures (Art. 121(6) / CRE20.22)
        pl.col("sovereign_cqs").alias("cp_sovereign_cqs"),
        pl.col("local_currency").alias("cp_local_currency"),
        # ECA / MEIP score for unrated sovereign Art. 137(1)-(2) Table 9 path.
        pl.col("eca_score").alias("cp_eca_score"),
        # Covered bond issuer institution CQS (Art. 129(5) derivation)
        pl.col("institution_cqs").alias("cp_institution_cqs"),
        # Internal-model id resolved by the rating-inheritance pipeline onto the
        # counterparty lookup. Traditional lending rows already carry ``model_id``
        # (hierarchy._attach_counterparty_rating renames internal_model_id ->
        # model_id per exposure), but synthetic CCR rows are appended AFTER that
        # attach and reach the classifier with ``model_id = null``. Surfacing the
        # counterparty's ``internal_model_id`` here lets _resolve_model_permissions
        # coalesce it into ``model_id`` so an IRB-permissioned counterparty's CCR
        # derivative exposure routes through F-IRB/A-IRB instead of falling back
        # to SA (CRR Art. 153(1) corporate IRB; CRR Art. 162(2)(b) derivative M).
        pl.col("internal_model_id").alias("cp_internal_model_id"),
    ]

    cp_cols = counterparties.select(select_cols)

    joined = exposures.join(
        cp_cols,
        on="counterparty_reference",
        how="left",
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


def join_specialised_lending(
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
            sl_data.select(["counterparty_reference", "sl_type", "slotting_category", "is_hvcre"]),
            on="counterparty_reference",
            how="left",
        )
    return exposures.with_columns(
        pl.lit(None).cast(pl.String).alias("sl_type"),
        pl.lit(None).cast(pl.String).alias("slotting_category"),
        pl.lit(None).cast(pl.Boolean).alias("is_hvcre"),
    )


# =========================================================================
# Independent flags (1 .with_columns — 11 expressions)
# =========================================================================


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
    if not resolved_pack.feature("b31_high_risk_class_applicable"):
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
            _build_is_adc_expr(schema_names),
            # --- Retail threshold check + Art. 123A conditions (B31) ---
            _build_qualifies_as_retail_expr(config, max_retail_exposure, pack=resolved_pack),
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
    if resolved_pack.feature("b31_art_124e_three_property_limit_applies"):
        exposures = exposures.with_columns(
            _build_has_income_cover_expr(),
        )

    return exposures


# =========================================================================
# SME size-test helper (shared by every SME-classification gate)
# =========================================================================


def is_sme_by_size_expr(
    config: CalculationConfig, *, pack: ResolvedRulepack | None = None
) -> pl.Expr:
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
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    turnover_threshold = float(
        regulatory_threshold(resolved_pack, "sme_turnover_threshold", config.eur_gbp_rate)
    )
    balance_sheet_threshold = float(
        regulatory_threshold(resolved_pack, "sme_balance_sheet_threshold", config.eur_gbp_rate)
    )
    metric = pl.col("sme_size_metric_gbp")
    source = pl.col("sme_size_source")
    turnover_branch = (source == "turnover") & (metric > 0) & (metric < turnover_threshold)
    assets_branch = (source == "assets") & (metric > 0) & (metric < balance_sheet_threshold)
    return turnover_branch | assets_branch


# =========================================================================
# Expression builders (private helpers returning pl.Expr)
# =========================================================================


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
    is_under_construction = pl.col("is_under_construction").fill_null(False)
    is_adc_product = pl.col("_pt_upper").is_in(["DEVELOPMENT_FINANCE", "CONSTRUCTION_LOAN"])
    # Corporate gate: entity types treated as corporate under SA Art. 112(1)(g).
    is_corporate_entity = pl.col("cp_entity_type").is_in(
        ["corporate", "company", "specialised_lending"]
    )
    is_natural_person = pl.col("cp_is_natural_person").fill_null(False)
    derived = is_corporate_entity & ~is_natural_person & (is_under_construction | is_adc_product)

    # KEEP (presence guard on a non-contract column): ``is_adc`` is not
    # declared on hierarchy_exit, so a sealed classifier input never
    # carries it and the plain derivation applies. The coalesce branch
    # preserves explicit-flag precedence for direct expression-level use.
    if "is_adc" in schema_names:
        return pl.coalesce(pl.col("is_adc"), derived).fill_null(False).alias("is_adc")
    return derived.alias("is_adc")


@cites("PS1/26, paragraph 124E")
def _build_has_income_cover_expr() -> pl.Expr:
    """Build ``has_income_cover`` with the Art. 124E three-property re-route.

    PRA PS1/26 Art. 124E(1)(b) restricts the owner-occupied preferential
    residential treatment (Art. 124F loan-split / Art. 124L) to natural-person
    borrowers whose total residential RE exposure is secured on no more than
    three residential properties. When the count strictly exceeds three
    (``cp_qualifying_property_count > _RRE_THREE_PROPERTY_LIMIT``), the
    exposure is materially dependent on property cash flows (Art. 124E(2))
    and routes to the income-producing whole-loan track (Art. 124G).

    Boundary: the comparison is strict ``> 3`` — count=3 stays owner-occupied,
    count=4 re-routes.

    Coalesce precedence: any explicit upstream ``has_income_cover=True`` (set
    from collateral ``is_income_producing`` in the hierarchy stage) wins, so a
    caller-supplied income flag is never overridden by a low property count.

    Returns a ``pl.Expr`` aliased ``has_income_cover`` (Boolean). The
    gating columns are sealed-lookup joins (``cp_qualifying_property_count``
    / ``cp_is_natural_person``) — always present; null counts never breach
    the limit and null natural-person flags fail the gate.
    """
    is_natural_person = pl.col("cp_is_natural_person").fill_null(False)
    # Strict > 3: count=3 stays owner-occupied; count=4 re-routes (Art. 124E(1)(b)).
    breaches_limit = pl.col("cp_qualifying_property_count") > _RRE_THREE_PROPERTY_LIMIT
    materially_dependent = is_natural_person & breaches_limit

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
    reclassified as defaulted. The post-classification step
    ``_collect_beel_on_non_defaulted_warnings`` flags the contradictory
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
    # Art. 123A(1)(a): SME auto-qualification — counterparty meets the
    # Art. 4(1)(128D) SME size test (turnover < EUR 50m OR balance-sheet
    # total < EUR 43m when turnover null).
    is_sme_for_art_123a = is_sme_by_size_expr(config, pack=resolved_pack)

    # Art. 123A(1)(b)(ii) granularity limb (BCBS CRE20.66): no single obligor's
    # aggregate exposure may exceed 0.2% of the total regulatory-retail
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

    # Art. 123A(1)(b)(ii) granularity limb: > 0.2% of the retail portfolio.
    # Gated on config.enforce_retail_granularity (default True) so the limb
    # can be suppressed where granularity is assessed by another method under
    # CRE20.66's national-discretion clause, or to isolate the other limbs.
    if config.enforce_retail_granularity:
        expr = expr.when(granularity_fail).then(pl.lit(False))

    # Art. 123A(1)(b)(iii): Non-SME must be managed as retail pool.
    # Null defaults to True (Art. 123A — documented KEEP: a null pool-
    # management flag preserves backward-compatible qualifying behaviour).
    expr = expr.when(
        pl.col("cp_is_managed_as_retail").fill_null(True) == False  # noqa: E712
    ).then(pl.lit(False))

    return expr.otherwise(pl.lit(True)).alias("qualifies_as_retail")
