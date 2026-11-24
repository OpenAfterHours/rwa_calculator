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
  Art. 147(4C)(b)(ii) / 147A(1)(e)(ii) conservatism), CLS011 (a group-revenue
  roll-up that forces F-IRB, Art. 147(4C)(b)(ii)), CLS013 (a null counterparty
  ``entity_type``, Art. 112 class undeterminable — RC-12) and SA011 (a non-UK
  PSE with no ``is_equivalent_jurisdiction``, weighted at the Art. 116(5) 100%
  as obligor and as guarantor) — one collect over the counterparty lookup.
- ``collect_classified_frame_warnings``: the row-count roll-ups over the
  materialised classified frame, from ONE collect — DQ008 for
  ``is_defaulted=False ∧ beel>0`` rows, CLS010 for revolving retail rows a
  QRRE gate kept out of QRRE, SA006 for project-finance rows whose phase
  was defaulted to pre-operational, CLS012 for slotted rows with no
  recognised grade, RE005 for a mortgage label without evidence of security
  and RE006 for an LTV derived from the property value (eager — must run
  post-materialise).
- ``collect_group_threshold_warnings``: AGG004 aggregate warning for rows that
  failed the retail threshold only because of debt owed to other entities of
  the reporting group (solo / sub-consolidated runs; post-materialise).
- ``build_audit_trail``: per-exposure classification reason frame.

References:
- PRA PS1/26 Art. 147(4C)(b)(ii) with Art. 147A(1)(e)(ii): large-corporate
  F-IRB restriction (CLS008); Art. 147(4C)(a): the specialised-lending
  subclass is outside it (CLS008 / CLS011)
- PRA PS1/26 Art. 147(4C)(b)(ii): highest-consolidation group revenue test —
  the roll-up flip warning (CLS011)
- PS1/26 Art. 181(1)(h)(ii) / CRR Art. 158(5): BEEL defined for defaulted
  exposures only (DQ008 companion check)
- PS1/26 Glossary "real estate exposure" / Art. 124A(1)(a), CRR Art. 125(1):
  security, not a product label, makes an exposure real estate (RE005)
- PS1/26 Art. 124C: LTV = amount of the loan / value of the property (RE006)
- CRR Art. 123(c) / PS1/26 Art. 123A(1)(b)(ii): group-wide retail threshold
  (AGG004)
- CRR Art. 4(1)(128D) / Commission Rec 2003/361/EC Art. 2: SME fallback
  suppressing the CLS008 warning
