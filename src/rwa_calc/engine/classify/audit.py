"""
Audit trail and data-quality warnings for the classification stage.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (engine/classify) -> CRMProcessor
    Sub-module of the classify stage package; consumed by ``classifier``
    (input warnings before flag derivation, BEEL warnings after the
    stage-exit materialise, audit trail at bundle build).

Key responsibilities:
- ``collect_input_warnings``: CLS008 warning for null corporate group
  annual_revenue under Basel 3.1 (Art. 147A(1)(d) conservatism) and CLS011
  for a group-revenue roll-up that forces F-IRB (Art. 147(4C)(b)(ii)).
- ``collect_classified_frame_warnings``: the row-count roll-ups over the
  materialised classified frame, from ONE collect — DQ008 for
  ``is_defaulted=False ∧ beel>0`` rows, CLS010 for revolving retail rows a
  QRRE gate kept out of QRRE, SA006 for project-finance rows whose phase
  was defaulted to pre-operational, and CLS012 for slotted rows with no
  recognised grade (eager — must run post-materialise).
- ``build_audit_trail``: per-exposure classification reason frame.

References:
- PRA PS1/26 Art. 147A(1)(d): large-corporate F-IRB restriction (CLS008)
- PRA PS1/26 Art. 147(4C)(b)(ii): highest-consolidation group revenue test —
  the roll-up flip warning (CLS011)
- PS1/26 Art. 181(1)(h)(ii) / CRR Art. 158(5): BEEL defined for defaulted
  exposures only (DQ008 companion check)
- CRR Art. 4(1)(128D) / Commission Rec 2003/361/EC Art. 2: SME fallback
  suppressing the CLS008 warning
- CRR Art. 154(4)(a)-(b) / PS1/26 Art. 147(5A)(a)-(b): QRRE gates (CLS010)
- PRA PS1/26 Art. 122B(2)(c)/(3): project-finance phase not demonstrated (SA006)
- CRR / PS1/26 Art. 153(5): slotting weight by the assigned grade (CLS012)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.errors import (
    ERROR_LARGE_CORP_GROUP_ROLLUP,
    ERROR_LARGE_CORP_REVENUE_NULL,
    ERROR_LFSE_ASSETS_NULL,
    ERROR_QRRE_GATE_DEMOTION,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    beel_on_non_defaulted_exposure_warning,
    classification_warning,
    pf_phase_unevidenced_warning,
    slotting_category_missing_warning,
)
from rwa_calc.domain.enums import ApproachType, ExposureClass, SlottingCategory
from rwa_calc.engine.classify.attributes import (
    natural_person_expr,
    with_group_annual_revenue,
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
    """Collect non-blocking warnings for null input data.

    Three warnings can fire here, each surfaced as a ``CalculationError`` with
    severity WARNING:

    - **LFSE size undetermined** (Art. 153(2), BOTH regimes): when a
      counterparty is flagged ``is_financial_sector_entity=True`` but
      ``total_assets`` is null and no explicit ``apply_fi_scalar`` election
      was made, the mandatory 1.25x correlation multiplier (CRR Art.
      142(1)(4) / PS1/26 glossary) cannot be derived — the scalar is not
      applied and CLS009 flags the gap so it is never a silent
      under-statement.

    - **Large-corp F-IRB restriction conservatism** (Art. 147A(1)(d),
      Basel 3.1 only): when the rolled-up ``group_annual_revenue`` is null on
      any corporate counterparty (own AND ultimate-parent turnover both
      absent), the engine treats the row as large-corp by default (see
      ``_is_large_corp`` in ``_apply_b31_approach_restrictions``) and
      emits CLS008.

    - **Group revenue roll-up flip** (Art. 147(4C)(b)(ii), Basel 3.1 only):
      when a corporate's OWN turnover is at/below GBP 440m but its highest-
      consolidation group turnover (rolled up the ultimate-parent chain)
      exceeds it, the large-corporate subclass forces F-IRB. CLS011 records
      that the restriction was driven by the group, not the entity itself.

    Column-absence warnings (the historical CLS005 / CLS007) are gone:
    the counterparty lookup is sealed against
    ``CP_LOOKUP_COUNTERPARTIES_EDGE`` and the exposures frame against
    ``hierarchy_exit``, so every declared column is guaranteed present
    and the absent-column states those warnings detected are
    unrepresentable. Each null-count check materialises a count via a
    ``.collect()`` on the (small) counterparty lookup.
    """
    errors: list[CalculationError] = []
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack

    # Roll counterparty turnover up the ultimate-parent chain once, so the
    # large-corp checks below read the same Art. 147(4C)(b)(ii) highest-
    # consolidation ``group_annual_revenue`` the classifier's
    # ``_apply_b31_approach_restrictions`` uses. Only adds one column; every
    # other check on the frame is untouched.
    counterparties = with_group_annual_revenue(data.counterparty_lookup.counterparties)

    # Art. 153(2) (both regimes): a flagged FSE with null total_assets leaves
    # the LFSE size test (Art. 142(1)(4) / PS1/26 glossary) undetermined, so
    # ``classify_exposure_subtypes`` does not apply the 1.25x scalar. Emit
    # CLS009 unless the firm supplied an explicit apply_fi_scalar election
    # (which resolves the treatment either way).
    lfse_undetermined_filter = (
        pl.col("is_financial_sector_entity").fill_null(False)
        & pl.col("total_assets").is_null()
        & ~pl.col("apply_fi_scalar").fill_null(False)
    )
    lfse_undetermined_count = (
        counterparties.filter(lfse_undetermined_filter).select(pl.len()).collect().item()
    )
    if lfse_undetermined_count > 0:
        errors.append(
            CalculationError(
                code=ERROR_LFSE_ASSETS_NULL,
                message=(
                    f"Art. 153(2) large-FSE 1.25x correlation multiplier could not "
                    f"be derived for {lfse_undetermined_count} financial-sector "
                    f"counterparty row(s) with null total_assets and no apply_fi_scalar "
                    f"election — the multiplier was NOT applied (supply total_assets "
                    f"or set apply_fi_scalar to confirm the LFSE treatment)."
                ),
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.CLASSIFICATION,
                regulatory_reference="CRR Art. 142(1)(4) / Art. 153(2)",
                field_name="total_assets",
            )
        )

    if not resolved_pack.feature("approach_restrictions_b31_applicable"):
        return errors

    # Art. 147A(1)(d): null revenue triggers the conservative large-corp F-IRB
    # restriction — emit CLS008 to flag the conservatism. Corporate-only count
    # to avoid spurious warnings for non-corporate entity types where revenue
    # is genuinely irrelevant. Keyed on the rolled-up ``group_annual_revenue``:
    # a subsidiary with null own turnover but a revenue-bearing ultimate parent
    # is resolved by the roll-up (its size is known) and does NOT warn — only a
    # row whose OWN and GROUP revenue are both null is genuinely unresolved. The
    # warning is further suppressed when total_assets is populated AND below the
    # SME balance-sheet threshold (CRR Art. 4(1)(128D) / Commission Rec
    # 2003/361/EC Art. 2 fallback) — in that case the counterparty is
    # definitively SME-sized and the restriction is not applied.
    balance_sheet_threshold = float(
        regulatory_threshold(resolved_pack, "sme_balance_sheet_threshold", config.eur_gbp_rate)
    )
    large_corp_threshold = float(
        regulatory_threshold(
            resolved_pack, "large_corporate_revenue_threshold", config.eur_gbp_rate
        )
    )
    is_corporate = pl.col("entity_type").fill_null("") == "corporate"
    unresolved_filter = (
        is_corporate
        & pl.col("group_annual_revenue").is_null()
        & (pl.col("total_assets").is_null() | (pl.col("total_assets") >= balance_sheet_threshold))
    )
    # Art. 147(4C)(b)(ii): a corporate whose OWN turnover is at/below GBP 440m
    # but whose highest-consolidation group turnover (rolled up the ultimate-
    # parent chain) exceeds it is restricted to F-IRB by the group, not by
    # itself — a material, non-obvious classification driver worth surfacing for
    # the audit trail (mirrors the CLS010 QRRE-gate-demotion pattern). Mutually
    # exclusive with CLS008 (which needs a null group figure; this needs a >
    # threshold one), so no counterparty raises both; a row whose own revenue
    # already exceeds the threshold is large regardless of its group and is out.
    rollup_driven_filter = (
        is_corporate
        & (pl.col("annual_revenue").is_null() | (pl.col("annual_revenue") <= large_corp_threshold))
        & (pl.col("group_annual_revenue") > large_corp_threshold)
    )
    # One materialisation for both corporate-size counts (a boolean expression
    # sums as the count of matching rows).
    size_counts = counterparties.select(
        unresolved_filter.sum().alias("_unresolved"),
        rollup_driven_filter.sum().alias("_rollup_driven"),
    ).collect()
    unresolved_count = size_counts["_unresolved"].item()
    rollup_driven_count = size_counts["_rollup_driven"].item()
    if unresolved_count > 0:
        errors.append(
            CalculationError(
                code=ERROR_LARGE_CORP_REVENUE_NULL,
                message=(
                    f"Art. 147A(1)(d) large-corporate F-IRB restriction applied "
                    f"conservatively for {unresolved_count} corporate counterparty "
                    f"row(s) with null annual_revenue (own and rolled-up group) and no "
                    f"SME-confirming total_assets — could not confirm size is below the "
                    f"GBP 440m threshold."
                ),
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.CLASSIFICATION,
                regulatory_reference="PRA PS1/26 Art. 147A(1)(d)",
                field_name="annual_revenue",
            )
        )
    if rollup_driven_count > 0:
        errors.append(
            CalculationError(
                code=ERROR_LARGE_CORP_GROUP_ROLLUP,
                message=(
                    f"Art. 147(4C)(b)(ii) group-consolidation revenue roll-up restricted "
                    f"{rollup_driven_count} corporate counterparty row(s) to F-IRB: own "
                    f"annual_revenue is at or below GBP 440m but the highest-consolidation "
                    f"group revenue (rolled up the ultimate-parent chain) exceeds it, so "
                    f"A-IRB is not permitted for the financial/large-corporates subclass."
                ),
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.CLASSIFICATION,
                regulatory_reference="PRA PS1/26 Art. 147(4C)(b)(ii)",
                field_name="annual_revenue",
            )
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

    One collect for all four: ``engine_eager_collect_sites`` is a
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
    return errors


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
