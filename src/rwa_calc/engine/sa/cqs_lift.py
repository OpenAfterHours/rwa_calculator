"""
Pre-ladder CQS lifts for the Standardised Approach.

Pipeline position:
    CRMProcessor -> SACalculator (engine/sa/risk_weights.py) -> OutputAggregator
    Called from ``_prepare_risk_weight_lookup`` before the CQS risk-weight table
    join, alongside the Art. 114(2A) central-bank lift (``engine/sa/central_bank.py``).

Key responsibilities:
- ``lift_institution_cqs``: source ``cqs`` from ``cp_institution_cqs`` for the two
  counterparty kinds the CRR redirects onto the institution ladder — non-named
  MDBs (Art. 117(1)) and demoted non-qualifying CCPs (Art. 107(2)(a)).

A "pre-ladder lift" writes a counterparty-carried CQS into the exposure's own
``cqs`` column so the ordinary rating tables downstream then apply unchanged. It
never fabricates a rating: a null source leaves ``cqs`` null and the row keeps its
unrated fallback.

Dtype note — ``cqs`` is declared ``Int8``. ``cp_institution_cqs`` is Int8 as well,
so this lift needs no cast; the ``cp_sovereign_cqs`` lift in ``central_bank.py``
does, because that column is Int32 and Polars would widen the ``when/then``
result until the sealed ``sa_branch`` edge contract rejects it. Any further lift
added here must check its source dtype and cast to ``pl.Int8`` when it differs.

References:
- CRR Art. 117(1); PS1/26 Art. 117(1)(a): non-named MDBs risk-weighted as institutions
- CRR Art. 107(2)(a): exposures to a non-qualifying CCP treated as institutions
- CRR Art. 120(1): the institution CQS ladder these lifts feed
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

logger = logging.getLogger(__name__)

# Uppercased exposure class and counterparty entity_type the lift keys off. Both
# are input-domain VALUES (see data/schemas.py VALID_ENTITY_TYPES), not
# regulatory scalars.
_MDB_UPPER_CLASS = "MDB"
_CCP_ENTITY_TYPE = "ccp"


@cites("CRR Art. 117(1)")
@cites("CRR Art. 107(2)")
@cites("PS1/26, paragraph 117")
def lift_institution_cqs(exposures: pl.LazyFrame, upper_class: pl.Expr) -> pl.LazyFrame:
    """Lift ``cp_institution_cqs`` into ``cqs`` for MDB / non-QCCP counterparties.

    ``upper_class`` is the caller's cached ``exposure_class`` uppercase expression,
    passed in rather than recomputed so the MDB test stays identical to the one the
    rest of the lookup preparation uses.
    """
    # CRR Art. 117(1) / PRA PS1/26 Art. 117(1)(a): non-named MDBs are treated
    # as institutions, so their primary CQS source is ``cp_institution_cqs``
    # (the MDB's own ECAI rating expressed as a CQS). When the exposure has
    # no top-level ``cqs`` (no rating attached at the rating-mapping stage)
    # but the counterparty carries an ``institution_cqs``, lift it into
    # ``cqs`` here so the downstream CQS-keyed branches and joins see it.
    # Named MDBs (mdb_named) bypass CQS entirely later — coalescing here is
    # harmless for them.
    is_mdb_class = upper_class == _MDB_UPPER_CLASS
    # CRR Art. 107(2)(a): a non-qualifying CCP counterparty (entity_type "ccp"
    # demoted past the Art. 306(1) 2%/4% pin by cp_is_qccp=False) is treated as
    # an ordinary institution. Its own ECAI rating is carried on the synthetic
    # CCR row as ``cp_institution_cqs`` (the CCR adapter surfaces no top-level
    # ``cqs``), so lift it into ``cqs`` here — mirroring the MDB treatment —
    # so the Art. 120(1) Table 3 institution ladder resolves (e.g. CQS 2 -> 50%)
    # instead of the unrated 100% fallback. Scoped to ``ccp`` entity_type with a
    # null ``cqs`` so rated institutions and lending rows are untouched.
    is_non_qccp_institution = (
        pl.col("cp_entity_type").fill_null("") == _CCP_ENTITY_TYPE
    ) & ~pl.col("cp_is_qccp").fill_null(True)
    return exposures.with_columns(
        pl.when((is_mdb_class | is_non_qccp_institution) & pl.col("cqs").is_null())
        .then(pl.col("cp_institution_cqs"))
        .otherwise(pl.col("cqs"))
        .alias("cqs")
    )
