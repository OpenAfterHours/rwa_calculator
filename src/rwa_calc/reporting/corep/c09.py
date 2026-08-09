"""
COREP C 09.01 / C 09.02 — geographical breakdown of exposures, declarative.

Pipeline position:
    sealed aggregator-exit ledger -> per-template population + derived
    discriminators -> ONE TemplateSpec per framework -> cellspec.execute()
    per country sheet -> dict["TOTAL" | ISO code, DataFrame]

Cell semantics (recorded decisions, this slice):

- BOTH templates split BY COLUMN on the basis Annex II §3.4 ¶87 names.
  ¶86: "This concept can be applied on an immediate-obligor basis and on
  an ultimate-risk basis. Hence, CRM techniques with substitution effects
  can change the allocation of an exposure to a country." ¶87: "Data
  regarding 'original exposure pre-conversion factors' shall be reported
  referring to the country of residence of the IMMEDIATE obligor. Data
  regarding 'exposure value' and 'Risk-weighted exposure amounts' shall be
  reported as of the country of residence of the ULTIMATE obligor." So the
  pre-conversion original exposure and the provisions columns (C 09.01
  0010/0020/0050/0055, C 09.02 0010/0030/0050/0055) key the IMMEDIATE
  obligor and the exposure-value / RWEA columns (C 09.01 0075/0080/0081/
  0082/0090, C 09.02 0105/0107/0110/0120/0121/0122/0125) key the ULTIMATE
  one — on BOTH axes at once, the row (class) and the sheet (country),
  since a beneficial substitution moves both together. Each cell carries
  its own population flag, its own class key and its own country flag;
  widening the frame to both populations WITHOUT that per-cell
  discrimination is the measured failure mode (a prototype inflated
  C 09.01 col 0010 by 61% and broke the row-0170 total).
- C 09.01's IMMEDIATE-obligor columns key the APPLIED Art. 112 class
  (``reporting_class_origin`` — recorded fix 2026-07-12: the Annex II
  instructions define them "same as the CR SA template", so a defaulted
  SA exposure moves to row 0100 exactly as C 07.00 assigns it), while the
  0020 "Defaulted exposures" MEMORANDUM keys the raw ORIGINAL class (the
  instruction's counterfactual "would have been" row) — a THREE-predicate
  row, since the ULTIMATE-obligor columns key the sealed
  ``reporting_class`` over the post-substitution population as well.
  C 09.02 keys the same pair over the ``reporting_approach_origin`` /
  ``reporting_approach`` IRB books (its origin key == raw
  ``exposure_class`` for that book — number-neutral convergence; the IRB
  template has no default row by design).
  The rows 0071-0073 SA specialised-lending "of which" cells take one
  extra POST-basis-only term: a covered part substituted onto a provider's
  risk weight stops applying its own Art. 122B treatment and leaves those
  rows, exactly as C 07.00's rows 0021-0026 do (``_SL_OWN_RW_COL``).
  Under B31 the RE reporting classes (retail_mortgage /
  residential_mortgage / commercial_mortgage — the Art. 124A standalone
  RE class plus the loan-splitter's secured legs) key the "Real estate
  exposures" row 0090 and its regulatory-RRE / regulatory-CRE / other-RE
  / ADC / SME "of which" sub-rows (0091-0095); the SA specialised-lending
  "of which" sub-rows (0071-0073) key sl_type (rectification R7).
- The COUNTRY axis is the SAME two-basis machinery as the class axis, run
  on the country as the sheet key (``_GEO_BASIS`` over
  ``kernel/bases.py::sheet_axis`` / ``sheet_frame``). A beneficially
  guaranteed cross-border leg therefore sits on TWO country sheets at
  once: its obligor's, reporting the pre-conversion original exposure, and
  its guarantor's, reporting the exposure value and RWEA. The keys are the
  sealed ``reporting_country`` / ``reporting_country_origin`` twins
  (aggregator ``_add_reporting_projection``, gated identically to the
  class twin — a DECLINED guarantee moves neither), degrading to the raw
  ``cp_country_code`` on a frame that seals neither. ``TOTAL`` is the
  all-geographies sheet and carries every leg on both geographical flags;
  a null country still partitions into no country sheet.
- C 09.01 shares C 07.00's population (``c07_population(both_bases=True)``
  — the SA book on the OBLIGOR's approach unioned with the SA book on the
  post-substitution approach, plus BOTH counterparty-credit-risk
  populations: FCCM SFT synthetic rows and SA-CCR derivative netting sets,
  admitted by ``risk_type``). The post limb is what carries an IRB-origin
  leg guaranteed by an SA protection provider onto this template — its
  exposure value and RWEA belong on the guarantor's class under Art. 235,
  which is where C 07.00's col 0100 already routes its inflow, and the
  cross-template rules v5746_q-v5772_q / boe_b0191-b0224 tie C 09.01's
  ¶87 columns straight to C 07.00's own post-substitution cols
  0200/0215/0220. That
  shared population is why the Basel 3.1 institution row is now populated:
  the derivative netting sets used to be dropped by the
  ``standardised_ccr`` output-floor relabel and never reached either
  template. C 09.02 is the IRB book INCLUDING slotting (the retired inline
  comment claiming exclusion was misleading).
- The reverse-map row keying handles the plain class rows: a row whose key
  is not a ``C09_01_SA_CLASS_MAP`` value AND not an RE/SL/SME sub-row key
  renders ALL-NULL (the short-term and CIU sub-rows stay permanently null —
  recorded dead code); the corporate rows fan in corporate + corporate_sme +
  specialised_lending; retail fans in retail_other (+ retail_qrre /
  retail_mortgage per template). The B31-only RE rows (0090-0095) and SA
  specialised-lending rows (0071-0073) bypass the reverse map via
  ``_c09_01_re_sl_pred`` (rectification R7): these keys never occur in
  CRR_C09_01_ROWS, so CRR C 09.01 is untouched.
- The three "of which: SME" rows (0075 corporate_sme / 0085 retail_sme /
  0095 mortgage_sme, ``_C09_01_SME_PARENT_KEYS``) key their PARENT row's
  class union narrowed by ``c09_sme``, C 07.00's own row-0020 SME ladder:
  Annex II and PS1/26 Annex II both define all three as "Same definition as
  for row 0020 of [OF] CR SA template". The retired reverse map had no entry
  mapping onto those keys, so they rendered permanently null and the
  geographical breakdown silently dropped the SME disclosure while the
  parent rows correctly aggregated it (v5773_q-v5776_q, boe_b0225-b0227,
  and — because a null of-which reads as zero against a NEGATIVE
  supporting-factor adjustment on the parent — v0411_m). B31 row 0095 is
  ``re_sme`` instead and keeps the raw ``is_sme`` narrowing of the RE class
  union (recorded R7, mirroring C 07.00's own RE memo rows).
- Cols 0010/0020 (C 09.01) and 0010/0030 (C 09.02) are ORIGINAL EXPOSURE
  PRE-CONVERSION FACTORS, defined by reference to C 07.00 col 0010 and
  C 08.01 col 0020 respectively, so they bind the same sealed per-side gross
  carriers those columns bind (``_pre_ccf_gross_binding``) — C 09.01 with
  C 07.00's counterparty-credit-risk term, C 09.02 without one, as C 08.01
  has none. The retired ladder picked ``ead_gross``, the POST-CCF exposure:
  on an off-balance-sheet book the geographical breakdown reported the
  conversion-factor-reduced figure in a pre-conversion column and the whole
  off-BS nominal vanished (v5769_q / boe_b0222). A synthetic frame carrying
  no raw gross input keeps the retired pick — generate-time variant.
- Recorded decision (R7): row 0090 keys the SEALED RE classes
  (retail_mortgage / residential_mortgage / commercial_mortgage). B31
  Art. 124I / Table A2 places income-producing CRE within the standalone
  real-estate class, but this pipeline's classifier seals IPRE-CRE as
  ``reporting_class_origin == "corporate"``, so it deliberately stays in
  row 0070 — keying 0090 on a secured-by-RE flag instead would count the
  same leg in both 0070 and 0090 and break the row-0170 Total tie-out this
  fix restored. If the classifier's IPRE-CRE scoping changes, row 0090
  follows automatically. The 0091-0094 sub-rows partition the RE class
  only for well-formed books: an ADC leg whose property_type is also
  residential/commercial + qualifying lands in 0094 AND 0091/0092, and a
  qualifying RE leg with an unrecognised property_type sits in 0090 only.
- Empty class rows render ALL-NULL (the dominant null path); the Total
  rows (0170 / 0150) compute over the WHOLE country frame — never nulled,
  and they aggregate exposures no class row displays.
- C 09.02's PD/LGD averages weight by ``ead_final`` (NOT the default
  ``reporting_ead``), report RAW ratios (no x100 despite the "(%)"
  labels), read ``lgd_post_crm`` only, and preserve the retired
  UNWEIGHTED-mean fallback when the subset carries zero total EAD (a
  module post-step — the WeightedAvg verb has no such fallback).
- The POST-SF RWEA ladder is the retired one, narrower than C 07/C 08:
  pick(rwa_final, rwa) (NO rwa_post_factor).
  The CRR "RWEA pre supporting factors" columns (C 09.01 col 0080,
  C 09.02 col 0110) key ``rwa_pre_factor`` — the pre-Art. 501/501a RWA
  snapshot, falling back to the post-SF ladder when it is not sealed —
  exactly as C 07.00's col 0215 / C 08.01's col 0255 do (rectification
  R15). The SME / Infrastructure "(-)" supporting-factor adjustment
  columns (0081/0082, 0121/0122) carry Σ(rwa_pre_factor − rwa) over each
  factor's applied subset (the retired asymmetric dedicated flag names —
  sme_supporting_factor_applied / infrastructure_factor_applied — falling
  back to is_sme / is_infrastructure + supporting_factor_applied on the
  sealed ledger, which never carries the dedicated names), so
  0080 + 0081 + 0082 = 0090 and 0110 + 0121 + 0122 = 0125 foot. Under B31
  none of these refs exist (supporting factors are CRR-only), so the change
  is scoped by column presence, not by regime branching.
- The Annex II §1.3 "(-)" negation covers ONLY the CRR supporting-factor
  adjustment columns (0081/0082, 0121/0122), applied by a module post-step
  AFTER execution (a zero deduction normalised to +0.0, null kept null).
  No provision_held fallback ladder on either template; provisions are the
  (unsealed) SCRA/GCRA carriers.
- Lineage-instrumented (R25): ``c09_01_plans`` / ``c09_02_plans`` expose the
  per-COUNTRY execution plans (``TOTAL`` first, then one sheet per sorted country
  key contributed by EITHER basis), sharing ``_c09_01_prepared`` /
  ``_c09_02_prepared`` +
  ``_country_frames`` with the reported generators so a cell's plan and its
  reported value key identically. Both pass ``_C09_NEGATIVE_COLS`` explicitly —
  the first C 09-family sign-aware sweep, so the CRR supporting-factor adjustment
  columns (0081/0082, 0121/0122) reconcile against their legs' positive
  magnitudes. The multi-basis C 09.01 row model drills correctly: an
  IMMEDIATE-obligor cell (0010) runs the APPLIED-class predicate
  (``reporting_class_origin``), the 0020 defaulted MEMO runs the ORIGINAL-class
  predicate (``exposure_class`` + defaulted) and an ULTIMATE-obligor cell
  (0075/0090) runs the post-substitution predicate (``reporting_class``), so on
  a defaulted or a guaranteed leg the three cells of one row drill different
  legs. C 09.02's ``_c09_02_avg_postfix`` is a
  value-dependent GENERATE post-step (an unweighted-mean fallback when a subset's
  total EAD is non-positive) on the reported frame the drill-down reads: it does
  not change a cell's legs (the same subset feeds the WeightedAvg or its
  fallback), and no portfolio subset triggers it today (recorded limitation — the
  ``weighted_avg`` label would understate a fired fallback, but the sign-aware
  sweep does not reconcile a WeightedAvg cell, so it is not that fallback's
  tripwire, unlike C 08.03's sum fallback).

References:
- Regulation (EU) 2021/451, Annex I/II (C 09.01 / C 09.02)
- PRA PS1/26 Annex I/II (OF 09.01 / OF 09.02), §3.4 ¶86/¶87 — the
  immediate-obligor / ultimate-obligor column basis; CRR Art. 112 / Art. 147
- CRR Art. 235 (risk-weight substitution) — what moves the class AND the country
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import polars as pl
from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Formula,
    RowPredicate,
    SafeSum,
    Sum,
    TemplateSpec,
    WeightedAvg,
    execute,
    subset_rows,
)
from rwa_calc.reporting.corep.c07 import c07_population
from rwa_calc.reporting.corep.postpass import negate_deduction_cols, null_empty_rows
from rwa_calc.reporting.corep.templates import (
    C09_01_SA_CLASS_MAP,
    get_c09_01_columns,
    get_c09_01_rows,
    get_c09_02_columns,
    get_c09_02_rows,
)
from rwa_calc.reporting.kernel import TwoBasis, pick, population_flags, sheet_axis, sheet_frame
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.plans import SheetPlan

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    type _PostStep = Callable[[pl.DataFrame, pl.DataFrame], pl.DataFrame]

    from rwa_calc.reporting.cellspec import ValueBinding
    from rwa_calc.reporting.corep.templates import COREPRow

_IRB_APPROACHES: tuple[str, ...] = ("foundation_irb", "advanced_irb", "slotting")

# C 09.02's own two-basis namespace (C 09.01 keys C 07.00's, via c07_population).
# Annex II §3.4 ¶87 splits this template BY COLUMN: "original exposure
# pre-conversion factors" reports at the IMMEDIATE obligor, while "exposure
# value" and "risk-weighted exposure amounts" report at the ULTIMATE obligor —
# which is the origin/post pair under the regulator's own vocabulary, and ¶86
# says so outright ("CRM techniques with substitution effects can change the
# allocation of an exposure to a country").
_C09_BASIS: TwoBasis = TwoBasis("c09")
# C 09.01's population flags, materialised by ``c07_population(both_bases=True)``
# under C 07.00's own namespace — C 09.01 IS a geographical cut of that
# population, so it must read the same two membership flags rather than
# re-deriving them (an SA-guarantor leg whose obligor is IRB is in the POST
# population only, and is exactly what the ¶87 columns exist to report).
_C07_BASIS: TwoBasis = TwoBasis("c07")
# The sealed post-substitution class twin (the ULTIMATE obligor of ¶87).
_POST_CLASS_COL: str = "reporting_class"

# The per-COUNTRY sheet axis, run on the SAME two-basis machinery as the class
# axis (``kernel/bases.py``) — a country IS the sheet key here. ¶86 states it
# outright: "CRM techniques with substitution effects can change the allocation
# of an exposure to a country", so a beneficially guaranteed leg sits on TWO
# country sheets at once (its obligor's for the pre-conversion original
# exposure, its guarantor's for the exposure value and RWEA) exactly as it sits
# on two class sheets. The keys are the sealed ``reporting_country`` twins,
# degrading to the raw ``cp_country_code`` on a frame that seals neither, which
# is what keeps the split number-neutral on a book that never substitutes across
# a border.
_GEO_BASIS: TwoBasis = TwoBasis("c09_geo")
_COUNTRY_ORIGIN_COL: str = "reporting_country_origin"
_COUNTRY_POST_COL: str = "reporting_country"
#: The raw per-exposure country the sealed twins are derived from, and the
#: fallback both keys degrade to on a synthetic frame that seals neither.
_RAW_COUNTRY_COL: str = "cp_country_code"

# C 09.02 row keys that map directly to a single exposure_class value.
_C09_02_DIRECT_EC: frozenset[str] = frozenset(
    {
        "central_govt_central_bank",
        "institution",
        "retail_mortgage",
        "retail_qrre",
        "retail_other",
        "equity",
    }
)

# C 09.02 row keys that always report empty (flags not yet in the pipeline).
_C09_02_EMPTY_KEYS: frozenset[str] = frozenset(
    {"corporate_purchased_receivables", "retail_purchased_receivables"}
)

# The four B31 retail-RE rows: (property_type values, is the SME split).
_C09_02_RE_ROWS: dict[str, tuple[tuple[str, ...], bool]] = {
    "retail_resi_re_sme": (("residential", "rre"), True),
    "retail_resi_re_non_sme": (("residential", "rre"), False),
    "retail_comm_re_sme": (("commercial", "cre"), True),
    "retail_comm_re_non_sme": (("commercial", "cre"), False),
}

_CORPORATE_FAMILY: tuple[str, ...] = ("corporate", "corporate_sme")

# B31 real-estate reporting classes (Art. 124A-124L: under Basel 3.1 real
# estate is a standalone SA exposure class). The SA loan-splitter
# (engine/stages/re_split) reclassifies property-secured non-RE exposures into
# residential_mortgage / commercial_mortgage secured legs; retail residential RE
# keeps the retail_mortgage class. These are the reporting_class_origin /
# exposure_class values that key OF 09.01 "Real estate exposures" row 0090.
_C09_01_RE_CLASSES: tuple[str, ...] = (
    "retail_mortgage",
    "residential_mortgage",
    "commercial_mortgage",
)

# OF 09.01 real-estate "of which" sub-rows (0091-0095): the presence-tolerant
# equals terms narrowing the RE class union. property_type / is_adc / is_sme are
# read raw (a null there correctly excludes the exposure from the sub-row);
# c09_re_qualifying is the derived null->True regulatory flag (see
# ``_c09_01_derived_exprs``). ADC (0094) and the SME "of which" (0095) cross-cut
# the residential/commercial/other partition, mirroring C 07.00's RE memo rows.
_C09_01_RE_ROW_TERMS: dict[str, tuple[tuple[str, str | bool], ...]] = {
    "re_residential": (("property_type", "residential"), ("c09_re_qualifying", True)),
    "re_commercial": (("property_type", "commercial"), ("c09_re_qualifying", True)),
    "re_other": (("c09_re_qualifying", False),),
    "re_adc": (("is_adc", True),),
    "re_sme": (("is_sme", True),),
}

# C 09.01 "of which: SME" sub-rows -> the parent class row whose subset they
# narrow. Annex II / PS1/26 Annex II define every one of them as "Same definition
# as for row 0020 of [OF] CR SA template", so each is its parent row's class
# union conjoined with the SAME SME discriminator C 07.00 row 0020 uses
# (``c09_sme``, see ``_c09_01_derived_exprs``). The retired reverse map had no
# entry mapping ONTO these keys, so all three rendered permanently null
# (v5773_q-v5776_q / boe_b0225-b0227 / v0411_m). ``re_sme`` (B31 row 0095) is NOT
# here: it narrows the real-estate class union and is keyed by the raw ``is_sme``
# borrower flag through ``_C09_01_RE_ROW_TERMS`` — the recorded R7 behaviour,
# mirroring C 07.00's own RE memo rows rather than its row 0020.
_C09_01_SME_PARENT_KEYS: dict[str, str] = {
    "corporate_sme": "corporate",
    "retail_sme": "retail",
    "mortgage_sme": "retail_mortgage",
}

# OF 09.01 SA specialised-lending "of which" sub-rows (0071-0073) keyed by the
# basis-independent sl_type discriminator (Art. 122A). SL money already fans
# into the corporate parent row 0070 via C09_01_SA_CLASS_MAP, so these add only
# object/commodities/project-finance granularity.
_C09_01_SL_TYPE_MAP: dict[str, str] = {
    "sl_object_finance": "object_finance",
    "sl_commodities_finance": "commodities_finance",
    "sl_project_finance": "project_finance",
}

# The CRM decline flag on the sealed ledger (``inject=False``, so it is simply
# absent on a run with no guarantee sub-step), and the derived "does this leg
# still apply its OWN Art. 122B risk weight?" gate it drives.
#
# ``sl_type`` is the OBLIGOR's characteristic and the CRM split never reassigns
# it, so a covered part substituted onto a protection provider's risk weight
# carries the obligor's ``sl_type`` into the post-basis columns. Annex II admits
# an exposure to a specialised-lending "of which" row on THREE conjunctive
# conditions, the third being the applied risk weight ("apply the risk weight
# treatment in accordance with Articles 122B(2)(c) or 122B(4)" — PS1/26 Annex II
# p.89), and ¶43 says the substitution effect "shall reflect the risk weighting
# treatment effectively applicable to the covered part of the exposure". The
# covered part applies the PROVIDER's Art. 122 weight, so it fails that third
# condition and belongs in none of rows 0071-0073. This is C 07.00's own
# ``_SL_OWN_RW_COL`` gate (rows 0021-0026), applied to the geographical twin of
# the rows it protects — the two must agree or the cross-template rules
# (boe_b0975 / boe_b0977) break in whichever direction only one of them moved.
_BENEFICIAL_COL: str = "is_guarantee_beneficial"
_SL_OWN_RW_COL: str = "c09_sl_own_rw"

# COREP Annex II §1.3 "(-)"-labelled deduction columns, negated post-execute:
# the CRR-only SME / Infrastructure supporting-factor adjustment columns on
# C 09.01 (0081/0082) and C 09.02 (0121/0122). Reported negative so the pre-SF
# RWEA plus the two adjustments foots to the post-SF RWEA (identical convention
# to C 07.00's 0216/0217 and C 08.01's 0256/0257). B31 frames carry none of
# these refs, so the negation post-step is an absent-column no-op there.
_C09_NEGATIVE_COLS: frozenset[str] = frozenset({"0081", "0082", "0121", "0122"})

# The "ORIGINAL EXPOSURE PRE-CONVERSION FACTORS" ladder (C 09.01 cols 0010/0020,
# C 09.02 cols 0010/0030). Annex II defines each of them by reference — C 09.01
# col 0010 "Same definition as for column 0010 of CR SA template", C 09.02
# col 0010 "Same definition as for column 0020 of CR IRB template" (PS1/26
# Annex II words OF 09.01 / OF 09.02 identically) — so they bind the SAME sealed
# per-side gross carriers those columns bind. The retired ladder picked
# ``ead_gross``, which is the POST-CCF exposure (drawn + CCF-adjusted undrawn):
# on an off-balance-sheet book that reported the conversion-factor-reduced figure
# in a pre-conversion column and lost the nominal (v5769_q / boe_b0222).
_PRE_CCF_SIDE_COLS: tuple[str, ...] = ("reporting_gross_on_bs", "reporting_gross_off_bs")

# C 09.01 shares C 07.00's population, which includes the counterparty-credit-risk
# legs (Annex II rows 0090-0130) whose per-side carriers are null by design. Their
# original exposure sits in the drawn/undrawn carriers, so col 0010 adds this
# CCR-only term exactly as C 07.00's col 0010 adds ``c07_ccr_gross``. C 09.02
# mirrors C 08.01 col 0020, which carries no such term.
_C09_CCR_GROSS_COL: str = "c09_ccr_gross"

# Raw gross inputs the per-side carriers are derived from. A frame carrying NONE
# of them (a synthetic unit frame handed straight to the generator, which only
# knows ``ead_gross``) gets all-null carriers from ``ensure_gross_side_carriers``,
# so the pre-conversion ladder would report nothing at all there: those frames
# keep the retired single-column pick — a generate-time variant, as the C 09.02
# retail-RE property filter already is.
_RAW_GROSS_INPUTS: tuple[str, ...] = (
    "drawn_amount",
    "interest",
    "nominal_amount",
    "undrawn_amount",
)


class _Row:
    """Minimal TemplateRow for the geo templates."""

    __slots__ = ("name", "ref")

    def __init__(self, ref: str, name: str) -> None:
        self.ref = ref
        self.name = name


def _const(value: float | None):  # noqa: ANN202 - tiny Formula factory
    def fn(_cells: Mapping[str, float | None], _prior: bool) -> float | None:
        return value

    return fn


# =============================================================================
# C 09.01 / OF 09.01 — geographical breakdown, SA
# =============================================================================


def _c09_01_prepared(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> tuple[pl.DataFrame, TemplateSpec, dict[str, RowPredicate | None]] | None:
    """Collect + prepare the C 09.01 population and build its spec once.

    Shared by ``c09_01_plans`` (the lineage plans) and ``generate_c09_01`` (the
    reported frames) so both run the SAME predicate over the SAME prepared frame.
    Returns ``None`` (preserving the generator's error contract) when a required
    column is missing or the C 07.00 population is empty. ``row_preds`` carries
    each row's COMBINED emptiness predicate — the ``_either_pred`` union of the
    immediate-obligor primary, the original-class 0020 memo and the
    ultimate-obligor post predicate — an ``any_of`` union that
    ``SheetPlan.row_terms`` cannot express, so the generate post-passes read it
    from here rather than the plan."""
    if pick(cols, "exposure_class") is None:
        errors.append("C09.01: Missing required column (exposure_class)")
        return None
    if pick(cols, "cp_country_code") is None:
        errors.append(
            "C09.01: Missing cp_country_code column — cannot produce geographical breakdown"
        )
        return None
    sa_df = c07_population(results, cols, both_bases=True).collect()
    if sa_df.height == 0:
        return None
    sa_cols = set(sa_df.columns)
    rwa_col = pick(sa_cols, "rwa_final", "rwa")
    data = sa_df.with_columns(_c09_01_derived_exprs(sa_cols, rwa_col))
    data = data.with_columns(_geo_keys(sa_cols, _C07_BASIS))
    spec, row_preds = _c09_01_spec(set(data.columns), framework, rwa_col)
    return data, spec, row_preds


def c09_01_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-COUNTRY C 09.01 / OF 09.01 execution plans for lineage.

    Keys the per-country plans on the sealed ``reporting_country`` twins
    (``TOTAL`` first, the whole population, then one sheet per sorted country
    contributed by EITHER basis — §3.4 ¶86/¶87) over the SHARED C 07.00
    population on BOTH bases — the standardised book plus BOTH counterparty-
    credit-risk populations (FCCM SFT rows and SA-CCR derivative netting sets),
    admitted by ``risk_type``. Every country plan shares the one framework spec
    (the row-selection differs only by the country frame). Passes
    ``_C09_NEGATIVE_COLS`` EXPLICITLY — the first C 09-family sign-aware sweep, so
    the CRR SME / Infrastructure supporting-factor adjustment columns (0081/0082)
    reconcile against the positive magnitudes their legs contribute."""
    built = _c09_01_prepared(results, cols, framework, errors)
    if built is None:
        return {}
    data, spec, _row_preds = built
    return _country_plans(data, spec)


@cites("PS1/26, paragraph 1.3")
def generate_c09_01(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 09.01 / OF 09.01 per country over the C 07.00 population.

    Shares ``_c09_01_prepared`` + ``_country_frames`` with ``c09_01_plans`` (so a
    cell's reported value and its plan are keyed identically), then applies the
    all-null inert-row pass and the Annex II §1.3 "(-)" negation on each reported
    frame — the drill-down reads a cell's value from HERE, so it honours both."""
    built = _c09_01_prepared(results, cols, framework, errors)
    if built is None:
        return {}
    data, spec, row_preds = built
    return {
        key: _render_sheet(spec, frame, row_preds, post=None)
        for key, frame in _country_frames(data)
    }


def _c09_01_derived_exprs(cols: set[str], rwa_col: str | None) -> list[pl.Expr]:
    """The C 09.01 discriminator columns: the defaulted ladder, the SME flag, the
    RE-family regulatory flag and the CCR original-exposure term.

    ``c09_sme`` is C 07.00's ``c07_sme`` ladder verbatim — the of-which SME rows
    are defined as "Same definition as for row 0020 of CR SA template", so they
    must select exactly the legs that row selects or the cross-template tie-out
    cannot hold. ``c09_re_qualifying`` fills a null ``is_qualifying_re`` to True —
    identical to C 07.00's ``c07_qualifying_re``, so a real-estate exposure with an
    unset qualifying flag counts as regulatory RE (rows 0091/0092) rather than
    "other real estate" (row 0093). property_type / is_adc / is_sme are read raw by
    the RE sub-row predicates (a null there correctly excludes the row).
    ``c09_ccr_gross`` is C 07.00's ``c07_ccr_gross`` verbatim: the original exposure
    of the counterparty-credit-risk / settlement legs, whose per-side gross carriers
    are null by design. Its gate list is EXACTLY the four exposure_types the side
    carriers populate, so col 0010's SafeSum counts every leg on one carrier only.
    """
    exprs: list[pl.Expr] = [
        _defaulted_expr(cols).alias("c09_defaulted"),
        _sme_expr(cols).alias("c09_sme"),
    ]
    if "is_qualifying_re" in cols:
        exprs.append(pl.col("is_qualifying_re").fill_null(value=True).alias("c09_re_qualifying"))
    if _BENEFICIAL_COL in cols:
        # The post-basis specialised-lending gate (see _SL_OWN_RW_COL), read the
        # same null-safe way C 07.00 reads it: an unknown benefit is not a
        # substitution, so the leg keeps applying its own Art. 122B weight.
        exprs.append(
            (pl.col(_BENEFICIAL_COL) == True)  # noqa: E712 - null-safe, see _SL_OWN_RW_COL
            .fill_null(value=False)
            .not_()
            .alias(_SL_OWN_RW_COL)
        )
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
            .alias(_C09_CCR_GROSS_COL)
        )
    exprs.extend(_c09_sf_delta_exprs(cols, rwa_col))
    return exprs


def _c09_01_row_pred(row_def: COREPRow, basis_col: str) -> RowPredicate | None:
    """The reverse-map keying over ``basis_col``: rows whose key is not a
    class-map VALUE and not an RE/SL/SME sub-row key are permanently null
    (the short-term and CIU sub-rows — recorded dead code).

    An "of which: SME" row (0075/0085/0095, ``_C09_01_SME_PARENT_KEYS``) keys its
    PARENT row's class union narrowed by ``c09_sme``: Annex II defines all three
    as "Same definition as for row 0020 of CR SA template", and the narrowing
    term is basis-INDEPENDENT so it survives the two-basis ``_either_pred`` union
    unchanged. The retired reverse map had no entry mapping onto these keys, so
    they rendered permanently null.

    Recorded fix (2026-07-12, Annex II C 09.1 instructions): the PRIMARY
    columns key the APPLIED Art. 112 class (``reporting_class_origin`` —
    "same definition as the CR SA template" columns, so a defaulted SA
    exposure moves to row 0100 exactly as in C 07.00), while the 0020
    "Defaulted exposures" MEMORANDUM keys the raw ORIGINAL class ("where
    the obligors would have been reported if those exposures were not
    assigned to 'exposures in default'")."""
    if row_def.ref == "0170":
        return RowPredicate()
    key = row_def.exposure_class_value
    if key is None:
        return None
    re_sl = _c09_01_re_sl_pred(key, basis_col)
    if re_sl is not None:
        return re_sl
    parent = _C09_01_SME_PARENT_KEYS.get(key)
    classes = sorted(ec for ec, mapped in C09_01_SA_CLASS_MAP.items() if mapped == (parent or key))
    if not classes:
        return None
    union = _class_union(*classes, col=basis_col)
    return union if parent is None else _narrow(union, ("c09_sme", True))


def _post_class_col(cols: set[str]) -> str:
    """The ¶87 ULTIMATE-obligor class key, DEGRADING to the origin twin.

    ``kernel/bases.py::class_keys``'s rule applied to a CELL key rather than a
    sheet key, and it is load-bearing for exactly the reason recorded there: the
    post-basis terms compile to presence-TOLERANT ``equals``, so on a frame that
    seals no ``reporting_class`` a hardcoded name yields an EMPTY subset and
    silently zeroes every exposure-value and RWEA cell on the template. Every
    synthetic unit frame in the COREP estate is such a frame. Degrading instead
    makes those frames report the same class under both bases — the split is
    number-neutral wherever nothing substitutes, which is the whole basis on
    which it is safe to apply it estate-wide.
    """
    return _POST_CLASS_COL if _POST_CLASS_COL in cols else "reporting_class_origin"


def _post_sl_gate(row_def: COREPRow, cols: set[str]) -> tuple[tuple[str, str | bool], ...]:
    """The POST-basis-only narrowing of the specialised-lending rows 0071-0073.

    Those rows key ``sl_type`` alone, which the CRM split leaves on the covered
    part, so on the post basis they would report a leg that has stopped applying
    its own Art. 122B risk weight — see ``_SL_OWN_RW_COL`` for the Annex II
    basis and C 07.00's ``_post_sl_terms`` for the row-0021-0026 twin of this.

    Empty when no substitution gate is sealed: the frame then carries no
    beneficially-substituted leg to exclude, and a presence-tolerant term on an
    underived column would zero the SL rows of every synthetic unit frame.
    """
    key = row_def.exposure_class_value
    sealed = key in _C09_01_SL_TYPE_MAP and _BENEFICIAL_COL in cols
    narrowing: list[tuple[str, str | bool]] = [(_SL_OWN_RW_COL, True)] if sealed else []
    return tuple(narrowing)


def _c09_01_re_sl_pred(key: str, basis_col: str) -> RowPredicate | None:
    """The B31-only real-estate (rows 0090-0095) and SA specialised-lending
    (rows 0071-0073) predicates — the retired reverse-map short-circuited these
    keys to permanently null (recorded dead code, rectification R7). Returns
    None for every non-RE/SL key so the caller falls through to the reverse map;
    CRR row keys never reach an RE/SL key, so CRR C 09.01 is untouched.

    - ``real_estate`` (0090): the RE class union over ``basis_col`` (applied
      basis for the primary columns, original basis for the 0020 memo).
    - ``re_residential`` / ``re_commercial`` (0091/0092): regulatory RE narrowed
      by property_type + the qualifying flag.
    - ``re_other`` (0093): non-regulatory RE (is_qualifying_re explicitly False).
    - ``re_adc`` (0094) / ``re_sme`` (0095): the ADC and SME "of which".
    - ``sl_*`` (0071-0073): SA specialised lending by sl_type."""
    if key in _C09_01_SL_TYPE_MAP:
        return RowPredicate(equals=(("sl_type", _C09_01_SL_TYPE_MAP[key]),))
    if key != "real_estate" and key not in _C09_01_RE_ROW_TERMS:
        return None
    re_union = _class_union(*_C09_01_RE_CLASSES, col=basis_col)
    if key == "real_estate":
        return re_union
    return _narrow(re_union, *_C09_01_RE_ROW_TERMS[key])


def _c09_01_spec(
    cols: set[str], framework: str, rwa_col: str | None
) -> tuple[TemplateSpec, dict[str, RowPredicate | None]]:
    column_refs = tuple(col.ref for col in get_c09_01_columns(framework))
    row_defs = get_c09_01_rows(framework)
    gross_pre_ccf = _pre_ccf_gross_binding(cols, with_ccr=True)
    ead_col = pick(cols, "ead_final")
    # Pre-SF RWEA snapshot (col 0080); falls back to the post-SF ladder (rwa_col,
    # resolved once in the generate call) when the aggregator did not seal it
    # (mirrors C 07.00 col 0215 / C 08.01 col 0255).
    rwa_pre_col = "rwa_pre_factor" if "rwa_pre_factor" in cols else rwa_col
    rows = tuple(_Row(row_def.ref, row_def.name) for row_def in row_defs)
    row_preds: dict[str, RowPredicate | None] = {}
    cells: dict[tuple[str, str], CellSpec] = {}
    origin_terms = _basis_terms(_C07_BASIS.pop_origin, _GEO_BASIS.basis_origin)
    post_terms = _basis_terms(_C07_BASIS.pop_post, _GEO_BASIS.basis_post)
    for row_def in row_defs:
        # Annex II §3.4 ¶87 splits this template BY COLUMN, so each row carries
        # TWO class predicates plus the 0020 memo's third. ``pred`` is the
        # IMMEDIATE obligor (origin class over the origin population, on the
        # obligor's country sheet) for the pre-conversion original exposure and
        # the provisions columns; ``post_pred`` is the ULTIMATE obligor (the
        # sealed post-substitution class over the post population, on the
        # guarantor's country sheet) for the exposure value and the RWEA.
        #
        # EVERY predicate carries its OWN population and country flags. Widening
        # the frame to both populations without that per-ROW discrimination is
        # the measured failure mode: an origin-keyed cell silently absorbs the
        # post-only legs (a prototype inflated col 0010 by 61% and broke the
        # row-0170 total by 4,900,000 that way).
        pred = _narrow_opt(_c09_01_row_pred(row_def, "reporting_class_origin"), *origin_terms)
        # 0020 memo: the raw ORIGINAL class + defaulted (the counterfactual
        # "would have been" row of the instruction) — an ORIGIN-basis column,
        # so it takes the origin population and the obligor's country.
        memo_pred = _narrow_opt(_c09_01_row_pred(row_def, "exposure_class"), *origin_terms)
        post_pred = _narrow_opt(
            _c09_01_row_pred(row_def, _post_class_col(cols)),
            *post_terms,
            *_post_sl_gate(row_def, cols),
        )
        # The all-null post-pass counts the UNION of all three: keyed on the
        # origin basis alone it nulls the very rows the post columns exist to
        # publish (an inflow-only sheet — CGCB here — has no origin-basis leg at
        # all, yet must report the exposure value and RWEA that arrived on it).
        row_preds[row_def.ref] = _either_pred(_either_pred(pred, memo_pred), post_pred)
        if pred is None or post_pred is None:
            continue
        ref = row_def.ref
        cells[(ref, "0010")] = _bind_or_null(gross_pre_ccf, pred)
        if gross_pre_ccf is not None and memo_pred is not None:
            # The 0020 memo is "Original exposure pre-conversion factors for those
            # exposures which have been classified as exposures in default", so it
            # reads the SAME pre-conversion ladder as col 0010 over the ORIGINAL
            # class + defaulted subset.
            cells[(ref, "0020")] = CellSpec(
                gross_pre_ccf,
                predicate=_conjoin(memo_pred, ("c09_defaulted", True)),
            )
        cells[(ref, "0050")] = CellSpec(Sum("gcra_provision_amount"), predicate=pred)
        cells[(ref, "0055")] = CellSpec(Sum("scra_provision_amount"), predicate=pred)
        for null_ref in ("0040", "0060", "0061", "0070"):
            cells[(ref, null_ref)] = CellSpec(Formula(refs=(), fn=_const(None)))
        # ¶87 ULTIMATE-obligor columns: the exposure value (0075) and the RWEA
        # (0080/0090), plus the CRR supporting-factor adjustments that must foot
        # 0080 + 0081 + 0082 = 0090. These are the columns v5746_q-v5772_q /
        # boe_b0191-b0224 tie to C 07.00's own post-substitution cols
        # 0200/0215/0220, so leaving them on the origin basis asserted that the
        # covered part had left the obligor's class on one template and stayed
        # on the other.
        cells[(ref, "0075")] = _sum_or_null(ead_col, post_pred)
        if "0080" in column_refs:
            cells[(ref, "0080")] = _sum_or_null(rwa_pre_col, post_pred)
            cells[(ref, "0081")] = _c09_sf_adjustment_cell(
                post_pred, cols, "sme_supporting_factor_applied", "is_sme"
            )
            cells[(ref, "0082")] = _c09_sf_adjustment_cell(
                post_pred, cols, "infrastructure_factor_applied", "is_infrastructure"
            )
        cells[(ref, "0090")] = _sum_or_null(rwa_col, post_pred)
    spec = TemplateSpec(
        name="c09_01", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
    )
    return spec, row_preds


# =============================================================================
# C 09.02 / OF 09.02 — geographical breakdown, IRB
# =============================================================================


def _c09_02_prepared(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> tuple[pl.DataFrame, TemplateSpec, dict[str, RowPredicate | None]] | None:
    """Collect + prepare the C 09.02 IRB book and build its spec once.

    Shared by ``c09_02_plans`` and ``generate_c09_02``. Returns ``None``
    (preserving the error contract) when a required column is missing or the IRB
    population is empty. Keys the sealed ``reporting_class_origin`` /
    ``reporting_class`` pair and the ``reporting_country`` pair over the
    ``reporting_approach_origin`` / ``reporting_approach`` IRB books INCLUDING
    slotting (slotting stays IN the population). The spec is built cols-aware
    from the ORIGINAL sealed set (derived discriminators are bound by name for
    the executor)."""
    if pick(cols, "exposure_class") is None:
        errors.append("C09.02: Missing required column (exposure_class)")
        return None
    if pick(cols, "cp_country_code") is None:
        errors.append(
            "C09.02: Missing cp_country_code column — cannot produce geographical breakdown"
        )
        return None
    irb_df = _irb_population(results, cols).collect()
    if irb_df.height == 0:
        return None
    approach_col = pick(cols, "reporting_approach_origin", "approach")
    rwa_col = pick(cols, "rwa_final", "rwa")
    data = _c09_02_prepare(irb_df, cols, approach_col, rwa_col)
    data = data.with_columns(_geo_keys(set(irb_df.columns), _C09_BASIS))
    spec, row_preds = _c09_02_spec(cols, framework, approach_col, rwa_col)
    return data, spec, row_preds


def c09_02_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-COUNTRY C 09.02 / OF 09.02 execution plans for lineage.

    Keys the per-country plans on the sealed ``reporting_country`` twins
    (``TOTAL`` first, then one sheet per sorted country contributed by EITHER
    basis — §3.4 ¶86/¶87) over the IRB book (F-IRB / A-IRB / slotting
    — slotting stays IN the population). Passes ``_C09_NEGATIVE_COLS`` explicitly
    so the CRR supporting-factor adjustment columns (0121/0122) reconcile with the
    sign convention. The value-dependent unweighted-mean fallback (see
    ``_c09_02_avg_postfix``) is a GENERATE post-step on the reported frame the
    drill-down reads; it does not change a cell's contributing legs (the same
    subset feeds either the EAD-weighted average or its fallback), and on this
    portfolio no country/class subset carries legs with a non-positive total EAD,
    so the fallback never fires and the reported average IS the declared
    WeightedAvg (recorded limitation: if a future book made a subset's total EAD
    non-positive, the drill-down's ``weighted_avg`` label would understate that
    the rendered value became an unweighted mean — the LEGS stay correct, and the
    sign-aware sweep does not reconcile a WeightedAvg cell, so it is not the
    tripwire it is for the C 08.03 sum fallback)."""
    built = _c09_02_prepared(results, cols, framework, errors)
    if built is None:
        return {}
    data, spec, _row_preds = built
    return _country_plans(data, spec)


@cites("PS1/26, paragraph 1.3")
def generate_c09_02(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute C 09.02 / OF 09.02 per country over the IRB book
    (F-IRB / A-IRB / slotting — slotting stays IN the population).

    Shares ``_c09_02_prepared`` + ``_country_frames`` with ``c09_02_plans``, then
    applies the all-null inert-row pass, the value-dependent unweighted-mean
    fallback (``_c09_02_avg_postfix``) and the Annex II §1.3 "(-)" negation on each
    reported frame — the drill-down reads a cell's value from HERE."""
    built = _c09_02_prepared(results, cols, framework, errors)
    if built is None:
        return {}
    data, spec, row_preds = built
    ead_col = pick(cols, "ead_final")
    pd_col = pick(cols, "pd_floored", "pd")
    lgd_col = pick(cols, "lgd_post_crm")

    def post(frame: pl.DataFrame, country_df: pl.DataFrame) -> pl.DataFrame:
        return _c09_02_avg_postfix(
            frame, country_df, row_preds, ead_col=ead_col, pd_col=pd_col, lgd_col=lgd_col
        )

    return {
        key: _render_sheet(spec, frame, row_preds, post=post)
        for key, frame in _country_frames(data)
    }


def _irb_population(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    """The IRB book on BOTH bases, tagged (mirrors ``c08.py::_irb_population``).

    Returns the UNION of the origin-approach IRB book and the post-substitution
    one, with ``c09_pop_origin`` / ``c09_pop_post`` recording which each leg is
    in. A leg with no substitution is in both, which is why the split is
    number-neutral on a book that never substitutes.

    The post book is a SUBSET of the origin one here, exactly as on C 08.01:
    ``aggregator._post_crm_approach_expr`` maps an SA guarantor to the SA literal
    and everything else to the obligor's own approach, so an IRB-origin leg can
    only LEAVE the IRB population post-substitution and an SA-origin leg can
    never enter it. So the union IS the origin book, and the flags do the work.
    """
    tagged = results.with_columns(population_flags(_C09_BASIS, cols, _IRB_APPROACHES))
    return tagged.filter(pl.col(_C09_BASIS.pop_origin) | pl.col(_C09_BASIS.pop_post))


def _c09_02_prepare(
    data: pl.DataFrame, cols: set[str], approach_col: str | None, rwa_col: str | None
) -> pl.DataFrame:
    """Derive the C 09.02 discriminators. Null semantics are load-bearing:
    the retired ``!= True`` filters DROP null-flag rows (no fill), while
    the non-SME anti-join KEEPS rows with no SME indicator (fill to
    False before negating)."""
    exprs: list[pl.Expr] = [_defaulted_expr(cols).alias("c09_defaulted")]
    if "sme_supporting_factor_eligible" in cols:
        sme = (pl.col("sme_supporting_factor_eligible") == True).fill_null(value=False)  # noqa: E712
    else:
        sme = pl.col("exposure_class").str.contains("sme").fill_null(value=False)
    exprs.append(sme.alias("c09_sme"))
    # The retired _filter_non_sme is an exposure_reference anti-join; with no
    # reference column it returns the base UNCHANGED (SME rows included).
    non_sme = sme.not_() if "exposure_reference" in cols else pl.lit(value=True)
    exprs.append(non_sme.alias("c09_non_sme"))
    if "sme_supporting_factor_eligible" in cols:
        corp_non_sme = pl.col("sme_supporting_factor_eligible") != True  # noqa: E712
    else:
        corp_non_sme = pl.col("exposure_class").str.contains("sme").not_()
    if "cp_apply_fi_scalar" in cols:
        corp_non_sme = corp_non_sme & (pl.col("cp_apply_fi_scalar") != True)  # noqa: E712
    exprs.append(corp_non_sme.alias("c09_corp_non_sme"))
    if approach_col is not None:
        exprs.append((pl.col(approach_col) == "slotting").alias("c09_slotting"))
    exprs.extend(_c09_sf_delta_exprs(cols, rwa_col))
    return data.with_columns(exprs)


def _c09_02_row_pred(  # noqa: PLR0911 - the retired branch cascade, one return per row family
    row_def: COREPRow, cols: set[str], approach_col: str | None, basis_col: str
) -> RowPredicate | None:
    """The retired _filter_c09_02_row branch cascade as predicates.

    ``basis_col`` is the class column the row keys on — the ORIGIN twin for the
    original-exposure and provisions columns, the POST twin for exposure value
    and RWEA (Annex II §3.4 ¶87). Every class term routes through it, so the two
    bases cannot drift apart in one branch of the cascade.
    """
    if row_def.ref == "0150":
        return RowPredicate()
    key = row_def.exposure_class_value
    if key is None or key in _C09_02_EMPTY_KEYS:
        return None
    if key in _C09_02_DIRECT_EC:
        return RowPredicate(equals=((basis_col, key),))
    if key == "corporate":
        return _class_union(*_CORPORATE_FAMILY, "specialised_lending", col=basis_col)
    if key == "sl_excl_slotting":
        terms: tuple[tuple[str, str | bool], ...] = ((basis_col, "specialised_lending"),)
        if approach_col is not None:
            terms = (*terms, ("c09_slotting", False))
        return RowPredicate(equals=terms)
    if key == "sl_slotting":
        if approach_col is None:
            return None
        return RowPredicate(equals=((basis_col, "specialised_lending"), ("c09_slotting", True)))
    if key == "corporate_sme":
        return _conjoin(_class_union(*_CORPORATE_FAMILY, col=basis_col), ("c09_sme", True))
    if key == "corporate_fse_large":
        return _conjoin(
            _class_union(*_CORPORATE_FAMILY, col=basis_col), ("cp_apply_fi_scalar", True)
        )
    if key == "corporate_non_sme":
        return _conjoin(_class_union(*_CORPORATE_FAMILY, col=basis_col), ("c09_corp_non_sme", True))
    if key == "retail":
        return _class_union("retail_mortgage", "retail_qrre", "retail_other", col=basis_col)
    if key in ("retail_mortgage_sme", "retail_mortgage_non_sme"):
        flag = "c09_sme" if key == "retail_mortgage_sme" else "c09_non_sme"
        return RowPredicate(equals=((basis_col, "retail_mortgage"), (flag, True)))
    if key in ("retail_other_sme", "retail_other_non_sme"):
        flag = "c09_sme" if key == "retail_other_sme" else "c09_non_sme"
        return RowPredicate(equals=((basis_col, "retail_other"), (flag, True)))
    if key in _C09_02_RE_ROWS:
        ptypes, is_sme = _C09_02_RE_ROWS[key]
        terms = (
            (basis_col, "retail_mortgage"),
            ("c09_sme" if is_sme else "c09_non_sme", True),
        )
        # The retired code skips the property filter when the column is
        # absent (the whole mortgage base stays in) — generate-time variant.
        if "property_type" in cols:
            limbs = tuple(RowPredicate(equals=(("property_type", ptype),)) for ptype in ptypes)
            return RowPredicate(equals=terms, any_of=limbs)
        return RowPredicate(equals=terms)
    return None


def _c09_02_spec(
    cols: set[str], framework: str, approach_col: str | None, rwa_col: str | None
) -> tuple[TemplateSpec, dict[str, RowPredicate | None]]:
    column_refs = tuple(col.ref for col in get_c09_02_columns(framework))
    row_defs = get_c09_02_rows(framework)
    # Col 0010 is "Same definition as for column 0020 of CR IRB template", which
    # binds the two per-side gross carriers and NO counterparty-credit-risk term
    # (C 08.x discloses CCR separately) — so C 09.02's does not carry one either.
    gross_pre_ccf = _pre_ccf_gross_binding(cols, with_ccr=False)
    ead_col = pick(cols, "ead_final")
    # rwa_col (deliberately two-wide) is resolved once in the generate call.
    # Pre-SF RWEA snapshot (col 0110); falls back to the post-SF ladder when the
    # aggregator did not seal it (mirrors C 07.00 col 0215 / C 08.01 col 0255).
    rwa_pre_col = "rwa_pre_factor" if "rwa_pre_factor" in cols else rwa_col
    pd_col = pick(cols, "pd_floored", "pd")
    lgd_col = pick(cols, "lgd_post_crm")
    rows = tuple(_Row(row_def.ref, row_def.name) for row_def in row_defs)
    row_preds: dict[str, RowPredicate | None] = {}
    cells: dict[tuple[str, str], CellSpec] = {}
    for row_def in row_defs:
        # Annex II §3.4 ¶87 splits this template by COLUMN, so each row carries
        # TWO predicates. ``pred`` is the IMMEDIATE obligor (origin class, origin
        # population) for the original-exposure and provisions columns;
        # ``post_pred`` is the ULTIMATE obligor (post class, post population) for
        # exposure value and RWEA. Each is narrowed to its own population, or a
        # leg that left the IRB book post-substitution would leak into the
        # origin-keyed columns — the C 09.01 prototype measured that leak at a
        # 61% inflation of the original-exposure column. Each also carries its
        # own COUNTRY basis (¶86: substitution changes the allocation of an
        # exposure to a country), so a cross-border guarantee moves the exposure
        # value and RWEA onto the guarantor's sheet while the original exposure
        # stays on the obligor's.
        pred = _narrow_opt(
            _c09_02_row_pred(row_def, cols, approach_col, "reporting_class_origin"),
            *_basis_terms(_C09_BASIS.pop_origin, _GEO_BASIS.basis_origin),
        )
        post_pred = _narrow_opt(
            _c09_02_row_pred(row_def, cols, approach_col, _post_class_col(cols)),
            *_basis_terms(_C09_BASIS.pop_post, _GEO_BASIS.basis_post),
        )
        # The all-null post-pass must count the UNION: keying it on the origin
        # basis alone nulls the very rows the post columns exist to populate.
        row_preds[row_def.ref] = _either_pred(pred, post_pred)
        if pred is None or post_pred is None:
            continue
        ref = row_def.ref
        def_pred = _conjoin(pred, ("c09_defaulted", True))
        post_def_pred = _conjoin(post_pred, ("c09_defaulted", True))
        cells[(ref, "0010")] = _bind_or_null(gross_pre_ccf, pred)
        if gross_pre_ccf is not None:
            # 0030 "Of which defaulted" is the ORIGINAL exposure value of the
            # defaulted subset — the same pre-conversion ladder as col 0010.
            cells[(ref, "0030")] = CellSpec(gross_pre_ccf, predicate=def_pred)
        for null_ref in ("0040", "0060", "0070"):
            cells[(ref, null_ref)] = CellSpec(Formula(refs=(), fn=_const(None)))
        cells[(ref, "0050")] = CellSpec(Sum("gcra_provision_amount"), predicate=pred)
        cells[(ref, "0055")] = CellSpec(Sum("scra_provision_amount"), predicate=pred)
        cells[(ref, "0080")] = _wavg_or_null(pd_col, ead_col, pred)
        cells[(ref, "0090")] = _wavg_or_null(lgd_col, ead_col, pred)
        cells[(ref, "0100")] = _wavg_or_null(lgd_col, ead_col, def_pred)
        # ¶87 ULTIMATE-obligor columns: exposure value and RWEA, plus the CRR
        # supporting-factor adjustments that must foot against 0125. The PD/LGD
        # averages (0080/0090/0100) and expected loss (0130) stay on the
        # IMMEDIATE obligor — ¶87 names only the two quantities below, and a
        # risk parameter is a property of the obligor whose book the row is.
        cells[(ref, "0105")] = _sum_or_null(ead_col, post_pred)
        if "0107" in column_refs and ead_col is not None:
            cells[(ref, "0107")] = CellSpec(Sum(ead_col), predicate=post_def_pred)
        if "0110" in column_refs:
            cells[(ref, "0110")] = _sum_or_null(rwa_pre_col, post_pred)
        if rwa_col is not None:
            cells[(ref, "0120")] = CellSpec(Sum(rwa_col), predicate=post_def_pred)
        if "0121" in column_refs:
            cells[(ref, "0121")] = _c09_sf_adjustment_cell(
                post_pred, cols, "sme_supporting_factor_applied", "is_sme"
            )
            cells[(ref, "0122")] = _c09_sf_adjustment_cell(
                post_pred, cols, "infrastructure_factor_applied", "is_infrastructure"
            )
        cells[(ref, "0125")] = _sum_or_null(rwa_col, post_pred)
        cells[(ref, "0130")] = CellSpec(Sum("expected_loss"), predicate=pred)
    spec = TemplateSpec(
        name="c09_02", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
    )
    return spec, row_preds


def _c09_02_avg_postfix(
    frame: pl.DataFrame,
    country_df: pl.DataFrame,
    row_preds: Mapping[str, RowPredicate | None],
    *,
    ead_col: str | None,
    pd_col: str | None,
    lgd_col: str | None,
) -> pl.DataFrame:
    """The retired _weighted_avg_or_mean fallback: an UNWEIGHTED mean of
    non-null values when the subset's total EAD weight is <= 0 (the
    WeightedAvg verb has no such fallback — value-dependent post-step)."""
    if pd_col is None and lgd_col is None:
        return frame
    overrides: dict[str, dict[str, float | None]] = {}
    live_preds = {ref: pred for ref, pred in row_preds.items() if pred is not None}
    row_subsets = subset_rows(country_df, live_preds)
    for ref, subset in row_subsets.items():
        if subset.height == 0:
            continue
        fixes: dict[str, float | None] = {}
        ead_sum = float(subset[ead_col].fill_null(0.0).sum()) if ead_col else 0.0
        if ead_col is None or ead_sum <= 0.0:
            if pd_col is not None:
                fixes["0080"] = _mean_or_none(subset[pd_col])
            if lgd_col is not None:
                fixes["0090"] = _mean_or_none(subset[lgd_col])
        if lgd_col is not None:
            defaulted = subset.filter(pl.col("c09_defaulted"))
            if defaulted.height > 0:
                def_sum = float(defaulted[ead_col].fill_null(0.0).sum()) if ead_col else 0.0
                if ead_col is None or def_sum <= 0.0:
                    fixes["0100"] = _mean_or_none(defaulted[lgd_col])
        if fixes:
            overrides[ref] = {k: v for k, v in fixes.items() if k in frame.columns}
    return _apply_overrides(frame, overrides)


# =============================================================================
# Shared helpers (population split, predicates, post-steps)
# =============================================================================


def _geo_keys(cols: set[str], population: TwoBasis) -> list[pl.Expr]:
    """The per-COUNTRY sheet keys, on the template's own population flags.

    Materialises ``_GEO_BASIS`` — the country axis expressed in the same
    ``TwoBasis`` vocabulary the class axis uses, so ``sheet_axis`` /
    ``sheet_frame`` partition countries with no second implementation. The two
    "class" keys are the sealed ``reporting_country`` twins and the two
    population flags are ALIASES of the template's own (C 07.00's for C 09.01,
    C 09.02's for itself), so a leg is on a country sheet only if it is in that
    basis's population to begin with.

    Both keys degrade to the raw ``cp_country_code`` on a frame that seals no
    country twin (every synthetic unit frame in the COREP estate), which reports
    the same country under both bases instead of emptying the ¶87 columns — the
    same degradation rule ``kernel/bases.py::class_keys`` applies to the class
    key, and for the same reason.
    """
    origin_col = _COUNTRY_ORIGIN_COL if _COUNTRY_ORIGIN_COL in cols else _RAW_COUNTRY_COL
    post_col = _COUNTRY_POST_COL if _COUNTRY_POST_COL in cols else origin_col
    return [
        pl.col(population.pop_origin).alias(_GEO_BASIS.pop_origin),
        pl.col(population.pop_post).alias(_GEO_BASIS.pop_post),
        pl.col(origin_col).alias(_GEO_BASIS.class_origin),
        pl.col(post_col).alias(_GEO_BASIS.class_post),
    ]


def _country_frames(data: pl.DataFrame) -> list[tuple[str, pl.DataFrame]]:
    """The per-country (key, frame) split, each frame tagged with its two bases.

    ``TOTAL`` first — the whole population, null-country rows included, both
    geographical flags True because every leg is in the all-geographies total on
    the basis it belongs to (its population flag still discriminates). Then one
    frame per sorted distinct country key contributed by EITHER basis, carrying
    the legs on that country under either and tagging which — so the guarantor's
    sheet gains the exposure value and RWEA of a leg whose original exposure
    stays reported on the obligor's.

    Shared by the plans builder and the reported generator so a cell's plan and
    its reported value are keyed identically.
    """
    total = data.with_columns(
        pl.lit(value=True).alias(_GEO_BASIS.basis_origin),
        pl.lit(value=True).alias(_GEO_BASIS.basis_post),
    )
    frames: list[tuple[str, pl.DataFrame]] = [("TOTAL", total)]
    frames.extend(
        (country, sheet_frame(_GEO_BASIS, data, country))
        for country in sorted(sheet_axis(_GEO_BASIS, data))
    )
    return frames


def _country_plans(data: pl.DataFrame, spec: TemplateSpec) -> dict[str, SheetPlan]:
    """One ``SheetPlan`` per country over the shared framework spec. Every plan
    carries ``_C09_NEGATIVE_COLS`` so the drill-down's sign-aware reconciliation
    covers the CRR supporting-factor adjustment columns (0081/0082, 0121/0122)."""
    return {
        key: SheetPlan(
            spec=spec,
            frame=frame,
            ctx=ReportingContext(),
            negative_cols=_C09_NEGATIVE_COLS,
        )
        for key, frame in _country_frames(data)
    }


def _render_sheet(
    spec: TemplateSpec,
    country_df: pl.DataFrame,
    row_preds: dict[str, RowPredicate | None],
    *,
    post: _PostStep | None,
) -> pl.DataFrame:
    """Execute one country sheet and apply its post-``execute`` passes: the
    all-null inert/empty rows, an optional value-dependent ``post`` step
    (C 09.02's unweighted-mean fallback), and the Annex II §1.3 "(-)" negation."""
    frame = execute(spec, country_df)
    frame = null_empty_rows(frame, country_df, row_preds)
    if post is not None:
        frame = post(frame, country_df)
    return negate_deduction_cols(frame, _C09_NEGATIVE_COLS)


def _class_union(*classes: str, col: str = "reporting_class_origin") -> RowPredicate:
    if len(classes) == 1:
        return RowPredicate(equals=((col, classes[0]),))
    return RowPredicate(any_of=tuple(RowPredicate(equals=((col, ec),)) for ec in classes))


def _either_pred(primary: RowPredicate | None, memo: RowPredicate | None) -> RowPredicate | None:
    """The row-emptiness basis: a row is null only when EVERY basis it publishes
    a column on has an empty subset — a class row whose only exposures defaulted
    keeps its 0020 memo while the primary columns move to row 0100, and an
    inflow-only sheet's row keeps the exposure value and RWEA that arrived on it
    while having no origin-basis leg at all.

    This is a true DISJUNCTION, computed by distributing each operand's shared
    ``equals`` into its own ``any_of`` limbs (``RowPredicate`` forbids nesting an
    ``any_of`` inside a limb, so a flat union is the only representable form).
    Keeping one operand's ``equals`` at the top — the shape this had while both
    operands were origin-basis and their ``equals`` therefore identical — silently
    imposes the FIRST basis's population and country flags on the second's limbs,
    which is precisely how the two-basis prototype nulled the row it had just
    populated. An RE sub-row's basis-INDEPENDENT discriminators (property_type /
    qualifying / ADC / SME) ride along inside every distributed limb, so a
    residential sub-row still cannot be un-nulled by commercial RE.

    An operand with no terms at all constrains nothing, so its union with
    anything constrains nothing either (returned as the constraint-free
    predicate, never as the other operand)."""
    if primary is None:
        return memo
    if memo is None:
        return primary
    if not _is_constrained(primary) or not _is_constrained(memo):
        return RowPredicate()
    limbs = [*_flat_limbs(primary), *_flat_limbs(memo)]
    return limbs[0] if len(limbs) == 1 else RowPredicate(any_of=tuple(limbs))


def _is_constrained(pred: RowPredicate) -> bool:
    """Does this predicate select a strict subset? (The Total rows do not.)"""
    return bool(pred.equals or pred.any_of)


def _flat_limbs(pred: RowPredicate) -> list[RowPredicate]:
    """``pred`` as a list of pure-conjunction limbs whose union is ``pred``.

    Only the two fields the C 09 predicates ever populate (``equals`` /
    ``any_of``) are carried — the sealed-column fields are unused on this
    template, which keys its classes through presence-tolerant ``equals`` terms
    so the two-basis class column can vary per cell."""
    if not pred.any_of:
        return [pred]
    return [RowPredicate(equals=(*pred.equals, *limb.equals)) for limb in pred.any_of]


def _conjoin(pred: RowPredicate, term: tuple[str, str | bool]) -> RowPredicate:
    return RowPredicate(equals=(*pred.equals, term), any_of=pred.any_of)


def _narrow(pred: RowPredicate, *terms: tuple[str, str | bool]) -> RowPredicate:
    """Conjoin extra presence-tolerant equals terms onto a (possibly
    class-union) predicate, preserving its any_of limbs (the variadic
    ``_conjoin`` used by the RE sub-row predicates)."""
    return RowPredicate(equals=(*pred.equals, *terms), any_of=pred.any_of)


def _narrow_opt(pred: RowPredicate | None, *terms: tuple[str, str | bool]) -> RowPredicate | None:
    """``_narrow`` for a predicate the row cascade may decline to build."""
    return None if pred is None else _narrow(pred, *terms)


def _basis_terms(population: str, geography: str) -> tuple[tuple[str, str | bool], ...]:
    """The two flags that pin one cell to ONE basis: the template's population
    membership on that basis, and the country sheet it keys on that basis.

    Both are derived Boolean columns and both are always materialised on the
    frames the executor sees, so they are read through the presence-TOLERANT
    ``equals`` channel like every other derived discriminator here."""
    return ((population, True), (geography, True))


def _sum_or_null(col: str | None, pred: RowPredicate) -> CellSpec:
    if col is None:
        return CellSpec(Formula(refs=(), fn=_const(None)))
    return CellSpec(Sum(col), predicate=pred)


def _bind_or_null(binding: ValueBinding | None, pred: RowPredicate) -> CellSpec:
    """``_sum_or_null`` for an already-resolved binding (the pre-conversion gross
    ladder, which is a SafeSum over carriers rather than a single column)."""
    if binding is None:
        return CellSpec(Formula(refs=(), fn=_const(None)))
    return CellSpec(binding, predicate=pred)


def _wavg_or_null(col: str | None, weight: str | None, pred: RowPredicate) -> CellSpec:
    if col is None or weight is None:
        return CellSpec(Formula(refs=(), fn=_const(None)))
    return CellSpec(WeightedAvg(col, weight=weight), predicate=pred, empty_cell="null")


def _c09_sf_delta_exprs(cols: set[str], rwa_col: str | None) -> list[pl.Expr]:
    """The CRR supporting-factor RWEA delta (rwa_pre_factor − post-SF RWEA, per
    leg), derived only when ``rwa_pre_factor`` is sealed — the geo twin of
    C 07.00's ``c07_sf_delta`` and C 08.01's ``c08_sf_delta``. The subtrahend is
    the SAME resolved post-SF carrier the 0090/0125 cells bind (``rwa_col``,
    threaded from the generate call), so a row's 0080/0110 (pre) minus the delta
    over its applied subset foots to its 0090/0125 (post). Absent when there is
    no pre-factor snapshot (a synthetic frame or a B31 run), which leaves the
    "(-)" adjustment cells structurally null."""
    if "rwa_pre_factor" not in cols or rwa_col is None:
        return []
    return [
        (pl.col("rwa_pre_factor").fill_null(0.0) - pl.col(rwa_col).fill_null(0.0)).alias(
            "c09_sf_delta"
        )
    ]


def _c09_sf_adjustment_cell(
    pred: RowPredicate, cols: set[str], dedicated: str, flag_col: str
) -> CellSpec:
    """A CRR "(-)" supporting-factor adjustment cell: Σ ``c09_sf_delta`` over the
    row's applied subset, negated post-execute. Mirrors C 07.00 / C 08.01's
    ``_sf_adjustment_cell`` verbatim, including the retired asymmetric dedicated
    flag names (``sme_supporting_factor_applied`` vs
    ``infrastructure_factor_applied``). Those dedicated names are not on the
    sealed ledger, so on a real run the fallback fires: the factor's own
    ``is_sme`` / ``is_infrastructure`` flag conjoined with the generic
    ``supporting_factor_applied``. Returns the structural-null Formula when no
    pre-factor snapshot exists (the adjustment cannot be computed)."""
    if "rwa_pre_factor" not in cols:
        return CellSpec(Formula(refs=(), fn=_const(None)))
    if dedicated in cols:
        return CellSpec(Sum("c09_sf_delta"), predicate=_conjoin(pred, (dedicated, True)))
    if flag_col in cols and "supporting_factor_applied" in cols:
        return CellSpec(
            Sum("c09_sf_delta"),
            predicate=_narrow(pred, (flag_col, True), ("supporting_factor_applied", True)),
        )
    return CellSpec(Formula(refs=(), fn=_const(None)))


def _pre_ccf_gross_binding(cols: set[str], *, with_ccr: bool) -> ValueBinding | None:
    """The "original exposure pre-conversion factors" binding for cols 0010/0020
    (C 09.01) and 0010/0030 (C 09.02).

    On a sealed frame this is the per-side gross SafeSum the referenced column of
    C 07.00 (col 0010, ``with_ccr=True``) / C 08.01 (col 0020, ``with_ccr=False``)
    binds. ``ensure_gross_side_carriers`` guarantees the two side columns exist at
    generator entry, but on a synthetic frame that carries no RAW gross input at
    all they are structurally all-null, so such a frame keeps the retired
    single-column ``ead_gross`` pick (which is post-CCF, and the only gross figure
    those frames carry). Returns None when neither basis exists."""
    if any(name in cols for name in _RAW_GROSS_INPUTS):
        side = (*_PRE_CCF_SIDE_COLS, _C09_CCR_GROSS_COL) if with_ccr else _PRE_CCF_SIDE_COLS
        return SafeSum(side)
    ead_gross_col = pick(cols, "ead_gross", "nominal_amount", "drawn_amount")
    return None if ead_gross_col is None else Sum(ead_gross_col)


def _sme_expr(cols: set[str]) -> pl.Expr:
    """C 07.00's ``c07_sme`` ladder: the SME discriminator its row 0020 selects on,
    which the C 09.01 of-which SME rows are defined by reference to. Nulls fold to
    False so the flag is a non-null Boolean the ``equals`` terms can match (a null
    ``sme_supporting_factor_eligible`` never matched ``== True`` either)."""
    if "sme_supporting_factor_eligible" in cols:
        return (pl.col("sme_supporting_factor_eligible") == True).fill_null(value=False)  # noqa: E712
    if "exposure_class" in cols:
        return pl.col("exposure_class").str.contains("sme").fill_null(value=False)
    return pl.lit(value=False)


def _defaulted_expr(cols: set[str]) -> pl.Expr:
    """The retired _filter_defaulted ladder as a Boolean expression."""
    if "is_defaulted" in cols:
        return pl.col("is_defaulted").fill_null(value=False)
    if "default_status" in cols:
        return pl.col("default_status") == True  # noqa: E712
    class_col = "exposure_class_applied" if "exposure_class_applied" in cols else "exposure_class"
    if class_col in cols:
        return pl.col(class_col) == "defaulted"
    if "pd_floored" in cols:
        return pl.col("pd_floored") >= 1.0
    return pl.lit(value=False)


def _apply_overrides(
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


def _mean_or_none(series: pl.Series) -> float | None:
    vals = series.drop_nulls()
    return float(cast("float", vals.mean())) if len(vals) > 0 else None
