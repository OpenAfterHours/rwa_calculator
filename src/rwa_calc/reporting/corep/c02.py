"""
COREP C 02.00 / OF 02.00 — own funds requirements (the master roll-up).

Pipeline position:
    sealed aggregator-exit ledger -> ONE typed pre-pass aggregation
    (approach / SA-class / IRB-class / sub-class / SL-type group-bys)
    -> figures by ``c02_rows.Slot`` -> the published layout -> DataFrame | None

This template is the recorded Kind-9 exception (plan §8.2): a portfolio-
total cross-approach roll-up whose row values are sums of PRE-COMPUTED
aggregates with value-dependent fallbacks — it deliberately does NOT run
through the cellspec executor.

WHERE a figure is reported is not decided here. Every figure is computed
against a ``c02_rows.Slot`` — named for what it means — and the slot carries
the row code each regime's published template gives it. This module addresses
no row by code (recorded fix 2026-11-13: it used to, and its codes were not
the published ones in either regime — see ``c02_rows``).

Cell semantics (recorded decisions):

- COLUMN 0010 IS UN-FLOORED UNDER BASEL 3.1. Every figure in it sums
  ``rwa_pre_floor``, not ``rwa_final``. Row 0010 column 0010 is ONE data point
  with OF 02.01's U-TREA total (taxonomy: OF02.00.01.01 r0010 c0010 ==
  OF02.01.01.03 r0080 c0030), ``boe_b1092`` sums it from the rows beneath it,
  and ``boe_b0383`` compares it with the floor — so a binding floor's add-on,
  which the engine spreads over ``rwa_final``, belongs in none of those rows.
  Under CRR there is no floor and the column sums ``rwa_final``. (Until
  2026-11-13 the column summed ``rwa_final`` and row 0010 column 0030 repeated
  the same total, which reported the floor as its own result.) This template
  and OF 02.01 each add the legs up in their own order, so the two cells can
  differ in the last binary place; the filing adapter gives a data point shown
  in several cells one value (``filing/canonical.py``).
- COLUMN 0020 (Basel 3.1) is the standardised-approach RWEA (``sa_rwa``) of the
  SAME legs a modelled row counts in column 0010 — "risk exposure amounts
  calculated under standardised approaches per exposure class" (PS1/26 Annex II
  §1.3). The taxonomy has the cell on the modelled rows only: a standardised
  row's column 0010 already IS that figure. Row 0040 is their S-TREA,
  ``boe_b0716``: SA (row 0050, column 0010) + the modelled book on SA (row
  0240, column 0020). Each class cell is one data point with OF 08.01 col 0276
  on the class's sheet (``boe_b0638``-``boe_b0654``), which sums the same
  carrier over the same key.
- COLUMN 0020 IS REPORTED WHENEVER IT IS KNOWN, and it is NOT gated on the
  output floor's entity scope. Two published facts decide that, against the
  reading of Annex II's "Scope" paragraph as "an exempt entity leaves the
  column empty": ``boe_b0716`` is an Error rule with no precondition, so a
  return carrying SA RWEA in row 0050 and nothing in row 0040 column 0020 is
  rejected (measured on an SA-only run: 0 against 1,375,000); and the class
  cells are OF 08.01 col 0276's data points, which that template reports
  whenever the ledger seals ``sa_rwa``. "Known" is: the ledger seals
  ``sa_rwa``, or it holds no modelled leg whose standardised figure would be
  needed. A modelled leg with no ``sa_rwa`` leaves the column empty and says so.
- COLUMN 0030 (Basel 3.1) exists on four rows. Row 0010 is the floor itself,
  "x * S-TREA + OF-ADJ" (Annex II §1.3, Art. 92(2A)); rows 0035 / 0036 are x and
  OF-ADJ; row 0034 is "Yes" when the floor is "equal to or greater than" row
  0010 column 0010. x is a RATE (``boe_b0359`` admits 0.55 ... 0.725), read off
  the ``OutputFloorSummary`` or, without one, the sealed ``output_floor_pct``.
  OF-ADJ is a portfolio figure the ledger does not carry: with no summary it is
  unknown, and then neither it, the floor nor the indicator is reported —
  empty, never 0.0, which ``boe_b0359`` and Art. 92 would both make a
  misstatement. An entity outside the floor's scope
  (``OutputFloorConfig.is_floor_applicable()``, Art. 92(2A)) has no output
  floor and reports nothing in column 0030.
- THE ENGINE'S FLOOR IS NOT THE TEMPLATE'S. The engine floors the modelled
  subset in isolation (recorded defect, docs/plans/c07-ccr-derivatives.md §4
  D6), so when its floor binds on a book that also holds SA exposures its
  post-floor total exceeds max(row 0010 col 0010, col 0030). Nothing here
  hides that: the difference is logged.
- Equity RWA routes by the sealed ``equity_method`` discriminator (R6):
  IRB-method equity (Art. 155(2) simple / Art. 155(3) PD-LGD — CRR only)
  reports at ``EQUITY_IRB`` and counts in the IRB total; SA-method equity
  (Art. 133 — the whole book under Basel 3.1, where Art. 147A removes IRB
  equity and OF 02.00 has no such row) reports in the SA breakdown (the SA
  total + its class row). No leg is booked in both, and the flat total counts
  it once regardless of routing. Equity whose method the ledger did not seal
  is treated as SA (never disclosed as IRB equity without an explicit method).
- The SA total and the SA class rows cover ``_SA_APPROACHES`` — SA *and*
  SA-CCR — so the template foots against the total and credit-risk rows, which
  are flat ledger sums and always carried the CCR RWEA (recorded fix
  2026-07-12; see the constant for why it is not shared).
- THREE keys, one per tied template, and all three now POST-SUBSTITUTION
  (``reporting_approach`` / ``reporting_class``): the approach rows and the
  SA class rows tie to C 07.00, the IRB class rows to C 08.01, and both
  those templates have moved their exposure-value and RWEA columns onto
  that basis. See the long note at the binding site for why that PRESERVES
  the 2026-07-12 fix (whose stated purpose was that tie) rather than
  reversing it, why the IRB half followed one commit later, why Art. 92 is
  unaffected, and — recorded there rather than fixed here — the
  ``(foundation_irb, retail_other)`` pair that has no row, which is
  downstream evidence of a missing CRR Art. 201 eligibility gate. The SA class
  rows route through the many-to-one ACCUMULATING ``C02_00_SA_CLASS_MAP``; they
  are "See CR SA template", so the map's groupings ARE the C 07.00 sheet
  groupings (recorded fix 2026-08-01: the map had been keyed on a vocabulary
  ``ExposureClass`` never emitted, so corporate_sme / other dropped out of the
  roll-up and retail_mortgage reported as retail (h) instead of
  immovable-property (i) — EBA v0207_m / v3334_i / v3338_i / v4240_i /
  v4241_i).
- THE IRB CLASS ROWS FOLLOW THE TIED TEMPLATE'S SHEETS. C 02.00 rows 0260-0410
  each equal a C 08.01 sheet (EBA ``v4245_i``-``v4259_i``), and those sheets are
  the Art. 147(2) classes, so CRR corporates split on the CLASS
  (``corporate_sme`` -> SME, ``corporate`` -> Other; Art. 147(2)(c) has no
  "financial and large" sub-class). OF 02.00 splits them three ways on the
  classifier's ``exposure_subclass`` (PS1/26 Art. 147A(1)(e)/(f)):
  financial/large -> F-IRB only, SME, other. A ``corporate_sme``-CLASS leg is
  SME under both (it used to match neither split and fell out of the
  breakdown: 16,063,845.09 of A-IRB RWEA on the rich Basel 3.1 portfolio).
- UNDER BASEL 3.1 THAT IS ONE DEFINITION, NOT TWO THAT AGREE. Each OF 02.00 IRB
  class row is one data point with the total of an OF 08.01 sheet, so the rows
  are grouped by the very sheet key OF 08 keys its sheets by
  (``corep/irb_sheets.py``): a leg cannot be counted in one row and reported on
  another sheet. The leg classification this module used to hold lives there.
- A-IRB folds a financial/large corporate into "other general corporates
  non-SME" while F-IRB reports it separately — asymmetric, preserved: Art. 147A
  permits no A-IRB for that sub-class, so the engine should emit none.
- An unknown SME / financial-sector / property-type flag is NOT a filter: the
  leg reports as non-SME, non-financial, residential.
- UNDER CRR SLOTTING IS SPECIALISED LENDING WITHOUT OWN ESTIMATES. C 02.00 has
  no slotting row. EBA ``v10673_m`` lets the C 08.01 slotting row carry a figure
  on the specialised-lending sheets only, ``v0338_m`` puts that row in the
  sheet's total, and ``v4248_i`` / ``v4253_i`` tie the totals to rows 0290 /
  0350; of those two parents, "neither own estimates of LGD nor Conversion
  Factors" (row 0250) is what Art. 153(5) slotting is. So slotting counts in
  ``FIRB_SPECIALISED_LENDING`` and ``FIRB``. (It was written to row 0410, which
  is "Retail - Other non-SME".) OF 02.00 gives slotting rows of its own.
- A figure whose slot has NO row under the regime (an A-IRB institution under
  Basel 3.1, say) is neither dropped nor put in a neighbouring row: it stays in
  its approach total, and ``_warn_if_a_breakdown_strands`` reports the amount.
  OF 08 reports the same legs on a sheet outside its published axis and in the
  same approach's Total (``corep/c08_sheets.py``).
- Rows this calculator computes zero-fill; the rows it does not (the other risk
  types, rows 0450 / 0460 / 0470) stay empty.

References:
- CRR Art. 92 (own funds requirements)
- CRR Art. 155 (IRB equity — ``EQUITY_IRB`` under CRR)
- PRA PS1/26 Art. 92 para 2A/3A/5 (output floor); Art. 147A (IRB equity,
  IRB sovereigns and A-IRB institutions removed); Annex II §1.3
- docs/plans/phase7-declarative-reporting.md §8.2 (Kind-9 pre-pass)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.reporting.corep import c02_rows as rows
from rwa_calc.reporting.corep import irb_sheets
from rwa_calc.reporting.corep.templates import (
    B31_C02_00_COLUMN_REFS,
    C02_00_SA_CLASS_MAP,
    CRR_C02_00_COLUMN_REFS,
    EQUITY_IRB_METHODS,
)
from rwa_calc.reporting.kernel import pick

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from rwa_calc.contracts.bundles import OutputFloorSummary
    from rwa_calc.contracts.config import OutputFloorConfig

# The sub-class aggregation key: (approach, class, is_sme, is_financial_large,
# is_commercial_property). Every flag is a definite boolean — unknown is False.
type _SubKey = tuple[str, str, bool, bool, bool]

# The approach labels that make up C 02.00's "Standardised approach" (rows
# 0050 / 0060) and its Art. 112 class rows (0070-0211).
#
# Annex II defines row 0040 as "RISK WEIGHTED EXPOSURE AMOUNTS FOR CREDIT,
# COUNTERPARTY CREDIT AND DILUTION RISKS AND FREE DELIVERIES" (Art. 92(3)(a),(f))
# and its SA child as the "CR SA and SEC SA templates at the level of total
# exposures" — the SA row IS the C 07.00 total, and C 07.00 reports CCR business
# (rows 0090-0130). Both CCR risk types (CCR_SFT and CCR_DERIVATIVE) are SA
# risk-weighted but carry ``standardised_ccr`` under Basel 3.1 — the output-floor
# relabel in ``engine/stages/calc.py``, which routes them into
# ``FLOOR_ELIGIBLE_APPROACHES`` and is load-bearing. So they are admitted here by
# label, and the template foots. Under CRR the relabel never fires (the legs
# carry ``standardised``), so the second entry is inert and no CRR cell moves.
#
# Deliberately LOCAL to C 02.00 (docs/plans/c07-ccr-derivatives.md §4 D4): a
# shared SA-approach constant would also widen the Pillar 3 CR4/CR5 disclosures,
# which correctly scope CCR out under Basel 3.1 (it has CCR1-CCR8).
_SA_APPROACHES: tuple[str, ...] = ("standardised", "standardised_ccr")

_FIRB: str = irb_sheets.FIRB
_AIRB: str = irb_sheets.AIRB
_SLOTTING: str = irb_sheets.SLOTTING
_EQUITY: str = "equity"

# OF 02.00's slotting rows by ``sl_type``.
_SLOTTING_TYPE_SLOTS: dict[str, rows.Slot] = {
    "project_finance": rows.SLOTTING_PROJECT_FINANCE,
    "object_finance": rows.SLOTTING_OBJECT_FINANCE,
    "commodities_finance": rows.SLOTTING_COMMODITIES_FINANCE,
    "ipre": rows.SLOTTING_IPRE,
    "hvcre": rows.SLOTTING_HVCRE,
}

# This module's handle on the shared ``equity_method`` IRB partition —
# ``EQUITY_IRB`` plus the IRB total. A RE-EXPORT of the one definition in
# ``templates``, not a second copy: C 07.00 admits its Art. 112(1)(p) population on
# the same tuple and the live EBA ERROR rule ``v4244_i`` ties row 0210 here to that
# template's equity sheet, so the two reading different values would straddle a
# published identity with nothing to catch it.
_EQUITY_IRB_METHODS: tuple[str, ...] = EQUITY_IRB_METHODS

# A residual below this is float dust, not a missing row.
_TOLERANCE: float = 0.01


@cites("PS1/26, paragraph 1.3")
def generate_c02_00(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
    *,
    output_floor_summary: OutputFloorSummary | None = None,
    output_floor_config: OutputFloorConfig | None = None,
) -> pl.DataFrame | None:
    """Generate C 02.00 (CRR) / OF 02.00 (Basel 3.1) Own Funds Requirements.

    The master capital template aggregating RWEA across all risk types.
    This calculator populates the credit risk rows (SA, F-IRB, A-IRB,
    slotting, equity); the other risk types are laid out and left empty.
    """
    ead_col = pick(cols, "ead_final")
    final_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    if ead_col is None or final_col is None:
        errors.append("C 02.00 skipped: missing EAD or RWA columns in results")
        return None

    is_b31 = framework == rows.FRAMEWORK_BASEL_3_1
    column_refs = B31_C02_00_COLUMN_REFS if is_b31 else CRR_C02_00_COLUMN_REFS
    # Column 0010's carrier: the UN-floored RWEA under Basel 3.1 (module
    # docstring). A frame the floor never ran on seals no ``rwa_pre_floor``, and
    # there ``rwa_final`` IS the un-floored figure.
    own_col = "rwa_pre_floor" if is_b31 and "rwa_pre_floor" in cols else final_col

    # THREE keys, because C 02.00's breakdowns tie to THREE different templates
    # and each must key the basis of the one it ties to (the two-basis discipline
    # C 07.00 established in f94be554, applied within one template):
    #
    #   approach_col   POST  (``reporting_approach``)      the approach totals
    #   sa_ec_col      POST  (``reporting_class``)         the SA class rows, "See CR
    #                                                      SA template" -> C 07.00
    #   irb_ec_col     POST  (``reporting_class``)         the IRB class rows
    #                                                      -> C 08.01
    #
    # This PRESERVES the 2026-07-12 fix rather than reversing it. That fix moved
    # the class rows off the origination class onto the applied Art. 112 class for
    # a stated reason — "so the SA breakdown ties to C 07.00". C 07.00's
    # exposure-value and RWEA columns have since moved to the post-substitution
    # basis, so FOLLOWING C 07.00 is what honours that intent; staying put is what
    # breaks it. The tie is published as EBA v4239_i / v4240_i ({C 02.00 r0120 /
    # r0130 c0010} == {C 07.00.a r0010 c0220} per class sheet), both ERROR
    # severity, and both FAILED on the origin key (institutions 750,000 against
    # C 07.00's 2,150,000; corporates 6,600,000 against 5,200,000 — the
    # substituted leg counted at the obligor's sheet on one template and the
    # guarantor's on the other).
    #
    # THE IRB CLASS ROWS HAVE NOW FOLLOWED, and this was always the PAIRED half of
    # that sequencing decision rather than a different answer. They tie to C 08.01
    # col 0260 (``boe_b0616``, ERROR: {OF 02.00 r0271 c0010} = {OF 08.01 r0010
    # c0260 z0006}), and C 08.01's exposure-value / RWEA columns have moved to the
    # post-substitution basis. When only ONE side had moved the rule broke by
    # exactly one leg either way — the S1 guarantee, an F-IRB corporate covered by
    # an F-IRB institution (1,427,773.69 = that leg's rwa_final): 4,283,321.07 vs
    # 2,855,547.38 with C 02.00 ahead, and 2,855,547.38 vs 4,283,321.07 with
    # C 08.01 ahead. Art. 161 substitution makes it an institution exposure on both
    # templates, so both keys sit on ``reporting_class`` and the rule foots.
    #
    # THE IMPOSSIBLE-PAIR TRAP, MEASURED AND ROOT-CAUSED. A post class key against
    # the obligor's retained approach can produce an (approach, class) pair with no
    # row — the aggregator moves the class but keeps the obligor's approach for a
    # non-SA guarantor. Here that is ``(foundation_irb, retail_other)``, which
    # Art. 151(4) makes impossible (retail is A-IRB only), and its RWEA would fall
    # out of the F-IRB class rows while the F-IRB total still counted it —
    # invisible to every published rule, because the rules only check rows that DO
    # exist. Measured on the CRM-substitution portfolio: 2,028,365.78 (CRR) /
    # 1,700,935.66 (B31).
    #
    # THE CAUSE IS NOT THIS KEY, AND MUST NOT BE PAPERED OVER HERE. The single leg
    # producing it is an F-IRB corporate loan whose covered part is guaranteed by a
    # RETAIL counterparty. CRR Art. 201(1) is an exhaustive list of eligible
    # providers of unfunded credit protection — (a) central governments/banks,
    # (b) RGLAs, (c) MDBs, (d) 0%-RW international organisations, (e) PSEs,
    # (f) institutions, (g) other CORPORATE entities, (h) QCCPs — and it has NO
    # retail limb, while Art. 201(2) additionally requires an IRB guarantor to be
    # internally rated. So the guarantee is ineligible and should never have
    # migrated the class at all; the impossible pair is DOWNSTREAM EVIDENCE of a
    # missing Art. 201 eligibility gate in ``engine/crm/``, not a reporting-layer
    # keying problem. Re-measured with such a gate applied, stranding is 0.00 in
    # both regimes. Normalising the pair into an adjacent row here would launder an
    # ineligible guarantee into a valid-looking disclosure, so it is deliberately
    # NOT done. Do not "fix" this by remapping the class or the approach.
    #
    # The 2026-07-12 note also said "identical values for IRB rows (raw ==
    # applied for the IRB book)". That is NO LONGER TRUE, and it is the defect
    # this fixes: an IRB-origin leg whose guarantee the engine applied under
    # Art. 235 carries ``reporting_approach == "standardised"`` against
    # ``approach_applied == "foundation_irb"``/``"slotting"``, so its RWEA was
    # disclosed under the IRB approach / slotting for an exposure that is a direct
    # SA exposure to the guarantor.
    #
    # ART. 92 IS UNTOUCHED: the total and credit-risk rows are FLAT ledger sums,
    # and the approach labels partition the ledger either way
    # (``approach_post_crm`` is ``approach_applied`` or the SA literal, never a new
    # label), so RWEA moves BETWEEN the SA and IRB totals and their sum still
    # foots to the credit-risk row.
    #
    # Each key degrades to its origin twin on a frame that seals no
    # post-substitution column, so the split is number-neutral wherever nothing
    # substitutes. Written as conditionals rather than multi-candidate ``pick``
    # ladders, which the arch_check ratchet counts.
    sa_ec_col = pick(
        cols, "reporting_class" if "reporting_class" in cols else "reporting_class_origin"
    )
    # Written out rather than aliased to ``sa_ec_col``: the two keys are distinct
    # QUESTIONS that currently have the same answer, and the seam is what let the
    # SA half move in f94be554/a7ced69e while the IRB half waited for C 08.01.
    irb_ec_col = pick(
        cols, "reporting_class" if "reporting_class" in cols else "reporting_class_origin"
    )
    # The origin twin, kept for the Art. 151(4) revert in
    # ``irb_sheets.placeable_irb_class``.
    origin_ec_col = pick(cols, "reporting_class_origin")
    approach_col = pick(
        cols, "reporting_approach" if "reporting_approach" in cols else "approach_applied"
    )

    if approach_col and sa_ec_col and irb_ec_col:
        ledger = _aggregate(
            results,
            cols,
            approach_col=approach_col,
            sa_ec_col=sa_ec_col,
            irb_ec_col=irb_ec_col,
            origin_ec_col=origin_ec_col or irb_ec_col,
            own_col=own_col,
            final_col=final_col,
        )
    else:
        # No approach / class key: the totals are all that can be stated.
        ledger = _totals_only(results, own_col=own_col, final_col=final_col)

    amounts = _amounts_by_slot(ledger, framework)
    class_rows = _sa_class_rows(ledger.sa_class)
    if ledger.has_breakdown:
        _warn_if_a_breakdown_strands(amounts, class_rows, framework)

    # Column 0020 is known when the ledger seals the standardised figure, or when
    # it holds no modelled leg that would need one (module docstring).
    standardised_known = (
        is_b31 and ledger.has_breakdown and ("sa_rwa" in cols or ledger.modelled_legs == 0)
    )
    if is_b31 and ledger.modelled_legs and "sa_rwa" not in cols:
        logger.warning(
            "OF 02.00: %d modelled leg(s) carry no sa_rwa, so column 0020 and the output "
            "floor cannot be stated and are left empty",
            ledger.modelled_legs,
        )
    floor = _Floor()
    if is_b31 and (output_floor_config is None or output_floor_config.is_floor_applicable()):
        floor = _output_floor(
            ledger,
            s_trea=amounts[rows.CREDIT_RISK].standardised if standardised_known else None,
            summary=output_floor_summary,
        )
        _warn_if_the_engine_floor_differs(ledger, floor)

    cells = _cells(amounts, class_rows, floor, framework, report_standardised=standardised_known)
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "row_ref": pl.String,
        "row_name": pl.String,
    }
    for ref in column_refs:
        schema[ref] = pl.Float64
    return pl.DataFrame(_build_rows(cells, framework, list(column_refs)), schema=schema)


# =============================================================================
# Typed pre-pass results
# =============================================================================


@dataclass(frozen=True)
class _Amount:
    """One population's RWEA under its own approach and under the standardised one.

    ``own`` is what column 0010 reports. ``standardised`` (``sa_rwa``) is what
    Basel 3.1 column 0020 reports for the same legs, and is 0.0 throughout on a
    frame that seals no ``sa_rwa`` — where the column is reported only if the
    frame holds no modelled leg.
    """

    own: float = 0.0
    standardised: float = 0.0

    def __add__(self, other: _Amount) -> _Amount:
        return _Amount(self.own + other.own, self.standardised + other.standardised)


_NOTHING = _Amount()


@dataclass(frozen=True)
class _Ledger:
    """The pre-pass aggregates every row is assembled from.

    ``has_breakdown`` is False only on a frame with no approach / class key,
    where the totals are all that can be stated. ``modelled_legs`` counts the
    F-IRB / A-IRB / slotting legs — the ones column 0020 needs ``sa_rwa`` for.
    ``irb_class`` / ``irb_sub`` are the CRR class rows' groupings; ``irb_sheet``
    is the Basel 3.1 one, keyed ``(approach, OF 08 sheet key)``.
    """

    total: _Amount
    final_total: float
    multiplier: float | None = None
    has_breakdown: bool = True
    modelled_legs: int = 0
    by_approach: dict[str, _Amount] = field(default_factory=dict)
    sa_class: dict[str, _Amount] = field(default_factory=dict)
    irb_class: dict[tuple[str, str], _Amount] = field(default_factory=dict)
    irb_sub: dict[_SubKey, _Amount] = field(default_factory=dict)
    irb_sheet: dict[tuple[str, str], _Amount] = field(default_factory=dict)
    slotting_type: dict[str, _Amount] = field(default_factory=dict)
    equity_sa: _Amount = _NOTHING
    equity_irb: _Amount = _NOTHING


@dataclass(frozen=True)
class _Floor:
    """The output-floor block: Basel 3.1 rows 0010 (col 0030), 0034, 0035, 0036.

    ``None`` is "not known", and an unknown figure is not reported.
    """

    multiplier: float | None = None
    adjustment: float | None = None
    amount: float | None = None
    activated: bool | None = None


# =============================================================================
# Pre-pass aggregation
# =============================================================================


def _aggregate(
    results: pl.LazyFrame,
    cols: set[str],
    *,
    approach_col: str,
    sa_ec_col: str,
    irb_ec_col: str,
    origin_ec_col: str,
    own_col: str,
    final_col: str,
) -> _Ledger:
    """Collect the ledger ONCE and group it every way the template needs.

    TWO CLASS KEYS, one per tied template — see the caller's note.
    ``sa_ec_col`` keys the SA class rows, which tie to C 07.00; ``irb_ec_col``
    keys the IRB class rows, which tie to C 08.01. BOTH are now the
    post-substitution class, because both tied templates have moved; they stay
    two parameters because they are two questions, and they answered differently
    for the one commit between C 07.00 moving and C 08.01 following.

    The IRB class and sub-class group-bys read the SAME placeable class
    (``irb_sheets.placeable_irb_class``), so a leg reverted to its origin class
    is split with the class it is counted in — before 2026-11-13 the sub-class
    split read the un-reverted class and the reverted leg fell out of the
    corporate sub-rows. The Basel 3.1 sheet key reads it too, and is the
    expression OF 08 keys its post-substitution sheets by.
    """
    placeable = irb_sheets.placeable_irb_class(irb_ec_col, origin_ec_col, approach_col)
    collected = results.select(
        pl.col(approach_col).alias("_approach"),
        pl.col(sa_ec_col).alias("_ec_sa"),
        placeable.alias("_ec_irb"),
        irb_sheets.sheet_key_expr(cols, pl.col(approach_col), placeable).alias("_sheet"),
        pl.col(own_col).fill_null(0.0).alias("_own"),
        pl.col(final_col).fill_null(0.0).alias("_final"),
        (pl.col("sa_rwa").fill_null(0.0) if "sa_rwa" in cols else pl.lit(0.0)).alias("_sa"),
        _equity_method_expr(cols).alias("_eqm"),
        (
            irb_sheets.is_sme_expr(cols) | (placeable == "corporate_sme").fill_null(value=False)
        ).alias("_sme"),
        irb_sheets.is_financial_large_expr(cols).alias("_fse"),
        irb_sheets.is_commercial_expr(cols).alias("_comm"),
        (pl.col("sl_type") if "sl_type" in cols else pl.lit(None, dtype=pl.String)).alias("_sl"),
        (
            pl.col("output_floor_pct")
            if "output_floor_pct" in cols
            else pl.lit(None, dtype=pl.Float64)
        ).alias("_pct"),
    ).collect()

    # Equity method partition (PS1/26 Art. 147A / CRR Art. 155). Only PROVEN
    # IRB-method equity (irb_simple / pd_lgd) counts in the IRB total and the
    # "Equity IRB" disclosure; SA-method equity — and any equity leg whose method
    # the ledger did not seal (null) — stays in the SA breakdown. Under Basel 3.1
    # every equity leg is stamped ``sa`` (Art. 147A), so the IRB partition is
    # empty.
    equity_mask = collected["_approach"] == _EQUITY
    equity_irb_mask = equity_mask & collected["_eqm"].is_in(_EQUITY_IRB_METHODS).fill_null(
        value=False
    )
    equity_sa_mask = equity_mask & ~equity_irb_mask

    # SA class breakdown: SA approaches plus SA-method equity. IRB-method equity
    # is excluded here — it is not a SA class. The SA-CCR legs join via
    # ``_SA_APPROACHES``, so a derivative reports under its counterparty's
    # Art. 112 class — and, being SA, they are not swept into the IRB group-by
    # below.
    sa_mask = collected["_approach"].is_in(_SA_APPROACHES)
    # The equity approach is excluded from the IRB class group-bys entirely: it
    # reports at ``EQUITY_IRB`` and the IRB total, never a per-class IRB row.
    modelled = collected.filter(~sa_mask & ~equity_mask)
    multipliers = collected["_pct"].drop_nulls()
    return _Ledger(
        total=_sum(collected),
        final_total=float(collected["_final"].sum()),
        multiplier=float(multipliers[0]) if multipliers.len() else None,
        modelled_legs=modelled.height,
        by_approach={
            str(key[0]): amount for key, amount in _grouped(collected, "_approach").items()
        },
        sa_class={
            str(key[0]): amount
            for key, amount in _grouped(
                collected.filter(sa_mask | equity_sa_mask), "_ec_sa"
            ).items()
        },
        irb_class={
            (str(key[0]), str(key[1])): amount
            for key, amount in _grouped(modelled, "_approach", "_ec_irb").items()
        },
        irb_sub={
            (str(key[0]), str(key[1]), bool(key[2]), bool(key[3]), bool(key[4])): amount
            for key, amount in _grouped(
                modelled, "_approach", "_ec_irb", "_sme", "_fse", "_comm"
            ).items()
        },
        irb_sheet={
            (str(key[0]), str(key[1])): amount
            for key, amount in _grouped(modelled, "_approach", "_sheet").items()
        },
        slotting_type={
            str(key[0]): amount
            for key, amount in _grouped(
                modelled.filter(pl.col("_approach") == _SLOTTING), "_sl"
            ).items()
            if key[0] is not None
        },
        equity_sa=_sum(collected.filter(equity_sa_mask)),
        equity_irb=_sum(collected.filter(equity_irb_mask)),
    )


def _totals_only(results: pl.LazyFrame, *, own_col: str, final_col: str) -> _Ledger:
    """The ledger of a frame with no approach / class key: its totals."""
    totals = results.select(
        pl.col(own_col).fill_null(0.0).sum().alias("_own"),
        pl.col(final_col).fill_null(0.0).sum().alias("_final"),
    ).collect()
    return _Ledger(
        total=_Amount(own=float(totals["_own"][0])),
        final_total=float(totals["_final"][0]),
        has_breakdown=False,
    )


def _sum(frame: pl.DataFrame) -> _Amount:
    """Both measures of a collected population."""
    return _Amount(own=float(frame["_own"].sum()), standardised=float(frame["_sa"].sum()))


def _grouped(frame: pl.DataFrame, *keys: str) -> dict[tuple[object, ...], _Amount]:
    """Both measures of ``frame`` per distinct ``keys`` tuple."""
    grouped = frame.group_by(list(keys)).agg(
        pl.col("_own").sum().alias("_own"), pl.col("_sa").sum().alias("_sa")
    )
    return {
        tuple(row[key] for key in keys): _Amount(float(row["_own"]), float(row["_sa"]))
        for row in grouped.iter_rows(named=True)
    }


def _equity_method_expr(cols: set[str]) -> pl.Expr:
    """The sealed ``equity_method`` column, or a typed null when absent.

    ``equity_method`` is a conditional AGGREGATOR_EXIT column (R6) present only
    on runs carrying an equity book. Absent => equity-free run => the injected
    null never matches ``_EQUITY_IRB_METHODS``, so every (non-existent) equity
    leg is treated as SA.
    """
    if "equity_method" in cols:
        return pl.col("equity_method")
    return pl.lit(None, dtype=pl.String)


# =============================================================================
# Figures by slot
# =============================================================================


def _amounts_by_slot(ledger: _Ledger, framework: str) -> dict[rows.Slot, _Amount]:
    """Every figure of the template, keyed by what it is — not by where it goes."""
    by_approach = ledger.by_approach
    sa = _add(by_approach.get(approach, _NOTHING) for approach in _SA_APPROACHES)
    sa = sa + ledger.equity_sa
    firb = by_approach.get(_FIRB, _NOTHING)
    airb = by_approach.get(_AIRB, _NOTHING)
    slotting = by_approach.get(_SLOTTING, _NOTHING)
    # The IRB total carries IRB-method equity (Art. 155); SA-method equity stays
    # in the SA total. This keeps SA + IRB = credit risk under either routing.
    irb = firb + airb + slotting + ledger.equity_irb

    amounts = _irb_class_amounts(ledger, is_b31=framework == rows.FRAMEWORK_BASEL_3_1)
    amounts[rows.TOTAL] = ledger.total
    # Credit risk is the whole ledger (the only risk type in scope) in column
    # 0010. Its column 0020 is S-TREA as ``boe_b0716`` states it — the SA total
    # as reported plus the modelled book on SA — and not a second flat sum.
    amounts[rows.CREDIT_RISK] = _Amount(ledger.total.own, sa.own + irb.standardised)
    amounts[rows.SA] = sa
    amounts[rows.SA_CLASSES] = sa
    amounts[rows.SA_SPECIALISED_LENDING] = ledger.sa_class.get("specialised_lending", _NOTHING)
    amounts[rows.SA_SHORT_TERM_ASSESSMENT] = _NOTHING
    amounts[rows.IRB] = irb
    amounts[rows.AIRB] = airb
    amounts[rows.EQUITY_IRB] = ledger.equity_irb

    if rows.SLOTTING.ref(framework) is None:
        # C 02.00: slotting is specialised lending without own estimates
        # (module docstring).
        amounts[rows.FIRB] = firb + slotting
        amounts[rows.FIRB_SPECIALISED_LENDING] += slotting
        return amounts

    amounts[rows.FIRB] = firb
    amounts[rows.SLOTTING] = slotting
    for sl_type, slot in _SLOTTING_TYPE_SLOTS.items():
        amounts[slot] = ledger.slotting_type.get(sl_type, _NOTHING)
    return amounts


def _irb_class_amounts(ledger: _Ledger, *, is_b31: bool) -> dict[rows.Slot, _Amount]:
    """The F-IRB and A-IRB class figures, read top to bottom of the templates."""
    if is_b31:
        # One definition with OF 08 (module docstring): each row is the legs of
        # its sheet under the sheet's own approach — which, on the sheet F-IRB
        # specialised lending shares with slotting, leaves the slotting legs to
        # the slotting rows.
        return {
            sheet.slot: ledger.irb_sheet.get((sheet.approach, sheet.key), _NOTHING)
            for sheet in irb_sheets.B31_CLASS_SHEETS
        }

    def of_class(approach: str, exposure_class: str) -> _Amount:
        return ledger.irb_class.get((approach, exposure_class), _NOTHING)

    def of_retail(exposure_class: str, *, sme: bool) -> _Amount:
        return _add(
            amount
            for (leg_approach, leg_class, is_sme, _fse, _comm), amount in ledger.irb_sub.items()
            if leg_approach == _AIRB and leg_class == exposure_class and is_sme == sme
        )

    # CRR Art. 147(2)(c): corporates split on the class, as the C 08.01 sheets
    # do; retail real estate and other retail split by SME only.
    return {
        rows.FIRB_CENTRAL_GOVERNMENTS: of_class(_FIRB, "central_govt_central_bank"),
        rows.FIRB_INSTITUTIONS: of_class(_FIRB, "institution"),
        rows.FIRB_CORPORATES_SME: of_class(_FIRB, "corporate_sme"),
        rows.FIRB_SPECIALISED_LENDING: of_class(_FIRB, "specialised_lending"),
        rows.FIRB_CORPORATES_OTHER: of_class(_FIRB, "corporate"),
        rows.AIRB_CENTRAL_GOVERNMENTS: of_class(_AIRB, "central_govt_central_bank"),
        rows.AIRB_INSTITUTIONS: of_class(_AIRB, "institution"),
        rows.AIRB_CORPORATES_SME: of_class(_AIRB, "corporate_sme"),
        rows.AIRB_SPECIALISED_LENDING: of_class(_AIRB, "specialised_lending"),
        rows.AIRB_CORPORATES_OTHER: of_class(_AIRB, "corporate"),
        rows.AIRB_RETAIL_REAL_ESTATE_SME: of_retail("retail_mortgage", sme=True),
        rows.AIRB_RETAIL_REAL_ESTATE_NON_SME: of_retail("retail_mortgage", sme=False),
        rows.AIRB_RETAIL_QRRE: of_class(_AIRB, "retail_qrre"),
        rows.AIRB_RETAIL_OTHER_SME: of_retail("retail_other", sme=True),
        rows.AIRB_RETAIL_OTHER_NON_SME: of_retail("retail_other", sme=False),
    }


def _sa_class_rows(sa_class: dict[str, _Amount]) -> dict[str, _Amount]:
    """The Art. 112(1) class rows, by row code: every mapped row, zero if empty.

    Several classes share a row (``C02_00_SA_CLASS_MAP``) and ACCUMULATE.
    """
    class_rows: dict[str, _Amount] = dict.fromkeys(C02_00_SA_CLASS_MAP.values(), _NOTHING)
    for exposure_class, row_ref in C02_00_SA_CLASS_MAP.items():
        class_rows[row_ref] += sa_class.get(exposure_class, _NOTHING)
    return class_rows


def _add(amounts: Iterable[_Amount]) -> _Amount:
    """Sum of ``amounts``; nothing sums to nothing."""
    total = _NOTHING
    for amount in amounts:
        total = total + amount
    return total


# =============================================================================
# The output floor
# =============================================================================


def _output_floor(
    ledger: _Ledger, *, s_trea: float | None, summary: OutputFloorSummary | None
) -> _Floor:
    """The floor block, from what is actually known.

    x comes from the summary or, without one, the ledger's sealed
    ``output_floor_pct``. OF-ADJ comes from the summary alone. The floor needs
    both and S-TREA; the indicator needs the floor (Annex II row 0034: column
    0030 "equal to or greater than" column 0010, both on row 0010).
    """
    multiplier = summary.floor_pct if summary is not None else ledger.multiplier
    adjustment = summary.of_adj if summary is not None else None
    if multiplier is None or adjustment is None or s_trea is None:
        return _Floor(multiplier=multiplier, adjustment=adjustment)
    amount = multiplier * s_trea + adjustment
    return _Floor(
        multiplier=multiplier,
        adjustment=adjustment,
        amount=amount,
        activated=amount >= ledger.total.own,
    )


def _warn_if_the_engine_floor_differs(ledger: _Ledger, floor: _Floor) -> None:
    """WARN when the engine's post-floor total is not the template's TREA.

    The template's TREA is max(U-TREA, floor) — row 0010, columns 0010 and 0030;
    ``boe_b0560`` and its siblings take exactly that maximum. The engine floors
    the modelled subset alone (docs/plans/c07-ccr-derivatives.md §4 D6), so its
    total is higher whenever its floor binds on a book with SA exposures, and
    Pillar 3 OV1 discloses the engine's figure. Not an error channel: neither
    figure is this template's to correct, and silence would hide the gap.
    """
    add_on = ledger.final_total - ledger.total.own
    if floor.amount is None:
        if add_on > _TOLERANCE:
            logger.warning(
                "OF 02.00: the engine applied an output-floor add-on of %.2f, but the floor "
                "(row 0010 column 0030) cannot be stated without the OutputFloorSummary — "
                "OF-ADJ is not on the ledger",
                add_on,
            )
        return
    template_trea = max(ledger.total.own, floor.amount)
    if abs(ledger.final_total - template_trea) > _TOLERANCE:
        logger.warning(
            "OF 02.00: the engine's post-floor total (%.2f) differs from max(U-TREA %.2f, "
            "floor %.2f) by %.2f — the engine floors the modelled subset only",
            ledger.final_total,
            ledger.total.own,
            floor.amount,
            ledger.final_total - template_trea,
        )


# =============================================================================
# The stranding net
# =============================================================================


def _warn_if_a_breakdown_strands(
    amounts: dict[rows.Slot, _Amount], class_rows: dict[str, _Amount], framework: str
) -> None:
    """WARN when a total exceeds the detail rows the template breaks it into.

    The net for the impossible-pair trap ``irb_sheets.placeable_irb_class``
    describes, and for every figure whose slot has no row under this regime. That
    revert is
    deliberately narrow — it fixes only the Art. 151(4) pair we have measured —
    so any OTHER (approach, class) combination the template has no row for
    strands its RWEA out of the breakdown while the total still counts it, and
    NO published rule would notice: the rules only check rows that exist. This
    turns that silence into a log line naming the amount.

    Not an error channel: the figures published are still correct at the approach
    and Art. 92 totals, and a residual is a disclosure-granularity defect
    upstream of this template, not a miscalculation in it.
    """
    for total, details in rows.BREAKDOWNS:
        total_ref = total.ref(framework)
        if total_ref is None:
            continue
        placed = [detail for detail in details if detail.ref(framework) is not None]
        _warn_on_residual(
            total_ref,
            amounts.get(total, _NOTHING).own,
            [str(detail.ref(framework)) for detail in placed],
            sum(amounts.get(detail, _NOTHING).own for detail in placed),
        )
    layout_rows = rows.get_c02_00_cells(framework)
    reported = {ref: amount for ref, amount in class_rows.items() if ref in layout_rows}
    _warn_on_residual(
        str(rows.SA_CLASSES.ref(framework)),
        amounts[rows.SA_CLASSES].own,
        sorted(reported),
        sum(amount.own for amount in reported.values()),
    )


def _warn_on_residual(total_ref: str, total: float, detail_refs: list[str], detail: float) -> None:
    """Log one total that its detail rows do not account for."""
    residual = total - detail
    if abs(residual) <= _TOLERANCE:
        return
    logger.warning(
        "C 02.00: row %s (%.2f) exceeds its breakdown %s (%.2f) by %.2f — RWEA the "
        "template has no detail row for; it is counted in the total but absent from the "
        "of-which rows",
        total_ref,
        total,
        "+".join(detail_refs),
        detail,
        residual,
    )


# =============================================================================
# Row assembly
# =============================================================================


def _cells(
    amounts: dict[rows.Slot, _Amount],
    class_rows: dict[str, _Amount],
    floor: _Floor,
    framework: str,
    *,
    report_standardised: bool,
) -> dict[str, dict[str, float | None]]:
    """Row code -> column -> value, for every row this calculator computes.

    A slot with no row under ``framework`` is not placed anywhere. Which of a
    row's columns the published template actually has is applied last, in
    ``_build_rows`` — so a value prepared here for a cell the template lacks
    cannot be reported.
    """

    def values(amount: _Amount) -> dict[str, float | None]:
        return {
            rows.COL_ALL_APPROACHES: amount.own,
            rows.COL_STANDARDISED: amount.standardised if report_standardised else None,
        }

    cells: dict[str, dict[str, float | None]] = {
        row_ref: values(amount) for row_ref, amount in class_rows.items()
    }
    for slot, amount in amounts.items():
        row_ref = slot.ref(framework)
        if row_ref is not None:
            cells[row_ref] = values(amount)

    total_ref = rows.TOTAL.ref(framework)
    if total_ref is not None:
        cells[total_ref][rows.COL_OUTPUT_FLOOR] = floor.amount
    for slot, value in (
        (rows.FLOOR_ACTIVATED, None if floor.activated is None else float(floor.activated)),
        (rows.FLOOR_MULTIPLIER, floor.multiplier),
        (rows.FLOOR_ADJUSTMENT, floor.adjustment),
    ):
        row_ref = slot.ref(framework)
        if row_ref is not None:
            cells[row_ref] = {rows.COL_OUTPUT_FLOOR: value}
    return cells


def _build_rows(
    cells: dict[str, dict[str, float | None]], framework: str, column_refs: list[str]
) -> list[dict[str, object]]:
    """Lay ``cells`` out on the published template, row by row.

    A row not in ``cells`` is one this calculator computes nothing for and is
    empty. A column the published row has no cell in is empty whatever was
    prepared for it.
    """
    return [
        {
            "row_ref": row.ref,
            "row_name": row.label,
            **{
                ref: cells.get(row.ref, {}).get(ref) if ref in row.columns else None
                for ref in column_refs
            },
        }
        for _section, published in rows.get_c02_00_layout(framework)
        for row in published
    ]
