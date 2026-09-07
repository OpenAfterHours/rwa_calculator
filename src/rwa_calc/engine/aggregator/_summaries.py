"""
Summary generation by exposure class, approach, and methodology.

Internal module — not part of the public API.

All three summaries are pure group-bys of the canonical per-leg reporting
ledger sealed on ``AGGREGATOR_EXIT_EDGE`` (Phase 7 S4): the class dimension is
``reporting_class`` (post-substitution — the guaranteed leg under the
guarantor's class, defaulted / SME-managed-as-retail under their applied
class), the approach dimension is ``reporting_approach``, and the method label
is the materialised ``reporting_method``. ``total_rwa`` sums the sealed
``rwa_final`` — already the post-floor row value when the output floor ran
(``_floor.py`` rewrites it; the pre-floor snapshot lives on ``rwa_pre_floor``)
— so every summary total ties exactly to the portfolio ``rwa_final`` total,
including CRR supporting-factor rows, which the previous
``reporting_ead x reporting_rw`` reconstruction overstated (recorded Phase 7
S4/F1 decision).
"""

from __future__ import annotations

import polars as pl

# UI methodology labels (presentation strings, not regulatory values). The
# calculation approaches collapse into the three methodology families the
# results page groups by — standardised -> STD, foundation IRB -> FIRB, advanced
# IRB -> AIRB (retail A-IRB included) — with slotting and equity surfaced under
# their own labels when present.
_METHOD_STD = "STD"
_METHOD_FIRB = "FIRB"
_METHOD_AIRB = "AIRB"
_METHOD_SLOTTING = "SLOTTING"
_METHOD_EQUITY = "EQUITY"

# The complete methodology vocabulary ``method_label_expr`` can resolve an approach
# to. Anything else falls through to its own upper-cased label, so a consumer that
# maps an EXTERNAL approach column (the reconciliation's legacy side) can test
# membership here to detect labels that will never meet ours on a join.
METHOD_LABELS: tuple[str, ...] = (
    _METHOD_STD,
    _METHOD_FIRB,
    _METHOD_AIRB,
    _METHOD_SLOTTING,
    _METHOD_EQUITY,
)


def generate_summary_by_class(
    results: pl.LazyFrame,
    columns: frozenset[str] | None = None,
) -> pl.LazyFrame:
    """
    Generate RWA summary by exposure class.

    Groups the per-leg reporting ledger on ``reporting_class``, so guaranteed
    legs are counted under the guarantor's exposure class and defaulted /
    SME-managed-as-retail rows under their applied class (CRR Art. 235 /
    Art. 112). ``total_rwa`` is the summed post-floor row RWA and ties exactly
    to the portfolio total.

    ``columns`` lets the aggregator hand over ``results``' column names it has
    already resolved for its sibling summaries; omitted, they are resolved here
    exactly as before. See :func:`generate_summary_by_approach`.
    """
    cols = _columns_of(results, columns)
    summary = results.group_by("reporting_class").agg(_class_agg_exprs(cols))
    return _with_avg_risk_weight(summary.rename({"reporting_class": "exposure_class"}))


def generate_summary_by_approach(
    results: pl.LazyFrame,
    columns: frozenset[str] | None = None,
) -> pl.LazyFrame:
    """
    Generate RWA summary by calculation approach.

    Groups the per-leg reporting ledger on ``reporting_approach``, so an
    SA-guaranteed leg is counted under the guarantor's standardised approach
    (CRR Art. 235 substitution) while IRB-guaranteed legs stay under the
    obligor's approach (Art. 161 parameter substitution).

    ``columns`` is ``results``' column names when the caller already holds
    them. The four summary builders the aggregator runs back to back all read
    the SAME post-floor ledger object, and ``collect_schema()`` is O(plan
    NODES) — so the aggregator resolves once and threads the set here. Because
    the set describes the very object being tested, and a LazyFrame is
    immutable, it cannot go stale. Omitted, it is resolved here as before.
    """
    cols = _columns_of(results, columns)
    agg_exprs: list[pl.Expr] = [
        pl.col("reporting_ead").sum().alias("total_ead"),
        pl.len().alias("exposure_count"),
        _post_floor_rwa_expr().sum().alias("total_rwa"),
    ]
    if "floor_impact_rwa" in cols:
        agg_exprs.append(pl.col("floor_impact_rwa").sum().alias("total_floor_impact"))
    if "expected_loss" in cols:
        agg_exprs.append(pl.col("expected_loss").sum().alias("total_expected_loss"))
    if "el_shortfall" in cols:
        agg_exprs.append(pl.col("el_shortfall").sum().alias("total_el_shortfall"))
    if "el_excess" in cols:
        agg_exprs.append(pl.col("el_excess").sum().alias("total_el_excess"))

    summary = results.group_by("reporting_approach").agg(agg_exprs)
    return summary.rename({"reporting_approach": "approach_applied"})


def generate_summary_by_class_method(
    results: pl.LazyFrame,
    columns: frozenset[str] | None = None,
) -> pl.LazyFrame:
    """
    Generate RWA summary by exposure class AND methodology (STD / FIRB / AIRB / …).

    The two-dimensional twin of ``generate_summary_by_class``: groups the same
    ledger rows by ``(reporting_class, reporting_method)`` so the UI can show
    RWA per methodology within each exposure class. Summing ``total_rwa`` over
    methods within a class reconciles exactly with ``generate_summary_by_class``
    (both read the same per-row post-floor RWA).

    Output columns: ``exposure_class``, ``method``, ``total_ead``, ``total_rwa``,
    ``exposure_count``, ``avg_risk_weight``.

    ``columns`` is the aggregator's already-resolved column set; see
    :func:`generate_summary_by_approach`.
    """
    cols = _columns_of(results, columns)
    summary = results.group_by(["reporting_class", "reporting_method"]).agg(_class_agg_exprs(cols))
    return _with_avg_risk_weight(
        summary.rename({"reporting_class": "exposure_class", "reporting_method": "method"})
    )


