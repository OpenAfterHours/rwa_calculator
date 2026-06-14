"""
Exposure subtype classification for the classification stage.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (stages/classify) -> CRMProcessor
    Sub-module of the classify stage package; consumed by ``classifier``
    after ``attributes.derive_independent_flags`` has set the base
    exposure classes and flags.

Key responsibilities:
- SME / retail / QRRE class mutation (``classify_exposure_subtypes``):
  CORPORATE_SME, RETAIL_QRRE, the obligor-aggregate QRRE limit, is_sme,
  requires_fi_scalar, is_hvcre.
- Art. 147(5) corporate→retail reclassification
  (``reclassify_corporate_to_retail``).
- Re-align ``exposure_class_irb`` with the mutated ``exposure_class``
  (``sync_irb_exposure_class``), excluding RGLA / PSE entity types.
- Derive the Basel 3.1 corporate ``exposure_subclass``
  (``derive_exposure_subclass``).

References:
- CRR Art. 147(5) / Basel CRE30.16-17: corporate→retail reclassification
- CRR Art. 154(4)(c) / PS1/26 Art. 147(5A)(c): QRRE aggregate limit
- CRR Art. 4(1)(128D): SME size test (via ``attributes.is_sme_by_size_expr``)
- CRR Art. 147(3)/147(4)(b): RGLA / PSE IRB class exclusion
- PS1/26, paragraph 147A.1: corporate exposure_subclass three-way split
- PRA PS1/26 Art. 124(3) / Art. 124K: ADC exclusion from CORPORATE_SME
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.schemas import RGLA_PSE_ENTITY_TYPES
from rwa_calc.domain.enums import ExposureClass, ExposureSubclass
from rwa_calc.engine.stages.classify.attributes import is_sme_by_size_expr
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.engine.utils import partition_by_nullable
from rwa_calc.rulebook import RulepackV0

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)


# =========================================================================
# Exposure subtype classification (1 .with_columns — 5 expressions)
# =========================================================================


def classify_exposure_subtypes(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
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
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    qrre_max_limit = float(
        regulatory_threshold(resolved_pack, "qrre_max_limit", config.eur_gbp_rate)
    )
    is_sme_by_size = is_sme_by_size_expr(config, pack=resolved_pack)

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
    # ``counterparty_reference`` before comparing. The driver columns
    # (``is_revolving`` / ``facility_limit``) are hierarchy_exit contract
    # columns — always present, null-gated by value below.
    #
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


def reclassify_corporate_to_retail(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    schema_names: set[str],
    *,
    pack: ResolvedRulepack | None = None,
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
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    is_sme_by_size = is_sme_by_size_expr(config, pack=resolved_pack)

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
    has_property_expr = _build_has_property_expr(schema_names)

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


def sync_irb_exposure_class(exposures: pl.LazyFrame) -> pl.LazyFrame:
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


@cites("PS1/26, paragraph 147A.1")
def derive_exposure_subclass(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Derive the Basel 3.1 corporate ``exposure_subclass`` (PRA PS1/26 Art. 147A(1)).

    Basel 3.1 only — under CRR the column is null. For rows whose
    ``exposure_class`` is corporate / corporate_sme, the three-way split is:

      - ``corporate_financial_large`` — FSE (``cp_is_financial_sector_entity``)
        OR large corporate (``cp_annual_revenue`` > the Art. 147A(1)(d) GBP 440m
        threshold). Art. 147A(1)(e).
      - ``corporate_sme`` — ``is_sme`` (turnover <= GBP 44m). Art. 147A(1)(f).
      - ``corporate_other`` — otherwise. Art. 147A(1)(f).

    Reuses the FSE predicate and the large-corporate revenue threshold
    (``regulatory_threshold(pack, "large_corporate_revenue_threshold", …)``) shared
    with ``_apply_b31_approach_restrictions``; non-corporate rows stay null.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    null_subclass = pl.lit(None, dtype=pl.String).alias("exposure_subclass")
    if not resolved_pack.feature("b31_exposure_subclass_reporting_applies"):
        return exposures.with_columns(null_subclass)

    is_corporate = pl.col("exposure_class").is_in(
        [ExposureClass.CORPORATE.value, ExposureClass.CORPORATE_SME.value]
    )

    is_fse = (pl.col("cp_is_financial_sector_entity") == True).fill_null(False)  # noqa: E712

    is_large_by_revenue = (
        pl.col("cp_annual_revenue")
        > float(
            regulatory_threshold(
                resolved_pack, "large_corporate_revenue_threshold", config.eur_gbp_rate
            )
        )
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


# =========================================================================
# Private helpers
# =========================================================================


def _build_has_property_expr(schema_names: set[str]) -> pl.Expr:
    """Build has_property_collateral expression.

    The property aggregates are hierarchy_exit contract columns —
    always present, null/False = no property collateral.
    """
    expr = (pl.col("property_collateral_value") > 0) | (
        pl.col("has_facility_property_collateral") == True  # noqa: E712
    )

    # KEEP (presence guard on a non-contract column): ``collateral_type``
    # is a collateral-table column, not declared on hierarchy_exit — a
    # sealed classifier input never carries it, so this branch only
    # contributes for direct expression-level use on hand-rolled frames.
    if "collateral_type" in schema_names:
        expr = expr | pl.col("collateral_type").is_in(
            ["immovable", "residential", "commercial"],
        )

    return expr
