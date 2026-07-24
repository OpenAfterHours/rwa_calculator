"""
Article 114 central-bank treatments for the Standardised Approach.

Pipeline position:
    CRMProcessor -> SACalculator (engine/sa/risk_weights.py) -> OutputAggregator
    Called from ``_prepare_risk_weight_lookup`` (the CQS lift) and from both
    risk-weight override ladders (the ECB predicate).

Key responsibilities:
- ``is_ecb_expr``: identify the ECB for the Art. 114(3) unconditional 0% RW.
- ``lift_central_bank_cqs``: PS1/26 Art. 114(2A) read-across
  from a central bank's government's ECAI assessment.

Three provisions of Article 114 assign a central bank 0%, and they are routinely
confused. Only the first is unconditional:

- **Art. 114(3)** — "Exposures to the [European] Central Bank shall be assigned a
  0 % risk weight." No currency test, no rating test. Present and identically
  worded in CRR and PS1/26, so it is NOT regime-gated.
- **Art. 114(4)** — the UK central government and the Bank of England
  *denominated and funded in sterling*. Currency-conditional; lives in
  ``risk_weights.py`` as the ``is_domestic_currency`` branch.
- **Art. 114(7)** — the third-country equivalent of (4). Currency-conditional.
  (PS1/26 marks 114(7) "Provision not in PRA Rulebook".)

References:
- CRR Art. 114(2)/(3)/(4)/(7); PS1/26 Art. 114(2)/(2A)/(3)/(4)
- CRR Art. 136: ECAI credit-assessment to credit-quality-step mapping
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.engine.sa.crr_risk_weight_tables import ECB_ZERO_RW

if TYPE_CHECKING:
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

# The documented data convention for the ECB (see data/schemas.py
# VALID_ENTITY_TYPES). A distinct entity_type VALUE, not a new column — the
# ``mdb_named`` precedent for Art. 117(2) named MDBs. The ECB is supranational,
# so ``country_code`` cannot identify it and a member state's code would wrongly
# pull it into the Art. 114(7) EU-domestic-currency branch.
_ECB_ENTITY_TYPE = "central_bank_ecb"
_CENTRAL_BANK_ENTITY_TYPE = "central_bank"


@cites("CRR Art. 114(3)")
@cites("PS1/26, paragraph 114")
def ecb_rw_expr() -> pl.Expr:
    """Art. 114(3): the ECB 0% risk weight, read from the common pack.

    Exposed as an expression builder rather than a module-scope constant so the
    regulatory value stays in the rulepack (arch_check check 5) — the pack-binding
    shim ``crr_risk_weight_tables`` is its only engine-side home.
    """
    return pl.lit(float(ECB_ZERO_RW))


@cites("CRR Art. 114(3)")
@cites("PS1/26, paragraph 114")
def is_ecb_expr() -> pl.Expr:
    """Art. 114(3): identify exposures to the ECB (0% RW, unconditionally).

    ``eq_missing`` returns False rather than null for a null ``cp_entity_type``,
    so no ``fill_null`` is needed and a missing entity type can never be read as
    the ECB.
    """
    return pl.col("cp_entity_type").eq_missing(_ECB_ENTITY_TYPE)


@cites("PS1/26, paragraph 114")
def lift_central_bank_cqs(exposures: pl.LazyFrame, pack: ResolvedRulepack) -> pl.LazyFrame:
    """PS1/26 Art. 114(2A): an unrated central bank takes its government's CQS.

    "Exposures to a central bank for which a credit assessment by a nominated
    ECAI is not available shall be treated in accordance with paragraph 2 if a
    credit assessment by a nominated ECAI is available for the central government
    of the jurisdiction of the central bank. In this case, the central
    government's credit assessment shall be used to determine the risk weight for
    exposures to the central bank."

    Implemented as a lift of ``cp_sovereign_cqs`` into ``cqs``, mirroring the
    MDB / non-QCCP ``cp_institution_cqs`` lift in ``risk_weights.py``, so the
    ordinary Art. 114(2) Table 1 ladder then applies unchanged.

    Scope is narrow on three axes:

    - ``central_bank`` exactly — not ``sovereign`` (a central government's own
      assessment already IS the Table 1 input, so there is nothing to
      substitute) and not ``central_bank_ecb`` (Art. 114(3) gives the ECB 0%
      ahead of any CQS ladder).
    - ``cqs`` null only — the central bank's own assessment wins where it
      exists; Art. 114(2A) fires only where one "is not available".
    - CRR has no paragraph 2A (Art. 114 runs 1, 2, 3, 4, 7), so the lift is
      gated on the cited ``central_bank_uses_sovereign_cqs`` pack Feature.

    A null ``cp_sovereign_cqs`` fabricates nothing: ``cqs`` stays null and the row
    keeps the Art. 114(1) unrated 100% fallback.

    ``cp_sovereign_cqs`` is declared ``Int32`` while ``cqs`` is ``Int8`` (its
    sibling ``cp_institution_cqs`` is already Int8, which is why the MDB lift
    needs no cast). The explicit cast keeps ``cqs`` Int8 — without it Polars
    widens the ``when/then/otherwise`` result and the ``sa_branch`` edge contract
    fails on every Basel 3.1 run. A credit quality step is 1-6, so Int8 is lossless.
    """
    if not pack.feature("central_bank_uses_sovereign_cqs"):
        return exposures
    is_unrated_central_bank = (
        pl.col("cp_entity_type").eq_missing(_CENTRAL_BANK_ENTITY_TYPE) & pl.col("cqs").is_null()
    )
    return exposures.with_columns(
        pl.when(is_unrated_central_bank)
        .then(pl.col("cp_sovereign_cqs").cast(pl.Int8))
        .otherwise(pl.col("cqs"))
        .alias("cqs")
    )
