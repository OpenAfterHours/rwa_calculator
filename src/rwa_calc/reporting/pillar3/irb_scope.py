"""
Shared CR6/CR10 population and balance-sheet scope for the IRB disclosure.

Pipeline position:
    sealed aggregator-exit ledger -> irb_credit_risk_population()
        -> {cr6, cr10}.execute() -> CR6 / CR10 DataFrame

CR6 (IRB by class / PD range) and CR10 (specialised-lending slotting) are the
Pillar 3 IRB CREDIT-risk disclosures (CRR Art. 452(g) / Art. 438(e)). They cover
the IRB / slotting credit-risk book EXCLUDING counterparty credit risk and
settlement risk — both are disclosed in the CCR-series templates (CCR1-CCR8,
Art. 439; EU 2021/637 Annex XXII/XXIII scope the IRB templates to credit risk)
and are NOT part of the CR6/CR10 population. This is the exact IRB mirror of
``sa_scope.sa_credit_risk_population`` (the CR4/CR5 SA decision); each template
owns its own recorded basis, and a shared risk-type constant is how one
template's scope would leak into another, so this scope stays LOCAL to the
Pillar 3 IRB templates and must NOT be reused by sa_scope, C 07.00, or C 08.x
(COREP C 08.x deliberately KEEPS the CCR legs in its EAD/RWEA population).

Two symmetric jobs, one discriminator (``exposure_type``), so that every CR6 /
CR10 row computes every column over the SAME population:

- EXCLUDE the non-credit-risk synthetic legs entirely (all columns — PD/category
  bands, totals, RWEA): SA-CCR derivative netting sets and FCCM SFT rows (both
  ``ccr_netting_set``), CCP default-fund contributions (``ccr_default_fund``,
  Art. 307-309) and settlement failed trades (``ccr_failed_trade``,
  Art. 378-380). A CCR leg mis-tagged with an IRB / slotting origin approach
  would otherwise leak into the class-total / RWEA columns while being absent
  from the on/off-balance-sheet split columns, so the template would not
  internally reconcile — the same defect ``sa_scope`` closes for CR4/CR5.

- CLASSIFY the genuine credit-risk commitment leg the sealed discriminator
  leaves null: the synthetic ``facility_undrawn`` undrawn-headroom row is an
  off-balance-sheet commitment (CRR Art. 111 / PS1/26 Art. 111 Table A1), so
  CR6's average-CCF column (weighted over the off-balance-sheet legs) counts it.
  The sealed ``reporting_on_balance_sheet`` contract keeps it null ("belongs to
  neither side; must NOT be filled to a side") because that column is read by
  templates that make their own scope decisions; CR6/CR10 patch it locally to
  off-balance-sheet so it lands on exactly one side here.

References:
- CRR Art. 452(g) (IRB by class/PD-range disclosure); Art. 438(e) (slotting);
  Art. 439 (CCR1-CCR8 CCR disclosures); Art. 378-380 (settlement risk);
  Art. 307-309 (CCP default-fund contributions); Art. 111 (off-balance-sheet
  CCF items)
- EU 2021/637 Annex XXII (CR6) / Annex XXIII (CR10) — credit-risk scope
- docs/plans/phase7-declarative-reporting.md §6 (decision F3)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Set as AbstractSet

# exposure_type values whose EAD/RWA is a counterparty-credit-risk or
# settlement requirement, not a Part Three, Title II, Chapter 3 IRB credit-risk
# one, so they leave the CR6/CR10 population entirely (disclosed instead in
# CCR1-CCR8 / the settlement-risk line). Kept LOCAL to the Pillar 3 IRB
# templates — see the module docstring: reusing this in COREP C 08.x would
# wrongly strip the CCR rows Annex II requires there.
_EXCLUDED_EXPOSURE_TYPES: tuple[str, ...] = (
    "ccr_netting_set",  # SA-CCR derivatives (CCR_DERIVATIVE) + FCCM SFTs (CCR_SFT)
    "ccr_default_fund",  # CCP default-fund contributions (Art. 307-309)
    "ccr_failed_trade",  # settlement failed trades (Art. 378-380)
)


def irb_credit_risk_population(data: pl.DataFrame, cols: AbstractSet[str]) -> pl.DataFrame:
    """Narrow an IRB / slotting frame to the CR6/CR10 IRB credit-risk population.

    Drops the non-credit-risk synthetic legs (CCR + settlement) and reclassifies
    the ``facility_undrawn`` commitment leg to off-balance-sheet, so CR6 and CR10
    compute every column over the SAME population.

    Presence-tolerant: with no ``exposure_type`` carrier (a synthetic unit frame
    that omits it) the frame is returned unchanged — the sealed ledger always
    carries it. A null ``exposure_type`` is never excluded (only an explicit
    match against the non-credit-risk set removes a row). Operates on an eager
    DataFrame (both callers ``.collect()`` before narrowing).
    """
    if "exposure_type" not in cols:
        return data
    exposure_type = pl.col("exposure_type")
    is_excluded = exposure_type.is_in(_EXCLUDED_EXPOSURE_TYPES).fill_null(value=False)
    data = data.filter(~is_excluded)
    if "reporting_on_balance_sheet" not in cols:
        return data
    return data.with_columns(
        pl.when(exposure_type == "facility_undrawn")
        .then(pl.lit(value=False))
        .otherwise(pl.col("reporting_on_balance_sheet"))
        .alias("reporting_on_balance_sheet")
    )
