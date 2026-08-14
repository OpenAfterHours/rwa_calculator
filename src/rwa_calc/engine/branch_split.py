"""
The approach split — one definition of which calculator owns a row.

Pipeline position:
    (not a pipeline stage) — an expression builder called by the two places
    that must agree on the split: ``engine/stages/calc.py``, which filters the
    unified frame into the SA / IRB / slotting branches, and
    ``engine/sa/calculator.py::calculate_unified``, which computes
    ``rwa_pre_factor`` for the rows the SA branch will not compute for itself.

Key responsibilities:
- Define the IRB and slotting predicates once, over the ``approach`` column.
- Define the SA branch as their **complement**, derived from the same predicate
  objects rather than restated as an allow-list of approach values.

Why the complement, and not a list
----------------------------------
``calculate_unified`` runs on the full pre-split frame and originally wrote
``rwa_pre_factor`` only where ``approach == 'standardised'``, while the split
routes everything that is neither IRB nor slotting onto the SA branch. Those
two selections have to describe the same population, because under the output
floor the SA branch does no arithmetic of its own — it only aliases
``rwa_post_factor -> rwa_final``. They did not: an equity-class row from the
main exposure tables was risk-weighted, excluded from the product, and reached
the submission with a null ``rwa_final`` (P1.317).

Restating the gate as an allow-list of ``{standardised, equity}`` would fix
that instance and leave the class armed — a sixth ``ApproachType`` routed to
the SA branch would be dropped the same way, silently. Two further reasons the
complement is the right form, both established while reviewing that fix:

- ``calculate_branch`` — the path taken when the output floor is off — has no
  approach guard at all and computes RWA for every row it is handed. So "the
  SA branch computes RWA for all of its rows" is already this estate's
  contract, and an allow-list would leave ``calculate_unified`` permanently
  narrower than its sibling. That difference is itself a CRR-vs-Basel-3.1
  divergence on this exact gate, which is what P1.317 *is*.
- The argument for an allow-list is that a future approach would be handed a
  confidently wrong number rather than an absent one. That trade is real, but
  it is settled the other way here: ``.claude/LESSONS.md`` B4 records that the
  dominant production escape class in this project is **absence, not
  wrongness**, and P1.317 is the proof — 3,750,000 of RWEA left the submission
  with no error, no null cell and no failing published rule. A wrong number is
  exposed to the supervisory register, the tie-outs and the goldens; a dropped
  row is exposed to none of them.

The decisive point is structural rather than a judgement about which failure is
worse: the drift that caused P1.317 was between the ``filter`` in
``stages/calc.py`` and the gate in ``calculate_unified``. Binding both to this
module couples that pair — the axis that actually drifted.

Null semantics, deliberately preserved: a null ``approach`` makes every
predicate here null, so such a row is dropped by ``filter`` and takes the
``otherwise`` arm of any ``when``. That is the behaviour both call sites had
before this module existed.

References:
- CRR Art. 92(3) / PS1/26 Art. 92(3A): the approaches whose RWEA is summed
"""

from __future__ import annotations

import logging

import polars as pl

from rwa_calc.domain.enums import ApproachType

logger = logging.getLogger(__name__)


def is_irb_approach() -> pl.Expr:
    """Rows the IRB calculator owns — foundation or advanced IRB."""
    return (pl.col("approach") == ApproachType.FIRB.value) | (
        pl.col("approach") == ApproachType.AIRB.value
    )


def is_slotting_approach() -> pl.Expr:
    """Rows the slotting calculator owns (CRR Art. 153(5))."""
    return pl.col("approach") == ApproachType.SLOTTING.value


def is_sa_branch_approach() -> pl.Expr:
    """Rows the SA branch owns — the complement of IRB and slotting.

    Today that is ``standardised`` and ``equity``. The point of stating it as a
    complement is that it stays correct without anyone remembering to revisit
    this function when a new approach is added.
    """
    return ~is_irb_approach() & ~is_slotting_approach()
