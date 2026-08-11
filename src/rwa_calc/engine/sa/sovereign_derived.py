"""
CQS-keyed risk-weight table lookups for the Standardised Approach.

Pipeline position:
    CRMProcessor -> SACalculator (engine/sa/risk_weights.py) -> OutputAggregator
    Called from the CRR / Basel 3.1 class-override chains to price a row off a
    CQS-keyed regulatory table.

Key responsibilities:
- ``sovereign_derived_rw_expr``: price a row off ``cp_sovereign_cqs`` — the
  counterparty's home central government's credit quality step — for the three
  classes the CRR derives from their sovereign when they carry no rating of
  their own (unrated PSE, unrated non-domestic RGLA, unrated institution and,
  via Art. 117(1), unrated non-named MDB).
- ``cqs_table_lookup_expr``: the same shape parameterised on the source CQS
  column, so it can drive any CQS-keyed table off ``cqs`` or a lifted variant.
- ``crr_art_121_4_trade_finance_expr``: the Art. 121(4) trade-finance predicate
  that holds those exposures out of the Art. 121(1) Table 5 ladder.

Both lookups are **RW-valued**: they map a CQS to a risk weight directly rather
than lifting a CQS into ``cqs``. That is deliberate — ``cp_sovereign_cqs`` is
``Int32`` while ``cqs`` is ``Int8``, and a lift that forgets the cast widens the
result until the sealed ``sa_branch`` edge contract rejects it (see the dtype
note in ``engine/sa/cqs_lift.py``).

References:
- CRR Art. 115(1)(a) Table 1A: sovereign-derived RGLA risk weights
- CRR Art. 116(1) Table 2: sovereign-derived PSE risk weights
- CRR Art. 121(1) Table 5: sovereign-derived unrated-institution risk weights
- CRR Art. 121(2): unrated central government -> 100%
- CRR Art. 121(4); CRR Art. 162(3): trade-finance exposures to unrated institutions
- CRR Art. 117(1): non-named MDBs risk-weighted as institutions
- PRA PS1/26 Art. 115 / 116 (identical sovereign-derived values)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.domain.enums import CQS

if TYPE_CHECKING:
    from decimal import Decimal

logger = logging.getLogger(__name__)

# The rated span of every CQS-keyed regulatory table. UNRATED is deliberately
# absent: each caller supplies its own unrated fallback, because the article
# that defines it differs by class (Art. 121(2) for institutions, Art. 116(1)
# for PSEs, Art. 122(2) for corporates).
_RATED_CQS: tuple[CQS, ...] = (CQS.CQS1, CQS.CQS2, CQS.CQS3, CQS.CQS4, CQS.CQS5, CQS.CQS6)


def sovereign_derived_rw_expr(
    table: dict[CQS, Decimal],
    unrated_default: float,
) -> pl.Expr:
    """Build a Polars expression pricing a row off its home sovereign's CQS.

    Used for unrated PSEs (Art. 116(1) Table 2), unrated non-domestic RGLAs
    (Art. 115(1)(a) Table 1A) and unrated institutions (Art. 121(1) Table 5,
    reached directly and via the Art. 117(1) non-named-MDB redirect). All three
    tables map sovereign CQS 1-6 to a risk weight; when ``cp_sovereign_cqs`` is
    null or out of domain the conservative ``unrated_default`` applies.

    That fallback is what implements CRR Art. 121(2) on the institution path —
    "for exposures to unrated institutions incorporated in countries where the
    central government is unrated, the risk weight shall be 100%" — so callers
    must not add a null gate of their own in front of it.

    References:
        CRR Art. 115(1)(a) Table 1A / Art. 116(1) Table 2 / Art. 121(1) Table 5
        CRR Art. 121(2) — the unrated-central-government residual
        PRA PS1/26 Art. 115 / 116 (identical values)
    """
    return cqs_table_lookup_expr("cp_sovereign_cqs", table, unrated_default)


def cqs_table_lookup_expr(
    cqs_col: str,
    table: dict[CQS, Decimal],
    unrated_default: pl.Expr | float,
) -> pl.Expr:
    """Build a when/then chain mapping a CQS-bearing column to RW from a CQS table.

    Parameterised on the CQS source column so it can drive any CQS-keyed
    regulatory table (CGCB Art. 114, MDB Table 2B Art. 117(1), PSE Table 2A
    Art. 116(2), RGLA Table 1B Art. 115(1)(b), Corporate Art. 122). The caller
    controls the unrated fallback, as a constant or a Polars expression.
    """
    expr = pl.when(pl.col(cqs_col) == int(_RATED_CQS[0])).then(pl.lit(float(table[_RATED_CQS[0]])))
    for cqs_val in _RATED_CQS[1:]:
        expr = expr.when(pl.col(cqs_col) == int(cqs_val)).then(pl.lit(float(table[cqs_val])))
    if isinstance(unrated_default, pl.Expr):
        return expr.otherwise(unrated_default)
    return expr.otherwise(pl.lit(unrated_default))


@cites("CRR Art. 121")
def crr_art_121_4_trade_finance_expr() -> pl.Expr:
    """Art. 121(4) trade-finance exposures to unrated institutions.

    Art. 121(4) prescribes a flat **50%** (20% where residual maturity is three
    months or less) for trade finance under Art. 162(3) second subparagraph
    point (b), "Notwithstanding paragraphs 2 and 3".

    **Which paragraph (4) displaces is genuinely ambiguous, and this predicate
    does not resolve it.** It names (2) and (3), *not* (1). So:

    - On a PURPOSIVE reading, (4) is a floor for trade finance generally and
      the answer is 50%.
    - On a LITERAL reading, (4) never displaces (1), so Table 5 still governs
      and the answer is 20% at sovereign CQS 1.

    The two readings differ by 30pp in OPPOSITE directions. Neither rate is
    implemented and no pack entry exists for either (P1.326 / P7.8 own them),
    so this predicate holds the rows OUT of the ladder and they land on the
    Art. 121 unrated **100%** residual via the base CQS join — over-stating
    both candidates, which is the right way to be wrong while the question is
    open. Do NOT add a 50% branch on the strength of this docstring; settling
    it needs the primary text read against the PRA Rulebook rendering.

    What is NOT ambiguous is the direction of the error if these rows are let
    into the ladder: 20% against a required 50% is a 30pp UNDERSTATEMENT, and
    that is why the exclusion exists at all.

    **There is deliberately no maturity gate.** Only Art. 121(4)'s 20% limb is
    maturity-conditioned; its 50% limb applies at every maturity. The sibling
    exemption in ``_apply_sovereign_floor_for_institutions`` does carry a
    one-year condition — that is CRE20.22 footnote 13, a different rule — and
    copying its shape here re-opens 20% at sovereign CQS 1 on any trade LC
    longer than a year. That is the guard gap that dropped P1.316 on its first
    pass, so the 5-year trade-LC case is pinned explicitly by
    ``tests/unit/crr/test_p1_316_art_121_1_table_5_unrated_institution.py``.

    ``eq_missing`` keeps the predicate null-safe without adding a ``fill_null``
    site: the flag reaches the SA branch non-null today, but a negated Kleene
    null would silently drop rows from the ladder.
    """
    return pl.col("is_short_term_trade_lc").eq_missing(True)
