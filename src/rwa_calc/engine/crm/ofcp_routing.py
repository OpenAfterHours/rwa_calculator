"""
Art. 200(1) other-funded-credit-protection reporting routing.

Pipeline position:
    life insurance -> third-party deposit -> route_other_funded_protection -> crm_exit

Key responsibilities:
- Decide, once per run, whether Art. 200(1) protection reports through the
  Art. 232 substitution block (C 08.01/02 col 0060) or through the A-IRB LGD
  Modelling Collateral Method block (cols 0171/0172/0173)
- Emit the three mutually-exclusive-by-construction reporting carriers that
  the aggregator seals for those cells

WHY THE DECISION IS MADE HERE. PS1/26 Annex II col 0060 (p.103) makes the two
blocks mutually exclusive per leg: "Other funded credit protection that is
treated as a guarantee in accordance with Article 232 ... shall be included.
... Other funded credit protection recognised by firms applying the AIRB
approach and using the LGD Modelling Collateral Method shall be reported in
columns 0171, 0172 and 0173." Which route applies turns on the run-level
``AIRBCollateralMethod`` election, and that election never reaches the COREP
generator — ``generate_c08_01`` and siblings take only
``(results, cols, framework, errors)``. Re-deriving it in ``reporting/`` would
put a regulatory decision in the presentation layer, so the CRM stage — which
already holds the config and the pack — decides once and emits amounts that are
exclusive by construction. The ``{c0170} = {c0171}+{c0172}+{c0173}`` identity
and the 0060/0171-0172 exclusivity then hold structurally rather than by
reporting-layer convention.

SOURCE-CARRIER DEPENDENCY (recorded, deliberately not fixed here). This module
routes whatever the two producers emit; it does not widen recognition. Today
``compute_third_party_deposit_columns`` zeroes ``third_party_deposit_value`` for
BOTH F-IRB and A-IRB (``third_party_deposit.py``: ``approach.is_in([FIRB,
AIRB])``, raising CRM017), so on an A-IRB leg ``ofcp_lgd_cash_deposit`` reports
0.0. That is truthful — the engine grants such a deposit no recognition — and it
is declared rather than silent, because CRM017 already fires.

Narrowing that gate to F-IRB only is a SEPARATE, CAPITAL-AFFECTING decision and
must not be taken as part of a reporting-basis change. Populating the carrier on
an A-IRB leg feeds ``apply_third_party_deposit_rw_mapping``, which
``engine/sa/calculator.py`` runs UNCONDITIONALLY to produce the SA-equivalent
risk weight for the Basel 3.1 output floor; the blend is benefit-only capped, so
it could only lower that floor wherever it binds. It needs its own review and
its own regression evidence against the floor.

``life_ins_collateral_value`` is not gated, so col 0172 populates on an A-IRB
leg and the published cols 0170-0173 rules stop passing vacuously.

References:
    CRR Art. 200(1): other funded credit protection (deposits, life policies,
        instruments repurchased on request)
    CRR Art. 232: Art. 200(1) protection treated as a guarantee (substitution)
    PRA PS1/26 Art. 169A: LGD Modelling Collateral Method election
    PS1/26 Annex II col 0060 / cols 0171-0173: the mutually exclusive routing
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.domain.enums import AIRBCollateralMethod
from rwa_calc.engine.crm.collateral import airb_lgd_preserved_expr
from rwa_calc.rulebook import RulepackV0

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)


@cites("CRR Art. 232")
@cites("PS1/26, paragraph 169A")
def route_other_funded_protection(
    exposures: pl.LazyFrame,
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Split the Art. 200(1) amounts between the substitution and LGD blocks.

    Reads the two amounts the earlier CRM sub-steps already produced —
    ``third_party_deposit_value`` (Art. 200(1)(a)) and
    ``life_ins_collateral_value`` (Art. 200(1)(b)) — and emits:

    ==============================  ====  ==================================
    carrier                         cell  content
    ==============================  ====  ==================================
    ``ofcp_lgd_cash_deposit``       0171  deposit, on the LGD-Modelling route
    ``ofcp_lgd_life_insurance``     0172  policy, on the LGD-Modelling route
    ``ofcp_substitution_amount``    0060  both, on the Art. 232 route
    ==============================  ====  ==================================

    One boolean selects all three branches, so for any leg a positive
    ``ofcp_lgd_*`` implies a zero ``ofcp_substitution_amount`` and vice versa —
    the exclusivity is structural, not a convention a consumer must uphold.
    Col 0173 (Art. 200(1)(c), instruments repurchased on request) has no engine
    carrier and stays 0.0 downstream.

    The two LGD carriers are capped per exposure: PS1/26 p.107 repeats "The
    value of collateral reported shall be limited to the value of the exposure
    at the level of an individual exposure" for each of 0171/0172/0173.
    ``ofcp_substitution_amount`` is NOT capped here — the whole substitution
    block (cols 0040+0050+0060) is capped jointly at the leg's gross exposure
    downstream by ``reporting/corep/crm_substitution.py::irb_block_cap_scale``,
    which sheds the over-run proportionally across the block; capping a single
    limb first would double-count the shed.

    Both source columns are producer-sealed non-null — each sub-step emits
    either a computed value or an explicit ``0.0`` default — so no null fill is
    needed or performed here.
    """
    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
    # The route exists only where the firm both CAN and DID elect LGD Modelling.
    # ``airb_lgd_collateral_method_applicable`` is a Basel-3.1-only Feature, so
    # under CRR this is False and every amount stays on the Art. 232 route —
    # today's behaviour, unchanged. Read as a Feature, never a regime bool.
    lgd_modelling_elected = (
        bool(resolved_pack.feature("airb_lgd_collateral_method_applicable"))
        and config.airb_collateral_method == AIRBCollateralMethod.LGD_MODELLING
    )

    deposit = pl.col("third_party_deposit_value")
    life_insurance = pl.col("life_ins_collateral_value")
    substitution_total = pl.sum_horizontal(deposit, life_insurance)

    if not lgd_modelling_elected:
        logger.debug("Art. 200(1) protection routed wholly to the Art. 232 substitution block")
        return exposures.with_columns(
            pl.lit(0.0).alias("ofcp_lgd_cash_deposit"),
            pl.lit(0.0).alias("ofcp_lgd_life_insurance"),
            substitution_total.alias("ofcp_substitution_amount"),
        )

    # Per-row limb test. ``airb_lgd_preserved_expr`` is the SAME expression that
    # defines the A-IRB collateral pool, so the routing and the pool can never
    # drift: it is True only for an A-IRB row whose modelled LGD actually stands,
    # which excludes an Art. 169B insufficient-data row that has fallen back to
    # the supervisory formula and therefore reports on the substitution limb.
    #
    # It inspects ``schema_names`` for exactly one column, so seal that column
    # onto the frame rather than probing the schema here: ``ensure_columns``
    # injects a typed NULL when absent, which the callee's ``.fill_null(True)``
    # resolves to the same value as its column-absent branch returns. The two
    # paths are therefore behaviourally identical, and the set below is exact.
    exposures = ensure_columns(
        exposures,
        {"has_sufficient_collateral_data": ColumnSpec(pl.Boolean, required=False)},
    )
    on_lgd_route = airb_lgd_preserved_expr(
        config, {"has_sufficient_collateral_data"}, pack=resolved_pack
    )
    exposure_cap = pl.col("ead_gross")
    logger.debug("Art. 200(1) protection routed per-leg (LGD Modelling Collateral Method elected)")
    return exposures.with_columns(
        pl.when(on_lgd_route)
        .then(pl.min_horizontal(deposit, exposure_cap))
        .otherwise(pl.lit(0.0))
        .alias("ofcp_lgd_cash_deposit"),
        pl.when(on_lgd_route)
        .then(pl.min_horizontal(life_insurance, exposure_cap))
        .otherwise(pl.lit(0.0))
        .alias("ofcp_lgd_life_insurance"),
        pl.when(on_lgd_route)
        .then(pl.lit(0.0))
        .otherwise(substitution_total)
        .alias("ofcp_substitution_amount"),
    )
