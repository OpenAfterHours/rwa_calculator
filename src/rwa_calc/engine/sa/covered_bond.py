"""
Article 129(5) unrated-covered-bond risk-weight derivation for the SA.

Pipeline position:
    CRMProcessor -> SACalculator (engine/sa/risk_weights.py) -> OutputAggregator
    Called from both risk-weight override ladders, in the covered-bond branch.

Key responsibilities:
- ``crr_unrated_cb_rw_expr``: CRR Art. 129(5), sub-paragraphs (a)-(d).
- ``b31_unrated_cb_rw_expr``: the PS1/26 arm, which additionally accepts an
  SCRA-derived issuer weight.

Both derive the covered bond's weight from the ISSUING INSTITUTION's senior
unsecured weight, in two steps: issuer CQS -> issuer RW (Art. 120 Table 3) ->
covered bond RW (the Art. 129(5) derivation table). The two regimes read
different derivation tables, which is why the CRR arm must not be reused under
B31: CRR sub-paragraph (b) maps a 50% issuer weight to 20%, where B31 maps it
to 25%.

References:
- CRR Art. 129(5); PS1/26 Art. 129(5) — unrated covered bond derivation
- CRR Art. 120 Table 3 / PS1/26 Art. 120 Table 3 (ECRA) — issuer weights
- PS1/26 Art. 120A — SCRA issuer weights, the B31-only fallback path
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

if TYPE_CHECKING:
    from polars.expr.whenthen import ChainedThen

from rwa_calc.domain.enums import CQS
from rwa_calc.engine.sa.b31_risk_weight_tables import B31_COVERED_BOND_UNRATED_FROM_SCRA

# Both derivation tables and both ECRA issuer ladders live in the CRR shim --
# it is the shared pack-binding home for the Art. 120/129 tables, and the b31
# shim carries only the SCRA-keyed map.
from rwa_calc.engine.sa.crr_risk_weight_tables import (
    COVERED_BOND_UNRATED_DERIVATION_B31,
    COVERED_BOND_UNRATED_DERIVATION_CRR,
    INSTITUTION_RISK_WEIGHTS_B31_ECRA,
    INSTITUTION_RISK_WEIGHTS_CRR,
)

logger = logging.getLogger(__name__)

_RATED_CQS: tuple[CQS, ...] = (CQS.CQS1, CQS.CQS2, CQS.CQS3, CQS.CQS4, CQS.CQS5, CQS.CQS6)


def _cqs_to_cb_rw(inst_table: dict, derivation: dict) -> dict[int, float]:
    """Chain issuer CQS -> issuer RW -> covered bond RW into a flat CQS map."""
    return {int(cqs): float(derivation[inst_table[cqs]]) for cqs in _RATED_CQS}


def _ecra_chain(cqs_to_cb_rw: dict[int, float]) -> ChainedThen:
    """Build the ``cp_institution_cqs`` when/then ladder shared by both regimes."""
    expr = pl.when(pl.col("cp_institution_cqs") == 1).then(pl.lit(cqs_to_cb_rw[1]))
    for cqs_int in (2, 3, 4, 5, 6):
        expr = expr.when(pl.col("cp_institution_cqs") == cqs_int).then(
            pl.lit(cqs_to_cb_rw[cqs_int])
        )
    return expr


@cites("CRR Art. 129")
def crr_unrated_cb_rw_expr() -> pl.Expr:
    """CRR Art. 129(5): derive an unrated covered bond's RW from the issuer's.

    When ``cp_institution_cqs`` is null (the issuing institution is itself
    unrated) the Art. 121 fallback issuer weight of 100% applies, deriving a
    covered bond weight of 50%.

    Uses the CRR-specific 4-key derivation dict: Art. 129(5) admits only
    sub-paragraphs (a)-(d), so a 50% issuer weight maps to 20%, NOT the B31
    value of 25%.
    """
    cqs_to_cb_rw = _cqs_to_cb_rw(INSTITUTION_RISK_WEIGHTS_CRR, COVERED_BOND_UNRATED_DERIVATION_CRR)
    unrated_inst_rw = INSTITUTION_RISK_WEIGHTS_CRR[CQS.UNRATED]
    unrated_cb_rw = float(COVERED_BOND_UNRATED_DERIVATION_CRR[unrated_inst_rw])
    return _ecra_chain(cqs_to_cb_rw).otherwise(pl.lit(unrated_cb_rw))


@cites("CRR Art. 129")
@cites("PS1/26, paragraph 129")
def b31_unrated_cb_rw_expr(scra_default_rw: float) -> pl.Expr:
    """PS1/26 Art. 129(5): as CRR, but the issuer weight may come from SCRA.

    Art. 129(5) operates on the resulting issuer weight regardless of its
    source, so the ECRA ladder (``cp_institution_cqs``) is tried first and an
    unrated issuer falls through to the SCRA grades (``cp_scra_grade``).

    ``scra_default_rw`` is the conservative Grade-C-equivalent residual, passed
    in from the caller's pack binding rather than re-read here.
    """
    cqs_to_cb_rw = _cqs_to_cb_rw(
        INSTITUTION_RISK_WEIGHTS_B31_ECRA, COVERED_BOND_UNRATED_DERIVATION_B31
    )
    expr = _ecra_chain(cqs_to_cb_rw)
    for grade, cb_rw in B31_COVERED_BOND_UNRATED_FROM_SCRA.items():
        expr = expr.when(pl.col("cp_scra_grade") == grade).then(pl.lit(float(cb_rw)))
    return expr.otherwise(pl.lit(scra_default_rw))
