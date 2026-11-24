"""
Art. 140(2) obligor-level short-term contamination weight for the Standardised Approach.

Pipeline position:
    CRMProcessor -> SACalculator (engine/sa/risk_weights.py) -> OutputAggregator
    Read by ``_apply_obligor_st_contamination_override`` in
    ``engine/sa/risk_weights.py`` (post-ladder, before the Art. 127 defaulted
    override) and by the CRR Art. 139(2) seniority test in
    ``engine/sa/issuer_rating_seniority.py`` (pre-ladder), whose "treated as
    unrated" weight must be the weight the override then assigns.

Key responsibilities:
- ``art_140_2_target_rw_expr``: the weight Art. 140(2) gives one of the
  obligor's target exposures whose weight would otherwise be ``base_rw`` — the
  single home of the two limbs' predicates and weights, so the override and the
  Art. 139(2) comparison cannot drift apart.

The rule. CRR Art. 140(2) / PRA PS1/26 Art. 140(2) (CRE21.17-18): a short-term
assessment is used only for its own item, except that "(a) if a short-term
rated facility is assigned a 150% risk weight, then all unrated unsecured
exposures to that obligor whether short-term or long-term shall also be
assigned a 150% risk weight; (b) if a short-term rated facility is assigned a
50% risk weight, no unrated short-term exposure to that obligor shall be
assigned a risk weight lower than 100%". The hierarchy stage broadcasts the
two per-obligor flags (``engine/hierarchy/enrich.py``,
``_apply_obligor_st_contamination_flags``).

References:
- CRR Art. 140(2)(a)/(b); PRA PS1/26 Art. 140(2)(a)/(b)
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

logger = logging.getLogger(__name__)


@cites("CRR Art. 140")
@cites("PS1/26, paragraph 140")
def art_140_2_target_rw_expr(base_rw: pl.Expr) -> pl.Expr:
    """Weight Art. 140(2) assigns a target exposure whose weight is otherwise ``base_rw``.

    - (a) the obligor carries a 150%-weighted short-term rated facility
      (``obligor_st_150_contamination``) and the exposure is UNSECURED
      (``~is_guaranteed`` — a guaranteed leg keeps its guarantor RW) -> 150%,
      short- or long-term. Checked first: the hard override dominates (b).
    - (b) the obligor carries a 50%-weighted short-term rated facility
      (``obligor_st_50_floor``), the exposure is unsecured and SHORT-TERM
      -> ``max(base_rw, 100%)``. The short-term window is the SA one used by
      the institution short-term branches (original maturity <= 3m, <= 6m for
      self-liquidating trade LCs). No fill_null: a null maturity yields a null
      gate the when-chain treats as "not short-term".
    - otherwise ``base_rw``.

    Which rows are targets is the caller's decision: the override passes the
    ladder's ``risk_weight`` for its own targets, and the Art. 139(2) seniority
    test passes the unrated weight of a row it may treat as unrated — such a
    row has no short-term assessment of its own and, once treated as unrated, a
    null ``cqs``, so it is a target.
    """
    is_unsecured = pl.col("is_guaranteed").not_()
    original_mty = pl.col("original_maturity_years")
    is_st = (original_mty <= 0.25) | (pl.col("is_short_term_trade_lc") & (original_mty <= 0.5))
    return (
        pl.when(pl.col("obligor_st_150_contamination") & is_unsecured)
        .then(pl.lit(1.50))
        .when(pl.col("obligor_st_50_floor") & is_unsecured & is_st)
        .then(pl.max_horizontal(base_rw, pl.lit(1.00)))
        .otherwise(base_rw)
    )
