"""
Securitisation pool aggregation helpers.

Pipeline position:
    OutputAggregator.aggregate -> apply_residual_multiplier
                              -> generate_securitisation_summary
                              -> generate_securitisation_audit

Phase 1 scope: flag and exclude securitised portions from standard credit-
risk RWA totals. The securitisation RWA framework itself (SEC-SA, SEC-IRBA
-- CRR Art. 259-264 / PS1/26 Art. 261-264) is out of scope; per-pool RWA
is reported as a placeholder ``standard_rwa * allocation_pct``.

Key responsibilities:
- ``apply_residual_multiplier``: scale every monetary column on the combined
  results frame by ``securitisation_residual_pct`` so existing aggregator
  summaries naturally reflect the on-balance-sheet residual only.
- ``generate_securitisation_summary``: explode each row's
  ``securitisation_pool_allocations`` struct list and group by
  ``pool_reference`` to produce per-pool EAD / RWA / EL totals.
- ``generate_securitisation_audit``: per-exposure reconciliation row showing
  parent EAD, residual EAD, sum of pool EAD slices, and any validation
  status from the allocator.

References:
- CRR Art. 109, Art. 244-246
- PRA PS1/26 Art. 147A(1)(j)
"""

from __future__ import annotations

import logging

import polars as pl

logger = logging.getLogger(__name__)

# Canonical list of money columns the residual multiplier applies to. Each
# column is scaled by ``securitisation_residual_pct`` so the on-balance-
# sheet view propagates to every existing summary (by class, by approach,
# pre/post CRM, output floor, EL, supporting factors).
#
# Why this list:
# - ``ead_final`` / ``rwa_final``: top-line on-balance-sheet contributions.
# - ``sa_rwa``: SA-equivalent RWA used by the output floor's S-TREA.
# - ``rwa_post_factor``: SA RWA after supporting-factor adjustment.
# - ``expected_loss`` + EL components: IRB EL summary inputs.
# - ``provision_allocated`` / ``provision_deducted``: provisions allocated to
#   this row (residual share only flows on-balance-sheet).
# - ``reporting_ead`` / ``reporting_rwa`` / ``reporting_rw``: post-CRM
#   reporting view (guarantee substitution).
MONEY_COLS: tuple[str, ...] = (
    "ead_final",
    "ead_pre_crm",
    "ead_after_collateral",
    "rwa_final",
    "sa_rwa",
    "rwa_post_factor",
    "rwa_pre_factor",
    "expected_loss",
    "el_shortfall",
    "el_excess",
    "provision_allocated",
    "provision_deducted",
    "ava_amount",
    "other_own_funds_reductions",
    "reporting_ead",
    "reporting_rwa",
)


def apply_residual_multiplier(
    lf: pl.LazyFrame,
    money_cols: tuple[str, ...] = MONEY_COLS,
) -> pl.LazyFrame:
    """Multiply every money column by ``securitisation_residual_pct``.

    The multiplier defaults to 1.0 when no allocation is attached to a
    row, so this helper is a no-op for non-securitised portfolios.
    Returns a new LazyFrame with the same schema as the input; only the
    listed money columns are rewritten.

    Args:
        lf: Per-row results frame (typically ``combined`` in the aggregator).
        money_cols: Columns to multiply. Defaults to MONEY_COLS.
    """
    schema_names = set(lf.collect_schema().names())
    if "securitisation_residual_pct" not in schema_names:
        # Hierarchy resolver attaches the column at default 1.0 even when no
        # allocations were supplied. Absence here means a caller materialised
        # the frame before that step (e.g., legacy tests) -- bail out.
        return lf

    # Multiplying by 1.0 must be a true no-op -- preserve null semantics on
    # the money columns. ``rwa_post_factor`` is null for IRB rows by design;
    # using ``fill_null(0.0)`` here would corrupt downstream invariants (e.g.,
    # the output-floor "never reduces RWA" structural test).
    multiplier = pl.col("securitisation_residual_pct").fill_null(1.0)
    exprs = [(pl.col(col) * multiplier).alias(col) for col in money_cols if col in schema_names]
    if not exprs:
        return lf
    return lf.with_columns(exprs)


