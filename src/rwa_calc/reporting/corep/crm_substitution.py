"""
COREP CRM substitution — the cross-template inflow router and the IRB waterfall.

Pipeline position:
    sealed aggregator-exit ledger -> substitution_inflows() ->
    ``ReportingContext.substitution_inflow`` -> C 07.00 col 0100
    (``corep/c07.py``) / C 08.01 col 0080 (``corep/c08.py``);
    crm_waterfall() / waterfall_refs() -> the C 08.01/02 col 0090 ``Formula``

Key responsibilities:
- Compute the per-destination-class CRM substitution INFLOW once over the WHOLE
  sealed population, and hand each inflow to the template that reports the
  approach the substituted leg is actually treated under.
- Own the C 08.01/02 col 0090 waterfall identity and its per-row-scope column
  selection, so the published rule and the code that satisfies it sit together.

WHY THIS IS NOT A PER-TEMPLATE HELPER (the defect it retires). C 07.00 and
C 08.01 each derived their own inflow map from their OWN approach-filtered
population, so a substitution that crossed the SA/IRB boundary was reported as
an outflow on one template and as an inflow on NEITHER: an IRB corporate loan
guaranteed by a sovereign (an SA-only class under PS1/26 Art. 147A(1)(a))
deducted the covered part on C 08.01 ``corporate`` and added it back nowhere,
because C 08.01 has no sovereign sheet and C 07.00's sovereign sheet is outside
the IRB leg's population. Annex II requires the opposite, for both templates and
both frameworks: "Exposures stemming from possible in- and outflows from and to
other templates shall be taken into account."

THE ROUTING KEY is the sealed ``reporting_approach`` — the aggregator's
``approach_post_crm`` (``engine/aggregator/aggregator.py``), which is exactly the
post-substitution approach: a guaranteed leg with an SA guarantor is a direct SA
exposure to the guarantor (CRR Art. 235 risk-weight substitution) and so its
inflow belongs on C 07.00, while a guaranteed leg with an IRB guarantor stays
under the obligor's IRB approach (CRR Art. 161 parameter substitution) and its
inflow belongs on C 08.01. The two destinations PARTITION the population — the
SA side is the complement of the IRB labels, so it also picks up the output
floor's ``standardised_ccr`` relabel — which is what makes an inflow impossible
to drop or to count twice. A frame that does not seal the column (synthetic
unit frames) is not routed at all: every inflow is offered to both templates and
each keeps the destination classes it has sheets for, the pre-routing behaviour.

SAME-CLASS MIGRATIONS ARE INCLUDED. Annex II, both templates and both
frameworks: "Inflows and outflows within the same exposure classes and, where
relevant, obligor grades or pools, shall also be considered." Gating the inflow
on a class CHANGE while the outflow subtotal counts every covered part makes a
same-class guarantee shrink the return by the covered amount — reproduced on
C 07.00 (``rgla`` guaranteed by an ``rgla`` counterparty lost 1,000,000 out of
col 0110) and, once col 0070 became the Annex II subtotal, on C 08.01 too.

RESIDUAL GAP (recorded, not papered over). The outflow subtotal counts every
route in the substitution block, but only the unfunded routes carry a
destination: the sealed ledger has ``post_crm_exposure_class_guaranteed`` for
guarantee / credit-derivative legs only. C 07.00's funded limbs (col 0070
financial collateral under the Simple Method, col 0080 Art. 232 other funded
protection) and C 08.01's col 0060 (Art. 232 other funded protection) therefore
produce an outflow with no matching inflow. The collateral issuer's exposure
class is not modelled, so the honest options are to under-report the outflow or
to under-report the inflow; the live rules ``v1663_m`` / ``v1665_m`` /
``v0305_m`` fix the outflow as the subtotal, so the gap lands on the inflow.
Sealing an issuer class per collateral leg is the follow-up that closes it.

References:
- Reg (EU) 2021/451 Annex II: C 07.00 cols 0090/0100 and C 08.01 cols 0070/0080
  ("SUBSTITUTION OF THE EXPOSURE DUE TO CRM"); PRA PS1/26 Annex II, OF 08.01
  cols 0070/0080
- CRR Art. 235 (risk-weight substitution), Art. 161 (IRB parameter substitution)
- Published rules: ``v0305_m`` / ``v0306_m`` (C 07.00), ``v1662_m`` / ``v1663_m``
  (C 08.01.a), ``v0347_m`` / ``v1665_m`` (C 08.02)

The two calling generators (``c07_plans`` / ``generate_c08_01``) carry the
``@cites`` annotations for this code path; a decorator pair here
(``CRR Art. 235`` + ``PS1/26, paragraph 1.3``) is a worthwhile addition but
needs ``uv run python scripts/generate_citation_matrix.py`` re-run to refresh
the docs matrix and the contract snapshot alongside it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Mapping

# The post-substitution approach labels whose inflow belongs on the IRB
# templates. Everything else is the SA destination — the complement, so the two
# sides partition the population (see the module docstring).
_IRB_DESTINATIONS: tuple[str, ...] = ("foundation_irb", "advanced_irb", "slotting")

# The sealed post-substitution approach (aggregator ``approach_post_crm``).
_DESTINATION_APPROACH_COL: str = "reporting_approach"
# The guarantor's exposure class — the destination sheet key.
_DESTINATION_CLASS_COL: str = "post_crm_exposure_class_guaranteed"
# The covered part of the original exposure pre-conversion factors.
_COVERED_COL: str = "guaranteed_portion"

type Destination = Literal["standardised", "irb"]

# C 08.01 rows whose col 0090 waterfall EXCLUDES the B31 col 0035 on-balance-sheet
# netting term. The BoE splits the published waterfall in two by row scope:
# ``boe_b0746`` (live, ERROR) is ``{c0090} = sum({c0020; 0035; 0070; 0080})`` over
# r:0010;0017;0020;0070;0170;0175;0180;0190;0200, while ``boe_b0746_1`` drops the
# 0035 term over r:0001;0030;0031;0032;0033;0034;0035 — which is exactly the
# OFF-BALANCE-SHEET row family (row 0030 "Off balance sheet items subject to credit
# risk" plus its five CCF sub-rows). That split is not arbitrary: Art. 166(3)
# netting of loans and deposits is an on-balance-sheet effect, so it cannot reduce
# an off-balance-sheet row. Row 0080 (slotting total) and the inert CCR
# netting-set rows 0040/0050/0060 are in NEITHER scope; 0080 keeps the term so it
# stays consistent with its section sibling 0070 and the 0070 + 0080 = 0010
# approach partition still foots. C 08.02 has no such split — ``boe_b0760`` puts
# 0035 in the waterfall on every row of OF08.02.01.01. Under CRR there is no col
# 0035 at all, so the whole mechanism is a B31-only no-op there.
C08_01_NETTING_EXEMPT_ROWS: frozenset[str] = frozenset(
    {"0030", "0031", "0032", "0033", "0034", "0035"}
)


def waterfall_refs(column_refs: tuple[str, ...], *, netting: bool) -> tuple[str, ...]:
    """The ``Formula`` refs for one C 08.01/02 col 0090 cell.

    Selecting the col 0035 term by REF rather than by a branch inside
    :func:`crm_waterfall` is C 07.00's ``_net_of_adjustments`` precedent: the
    executor passes only the named refs, so an omitted one reads as zero. The
    presence guard keeps CRR — which has no col 0035 — on the three-ref form, and
    is load-bearing besides: a ref naming a column outside ``column_refs`` raises
    in the executor rather than degrading.
    """
    if netting and "0035" in column_refs:
        return ("0020", "0035", "0070", "0080")
    return ("0020", "0070", "0080")


def crm_waterfall(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0090 = 0020 - 0035 - 0070 + 0080 (positive magnitudes; 0035 by ref).

    The published identity, on the REPORTED signs where 0035/0070 are "(-)"
    deductions: ``{c0090} = sum({c0020; 0035; 0070; 0080})`` — EBA ``v1662_m`` /
    ``v0347_m`` and BoE ``boe_b0746`` (C 08.01) / ``boe_b0760`` (C 08.02). Col
    0070 IS the whole outflow; cols 0040/0050/0060 are the breakdown that MAKES
    it up, so subtracting both — as this did before — deducts every covered part
    twice. That is C 07.00's recorded ``_net_after_substitution`` defect on the
    IRB surface. The cell runs BEFORE the Annex II §1.3 negation pass, hence the
    positive magnitudes and the subtractions.
    """
    return (
        (cells["0020"] or 0.0)
        - (cells.get("0035") or 0.0)
        - (cells["0070"] or 0.0)
        + (cells["0080"] or 0.0)
    )


