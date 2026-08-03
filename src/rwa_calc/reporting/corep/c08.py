"""
COREP C 08.01/02/03/04/05/06 — IRB credit risk, declarative.

Pipeline position:
    sealed aggregator-exit ledger -> _prepare() -> per-template TemplateSpecs
    (C 08.01 static rows; C 08.02 data-driven grade/PD-band rows; C 08.03/05
    sparse PD-range rows; C 08.04 fixed flow rows; C 08.06 per-SL-type
    category x maturity rows) -> cellspec.execute() -> dict[class, DataFrame]
    each. C 08.07 is a separate module (``corep/c08_07.py``).

Cell semantics (recorded decisions, this slice):

- All five dicts key the sealed ``reporting_class_origin`` (== raw
  ``exposure_class`` for IRB rows — the obligor basis, number-neutral
  convergence; no applied-class ladder and NO specialised-lending merge,
  unlike C 07.00). The population is the origin IRB book keyed on
  ``reporting_approach_origin`` (F-IRB / A-IRB / slotting); C 08.02/03/04/05
  exclude slotting per template. C 08.07 alone keeps the RAW class key
  (Art. 147 origination taxonomy over the FULL population).
- SLOTTING IS OUT OF SCOPE OF C 08.02 (recorded, evidenced): PS1/26 Annex II
  §3.3.4 paragraph 77A — "Institutions shall complete this template in respect
  of exposures subject to the AIRB approach and the FIRB approach, but not in
  respect of exposures subject to the slotting approach". §3.3.2 paragraph 76
  says the same structurally under BOTH frameworks — "CR IRB 2 provides a
  breakdown of total exposures assigned to obligor grades or pools (exposures
  reported under row 0070 of CR IRB 1)" — and C 08.01 row 0070 is the F-IRB/
  A-IRB union while slotting reports on row 0080 ("SPECIALISED LENDING SLOTTING
  APPROACH: TOTAL"). A slotting leg has no PD-derived obligor grade by
  construction (Art. 153(5)), so the retired behaviour banded the whole slotting
  book onto C 08.02's "Unassigned" residual row and broke the published
  cross-template identity ``{OF08.01 r0070} = sum({OF08.02})`` on every shared
  column (boe_b0752_*/boe_b0814_*). C 08.02 therefore reads ``_non_slotting``,
  exactly as C 08.03/05 already did — a slotting-only class emits NO C 08.02
  sheet at all.
- Col 0060 ("OTHER FUNDED CREDIT PROTECTION") reads the Art. 232(1) / Art. 200(1)
  carriers ONLY — protection treated as a guarantee, which acts on the obligor's
  PD through substitution. The Art. 199 collateral (immovable property,
  receivables, other physical) is NOT in this column: it is an LGD mitigant, and
  Annex II routes it by name to the CRM-in-LGD-estimates block at cols
  0190/0200/0210, where ``_value_cells`` already reports it. Summing it here too
  was a DOUBLE COUNT that drove col 0090 negative — the same defect and the same
  remedy as C 07.00 col 0080. The block (0040/0050/0060) is additionally CAPPED
  PER LEG at the original exposure pre-conversion factors, the excess shed
  proportionally (``irb_protection_exprs``, C 07.00's ``_block_cap_scale``
  precedent) — Annex II mandates that twice, though it is inert once the Art. 199
  collateral is out. Col 0070 (the outflow) is the already-capped SUBTOTAL of
  that block and so is not capped again. See the helper for the quoted
  instructions behind each of these.
- THE TWO CRM BLOCKS ARE MUTUALLY EXCLUSIVE, so cols 0150/0160 report a constant
  0.0 instead of restating cols 0040/0050 (which they did, behind the very same
  ``protection_type`` predicate, publishing every guarantee twice per sheet).
  Annex II splits unfunded protection by EFFECT — its cols 0150-0210 heading bars
  "the substitution effect of CRM techniques" outright — and PS1/26 by NAMED
  METHOD: 0040/0050 = Risk-Weight / Parameter Substitution, 0150/0160 = the
  Art. 183 LGD Adjustment Method, which ``engine/irb/guarantee.py`` never
  applies. The FUNDED half (0180-0210, Art. 197/199 collateral) still reports.
  Rationale, evidence and the col 0220 double-default residual: see the pin
  ``test_c08_crm_substitution.py::TestCrmInLgdBlockExcludesSubstitutedProtection``.
- The CRM SUBSTITUTION BLOCK IS A TWO-STEP WATERFALL — the C 07.00 shape
  (``corep/c07.py::_substitution_outflow`` / ``::_net_after_substitution``) on
  the IRB surface, written to the published identities rather than re-derived:
  ``0070 = 0040 + 0050 + 0060`` (live ``v1663_m`` / ``v1665_m``, BoE
  ``boe_b0747`` / ``boe_b0761``) then ``0090 = 0020 - 0035 - 0070 + 0080``
  (``v1662_m`` / live ``v0347_m``, BoE ``boe_b0746`` / ``boe_b0760``; published
  additively over the reported signs, where 0035/0070 are "(-)" deductions).
  What this replaced were two reproduced defects: col 0070 was an INDEPENDENT
  ``Sum(guaranteed_portion)`` gated on the guarantor's class DIFFERING from the
  obligor's — so a same-class guarantee reported a populated col 0040 against
  ``0070 = 0``, a flat breach of ``v1663_m``, and Art. 232 other funded
  protection never reached the outflow at all — and col 0090 then subtracted the
  breakdown AND the subtotal, deducting every covered part twice. Col 0070 binds
  the per-leg subtotal ``irb_protection_exprs`` derives (``c08_prot_block``),
  so the first identity holds by construction however the frame degrades, and it
  stays a value binding rather than a ``Formula`` so col 0090 may reference it —
  the executor refuses a formula that references a formula. The B31-only col 0035
  term is row-scoped; see ``crm_substitution.C08_01_NETTING_EXEMPT_ROWS``.
- The INFLOW side (col 0080) is routed ACROSS templates by
  ``corep/crm_substitution.py``, over the whole population and keyed on the
  sealed post-substitution approach: an inflow whose substituted leg is treated
  under SA belongs on C 07.00, not here. Reading it off this template's own
  IRB-filtered frame dropped a sovereign-guaranteed IRB corporate loan's inflow
  entirely (Annex II: "Exposures stemming from possible in- and outflows from
  and to other templates shall be taken into account"). The C 08.01 sheet axis
  is the UNION of the classes present in the IRB book and the classes receiving
  an inflow, so a guarantor class with no native IRB exposure still has a sheet
  to land on. That module's docstring records the one residual this leaves —
  col 0060's Art. 232 limb produces an outflow with no destination class — as a
  named follow-up rather than hiding it behind a re-gated col 0070.
- C 08.01/02 share one value surface (computed framework-agnostic, filtered
  by each framework's column refs): gross exposures, that CRM waterfall over
  POSITIVE magnitudes,
  the cross-sheet substitution inflow (0080, C 08.01 Total row only; C 08.02 excludes it) via
  ``ReportingContext.substitution_inflow``, the two "of which: off balance
  sheet" memo columns on their RECORDED bases (R11): 0100 (POST-CRM PRE-CCF
  group) = the off-BS slice of the 0090 waterfall, derived per row in
  ``_c08_off_bs_pre_ccf`` over ``c08_bs == "off"`` legs (the 0080 inflow is
  excluded — a total-row cross-sheet scalar with no leg-level BS attribution);
  0120 (EXPOSURE VALUE post-CCF group) = Sum(ead_final) over the off-BS legs,
  the after-all-CRM total 0104 (= 0090 + 0101 + 0102 on the REPORTED signs,
  ``_c08_after_all_crm``; another post-execute pass because the executor refuses a
  formula that references a formula and all three inputs are ``Formula`` cells),
  EAD-weighted PD/LGD, maturity
  in DAYS (x365 — ``irb_maturity_m`` is years despite the suffix), LFSE
  sub-splits gated on ``cp_apply_fi_scalar`` presence, defaulted sub-splits
  via the retired detection ladder, CRR supporting-factor deltas (the
  asymmetric dedicated flag names preserved), B31 adjustment/output-floor
  columns, and the provisions ladder (SCRA/GCRA sums falling back, when they
  net to ~0, to ``provision_held`` if the frame carries it else the sealed
  ``provision_allocated`` — R10b; a value-dependent PER-CELL branch applied as
  a module post-step). The Annex II §1.3 "(-)" negation covers
  the CRM substitution outflows 0040/0050/0060/0070 (both frameworks), B31's
  on-BS netting adjustment 0035 and slotting FCCM adjustments 0102/0103
  (structural-null today), the CRR supporting-factor adjustments 0256/0257,
  and provisions 0290 — applied AFTER the CRM waterfall (0090) has consumed
  the positive magnitudes, with a zero deduction normalised to ``+0.0``.
  Lineage-instrumented (R23): ``c08_01_plans`` / ``c08_02_plans`` expose the
  per-class execution plans, passing ``_NEGATIVE_COLS`` explicitly so the
  drill-down's sign-aware reconciliation holds on the negated columns (0256
  non-zero on corporate_sme). C 08.01's plans thread the real per-class
  substitution inflow, so the Total-row col 0080 (``SideContext``) drills to its
  real value (the C 07.00 pattern); C 08.02's per-grade 0080 is a constant 0.0
  (R12) and its String label col 0005 is skipped by the tie-out value-column sweep.
  Ratchet note (R23/R24): each extraction bumped ``max_reporting_module_loc``
  (2016 -> post-R23 -> 2320 post-R24, zero slack) — the mechanical additive
  cost of exposing each template's cells/plans builders with their mandated
  docstrings, no behaviour change. Unlike the c07/cr4/cr8/cr7a extractions this
  module alone needs a bump per wave: it hosts SEVEN templates in one file.
  R24 added the ``c08_03_plans`` / ``c08_05_plans`` / ``c08_06_plans`` builders
  (and split ``_c08_03_cells`` / ``_c08_05_cells`` and the c08_06 row helpers
  out of their generators). Splitting c08.py per-template is the honest
  long-term answer — recorded as a deferred follow-up (shared value surface,
  its own risky item).
- The EL memo columns 0280 (pre post-model adjustment) and its B31 twin 0282
  (after post-model adjustments) coalesce PER LEG (R10a): they read the
  formula-IRB ``el_pre_adjustment`` / ``el_after_adjustment`` where non-null
  else the base ``expected_loss``. The adjustment columns exist whenever ANY
  formula-IRB leg exists in the run but are NULL on slotting legs (their EL
  comes from the slotting calculator, on ``expected_loss``), so the retired
  Sum-with-null-fill reported a masked 0.0 for slotting EL on those sheets
  while C 08.06 col 0090 (Sum ``expected_loss``) reported it correctly; the
  coalesce is a value no-op on formula-IRB legs (el_pre == expected_loss
  there) and surfaces the real slotting EL on slotting legs. The aggregator
  injects ``el_pre_adjustment`` onto the sealed frame under BOTH frameworks
  (CRR's ``apply_post_model_adjustments`` copies expected_loss into it), so
  the coalesce corrects 0280 for either framework's slotting sheets; B31 alone
  additionally carries 0282 (``el_after_adjustment``). The derived
  ``c08_el_pre`` / ``c08_el_after`` columns are built in ``_prepare``.
- C 08.02's rows are data-driven (distinct firm grades when
  ``cp_internal_rating_grade`` has values, else the populated fixed PD
  bands, plus an "Unassigned" residual); ``row_ref == row_name == the
  String column 0005``, injected post-execute — the CR9.1 pattern.
- RECORDED DECISION (R12) — the cross-class substitution INFLOW (col 0080,
  and hence its contribution to the 0090 waterfall) is kept off every GRADE row
  of C 08.02, landing instead on its residual "Unassigned" row. Two facts about
  the sealed origin-basis ledger make per-grade attribution unsound:
  (i) C 08 keys ``reporting_class_origin`` (the obligor basis — a recorded
  number-neutral convergence decision), so a guaranteed leg substituted from
  class X into class Y physically sits in X's ORIGIN sheet, reported there as
  an OUTFLOW (col 0070) at the OBLIGOR's grade — the inflow into Y is made of
  legs that live in OTHER sheets, never in Y's partition; (ii) that leg carries
  the OBLIGOR's ``pd_floored`` / ``cp_internal_rating_grade``, NEVER the
  guarantor's — IRB parameter substitution computes the guarantor RW/EL inside
  a local swap-restore window without overwriting the leg's own PD/grade
  (``engine/irb/guarantee.py::_apply_parameter_substitution``), and under CRR
  the guarantor is SA-RW-substituted with no guarantor PD grade at all. The
  inflow into Y is a per-destination-class SCALAR
  (``ReportingContext.substitution_inflow``, ``corep/crm_substitution.py``
  grouped by ``post_crm_exposure_class_guaranteed``) that C 08.01 lands on its
  constraint-free Total row (0010) and on one row of each of its two published
  row decompositions.
  R12's CONCLUSION IS SUPERSEDED; ITS REASONING IS NOT. Four live ERROR rules —
  ``boe_b0752_8`` / ``boe_b0814_07`` (col 0080) and ``boe_b0752_9`` /
  ``boe_b0814_08`` (col 0090), two distinct identities each stated twice in the
  pack — require ``{OF08.01 r0070} = sum({OF08.02})`` on those columns. Together
  with ``boe_b0745`` / ``v0338_m`` (which put the inflow on row 0070) that is a
  published statement that C 08.02 MUST carry the inflow, so "excluded entirely"
  was never available and the MONITORED divergence R12 recorded here was in fact
  a standing breach of four ERROR-severity rules. What survives is the reason
  per-GRADE attribution is unsound — the ledger carries the obligor's grade,
  never the guarantor's — and that is precisely why the inflow lands on the
  residual "Unassigned" row (``_C08_02_INFLOW_ROW``) rather than on any grade:
  the row already means "an exposure whose grade we do not carry", which is
  exactly what a cross-sheet inflow is. C 08.02 takes the GRADED component only
  (it excludes slotting, and the tie-out is against C 08.01 row 0070, the
  F-IRB/A-IRB union). Sealing the GUARANTOR's rating grade per leg remains the
  enhancement that would allow a true per-grade split. Regulatory basis: Reg (EU)
  2021/451 Annex II (C 08.01/02 share the CRM-substitution column block);
  PS1/26 Annex XXII (obligor-basis reporting bars substitution effects from the
  grade breakdown — which the Unassigned landing respects, since it asserts no
  grade). Pin:
  ``tests/unit/reporting/corep/test_c08_02.py::TestC0802InflowLandsOnUnassignedRow``.
- C 08.03/05 allocate rows over the 17 fixed PD ranges (B31 allocates on
  the pre-input-floor ``pd``, CRR on ``pd_floored``; the reported PD is
  always post-floor), emit ONLY populated buckets (sparse) plus an
  optional 9999 "Unassigned" row. C 08.03's on/off-BS gross columns
  (0010/0020) Sum the sealed per-side gross carriers
  (``reporting_gross_on_bs`` / ``reporting_gross_off_bs``) over the band with a
  member-only predicate — the carriers are row-level and null outside their
  side, so a band with no off-BS rows sums 0.0 naturally (the retired
  whole-bucket fallback is gone). C 08.05's averages are null-filled arithmetic
  means (weighted by a constant-one column), with the CR9-style point-in-time
  fallbacks for the prior-year/historical carriers.
  Lineage-instrumented (R24): ``c08_03_plans`` / ``c08_05_plans`` expose the
  per-class sparse-PD-range plans (the data-driven c08_02 pattern; each row keys
  the derived ``c08_pd_range`` leaf band — or ``c08_pd_parent`` for the four
  hierarchical parent bands — carried in ``row_terms``). C 08.05 is
  execute-only (R13 deleted the rate postfix). C 08.03 has ONE post-execute pass
  (the provisions ladder on col 0110), on the reported frame the drill-down reads;
  cols 0010/0020 need none.
- C 08.04 is the CR8-clone flow: only the closing-RWEA cell (row 0090) is
  populated — note its DELIBERATELY two-wide RWA ladder (``rwa_final``,
  ``rwa`` — no ``rwa_post_factor``). Lineage-instrumented (R22): ``c08_04_plans``
  exposes the per-class current-period plans (no prior frame), so its opening
  (row 0010, a ``PriorPeriod`` cell) and residual (row 0080, a ``Formula``
  deriving from it) rows are refused by the drill-down exactly as CR8 refuses
  its rows 1/8; the reported ``generate_c08_04`` keeps threading the prior
  frame.
- C 08.06 keys per-SL-type sheets (CRR's IPRE absorbs HVCRE when
  ``is_hvcre`` exists; B31 splits HVCRE out; empty SL types emit NO sheet)
  over the slotting-only book, with a per-ROW two-branch policy: empty
  non-Total rows zero-fill (0070 = the fixed display risk weight from the
  row definition), live rows and both maturity-split Total rows compute on
  data (0050/0060/0070/0031 null where the retired code reported None).
  CRR's 0080 prefers ``rwa_post_factor``; the maturity fallback is
  asymmetric (no ``is_short_maturity`` column -> short band empty, long
  band absorbs the category); the "substantially stronger" sub-rows are
  unconditionally empty. Lineage-instrumented (R24): ``c08_06_plans`` exposes
  the per-SL-type plans, and because the row set is number-neutral but the
  EMPTY-row set is per-sheet, each sheet gets its OWN spec — an empty non-Total
  row's col 0070 (a fixed display RW, not a measured weighted average) is left
  UNBOUND (``_c08_06_empty_refs``), so the drill-down reports the template's
  empty policy and reads its value from the reported frame rather than a
  WeightedAvg with no legs. The three value-dependent post-passes (empty-row
  zero-fill; the live 0030/0040/0070 fixes; the provisions ladder) stay on the
  reported frame.
- C 08.07 / OF 08.07 lives in its own module (``corep/c08_07.py``): it shares
  none of the C 08.01/02 value surface, reads the FULL population rather than
  the IRB book, and is the one COREP sheet keyed on the RAW ``exposure_class``.

References:
- CRR Art. 142-191 (IRB); Art. 153 (risk weights), Art. 180 (PD
  validation), Art. 501/501a (supporting factors); Reg (EU) 2021/451
  Annex I/II (C 08.0x); PRA PS1/26 Annex I/II (OF 08.0x)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import polars as pl
from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Count,
    Formula,
    PriorPeriod,
    RowPredicate,
    SafeSum,
    SideContext,
    Sum,
    TemplateSpec,
    WeightedAvg,
    execute,
    matched_counts,
    subset_rows,
)
from rwa_calc.reporting.corep.crm_substitution import (
    C08_01_NETTING_EXEMPT_ROWS,
    IRB_BLOCK_COL,
    IRB_OFCP_CARRIERS,
    InflowBreakdown,
    crm_waterfall,
    irb_origin_inflows,
    irb_protection_exprs,
    waterfall_refs,
)
from rwa_calc.reporting.corep.pd_scale import banded_rows
from rwa_calc.reporting.corep.templates import (
    C08_04_ROWS,
    C08_06_CATEGORY_MAP,
    PD_BANDS,
    get_c08_02_columns,
    get_c08_03_columns,
    get_c08_04_columns,
    get_c08_05_columns,
    get_c08_06_columns,
    get_c08_06_rows,
    get_c08_06_sl_types,
    get_c08_columns,
    get_irb_row_sections,
)
from rwa_calc.reporting.kernel import (
    available_columns,
    pick,
    safe_sum,
)
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.plans import SheetPlan

if TYPE_CHECKING:
    from collections.abc import Mapping

# Annex II §1.3 "(-)"-labelled deduction columns on the C 08.01/02 surface,
# negated post-execute (AFTER the CRM waterfall consumes positive magnitudes):
# the CRM substitution outflows 0040/0050/0060/0070 (both frameworks), B31's
# on-balance-sheet netting adjustment 0035, B31's slotting financial-collateral
# adjustments 0102/0103 (structural-null today — the negation is a no-op that
# keeps the sign truthful if a carrier is ever wired), the CRR supporting-factor
# adjustments 0256/0257, and value adjustments/provisions 0290. The set is
# framework-guarded by intersection with the frame's columns in ``_negate`` —
# 0035/0102/0103 (B31-only) and 0256/0257 (CRR-only) are absent no-ops in the
# other regime.
_NEGATIVE_COLS: frozenset[str] = frozenset(
    {"0035", "0040", "0050", "0060", "0070", "0102", "0103", "0256", "0257", "0290"}
)

_IRB_APPROACHES: tuple[str, ...] = ("foundation_irb", "advanced_irb", "slotting")

# Which ``ReportingContext`` inflow component each C 08.01 row's col 0080 takes.
# The Total row 0010 takes the whole inflow; rows 0020/0030 take its balance-sheet
# split. Both are needed: row 0010 is decomposed TWICE over the same columns by
# live ERROR rules — ``boe_b0744`` on the balance-sheet axis (r0020+r0030+r0040+
# r0050+r0060) and ``boe_b0745`` / EBA ``v0338_m`` on the IRB treatment axis
# (r0070+r0080+r0170+r0180) — and a Total-row-only inflow breached BOTH by exactly
# the inflow on cols 0080/0090/0104 (measured on the CRM-substitution portfolio,
# not inferred). The balance-sheet split is unambiguous: the side is a property of
# the underlying asset and substitution does not change it.
#
# ROWS 0070/0080 CARRY THE TREATMENT SPLIT, and binding them is only coherent
# BECAUSE C 08.02 now carries the inflow too. Four live ERROR rules —
# ``boe_b0752_8`` / ``boe_b0814_07`` (col 0080) and ``boe_b0752_9`` /
# ``boe_b0814_08`` (col 0090), two distinct identities each stated twice in the
# pack — require ``{OF08.01 r0070} = sum({OF08.02})`` on those columns. So the
# published set jointly demands that the inflow reach row 0070 AND that the
# C 08.02 grade rows sum to it: binding row 0070 alone would fix ``boe_b0745`` /
# ``v0338_m`` and break both identities. See ``_C08_02_INFLOW_ROW``.

# The C 08.02 row the substitution inflow lands on — the residual "Unassigned"
# grade bucket ``_c08_02_keyed`` already emits for legs with no rating grade.
#
# WHY THAT ROW AND NOT A GRADE (recorded decision R12, superseded in its
# conclusion but not in its reasoning). R12 kept C 08.02 inflow-free because the
# origin-basis ledger carries the OBLIGOR's grade and never the guarantor's, so a
# per-grade split would misattribute the inflow to a foreign obligor's grade in a
# different class's rating scale. That reasoning is intact and is exactly why the
# inflow does NOT go on a grade row. What R12 got wrong was the conclusion that it
# therefore goes nowhere: the four tie-out rules above are a published statement
# that C 08.02 must sum to C 08.01 row 0070 on cols 0080/0090, so "nowhere" is not
# available. The Unassigned residual row states precisely what is known — an
# exposure whose grade the ledger does not carry — without inventing a grade it
# does not have, which is the same thing the row already means for a leg with a
# null ``cp_internal_rating_grade``. A destination class with no unassigned-grade
# legs of its own has the row added for the inflow (``c08_02_plans``).
_C08_02_INFLOW_ROW: str = "Unassigned"

_C08_01_INFLOW_KEYS: dict[str, str] = {
    "0010": "substitution_inflow",
    "0020": "substitution_inflow_on_bs",
    "0030": "substitution_inflow_off_bs",
    "0070": "substitution_inflow_graded",
    "0080": "substitution_inflow_slotting",
}

# Single-frame lineage key: C 08.07 has no sheet axis, so its one plan keys
# under a canonical name (see reporting.plans / _resolve_sheet_key single_frame).
_C08_07_SHEET_KEY = "c08_07"


_Terms = tuple[tuple[str, str | bool], ...]
type _EmptyCell = Literal["zero", "null"]


class _Row:
    """Minimal TemplateRow for data-driven row axes."""

    __slots__ = ("name", "ref")

    def __init__(self, ref: str, name: str) -> None:
        self.ref = ref
        self.name = name


def _const(value: float | None):  # noqa: ANN202 - tiny Formula factory
    def fn(_cells: Mapping[str, float | None], _prior: bool) -> float | None:
        return value

    return fn


def _copy_of_0040(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    return cells["0040"]


def _observed_rate(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """C 08.05 col 0040 = col 0030 / col 0020 as rendered (0.0 when no obligors).

    The denominator is col 0020 — the obligor count at the start of the
    observation period (prior-year cohort when ``prior_year_obligor_count`` is
    supplied, else the current-period fallback col 0020 itself reports). Col
    0030 (defaulted during the year) over col 0020 is the accepted cross-period
    proxy for the observed default rate; keeping the denominator equal to col
    0020 makes the disclosure internally consistent (Annex II C 08.05).
    """
    obligors = cells["0020"] or 0.0
    if obligors <= 0:
        return 0.0
    return (cells["0030"] or 0.0) / obligors


def _c08_04_other_flow(cells: Mapping[str, float | None], prior_available: bool) -> float | None:
    """C 08.04 row 0080 (Other) = closing(0090) - opening(0010) with a prior
    period, else null (the CR8 row-8 convention; a None side coerces to zero —
    PS1/26 Annex XXII paragraph 11)."""
    if not prior_available:
        return None
    return (cells["0090"] or 0.0) - (cells["0010"] or 0.0)


# =============================================================================
# Shared population + derived discriminators
# =============================================================================


def _irb_population(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    """The IRB book (retired _filter_by_irb_approach): F-IRB/A-IRB/slotting."""
    approach_col = pick(cols, "reporting_approach_origin")
    if approach_col is None:
        return results.filter(pl.lit(value=False))
    return results.filter(pl.col(approach_col).is_in(list(_IRB_APPROACHES)))


def _prepare(data: pl.DataFrame, cols: set[str]) -> pl.DataFrame:
    """Add the module-derived discriminator columns (each only when its
    sources exist — underived columns make their tolerant terms match
    nothing, reproducing the retired absent-column behaviour)."""
    exprs: list[pl.Expr] = [pl.lit(1.0).alias("c08_one")]

    # Defaulted ladder (retired _filter_defaulted precedence).
    if "is_defaulted" in cols:
        exprs.append(pl.col("is_defaulted").fill_null(value=False).alias("c08_defaulted"))
    elif "default_status" in cols:
        exprs.append((pl.col("default_status") == True).alias("c08_defaulted"))  # noqa: E712
    elif "exposure_class_applied" in cols or "exposure_class" in cols:
        class_col = (
            "exposure_class_applied" if "exposure_class_applied" in cols else "exposure_class"
        )
        exprs.append((pl.col(class_col) == "defaulted").alias("c08_defaulted"))
    elif "pd_floored" in cols:
        exprs.append((pl.col("pd_floored") >= 1.0).alias("c08_defaulted"))

    # On/off-balance-sheet (kernel rule: bs_type preferred, else exposure_type).
    if "bs_type" in cols:
        exprs.append(
            pl.when(pl.col("bs_type") == "ONB")
            .then(pl.lit("on"))
            .when(pl.col("bs_type") == "OFB")
            .then(pl.lit("off"))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("c08_bs")
        )
    elif "exposure_type" in cols:
        exprs.append(
            pl.when(pl.col("exposure_type") == "loan")
            .then(pl.lit("on"))
            .when(pl.col("exposure_type").is_in(["facility", "contingent", "facility_undrawn"]))
            .then(pl.lit("off"))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("c08_bs")
        )

    # Supporting-factor RWEA delta (CRR cols 0256/0257).
    if "rwa_pre_factor" in cols:
        rwa_source = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
        if rwa_source is not None:
            exprs.append(
                (pl.col("rwa_pre_factor").fill_null(0.0) - pl.col(rwa_source).fill_null(0.0)).alias(
                    "c08_sf_delta"
                )
            )

    # B31 section-3 unrated-corporate discriminators (retired
    # _filter_section3_unrated_corp / _filter_section3_unrated_ig).
    if "exposure_class" in cols:
        corp = (
            pl.col("exposure_class").str.contains("corporate", literal=True).fill_null(value=False)
        )
        unrated = pl.col("sa_cqs").is_null() if "sa_cqs" in cols else pl.lit(value=True)
        exprs.append((corp & unrated).alias("c08_unrated_corp"))
        if "cp_is_investment_grade" in cols:
            ig = pl.col("cp_is_investment_grade").fill_null(value=False) == True  # noqa: E712
            exprs.append((corp & unrated & ig).alias("c08_unrated_ig"))
        elif "pd_floored" in cols:
            exprs.append((corp & unrated & (pl.col("pd_floored") <= 0.005)).alias("c08_unrated_ig"))

    # Col 0280/0282 expected-loss coalesce (R10a). The formula-IRB post-model-
    # adjustment EL columns (``el_pre_adjustment`` / ``el_after_adjustment``,
    # engine/irb/adjustments.py::apply_post_model_adjustments) are produced ONLY
    # on the formula-IRB leg, so they are NULL on slotting legs — whose real EL
    # rides on ``expected_loss`` (from the slotting calculator). A plain
    # Sum("el_pre_adjustment") fills those slotting nulls to 0.0, masking the
    # slotting EL that C 08.06 col 0090 reports correctly as Sum("expected_loss").
    # A PER-LEG coalesce reports the formula-IRB adjustment EL where present, else
    # the base expected_loss — a value no-op on formula-IRB legs (el_pre_adjustment
    # == expected_loss there) that surfaces the true slotting EL on slotting legs.
    if "el_pre_adjustment" in cols:
        exprs.append(
            (
                pl.coalesce("el_pre_adjustment", "expected_loss")
                if "expected_loss" in cols
                else pl.col("el_pre_adjustment")
            ).alias("c08_el_pre")
        )
    if "el_after_adjustment" in cols:
        exprs.append(
            (
                pl.coalesce("el_after_adjustment", "expected_loss")
                if "expected_loss" in cols
                else pl.col("el_after_adjustment")
            ).alias("c08_el_after")
        )

    # Col 0251 RWEA-pre-adjustments coalesce — the R10a EL pattern, same cause.
    # ``rwa_pre_adjustments`` (engine/irb/adjustments.py::apply_post_model_adjustments)
    # is produced ONLY on the formula-IRB leg, so it is NULL on slotting legs. A plain
    # Sum fills those nulls to 0.0, and OF 08.01/02 then report col 0251 (RWEA PRE
    # adjustments) as 0.0 against a populated col 0260 (RWEA AFTER adjustments) —
    # breaking ``{c0260} = sum({c0251;0252;0253;0254})`` (boe_b0751/boe_b0763) on
    # every slotting row. A PER-LEG coalesce reports the formula-IRB pre-adjustment
    # RWEA where present, else the leg's own RWEA: a value no-op on formula-IRB legs,
    # and correct on slotting legs, which carry NONE of the three Art. 153(5A)/154(4A)
    # adjustments cols 0252-0254 report (PS1/26 Annex II makes this explicit for col
    # 0254 — "This column shall not be reported for sheets relating to the FIRB
    # approach or the slotting approach"), so their 0260 == 0251 by construction.
    if "rwa_pre_adjustments" in cols:
        rwa_fallback = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
        exprs.append(
            (
                pl.coalesce("rwa_pre_adjustments", rwa_fallback)
                if rwa_fallback is not None
                else pl.col("rwa_pre_adjustments")
            ).alias("c08_rwa_pre_adj")
        )

    exprs.extend(irb_protection_exprs(cols))

    return data.with_columns(exprs)


# =============================================================================
# The shared C 08.01/02 value surface
# =============================================================================


def _lfse_cell(
    cols: set[str],
    binding_factory,  # noqa: ANN001 - a zero-arg ValueBinding factory
    terms: _Terms,
    *,
    empty: _EmptyCell = "zero",
) -> CellSpec:
    """LFSE sub-split cells: bound over ``cp_apply_fi_scalar == True`` when
    the flag column exists (empty LFSE subsets report 0.0), else the
    recorded constant-None."""
    if "cp_apply_fi_scalar" not in cols:
        return CellSpec(Formula(refs=(), fn=_const(None)))
    return CellSpec(
        binding_factory(),
        predicate=RowPredicate(equals=(*terms, ("cp_apply_fi_scalar", True))),
        empty_cell=empty,
    )


def _sf_adjustment_cell(terms: _Terms, cols: set[str], dedicated: str, flag_col: str) -> CellSpec:
    """CRR supporting-factor adjustment: Σ(rwa_pre_factor - rwa) over the
    applied rows; None when no carrier. ``dedicated`` preserves the retired
    asymmetric flag names."""
    if "rwa_pre_factor" not in cols:
        return CellSpec(Formula(refs=(), fn=_const(None)))
    if dedicated in cols:
        return CellSpec(
            Sum("c08_sf_delta"), predicate=RowPredicate(equals=(*terms, (dedicated, True)))
        )
    if flag_col in cols and "supporting_factor_applied" in cols:
        return CellSpec(
            Sum("c08_sf_delta"),
            predicate=RowPredicate(
                equals=(*terms, (flag_col, True), ("supporting_factor_applied", True))
            ),
        )
    return CellSpec(Formula(refs=(), fn=_const(None)))


def _value_cells(  # noqa: C901, PLR0915 - the full C 08.01/02 column surface
    terms: _Terms,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    column_refs: tuple[str, ...],
    *,
    inflow_key: str | None,
    netting_in_waterfall: bool,
) -> dict[str, CellSpec]:
    member = RowPredicate(equals=terms)
    refs_0090 = waterfall_refs(column_refs, netting=netting_in_waterfall)

    def narrowed(*extra: tuple[str, str | bool]) -> RowPredicate:
        return RowPredicate(equals=(*terms, *extra))

    lgd_col = pick(cols, "lgd_floored", "lgd_input")
    # The substitution block (0040/0050/0060) reads the Annex II-capped twins
    # ``irb_protection_exprs`` derives; col 0070 (the outflow) stays RAW — see
    # that helper for why it is outside the cap block. A frame with no raw
    # carrier gets no twin, so the raw name is kept and behaviour is unchanged.
    gp_col = "c08_prot_guaranteed" if "guaranteed_portion" in cols else "guaranteed_portion"
    prot_cols = tuple(f"c08_prot_{col}" if col in cols else col for col in IRB_OFCP_CARRIERS)
    cells: dict[str, CellSpec] = {
        "0010": CellSpec(
            WeightedAvg("pd_floored", weight=ead_col), predicate=member, empty_cell="null"
        ),
        "0020": CellSpec(
            SafeSum(("reporting_gross_on_bs", "reporting_gross_off_bs")), predicate=member
        ),
        "0030": _lfse_cell(
            cols, lambda: SafeSum(("reporting_gross_on_bs", "reporting_gross_off_bs")), terms
        ),
        "0035": CellSpec(Sum("on_bs_netting_amount"), predicate=member),
        "0040": (
            CellSpec(Sum(gp_col), predicate=narrowed(("protection_type", "guarantee")))
            if "protection_type" in cols
            else CellSpec(Sum(gp_col), predicate=member)
        ),
        "0050": (
            CellSpec(
                Sum(gp_col),
                predicate=narrowed(("protection_type", "credit_derivative")),
            )
            if "protection_type" in cols
            else CellSpec(Formula(refs=(), fn=_const(0.0)))
        ),
        "0060": CellSpec(SafeSum(prot_cols), predicate=member),
        # 0070 (the substitution OUTFLOW) binds the per-leg subtotal of the block
        # above it, so ``{c0070} = {c0040} + {c0050} + {c0060}`` (live rules
        # ``v1663_m`` / ``v1665_m``) holds by construction — see the module
        # docstring for the class-change-gated Sum this replaced. A value
        # binding, not a Formula, so col 0090 may reference it.
        "0070": CellSpec(Sum(IRB_BLOCK_COL), predicate=member),
        # 0080 (the substitution INFLOW) lands on the Total row AND on one row of
        # each published decomposition of it — ``boe_b0744`` (balance-sheet axis,
        # rows 0020/0030) and ``boe_b0745`` / ``v0338_m`` (IRB treatment axis, rows
        # 0070/0080). Both are live ERROR rules and both are stated over the same
        # columns, so a Total-row-only inflow breaches each by exactly the inflow.
        # ``inflow_key`` names which component this row takes; None = a row outside
        # both decompositions, which reports the recorded constant 0.0.
        "0080": (
            CellSpec(SideContext(inflow_key))
            if inflow_key is not None
            else CellSpec(Formula(refs=(), fn=_const(0.0)))
        ),
        "0090": CellSpec(Formula(refs=refs_0090, fn=crm_waterfall)),
        # 0100 ("of which: off balance sheet") sits in the POST-CRM PRE-CCF
        # group (the 0090 waterfall), so it is the off-BS slice of that
        # pre-conversion-factor quantity — filled by ``_c08_off_bs_pre_ccf``
        # post-execute (the executor has no intra-row sub-waterfall verb). The
        # placeholder null is what an inert row keeps (R11).
        "0100": CellSpec(Formula(refs=(), fn=_const(None))),
        "0101": CellSpec(Formula(refs=(), fn=_const(None))),
        "0102": CellSpec(Formula(refs=(), fn=_const(None))),
        "0103": CellSpec(Formula(refs=(), fn=_const(None))),
        # 0104 ("exposure after ALL CRM pre-conversion factors") = the 0090
        # waterfall adjusted for the slotting FCCM columns — filled by
        # ``_c08_after_all_crm`` post-execute, because 0090/0101/0102 are all
        # Formula cells and the executor forbids a formula referencing a formula.
        # The placeholder null is what an inert row keeps (the 0100 convention).
        "0104": CellSpec(Formula(refs=(), fn=_const(None))),
        "0110": CellSpec(Sum(ead_col), predicate=member),
        # 0120 ("of which: off balance sheet") sits in the EXPOSURE VALUE
        # (post-CCF) group, so it is Sum(ead_final) over the off-BS legs —
        # exactly the basis the old 0100 carried before R11 moved it here.
        "0120": CellSpec(Sum(ead_col), predicate=narrowed(("c08_bs", "off"))),
        "0125": CellSpec(Sum(ead_col), predicate=narrowed(("c08_defaulted", True))),
        "0130": CellSpec(Formula(refs=(), fn=_const(None))),
        "0140": _lfse_cell(cols, lambda: Sum(ead_col), terms),
        # 0150/0160: the CRM-in-LGD twins of cols 0040/0050, mutually exclusive
        # with them and empty on today's calculator (module docstring). The
        # recorded constant 0.0 is the convention cols 0170-0173 already follow.
        "0150": CellSpec(Formula(refs=(), fn=_const(0.0))),
        "0160": CellSpec(Formula(refs=(), fn=_const(0.0))),
        "0170": CellSpec(Formula(refs=(), fn=_const(0.0))),
        "0171": CellSpec(Formula(refs=(), fn=_const(0.0))),
        "0172": CellSpec(Formula(refs=(), fn=_const(0.0))),
        "0173": CellSpec(Formula(refs=(), fn=_const(0.0))),
        "0180": CellSpec(Sum("collateral_financial_value"), predicate=member),
        "0190": CellSpec(Sum("collateral_re_value"), predicate=member),
        "0200": CellSpec(Sum("collateral_other_physical_value"), predicate=member),
        "0210": CellSpec(Sum("collateral_receivables_value"), predicate=member),
        "0220": CellSpec(Sum("double_default_unfunded_protection"), predicate=member),
        "0230": (
            CellSpec(WeightedAvg(lgd_col, weight=ead_col), predicate=member, empty_cell="null")
            if lgd_col is not None
            else CellSpec(Formula(refs=(), fn=_const(None)))
        ),
        "0240": (
            _lfse_cell(cols, lambda: WeightedAvg(lgd_col, weight=ead_col), terms)
            if lgd_col is not None
            else CellSpec(Formula(refs=(), fn=_const(None)))
        ),
        "0250": CellSpec(
            WeightedAvg("irb_maturity_m", weight=ead_col, scale=365.0),
            predicate=member,
            empty_cell="null",
        ),
        "0251": CellSpec(
            Sum("c08_rwa_pre_adj" if "rwa_pre_adjustments" in cols else "rwa_pre_adjustments"),
            predicate=member,
        ),
        "0252": CellSpec(Sum("post_model_adjustment_rwa"), predicate=member),
        "0253": CellSpec(Sum("mortgage_rw_floor_adjustment"), predicate=member),
        "0254": CellSpec(Sum("unrecognised_exposure_adjustment"), predicate=member),
        "0255": CellSpec(
            Sum("rwa_pre_factor" if "rwa_pre_factor" in cols else rwa_col), predicate=member
        ),
        "0256": _sf_adjustment_cell(terms, cols, "sme_supporting_factor_applied", "is_sme"),
        "0257": _sf_adjustment_cell(
            terms, cols, "infrastructure_factor_applied", "is_infrastructure"
        ),
        "0260": CellSpec(Sum(rwa_col), predicate=member),
        "0265": CellSpec(Sum(rwa_col), predicate=narrowed(("c08_defaulted", True))),
        "0270": _lfse_cell(cols, lambda: Sum(rwa_col), terms),
        "0275": CellSpec(Sum(ead_col), predicate=member),
        "0276": (
            CellSpec(Sum("sa_rwa"), predicate=member)
            if "sa_rwa" in cols
            else CellSpec(Formula(refs=(), fn=_const(None)))
        ),
        "0280": CellSpec(
            Sum("c08_el_pre" if "el_pre_adjustment" in cols else "expected_loss"),
            predicate=member,
        ),
        "0281": CellSpec(Sum("post_model_adjustment_el"), predicate=member),
        "0282": CellSpec(
            Sum("c08_el_after" if "el_after_adjustment" in cols else "el_after_adjustment"),
            predicate=member,
        ),
        "0290": CellSpec(
            SafeSum(("scra_provision_amount", "gcra_provision_amount")), predicate=member
        ),
        "0300": (
            CellSpec(Count("counterparty_reference", distinct=True), predicate=member)
            if "counterparty_reference" in cols
            else CellSpec(Count("exposure_reference"), predicate=member)
        ),
        "0310": CellSpec(Sum(rwa_col), predicate=member),
    }
    return {ref: cell for ref, cell in cells.items() if ref in column_refs}


# =============================================================================
# C 08.01
# =============================================================================


def _c08_01_row_terms(framework: str, cols: set[str]) -> dict[str, _Terms | None]:
    """Membership terms per C 08.01 row ref (None = inert all-null row).

    Ports the retired section dispatch: section 1's "of which" rows are
    hardwired null; section 2 splits on/off-BS (B31's CCF-bucket and
    netting-set rows are inert); section 3 splits the origin approach
    (F-IRB/A-IRB vs slotting) plus the B31 unrated-corporate memo rows.
    """
    terms: dict[str, _Terms | None] = {}
    for section_index, section in enumerate(get_irb_row_sections(framework)):
        for row in section.rows:
            ref = row.ref
            if section_index == 0:
                terms[ref] = () if ref == "0010" else None
            elif section_index == 1:
                if ref == "0020":
                    terms[ref] = (("c08_bs", "on"),)
                elif ref == "0030":
                    terms[ref] = (("c08_bs", "off"),)
                else:
                    terms[ref] = None
            elif ref == "0070":
                terms[ref] = None  # composed via any_of below
            elif ref == "0080":
                terms[ref] = (("reporting_approach_origin", "slotting"),)
            elif ref == "0190":
                terms[ref] = (("c08_unrated_corp", True),)
            elif ref == "0200":
                terms[ref] = (("c08_unrated_ig", True),)
            else:
                terms[ref] = None
    return terms


def _c08_01_grades_pred() -> RowPredicate:
    """Row 0070 (obligor grades/pools) — the F-IRB/A-IRB non-slotting union.

    A two-limb ``any_of`` over ``reporting_approach_origin`` (slotting reports on
    row 0080). Defined once and shared by ``_c08_01_spec`` (merges it into every
    0070 cell) and ``_c08_01_row_preds`` (rebuilds it for the generate post-passes),
    so the drill-down's spec and the generator's predicate never drift."""
    return RowPredicate(
        any_of=(
            RowPredicate(equals=(("reporting_approach_origin", "foundation_irb"),)),
            RowPredicate(equals=(("reporting_approach_origin", "advanced_irb"),)),
        )
    )


def _c08_01_spec(framework: str, cols: set[str], ead_col: str, rwa_col: str) -> TemplateSpec:
    """The C 08.01 TemplateSpec for one run (built cols-aware).

    Shared by ``c08_01_plans`` and ``generate_c08_01`` so the drill-down re-runs
    the exact predicate the generator executed. Row 0070 merges the F-IRB/A-IRB
    union into every value cell; other rows carry their ``_c08_01_row_terms``, and
    the Total row (0010) carries the ``SideContext`` inflow (col 0080). ``cols`` is
    the PRE-``_prepare`` base-column set (``_value_cells`` reads it for base-column
    membership only, binding derived columns by name for the executor to resolve)."""
    column_refs = tuple(col.ref for col in get_c08_columns(framework))
    rows = tuple(row for section in get_irb_row_sections(framework) for row in section.rows)
    row_terms = _c08_01_row_terms(framework, cols)
    cells: dict[tuple[str, str], CellSpec] = {}
    for row in rows:
        terms = row_terms.get(row.ref)
        netting = row.ref not in C08_01_NETTING_EXEMPT_ROWS
        if row.ref == "0070":
            pred = _c08_01_grades_pred()
            for col_ref, cell in _value_cells(
                (),
                cols,
                ead_col,
                rwa_col,
                column_refs,
                inflow_key=_C08_01_INFLOW_KEYS.get("0070"),
                netting_in_waterfall=True,
            ).items():
                merged = (
                    CellSpec(cell.binding, predicate=pred, empty_cell=cell.empty_cell)
                    if cell.predicate is None or not cell.predicate.equals
                    else CellSpec(
                        cell.binding,
                        predicate=RowPredicate(equals=cell.predicate.equals, any_of=pred.any_of),
                        empty_cell=cell.empty_cell,
                    )
                )
                cells[(row.ref, col_ref)] = merged
            continue
        if terms is None:
            continue
        for col_ref, cell in _value_cells(
            terms,
            cols,
            ead_col,
            rwa_col,
            column_refs,
            inflow_key=_C08_01_INFLOW_KEYS.get(row.ref),
            netting_in_waterfall=netting,
        ).items():
            cells[(row.ref, col_ref)] = cell
    return TemplateSpec(
        name="c08_01", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
    )


def _c08_01_row_preds(row_terms: dict[str, _Terms | None]) -> dict[str, RowPredicate | None]:
    """Rebuild the C 08.01 per-row predicates from the plan's row terms.

    The three generate post-passes need each row's ``RowPredicate`` — including row
    0070's ``any_of`` union, which simple equals-terms cannot express — so it is
    rebuilt from the same ``row_terms`` the plan carries (deterministic, so
    identical to the retired inline set). ``None`` = an inert (all-null) row;
    ``()`` = the constraint-free Total row."""
    preds: dict[str, RowPredicate | None] = {}
    for ref, terms in row_terms.items():
        if ref == "0070":
            preds[ref] = _c08_01_grades_pred()
        elif terms is None:
            preds[ref] = None
        else:
            preds[ref] = RowPredicate(equals=terms) if terms else RowPredicate()
    return preds


def c08_01_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-obligor-class C 08.01 execution plans for lineage.

    Keys the per-class plans on the sealed ``reporting_class_origin`` over the
    WHOLE IRB book (F-IRB / A-IRB / slotting — C 08.01 does NOT exclude slotting),
    preserving ``generate_c08_01``'s error contract. Each plan threads the real
    per-destination-class CRM substitution INFLOW into its ``ReportingContext`` (the
    C 07.00 pattern), so the Total row's col 0080 drills to its real value rather
    than being refused, and passes ``_NEGATIVE_COLS`` EXPLICITLY (the first large
    Annex II §1.3 "(-)" negation set through lineage since C 07.00).

    The inflow is routed by ``corep/crm_substitution.py`` over the WHOLE
    population, not over the IRB book: an inflow whose substituted leg is treated
    under the standardised approach belongs on C 07.00, and reading it off this
    template's own approach-filtered frame dropped it entirely. The sheet axis is
    correspondingly the UNION of the classes present in the IRB book and the
    classes RECEIVING an inflow — Annex II's "Exposures stemming from possible in-
    and outflows from and to other templates shall be taken into account" is not
    satisfied by an inflow with nowhere to land, so a guarantor class with no
    native IRB exposure gets an inflow-only sheet (its Total row 0010 is
    constraint-free, so it survives ``_null_empty_rows`` and reports
    ``0090 = 0080``)."""
    ec_col = pick(cols, "reporting_class_origin")
    ead_col = pick(cols, "ead_final")
    rwa_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    if ec_col is None or ead_col is None or rwa_col is None:
        if ead_col is None or rwa_col is None:
            errors.append("C08.01: Missing EAD or RWA columns")
        if ec_col is None:
            errors.append("C08.01: Missing exposure_class column")
        return {}
    irb_df = _irb_population(results, cols).collect()
    # Resolved BEFORE the empty-population guard: a book whose IRB-destined
    # inflow comes entirely from legs outside this template would lose it to the
    # early exit, which is the same dropped-inflow defect one level up.
    inflow_map = irb_origin_inflows(results, cols, destination="irb")
    if len(irb_df) == 0 and not inflow_map:
        return {}
    data_cols = set(irb_df.columns)
    irb_df = _prepare(irb_df, data_cols)
    spec = _c08_01_spec(framework, data_cols, ead_col, rwa_col)
    row_terms = _c08_01_row_terms(framework, data_cols)
    plans: dict[str, SheetPlan] = {}
    sheet_keys = set(irb_df[ec_col].drop_nulls().unique().to_list()) | set(inflow_map)
    for ec in sorted(sheet_keys):
        inflow = inflow_map.get(ec)
        plans[ec] = SheetPlan(
            spec=spec,
            frame=irb_df.filter(pl.col(ec_col) == ec),
            ctx=ReportingContext(
                substitution_inflow=inflow.total if inflow else 0.0,
                substitution_inflow_on_bs=inflow.on_bs if inflow else 0.0,
                substitution_inflow_off_bs=inflow.off_bs if inflow else 0.0,
                substitution_inflow_graded=inflow.graded if inflow else 0.0,
                substitution_inflow_slotting=inflow.slotting if inflow else 0.0,
            ),
            negative_cols=_NEGATIVE_COLS,
            row_terms=row_terms,
            inflow_rows=_inflow_rows(inflow),
        )
    return plans


