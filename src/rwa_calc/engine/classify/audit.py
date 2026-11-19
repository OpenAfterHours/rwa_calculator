"""
Audit trail and data-quality warnings for the classification stage.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (engine/classify) -> CRMProcessor
    Sub-module of the classify stage package; consumed by ``classifier``
    (input warnings before flag derivation, BEEL warnings after the
    stage-exit materialise, audit trail at bundle build).

Key responsibilities:
- ``collect_input_warnings``: CLS009 (LFSE assets unknown), CLS016 (SME
  status decided by the consolidated group), CLS015 (Basel 3.1 SME turnover
  unknown), CLS008 (null corporate group annual_revenue under Basel 3.1,
  Art. 147A(1)(d) conservatism) and CLS011 (a group-revenue roll-up that forces
  F-IRB, Art. 147(4C)(b)(ii)) — one collect over the counterparty lookup.
- ``collect_beel_on_non_defaulted_warnings``: DQ008 aggregate warning for
  ``is_defaulted=False ∧ beel>0`` rows (eager — must run post-materialise).
- ``collect_group_threshold_warnings``: AGG004 aggregate warning for rows that
  failed the retail threshold only because of debt owed to other entities of
  the reporting group (solo / sub-consolidated runs; post-materialise).
- ``build_audit_trail``: per-exposure classification reason frame.

References:
- PRA PS1/26 Art. 147A(1)(d): large-corporate F-IRB restriction (CLS008)
- PRA PS1/26 Art. 147(4C)(b)(ii): highest-consolidation group revenue test —
  the roll-up flip warning (CLS011)
- PS1/26 Art. 181(1)(h)(ii) / CRR Art. 158(5): BEEL defined for defaulted
  exposures only (DQ008 companion check)
- CRR Art. 123(c) / PS1/26 Art. 123A(1)(b)(ii): group-wide retail threshold
  (AGG004)
- CRR Art. 4(1)(128D) / Commission Rec 2003/361/EC Art. 2: SME fallback
  suppressing the CLS008 warning
- PS1/26 glossary SME ("annual turnover of not more than GBP 44 million ...
  calculated on the basis of the highest consolidated accounts of the group"):
  CLS015 / CLS016
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import (
    ERROR_GROUP_THRESHOLD_FROM_OTHER_ENTITIES,
    ERROR_LARGE_CORP_GROUP_ROLLUP,
    ERROR_LARGE_CORP_REVENUE_NULL,
    ERROR_LFSE_ASSETS_NULL,
    ERROR_QRRE_GATE_DEMOTION,
    ERROR_SME_GROUP_SIZE_FLIP,
    ERROR_SME_REVENUE_NULL_B31,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    beel_on_non_defaulted_exposure_warning,
    classification_warning,
)
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.classify.attributes import (
    group_size_exprs,
    is_sme_by_size_expr,
    natural_person_expr,
    sme_size_exprs,
)
from rwa_calc.engine.classify.subtypes import (
    qrre_undrawn_cancellable_expr,
    qrre_unsecured_expr,
)
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.rulebook import RulepackV0

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import ResolvedHierarchyBundle
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)


# =========================================================================
# Input-data warnings (non-blocking; collected as CalculationError list)
# =========================================================================


def collect_input_warnings(
    data: ResolvedHierarchyBundle,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> list[CalculationError]:
    """Collect non-blocking warnings for counterparty size data.

    Each warning is a ``CalculationError`` with severity WARNING, counted over
    the counterparty lookup's consolidated group figures (``group_size_exprs``)
    — the same figures the classifier sizes on:

    - **LFSE size undetermined** (CLS009, Art. 153(2), BOTH regimes): a
      counterparty flagged ``is_financial_sector_entity=True`` whose LFSE asset
      figure is null (own assets under CRR; group assets under Basel 3.1, see the
      ``lfse_assets_at_highest_consolidation`` Feature) and with no explicit
      ``apply_fi_scalar`` election: the mandatory 1.25x correlation multiplier
      cannot be derived, so it is not applied and the gap is never silent.
    - **SME status decided by the group** (CLS016, BOTH regimes): the entity's
      OWN figures pass the SME size test but its consolidated group's do not, so
      it gets no SME treatment (PS1/26 glossary SME (1) "highest consolidated
      accounts of the group"; Art. 153(4) "consolidated group").
    - **Basel 3.1 SME turnover unknown** (CLS015, when the
      ``sme_size_assets_fallback`` Feature is off): a corporate with no annual
      revenue (own or group) whose total assets are under the balance-sheet
      threshold — an SME under CRR's Rec 2003/361/EC balance-sheet limb, not
      under the turnover-only PS1/26 glossary SME, so no SME treatment applies.
    - **Large-corp F-IRB restriction conservatism** (CLS008, Art. 147A(1)(d),
      Basel 3.1 only): a corporate with null group revenue and no SME-sized
      group total assets is treated as large-corp by default (see
      ``_apply_b31_approach_restrictions``).
    - **Group revenue roll-up flip** (CLS011, Art. 147(4C)(b)(ii), Basel 3.1
      only): own turnover at/below GBP 440m but the highest-consolidation group
      turnover above it, so the large-corporate subclass forces F-IRB.

    Column-absence warnings (the historical CLS005 / CLS007) are gone: the
    counterparty lookup is sealed against ``CP_LOOKUP_COUNTERPARTIES_EDGE``, so
    every declared column is present. All counts come from ONE ``.collect()``
    on the (small) counterparty lookup.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    group_revenue, group_assets = group_size_exprs()
    counterparties = data.counterparty_lookup.counterparties.with_columns(
        group_revenue.alias("group_annual_revenue"), group_assets.alias("group_total_assets")
    )
    filters = _input_warning_filters(config, resolved_pack)
    counts = (
        counterparties.select([flag.sum().alias(code) for code, flag in filters.items()])
        .collect()
        .row(0, named=True)
    )
    return [
        _input_warning(code, count, config, resolved_pack)
        for code, count in counts.items()
        if count
    ]


def collect_beel_on_non_defaulted_warnings(
    classified: pl.LazyFrame,
) -> list[CalculationError]:
    """Emit a single aggregate DQ008 warning summing ``(is_defaulted=False ∧ beel>0)`` rows.

    PS1/26 Art. 181(1)(h)(ii) and CRR Art. 158(5) define BEEL only for
    defaulted exposures, but a firm's A-IRB model pipeline may emit a
    BEEL-style value alongside LGD on performing rows. The classifier
    deliberately does NOT treat ``beel > 0`` as a default trigger (see
    ``_build_is_defaulted_expr``); this companion check surfaces the
    input contradiction as a non-blocking data-quality warning so the
    audit trail is explicit.

    Returns an empty list when no rows are offending (``beel`` is a
    hierarchy_exit contract column — always present, null = not
    supplied). Otherwise returns a single-element list carrying the
    total count, matching the CLS006 / CLS008 roll-up pattern used by
    every other classifier-stage warning. Reads the *derived*
    ``is_defaulted`` so rows that the counterparty cascade legitimately
    routes to defaulted are NOT flagged — those rows correctly consume
    BEEL in the IRB defaulted formula.
    """
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


def collect_qrre_gate_demotion_warnings(
    classified: pl.LazyFrame,
) -> list[CalculationError]:
    """Emit a single aggregate CLS010 warning for revolving retail rows denied QRRE.

    CRR Art. 154(4)(a)-(b) / PS1/26 Art. 147(5A)(a)-(b) restrict the qualifying
    revolving retail exposures (QRRE) sub-class to exposures that are (a) to
    individuals and (b) revolving, unsecured and — to the extent undrawn —
    unconditionally cancellable. A row that is otherwise a QRRE candidate
    (RETAIL_OTHER, regulatory-retail, revolving) but fails one of those gates is
    correctly left in RETAIL_OTHER rather than admitted to QRRE (whose lower
    correlation would understate RWA). This companion check surfaces those
    gate-driven demotions as a single non-blocking warning so the reason a
    revolving retail line missed QRRE is explicit in the audit trail.

    Rows demoted purely by the (c) aggregate-nominal limit are NOT flagged —
    they pass every (a)/(b) gate and their demotion is the long-standing
    per-obligor cap behaviour, not a new gate. The driver columns
    (``is_secured`` / ``risk_type`` / ``undrawn_amount`` / ``cp_entity_type`` /
    ``cp_is_natural_person``) are present on the pre-seal classified frame.
    """
    # Fails an (a)/(b) gate: not an individual, secured, or (undrawn and) not
    # unconditionally cancellable. Reuses the exact gate predicates the
    # classifier applies (subtypes.py) so the warning cannot drift from the rule.
    failed_gate = ~natural_person_expr() | ~qrre_unsecured_expr() | ~qrre_undrawn_cancellable_expr()
    would_be_candidate = (
        (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
        & pl.col("is_revolving")
        & pl.col("qualifies_as_retail")
    )
    demoted_count = (
        classified.filter(would_be_candidate & failed_gate).select(pl.len()).collect().item()
    )
    if demoted_count == 0:
        return []
    return [
        classification_warning(
            code=ERROR_QRRE_GATE_DEMOTION,
            message=(
                f"{demoted_count} revolving regulatory-retail exposure(s) were kept in "
                "RETAIL_OTHER rather than admitted to QRRE: they fail an "
                "Art. 147(5A)(a)-(b) / Art. 154(4)(a)-(b) gate (not to an individual, "
                "secured, or — to the extent undrawn — not unconditionally cancellable). "
                "QRRE's lower correlation would understate RWA, so the demotion is "
                "conservative."
            ),
            regulatory_reference="CRR Art. 154(4)(a)-(b) / PS1/26 Art. 147(5A)(a)-(b)",
        )
    ]


@cites("CRR Art. 123")
@cites("PS1/26, paragraph 123A")
def collect_group_threshold_warnings(
    classified: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack,
) -> list[CalculationError]:
    """Emit one AGG004 warning for rows that failed the retail threshold only on group debt.

    On a solo / sub-consolidated run the retail threshold counts the amount the
    obligor owes to the institution, its parent undertakings, its subsidiaries
    and subsidiaries of its parent undertakings (CRR Art. 123(c); PS1/26
    Art. 123(1)(b)(ii) / 123A(1)(b)(ii) / 147(5)(a)(ii)) — the whole reporting
    group, carried as ``out_of_scope_group_adjusted_exposure``. A row whose own
    books are within the limit but whose group-wide aggregate is over it is
    classified differently from what the run's own books show, so it is named
    rather than left silent. Empty on an unscoped or whole-group run, where the
    increment column is null throughout — an unscoped run returns at once rather
    than pay a collect to count nothing. Reads the pre-seal classified frame.
    """
    if config.reporting_entity is None:
        return []
    limit = float(regulatory_threshold(pack, "retail_max_exposure", config.eur_gbp_rate))
    own = pl.col("lending_group_adjusted_exposure")
    flipped = (own <= limit) & (
        pl.sum_horizontal(own, pl.col("out_of_scope_group_adjusted_exposure")) > limit
    )
    counts = classified.filter(flipped).select(
        pl.len().alias("_rows"),
        pl.col("counterparty_reference").n_unique().alias("_obligors"),
    )
    row = counts.collect().row(0, named=True)
    if row["_rows"] == 0:
        return []
    return [
        CalculationError(
            code=ERROR_GROUP_THRESHOLD_FROM_OTHER_ENTITIES,
            message=(
                f"{row['_rows']} exposure row(s) across {row['_obligors']} obligor(s) "
                f"failed the retail threshold (GBP {limit:,.0f}) only because of debt "
                "owed to other entities of the reporting group: the run's own books "
                "are within the limit, the amount owed to the institution, its parent "
                "undertakings and their subsidiaries is not. The exposures are not "
                "(regulatory) retail on this solo / sub-consolidated run."
            ),
            severity=ErrorSeverity.WARNING,
            category=ErrorCategory.CLASSIFICATION,
            regulatory_reference=(
                "CRR Art. 123(c) / PS1/26 Art. 123(1)(b)(ii), 123A(1)(b)(ii), 147(5)(a)(ii)"
            ),
            field_name="out_of_scope_group_adjusted_exposure",
        )
    ]


# =========================================================================
# Input-warning helpers
# =========================================================================


def _input_warning_filters(config: CalculationConfig, pack: ResolvedRulepack) -> dict[str, pl.Expr]:
    """Per warning code, the counterparty predicate it counts (False when off).

    Reads the lookup with ``group_size_exprs`` applied. Regime-gated codes are
    a ``False`` literal when their Feature is off, so one select counts all.
    """
    balance_sheet_threshold = float(
        regulatory_threshold(pack, "sme_balance_sheet_threshold", config.eur_gbp_rate)
    )
    large_corp_threshold = float(
        regulatory_threshold(pack, "large_corporate_revenue_threshold", config.eur_gbp_rate)
    )
    is_corporate = pl.col("entity_type").fill_null("") == "corporate"
    lfse_assets = pl.col(
        "group_total_assets"
        if pack.feature("lfse_assets_at_highest_consolidation")
        else "total_assets"
    )
    own_metric, own_source = sme_size_exprs(pl.col("annual_revenue"), pl.col("total_assets"))
    group_metric, group_source = sme_size_exprs(
        pl.col("group_annual_revenue"), pl.col("group_total_assets")
    )
    off = pl.lit(value=False)
    b31_restrictions = pack.feature("approach_restrictions_b31_applicable")
    group_revenue_null = is_corporate & pl.col("group_annual_revenue").is_null()
    return {
        # CLS009: the flagged FSE's LFSE asset figure is unknown.
        ERROR_LFSE_ASSETS_NULL: (
            pl.col("is_financial_sector_entity").fill_null(False)
            & lfse_assets.is_null()
            & ~pl.col("apply_fi_scalar").fill_null(False)
        ),
        # CLS016: own figures are SME-sized, the consolidated group's are not.
        ERROR_SME_GROUP_SIZE_FLIP: (
            is_sme_by_size_expr(config, pack=pack, metric=own_metric, source=own_source)
            & ~is_sme_by_size_expr(config, pack=pack, metric=group_metric, source=group_source)
        ),
        # CLS015: no turnover anywhere in the group, assets the balance-sheet
        # limb would have accepted — only where that limb is not the regime's.
        ERROR_SME_REVENUE_NULL_B31: (
            off
            if pack.feature("sme_size_assets_fallback")
            else group_revenue_null
            & (pl.col("group_total_assets") > 0)
            & (pl.col("group_total_assets") < balance_sheet_threshold)
        ),
        # CLS008: null group revenue and no SME-sized group assets.
        ERROR_LARGE_CORP_REVENUE_NULL: (
            group_revenue_null
            & (
                pl.col("group_total_assets").is_null()
                | (pl.col("group_total_assets") >= balance_sheet_threshold)
            )
            if b31_restrictions
            else off
        ),
        # CLS011: own revenue small, the group's large.
        ERROR_LARGE_CORP_GROUP_ROLLUP: (
            is_corporate
            & (
                pl.col("annual_revenue").is_null()
                | (pl.col("annual_revenue") <= large_corp_threshold)
            )
            & (pl.col("group_annual_revenue") > large_corp_threshold)
            if b31_restrictions
            else off
        ),
    }


def _input_warning(
    code: str, count: int, config: CalculationConfig, pack: ResolvedRulepack
) -> CalculationError:
    """Build the WARNING for one ``_input_warning_filters`` code and its count."""
    turnover = float(regulatory_threshold(pack, "sme_turnover_threshold", config.eur_gbp_rate))
    messages: dict[str, tuple[str, str, str]] = {
        ERROR_LFSE_ASSETS_NULL: (
            f"Art. 153(2) large-FSE 1.25x correlation multiplier could not be derived for "
            f"{count} financial-sector counterparty row(s) with null total_assets (at the "
            f"basis the regime sizes a large FSE on) and no apply_fi_scalar election — the "
            f"multiplier was NOT applied (supply total_assets or set apply_fi_scalar to "
            f"confirm the LFSE treatment).",
            "CRR Art. 142(1)(4) / Art. 153(2)",
            "total_assets",
        ),
        ERROR_SME_GROUP_SIZE_FLIP: (
            f"SME size test decided by the consolidated group for {count} counterparty "
            f"row(s): the entity's own annual_revenue / total_assets are SME-sized but its "
            f"group's (the highest consolidation among it and its org_mappings ancestors) "
            f"are not, so no SME treatment applies.",
            "PS1/26 glossary SME (1) / CRR Art. 153(4)",
            "annual_revenue",
        ),
        ERROR_SME_REVENUE_NULL_B31: (
            f"{count} corporate counterparty row(s) have no annual_revenue (own or group) "
            f"but total_assets under the balance-sheet threshold: the PS1/26 SME definition "
            f"is turnover only ('not more than GBP {turnover:,.0f}'), so they are NOT "
            f"treated as SMEs (no 85% weight, no SME retail route, no IRB firm-size "
            f"adjustment). Supply annual_revenue to establish SME status.",
            "PS1/26 glossary SME / Art. 122(11)",
            "annual_revenue",
        ),
        ERROR_LARGE_CORP_REVENUE_NULL: (
            f"Art. 147A(1)(d) large-corporate F-IRB restriction applied conservatively for "
            f"{count} corporate counterparty row(s) with null annual_revenue (own and "
            f"rolled-up group) and no SME-confirming total_assets — could not confirm size "
            f"is below the GBP 440m threshold.",
            "PRA PS1/26 Art. 147A(1)(d)",
            "annual_revenue",
        ),
        ERROR_LARGE_CORP_GROUP_ROLLUP: (
            f"Art. 147(4C)(b)(ii) group-consolidation revenue roll-up restricted {count} "
            f"corporate counterparty row(s) to F-IRB: own annual_revenue is at or below GBP "
            f"440m but the highest-consolidation group revenue (the max over the entity and "
            f"its org_mappings ancestors) exceeds it, so A-IRB is not permitted for the "
            f"financial/large-corporates subclass.",
            "PRA PS1/26 Art. 147(4C)(b)(ii)",
            "annual_revenue",
        ),
    }
    message, reference, field_name = messages[code]
    return CalculationError(
        code=code,
        message=message,
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.CLASSIFICATION,
        regulatory_reference=reference,
        field_name=field_name,
    )


# =========================================================================
# Audit trail
# =========================================================================


def build_audit_trail(
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
