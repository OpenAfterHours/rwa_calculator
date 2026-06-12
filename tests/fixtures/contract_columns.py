"""
Pad hand-rolled calculator-branch frames with crm_exit contract columns.

Phase 3 sealed the calculators' branch input: every REQUIRED crm_exit
column is guaranteed present in production, so the SA / IRB / slotting
namespaces read contract columns directly (no presence guards). Tests
that hand-roll minimal LazyFrames and call namespace methods or
``calculate_branch`` directly must therefore carry those columns.

``pad_crm_exit_defaults`` adds the commonly-read contract columns with
production-realistic neutral values (only when missing) WITHOUT
stripping extra non-contract columns — unlike
``tests.fixtures.resolved_bundle.seal_crm_exit``, which conforms to the
full edge shape and drops calculator-internal inputs such as
``maturity`` / ``turnover_m``.

Derived pads mirror upstream stage outputs:
- ``ead_final`` falls back to a legacy ``ead`` column when present
- ``ead_gross`` mirrors ``ead_final`` (no CRM reduction)
- ``lgd_post_crm`` mirrors ``lgd`` (no collateral adjustment)
"""

from __future__ import annotations

import polars as pl

from rwa_calc.contracts.edges import CALC_BRANCH_EDGES, seal_lenient

_SIMPLE_DEFAULTS: dict[str, pl.Expr] = {
    "seniority": pl.lit("senior"),
    "exposure_class": pl.lit(None, dtype=pl.String),
    "purchased_receivables_subtype": pl.lit(None, dtype=pl.String),
    "cp_is_financial_sector_entity": pl.lit(False),
    "is_qrre_transactor": pl.lit(False),
    "requires_fi_scalar": pl.lit(False),
    "has_one_day_maturity_floor": pl.lit(False),
    "is_defaulted": pl.lit(False),
    "beel": pl.lit(0.0),
    "is_sme": pl.lit(False),
    "is_infrastructure": pl.lit(False),
    # Null lending group preserves the counterparty fallback in the SME
    # group-key resolution; counterparty_reference is deliberately NOT
    # padded (its absence drives the SF001 warning path).
    "lending_group_reference": pl.lit(None, dtype=pl.String),
    "sme_size_metric_gbp": pl.lit(None, dtype=pl.Float64),
    "maturity_date": pl.lit(None, dtype=pl.Date),
    "effective_maturity": pl.lit(None, dtype=pl.Float64),
    "facility_termination_date": pl.lit(None, dtype=pl.Date),
    "is_revolving": pl.lit(False),
    "is_sft": pl.lit(False),
    "is_short_term_trade_lc": pl.lit(False),
    "lgd": pl.lit(None, dtype=pl.Float64),
    # Internal derived column normally produced by ``prepare_columns``; the
    # neutral null matches the no-SME derivation result (is_sme=False).
    "turnover_m": pl.lit(None, dtype=pl.Float64),
    "total_collateral_for_lgd": pl.lit(0.0),
    "crm_alloc_financial": pl.lit(0.0),
    "crm_alloc_covered_bond": pl.lit(0.0),
    "crm_alloc_receivables": pl.lit(0.0),
    "crm_alloc_real_estate": pl.lit(0.0),
    "crm_alloc_other_physical": pl.lit(0.0),
    "crm_alloc_life_insurance": pl.lit(0.0),
    "provision_allocated": pl.lit(0.0),
    "ava_amount": pl.lit(0.0),
    "other_own_funds_reductions": pl.lit(0.0),
}


def pad_crm_exit_defaults(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Add missing crm_exit contract columns with neutral defaults.

    Only columns absent from the frame are added; existing columns and
    extra non-contract columns are untouched. ``approach`` is
    deliberately NOT padded — ``classify_approach`` owns its default.
    """
    names = set(lf.collect_schema().names())

    additions = [expr.alias(name) for name, expr in _SIMPLE_DEFAULTS.items() if name not in names]
    if additions:
        lf = lf.with_columns(additions)
    names |= {name for name in _SIMPLE_DEFAULTS if name not in names}

    derived: list[pl.Expr] = []
    if "ead_final" in names:  # noqa: SIM108 — three-way source resolution
        ead_final_src = pl.col("ead_final")
    elif "ead" in names:
        # with_columns evaluates in parallel — reference the source column,
        # not the alias created in the same pass.
        ead_final_src = pl.col("ead")
        derived.append(ead_final_src.alias("ead_final"))
    else:
        ead_final_src = pl.lit(0.0)
    if "ead_gross" not in names:
        derived.append(ead_final_src.alias("ead_gross"))
    if "lgd_post_crm" not in names:
        derived.append(pl.col("lgd").alias("lgd_post_crm"))
    if derived:
        lf = lf.with_columns(derived)
    return lf


def pad_slotting_branch_defaults(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Pad a hand-rolled slotting ``calculate_branch`` frame.

    Adds ``approach="slotting"`` (the pipeline routes pre-filtered slotting
    rows, so the column is always populated in production) on top of the
    generic crm_exit defaults.
    """
    names = set(lf.collect_schema().names())
    if "approach" not in names:
        lf = lf.with_columns(pl.lit("slotting").alias("approach"))
    return pad_crm_exit_defaults(lf)


def _pad_calc_branch(frame: pl.LazyFrame | pl.DataFrame, branch: str) -> pl.LazyFrame:
    """Leniently conform a hand-rolled calculator-branch frame to its edge.

    Mirrors the orchestrator's branch-exit seal shape: missing REQUIRED
    columns become typed nulls, required-with-inject optionals get their
    defaults, CONDITIONAL (inject=False) columns are preserved only when
    supplied, undeclared scratch columns are stripped.

    ``equity_type`` is appended after the seal: it is required at the
    aggregator exit but owned by the equity path — production's combined
    frame always carries it because the equity calculator returns a
    (possibly empty) results frame with the column even when the portfolio
    holds no equity. Aggregate-calling tests that pass
    ``equity_bundle=None`` need the column to come from the branch inputs.
    """
    lf = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    sealed, _missing = seal_lenient(lf, CALC_BRANCH_EDGES[branch])
    return sealed.with_columns(pl.lit(None, dtype=pl.String).alias("equity_type"))


def pad_sa_branch(frame: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """Pad a hand-rolled SA results frame to the sa_branch edge shape."""
    return _pad_calc_branch(frame, "sa_branch")


def pad_irb_branch(frame: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """Pad a hand-rolled IRB results frame to the irb_branch edge shape."""
    return _pad_calc_branch(frame, "irb_branch")


def pad_slotting_branch(frame: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """Pad a hand-rolled slotting results frame to the slotting_branch edge shape."""
    return _pad_calc_branch(frame, "slotting_branch")