def _inflow_rows(inflow: InflowBreakdown | None) -> frozenset[str]:
    """The C 08.01 rows carrying a NON-ZERO inflow component on this sheet.

    ``_null_empty_rows`` renders a row all-null when its subset is empty, which is
    right for a row with nothing in it — but a row that receives an inflow is not
    empty, it is made entirely of money that lives in other sheets. Nulling it
    would delete the very component the published row sums need (and does, on an
    inflow-only sheet, where every constrained subset is empty). So the rows with
    a live inflow component are exempted."""
    if inflow is None:
        return frozenset()
    parts = {
        "0010": inflow.total,
        "0020": inflow.on_bs,
        "0030": inflow.off_bs,
        "0070": inflow.graded,
        "0080": inflow.slotting,
    }
    # Gated on the bound key set, so a row whose component exists but is not bound
    # (rows 0070/0080 today — see ``_C08_01_INFLOW_KEYS``) keeps the ordinary
    # empty-row policy rather than being exempted from a pass it does not need.
    return frozenset(ref for ref, value in parts.items() if value and ref in _C08_01_INFLOW_KEYS)


@cites("PS1/26, paragraph 1.3")
def generate_c08_01(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 08.01 per obligor-class sheet over the sealed ledger.

    Iterates ``c08_01_plans`` and applies the five post-execute passes on the
    reported frame (the off-BS pre-CCF memo 0100, the after-all-CRM total 0104,
    the all-null inert rows, the provisions ladder 0290, the Annex II §1.3 "(-)"
    negation) — the drill-down reads a cell's value from HERE, so it honours every
    pass. The per-row predicates the passes need are rebuilt from the plan's
    ``row_terms``."""
    result: dict[str, pl.DataFrame] = {}
    for ec, plan in c08_01_plans(results, cols, framework, errors).items():
        row_preds = _c08_01_row_preds(plan.row_terms)
        data_cols = set(plan.frame.columns)
        frame = execute(plan.spec, plan.frame, plan.ctx)
        frame = _c08_off_bs_pre_ccf(frame, plan.frame, row_preds)
        frame = _c08_after_all_crm(frame)
        frame = _null_empty_rows(frame, plan.frame, row_preds, plan.inflow_rows)
        frame = _provisions_postfix(frame, plan.frame, row_preds, data_cols, ref="0290")
        result[ec] = _negate(frame)
    return result


# =============================================================================
# C 08.02
# =============================================================================


def _c08_02_spec(
    labels: list[str],
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    value_refs: tuple[str, ...],
) -> TemplateSpec:
    """One C 08.02 class sheet's data-driven spec (a row per grade/PD-band label).

    Each row keys the derived ``c08_02_key`` label; the value cells are the shared
    C 08.01/02 surface (``_value_cells``). ``labels`` empty -> an empty spec (rows
    ``()``); the caller emits an ``_empty_frame`` instead of executing. ``cols`` is
    the PRE-``_prepare`` base-column set (see ``_c08_01_spec``).

    The substitution INFLOW lands on the "Unassigned" residual row and nowhere
    else — see ``_C08_02_INFLOW_ROW`` for why that row and not a grade."""
    rows = tuple(_Row(label, label) for label in labels)
    cells: dict[tuple[str, str], CellSpec] = {}
    for label in labels:
        terms: _Terms = (("c08_02_key", label),)
        for col_ref, cell in _value_cells(
            terms,
            cols,
            ead_col,
            rwa_col,
            value_refs,
            inflow_key=("substitution_inflow_graded" if label == _C08_02_INFLOW_ROW else None),
            netting_in_waterfall=True,
        ).items():
            cells[(label, col_ref)] = cell
    return TemplateSpec(
        name="c08_02", rows=rows, column_refs=value_refs, cells=cells, empty_cell="zero"
    )


def c08_02_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-class C 08.02 execution plans for lineage (data-driven rows).

    Each class sheet has its OWN spec — rows are the distinct firm grades (else the
    populated PD bands + "Unassigned") derived per class by ``_c08_02_keyed`` (the
    CR9.1 pattern), so the plans fn builds per-sheet specs exactly as the generator
    does. Keys on the sealed ``reporting_class_origin`` over the IRB NON-slotting
    book (PS1/26 Annex II §3.3.4 paragraph 77A — see the module docstring; a
    slotting-only class emits no sheet, as on C 08.03/05),
    preserving ``generate_c08_02``'s error contract. The cross-class substitution
    INFLOW lands on the "Unassigned" residual row (``_C08_02_INFLOW_ROW``), which
    is what makes the published C 08.01 r0070 tie-out hold; ``_NEGATIVE_COLS`` is
    passed explicitly (0256 still negates on C 08.02)."""
    ec_col = pick(cols, "reporting_class_origin")
    ead_col = pick(cols, "ead_final")
    rwa_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    pd_col = pick(cols, "pd_floored", "pd")
    grade_col = pick(cols, "cp_internal_rating_grade")
    if ec_col is None or ead_col is None or rwa_col is None:
        errors.append("C08.02: Missing required columns")
        return {}
    if pd_col is None:
        errors.append("C08.02: No PD column available — skipping PD grade breakdown")
        return {}
    irb_df = _non_slotting(results, cols).collect()
    # The GRADED component only: C 08.02 excludes slotting, and the tie-out it must
    # satisfy is against C 08.01 row 0070, which is the F-IRB/A-IRB union.
    inflow_map = irb_origin_inflows(results, cols, destination="irb")
    graded = {ec: flow.graded for ec, flow in inflow_map.items() if flow.graded}
    if len(irb_df) == 0 and not graded:
        return {}
    data_cols = set(irb_df.columns)
    irb_df = _prepare(irb_df, data_cols)
    value_refs = tuple(col.ref for col in get_c08_02_columns(framework) if col.ref != "0005")
    plans: dict[str, SheetPlan] = {}
    sheet_keys = set(irb_df[ec_col].drop_nulls().unique().to_list()) | set(graded)
    for ec in sorted(sheet_keys):
        class_df = irb_df.filter(pl.col(ec_col) == ec)
        labels, keyed = _c08_02_keyed(class_df, pd_col, grade_col)
        if graded.get(ec) and _C08_02_INFLOW_ROW not in labels:
            # A destination class whose own book has no unassigned-grade legs (or no
            # legs at all) still needs the row the inflow lands on, or the C 08.01
            # r0070 tie-out has nothing to sum against.
            labels = [*labels, _C08_02_INFLOW_ROW]
        plans[ec] = SheetPlan(
            spec=_c08_02_spec(labels, data_cols, ead_col, rwa_col, value_refs),
            frame=keyed,
            ctx=ReportingContext(substitution_inflow_graded=graded.get(ec, 0.0)),
            negative_cols=_NEGATIVE_COLS,
        )
    return plans


@cites("PS1/26, paragraph 1.3")
def generate_c08_02(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 08.02 per class sheet with data-driven grade/PD-band rows.

    Iterates ``c08_02_plans`` and per sheet applies the off-BS pre-CCF memo (0100),
    the after-all-CRM total (0104), the provisions ladder (0290) and the Annex II
    §1.3 "(-)" negation, then injects
    the String row label into col 0005 (the CR9.1 post-execute pattern). An
    empty-label class emits an ``_empty_frame`` (0005 typed String). Each row's
    predicate is rebuilt from the plan spec's row refs (each a ``c08_02_key``
    label)."""
    column_refs = tuple(col.ref for col in get_c08_02_columns(framework))
    result: dict[str, pl.DataFrame] = {}
    for ec, plan in c08_02_plans(results, cols, framework, errors).items():
        if not plan.spec.rows:
            result[ec] = _empty_frame(column_refs, string_refs=("0005",))
            continue
        row_preds: dict[str, RowPredicate | None] = {
            row.ref: RowPredicate(equals=(("c08_02_key", row.ref),)) for row in plan.spec.rows
        }
        data_cols = set(plan.frame.columns)
        frame = execute(plan.spec, plan.frame, plan.ctx)
        frame = _c08_off_bs_pre_ccf(frame, plan.frame, row_preds)
        frame = _c08_after_all_crm(frame)
        frame = _provisions_postfix(frame, plan.frame, row_preds, data_cols, ref="0290")
        frame = _negate(frame)
        frame = frame.with_columns(pl.col("row_name").alias("0005"))
        result[ec] = frame.select(["row_ref", "row_name", *column_refs])
    return result


def _c08_02_keyed(
    class_df: pl.DataFrame, pd_col: str, grade_col: str | None
) -> tuple[list[str], pl.DataFrame]:
    """Derive the C 08.02 row key column: distinct firm grades when the
    grade column has values (null grades -> "Unassigned"), else the
    populated fixed PD bands (out-of-band/null PD -> "Unassigned")."""
    if grade_col is not None and grade_col in class_df.columns:
        non_null = class_df.filter(pl.col(grade_col).is_not_null())
        if len(non_null) > 0:
            keyed = class_df.with_columns(
                pl.col(grade_col).fill_null("Unassigned").alias("c08_02_key")
            )
            labels = non_null[grade_col].unique().sort().to_list()
            if len(non_null) < len(class_df):
                labels.append("Unassigned")
            return labels, keyed
    band_expr: pl.Expr = pl.lit("Unassigned")
    for lower, upper, label in reversed(PD_BANDS):
        band_expr = (
            pl.when((pl.col(pd_col) >= lower) & (pl.col(pd_col) < upper))
            .then(pl.lit(label))
            .otherwise(band_expr)
        )
    keyed = class_df.with_columns(band_expr.alias("c08_02_key"))
    present = set(keyed["c08_02_key"].to_list())
    labels = [label for _lo, _hi, label in PD_BANDS if label in present]
    if "Unassigned" in present:
        labels.append("Unassigned")
    return labels, keyed


# =============================================================================
# C 08.03 / C 08.05 — the sparse PD-range pair
# =============================================================================


def _pd_alloc_col(cols: set[str], framework: str) -> str | None:
    if framework == "BASEL_3_1":
        return pick(cols, "pd", "pd_floored")
    return pick(cols, "pd_floored", "pd")


def _c08_03_cells(  # noqa: PLR0913 - the full C 08.03 sparse-PD-range column surface
    band_rows: list[tuple[str, str, str]],
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    pd_report_col: str,
    lgd_col: str | None,
) -> dict[tuple[str, str], CellSpec]:
    """The C 08.03 per-band cell surface (one PD range = one row).

    Shared by ``c08_03_plans`` (the lineage spec) and ``generate_c08_03`` (the
    reported frame). Cols 0010/0020 sum the sealed per-side gross carriers
    (``reporting_gross_on_bs`` / ``reporting_gross_off_bs``) over the whole band
    — the carriers are row-level and null outside their side, so a band with no
    off-BS rows sums 0.0 naturally, which is why the retired on/off whole-bucket
    fallback is gone. Col 0030 weights the average CCF by the off-BS gross."""
    cells: dict[tuple[str, str], CellSpec] = {}
    for ref, label, term_col in band_rows:
        terms: _Terms = ((term_col, label),)
        member = RowPredicate(equals=terms)
        cells[(ref, "0010")] = CellSpec(Sum("reporting_gross_on_bs"), predicate=member)
        cells[(ref, "0020")] = CellSpec(Sum("reporting_gross_off_bs"), predicate=member)
        cells[(ref, "0030")] = CellSpec(
            WeightedAvg("ccf", weight="reporting_gross_off_bs"),
            predicate=member,
            empty_cell="null",
        )
        cells[(ref, "0040")] = CellSpec(Sum(ead_col), predicate=member)
        cells[(ref, "0050")] = CellSpec(
            WeightedAvg(pd_report_col, weight=ead_col), predicate=member, empty_cell="null"
        )
        cells[(ref, "0060")] = (
            CellSpec(Count("counterparty_reference", distinct=True), predicate=member)
            if "counterparty_reference" in cols
            else CellSpec(Count("exposure_reference"), predicate=member)
        )
        cells[(ref, "0070")] = (
            CellSpec(WeightedAvg(lgd_col, weight=ead_col), predicate=member, empty_cell="null")
            if lgd_col is not None
            else CellSpec(Formula(refs=(), fn=_const(None)))
        )
        cells[(ref, "0080")] = CellSpec(
            WeightedAvg("irb_maturity_m", weight=ead_col), predicate=member, empty_cell="null"
        )
        cells[(ref, "0090")] = CellSpec(Sum(rwa_col), predicate=member)
        cells[(ref, "0100")] = CellSpec(Sum("expected_loss"), predicate=member)
        cells[(ref, "0110")] = CellSpec(
            SafeSum(("scra_provision_amount", "gcra_provision_amount")), predicate=member
        )
    return cells


def c08_03_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-class C 08.03 execution plans for lineage (sparse PD rows).

    Each class sheet has its OWN spec — rows are the populated bands of the fixed
    regulatory PD scale (plus an optional 9999 Unassigned) derived per class by
    ``pd_scale.banded_rows`` (the c08_02 data-driven pattern), keyed on the derived
    ``c08_pd_range`` / ``c08_pd_parent`` label carried in ``row_terms``. The scale
    is hierarchical, so parent bands overlap and sum their sub-bands. Keys on the sealed ``reporting_class_origin`` over the IRB
    NON-slotting book, preserving ``generate_c08_03``'s error contract. C 08.03
    carries no "(-)"-labelled deduction column, so ``negative_cols`` is empty. The
    provisions ladder (col 0110) is the one post-execute pass, on the REPORTED
    frame (``generate_c08_03``), which the drill-down reads a cell's value from.
    Cols 0010/0020 sum the sealed per-side gross carriers directly (no on/off
    whole-bucket fallback — the carriers are row-level and null outside their
    side, so an empty side sums 0.0 naturally)."""
    ec_col = pick(cols, "reporting_class_origin")
    ead_col = pick(cols, "ead_final")
    rwa_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    if ec_col is None or ead_col is None or rwa_col is None:
        errors.append("C08.03: Missing required columns (exposure_class/ead/rwa)")
        return {}
    alloc_pd_col = _pd_alloc_col(cols, framework)
    report_pd_col = pick(cols, "pd_floored", "pd")
    if alloc_pd_col is None:
        errors.append("C08.03: No PD column available — skipping PD range breakdown")
        return {}
    irb_df = _non_slotting(results, cols).collect()
    if len(irb_df) == 0:
        return {}
    data_cols = set(irb_df.columns)
    irb_df = _prepare(irb_df, data_cols)
    column_refs = tuple(col.ref for col in get_c08_03_columns(framework))
    lgd_col = pick(data_cols, "lgd_floored", "lgd_input")
    pd_report_col = report_pd_col or alloc_pd_col
    plans: dict[str, SheetPlan] = {}
    for ec in irb_df[ec_col].drop_nulls().unique().sort().to_list():
        class_df = irb_df.filter(pl.col(ec_col) == ec)
        band_rows, banded = banded_rows(class_df, alloc_pd_col, framework)
        cells = _c08_03_cells(band_rows, data_cols, ead_col, rwa_col, pd_report_col, lgd_col)
        rows = tuple(_Row(ref, label) for ref, label, _col in band_rows)
        plans[ec] = SheetPlan(
            spec=TemplateSpec(
                name="c08_03", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
            ),
            frame=banded,
            ctx=ReportingContext(),
            negative_cols=frozenset(),
            row_terms={ref: ((col, label),) for ref, label, col in band_rows},
        )
    return plans


@cites("PS1/26, paragraph 1.3")
def generate_c08_03(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 08.03 per class sheet over sparse PD-range rows.

    Iterates ``c08_03_plans`` and applies the one post-execute pass on the
    reported frame — the provisions ladder (col 0110) — which the drill-down
    reads a cell's value from. Cols 0010/0020 (the sealed per-side gross
    carriers) need no post-pass. Each row's predicate is rebuilt from the plan's
    ``row_terms`` (a ``c08_pd_range`` leaf label, or ``c08_pd_parent`` for a
    parent band)."""
    column_refs = tuple(col.ref for col in get_c08_03_columns(framework))
    result: dict[str, pl.DataFrame] = {}
    for ec, plan in c08_03_plans(results, cols, framework, errors).items():
        if not plan.spec.rows:
            result[ec] = _empty_frame(column_refs)
            continue
        banded = plan.frame
        data_cols = set(banded.columns)
        row_preds: dict[str, RowPredicate | None] = {
            ref: RowPredicate(equals=terms) for ref, terms in plan.row_terms.items() if terms
        }
        frame = execute(plan.spec, banded)
        frame = _provisions_postfix(frame, banded, row_preds, data_cols, ref="0110")
        result[ec] = frame
    return result


def _c08_05_cells(  # noqa: PLR0913 - the full C 08.05 PD-backtesting column surface
    band_rows: list[tuple[str, str, str]],
    cols: set[str],
    pd_report_col: str,
    *,
    prior_present: bool,
    hist_present: bool,
) -> dict[tuple[str, str], CellSpec]:
    """The C 08.05 per-band cell surface (PD back-testing over sparse ranges).

    Shared by ``c08_05_plans`` and ``generate_c08_05``. R13 deleted this
    template's rate postfix, so it is execute-only — the cleanest of the C 08.03/
    05/06 trio: col 0040 (observed default rate) is an intra-row Formula and 0050
    a copy-of-0040 fallback (or the WeightedAvg historical rate when supplied)."""
    cells: dict[tuple[str, str], CellSpec] = {}
    for ref, label, term_col in band_rows:
        terms: _Terms = ((term_col, label),)
        member = RowPredicate(equals=terms)
        cells[(ref, "0010")] = CellSpec(
            WeightedAvg(pd_report_col, weight="c08_one"), predicate=member, empty_cell="null"
        )
        if prior_present:
            cells[(ref, "0020")] = CellSpec(Sum("prior_year_obligor_count"), predicate=member)
        elif "counterparty_reference" in cols:
            cells[(ref, "0020")] = CellSpec(
                Count("counterparty_reference", distinct=True), predicate=member
            )
        else:
            cells[(ref, "0020")] = CellSpec(Count("exposure_reference"), predicate=member)
        if "counterparty_reference" in cols:
            cells[(ref, "0030")] = CellSpec(
                Count("counterparty_reference", distinct=True),
                predicate=RowPredicate(equals=(*terms, ("c08_05_defaulted", True))),
            )
        else:
            cells[(ref, "0030")] = CellSpec(
                Count("exposure_reference"),
                predicate=RowPredicate(equals=(*terms, ("c08_05_defaulted", True))),
            )
        cells[(ref, "0040")] = CellSpec(Formula(refs=("0020", "0030"), fn=_observed_rate))
        if hist_present:
            cells[(ref, "0050")] = CellSpec(
                WeightedAvg("historical_annual_default_rate", weight="c08_one"), predicate=member
            )
        else:
            cells[(ref, "0050")] = CellSpec(Formula(refs=("0040",), fn=_copy_of_0040))
    return cells


def c08_05_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-class C 08.05 execution plans for lineage (sparse PD rows).

    Shares ``pd_scale.banded_rows`` / ``_pd_alloc_col`` with C 08.03; each class sheet has
    its OWN sparse-PD-range spec, keyed on the sealed ``reporting_class_origin``
    over the IRB NON-slotting book (preserving ``generate_c08_05``'s error
    contract). Execute-only (R13 deleted the rate postfix), so ``generate_c08_05``
    is a plain ``execute`` of each plan — no post-execute pass, and no
    "(-)"-labelled deduction column (``negative_cols`` empty)."""
    ec_col = pick(cols, "reporting_class_origin")
    if ec_col is None:
        errors.append("C08.05: Missing required column (exposure_class)")
        return {}
    alloc_pd_col = _pd_alloc_col(cols, framework)
    report_pd_col = pick(cols, "pd_floored", "pd")
    if alloc_pd_col is None:
        errors.append("C08.05: No PD column available — skipping PD backtesting")
        return {}
    irb_df = _non_slotting(results, cols).collect()
    if len(irb_df) == 0:
        return {}
    data_cols = set(irb_df.columns)
    pd_report_col = report_pd_col or alloc_pd_col
    irb_df = _c08_05_prepare(_prepare(irb_df, data_cols), data_cols, pd_report_col)
    column_refs = tuple(col.ref for col in get_c08_05_columns(framework))
    prior_present = "prior_year_obligor_count" in data_cols
    hist_present = "historical_annual_default_rate" in data_cols
    plans: dict[str, SheetPlan] = {}
    for ec in irb_df[ec_col].drop_nulls().unique().sort().to_list():
        class_df = irb_df.filter(pl.col(ec_col) == ec)
        band_rows, banded = banded_rows(class_df, alloc_pd_col, framework)
        cells = _c08_05_cells(
            band_rows,
            data_cols,
            pd_report_col,
            prior_present=prior_present,
            hist_present=hist_present,
        )
        rows = tuple(_Row(ref, label) for ref, label, _col in band_rows)
        plans[ec] = SheetPlan(
            spec=TemplateSpec(
                name="c08_05", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
            ),
            frame=banded,
            ctx=ReportingContext(),
            negative_cols=frozenset(),
            row_terms={ref: ((col, label),) for ref, label, col in band_rows},
        )
    return plans


@cites("PS1/26, paragraph 1.3")
def generate_c08_05(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 08.05 per class sheet (PD back-testing over sparse ranges).

    Iterates ``c08_05_plans`` and executes each plan — R13 left this template
    execute-only, so there is no post-execute pass to reconcile the drill-down
    against."""
    column_refs = tuple(col.ref for col in get_c08_05_columns(framework))
    result: dict[str, pl.DataFrame] = {}
    for ec, plan in c08_05_plans(results, cols, framework, errors).items():
        result[ec] = (
            _empty_frame(column_refs) if not plan.spec.rows else execute(plan.spec, plan.frame)
        )
    return result


def _c08_05_prepare(data: pl.DataFrame, cols: set[str], report_pd_col: str) -> pl.DataFrame:
    """The C 08.05 default-detection ladder (is_defaulted else PD >= 100%)."""
    if "is_defaulted" in cols:
        flag = pl.col("is_defaulted") == True  # noqa: E712
    elif report_pd_col in cols:
        flag = (pl.col(report_pd_col) >= 1.0).fill_null(value=False)
    else:
        flag = pl.lit(value=False)
    return data.with_columns(flag.alias("c08_05_defaulted"))


# =============================================================================
# C 08.04 — the flow clone
# =============================================================================


def _c08_04_spec(cols: set[str], framework: str) -> TemplateSpec:
    """The C 08.04 flow spec (the CR8 clone): closing (row 0090, current
    period), opening (row 0010, a ``PriorPeriod`` binding) and residual (row
    0080, a ``Formula`` deriving from both). Shared by the reported generator
    (which threads a prior-period frame) and the lineage plan (the
    current-period view — no prior, so the opening/residual rows stay null and
    are refused by the drill-down exactly as CR8 refuses its rows 1/8). The RWA
    ladder is deliberately two-wide (no ``rwa_post_factor``) — the retired
    ladder."""
    rwa_col = pick(cols, "rwa_final", "rwa")
    column_refs = tuple(col.ref for col in get_c08_04_columns(framework))
    rows = tuple(C08_04_ROWS)
    cells: dict[tuple[str, str], CellSpec] = {}
    if rwa_col is not None:
        cells[("0090", "0010")] = CellSpec(Sum(rwa_col))  # closing RWEA
        cells[("0010", "0010")] = CellSpec(PriorPeriod(Sum(rwa_col)))  # opening RWEA
        cells[("0080", "0010")] = CellSpec(
            Formula(refs=("0090", "0010"), fn=_c08_04_other_flow)  # signed residual
        )
    return TemplateSpec(
        name="c08_04", rows=rows, column_refs=column_refs, cells=cells, empty_cell="null"
    )


def c08_04_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-class C 08.04 execution plans for lineage (current period).

    The current-period view: no prior-period frame is threaded, so the opening
    (row 0010, a ``PriorPeriod`` cell) and residual (row 0080, a ``Formula``
    deriving from it) rows stay null — both are prior-period-derived, so lineage
    REFUSES them exactly as CR8 refuses its opening/residual rows (R20's refusal,
    free). Keys the per-class plans on the sealed ``reporting_class_origin``,
    identically to ``generate_c08_04``, and preserves its error contract. C 08.04
    carries no "(-)"-labelled deduction column, so ``negative_cols`` is empty.
    """
    ec_col = pick(cols, "reporting_class_origin")
    if ec_col is None:
        errors.append("C08.04: Missing required column (exposure_class)")
        return {}
    irb_df = _non_slotting(results, cols).collect()
    if len(irb_df) == 0:
        return {}
    data_cols = set(irb_df.columns)
    spec = _c08_04_spec(data_cols, framework)
    plans: dict[str, SheetPlan] = {}
    for ec in irb_df[ec_col].drop_nulls().unique().sort().to_list():
        plans[ec] = SheetPlan(
            spec=spec,
            frame=irb_df.filter(pl.col(ec_col) == ec),
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    return plans


def c08_04_frames(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Render the current-period C 08.04 frames for lineage (keyed like
    ``c08_04_plans``). The lineage-facing generator — no prior-period frame —
    so a cell's reported value and its spec are looked up under the same class
    key. C 08.04 has no post-execute passes, so this is a plain ``execute``.
    ``generate_c08_04`` (the prior-aware dispatch entry) keeps its distinct
    signature and threads the external prior frame the current-period lineage
    view cannot carry."""
    return {
        key: execute(plan.spec, plan.frame, plan.ctx)
        for key, plan in c08_04_plans(results, cols, framework, errors).items()
    }


@cites("PS1/26, paragraph 1.3")
def generate_c08_04(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
    prior_results: pl.LazyFrame | None = None,
) -> dict[str, pl.DataFrame]:
    """Execute C 08.04 per class sheet — closing, opening, and residual flow.

    Mirrors Pillar 3 CR8 (``pillar3/cr8.py``): row 0090 (closing) sums the
    current period's RWEA; row 0010 (opening) sums the SAME population over
    the prior-period frame (``prior_results``, filtered identically and keyed
    per sheet) through the ``PriorPeriod`` binding; row 0080 (Other) carries
    the signed residual ``closing - opening`` so the statement foots. The six
    attributable driver rows (0020-0070) stay null — two point-in-time
    snapshots cannot supply the exposure-level period-over-period lineage they
    need. With NO prior period every row but the closing stays null (unchanged
    behaviour; PS1/26 Annex XXII paragraph 11).

    ``prior_results`` must be a prior run of the SAME sealed shape as
    ``results`` (an aggregator-exit frame): ``rwa_col`` is resolved from the
    CURRENT frame's columns and reused verbatim over the prior — safe only
    under that same-shape precondition (a prior frame missing that column
    yields a null opening, never a raise).

    Prior-only-class limitation (recorded, deliberate — NOT a bug): the sheet
    loop iterates the CURRENT period's classes only. A class that carried RWEA
    last period but has zero exposures this period (fully run off) therefore
    emits NO sheet, and its run-off leaves no trace in any flow statement. This
    is inherent to the per-class-sheet pattern — every C 08.0x template behaves
    this way. Unioning current+prior class keys to emit an opening-only run-off
    sheet is the possible future extension if a supervisor ever requires the
    run-off to be visible; it is intentionally NOT implemented here.
    """
    ec_col = pick(cols, "reporting_class_origin")
    if ec_col is None:
        errors.append("C08.04: Missing required column (exposure_class)")
        return {}
    irb_df = _non_slotting(results, cols).collect()
    if len(irb_df) == 0:
        return {}
    data_cols = set(irb_df.columns)
    prior_irb_df, prior_ec_col = _c08_04_prior(prior_results)
    spec = _c08_04_spec(data_cols, framework)
    result: dict[str, pl.DataFrame] = {}
    for ec in irb_df[ec_col].drop_nulls().unique().sort().to_list():
        class_df = irb_df.filter(pl.col(ec_col) == ec)
        ctx: ReportingContext | None = None
        if prior_irb_df is not None and prior_ec_col is not None:
            prior_class = prior_irb_df.filter(pl.col(prior_ec_col) == ec)
            ctx = ReportingContext(previous_period_results=prior_class.lazy())
        result[ec] = execute(spec, class_df, ctx)
    return result


def _c08_04_prior(
    prior_results: pl.LazyFrame | None,
) -> tuple[pl.DataFrame | None, str | None]:
    """Collect and IRB-filter the prior-period frame for the opening RWEA.

    Returns ``(None, None)`` when no prior period is supplied, or when the
    prior frame lacks the ``reporting_class_origin`` key the current sheets
    are keyed on — the opening then stays null (graceful degradation, never a
    raise). The prior frame is IRB non-slotting filtered exactly as the
    current one, so its per-class RWEA sum is the like-for-like opening.
    """
    if prior_results is None:
        return None, None
    prior_cols = available_columns(prior_results)
    prior_ec_col = pick(prior_cols, "reporting_class_origin")
    if prior_ec_col is None:
        return None, None
    return _non_slotting(prior_results, prior_cols).collect(), prior_ec_col


# =============================================================================
# C 08.06 / OF 08.06 — specialised lending slotting (per SL-type sheets)
# =============================================================================


def _c08_06_row_defs(framework: str) -> list[tuple[str, str, bool | None, str]]:
    """The C 08.06 category x maturity row definitions (category + Total rows
    only) for one framework — shared by the spec, the plan and the sheet
    post-passes."""
    return [
        row_def
        for row_def in get_c08_06_rows(framework)
        if row_def[1] == "Total" or row_def[1] in C08_06_CATEGORY_MAP
    ]


def _c08_06_row_preds(
    row_defs: list[tuple[str, str, bool | None, str]], cols: set[str]
) -> dict[str, RowPredicate]:
    """Each row's category x maturity subset predicate (the asymmetric
    ``is_short_maturity`` fallback preserved)."""
    has_maturity = "is_short_maturity" in cols
    return {
        row_def[0]: _c08_06_row_pred(row_def[1], row_def[2], has_maturity=has_maturity)
        for row_def in row_defs
    }


def _c08_06_empty_refs(
    type_df: pl.DataFrame,
    row_defs: list[tuple[str, str, bool | None, str]],
    row_preds: dict[str, RowPredicate],
) -> frozenset[str]:
    """Non-Total rows with an EMPTY subset on this SL-type sheet.

    These rows are hard zero-filled by ``_c08_06_sheet`` (every cell 0.0 except
    col 0070 = the row definition's FIXED display risk weight), so their col 0070
    is a display artefact, not a measured weighted average. The per-sheet spec
    therefore leaves that cell UNBOUND (its value comes from the reported frame's
    zero-fill pass), so lineage reports it as the template's empty policy rather
    than a WeightedAvg with no legs whose value would contradict the screen. Uses
    the SAME emptiness test as ``_c08_06_sheet`` (subset height 0, label != Total)."""
    subsets = subset_rows(type_df, dict(row_preds))
    return frozenset(
        row_def[0]
        for row_def in row_defs
        if row_def[1] != "Total" and subsets[row_def[0]].height == 0
    )


def _c08_06_sheets(data: pl.DataFrame, cols: set[str], framework: str) -> dict[str, pl.DataFrame]:
    """The per-SL-type frames (empty SL types emit no sheet); a frame with no
    ``sl_type`` column is one ``specialised_lending`` sheet."""
    if "sl_type" not in cols:
        return {"specialised_lending": data}
    sheets: dict[str, pl.DataFrame] = {}
    for sl_key in get_c08_06_sl_types(framework):
        type_df = _c08_06_sl_type_sheet(data, sl_key, cols, framework)
        if type_df.height > 0:
            sheets[sl_key] = type_df
    return sheets


def c08_06_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-SL-type C 08.06 execution plans for lineage (slotting only).

    Keys per-SL-TYPE sheets (CRR's IPRE absorbs HVCRE; B31 splits HVCRE; empty SL
    types emit NO sheet) over the slotting-only book, preserving
    ``generate_c08_06``'s error contract. Each sheet gets its OWN spec because the
    row set is number-neutral but the EMPTY-row set is per-sheet: an empty
    non-Total row's col 0070 is a fixed display risk weight (a zero-fill artefact),
    so the spec leaves that one cell UNBOUND (``_c08_06_empty_refs``) — the
    drill-down then reports it as the template's empty policy and reads its value
    from the reported frame, honouring the zero-fill without a WeightedAvg that has
    no legs. The three value-dependent post-passes (empty-row zero-fill; the 0030
    nominal / 0040 clamp / 0070 first-non-null live fixes; the provisions ladder)
    live on the REPORTED frame (``generate_c08_06``). C 08.06 carries no
    "(-)"-labelled deduction column, so ``negative_cols`` is empty."""
    ead_col = pick(cols, "ead_final")
    rwa_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    if ead_col is None or rwa_col is None:
        errors.append("C08.06: Missing required columns (ead/rwa)")
        return {}
    if pick(cols, "reporting_approach_origin", "approach") is None:
        errors.append("C08.06: No approach column — cannot identify slotting exposures")
        return {}
    # The retired dispatch pre-filtered the IRB book on the applied
    # approach only — an ``approach``-only frame silently yields nothing.
    if "reporting_approach_origin" not in cols:
        return {}
    slotting_df = results.filter(pl.col("reporting_approach_origin") == "slotting").collect()
    if slotting_df.height == 0:
        return {}
    if "slotting_category" not in cols:
        errors.append("C08.06: Missing slotting_category column — cannot generate template")
        return {}
    data = _c08_06_prepare(slotting_df, cols)
    row_defs = _c08_06_row_defs(framework)
    row_preds = _c08_06_row_preds(row_defs, cols)
    plans: dict[str, SheetPlan] = {}
    for sl_key, type_df in _c08_06_sheets(data, cols, framework).items():
        empty_refs = _c08_06_empty_refs(type_df, row_defs, row_preds)
        plans[sl_key] = SheetPlan(
            spec=_c08_06_spec(cols, ead_col, rwa_col, framework, empty_refs),
            frame=type_df,
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    return plans


@cites("PS1/26, paragraph 1.3")
def generate_c08_06(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 08.06 / OF 08.06 per SL-type sheet (slotting only).

    Rows = slotting category x maturity band (plus the two maturity-split
    Total rows); the retired two-branch row policy is preserved: an EMPTY
    non-Total row zero-fills every cell and reports the row definition's
    fixed display risk weight in 0070, while live rows (and both Total
    rows, even when empty) compute on data with per-cell null policy. Iterates
    ``c08_06_plans`` and applies ``_c08_06_sheet``'s value-dependent overrides on
    each plan's reported frame, which the drill-down reads a cell's value from."""
    plans = c08_06_plans(results, cols, framework, errors)
    if not plans:
        return {}
    ead_col = pick(cols, "ead_final")
    if ead_col is None:  # unreachable — a non-empty plan set implies ead_final resolved
        return {}
    row_defs = _c08_06_row_defs(framework)
    row_preds = _c08_06_row_preds(row_defs, cols)
    return {
        sl_key: _c08_06_sheet(plan.spec, plan.frame, row_defs, row_preds, cols, ead_col)
        for sl_key, plan in plans.items()
    }


def _c08_06_prepare(data: pl.DataFrame, cols: set[str]) -> pl.DataFrame:
    """Derive the off-balance discriminator (the kernel filter_off_bs rule:
    ``bs_type == "OFB"`` else ``exposure_type in {facility, contingent,
    facility_undrawn}`` else nothing) and the always-False carrier behind the
    permanently-empty "substantially stronger" sub-rows."""
    if "bs_type" in cols:
        off_bs = pl.col("bs_type") == "OFB"
    elif "exposure_type" in cols:
        off_bs = pl.col("exposure_type").is_in(["facility", "contingent", "facility_undrawn"])
    else:
        off_bs = pl.lit(value=False)
    return data.with_columns(
        off_bs.alias("c0806_off_bs"),
        pl.lit(value=False).alias("c0806_never"),
    )


def _c08_06_sl_type_sheet(
    data: pl.DataFrame, sl_key: str, cols: set[str], framework: str
) -> pl.DataFrame:
    """The retired HVCRE routing: CRR's IPRE sheet absorbs HVCRE (only when
    ``is_hvcre`` exists); B31's HVCRE sheet admits ``is_hvcre`` flags too."""
    has_hvcre = "is_hvcre" in cols
    if sl_key == "ipre" and framework != "BASEL_3_1" and has_hvcre:
        return data.filter(pl.col("sl_type").is_in(["ipre", "hvcre"]))
    if sl_key == "hvcre" and framework == "BASEL_3_1" and has_hvcre:
        return data.filter((pl.col("sl_type") == "hvcre") | pl.col("is_hvcre"))
    return data.filter(pl.col("sl_type") == sl_key)


def _c08_06_row_pred(label: str, is_short: bool | None, *, has_maturity: bool) -> RowPredicate:
    """One category x maturity row subset. The retired asymmetric fallback
    is preserved: with no maturity column the SHORT band is empty while the
    LONG band absorbs the whole category."""
    never = RowPredicate(equals=(("c0806_never", True),))
    if "substantially stronger" in label:
        return never
    terms: list[tuple[str, str | bool]] = []
    if label != "Total":
        terms.append(("slotting_category", C08_06_CATEGORY_MAP[label]))
    if is_short is not None:
        if has_maturity:
            terms.append(("is_short_maturity", is_short))
        elif is_short:
            return never
    return RowPredicate(equals=tuple(terms))


def _c08_06_spec(
    cols: set[str], ead_col: str, rwa_col: str, framework: str, empty_refs: frozenset[str]
) -> TemplateSpec:
    """The C 08.06 spec for one SL-type sheet (framework-shaped).

    ``empty_refs`` names the non-Total rows whose subset is empty on THIS sheet:
    their col 0070 is a fixed display risk weight applied by the zero-fill
    post-pass, so it is left UNBOUND here (see ``_c08_06_empty_refs``). Every
    other cell is number-neutral across sheets."""
    column_refs = tuple(col.ref for col in get_c08_06_columns(framework))
    row_defs = _c08_06_row_defs(framework)
    rows = tuple(_Row(row_def[0], row_def[1]) for row_def in row_defs)
    row_preds = _c08_06_row_preds(row_defs, cols)
    crm_col = pick(cols, "ead_pre_ccf", "exposure_post_crm")
    if framework != "BASEL_3_1" and "rwa_post_factor" in cols:
        rwea_col = "rwa_post_factor"  # CRR prefers the post-supporting-factor RWEA
    else:
        rwea_col = rwa_col
    cells: dict[tuple[str, str], CellSpec] = {}
    for row_def in row_defs:
        ref = row_def[0]
        pred = row_preds[ref]
        off_pred = RowPredicate(equals=(*pred.equals, ("c0806_off_bs", True)))
        cells[(ref, "0010")] = CellSpec(
            SafeSum(("reporting_gross_on_bs", "reporting_gross_off_bs")),
            predicate=pred,
        )
        cells[(ref, "0020")] = (
            CellSpec(Sum(crm_col), predicate=pred)
            if crm_col is not None
            else CellSpec(Formula(refs=("0010",), fn=_copy_of_0010))
        )
        cells[(ref, "0030")] = CellSpec(Sum("reporting_gross_off_bs"), predicate=pred)
        if "0031" in column_refs:
            cells[(ref, "0031")] = CellSpec(Formula(refs=(), fn=_const(None)))
        cells[(ref, "0040")] = CellSpec(Sum(ead_col), predicate=pred)
        cells[(ref, "0050")] = CellSpec(Sum(ead_col), predicate=off_pred, empty_cell="null")
        cells[(ref, "0060")] = CellSpec(Formula(refs=(), fn=_const(None)))
        # Col 0070 on an EMPTY non-Total row is a fixed display risk weight from
        # the zero-fill post-pass (not a measured weighted average), so it is left
        # UNBOUND — the drill-down reads its value from the reported frame and
        # reports the template's empty policy, never a WeightedAvg with no legs.
        if ref not in empty_refs:
            cells[(ref, "0070")] = CellSpec(
                WeightedAvg("risk_weight", weight=ead_col), predicate=pred, empty_cell="null"
            )
        cells[(ref, "0080")] = CellSpec(Sum(rwea_col), predicate=pred)
        cells[(ref, "0090")] = (
            CellSpec(Sum("expected_loss"), predicate=pred)
            if "expected_loss" in cols
            else CellSpec(Formula(refs=(), fn=_const(None)))
        )
        cells[(ref, "0100")] = CellSpec(
            SafeSum(("scra_provision_amount", "gcra_provision_amount")), predicate=pred
        )
    return TemplateSpec(
        name="c08_06", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
    )


def _c08_06_sheet(
    spec: TemplateSpec,
    type_df: pl.DataFrame,
    row_defs: list[tuple[str, str, bool | None, str]],
    row_preds: dict[str, RowPredicate],
    cols: set[str],
    ead_col: str,
) -> pl.DataFrame:
    """Execute one SL-type sheet and apply the retired value-dependent
    branches: the zero-fill policy for empty non-Total rows (fixed display
    RW in 0070), the >0 clamp on 0040, the first-non-null risk weight when
    the subset carries zero total EAD, and the SCRA/GCRA -> provision_held
    provisions ladder. Col 0030 (off-BS gross) now sums the sealed
    ``reporting_gross_off_bs`` carrier over the whole row in the spec — the
    carrier is null outside the off side, so an all-on-BS row sums 0.0
    naturally and the retired whole-subset nominal fallback is gone."""
    frame = execute(spec, type_df)
    overrides: dict[str, dict[str, float | None]] = {}
    row_subsets = subset_rows(type_df, dict(row_preds))
    for row_ref, label, _is_short, rw_display in row_defs:
        subset = row_subsets[row_ref]
        if subset.height == 0 and label != "Total":
            overrides[row_ref] = _c08_06_zero_row(spec.column_refs, rw_display)
            continue
        fixes: dict[str, float | None] = {}
        ead_sum = float(subset[ead_col].fill_null(0.0).sum())
        if ead_sum <= 0.0:
            fixes["0040"] = 0.0
        if subset.height > 0 and ead_sum <= 0.0 and "risk_weight" in cols:
            rw_vals = subset["risk_weight"].drop_nulls()
            fixes["0070"] = float(rw_vals[0]) if len(rw_vals) > 0 else None
        if fixes:
            overrides[row_ref] = fixes
    frame = _c08_06_apply_overrides(frame, overrides)
    return _provisions_postfix(frame, type_df, row_preds, cols, ref="0100")


def _c08_06_zero_row(column_refs: tuple[str, ...], rw_display: str) -> dict[str, float | None]:
    """The retired zero-fill for an empty non-Total row: every cell 0.0
    except 0070 = the row definition's display risk weight ("50%" -> 0.5;
    unparseable/blank -> None)."""
    values: dict[str, float | None] = dict.fromkeys(column_refs, 0.0)
    if rw_display:
        try:
            values["0070"] = float(rw_display.replace("%", "").strip()) / 100.0
        except ValueError:
            values["0070"] = None
    else:
        values["0070"] = None
    return values


def _c08_06_apply_overrides(
    frame: pl.DataFrame, overrides: dict[str, dict[str, float | None]]
) -> pl.DataFrame:
    if not overrides:
        return frame
    exprs: list[pl.Expr] = []
    value_cols = [col for col in frame.columns if col not in ("row_ref", "row_name")]
    for col in value_cols:
        expr = pl.col(col)
        touched = False
        for row_ref, values in overrides.items():
            if col in values:
                expr = (
                    pl.when(pl.col("row_ref") == row_ref)
                    .then(pl.lit(values[col], dtype=pl.Float64))
                    .otherwise(expr)
                )
                touched = True
        if touched:
            exprs.append(expr.alias(col))
    return frame.with_columns(exprs) if exprs else frame


def _copy_of_0010(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """C 08.06 col 0020 falls back to col 0010 when no post-CRM carrier
    (``ead_pre_ccf`` / ``exposure_post_crm``) exists."""
    return cells["0010"]


# =============================================================================
# Shared post-steps + small helpers
# =============================================================================


def _non_slotting(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    irb = _irb_population(results, cols)
    approach_col = pick(cols, "reporting_approach_origin", "approach")
    if approach_col is not None:
        return irb.filter(pl.col(approach_col) != "slotting")
    return irb


def _null_empty_rows(
    frame: pl.DataFrame,
    class_df: pl.DataFrame,
    row_preds: dict[str, RowPredicate | None],
    keep: frozenset[str] = frozenset(),
) -> pl.DataFrame:
    """Render inert rows and rows with EMPTY subsets all-null.

    ``keep`` exempts rows whose content is a cross-sheet inflow: their own subset
    is legitimately empty (the money lives in other sheets), so nulling them would
    delete the component the published row sums need — visibly so on an
    inflow-only sheet, where EVERY constrained subset is empty."""
    constrained = {
        ref: pred
        for ref, pred in row_preds.items()
        if pred is not None and (pred.equals or pred.any_of)
    }
    counts = matched_counts(class_df, constrained)
    null_refs = [
        ref
        for ref, pred in row_preds.items()
        if ref not in keep and (pred is None or ((pred.equals or pred.any_of) and counts[ref] == 0))
    ]
    if not null_refs:
        return frame
    value_cols = [col for col in frame.columns if col not in ("row_ref", "row_name")]
    return frame.with_columns(
        pl.when(pl.col("row_ref").is_in(null_refs))
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col(col))
        .alias(col)
        for col in value_cols
    )


def _provisions_postfix(
    frame: pl.DataFrame,
    class_df: pl.DataFrame,
    row_preds: Mapping[str, RowPredicate | None],
    cols: set[str],
    *,
    ref: str,
) -> pl.DataFrame:
    """The provisions ladder: when the SCRA/GCRA base sum nets to ~0, swap the
    whole cell to the best available provisions carrier for the row subset (a
    value-dependent, PER-CELL branch — the recorded C 08 granularity, distinct
    from C 07.00's per-row ladder).

    The fallback carrier is ``provision_held`` when the frame carries it (the
    synthetic COREP unit frames supply it), else the sealed ``provision_allocated``
    (R10b). The retired ``provision_held``-only fallback was DEAD on every real
    submission: ``provision_held`` is an input pass-through the aggregator seal
    strips, so ``"provision_held" not in cols`` returned early and the provisions
    cells (C 08.01/02 col 0290, C 08.03 col 0110, C 08.06 col 0100) rendered a
    hard 0.0. ``provision_allocated`` is the sealed provisions carrier that IS
    meaningful on the IRB book: unlike C 07.00's ``provision_deducted`` (R9), the
    Art. 111(2) drawn-first deduction is SA-only (engine/crm/provisions.py —
    IRB/Slotting: provision_on_drawn = 0, provision_on_nominal = 0, so
    provision_deducted is STRUCTURALLY 0.0 on every IRB/slotting leg), whereas
    provision_allocated is tracked for all approaches (it feeds the IRB EL
    shortfall/excess). scra/gcra stay the preferred base; a book that supplies
    them non-degenerately keeps that granular figure."""
    fallback_col = (
        "provision_held"
        if "provision_held" in cols
        else "provision_allocated"
        if "provision_allocated" in cols
        else None
    )
    if ref not in frame.columns or fallback_col is None:
        return frame
    needed: dict[str, RowPredicate | None] = {}
    for row_ref, pred in row_preds.items():
        if pred is None:
            continue
        current = frame.filter(pl.col("row_ref") == row_ref)
        if current.height == 0 or current[ref][0] is None:
            continue
        if abs(current[ref][0]) >= 1e-9:
            continue
        needed[row_ref] = pred
    fixes: dict[str, float] = {}
    for row_ref, subset in subset_rows(class_df, needed).items():
        if subset.height == 0:
            continue
        fixes[row_ref] = float(subset[fallback_col].fill_null(0.0).sum())
    if not fixes:
        return frame
    expr: pl.Expr = pl.col(ref)
    for row_ref, value in fixes.items():
        expr = pl.when(pl.col("row_ref") == row_ref).then(pl.lit(value)).otherwise(expr)
    return frame.with_columns(expr.alias(ref))


def _c08_off_bs_pre_ccf(
    frame: pl.DataFrame,
    class_df: pl.DataFrame,
    row_preds: Mapping[str, RowPredicate | None],
) -> pl.DataFrame:
    """Fill C 08.01/02 col 0100 with the off-BS slice of the 0090 waterfall.

    Col 0100 ("of which: off balance sheet") sits in the POST-CRM PRE-CCF
    column group (the 0090 "Exposure after CRM substitution pre CCFs"
    waterfall), so it reports the off-BS share of that PRE-conversion-factor
    quantity — NOT the post-CCF exposure value (that is col 0120). The
    executor has no intra-row sub-waterfall verb, so 0100 is derived here per
    row over the row's ``c08_bs == "off"`` legs, mirroring ``_value_cells`` +
    ``crm_substitution.crm_waterfall`` term-for-term:

        0100 = off-BS gross (0020: the sealed reporting_gross_off_bs carrier)
             - off-BS substitution outflow (0070: the ``c08_prot_block``
               subtotal cols 0040/0050/0060 break down)

    It carries the waterfall's OWN correction: reading the breakdown columns AND
    the outflow subtotal — as this did before — deducts the same covered part
    twice, exactly as ``crm_waterfall`` did. Binding the same per-leg subtotal
    col 0070 binds keeps the memo a true slice of 0090 by construction rather
    than by two derivations agreeing.

    THE B31 COL 0035 TERM IS DELIBERATELY ABSENT, and that is load-bearing rather
    than an oversight: col 0035 is the Art. 166(3) on-balance-sheet netting of
    loans and deposits, so it has no off-balance-sheet share to slice. The BoE
    scoping says the same thing structurally — ``boe_b0746_1`` drops the 0035 term
    from the col 0090 waterfall on exactly the off-balance-sheet row family
    (``crm_substitution.C08_01_NETTING_EXEMPT_ROWS``), so an off-BS memo that
    subtracted it would contradict the published rule for row 0030 while claiming
    to be its slice. Do not "restore" it for symmetry with the on-BS rows.

    It is computed on POSITIVE magnitudes read from the raw ``class_df`` (so
    the result is independent of the later ``_negate`` sign pass). The 0080
    substitution INFLOW is EXCLUDED: it is a total-row cross-sheet scalar
    (``ReportingContext.substitution_inflow``, a per-destination-class
    aggregate with no leg-level on/off-BS attribution), so an off-BS memo
    cannot claim a share of it — recorded decision, matching 0090's own
    convention that the inflow only lands on the (constraint-free) total row.

    Every leg is either on- or off-BS (``c08_bs``) and the outflow carrier is a
    leg-level amount pro-rated across the two-leg guarantee split, so summing it
    over the off-BS legs is the EXACT slice. Inert (None-predicate) rows are left
    as the null placeholder for ``_null_empty_rows``; C 08.02 has none.
    """
    if "0100" not in frame.columns:
        return frame
    cols = set(class_df.columns)
    if "c08_bs" not in cols:
        return frame
    active = {ref: pred for ref, pred in row_preds.items() if pred is not None}
    if not active:
        return frame
    fixes: dict[str, float] = {}
    for row_ref, subset in subset_rows(class_df, active).items():
        off = subset.filter(pl.col("c08_bs") == "off")
        off_cols = set(off.columns)
        gross = safe_sum(off, off_cols, "reporting_gross_off_bs")
        fixes[row_ref] = gross - safe_sum(off, off_cols, IRB_BLOCK_COL)
    expr: pl.Expr = pl.col("0100")
    for row_ref, value in fixes.items():
        expr = (
            pl.when(pl.col("row_ref") == row_ref)
            .then(pl.lit(value, dtype=pl.Float64))
            .otherwise(expr)
        )
    return frame.with_columns(expr.alias("0100"))


def _c08_after_all_crm(frame: pl.DataFrame) -> pl.DataFrame:
    """Fill C 08.01/02 col 0104 — exposure after ALL CRM, pre-conversion factors.

    PS1/26 Annex II (OF 08.01 col 0104): "Institutions shall report the value
    reported in column 0090 after adjusting for the reduction in exposure due to
    the Financial Collateral Comprehensive Method reported in columns 0101-0103."
    The published identity (boe_b1040) states it additively over the REPORTED
    (signed) cells::

        0104 = 0090 + 0101 + 0102

    — col 0103 is an "of which" sub-item of 0102 and is excluded, and 0102 is a
    "(-)"-labelled deduction, so on the POSITIVE magnitudes this pass sees (it
    runs before ``_negate``) the arithmetic is ``0090 + 0101 - 0102``.

    Cols 0101-0103 apply to slotting exposures only ("An institution shall only
    report values for exposures subject to the slotting approach") and are
    structural nulls today — no FCCM-under-slotting carrier is sealed — so 0104
    currently reproduces 0090 on every row. The subtraction is written out
    anyway so the cell stays truthful the day a carrier is wired.

    This is a post-execute pass and not a ``Formula`` cell because 0090, 0101 and
    0102 are themselves ``Formula`` cells and the executor refuses a formula that
    references another formula. A null 0090 (an inert row) keeps 0104 null for
    ``_null_empty_rows``; a frame without col 0104 (CRR, which has no FCCM
    column block) is left untouched.
    """
    if "0104" not in frame.columns or "0090" not in frame.columns:
        return frame
    total = pl.col("0090").fill_null(0.0)
    if "0101" in frame.columns:
        total = total + pl.col("0101").fill_null(0.0)
    if "0102" in frame.columns:
        total = total - pl.col("0102").fill_null(0.0)
    return frame.with_columns(
        pl.when(pl.col("0090").is_null())
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(total)
        .alias("0104")
    )


def _negate_expr(col: str) -> pl.Expr:
    """Negate a "(-)"-labelled deduction column, normalising a zero to ``+0.0``.

    Plain ``-pl.col(col)`` flips the IEEE sign bit, so a ``0.0`` cell would
    serialise as ``-0.0`` (``+ 0.0`` does NOT clear it in Polars); the explicit
    zero branch keeps a zero deduction as ``+0.0``. Null stays null (``== 0.0``
    is null on a null row, so the ``otherwise`` branch returns ``-null``). This
    is the identical expression used by C 07.00's ``_negate_deduction_cols``."""
    return pl.when(pl.col(col) == 0.0).then(pl.lit(0.0)).otherwise(-pl.col(col)).alias(col)


def _negate(frame: pl.DataFrame) -> pl.DataFrame:
    """Annex II §1.3: emit the "(-)"-labelled deduction columns negative on the
    C 08.01/02 surface (``_NEGATIVE_COLS``), AFTER the CRM waterfall (0090) has
    consumed their positive magnitudes. Intersecting with the frame's columns
    makes the framework-specific members (B31's 0035/0102/0103, CRR's 0256/0257)
    no-ops in the regime where the column is absent. A zero cell is emitted as
    ``+0.0`` (not ``-0.0`` — plain float negation flips the sign bit and Polars
    keeps it) and null stays null; identical expression to C 07.00's pass."""
    targets = [col for col in frame.columns if col in _NEGATIVE_COLS]
    if not targets:
        return frame
    return frame.with_columns(_negate_expr(col) for col in targets)


def _empty_frame(column_refs: tuple[str, ...], string_refs: tuple[str, ...] = ()) -> pl.DataFrame:
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "row_ref": pl.String,
        "row_name": pl.String,
    }
    for ref in column_refs:
        schema[ref] = pl.String if ref in string_refs else pl.Float64
    return pl.DataFrame(schema=schema)