- PS1/26 glossary SME ("annual turnover of not more than GBP 44 million ...
  calculated on the basis of the highest consolidated accounts of the group"):
  CLS015 / CLS016
- CRR Art. 154(4)(a)-(b) / PS1/26 Art. 147(5A)(a)-(b): QRRE gates (CLS010)
- PRA PS1/26 Art. 122B(2)(c)/(3): project-finance phase not demonstrated (SA006)
- CRR / PS1/26 Art. 153(5): slotting weight by the assigned grade (CLS012)
- CRR Art. 112 / PS1/26 Art. 112(2) Table A2: exposure-class assignment (CLS013)
- CRR Art. 116(5) / PS1/26 Art. 116(3A): third-country PSE equivalence (SA011)
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
    ERROR_NULL_ENTITY_TYPE,
    ERROR_QRRE_GATE_DEMOTION,
    ERROR_SME_GROUP_SIZE_FLIP,
    ERROR_SME_REVENUE_NULL_B31,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    beel_on_non_defaulted_exposure_warning,
    classification_warning,
    ltv_derived_warning,
    no_property_evidence_warning,
    pf_phase_unevidenced_warning,
    pse_equivalence_unasserted_warning,
    slotting_category_missing_warning,
)
from rwa_calc.domain.enums import ApproachType, ExposureClass, SlottingCategory
from rwa_calc.engine.classify.attributes import (
    group_size_exprs,
    is_sme_by_size_expr,
    large_corporate_test_entity_expr,
    natural_person_expr,
    sme_size_exprs,
)
from rwa_calc.engine.classify.re_evidence import re_evidence_count_exprs
from rwa_calc.engine.classify.subtypes import (
    qrre_undrawn_cancellable_expr,
    qrre_unsecured_expr,
)
from rwa_calc.engine.entity_class_maps import entity_types_by_sa_class
from rwa_calc.engine.sa.jurisdiction import pse_equivalence_unasserted_expr
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
    - **Large-corp F-IRB restriction conservatism** (CLS008, Art. 147(4C)(b)(ii)
      with Art. 147A(1)(e)(ii), Basel 3.1 only): a ``corporate`` / ``company``
      with null group revenue, no SME-sized group total assets and no
      specialised-lending record (Art. 147(4C)(a)) is treated as large-corp by
      default (see ``_apply_b31_approach_restrictions``).
    - **Group revenue roll-up flip** (CLS011, Art. 147(4C)(b)(ii), Basel 3.1
      only): own turnover at/below GBP 440m but the highest-consolidation group
      turnover above it, so the large-corporate subclass forces F-IRB.
    - **Null entity_type** (CLS013, Art. 112, BOTH regimes, RC-12): a
      counterparty whose ``entity_type`` is null cannot be mapped to an
      exposure class; its exposures fall to OTHER (100% SA) and its rating is
      not read. The warning names the first few counterparties; the fallback
      class is unchanged.
    - **Third-country PSE equivalence unasserted** (SA011, CRR Art. 116(5),
      BOTH regimes): a PSE counterparty that is not definitely UK and whose
      ``is_equivalent_jurisdiction`` is null. The engine weights it at the
      Art. 116(5) 100% wherever it appears — as an obligor
      (``sa/risk_weights.py``) and as a guarantor (``sa/guarantor_rw.py``) —
      which is right on the data supplied but turns a 20% Table 2 / 2A weight
      into 100% for an equivalent jurisdiction whose flag was never populated.
      Counted on the counterparty lookup because the guarantor IS a
      counterparty row, so one census covers both uses; an explicit False is a
      determination and does not count.

    Column-absence warnings (the historical CLS005 / CLS007) are gone: the
    counterparty lookup is sealed against ``CP_LOOKUP_COUNTERPARTIES_EDGE``, so
    every declared column is present. All counts come from ONE ``.collect()``
    on the (small) counterparty lookup.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    group_revenue, group_assets = group_size_exprs()
    counterparties = _with_sl_record_marker(
        data.counterparty_lookup.counterparties.with_columns(
            group_revenue.alias("group_annual_revenue"), group_assets.alias("group_total_assets")
        ),
        data.specialised_lending,
    )
    filters = _input_warning_filters(config, resolved_pack)
    # CLS013 rides the same select: its count plus the first few references,
    # so the message can name rows without a second collect.
    is_null_entity_type = pl.col("entity_type").is_null()
    # SA011 rides it too: PSE rows (the run pack's SA class map) whose
    # Art. 116(5) gate binds only because no equivalence flag was supplied.
    pse_types = list(entity_types_by_sa_class(resolved_pack).get(ExposureClass.PSE.value, ()))
    pse_unasserted = pl.col("entity_type").str.to_lowercase().is_in(
        pse_types
    ) & pse_equivalence_unasserted_expr("country_code", "is_equivalent_jurisdiction")
    counts = (
        counterparties.select(
            *[flag.sum().alias(code) for code, flag in filters.items()],
            pse_unasserted.sum().alias("_pse_equivalence_unasserted"),
            is_null_entity_type.sum().alias("_null_entity_type"),
            pl.col("counterparty_reference")
            .filter(is_null_entity_type)
            .head(5)  # names the first five; the message counts the rest
            .implode()
            .alias("_null_entity_type_refs"),
        )
        .collect()
        .row(0, named=True)
    )
    errors = _null_entity_type_warnings(
        counts.pop("_null_entity_type"), list(counts.pop("_null_entity_type_refs"))
    )
    pse_unasserted_count = counts.pop("_pse_equivalence_unasserted")
    if pse_unasserted_count:
        errors.append(pse_equivalence_unasserted_warning(n=pse_unasserted_count))
    errors.extend(
        _input_warning(code, count, config, resolved_pack)
        for code, count in counts.items()
        if count
    )
    return errors


