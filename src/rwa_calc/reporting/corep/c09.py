"""
COREP C 09.01 / C 09.02 — geographical breakdown of exposures, declarative.

Pipeline position:
    sealed aggregator-exit ledger -> per-template population + derived
    discriminators -> ONE TemplateSpec per framework -> cellspec.execute()
    per country sheet -> dict["TOTAL" | ISO code, DataFrame]

Cell semantics (recorded decisions, this slice):

- C 09.01's PRIMARY columns key the APPLIED Art. 112 class
  (``reporting_class_origin`` — recorded fix 2026-07-12: the Annex II
  instructions define them "same as the CR SA template", so a defaulted
  SA exposure moves to row 0100 exactly as C 07.00 assigns it), while the
  0020 "Defaulted exposures" MEMORANDUM keys the raw ORIGINAL class (the
  instruction's counterfactual "would have been" row) — a two-basis
  template like Pillar 3 CR4. C 09.02 keys the sealed
  ``reporting_class_origin`` (== raw ``exposure_class`` for the IRB
  book — number-neutral convergence; the IRB template has no default
  row by design) over the ``reporting_approach_origin`` population.
  Under B31 the RE reporting classes (retail_mortgage /
  residential_mortgage / commercial_mortgage — the Art. 124A standalone
  RE class plus the loan-splitter's secured legs) key the "Real estate
  exposures" row 0090 and its regulatory-RRE / regulatory-CRE / other-RE
  / ADC / SME "of which" sub-rows (0091-0095); the SA specialised-lending
  "of which" sub-rows (0071-0073) key sl_type (rectification R7).
- C 09.01 shares C 07.00's population (``c07_population`` — the SA book
  plus BOTH counterparty-credit-risk populations: FCCM SFT synthetic rows
  and SA-CCR derivative netting sets, admitted by ``risk_type``). That
  shared population is why the Basel 3.1 institution row is now populated:
  the derivative netting sets used to be dropped by the
  ``standardised_ccr`` output-floor relabel and never reached either
  template. C 09.02 is the IRB book INCLUDING slotting (the retired inline
  comment claiming exclusion was misleading).
- The reverse-map row keying handles the plain class rows: a row whose key
  is not a ``C09_01_SA_CLASS_MAP`` value AND not an RE/SL key renders
  ALL-NULL (the corporate_sme / retail_sme / mortgage_sme, short-term and
  CIU sub-rows stay permanently null — recorded dead code, out of R7
  scope; the RE-SME row 0095 IS implemented); the corporate rows fan in
  corporate + corporate_sme + specialised_lending; retail fans in
  retail_other (+ retail_qrre / retail_mortgage per template). The B31-only
  RE rows (0090-0095) and SA specialised-lending rows (0071-0073) bypass
  the reverse map via ``_c09_01_re_sl_pred`` (rectification R7): these keys
  never occur in CRR_C09_01_ROWS, so CRR C 09.01 is untouched.
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
- Column ladders are the retired ones, narrower than C 07/C 08: gross =
  pick(ead_gross, nominal_amount, drawn_amount) (a single column, never a
  SafeSum); the POST-SF RWEA = pick(rwa_final, rwa) (NO rwa_post_factor).
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
  per-COUNTRY execution plans (``TOTAL`` first, then one sheet per sorted non-null
  ``cp_country_code``), sharing ``_c09_01_prepared`` / ``_c09_02_prepared`` +
  ``_country_frames`` with the reported generators so a cell's plan and its
  reported value key identically. Both pass ``_C09_NEGATIVE_COLS`` explicitly —
  the first C 09-family sign-aware sweep, so the CRR supporting-factor adjustment
  columns (0081/0082, 0121/0122) reconcile against their legs' positive
  magnitudes. The two-basis C 09.01 row model drills correctly: a PRIMARY cell
  (e.g. 0010/0090) runs the APPLIED-class predicate (``reporting_class_origin``)
  while the 0020 defaulted MEMO runs the ORIGINAL-class predicate
  (``exposure_class`` + defaulted), so on a defaulted leg whose applied class
  moved the two cells drill different legs. C 09.02's ``_c09_02_avg_postfix`` is a
  value-dependent GENERATE post-step (an unweighted-mean fallback when a subset's
  total EAD is non-positive) on the reported frame the drill-down reads: it does
  not change a cell's legs (the same subset feeds the WeightedAvg or its
  fallback), and no portfolio subset triggers it today (recorded limitation — the
  ``weighted_avg`` label would understate a fired fallback, but the sign-aware
  sweep does not reconcile a WeightedAvg cell, so it is not that fallback's
  tripwire, unlike C 08.03's sum fallback).

References:
- Regulation (EU) 2021/451, Annex I/II (C 09.01 / C 09.02)
- PRA PS1/26 Annex I/II (OF 09.01 / OF 09.02); CRR Art. 112 / Art. 147
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
    Sum,
    TemplateSpec,
    WeightedAvg,
    execute,
    matched_counts,
    subset_rows,
)
from rwa_calc.reporting.corep.c07 import c07_population
from rwa_calc.reporting.corep.templates import (
    C09_01_SA_CLASS_MAP,
    get_c09_01_columns,
    get_c09_01_rows,
    get_c09_02_columns,
    get_c09_02_rows,
)
from rwa_calc.reporting.kernel import pick
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.plans import SheetPlan

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    type _PostStep = Callable[[pl.DataFrame, pl.DataFrame], pl.DataFrame]

    from rwa_calc.reporting.corep.templates import COREPRow

_IRB_APPROACHES: tuple[str, ...] = ("foundation_irb", "advanced_irb", "slotting")

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

# OF 09.01 SA specialised-lending "of which" sub-rows (0071-0073) keyed by the
# basis-independent sl_type discriminator (Art. 122A). SL money already fans
# into the corporate parent row 0070 via C09_01_SA_CLASS_MAP, so these add only
# object/commodities/project-finance granularity.
_C09_01_SL_TYPE_MAP: dict[str, str] = {
    "sl_object_finance": "object_finance",
    "sl_commodities_finance": "commodities_finance",
    "sl_project_finance": "project_finance",
}

# COREP Annex II §1.3 "(-)"-labelled deduction columns, negated post-execute:
# the CRR-only SME / Infrastructure supporting-factor adjustment columns on
# C 09.01 (0081/0082) and C 09.02 (0121/0122). Reported negative so the pre-SF
# RWEA plus the two adjustments foots to the post-SF RWEA (identical convention
# to C 07.00's 0216/0217 and C 08.01's 0256/0257). B31 frames carry none of
# these refs, so the negation post-step is an absent-column no-op there.
_C09_NEGATIVE_COLS: frozenset[str] = frozenset({"0081", "0082", "0121", "0122"})


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
    each row's COMBINED two-basis emptiness predicate (the ``_either_pred`` of the
    applied-class primary and the original-class 0020 memo) — an ``any_of`` union
    that ``SheetPlan.row_terms`` cannot express, so the generate post-passes read
    it from here rather than the plan."""
    if pick(cols, "exposure_class") is None:
        errors.append("C09.01: Missing required column (exposure_class)")
        return None
    if pick(cols, "cp_country_code") is None:
        errors.append(
            "C09.01: Missing cp_country_code column — cannot produce geographical breakdown"
        )
        return None
    sa_df = c07_population(results, cols).collect()
    if sa_df.height == 0:
        return None
    sa_cols = set(sa_df.columns)
    rwa_col = pick(sa_cols, "rwa_final", "rwa")
    data = sa_df.with_columns(_c09_01_derived_exprs(sa_cols, rwa_col))
    spec, row_preds = _c09_01_spec(set(data.columns), framework, rwa_col)
    return data, spec, row_preds