def substitution_inflows(
    results: pl.LazyFrame,
    cols: set[str],
    *,
    destination: Destination,
) -> dict[str, float]:
    """Per-destination-class CRM substitution inflows for one template family.

    ``results`` is the WHOLE sealed population (not the calling template's own
    slice) — routing across the SA/IRB boundary is the entire point. ``cols``
    is its column set. ``destination`` selects the half of the population whose
    substituted legs are treated under the standardised approach (C 07.00) or
    under an IRB approach (C 08.01).

    Returns ``{guarantor exposure class: covered amount}``, positive
    magnitudes, empty when the frame carries no substitution carriers. Legs with
    no destination class are dropped rather than grouped under a null key: the
    sheet axis has no null member, so a null-keyed inflow could only be silently
    lost. Every leg with a positive covered part is counted — including one whose
    guarantor sits in the obligor's own class (Annex II "Inflows and outflows
    within the same exposure classes ... shall also be considered").
    """
    if not {_COVERED_COL, _DESTINATION_CLASS_COL} <= cols:
        return {}
    covered = pl.col(_COVERED_COL).fill_null(0.0)
    migrated = results.filter((covered > 0) & pl.col(_DESTINATION_CLASS_COL).is_not_null())
    if _DESTINATION_APPROACH_COL in cols:
        is_irb = (
            pl.col(_DESTINATION_APPROACH_COL).is_in(list(_IRB_DESTINATIONS)).fill_null(value=False)
        )
        migrated = migrated.filter(is_irb if destination == "irb" else ~is_irb)
    grouped = migrated.group_by(_DESTINATION_CLASS_COL).agg(covered.sum().alias("inflow")).collect()
    return {
        row[_DESTINATION_CLASS_COL]: float(row["inflow"]) for row in grouped.iter_rows(named=True)
    }
