"""
Shared CR4/CR5 population and balance-sheet scope for the SA disclosure.

Pipeline position:
    sealed aggregator-exit ledger -> sa_credit_risk_population()
        -> {build_cr4_spec, build_cr5_spec}.execute() -> CR4 / CR5 DataFrame

CR4 and CR5 are the Pillar 3 standardised-approach CREDIT-risk disclosures
(CRR Art. 444(e)). They cover the SA credit-risk book EXCLUDING counterparty
credit risk and settlement risk — both are disclosed in the CCR-series
templates (CCR1-CCR8, Art. 439) / the settlement-risk own-funds line and are
NOT part of the CR4/CR5 population. This is the deliberate mirror-image of
COREP C 07.00, which INCLUDES CCR by ``risk_type`` (Annex II rows 0090-0130):
each template owns its own recorded basis, and a shared risk-type constant is
how one template's scope would leak into another
(docs/plans/c07-ccr-derivatives.md §4 D4) — so this scope stays LOCAL to the
Pillar 3 SA templates and must NOT be reused by C 07.00.

Two symmetric jobs, one discriminator (``exposure_type``), so that every CR4
row computes every column over the SAME population (and CR5 likewise):

- EXCLUDE the non-credit-risk synthetic legs entirely (all columns — class
  rows, RW bands, totals, RWEA): SA-CCR derivative netting sets and FCCM SFT
  rows (both ``ccr_netting_set``), CCP default-fund contributions
  (``ccr_default_fund``, Art. 307-309) and settlement failed trades
  (``ccr_failed_trade``, Art. 378-380). Under CRR these carry
  ``approach_applied == "standardised"`` and so passed the CR4/CR5 origin
  filter — they leaked into the class-total / RWEA columns while being absent
  from the on/off-balance-sheet split columns (which key the sealed
  ``reporting_on_balance_sheet``, null for these types), so the template did
  not internally reconcile. Under Basel 3.1 the CCR legs already carry the
  ``standardised_ccr`` output-floor relabel and never reach the population;
  this exposure_type filter makes the exclusion regime-independent (and is a
  no-op there).

- CLASSIFY the genuine credit-risk commitment leg the sealed discriminator
  leaves null: the synthetic ``facility_undrawn`` undrawn-headroom row is an
  off-balance-sheet commitment (CRR Art. 111 / PS1/26 Art. 111 Table A1), so
  its gross feeds CR4 col b / CR5 col bb and its post-CCF EAD feeds cols c/d.
  The sealed ``reporting_on_balance_sheet`` contract keeps it null ("belongs
  to neither side; must NOT be filled to a side") because that column is also
  read by templates (CR6/CR10) that make their own scope decisions; CR4/CR5
  patch it locally to off-balance-sheet so it lands on exactly one side here.

References:
- CRR Art. 444(e) (SA credit-risk disclosure); Art. 439 (CCR1-CCR8 CCR
  disclosures); Art. 378-380 (settlement risk); Art. 307-309 (CCP
  default-fund contributions); Art. 111 (SA off-balance-sheet CCF items)
- COREP Annex II C 07.00 (the CCR-INCLUSIVE COREP counterpart)
- docs/plans/phase7-declarative-reporting.md §6 (decision F3)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Set as AbstractSet

# exposure_type values whose EAD/RWA is NOT a Part Three, Title II, Chapter 2
# SA credit-risk requirement, so they leave the CR4/CR5 population entirely
# (disclosed instead in CCR1-CCR8 / the settlement-risk line). Kept LOCAL to
# the Pillar 3 SA templates — see the module docstring: reusing this in
# C 07.00 would wrongly strip the CCR rows Annex II requires there.
_EXCLUDED_EXPOSURE_TYPES: tuple[str, ...] = (
    "ccr_netting_set",  # SA-CCR derivatives (CCR_DERIVATIVE) + FCCM SFTs (CCR_SFT)
    "ccr_default_fund",  # CCP default-fund contributions (Art. 307-309)
    "ccr_failed_trade",  # settlement failed trades (Art. 378-380)
)


def sa_credit_risk_population(results: pl.LazyFrame, cols: AbstractSet[str]) -> pl.LazyFrame:
    """Narrow the sealed ledger to the CR4/CR5 SA credit-risk population.

    Drops the non-credit-risk synthetic legs (CCR + settlement) and reclassifies
    the ``facility_undrawn`` commitment leg to off-balance-sheet, so CR4 and CR5
    compute every column over the SAME population.

    Presence-tolerant: with no ``exposure_type`` carrier (a synthetic unit frame
    that omits it) the frame is returned unchanged — the sealed ledger always
    carries it. A null ``exposure_type`` is never excluded (only an explicit
    match against the non-credit-risk set removes a row).
    """
    if "exposure_type" not in cols:
        return results
    exposure_type = pl.col("exposure_type")
    is_excluded = exposure_type.is_in(_EXCLUDED_EXPOSURE_TYPES).fill_null(value=False)
    results = results.filter(~is_excluded)
    if "reporting_on_balance_sheet" not in cols:
        return results
    return results.with_columns(
        pl.when(exposure_type == "facility_undrawn")
        .then(pl.lit(value=False))
        .otherwise(pl.col("reporting_on_balance_sheet"))
        .alias("reporting_on_balance_sheet")
    )
