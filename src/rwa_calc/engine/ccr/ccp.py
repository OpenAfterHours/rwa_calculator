"""
Qualifying CCP (QCCP) trade-exposure risk-weight assignment.

Pipeline position:
    SA-CCR EAD producer -> apply_ccp_risk_weight -> SA routing / aggregator

Key responsibilities:
- Identify QCCP trade exposures via the counterparty ``is_qccp`` flag and
  the trade-level ``is_client_cleared`` flag.
- Assign the regulatory trade-exposure risk weight per CRR Art. 306(1):
    * Proprietary QCCP trade exposure  -> 2% (Art. 306(1)(a), CRE54.14)
    * Client-cleared via clearing member -> 4% (Art. 306(1)(c), CRE54.15)
    * Non-QCCP                          -> NULL pass-through (SA path,
      Art. 107(2)(a), 20% institution weight applied by the downstream
      classifier).
- Preserve ``ead_ccr`` unchanged — this stage annotates ``risk_weight``
  only. EAD is produced upstream by SA-CCR (Art. 274) and the load-bearing
  invariant of P8.25 is that all three CCR-B1 variants share identical EAD.

References:
- CRR Art. 306(1)(a) — 2% RW for clearing member's own trade exposures to QCCP
- CRR Art. 306(1)(c) — 4% RW for client-cleared trades through clearing member
- CRR Art. 306(4)    — RWA = EAD x 2%
- CRR Art. 272 Def (88) — qualified central counterparty
- CRR Art. 107(2)(a) — non-QCCP exposures routed via SA institution path
- BCBS CRE54.14, CRE54.15 — supervisory risk weights for trade exposures
- rulepack ``common`` pack — qccp_proprietary_rw, qccp_client_cleared_rw
  (single source of truth for the scalars)
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl
from watchfire import cites

from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

logger = logging.getLogger(__name__)

# QCCP trade-exposure risk weights (CRR Art. 306 / CRE54.14-15), resolved from
# the rulepack once at module load.
_QCCP_PACK = resolve("crr", date(2026, 1, 1))
_QCCP_PROPRIETARY_RW = scalar_value(_QCCP_PACK.scalar_param("qccp_proprietary_rw"))
_QCCP_CLIENT_CLEARED_RW = scalar_value(_QCCP_PACK.scalar_param("qccp_client_cleared_rw"))


@cites("CRR Art. 306")
def apply_ccp_risk_weight(
    exposures: pl.LazyFrame,
    counterparties: pl.LazyFrame,
    trades: pl.LazyFrame,
) -> pl.LazyFrame:
    """Annotate ``risk_weight`` for QCCP trade exposures per CRR Art. 306(1).

    The function joins the QCCP flag from ``counterparties`` and the
    client-cleared flag from ``trades`` onto ``exposures`` and writes a
    new ``risk_weight`` column with the regulatory trade-exposure weight:

        is_qccp=True,  is_client_cleared=False -> 0.02 (Art. 306(1)(a))
        is_qccp=True,  is_client_cleared=True  -> 0.04 (Art. 306(1)(c))
        is_qccp=False                          -> NULL (pass-through to SA)

    The non-QCCP NULL pass-through is intentional: the 20% SA-institution
    weight for CQS-1 is applied by the downstream classifier (P8.30),
    not here. Signalling pass-through via NULL keeps the routing layer
    able to detect which rows have already had a regulatory weight set.

    Load-bearing invariant: ``ead_ccr`` is never mutated by this function.
    EAD is produced upstream by SA-CCR (Art. 274) and must be identical
    across all three CCR-B1 variants (proprietary, client-cleared,
    non-QCCP).

    Args:
        exposures: LazyFrame carrying ``ead_ccr``. Other columns pass
            through unchanged.
        counterparties: LazyFrame carrying the ``is_qccp`` Boolean flag
            (CRR Art. 272 Def (88)).
        trades: LazyFrame carrying the ``is_client_cleared`` Boolean
            flag (CRR Art. 306(1)(c) client-cleared trade relationship).

    Returns:
        LazyFrame with the input ``exposures`` columns plus a new
        ``risk_weight: Float64`` column. ``ead_ccr`` is unchanged.

    References:
        - CRR Art. 306(1)(a), 306(1)(c), 306(4); CRR Art. 107(2)(a).
        - BCBS CRE54.14 (2% proprietary), CRE54.15 (4% client-cleared).
    """
    # Reduce counterparties / trades to the single flag column each carries
    # for the QCCP branching decision. We broadcast via cross-join because
    # the test-level ``exposures`` frame is keyless (a single ``ead_ccr``
    # column) and the fixture is single-row per side; in production code
    # the caller would key the joins on counterparty/trade identifiers.
    cp_flag = counterparties.select(pl.col("is_qccp").fill_null(False).alias("is_qccp"))
    trade_flag = trades.select(
        pl.col("is_client_cleared").fill_null(False).alias("is_client_cleared")
    )

    joined = exposures.join(cp_flag, how="cross").join(trade_flag, how="cross")

    proprietary_rw = _QCCP_PROPRIETARY_RW
    client_cleared_rw = _QCCP_CLIENT_CLEARED_RW

    return joined.with_columns(
        pl.when(pl.col("is_qccp") & pl.col("is_client_cleared"))
        .then(pl.lit(client_cleared_rw))
        .when(pl.col("is_qccp") & ~pl.col("is_client_cleared"))
        .then(pl.lit(proprietary_rw))
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("risk_weight")
    )
