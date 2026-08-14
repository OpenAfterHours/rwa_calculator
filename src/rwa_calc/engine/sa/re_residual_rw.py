"""
CRR Art. 124(1) unsecured-counterparty risk weight for the RE residual leg.

Pipeline position:
    CRMProcessor -> SACalculator (engine/sa/risk_weights.py) -> Aggregation

Key responsibilities:
- Resolve "the risk weight applicable to the unsecured exposures of the
  counterparty involved" for the part of a real-estate exposure that exceeds
  the mortgage value, used by the CRR Art. 125 whole-loan residential blend.

The rule, verbatim (CRR Art. 124(1), first sub-paragraph, second sentence):

    "The part of the exposure that exceeds the mortgage value of the immovable
    property shall be assigned the risk weight applicable to the unsecured
    exposures of the counterparty involved."

That is an OPEN REFERRAL to the obligor's own class ladder. Art. 125 states no
weight for the excess at all — it sets only the 35% preferential weight and the
Art. 125(2)(d) 80% limit — so the 75% the blend used before is Art. 124(1)'s
referral resolved at Art. 123's regulatory-retail weight, correct for a retail
obligor and wrong for every other counterparty type.

Extracted from ``risk_weights.py`` rather than added inline: that module sits
at the ``max_engine_module_loc`` ratchet's headroom.

References:
- CRR Art. 124(1) first sub-paragraph, second sentence: the excess takes the
  counterparty's unsecured risk weight (docs/assets/crr.pdf PAGE_INDEX 121)
- CRR Art. 123: regulatory retail 75%, subject to (a) the natural-person/SME
  entity test and (c) the EUR 1m aggregate threshold
- CRR Art. 122(2) Table 6: corporate risk weight by CQS; unrated 100%
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl

from rwa_calc.domain.enums import CQS
from rwa_calc.engine.sa.crr_risk_weight_tables import CORPORATE_RISK_WEIGHTS
from rwa_calc.engine.sa.sovereign_derived import cqs_table_lookup_expr
from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

logger = logging.getLogger(__name__)

_CRR_PACK = resolve("crr", date(2026, 1, 1))

# Pack-derived scalars grouped in a dict (mirrors ``risk_weights.py``'s
# ``_SA_CRR_RW``) so the arch check does not read the individual ``float(...)``
# aliases as engine-declared regulatory scalars.
_ART_124_1_RW: dict[str, float] = {
    # Art. 123: regulatory retail, 75% flat.
    "art_123_retail": scalar_value(_CRR_PACK.scalar_param("retail_risk_weight")),
    # Art. 122(2) second subparagraph: an unrated corporate takes 100%.
    "art_122_corporate_unrated": float(CORPORATE_RISK_WEIGHTS[CQS.UNRATED]),
}


def crr_art_124_1_unsecured_cp_rw_expr() -> pl.Expr:
    """Unsecured risk weight of the counterparty, for the Art. 124(1) referral.

    Two limbs, in precedence order:

    - **Art. 123** — an obligor that is a natural person or an SME *and* meets
      the Art. 123(c) EUR 1m aggregate threshold takes the 75% regulatory-retail
      weight. Art. 123 makes no reference to a credit quality step, so a rated
      retail obligor still takes 75%.
    - **Art. 122(2) Table 6** — every other counterparty takes the corporate
      ladder by CQS, falling back to the unrated 100%.

    How this differs from its two nearest siblings, both of which are wrong to
    copy here:

    - ``risk_weights.py``'s Art. 126 **commercial** blend resolves its residual
      through ``CORPORATE_RISK_WEIGHTS`` *unconditionally*. Right for CRE, whose
      obligor is a corporate by construction; wrong for RRE, where the obligor
      is usually a natural person and Art. 123 governs. This expression adds the
      Art. 123 limb ahead of that lookup and is otherwise identical to it.
    - ``b31_risk_weight_tables.py::_b31_art_124l_cp_rw_expr`` has the right shape
      but two extra bands — an 85% "other SME" weight and a social-housing floor
      — that are PS1/26 Art. 124L constructs with **no CRR equivalent**. CRR
      prices a non-retail SME through Art. 122 like any other corporate (the
      Art. 501 SME supporting factor is a separate multiplier applied later, not
      a risk weight), and has no social-housing provision at all. Importing
      either band would invent a rule.

    ``qualifies_as_retail`` carries only the Art. 123(c) threshold limb under
    CRR (see ``stages/classify/attributes.py::_build_qualifies_as_retail_expr``)
    — it is derived for the retail *class* population and is True for any row
    under EUR 1m, including a corporate one — so the Art. 123(a) entity test is
    conjoined here explicitly. Nulls are left to Kleene logic rather than being
    filled: a null flag makes the retail limb null, the row falls through to the
    corporate ladder, and the conservative (higher) weight wins.

    Requires columns: ``qualifies_as_retail``, ``cp_is_natural_person``,
    ``is_sme``, ``cqs`` — all guaranteed present by ``SA_INPUT_CONTRACT``.

    Returns:
        Expression resolving to the counterparty's unsecured risk weight.
    """
    # Art. 123 first subparagraph: (a) natural person or SME, AND (c) aggregate
    # owed <= EUR 1m. "Exposures that do not comply with the criteria referred
    # to in points (a) to (c) ... shall not be eligible for the retail
    # exposures class" — so both limbs must hold.
    is_art_123_retail = pl.col("qualifies_as_retail") & (
        pl.col("cp_is_natural_person") | pl.col("is_sme")
    )
    return (
        pl.when(is_art_123_retail)
        .then(pl.lit(_ART_124_1_RW["art_123_retail"]))
        .otherwise(
            cqs_table_lookup_expr(
                "cqs",
                CORPORATE_RISK_WEIGHTS,
                pl.lit(_ART_124_1_RW["art_122_corporate_unrated"]),
            )
        )
    )
