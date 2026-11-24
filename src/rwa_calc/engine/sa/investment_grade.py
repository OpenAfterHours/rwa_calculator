"""
Basel 3.1 investment-grade assessment for unrated corporates — which election governs a row.

Pipeline position:
    engine/sa/risk_weights.py::_apply_b31_risk_weight_overrides -> here
    (inside the SA risk-weight chain that ``SACalculator.calculate_unified``
    runs on every row, so IRB rows receive their SA-equivalent weight for the
    output floor as well), then engine/sa/risk_weights.py::apply_risk_weights
    -> here again once Art. 140(2) and Art. 127 have run

Key responsibilities:
- Decide, per row, whether the firm's own investment-grade assessment sets the
  weight of an unrated non-SME corporate, and if so which way it went
  (``investment_grade_assessment_expr``).
- Keep the two PS1/26 Art. 122 elections apart. They used to be one flag
  (P1.475), so a firm could not hold one without the other:

  - **Art. 122(6)**, a PRA *permission*, governs rows the firm weights under the
    Standardised Approach — SA-branch rows, including SA-weighted CCR legs
    (approach ``standardised``) that the output floor nevertheless counts.
    ``CalculationConfig.resolved_sa_investment_grade_permission``.
  - **Art. 122(8)**, the output-floor choice, governs only "exposures to which
    it applies the IRB Approach within the exposure class set out in point (g)
    of Article 112(1)" — so their SA-equivalent ``sa_rwa``, which feeds S-TREA
    (Art. 92(3A)(b)(ii)). (a) is 100%; (b), on notice to the PRA, is the
    paragraph 6 split.
    ``CalculationConfig.resolved_output_floor_investment_grade_election``.

  Both are read through the config's ``resolved_*`` properties, never the raw
  fields: an unstated election is ``None`` there and follows the deprecated
  ``use_investment_grade_assessment`` alias.

  The row's own approach selects the election: F-IRB / A-IRB (and slotting,
  which is the IRB Approach too, although no slotting row is an unrated
  non-specialised-lending corporate) read the floor election; every other
  row reads the permission. A frame that arrived with no ``approach`` column
  is an SA-only frame (``calculate_branch``): ``SA_INPUT_CONTRACT`` defaults it
  to ``standardised``, so it reads the permission. A null ``approach`` reads
  the permission too (``when`` routes null to ``otherwise``).

  An IRB-origin guarantee crossing leg — the guaranteed share of an F-IRB /
  A-IRB exposure substituted onto an SA guarantor, *reported* under the SA
  (``reporting_approach`` ``standardised``) — keeps its IRB ``approach`` at this
  stage, so it reads the Art. 122(8) election, not the permission: the leg is
  part of an exposure the firm "applies the IRB Approach" to. Only that choice
  of election has been measured, on the carrier of the registered
  crm-substitution book's S3 leg
  (``tests/acceptance/reporting/test_of08_investment_grade_election.py``). No
  money was: that leg's guarantor is a domestic central government at 0%, so
  its ``sa_rwa`` and ``rwa_final`` are 0 under every permission / election
  combination (LESSONS C2).

- Publish the outcome as the sealed carrier
  ``contracts.edges.INVESTMENT_GRADE_ASSESSED_COL`` (``sa_investment_grade_assessed``)
  so OF 08.01 row 0200 can report the legs whose output-floor weight the
  investment-grade assessment set, which PS1/26 Annex II requires that row to be
  "consistent with". ``investment_grade_weight_governed_expr`` narrows it once
  the row's exposure-class weight is final.

Three-valued, deliberately, and it records the WEIGHT the assessment set, not
the assessment alone: True = the paragraph 6(a) 65% is the row's exposure-class
weight (the governing election applies and the firm assessed the obligor
investment grade); False = the paragraph 6(b) 135% is (assessed not investment
grade, including a null input flag, which the firm has not assessed as
investment grade); null = the assessment does not set the row's weight. Null
covers the election not held, a rated obligor, a paragraph 11 SME (85%) and a
non-corporate — and, alike, every row on which another rule sets the weight
first or last: an Art. 133 subordinated instrument (Art. 112(1)(p), above
corporates in Table A2), an Art. 127 exposure in default (Art. 112(1)(j)), an
Art. 140(2) obligor contamination, and the CCR failed-trade, default-fund and
QCCP trade-exposure weights. Art. 122(8) reaches only "the exposure class set
out in point (g) of Article 112(1)", so on an IRB leg those classes are outside
it by its own words. Later credit risk mitigation (substitution, FCSM, Art. 123B)
does not move the carrier: like the loan-split carriers, it records the
exposure-class weight, not the weight after protection.

References:
- PRA PS1/26 Art. 122(5), (6), (8), (9), (11): unrated corporate weights
- PRA PS1/26 Art. 92(3A)(b)(ii): S-TREA uses Art. 122(8)(a) or (b)
- PRA PS1/26 Annex II, OF 08.01 row 0200 (printed p.118)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.edges import INVESTMENT_GRADE_ASSESSED_COL
from rwa_calc.engine.branch_split import is_irb_approach, is_slotting_approach

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)


@cites("PS1/26, paragraph 122")
def investment_grade_assessment_expr(
    config: CalculationConfig,
    is_unrated_corporate: pl.Expr,
) -> pl.Expr:
    """The firm's investment-grade assessment where its governing election sets the weight.

    Reads ``approach`` (ensured by ``SA_INPUT_CONTRACT``) and
    ``cp_is_investment_grade``.

    Args:
        config: Run configuration holding the two firm elections.
        is_unrated_corporate: The chain's unrated non-SME corporate predicate
            (no nominated-ECAI assessment; para 11 SMEs excluded).

    Returns:
        Boolean expression: True (assessed investment grade, 65%), False
        (assessed not investment grade, 135%) or null (no governing election,
        rated, SME, not a corporate). ``investment_grade_weight_governed_expr``
        later nulls the rows on which another rule sets the weight.

    References:
        PS1/26 Art. 122(6) (SA permission) and Art. 122(8)(b) (output floor).
    """
    governing_election = (
        pl.when(is_irb_approach() | is_slotting_approach())
        .then(pl.lit(config.resolved_output_floor_investment_grade_election))
        .otherwise(pl.lit(config.resolved_sa_investment_grade_permission))
    )
    return (
        pl.when(governing_election & is_unrated_corporate)
        .then(pl.col("cp_is_investment_grade").fill_null(value=False))
        .otherwise(pl.lit(None, dtype=pl.Boolean))
    )


@cites("PS1/26, paragraph 122")
@cites("PS1/26, paragraph 127")
@cites("PS1/26, paragraph 133")
def investment_grade_weight_governed_expr(ig_rw: float, nig_rw: float) -> pl.Expr:
    """The investment-grade carrier, kept only where paragraph 6 set the row's weight.

    Run once the exposure-class weight is final (after the chain, Art. 140(2)
    and Art. 127). A row whose ``risk_weight`` is not the paragraph 6 weight its
    assessment selects took its weight from another rule — an earlier branch of
    the chain (Art. 133(5) subordinated debt, a CCR failed trade, default fund
    or QCCP trade exposure) or a later override (Art. 140(2), Art. 127 default)
    — and its carrier becomes null. The same weight-equality test the loan-split
    carriers use (``b31_risk_weight_tables.py::with_b31_loan_split_parts``):
    every one of those rules sets a weight other than 65% / 135% on an unrated
    non-SME corporate, and a row the chain priced at the paragraph 6 weight
    carries that exact literal.

    Args:
        ig_rw: The Art. 122(6)(a) weight the chain applied (65%).
        nig_rw: The Art. 122(6)(b) weight the chain applied (135%).

    Returns:
        The carrier, null wherever the paragraph 6 weight is not the row's.

    References:
        PS1/26 Art. 122(8) ("within the exposure class set out in point (g)"),
        Art. 112(2) Table A2, Art. 127, Art. 133(5); Annex II OF 08.01 row 0200.
    """
    assessed = pl.col(INVESTMENT_GRADE_ASSESSED_COL)
    paragraph_6_weight = pl.when(assessed).then(pl.lit(ig_rw)).otherwise(pl.lit(nig_rw))
    return pl.when(pl.col("risk_weight") == paragraph_6_weight).then(assessed)