def collect_classified_frame_warnings(
    classified: pl.LazyFrame,
) -> list[CalculationError]:
    """Roll the per-row classification warnings up from ONE collect.

    Runs on the materialised classifier-exit frame (the scratch column
    ``_sl_project_phase_defaulted`` is still present; the seal strips it
    afterwards). Each warning is a single aggregate carrying its row count,
    and is omitted when the count is zero:

    - **DQ008** — ``is_defaulted=False ∧ beel>0``. PS1/26 Art. 181(1)(h)(ii)
      and CRR Art. 158(5) define BEEL only for defaulted exposures; the
      classifier deliberately does NOT treat ``beel > 0`` as a default trigger
      (see ``_build_is_defaulted_expr``), so the contradiction is surfaced
      here. Reads the *derived* ``is_defaulted``, so rows the counterparty
      cascade routes to defaulted are not flagged.
    - **CLS010** — a revolving regulatory-retail row (RETAIL_OTHER) that fails
      an Art. 154(4)(a)-(b) / Art. 147(5A)(a)-(b) QRRE gate (not to an
      individual, secured, or — to the extent undrawn — not unconditionally
      cancellable) and so stays out of QRRE. Rows demoted purely by the (c)
      aggregate-nominal limit pass every (a)/(b) gate and are not flagged.
      Reuses the classifier's own gate predicates so it cannot drift.
    - **SA006** — a project-finance row whose phase
      ``resolve_sl_project_phase`` defaulted to pre-operational (PS1/26
      Art. 122B(3)); always zero under CRR, where the Feature is off.
    - **CLS012** — a row routed to the slotting approach whose
      ``slotting_category`` is null or not a ``SlottingCategory`` value
      (case-insensitive, as the slotting lookup reads it). Both regimes. The
      slotting calculator weights it at the cited ``satisfactory`` default;
      this makes that visible (review IV-09, warning half).
    - **RE005** — a mortgage product label with no evidence of real-estate
      security (``re_evidence.re_evidence_count_exprs``; review CL-08).
    - **RE006** — an LTV the hierarchy derived from the linked property value
      (review RE-10). ``beel`` and ``ltv_derived`` are hierarchy_exit contract
      columns — always present.

    One collect for all six: ``engine_eager_collect_sites`` is a
    non-increasing ratchet, so a new roll-up joins this select rather than
    adding a materialisation.
    """
    failed_qrre_gate = (
        ~natural_person_expr() | ~qrre_unsecured_expr() | ~qrre_undrawn_cancellable_expr()
    )
    would_be_qrre_candidate = (
        (pl.col("exposure_class") == ExposureClass.RETAIL_OTHER.value)
        & pl.col("is_revolving")
        & pl.col("qualifies_as_retail")
    )
    grade = pl.col("slotting_category").str.to_lowercase()
    slotted_without_grade = (pl.col("approach") == ApproachType.SLOTTING.value) & (
        grade.is_null() | ~grade.is_in([member.value for member in SlottingCategory])
    )
    counts = classified.select(
        (~pl.col("is_defaulted").fill_null(False) & (pl.col("beel").fill_null(0.0) > 0.0))
        .sum()
        .alias("beel_on_non_defaulted"),
        (would_be_qrre_candidate & failed_qrre_gate).sum().alias("qrre_gate_demoted"),
        pl.col("_sl_project_phase_defaulted").sum().alias("pf_phase_defaulted"),
        slotted_without_grade.sum().alias("slotting_grade_missing"),
        *[expr.alias(name) for name, expr in re_evidence_count_exprs().items()],
    ).collect()

    errors: list[CalculationError] = []
    beel_count = counts["beel_on_non_defaulted"].item()
    if beel_count:
        errors.append(beel_on_non_defaulted_exposure_warning(n=beel_count))
    demoted_count = counts["qrre_gate_demoted"].item()
    if demoted_count:
        errors.append(_qrre_gate_demotion_warning(demoted_count))
    pf_phase_count = counts["pf_phase_defaulted"].item()
    if pf_phase_count:
        errors.append(pf_phase_unevidenced_warning(n=pf_phase_count))
    grade_missing_count = counts["slotting_grade_missing"].item()
    if grade_missing_count:
        errors.append(slotting_category_missing_warning(n=grade_missing_count))
    re005_standardised = counts["re005_standardised"].item()
    re005_other = counts["re005_other"].item()
    if re005_standardised or re005_other:
        errors.append(
            no_property_evidence_warning(n_standardised=re005_standardised, n_other=re005_other)
        )
    re006_count = counts["re006"].item()
    if re006_count:
        errors.append(ltv_derived_warning(n=re006_count))
    return errors


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
    rather than left silent. Only natural persons and SME-sized obligors are
    counted: the threshold governs those alone (PS1/26 Art. 123(1)(a)/(b); CRR
    Art. 123(a) "a natural person or persons, or ... an SME"), so a large
    corporate or a bank is never retail whatever the group owes, and counting it
    would make the warning fire for every multi-entity wholesale obligor. Empty on
    an unscoped or whole-group run, where the increment column is null throughout
    — an unscoped run returns at once rather than pay a collect to count nothing.
    Reads the pre-seal classified frame.
    """
    if config.reporting_entity is None:
        return []
    limit = float(regulatory_threshold(pack, "retail_max_exposure", config.eur_gbp_rate))
    own = pl.col("lending_group_adjusted_exposure")
    retail_governed = natural_person_expr() | is_sme_by_size_expr(config, pack=pack)
    flipped = (
        retail_governed
        & (own <= limit)
        & (pl.sum_horizontal(own, pl.col("out_of_scope_group_adjusted_exposure")) > limit)
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


def _with_sl_record_marker(
    counterparties: pl.LazyFrame, specialised_lending: pl.LazyFrame | None
) -> pl.LazyFrame:
    """Add ``_sl_record_reference``: non-null where the counterparty has an SL record.

    The classifier joins the specialised-lending table by
    ``counterparty_reference`` and puts every exposure of a counterparty whose
    record carries an ``sl_type`` in the specialised-lending class
    (``attributes.join_specialised_lending`` / ``derive_independent_flags``), so
    the counterparty-level marker selects exactly the obligors whose rows the
    Art. 147(4C)(a) exclusion takes out of the large-corporate test. A lazy left
    join — it adds no ``collect`` to the single one in ``collect_input_warnings``.
    """
    if specialised_lending is None:
        return counterparties.with_columns(
            pl.lit(None, dtype=pl.String).alias("_sl_record_reference")
        )
    sl_records = (
        specialised_lending.filter(pl.col("sl_type").is_not_null())
        .select(pl.col("counterparty_reference"))
        .unique()
        .with_columns(pl.col("counterparty_reference").alias("_sl_record_reference"))
    )
    return counterparties.join(sl_records, on="counterparty_reference", how="left")


def _input_warning_filters(config: CalculationConfig, pack: ResolvedRulepack) -> dict[str, pl.Expr]:
    """Per warning code, the counterparty predicate it counts (False when off).

    Reads the lookup with ``group_size_exprs`` applied and the
    ``_sl_record_reference`` marker from ``_with_sl_record_marker``.
    Regime-gated codes are a ``False`` literal when their Feature is off, so one
    select counts all.

    The corporate population is ``large_corporate_test_entity_expr`` — the same
    predicate the approach restriction reads (``corporate`` and its alias
    ``company``, P1.321). CLS008 and CLS011 announce the Art. 147(4C)(b)(ii)
    F-IRB restriction, which Art. 147(4C)(a) never applies to the
    specialised-lending subclass, so a counterparty with a specialised-lending
    record is not counted for them. CLS015 keeps it: SME status is not a
    subclass test and still reaches a specialised-lending obligor (the IRB
    firm-size adjustment reads ``is_sme``).
    """
    balance_sheet_threshold = float(
        regulatory_threshold(pack, "sme_balance_sheet_threshold", config.eur_gbp_rate)
    )
    large_corp_threshold = float(
        regulatory_threshold(pack, "large_corporate_revenue_threshold", config.eur_gbp_rate)
    )
    is_corporate = large_corporate_test_entity_expr("entity_type")
    # Art. 147(4C)(a): outside the specialised-lending subclass.
    in_large_corporate_test = is_corporate & pl.col("_sl_record_reference").is_null()
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
            in_large_corporate_test
            & pl.col("group_annual_revenue").is_null()
            & (
                pl.col("group_total_assets").is_null()
                | (pl.col("group_total_assets") >= balance_sheet_threshold)
            )
            if b31_restrictions
            else off
        ),
        # CLS011: own revenue small, the group's large.
        ERROR_LARGE_CORP_GROUP_ROLLUP: (
            in_large_corporate_test
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
            f"Art. 147(4C)(b)(ii) large-corporate F-IRB restriction applied conservatively for "
            f"{count} corporate counterparty row(s) with null annual_revenue (own and "
            f"rolled-up group) and no SME-confirming total_assets — could not confirm size "
            f"is below the GBP 440m threshold.",
            "PRA PS1/26 Art. 147(4C)(b)(ii), Art. 147A(1)(e)(ii)",
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


# =========================================================================
# Private helpers
# =========================================================================


def _qrre_gate_demotion_warning(demoted_count: int) -> CalculationError:
    """The CLS010 roll-up for revolving retail rows a QRRE gate kept in RETAIL_OTHER."""
    return classification_warning(
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


@cites("CRR Art. 112")
@cites("PS1/26, paragraph 112")
def _null_entity_type_warnings(count: int, references: list[str | None]) -> list[CalculationError]:
    """Return the RC-12 CLS013 warning for counterparties with a null ``entity_type``.

    ``entity_type`` is the single source of the exposure class (Art. 112(2): an
    institution "shall assign exposures to the exposure classes listed in Column A
    of Table A2 according to the criteria in the corresponding row of Column B").
    A null matches no row of the class map, so every exposure to the counterparty
    falls to OTHER (100% SA) and its ECAI rating is never read. The class is left
    as it is — the true class, and so the direction of error, is unknowable from
    the row (orchestrator decision) — but the run says so, naming the rows.
    """
    if count == 0:
        return []
    named = ", ".join(str(reference) for reference in references)
    more = f" and {count - len(references)} more" if count > len(references) else ""
    return [
        CalculationError(
            code=ERROR_NULL_ENTITY_TYPE,
            message=(
                f"{count} counterparty row(s) carry a null entity_type ({named}{more}). "
                "Their exposures cannot be assigned an Art. 112 exposure class and fall to "
                "the residual 'other' class at 100% (SA); any external rating is not used. "
                "The true class may carry a higher or a lower weight — populate entity_type."
            ),
            severity=ErrorSeverity.WARNING,
            category=ErrorCategory.CLASSIFICATION,
            regulatory_reference="CRR Art. 112 / PRA PS1/26 Art. 112(2) Table A2",
            field_name="entity_type",
        )
    ]