def c09_01_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-COUNTRY C 09.01 / OF 09.01 execution plans for lineage.

    Keys the per-country plans on the sealed ``cp_country_code`` (``TOTAL`` first,
    the whole population, then one sheet per sorted non-null country) over the
    SHARED C 07.00 population — the standardised book plus BOTH counterparty-
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
    """The C 09.01 discriminator columns: the defaulted ladder plus the RE-family
    regulatory flag. ``c09_re_qualifying`` fills a null ``is_qualifying_re`` to
    True — identical to C 07.00's ``c07_qualifying_re``, so a real-estate exposure
    with an unset qualifying flag counts as regulatory RE (rows 0091/0092) rather
    than "other real estate" (row 0093). property_type / is_adc / is_sme are read
    raw by the RE sub-row predicates (a null there correctly excludes the row)."""
    exprs: list[pl.Expr] = [_defaulted_expr(cols).alias("c09_defaulted")]
    if "is_qualifying_re" in cols:
        exprs.append(pl.col("is_qualifying_re").fill_null(value=True).alias("c09_re_qualifying"))
    exprs.extend(_c09_sf_delta_exprs(cols, rwa_col))
    return exprs


def _c09_01_row_pred(row_def: COREPRow, basis_col: str) -> RowPredicate | None:
    """The reverse-map keying over ``basis_col``: rows whose key is not a
    class-map VALUE are permanently null (the map short-circuits before
    the SME / RE / SL / CIU sub-filters ever run — recorded dead code).

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
    classes = sorted(ec for ec, mapped in C09_01_SA_CLASS_MAP.items() if mapped == key)
    if not classes:
        return None
    return _class_union(*classes, col=basis_col)


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
    ead_gross_col = pick(cols, "ead_gross", "nominal_amount", "drawn_amount")
    ead_col = pick(cols, "ead_final")
    # Pre-SF RWEA snapshot (col 0080); falls back to the post-SF ladder (rwa_col,
    # resolved once in the generate call) when the aggregator did not seal it
    # (mirrors C 07.00 col 0215 / C 08.01 col 0255).
    rwa_pre_col = "rwa_pre_factor" if "rwa_pre_factor" in cols else rwa_col
    rows = tuple(_Row(row_def.ref, row_def.name) for row_def in row_defs)
    row_preds: dict[str, RowPredicate | None] = {}
    cells: dict[tuple[str, str], CellSpec] = {}
    for row_def in row_defs:
        # Primary columns: the APPLIED Art. 112 class (the sealed obligor
        # applied ladder — defaulted exposures sit in row 0100, as C 07.00).
        pred = _c09_01_row_pred(row_def, "reporting_class_origin")
        # 0020 memo: the raw ORIGINAL class + defaulted (the counterfactual
        # "would have been" row of the instruction).
        memo_pred = _c09_01_row_pred(row_def, "exposure_class")
        row_preds[row_def.ref] = _either_pred(pred, memo_pred)
        if pred is None:
            continue
        ref = row_def.ref
        cells[(ref, "0010")] = _sum_or_null(ead_gross_col, pred)
        if ead_gross_col is not None and memo_pred is not None:
            cells[(ref, "0020")] = CellSpec(
                Sum(ead_gross_col),
                predicate=_conjoin(memo_pred, ("c09_defaulted", True)),
            )
        cells[(ref, "0050")] = CellSpec(Sum("gcra_provision_amount"), predicate=pred)
        cells[(ref, "0055")] = CellSpec(Sum("scra_provision_amount"), predicate=pred)
        for null_ref in ("0040", "0060", "0061", "0070"):
            cells[(ref, null_ref)] = CellSpec(Formula(refs=(), fn=_const(None)))
        cells[(ref, "0075")] = _sum_or_null(ead_col, pred)
        if "0080" in column_refs:
            cells[(ref, "0080")] = _sum_or_null(rwa_pre_col, pred)
            cells[(ref, "0081")] = _c09_sf_adjustment_cell(
                pred, cols, "sme_supporting_factor_applied", "is_sme"
            )
            cells[(ref, "0082")] = _c09_sf_adjustment_cell(
                pred, cols, "infrastructure_factor_applied", "is_infrastructure"
            )
        cells[(ref, "0090")] = _sum_or_null(rwa_col, pred)
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
    population is empty. Keys the sealed ``reporting_class_origin`` over the
    ``reporting_approach_origin`` IRB book INCLUDING slotting (slotting stays IN
    the population). The spec is built cols-aware from the ORIGINAL sealed set
    (derived discriminators are bound by name for the executor)."""
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
    spec, row_preds = _c09_02_spec(cols, framework, approach_col, rwa_col)
    return data, spec, row_preds


