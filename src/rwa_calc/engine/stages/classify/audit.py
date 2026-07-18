"""
Audit trail and data-quality warnings for the classification stage.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (stages/classify) -> CRMProcessor
    Sub-module of the classify stage package; consumed by ``classifier``
    (input warnings before flag derivation, BEEL warnings after the
    stage-exit materialise, audit trail at bundle build).

Key responsibilities:
- ``collect_input_warnings``: CLS008 warning for null corporate
  annual_revenue under Basel 3.1 (Art. 147A(1)(d) conservatism).
- ``collect_beel_on_non_defaulted_warnings``: DQ008 aggregate warning for
  ``is_defaulted=False ∧ beel>0`` rows (eager — must run post-materialise).
- ``build_audit_trail``: per-exposure classification reason frame.

References:
- PRA PS1/26 Art. 147A(1)(d): large-corporate F-IRB restriction (CLS008)
- PS1/26 Art. 181(1)(h)(ii) / CRR Art. 158(5): BEEL defined for defaulted
  exposures only (DQ008 companion check)
- CRR Art. 4(1)(128D) / Commission Rec 2003/361/EC Art. 2: SME fallback
  suppressing the CLS008 warning
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.errors import (
    ERROR_LARGE_CORP_REVENUE_NULL,
    ERROR_LFSE_ASSETS_NULL,
    CalculationError,
    ErrorCategory,
    ErrorSeverity,
    beel_on_non_defaulted_exposure_warning,
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

    Two warnings fire here, each surfaced as a ``CalculationError`` with
    severity WARNING:

    - **LFSE size undetermined** (Art. 153(2), BOTH regimes): when a
      counterparty is flagged ``is_financial_sector_entity=True`` but
      ``total_assets`` is null and no explicit ``apply_fi_scalar`` election
      was made, the mandatory 1.25x correlation multiplier (CRR Art.
      142(1)(4) / PS1/26 glossary) cannot be derived — the scalar is not
      applied and CLS009 flags the gap so it is never a silent
      under-statement.

    - **Large-corp F-IRB restriction conservatism** (Art. 147A(1)(d),
      Basel 3.1 only): when ``annual_revenue`` is null on any corporate
      counterparty, the engine treats the row as large-corp by default (see
      ``_is_large_corp`` in ``_apply_b31_approach_restrictions``) and
      emits CLS008.

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
        data.counterparty_lookup.counterparties.filter(lfse_undetermined_filter)
        .select(pl.len())
        .collect()
        .item()
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

    # Art. 147A(1)(d): null annual_revenue triggers the conservative
    # large-corp F-IRB restriction — emit CLS008 to flag the conservatism.
    # Corporate-only count to avoid spurious warnings for non-corporate
    # entity types where annual_revenue is genuinely irrelevant. The
    # warning is suppressed when total_assets is populated AND below the
    # SME balance-sheet threshold (CRR Art. 4(1)(128D) / Commission Rec
    # 2003/361/EC Art. 2 fallback) — in that case the counterparty is
    # definitively SME-sized and the restriction is not applied.
    balance_sheet_threshold = float(
        regulatory_threshold(resolved_pack, "sme_balance_sheet_threshold", config.eur_gbp_rate)
    )
    unresolved_filter = (
        (pl.col("entity_type").fill_null("") == "corporate")
        & pl.col("annual_revenue").is_null()
        & (pl.col("total_assets").is_null() | (pl.col("total_assets") >= balance_sheet_threshold))
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
