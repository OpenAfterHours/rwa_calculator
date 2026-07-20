"""
Reporting-ledger builder for hand-rolled reconciliation test frames.

Pipeline position:
    test fixtures -> ReconciliationRunner (whose input contract is the sealed
    aggregator exit)

Key responsibilities:
- Mirror the aggregator's sealed reporting projection onto a hand-rolled
  our-side frame, so unit tests stay shape-identical to production without
  re-pinning every literal.

The sealed aggregator exit carries the Phase 7 canonical ledger columns
(``reporting_class``, ``reporting_class_origin``, ``reporting_approach``,
``reporting_approach_origin``). Production derives them once in the aggregator
(``_add_exposure_class_applied`` -> ``_add_post_crm_reporting_class`` /
``_approach`` -> ``_add_reporting_projection``); this builder applies the same
identities to whatever raw columns a test supplies — for an unguaranteed row
the applied and post-CRM classes ARE the origination class. Frames that set
the substitution columns explicitly keep their values.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.generator import COREPGenerator
    from rwa_calc.reporting.pillar3.generator import Pillar3Generator


def with_reporting_ledger(ours: pl.LazyFrame) -> pl.LazyFrame:
    """Add the canonical ``reporting_*`` ledger columns a test frame omits."""
    cols = set(ours.collect_schema().names())

    def first(*names: str) -> str | None:
        return next((n for n in names if n in cols), None)

    derivations = (
        (
            "reporting_class",
            ("exposure_class_post_crm", "exposure_class_applied", "exposure_class"),
        ),
        ("reporting_class_origin", ("exposure_class_applied", "exposure_class")),
        ("reporting_approach", ("approach_post_crm", "approach_applied")),
        ("reporting_approach_origin", ("approach_applied",)),
        ("reporting_ead", ("ead_final",)),
        ("reporting_rw", ("risk_weight",)),
    )
    dtypes: dict[str, pl.DataType] = {
        "reporting_class": pl.String(),
        "reporting_class_origin": pl.String(),
        "reporting_approach": pl.String(),
        "reporting_approach_origin": pl.String(),
        "reporting_ead": pl.Float64(),
        "reporting_rw": pl.Float64(),
    }
    exprs: list[pl.Expr] = []
    for target, sources in derivations:
        if target in cols:
            continue
        src = first(*sources)
        if src is not None:
            exprs.append(pl.col(src).alias(target))
        else:
            # No source on this synthetic frame: inject a typed null, exactly
            # as the lenient seal would — the sealed ledger always carries the
            # column, and a null never matches a predicate.
            exprs.append(pl.lit(None, dtype=dtypes[target]).alias(target))
    if "reporting_on_balance_sheet" not in cols:
        # Mirrors the aggregator's exposure-type rule (bs_type never reaches
        # the aggregator): loan -> on-BS, facility/contingent -> off-BS,
        # anything else -> null.
        if "exposure_type" in cols:
            exprs.append(
                pl.when(pl.col("exposure_type") == "loan")
                .then(pl.lit(value=True))
                .when(pl.col("exposure_type").is_in(["facility", "contingent"]))
                .then(pl.lit(value=False))
                .otherwise(pl.lit(None, dtype=pl.Boolean))
                .alias("reporting_on_balance_sheet")
            )
        else:
            exprs.append(pl.lit(None, dtype=pl.Boolean).alias("reporting_on_balance_sheet"))
    return ours.with_columns(exprs) if exprs else ours


class LedgerShimPillar3Generator:
    """Test shim: a Pillar3Generator whose lazyframe entry first mirrors the
    sealed reporting projection onto the hand-rolled synthetic frame — the
    production input contract is the sealed aggregator exit, and the unit
    estate must stay shape-identical to it (Phase 7 S0b re-baseline rule)."""

    def __new__(cls) -> Pillar3Generator:  # noqa: D102 - thin factory, isinstance holds
        from rwa_calc.reporting.pillar3.generator import Pillar3Generator

        class _Shim(Pillar3Generator):
            # Mirrors the parent signature exactly — tests introspect it via
            # inspect.signature to feature-gate the prior-period kwarg.
            def generate_from_lazyframe(
                self,
                results,
                *,
                framework="CRR",
                capital_ratios=None,
                output_floor_summary=None,
                previous_period_results=None,
            ):
                return super().generate_from_lazyframe(
                    with_reporting_ledger(results),
                    framework=framework,
                    capital_ratios=capital_ratios,
                    output_floor_summary=output_floor_summary,
                    previous_period_results=previous_period_results,
                )

        return _Shim()


class LedgerShimCorepGenerator:
    """Test shim: a COREPGenerator whose lazyframe entry first mirrors the
    sealed reporting projection onto the hand-rolled synthetic frame — the
    production input contract is the sealed aggregator exit (Phase 7 COREP
    ledger convergence). Fixtures pinning defaulted/substituted behaviour
    must supply ``exposure_class_applied`` (etc.) explicitly, exactly as the
    Pillar 3 estate does — the shim aliases, it does not re-derive the
    applied ladder."""

    def __new__(cls) -> COREPGenerator:  # noqa: D102 - thin factory, isinstance holds
        from rwa_calc.reporting.corep.generator import COREPGenerator

        class _Shim(COREPGenerator):
            # Mirrors the parent signature exactly. The prior-period frame is
            # sealed too: C 08.04 keys its opening RWEA on the sealed
            # reporting_class_origin / reporting_approach_origin columns, so a
            # synthetic prior frame must carry them exactly like the current one.
            def generate_from_lazyframe(
                self,
                results,
                *,
                framework="CRR",
                output_floor_summary=None,
                output_floor_config=None,
                previous_period_results=None,
            ):
                prior = (
                    with_reporting_ledger(previous_period_results)
                    if previous_period_results is not None
                    else None
                )
                return super().generate_from_lazyframe(
                    with_reporting_ledger(results),
                    framework=framework,
                    output_floor_summary=output_floor_summary,
                    output_floor_config=output_floor_config,
                    previous_period_results=prior,
                )

        return _Shim()