def generate_securitisation_summary(lf: pl.LazyFrame) -> pl.LazyFrame | None:
    """Per-pool EAD / RWA / EL summary derived from the per-row pool allocations.

    Each row's ``securitisation_pool_allocations`` struct list is exploded,
    then ``ead_final`` / ``rwa_final`` / ``expected_loss`` are multiplied by
    the row's ``allocation_pct`` and summed by ``pool_reference``.

    Phase 1 reports the placeholder ``total_rwa`` = standard RWA * pct; the
    actual securitisation-framework RWA (SEC-SA / SEC-IRBA) is out of scope
    and lands in a future phase. Downstream consumers should treat the
    ``total_rwa`` column as a memorandum value, not regulatory capital.

    Returns ``None`` when the input frame lacks the required columns or no
    row has any pool allocation -- distinguishes "no securitisation in
    this portfolio" from an empty grouped frame.
    """
    schema_names = set(lf.collect_schema().names())
    required = {"securitisation_pool_allocations", "ead_final"}
    if not required.issubset(schema_names):
        return None

    has_rwa = "rwa_final" in schema_names
    has_el = "expected_loss" in schema_names
    has_class = "exposure_class" in schema_names

    select_cols = [
        pl.col("exposure_reference"),
        pl.col("securitisation_pool_allocations"),
        pl.col("ead_final").fill_null(0.0).alias("_parent_ead"),
    ]
    if has_rwa:
        select_cols.append(pl.col("rwa_final").fill_null(0.0).alias("_parent_rwa"))
    if has_el:
        select_cols.append(pl.col("expected_loss").fill_null(0.0).alias("_parent_el"))
    if has_class:
        select_cols.append(pl.col("exposure_class").alias("_parent_class"))

    # NB: we intentionally read the original ead_final / rwa_final here
    # rather than the residual-multiplied frame -- pool slices must use
    # the un-multiplied parent total.
    base = lf.select(select_cols).filter(
        pl.col("securitisation_pool_allocations").is_not_null()
        & (pl.col("securitisation_pool_allocations").list.len() > 0)
    )

    # Early bail when no row has any allocation -- return None so callers
    # can distinguish "no securitisation in this portfolio" from a
    # legitimately empty grouped frame.
    if base.select(pl.len()).collect().item() == 0:
        return None

    exploded = base.explode("securitisation_pool_allocations").with_columns(
        [
            pl.col("securitisation_pool_allocations")
            .struct.field("pool_reference")
            .alias("pool_reference"),
            pl.col("securitisation_pool_allocations")
            .struct.field("allocation_pct")
            .alias("allocation_pct"),
        ]
    )

    agg_exprs: list[pl.Expr] = [
        pl.len().alias("exposure_count"),
        (pl.col("_parent_ead") * pl.col("allocation_pct")).sum().alias("total_ead"),
        pl.col("allocation_pct").sum().alias("total_allocation_pct"),
    ]
    if has_rwa:
        agg_exprs.append(
            (pl.col("_parent_rwa") * pl.col("allocation_pct")).sum().alias("total_rwa_placeholder")
        )
    if has_el:
        agg_exprs.append(
            (pl.col("_parent_el") * pl.col("allocation_pct")).sum().alias("total_expected_loss")
        )

    return exploded.group_by("pool_reference").agg(agg_exprs).sort("pool_reference")


def generate_securitisation_audit(
    lf: pl.LazyFrame,
    resolved: pl.LazyFrame | None,
) -> pl.LazyFrame | None:
    """Per-exposure reconciliation: parent EAD = residual + sum(pool slices).

    Joins the allocator's resolved lookup (which carries ``audit_status``)
    onto a per-exposure aggregation of the per-row results frame. Used by
    downstream consumers to verify the carve-out arithmetic and surface
    any over-allocated / fully-securitised exposures from the allocator.

    Returns ``None`` when ``resolved`` is None (no allocations supplied)
    or the input frame lacks the required columns -- the caller chooses
    whether to omit the audit altogether in those cases.
    """
    if resolved is None:
        return None

    schema_names = set(lf.collect_schema().names())
    if "ead_final" not in schema_names or "exposure_reference" not in schema_names:
        return None

    # Per-exposure aggregation -- one row per (exposure_reference,
    # exposure_type) carrying parent EAD, residual EAD, and the sum of
    # pool slices via the same explode + multiply trick used in
    # generate_securitisation_summary. Doing this in the aggregator
    # rather than in the allocator means the audit reflects post-CRM /
    # post-CCF / post-RW EAD figures -- the parent value the user sees
    # on the standard reporting view -- not the raw input nominal.
    parent_agg = lf.group_by("exposure_reference").agg(
        [
            pl.col("ead_final").fill_null(0.0).sum().alias("parent_ead"),
            (
                pl.col("ead_final").fill_null(0.0)
                * pl.col("securitisation_residual_pct").fill_null(1.0)
            )
            .sum()
            .alias("residual_ead"),
            (
                pl.col("ead_final").fill_null(0.0)
                * (pl.lit(1.0) - pl.col("securitisation_residual_pct").fill_null(1.0))
            )
            .sum()
            .alias("securitised_ead"),
        ]
    )

    audit = resolved.select(
        [
            pl.col("exposure_reference"),
            pl.col("exposure_type"),
            pl.col("securitisation_residual_pct").alias("residual_pct"),
            pl.col("total_allocated_pct"),
            pl.col("audit_status"),
        ]
    ).join(parent_agg, on="exposure_reference", how="left")

    return audit.with_columns(
        (
            pl.col("parent_ead").fill_null(0.0)
            - pl.col("residual_ead").fill_null(0.0)
            - pl.col("securitised_ead").fill_null(0.0)
        ).alias("reconciliation_delta")
    ).sort("exposure_reference")
