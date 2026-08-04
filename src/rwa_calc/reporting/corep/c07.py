"""
COREP C 07.00 — SA credit risk (per obligor-class sheets), declarative.

Pipeline position:
    sealed aggregator-exit ledger -> _prepare() -> one TemplateSpec per
    framework (built cols-aware) executed per exposure-class sheet
    -> dict[class, DataFrame]

Cell semantics (the recorded F4 decision —
docs/plans/phase7-declarative-reporting.md §6):

- EVERY SHEET IS TWO POPULATIONS, NOT ONE — the recorded two-basis decision.
  Annex II makes the front of the template and the back of it answer
  different questions, so a sheet's cells split by BASIS:
    * ORIGIN basis (``c07_basis_origin``) — the obligor's own book. Cols
      0010-0150: the gross exposure, the value adjustments, the CRM
      substitution block and the pre-conversion waterfall. A guaranteed leg
      belongs here on the OBLIGOR's sheet, because that is where its covered
      part is "deducted from the obligor's exposure class" (col 0090).
    * POST basis (``c07_basis_post``) — after substitution. Cols 0160-0235:
      the CCF breakdown, the exposure value, and the RWEA. Col 0200 is
      defined as the "exposure value after taking into account value
      adjustments, ALL CREDIT RISK MITIGANTS and conversion factors" —
      substitution is a credit risk mitigant, so the covered part must leave
      the obligor's sheet and land on the protection provider's, exactly as
      col 0090/0100 already move it pre-conversion. Cols 0160-0190 follow it
      because they break down col 0150, which is already post-substitution,
      and because ``v0308_m`` / ``boe_b0471`` test col 0200 AGAINST them.
  Binding col 0200/0220 to the ORIGIN population was a recorded build
  shortfall (F4 never extended substitution-awareness past the waterfall),
  not a decision: it left a fully-outflowed row reporting its raw EAD at the
  obligor's sheet and an inflow-only sheet reporting none at all, breaking
  ``v0308_m`` / ``v8726_m`` / ``boe_b0471`` / ``boe_b0556`` and putting this
  template on a different basis from Pillar 3 CR4 cols c-f and all of CR5,
  which cite col 0200 as the DEFINITION of their own post-substitution basis.
- Sheets key the OBLIGOR applied class on the origin basis (the sealed
  ``reporting_class_origin``) and the GUARANTOR class on the post basis (the
  sealed ``reporting_class``); the sheet AXIS is the union of both plus the
  classes receiving an inflow. Specialised lending is merged into corporate
  on BOTH keys (Art. 112(1)(g): SL is a corporate sub-type under SA; the SL
  "of which" rows split it back via sl_type) — an SL guarantor must key a
  sheet this template has. A frame that seals no ``reporting_class`` /
  ``reporting_approach`` (synthetic unit frames) degrades the post basis to
  the origin basis, so a book with no substitution reports identically under
  both and the split is number-neutral by construction.
- The population is the standardised book plus BOTH counterparty-credit-risk
  populations (``risk_type in {"CCR_SFT", "CCR_DERIVATIVE"}`` — SA-risk-weighted
  but tagged ``standardised_ccr`` under the output floor, so they are admitted by
  ``risk_type``, never by the approach label; relabelling the approach back would
  break the output floor, which routes on it).
  Annex II is explicit that C 07.00 covers CCR: rows 0070/0080 say "Exposures
  that are subject to counterparty credit risk shall be reported in rows
  0090 - 0130, and therefore shall not be reported in this row", row 0110 is
  "Derivatives and Long Settlement Transactions netting sets" (the ADDITIVE
  PARENT of the QCCP "of which" row 0120; 0100 is the same "of which" for the
  SFT row 0090), and cols 0210/0211 carry the CCR exposure value and its
  Art. 301(1) CCP-cleared exclusion. C 07.00 and C 34 are NOT alternatives —
  C 34 analyses CCR by approach, C 07.00 risk-weights those same exposures
  under SA; a derivative belongs in both, and no roll-up sums the two.
  Row 0130 (contractual cross-product netting sets, Art. 295(c)) is inert
  because it is NOT MODELLED — no input carrier exists for a cross-product
  netting agreement. See ``docs/plans/c07-ccr-derivatives.md``.
- The CRM substitution block (cols 0050-0090) reports ONLY what Annex II
  admits there — see ``_protection_exprs``. Cols 0050/0060 are the eligible
  unfunded protection (guarantees / credit derivatives), col 0070 the
  financial collateral incorporated under the Simple Method, col 0080 the
  Art. 232 "other funded credit protection" (Art. 200(1)(a)/(b)/(c)). SA
  immovable-property, receivables and other-physical collateral are
  DELIBERATELY ABSENT: Art. 199 makes them eligible under the IRB Approach
  only, and under SA the mortgage benefit arrives through the exposure class
  and its Art. 124-126 risk weight, so reporting them here would double-count
  it. The whole block is capped at the row's own exposure ("Collateral that
  has an effect on the exposure value ... shall be capped at the exposure
  value"), which is what keeps col 0110 non-negative.
- Substitution outflow (col 0090) is the Annex II subtotal of that block,
  0050 + 0060 + 0070 + 0080 — the covered part of each exposure that leaves
  the obligor's class for the protection provider's (rules ``v0305_m`` /
  ``boe_b0694``). Substitution inflow (col 0100) is a CROSS-SHEET and
  CROSS-TEMPLATE number, computed by ``corep/crm_substitution.py`` over the
  whole population per destination class and threaded to the total row 0010 via
  the ``ReportingContext.substitution_inflow`` side input (the out-of-frame
  escape; sub-rows report 0.0). Two properties of it are load-bearing and were
  both defects: it counts SAME-CLASS migrations (Annex II "Inflows and outflows
  within the same exposure classes shall also be reported" — gating it on a class
  change while the outflow subtotal counts every covered part made a same-class
  guarantee leak the covered amount out of col 0110), and it is ROUTED by the
  approach the substituted leg is treated under, so an SA guarantor's inflow
  reaches this template even when the guaranteed exposure is IRB. The sheet axis
  is correspondingly the union of the classes present and the classes receiving
  an inflow. The inflow mirror of the FUNDED limbs (0070 / 0080) is still not
  modelled: no collateral-issuer exposure class is carried, so those two limbs
  produce an outflow with no matching inflow — the recorded residual, kept
  visible rather than hidden by re-gating the outflow (which the live rule
  ``v0305_m`` fixes as the subtotal). C 08.01 col 0060 carries the same residual.
- The intra-row waterfalls are Formulas over positive magnitudes:
  0040 = 0010 - 0030 (- 0035 under Basel 3.1); 0090 = 0050 + 0060 + 0070
  + 0080; 0110 = 0040 - 0090 + 0100; 0150 = max(0, 0110 - 0130). 0110
  subtracts the components ONCE, through the 0090 subtotal — subtracting
  both the components and 0090 double-counts the outflow. The COREP
  Annex II §1.3 "(-)" sign convention is applied by a module post-step
  AFTER execution (negating {0030, 0035, 0050, 0060, 0070, 0080, 0090,
  0130, 0140} plus the CRR supporting-factor adjustments {0216, 0217};
  -0.0 normalised; null stays null).
- Row subsets reproduce the retired section builders as tolerant-equals
  terms over raw and module-derived discriminator columns (defaulted /
  SME / materially-dependent / qualifying-RE ladders, the RW band label,
  the CCF bucket, the substitution flag, on/off-balance-sheet). A row
  whose subset is EMPTY (or whose discriminators are absent) renders
  ALL-NULL — the retired ``_null_row`` contract — via a module post-step
  that re-applies each row's predicate.
- Cells whose sources are never produced render None via constant
  Formulas (0240; 0210/0211 when no ``risk_type`` / ``cp_entity_type``
  carrier is sealed; the CCF buckets and supporting-factor adjustments
  when their carriers are absent), preserving the recorded structural-null
  cells.
- The CCF buckets (0160-0190) are a breakdown of the **fully adjusted
  exposure value of off-balance-sheet items** — Annex II heads that block
  "BREAKDOWN OF THE FULLY ADJUSTED EXPOSURE VALUE OF OFF-BALANCE SHEET
  ITEMS BY CONVERSION FACTORS". They therefore sum the PRE-conversion
  off-balance-sheet gross (``reporting_gross_off_bs`` — the same carrier
  col 0010 sums on the off-side, so 0150 decomposes into them by
  construction, on the POST basis they share with it), narrowed to the
  off-balance-sheet side, NOT the post-conversion ``ead_final``. Col 0200
  is what survives conversion, and
  the two are related by the supervisory identity ``boe_b0471``:
  ``{c0200} = {c0150} - 0.9*{c0160} - 0.8*{c0170} - 0.6*{c0171}
  - 0.5*{c0180}``. Summing EAD here would break that rule, ``v6364_m``
  (``{c0150} = {c0160}+{c0170}+{c0180}+{c0190}`` on row 0080) and the EBA
  equivalents ``v1659_m`` / ``v1661_m`` simultaneously.

References:
- CRR Art. 111-113 (SA exposure values / RWEA); Art. 501/501a
  (supporting factors); Art. 199 (collateral eligible under IRB only),
  Art. 200/232 (other funded credit protection), Art. 222 (FCSM),
  Art. 235 (covered / uncovered split); COREP Annex II C 07.00
  ¶40-43/¶56/¶56A (class assignment + substitution); PRA PS1/26
  Annex II/App. 17 (OF 07.00)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8, decision F4)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, NamedTuple

import polars as pl
from watchfire import cites

from rwa_calc.domain.enums import ExposureClass
from rwa_calc.reporting.cellspec import (
    CellSpec,
    Formula,
    RowPredicate,
    SafeSum,
    SideContext,
    Sum,
    TemplateSpec,
    execute,
)
from rwa_calc.reporting.corep.crm_substitution import irb_origin_inflows
from rwa_calc.reporting.corep.postpass import negate_deduction_cols, null_empty_rows
from rwa_calc.reporting.corep.templates import (
    get_c07_columns,
    get_sa_risk_weight_bands,
    get_sa_row_sections,
)
from rwa_calc.reporting.kernel import (
    TwoBasis,
    class_keys,
    pick,
    population_flags,
    sheet_axis,
    sheet_frame,
)
from rwa_calc.reporting.kernel.bases import ORIGIN_APPROACH_SOURCE
from rwa_calc.reporting.metadata import SUBSTITUTION_INFLOW_RW_PREFIX, ReportingContext
from rwa_calc.reporting.plans import SheetPlan

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

# COREP Annex II §1.3 "(-)"-labelled deduction columns, negated post-execute.
# 0216/0217 are the CRR-only "(-) SME/Infrastructure supporting factor adjustment"
# columns (Art. 501/501a) — reported negative so 0215 + 0216 + 0217 = 0220 foots.
_NEGATIVE_COLS: frozenset[str] = frozenset(
    {"0030", "0035", "0050", "0060", "0070", "0080", "0090", "0130", "0140", "0216", "0217"}
)

# The two-basis discriminators (see the module docstring). The mechanism —
# derived boolean columns rather than ``RowPredicate`` fields, and why that is
# the only shape the post basis can DEGRADE in — lives in
# ``reporting/kernel/bases.py``, shared with C 08.01.
_BASIS: TwoBasis = TwoBasis("c07")
_BASIS_ORIGIN_COL: str = _BASIS.basis_origin
_BASIS_POST_COL: str = _BASIS.basis_post
_ORIGIN_APPROACH_SOURCE: str = ORIGIN_APPROACH_SOURCE

# The ``c07_bs`` labels rows 0070 / 0080 filter on, and the keys the col 0100
# inflow is split by when it lands on them.
_ON_BS: str = "on"
_OFF_BS: str = "off"

# Col 0030 provisions carriers, in preference order: the specific / general
# provision input pass-throughs (never sealed on the aggregator exit — present
# only on synthetic unit frames a book supplies) then the sealed SA Art. 111(2)
# deducted provision. Any one present drives the c07_provision derivation in
# _prepare; none present keeps the retired SafeSum(scra, gcra) binding.
_PROVISION_SOURCES: frozenset[str] = frozenset(
    {"scra_provision_amount", "gcra_provision_amount", "provision_deducted"}
)

# CCF bucket maps: the applied conversion factor (rounded to 4dp) -> column ref.
# CRR Art. 111 / Annex I has four buckets; PRA PS1/26 Art. 111 Table A1 has five
# (Row 5 "other commitments" 40% is new, and Row 7 UCC moves 0% -> 10%).
_CCF_MAP_CRR: dict[float, str] = {0.0: "0160", 0.2: "0170", 0.5: "0180", 1.0: "0190"}
_CCF_MAP_B31: dict[float, str] = {0.1: "0160", 0.2: "0170", 0.4: "0171", 0.5: "0180", 1.0: "0190"}
_CCF_REFS: tuple[str, ...] = ("0160", "0170", "0171", "0180", "0190")

# Applied-CCF carriers, in preference order. ``ccf`` is the sealed
# aggregator-exit name the pipeline really produces (and the one C 08.01 / CR5 /
# CR6 already read); ``ccf_applied`` is the synthetic COREP/Pillar 3 unit-frame
# spelling, kept so the shim estate keeps working. C 07.00 read ONLY the latter
# until 2026-08, so every real submission published structurally-null CCF buckets
# and four supervisory rules were unevaluable — hence the resolution is a single
# named ladder and its absence is logged, never silently tolerated. Converging
# the synthetic estate onto ``ccf`` is a recorded follow-up, not done here.
_CCF_CARRIERS: tuple[str, ...] = ("ccf", "ccf_applied")

# Pre-conversion off-balance-sheet gross: what the CCF buckets break down, and
# the same carrier col 0010 sums on the off-side (so 0150 decomposes into the
# buckets by construction — see the module docstring on boe_b0471 / v6364_m).
_OFF_BS_GROSS_COL: str = "reporting_gross_off_bs"

# Col 0080 "(-) Other funded credit protection, Article 232 CRR": the SA
# carriers for the protection Art. 232 recognises, which is exactly the
# Art. 200(1) list — (a) cash on deposit with a third-party institution
# (Art. 232(1), treated as a guarantee by that institution) and (b) life
# insurance policies pledged to the lender (Art. 232(2)). Art. 200(1)(c)
# instruments repurchased on request (Art. 232(4)) is NOT MODELLED — no input
# carrier exists — so it is absent rather than silently folded in.
#
# What is deliberately NOT here: ``collateral_re_value`` /
# ``collateral_receivables_value`` / ``collateral_other_physical_value``. Those
# are the Art. 199 IRB carriers (C 08.01 cols 0190/0200/0210 read them, which is
# where they belong). Art. 199 is headed "Additional eligibility for collateral
# under the IRB Approach" and opens "institutions that calculate risk-weighted
# exposure amounts and expected loss amounts under the IRB Approach may also use
# the following forms of collateral: (a) immovable property collateral ...;
# (b) receivables ...; (c) other physical collateral". None of it is eligible
# funded credit protection under the Standardised Approach, so none of it can
# produce an SA substitution effect: under SA an immovable-property security
# drives the exposure CLASS and the Art. 124-126 risk weight instead. Reporting
# it in col 0080 while also risk-weighting the mortgage at its RE weight
# double-counts the same benefit, and it drove col 0110 negative (a 60%-LTV
# mortgage put 666,667 of property against a 400,000 exposure).
_OFCP_CARRIERS: tuple[str, ...] = ("life_ins_collateral_value", "third_party_deposit_value")

# Col 0070 "(-) Financial collateral: Simple method" (Art. 222(1)-(2)).
_FCSM_CARRIER: str = "fcsm_collateral_value"

# The capped unfunded limb (cols 0050 + 0060 per row) that col 0100's inflow is
# measured on — see ``_protection_exprs``.
_UNFUNDED_COL: str = "c07_prot_unfunded"
# The CRM decline flag — CONDITIONAL on the edge, so every read is presence-tolerant.
# A DECLINED guarantee (it would have raised capital, which CRR Art. 193(1)
# forbids) produces no substitution effect, so it must not appear in the Annex II
# block headed "CRM TECHNIQUES WITH SUBSTITUTION EFFECTS ON THE EXPOSURE". Gating
# the unfunded magnitude gates the col 0100 INFLOW too, since that binds the same
# carrier. Basis and the recorded elections (decline vs apply-and-cap; the strict
# ``<``): ``engine/sa/rw_adjustments.py::apply_guarantee_substitution``.
_BENEFICIAL_COL: str = "is_guarantee_beneficial"

# The guarantor's exposure class (the col 0100 destination key) and the origin
# approaches whose inflow half ``crm_substitution.irb_origin_inflows`` owns.
_POST_CRM_CLASS_COL: str = "post_crm_exposure_class_guaranteed"
_IRB_ORIGINS: tuple[str, ...] = ("foundation_irb", "advanced_irb", "slotting")

# Col 0010's gross carriers — reused as the cap basis for the 0050-0100 block
# (the row's own contribution to col 0040, i.e. gross net of value adjustments).
_GROSS_CARRIERS: tuple[str, ...] = (
    "reporting_gross_on_bs",
    _OFF_BS_GROSS_COL,
    "c07_ccr_gross",
)

# What counts as counterparty credit risk in C 07.00: the population limb
# (``c07_population``) and the "of which: arising from CCR" discriminator (cols
# 0210/0211) read the SAME set. All three members are SA-risk-weighted but carry
# ``standardised_ccr`` under the output floor, so they are admitted by risk_type,
# never by the approach label.
#
# The CCR set is THREE risk types, not two: FCCM SFT synthetic rows, SA-CCR
# derivative netting sets, and ``CCR_DEFAULT_FUND`` — CCP default-fund
# contributions (Art. 307-309), which are Chapter 6 counterparty credit risk just
# as much as the other two. Do not trim it back to two: without it the population
# would silently depend on the approach LABEL (default-fund rows carry
# ``approach_applied == "standardised"``, so they reach C 07.00 anyway today — the
# limb makes the intent explicit), and the 0210/0211 "of which CCR" columns would
# under-report a book that holds default-fund contributions. It also keeps this
# template's definition of CCR identical to OF 02.01's and CMS1's, so one
# submission cannot carry two contradictory definitions.
#
# Deliberately LOCAL to C 07.00 (docs/plans/c07-ccr-derivatives.md §4 D4): each
# template owns its own tuple — a shared risk-type constant is how one template's
# basis leaks into CR4/CR5/OV1, which key their own recorded bases.
_CCR_RISK_TYPES: tuple[str, ...] = ("CCR_SFT", "CCR_DERIVATIVE", "CCR_DEFAULT_FUND")

# Section 1 "of which" maps (retired _C07_* constants, preserved verbatim).
_SL_TYPE_MAP: dict[str, str] = {
    "0021": "object_finance",
    "0022": "commodities_finance",
    "0023": "project_finance",
}
_PF_PHASE_MAP: dict[str, str] = {
    "0024": "pre_operational",
    "0025": "operational",
    "0026": "high_quality_operational",
}
# The POST-basis gate on the specialised-lending "of which" rows 0021-0026: does
# this leg still apply its OWN Art. 122B risk-weight treatment? ``sl_type`` is
# the OBLIGOR's characteristic and the CRM split never reassigns it, so a covered
# part substituted onto a protection provider's risk weight carries the obligor's
# ``sl_type`` onto the GUARANTOR's sheet, where the post-basis cells (0160-0235)
# would report it as the guarantor's specialised lending.
#
# Annex II admits a row 0021-0026 exposure on THREE conjunctive conditions, the
# third of which is the applied risk weight: row 0023 is "only exposures which
# are 'project finance exposures' ..., assigned to the exposure class 'Exposures
# to corporates' ..., [and] apply the risk weight treatment in accordance with
# Articles 122B(2)(c) or 122B(4)" (PS1/26 Annex II p.89; rows 0024-0026 spell the
# same limb "(d) subject to the risk weight treatment in accordance with Article
# 122B(2)(c)"). A substituted-in covered part applies the PROVIDER's Art. 122
# weight, not Art. 122B — and ¶43 says so directly: "the substitution effect ...
# shall reflect the risk weighting treatment effectively applicable to the
# covered part of the exposure". So it fails the third condition and belongs in
# NEITHER row 0023 nor its phase children.
#
# ORIGIN basis deliberately UNCHANGED: cols 0010-0150 are the obligor's own book,
# where ¶42/¶56A require the covered part to be shown leaving the obligor's class
# through col 0090. Derived rather than expressed as a bare
# ``(_BENEFICIAL_COL, False)`` term for the ``c07_qccp`` reason — that compiles to
# ``== False``, so a NULL flag would drop every unguaranteed SL exposure out of
# its own row.
_SL_OWN_RW_COL: str = "c07_sl_own_rw"
_CIU_ROW_APPROACH: dict[str, str] = {
    "0281": "look_through",
    "0282": "mandate_based",
    "0283": "fallback",
}
# Memo defaulted-at-RW rows: ref -> the RW band label (Art. 127 100%/150%).
_MEMO_DEFAULTED_RW: dict[str, str] = {"0300": "100%", "0320": "150%"}
_MEMO_RE_SECURED: dict[str, str] = {"0290": "commercial", "0310": "residential"}
_RE_ROW_FILTERS: dict[str, dict[str, Any]] = {
    "0330": {"property_type": "residential"},
    "0331": {"property_type": "residential", "materially_dependent": False},
    "0332": {"property_type": "residential", "materially_dependent": True},
    "0340": {"property_type": "commercial"},
    "0341": {"property_type": "commercial", "materially_dependent": False, "is_sme": False},
    "0342": {"property_type": "commercial", "materially_dependent": True},
    "0343": {"property_type": "commercial", "materially_dependent": False, "is_sme": True},
    "0344": {"property_type": "commercial", "materially_dependent": True, "is_sme": True},
    "0350": {"is_qualifying": False},
    "0351": {"is_qualifying": False, "property_type": "residential", "materially_dependent": False},
    "0352": {"is_qualifying": False, "property_type": "residential", "materially_dependent": True},
    "0353": {"is_qualifying": False, "property_type": "commercial", "materially_dependent": False},
    "0354": {"is_qualifying": False, "property_type": "commercial", "materially_dependent": True},
    "0360": {"is_adc": True},
}
_EQUITY_TRANSITIONAL_FILTERS: dict[str, tuple[str, bool]] = {
    "0371": ("sa_transitional", True),
    "0372": ("sa_transitional", False),
    "0373": ("irb_transitional", True),
    "0374": ("irb_transitional", False),
}

_Terms = tuple[tuple[str, str | bool], ...]


def _const(value: float | None):  # noqa: ANN202 - tiny Formula factory
    def fn(_cells: Mapping[str, float | None], _prior: bool) -> float | None:
        return value

    return fn


def _net_of_adjustments(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0040 = 0010 - 0030 - 0035 (positive magnitudes; 0035 absent under CRR)."""
    return (cells["0010"] or 0.0) - (cells["0030"] or 0.0) - (cells.get("0035") or 0.0)


