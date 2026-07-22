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
    # Floored gross-exposure carriers — mirror the aggregator's clip-at-0 of
    # the raw drawn/interest/nominal/undrawn amounts (a negative on-balance
    # netting deposit must never make a gross-exposure cell go negative). When
    # the raw source is absent, inject a typed null exactly as the seal would.
    for target, source in (
        ("reporting_gross_drawn", "drawn_amount"),
        ("reporting_gross_interest", "interest"),
        ("reporting_gross_nominal", "nominal_amount"),
        ("reporting_gross_undrawn", "undrawn_amount"),
    ):
        if target in cols:
            continue
        if source in cols:
            exprs.append(pl.col(source).clip(lower_bound=0.0).alias(target))
        else:
            exprs.append(pl.lit(None, dtype=pl.Float64).alias(target))
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
    # Sealed per-side gross carriers (CRR Art. 111 on/off-BS credit-risk gross
    # scope). Independent of ``reporting_on_balance_sheet`` by design: a
    # credit-risk-in-scope exposure type gets a real on/off split even where
    # that column would null out (e.g. ``facility_undrawn``), while CCR /
    # settlement legs stay null on both sides. Mirrors the aggregator's
    # floor-at-0 convention; a null component inside a known-side sum counts
    # as 0, but a wholly unknown side stays null (never fill Float nulls to
    # 0.0 — anti-conservative).
    # "facility" is a legacy off-BS alias: production never emits it, but
    # R11-era unit fixtures do, and every discriminator (reporting_on_balance_sheet,
    # filter_off_bs, the c07_bs/c08_bs ladders) maps it off-BS — the carriers
    # must too, or the null-carrier asymmetry this fix removes is recreated.
    credit_bs_types = ("loan", "contingent", "facility_undrawn", "facility")

    def _col_or_null(name: str) -> pl.Expr:
        return pl.col(name) if name in cols else pl.lit(None, dtype=pl.Float64)

    drawn_expr = _col_or_null("drawn_amount")
    interest_expr = _col_or_null("interest")
    nominal_expr = _col_or_null("nominal_amount")
    undrawn_expr = _col_or_null("undrawn_amount")
    on_bs_sum = (
        pl.when(drawn_expr.is_null() & interest_expr.is_null())
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(
            drawn_expr.clip(lower_bound=0.0).fill_null(0.0)
            + interest_expr.clip(lower_bound=0.0).fill_null(0.0)
        )
    )
    if "reporting_gross_on_bs" not in cols:
        if "exposure_type" in cols:
            exprs.append(
                pl.when(pl.col("exposure_type").is_in(list(credit_bs_types)))
                .then(on_bs_sum)
                .otherwise(pl.lit(None, dtype=pl.Float64))
                .alias("reporting_gross_on_bs")
            )
        else:
            # Legacy synthetic frame with no exposure_type: on-side sum
            # applies unconditionally (the retired whole-bucket fallback).
            exprs.append(on_bs_sum.alias("reporting_gross_on_bs"))
    if "reporting_gross_off_bs" not in cols:
        if "exposure_type" in cols:
            exprs.append(
                pl.when(pl.col("exposure_type") == "contingent")
                .then(nominal_expr.clip(lower_bound=0.0))
                .when(pl.col("exposure_type") == "facility_undrawn")
                .then(undrawn_expr.clip(lower_bound=0.0))
                .when(pl.col("exposure_type") == "loan")
                .then(pl.lit(0.0))
                .when(pl.col("exposure_type") == "facility")
                # Legacy off-BS alias: its carrier home is ambiguous (R11-era
                # fixtures use either nominal or undrawn), so max_horizontal
                # counts an aliased pair exactly once; all-null -> null.
                .then(
                    pl.max_horizontal(
                        nominal_expr.clip(lower_bound=0.0),
                        undrawn_expr.clip(lower_bound=0.0),
                    )
                )
                .otherwise(pl.lit(None, dtype=pl.Float64))
                .alias("reporting_gross_off_bs")
            )
        else:
            # Legacy synthetic frame with no exposure_type: the off-BS gross
            # can be carried in either raw column (the retired C 08.03
            # fallback read nominal; the retired C 07/C 08.01 formula read
            # undrawn), and pipeline facility_undrawn rows alias the two.
            # max_horizontal counts an aliased pair exactly once and
            # reproduces both retired behaviours without double-counting;
            # all-null -> null (amendment, Wave 2 finding).
            exprs.append(
                pl.max_horizontal(
                    nominal_expr.clip(lower_bound=0.0),
                    undrawn_expr.clip(lower_bound=0.0),
                ).alias("reporting_gross_off_bs")
            )
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
                output_floor_summary=None,
                previous_period_results=None,
            ):
                return super().generate_from_lazyframe(
                    with_reporting_ledger(results),
                    framework=framework,
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
