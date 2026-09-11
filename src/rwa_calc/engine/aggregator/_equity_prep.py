"""
Equity result preparation.

Internal module — not part of the public API.
"""

from __future__ import annotations

import polars as pl

from rwa_calc.domain.enums import ApproachType, ExposureClass


def prepare_equity_results(
    equity_results: pl.LazyFrame,
    *,
    include_sa_equivalent: bool = False,
) -> pl.LazyFrame:
    """Add equity approach tag, ensure exposure_class exists, and normalize RWA.

    Equity rows enter the results frame via this path (concatenated at the
    aggregator), NOT through hierarchy/unify, so the reconciliation base
    ``source_exposure_reference`` must be populated here too — equity is
    base-grain, so it equals ``exposure_reference``. Without this, equity rows
    would carry an injected null base and any base-grain reconciliation key
    would collapse every equity exposure into one null-keyed group.

    When ``include_sa_equivalent`` is set the equity leg's standardised-equivalent
    RWA (``sa_rwa``) is populated as its own pre-floor RWA. Under Basel 3.1 the IRB
    equity treatment is removed (Art. 147A / CRE20.58-62), so equity is
    standardised-only and its standardised-equivalent RWA IS the RWA the equity
    calculator already produced. The SA calculator never runs on equity legs, so
    without this ``sa_rwa`` stays null and the disclosed S-TREA (OF 02.01 col 0040,
    C 02.00 col 0020, CMS1/CMS2 col d) would silently drop equity. The flag mirrors
    the SA calculator's own ``output_floor``-Feature gate on ``sa_rwa`` so no
    ``sa_rwa`` column is minted on CRR frames that never carry one. Equity is not
    floor-eligible, so this leaves the output-floor base and ``rwa_final`` unchanged.

    ``exposure_type`` / ``drawn_amount`` place the holding on the balance sheet so
    the SA reporting templates can report the Art. 112(1)(p) class at all. Equity
    reaches the sealed exit without passing an SA/IRB/slotting branch, so every
    input-side carrier the reporting projection reads is an injected null on these
    rows, and C 07.00 / OF 07.00 would publish a 0.00 gross waterfall against a
    real exposure value and RWEA. See :func:`rwa_calc.engine.aggregator.aggregator.
    _add_reporting_projection` for the three ladders that consume them.
    """
    cols = set(equity_results.collect_schema().names())
    rwa_col = "rwa" if "rwa" in cols else "rwa_final"

    result = equity_results
    if "exposure_class" not in cols:
        # Art. 112(1)(o) CIU vs (p) equity. The two letters are DISJOINT in both
        # regimes and are told apart by the article that supplies the risk
        # weight — Arts. 132-132C for (o), Art. 133 for (p) — so this keys
        # exactly what the risk weight keyed: ``equity_type == "ciu"``, the same
        # discriminator as ``engine/equity/calculator.py::_append_ciu_branches``.
        # Regime-BLIND with no Feature to read: PS1/26 Art. 112(2) Table A2 ranks
        # (o) at row (2) above (p) at row (3), and the COREP Annex II decision
        # tree answers its point-(p) gate ("see also Article 133 CRR") NO for a
        # CIU and routes it to the rank-5 (l)+(o) gate, which states those
        # classes are "disjoint among themselves". It is not a pack CategoryMap
        # entry because ``entity_type`` cannot express a CIU — a wrapper's
        # counterparty is an ordinary corporate or equity entity.
        #
        # Two steps, (p) first and the (o) override second, so the override is a
        # no-op rather than a raise on a frame carrying no ``equity_type`` at all
        # (the regex selector expands to nothing): the fallback direction is the
        # pre-existing "every equity-file leg is class (p)" behaviour, never an
        # unstamped class that would drop the leg out of the C 02.00 breakdown.
        result = result.with_columns(
            [pl.lit(ExposureClass.EQUITY.value).alias("exposure_class")]
        ).with_columns(
            pl.when(pl.col("^equity_type$").str.to_lowercase() == "ciu")
            .then(pl.lit(ExposureClass.CIU.value))
            .otherwise(pl.col("exposure_class"))
            .alias("exposure_class")
        )

    prepared = [
        pl.lit(ApproachType.EQUITY.value).alias("approach_applied"),
        pl.col(rwa_col).alias("rwa_final"),
        # Equity is base-grain, so its reconciliation base equals its own
        # reference (set unconditionally — no presence guard).
        pl.col("exposure_reference").alias("source_exposure_reference"),
        # Facility-share carriers. An equity holding is never a candidate: the
        # fan-out only replicates synthetic facility_undrawn rows. They are
        # emitted HERE because equity is the one path that reaches the sealed
        # aggregator exit without passing an SA/IRB/slotting branch seal — it is
        # concatenated straight onto the combined frame (aggregator.py) — so
        # nothing upstream resolves these two columns for an equity row and the
        # diagonal concat would otherwise inject a null. Resolving them at the
        # producer rather than filling them at the exit is deliberate: a fill on
        # AGGREGATOR_EXIT_EDGE adds a with_columns node on top of the already
        # materialised frame, which tests/unit/test_aggregator_eager_views.py
        # counts and rejects.
        pl.lit(None).cast(pl.String).alias("facility_share_group"),
        pl.lit(False).alias("is_facility_share_candidate"),
        # Balance-sheet placement. ``equity`` is a synthetic-producer
        # ``exposure_type`` in the same sense as ``ccr_netting_set`` /
        # ``ccr_default_fund`` / ``ccr_failed_trade`` — a value no input file
        # carries, minted by the one stage that knows what the row is. It is NOT
        # spelled ``loan``: the reconciliation exposes ``exposure_type`` as a
        # ledger carrier, so a borrowed label would assert a loan that does not
        # exist. The three on/off-balance-sheet ladders in
        # ``_add_reporting_projection`` (and C 07.00 / C 09.01's ``_bs``
        # discriminators) each admit it explicitly; a new value they did not learn
        # would silently report on neither side, which is the defect this fixes.
        pl.lit("equity").alias("exposure_type"),
        # The on-balance-sheet gross. An equity holding is wholly drawn: CRR
        # Art. 133(3) / PS1/26 Art. 133 make its exposure value "the accounting
        # value remaining after specific credit risk adjustments", there is no
        # commitment to convert and no conversion factor, so gross == exposure
        # value == ``ead_final`` and the off-balance-sheet side is a true 0.0 (the
        # ladder derives that, it is not filled here). ``interest`` /
        # ``nominal_amount`` / ``undrawn_amount`` are deliberately LEFT NULL —
        # an equity instrument accrues no interest and has no nominal or undrawn
        # limb, and filling a Float null to 0.0 is the estate's standing ban.
        # Art. 155(2) short-position netting can move ``ead_final`` below the
        # gross holding, but it runs on the IRB-simple path only, and C 07.00
        # excludes IRB-method equity (COREP Annex II ¶50), so no admitted leg
        # reports a netted figure as its gross.
        pl.col("ead_final").alias("drawn_amount"),
        # Pre-supporting-factor RWEA. This is an ALIAS, not a shortcut: CRR
        # Art. 501 (SME) and Art. 501a (infrastructure) apply to credit exposures
        # computed under Chapters 2 and 3 of Title II Part Three, and an equity
        # holding or CIU wrapper is outside both factors' scope entirely — there
        # is no SME turnover test and no qualifying-infrastructure test to pass,
        # so no factor can ever be applied and the pre-factor RWEA IS the RWEA.
        # The Art. 501/501a adjustment columns are therefore a true 0.0, not a
        # missing figure.
        #
        # Resolved HERE for the same reason as the three carriers above:
        # ``rwa_pre_factor`` is written by ``engine/sa/calculator.py`` for the SA
        # branch and ``engine/irb/calculator.py`` for IRB, and an equity-file leg
        # passes NEITHER, so the reporting projection read an injected null and
        # published 0.00 against a real RWEA — breaking ``0215 + 0216 + 0217 =
        # 0220`` (C 07.00, v0329_m / v09747_m), ``0080 + 0081 + 0082 = 0090``
        # (C 09.01, v0407_m) and the 35%-band ERROR rule v0321_m, and reconciling
        # v5803_q at 0 = 0 against a real figure. CRR-only: the Art. 501/501a
        # columns do not exist on OF 07.00 / OF 09.01, and no Basel 3.1 cell
        # reads this carrier.
        pl.col(rwa_col).alias("rwa_pre_factor"),
    ]
    if include_sa_equivalent:
        prepared.append(pl.col(rwa_col).alias("sa_rwa"))

    return result.with_columns(prepared)