def c09_02_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the per-COUNTRY C 09.02 / OF 09.02 execution plans for lineage.

    Keys the per-country plans on ``cp_country_code`` (``TOTAL`` first, then one
    sheet per sorted non-null country) over the IRB book (F-IRB / A-IRB / slotting
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
    """The retired _filter_by_irb_approach: keyed to approach_applied only."""
    if "reporting_approach_origin" not in cols:
        return results.filter(pl.lit(value=False))
    return results.filter(pl.col("reporting_approach_origin").is_in(list(_IRB_APPROACHES)))


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
    row_def: COREPRow, cols: set[str], approach_col: str | None
) -> RowPredicate | None:
    """The retired _filter_c09_02_row branch cascade as predicates."""
    if row_def.ref == "0150":
        return RowPredicate()
    key = row_def.exposure_class_value
    if key is None or key in _C09_02_EMPTY_KEYS:
        return None
    if key in _C09_02_DIRECT_EC:
        return RowPredicate(equals=(("reporting_class_origin", key),))
    if key == "corporate":
        return _class_union(*_CORPORATE_FAMILY, "specialised_lending")
    if key == "sl_excl_slotting":
        terms: tuple[tuple[str, str | bool], ...] = (
            ("reporting_class_origin", "specialised_lending"),
        )
        if approach_col is not None:
            terms = (*terms, ("c09_slotting", False))
        return RowPredicate(equals=terms)
    if key == "sl_slotting":
        if approach_col is None:
            return None
        return RowPredicate(
            equals=(("reporting_class_origin", "specialised_lending"), ("c09_slotting", True))
        )
    if key == "corporate_sme":
        return _conjoin(_class_union(*_CORPORATE_FAMILY), ("c09_sme", True))
    if key == "corporate_fse_large":
        return _conjoin(_class_union(*_CORPORATE_FAMILY), ("cp_apply_fi_scalar", True))
    if key == "corporate_non_sme":
        return _conjoin(_class_union(*_CORPORATE_FAMILY), ("c09_corp_non_sme", True))
    if key == "retail":
        return _class_union("retail_mortgage", "retail_qrre", "retail_other")
    if key in ("retail_mortgage_sme", "retail_mortgage_non_sme"):
        flag = "c09_sme" if key == "retail_mortgage_sme" else "c09_non_sme"
        return RowPredicate(equals=(("reporting_class_origin", "retail_mortgage"), (flag, True)))
    if key in ("retail_other_sme", "retail_other_non_sme"):
        flag = "c09_sme" if key == "retail_other_sme" else "c09_non_sme"
        return RowPredicate(equals=(("reporting_class_origin", "retail_other"), (flag, True)))
    if key in _C09_02_RE_ROWS:
        ptypes, is_sme = _C09_02_RE_ROWS[key]
        terms = (
            ("reporting_class_origin", "retail_mortgage"),
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
    ead_gross_col = pick(cols, "ead_gross", "nominal_amount", "drawn_amount")
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
        pred = _c09_02_row_pred(row_def, cols, approach_col)
        row_preds[row_def.ref] = pred
        if pred is None:
            continue
        ref = row_def.ref
        def_pred = _conjoin(pred, ("c09_defaulted", True))
        cells[(ref, "0010")] = _sum_or_null(ead_gross_col, pred)
        if ead_gross_col is not None:
            cells[(ref, "0030")] = CellSpec(Sum(ead_gross_col), predicate=def_pred)
        for null_ref in ("0040", "0060", "0070"):
            cells[(ref, null_ref)] = CellSpec(Formula(refs=(), fn=_const(None)))
        cells[(ref, "0050")] = CellSpec(Sum("gcra_provision_amount"), predicate=pred)
        cells[(ref, "0055")] = CellSpec(Sum("scra_provision_amount"), predicate=pred)
        cells[(ref, "0080")] = _wavg_or_null(pd_col, ead_col, pred)
        cells[(ref, "0090")] = _wavg_or_null(lgd_col, ead_col, pred)
        cells[(ref, "0100")] = _wavg_or_null(lgd_col, ead_col, def_pred)
        cells[(ref, "0105")] = _sum_or_null(ead_col, pred)
        if "0107" in column_refs and ead_col is not None:
            cells[(ref, "0107")] = CellSpec(Sum(ead_col), predicate=def_pred)
        if "0110" in column_refs:
            cells[(ref, "0110")] = _sum_or_null(rwa_pre_col, pred)
        if rwa_col is not None:
            cells[(ref, "0120")] = CellSpec(Sum(rwa_col), predicate=def_pred)
        if "0121" in column_refs:
            cells[(ref, "0121")] = _c09_sf_adjustment_cell(
                pred, cols, "sme_supporting_factor_applied", "is_sme"
            )
            cells[(ref, "0122")] = _c09_sf_adjustment_cell(
                pred, cols, "infrastructure_factor_applied", "is_infrastructure"
            )
        cells[(ref, "0125")] = _sum_or_null(rwa_col, pred)
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


def _country_frames(data: pl.DataFrame) -> list[tuple[str, pl.DataFrame]]:
    """The per-country (key, frame) split: TOTAL first (the whole population,
    null-country rows included), then one frame per sorted distinct non-null
    cp_country_code. Shared by the plans builder and the reported generator so a
    cell's plan and its reported value are keyed identically."""
    frames: list[tuple[str, pl.DataFrame]] = [("TOTAL", data)]
    countries = (
        data.select(pl.col("cp_country_code"))
        .filter(pl.col("cp_country_code").is_not_null())
        .unique()
        .sort("cp_country_code")
        .to_series()
        .to_list()
    )
    frames.extend(
        (country, data.filter(pl.col("cp_country_code") == country)) for country in countries
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
    frame = _null_empty_rows(frame, country_df, row_preds)
    if post is not None:
        frame = post(frame, country_df)
    return _negate_deduction_cols(frame)


def _class_union(*classes: str, col: str = "reporting_class_origin") -> RowPredicate:
    if len(classes) == 1:
        return RowPredicate(equals=((col, classes[0]),))
    return RowPredicate(any_of=tuple(RowPredicate(equals=((col, ec),)) for ec in classes))


def _either_pred(primary: RowPredicate | None, memo: RowPredicate | None) -> RowPredicate | None:
    """The row-emptiness basis for C 09.01: a row is null only when BOTH
    its primary (applied-class) and memo (original-class) subsets are
    empty — a class row whose only exposures defaulted keeps its 0020
    memo while the primary columns move to row 0100.

    An RE sub-row carries a basis-KEYED class union (any_of over
    reporting_class_origin vs exposure_class) alongside basis-INDEPENDENT
    discriminator terms (property_type / qualifying / ADC / SME in equals).
    Those discriminators are shared across the two bases, so the combined
    emptiness predicate keeps them (equals) and unions only the class limbs
    (any_of) — dropping the discriminators here would wrongly un-null a
    residential sub-row whenever any commercial RE existed."""
    if primary is None:
        return memo
    if memo is None:
        return primary
    if primary.equals and (primary.any_of or memo.any_of):
        return RowPredicate(equals=primary.equals, any_of=(*primary.any_of, *memo.any_of))
    limbs: list[RowPredicate] = []
    for pred in (primary, memo):
        if pred.any_of:
            limbs.extend(pred.any_of)
        elif pred.equals:
            limbs.append(RowPredicate(equals=pred.equals))
    if not limbs:
        return RowPredicate()
    return RowPredicate(any_of=tuple(limbs))


def _conjoin(pred: RowPredicate, term: tuple[str, str | bool]) -> RowPredicate:
    return RowPredicate(equals=(*pred.equals, term), any_of=pred.any_of)


def _narrow(pred: RowPredicate, *terms: tuple[str, str | bool]) -> RowPredicate:
    """Conjoin extra presence-tolerant equals terms onto a (possibly
    class-union) predicate, preserving its any_of limbs (the variadic
    ``_conjoin`` used by the RE sub-row predicates)."""
    return RowPredicate(equals=(*pred.equals, *terms), any_of=pred.any_of)


def _sum_or_null(col: str | None, pred: RowPredicate) -> CellSpec:
    if col is None:
        return CellSpec(Formula(refs=(), fn=_const(None)))
    return CellSpec(Sum(col), predicate=pred)


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


def _null_empty_rows(
    frame: pl.DataFrame,
    country_df: pl.DataFrame,
    row_preds: Mapping[str, RowPredicate | None],
) -> pl.DataFrame:
    """Render dead rows (no predicate) and empty class subsets ALL-NULL —
    the Total row (no equals/any_of terms) is never nulled."""
    constrained = {
        ref: pred
        for ref, pred in row_preds.items()
        if pred is not None and (pred.equals or pred.any_of)
    }
    counts = matched_counts(country_df, constrained)
    null_refs = [
        ref
        for ref, pred in row_preds.items()
        if pred is None or ((pred.equals or pred.any_of) and counts[ref] == 0)
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


def _negate_deduction_cols(frame: pl.DataFrame) -> pl.DataFrame:
    """COREP Annex II §1.3: emit the CRR "(-)"-labelled supporting-factor
    adjustment columns as negative figures (after the pre/post pair captured the
    positive magnitudes). Intersected with the frame's columns, so it is an
    absent-column no-op on B31 sheets. Identical expression to C 07.00 /
    C 08.01's negation pass: a zero deduction is normalised to +0.0, null stays
    null."""
    targets = [col for col in frame.columns if col in _C09_NEGATIVE_COLS]
    if not targets:
        return frame
    return frame.with_columns(_negate_expr(col) for col in targets)


def _negate_expr(col: str) -> pl.Expr:
    """Negate a "(-)"-labelled deduction column, normalising a zero to +0.0.

    Plain ``-pl.col(col)`` flips the IEEE sign bit, so a ``0.0`` cell would
    serialise as ``-0.0``; the explicit zero branch keeps a zero deduction as
    ``+0.0``. Null stays null."""
    return pl.when(pl.col(col) == 0.0).then(pl.lit(0.0)).otherwise(-pl.col(col)).alias(col)