def method_label_expr(approach_col: str) -> pl.Expr:
    """Map an approach column to the UI methodology label (STD/FIRB/AIRB/…).

    The single, public source of the approach->methodology mapping. The
    aggregator materialises it as ``reporting_method`` on the sealed ledger;
    the dual-run comparison (``analysis/comparison.py``) and the
    reconciliation's LEGACY side reuse it so their class×method splits carry
    the *same* labels as the single-run ``summary_by_class_method``, rather
    than re-deriving the vocabulary. See ``_method_expr`` for the rules.
    """
    return _method_expr(approach_col)


# =============================================================================
# Private helpers
# =============================================================================


def _method_expr(approach_col: str) -> pl.Expr:
    """Map a calculation approach to a UI methodology label (STD/FIRB/AIRB/…).

    Presentation grouping for the results page: the standardised approach maps to
    STD, foundation IRB to FIRB, advanced IRB to AIRB (retail A-IRB folded in),
    with slotting and equity under their own labels. The match is
    case-insensitive and accepts both the ``ApproachType`` values
    ("standardised"/"foundation_irb"/"advanced_irb"/…) and the short aliases
    (SA/FIRB/AIRB/SLOTTING) that appear on branch frames; anything unrecognised
    falls through to its own upper-cased label rather than being dropped.
    """
    # A null approach yields null through every str op, so it falls through the
    # when-chain to the ``otherwise`` (-> "OTHER") — no leading fill is needed.
    approach = pl.col(approach_col).cast(pl.String).str.to_lowercase()
    return (
        pl.when(approach.str.starts_with("standard") | approach.is_in(["sa", "std"]))
        .then(pl.lit(_METHOD_STD))
        .when(approach.str.contains("foundation", literal=True) | (approach == "firb"))
        .then(pl.lit(_METHOD_FIRB))
        .when(approach.str.contains("advanced", literal=True) | (approach == "airb"))
        .then(pl.lit(_METHOD_AIRB))
        .when(approach.str.contains("slotting", literal=True))
        .then(pl.lit(_METHOD_SLOTTING))
        .when(approach.str.contains("equity", literal=True))
        .then(pl.lit(_METHOD_EQUITY))
        .otherwise(pl.col(approach_col).cast(pl.String).fill_null("OTHER").str.to_uppercase())
    )


def _post_floor_rwa_expr() -> pl.Expr:
    """Per-row POST-FLOOR RWA — ``rwa_final`` as sealed.

    When the output floor runs, ``apply_floor_with_impact`` rewrites each row's
    ``rwa_final`` to the post-floor value (the pre-floor snapshot moves to
    ``rwa_pre_floor``, the add-on to ``floor_impact_rwa`` —
    ``engine/aggregator/_floor.py``), so the sealed ``rwa_final`` IS the
    post-floor row RWA under every regime: the summed totals reconcile with
    ``output_floor_summary.total_rwa_post_floor`` under Basel 3.1 (PRA PS1/26
    Art. 92(2A), P1.130) and with the plain ``rwa_final`` portfolio total under
    CRR. Do NOT add ``floor_impact_rwa`` on top — that double-counts the
    add-on. A null ``rwa_final`` stays null (never filled — anti-conservative).
    """
    return pl.col("rwa_final")


def _columns_of(lf: pl.LazyFrame, columns: frozenset[str] | None) -> set[str]:
    """``lf``'s column names, resolved only when the caller supplied none.

    ``LazyFrame.collect_schema()`` walks the whole plan (O(plan NODES)), and
    the aggregator asks the same post-floor ledger object for its columns four
    times in a row. A supplied set always describes that same object, so it is
    safe by construction rather than by assumption.
    """
    return set(lf.collect_schema().names()) if columns is None else set(columns)


def _class_agg_exprs(cols: set[str]) -> list[pl.Expr]:
    """Shared aggregations for the by-class and by-class×method summaries."""
    agg_exprs: list[pl.Expr] = [
        pl.col("reporting_ead").sum().alias("total_ead"),
        pl.len().alias("exposure_count"),
        _post_floor_rwa_expr().sum().alias("total_rwa"),
        (pl.col("reporting_rw") * pl.col("reporting_ead")).sum().alias("_weighted_rw"),
    ]
    if "is_floor_binding" in cols:
        agg_exprs.append(
            pl.col("is_floor_binding").sum().cast(pl.UInt32).alias("floor_binding_count")
        )
    return agg_exprs


def _with_avg_risk_weight(summary: pl.LazyFrame) -> pl.LazyFrame:
    """Add ``avg_risk_weight`` (EAD-weighted mean of ``reporting_rw``)."""
    return summary.with_columns(
        pl.when(pl.col("total_ead") > 0)
        .then(pl.col("_weighted_rw") / pl.col("total_ead"))
        .otherwise(pl.lit(0.0))
        .alias("avg_risk_weight"),
    ).drop("_weighted_rw")
