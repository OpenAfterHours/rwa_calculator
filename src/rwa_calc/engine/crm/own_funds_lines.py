"""
Own-funds lines on the exposure frame: settlement-risk and CCP default-fund rows.

Pipeline position:
    ccr_sa_ccr (mints ``ft__`` / ``dfc__`` rows) -> classifier (SA only)
    -> crm_processor (no CRM: this module's partition) -> calculators (RW 12.5)

Key responsibilities:
- ``own_funds_line_expr``: the null-safe predicate naming a row whose
  ``drawn_amount`` is an own-funds REQUIREMENT, not an exposure value — the
  ``SETTLEMENT_FAILED_TRADE`` rows (CRR Art. 378-380) and the
  ``CCR_DEFAULT_FUND`` rows (CCR (CRR) Part Art. 307-310).
- ``partition_own_funds_lines``: split the classified bundle into the credit
  exposures, which keep every CRM input, and the own-funds lines, which get
  none — so counterparty- and facility-level collateral, guarantees and
  provisions are neither applied to an own-funds amount nor diluted by one.
- ``merge_crm_bundles``: re-join the two CRM outputs into one sealed bundle.

Why (review item CC-08, 2026-11). The rows are minted as synthetic exposures
only so their RWEA reaches the totals and the templates; the RW pin of 12.5
converts the amount to RWEA. Nothing in the rules makes them credit exposures:
- CRR Art. 378: "multiply that price difference by the appropriate factor in
  column A of Table 1 in order to calculate the institution's own funds
  requirement for settlement risk"; Art. 92(3)(ca) (PS1/26 identical): "the own
  funds requirements for settlement risk calculated in accordance with Articles
  378 and 380 of CRR".
- CCR (CRR) Part Art. 308(3) / 309(2): RWEA = "the own funds requirement ...
  multiplied by 12.5".
Neither admits an IRB formula or any credit risk mitigation on the amount. Before
the fix a counterparty-level cash pledge took FT1's RWEA from 625,000 to 29,762,
a counterparty-level sovereign guarantee to 50,000, and an F-IRB permission to
45,764 (CRR) / 265,881 (Basel 3.1).

References:
- CRR Art. 92(3)(ca), 378-380; CCR (CRR) Part Art. 307-310.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import ClassifiedExposuresBundle, CRMAdjustedBundle
from rwa_calc.contracts.edges import (
    CLASSIFIER_EXIT_CCR_EDGE,
    CRM_EXIT_CCR_EDGE,
    seal,
    sealed_edge_of,
)
from rwa_calc.domain.enums import RiskType

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import RawDataBundle

logger = logging.getLogger(__name__)


def own_funds_line_expr() -> pl.Expr:
    """True on settlement-risk and default-fund rows; False (never null) elsewhere.

    ``eq_missing`` keeps the predicate total, so a null ``risk_type`` — every
    drawn loan — reads False rather than poisoning the ``when`` chains that use
    it (Polars routes a null condition to ``otherwise``).
    """
    risk_type = pl.col("risk_type")
    return risk_type.eq_missing(RiskType.SETTLEMENT_FAILED_TRADE.value) | risk_type.eq_missing(
        RiskType.CCR_DEFAULT_FUND.value
    )


def carries_own_funds_lines(raw: RawDataBundle | None) -> bool:
    """Whether the CCR input can mint any own-funds line (static — no collect)."""
    ccr = raw.ccr if raw is not None else None
    return ccr is not None and (
        ccr.failed_trades is not None or ccr.default_fund_contributions is not None
    )


def partition_own_funds_lines(
    classified: ClassifiedExposuresBundle,
) -> tuple[ClassifiedExposuresBundle, ClassifiedExposuresBundle] | None:
    """Split ``classified`` into (credit exposures, own-funds lines).

    The credit bundle keeps every CRM input and pass-through; the own-funds
    bundle carries the own-funds rows with NO collateral, links, guarantees or
    provisions, so the CRM chain initialises their EAD columns and applies
    nothing. Both halves are re-sealed on the classifier CCR exit contract they
    were cut from (a row filter does not change the shape).

    Returns ``None`` when the frame is not the CCR classifier exit — own-funds
    lines are minted only by the CCR stage, so there is nothing to split.
    """
    if sealed_edge_of(classified.all_exposures) != CLASSIFIER_EXIT_CCR_EDGE.name:
        return None
    is_own_funds = own_funds_line_expr()
    credit = replace(
        classified,
        all_exposures=seal(
            classified.all_exposures.filter(~is_own_funds), CLASSIFIER_EXIT_CCR_EDGE
        ),
    )
    own_funds = replace(
        classified,
        all_exposures=seal(classified.all_exposures.filter(is_own_funds), CLASSIFIER_EXIT_CCR_EDGE),
        equity_exposures=None,
        ciu_holdings=None,
        collateral=None,
        collateral_links=None,
        guarantees=None,
        provisions=None,
        securitisation_audit=None,
    )
    return credit, own_funds


def merge_crm_bundles(credit: CRMAdjustedBundle, own_funds: CRMAdjustedBundle) -> CRMAdjustedBundle:
    """Re-join the CRM outputs of the two partitions into one sealed bundle.

    Every pass-through and audit frame comes from the credit half (the own-funds
    half was given none); the errors of both halves are kept.
    """
    exposures = pl.concat([credit.exposures, own_funds.exposures], how="diagonal_relaxed")
    return replace(
        credit,
        exposures=seal(exposures, CRM_EXIT_CCR_EDGE),
        crm_errors=[*credit.crm_errors, *own_funds.crm_errors],
    )


__all__ = [
    "carries_own_funds_lines",
    "merge_crm_bundles",
    "own_funds_line_expr",
    "partition_own_funds_lines",
]
