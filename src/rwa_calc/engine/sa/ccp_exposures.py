"""
Exposures to a central counterparty — which ones Section 9 pins (Art. 107(2)).

Pipeline position:
    CRMProcessor -> SACalculator (engine/sa/risk_weights.py,
    engine/sa/sovereign_floor.py) -> OutputAggregator

Key responsibilities:
- ``qccp_trade_exposure_expr``: the ONE predicate for "a trade exposure to a
  qualifying CCP" — the population the CCR (CRR) Part Art. 306(1) 2% / 4% pin
  covers and the Art. 121(6) sovereign floor leaves alone.
- ``qccp_trade_risk_weight_expr``: the pinned weight itself, 4% where the trade
  is client-cleared (Art. 305(3)) and 2% otherwise (Art. 306(1)(a)).

Rule text — CRR Art. 107(2) = PS1/26 Art. 107(2): "For trade exposures and for
default fund contributions to a central counterparty, institutions shall apply
the treatment set out in Section 9 ... For all other types of exposures to a
central counterparty, institutions shall treat those exposures as follows: (a) as
exposures to an institution for other types of exposures to a qualifying CCP;
(b) as exposures to a corporate for other types of exposures to a non-qualifying
CCP."

Review item CC-11 (2026-11): the pin used to key on the counterparty alone, so a
term loan to a QCCP took 2% where Art. 107(2)(a) sends it to the institution
ladder. The trade-exposure term is the engine's SA-CCR and FCCM rows (risk types
``CCR_DERIVATIVE`` / ``CCR_SFT``) — the only rows on the frame the input can mark
as trades with a CCP. Default-fund contributions are pinned separately at 12.5 on
their own-funds amount. The non-QCCP limb (b) is an exposure-CLASS question,
answered in the classifier (``engine/classify/attributes.py``).

Null-safety: every term is total without a ``fill_null`` (``eq_missing``; Kleene
``is_null() | col``), so the predicate never makes a ``when`` chain or a
``decide`` case indeterminate. An absent ``cp_is_qccp`` reads as qualifying —
the long-standing convention for a ``ccp`` entity type with no flag.

References:
- CRR Art. 107(2); PS1/26 Art. 107(2).
- CCR (CRR) Part Art. 305(3), 306(1); BCBS CRE54.14-54.15.
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

from rwa_calc.domain.enums import RiskType

logger = logging.getLogger(__name__)

# Counterparty entity_type for a central counterparty (an input-domain VALUE —
# data/schemas.py VALID_ENTITY_TYPES — not a regulatory scalar).
_CCP_ENTITY_TYPE = "ccp"


@cites("CRR Art. 107(2)")
@cites("CRR Art. 306(1)")
def qccp_trade_exposure_expr() -> pl.Expr:
    """True on an SA-CCR / FCCM trade exposure to a qualifying CCP; never null."""
    risk_type = pl.col("risk_type")
    is_trade_exposure = risk_type.eq_missing(RiskType.CCR_DERIVATIVE.value) | risk_type.eq_missing(
        RiskType.CCR_SFT.value
    )
    is_qualifying_ccp = pl.col("cp_entity_type").eq_missing(_CCP_ENTITY_TYPE) & (
        pl.col("cp_is_qccp").is_null() | pl.col("cp_is_qccp")
    )
    return is_trade_exposure & is_qualifying_ccp


def qccp_trade_risk_weight_expr(proprietary_rw: float, client_cleared_rw: float) -> pl.Expr:
    """The Art. 306(1) pin: ``client_cleared_rw`` on a client-cleared trade, else proprietary."""
    return (
        pl.when(pl.col("cp_is_ccp_client_cleared").eq_missing(True))
        .then(pl.lit(client_cleared_rw))
        .otherwise(pl.lit(proprietary_rw))
    )


__all__ = ["qccp_trade_exposure_expr", "qccp_trade_risk_weight_expr"]