def _substitution_outflow(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0090 = 0050 + 0060 + 0070 + 0080 (positive magnitudes).

    Annex II C 07.00 cols 0090/0100: "Outflows shall correspond to the covered
    part of the Original Exposure pre-conversion factors that is deducted from
    the obligor's exposure class and subsequently assigned to the protection
    provider's exposure class" — for exposures under the risk-weight
    substitution method AND for collateral recognised under the Financial
    Collateral Simple Method or the Other Funded Credit Protection Method. The
    covered part under each of those four routes is exactly cols 0050-0080, so
    the outflow is their subtotal (rules ``v0305_m`` / ``boe_b0694``).
    """
    return sum((cells.get(ref) or 0.0) for ref in ("0050", "0060", "0070", "0080"))


def _net_after_substitution(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0110 = 0040 - 0090 + 0100 (rule ``v0306_m`` / ``boe_b0697``).

    0090 already IS 0050 + 0060 + 0070 + 0080, so the components are removed
    once, through the subtotal. Subtracting both them and 0090 — as this did
    before — deducts every substitution outflow twice.
    """
    return (cells["0040"] or 0.0) - (cells["0090"] or 0.0) + (cells["0100"] or 0.0)


def _fully_adjusted(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0150 = max(0, 0110 - 0130)."""
    return max(0.0, (cells["0110"] or 0.0) - (cells["0130"] or 0.0))


@cites("PS1/26, paragraph 1.3")
def c07_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-obligor-class execution plans for C 07.00.

    Preserves the generator's contracts: missing EAD/RWA columns record
    "C07: Missing EAD or RWA columns in results"; a missing class column records
    "C07: Missing exposure_class column"; an empty SA population yields ``{}``.
    """
    # Phase 7 convergence: the sealed obligor applied class, single name
    # (== the retired exposure_class_applied/exposure_class ladder).
    ec_col = pick(cols, "reporting_class_origin")
    ead_col = pick(cols, "ead_final")
    rwa_col = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
    if ec_col is None or ead_col is None or rwa_col is None:
        if ead_col is None or rwa_col is None:
            errors.append("C07: Missing EAD or RWA columns in results")
        if ec_col is None:
            errors.append("C07: Missing exposure_class column")
        return {}

    sa_df = c07_population(results, cols, both_bases=True).collect()
    # Resolved BEFORE the empty-population guard: an all-IRB book guaranteed by
    # an SA counterparty has NO SA leg of its own, and the early exit would drop
    # the inflow this template is the only home for.
    inflows = _sa_inflows(results, cols, framework)
    if len(sa_df) == 0 and not inflows.total:
        return {}

    # The two sheet keys, Art. 112 Table A2 merge applied to BOTH (SL is a
    # corporate sub-type under SA). The post key degrades to the origin key on a
    # frame that seals no ``reporting_class``, which is what makes the two-basis
    # split number-neutral wherever nothing substitutes.
    sa_df = sa_df.with_columns(
        class_keys(_BASIS, set(sa_df.columns), ec_col, key=_merge_specialised_lending)
    )
    data_cols = set(sa_df.columns)
    sa_df = _prepare(sa_df, data_cols, framework)
    _warn_if_ccf_buckets_unreportable(sa_df, data_cols)
    # The SA-origin half joins the cross-template half only now: it is measured on
    # THIS template's capped carrier, which _prepare has just derived.
    inflows = _add_sa_origin_inflows(inflows, sa_df)

    row_terms = _row_terms(framework, data_cols)
    spec = _build_spec(framework, data_cols, ead_col, rwa_col, row_terms)

    plans: dict[str, SheetPlan] = {}
    # Sealed-ledger rule: the class columns always exist; a null key (no source
    # on a synthetic frame) partitions into NO sheet. The axis is the UNION of
    # the classes present on EITHER basis and the classes RECEIVING an inflow —
    # Annex II requires in- and outflows to and from other templates to be taken
    # into account, which an inflow with no sheet to land on cannot satisfy. The
    # post-basis limb is belt-and-braces: a beneficially-substituted leg's
    # guarantor class is an inflow key too, so in practice it adds no sheet — but
    # without it a leg whose inflow the block cap shed to zero would drop its
    # exposure value and RWEA out of the template silently. An inflow-only sheet
    # keeps its constraint-free total row 0010 and reports 0110 = 0100.
    axis = sheet_axis(_BASIS, sa_df) | set(inflows.total)
    for ec in sorted(axis):
        sides = inflows.by_side.get(ec, {})
        bands = inflows.by_rw_band.get(ec, {})
        plans[ec] = SheetPlan(
            spec=spec,
            frame=sheet_frame(_BASIS, sa_df, ec),
            ctx=ReportingContext(
                substitution_inflow=inflows.total.get(ec, 0.0),
                substitution_inflow_on_bs=sides.get(_ON_BS, 0.0),
                substitution_inflow_off_bs=sides.get(_OFF_BS, 0.0),
                substitution_inflow_by_rw=bands,
            ),
            negative_cols=_NEGATIVE_COLS,
            row_terms=row_terms,
            inflow_rows=_inflow_rows(row_terms, sides, bands),
        )
    return plans


def _merge_specialised_lending(class_col: str) -> pl.Expr:
    """Art. 112 Table A2: SL is a corporate sub-type under SA, so it is merged
    into corporate before keying a sheet (the SL "of which" rows split it back
    via ``sl_type``). Applied to BOTH sheet keys, so an SL guarantor's covered
    part keys a sheet this template actually has."""
    return (
        pl.when(pl.col(class_col) == ExposureClass.SPECIALISED_LENDING.value)
        .then(pl.lit(ExposureClass.CORPORATE.value))
        .otherwise(pl.col(class_col))
    )


@cites("PS1/26, paragraph 1.3")
def generate_c07(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 07.00 per obligor-class sheet over the sealed ledger."""
    result: dict[str, pl.DataFrame] = {}
    for ec, plan in c07_plans(results, cols, framework, errors).items():
        frame = execute(plan.spec, plan.frame, plan.ctx)
        # ``row_terms`` -> predicates: ``None`` is an inert row, ``()`` the
        # constraint-free Total row (never nulled), anything else constrained.
        preds = {
            ref: None if terms is None else RowPredicate(equals=terms)
            for ref, terms in plan.row_terms.items()
        }
        frame = null_empty_rows(frame, plan.frame, preds, plan.inflow_rows)
        result[ec] = negate_deduction_cols(frame, _NEGATIVE_COLS)
    return result


@cites("PS1/26")
def c07_population(
    results: pl.LazyFrame, cols: set[str], *, both_bases: bool = False
) -> pl.LazyFrame:
    """The C 07.00 population: the standardised book plus the CCR rows.

    ``both_bases`` selects WHICH standardised book. The default is the
    ORIGIN-approach one — the obligor's own book, and the only thing C 09.01
    (which shares this population for its geographical breakdown) asks for.
    C 07.00 itself takes the UNION of the origin-approach book and the
    POST-substitution one, tagged with ``c07_pop_origin`` / ``c07_pop_post`` so
    each cell reads its own basis (module docstring). A leg with no substitution
    is in both, which is why the split is number-neutral on a book that never
    substitutes. The post limb is what carries an IRB-origin leg guaranteed by an
    SA protection provider onto this template: its exposure value and RWEA belong
    on the guarantor's SA sheet under Art. 235, which is where col 0100 already
    routes its inflow. Widening C 09.01 the same way is a separate question with
    its own goldens, so the default deliberately does not.

    The CCR limb admits ALL THREE counterparty-credit-risk risk types by
    ``risk_type`` — Annex II puts them in rows 0090-0130, and C 07.00
    risk-weights under SA the very exposures C 34 analyses by approach.
    Admission cannot key the approach label: under the output floor
    ``engine/stages/calc.py`` relabels CCR rows to ``standardised_ccr`` so they
    route into the floor-eligible approaches, which is load-bearing and must NOT
    be undone here. CCR legs join BOTH bases: substitution does not move them.

    The dedupe keys the exposure reference, which the sealed ledger always
    carries. The ``subset=None`` fallback (synthetic unit frames only, where no
    reference column exists) dedupes on ALL columns — two genuinely distinct
    exposures identical in every column would collapse into one. Harmless where
    it can fire; do not promote this fallback to the ledger path.
    """
    ccr = (
        pl.col("risk_type").is_in(_CCR_RISK_TYPES).fill_null(value=False)
        if "risk_type" in cols
        else None
    )
    tagged = results.with_columns(population_flags(_BASIS, cols, ("standardised",), admit=ccr))
    admitted = (
        tagged.filter(pl.col(_BASIS.pop_origin) | pl.col(_BASIS.pop_post))
        if both_bases
        else tagged.filter(pl.col(_BASIS.pop_origin)).drop(_BASIS.pop_origin, _BASIS.pop_post)
    )
    return admitted.unique(
        subset=["exposure_reference"] if "exposure_reference" in cols else None,
        keep="first",
    )


def _has_bs_side(cols: set[str]) -> bool:
    """True when ``_prepare`` can derive ``c07_bs`` from this column set.

    The single source of truth for that question. ``_prepare`` prefers
    ``bs_type`` and falls back to ``exposure_type``; any cell narrowing on
    ``c07_bs`` must ask the SAME question or it silently stops narrowing on the
    ledger path, where only ``exposure_type`` is sealed.
    """
    return "bs_type" in cols or "exposure_type" in cols


def _warn_if_ccf_buckets_unreportable(data: pl.DataFrame, cols: set[str]) -> None:
    """WARN when C 07.00 will publish null CCF buckets despite off-BS exposure.

    Cols 0160-0190 need an applied-CCF carrier. When none is present the cells
    render structurally null and ``boe_b0471`` / ``v6364_m`` / ``v1659_m`` /
    ``v1661_m`` cannot be evaluated on the submission. That is legitimate for a
    book with no off-balance-sheet items, so the warning is gated on there being
    something to break down — otherwise every on-balance-only frame would warn.

    This exists because the carrier-name defect (C 07.00 read ``ccf_applied``,
    which no pipeline run produces) failed silently for the life of the template.
    """
    if pick(cols, *_CCF_CARRIERS) is not None or _OFF_BS_GROSS_COL not in cols:
        return
    off_bs_total = float(data[_OFF_BS_GROSS_COL].fill_null(0.0).sum())
    if off_bs_total <= 0.0:
        return
    logger.warning(
        "C 07.00: no applied-CCF carrier (tried %s) but %.0f of off-balance-sheet "
        "gross exposure is in scope — columns 0160-0190 will report null and the "
        "CCF-breakdown validation rules cannot be evaluated",
        ", ".join(_CCF_CARRIERS),
        off_bs_total,
    )


def _prepare(data: pl.DataFrame, cols: set[str], framework: str) -> pl.DataFrame:
    """Add the module-derived discriminator columns (each only when its
    sources exist — an underived column makes its tolerant terms match
    nothing, reproducing the retired absent-column null rows)."""
    exprs: list[pl.Expr] = []

    # Defaulted ladder (retired _filter_defaulted, verbatim precedence).
    if "is_defaulted" in cols:
        exprs.append(pl.col("is_defaulted").fill_null(value=False).alias("c07_defaulted"))
    elif "default_status" in cols:
        exprs.append((pl.col("default_status") == True).alias("c07_defaulted"))  # noqa: E712
    elif "exposure_class_applied" in cols or "exposure_class" in cols:
        class_col = (
            "exposure_class_applied" if "exposure_class_applied" in cols else "exposure_class"
        )
        exprs.append((pl.col(class_col) == "defaulted").alias("c07_defaulted"))
    elif "pd_floored" in cols:
        exprs.append((pl.col("pd_floored") >= 1.0).alias("c07_defaulted"))

    # SME ladder (retired _filter_sme).
    if "sme_supporting_factor_eligible" in cols:
        exprs.append(
            (pl.col("sme_supporting_factor_eligible") == True).alias("c07_sme")  # noqa: E712
        )
    elif "exposure_class" in cols:
        exprs.append(
            pl.col("exposure_class").str.contains("sme").fill_null(value=False).alias("c07_sme")
        )

    # On/off-balance-sheet (kernel rule: bs_type preferred, else exposure_type).
    # Derivability is asked ONCE, via _has_bs_side: the CCF-bucket cells narrow on
    # ``c07_bs`` and used to gate that narrowing on ``bs_type`` alone — a column
    # the aggregator never seals — so on the ledger path the narrowing silently
    # never applied. The two sites must not drift again.
    if "bs_type" in cols:
        exprs.append(
            pl.when(pl.col("bs_type") == "ONB")
            .then(pl.lit("on"))
            .when(pl.col("bs_type") == "OFB")
            .then(pl.lit("off"))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("c07_bs")
        )
    elif "exposure_type" in cols:
        exprs.append(
            pl.when(pl.col("exposure_type") == "loan")
            .then(pl.lit("on"))
            .when(pl.col("exposure_type").is_in(["facility", "contingent", "facility_undrawn"]))
            .then(pl.lit("off"))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("c07_bs")
        )

    # Original-exposure gross for the non-credit-risk legs C 07.00 KEEPS but the
    # credit-risk side carriers (reporting_gross_on_bs / _off_bs) null out. Unlike
    # C 08.x / CR4-CR6 (which disclose CCR separately and so drop it from their
    # gross columns), C 07.00 includes counterparty credit risk (Annex II rows
    # 0090-0130), so col 0010 must carry the CCR / settlement legs' original
    # exposure too. Their EAD sits in drawn_amount (no CCF applies), so this is
    # the pre-fix SafeSum(reporting_gross_drawn, reporting_gross_undrawn) restored
    # for exactly those legs — null on a credit-risk leg, where the side carriers
    # already carry the gross. The gate list is EXACTLY the four exposure_types the
    # side carriers populate (loan / contingent / facility_undrawn + the "facility"
    # legacy alias, Amendment 2), so col 0010's SafeSum(on_bs, off_bs, c07_ccr_gross)
    # counts every leg once on exactly one carrier — a "facility" leg must be null
    # here or its off-side gross would double-count.
    if {"exposure_type", "reporting_gross_drawn", "reporting_gross_undrawn"} <= cols:
        exprs.append(
            pl.when(
                pl.col("exposure_type").is_in(
                    ["loan", "contingent", "facility_undrawn", "facility"]
                )
            )
            .then(pl.lit(None, dtype=pl.Float64))
            .otherwise(
                pl.sum_horizontal(
                    pl.col("reporting_gross_drawn"), pl.col("reporting_gross_undrawn")
                )
            )
            .alias("c07_ccr_gross")
        )

    # RW band label (retired _compute_rw_section_rows assignment).
    if "risk_weight" in cols:
        exprs.append(_rw_band_expr(framework).alias("c07_rw_band"))

    # CCF bucket ref (retired _c07_ccf_cols map), off the resolved carrier.
    ccf_col = pick(cols, *_CCF_CARRIERS)
    if ccf_col is not None:
        ccf_map = _CCF_MAP_B31 if framework == "BASEL_3_1" else _CCF_MAP_CRR
        bucket_expr: pl.Expr = pl.lit(None, dtype=pl.String)
        for ccf_value, ref in ccf_map.items():
            bucket_expr = (
                pl.when(
                    pl.col(ccf_col).cast(pl.Float64, strict=False).round(4) == round(ccf_value, 4)
                )
                .then(pl.lit(ref))
                .otherwise(bucket_expr)
            )
        exprs.append(bucket_expr.alias("c07_ccf_bucket"))

    # Materially-dependent ladder (exact field keeps nulls-excluded; proxies
    # fill null to False — retired _filter_re_materially_dependent).
    if "materially_dependent_on_property" in cols:
        exprs.append(pl.col("materially_dependent_on_property").alias("c07_md"))
    elif "has_income_cover" in cols:
        exprs.append(pl.col("has_income_cover").fill_null(value=False).alias("c07_md"))
    elif "is_income_producing" in cols:
        exprs.append(pl.col("is_income_producing").fill_null(value=False).alias("c07_md"))

    if "property_type" in cols:
        exprs.append(pl.col("property_type").is_not_null().alias("c07_has_property"))
    if "is_qualifying_re" in cols:
        exprs.append(pl.col("is_qualifying_re").fill_null(value=True).alias("c07_qualifying_re"))
    if "ppu_reason" in cols:
        exprs.append(
            pl.col("ppu_reason")
            .str.starts_with("art_150_1_")
            .fill_null(value=False)
            .alias("c07_ppu")
        )
    if "sa_cqs" in cols:
        exprs.append(pl.col("sa_cqs").is_not_null().alias("c07_rated"))

    # Post-basis specialised-lending gate (rows 0021-0026) — see _SL_OWN_RW_COL.
    # The complement of the ``_protection_exprs`` substitution gate, read the same
    # null-safe way (an unknown benefit is not a substitution), so the row
    # exclusion and the col 0090/0100 flow are driven by ONE flag and cannot
    # drift: exactly the legs whose covered part left for a provider's risk
    # weight are the legs that stop applying Art. 122B.
    if _BENEFICIAL_COL in cols:
        exprs.append(
            (pl.col(_BENEFICIAL_COL) == True)  # noqa: E712 - null-safe, see _protection_exprs
            .fill_null(value=False)
            .not_()
            .alias(_SL_OWN_RW_COL)
        )

    # CCR discriminators (cols 0210/0211). 0210 = "of which: arising from
    # counterparty credit risk"; 0211 = the same, excluding the Art. 301(1)
    # CCP-cleared transactions. RowPredicate carries no negation, so the
    # "excluding CCP" side is derived here as its own flag.
    if "risk_type" in cols:
        is_ccr = pl.col("risk_type").is_in(_CCR_RISK_TYPES).fill_null(value=False)
        exprs.append(is_ccr.alias("c07_ccr"))
        if "cp_entity_type" in cols:
            exprs.append(
                (is_ccr & (pl.col("cp_entity_type").fill_null("") != "ccp")).alias(
                    "c07_ccr_non_ccp"
                )
            )

    # QCCP discriminator (the "of which: cleared through a QCCP" rows 0100/0120).
    # The project-wide canonical form, mirrored verbatim: a ``ccp`` entity_type
    # whose flag is not an EXPLICIT False (CRR Art. 272 Def (88) / Art. 306 — an
    # absent flag is treated as qualifying; only an explicit False demotes a
    # ``ccp`` to the Art. 107(2)(a) institution ladder). Identical to
    # engine/sa/risk_weights.py's 2%/4% override, the aggregator's
    # ``rwa_ccr_qccp_trade`` partition and Pillar 3 CCR8. It MUST be derived
    # rather than expressed as a RowPredicate term: a bare ("cp_is_qccp", True)
    # compiles to ``== True``, so a NULL flag would drop a netting set that the
    # very same sheet already reports in the 2% risk-weight band.
    if {"cp_entity_type", "cp_is_qccp"} <= cols:
        exprs.append(
            ((pl.col("cp_entity_type") == "ccp") & pl.col("cp_is_qccp").fill_null(value=True))
            .fill_null(value=False)
            .alias("c07_qccp")
        )

    # Collateral volatility/maturity adjustment (col 0140 = market - Cvam).
    if "collateral_market_value" in cols:
        adjusted = (
            pl.col("collateral_adjusted_value").fill_null(0.0)
            if "collateral_adjusted_value" in cols
            else pl.lit(0.0)
        )
        exprs.append(
            (pl.col("collateral_market_value").fill_null(0.0) - adjusted).alias("c07_vol_mat_adj")
        )

    # Supporting-factor RWEA delta (cols 0216/0217 = pre - post per row).
    if "rwa_pre_factor" in cols:
        rwa_source = pick(cols, "rwa_final", "rwa_post_factor", "rwa")
        if rwa_source is not None:
            exprs.append(
                (pl.col("rwa_pre_factor").fill_null(0.0) - pl.col(rwa_source).fill_null(0.0)).alias(
                    "c07_sf_delta"
                )
            )

    # Col 0030 provisions magnitude (Annex II "(-) Value adjustments and
    # provisions associated with the original exposure"). SCRA/GCRA-preferred,
    # SA-carrier fallback ladder — the same preference ORDER as C 08.01/02's
    # provisions ladder (``_provisions_postfix``), but at a different GRANULARITY
    # and derived at a different point:
    #   - Granularity (the recorded C 07 contract): the pick is PER EXPOSURE ROW
    #     here — each row takes its own scra+gcra when non-degenerate, else its
    #     own provision_deducted — then the row cell sums those picks. C 08
    #     decides PER CELL: it aggregates scra/gcra over the whole row subset and
    #     swaps the entire cell to provision_held only when that aggregate nets
    #     to ~0. The two diverge only on a frame where some rows carry scra/gcra
    #     and others do not; per-row is deliberate and pinned by
    #     test_c07_provisions.py::test_mixed_frame_picks_per_row_not_per_cell.
    #   - Timing: derived HERE pre-execute (a c07_provision column) rather than as
    #     a post-execute patch, because col 0040's Formula (0010 - 0030) must
    #     consume the corrected magnitude in the SAME execute pass (0290 on C 08
    #     has no dependent formula, so C 08 can patch it after execute).
    # The fallback carrier is the sealed SA Art. 111(2) deducted provision
    # (``provision_deducted`` = provision_on_drawn + provision_on_nominal), which
    # is EXACTLY the amount the EAD math removes from the gross exposure
    # (engine/crm/guarantees.py: on_bal = drawn - provision_on_drawn; nominal =
    # nominal - provision_on_nominal), so 0040 reconstructs the engine's own
    # net-of-provisions basis. ``provision_allocated`` was CONSIDERED AND
    # REJECTED: it can exceed provision_deducted for an over-provisioned exposure
    # (the deduction is capped at drawn+nominal by the min() in provisions.py), so
    # summing it into 0030 would over-report the deduction and break the
    # 0040 = engine-net-basis identity. scra/gcra are never sealed on the
    # aggregator exit, so a real submission resolves to provision_deducted; the
    # synthetic COREP unit frames that supply scra/gcra keep their more granular
    # figure. CCR synthetic rows carry provision_deducted = null/0 (no Art. 111(2)
    # drawn-first deduction), so they contribute nothing to 0030.
    if _PROVISION_SOURCES & cols:
        carrier = (
            pl.col("provision_deducted").fill_null(0.0)
            if "provision_deducted" in cols
            else pl.lit(0.0)
        )
        if {"scra_provision_amount", "gcra_provision_amount"} & cols:
            scra = (
                pl.col("scra_provision_amount").fill_null(0.0)
                if "scra_provision_amount" in cols
                else pl.lit(0.0)
            )
            gcra = (
                pl.col("gcra_provision_amount").fill_null(0.0)
                if "gcra_provision_amount" in cols
                else pl.lit(0.0)
            )
            supplied = scra + gcra
            exprs.append(
                pl.when(supplied.abs() >= 1e-9)
                .then(supplied)
                .otherwise(carrier)
                .alias("c07_provision")
            )
        else:
            exprs.append(carrier.alias("c07_provision"))

    prepared = data.with_columns(exprs) if exprs else data
    # Second pass: the CRM substitution block reads c07_provision / c07_ccr_gross
    # derived above, so it cannot share their ``with_columns``.
    return prepared.with_columns(_protection_exprs(set(prepared.columns)))


def _rw_band_expr(framework: str) -> pl.Expr:
    """The risk-weight band LABEL for one row — the C 07.00 section-2 row axis.

    One definition, used twice: ``_prepare`` derives ``c07_rw_band`` from it for the
    band rows themselves, and ``_sa_inflows`` hands the SAME expression to the
    substitution router so a banded inflow lands on a row that exists. The ladder
    is regime-shaped (``get_sa_risk_weight_bands``; Basel 3.1 adds 15/25/30/40/45/
    60/65/80/85/105/110/130/135% sub-bands) and ends in the "Other risk weights"
    catch-all, so a weight matching no band is reported, never dropped.
    """
    band_expr: pl.Expr = pl.lit("Other risk weights")
    for rw_value, label in reversed(get_sa_risk_weight_bands(framework)):
        band_expr = (
            pl.when(
                pl.col("risk_weight").cast(pl.Float64, strict=False).round(4) == round(rw_value, 4)
            )
            .then(pl.lit(label))
            .otherwise(band_expr)
        )
    return band_expr


def _protection_exprs(cols: set[str]) -> list[pl.Expr]:
    """Per-row magnitudes for the Annex II substitution block (cols 0050-0080).

    Annex II C 07.00 heads cols 0050-0100 "CREDIT RISK MITIGATION (CRM)
    TECHNIQUES WITH SUBSTITUTION EFFECTS ON THE EXPOSURE" and is closed about
    what may appear there — "Items to be reported here: collateral,
    incorporated in accordance with the Financial Collateral Simple Method;
    eligible unfunded credit protection" (PS1/26 adds the third named limb,
    "other funded credit protection, incorporated in accordance with the Other
    Funded Credit Protection Method"). So four magnitudes, one per column:

        0050  guarantees            Art. 203 unfunded protection
        0060  credit derivatives    Art. 204
        0070  financial collateral  Art. 222(1)-(2), Simple Method
        0080  other funded          Art. 232 / Art. 200(1) — see _OFCP_CARRIERS

    and nothing else. Art. 199 immovable-property / receivables / other-physical
    collateral is IRB-only and is NOT one of them.

    All four are capped TOGETHER at the row's own exposure: "Collateral that has
    an effect on the exposure value (e.g. if used for credit risk mitigation
    techniques with substitution effects on the exposure) shall be capped at the
    exposure value." The cap is applied per row (Art. 235 splits each individual
    exposure into a covered and an uncovered part), on the BLOCK total rather
    than per column, because it is the block total that becomes the col 0090
    outflow: capping each column separately would still let their sum exceed the
    exposure and drive col 0110 negative. Where the block over-runs, the excess
    is shed proportionally — Annex II prescribes no priority between the four
    routes, and a proportional shed is the only order-independent choice.

    The cap basis is the row's contribution to col 0040 (gross pre-conversion
    factors, net of value adjustments and provisions), floored at zero. That is
    tighter than col 0010's "exposure value" and it is what makes
    ``0110 = 0040 - 0090 + 0100`` non-negative by construction — the property
    rules ``v10293_s`` / ``boe_b0667`` ({template} >= 0) assert.

    A DECLINED GUARANTEE CONTRIBUTES NOTHING TO COLS 0050/0060. The block heading
    is "CRM TECHNIQUES **WITH SUBSTITUTION EFFECTS ON THE EXPOSURE**", and a
    guarantee the calculator declined has none: Art. 193(1) bars a guarantee from
    raising the RWEA and Art. 193(3) leaves amending the calculation an election,
    so where the guarantor's weight does not beat the obligor's the engine leaves
    the RWA on the borrower basis and ``is_guarantee_beneficial`` is
    false. Reporting it here booked a col 0090 outflow that no exposure ever left
    and — because the col 0100 inflow binds the same ``_UNFUNDED_COL`` — a
    matching phantom inflow onto the guarantor's sheet, banded at the BORROWER's
    own risk weight. Gating the CARRIER, not the two cells, is what keeps outflow
    and inflow on a single decision, so neither can move without the other.
    """
    guaranteed = (
        pl.col("guaranteed_portion").fill_null(0.0) if "guaranteed_portion" in cols else pl.lit(0.0)
    )
    if "protection_type" in cols:
        # Same split the retired 0050/0060 cell predicates made: a null
        # protection_type contributes to neither column.
        guarantee = (
            pl.when(pl.col("protection_type") == "guarantee").then(guaranteed).otherwise(0.0)
        )
        credit_derivative = (
            pl.when(pl.col("protection_type") == "credit_derivative")
            .then(guaranteed)
            .otherwise(0.0)
        )
    else:
        guarantee = guaranteed
        credit_derivative = pl.lit(0.0)

    if _BENEFICIAL_COL in cols:
        # A DECLINED guarantee has no substitution effect at all, so it belongs in
        # neither the outflow nor the inflow — see the docstring's closing note.
        # ``== True`` is the null-safe reading: an unknown benefit is not a
        # substitution, and it must not be filled the other way.
        applied = pl.col(_BENEFICIAL_COL) == True  # noqa: E712 - null-safe, see above
        guarantee = pl.when(applied).then(guarantee).otherwise(pl.lit(0.0))
        credit_derivative = pl.when(applied).then(credit_derivative).otherwise(pl.lit(0.0))

    fcsm = pl.col(_FCSM_CARRIER).fill_null(0.0) if _FCSM_CARRIER in cols else pl.lit(0.0)
    ofcp_parts = [pl.col(col).fill_null(0.0) for col in _OFCP_CARRIERS if col in cols]
    other_funded = pl.sum_horizontal(ofcp_parts) if ofcp_parts else pl.lit(0.0)

    scale = _block_cap_scale(cols, guarantee + credit_derivative + fcsm + other_funded)
    return [
        (guarantee * scale).alias("c07_prot_guarantee"),
        (credit_derivative * scale).alias("c07_prot_credit_derivative"),
        (fcsm * scale).alias("c07_prot_fcsm"),
        (other_funded * scale).alias("c07_prot_other_funded"),
        # The UNFUNDED half of the block — cols 0050 + 0060 per row, i.e. the only
        # part of the col 0090 outflow that carries a destination class. The col
        # 0100 INFLOW binds this so it is the SAME capped magnitude the outflow
        # reports: reading the raw ``guaranteed_portion`` booked more on the way in
        # than ever left, creating money whenever the cap bit. It inherits the
        # protection_type split above, so a row carrying an out-of-vocabulary
        # protection type (non-blocking validation lets one through) contributes
        # zero to BOTH sides rather than zero out and a full amount in.
        ((guarantee + credit_derivative) * scale).alias(_UNFUNDED_COL),
    ]


def _block_cap_scale(cols: set[str], block_total: pl.Expr) -> pl.Expr:
    """The 0-1 factor that caps the substitution block at the row's exposure.

    ``1.0`` unless the block over-runs the cap basis, in which case
    ``basis / block_total`` (well-defined: an over-run implies a positive
    total). Degrades to ``1.0`` — uncapped, the pre-2026-08 behaviour — only on
    a frame that carries neither a gross carrier nor ``ead_final``, which the
    sealed ledger never is.
    """
    gross = [pl.col(col).fill_null(0.0) for col in _GROSS_CARRIERS if col in cols]
    if not gross and "ead_final" in cols:
        gross = [pl.col("ead_final").fill_null(0.0)]
    if not gross:
        return pl.lit(1.0)
    basis = pl.sum_horizontal(gross)
    if "c07_provision" in cols:
        basis = basis - pl.col("c07_provision").fill_null(0.0)
    basis = basis.clip(lower_bound=0.0)
    return pl.when(block_total > basis).then(basis / block_total).otherwise(1.0)


class _Inflows(NamedTuple):
    """The col 0100 inflow per destination class, on the three row axes C 07.00
    decomposes it over.

    ``total`` lands on the Total row 0010; ``by_side`` on the balance-sheet rows
    0070 / 0080 (keyed by the ``c07_bs`` label those rows filter on); ``by_rw_band``
    on the section-2 risk-weight rows. Each axis re-counts the SAME money — a
    native exposure appears once in each decomposition, so a substituted-in amount
    must too.

    THE BALANCE-SHEET AXIS BECAME LOAD-BEARING WITH THE TWO-BASIS SPLIT. It was
    once correctly absent: the recorded reasoning was that C 07.00's own row sum
    ``boe_b0717`` is scoped to cols 0200/0220, "neither of which the inflow
    touches", so rows 0070/0080 imposed no constraint on col 0100. Col 0200 is
    now on the POST basis, so it DOES report the arriving legs — and it reports
    them on row 0070/0080 as well as on row 0010, because the arriving leg's own
    balance-sheet side is in the frame. Leaving those two rows' col 0150 without
    the inflow left them declaring an exposure value larger than the fully
    adjusted exposure it came from, breaching ``boe_b0556`` / ``v8726_m``
    ({c0200} <= {c0150}) on precisely the sheets the substitution reached.

    IT IS NOT ``boe_b0717`` THAT FORCES THIS, AND THE DIFFERENCE IS INSTRUCTIVE —
    two reviewers predicted that rule as the casualty, and it was MEASURED not to
    be (it passes with the split, without it, and before the two-basis change:
    6 evaluated, 5 passing; its EBA twin ``v0310_m`` likewise). Its row
    decomposition is scoped to cols 0200/0220 ONLY, and those columns read the
    arriving LEGS THEMSELVES off the post-basis frame — each carries its own
    ``c07_bs``, so rows 0070/0080 pick it up with no out-of-frame scalar at all
    and the sum foots by construction. ``boe_b0556`` breaks because it STRADDLES
    the two mechanisms: col 0200 gets the arriving legs from the frame while col
    0150 gets the arriving amount only from the ``SideContext`` scalar, which
    landed on row 0010 and the band rows but not on 0070/0080. A rule confined to
    either mechanism alone is safe; the ones to check are the ones spanning both.
    (The CCR rows in ``boe_b0717``'s list — 0090/0110/0130 — take no inflow at
    all: they key ``risk_type``, which ``_inflow_key_for`` does not recognise, and
    0130 is inert. Verified, not assumed.)
    """

    total: dict[str, float]
    by_side: dict[str, dict[str, float]]
    by_rw_band: dict[str, dict[str, float]]


def _sa_inflows(results: pl.LazyFrame, cols: set[str], framework: str) -> _Inflows:
    """The SA-destined substitution inflows, keyed the way C 07.00 keys sheets.

    TWO HALVES, because the inflow must be measured with the cap of the template
    that REPORTED the matching outflow and the two templates cap on different
    bases (this one nets provisions off the basis — ``_block_cap_scale`` — under
    the Art. 111(2) drawn-first deduction; the IRB basis does not):

    - IRB-origin legs guaranteed by an SA protection provider. Their outflow is
      reported on C 08.01, so ``crm_substitution.irb_origin_inflows`` measures
      them on the IRB capped carrier. This is the cross-template half, and
      dropping it was the defect that left a sovereign-guaranteed IRB corporate
      loan's covered part reported as an outflow and as an inflow nowhere.
    - SA-origin legs, added here from this template's OWN prepared frame so they
      carry THIS cap. ``_post_crm_approach_expr`` gives an SA-origin leg an SA
      destination under both of its branches, so no SA-origin leg can be missing
      from C 08.01 by being counted here.

    Keys are raw guarantor exposure classes, so the Art. 112 Table A2 merge this
    template applies to its sheet axis (specialised lending is a corporate
    sub-type under SA) is applied to them too: otherwise an inflow into an SL
    guarantor would key a sheet C 07.00 does not have.
    """
    merged: dict[str, float] = {}
    sides: dict[str, dict[str, float]] = {}
    bands: dict[str, dict[str, float]] = {}
    # The graded/slotting split is NOT read: C 07.00 has no IRB-treatment row
    # axis. The other two are — ``v0312_m`` / ``boe_b0719`` decompose row 0010
    # over the band rows and ``boe_b0717`` over rows 0070/0080, on columns the
    # inflow now reaches (col 0150 through 0110, and col 0200 through the post
    # basis). ``risk_weight`` is absent on a frame too thin to band; the router
    # then returns no split and the band rows keep their ordinary empty policy.
    band_expr = _rw_band_expr(framework) if "risk_weight" in cols else None
    for exposure_class, inflow in irb_origin_inflows(
        results, cols, destination="standardised", band_expr=band_expr
    ).items():
        _accumulate(merged, exposure_class, inflow.total)
        _accumulate_split(sides, exposure_class, _ON_BS, inflow.on_bs)
        _accumulate_split(sides, exposure_class, _OFF_BS, inflow.off_bs)
        for band, amount in inflow.by_rw_band.items():
            _accumulate_split(bands, exposure_class, band, amount)
    return _Inflows(merged, sides, bands)


def _add_sa_origin_inflows(inflows: _Inflows, sa_df: pl.DataFrame) -> _Inflows:
    """Add the SA-origin half of col 0100, off this template's own capped frame.

    ``sa_df`` is post-``_prepare``, so it carries ``_UNFUNDED_COL`` — the same
    capped magnitude cols 0050/0060 report and col 0090 subtotals. Summing that
    (rather than the raw covered carrier) is what makes the inflow equal and
    opposite to the outflow when the Annex II block cap bites.

    IRB-origin rows are excluded here because ``irb_origin_inflows`` already
    counted them on the IRB cap. The exclusion is not redundant: ``c07_population``
    admits the counterparty-credit-risk rows by ``risk_type`` with NO approach
    filter, so an IRB-origin CCR row can legitimately sit in this frame and would
    otherwise be counted twice.

    DECLINED GUARANTEES ARE EXCLUDED TOO, and without a filter of their own:
    ``_protection_exprs`` has already zeroed ``_UNFUNDED_COL`` on a leg whose
    guarantee the calculator declined, so the ``> 0`` filter below drops it. It is
    Art. 235 substitution ACTUALLY BEING APPLIED that entitles the covered part to
    the guarantor's sheet; a positive covered carrier only says protection was
    attached. Art. 193(1) bars a guarantee from raising the RWEA and Art. 193(3)
    makes amending the calculation an election, so the SA calculator DECLINES a
    guarantee whose guarantor weight does not beat the obligor's
    (``is_guarantee_beneficial=False``) and leaves the RWA on the borrower basis.
    Booking that as an inflow moved the covered part onto the guarantor's sheet
    banded — via ``c07_rw_band`` — at the BORROWER's own risk weight, reproduced
    as a full 10,000,000 phantom inflow onto ``central_govt_central_bank`` at
    100%. Sharing the carrier with the col 0090 outflow is what keeps both sides
    off the SAME decision, so a declined guarantee can neither leave nor arrive.
    """
    cols = set(sa_df.columns)
    if not {_UNFUNDED_COL, _POST_CRM_CLASS_COL} <= cols:
        return inflows
    # The ORIGIN population only: this half speaks for legs whose OUTFLOW this
    # template reported, and only an origin-basis leg has one here. Post-basis-
    # only legs are IRB-origin by construction (they are in the post population
    # and not the origin one), so they arrive from ``irb_origin_inflows`` already
    # measured on the IRB cap — counting them again would create money.
    frame = sa_df.filter(
        pl.col(_BASIS.pop_origin)
        & (pl.col(_UNFUNDED_COL) > 0)
        & pl.col(_POST_CRM_CLASS_COL).is_not_null()
    )
    if _ORIGIN_APPROACH_SOURCE in cols:
        frame = frame.filter(~pl.col(_ORIGIN_APPROACH_SOURCE).is_in(list(_IRB_ORIGINS)))
    grouped = frame.group_by(_POST_CRM_CLASS_COL).agg(pl.col(_UNFUNDED_COL).sum().alias("inflow"))
    merged = dict(inflows.total)
    for row in grouped.iter_rows(named=True):
        _accumulate(merged, row[_POST_CRM_CLASS_COL], float(row["inflow"]))
    # The two split axes, each a group_by on the SAME frame. A leg the frame
    # cannot place on a balance-sheet side (null ``c07_bs``) joins the ON side,
    # matching ``crm_substitution._off_bs``'s convention — that is what keeps
    # on + off == total, and therefore keeps ``boe_b0717`` footing.
    merged_sides = _add_split(inflows.by_side, frame, _side_label(cols))
    merged_bands = _add_split(
        inflows.by_rw_band, frame, pl.col("c07_rw_band") if "c07_rw_band" in cols else None
    )
    return _Inflows(merged, merged_sides, merged_bands)


def _side_label(cols: set[str]) -> pl.Expr:
    """The ``c07_bs`` label rows 0070/0080 filter on, defaulting to the ON side."""
    if "c07_bs" not in cols:
        return pl.lit(_ON_BS)
    return pl.when(pl.col("c07_bs") == _OFF_BS).then(pl.lit(_OFF_BS)).otherwise(pl.lit(_ON_BS))


def _add_split(
    existing: dict[str, dict[str, float]], frame: pl.DataFrame, label: pl.Expr | None
) -> dict[str, dict[str, float]]:
    """Accumulate one inflow split axis over the SA-origin frame into a copy of
    ``existing`` (the cross-template half). ``None`` label = axis unavailable on
    this frame; its rows then keep their ordinary empty policy."""
    merged = {key: dict(value) for key, value in existing.items()}
    if label is None:
        return merged
    grouped = (
        frame.with_columns(label.alias("_axis"))
        .group_by(_POST_CRM_CLASS_COL, "_axis")
        .agg(pl.col(_UNFUNDED_COL).sum().alias("inflow"))
    )
    for row in grouped.iter_rows(named=True):
        _accumulate_split(merged, row[_POST_CRM_CLASS_COL], row["_axis"], float(row["inflow"]))
    return merged


def _accumulate_split(
    split: dict[str, dict[str, float]], exposure_class: str, axis: str, amount: float
) -> None:
    """Add one destination-class/axis amount under this template's sheet key."""
    per_class = split.setdefault(_sheet_key(exposure_class), {})
    per_class[axis] = per_class.get(axis, 0.0) + amount


def _accumulate(merged: dict[str, float], exposure_class: str, amount: float) -> None:
    """Add one destination-class amount under this template's sheet key."""
    key = _sheet_key(exposure_class)
    merged[key] = merged.get(key, 0.0) + amount


def _sheet_key(exposure_class: str) -> str:
    """A raw guarantor class as this template's sheet key — the Art. 112 Table A2
    merge the sheet axis applies (SL is a corporate sub-type under SA), so an
    inflow into an SL guarantor cannot key a sheet C 07.00 does not have."""
    if exposure_class == ExposureClass.SPECIALISED_LENDING.value:
        return ExposureClass.CORPORATE.value
    return exposure_class


def _inflow_rows(
    row_terms: dict[str, _Terms | None], sides: dict[str, float], bands: dict[str, float]
) -> frozenset[str]:
    """Split rows carrying a NON-ZERO inflow on this sheet.

    ``_null_empty_rows`` renders a row all-null when its own subset is empty,
    which would delete the split inflow on exactly the sheets that need it most —
    an inflow-only destination class has no native rows at all. Exempting them is
    what makes the row-0010 decompositions foot there. A row qualifies by its own
    single membership term, the same way ``_inflow_key_for`` recognises it, so the
    regime-specific band axis needs no hardcoded ref ladder."""
    keep: set[str] = set()
    for ref, terms in row_terms.items():
        if terms is None or len(terms) != 1:
            continue
        column, value = terms[0]
        split = bands if column == "c07_rw_band" else sides if column == "c07_bs" else None
        if split is not None and split.get(str(value)):
            keep.add(ref)
    return frozenset(keep)


def _row_terms(framework: str, cols: set[str]) -> dict[str, _Terms | None]:
    """Tolerant-equals membership terms per row ref (None = inert row —
    rendered all-null). Ports the retired section-subset builders."""
    terms: dict[str, _Terms | None] = {}
    for section_index, section in enumerate(get_sa_row_sections(framework)):
        for row in section.rows:
            terms[row.ref] = _terms_for_row(section_index, row.ref, row.name, cols)
    return terms


def _terms_for_row(  # noqa: PLR0911, PLR0912, C901 - a direct table of the retired dispatch
    section_index: int, ref: str, name: str, cols: set[str]
) -> _Terms | None:
    if section_index == 0:
        if ref == "0010":
            return ()
        if ref == "0015":
            return (("c07_defaulted", True),)
        if ref == "0020":
            return (("c07_sme", True),)
        if ref in _SL_TYPE_MAP:
            return (("sl_type", _SL_TYPE_MAP[ref]),)
        if ref in _PF_PHASE_MAP:
            return (("sl_type", "project_finance"), ("sl_project_phase", _PF_PHASE_MAP[ref]))
        if ref in _RE_ROW_FILTERS:
            return _re_terms(cols, **_RE_ROW_FILTERS[ref])  # type: ignore[arg-type]
        if ref == "0030":
            return _supporting_factor_terms(cols, "sme")
        if ref == "0035":
            return _supporting_factor_terms(cols, "infrastructure")
        if ref == "0050":
            return (("c07_ppu", True),)
        if ref == "0060":
            return (("ppu_reason", "art_148_rollout"),)
        return None
    if section_index == 1:
        if ref == "0070":
            return (("c07_bs", "on"),)
        if ref == "0080":
            return (("c07_bs", "off"),)
        if ref == "0090":
            return (("risk_type", "CCR_SFT"),)
        if ref == "0100":  # of which: SFT netting sets cleared through a QCCP
            return (("risk_type", "CCR_SFT"), ("c07_qccp", True))
        if ref == "0110":  # derivative + long-settlement netting sets — the
            # ADDITIVE PARENT of 0120: every netting set, INCLUDING the
            # QCCP-cleared ones. Writing it as "derivative AND NOT qccp" would
            # make 0120 a sibling and the breakdown would stop footing.
            return (("risk_type", "CCR_DERIVATIVE"),)
        if ref == "0120":  # of which: derivative netting sets cleared via a QCCP
            return (("risk_type", "CCR_DERIVATIVE"), ("c07_qccp", True))
        # 0130 (contractual cross-product netting sets, Art. 295(c)) is NOT
        # MODELLED: no input carrier exists for a cross-product netting
        # agreement. Inert, not "checked and found empty".
        return None
    if section_index == 2:  # noqa: PLR2004 - RW band section
        return (("c07_rw_band", name),)
    if section_index == 3:  # noqa: PLR2004 - CIU section
        if ref in _CIU_ROW_APPROACH:
            return (("ciu_approach", _CIU_ROW_APPROACH[ref]),)
        return None
    # Section 5: memorandum items
    if ref in _EQUITY_TRANSITIONAL_FILTERS:
        approach, higher_risk = _EQUITY_TRANSITIONAL_FILTERS[ref]
        base: _Terms = (("equity_transitional_approach", approach),)
        if "equity_higher_risk" in cols:
            return (*base, ("equity_higher_risk", higher_risk))
        if higher_risk:
            return None
        return base
    if ref == "0380":
        return (("currency_mismatch_multiplier_applied", True),)
    if ref in _MEMO_DEFAULTED_RW:
        return (("c07_defaulted", True), ("c07_rw_band", _MEMO_DEFAULTED_RW[ref]))
    if ref in _MEMO_RE_SECURED:
        return (("property_type", _MEMO_RE_SECURED[ref]),)
    return None


def _re_terms(
    cols: set[str],
    *,
    property_type: str | None = None,
    materially_dependent: bool | None = None,
    is_sme: bool | None = None,
    is_adc: bool | None = None,
    is_qualifying: bool | None = None,
) -> _Terms | None:
    """RE "of which" membership terms (retired _filter_re semantics)."""
    terms: list[tuple[str, str | bool]] = []
    if property_type is not None:
        terms.append(("property_type", property_type))
    else:
        terms.append(("c07_has_property", True))
    if is_qualifying is not None:
        if "is_qualifying_re" not in cols and is_qualifying is False:
            return None  # no non-qualifying RE to report
        terms.append(("c07_qualifying_re", is_qualifying))
    if materially_dependent is not None:
        terms.append(("c07_md", materially_dependent))
    if is_sme is not None:
        terms.append(("c07_sme", is_sme))
    if is_adc is not None:
        if "is_adc" not in cols and is_adc is True:
            return None
        terms.append(("is_adc", is_adc))
    return tuple(terms)


def _supporting_factor_terms(cols: set[str], factor_type: str) -> _Terms | None:
    """Section 1 supporting-factor row terms (retired _filter_supporting_factor)."""
    flag_col = "is_sme" if factor_type == "sme" else "is_infrastructure"
    if flag_col not in cols:
        return None
    applied = pick(cols, f"{factor_type}_supporting_factor_applied", "supporting_factor_applied")
    if applied is None:
        return ((flag_col, True),)
    return ((flag_col, True), (applied, True))


def _build_spec(
    framework: str,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    row_terms: dict[str, _Terms | None],
) -> TemplateSpec:
    """The C 07.00 TemplateSpec for one run (built cols-aware so carrier
    ladders and structural-null variants resolve once per generate call)."""
    column_refs = tuple(col.ref for col in get_c07_columns(framework))
    is_b31 = framework == "BASEL_3_1"
    rows = tuple(row for section in get_sa_row_sections(framework) for row in section.rows)

    cells: dict[tuple[str, str], CellSpec] = {}
    for row in rows:
        terms = row_terms.get(row.ref)
        if terms is None:
            continue
        for col_ref, cell in _row_cells(
            terms,
            cols,
            ead_col,
            rwa_col,
            column_refs,
            is_b31=is_b31,
            inflow_key=_inflow_key_for(row.ref, terms),
        ).items():
            cells[(row.ref, col_ref)] = cell
    return TemplateSpec(
        name="c07_00",
        rows=rows,
        column_refs=column_refs,
        cells=cells,
        empty_cell="zero",
    )


def _inflow_key_for(ref: str, terms: _Terms) -> str | None:
    """Which ``ReportingContext`` inflow component this row's col 0100 takes.

    The Total row takes the whole inflow; a BALANCE-SHEET row (0070/0080) and a
    RISK-WEIGHT BAND row each take the share of it reported on their side / at
    their band. Both are recognised by their own single membership term rather
    than by a hardcoded ref ladder, so the regime-specific band axis (Basel 3.1
    adds thirteen sub-bands) and the two-term memo rows 0300/0320 (defaulted AND
    banded, which are "of which" memos and NOT part of the row-0010
    decomposition) both fall out correctly.
    """
    if ref == "0010":
        return "substitution_inflow"
    if len(terms) != 1:
        return None
    column, value = terms[0]
    if column == "c07_rw_band":
        return f"{SUBSTITUTION_INFLOW_RW_PREFIX}{value}"
    if column == "c07_bs":
        return "substitution_inflow_off_bs" if value == _OFF_BS else "substitution_inflow_on_bs"
    return None


def _post_sl_terms(terms: _Terms, cols: set[str]) -> _Terms:
    """The POST-basis-only narrowing of the specialised-lending "of which" rows.

    A row keying ``sl_type`` (0021-0026) admits a leg on the post basis only
    while that leg still applies its own Art. 122B risk weight — see
    ``_SL_OWN_RW_COL`` for the Annex II basis. Recognised by the row's own
    membership term rather than a hardcoded ref ladder, so the phase children
    (which key ``sl_type`` AND ``sl_project_phase``) fall out with the parent.
    Empty when no substitution gate is sealed: the frame then carries no
    beneficially-substituted leg to exclude, and a term on an underived column
    would zero the SL rows of every synthetic unit frame.
    """
    if _BENEFICIAL_COL not in cols or not any(column == "sl_type" for column, _ in terms):
        return ()
    return ((_SL_OWN_RW_COL, True),)


def _row_cells(  # noqa: PLR0913 - the full 24-column surface of one row
    terms: _Terms,
    cols: set[str],
    ead_col: str,
    rwa_col: str,
    column_refs: tuple[str, ...],
    *,
    is_b31: bool,
    inflow_key: str | None,
) -> dict[str, CellSpec]:
    # The two-basis split (module docstring): cols 0010-0150 read the obligor's
    # own book, cols 0160-0235 read the post-substitution population. Every
    # predicate carries its basis flag, INCLUDING the total row's (whose ``terms``
    # are empty) — an unflagged predicate would silently sum both populations.
    origin_terms: _Terms = ((_BASIS_ORIGIN_COL, True), *terms)
    post_terms: _Terms = ((_BASIS_POST_COL, True), *terms, *_post_sl_terms(terms, cols))
    member = RowPredicate(equals=origin_terms)
    post_member = RowPredicate(equals=post_terms)

    def narrowed(*extra: tuple[str, str | bool]) -> RowPredicate:
        """A further-narrowed POST-basis predicate — every caller (cols
        0210/0211/0230/0235) is an exposure-value or RWEA breakdown."""
        return RowPredicate(equals=(*post_terms, *extra))

    cells: dict[str, CellSpec] = {
        "0010": CellSpec(
            SafeSum(("reporting_gross_on_bs", "reporting_gross_off_bs", "c07_ccr_gross")),
            predicate=member,
        ),
        "0020": CellSpec(Sum("own_funds_deduction_amount"), predicate=member),
        "0030": (
            CellSpec(Sum("c07_provision"), predicate=member)
            if _PROVISION_SOURCES & cols
            else CellSpec(
                SafeSum(("scra_provision_amount", "gcra_provision_amount")), predicate=member
            )
        ),
        # 0050-0080: the four block-capped substitution magnitudes derived by
        # ``_protection_exprs`` (which owns the protection_type split the 0050 /
        # 0060 cell predicates used to make). 0070 / 0080 keep the SafeSum
        # binding when their carriers are absent so a frame that seals none of
        # them still renders the recorded structural null rather than a 0.0.
        "0050": CellSpec(Sum("c07_prot_guarantee"), predicate=member),
        "0060": CellSpec(Sum("c07_prot_credit_derivative"), predicate=member),
        "0070": (
            CellSpec(Sum("c07_prot_fcsm"), predicate=member)
            if _FCSM_CARRIER in cols
            else CellSpec(SafeSum((_FCSM_CARRIER,)), predicate=member)
        ),
        "0080": (
            CellSpec(Sum("c07_prot_other_funded"), predicate=member)
            if set(_OFCP_CARRIERS) & cols
            else CellSpec(SafeSum(_OFCP_CARRIERS), predicate=member)
        ),
        "0090": CellSpec(Formula(refs=("0050", "0060", "0070", "0080"), fn=_substitution_outflow)),
        "0110": CellSpec(Formula(refs=("0040", "0090", "0100"), fn=_net_after_substitution)),
        "0120": CellSpec(Formula(refs=(), fn=_const(0.0))),
        "0130": CellSpec(Sum("collateral_adjusted_value"), predicate=member),
        "0140": (
            CellSpec(Sum("c07_vol_mat_adj"), predicate=member)
            if "collateral_market_value" in cols
            else CellSpec(Formula(refs=(), fn=_const(None)))
        ),
        "0150": CellSpec(Formula(refs=("0110", "0130"), fn=_fully_adjusted)),
        # Col 0200 onwards are POST-basis. Annex II defines col 0200 as the
        # "exposure value after taking into account value adjustments, ALL CREDIT
        # RISK MITIGANTS and conversion factors that is to be assigned to risk
        # weights in accordance with Article 113" — Art. 235 substitution is a
        # credit risk mitigant, so the covered part's exposure value and RWEA
        # follow its col 0090/0100 flow onto the protection provider's sheet.
        "0200": CellSpec(Sum(ead_col), predicate=post_member),
        # Annex II col 0200: "Exposure values for CCR business shall be the same
        # as reported in column 0210" — so 0210 is the row's exposure value
        # narrowed to its CCR rows, and 0211 narrows further by excluding the
        # Art. 301(1) CCP-cleared transactions.
        "0210": (
            CellSpec(Sum(ead_col), predicate=narrowed(("c07_ccr", True)))
            if "risk_type" in cols
            else CellSpec(Formula(refs=(), fn=_const(None)))
        ),
        "0211": (
            CellSpec(Sum(ead_col), predicate=narrowed(("c07_ccr_non_ccp", True)))
            if {"risk_type", "cp_entity_type"} <= cols
            else CellSpec(Formula(refs=(), fn=_const(None)))
        ),
        "0220": CellSpec(Sum(rwa_col), predicate=post_member),
        "0240": CellSpec(Formula(refs=(), fn=_const(None))),
    }
    # Col 0100 lands on the Total row AND on the risk-weight band row matching the
    # weight each substituted amount is reported at. ``v0312_m`` (C 07.00.a,
    # reactivated 2015-02-27) and ``boe_b0719`` (OF07.00.01.01, live) decompose row
    # 0010 over the band rows on col 0150, which the inflow reaches through col
    # 0110 — so a Total-row-only inflow breaches both by exactly the inflow, and an
    # inflow-only sheet has no populated band row at all. See ``_inflow_key_for``.
    if inflow_key is not None:
        cells["0100"] = CellSpec(SideContext(inflow_key))
    if is_b31:
        cells["0035"] = CellSpec(Sum("on_bs_netting_amount"), predicate=member)
        cells["0040"] = CellSpec(Formula(refs=("0010", "0030", "0035"), fn=_net_of_adjustments))
    else:
        cells["0040"] = CellSpec(Formula(refs=("0010", "0030"), fn=_net_of_adjustments))
        # CRR supporting-factor columns (Art. 501/501a) — POST basis with col
        # 0220, which they have to foot against (0215 + 0216 + 0217 = 0220).
        cells["0215"] = CellSpec(
            Sum("rwa_pre_factor" if "rwa_pre_factor" in cols else rwa_col), predicate=post_member
        )
        cells["0216"] = _sf_adjustment_cell(
            post_terms, cols, "sme_supporting_factor_applied", "is_sme"
        )
        cells["0217"] = _sf_adjustment_cell(
            post_terms, cols, "infrastructure_factor_applied", "is_infrastructure"
        )

    # CCF buckets (0160-0190): the PRE-conversion off-balance-sheet gross per
    # bucket, not the post-conversion EAD — Annex II heads the block "fully
    # adjusted exposure value of off-balance sheet items", and col 0200 is what
    # survives conversion (see the module docstring on boe_b0471 / v6364_m).
    #
    # The off-side narrowing is load-bearing, not cosmetic: a drawn loan carries
    # ccf = 0.0, which is a REAL bucket under CRR (Art. 111 / Annex I LR 0% ->
    # col 0160), so without it every on-balance loan would land in the 0% bucket.
    # Its gross there is 0.0, so the numbers would not move — the cell would just
    # silently stop being a statement about off-balance-sheet items.
    #
    # empty_cell="null": a row with no off-balance-sheet item in the bucket
    # reports blank, not 0.0 — the template's recorded empty-subset contract
    # (the retired _null_row semantics these cells replaced).
    #
    # POST basis, with col 0200 rather than with the gross col 0010 they read the
    # carrier of: they break down col 0150, which is ALREADY post-substitution
    # (it nets the col 0090 outflow and adds the col 0100 inflow), and
    # ``v0308_m`` / ``boe_b0471`` test col 0200 AGAINST them. Leaving them on the
    # origin basis while col 0200 moved would break that identity the other way.
    ccf_refs = [ref for ref in _CCF_REFS if ref in column_refs]
    for ref in ccf_refs:
        if pick(cols, *_CCF_CARRIERS) is not None and _OFF_BS_GROSS_COL in cols:
            bucket_terms: _Terms = (*post_terms, ("c07_ccf_bucket", ref))
            if _has_bs_side(cols):
                bucket_terms = (*bucket_terms, ("c07_bs", "off"))
            cells[ref] = CellSpec(
                Sum(_OFF_BS_GROSS_COL),
                predicate=RowPredicate(equals=bucket_terms),
                empty_cell="null",
            )
        else:
            cells[ref] = CellSpec(Formula(refs=(), fn=_const(None)))

    # ECAI split (0230/0235): sa_cqs is never sealed — populated on synthetic
    # frames only.
    if "sa_cqs" in cols:
        cells["0230"] = CellSpec(Sum(rwa_col), predicate=narrowed(("c07_rated", True)))
        if "0235" in column_refs:
            cells["0235"] = CellSpec(Sum(rwa_col), predicate=narrowed(("c07_rated", False)))
    else:
        cells["0230"] = CellSpec(Formula(refs=(), fn=_const(None)))
        if "0235" in column_refs:
            cells["0235"] = CellSpec(Formula(refs=(), fn=_const(None)))

    return {ref: cell for ref, cell in cells.items() if ref in column_refs}


def _sf_adjustment_cell(terms: _Terms, cols: set[str], dedicated: str, flag_col: str) -> CellSpec:
    """Supporting-factor RWEA adjustment (retired _supporting_factor_adjustment):
    Σ(rwa_pre_factor - rwa) over the applied rows; None when no carrier.
    ``dedicated`` is the factor's own applied-flag column (note the retired
    asymmetric names: sme_supporting_factor_applied vs
    infrastructure_factor_applied)."""
    if "rwa_pre_factor" not in cols:
        return CellSpec(Formula(refs=(), fn=_const(None)))
    if dedicated in cols:
        return CellSpec(
            Sum("c07_sf_delta"), predicate=RowPredicate(equals=(*terms, (dedicated, True)))
        )
    if flag_col in cols and "supporting_factor_applied" in cols:
        return CellSpec(
            Sum("c07_sf_delta"),
            predicate=RowPredicate(
                equals=(*terms, (flag_col, True), ("supporting_factor_applied", True))
            ),
        )
    return CellSpec(Formula(refs=(), fn=_const(None)))
