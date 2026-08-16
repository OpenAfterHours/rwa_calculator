"""
Article 115 regional-government / local-authority treatments for the SA.

Pipeline position:
    CRMProcessor -> SACalculator (engine/sa/risk_weights.py) -> OutputAggregator
    Called from both risk-weight override ladders, in the sovereign-like section
    ahead of the Art. 115(5) sterling branch.

Key responsibilities:
- ``is_rgla_sovereign_expr``: select the RGLAs that are treated as their central
  government rather than as ordinary regional governments.
- ``rgla_sovereign_rw_expr``: price those rows on the Art. 114 CGCB ladder.

Art. 115 splits RGLAs three ways, and the repo models the split with the
``rgla_sovereign`` / ``rgla_institution`` ``entity_type`` values (see
``data/schemas.py``), NOT with ``is_equivalent_jurisdiction`` — that column
carries the separate prudential-supervision equivalence determination:

- **Art. 115(2)** — the Scottish Government, the Welsh Government and the
  Northern Ireland Executive "shall be treated as exposures to the central
  government of the UK and assigned a risk weight **in accordance with
  Article 114**". Not a flat 0%: Art. 114 gives 0% only via the sterling
  limb, or via Table 1 at CQS1.
- **Art. 115(4)** — the wider "treated as exposures to the central government"
  equivalence list. PS1/26 marks it "[Note: Provision not in PRA Rulebook]", so
  it SURVIVES in CRR and is relied on under Basel 3.1 too. (Contrast the
  "[Note: Provision left blank]" form, which means deleted — conflating the two
  refuted a sibling audit finding.)
- **Art. 115(1)** — everything else: the RGLA Table 1A / 1B ladders, which stay
  in ``risk_weights.py`` and are deliberately untouched here.

Before P1.282 the ``rgla_sovereign`` rows were pinned to 0% whenever
``cp_country_code == "GB"``, unconditionally on currency and on the UK's own
credit assessment, and a non-GB ``rgla_sovereign`` was not recognised at all —
it fell through to the ordinary Art. 115(1)(a) Table 1A ladder. Those are errors
in OPPOSITE directions: the GB pin understates once the UK is downgraded below
CQS1 on a non-sterling exposure, while the non-GB omission overstates (Table 1A
charges 20% at CQS1 where Art. 114 Table 1 charges 0%).

Deliberately NOT implemented here: the Art. 114(7) EU-domestic-currency 0%
relief for a non-GB ``rgla_sovereign``. Extending that limb to this population
would grant full relief off an ``entity_type`` string; it is recorded as a
follow-up rather than folded in silently.

References:
- CRR Art. 115(2)/(4); PS1/26 Art. 115(2), Art. 115(4) ("not in PRA Rulebook")
- CRR / PS1/26 Art. 114(1)-(2) — the CGCB ladder these rows are priced on
- PS1/26 Art. 115(5) — the UK-sterling flat 20%, which stays downstream
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

from rwa_calc.domain.enums import CQS
from rwa_calc.engine.sa.crr_risk_weight_tables import (
    CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
    RGLA_UK_DEVOLVED_RW,
)

logger = logging.getLogger(__name__)

# Input-domain entity_type value (data/schemas.py VALID_ENTITY_TYPES), not a
# regulatory scalar — the repo's marker for an Art. 115(2)/(4) RGLA that is
# treated as its central government.
_RGLA_SOVEREIGN_ENTITY_TYPE = "rgla_sovereign"

_CQS_LADDER: tuple[CQS, ...] = (CQS.CQS1, CQS.CQS2, CQS.CQS3, CQS.CQS4, CQS.CQS5, CQS.CQS6)


@cites("CRR Art. 115")
@cites("PS1/26, paragraph 115")
def is_rgla_sovereign_expr(upper_class: pl.Expr) -> pl.Expr:
    """Select RGLA rows that Art. 115(2)/(4) price as a central government.

    Scoped so the branch never captures a row it cannot price better than the
    existing chain: a GB row (which previously took the flat 0% and must keep a
    defined answer) or any row carrying a usable sovereign CQS. A non-GB
    ``rgla_sovereign`` with no sovereign assessment is left to fall through to
    the ordinary Art. 115(1) ladder exactly as before, so this change cannot
    silently re-price rows it has no better basis for.

    ``eq_missing`` returns False rather than null for a null ``cp_entity_type``,
    so a missing entity type can never be read as sovereign-equivalent.
    """
    is_sovereign_rgla = (upper_class == "RGLA") & pl.col("cp_entity_type").eq_missing(
        _RGLA_SOVEREIGN_ENTITY_TYPE
    )
    has_sovereign_cqs = pl.col("cp_sovereign_cqs").is_not_null() & (pl.col("cp_sovereign_cqs") > 0)
    return is_sovereign_rgla & ((pl.col("cp_country_code") == "GB") | has_sovereign_cqs)


@cites("CRR Art. 115")
@cites("CRR Art. 114")
@cites("PS1/26, paragraph 115")
def rgla_sovereign_rw_expr(is_uk_domestic_funded: pl.Expr) -> pl.Expr:
    """Price an Art. 115(2)/(4) RGLA on the Art. 114 central-government ladder.

    Order matters and mirrors Art. 114 itself:

    1. ``is_uk_domestic_funded`` (GB counterparty, sterling-denominated AND
       sterling-funded) keeps 0% — that is Art. 114(4) reached through
       Art. 115(2), and it is why the GB/sterling base case is untouched by
       P1.282. The funding limb is P1.314: Art. 114(4) reads "denominated
       **and funded** in sterling", so a sterling-denominated but
       foreign-funded devolved exposure drops to the ladder below.
    2. Otherwise the Art. 114(2) Table 1 ladder on the counterparty's sovereign
       CQS. This is the limb the old code was missing: a non-sterling devolved
       exposure follows the UK's own assessment, so it stops being 0% the moment
       the UK leaves CQS1.
    3. The residual is the devolved 0%, reachable only for a GB row with no
       usable sovereign CQS (``is_rgla_sovereign_expr`` excludes every other
       row from this branch), so behaviour there is unchanged.

    No cast is needed on ``cp_sovereign_cqs`` here: it is compared against
    integer literals and never written into the Int8 ``cqs`` column, unlike the
    Art. 114(2A) lift in ``central_bank.py``.
    """
    devolved_rw = pl.lit(float(RGLA_UK_DEVOLVED_RW))
    ladder = pl.when(pl.col("cp_sovereign_cqs") == int(_CQS_LADDER[0])).then(
        pl.lit(float(CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[_CQS_LADDER[0]]))
    )
    for cqs_val in _CQS_LADDER[1:]:
        ladder = ladder.when(pl.col("cp_sovereign_cqs") == int(cqs_val)).then(
            pl.lit(float(CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[cqs_val]))
        )
    return pl.when(is_uk_domestic_funded).then(devolved_rw).otherwise(ladder.otherwise(devolved_rw))
